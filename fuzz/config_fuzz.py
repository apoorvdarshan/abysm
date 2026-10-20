#!/usr/bin/env python3
"""Fuzz the store-release config loader with ABYSM's store/store-release.toml.

    python3 -I fuzz/config_fuzz.py [libFuzzer flags] [corpus dir]

Every release and Store checks job starts by loading store/store-release.toml
(store_release.config.load_for_app) and binding the abysm flow and the shared
modules to it (store_release.context.configure). What it accepts decides which
files the jobs check out, which project they build and which tags they release.
Inputs start from ABYSM's real config: arbitrary bytes, byte edits of the file,
and edits of its tables (keys removed or added, values of every TOML type, unsafe
paths and templates). Properties:

- ABYSM's own config loads, selects the abysm flow and passes every check below;
- loading raises nothing but ConfigError, and configure raises nothing but
  ConfigError for a config the loader accepted;
- once configured for the abysm flow, every path its modules and the release notes
  reader are bound to (module constants and function defaults) lies inside the
  app checkout, and none is left unconfigured;
- the tag prefix is ([a-z]+-)*v, the bundle id a reverse-DNS name and the App
  Store Connect app id digits, exactly as the config says; every gate job is a
  workflow of the app repository itself;
- each job's sparse-checkout patterns start with the config, and are rooted, one
  line each, without NUL or a '..' segment; the GitHub Release title renders.
"""
from __future__ import annotations

import copy
import datetime
import itertools
import re
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402  (puts the pinned store-release checkout on sys.path)

import atheris  # noqa: E402

with atheris.instrument_imports(include=["store_release"]):
    from store_release import config, context, paths, release_notes
    from store_release.flows import UNCONFIGURED_ROOT, UNCONFIGURED_TEXT, rebind
    from store_release.flows.abysm import asc_release, export_listing, ios_release, validate_catalog

FLOW_MODULES = (asc_release, ios_release, export_listing, validate_catalog)
PLACEHOLDER_NAMES = {"UNCONFIGURED_ROOT", "UNCONFIGURED_TEXT"}
TAG_PREFIX = re.compile(r"(?:[a-z]+-)*v")
BUNDLE_ID = re.compile(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
LOCAL_WORKFLOW = re.compile(r"\./\.github/workflows/[A-Za-z0-9._-]+\.ya?ml")
ENVIRON = {"GITHUB_WORKFLOW_REF": "apoorvdarshan/abysm/.github/workflows/ios-release.yml@refs/tags/v1.1",
           "GITHUB_REPOSITORY": "apoorvdarshan/abysm"}

SOURCE = harness.CONFIG_FILE.read_bytes()
BASE = tomllib.loads(SOURCE.decode("utf-8"))
WORK = harness.scratch("config")
# load_for_app reads <app>/store/store-release.toml, as every job does.
LOAD_ROOT = WORK / "app"
(LOAD_ROOT / "store").mkdir(parents=True)
CONFIG_FILE = LOAD_ROOT / harness.CONFIG_PATH
# Each configure gets a new app root, so a constant left over from an earlier
# configuration points outside it and is caught.
ROOTS = (WORK / f"checkout-{n}" for n in itertools.count())

TRICKY = ("", ".", "..", "/", "//", "../x", "x/..", "x/../y", "./x", "x/./y", "x//y", "/abs", "!/x", "!x", "/x/",
          "/x ", " /x", "x\\y", "x\x00y", "x\ny", "x\ry", "x\u2028y", "~/x", "*", "**/x", "x/*.png", "/../x",
          "!/../x", "{version}", "{build}", "{tag}", "{build_suffix}", "{}", "{0}", "{version!r}", "{version:>9}",
          "{version.real}", "{version[0]}", "{{", "}}", "{", "}", "x" * 300, "\xe9/\xfc", "C:\\x", "true", "1", "NO",
          "YES", "v", "ios-v", "V", "v1", "-v", "com.apoorvdarshan.Abysm", "com..x", "Abysm", "abysm", "scowld",
          "fud-ai", "APP_IPHONE_67", "WATCH", "/Applications/Xcode_27.app/Contents/Developer",
          "/Applications/Xcode-beta.app", "./.github/workflows/ios-tests.yml", "../.github/workflows/x.yml",
          "owner/repo/.github/workflows/x.yml@v1", "store/metadata/ios", "store/metadata/x", "store/../ios")
PATH_TRICKS = ("../x", "../../etc/passwd", "x/../../y", "store/../../x", "/abs", "/", ".", "..", "./x", "x//y",
               "x/./y", "~/x", "x\\..\\y", "x\x00", "x\n", "store/metadata/../../../ios", "../store/metadata/ios",
               "Abysm.xcodeproj/..", "../Abysm.xcodeproj", "/Abysm.xcodeproj")
TOKENS = (b"\n", b"=", b"[", b"]", b"[[", b"]]", b"\"", b"'", b"\"\"\"", b",", b"{", b"}", b".", b"#", b"..",
          b"/", b"\\", b"\x00", b"\xff", b"true", b"1", b"ios", b"flow", b"path", b"tag_prefix", b"\"../x\"")


def key_names() -> list[str]:
    names: set[str] = {"unknown", "", "schema ", "flow", "path", "dir", "uses", "source_archive"}

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                names.add(key)
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(BASE)
    return sorted(names)


KEYS = key_names()


def bound_paths(value: object, depth: int = 0):
    if isinstance(value, Path):
        yield value
    elif isinstance(value, (tuple, list, set, frozenset)) and depth < 4:
        for item in value:
            yield from bound_paths(item, depth + 1)
    elif isinstance(value, dict) and depth < 4:
        for key, item in value.items():
            yield from bound_paths(key, depth + 1)
            yield from bound_paths(item, depth + 1)


def check_inside(root: Path, label: str, path: Path) -> None:
    resolved = path.resolve()
    assert resolved == root or root in resolved.parents, f"{label} = {path} is outside the app checkout {root}"


def check_configured(parsed: config.Config, root: Path) -> None:
    """What the jobs rely on once the CLI has configured the abysm flow for this config."""
    ios = parsed.ios
    for module in FLOW_MODULES:
        name = module.__name__.rsplit(".", 1)[-1]
        left = [item for item in rebind.unconfigured_values(module, (UNCONFIGURED_ROOT, UNCONFIGURED_TEXT))
                if item not in PLACEHOLDER_NAMES]
        assert not left, f"{name} still unconfigured: {left}"
        for attr, value in vars(module).items():
            if attr.startswith("__") or attr in PLACEHOLDER_NAMES:
                continue
            if callable(value) and getattr(value, "__module__", None) == module.__name__:
                value = (getattr(value, "__defaults__", None) or ()) + tuple(
                    (getattr(value, "__kwdefaults__", None) or {}).values())
            for path in bound_paths(value):
                check_inside(root, f"{name}.{attr}", path)
    check_inside(root, "release_notes", release_notes.ROOT / release_notes.NOTES_RELPATH)
    assert TAG_PREFIX.fullmatch(ios.tag_prefix) and ios_release.TAG_PREFIX == ios.tag_prefix, \
        f"tag prefix {ios.tag_prefix!r} (flow: {ios_release.TAG_PREFIX!r})"
    assert BUNDLE_ID.fullmatch(ios.bundle_id) and ios_release.BUNDLE_ID == ios.bundle_id, \
        f"bundle id {ios.bundle_id!r} (flow: {ios_release.BUNDLE_ID!r})"
    assert ios.asc_app_id.isascii() and ios.asc_app_id.isdigit(), f"App Store Connect app id {ios.asc_app_id!r}"
    assert ios_release.APP_STORE_APP_ID == ios.asc_app_id == asc_release.APP_STORE_APP_ID, \
        f"App Store Connect app id {ios.asc_app_id!r} bound as {ios_release.APP_STORE_APP_ID!r}"
    for job in ios.gate_jobs:
        assert LOCAL_WORKFLOW.fullmatch(job.uses), f"gate job {job.id} runs {job.uses!r}"


def check_patterns(parsed: config.Config) -> None:
    for job in paths.JOBS:
        if job.startswith("android-") and parsed.android is None:
            continue
        try:
            lines = paths.patterns(parsed, job, config_path=harness.CONFIG_PATH, environ=ENVIRON)
        except config.ConfigError:
            continue
        assert lines and lines[0] == f"/{harness.CONFIG_PATH}", f"{job} checks out {lines!r}"
        for line in lines:
            assert line.startswith(("/", "!/")), f"{job}: unrooted pattern {line!r}"
            assert not any(ch in line for ch in "\n\r\x00"), f"{job}: pattern {line!r} spans lines"
            assert ".." not in line.lstrip("!").split("/"), f"{job}: pattern {line!r} leaves the checkout"


def check_accepted(parsed: config.Config) -> None:
    if parsed.ios is not None:
        config.render_template(parsed.ios.title, **{name: "1" for name in config.IOS_TITLE_PLACEHOLDERS})
    check_patterns(parsed)
    root = next(ROOTS)
    try:
        context.configure(parsed, root, config_path=harness.CONFIG_PATH)
    except config.ConfigError:
        return
    if parsed.ios is not None and parsed.ios.flow == "abysm":
        check_configured(parsed, root.resolve())


def new_value(fdp: atheris.FuzzedDataProvider, old: object, depth: int = 0) -> object:
    kind = fdp.ConsumeIntInRange(0, 12)
    if kind == 0:
        return harness.pick(fdp, TRICKY)
    if kind == 1:
        return fdp.ConsumeUnicodeNoSurrogates(fdp.ConsumeIntInRange(0, 20))
    if kind == 2 and isinstance(old, str):
        fragment = harness.pick(fdp, TRICKY)
        return fragment + old if fdp.ConsumeBool() else old + fragment
    if kind == 3:
        return harness.pick(fdp, (0, 1, -1, 2, 10, 2**63 - 1, -(2**63)))
    if kind == 4:
        return harness.pick(fdp, (0.0, 1.5, float("inf"), float("nan")))
    if kind == 5:
        return fdp.ConsumeBool()
    if kind == 6:
        return harness.pick(fdp, (datetime.date(2026, 10, 21), datetime.time(3, 53),
                                  datetime.datetime(2026, 10, 21, 3, 53)))
    if kind == 7 and depth < 2:
        return [new_value(fdp, None, depth + 1) for _ in range(fdp.ConsumeIntInRange(0, 3))]
    if kind == 8 and depth < 2:
        return {harness.pick(fdp, KEYS): new_value(fdp, None, depth + 1) for _ in range(fdp.ConsumeIntInRange(0, 2))}
    if kind == 9:
        return [harness.pick(fdp, TRICKY) for _ in range(fdp.ConsumeIntInRange(0, 3))]
    if kind == 10 and isinstance(old, list):
        return old + [copy.deepcopy(harness.pick(fdp, old))] if old else []
    if kind == 11 and isinstance(old, str):
        return harness.pick(fdp, PATH_TRICKS)
    return harness.pick(fdp, TRICKY)


def slots_of(data: dict) -> tuple[list[tuple[dict | list, object]], list[dict | list]]:
    slots: list[tuple[dict | list, object]] = []
    containers: list[dict | list] = [data]

    def walk(node: object) -> None:
        items = node.items() if isinstance(node, dict) else enumerate(node) if isinstance(node, list) else ()
        for key, value in list(items):
            slots.append((node, key))
            if isinstance(value, (dict, list)):
                containers.append(value)
            walk(value)
    walk(data)
    return slots, containers


def mutate(fdp: atheris.FuzzedDataProvider, data: dict) -> None:
    slots, containers = slots_of(data)
    strings = [(c, k) for c, k in slots if isinstance(c[k], str) and ("/" in c[k] or "." in c[k])]  # type: ignore[index]
    operation = fdp.ConsumeIntInRange(0, 4)
    if not slots or (operation == 2 and not strings):
        operation = 3
    if operation == 0:
        container, key = harness.pick(fdp, slots)
        del container[key]  # type: ignore[arg-type]
    elif operation == 1:
        container, key = harness.pick(fdp, slots)
        container[key] = new_value(fdp, container[key])  # type: ignore[index]
    elif operation == 2:
        # Point one path-like string (it has a '/' or a '.') somewhere unsafe.
        container, key = harness.pick(fdp, strings)
        container[key] = harness.pick(fdp, PATH_TRICKS)  # type: ignore[index]
    else:
        target = harness.pick(fdp, containers)
        if isinstance(target, dict):
            target[harness.pick(fdp, KEYS)] = new_value(fdp, None)
        else:
            target.append(new_value(fdp, None))


def edit_bytes(fdp: atheris.FuzzedDataProvider) -> bytes:
    data = bytearray(SOURCE)
    for _ in range(fdp.ConsumeIntInRange(1, 4)):
        at = fdp.ConsumeIntInRange(0, len(data))
        piece = harness.pick(fdp, TOKENS) if fdp.ConsumeBool() else fdp.ConsumeBytes(fdp.ConsumeIntInRange(0, 8))
        cut = fdp.ConsumeIntInRange(0, 8) if fdp.ConsumeBool() else 0
        data[at:at + cut] = piece
    return bytes(data)


def load(raw: bytes) -> config.Config | None:
    CONFIG_FILE.write_bytes(raw)
    try:
        return config.load_for_app(LOAD_ROOT, harness.CONFIG_PATH)
    except config.ConfigError:
        return None


# ABYSM's config itself: it must load, run the abysm flow and pass every check.
REAL = load(SOURCE)
assert REAL is not None and REAL.ios is not None and REAL.ios.flow == "abysm", "store/store-release.toml must load"
check_accepted(REAL)


def TestOneInput(data: bytes) -> None:
    if not data:
        return
    mode = data[0] % 4
    fdp = atheris.FuzzedDataProvider(data[1:])
    if mode == 0:
        parsed = load(data[1:])
    elif mode == 1:
        parsed = load(edit_bytes(fdp))
    else:
        document = copy.deepcopy(BASE)
        for _ in range(fdp.ConsumeIntInRange(1, 4 if mode == 2 else 1)):
            mutate(fdp, document)
        try:
            parsed = config.parse(document)
        except config.ConfigError:
            parsed = None
    if parsed is not None:
        check_accepted(parsed)


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Fuzz the iOS release switches and stage gates of ABYSM's release runs.

    python3 -I fuzz/release_gates_fuzz.py [libFuzzer flags] [corpus dir]

The prepare job's `run.py ios gates` runs the abysm flow's resolve_gates
(store_release/flows/abysm/ios_release.py), bound to store/store-release.toml, and
writes what the run may do to $GITHUB_OUTPUT. Each later job re-checks the inputs
it was given with `run.py stage check` (store_release/stage.py) against the
config's gate job, quality. Properties:

- resolve_gates accepts exactly what the documented rules allow (an independent
  model): every switch is true/1/yes/on or false/0/no/off/empty in any case with
  surrounding whitespace, or unset, and an invalid one fails even with
  IOS_RELEASE_AUTOMATION off or on a validation run; build wait numbers are plain
  digits within their bounds; only tag pushes and manual runs run; a tag must be
  exactly v<MARKETING_VERSION>; a validation version only on manual runs; with the
  master switch on, review needs this run's upload and public release needs review.
  It raises nothing but ReleaseError.
- The plan it returns is the model's: a manual run publishes nothing, the master
  switch off publishes nothing, and no store operation is on that its own switch
  did not ask for.
- write_outputs writes one key=value line per output, which reads back to the plan.
- gate_check passes only for quality=success, or quality=skipped outside a release.
- The app-store-connect and github-release stage checks pass only a tag push for
  v<version>, exact true/false flags, review with this run's upload (a build id),
  and a successful quality job; and they pass every tag-run plan resolve_gates
  accepts, so a valid release is never stopped half-way.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402  (puts the pinned store-release checkout on sys.path)

import atheris  # noqa: E402

with atheris.instrument_imports(include=["store_release"]):
    from store_release import config, context, stage
    from store_release.flows.abysm import ios_release

# ABYSM's documented switches (store/README.md): the master switch, then each store
# operation and the plan key it controls.
MASTER = "IOS_RELEASE_AUTOMATION"
OPERATIONS = {
    "IOS_CREATE_VERSION": "create_version",
    "IOS_UPLOAD_BUILD": "upload_build",
    "IOS_UPLOAD_LISTING": "listing",
    "IOS_UPLOAD_WHATS_NEW": "whats_new",
    "IOS_UPLOAD_SCREENSHOTS": "screenshots",
    "IOS_UPLOAD_CREATIVE_ASSETS": "creative",
    "IOS_SUBMIT_REVIEW": "submit",
    "IOS_PUBLIC_RELEASE": "public_release",
}
ASC_OPERATIONS = ("listing", "whats_new", "screenshots", "creative", "submit")
# name -> (default, low, high): poll every 30 seconds for up to 2 hours by default.
NUMBERS = {"IOS_BUILD_POLL_SECONDS": (30, 10, 600), "IOS_BUILD_WAIT_MINUTES": (120, 10, 300)}
NUMBER_KEYS = {"IOS_BUILD_POLL_SECONDS": "poll_seconds", "IOS_BUILD_WAIT_MINUTES": "wait_minutes"}
TRUE = {"1", "true", "yes", "on"}
FALSE = {"", "0", "false", "no", "off"}
VERSION = re.compile(r"[0-9]+(?:\.[0-9]+){0,2}")
DIGITS = re.compile(r"[0-9]+")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

CONFIG = config.load(harness.CONFIG_FILE)
context.configure(CONFIG, harness.REPO, config_path=harness.CONFIG_PATH)
assert CONFIG.ios is not None and CONFIG.ios.flow == "abysm", "store/store-release.toml must run the abysm flow"
TAG_PREFIX = CONFIG.ios.tag_prefix
assert TAG_PREFIX == "v" == ios_release.TAG_PREFIX, "ABYSM's release tags are v<MARKETING_VERSION>"
GATE_JOBS = [job.id for job in CONFIG.ios.gate_jobs]
assert GATE_JOBS == ["quality"], f"update this target for the gate jobs {GATE_JOBS}"
assert CONFIG.ios.gate_policy == "parallel", CONFIG.ios.gate_policy
# The fuzzed code must still be what these properties describe (a store-release bump
# that adds a switch or moves a bound fails here, not silently).
assert ios_release.MASTER == MASTER
assert dict(ios_release.OPERATION_SWITCHES) == OPERATIONS, ios_release.OPERATION_SWITCHES
for _spec in (ios_release.POLL_SECONDS, ios_release.WAIT_MINUTES):
    assert NUMBERS[_spec[0]] == tuple(_spec[1:]), _spec
# The real MARKETING_VERSION, read through the flow from ABYSM's project.
PROJECT_VERSION = ios_release.project_marketing_version()

OUTPUT = harness.scratch("gates") / "github_output"
os.environ["GITHUB_OUTPUT"] = str(OUTPUT)
STAGE_PARSER = argparse.ArgumentParser(add_help=False)
stage.add_stage_arguments(STAGE_PARSER)

# Switch values the documented rules accept, and ones they must reject.
VALID_SWITCHES = ("", "true", "false", "TRUE", "False", " yes ", "on", "ON\t", "1", "0", "no", "off", "\ntrue\n",
                  "\u00a0true")
ODD_SWITCHES = ("tru", "enabled", "2", "-1", "yes please", "true\nfalse", "t", "y", "none", "null", "\u0131",
                "\uff54rue", "on\x00", "true!", "o n")
VALID_NUMBERS = ("", "10", "30", "45", " 120 ", "300", "600", "045", "30\n", " ")
ODD_NUMBERS = ("0", "9", "301", "601", "+30", "3e1", "0x1e", "1_000", "\u0663\u0660", "-10", "15.0",
               "\uff13\uff10", "1 0")
EVENTS = ("push", "workflow_dispatch")
ODD_EVENTS = ("pull_request", "schedule", "release", "Push", "", "push ")
VERSIONS = ("1.0", "1.0.1", "1.1", "2.0.0", "10.20.30", "1", "0.9")
ODD_VERSIONS = ("1.0.1.2", "01.0", "1..0", " 1.1 ", "v1.0", "", "1.0-beta", "\u0661.0", "1.0\n", "1.1 ", "\uff11.0")
REF_SUFFIXES = ("", "", " ", "\n", ".0", "-rc1", "-build2", "0")
REF_PREFIXES = ("refs/tags/", "V", "ios-v", "vv", " ")
GATE_STRINGS = ("quality=success", "quality=skipped", "quality=failure", "quality=cancelled", "quality=",
                "quality=success ", " quality=success", "quality=success quality=success", "Quality=success",
                "quality=success tests=success", "tests=success", "quality=succes", "quality=success\n",
                "quality==success", "quality=skipped quality=success", "")
# The app-store-connect stage's switch inputs (plan keys), passed as exact true/false.
STAGE_FLAGS = ("upload_build", "listing", "whats_new", "screenshots", "creative", "submit", "public_release")
FLAG_VALUES = ("true", "false", "", "True", "1", "yes", " true", "false\n")
BUILD_IDS = ("", "0123abcd-0123-4567-89ab-0123456789ab", "0123ABCD-0123-4567-89AB-0123456789AB",
             "0123abcd-0123-4567-89ab-0123456789a", "not-a-build-id", "0123abcd01234567 89ab0123456789ab")
BUILD_NUMBERS = ("", "1", "7", "42", "0", "-1", "1.0", "x", "\u0663")


def switch_state(raw: str | None) -> bool | None:
    """On, off, or None for a value a release must reject."""
    value = (raw or "").strip().lower()
    return True if value in TRUE else False if value in FALSE else None


def number_value(name: str, raw: str | None) -> int | None:
    default, low, high = NUMBERS[name]
    value = (raw or "").strip()
    if not value:
        return default
    if not (value.isascii() and value.isdigit()) or not low <= int(value) <= high:
        return None
    return int(value)


def model(env: dict[str, str], event: str, ref: str, version: str, override: str) -> dict[str, object] | None:
    """What a run may do under the documented rules, or None when it must fail."""
    if event not in ("push", "workflow_dispatch"):
        return None
    override = override.strip()
    if override and (event != "workflow_dispatch" or not VERSION.fullmatch(override)):
        return None
    states = {name: switch_state(env.get(name)) for name in (MASTER, *OPERATIONS)}
    numbers = {name: number_value(name, env.get(name)) for name in NUMBERS}
    if None in states.values() or None in numbers.values():
        return None
    requested = {key: bool(states[name]) for name, key in OPERATIONS.items()}
    if event == "workflow_dispatch":
        plan = {key: False for key in OPERATIONS.values()}
        mode, master = "validate", False
        version = override or version
    else:
        if ref != TAG_PREFIX + version:
            return None
        mode, master = "release", bool(states[MASTER])
        if master and requested["submit"] and not requested["upload_build"]:
            return None
        if master and requested["public_release"] and not requested["submit"]:
            return None
        plan = dict(requested) if master else {key: False for key in OPERATIONS.values()}
    plan.update({
        "mode": mode,
        "master": master,
        "build": mode == "validate" or plan["upload_build"],
        "asc": any(plan[key] for key in ASC_OPERATIONS),
        "marketing_version": version,
        **{NUMBER_KEYS[name]: value for name, value in numbers.items()},
    })
    return plan


# Choice 0 is the common case everywhere, so an input that runs out of bytes is a
# realistic run (atheris then returns the low end of every range).
def raw_switch(fdp: atheris.FuzzedDataProvider) -> str | None:
    """Mostly values a repository variable would hold, sometimes odd or arbitrary text."""
    choice = fdp.ConsumeIntInRange(0, 19)
    if choice <= 15:
        return harness.pick(fdp, VALID_SWITCHES)
    if choice <= 17:
        return None
    if choice == 18:
        return harness.pick(fdp, ODD_SWITCHES)
    return fdp.ConsumeUnicodeNoSurrogates(fdp.ConsumeIntInRange(0, 8))


def raw_number(fdp: atheris.FuzzedDataProvider) -> str | None:
    choice = fdp.ConsumeIntInRange(0, 11)
    if choice <= 6:
        return harness.pick(fdp, VALID_NUMBERS)
    if choice <= 8:
        return None
    if choice == 9:
        return str(fdp.ConsumeIntInRange(0, 1000))
    if choice == 10:
        return harness.pick(fdp, ODD_NUMBERS)
    return fdp.ConsumeUnicodeNoSurrogates(fdp.ConsumeIntInRange(0, 6))


def marketing_version(fdp: atheris.FuzzedDataProvider) -> str:
    """A MARKETING_VERSION the project could hold: the flow only reads one matching VERSION."""
    choice = fdp.ConsumeIntInRange(0, 2)
    if choice == 0:
        return PROJECT_VERSION
    if choice == 1:
        return harness.pick(fdp, VERSIONS)
    return ".".join(str(fdp.ConsumeIntInRange(0, 30)) for _ in range(fdp.ConsumeIntInRange(1, 3)))


def event_name(fdp: atheris.FuzzedDataProvider) -> str:
    return harness.pick(fdp, ODD_EVENTS) if fdp.ConsumeIntInRange(0, 5) == 5 else harness.pick(fdp, EVENTS)


def ref_name(fdp: atheris.FuzzedDataProvider, version: str) -> str:
    choice = fdp.ConsumeIntInRange(0, 7)
    if choice <= 4:
        return TAG_PREFIX + version
    if choice == 3:
        return TAG_PREFIX + version + harness.pick(fdp, REF_SUFFIXES)
    if choice == 4:
        return harness.pick(fdp, REF_PREFIXES) + version
    return fdp.ConsumeUnicodeNoSurrogates(fdp.ConsumeIntInRange(0, 12))


def override_version(fdp: atheris.FuzzedDataProvider, event: str) -> str:
    """The validation version input: usually empty, except on some manual runs."""
    choice = fdp.ConsumeIntInRange(0, 4 if event == "workflow_dispatch" else 12)
    if choice <= 1 or choice > 4:
        return ""
    if choice == 2:
        return harness.pick(fdp, VERSIONS)
    if choice == 3:
        return harness.pick(fdp, ODD_VERSIONS)
    return fdp.ConsumeUnicodeNoSurrogates(fdp.ConsumeIntInRange(0, 8))


def output_text(value: object) -> str:
    return ("true" if value else "false") if isinstance(value, bool) else str(value)


def check_outputs(plan: dict[str, object]) -> None:
    OUTPUT.write_text("", encoding="utf-8")
    with contextlib.redirect_stdout(io.StringIO()):
        ios_release.write_outputs(plan)
    text = OUTPUT.read_text(encoding="utf-8")
    assert text.endswith("\n"), text
    read: dict[str, str] = {}
    for line in text[:-1].split("\n"):
        key, sep, value = line.partition("=")
        assert sep and key and "<<" not in key and key not in read, f"bad output line {line!r}"
        read[key] = value
    assert read == {key: output_text(value) for key, value in plan.items()}, (read, plan)


def check_stage(name: str, env: dict[str, str], **inputs: str) -> bool:
    """True when `stage check --stage <name>` accepts these inputs."""
    args = STAGE_PARSER.parse_args(["--stage", name])
    for key, value in inputs.items():
        setattr(args, key, value)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            stage.stage_check(name, args, CONFIG, environ=env)
    except stage.StageError:
        return False
    return True


def check_plan_passes_stages(plan: dict[str, object], env: dict[str, str]) -> None:
    """The later jobs accept the inputs a tag run's caller passes them (ios-release.yml)."""
    version = str(plan["marketing_version"])
    uploaded = "7" if plan["upload_build"] else ""
    assert check_stage("ios-github-release", env, gates="quality=success", marketing_version=version,
                       uploaded_build=uploaded), plan
    if plan["asc"]:
        flags = {key: output_text(plan[key]) for key in STAGE_FLAGS}
        assert check_stage("ios-app-store-connect", env, gates="quality=success", marketing_version=version,
                           build_number=uploaded, build_id=BUILD_IDS[1] if plan["upload_build"] else "",
                           **flags), plan


def check_gates(fdp: atheris.FuzzedDataProvider) -> None:
    env: dict[str, str] = {}
    for name in (MASTER, *OPERATIONS):
        raw = raw_switch(fdp)
        if raw is not None:
            env[name] = raw
    for name in NUMBERS:
        raw = raw_number(fdp)
        if raw is not None:
            env[name] = raw
    event = event_name(fdp)
    version = marketing_version(fdp)
    ref = ref_name(fdp, version)
    override = override_version(fdp, event)
    want = model(env, event, ref, version, override)
    case = f"env={env!r} event={event!r} ref={ref!r} version={version!r} override={override!r}"
    try:
        gates = ios_release.resolve_gates(env, event=event, ref_name=ref, marketing_version=version,
                                          validation_version=override)
    except ios_release.ReleaseError:
        assert want is None, f"a valid run was refused: {case}"
        return
    assert want is not None, f"an invalid run was accepted: {case} gates={gates!r}"
    notes = gates.pop("notes")
    assert isinstance(notes, list), case
    assert gates == want, f"plan differs from the rules: {case}\n got {gates!r}\nwant {want!r}"
    # The release-safety rules, stated on their own.
    operations = [key for key in OPERATIONS.values() if gates[key]]
    if event == "workflow_dispatch" or switch_state(env.get(MASTER)) is not True:
        assert not operations and not gates["asc"] and not gates["master"], f"publishes without a tag and " \
                                                                             f"the master switch: {case}"
    else:
        assert ref == "v" + version, case
    assert not gates["submit"] or gates["upload_build"], case
    assert not gates["public_release"] or gates["submit"], case
    check_outputs(gates)
    if gates["mode"] == "release":
        check_plan_passes_stages(gates, {"GITHUB_EVENT_NAME": event, "GITHUB_REF_NAME": ref})


def check_gate_strings(fdp: atheris.FuzzedDataProvider) -> None:
    raw = harness.pick(fdp, GATE_STRINGS) if fdp.ConsumeBool() else fdp.ConsumeUnicodeNoSurrogates(
        fdp.ConsumeIntInRange(0, 24))
    release = fdp.ConsumeBool()
    try:
        stage.gate_check(raw, GATE_JOBS, release=release)
        accepted = True
    except stage.StageError:
        accepted = False
    allowed = {"quality=success"} if release else {"quality=success", "quality=skipped"}
    assert accepted == (raw in allowed), f"gate_check({raw!r}, release={release}) -> {accepted}"


def check_stage_inputs(fdp: atheris.FuzzedDataProvider) -> None:
    version = marketing_version(fdp) if fdp.ConsumeIntInRange(0, 3) else harness.pick(fdp, ODD_VERSIONS)
    event = event_name(fdp)
    env = {"GITHUB_EVENT_NAME": event, "GITHUB_REF_NAME": ref_name(fdp, version)}
    gates = harness.pick(fdp, GATE_STRINGS[:4]) if fdp.ConsumeBool() else harness.pick(fdp, GATE_STRINGS)
    tag_ok = event == "push" and VERSION.fullmatch(version) is not None and env["GITHUB_REF_NAME"] == "v" + version
    case = f"env={env!r} version={version!r} gates={gates!r}"
    if fdp.ConsumeBool():
        uploaded = harness.pick(fdp, BUILD_NUMBERS)
        if check_stage("ios-github-release", env, gates=gates, marketing_version=version, uploaded_build=uploaded):
            assert tag_ok and gates == "quality=success", case
            assert uploaded == "" or DIGITS.fullmatch(uploaded), f"uploaded_build={uploaded!r} {case}"
        return
    flags = {name: harness.pick(fdp, ("true", "false")) if fdp.ConsumeIntInRange(0, 7)
             else harness.pick(fdp, FLAG_VALUES) for name in STAGE_FLAGS}
    build_id = harness.pick(fdp, BUILD_IDS)
    build_number = harness.pick(fdp, BUILD_NUMBERS)
    if not check_stage("ios-app-store-connect", env, gates=gates, marketing_version=version, build_id=build_id,
                       build_number=build_number, **flags):
        return
    case += f" flags={flags!r} build_id={build_id!r} build_number={build_number!r}"
    assert tag_ok and gates == "quality=success", case
    assert all(value in ("true", "false") for value in flags.values()), case
    on = {name for name, value in flags.items() if value == "true"}
    assert on & set(ASC_OPERATIONS), f"ran with no App Store Connect operation: {case}"
    assert "submit" not in on or "upload_build" in on, f"review without this run's upload: {case}"
    assert "public_release" not in on or "submit" in on, f"public release without review: {case}"
    if "upload_build" in on:
        assert UUID.fullmatch(build_id) and DIGITS.fullmatch(build_number), case
    else:
        assert build_id == "", case


def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    choice = fdp.ConsumeIntInRange(0, 5)
    if choice <= 3:
        check_gates(fdp)
    elif choice == 4:
        check_gate_strings(fdp)
    else:
        check_stage_inputs(fdp)


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()

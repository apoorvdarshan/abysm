#!/usr/bin/env python3
"""Fuzz the log redaction that runs before ABYSM's failed-build logs are kept.

    python3 -I fuzz/redact_logs_fuzz.py [libFuzzer flags] [corpus dir]

When an iOS release build fails, the build job copies xcodebuild's and Xcode's
distribution logs into a folder and runs `run.py ios redact-logs DIR`
(store_release/redact.py) with the App Store Connect key ID and issuer ID in
ASC_KEY_ID and ASC_ISSUER_ID. The folder becomes a workflow artifact only when that
step succeeds, and ABYSM's artifacts are as public as its repository. Folders hold
files and subfolders with the IDs in any ASCII case, as UTF-8, UTF-16LE or UTF-16BE
text, in contents and in file and folder names (Xcode names key files
AuthKey_<key ID>.p8), plus symbolic links out of the folder. Properties:

- with realistic IDs (a 10-character key ID, a UUID issuer ID) it exits 0, and no
  file content or path left in the folder holds either ID in any of those forms;
- for any ASCII ID values, when it exits 0 no file left holds an ID: a file it
  cannot clean is deleted, or it exits non-zero (fails closed). (App Store Connect
  IDs are ASCII; an ID with a non-ASCII capital letter is not covered, because the
  leftover check lowercases the ID with str.lower() and the file with bytes.lower().)
- files whose path and content hold no ID are left exactly as they were;
- it never writes through a symbolic link: files outside the folder are unchanged;
- with either ID unset (or only whitespace) it changes nothing.
"""
from __future__ import annotations

import contextlib
import io
import os
import shutil
import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402  (puts the pinned store-release checkout on sys.path)

import atheris  # noqa: E402

with atheris.instrument_imports(include=["store_release"]):
    from store_release import redact

NAMES = ("ASC_KEY_ID", "ASC_ISSUER_ID")
FORMS = ("utf-8", "utf-16-le", "utf-16-be")
KEY_ID_CHARS = string.ascii_uppercase + string.digits
ASCII = string.ascii_letters + string.digits + string.punctuation + " \t"
HEX = "0123456789abcdef"
WORK = harness.scratch("redact")
LOGS = WORK / "logs"
# Outside the folder, and what the folder's symbolic links point at.
OUTSIDE_FILE = WORK / "outside.log"
OUTSIDE_DIR = WORK / "outside-dir"
PLAIN_NAMES = ("build.log", "xcodebuild-archive.log", "IDEDistribution.standard.log", "Distribution Summary.plist",
               "ExportOptions.plist", "altool.log", "IDEDistribution.verbose.log", "Packaging.log", "x")
FOLDER_NAMES = ("Abysm.xcdistributionlogs", "Abysm 2026-10-21 03-53-20.xcdistributionlogs", "logs", "sub")
FILLER = (b"Authenticating with App Store Connect\n", b"key ", b"issuer: ", b"\x00", b"\r\n", b"\xff\xfe",
          b"apiKeyID=", b"<key>apiIssuer</key>", b"\"", b"=", b" ")


def holds(data: bytes, ids: list[str]) -> bool:
    """Any ID in data, in any ASCII case, as UTF-8 or UTF-16 text."""
    folded = data.lower()
    return any(value and value.encode(form).lower() in folded for value in ids for form in FORMS)


def any_case(fdp: atheris.FuzzedDataProvider, value: str) -> str:
    mode = fdp.ConsumeIntInRange(0, 3)
    if mode == 0:
        return value
    if mode == 1:
        return value.lower()
    if mode == 2:
        return value.upper()
    return "".join(ch.upper() if fdp.ConsumeBool() else ch.lower() for ch in value)


def realistic_ids(fdp: atheris.FuzzedDataProvider) -> dict[str, str]:
    key_id = "".join(harness.pick(fdp, KEY_ID_CHARS) for _ in range(10))
    digits = "".join(harness.pick(fdp, HEX) for _ in range(32))
    issuer = "-".join((digits[:8], digits[8:12], digits[12:16], digits[16:20], digits[20:]))
    return {"ASC_KEY_ID": key_id, "ASC_ISSUER_ID": issuer}


def arbitrary_ids(fdp: atheris.FuzzedDataProvider) -> dict[str, str]:
    """Any short ASCII text, as a secret holding an App Store Connect ID could."""
    return {name: "".join(harness.pick(fdp, ASCII) for _ in range(fdp.ConsumeIntInRange(0, 10))) for name in NAMES}


def content(fdp: atheris.FuzzedDataProvider, ids: list[str]) -> bytes:
    parts: list[bytes] = []
    for _ in range(fdp.ConsumeIntInRange(0, 8)):
        choice = fdp.ConsumeIntInRange(0, 4)
        if choice <= 1 and ids:
            parts.append(any_case(fdp, harness.pick(fdp, ids)).encode(harness.pick(fdp, FORMS)))
        elif choice == 2:
            parts.append(harness.pick(fdp, FILLER))
        else:
            parts.append(fdp.ConsumeBytes(fdp.ConsumeIntInRange(0, 48)))
    return b"".join(parts)


def name(fdp: atheris.FuzzedDataProvider, ids: list[str], names: tuple[str, ...]) -> str:
    """A file or folder name, sometimes holding a (realistic) ID."""
    if ids and fdp.ConsumeIntInRange(0, 3) == 0:
        value = any_case(fdp, harness.pick(fdp, ids))
        return harness.pick(fdp, (f"AuthKey_{value}.p8", f"{value}.log", f"{value}", f"issuer-{value}"))
    return harness.pick(fdp, names)


def build_folder(fdp: atheris.FuzzedDataProvider, ids: list[str], name_ids: list[str]) -> dict[Path, bytes]:
    """Fill LOGS; returns every regular file written (relative path -> bytes)."""
    files: dict[Path, bytes] = {}
    for _ in range(fdp.ConsumeIntInRange(1, 6)):
        parts = [name(fdp, name_ids, FOLDER_NAMES) for _ in range(fdp.ConsumeIntInRange(0, 2))]
        relative = Path(*parts, name(fdp, name_ids, PLAIN_NAMES))
        # Skip a path that is, or is inside, one already written (ignoring case, for
        # case-insensitive file systems).
        folded = Path(str(relative).lower())
        if any(folded == old or old in folded.parents or folded in old.parents
               for old in (Path(str(other).lower()) for other in files)):
            continue
        data = content(fdp, ids)
        (LOGS / relative).parent.mkdir(parents=True, exist_ok=True)
        (LOGS / relative).write_bytes(data)
        files[relative] = data
    if fdp.ConsumeBool():
        (LOGS / "linked.log").symlink_to(OUTSIDE_FILE)
    if fdp.ConsumeBool():
        (LOGS / "linked-dir").symlink_to(OUTSIDE_DIR, target_is_directory=True)
    return files


def reset(ids: list[str]) -> None:
    shutil.rmtree(WORK, ignore_errors=True)
    LOGS.mkdir(parents=True)
    OUTSIDE_DIR.mkdir()
    OUTSIDE_FILE.write_bytes(b"outside the folder: " + "".join(ids).encode("utf-8"))
    (OUTSIDE_DIR / "kept.log").write_bytes(b"also outside: " + "".join(ids).encode("utf-16-le"))


def snapshot() -> dict[Path, bytes]:
    return {path.relative_to(LOGS): path.read_bytes()
            for path in LOGS.rglob("*") if path.is_file() and not path.is_symlink()}


def run(ids: dict[str, str]) -> int | None:
    """redact-logs' exit code, or None when it raised (the step fails: nothing is uploaded)."""
    saved = {key: os.environ.get(key) for key in NAMES}
    os.environ.update(ids)
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return redact.main(["redact-logs", str(LOGS)])
    except OSError:
        return None
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    realistic = fdp.ConsumeIntInRange(0, 3) != 0
    ids = realistic_ids(fdp) if realistic else arbitrary_ids(fdp)
    if not realistic and fdp.ConsumeIntInRange(0, 5) == 0:
        ids[harness.pick(fdp, NAMES)] = harness.pick(fdp, ("", " ", "\t\n"))
    # What the step compares with: the secrets as GitHub passes them, stripped.
    values = [value.strip() for value in ids.values()]
    reset(values)
    outside = (OUTSIDE_FILE.read_bytes(), (OUTSIDE_DIR / "kept.log").read_bytes())
    files = build_folder(fdp, [v for v in values if v], [v for v in values if v] if realistic else [])
    before = snapshot()
    code = run(ids)
    after = snapshot()
    case = f"ids={ids!r} files={files!r} -> exit {code}, left {after!r}"

    assert (OUTSIDE_FILE.read_bytes(), (OUTSIDE_DIR / "kept.log").read_bytes()) == outside, \
        f"wrote outside the folder: {case}"
    if not all(values):
        assert code == 0 and after == before, f"changed the folder without both IDs: {case}"
        return
    if realistic:
        assert code == 0, f"failed on realistic IDs: {case}"
    if code == 0:
        for relative, kept in after.items():
            assert not holds(kept, values), f"{relative} still holds an ID: {case}"
    if realistic:
        for path in LOGS.rglob("*"):
            assert not holds(path.name.encode("utf-8"), values), f"a path still holds an ID: {path} {case}"
    for relative, original in before.items():
        if not holds(str(relative).encode("utf-8"), values) and not holds(original, values):
            assert after.get(relative) == original, f"changed {relative}, which held no ID: {case}"


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()

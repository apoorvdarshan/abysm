#!/usr/bin/env python3
"""Fuzz the GitHub Release notes ABYSM's release publishes from RELEASE_NOTES.md.

    python3 -I fuzz/release_notes_fuzz.py [libFuzzer flags] [corpus dir]

The release runs `run.py --app-root app release-notes --if-present <tag>`
(store_release/release_notes.py, reading release_notes.path from
store/store-release.toml) in prepare, before anything is built, and again in the
GitHub Release job, which publishes what it prints; empty output means GitHub
generates the notes. Store checks runs `release-notes --check-headings` on pull
requests. Files are built from ABYSM's real RELEASE_NOTES.md lines and tags and
checked against an independent line-by-line reading. Properties:

- a tag with exactly one non-empty `## <tag>` section prints exactly that
  section's text, so never another release's section or the Unreleased notes;
- a tag without a section prints nothing and succeeds;
- a repeated or empty section, the tag Unreleased, or an empty tag fails without
  printing anything; nothing but that exit is raised;
- --check-headings fails exactly when a `## ` heading repeats, so it passes no file
  a tag run would reject as a duplicate. (Checked for files whose line breaks are
  \\n, \\r\\n or \\r: str.splitlines(), which it uses, also splits at characters such
  as U+2028 that the tag run does not.)
"""
from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402  (puts the pinned store-release checkout on sys.path)

import atheris  # noqa: E402

with atheris.instrument_imports(include=["store_release"]):
    from store_release import config, context, release_notes

CONFIG = config.load(harness.CONFIG_FILE)
APP = harness.scratch("notes")
context.configure(CONFIG, APP, config_path=harness.CONFIG_PATH)
assert CONFIG.release_notes == "RELEASE_NOTES.md", CONFIG.release_notes
assert CONFIG.ios is not None and CONFIG.ios.tag_prefix == "v", "ABYSM's release tags are v<MARKETING_VERSION>"
NOTES = APP / CONFIG.release_notes

REAL_LINES = harness.RELEASE_NOTES.read_text(encoding="utf-8").split("\n")
REAL_TAGS = [line[3:].strip() for line in REAL_LINES if line.startswith("## ")]
assert "Unreleased" in REAL_TAGS and any(tag.startswith("v") for tag in REAL_TAGS), REAL_TAGS
TAGS = sorted(set(REAL_TAGS) | {"v1.0", "v1.0.1", "v1.1", "v1.10", "v2.0", "v1.1.1"})
NEAR_TAGS = ("V1.1", "v1.1 ", " v1.1", "v1.1\t", "1.1", "v1", "unreleased", "Unreleased ", "v1.1.0", "v1.1-rc1",
             "v1.\u0661", "v1\u20141")
HEADING_STARTS = ("## ", "## ", "## ", "##  ", "## \t", "### ", "#", "##", " ## ", "##\t")
LINE_ENDS = ("\n", "\n", "\r\n", " \n", "\r", "")
TOKENS = ("\n", "\r\n", "\r", "## ", "### ", "# ", "- ", "  ", "\t", "```", "\u2028", "\x85", "\x0c", "\x1c",
          "\xa0", "notes", "v1.1", "Unreleased")
# Line breaks str.splitlines() splits at besides \n, \r\n and \r (which reading the file
# turns into \n).
OTHER_BREAKS = frozenset("\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029")


def reference_sections(text: str) -> list[tuple[str, str]]:
    """(title, body) per `## ` heading line, reading the file line by line."""
    found: list[tuple[str, list[str]]] = []
    for line in text.split("\n"):
        if line.startswith("## "):
            found.append((line[3:].strip(), []))
        elif found:
            found[-1][1].append(line)
    return [(title, "\n".join(body).strip()) for title, body in found]


def run(argv: list[str]) -> tuple[int, str]:
    """(exit code, stdout) of `release-notes ARGV`."""
    out = io.StringIO()
    code = 0
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            release_notes.main(argv)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    return code, out.getvalue()


def pick_tag(fdp: atheris.FuzzedDataProvider) -> str:
    choice = fdp.ConsumeIntInRange(0, 7)
    if choice <= 4:
        return harness.pick(fdp, TAGS)
    if choice == 5:
        return harness.pick(fdp, NEAR_TAGS)
    if choice == 6:
        return "v" + ".".join(str(fdp.ConsumeIntInRange(0, 12)) for _ in range(fdp.ConsumeIntInRange(1, 3)))
    tag = fdp.ConsumeUnicodeNoSurrogates(fdp.ConsumeIntInRange(0, 10))
    # A tag name never starts with "-" (git and argparse would both read an option).
    return "v" + tag if tag.startswith("-") else tag


def notes_file(fdp: atheris.FuzzedDataProvider, tag: str) -> str:
    parts: list[str] = []
    if fdp.ConsumeIntInRange(0, 3) == 0:
        parts.append("\n".join(REAL_LINES) + "\n")
    for _ in range(fdp.ConsumeIntInRange(0, 14)):
        choice = fdp.ConsumeIntInRange(0, 9)
        if choice <= 2:
            title = tag if fdp.ConsumeBool() else pick_tag(fdp)
            parts.append(harness.pick(fdp, HEADING_STARTS) + title + harness.pick(fdp, LINE_ENDS))
        elif choice <= 5:
            parts.append(harness.pick(fdp, REAL_LINES) + "\n")
        elif choice <= 7:
            parts.append(harness.pick(fdp, TOKENS))
        else:
            parts.append(fdp.ConsumeUnicodeNoSurrogates(fdp.ConsumeIntInRange(0, 12)))
    return "".join(parts)


def check_tag_run(text: str, tag: str) -> None:
    code, printed = run(["--if-present", tag])
    matches = [body for title, body in reference_sections(text) if title == tag]
    case = f"tag={tag!r} text={text!r} -> exit {code}, printed {printed!r}"
    if not tag or tag == "Unreleased" or len(matches) > 1 or matches == [""]:
        assert code != 0 and printed == "", f"should fail without publishing: {case}"
        return
    assert code == 0, f"failed on usable notes: {case}"
    if not matches:
        assert printed == "", f"printed notes for a tag without a section: {case}"
        return
    assert printed == matches[0] + "\n", f"published the wrong text (want {matches[0]!r}): {case}"


def check_headings(text: str) -> None:
    if OTHER_BREAKS & set(text):
        return
    code, _ = run(["--check-headings"])
    titles = [title for title, _ in reference_sections(text)]
    repeated = len(titles) != len(set(titles))
    assert (code != 0) == repeated, f"--check-headings exit {code} for titles {titles!r}: text={text!r}"


def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    tag = pick_tag(fdp)
    NOTES.write_bytes(notes_file(fdp, tag).encode("utf-8"))
    # What release_notes reads: universal newlines turn \r\n and \r into \n.
    text = NOTES.read_text(encoding="utf-8")
    check_tag_run(text, tag)
    check_headings(text)


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()

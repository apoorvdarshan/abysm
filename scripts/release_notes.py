#!/usr/bin/env python3
"""Print the reviewed RELEASE_NOTES.md section for an exact release tag.

Exit status: 0 = section printed; 3 = no section for this tag (the release
workflow then lets GitHub generate notes); 1 = the section exists but is empty.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

NOTES = Path(__file__).resolve().parents[1] / "RELEASE_NOTES.md"
MISSING = 3


def section(text: str, tag: str) -> str | None:
    """Body of the `## <tag>` section, or None when there is none."""
    if tag.strip().lower() == "unreleased":
        return None
    for chunk in re.split(r"^## ", text, flags=re.MULTILINE)[1:]:
        title, _, body = chunk.partition("\n")
        if title.strip() == tag:
            return body.strip()
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tag", help="release tag, e.g. v1.0.1")
    args = parser.parse_args(argv)
    text = NOTES.read_text(encoding="utf-8") if NOTES.is_file() else ""
    body = section(text, args.tag)
    if body is None:
        print(f"note: RELEASE_NOTES.md has no '## {args.tag}' section", file=sys.stderr)
        return MISSING
    if not body:
        print(f"error: the '## {args.tag}' section in RELEASE_NOTES.md is empty", file=sys.stderr)
        return 1
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

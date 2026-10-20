#!/usr/bin/env python3
"""Print the apoorvdarshan/store-release commit ABYSM's release workflows pin.

    python3 -I fuzz/store_release_pin.py              the 40-character commit SHA
    python3 -I fuzz/store_release_pin.py --check DIR  also fail unless DIR is a
                                                      checkout of exactly that commit

The fuzz targets test the store-release code a release would run, so they use the
commit every `uses: apoorvdarshan/store-release/...@<sha>` line in
.github/workflows/ names. It fails when there is no such line, when a line is not
pinned to a full commit SHA, or when the lines disagree.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO / ".github" / "workflows"
USES = re.compile(r"^\s*(?:-\s+)?uses:\s*apoorvdarshan/store-release/(?P<path>[^@\s]+)@(?P<ref>\S+)", re.M)
SHA = re.compile(r"[0-9a-f]{40}")


def pinned_commit(workflows: Path = WORKFLOWS) -> str:
    refs: dict[str, list[str]] = {}
    for path in sorted(workflows.glob("*.y*ml")):
        for match in USES.finditer(path.read_text(encoding="utf-8")):
            refs.setdefault(match.group("ref"), []).append(f"{path.name}: {match.group('path')}")
    if not refs:
        raise SystemExit(f"error: no workflow in {workflows} uses apoorvdarshan/store-release")
    unpinned = [ref for ref in refs if not SHA.fullmatch(ref)]
    if unpinned:
        raise SystemExit(f"error: store-release is used at {', '.join(unpinned)}, not a full commit SHA")
    if len(refs) > 1:
        listing = "; ".join(f"{ref} ({', '.join(uses)})" for ref, uses in refs.items())
        raise SystemExit(f"error: the workflows pin different store-release commits: {listing}")
    return next(iter(refs))


def checkout_commit(directory: Path) -> str:
    result = subprocess.run(["git", "-C", str(directory), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"error: {directory} is not a git checkout: {result.stderr.strip()}")
    return result.stdout.strip()


def main(argv: list[str]) -> int:
    sha = pinned_commit()
    if argv[:1] == ["--check"] and len(argv) == 2:
        found = checkout_commit(Path(argv[1]))
        if found != sha:
            print(f"error: {argv[1]} is at {found}, but the workflows pin store-release {sha}", file=sys.stderr)
            return 1
    elif argv:
        print(__doc__, file=sys.stderr)
        return 2
    print(sha)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

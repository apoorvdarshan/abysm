#!/usr/bin/env python3
"""The apoorvdarshan/store-release commit ABYSM's release workflows pin.

    python3 -I fuzz/store_release_pin.py              print the 40-character commit SHA
    python3 -I fuzz/store_release_pin.py --fetch DIR  fetch exactly that commit into DIR
                                                      (a new or empty folder)
    python3 -I fuzz/store_release_pin.py --check DIR  fail unless DIR is a checkout of
                                                      exactly that commit

The fuzz targets test the store-release code a release would run, so they use the
commit every `uses: apoorvdarshan/store-release/...@<sha>` line in
.github/workflows/ names; when Dependabot moves the pin, they follow. It fails when
there is no such line, when a line is not pinned to a full commit SHA, or when the
lines disagree. --fetch reads the public repository anonymously and checks the
fetched commit before it returns.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO / ".github" / "workflows"
URL = "https://github.com/apoorvdarshan/store-release.git"
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


def git(*args: str) -> str:
    result = subprocess.run(["git", "-c", "advice.detachedHead=false", *args],
                            capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"error: git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def check(directory: Path, sha: str) -> None:
    found = git("-C", str(directory), "rev-parse", "HEAD")
    if found != sha:
        raise SystemExit(f"error: {directory} is at {found}, but the workflows pin store-release {sha}")


def fetch(directory: Path, sha: str) -> None:
    if directory.exists() and any(directory.iterdir()):
        raise SystemExit(f"error: {directory} is not empty")
    git("init", "-q", str(directory))
    git("-C", str(directory), "fetch", "-q", "--depth", "1", "--no-tags", URL, sha)
    git("-C", str(directory), "checkout", "-q", "--detach", "FETCH_HEAD")
    check(directory, sha)


def main(argv: list[str]) -> int:
    sha = pinned_commit()
    if len(argv) == 2 and argv[0] in ("--fetch", "--check"):
        (fetch if argv[0] == "--fetch" else check)(Path(argv[1]), sha)
    elif argv:
        print(__doc__, file=sys.stderr)
        return 2
    print(sha)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

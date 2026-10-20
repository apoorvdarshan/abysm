"""Shared setup for the Atheris fuzz targets (fuzz/*_fuzz.py).

The targets fuzz the apoorvdarshan/store-release code ABYSM's release workflows
run, at the commit they pin (fuzz/store_release_pin.py). Importing this module puts
that checkout on sys.path: STORE_RELEASE_DIR when set, otherwise .store-release/ at
the repository root (fuzz.yml checks it out there). It never imports store_release
itself; each target imports it inside atheris.instrument_imports(), so the package
is instrumented for coverage.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CONFIG_PATH = "store/store-release.toml"
CONFIG_FILE = REPO / CONFIG_PATH
RELEASE_NOTES = REPO / "RELEASE_NOTES.md"
STORE_RELEASE = Path(os.environ.get("STORE_RELEASE_DIR") or REPO / ".store-release").resolve()

if not (STORE_RELEASE / "store_release" / "__init__.py").is_file():
    raise SystemExit(f"error: no store-release checkout at {STORE_RELEASE}; see fuzz/README.md")
if str(STORE_RELEASE) not in sys.path:
    sys.path.insert(0, str(STORE_RELEASE))


def pick(fdp, values):
    """One item of a non-empty sequence (atheris's PickValueInList takes lists only)."""
    return values[fdp.ConsumeIntInRange(0, len(values) - 1)]


def scratch(prefix: str) -> Path:
    """A fresh, empty folder for one target's files (its stand-in app checkout or log folder)."""
    return Path(tempfile.mkdtemp(prefix=f"abysm-fuzz-{prefix}-")).resolve()

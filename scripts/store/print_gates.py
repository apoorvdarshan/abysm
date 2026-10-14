#!/usr/bin/env python3
"""Print the iOS release switches (repository Variables). Never touches a store."""
from __future__ import annotations

import os

GATES = (
    "IOS_RELEASE_AUTOMATION",
    "IOS_UPLOAD_BUILD",
    "IOS_UPLOAD_LISTING",
    "IOS_UPLOAD_WHATS_NEW",
    "IOS_UPLOAD_SCREENSHOTS",
    "IOS_SUBMIT_REVIEW",
    "IOS_PUBLIC_RELEASE",
)
TIMING = (("IOS_BUILD_POLL_SECONDS", "30"), ("IOS_BUILD_WAIT_MINUTES", "120"))


def enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def main() -> None:
    print("iOS release switches (false = nothing reaches App Store Connect):")
    for name in GATES:
        print(f"  {name}={'true' if enabled(name) else 'false'}")
    for name, default in TIMING:
        print(f"  {name}={os.environ.get(name, '').strip() or default}")
    if not enabled("IOS_RELEASE_AUTOMATION"):
        print("note: IOS_RELEASE_AUTOMATION is off, so every iOS store operation is skipped")
    elif not any(enabled(name) for name in GATES[1:]):
        print("note: the master switch is on but no store operation is enabled")
    else:
        print("WARNING: one or more live App Store Connect operations are on")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""ABYSM App Store Connect version, listing, screenshots, creative assets, build selection and review (gated in CI).

Every App Store Connect call goes through the pinned App Store Connect CLI
(`asc`, see asc_cli.py); this script decides what may change and checks the
results. Called by .github/workflows/ios-release.yml with flags resolved from
the IOS_* switches (see store/README.md):

  UPLOAD_LISTING          version text (description, keywords, promotional text,
                          marketing/support URLs) and App Info (name, subtitle,
                          privacy policy URL) for every locale in store/metadata/ios/
  UPLOAD_WHATS_NEW        whats_new.txt for every locale
  UPLOAD_SCREENSHOTS      iPhone 6.9" and iPad 13" screenshots from store/metadata/screenshots/,
                          uploaded from staged copies (RGB where the file stores alpha)
  UPLOAD_CREATIVE_ASSETS  product page header and search results images from
                          store/creative/ios/: a new image is uploaded to the Asset
                          Library and reviewed on its own; an approved one is placed
  SUBMIT_IOS_REVIEW       select THIS run's build (read back + rechecked), then submit the
                          version and any Ready-to-Submit catalog products for review
  PUBLIC_RELEASE          release automatically after approval (else manual release)
  CREATE_IOS_VERSION      with --create-version: create the tag's App Store version
                          when it is missing (an existing one is left alone)

Only fields, screenshots, images and selections that differ from App Store
Connect are sent, so re-running the step is safe. A screenshot set counts as
matching only when it holds the repo's images in order and App Store Connect has
processed every one, so a set left by a failed or timed-out wait is uploaded
again. Once the version is in a draft review submission (READY_FOR_REVIEW) its
text can still change but its screenshots and creative placements cannot. Once
it is submitted (WAITING_FOR_REVIEW, IN_REVIEW) nothing can, and a re-run writes
nothing: it succeeds only if App Store Connect already matches the repo, review
holds this run's build, and no catalog product is still due for review (a
product is never sent to App Review without the version).

`--dry-run` validates the local inputs only and makes no App Store Connect calls.
`--create-version` (CREATE_IOS_VERSION, from the IOS_CREATE_VERSION switch) runs
first on a release run: it adds the App Store version for the tag when App Store
Connect does not have it yet, and leaves an existing one alone. It refuses when
another version is still on its way to the store or the tag's version is not
newer than every existing one.
`--preflight` runs before anything is built, with asc in read-only mode
(ASC_READ_ONLY: asc refuses every write before it is sent). It fails when the
App Store version is missing (turn on IOS_CREATE_VERSION, or create it in App
Store Connect first) or when its state, localizations, images or catalog
products would stop the enabled steps.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import asc_cli  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUNDLE_ID = "com.apoorvdarshan.Abysm"
# App Store Connect app record for DEFAULT_BUNDLE_ID ("ABYSM - Dive the Deep Sea").
# Every run checks that this record carries exactly that bundle id before
# touching anything.
ASC_APP_ID = "6783505799"
PLATFORM = "IOS"
METADATA_DIR = ROOT / "store" / "metadata"
CREATIVE_DIR = ROOT / "store" / "creative" / "ios"
CATALOG = ROOT / "store" / "catalog" / "products.json"
PRIMARY_LOCALE = "en-US"

# Everything about the version can change: text, App Info, screenshots and
# creative placements.
EDITABLE_VERSION_STATES = {
    "PREPARE_FOR_SUBMISSION",
    "DEVELOPER_REJECTED",
    "REJECTED",
    "METADATA_REJECTED",
    "INVALID_BINARY",
}
# READY_FOR_REVIEW means the version already sits in a draft review submission
# (for example after a failed submit). It can still be submitted, and its text
# (listing, What's New, App Info) can still change; its screenshots and
# creative placements cannot.
TEXT_EDITABLE_VERSION_STATES = EDITABLE_VERSION_STATES | {"READY_FOR_REVIEW"}
SUBMITTABLE_VERSION_STATES = EDITABLE_VERSION_STATES | {"READY_FOR_REVIEW"}
# Already submitted: nothing can change, and a re-run of the store step (for
# example after the job failed once the submit had gone through) writes nothing.
# It passes only when App Store Connect already matches the repo, review holds
# this run's build, and no catalog product is left Ready to Submit.
SUBMITTED_VERSION_STATES = {"WAITING_FOR_REVIEW", "IN_REVIEW"}
# App Info (name, subtitle, privacy URL) is editable only while a new version is
# prepared, including while that version waits in a draft review submission.
EDITABLE_APP_INFO_STATES = {
    "PREPARE_FOR_SUBMISSION",
    "DEVELOPER_REJECTED",
    "REJECTED",
    "METADATA_REJECTED",
    "INVALID_BINARY",
    "READY_FOR_REVIEW",
}
# App Info records of a version that is already on the App Store (never edited).
LIVE_APP_INFO_STATES = {"READY_FOR_SALE", "READY_FOR_DISTRIBUTION", "REPLACED_WITH_NEW_INFO"}
# Versions in these states are finished. Any other state means the version is
# still on its way to the store, and App Store Connect allows only one such
# version per platform, so --create-version never creates a version next to it.
FINISHED_VERSION_STATES = {
    "READY_FOR_SALE",
    "REPLACED_WITH_NEW_VERSION",
    "REMOVED_FROM_SALE",
    "DEVELOPER_REMOVED_FROM_SALE",
}

# (ASC attribute, file in store/metadata/ios/<locale>/, max characters)
LISTING_FIELDS = (
    ("description", "description.txt", 4000),
    ("keywords", "keywords.txt", 100),
    ("promotionalText", "promotional_text.txt", 170),
    ("marketingUrl", "marketing_url.txt", None),
    ("supportUrl", "support_url.txt", None),
)
WHATS_NEW_FIELD = ("whatsNew", "whats_new.txt", 4000)
APP_INFO_FIELDS = (
    ("name", "name.txt", 30),
    ("subtitle", "subtitle.txt", 30),
    ("privacyPolicyUrl", "privacy_url.txt", None),
    ("privacyChoicesUrl", "privacy_choices_url.txt", None),
)
URL_ATTRIBUTES = {"marketingUrl", "supportUrl", "privacyPolicyUrl", "privacyChoicesUrl"}
# The `asc localizations update` flag for each attribute.
FIELD_FLAGS = {
    "description": "--description",
    "keywords": "--keywords",
    "promotionalText": "--promotional-text",
    "marketingUrl": "--marketing-url",
    "supportUrl": "--support-url",
    "whatsNew": "--whats-new",
    "name": "--name",
    "subtitle": "--subtitle",
    "privacyPolicyUrl": "--privacy-policy-url",
    "privacyChoicesUrl": "--privacy-choices-url",
}

# Screenshots come from the repo's App Store-ready images, uploaded from staged
# copies (stage_screenshots) so the committed files are never changed.
# Display type → (source folder, accepted pixel sizes). ABYSM is landscape-only.
# The accepted sizes are exactly what asc accepts for the display type
# (`asc screenshots sizes --display-type <TYPE>`).
SCREENSHOT_SETS: tuple[tuple[str, Path, frozenset[tuple[int, int]]], ...] = (
    (
        "APP_IPHONE_67",  # App Store Connect's 6.9"/6.7" iPhone slot
        ROOT / "store" / "metadata" / "screenshots" / "ios" / "iphone",
        frozenset({(2796, 1290), (1290, 2796), (2868, 1320), (1320, 2868), (2736, 1260), (1260, 2736)}),
    ),
    (
        "APP_IPAD_PRO_3GEN_129",  # 13"/12.9" iPad slot
        ROOT / "store" / "metadata" / "screenshots" / "ios" / "ipad",
        frozenset({(2752, 2064), (2064, 2752), (2732, 2048), (2048, 2732)}),
    ),
)
# asc's --device-type for each display type.
DEVICE_TYPES = {"APP_IPHONE_67": "IPHONE_67", "APP_IPAD_PRO_3GEN_129": "IPAD_PRO_3GEN_129"}
APP_SCREENSHOT_SET_MAX = 10
SCREENSHOT_PROCESSING_TIMEOUT_SECONDS = 600
SCREENSHOT_PROCESSING_POLL_SECONDS = 10

# Product page creative assets (IOS_UPLOAD_CREATIVE_ASSETS): the folder under
# --creative-dir, the placement type, and a label for logs. Each folder holds at
# most one image.
CREATIVE_SLOTS = (
    ("header", "PRODUCT_PAGE_HEADER_ASSET", "product page header"),
    ("search-results", "APP_STORE_SEARCH_RESULTS_ASSET", "search results"),
)
# Apple's image specs per slot (asc asset-library specs): the header is a 21:9
# 3840x1646 PNG; search results are 3:2 PNG or JPEG from 1920x1280 to 3840x2560.
# A 5244x2950 16:9 PNG is a universal image that fits either.
UNIVERSAL_CREATIVE_SIZE = (5244, 2950)
CREATIVE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
# Library image states: still being reviewed, or finished without approval.
CREATIVE_PENDING_STATES = {"WAITING_FOR_REVIEW", "IN_REVIEW", "ACCEPTED"}
CREATIVE_UNSUBMITTED_STATES = {"PREPARE_FOR_SUBMISSION", "READY_FOR_REVIEW", "COMPLETE", "UPLOAD_COMPLETE"}
# AWAITING_UPLOAD is a reservation an interrupted upload left behind (asc never
# deletes it); it is ignored like a failed one, so the next run uploads the image again.
CREATIVE_DEAD_STATES = {"REJECTED", "FAILED", "ARCHIVED", "AWAITING_UPLOAD"}

CATALOG_GROUPS = ("nonConsumables", "consumables", "subscriptions")


def fail(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(1)


def truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def read_text(path: Path) -> str | None:
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


# --- asc ---------------------------------------------------------------------------


def data(payload: Any) -> Any:
    return (payload or {}).get("data") if isinstance(payload, dict) else None


def rows(payload: Any) -> list[dict[str, Any]]:
    value = data(payload)
    return value if isinstance(value, list) else []


def attrs(row: dict[str, Any] | None) -> dict[str, Any]:
    return (row or {}).get("attributes") or {}


def related_id(row: dict[str, Any], name: str) -> str | None:
    """The related record's id; asc reports a missing relationship as an empty id."""
    return (((row.get("relationships") or {}).get(name) or {}).get("data") or {}).get("id")


def asc_value(text: str) -> str:
    """A flag value for asc, which reads a leading @ as @file:/@env: (escaped as @@)."""
    return "@" + text if text.startswith("@") else text


def load_credentials() -> None:
    names = ("APP_STORE_CONNECT_API_KEY_ID", "APP_STORE_CONNECT_ISSUER_ID", "APP_STORE_CONNECT_API_KEY_P8")
    if not all(os.environ.get(name, "").strip() for name in names):
        fail(
            "missing ASC credentials — set APP_STORE_CONNECT_API_KEY_ID, "
            "APP_STORE_CONNECT_ISSUER_ID, APP_STORE_CONNECT_API_KEY_P8"
        )


def asc_from_environment(*, read_only: bool = False) -> asc_cli.Asc:
    """asc with the release credentials; read_only makes asc refuse every write before it is sent."""
    load_credentials()
    return asc_cli.Asc(read_only=read_only)


def call(asc: asc_cli.Asc, *args: str) -> Any:
    """Run asc and stop the release with a readable error when it fails."""
    try:
        return asc.run(*args)
    except asc_cli.AscError as exc:
        fail(str(exc))


def find_app(asc: asc_cli.Asc, bundle_id: str, app_id: str = ASC_APP_ID) -> str:
    """The pinned App Store Connect app, after checking it carries exactly bundle_id.

    Refuses anything but ABYSM's app: the record must be the pinned one and
    report exactly this bundle id (a record without one never matches).
    """
    record = data(call(asc, "apps", "view", "--id", app_id)) or {}
    if record.get("id") != app_id:
        fail(f"App Store Connect returned app {record.get('id')!r}, expected {app_id}")
    found = attrs(record).get("bundleId")
    if found != bundle_id:
        fail(f"App Store Connect app {app_id} has bundle id {found!r}, expected {bundle_id}")
    return app_id


def version_state(version: dict[str, Any]) -> str:
    a = attrs(version)
    return a.get("appStoreState") or a.get("appVersionState") or ""


def list_ios_app_store_versions(asc: asc_cli.Asc, app_id: str) -> list[dict[str, Any]]:
    """Every iOS App Store version of the app."""
    return rows(call(asc, "versions", "list", "--app", app_id, "--platform", PLATFORM, "--paginate"))


def get_ios_app_store_version(asc: asc_cli.Asc, app_id: str, version_string: str) -> dict[str, Any]:
    versions = list_ios_app_store_versions(asc, app_id)
    matches = [row for row in versions if attrs(row).get("versionString") == version_string]
    if not matches:
        fail(
            f"no iOS App Store version {version_string!r} for app {app_id} "
            "(turn on IOS_CREATE_VERSION, or create the version in App Store Connect first: "
            f"add iOS version {version_string} and leave it in Prepare for Submission, then rerun)"
        )
    if len(matches) > 1:
        fail(f"ambiguous App Store versions for {version_string!r}: {len(matches)} records")
    return matches[0]


def version_localizations(asc: asc_cli.Asc, version_id: str, locale: str | None = None) -> list[dict[str, Any]]:
    args = ["localizations", "list", "--version", version_id, "--paginate"]
    if locale:
        args += ["--locale", locale]
    return rows(call(asc, *args))


def version_localization(asc: asc_cli.Asc, version_id: str, locale: str) -> dict[str, Any]:
    """The version's localization for exactly `locale`."""
    for row in version_localizations(asc, version_id, locale):
        if attrs(row).get("locale") == locale:
            return row
    fail(f"no {locale} localization for App Store version {version_id}; add it in App Store Connect first")
    raise AssertionError  # unreachable


def app_infos(asc: asc_cli.Asc, app_id: str) -> list[dict[str, Any]]:
    return rows(call(asc, "apps", "info", "list", "--app", app_id))


def app_info_localizations(asc: asc_cli.Asc, app_id: str, info_id: str, locale: str | None = None) -> list[dict[str, Any]]:
    args = ["localizations", "list", "--app", app_id, "--type", "app-info", "--app-info", info_id, "--paginate"]
    if locale:
        args += ["--locale", locale]
    return rows(call(asc, *args))


def app_info_localization(asc: asc_cli.Asc, app_id: str, info_id: str, locale: str) -> dict[str, Any]:
    """The App Info's localization for exactly `locale`."""
    for row in app_info_localizations(asc, app_id, info_id, locale):
        if attrs(row).get("locale") == locale:
            return row
    fail(f"no {locale} localization for App Info {info_id}; add it in App Store Connect first")
    raise AssertionError  # unreachable


# --- Listing text ------------------------------------------------------------


def listing_locales(metadata_dir: Path) -> list[str]:
    """Locales with a folder under store/metadata/ios/ (one per App Store localization)."""
    ios_dir = metadata_dir / "ios"
    if not ios_dir.is_dir():
        return []
    return sorted(p.name for p in ios_dir.iterdir() if p.is_dir() and not p.name.startswith("."))


def field_values(loc_dir: Path, fields: Iterable[tuple[str, str, int | None]]) -> dict[str, str]:
    values: dict[str, str] = {}
    for attribute, filename, _ in fields:
        value = read_text(loc_dir / filename)
        if value is not None:
            values[attribute] = value
    return values


def check_field_values(locale: str, values: dict[str, str], fields: Iterable[tuple[str, str, int | None]]) -> None:
    for attribute, filename, limit in fields:
        value = values.get(attribute)
        if value is None:
            continue
        if limit is not None and len(value) > limit:
            fail(f"{locale}/{filename} is {len(value)} characters (App Store limit {limit})")
        if attribute in URL_ATTRIBUTES and not re.fullmatch(r"https://\S+", value):
            fail(f"{locale}/{filename} must be a single https:// URL")


def changed_attributes(current: dict[str, Any], wanted: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in wanted.items() if (current.get(k) or "").strip() != v}


def field_args(values: dict[str, str]) -> list[str]:
    """`asc localizations update` flags for these attribute values."""
    args: list[str] = []
    for attribute in sorted(values):
        args += [FIELD_FLAGS[attribute], asc_value(values[attribute])]
    return args


def app_info_state(info: dict[str, Any]) -> str:
    a = attrs(info)
    return a.get("appStoreState") or a.get("state") or ""


def choose_app_info(asc: asc_cli.Asc, app_id: str) -> tuple[dict[str, Any] | None, bool]:
    """The App Info the repo is compared with, and whether a release may change it.

    A version being prepared (or waiting in a draft review submission) has its own
    editable App Info next to the live one. Otherwise the App Info of the version
    in review, or else the live one, is only compared, never changed.
    """
    infos = app_infos(asc, app_id)
    for info in infos:
        if app_info_state(info) in EDITABLE_APP_INFO_STATES:
            return info, True
    in_flight = [info for info in infos if app_info_state(info) not in LIVE_APP_INFO_STATES]
    chosen = (in_flight or infos or [None])[0]
    return chosen, False


def upload_listing(
    asc: asc_cli.Asc,
    *,
    app_id: str,
    version_id: str,
    locale: str,
    metadata_dir: Path,
    include_listing: bool = True,
    include_whats_new: bool = False,
    app_info: tuple[dict[str, Any] | None, bool] | None = None,
    text_editable: bool = True,
    write: bool = True,
    state: str = "",
) -> list[str]:
    """Bring one locale's version text (and, with the listing, App Info) in line with the repo.

    Listing text and What's New are separate switches. Only fields that differ are
    sent, so a re-run changes nothing. When the version's text is locked (already
    submitted) or no App Info is editable, a field that differs fails the run
    instead of being skipped. With write=False (preflight) nothing is sent.
    Returns the fields that differ, as "<locale> <attribute>".
    """
    loc_dir = metadata_dir / "ios" / locale
    fields = (LISTING_FIELDS if include_listing else ()) + ((WHATS_NEW_FIELD,) if include_whats_new else ())
    wanted = field_values(loc_dir, fields)
    version_loc = version_localization(asc, version_id, locale)
    changes = changed_attributes(attrs(version_loc), wanted)
    differing = [f"{locale} {name}" for name in sorted(changes)]
    if changes and not text_editable:
        fail(
            f"{locale}: {', '.join(sorted(changes))} differ from App Store Connect, but the "
            f"version text cannot change while the version is {state or 'locked'}; make the "
            "repo match App Store Connect, or remove the version from review there, then rerun"
        )
    if changes and write:
        call(asc, "localizations", "update", "--id", version_loc["id"], *field_args(changes))
        print(f"  {locale}: updated {', '.join(sorted(changes))}")
    elif changes:
        print(f"  {locale}: would update {', '.join(sorted(changes))}")
    else:
        print(f"  {locale}: version text already matches the repo")

    if not include_listing:
        return differing
    info_wanted = field_values(loc_dir, APP_INFO_FIELDS)
    if not info_wanted:
        return differing
    info, info_editable = app_info if app_info is not None else choose_app_info(asc, app_id)
    if info is None:
        fail(f"App Store Connect returned no App Info for app {app_id}")
        raise AssertionError  # unreachable
    info_loc = app_info_localization(asc, app_id, info["id"], locale)
    info_changes = changed_attributes(attrs(info_loc), info_wanted)
    differing += [f"{locale} {name}" for name in sorted(info_changes)]
    if not info_changes:
        print(f"  {locale}: App Info already matches the repo")
    elif not (info_editable and text_editable):
        # Name, subtitle and privacy URL can only change while a new version is prepared.
        fail(
            f"{locale}: App Info fields {', '.join(sorted(info_changes))} differ from App Store "
            f"Connect but no App Info is editable (state {app_info_state(info) or 'unknown'}); "
            "prepare the new version first"
        )
    elif write:
        call(asc, "localizations", "update", "--type", "app-info", "--id", info_loc["id"], *field_args(info_changes))
        print(f"  {locale}: updated App Info {', '.join(sorted(info_changes))}")
    else:
        print(f"  {locale}: would update App Info {', '.join(sorted(info_changes))}")
    return differing


# --- Screenshots ---------------------------------------------------------------


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        fail(f"{path.name} is not a PNG file")
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


def screenshot_plan(
    sets: Iterable[tuple[str, Path, frozenset[tuple[int, int]]]] = SCREENSHOT_SETS,
) -> list[tuple[str, list[Path]]]:
    """Validate the App Store-ready images; fail clearly if any set is missing or wrong."""
    plan: list[tuple[str, list[Path]]] = []
    for display_type, folder, accepted in sets:
        shown = folder.relative_to(ROOT) if folder.is_relative_to(ROOT) else folder
        pngs = sorted(folder.glob("*.png")) if folder.is_dir() else []
        if not pngs:
            fail(
                f"IOS_UPLOAD_SCREENSHOTS is on but {shown}/ has no PNG screenshots for "
                f"{display_type}; add App Store-ready images or turn the switch off"
            )
        if len(pngs) > APP_SCREENSHOT_SET_MAX:
            fail(f"{shown}/ has {len(pngs)} PNGs; App Store Connect allows {APP_SCREENSHOT_SET_MAX}")
        if display_type not in DEVICE_TYPES:
            fail(f"no asc device type for {display_type}")
        sizes = ", ".join(f"{w}x{h}" for w, h in sorted(accepted))
        for path in pngs:
            size = png_size(path)
            if size not in accepted:
                fail(f"{shown}/{path.name} is {size[0]}x{size[1]}; {display_type} accepts {sizes}")
        plan.append((display_type, pngs))
    return plan


def screenshot_alpha_problem(plan: list[tuple[str, list[Path]]]) -> str | None:
    """Why asc would refuse these screenshots, or None when it would not.

    asc uploads no PNG that stores an alpha channel or transparency (colour types
    4 and 6, or a tRNS chunk), even when every pixel is opaque. Run on the staged
    copies, it is the last check on exactly what asc is given.
    """
    found = []
    for display_type, pngs in plan:
        names = [path.name for path in pngs if asc_cli.image_has_alpha(path)]
        if names:
            found.append(f"{display_type}: {', '.join(names)}")
    if not found:
        return None
    return (
        "these screenshots store an alpha channel, which App Store Connect refuses (asc uploads no PNG with "
        f"alpha, even a fully opaque one): {'; '.join(found)}; not uploading them"
    )


def try_import_pillow():
    """Pillow's Image module, or None when Pillow is not installed."""
    try:
        from PIL import Image  # type: ignore[import-untyped]
    except ImportError:
        return None
    return Image


def opaque_rgb(Image, img):
    """The image without an alpha channel, transparent pixels laid over black.

    App Store Connect (and asc) refuse screenshots that store alpha, even when
    every pixel is opaque.
    """
    img = img.convert("RGBA")
    canvas = Image.new("RGB", img.size, (0, 0, 0))
    canvas.paste(img, mask=img.getchannel("A"))
    return canvas


def stage_screenshots(plan: list[tuple[str, list[Path]]], dest: Path) -> list[tuple[str, list[Path]]]:
    """Copies of the screenshots in dest, exactly as asc will upload them; the repo's files never change.

    A PNG that stores alpha, which asc refuses, is converted to RGB with Pillow
    (transparent pixels laid over black, any colour profile kept); any other
    file is copied byte for byte. App Store Connect stores the checksum of what
    was uploaded, so the set checks compare against these copies. Pillow writes
    the same bytes for the same image on every run, but a Pillow update can
    change them, and the next run then uploads the sets again.
    """
    Image = None
    staged: list[tuple[str, list[Path]]] = []
    for display_type, pngs in plan:
        folder = dest / display_type
        folder.mkdir(parents=True)
        copies = []
        for path in pngs:
            copy = folder / path.name
            if not asc_cli.image_has_alpha(path):
                shutil.copyfile(path, copy)
            else:
                Image = Image or try_import_pillow()
                if Image is None:
                    fail(
                        f"{display_type}: {path.name} stores an alpha channel, which App Store Connect refuses, and "
                        "converting it to RGB needs Pillow: python3 -m pip install --require-hashes -r "
                        "requirements-store.txt"
                    )
                try:
                    with Image.open(path) as img:
                        opaque_rgb(Image, img).save(copy, format="PNG", icc_profile=img.info.get("icc_profile"))
                except (OSError, SyntaxError, ValueError) as exc:
                    fail(f"{display_type}: could not convert {path.name} to RGB: {exc}")
            copies.append(copy)
        staged.append((display_type, copies))
    return staged


def md5_hex(path: Path) -> str:
    """The checksum App Store Connect stores as an uploaded screenshot's sourceFileChecksum."""
    return hashlib.md5(path.read_bytes()).hexdigest()  # noqa: S324 - Apple's checksum


def live_screenshot_sets(asc: asc_cli.Asc, version_loc_id: str) -> dict[str, list[dict[str, Any]]]:
    """Display type -> the screenshots App Store Connect holds in that set, in order."""
    payload = call(asc, "screenshots", "list", "--version-localization", version_loc_id)
    live: dict[str, list[dict[str, Any]]] = {}
    for entry in (payload or {}).get("sets") or []:
        live[attrs(entry.get("set")).get("screenshotDisplayType")] = list(entry.get("screenshots") or [])
    return live


def screenshot_set_problem(shots: list[dict[str, Any]] | None, pngs: list[Path]) -> str | None:
    """Why the set does not already hold the repo's images, or None when it does.

    The set matches only when it holds the repo's images (same checksums, same
    order) and App Store Connect has processed every one (assetDeliveryState
    COMPLETE). An upload's sourceFileChecksum is stored when it is committed,
    before Apple processes the image, so a set left by a failed or timed-out wait
    already has the repo's checksums but an image that is FAILED or still
    processing. Such a set must be uploaded again, never taken as done.
    """
    if shots is None:
        return "are missing"
    if [attrs(s).get("sourceFileChecksum") for s in shots] != [md5_hex(p) for p in pngs]:
        return "differ from the repo"
    unprocessed = []
    for shot in shots:
        a = attrs(shot)
        state = (a.get("assetDeliveryState") or {}).get("state")
        if state != "COMPLETE":
            unprocessed.append(f"{a.get('fileName') or shot.get('id')}: {state or 'no processing state'}")
    if unprocessed:
        return f"match the repo but are not all processed by App Store Connect ({', '.join(unprocessed)})"
    return None


def upload_screenshot_set(asc: asc_cli.Asc, version_loc_id: str, display_type: str, pngs: list[Path]) -> None:
    """Replace one set with exactly these images, in file-name order.

    asc uploads every file in the folder it is given, so the images are copied
    into a folder of their own first. --replace deletes the set's screenshots
    before uploading; asc keeps the file order and waits until Apple has
    processed each image. A failure part-way leaves a set that differs from the
    repo, so a re-run replaces it again.
    """
    with tempfile.TemporaryDirectory(prefix="abysm-screenshots-") as tmp:
        for path in pngs:
            shutil.copyfile(path, Path(tmp) / path.name)
        call(
            asc, "screenshots", "upload", "--version-localization", version_loc_id, "--path", tmp,
            "--device-type", DEVICE_TYPES[display_type], "--replace", "--confirm",
        )


def wait_for_screenshots(
    asc: asc_cli.Asc,
    version_loc_id: str,
    uploaded: list[tuple[str, list[Path]]],
    *,
    timeout: float = SCREENSHOT_PROCESSING_TIMEOUT_SECONDS,
    poll_seconds: float = SCREENSHOT_PROCESSING_POLL_SECONDS,
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Wait until every uploaded set holds the repo's images and Apple has processed each one.

    asc already waits for each image while uploading; this reads the sets back,
    so the run never passes on a set that holds other images, has an image Apple
    rejected, or is still processing at the deadline.
    """
    deadline = now() + timeout
    while True:
        live = live_screenshot_sets(asc, version_loc_id)
        pending = 0
        for display_type, pngs in uploaded:
            shots = live.get(display_type) or []
            if [attrs(s).get("sourceFileChecksum") for s in shots] != [md5_hex(p) for p in pngs]:
                fail(f"after uploading, App Store Connect's {display_type} set does not hold the repo's images")
            for shot in shots:
                delivery = attrs(shot).get("assetDeliveryState") or {}
                state = delivery.get("state")
                if state == "FAILED":
                    errors = "; ".join(e.get("description") or e.get("code") or "?" for e in delivery.get("errors") or [])
                    fail(f"App Store Connect rejected screenshot {attrs(shot).get('fileName') or shot.get('id')}: "
                         f"{errors or 'FAILED'}")
                if state != "COMPLETE":
                    pending += 1
        if not pending:
            return
        if now() >= deadline:
            fail(f"timed out waiting for App Store Connect to process {pending} screenshot(s)")
        sleep(poll_seconds)


def upload_screenshots(
    asc: asc_cli.Asc,
    *,
    version_id: str,
    locale: str,
    plan: list[tuple[str, list[Path]]],
    wait: Callable[[Any, str, list[tuple[str, list[Path]]]], None] = wait_for_screenshots,
    editable: bool = True,
    write: bool = True,
    state: str = "",
) -> list[str]:
    """Make each display type's set hold exactly the repo's images, in file-name order.

    A set that already holds them (same checksums, same order) and whose images
    App Store Connect has all processed is left alone, so a re-run uploads
    nothing. Any other set, including one with an image that failed or is still
    processing after an earlier attempt, is replaced only while screenshots are
    editable; otherwise the run fails. With write=False (preflight) nothing is
    sent. Returns the display types that differ.
    """
    version_loc = version_localization(asc, version_id, locale)
    live = live_screenshot_sets(asc, version_loc["id"])
    differing: list[str] = []
    uploaded: list[tuple[str, list[Path]]] = []
    for display_type, pngs in plan:
        problem = screenshot_set_problem(live.get(display_type), pngs)
        if problem is None:
            print(f"  {display_type} ({locale}): {len(pngs)} screenshot(s) already match the repo")
            continue
        differing.append(display_type)
        if not editable:
            fail(
                f"{display_type} ({locale}) screenshots {problem}; screenshots cannot change while the "
                f"version is {state or 'locked'}, so remove the version from its review submission in "
                "App Store Connect (or turn IOS_UPLOAD_SCREENSHOTS off), then rerun"
            )
        if not write:
            print(f"  {display_type} ({locale}): screenshots {problem}; would replace the set with {len(pngs)} screenshot(s)")
            continue
        print(f"  {display_type} ({locale}): screenshots {problem}; replacing the set with {len(pngs)} screenshot(s)")
        upload_screenshot_set(asc, version_loc["id"], display_type, pngs)
        uploaded.append((display_type, pngs))
    if uploaded:
        wait(asc, version_loc["id"], uploaded)
        print(f"  {sum(len(pngs) for _, pngs in uploaded)} screenshot(s) processed by App Store Connect")
    return differing


# --- Creative assets -------------------------------------------------------------


def image_dimensions(path: Path) -> tuple[str | None, int, int]:
    """(format, width, height) of a PNG or JPEG, read from its headers."""
    raw = Path(path).read_bytes()
    if raw.startswith(asc_cli.PNG_SIGNATURE) and len(raw) >= 24:
        return "png", int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big")
    if raw[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(raw):
            if raw[i] != 0xFF:
                i += 1
                continue
            marker = raw[i + 1]
            if marker == 0xFF or marker in (0x01, 0xD8) or 0xD0 <= marker <= 0xD7:
                i += 1 if marker == 0xFF else 2
                continue
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                return "jpeg", int.from_bytes(raw[i + 7:i + 9], "big"), int.from_bytes(raw[i + 5:i + 7], "big")
            i += 2 + int.from_bytes(raw[i + 2:i + 4], "big")
    return None, 0, 0


def creative_size_problem(placement_type: str, path: Path) -> str | None:
    """Why Apple would refuse this image for the slot, or None when it fits."""
    kind, width, height = image_dimensions(path)
    if kind is None:
        return "is not a PNG or JPEG"
    if kind == "png" and (width, height) == UNIVERSAL_CREATIVE_SIZE:
        return None
    if placement_type == "PRODUCT_PAGE_HEADER_ASSET":
        if kind != "png" or (width, height) != (3840, 1646):
            return f"is a {width}x{height} {kind.upper()}; the header must be a 3840x1646 PNG"
        return None
    if not (1920 <= width <= 3840 and width * 2 == height * 3):
        return f"is {width}x{height}; search results images are 3:2, from 1920x1280 to 3840x2560"
    return None


def creative_sources(creative_dir: Path) -> list[tuple[str, str, Path]]:
    """(placement type, label, image) for every creative slot that has an image."""
    found = []
    for folder, placement_type, label in CREATIVE_SLOTS:
        slot_dir = creative_dir / folder
        images = sorted(
            p for p in slot_dir.glob("*") if p.is_file() and p.suffix.lower() in CREATIVE_EXTENSIONS
        ) if slot_dir.is_dir() else []
        if len(images) > 1:
            fail(f"the {label} slot takes one image; {slot_dir} has {len(images)}")
        if images and asc_cli.image_has_alpha(images[0]):
            fail(f"the {label} image {images[0].name} has an alpha channel, which App Store Connect refuses; re-export it as RGB")
        problem = creative_size_problem(placement_type, images[0]) if images else None
        if problem:
            fail(f"the {label} image {images[0].name} {problem}")
        if images:
            found.append((placement_type, label, images[0]))
    if not found:
        fail(f"creative asset upload is on, but {creative_dir} has no header or search results image")
    return found


def library_images(asc: asc_cli.Asc, library_id: str) -> list[dict[str, Any]]:
    return rows(
        call(asc, "asset-library", "images", "list", "--library-id", library_id, "--category", "CREATIVE_ASSETS", "--paginate")
    )


def library_image_for(images: list[dict[str, Any]], path: Path) -> dict[str, Any] | None:
    """The newest usable library image uploaded from this exact file (name and size)."""
    size = path.stat().st_size
    matches = [
        image
        for image in images
        if attrs(image).get("fileName") == path.name
        and attrs(image).get("fileSize") == size
        and attrs(image).get("state") not in CREATIVE_DEAD_STATES
    ]
    rejected = [
        image
        for image in images
        if attrs(image).get("fileName") == path.name
        and attrs(image).get("fileSize") == size
        and attrs(image).get("state") == "REJECTED"
    ]
    if not matches and rejected:
        fail(
            f"App Review rejected {path.name}; replace the image (a new file name) and re-run. "
            f"Details: {json.dumps(attrs(rejected[0]).get('stateDetails'))}"
        )
    return max(matches, key=lambda image: attrs(image).get("createdDate") or "") if matches else None


def sync_creative_assets(
    asc: asc_cli.Asc,
    *,
    app_id: str,
    version_id: str,
    locale: str,
    creative_dir: Path,
    editable: bool,
    write: bool = True,
    state: str = "",
    reserved_draft: str | None = None,
) -> dict[str, str]:
    """Put the repository's header and search results images on the version.

    An image is uploaded to the Asset Library once (matched by file name and size)
    and reviewed on its own. Only approved images are placed, because a version
    that is already approved only takes approved assets; one that is still in
    review or not yet submitted is placed on a later run. Nothing changes while
    the version is locked (in a review submission): an image that would have to
    be uploaded or sent to App Review then fails the run, and an approved image
    waits until the version can be edited. With write=False (preflight) nothing
    is sent. Returns placement type -> outcome.
    """
    sources = creative_sources(creative_dir)
    library_id = (data(call(asc, "asset-library", "view", "--app", app_id)) or {}).get("id")
    if not library_id:
        fail(f"App Store Connect returned no Asset Library for app {app_id}")
    images = library_images(asc, library_id)
    version_loc = version_localization(asc, version_id, locale)
    locked = f"while the version is {state or 'locked'}"
    outcomes: dict[str, str] = {}
    to_review: list[tuple[str, dict[str, Any]]] = []
    for placement_type, label, path in sources:
        image = library_image_for(images, path)
        if image is None:
            if not editable:
                fail(f"cannot upload the {label} image {path.name} {locked}")
            if not write:
                outcomes[placement_type] = "would upload and submit for review"
                print(f"  {label}: would upload {path.name} to the Asset Library and send it to App Review")
                continue
            # asc waits for processing and prints a receipt (imageId, ready, state).
            receipt = call(asc, "asset-library", "images", "upload", "--library-id", library_id, "--file", str(path))
            if not receipt.get("imageId") or not receipt.get("ready"):
                fail(f"Apple did not finish processing the {label} image {path.name}: {json.dumps(receipt)}")
            image = {"id": receipt["imageId"], "attributes": {"fileName": path.name, "state": receipt.get("state")}}
            print(f"  uploaded {path.name} to the Asset Library ({image['id']})")
        image_state = attrs(image).get("state") or ""
        if image_state in CREATIVE_UNSUBMITTED_STATES or not image_state:
            if not editable:
                fail(
                    f"cannot send the {label} image {path.name} to App Review {locked}; re-run once the "
                    "version can be edited, or submit it in App Store Connect"
                )
            if not write:
                outcomes[placement_type] = "would submit for review"
                print(f"  {label}: would send {path.name} to App Review")
                continue
            to_review.append((label, image))
            outcomes[placement_type] = "submitted for review"
            continue
        if image_state in CREATIVE_PENDING_STATES:
            outcomes[placement_type] = f"in App Review ({image_state}); placed on a later run"
            print(f"  {label}: {path.name} is {image_state}; it is placed once App Review approves it")
            continue
        if image_state != "APPROVED":
            fail(f"the {label} image {path.name} is {image_state}; resolve it in App Store Connect")
        current = rows(
            call(
                asc, "localizations", "placements", "list", "--localization-id", version_loc["id"],
                "--placement-type", placement_type, "--include", "image",
            )
        )
        if any(related_id(row, "image") == image["id"] for row in current):
            outcomes[placement_type] = "already placed"
            print(f"  {label}: {path.name} is already on the product page")
            continue
        if not editable:
            # Approval can land between a submit and a rerun; that is not a
            # mismatch, so the rerun passes and placement waits for an editable version.
            outcomes[placement_type] = "approved; placed once the version can be edited"
            print(f"  {label}: {path.name} is approved; it is placed on a later run, once the version can be edited")
            continue
        if not write:
            outcomes[placement_type] = "would place"
            print(f"  {label}: would place {path.name} on the product page")
            continue
        if current:
            call(
                asc, "localizations", "placements", "swap", "--localization-id", version_loc["id"],
                "--image-id", image["id"], "--placement-type", placement_type, "--placement-id", current[0]["id"],
                "--confirm",
            )
        else:
            call(
                asc, "localizations", "placements", "create", "--localization-id", version_loc["id"],
                "--image-id", image["id"], "--placement-type", placement_type, "--placement-group", "DEFAULT_PROFILE",
            )
        outcomes[placement_type] = "placed"
        print(f"  {label}: placed {path.name} on the product page")
    if to_review:
        submit_creative_review(asc, app_id, to_review, reserved_draft=reserved_draft)
    return outcomes


def submit_creative_review(
    asc: asc_cli.Asc, app_id: str, images: list[tuple[str, dict[str, Any]]], *, reserved_draft: str | None = None
) -> str:
    """Send not-yet-reviewed creative images to App Review in a submission of their own.

    A draft an earlier attempt left behind holding only some of these images is
    finished first, else an empty one, instead of starting another, so reruns
    leave no extra drafts. The draft this run chose for the version and its
    products (reserved_draft) is never taken.
    """
    wanted = {image["id"] for _, image in images}
    partial = empty = None
    for draft in draft_submission_ids(asc, app_id):
        if draft == reserved_draft:
            continue
        # A version or product item adds an empty id, which is never wanted.
        held = {related_id(item, "appAssetLibraryImage") for item in submission_items(asc, draft)}
        if not held:
            empty = empty or draft
        elif held <= wanted:
            partial = draft
            break
    submission_id = partial or empty
    if submission_id:
        print(f"  finishing creative review submission {submission_id} from an earlier attempt")
    else:
        submission_id = create_draft_submission(asc, app_id)
    for label, image in images:
        call(
            asc, "review", "items-add", "--submission", submission_id, "--item-type", "appAssetLibraryImages",
            "--item-id", image["id"], "--if-exists", "skip",
        )
        print(f"  {label}: {attrs(image).get('fileName')} added to creative review submission {submission_id}")
    items = submission_items(asc, submission_id)
    unexpected = [item["id"] for item in items if related_id(item, "appAssetLibraryImage") not in wanted]
    if unexpected or len(items) != len(images):
        fail(f"review submission {submission_id} holds unexpected items {unexpected}; not submitting it")
    submit_review_submission(asc, submission_id)
    print(f"  submitted {len(images)} creative image(s) for App Review ({submission_id})")
    return submission_id


# --- In-app purchases ----------------------------------------------------------


def load_catalog(path: Path = CATALOG) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def intended_product_ids(catalog: dict[str, Any] | None = None) -> set[str]:
    """Product ids the release may submit, from store/catalog/products.json."""
    catalog = load_catalog() if catalog is None else catalog
    ids: set[str] = set()
    for group in CATALOG_GROUPS:
        for item in catalog.get(group) or []:
            pid = item.get("id")
            if isinstance(pid, str) and pid:
                ids.add(pid)
    return ids


class ProductSubmitError(Exception):
    """A required product could not be added to App Review."""


class ProductAttachResult:
    """Catalog products in a draft review submission after attach_catalog_products()."""

    def __init__(
        self, submission_id: str, attached: int, added_items: bool, allowed_versions: set[str] | None = None
    ) -> None:
        self.submission_id = submission_id
        # Products in the draft now, attached by this call or by an earlier attempt.
        self.attached = attached
        self.added_items = added_items
        # Every version of every catalog product: the only product items a draft
        # may hold when it is submitted.
        self.allowed_versions = allowed_versions or set()


# Subscription states that can still be (re)attached to a review.
SUBMITTABLE_SUBSCRIPTION_STATES = {"READY_TO_SUBMIT", "DEVELOPER_REJECTED", "READY_FOR_REVIEW"}
# One-time purchases ("Unlock the Deep") are attached only while Ready to Submit.
SUBMITTABLE_IAP_STATES = {"READY_TO_SUBMIT"}
# Review submission item relationships asc is asked to include.
ITEM_RELATIONSHIPS = ("appStoreVersion", "subscriptionVersion", "inAppPurchaseVersion", "appAssetLibraryImage")


def draft_submission_ids(asc: asc_cli.Asc, app_id: str) -> list[str]:
    """The app's READY_FOR_REVIEW (draft) iOS review submissions."""
    payload = call(
        asc, "review", "submissions-list", "--app", app_id, "--platform", PLATFORM, "--state", "READY_FOR_REVIEW",
        "--paginate",
    )
    return [row["id"] for row in rows(payload) if row.get("id")]


def submission_items(asc: asc_cli.Asc, submission_id: str) -> list[dict[str, Any]]:
    """The submission's items with their related ids (asc asks for them explicitly)."""
    return rows(
        call(
            asc, "review", "items-list", "--submission", submission_id, "--include", ",".join(ITEM_RELATIONSHIPS),
            "--paginate",
        )
    )


def find_draft_submission(asc: asc_cli.Asc, app_id: str, version_id: str | None = None) -> str | None:
    """The app's draft review submission to use for the version and its products, if there is one.

    The draft already holding version_id wins. Otherwise only a draft holding no
    app version is reused, so another version's draft is never touched. A draft
    holding creative images belongs to their own review and is skipped.
    """
    drafts = []
    for submission_id in draft_submission_ids(asc, app_id):
        items = submission_items(asc, submission_id)
        if not any(related_id(item, "appAssetLibraryImage") for item in items):
            drafts.append((submission_id, {related_id(item, "appStoreVersion") for item in items} - {None, ""}))
    if version_id:
        for submission_id, versions in drafts:
            if version_id in versions:
                return submission_id
    for submission_id, versions in drafts:
        if not versions:
            return submission_id
    return None


def create_draft_submission(asc: asc_cli.Asc, app_id: str) -> str:
    created = data(call(asc, "review", "submissions-create", "--app", app_id, "--platform", PLATFORM)) or {}
    if not created.get("id"):
        fail("asc did not report the new review submission's id")
    return created["id"]


def get_or_create_draft_submission(asc: asc_cli.Asc, app_id: str, version_id: str | None = None) -> str:
    """Return the app's draft review submission for the version and products, creating one."""
    return find_draft_submission(asc, app_id, version_id) or create_draft_submission(asc, app_id)


def draft_item_version_ids(asc: asc_cli.Asc, submission_id: str) -> set[str]:
    """App, subscription and in-app purchase version ids already attached to a draft."""
    ids: set[str] = set()
    for item in submission_items(asc, submission_id):
        for name in ITEM_RELATIONSHIPS[:3]:
            found = related_id(item, name)
            if found:
                ids.add(found)
    return ids


def submit_review_submission(asc: asc_cli.Asc, submission_id: str) -> None:
    """Send a draft review submission, and everything in it, to App Review."""
    call(asc, "review", "submissions-submit", "--id", submission_id, "--confirm")


def newest_version_id(versions: list[dict[str, Any]]) -> str | None:
    """A product's in-flight version (one per product; the highest number wins)."""
    numbered = [v for v in versions if attrs(v).get("version")]
    if not numbered:
        return versions[0]["id"] if versions else None
    return max(numbered, key=lambda v: v["attributes"]["version"])["id"]


def catalog_review_items(
    asc: asc_cli.Asc, app_id: str, intended_ids: set[str]
) -> tuple[list[tuple[str, str, str]], list[str], set[str]]:
    """Ready-to-Submit catalog products and the review item each needs (reads only).

    Returns ([(label, review item type, version id)], problems, allowed version
    ids). Only products listed in store/catalog/products.json are considered,
    and approved products are never resubmitted. The allowed version ids are
    every version of every catalog product, in any state: the only product items
    a draft may hold when it is submitted.
    """
    items: list[tuple[str, str, str]] = []
    problems: list[str] = []
    allowed: set[str] = set()
    products = [
        ("subscription", "subscriptionVersions", SUBMITTABLE_SUBSCRIPTION_STATES, sub,
         ("subscriptions", "versions", "list", "--subscription-id", sub["id"], "--paginate"))
        for sub in rows(call(asc, "subscriptions", "list", "--app", app_id, "--paginate"))
    ] + [
        ("in-app purchase", "inAppPurchaseVersions", SUBMITTABLE_IAP_STATES, iap,
         ("iap", "versions", "list", "--iap-id", iap["id"], "--paginate"))
        for iap in rows(call(asc, "iap", "list", "--app", app_id, "--paginate"))
    ]
    for kind, item_type, submittable, product, versions_query in products:
        a = attrs(product)
        pid = a.get("productId") or ""
        if pid not in intended_ids:
            continue
        versions = rows(call(asc, *versions_query))
        allowed |= {v["id"] for v in versions if v.get("id")}
        if a.get("state") not in submittable:
            continue
        label = f"{kind} {a.get('name') or product['id']} ({pid})"
        version_id = newest_version_id(versions)
        if version_id:
            items.append((label, item_type, version_id))
        else:
            problems.append(f"{label}: no version to submit")
    return items, problems, allowed


def attach_catalog_products(
    asc: asc_cli.Asc,
    app_id: str,
    *,
    intended_ids: set[str] | None = None,
    submission_id: str | None = None,
) -> ProductAttachResult:
    """Attach Ready-to-Submit catalog products to the app's draft review submission.

    Nothing goes to App Review here. Subscriptions (`subscriptionVersions`) and
    one-time purchases (`inAppPurchaseVersions`; ABYSM's "Unlock the Deep" is a
    non-consumable) become items of the same draft as the app version, and the
    single submit after the final build recheck sends them all together. The
    deprecated `inAppPurchaseSubmissions` endpoint, which sends a product to review
    on its own straight away, is never used. Items already in the draft are
    skipped, so a retry adds nothing twice. Without a submission_id the app's
    existing draft is used, and a draft is created only when something needs one.
    """
    if intended_ids is None:
        intended_ids = intended_product_ids()
    if not intended_ids:
        print("  catalog has no products to submit")
        return ProductAttachResult(submission_id or "", 0, False)
    items, failures, allowed = catalog_review_items(asc, app_id, intended_ids)
    if submission_id is None:
        submission_id = find_draft_submission(asc, app_id)
    already_attached = draft_item_version_ids(asc, submission_id) if submission_id else set()
    attached = 0
    added_items = False
    for label, item_type, version_id in items:
        if version_id in already_attached:
            attached += 1
            print(f"  {label}: already in the review submission")
            continue
        if submission_id is None:
            submission_id = create_draft_submission(asc, app_id)
        try:
            asc.run(
                "review", "items-add", "--submission", submission_id, "--item-type", item_type,
                "--item-id", version_id, "--if-exists", "skip",
            )
        except asc_cli.AscError as exc:
            failures.append(f"{label}: {exc}")
            continue
        attached += 1
        added_items = True
        print(f"  {label}: attached to the review submission")

    print(f"  catalog products in the review submission: {attached}")
    if failures:
        raise ProductSubmitError(
            "these required products were not added to App Review: "
            + "; ".join(failures)
            + ". Resolve them in App Store Connect and rerun the release."
        )
    return ProductAttachResult(submission_id or "", attached, added_items, allowed)


def check_draft_items(
    asc: asc_cli.Asc, submission_id: str, *, version_id: str | None, allowed_products: set[str]
) -> None:
    """Refuse to submit a draft holding anything but this version and catalog products.

    A reused draft can hold items added by hand or by another tool; they must
    not ride along into App Review.
    """
    unexpected = []
    items = submission_items(asc, submission_id)
    if version_id and not any(related_id(item, "appStoreVersion") == version_id for item in items):
        fail(f"review submission {submission_id} does not hold App Store version {version_id}; not submitting it")
    for item in items:
        app_version = related_id(item, "appStoreVersion")
        product = related_id(item, "subscriptionVersion") or related_id(item, "inAppPurchaseVersion")
        if app_version and app_version == version_id:
            continue
        if product and not app_version and product in allowed_products:
            continue
        unexpected.append(item.get("id"))
    if unexpected:
        fail(
            f"review submission {submission_id} holds items this release did not choose ({', '.join(map(str, unexpected))}); "
            "remove them in App Store Connect and rerun"
        )


# --- Build selection and review ------------------------------------------------

RELEASE_TYPE_PUBLIC = "AFTER_APPROVAL"
RELEASE_TYPE_MANUAL = "MANUAL"


def verify_build(asc: asc_cli.Asc, build_id: str, version_string: str, build_number: str) -> None:
    """Re-read the build and refuse anything but this run's processed build."""
    payload = call(
        asc, "builds", "list", "--app", ASC_APP_ID, "--build-number", build_number, "--version", version_string,
        "--platform", PLATFORM, "--processing-state", "all", "--include", "preReleaseVersion",
    )
    included = {(row.get("type"), row.get("id")): row for row in (payload or {}).get("included") or []}
    build = next((row for row in rows(payload) if row.get("id") == build_id), None)
    problems = []
    if build is None:
        problems.append("not listed for this app, version and build number")
    else:
        a = attrs(build)
        pre = attrs(included.get(("preReleaseVersions", related_id(build, "preReleaseVersion"))))
        if a.get("version") != build_number:
            problems.append(f"build number {a.get('version')!r}")
        if a.get("processingState") != "VALID":
            problems.append(f"processing state {a.get('processingState')!r}")
        if a.get("expired"):
            problems.append("expired")
        if pre.get("version") != version_string or pre.get("platform") != PLATFORM:
            problems.append(f"version {pre.get('platform')} {pre.get('version')!r}")
    if problems:
        fail(f"build {build_id} is not {version_string} ({build_number}), VALID and unexpired: " + ", ".join(problems))


def attached_build_id(asc: asc_cli.Asc, version_id: str) -> str | None:
    payload = call(asc, "versions", "view", "--version-id", version_id, "--include", "build")
    return related_id(data(payload) or {}, "build")


def confirm_selected_build(asc: asc_cli.Asc, version_id: str, build_id: str) -> None:
    current = attached_build_id(asc, version_id)
    if current != build_id:
        fail(f"App Store version {version_id} has build {current or 'none'} selected, expected {build_id}; not submitting")


def select_build(asc: asc_cli.Asc, version_id: str, build_id: str, version_string: str, build_number: str) -> None:
    """Explicitly select this run's build for the version, then read it back."""
    verify_build(asc, build_id, version_string, build_number)
    if attached_build_id(asc, version_id) == build_id:
        # A re-run: the version (possibly already in a draft submission) holds it.
        print(f"  build {build_number} ({build_id}) is already selected for version {version_string}")
    else:
        call(asc, "versions", "attach-build", "--version-id", version_id, "--build-id", build_id)
    confirm_selected_build(asc, version_id, build_id)
    print(f"  selected build {build_number} ({build_id}) for version {version_string}")


def set_release_type(asc: asc_cli.Asc, version_id: str, *, public_release: bool, current: str | None = None) -> None:
    release_type = RELEASE_TYPE_PUBLIC if public_release else RELEASE_TYPE_MANUAL
    label = "automatic after approval" if public_release else "manual release after approval"
    if current == release_type:
        print(f"  release type already {label}")
        return
    call(asc, "versions", "update", "--version-id", version_id, "--release-type", release_type)
    print(f"  release type: {label}")


def submit_for_review(
    asc: asc_cli.Asc,
    app_id: str,
    version_id: str,
    state: str = "",
    *,
    submission_id: str | None = None,
    allowed_products: set[str] | None = None,
) -> None:
    """Add the version to the draft (unless it is there) and submit the draft.

    The draft is submitted only when it holds this version and nothing but
    versions of catalog products besides it, so a product never goes to App
    Review without the version and nothing added by hand rides along.
    """
    # Reuse a draft (an earlier attempt can leave one that was never submitted).
    if submission_id is None:
        submission_id = get_or_create_draft_submission(asc, app_id, version_id)
    if version_id not in draft_item_version_ids(asc, submission_id):
        if state == "READY_FOR_REVIEW":
            # The version already sits in another draft; submitting this one would
            # send its products to App Review without the version.
            fail(
                f"version {version_id} is READY_FOR_REVIEW but not in review submission {submission_id}; "
                "check its draft in App Store Connect, then rerun"
            )
        call(
            asc, "review", "items-add", "--submission", submission_id, "--item-type", "appStoreVersions",
            "--item-id", version_id, "--if-exists", "skip",
        )
    check_draft_items(asc, submission_id, version_id=version_id, allowed_products=allowed_products or set())
    submit_review_submission(asc, submission_id)
    print(f"  submitted App Store version {version_id} for review (submission {submission_id})")


# --- Entry point -----------------------------------------------------------------


def validate_local_inputs(
    *,
    upload_listing: bool,
    upload_whats_new: bool,
    upload_screenshots: bool,
    metadata_dir: Path,
    screenshot_sets: Iterable[tuple[str, Path, frozenset[tuple[int, int]]]] = SCREENSHOT_SETS,
    upload_creative: bool = False,
    creative_dir: Path = CREATIVE_DIR,
) -> tuple[list[str], list[tuple[str, list[Path]]]]:
    """Check every file a live run would send before any App Store Connect call."""
    locales = listing_locales(metadata_dir)
    if (upload_listing or upload_whats_new) and not locales:
        fail(f"no locale folders under {metadata_dir / 'ios'}")
    if upload_listing and PRIMARY_LOCALE not in locales:
        fail(f"the primary locale {PRIMARY_LOCALE} is missing from {metadata_dir / 'ios'}")
    for locale in locales:
        loc_dir = metadata_dir / "ios" / locale
        if upload_listing:
            values = field_values(loc_dir, LISTING_FIELDS)
            if "description" not in values or "keywords" not in values:
                fail(f"{locale} needs description.txt and keywords.txt")
            check_field_values(locale, values, LISTING_FIELDS)
            check_field_values(locale, field_values(loc_dir, APP_INFO_FIELDS), APP_INFO_FIELDS)
        if upload_whats_new:
            value = read_text(loc_dir / WHATS_NEW_FIELD[1])
            if not value:
                fail(f"What's New upload is on, but {locale}/{WHATS_NEW_FIELD[1]} is missing or empty")
            check_field_values(locale, {WHATS_NEW_FIELD[0]: value}, (WHATS_NEW_FIELD,))
    plan = screenshot_plan(screenshot_sets) if upload_screenshots else []
    if upload_creative:
        creative_sources(creative_dir)
    return locales, plan


def version_key(version_string: str) -> tuple[int, ...] | None:
    """1.0.1 -> (1, 0, 1), padded to three parts; None when it is not a plain version."""
    if not re.fullmatch(r"[0-9]+(\.[0-9]+){0,2}", version_string or ""):
        return None
    parts = [int(part) for part in version_string.split(".")]
    return tuple(parts + [0] * (3 - len(parts)))


def ensure_ios_app_store_version(asc: asc_cli.Asc, *, bundle_id: str, version_string: str) -> None:
    """Create the App Store version for this release when it does not exist yet.

    An existing version with this number is left as it is (the preflight then
    checks its state). Nothing is created when another version is still on its
    way to the store, or when this number is not newer than every existing
    version; the created version is read back before the run continues.
    """
    wanted = version_key(version_string)
    if wanted is None:
        fail(f"version {version_string!r} must look like 1.0 or 1.0.1")
    app_id = find_app(asc, bundle_id)  # refuses any app but ABYSM's
    versions = list_ios_app_store_versions(asc, app_id)
    existing = [row for row in versions if attrs(row).get("versionString") == version_string]
    if len(existing) > 1:
        fail(f"ambiguous App Store versions for {version_string!r}: {len(existing)} records")
    if existing:
        print(f"App Store version {version_string} already exists ({version_state(existing[0])}); nothing to create")
        return
    problems: list[str] = []
    for row in versions:
        other = attrs(row).get("versionString") or ""
        state = version_state(row)
        if state not in FINISHED_VERSION_STATES:
            problems.append(
                f"version {other!r} is still {state or 'in an unknown state'}; release or remove it "
                f"in App Store Connect before {version_string} can be created"
            )
        other_key = version_key(other)
        if other_key is not None and other_key >= wanted:
            problems.append(f"version {version_string} is not newer than the existing version {other}")
    if problems:
        fail(f"not creating App Store version {version_string} (nothing was changed):\n  " + "\n  ".join(problems))
    call(asc, "versions", "create", "--app", app_id, "--version", version_string, "--platform", PLATFORM)
    # Read back with its own check: the version was just created, so the generic
    # "version is missing" advice (turn on IOS_CREATE_VERSION) would be wrong here.
    created = [
        row for row in list_ios_app_store_versions(asc, app_id) if attrs(row).get("versionString") == version_string
    ]
    if len(created) != 1:
        fail(
            f"created App Store version {version_string}, but reading it back found {len(created)} records; "
            "check it in App Store Connect before rerunning"
        )
    print(f"created App Store version {version_string} ({version_state(created[0]) or 'state not reported yet'})")


def check_version_state(
    version_string: str, state: str, *, edits_metadata: bool, do_submit: bool, new_build: bool
) -> None:
    """Fail unless the enabled steps can run while the App Store version is in `state`.

    new_build: this run has not uploaded its build yet (--preflight), so a version
    that is already submitted can never take it.
    """
    submitted = state in SUBMITTED_VERSION_STATES
    if do_submit and submitted and new_build:
        fail(
            f"version {version_string!r} is already {state}, so the build this run would upload "
            "cannot be submitted. To finish the run that submitted it, use Re-run failed jobs on "
            "that run; otherwise remove the version from review in App Store Connect first"
        )
    if do_submit and not (submitted or state in SUBMITTABLE_VERSION_STATES):
        fail(f"version {version_string!r} cannot be submitted for review (state={state})")
    if edits_metadata and not (submitted or state in TEXT_EDITABLE_VERSION_STATES):
        fail(
            f"version {version_string!r} is not editable (state={state}); editable states: "
            + ", ".join(sorted(TEXT_EDITABLE_VERSION_STATES))
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--metadata-dir", type=Path, default=METADATA_DIR, help="Listing tree (store/metadata)")
    parser.add_argument(
        "--creative-dir",
        type=Path,
        default=CREATIVE_DIR,
        help="Product page header and search results images: " + ", ".join(s[0] for s in CREATIVE_SLOTS),
    )
    parser.add_argument("--bundle-id", default=DEFAULT_BUNDLE_ID)
    parser.add_argument("--version", help="Marketing version from the release tag (v1.0.1 → 1.0.1)")
    parser.add_argument("--build-id", help="App Store Connect id of the build uploaded by this run (required to submit)")
    parser.add_argument("--build-number", help="CFBundleVersion of the build uploaded by this run (required to submit)")
    parser.add_argument("--dry-run", action="store_true", help="Validate switches and local files only — no asc calls")
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Read-only App Store Connect checks before anything is built (asc in read-only mode)",
    )
    parser.add_argument(
        "--create-version",
        action="store_true",
        help="Create the App Store version for --version when it is missing (CREATE_IOS_VERSION)",
    )
    args = parser.parse_args()
    if args.dry_run and args.preflight:
        fail("--dry-run and --preflight are separate modes; pass only one")
    # find_app() checks the pinned app's bundle id, so only ABYSM is accepted.
    if args.bundle_id != DEFAULT_BUNDLE_ID:
        fail(f"this publisher only supports the ABYSM iOS bundle ({DEFAULT_BUNDLE_ID})")

    if args.create_version:
        if args.preflight:
            fail("--create-version and --preflight are separate modes; pass only one")
        if not truthy("CREATE_IOS_VERSION"):
            print("App Store version creation skipped — CREATE_IOS_VERSION is off")
            return
        if not args.version:
            fail("--create-version needs --version (the marketing version from the tag)")
        # Checked before the dry run returns, so a dry run rejects what a live run would.
        if version_key(args.version) is None:
            fail(f"version {args.version!r} must look like 1.0 or 1.0.1")
        if args.dry_run:
            print(f"App Store Connect dry run — would create App Store version {args.version} if it is missing")
            return
        ensure_ios_app_store_version(asc_from_environment(), bundle_id=args.bundle_id, version_string=args.version)
        return

    do_listing = truthy("UPLOAD_LISTING")
    do_whats_new = truthy("UPLOAD_WHATS_NEW")
    do_screenshots = truthy("UPLOAD_SCREENSHOTS")
    do_creative = truthy("UPLOAD_CREATIVE_ASSETS")
    do_submit = truthy("SUBMIT_IOS_REVIEW")
    do_public = truthy("PUBLIC_RELEASE")

    if not (do_listing or do_whats_new or do_screenshots or do_creative or do_submit):
        print(
            "App Store Connect step skipped — UPLOAD_LISTING / UPLOAD_WHATS_NEW / UPLOAD_SCREENSHOTS / "
            "UPLOAD_CREATIVE_ASSETS / SUBMIT_IOS_REVIEW are off"
        )
        return
    if do_public and not do_submit:
        fail("PUBLIC_RELEASE only applies when SUBMIT_IOS_REVIEW is on")
    # The preflight runs before this run's build exists.
    if do_submit and not args.preflight and not (args.build_id and args.build_number):
        fail("submitting needs --build-id and --build-number for the build uploaded by this run; an older build is never substituted")

    locales, plan = validate_local_inputs(
        upload_listing=do_listing,
        upload_whats_new=do_whats_new,
        upload_screenshots=do_screenshots,
        metadata_dir=args.metadata_dir,
        screenshot_sets=SCREENSHOT_SETS,
        upload_creative=do_creative,
        creative_dir=args.creative_dir,
    )
    if do_submit:
        intended_product_ids()  # the catalog must parse before anything is submitted

    # asc refuses a PNG that stores alpha, so the screenshots go up from copies
    # staged outside the repository, converted to RGB where needed. Every mode
    # stages them, so the dry run and the preflight check what a live run uploads.
    # The folder is removed when the run ends.
    if plan:
        staging = tempfile.TemporaryDirectory(prefix="abysm-screenshots-")
        plan = stage_screenshots(plan, Path(staging.name))
    # The last check on what asc is given, before any asc call.
    alpha = screenshot_alpha_problem(plan)
    if alpha:
        fail(alpha)
    if args.dry_run:
        print("App Store Connect dry run — local inputs OK; no asc calls")
        print(
            f"  bundle={args.bundle_id} locales={','.join(locales) or '-'} listing={do_listing} "
            f"whats_new={do_whats_new} screenshots={sum(len(p) for _, p in plan)} creative={do_creative} "
            f"submit={do_submit} public_release={do_public}"
        )
        return
    if not args.version:
        fail("--version is required for live App Store Connect calls")

    # The preflight only reads: asc refuses every write in read-only mode.
    asc = asc_from_environment(read_only=args.preflight)
    write = not args.preflight
    app_id = find_app(asc, args.bundle_id)
    version = get_ios_app_store_version(asc, app_id, args.version)
    version_id = version["id"]
    state = version_state(version)
    label = "App Store Connect preflight (read-only)" if args.preflight else "App Store Connect"
    print(f"{label}: app={app_id} version={args.version} id={version_id} state={state}")
    edits_metadata = do_listing or do_whats_new or do_screenshots or do_creative
    check_version_state(
        args.version, state, edits_metadata=edits_metadata, do_submit=do_submit, new_build=args.preflight
    )
    submitted = state in SUBMITTED_VERSION_STATES
    # Pick and check the version's draft before any write (text, screenshots,
    # images or the build), so a run that has to stop here changes nothing; the
    # preflight stops on it too.
    submission_id: str | None = None
    if do_submit and not submitted:
        submission_id = find_draft_submission(asc, app_id, version_id)
        if state == "READY_FOR_REVIEW" and (
            submission_id is None
            or not any(related_id(item, "appStoreVersion") == version_id for item in submission_items(asc, submission_id))
        ):
            fail(
                f"version {args.version} is READY_FOR_REVIEW, but no draft review submission holds it; "
                "remove the version from its submission in App Store Connect and rerun"
            )

    if do_submit and submitted:
        # A re-run after this run's submit went through (for example the job failed
        # afterwards): accept it only if review holds exactly this run's build.
        confirm_selected_build(asc, version_id, args.build_id)

    if do_listing or do_whats_new:
        parts = [n for n, on in (("listing", do_listing), ("What's New", do_whats_new)) if on]
        print(f"{'checking' if args.preflight else 'updating'} {' + '.join(parts)} for {', '.join(locales)}…")
        app_info = choose_app_info(asc, app_id) if do_listing else None
        for locale in locales:
            upload_listing(
                asc,
                app_id=app_id,
                version_id=version_id,
                locale=locale,
                metadata_dir=args.metadata_dir,
                include_listing=do_listing,
                include_whats_new=do_whats_new,
                app_info=app_info,
                text_editable=state in TEXT_EDITABLE_VERSION_STATES,
                write=write,
                state=state,
            )

    if do_screenshots:
        print("checking screenshots…" if args.preflight else "uploading screenshots…")
        upload_screenshots(
            asc,
            version_id=version_id,
            locale=PRIMARY_LOCALE,
            plan=plan,
            editable=state in EDITABLE_VERSION_STATES,
            write=write,
            state=state,
        )

    if do_creative:
        print(
            "checking product page header and search results images…" if args.preflight
            else "syncing product page header and search results images…"
        )
        sync_creative_assets(
            asc,
            app_id=app_id,
            version_id=version_id,
            locale=PRIMARY_LOCALE,
            creative_dir=args.creative_dir,
            editable=state in EDITABLE_VERSION_STATES,
            write=write,
            state=state,
            reserved_draft=submission_id,
        )

    if args.preflight:
        if do_submit:
            items, problems, _ = catalog_review_items(asc, app_id, intended_product_ids())
            if problems:
                fail(
                    "these required products cannot be added to App Review: " + "; ".join(problems)
                    + ". Resolve them in App Store Connect before tagging."
                )
            for item_label, *_ in items:
                print(f"  {item_label}: goes to App Review with the version")
        print(f"preflight passed: version {args.version} ({state}) is ready for the enabled steps; nothing was changed")
        return

    if do_submit and submitted:
        # Nothing is written once the version is submitted. A catalog product still
        # due for review did not go out with the version, and it is never sent to
        # App Review on its own (no draft, no item, no product-only submission).
        items, problems, _ = catalog_review_items(asc, app_id, intended_product_ids())
        left_behind = [item_label for item_label, *_ in items] + problems
        if left_behind:
            fail(
                f"version {args.version!r} is already {state}, but these catalog products did not go to App "
                "Review with it: " + "; ".join(left_behind) + ". A product is never sent to App Review without "
                "the version: submit it in App Store Connect yourself (or with the next version), then rerun"
            )
        print(f"submit skipped — the version is already {state} with this run's build; nothing was changed")
    elif do_submit:
        print("selecting this run's build…")
        select_build(asc, version_id, args.build_id, args.version, args.build_number)
        set_release_type(asc, version_id, public_release=do_public, current=attrs(version).get("releaseType"))
        print("attaching catalog products to the review submission…")
        # The draft chosen before any write; images never take it.
        submission_id = submission_id or create_draft_submission(asc, app_id)
        try:
            result = attach_catalog_products(asc, app_id, submission_id=submission_id)
        except ProductSubmitError as exc:
            # A product that must ship with this version blocks the submission.
            fail(f"{exc} Not submitting the app version.")
        # Recheck immediately before submitting: the selection must still be this
        # run's processed build. Nothing has gone to App Review yet; the submit
        # below sends the version and its products together.
        verify_build(asc, args.build_id, args.version, args.build_number)
        confirm_selected_build(asc, version_id, args.build_id)
        print("submitting for App Review…")
        submit_for_review(
            asc, app_id, version_id, state, submission_id=submission_id, allowed_products=result.allowed_versions
        )
        print(f"  {result.attached} catalog product(s) went out with the version")

    print("App Store Connect step finished")


if __name__ == "__main__":
    main()

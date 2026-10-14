#!/usr/bin/env python3
"""ABYSM App Store Connect listing, screenshots, build selection and review (gated in CI).

Called by .github/workflows/ios-release.yml with flags resolved from the IOS_*
switches (see store/README.md):

  UPLOAD_LISTING      version text (description, keywords, promotional text,
                      marketing/support URLs) and App Info (name, subtitle,
                      privacy policy URL) for every locale in store/metadata/ios/
  UPLOAD_WHATS_NEW    whats_new.txt for every locale
  UPLOAD_SCREENSHOTS  iPhone 6.9" and iPad 13" screenshots from store/metadata/screenshots/
  SUBMIT_IOS_REVIEW   select THIS run's build (read back + rechecked), then submit the
                      version and any Ready-to-Submit catalog products for review
  PUBLIC_RELEASE      release automatically after approval (else manual release)

Only fields, screenshots and selections that differ from App Store Connect are
sent, so re-running the step is safe. A screenshot set counts as matching only
when it holds the repo's images in order and App Store Connect has processed
every one, so a set left by a failed or timed-out wait is uploaded again. Once
the version is in a draft review submission (READY_FOR_REVIEW) its text can
still change but its screenshots cannot. Once it is submitted (WAITING_FOR_REVIEW,
IN_REVIEW) nothing can, and a re-run writes nothing: it succeeds only if App
Store Connect already matches the repo, review holds this run's build, and no
catalog product is still due for review (a product is never sent to App Review
without the version).

`--dry-run` validates the local inputs only and makes no network calls.
`--preflight` runs before anything is built: GET requests only, it fails when the
App Store version is missing (create it in App Store Connect first) or when its
state, localizations or catalog products would stop the enabled steps.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable

ROOT = Path(__file__).resolve().parents[2]
ASC_ROOT = "https://api.appstoreconnect.apple.com"
ASC_BASE = f"{ASC_ROOT}/v1"
DEFAULT_BUNDLE_ID = "com.apoorvdarshan.Abysm"
# App Store Connect app record for the bundle id ("ABYSM - Dive the Deep Sea").
APP_STORE_APP_ID = "6783505799"
METADATA_DIR = ROOT / "store" / "metadata"
CATALOG = ROOT / "store" / "catalog" / "products.json"
PRIMARY_LOCALE = "en-US"

# Everything about the version can change: text, App Info and screenshots.
EDITABLE_VERSION_STATES = {
    "PREPARE_FOR_SUBMISSION",
    "DEVELOPER_REJECTED",
    "REJECTED",
    "METADATA_REJECTED",
    "INVALID_BINARY",
}
# READY_FOR_REVIEW means the version already sits in a draft review submission
# (for example after a failed submit). It can still be submitted, and its text
# (listing, What's New, App Info) can still change; its screenshots cannot.
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

# Screenshots come straight from the repo's App Store-ready images.
# Display type → (source folder, accepted pixel sizes). ABYSM is landscape-only.
SCREENSHOT_SETS: tuple[tuple[str, Path, frozenset[tuple[int, int]]], ...] = (
    (
        "APP_IPHONE_67",  # App Store Connect's 6.9"/6.7" iPhone slot
        ROOT / "store" / "metadata" / "screenshots" / "ios" / "iphone",
        frozenset({(2796, 1290), (1290, 2796)}),
    ),
    (
        "APP_IPAD_PRO_3GEN_129",  # 13"/12.9" iPad slot
        ROOT / "store" / "metadata" / "screenshots" / "ios" / "ipad",
        frozenset({(2752, 2064), (2064, 2752), (2732, 2048), (2048, 2732)}),
    ),
)
APP_SCREENSHOT_SET_MAX = 10
SCREENSHOT_PROCESSING_TIMEOUT_SECONDS = 600
SCREENSHOT_PROCESSING_POLL_SECONDS = 10

CATALOG_GROUPS = ("nonConsumables", "consumables", "subscriptions")


def fail(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(1)


class AscHttpError(SystemExit):
    """An App Store Connect HTTP error; exits like fail() unless a caller retries."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"error: {message}")
        self.status = status


def truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def read_text(path: Path) -> str | None:
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


class AscClient:
    # JWTs are minted for 20 minutes; refresh well before that during long waits.
    TOKEN_MAX_AGE_SECONDS = 600

    def __init__(self, token: str | None = None, *, token_factory: Any | None = None) -> None:
        if token is None and token_factory is None:
            raise ValueError("AscClient needs a token or a token_factory")
        self._token_factory = token_factory
        self._token = token if token is not None else token_factory()
        self._token_minted = time.monotonic()

    def _authorization(self) -> str:
        if (
            self._token_factory is not None
            and time.monotonic() - self._token_minted > self.TOKEN_MAX_AGE_SECONDS
        ):
            self._token = self._token_factory()
            self._token_minted = time.monotonic()
        return f"Bearer {self._token}"

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        url = path if path.startswith("http") else f"{ASC_BASE}{path}"
        headers = {"Authorization": self._authorization(), "Accept": "application/json"}
        data: bytes | None = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                payload = resp.read()
                return json.loads(payload.decode("utf-8")) if payload else None
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            print(f"error: ASC {method} {path} → HTTP {exc.code}: {detail[:2000]}", file=sys.stderr)
            raise AscHttpError(exc.code, f"ASC {method} {path} → HTTP {exc.code}") from None

    def get(self, path: str) -> dict[str, Any]:
        result = self.request("GET", path)
        assert result is not None
        return result

    def patch(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        result = self.request("PATCH", path, body=body)
        assert result is not None
        return result

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        result = self.request("POST", path, body=body)
        assert result is not None
        return result

    def upload_bytes(self, url: str, data: bytes, headers: dict[str, str], *, method: str = "PUT") -> None:
        req = urllib.request.Request(url, data=data, method=method.upper(), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=300):
                return
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            fail(f"ASC asset upload → HTTP {exc.code}: {detail[:1000]}")


class ReadOnlyViolation(AssertionError):
    """A --preflight code path tried to change App Store Connect."""


class ReadOnlyClient:
    """GET-only view of a client for --preflight: any write raises before it is sent."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def get(self, path: str) -> dict[str, Any]:
        return self._client.get(path)

    def request(self, method: str, path: str, *, body: dict[str, Any] | None = None) -> dict[str, Any] | None:
        if method.upper() != "GET":
            raise ReadOnlyViolation(f"preflight is read-only; refused {method} {path}")
        return self._client.request(method, path, body=body)

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        raise ReadOnlyViolation(f"preflight is read-only; refused POST {path}")

    def patch(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        raise ReadOnlyViolation(f"preflight is read-only; refused PATCH {path}")

    def upload_bytes(self, url: str, data: bytes, headers: dict[str, str], *, method: str = "PUT") -> None:
        raise ReadOnlyViolation(f"preflight is read-only; refused {method} upload")


def make_asc_token(key_id: str, issuer_id: str, private_key: str) -> str:
    import jwt  # noqa: PLC0415 - only live runs need PyJWT

    now = int(time.time())
    payload = {"iss": issuer_id, "iat": now, "exp": now + 1200, "aud": "appstoreconnect-v1"}
    headers = {"kid": key_id, "typ": "JWT"}
    return jwt.encode(payload, private_key, algorithm="ES256", headers=headers)


def load_credentials() -> tuple[str, str, str]:
    key_id = os.environ.get("APP_STORE_CONNECT_API_KEY_ID", "").strip()
    issuer_id = os.environ.get("APP_STORE_CONNECT_ISSUER_ID", "").strip()
    key_p8 = os.environ.get("APP_STORE_CONNECT_API_KEY_P8", "").strip()
    if not key_id or not issuer_id or not key_p8:
        fail(
            "missing ASC credentials — set APP_STORE_CONNECT_API_KEY_ID, "
            "APP_STORE_CONNECT_ISSUER_ID, APP_STORE_CONNECT_API_KEY_P8"
        )
    return key_id, issuer_id, key_p8.replace("\\n", "\n")


def client_from_environment() -> AscClient:
    """Client whose JWT is re-minted automatically during long-running steps."""
    key_id, issuer_id, key_p8 = load_credentials()
    return AscClient(token_factory=lambda: make_asc_token(key_id, issuer_id, key_p8))


def find_app(client: Any, bundle_id: str, expected_id: str = APP_STORE_APP_ID) -> str:
    """The App Store Connect app id for `bundle_id`; refuses anything but ABYSM's app."""
    query = urllib.parse.urlencode({"filter[bundleId]": bundle_id})
    data = client.get(f"/apps?{query}").get("data") or []
    # filter[bundleId] can match by prefix on some keys, so compare exactly; a row
    # without a bundleId is never taken as a match.
    exact = [row for row in data if (row.get("attributes") or {}).get("bundleId") == bundle_id]
    if not exact:
        fail(f"no App Store Connect app for bundle id {bundle_id}")
    if len(exact) > 1:
        fail(f"ambiguous: {len(exact)} App Store Connect apps for bundle id {bundle_id}")
    app_id = exact[0]["id"]
    if expected_id and app_id != expected_id:
        fail(f"bundle id {bundle_id} resolved to app {app_id}, expected {expected_id}")
    return app_id


def iter_collection(client: Any, path: str) -> list[dict[str, Any]]:
    """Return every record in an ASC collection, following links.next."""
    rows: list[dict[str, Any]] = []
    while path:
        payload = client.get(path)
        rows.extend(payload.get("data") or [])
        next_url = (payload.get("links") or {}).get("next")
        if not next_url:
            break
        path = next_url
    return rows


def version_state(version: dict[str, Any]) -> str:
    attrs = version.get("attributes") or {}
    return attrs.get("appStoreState") or attrs.get("appVersionState") or ""


def get_ios_app_store_version(client: Any, app_id: str, version_string: str) -> dict[str, Any]:
    rows = iter_collection(
        client,
        f"/apps/{app_id}/appStoreVersions?"
        + urllib.parse.urlencode({"limit": "50", "filter[platform]": "IOS"}),
    )
    matches = [r for r in rows if (r.get("attributes") or {}).get("versionString") == version_string]
    if not matches:
        fail(
            f"no iOS App Store version {version_string!r} for app {app_id} "
            f"(create the version in App Store Connect first: add iOS version {version_string} "
            "and leave it in Prepare for Submission, then rerun)"
        )
    if len(matches) > 1:
        fail(f"ambiguous App Store versions for {version_string!r}: {len(matches)} records")
    return matches[0]


def localization_for_locale(client: Any, collection_path: str, locale: str) -> dict[str, Any]:
    rows = iter_collection(client, f"{collection_path}?limit=50")
    for row in rows:
        if (row.get("attributes") or {}).get("locale") == locale:
            return row
    fail(f"no {locale} localization at {collection_path}; add it in App Store Connect first")
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


def app_info_state(info: dict[str, Any]) -> str:
    attrs = info.get("attributes") or {}
    return attrs.get("appStoreState") or attrs.get("state") or ""


def choose_app_info(client: Any, app_id: str) -> tuple[dict[str, Any] | None, bool]:
    """The App Info the repo is compared with, and whether a release may change it.

    A version being prepared (or waiting in a draft review submission) has its own
    editable App Info next to the live one. Otherwise the App Info of the version
    in review, or else the live one, is only compared, never changed.
    """
    infos = iter_collection(client, f"/apps/{app_id}/appInfos")
    for info in infos:
        if app_info_state(info) in EDITABLE_APP_INFO_STATES:
            return info, True
    in_flight = [info for info in infos if app_info_state(info) not in LIVE_APP_INFO_STATES]
    chosen = (in_flight or infos or [None])[0]
    return chosen, False


def upload_listing(
    client: Any,
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
    version_loc = localization_for_locale(
        client, f"/appStoreVersions/{version_id}/appStoreVersionLocalizations", locale
    )
    changes = changed_attributes(version_loc.get("attributes") or {}, wanted)
    differing = [f"{locale} {name}" for name in sorted(changes)]
    if changes and not text_editable:
        fail(
            f"{locale}: {', '.join(sorted(changes))} differ from App Store Connect, but the "
            f"version text cannot change while the version is {state or 'locked'}; make the "
            "repo match App Store Connect, or remove the version from review there, then rerun"
        )
    if changes and write:
        client.patch(
            f"/appStoreVersionLocalizations/{version_loc['id']}",
            {"data": {"type": "appStoreVersionLocalizations", "id": version_loc["id"], "attributes": changes}},
        )
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
    info, info_editable = app_info if app_info is not None else choose_app_info(client, app_id)
    if info is None:
        fail(f"App Store Connect returned no App Info for app {app_id}")
        raise AssertionError  # unreachable
    info_loc = localization_for_locale(client, f"/appInfos/{info['id']}/appInfoLocalizations", locale)
    info_changes = changed_attributes(info_loc.get("attributes") or {}, info_wanted)
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
        client.patch(
            f"/appInfoLocalizations/{info_loc['id']}",
            {"data": {"type": "appInfoLocalizations", "id": info_loc["id"], "attributes": info_changes}},
        )
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
        sizes = ", ".join(f"{w}x{h}" for w, h in sorted(accepted))
        for path in pngs:
            size = png_size(path)
            if size not in accepted:
                fail(f"{shown}/{path.name} is {size[0]}x{size[1]}; {display_type} accepts {sizes}")
        plan.append((display_type, pngs))
    return plan


def md5_hex(path: Path) -> str:
    """The checksum App Store Connect stores as an uploaded screenshot's sourceFileChecksum."""
    return hashlib.md5(path.read_bytes()).hexdigest()  # noqa: S324 - Apple's checksum


def find_screenshot_set(client: Any, version_loc_id: str, display_type: str) -> dict[str, Any] | None:
    for item in iter_collection(client, f"/appStoreVersionLocalizations/{version_loc_id}/appScreenshotSets"):
        if (item.get("attributes") or {}).get("screenshotDisplayType") == display_type:
            return item
    return None


def ensure_screenshot_set(client: Any, version_loc_id: str, display_type: str) -> dict[str, Any]:
    found = find_screenshot_set(client, version_loc_id, display_type)
    if found is not None:
        return found
    created = client.post(
        "/appScreenshotSets",
        {
            "data": {
                "type": "appScreenshotSets",
                "attributes": {"screenshotDisplayType": display_type},
                "relationships": {
                    "appStoreVersionLocalization": {
                        "data": {"type": "appStoreVersionLocalizations", "id": version_loc_id}
                    }
                },
            }
        },
    )
    return created["data"]


def screenshot_set_problem(client: Any, screenshot_set_id: str, pngs: list[Path]) -> str | None:
    """Why the set does not already hold the repo's images, or None when it does.

    The set matches only when it holds the repo's images (same checksums, same
    order) and App Store Connect has processed every one (assetDeliveryState
    COMPLETE). An upload's sourceFileChecksum is stored when it is committed,
    before Apple processes the image, so a set left by a failed or timed-out wait
    already has the repo's checksums but an image that is FAILED or still
    processing. Such a set must be uploaded again, never taken as done.
    """
    shots = iter_collection(client, f"/appScreenshotSets/{screenshot_set_id}/appScreenshots")
    if [(s.get("attributes") or {}).get("sourceFileChecksum") for s in shots] != [md5_hex(p) for p in pngs]:
        return "differ from the repo"
    unprocessed = []
    for shot in shots:
        attrs = shot.get("attributes") or {}
        state = (attrs.get("assetDeliveryState") or {}).get("state")
        if state != "COMPLETE":
            unprocessed.append(f"{attrs.get('fileName') or shot.get('id')}: {state or 'no processing state'}")
    if unprocessed:
        return f"match the repo but are not all processed by App Store Connect ({', '.join(unprocessed)})"
    return None


def list_screenshot_ids(client: Any, screenshot_set_id: str) -> list[str]:
    return [s["id"] for s in iter_collection(client, f"/appScreenshotSets/{screenshot_set_id}/appScreenshots")]


def upload_screenshot_file(client: Any, screenshot_set_id: str, image_path: Path) -> str:
    raw = image_path.read_bytes()
    reserved = client.post(
        "/appScreenshots",
        {
            "data": {
                "type": "appScreenshots",
                "attributes": {"fileName": image_path.name, "fileSize": len(raw)},
                "relationships": {
                    "appScreenshotSet": {"data": {"type": "appScreenshotSets", "id": screenshot_set_id}}
                },
            }
        },
    )
    shot = reserved["data"]
    operations = (shot.get("attributes") or {}).get("uploadOperations") or []
    if not operations:
        fail(f"App Store Connect returned no upload operations for {image_path.name}")
    for op in operations:
        offset = int(op.get("offset", 0))
        chunk = raw[offset: offset + int(op["length"])]
        headers = {h["name"]: h["value"] for h in op.get("requestHeaders") or []}
        client.upload_bytes(op["url"], chunk, headers, method=(op.get("method") or "PUT"))
    client.patch(
        f"/appScreenshots/{shot['id']}",
        {
            "data": {
                "type": "appScreenshots",
                "id": shot["id"],
                "attributes": {"uploaded": True, "sourceFileChecksum": hashlib.md5(raw).hexdigest()},  # noqa: S324 - Apple's checksum
            }
        },
    )
    print(f"    uploaded {image_path.name}")
    return shot["id"]


def wait_for_screenshots(
    client: Any,
    screenshot_ids: list[str],
    *,
    timeout: float = SCREENSHOT_PROCESSING_TIMEOUT_SECONDS,
    poll_seconds: float = SCREENSHOT_PROCESSING_POLL_SECONDS,
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Wait until App Store Connect has processed every uploaded screenshot."""
    deadline = now() + timeout
    pending = list(screenshot_ids)
    while pending:
        still: list[str] = []
        for shot_id in pending:
            attrs = client.get(f"/appScreenshots/{shot_id}").get("data", {}).get("attributes") or {}
            delivery = attrs.get("assetDeliveryState") or {}
            state = delivery.get("state")
            if state == "COMPLETE":
                continue
            if state == "FAILED":
                errors = "; ".join(e.get("description") or e.get("code") or "?" for e in delivery.get("errors") or [])
                fail(f"App Store Connect rejected screenshot {attrs.get('fileName') or shot_id}: {errors or 'FAILED'}")
            still.append(shot_id)
        pending = still
        if not pending:
            break
        if now() >= deadline:
            fail(f"timed out waiting for App Store Connect to process {len(pending)} screenshot(s)")
        sleep(poll_seconds)


def upload_screenshots(
    client: Any,
    *,
    version_id: str,
    locale: str,
    plan: list[tuple[str, list[Path]]],
    wait: Callable[[Any, list[str]], None] = wait_for_screenshots,
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
    version_loc = localization_for_locale(
        client, f"/appStoreVersions/{version_id}/appStoreVersionLocalizations", locale
    )
    differing: list[str] = []
    uploaded: list[str] = []
    for display_type, pngs in plan:
        existing = find_screenshot_set(client, version_loc["id"], display_type)
        problem = "are missing" if existing is None else screenshot_set_problem(client, existing["id"], pngs)
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
        if existing is None:
            existing = ensure_screenshot_set(client, version_loc["id"], display_type)
        set_id = existing["id"]
        old_ids = list_screenshot_ids(client, set_id)
        # Upload replacements one at a time. App Store Connect rejects new
        # reservations while a set is full, so delete one old screenshot first
        # when needed. A failure mid-way can leave a mixed set; rerun to repair.
        for path in pngs:
            if len(list_screenshot_ids(client, set_id)) >= APP_SCREENSHOT_SET_MAX:
                if not old_ids:
                    fail(f"{display_type} set is full with no previous screenshots left to replace")
                client.request("DELETE", f"/appScreenshots/{old_ids.pop(0)}")
            uploaded.append(upload_screenshot_file(client, set_id, path))
        for shot_id in old_ids:
            client.request("DELETE", f"/appScreenshots/{shot_id}")
        if old_ids:
            print(f"    removed {len(old_ids)} previous screenshot(s)")
    if uploaded:
        wait(client, uploaded)
        print(f"  {len(uploaded)} screenshot(s) processed by App Store Connect")
    return differing


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

    def __init__(self, submission_id: str, attached: int, added_items: bool) -> None:
        self.submission_id = submission_id
        # Products in the draft now, attached by this call or by an earlier attempt.
        self.attached = attached
        self.added_items = added_items


# Subscription states that can still be (re)attached to a review.
SUBMITTABLE_SUBSCRIPTION_STATES = {"READY_TO_SUBMIT", "DEVELOPER_REJECTED", "READY_FOR_REVIEW"}
# One-time purchases ("Unlock the Deep") are attached only while Ready to Submit.
SUBMITTABLE_IAP_STATES = {"READY_TO_SUBMIT"}


def draft_submission_query(app_id: str) -> str:
    return f"/apps/{app_id}/reviewSubmissions?" + urllib.parse.urlencode(
        {"filter[state]": "READY_FOR_REVIEW", "limit": "5"}
    )


def find_draft_submission(client: Any, app_id: str) -> str | None:
    """The app's READY_FOR_REVIEW draft review submission, if there is one."""
    for row in client.get(draft_submission_query(app_id)).get("data") or []:
        return row["id"]
    return None


def create_draft_submission(client: Any, app_id: str) -> str:
    submission = client.post(
        "/reviewSubmissions",
        {
            "data": {
                "type": "reviewSubmissions",
                "relationships": {"app": {"data": {"type": "apps", "id": app_id}}},
            }
        },
    )
    return submission["data"]["id"]


def get_or_create_draft_submission(client: Any, app_id: str) -> str:
    """Return the app's READY_FOR_REVIEW draft review submission, creating one."""
    return find_draft_submission(client, app_id) or create_draft_submission(client, app_id)


def draft_items_path(submission_id: str) -> str:
    # Review Submission Items omit relationships unless they are included.
    return (
        f"/reviewSubmissions/{submission_id}/items?limit=50"
        "&include=appStoreVersion,subscriptionVersion,inAppPurchaseVersion"
    )


def draft_item_version_ids(client: Any, submission_id: str) -> set[str]:
    """App, subscription and in-app purchase version ids already attached to a draft."""
    ids: set[str] = set()
    for item in iter_collection(client, draft_items_path(submission_id)):
        for name in ("subscriptionVersion", "appStoreVersion", "inAppPurchaseVersion"):
            related = ((item.get("relationships") or {}).get(name) or {}).get("data") or {}
            if related.get("id"):
                ids.add(related["id"])
    return ids


def submit_review_submission(client: Any, submission_id: str) -> None:
    """Submitting is a PATCH with submitted=true; there is no /submit action."""
    client.request(
        "PATCH",
        f"/reviewSubmissions/{submission_id}",
        body={"data": {"type": "reviewSubmissions", "id": submission_id, "attributes": {"submitted": True}}},
    )


def newest_version_id(versions: list[dict[str, Any]]) -> str | None:
    """A product's in-flight version (one per product; the highest number wins)."""
    numbered = [v for v in versions if (v.get("attributes") or {}).get("version")]
    if not numbered:
        return versions[0]["id"] if versions else None
    return max(numbered, key=lambda v: v["attributes"]["version"])["id"]


def current_subscription_version(client: Any, subscription_id: str) -> str | None:
    return newest_version_id(iter_collection(client, f"/subscriptions/{subscription_id}/versions"))


def iap_versions_path(iap_id: str) -> str:
    # In-app purchase versions are a v2 resource.
    return f"{ASC_ROOT}/v2/inAppPurchases/{iap_id}/versions?limit=50"


def current_iap_version(client: Any, iap_id: str) -> str | None:
    return newest_version_id(iter_collection(client, iap_versions_path(iap_id)))


def catalog_review_items(
    client: Any, app_id: str, intended_ids: set[str]
) -> tuple[list[tuple[str, str, str, str]], list[str]]:
    """Ready-to-Submit catalog products and the review item each needs (GET requests only).

    Returns ([(label, relationship, resource type, version id)], problems). Only
    products listed in store/catalog/products.json are considered, and approved
    products are never resubmitted.
    """
    items: list[tuple[str, str, str, str]] = []
    problems: list[str] = []
    for group in iter_collection(client, f"/apps/{app_id}/subscriptionGroups?limit=200"):
        for sub in iter_collection(client, f"/subscriptionGroups/{group['id']}/subscriptions?limit=200"):
            attrs = sub.get("attributes") or {}
            pid = attrs.get("productId") or ""
            if pid not in intended_ids or attrs.get("state") not in SUBMITTABLE_SUBSCRIPTION_STATES:
                continue
            label = f"subscription {attrs.get('name') or sub['id']} ({pid})"
            version_id = current_subscription_version(client, sub["id"])
            if version_id:
                items.append((label, "subscriptionVersion", "subscriptionVersions", version_id))
            else:
                problems.append(f"{label}: no version to submit")
    for iap in iter_collection(client, f"/apps/{app_id}/inAppPurchasesV2?limit=200"):
        attrs = iap.get("attributes") or {}
        pid = attrs.get("productId") or ""
        if pid not in intended_ids or attrs.get("state") not in SUBMITTABLE_IAP_STATES:
            continue
        label = f"in-app purchase {attrs.get('name') or iap['id']} ({pid})"
        version_id = current_iap_version(client, iap["id"])
        if version_id:
            items.append((label, "inAppPurchaseVersion", "inAppPurchaseVersions", version_id))
        else:
            problems.append(f"{label}: no version to submit")
    return items, problems


def attach_catalog_products(
    client: Any,
    app_id: str,
    *,
    intended_ids: set[str] | None = None,
    submission_id: str | None = None,
) -> ProductAttachResult:
    """Attach Ready-to-Submit catalog products to the app's draft review submission.

    Nothing goes to App Review here. Subscriptions (`subscriptionVersion`) and
    one-time purchases (`inAppPurchaseVersion`; ABYSM's "Unlock the Deep" is a
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
    items, failures = catalog_review_items(client, app_id, intended_ids)
    if submission_id is None:
        submission_id = find_draft_submission(client, app_id)
    already_attached = draft_item_version_ids(client, submission_id) if submission_id else set()
    attached = 0
    added_items = False
    for label, relationship, resource_type, version_id in items:
        if version_id in already_attached:
            attached += 1
            print(f"  {label}: already in the review submission")
            continue
        if submission_id is None:
            submission_id = create_draft_submission(client, app_id)
        try:
            client.post(
                "/reviewSubmissionItems",
                {
                    "data": {
                        "type": "reviewSubmissionItems",
                        "relationships": {
                            "reviewSubmission": {"data": {"type": "reviewSubmissions", "id": submission_id}},
                            relationship: {"data": {"type": resource_type, "id": version_id}},
                        },
                    }
                },
            )
        except SystemExit:
            failures.append(label)
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
    return ProductAttachResult(submission_id or "", attached, added_items)


# --- Build selection and review ------------------------------------------------

RELEASE_TYPE_PUBLIC = "AFTER_APPROVAL"
RELEASE_TYPE_MANUAL = "MANUAL"


def verify_build(client: Any, build_id: str, version_string: str, build_number: str) -> None:
    """Re-read the build and refuse anything but this run's processed build."""
    payload = client.get(
        f"/builds/{build_id}?"
        + urllib.parse.urlencode(
            {
                "include": "preReleaseVersion",
                "fields[builds]": "version,processingState,expired,preReleaseVersion",
                "fields[preReleaseVersions]": "version,platform",
            }
        )
    )
    data = payload.get("data") or {}
    attrs = data.get("attributes") or {}
    pre = next((r for r in payload.get("included") or [] if r.get("type") == "preReleaseVersions"), {})
    pre_attrs = pre.get("attributes") or {}
    problems = []
    if data.get("id") != build_id:
        problems.append(f"id {data.get('id')!r}")
    if attrs.get("version") != build_number:
        problems.append(f"build number {attrs.get('version')!r}")
    if attrs.get("processingState") != "VALID":
        problems.append(f"processing state {attrs.get('processingState')!r}")
    if attrs.get("expired"):
        problems.append("expired")
    if pre_attrs.get("version") != version_string or pre_attrs.get("platform") != "IOS":
        problems.append(f"version {pre_attrs.get('platform')} {pre_attrs.get('version')!r}")
    if problems:
        fail(f"build {build_id} is not {version_string} ({build_number}), VALID and unexpired: " + ", ".join(problems))


def attached_build_id(client: Any, version_id: str) -> str | None:
    return (client.get(f"/appStoreVersions/{version_id}/build").get("data") or {}).get("id")


def confirm_selected_build(client: Any, version_id: str, build_id: str) -> None:
    current = attached_build_id(client, version_id)
    if current != build_id:
        fail(f"App Store version {version_id} has build {current or 'none'} selected, expected {build_id}; not submitting")


def select_build(client: Any, version_id: str, build_id: str, version_string: str, build_number: str) -> None:
    """Explicitly select this run's build for the version, then read it back."""
    verify_build(client, build_id, version_string, build_number)
    if attached_build_id(client, version_id) == build_id:
        # A re-run: the version (possibly already in a draft submission) holds it.
        print(f"  build {build_number} ({build_id}) is already selected for version {version_string}")
    else:
        client.request(
            "PATCH",
            f"/appStoreVersions/{version_id}/relationships/build",
            body={"data": {"type": "builds", "id": build_id}},
        )
    confirm_selected_build(client, version_id, build_id)
    print(f"  selected build {build_number} ({build_id}) for version {version_string}")


def set_release_type(client: Any, version_id: str, *, public_release: bool, current: str | None = None) -> None:
    release_type = RELEASE_TYPE_PUBLIC if public_release else RELEASE_TYPE_MANUAL
    label = "automatic after approval" if public_release else "manual release after approval"
    if current == release_type:
        print(f"  release type already {label}")
        return
    client.patch(
        f"/appStoreVersions/{version_id}",
        {"data": {"type": "appStoreVersions", "id": version_id, "attributes": {"releaseType": release_type}}},
    )
    print(f"  release type: {label}")


def submit_for_review(client: Any, app_id: str, version_id: str, state: str = "", *, submission_id: str | None = None) -> None:
    # Reuse a draft (an earlier attempt can leave one that was never submitted).
    if submission_id is None:
        submission_id = get_or_create_draft_submission(client, app_id)
    already_added = state == "READY_FOR_REVIEW" or version_id in draft_item_version_ids(client, submission_id)
    if not already_added:
        client.post(
            "/reviewSubmissionItems",
            {
                "data": {
                    "type": "reviewSubmissionItems",
                    "relationships": {
                        "reviewSubmission": {"data": {"type": "reviewSubmissions", "id": submission_id}},
                        "appStoreVersion": {"data": {"type": "appStoreVersions", "id": version_id}},
                    },
                }
            },
        )
    submit_review_submission(client, submission_id)
    print(f"  submitted App Store version {version_id} for review (submission {submission_id})")


# --- Entry point -----------------------------------------------------------------


def validate_local_inputs(
    *,
    upload_listing: bool,
    upload_whats_new: bool,
    upload_screenshots: bool,
    metadata_dir: Path,
    screenshot_sets: Iterable[tuple[str, Path, frozenset[tuple[int, int]]]] = SCREENSHOT_SETS,
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
    return locales, plan


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
    parser.add_argument("--bundle-id", default=DEFAULT_BUNDLE_ID)
    parser.add_argument("--version", help="Marketing version from the release tag (v1.0.1 → 1.0.1)")
    parser.add_argument("--build-id", help="App Store Connect id of the build uploaded by this run (required to submit)")
    parser.add_argument("--build-number", help="CFBundleVersion of the build uploaded by this run (required to submit)")
    parser.add_argument("--dry-run", action="store_true", help="Validate switches and local files only — no network")
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Read-only App Store Connect checks before anything is built (GET requests only)",
    )
    args = parser.parse_args()
    if args.dry_run and args.preflight:
        fail("--dry-run and --preflight are separate modes; pass only one")

    do_listing = truthy("UPLOAD_LISTING")
    do_whats_new = truthy("UPLOAD_WHATS_NEW")
    do_screenshots = truthy("UPLOAD_SCREENSHOTS")
    do_submit = truthy("SUBMIT_IOS_REVIEW")
    do_public = truthy("PUBLIC_RELEASE")

    if not (do_listing or do_whats_new or do_screenshots or do_submit):
        print("App Store Connect step skipped — UPLOAD_LISTING / UPLOAD_WHATS_NEW / UPLOAD_SCREENSHOTS / SUBMIT_IOS_REVIEW are off")
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
    )
    if do_submit:
        intended_product_ids()  # the catalog must parse before anything is submitted

    if args.dry_run:
        print("App Store Connect dry run — local inputs OK; no API calls")
        print(
            f"  bundle={args.bundle_id} locales={','.join(locales) or '-'} listing={do_listing} "
            f"whats_new={do_whats_new} screenshots={sum(len(p) for _, p in plan)} "
            f"submit={do_submit} public_release={do_public}"
        )
        return
    if not args.version:
        fail("--version is required for live App Store Connect calls")

    client: Any = client_from_environment()
    if args.preflight:
        client = ReadOnlyClient(client)
    write = not args.preflight
    app_id = find_app(client, args.bundle_id)
    version = get_ios_app_store_version(client, app_id, args.version)
    version_id = version["id"]
    state = version_state(version)
    label = "App Store Connect preflight (read-only)" if args.preflight else "App Store Connect"
    print(f"{label}: app={app_id} version={args.version} id={version_id} state={state}")
    edits_metadata = do_listing or do_whats_new or do_screenshots
    check_version_state(
        args.version, state, edits_metadata=edits_metadata, do_submit=do_submit, new_build=args.preflight
    )
    submitted = state in SUBMITTED_VERSION_STATES

    if do_submit and submitted:
        # A re-run after this run's submit went through (for example the job failed
        # afterwards): accept it only if review holds exactly this run's build.
        confirm_selected_build(client, version_id, args.build_id)

    if do_listing or do_whats_new:
        parts = [n for n, on in (("listing", do_listing), ("What's New", do_whats_new)) if on]
        print(f"{'checking' if args.preflight else 'updating'} {' + '.join(parts)} for {', '.join(locales)}…")
        app_info = choose_app_info(client, app_id) if do_listing else None
        for locale in locales:
            upload_listing(
                client,
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
            client,
            version_id=version_id,
            locale=PRIMARY_LOCALE,
            plan=plan,
            editable=state in EDITABLE_VERSION_STATES,
            write=write,
            state=state,
        )

    if args.preflight:
        if do_submit:
            items, problems = catalog_review_items(client, app_id, intended_product_ids())
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
        items, problems = catalog_review_items(client, app_id, intended_product_ids())
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
        select_build(client, version_id, args.build_id, args.version, args.build_number)
        set_release_type(
            client, version_id, public_release=do_public, current=(version.get("attributes") or {}).get("releaseType")
        )
        print("attaching catalog products to the review submission…")
        submission_id = get_or_create_draft_submission(client, app_id)
        try:
            result = attach_catalog_products(client, app_id, submission_id=submission_id)
        except ProductSubmitError as exc:
            # A product that must ship with this version blocks the submission.
            fail(f"{exc} Not submitting the app version.")
        # Recheck immediately before submitting: the selection must still be this
        # run's processed build. Nothing has gone to App Review yet; the submit
        # below sends the version and its products together.
        verify_build(client, args.build_id, args.version, args.build_number)
        confirm_selected_build(client, version_id, args.build_id)
        print("submitting for App Review…")
        submit_for_review(client, app_id, version_id, state, submission_id=submission_id)
        print(f"  {result.attached} catalog product(s) went out with the version")

    print("App Store Connect step finished")


if __name__ == "__main__":
    main()

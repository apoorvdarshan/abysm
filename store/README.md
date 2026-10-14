# Store release automation

GitHub Actions builds, signs and uploads ABYSM to App Store Connect, keeps the
App Store listing in this repo, and creates the GitHub Release for each version
tag. Everything lives in [`ios-release.yml`](../.github/workflows/ios-release.yml).

**Nothing reaches the App Store unless its switch is on.** Every switch is off
until you set it.

**Xcode Cloud is being removed for ABYSM.** Its tag-triggered workflow is deleted
in App Store Connect once this pipeline has passed validation. Never re-create an
Xcode Cloud workflow for `v*` tags: Xcode Cloud triggers live in App Store
Connect, not in this repo, so no GitHub switch can stop them, and both pipelines
would upload a build for the same tag.

## Release flow (`v<MARKETING_VERSION>` tag)

```
v1.0.1 tag ─► unit + UI tests (ios-tests.yml) ─► resolve switches
  │             (tag must be exactly "v" + MARKETING_VERSION, e.g. v1.0.1 for 1.0.1)
  └─ IOS_RELEASE_AUTOMATION off ─► GitHub Release only
  └─ on:
       IOS_UPLOAD_BUILD ─► next build number from App Store Connect
                        ─► archive Release ─► verify bundle id / version / build in every bundle
                        ─► cloud-signed export + upload
                        ─► wait until THIS build is VALID (poll 30 s, up to 120 min from upload start)
       IOS_UPLOAD_LISTING / IOS_UPLOAD_WHATS_NEW / IOS_UPLOAD_SCREENSHOTS ─► version metadata
       IOS_SUBMIT_REVIEW ─► select this run's build, read it back, set release type
                         ─► attach Ready-to-Submit catalog products
                         ─► recheck build + selection ─► submit for App Review
  └─ GitHub Release (only if every enabled step succeeded)
```

A tag that is not exactly `v<MARKETING_VERSION>` (for example `v1.0.0` while the
project says `1.0`, or `v1.1.0-beta.1`) fails before anything is built and
creates no GitHub Release. One tag runs one pipeline; the former
`github-release.yml` workflow is folded into this one.

A manual **Run workflow** (`workflow_dispatch`) is a validation run: it archives
with the CI signing identity, exports with cloud-managed distribution signing
and validates the IPA with App Store Connect (`altool --validate-app`). It never
uploads, edits the listing, submits or creates a GitHub Release, whatever the
switches say. Apple refuses versions it has already approved, so fill in the
optional **marketing_version** input with the next version (e.g. `1.0.1`); the
build is validated as that version without changing the project.

Submission stops instead of continuing when the build times out, fails
processing, is expired, is ambiguous, belongs to another app or version, was
uploaded before this run, or is not the build selected on the version. An older
build is never substituted. The wait covers build readiness only, not Apple's
review or the public release.

## Switches

Repository **Variables** (Settings → Secrets and variables → Actions → Variables).
Missing means off. Any value other than `true/false/yes/no/on/off/1/0` fails the
run, even when the master switch is off. Copy names from
[`gates.env.example`](gates.env.example).

| Variable | When `true` |
|----------|-------------|
| `IOS_RELEASE_AUTOMATION` | Master switch. When off, every operation below is skipped and a tag only gets its GitHub Release |
| `IOS_UPLOAD_BUILD` | Build, sign and upload the binary to App Store Connect, then wait until it is processed |
| `IOS_UPLOAD_LISTING` | Version text (description, keywords, promotional text, marketing and support URLs) and App Info (name, subtitle, privacy policy URL) from `store/metadata/ios/<locale>/`. Only changed fields are sent |
| `IOS_UPLOAD_WHATS_NEW` | What's New from `store/metadata/ios/<locale>/whats_new.txt` (required for every locale when on) |
| `IOS_UPLOAD_SCREENSHOTS` | Replace the iPhone 6.9" and iPad 13" screenshots (see below) |
| `IOS_SUBMIT_REVIEW` | Select this run's build and submit the version **and** any Ready-to-Submit catalog products for review. Requires `IOS_UPLOAD_BUILD` |
| `IOS_PUBLIC_RELEASE` | Release automatically after approval. Off = you release it by hand. Requires `IOS_SUBMIT_REVIEW` |
| `IOS_BUILD_POLL_SECONDS` | How often to check build processing: default 30, 10–600 |
| `IOS_BUILD_WAIT_MINUTES` | Total wait, counted from upload start (upload + processing): default 120, 10–300 |

Listing, What's New, screenshots and submission need an editable App Store
version for the tag's version: create it (e.g. 1.0.1) in App Store Connect
first. The run fails clearly if it is missing or already in review.

## Secrets

| Secret | Used for |
|--------|----------|
| `APP_STORE_CONNECT_API_KEY_ID` | Admin-role App Store Connect API key: build numbers, cloud-managed distribution signing, upload, build readiness, listing, review |
| `APP_STORE_CONNECT_ISSUER_ID` | Its issuer |
| `APP_STORE_CONNECT_API_KEY_P8` | Its private key (`.p8` body) |
| `IOS_DEV_SIGNING_P12_BASE64` | Shared CI Apple Development identity (base64 `.p12`; certificate "Apple Development: Created via API", ID `NVNGDQGCKK`, expires 2027-10-14) that signs the archive. App Store signing happens at export with Apple's cloud-managed distribution certificate |
| `IOS_DEV_SIGNING_P12_PASSWORD` | Password for that `.p12` |

**Certificate rotation.** The development certificate is shared by several of
Apoorv's apps (Fud AI, Verceltics, ABYSM, iitjee, Quit All, Scowld, Sesslet) and
its private key exists only in these secrets. Before it expires on 2027-10-14
(or if it is revoked), create a new Apple Development certificate for CI (App
Store Connect API, `certificateType: DEVELOPMENT`), replace both
`IOS_DEV_SIGNING_*` secrets in every repo that uses it, run a validation for
each, and then revoke the old certificate.

## Listing metadata

The repo is the source of truth for the App Store listing. Each App Store
localization has a folder; today ABYSM has `en-US` only.

```
store/metadata/ios/en-US/
  description.txt        keywords.txt        promotional_text.txt
  marketing_url.txt      support_url.txt     (version text)
  name.txt               subtitle.txt        privacy_url.txt   (App Info)
  whats_new.txt          (add before tagging when IOS_UPLOAD_WHATS_NEW is on)
```

These files were exported read-only from the live 1.0 listing with
[`export_listing.py`](../scripts/store/export_listing.py). If you edit the
listing in App Store Connect, export again so the repo stays the source of truth:

```bash
python3 scripts/store/export_listing.py                 # the version on the App Store
python3 scripts/store/export_listing.py --version 1.0.1 # a version being prepared
```

App Info (name, subtitle, privacy URL) can only change while a new version is
being prepared. If those files differ from App Store Connect when nothing is
editable, the listing step fails instead of skipping them silently.
`APPSTORE.md` keeps reviewer notes and other submission details.

## Screenshots

`IOS_UPLOAD_SCREENSHOTS` uploads the App Store-ready marketing images already in
the repo; nothing is resized or generated:

| App Store Connect slot | Source | Accepted sizes |
|------------------------|--------|----------------|
| `APP_IPHONE_67` (iPhone 6.9") | [`marketing/app-store/iphone/mockups/`](../marketing/app-store/iphone/mockups/) | 2796×1290 (landscape) or 1290×2796 |
| `APP_IPAD_PRO_3GEN_129` (iPad 13") | [`marketing/app-store/ipad/mockups/`](../marketing/app-store/ipad/mockups/) | 2752×2064, 2732×2048 or their portrait sizes |

Each set is replaced in file-name order (1–10 PNGs) for the `en-US` listing,
and the run waits until App Store Connect has processed every image. A missing
folder, an empty set, more than 10 files or any other size fails the run with a
clear message before anything is uploaded.

## In-app purchases

ABYSM sells one non-consumable, **Unlock the Deep**
(`com.apoorvdarshan.Abysm.unlockdeep`, entitlement `deep`), listed in
[`catalog/products.json`](catalog/products.json).
[`validate_catalog.py`](../scripts/store/validate_catalog.py) checks the catalog
against `Abysm.storekit` and `StoreManager.swift`. With `IOS_SUBMIT_REVIEW` on,
catalog products in `READY_TO_SUBMIT` go to App Review with the version
(subscriptions via `subscriptionVersion` review items, one-time purchases via
`inAppPurchaseSubmissions`). Unlock the Deep is already approved, so it is never
resubmitted; products missing from the catalog are never submitted. If a
required product cannot be attached, the version is not submitted.

## Scripts

| Script | Role |
|--------|------|
| [`scripts/store/ios_release.py`](../scripts/store/ios_release.py) | Switches and tag rule, build number, wait for this run's build |
| [`scripts/store/asc_release.py`](../scripts/store/asc_release.py) | Listing, What's New, screenshots, build selection, products, App Review |
| [`scripts/store/export_listing.py`](../scripts/store/export_listing.py) | Read-only export of the App Store listing into `store/metadata/` |
| [`scripts/store/validate_catalog.py`](../scripts/store/validate_catalog.py) | Catalog vs. StoreKit file vs. app code |
| [`scripts/store/print_gates.py`](../scripts/store/print_gates.py) | Print the switches (never touches a store) |
| [`scripts/store/test_ios_release.py`](../scripts/store/test_ios_release.py) | Offline tests: disabled/invalid switches, tag mismatch, validation mode, build wait timeout/failure/ambiguity/mismatch/old build, selection read-back, token refresh, listing and screenshot checks |
| [`scripts/release_notes.py`](../scripts/release_notes.py) | GitHub Release notes from the matching `RELEASE_NOTES.md` section (else GitHub generates them) |

[`requirements-store.txt`](../requirements-store.txt) (PyJWT, hash-pinned) is
installed only by jobs that call the App Store Connect API. The offline checks
run in the **Store release checks** workflow for changes to these files, and
again before every release run.

## How to release

1. Bump `MARKETING_VERSION` (and `CURRENT_PROJECT_VERSION` if you like; the
   pipeline always uses at least one more than App Store Connect's highest build).
2. Before relying on signing changes, run **iOS Release → Run workflow** with the
   new version (validation only).
3. Create the version in App Store Connect; update `store/metadata/` and add
   `whats_new.txt`; optionally add a `## v1.0.1` section to `RELEASE_NOTES.md`.
4. Turn on only the switches you want (the master switch plus each operation).
   Leave `IOS_SUBMIT_REVIEW` and `IOS_PUBLIC_RELEASE` off until you intend that release.
5. Push the tag: `git tag -a v1.0.1 -m "ABYSM 1.0.1" && git push origin v1.0.1`.

## Dry run

```bash
python3 -m unittest discover -s scripts/store -p 'test_*.py'
python3 scripts/store/validate_catalog.py
python3 scripts/store/print_gates.py
UPLOAD_LISTING=true UPLOAD_SCREENSHOTS=true SUBMIT_IOS_REVIEW=true \
  python3 scripts/store/asc_release.py --dry-run --build-id DRY-RUN --build-number 1
```

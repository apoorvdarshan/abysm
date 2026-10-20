# Store release automation

GitHub Actions builds, signs and uploads ABYSM to App Store Connect, keeps the
App Store listing in this repo, and creates the GitHub Release for each version
tag. Everything lives in [`ios-release.yml`](../.github/workflows/ios-release.yml).

**Nothing reaches the App Store unless its switch is on.** Every switch is off
until you set it.

**Xcode Cloud was removed for ABYSM on 2026-10-14**, after this pipeline passed
validation: its workflow and product were deleted in App Store Connect. Never
re-create an Xcode Cloud workflow for `v*` tags: Xcode Cloud triggers live in App
Store Connect, not in this repo, so no GitHub switch can stop them, and both
pipelines would upload a build for the same tag.

## Release flow (`v<MARKETING_VERSION>` tag)

```
v1.0.1 tag ─► unit + UI tests (ios-tests.yml) ─► resolve switches
  │             (tag must be exactly "v" + MARKETING_VERSION, e.g. v1.0.1 for 1.0.1;
  │              a "## v1.0.1" RELEASE_NOTES.md section, if present, must not be
  │              empty or duplicated)
  └─ IOS_RELEASE_AUTOMATION off ─► GitHub Release only
  └─ on:
       IOS_CREATE_VERSION ─► create the 1.0.1 App Store version if it is missing (an
                             existing one is left alone; refuses, without writing, when
                             another version is still on its way to the store or 1.0.1
                             is not newer than every existing version)
       listing / What's New / screenshot / creative asset / review switch on
                        ─► read-only preflight: the 1.0.1 App Store version exists and
                           its state, locales, images and due catalog products allow
                           those steps
       IOS_UPLOAD_BUILD ─► next build number from App Store Connect
                        ─► archive Release ─► verify bundle id / version / build in every bundle
                        ─► cloud-signed export + upload
                        ─► wait-for-build job: until THIS build is VALID
                           (poll 30 s, up to 120 min from upload start)
       IOS_UPLOAD_LISTING / IOS_UPLOAD_WHATS_NEW / IOS_UPLOAD_SCREENSHOTS ─► version metadata
                           (only what differs from App Store Connect)
       IOS_UPLOAD_CREATIVE_ASSETS ─► header / search results images: upload and review
                                     new ones on their own, place approved ones
       IOS_SUBMIT_REVIEW ─► select this run's build, read it back, set release type
                         ─► add Ready-to-Submit catalog products to the draft submission
                         ─► recheck build + selection, and that the draft holds only
                            this version and catalog products
                         ─► submit version + products together
  └─ GitHub Release (only if every enabled step succeeded)
```

A tag that is not exactly `v<MARKETING_VERSION>` (for example `v1.0.0` while the
project says `1.0`, or `v1.1.0-beta.1`) fails before anything is built and
creates no GitHub Release. One tag runs one pipeline; the former
`github-release.yml` workflow is folded into this one.

Tag runs share one concurrency group with `queue: max`: releases run one at a
time, in order, and a newer tag never cancels one that is still waiting. Each
manual validation run has its own group, so it never waits behind or cancels a
release.

Waiting for App Store Connect to process the upload is its own job,
`wait-for-build`, which hands the processed build's id to the
`app-store-connect` job (listing, What's New, screenshots, creative assets,
review). If that job fails, **Re-run failed jobs** reuses the processed build
instead of waiting again against the original upload deadline (which would
always time out). A re-run never extends that deadline: a timed-out wait fails
again.

The `app-store-connect` job only sends what differs from App Store Connect, so
re-running it is safe, including after a submission that only partly went
through:

| Version state when the job re-runs | What the re-run does |
|------------------------------------|----------------------|
| Prepare for Submission (or rejected) | Sends only changed text, App Info and screenshot sets (a set with an image that failed or is still processing counts as changed and is uploaded again); uploads, sends to App Review or places only the creative images that need it; selects this run's build unless it is already selected; submits |
| `READY_FOR_REVIEW` (in a draft submission, for example after a failed submit) | Text and App Info can still change; screenshots must already match the repo and be processed, and creative images must already be in place or in App Review (Apple locks them); submits the draft, which must hold this version |
| `WAITING_FOR_REVIEW` / `IN_REVIEW` (the submit went through) | Writes nothing. Passes only if review holds this run's build, the listing, What's New and screenshots already match the repo (every screenshot processed), the creative images are in place or in App Review, and no catalog product is still Ready to Submit; otherwise fails without writing. A product left behind is never sent to App Review on its own: submit it in App Store Connect yourself (or with the next version) |

A brand-new run (a new tag, or **Re-run all jobs**) uploads a new build, which
can never replace one already in review: its preflight fails before anything is
built.

### App Store Connect CLI (`asc`)

Every App Store Connect call goes through the
[App Store Connect CLI](https://github.com/rorkai/App-Store-Connect-CLI) (`asc`,
MIT) instead of hand-written API code.
[`scripts/store/asc_cli.py`](../scripts/store/asc_cli.py) is the only place
that runs it:

- It is pinned to one release (`ASC_VERSION`, now 5.15.0) and installed by
  `asc_cli.py install`, which refuses a binary whose SHA-256 differs from the
  pinned value for that platform (`linux_amd64` and `macOS_arm64`). Every job
  that calls App Store Connect runs `asc_cli.py check` first, and every call
  re-checks the checksum of the `asc` on `PATH` before handing it credentials;
  no environment variable can point the scripts at another executable. The
  **Store release checks** workflow installs and checks it too, so a pin that no
  longer downloads or matches fails on the pull request.
- Credentials come only from the `APP_STORE_CONNECT_*` secrets, through asc's
  own environment variables; the keychain and asc config files are bypassed,
  and `ASC_STRICT_AUTH` rejects credentials mixed from several sources.
- Telemetry (`ASC_TELEMETRY_DISABLED`, `DO_NOT_TRACK`) and the skills update
  check are off.
- Checks that must never write run asc read-only (`ASC_READ_ONLY`): the
  preflight, build numbering, the build wait, `export_listing.py`, and the
  whole `prepare` job on validation runs. asc refuses a write in that mode
  before sending it (exit 6).
- On failure the error keeps asc's exit code and drops the key and issuer IDs.
  The build wait retries asc's server-side exit codes (HTTP 5xx, 408, 429 and
  timeouts) and network drops, which asc reports as a generic exit 1 with a
  connection error; auth, usage and not-found errors stop at once. asc itself
  retries GET requests that hit 429 or 503 (`ASC_MAX_RETRIES=5`).

The binary itself is still exported and uploaded by `xcodebuild`. To move to a
newer asc, change `ASC_VERSION` and both `ASC_SHA256` values from that release's
`asc_<version>_checksums.txt`, then run the store tests.

When the build job fails, its xcodebuild/altool logs are kept for 7 days as the
`ios-release-logs-<run id>-<attempt>` artifact, with the App Store Connect key
ID and issuer ID replaced by `<ASC_KEY_ID>` / `<ASC_ISSUER_ID>` in every file,
binary files and UTF-16 text included
([`redact_logs.py`](../scripts/store/redact_logs.py)). Links and files that
cannot be redacted are removed; if redaction itself fails, nothing is uploaded.

**Release notes.** App Store What's New comes only from
`store/metadata/ios/<locale>/whats_new.txt` (plain text; `RELEASE_NOTES.md`
never reaches the App Store) and is checked (present, non-empty, within Apple's
4000-character limit, in every locale) before the build starts, but only when
`IOS_UPLOAD_WHATS_NEW` is on; with it off, a tag never fails over What's New
text. `RELEASE_NOTES.md` only feeds the GitHub Release: a matching `## v1.0.1`
section becomes its notes, and without one (or without the file) GitHub
generates them (`--generate-notes`). On a tag push the prepare job checks this
before anything is built or uploaded: a matching section that is present but
empty, or a tag with two `## v1.0.1` sections, fails the run there instead of
after the store steps (the GitHub Release step repeats the check and never
publishes blank or ambiguous notes).

**Unused files never block a release.** The repository's listing and
screenshots are checked before the build only when `IOS_UPLOAD_LISTING` /
`IOS_UPLOAD_SCREENSHOTS` are on (the gated dry run in prepare), and only the
tag's own `RELEASE_NOTES.md` section is checked. The tests that check those
files whatever the switches say (and that no `RELEASE_NOTES.md` heading is
duplicated) run in the **Store release checks** workflow on pull requests and
`main`, and are skipped in release runs (`STORE_TESTS_SCOPE=release`).

A manual **Run workflow** (`workflow_dispatch`) is a validation run: it archives
with the CI signing identity, exports with cloud-managed distribution signing
and validates the IPA with App Store Connect (`altool --validate-app`). It never
uploads, edits the listing, submits or creates a GitHub Release, whatever the
switches say, and never creates an App Store version. Apple refuses versions it
has already approved, so fill in the optional **marketing_version** input with
the next version (e.g. `1.0.1`); the build is validated as that version without
changing the project.

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
| `IOS_CREATE_VERSION` | Create the tag's App Store version (Prepare for Submission) when App Store Connect does not have it, before the preflight; the version is read back before the run continues. An existing version is left alone. Refuses, before anything is built and without writing, when another version is still on its way to the store (anything but Ready for Distribution, replaced or removed), the tag is not newer than every existing version, the bundle id resolves to another app, or the version is not a plain `1.0` / `1.0.1`. Tag runs only |
| `IOS_UPLOAD_BUILD` | Build, sign and upload the binary to App Store Connect, then wait until it is processed |
| `IOS_UPLOAD_LISTING` | Version text (description, keywords, promotional text, marketing and support URLs) and App Info (name, subtitle, privacy policy URL) from `store/metadata/ios/<locale>/`. Only changed fields are sent |
| `IOS_UPLOAD_WHATS_NEW` | What's New from `store/metadata/ios/<locale>/whats_new.txt` (required for every locale when on) |
| `IOS_UPLOAD_SCREENSHOTS` | Replace the iPhone 6.9" and iPad 13" screenshots (see below) |
| `IOS_UPLOAD_CREATIVE_ASSETS` | Product page header and search results images from `store/creative/ios` (see below). A new image is uploaded to the Asset Library and sent to App Review in a submission of its own; once Apple approves it, a later run places it on the version. Never changes anything while the version is in a review submission |
| `IOS_SUBMIT_REVIEW` | Select this run's build and submit the version **and** any Ready-to-Submit catalog products for review. Requires `IOS_UPLOAD_BUILD` |
| `IOS_PUBLIC_RELEASE` | Release automatically after approval. Off = you release it by hand. Requires `IOS_SUBMIT_REVIEW` |
| `IOS_BUILD_POLL_SECONDS` | How often to check build processing: default 30, 10–600 |
| `IOS_BUILD_WAIT_MINUTES` | Total wait, counted from upload start (upload + processing): default 120, 10–300 |

Listing, What's New, screenshots, creative assets and submission need the App
Store version for the tag's version (e.g. 1.0.1) to exist in an editable state.
With `IOS_CREATE_VERSION` on, the tag run creates a missing one itself (in
Prepare for Submission) before the preflight; otherwise create it in App Store
Connect first and leave it in Prepare for Submission. A version created by a run
whose later steps fail stays in Prepare for Submission, and the next run for the
same tag reuses it. With any of those switches on, a read-only preflight in the
prepare job checks the version before anything is built, so a missing or locked
version (or a missing localization, a rejected creative image, or a catalog
product due for review that cannot be attached) fails the run before a binary is
uploaded. A build-only release (`IOS_UPLOAD_BUILD` alone) does not need the
version.

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
[`export_listing.py`](../scripts/store/export_listing.py), which runs asc
read-only. If you edit the listing in App Store Connect, export again so the
repo stays the source of truth (with the pinned asc on `PATH`, see the dry run
below):

```bash
python3 scripts/store/export_listing.py                 # the version on the App Store
python3 scripts/store/export_listing.py --version 1.0.1 # a version being prepared
```

App Info (name, subtitle, privacy URL) can only change while a new version is
being prepared. If those files differ from App Store Connect when nothing is
editable, the listing step fails instead of skipping them silently.
`APPSTORE.md` keeps reviewer notes and other submission details.

## Screenshots

`IOS_UPLOAD_SCREENSHOTS` uploads the App Store-ready images already in the
repo; nothing is resized or generated:

| App Store Connect slot | Source | Accepted sizes |
|------------------------|--------|----------------|
| `APP_IPHONE_67` (iPhone 6.9") | [`store/metadata/screenshots/ios/iphone/`](metadata/screenshots/ios/iphone/) | 2796×1290 (landscape) or 1290×2796 |
| `APP_IPAD_PRO_3GEN_129` (iPad 13") | [`store/metadata/screenshots/ios/ipad/`](metadata/screenshots/ios/ipad/) | 2752×2064, 2732×2048 or their portrait sizes |

Each set is replaced in file-name order (1–10 PNGs) for the `en-US` listing,
and the run waits until App Store Connect has processed every image. A set that
already holds exactly these images (same checksums, same order) and whose
images App Store Connect has all processed is left alone, so a re-run uploads
nothing. App Store Connect records an image's checksum as soon as it is
uploaded, before processing, so a set left by an attempt whose wait failed or
timed out is not taken as done: the re-run uploads it again and waits, or fails
if the version's screenshots are already locked. A missing folder, an empty
set, more than 10 files or any other size fails the run with a clear message
before anything is uploaded. asc uploads a set with `asc screenshots upload
--replace` (the old images are deleted first), from a copy of exactly these
images, and waits for Apple to process each one; the run then reads the set
back.

The images are uploaded exactly as committed, so export them as RGB PNGs: App
Store Connect, and asc before it uploads, refuses a PNG that stores an alpha
channel (colour types 4 and 6, or a `tRNS` chunk) even when every pixel is
opaque. With `IOS_UPLOAD_SCREENSHOTS` on, the preflight and the store step stop
on such a file before any App Store Connect call; the offline dry run (and so
the **Store release checks** workflow) names them as a warning.

## Creative assets

`IOS_UPLOAD_CREATIVE_ASSETS` (off) keeps the product page header and search
results images in the repo. Today there are none; put each image in its folder
before turning the switch on:

```
store/creative/ios/
  header/           one product page header image, 3840×1646 PNG
  search-results/   one search results image, 3:2, 1920×1280 to 3840×2560
```

Each folder takes one PNG without an alpha channel, or a JPEG; an image that
stores alpha stops the run before any App Store Connect call. An image is
matched in the Asset Library by file name and size, so give a changed image a
new file name. Apple reviews each new image on its own (ABYSM already has an
approved version): a run uploads it, sends it to App Review in a submission of
its own, and a later run places it on the `en-US` product page (or swaps it in
for the image already there) once it is approved. A rejected image stops the run
with Apple's reason. While the version is in a review submission nothing is
uploaded, sent or placed: images already in place or in App Review pass,
anything else fails the run. Apple's rules for these images: no prices, website
addresses, other platforms or Apple badges, and no transparency.

## Export compliance

ABYSM declares its export compliance answer in
[`Abysm/Info.plist`](../Abysm/Info.plist): `ITSAppUsesNonExemptEncryption` is
`false`, so App Store Connect never asks about a build by hand. Without it,
review submission fails with `usesNonExemptEncryption` missing (HTTP 409), as
it did for another app sharing this pipeline.

`false` is right while the game only uses exempt encryption: HTTPS (Apple's
networking and the RevenueCat SDK, which also uses the Keychain, hashing and
signature checks) and Apple's system crypto. If ABYSM ever adds its own
encryption, set the key to `true` and add `ITSEncryptionExportComplianceCode`
with the code App Store Connect issues for the app's encryption documentation.

Every run that builds (release or validation) checks it twice: `ios_release.py
gates` reads the app target's Debug and Release configurations before anything
is built, each on its own (both must exist and give the same answer from the
`INFOPLIST_KEY_ITSAppUsesNonExemptEncryption` build setting or the Info.plist
key, which must agree; other targets never count), and the bundle check after
the archive reads the archived
app's `Info.plist` (`ios_release.py export-compliance --info-plist`). A missing
answer, different or unknown values, or `true` without the code fails the run.

## In-app purchases

ABYSM sells one non-consumable, **Unlock the Deep**
(`com.apoorvdarshan.Abysm.unlockdeep`, entitlement `deep`), listed in
[`catalog/products.json`](catalog/products.json).
[`validate_catalog.py`](../scripts/store/validate_catalog.py) checks the catalog
against `Abysm.storekit` and `StoreManager.swift`. With `IOS_SUBMIT_REVIEW` on,
catalog products in `READY_TO_SUBMIT` join the same draft review submission as
the version (one-time purchases as `inAppPurchaseVersions` items, subscriptions
as `subscriptionVersions` items, via `asc review items-add`) and go to App
Review together with it, in the single submit after the final build recheck; if
that recheck fails, nothing is submitted. A reused draft is submitted only when
it holds this version and nothing else but versions of catalog products, so an
item added by hand never rides along; a draft holding creative images belongs to
their own review and is never used for the version. The draft that already holds
this version is reused; otherwise only a draft holding no app version is, so
another version's draft is never touched. A `READY_FOR_REVIEW` version that no
draft holds stops the run before anything is added. A product never goes to App
Review without the version: the deprecated `inAppPurchaseSubmissions` endpoint
is never used, and neither is a product-only review submission. If a re-run
finds the version already submitted while a catalog product is still Ready to
Submit, it fails without writing. Unlock the Deep is already approved, so it is
never resubmitted; products missing from the catalog are never submitted. If a
required product cannot be attached, the version is not submitted.

## Scripts

| Script | Role |
|--------|------|
| [`scripts/store/ios_release.py`](../scripts/store/ios_release.py) | Switches and tag rule, export compliance check (project and archived app), build number, wait for this run's build (asc read-only) |
| [`scripts/store/asc_cli.py`](../scripts/store/asc_cli.py) | Installs the pinned, checksum-verified `asc` and runs it (credentials, read-only mode, telemetry off, redacted errors); tells whether a PNG stores alpha, which asc refuses |
| [`scripts/store/asc_release.py`](../scripts/store/asc_release.py) | Version creation (`--create-version`), read-only preflight (`--preflight`), listing, What's New, screenshots, header and search results images, build selection, products, App Review; every call through `asc` |
| [`scripts/store/export_listing.py`](../scripts/store/export_listing.py) | Read-only export of the App Store listing into `store/metadata/` (asc read-only) |
| [`scripts/store/validate_catalog.py`](../scripts/store/validate_catalog.py) | Catalog vs. StoreKit file vs. app code |
| [`scripts/store/print_gates.py`](../scripts/store/print_gates.py) | Print the switches, showing invalid values as `INVALID` (never touches a store) |
| [`scripts/store/redact_logs.py`](../scripts/store/redact_logs.py) | Redact the App Store Connect key/issuer IDs from failed-build logs before they become an artifact |
| [`scripts/store/test_ios_release.py`](../scripts/store/test_ios_release.py) | Offline tests against a fake App Store Connect behind `asc`: disabled/invalid switches, tag mismatch, validation mode, build wait timeout/failure/ambiguity/mismatch/old build/missing upload time/network drops, selection read-back, export compliance (project and archived app), version creation (only when missing, never next to a version still on its way to the store or older than an existing one), the read-only preflight, safe re-runs in every version state (including screenshots that failed or are still processing), products going out with the version and never on their own, which draft is used and drafts holding items this release did not choose, screenshots and creative images with an alpha channel, creative assets (upload, review, placement, swap, locked versions, retries), the asc runner (credentials, read-only mode, redaction, pinned checksum), listing and screenshot checks, release notes, log redaction, workflow wiring (release queue, wait-for-build job, preflight, pinned asc and Python), and `test-ios.sh`'s simulator shutdown between the unit and UI tests |
| [`scripts/release_notes.py`](../scripts/release_notes.py) | GitHub Release notes from the matching `RELEASE_NOTES.md` section (else GitHub generates them); a duplicated section fails |

The store scripts need no Python packages: every App Store Connect call goes
through the pinned `asc` (see above), which only the jobs that call App Store
Connect install. They run on Python 3.13 from `actions/setup-python` (never the
runner's system Python), and their steps run unbuffered (`python3 -u`) so
progress shows in the live log. The offline checks run in the **Store release
checks** workflow for changes to these files, and again before every release
run.

## How to release

1. Bump `MARKETING_VERSION` (and `CURRENT_PROJECT_VERSION` if you like; the
   pipeline always uses at least one more than App Store Connect's highest build).
2. Before relying on signing changes, run **iOS Release → Run workflow** with the
   new version (validation only).
3. Whenever a listing, What's New, screenshot, creative asset or review switch
   is on, the 1.0.1 App Store version must exist. With `IOS_CREATE_VERSION` on,
   the tag run creates it; otherwise **create it in App Store Connect first**
   (iOS App → add version, leave it in Prepare for Submission). The preflight
   fails the tag run before the build without it. Then update `store/metadata/`
   and add `whats_new.txt`; optionally add one `## v1.0.1` section to
   `RELEASE_NOTES.md`.
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

The preflight can also run locally with App Store Connect credentials
(`APP_STORE_CONNECT_API_KEY_ID` / `_ISSUER_ID` / `_API_KEY_P8`) and the pinned
asc on `PATH`; asc runs read-only, so nothing can change:

```bash
python3 scripts/store/asc_cli.py install --dest "$HOME/.local/asc-5.15.0"
export PATH="$HOME/.local/asc-5.15.0:$PATH"
python3 scripts/store/asc_cli.py check
UPLOAD_LISTING=true SUBMIT_IOS_REVIEW=true \
  python3 scripts/store/asc_release.py --preflight --version 1.0.1
```

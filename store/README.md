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
       IOS_UPLOAD_SCREENSHOTS ─► stage the screenshots as RGB copies (no alpha channel)
       IOS_UPLOAD_CREATIVE_ASSETS ─► check the header / search results images
                                     (size, format, no alpha, well-formed file)
       listing / What's New / screenshot / creative asset / review switch on
                        ─► read-only preflight: the 1.0.1 App Store version exists and
                           its state, locales and due catalog products allow those steps,
                           a READY_FOR_REVIEW version's draft (with IOS_SUBMIT_REVIEW) and
                           the images' Asset Library state (with IOS_UPLOAD_CREATIVE_ASSETS)
       IOS_UPLOAD_BUILD ─► next build number from App Store Connect
                        ─► archive Release ─► verify bundle id / version / build in every bundle
                        ─► cloud-signed export + upload
                        ─► wait-for-build job: until THIS build is VALID
                           (poll 30 s, up to 120 min from upload start)
       IOS_SUBMIT_REVIEW ─► pick and check the version's draft review submission
                            (read-only, before any write) and reserve it
       IOS_UPLOAD_LISTING / IOS_UPLOAD_WHATS_NEW / IOS_UPLOAD_SCREENSHOTS ─► version metadata
                           (only what differs from App Store Connect)
       IOS_UPLOAD_CREATIVE_ASSETS ─► new images: Asset Library upload, then App Review
                                     in a submission of their own
                                  ─► approved images: placed on the version (en-US)
       IOS_SUBMIT_REVIEW ─► select this run's build, read it back, set release type
                         ─► add Ready-to-Submit catalog products to the draft submission
                         ─► recheck build + selection ─► submit version + products together
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
through. Header and search results images already in the Asset Library are
never uploaded again, an image already placed is left alone, and an interrupted
image review is finished in the draft it left (see below).

| Version state when the job re-runs | What the re-run does |
|------------------------------------|----------------------|
| Prepare for Submission (or rejected) | Sends only changed text, App Info and screenshot sets (a set with an image that failed or is still processing counts as changed and is uploaded again); uploads, sends to App Review or places only the header and search results images that need it; selects this run's build unless it is already selected; submits |
| `READY_FOR_REVIEW` (in a draft submission, for example after a failed submit) | Text and App Info can still change; screenshots must already match the repo and be processed (Apple locks them); header and search results images are not uploaded, reviewed or placed (one that still needs uploading or review fails the run, an approved one waits for a later run); submits the draft, which must hold this version |
| `WAITING_FOR_REVIEW` / `IN_REVIEW` (the submit went through) | Writes nothing. Passes only if review holds this run's build, the listing, What's New and screenshots already match the repo (every screenshot processed), the header and search results images are in place, approved or in App Review, and no catalog product is still Ready to Submit; otherwise fails without writing. A product left behind is never sent to App Review on its own: submit it in App Store Connect yourself (or with the next version) |

A brand-new run (a new tag, or **Re-run all jobs**) uploads a new build, which
can never replace one already in review: its preflight fails before anything is
built.

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

**Unused files never block a release.** The repository's listing, screenshots
and header / search results images are checked before the build only when
`IOS_UPLOAD_LISTING` / `IOS_UPLOAD_SCREENSHOTS` / `IOS_UPLOAD_CREATIVE_ASSETS`
are on (the gated dry run in prepare), and only the tag's own
`RELEASE_NOTES.md` section is checked. The tests that check those files
whatever the switches say (and that no `RELEASE_NOTES.md` heading is
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
| `IOS_UPLOAD_SCREENSHOTS` | Replace the iPhone 6.9", iPad 13", iPhone Duo and Apple Watch screenshots, uploaded as RGB copies (see below) |
| `IOS_UPLOAD_CREATIVE_ASSETS` | Product page header and search results images from `store/creative/ios/`, checked (size, format, no alpha) before the build. A new image is uploaded to the Asset Library once and sent to App Review in a submission of its own; an approved image is placed on the version's en-US page while the version can be edited (see below). Empty folders mean nothing to do. Off: never read |
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
version (or a missing localization, a `READY_FOR_REVIEW` version that no usable
draft holds, a header or search results image the version cannot take now, or a
catalog product due for review that cannot be attached) fails the run before a
binary is uploaded. A build-only release (`IOS_UPLOAD_BUILD` alone) does not
need the version.

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

`IOS_UPLOAD_SCREENSHOTS` uploads the App Store-ready images already in the
repo; nothing is resized or generated:

| App Store Connect slot | Source | Accepted sizes |
|------------------------|--------|----------------|
| `APP_IPHONE_67` (iPhone 6.9") | [`store/metadata/screenshots/ios/iphone/`](metadata/screenshots/ios/iphone/) | 2796×1290 (landscape) or 1290×2796 |
| `APP_IPAD_PRO_3GEN_129` (iPad 13") | [`store/metadata/screenshots/ios/ipad/`](metadata/screenshots/ios/ipad/) | 2752×2064, 2732×2048 or their portrait sizes |
| `APP_IPHONE_DUO` (iPhone Duo, optional) | [`store/metadata/screenshots/ios/iphone-duo/`](metadata/screenshots/ios/iphone-duo/) | outer screen 1398×2034 or inner screen 2007×2853 |
| Apple Watch (optional) | [`store/metadata/screenshots/ios/watch/`](metadata/screenshots/ios/watch/) | each frame's size picks its set (below) |

Each set is replaced in file-name order (1–10 PNGs) for the `en-US` listing,
and the run waits until App Store Connect has processed every image. A set that
already holds exactly these images (same checksums, same order) and whose
images App Store Connect has all processed is left alone, so a re-run uploads
nothing. App Store Connect records an image's checksum as soon as it is
uploaded, before processing, so a set left by an attempt whose wait failed or
timed out is not taken as done: the re-run uploads it again and waits, or fails
if the version's screenshots are already locked. A missing iPhone or iPad
folder, an empty iPhone or iPad set, more than 10 files or any other size fails
the run with a clear message before anything is uploaded.

App Store screenshots are uploaded as RGB PNGs. App Store Connect refuses a PNG
that stores an alpha channel, even when every pixel is opaque, and ABYSM's
committed screenshots are RGBA, so the run stages a copy of each in a temporary
folder: Pillow lays transparent pixels over black once and keeps the colour
profile (ICC profile, sRGB, gamma and chromaticity chunks). The files in
`store/metadata/screenshots/` are only read, never rewritten. The dry run, the
preflight and the set checksum comparisons all use the same copies. Without
Pillow, a file is copied as it is and one that stores alpha fails the run.
Right before upload, `asc_release.py` refuses any copy that still stores alpha
(PNG colour type 4 or 6, or a `tRNS` chunk) or is not a well-formed PNG
(complete chunks with matching CRCs, image data of the size its header gives, a
final `IEND`), before anything is sent.

The live 1.1 sets (uploaded by hand as `image1.png` to `image5.png`) hold the
same pixels as the repository's files, checked on 2026-10-20, but App Store
Connect compares checksums, not pixels: the first run with
`IOS_UPLOAD_SCREENSHOTS` on replaces both sets once with the RGB copies, and
later runs find them matching.

The iPhone Duo and Apple Watch sets are optional: ABYSM has none, and without
PNGs in their folder the live sets in App Store Connect are left alone. Apple
Watch screenshots go with the other sets when `store/metadata/screenshots/ios/watch/`
holds PNGs. Each frame's size picks its set: 416×496 `APP_WATCH_SERIES_10`,
422×514 or 410×502 `APP_WATCH_ULTRA`, 396×484 `APP_WATCH_SERIES_7`, 368×448
`APP_WATCH_SERIES_4`, 312×390 `APP_WATCH_SERIES_3`; any other size fails the
run. Like every set, a Watch set is replaced only when its files differ, and
only compared while the version is in a review submission. Watch sets the
repository has no frames for (such as an `APP_WATCH_ULTRA` set uploaded by hand)
are left alone; remove them in App Store Connect if they should go.

## Header and search results images

With `IOS_UPLOAD_CREATIVE_ASSETS` on, the images in `store/creative/ios/` go to
the App Store product page: `header/` takes one PNG of exactly 3840×1646, and
`search-results/` one PNG or JPEG in 3:2, from 1920×1280 to 3840×2560. Neither
may store alpha. `prepare` checks sizes, formats, alpha and that each file is
a complete, well-formed image before anything is built, then (read-only) each
image's Asset Library state the way the store step plans it, so an image the
version cannot take now fails before the build. A slot without an image is left
alone. ABYSM has no header or search results image yet: both folders hold only
a README, so the switch has nothing to do until an image is committed.

```
store/creative/ios/
  header/           one product page header PNG, exactly 3840×1646
  search-results/   one search results PNG or JPEG, 3:2, 1920 to 3840 wide
```

They live in the app's Asset Library and are reviewed on their own, apart from
the version:

1. An image is uploaded once, matched by file name and size. A reservation an
   interrupted upload left in `AWAITING_UPLOAD` (like a failed or archived image)
   does not count, and the image is uploaded again. To change an image, commit
   it under a new file name. An image App Review rejected stops the run until it
   is replaced.
2. A new image goes to App Review in a review submission of its own, never the
   version's draft. A draft an earlier attempt left holding only some of the
   images is finished first, else an empty draft, else a new one is created, so
   re-runs never pile up drafts. The run submits it only when it holds exactly
   these images.
3. Once Apple approves an image, the run places it on the version's en-US
   localization (`POST /v1/appAssetLibraryPlacements`, placement group
   `DEFAULT_PROFILE`), only while the version can be edited (Prepare for
   Submission or rejected). An image already placed there is left alone; another
   image in the same slot is replaced in the same request. Approval takes a while,
   so a new image is usually placed by the next release's run.

While the version is in a review submission (`READY_FOR_REVIEW`,
`WAITING_FOR_REVIEW` or `IN_REVIEW`), nothing is uploaded, reviewed or placed:
an image that still needs uploading or review fails the run, and an approved
image waits for a later run.

With `IOS_SUBMIT_REVIEW` on, the run picks the version's draft review submission
before anything is written: the draft that already holds the version, else a
draft holding no app version, never one holding header or search results images.
That draft is reserved for the version and its products, so image reviews never
take it. A `READY_FOR_REVIEW` version that no such draft holds stops the run in
`prepare`, before the build, and the store step checks it again before its first
write.

Apple's rules for these images: no prices, website addresses, other platforms or
Apple badges, and no transparency.

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
the version (one-time purchases as `inAppPurchaseVersion` items, subscriptions
as `subscriptionVersion` items) and go to App Review together with it, in the
single submit after the final build recheck; if that recheck fails, nothing is
submitted. A product never goes to App Review without the version: the
deprecated `inAppPurchaseSubmissions` endpoint is never used, and neither is a
product-only review submission. If a re-run finds the version already submitted
while a catalog product is still Ready to Submit, it fails without writing.
Unlock the Deep is already approved, so it is never resubmitted; products
missing from the catalog are never submitted. If a required product cannot be
attached, the version is not submitted.

## Scripts

| Script | Role |
|--------|------|
| [`scripts/store/ios_release.py`](../scripts/store/ios_release.py) | Switches and tag rule, export compliance check (project and archived app), build number, wait for this run's build |
| [`scripts/store/asc_release.py`](../scripts/store/asc_release.py) | Version creation (`--create-version`), read-only preflight (`--preflight`), listing, What's New, iPhone / iPad / iPhone Duo / Apple Watch screenshots (uploaded as RGB copies), header and search results images, build selection, products, App Review |
| [`scripts/store/export_listing.py`](../scripts/store/export_listing.py) | Read-only export of the App Store listing into `store/metadata/` |
| [`scripts/store/validate_catalog.py`](../scripts/store/validate_catalog.py) | Catalog vs. StoreKit file vs. app code |
| [`scripts/store/print_gates.py`](../scripts/store/print_gates.py) | Print the switches, showing invalid values as `INVALID` (never touches a store) |
| [`scripts/store/redact_logs.py`](../scripts/store/redact_logs.py) | Redact the App Store Connect key/issuer IDs from failed-build logs before they become an artifact |
| [`scripts/store/test_ios_release.py`](../scripts/store/test_ios_release.py) | Offline tests: disabled/invalid switches, tag mismatch, validation mode, build wait timeout/failure/ambiguity/mismatch/old build/missing upload time, selection read-back, export compliance (project and archived app), version creation (only when missing, never next to a version still on its way to the store or older than an existing one), preflight, safe re-runs in every version state (including screenshots that failed or are still processing), products going out with the version and never on their own, which draft the version uses, token refresh, listing and screenshot checks, the screenshots' RGB copies and the alpha guard, Apple Watch and iPhone Duo sets, header and search results images (upload, review, placement, drafts), release notes, log redaction, workflow wiring (release queue, wait-for-build job, preflight, pinned Python), and `test-ios.sh`'s simulator shutdown between the unit and UI tests |
| [`scripts/release_notes.py`](../scripts/release_notes.py) | GitHub Release notes from the matching `RELEASE_NOTES.md` section (else GitHub generates them); a duplicated section fails |

[`requirements-store.txt`](../requirements-store.txt) (PyJWT, and Pillow for
the RGB screenshot copies; hash-pinned) is installed only by jobs that call the
App Store Connect API, always on Python 3.13 from `actions/setup-python` (never
the runner's system Python), and in prepare before the offline checks; those
steps run unbuffered (`python3 -u`) so progress shows in the live log. The
offline checks run in the **Store release checks** workflow for changes to these
files, with the store tooling installed first (`STORE_TESTS_NEED_PILLOW`, so the
tests of the RGB copies cannot skip), and again before every release run.

## How to release

1. Bump `MARKETING_VERSION` (and `CURRENT_PROJECT_VERSION` if you like; the
   pipeline always uses at least one more than App Store Connect's highest build).
2. Before relying on signing changes, run **iOS Release → Run workflow** with the
   new version (validation only).
3. Whenever a listing, What's New, screenshot, creative asset or review switch
   is on, the 1.0.1 App Store version must exist. With `IOS_CREATE_VERSION` on, the tag run
   creates it; otherwise **create it in App Store Connect first** (iOS App → add
   version, leave it in Prepare for Submission). The preflight fails the tag run
   before the build without it. Then update `store/metadata/` and add
   `whats_new.txt`; optionally add one `## v1.0.1` section to `RELEASE_NOTES.md`.
4. Turn on only the switches you want (the master switch plus each operation).
   Leave `IOS_SUBMIT_REVIEW` and `IOS_PUBLIC_RELEASE` off until you intend that release.
5. Push the tag: `git tag -a v1.0.1 -m "ABYSM 1.0.1" && git push origin v1.0.1`.

## Dry run

```bash
python3 -m pip install --require-hashes -r requirements-store.txt   # Pillow, for the RGB copies
python3 -m unittest discover -s scripts/store -p 'test_*.py'
python3 scripts/store/validate_catalog.py
python3 scripts/store/print_gates.py
UPLOAD_LISTING=true UPLOAD_SCREENSHOTS=true SUBMIT_IOS_REVIEW=true \
  python3 scripts/store/asc_release.py --dry-run --build-id DRY-RUN --build-number 1
UPLOAD_CREATIVE_ASSETS=true python3 scripts/store/asc_release.py --dry-run   # header / search images
```

The preflight can also run locally with App Store Connect credentials
(`APP_STORE_CONNECT_API_KEY_ID` / `_ISSUER_ID` / `_API_KEY_P8`); it only sends
GET requests:

```bash
UPLOAD_LISTING=true SUBMIT_IOS_REVIEW=true \
  python3 scripts/store/asc_release.py --preflight --version 1.0.1
```

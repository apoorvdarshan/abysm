# Store releases

ABYSM's App Store releases run on
[apoorvdarshan/store-release](https://github.com/apoorvdarshan/store-release), a shared set
of reusable workflows and Python tooling. ABYSM's own release scripts (`scripts/store/`
at `a12a6d2`) moved there unchanged as the `abysm` flow
([flows](https://github.com/apoorvdarshan/store-release/blob/v0.2.0/docs/flows.md#abysm-iosflow--abysm)), so every
rule below is what this repository's pipeline did before. Two thin caller workflows
pin store-release by commit SHA, with the version in a `# vX.Y.Z` comment (v0.2.0 today):

| Workflow | Trigger | What it does |
|----------|---------|--------------|
| [`ios-release.yml`](../.github/workflows/ios-release.yml) | `v<MARKETING_VERSION>` tag | release run (e.g. `v1.0.1` for 1.0.1; any other `v*` tag fails before anything is built) |
| | **Run workflow** | validation only: archive, cloud-signed export and App Store Connect validation of the IPA, plus a read-only store plan. Never uploads, edits the listing, submits, creates a version or a GitHub Release |
| [`store-checks.yml`](../.github/workflows/store-checks.yml) | pull requests and `main` pushes that touch store files, **Run workflow** | checks the store data, the catalog, export compliance, [`store-release.toml`](store-release.toml) and the callers against the pinned version, and dry-runs every App Store Connect operation with every switch on (no network). Never uploads |

**Nothing reaches the App Store unless its switch is on**, and merging never
releases: only a tag push does. The callers are rendered by store-release
(`run.py callers render`); Store checks fails when one is edited by hand or pins
anything but a store-release release. Dependabot moves both pins to a new
store-release release in one PR of its own, seven days after it is published.

How the pipeline behaves is documented in store-release (v0.2.0):
[switches](https://github.com/apoorvdarshan/store-release/blob/v0.2.0/docs/switches.md),
[secrets](https://github.com/apoorvdarshan/store-release/blob/v0.2.0/docs/secrets.md),
[jobs and checks](https://github.com/apoorvdarshan/store-release/blob/v0.2.0/docs/workflows.md),
[store plan](https://github.com/apoorvdarshan/store-release/blob/v0.2.0/docs/plan.md),
[re-runs](https://github.com/apoorvdarshan/store-release/blob/v0.2.0/docs/rerun.md),
[verifying downloads](https://github.com/apoorvdarshan/store-release/blob/v0.2.0/docs/verification.md),
[the config file](https://github.com/apoorvdarshan/store-release/blob/v0.2.0/docs/config.md)
and [how a new release reaches this repository](https://github.com/apoorvdarshan/store-release/blob/v0.2.0/docs/release-process.md#how-apps-receive-a-release).
This file keeps ABYSM's own facts.

**Xcode Cloud was removed for ABYSM on 2026-10-14**, after this pipeline passed
validation: its workflow and product were deleted in App Store Connect. Never
re-create an Xcode Cloud workflow for `v*` tags: Xcode Cloud triggers live in App
Store Connect, not in this repo, so no GitHub switch can stop them, and both
pipelines would upload a build for the same tag.

## What this repository keeps

- [`store-release.toml`](store-release.toml): where the store files are and ABYSM's
  fixed identities: bundle id `com.apoorvdarshan.Abysm`, App Store Connect app
  `6783505799`, team `23RV7FYH36`, the Xcode to build with, the screenshot sets and
  the GitHub Release title (`ABYSM vX.Y`, plus ` (build N)` when the run uploaded one;
  an existing release is left as it is).
- The switches (repository variables) and credentials (repository secrets) below.
- The listing, What's New, screenshots, header and search results images and the
  product catalog under `store/`, and [`RELEASE_NOTES.md`](../RELEASE_NOTES.md)
  (GitHub Release bodies). `APPSTORE.md` keeps reviewer notes and other submission
  details.
- The gate a tag run must pass first: [`ios-tests.yml`](../.github/workflows/ios-tests.yml)
  (`scripts/test-ios.sh`: unit and UI tests; a suite that runs no tests fails), as the
  caller's `quality` job. `scripts/test-ios.sh`'s simulator shutdown between the two
  suites is tested against a fake `xcrun` by
  [`scripts/ci/test_test_ios.py`](../scripts/ci/test_test_ios.py), run by
  [`test-ios-script.yml`](../.github/workflows/test-ios-script.yml).

## Current switches

Repository **Variables** (Settings → Secrets and variables → Actions → Variables),
as of 2026-10-21. Missing means off; any value other than
`true/false/yes/no/on/off/1/0` fails the run, even when the master switch is off.

| Variable | Value | When `true` |
|----------|-------|-------------|
| `IOS_RELEASE_AUTOMATION` | `true` | Master switch. Off: every operation below is skipped and a tag only gets its GitHub Release |
| `IOS_CREATE_VERSION` | `true` | Create the tag's App Store version (Prepare for Submission) when App Store Connect does not have it, before the preflight; refuses without writing when another version is still on its way to the store or the tag is not newer than every existing version. Tag runs only |
| `IOS_UPLOAD_BUILD` | `true` | Build, sign and upload the binary, then wait until App Store Connect has processed this run's build |
| `IOS_UPLOAD_LISTING` | not set (off) | Version text and App Info from `store/metadata/ios/<locale>/`; only changed fields are sent |
| `IOS_UPLOAD_WHATS_NEW` | `true` | What's New from `store/metadata/ios/<locale>/whats_new.txt` (required for every locale when on) |
| `IOS_UPLOAD_SCREENSHOTS` | not set (off) | Replace the iPhone 6.9", iPad 13", iPhone Duo and Apple Watch sets, uploaded as RGB copies |
| `IOS_UPLOAD_CREATIVE_ASSETS` | not set (off) | Product page header and search results images from `store/creative/ios/` |
| `IOS_SUBMIT_REVIEW` | `true` | Select this run's build and submit the version **and** any Ready-to-Submit catalog products for review. Requires `IOS_UPLOAD_BUILD` |
| `IOS_PUBLIC_RELEASE` | `true` | Release automatically after approval. Requires `IOS_SUBMIT_REVIEW` |
| `IOS_BUILD_POLL_SECONDS` | not set (30) | How often to check build processing: 10–600 |
| `IOS_BUILD_WAIT_MINUTES` | not set (120) | Total wait from upload start (upload + processing): 10–300 |

With these values, a `v1.0.1` tag runs the unit and UI tests, creates App Store
version 1.0.1 when App Store Connect does not have it yet, checks `whats_new.txt`
before anything is built, builds, signs and uploads the binary, waits until App
Store Connect has processed it, sets What's New, selects the build and submits the
version (with any Ready-to-Submit catalog product) for review, released as soon as
Apple approves it. The listing, screenshots and header and search results images
are left alone. Then it creates the GitHub Release `ABYSM v1.0.1 (build N)`.

Each **Run workflow** prints this plan for the switches as they are at that moment
(the `store-plan` job's summary).

## Secrets

| Secret | Used for |
|--------|----------|
| `APP_STORE_CONNECT_API_KEY_ID` | Admin-role App Store Connect API key: build numbers, cloud-managed distribution signing, upload, build readiness, listing, review |
| `APP_STORE_CONNECT_ISSUER_ID` | Its issuer |
| `APP_STORE_CONNECT_API_KEY_P8` | Its private key (`.p8` body) |
| `IOS_DEV_SIGNING_P12_BASE64` | Shared CI Apple Development identity (base64 `.p12`; certificate "Apple Development: Created via API", ID `NVNGDQGCKK`, expires 2027-10-14) that signs the archive. App Store signing happens at export with Apple's cloud-managed distribution certificate |
| `IOS_DEV_SIGNING_P12_PASSWORD` | Password for that `.p12` |

The caller passes each reusable workflow exactly the secrets it declares, by name
(never `secrets: inherit`).

**Certificate rotation.** The development certificate is shared by several of
Apoorv's apps (Fud AI, Verceltics, ABYSM, iitjee, Quit All, Scowld, Sesslet) and
its private key exists only in these secrets. Before it expires on 2027-10-14
(or if it is revoked), follow
[the shared CI signing identity](https://github.com/apoorvdarshan/store-release/blob/v0.2.0/docs/secrets.md#the-shared-ci-signing-identity):
replace both `IOS_DEV_SIGNING_*` secrets in every repo that uses it, run a
validation for each, and then revoke the old certificate.

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

These files were exported read-only from the live 1.0 listing with ABYSM's
listing exporter, which now runs from store-release. If you edit the listing in
App Store Connect, export again so the repo stays the source of truth (GET
requests only; needs the three `APP_STORE_CONNECT_*` values in the environment
and a checkout of store-release at the pinned tag with its `requirements.txt`
installed):

```bash
python3 -I <store-release>/run.py --app-root . ios export-listing                  # the version on the App Store
python3 -I <store-release>/run.py --app-root . ios export-listing --version 1.0.1  # a version being prepared
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

Every run that builds (release or validation) checks it twice: `ios gates`
reads the app target's Debug and Release configurations before anything is
built, each on its own (both must exist and give the same answer from the
`INFOPLIST_KEY_ITSAppUsesNonExemptEncryption` build setting or the Info.plist
key, which must agree; other targets never count), and the bundle check after
the archive reads the archived app's `Info.plist` (`ios export-compliance
--info-plist`). A missing answer, different or unknown values, or `true` without
the code fails the run. **Store checks** also runs the project check on pull
requests and requires the answer `NO`.

## In-app purchases

ABYSM sells one non-consumable, **Unlock the Deep**
(`com.apoorvdarshan.Abysm.unlockdeep`, entitlement `deep`), listed in
[`catalog/products.json`](catalog/products.json).
The catalog check (`catalog check`, ABYSM's own `validate_catalog.py` ported to
store-release) compares it with `Abysm.storekit` and `StoreManager.swift` on every
release run and pull request. With `IOS_SUBMIT_REVIEW` on,
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

## How to release

1. Bump `MARKETING_VERSION` (and `CURRENT_PROJECT_VERSION` if you like; the
   pipeline always uses at least one more than App Store Connect's highest build).
2. Update `store/metadata/` and add `whats_new.txt` (required while
   `IOS_UPLOAD_WHATS_NEW` is on); optionally add one `## v1.0.1` section to
   `RELEASE_NOTES.md` (it becomes the GitHub Release body; without one GitHub
   generates the notes, and an empty or duplicated section fails the run before
   anything is built).
3. Run **iOS Release → Run workflow** with `marketing_version` set to the new
   version (validation only; Apple refuses versions it has already approved). Read
   the `store-plan` job's summary: it lists every write the tag run would make with
   the current switches, and anything that would stop it.
4. Turn on only the switches you want. With a listing, What's New, screenshot,
   creative asset or review switch on, the version must exist: `IOS_CREATE_VERSION`
   creates a missing one, otherwise create it in App Store Connect and leave it in
   Prepare for Submission. A read-only preflight checks it before anything is built.
5. Push the tag: `git tag -a v1.0.1 -m "ABYSM 1.0.1" && git push origin v1.0.1`.
6. If a later step fails, fix the cause and use **Re-run failed jobs**
   ([re-runs](https://github.com/apoorvdarshan/store-release/blob/v0.2.0/docs/rerun.md)): the store step only sends what differs, and
   `wait-for-build` keeps its result.

## Rolling back

Reverting the pull request that moved ABYSM to store-release restores the previous
pipeline; switch names, values and secrets did not change.

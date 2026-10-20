# Contributing to ABYSM

Thanks for helping with ABYSM. The game is a Swift + SpriteKit app for iPhone
and iPad, with a small static website in `web/` and Python release tooling in
`scripts/`. Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).

## Reporting bugs and requesting features

- **Bugs:** open a [bug report](https://github.com/apoorvdarshan/abysm/issues/new?template=bug_report.yml),
  or tap the bug button on the game's title screen, which fills in the app
  version, device, and iOS version for you. Add the steps to reproduce.
- **Ideas:** open a [feature request](https://github.com/apoorvdarshan/abysm/issues/new?template=feature_request.yml),
  or tap the light bulb button on the title screen.
- **Security problems:** do not open an issue. Follow [SECURITY.md](SECURITY.md).

Issues and pull requests are public. The maintainer reads every one and replies
in the issue.

## Making a change

1. Fork the repository and clone your fork.
2. Create a branch: `git checkout -b fix/short-description`.
3. Make your change, with tests (see [Tests](#tests)).
4. Run the checks for the parts you touched (see below).
5. Open a pull request against `main` and fill in the template.

Keep each pull request to one topic. CI must pass before a pull request is
merged.

## Building the app

1. Open `Abysm.xcodeproj` in Xcode (CI uses Xcode 27).
2. Select the **Abysm** scheme and run on an iOS 17+ simulator or device. The
   game is landscape only.
3. For a device build, choose your own development team under Signing &
   Capabilities.

Swift Package Manager resolves the only dependency, RevenueCat, on first open.
Debug simulator builds that run under XCTest or with `--ui-testing` never
configure RevenueCat, so tests stay offline and can never start a purchase.

## Checks

| Area | Command |
| --- | --- |
| App (unit + UI tests) | `bash scripts/test-ios.sh` |
| `scripts/test-ios.sh` (fake `xcrun`) | `python3 -m unittest -v scripts/ci/test_test_ios.py` |
| Store data and release config | the **Store checks** workflow (see [`store/README.md`](store/README.md)) |
| Website | `cd web && npm ci && npm audit && npm run build` (Node.js 22+) |

`scripts/test-ios.sh` creates its own simulator, builds once, runs the unit
tests and then the UI tests, and deletes the simulator afterwards. It fails if
either suite runs no tests. CI runs the same script, plus CodeQL.

## Tests

**New behavior and bug fixes must come with automated tests.** Pull requests
that change behavior without a test are not merged unless a test is impractical,
and then the pull request must explain why and how the change was checked.

- **Game logic** (depth zones, creatures, saving, controls, the paywall state
  machine): unit tests in `AbysmTests/`.
- **Screens and flows:** UI tests in `AbysmUITests/`. They drive the real
  SpriteKit screens by VoiceOver label, so make new buttons
  `AccessibleButtonNode`s with a label.
- **CI scripts:** `unittest` tests in `scripts/ci/` (for example
  `scripts/ci/test_test_ios.py` for `scripts/test-ios.sh`).
- **Release tooling:** it lives in
  [apoorvdarshan/store-release](https://github.com/apoorvdarshan/store-release), with its tests; change it there.

## Code guidelines

- **Swift 5 language mode** with `SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor`.
  Mark pure data and helpers `nonisolated` where needed.
- **SpriteKit only** for the game. Keep pixel art crisp with nearest-neighbor
  filtering.
- **Localization:** every user-facing string goes through `L(key, english)` and
  lives in `Abysm/Localizable.xcstrings` with all 16 languages. Use `GameFont`
  so non-Latin scripts fall back to a font that has their glyphs.
- **Accessibility:** buttons are `AccessibleButtonNode`s with a VoiceOver label;
  hidden buttons must not be reachable with VoiceOver.
- **Controls:** anything you can do by touch should also work with a game
  controller.
- **Dependencies:** ask in an issue before adding one. RevenueCat is the only
  runtime dependency.
- **Workflows:** pin every action to a full commit SHA, give each workflow
  read-only `permissions` by default, and never print secrets.

## License

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE).

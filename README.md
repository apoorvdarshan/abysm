<p align="center">
  <img src="Abysm/Assets.xcassets/AppIcon.appiconset/AppIcon.png" alt="ABYSM" width="160" height="160" />
</p>

<h1 align="center">ABYSM</h1>

<p align="center"><em>A dive to the bottom of the sea.</em></p>

<p align="center">
  <img alt="Platform" src="https://img.shields.io/badge/platform-iOS%20%7C%20iPadOS-0a1a3a?style=flat-square" />
  <img alt="iOS" src="https://img.shields.io/badge/iOS-17%2B-1b6ea8?style=flat-square" />
  <img alt="Swift" src="https://img.shields.io/badge/Swift-5-orange?style=flat-square" />
  <img alt="Engine" src="https://img.shields.io/badge/SpriteKit-2d9bb0?style=flat-square" />
  <img alt="Languages" src="https://img.shields.io/badge/languages-16-2bb673?style=flat-square" />
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-2bb673?style=flat-square" /></a>
</p>

<p align="center">
  <a href="https://www.bestpractices.dev/projects/15505"><img alt="OpenSSF Best Practices" src="https://www.bestpractices.dev/projects/15505/badge" /></a>
  <a href="https://scorecard.dev/viewer/?uri=github.com/apoorvdarshan/abysm"><img alt="OpenSSF Scorecard" src="https://api.scorecard.dev/projects/github.com/apoorvdarshan/abysm/badge" /></a>
</p>

---

**ABYSM** is a calm, free-swim deep-sea exploration game. Sink from the sunlit surface all the way down to the bottom of the ocean — the 10,935 m **Challenger Deep** — meeting the real creatures that live at each depth along the way.

No goals. No timers. No combat. Just you, a headlamp, and the slow weightless drift into the dark.

> Put on headphones, turn the lights down, and descend.

## 🌊 The descent

The ocean is built to scale, from the warm shallows to the crushing trench floor. Each zone gets darker, colder, and stranger than the last.

| Zone | Depth | What it feels like |
|------|-------|--------------------|
| ☀️ Sunlight Zone | 0 – 200 m | Warm, bright, full of life |
| 🌫️ Twilight Zone | 200 – 1,000 m | Fading blue gloom, lit by living glow |
| 🌑 Midnight Zone | 1,000 – 4,000 m | Eternal black, near-freezing |
| 🕳️ The Abyss | 4,000 – 6,000 m | Pitch-black plains, immense pressure |
| ⚫ Hadal Zone | 6,000 – 10,935 m | The deepest trenches — barely alive |

## ✨ Features

- **75 real sea creatures** placed at their true depths, each with a one-line fact — from the manatee in the shallows to the anglerfish, giant squid, and the hadal snailfish at the very bottom.
- **8 real ocean landmarks** to find on the way down, including the **RMS Titanic** (3,800 m), the **USS Johnston** (6,241 m), and the **Challenger Deep** (10,935 m).
- **A living headlamp** that carves a glowing circle out of the darkening deep.
- **Breach the surface** like a dolphin, then sink back into the blue.
- Original **pixel art**, procedurally generated **ambient audio**, and gentle **haptics**.
- Full **game-controller** support, or a simple on-screen joystick.
- Playable in **16 languages**.

## 🎮 Controls

**Touch**

- Bottom-left **joystick** to swim.
- Bottom-right action diamond — **▲ rise to surface · ▼ headlamp · ◀ boost · ▶ turbo**.
- Top-left **pause**, top-right **mute**.

**Game controller**

| Input | Action |
|-------|--------|
| Left stick / D-pad | Swim |
| A | Toggle headlamp |
| B | Turbo |
| X | Boost |
| Y | Rise to surface |
| Menu | Pause |
| L1 | Mute |

## 🌍 Languages

English · Spanish · French · German · Italian · Brazilian Portuguese · Russian · Polish · Dutch · Turkish · Hindi · Japanese · Korean · Simplified Chinese · Traditional Chinese · Arabic

All text lives in a single `Localizable.xcstrings` String Catalog. Latin-script languages keep the retro pixel font; other scripts (CJK, Cyrillic, Devanagari, Arabic) fall back to a glyph-complete system font so everything renders and shapes correctly.

## 🛠️ Built with

- **Swift** + **SpriteKit** — the whole game is a handful of `SKScene`s and nodes.
- **GameController** — MFi / Xbox / PlayStation controller support.
- **AVFoundation** — looping, depth-mixed generated ambience.
- **Core Haptics** — controller + device rumble for key moments.
- **String Catalogs** — 16-language localization.
- Procedural pixel textures and dithered depth gradients, no giant pre-baked art.

## 🚀 Build & run

1. Open `Abysm.xcodeproj` in Xcode.
2. Select the **Abysm** scheme.
3. Run on an iOS **17+** device or simulator (landscape).

The only dependency is the **RevenueCat** Swift package (`purchases-ios-spm`), which Xcode resolves automatically via Swift Package Manager on first open — no manual setup.

### Website

The static landing page in `web/` is hosted on Cloudflare Workers. With Wrangler authenticated, build and deploy it from the repository root:

```sh
cd web
npm run build
npx wrangler deploy
```

### Testing

```sh
bash scripts/test-ios.sh
```

Builds the Debug app once for a simulator it creates (and deletes afterwards), runs the unit tests, shuts the simulator down and confirms it is shut down, then runs the UI tests on a fresh boot from a cold launch, so the first UI test never races the unit-test host's shutdown. It fails if either suite fails or runs no tests, or if the simulator cannot be confirmed shut down between the suites, and never retries. Results (`UnitTests.xcresult`, `UITests.xcresult` and logs) go to `~/Library/Developer/Xcode/DerivedData/Abysm-simulator-tests/TestResults/`.

- **AbysmTests** (unit): the creature and landmark catalog, zone boundaries and water colour, the free dive vs. the 1,000 m gate, saving and Continue, the paywall's state machine, controls and the depth read-out, VoiceOver behaviour of hidden buttons, diver physics limits, and localization coverage.
- **AbysmUITests** (UI, on the real SpriteKit screens): the title menu, the sound setting across launches, starting a dive, swimming and rising, pause → resume → main menu → Continue, resuming a saved depth, and the "Unlock the Deep" gate (shown, restore checked, dismissed — never bought).

Test runs are offline: in Debug simulator builds launched by XCTest (or with `--ui-testing`), RevenueCat is never configured, so no network, account or purchase is involved. Release and device builds are unaffected. The **iOS tests** workflow runs both suites on GitHub's `xcode-27` runner for pull requests and pushes to `main` that touch the app, its tests or its project.

CodeQL analyzes the Swift app, the Python release tooling, the website and the workflows, and the release tooling's log redaction, release switches and release notes are fuzzed with Atheris (see [`fuzz/`](fuzz/README.md)).

### Releases

GitHub Actions builds, signs and uploads releases; Xcode Cloud was removed for ABYSM on 2026-10-14 and must not be re-created. A release tag is exactly `v` + the project's `MARKETING_VERSION` — for version 1.0.1:

```sh
git tag -a v1.0.1 -m "ABYSM 1.0.1"
git push origin v1.0.1
```

The tag runs the tests, then the **iOS Release** workflow, which uploads, updates the listing or submits for review only for the switches you turned on (all off by default), and finally creates the GitHub Release (notes from a matching `RELEASE_NOTES.md` section, otherwise generated). Any other `v*` tag fails without releasing anything. With a listing, What's New, screenshot or review switch on, create the version (e.g. 1.0.1) in App Store Connect before tagging: a read-only preflight checks it before anything is built. **Run workflow** on iOS Release only validates a signed build with App Store Connect. See [`store/README.md`](store/README.md) for the switches, secrets, listing metadata and screenshots.

## 🔗 Links & support

- **Website:** [abysm.apoorvdarshan.com](https://abysm.apoorvdarshan.com/)
- **App Store / rate ABYSM:** [apps.apple.com/app/abysm-dive-the-deep-sea/id6783505799](https://apps.apple.com/app/abysm-dive-the-deep-sea/id6783505799)
- **Privacy:** [abysm.apoorvdarshan.com/#privacy](https://abysm.apoorvdarshan.com/#privacy)
- **Terms:** [abysm.apoorvdarshan.com/#terms](https://abysm.apoorvdarshan.com/#terms)
- **Email support:** [ad13dtu@gmail.com](mailto:ad13dtu@gmail.com?subject=ABYSM%20Support)
- **Email Apoorv:** [apoorvdarshan@gmail.com](mailto:apoorvdarshan@gmail.com?subject=ABYSM%20Support)
- **X:** [@apoorvdarshan](https://x.com/apoorvdarshan)
- **Instagram:** [@apoorvgames](https://www.instagram.com/apoorvgames/)
- **Product Hunt:** [Upvote for ABYSM](https://www.producthunt.com/products/abysm)
- **TrustMRR:** [ABYSM on TrustMRR](https://trustmrr.com/startup/abysm-dive-the-deep-sea)

## 🔒 Privacy

ABYSM has no account, no login, no ads, and no advertising or cross-app tracking. Your current dive's depth and position, sound preference, and cached unlock state are stored locally on your device (via `UserDefaults`). The app follows the language selected in iOS and does not store a separate language preference. **RevenueCat** is contacted at launch and for purchase or restore operations; it receives an anonymous app-user ID, purchase and entitlement information, and basic technical information needed to provide and validate "Unlock the Deep." This information is not used for advertising or cross-app tracking. See [RevenueCat's privacy policy](https://www.revenuecat.com/privacy-policy/) for its processing details.

App Store privacy label: **Purchases** (Purchase History) — not linked to your identity, not used for tracking.

## 🤝 Contributing

Bug reports, ideas and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for how to build, test and submit changes, and the [Code of Conduct](CODE_OF_CONDUCT.md). Report security problems privately as described in [SECURITY.md](SECURITY.md).

## 📜 License

ABYSM is released under the [MIT License](LICENSE). The Press Start 2P font is under the SIL Open Font License 1.1; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

---

<p align="center"><sub>Made with ☕ and an unreasonable fondness for anglerfish.</sub></p>

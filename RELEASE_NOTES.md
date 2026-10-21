# ABYSM release notes

Reviewed notes for GitHub Releases. When a `## vX.Y.Z` heading matches the
pushed release tag exactly, the iOS Release workflow uses that section as the
GitHub Release notes; without one, GitHub generates notes from the commits.
Keep one section per tag: an empty or duplicated section fails the release
before anything is built. App Store "What's New" text is separate:
`store/metadata/ios/<locale>/whats_new.txt`.

Move the `Unreleased` items under a new `## vX.Y.Z` heading when you tag.

## Unreleased

## v1.1.1

- Bug fixes and improvements.
- The RevenueCat purchases SDK, which handles Unlock the Deep, is updated
  from 5.95.0 to 5.96.0.

## v1.1

- VoiceOver speaks every title-screen button, the in-game controls and the
  depth read-out in your language, with the right plural forms for meters.
- The Instagram button now opens @apoorvcodes, and the Product Hunt button
  opens the current ABYSM page.
- ABYSM is open source. The title screen links to its GitHub repository
  (star it there) and to forms for reporting a bug or requesting a feature;
  the bug form comes prefilled with your app and iOS version.
- VoiceOver no longer lists or activates buttons that are hidden: CONTINUE
  before there is a saved dive, and the pause menu and Unlock the Deep screen
  while they are closed.
- When you resume a dive, the headlamp button is there from the first frame.

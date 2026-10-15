# ABYSM release notes

Reviewed notes for GitHub Releases. When a `## vX.Y.Z` heading matches the
pushed release tag exactly, the iOS Release workflow uses that section as the
GitHub Release notes; without one, GitHub generates notes from the commits.
Keep one section per tag: an empty or duplicated section fails the release
before anything is built. App Store "What's New" text is separate:
`store/metadata/ios/<locale>/whats_new.txt`.

Move the `Unreleased` items under a new `## vX.Y.Z` heading when you tag.

## Unreleased

- ABYSM is open source. The title screen links to its GitHub repository
  (star it there) and to forms for reporting a bug or requesting a feature;
  the bug form comes prefilled with your app and iOS version.
- VoiceOver no longer lists or activates buttons that are hidden: CONTINUE
  before there is a saved dive, and the pause menu and Unlock the Deep screen
  while they are closed.

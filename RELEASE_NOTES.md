# ABYSM release notes

Reviewed notes for GitHub Releases. When a `## vX.Y.Z` heading matches the
pushed release tag exactly, the iOS Release workflow uses that section as the
GitHub Release notes; without one, GitHub generates notes from the commits.
Keep one section per tag: an empty or duplicated section fails the release
before anything is built. App Store "What's New" text is separate:
`store/metadata/ios/<locale>/whats_new.txt`.

Move the `Unreleased` items under a new `## vX.Y.Z` heading when you tag.

## Unreleased

- VoiceOver no longer lists or activates buttons that are hidden: CONTINUE
  before there is a saved dive, and the pause menu and Unlock the Deep screen
  while they are closed.

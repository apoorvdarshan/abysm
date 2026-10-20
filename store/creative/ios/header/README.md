# Product page header image

Empty: ABYSM has no product page header image yet, so `IOS_UPLOAD_CREATIVE_ASSETS`
has nothing to do for this slot.

To add one, commit a single PNG of exactly 3840×1646, without an alpha channel.
The release run uploads it to the App Store Connect Asset Library once, sends it
to App Review in a submission of its own and, once Apple approves it, places it
on the version's en-US product page ([store-release's ABYSM flow](https://github.com/apoorvdarshan/store-release/blob/v0.3.0/store_release/flows/abysm/asc_release.py)). To change
it later, commit the new image under a new file name. See
[`store/README.md`](../../../README.md#header-and-search-results-images).

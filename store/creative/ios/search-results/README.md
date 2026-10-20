# Search results image

Empty: ABYSM has no search results image yet, so `IOS_UPLOAD_CREATIVE_ASSETS` has
nothing to do for this slot.

To add one, commit a single PNG or JPEG in 3:2, from 1920×1280 to 3840×2560,
without an alpha channel. The release run uploads it to the App Store Connect
Asset Library once, sends it to App Review in a submission of its own and, once
Apple approves it, places it on the version's en-US product page
([store-release's ABYSM flow](https://github.com/apoorvdarshan/store-release/blob/v0.2.0/store_release/flows/abysm/asc_release.py)). To change it later, commit the new image under
a new file name. See
[`store/README.md`](../../../README.md#header-and-search-results-images).

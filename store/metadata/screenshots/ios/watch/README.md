# Apple Watch screenshots

Optional, and empty: ABYSM has no Apple Watch screenshots, so the Watch sets in
App Store Connect are left alone.

With `IOS_UPLOAD_SCREENSHOTS` on, PNGs here go to App Store Connect with the
iPhone and iPad sets, in file-name order, as RGB copies
(`scripts/store/asc_release.py`). Each frame's size picks its set: 416×496
`APP_WATCH_SERIES_10`, 422×514 or 410×502 `APP_WATCH_ULTRA`, 396×484
`APP_WATCH_SERIES_7`, 368×448 `APP_WATCH_SERIES_4`, 312×390 `APP_WATCH_SERIES_3`.
Any other size fails the run before anything is uploaded.

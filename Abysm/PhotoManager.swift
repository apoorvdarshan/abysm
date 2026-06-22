//
//  PhotoManager.swift
//  Abysm
//
//  Saves and lists dive photos (PNG files in the app's Documents/photos folder)
//  for the in-game camera + the Photos gallery on the title screen.
//

import UIKit

enum PhotoManager {

    private static var dir: URL {
        let base = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let d = base.appendingPathComponent("photos", isDirectory: true)
        try? FileManager.default.createDirectory(at: d, withIntermediateDirectories: true)
        return d
    }

    /// `stamp` is passed in (milliseconds) so callers control the timestamp.
    @discardableResult
    static func save(_ image: UIImage, stamp: Int) -> Bool {
        guard let data = image.pngData() else { return false }
        let url = dir.appendingPathComponent("abysm_\(stamp).png")
        return (try? data.write(to: url)) != nil
    }

    /// Saved photos, newest first (filenames embed a sortable timestamp).
    static func allURLs() -> [URL] {
        let urls = (try? FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil)) ?? []
        return urls.filter { $0.pathExtension == "png" }
            .sorted { $0.lastPathComponent > $1.lastPathComponent }
    }

    static func image(_ url: URL) -> UIImage? { UIImage(contentsOfFile: url.path) }

    static var count: Int { allURLs().count }
}

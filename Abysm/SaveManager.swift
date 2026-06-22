//
//  SaveManager.swift
//  Abysm
//
//  Tiny persistence for "Continue": remembers where the diver left off (depth +
//  horizontal position) so the title screen can resume the dive.
//

import CoreGraphics
import Foundation

enum SaveManager {
    private static let kHas = "abysm.hasSave"
    private static let kDepth = "abysm.depthMeters"
    private static let kX = "abysm.x"
    private static let kDeepest = "abysm.deepestMeters"

    static var hasSave: Bool { UserDefaults.standard.bool(forKey: kHas) }
    static var depthMeters: CGFloat { CGFloat(UserDefaults.standard.double(forKey: kDepth)) }
    static var x: CGFloat { CGFloat(UserDefaults.standard.double(forKey: kX)) }
    /// Deepest depth ever reached (kept across New Game, for a future record).
    static var deepestMeters: CGFloat { CGFloat(UserDefaults.standard.double(forKey: kDeepest)) }

    static func save(depthMeters: CGFloat, x: CGFloat) {
        let d = UserDefaults.standard
        d.set(true, forKey: kHas)
        d.set(Double(depthMeters), forKey: kDepth)
        d.set(Double(x), forKey: kX)
        if depthMeters > deepestMeters { d.set(Double(depthMeters), forKey: kDeepest) }
    }

    /// Forget the resume point (Start New Game), but keep the deepest record.
    static func clearResume() {
        UserDefaults.standard.set(false, forKey: kHas)
    }
}

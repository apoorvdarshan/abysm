//
//  Creatures.swift
//  Abysm
//
//  The sea-life dataset: real creatures placed at their real depths (data from
//  neal.fun/deep-sea + cross-check). Only creatures whose pixel-art sprite has
//  been generated are listed here; more are added zone-by-zone as art is made.
//

import CoreGraphics

struct CreatureDef {
    let key: String        // asset = "creature_<key>"
    let depthM: CGFloat    // real depth in metres
    let width: CGFloat     // on-screen width in points (rough real-scale)
    var still: Bool = false // true = anchored (e.g. coral), no horizontal patrol
}

enum Creatures {

    /// Generated so far — Sunlight Zone (0–200 m).
    static let all: [CreatureDef] = [
        CreatureDef(key: "salmon",    depthM: 3,  width: 95),
        CreatureDef(key: "manatee",   depthM: 3,  width: 200),
        CreatureDef(key: "coral",     depthM: 12, width: 110, still: true),
        CreatureDef(key: "polarbear", depthM: 23, width: 150),
        CreatureDef(key: "clownfish", depthM: 37, width: 60),
        CreatureDef(key: "bluetang",  depthM: 45, width: 66),
        CreatureDef(key: "seadragon", depthM: 53, width: 84)
    ]
}

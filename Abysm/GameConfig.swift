//
//  GameConfig.swift
//  Abysm
//
//  Central tuning values, world layout, color palette, and small math helpers.
//  ABYSM — Phase 1: The Surface.
//
//  Coordinate system (world / scene space, points):
//    • y = 0           → the ocean surface line
//    • y > 0           → sky (sun, light, air)
//    • y < 0           → underwater (deeper = more negative)
//    • x ∈ [-worldHalfWidth ... +worldHalfWidth]
//

import UIKit
import SpriteKit

enum GameConfig {

    // MARK: World layout (points)

    /// Half the explorable horizontal width. Total world width is 2× this.
    static let worldHalfWidth: CGFloat = 900
    /// Top of the sky region (how far above the surface the sky extends).
    static let skyTop: CGFloat = 1400
    /// Deepest reachable point for Phase 1 (a soft floor). ~52 m down.
    static let worldFloor: CGFloat = -4200

    /// Points per in-world meter, used for the depth read-out.
    static let pointsPerMeter: CGFloat = 80

    // MARK: Player (swimmer)

    /// Where the swimmer starts — just below the surface (~2 m deep).
    static let playerStartY: CGFloat = -170
    /// Swim acceleration (target acceleration in points/sec², applied as force).
    static let playerAccel: CGFloat = 560
    /// Hard speed cap so the swimmer always feels controlled and floaty.
    static let playerMaxSpeed: CGFloat = 360
    /// Water drag — high value gives the slow, weightless glide-to-stop feel.
    static let playerLinearDamping: CGFloat = 2.6
    /// Mass of the swimmer's physics body.
    static let playerMass: CGFloat = 0.5
    /// How close to the target before we consider it "arrived" and drift.
    static let arriveRadius: CGFloat = 16
    /// Minimum speed before the swimmer re-orients to face its heading.
    static let orientSpeedThreshold: CGFloat = 16

    // MARK: Camera

    /// Per-frame follow lerp factor (0 = frozen, 1 = instant snap).
    static let cameraSmoothing: CGFloat = 0.10

    // MARK: Environment

    /// How far below the surface the animated caustic light reaches.
    static let causticDepth: CGFloat = 1600
    /// Horizontal spacing of samples when rebuilding the wavy surface path.
    static let surfaceWaveSampleStep: CGFloat = 14

    // MARK: Z ordering (global, since the view uses ignoresSiblingOrder)

    enum Z {
        // World content
        static let sky: CGFloat        = -100
        static let water: CGFloat      = -95
        static let surface: CGFloat    = -88
        static let sunGlow: CGFloat    = -82
        static let godRays: CGFloat    = -78
        static let caustics: CGFloat   = -70
        static let bubbles: CGFloat    = -2
        static let player: CGFloat     = 0
        // Camera-attached screen overlays
        static let blueTint: CGFloat   = 40
        static let plankton: CGFloat   = 45
        static let darkness: CGFloat   = 60
        static let hud: CGFloat        = 100
    }
}

// MARK: - Color palette

enum Palette {

    /// Convenience: build a UIColor from 0–255 channels.
    static func rgb(_ r: CGFloat, _ g: CGFloat, _ b: CGFloat, _ a: CGFloat = 1) -> UIColor {
        UIColor(red: r / 255, green: g / 255, blue: b / 255, alpha: a)
    }

    /// Fallback fill shown before textures load — deep ocean dark.
    static let deepBackground = rgb(2, 8, 18)

    /// Water gradient, top (surface, index 0) → bottom (abyss). Bright & colorful
    /// up top, fading to near-black deep down.
    static let waterStops: [(UIColor, CGFloat)] = [
        (rgb(64, 224, 217), 0.00),   // bright turquoise at the surface
        (rgb(28, 184, 196), 0.10),   // teal
        (rgb(18, 132, 176), 0.28),   // shallow blue
        (rgb(12,  86, 134), 0.50),   // mid blue
        (rgb( 8,  48,  86), 0.72),   // deep blue
        (rgb( 3,  18,  40), 0.88),   // dark navy
        (rgb( 1,   7,  18), 1.00)    // near black
    ]

    /// Sky gradient, top (index 0) → horizon (y = 0). Sunny daytime blue.
    /// Kept clearly blue (not white) toward the horizon so the small visible
    /// sliver of sky still reads as "light blue sky".
    static let skyStops: [(UIColor, CGFloat)] = [
        (rgb( 56, 150, 226), 0.00),  // upper sky blue
        (rgb(104, 184, 238), 0.45),  // sky blue
        (rgb(152, 208, 240), 0.80),  // light blue near the horizon
        (rgb(184, 224, 244), 1.00)   // soft light-blue horizon at the waterline
    ]

    static let blueTint    = rgb(20, 90, 150)          // whole-screen underwater tint
    static let surfaceBand  = rgb(150, 240, 235)        // sunlit band just under the surface
    static let foam         = UIColor(white: 1.0, alpha: 0.85)
    static let sunCore      = rgb(255, 250, 224)
    static let sunGlow      = rgb(255, 238, 170)
    static let rayColor     = rgb(255, 247, 214)
}

// MARK: - Math helpers

/// GLSL-style smoothstep: 0 below edge0, 1 above edge1, smooth in between.
func smoothstep(_ edge0: CGFloat, _ edge1: CGFloat, _ x: CGFloat) -> CGFloat {
    guard edge1 != edge0 else { return x < edge0 ? 0 : 1 }
    let t = max(0, min(1, (x - edge0) / (edge1 - edge0)))
    return t * t * (3 - 2 * t)
}

func clamp(_ value: CGFloat, _ lower: CGFloat, _ upper: CGFloat) -> CGFloat {
    min(max(value, lower), upper)
}

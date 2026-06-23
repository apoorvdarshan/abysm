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

    /// Points per in-world meter. Tuned so the full descent is a journey of
    /// minutes, not an hour (the real 10,935 m would be ~875k pt at 80 pt/m).
    static let pointsPerMeter: CGFloat = 12
    /// The deepest point of any ocean — the Challenger Deep (Mariana Trench).
    static let maxDepthMeters: CGFloat = 10935
    /// World floor in points (the trench floor).
    static let worldFloor: CGFloat = -maxDepthMeters * pointsPerMeter

    /// Size of one "art pixel" in points — the global pixel scale for the
    /// whole pixel-art look (dithered gradients, caustics grid, etc.).
    static let pixel: CGFloat = 6

    // MARK: Player (swimmer)

    /// Where the swimmer starts — just below the surface (~3 m). Kept shallow
    /// so the low sun & surface frame nicely in landscape's short height.
    static let playerStartY: CGFloat = -36
    /// Swim acceleration (target acceleration in points/sec², applied as force).
    static let playerAccel: CGFloat = 560
    /// Hard speed cap so the swimmer always feels controlled and floaty.
    static let playerMaxSpeed: CGFloat = 360
    /// Water drag — high value gives the slow, weightless glide-to-stop feel.
    static let playerLinearDamping: CGFloat = 2.6
    /// Mass of the swimmer's physics body.
    static let playerMass: CGFloat = 0.5
    /// Minimum speed before the swimmer re-orients to face its heading.
    static let orientSpeedThreshold: CGFloat = 16
    /// Gravity (points/sec²) applied when the diver breaches above the surface,
    /// arcing it back down like a leaping dolphin.
    static let breachGravity: CGFloat = 1100
    /// Low drag while airborne so the breach keeps its momentum.
    static let airDamping: CGFloat = 0.2
    /// Cap on upward speed once airborne, so breaches stay a modest hop (not a
    /// rocket). Arc height ≈ speed² / (2·breachGravity).
    static let maxBreachUpSpeed: CGFloat = 560

    // MARK: Device scaling

    /// iPad's larger screen reveals more world, so creatures and their labels
    /// read small there — scale them up. iPhone is unchanged (1.0).
    static var isPad: Bool { UIDevice.current.userInterfaceIdiom == .pad }
    /// Multiplier for creature sprite size on iPad.
    static var creatureScale: CGFloat { isPad ? 1.35 : 1.0 }
    /// Multiplier for creature name-tag / fact-bubble text + plates on iPad.
    static var labelScale: CGFloat { isPad ? 1.4 : 1.0 }

    // MARK: Camera

    /// Per-frame follow lerp factor (0 = frozen, 1 = instant snap).
    static let cameraSmoothing: CGFloat = 0.10

    // MARK: Environment

    /// How far below the surface the animated caustic light reaches.
    static let causticDepth: CGFloat = 1600
    /// Horizontal spacing of samples when rebuilding the wavy surface path.
    static let surfaceWaveSampleStep: CGFloat = 14

    // MARK: Ocean depth zones (real metre boundaries)

    struct Zone { let key: String; let name: String; let topMeters: CGFloat; let blurb: String }
    static let zones: [Zone] = [
        Zone(key: "sunlight", name: "SUNLIGHT ZONE", topMeters: 0,    blurb: "Warm, sunlit waters where most ocean life thrives."),
        Zone(key: "twilight", name: "TWILIGHT ZONE", topMeters: 200,  blurb: "Fading blue gloom — cold, dim, lit by living glow."),
        Zone(key: "midnight", name: "MIDNIGHT ZONE", topMeters: 1000, blurb: "Eternal black, near-freezing, crushing dark."),
        Zone(key: "abyss",    name: "THE ABYSS",     topMeters: 4000, blurb: "Frigid, pitch-black plains under immense pressure."),
        Zone(key: "hadal",    name: "HADAL ZONE",    topMeters: 6000, blurb: "Deepest trenches: crushing, lightless, barely alive.")
    ]

    /// Water background color by depth (metres): bright surface → black trench.
    static let depthColorStops: [(CGFloat, UIColor)] = [
        (0,     Palette.rgb(104, 198, 196)),
        (60,    Palette.rgb(64, 162, 182)),
        (200,   Palette.rgb(34, 104, 150)),
        (700,   Palette.rgb(20, 60, 116)),
        (1500,  Palette.rgb(13, 38, 84)),
        (4000,  Palette.rgb(8, 22, 54)),
        (6500,  Palette.rgb(5, 12, 32)),
        (10935, Palette.rgb(2, 5, 14))
    ]

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
        static let vignette: CGFloat   = 70
        static let hud: CGFloat        = 100
        static let joystick: CGFloat   = 110
        static let intro: CGFloat      = 120
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
    // Disciplined depth ramp: saturation peaks mid-ramp (never max-sat+max-
    // bright = "washed"), hue shifts cooler and value drops as it deepens.
    static let waterStops: [(UIColor, CGFloat)] = [
        (rgb(94, 196, 194), 0.00),   // surface: soft cyan-teal
        (rgb(58, 160, 184), 0.12),   // teal
        (rgb(40, 118, 162), 0.28),   // shallow blue
        (rgb(28,  84, 138), 0.46),   // saturated mid-blue
        (rgb(20,  54, 104), 0.66),   // deep indigo
        (rgb(13,  32,  70), 0.84),   // navy
        (rgb( 7,  16,  38), 1.00)    // near-black blue-violet
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
    static let tintShallow = rgb(42, 150, 168)         // depth grade near the surface (teal)
    static let tintDeep    = rgb(8, 26, 78)            // depth grade in the deep (indigo)
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

/// Linearly interpolate between two colors in RGB.
func lerpColor(_ a: UIColor, _ b: UIColor, _ t: CGFloat) -> UIColor {
    var ar: CGFloat = 0, ag: CGFloat = 0, ab: CGFloat = 0, aa: CGFloat = 0
    var br: CGFloat = 0, bg: CGFloat = 0, bb: CGFloat = 0, ba: CGFloat = 0
    a.getRed(&ar, green: &ag, blue: &ab, alpha: &aa)
    b.getRed(&br, green: &bg, blue: &bb, alpha: &ba)
    let s = max(0, min(1, t))
    return UIColor(red: ar + (br - ar) * s, green: ag + (bg - ag) * s,
                   blue: ab + (bb - ab) * s, alpha: aa + (ba - aa) * s)
}

/// Water background color at a given depth in metres (lerp through the ramp).
func depthColor(_ m: CGFloat) -> UIColor {
    let stops = GameConfig.depthColorStops
    if m <= stops.first!.0 { return stops.first!.1 }
    if m >= stops.last!.0 { return stops.last!.1 }
    for i in 1..<stops.count where m <= stops[i].0 {
        let a = stops[i - 1], b = stops[i]
        return lerpColor(a.1, b.1, (m - a.0) / (b.0 - a.0))
    }
    return stops.last!.1
}

/// Localized name of the ocean zone at a given depth in metres.
func zoneName(_ m: CGFloat) -> String {
    var z = GameConfig.zones.first!
    for cand in GameConfig.zones where m >= cand.topMeters { z = cand }
    return L("zone.\(z.key).name", z.name)
}

/// Localized one-line blurb for a zone, for the zone-entry banner. Accepts the
/// zone's English *or* localized display name.
func zoneBlurb(_ name: String) -> String {
    guard let z = GameConfig.zones.first(where: {
        $0.name == name || L("zone.\($0.key).name", $0.name) == name
    }) else { return "" }
    return L("zone.\(z.key).blurb", z.blurb)
}

/// Interpolate an angle toward a target along the shortest path (handles wrap).
func lerpAngle(_ from: CGFloat, _ to: CGFloat, _ t: CGFloat) -> CGFloat {
    var diff = (to - from).truncatingRemainder(dividingBy: 2 * .pi)
    if diff > .pi { diff -= 2 * .pi }
    if diff < -.pi { diff += 2 * .pi }
    return from + diff * t
}

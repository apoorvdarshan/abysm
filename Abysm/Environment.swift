//
//  Environment.swift
//  Abysm
//
//  Builds the static & shader-driven backdrop of the surface scene: the sky,
//  the water column gradient, the sun with its glow, animated god rays, and
//  the caustic light layer. Each factory returns a ready-to-add node with its
//  zPosition already set.
//

import SpriteKit

enum Environment {

    /// Generous horizontal overhang so the world's edges are never visible
    /// past the camera clamp.
    private static var spanWidth: CGFloat { GameConfig.worldHalfWidth * 2 + 400 }

    /// Where the sun sits — low and to one side so it's framed in the top
    /// corner of the starting view. Landscape has little vertical room, so the
    /// sun rides near the waterline (a low, bright morning sun).
    static var sunPosition: CGPoint {
        CGPoint(x: GameConfig.worldHalfWidth * 0.30, y: 95)
    }

    // MARK: Sky

    static func makeSky() -> SKSpriteNode {
        let height = GameConfig.skyTop + 400
        let texture = TextureFactory.pixelGradient(size: CGSize(width: spanWidth, height: height),
                                                   pixel: GameConfig.pixel, stops: Palette.skyStops)
        let sky = SKSpriteNode(texture: texture, size: CGSize(width: spanWidth, height: height))
        sky.anchorPoint = CGPoint(x: 0.5, y: 0)   // bottom edge sits on the surface (y = 0)
        sky.position = .zero
        sky.zPosition = GameConfig.Z.sky
        return sky
    }

    // MARK: Tide line (sky ↔ sea separator)

    /// A clean pixel "tide" — a foam wave on the surface that softly separates
    /// sky and sea. Its shape animates (drifting, morphing crests) and it gently
    /// rises and falls. Fixed at the surface; only the wave shape moves.
    static func makeTideLine() -> SKSpriteNode {
        let px = GameConfig.pixel
        let texels = max(1, Int(spanWidth / px))
        let frameCount = 16
        let frames = (0..<frameCount).map { f -> SKTexture in
            TextureFactory.tideStrip(texelsWide: texels, phase: Double(f) / Double(frameCount) * 2 * .pi)
        }
        let line = SKSpriteNode(texture: frames[0], size: CGSize(width: spanWidth, height: 8 * px))
        line.anchorPoint = CGPoint(x: 0.5, y: 0.5)
        line.position = .zero
        line.zPosition = GameConfig.Z.surface
        line.run(.repeatForever(.animate(with: frames, timePerFrame: 0.11, resize: false, restore: false)))
        let bob = SKAction.sequence([.moveBy(x: 0, y: 4, duration: 2.3),
                                     .moveBy(x: 0, y: -4, duration: 2.3)])
        bob.timingMode = .easeInEaseOut
        line.run(.repeatForever(bob))
        return line
    }

    // MARK: Day / night

    /// A dark overlay over the sky region; its opacity is driven by "nightness".
    static func makeNightOverlay() -> SKSpriteNode {
        let h = GameConfig.skyTop + 400
        let o = SKSpriteNode(color: Palette.rgb(6, 14, 34), size: CGSize(width: spanWidth, height: h))
        o.anchorPoint = CGPoint(x: 0.5, y: 0)   // bottom on the surface, covering the sky
        o.position = .zero
        o.zPosition = GameConfig.Z.sunGlow - 2
        o.alpha = 0
        return o
    }

    /// A field of twinkling stars in the sky (node alpha = nightness).
    static func makeStars() -> SKNode {
        let node = SKNode()
        node.zPosition = GameConfig.Z.sunGlow - 1
        node.alpha = 0
        let tex = TextureFactory.pixelDot(2, color: .white)
        for _ in 0..<70 {
            let s = SKSpriteNode(texture: tex)
            let sz = [4, 4, 6, 6, 8].randomElement()!
            s.size = CGSize(width: CGFloat(sz), height: CGFloat(sz))
            s.position = CGPoint(x: CGFloat.random(in: -spanWidth / 2...spanWidth / 2),
                                 y: CGFloat.random(in: 40...440))
            s.alpha = CGFloat.random(in: 0.5...1.0)
            let twinkle = SKAction.sequence([.fadeAlpha(to: 0.3, duration: .random(in: 0.8...1.8)),
                                             .fadeAlpha(to: 1.0, duration: .random(in: 0.8...1.8))])
            s.run(.repeatForever(twinkle))
            node.addChild(s)
        }
        return node
    }

    /// A pale moon that fades in at night (positioned like the sun).
    static func makeMoon() -> SKSpriteNode {
        let r = 9
        let moon = SKSpriteNode(texture: TextureFactory.pixelCircle(radius: r, color: Palette.rgb(226, 230, 240)))
        let d = CGFloat(r * 2 + 2) * GameConfig.pixel
        moon.size = CGSize(width: d, height: d)
        moon.zPosition = GameConfig.Z.sunGlow + 1
        moon.alpha = 0
        return moon
    }

    // MARK: Trench floor

    /// The sediment seabed at the very bottom of the trench (Challenger Deep).
    static func makeTrenchFloor() -> SKSpriteNode {
        let px = GameConfig.pixel
        let texels = max(1, Int(spanWidth / px))
        let tex = TextureFactory.sedimentStrip(texelsWide: texels)
        let floor = SKSpriteNode(texture: tex, size: CGSize(width: spanWidth, height: 18 * px))
        floor.anchorPoint = CGPoint(x: 0.5, y: 1)             // top edge = floor line
        floor.position = CGPoint(x: 0, y: GameConfig.worldFloor + 20)
        floor.zPosition = GameConfig.Z.player - 25
        return floor
    }

    // MARK: Underwater sunlight glow

    /// A soft, wide pool of sunlight glowing through the upper water — diffuse,
    /// centered on the diver's column (not pinned to the sun).
    static func makeUnderwaterGlow() -> SKSpriteNode {
        let tex = TextureFactory.radialGlow(diameter: 512,
                                            inner: Palette.rgb(222, 250, 244, 0.5),
                                            outer: Palette.rgb(180, 236, 228, 0))
        let glow = SKSpriteNode(texture: tex)
        glow.size = CGSize(width: 1500, height: 620)
        glow.position = CGPoint(x: 0, y: -210)   // upper water, below the surface
        glow.zPosition = GameConfig.Z.water
        glow.blendMode = .add
        glow.alpha = 0.45
        return glow
    }

    // MARK: Water column

    static func makeWater() -> SKSpriteNode {
        let height = -GameConfig.worldFloor + 800
        let texture = TextureFactory.pixelGradient(size: CGSize(width: spanWidth, height: height),
                                                   pixel: GameConfig.pixel, stops: Palette.waterStops)
        let water = SKSpriteNode(texture: texture, size: CGSize(width: spanWidth, height: height))
        water.anchorPoint = CGPoint(x: 0.5, y: 1)  // top edge sits on the surface (y = 0)
        water.position = .zero
        water.zPosition = GameConfig.Z.water
        return water
    }

    // MARK: Sun

    static func makeSun() -> SKNode {
        let node = SKNode()
        node.position = sunPosition
        node.zPosition = GameConfig.Z.sunGlow

        // Hard-edged pixel-art sun disc (no soft glow).
        let r = 11
        let sun = SKSpriteNode(texture: TextureFactory.pixelSun(radius: r))
        let d = CGFloat(r * 2 + 2) * GameConfig.pixel
        sun.size = CGSize(width: d, height: d)
        node.addChild(sun)
        return node
    }

    // MARK: God rays

    static func makeGodRays() -> SKNode {
        let node = SKNode()
        node.position = sunPosition
        node.zPosition = GameConfig.Z.godRays

        let beamTexture = TextureFactory.softBeam(size: CGSize(width: 256, height: 1024))
        // Reach into the upper water (where shafts are visible) without painting
        // a huge additive sprite whose lower half is already transparent.
        let beamHeight = sunPosition.y + 1150

        // A fan of shafts spreading from the sun down into the water.
        let configs: [(width: CGFloat, angle: CGFloat, baseAlpha: CGFloat, period: TimeInterval)] = [
            (260, -0.30, 0.11, 7.0),
            (200, -0.16, 0.14, 5.5),
            (310, -0.02, 0.16, 8.5),
            (210,  0.14, 0.13, 6.0),
            (155,  0.28, 0.10, 9.0),
            (120,  0.42, 0.07, 5.0)
        ]

        for (i, c) in configs.enumerated() {
            let beam = SKSpriteNode(texture: beamTexture, size: CGSize(width: c.width, height: beamHeight))
            beam.anchorPoint = CGPoint(x: 0.5, y: 1)   // hangs downward from the sun
            beam.zRotation = c.angle
            beam.blendMode = .add
            beam.color = Palette.rayColor
            beam.colorBlendFactor = 0.4
            beam.alpha = c.baseAlpha

            // Each shaft breathes on its own phase so the light feels alive.
            let dim = SKAction.fadeAlpha(to: c.baseAlpha * 0.45, duration: c.period)
            dim.timingMode = .easeInEaseOut
            let bright = SKAction.fadeAlpha(to: c.baseAlpha, duration: c.period)
            bright.timingMode = .easeInEaseOut
            let shimmer = SKAction.sequence([dim, bright])
            let startDelay = SKAction.wait(forDuration: Double(i) * 0.6)
            beam.run(.sequence([startDelay, .repeatForever(shimmer)]))

            // A faint sway in angle.
            let sway = SKAction.sequence([
                SKAction.rotate(byAngle: 0.03, duration: c.period * 0.8),
                SKAction.rotate(byAngle: -0.03, duration: c.period * 0.8)
            ])
            sway.timingMode = .easeInEaseOut
            beam.run(.repeatForever(sway))

            node.addChild(beam)
        }
        return node
    }

    // MARK: Caustics

    static func makeCaustics() -> SKSpriteNode {
        let size = CGSize(width: spanWidth, height: GameConfig.causticDepth)
        let node = SKSpriteNode(texture: TextureFactory.white(), size: size)
        node.anchorPoint = CGPoint(x: 0.5, y: 1)   // top at the surface, extends down
        node.position = .zero
        node.zPosition = GameConfig.Z.caustics
        node.colorBlendFactor = 0
        node.blendMode = .add
        node.shader = Shaders.caustics(cols: Float(size.width / GameConfig.pixel),
                                       rows: Float(size.height / GameConfig.pixel))
        return node
    }
}

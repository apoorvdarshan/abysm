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

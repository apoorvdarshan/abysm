//
//  Particles.swift
//  Abysm
//
//  Code-built emitters (no .sks files): the bubble trail that follows the
//  swimmer and the ambient plankton drifting through the water.
//

import SpriteKit

enum Particles {

    /// Bubbles that rise from the swimmer. Birth rate is driven at runtime by
    /// the player's speed (more bubbles while actively swimming).
    static func bubbleTrail() -> SKEmitterNode {
        let e = SKEmitterNode()
        e.particleTexture = TextureFactory.pixelDot(2, color: UIColor(white: 1, alpha: 0.95))
        e.particleBirthRate = 3
        e.numParticlesToEmit = 0            // endless
        e.particleLifetime = 2.6
        e.particleLifetimeRange = 1.0

        e.emissionAngle = .pi / 2           // upward
        e.emissionAngleRange = .pi / 5
        e.particleSpeed = 34
        e.particleSpeedRange = 18
        e.yAcceleration = 26                // buoyancy — bubbles accelerate up

        e.particlePositionRange = CGVector(dx: 20, dy: 12)

        e.particleScale = 3                 // ~1 art-pixel bubbles
        e.particleScaleRange = 2

        e.particleAlpha = 0.7
        e.particleAlphaRange = 0.2
        e.particleAlphaSpeed = -0.22

        e.particleColorBlendFactor = 0
        e.particleBlendMode = .add
        return e
    }

    /// Slow, faint motes drifting in every direction — plankton / suspended
    /// particles. Spread across the viewport via `particlePositionRange`.
    static func plankton() -> SKEmitterNode {
        let e = SKEmitterNode()
        e.particleTexture = TextureFactory.pixelDot(2, color: Palette.rgb(200, 245, 240))
        e.particleBirthRate = 8
        e.numParticlesToEmit = 0
        e.particleLifetime = 12
        e.particleLifetimeRange = 5

        e.emissionAngle = 0
        e.emissionAngleRange = .pi * 2      // any direction
        e.particleSpeed = 7
        e.particleSpeedRange = 5

        e.particleScale = 2.5
        e.particleScaleRange = 1.5

        e.particleAlpha = 0.35
        e.particleAlphaRange = 0.15

        e.particleColorBlendFactor = 0
        e.particleBlendMode = .add

        // Sensible default; the scene resizes this to the live viewport.
        e.particlePositionRange = CGVector(dx: 600, dy: 900)
        return e
    }

    /// A few big, very soft, out-of-focus motes drifting near the "lens" —
    /// foreground depth-of-field that adds dimensionality without clutter.
    static func bokeh() -> SKEmitterNode {
        let e = SKEmitterNode()
        e.particleTexture = TextureFactory.speck(diameter: 80)
        e.particleBirthRate = 0.6
        e.numParticlesToEmit = 0
        e.particleLifetime = 18
        e.particleLifetimeRange = 6

        e.emissionAngle = .pi               // drift slowly with the "current"
        e.emissionAngleRange = .pi / 2
        e.particleSpeed = 13
        e.particleSpeedRange = 8

        e.particleScale = 1.0
        e.particleScaleRange = 0.8
        e.particleScaleSpeed = 0.05

        e.particleAlpha = 0.09
        e.particleAlphaRange = 0.05

        e.particleColorBlendFactor = 0
        e.particleBlendMode = .add
        e.particlePositionRange = CGVector(dx: 800, dy: 500)
        return e
    }

    /// Larger, slower "marine snow" drifting gently downward — adds a sense of
    /// suspended depth behind the closer plankton.
    static func marineSnow() -> SKEmitterNode {
        let e = SKEmitterNode()
        e.particleTexture = TextureFactory.pixelDot(2, color: UIColor(white: 1, alpha: 1))
        e.particleBirthRate = 3
        e.numParticlesToEmit = 0
        e.particleLifetime = 18
        e.particleLifetimeRange = 7

        e.emissionAngle = -.pi / 2          // drift downward like snow
        e.emissionAngleRange = .pi / 2.5
        e.particleSpeed = 9
        e.particleSpeedRange = 6
        e.yAcceleration = -4

        e.particleScale = 3
        e.particleScaleRange = 1.5

        e.particleAlpha = 0.4
        e.particleAlphaRange = 0.15

        e.particleColorBlendFactor = 0
        e.particleBlendMode = .add
        e.particlePositionRange = CGVector(dx: 700, dy: 520)
        return e
    }
}

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
        e.particleTexture = TextureFactory.bubble(diameter: 24)
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

        e.particleScale = 0.5
        e.particleScaleRange = 0.4
        e.particleScaleSpeed = -0.06

        e.particleAlpha = 0.55
        e.particleAlphaRange = 0.2
        e.particleAlphaSpeed = -0.18

        e.particleColorBlendFactor = 0
        e.particleBlendMode = .add
        return e
    }

    /// Slow, faint motes drifting in every direction — plankton / suspended
    /// particles. Spread across the viewport via `particlePositionRange`.
    static func plankton() -> SKEmitterNode {
        let e = SKEmitterNode()
        e.particleTexture = TextureFactory.speck(diameter: 16)
        e.particleBirthRate = 8
        e.numParticlesToEmit = 0
        e.particleLifetime = 12
        e.particleLifetimeRange = 5

        e.emissionAngle = 0
        e.emissionAngleRange = .pi * 2      // any direction
        e.particleSpeed = 7
        e.particleSpeedRange = 5

        e.particleScale = 0.18
        e.particleScaleRange = 0.12

        e.particleAlpha = 0.16
        e.particleAlphaRange = 0.10

        e.particleColorBlendFactor = 0
        e.particleBlendMode = .add

        // Sensible default; the scene resizes this to the live viewport.
        e.particlePositionRange = CGVector(dx: 600, dy: 900)
        return e
    }

    /// Larger, slower "marine snow" drifting gently downward — adds a sense of
    /// suspended depth behind the closer plankton.
    static func marineSnow() -> SKEmitterNode {
        let e = SKEmitterNode()
        e.particleTexture = TextureFactory.speck(diameter: 24)
        e.particleBirthRate = 3
        e.numParticlesToEmit = 0
        e.particleLifetime = 18
        e.particleLifetimeRange = 7

        e.emissionAngle = -.pi / 2          // drift downward like snow
        e.emissionAngleRange = .pi / 2.5
        e.particleSpeed = 9
        e.particleSpeedRange = 6
        e.yAcceleration = -4

        e.particleScale = 0.11
        e.particleScaleRange = 0.09

        e.particleAlpha = 0.28
        e.particleAlphaRange = 0.14

        e.particleColorBlendFactor = 0
        e.particleBlendMode = .add
        e.particlePositionRange = CGVector(dx: 700, dy: 520)
        return e
    }
}

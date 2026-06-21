//
//  CreatureField.swift
//  Abysm
//
//  Places each creature in the world at its real depth, drifting on a slow
//  horizontal patrol with a gentle bob. Ambient sea life you pass on the way
//  down. (Only creatures with generated sprites appear — see Creatures.swift.)
//

import SpriteKit

final class CreatureField: SKNode {

    func populate() {
        for c in Creatures.all {
            let tex = SKTexture(imageNamed: "creature_\(c.key)")
            tex.filteringMode = .nearest
            let aspect = tex.size().width > 0 ? tex.size().height / tex.size().width : 1
            let sprite = SKSpriteNode(texture: tex)
            sprite.size = CGSize(width: c.width, height: c.width * aspect)
            sprite.zPosition = GameConfig.Z.player - 1   // just behind the diver

            let margin = c.width
            let x = CGFloat.random(in: (-GameConfig.worldHalfWidth + margin)...(GameConfig.worldHalfWidth - margin))
            sprite.position = CGPoint(x: x, y: -c.depthM * GameConfig.pointsPerMeter)
            addChild(sprite)
            animate(sprite, c)
        }
    }

    private func animate(_ sprite: SKSpriteNode, _ c: CreatureDef) {
        // Gentle vertical bob for everything (alive feel).
        let amt = CGFloat.random(in: 4...8)
        let bob = SKAction.sequence([.moveBy(x: 0, y: amt, duration: 1.4),
                                     .moveBy(x: 0, y: -amt, duration: 1.4)])
        bob.timingMode = .easeInEaseOut
        sprite.run(.repeatForever(bob))

        if c.still {
            let sway = SKAction.sequence([.rotate(byAngle: 0.05, duration: 2.2),
                                          .rotate(byAngle: -0.05, duration: 2.2)])
            sway.timingMode = .easeInEaseOut
            sprite.run(.repeatForever(sway))
            return
        }

        // Slow horizontal patrol, flipping to face the swim direction.
        let range = CGFloat.random(in: 140...340)
        let speed = CGFloat.random(in: 16...36)
        let dur = TimeInterval(range / speed)
        sprite.xScale = -1   // start swimming left (sprite faces +x by default)
        let goLeft = SKAction.moveBy(x: -range, y: 0, duration: dur)
        let goRight = SKAction.moveBy(x: range, y: 0, duration: dur)
        goLeft.timingMode = .easeInEaseOut
        goRight.timingMode = .easeInEaseOut
        let faceRight = SKAction.run { sprite.xScale = 1 }
        let faceLeft = SKAction.run { sprite.xScale = -1 }
        sprite.run(.repeatForever(.sequence([goLeft, faceRight, goRight, faceLeft])))
    }
}

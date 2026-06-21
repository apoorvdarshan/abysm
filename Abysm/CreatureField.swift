//
//  CreatureField.swift
//  Abysm
//
//  Places each creature in the world at its real depth and brings it to life:
//  a slow horizontal patrol (facing the swim direction) + gentle bob on a
//  container, plus a procedural "swim" wiggle (tail-wag rotation + body-length
//  pulse) on the sprite itself, so every creature moves without needing per-
//  creature animation frames.
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

            // Container carries position / patrol / facing; sprite carries the
            // swim wiggle — separate nodes so the two never fight over a transform.
            let node = SKNode()
            node.zPosition = GameConfig.Z.player - 1
            let margin = c.width
            let x = CGFloat.random(in: (-GameConfig.worldHalfWidth + margin)...(GameConfig.worldHalfWidth - margin))
            node.position = CGPoint(x: x, y: -c.depthM * GameConfig.pointsPerMeter)
            node.addChild(sprite)
            addChild(node)

            animate(container: node, sprite: sprite, c)
        }
    }

    private func animate(container: SKNode, sprite: SKSpriteNode, _ c: CreatureDef) {
        let phase = TimeInterval.random(in: 0...1)

        // Gentle vertical bob (alive feel) — on the container.
        let amt = CGFloat.random(in: 4...9)
        let bob = SKAction.sequence([.moveBy(x: 0, y: amt, duration: 1.4),
                                     .moveBy(x: 0, y: -amt, duration: 1.4)])
        bob.timingMode = .easeInEaseOut
        container.run(.sequence([.wait(forDuration: phase), .repeatForever(bob)]))

        if c.still {
            // Anchored things (coral) just sway.
            let sway = SKAction.sequence([.rotate(toAngle: 0.05, duration: 2.2),
                                          .rotate(toAngle: -0.05, duration: 2.2)])
            sway.timingMode = .easeInEaseOut
            sprite.run(.repeatForever(sway))
            return
        }

        // Procedural swim wiggle on the sprite: tail-wag rotation + length pulse.
        let wag = CGFloat.random(in: 0.05...0.09)
        let beat = TimeInterval.random(in: 0.4...0.7)
        let wagAnim = SKAction.sequence([.rotate(toAngle: wag, duration: beat),
                                         .rotate(toAngle: -wag, duration: beat)])
        wagAnim.timingMode = .easeInEaseOut
        let pulse = SKAction.sequence([.scaleX(to: 0.94, duration: beat),
                                       .scaleX(to: 1.0, duration: beat)])
        pulse.timingMode = .easeInEaseOut
        sprite.run(.sequence([.wait(forDuration: phase), .repeatForever(wagAnim)]))
        sprite.run(.sequence([.wait(forDuration: phase * 0.5), .repeatForever(pulse)]))

        // Slow horizontal patrol, flipping the container to face the direction.
        let range = CGFloat.random(in: 140...340)
        let speed = CGFloat.random(in: 16...36)
        let dur = TimeInterval(range / speed)
        container.xScale = -1   // start swimming left (sprite faces +x by default)
        let goLeft = SKAction.moveBy(x: -range, y: 0, duration: dur)
        let goRight = SKAction.moveBy(x: range, y: 0, duration: dur)
        goLeft.timingMode = .easeInEaseOut
        goRight.timingMode = .easeInEaseOut
        let faceRight = SKAction.run { container.xScale = 1 }
        let faceLeft = SKAction.run { container.xScale = -1 }
        container.run(.repeatForever(.sequence([goLeft, faceRight, goRight, faceLeft])))
    }
}

//
//  CreatureField.swift
//  Abysm
//
//  Places each creature at its real depth and brings it to life. Node tree:
//    wrapper (position: patrol + bob; never flips — holds the name tag)
//      └ container (xScale: faces swim direction)
//          └ sprite (procedural swim wiggle: tail-wag + length pulse)
//      └ nameTag (always-readable label, like neal.fun's creature labels)
//  Also answers `nearest(to:within:)` so the scene can show an info card.
//

import SpriteKit

final class CreatureField: SKNode {

    private(set) var placed: [(def: CreatureDef, node: SKNode)] = []

    func populate() {
        for c in Creatures.all {
            let tex = SKTexture(imageNamed: "creature_\(c.key)")
            tex.filteringMode = .nearest
            let aspect = tex.size().width > 0 ? tex.size().height / tex.size().width : 1
            let sprite = SKSpriteNode(texture: tex)
            sprite.size = CGSize(width: c.width, height: c.width * aspect)

            let container = SKNode()
            container.addChild(sprite)

            let wrapper = SKNode()
            wrapper.zPosition = GameConfig.Z.player - 1
            let margin = c.width
            let x = CGFloat.random(in: (-GameConfig.worldHalfWidth + margin)...(GameConfig.worldHalfWidth - margin))
            wrapper.position = CGPoint(x: x, y: -c.depthM * GameConfig.pointsPerMeter)
            wrapper.addChild(container)

            let tag = makeNameTag(c.name)
            tag.position = CGPoint(x: 0, y: -sprite.size.height / 2 - 16)
            wrapper.addChild(tag)

            addChild(wrapper)
            placed.append((c, wrapper))
            animate(wrapper: wrapper, container: container, sprite: sprite, c)
        }
    }

    /// The creature closest to `point` within `d`, or nil.
    func nearest(to point: CGPoint, within d: CGFloat) -> CreatureDef? {
        var best: CreatureDef?
        var bestDist = d
        for (def, node) in placed {
            let dist = hypot(node.position.x - point.x, node.position.y - point.y)
            if dist < bestDist { bestDist = dist; best = def }
        }
        return best
    }

    // MARK: Name tag (readable over any background)

    private func makeNameTag(_ name: String) -> SKNode {
        let node = SKNode()
        let label = SKLabelNode(fontNamed: "PressStart2P-Regular")
        label.text = name.uppercased()
        label.fontSize = 7
        label.fontColor = .white
        label.verticalAlignmentMode = .center
        label.horizontalAlignmentMode = .center
        label.zPosition = 1

        let plate = SKSpriteNode(color: Palette.rgb(8, 20, 44),
                                 size: CGSize(width: label.frame.width + 14, height: 18))
        plate.alpha = 0.5
        plate.zPosition = 0
        node.addChild(plate)
        node.addChild(label)
        node.alpha = 0.82
        return node
    }

    // MARK: Motion

    private func animate(wrapper: SKNode, container: SKNode, sprite: SKSpriteNode, _ c: CreatureDef) {
        let phase = TimeInterval.random(in: 0...1)

        let amt = CGFloat.random(in: 4...9)
        let bob = SKAction.sequence([.moveBy(x: 0, y: amt, duration: 1.4),
                                     .moveBy(x: 0, y: -amt, duration: 1.4)])
        bob.timingMode = .easeInEaseOut
        wrapper.run(.sequence([.wait(forDuration: phase), .repeatForever(bob)]))

        if c.still {
            let sway = SKAction.sequence([.rotate(toAngle: 0.05, duration: 2.2),
                                          .rotate(toAngle: -0.05, duration: 2.2)])
            sway.timingMode = .easeInEaseOut
            sprite.run(.repeatForever(sway))
            return
        }

        // Procedural swim wiggle on the sprite.
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

        // Slow horizontal patrol on the wrapper, flipping the container to face.
        let range = CGFloat.random(in: 140...340)
        let speed = CGFloat.random(in: 16...36)
        let dur = TimeInterval(range / speed)
        container.xScale = -1
        let goLeft = SKAction.moveBy(x: -range, y: 0, duration: dur)
        let goRight = SKAction.moveBy(x: range, y: 0, duration: dur)
        goLeft.timingMode = .easeInEaseOut
        goRight.timingMode = .easeInEaseOut
        let faceRight = SKAction.run { container.xScale = 1 }
        let faceLeft = SKAction.run { container.xScale = -1 }
        wrapper.run(.repeatForever(.sequence([goLeft, faceRight, goRight, faceLeft])))
    }
}

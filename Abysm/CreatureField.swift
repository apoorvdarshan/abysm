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

import UIKit
import SpriteKit

final class CreatureField: SKNode {

    private(set) var placed: [(def: CreatureDef, node: SKNode)] = []
    /// One fact bubble per creature (same order as `placed`), hidden until the
    /// diver is the nearest creature — shown in-world beside the creature so it
    /// never covers the screen.
    private var infos: [SKNode] = []
    private var shownIndex: Int?

    /// Per-creature horizontal drift + bob state, updated every frame so the
    /// creatures wrap around the diver's column (see `update`).
    private struct Mover {
        let wrapper: SKNode
        let vx: CGFloat          // horizontal drift (points/sec); 0 for anchored creatures
        let depthY: CGFloat
        let bobAmp: CGFloat
        let bobSpeed: CGFloat
        var phase: CGFloat
    }
    private var movers: [Mover] = []
    /// Half-width of the window creatures wrap within, around the camera, so each
    /// depth's creatures always populate the diver's column. Larger than the
    /// screen half-width so the wrap happens off-screen (no visible pop).
    private let wrapHalf: CGFloat = 640

    /// Creatures whose source sprite faces RIGHT (the majority face left). Used to
    /// flip each creature so it swims HEAD-first, not tail-first. Verified per
    /// sprite by eye/mouth/head position.
    private static let facesRight: Set<String> = [
        "bigeyetuna", "clownfish", "dragonfish", "emperorpenguin", "facelessfish",
        "giantisopod", "grenadier", "leatherback", "nautilus", "oarfish",
        "salmon", "snailfish", "spermwhale", "sunfish",
    ]
    // NOTE: re-verified after the 42-sprite art swap — many regenerated sprites
    // flipped facing (polarbear/mahimahi/sealion/chaincatshark/cookiecutter/
    // fangtooth/manatee/barracuda/gulpereel/scalyfoot/beakedwhale now face left;
    // giantisopod now faces right). Non-swapped creatures keep their verified facing.

    func populate() {
        for c in Creatures.all {
            // Skip any creature whose sprite isn't bundled yet, so a missing
            // asset never renders as SpriteKit's red ✗ placeholder box.
            guard UIImage(named: "creature_\(c.key)") != nil else { continue }
            let tex = SKTexture(imageNamed: "creature_\(c.key)")
            tex.filteringMode = .nearest
            let aspect = tex.size().width > 0 ? tex.size().height / tex.size().width : 1
            let sprite = SKSpriteNode(texture: tex)
            let cs = GameConfig.creatureScale
            sprite.size = CGSize(width: c.width * cs, height: c.width * aspect * cs)

            let container = SKNode()
            container.addChild(sprite)

            let wrapper = SKNode()
            wrapper.zPosition = GameConfig.Z.player - 1
            let depthY = -c.depthM * GameConfig.pointsPerMeter
            wrapper.position = CGPoint(x: CGFloat.random(in: -wrapHalf...wrapHalf), y: depthY)
            wrapper.addChild(container)

            let tag = makeNameTag(L("creature.\(c.key).name", c.name))
            tag.position = CGPoint(x: 0, y: -sprite.size.height / 2 - 16)
            wrapper.addChild(tag)

            let fact = makeFactBubble(c)
            fact.position = CGPoint(x: 0, y: tag.position.y - 16)
            fact.alpha = 0
            wrapper.addChild(fact)

            addChild(wrapper)
            placed.append((c, wrapper))
            infos.append(fact)

            // Continuous horizontal drift (anchored creatures stay put). Flip so
            // the creature swims HEAD-first: the displayed facing must match the
            // movement direction, accounting for which way the source art faces.
            let vx: CGFloat = c.still ? 0 : (Bool.random() ? 1 : -1) * CGFloat.random(in: 16...44)
            let natural: CGFloat = Self.facesRight.contains(c.key) ? 1 : -1
            container.xScale = vx == 0 ? 1 : (vx < 0 ? -1 : 1) * natural
            movers.append(Mover(wrapper: wrapper, vx: vx, depthY: depthY,
                                bobAmp: CGFloat.random(in: 4...9),
                                bobSpeed: CGFloat.random(in: 1.0...1.6),
                                phase: CGFloat.random(in: 0...6.28)))
            setupWiggle(sprite: sprite, still: c.still)
        }
    }

    /// Drift each creature horizontally and wrap it around the camera, plus a
    /// gentle vertical bob. Wrapping keeps every depth's creatures in the diver's
    /// column so they're always seen crossing as you descend the endless ocean.
    func update(dt: CGFloat, cameraX: CGFloat) {
        for i in movers.indices {
            movers[i].phase += dt
            let m = movers[i]
            let w = m.wrapper
            if m.vx != 0 { w.position.x += m.vx * dt }
            let rel = w.position.x - cameraX
            if rel > wrapHalf { w.position.x -= 2 * wrapHalf }
            else if rel < -wrapHalf { w.position.x += 2 * wrapHalf }
            w.position.y = m.depthY + sin(m.phase * m.bobSpeed) * m.bobAmp
        }
    }

    /// Show the fact bubble for the creature nearest `point` (within `d`), and
    /// fade out the previously-shown one. No screen overlay — the info lives in
    /// the water next to its creature.
    func updateInfo(near point: CGPoint, within d: CGFloat) {
        var best = -1
        var bestDist = d
        for (i, p) in placed.enumerated() {
            let dist = hypot(p.node.position.x - point.x, p.node.position.y - point.y)
            if dist < bestDist { bestDist = dist; best = i }
        }
        let newIndex = best >= 0 ? best : nil
        guard newIndex != shownIndex else { return }
        if let old = shownIndex {
            infos[old].removeAllActions()
            infos[old].run(.fadeAlpha(to: 0, duration: 0.25))
        }
        if let n = newIndex {
            infos[n].removeAllActions()
            infos[n].run(.fadeAlpha(to: 1, duration: 0.18))
        }
        shownIndex = newIndex
    }

    // MARK: Name tag (readable over any background)

    private func makeNameTag(_ name: String) -> SKNode {
        let s = GameConfig.labelScale
        let node = SKNode()
        let label = GameFont.label()
        label.text = name.uppercased(with: Locale.current)   // locale-safe (e.g. Turkish i/İ)
        label.fontSize = 7 * s
        label.fontColor = .white
        label.verticalAlignmentMode = .center
        label.horizontalAlignmentMode = .center
        label.zPosition = 1

        let plate = SKSpriteNode(color: Palette.rgb(8, 20, 44),
                                 size: CGSize(width: label.frame.width + 14 * s, height: 18 * s))
        plate.alpha = 0.5
        plate.zPosition = 0
        node.addChild(plate)
        node.addChild(label)
        node.alpha = 0.82
        return node
    }

    // MARK: Fact bubble (neal.fun-style info, in-world beside the creature)

    private func makeFactBubble(_ c: CreatureDef) -> SKNode {
        let s = GameConfig.labelScale
        let node = SKNode()
        let width: CGFloat = 212 * s
        let topPad: CGFloat = 4 * s, gap: CGFloat = 7 * s, botPad: CGFloat = 8 * s

        let meta = GameFont.label()
        meta.text = "\(Int(c.depthM))M  ·  \(zoneName(c.depthM))"
        meta.fontSize = 6 * s
        meta.fontColor = Palette.rgb(150, 236, 232)
        meta.horizontalAlignmentMode = .center
        meta.verticalAlignmentMode = .top
        meta.position = CGPoint(x: 0, y: -topPad)
        meta.zPosition = 1

        let fact = GameFont.label()
        fact.text = L("creature.\(c.key).fact", c.fact)
        fact.fontSize = 6 * s
        fact.fontColor = Palette.rgb(212, 228, 238)
        fact.horizontalAlignmentMode = .center
        fact.verticalAlignmentMode = .top
        fact.numberOfLines = 0
        fact.preferredMaxLayoutWidth = width - 18 * s
        fact.lineBreakMode = .byWordWrapping
        fact.zPosition = 1

        let metaH = meta.frame.height
        fact.position = CGPoint(x: 0, y: -topPad - metaH - gap)
        let factH = fact.frame.height
        let totalH = topPad + metaH + gap + factH + botPad   // top pad + content + bottom pad

        let plate = SKSpriteNode(color: Palette.rgb(8, 18, 40), size: CGSize(width: width, height: totalH))
        plate.alpha = 0.72
        plate.position = CGPoint(x: 0, y: -totalH / 2)

        let border = SKSpriteNode(color: Palette.rgb(96, 184, 198),
                                  size: CGSize(width: width + 4, height: totalH + 4))
        border.alpha = 0.5
        border.position = plate.position
        border.zPosition = -1

        node.addChild(border)
        node.addChild(plate)
        node.addChild(meta)
        node.addChild(fact)
        return node
    }

    // MARK: Motion

    /// Procedural swim wiggle (tail-wag + length pulse), or a slow sway for
    /// anchored creatures. Horizontal drift + bob live in `update`.
    private func setupWiggle(sprite: SKSpriteNode, still: Bool) {
        let phase = TimeInterval.random(in: 0...1)

        if still {
            let sway = SKAction.sequence([.rotate(toAngle: 0.05, duration: 2.2),
                                          .rotate(toAngle: -0.05, duration: 2.2)])
            sway.timingMode = .easeInEaseOut
            sprite.run(.repeatForever(sway))
            return
        }

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
    }
}

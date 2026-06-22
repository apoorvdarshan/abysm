//
//  Atmosphere.swift
//  Abysm
//
//  Background depth/life that makes the dive feel alive:
//    • ScenicField — dim, distant pixel-art scenery (coral, kelp, rock spires,
//      mounds, hydrothermal vents) placed at depth-appropriate bands, behind the
//      creatures, blue-tinted and faded so it reads as far-off seabed.
//    • SchoolField — loose schools of small fish drifting and wrapping around
//      the diver's column at various depths.
//  Both wrap horizontally around the camera so they always populate the endless
//  ocean as you descend.
//

import UIKit
import SpriteKit

final class ScenicField: SKNode {

    private var pieces: [SKNode] = []
    private let wrapHalf: CGFloat = 920
    private let tint = Palette.rgb(16, 52, 98)

    func populate() {
        // (asset, minDepth, maxDepth) — scenery suited to each depth band.
        let bands: [(String, CGFloat, CGFloat)] = [
            ("bg_coral", 5, 200), ("bg_kelp", 10, 260), ("bg_kelp", 60, 420),
            ("bg_mound", 200, 1800), ("bg_pillar", 350, 2400), ("bg_mound", 1500, 3800),
            ("bg_pillar", 2200, 5200), ("bg_vent", 1600, 4200), ("bg_vent", 4200, 7200),
            ("bg_mound", 5200, 9000), ("bg_pillar", 6500, 10400),
        ]
        for (key, dMin, dMax) in bands {
            guard UIImage(named: key) != nil else { continue }
            let tex = SKTexture(imageNamed: key); tex.filteringMode = .nearest
            let aspect = tex.size().width > 0 ? tex.size().height / tex.size().width : 1
            for _ in 0..<2 {
                let depthM = CGFloat.random(in: dMin...dMax)
                let frac = min(1, depthM / 6000)
                let w = CGFloat.random(in: 120...200)
                let sprite = SKSpriteNode(texture: tex)
                sprite.size = CGSize(width: w, height: w * aspect)
                sprite.color = tint
                sprite.colorBlendFactor = 0.45 + 0.4 * frac    // bluer/dimmer with depth
                sprite.alpha = 0.7 - 0.32 * frac
                if key == "bg_kelp" || key == "bg_coral" {
                    let sway = SKAction.sequence([rot(0.06, 2.4), rot(-0.06, 2.4)])
                    sprite.run(.repeatForever(sway))
                }
                let node = SKNode()
                node.addChild(sprite)
                node.position = CGPoint(x: CGFloat.random(in: -wrapHalf...wrapHalf),
                                        y: -depthM * GameConfig.pointsPerMeter)
                node.zPosition = GameConfig.Z.player - 20 - CGFloat.random(in: 0...8)
                addChild(node)
                pieces.append(node)
            }
        }
    }

    func update(cameraX: CGFloat) {
        for n in pieces {
            let rel = n.position.x - cameraX
            if rel > wrapHalf { n.position.x -= 2 * wrapHalf }
            else if rel < -wrapHalf { n.position.x += 2 * wrapHalf }
        }
    }

    private func rot(_ a: CGFloat, _ d: TimeInterval) -> SKAction {
        let r = SKAction.rotate(toAngle: a, duration: d); r.timingMode = .easeInEaseOut; return r
    }
}

final class CloudField: SKNode {

    private var clouds: [(node: SKNode, vx: CGFloat)] = []
    private let wrapHalf: CGFloat = 1150

    func populate() {
        let keys = ["cloud_a", "cloud_b"]
        for i in 0..<8 {
            let key = keys[i % keys.count]
            guard UIImage(named: key) != nil else { continue }
            let tex = SKTexture(imageNamed: key); tex.filteringMode = .nearest
            let aspect = tex.size().width > 0 ? tex.size().height / tex.size().width : 1
            let w = CGFloat.random(in: 190...320)
            let sprite = SKSpriteNode(texture: tex)
            sprite.size = CGSize(width: w, height: w * aspect)
            sprite.alpha = CGFloat.random(in: 0.78...0.96)
            let node = SKNode()
            node.addChild(sprite)
            node.position = CGPoint(x: CGFloat.random(in: -wrapHalf...wrapHalf),
                                    y: CGFloat.random(in: 70...165))
            node.zPosition = GameConfig.Z.sky + 5     // in front of the sky gradient
            addChild(node)
            clouds.append((node, CGFloat.random(in: 4...11) * (Bool.random() ? 1 : -1)))
        }
    }

    func update(dt: CGFloat, cameraX: CGFloat) {
        for c in clouds {
            c.node.position.x += c.vx * dt
            let rel = c.node.position.x - cameraX
            if rel > wrapHalf { c.node.position.x -= 2 * wrapHalf }
            else if rel < -wrapHalf { c.node.position.x += 2 * wrapHalf }
        }
    }
}

final class SchoolField: SKNode {

    private struct Fish {
        let node: SKNode; let vx: CGFloat; let baseY: CGFloat
        let bobAmp: CGFloat; let bobSpeed: CGFloat; var phase: CGFloat
    }
    private var fish: [Fish] = []
    private let wrapHalf: CGFloat = 780

    func populate() {
        guard UIImage(named: "school_fish") != nil else { return }
        let tex = SKTexture(imageNamed: "school_fish"); tex.filteringMode = .nearest
        let aspect = tex.size().width > 0 ? tex.size().height / tex.size().width : 1
        let depths: [CGFloat] = [40, 130, 320, 620, 1100, 2400]
        for d in depths {
            let dir: CGFloat = Bool.random() ? 1 : -1
            let speed = CGFloat.random(in: 18...34) * dir
            let cx = CGFloat.random(in: -wrapHalf...wrapHalf)
            let frac = min(0.65, d / 4000)
            for _ in 0..<Int.random(in: 4...7) {
                let w = CGFloat.random(in: 32...46)
                let sprite = SKSpriteNode(texture: tex)
                sprite.size = CGSize(width: w, height: w * aspect)
                sprite.xScale = dir < 0 ? -1 : 1
                sprite.color = Palette.rgb(16, 52, 98); sprite.colorBlendFactor = frac
                let node = SKNode()
                node.addChild(sprite)
                let y = -d * GameConfig.pointsPerMeter + CGFloat.random(in: -45...45)
                node.position = CGPoint(x: cx + CGFloat.random(in: -80...80), y: y)
                node.zPosition = GameConfig.Z.player - 12
                addChild(node)
                fish.append(Fish(node: node, vx: speed, baseY: y,
                                 bobAmp: CGFloat.random(in: 3...7),
                                 bobSpeed: CGFloat.random(in: 1.2...1.9),
                                 phase: CGFloat.random(in: 0...6.28)))
            }
        }
    }

    func update(dt: CGFloat, cameraX: CGFloat) {
        for i in fish.indices {
            fish[i].phase += dt
            let f = fish[i], n = f.node
            n.position.x += f.vx * dt
            let rel = n.position.x - cameraX
            if rel > wrapHalf { n.position.x -= 2 * wrapHalf }
            else if rel < -wrapHalf { n.position.x += 2 * wrapHalf }
            n.position.y = f.baseY + sin(f.phase * f.bobSpeed) * f.bobAmp
        }
    }
}

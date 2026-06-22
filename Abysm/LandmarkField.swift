//
//  LandmarkField.swift
//  Abysm
//
//  neal.fun-style landmark "moments" at real depths: a glowing gold marker line
//  spanning the view with a labelled plate (name · depth · note). Drawn entirely
//  in-engine (no art needed). Rendered above the darkness veil so it's always
//  readable, even in the pitch-black deep. The line follows the camera
//  horizontally so it spans the endless ocean.
//

import UIKit
import SpriteKit

struct LandmarkDef {
    let name: String
    let depthM: CGFloat
    let note: String
}

final class LandmarkField: SKNode {

    static let all: [LandmarkDef] = [
        LandmarkDef(name: "DEEPEST SCUBA DIVE", depthM: 332,
                    note: "Ahmed Gabr, 2014 — as deep as a human has ever scuba-dived."),
        LandmarkDef(name: "RMS TITANIC", depthM: 3800,
                    note: "The wreck has rested on the seafloor here since 1912."),
        LandmarkDef(name: "USS JOHNSTON", depthM: 6241,
                    note: "The deepest shipwreck ever found, lost in WWII's Battle off Samar."),
        LandmarkDef(name: "CHALLENGER DEEP", depthM: 10935,
                    note: "The bottom of the ocean. You made it all the way down.")
    ]

    private var nodes: [SKNode] = []

    func populate() {
        for d in LandmarkField.all {
            let node = makeLandmark(d)
            node.position = CGPoint(x: 0, y: -d.depthM * GameConfig.pointsPerMeter)
            node.zPosition = GameConfig.Z.darkness + 2   // above the darkness veil
            addChild(node)
            nodes.append(node)
        }
    }

    /// Keep each marker centered on the diver's column so the line spans the view
    /// and the label stays readable as you cross its depth in the endless ocean.
    func update(cameraX: CGFloat) {
        for n in nodes { n.position.x = cameraX }
    }

    // MARK: Build

    private func makeLandmark(_ d: LandmarkDef) -> SKNode {
        let node = SKNode()
        let gold = Palette.rgb(242, 208, 120)
        let width: CGFloat = 312

        // Marker line across the view + a soft additive glow behind it.
        let line = SKSpriteNode(color: gold, size: CGSize(width: 4200, height: 4))
        line.alpha = 0.30
        node.addChild(line)
        let glow = SKSpriteNode(color: gold, size: CGSize(width: 1400, height: 12))
        glow.alpha = 0.12
        glow.blendMode = .add
        glow.zPosition = -1
        node.addChild(glow)

        // Labels, built top-down then floated just above the line.
        let name = label(d.name, 11, gold)
        let depth = label("\(Int(d.depthM))M", 14, .white)
        let note = label(d.note, 6, Palette.rgb(214, 226, 236))
        note.numberOfLines = 2
        note.preferredMaxLayoutWidth = width - 20
        note.lineBreakMode = .byWordWrapping
        [name, depth, note].forEach {
            $0.horizontalAlignmentMode = .center
            $0.verticalAlignmentMode = .top
            $0.zPosition = 1
        }

        let pad: CGFloat = 9
        let nameH = name.frame.height, depthH = depth.frame.height, noteH = note.frame.height
        let blockH = pad + nameH + 5 + depthH + 6 + noteH + pad
        let bottom: CGFloat = 16          // gap above the marker line
        let top = bottom + blockH
        name.position  = CGPoint(x: 0, y: top - pad)
        depth.position = CGPoint(x: 0, y: top - pad - nameH - 5)
        note.position  = CGPoint(x: 0, y: top - pad - nameH - 5 - depthH - 6)

        let plate = SKSpriteNode(color: Palette.rgb(9, 20, 44), size: CGSize(width: width, height: blockH))
        plate.alpha = 0.82
        plate.position = CGPoint(x: 0, y: bottom + blockH / 2)
        let border = SKSpriteNode(color: gold, size: CGSize(width: width + 6, height: blockH + 6))
        border.alpha = 0.5
        border.position = plate.position
        border.zPosition = -1

        node.addChild(border)
        node.addChild(plate)
        node.addChild(name)
        node.addChild(depth)
        node.addChild(note)
        return node
    }

    private func label(_ text: String, _ size: CGFloat, _ color: UIColor) -> SKLabelNode {
        let l = SKLabelNode(fontNamed: "PressStart2P-Regular")
        l.text = text
        l.fontSize = size
        l.fontColor = color
        return l
    }
}

//
//  LandmarkField.swift
//  Abysm
//
//  neal.fun-style landmark "moments" at real depths: a pixel-art scene (a
//  shipwreck, a submersible, a record diver) sitting in the water with a small
//  label below it (name · depth · note). No separator lines — the art reads as
//  part of the sea. The artwork sits behind the swimmer/creatures and is lit by
//  the lamp like everything else; the label floats above the darkness veil so
//  it stays readable even in the pitch-black deep. Each marker wraps around the
//  diver's column (like the creatures) so you meet it as you descend.
//

import UIKit
import SpriteKit

struct LandmarkDef {
    let name: String
    let depthM: CGFloat
    let note: String
    let image: String?
    let width: CGFloat
}

final class LandmarkField: SKNode {

    static let all: [LandmarkDef] = [
        LandmarkDef(name: "DEEPEST SCUBA DIVE", depthM: 332,
                    note: "Ahmed Gabr, 2014 — as deep as a human has ever scuba-dived.",
                    image: "diver0", width: 110),
        LandmarkDef(name: "RMS TITANIC", depthM: 3800,
                    note: "The wreck has rested on the seafloor here since 1912.",
                    image: "landmark_titanic", width: 260),
        LandmarkDef(name: "USS JOHNSTON", depthM: 6241,
                    note: "The deepest shipwreck ever found, lost in WWII's Battle off Samar.",
                    image: "landmark_johnston", width: 240),
        LandmarkDef(name: "CHALLENGER DEEP", depthM: 10935,
                    note: "The bottom of the ocean. You made it all the way down.",
                    image: "landmark_submersible", width: 150)
    ]

    private var nodes: [SKNode] = []
    /// Wrap window around the camera (matches the creatures) so each landmark is
    /// always near the diver's column at its depth. Larger than the screen
    /// half-width so the wrap happens off-screen.
    private let wrapHalf: CGFloat = 640

    func populate() {
        for d in LandmarkField.all {
            let node = makeLandmark(d)
            node.position = CGPoint(x: 0, y: -d.depthM * GameConfig.pointsPerMeter)
            addChild(node)
            nodes.append(node)
        }
    }

    /// Keep each marker wrapped within the diver's column as you roam the endless
    /// ocean, so you cross it at its depth.
    func update(cameraX: CGFloat) {
        for n in nodes {
            let rel = n.position.x - cameraX
            if rel > wrapHalf { n.position.x -= 2 * wrapHalf }
            else if rel < -wrapHalf { n.position.x += 2 * wrapHalf }
        }
    }

    // MARK: Build

    private func makeLandmark(_ d: LandmarkDef) -> SKNode {
        let node = SKNode()
        let gold = Palette.rgb(242, 208, 120)

        // The pixel-art scene, sitting behind the swimmer/creatures and lit by
        // the lamp (below the darkness veil).
        var artBottom: CGFloat = 0
        if let name = d.image, UIImage(named: name) != nil {
            let tex = SKTexture(imageNamed: name)
            tex.filteringMode = .nearest
            let aspect = tex.size().width > 0 ? tex.size().height / tex.size().width : 1
            let sprite = SKSpriteNode(texture: tex)
            sprite.size = CGSize(width: d.width, height: d.width * aspect)
            sprite.zPosition = -2          // behind creatures + diver; lamp reveals it
            node.addChild(sprite)
            artBottom = -sprite.size.height / 2
        }

        // Label block below the art (above the darkness veil so it always reads).
        let width: CGFloat = 300
        let nameL = label(d.name, 11, gold)
        let depthL = label("\(Int(d.depthM))M", 14, .white)
        let noteL = label(d.note, 6, Palette.rgb(214, 226, 236))
        noteL.numberOfLines = 2
        noteL.preferredMaxLayoutWidth = width - 20
        noteL.lineBreakMode = .byWordWrapping
        [nameL, depthL, noteL].forEach {
            $0.horizontalAlignmentMode = .center
            $0.verticalAlignmentMode = .top
            $0.zPosition = GameConfig.Z.darkness + 3   // above the veil
        }

        let pad: CGFloat = 9
        let nameH = nameL.frame.height, depthH = depthL.frame.height, noteH = noteL.frame.height
        let blockH = pad + nameH + 5 + depthH + 6 + noteH + pad
        let top = artBottom - 12          // sits just under the art
        nameL.position  = CGPoint(x: 0, y: top - pad)
        depthL.position = CGPoint(x: 0, y: top - pad - nameH - 5)
        noteL.position  = CGPoint(x: 0, y: top - pad - nameH - 5 - depthH - 6)

        let plate = SKSpriteNode(color: Palette.rgb(9, 20, 44), size: CGSize(width: width, height: blockH))
        plate.alpha = 0.82
        plate.position = CGPoint(x: 0, y: top - blockH / 2)
        plate.zPosition = GameConfig.Z.darkness + 2
        let border = SKSpriteNode(color: gold, size: CGSize(width: width + 6, height: blockH + 6))
        border.alpha = 0.5
        border.position = plate.position
        border.zPosition = GameConfig.Z.darkness + 1

        node.addChild(border)
        node.addChild(plate)
        node.addChild(nameL)
        node.addChild(depthL)
        node.addChild(noteL)
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

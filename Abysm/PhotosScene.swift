//
//  PhotosScene.swift
//  Abysm
//
//  The Photos gallery, reached from the title: a grid of dive photos you've
//  snapped with the in-game camera. Tap a photo to view it large; BACK returns
//  to the title.
//

import UIKit
import SpriteKit

final class PhotosScene: SKScene {

    private let bg = SKSpriteNode()
    private let backBtn = SKNode()
    private let titleL = SKLabelNode(fontNamed: "PressStart2P-Regular")
    private var thumbs: [(node: SKNode, url: URL)] = []
    private var overlay: SKNode?            // the enlarged view, if open
    private let btnW: CGFloat = 180, btnH: CGFloat = 44

    override func didMove(to view: SKView) {
        anchorPoint = CGPoint(x: 0.5, y: 0.5)
        backgroundColor = Palette.rgb(14, 40, 78)
        bg.zPosition = -10; addChild(bg)

        titleL.text = "PHOTOS"; titleL.fontSize = 28; titleL.fontColor = .white
        titleL.verticalAlignmentMode = .center; titleL.horizontalAlignmentMode = .center
        titleL.zPosition = 5; addChild(titleL)

        plate(backBtn, "BACK")

        let urls = Array(PhotoManager.allURLs().prefix(9))
        if urls.isEmpty {
            let empty = SKLabelNode(fontNamed: "PressStart2P-Regular")
            empty.text = "NO PHOTOS YET — TAP THE CAMERA WHILE DIVING"
            empty.fontSize = 9; empty.fontColor = Palette.rgb(150, 200, 230)
            empty.verticalAlignmentMode = .center; empty.horizontalAlignmentMode = .center
            empty.zPosition = 5; empty.name = "empty"
            addChild(empty)
        } else {
            for url in urls {
                let frame = SKSpriteNode(color: Palette.rgb(150, 236, 232), size: .zero)
                frame.zPosition = 4
                let img = SKSpriteNode()
                img.zPosition = 5
                if let ui = PhotoManager.image(url) {
                    img.texture = SKTexture(image: ui)
                    img.texture?.filteringMode = .nearest
                }
                frame.addChild(img)
                frame.name = "thumb"
                addChild(frame)
                thumbs.append((frame, url))
            }
        }

        layout()
        DispatchQueue.main.async { [weak self] in self?.layout() }
    }

    private func plate(_ node: SKNode, _ text: String) {
        let border = SKSpriteNode(color: Palette.rgb(150, 236, 232), size: CGSize(width: btnW + 6, height: btnH + 6)); border.alpha = 0.8
        let p = SKSpriteNode(color: Palette.rgb(9, 20, 44), size: CGSize(width: btnW, height: btnH)); p.alpha = 0.95; p.zPosition = 1
        let l = SKLabelNode(fontNamed: "PressStart2P-Regular")
        l.text = text; l.fontSize = 14; l.fontColor = .white
        l.verticalAlignmentMode = .center; l.horizontalAlignmentMode = .center; l.zPosition = 2
        node.addChild(border); node.addChild(p); node.addChild(l); node.zPosition = 6
        addChild(node)
    }

    private func layout() {
        let w = size.width, h = size.height
        bg.size = CGSize(width: w, height: h)
        titleL.position = CGPoint(x: 0, y: h / 2 - 46)
        backBtn.position = CGPoint(x: -w / 2 + btnW / 2 + 24, y: h / 2 - 44)
        if let e = childNode(withName: "empty") { e.position = .zero }

        // 3-column grid centered under the title.
        let cols = 3
        let cellW = min(230, (w - 120) / CGFloat(cols))
        let aspect: CGFloat = h > 0 ? (size.height / size.width) : 0.5
        let imgW = cellW - 16
        let imgH = imgW * aspect
        let cellH = imgH + 16
        let rows = Int(ceil(Double(thumbs.count) / Double(cols)))
        let gridW = CGFloat(cols) * cellW
        let gridTop = h / 2 - 100
        for (i, t) in thumbs.enumerated() {
            let r = i / cols, c = i % cols
            let x = -gridW / 2 + cellW / 2 + CGFloat(c) * cellW
            let y = gridTop - cellH / 2 - CGFloat(r) * cellH
            t.node.position = CGPoint(x: x, y: y)
            if let frame = t.node as? SKSpriteNode {
                frame.size = CGSize(width: imgW + 6, height: imgH + 6)
                (frame.children.first as? SKSpriteNode)?.size = CGSize(width: imgW, height: imgH)
            }
        }
        _ = rows
    }

    override func didChangeSize(_ oldSize: CGSize) { super.didChangeSize(oldSize); layout() }

    override func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent?) {
        guard let t = touches.first else { return }
        let p = t.location(in: self)
        if overlay != nil { overlay?.removeFromParent(); overlay = nil; return }   // tap dismisses the big view
        if abs(p.x - backBtn.position.x) <= btnW / 2, abs(p.y - backBtn.position.y) <= btnH / 2 {
            goBack(); return
        }
        for thumb in thumbs {
            guard let f = thumb.node as? SKSpriteNode else { continue }
            if abs(p.x - f.position.x) <= f.size.width / 2, abs(p.y - f.position.y) <= f.size.height / 2 {
                enlarge(thumb.url); return
            }
        }
    }

    private func enlarge(_ url: URL) {
        guard let ui = PhotoManager.image(url) else { return }
        let node = SKNode(); node.zPosition = 50
        let dim = SKSpriteNode(color: .black, size: CGSize(width: size.width * 2, height: size.height * 2))
        dim.alpha = 0.82; node.addChild(dim)
        let img = SKSpriteNode(texture: SKTexture(image: ui))
        img.texture?.filteringMode = .nearest
        let maxW = size.width * 0.86, maxH = size.height * 0.86
        let aspect = ui.size.height / max(1, ui.size.width)
        var iw = maxW, ih = maxW * aspect
        if ih > maxH { ih = maxH; iw = maxH / aspect }
        img.size = CGSize(width: iw, height: ih); img.zPosition = 1
        node.addChild(img)
        addChild(node); overlay = node
    }

    private func goBack() {
        guard let v = view else { return }
        let t = TitleScene(size: v.bounds.size)
        t.scaleMode = .resizeFill
        v.presentScene(t, transition: .fade(with: .black, duration: 0.4))
    }
}

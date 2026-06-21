//
//  DepthHUD.swift
//  Abysm
//
//  Depth read-out on a pixel-art panel (dark plate + light border) so it stays
//  readable over bright water. Lives as a camera child; positioned by the scene.
//

import SpriteKit

final class DepthHUD: SKNode {

    private let value = SKLabelNode(fontNamed: "PressStart2P-Regular")
    private let caption = SKLabelNode(fontNamed: "PressStart2P-Regular")
    private let panel = SKSpriteNode()
    private let border = SKSpriteNode()
    private var lastMeters = Int.min

    override init() {
        super.init()
        zPosition = GameConfig.Z.hud
        let px = GameConfig.pixel
        let w = 38 * px, h = 9 * px

        border.color = Palette.rgb(180, 238, 236)
        border.size = CGSize(width: w + 2 * px, height: h + 2 * px)
        border.zPosition = 0
        addChild(border)

        panel.color = Palette.rgb(10, 26, 56)
        panel.alpha = 0.86
        panel.size = CGSize(width: w, height: h)
        panel.zPosition = 1
        addChild(panel)

        caption.fontSize = 8
        caption.fontColor = Palette.rgb(150, 236, 232)
        caption.verticalAlignmentMode = .center
        caption.horizontalAlignmentMode = .center
        caption.text = "SUNLIGHT ZONE"
        caption.position = CGPoint(x: 0, y: h * 0.24)
        caption.zPosition = 2
        addChild(caption)

        value.fontSize = 17
        value.fontColor = .white
        value.verticalAlignmentMode = .center
        value.horizontalAlignmentMode = .center
        value.text = "0M"
        value.position = CGPoint(x: 0, y: -h * 0.18)
        value.zPosition = 2
        addChild(value)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    private var lastZone = ""

    func update(depthMeters: CGFloat, zone: String) {
        let m = max(0, Int(depthMeters.rounded()))
        if m != lastMeters {
            lastMeters = m
            value.text = "\(m)M"
        }
        if zone != lastZone {
            lastZone = zone
            caption.text = zone
        }
    }
}

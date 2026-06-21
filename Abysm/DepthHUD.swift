//
//  DepthHUD.swift
//  Abysm
//
//  The lone piece of UI in Phase 1: a subtle depth read-out. Lives as a child
//  of the camera so it stays pinned to the screen, and is positioned by the
//  scene to respect the safe-area inset. Each label carries a soft dark shadow
//  copy so it stays legible over both the bright sunlit surface and the dark
//  deep water.
//

import SpriteKit

final class DepthHUD: SKNode {

    private let value = SKLabelNode(fontNamed: "PressStart2P-Regular")
    private let valueShadow = SKLabelNode(fontNamed: "PressStart2P-Regular")
    private let caption = SKLabelNode(fontNamed: "PressStart2P-Regular")
    private let captionShadow = SKLabelNode(fontNamed: "PressStart2P-Regular")
    private var lastMeters = Int.min

    override init() {
        super.init()
        zPosition = GameConfig.Z.hud

        configure(caption, size: 9, color: UIColor(white: 1, alpha: 0.6), y: 22, text: "DEPTH")
        configure(captionShadow, size: 9, color: UIColor(white: 0, alpha: 0.3), y: 22 - 3, text: "DEPTH")
        configure(value, size: 18, color: UIColor(white: 1, alpha: 0.9), y: 0, text: "0M")
        configure(valueShadow, size: 18, color: UIColor(white: 0, alpha: 0.35), y: -3, text: "0M")

        // Shadows behind their labels.
        addChild(captionShadow)
        addChild(caption)
        addChild(valueShadow)
        addChild(value)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    private func configure(_ label: SKLabelNode, size: CGFloat, color: UIColor, y: CGFloat, text: String) {
        label.fontSize = size
        label.fontColor = color
        label.verticalAlignmentMode = .center
        label.horizontalAlignmentMode = .center
        label.position = CGPoint(x: 0, y: y)
        label.text = text
    }

    func update(depthMeters: CGFloat) {
        let m = max(0, Int(depthMeters.rounded()))
        guard m != lastMeters else { return }
        lastMeters = m
        value.text = "\(m)M"
        valueShadow.text = "\(m)M"
    }
}

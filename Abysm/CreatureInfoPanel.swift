//
//  CreatureInfoPanel.swift
//  Abysm
//
//  A neal.fun-style info card: when the diver swims near a creature, this panel
//  fades in with its name, depth + zone, and a one-line fact. A camera child,
//  positioned by the scene.
//

import SpriteKit

final class CreatureInfoPanel: SKNode {

    let panelSize = CGSize(width: 384, height: 104)
    private let border = SKSpriteNode()
    private let panel = SKSpriteNode()
    private let nameL = SKLabelNode(fontNamed: "PressStart2P-Regular")
    private let metaL = SKLabelNode(fontNamed: "PressStart2P-Regular")
    private let factL = SKLabelNode(fontNamed: "PressStart2P-Regular")
    private var shownKey = ""

    override init() {
        super.init()
        zPosition = GameConfig.Z.hud
        let px = GameConfig.pixel

        border.color = Palette.rgb(150, 236, 232)
        border.size = CGSize(width: panelSize.width + 2 * px, height: panelSize.height + 2 * px)
        addChild(border)

        panel.color = Palette.rgb(10, 26, 56)
        panel.alpha = 0.92
        panel.size = panelSize
        panel.zPosition = 1
        addChild(panel)

        configure(nameL, size: 13, color: .white, y: panelSize.height / 2 - 18)
        configure(metaL, size: 8, color: Palette.rgb(150, 236, 232), y: panelSize.height / 2 - 38)
        configure(factL, size: 7, color: Palette.rgb(206, 224, 236), y: panelSize.height / 2 - 56)
        factL.numberOfLines = 0
        factL.verticalAlignmentMode = .top
        factL.preferredMaxLayoutWidth = panelSize.width - 30
        factL.lineBreakMode = .byWordWrapping

        alpha = 0   // hidden until near a creature
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    private func configure(_ l: SKLabelNode, size: CGFloat, color: UIColor, y: CGFloat) {
        l.fontSize = size
        l.fontColor = color
        l.horizontalAlignmentMode = .center
        l.verticalAlignmentMode = .center
        l.position = CGPoint(x: 0, y: y)
        l.zPosition = 2
        addChild(l)
    }

    func show(_ d: CreatureDef) {
        guard d.name != shownKey else { return }
        shownKey = d.name
        nameL.text = d.name.uppercased()
        metaL.text = "\(Int(d.depthM))M  ·  \(zoneName(d.depthM))"
        factL.text = d.fact
        removeAllActions()
        run(.fadeAlpha(to: 1, duration: 0.18))
    }

    func hide() {
        guard !shownKey.isEmpty else { return }
        shownKey = ""
        removeAllActions()
        run(.fadeAlpha(to: 0, duration: 0.28))
    }
}

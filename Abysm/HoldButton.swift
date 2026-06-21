//
//  HoldButton.swift
//  Abysm
//
//  A pixel-art on-screen button that reports a held/pressed state (used for the
//  speed boost + turbo on the right side). High-contrast like the joystick.
//

import SpriteKit

final class HoldButton: SKNode {

    let radius: CGFloat
    private let fill = SKSpriteNode()
    private let ring = SKSpriteNode()
    private let label = SKLabelNode(fontNamed: "PressStart2P-Regular")
    private let baseColor: UIColor
    private(set) var pressed = false

    init(radius: CGFloat, glyph: String, fontSize: CGFloat, color: UIColor) {
        self.radius = radius
        self.baseColor = color
        super.init()
        zPosition = GameConfig.Z.joystick
        let px = GameConfig.pixel
        let r = Int((radius / px).rounded())
        let size = CGSize(width: CGFloat(r * 2 + 2) * px, height: CGFloat(r * 2 + 2) * px)

        fill.texture = TextureFactory.pixelCircle(radius: r, color: color)
        fill.size = size
        fill.alpha = 0.55
        addChild(fill)

        ring.texture = TextureFactory.pixelCircle(radius: r, ring: 2, color: UIColor(white: 1, alpha: 0.9))
        ring.size = size
        ring.zPosition = 1
        addChild(ring)

        label.text = glyph
        label.fontSize = fontSize
        label.fontColor = .white
        label.verticalAlignmentMode = .center
        label.horizontalAlignmentMode = .center
        label.zPosition = 2
        addChild(label)
        alpha = 0.85
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    /// `point` in the button's parent (camera) space.
    func hit(_ point: CGPoint) -> Bool {
        hypot(point.x - position.x, point.y - position.y) <= radius * 1.25
    }

    func setPressed(_ v: Bool) {
        guard v != pressed else { return }
        pressed = v
        fill.alpha = v ? 0.95 : 0.55
        run(.fadeAlpha(to: v ? 1.0 : 0.85, duration: 0.06))
        setScale(v ? 0.92 : 1.0)
    }
}

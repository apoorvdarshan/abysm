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
    private let base = SKSpriteNode()
    private let fill = SKSpriteNode()
    private let ring = SKSpriteNode()
    private let label = SKLabelNode(fontNamed: "PressStart2P-Regular")
    private let baseColor: UIColor
    private(set) var pressed = false
    var accessibilityAction: (() -> Void)?

    init(radius: CGFloat, glyph: String, fontSize: CGFloat, color: UIColor) {
        self.radius = radius
        self.baseColor = color
        super.init()
        zPosition = GameConfig.Z.joystick
        let px = GameConfig.pixel
        let r = Int((radius / px).rounded())
        let size = CGSize(width: CGFloat(r * 2 + 2) * px, height: CGFloat(r * 2 + 2) * px)

        // Dark base disc so the button reads clearly over bright water.
        base.texture = TextureFactory.pixelCircle(radius: r, color: Palette.rgb(8, 22, 48))
        base.size = size
        base.alpha = 0.72
        base.zPosition = -1
        addChild(base)

        fill.texture = TextureFactory.pixelCircle(radius: r, color: color)
        fill.size = size
        fill.alpha = 0.45
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
        alpha = 0.95
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    func configureAccessibility(label: String, hint: String? = nil) {
        isAccessibilityElement = true
        accessibilityLabel = label
        accessibilityHint = hint
        accessibilityTraits = .button
    }

    // A hidden control (the headlamp in the sunlit zone) is not offered or
    // activated by accessibility.
    override var isAccessibilityElement: Bool {
        get { super.isAccessibilityElement && isVisibleInScene }
        set { super.isAccessibilityElement = newValue }
    }

    override var accessibilityTraits: UIAccessibilityTraits {
        get { isVisibleInScene ? super.accessibilityTraits : super.accessibilityTraits.union(.notEnabled) }
        set { super.accessibilityTraits = newValue }
    }

    override func accessibilityActivate() -> Bool {
        guard isVisibleInScene, let accessibilityAction else { return false }
        accessibilityAction()
        return true
    }

    /// `point` in the button's parent (camera) space.
    func hit(_ point: CGPoint) -> Bool {
        hypot(point.x - position.x, point.y - position.y) <= radius * 1.25
    }

    func setPressed(_ v: Bool) {
        guard v != pressed else { return }
        pressed = v
        fill.alpha = v ? 0.9 : 0.45
        run(.fadeAlpha(to: v ? 1.0 : 0.95, duration: 0.06))
        setScale(v ? 0.92 : 1.0)
    }
}

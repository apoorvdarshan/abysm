//
//  Joystick.swift
//  Abysm
//
//  An on-screen analog stick pinned to the bottom-left (a child of the camera,
//  so it stays put on screen). Drag the knob to steer the swimmer in any
//  direction; release and it springs back to center. `vector` is the steering
//  input: direction + magnitude in [-1, 1] per axis (length clamped to 1),
//  with +y meaning "up" to match SpriteKit/world space.
//

import SpriteKit

final class Joystick: SKNode {

    let baseRadius: CGFloat = 58
    private let knobRadius: CGFloat = 30
    /// Touches starting anywhere within this radius of the base engage the stick.
    var activationRadius: CGFloat { baseRadius * 1.9 }

    private let outerGlow = SKShapeNode(circleOfRadius: 66)
    private let base = SKShapeNode(circleOfRadius: 58)
    private let guide = SKShapeNode(circleOfRadius: 52)
    private let centerDot = SKShapeNode(circleOfRadius: 4)
    private let knob = SKSpriteNode()
    private let knobRim = SKShapeNode(circleOfRadius: 30)

    /// Current steering input (length 0…1). Zero when released.
    private(set) var vector: CGVector = .zero
    private var engaged = false

    override init() {
        super.init()
        zPosition = GameConfig.Z.joystick

        outerGlow.fillColor = Palette.rgb(150, 240, 235).withAlphaComponent(0.06)
        outerGlow.strokeColor = .clear
        outerGlow.blendMode = .add
        addChild(outerGlow)

        base.fillColor = UIColor(white: 1, alpha: 0.06)
        base.strokeColor = UIColor(white: 1, alpha: 0.32)
        base.lineWidth = 2
        addChild(base)

        guide.fillColor = .clear
        guide.strokeColor = UIColor(white: 1, alpha: 0.12)
        guide.lineWidth = 1
        addChild(guide)

        centerDot.fillColor = UIColor(white: 1, alpha: 0.22)
        centerDot.strokeColor = .clear
        addChild(centerDot)

        knob.texture = TextureFactory.radialGlow(
            diameter: 120,
            inner: Palette.rgb(180, 250, 246).withAlphaComponent(0.95),
            outer: Palette.rgb(70, 170, 190).withAlphaComponent(0.55))
        knob.size = CGSize(width: knobRadius * 2, height: knobRadius * 2)
        addChild(knob)

        knobRim.fillColor = .clear
        knobRim.strokeColor = UIColor(white: 1, alpha: 0.85)
        knobRim.lineWidth = 2
        knobRim.blendMode = .add
        knob.addChild(knobRim)

        alpha = 0.85

        // Gentle idle breathing so the control is noticeable but unobtrusive.
        let breathe = SKAction.sequence([
            SKAction.fadeAlpha(to: 0.62, duration: 1.6),
            SKAction.fadeAlpha(to: 0.85, duration: 1.6)
        ])
        breathe.timingMode = .easeInEaseOut
        run(.repeatForever(breathe), withKey: "breathe")
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    /// Try to engage the stick from a touch at `point` (in this node's parent
    /// space). Returns true if the touch is close enough to take control.
    func engage(at point: CGPoint) -> Bool {
        let local = CGPoint(x: point.x - position.x, y: point.y - position.y)
        guard hypot(local.x, local.y) <= activationRadius else { return false }
        engaged = true
        removeAction(forKey: "breathe")
        run(.fadeAlpha(to: 1.0, duration: 0.08))
        knob.run(.scale(to: 1.15, duration: 0.08))
        outerGlow.run(.fadeAlpha(to: 0.16, duration: 0.12))
        moveKnob(to: local)
        return true
    }

    /// Update the knob/vector from a drag at `point` (parent space).
    func drag(to point: CGPoint) {
        moveKnob(to: CGPoint(x: point.x - position.x, y: point.y - position.y))
    }

    /// Release: spring the knob home and clear the input.
    func release() {
        engaged = false
        vector = .zero
        knob.removeAllActions()
        let home = SKAction.move(to: .zero, duration: 0.12)
        home.timingMode = .easeOut
        knob.run(.group([home, .scale(to: 1.0, duration: 0.12)]))
        outerGlow.run(.fadeAlpha(to: 0.06, duration: 0.2))

        let breathe = SKAction.sequence([
            SKAction.fadeAlpha(to: 0.62, duration: 1.6),
            SKAction.fadeAlpha(to: 0.85, duration: 1.6)
        ])
        breathe.timingMode = .easeInEaseOut
        run(.repeatForever(breathe), withKey: "breathe")
    }

    private func moveKnob(to local: CGPoint) {
        let dist = hypot(local.x, local.y)
        if dist < 0.0001 {
            knob.position = .zero
            vector = .zero
            return
        }
        let clamped = min(dist, baseRadius)
        let ux = local.x / dist
        let uy = local.y / dist
        knob.removeAction(forKey: "spring")
        knob.position = CGPoint(x: ux * clamped, y: uy * clamped)
        vector = CGVector(dx: ux * (clamped / baseRadius),
                          dy: uy * (clamped / baseRadius))
    }
}

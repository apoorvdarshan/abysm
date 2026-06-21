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

    private let base = SKShapeNode(circleOfRadius: 58)
    private let knob = SKShapeNode(circleOfRadius: 30)

    /// Current steering input (length 0…1). Zero when released.
    private(set) var vector: CGVector = .zero

    override init() {
        super.init()
        zPosition = GameConfig.Z.joystick

        base.fillColor = UIColor(white: 1, alpha: 0.08)
        base.strokeColor = UIColor(white: 1, alpha: 0.35)
        base.lineWidth = 2
        addChild(base)

        // Faint guide ring for the knob's travel.
        let guide = SKShapeNode(circleOfRadius: baseRadius - 6)
        guide.fillColor = .clear
        guide.strokeColor = UIColor(white: 1, alpha: 0.12)
        guide.lineWidth = 1
        base.addChild(guide)

        knob.fillColor = Palette.rgb(150, 240, 235).withAlphaComponent(0.55)
        knob.strokeColor = UIColor(white: 1, alpha: 0.85)
        knob.lineWidth = 2
        addChild(knob)

        alpha = 0.9
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    /// Try to engage the stick from a touch at `point` (in this node's parent
    /// space). Returns true if the touch is close enough to take control.
    func engage(at point: CGPoint) -> Bool {
        let local = CGPoint(x: point.x - position.x, y: point.y - position.y)
        guard hypot(local.x, local.y) <= activationRadius else { return false }
        moveKnob(to: local)
        return true
    }

    /// Update the knob/vector from a drag at `point` (parent space).
    func drag(to point: CGPoint) {
        moveKnob(to: CGPoint(x: point.x - position.x, y: point.y - position.y))
    }

    /// Release: spring the knob home and clear the input.
    func release() {
        vector = .zero
        knob.removeAllActions()
        let home = SKAction.move(to: .zero, duration: 0.12)
        home.timingMode = .easeOut
        knob.run(home)
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
        knob.removeAllActions()
        knob.position = CGPoint(x: ux * clamped, y: uy * clamped)
        vector = CGVector(dx: ux * (clamped / baseRadius),
                          dy: uy * (clamped / baseRadius))
    }
}

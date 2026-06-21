//
//  Joystick.swift
//  Abysm
//
//  On-screen analog stick (bottom-left), now pixel-art: a hard pixel-circle
//  ring base and a filled pixel-disc knob, with the knob snapped to the pixel
//  grid. `vector` is direction × magnitude in [-1, 1] per axis (+y = up).
//

import SpriteKit

final class Joystick: SKNode {

    let baseRadius: CGFloat = 60
    private let knobRadius: CGFloat = 30
    var activationRadius: CGFloat { baseRadius * 1.9 }

    private let base = SKSpriteNode()
    private let knob = SKSpriteNode()

    private(set) var vector: CGVector = .zero

    override init() {
        super.init()
        zPosition = GameConfig.Z.joystick
        let px = GameConfig.pixel

        let baseR = Int((baseRadius / px).rounded())
        base.texture = TextureFactory.pixelCircle(radius: baseR, ring: 2,
                                                  color: UIColor(white: 1, alpha: 0.5))
        base.size = CGSize(width: CGFloat(baseR * 2 + 2) * px, height: CGFloat(baseR * 2 + 2) * px)
        addChild(base)

        let knobR = Int((knobRadius / px).rounded())
        knob.texture = TextureFactory.pixelCircle(radius: knobR, color: Palette.rgb(150, 240, 235))
        knob.size = CGSize(width: CGFloat(knobR * 2 + 2) * px, height: CGFloat(knobR * 2 + 2) * px)
        addChild(knob)

        alpha = 0.85
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    func engage(at point: CGPoint) -> Bool {
        let local = CGPoint(x: point.x - position.x, y: point.y - position.y)
        guard hypot(local.x, local.y) <= activationRadius else { return false }
        run(.fadeAlpha(to: 1.0, duration: 0.06))
        moveKnob(to: local)
        return true
    }

    func drag(to point: CGPoint) {
        moveKnob(to: CGPoint(x: point.x - position.x, y: point.y - position.y))
    }

    func release() {
        vector = .zero
        knob.removeAllActions()
        knob.run(.move(to: .zero, duration: 0.1))
        run(.fadeAlpha(to: 0.85, duration: 0.15))
    }

    private func moveKnob(to local: CGPoint) {
        let dist = hypot(local.x, local.y)
        if dist < 0.0001 { knob.position = .zero; vector = .zero; return }
        let clamped = min(dist, baseRadius)
        let ux = local.x / dist, uy = local.y / dist
        let px = GameConfig.pixel
        knob.removeAction(forKey: "spring")
        // Snap the knob to the pixel grid so it stays crisp.
        knob.position = CGPoint(x: ((ux * clamped) / px).rounded() * px,
                                y: ((uy * clamped) / px).rounded() * px)
        vector = CGVector(dx: ux * (clamped / baseRadius), dy: uy * (clamped / baseRadius))
    }
}

//
//  Joystick.swift
//  Abysm
//
//  On-screen analog stick (bottom-left), pixel-art and high-contrast so it's
//  clearly visible over bright water: a dark base disc + bright ring, and a
//  bright knob with a dark outline. `vector` = direction × magnitude [-1,1],
//  +y = up. Knob snaps to the pixel grid.
//

import SpriteKit

final class Joystick: SKNode {

    let baseRadius: CGFloat = 62
    private let knobRadius: CGFloat = 30
    var activationRadius: CGFloat { baseRadius * 1.9 }

    private let baseFill = SKSpriteNode()
    private let baseRing = SKSpriteNode()
    private let knob = SKSpriteNode()
    private let knobOutline = SKSpriteNode()

    private(set) var vector: CGVector = .zero

    override init() {
        super.init()
        zPosition = GameConfig.Z.joystick
        let px = GameConfig.pixel
        let baseR = Int((baseRadius / px).rounded())
        let baseSize = CGSize(width: CGFloat(baseR * 2 + 2) * px, height: CGFloat(baseR * 2 + 2) * px)

        baseFill.texture = TextureFactory.pixelCircle(radius: baseR, color: Palette.rgb(8, 22, 48))
        baseFill.size = baseSize; baseFill.alpha = 0.5; baseFill.zPosition = 0
        addChild(baseFill)

        baseRing.texture = TextureFactory.pixelCircle(radius: baseR, ring: 2, color: Palette.rgb(190, 240, 238))
        baseRing.size = baseSize; baseRing.alpha = 0.9; baseRing.zPosition = 1
        addChild(baseRing)

        let knobR = Int((knobRadius / px).rounded())
        let knobSize = CGSize(width: CGFloat(knobR * 2 + 2) * px, height: CGFloat(knobR * 2 + 2) * px)
        knobOutline.texture = TextureFactory.pixelCircle(radius: knobR, color: Palette.rgb(6, 20, 44))
        knobOutline.size = knobSize; knobOutline.zPosition = 2
        addChild(knobOutline)
        knob.texture = TextureFactory.pixelCircle(radius: knobR - 1, color: Palette.rgb(120, 232, 230))
        knob.size = CGSize(width: CGFloat((knobR - 1) * 2 + 2) * px, height: CGFloat((knobR - 1) * 2 + 2) * px)
        knob.zPosition = 3
        addChild(knob)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    func engage(at point: CGPoint) -> Bool {
        let local = CGPoint(x: point.x - position.x, y: point.y - position.y)
        guard hypot(local.x, local.y) <= activationRadius else { return false }
        moveKnob(to: local)
        return true
    }

    func drag(to point: CGPoint) {
        moveKnob(to: CGPoint(x: point.x - position.x, y: point.y - position.y))
    }

    func release() {
        vector = .zero
        knob.run(.move(to: .zero, duration: 0.1))
        knobOutline.run(.move(to: .zero, duration: 0.1))
    }

    private func moveKnob(to local: CGPoint) {
        let dist = hypot(local.x, local.y)
        if dist < 0.0001 { knob.position = .zero; knobOutline.position = .zero; vector = .zero; return }
        let clamped = min(dist, baseRadius)
        let ux = local.x / dist, uy = local.y / dist
        let px = GameConfig.pixel
        let p = CGPoint(x: ((ux * clamped) / px).rounded() * px, y: ((uy * clamped) / px).rounded() * px)
        knob.position = p
        knobOutline.position = p
        vector = CGVector(dx: ux * (clamped / baseRadius), dy: uy * (clamped / baseRadius))
    }
}

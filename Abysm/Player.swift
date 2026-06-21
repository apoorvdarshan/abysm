//
//  Player.swift
//  Abysm
//
//  The swimmer. Drawn entirely from SpriteKit shapes (no art assets), driven
//  by a damped physics body for a slow, weightless, floaty feel. Steered by
//  touch: tap or drag sets a target the swimmer eases toward, then drifts to
//  a stop. Trails bubbles while moving and gently bobs while idle.
//

import SpriteKit

final class Player: SKNode {

    /// Visual container — orientation (heading rotation + left/right flip) is
    /// applied here, leaving the physics node itself unrotated.
    private let visual = SKNode()
    private let bubbles = Particles.bubbleTrail()

    /// Steering input from the joystick: direction + magnitude in [-1, 1] per
    /// axis (length ≤ 1). Zero = no thrust, so the swimmer coasts to a stop.
    private var thrust: CGVector = .zero
    /// Internal clock for the idle bob.
    private var clock: CGFloat = 0
    private var movingScale: CGFloat = 1   // current vertical flip (+1 / -1)

    override init() {
        super.init()
        zPosition = GameConfig.Z.player
        addChild(visual)
        buildBody()
        setupPhysics()

        bubbles.zPosition = GameConfig.Z.bubbles
        bubbles.position = CGPoint(x: 0, y: -2)
        addChild(bubbles)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    // MARK: Build the cartoon swimmer (facing +x by default)

    private func buildBody() {
        let skin     = Palette.rgb(255, 214, 170)
        let skinLine = Palette.rgb(206, 150, 110)
        let suit     = Palette.rgb(40, 70, 120)
        let suitLine = Palette.rgb(24, 44, 80)
        let fin      = Palette.rgb(60, 150, 170)
        let outline  = UIColor(white: 0.05, alpha: 0.35)

        // Back fins / flippers (drawn first so they sit behind the body).
        for dy in [CGFloat(6), -6] {
            let flipper = SKShapeNode(path: trianglePath(length: 22, width: 16))
            flipper.fillColor = fin
            flipper.strokeColor = outline
            flipper.lineWidth = 1
            flipper.position = CGPoint(x: -30, y: dy)
            flipper.zRotation = dy > 0 ? 0.25 : -0.25
            visual.addChild(flipper)
        }

        // Legs.
        for dy in [CGFloat(5), -5] {
            let leg = capsule(width: 26, height: 8, color: skin, line: skinLine)
            leg.position = CGPoint(x: -16, y: dy)
            leg.zRotation = dy > 0 ? 0.12 : -0.12
            visual.addChild(leg)
        }

        // Torso (swimsuit).
        let torso = capsule(width: 46, height: 22, color: suit, line: suitLine)
        torso.position = .zero
        visual.addChild(torso)

        // Forward-reaching arm.
        let arm = capsule(width: 28, height: 8, color: skin, line: skinLine)
        arm.position = CGPoint(x: 16, y: 9)
        arm.zRotation = 0.28
        visual.addChild(arm)

        // Head.
        let head = SKShapeNode(circleOfRadius: 11)
        head.fillColor = skin
        head.strokeColor = skinLine
        head.lineWidth = 1
        head.position = CGPoint(x: 27, y: 3)
        visual.addChild(head)

        // Swim mask / goggles.
        let mask = SKShapeNode(rectOf: CGSize(width: 12, height: 8), cornerRadius: 3)
        mask.fillColor = Palette.rgb(120, 220, 230).withAlphaComponent(0.9)
        mask.strokeColor = suitLine
        mask.lineWidth = 1
        mask.position = CGPoint(x: 32, y: 4)
        visual.addChild(mask)

        // Soft contact-shadow under the swimmer for a touch of depth.
        let shadow = SKShapeNode(ellipseOf: CGSize(width: 60, height: 26))
        shadow.fillColor = UIColor(white: 0, alpha: 0.10)
        shadow.strokeColor = .clear
        shadow.zPosition = -1
        visual.addChild(shadow)
    }

    /// Rounded-rectangle "capsule" helper.
    private func capsule(width: CGFloat, height: CGFloat, color: UIColor, line: UIColor) -> SKShapeNode {
        let node = SKShapeNode(rectOf: CGSize(width: width, height: height), cornerRadius: height / 2)
        node.fillColor = color
        node.strokeColor = line
        node.lineWidth = 1
        return node
    }

    /// A simple triangle path pointing in -x (used for fins behind the body).
    private func trianglePath(length: CGFloat, width: CGFloat) -> CGPath {
        let path = CGMutablePath()
        path.move(to: CGPoint(x: 0, y: 0))
        path.addLine(to: CGPoint(x: -length, y: width / 2))
        path.addLine(to: CGPoint(x: -length, y: -width / 2))
        path.closeSubpath()
        return path
    }

    // MARK: Physics

    private func setupPhysics() {
        let body = SKPhysicsBody(circleOfRadius: 22)
        body.affectedByGravity = false
        body.allowsRotation = false           // we orient the visual manually
        body.linearDamping = GameConfig.playerLinearDamping
        body.mass = GameConfig.playerMass
        body.friction = 0
        body.restitution = 0
        // No collisions in Phase 1 — the swimmer roams freely.
        body.categoryBitMask = 0
        body.collisionBitMask = 0
        body.contactTestBitMask = 0
        physicsBody = body
    }

    /// Let bubbles trail in world space instead of riding along with the body.
    func attachBubbleTarget(_ node: SKNode) {
        bubbles.targetNode = node
    }

    // MARK: Steering

    /// Set the joystick steering input (direction × magnitude, length ≤ 1).
    func setThrust(_ vector: CGVector) { thrust = vector }

    // MARK: Per-frame update

    func update(_ dt: CGFloat) {
        guard let body = physicsBody else { return }
        clock += dt

        // Swim in the joystick's direction; magnitude scales the thrust so a
        // small push glides and a full push drives hard. No input → coast.
        let mag = hypot(thrust.dx, thrust.dy)
        if mag > 0.05 {
            let f = GameConfig.playerAccel * body.mass
            body.applyForce(CGVector(dx: thrust.dx * f, dy: thrust.dy * f))
        }

        // Clamp to a comfortable top speed.
        var v = body.velocity
        let speed = hypot(v.dx, v.dy)
        if speed > GameConfig.playerMaxSpeed {
            let s = GameConfig.playerMaxSpeed / speed
            v = CGVector(dx: v.dx * s, dy: v.dy * s)
            body.velocity = v
        }

        keepInsideWorld(body)
        orient(velocity: body.velocity, speed: hypot(body.velocity.dx, body.velocity.dy))

        // More bubbles while swimming, a few while resting.
        bubbles.particleBirthRate = speed > 36 ? 24 : 3
    }

    /// Face the direction of travel; flip vertically when heading left so the
    /// swimmer stays upright instead of going belly-up. While idle, level out
    /// and add a gentle vertical bob.
    private func orient(velocity v: CGVector, speed: CGFloat) {
        if speed > GameConfig.orientSpeedThreshold {
            movingScale = v.dx < 0 ? -1 : 1
            visual.yScale = movingScale
            visual.zRotation = atan2(v.dy, v.dx)
            visual.position.y = visual.position.y * 0.85   // settle bob back to 0
        } else {
            // Idle: KEEP the last facing (yScale), ease the pitch back to level
            // for that facing (0 when facing right, π when facing left — paired
            // with yScale = -1 that reads as upright), and add a gentle bob.
            visual.yScale = movingScale
            let level: CGFloat = movingScale < 0 ? .pi : 0
            visual.zRotation = lerpAngle(visual.zRotation, level, 0.12)
            visual.position.y = sin(clock * 1.6) * 2.5
        }
    }

    /// Soft clamp inside the world bounds, killing the outward velocity so the
    /// swimmer rests against the edge rather than jittering.
    private func keepInsideWorld(_ body: SKPhysicsBody) {
        let minX = -GameConfig.worldHalfWidth + 30
        let maxX =  GameConfig.worldHalfWidth - 30
        let minY =  GameConfig.worldFloor + 30
        let maxY: CGFloat = 30                 // may peek just above the surface

        if position.x < minX { position.x = minX; if body.velocity.dx < 0 { body.velocity.dx = 0 } }
        if position.x > maxX { position.x = maxX; if body.velocity.dx > 0 { body.velocity.dx = 0 } }
        if position.y < minY { position.y = minY; if body.velocity.dy < 0 { body.velocity.dy = 0 } }
        if position.y > maxY { position.y = maxY; if body.velocity.dy > 0 { body.velocity.dy = 0 } }
    }
}

//
//  Player.swift
//  Abysm
//
//  The swimmer — now a PixelLab-generated pixel-art sprite (nearest-neighbor,
//  transparent) driven by a damped physics body for the slow, floaty feel and
//  steered by the on-screen joystick. Faces its heading (horizontal flip +
//  pitch), with a gentle pixel-snapped idle bob.
//

import SpriteKit

final class Player: SKNode {

    /// Visual root — heading rotation, left/right flip, and idle bob apply here.
    private let bodyRoot = SKNode()
    private let sprite: SKSpriteNode
    private let bubbles = Particles.bubbleTrail()

    private var thrust: CGVector = .zero
    private var clock: CGFloat = 0
    private var movingScale: CGFloat = 1   // vertical flip used to stay upright when facing left

    override init() {
        let frames: [SKTexture] = (0..<4).map {
            let t = SKTexture(imageNamed: "diver\($0)"); t.filteringMode = .nearest; return t
        }
        sprite = SKSpriteNode(texture: frames[0])
        sprite.size = CGSize(width: 184, height: 184)   // detailed 128px frames, larger presence
        super.init()
        zPosition = GameConfig.Z.player

        bodyRoot.addChild(sprite)
        // Loop the flutter-kick swim cycle.
        sprite.run(.repeatForever(.animate(with: frames, timePerFrame: 0.14,
                                           resize: false, restore: true)), withKey: "swim")
        addChild(bodyRoot)
        setupPhysics()

        bubbles.zPosition = GameConfig.Z.bubbles
        bubbles.position = CGPoint(x: -10, y: 0)
        addChild(bubbles)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    // MARK: Physics

    private func setupPhysics() {
        let body = SKPhysicsBody(circleOfRadius: 34)
        body.affectedByGravity = false
        body.allowsRotation = false
        body.linearDamping = GameConfig.playerLinearDamping
        body.mass = GameConfig.playerMass
        body.friction = 0
        body.restitution = 0
        body.categoryBitMask = 0
        body.collisionBitMask = 0
        body.contactTestBitMask = 0
        physicsBody = body
    }

    func attachBubbleTarget(_ node: SKNode) { bubbles.targetNode = node }

    // MARK: Steering

    func setThrust(_ vector: CGVector) { thrust = vector }

    // MARK: Per-frame update

    func update(_ dt: CGFloat) {
        guard let body = physicsBody else { return }
        clock += dt

        let mag = hypot(thrust.dx, thrust.dy)
        if mag > 0.05 {
            let f = GameConfig.playerAccel * body.mass
            body.applyForce(CGVector(dx: thrust.dx * f, dy: thrust.dy * f))
        }

        var v = body.velocity
        let speed = hypot(v.dx, v.dy)
        if speed > GameConfig.playerMaxSpeed {
            let s = GameConfig.playerMaxSpeed / speed
            v = CGVector(dx: v.dx * s, dy: v.dy * s)
            body.velocity = v
        }

        keepInsideWorld(body)
        orient(velocity: body.velocity, speed: speed)
        bubbles.particleBirthRate = speed > 36 ? 22 : 3
    }

    /// Face the heading; flip vertically when facing left so the diver stays
    /// upright. Hysteresis on dx so near-vertical swims don't mirror-flip.
    private func orient(velocity v: CGVector, speed: CGFloat) {
        if speed > GameConfig.orientSpeedThreshold {
            if v.dx < -40 { movingScale = -1 } else if v.dx > 40 { movingScale = 1 }
            bodyRoot.zRotation = atan2(v.dy, v.dx)
            bodyRoot.position.y *= 0.8
        } else {
            let level: CGFloat = movingScale < 0 ? .pi : 0
            bodyRoot.zRotation = lerpAngle(bodyRoot.zRotation, level, 0.12)
            bodyRoot.position.y = (sin(clock * 1.6) * 3).rounded()   // pixel-snapped bob
        }
        bodyRoot.yScale = movingScale
    }

    private func keepInsideWorld(_ body: SKPhysicsBody) {
        let minX = -GameConfig.worldHalfWidth + 40
        let maxX =  GameConfig.worldHalfWidth - 40
        let minY =  GameConfig.worldFloor + 40
        let maxY: CGFloat = 30

        if position.x < minX { position.x = minX; if body.velocity.dx < 0 { body.velocity.dx = 0 } }
        if position.x > maxX { position.x = maxX; if body.velocity.dx > 0 { body.velocity.dx = 0 } }
        if position.y < minY { position.y = minY; if body.velocity.dy < 0 { body.velocity.dy = 0 } }
        if position.y > maxY { position.y = maxY; if body.velocity.dy > 0 { body.velocity.dy = 0 } }
    }
}

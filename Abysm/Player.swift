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
    /// Soft warm glow around the swimmer — a real (non-pixel) lamp light. The
    /// wide reveal of the dark deep is handled by the scene's darkness veil.
    private let lampGlow = SKSpriteNode(texture: TextureFactory.radialGlow(
        diameter: 256,
        inner: Palette.rgb(255, 243, 198, 0.5),
        outer: Palette.rgb(255, 243, 198, 0)))

    private var thrust: CGVector = .zero
    /// Speed/force multiplier from the boost buttons (1 = normal).
    var boostFactor: CGFloat = 1
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

        // Warm lamp glow (additive) — sits just ahead of the diver and brightens
        // the water right around the swimmer. Behind the body so it haloes it.
        lampGlow.size = CGSize(width: 120, height: 120)   // small halo only — the blue reveal does the seeing
        lampGlow.position = CGPoint(x: 18, y: -2)
        lampGlow.blendMode = .add
        lampGlow.zPosition = -0.5
        lampGlow.alpha = 0          // grows with depth (set by the scene)
        bodyRoot.addChild(lampGlow)

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

    /// Current speed (points/sec) — the camera uses it to tighten its follow at
    /// high speed so the fast-moving diver stays framed instead of outrunning it.
    /// (Named `currentSpeed` to avoid SKNode's own `speed` action multiplier.)
    var currentSpeed: CGFloat { hypot(physicsBody?.velocity.dx ?? 0, physicsBody?.velocity.dy ?? 0) }

    func setFlashlight(_ on: Bool) { lampGlow.isHidden = !on }

    /// Fade the lamp glow in with depth so it never washes the bright surface.
    func setLampIntensity(_ k: CGFloat) { lampGlow.alpha = k }

    // MARK: Steering

    func setThrust(_ vector: CGVector) { thrust = vector }

    // MARK: Per-frame update

    func update(_ dt: CGFloat) {
        guard let body = physicsBody else { return }
        clock += dt

        let inAir = position.y > 0
        let mag = hypot(thrust.dx, thrust.dy)
        if inAir {
            // Breach: ballistic arc — gravity pulls back, little drag, no swimming.
            body.linearDamping = GameConfig.airDamping
            body.applyForce(CGVector(dx: 0, dy: -GameConfig.breachGravity * body.mass))
            if body.velocity.dy > GameConfig.maxBreachUpSpeed {   // keep the hop modest
                body.velocity.dy = GameConfig.maxBreachUpSpeed
            }
        } else {
            body.linearDamping = GameConfig.playerLinearDamping
            if mag > 0.05 {
                let f = GameConfig.playerAccel * body.mass * boostFactor
                body.applyForce(CGVector(dx: thrust.dx * f, dy: thrust.dy * f))
            }
        }

        var v = body.velocity
        let speed = hypot(v.dx, v.dy)
        if !inAir {
            let cap = GameConfig.playerMaxSpeed * boostFactor   // no cap in the air, let it leap
            if speed > cap {
                let s = cap / speed
                v = CGVector(dx: v.dx * s, dy: v.dy * s)
                body.velocity = v
            }
        }

        keepInsideWorld(body)
        orient(velocity: body.velocity, speed: speed)
        bubbles.particleBirthRate = (!inAir && speed > 36) ? 22 : 3
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
        // Horizontal is endless — only the vertical column (surface ↔ trench
        // floor) is bounded.
        let minY =  GameConfig.worldFloor + 40
        let maxY = GameConfig.skyTop - 60   // high ceiling so the diver can breach
        if position.y < minY { position.y = minY; if body.velocity.dy < 0 { body.velocity.dy = 0 } }
        if position.y > maxY { position.y = maxY; if body.velocity.dy > 0 { body.velocity.dy = 0 } }
    }
}

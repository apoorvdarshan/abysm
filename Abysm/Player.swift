//
//  Player.swift
//  Abysm
//
//  The swimmer. Still drawn from SpriteKit shapes (no art assets), but with
//  gradient-shaded body parts, bright rim highlights, a localized bloom glow,
//  and an animated flutter-kick swim cycle. Driven by a damped physics body
//  for a slow, weightless, floaty feel and steered by the on-screen joystick.
//

import SpriteKit

final class Player: SKNode {

    /// Visual root. Orientation — heading rotation, left/right flip, idle bob —
    /// is applied here, leaving the physics node itself unrotated.
    private let bodyRoot = SKNode()
    private let bubbles = Particles.bubbleTrail()

    // Animated limbs.
    private let legFront = SKNode()
    private let legBack = SKNode()
    private let armFront = SKNode()
    private let armBack = SKNode()
    private let armRestAngle: CGFloat = -0.18
    private let armBackRestAngle: CGFloat = 2.7

    /// Steering input from the joystick (direction × magnitude, length ≤ 1).
    private var thrust: CGVector = .zero
    private var clock: CGFloat = 0        // idle-bob clock
    private var swimPhase: CGFloat = 0    // flutter-kick phase
    private var movingScale: CGFloat = 1  // current vertical flip (+1 / -1)

    override init() {
        super.init()
        zPosition = GameConfig.Z.player

        addChild(bodyRoot)
        addGlowAura()
        buildBody()
        setupPhysics()

        bubbles.zPosition = GameConfig.Z.bubbles
        bubbles.position = CGPoint(x: 0, y: -2)
        addChild(bubbles)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    // MARK: Gradient textures (lit from above)

    private static let suitTex = TextureFactory.verticalGradient(
        size: CGSize(width: 8, height: 64),
        stops: [(Palette.rgb(78, 138, 192), 0.0), (Palette.rgb(26, 44, 88), 1.0)])
    private static let skinTex = TextureFactory.verticalGradient(
        size: CGSize(width: 8, height: 64),
        stops: [(Palette.rgb(255, 226, 192), 0.0), (Palette.rgb(228, 170, 120), 1.0)])
    private static let capTex = TextureFactory.verticalGradient(
        size: CGSize(width: 8, height: 64),
        stops: [(Palette.rgb(54, 92, 150), 0.0), (Palette.rgb(22, 36, 74), 1.0)])

    /// A cheap static additive glow behind the diver (replaces a per-frame
    /// CIBloom, which re-rendered the animated body offscreen every frame).
    private func addGlowAura() {
        let glow = SKSpriteNode(texture: TextureFactory.radialGlow(
            diameter: 130,
            inner: Palette.rgb(175, 242, 240).withAlphaComponent(0.5),
            outer: Palette.rgb(175, 242, 240).withAlphaComponent(0)))
        glow.blendMode = .add
        glow.alpha = 0.32
        glow.zPosition = -5
        bodyRoot.addChild(glow)
    }

    // MARK: Build the swimmer (facing +x by default)

    private func buildBody() {
        let finColor = Palette.rgb(48, 150, 172).withAlphaComponent(0.9)
        let rim = Palette.rgb(190, 252, 246)

        // Soft contact shadow underneath.
        let shadow = SKShapeNode(ellipseOf: CGSize(width: 66, height: 24))
        shadow.fillColor = UIColor(white: 0, alpha: 0.10)
        shadow.strokeColor = .clear
        shadow.position = CGPoint(x: -4, y: -13)
        shadow.zPosition = -2
        bodyRoot.addChild(shadow)

        // Far (back) limbs first so they sit behind the torso.
        configureLeg(legBack, finColor: finColor, near: false)
        legBack.position = CGPoint(x: -20, y: 4)
        legBack.zPosition = -1
        bodyRoot.addChild(legBack)

        configureArm(armBack, near: false)
        armBack.position = CGPoint(x: 14, y: 2)
        armBack.zRotation = armBackRestAngle
        armBack.zPosition = -1
        bodyRoot.addChild(armBack)

        // Torso (wetsuit) with a gradient + bright rim along the top.
        let torso = gradientCapsule(width: 48, height: 23, texture: Self.suitTex)
        bodyRoot.addChild(torso)

        let torsoRim = SKShapeNode(rectOf: CGSize(width: 40, height: 4), cornerRadius: 2)
        torsoRim.fillColor = rim.withAlphaComponent(0.55)
        torsoRim.strokeColor = .clear
        torsoRim.blendMode = .add
        torsoRim.position = CGPoint(x: -1, y: 9)
        bodyRoot.addChild(torsoRim)

        // Near (front) limbs over the torso.
        configureLeg(legFront, finColor: finColor, near: true)
        legFront.position = CGPoint(x: -20, y: -3)
        bodyRoot.addChild(legFront)

        configureArm(armFront, near: true)
        armFront.position = CGPoint(x: 16, y: 4)
        armFront.zRotation = armRestAngle
        bodyRoot.addChild(armFront)

        // Head + swim cap + mask.
        let head = SKShapeNode(circleOfRadius: 11)
        head.fillTexture = Self.skinTex
        head.fillColor = .white
        head.strokeColor = .clear
        head.position = CGPoint(x: 28, y: 2)
        bodyRoot.addChild(head)

        let cap = SKShapeNode(path: capPath(radius: 12))
        cap.fillTexture = Self.capTex
        cap.fillColor = .white
        cap.strokeColor = .clear
        cap.position = CGPoint(x: 28, y: 2)
        bodyRoot.addChild(cap)

        let capRim = SKShapeNode(path: capRimPath(radius: 12))
        capRim.fillColor = .clear
        capRim.strokeColor = rim.withAlphaComponent(0.5)
        capRim.lineWidth = 1.5
        capRim.blendMode = .add
        capRim.lineCap = .round
        capRim.position = CGPoint(x: 28, y: 2)
        bodyRoot.addChild(capRim)

        // Snorkel: thin tube up & back from the side of the head.
        let snorkel = SKShapeNode(rectOf: CGSize(width: 4, height: 22), cornerRadius: 2)
        snorkel.fillColor = Palette.rgb(245, 222, 90)
        snorkel.strokeColor = .clear
        snorkel.position = CGPoint(x: 33, y: 13)
        snorkel.zRotation = 0.18
        snorkel.zPosition = -1
        bodyRoot.addChild(snorkel)

        // Dive mask — bright cyan, glints under bloom.
        let mask = SKShapeNode(rectOf: CGSize(width: 13, height: 9), cornerRadius: 3.5)
        mask.fillColor = Palette.rgb(140, 232, 240)
        mask.strokeColor = Palette.rgb(24, 44, 80)
        mask.lineWidth = 1
        mask.position = CGPoint(x: 33, y: 3)
        bodyRoot.addChild(mask)

        let glint = SKShapeNode(rectOf: CGSize(width: 4, height: 4), cornerRadius: 1.5)
        glint.fillColor = UIColor(white: 1, alpha: 0.9)
        glint.strokeColor = .clear
        glint.blendMode = .add
        glint.position = CGPoint(x: 35, y: 5)
        bodyRoot.addChild(glint)

        addCausticHighlights()
    }

    /// Soft surface-light dapples that slowly drift and pulse across the body —
    /// reads as caustic light playing on the swimmer (and glows via the bloom).
    private func addCausticHighlights() {
        let tex = TextureFactory.radialGlow(
            diameter: 36,
            inner: Palette.rgb(210, 255, 250).withAlphaComponent(0.7),
            outer: Palette.rgb(210, 255, 250).withAlphaComponent(0))
        let spots: [(CGPoint, TimeInterval)] = [(CGPoint(x: 2, y: 4), 0.0), (CGPoint(x: 20, y: -2), 1.1)]
        for (origin, phase) in spots {
            let spot = SKSpriteNode(texture: tex)
            spot.blendMode = .add
            spot.alpha = 0
            spot.position = origin
            spot.zPosition = 4
            bodyRoot.addChild(spot)

            let pulse = SKAction.sequence([
                .fadeAlpha(to: 0.4, duration: 1.4),
                .fadeAlpha(to: 0.0, duration: 1.6)
            ])
            pulse.timingMode = .easeInEaseOut
            let drift = SKAction.sequence([
                .moveBy(x: -14, y: 3, duration: 3.0),
                .moveBy(x: 14, y: -3, duration: 3.0)
            ])
            drift.timingMode = .easeInEaseOut
            spot.run(.sequence([.wait(forDuration: phase), .repeatForever(pulse)]))
            spot.run(.repeatForever(drift))
        }
    }

    // MARK: Limb builders

    private func configureLeg(_ leg: SKNode, finColor: UIColor, near: Bool) {
        let thigh = gradientCapsule(width: 26, height: 8, texture: Self.skinTex)
        thigh.position = CGPoint(x: -13, y: 0)
        thigh.alpha = near ? 1.0 : 0.9
        leg.addChild(thigh)

        let fin = SKShapeNode(path: finPath(length: 22, width: 17))
        fin.fillColor = finColor
        fin.strokeColor = UIColor(white: 1, alpha: 0.22)
        fin.lineWidth = 1
        fin.position = CGPoint(x: -25, y: 0)
        leg.addChild(fin)
    }

    private func configureArm(_ arm: SKNode, near: Bool) {
        let limb = gradientCapsule(width: 28, height: 8, texture: Self.skinTex)
        limb.position = CGPoint(x: 14, y: 0)
        limb.alpha = near ? 1.0 : 0.85
        arm.addChild(limb)
    }

    // MARK: Shape helpers

    private func gradientCapsule(width: CGFloat, height: CGFloat, texture: SKTexture) -> SKShapeNode {
        let n = SKShapeNode(rectOf: CGSize(width: width, height: height), cornerRadius: height / 2)
        n.fillTexture = texture
        n.fillColor = .white
        n.strokeColor = .clear
        n.lineWidth = 0
        return n
    }

    /// A flipper: a soft elongated blade pointing in -x.
    private func finPath(length: CGFloat, width: CGFloat) -> CGPath {
        let p = CGMutablePath()
        p.move(to: CGPoint(x: 2, y: 0))
        p.addQuadCurve(to: CGPoint(x: -length, y: width / 2),
                       control: CGPoint(x: -length * 0.5, y: width * 0.30))
        p.addQuadCurve(to: CGPoint(x: -length, y: -width / 2),
                       control: CGPoint(x: -length * 0.9, y: 0))
        p.addQuadCurve(to: CGPoint(x: 2, y: 0),
                       control: CGPoint(x: -length * 0.5, y: -width * 0.30))
        p.closeSubpath()
        return p
    }

    /// Top hemisphere of the head, used as the swim cap.
    private func capPath(radius: CGFloat) -> CGPath {
        let p = CGMutablePath()
        p.addArc(center: .zero, radius: radius, startAngle: 0, endAngle: .pi, clockwise: false)
        p.closeSubpath()
        return p
    }

    private func capRimPath(radius: CGFloat) -> CGPath {
        let p = CGMutablePath()
        p.addArc(center: .zero, radius: radius - 1, startAngle: 0.15, endAngle: .pi - 0.15, clockwise: false)
        return p
    }

    // MARK: Physics

    private func setupPhysics() {
        let body = SKPhysicsBody(circleOfRadius: 22)
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
        animateSwim(dt: dt, speed: speed)

        bubbles.particleBirthRate = speed > 36 ? 24 : 3
    }

    /// Flutter-kick + gentle arm stroke, faster the harder the swimmer moves.
    private func animateSwim(dt: CGFloat, speed: CGFloat) {
        let frac = min(speed / GameConfig.playerMaxSpeed, 1)
        swimPhase += dt * (5.0 + frac * 9.0)
        let kick = sin(swimPhase)
        let amp = 0.16 + frac * 0.40
        legFront.zRotation = kick * amp
        legBack.zRotation = -kick * amp
        armFront.zRotation = armRestAngle + sin(swimPhase * 0.5 + 1.0) * (0.08 + frac * 0.14)
        armBack.zRotation = armBackRestAngle - sin(swimPhase * 0.5) * 0.07
    }

    /// Face the direction of travel; flip vertically when heading left so the
    /// swimmer stays upright. While idle, level out the pitch and gently bob.
    private func orient(velocity v: CGVector, speed: CGFloat) {
        if speed > GameConfig.orientSpeedThreshold {
            // Only flip facing on a clear horizontal heading; keep the last
            // facing while moving near-vertical so joystick wobble around the
            // vertical axis doesn't mirror-snap the whole body every frame.
            if v.dx < -40 { movingScale = -1 } else if v.dx > 40 { movingScale = 1 }
            bodyRoot.zRotation = atan2(v.dy, v.dx)
            bodyRoot.position.y *= 0.85
        } else {
            let level: CGFloat = movingScale < 0 ? .pi : 0
            bodyRoot.zRotation = lerpAngle(bodyRoot.zRotation, level, 0.12)
            bodyRoot.position.y = sin(clock * 1.6) * 2.5
        }
        // Gentle, volume-preserving breathing keeps the diver feeling alive.
        let breath = sin(clock * 1.3) * 0.02
        bodyRoot.xScale = 1 - breath * 0.5
        bodyRoot.yScale = movingScale * (1 + breath)
    }

    private func keepInsideWorld(_ body: SKPhysicsBody) {
        let minX = -GameConfig.worldHalfWidth + 30
        let maxX =  GameConfig.worldHalfWidth - 30
        let minY =  GameConfig.worldFloor + 30
        let maxY: CGFloat = 30

        if position.x < minX { position.x = minX; if body.velocity.dx < 0 { body.velocity.dx = 0 } }
        if position.x > maxX { position.x = maxX; if body.velocity.dx > 0 { body.velocity.dx = 0 } }
        if position.y < minY { position.y = minY; if body.velocity.dy < 0 { body.velocity.dy = 0 } }
        if position.y > maxY { position.y = maxY; if body.velocity.dy > 0 { body.velocity.dy = 0 } }
    }
}

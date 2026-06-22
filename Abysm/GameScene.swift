//
//  GameScene.swift
//  Abysm
//
//  ABYSM — Phase 1: The Surface.
//
//  Assembles the surface world (sky, sun, god rays, caustics, wavy surface,
//  water column), the swimmer, an all-directions follow camera, the ambient
//  plankton, the whole-screen blue tint, the depth-darkening overlay, and the
//  depth HUD. Drives swimming input and the per-frame depth response.
//

import SpriteKit
import GameController

final class GameScene: SKScene {

    // World
    private let oceanSurface = OceanSurface(width: GameConfig.worldHalfWidth * 2 + 400)
    private let player = Player()
    private let creatureField = CreatureField()
    private let landmarkField = LandmarkField()
    // Surface backdrop — followed horizontally so the world feels endless.
    private var skyNode = SKNode()
    private var sunNode = SKNode()
    private var causticsNode = SKNode()

    // Camera & screen-space overlays (children of the camera)
    private let cameraNode = SKCameraNode()
    /// Full-screen water color driven by depth (replaces a giant gradient
    /// texture — the descent reaches ~10,935 m, far too deep to texture).
    private let waterBackground = SKSpriteNode(color: .black, size: CGSize(width: 2800, height: 3600))
    private let plankton = Particles.plankton()
    private let marineSnow = Particles.marineSnow()
    private let hud = DepthHUD()
    private let joystick = Joystick()
    private let boostBtn = HoldButton(radius: 32, glyph: ">>", fontSize: 12, color: Palette.rgb(40, 150, 168))
    private let turboBtn = HoldButton(radius: 36, glyph: ">>>", fontSize: 12, color: Palette.rgb(225, 130, 50))
    private let flashBtn = HoldButton(radius: 28, glyph: "*", fontSize: 16, color: Palette.rgb(232, 196, 64))
    private let surfaceBtn = HoldButton(radius: 26, glyph: "", fontSize: 1, color: Palette.rgb(92, 196, 226))
    private var flashlightOn = true

    // Zone-entry / "did you know" banner (a brief centered toast).
    private let banner = SKNode()
    private let bannerBorder = SKSpriteNode()
    private let bannerPlate = SKSpriteNode()
    private let bannerTitle = SKLabelNode(fontNamed: "PressStart2P-Regular")
    private let bannerBody = SKLabelNode(fontNamed: "PressStart2P-Regular")
    private var lastZoneName = ""
    private var lastDepthMeters: CGFloat = 0
    private var shownTrivia: Set<Int> = []

    /// "You are now deeper than X" comparisons, shown once as you pass each depth.
    private static let trivia: [(depth: CGFloat, text: String)] = [
        (30,  "Deeper than a blue whale is long (30 m) — the largest animal ever"),
        (93,  "Deeper than the Statue of Liberty is tall (93 m)"),
        (96,  "Deeper than Big Ben's Elizabeth Tower (96 m)"),
        (111, "Deeper than the Saturn V rocket is tall (111 m)"),
        (147, "Deeper than the Great Pyramid of Giza (147 m)"),
        (169, "Deeper than the Washington Monument (169 m)"),
        (227, "Deeper than a Golden Gate Bridge tower (227 m)"),
        (330, "Deeper than the Eiffel Tower is tall (330 m)"),
        (443, "Deeper than the Empire State Building (443 m)"),
        (452, "Deeper than the Petronas Towers (452 m)"),
        (828, "Deeper than the Burj Khalifa (828 m) — the tallest building"),
    ]

    /// Depth darkness + headlamp reveal: a full-screen veil that's clear through
    /// a soft disc around the diver (wide when the lamp is on, tiny when off)
    /// and dark beyond. Its opacity fades in with depth.
    private let darkness = SKSpriteNode()
    private let veilOn  = TextureFactory.darknessVeil(holeFrac: 0.18, featherFrac: 0.12, tint: Palette.rgb(1, 4, 12))
    private let veilOff = TextureFactory.darknessVeil(holeFrac: 0.05, featherFrac: 0.07, tint: Palette.rgb(1, 4, 12))

    /// True while the "rise to surface" button is whisking the diver up.
    private var ascending = false

    private var lastUpdateTime: TimeInterval = 0
    // Touches currently controlling each control (multi-touch).
    private var stickTouch: UITouch?
    private var boostTouch: UITouch?
    private var turboTouch: UITouch?
    private var surfaceTouch: UITouch?

    /// Token for the game-controller connect observer.
    private var controllerObserver: NSObjectProtocol?

    // MARK: Scene setup

    override func didMove(to view: SKView) {
        backgroundColor = Palette.deepBackground
        physicsWorld.gravity = .zero

        buildWorld()
        buildCamera()
        buildPlayer()

        cameraNode.position = player.position
        layout()
        // Re-run once UIKit has finished its first layout pass and the real
        // safe-area insets are available (they can read 0 inside didMove).
        DispatchQueue.main.async { [weak self] in self?.layout() }

        setupControllers()
        playIntroFade()
    }

    deinit {
        if let o = controllerObserver { NotificationCenter.default.removeObserver(o) }
    }

    /// Gentle fade-in from black so the scene reveals softly on launch.
    private func playIntroFade() {
        let fade = SKSpriteNode(color: .black, size: CGSize(width: 2600, height: 3600))
        fade.zPosition = GameConfig.Z.intro
        cameraNode.addChild(fade)
        fade.run(.sequence([
            .wait(forDuration: 0.15),
            .fadeOut(withDuration: 0.9),
            .removeFromParent()
        ]))
    }

    private func buildWorld() {
        skyNode = Environment.makeSky()
        sunNode = Environment.makeSun()
        causticsNode = Environment.makeCaustics()
        addChild(skyNode)
        addChild(sunNode)
        addChild(causticsNode)
        addChild(oceanSurface)
        creatureField.populate()
        addChild(creatureField)
        landmarkField.populate()
        addChild(landmarkField)
    }

    private func buildCamera() {
        addChild(cameraNode)
        camera = cameraNode

        // Behind everything (incl. the world sky), filling the screen.
        waterBackground.zPosition = -200
        cameraNode.addChild(waterBackground)

        // Darkness veil — above the world/creatures, below the HUD. Clear disc
        // (the lamp's reach) follows the diver; opacity grows with depth.
        darkness.size = CGSize(width: 4200, height: 4200)
        darkness.texture = flashlightOn ? veilOn : veilOff
        darkness.zPosition = GameConfig.Z.darkness
        darkness.alpha = 0
        cameraNode.addChild(darkness)

        marineSnow.zPosition = GameConfig.Z.plankton - 1
        cameraNode.addChild(marineSnow)
        marineSnow.targetNode = self
        marineSnow.advanceSimulationTime(16)

        plankton.zPosition = GameConfig.Z.plankton
        cameraNode.addChild(plankton)
        // Release motes into world space so the camera glides past them
        // (parallax / suspended-in-water feel) instead of them riding the screen.
        plankton.targetNode = self
        plankton.advanceSimulationTime(12)   // pre-fill the screen so it isn't empty at launch

        cameraNode.addChild(hud)
        cameraNode.addChild(joystick)
        cameraNode.addChild(boostBtn)
        cameraNode.addChild(turboBtn)
        cameraNode.addChild(flashBtn)
        flashBtn.setPressed(flashlightOn)   // reflect the default-on state

        // "Rise to the surface" button (top-left) with a pixel up-arrow glyph.
        let upArrow = SKSpriteNode(texture: TextureFactory.pixelTriangleUp(half: 7, color: .white))
        upArrow.size = CGSize(width: 18, height: 15)
        upArrow.zPosition = 3
        surfaceBtn.addChild(upArrow)
        cameraNode.addChild(surfaceBtn)

        // Zone / trivia banner (centered toast, hidden until shown).
        bannerBorder.zPosition = 0
        bannerPlate.color = Palette.rgb(9, 20, 44); bannerPlate.alpha = 0.92; bannerPlate.zPosition = 1
        for l in [bannerTitle, bannerBody] {
            l.horizontalAlignmentMode = .center; l.verticalAlignmentMode = .top; l.zPosition = 2
        }
        bannerTitle.fontSize = 13
        bannerBody.fontSize = 8
        bannerBody.numberOfLines = 0
        bannerBody.lineBreakMode = .byWordWrapping
        banner.addChild(bannerBorder); banner.addChild(bannerPlate)
        banner.addChild(bannerTitle); banner.addChild(bannerBody)
        banner.zPosition = GameConfig.Z.hud + 1
        banner.alpha = 0
        cameraNode.addChild(banner)
    }

    /// Show a brief centered banner (zone entry or a depth fact), then fade it out.
    private func showBanner(title: String, body: String, accent: UIColor) {
        let w: CGFloat = 380, pad: CGFloat = 13
        bannerTitle.text = title
        bannerBody.text = body
        bannerBody.preferredMaxLayoutWidth = w - 30
        bannerTitle.fontColor = accent
        bannerBody.fontColor = Palette.rgb(214, 226, 236)

        let th = title.isEmpty ? 0 : bannerTitle.frame.height
        let gap: CGFloat = title.isEmpty ? 0 : 7
        let bh = bannerBody.frame.height
        let totalH = pad + th + gap + bh + pad
        bannerTitle.position = CGPoint(x: 0, y: totalH / 2 - pad)
        bannerBody.position = CGPoint(x: 0, y: totalH / 2 - pad - th - gap)
        bannerPlate.size = CGSize(width: w, height: totalH)
        bannerBorder.color = accent
        bannerBorder.alpha = 0.55
        bannerBorder.size = CGSize(width: w + 6, height: totalH + 6)

        banner.removeAllActions()
        banner.alpha = 0
        banner.run(.sequence([.fadeAlpha(to: 1, duration: 0.4),
                              .wait(forDuration: 2.6),
                              .fadeAlpha(to: 0, duration: 0.8)]))
    }

    private func buildPlayer() {
        player.position = CGPoint(x: 0, y: GameConfig.playerStartY)
        addChild(player)
        player.attachBubbleTarget(self)   // bubbles trail in world space
    }

    // MARK: Layout (re-run whenever the view size changes)

    private func layout() {
        guard camera != nil else { return }
        let viewport = size
        // Enforce a minimum so the top row clears the camera housing. (Landscape
        // puts the Dynamic Island on a side edge, so the top can sit fairly high.)
        let topInset = max(view?.safeAreaInsets.top ?? 0, 40)

        hud.position = CGPoint(x: 0, y: viewport.height / 2 - topInset - 14)
        banner.position = CGPoint(x: 0, y: viewport.height * 0.16)
        plankton.particlePositionRange = CGVector(dx: viewport.width + 80,
                                                  dy: viewport.height + 80)
        marineSnow.particlePositionRange = CGVector(dx: viewport.width + 120,
                                                    dy: viewport.height + 120)

        // Joystick pinned to the bottom-left, clear of the landscape notch.
        let safeBottom = view?.safeAreaInsets.bottom ?? 0
        let safeLeft = view?.safeAreaInsets.left ?? 0
        joystick.position = CGPoint(
            x: -viewport.width / 2 + safeLeft + joystick.baseRadius + 28,
            y: -viewport.height / 2 + safeBottom + joystick.baseRadius + 24)

        // The four action buttons sit in a controller-style diamond, bottom-right
        // (top = rise · bottom = lamp · left = boost · right = turbo), mirroring
        // the joystick and freeing the top + center of the screen.
        let safeRight = view?.safeAreaInsets.right ?? 0
        let arm: CGFloat = 54   // diamond arm length from the cluster center
        let ccx = viewport.width / 2 - safeRight - turboBtn.radius - arm - 16
        let ccy = -viewport.height / 2 + safeBottom + flashBtn.radius + arm + 16
        surfaceBtn.position = CGPoint(x: ccx, y: ccy + arm)
        flashBtn.position   = CGPoint(x: ccx, y: ccy - arm)
        boostBtn.position   = CGPoint(x: ccx - arm, y: ccy)
        turboBtn.position   = CGPoint(x: ccx + arm, y: ccy)
    }

    override func didChangeSize(_ oldSize: CGSize) {
        super.didChangeSize(oldSize)
        layout()
    }

    // MARK: Touch steering (virtual joystick, bottom-left)

    override func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent?) {
        for t in touches {
            let p = t.location(in: cameraNode)
            if flashBtn.hit(p) { toggleFlashlight(); continue }   // tap to toggle the headlamp
            if surfaceTouch == nil, surfaceBtn.hit(p) {           // whisk up to the surface
                surfaceTouch = t; surfaceBtn.setPressed(true); beginAscent()
                continue
            }
            if stickTouch == nil, joystick.engage(at: p) { stickTouch = t; ascending = false; continue }
            if turboTouch == nil, turboBtn.hit(p) { turboTouch = t; turboBtn.setPressed(true); continue }
            if boostTouch == nil, boostBtn.hit(p) { boostTouch = t; boostBtn.setPressed(true); continue }
        }
    }

    override func touchesMoved(_ touches: Set<UITouch>, with event: UIEvent?) {
        if let st = stickTouch, touches.contains(st) {
            joystick.drag(to: st.location(in: cameraNode))
        }
    }

    override func touchesEnded(_ touches: Set<UITouch>, with event: UIEvent?) { endTouches(touches) }
    override func touchesCancelled(_ touches: Set<UITouch>, with event: UIEvent?) { endTouches(touches) }

    private func endTouches(_ touches: Set<UITouch>) {
        for t in touches {
            if t == stickTouch { joystick.release(); stickTouch = nil }
            if t == boostTouch { boostBtn.setPressed(false); boostTouch = nil }
            if t == turboTouch { turboBtn.setPressed(false); turboTouch = nil }
            if t == surfaceTouch { surfaceBtn.setPressed(false); surfaceTouch = nil }
        }
    }

    // MARK: Shared actions (used by both touch and the game controller)

    private func toggleFlashlight() {
        flashlightOn.toggle()
        player.setFlashlight(flashlightOn)
        flashBtn.setPressed(flashlightOn)
        darkness.texture = flashlightOn ? veilOn : veilOff
    }

    private func beginAscent() {
        ascending = true
        player.setThrust(.zero)
        joystick.release(); stickTouch = nil
    }

    // MARK: Game controller (optional — left stick/dpad to swim; see attach())

    private func setupControllers() {
        GCController.controllers().forEach(attach)
        controllerObserver = NotificationCenter.default.addObserver(
            forName: .GCControllerDidConnect, object: nil, queue: .main) { [weak self] note in
            if let c = note.object as? GCController { self?.attach(c) }
        }
        GCController.startWirelessControllerDiscovery {}
    }

    /// Map the tap-style buttons. Hold-style boost/turbo + the sticks are polled
    /// each frame in `update`. Layout matches the on-screen diamond:
    ///   Y (top) = rise · A (bottom) = lamp · X (left) = boost · B (right) = turbo.
    private func attach(_ controller: GCController) {
        guard let gp = controller.extendedGamepad else { return }
        gp.buttonY.pressedChangedHandler = { [weak self] _, _, pressed in
            if pressed { self?.beginAscent() }
        }
        gp.buttonA.pressedChangedHandler = { [weak self] _, _, pressed in
            if pressed { self?.toggleFlashlight() }
        }
    }

    // MARK: Game loop

    override func update(_ currentTime: TimeInterval) {
        let dt: CGFloat
        if lastUpdateTime == 0 {
            dt = 1.0 / 60.0
        } else {
            dt = CGFloat(min(currentTime - lastUpdateTime, 1.0 / 20.0))   // cap big hitches
        }
        lastUpdateTime = currentTime

        // Gather input: on-screen joystick/buttons plus an optional game controller.
        var moveVec = joystick.vector
        var cBoost = false, cTurbo = false
        if let gp = GCController.current?.extendedGamepad {
            var dx = CGFloat(gp.leftThumbstick.xAxis.value)
            var dy = CGFloat(gp.leftThumbstick.yAxis.value)
            if gp.dpad.xAxis.value != 0 || gp.dpad.yAxis.value != 0 {
                dx = CGFloat(gp.dpad.xAxis.value); dy = CGFloat(gp.dpad.yAxis.value)
            }
            let mag = hypot(dx, dy)
            if mag > 0.18 {
                let s = min(mag, 1) / mag
                moveVec = CGVector(dx: dx * s, dy: dy * s)
                ascending = false              // grabbing the stick cancels an auto-rise
            }
            cBoost = gp.buttonX.isPressed || gp.rightShoulder.isPressed
            cTurbo = gp.buttonB.isPressed || gp.rightTrigger.value > 0.3
        }

        if ascending {
            // Whisk straight up to the surface (ease-out, with a floor speed so
            // even a trench-deep ascent only takes a moment).
            let target = GameConfig.playerStartY
            player.physicsBody?.velocity = .zero
            let dy = target - player.position.y
            if dy <= 8 {
                player.position.y = target
                ascending = false
                surfaceBtn.setPressed(false)
            } else {
                player.position.y += max(dy * 0.13, 1100 * dt)
            }
            player.setThrust(.zero)
        } else {
            player.setThrust(moveVec)
            let turbo = turboBtn.pressed || cTurbo
            let boost = boostBtn.pressed || cBoost
            player.boostFactor = turbo ? 16.0 : (boost ? 6.0 : 1.0)
        }
        player.update(dt)

        // Drift creatures and wrap them around the diver's column so each depth's
        // creatures are always nearby and crossing the view as you descend.
        creatureField.update(dt: dt, cameraX: cameraNode.position.x)
        landmarkField.update(cameraX: cameraNode.position.x)
        // Fade in the nearest creature's in-world fact bubble (no screen overlay).
        creatureField.updateInfo(near: player.position, within: 230)

        let halfW = size.width / 2 + 50
        oceanSurface.update(currentTime,
                            minX: cameraNode.position.x - halfW,
                            maxX: cameraNode.position.x + halfW)
        updateDepthEffects()
    }

    /// HUD read-out plus depth-driven darkening and tint.
    private func updateDepthEffects() {
        let depthPoints = max(0, -player.position.y)
        let meters = depthPoints / GameConfig.pointsPerMeter
        let zone = zoneName(meters)

        hud.update(depthMeters: meters, zone: zone)

        // Water color is driven directly by depth, progressing through the
        // ocean zones from bright surface to the black trench.
        waterBackground.color = depthColor(meters)

        // Darkness closes in below the sunlit zone; the headlamp keeps a clear
        // disc around the diver so the lit deep stays explorable.
        let dark = smoothstep(150, 950, meters)
        darkness.alpha = dark
        player.setLampIntensity(dark)

        // Banners: announce a new zone, else surface a "deeper than X" fact as
        // you first pass its depth (at most one banner per frame).
        var shownBanner = false
        if zone != lastZoneName {
            lastZoneName = zone
            showBanner(title: zone, body: zoneBlurb(zone), accent: Palette.rgb(150, 236, 232))
            shownBanner = true
        }
        if !shownBanner {
            for (i, t) in GameScene.trivia.enumerated()
            where !shownTrivia.contains(i) && lastDepthMeters < t.depth && meters >= t.depth {
                shownTrivia.insert(i)
                showBanner(title: "", body: t.text, accent: Palette.rgb(150, 210, 240))
                break
            }
        }
        lastDepthMeters = meters
    }

    /// Smoothly follow the swimmer (after physics has settled), clamped so the
    /// camera never reveals the world's edges.
    override func didFinishUpdate() {
        guard let cam = camera else { return }

        // Snap tightly while rising; otherwise tighten the follow as the diver
        // speeds up (boost/turbo) so it never outruns the camera off-screen.
        let k = ascending ? 1.0 : min(0.5, GameConfig.cameraSmoothing + player.currentSpeed / 5200)
        var p = CGPoint(
            x: cam.position.x + (player.position.x - cam.position.x) * k,
            y: cam.position.y + (player.position.y - cam.position.y) * k)

        let halfH = size.height / 2

        // Horizontal is endless — follow freely; only the vertical column is clamped.
        let minY = GameConfig.worldFloor + halfH
        let maxY = GameConfig.skyTop - halfH
        p.y = minY <= maxY ? clamp(p.y, minY, maxY) : (minY + maxY) / 2

        cam.position = p

        // Keep the surface backdrop centered on the diver so swimming sideways
        // forever never reveals its edges.
        let cx = cam.position.x
        skyNode.position.x = cx
        causticsNode.position.x = cx
        sunNode.position.x = cx + Environment.sunPosition.x

        // Keep the lamp's clear disc centered on the diver (not the screen).
        darkness.position = CGPoint(x: player.position.x - cam.position.x,
                                    y: player.position.y - cam.position.y)
    }
}

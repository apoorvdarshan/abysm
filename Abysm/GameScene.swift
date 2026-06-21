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

final class GameScene: SKScene {

    // World
    private let oceanSurface = OceanSurface(width: GameConfig.worldHalfWidth * 2 + 400)
    private let player = Player()
    private let creatureField = CreatureField()

    // Camera & screen-space overlays (children of the camera)
    private let cameraNode = SKCameraNode()
    /// Full-screen water color driven by depth (replaces a giant gradient
    /// texture — the descent reaches ~10,935 m, far too deep to texture).
    private let waterBackground = SKSpriteNode(color: .black, size: CGSize(width: 2800, height: 3600))
    private let plankton = Particles.plankton()
    private let marineSnow = Particles.marineSnow()
    private let hud = DepthHUD()
    private let joystick = Joystick()
    private let creatureInfo = CreatureInfoPanel()
    private let boostBtn = HoldButton(radius: 44, glyph: ">>", fontSize: 16, color: Palette.rgb(40, 150, 168))
    private let turboBtn = HoldButton(radius: 50, glyph: ">>>", fontSize: 15, color: Palette.rgb(225, 130, 50))
    private let flashBtn = HoldButton(radius: 38, glyph: "*", fontSize: 22, color: Palette.rgb(232, 196, 64))
    private var flashlightOn = true

    private var lastUpdateTime: TimeInterval = 0
    // Touches currently controlling each control (multi-touch).
    private var stickTouch: UITouch?
    private var boostTouch: UITouch?
    private var turboTouch: UITouch?

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

        playIntroFade()
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
        addChild(Environment.makeSky())
        addChild(Environment.makeSun())
        addChild(Environment.makeCaustics())
        addChild(oceanSurface)
        creatureField.populate()
        addChild(creatureField)
    }

    private func buildCamera() {
        addChild(cameraNode)
        camera = cameraNode

        // Behind everything (incl. the world sky), filling the screen.
        waterBackground.zPosition = -200
        cameraNode.addChild(waterBackground)

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
        cameraNode.addChild(creatureInfo)
        cameraNode.addChild(joystick)
        cameraNode.addChild(boostBtn)
        cameraNode.addChild(turboBtn)
        cameraNode.addChild(flashBtn)
        flashBtn.setPressed(flashlightOn)   // reflect the default-on state
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
        // Enforce a minimum so the HUD always clears the Dynamic Island / notch,
        // even before UIKit reports the real safe-area inset.
        let topInset = max(view?.safeAreaInsets.top ?? 0, 59)

        hud.position = CGPoint(x: 0, y: viewport.height / 2 - (topInset + 26))
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

        // Creature info card: top-center, stacked just under the depth HUD
        // (clear of the bottom joystick/boost controls).
        creatureInfo.position = CGPoint(x: 0, y: hud.position.y - 27 - creatureInfo.panelSize.height / 2 - 10)

        // Boost + turbo: bottom-right (turbo rightmost), mirroring the joystick.
        let safeRight = view?.safeAreaInsets.right ?? 0
        let by = -viewport.height / 2 + safeBottom + turboBtn.radius + 24
        turboBtn.position = CGPoint(x: viewport.width / 2 - safeRight - turboBtn.radius - 26, y: by)
        boostBtn.position = CGPoint(x: turboBtn.position.x - turboBtn.radius - boostBtn.radius - 22, y: by)

        // Flashlight toggle: top-right.
        flashBtn.position = CGPoint(x: viewport.width / 2 - safeRight - flashBtn.radius - 18,
                                    y: viewport.height / 2 - topInset - flashBtn.radius - 6)
    }

    override func didChangeSize(_ oldSize: CGSize) {
        super.didChangeSize(oldSize)
        layout()
    }

    // MARK: Touch steering (virtual joystick, bottom-left)

    override func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent?) {
        for t in touches {
            let p = t.location(in: cameraNode)
            if flashBtn.hit(p) {   // tap to toggle the headlamp
                flashlightOn.toggle()
                player.setFlashlight(flashlightOn)
                flashBtn.setPressed(flashlightOn)
                continue
            }
            if stickTouch == nil, joystick.engage(at: p) { stickTouch = t; continue }
            if boostTouch == nil, boostBtn.hit(p) { boostTouch = t; boostBtn.setPressed(true); continue }
            if turboTouch == nil, turboBtn.hit(p) { turboTouch = t; turboBtn.setPressed(true); continue }
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

        player.setThrust(joystick.vector)
        player.boostFactor = turboBtn.pressed ? 3.0 : (boostBtn.pressed ? 1.9 : 1.0)
        player.update(dt)

        // Show the info card for the nearest creature you're swimming by.
        if let def = creatureField.nearest(to: player.position, within: 210) {
            creatureInfo.show(def)
        } else {
            creatureInfo.hide()
        }

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

        hud.update(depthMeters: meters, zone: zoneName(meters))

        // Water color is driven directly by depth, progressing through the
        // ocean zones from bright surface to the black trench.
        waterBackground.color = depthColor(meters)
    }

    /// Smoothly follow the swimmer (after physics has settled), clamped so the
    /// camera never reveals the world's edges.
    override func didFinishUpdate() {
        guard let cam = camera else { return }

        var p = CGPoint(
            x: cam.position.x + (player.position.x - cam.position.x) * GameConfig.cameraSmoothing,
            y: cam.position.y + (player.position.y - cam.position.y) * GameConfig.cameraSmoothing)

        let halfW = size.width / 2
        let halfH = size.height / 2

        let minX = -GameConfig.worldHalfWidth + halfW
        let maxX =  GameConfig.worldHalfWidth - halfW
        p.x = minX <= maxX ? clamp(p.x, minX, maxX) : 0

        let minY = GameConfig.worldFloor + halfH
        let maxY = GameConfig.skyTop - halfH
        p.y = minY <= maxY ? clamp(p.y, minY, maxY) : (minY + maxY) / 2

        cam.position = p
    }
}

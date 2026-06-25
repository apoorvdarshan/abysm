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
    private let player = Player()
    private let creatureField = CreatureField()
    private let landmarkField = LandmarkField()
    private let scenicField = ScenicField()
    private let schoolField = SchoolField()
    // Surface backdrop — followed horizontally so the world feels endless.
    private var skyNode = SKNode()
    private var sunNode = SKNode()
    private var underwaterGlow = SKNode()
    private var tideLine = SKNode()
    private let cloudField = CloudField()

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

    /// Tokens for the game-controller connect/disconnect observers.
    private var controllerObserver: NSObjectProtocol?
    private var controllerDisconnectObserver: NSObjectProtocol?

    /// Optional start point (set before presenting) — used by Continue.
    var startDepthMeters: CGFloat?
    var startX: CGFloat?
    private var saveAccum: CGFloat = 0
    private var saveObserver: NSObjectProtocol?
    private var lastPlayerY: CGFloat = -1

    // Pause / main-menu.
    private let pauseBtn = HoldButton(radius: 26, glyph: "", fontSize: 1, color: Palette.rgb(52, 92, 134))
    private let pauseIcon = SKSpriteNode()
    private let pauseOverlay = SKNode()
    private let resumeBtn = SKNode()
    private let menuBtn = SKNode()
    private var menuPaused = false
    private var pauseIndex = 0          // 0 = Resume, 1 = Main Menu (controller nav)
    private var navCooldown: CGFloat = 0
    private let pBtnW: CGFloat = 260, pBtnH: CGFloat = 48

    // Sound + haptics.
    private let muteBtn = HoldButton(radius: 28, glyph: "", fontSize: 1, color: Palette.rgb(52, 92, 134))
    private let muteIcon = SKSpriteNode()
    // Pre-built once so toggling mute never regenerates a texture mid-swim (that
    // main-thread hitch made the diver lurch forward a frame).
    private let speakerOn  = TextureFactory.pixelSpeaker(crossed: false)
    private let speakerOff = TextureFactory.pixelSpeaker(crossed: true)
    private var soundMuted = false
    private var isBoosting = false
    private var prevBoost = false
    private var prevTurbo = false
    private var floorThudDone = false
    /// Last integer depth the water color was set for (skip per-frame UIColor work).
    private var lastColorMeters = Int.min

    // Paywall — the free dive ends at the 1,000 m gate until "Unlock the Deep".
    private let gateMeters: CGFloat = 1000
    private var gateY: CGFloat { -gateMeters * GameConfig.pointsPerMeter }
    private let paywall = Paywall()
    private var paywalled = false
    private var gateCooldown: CGFloat = 0

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
        AudioManager.shared.start()
        playIntroFade()

        // Sync the unlock entitlement (and load the product/price) for the gate.
        Task { await StoreManager.shared.refresh() }

        // Save the resume point when the app goes to the background.
        saveObserver = NotificationCenter.default.addObserver(
            forName: UIApplication.willResignActiveNotification, object: nil, queue: .main) { [weak self] _ in
            self?.saveProgress()
        }
    }

    deinit {
        if let o = controllerObserver { NotificationCenter.default.removeObserver(o) }
        if let o = controllerDisconnectObserver { NotificationCenter.default.removeObserver(o) }
        if let o = saveObserver { NotificationCenter.default.removeObserver(o) }
        // NB: we deliberately do NOT clear the controller's pressedChangedHandlers
        // here. They use [weak self] (so a dead scene's closures are harmless
        // no-ops) and the next scene overwrites them on attach. Clearing them in
        // deinit raced the next scene's setup and wiped its just-installed handler.
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
        underwaterGlow = Environment.makeUnderwaterGlow()
        tideLine = Environment.makeTideLine()
        addChild(skyNode)
        addChild(sunNode)
        addChild(underwaterGlow)
        addChild(tideLine)
        cloudField.populate()
        addChild(cloudField)
        scenicField.populate()
        addChild(scenicField)
        schoolField.populate()
        addChild(schoolField)
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
        flashBtn.isHidden = true            // shown once below the sunlit zone (updateDepthEffects)

        // "Rise to the surface" button (top-left) with a pixel up-arrow glyph.
        let upArrow = SKSpriteNode(texture: TextureFactory.pixelTriangleUp(half: 7, color: .white))
        upArrow.size = CGSize(width: 18, height: 15)
        upArrow.zPosition = 3
        surfaceBtn.addChild(upArrow)
        cameraNode.addChild(surfaceBtn)

        // Mute toggle (top-right) with a pixel speaker icon. Sync to the mute
        // state already set elsewhere (e.g. the main-menu toggle) so the icon
        // and haptics match on entry instead of assuming sound is on.
        soundMuted = AudioManager.shared.muted
        HapticsManager.shared.enabled = !soundMuted
        muteIcon.texture = soundMuted ? speakerOff : speakerOn
        muteIcon.size = CGSize(width: 24, height: 16)
        muteIcon.zPosition = 3
        muteBtn.addChild(muteIcon)
        cameraNode.addChild(muteBtn)

        // Pause button (top-left) + the pause overlay.
        pauseIcon.texture = TextureFactory.pixelPause()
        pauseIcon.size = CGSize(width: 18, height: 21)
        pauseIcon.zPosition = 3
        pauseBtn.addChild(pauseIcon)
        cameraNode.addChild(pauseBtn)
        buildPauseOverlay()

        // Paywall modal — hidden until the diver reaches the 1,000 m gate.
        paywall.isHidden = true
        paywall.onUnlock  = { [weak self] in self?.buyUnlock() }
        paywall.onRestore = { [weak self] in self?.restorePurchase() }
        paywall.onDismiss = { [weak self] in self?.closePaywall(lift: true) }
        cameraNode.addChild(paywall)
    }

    private func buildPauseOverlay() {
        let dim = SKSpriteNode(color: .black, size: CGSize(width: 4200, height: 3200))
        dim.alpha = 0.66; dim.zPosition = 0
        let titleL = GameFont.label()
        titleL.text = L("pause.title", "PAUSED"); titleL.fontSize = 26; titleL.fontColor = .white
        titleL.verticalAlignmentMode = .center; titleL.horizontalAlignmentMode = .center
        titleL.zPosition = 2; titleL.position = CGPoint(x: 0, y: 96)
        pauseOverlay.addChild(dim); pauseOverlay.addChild(titleL)
        plateButton(resumeBtn, L("pause.resume", "RESUME"), y: 20)
        plateButton(menuBtn, L("pause.main_menu", "MAIN MENU"), y: 20 - (pBtnH + 18))
        pauseOverlay.zPosition = GameConfig.Z.intro + 1
        pauseOverlay.isHidden = true
        cameraNode.addChild(pauseOverlay)
    }

    private func plateButton(_ node: SKNode, _ text: String, y: CGFloat) {
        let border = SKSpriteNode(color: Palette.rgb(150, 236, 232), size: CGSize(width: pBtnW + 6, height: pBtnH + 6))
        border.alpha = 0.8
        let plate = SKSpriteNode(color: Palette.rgb(9, 20, 44), size: CGSize(width: pBtnW, height: pBtnH))
        plate.alpha = 0.95; plate.zPosition = 1
        let label = GameFont.label()
        label.text = text; label.fontSize = 15; label.fontColor = .white
        label.verticalAlignmentMode = .center; label.horizontalAlignmentMode = .center; label.zPosition = 2
        node.addChild(border); node.addChild(plate); node.addChild(label)
        node.position = CGPoint(x: 0, y: y); node.zPosition = 1
        pauseOverlay.addChild(node)
    }

    private func buildPlayer() {
        let y = startDepthMeters.map { -$0 * GameConfig.pointsPerMeter } ?? GameConfig.playerStartY
        player.position = CGPoint(x: startX ?? 0, y: y)
        addChild(player)
        player.attachBubbleTarget(self)   // bubbles trail in world space
        lastPlayerY = player.position.y   // seed so spawning doesn't fake a breach
    }

    /// Persist the diver's current depth + x so the title can offer Continue.
    private func saveProgress() {
        let meters = max(0, -player.position.y) / GameConfig.pointsPerMeter
        SaveManager.save(depthMeters: meters, x: player.position.x)
    }

    // MARK: Layout (re-run whenever the view size changes)

    private func layout() {
        guard camera != nil else { return }
        let viewport = size
        // Enforce a minimum so the top row clears the camera housing. (Landscape
        // puts the Dynamic Island on a side edge, so the top can sit fairly high.)
        let topInset = max(view?.safeAreaInsets.top ?? 0, 40)

        hud.position = CGPoint(x: 0, y: viewport.height / 2 - topInset - 14)
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

        // Mute toggle: top-right corner.
        muteBtn.position = CGPoint(x: viewport.width / 2 - safeRight - muteBtn.radius - 16,
                                   y: viewport.height / 2 - topInset - muteBtn.radius - 6)
        // Pause: top-left corner.
        pauseBtn.position = CGPoint(x: -viewport.width / 2 + safeLeft + pauseBtn.radius + 16,
                                    y: viewport.height / 2 - topInset - pauseBtn.radius - 6)

        // Shrink the paywall plaque only if the screen is too small to fit it.
        paywall.setScale(min(1, min((viewport.width - 24) / Paywall.panelW,
                                    (viewport.height - 24) / Paywall.panelH)))
    }

    override func didChangeSize(_ oldSize: CGSize) {
        super.didChangeSize(oldSize)
        layout()
    }

    // MARK: Touch steering (virtual joystick, bottom-left)

    override func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent?) {
        // While the paywall is up, only its buttons are live.
        if paywalled {
            guard let t = touches.first else { return }
            paywall.handleTap(t.location(in: paywall))
            return
        }
        // While paused, only the overlay buttons are live.
        if menuPaused {
            guard let t = touches.first else { return }
            // resumeBtn / menuBtn live in the overlay's space — hit-test there.
            let p = t.location(in: pauseOverlay)
            if hitPlate(resumeBtn, p) { resumeGame() }
            else if hitPlate(menuBtn, p) { toMainMenu() }
            return
        }
        for t in touches {
            let p = t.location(in: cameraNode)
            if pauseBtn.hit(p) { openPause(); continue }
            if muteBtn.hit(p) { toggleMute(); continue }          // tap to mute/unmute
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
        // The headlamp doesn't exist in the sunlit zone — ignore toggles there so
        // a controller press makes no click sound and changes nothing.
        let meters = max(0, -player.position.y) / GameConfig.pointsPerMeter
        guard meters >= GameConfig.zones[1].topMeters else { return }
        flashlightOn.toggle()
        player.setFlashlight(flashlightOn)
        flashBtn.setPressed(flashlightOn)
        darkness.texture = flashlightOn ? veilOn : veilOff
        AudioManager.shared.playClick()
    }

    private func beginAscent() {
        ascending = true
        player.setThrust(.zero)
        joystick.release(); stickTouch = nil
    }

    private func toggleMute() {
        soundMuted.toggle()
        AudioManager.shared.setMuted(soundMuted)
        HapticsManager.shared.enabled = !soundMuted
        muteIcon.texture = soundMuted ? speakerOff : speakerOn
    }

    private func hitPlate(_ node: SKNode, _ p: CGPoint) -> Bool {
        abs(p.x - node.position.x) <= pBtnW / 2 && abs(p.y - node.position.y) <= pBtnH / 2
    }

    private func openPause() {
        guard !menuPaused else { return }
        menuPaused = true
        pauseIndex = 0
        saveProgress()
        joystick.release(); stickTouch = nil
        boostBtn.setPressed(false); boostTouch = nil
        turboBtn.setPressed(false); turboTouch = nil
        ascending = false; surfaceBtn.setPressed(false); surfaceTouch = nil
        isBoosting = false; prevBoost = false; prevTurbo = false
        player.physicsBody?.velocity = .zero      // hold the diver still
        pauseOverlay.isHidden = false
        highlightPause()
    }

    private func resumeGame() {
        menuPaused = false
        pauseOverlay.isHidden = true
    }

    private func toMainMenu() {
        saveProgress()
        guard let v = view else { return }
        let t = TitleScene(size: v.bounds.size)
        t.scaleMode = .resizeFill
        v.presentScene(t, transition: .fade(with: .black, duration: 0.6))
    }

    // MARK: Paywall ("Unlock the Deep")

    /// Freeze the diver and raise the purchase modal at the 1,000 m gate.
    private func presentPaywall() {
        guard !paywalled else { return }
        paywalled = true
        // Clear every input, same as opening the pause menu.
        joystick.release(); stickTouch = nil
        boostBtn.setPressed(false); boostTouch = nil
        turboBtn.setPressed(false); turboTouch = nil
        ascending = false; surfaceBtn.setPressed(false); surfaceTouch = nil
        isBoosting = false; prevBoost = false; prevTurbo = false
        player.setThrust(.zero)
        player.physicsBody?.velocity = .zero
        saveProgress()
        paywall.reset(price: StoreManager.shared.displayPrice)
        paywall.isHidden = false
        // Pull the real localized price in case it wasn't loaded yet.
        Task { @MainActor in
            await StoreManager.shared.loadProduct()
            paywall.setPrice(StoreManager.shared.displayPrice)
        }
        HapticsManager.shared.pulse(intensity: 0.4, sharpness: 0.3)
    }

    /// Hide the modal. `lift` nudges the diver back above the gate so dismissing
    /// ("keep exploring") doesn't immediately re-trigger it.
    private func closePaywall(lift: Bool) {
        paywalled = false
        paywall.isHidden = true
        paywall.setBusy(false)
        if lift {
            gateCooldown = 0.8
            if player.position.y <= gateY {
                player.position.y = gateY + 120
                player.physicsBody?.velocity = .zero
            }
        }
    }

    private func buyUnlock() {
        guard !paywall.isBusy else { return }
        paywall.setBusy(true)
        paywall.setStatus(L("paywall.purchasing", "PURCHASING…"))
        Task { @MainActor in
            switch await StoreManager.shared.purchase() {
            case .success:
                paywall.setStatus(L("paywall.unlocked", "THE DEEP IS YOURS"))
                HapticsManager.shared.pulse(intensity: 1.0, sharpness: 0.6)
                try? await Task.sleep(nanoseconds: 1_100_000_000)
                closePaywall(lift: false)   // unlocked — let them keep descending
            case .pending:
                // Deferred (Ask to Buy / parental approval) — distinct from the
                // active-purchase status; the modal auto-closes on approval.
                paywall.setBusy(false)
                paywall.setStatus(L("paywall.pending", "WAITING FOR APPROVAL"))
            case .cancelled:
                paywall.setBusy(false); paywall.setStatus(nil)
            case .failed:
                paywall.setBusy(false)
                paywall.setStatus(L("paywall.failed", "PURCHASE FAILED"))
            }
        }
    }

    private func restorePurchase() {
        guard !paywall.isBusy else { return }
        paywall.setBusy(true)
        paywall.setStatus(L("paywall.restoring", "RESTORING…"))
        Task { @MainActor in
            if await StoreManager.shared.restore() {
                paywall.setStatus(L("paywall.unlocked", "THE DEEP IS YOURS"))
                try? await Task.sleep(nanoseconds: 900_000_000)
                closePaywall(lift: false)
            } else {
                paywall.setBusy(false)
                paywall.setStatus(L("paywall.nothing_restored", "NOTHING TO RESTORE"))
            }
        }
    }

    /// Highlight the selected pause button (controller only).
    private func highlightPause() {
        let hasController = GCController.current != nil
        resumeBtn.setScale(hasController && pauseIndex == 0 ? 1.06 : 1.0)
        menuBtn.setScale(hasController && pauseIndex == 1 ? 1.06 : 1.0)
        resumeBtn.alpha = (!hasController || pauseIndex == 0) ? 1.0 : 0.7
        menuBtn.alpha = (!hasController || pauseIndex == 1) ? 1.0 : 0.7
    }

    // MARK: Game controller (optional — left stick/dpad to swim; see attach())

    private func setupControllers() {
        GCController.controllers().forEach(attach)
        controllerObserver = NotificationCenter.default.addObserver(
            forName: .GCControllerDidConnect, object: nil, queue: .main) { [weak self] note in
            if let c = note.object as? GCController { self?.attach(c) }
        }
        controllerDisconnectObserver = NotificationCenter.default.addObserver(
            forName: .GCControllerDidDisconnect, object: nil, queue: .main) { [weak self] note in
            if let c = note.object as? GCController { self?.detach(c) }
        }
        GCController.startWirelessControllerDiscovery {}
    }

    /// A controller dropped: stop steering with it and un-stick the pause cursor.
    private func detach(_ controller: GCController) {
        player.setThrust(.zero)
        if menuPaused { highlightPause() }
    }

    /// Map the tap-style buttons. Hold-style boost/turbo + the sticks are polled
    /// each frame in `update`. Layout matches the on-screen diamond:
    ///   Y (top) = rise · A (bottom) = lamp · X (left) = boost · B (right) = turbo.
    private func attach(_ controller: GCController) {
        HapticsManager.shared.attach(controller)
        guard let gp = controller.extendedGamepad else { return }
        GCController.stopWirelessControllerDiscovery()   // found one; stop scanning
        gp.buttonY.pressedChangedHandler = { [weak self] _, _, pressed in
            guard pressed, let self = self, !self.menuPaused, !self.paywalled else { return }
            self.beginAscent()
        }
        // A buys the unlock while the paywall is up, activates the highlighted
        // pause choice while paused, else toggles the lamp.
        gp.buttonA.pressedChangedHandler = { [weak self] _, _, pressed in
            guard pressed, let self = self else { return }
            if self.paywalled {
                self.paywall.activateSelected()
            } else if self.menuPaused {
                if self.pauseIndex == 0 { self.resumeGame() } else { self.toMainMenu() }
            } else {
                self.toggleFlashlight()
            }
        }
        // B is only turbo (polled in update). The paywall is dismissed via its
        // KEEP EXPLORING button, not a B shortcut.
        // Options/Menu toggles pause (or dismisses the paywall); L1 toggles mute.
        gp.buttonMenu.pressedChangedHandler = { [weak self] _, _, pressed in
            guard pressed, let self = self else { return }
            if self.paywalled { self.closePaywall(lift: true) }
            else if self.menuPaused { self.resumeGame() } else { self.openPause() }
        }
        gp.leftShoulder.pressedChangedHandler = { [weak self] _, _, pressed in
            if pressed { self?.toggleMute() }
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

        // While the "Unlock the Deep" modal is up, the game is frozen; only drive
        // the paywall's controller cursor (stick/d-pad to highlight, A to pick).
        if paywalled {
            // If the unlock arrives out-of-band (Ask to Buy approval, or a buy /
            // restore on another device) while the modal is up, close it and let
            // them keep descending instead of leaving them frozen behind it.
            if StoreManager.shared.isUnlocked { closePaywall(lift: false); return }
            navCooldown = max(0, navCooldown - dt)
            if let gp = GCController.current?.extendedGamepad, navCooldown == 0 {
                let y = gp.leftThumbstick.yAxis.value + gp.dpad.yAxis.value
                if y > 0.5 { paywall.moveSelection(-1); navCooldown = 0.22 }
                else if y < -0.5 { paywall.moveSelection(1); navCooldown = 0.22 }
            }
            return
        }

        // While paused, the game is frozen; only drive the pause-menu cursor.
        if menuPaused {
            navCooldown = max(0, navCooldown - dt)
            if let gp = GCController.current?.extendedGamepad, navCooldown == 0 {
                let y = gp.leftThumbstick.yAxis.value + gp.dpad.yAxis.value
                if y > 0.5 { pauseIndex = 0; navCooldown = 0.22; highlightPause() }
                else if y < -0.5 { pauseIndex = 1; navCooldown = 0.22; highlightPause() }
            }
            return
        }

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
            isBoosting = false
            prevBoost = false; prevTurbo = false
        } else {
            player.setThrust(moveVec)
            let turbo = turboBtn.pressed || cTurbo
            let boost = boostBtn.pressed || cBoost
            player.boostFactor = turbo ? 16.0 : (boost ? 6.0 : 1.0)
            isBoosting = turbo || boost
            // A haptic kick when boost/turbo first engages.
            if turbo && !prevTurbo { HapticsManager.shared.pulse(intensity: 1.0, sharpness: 0.6) }
            else if boost && !prevBoost { HapticsManager.shared.pulse(intensity: 0.5, sharpness: 0.4) }
            prevBoost = boost; prevTurbo = turbo
        }
        player.update(dt)

        // Depth gate: the free dive ends at 1,000 m until "Unlock the Deep".
        // Clamp the diver at the gate and, when they actively press deeper,
        // raise the purchase modal.
        if !StoreManager.shared.isUnlocked {
            gateCooldown = max(0, gateCooldown - dt)
            if player.position.y < gateY {
                player.position.y = gateY
                if let b = player.physicsBody, b.velocity.dy < 0 { b.velocity.dy = 0 }
            }
            if player.position.y <= gateY + 2, moveVec.dy < -0.15, gateCooldown == 0 {
                presentPaywall()
                return
            }
        }

        // A heavy thud the first time you reach the trench floor.
        if player.position.y <= GameConfig.worldFloor + 60 {
            if !floorThudDone { floorThudDone = true; HapticsManager.shared.pulse(intensity: 0.9, sharpness: 0.7) }
        } else if player.position.y > GameConfig.worldFloor + 500 {
            floorThudDone = false
        }

        // Drift creatures and wrap them around the diver's column so each depth's
        // creatures are always nearby and crossing the view as you descend.
        saveAccum += dt
        if saveAccum >= 3 { saveAccum = 0; saveProgress() }

        creatureField.update(dt: dt, cameraX: cameraNode.position.x)
        landmarkField.update(cameraX: cameraNode.position.x)
        scenicField.update(cameraX: cameraNode.position.x)
        schoolField.update(dt: dt, cameraX: cameraNode.position.x)
        cloudField.update(dt: dt, cameraX: cameraNode.position.x)
        // Fade in the nearest creature's in-world fact bubble (no screen overlay).
        creatureField.updateInfo(near: player.position, within: 230)

        // Splash when the diver breaches out of, or drops back into, the surface.
        let y = player.position.y
        let vy = abs(player.physicsBody?.velocity.dy ?? 0)
        if vy > 70, (lastPlayerY <= 0) != (y <= 0) {
            spawnSplash(at: player.position.x)
            AudioManager.shared.playSplash()
        }
        lastPlayerY = y

        updateDepthEffects()
    }

    /// A quick burst of white droplets at the surface (y = 0).
    private func spawnSplash(at x: CGFloat) {
        let tex = TextureFactory.pixelDot(2, color: .white)
        for _ in 0..<14 {
            let d = SKSpriteNode(texture: tex)
            let s = CGFloat.random(in: 4...9)
            d.size = CGSize(width: s, height: s)
            d.position = CGPoint(x: x + CGFloat.random(in: -24...24), y: 2)
            d.zPosition = GameConfig.Z.player + 1
            addChild(d)
            let dx = CGFloat.random(in: -90...90)
            let up = CGFloat.random(in: 70...170)
            let rise = SKAction.moveBy(x: dx, y: up, duration: 0.3); rise.timingMode = .easeOut
            let fall = SKAction.moveBy(x: dx * 0.4, y: -up - 40, duration: 0.45); fall.timingMode = .easeIn
            d.run(.sequence([rise, fall, .removeFromParent()]))
            d.run(.fadeOut(withDuration: 0.72))
        }
    }

    /// HUD read-out plus depth-driven darkening and tint.
    private func updateDepthEffects() {
        let depthPoints = max(0, -player.position.y)
        let meters = depthPoints / GameConfig.pointsPerMeter
        let zone = zoneName(meters)

        hud.update(depthMeters: meters, zone: zone)

        // The headlamp button only matters once you leave the sunlit zone — hide
        // it up top (where it does nothing), show it from the Twilight zone down.
        flashBtn.isHidden = meters < GameConfig.zones[1].topMeters

        // Water color is driven directly by depth, surface → black trench. It
        // shifts imperceptibly within a meter, so only rebuild the UIColor when
        // the integer depth changes (avoids a per-frame allocation while idling).
        let mInt = Int(meters)
        if mInt != lastColorMeters {
            lastColorMeters = mInt
            waterBackground.color = depthColor(meters)
        }

        // Darkness closes in below the sunlit zone; the headlamp keeps a clear
        // disc around the diver so the lit deep stays explorable.
        let dark = smoothstep(150, 950, meters)
        darkness.alpha = dark
        player.setLampIntensity(dark)

        // Crossfade the surface/deep audio layers by depth; bubbles while boosting.
        AudioManager.shared.update(depthMeters: meters, boosting: isBoosting)
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
        tideLine.position.x = cx
        underwaterGlow.position.x = cx
        sunNode.position.x = cx + Environment.sunPosition.x

        // Keep the lamp's clear disc centered on the diver (not the screen).
        darkness.position = CGPoint(x: player.position.x - cam.position.x,
                                    y: player.position.y - cam.position.y)
    }
}

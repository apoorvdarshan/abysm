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
import CoreImage

final class GameScene: SKScene {

    // World
    private let oceanSurface = OceanSurface(width: GameConfig.worldHalfWidth * 2 + 400)
    private let player = Player()

    // Camera & screen-space overlays (children of the camera)
    private let cameraNode = SKCameraNode()
    private let blueTint = SKSpriteNode(color: Palette.blueTint, size: CGSize(width: 2400, height: 3400))
    private let darkness = SKSpriteNode(color: .black, size: CGSize(width: 2400, height: 3400))
    private let plankton = Particles.plankton()
    private let marineSnow = Particles.marineSnow()
    private let bokeh = Particles.bokeh()
    private let vignette = SKSpriteNode(texture: TextureFactory.vignette(diameter: 512, edgeAlpha: 0.55))
    private let hud = DepthHUD()
    private let joystick = Joystick()

    private var lastUpdateTime: TimeInterval = 0
    /// The single touch currently controlling the joystick (if any).
    private var stickTouch: UITouch?

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
        addChild(Environment.makeWater())
        addChild(Environment.makeSun())
        addChild(Environment.makeGodRays())
        addChild(Environment.makeCaustics())
        addChild(oceanSurface)
    }

    private func buildCamera() {
        addChild(cameraNode)
        camera = cameraNode

        blueTint.zPosition = GameConfig.Z.blueTint
        blueTint.alpha = 0.06
        cameraNode.addChild(blueTint)

        marineSnow.zPosition = GameConfig.Z.plankton - 1
        cameraNode.addChild(marineSnow)
        marineSnow.targetNode = self
        marineSnow.advanceSimulationTime(16)

        bokeh.zPosition = GameConfig.Z.plankton + 2   // closest "lens" layer
        cameraNode.addChild(bokeh)
        bokeh.targetNode = self
        bokeh.advanceSimulationTime(18)

        plankton.zPosition = GameConfig.Z.plankton
        cameraNode.addChild(plankton)
        // Release motes into world space so the camera glides past them
        // (parallax / suspended-in-water feel) instead of them riding the screen.
        plankton.targetNode = self
        plankton.advanceSimulationTime(12)   // pre-fill the screen so it isn't empty at launch

        darkness.zPosition = GameConfig.Z.darkness
        darkness.alpha = 0
        cameraNode.addChild(darkness)

        vignette.zPosition = GameConfig.Z.vignette
        vignette.blendMode = .alpha
        cameraNode.addChild(vignette)

        cameraNode.addChild(hud)
        cameraNode.addChild(joystick)
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
        bokeh.particlePositionRange = CGVector(dx: viewport.width + 160,
                                               dy: viewport.height + 160)

        // Vignette stretched to frame the viewport (a touch larger so the dark
        // ring sits just past the screen edges rather than intruding).
        vignette.size = CGSize(width: viewport.width * 1.25, height: viewport.height * 1.35)

        // Joystick pinned to the bottom-left, clear of the landscape notch.
        let safeBottom = view?.safeAreaInsets.bottom ?? 0
        let safeLeft = view?.safeAreaInsets.left ?? 0
        joystick.position = CGPoint(
            x: -viewport.width / 2 + safeLeft + joystick.baseRadius + 28,
            y: -viewport.height / 2 + safeBottom + joystick.baseRadius + 24)
    }

    override func didChangeSize(_ oldSize: CGSize) {
        super.didChangeSize(oldSize)
        layout()
    }

    // MARK: Touch steering (virtual joystick, bottom-left)

    override func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent?) {
        guard stickTouch == nil else { return }
        for t in touches {
            if joystick.engage(at: t.location(in: cameraNode)) {
                stickTouch = t
                break
            }
        }
    }

    override func touchesMoved(_ touches: Set<UITouch>, with event: UIEvent?) {
        guard let st = stickTouch, touches.contains(st) else { return }
        joystick.drag(to: st.location(in: cameraNode))
    }

    override func touchesEnded(_ touches: Set<UITouch>, with event: UIEvent?) { endStick(touches) }
    override func touchesCancelled(_ touches: Set<UITouch>, with event: UIEvent?) { endStick(touches) }

    private func endStick(_ touches: Set<UITouch>) {
        guard let st = stickTouch, touches.contains(st) else { return }
        joystick.release()
        stickTouch = nil
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
        player.update(dt)

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

        hud.update(depthMeters: meters)

        // Color-grade the whole scene by depth: a faint teal wash near the
        // sunny surface deepening to indigo, then the black overlay takes over.
        let grade = smoothstep(2, 42, meters)
        blueTint.color = lerpColor(Palette.tintShallow, Palette.tintDeep, grade)
        blueTint.alpha = 0.05 + grade * 0.22
        darkness.alpha = smoothstep(6, 52, meters) * 0.85
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

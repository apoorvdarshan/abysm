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

    // Camera & screen-space overlays (children of the camera)
    private let cameraNode = SKCameraNode()
    private let blueTint = SKSpriteNode(color: Palette.blueTint, size: CGSize(width: 2400, height: 3400))
    private let darkness = SKSpriteNode(color: .black, size: CGSize(width: 2400, height: 3400))
    private let plankton = Particles.plankton()
    private let hud = DepthHUD()

    private var lastUpdateTime: TimeInterval = 0

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

        plankton.zPosition = GameConfig.Z.plankton
        cameraNode.addChild(plankton)
        plankton.advanceSimulationTime(12)   // pre-fill the screen so it isn't empty at launch

        darkness.zPosition = GameConfig.Z.darkness
        darkness.alpha = 0
        cameraNode.addChild(darkness)

        cameraNode.addChild(hud)
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
    }

    override func didChangeSize(_ oldSize: CGSize) {
        super.didChangeSize(oldSize)
        layout()
    }

    // MARK: Touch steering

    private func steer(_ touches: Set<UITouch>) {
        guard let touch = touches.first else { return }
        player.setTarget(touch.location(in: self))
    }

    override func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent?) { steer(touches) }
    override func touchesMoved(_ touches: Set<UITouch>, with event: UIEvent?) { steer(touches) }

    // MARK: Game loop

    override func update(_ currentTime: TimeInterval) {
        let dt: CGFloat
        if lastUpdateTime == 0 {
            dt = 1.0 / 60.0
        } else {
            dt = CGFloat(min(currentTime - lastUpdateTime, 1.0 / 20.0))   // cap big hitches
        }
        lastUpdateTime = currentTime

        player.update(dt)
        oceanSurface.update(currentTime)
        updateDepthEffects()
    }

    /// HUD read-out plus depth-driven darkening and tint.
    private func updateDepthEffects() {
        let depthPoints = max(0, -player.position.y)
        let meters = depthPoints / GameConfig.pointsPerMeter

        hud.update(depthMeters: meters)
        darkness.alpha = smoothstep(3, 48, meters) * 0.82
        blueTint.alpha = 0.06 + smoothstep(0, 40, meters) * 0.16
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

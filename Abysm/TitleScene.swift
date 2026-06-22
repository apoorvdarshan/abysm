//
//  TitleScene.swift
//  Abysm
//
//  The start screen: the ABYSM title over a sunlit-surface gradient, with
//  CONTINUE (resume the saved dive), NEW GAME, and a SOUND toggle. Works by
//  touch or game controller.
//

import UIKit
import SpriteKit
import GameController

final class TitleScene: SKScene {

    private let bg = SKSpriteNode()
    private let sun = SKSpriteNode(texture: TextureFactory.pixelSun(radius: 11))
    private let title = SKLabelNode(fontNamed: "PressStart2P-Regular")
    private let tagline = SKLabelNode(fontNamed: "PressStart2P-Regular")
    private let continueBtn = SKNode()
    private let newGameBtn = SKNode()
    private let soundBtn = SKNode()
    private var soundLbl: SKLabelNode?
    private let plankton = Particles.plankton()

    private let btnW: CGFloat = 250, btnH: CGFloat = 46
    private var soundOn = true
    private var controllerObserver: NSObjectProtocol?

    private let titleStops: [(UIColor, CGFloat)] = [
        (Palette.rgb(56, 150, 226), 0.0),
        (Palette.rgb(150, 206, 238), 0.34),
        (Palette.rgb(104, 198, 196), 0.42),
        (Palette.rgb(18, 64, 116), 1.0),
    ]

    override func didMove(to view: SKView) {
        anchorPoint = CGPoint(x: 0.5, y: 0.5)
        backgroundColor = Palette.rgb(20, 80, 140)
        soundOn = !AudioManager.shared.muted

        bg.zPosition = -10; addChild(bg)
        sun.zPosition = -8; addChild(sun)

        title.text = "ABYSM"; title.fontSize = 54; title.fontColor = .white
        title.verticalAlignmentMode = .center; title.horizontalAlignmentMode = .center
        title.zPosition = 5; addChild(title)

        tagline.text = "A DIVE TO THE BOTTOM OF THE SEA"; tagline.fontSize = 9
        tagline.fontColor = Palette.rgb(180, 238, 236)
        tagline.verticalAlignmentMode = .center; tagline.horizontalAlignmentMode = .center
        tagline.zPosition = 5; addChild(tagline)

        buildButton(continueBtn, "CONTINUE")
        buildButton(newGameBtn, "NEW GAME")
        soundLbl = buildButton(soundBtn, soundText())
        continueBtn.isHidden = !SaveManager.hasSave

        plankton.zPosition = 2
        plankton.targetNode = self
        plankton.advanceSimulationTime(10)
        addChild(plankton)

        layout()
        DispatchQueue.main.async { [weak self] in self?.layout() }

        setupControllers()
        AudioManager.shared.start()   // ambient bed plays under the title too
    }

    deinit {
        if let o = controllerObserver { NotificationCenter.default.removeObserver(o) }
    }

    @discardableResult
    private func buildButton(_ node: SKNode, _ text: String) -> SKLabelNode {
        let border = SKSpriteNode(color: Palette.rgb(150, 236, 232), size: CGSize(width: btnW + 6, height: btnH + 6))
        border.alpha = 0.75; border.zPosition = 0
        let plate = SKSpriteNode(color: Palette.rgb(9, 20, 44), size: CGSize(width: btnW, height: btnH))
        plate.alpha = 0.92; plate.zPosition = 1
        let label = SKLabelNode(fontNamed: "PressStart2P-Regular")
        label.text = text; label.fontSize = 14; label.fontColor = .white
        label.verticalAlignmentMode = .center; label.horizontalAlignmentMode = .center; label.zPosition = 2
        node.addChild(border); node.addChild(plate); node.addChild(label)
        node.zPosition = 5
        addChild(node)
        return label
    }

    private func soundText() -> String { "SOUND: \(soundOn ? "ON" : "OFF")" }

    private func layout() {
        let w = size.width, h = size.height
        bg.texture = TextureFactory.pixelGradient(size: CGSize(width: w, height: h),
                                                  pixel: GameConfig.pixel, stops: titleStops)
        bg.size = CGSize(width: w, height: h)
        sun.size = CGSize(width: 150, height: 150)
        sun.position = CGPoint(x: w * 0.30, y: h * 0.28)

        title.position = CGPoint(x: 0, y: h * 0.24)
        tagline.position = CGPoint(x: 0, y: h * 0.24 - 46)

        let gap = btnH + 18
        var y = -h * 0.04
        if !continueBtn.isHidden { continueBtn.position = CGPoint(x: 0, y: y); y -= gap }
        newGameBtn.position = CGPoint(x: 0, y: y); y -= gap
        soundBtn.position = CGPoint(x: 0, y: y)
    }

    override func didChangeSize(_ oldSize: CGSize) { super.didChangeSize(oldSize); layout() }

    // MARK: Input

    override func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent?) {
        guard let t = touches.first else { return }
        let p = t.location(in: self)
        if !continueBtn.isHidden, hit(continueBtn, p) { continueGame() }
        else if hit(newGameBtn, p) { newGame() }
        else if hit(soundBtn, p) { toggleSound() }
    }

    private func hit(_ node: SKNode, _ p: CGPoint) -> Bool {
        abs(p.x - node.position.x) <= btnW / 2 && abs(p.y - node.position.y) <= btnH / 2
    }

    private func setupControllers() {
        controllerObserver = NotificationCenter.default.addObserver(
            forName: .GCControllerDidConnect, object: nil, queue: .main) { [weak self] note in
            if let c = note.object as? GCController { self?.attach(c) }
        }
        GCController.controllers().forEach(attach)
    }

    private func attach(_ controller: GCController) {
        guard let gp = controller.extendedGamepad else { return }
        gp.buttonA.pressedChangedHandler = { [weak self] _, _, pressed in
            guard pressed, let self = self else { return }
            if SaveManager.hasSave { self.continueGame() } else { self.newGame() }
        }
        gp.buttonY.pressedChangedHandler = { [weak self] _, _, pressed in
            if pressed { self?.newGame() }
        }
        gp.buttonMenu.pressedChangedHandler = { [weak self] _, _, pressed in
            if pressed { self?.toggleSound() }
        }
    }

    // MARK: Actions

    private func toggleSound() {
        soundOn.toggle()
        AudioManager.shared.setMuted(!soundOn)
        soundLbl?.text = soundText()
    }

    private func continueGame() { startGame(depth: SaveManager.depthMeters, x: SaveManager.x) }

    private func newGame() {
        SaveManager.clearResume()
        startGame(depth: nil, x: nil)
    }

    private func startGame(depth: CGFloat?, x: CGFloat?) {
        guard let v = view else { return }
        let g = GameScene(size: v.bounds.size)
        g.scaleMode = .resizeFill
        g.startDepthMeters = depth
        g.startX = x
        v.presentScene(g, transition: .fade(with: .black, duration: 0.6))
    }
}

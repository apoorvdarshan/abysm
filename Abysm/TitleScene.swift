//
//  TitleScene.swift
//  Abysm
//
//  The start screen: the ABYSM title over a sunlit-surface scene with a little
//  pixel-art reef (coral, kelp, a rock spire), the diver drifting, and fish.
//  CONTINUE (resume the saved dive), NEW GAME, and a SOUND toggle. Touch or
//  game controller.
//

import UIKit
import SpriteKit
import GameController

final class TitleScene: SKScene {

    private let bg = SKSpriteNode()
    private let sun = SKSpriteNode(texture: TextureFactory.pixelSun(radius: 11))
    private let title = SKLabelNode(fontNamed: "PressStart2P-Regular")
    private let titleShadow = SKLabelNode(fontNamed: "PressStart2P-Regular")
    private let tagline = SKLabelNode(fontNamed: "PressStart2P-Regular")
    private let taglineShadow = SKLabelNode(fontNamed: "PressStart2P-Regular")

    // Reef diorama.
    private let coral = SKSpriteNode()
    private let kelpL = SKSpriteNode()
    private let kelpR = SKSpriteNode()
    private let pillar = SKSpriteNode()
    private let diver = SKSpriteNode()
    private let fish1 = SKSpriteNode()
    private let fish2 = SKSpriteNode()
    private let cloud1 = SKSpriteNode()
    private let cloud2 = SKSpriteNode()
    private let cloud3 = SKSpriteNode()
    private let bigCreature = SKSpriteNode()

    private let continueBtn = SKNode()
    private let newGameBtn = SKNode()
    private let soundBtn = SKNode()
    private var soundLbl: SKLabelNode?
    private let plankton = Particles.plankton()

    private let btnW: CGFloat = 250, btnH: CGFloat = 46
    private var soundOn = true
    private var controllerObserver: NSObjectProtocol?

    // Controller menu navigation.
    private var items: [(node: SKNode, run: () -> Void)] = []
    private var selectedIndex = 0
    private var lastT: TimeInterval = 0
    private var navCooldown: CGFloat = 0

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

        buildReef()

        // Title with a soft shadow.
        configureLabel(titleShadow, size: 54, color: Palette.rgb(8, 28, 56), z: 4)
        configureLabel(title, size: 54, color: .white, z: 5)
        title.text = "ABYSM"; titleShadow.text = "ABYSM"

        configureLabel(taglineShadow, size: 11, color: Palette.rgb(6, 22, 44), z: 4)
        configureLabel(tagline, size: 11, color: .white, z: 5)
        tagline.text = "A DIVE TO THE BOTTOM OF THE SEA"
        taglineShadow.text = tagline.text

        buildButton(continueBtn, "CONTINUE")
        buildButton(newGameBtn, "NEW GAME")
        soundLbl = buildButton(soundBtn, soundText())
        continueBtn.isHidden = !SaveManager.hasSave

        // Ordered list for controller navigation (matches the visible buttons).
        if SaveManager.hasSave { items.append((continueBtn, { [weak self] in self?.continueGame() })) }
        items.append((newGameBtn, { [weak self] in self?.newGame() }))
        items.append((soundBtn, { [weak self] in self?.toggleSound() }))
        highlightSelected()

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
        // NB: do NOT clear the controller's handlers here — see GameScene.deinit.
    }

    private func configureLabel(_ l: SKLabelNode, size: CGFloat, color: UIColor, z: CGFloat) {
        l.fontSize = size; l.fontColor = color
        l.verticalAlignmentMode = .center; l.horizontalAlignmentMode = .center
        l.zPosition = z; addChild(l)
    }

    // MARK: Reef diorama

    private func buildReef() {
        deco(diver, "diver0", width: 132, z: -3, anchorBottom: false)
        deco(coral, "bg_coral", width: 150, z: -4, anchorBottom: true)
        deco(kelpL, "bg_kelp", width: 82, z: -3, anchorBottom: true)
        deco(kelpR, "bg_kelp", width: 68, z: -6, anchorBottom: true); kelpR.xScale = -1
        deco(pillar, "bg_pillar", width: 132, z: -6, anchorBottom: true)
        deco(fish1, "school_fish", width: 48, z: -4, anchorBottom: false)
        deco(fish2, "school_fish", width: 36, z: -5, anchorBottom: false)
        deco(cloud1, "cloud_a", width: 200, z: -9, anchorBottom: false)
        deco(cloud2, "cloud_b", width: 150, z: -9, anchorBottom: false)
        deco(cloud3, "cloud_a", width: 168, z: -9, anchorBottom: false); cloud3.xScale = -1
        deco(bigCreature, "creature_manatee", width: 250, z: -7, anchorBottom: false)
        bigCreature.color = Palette.rgb(36, 86, 128); bigCreature.colorBlendFactor = 0.4; bigCreature.alpha = 0.7

        // Gentle life.
        let bob = SKAction.sequence([move(0, 8, 1.7), move(0, -8, 1.7)])
        diver.run(.repeatForever(bob))
        diver.run(.repeatForever(.sequence([rot(0.06, 2.3), rot(-0.06, 2.3)])))
        kelpL.run(.repeatForever(.sequence([rot(0.10, 2.1), rot(-0.10, 2.1)])))
        kelpR.run(.repeatForever(.sequence([rot(-0.10, 2.4), rot(0.10, 2.4)])))
        fish1.run(.repeatForever(.sequence([move(150, 12, 5), move(-150, -12, 5)])))
        fish2.run(.repeatForever(.sequence([move(-120, -8, 6), move(120, 8, 6)])))
        cloud1.run(.repeatForever(.sequence([move(60, 0, 9), move(-60, 0, 9)])))
        cloud2.run(.repeatForever(.sequence([move(-50, 0, 11), move(50, 0, 11)])))
        cloud3.run(.repeatForever(.sequence([move(70, 0, 12), move(-70, 0, 12)])))
        bigCreature.run(.repeatForever(.sequence([move(90, 10, 15), move(-90, -10, 15)])))
        bigCreature.run(.repeatForever(.sequence([rot(0.02, 3.2), rot(-0.02, 3.2)])))
    }

    private func deco(_ node: SKSpriteNode, _ name: String, width: CGFloat, z: CGFloat, anchorBottom: Bool) {
        let t = SKTexture(imageNamed: name); t.filteringMode = .nearest
        node.texture = t
        let aspect = t.size().width > 0 ? t.size().height / t.size().width : 1
        node.size = CGSize(width: width, height: width * aspect)
        if anchorBottom { node.anchorPoint = CGPoint(x: 0.5, y: 0) }
        node.zPosition = z
        addChild(node)
    }

    private func move(_ x: CGFloat, _ y: CGFloat, _ d: TimeInterval) -> SKAction {
        let a = SKAction.moveBy(x: x, y: y, duration: d); a.timingMode = .easeInEaseOut; return a
    }
    private func rot(_ a: CGFloat, _ d: TimeInterval) -> SKAction {
        let r = SKAction.rotate(toAngle: a, duration: d); r.timingMode = .easeInEaseOut; return r
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
        node.zPosition = 6
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
        sun.position = CGPoint(x: w * 0.31, y: h * 0.30)

        title.position = CGPoint(x: 0, y: h * 0.26)
        titleShadow.position = CGPoint(x: 3, y: h * 0.26 - 3)
        tagline.position = CGPoint(x: 0, y: h * 0.26 - 48)
        taglineShadow.position = CGPoint(x: 2, y: h * 0.26 - 48 - 2)

        // Reef along the bottom edges (clear of the centered buttons).
        let floor = -h / 2 - 6
        coral.position  = CGPoint(x: -w * 0.40, y: floor)
        kelpL.position  = CGPoint(x: -w * 0.29, y: floor)
        pillar.position = CGPoint(x:  w * 0.43, y: floor)
        kelpR.position  = CGPoint(x:  w * 0.33, y: floor)
        diver.position  = CGPoint(x: -w * 0.31, y: h * 0.02)
        fish1.position  = CGPoint(x:  w * 0.20, y: -h * 0.02)
        fish2.position  = CGPoint(x:  w * 0.28, y: -h * 0.14)
        cloud1.position = CGPoint(x: -w * 0.34, y: h * 0.34)
        cloud2.position = CGPoint(x:  w * 0.08, y: h * 0.40)
        cloud3.position = CGPoint(x:  w * 0.32, y: h * 0.30)
        bigCreature.position = CGPoint(x: -w * 0.16, y: -h * 0.18)

        let gap = btnH + 18
        var y = -h * 0.06
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
            guard pressed, let self = self, self.selectedIndex < self.items.count else { return }
            self.items[self.selectedIndex].run()
        }
        gp.dpad.up.pressedChangedHandler   = { [weak self] _, _, p in if p { self?.moveSelection(-1) } }
        gp.dpad.down.pressedChangedHandler = { [weak self] _, _, p in if p { self?.moveSelection(1) } }
    }

    // MARK: Controller menu navigation

    override func update(_ currentTime: TimeInterval) {
        let dt = lastT == 0 ? 0 : currentTime - lastT
        lastT = currentTime
        navCooldown = max(0, navCooldown - CGFloat(dt))
        if let gp = GCController.current?.extendedGamepad, navCooldown == 0 {
            let y = gp.leftThumbstick.yAxis.value
            if y > 0.5 { moveSelection(-1); navCooldown = 0.22 }
            else if y < -0.5 { moveSelection(1); navCooldown = 0.22 }
        }
        highlightSelected()
    }

    private func moveSelection(_ d: Int) {
        guard !items.isEmpty else { return }
        selectedIndex = (selectedIndex + d + items.count) % items.count
        highlightSelected()
    }

    private func highlightSelected() {
        let hasController = GCController.current != nil
        for (i, it) in items.enumerated() {
            let sel = i == selectedIndex
            it.node.setScale(hasController && sel ? 1.07 : 1.0)
            it.node.alpha = (!hasController || sel) ? 1.0 : 0.8
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

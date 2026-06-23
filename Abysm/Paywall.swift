//
//  Paywall.swift
//  Abysm
//
//  The "Unlock the Deep" modal shown at the 1,000 m gate. Framed in a pixel-art
//  sunken-treasure wooden plaque (brass + rope corners) with a glowing pixel
//  anglerfish, warm brass lettering, and a carved gold UNLOCK button. Three
//  choices: UNLOCK (buy), RESTORE, or KEEP EXPLORING (dismiss and stay in the
//  free zones). Lives as a camera child, centered on screen.
//

import SpriteKit

final class Paywall: SKNode {

    var onUnlock: () -> Void = {}
    var onRestore: () -> Void = {}
    var onDismiss: () -> Void = {}

    /// While a purchase/restore is in flight, taps are ignored.
    private(set) var isBusy = false

    // 2× the 192×172 frame texture → crisp integer-scaled pixels.
    private let panelW: CGFloat = 384, panelH: CGFloat = 344
    private let unlockLabel = GameFont.label()
    private let statusLabel = GameFont.label()

    // Treasure palette.
    private let brass   = Palette.rgb(244, 212, 132)
    private let cream   = Palette.rgb(228, 214, 184)
    private let muted   = Palette.rgb(150, 134, 100)

    private var unlockRect = CGRect.zero
    private var restoreRect = CGRect.zero
    private var dismissRect = CGRect.zero

    override init() {
        super.init()
        zPosition = GameConfig.Z.intro + 2
        build()
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    // MARK: Build

    private func build() {
        // Dim the world behind the modal.
        let dim = SKSpriteNode(color: .black, size: CGSize(width: 4200, height: 3200))
        dim.alpha = 0.72; dim.zPosition = 0
        addChild(dim)

        // Wooden treasure-plaque frame (pixel art, integer-scaled, dark center).
        let frameTex = SKTexture(imageNamed: "paywall_frame")
        frameTex.filteringMode = .nearest
        let frame = SKSpriteNode(texture: frameTex)
        frame.size = CGSize(width: panelW, height: panelH)
        frame.zPosition = 1
        addChild(frame)

        // Pixel anglerfish hero.
        let heroTex = SKTexture(imageNamed: "paywall_hero")
        heroTex.filteringMode = .nearest
        let hero = SKSpriteNode(texture: heroTex)
        hero.size = CGSize(width: 60, height: 60)
        hero.position = CGPoint(x: 0, y: 96)
        hero.zPosition = 3
        addChild(hero)

        // Title — carved brass.
        let title = GameFont.label()
        title.text = L("paywall.title", "UNLOCK THE DEEP")
        title.fontSize = 15; title.fontColor = brass
        title.horizontalAlignmentMode = .center; title.verticalAlignmentMode = .center
        title.position = CGPoint(x: 0, y: 52); title.zPosition = 3
        addChild(title)

        // Body (wraps).
        let body = GameFont.label()
        body.text = L("paywall.body",
            "Dive past 1,000 m to the trench floor — the deep zones, ~45 more creatures, and landmarks like the Titanic.")
        body.fontSize = 8; body.fontColor = cream
        body.horizontalAlignmentMode = .center; body.verticalAlignmentMode = .top
        body.numberOfLines = 0; body.preferredMaxLayoutWidth = 270
        body.lineBreakMode = .byWordWrapping
        body.position = CGPoint(x: 0, y: 26); body.zPosition = 3
        addChild(body)

        // Status line (purchasing / restoring / failed); hidden until needed.
        statusLabel.fontSize = 8; statusLabel.fontColor = brass
        statusLabel.horizontalAlignmentMode = .center; statusLabel.verticalAlignmentMode = .center
        statusLabel.position = CGPoint(x: 0, y: -24); statusLabel.zPosition = 4
        statusLabel.isHidden = true
        addChild(statusLabel)

        // UNLOCK — carved gold button.
        let unlock = SKNode()
        unlock.position = CGPoint(x: 0, y: -56); unlock.zPosition = 3
        goldButton(into: unlock, size: CGSize(width: 268, height: 42))
        unlockLabel.fontSize = 13; unlockLabel.fontColor = Palette.rgb(46, 28, 10)
        unlockLabel.horizontalAlignmentMode = .center; unlockLabel.verticalAlignmentMode = .center
        unlockLabel.zPosition = 3
        unlock.addChild(unlockLabel)
        addChild(unlock)
        unlockRect = CGRect(x: -134, y: -56 - 21, width: 268, height: 42)
        setPrice("$2.99")

        // RESTORE / KEEP EXPLORING — bare text choices.
        restoreRect = makeTextButton(L("paywall.restore", "RESTORE"),
                                     y: -100, color: cream, size: 10)
        dismissRect = makeTextButton(L("paywall.keep_exploring", "KEEP EXPLORING"),
                                     y: -128, color: muted, size: 9)
    }

    /// A carved, beveled gold button (top highlight + bottom shadow) for that
    /// chunky pixel look.
    private func goldButton(into node: SKNode, size: CGSize) {
        let inset: CGFloat = 4
        let outer = SKSpriteNode(color: Palette.rgb(58, 38, 16), size: size)
        outer.zPosition = 0
        let face = SKSpriteNode(color: Palette.rgb(214, 168, 74),
                                size: CGSize(width: size.width - inset * 2, height: size.height - inset * 2))
        face.zPosition = 1
        let hi = SKSpriteNode(color: Palette.rgb(244, 214, 142), size: CGSize(width: face.size.width, height: 5))
        hi.position = CGPoint(x: 0, y: face.size.height / 2 - 2.5); hi.zPosition = 2
        let sh = SKSpriteNode(color: Palette.rgb(150, 110, 40), size: CGSize(width: face.size.width, height: 4))
        sh.position = CGPoint(x: 0, y: -face.size.height / 2 + 2); sh.zPosition = 2
        node.addChild(outer); node.addChild(face); node.addChild(hi); node.addChild(sh)
    }

    /// A bare text button (no plate). Returns its tappable rect in node space.
    private func makeTextButton(_ text: String, y: CGFloat, color: UIColor, size: CGFloat) -> CGRect {
        let l = GameFont.label()
        l.text = text; l.fontSize = size; l.fontColor = color
        l.horizontalAlignmentMode = .center; l.verticalAlignmentMode = .center
        l.position = CGPoint(x: 0, y: y); l.zPosition = 3
        addChild(l)
        let h: CGFloat = 28
        return CGRect(x: -panelW / 2, y: y - h / 2, width: panelW, height: h)
    }

    // MARK: State

    func setPrice(_ price: String) {
        unlockLabel.text = "\(L("paywall.unlock", "UNLOCK"))   \(price)"
    }

    func setStatus(_ text: String?) {
        statusLabel.text = text ?? ""
        statusLabel.isHidden = (text == nil)
    }

    func setBusy(_ busy: Bool) {
        isBusy = busy
        unlockLabel.alpha = busy ? 0.4 : 1.0
    }

    /// Fresh state each time the modal is shown.
    func reset(price: String) {
        setBusy(false)
        setStatus(nil)
        setPrice(price)
    }

    /// Route a tap (in this node's coordinate space) to a button.
    func handleTap(_ p: CGPoint) {
        guard !isBusy else { return }
        if unlockRect.contains(p) { onUnlock() }
        else if restoreRect.contains(p) { onRestore() }
        else if dismissRect.contains(p) { onDismiss() }
    }
}

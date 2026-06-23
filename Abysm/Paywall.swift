//
//  Paywall.swift
//  Abysm
//
//  The "Unlock the Deep" modal shown at the 1,000 m gate. Framed in a pixel-art
//  sunken-treasure wooden plaque (rope corners) with a glowing pixel anglerfish,
//  warm brass lettering, and a carved gold UNLOCK button. Every element — title,
//  body, UNLOCK, RESTORE, KEEP EXPLORING — sits inside the plaque's dark center
//  window (measured from the art). Three choices: buy, restore, or dismiss.
//

import SpriteKit

final class Paywall: SKNode {

    var onUnlock: () -> Void = {}
    var onRestore: () -> Void = {}
    var onDismiss: () -> Void = {}

    /// While a purchase/restore is in flight, taps are ignored.
    private(set) var isBusy = false

    // Plaque = 2× the 288×176 frame texture (crisp integer scaling). The dark
    // center window measured from the art is x[-236,234], y[-102,104].
    static let panelW: CGFloat = 576, panelH: CGFloat = 352
    private let winTop: CGFloat = 104, winBottom: CGFloat = -102

    private let unlockLabel = GameFont.label()
    private let statusLabel = GameFont.label()

    private let brass = Palette.rgb(244, 212, 132)
    private let cream = Palette.rgb(228, 214, 184)
    private let muted = Palette.rgb(156, 140, 104)

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
        frame.size = CGSize(width: Self.panelW, height: Self.panelH)
        frame.zPosition = 1
        addChild(frame)

        // Pixel anglerfish hero (top of the window).
        let heroTex = SKTexture(imageNamed: "paywall_hero")
        heroTex.filteringMode = .nearest
        let hero = SKSpriteNode(texture: heroTex)
        hero.size = CGSize(width: 40, height: 40)
        hero.position = CGPoint(x: 0, y: 80)
        hero.zPosition = 3
        addChild(hero)

        // Title — carved brass.
        let title = GameFont.label()
        title.text = L("paywall.title", "UNLOCK THE DEEP")
        title.fontSize = 14; title.fontColor = brass
        title.horizontalAlignmentMode = .center; title.verticalAlignmentMode = .center
        title.position = CGPoint(x: 0, y: 54); title.zPosition = 3
        addChild(title)

        // Body (wraps; window is wide so it fits in ~2 lines).
        let body = GameFont.label()
        body.text = L("paywall.body",
            "Dive past 1,000 m to the trench floor — the deep zones, ~45 more creatures, and landmarks like the Titanic.")
        body.fontSize = 8; body.fontColor = cream
        body.horizontalAlignmentMode = .center; body.verticalAlignmentMode = .top
        body.numberOfLines = 0; body.preferredMaxLayoutWidth = 440
        body.lineBreakMode = .byWordWrapping
        body.position = CGPoint(x: 0, y: 38); body.zPosition = 3
        addChild(body)

        // Status line (purchasing / restoring / failed); over the button, hidden.
        statusLabel.fontSize = 8; statusLabel.fontColor = brass
        statusLabel.horizontalAlignmentMode = .center; statusLabel.verticalAlignmentMode = .center
        statusLabel.position = CGPoint(x: 0, y: -16); statusLabel.zPosition = 4
        statusLabel.isHidden = true
        addChild(statusLabel)

        // UNLOCK — carved gold button.
        let unlock = SKNode()
        unlock.position = CGPoint(x: 0, y: -18); unlock.zPosition = 3
        goldButton(into: unlock, size: CGSize(width: 300, height: 34))
        unlockLabel.fontSize = 13; unlockLabel.fontColor = Palette.rgb(46, 28, 10)
        unlockLabel.horizontalAlignmentMode = .center; unlockLabel.verticalAlignmentMode = .center
        unlockLabel.zPosition = 3
        unlock.addChild(unlockLabel)
        addChild(unlock)
        unlockRect = CGRect(x: -150, y: -18 - 17, width: 300, height: 34)
        setPrice("$2.99")

        // RESTORE / KEEP EXPLORING — bare text choices, inside the window.
        restoreRect = makeTextButton(L("paywall.restore", "RESTORE"),
                                     y: -54, color: cream, size: 9)
        dismissRect = makeTextButton(L("paywall.keep_exploring", "KEEP EXPLORING"),
                                     y: -82, color: muted, size: 8)
    }

    /// A carved, beveled gold button (top highlight + bottom shadow).
    private func goldButton(into node: SKNode, size: CGSize) {
        let inset: CGFloat = 4
        let outer = SKSpriteNode(color: Palette.rgb(58, 38, 16), size: size); outer.zPosition = 0
        let face = SKSpriteNode(color: Palette.rgb(214, 168, 74),
                                size: CGSize(width: size.width - inset * 2, height: size.height - inset * 2))
        face.zPosition = 1
        let hi = SKSpriteNode(color: Palette.rgb(244, 214, 142), size: CGSize(width: face.size.width, height: 4))
        hi.position = CGPoint(x: 0, y: face.size.height / 2 - 2); hi.zPosition = 2
        let sh = SKSpriteNode(color: Palette.rgb(150, 110, 40), size: CGSize(width: face.size.width, height: 3))
        sh.position = CGPoint(x: 0, y: -face.size.height / 2 + 1.5); sh.zPosition = 2
        node.addChild(outer); node.addChild(face); node.addChild(hi); node.addChild(sh)
    }

    /// A bare text button (no plate). Returns its tappable rect in node space,
    /// kept inside the plaque window width so taps never spill onto the wood.
    private func makeTextButton(_ text: String, y: CGFloat, color: UIColor, size: CGFloat) -> CGRect {
        let l = GameFont.label()
        l.text = text; l.fontSize = size; l.fontColor = color
        l.horizontalAlignmentMode = .center; l.verticalAlignmentMode = .center
        l.position = CGPoint(x: 0, y: y); l.zPosition = 3
        addChild(l)
        return CGRect(x: -235, y: y - 13, width: 470, height: 26)
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

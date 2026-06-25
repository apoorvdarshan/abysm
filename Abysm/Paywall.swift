//
//  Paywall.swift
//  Abysm
//
//  The "Unlock the Deep" modal shown at the 1,000 m gate. Framed in a pixel-art
//  sunken-treasure wooden plaque (rope corners) with a glowing pixel anglerfish
//  and warm brass lettering. Three carved buttons stacked in the dark center —
//  UNLOCK (gold), KEEP EXPLORING and RESTORE (bronze). Touch or game controller
//  (stick/d-pad highlights, A activates).
//

import SpriteKit
import GameController

final class Paywall: SKNode {

    var onUnlock: () -> Void = {}
    var onRestore: () -> Void = {}
    var onDismiss: () -> Void = {}

    /// While a purchase/restore is in flight, taps/clicks are ignored.
    private(set) var isBusy = false

    // Plaque = 2× the 288×176 frame texture (crisp integer scaling). Dark center
    // window measured from the art: x[-235,235], y[-102,104].
    static let panelW: CGFloat = 576, panelH: CGFloat = 352

    private let brass = Palette.rgb(244, 212, 132)
    private let cream = Palette.rgb(228, 214, 184)

    private let unlockLabel = GameFont.label()
    private let statusLabel = GameFont.label()

    // Controller navigation: [UNLOCK, KEEP EXPLORING, RESTORE].
    private var buttons: [SKNode] = []
    private var selected = 0

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

        // Wooden treasure-plaque frame (pixel art, integer-scaled, transparent
        // outside the wood, dark center).
        let frameTex = SKTexture(imageNamed: "paywall_frame")
        frameTex.filteringMode = .nearest
        let frame = SKSpriteNode(texture: frameTex)
        frame.size = CGSize(width: Self.panelW, height: Self.panelH)
        frame.zPosition = 1
        addChild(frame)

        // Pixel anglerfish hero.
        let heroTex = SKTexture(imageNamed: "paywall_hero")
        heroTex.filteringMode = .nearest
        let hero = SKSpriteNode(texture: heroTex)
        hero.size = CGSize(width: 30, height: 30)
        hero.position = CGPoint(x: 0, y: 88)
        hero.zPosition = 3
        addChild(hero)

        // Title — carved brass.
        let title = GameFont.label()
        title.text = L("paywall.title", "UNLOCK THE DEEP")
        title.fontSize = 13; title.fontColor = brass
        title.horizontalAlignmentMode = .center; title.verticalAlignmentMode = .center
        title.position = CGPoint(x: 0, y: 64); title.zPosition = 3
        addChild(title)

        // Body (wraps to 2–3 lines depending on locale; the longest Latin
        // translations run ~128 chars, so use a smaller size + wider wrap so they
        // don't crowd the UNLOCK button below).
        let body = GameFont.label()
        body.text = L("paywall.body",
            "Dive past 1,000 m to the trench floor — the deep zones, ~45 more creatures, and landmarks like the Titanic.")
        body.fontSize = 7; body.fontColor = cream
        body.horizontalAlignmentMode = .center; body.verticalAlignmentMode = .top
        body.numberOfLines = 0; body.preferredMaxLayoutWidth = 470
        body.lineBreakMode = .byWordWrapping
        body.position = CGPoint(x: 0, y: 46); body.zPosition = 3
        addChild(body)

        // Status line (purchasing / restoring / failed); over UNLOCK, hidden.
        statusLabel.fontSize = 8; statusLabel.fontColor = brass
        statusLabel.horizontalAlignmentMode = .center; statusLabel.verticalAlignmentMode = .center
        statusLabel.position = CGPoint(x: 0, y: 2); statusLabel.zPosition = 5
        statusLabel.isHidden = true
        addChild(statusLabel)

        // UNLOCK — primary gold button (keeps a label ref for the price).
        let unlock = SKNode()
        unlock.position = CGPoint(x: 0, y: 2); unlock.zPosition = 3
        carvedButton(into: unlock, size: CGSize(width: 300, height: 34), primary: true)
        unlockLabel.fontSize = 13; unlockLabel.fontColor = Palette.rgb(46, 28, 10)
        unlockLabel.horizontalAlignmentMode = .center; unlockLabel.verticalAlignmentMode = .center
        unlockLabel.zPosition = 3
        unlock.addChild(unlockLabel)
        addChild(unlock)
        buttons.append(unlock)
        unlockRect = CGRect(x: -150, y: 2 - 17, width: 300, height: 34)
        setPrice("$2.99")

        // KEEP EXPLORING — secondary bronze button.
        let (keep, keepRect) = makeButton(L("paywall.keep_exploring", "KEEP EXPLORING"),
                                          y: -38, w: 240, h: 30)
        buttons.append(keep); dismissRect = keepRect

        // RESTORE — secondary bronze button, below both.
        let (rest, restRect) = makeButton(L("paywall.restore", "RESTORE"),
                                          y: -76, w: 240, h: 30)
        buttons.append(rest); restoreRect = restRect

        highlight()
    }

    /// A carved, beveled button (top highlight + bottom shadow). `primary` is the
    /// bright gold UNLOCK; otherwise a muted bronze.
    private func carvedButton(into node: SKNode, size: CGSize, primary: Bool) {
        let outerC = primary ? Palette.rgb(58, 38, 16) : Palette.rgb(44, 30, 14)
        let faceC  = primary ? Palette.rgb(214, 168, 74) : Palette.rgb(132, 98, 48)
        let hiC    = primary ? Palette.rgb(244, 214, 142) : Palette.rgb(176, 140, 80)
        let shC    = primary ? Palette.rgb(150, 110, 40) : Palette.rgb(86, 60, 26)
        let inset: CGFloat = 4
        let outer = SKSpriteNode(color: outerC, size: size); outer.zPosition = 0
        let face = SKSpriteNode(color: faceC,
                                size: CGSize(width: size.width - inset * 2, height: size.height - inset * 2))
        face.zPosition = 1
        let hi = SKSpriteNode(color: hiC, size: CGSize(width: face.size.width, height: 4))
        hi.position = CGPoint(x: 0, y: face.size.height / 2 - 2); hi.zPosition = 2
        let sh = SKSpriteNode(color: shC, size: CGSize(width: face.size.width, height: 3))
        sh.position = CGPoint(x: 0, y: -face.size.height / 2 + 1.5); sh.zPosition = 2
        node.addChild(outer); node.addChild(face); node.addChild(hi); node.addChild(sh)
    }

    /// A labeled bronze button. Returns its container node and tappable rect.
    private func makeButton(_ text: String, y: CGFloat, w: CGFloat, h: CGFloat) -> (SKNode, CGRect) {
        let node = SKNode(); node.position = CGPoint(x: 0, y: y); node.zPosition = 3
        carvedButton(into: node, size: CGSize(width: w, height: h), primary: false)
        let l = GameFont.label()
        l.text = text; l.fontSize = 11; l.fontColor = Palette.rgb(238, 224, 192)
        l.horizontalAlignmentMode = .center; l.verticalAlignmentMode = .center; l.zPosition = 3
        node.addChild(l); addChild(node)
        return (node, CGRect(x: -w / 2, y: y - h / 2, width: w, height: h))
    }

    // MARK: Controller navigation

    /// Highlight the selected button (only when a controller is connected).
    func highlight() {
        let has = GCController.current != nil
        for (i, b) in buttons.enumerated() {
            let sel = (i == selected)
            b.setScale(has && sel ? 1.07 : 1.0)
            b.alpha = (!has || sel) ? 1.0 : 0.7
        }
    }

    func moveSelection(_ d: Int) {
        guard !buttons.isEmpty else { return }
        selected = (selected + d + buttons.count) % buttons.count
        highlight()
    }

    /// Activate the highlighted button (controller A).
    func activateSelected() {
        // KEEP EXPLORING stays live even while busy, so the modal is always
        // escapable (e.g. if a purchase/restore stalls).
        if selected == 1 { onDismiss(); return }
        guard !isBusy else { return }
        switch selected {
        case 0: onUnlock()
        default: onRestore()
        }
    }

    // MARK: State

    func setPrice(_ price: String) {
        // Wrap the LTR price in bidi isolates (U+2068 FSI … U+2069 PDI) so its
        // order/spacing stay correct when the label is RTL (e.g. Arabic).
        let isolated = "\u{2068}\(price)\u{2069}"
        unlockLabel.text = "\(L("paywall.unlock", "UNLOCK"))\u{00A0}\u{00A0}\(isolated)"
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
        selected = 0
        setBusy(false)
        setStatus(nil)
        setPrice(price)
        highlight()
    }

    /// Route a tap (in this node's coordinate space) to a button.
    func handleTap(_ p: CGPoint) {
        // KEEP EXPLORING stays live even while busy (always an escape hatch).
        if dismissRect.contains(p) { onDismiss(); return }
        guard !isBusy else { return }
        if unlockRect.contains(p) { onUnlock() }
        else if restoreRect.contains(p) { onRestore() }
    }
}

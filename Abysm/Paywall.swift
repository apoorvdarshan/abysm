//
//  Paywall.swift
//  Abysm
//
//  The "Unlock the Deep" pixel modal shown at the 1,000 m gate. Same plate +
//  cyan-border visual language as the pause menu, with a pixel anglerfish hero.
//  Three choices: UNLOCK (buy), RESTORE, or KEEP EXPLORING (dismiss and stay in
//  the free zones). Lives as a camera child, centered on screen.
//

import SpriteKit

final class Paywall: SKNode {

    var onUnlock: () -> Void = {}
    var onRestore: () -> Void = {}
    var onDismiss: () -> Void = {}

    /// While a purchase/restore is in flight, taps are ignored.
    private(set) var isBusy = false

    private let panelW: CGFloat = 360, panelH: CGFloat = 340
    private let unlockLabel = GameFont.label()
    private let statusLabel = GameFont.label()

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
        dim.alpha = 0.7; dim.zPosition = 0
        addChild(dim)

        // Panel: cyan border + dark navy plate (matches the menus).
        let border = SKSpriteNode(color: Palette.rgb(150, 236, 232),
                                  size: CGSize(width: panelW + 6, height: panelH + 6))
        border.alpha = 0.8; border.zPosition = 1
        let plate = SKSpriteNode(color: Palette.rgb(9, 20, 44), size: CGSize(width: panelW, height: panelH))
        plate.alpha = 0.97; plate.zPosition = 2
        addChild(border); addChild(plate)

        // Pixel anglerfish hero.
        let heroTex = SKTexture(imageNamed: "paywall_hero")
        heroTex.filteringMode = .nearest
        let hero = SKSpriteNode(texture: heroTex)
        hero.size = CGSize(width: 72, height: 72)
        hero.position = CGPoint(x: 0, y: 118)
        hero.zPosition = 3
        addChild(hero)

        // Title.
        let title = GameFont.label()
        title.text = L("paywall.title", "UNLOCK THE DEEP")
        title.fontSize = 17; title.fontColor = Palette.rgb(150, 236, 232)
        title.horizontalAlignmentMode = .center; title.verticalAlignmentMode = .center
        title.position = CGPoint(x: 0, y: 70); title.zPosition = 3
        addChild(title)

        // Body (wraps).
        let body = GameFont.label()
        body.text = L("paywall.body",
            "Dive past 1,000 m to the trench floor — the deep zones, ~45 more creatures, and landmarks like the Titanic.")
        body.fontSize = 8; body.fontColor = Palette.rgb(212, 228, 238)
        body.horizontalAlignmentMode = .center; body.verticalAlignmentMode = .top
        body.numberOfLines = 0; body.preferredMaxLayoutWidth = panelW - 56
        body.lineBreakMode = .byWordWrapping
        body.position = CGPoint(x: 0, y: 44); body.zPosition = 3
        addChild(body)

        // Status line (purchasing / restoring / failed); hidden until needed.
        statusLabel.fontSize = 8; statusLabel.fontColor = Palette.rgb(150, 236, 232)
        statusLabel.horizontalAlignmentMode = .center; statusLabel.verticalAlignmentMode = .center
        statusLabel.position = CGPoint(x: 0, y: -26); statusLabel.zPosition = 3
        statusLabel.isHidden = true
        addChild(statusLabel)

        // UNLOCK (primary).
        let unlock = SKNode()
        unlock.position = CGPoint(x: 0, y: -64); unlock.zPosition = 3
        plateButton(into: unlock, size: CGSize(width: 290, height: 46),
                    fill: Palette.rgb(40, 150, 168), border: Palette.rgb(150, 236, 232))
        unlockLabel.fontSize = 13; unlockLabel.fontColor = .white
        unlockLabel.horizontalAlignmentMode = .center; unlockLabel.verticalAlignmentMode = .center
        unlockLabel.zPosition = 2
        unlock.addChild(unlockLabel)
        addChild(unlock)
        unlockRect = CGRect(x: -145, y: -64 - 23, width: 290, height: 46)
        setPrice("$2.99")

        // RESTORE (secondary).
        restoreRect = makeTextButton(L("paywall.restore", "RESTORE"),
                                     y: -112, color: Palette.rgb(150, 236, 232), size: 10)
        // KEEP EXPLORING (dismiss).
        dismissRect = makeTextButton(L("paywall.keep_exploring", "KEEP EXPLORING"),
                                     y: -146, color: Palette.rgb(150, 176, 196), size: 9)
    }

    private func plateButton(into node: SKNode, size: CGSize, fill: UIColor, border: UIColor) {
        let b = SKSpriteNode(color: border, size: CGSize(width: size.width + 6, height: size.height + 6))
        b.alpha = 0.85; b.zPosition = 0
        let p = SKSpriteNode(color: fill, size: size); p.alpha = 0.95; p.zPosition = 1
        node.addChild(b); node.addChild(p)
    }

    /// A bare text button (no plate). Returns its tappable rect in node space.
    private func makeTextButton(_ text: String, y: CGFloat, color: UIColor, size: CGFloat) -> CGRect {
        let l = GameFont.label()
        l.text = text; l.fontSize = size; l.fontColor = color
        l.horizontalAlignmentMode = .center; l.verticalAlignmentMode = .center
        l.position = CGPoint(x: 0, y: y); l.zPosition = 3
        addChild(l)
        let h: CGFloat = 30
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
        // While a transaction is in flight, fade the choices so they read as
        // inert (taps are also ignored via `isBusy`).
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

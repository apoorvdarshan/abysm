//
//  DepthHUD.swift
//  Abysm
//
//  Compact depth read-out: a slim single-line pill ("590M  TWILIGHT ZONE") so
//  it stays readable over the water without eating the center of the screen.
//  Lives as a camera child; positioned by the scene.
//

import UIKit
import SpriteKit

final class DepthHUD: SKNode {

    private let label = GameFont.label()
    private let panel = SKSpriteNode()
    private let border = SKSpriteNode()
    private var lastMeters = Int.min
    private var lastZone = ""

    override init() {
        super.init()
        zPosition = GameConfig.Z.hud

        border.color = Palette.rgb(150, 236, 232)
        border.alpha = 0.55
        border.zPosition = 0
        addChild(border)

        panel.color = Palette.rgb(10, 26, 56)
        panel.alpha = 0.72
        panel.zPosition = 1
        addChild(panel)

        label.verticalAlignmentMode = .center
        label.horizontalAlignmentMode = .center
        label.zPosition = 2
        addChild(label)

        isAccessibilityElement = true
        accessibilityTraits = .updatesFrequently

        refresh()
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    func update(depthMeters: CGFloat, zone: String) {
        let m = max(0, Int(depthMeters.rounded()))
        guard m != lastMeters || zone != lastZone else { return }
        lastMeters = m
        lastZone = zone
        refresh()
    }

    /// Rebuild the one-line label (meter in white, zone in cyan) and fit the pill.
    private func refresh() {
        let m = lastMeters == Int.min ? 0 : lastMeters
        let z = lastZone.isEmpty ? L("zone.sunlight.name", "SUNLIGHT ZONE") : lastZone
        let font = GameFont.uiFont(size: 11)
        let s = NSMutableAttributedString(string: "\(m)M",
                                          attributes: [.font: font, .foregroundColor: UIColor.white])
        s.append(NSAttributedString(string: "   \(z)",
                                    attributes: [.font: font, .foregroundColor: Palette.rgb(150, 236, 232)]))
        label.attributedText = s
        // Spoken read-out; the catalog gives each language its plural forms of "meters".
        accessibilityLabel = String.localizedStringWithFormat(
            NSLocalizedString("hud.depth_spoken", value: "Depth %lld meters, %@", comment: "VoiceOver depth read-out"),
            m, z)

        let w = label.frame.width + 26
        let h: CGFloat = 28
        panel.size = CGSize(width: w, height: h)
        border.size = CGSize(width: w + 6, height: h + 6)
    }
}

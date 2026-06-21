//
//  OceanSurface.swift
//  Abysm
//
//  The boundary between sky and sea, rendered as a BLOCKY pixel wave: the crest
//  is a stepped staircase (sampled and quantized to the art-pixel grid), with a
//  chunky foam line and a thin flat sunlit lip. Rebuilt each frame across the
//  visible x-range only.
//

import SpriteKit

final class OceanSurface: SKNode {

    private let band = SKShapeNode()
    private let foam = SKShapeNode()
    private let width: CGFloat
    private let bandDepth: CGFloat = 30

    init(width: CGFloat) {
        self.width = width
        super.init()
        zPosition = GameConfig.Z.surface

        band.fillColor = Palette.surfaceBand.withAlphaComponent(0.4)
        band.strokeColor = .clear
        band.blendMode = .add
        band.zPosition = 0
        addChild(band)

        foam.fillColor = .clear
        foam.strokeColor = Palette.foam
        foam.lineWidth = GameConfig.pixel        // chunky pixel foam
        foam.lineCap = .butt
        foam.lineJoin = .miter
        foam.blendMode = .add
        foam.zPosition = 1
        addChild(foam)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    /// Crest height at x/time, quantized to the pixel grid.
    private func waveY(_ x: CGFloat, _ t: CGFloat) -> CGFloat {
        let y = sin(x * 0.012 + t * 1.10) * 9
            + sin(x * 0.005 - t * 0.70) * 6
            + sin(x * 0.020 + t * 1.70) * 3
        let px = GameConfig.pixel
        return (y / px).rounded() * px
    }

    /// Rebuild the blocky wave across the on-screen x-range [minX, maxX].
    func update(_ currentTime: TimeInterval, minX: CGFloat, maxX: CGFloat) {
        let t = CGFloat(currentTime)
        let half = width / 2
        let px = GameConfig.pixel
        // Snap the window to the pixel grid so steps don't shimmer as we pan.
        let lo = max(-half, (minX / px).rounded(.down) * px)
        let hi = min(half, (maxX / px).rounded(.up) * px)
        guard hi > lo else { band.path = nil; foam.path = nil; return }

        let crest = CGMutablePath()
        let fill = CGMutablePath()
        var prevY = waveY(lo, t)
        crest.move(to: CGPoint(x: lo, y: prevY))
        fill.move(to: CGPoint(x: lo, y: -bandDepth))
        fill.addLine(to: CGPoint(x: lo, y: prevY))

        var x = lo + px
        while x <= hi {
            let y = waveY(x, t)
            // Staircase: horizontal at the old height, then a vertical step.
            crest.addLine(to: CGPoint(x: x, y: prevY))
            crest.addLine(to: CGPoint(x: x, y: y))
            fill.addLine(to: CGPoint(x: x, y: prevY))
            fill.addLine(to: CGPoint(x: x, y: y))
            prevY = y
            x += px
        }

        fill.addLine(to: CGPoint(x: hi, y: -bandDepth))
        fill.closeSubpath()

        band.path = fill
        foam.path = crest
    }
}

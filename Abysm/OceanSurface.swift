//
//  OceanSurface.swift
//  Abysm
//
//  The wavy boundary between sky and sea. A translucent sunlit band whose top
//  edge is a moving sum-of-sines, plus a bright foam highlight tracing the
//  crest. Rebuilt every frame from the scene clock.
//

import SpriteKit

final class OceanSurface: SKNode {

    private let band = SKShapeNode()
    private let glowLine = SKShapeNode()
    private let foam = SKShapeNode()
    private let width: CGFloat
    private let bandDepth: CGFloat = 150

    init(width: CGFloat) {
        self.width = width
        super.init()
        zPosition = GameConfig.Z.surface

        band.fillColor = Palette.surfaceBand.withAlphaComponent(0.30)
        band.strokeColor = .clear
        band.blendMode = .add
        band.zPosition = 0
        addChild(band)

        // Soft wide glow under the crest — a sunlit sheen on the water line.
        glowLine.fillColor = .clear
        glowLine.strokeColor = Palette.surfaceBand.withAlphaComponent(0.5)
        glowLine.lineWidth = 9
        glowLine.lineCap = .round
        glowLine.blendMode = .add
        glowLine.zPosition = 1
        addChild(glowLine)

        // Crisp bright foam crest on top.
        foam.fillColor = .clear
        foam.strokeColor = Palette.foam
        foam.lineWidth = 2.5
        foam.lineCap = .round
        foam.blendMode = .add
        foam.zPosition = 2
        addChild(foam)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    /// Height of the wave crest at a given x and time — a layered sine.
    private func waveY(_ x: CGFloat, _ t: CGFloat) -> CGFloat {
        sin(x * 0.012 + t * 1.10) * 9
        + sin(x * 0.005 - t * 0.70) * 6
        + sin(x * 0.020 + t * 1.70) * 3
    }

    /// Rebuild the wavy band + foam for the current time, but ONLY across the
    /// x-range currently on screen ([minX, maxX]) rather than the whole world.
    /// The wave is a pure function of absolute x and time, so the visible
    /// window stays seamless as the camera pans — this cuts the per-frame path
    /// work ~5x versus rebuilding the full 2200pt band every frame.
    func update(_ currentTime: TimeInterval, minX: CGFloat, maxX: CGFloat) {
        let t = CGFloat(currentTime)
        let half = width / 2
        let step = GameConfig.surfaceWaveSampleStep

        // Clamp the draw window to the band's own extent.
        let lo = max(-half, minX)
        let hi = min(half, maxX)
        guard hi > lo else { band.path = nil; foam.path = nil; glowLine.path = nil; return }

        let bandPath = CGMutablePath()
        let foamPath = CGMutablePath()

        bandPath.move(to: CGPoint(x: lo, y: -bandDepth))
        bandPath.addLine(to: CGPoint(x: lo, y: waveY(lo, t)))
        foamPath.move(to: CGPoint(x: lo, y: waveY(lo, t)))

        var x = lo + step
        while x < hi {
            let y = waveY(x, t)
            bandPath.addLine(to: CGPoint(x: x, y: y))
            foamPath.addLine(to: CGPoint(x: x, y: y))
            x += step
        }

        // Always finish exactly at hi so the edge is crisp.
        let yEnd = waveY(hi, t)
        bandPath.addLine(to: CGPoint(x: hi, y: yEnd))
        foamPath.addLine(to: CGPoint(x: hi, y: yEnd))
        bandPath.addLine(to: CGPoint(x: hi, y: -bandDepth))
        bandPath.closeSubpath()

        band.path = bandPath
        foam.path = foamPath
        glowLine.path = foamPath
    }
}

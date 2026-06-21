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

        foam.fillColor = .clear
        foam.strokeColor = Palette.foam
        foam.lineWidth = 3
        foam.lineCap = .round
        foam.blendMode = .add
        foam.zPosition = 1
        addChild(foam)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    /// Height of the wave crest at a given x and time — a layered sine.
    private func waveY(_ x: CGFloat, _ t: CGFloat) -> CGFloat {
        sin(x * 0.012 + t * 1.10) * 9
        + sin(x * 0.005 - t * 0.70) * 6
        + sin(x * 0.020 + t * 1.70) * 3
    }

    /// Rebuild the wavy band + foam for the current time.
    func update(_ currentTime: TimeInterval) {
        let t = CGFloat(currentTime)
        let half = width / 2
        let step = GameConfig.surfaceWaveSampleStep

        let bandPath = CGMutablePath()
        let foamPath = CGMutablePath()

        // Band: filled region from the wavy surface down to -bandDepth.
        bandPath.move(to: CGPoint(x: -half, y: -bandDepth))
        bandPath.addLine(to: CGPoint(x: -half, y: waveY(-half, t)))
        foamPath.move(to: CGPoint(x: -half, y: waveY(-half, t)))

        var x = -half + step
        while x <= half {
            let y = waveY(x, t)
            bandPath.addLine(to: CGPoint(x: x, y: y))
            foamPath.addLine(to: CGPoint(x: x, y: y))
            x += step
        }

        bandPath.addLine(to: CGPoint(x: half, y: -bandDepth))
        bandPath.closeSubpath()

        band.path = bandPath
        foam.path = foamPath
    }
}

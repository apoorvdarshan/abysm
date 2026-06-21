//
//  TextureFactory.swift
//  Abysm
//
//  Generates all of ABYSM's textures procedurally with Core Graphics so the
//  game ships with zero image assets. Gradients, the sun glow, god-ray beams,
//  bubbles and plankton specks are all drawn here.
//

import UIKit
import SpriteKit

enum TextureFactory {

    // MARK: Gradients

    /// A vertical gradient texture. `stops` are (color, location) pairs where
    /// location 0 is the TOP of the texture and 1 is the bottom.
    static func verticalGradient(size: CGSize, stops: [(UIColor, CGFloat)]) -> SKTexture {
        let renderer = UIGraphicsImageRenderer(size: size)
        let image = renderer.image { ctx in
            let cg = ctx.cgContext
            let space = CGColorSpaceCreateDeviceRGB()
            let colors = stops.map { $0.0.cgColor } as CFArray
            let locations = stops.map { $0.1 }
            guard let gradient = CGGradient(colorsSpace: space, colors: colors, locations: locations) else { return }
            cg.drawLinearGradient(gradient,
                                  start: CGPoint(x: 0, y: 0),
                                  end: CGPoint(x: 0, y: size.height),
                                  options: [])
        }
        let texture = SKTexture(image: image)
        texture.filteringMode = .linear
        return texture
    }

    // MARK: Sun

    /// A soft radial glow fading from `inner` at the center to `outer` at the edge.
    static func radialGlow(diameter: CGFloat, inner: UIColor, outer: UIColor) -> SKTexture {
        let size = CGSize(width: diameter, height: diameter)
        let image = UIGraphicsImageRenderer(size: size).image { ctx in
            let cg = ctx.cgContext
            let space = CGColorSpaceCreateDeviceRGB()
            let colors = [inner.cgColor, outer.cgColor] as CFArray
            guard let gradient = CGGradient(colorsSpace: space, colors: colors, locations: [0, 1]) else { return }
            let center = CGPoint(x: diameter / 2, y: diameter / 2)
            cg.drawRadialGradient(gradient,
                                  startCenter: center, startRadius: 0,
                                  endCenter: center, endRadius: diameter / 2,
                                  options: [])
        }
        return SKTexture(image: image)
    }

    // MARK: God rays

    /// A soft light beam: bright at the top, fading down and toward both sides,
    /// so a stack of these reads as sun shafts through the water.
    static func softBeam(size: CGSize) -> SKTexture {
        let image = UIGraphicsImageRenderer(size: size).image { ctx in
            let cg = ctx.cgContext
            let space = CGColorSpaceCreateDeviceRGB()

            // Vertical fade: opaque white at the top → clear at the bottom.
            let vColors = [UIColor(white: 1, alpha: 1).cgColor,
                           UIColor(white: 1, alpha: 0).cgColor] as CFArray
            if let vGrad = CGGradient(colorsSpace: space, colors: vColors, locations: [0, 1]) {
                cg.drawLinearGradient(vGrad,
                                      start: CGPoint(x: 0, y: 0),
                                      end: CGPoint(x: 0, y: size.height),
                                      options: [])
            }

            // Carve soft sides: multiply existing alpha by a center-bright,
            // edges-clear horizontal gradient.
            cg.setBlendMode(.destinationIn)
            let hColors = [UIColor(white: 1, alpha: 0).cgColor,
                           UIColor(white: 1, alpha: 1).cgColor,
                           UIColor(white: 1, alpha: 0).cgColor] as CFArray
            if let hGrad = CGGradient(colorsSpace: space, colors: hColors, locations: [0, 0.5, 1]) {
                cg.drawLinearGradient(hGrad,
                                      start: CGPoint(x: 0, y: 0),
                                      end: CGPoint(x: size.width, y: 0),
                                      options: [])
            }
        }
        return SKTexture(image: image)
    }

    // MARK: Particles

    /// A little bubble: faint fill, bright ring, and a small highlight.
    static func bubble(diameter: CGFloat) -> SKTexture {
        let size = CGSize(width: diameter, height: diameter)
        let image = UIGraphicsImageRenderer(size: size).image { ctx in
            let cg = ctx.cgContext
            let rect = CGRect(origin: .zero, size: size).insetBy(dx: diameter * 0.14, dy: diameter * 0.14)

            cg.setFillColor(UIColor(white: 1, alpha: 0.10).cgColor)
            cg.fillEllipse(in: rect)

            cg.setStrokeColor(UIColor(white: 1, alpha: 0.85).cgColor)
            cg.setLineWidth(max(1, diameter * 0.08))
            cg.strokeEllipse(in: rect)

            let hl = CGRect(x: diameter * 0.30, y: diameter * 0.26,
                            width: diameter * 0.16, height: diameter * 0.16)
            cg.setFillColor(UIColor(white: 1, alpha: 0.9).cgColor)
            cg.fillEllipse(in: hl)
        }
        return SKTexture(image: image)
    }

    /// A tiny soft mote for drifting plankton.
    static func speck(diameter: CGFloat) -> SKTexture {
        radialGlow(diameter: diameter,
                   inner: UIColor(white: 1, alpha: 0.95),
                   outer: UIColor(white: 1, alpha: 0))
    }

    /// A radial vignette: fully clear through the center, darkening toward the
    /// edges/corners. Stretched over the viewport for a cinematic frame.
    static func vignette(diameter: CGFloat, edgeAlpha: CGFloat) -> SKTexture {
        let size = CGSize(width: diameter, height: diameter)
        let image = UIGraphicsImageRenderer(size: size).image { ctx in
            let cg = ctx.cgContext
            let space = CGColorSpaceCreateDeviceRGB()
            let colors = [UIColor(white: 0, alpha: 0).cgColor,
                          UIColor(white: 0, alpha: 0).cgColor,
                          UIColor(white: 0, alpha: edgeAlpha).cgColor] as CFArray
            guard let grad = CGGradient(colorsSpace: space, colors: colors, locations: [0, 0.55, 1]) else { return }
            let c = CGPoint(x: diameter / 2, y: diameter / 2)
            cg.drawRadialGradient(grad, startCenter: c, startRadius: 0,
                                  endCenter: c, endRadius: diameter / 2,
                                  options: [.drawsAfterEndLocation])
        }
        return SKTexture(image: image)
    }

    /// A plain white texture — base for shader-driven sprites (e.g. caustics).
    static func white(size: CGFloat = 8) -> SKTexture {
        let s = CGSize(width: size, height: size)
        let image = UIGraphicsImageRenderer(size: s).image { ctx in
            UIColor.white.setFill()
            ctx.fill(CGRect(origin: .zero, size: s))
        }
        return SKTexture(image: image)
    }
}

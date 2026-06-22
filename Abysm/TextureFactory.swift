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

    // MARK: Pixel-art gradient

    /// A vertical gradient rendered as PIXEL ART: clean FLAT horizontal depth
    /// bands (each `bandTexels` art-pixels tall) sampled from a disciplined
    /// color ramp — no per-pixel dithering (that reads as halftone noise). A
    /// thin Bayer dither is applied only on the 1-texel seam between bands so
    /// transitions don't look like a hard artifact. `stops[0]` is the top.
    static func pixelGradient(size: CGSize, pixel: CGFloat,
                              stops: [(UIColor, CGFloat)], bandTexels: Int = 5) -> SKTexture {
        let w = max(1, Int((size.width / pixel).rounded()))
        let h = max(1, Int((size.height / pixel).rounded()))
        let band = max(1, bandTexels)
        let bayer: [[Int]] = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]

        let cs: [(CGFloat, (CGFloat, CGFloat, CGFloat))] = stops.map { (c, loc) in
            var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
            c.getRed(&r, green: &g, blue: &b, alpha: &a)
            return (loc, (r, g, b))
        }
        func sample(_ t: CGFloat) -> (CGFloat, CGFloat, CGFloat) {
            if t <= cs.first!.0 { return cs.first!.1 }
            if t >= cs.last!.0 { return cs.last!.1 }
            for i in 1..<cs.count where t <= cs[i].0 {
                let a = cs[i - 1], b = cs[i]
                let f = (t - a.0) / (b.0 - a.0)
                return (a.1.0 + (b.1.0 - a.1.0) * f,
                        a.1.1 + (b.1.1 - a.1.1) * f,
                        a.1.2 + (b.1.2 - a.1.2) * f)
            }
            return cs.last!.1
        }
        func bandColor(_ b: Int) -> (CGFloat, CGFloat, CGFloat) {
            let centerY = min(h - 1, b * band + band / 2)
            return sample(h > 1 ? CGFloat(centerY) / CGFloat(h - 1) : 0)
        }
        func px(_ v: (CGFloat, CGFloat, CGFloat)) -> (UInt8, UInt8, UInt8) {
            (UInt8(max(0, min(255, v.0 * 255))), UInt8(max(0, min(255, v.1 * 255))), UInt8(max(0, min(255, v.2 * 255))))
        }

        var buf = [UInt8](repeating: 0, count: w * h * 4)
        for y in 0..<h {
            let b = y / band
            let inSeam = (y % band) == 0 && b > 0      // top row of each band == seam
            let cur = px(bandColor(b))
            let prev = inSeam ? px(bandColor(b - 1)) : cur
            for x in 0..<w {
                // On the seam row, dither 50/50 between this band and the one above.
                let usedPrev = inSeam && (bayer[y & 3][x & 3] >= 8)
                let c = usedPrev ? prev : cur
                let i = (y * w + x) * 4
                buf[i] = c.0; buf[i + 1] = c.1; buf[i + 2] = c.2; buf[i + 3] = 255
            }
        }
        let space = CGColorSpaceCreateDeviceRGB()
        let ctx = CGContext(data: &buf, width: w, height: h, bitsPerComponent: 8,
                            bytesPerRow: w * 4, space: space,
                            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
        let tex = SKTexture(cgImage: ctx.makeImage()!)
        tex.filteringMode = .nearest
        return tex
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

    /// A hard-edged solid square — a single "pixel" mote for particles
    /// (nearest-neighbor). `px` is the texel size.
    static func pixelDot(_ px: Int = 2, color: UIColor) -> SKTexture {
        let s = CGSize(width: px, height: px)
        let image = UIGraphicsImageRenderer(size: s).image { ctx in
            color.setFill(); ctx.fill(CGRect(origin: .zero, size: s))
        }
        let t = SKTexture(image: image); t.filteringMode = .nearest
        return t
    }

    /// A hard-edged pixel-art sun disc: bright core, a ring, a darker rim — no
    /// anti-aliasing. `radius` is in texels.
    static func pixelSun(radius r: Int) -> SKTexture {
        let n = r * 2 + 2
        let cx = CGFloat(n) / 2, cy = CGFloat(n) / 2
        let core = (255.0, 250.0, 205.0), mid = (255.0, 226.0, 120.0), rim = (250.0, 196.0, 70.0)
        var buf = [UInt8](repeating: 0, count: n * n * 4)
        for y in 0..<n {
            for x in 0..<n {
                let d = hypot(CGFloat(x) + 0.5 - cx, CGFloat(y) + 0.5 - cy)
                let rr = CGFloat(r)
                let c: (Double, Double, Double)?
                if d <= rr * 0.55 { c = core }
                else if d <= rr * 0.85 { c = mid }
                else if d <= rr { c = rim }
                else { c = nil }
                let i = (y * n + x) * 4
                if let c = c {
                    buf[i] = UInt8(c.0); buf[i+1] = UInt8(c.1); buf[i+2] = UInt8(c.2); buf[i+3] = 255
                }
            }
        }
        let space = CGColorSpaceCreateDeviceRGB()
        let ctx = CGContext(data: &buf, width: n, height: n, bitsPerComponent: 8,
                            bytesPerRow: n * 4, space: space,
                            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
        let t = SKTexture(cgImage: ctx.makeImage()!); t.filteringMode = .nearest
        return t
    }

    /// A hard-edged pixel circle. `ring > 0` makes a hollow outline of that
    /// texel thickness; `ring == 0` is a filled disc. `radius` is in texels.
    static func pixelCircle(radius r: Int, ring: Int = 0, color: UIColor) -> SKTexture {
        let n = r * 2 + 2
        let cx = CGFloat(n) / 2, cy = CGFloat(n) / 2
        var cr: CGFloat = 0, cg: CGFloat = 0, cb: CGFloat = 0, ca: CGFloat = 0
        color.getRed(&cr, green: &cg, blue: &cb, alpha: &ca)
        var buf = [UInt8](repeating: 0, count: n * n * 4)
        let rr = CGFloat(r)
        for y in 0..<n {
            for x in 0..<n {
                let d = hypot(CGFloat(x) + 0.5 - cx, CGFloat(y) + 0.5 - cy)
                let inside = ring > 0 ? (d <= rr && d >= rr - CGFloat(ring)) : (d <= rr)
                if inside {
                    let i = (y * n + x) * 4   // premultiplied
                    buf[i] = UInt8(cr * ca * 255); buf[i+1] = UInt8(cg * ca * 255)
                    buf[i+2] = UInt8(cb * ca * 255); buf[i+3] = UInt8(ca * 255)
                }
            }
        }
        let space = CGColorSpaceCreateDeviceRGB()
        let ctx = CGContext(data: &buf, width: n, height: n, bitsPerComponent: 8,
                            bytesPerRow: n * 4, space: space,
                            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
        let t = SKTexture(cgImage: ctx.makeImage()!); t.filteringMode = .nearest
        return t
    }

    /// A full-screen DARKNESS veil for the deep sea: fully CLEAR through a soft
    /// central disc (the lamp's reach) and ramping to a solid dark tint toward
    /// the edges. Smooth (not pixelated) so the lamp reads as real light, not a
    /// hard pixel shape. The scene fades this in with depth and swaps the hole
    /// size when the headlamp toggles — a wide reveal on, a tiny bubble off.
    /// `holeFrac`/`featherFrac` are fractions of the texture's radius.
    static func darknessVeil(holeFrac: CGFloat, featherFrac: CGFloat,
                             tint: UIColor = .black) -> SKTexture {
        let d: CGFloat = 512
        let size = CGSize(width: d, height: d)
        let image = UIGraphicsImageRenderer(size: size).image { ctx in
            let cg = ctx.cgContext
            let space = CGColorSpaceCreateDeviceRGB()
            let clear = tint.withAlphaComponent(0).cgColor
            let solid = tint.withAlphaComponent(1).cgColor
            let colors = [clear, clear, solid] as CFArray
            let locs: [CGFloat] = [0, holeFrac, min(1, holeFrac + featherFrac)]
            guard let grad = CGGradient(colorsSpace: space, colors: colors, locations: locs) else { return }
            let c = CGPoint(x: d / 2, y: d / 2)
            cg.drawRadialGradient(grad, startCenter: c, startRadius: 0,
                                  endCenter: c, endRadius: d / 2,
                                  options: [.drawsAfterEndLocation])
        }
        let t = SKTexture(image: image); t.filteringMode = .linear
        return t
    }

    /// A hard-edged pixel up-arrow (apex at the top, widening downward). `half`
    /// is half the base width in texels. Used as the "rise to the surface" glyph.
    static func pixelTriangleUp(half: Int, color: UIColor) -> SKTexture {
        let w = half * 2 + 2
        let h = half + 2
        let cx = CGFloat(w) / 2
        var cr: CGFloat = 0, cg: CGFloat = 0, cb: CGFloat = 0, ca: CGFloat = 0
        color.getRed(&cr, green: &cg, blue: &cb, alpha: &ca)
        var buf = [UInt8](repeating: 0, count: w * h * 4)
        for y in 0..<h {
            let halfWidth = CGFloat(y)            // apex at the top row, widening down
            for x in 0..<w where abs(CGFloat(x) + 0.5 - cx) <= halfWidth {
                let i = (y * w + x) * 4           // premultiplied
                buf[i] = UInt8(cr * ca * 255); buf[i+1] = UInt8(cg * ca * 255)
                buf[i+2] = UInt8(cb * ca * 255); buf[i+3] = UInt8(ca * 255)
            }
        }
        let space = CGColorSpaceCreateDeviceRGB()
        let ctx = CGContext(data: &buf, width: w, height: h, bitsPerComponent: 8,
                            bytesPerRow: w * 4, space: space,
                            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
        let t = SKTexture(cgImage: ctx.makeImage()!); t.filteringMode = .nearest
        return t
    }

    /// A small pixel speaker icon for the mute button. `crossed` draws a slash
    /// (muted); otherwise two sound-wave bars.
    static func pixelSpeaker(crossed: Bool, color: UIColor = .white) -> SKTexture {
        let w = 18, h = 12
        var cr: CGFloat = 0, cg: CGFloat = 0, cb: CGFloat = 0, ca: CGFloat = 0
        color.getRed(&cr, green: &cg, blue: &cb, alpha: &ca)
        var buf = [UInt8](repeating: 0, count: w * h * 4)
        func set(_ x: Int, _ y: Int) {
            guard x >= 0, x < w, y >= 0, y < h else { return }
            let i = (y * w + x) * 4
            buf[i] = UInt8(cr * ca * 255); buf[i+1] = UInt8(cg * ca * 255)
            buf[i+2] = UInt8(cb * ca * 255); buf[i+3] = UInt8(ca * 255)
        }
        for x in 2...5 { for y in 4...7 { set(x, y) } }          // speaker box
        for x in 6...9 { let hh = x - 5; for y in (5 - hh)...(6 + hh) { set(x, y) } }  // cone
        if crossed {
            for x in 1...16 { let y = Int((Double(x) * 0.6).rounded()); set(x, y); set(x, y + 1) }
        } else {
            for y in 3...8 { set(12, y) }
            for y in 2...9 { set(14, y) }
        }
        let space = CGColorSpaceCreateDeviceRGB()
        let ctx = CGContext(data: &buf, width: w, height: h, bitsPerComponent: 8,
                            bytesPerRow: w * 4, space: space,
                            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
        let t = SKTexture(cgImage: ctx.makeImage()!); t.filteringMode = .nearest
        return t
    }

    /// A small pixel pause icon (two vertical bars) for the in-game menu button.
    static func pixelPause(color: UIColor = .white) -> SKTexture {
        let w = 12, h = 14
        var cr: CGFloat = 0, cg: CGFloat = 0, cb: CGFloat = 0, ca: CGFloat = 0
        color.getRed(&cr, green: &cg, blue: &cb, alpha: &ca)
        var buf = [UInt8](repeating: 0, count: w * h * 4)
        for y in 1...12 {
            for x in [2, 3, 4, 7, 8, 9] {
                let i = (y * w + x) * 4
                buf[i] = UInt8(cr * ca * 255); buf[i+1] = UInt8(cg * ca * 255)
                buf[i+2] = UInt8(cb * ca * 255); buf[i+3] = UInt8(ca * 255)
            }
        }
        let space = CGColorSpaceCreateDeviceRGB()
        let ctx = CGContext(data: &buf, width: w, height: h, bitsPerComponent: 8,
                            bytesPerRow: w * 4, space: space,
                            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
        let t = SKTexture(cgImage: ctx.makeImage()!); t.filteringMode = .nearest
        return t
    }

    /// A clean horizontal "tide" strip: a gentle low-amplitude foam wave with a
    /// thin sunlit highlight just beneath it — the soft separator between sky and
    /// sea. `texelsWide` art-pixels across; meant to span the surface.
    static func tideStrip(texelsWide w: Int) -> SKTexture {
        let h = 8
        var buf = [UInt8](repeating: 0, count: w * h * 4)
        func put(_ x: Int, _ y: Int, _ r: Double, _ g: Double, _ b: Double, _ a: Double) {
            guard y >= 0, y < h else { return }
            let i = (y * w + x) * 4
            buf[i] = UInt8(r * a); buf[i+1] = UInt8(g * a); buf[i+2] = UInt8(b * a); buf[i+3] = UInt8(a * 255)
        }
        for x in 0..<w {
            let crest = 3 + Int((sin(Double(x) * 0.10) * 2).rounded())   // gentle long wave
            put(x, crest,     236, 252, 248, 1.0)   // foam crest
            put(x, crest + 1, 236, 252, 248, 0.9)   // foam
            put(x, crest + 2, 168, 228, 220, 0.7)   // sunlit lip just under the surface
        }
        let space = CGColorSpaceCreateDeviceRGB()
        let ctx = CGContext(data: &buf, width: w, height: h, bitsPerComponent: 8,
                            bytesPerRow: w * 4, space: space,
                            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
        let t = SKTexture(cgImage: ctx.makeImage()!); t.filteringMode = .nearest
        return t
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

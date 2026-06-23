//
//  Localization.swift
//  Abysm
//
//  Tiny localization layer. All user-facing text lives in Localizable.xcstrings
//  (16 languages); `L(key, en)` resolves a key to the active language and falls
//  back to the supplied English if a translation is ever missing — so the game
//  always shows *something* readable.
//
//  GameFont picks the display font by script. The game's look is the pixel font
//  PressStart2P, but it only carries Latin glyphs — so for languages written in
//  other scripts (Cyrillic, CJK, Devanagari, Arabic) we fall back to a built-in
//  system font that actually has the glyphs (and shapes Arabic/Devanagari
//  correctly). Latin-script languages keep the pixel look.
//

import UIKit
import SpriteKit

/// Localized string for `key`, defaulting to `en` (the development English) when
/// the key has no translation in the active language.
@inline(__always)
func L(_ key: String, _ en: String) -> String {
    Bundle.main.localizedString(forKey: key, value: en, table: nil)
}

enum GameFont {

    /// The pixel display font (Latin glyphs only).
    static let pixelName = "PressStart2P-Regular"

    /// The language the app actually resolved to (device language ∩ app's
    /// localizations), e.g. "en", "pt-BR", "zh-Hant", "ar".
    static let activeLanguage: String = Bundle.main.preferredLocalizations.first ?? "en"

    /// Font name to hand `SKLabelNode(fontNamed:)`. Pixel font for Latin scripts;
    /// a script-appropriate built-in font otherwise so glyphs render (no tofu
    /// boxes) and complex scripts shape properly.
    static let labelFontName: String = {
        let lang = activeLanguage
        if lang.hasPrefix("ja") { return "HiraginoSans-W6" }
        if lang.hasPrefix("ko") { return "AppleSDGothicNeo-Bold" }
        if lang.hasPrefix("zh") {
            let traditional = lang.contains("Hant") || lang.contains("TW")
                || lang.contains("HK") || lang.contains("MO")
            return traditional ? "PingFangTC-Semibold" : "PingFangSC-Semibold"
        }
        if lang.hasPrefix("ru") { return "HelveticaNeue-Bold" }       // covers Cyrillic
        if lang.hasPrefix("hi") { return "KohinoorDevanagari-Semibold" }
        if lang.hasPrefix("ar") { return "GeezaPro-Bold" }            // shapes Arabic
        return pixelName                                              // Latin scripts
    }()

    /// True when the active language is rendered in the pixel font.
    static let usesPixel: Bool = (labelFontName == pixelName)

    /// True for right-to-left languages (currently only Arabic).
    static let isRTL: Bool = activeLanguage.hasPrefix("ar")

    /// A label node in the active language's font.
    static func label() -> SKLabelNode { SKLabelNode(fontNamed: labelFontName) }

    /// A UIFont for attributed text (the depth HUD). System fonts read a touch
    /// small next to the chunky pixel font, so nudge non-pixel sizes up slightly.
    static func uiFont(size: CGFloat) -> UIFont {
        if usesPixel, let f = UIFont(name: pixelName, size: size) { return f }
        return UIFont(name: labelFontName, size: size + 1)
            ?? UIFont.systemFont(ofSize: size + 1, weight: .semibold)
    }
}

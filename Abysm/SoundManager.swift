//
//  SoundManager.swift
//  Abysm
//
//  All audio is generated (see /tmp/synth.py) so it's fully copyright-free:
//    • ambient — a calm underwater bed, always playing
//    • waves   — surface wash, loud near the top, fading with depth
//    • rumble  — deep pressure sub-bass, fading in as you descend
//    • bubbles — a water rush while boosting/turbo
//  A single mute toggle silences everything (and disables haptics).
//
//  HapticsManager fires short rumbles at key moments — on a game controller
//  (Core Haptics) and on the phone (UIKit) — when sound is on.
//

import UIKit
import AVFoundation
import CoreHaptics
import GameController

final class AudioManager {

    static let shared = AudioManager()

    private var ambient: AVAudioPlayer?
    private var waves: AVAudioPlayer?
    private var rumble: AVAudioPlayer?
    private var bubbles: AVAudioPlayer?
    private var click: AVAudioPlayer?
    private var splash: AVAudioPlayer?
    private var started = false
    private(set) var muted = false

    func start() {
        guard !started else { return }
        started = true
        let session = AVAudioSession.sharedInstance()
        // Play even on silent, but mix politely with the user's own music.
        try? session.setCategory(.playback, options: [.mixWithOthers])
        try? session.setActive(true)

        ambient = make("ambient"); waves = make("waves")
        rumble = make("rumble");   bubbles = make("bubbles")
        [ambient, waves, rumble, bubbles].forEach { $0?.numberOfLoops = -1 }
        ambient?.volume = 0.5; waves?.volume = 0.5; rumble?.volume = 0; bubbles?.volume = 0
        if !muted { [ambient, waves, rumble, bubbles].forEach { $0?.play() } }

        click = make("click"); click?.volume = 0.7
        splash = make("splash"); splash?.volume = 0.7

        // Resume the looping bed after an interruption (phone call, Siri, etc.).
        NotificationCenter.default.addObserver(
            self, selector: #selector(handleInterruption),
            name: AVAudioSession.interruptionNotification, object: session)
    }

    @objc private func handleInterruption(_ note: Notification) {
        guard let raw = note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
              AVAudioSession.InterruptionType(rawValue: raw) == .ended else { return }
        try? AVAudioSession.sharedInstance().setActive(true)
        if !muted { [ambient, waves, rumble, bubbles].forEach { $0?.play() } }
    }

    /// A one-shot UI click (e.g. toggling the lamp).
    func playClick() {
        guard !muted, let c = click else { return }
        c.currentTime = 0
        c.play()
    }

    /// A one-shot water splash (breach / re-entry).
    func playSplash() {
        guard !muted, let s = splash else { return }
        s.currentTime = 0
        s.play()
    }

    /// Crossfade the surface/deep layers by depth and gate the boost bubbles.
    func update(depthMeters m: CGFloat, boosting: Bool) {
        guard !muted else { return }
        waves?.volume = Float(max(0, 1 - m / 600)) * 0.6
        rumble?.volume = Float(min(1, max(0, (m - 800) / 2400))) * 0.55
        bubbles?.volume = boosting ? 0.5 : 0
    }

    func setMuted(_ on: Bool) {
        muted = on
        let players = [ambient, waves, rumble, bubbles]
        if on { players.forEach { $0?.pause() } }
        else { players.forEach { $0?.play() } }
    }

    private func make(_ name: String) -> AVAudioPlayer? {
        guard let url = Bundle.main.url(forResource: name, withExtension: "wav"),
              let p = try? AVAudioPlayer(contentsOf: url) else { return nil }
        p.prepareToPlay()
        return p
    }
}

final class HapticsManager {

    static let shared = HapticsManager()

    private var engine: CHHapticEngine?
    var enabled = true

    /// Spin up a Core Haptics engine for a connected controller (if it supports it).
    func attach(_ controller: GCController) {
        guard engine == nil, let haptics = controller.haptics else { return }
        let e = haptics.createEngine(withLocality: .default)
        // The system auto-stops the engine on interruptions/idle; restart it so
        // haptics keep working for the rest of the session.
        e?.isAutoShutdownEnabled = true
        e?.stoppedHandler = { _ in try? e?.start() }
        e?.resetHandler = { try? e?.start() }
        engine = e
        try? engine?.start()
    }

    /// A short rumble — on the controller and the phone — for a "moment".
    func pulse(intensity: Float, sharpness: Float) {
        guard enabled else { return }

        // Phone haptics.
        let style: UIImpactFeedbackGenerator.FeedbackStyle =
            intensity >= 0.8 ? .heavy : (intensity >= 0.5 ? .medium : .light)
        UIImpactFeedbackGenerator(style: style).impactOccurred()

        // Controller haptics (Core Haptics).
        guard let engine = engine else { return }
        let event = CHHapticEvent(eventType: .hapticTransient, parameters: [
            CHHapticEventParameter(parameterID: .hapticIntensity, value: intensity),
            CHHapticEventParameter(parameterID: .hapticSharpness, value: sharpness),
        ], relativeTime: 0)
        if let pattern = try? CHHapticPattern(events: [event], parameters: []),
           let player = try? engine.makePlayer(with: pattern) {
            try? player.start(atTime: 0)
        }
    }
}

//
//  AbysmUITests.swift
//  AbysmUITests
//
//  The main player journeys on the real SpriteKit screens: the title menu,
//  starting and continuing a dive, swimming, rising, pausing, the sound toggle,
//  and the 1,000 m "Unlock the Deep" gate (shown and dismissed, never bought).
//
//  Every launch passes `--ui-testing`: the Debug simulator build then never
//  configures RevenueCat, so nothing touches the network, an account or a real
//  purchase. `--ui-testing-reset` starts from a fresh install's saved state;
//  a saved dive or the unlock is seeded through the UserDefaults argument domain
//  (e.g. `-abysm.depthMeters 650`), exactly the keys the app itself writes.
//
//  SpriteKit exposes buttons as zero-size elements centred on the node, so taps
//  go to that point (the same spot a player touches). Hidden buttons stay in the
//  accessibility tree but report `isEnabled == false`.
//

import XCTest

final class AbysmUITests: XCTestCase {

    private var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // MARK: Journeys

    @MainActor
    func testFirstLaunchShowsTheTitleMenu() {
        launch()
        waitForEnabled(button("NEW GAME"))
        XCTAssertTrue(button("SOUND: ON").isEnabled)
        XCTAssertFalse(button("CONTINUE").isEnabled, "a first launch has no dive to continue")
        for link in ["PRIVACY", "TERMS", "RATE", "SHARE", "CONTACT 1", "CONTACT 2",
                     "@APOORVDARSHAN", "@APOORVGAMES", "VOTE ON PRODUCT HUNT"] {
            XCTAssertTrue(button(link).isEnabled, link)
        }
        XCTAssertTrue(text("A DIVE TO THE BOTTOM OF THE SEA").exists)
    }

    @MainActor
    func testSoundSettingIsRememberedAcrossLaunches() {
        launch()
        tap(waitForEnabled(button("SOUND: ON")))
        XCTAssertTrue(text("SOUND: OFF").waitForExistence(timeout: 10))

        relaunchKeepingData()
        waitForEnabled(button("SOUND: OFF"))
        XCTAssertFalse(button("SOUND: ON").exists)
    }

    @MainActor
    func testNewDiveSwimsDownAndRisesBackToTheSurface() {
        launch()
        tap(waitForEnabled(button("NEW GAME")))
        let hud = depthHUD()
        waitForLabel(hud, "Depth 3 meters, SUNLIGHT ZONE")
        XCTAssertTrue(button("Mute or unmute sound").isEnabled)
        XCTAssertTrue(button("Rise to surface").isEnabled)
        XCTAssertFalse(button("Toggle headlamp").isEnabled, "no headlamp in the sunlit zone")

        swimDown(seconds: 3)
        XCTAssertGreaterThan(depth(hud), 10, "the joystick moves the diver down")

        tap(button("Rise to surface"))
        waitForLabel(hud, "Depth 3 meters, SUNLIGHT ZONE")
    }

    @MainActor
    func testPauseMenuResumesAndReturnsToTheTitleWithContinue() {
        launch()
        tap(waitForEnabled(button("NEW GAME")))
        let pause = waitForEnabled(button("Pause"))
        XCTAssertFalse(button("RESUME").isEnabled, "the pause menu starts closed")

        tap(pause)
        tap(waitForEnabled(button("RESUME")))
        waitForDisabled(button("RESUME"))

        tap(pause)
        tap(waitForEnabled(button("MAIN MENU")))
        // Pausing saved the dive, so the title now offers to continue it.
        tap(waitForEnabled(button("CONTINUE")))
        waitForLabel(depthHUD(), "Depth 3 meters, SUNLIGHT ZONE")
        XCTAssertTrue(waitForEnabled(button("Pause")).isEnabled)
    }

    @MainActor
    func testContinueResumesTheSavedDepth() {
        launch(savedDepth: 650)
        tap(waitForEnabled(button("CONTINUE")))
        readAccessibilityDuringSceneFade(button("Toggle headlamp"))
        waitForLabel(depthHUD(), "Depth 650 meters, TWILIGHT ZONE")
        XCTAssertTrue(waitForEnabled(button("Toggle headlamp")).isEnabled, "the headlamp appears below 200 m")
        XCTAssertFalse(button("UNLOCK").isEnabled)
    }

    @MainActor
    func testDepthGateOffersTheUnlockAndCanBeDismissed() {
        launch(savedDepth: 1000)
        tap(waitForEnabled(button("CONTINUE")))
        readAccessibilityDuringSceneFade(button("UNLOCK"))

        let unlock = waitForEnabled(button("UNLOCK"))
        XCTAssertTrue(button("KEEP EXPLORING").isEnabled)
        XCTAssertTrue(button("RESTORE").isEnabled)
        XCTAssertTrue(text("UNLOCK THE DEEP").exists)
        let price = app.otherElements.matching(NSPredicate(format: "label BEGINSWITH %@ AND label CONTAINS %@", "UNLOCK", "$2.99"))
        XCTAssertTrue(price.firstMatch.waitForExistence(timeout: 10), "the unlock shows its price")

        // Offline there is nothing to restore: the gate stays closed and up.
        tap(button("RESTORE"))
        XCTAssertTrue(price.firstMatch.waitForExistence(timeout: 15))
        XCTAssertTrue(unlock.isEnabled)

        tap(button("KEEP EXPLORING"))
        waitForDisabled(unlock)
        // Dismissing lifts the diver back above the 1,000 m gate.
        waitForLabel(depthHUD(), "Depth 990 meters, TWILIGHT ZONE")
    }

    @MainActor
    func testUnlockedDiveContinuesPastTheGate() {
        launch(savedDepth: 1200, unlocked: true)
        tap(waitForEnabled(button("CONTINUE")))
        waitForLabel(depthHUD(), "Depth 1200 meters, MIDNIGHT ZONE")
        XCTAssertFalse(button("UNLOCK").isEnabled, "an unlocked diver never meets the gate")
    }

    // MARK: Launching

    @MainActor
    private func launch(savedDepth: Int? = nil, unlocked: Bool = false) {
        XCUIDevice.shared.orientation = .landscapeLeft   // ABYSM is landscape-only
        app = XCUIApplication()
        app.launchArguments = [
            "--ui-testing", "--ui-testing-reset",
            "-AppleLanguages", "(en)", "-AppleLocale", "en_US",
        ]
        if let savedDepth {
            app.launchArguments += ["-abysm.hasSave", "YES", "-abysm.depthMeters", "\(savedDepth)", "-abysm.x", "0"]
        }
        if unlocked {
            app.launchArguments += ["-abysm.unlockedDeep", "YES"]
        }
        app.launch()
    }

    @MainActor
    private func relaunchKeepingData() {
        app.terminate()
        app.launchArguments.removeAll { $0 == "--ui-testing-reset" }
        app.launch()
    }

    /// Reads the accessibility tree while the dive scene fades in (it starts
    /// paused, so controls that appear with depth are still hidden). A control
    /// that appears afterwards must still be offered: SpriteKit keeps the
    /// elements it reported until the app posts a layout change, and a tree read
    /// during the fade once hid the headlamp from VoiceOver and these tests.
    @MainActor
    private func readAccessibilityDuringSceneFade(_ element: XCUIElement) {
        for _ in 0..<6 {
            _ = element.exists
            Thread.sleep(forTimeInterval: 0.1)
        }
    }

    // MARK: Elements

    @MainActor
    private func button(_ label: String) -> XCUIElement {
        app.buttons[label]
    }

    /// A SpriteKit label (titles have a drop-shadow twin, so take the first).
    @MainActor
    private func text(_ label: String) -> XCUIElement {
        app.otherElements.matching(NSPredicate(format: "label == %@", label)).firstMatch
    }

    @MainActor
    private func depthHUD() -> XCUIElement {
        let hud = app.otherElements.matching(NSPredicate(format: "label BEGINSWITH 'Depth '")).firstMatch
        XCTAssertTrue(hud.waitForExistence(timeout: 20), "depth read-out")
        return hud
    }

    /// Meters shown by the depth read-out ("Depth 590 meters, TWILIGHT ZONE").
    @MainActor
    private func depth(_ hud: XCUIElement) -> Int {
        let words = hud.label.split(separator: " ")
        return words.count > 1 ? Int(words[1]) ?? -1 : -1
    }

    // MARK: Actions

    /// Touch the centre of a SpriteKit button, where a player's finger lands.
    @MainActor
    private func tap(_ element: XCUIElement) {
        element.coordinate(withNormalizedOffset: .zero).tap()
    }

    /// Hold the on-screen joystick (bottom-left) pushed down.
    @MainActor
    private func swimDown(seconds: TimeInterval) {
        // The stick sits 48 pt right of the pause button and 42 pt above the
        // headlamp button's row; it accepts touches within ~118 pt of its centre.
        let pause = button("Pause").frame.origin
        let lamp = button("Toggle headlamp").frame.origin
        let origin = app.coordinate(withNormalizedOffset: .zero)
        let stick = origin.withOffset(CGVector(dx: pause.x + 48, dy: lamp.y - 42))
        stick.press(forDuration: 0.1, thenDragTo: stick.withOffset(CGVector(dx: 0, dy: 60)),
                    withVelocity: .default, thenHoldForDuration: seconds)
    }

    // MARK: Waiting

    @MainActor
    @discardableResult
    private func waitForEnabled(_ element: XCUIElement, timeout: TimeInterval = 20,
                                file: StaticString = #filePath, line: UInt = #line) -> XCUIElement {
        waitUntil(element, "exists == true AND enabled == true", timeout: timeout, file: file, line: line)
        return element
    }

    @MainActor
    private func waitForDisabled(_ element: XCUIElement, timeout: TimeInterval = 15,
                                 file: StaticString = #filePath, line: UInt = #line) {
        waitUntil(element, "enabled == false", timeout: timeout, file: file, line: line)
    }

    @MainActor
    private func waitForLabel(_ element: XCUIElement, _ label: String, timeout: TimeInterval = 20,
                              file: StaticString = #filePath, line: UInt = #line) {
        let predicate = NSPredicate(format: "label == %@", label)
        let expectation = XCTNSPredicateExpectation(predicate: predicate, object: element)
        if XCTWaiter.wait(for: [expectation], timeout: timeout) != .completed {
            XCTFail("expected \"\(label)\", found \"\(element.label)\"", file: file, line: line)
        }
    }

    @MainActor
    private func waitUntil(_ element: XCUIElement, _ format: String, timeout: TimeInterval,
                      file: StaticString, line: UInt) {
        let expectation = XCTNSPredicateExpectation(predicate: NSPredicate(format: format), object: element)
        if XCTWaiter.wait(for: [expectation], timeout: timeout) != .completed {
            XCTFail("\(element) did not become \(format)", file: file, line: line)
        }
    }
}

import XCTest
@testable import Abysm

/// The resume point behind CONTINUE and the sound preference, both kept in
/// UserDefaults. Each test restores the keys it touches.
@MainActor
final class PersistenceTests: XCTestCase {

    private let keys = ["abysm.hasSave", "abysm.depthMeters", "abysm.x", "abysm.deepestMeters", "abysm.muted"]
    private var saved: [String: Any] = [:]

    override func setUp() {
        super.setUp()
        let defaults = UserDefaults.standard
        for key in keys {
            saved[key] = defaults.object(forKey: key)
            defaults.removeObject(forKey: key)
        }
    }

    override func tearDown() {
        let defaults = UserDefaults.standard
        for key in keys {
            if let value = saved[key] { defaults.set(value, forKey: key) } else { defaults.removeObject(forKey: key) }
        }
        AudioManager.shared.setMuted(UserDefaults.standard.bool(forKey: "abysm.muted"))
        super.tearDown()
    }

    func testAFreshInstallHasNothingToContinue() {
        XCTAssertFalse(SaveManager.hasSave)
        XCTAssertEqual(SaveManager.depthMeters, 0)
        XCTAssertEqual(SaveManager.deepestMeters, 0)
    }

    func testSavingRecordsTheResumePointAndTheDeepestDive() {
        SaveManager.save(depthMeters: 512.5, x: -140)
        XCTAssertTrue(SaveManager.hasSave)
        XCTAssertEqual(SaveManager.depthMeters, 512.5)
        XCTAssertEqual(SaveManager.x, -140)
        XCTAssertEqual(SaveManager.deepestMeters, 512.5)

        SaveManager.save(depthMeters: 80, x: 10)
        XCTAssertEqual(SaveManager.depthMeters, 80, "resume where the diver left off")
        XCTAssertEqual(SaveManager.deepestMeters, 512.5, "the record never goes back up")
    }

    func testNewGameForgetsTheResumePointButKeepsTheRecord() {
        SaveManager.save(depthMeters: 2400, x: 0)
        SaveManager.clearResume()
        XCTAssertFalse(SaveManager.hasSave)
        XCTAssertEqual(SaveManager.deepestMeters, 2400)
    }

    func testMuteIsRemembered() {
        AudioManager.shared.setMuted(true)
        XCTAssertTrue(AudioManager.shared.muted)
        XCTAssertTrue(UserDefaults.standard.bool(forKey: "abysm.muted"))
        AudioManager.shared.setMuted(false)
        XCTAssertFalse(UserDefaults.standard.bool(forKey: "abysm.muted"))
    }
}

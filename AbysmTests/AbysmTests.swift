import XCTest
import UIKit
@testable import Abysm

@MainActor
final class AbysmTests: XCTestCase {

    func testCreatureCatalogIsCompleteAndUnique() {
        XCTAssertEqual(Creatures.all.count, 75)
        XCTAssertEqual(Set(Creatures.all.map(\.key)).count, Creatures.all.count)

        for creature in Creatures.all {
            XCTAssertGreaterThanOrEqual(creature.depthM, 0, creature.key)
            XCTAssertLessThanOrEqual(creature.depthM, GameConfig.maxDepthMeters, creature.key)
            XCTAssertNotNil(UIImage(named: "creature_\(creature.key)"), creature.key)
        }
    }

    func testWorldDefinitionsAreOrderedAndBounded() {
        XCTAssertEqual(GameConfig.zones.count, 5)
        XCTAssertEqual(GameConfig.zones.map(\.topMeters), GameConfig.zones.map(\.topMeters).sorted())
        XCTAssertEqual(LandmarkField.all.count, 8)

        for landmark in LandmarkField.all {
            XCTAssertGreaterThanOrEqual(landmark.depthM, 0, landmark.key)
            XCTAssertLessThanOrEqual(landmark.depthM, GameConfig.maxDepthMeters, landmark.key)
        }
    }

    func testCoreMathClampsAndInterpolates() {
        XCTAssertEqual(clamp(-1, 0, 10), 0)
        XCTAssertEqual(clamp(12, 0, 10), 10)
        XCTAssertEqual(clamp(4, 0, 10), 4)
        XCTAssertEqual(smoothstep(0, 10, -1), 0)
        XCTAssertEqual(smoothstep(0, 10, 5), 0.5, accuracy: 0.0001)
        XCTAssertEqual(smoothstep(0, 10, 11), 1)
    }

    func testEverySupportedLocaleContainsEveryCatalogEntry() throws {
        let locales = [
            "ar", "de", "en", "es", "fr", "hi", "it", "ja", "ko", "nl",
            "pl", "pt-BR", "ru", "tr", "zh-Hans", "zh-Hant",
        ]
        let keys = localizationKeys()
        XCTAssertEqual(keys.count, 198)

        for locale in locales {
            let url = try XCTUnwrap(Bundle.main.url(forResource: locale, withExtension: "lproj"), locale)
            let bundle = try XCTUnwrap(Bundle(url: url), locale)
            for key in keys {
                XCTAssertNotEqual(bundle.localizedString(forKey: key, value: "__MISSING__", table: nil),
                                  "__MISSING__", "\(locale): \(key)")
            }
        }
    }

    func testGitHubLinksOpenTheRepositoryAndItsIssueForms() throws {
        XCTAssertEqual(ProjectLinks.repository.absoluteString, "https://github.com/apoorvdarshan/abysm")

        let bug = try XCTUnwrap(URLComponents(
            url: ProjectLinks.newIssue(.bugReport, appVersion: "1.0 (2)", deviceOS: "iPhone, iOS 26.1"),
            resolvingAgainstBaseURL: false))
        XCTAssertEqual(bug.host, "github.com")
        XCTAssertEqual(bug.path, "/apoorvdarshan/abysm/issues/new")
        XCTAssertEqual(bug.queryItems, [
            URLQueryItem(name: "template", value: "bug_report.yml"),
            URLQueryItem(name: "app-version", value: "1.0 (2)"),
            URLQueryItem(name: "device-os", value: "iPhone, iOS 26.1"),
        ])

        let feature = try XCTUnwrap(URLComponents(url: ProjectLinks.newIssue(.featureRequest),
                                                  resolvingAgainstBaseURL: false))
        XCTAssertEqual(feature.path, "/apoorvdarshan/abysm/issues/new")
        XCTAssertEqual(feature.queryItems, [URLQueryItem(name: "template", value: "feature_request.yml")],
                       "a feature request carries no device details")

        XCTAssertFalse(ProjectLinks.appVersion.contains("?"), ProjectLinks.appVersion)
        XCTAssertTrue(ProjectLinks.deviceOS.contains(UIDevice.current.systemVersion), ProjectLinks.deviceOS)
        for icon in ["ui_github", "ui_bug", "ui_feature"] {
            XCTAssertNotNil(UIImage(named: icon), icon)
        }
    }

    func testStoreIdentifiersRemainStable() {
        XCTAssertEqual(StoreManager.productID, "com.apoorvdarshan.Abysm.unlockdeep")
        XCTAssertEqual(StoreManager.entitlementID, "deep")
    }

    private func localizationKeys() -> [String] {
        var keys = [
            "title.tagline", "menu.continue", "menu.new_game", "menu.sound_on", "menu.sound_off",
            "menu.github", "menu.report_bug", "menu.request_feature",
            "pause.title", "pause.resume", "pause.main_menu",
            "paywall.title", "paywall.body", "paywall.unlock", "paywall.restore",
            "paywall.keep_exploring", "paywall.purchasing", "paywall.pending",
            "paywall.restoring", "paywall.failed", "paywall.nothing_restored", "paywall.unlocked",
        ]
        keys += GameConfig.zones.flatMap { ["zone.\($0.key).name", "zone.\($0.key).blurb"] }
        keys += Creatures.all.flatMap { ["creature.\($0.key).name", "creature.\($0.key).fact"] }
        keys += LandmarkField.all.flatMap { ["landmark.\($0.key).name", "landmark.\($0.key).note"] }
        return keys
    }
}

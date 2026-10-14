import XCTest
import SpriteKit
import UIKit
@testable import Abysm

/// The ocean model the whole game is built on: real zone boundaries, the
/// depth-driven water colour, the free dive vs. the 1,000 m gate, and how
/// creatures and landmarks stay in the diver's column.
@MainActor
final class GameWorldTests: XCTestCase {

    private func zone(_ key: String) -> String {
        let zone = GameConfig.zones.first { $0.key == key }!
        return L("zone.\(key).name", zone.name)
    }

    func testZoneNamesFollowRealDepthBoundaries() {
        XCTAssertEqual(zoneName(0), zone("sunlight"))
        XCTAssertEqual(zoneName(199.9), zone("sunlight"))
        XCTAssertEqual(zoneName(200), zone("twilight"))
        XCTAssertEqual(zoneName(999.9), zone("twilight"))
        XCTAssertEqual(zoneName(1000), zone("midnight"))
        XCTAssertEqual(zoneName(3999), zone("midnight"))
        XCTAssertEqual(zoneName(4000), zone("abyss"))
        XCTAssertEqual(zoneName(6000), zone("hadal"))
        XCTAssertEqual(zoneName(GameConfig.maxDepthMeters), zone("hadal"))
    }

    func testZoneBlurbAcceptsEnglishOrLocalizedNames() {
        let blurb = L("zone.twilight.blurb", GameConfig.zones[1].blurb)
        XCTAssertEqual(zoneBlurb("TWILIGHT ZONE"), blurb)
        XCTAssertEqual(zoneBlurb(zone("twilight")), blurb)
        XCTAssertEqual(zoneBlurb("NOT A ZONE"), "")
    }

    func testWaterDarkensFromTheSurfaceToTheTrench() {
        func brightness(_ color: UIColor) -> CGFloat {
            var h: CGFloat = 0, s: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
            color.getHue(&h, saturation: &s, brightness: &b, alpha: &a)
            return b
        }
        let stops = GameConfig.depthColorStops
        XCTAssertEqual(depthColor(-50), stops.first!.1, "above the surface clamps to the first stop")
        XCTAssertEqual(depthColor(GameConfig.maxDepthMeters + 500), stops.last!.1)
        var previous = CGFloat.greatestFiniteMagnitude
        for meters in stride(from: CGFloat(0), through: GameConfig.maxDepthMeters, by: 250) {
            let value = brightness(depthColor(meters))
            XCTAssertLessThanOrEqual(value, previous + 0.0001, "brighter at \(meters) m")
            previous = value
        }
        // Halfway between two stops is the halfway colour.
        let mid = depthColor((stops[1].0 + stops[2].0) / 2)
        let expected = lerpColor(stops[1].1, stops[2].1, 0.5)
        var m = (CGFloat(0), CGFloat(0), CGFloat(0), CGFloat(0))
        var e = (CGFloat(0), CGFloat(0), CGFloat(0), CGFloat(0))
        mid.getRed(&m.0, green: &m.1, blue: &m.2, alpha: &m.3)
        expected.getRed(&e.0, green: &e.1, blue: &e.2, alpha: &e.3)
        XCTAssertEqual(m.0, e.0, accuracy: 0.001)
        XCTAssertEqual(m.1, e.1, accuracy: 0.001)
        XCTAssertEqual(m.2, e.2, accuracy: 0.001)
    }

    func testColorAndAngleInterpolation() {
        XCTAssertEqual(lerpColor(.black, .white, 2), lerpColor(.black, .white, 1), "t is clamped")
        XCTAssertEqual(lerpColor(.black, .white, -1), lerpColor(.black, .white, 0))
        // 3.0 → -3.0 rad is a short hop across ±π, not a long turn through 0.
        XCTAssertEqual(abs(lerpAngle(3.0, -3.0, 0.5)), .pi, accuracy: 0.01)
        XCTAssertEqual(lerpAngle(0, 1, 0.25), 0.25, accuracy: 0.0001)
        XCTAssertEqual(smoothstep(5, 5, 4), 0)
        XCTAssertEqual(smoothstep(5, 5, 6), 1)
    }

    func testFreeDiveAndTheUnlockSplitTheCreaturesAsAdvertised() throws {
        // The listing and paywall promise 35 creatures in the free dive and 40
        // more past the 1,000 m gate.
        let gate: CGFloat = 1000
        XCTAssertEqual(Creatures.all.filter { $0.depthM < gate }.count, 35)
        XCTAssertEqual(Creatures.all.filter { $0.depthM >= gate }.count, 40)
        let english = try XCTUnwrap(Bundle.main.url(forResource: "en", withExtension: "lproj").flatMap(Bundle.init(url:)))
        XCTAssertTrue(english.localizedString(forKey: "paywall.body", value: nil, table: nil).contains("40 more creatures"))
        XCTAssertEqual(GameConfig.zones.first { $0.key == "midnight" }?.topMeters, gate,
                       "the gate opens onto the Midnight Zone")
    }

    func testLandmarksSitAtTheirRealDepths() {
        let depths = Dictionary(uniqueKeysWithValues: LandmarkField.all.map { ($0.key, $0.depthM) })
        XCTAssertEqual(depths["titanic"], 3800)
        XCTAssertEqual(depths["johnston"], 6241)
        XCTAssertEqual(depths["challenger_deep"], GameConfig.maxDepthMeters)
        XCTAssertEqual(Set(LandmarkField.all.map(\.name)).count, LandmarkField.all.count)
        for landmark in LandmarkField.all where landmark.image != nil {
            XCTAssertNotNil(UIImage(named: landmark.image!), landmark.key)
        }
    }

    func testWorldGeometryFitsTheDescent() {
        XCTAssertEqual(GameConfig.worldFloor, -GameConfig.maxDepthMeters * GameConfig.pointsPerMeter)
        XCTAssertLessThan(GameConfig.playerStartY, 0, "the dive starts underwater")
        XCTAssertGreaterThan(GameConfig.playerStartY, -1000 * GameConfig.pointsPerMeter, "and above the gate")
        XCTAssertGreaterThan(GameConfig.skyTop, 0)
    }

    func testCreaturesStayAtTheirDepthAndWrapAroundTheDiver() {
        let field = CreatureField()
        field.populate()
        XCTAssertEqual(field.placed.count, Creatures.all.count, "every creature has a bundled sprite")
        // The camera has drifted right; one frame later every creature is back
        // within the 640 pt window around it (wrapping happens off-screen).
        let cameraX: CGFloat = 700
        field.update(dt: 1.0 / 60.0, cameraX: cameraX)
        for (creature, node) in field.placed {
            let depthY = -creature.depthM * GameConfig.pointsPerMeter
            XCTAssertEqual(node.position.y, depthY, accuracy: 9.01, creature.key)
            XCTAssertLessThanOrEqual(abs(node.position.x - cameraX), 640 + 1, creature.key)
        }
    }

    func testLandmarksWrapAroundTheDiver() {
        let field = LandmarkField()
        field.populate()
        XCTAssertEqual(field.children.count, LandmarkField.all.count)
        field.update(cameraX: -1_000)
        for (node, landmark) in zip(field.children, LandmarkField.all) {
            XCTAssertEqual(node.position.y, -landmark.depthM * GameConfig.pointsPerMeter, landmark.key)
            XCTAssertEqual(node.position.x, -1_280, landmark.key)   // wrapped one window left
        }
        field.update(cameraX: -1_000)
        XCTAssertTrue(field.children.allSatisfy { $0.position.x == -1_280 }, "stable once inside the window")
    }
}

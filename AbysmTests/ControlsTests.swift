import XCTest
import SpriteKit
@testable import Abysm

/// On-screen controls, the depth read-out, and how hidden controls behave for
/// VoiceOver (they must not be offered or activated while the player can't see them).
@MainActor
final class ControlsTests: XCTestCase {

    func testJoystickReportsDirectionAndStrength() {
        let stick = Joystick()
        stick.position = CGPoint(x: -300, y: -100)
        XCTAssertTrue(stick.engage(at: CGPoint(x: -300, y: -100 - stick.baseRadius / 2)))
        XCTAssertEqual(stick.vector.dx, 0, accuracy: 0.0001)
        XCTAssertEqual(stick.vector.dy, -0.5, accuracy: 0.0001)

        stick.drag(to: CGPoint(x: -300 + 500, y: -100))  // far past the rim
        XCTAssertEqual(stick.vector.dx, 1, accuracy: 0.0001, "strength is capped at full")
        XCTAssertEqual(stick.vector.dy, 0, accuracy: 0.0001)

        stick.release()
        XCTAssertEqual(stick.vector, .zero)
        XCTAssertFalse(stick.engage(at: CGPoint(x: -300 + stick.activationRadius + 1, y: -100)))
    }

    func testHoldButtonHitAreaAndPressedState() {
        let button = HoldButton(radius: 30, glyph: ">>", fontSize: 12, color: .white)
        button.position = CGPoint(x: 100, y: 50)
        XCTAssertTrue(button.hit(CGPoint(x: 100 + 37, y: 50)), "touches just outside the art still count")
        XCTAssertFalse(button.hit(CGPoint(x: 100 + 38, y: 50)))
        button.setPressed(true)
        XCTAssertTrue(button.pressed)
        button.setPressed(false)
        XCTAssertFalse(button.pressed)
    }

    func testDepthReadOutIsSpokenAndRounded() {
        let hud = DepthHUD()
        XCTAssertEqual(hud.accessibilityLabel, "Depth 0 meters, SUNLIGHT ZONE")
        hud.update(depthMeters: 589.6, zone: "TWILIGHT ZONE")
        XCTAssertEqual(hud.accessibilityLabel, "Depth 590 meters, TWILIGHT ZONE")
        hud.update(depthMeters: -4, zone: "SUNLIGHT ZONE")
        XCTAssertEqual(hud.accessibilityLabel, "Depth 0 meters, SUNLIGHT ZONE", "breaching reads as the surface")
    }

    func testHiddenButtonsAreNotOfferedOrActivated() {
        let scene = SKScene(size: CGSize(width: 800, height: 400))
        let overlay = SKNode()
        scene.addChild(overlay)
        let button = AccessibleButtonNode()
        var activations = 0
        button.activationHandler = { activations += 1 }
        button.configureAccessibility(label: "RESUME")
        overlay.addChild(button)

        XCTAssertTrue(button.isAccessibilityElement)
        XCTAssertFalse(button.accessibilityTraits.contains(.notEnabled))
        XCTAssertTrue(button.accessibilityActivate())
        XCTAssertEqual(activations, 1)

        overlay.isHidden = true                     // e.g. the closed pause menu
        XCTAssertFalse(button.isAccessibilityElement)
        XCTAssertTrue(button.accessibilityTraits.contains(.notEnabled))
        XCTAssertTrue(button.accessibilityTraits.contains(.button))
        XCTAssertFalse(button.accessibilityActivate())
        XCTAssertEqual(activations, 1, "a hidden button never runs its action")

        overlay.isHidden = false
        button.alpha = 0
        XCTAssertFalse(button.accessibilityActivate())
        button.alpha = 1
        button.removeFromParent()
        XCTAssertFalse(button.isAccessibilityElement, "not in a scene")
    }

    func testHiddenHoldButtonIsNotActivated() {
        let scene = SKScene(size: CGSize(width: 800, height: 400))
        let lamp = HoldButton(radius: 28, glyph: "*", fontSize: 16, color: .yellow)
        var toggles = 0
        lamp.configureAccessibility(label: "Toggle headlamp")
        lamp.accessibilityAction = { toggles += 1 }
        scene.addChild(lamp)
        XCTAssertTrue(lamp.accessibilityActivate())
        lamp.isHidden = true                        // the sunlit zone has no headlamp
        XCTAssertFalse(lamp.accessibilityActivate())
        XCTAssertTrue(lamp.accessibilityTraits.contains(.notEnabled))
        XCTAssertEqual(toggles, 1)
    }

    /// Keeps each test's scene alive (a node only weakly references its scene).
    private var scenes: [SKScene] = []

    private func diverInAScene() throws -> (Player, SKPhysicsBody) {
        let scene = SKScene(size: CGSize(width: 800, height: 400))
        scene.physicsWorld.gravity = .zero
        let player = Player()
        scene.addChild(player)
        scenes.append(scene)
        return (player, try XCTUnwrap(player.physicsBody))
    }

    func testDiverSpeedIsCappedUnderwaterAndBoostRaisesTheCap() throws {
        let (player, body) = try diverInAScene()
        player.position = CGPoint(x: 0, y: -600)
        body.velocity = CGVector(dx: 1_000, dy: 0)
        player.update(1.0 / 60.0)
        XCTAssertEqual(body.velocity.dx, GameConfig.playerMaxSpeed, accuracy: 0.5)

        player.boostFactor = 16
        body.velocity = CGVector(dx: 1_000, dy: 0)
        player.update(1.0 / 60.0)
        XCTAssertEqual(body.velocity.dx, 1_000, accuracy: 0.5, "turbo raises the cap")
        XCTAssertEqual(body.linearDamping, GameConfig.playerLinearDamping, accuracy: 0.0001)
    }

    func testDiverStaysBetweenTheTrenchFloorAndTheSky() throws {
        let (player, body) = try diverInAScene()
        player.position = CGPoint(x: 0, y: GameConfig.worldFloor - 200)
        body.velocity = CGVector(dx: 0, dy: -80)
        player.update(1.0 / 60.0)
        XCTAssertEqual(player.position.y, GameConfig.worldFloor + 40)
        XCTAssertEqual(body.velocity.dy, 0, accuracy: 0.0001)

        // Breaching: low drag in the air and a modest hop.
        player.position = CGPoint(x: 0, y: 40)
        body.velocity = CGVector(dx: 0, dy: 2_000)
        player.update(1.0 / 60.0)
        XCTAssertEqual(body.linearDamping, GameConfig.airDamping, accuracy: 0.0001)
        XCTAssertLessThanOrEqual(body.velocity.dy, GameConfig.maxBreachUpSpeed + 0.001)

        player.position = CGPoint(x: 0, y: GameConfig.skyTop + 100)
        player.update(1.0 / 60.0)
        XCTAssertEqual(player.position.y, GameConfig.skyTop - 60)
    }
}

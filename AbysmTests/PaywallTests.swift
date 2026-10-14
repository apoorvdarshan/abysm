import XCTest
import SpriteKit
@testable import Abysm

/// The "Unlock the Deep" modal's state machine: tap routing, the busy lock,
/// controller selection and the price/status label. Nothing here buys anything.
@MainActor
final class PaywallTests: XCTestCase {

    private var paywall: Paywall!
    private var events: [String] = []

    override func setUp() {
        super.setUp()
        events = []
        paywall = Paywall()
        paywall.onUnlock = { [unowned self] in self.events.append("unlock") }
        paywall.onRestore = { [unowned self] in self.events.append("restore") }
        paywall.onDismiss = { [unowned self] in self.events.append("dismiss") }
    }

    private var buttons: [AccessibleButtonNode] { paywall.children.compactMap { $0 as? AccessibleButtonNode } }

    private var unlockText: String? {
        buttons[0].children.compactMap { $0 as? SKLabelNode }.first?.text
    }

    private let unlockCenter = CGPoint(x: 0, y: 2)
    private let keepExploringCenter = CGPoint(x: 0, y: -38)
    private let restoreCenter = CGPoint(x: 0, y: -76)

    func testButtonsAreUnlockKeepExploringAndRestore() {
        XCTAssertEqual(buttons.map(\.accessibilityLabel), [
            L("paywall.unlock", "UNLOCK"), L("paywall.keep_exploring", "KEEP EXPLORING"), L("paywall.restore", "RESTORE"),
        ])
    }

    func testTapsReachTheRightAction() {
        paywall.handleTap(unlockCenter)
        paywall.handleTap(keepExploringCenter)
        paywall.handleTap(restoreCenter)
        paywall.handleTap(CGPoint(x: 0, y: 140))   // the title, not a button
        paywall.handleTap(CGPoint(x: 200, y: 2))    // beside UNLOCK
        XCTAssertEqual(events, ["unlock", "dismiss", "restore"])
    }

    func testWhileBusyOnlyKeepExploringWorks() {
        paywall.setBusy(true)
        paywall.handleTap(unlockCenter)
        paywall.handleTap(restoreCenter)
        paywall.activateSelected()                  // UNLOCK is selected
        XCTAssertEqual(events, [])
        paywall.handleTap(keepExploringCenter)
        paywall.moveSelection(1)
        paywall.activateSelected()
        XCTAssertEqual(events, ["dismiss", "dismiss"], "the modal is always escapable")
    }

    func testControllerSelectionWrapsAround() {
        paywall.moveSelection(-1)                   // UNLOCK → RESTORE (wraps)
        paywall.activateSelected()
        paywall.moveSelection(1)                    // RESTORE → UNLOCK
        paywall.activateSelected()
        XCTAssertEqual(events, ["restore", "unlock"])
    }

    func testStatusTemporarilyReplacesThePrice() {
        let unlock = L("paywall.unlock", "UNLOCK")
        paywall.setPrice("$2.99")
        XCTAssertEqual(unlockText, "\(unlock)\u{00A0}\u{00A0}\u{2068}$2.99\u{2069}", "bidi-isolated price")
        paywall.setStatus("PURCHASING…")
        XCTAssertEqual(unlockText, "PURCHASING…")
        paywall.setPrice("€3,49")                   // a late price load must not hide the status
        XCTAssertEqual(unlockText, "PURCHASING…")
        paywall.setStatus(nil)
        XCTAssertEqual(unlockText, "\(unlock)\u{00A0}\u{00A0}\u{2068}€3,49\u{2069}")
    }

    func testResetStartsFresh() {
        paywall.setBusy(true)
        paywall.setStatus("WAITING FOR APPROVAL")
        paywall.moveSelection(2)
        paywall.reset(price: "$1.99")
        XCTAssertFalse(paywall.isBusy)
        XCTAssertTrue(unlockText?.contains("$1.99") == true)
        paywall.activateSelected()
        XCTAssertEqual(events, ["unlock"], "selection returns to UNLOCK")
    }
}

import XCTest
@testable import Abysm

/// Test runs must never reach RevenueCat, StoreKit or the network. The store
/// keeps working from its cached unlock state, with the fallback price.
@MainActor
final class OfflineStoreTests: XCTestCase {

    func testTestRunsStayOffline() {
        XCTAssertTrue(TestSupport.isActive, "hosted unit tests run in the offline test mode")
        StoreManager.configure()                    // a no-op in test runs; must not crash
        XCTAssertEqual(StoreManager.shared.displayPrice, "$2.99", "no product is loaded offline")
    }

    func testRestoreWithoutRevenueCatKeepsTheCachedUnlock() async {
        let before = StoreManager.shared.isUnlocked
        let restored = await StoreManager.shared.restore()
        XCTAssertEqual(restored, before)
        await StoreManager.shared.refresh()          // also offline: nothing changes
        XCTAssertEqual(StoreManager.shared.isUnlocked, before)
    }
}

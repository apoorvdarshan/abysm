import XCTest
@testable import Abysm

/// Test runs must never reach RevenueCat, StoreKit or the network. The store
/// keeps working from its cached unlock state, without inventing a price.
@MainActor
final class OfflineStoreTests: XCTestCase {

    func testTestRunsStayOffline() {
        XCTAssertTrue(TestSupport.isActive, "hosted unit tests run in the offline test mode")
        StoreManager.configure()                    // a no-op in test runs; must not crash
        XCTAssertNil(StoreManager.shared.displayPrice, "no storefront price is available offline")
    }

    func testUnavailableProductNeverGrantsAnUnlock() async {
        let before = StoreManager.shared.isUnlocked
        let outcome = await StoreManager.shared.purchase()
        if case .failed = outcome {} else { XCTFail("a missing product must fail, including in Debug") }
        XCTAssertEqual(StoreManager.shared.isUnlocked, before)
    }

    func testRestoreWithoutRevenueCatKeepsTheCachedUnlock() async {
        let before = StoreManager.shared.isUnlocked
        let restored = await StoreManager.shared.restore()
        XCTAssertEqual(restored, before)
        await StoreManager.shared.refresh()          // also offline: nothing changes
        XCTAssertEqual(StoreManager.shared.isUnlocked, before)
    }
}

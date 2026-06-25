//
//  StoreManager.swift
//  Abysm
//
//  The single in-app purchase: "Unlock the Deep" — a one-time, non-consumable
//  that opens the descent past the 1,000 m gate down to the trench floor.
//
//  Backed by RevenueCat. Ownership is the `deep` entitlement; it's mirrored into
//  UserDefaults so the depth gate can be checked synchronously every frame
//  without awaiting the network. The public surface (isUnlocked / displayPrice /
//  loadProduct / refresh / purchase / restore) is unchanged from the old
//  StoreKit 2 implementation, so the gate and paywall code need no changes.
//

import Foundation
import RevenueCat

@MainActor
final class StoreManager {

    static let shared = StoreManager()

    /// Public, app-specific RevenueCat SDK key (safe to ship in the binary).
    private static let apiKey = "appl_udklBZMzqHHHNeZtuXBQbRWJUTj"
    /// RevenueCat entitlement that represents the unlock.
    static let entitlementID = "deep"
    /// The App Store product behind the unlock (for reference / fallbacks).
    static let productID = "com.apoorvdarshan.Abysm.unlockdeep"
    private static let unlockedKey = "abysm.unlockedDeep"

    /// Configure RevenueCat once, at launch, before anything touches `shared`.
    static func configure() {
        guard !Purchases.isConfigured else { return }
        Purchases.logLevel = .warn
        Purchases.configure(withAPIKey: apiKey)
        _ = shared   // start the customer-info listener + initial refresh
    }

    /// The package to buy (nil until `loadProduct` succeeds); carries the price.
    private(set) var package: Package?

    /// Whether the full descent is unlocked. Persisted so the depth gate can be
    /// checked synchronously every frame without awaiting RevenueCat.
    private(set) var isUnlocked: Bool {
        didSet { UserDefaults.standard.set(isUnlocked, forKey: Self.unlockedKey) }
    }

    /// Localized display price, e.g. "$2.99" / "2,99 €" (falls back until loaded).
    var displayPrice: String { package?.storeProduct.localizedPriceString ?? "$2.99" }

    private var updatesTask: Task<Void, Never>?

    private init() {
        isUnlocked = UserDefaults.standard.bool(forKey: Self.unlockedKey)
        // Catch entitlement changes that arrive outside a direct buy (Ask to Buy
        // approvals, restores, or a purchase made on another device).
        updatesTask = Task { [weak self] in
            for await info in Purchases.shared.customerInfoStream {
                self?.apply(info)
            }
        }
        Task { await refresh() }
    }

    /// Fetch the offering's package from RevenueCat (for the localized price).
    func loadProduct() async {
        guard Purchases.isConfigured,
              let offerings = try? await Purchases.shared.offerings() else { return }
        package = offerings.current?.lifetime ?? offerings.current?.availablePackages.first
    }

    /// Recompute `isUnlocked` from the current entitlements (and load the package).
    func refresh() async {
        await loadProduct()
        guard Purchases.isConfigured,
              let info = try? await Purchases.shared.customerInfo() else { return }
        apply(info)
    }

    enum Outcome { case success, cancelled, pending, failed }

    /// Buy the unlock. Updates `isUnlocked` on success.
    func purchase() async -> Outcome {
        if package == nil { await loadProduct() }
        guard let package else {
            #if DEBUG
            // Dev convenience: if RevenueCat can't vend the package (e.g. installed
            // via devicectl with no sandbox account), grant locally so the gate +
            // post-unlock descent stay testable on-device. Never in Release.
            isUnlocked = true
            return .success
            #else
            return .failed
            #endif
        }
        do {
            let result = try await Purchases.shared.purchase(package: package)
            if result.userCancelled { return .cancelled }
            apply(result.customerInfo)
            return isUnlocked ? .success : .failed
        } catch {
            let ns = error as NSError
            if ns.domain == ErrorCode.errorDomain,
               ns.code == ErrorCode.paymentPendingError.rawValue { return .pending }
            return .failed
        }
    }

    /// Restore prior purchases. Returns true if the unlock is now owned.
    func restore() async -> Bool {
        if let info = try? await Purchases.shared.restorePurchases() {
            apply(info)
        } else {
            await refresh()
        }
        return isUnlocked
    }

    /// Mirror the `deep` entitlement into `isUnlocked`.
    private func apply(_ info: CustomerInfo) {
        isUnlocked = info.entitlements.active[Self.entitlementID] != nil
    }
}

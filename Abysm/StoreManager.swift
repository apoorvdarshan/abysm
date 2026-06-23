//
//  StoreManager.swift
//  Abysm
//
//  The single in-app purchase: "Unlock the Deep" — a one-time, non-consumable
//  that opens the descent past the 1,000 m gate down to the trench floor.
//  StoreKit 2. The unlock state is cached in UserDefaults for an instant gate
//  check at launch, and kept in sync with the App Store's entitlements.
//

import StoreKit

@MainActor
final class StoreManager {

    static let shared = StoreManager()

    static let productID = "com.apoorvdarshan.Abysm.unlockdeep"
    private static let unlockedKey = "abysm.unlockedDeep"

    /// The loaded product (nil until `loadProduct` succeeds).
    private(set) var product: Product?

    /// Whether the full descent is unlocked. Persisted so the depth gate can be
    /// checked synchronously every frame without awaiting StoreKit.
    private(set) var isUnlocked: Bool {
        didSet { UserDefaults.standard.set(isUnlocked, forKey: Self.unlockedKey) }
    }

    /// Localized display price, e.g. "$2.99" / "2,99 €" (falls back until loaded).
    var displayPrice: String { product?.displayPrice ?? "$2.99" }

    private var updatesTask: Task<Void, Never>?

    private init() {
        isUnlocked = UserDefaults.standard.bool(forKey: Self.unlockedKey)
        // Catch transactions that arrive outside a direct buy (Ask to Buy
        // approvals, restores, or a purchase made on another device).
        updatesTask = Task { [weak self] in
            for await result in Transaction.updates {
                await self?.handle(result)
            }
        }
        Task { await refresh() }
    }

    /// Fetch the product from the App Store (or the local .storekit config).
    func loadProduct() async {
        product = try? await Product.products(for: [Self.productID]).first
    }

    /// Recompute `isUnlocked` from the current entitlements (and load the product).
    func refresh() async {
        await loadProduct()
        var owned = false
        for await result in Transaction.currentEntitlements {
            if case .verified(let t) = result,
               t.productID == Self.productID, t.revocationDate == nil {
                owned = true
            }
        }
        isUnlocked = owned
    }

    enum Outcome { case success, cancelled, pending, failed }

    /// Buy the unlock. Updates `isUnlocked` on success.
    func purchase() async -> Outcome {
        if product == nil { await loadProduct() }
        guard let product else {
            #if DEBUG
            // Dev convenience: if StoreKit can't vend the product (e.g. installed
            // via devicectl with no sandbox / no .storekit config), grant locally
            // so the gate + post-unlock descent stays testable on-device. This
            // branch never compiles into a Release/App Store build.
            isUnlocked = true
            return .success
            #else
            return .failed
            #endif
        }
        do {
            switch try await product.purchase() {
            case .success(let verification):
                guard case .verified(let t) = verification else { return .failed }
                isUnlocked = true
                await t.finish()
                return .success
            case .userCancelled: return .cancelled
            case .pending:       return .pending
            @unknown default:    return .failed
            }
        } catch {
            return .failed
        }
    }

    /// Restore prior purchases. Returns true if the unlock is now owned.
    func restore() async -> Bool {
        try? await AppStore.sync()
        await refresh()
        return isUnlocked
    }

    private func handle(_ result: VerificationResult<Transaction>) async {
        guard case .verified(let t) = result else { return }
        if t.productID == Self.productID, t.revocationDate == nil {
            isUnlocked = true
        }
        await t.finish()
    }
}

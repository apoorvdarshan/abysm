//
//  TestSupport.swift
//  Abysm
//
//  Launch controls for the simulator test suites (AbysmTests hosts the app;
//  AbysmUITests launches it with `--ui-testing`). Everything here only runs in
//  Debug simulator builds: Release and device builds compile `isActive` to
//  false and `prepareLaunch()` to nothing, so they start exactly as before.
//

import Foundation

enum TestSupport {

    /// Passed by AbysmUITests on every launch.
    static let uiTestingArgument = "--ui-testing"
    /// Passed by AbysmUITests to start from a fresh install's saved state.
    static let resetArgument = "--ui-testing-reset"

    /// True while XCTest hosts (unit tests) or drives (UI tests) this Debug
    /// simulator build. RevenueCat is then never configured, so test runs stay
    /// offline and can never start a purchase.
    static let isActive: Bool = {
        #if DEBUG && targetEnvironment(simulator)
        let environment = ProcessInfo.processInfo.environment
        return CommandLine.arguments.contains(uiTestingArgument)
            || environment["XCTestConfigurationFilePath"] != nil
            || environment["XCTestBundlePath"] != nil
            || NSClassFromString("XCTestCase") != nil
        #else
        return false
        #endif
    }()

    /// Runs first at launch. A UI test launched with `--ui-testing-reset`
    /// forgets this app's saved dive, sound and unlock state (UserDefaults
    /// only), so every test starts like a first launch.
    static func prepareLaunch() {
        #if DEBUG && targetEnvironment(simulator)
        let arguments = CommandLine.arguments
        guard arguments.contains(uiTestingArgument), arguments.contains(resetArgument),
              let domain = Bundle.main.bundleIdentifier else { return }
        UserDefaults.standard.removePersistentDomain(forName: domain)
        #endif
    }
}

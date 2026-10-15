//
//  ProjectLinks.swift
//  Abysm
//
//  ABYSM is open source (MIT). The title screen links to its GitHub repository
//  and to the repository's bug report and feature request forms. The bug form is
//  prefilled with the app version and the device/iOS version, which the player
//  can still edit before submitting; nothing else about the player is sent.
//

import UIKit

enum ProjectLinks {
    static let repository = URL(string: "https://github.com/apoorvdarshan/abysm")!

    /// GitHub issue form templates in .github/ISSUE_TEMPLATE.
    enum IssueForm: String {
        case bugReport = "bug_report.yml"
        case featureRequest = "feature_request.yml"
    }

    /// A new-issue URL for `form`. GitHub prefills an issue form field from the
    /// query parameter with the same name as the field's `id`.
    static func newIssue(_ form: IssueForm, appVersion: String = Self.appVersion,
                         deviceOS: String = Self.deviceOS) -> URL {
        var components = URLComponents(url: repository.appendingPathComponent("issues/new"),
                                       resolvingAgainstBaseURL: false)!
        var query = [URLQueryItem(name: "template", value: form.rawValue)]
        if form == .bugReport {
            query.append(URLQueryItem(name: "app-version", value: appVersion))
            query.append(URLQueryItem(name: "device-os", value: deviceOS))
        }
        components.queryItems = query
        return components.url!
    }

    /// "1.0 (2)": the marketing version and build number.
    static var appVersion: String {
        let info = Bundle.main.infoDictionary
        let version = info?["CFBundleShortVersionString"] as? String ?? "?"
        let build = info?["CFBundleVersion"] as? String ?? "?"
        return "\(version) (\(build))"
    }

    /// "iPhone, iOS 26.1" or "iPad, iPadOS 26.1".
    static var deviceOS: String {
        let device = UIDevice.current
        return "\(device.model), \(device.systemName) \(device.systemVersion)"
    }
}

//
//  AccessibleButtonNode.swift
//  Abysm
//
//  SpriteKit buttons are visual nodes rather than UIKit controls. This node
//  exposes them to VoiceOver and routes the accessibility activation gesture to
//  the same action used by touch and game-controller input.
//

import SpriteKit
import UIKit

final class AccessibleButtonNode: SKNode {
    var activationHandler: (() -> Void)?

    func configureAccessibility(label: String, hint: String? = nil) {
        isAccessibilityElement = true
        accessibilityLabel = label
        accessibilityHint = hint
        accessibilityTraits = .button
    }

    override func accessibilityActivate() -> Bool {
        guard !isHidden, alpha > 0, let activationHandler else { return false }
        activationHandler()
        return true
    }
}

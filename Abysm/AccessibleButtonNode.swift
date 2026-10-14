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

    // A button the player can't see (CONTINUE without a saved dive, the pause
    // menu and paywall while closed) is not offered or activated by accessibility.
    override var isAccessibilityElement: Bool {
        get { super.isAccessibilityElement && isVisibleInScene }
        set { super.isAccessibilityElement = newValue }
    }

    override var accessibilityTraits: UIAccessibilityTraits {
        get { isVisibleInScene ? super.accessibilityTraits : super.accessibilityTraits.union(.notEnabled) }
        set { super.accessibilityTraits = newValue }
    }

    override func accessibilityActivate() -> Bool {
        guard isVisibleInScene, let activationHandler else { return false }
        activationHandler()
        return true
    }
}

extension SKNode {
    /// True when this node is in a scene and neither it nor any ancestor is
    /// hidden or fully transparent — i.e. the player can actually see it.
    var isVisibleInScene: Bool {
        guard scene != nil else { return false }
        var node: SKNode? = self
        while let current = node {
            if current.isHidden || current.alpha <= 0 { return false }
            node = current.parent
        }
        return true
    }
}

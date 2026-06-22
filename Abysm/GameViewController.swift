//
//  GameViewController.swift
//  Abysm
//

import UIKit
import SpriteKit

final class GameViewController: UIViewController {

    override func viewDidLoad() {
        super.viewDidLoad()

        guard let skView = view as? SKView else { return }

        // Build the scene in code (we don't use GameScene.sks). .resizeFill
        // keeps 1 scene point == 1 screen point; the scene re-lays-out itself
        // via didChangeSize whenever the view's bounds settle.
        let scene = TitleScene(size: skView.bounds.size)
        scene.scaleMode = .resizeFill
        skView.presentScene(scene)

        skView.ignoresSiblingOrder = true   // we rely on explicit zPosition
        skView.isMultipleTouchEnabled = true // steer + boost at the same time
        skView.showsFPS = false
        skView.showsNodeCount = false
    }

    override var supportedInterfaceOrientations: UIInterfaceOrientationMask {
        .landscape
    }

    override var prefersStatusBarHidden: Bool { true }
}

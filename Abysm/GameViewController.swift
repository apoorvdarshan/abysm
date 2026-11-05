//
//  GameViewController.swift
//  Abysm
//

import UIKit
import SpriteKit

final class GameViewController: UIViewController {

    private var gameView: SKView?

    override func viewDidLoad() {
        super.viewDidLoad()

        // Keep a single scene alive as Duo switches displays or folds. The
        // container can move/resize the playfield without resetting the dive.
        let skView = SKView(frame: view.bounds)
        view.backgroundColor = Palette.deepBackground
        view.addSubview(skView)
        gameView = skView
        if #available(iOS 27.1, *) {
            view.addInteraction(UIHingeInteraction { [weak self] _, _ in
                self?.view.setNeedsLayout()
            })
        }

        // Build the scene in code (we don't use GameScene.sks). .resizeFill
        // keeps 1 scene point == 1 screen point; the scene re-lays-out itself
        // via didChangeSize whenever the view's bounds settle.
        let scene: SKScene
        if let depth = TestSupport.screenshotDepth {
            let dive = GameScene(size: skView.bounds.size)
            dive.startDepthMeters = depth
            dive.startX = UserDefaults.standard.double(forKey: "abysm.x")
            scene = dive
        } else {
            scene = TitleScene(size: skView.bounds.size)
        }
        scene.scaleMode = .resizeFill
        skView.presentScene(scene)

        skView.ignoresSiblingOrder = true   // we rely on explicit zPosition
        skView.isMultipleTouchEnabled = true // steer + boost at the same time
        skView.showsFPS = false
        skView.showsNodeCount = false
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        var reserved: [CGRect] = []
        if #available(iOS 27.1, *) {
            reserved = (view.reservedRegions(kind: .division)
                        + view.reservedRegions(kind: .occlusion))
                .filter(\.isActive).map(\.frame)
        }
        let frame = GameViewport.playableRect(in: view.safeAreaLayoutGuide.layoutFrame,
                                              avoiding: reserved)
        if gameView?.frame != frame { gameView?.frame = frame }
    }

    override func viewSafeAreaInsetsDidChange() {
        super.viewSafeAreaInsetsDidChange()
        view.setNeedsLayout()
    }

    override var supportedInterfaceOrientations: UIInterfaceOrientationMask {
        .landscape
    }

    override var prefersStatusBarHidden: Bool { true }
}

/// Find the largest contiguous playfield outside active fold/camera regions.
/// Frames from UIKit already include the margins needed for interactive content.
enum GameViewport {
    static func playableRect(in bounds: CGRect, avoiding regions: [CGRect]) -> CGRect {
        guard bounds.width > 0, bounds.height > 0 else { return .zero }
        var candidates = [bounds]
        for region in regions {
            candidates = candidates.flatMap { rect -> [CGRect] in
                let blocked = rect.intersection(region)
                guard !blocked.isNull, blocked.width > 0, blocked.height > 0 else { return [rect] }
                return [
                    CGRect(x: rect.minX, y: rect.minY, width: blocked.minX - rect.minX, height: rect.height),
                    CGRect(x: blocked.maxX, y: rect.minY, width: rect.maxX - blocked.maxX, height: rect.height),
                    CGRect(x: rect.minX, y: rect.minY, width: rect.width, height: blocked.minY - rect.minY),
                    CGRect(x: rect.minX, y: blocked.maxY, width: rect.width, height: rect.maxY - blocked.maxY),
                ].filter { $0.width > 0 && $0.height > 0 }
            }
        }
        return candidates.max { $0.width * $0.height < $1.width * $1.height } ?? .zero
    }
}

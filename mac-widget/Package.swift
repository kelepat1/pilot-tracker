// swift-tools-version:5.9
//
// Package.swift — a SwiftPM view of the code the widget and its host app share.
//
// Why this exists: the widget itself can only be built by Xcode (a WidgetKit extension needs
// Xcode's build system and a real signing identity), but Models.swift, WidgetConfig.swift and
// StatusViews.swift are ordinary Swift and can be compiled and type-checked by SwiftPM. That
// gives you real compiler diagnostics in VS Code — and a build check that does not require
// Xcode — for the parts that are testable in isolation.
//
// The two `@main` entry points are deliberately excluded: PilotCadetWidget.swift owns the
// widget bundle's entry point and PilotCadetApp.swift owns the app's, so they cannot share a
// module.
//
// Build (note SDKROOT — see .vscode/settings.json for why the default SDK fails on SwiftUI):
//     SDKROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX26.5.sdk swift build
//
import PackageDescription

let package = Package(
    name: "PilotCadetShared",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .library(name: "PilotCadetShared", targets: ["PilotCadetShared"])
    ],
    targets: [
        .target(
            name: "PilotCadetShared",
            path: ".",
            exclude: [
                "PilotCadetApp.swift",
                "PilotCadetWidget.swift",
                "preview",
                "PilotCadetWidget.xcodeproj",
                "Info.plist",
                "PilotCadet.entitlements",
                "PilotCadetWidget.entitlements",
                "verify-build.sh",
                "check-contract.py",
                "README.md",
            ],
            sources: [
                "Models.swift",
                "WidgetConfig.swift",
                "StatusViews.swift",
                "WidgetContentViews.swift",
            ]
        )
    ]
)

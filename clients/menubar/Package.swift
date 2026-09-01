// swift-tools-version:5.10
// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

import PackageDescription

let package = Package(
    name: "AITTSMenuBar",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "AITTSMenuBar",
            path: "Sources/AITTSMenuBar"
        ),
        .testTarget(
            name: "AITTSMenuBarTests",
            dependencies: ["AITTSMenuBar"],
            path: "Tests/AITTSMenuBarTests"
        ),
    ]
)

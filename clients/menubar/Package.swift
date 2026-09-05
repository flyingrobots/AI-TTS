// swift-tools-version:5.10
// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

import PackageDescription

let package = Package(
    name: "AITTSMenuBar",
    platforms: [.macOS(.v14)],
    products: [
        .library(name: "AITTSApplication", targets: ["AITTSApplication"]),
        .library(name: "AITTSMacAdapters", targets: ["AITTSMacAdapters"]),
        .library(name: "AITTSMacEntryPoints", targets: ["AITTSMacEntryPoints"]),
        .executable(name: "AITTSMenuBar", targets: ["AITTSMenuBar"]),
    ],
    targets: [
        .target(
            name: "AITTSApplication",
            path: "Sources/AITTSApplication"
        ),
        .target(
            name: "AITTSMacAdapters",
            dependencies: ["AITTSApplication"],
            path: "Sources/AITTSMacAdapters"
        ),
        .target(
            name: "AITTSMacEntryPoints",
            dependencies: ["AITTSApplication"],
            path: "Sources/AITTSMacEntryPoints"
        ),
        .executableTarget(
            name: "AITTSMenuBar",
            dependencies: ["AITTSApplication", "AITTSMacAdapters", "AITTSMacEntryPoints"],
            path: "Sources/AITTSMenuBar"
        ),
        .testTarget(
            name: "AITTSMenuBarTests",
            dependencies: [
                "AITTSApplication",
                "AITTSMacAdapters",
                "AITTSMacEntryPoints",
                "AITTSMenuBar",
            ],
            path: "Tests/AITTSMenuBarTests"
        ),
    ]
)

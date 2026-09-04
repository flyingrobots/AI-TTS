// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//
// An advisory lock makes one status item a process invariant, including when
// developers use `swift run` and Launch Services cannot enforce bundle policy.

import Darwin
import Foundation

final class SingleInstanceLock {
    private let descriptor: Int32

    convenience init?() {
        guard let applicationSupport = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        ).first else { return nil }
        self.init(url: applicationSupport.appendingPathComponent("ai-tts/menubar.lock"))
    }

    init?(url: URL) {
        do {
            try FileManager.default.createDirectory(
                at: url.deletingLastPathComponent(),
                withIntermediateDirectories: true,
                attributes: [.posixPermissions: 0o700]
            )
        } catch {
            return nil
        }

        let candidate = Darwin.open(url.path, O_CREAT | O_RDWR, S_IRUSR | S_IWUSR)
        guard candidate >= 0 else { return nil }
        guard flock(candidate, LOCK_EX | LOCK_NB) == 0 else {
            Darwin.close(candidate)
            return nil
        }
        descriptor = candidate
    }

    deinit {
        flock(descriptor, LOCK_UN)
        Darwin.close(descriptor)
    }
}

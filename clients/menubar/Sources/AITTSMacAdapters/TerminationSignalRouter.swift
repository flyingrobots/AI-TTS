// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

import Darwin
import Foundation

/// Routes SIGTERM to the app's normal termination path.
///
/// The installer retires a running menu-bar UI with SIGTERM, and `launchctl
/// bootout` sends it too. SIGTERM's default action ends the process without
/// running `applicationWillTerminate`, which skips media-ducking cleanup.
/// Ignoring the signal and observing it with a dispatch source lets the app
/// terminate normally instead.
public final class TerminationSignalRouter {
    public typealias Install = (_ signal: Int32, _ handler: @escaping () -> Void) -> AnyObject

    private let source: AnyObject

    public init(
        install: Install = { signal, handler in
            TerminationSignalRouter.dispatchSource(signal: signal, queue: .main, handler: handler)
        },
        terminate: @escaping () -> Void
    ) {
        source = install(SIGTERM, terminate)
    }

    /// Ignore `signal`'s default action and deliver it to `handler` on `queue`.
    public static func dispatchSource(
        signal: Int32, queue: DispatchQueue, handler: @escaping () -> Void
    ) -> AnyObject {
        Darwin.signal(signal, SIG_IGN)
        let source = DispatchSource.makeSignalSource(signal: signal, queue: queue)
        source.setEventHandler(handler: handler)
        source.resume()
        return source
    }
}

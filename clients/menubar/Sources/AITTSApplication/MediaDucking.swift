// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

import Foundation

public enum MediaDuckingRouteError: LocalizedError {
    case deliveryInterrupted
    /// Core Audio has not registered the daemon yet; it does once its output opens.
    case speechProcessPending

    public var errorDescription: String? {
        switch self {
        case .deliveryInterrupted: return "Other-app audio delivery stopped."
        case .speechProcessPending: return "Waiting for the speech output process."
        }
    }
}

public protocol MediaDuckingRoute: AnyObject {
    var outputDevice: UInt32 { get }
    func waitUntilReady() async throws
    func monitorDelivery() async throws
    func setDucked(_ value: Bool)
    func close()
}

/// Owns the routing lease across speech, pause, disconnection and output changes.
@MainActor
public final class MediaDuckingController {
    public private(set) var status = "Ready to lower other apps during speech."
    public var onStatus: ((String) -> Void)?
    private let create: (Int32) throws -> any MediaDuckingRoute
    private let defaultOutput: () throws -> UInt32
    private let releaseDelay: () async throws -> Void
    private let lookupRetryDelay: () async throws -> Void
    private var lookupRetryTask: Task<Void, Never>?
    private var route: (any MediaDuckingRoute)?
    private var activationTask: Task<Void, Never>?
    private var ready = false
    private var restoreTask: Task<Void, Never>?
    private var generation = 0
    private var process: Int32?
    private var failed = false

    public init(
        create: @escaping (Int32) throws -> any MediaDuckingRoute,
        defaultOutput: @escaping () throws -> UInt32,
        releaseDelay: @escaping () async throws -> Void = { try await Task.sleep(nanoseconds: 200_000_000) },
        lookupRetryDelay: @escaping () async throws -> Void = { try await Task.sleep(nanoseconds: 250_000_000) }
    ) {
        self.create = create
        self.defaultOutput = defaultOutput
        self.releaseDelay = releaseDelay
        self.lookupRetryDelay = lookupRetryDelay
    }

    public func update(enabled: Bool, speaking: Bool, daemonPID: Int32?) {
        lookupRetryTask?.cancel()
        lookupRetryTask = nil
        guard enabled && speaking, let daemonPID, daemonPID > 0 else {
            restore(status: enabled ? "Ready to lower other apps during speech." : "Ducking is off.")
            return
        }
        guard !failed else { return }
        restoreTask?.cancel()
        restoreTask = nil
        generation += 1
        do {
            let output = try defaultOutput()
            if process != daemonPID || route?.outputDevice != output {
                activationTask?.cancel()
                activationTask = nil
                ready = false
                route?.close()
                route = nil
                route = try create(daemonPID)
                process = daemonPID
            }
            route?.setDucked(true)
            if ready {
                publish("Other apps are lowered during speech.")
            } else {
                publish("Waiting for other-app audio. Allow system-audio access if macOS prompts.")
            }
            beginActivation()
        } catch MediaDuckingRouteError.speechProcessPending {
            // The menu can see Playing before the daemon opens its output. That
            // lookup succeeds shortly, so try again rather than wait for Retry.
            route?.close()
            route = nil
            publish(MediaDuckingRouteError.speechProcessPending.localizedDescription)
            scheduleLookupRetry(daemonPID: daemonPID)
        } catch {
            route?.close()
            route = nil
            failed = true
            publish(error.localizedDescription)
        }
    }

    private func scheduleLookupRetry(daemonPID: Int32) {
        lookupRetryTask?.cancel()
        let ticket = generation
        lookupRetryTask = Task { [weak self, lookupRetryDelay] in
            do { try await lookupRetryDelay() } catch { return }
            guard let self, !Task.isCancelled, self.generation == ticket else { return }
            self.lookupRetryTask = nil
            self.update(enabled: true, speaking: true, daemonPID: daemonPID)
        }
    }

    /// Clear a failure, and drop a route still waiting for delivery so the next
    /// update builds a fresh tap. A route already delivering is kept.
    public func retry() {
        failed = false
        guard !ready, route != nil else { return }
        activationTask?.cancel()
        activationTask = nil
        route?.close()
        route = nil
        process = nil
    }

    /// Use for application shutdown, when there may be no run loop left for a ramp.
    public func close() {
        generation += 1
        lookupRetryTask?.cancel()
        lookupRetryTask = nil
        activationTask?.cancel()
        activationTask = nil
        ready = false
        restoreTask?.cancel()
        restoreTask = nil
        route?.close()
        route = nil
        process = nil
    }

    private func beginActivation() {
        guard activationTask == nil, let activating = route else { return }
        activationTask = Task { [weak self] in
            do {
                try await activating.waitUntilReady()
                guard let self, !Task.isCancelled, self.route === activating else { return }
                self.ready = true
                self.publish("Other apps are lowered during speech.")
                try await activating.monitorDelivery()
            } catch {
                guard let self, !Task.isCancelled, self.route === activating else { return }
                activating.close()
                self.route = nil
                self.activationTask = nil
                self.ready = false
                if case MediaDuckingRouteError.deliveryInterrupted = error {
                    self.update(enabled: true, speaking: true, daemonPID: self.process)
                } else {
                    self.failed = true
                    self.publish(error.localizedDescription)
                }
            }
        }
    }

    private func restore(status: String) {
        guard route != nil else {
            if !failed { publish(status) }
            return
        }
        guard restoreTask == nil else { return }
        activationTask?.cancel()
        activationTask = nil
        route?.setDucked(false)
        generation += 1
        let ticket = generation
        restoreTask = Task { [weak self, releaseDelay] in
            do { try await releaseDelay() } catch { return }
            guard let self, !Task.isCancelled, self.generation == ticket else { return }
            self.route?.close()
            self.route = nil
            self.ready = false
            self.process = nil
            self.restoreTask = nil
            self.publish(status)
        }
    }

    private func publish(_ message: String) {
        status = message
        onStatus?(message)
    }
}

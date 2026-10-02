// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

import AITTSApplication
import CoreAudio
import Foundation

/// Applies a bounded linear ramp without allocating or waiting in the audio callback.
public final class DuckingGain: @unchecked Sendable {
    private let lock = NSLock()
    private var requested: Float = 1
    private var target: Float = 1
    private var current: Float = 1
    private let step: Float

    public init(sampleRate: Double, rampSeconds: Double = 0.15) {
        step = Float(1 / max(1, sampleRate * rampSeconds))
    }

    public func setDucked(_ ducked: Bool) {
        lock.lock()
        requested = ducked ? 0.3 : 1
        lock.unlock()
    }

    /// The caller owns both buffers; stereo and planar layouts share a frame gain.
    public func render(input: UnsafePointer<AudioBufferList>, output: UnsafeMutablePointer<AudioBufferList>) {
        if lock.try() {
            target = requested
            lock.unlock()
        }
        let inputs = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: input))
        let outputs = UnsafeMutableAudioBufferListPointer(output)
        // Route only matching Float32 layouts. Unsupported layouts remain untouched
        // until startup validation rejects them; never reinterpret integer audio.
        guard inputs.count == outputs.count else { return }
        var frames = UInt32.max
        for index in inputs.indices {
            let source = inputs[index]
            let destination = outputs[index]
            guard source.mNumberChannels == destination.mNumberChannels,
                  source.mNumberChannels > 0 else { return }
            frames = min(frames, min(source.mDataByteSize, destination.mDataByteSize)
                         / (4 * source.mNumberChannels))
        }
        guard frames != UInt32.max else { return }
        for frame in 0..<Int(frames) {
            current += min(step, max(-step, target - current))
            for index in inputs.indices {
                let source = inputs[index]
                let destination = outputs[index]
                guard let read = source.mData?.assumingMemoryBound(to: Float.self),
                      let write = destination.mData?.assumingMemoryBound(to: Float.self) else { continue }
                for channel in 0..<Int(source.mNumberChannels) {
                    let offset = frame * Int(source.mNumberChannels) + channel
                    write[offset] = read[offset] * current
                }
            }
        }
    }
}

/// The callback observes delivery while the original routes remain audible.
/// No captured samples are retained; only readiness and layout validity cross threads.
public final class DuckingDeliveryGate: @unchecked Sendable {
    public enum State { case noCallbacks, silent, audio, invalid }
    private let lock: NSLock
    private var state: State = .noCallbacks
    private var enabled = false
    private var callbacks: UInt64 = 0
    // Callback-owned values survive a concurrent status read without a silent buffer.
    private var rendering = false
    private var invalidLayout = false

    public init(lock: NSLock = NSLock()) { self.lock = lock }
    public var observed: State {
        lock.lock(); defer { lock.unlock() }
        return state
    }
    public var callbackCount: UInt64 {
        lock.lock(); defer { lock.unlock() }
        return callbacks
    }
    public func enable() {
        lock.lock(); enabled = true; lock.unlock()
    }

    /// Returns whether this callback may replace the original output.
    public func receive(input: UnsafePointer<AudioBufferList>, output: UnsafeMutablePointer<AudioBufferList>) -> Bool {
        let inputs = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: input))
        let outputs = UnsafeMutableAudioBufferListPointer(output)
        var valid = inputs.count > 0 && inputs.count == outputs.count
        var audible = false
        if valid {
            for index in inputs.indices {
                let source = inputs[index], destination = outputs[index]
                guard source.mNumberChannels > 0,
                      source.mNumberChannels == destination.mNumberChannels,
                      source.mDataByteSize == destination.mDataByteSize,
                      source.mDataByteSize > 0,
                      source.mDataByteSize % (4 * source.mNumberChannels) == 0,
                      let data = source.mData?.assumingMemoryBound(to: Float.self),
                      destination.mData != nil else { valid = false; break }
                for sample in 0..<Int(source.mDataByteSize / 4) {
                    if data[sample].isFinite && data[sample] != 0 { audible = true; break }
                }
            }
        }
        if !valid { invalidLayout = true }
        if lock.try() {
            callbacks &+= 1
            if invalidLayout { state = .invalid }
            else if state != .invalid {
                if audible { state = .audio }
                else if state == .noCallbacks { state = .silent }
            }
            rendering = enabled && state != .invalid
            lock.unlock()
        }
        let mayRender = rendering && !invalidLayout
        if !mayRender {
            for buffer in outputs {
                if let data = buffer.mData { memset(data, 0, Int(buffer.mDataByteSize)) }
            }
        }
        return mayRender
    }
}

public enum AudioTapError: LocalizedError {
    case unavailable(String)
    case coreAudio(String, OSStatus)
    public var errorDescription: String? {
        switch self {
        case .unavailable(let message): return message
        case .coreAudio(let operation, let status): return "\(operation) failed (Core Audio \(status)). Check system-audio permission."
        }
    }
}

/// A private, output-only aggregate routes other processes through a process tap.
/// Destroying the tap restores the original routes, including on process exit.
@available(macOS 14.2, *)
public final class OtherAudioTap: MediaDuckingRoute {
    public let outputDevice: AudioObjectID
    private var tap: AudioObjectID = 0
    private var aggregate: AudioObjectID = 0
    private var ioProc: AudioDeviceIOProcID?
    private var gain: DuckingGain?
    private let delivery = DuckingDeliveryGate()
    private var description: CATapDescription?
    private var activated = false

    public init(daemonPID: Int32) throws {
        outputDevice = try Self.defaultOutputDevice()
        do {
            let excluded = try [daemonPID, ProcessInfo.processInfo.processIdentifier].map(Self.processObject)
            var uid: CFString = "" as CFString
            try Self.read(outputDevice, kAudioDevicePropertyDeviceUID, into: &uid)
            let description = CATapDescription(excludingProcesses: excluded, deviceUID: uid as String, stream: 0)
            description.name = "AI-TTS other-app ducking"
            description.isPrivate = true
            description.muteBehavior = .unmuted
            self.description = description
            try Self.check(AudioHardwareCreateProcessTap(description, &tap), "Create audio tap")
            var format = AudioStreamBasicDescription()
            try Self.read(tap, kAudioTapPropertyFormat, into: &format)
            guard format.mFormatID == kAudioFormatLinearPCM,
                  format.mFormatFlags & kAudioFormatFlagIsFloat != 0,
                  format.mBitsPerChannel == 32 else {
                throw AudioTapError.unavailable("Ducking needs a Float32 output route.")
            }
            let configuration: [String: Any] = [
                kAudioAggregateDeviceNameKey: "AI-TTS ducking",
                kAudioAggregateDeviceUIDKey: UUID().uuidString,
                kAudioAggregateDeviceIsPrivateKey: true,
                kAudioAggregateDeviceMainSubDeviceKey: uid,
                kAudioAggregateDeviceSubDeviceListKey: [[
                    kAudioSubDeviceUIDKey: uid,
                    kAudioSubDeviceInputChannelsKey: 0,
                ]],
                kAudioAggregateDeviceTapListKey: [[
                    kAudioSubTapUIDKey: description.uuid.uuidString,
                    kAudioSubTapDriftCompensationKey: true,
                ]],
                kAudioAggregateDeviceTapAutoStartKey: true,
            ]
            try Self.check(AudioHardwareCreateAggregateDevice(configuration as CFDictionary, &aggregate), "Create audio route")
            var inputFormat = AudioStreamBasicDescription()
            var outputFormat = AudioStreamBasicDescription()
            try Self.read(aggregate, kAudioDevicePropertyStreamFormat, scope: kAudioObjectPropertyScopeInput, into: &inputFormat)
            try Self.read(aggregate, kAudioDevicePropertyStreamFormat, scope: kAudioObjectPropertyScopeOutput, into: &outputFormat)
            try Self.validateFormats(input: inputFormat, output: outputFormat,
                                     inputChannels: Self.channelCount(aggregate, scope: kAudioObjectPropertyScopeInput),
                                     outputChannels: Self.channelCount(aggregate, scope: kAudioObjectPropertyScopeOutput))
            let gain = DuckingGain(sampleRate: inputFormat.mSampleRate)
            self.gain = gain
            let delivery = self.delivery
            try Self.check(AudioDeviceCreateIOProcIDWithBlock(&ioProc, aggregate, nil) { _, input, _, output, _ in
                if delivery.receive(input: input, output: output) {
                    gain.render(input: input, output: output)
                }
            }, "Create audio callback")
            try Self.check(AudioDeviceStart(aggregate, ioProc), "Start audio route")
            gain.setDucked(true)
        } catch {
            close()
            throw error
        }
    }

    @MainActor
    public func waitUntilReady() async throws {
        if activated { return }
        while true {
            try Task.checkCancellation()
            guard tap != 0 else { throw CancellationError() }
            switch delivery.observed {
            case .audio:
                guard let description else { throw CancellationError() }
                description.muteBehavior = .mutedWhenTapped
                var value = description
                var address = AudioObjectPropertyAddress(mSelector: kAudioTapPropertyDescription,
                    mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
                try withUnsafePointer(to: &value) { pointer in
                    try Self.check(AudioObjectSetPropertyData(tap, &address, 0, nil,
                        UInt32(MemoryLayout<CATapDescription>.size), pointer), "Activate ducking")
                }
                delivery.enable()
                activated = true
                return
            case .invalid:
                throw AudioTapError.unavailable("The audio route changed to an unsupported buffer layout.")
            case .noCallbacks, .silent: break
            }
            try await Task.sleep(nanoseconds: 50_000_000)
        }
    }

    @MainActor
    public func monitorDelivery() async throws {
        var previous = delivery.callbackCount
        var lastDelivery = ContinuousClock.now
        while true {
            try await Task.sleep(nanoseconds: 50_000_000)
            guard tap != 0 else { throw CancellationError() }
            guard delivery.observed != .invalid else {
                throw AudioTapError.unavailable("The audio route changed to an unsupported buffer layout. Other apps have been restored.")
            }
            let count = delivery.callbackCount
            if count != previous { previous = count; lastDelivery = .now }
            if lastDelivery.duration(to: .now) >= .milliseconds(500) {
                throw MediaDuckingRouteError.deliveryInterrupted
            }
        }
    }

    public func setDucked(_ value: Bool) { gain?.setDucked(value) }

    public func close() {
        if let ioProc {
            AudioDeviceStop(aggregate, ioProc)
            AudioDeviceDestroyIOProcID(aggregate, ioProc)
            self.ioProc = nil
        }
        if aggregate != 0 { AudioHardwareDestroyAggregateDevice(aggregate); aggregate = 0 }
        if tap != 0 { AudioHardwareDestroyProcessTap(tap); tap = 0 }
        gain = nil
    }

    deinit { close() }

    /// Validate the PCM contract before opening an I/O procedure.
    public static func validateFormats(input inputFormat: AudioStreamBasicDescription,
                                       output outputFormat: AudioStreamBasicDescription,
                                       inputChannels: UInt32, outputChannels: UInt32) throws {
        guard inputChannels > 0,
              inputChannels == inputFormat.mChannelsPerFrame,
              outputChannels == inputChannels,
              inputFormat.mFormatID == kAudioFormatLinearPCM,
              outputFormat.mFormatID == kAudioFormatLinearPCM,
              inputFormat.mFormatFlags == outputFormat.mFormatFlags,
              inputFormat.mFormatFlags & kAudioFormatFlagIsFloat != 0,
              inputFormat.mFormatFlags & kAudioFormatFlagIsBigEndian == 0,
              inputFormat.mBitsPerChannel == 32, outputFormat.mBitsPerChannel == 32,
              inputFormat.mChannelsPerFrame == outputFormat.mChannelsPerFrame,
              inputFormat.mBytesPerFrame == outputFormat.mBytesPerFrame,
              inputFormat.mSampleRate == outputFormat.mSampleRate,
              inputFormat.mSampleRate > 0 else {
            throw AudioTapError.unavailable("This output route does not support matching Float32 ducking.")
        }
    }

    public static func defaultOutputDevice() throws -> AudioObjectID {
        var device: AudioObjectID = 0
        try read(AudioObjectID(kAudioObjectSystemObject), kAudioHardwarePropertyDefaultOutputDevice, into: &device)
        guard device != 0 else { throw AudioTapError.unavailable("No output device is available.") }
        return device
    }

    private static func processObject(_ pid: Int32) throws -> AudioObjectID {
        var process: AudioObjectID = 0
        var pid = pid
        var address = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyTranslatePIDToProcessObject, mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
        var size = UInt32(MemoryLayout<AudioObjectID>.size)
        try check(AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &address, UInt32(MemoryLayout<Int32>.size), &pid, &size, &process), "Find speech process")
        guard process != 0 else { throw MediaDuckingRouteError.speechProcessPending }
        return process
    }

    private static func channelCount(_ object: AudioObjectID, scope: AudioObjectPropertyScope) throws -> UInt32 {
        var address = AudioObjectPropertyAddress(mSelector: kAudioDevicePropertyStreamConfiguration, mScope: scope, mElement: kAudioObjectPropertyElementMain)
        var size: UInt32 = 0
        try check(AudioObjectGetPropertyDataSize(object, &address, 0, nil, &size), "Inspect audio channels")
        guard size >= MemoryLayout<AudioBufferList>.size else {
            throw AudioTapError.unavailable("No audio channels are available.")
        }
        let memory = UnsafeMutableRawPointer.allocate(byteCount: Int(size), alignment: MemoryLayout<AudioBufferList>.alignment)
        defer { memory.deallocate() }
        try check(AudioObjectGetPropertyData(object, &address, 0, nil, &size, memory), "Read audio channels")
        return UnsafeMutableAudioBufferListPointer(memory.assumingMemoryBound(to: AudioBufferList.self))
            .reduce(0) { $0 + $1.mNumberChannels }
    }

    private static func read<T>(_ object: AudioObjectID, _ selector: AudioObjectPropertySelector, scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal, into value: inout T) throws {
        var address = AudioObjectPropertyAddress(mSelector: selector, mScope: scope, mElement: kAudioObjectPropertyElementMain)
        var size = UInt32(MemoryLayout<T>.size)
        try withUnsafeMutablePointer(to: &value) { pointer in
            try check(AudioObjectGetPropertyData(object, &address, 0, nil, &size, pointer), "Read audio route")
        }
    }

    private static func check(_ status: OSStatus, _ operation: String) throws {
        if status != noErr { throw AudioTapError.coreAudio(operation, status) }
    }
}

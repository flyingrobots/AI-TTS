// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium (owned Core Audio buffer layouts, no hardware)
// Test-Oracle: other-app samples ramp to 30% and return to unity; channels retain identity

import CoreAudio
import XCTest
@testable import AITTSMacAdapters

final class DuckingGainTests: XCTestCase {
    override func setUp() { super.setUp(); executionTimeAllowance = 15 }

    func testStereoGainRampsToDuckAndBackWithoutChangingChannels() {
        let gain = DuckingGain(sampleRate: 1000, rampSeconds: 0.1)
        gain.setDucked(true)
        let ducked = render(gain, frames: 100)
        XCTAssertEqual(ducked[0], 0.495, accuracy: 0.00001)
        XCTAssertEqual(ducked[1], -0.2475, accuracy: 0.00001)
        XCTAssertEqual(ducked[198], 0.15, accuracy: 0.00001)
        XCTAssertEqual(ducked[199], -0.075, accuracy: 0.00001)
        for frame in 1..<100 {
            XCTAssertLessThanOrEqual(abs(ducked[frame * 2] - ducked[(frame - 1) * 2]), 0.00501)
        }
        gain.setDucked(false)
        let restored = render(gain, frames: 100)
        XCTAssertEqual(restored[0], 0.155, accuracy: 0.00001)
        XCTAssertEqual(restored[198], 0.5, accuracy: 0.00001)
        XCTAssertEqual(restored[199], -0.25, accuracy: 0.00001)
    }

    func testNativeEightChannelLayoutIsAcceptedWithoutIncludingExtraInputs() throws {
        guard #available(macOS 14.2, *) else { throw XCTSkip("Process taps require macOS 14.2") }
        let format = AudioStreamBasicDescription(mSampleRate: 48000, mFormatID: kAudioFormatLinearPCM,
            mFormatFlags: kAudioFormatFlagIsFloat | kAudioFormatFlagIsPacked,
            mBytesPerPacket: 32, mFramesPerPacket: 1, mBytesPerFrame: 32,
            mChannelsPerFrame: 8, mBitsPerChannel: 32, mReserved: 0)
        XCTAssertNoThrow(try OtherAudioTap.validateFormats(input: format, output: format, inputChannels: 8, outputChannels: 8))
        XCTAssertThrowsError(try OtherAudioTap.validateFormats(input: format, output: format, inputChannels: 10, outputChannels: 8))
    }

    func testDeliveryGateKeepsOutputSilentUntilAudioArrivesAndActivationIsExplicit() {
        let gate = DuckingDeliveryGate()
        var sample: Float = 0
        var result: Float = 9
        XCTAssertEqual(gate.observed, .noCallbacks)
        withUnsafeMutablePointer(to: &sample) { source in
            withUnsafeMutablePointer(to: &result) { destination in
                var input = AudioBufferList(mNumberBuffers: 1, mBuffers: AudioBuffer(mNumberChannels: 1, mDataByteSize: 4, mData: source))
                var output = AudioBufferList(mNumberBuffers: 1, mBuffers: AudioBuffer(mNumberChannels: 1, mDataByteSize: 4, mData: destination))
                XCTAssertFalse(gate.receive(input: &input, output: &output))
                XCTAssertEqual(destination.pointee, 0)
                XCTAssertEqual(gate.observed, .silent)
                source.pointee = 0.25
                XCTAssertFalse(gate.receive(input: &input, output: &output))
                XCTAssertEqual(gate.observed, .audio)
                gate.enable()
                XCTAssertTrue(gate.receive(input: &input, output: &output))
                output.mBuffers.mNumberChannels = 2
                XCTAssertFalse(gate.receive(input: &input, output: &output))
                XCTAssertEqual(gate.observed, .invalid)
                output.mBuffers.mNumberChannels = 1
                XCTAssertFalse(gate.receive(input: &input, output: &output))
            }
        }
    }

    func testStatusReaderCannotSilenceAnAlreadyEnabledCallback() {
        let lock = NSLock()
        let gate = DuckingDeliveryGate(lock: lock)
        var sample: Float = 0.25
        var result: Float = 0
        gate.enable()
        withUnsafeMutablePointer(to: &sample) { source in
            withUnsafeMutablePointer(to: &result) { destination in
                var input = AudioBufferList(mNumberBuffers: 1, mBuffers: AudioBuffer(mNumberChannels: 1, mDataByteSize: 4, mData: source))
                var output = AudioBufferList(mNumberBuffers: 1, mBuffers: AudioBuffer(mNumberChannels: 1, mDataByteSize: 4, mData: destination))
                XCTAssertTrue(gate.receive(input: &input, output: &output))
                lock.lock()
                let rendersWhileStatusReaderOwnsLock = gate.receive(input: &input, output: &output)
                lock.unlock()
                XCTAssertTrue(rendersWhileStatusReaderOwnsLock)
            }
        }
    }

    private func render(_ gain: DuckingGain, frames: Int) -> [Float] {
        let source = UnsafeMutablePointer<Float>.allocate(capacity: frames * 2)
        let destination = UnsafeMutablePointer<Float>.allocate(capacity: frames * 2)
        defer { source.deallocate(); destination.deallocate() }
        for frame in 0..<frames { source[frame * 2] = 0.5; source[frame * 2 + 1] = -0.25 }
        destination.initialize(repeating: 0, count: frames * 2)
        var input = AudioBufferList(mNumberBuffers: 1, mBuffers: AudioBuffer(mNumberChannels: 2, mDataByteSize: UInt32(frames * 8), mData: source))
        var output = AudioBufferList(mNumberBuffers: 1, mBuffers: AudioBuffer(mNumberChannels: 2, mDataByteSize: UInt32(frames * 8), mData: destination))
        gain.render(input: &input, output: &output)
        return Array(UnsafeBufferPointer(start: destination, count: frames * 2))
    }
}

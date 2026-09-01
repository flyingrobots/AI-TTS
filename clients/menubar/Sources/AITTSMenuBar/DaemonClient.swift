// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
//
// A blocking Unix-socket client, always used from a background queue.

import Foundation

enum ClientError: Error {
    case unreachable(String)
}

final class DaemonClient: Sendable {
    private let socketPath: String

    init(socketPath: String = WireProtocol.defaultSocketPath()) {
        self.socketPath = socketPath
    }

    /// Send one request and return the parsed response.
    func request(_ payload: [String: Any]) throws -> [String: Any] {
        let fd = try connect()
        defer { close(fd) }
        let data = try WireProtocol.encode(payload)
        try writeAll(fd, data)
        let line = try readLine(fd)
        return try WireProtocol.parseResponse(line)
    }

    /// Subscribe and block, invoking `onEvent` per event line, until the
    /// connection drops or `shouldContinue` says stop. Call from a background
    /// thread; reconnection is the caller's job.
    func subscribe(shouldContinue: () -> Bool, onEvent: (Data) -> Void) throws {
        let fd = try connect()
        defer { close(fd) }
        // Events can be minutes apart; do not let the receive timeout cut us off.
        var timeout = timeval(tv_sec: 2, tv_usec: 0)
        setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size))
        try writeAll(fd, WireProtocol.encode(["op": "subscribe"]))
        var buffer = Data()
        var chunk = [UInt8](repeating: 0, count: 65536)
        while shouldContinue() {
            let count = read(fd, &chunk, chunk.count)
            if count == 0 { throw ClientError.unreachable("event stream closed") }
            if count < 0 {
                // EAGAIN from the 2s receive timeout: loop so shouldContinue is re-checked.
                if errno == EAGAIN || errno == EWOULDBLOCK { continue }
                throw ClientError.unreachable("event stream read failed")
            }
            buffer.append(contentsOf: chunk[0..<count])
            while let newline = buffer.firstIndex(of: 0x0A) {
                let line = buffer.prefix(upTo: newline)
                buffer.removeSubrange(...newline)
                if !line.isEmpty { onEvent(Data(line)) }
            }
        }
    }

    private func connect() throws -> Int32 {
        let fd = socket(AF_UNIX, SOCK_STREAM, 0)
        guard fd >= 0 else { throw ClientError.unreachable("cannot create socket") }
        var addr = sockaddr_un()
        addr.sun_family = sa_family_t(AF_UNIX)
        let bytes = socketPath.utf8CString
        guard bytes.count <= MemoryLayout.size(ofValue: addr.sun_path) else {
            close(fd)
            throw ClientError.unreachable("socket path too long")
        }
        withUnsafeMutableBytes(of: &addr.sun_path) { raw in
            bytes.withUnsafeBytes { src in
                raw.copyMemory(from: UnsafeRawBufferPointer(rebasing: src.prefix(raw.count)))
            }
        }
        let size = socklen_t(MemoryLayout<sockaddr_un>.size)
        let result = withUnsafePointer(to: &addr) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { sockaddrPointer in
                Darwin.connect(fd, sockaddrPointer, size)
            }
        }
        guard result == 0 else {
            close(fd)
            throw ClientError.unreachable("daemon not reachable at \(socketPath)")
        }
        var timeout = timeval(tv_sec: 10, tv_usec: 0)
        setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size))
        return fd
    }

    private func writeAll(_ fd: Int32, _ data: Data) throws {
        try data.withUnsafeBytes { (raw: UnsafeRawBufferPointer) in
            var offset = 0
            while offset < raw.count {
                let written = write(fd, raw.baseAddress!.advanced(by: offset), raw.count - offset)
                guard written > 0 else { throw ClientError.unreachable("write failed") }
                offset += written
            }
        }
    }

    private func readLine(_ fd: Int32) throws -> Data {
        var buffer = Data()
        var chunk = [UInt8](repeating: 0, count: 65536)
        while true {
            let count = read(fd, &chunk, chunk.count)
            guard count > 0 else { throw ClientError.unreachable("daemon closed the connection") }
            buffer.append(contentsOf: chunk[0..<count])
            if let newline = buffer.firstIndex(of: 0x0A) {
                return buffer.prefix(upTo: newline)
            }
        }
    }
}

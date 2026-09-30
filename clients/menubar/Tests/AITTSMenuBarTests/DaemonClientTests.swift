// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0
// Test-Size: medium (owned socket pair)
// Test-Oracle: maintenance requests receive the 120-second socket allowance;
// ordinary controls retain the 10-second allowance

import Foundation
import XCTest
@testable import AITTSMacAdapters

final class DaemonClientTests: XCTestCase {
    override func setUp() {
        super.setUp()
        executionTimeAllowance = 15
    }

    func testRequestConfiguresTheSocketReceiveTimeout() throws {
        let cases: [([String: Any], Int)] = [
            (["op": "storage"], 120),
            (["op": "storage", "delete": ["old"]], 120),
            (["op": "clear", "queue": "history", "delete_files": true], 120),
            (["op": "export_evidence", "id": "clip"], 120),
            (["op": "restart_model"], 120),
            (["op": "clear", "queue": "history"], 10),
            (["op": "clear", "queue": "history", "delete_files": false], 10),
            (["op": "snapshot"], 10),
        ]
        for (payload, expectedSeconds) in cases {
            var sockets: [Int32] = [-1, -1]
            guard socketpair(AF_UNIX, SOCK_STREAM, 0, &sockets) == 0 else {
                XCTFail("Cannot create owned socket pair")
                return
            }
            let clientSocket = sockets[0]
            let serverSocket = sockets[1]
            defer { close(clientSocket); close(serverSocket) }
            var initial = timeval(tv_sec: 10, tv_usec: 0)
            guard setsockopt(clientSocket, SOL_SOCKET, SO_RCVTIMEO, &initial,
                             socklen_t(MemoryLayout<timeval>.size)) == 0 else {
                XCTFail("Cannot establish the ordinary connection timeout")
                return
            }
            let reply = Data("{\"ok\":true}\n".utf8)
            let written = reply.withUnsafeBytes { write(serverSocket, $0.baseAddress, $0.count) }
            guard written == reply.count else {
                XCTFail("Cannot seed the daemon reply")
                return
            }
            let client = DaemonClient(openConnection: { dup(clientSocket) })
            _ = try client.request(payload)
            var actual = timeval()
            var length = socklen_t(MemoryLayout<timeval>.size)
            guard getsockopt(clientSocket, SOL_SOCKET, SO_RCVTIMEO, &actual, &length) == 0 else {
                XCTFail("Cannot inspect the configured socket timeout")
                return
            }
            XCTAssertEqual(actual.tv_sec, expectedSeconds, "request: \(payload)")
            XCTAssertEqual(actual.tv_usec, 0, "request: \(payload)")
        }
    }
}

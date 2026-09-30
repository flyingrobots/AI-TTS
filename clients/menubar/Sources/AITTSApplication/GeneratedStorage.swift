// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

import Foundation

public struct GeneratedFile: Identifiable, Sendable {
    public let id: String
    public let preview: String
    public let bytes: Int64
    public let modifiedAt: Double
    public let protected: Bool

    public init(id: String, preview: String, bytes: Int64, modifiedAt: Double, protected: Bool) {
        self.id = id; self.preview = preview; self.bytes = bytes
        self.modifiedAt = modifiedAt; self.protected = protected
    }
}

public struct GeneratedStorageSnapshot: Sendable {
    public let entries: [GeneratedFile]
    public let totalBytes: Int64
    public let retentionDays: Int
    public let message: String?

    public init(entries: [GeneratedFile], totalBytes: Int64, retentionDays: Int, message: String?) {
        self.entries = entries; self.totalBytes = totalBytes
        self.retentionDays = retentionDays; self.message = message
    }
}

public protocol GeneratedStorageManaging: Sendable {
    func storage(retentionDays: Int?, deleting: [String]?) throws -> GeneratedStorageSnapshot
    func clearHistoryAndFiles() throws
}

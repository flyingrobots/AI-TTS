// Copyright 2026 James Ross
// SPDX-License-Identifier: Apache-2.0

import AITTSApplication
import AITTSMacAdapters
import AITTSMacEntryPoints
import AppKit
import SwiftUI

@MainActor
final class SpeechComposer: ObservableObject {
    @Published var draft = SpeechDraft()
    @Published private(set) var busy = false
    @Published var error: String?
    @Published private(set) var notice: String?
    var priorApplication: Int32?
    private let speech: any SpeechServicePort
    private let documents: any SpeechDocumentReaderPort
    private let clipboard: any ClipboardTextReaderPort
    private let selection: any SelectedTextReaderPort

    init(speech: any SpeechServicePort,
         documents: any SpeechDocumentReaderPort = LocalSpeechDocumentReader(),
         clipboard: any ClipboardTextReaderPort = MacClipboardTextReader(),
         selection: any SelectedTextReaderPort = AccessibilitySelectionReader()) {
        self.speech = speech
        self.documents = documents
        self.clipboard = clipboard
        self.selection = selection
    }

    func clear() {
        let voice = draft.voice
        let engine = draft.engine
        let contentFormat = draft.contentFormat
        draft = SpeechDraft()
        draft.voice = voice
        draft.engine = engine
        draft.contentFormat = contentFormat
        notice = nil
        error = nil
    }

    func attach(_ url: URL) async {
        await importText { [documents] in
            let document = try documents.read(url)
            return (document.text, "file:\(document.filename)", document.contentFormat)
        }
    }

    func pasteClipboard() async {
        await importText { [clipboard] in
            (try clipboard.readClipboardText(), "clipboard", .plainText)
        }
    }

    func importSelection() async {
        let process = priorApplication
        await importText { [selection] in
            guard let process else { throw CurrentSelectionError.noPriorApplication }
            return (try selection.readSelectedText(from: process), "selection", .plainText)
        }
    }

    private func importText(_ read: @escaping @Sendable () throws -> (String, String, SpeechContentFormat)) async {
        guard !busy else { return }
        busy = true
        error = nil
        notice = nil
        defer { busy = false }
        do {
            let (text, origin, format) = try await Task.detached(operation: read).value
            try draft.append(text, origin: origin, format: format)
        } catch { self.error = error.localizedDescription }
    }

    func submit(playbackHeld: Bool) async {
        guard !busy else { return }
        error = nil
        notice = nil
        do {
            let submission = try draft.submission()
            busy = true
            defer { busy = false }
            try await Task.detached { [speech] in try speech.submit(submission) }.value
            clear()
            notice = playbackHeld
                ? "Queued. Playback is paused; use Resume when you’re ready."
                : "Queued for speech."
        } catch let SpeechServiceError.rejected(_, message) {
            error = message
        } catch { self.error = error.localizedDescription }
    }
}

@MainActor
final class SpeechSelectionTracker: NSObject {
    private let applicationNotifications: NotificationCenter
    private var activationObserver: NSObjectProtocol?

    init(state: AppState, applicationNotifications: NotificationCenter? = nil,
         ownProcessIdentifier: Int32 = ProcessInfo.processInfo.processIdentifier) {
        self.applicationNotifications = applicationNotifications ?? NSWorkspace.shared.notificationCenter
        super.init()
        activationObserver = self.applicationNotifications.addObserver(
            forName: NSWorkspace.didActivateApplicationNotification, object: nil, queue: .main
        ) { [weak state] notification in
            let process = (notification.userInfo?[NSWorkspace.applicationUserInfoKey]
                           as? NSRunningApplication)?.processIdentifier
            guard process != ownProcessIdentifier else { return }
            // The notification center delivers this observer on OperationQueue.main.
            MainActor.assumeIsolated { state?.composer.priorApplication = process }
        }
    }

    deinit {
        if let activationObserver { applicationNotifications.removeObserver(activationObserver) }
    }
}

struct SpeechComposerView: View {
    @EnvironmentObject var state: AppState
    @ObservedObject var composer: SpeechComposer
    @State private var importingFile = false
    @FocusState private var editorFocused: Bool

    private var localModels: [SpeechEngine] {
        if !state.engines.isEmpty { return state.engines.filter(\.isLocal) }
        guard let name = state.status?.engine else { return [] }
        return [SpeechEngine(name: name, isLocal: true, voices: state.voices, state: "unknown")]
    }

    private var modelVoices: [String] {
        let name = composer.draft.engine ?? state.status?.engine
        return localModels.first(where: { $0.name == name })?.voices ?? []
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("Speak").font(.headline)
                Spacer()
                Text("\(composer.draft.text.count) characters").font(.caption2).foregroundStyle(.secondary)
                Button { state.showingComposer = false } label: { Image(systemName: "xmark") }
                    .buttonStyle(.borderless)
                    .accessibilityLabel("Close speech editor")
            }
            TextEditor(text: $composer.draft.text)
                .font(.body)
                .frame(height: 100)
                .padding(6)
                .background(.background)
                .overlay(RoundedRectangle(cornerRadius: 6).stroke(.quaternary))
                .accessibilityLabel("Text to speak")
                .focused($editorFocused)
                .disabled(composer.busy)
            HStack {
                Button("Attach…", systemImage: "paperclip") { importingFile = true }
                Button("Paste") { Task { await composer.pasteClipboard() } }
                Button("Selection") { Task { await composer.importSelection() } }
                Spacer()
                Button("Clear") { composer.clear() }
            }.disabled(composer.busy)
            if !composer.draft.origins.isEmpty {
                Text("Imported: " + composer.draft.origins.joined(separator: ", "))
                    .font(.caption).foregroundStyle(.secondary).lineLimit(2)
                    .help(composer.draft.origins.joined(separator: "\n"))
            }
            VStack(alignment: .leading, spacing: 6) {
                Picker("Voice", selection: $composer.draft.voice) {
                    Text("Daemon default").tag(String?.none)
                    ForEach(modelVoices, id: \.self) { Text($0).tag(Optional($0)) }
                }
                Picker("Model", selection: $composer.draft.engine) {
                    Text("Daemon default").tag(String?.none)
                    ForEach(localModels) { engine in
                        Text(engine.name).tag(Optional(engine.name))
                    }
                }
                .onChange(of: composer.draft.engine) {
                    composer.draft.reconcileVoice(with: modelVoices)
                }
                .onChange(of: modelVoices) { _, voices in
                    composer.draft.reconcileVoice(with: voices)
                }
                Picker("Text", selection: $composer.draft.contentFormat) {
                    Text("Plain text").tag(SpeechContentFormat.plainText)
                    Text("Markdown").tag(SpeechContentFormat.markdown)
                }
            }.disabled(composer.busy)
            Text("Attach .txt, .md, or a PDF with selectable text. Imports are added to the editor. Model choices reflect the running daemon.")
                .font(.caption).foregroundStyle(.secondary)
            if let error = composer.error {
                Text(error).foregroundStyle(.red).textSelection(.enabled)
            }
            if let notice = composer.notice {
                Text(notice).foregroundStyle(.secondary)
            }
            HStack {
                if !state.reachable { Text("Connect to the daemon to submit.").foregroundStyle(.secondary) }
                if composer.busy { ProgressView().controlSize(.small) }
                Spacer()
                Button("Speak", systemImage: "speaker.wave.2.fill") {
                    Task { await composer.submit(playbackHeld: state.status?.playbackState == "paused") }
                }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(.return, modifiers: .command)
                .disabled(composer.busy || !state.reachable || composer.draft.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        .padding(10)
        .onAppear { editorFocused = true }
        .fileImporter(isPresented: $importingFile,
                      allowedContentTypes: LocalSpeechDocumentReader.allowedContentTypes) { result in
            switch result {
            case .success(let url): Task { await composer.attach(url) }
            case .failure(let error): composer.error = error.localizedDescription
            }
        }
    }
}

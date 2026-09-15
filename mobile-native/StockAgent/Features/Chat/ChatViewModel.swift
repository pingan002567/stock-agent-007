import Foundation

@MainActor
final class ChatViewModel: ObservableObject {
    @Published var sessions: [CopilotSession] = []
    @Published var currentSession: CopilotSession?
    @Published var rows: [ChatRow] = []
    @Published var draft = ""
    @Published var error = ""
    @Published var notice = ""
    @Published var drawerOpen = false
    @Published var uploads: [SessionUpload] = []
    @Published var uploadsSupported = true
    @Published var uploadsBusy = false
    /// Session IDs that currently have an in-flight SSE reply.
    @Published private(set) var streamingSessionIds: Set<String> = []

    private var streamTasks: [String: Task<Void, Never>] = [:]
    private var rowsBySession: [String: [ChatRow]] = [:]
    private var failedTextBySession: [String: String] = [:]
    private let api = APIClient.shared

    /// True only when the *visible* session is generating.
    var sending: Bool {
        guard let sid = currentSession?.sessionId else { return false }
        return streamingSessionIds.contains(sid)
    }

    var title: String {
        if let t = currentSession?.displayTitle, t != "未命名" { return t }
        if case .user(let b) = rows.first(where: {
            if case .user = $0 { return true }
            return false
        }) {
            let clipped = String(b.text.prefix(24))
            return clipped.isEmpty ? "Stock Agent" : clipped
        }
        return "Stock Agent"
    }

    var canRetry: Bool {
        guard let sid = currentSession?.sessionId, !sending else { return false }
        return failedTextBySession[sid] != nil
    }

    func isStreaming(sessionId: String) -> Bool {
        streamingSessionIds.contains(sessionId)
    }

    func bootstrap() async {
        error = ""
        do {
            sessions = try await api.fetchSessions()
            if currentSession == nil {
                currentSession = sessions.first
            }
            if let sid = currentSession?.sessionId {
                try await presentSession(sid, preferCacheIfStreaming: true)
                await refreshUploads()
            } else {
                rows = []
                uploads = []
            }
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }

    func openSession(_ session: CopilotSession) async {
        guard session.sessionId != currentSession?.sessionId else {
            drawerOpen = false
            return
        }
        persistCurrentRows()
        currentSession = session
        drawerOpen = false
        error = ""
        do {
            try await presentSession(session.sessionId, preferCacheIfStreaming: true)
            await refreshUploads()
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }

    func newSession() async {
        error = ""
        persistCurrentRows()
        do {
            let session = try await api.createSession()
            sessions.insert(session, at: 0)
            currentSession = session
            rows = []
            rowsBySession[session.sessionId] = []
            uploads = []
            uploadsSupported = true
            drawerOpen = false
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }

    func deleteSession(_ session: CopilotSession) async {
        let sid = session.sessionId
        cancelStream(sessionId: sid, finalizeTurn: false)
        rowsBySession.removeValue(forKey: sid)
        failedTextBySession.removeValue(forKey: sid)
        do {
            try await api.deleteSession(id: sid)
            sessions.removeAll { $0.sessionId == sid }
            if currentSession?.sessionId == sid {
                currentSession = sessions.first
                if let next = currentSession?.sessionId {
                    try await presentSession(next, preferCacheIfStreaming: true)
                    await refreshUploads()
                } else {
                    rows = []
                    uploads = []
                }
            }
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }

    func renameSession(_ session: CopilotSession, title: String) async {
        let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        do {
            let updated = try await api.renameSession(id: session.sessionId, title: trimmed)
            if let idx = sessions.firstIndex(where: { $0.sessionId == session.sessionId }) {
                sessions[idx] = updated
            }
            if currentSession?.sessionId == session.sessionId {
                currentSession = updated
            }
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }

    func send() async {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !sending else { return }
        await sendText(text)
    }

    func retryLastFailed() async {
        guard let sid = currentSession?.sessionId,
              let text = failedTextBySession[sid],
              !sending else { return }
        await sendText(text)
    }

    private func sendText(_ text: String) async {
        error = ""
        notice = ""
        draft = ""

        // Match desktop: pending composer chips clear immediately on send,
        // while filenames are attached to this message payload.
        let pendingUploads = uploads
        uploads = []

        do {
            if currentSession == nil {
                let session = try await api.createSession(title: String(text.prefix(24)))
                sessions.insert(session, at: 0)
                currentSession = session
                rows = []
                rowsBySession[session.sessionId] = []
            }
            guard let session = currentSession else { return }
            let sessionId = session.sessionId
            failedTextBySession.removeValue(forKey: sessionId)

            var list = rowsBySession[sessionId] ?? rows
            list.append(.user(UserBubble(
                id: "local-user-\(UUID().uuidString)",
                text: text,
                attachmentNames: pendingUploads.map(\.filename)
            )))
            let streamId = "stream-\(UUID().uuidString)"
            list.append(.assistant(AssistantTurn(
                id: streamId,
                phase: .reasoning,
                isStreaming: true
            )))
            rowsBySession[sessionId] = list
            if currentSession?.sessionId == sessionId {
                rows = list
            }

            streamingSessionIds.insert(sessionId)

            let run = try await api.sendMessage(
                sessionId: sessionId,
                message: text,
                attachments: pendingUploads
            )
            mutateAssistant(sessionId: sessionId, turnId: streamId) { $0.runId = run.runId }
            let url = try api.streamURL(sessionId: sessionId, runId: run.runId)
            startStream(url: url, turnId: streamId, sessionId: sessionId)
        } catch {
            // Restore chips so user can retry with the same attachments.
            if uploads.isEmpty {
                uploads = pendingUploads
            }
            if let sid = currentSession?.sessionId {
                failedTextBySession[sid] = text
                streamingSessionIds.remove(sid)
            }
            self.error = (error as? APIError)?.message ?? error.localizedDescription
            if let sid = currentSession?.sessionId,
               let idx = (rowsBySession[sid] ?? rows).indices.last {
                mutateLastAssistant(sessionId: sid) { turn in
                    turn.isStreaming = false
                    turn.failed = true
                    turn.phase = .error
                    if turn.displayAnswer.isEmpty { turn.answerText = self.error }
                }
                _ = idx
            }
        }
    }

    /// Stop only the currently visible session's stream.
    func stop() {
        guard let sid = currentSession?.sessionId else { return }
        cancelStream(sessionId: sid, finalizeTurn: true)
    }

    func refreshUploads() async {
        guard let sid = currentSession?.sessionId else {
            uploads = []
            return
        }
        do {
            let resp = try await api.listUploads(sessionId: sid)
            uploadsSupported = resp.supported ?? true
            uploads = resp.files ?? []
        } catch {}
    }

    func uploadFiles(_ urls: [URL]) async {
        guard let sid = currentSession?.sessionId else {
            error = "请先创建或打开一个会话"
            return
        }
        uploadsBusy = true
        defer { uploadsBusy = false }
        do {
            for url in urls { _ = url.startAccessingSecurityScopedResource() }
            defer { for url in urls { url.stopAccessingSecurityScopedResource() } }
            let resp = try await api.uploadFiles(sessionId: sid, fileURLs: urls)
            uploadsSupported = resp.supported ?? true
            if uploadsSupported == false {
                error = "当前运行时不支持附件上传"
            }
            await refreshUploads()
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }

    func deleteUpload(_ file: SessionUpload) async {
        guard let sid = currentSession?.sessionId else { return }
        do {
            try await api.deleteUpload(sessionId: sid, filename: file.filename)
            await refreshUploads()
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }

    // MARK: - Session presentation

    private func persistCurrentRows() {
        guard let sid = currentSession?.sessionId else { return }
        rowsBySession[sid] = rows
    }

    private func presentSession(_ sessionId: String, preferCacheIfStreaming: Bool) async throws {
        if preferCacheIfStreaming,
           streamingSessionIds.contains(sessionId),
           let cached = rowsBySession[sessionId] {
            rows = cached
            return
        }
        if let cached = rowsBySession[sessionId], streamingSessionIds.contains(sessionId) {
            rows = cached
            return
        }
        let messages = try await api.fetchMessages(sessionId: sessionId)
        let built = ChatHistoryBuilder.rows(from: messages)
        // Keep live streaming cache if still active (server may lag behind tokens).
        if streamingSessionIds.contains(sessionId), let live = rowsBySession[sessionId] {
            rows = live
        } else {
            rowsBySession[sessionId] = built
            rows = built
        }
    }

    // MARK: - Streaming

    private func startStream(url: URL, turnId: String, sessionId: String) {
        streamTasks[sessionId]?.cancel()
        streamingSessionIds.insert(sessionId)

        let task = Task { @MainActor [weak self] in
            guard let self else { return }
            let client = SSEClient(session: self.api.makeSSESession())
            let stream = await client.stream(url: url)
            do {
                for try await event in stream {
                    if Task.isCancelled { break }
                    self.apply(
                        update: CopilotStreamParser.parse(event),
                        sessionId: sessionId,
                        turnId: turnId
                    )
                }
                if !Task.isCancelled {
                    self.mutateAssistant(sessionId: sessionId, turnId: turnId) { turn in
                        turn.isStreaming = false
                        if turn.phase != .error {
                            turn.phase = .final
                        }
                    }
                }
            } catch {
                if !Task.isCancelled {
                    let message: String
                    if let apiErr = error as? APIError {
                        message = apiErr.message
                    } else {
                        message = TransportErrorMapper.map(error).message
                    }
                    if self.currentSession?.sessionId == sessionId {
                        self.error = message
                    }
                    self.mutateAssistant(sessionId: sessionId, turnId: turnId) { turn in
                        turn.isStreaming = false
                        turn.failed = true
                        turn.phase = .error
                        if turn.displayAnswer.isEmpty {
                            turn.answerText = message
                        }
                    }
                    self.failedTextBySession[sessionId] = self.lastUserText(in: sessionId)
                }
            }

            self.streamTasks[sessionId] = nil
            self.streamingSessionIds.remove(sessionId)

            if !Task.isCancelled {
                if self.currentSession?.sessionId != sessionId {
                    let title = self.sessions.first(where: { $0.sessionId == sessionId })?.displayTitle ?? "另一会话"
                    self.notice = "「\(title)」的回答已完成"
                }
                if let sessions = try? await self.api.fetchSessions() {
                    self.sessions = sessions
                    if self.currentSession?.sessionId == sessionId,
                       let updated = sessions.first(where: { $0.sessionId == sessionId }) {
                        self.currentSession = updated
                    }
                }
            }
        }
        streamTasks[sessionId] = task
    }

    private func cancelStream(sessionId: String, finalizeTurn: Bool) {
        streamTasks[sessionId]?.cancel()
        streamTasks[sessionId] = nil
        streamingSessionIds.remove(sessionId)
        guard finalizeTurn else { return }
        mutateLastAssistant(sessionId: sessionId) { turn in
            guard turn.isStreaming else { return }
            turn.isStreaming = false
            if turn.phase != .final && turn.phase != .error {
                turn.phase = turn.displayAnswer.isEmpty ? .error : .final
            }
        }
    }

    private func apply(update: StreamUpdate, sessionId: String, turnId: String) {
        mutateAssistant(sessionId: sessionId, turnId: turnId) { turn in
            switch update {
            case .reasoning(let text):
                turn.phase = .reasoning
                if turn.reasoningText.isEmpty {
                    turn.reasoningText = text
                } else if turn.reasoningText != text {
                    turn.reasoningText += "\n" + text
                }
            case .toolCall(let id, let name):
                turn.phase = .tools
                if !turn.tools.contains(where: { $0.id == id }) {
                    turn.tools.append(ToolChip(id: id, name: name, status: .running, resultPreview: ""))
                }
            case .toolResult(let id, let preview):
                turn.phase = .tools
                if let idx = turn.tools.firstIndex(where: { $0.id == id }) {
                    turn.tools[idx].status = .done
                    turn.tools[idx].resultPreview = preview
                } else {
                    turn.tools.append(ToolChip(id: id, name: "tool", status: .done, resultPreview: preview))
                }
            case .partialAnswer(let text):
                turn.phase = .answering
                turn.answerText += text
            case .finalAnswer(let text):
                turn.phase = .final
                turn.isStreaming = false
                if !text.isEmpty {
                    turn.answerText = text
                }
            case .error(let message):
                turn.phase = .error
                turn.failed = true
                turn.isStreaming = false
                if turn.displayAnswer.isEmpty {
                    turn.answerText = message
                }
                if self.currentSession?.sessionId == sessionId {
                    self.error = message
                }
                self.failedTextBySession[sessionId] = self.lastUserText(in: sessionId)
            case .ignore:
                break
            }
        }
    }

    private func mutateAssistant(sessionId: String, turnId: String, _ body: (inout AssistantTurn) -> Void) {
        var list = rowsBySession[sessionId] ?? []
        guard let idx = list.firstIndex(where: { $0.id == turnId }),
              case .assistant(var turn) = list[idx] else { return }
        body(&turn)
        list[idx] = .assistant(turn)
        rowsBySession[sessionId] = list
        if currentSession?.sessionId == sessionId {
            rows = list
        }
    }

    private func mutateLastAssistant(sessionId: String, _ body: (inout AssistantTurn) -> Void) {
        var list = rowsBySession[sessionId] ?? []
        guard let idx = list.indices.last,
              case .assistant(var turn) = list[idx] else { return }
        body(&turn)
        list[idx] = .assistant(turn)
        rowsBySession[sessionId] = list
        if currentSession?.sessionId == sessionId {
            rows = list
        }
    }

    private func lastUserText(in sessionId: String) -> String? {
        let list = rowsBySession[sessionId] ?? []
        for row in list.reversed() {
            if case .user(let b) = row { return b.text }
        }
        return nil
    }
}

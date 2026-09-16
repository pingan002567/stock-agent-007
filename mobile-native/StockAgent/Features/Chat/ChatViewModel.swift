import Foundation

/// Survives process death so re-entry can offer retry after an interrupted reply.
struct PendingStream: Codable, Equatable {
    var sessionId: String
    var runId: String?
    var userText: String
    var updatedAt: TimeInterval
}

enum PendingStreamStore {
    private static let key = "stockagent.pendingStreams"

    static func load() -> [PendingStream] {
        guard let data = UserDefaults.standard.data(forKey: key),
              let items = try? JSONDecoder().decode([PendingStream].self, from: data)
        else { return [] }
        return items
    }

    static func save(_ items: [PendingStream]) {
        if items.isEmpty {
            UserDefaults.standard.removeObject(forKey: key)
            return
        }
        if let data = try? JSONEncoder().encode(items) {
            UserDefaults.standard.set(data, forKey: key)
        }
    }

    static func upsert(_ item: PendingStream) {
        var items = load().filter { $0.sessionId != item.sessionId }
        items.append(item)
        save(items)
    }

    static func remove(sessionId: String) {
        save(load().filter { $0.sessionId != sessionId })
    }
}

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
    @Published private(set) var isLoadingOlder = false
    @Published private(set) var hasMoreHistory = false
    /// UI scroll instruction after prepend / open.
    @Published var scrollTarget: ScrollTarget?

    enum ScrollTarget: Equatable {
        case bottom(id: String)
        case pin(id: String)
    }

    private var streamTasks: [String: Task<Void, Never>] = [:]
    private var idleWatchdogs: [String: Task<Void, Never>] = [:]
    private var rowsBySession: [String: [ChatRow]] = [:]
    private var failedTextBySession: [String: String] = [:]
    private var historyCursorBySession: [String: HistoryCursor] = [:]
    private let api = APIClient.shared
    private let pageTurnLimit = 20

    private struct HistoryCursor {
        var hasMore: Bool
        var nextBefore: String?
        var isLoadingOlder: Bool = false
    }

    /// No meaningful SSE progress for this long → treat as stalled and unlock retry.
    private let streamIdleTimeoutSeconds: TimeInterval = 120
    private let emptyAnswerFallback =
        "回答未生成完整（工具可能已执行）。请点重试，或换个问法再试。"
    private let idleTimeoutFallback =
        "回答超时：长时间没有新内容。请点重试。"
    private let interruptedExitFallback =
        "上次回答在退出后中断（服务端已停止该轮，避免重复执行工具）。请点重试。"

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
            await recoverInterruptedStreamsAfterRelaunch()
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }

    /// Call when app returns to foreground (or after cold launch bootstrap).
    func handleAppBecameActive() async {
        await recoverInterruptedStreamsAfterRelaunch()
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
            historyCursorBySession[session.sessionId] = HistoryCursor(hasMore: false, nextBefore: nil)
            hasMoreHistory = false
            isLoadingOlder = false
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
        idleWatchdogs[sid]?.cancel()
        idleWatchdogs[sid] = nil
        clearPending(sessionId: sid)
        rowsBySession.removeValue(forKey: sid)
        historyCursorBySession.removeValue(forKey: sid)
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
            PendingStreamStore.upsert(PendingStream(
                sessionId: sessionId,
                runId: run.runId,
                userText: text,
                updatedAt: Date().timeIntervalSince1970
            ))
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
                PendingStreamStore.remove(sessionId: sid)
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
            syncHistoryFlags(for: sessionId)
            return
        }
        if let cached = rowsBySession[sessionId], streamingSessionIds.contains(sessionId) {
            rows = cached
            syncHistoryFlags(for: sessionId)
            return
        }
        // Keep already-paginated cache when switching back (unless streaming forced refresh).
        if let cached = rowsBySession[sessionId],
           historyCursorBySession[sessionId] != nil,
           !streamingSessionIds.contains(sessionId) {
            rows = cached
            syncHistoryFlags(for: sessionId)
            if let lastId = cached.last?.id {
                scrollTarget = .bottom(id: lastId)
            }
            return
        }

        let page = try await api.fetchMessagePage(
            sessionId: sessionId,
            limitTurns: pageTurnLimit,
            before: nil
        )
        let built = ChatHistoryBuilder.rows(from: page.items)
        historyCursorBySession[sessionId] = HistoryCursor(
            hasMore: page.hasMore,
            nextBefore: page.nextBefore
        )
        if streamingSessionIds.contains(sessionId), let live = rowsBySession[sessionId] {
            rows = live
        } else {
            rowsBySession[sessionId] = built
            rows = built
            if let lastId = built.last?.id {
                scrollTarget = .bottom(id: lastId)
            }
        }
        syncHistoryFlags(for: sessionId)
    }

    /// Load older turns when user scrolls near the top. Returns pin id for scroll restore.
    func loadOlderHistoryIfNeeded() async {
        guard let sessionId = currentSession?.sessionId else { return }
        guard !streamingSessionIds.contains(sessionId) else { return }
        var cursor = historyCursorBySession[sessionId] ?? HistoryCursor(hasMore: false, nextBefore: nil)
        guard cursor.hasMore, !cursor.isLoadingOlder, let before = cursor.nextBefore else {
            syncHistoryFlags(for: sessionId)
            return
        }

        cursor.isLoadingOlder = true
        historyCursorBySession[sessionId] = cursor
        isLoadingOlder = true

        let anchorId = rows.first?.id
        do {
            let page = try await api.fetchMessagePage(
                sessionId: sessionId,
                limitTurns: pageTurnLimit,
                before: before
            )
            let olderRows = ChatHistoryBuilder.rows(from: page.items)
            var existing = rowsBySession[sessionId] ?? rows
            let existingIds = Set(existing.map(\.id))
            let uniqueOlder = olderRows.filter { !existingIds.contains($0.id) }
            existing = uniqueOlder + existing
            rowsBySession[sessionId] = existing
            if currentSession?.sessionId == sessionId {
                rows = existing
            }
            cursor.hasMore = page.hasMore
            cursor.nextBefore = page.nextBefore
            cursor.isLoadingOlder = false
            historyCursorBySession[sessionId] = cursor
            if let anchorId {
                scrollTarget = .pin(id: anchorId)
            }
        } catch {
            cursor.isLoadingOlder = false
            historyCursorBySession[sessionId] = cursor
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
        syncHistoryFlags(for: sessionId)
    }

    func consumeScrollTarget() {
        scrollTarget = nil
    }

    private func syncHistoryFlags(for sessionId: String) {
        let cursor = historyCursorBySession[sessionId]
        if currentSession?.sessionId == sessionId {
            hasMoreHistory = cursor?.hasMore ?? false
            isLoadingOlder = cursor?.isLoadingOlder ?? false
        }
    }

    /// Refresh the latest turn window while keeping any already-loaded older prefix.

    // MARK: - Interrupt / relaunch recovery

    /// After kill/relaunch (or stream died in background): settle server run, reload history, unlock retry.
    /// Does **not** resume live generation — backend refuses to re-run tools on the same run_id.
    private func recoverInterruptedStreamsAfterRelaunch() async {
        let pending = PendingStreamStore.load()
        guard !pending.isEmpty else { return }

        var keep: [PendingStream] = []
        for item in pending {
            if streamingSessionIds.contains(item.sessionId) {
                keep.append(item)
                continue
            }
            await settleInterruptedPending(item)
        }
        PendingStreamStore.save(keep)
    }

    private func settleInterruptedPending(_ item: PendingStream) async {
        defer { PendingStreamStore.remove(sessionId: item.sessionId) }

        if let runId = item.runId, let url = try? api.streamURL(sessionId: item.sessionId, runId: runId) {
            // Trigger server stream_recovery guard so a final/error is persisted.
            await drainStreamQuietly(url: url)
        }

        if currentSession?.sessionId == item.sessionId {
            if let built = try? await reloadRows(sessionId: item.sessionId) {
                rowsBySession[item.sessionId] = built
                rows = built
            }
            markLastAssistantInterrupted(sessionId: item.sessionId)
            failedTextBySession[item.sessionId] = item.userText
            error = interruptedExitFallback
            notice = interruptedExitFallback
        } else {
            failedTextBySession[item.sessionId] = item.userText
            if notice.isEmpty {
                let title = sessions.first(where: { $0.sessionId == item.sessionId })?.displayTitle ?? "另一会话"
                notice = "「\(title)」上次回答在退出后中断，打开该会话后可重试。"
            }
        }
    }

    private func drainStreamQuietly(url: URL) async {
        let client = SSEClient(session: api.makeSSESession())
        let stream = await client.stream(url: url)
        do {
            for try await _ in stream {
                if Task.isCancelled { break }
            }
        } catch {
            // Expected when run already finished or network blips; history reload follows.
        }
    }

    private func reloadRows(sessionId: String) async throws -> [ChatRow] {
        let page = try await api.fetchMessagePage(
            sessionId: sessionId,
            limitTurns: pageTurnLimit,
            before: nil
        )
        let latest = ChatHistoryBuilder.rows(from: page.items)
        let previous = rowsBySession[sessionId] ?? []
        let prior = historyCursorBySession[sessionId]
        // Keep older-page cursor if user already scrolled up; otherwise adopt latest page cursor.
        if let prior, prior.nextBefore != nil, prior.hasMore {
            historyCursorBySession[sessionId] = HistoryCursor(
                hasMore: true,
                nextBefore: prior.nextBefore
            )
        } else {
            historyCursorBySession[sessionId] = HistoryCursor(
                hasMore: page.hasMore,
                nextBefore: page.nextBefore
            )
        }
        syncHistoryFlags(for: sessionId)

        guard !previous.isEmpty, let firstLatest = latest.first else {
            return latest
        }
        if let idx = previous.firstIndex(where: { $0.id == firstLatest.id }) {
            return Array(previous.prefix(idx)) + latest
        }
        if case .user(let user) = firstLatest,
           let idx = previous.lastIndex(where: {
               if case .user(let priorUser) = $0 { return priorUser.text == user.text }
               return false
           }) {
            return Array(previous.prefix(idx)) + latest
        }
        var merged = previous
        let ids = Set(merged.map(\.id))
        for row in latest where !ids.contains(row.id) {
            merged.append(row)
        }
        return merged
    }

    private func markLastAssistantInterrupted(sessionId: String) {
        mutateLastAssistant(sessionId: sessionId) { turn in
            guard turn.displayAnswer.isEmpty || turn.failed else { return }
            turn.isStreaming = false
            turn.failed = true
            turn.phase = .error
            if turn.displayAnswer.isEmpty {
                turn.answerText = interruptedExitFallback
            }
        }
    }

    private func clearPending(sessionId: String) {
        PendingStreamStore.remove(sessionId: sessionId)
    }

    // MARK: - Streaming

    private func startStream(url: URL, turnId: String, sessionId: String) {
        streamTasks[sessionId]?.cancel()
        idleWatchdogs[sessionId]?.cancel()
        streamingSessionIds.insert(sessionId)
        armIdleWatchdog(sessionId: sessionId, turnId: turnId)

        let task = Task { @MainActor [weak self] in
            guard let self else { return }
            let client = SSEClient(session: self.api.makeSSESession())
            let stream = await client.stream(url: url)
            var endedWithTransportError = false
            do {
                for try await event in stream {
                    if Task.isCancelled { break }
                    let update = CopilotStreamParser.parse(event)
                    if case .ignore = update {
                        // Keepalive / unknown frames: do not reset idle clock.
                    } else {
                        self.armIdleWatchdog(sessionId: sessionId, turnId: turnId)
                    }
                    self.apply(update: update, sessionId: sessionId, turnId: turnId)
                }
            } catch {
                endedWithTransportError = true
                if !Task.isCancelled {
                    let message: String
                    if let apiErr = error as? APIError {
                        message = apiErr.message
                    } else {
                        message = TransportErrorMapper.map(error).message
                    }
                    self.failTurn(
                        sessionId: sessionId,
                        turnId: turnId,
                        message: message,
                        surfaceError: true
                    )
                }
            }

            self.idleWatchdogs[sessionId]?.cancel()
            self.idleWatchdogs[sessionId] = nil
            self.streamTasks[sessionId] = nil
            self.streamingSessionIds.remove(sessionId)

            if !Task.isCancelled, !endedWithTransportError {
                await self.settleStreamCompletion(sessionId: sessionId, turnId: turnId)
            }

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

    /// Restart idle timer: meaningful SSE progress must arrive within ``streamIdleTimeoutSeconds``.
    private func armIdleWatchdog(sessionId: String, turnId: String) {
        idleWatchdogs[sessionId]?.cancel()
        let timeout = streamIdleTimeoutSeconds
        idleWatchdogs[sessionId] = Task { @MainActor [weak self] in
            guard let self else { return }
            try? await Task.sleep(nanoseconds: UInt64(timeout * 1_000_000_000))
            guard !Task.isCancelled else { return }
            guard self.streamingSessionIds.contains(sessionId) else { return }
            self.failTurn(
                sessionId: sessionId,
                turnId: turnId,
                message: self.idleTimeoutFallback,
                surfaceError: true
            )
            self.streamTasks[sessionId]?.cancel()
            self.streamTasks[sessionId] = nil
            self.streamingSessionIds.remove(sessionId)
            self.idleWatchdogs[sessionId] = nil
        }
    }

    /// After SSE closes: hydrate from history if possible; otherwise mark failed + enable retry.
    private func settleStreamCompletion(sessionId: String, turnId: String) async {
        guard var turn = assistantTurn(sessionId: sessionId, turnId: turnId) else { return }
        if turn.failed || turn.phase == .error {
            turn.isStreaming = false
            replaceAssistant(sessionId: sessionId, turnId: turnId, turn)
            clearPending(sessionId: sessionId)
            return
        }

        if !turn.displayAnswer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            turn.isStreaming = false
            turn.phase = .final
            replaceAssistant(sessionId: sessionId, turnId: turnId, turn)
            clearPending(sessionId: sessionId)
            return
        }

        // Stream ended with tools/reasoning only — try server-persisted final answer.
        if let recovered = await recoverAnswerFromHistory(sessionId: sessionId, runId: turn.runId),
           !recovered.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            turn.answerText = recovered
            turn.isStreaming = false
            turn.phase = .final
            turn.failed = false
            replaceAssistant(sessionId: sessionId, turnId: turnId, turn)
            clearPending(sessionId: sessionId)
            return
        }

        failTurn(
            sessionId: sessionId,
            turnId: turnId,
            message: emptyAnswerFallback,
            surfaceError: true
        )
    }

    private func recoverAnswerFromHistory(sessionId: String, runId: String?) async -> String? {
        guard let page = try? await api.fetchMessagePage(
            sessionId: sessionId,
            limitTurns: pageTurnLimit,
            before: nil
        ) else { return nil }
        let built = ChatHistoryBuilder.rows(from: page.items)
        for row in built.reversed() {
            guard case .assistant(let hist) = row else { continue }
            if let runId, let histRun = hist.runId, histRun != runId { continue }
            let text = hist.displayAnswer.trimmingCharacters(in: .whitespacesAndNewlines)
            if !text.isEmpty { return hist.answerText }
            if runId != nil { break }
        }
        return nil
    }

    private func failTurn(sessionId: String, turnId: String, message: String, surfaceError: Bool) {
        if surfaceError, currentSession?.sessionId == sessionId {
            error = message
        }
        mutateAssistant(sessionId: sessionId, turnId: turnId) { turn in
            turn.isStreaming = false
            turn.failed = true
            turn.phase = .error
            if turn.displayAnswer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                turn.answerText = message
            }
        }
        failedTextBySession[sessionId] = lastUserText(in: sessionId)
        clearPending(sessionId: sessionId)
    }
        idleWatchdogs[sessionId]?.cancel()
        idleWatchdogs[sessionId] = nil
        streamTasks[sessionId]?.cancel()
        streamTasks[sessionId] = nil
        streamingSessionIds.remove(sessionId)
        guard finalizeTurn else { return }
        mutateLastAssistant(sessionId: sessionId) { turn in
            guard turn.isStreaming else { return }
            turn.isStreaming = false
            if turn.displayAnswer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                turn.failed = true
                turn.phase = .error
                if turn.answerText.isEmpty {
                    turn.answerText = "已停止生成。可点重试继续。"
                }
                self.failedTextBySession[sessionId] = self.lastUserText(in: sessionId)
            } else if turn.phase != .final && turn.phase != .error {
                turn.phase = .final
            }
        }
        clearPending(sessionId: sessionId)
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
                self.clearPending(sessionId: sessionId)
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
                self.clearPending(sessionId: sessionId)
            case .ignore:
                break
            }
        }
    }

    private func assistantTurn(sessionId: String, turnId: String) -> AssistantTurn? {
        let list = rowsBySession[sessionId] ?? []
        guard let idx = list.firstIndex(where: { $0.id == turnId }),
              case .assistant(let turn) = list[idx] else { return nil }
        return turn
    }

    private func replaceAssistant(sessionId: String, turnId: String, _ turn: AssistantTurn) {
        var list = rowsBySession[sessionId] ?? []
        guard let idx = list.firstIndex(where: { $0.id == turnId }) else { return }
        list[idx] = .assistant(turn)
        rowsBySession[sessionId] = list
        if currentSession?.sessionId == sessionId {
            rows = list
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

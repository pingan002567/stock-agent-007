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
    @Published private(set) var streamingSessionIds: Set<String> = []
    @Published private(set) var isLoadingOlder = false
    @Published private(set) var hasMoreHistory = false
    @Published var scrollTarget: ScrollTarget?
    /// Symbol/page context for the next send (e.g. from stock detail).
    @Published var composeContext: ComposeContext?
    @Published var sendBlockedReason: String?

    enum ScrollTarget: Equatable {
        case bottom(id: String)
        case pin(id: String)
    }

    private var rowsBySession: [String: [ChatRow]] = [:]
    private var failedTextBySession: [String: String] = [:]
    private let api = APIClient.shared
    private let pager = ChatHistoryPager()
    private let streaming = ChatStreamingService()
    private let reachability = NetworkReachability.shared

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

    var canSend: Bool {
        reachability.isOnline && reachability.authFailureMessage == nil && sendBlockedReason == nil
    }

    func isStreaming(sessionId: String) -> Bool {
        streamingSessionIds.contains(sessionId)
    }

    func prepareCompose(page: String, symbol: String, draft prompt: String) {
        composeContext = ComposeContext(page: page, symbol: symbol)
        draft = prompt
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
            #if DEBUG
            let parserFailures = ChatParserSmoke.runAll()
            if !parserFailures.isEmpty {
                print("[ChatParserSmoke] failures: \(parserFailures.joined(separator: "; "))")
            }
            #endif
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
            noteAuthFailure(error)
        }
    }

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
            noteAuthFailure(error)
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
            pager.resetEmpty(sessionId: session.sessionId)
            loadedHistorySessions.insert(session.sessionId)
            hasMoreHistory = false
            isLoadingOlder = false
            uploads = []
            uploadsSupported = true
            drawerOpen = false
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
            noteAuthFailure(error)
        }
    }

    func deleteSession(_ session: CopilotSession) async {
        let sid = session.sessionId
        streaming.cancelLocal(sessionId: sid)
        streamingSessionIds.remove(sid)
        clearPending(sessionId: sid)
        rowsBySession.removeValue(forKey: sid)
        pager.remove(sessionId: sid)
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
            noteAuthFailure(error)
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
        guard !text.isEmpty, !sending, canSend else { return }
        await sendText(text, humanInputResponse: nil)
    }

    func retryLastFailed() async {
        guard let sid = currentSession?.sessionId,
              let text = failedTextBySession[sid],
              !sending,
              canSend else { return }
        await sendText(text, humanInputResponse: nil)
    }

    func submitClarification(response: [String: Any], displayText: String, for turnId: String) async {
        guard let sid = currentSession?.sessionId, canSend, !sending else { return }
        mutateAssistant(sessionId: sid, turnId: turnId) { turn in
            turn.clarificationAnswered = true
            turn.phase = .final
        }
        await sendText(displayText, humanInputResponse: response)
    }

    private func sendText(_ text: String, humanInputResponse: [String: Any]?) async {
        error = ""
        notice = ""
        draft = ""

        let pendingUploads = uploads
        uploads = []
        let context = composeContext
        composeContext = nil

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
                page: context?.page ?? "chat",
                symbol: context?.symbol ?? "",
                attachments: pendingUploads,
                humanInputResponse: humanInputResponse
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
            if uploads.isEmpty {
                uploads = pendingUploads
            }
            if let sid = currentSession?.sessionId {
                failedTextBySession[sid] = text
                streamingSessionIds.remove(sid)
                PendingStreamStore.remove(sessionId: sid)
            }
            self.error = (error as? APIError)?.message ?? error.localizedDescription
            noteAuthFailure(error)
            if let sid = currentSession?.sessionId {
                mutateLastAssistant(sessionId: sid) { turn in
                    turn.isStreaming = false
                    turn.failed = true
                    turn.phase = .error
                    if turn.displayAnswer.isEmpty { turn.answerText = self.error }
                }
            }
        }
    }

    /// Stop visible session: cancel server run first, then local SSE.
    func stop() {
        guard let sid = currentSession?.sessionId else { return }
        let runId = assistantTurnRunId(sessionId: sid)
        cancelStream(sessionId: sid, finalizeTurn: true)
        if let runId {
            Task {
                do {
                    try await api.cancelRun(sessionId: sid, runId: runId)
                } catch {
                    if self.notice.isEmpty {
                        self.notice = "已本地停止；服务端取消失败，可稍后重试。"
                    }
                }
            }
        }
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
        if let cached = rowsBySession[sessionId],
           loadedHistorySessions.contains(sessionId),
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
            limitTurns: pager.pageTurnLimit,
            before: nil
        )
        let built = ChatHistoryBuilder.rows(from: page.items)
        pager.adoptPage(sessionId: sessionId, hasMore: page.hasMore, nextBefore: page.nextBefore)
        loadedHistorySessions.insert(sessionId)
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

    private var loadedHistorySessions: Set<String> = []

    func loadOlderHistoryIfNeeded() async {
        guard let sessionId = currentSession?.sessionId else { return }
        guard pager.shouldAttemptLoad(
            sessionId: sessionId,
            rowCount: rows.count,
            isStreaming: streamingSessionIds.contains(sessionId)
        ) else {
            syncHistoryFlags(for: sessionId)
            return
        }

        let before = pager.cursor(for: sessionId).nextBefore
        guard let before else { return }

        pager.setLoading(true, sessionId: sessionId)
        isLoadingOlder = true

        let anchorId = rows.first?.id
        do {
            let page = try await api.fetchMessagePage(
                sessionId: sessionId,
                limitTurns: pager.pageTurnLimit,
                before: before
            )
            let olderRows = ChatHistoryBuilder.rows(from: page.items)
            var existing = rowsBySession[sessionId] ?? rows
            existing = ChatHistoryBuilder.mergePrepend(older: olderRows, existing: existing)
            rowsBySession[sessionId] = existing
            if currentSession?.sessionId == sessionId {
                rows = existing
            }
            pager.updateAfterLoad(sessionId: sessionId, hasMore: page.hasMore, nextBefore: page.nextBefore)
            if let anchorId {
                scrollTarget = .pin(id: anchorId)
            }
        } catch {
            pager.setLoading(false, sessionId: sessionId)
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
        syncHistoryFlags(for: sessionId)
    }

    func consumeScrollTarget() {
        scrollTarget = nil
    }

    private func syncHistoryFlags(for sessionId: String) {
        let cursor = pager.cursor(for: sessionId)
        if currentSession?.sessionId == sessionId {
            hasMoreHistory = cursor.hasMore
            isLoadingOlder = cursor.isLoadingOlder
        }
    }

    // MARK: - Interrupt / relaunch recovery

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

        if let runId = item.runId {
            try? await api.cancelRun(sessionId: item.sessionId, runId: runId)
            if let url = try? api.streamURL(sessionId: item.sessionId, runId: runId) {
                await drainStreamQuietly(url: url)
            }
        }

        if currentSession?.sessionId == item.sessionId {
            if let built = try? await reloadRows(sessionId: item.sessionId) {
                rowsBySession[item.sessionId] = built
                rows = built
            }
            markLastAssistantInterrupted(sessionId: item.sessionId)
            failedTextBySession[item.sessionId] = item.userText
            error = streaming.fallbacks.interruptedExit
            notice = streaming.fallbacks.interruptedExit
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
        } catch {}
    }

    private func reloadRows(sessionId: String) async throws -> [ChatRow] {
        let page = try await api.fetchMessagePage(
            sessionId: sessionId,
            limitTurns: pager.pageTurnLimit,
            before: nil
        )
        let latest = ChatHistoryBuilder.rows(from: page.items)
        let previous = rowsBySession[sessionId] ?? []
        pager.preserveOlderCursor(
            sessionId: sessionId,
            fallbackHasMore: page.hasMore,
            fallbackBefore: page.nextBefore
        )
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
                turn.answerText = streaming.fallbacks.interruptedExit
            }
        }
    }

    private func clearPending(sessionId: String) {
        PendingStreamStore.remove(sessionId: sessionId)
    }

    // MARK: - Streaming

    private func startStream(url: URL, turnId: String, sessionId: String) {
        streamingSessionIds.insert(sessionId)
        var settledByIdle = false
        streaming.start(
            url: url,
            sessionId: sessionId,
            turnId: turnId,
            api: api,
            onEvent: { [weak self] update in
                self?.apply(update: update, sessionId: sessionId, turnId: turnId)
            },
            onTransportError: { [weak self] message in
                guard let self else { return }
                settledByIdle = true
                self.failTurn(
                    sessionId: sessionId,
                    turnId: turnId,
                    message: message,
                    surfaceError: true
                )
                self.streamingSessionIds.remove(sessionId)
            },
            onFinished: { [weak self] cancelled, transportError in
                guard let self else { return }
                self.streamingSessionIds.remove(sessionId)
                Task { @MainActor in
                    if !cancelled, !transportError, !settledByIdle {
                        await self.settleStreamCompletion(sessionId: sessionId, turnId: turnId)
                    }
                    if !cancelled {
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
            }
        )
    }

    private func settleStreamCompletion(sessionId: String, turnId: String) async {
        guard var turn = assistantTurn(sessionId: sessionId, turnId: turnId) else { return }
        if turn.failed || turn.phase == .error {
            turn.isStreaming = false
            replaceAssistant(sessionId: sessionId, turnId: turnId, turn)
            clearPending(sessionId: sessionId)
            return
        }

        if turn.awaitingClarification {
            turn.isStreaming = false
            turn.phase = .clarification
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

        // History may have restored clarification without answer text.
        if let built = try? await reloadRows(sessionId: sessionId) {
            if let hist = built.reversed().compactMap({ row -> AssistantTurn? in
                if case .assistant(let t) = row { return t }
                return nil
            }).first(where: { $0.runId == turn.runId || turn.runId == nil }),
               hist.awaitingClarification {
                turn.clarificationRequest = hist.clarificationRequest
                turn.clarificationText = hist.clarificationText
                turn.isStreaming = false
                turn.phase = .clarification
                replaceAssistant(sessionId: sessionId, turnId: turnId, turn)
                clearPending(sessionId: sessionId)
                return
            }
        }

        failTurn(
            sessionId: sessionId,
            turnId: turnId,
            message: streaming.fallbacks.emptyAnswer,
            surfaceError: true
        )
    }

    private func recoverAnswerFromHistory(sessionId: String, runId: String?) async -> String? {
        guard let page = try? await api.fetchMessagePage(
            sessionId: sessionId,
            limitTurns: pager.pageTurnLimit,
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

    private func cancelStream(sessionId: String, finalizeTurn: Bool) {
        streaming.cancelLocal(sessionId: sessionId)
        streamingSessionIds.remove(sessionId)
        guard finalizeTurn else { return }
        mutateLastAssistant(sessionId: sessionId) { turn in
            guard turn.isStreaming || turn.phase != .final else { return }
            turn.isStreaming = false
            if turn.displayAnswer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                turn.failed = true
                turn.phase = .error
                if turn.answerText.isEmpty {
                    turn.answerText = streaming.fallbacks.stopped
                }
                self.failedTextBySession[sessionId] = self.lastUserText(in: sessionId)
            } else if turn.phase != .final && turn.phase != .error && turn.phase != .clarification {
                turn.phase = .final
            }
        }
        clearPending(sessionId: sessionId)
    }

    private func apply(update: StreamUpdate, sessionId: String, turnId: String) {
        mutateAssistant(sessionId: sessionId, turnId: turnId) { turn in
            ChatStreamingService.apply(update, to: &turn)
            switch update {
            case .finalAnswer:
                self.clearPending(sessionId: sessionId)
            case .clarification:
                self.clearPending(sessionId: sessionId)
            case .error(let message):
                if self.currentSession?.sessionId == sessionId, !message.contains("停止") {
                    self.error = message
                }
                if !message.contains("停止") {
                    self.failedTextBySession[sessionId] = self.lastUserText(in: sessionId)
                } else {
                    self.failedTextBySession[sessionId] = self.lastUserText(in: sessionId)
                }
                self.clearPending(sessionId: sessionId)
            default:
                break
            }
        }
    }

    private func noteAuthFailure(_ error: Error) {
        let message = (error as? APIError)?.message ?? error.localizedDescription
        if message.contains("401") || message.localizedCaseInsensitiveContains("unauthorized")
            || message.contains("未授权") || message.contains("登录") {
            reachability.reportUnauthorized()
        }
    }

    private func assistantTurnRunId(sessionId: String) -> String? {
        let list = rowsBySession[sessionId] ?? rows
        for row in list.reversed() {
            if case .assistant(let turn) = row, let runId = turn.runId {
                return runId
            }
        }
        return nil
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
        guard !sessionId.isEmpty else { return }
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

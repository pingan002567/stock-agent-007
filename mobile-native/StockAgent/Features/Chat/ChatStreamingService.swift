import Foundation

/// SSE / idle watchdog / pending-stream helpers used by ChatViewModel.
@MainActor
final class ChatStreamingService {
    struct Fallbacks {
        let emptyAnswer: String
        let idleTimeout: String
        let interruptedExit: String
        let stopped: String
    }

    let idleTimeoutSeconds: TimeInterval
    let fallbacks: Fallbacks

    private var streamTasks: [String: Task<Void, Never>] = [:]
    private var idleWatchdogs: [String: Task<Void, Never>] = [:]

    init(
        idleTimeoutSeconds: TimeInterval = 120,
        fallbacks: Fallbacks = Fallbacks(
            emptyAnswer: "回答未生成完整（工具可能已执行）。请点重试，或换个问法再试。",
            idleTimeout: "回答超时：长时间没有服务端心跳。请点重试，或检查远端连接。",
            interruptedExit: "上次回答在退出后中断（服务端已停止该轮，避免重复执行工具）。请点重试。",
            stopped: "已停止生成。可点重试继续。"
        )
    ) {
        self.idleTimeoutSeconds = idleTimeoutSeconds
        self.fallbacks = fallbacks
    }

    func isActive(sessionId: String) -> Bool {
        streamTasks[sessionId] != nil
    }

    func cancelLocal(sessionId: String) {
        idleWatchdogs[sessionId]?.cancel()
        idleWatchdogs[sessionId] = nil
        streamTasks[sessionId]?.cancel()
        streamTasks[sessionId] = nil
    }

    func armIdleWatchdog(
        sessionId: String,
        turnId: String,
        onTimeout: @escaping @MainActor (String, String) -> Void
    ) {
        idleWatchdogs[sessionId]?.cancel()
        let timeout = idleTimeoutSeconds
        idleWatchdogs[sessionId] = Task { @MainActor in
            try? await Task.sleep(nanoseconds: UInt64(timeout * 1_000_000_000))
            guard !Task.isCancelled else { return }
            onTimeout(sessionId, turnId)
        }
    }

    func clearIdle(sessionId: String) {
        idleWatchdogs[sessionId]?.cancel()
        idleWatchdogs[sessionId] = nil
    }

    func start(
        url: URL,
        sessionId: String,
        turnId: String,
        api: APIClient,
        onEvent: @escaping @MainActor (StreamUpdate) -> Void,
        onTransportError: @escaping @MainActor (String) -> Void,
        onFinished: @escaping @MainActor (_ cancelled: Bool, _ transportError: Bool) -> Void
    ) {
        streamTasks[sessionId]?.cancel()
        clearIdle(sessionId: sessionId)
        armIdleWatchdog(sessionId: sessionId, turnId: turnId) { sid, tid in
            onTransportError(self.fallbacks.idleTimeout)
            self.cancelLocal(sessionId: sid)
            _ = tid
        }

        let task = Task { @MainActor in
            let client = SSEClient(session: api.makeSSESession())
            let stream = await client.stream(url: url)
            var endedWithTransportError = false
            do {
                for try await event in stream {
                    if Task.isCancelled { break }
                    // Any SSE frame (incl. ping/progress keepalive) proves liveness —
                    // long-running tools must not trip the idle watchdog.
                    self.armIdleWatchdog(sessionId: sessionId, turnId: turnId) { sid, tid in
                        onTransportError(self.fallbacks.idleTimeout)
                        self.cancelLocal(sessionId: sid)
                        _ = tid
                    }
                    let update = CopilotStreamParser.parse(event)
                    onEvent(update)
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
                    onTransportError(message)
                }
            }

            self.clearIdle(sessionId: sessionId)
            self.streamTasks[sessionId] = nil
            onFinished(Task.isCancelled, endedWithTransportError)
        }
        streamTasks[sessionId] = task
    }

    static func apply(_ update: StreamUpdate, to turn: inout AssistantTurn) {
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
            if turn.awaitingClarification && text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                turn.phase = .clarification
                turn.isStreaming = false
            } else {
                turn.phase = .final
                turn.isStreaming = false
                if !text.isEmpty {
                    turn.answerText = text
                }
            }
        case .clarification(let request, let text):
            turn.phase = .clarification
            turn.isStreaming = false
            turn.failed = false
            if let request {
                turn.clarificationRequest = request
                turn.clarificationText = request.question
            } else if let text, !text.isEmpty {
                turn.clarificationText = text
            }
        case .skillTrace(let steps):
            var map = Dictionary(uniqueKeysWithValues: turn.skillTrace.map { ($0.skill, $0) })
            for step in steps {
                map[step.skill] = step
            }
            turn.skillTrace = map.values.sorted { $0.step < $1.step }
        case .error(let message):
            // User cancel surfaces as a soft stop, not a hard failure banner forever.
            let isCancel = message.contains("停止")
            turn.phase = isCancel ? .final : .error
            turn.failed = !isCancel
            turn.isStreaming = false
            if turn.displayAnswer.isEmpty {
                turn.answerText = message
            }
        case .ignore:
            break
        }
    }
}

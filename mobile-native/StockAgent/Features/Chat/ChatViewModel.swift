import Foundation

struct ChatBubble: Identifiable, Hashable {
    let id: String
    let role: String // user | assistant | system
    var text: String
    var isStreaming: Bool = false
}

@MainActor
final class ChatViewModel: ObservableObject {
    @Published var sessions: [CopilotSession] = []
    @Published var currentSession: CopilotSession?
    @Published var bubbles: [ChatBubble] = []
    @Published var draft = ""
    @Published var sending = false
    @Published var error = ""
    @Published var drawerOpen = false

    private var streamTask: Task<Void, Never>?
    private let api = APIClient.shared

    var title: String {
        let t = currentSession?.title.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return t.isEmpty ? "Stock Agent" : t
    }

    func bootstrap() async {
        error = ""
        do {
            sessions = try await api.fetchSessions()
            if currentSession == nil {
                currentSession = sessions.first
            }
            if let sid = currentSession?.sessionId {
                try await loadMessages(sessionId: sid)
            } else {
                bubbles = []
            }
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }

    func openSession(_ session: CopilotSession) async {
        currentSession = session
        drawerOpen = false
        do {
            try await loadMessages(sessionId: session.sessionId)
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }

    func newSession() async {
        error = ""
        do {
            let session = try await api.createSession()
            sessions.insert(session, at: 0)
            currentSession = session
            bubbles = []
            drawerOpen = false
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }

    func deleteSession(_ session: CopilotSession) async {
        do {
            try await api.deleteSession(id: session.sessionId)
            sessions.removeAll { $0.sessionId == session.sessionId }
            if currentSession?.sessionId == session.sessionId {
                currentSession = sessions.first
                if let sid = currentSession?.sessionId {
                    try await loadMessages(sessionId: sid)
                } else {
                    bubbles = []
                }
            }
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }

    func send() async {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !sending else { return }
        sending = true
        error = ""
        draft = ""
        defer { sending = false }

        do {
            if currentSession == nil {
                let session = try await api.createSession(title: String(text.prefix(24)))
                sessions.insert(session, at: 0)
                currentSession = session
            }
            guard let session = currentSession else { return }

            bubbles.append(ChatBubble(id: "local-user-\(UUID().uuidString)", role: "user", text: text))
            let streamId = "stream-\(UUID().uuidString)"
            bubbles.append(ChatBubble(id: streamId, role: "assistant", text: "", isStreaming: true))

            let run = try await api.sendMessage(sessionId: session.sessionId, message: text)
            let url = try api.streamURL(sessionId: session.sessionId, runId: run.runId)
            await consumeStream(url: url, bubbleId: streamId)
            sessions = try await api.fetchSessions()
            if let updated = sessions.first(where: { $0.sessionId == session.sessionId }) {
                currentSession = updated
            }
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
            if let idx = bubbles.lastIndex(where: { $0.isStreaming }) {
                bubbles[idx].isStreaming = false
                if bubbles[idx].text.isEmpty {
                    bubbles[idx].text = self.error
                }
            }
        }
    }

    func stop() {
        streamTask?.cancel()
        streamTask = nil
        if let idx = bubbles.lastIndex(where: { $0.isStreaming }) {
            bubbles[idx].isStreaming = false
        }
        sending = false
    }

    private func loadMessages(sessionId: String) async throws {
        let messages = try await api.fetchMessages(sessionId: sessionId)
        bubbles = messages.compactMap { msg in
            let role = msg.role == "user" ? "user" : "assistant"
            let text = msg.text?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            guard !text.isEmpty || role == "user" else { return nil }
            if msg.kind == "tool_call" || msg.kind == "tool_result" { return nil }
            return ChatBubble(id: msg.messageId, role: role, text: text.isEmpty ? " " : text)
        }
    }

    private func consumeStream(url: URL, bubbleId: String) async {
        streamTask?.cancel()
        let client = SSEClient(session: api.makeSSESession())
        let stream = await client.stream(url: url)
        streamTask = Task {
            var assembled = ""
            do {
                for try await event in stream {
                    if Task.isCancelled { break }
                    guard let parsed = CopilotStreamParser.text(from: event) else { continue }
                    switch parsed.kind {
                    case "partial_answer", "message":
                        assembled += parsed.text
                        updateBubble(id: bubbleId, text: assembled, streaming: true)
                    case "final":
                        if !parsed.text.isEmpty { assembled = parsed.text }
                        updateBubble(id: bubbleId, text: assembled.isEmpty ? parsed.text : assembled, streaming: false)
                    case "error":
                        updateBubble(id: bubbleId, text: parsed.text, streaming: false)
                        error = parsed.text
                    default:
                        break
                    }
                }
                updateBubble(id: bubbleId, text: nil, streaming: false)
            } catch {
                if !Task.isCancelled {
                    if let apiErr = error as? APIError {
                        self.error = apiErr.message
                    } else {
                        self.error = TransportErrorMapper.map(error).message
                    }
                    updateBubble(id: bubbleId, text: nil, streaming: false)
                }
            }
        }
        await streamTask?.value
    }

    private func updateBubble(id: String, text: String?, streaming: Bool) {
        guard let idx = bubbles.firstIndex(where: { $0.id == id }) else { return }
        if let text { bubbles[idx].text = text }
        bubbles[idx].isStreaming = streaming
    }
}

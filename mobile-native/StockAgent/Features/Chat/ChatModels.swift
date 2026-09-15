import Foundation

enum AssistantPhase: String, Hashable {
    case reasoning
    case tools
    case answering
    case final
    case error

    var label: String {
        switch self {
        case .reasoning: return "思考中"
        case .tools: return "调用工具"
        case .answering: return "生成回答"
        case .final: return ""
        case .error: return "出错"
        }
    }
}

struct ToolChip: Identifiable, Hashable {
    let id: String
    var name: String
    var status: Status
    var resultPreview: String

    enum Status: String, Hashable {
        case running
        case done
        case failed
    }
}

struct AssistantTurn: Identifiable, Hashable {
    let id: String
    var runId: String?
    var phase: AssistantPhase
    var reasoningText: String
    var tools: [ToolChip]
    var answerText: String
    var isStreaming: Bool
    var failed: Bool

    init(
        id: String,
        runId: String? = nil,
        phase: AssistantPhase = .reasoning,
        reasoningText: String = "",
        tools: [ToolChip] = [],
        answerText: String = "",
        isStreaming: Bool = false,
        failed: Bool = false
    ) {
        self.id = id
        self.runId = runId
        self.phase = phase
        self.reasoningText = reasoningText
        self.tools = tools
        self.answerText = answerText
        self.isStreaming = isStreaming
        self.failed = failed
    }

    var displayAnswer: String {
        answerText.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

struct UserBubble: Identifiable, Hashable {
    let id: String
    var text: String
    var attachmentNames: [String] = []
}

enum ChatRow: Identifiable, Hashable {
    case user(UserBubble)
    case assistant(AssistantTurn)

    var id: String {
        switch self {
        case .user(let b): return b.id
        case .assistant(let t): return t.id
        }
    }

    var scrollText: String {
        switch self {
        case .user(let b): return b.text
        case .assistant(let t): return t.answerText + t.reasoningText + t.tools.map(\.name).joined()
        }
    }
}

/// Parsed SSE update for an assistant turn.
enum StreamUpdate: Sendable {
    case reasoning(String)
    case toolCall(id: String, name: String)
    case toolResult(id: String, preview: String)
    case partialAnswer(String)
    case finalAnswer(String)
    case error(String)
    case ignore
}

enum CopilotStreamParser {
    static func parse(_ event: SSEEvent) -> StreamUpdate {
        guard let data = event.data.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return .ignore }

        let type = event.type.isEmpty || event.type == "message"
            ? ((obj["type"] as? String) ?? "message")
            : event.type
        let payload = obj["payload"] as? [String: Any] ?? [:]

        switch type {
        case "reasoning":
            if let text = stringValue(payload["text"]) ?? stringValue(obj["text"]), !text.isEmpty {
                return .reasoning(text)
            }
        case "tool_call":
            let name = stringValue(payload["tool"]) ?? stringValue(payload["name"]) ?? "tool"
            if name == "write_todos" { return .ignore }
            let callId = stringValue(payload["call_id"])
                ?? "\(name)-\(Int(Date().timeIntervalSince1970 * 1000))"
            return .toolCall(id: callId, name: name)
        case "tool_result":
            let callId = stringValue(payload["call_id"]) ?? ""
            guard !callId.isEmpty else { return .ignore }
            return .toolResult(id: callId, preview: extractToolResultText(payload))
        case "partial_answer", "message":
            if let text = stringValue(payload["text"])
                ?? stringValue(payload["content"])
                ?? stringValue(obj["text"]), !text.isEmpty {
                return .partialAnswer(text)
            }
        case "final":
            let text = stringValue(payload["conclusion"])
                ?? stringValue(payload["text"])
                ?? stringValue(payload["content"])
                ?? stringValue(obj["conclusion"])
                ?? stringValue(obj["text"])
                ?? ""
            return .finalAnswer(text)
        case "error":
            let msg = stringValue(payload["message"])
                ?? stringValue(payload["error"])
                ?? stringValue(obj["message"])
                ?? event.data
            return .error(msg)
        default:
            break
        }
        return .ignore
    }

    private static func stringValue(_ any: Any?) -> String? {
        if let s = any as? String { return s }
        if let n = any as? NSNumber { return n.stringValue }
        return nil
    }

    private static func extractToolResultText(_ payload: [String: Any]) -> String {
        if let t = stringValue(payload["text"]) { return String(t.prefix(2000)) }
        if let t = stringValue(payload["output"]) { return String(t.prefix(2000)) }
        if let t = stringValue(payload["result"]) { return String(t.prefix(2000)) }
        if let result = payload["result"] {
            if let data = try? JSONSerialization.data(withJSONObject: result),
               let s = String(data: data, encoding: .utf8) {
                return String(s.prefix(2000))
            }
        }
        var rest = payload
        rest.removeValue(forKey: "call_id")
        guard !rest.isEmpty,
              let data = try? JSONSerialization.data(withJSONObject: rest, options: [.sortedKeys]),
              let s = String(data: data, encoding: .utf8) else { return "" }
        return String(s.prefix(2000))
    }
}

enum ChatHistoryBuilder {
    /// Fold persisted messages into user bubbles + assistant turns by run_id.
    static func rows(from messages: [CopilotMessage]) -> [ChatRow] {
        var rows: [ChatRow] = []
        var openTurn: AssistantTurn?
        var openRunId: String?

        func flushTurn() {
            if var turn = openTurn {
                turn.phase = turn.failed ? .error : .final
                turn.isStreaming = false
                if turn.displayAnswer.isEmpty && turn.tools.isEmpty && turn.reasoningText.isEmpty {
                    // skip empty
                } else {
                    rows.append(.assistant(turn))
                }
            }
            openTurn = nil
            openRunId = nil
        }

        for msg in messages {
            let kind = msg.kind ?? ""
            let role = msg.role
            let text = (msg.text ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            let runId = msg.runId

            if role == "user" || kind == "user_message" {
                flushTurn()
                rows.append(.user(UserBubble(
                    id: msg.messageId,
                    text: text.isEmpty ? " " : text,
                    attachmentNames: attachmentNames(from: msg.payload)
                )))
                continue
            }

            if kind == "skill_trace" { continue }

            let sameRun = runId != nil && runId == openRunId
            if openTurn == nil || (runId != nil && !sameRun && openRunId != nil) {
                flushTurn()
                openTurn = AssistantTurn(id: msg.messageId, runId: runId, phase: .final)
                openRunId = runId
            } else if openTurn != nil, runId == nil, openRunId != nil {
                // orphan assistant without run_id after a run — start new if previous finalized content exists
            }

            guard var turn = openTurn else { continue }

            switch kind {
            case "tool_call":
                let name = payloadString(msg.payload, "tool")
                    ?? payloadString(msg.payload, "name")
                    ?? (text.isEmpty ? "tool" : text)
                let callId = payloadString(msg.payload, "call_id") ?? msg.messageId
                if !turn.tools.contains(where: { $0.id == callId }) {
                    turn.tools.append(ToolChip(id: callId, name: name, status: .done, resultPreview: ""))
                }
                turn.phase = .tools
            case "tool_result":
                let callId = payloadString(msg.payload, "call_id") ?? ""
                let preview = toolPreview(from: msg)
                if let idx = turn.tools.firstIndex(where: { $0.id == callId }) {
                    turn.tools[idx].status = .done
                    turn.tools[idx].resultPreview = preview
                } else if !callId.isEmpty {
                    turn.tools.append(ToolChip(id: callId, name: "tool", status: .done, resultPreview: preview))
                }
            case "partial_answer", "final_answer", "message":
                if !text.isEmpty {
                    if kind == "final_answer" || turn.answerText.isEmpty {
                        turn.answerText = text
                    } else if !turn.answerText.contains(text) {
                        turn.answerText += text
                    }
                }
                turn.phase = kind == "final_answer" ? .final : .answering
            case "error":
                turn.failed = true
                turn.phase = .error
                if !text.isEmpty { turn.answerText = text }
            case "reasoning":
                if !text.isEmpty {
                    turn.reasoningText = turn.reasoningText.isEmpty ? text : turn.reasoningText + "\n" + text
                }
            default:
                if role == "assistant", !text.isEmpty, kind != "tool_call", kind != "tool_result" {
                    turn.answerText = text
                    turn.phase = .final
                }
            }
            openTurn = turn
            if openRunId == nil { openRunId = runId }
        }
        flushTurn()
        return rows
    }

    private static func payloadString(_ payload: [String: JSONValue]?, _ key: String) -> String? {
        guard let v = payload?[key] else { return nil }
        if case .string(let s) = v { return s }
        return nil
    }

    private static func attachmentNames(from payload: [String: JSONValue]?) -> [String] {
        guard case .array(let items) = payload?["attachments"] else { return [] }
        return items.compactMap { item in
            guard case .object(let obj) = item,
                  case .string(let name) = obj["filename"],
                  !name.isEmpty else { return nil }
            return name
        }
    }

    private static func toolPreview(from msg: CopilotMessage) -> String {
        if let t = msg.text, !t.isEmpty { return String(t.prefix(2000)) }
        guard let payload = msg.payload else { return "" }
        if case .string(let s) = payload["text"] { return String(s.prefix(2000)) }
        if case .string(let s) = payload["output"] { return String(s.prefix(2000)) }
        return ""
    }
}

/// Minimal JSON value for message payloads.
enum JSONValue: Decodable, Hashable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null; return }
        if let b = try? c.decode(Bool.self) { self = .bool(b); return }
        if let n = try? c.decode(Double.self) { self = .number(n); return }
        if let s = try? c.decode(String.self) { self = .string(s); return }
        if let o = try? c.decode([String: JSONValue].self) { self = .object(o); return }
        if let a = try? c.decode([JSONValue].self) { self = .array(a); return }
        self = .null
    }

    var displayLine: String? {
        switch self {
        case .string(let s): return s
        case .number(let n): return String(n)
        case .bool(let b): return b ? "true" : "false"
        case .null: return nil
        case .array(let items):
            let parts = items.compactMap(\.displayLine)
            return parts.isEmpty ? nil : parts.joined(separator: ", ")
        case .object(let obj):
            if let t = obj["title"]?.displayLine { return t }
            if let m = obj["message"]?.displayLine { return m }
            if let s = obj["summary"]?.displayLine { return s }
            let parts = obj.map { "\($0.key)=\($0.value.displayLine ?? "")" }.sorted()
            return parts.isEmpty ? nil : parts.joined(separator: "; ")
        }
    }
}

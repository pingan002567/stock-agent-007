import Foundation

enum AssistantPhase: String, Hashable {
    case reasoning
    case tools
    case answering
    case clarification
    case final
    case error

    var label: String {
        switch self {
        case .reasoning: return "思考中"
        case .tools: return "调用工具"
        case .answering: return "生成回答"
        case .clarification: return "等待补充"
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

struct SkillTraceStep: Identifiable, Hashable, Sendable {
    var id: String { "\(step)-\(skill)" }
    var step: Int
    var skill: String
    var label: String
    var status: String
    var purpose: String?

    var displayTitle: String {
        let base = label.isEmpty ? skill : label
        return base.isEmpty ? "技能" : base
    }
}

struct HumanInputOption: Identifiable, Hashable, Sendable {
    let id: String
    var label: String
    var value: String
}

struct HumanInputRequest: Hashable, Sendable {
    var version: Int
    var source: String
    var requestId: String
    var toolCallId: String?
    var title: String?
    var question: String
    var context: String?
    var inputMode: String
    var options: [HumanInputOption]

    func optionResponse(option: HumanInputOption) -> [String: Any] {
        [
            "version": 1,
            "kind": "human_input_response",
            "source": source,
            "request_id": requestId,
            "response_kind": "option",
            "option_id": option.id,
            "value": option.value,
        ]
    }

    func textResponse(value: String) -> [String: Any] {
        [
            "version": 1,
            "kind": "human_input_response",
            "source": source,
            "request_id": requestId,
            "response_kind": "text",
            "value": value.trimmingCharacters(in: .whitespacesAndNewlines),
        ]
    }

    func displayMessage(for response: [String: Any]) -> String {
        let value = (response["value"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return value.isEmpty ? "（已回答澄清）" : value
    }
}

struct ComposeContext: Equatable {
    var page: String
    var symbol: String
}

struct AssistantTurn: Identifiable, Hashable {
    let id: String
    var runId: String?
    var phase: AssistantPhase
    var reasoningText: String
    var tools: [ToolChip]
    var skillTrace: [SkillTraceStep]
    var answerText: String
    var isStreaming: Bool
    var failed: Bool
    var clarificationRequest: HumanInputRequest?
    var clarificationText: String?
    var clarificationAnswered: Bool

    init(
        id: String,
        runId: String? = nil,
        phase: AssistantPhase = .reasoning,
        reasoningText: String = "",
        tools: [ToolChip] = [],
        skillTrace: [SkillTraceStep] = [],
        answerText: String = "",
        isStreaming: Bool = false,
        failed: Bool = false,
        clarificationRequest: HumanInputRequest? = nil,
        clarificationText: String? = nil,
        clarificationAnswered: Bool = false
    ) {
        self.id = id
        self.runId = runId
        self.phase = phase
        self.reasoningText = reasoningText
        self.tools = tools
        self.skillTrace = skillTrace
        self.answerText = answerText
        self.isStreaming = isStreaming
        self.failed = failed
        self.clarificationRequest = clarificationRequest
        self.clarificationText = clarificationText
        self.clarificationAnswered = clarificationAnswered
    }

    var displayAnswer: String {
        answerText.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var awaitingClarification: Bool {
        !clarificationAnswered
            && (clarificationRequest != nil
                || !(clarificationText ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
    }

    var hasRetryableFailure: Bool {
        failed && !isStreaming
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
        case .assistant(let t):
            return t.answerText
                + t.reasoningText
                + t.tools.map(\.name).joined()
                + (t.clarificationText ?? "")
                + t.skillTrace.map(\.displayTitle).joined()
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
    case clarification(HumanInputRequest?, text: String?)
    case skillTrace([SkillTraceStep])
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
            if let clarification = parseHumanInput(payload["clarification"] as? [String: Any]
                ?? obj["clarification"] as? [String: Any]) {
                return .clarification(clarification, text: clarification.question)
            }
            if let skillPayload = payload["skill_trace"] ?? obj["skill_trace"] {
                let steps = parseSkillTrace(skillPayload)
                if !steps.isEmpty {
                    // Prefer final answer text; skill_trace also applied separately via event.
                    _ = steps
                }
            }
            let text = stringValue(payload["conclusion"])
                ?? stringValue(payload["text"])
                ?? stringValue(payload["content"])
                ?? stringValue(obj["conclusion"])
                ?? stringValue(obj["text"])
                ?? ""
            return .finalAnswer(text)
        case "clarification":
            let request = parseHumanInput(payload) ?? parseHumanInput(obj)
            let text = request?.question
                ?? stringValue(payload["question"])
                ?? stringValue(payload["text"])
            return .clarification(request, text: text)
        case "skill_trace":
            let steps = parseSkillTrace(payload["items"] ?? payload["skill_trace"] ?? payload)
            if steps.isEmpty {
                let single = parseSkillTrace([payload])
                return single.isEmpty ? .ignore : .skillTrace(single)
            }
            return .skillTrace(steps)
        case "error":
            let msg = stringValue(payload["message"])
                ?? stringValue(payload["error"])
                ?? stringValue(obj["message"])
                ?? event.data
            return .error(msg)
        case "ping", "progress":
            // Backend liveness heartbeat — ChatStreamingService re-arms idle on any frame.
            return .ignore
        default:
            break
        }
        return .ignore
    }

    static func parseHumanInput(_ raw: [String: Any]?) -> HumanInputRequest? {
        guard let raw else { return nil }
        let question = stringValue(raw["question"]) ?? stringValue(raw["text"]) ?? ""
        guard !question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
        let requestId = stringValue(raw["request_id"])
            ?? stringValue(raw["call_id"])
            ?? "clarification:\(UUID().uuidString)"
        let optionsRaw = raw["options"] as? [Any] ?? []
        var options: [HumanInputOption] = []
        for (idx, item) in optionsRaw.enumerated() {
            if let s = item as? String, !s.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                let trimmed = s.trimmingCharacters(in: .whitespacesAndNewlines)
                options.append(HumanInputOption(id: "opt-\(idx + 1)", label: trimmed, value: trimmed))
            } else if let obj = item as? [String: Any] {
                let label = stringValue(obj["label"]) ?? stringValue(obj["value"]) ?? ""
                let value = stringValue(obj["value"]) ?? label
                let id = stringValue(obj["id"]) ?? "opt-\(idx + 1)"
                if !label.isEmpty {
                    options.append(HumanInputOption(id: id, label: label, value: value))
                }
            }
        }
        return HumanInputRequest(
            version: (raw["version"] as? Int) ?? 1,
            source: stringValue(raw["source"]) ?? "ask_clarification",
            requestId: requestId,
            toolCallId: stringValue(raw["tool_call_id"]) ?? stringValue(raw["call_id"]),
            title: stringValue(raw["title"]),
            question: question,
            context: stringValue(raw["context"]),
            inputMode: stringValue(raw["input_mode"])
                ?? (options.isEmpty ? "free_text" : "choice_with_other"),
            options: options
        )
    }

    static func parseSkillTrace(_ any: Any?) -> [SkillTraceStep] {
        let rows: [[String: Any]]
        if let arr = any as? [[String: Any]] {
            rows = arr
        } else if let arr = any as? [Any] {
            rows = arr.compactMap { $0 as? [String: Any] }
        } else if let obj = any as? [String: Any] {
            if let nested = obj["items"] as? [[String: Any]] {
                rows = nested
            } else if let nested = obj["skill_trace"] as? [[String: Any]] {
                rows = nested
            } else if obj["skill"] != nil || obj["label"] != nil {
                rows = [obj]
            } else {
                return []
            }
        } else {
            return []
        }
        return rows.enumerated().compactMap { idx, item in
            let skill = stringValue(item["skill"]) ?? ""
            let label = stringValue(item["label"]) ?? skill
            guard !skill.isEmpty || !label.isEmpty else { return nil }
            let step = (item["step"] as? Int)
                ?? (item["step"] as? NSNumber)?.intValue
                ?? (idx + 1)
            return SkillTraceStep(
                step: step,
                skill: skill.isEmpty ? label : skill,
                label: label,
                status: stringValue(item["status"]) ?? "pending",
                purpose: stringValue(item["purpose"])
            )
        }
    }

    static func stringValue(_ any: Any?) -> String? {
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
                if turn.awaitingClarification {
                    turn.phase = .clarification
                } else {
                    turn.phase = turn.failed ? .error : .final
                }
                turn.isStreaming = false
                if turn.displayAnswer.isEmpty
                    && turn.tools.isEmpty
                    && turn.reasoningText.isEmpty
                    && !turn.awaitingClarification
                    && turn.skillTrace.isEmpty {
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

            let sameRun = runId != nil && runId == openRunId
            if openTurn == nil || (runId != nil && !sameRun && openRunId != nil) {
                flushTurn()
                openTurn = AssistantTurn(id: msg.messageId, runId: runId, phase: .final)
                openRunId = runId
            }

            guard var turn = openTurn else { continue }

            switch kind {
            case "skill_trace":
                if let steps = skillTrace(from: msg), !steps.isEmpty {
                    turn.skillTrace = mergeSkillTrace(turn.skillTrace, steps)
                }
            case "clarification":
                if let request = humanInput(from: msg) {
                    turn.clarificationRequest = request
                    turn.clarificationText = request.question
                } else if !text.isEmpty {
                    turn.clarificationText = text
                }
                turn.phase = .clarification
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
                if let clarification = clarificationFromPayload(msg.payload) {
                    turn.clarificationRequest = clarification
                    turn.clarificationText = clarification.question
                    turn.phase = .clarification
                } else if !text.isEmpty {
                    if kind == "final_answer" || turn.answerText.isEmpty {
                        turn.answerText = text
                    } else if !turn.answerText.contains(text) {
                        turn.answerText += text
                    }
                    turn.phase = kind == "final_answer" ? .final : .answering
                }
                if kind == "final_answer", let steps = skillTrace(from: msg), !steps.isEmpty {
                    turn.skillTrace = mergeSkillTrace(turn.skillTrace, steps)
                }
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

    /// Merge older prepended rows with a newer page without duplicating ids.
    static func mergePrepend(older: [ChatRow], existing: [ChatRow]) -> [ChatRow] {
        let existingIds = Set(existing.map(\.id))
        let uniqueOlder = older.filter { !existingIds.contains($0.id) }
        return uniqueOlder + existing
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

    private static func humanInput(from msg: CopilotMessage) -> HumanInputRequest? {
        guard let payload = msg.payload else {
            if let text = msg.text, !text.isEmpty {
                return HumanInputRequest(
                    version: 1,
                    source: "ask_clarification",
                    requestId: "clarification:\(msg.messageId)",
                    toolCallId: nil,
                    title: nil,
                    question: text,
                    context: nil,
                    inputMode: "free_text",
                    options: []
                )
            }
            return nil
        }
        return clarificationFromPayload(payload)
    }

    private static func clarificationFromPayload(_ payload: [String: JSONValue]?) -> HumanInputRequest? {
        guard let payload else { return nil }
        var dict: [String: Any] = [:]
        for (k, v) in payload {
            dict[k] = jsonAny(v)
        }
        if let nested = dict["clarification"] as? [String: Any] {
            return CopilotStreamParser.parseHumanInput(nested)
        }
        return CopilotStreamParser.parseHumanInput(dict)
    }

    private static func skillTrace(from msg: CopilotMessage) -> [SkillTraceStep]? {
        guard let payload = msg.payload else { return nil }
        var dict: [String: Any] = [:]
        for (k, v) in payload {
            dict[k] = jsonAny(v)
        }
        let steps = CopilotStreamParser.parseSkillTrace(dict["skill_trace"] ?? dict["items"] ?? dict)
        return steps.isEmpty ? nil : steps
    }

    private static func mergeSkillTrace(_ current: [SkillTraceStep], _ incoming: [SkillTraceStep]) -> [SkillTraceStep] {
        var map = Dictionary(uniqueKeysWithValues: current.map { ($0.skill, $0) })
        for step in incoming {
            map[step.skill] = step
        }
        return map.values.sorted { $0.step < $1.step }
    }

    private static func jsonAny(_ value: JSONValue) -> Any {
        switch value {
        case .string(let s): return s
        case .number(let n): return n
        case .bool(let b): return b
        case .null: return NSNull()
        case .array(let items): return items.map(jsonAny)
        case .object(let obj): return obj.mapValues(jsonAny)
        }
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

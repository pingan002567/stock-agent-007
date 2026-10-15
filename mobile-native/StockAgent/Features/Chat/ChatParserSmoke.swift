import Foundation

#if DEBUG
/// Lightweight smoke assertions for stream/history parsers (no XCTest target required).
enum ChatParserSmoke {
    static func runAll() -> [String] {
        var failures: [String] = []

        let clarifyEvent = SSEEvent(
            type: "clarification",
            data: #"{"type":"clarification","payload":{"question":"仓位多少？","options":["10%","20%"],"request_id":"clarification:1","source":"ask_clarification","input_mode":"single_choice"}}"#
        )
        switch CopilotStreamParser.parse(clarifyEvent) {
        case .clarification(let req, let text):
            if req?.question != "仓位多少？" { failures.append("clarification question mismatch") }
            if (req?.options.count ?? 0) != 2 { failures.append("clarification options missing") }
            if text != "仓位多少？" { failures.append("clarification text mismatch") }
        default:
            failures.append("expected clarification update")
        }

        let skillEvent = SSEEvent(
            type: "skill_trace",
            data: #"{"type":"skill_trace","payload":{"items":[{"step":1,"skill":"research-analyst","label":"研究","status":"running"}]}}"#
        )
        switch CopilotStreamParser.parse(skillEvent) {
        case .skillTrace(let steps):
            if steps.first?.skill != "research-analyst" { failures.append("skill_trace skill mismatch") }
        default:
            failures.append("expected skill_trace update")
        }

        let older: [ChatRow] = [
            .user(UserBubble(id: "u1", text: "old")),
            .assistant(AssistantTurn(id: "a1", answerText: "old-a")),
        ]
        let existing: [ChatRow] = [
            .user(UserBubble(id: "u2", text: "new")),
            .assistant(AssistantTurn(id: "a2", answerText: "new-a")),
            .user(UserBubble(id: "u1", text: "dup")),
        ]
        let merged = ChatHistoryBuilder.mergePrepend(older: older, existing: existing)
        if merged.count != 4 { failures.append("mergePrepend count \(merged.count)") }
        if merged.first?.id != "u1" { failures.append("mergePrepend order") }

        let messages = [
            CopilotMessage(
                messageId: "m1",
                sessionId: "s",
                role: "user",
                kind: "user_message",
                text: "分析一下",
                createdAt: nil,
                runId: "r1",
                payload: nil
            ),
            CopilotMessage(
                messageId: "m2",
                sessionId: "s",
                role: "assistant",
                kind: "clarification",
                text: "时间周期？",
                createdAt: nil,
                runId: "r1",
                payload: [
                    "question": .string("时间周期？"),
                    "request_id": .string("clarification:x"),
                    "source": .string("ask_clarification"),
                    "input_mode": .string("free_text"),
                ]
            ),
        ]
        let rows = ChatHistoryBuilder.rows(from: messages)
        if rows.count != 2 { failures.append("history rows count") }
        if case .assistant(let turn) = rows.last {
            if !turn.awaitingClarification { failures.append("history clarification not restored") }
        } else {
            failures.append("history missing assistant")
        }

        return failures
    }
}
#endif

import SwiftUI

enum BubbleCollapsePolicy {
    /// Approx. characters before list bubble collapses into a preview.
    static let answerCharLimit = 280
    /// Soft line budget for preview.
    static let answerLineLimit = 5

    static func shouldCollapseAnswer(_ text: String) -> Bool {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.count > answerCharLimit { return true }
        let lines = trimmed.split(whereSeparator: \.isNewline).count
        return lines > answerLineLimit
    }

    static func preview(of text: String) -> String {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return "" }
        if trimmed.count <= answerCharLimit {
            let lines = trimmed.split(separator: "\n", omittingEmptySubsequences: false)
            if lines.count <= answerLineLimit { return trimmed }
            return lines.prefix(answerLineLimit).joined(separator: "\n") + "…"
        }
        let idx = trimmed.index(trimmed.startIndex, offsetBy: answerCharLimit)
        var slice = String(trimmed[..<idx])
        if let lastSpace = slice.lastIndex(where: { $0.isWhitespace || $0.isNewline }) {
            slice = String(slice[..<lastSpace])
        }
        return slice.trimmingCharacters(in: .whitespacesAndNewlines) + "…"
    }
}

struct AssistantBubbleView: View {
    let turn: AssistantTurn
    @State private var toolsExpanded = false

    private var answerCollapsed: Bool {
        !turn.isStreaming && BubbleCollapsePolicy.shouldCollapseAnswer(turn.answerText)
    }

    private var streamingCollapsed: Bool {
        turn.isStreaming && BubbleCollapsePolicy.shouldCollapseAnswer(turn.answerText)
    }

    var body: some View {
        HStack(alignment: .top, spacing: 0) {
            VStack(alignment: .leading, spacing: 10) {
                if turn.isStreaming, turn.phase != .final {
                    phaseBar
                }

                if !turn.reasoningText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    NavigationLink {
                        AssistantTurnDetailView(turn: turn, initialTab: .reasoning)
                    } label: {
                        metaChip(
                            title: "思考过程",
                            subtitle: String(turn.reasoningText.prefix(40)) + (turn.reasoningText.count > 40 ? "…" : ""),
                            systemImage: "brain.head.profile"
                        )
                    }
                    .buttonStyle(.plain)
                }

                if !turn.tools.isEmpty {
                    toolsCollapsedSection
                }

                answerSection

                if turn.failed {
                    Text("生成失败")
                        .font(.caption2)
                        .foregroundStyle(.red)
                }
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color(.secondarySystemBackground).opacity(0.94))
            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
            .contextMenu {
                if !turn.displayAnswer.isEmpty {
                    Button {
                        ChatClipboard.copy(turn.answerText)
                    } label: {
                        Label("复制回答", systemImage: "doc.on.doc")
                    }
                    ShareLink(item: turn.answerText) {
                        Label("分享回答", systemImage: "square.and.arrow.up")
                    }
                }
                if !turn.reasoningText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    Button {
                        ChatClipboard.copy(turn.reasoningText)
                    } label: {
                        Label("复制思考", systemImage: "brain.head.profile")
                    }
                }
                Button {
                    ChatClipboard.copy(fullTurnText)
                } label: {
                    Label("复制全部", systemImage: "doc.on.doc.fill")
                }
                if !fullTurnText.isEmpty {
                    ShareLink(item: fullTurnText) {
                        Label("分享全部", systemImage: "square.and.arrow.up")
                    }
                }
            }

            Spacer(minLength: 36)
        }
    }

    private var fullTurnText: String {
        var parts: [String] = []
        let reasoning = turn.reasoningText.trimmingCharacters(in: .whitespacesAndNewlines)
        if !reasoning.isEmpty { parts.append(reasoning) }
        if !turn.tools.isEmpty {
            parts.append(turn.tools.map(\.name).joined(separator: ", "))
        }
        let answer = turn.displayAnswer
        if !answer.isEmpty { parts.append(answer) }
        return parts.joined(separator: "\n\n")
    }

    private var phaseBar: some View {
        HStack(spacing: 8) {
            ProgressView()
                .controlSize(.small)
            Text(turn.phase.label.isEmpty ? "处理中" : turn.phase.label)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private var toolsCollapsedSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Button {
                withAnimation(.easeInOut(duration: 0.2)) {
                    toolsExpanded.toggle()
                }
            } label: {
                HStack(spacing: 8) {
                    Image(systemName: "wrench.and.screwdriver")
                        .font(.caption)
                    Text("工具调用 · \(turn.tools.count)")
                        .font(.caption.weight(.semibold))
                    Spacer(minLength: 4)
                    statusDots
                    Image(systemName: toolsExpanded ? "chevron.up" : "chevron.down")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                .foregroundStyle(.primary)
                .padding(.horizontal, 10)
                .padding(.vertical, 8)
                .background(Color(.tertiarySystemFill))
                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
            }
            .buttonStyle(.plain)

            if toolsExpanded {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(turn.tools) { tool in
                        NavigationLink {
                            AssistantTurnDetailView(turn: turn, initialTab: .tools, focusToolId: tool.id)
                        } label: {
                            HStack(spacing: 8) {
                                toolStatusIcon(tool.status)
                                Text(tool.name)
                                    .font(.caption)
                                    .lineLimit(1)
                                Spacer()
                                Text("详情")
                                    .font(.caption2)
                                    .foregroundStyle(.secondary)
                            }
                            .padding(.horizontal, 10)
                            .padding(.vertical, 6)
                            .background(toolColor(tool.status).opacity(0.12))
                            .foregroundStyle(toolColor(tool.status))
                            .clipShape(Capsule())
                        }
                        .buttonStyle(.plain)
                    }
                }
                .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
    }

    private var statusDots: some View {
        HStack(spacing: 4) {
            let running = turn.tools.filter { $0.status == .running }.count
            let done = turn.tools.filter { $0.status == .done }.count
            if running > 0 {
                Text("\(running) 进行中")
                    .font(.caption2)
                    .foregroundStyle(.blue)
            }
            if done > 0 {
                Text("\(done) 完成")
                    .font(.caption2)
                    .foregroundStyle(.green)
            }
        }
    }

    @ViewBuilder
    private var answerSection: some View {
        if turn.displayAnswer.isEmpty && turn.isStreaming && turn.tools.isEmpty && turn.reasoningText.isEmpty {
            Text("…")
                .foregroundStyle(.secondary)
        } else if turn.displayAnswer.isEmpty && !turn.isStreaming {
            EmptyView()
        } else if answerCollapsed || streamingCollapsed {
            NavigationLink {
                AssistantTurnDetailView(turn: turn, initialTab: .answer)
            } label: {
                VStack(alignment: .leading, spacing: 8) {
                    Text(BubbleCollapsePolicy.preview(of: turn.answerText))
                        .font(.body)
                        .foregroundStyle(.primary)
                        .multilineTextAlignment(.leading)
                        .lineLimit(BubbleCollapsePolicy.answerLineLimit)
                        .textSelection(.enabled)
                    HStack(spacing: 4) {
                        Text(turn.isStreaming ? "生成较长，点开看全文" : "查看完整回答")
                            .font(.caption.weight(.semibold))
                        Image(systemName: "chevron.right")
                            .font(.caption2)
                    }
                    .foregroundStyle(Color.accentColor)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
        } else {
            VStack(alignment: .leading, spacing: 8) {
                MarkdownText(
                    source: turn.answerText,
                    showCursor: turn.isStreaming && turn.phase == .answering
                )
                .font(.body)
                .frame(maxWidth: .infinity, alignment: .leading)

                if !turn.isStreaming, !turn.displayAnswer.isEmpty {
                    NavigationLink {
                        AssistantTurnDetailView(turn: turn, initialTab: .answer)
                    } label: {
                        Text("详情页阅读")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    private func metaChip(title: String, subtitle: String, systemImage: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: systemImage)
                .font(.caption)
                .foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.caption.weight(.semibold))
                Text(subtitle)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer(minLength: 0)
            Image(systemName: "chevron.right")
                .font(.caption2)
                .foregroundStyle(.tertiary)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background(Color(.tertiarySystemFill))
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
    }

    private func toolStatusIcon(_ status: ToolChip.Status) -> some View {
        Group {
            switch status {
            case .running: ProgressView().controlSize(.mini)
            case .done: Image(systemName: "checkmark.circle.fill")
            case .failed: Image(systemName: "xmark.circle.fill")
            }
        }
        .font(.caption)
    }

    private func toolColor(_ status: ToolChip.Status) -> Color {
        switch status {
        case .running: return .blue
        case .done: return .green
        case .failed: return .red
        }
    }
}

struct UserBubbleView: View {
    let bubble: UserBubble

    var body: some View {
        HStack {
            Spacer(minLength: 40)
            VStack(alignment: .trailing, spacing: 6) {
                if !bubble.attachmentNames.isEmpty {
                    VStack(alignment: .trailing, spacing: 4) {
                        ForEach(bubble.attachmentNames, id: \.self) { name in
                            HStack(spacing: 4) {
                                Image(systemName: "paperclip")
                                Text(name).lineLimit(1)
                            }
                            .font(.caption2)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 4)
                            .background(Color(.tertiarySystemFill))
                            .clipShape(Capsule())
                        }
                    }
                }
                Text(bubble.text)
                    .font(.body)
                    .textSelection(.enabled)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)
                    .background(Color(.secondarySystemBackground).opacity(0.94))
                    .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                    .contextMenu {
                        Button {
                            ChatClipboard.copy(bubble.text)
                        } label: {
                            Label("复制", systemImage: "doc.on.doc")
                        }
                    }
            }
        }
    }
}

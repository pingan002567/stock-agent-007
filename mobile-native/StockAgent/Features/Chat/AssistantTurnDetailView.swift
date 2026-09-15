import SwiftUI

struct AssistantTurnDetailView: View {
    enum Tab: String, CaseIterable, Identifiable {
        case answer, tools, reasoning
        var id: String { rawValue }
        var title: String {
            switch self {
            case .answer: return "回答"
            case .tools: return "工具"
            case .reasoning: return "思考"
            }
        }
    }

    let turn: AssistantTurn
    var initialTab: Tab = .answer
    var focusToolId: String?

    @State private var tab: Tab = .answer
    @State private var expandedToolId: String?

    var body: some View {
        VStack(spacing: 0) {
            Picker("分区", selection: $tab) {
                ForEach(availableTabs) { item in
                    Text(item.title).tag(item)
                }
            }
            .pickerStyle(.segmented)
            .padding(.horizontal, 16)
            .padding(.vertical, 10)

            Divider()

            ScrollView {
                Group {
                    switch tab {
                    case .answer:
                        answerPane
                    case .tools:
                        toolsPane
                    case .reasoning:
                        reasoningPane
                    }
                }
                .padding(16)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .background(Color(.systemBackground))
        .navigationTitle(navTitle)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItemGroup(placement: .topBarTrailing) {
                if tab == .answer, !turn.displayAnswer.isEmpty {
                    ShareLink(item: turn.answerText) {
                        Image(systemName: "square.and.arrow.up")
                    }
                    .accessibilityLabel("分享回答")
                    Button {
                        ChatClipboard.copy(turn.answerText)
                    } label: {
                        Image(systemName: "doc.on.doc")
                    }
                    .accessibilityLabel("复制回答")
                } else if tab == .reasoning,
                          !turn.reasoningText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    ShareLink(item: turn.reasoningText) {
                        Image(systemName: "square.and.arrow.up")
                    }
                    Button {
                        ChatClipboard.copy(turn.reasoningText)
                    } label: {
                        Image(systemName: "doc.on.doc")
                    }
                    .accessibilityLabel("复制思考")
                }
            }
        }
        .onAppear {
            tab = resolvedInitialTab
            expandedToolId = focusToolId
        }
    }

    private var availableTabs: [Tab] {
        var items: [Tab] = [.answer]
        if !turn.tools.isEmpty { items.append(.tools) }
        if !turn.reasoningText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            items.append(.reasoning)
        }
        return items
    }

    private var resolvedInitialTab: Tab {
        if availableTabs.contains(initialTab) { return initialTab }
        return availableTabs.first ?? .answer
    }

    private var navTitle: String {
        if turn.isStreaming { return "生成中…" }
        if turn.failed { return "回答失败" }
        return "回答详情"
    }

    private var answerPane: some View {
        VStack(alignment: .leading, spacing: 16) {
            if turn.displayAnswer.isEmpty {
                ContentUnavailableView(
                    turn.isStreaming ? "正在生成" : "暂无正文",
                    systemImage: "text.alignleft",
                    description: Text(turn.isStreaming ? "完成后将在这里格式化展示。" : "这轮没有可展示的回答文本。")
                )
                .frame(maxWidth: .infinity)
                .padding(.top, 40)
            } else {
                MarkdownText(
                    source: turn.answerText,
                    showCursor: turn.isStreaming && turn.phase == .answering,
                    richBlocks: true
                )
                .frame(maxWidth: .infinity, alignment: .leading)

                metaFooter
            }
        }
    }

    private var toolsPane: some View {
        VStack(alignment: .leading, spacing: 12) {
            if turn.tools.isEmpty {
                Text("本轮没有工具调用。")
                    .foregroundStyle(.secondary)
            } else {
                ForEach(turn.tools) { tool in
                    DisclosureGroup(
                        isExpanded: Binding(
                            get: { expandedToolId == tool.id },
                            set: { expandedToolId = $0 ? tool.id : nil }
                        )
                    ) {
                        Text(tool.resultPreview.isEmpty ? "暂无结果预览" : tool.resultPreview)
                            .font(.footnote.monospaced())
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.top, 8)
                    } label: {
                        HStack {
                            statusBadge(tool.status)
                            Text(tool.name)
                                .font(.subheadline.weight(.semibold))
                            Spacer()
                        }
                    }
                    .padding(12)
                    .background(Color(.secondarySystemBackground))
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                }
            }
        }
    }

    private var reasoningPane: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(turn.reasoningText)
                .font(.callout)
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var metaFooter: some View {
        VStack(alignment: .leading, spacing: 6) {
            Divider()
            if let runId = turn.runId {
                Text("run · \(runId)")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
            Text("字数 · \(turn.answerText.count) · 工具 · \(turn.tools.count)")
                .font(.caption2)
                .foregroundStyle(.tertiary)
        }
        .padding(.top, 8)
    }

    private func statusBadge(_ status: ToolChip.Status) -> some View {
        Group {
            switch status {
            case .running:
                ProgressView().controlSize(.mini)
            case .done:
                Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
            case .failed:
                Image(systemName: "xmark.circle.fill").foregroundStyle(.red)
            }
        }
        .font(.caption)
    }
}

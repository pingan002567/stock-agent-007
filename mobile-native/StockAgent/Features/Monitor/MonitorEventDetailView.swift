import SwiftUI

struct MonitorEventDetailView: View {
    let event: MonitorEvent

    var body: some View {
        List {
            Section("概要") {
                LabeledContent("标题", value: event.title ?? "—")
                if let severity = event.severity {
                    LabeledContent("级别", value: severity.uppercased())
                }
                if let symbol = event.symbol, !symbol.isEmpty {
                    LabeledContent("标的", value: symbol)
                }
                if let triggered = event.triggeredAt {
                    LabeledContent("触发时间", value: triggered)
                }
                if let source = event.source {
                    LabeledContent("来源", value: source)
                }
            }

            if let rule = event.triggerRule, !rule.isEmpty {
                Section("触发规则") {
                    Text(rule)
                        .font(.footnote.monospaced())
                        .textSelection(.enabled)
                }
            }

            if let message = event.message, !message.isEmpty {
                Section("说明") {
                    Text(message)
                        .font(.subheadline)
                        .textSelection(.enabled)
                }
            }

            if !event.payloadSummary.isEmpty {
                Section("载荷") {
                    Text(event.payloadSummary)
                        .font(.footnote.monospaced())
                        .textSelection(.enabled)
                }
            }

            if !event.evidenceLines.isEmpty {
                Section("证据") {
                    ForEach(Array(event.evidenceLines.enumerated()), id: \.offset) { _, line in
                        Text(line)
                            .font(.footnote)
                            .textSelection(.enabled)
                    }
                }
            }

            if let actions = event.suggestedActions, !actions.isEmpty {
                Section("建议动作") {
                    ForEach(actions, id: \.self) { action in
                        Text(action).font(.footnote)
                    }
                }
            }

            if event.isBrowsableSymbol, let symbol = event.symbol {
                Section {
                    NavigationLink {
                        StockDetailView(symbol: symbol)
                    } label: {
                        Label("查看标的 \(symbol)", systemImage: "chart.line.uptrend.xyaxis")
                    }
                }
            }

            if let ruleId = event.ruleId, !ruleId.isEmpty {
                Section("反馈") {
                    HStack {
                        Button("有用") {
                            Task { try? await APIClient.shared.sendMonitorFeedback(ruleId: ruleId, wasUseful: true) }
                        }
                        Button("无用") {
                            Task { try? await APIClient.shared.sendMonitorFeedback(ruleId: ruleId, wasUseful: false) }
                        }
                        .foregroundStyle(.secondary)
                    }
                }
            }
        }
        .navigationTitle("事件详情")
        .navigationBarTitleDisplayMode(.inline)
    }
}

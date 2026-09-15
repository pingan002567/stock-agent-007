import SwiftUI

struct HoldingsView: View {
    @State private var items: [HoldingItem] = []
    @State private var summary: HoldingsSummary?
    @State private var demo = false
    @State private var error = ""
    @State private var loading = true
    @State private var selected: HoldingItem?

    var body: some View {
        NavigationStack {
            Group {
                if loading {
                    ProgressView("加载持仓…")
                } else if !error.isEmpty && items.isEmpty {
                    ContentUnavailableView("加载失败", systemImage: "exclamationmark.triangle", description: Text(error))
                } else if items.isEmpty {
                    ContentUnavailableView(
                        "暂无持仓",
                        systemImage: "chart.line.uptrend.xyaxis",
                        description: Text("在桌面端导入持仓，或在对话里调整后会显示在这里。")
                    )
                } else {
                    List {
                        if let summary {
                            Section("组合摘要") {
                                LabeledContent("总市值", value: format(summary.totalValue))
                                LabeledContent("仓位数", value: "\(summary.positions ?? items.count)")
                                if let cash = summary.cashPct {
                                    LabeledContent("现金占比", value: String(format: "%.1f%%", cash))
                                }
                                if demo {
                                    Text("当前为演示组合")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                            }
                        }
                        Section("持仓") {
                            ForEach(items) { item in
                                Button {
                                    selected = item
                                } label: {
                                    HStack {
                                        VStack(alignment: .leading, spacing: 2) {
                                            Text(item.name ?? item.symbol ?? "—").font(.headline)
                                            if let qty = item.quantity {
                                                Text(String(format: "数量 %.2f", qty))
                                                    .font(.caption)
                                                    .foregroundStyle(.secondary)
                                            }
                                        }
                                        Spacer()
                                        VStack(alignment: .trailing, spacing: 2) {
                                            if let mv = item.marketValue {
                                                Text(String(format: "%.0f", mv)).font(.body.monospacedDigit())
                                            }
                                            if let pct = item.pnlPct {
                                                Text(String(format: "%+.2f%%", pct))
                                                    .font(.caption.monospacedDigit())
                                                    .foregroundStyle(pct >= 0 ? .green : .red)
                                            }
                                        }
                                        Image(systemName: "chevron.right")
                                            .font(.caption2)
                                            .foregroundStyle(.tertiary)
                                    }
                                }
                                .foregroundStyle(.primary)
                            }
                        }
                    }
                }
            }
            .navigationTitle("持仓")
            .refreshable { await load() }
            .task { await load() }
            .navigationDestination(item: $selected) { item in
                StockDetailView(symbol: item.symbol ?? item.id, fallbackName: item.name)
            }
        }
    }

    private func format(_ value: Double?) -> String {
        guard let value else { return "—" }
        return String(format: "%.0f", value)
    }

    private func load() async {
        loading = items.isEmpty
        error = ""
        do {
            let bundle = try await APIClient.shared.fetchHoldingsBundle()
            items = bundle.items ?? []
            summary = bundle.summary
            demo = bundle.demo ?? false
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
        loading = false
    }
}

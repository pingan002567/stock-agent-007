import SwiftUI

struct HoldingsView: View {
    @State private var items: [HoldingItem] = []
    @State private var error = ""
    @State private var loading = true

    var body: some View {
        NavigationStack {
            Group {
                if loading {
                    ProgressView("加载持仓…")
                } else if !error.isEmpty {
                    ContentUnavailableView("加载失败", systemImage: "exclamationmark.triangle", description: Text(error))
                } else if items.isEmpty {
                    ContentUnavailableView("暂无持仓", systemImage: "chart.line.uptrend.xyaxis", description: Text("导入或在对话中维护持仓后会显示在这里。"))
                } else {
                    List(items) { item in
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
                        }
                    }
                }
            }
            .navigationTitle("持仓")
            .refreshable { await load() }
            .task { await load() }
        }
    }

    private func load() async {
        loading = items.isEmpty
        error = ""
        do {
            items = try await APIClient.shared.fetchHoldings()
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
        loading = false
    }
}

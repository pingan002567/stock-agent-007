import SwiftUI

struct StrategyListView: View {
    @State private var items: [StrategyItem] = []
    @State private var error = ""
    @State private var loading = true

    var body: some View {
        Group {
            if loading {
                ProgressView("加载策略…")
            } else if !error.isEmpty && items.isEmpty {
                ContentUnavailableView("加载失败", systemImage: "exclamationmark.triangle", description: Text(error))
            } else if items.isEmpty {
                ContentUnavailableView("暂无策略", systemImage: "chart.xyaxis.line", description: Text("在桌面端创建策略后可在此查看与回测。"))
            } else {
                List(items) { item in
                    NavigationLink {
                        StrategyDetailView(strategy: item)
                    } label: {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(item.name ?? item.strategyId ?? "策略").font(.headline)
                            Text(item.strategyType ?? "—")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            if let desc = item.description, !desc.isEmpty {
                                Text(desc).font(.footnote).lineLimit(2).foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            }
        }
        .navigationTitle("策略回测")
        .refreshable { await load() }
        .task { await load() }
    }

    private func load() async {
        loading = items.isEmpty
        error = ""
        do {
            items = try await APIClient.shared.fetchStrategies()
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
        loading = false
    }
}

struct StrategyDetailView: View {
    let strategy: StrategyItem
    @State private var latest: BacktestRun?
    @State private var busy = false
    @State private var error = ""
    @State private var confirmRun = false

    private var strategyId: String { strategy.strategyId ?? strategy.id }

    var body: some View {
        List {
            Section("策略") {
                LabeledContent("名称", value: strategy.name ?? strategyId)
                LabeledContent("类型", value: strategy.strategyType ?? "—")
                if let desc = strategy.description, !desc.isEmpty {
                    Text(desc).font(.subheadline)
                }
            }
            Section("回测") {
                Button("运行回测") { confirmRun = true }
                    .disabled(busy)
                if busy { ProgressView() }
                if let latest {
                    BacktestResultCard(run: latest)
                } else {
                    Text("暂无历史回测").foregroundStyle(.secondary).font(.footnote)
                }
            }
            if !error.isEmpty {
                Section { Text(error).foregroundStyle(.red).font(.footnote) }
            }
        }
        .navigationTitle(strategy.name ?? "策略")
        .navigationBarTitleDisplayMode(.inline)
        .task { await loadLatest() }
        .confirmationDialog("确认运行回测？", isPresented: $confirmRun, titleVisibility: .visible) {
            Button("运行") { Task { await run() } }
            Button("取消", role: .cancel) {}
        }
    }

    private func loadLatest() async {
        latest = try? await APIClient.shared.fetchLatestBacktest(strategyId: strategyId)
    }

    private func run() async {
        busy = true
        error = ""
        defer { busy = false }
        do {
            latest = try await APIClient.shared.runBacktest(strategyId: strategyId)
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }
}

struct BacktestResultCard: View {
    let run: BacktestRun

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(run.runId).font(.caption).foregroundStyle(.secondary)
            if let m = run.metrics {
                metric("总收益", m.totalReturnPct.map { String(format: "%+.2f%%", $0) })
                metric("年化", m.annualizedReturnPct.map { String(format: "%+.2f%%", $0) })
                metric("最大回撤", m.maxDrawdownPct.map { String(format: "%.2f%%", $0) })
                metric("夏普", m.sharpeRatio.map { String(format: "%.2f", $0) })
                metric("胜率", m.winRate.map { String(format: "%.1f%%", $0 * (abs($0) <= 1 ? 100 : 1)) })
            }
            if run.degraded == true {
                Text(run.degradedReason ?? "结果降级")
                    .font(.caption2)
                    .foregroundStyle(.orange)
            }
        }
    }

    @ViewBuilder
    private func metric(_ title: String, _ value: String?) -> some View {
        if let value {
            LabeledContent(title, value: value)
        }
    }
}

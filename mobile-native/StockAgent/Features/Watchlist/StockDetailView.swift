import SwiftUI
import Charts

struct StockDetailView: View {
    let symbol: String
    var fallbackName: String?

    @EnvironmentObject private var tabs: TabRouter
    @EnvironmentObject private var chat: ChatViewModel

    @State private var context: StockContextBrief?
    @State private var bars: [HistoryBar] = []
    @State private var intel: [IntelItem] = []
    @State private var financial: FinancialRow?
    @State private var researchMessage = ""
    @State private var report: ReportDetail?
    @State private var showReport = false
    @State private var busy = false
    @State private var error = ""

    var body: some View {
        List {
            quoteSection
            if !bars.isEmpty {
                chartSection
            }
            metaSection
            if let financial {
                financialSection(financial)
            }
            if !intel.isEmpty {
                intelSection
            }
            actionsSection
            researchSection
            if !error.isEmpty {
                Section {
                    Text(error).foregroundStyle(.red).font(.footnote)
                }
            }
        }
        .navigationTitle(context?.name ?? fallbackName ?? symbol)
        .navigationBarTitleDisplayMode(.inline)
        .task { await loadAll() }
        .refreshable { await loadAll() }
        .sheet(isPresented: $showReport) {
            NavigationStack {
                Group {
                    if let report {
                        ScrollView {
                            MarkdownText(source: report.content ?? report.conclusion ?? "暂无正文", richBlocks: true)
                                .padding()
                        }
                        .navigationTitle(report.title ?? "研究报告")
                        .navigationBarTitleDisplayMode(.inline)
                    } else {
                        ProgressView("加载报告…")
                    }
                }
                .toolbar {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button("完成") { showReport = false }
                    }
                }
            }
        }
    }

    private var quoteSection: some View {
        Section("报价") {
            LabeledContent("代码", value: symbol)
            LabeledContent("名称", value: context?.name ?? fallbackName ?? "—")
            if let last = context?.price?.last {
                LabeledContent("最新价", value: String(format: "%.2f", last))
            }
            if let pct = context?.price?.changePct {
                LabeledContent("涨跌幅", value: String(format: "%+.2f%%", pct))
                    .foregroundStyle(pct >= 0 ? Color.green : Color.red)
            }
            if let source = context?.price?.source {
                LabeledContent("行情源", value: source)
            }
            if context?.price?.degraded == true {
                Text("行情已降级，数据可能滞后")
                    .font(.caption)
                    .foregroundStyle(.orange)
            }
        }
    }

    private var chartSection: some View {
        Section("近 \(bars.count) 日走势") {
            Chart(bars) { bar in
                if let close = bar.close {
                    LineMark(
                        x: .value("日", bar.date ?? ""),
                        y: .value("收盘", close)
                    )
                    .interpolationMethod(.catmullRom)
                    AreaMark(
                        x: .value("日", bar.date ?? ""),
                        y: .value("收盘", close)
                    )
                    .foregroundStyle(Color.accentColor.opacity(0.12))
                }
            }
            .chartXAxis(.hidden)
            .frame(height: 140)
            .padding(.vertical, 4)
        }
    }

    @ViewBuilder
    private var metaSection: some View {
        Section("概况") {
            if let industry = context?.industry, !industry.isEmpty {
                LabeledContent("行业", value: industry)
            }
            if let sector = context?.sector, !sector.isEmpty {
                LabeledContent("板块", value: sector)
            }
            if let market = context?.market, !market.isEmpty {
                LabeledContent("市场", value: market)
            }
            if let rel = context?.relation {
                HStack(spacing: 8) {
                    if rel.inWatchlist == true { chip("自选") }
                    if rel.inHoldings == true { chip("持仓") }
                    if rel.monitored == true { chip("盯盘") }
                }
            }
            if let ai = context?.aiState {
                if let stance = ai.stance, !stance.isEmpty {
                    LabeledContent("观点", value: stance)
                }
                if let risk = ai.riskLabel, !risk.isEmpty {
                    LabeledContent("风险", value: risk)
                }
            }
            if let holding = context?.holding, (holding.quantity ?? 0) > 0 {
                if let qty = holding.quantity {
                    LabeledContent("持仓数量", value: String(format: "%.2f", qty))
                }
                if let pnl = holding.pnlPct {
                    LabeledContent("持仓盈亏", value: String(format: "%+.2f%%", pnl))
                }
            }
            if let summary = context?.summary, !summary.isEmpty {
                Text(summary).font(.subheadline)
            }
        }
    }

    private func financialSection(_ row: FinancialRow) -> some View {
        Section("最新财报 · \(row.reportDate ?? "—")") {
            if let revenue = row.revenue {
                LabeledContent("营收", value: formatMoney(revenue))
            }
            if let profit = row.profit {
                LabeledContent("净利润", value: formatMoney(profit))
                    .foregroundStyle(profit >= 0 ? Color.primary : Color.red)
            }
            if let assets = row.totalAssets {
                LabeledContent("总资产", value: formatMoney(assets))
            }
        }
    }

    private var intelSection: some View {
        Section("近期资讯") {
            ForEach(intel.prefix(5)) { item in
                VStack(alignment: .leading, spacing: 4) {
                    Text(item.title ?? "资讯")
                        .font(.subheadline.weight(.medium))
                    HStack {
                        if let source = item.source {
                            Text(source).font(.caption2).foregroundStyle(.secondary)
                        }
                        if let published = item.publishedAt {
                            Text(published).font(.caption2).foregroundStyle(.tertiary)
                        }
                    }
                }
                .padding(.vertical, 2)
            }
        }
    }

    private var actionsSection: some View {
        Section("快捷") {
            Button {
                askInChat()
            } label: {
                Label("在对话中分析", systemImage: "bubble.left.and.bubble.right")
            }
            if let reportId = context?.latestReport?.reportId ?? report?.reportId {
                Button {
                    Task { await openReport(reportId) }
                } label: {
                    Label("查看最新报告", systemImage: "doc.text")
                }
            }
        }
    }

    private var researchSection: some View {
        Section("研究") {
            if let status = context?.researchStatus, !status.isEmpty {
                LabeledContent("研究状态", value: status)
            }
            Button {
                Task { await runResearch() }
            } label: {
                if busy {
                    ProgressView()
                } else {
                    Text("生成轻量研究")
                }
            }
            .disabled(busy)
            if !researchMessage.isEmpty {
                Text(researchMessage)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            if let status = context?.researchStatus, !status.isEmpty {
                Button {
                    askInChat()
                } label: {
                    Label("在对话中跟进研究（\(status)）", systemImage: "arrow.up.right.circle")
                }
            }
        }
    }

    private func chip(_ text: String) -> some View {
        Text(text)
            .font(.caption2.weight(.semibold))
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(Color.accentColor.opacity(0.12))
            .foregroundStyle(Color.accentColor)
            .clipShape(Capsule())
    }

    private func formatMoney(_ value: Double) -> String {
        let abs = abs(value)
        if abs >= 1e8 { return String(format: "%.2f亿", value / 1e8) }
        if abs >= 1e4 { return String(format: "%.2f万", value / 1e4) }
        return String(format: "%.0f", value)
    }

    private func askInChat() {
        let name = context?.name ?? fallbackName ?? symbol
        let prompt = "请分析 \(symbol)（\(name)）：结合近期行情、资讯与风险，给出简要观点与观察位。不下单，仅供研究参考。"
        chat.prepareCompose(page: "stock_detail", symbol: symbol, draft: prompt)
        tabs.selected = .chat
    }

    private func loadAll() async {
        error = ""
        async let ctxTask: Void = loadContext()
        async let histTask: Void = loadHistory()
        async let intelTask: Void = loadIntel()
        async let finTask: Void = loadFinancial()
        _ = await (ctxTask, histTask, intelTask, finTask)
    }

    private func loadContext() async {
        do {
            context = try await APIClient.shared.fetchStockContext(symbol: symbol)
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }

    private func loadHistory() async {
        bars = (try? await APIClient.shared.fetchStockHistory(symbol: symbol, days: 30)) ?? []
    }

    private func loadIntel() async {
        intel = (try? await APIClient.shared.fetchStockIntel(symbol: symbol)) ?? []
    }

    private func loadFinancial() async {
        financial = (try? await APIClient.shared.fetchStockFinancial(symbol: symbol))?.items?.first
    }

    private func runResearch() async {
        busy = true
        defer { busy = false }
        do {
            let result = try await APIClient.shared.triggerStockResearch(symbol: symbol)
            researchMessage = result.message ?? "已提交研究任务"
            if let reportId = result.reportId {
                await openReport(reportId)
            } else if let existing = context?.latestReport?.reportId {
                await openReport(existing)
            }
            await loadContext()
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }

    private func openReport(_ reportId: String) async {
        do {
            report = try await APIClient.shared.fetchReport(reportId: reportId)
            showReport = true
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }
}

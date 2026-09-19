import SwiftUI

struct RuntimeSettingsView: View {
    var initial: WorkbenchSettings?

    @State private var settings: WorkbenchSettings?
    @State private var error = ""
    @State private var loading = true

    var body: some View {
        List {
            if let runtime = settings?.agentRuntime ?? initial?.agentRuntime {
                Section("Agent Runtime") {
                    LabeledContent("客户端", value: runtime.activeClient ?? "—")
                    LabeledContent("模式", value: runtime.mode ?? "—")
                    LabeledContent("模型", value: runtime.modelName ?? "—")
                    LabeledContent("可用", value: boolLabel(runtime.available))
                    LabeledContent("降级", value: boolLabel(runtime.degraded))
                    if let reason = runtime.degradedReason, !reason.isEmpty {
                        Text(reason)
                            .font(.footnote)
                            .foregroundStyle(.orange)
                    }
                    LabeledContent("思考", value: boolLabel(runtime.thinkingEnabled))
                    LabeledContent("子代理", value: boolLabel(runtime.subagentEnabled))
                    LabeledContent("计划模式", value: boolLabel(runtime.planMode))
                }
            }

            if let cfg = settings?.runtimeConfig ?? initial?.runtimeConfig {
                Section("模型配置") {
                    LabeledContent("Provider", value: cfg.providerId ?? "—")
                    LabeledContent("模型", value: cfg.modelName ?? cfg.defaultModel ?? "—")
                    LabeledContent("API Key", value: (cfg.hasApiKey == true) ? "已配置" : "未配置")
                    if let base = cfg.baseUrl, !base.isEmpty {
                        LabeledContent("Base URL", value: base)
                    }
                }
            }

            if let dp = settings?.dataProvider ?? initial?.dataProvider {
                Section("行情数据源") {
                    LabeledContent("主源", value: dp.activeProvider ?? "—")
                    LabeledContent("回退", value: dp.fallbackProvider ?? "—")
                    LabeledContent("AKShare", value: boolLabel(dp.akshareAvailable))
                    LabeledContent("降级", value: boolLabel(dp.degraded))
                    if let reason = dp.degradedReason, !reason.isEmpty {
                        Text(reason)
                            .font(.footnote)
                            .foregroundStyle(.orange)
                    }
                }
            }

            if !error.isEmpty {
                Section {
                    Text(error).font(.footnote).foregroundStyle(.red)
                }
            }
        }
        .navigationTitle("运行状态")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .refreshable { await load() }
    }

    private func boolLabel(_ value: Bool?) -> String {
        guard let value else { return "—" }
        return value ? "是" : "否"
    }

    private func load() async {
        loading = true
        defer { loading = false }
        do {
            settings = try await APIClient.shared.fetchSettings()
            error = ""
        } catch {
            if settings == nil && initial == nil {
                self.error = (error as? APIError)?.message ?? error.localizedDescription
            }
        }
    }
}

struct SkillsSettingsView: View {
    var initialSkills: [SkillInfo]

    @State private var skills: [SkillInfo] = []
    @State private var busyName: String?
    @State private var error = ""

    var body: some View {
        List {
            Section {
                ForEach(skills) { skill in
                    Toggle(isOn: Binding(
                        get: { skill.enabled ?? false },
                        set: { newValue in
                            Task { await setEnabled(skill, enabled: newValue) }
                        }
                    )) {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(skill.displayName)
                            if let desc = skill.description, !desc.isEmpty {
                                Text(desc)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                    .lineLimit(3)
                            }
                            if let authority = skill.authority {
                                Text(authority)
                                    .font(.caption2)
                                    .foregroundStyle(.tertiary)
                            }
                        }
                    }
                    .disabled(skill.locked == true || busyName == skill.name)
                }
            } footer: {
                Text("关闭后 Agent 不会委派该技能。锁定技能不可改。")
            }

            if !error.isEmpty {
                Section {
                    Text(error).font(.footnote).foregroundStyle(.red)
                }
            }
        }
        .navigationTitle("AI 技能")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            if skills.isEmpty {
                skills = initialSkills
            }
        }
        .task {
            if let fresh = try? await APIClient.shared.fetchSettings().skills {
                skills = fresh
            }
        }
        .refreshable {
            if let fresh = try? await APIClient.shared.fetchSettings().skills {
                skills = fresh
            }
        }
    }

    private func setEnabled(_ skill: SkillInfo, enabled: Bool) async {
        busyName = skill.name
        defer { busyName = nil }
        // Optimistic
        if let idx = skills.firstIndex(where: { $0.name == skill.name }) {
            skills[idx].enabled = enabled
        }
        do {
            skills = try await APIClient.shared.setSkillEnabled(name: skill.name, enabled: enabled)
            error = ""
        } catch {
            // Revert
            if let idx = skills.firstIndex(where: { $0.name == skill.name }) {
                skills[idx].enabled = !enabled
            }
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }
}

struct CostSettingsView: View {
    @State private var days: [CostDay] = []
    @State private var error = ""
    @State private var loading = true

    var body: some View {
        List {
            if loading && days.isEmpty {
                ProgressView("加载用量…")
            } else if days.isEmpty {
                ContentUnavailableView("暂无用量", systemImage: "chart.bar", description: Text(error.isEmpty ? "还没有计费记录。" : error))
            } else {
                Section("近几日") {
                    ForEach(days) { day in
                        VStack(alignment: .leading, spacing: 6) {
                            HStack {
                                Text(day.date ?? "—").font(.headline)
                                Spacer()
                                Text(String(format: "¥%.3f", day.totalCost ?? 0))
                                    .font(.body.monospacedDigit())
                            }
                            HStack {
                                Text("运行 \(day.runCount ?? 0) 次")
                                Spacer()
                                Text("in \(formatTokens(day.totalInputTokens)) · out \(formatTokens(day.totalOutputTokens))")
                            }
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        }
                        .padding(.vertical, 2)
                    }
                }
                Section {
                    LabeledContent("合计费用", value: String(format: "¥%.3f", days.compactMap(\.totalCost).reduce(0, +)))
                    LabeledContent("合计运行", value: "\(days.compactMap(\.runCount).reduce(0, +)) 次")
                }
            }
        }
        .navigationTitle("用量与费用")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .refreshable { await load() }
    }

    private func formatTokens(_ n: Int?) -> String {
        guard let n else { return "—" }
        if n >= 1_000_000 { return String(format: "%.1fM", Double(n) / 1_000_000) }
        if n >= 1_000 { return String(format: "%.1fK", Double(n) / 1_000) }
        return "\(n)"
    }

    private func load() async {
        loading = true
        defer { loading = false }
        do {
            days = try await APIClient.shared.fetchCostSummary()
            error = ""
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }
}

struct ReportsListView: View {
    var initialReportId: String? = nil

    @State private var items: [ReportListItem] = []
    @State private var error = ""
    @State private var loading = true
    @State private var selected: ReportDetail?

    var body: some View {
        Group {
            if loading && items.isEmpty {
                ProgressView("加载报告…")
            } else if items.isEmpty {
                ContentUnavailableView("暂无报告", systemImage: "doc.text", description: Text(error.isEmpty ? "深研或值班简报会出现在这里。" : error))
            } else {
                List(items) { item in
                    Button {
                        Task { await open(item.reportId) }
                    } label: {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(item.title ?? item.reportId)
                                .font(.headline)
                                .foregroundStyle(.primary)
                            HStack {
                                if let type = item.reportType {
                                    Text(type).font(.caption2)
                                }
                                if let symbol = item.symbol, !symbol.isEmpty {
                                    Text(symbol).font(.caption2)
                                }
                                Spacer()
                                if let at = item.generatedAt {
                                    Text(at).font(.caption2)
                                }
                            }
                            .foregroundStyle(.secondary)
                            if let conclusion = item.conclusion, !conclusion.isEmpty {
                                Text(conclusion)
                                    .font(.footnote)
                                    .foregroundStyle(.secondary)
                                    .lineLimit(2)
                            }
                        }
                    }
                }
            }
        }
        .navigationTitle("研究报告")
        .navigationBarTitleDisplayMode(.inline)
        .task {
            await load()
            if let rid = initialReportId, !rid.isEmpty {
                await open(rid)
            }
        }
        .refreshable { await load() }
        .sheet(item: $selected) { report in
            NavigationStack {
                ScrollView {
                    MarkdownText(
                        source: report.content ?? report.conclusion ?? "暂无正文",
                        richBlocks: true
                    )
                    .padding()
                }
                .navigationTitle(report.title ?? "报告")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button("完成") { selected = nil }
                    }
                }
            }
        }
    }

    private func load() async {
        loading = true
        defer { loading = false }
        do {
            items = try await APIClient.shared.fetchReports().items
            error = ""
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }

    private func open(_ reportId: String) async {
        do {
            selected = try await APIClient.shared.fetchReport(reportId: reportId)
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }
}

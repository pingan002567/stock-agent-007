import SwiftUI

struct MonitorView: View {
    @State private var items: [MonitorEvent] = []
    @State private var status: MonitorStatus?
    @State private var rules: [MonitorRule] = []
    @State private var page = 1
    @State private var totalPages = 1
    @State private var error = ""
    @State private var loading = true
    @State private var loadingMore = false
    @State private var evaluating = false
    @State private var showRules = false
    @State private var selected: MonitorEvent?

    var body: some View {
        NavigationStack {
            Group {
                if loading {
                    ProgressView("加载盯盘…")
                } else if !error.isEmpty && items.isEmpty {
                    ContentUnavailableView("加载失败", systemImage: "exclamationmark.triangle", description: Text(error))
                } else if items.isEmpty {
                    ContentUnavailableView("暂无事件", systemImage: "bell", description: Text("盯盘规则触发后会显示在这里。"))
                } else {
                    List {
                        if let status {
                            Section {
                                Toggle(
                                    "盯盘运行中",
                                    isOn: Binding(
                                        get: { status.isRunning },
                                        set: { enabled in
                                            Task { await setRunning(enabled) }
                                        }
                                    )
                                )
                                if let last = status.lastCheckedAt {
                                    Text("上次检查 \(last)")
                                        .font(.caption2)
                                        .foregroundStyle(.secondary)
                                }
                                if let err = status.lastError, !err.isEmpty {
                                    Text(err)
                                        .font(.caption2)
                                        .foregroundStyle(.orange)
                                }
                            }
                        }
                        Section("事件") {
                            ForEach(items) { event in
                                Button {
                                    selected = event
                                } label: {
                                    VStack(alignment: .leading, spacing: 6) {
                                        HStack {
                                            Text(event.title ?? event.symbol ?? "事件")
                                                .font(.headline)
                                                .foregroundStyle(.primary)
                                            Spacer()
                                            if let severity = event.severity {
                                                Text(severity.uppercased())
                                                    .font(.caption2.bold())
                                                    .padding(.horizontal, 6)
                                                    .padding(.vertical, 2)
                                                    .background(severityColor(severity).opacity(0.15))
                                                    .foregroundStyle(severityColor(severity))
                                                    .clipShape(Capsule())
                                            }
                                        }
                                        if let message = event.message, !message.isEmpty {
                                            Text(message).font(.subheadline).foregroundStyle(.secondary).lineLimit(2)
                                        } else if let rule = event.triggerRule, !rule.isEmpty {
                                            Text(rule).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                                        }
                                        HStack {
                                            if let symbol = event.symbol, !symbol.isEmpty {
                                                Text(symbol).font(.caption2).foregroundStyle(.tertiary)
                                            }
                                            if let triggered = event.triggeredAt {
                                                Text(triggered).font(.caption2).foregroundStyle(.tertiary)
                                            }
                                        }
                                    }
                                    .padding(.vertical, 2)
                                }
                            }
                            if page < totalPages {
                                Button {
                                    Task { await loadMore() }
                                } label: {
                                    if loadingMore {
                                        ProgressView()
                                    } else {
                                        Text("加载更多")
                                    }
                                }
                            }
                        }
                    }
                }
            }
            .navigationTitle("盯盘")
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        Task { await evaluateOnce() }
                    } label: {
                        if evaluating {
                            ProgressView()
                        } else {
                            Image(systemName: "arrow.triangle.2.circlepath")
                        }
                    }
                    .accessibilityLabel("立即评估")
                    .disabled(evaluating)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("规则") { showRules = true }
                }
            }
            .sheet(isPresented: $showRules) {
                MonitorRulesSheet(rules: $rules)
            }
            .navigationDestination(item: $selected) { event in
                MonitorEventDetailView(event: event)
            }
            .refreshable { await reload() }
            .task { await reload() }
            .overlay(alignment: .top) {
                if !error.isEmpty, !items.isEmpty {
                    Text(error)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .padding(8)
                        .frame(maxWidth: .infinity)
                        .background(.ultraThinMaterial)
                }
            }
        }
    }

    private func severityColor(_ s: String) -> Color {
        switch s.lowercased() {
        case "high", "critical": return .red
        case "medium", "warn", "warning": return .orange
        default: return .blue
        }
    }

    private func reload() async {
        loading = items.isEmpty
        error = ""
        page = 1
        do {
            async let eventsTask = APIClient.shared.fetchMonitorEvents(page: 1, pageSize: 30)
            async let statusTask = APIClient.shared.fetchMonitorStatus()
            async let rulesTask = APIClient.shared.fetchMonitorRules()
            let events = try await eventsTask
            items = events.items
            totalPages = max(events.totalPages ?? 1, 1)
            status = try? await statusTask
            rules = (try? await rulesTask) ?? []
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
        loading = false
    }

    private func loadMore() async {
        guard !loadingMore, page < totalPages else { return }
        loadingMore = true
        defer { loadingMore = false }
        do {
            let next = page + 1
            let events = try await APIClient.shared.fetchMonitorEvents(page: next, pageSize: 30)
            items.append(contentsOf: events.items)
            page = next
            totalPages = max(events.totalPages ?? totalPages, totalPages)
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }

    private func setRunning(_ enabled: Bool) async {
        do {
            status = enabled
                ? try await APIClient.shared.startMonitor()
                : try await APIClient.shared.pauseMonitor()
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }

    private func evaluateOnce() async {
        evaluating = true
        defer { evaluating = false }
        do {
            _ = try await APIClient.shared.evaluateMonitorOnce(force: false)
            await reload()
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }
}

struct MonitorRulesSheet: View {
    @Binding var rules: [MonitorRule]
    @Environment(\.dismiss) private var dismiss
    @State private var error = ""
    @State private var showAdd = false
    @State private var busyId: String?

    var body: some View {
        NavigationStack {
            List {
                if rules.isEmpty {
                    Text("暂无规则").foregroundStyle(.secondary)
                } else {
                    ForEach(rules) { rule in
                        VStack(alignment: .leading, spacing: 8) {
                            HStack {
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(rule.displayName).font(.headline)
                                    Text(ruleMeta(rule))
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                                Spacer()
                                Toggle(
                                    "",
                                    isOn: Binding(
                                        get: { rule.enabled ?? true },
                                        set: { enabled in
                                            Task { await setEnabled(rule, enabled: enabled) }
                                        }
                                    )
                                )
                                .labelsHidden()
                                .disabled(busyId == rule.id)
                            }
                            if let trigger = rule.triggerRule, !trigger.isEmpty {
                                Text(trigger)
                                    .font(.caption2.monospaced())
                                    .foregroundStyle(.tertiary)
                            }
                        }
                        .swipeActions {
                            Button(role: .destructive) {
                                Task { await delete(rule) }
                            } label: {
                                Text("删除")
                            }
                        }
                    }
                }
            }
            .navigationTitle("盯盘规则")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("关闭") { dismiss() }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        showAdd = true
                    } label: {
                        Image(systemName: "plus")
                    }
                }
            }
            .sheet(isPresented: $showAdd) {
                AddMonitorRuleSheet { created in
                    rules.insert(created, at: 0)
                }
            }
            .overlay(alignment: .bottom) {
                if !error.isEmpty {
                    Text(error)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .padding()
                }
            }
        }
        .presentationDetents([.medium, .large])
    }

    private func ruleMeta(_ rule: MonitorRule) -> String {
        var parts: [String] = []
        parts.append(rule.ruleType ?? "—")
        if let symbol = rule.symbol, !symbol.isEmpty { parts.append(symbol) }
        if let threshold = rule.threshold {
            parts.append(String(format: "阈值 %.1f", threshold))
        }
        parts.append(rule.severity ?? "medium")
        return parts.joined(separator: " · ")
    }

    private func setEnabled(_ rule: MonitorRule, enabled: Bool) async {
        guard let ruleId = rule.ruleId else { return }
        busyId = rule.id
        defer { busyId = nil }
        do {
            let updated = try await APIClient.shared.upsertMonitorRule(rule.upsertBody(enabledOverride: enabled))
            if let idx = rules.firstIndex(where: { $0.ruleId == ruleId }) {
                rules[idx] = updated
            }
            error = ""
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }

    private func delete(_ rule: MonitorRule) async {
        guard let ruleId = rule.ruleId else { return }
        do {
            try await APIClient.shared.deleteMonitorRule(id: ruleId)
            rules.removeAll { $0.ruleId == ruleId }
            error = ""
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }
}

struct AddMonitorRuleSheet: View {
    var onCreated: (MonitorRule) -> Void
    @Environment(\.dismiss) private var dismiss

    @State private var title = "涨跌幅提醒"
    @State private var symbol = ""
    @State private var threshold = 5.0
    @State private var severity = "medium"
    @State private var busy = false
    @State private var error = ""

    private let severities = ["low", "medium", "high"]

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("标题", text: $title)
                    TextField("标的（可空=全市场）", text: $symbol)
                        .textInputAutocapitalization(.characters)
                        .autocorrectionDisabled()
                    HStack {
                        Text("阈值 %")
                        Spacer()
                        TextField("5", value: $threshold, format: .number)
                            .keyboardType(.decimalPad)
                            .multilineTextAlignment(.trailing)
                            .frame(width: 80)
                    }
                    Picker("级别", selection: $severity) {
                        ForEach(severities, id: \.self) { Text($0).tag($0) }
                    }
                } footer: {
                    Text("将创建 price_change_pct_gt 规则：绝对涨跌幅超过阈值时触发。")
                }
                if !error.isEmpty {
                    Section {
                        Text(error).foregroundStyle(.red).font(.footnote)
                    }
                }
            }
            .navigationTitle("新建规则")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("创建") {
                        Task { await create() }
                    }
                    .disabled(busy || title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
        }
    }

    private func create() async {
        busy = true
        defer { busy = false }
        let body = MonitorRule.newPriceMove(
            title: title.trimmingCharacters(in: .whitespacesAndNewlines),
            symbol: symbol.trimmingCharacters(in: .whitespacesAndNewlines),
            threshold: threshold,
            severity: severity
        )
        do {
            let created = try await APIClient.shared.upsertMonitorRule(body)
            onCreated(created)
            dismiss()
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }
}

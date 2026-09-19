import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var auth: AuthStore
    @EnvironmentObject private var api: APIClient
    @EnvironmentObject private var chat: ChatViewModel
    @ObservedObject private var push = PushNotificationManager.shared

    @State private var settings: WorkbenchSettings?
    @State private var probing = false
    @State private var loading = false
    @State private var probeMessage = ""
    @State private var loadError = ""
    @State private var dutyCompletionPush = true
    @State private var savingNotificationPrefs = false

    var body: some View {
        NavigationStack {
            List {
                if isDegraded {
                    degradedBanner
                }
                connectionSection
                backendSection
                marketSection
                featuresSection
                pushSection
                tradingSection
                disconnectSection
                aboutSection
            }
            .navigationTitle("设置")
            .refreshable { await reload() }
            .task { await reload() }
        }
    }

    // MARK: - Sections

    private var degradedBanner: some View {
        Section {
            Label(degradedFooter, systemImage: "exclamationmark.triangle.fill")
                .font(.footnote)
                .foregroundStyle(.orange)
        }
    }

    private var connectionSection: some View {
        Section("当前连接") {
            LabeledContent("地址", value: displayHost)
            LabeledContent("完整 URL") {
                Text(auth.remoteURL.isEmpty ? "—" : auth.remoteURL)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
            }
            LabeledContent("令牌", value: auth.accessToken.isEmpty ? "未设置" : "已保存（Keychain）")
            Button {
                Task { await reprobe() }
            } label: {
                if probing {
                    ProgressView()
                } else {
                    Text("重新探测健康")
                }
            }
            .disabled(probing)
            if !probeMessage.isEmpty {
                Text(probeMessage)
                    .font(.caption)
                    .foregroundStyle(probeMessage.contains("通过") ? Color.secondary : Color.red)
            }
        }
    }

    private var backendSection: some View {
        Section {
            NavigationLink {
                RuntimeSettingsView(initial: settings)
            } label: {
                VStack(alignment: .leading, spacing: 4) {
                    Text("运行状态")
                    Text(runtimeSubtitle)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            NavigationLink {
                LlmModelSettingsView(initial: settings?.llmProviders)
            } label: {
                VStack(alignment: .leading, spacing: 4) {
                    Text("模型服务")
                    Text(settings?.llmProviders?.defaultModel ?? settings?.runtimeConfig?.defaultModel ?? "未连接")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
            NavigationLink {
                SkillsSettingsView(initialSkills: settings?.skills ?? [])
            } label: {
                HStack {
                    Text("AI 技能")
                    Spacer()
                    Text(skillsCountLabel)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            NavigationLink {
                CostSettingsView()
            } label: {
                Text("用量与费用")
            }
        } header: {
            Text("后端与模型")
        }
    }

    private var marketSection: some View {
        Section {
            NavigationLink {
                MarketRefreshSettingsView(initial: settings?.marketRefresh)
            } label: {
                VStack(alignment: .leading, spacing: 4) {
                    Text("刷新频率")
                    Text(refreshSubtitle)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            NavigationLink {
                DataSourcesSettingsView(
                    initialSources: settings?.dataSources,
                    initialAvailable: settings?.availableDataProviders ?? [],
                    initialSchema: settings?.providerCredentialSchema ?? [:]
                )
            } label: {
                VStack(alignment: .leading, spacing: 4) {
                    Text("行情数据源")
                    Text(dataSourceSubtitle)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        } header: {
            Text("行情")
        }
    }

    private var featuresSection: some View {
        Section("功能") {
            NavigationLink {
                InvestorProfileSettingsView(initial: settings?.investorProfile)
            } label: {
                VStack(alignment: .leading, spacing: 4) {
                    Text("投资画像")
                    Text(investorSubtitle)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            NavigationLink("外观与主题") {
                ChatAppearanceSettingsView()
            }
            NavigationLink("策略回测") {
                StrategyListView()
            }
            NavigationLink("研究报告") {
                ReportsListView()
            }
        }
    }

    private var pushSection: some View {
        Section {
            Button("请求推送授权并注册") {
                push.requestAuthorizationAndRegister()
                Task {
                    // Wait briefly for token callback.
                    try? await Task.sleep(nanoseconds: 800_000_000)
                    if let token = push.deviceTokenHex {
                        #if DEBUG
                        let env = "sandbox"
                        #else
                        let env = "production"
                        #endif
                        try? await api.registerAPNsDevice(token: token, environment: env)
                    }
                }
            }
            LabeledContent("推送授权", value: pushAuthLabel)
            LabeledContent(
                "Device Token",
                value: push.deviceTokenHex.map { String($0.prefix(16)) + "…" } ?? "未注册"
            )
            Toggle(
                "定时任务完成通知",
                isOn: Binding(
                    get: { dutyCompletionPush },
                    set: { newValue in
                        dutyCompletionPush = newValue
                        Task { await saveDutyCompletionPush(newValue) }
                    }
                )
            )
            .disabled(savingNotificationPrefs)
        } header: {
            Text("通知")
        } footer: {
            Text("完成通知默认开启；失败始终推送。需付费 Apple 开发者账号开通 Push，并配置服务端 APNS_* 后真机才能收到远程推送。")
        }
    }

    private var tradingSection: some View {
        Section {
            LabeledContent(
                "纸上交易",
                value: settings?.tradingControls?.paperTrading ?? "sandbox_only"
            )
            LabeledContent(
                "实盘下单",
                value: settings?.tradingControls?.realOrder ?? "blocked"
            )
        } header: {
            Text("交易约束")
        } footer: {
            Text("本客户端不下单。结论仅供研究参考。")
        }
    }

    private var disconnectSection: some View {
        Section {
            Button("切换后端", role: .destructive) {
                chat.stop()
                api.clear()
                auth.disconnect()
            }
        } footer: {
            Text("返回连接页。已保存的地址和令牌会留在输入框，但仍需再点一次连接。")
        }
    }

    private var aboutSection: some View {
        Section("关于") {
            LabeledContent("客户端", value: "Stock Agent 原生 iOS")
            LabeledContent("版本", value: appVersion)
            LabeledContent("Bundle ID", value: Bundle.main.bundleIdentifier ?? "com.stockagent.app")
            if !loadError.isEmpty {
                Text(loadError)
                    .font(.caption)
                    .foregroundStyle(.red)
            }
            if loading {
                ProgressView("同步设置…")
            }
        }
    }

    // MARK: - Labels

    private var isDegraded: Bool {
        settings?.agentRuntime?.degraded == true
            || settings?.dataProvider?.degraded == true
            || api.lastDegraded == true
    }

    private var displayHost: String {
        let raw = auth.remoteURL
        guard let url = URL(string: raw), let host = url.host else { return raw.isEmpty ? "—" : raw }
        if let port = url.port {
            return "\(host):\(port)"
        }
        return host
    }

    private var runtimeSubtitle: String {
        let client = settings?.agentRuntime?.activeClient ?? api.lastActiveClient ?? "—"
        let model = settings?.agentRuntime?.modelName ?? api.lastModelName ?? settings?.runtimeConfig?.modelName
        if let model, !model.isEmpty {
            return "\(client) · \(model)"
        }
        return client
    }

    private var refreshSubtitle: String {
        guard let cfg = settings?.marketRefresh else { return "—" }
        return "页面 \(cfg.pageRefreshSeconds)s · 预热 \(cfg.warmupSeconds)s"
    }

    private var dataSourceSubtitle: String {
        let available = settings?.availableDataProviders ?? []
        guard !available.isEmpty else {
            return settings?.dataProvider?.activeProvider ?? "—"
        }
        let sources = settings?.dataSources
        let on = available.filter {
            sources?.isEnabled(providerId: $0.id, fallback: $0.defaultEnabled) ?? $0.defaultEnabled
        }.count
        return "\(on)/\(available.count) 启用"
    }

    private var investorSubtitle: String {
        let profile = settings?.investorProfile ?? .default
        let notes = profile.notes.trimmingCharacters(in: .whitespacesAndNewlines)
        if notes.isEmpty { return profile.riskLabel }
        return "\(profile.riskLabel) · 已填自述"
    }

    private var skillsCountLabel: String {
        let skills = settings?.skills ?? []
        guard !skills.isEmpty else { return "—" }
        let on = skills.filter { $0.enabled == true }.count
        return "\(on)/\(skills.count) 启用"
    }

    private var degradedFooter: String {
        let reason = settings?.agentRuntime?.degradedReason
            ?? settings?.dataProvider?.degradedReason
            ?? "部分能力已降级"
        return "降级：\(reason)"
    }

    private var pushAuthLabel: String {
        switch push.authorizationStatus {
        case .authorized: return "已授权"
        case .denied: return "已拒绝"
        case .provisional: return "临时授权"
        case .ephemeral: return "短暂授权"
        case .notDetermined: return "未请求"
        @unknown default: return "未知"
        }
    }

    private var appVersion: String {
        let v = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "—"
        let b = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? ""
        return b.isEmpty ? v : "\(v) (\(b))"
    }

    // MARK: - Actions

    private func reload() async {
        loading = true
        loadError = ""
        defer { loading = false }
        do {
            settings = try await api.fetchSettings()
            dutyCompletionPush = settings?.notificationPrefs?.dutyCompletionPush ?? true
            _ = try? await api.probeHealth()
        } catch {
            loadError = (error as? APIError)?.message ?? error.localizedDescription
        }
    }

    private func saveDutyCompletionPush(_ enabled: Bool) async {
        savingNotificationPrefs = true
        defer { savingNotificationPrefs = false }
        do {
            let saved = try await api.updateNotificationPrefs(
                NotificationPrefs(dutyCompletionPush: enabled)
            )
            dutyCompletionPush = saved.dutyCompletionPush
        } catch {
            // Revert UI on failure.
            dutyCompletionPush = settings?.notificationPrefs?.dutyCompletionPush ?? true
            loadError = (error as? APIError)?.message ?? error.localizedDescription
        }
    }

    private func reprobe() async {
        probing = true
        defer { probing = false }
        do {
            let health = try await api.probeHealth()
            let client = health.agentRuntime?.activeClient ?? "?"
            let model = health.agentRuntime?.modelName.map { " · \($0)" } ?? ""
            probeMessage = "健康检查通过（\(client)\(model)）"
            settings = try? await api.fetchSettings()
            dutyCompletionPush = settings?.notificationPrefs?.dutyCompletionPush ?? true
        } catch {
            probeMessage = (error as? APIError)?.message ?? error.localizedDescription
        }
    }
}

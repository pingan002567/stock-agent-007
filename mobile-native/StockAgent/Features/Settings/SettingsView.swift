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

    var body: some View {
        NavigationStack {
            List {
                connectionSection
                runtimeSection
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

    private var runtimeSection: some View {
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
            Text("后端能力")
        } footer: {
            if settings?.agentRuntime?.degraded == true
                || settings?.dataProvider?.degraded == true
                || api.lastDegraded == true {
                Text(degradedFooter)
                    .foregroundStyle(.orange)
            }
        }
    }

    private var featuresSection: some View {
        Section("功能") {
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
        } header: {
            Text("通知")
        } footer: {
            Text("需在 Apple Developer 为 Bundle ID 开通 Push，并在 entitlements 加回 aps-environment 后才能真机收到远程推送。")
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
            if let runtime = settings?.agentRuntime {
                // Keep APIClient cache in sync for other screens.
                _ = runtime
            }
            // Soft health refresh without blocking UI on failure.
            _ = try? await api.probeHealth()
        } catch {
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
        } catch {
            probeMessage = (error as? APIError)?.message ?? error.localizedDescription
        }
    }
}

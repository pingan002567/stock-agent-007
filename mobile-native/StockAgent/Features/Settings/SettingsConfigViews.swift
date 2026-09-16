import SwiftUI

// MARK: - Market refresh

struct MarketRefreshSettingsView: View {
    var initial: MarketRefreshConfig?

    @State private var config: MarketRefreshConfig = .standard
    @State private var saving = false
    @State private var message = ""
    @State private var error = ""

    var body: some View {
        List {
            Section {
                presetRow
            } header: {
                Text("预设")
            } footer: {
                Text("页面刷新只打本机接口；行情预热会打上游全市场快照；同股补拉冷却限制手动与 AI 的 refresh。")
            }

            Section("自定义（秒）") {
                stepperRow(
                    title: "页面刷新",
                    value: $config.pageRefreshSeconds,
                    range: 30...600,
                    hint: "30–600"
                )
                stepperRow(
                    title: "行情预热",
                    value: $config.warmupSeconds,
                    range: 120...3600,
                    hint: "120–3600"
                )
                stepperRow(
                    title: "同股补拉冷却",
                    value: $config.manualCooldownSeconds,
                    range: 30...1800,
                    hint: "30–1800"
                )
            }

            Section {
                Button {
                    Task { await save() }
                } label: {
                    if saving {
                        ProgressView()
                    } else {
                        Text("保存刷新频率")
                    }
                }
                .disabled(saving)
            }

            if !message.isEmpty {
                Section {
                    Text(message).font(.caption).foregroundStyle(.secondary)
                }
            }
            if !error.isEmpty {
                Section {
                    Text(error).font(.caption).foregroundStyle(.red)
                }
            }
        }
        .navigationTitle("刷新频率")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            if let initial { config = initial }
        }
        .task {
            if let fresh = try? await APIClient.shared.fetchSettings().marketRefresh {
                config = fresh
            }
        }
    }

    private var presetRow: some View {
        HStack(spacing: 8) {
            ForEach(MarketRefreshPreset.all) { preset in
                Button(preset.label) {
                    config = preset.config
                    message = ""
                }
                .buttonStyle(.bordered)
                .tint(matches(preset.config) ? Color.accentColor : Color.secondary)
            }
            Spacer(minLength: 0)
        }
        .padding(.vertical, 4)
    }

    private func stepperRow(
        title: String,
        value: Binding<Int>,
        range: ClosedRange<Int>,
        hint: String
    ) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(title)
                Spacer()
                Text("\(value.wrappedValue)s")
                    .font(.body.monospacedDigit())
                    .foregroundStyle(.secondary)
            }
            Stepper(value: value, in: range, step: title.contains("预热") ? 30 : 10) {
                Text(hint).font(.caption2).foregroundStyle(.tertiary)
            }
        }
    }

    private func matches(_ other: MarketRefreshConfig) -> Bool {
        config.pageRefreshSeconds == other.pageRefreshSeconds
            && config.warmupSeconds == other.warmupSeconds
            && config.manualCooldownSeconds == other.manualCooldownSeconds
    }

    private func save() async {
        saving = true
        defer { saving = false }
        do {
            config = try await APIClient.shared.updateMarketRefresh(config)
            message = "已保存"
            error = ""
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
            message = ""
        }
    }
}

// MARK: - Data sources

struct DataSourcesSettingsView: View {
    var initialSources: DataSourcesConfig?
    var initialAvailable: [AvailableDataProvider]
    var initialSchema: [String: [ProviderCredentialField]]

    @State private var sources: DataSourcesConfig = DataSourcesConfig()
    @State private var available: [AvailableDataProvider] = []
    @State private var schema: [String: [ProviderCredentialField]] = [:]
    @State private var busyId: String?
    @State private var savingCreds = false
    @State private var message = ""
    @State private var error = ""
    @State private var draftCreds: [String: [String: String]] = [:]

    var body: some View {
        List {
            if !marketBindings.isEmpty {
                Section("市场主源") {
                    ForEach(marketBindings, id: \.market) { row in
                        LabeledContent(row.label, value: row.provider)
                    }
                }
            }

            Section {
                ForEach(available) { provider in
                    providerRow(provider)
                }
            } header: {
                Text("数据源")
            } footer: {
                Text("免费源只需开关。付费源需填写凭证后保存；凭证写入服务端档案，不会明文回显到其它设备日志。")
            }

            if needsCredentialSave {
                Section {
                    Button {
                        Task { await saveCredentials() }
                    } label: {
                        if savingCreds {
                            ProgressView()
                        } else {
                            Text("保存 API 凭证")
                        }
                    }
                    .disabled(savingCreds)
                }
            }

            if !message.isEmpty {
                Section { Text(message).font(.caption).foregroundStyle(.secondary) }
            }
            if !error.isEmpty {
                Section { Text(error).font(.footnote).foregroundStyle(.red) }
            }
        }
        .navigationTitle("行情数据源")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            if sources.providers == nil { sources = initialSources ?? DataSourcesConfig() }
            if available.isEmpty { available = initialAvailable }
            if schema.isEmpty { schema = initialSchema }
            syncDraftFromSources()
        }
        .task { await reload() }
        .refreshable { await reload() }
    }

    private var needsCredentialSave: Bool {
        available.contains { provider in
            let fields = schema[provider.id] ?? []
            guard !fields.isEmpty else { return false }
            return fields.contains { field in
                draftValue(provider.id, field.key) != sources.credential(provider.id, key: field.key)
            }
        }
    }

    @ViewBuilder
    private func providerRow(_ provider: AvailableDataProvider) -> some View {
        let fields = schema[provider.id] ?? []
        let enabled = sources.isEnabled(providerId: provider.id, fallback: provider.defaultEnabled)
        let credsReady = provider.free == true || sources.credentialsComplete(providerId: provider.id, fields: fields)

        VStack(alignment: .leading, spacing: 10) {
            Toggle(isOn: binding(for: provider)) {
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 6) {
                        Text(provider.displayName)
                        if provider.free == true {
                            tag("免费", tint: Color.accentColor)
                        } else {
                            tag("需 API", tint: .orange)
                        }
                        if enabled && !credsReady {
                            tag("待配置", tint: .orange)
                        }
                    }
                    if let markets = provider.markets, !markets.isEmpty {
                        Text(markets.joined(separator: " · "))
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                    }
                    if let desc = provider.description, !desc.isEmpty {
                        Text(desc)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(3)
                    }
                }
            }
            .disabled(busyId == provider.id)

            if !fields.isEmpty {
                ForEach(fields) { field in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(field.displayLabel)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        if field.secret == false {
                            TextField(field.env ?? field.key, text: draftBinding(provider.id, field.key))
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                                .font(.body.monospaced())
                        } else {
                            SecureField(field.env ?? field.key, text: draftBinding(provider.id, field.key))
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                                .font(.body.monospaced())
                        }
                    }
                }
            }
        }
        .padding(.vertical, 4)
    }

    private func tag(_ text: String, tint: Color) -> some View {
        Text(text)
            .font(.caption2)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(tint.opacity(0.12))
            .foregroundStyle(tint)
            .clipShape(Capsule())
    }

    private struct MarketRow {
        let market: String
        let label: String
        let provider: String
    }

    private var marketBindings: [MarketRow] {
        let order = ["CN", "HK", "US"]
        let providers = sources.providers ?? [:]
        return order.compactMap { key in
            guard let binding = providers[key] else { return nil }
            return MarketRow(
                market: key,
                label: binding.label ?? key,
                provider: binding.provider ?? "—"
            )
        }
    }

    private func binding(for provider: AvailableDataProvider) -> Binding<Bool> {
        Binding(
            get: { sources.isEnabled(providerId: provider.id, fallback: provider.defaultEnabled) },
            set: { newValue in
                Task { await setEnabled(provider, enabled: newValue) }
            }
        )
    }

    private func draftBinding(_ providerId: String, _ key: String) -> Binding<String> {
        Binding(
            get: { draftValue(providerId, key) },
            set: { newValue in
                var entry = draftCreds[providerId] ?? [:]
                entry[key] = newValue
                draftCreds[providerId] = entry
            }
        )
    }

    private func draftValue(_ providerId: String, _ key: String) -> String {
        draftCreds[providerId]?[key] ?? sources.credential(providerId, key: key)
    }

    private func syncDraftFromSources() {
        var next: [String: [String: String]] = [:]
        for (providerId, fields) in schema {
            var entry: [String: String] = [:]
            for field in fields {
                entry[field.key] = sources.credential(providerId, key: field.key)
            }
            next[providerId] = entry
        }
        draftCreds = next
    }

    private func reload() async {
        do {
            let settings = try await APIClient.shared.fetchSettings()
            sources = settings.dataSources ?? DataSourcesConfig()
            available = settings.availableDataProviders ?? []
            schema = settings.providerCredentialSchema ?? [:]
            syncDraftFromSources()
            error = ""
        } catch {
            if available.isEmpty {
                self.error = (error as? APIError)?.message ?? error.localizedDescription
            }
        }
    }

    private func setEnabled(_ provider: AvailableDataProvider, enabled: Bool) async {
        busyId = provider.id
        defer { busyId = nil }
        var next = sources
        next.setEnabled(providerId: provider.id, enabled: enabled)
        sources = next
        do {
            sources = try await APIClient.shared.updateDataSources(next)
            error = ""
            message = ""
        } catch {
            var reverted = sources
            reverted.setEnabled(providerId: provider.id, enabled: !enabled)
            sources = reverted
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }

    private func saveCredentials() async {
        savingCreds = true
        defer { savingCreds = false }
        var next = sources
        for (providerId, fields) in draftCreds {
            for (key, value) in fields {
                next.setCredential(providerId: providerId, key: key, value: value)
            }
        }
        do {
            sources = try await APIClient.shared.updateDataSources(next)
            syncDraftFromSources()
            message = "凭证已保存"
            error = ""
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
            message = ""
        }
    }
}

// MARK: - LLM providers + default model

struct LlmModelSettingsView: View {
    var initial: LlmProvidersSnapshot?

    @State private var snapshot: LlmProvidersSnapshot?
    @State private var busy = false
    @State private var busyId: String?
    @State private var message = ""
    @State private var error = ""
    @State private var connectTarget: LlmProviderItem?
    @State private var disconnectTarget: LlmProviderItem?

    var body: some View {
        List {
            Section {
                LabeledContent("当前默认", value: snapshot?.defaultModel ?? initial?.defaultModel ?? "—")
            } footer: {
                Text("连接提供商后，在下方选择默认模型。Key 保存在服务端用户凭证中。")
            }

            Section("已连接") {
                let connected = snapshot?.connected ?? initial?.connected ?? []
                if connected.isEmpty {
                    Text("还没有连接任何提供商")
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(connected) { provider in
                        connectedProviderBlock(provider)
                    }
                }
            }

            if !availableToConnect.isEmpty {
                Section("可连接") {
                    ForEach(availableToConnect) { provider in
                        HStack(alignment: .top) {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(provider.displayName)
                                if let note = provider.note, !note.isEmpty {
                                    Text(note).font(.caption).foregroundStyle(.secondary)
                                }
                                if let base = provider.baseUrl, !base.isEmpty {
                                    Text(base).font(.caption2).foregroundStyle(.tertiary)
                                }
                            }
                            Spacer()
                            Button("连接") { connectTarget = provider }
                                .buttonStyle(.borderedProminent)
                                .disabled(busy)
                        }
                        .padding(.vertical, 2)
                    }
                }
            }

            if !message.isEmpty {
                Section { Text(message).font(.caption).foregroundStyle(.secondary) }
            }
            if !error.isEmpty {
                Section { Text(error).font(.caption).foregroundStyle(.red) }
            }
        }
        .navigationTitle("模型服务")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            if snapshot == nil { snapshot = initial }
        }
        .task { await reload() }
        .refreshable { await reload() }
        .sheet(item: $connectTarget) { provider in
            LlmConnectSheet(provider: provider) { result in
                snapshot = result
                message = "已连接 \(provider.displayName)"
                error = ""
                connectTarget = nil
            }
        }
        .confirmationDialog(
            "断开「\(disconnectTarget?.displayName ?? "")」？",
            isPresented: Binding(
                get: { disconnectTarget != nil },
                set: { if !$0 { disconnectTarget = nil } }
            ),
            titleVisibility: .visible
        ) {
            Button("断开", role: .destructive) {
                if let target = disconnectTarget {
                    Task { await disconnect(target) }
                }
            }
            Button("取消", role: .cancel) { disconnectTarget = nil }
        } message: {
            Text("已保存的 API Key 会从服务端凭证中移除。")
        }
    }

    private var availableToConnect: [LlmProviderItem] {
        let connectedIds = Set((snapshot?.connected ?? []).map(\.id))
        let catalog = snapshot?.catalog ?? []
        if !catalog.isEmpty {
            return catalog.filter { ($0.connected != true) && !connectedIds.contains($0.id) && ($0.custom != true) }
        }
        return (snapshot?.popular ?? []).filter { !connectedIds.contains($0.id) }
    }

    @ViewBuilder
    private func connectedProviderBlock(_ provider: LlmProviderItem) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(provider.displayName).font(.headline)
                    if provider.hasKey == true {
                        Text("已保存 API Key").font(.caption2).foregroundStyle(.secondary)
                    }
                }
                Spacer()
                if provider.canDisconnect != false {
                    Button("断开", role: .destructive) {
                        disconnectTarget = provider
                    }
                    .disabled(busyId == provider.id)
                }
            }

            let models = provider.models ?? []
            if models.isEmpty {
                Text("无可用模型").font(.caption).foregroundStyle(.secondary)
            } else {
                ForEach(models) { model in
                    let ref = "\(provider.id)/\(model.id)"
                    Button {
                        Task { await select(ref) }
                    } label: {
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(model.displayName).foregroundStyle(.primary)
                                Text(ref).font(.caption2).foregroundStyle(.secondary)
                            }
                            Spacer()
                            if (snapshot?.defaultModel ?? initial?.defaultModel) == ref {
                                Image(systemName: "checkmark.circle.fill")
                                    .foregroundStyle(Color.accentColor)
                            }
                        }
                    }
                    .disabled(busy)
                }
            }
        }
        .padding(.vertical, 4)
    }

    private func reload() async {
        do {
            snapshot = try await APIClient.shared.fetchLlmProviders()
            error = ""
        } catch {
            if snapshot == nil {
                self.error = (error as? APIError)?.message ?? error.localizedDescription
            }
        }
    }

    private func select(_ ref: String) async {
        busy = true
        defer { busy = false }
        do {
            snapshot = try await APIClient.shared.setDefaultLlmModel(ref)
            message = "已切换为 \(ref)"
            error = ""
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
            message = ""
        }
    }

    private func disconnect(_ provider: LlmProviderItem) async {
        busyId = provider.id
        defer {
            busyId = nil
            disconnectTarget = nil
        }
        do {
            snapshot = try await APIClient.shared.disconnectLlmProvider(providerId: provider.id)
            message = "已断开 \(provider.displayName)"
            error = ""
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
            message = ""
        }
    }
}

private struct LlmConnectSheet: View {
    let provider: LlmProviderItem
    var onConnected: (LlmProvidersSnapshot) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var apiKey = ""
    @State private var busy = false
    @State private var error = ""

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    LabeledContent("提供商", value: provider.displayName)
                    if let base = provider.baseUrl, !base.isEmpty {
                        LabeledContent("Base URL", value: base)
                    }
                }

                if provider.needsKey {
                    Section {
                        SecureField("API Key", text: $apiKey)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .font(.body.monospaced())
                    } footer: {
                        Text(provider.note ?? "Key 仅保存在你的后端服务，不会写入 App 本地。")
                    }
                } else {
                    Section {
                        Text("该提供商无需 API Key，可直接连接。")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                }

                if !error.isEmpty {
                    Section {
                        Text(error).font(.footnote).foregroundStyle(.red)
                    }
                }
            }
            .navigationTitle("连接 \(provider.displayName)")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }.disabled(busy)
                }
                ToolbarItem(placement: .confirmationAction) {
                    if busy {
                        ProgressView()
                    } else {
                        Button("连接") { Task { await connect() } }
                            .disabled(provider.needsKey && apiKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }
                }
            }
        }
    }

    private func connect() async {
        busy = true
        defer { busy = false }
        do {
            let snap = try await APIClient.shared.connectLlmProvider(
                providerId: provider.id,
                apiKey: provider.needsKey ? apiKey : nil
            )
            onConnected(snap)
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }
}

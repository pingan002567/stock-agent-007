import SwiftUI

struct ConnectView: View {
    @EnvironmentObject private var auth: AuthStore
    @EnvironmentObject private var api: APIClient

    @State private var urlText = ""
    @State private var tokenText = ""
    @State private var busy = false
    @State private var error = ""
    @State private var copied = false

    private var quickURLs: [(label: String, url: String)] {
        var items: [(String, String)] = [
            ("推荐 443", RemoteDefaults.recommendedBaseURL),
            ("备用 8686", RemoteDefaults.alternateBaseURL),
        ]
        let last = auth.lastSuccessfulURL.trimmingCharacters(in: .whitespacesAndNewlines)
        if !last.isEmpty,
           last != RemoteDefaults.recommendedBaseURL,
           last != RemoteDefaults.alternateBaseURL {
            items.insert(("上次成功", last), at: 0)
        }
        return items
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text("填写 HTTPS 服务地址和访问令牌。只有点连接后，App 才会访问后端。")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }

                Section {
                    TextField(RemoteDefaults.recommendedBaseURL, text: $urlText)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)

                    SecureField("访问令牌（WORKBENCH_ACCESS_TOKEN）", text: $tokenText)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()

                    if !quickURLs.isEmpty {
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: 8) {
                                ForEach(quickURLs, id: \.url) { item in
                                    Button(item.label) {
                                        urlText = item.url
                                    }
                                    .buttonStyle(.bordered)
                                    .controlSize(.small)
                                }
                            }
                        }
                        .listRowInsets(EdgeInsets(top: 8, leading: 16, bottom: 8, trailing: 16))
                    }
                } header: {
                    Text("远端服务")
                } footer: {
                    Text("推荐 \(RemoteDefaults.recommendedBaseURL)（HTTPS 443）。若连不上可改用 \(RemoteDefaults.alternateBaseURL)。自签证书已在客户端放行。")
                }

                if !error.isEmpty {
                    Section {
                        Text(error)
                            .foregroundStyle(.red)
                            .font(.footnote)
                            .textSelection(.enabled)
                        Button {
                            ChatClipboard.copy(diagnosticsText)
                            copied = true
                            Task {
                                try? await Task.sleep(nanoseconds: 1_500_000_000)
                                copied = false
                            }
                        } label: {
                            Label(copied ? "已复制" : "复制诊断信息", systemImage: copied ? "checkmark" : "doc.on.doc")
                        }
                    } header: {
                        Text("连接失败")
                    }
                }

                Section {
                    Button {
                        Task { await connect() }
                    } label: {
                        HStack {
                            Spacer()
                            if busy {
                                ProgressView()
                            } else {
                                Text("连接").bold()
                            }
                            Spacer()
                        }
                    }
                    .disabled(busy || urlText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
            .navigationTitle("连接后端")
            .onAppear {
                if auth.remoteURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    urlText = RemoteDefaults.recommendedBaseURL
                } else {
                    urlText = auth.remoteURL
                }
                tokenText = auth.accessToken
            }
        }
    }

    private var diagnosticsText: String {
        """
        URL: \(urlText)
        上次成功: \(auth.lastSuccessfulURL.isEmpty ? "—" : auth.lastSuccessfulURL)
        错误: \(error)
        时间: \(ISO8601DateFormatter().string(from: Date()))
        """
    }

    private func connect() async {
        error = ""
        busy = true
        defer { busy = false }
        if let hint = APIClient.connectionHint(forURLString: urlText) {
            error = hint
            return
        }
        do {
            try api.configure(baseURLString: urlText, token: tokenText)
            _ = try await api.probeHealth()
            auth.saveDraft(url: urlText, token: tokenText)
            auth.recordSuccessfulURL(urlText)
            auth.markConnected()
            NetworkReachability.shared.clearAuthFailure()
        } catch {
            self.error = Self.mapConnectError(error, url: urlText)
        }
    }

    private static func mapConnectError(_ error: Error, url: String) -> String {
        let mapped = (error as? APIError)?.message ?? TransportErrorMapper.map(error).message
        if let hint = APIClient.connectionHint(forURLString: url),
           mapped.contains("超时") || mapped.contains("不可达") || mapped.contains("无法连上") {
            return "\(mapped)\n\(hint)"
        }
        return mapped
    }
}

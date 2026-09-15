import SwiftUI

struct ConnectView: View {
    @EnvironmentObject private var auth: AuthStore
    @EnvironmentObject private var api: APIClient

    @State private var urlText = ""
    @State private var tokenText = ""
    @State private var busy = false
    @State private var error = ""

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
                } header: {
                    Text("远端服务")
                } footer: {
                    Text("推荐 \(RemoteDefaults.recommendedBaseURL)（HTTPS 443）。若连不上可改用 https://IP:8686。自签证书已在客户端放行。")
                }

                if !error.isEmpty {
                    Section {
                        Text(error)
                            .foregroundStyle(.red)
                            .font(.footnote)
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
            auth.markConnected()
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

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
                    Text("填写你的服务地址和访问令牌。只有点连接后，App 才会访问后端。")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }

                Section("远端服务") {
                    TextField("https://你的后端地址", text: $urlText)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)

                    SecureField("访问令牌", text: $tokenText)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
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
                urlText = auth.remoteURL
                tokenText = auth.accessToken
            }
        }
    }

    private func connect() async {
        error = ""
        busy = true
        defer { busy = false }
        do {
            try api.configure(baseURLString: urlText, token: tokenText)
            _ = try await api.probeHealth()
            auth.saveDraft(url: urlText, token: tokenText)
            auth.markConnected()
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }
}

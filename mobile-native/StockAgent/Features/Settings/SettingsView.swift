import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var auth: AuthStore
    @EnvironmentObject private var api: APIClient
    @EnvironmentObject private var chat: ChatViewModel

    var body: some View {
        NavigationStack {
            List {
                Section("当前连接") {
                    LabeledContent("地址", value: displayHost)
                    LabeledContent("令牌", value: auth.accessToken.isEmpty ? "未设置" : "已保存")
                }

                Section {
                    Button("切换后端", role: .destructive) {
                        chat.stop()
                        api.clear()
                        auth.disconnect()
                    }
                } footer: {
                    Text("返回连接页。已保存的地址和令牌会留在输入框，但仍需再点一次连接。")
                }

                Section("关于") {
                    LabeledContent("客户端", value: "Stock Agent 原生 iOS")
                    LabeledContent("Bundle ID", value: "com.stockagent.app")
                }
            }
            .navigationTitle("设置")
        }
    }

    private var displayHost: String {
        let raw = auth.remoteURL
        guard let url = URL(string: raw), let host = url.host else { return raw.isEmpty ? "—" : raw }
        if let port = url.port {
            return "\(host):\(port)"
        }
        return host
    }
}

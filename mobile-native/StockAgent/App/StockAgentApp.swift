import SwiftUI

@main
struct StockAgentApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var auth = AuthStore.shared
    @StateObject private var api = APIClient.shared
    @StateObject private var chat = ChatViewModel()
    @StateObject private var tabs = TabRouter()
    @StateObject private var theme = AppThemeStore.shared

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(auth)
                .environmentObject(api)
                .environmentObject(chat)
                .environmentObject(tabs)
                .environmentObject(theme)
                .tint(theme.accentColor)
                .preferredColorScheme(theme.scheme.preferred)
                .onReceive(NotificationCenter.default.publisher(for: .stockAgentOpenMonitor)) { _ in
                    tabs.selected = .monitor
                }
                .onChange(of: auth.isConnected) { _, connected in
                    if connected {
                        PushNotificationManager.shared.requestAuthorizationAndRegister()
                        if let token = PushNotificationManager.shared.deviceTokenHex {
                            Task {
                                #if DEBUG
                                let env = "sandbox"
                                #else
                                let env = "production"
                                #endif
                                try? await api.registerAPNsDevice(token: token, environment: env)
                            }
                        }
                    }
                }
        }
    }
}

@MainActor
final class TabRouter: ObservableObject {
    enum Tab: Hashable {
        case chat, watchlist, holdings, monitor, settings
    }

    @Published var selected: Tab = .chat
}

struct RootView: View {
    @EnvironmentObject private var auth: AuthStore

    var body: some View {
        Group {
            if auth.isConnected {
                MainTabView()
            } else {
                ConnectView()
            }
        }
    }
}

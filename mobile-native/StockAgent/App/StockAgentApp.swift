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
                .onReceive(NotificationCenter.default.publisher(for: .stockAgentOpenMonitor)) { note in
                    let eventId = note.userInfo?["event_id"] as? String
                    let symbol = note.userInfo?["symbol"] as? String
                    tabs.openMonitor(eventId: eventId, symbol: symbol)
                    Task { await MonitorUnreadStore.shared.refreshFromServer() }
                }
                .onChange(of: auth.isConnected) { _, connected in
                    if connected {
                        PushNotificationManager.shared.requestAuthorizationAndRegister()
                        Task { await MonitorUnreadStore.shared.refreshFromServer() }
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
                    } else {
                        MonitorUnreadStore.shared.setUnreadCount(0)
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
    /// Deep-link target from APNs / local notification.
    @Published var pendingMonitorEventId: String?
    @Published var pendingMonitorSymbol: String?

    func openMonitor(eventId: String? = nil, symbol: String? = nil) {
        pendingMonitorEventId = eventId
        pendingMonitorSymbol = symbol
        selected = .monitor
    }

    var hasMonitorDeepLink: Bool {
        pendingMonitorEventId != nil || pendingMonitorSymbol != nil
    }

    func consumeMonitorDeepLink() -> (eventId: String?, symbol: String?) {
        defer {
            pendingMonitorEventId = nil
            pendingMonitorSymbol = nil
        }
        return (pendingMonitorEventId, pendingMonitorSymbol)
    }
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

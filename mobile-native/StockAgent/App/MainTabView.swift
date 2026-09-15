import SwiftUI

struct MainTabView: View {
    @State private var tab: Tab = .chat

    enum Tab: Hashable {
        case chat, watchlist, holdings, monitor, settings
    }

    var body: some View {
        TabView(selection: $tab) {
            ChatView()
                .tabItem { Label("对话", systemImage: "bubble.left.and.bubble.right") }
                .tag(Tab.chat)

            WatchlistView()
                .tabItem { Label("自选", systemImage: "star") }
                .tag(Tab.watchlist)

            HoldingsView()
                .tabItem { Label("持仓", systemImage: "chart.line.uptrend.xyaxis") }
                .tag(Tab.holdings)

            MonitorView()
                .tabItem { Label("盯盘", systemImage: "bell") }
                .tag(Tab.monitor)

            SettingsView()
                .tabItem { Label("设置", systemImage: "gearshape") }
                .tag(Tab.settings)
        }
    }
}

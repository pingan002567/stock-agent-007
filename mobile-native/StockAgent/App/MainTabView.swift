import SwiftUI

struct MainTabView: View {
    @EnvironmentObject private var tabs: TabRouter

    var body: some View {
        TabView(selection: $tabs.selected) {
            ChatView()
                .tabItem { Label("对话", systemImage: "bubble.left.and.bubble.right") }
                .tag(TabRouter.Tab.chat)

            WatchlistView()
                .tabItem { Label("自选", systemImage: "star") }
                .tag(TabRouter.Tab.watchlist)

            HoldingsView()
                .tabItem { Label("持仓", systemImage: "chart.line.uptrend.xyaxis") }
                .tag(TabRouter.Tab.holdings)

            MonitorView()
                .tabItem { Label("盯盘", systemImage: "bell") }
                .tag(TabRouter.Tab.monitor)

            SettingsView()
                .tabItem { Label("设置", systemImage: "gearshape") }
                .tag(TabRouter.Tab.settings)
        }
    }
}

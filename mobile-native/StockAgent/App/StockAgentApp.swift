import SwiftUI

@main
struct StockAgentApp: App {
    @StateObject private var auth = AuthStore.shared
    @StateObject private var api = APIClient.shared
    @StateObject private var chat = ChatViewModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(auth)
                .environmentObject(api)
                .environmentObject(chat)
        }
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

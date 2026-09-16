import Foundation
import Network

/// Global reachability + API auth failure signal for weak-net banner.
@MainActor
final class NetworkReachability: ObservableObject {
    static let shared = NetworkReachability()

    @Published private(set) var isOnline = true
    @Published var authFailureMessage: String?

    private let monitor = NWPathMonitor()
    private let queue = DispatchQueue(label: "stockagent.reachability")

    private init() {
        monitor.pathUpdateHandler = { [weak self] path in
            Task { @MainActor in
                self?.isOnline = path.status == .satisfied
            }
        }
        monitor.start(queue: queue)
    }

    var bannerText: String? {
        if !isOnline { return "网络不可用，请检查连接后重试" }
        if let authFailureMessage, !authFailureMessage.isEmpty { return authFailureMessage }
        return nil
    }

    func reportUnauthorized() {
        authFailureMessage = "登录已失效，请重新连接服务器"
    }

    func clearAuthFailure() {
        authFailureMessage = nil
    }
}

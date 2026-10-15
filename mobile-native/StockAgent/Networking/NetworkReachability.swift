import Foundation
import Network

/// Global reachability + API auth failure signal for weak-net banner.
@MainActor
final class NetworkReachability: ObservableObject {
    static let shared = NetworkReachability()

    @Published private(set) var isOnline = true
    @Published var authFailureMessage: String?
    /// Fires when path transitions from unsatisfied → satisfied.
    var onBecameOnline: (() -> Void)?

    private let monitor = NWPathMonitor()
    private let queue = DispatchQueue(label: "stockagent.reachability")

    private init() {
        monitor.pathUpdateHandler = { [weak self] path in
            Task { @MainActor in
                guard let self else { return }
                let online = path.status == .satisfied
                let wasOffline = !self.isOnline
                self.isOnline = online
                if wasOffline && online {
                    self.onBecameOnline?()
                }
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

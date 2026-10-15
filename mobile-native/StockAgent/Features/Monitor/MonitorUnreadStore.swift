import Foundation

/// Shared unread badge for the Monitor tab.
@MainActor
final class MonitorUnreadStore: ObservableObject {
    static let shared = MonitorUnreadStore()

    @Published private(set) var unreadCount: Int = 0

    private init() {}

    /// True when the tab should show a red indicator.
    var hasUnread: Bool { unreadCount > 0 }

    func setUnreadCount(_ count: Int) {
        let next = max(0, count)
        if unreadCount != next {
            unreadCount = next
        }
    }

    func refreshFromEventIds(_ eventIds: [String]) {
        setUnreadCount(MonitorSeenStore.unreadCount(in: eventIds))
    }

    /// Fetch latest page and recompute badge (works even when Monitor tab is not visible).
    func refreshFromServer() async {
        guard APIClient.shared.isConfigured else {
            setUnreadCount(0)
            return
        }
        do {
            let page = try await APIClient.shared.fetchMonitorEvents(page: 1, pageSize: 30)
            refreshFromEventIds(page.items.map(\.stableId))
        } catch {
            // Keep last known badge on transient failures.
        }
    }
}

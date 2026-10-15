import Foundation

/// Local read-state for monitor events (no backend unread API yet).
enum MonitorSeenStore {
    private static let key = "stockagent.monitor.seenEventIds"
    private static let maxIds = 500

    static func load() -> Set<String> {
        Set(UserDefaults.standard.stringArray(forKey: key) ?? [])
    }

    static func isUnread(_ eventId: String) -> Bool {
        !load().contains(eventId)
    }

    static func markSeen(_ eventId: String) {
        var ids = load()
        ids.insert(eventId)
        // Cap growth: keep arbitrary subset when over limit.
        if ids.count > maxIds {
            ids = Set(ids.prefix(maxIds))
        }
        UserDefaults.standard.set(Array(ids), forKey: key)
    }

    static func markAllSeen(_ eventIds: [String]) {
        var ids = load()
        for id in eventIds { ids.insert(id) }
        if ids.count > maxIds {
            ids = Set(ids.suffix(maxIds))
        }
        UserDefaults.standard.set(Array(ids), forKey: key)
    }

    static func unreadCount(in eventIds: [String]) -> Int {
        let seen = load()
        return eventIds.reduce(0) { $0 + (seen.contains($1) ? 0 : 1) }
    }
}

import Foundation

/// Owns turn-based history pagination cursors (separate from ChatViewModel UI state).
@MainActor
final class ChatHistoryPager {
    struct Cursor {
        var hasMore: Bool
        var nextBefore: String?
        var isLoadingOlder: Bool = false
    }

    let pageTurnLimit = 20
    /// Skip auto-prefetch on very short lists (avoids loop on first paint).
    let minRowsBeforePrefetch = 8
    /// Debounce between older-page fetches.
    let loadDebounceSeconds: TimeInterval = 1.0

    private var cursors: [String: Cursor] = [:]
    private var lastLoadAt: [String: Date] = [:]

    func remove(sessionId: String) {
        cursors.removeValue(forKey: sessionId)
        lastLoadAt.removeValue(forKey: sessionId)
    }

    func resetEmpty(sessionId: String) {
        cursors[sessionId] = Cursor(hasMore: false, nextBefore: nil)
    }

    func adoptPage(sessionId: String, hasMore: Bool, nextBefore: String?) {
        cursors[sessionId] = Cursor(hasMore: hasMore, nextBefore: nextBefore)
    }

    func preserveOlderCursor(sessionId: String, fallbackHasMore: Bool, fallbackBefore: String?) {
        if let prior = cursors[sessionId], prior.nextBefore != nil, prior.hasMore {
            cursors[sessionId] = Cursor(hasMore: true, nextBefore: prior.nextBefore)
        } else {
            cursors[sessionId] = Cursor(hasMore: fallbackHasMore, nextBefore: fallbackBefore)
        }
    }

    func cursor(for sessionId: String) -> Cursor {
        cursors[sessionId] ?? Cursor(hasMore: false, nextBefore: nil)
    }

    func setLoading(_ loading: Bool, sessionId: String) {
        var c = cursor(for: sessionId)
        c.isLoadingOlder = loading
        cursors[sessionId] = c
        if loading {
            lastLoadAt[sessionId] = Date()
        }
    }

    func updateAfterLoad(sessionId: String, hasMore: Bool, nextBefore: String?) {
        cursors[sessionId] = Cursor(hasMore: hasMore, nextBefore: nextBefore, isLoadingOlder: false)
    }

    /// Whether top-of-list appear should trigger an older-page fetch.
    func shouldAttemptLoad(sessionId: String, rowCount: Int, isStreaming: Bool) -> Bool {
        guard !isStreaming else { return false }
        guard rowCount >= minRowsBeforePrefetch else { return false }
        let c = cursor(for: sessionId)
        guard c.hasMore, !c.isLoadingOlder, c.nextBefore != nil else { return false }
        if let last = lastLoadAt[sessionId],
           Date().timeIntervalSince(last) < loadDebounceSeconds {
            return false
        }
        return true
    }
}

import Foundation

/// Accepts server trust for personal self-signed HTTPS backends.
/// Must implement task-level challenge — session-level alone is not enough for data/SSE tasks.
final class TrustingURLSessionDelegate: NSObject, URLSessionDelegate, URLSessionTaskDelegate {
    func urlSession(
        _ session: URLSession,
        didReceive challenge: URLAuthenticationChallenge,
        completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void
    ) {
        Self.resolve(challenge, completionHandler: completionHandler)
    }

    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        didReceive challenge: URLAuthenticationChallenge,
        completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void
    ) {
        Self.resolve(challenge, completionHandler: completionHandler)
    }

    private static func resolve(
        _ challenge: URLAuthenticationChallenge,
        completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void
    ) {
        if challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust,
           let trust = challenge.protectionSpace.serverTrust {
            completionHandler(.useCredential, URLCredential(trust: trust))
            return
        }
        completionHandler(.performDefaultHandling, nil)
    }
}

@MainActor
final class APIClient: ObservableObject {
    static let shared = APIClient()

    private let delegate = TrustingURLSessionDelegate()
    private lazy var session: URLSession = {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 60
        config.timeoutIntervalForResource = 600
        return URLSession(configuration: config, delegate: delegate, delegateQueue: nil)
    }()

    private var baseURL: URL?
    private var accessToken: String = ""

    func configure(baseURLString: String, token: String) throws {
        let normalized = try Self.normalizeRemoteURL(baseURLString)
        guard let url = URL(string: normalized) else {
            throw APIError(message: "地址无效")
        }
        baseURL = url
        accessToken = token.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    func clear() {
        baseURL = nil
        accessToken = ""
    }

    static func normalizeRemoteURL(_ raw: String) throws -> String {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { throw APIError(message: "请填写远端地址") }
        let withScheme = trimmed.contains("://") ? trimmed : "https://\(trimmed)"
        guard var components = URLComponents(string: withScheme) else {
            throw APIError(message: "地址格式不正确")
        }
        guard components.scheme == "http" || components.scheme == "https" else {
            throw APIError(message: "只支持 http 或 https 地址")
        }
        if components.path == "/" { components.path = "" }
        while components.path.hasSuffix("/") {
            components.path.removeLast()
        }
        guard let result = components.string else { throw APIError(message: "地址格式不正确") }
        return result
    }

    func probeHealth() async throws -> HealthResponse {
        let data = try await getData(path: "/api/health")
        let health = try JSONDecoder().decode(HealthResponse.self, from: data)
        guard health.status == "ok" else {
            throw APIError(message: "后端已响应，但健康状态不是 ok")
        }
        guard health.agentRuntime != nil else {
            throw APIError(message: accessToken.isEmpty ? "需要访问令牌" : "访问令牌无效")
        }
        return health
    }

    func fetchSessions() async throws -> [CopilotSession] {
        let data = try await getData(path: "/api/copilot/sessions")
        return try JSONDecoder().decode(CopilotSessionList.self, from: data).items
    }

    func createSession(title: String = "新对话") async throws -> CopilotSession {
        let body: [String: Any] = [
            "title": title,
            "current_page": "chat",
            "anchor_symbol": NSNull(),
            "authority_level": "A4",
            "default_model": NSNull(),
        ]
        let data = try await request(path: "/api/copilot/sessions", method: "POST", json: body)
        return try JSONDecoder().decode(CopilotSession.self, from: data)
    }

    func deleteSession(id: String) async throws {
        _ = try await request(path: "/api/copilot/sessions/\(id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? id)", method: "DELETE")
    }

    func fetchMessages(sessionId: String) async throws -> [CopilotMessage] {
        let path = "/api/copilot/sessions/\(sessionId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? sessionId)/messages"
        let data = try await getData(path: path)
        return try JSONDecoder().decode(CopilotMessageList.self, from: data).items
    }

    func sendMessage(sessionId: String, message: String) async throws -> CopilotRun {
        let path = "/api/copilot/sessions/\(sessionId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? sessionId)/messages"
        let body: [String: Any] = [
            "message": message,
            "page": "chat",
            "symbol": "",
            "authority_level": "A4",
            "client_message_id": "ios-\(Int(Date().timeIntervalSince1970 * 1000))",
            "attachments": [],
        ]
        let data = try await request(path: path, method: "POST", json: body)
        return try JSONDecoder().decode(CopilotRun.self, from: data)
    }

    func streamURL(sessionId: String, runId: String) throws -> URL {
        let path = "/api/copilot/sessions/\(sessionId)/stream/\(runId)"
        var components = URLComponents(url: try makeURL(path: path), resolvingAgainstBaseURL: false)
        if !accessToken.isEmpty {
            components?.queryItems = [URLQueryItem(name: "access_token", value: accessToken)]
        }
        guard let url = components?.url else { throw APIError(message: "流地址无效") }
        return url
    }

    func fetchWatchlist() async throws -> [WatchlistItem] {
        let data = try await getData(path: "/api/watchlist")
        // API may return a bare array
        if let items = try? JSONDecoder().decode([WatchlistItem].self, from: data) {
            return items
        }
        return []
    }

    func fetchHoldings() async throws -> [HoldingItem] {
        let data = try await getData(path: "/api/holdings")
        if let wrapped = try? JSONDecoder().decode(HoldingsResponse.self, from: data), let items = wrapped.items {
            return items
        }
        if let items = try? JSONDecoder().decode([HoldingItem].self, from: data) {
            return items
        }
        return []
    }

    func fetchMonitorEvents() async throws -> [MonitorEvent] {
        let data = try await getData(path: "/api/monitor/events?page=1&page_size=50")
        return try JSONDecoder().decode(MonitorEventList.self, from: data).items
    }

    func makeSSESession() -> URLSession {
        // SSE uses its own dataTask delegate session; keep this for API symmetry.
        session
    }

    // MARK: - HTTP helpers

    private func getData(path: String) async throws -> Data {
        try await request(path: path, method: "GET")
    }

    @discardableResult
    private func request(path: String, method: String, json: [String: Any]? = nil) async throws -> Data {
        let finalURL = try makeURL(path: path)

        var req = URLRequest(url: finalURL)
        req.httpMethod = method
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        if !accessToken.isEmpty {
            req.setValue(accessToken, forHTTPHeaderField: "X-Workbench-Token")
        }
        if let json {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject: json)
        }

        do {
            let (data, response) = try await session.data(for: req)
            guard let http = response as? HTTPURLResponse else {
                throw APIError(message: "无效响应")
            }
            if http.statusCode == 401 {
                throw APIError(message: "访问令牌无效")
            }
            guard (200..<300).contains(http.statusCode) else {
                let detail = String(data: data, encoding: .utf8) ?? ""
                throw APIError(message: "HTTP \(http.statusCode)\(detail.isEmpty ? "" : ": \(detail.prefix(120))")")
            }
            return data
        } catch let err as APIError {
            throw err
        } catch {
            throw TransportErrorMapper.map(error)
        }
    }

    static func mapTransportError(_ error: Error) -> APIError {
        TransportErrorMapper.map(error)
    }

    private func makeURL(path: String) throws -> URL {
        guard let base = baseURL else { throw APIError(message: "未配置远端地址") }
        let trimmed = path.hasPrefix("/") ? String(path.dropFirst()) : path
        guard let url = URL(string: trimmed, relativeTo: base)?.absoluteURL else {
            throw APIError(message: "请求地址无效")
        }
        return url
    }
}

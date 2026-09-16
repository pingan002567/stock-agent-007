import Foundation
import UniformTypeIdentifiers

/// Accepts server trust for personal self-signed HTTPS backends.
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

    @Published private(set) var lastActiveClient: String?
    @Published private(set) var lastRuntimeMode: String?
    @Published private(set) var lastModelName: String?
    @Published private(set) var lastDegraded: Bool?

    func configure(baseURLString: String, token: String) throws {
        let normalized = try Self.normalizeRemoteURL(baseURLString)
        guard let url = URL(string: normalized) else {
            throw APIError(message: "地址无效")
        }
        baseURL = url
        accessToken = token.trimmingCharacters(in: .whitespacesAndNewlines)
        lastActiveClient = nil
        lastRuntimeMode = nil
        lastModelName = nil
        lastDegraded = nil
    }

    func clear() {
        baseURL = nil
        accessToken = ""
        lastActiveClient = nil
        lastRuntimeMode = nil
        lastModelName = nil
        lastDegraded = nil
    }

    var isConfigured: Bool { baseURL != nil }

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
        guard let runtime = health.agentRuntime else {
            throw APIError(message: accessToken.isEmpty ? "需要访问令牌" : "访问令牌无效（health 无 agent_runtime）")
        }
        lastActiveClient = runtime.activeClient
        lastRuntimeMode = runtime.mode
        lastModelName = runtime.modelName
        lastDegraded = runtime.degraded
        return health
    }

    /// Soft hint when 443 still blocked (cleared after Phase 5 SG open).
    static func connectionHint(forURLString raw: String) -> String? {
        guard let url = URL(string: (try? normalizeRemoteURL(raw)) ?? raw),
              let host = url.host else { return nil }
        if host == "47.103.58.33", url.port == 8686 {
            return nil
        }
        return nil
    }

    // MARK: - Copilot

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

    func renameSession(id: String, title: String) async throws -> CopilotSession {
        let data = try await request(
            path: "/api/copilot/sessions/\(enc(id))",
            method: "PUT",
            json: ["title": title]
        )
        return try JSONDecoder().decode(CopilotSession.self, from: data)
    }

    func deleteSession(id: String) async throws {
        _ = try await request(path: "/api/copilot/sessions/\(enc(id))", method: "DELETE")
    }

    func fetchMessages(sessionId: String) async throws -> [CopilotMessage] {
        let page = try await fetchMessagePage(sessionId: sessionId, limitTurns: nil, before: nil)
        return page.items
    }

    /// When ``limitTurns`` is set, returns a turn-paginated window; otherwise full history.
    func fetchMessagePage(
        sessionId: String,
        limitTurns: Int? = 20,
        before: String? = nil
    ) async throws -> CopilotMessagePage {
        var items: [URLQueryItem] = []
        if let limitTurns {
            items.append(URLQueryItem(name: "limit_turns", value: String(limitTurns)))
        }
        if let before, !before.isEmpty {
            items.append(URLQueryItem(name: "before", value: before))
        }
        let data = try await getData(
            path: "/api/copilot/sessions/\(enc(sessionId))/messages",
            query: items
        )
        if limitTurns == nil {
            let list = try JSONDecoder().decode(CopilotMessageList.self, from: data)
            return CopilotMessagePage(items: list.items, hasMore: false, nextBefore: nil)
        }
        return try JSONDecoder().decode(CopilotMessagePage.self, from: data)
    }

    func sendMessage(
        sessionId: String,
        message: String,
        attachments: [SessionUpload] = []
    ) async throws -> CopilotRun {
        let body: [String: Any] = [
            "message": message,
            "page": "chat",
            "symbol": "",
            "authority_level": "A4",
            "client_message_id": "ios-\(Int(Date().timeIntervalSince1970 * 1000))",
            "attachments": attachments.map { $0.asAttachmentPayload() },
        ]
        let data = try await request(
            path: "/api/copilot/sessions/\(enc(sessionId))/messages",
            method: "POST",
            json: body
        )
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

    func listUploads(sessionId: String) async throws -> SessionUploadsResponse {
        let data = try await getData(path: "/api/copilot/sessions/\(enc(sessionId))/uploads")
        return try JSONDecoder().decode(SessionUploadsResponse.self, from: data)
    }

    func deleteUpload(sessionId: String, filename: String) async throws {
        _ = try await request(
            path: "/api/copilot/sessions/\(enc(sessionId))/uploads/\(enc(filename))",
            method: "DELETE"
        )
    }

    func uploadFiles(sessionId: String, fileURLs: [URL]) async throws -> SessionUploadsResponse {
        let boundary = "Boundary-\(UUID().uuidString)"
        var body = Data()
        for fileURL in fileURLs {
            let name = fileURL.lastPathComponent
            let fileData = try Data(contentsOf: fileURL)
            body.append("--\(boundary)\r\n".data(using: .utf8)!)
            body.append(
                "Content-Disposition: form-data; name=\"files\"; filename=\"\(name)\"\r\n"
                    .data(using: .utf8)!
            )
            body.append("Content-Type: application/octet-stream\r\n\r\n".data(using: .utf8)!)
            body.append(fileData)
            body.append("\r\n".data(using: .utf8)!)
        }
        body.append("--\(boundary)--\r\n".data(using: .utf8)!)

        let data = try await request(
            path: "/api/copilot/sessions/\(enc(sessionId))/uploads",
            method: "POST",
            rawBody: body,
            contentType: "multipart/form-data; boundary=\(boundary)"
        )
        if let decoded = try? JSONDecoder().decode(SessionUploadsResponse.self, from: data) {
            return decoded
        }
        return try await listUploads(sessionId: sessionId)
    }

    // MARK: - Watchlist / stocks

    func fetchWatchlist() async throws -> [WatchlistItem] {
        let data = try await getData(path: "/api/watchlist")
        if let items = try? JSONDecoder().decode([WatchlistItem].self, from: data) {
            return items
        }
        return []
    }

    func addWatchlistItem(symbol: String, name: String) async throws {
        let body: [String: Any] = [
            "symbol": symbol,
            "name": name,
            "group": "观察池",
            "tags": [],
            "monitored": false,
        ]
        _ = try await request(path: "/api/watchlist/items", method: "POST", json: body)
    }

    func deleteWatchlistItem(symbol: String) async throws {
        _ = try await request(path: "/api/watchlist/items/\(enc(symbol))", method: "DELETE")
    }

    func searchStocks(query: String) async throws -> [StockSearchHit] {
        let q = query.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? query
        let data = try await getData(path: "/api/stocks/search?q=\(q)")
        return try JSONDecoder().decode(StockSearchResponse.self, from: data).items
    }

    func fetchStockContext(symbol: String) async throws -> StockContextBrief {
        let data = try await getData(path: "/api/stocks/\(enc(symbol))/context")
        return try JSONDecoder().decode(StockContextBrief.self, from: data)
    }

    func fetchStockHistory(symbol: String, days: Int = 30) async throws -> [HistoryBar] {
        let data = try await getData(path: "/api/stocks/\(enc(symbol))/history?days=\(days)")
        return try JSONDecoder().decode(StockHistoryResponse.self, from: data).items ?? []
    }

    func fetchStockIntel(symbol: String) async throws -> [IntelItem] {
        let data = try await getData(path: "/api/stocks/\(enc(symbol))/intel")
        return try JSONDecoder().decode(StockIntelResponse.self, from: data).items ?? []
    }

    func fetchStockFinancial(symbol: String) async throws -> StockFinancialResponse {
        let data = try await getData(path: "/api/stocks/\(enc(symbol))/financial")
        return try JSONDecoder().decode(StockFinancialResponse.self, from: data)
    }

    func fetchReport(reportId: String) async throws -> ReportDetail {
        let data = try await getData(path: "/api/reports/\(enc(reportId))")
        return try JSONDecoder().decode(ReportDetail.self, from: data)
    }

    func triggerStockResearch(symbol: String) async throws -> ResearchTriggerResult {
        let data = try await request(
            path: "/api/stocks/\(enc(symbol))/research",
            method: "POST",
            json: [:]
        )
        let obj = (try? JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
        let report = obj["report"] as? [String: Any]
        let task = obj["task"] as? [String: Any]
        return ResearchTriggerResult(
            status: obj["status"] as? String,
            message: obj["message"] as? String,
            reportId: report?["report_id"] as? String,
            taskId: task?["task_id"] as? String
        )
    }

    // MARK: - Holdings

    func fetchHoldingsBundle() async throws -> HoldingsResponse {
        let data = try await getData(path: "/api/holdings")
        return try JSONDecoder().decode(HoldingsResponse.self, from: data)
    }

    func fetchHoldings() async throws -> [HoldingItem] {
        try await fetchHoldingsBundle().items ?? []
    }

    // MARK: - Monitor

    func fetchMonitorEvents(page: Int = 1, pageSize: Int = 30) async throws -> MonitorEventList {
        let data = try await getData(path: "/api/monitor/events?page=\(page)&page_size=\(pageSize)")
        return try JSONDecoder().decode(MonitorEventList.self, from: data)
    }

    func fetchMonitorStatus() async throws -> MonitorStatus {
        let data = try await getData(path: "/api/monitor/status")
        return try JSONDecoder().decode(MonitorStatus.self, from: data)
    }

    func startMonitor() async throws -> MonitorStatus {
        let data = try await request(path: "/api/monitor/start", method: "POST", json: [:])
        return try JSONDecoder().decode(MonitorStatus.self, from: data)
    }

    func pauseMonitor() async throws -> MonitorStatus {
        let data = try await request(path: "/api/monitor/pause", method: "POST", json: [:])
        return try JSONDecoder().decode(MonitorStatus.self, from: data)
    }

    func fetchMonitorRules() async throws -> [MonitorRule] {
        let data = try await getData(path: "/api/monitor/rules")
        return try JSONDecoder().decode(MonitorRuleList.self, from: data).items
    }

    func upsertMonitorRule(_ body: [String: Any]) async throws -> MonitorRule {
        let data = try await request(path: "/api/monitor/rules", method: "POST", json: body)
        return try JSONDecoder().decode(MonitorRule.self, from: data)
    }

    func deleteMonitorRule(id: String) async throws {
        _ = try await request(path: "/api/monitor/rules/\(enc(id))", method: "DELETE")
    }

    @discardableResult
    func evaluateMonitorOnce(force: Bool = false) async throws -> [String: Any] {
        let data = try await request(
            path: "/api/monitor/evaluate-once",
            method: "POST",
            json: ["source": "ios_manual", "force": force]
        )
        return (try? JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
    }

    func sendMonitorFeedback(ruleId: String, wasUseful: Bool) async throws {
        _ = try await request(
            path: "/api/monitor/feedback",
            method: "POST",
            json: ["rule_id": ruleId, "was_useful": wasUseful]
        )
    }

    // MARK: - Strategy / backtest

    func fetchStrategies() async throws -> [StrategyItem] {
        let data = try await getData(path: "/api/strategies")
        return try JSONDecoder().decode(StrategyList.self, from: data).items
    }

    func fetchLatestBacktest(strategyId: String) async throws -> BacktestRun? {
        do {
            let data = try await getData(path: "/api/strategies/\(enc(strategyId))/backtests/latest")
            return try JSONDecoder().decode(BacktestRun.self, from: data)
        } catch {
            return nil
        }
    }

    func runBacktest(strategyId: String) async throws -> BacktestRun {
        let data = try await request(
            path: "/api/strategies/\(enc(strategyId))/backtest",
            method: "POST",
            json: [:]
        )
        return try JSONDecoder().decode(BacktestRun.self, from: data)
    }

    func fetchBacktest(runId: String) async throws -> BacktestRun {
        let data = try await getData(path: "/api/backtests/\(enc(runId))")
        return try JSONDecoder().decode(BacktestRun.self, from: data)
    }

    // MARK: - Settings / runtime

    func fetchSettings() async throws -> WorkbenchSettings {
        let data = try await getData(path: "/api/settings")
        return try JSONDecoder().decode(WorkbenchSettings.self, from: data)
    }

    func setSkillEnabled(name: String, enabled: Bool) async throws -> [SkillInfo] {
        let data = try await request(
            path: "/api/settings/skills",
            method: "PUT",
            json: ["name": name, "enabled": enabled]
        )
        let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        guard let skillsRaw = obj?["skills"] else { return [] }
        let skillsData = try JSONSerialization.data(withJSONObject: skillsRaw)
        return try JSONDecoder().decode([SkillInfo].self, from: skillsData)
    }

    func fetchCostSummary() async throws -> [CostDay] {
        let data = try await getData(path: "/api/runtime/cost-summary")
        return try JSONDecoder().decode(CostSummaryResponse.self, from: data).days ?? []
    }

    func fetchReports(page: Int = 1, pageSize: Int = 20) async throws -> ReportListResponse {
        let data = try await getData(path: "/api/reports?page=\(page)&page_size=\(pageSize)")
        return try JSONDecoder().decode(ReportListResponse.self, from: data)
    }

    // MARK: - Devices / APNs

    func registerAPNsDevice(token: String, environment: String) async throws {
        _ = try await request(
            path: "/api/devices/apns",
            method: "POST",
            json: [
                "device_token": token,
                "environment": environment,
                "platform": "ios",
                "bundle_id": "com.stockagent.app",
            ]
        )
    }

    func unregisterAPNsDevice(token: String) async throws {
        _ = try await request(
            path: "/api/devices/apns/\(enc(token))",
            method: "DELETE"
        )
    }

    func makeSSESession() -> URLSession { session }

    // MARK: - HTTP helpers

    private func enc(_ value: String) -> String {
        value.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? value
    }

    private func getData(path: String, query: [URLQueryItem] = []) async throws -> Data {
        try await request(path: path, method: "GET", query: query)
    }

    @discardableResult
    private func request(
        path: String,
        method: String,
        json: [String: Any]? = nil,
        rawBody: Data? = nil,
        contentType: String? = nil,
        query: [URLQueryItem] = []
    ) async throws -> Data {
        var finalURL = try makeURL(path: path)
        if !query.isEmpty {
            guard var components = URLComponents(url: finalURL, resolvingAgainstBaseURL: false) else {
                throw APIError(message: "请求地址无效")
            }
            components.queryItems = (components.queryItems ?? []) + query
            guard let url = components.url else { throw APIError(message: "请求地址无效") }
            finalURL = url
        }
        var req = URLRequest(url: finalURL)
        req.httpMethod = method
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        if !accessToken.isEmpty {
            req.setValue(accessToken, forHTTPHeaderField: "X-Workbench-Token")
        }
        if let rawBody {
            req.httpBody = rawBody
            req.setValue(contentType ?? "application/octet-stream", forHTTPHeaderField: "Content-Type")
        } else if let json {
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

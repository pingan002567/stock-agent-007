import Foundation

struct HealthResponse: Decodable {
    let status: String?
    let serverRole: String?
    let agentRuntime: AgentRuntimeStatus?
    let dataProvider: DataProviderStatus?

    enum CodingKeys: String, CodingKey {
        case status
        case serverRole = "server_role"
        case agentRuntime = "agent_runtime"
        case dataProvider = "data_provider"
    }
}

struct AgentRuntimeStatus: Decodable, Hashable {
    let activeClient: String?
    let mode: String?
    let available: Bool?
    let degraded: Bool?
    let degradedReason: String?
    let modelName: String?
    let thinkingEnabled: Bool?
    let subagentEnabled: Bool?
    let planMode: Bool?

    enum CodingKeys: String, CodingKey {
        case mode, available, degraded
        case activeClient = "active_client"
        case degradedReason = "degraded_reason"
        case modelName = "model_name"
        case thinkingEnabled = "thinking_enabled"
        case subagentEnabled = "subagent_enabled"
        case planMode = "plan_mode"
    }
}

struct DataProviderStatus: Decodable, Hashable {
    let activeProvider: String?
    let fallbackProvider: String?
    let degraded: Bool?
    let degradedReason: String?
    let akshareAvailable: Bool?

    enum CodingKeys: String, CodingKey {
        case degraded
        case activeProvider = "active_provider"
        case fallbackProvider = "fallback_provider"
        case degradedReason = "degraded_reason"
        case akshareAvailable = "akshare_available"
    }
}

struct WorkbenchSettings: Decodable {
    let skills: [SkillInfo]?
    let agentRuntime: AgentRuntimeStatus?
    let dataProvider: DataProviderStatus?
    let runtimeConfig: RuntimeConfigPublic?
    let tradingControls: TradingControls?

    enum CodingKeys: String, CodingKey {
        case skills
        case agentRuntime = "agent_runtime"
        case dataProvider = "data_provider"
        case runtimeConfig = "runtime_config"
        case tradingControls = "trading_controls"
    }
}

struct SkillInfo: Identifiable, Decodable, Hashable {
    let name: String
    let label: String?
    let description: String?
    let authority: String?
    var enabled: Bool?
    let locked: Bool?

    var id: String { name }
    var displayName: String { label ?? name }
}

struct RuntimeConfigPublic: Decodable, Hashable {
    let providerId: String?
    let modelName: String?
    let defaultModel: String?
    let baseUrl: String?
    let hasApiKey: Bool?

    enum CodingKeys: String, CodingKey {
        case baseUrl = "base_url"
        case providerId = "provider_id"
        case modelName = "model_name"
        case defaultModel = "default_model"
        case hasApiKey = "has_api_key"
    }
}

struct TradingControls: Decodable, Hashable {
    let paperTrading: String?
    let realOrder: String?

    enum CodingKeys: String, CodingKey {
        case paperTrading = "paper_trading"
        case realOrder = "real_order"
    }
}

struct CostDay: Identifiable, Decodable, Hashable {
    let date: String?
    let totalCost: Double?
    let totalInputTokens: Int?
    let totalOutputTokens: Int?
    let runCount: Int?

    var id: String { date ?? UUID().uuidString }

    enum CodingKeys: String, CodingKey {
        case date
        case totalCost = "total_cost"
        case totalInputTokens = "total_input_tokens"
        case totalOutputTokens = "total_output_tokens"
        case runCount = "run_count"
    }
}

struct CostSummaryResponse: Decodable {
    let days: [CostDay]?
}

struct ReportListItem: Identifiable, Decodable, Hashable {
    let reportId: String
    let title: String?
    let symbol: String?
    let reportType: String?
    let conclusion: String?
    let generatedAt: String?

    var id: String { reportId }

    enum CodingKeys: String, CodingKey {
        case title, symbol, conclusion
        case reportId = "report_id"
        case reportType = "report_type"
        case generatedAt = "generated_at"
    }
}

struct ReportListResponse: Decodable {
    let items: [ReportListItem]
    let total: Int?
    let page: Int?
    let totalPages: Int?

    enum CodingKeys: String, CodingKey {
        case items, total, page
        case totalPages = "total_pages"
    }
}

struct CopilotSession: Identifiable, Decodable, Hashable {
    let sessionId: String
    var title: String
    let createdAt: String?
    let lastMessageAt: String?
    let messageCount: Int?

    var id: String { sessionId }

    var displayTitle: String {
        let t = title.trimmingCharacters(in: .whitespacesAndNewlines)
        return t.isEmpty ? "未命名" : t
    }

    enum CodingKeys: String, CodingKey {
        case sessionId = "session_id"
        case title
        case createdAt = "created_at"
        case lastMessageAt = "last_message_at"
        case messageCount = "message_count"
    }
}

struct CopilotSessionList: Decodable {
    let items: [CopilotSession]
}

struct CopilotMessage: Identifiable, Decodable, Hashable {
    let messageId: String
    let sessionId: String?
    let role: String
    let kind: String?
    let text: String?
    let createdAt: String?
    let runId: String?
    let payload: [String: JSONValue]?

    var id: String { messageId }

    enum CodingKeys: String, CodingKey {
        case messageId = "message_id"
        case sessionId = "session_id"
        case role, kind, text, payload
        case createdAt = "created_at"
        case runId = "run_id"
    }
}

struct CopilotMessageList: Decodable {
    let items: [CopilotMessage]
    let hasMore: Bool?
    let nextBefore: String?

    enum CodingKeys: String, CodingKey {
        case items
        case hasMore = "has_more"
        case nextBefore = "next_before"
    }
}

struct CopilotMessagePage: Decodable {
    let items: [CopilotMessage]
    let hasMore: Bool
    let nextBefore: String?

    enum CodingKeys: String, CodingKey {
        case items
        case hasMore = "has_more"
        case nextBefore = "next_before"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        items = try c.decode([CopilotMessage].self, forKey: .items)
        hasMore = try c.decodeIfPresent(Bool.self, forKey: .hasMore) ?? false
        nextBefore = try c.decodeIfPresent(String.self, forKey: .nextBefore)
    }

    init(items: [CopilotMessage], hasMore: Bool, nextBefore: String?) {
        self.items = items
        self.hasMore = hasMore
        self.nextBefore = nextBefore
    }
}

struct CopilotRun: Decodable {
    let runId: String
    let sessionId: String?

    enum CodingKeys: String, CodingKey {
        case runId = "run_id"
        case sessionId = "session_id"
    }
}

struct WatchlistItem: Identifiable, Decodable, Hashable {
    let symbol: String
    let name: String?
    let group: String?
    let monitored: Bool?
    let price: PriceInfo?

    var id: String { symbol }

    struct PriceInfo: Decodable, Hashable {
        let last: Double?
        let changePct: Double?
        enum CodingKeys: String, CodingKey {
            case last
            case changePct = "change_pct"
        }
    }
}

struct StockSearchHit: Identifiable, Decodable, Hashable {
    let symbol: String
    let name: String?
    let market: String?

    var id: String { symbol }
}

struct StockSearchResponse: Decodable {
    let items: [StockSearchHit]
}

struct HoldingItem: Identifiable, Decodable, Hashable {
    let symbol: String?
    let name: String?
    let quantity: Double?
    let marketValue: Double?
    let cost: Double?
    let pnlPct: Double?

    var id: String { symbol ?? name ?? "holding" }

    enum CodingKeys: String, CodingKey {
        case symbol, name, quantity, cost
        case marketValue = "market_value"
        case pnlPct = "pnl_pct"
    }
}

struct HoldingsSummary: Decodable {
    let totalValue: Double?
    let positions: Int?
    let maxWeightPct: Double?
    let cashPct: Double?
    let source: String?

    enum CodingKeys: String, CodingKey {
        case totalValue = "total_value"
        case positions
        case maxWeightPct = "max_weight_pct"
        case cashPct = "cash_pct"
        case source
    }
}

struct HoldingsResponse: Decodable {
    let items: [HoldingItem]?
    let summary: HoldingsSummary?
    let demo: Bool?
}

struct MonitorEvent: Decodable, Identifiable, Hashable {
    let eventId: String?
    let symbol: String?
    let title: String?
    let message: String?
    let severity: String?
    let triggeredAt: String?
    let ruleId: String?
    let ruleType: String?
    let triggerRule: String?
    let source: String?
    let evidence: [JSONValue]?
    let suggestedActions: [String]?
    let payload: [String: JSONValue]?

    var id: String { stableId }
    var stableId: String {
        eventId ?? "\(symbol ?? "")-\(triggeredAt ?? "")-\(title ?? "")"
    }

    var isBrowsableSymbol: Bool {
        guard let symbol, !symbol.isEmpty else { return false }
        let upper = symbol.uppercased()
        let blocked: Set<String> = ["DATA", "MARKET", "SYSTEM", "PORTFOLIO", "ALL"]
        return !blocked.contains(upper)
    }

    var evidenceLines: [String] {
        (evidence ?? []).compactMap { $0.displayLine }
    }

    var payloadSummary: String {
        guard let payload, !payload.isEmpty else { return "" }
        return payload
            .map { "\($0.key): \($0.value.displayLine ?? "")" }
            .sorted()
            .joined(separator: "\n")
    }

    enum CodingKeys: String, CodingKey {
        case eventId = "event_id"
        case symbol, title, message, severity, source, evidence, payload
        case triggeredAt = "triggered_at"
        case ruleId = "rule_id"
        case ruleType = "rule_type"
        case triggerRule = "trigger_rule"
        case suggestedActions = "suggested_actions"
    }
}

struct MonitorEventList: Decodable {
    let items: [MonitorEvent]
    let total: Int?
    let page: Int?
    let pageSize: Int?
    let totalPages: Int?

    enum CodingKeys: String, CodingKey {
        case items, total, page
        case pageSize = "page_size"
        case totalPages = "total_pages"
    }
}

struct MonitorStatus: Decodable {
    let status: String?
    let autoStart: Bool?
    let intervalSeconds: Int?
    let lastCheckedAt: String?
    let lastMatchedAt: String?
    let lastError: String?

    var isRunning: Bool {
        let s = (status ?? "").lowercased()
        return s == "running" || s == "active" || s == "started"
    }

    enum CodingKeys: String, CodingKey {
        case status
        case autoStart = "auto_start"
        case intervalSeconds = "interval_seconds"
        case lastCheckedAt = "last_checked_at"
        case lastMatchedAt = "last_matched_at"
        case lastError = "last_error"
    }
}

struct MonitorRule: Identifiable, Decodable, Hashable {
    let ruleId: String?
    var title: String?
    var ruleType: String?
    var enabled: Bool?
    var severity: String?
    var symbol: String?
    var threshold: Double?
    var keyword: String?
    var cooldownSeconds: Int?
    var triggerRule: String?
    var source: String?

    var id: String { ruleId ?? title ?? "rule" }
    var displayName: String { title ?? ruleId ?? "规则" }

    enum CodingKeys: String, CodingKey {
        case title, enabled, severity, symbol, threshold, keyword, source
        case ruleId = "rule_id"
        case ruleType = "rule_type"
        case cooldownSeconds = "cooldown_seconds"
        case triggerRule = "trigger_rule"
    }

    func upsertBody(enabledOverride: Bool? = nil) -> [String: Any] {
        var body: [String: Any] = [
            "rule_type": ruleType ?? "price_change_pct_gt",
            "enabled": enabledOverride ?? (enabled ?? true),
            "severity": severity ?? "medium",
            "cooldown_seconds": cooldownSeconds ?? 3600,
        ]
        if let ruleId { body["rule_id"] = ruleId }
        if let title { body["title"] = title }
        if let symbol, !symbol.isEmpty { body["symbol"] = symbol }
        if let threshold { body["threshold"] = threshold }
        if let keyword { body["keyword"] = keyword }
        if let triggerRule { body["trigger_rule"] = triggerRule }
        if let source { body["source"] = source }
        return body
    }

    static func newPriceMove(
        title: String,
        symbol: String?,
        threshold: Double,
        severity: String
    ) -> [String: Any] {
        var body: [String: Any] = [
            "rule_type": "price_change_pct_gt",
            "title": title,
            "threshold": threshold,
            "severity": severity,
            "enabled": true,
            "cooldown_seconds": 3600,
            "trigger_rule": "abs(price_change_pct) > \(threshold.gFormat)%",
            "source": "ios",
        ]
        if let symbol, !symbol.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            body["symbol"] = symbol.uppercased()
        }
        return body
    }
}

struct MonitorRuleList: Decodable {
    let items: [MonitorRule]
}

private extension Double {
    var gFormat: String {
        truncatingRemainder(dividingBy: 1) == 0
            ? String(format: "%.0f", self)
            : String(format: "%g", self)
    }
}

struct SessionUpload: Identifiable, Decodable, Hashable {
    let filename: String
    let size: Int?
    let mimeType: String?
    let markdownFile: String?

    var id: String { filename }

    enum CodingKeys: String, CodingKey {
        case filename, size
        case mimeType = "mime_type"
        case markdownFile = "markdown_file"
    }

    func asAttachmentPayload() -> [String: Any] {
        var body: [String: Any] = [
            "filename": filename,
            "size": size ?? 0,
        ]
        if let markdownFile {
            body["markdown_file"] = markdownFile
        }
        return body
    }
}

struct SessionUploadsResponse: Decodable {
    let supported: Bool?
    let files: [SessionUpload]?
    let count: Int?
}

struct StockContextBrief: Decodable {
    let symbol: String?
    let name: String?
    let market: String?
    let industry: String?
    let sector: String?
    let price: ContextPrice?
    let summary: String?
    let relation: Relation?
    let holding: HoldingBrief?
    let aiState: AIState?
    let latestReport: LatestReportRef?
    let researchStatus: String?

    struct ContextPrice: Decodable {
        let last: Double?
        let changePct: Double?
        let source: String?
        let degraded: Bool?
        let updatedAt: String?
        enum CodingKeys: String, CodingKey {
            case last, source, degraded
            case changePct = "change_pct"
            case updatedAt = "updated_at"
        }
    }

    struct Relation: Decodable {
        let inHoldings: Bool?
        let inWatchlist: Bool?
        let monitored: Bool?
        enum CodingKeys: String, CodingKey {
            case inHoldings = "in_holdings"
            case inWatchlist = "in_watchlist"
            case monitored
        }
    }

    struct HoldingBrief: Decodable {
        let quantity: Double?
        let cost: Double?
        let marketValue: Double?
        let pnlPct: Double?
        let weightPct: Double?
        enum CodingKeys: String, CodingKey {
            case quantity, cost
            case marketValue = "market_value"
            case pnlPct = "pnl_pct"
            case weightPct = "weight_pct"
        }
    }

    struct AIState: Decodable {
        let stance: String?
        let score: Double?
        let confidence: Double?
        let riskLabel: String?
        enum CodingKeys: String, CodingKey {
            case stance, score, confidence
            case riskLabel = "risk_label"
        }
    }

    struct LatestReportRef: Decodable {
        let reportId: String?
        let generatedAt: String?
        enum CodingKeys: String, CodingKey {
            case reportId = "report_id"
            case generatedAt = "generated_at"
        }
    }

    enum CodingKeys: String, CodingKey {
        case symbol, name, market, industry, sector, price, summary, relation, holding
        case aiState = "ai_state"
        case latestReport = "latest_report"
        case researchStatus = "research_status"
    }
}

struct HistoryBar: Identifiable, Decodable, Hashable {
    let date: String?
    let open: Double?
    let high: Double?
    let low: Double?
    let close: Double?
    let volume: Double?

    var id: String { date ?? UUID().uuidString }
}

struct StockHistoryResponse: Decodable {
    let symbol: String?
    let items: [HistoryBar]?
}

struct IntelItem: Identifiable, Decodable, Hashable {
    let title: String?
    let source: String?
    let publishedAt: String?
    let url: String?
    let type: String?

    var id: String { "\(title ?? "")-\(publishedAt ?? "")-\(url ?? "")" }

    enum CodingKeys: String, CodingKey {
        case title, source, url, type
        case publishedAt = "published_at"
    }
}

struct StockIntelResponse: Decodable {
    let items: [IntelItem]?
}

struct FinancialRow: Identifiable, Decodable, Hashable {
    let reportDate: String?
    let reportType: String?
    let revenue: Double?
    let profit: Double?
    let totalAssets: Double?
    let totalLiabilities: Double?

    var id: String { "\(reportDate ?? "")-\(reportType ?? "")" }

    enum CodingKeys: String, CodingKey {
        case revenue, profit
        case reportDate = "report_date"
        case reportType = "report_type"
        case totalAssets = "total_assets"
        case totalLiabilities = "total_liabilities"
    }
}

struct StockFinancialResponse: Decodable {
    let items: [FinancialRow]?
    let degraded: Bool?
}

struct ResearchTriggerResult {
    let status: String?
    let message: String?
    let reportId: String?
    let taskId: String?
}

struct ReportDetail: Identifiable, Decodable, Hashable {
    let reportId: String
    let title: String?
    let symbol: String?
    let reportType: String?
    let conclusion: String?
    let content: String?
    let generatedAt: String?

    var id: String { reportId }

    enum CodingKeys: String, CodingKey {
        case title, symbol, content, conclusion
        case reportId = "report_id"
        case reportType = "report_type"
        case generatedAt = "generated_at"
    }
}

struct StrategyItem: Identifiable, Decodable, Hashable {
    let strategyId: String?
    let name: String?
    let strategyType: String?
    let description: String?

    var id: String { strategyId ?? name ?? UUID().uuidString }

    enum CodingKeys: String, CodingKey {
        case strategyId = "strategy_id"
        case name
        case strategyType = "strategy_type"
        case description
    }
}

struct StrategyList: Decodable {
    let items: [StrategyItem]
}

struct BacktestRun: Identifiable, Decodable {
    let runId: String
    let strategyId: String?
    let strategyName: String?
    let createdAt: String?
    let metrics: BacktestMetrics?
    let degraded: Bool?
    let degradedReason: String?

    var id: String { runId }

    enum CodingKeys: String, CodingKey {
        case runId = "run_id"
        case strategyId = "strategy_id"
        case strategyName = "strategy_name"
        case createdAt = "created_at"
        case metrics, degraded
        case degradedReason = "degraded_reason"
    }
}

struct BacktestMetrics: Decodable {
    let totalReturnPct: Double?
    let annualizedReturnPct: Double?
    let maxDrawdownPct: Double?
    let sharpeRatio: Double?
    let winRate: Double?

    enum CodingKeys: String, CodingKey {
        case totalReturnPct = "total_return_pct"
        case annualizedReturnPct = "annualized_return_pct"
        case maxDrawdownPct = "max_drawdown_pct"
        case sharpeRatio = "sharpe_ratio"
        case winRate = "win_rate"
    }
}

struct BacktestList: Decodable {
    let items: [BacktestRun]
}

struct APIError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

enum TransportErrorMapper {
    static func map(_ error: Error) -> APIError {
        let ns = error as NSError
        let certCodes: Set<Int> = [
            NSURLErrorServerCertificateUntrusted,
            NSURLErrorServerCertificateHasBadDate,
            NSURLErrorServerCertificateHasUnknownRoot,
            NSURLErrorServerCertificateNotYetValid,
            NSURLErrorClientCertificateRejected,
            NSURLErrorSecureConnectionFailed,
        ]
        if ns.domain == NSURLErrorDomain && certCodes.contains(ns.code) {
            return APIError(message: "证书不被信任：请确认已使用最新原生包（已放行自签 HTTPS）")
        }
        let timeoutCodes: Set<Int> = [
            NSURLErrorTimedOut,
            NSURLErrorCannotConnectToHost,
            NSURLErrorNetworkConnectionLost,
            NSURLErrorNotConnectedToInternet,
        ]
        if ns.domain == NSURLErrorDomain && timeoutCodes.contains(ns.code) {
            return APIError(message: "连接超时或主机不可达：请确认地址与安全组（443/8686），并确认手机网络能访问该主机")
        }
        let msg = error.localizedDescription
        if msg.contains("证书") || msg.range(of: "certificate|SSL|TLS|secure", options: [.regularExpression, .caseInsensitive]) != nil {
            return APIError(message: "证书不被信任：请确认已使用最新原生包（已放行自签 HTTPS）")
        }
        if msg.range(of: "timed out|Timeout|无法连接|Could not connect", options: [.regularExpression, .caseInsensitive]) != nil {
            return APIError(message: "连接超时或主机不可达：请确认地址与安全组（443/8686），并确认手机网络能访问该主机")
        }
        return APIError(message: "无法连上后端，请确认服务已启动、地址正确，且手机能访问该主机")
    }
}

enum RemoteDefaults {
    /// Prefer default HTTPS once SG opens 443; :8686 remains compatible.
    static let recommendedBaseURL = "https://47.103.58.33"
    static let alternateBaseURL = "https://47.103.58.33:8686"
}

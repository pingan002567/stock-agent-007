import Foundation

struct HealthResponse: Decodable {
    let status: String?
    let serverRole: String?
    let agentRuntime: AgentRuntime?

    enum CodingKeys: String, CodingKey {
        case status
        case serverRole = "server_role"
        case agentRuntime = "agent_runtime"
    }

    struct AgentRuntime: Decodable {
        let activeClient: String?
        enum CodingKeys: String, CodingKey {
            case activeClient = "active_client"
        }
    }
}

struct CopilotSession: Identifiable, Decodable, Hashable {
    let sessionId: String
    var title: String
    let createdAt: String?
    let lastMessageAt: String?
    let messageCount: Int?

    var id: String { sessionId }

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

    var id: String { messageId }

    enum CodingKeys: String, CodingKey {
        case messageId = "message_id"
        case sessionId = "session_id"
        case role, kind, text
        case createdAt = "created_at"
        case runId = "run_id"
    }
}

struct CopilotMessageList: Decodable {
    let items: [CopilotMessage]
}

struct CopilotRun: Decodable {
    let runId: String
    let sessionId: String?

    enum CodingKeys: String, CodingKey {
        case runId = "run_id"
        case sessionId = "session_id"
    }
}

struct WatchlistItem: Identifiable, Decodable {
    let symbol: String
    let name: String?
    let group: String?
    let monitored: Bool?
    let price: PriceInfo?

    var id: String { symbol }

    struct PriceInfo: Decodable {
        let last: Double?
        let changePct: Double?
        enum CodingKeys: String, CodingKey {
            case last
            case changePct = "change_pct"
        }
    }
}

struct HoldingItem: Identifiable, Decodable {
    let symbol: String?
    let name: String?
    let quantity: Double?
    let marketValue: Double?
    let costBasis: Double?
    let pnlPct: Double?

    var id: String { symbol ?? UUID().uuidString }

    enum CodingKeys: String, CodingKey {
        case symbol, name, quantity
        case marketValue = "market_value"
        case costBasis = "cost_basis"
        case pnlPct = "pnl_pct"
    }
}

struct HoldingsResponse: Decodable {
    let items: [HoldingItem]?
}

struct MonitorEvent: Decodable {
    let id: String?
    let symbol: String?
    let title: String?
    let message: String?
    let severity: String?
    let createdAt: String?

    var stableId: String { id ?? "\(symbol ?? "")-\(createdAt ?? "")-\(title ?? "")" }

    enum CodingKeys: String, CodingKey {
        case id, symbol, title, message, severity
        case createdAt = "created_at"
    }
}

struct MonitorEventList: Decodable {
    let items: [MonitorEvent]
    let total: Int?
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
        let msg = error.localizedDescription
        if msg.contains("证书") || msg.range(of: "certificate|SSL|TLS|secure", options: [.regularExpression, .caseInsensitive]) != nil {
            return APIError(message: "证书不被信任：请确认已使用最新原生包（已放行自签 HTTPS）")
        }
        return APIError(message: "无法连上后端，请确认服务已启动、地址正确，且手机能访问该主机")
    }
}

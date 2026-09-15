import SwiftUI

struct MonitorView: View {
    @State private var items: [MonitorEvent] = []
    @State private var error = ""
    @State private var loading = true

    var body: some View {
        NavigationStack {
            Group {
                if loading {
                    ProgressView("加载盯盘…")
                } else if !error.isEmpty {
                    ContentUnavailableView("加载失败", systemImage: "exclamationmark.triangle", description: Text(error))
                } else if items.isEmpty {
                    ContentUnavailableView("暂无事件", systemImage: "bell", description: Text("盯盘规则触发后会显示在这里。"))
                } else {
                    List(items, id: \.stableId) { event in
                        VStack(alignment: .leading, spacing: 6) {
                            HStack {
                                Text(event.title ?? event.symbol ?? "事件")
                                    .font(.headline)
                                Spacer()
                                if let severity = event.severity {
                                    Text(severity.uppercased())
                                        .font(.caption2.bold())
                                        .padding(.horizontal, 6)
                                        .padding(.vertical, 2)
                                        .background(severityColor(severity).opacity(0.15))
                                        .foregroundStyle(severityColor(severity))
                                        .clipShape(Capsule())
                                }
                            }
                            if let message = event.message, !message.isEmpty {
                                Text(message).font(.subheadline).foregroundStyle(.secondary)
                            }
                            if let created = event.createdAt {
                                Text(created).font(.caption2).foregroundStyle(.tertiary)
                            }
                        }
                        .padding(.vertical, 2)
                    }
                }
            }
            .navigationTitle("盯盘")
            .refreshable { await load() }
            .task { await load() }
        }
    }

    private func severityColor(_ s: String) -> Color {
        switch s.lowercased() {
        case "high", "critical": return .red
        case "medium", "warn", "warning": return .orange
        default: return .blue
        }
    }

    private func load() async {
        loading = items.isEmpty
        error = ""
        do {
            items = try await APIClient.shared.fetchMonitorEvents()
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
        loading = false
    }
}

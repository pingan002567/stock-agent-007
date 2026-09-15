import SwiftUI

struct WatchlistView: View {
    @State private var items: [WatchlistItem] = []
    @State private var error = ""
    @State private var loading = true

    var body: some View {
        NavigationStack {
            Group {
                if loading {
                    ProgressView("加载自选…")
                } else if !error.isEmpty {
                    ContentUnavailableView("加载失败", systemImage: "exclamationmark.triangle", description: Text(error))
                } else if items.isEmpty {
                    ContentUnavailableView("暂无自选", systemImage: "star", description: Text("在桌面端或对话里添加标的后会显示在这里。"))
                } else {
                    List(items) { item in
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(item.name ?? item.symbol).font(.headline)
                                Text(item.symbol).font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            if let last = item.price?.last {
                                VStack(alignment: .trailing, spacing: 2) {
                                    Text(String(format: "%.2f", last)).font(.body.monospacedDigit())
                                    if let pct = item.price?.changePct {
                                        Text(String(format: "%+.2f%%", pct))
                                            .font(.caption.monospacedDigit())
                                            .foregroundStyle(pct >= 0 ? .green : .red)
                                    }
                                }
                            }
                        }
                    }
                }
            }
            .navigationTitle("自选")
            .refreshable { await load() }
            .task { await load() }
        }
    }

    private func load() async {
        loading = items.isEmpty
        error = ""
        do {
            items = try await APIClient.shared.fetchWatchlist()
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
        loading = false
    }
}

import SwiftUI

struct WatchlistView: View {
    @State private var items: [WatchlistItem] = []
    @State private var error = ""
    @State private var loading = true
    @State private var showAdd = false
    @State private var selected: WatchlistItem?

    var body: some View {
        NavigationStack {
            Group {
                if loading {
                    ProgressView("加载自选…")
                } else if !error.isEmpty && items.isEmpty {
                    ContentUnavailableView("加载失败", systemImage: "exclamationmark.triangle", description: Text(error))
                } else if items.isEmpty {
                    ContentUnavailableView(
                        "暂无自选",
                        systemImage: "star",
                        description: Text("点右上角添加标的，或在桌面端/对话里维护自选。")
                    )
                } else {
                    List {
                        ForEach(items) { item in
                            Button {
                                selected = item
                            } label: {
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
                            .foregroundStyle(.primary)
                            .swipeActions {
                                Button(role: .destructive) {
                                    Task { await remove(item.symbol) }
                                } label: {
                                    Text("删除")
                                }
                            }
                        }
                    }
                }
            }
            .navigationTitle("自选")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showAdd = true } label: {
                        Image(systemName: "plus")
                    }
                }
            }
            .refreshable { await load() }
            .task { await load() }
            .sheet(isPresented: $showAdd) {
                AddWatchlistSheet {
                    await load()
                }
            }
            .navigationDestination(item: $selected) { item in
                StockDetailView(symbol: item.symbol, fallbackName: item.name)
            }
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

    private func remove(_ symbol: String) async {
        do {
            try await APIClient.shared.deleteWatchlistItem(symbol: symbol)
            items.removeAll { $0.symbol == symbol }
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }
}

struct AddWatchlistSheet: View {
    var onAdded: () async -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var query = ""
    @State private var hits: [StockSearchHit] = []
    @State private var error = ""
    @State private var searching = false

    var body: some View {
        NavigationStack {
            List {
                if !error.isEmpty {
                    Text(error).foregroundStyle(.red).font(.footnote)
                }
                ForEach(hits) { hit in
                    Button {
                        Task { await add(hit) }
                    } label: {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(hit.name ?? hit.symbol).foregroundStyle(.primary)
                            Text("\(hit.symbol)\(hit.market.map { " · \($0)" } ?? "")")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            }
            .searchable(text: $query, prompt: "代码或名称")
            .navigationTitle("添加自选")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
            }
            .onChange(of: query) { _, newValue in
                Task { await search(newValue) }
            }
            .overlay {
                if searching { ProgressView() }
            }
        }
    }

    private func search(_ q: String) async {
        let trimmed = q.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.count >= 1 else {
            hits = []
            return
        }
        searching = true
        defer { searching = false }
        do {
            hits = try await APIClient.shared.searchStocks(query: trimmed)
            error = ""
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }

    private func add(_ hit: StockSearchHit) async {
        do {
            try await APIClient.shared.addWatchlistItem(symbol: hit.symbol, name: hit.name ?? hit.symbol)
            await onAdded()
            dismiss()
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }
}

import SwiftUI

struct ScheduledTasksView: View {
    @State private var items: [ScheduledTask] = []
    @State private var error = ""
    @State private var loading = true
    @State private var busyId: String?
    @State private var selectedReport: ReportDetail?
    @State private var notice = ""

    var body: some View {
        Group {
            if loading && items.isEmpty {
                ProgressView("加载定时任务…")
            } else if items.isEmpty {
                ContentUnavailableView(
                    "暂无定时任务",
                    systemImage: "clock",
                    description: Text(error.isEmpty ? "盘前简报等值班任务会出现在这里。" : error)
                )
            } else {
                List {
                    if !notice.isEmpty {
                        Text(notice)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                    ForEach(items) { task in
                        ScheduledTaskRow(
                            task: task,
                            busy: busyId == task.taskId,
                            onToggle: { enabled in
                                Task { await toggle(task, enabled: enabled) }
                            },
                            onRunNow: {
                                Task { await runNow(task) }
                            },
                            onOpenReport: { reportId in
                                Task { await openReport(reportId) }
                            }
                        )
                    }
                }
                .listStyle(.insetGrouped)
            }
        }
        .navigationTitle("定时值班")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .refreshable { await load() }
        .sheet(item: $selectedReport) { report in
            NavigationStack {
                ScrollView {
                    MarkdownText(
                        source: report.content ?? report.conclusion ?? "暂无正文",
                        richBlocks: true
                    )
                    .padding()
                }
                .navigationTitle(report.title ?? "报告")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button("完成") { selectedReport = nil }
                    }
                }
            }
        }
    }

    private func load() async {
        if items.isEmpty { loading = true }
        defer { loading = false }
        do {
            items = try await APIClient.shared.fetchScheduledTasks()
            error = ""
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }

    private func toggle(_ task: ScheduledTask, enabled: Bool) async {
        busyId = task.taskId
        defer { busyId = nil }
        do {
            let updated = try await APIClient.shared.toggleScheduledTask(
                taskId: task.taskId,
                enabled: enabled
            )
            if let idx = items.firstIndex(where: { $0.taskId == task.taskId }) {
                items[idx] = updated
            }
            notice = enabled ? "已启用「\(task.name)」" : "已停用「\(task.name)」"
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
            await load()
        }
    }

    private func runNow(_ task: ScheduledTask) async {
        if let idx = items.firstIndex(where: { $0.taskId == task.taskId }) {
            items[idx].lastStatus = "running"
        }
        notice = "已后台启动「\(task.name)」，完成后下拉刷新或点查看报告"
        let taskId = task.taskId
        let name = task.name
        Task {
            do {
                try await APIClient.shared.runScheduledTaskNow(taskId: taskId)
                await MainActor.run {
                    notice = "「\(name)」已完成，可下拉刷新查看报告"
                }
            } catch {
                await MainActor.run {
                    notice = (error as? APIError)?.message ?? error.localizedDescription
                }
            }
            await load()
        }
    }

    private func openReport(_ reportId: String) async {
        do {
            selectedReport = try await APIClient.shared.fetchReport(reportId: reportId)
        } catch {
            self.error = (error as? APIError)?.message ?? error.localizedDescription
        }
    }
}

private struct ScheduledTaskRow: View {
    let task: ScheduledTask
    let busy: Bool
    let onToggle: (Bool) -> Void
    let onRunNow: () -> Void
    let onOpenReport: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(task.name)
                        .font(.headline)
                    Text(task.scheduleLabelZh)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer(minLength: 8)
                Toggle("", isOn: Binding(
                    get: { task.enabled },
                    set: { onToggle($0) }
                ))
                .labelsHidden()
                .disabled(busy)
            }

            HStack(spacing: 8) {
                Text("下次 \(task.nextRunShort)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                statusPill
            }

            if let skip = task.skipReason, task.enabled, !skip.isEmpty {
                Text(skip)
                    .font(.caption)
                    .foregroundStyle(.orange)
            } else if task.lastStatus == "failed", let err = task.lastError, !err.isEmpty {
                Text(err)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .lineLimit(2)
            }

            HStack(spacing: 12) {
                Button("立即运行", action: onRunNow)
                    .buttonStyle(.borderedProminent)
                    .controlSize(.small)
                    .disabled(busy)
                if let rid = task.lastReportId, !rid.isEmpty {
                    Button("查看报告") { onOpenReport(rid) }
                        .buttonStyle(.borderless)
                        .controlSize(.small)
                } else {
                    Text("暂无报告")
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                }
                if busy {
                    ProgressView()
                        .controlSize(.small)
                }
            }
        }
        .padding(.vertical, 4)
    }

    @ViewBuilder
    private var statusPill: some View {
        let status = (task.lastStatus ?? "").lowercased()
        let (text, color): (String, Color) = {
            switch status {
            case "completed", "success", "ok":
                return ("成功\(agoSuffix)", .green)
            case "failed", "error":
                return ("失败", .red)
            case "running":
                return ("运行中", .blue)
            case "skipped":
                return ("已跳过", .orange)
            case "":
                return task.enabled ? ("未运行", .secondary) : ("已停用", .secondary)
            default:
                return (task.lastStatus ?? "—", .secondary)
            }
        }()
        Text(text)
            .font(.caption2.weight(.semibold))
            .padding(.horizontal, 8)
            .padding(.vertical, 2)
            .background(color.opacity(0.12), in: Capsule())
            .foregroundStyle(color)
    }

    private var agoSuffix: String {
        guard let raw = task.lastRunAt, !raw.isEmpty else { return "" }
        return " · \(Self.relativeTime(raw))"
    }

    private static func relativeTime(_ iso: String) -> String {
        let formats = [
            "yyyy-MM-dd'T'HH:mm:ssZ",
            "yyyy-MM-dd'T'HH:mm:ss",
            "yyyy-MM-dd'T'HH:mm",
            "yyyy-MM-dd HH:mm:ss",
        ]
        let parser = DateFormatter()
        parser.locale = Locale(identifier: "en_US_POSIX")
        var date: Date?
        for f in formats {
            parser.dateFormat = f
            if let d = parser.date(from: iso) {
                date = d
                break
            }
            // Try with fractional seconds stripped
            let trimmed = String(iso.prefix(19))
            if let d = parser.date(from: trimmed.replacingOccurrences(of: " ", with: "T")) {
                date = d
                break
            }
        }
        guard let date else { return iso }
        let formatter = RelativeDateTimeFormatter()
        formatter.locale = Locale(identifier: "zh_CN")
        formatter.unitsStyle = .short
        return formatter.localizedString(for: date, relativeTo: Date())
    }
}

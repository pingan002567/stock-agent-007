import SwiftUI
import PhotosUI
import UniformTypeIdentifiers

struct ChatView: View {
    @EnvironmentObject private var chat: ChatViewModel
    @Environment(\.scenePhase) private var scenePhase
    @State private var appeared = false

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                MessageListView()
                if !chat.uploads.isEmpty || chat.uploadsBusy {
                    UploadStripView()
                }
                ComposerView()
            }
            .navigationTitle(chat.title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        chat.drawerOpen = true
                    } label: {
                        Image(systemName: "line.3.horizontal")
                    }
                    .accessibilityLabel("会话列表")
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        Task { await chat.newSession() }
                    } label: {
                        Image(systemName: "plus")
                    }
                    .accessibilityLabel("新对话")
                }
            }
            .sheet(isPresented: $chat.drawerOpen) {
                SessionDrawerView()
                    .presentationDetents([.large])
            }
            .overlay(alignment: .top) {
                VStack(spacing: 0) {
                    if !chat.error.isEmpty {
                        HStack {
                            Text(chat.error)
                                .font(.footnote)
                                .foregroundStyle(.red)
                            if chat.canRetry {
                                Button("重试") {
                                    Task { await chat.retryLastFailed() }
                                }
                                .font(.footnote.bold())
                            }
                        }
                        .padding(8)
                        .frame(maxWidth: .infinity)
                        .background(.ultraThinMaterial)
                    }
                    if !chat.notice.isEmpty {
                        Text(chat.notice)
                            .font(.footnote)
                            .foregroundStyle(.primary)
                            .padding(8)
                            .frame(maxWidth: .infinity)
                            .background(Color.accentColor.opacity(0.12))
                            .onTapGesture { chat.notice = "" }
                            .task(id: chat.notice) {
                                try? await Task.sleep(nanoseconds: 4_000_000_000)
                                if !chat.notice.isEmpty { chat.notice = "" }
                            }
                    }
                }
            }
            .task {
                if !appeared {
                    appeared = true
                    await chat.bootstrap()
                }
            }
            .onChange(of: scenePhase) { _, phase in
                if phase == .active {
                    Task { await chat.handleAppBecameActive() }
                }
            }
        }
    }
}

struct MessageListView: View {
    @EnvironmentObject private var chat: ChatViewModel
    @ObservedObject private var appearance = ChatAppearanceStore.shared

    var body: some View {
        ZStack {
            chatBackground
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 14) {
                        historyHeader

                        if chat.rows.isEmpty && !chat.sending {
                            VStack(spacing: 12) {
                                Text("有什么可以帮你？")
                                    .font(.system(size: 28, weight: .semibold))
                                Text("可给目标价与操作观点，不下单。结论仅供研究参考。")
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)
                                    .multilineTextAlignment(.center)
                            }
                            .frame(maxWidth: .infinity)
                            .padding(.top, 80)
                            .padding(.horizontal, 24)
                        }

                        ForEach(Array(chat.rows.enumerated()), id: \.element.id) { index, row in
                            Group {
                                switch row {
                                case .user(let bubble):
                                    UserBubbleView(bubble: bubble)
                                case .assistant(let turn):
                                    AssistantBubbleView(turn: turn)
                                }
                            }
                            .id(row.id)
                            .onAppear {
                                if index == 0 {
                                    Task { await chat.loadOlderHistoryIfNeeded() }
                                }
                            }
                        }
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 12)
                }
                .scrollContentBackground(.hidden)
                .onChange(of: chat.rows.last?.scrollText) { _, _ in
                    // Stick to bottom only while the visible session is generating.
                    guard chat.sending, let id = chat.rows.last?.id else { return }
                    withAnimation { proxy.scrollTo(id, anchor: .bottom) }
                }
                .onChange(of: chat.scrollTarget) { _, target in
                    guard let target else { return }
                    switch target {
                    case .bottom(let id):
                        withAnimation { proxy.scrollTo(id, anchor: .bottom) }
                    case .pin(let id):
                        proxy.scrollTo(id, anchor: .top)
                    }
                    chat.consumeScrollTarget()
                }
            }
        }
    }

    @ViewBuilder
    private var historyHeader: some View {
        if chat.isLoadingOlder {
            HStack(spacing: 8) {
                ProgressView()
                Text("加载更早消息…")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 6)
            .id("history-loading")
        } else if chat.hasMoreHistory && !chat.rows.isEmpty {
            Text("上滑加载更早消息")
                .font(.caption2)
                .foregroundStyle(.tertiary)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 4)
                .id("history-hint")
        } else if !chat.hasMoreHistory && chat.rows.count > 8 {
            Text("没有更多消息了")
                .font(.caption2)
                .foregroundStyle(.tertiary)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 4)
        }
    }

    @ViewBuilder
    private var chatBackground: some View {
        if let image = appearance.backgroundImage {
            GeometryReader { geo in
                Image(uiImage: image)
                    .resizable()
                    .scaledToFill()
                    .frame(width: geo.size.width, height: geo.size.height)
                    .clipped()
                    .overlay(Color.black.opacity(appearance.dimOpacity))
            }
            .ignoresSafeArea(edges: .bottom)
        } else {
            Color(.systemBackground)
        }
    }
}

struct UploadStripView: View {
    @EnvironmentObject private var chat: ChatViewModel

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                if chat.uploadsBusy {
                    ProgressView().padding(.leading, 8)
                }
                ForEach(chat.uploads) { file in
                    HStack(spacing: 6) {
                        Image(systemName: "paperclip")
                        Text(file.filename)
                            .lineLimit(1)
                        Button {
                            Task { await chat.deleteUpload(file) }
                        } label: {
                            Image(systemName: "xmark.circle.fill")
                                .foregroundStyle(.secondary)
                        }
                    }
                    .font(.caption)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 6)
                    .background(Color(.secondarySystemBackground))
                    .clipShape(Capsule())
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
        }
    }
}

struct ComposerView: View {
    @EnvironmentObject private var chat: ChatViewModel
    @FocusState private var focused: Bool
    @State private var showFileImporter = false
    @State private var photoItem: PhotosPickerItem?

    var body: some View {
        VStack(spacing: 0) {
            Divider()
            HStack(alignment: .center, spacing: 10) {
                Menu {
                    PhotosPicker(selection: $photoItem, matching: .images) {
                        Label("相册图片", systemImage: "photo")
                    }
                    Button {
                        showFileImporter = true
                    } label: {
                        Label("选取文件", systemImage: "doc")
                    }
                } label: {
                    Image(systemName: "plus.circle.fill")
                        .font(.system(size: 30))
                        .symbolRenderingMode(.hierarchical)
                        .foregroundStyle(chat.uploadsSupported ? Color.accentColor : Color.secondary)
                        .frame(width: 34, height: 34)
                        .contentShape(Rectangle())
                }
                .disabled(!chat.uploadsSupported || chat.sending)

                TextField("问 Stock Agent…", text: $chat.draft, axis: .vertical)
                    .lineLimit(1...6)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)
                    .frame(minHeight: 34)
                    .background(Color(.secondarySystemBackground))
                    .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                    .focused($focused)

                Group {
                    if chat.sending {
                        Button { chat.stop() } label: {
                            Image(systemName: "stop.circle.fill")
                                .font(.system(size: 30))
                                .frame(width: 34, height: 34)
                                .contentShape(Rectangle())
                        }
                        .accessibilityLabel("停止")
                    } else {
                        Button {
                            Task { await chat.send() }
                        } label: {
                            Image(systemName: "arrow.up.circle.fill")
                                .font(.system(size: 30))
                                .frame(width: 34, height: 34)
                                .contentShape(Rectangle())
                        }
                        .disabled(chat.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
        }
        .background(.bar)
        .fileImporter(
            isPresented: $showFileImporter,
            allowedContentTypes: [.item, .pdf, .plainText, .image],
            allowsMultipleSelection: true
        ) { result in
            if case .success(let urls) = result {
                Task { await chat.uploadFiles(urls) }
            }
        }
        .onChange(of: photoItem) { _, item in
            guard let item else { return }
            Task {
                if let data = try? await item.loadTransferable(type: Data.self) {
                    let url = FileManager.default.temporaryDirectory
                        .appendingPathComponent("photo-\(UUID().uuidString).jpg")
                    try? data.write(to: url)
                    await chat.uploadFiles([url])
                }
                photoItem = nil
            }
        }
    }
}

struct SessionDrawerView: View {
    @EnvironmentObject private var chat: ChatViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var pendingDelete: CopilotSession?
    @State private var renameTarget: CopilotSession?
    @State private var renameText = ""
    @State private var query = ""

    private var filteredSessions: [CopilotSession] {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty else { return chat.sessions }
        return chat.sessions.filter {
            $0.displayTitle.localizedCaseInsensitiveContains(q)
                || $0.sessionId.localizedCaseInsensitiveContains(q)
        }
    }

    var body: some View {
        NavigationStack {
            List {
                Button {
                    Task {
                        await chat.newSession()
                        dismiss()
                    }
                } label: {
                    Label("新建对话", systemImage: "plus")
                }

                Section {
                    if filteredSessions.isEmpty {
                        Text(query.isEmpty ? "暂无会话" : "无匹配会话")
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(filteredSessions) { session in
                            Button {
                                Task {
                                    await chat.openSession(session)
                                    dismiss()
                                }
                            } label: {
                                HStack(alignment: .center, spacing: 10) {
                                    VStack(alignment: .leading, spacing: 4) {
                                        Text(session.displayTitle)
                                            .foregroundStyle(.primary)
                                            .lineLimit(1)
                                        if let meta = session.lastMessageAt ?? session.createdAt {
                                            Text(meta)
                                                .font(.caption)
                                                .foregroundStyle(.secondary)
                                        }
                                    }
                                    Spacer(minLength: 0)
                                    if chat.isStreaming(sessionId: session.sessionId) {
                                        ProgressView()
                                            .controlSize(.small)
                                    }
                                }
                            }
                            .swipeActions(edge: .trailing) {
                                Button(role: .destructive) {
                                    pendingDelete = session
                                } label: {
                                    Text("删除")
                                }
                                Button {
                                    renameTarget = session
                                    renameText = session.title
                                } label: {
                                    Text("重命名")
                                }
                                .tint(.blue)
                            }
                            .contextMenu {
                                Button {
                                    renameTarget = session
                                    renameText = session.title
                                } label: {
                                    Label("重命名", systemImage: "pencil")
                                }
                                Button(role: .destructive) {
                                    pendingDelete = session
                                } label: {
                                    Label("删除", systemImage: "trash")
                                }
                            }
                        }
                    }
                } header: {
                    Text("会话")
                }
            }
            .navigationTitle("会话")
            .searchable(text: $query, prompt: "搜索会话")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("完成") { dismiss() }
                }
            }
            .task { await chat.bootstrap() }
            .confirmationDialog(
                "删除此会话？",
                isPresented: Binding(
                    get: { pendingDelete != nil },
                    set: { if !$0 { pendingDelete = nil } }
                ),
                titleVisibility: .visible
            ) {
                Button("删除", role: .destructive) {
                    if let session = pendingDelete {
                        Task { await chat.deleteSession(session) }
                    }
                    pendingDelete = nil
                }
                Button("取消", role: .cancel) { pendingDelete = nil }
            }
            .alert(
                "重命名会话",
                isPresented: Binding(
                    get: { renameTarget != nil },
                    set: { if !$0 { renameTarget = nil } }
                )
            ) {
                TextField("标题", text: $renameText)
                Button("保存") {
                    if let session = renameTarget {
                        Task { await chat.renameSession(session, title: renameText) }
                    }
                    renameTarget = nil
                }
                Button("取消", role: .cancel) { renameTarget = nil }
            }
        }
    }
}

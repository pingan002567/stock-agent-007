import SwiftUI
import UIKit
import PhotosUI
import UniformTypeIdentifiers

struct ChatView: View {
    @EnvironmentObject private var chat: ChatViewModel
    @Environment(\.scenePhase) private var scenePhase
    @State private var appeared = false
    /// Distance to lift the composer above the software keyboard.
    @State private var keyboardLift: CGFloat = 0
    /// Host view used to measure composer-bottom ↔ keyboard-top overlap.
    @StateObject private var keyboardHost = ChatKeyboardHost()

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                ConnectivityBanner(reachability: NetworkReachability.shared)
                MessageListView(keyboardLift: keyboardLift)
                VStack(spacing: 0) {
                    if !chat.uploads.isEmpty || chat.uploadsBusy {
                        UploadStripView()
                    }
                    ComposerView()
                        .background {
                            ChatKeyboardHostAnchor(host: keyboardHost)
                        }
                }
                // Snap with keyboard — no ease/bounce on the composer.
                .offset(y: -keyboardLift)
                .transaction { $0.animation = nil }
            }
            .ignoresSafeArea(.keyboard)
            .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillShowNotification)) { note in
                applyKeyboardShow(note)
            }
            .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillChangeFrameNotification)) { note in
                // Only track size changes while already lifted (e.g. emoji keyboard).
                guard keyboardLift > 1 else { return }
                applyKeyboardShow(note)
            }
            .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillHideNotification)) { note in
                let duration = (note.userInfo?[UIResponder.keyboardAnimationDurationUserInfoKey] as? Double) ?? 0.25
                var t = Transaction()
                t.animation = nil
                withTransaction(t) { keyboardLift = 0 }
                DispatchQueue.main.asyncAfter(deadline: .now() + duration + 0.05) {
                    keyboardHost.clearRestingBaseline()
                }
            }
            .onChange(of: chat.currentSession?.sessionId) { _, _ in
                dismissKeyboard()
            }
            .onChange(of: chat.drawerOpen) { _, open in
                if open { dismissKeyboard() }
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

    private func applyKeyboardShow(_ note: Notification) {
        guard let frame = note.userInfo?[UIResponder.keyboardFrameEndUserInfoKey] as? CGRect else { return }

        let lift = keyboardHost.lift(forKeyboardFrame: frame, currentLift: keyboardLift)
        guard lift > 0.5 || keyboardLift > 0.5 else { return }
        guard abs(lift - keyboardLift) > 0.5 else { return }

        var t = Transaction()
        t.animation = nil
        withTransaction(t) { keyboardLift = lift }
    }

    private func dismissKeyboard() {
        UIApplication.shared.sendAction(
            #selector(UIResponder.resignFirstResponder),
            to: nil,
            from: nil,
            for: nil
        )
        if keyboardLift > 0 {
            var t = Transaction()
            t.animation = nil
            withTransaction(t) { keyboardLift = 0 }
            keyboardHost.clearRestingBaseline()
        }
    }
}

struct MessageListView: View {
    @EnvironmentObject private var chat: ChatViewModel
    @ObservedObject private var appearance = ChatAppearanceStore.shared
    var keyboardLift: CGFloat = 0
    /// True while the bottom (latest) region is off-screen.
    @State private var showJumpToLatest = false
    /// Avoid loading older history until the initial scroll-to-latest settles.
    @State private var allowOlderLoad = false
    @State private var pendingRevealLatest = false
    /// Ignore bottom-sentinel appear while prepending history (LazyVStack remount flicker).
    @State private var ignoreBottomAppear = false
    /// Cancels in-flight jump retries when a newer jump/session starts.
    @State private var jumpGeneration = 0

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
                                VStack(spacing: 8) {
                                    ForEach(ChatStarterPrompts.all) { item in
                                        Button {
                                            chat.draft = item.prompt
                                        } label: {
                                            Text(item.label)
                                                .font(.subheadline.weight(.medium))
                                                .frame(maxWidth: .infinity)
                                                .padding(.vertical, 10)
                                                .padding(.horizontal, 12)
                                                .background(Color(.secondarySystemBackground))
                                                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                                        }
                                        .buttonStyle(.plain)
                                        .disabled(!chat.canSend)
                                    }
                                }
                                .padding(.top, 8)
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
                                    AssistantBubbleView(
                                        turn: turn,
                                        onRetry: turn.hasRetryableFailure && chat.canRetry
                                            ? { Task { await chat.retryLastFailed() } }
                                            : nil,
                                        onClarificationSubmit: turn.awaitingClarification
                                            ? { response, text in
                                                Task {
                                                    await chat.submitClarification(
                                                        response: response,
                                                        displayText: text,
                                                        for: turn.id
                                                    )
                                                }
                                            }
                                            : nil
                                    )
                                }
                            }
                            .id(row.id)
                            .onAppear {
                                guard allowOlderLoad, index == 0, chat.rows.count >= 8 else { return }
                                Task { await chat.loadOlderHistoryIfNeeded() }
                            }
                        }

                        Color.clear
                            .frame(height: 24)
                            .id("chat-bottom-sentinel")
                            .onAppear {
                                markArrivedAtLatest()
                            }
                            .onDisappear {
                                guard !chat.rows.isEmpty else { return }
                                // Don't resurface the button while a jump is in flight.
                                guard !pendingRevealLatest else { return }
                                if !showJumpToLatest { showJumpToLatest = true }
                            }

                        // Reserves space under the upward-offset composer; height snaps (no animation).
                        Color.clear
                            .frame(height: keyboardLift)
                            .id("keyboard-lift-spacer")
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 12)
                    .transaction { $0.animation = nil }
                }
                .scrollContentBackground(.hidden)
                .scrollDismissesKeyboard(.interactively)
                .simultaneousGesture(
                    TapGesture().onEnded {
                        UIApplication.shared.sendAction(
                            #selector(UIResponder.resignFirstResponder),
                            to: nil,
                            from: nil,
                            for: nil
                        )
                    }
                )
                .background {
                    ChatScrollKeyboardAnchor(lift: keyboardLift, stickToBottom: !showJumpToLatest)
                }
                .onChange(of: keyboardLift) { _, lift in
                    guard lift > 0, !showJumpToLatest, let id = chat.rows.last?.id else { return }
                    var transaction = Transaction()
                    transaction.disablesAnimations = true
                    withTransaction(transaction) {
                        proxy.scrollTo(id, anchor: .bottom)
                        proxy.scrollTo("chat-bottom-sentinel", anchor: .bottom)
                    }
                }
                .onAppear {
                    if let id = chat.rows.last?.id {
                        revealLatest(proxy: proxy, id: id, fromUser: false)
                    } else {
                        allowOlderLoad = true
                    }
                }
                .onChange(of: chat.rows.last?.scrollText) { _, _ in
                    guard chat.sending, !showJumpToLatest, let id = chat.rows.last?.id else { return }
                    withAnimation { proxy.scrollTo(id, anchor: .bottom) }
                }
                .onChange(of: chat.scrollTarget) { _, target in
                    guard let target else { return }
                    switch target {
                    case .bottom(let id):
                        revealLatest(proxy: proxy, id: id, fromUser: false)
                    case .pin(let id):
                        beginHistoryPin(proxy: proxy, id: id)
                    }
                    chat.consumeScrollTarget()
                }
                .onChange(of: chat.isLoadingOlder) { _, loading in
                    if loading {
                        ignoreBottomAppear = true
                        showJumpToLatest = true
                    }
                }
                .onChange(of: chat.currentSession?.sessionId) { _, _ in
                    showJumpToLatest = false
                    allowOlderLoad = false
                    pendingRevealLatest = true
                    ignoreBottomAppear = false
                    jumpGeneration += 1
                }
                .onChange(of: chat.rows.last?.id) { _, lastId in
                    guard pendingRevealLatest, let lastId else { return }
                    revealLatest(proxy: proxy, id: lastId, fromUser: false)
                }
                .overlay(alignment: .bottomTrailing) {
                    if showJumpToLatest, !chat.rows.isEmpty {
                        Button {
                            guard let id = chat.rows.last?.id else { return }
                            revealLatest(proxy: proxy, id: id, fromUser: true)
                        } label: {
                            HStack(spacing: 5) {
                                Image(systemName: "arrow.down")
                                    .font(.caption.weight(.bold))
                                Text("最新")
                                    .font(.caption.weight(.semibold))
                            }
                            .foregroundStyle(.primary)
                            .padding(.horizontal, 12)
                            .padding(.vertical, 9)
                            .background(.ultraThinMaterial, in: Capsule())
                            .overlay(
                                Capsule()
                                    .strokeBorder(Color.primary.opacity(0.08), lineWidth: 0.5)
                            )
                            .shadow(color: .black.opacity(0.12), radius: 8, y: 3)
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("回到最新消息")
                        .padding(.trailing, 14)
                        .padding(.bottom, 10)
                    }
                }
            }
        }
    }

    private func markArrivedAtLatest() {
        if pendingRevealLatest {
            pendingRevealLatest = false
            allowOlderLoad = true
            showJumpToLatest = false
            return
        }
        guard !ignoreBottomAppear else { return }
        if showJumpToLatest { showJumpToLatest = false }
    }

    private func beginHistoryPin(proxy: ScrollViewProxy, id: String) {
        ignoreBottomAppear = true
        pendingRevealLatest = false
        showJumpToLatest = true
        proxy.scrollTo(id, anchor: .top)
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: 450_000_000)
            ignoreBottomAppear = false
            if !pendingRevealLatest {
                showJumpToLatest = true
            }
        }
    }

    /// - Parameter fromUser: user tapped「最新」. Keep the button until bottom is confirmed,
    ///   because an in-flight scroll gesture often cancels the first `scrollTo`.
    private func revealLatest(proxy: ScrollViewProxy, id: String, fromUser: Bool) {
        jumpGeneration += 1
        let generation = jumpGeneration
        pendingRevealLatest = true
        ignoreBottomAppear = false
        if !fromUser {
            showJumpToLatest = false
        }

        scrollToLatestNow(proxy: proxy, id: id, animated: false)

        Task { @MainActor in
            for step in 0..<14 {
                guard generation == jumpGeneration, pendingRevealLatest else { return }
                try? await Task.sleep(nanoseconds: 70_000_000)
                let animated = step >= 2 && step <= 5
                scrollToLatestNow(proxy: proxy, id: id, animated: animated)
            }
            guard generation == jumpGeneration else { return }
            // Bottom never confirmed: keep button so user can tap again.
            if pendingRevealLatest, fromUser {
                pendingRevealLatest = false
                showJumpToLatest = true
            } else if pendingRevealLatest {
                pendingRevealLatest = false
                allowOlderLoad = true
                showJumpToLatest = false
            }
        }
    }

    private func scrollToLatestNow(proxy: ScrollViewProxy, id: String, animated: Bool) {
        if animated {
            withAnimation(.easeOut(duration: 0.22)) {
                proxy.scrollTo(id, anchor: .bottom)
                proxy.scrollTo("chat-bottom-sentinel", anchor: .bottom)
            }
        } else {
            var transaction = Transaction()
            transaction.disablesAnimations = true
            withTransaction(transaction) {
                proxy.scrollTo(id, anchor: .bottom)
                proxy.scrollTo("chat-bottom-sentinel", anchor: .bottom)
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



/// Holds a real UIView in the chat layout so keyboard overlap can be measured precisely.
@MainActor
private final class ChatKeyboardHost: ObservableObject {
    weak var view: UIView?
    /// Tab-bar / home-indicator inset captured while the keyboard is hidden.
    private var restingBottomInset: CGFloat?

    /// Padding needed so the composer bottom sits flush on the keyboard top.
    func lift(forKeyboardFrame keyboardFrame: CGRect, currentLift: CGFloat) -> CGFloat {
        let window = view?.window
            ?? UIApplication.shared.connectedScenes
                .compactMap { $0 as? UIWindowScene }
                .flatMap(\.windows)
                .first(where: \.isKeyWindow)

        guard let window else {
            let screenHeight = UIScreen.main.bounds.height
            return max(0, screenHeight - keyboardFrame.minY)
        }

        let keyboardInScreen = window.convert(keyboardFrame, from: nil)
        let covered = max(0, window.bounds.height - keyboardInScreen.minY)
        guard covered > 1, keyboardInScreen.minY < window.bounds.height - 1 else { return 0 }

        if currentLift < 1 || restingBottomInset == nil {
            restingBottomInset = resolveBottomInset(window: window)
        }

        // Composer already sits above the tab-bar safe area; subtract that once so we
        // don't leave a safe-area-sized gap above the keyboard.
        return max(0, covered - (restingBottomInset ?? 0))
    }

    func clearRestingBaseline() {
        restingBottomInset = nil
    }

    private func resolveBottomInset(window: UIWindow) -> CGFloat {
        // 1) Prefer safe-area from an ancestor of the composer anchor.
        var node: UIView? = view
        while let current = node {
            if current.safeAreaInsets.bottom > 1 {
                return current.safeAreaInsets.bottom
            }
            node = current.superview
        }

        // 2) SwiftUI TabView still hosts a UITabBar — use its visible height.
        if let tabBar = findTabBar(in: window) {
            let frame = tabBar.convert(tabBar.bounds, to: nil)
            let height = max(0, window.bounds.maxY - frame.minY)
            if height > 1 { return height }
        }

        // 3) Home indicator only (better than overshooting by a full tab bar).
        return window.safeAreaInsets.bottom
    }

    private func findTabBar(in root: UIView) -> UITabBar? {
        if let tabBar = root as? UITabBar { return tabBar }
        for child in root.subviews {
            if let tabBar = findTabBar(in: child) { return tabBar }
        }
        return nil
    }
}

private struct ChatKeyboardHostAnchor: UIViewRepresentable {
    let host: ChatKeyboardHost

    func makeUIView(context: Context) -> UIView {
        let view = PassThroughView()
        DispatchQueue.main.async {
            host.view = view
        }
        return view
    }

    func updateUIView(_ uiView: UIView, context: Context) {
        if host.view !== uiView {
            host.view = uiView
        }
    }
}

/// Shifts the UIScrollView content offset when the composer lifts with the keyboard.
private struct ChatScrollKeyboardAnchor: UIViewRepresentable {
    var lift: CGFloat
    var stickToBottom: Bool

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> UIView {
        let view = PassThroughView()
        context.coordinator.view = view
        return view
    }

    func updateUIView(_ uiView: UIView, context: Context) {
        context.coordinator.apply(lift: lift, stickToBottom: stickToBottom)
    }

    final class Coordinator {
        weak var view: UIView?
        private var lastLift: CGFloat = 0

        func apply(lift: CGFloat, stickToBottom: Bool) {
            let delta = lift - lastLift
            lastLift = lift
            guard abs(delta) > 0.5 else { return }

            // Layout may not have finished; adjust on next run loop.
            DispatchQueue.main.async { [weak self] in
                self?.adjust(delta: delta, stickToBottom: stickToBottom)
            }
        }

        private func adjust(delta: CGFloat, stickToBottom: Bool) {
            guard let scroll = enclosingScrollView() else { return }
            let inset = scroll.adjustedContentInset
            let maxOffset = max(
                0,
                scroll.contentSize.height - scroll.bounds.height + inset.bottom
            )
            var target = scroll.contentOffset.y + delta
            if stickToBottom {
                target = maxOffset
            } else {
                target = min(max(0, target), maxOffset)
            }
            // Instant adjust — animated offset races the composer and shakes the transcript.
            UIView.performWithoutAnimation {
                scroll.contentOffset = CGPoint(x: scroll.contentOffset.x, y: target)
            }
        }

        private func enclosingScrollView() -> UIScrollView? {
            var node = view?.superview
            while let current = node {
                if let scroll = current as? UIScrollView {
                    return scroll
                }
                node = current.superview
            }
            return nil
        }
    }
}

private final class PassThroughView: UIView {
    override func hitTest(_ point: CGPoint, with event: UIEvent?) -> UIView? { nil }
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

                TextField(
                    chat.canSend ? "问 Stock Agent…" : "网络不可用，暂不可发送",
                    text: $chat.draft,
                    axis: .vertical
                )
                    .lineLimit(1...6)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)
                    .frame(minHeight: 34)
                    .background(Color(.secondarySystemBackground))
                    .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                    .focused($focused)
                    .disabled(!chat.canSend && !chat.sending)

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
                        .disabled(
                            !chat.canSend
                                || chat.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                        )
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

import SwiftUI

struct ChatView: View {
    @EnvironmentObject private var chat: ChatViewModel
    @State private var appeared = false

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                MessageListView()
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
                if !chat.error.isEmpty {
                    Text(chat.error)
                        .font(.footnote)
                        .foregroundStyle(.red)
                        .padding(8)
                        .frame(maxWidth: .infinity)
                        .background(.ultraThinMaterial)
                }
            }
            .task {
                if !appeared {
                    appeared = true
                    await chat.bootstrap()
                }
            }
        }
    }
}

struct MessageListView: View {
    @EnvironmentObject private var chat: ChatViewModel

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 14) {
                    if chat.bubbles.isEmpty && !chat.sending {
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

                    ForEach(chat.bubbles) { bubble in
                        MessageBubbleView(bubble: bubble)
                            .id(bubble.id)
                    }
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
            }
            .onChange(of: chat.bubbles.last?.text) { _, _ in
                if let id = chat.bubbles.last?.id {
                    withAnimation { proxy.scrollTo(id, anchor: .bottom) }
                }
            }
        }
    }
}

struct MessageBubbleView: View {
    let bubble: ChatBubble

    var body: some View {
        HStack {
            if bubble.role == "user" { Spacer(minLength: 40) }
            Text(bubble.text.isEmpty && bubble.isStreaming ? "…" : bubble.text)
                .font(.body)
                .padding(.horizontal, bubble.role == "user" ? 14 : 0)
                .padding(.vertical, bubble.role == "user" ? 10 : 2)
                .background(bubble.role == "user" ? Color(.secondarySystemBackground) : Color.clear)
                .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
            if bubble.role != "user" { Spacer(minLength: 24) }
        }
    }
}

struct ComposerView: View {
    @EnvironmentObject private var chat: ChatViewModel
    @FocusState private var focused: Bool

    var body: some View {
        VStack(spacing: 0) {
            Divider()
            HStack(alignment: .bottom, spacing: 10) {
                TextField("问 Stock Agent…", text: $chat.draft, axis: .vertical)
                    .lineLimit(1...6)
                    .padding(12)
                    .background(Color(.secondarySystemBackground))
                    .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                    .focused($focused)

                if chat.sending {
                    Button { chat.stop() } label: {
                        Image(systemName: "stop.circle.fill")
                            .font(.system(size: 32))
                    }
                } else {
                    Button {
                        Task { await chat.send() }
                    } label: {
                        Image(systemName: "arrow.up.circle.fill")
                            .font(.system(size: 32))
                    }
                    .disabled(chat.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
        }
        .background(.bar)
    }
}

struct SessionDrawerView: View {
    @EnvironmentObject private var chat: ChatViewModel
    @Environment(\.dismiss) private var dismiss

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

                Section("会话") {
                    ForEach(chat.sessions) { session in
                        Button {
                            Task {
                                await chat.openSession(session)
                                dismiss()
                            }
                        } label: {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(session.title.isEmpty ? "未命名" : session.title)
                                    .foregroundStyle(.primary)
                                    .lineLimit(1)
                                if let meta = session.lastMessageAt ?? session.createdAt {
                                    Text(meta)
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                            }
                        }
                        .swipeActions {
                            Button(role: .destructive) {
                                Task { await chat.deleteSession(session) }
                            } label: {
                                Text("删除")
                            }
                        }
                    }
                }
            }
            .navigationTitle("会话")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("完成") { dismiss() }
                }
            }
            .task { await chat.bootstrap() }
        }
    }
}

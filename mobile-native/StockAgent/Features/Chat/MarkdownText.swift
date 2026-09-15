import SwiftUI

struct MarkdownText: View {
    let source: String
    var showCursor: Bool = false
    /// When true, use block layout (headings / bullets / spacing) for detail reading.
    var richBlocks: Bool = false

    @State private var rendered: AttributedString = AttributedString()
    @State private var renderTask: Task<Void, Never>?

    var body: some View {
        Group {
            if richBlocks {
                richBody
            } else {
                inlineBody
            }
        }
        .textSelection(.enabled)
        .onAppear { scheduleRender(immediate: true) }
        .onChange(of: source) { _, _ in scheduleRender(immediate: false) }
        .onDisappear { renderTask?.cancel() }
    }

    @ViewBuilder
    private var inlineBody: some View {
        if rendered.characters.isEmpty && source.isEmpty {
            EmptyView()
        } else {
            Text(rendered) + (showCursor ? Text("▍").foregroundStyle(.secondary) : Text(""))
        }
    }

    @ViewBuilder
    private var richBody: some View {
        let blocks = AnswerFormatter.blocks(from: source)
        if blocks.isEmpty {
            EmptyView()
        } else {
            VStack(alignment: .leading, spacing: 14) {
                ForEach(Array(blocks.enumerated()), id: \.offset) { _, block in
                    switch block {
                    case .heading(let text):
                        Text(parseInline(text))
                            .font(.title3.weight(.semibold))
                            .foregroundStyle(.primary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    case .paragraph(let text):
                        Text(parseInline(text))
                            .font(.body)
                            .lineSpacing(5)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    case .bullet(let text):
                        HStack(alignment: .top, spacing: 8) {
                            Text("•")
                                .font(.body.weight(.semibold))
                                .foregroundStyle(.secondary)
                            Text(parseInline(text))
                                .font(.body)
                                .lineSpacing(4)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    case .code(let text):
                        Text(text)
                            .font(.footnote.monospaced())
                            .textSelection(.enabled)
                            .padding(12)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(Color(.secondarySystemBackground))
                            .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                    }
                }
                if showCursor {
                    Text("▍").foregroundStyle(.secondary)
                }
            }
        }
    }

    private func scheduleRender(immediate: Bool) {
        guard !richBlocks else { return }
        renderTask?.cancel()
        renderTask = Task {
            if !immediate {
                try? await Task.sleep(nanoseconds: 70_000_000)
            }
            if Task.isCancelled { return }
            let next = Self.parse(source)
            await MainActor.run {
                rendered = next
            }
        }
    }

    private func parseInline(_ raw: String) -> AttributedString {
        Self.parse(raw, prepare: false)
    }

    private static func parse(_ raw: String, prepare: Bool = true) -> AttributedString {
        let trimmed = prepare ? AnswerFormatter.prepare(raw) : raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return AttributedString() }
        var options = AttributedString.MarkdownParsingOptions()
        options.interpretedSyntax = .full
        options.failurePolicy = .returnPartiallyParsedIfPossible
        if let md = try? AttributedString(markdown: trimmed, options: options) {
            return md
        }
        // Fallback: preserve newlines without markdown
        return AttributedString(trimmed.replacingOccurrences(of: "  \n", with: "\n"))
    }
}

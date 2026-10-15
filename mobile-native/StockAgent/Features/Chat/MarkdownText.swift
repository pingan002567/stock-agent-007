import SwiftUI

struct MarkdownText: View {
    let source: String
    var showCursor: Bool = false
    /// When true, use block layout (headings / lists / tables) for detail reading — desktop parity.
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
                    blockView(block)
                }
                if showCursor {
                    Text("▍").foregroundStyle(.secondary)
                }
            }
        }
    }

    @ViewBuilder
    private func blockView(_ block: AnswerFormatter.Block) -> some View {
        switch block {
        case .heading(let level, let text):
            Text(parseInline(text))
                .font(headingFont(level))
                .foregroundStyle(.primary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.top, level <= 2 ? 4 : 0)

        case .paragraph(let text):
            Text(parseInline(softBreaks(text)))
                .font(.body)
                .lineSpacing(5)
                .frame(maxWidth: .infinity, alignment: .leading)

        case .unorderedList(let items):
            VStack(alignment: .leading, spacing: 8) {
                ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                    HStack(alignment: .top, spacing: 8) {
                        Text("•")
                            .font(.body.weight(.semibold))
                            .foregroundStyle(.secondary)
                        Text(parseInline(item))
                            .font(.body)
                            .lineSpacing(4)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }

        case .orderedList(let items):
            VStack(alignment: .leading, spacing: 8) {
                ForEach(Array(items.enumerated()), id: \.offset) { idx, item in
                    HStack(alignment: .top, spacing: 8) {
                        Text("\(idx + 1).")
                            .font(.body.monospacedDigit().weight(.semibold))
                            .foregroundStyle(.secondary)
                            .frame(minWidth: 22, alignment: .trailing)
                        Text(parseInline(item))
                            .font(.body)
                            .lineSpacing(4)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }

        case .code(let text):
            Text(text)
                .font(.footnote.monospaced())
                .textSelection(.enabled)
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color(.secondarySystemBackground))
                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))

        case .table(let headers, let rows):
            MarkdownTableView(headers: headers, rows: rows)

        case .horizontalRule:
            Divider()
                .padding(.vertical, 4)
        }
    }

    private func headingFont(_ level: Int) -> Font {
        switch level {
        case 1: return .title2.weight(.bold)
        case 2: return .title3.weight(.semibold)
        case 3: return .headline.weight(.semibold)
        default: return .subheadline.weight(.semibold)
        }
    }

    /// Preserve soft newlines inside a paragraph (desktop renderInline inserts <br>).
    private func softBreaks(_ text: String) -> String {
        text.replacingOccurrences(of: "\n", with: "  \n")
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
        return AttributedString(trimmed.replacingOccurrences(of: "  \n", with: "\n"))
    }
}

// MARK: - Table (desktop msg-table parity)

private struct MarkdownTableView: View {
    let headers: [String]
    let rows: [[String]]

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 0) {
                    ForEach(Array(headers.enumerated()), id: \.offset) { _, header in
                        Text(inline(header))
                            .font(.caption.weight(.semibold))
                            .frame(minWidth: 72, alignment: .leading)
                            .padding(.horizontal, 10)
                            .padding(.vertical, 8)
                    }
                }
                .background(Color(.tertiarySystemFill))

                ForEach(Array(rows.enumerated()), id: \.offset) { ri, row in
                    HStack(spacing: 0) {
                        ForEach(0..<headers.count, id: \.self) { ci in
                            let cell = ci < row.count ? row[ci] : ""
                            Text(inline(cell))
                                .font(.caption)
                                .frame(minWidth: 72, alignment: .leading)
                                .padding(.horizontal, 10)
                                .padding(.vertical, 8)
                        }
                    }
                    .background(ri % 2 == 0 ? Color.clear : Color(.secondarySystemBackground).opacity(0.55))
                }
            }
            .overlay(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .stroke(Color(.separator), lineWidth: 0.5)
            )
            .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        }
    }

    private func inline(_ raw: String) -> AttributedString {
        var options = AttributedString.MarkdownParsingOptions()
        options.interpretedSyntax = .inlineOnlyPreservingWhitespace
        options.failurePolicy = .returnPartiallyParsedIfPossible
        if let md = try? AttributedString(markdown: raw, options: options) {
            return md
        }
        return AttributedString(raw)
    }
}

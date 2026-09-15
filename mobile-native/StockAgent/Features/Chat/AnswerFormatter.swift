import Foundation

/// Turns assistant answer text into readable blocks for bubble / detail views.
enum AnswerFormatter {
    enum Block: Equatable {
        case heading(String)
        case paragraph(String)
        case bullet(String)
        case code(String)
    }

    /// Normalize newlines, loosen wall-of-text Chinese prose, keep light Markdown.
    static func prepare(_ raw: String) -> String {
        var s = raw
            .replacingOccurrences(of: "\r\n", with: "\n")
            .replacingOccurrences(of: "\r", with: "\n")
        s = s.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !s.isEmpty else { return s }
        if !s.contains("\n") {
            s = loosenDenseProse(s)
        }
        return softBreaksToHard(s)
    }

    static func blocks(from raw: String) -> [Block] {
        let prepared = prepare(raw)
            .replacingOccurrences(of: "  \n", with: "\n")
        guard !prepared.isEmpty else { return [] }

        var out: [Block] = []
        var paragraphBuf: [String] = []
        var inCode = false
        var codeBuf: [String] = []

        func flushParagraph() {
            let text = paragraphBuf.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
            paragraphBuf = []
            guard !text.isEmpty else { return }
            out.append(.paragraph(text))
        }

        for line in prepared.split(separator: "\n", omittingEmptySubsequences: false).map(String.init) {
            let trimmed = line.trimmingCharacters(in: .whitespaces)

            if trimmed.hasPrefix("```") {
                if inCode {
                    out.append(.code(codeBuf.joined(separator: "\n")))
                    codeBuf = []
                    inCode = false
                } else {
                    flushParagraph()
                    inCode = true
                }
                continue
            }
            if inCode {
                codeBuf.append(line)
                continue
            }

            if trimmed.isEmpty {
                flushParagraph()
                continue
            }

            if let heading = matchHeading(trimmed) {
                flushParagraph()
                out.append(.heading(heading))
                continue
            }

            if let bullet = matchBullet(trimmed) {
                flushParagraph()
                out.append(.bullet(bullet))
                continue
            }

            paragraphBuf.append(trimmed)
        }

        if inCode {
            out.append(.code(codeBuf.joined(separator: "\n")))
        }
        flushParagraph()
        return mergeAdjacentParagraphs(out)
    }

    // MARK: - Dense prose

    /// Insert paragraph breaks into Chinese LLM walls that use `·` / `：` as structure.
    private static func loosenDenseProse(_ s: String) -> String {
        var out = s
        let replacements: [(String, String)] = [
            ("。· ", "。\n\n· "),
            ("；· ", "；\n· "),
            ("！· ", "！\n\n· "),
            ("：· ", "：\n· "),
            ("。- ", "。\n\n- "),
            ("。* ", "。\n\n* "),
        ]
        for (from, to) in replacements {
            out = out.replacingOccurrences(of: from, with: to)
        }

        // 。标签： → new paragraph before short section labels
        if let regex = try? NSRegularExpression(
            pattern: #"([。！？])([^。！？\n]{1,16}[：:])"#,
            options: []
        ) {
            let range = NSRange(out.startIndex..<out.endIndex, in: out)
            out = regex.stringByReplacingMatches(
                in: out,
                options: [],
                range: range,
                withTemplate: "$1\n\n$2"
            )
        }

        // Standalone middle-dot clauses: " · 数据源：" mid-sentence list
        if let regex = try? NSRegularExpression(
            pattern: #"\s·\s([^·\n]{2,40}[：:])"#,
            options: []
        ) {
            let range = NSRange(out.startIndex..<out.endIndex, in: out)
            out = regex.stringByReplacingMatches(
                in: out,
                options: [],
                range: range,
                withTemplate: "\n\n· $1"
            )
        }

        return out
    }

    /// Markdown treats single `\n` as space; convert to hard breaks.
    private static func softBreaksToHard(_ s: String) -> String {
        let parts = s.components(separatedBy: "\n\n")
        return parts
            .map { $0.replacingOccurrences(of: "\n", with: "  \n") }
            .joined(separator: "\n\n")
    }

    private static func matchHeading(_ line: String) -> String? {
        if line.hasPrefix("### ") { return String(line.dropFirst(4)) }
        if line.hasPrefix("## ") { return String(line.dropFirst(3)) }
        if line.hasPrefix("# ") { return String(line.dropFirst(2)) }
        return nil
    }

    private static func matchBullet(_ line: String) -> String? {
        let prefixes = ["- ", "* ", "• ", "· ", "– "]
        for p in prefixes where line.hasPrefix(p) {
            return String(line.dropFirst(p.count))
        }
        // 1. 2. ordered
        if let regex = try? NSRegularExpression(pattern: #"^\d+[\.、]\s+"#, options: []),
           let match = regex.firstMatch(in: line, options: [], range: NSRange(line.startIndex..<line.endIndex, in: line)),
           let range = Range(match.range, in: line) {
            return String(line[range.upperBound...])
        }
        return nil
    }

    private static func mergeAdjacentParagraphs(_ blocks: [Block]) -> [Block] {
        // Keep as-is; splitting already did the job.
        blocks
    }
}

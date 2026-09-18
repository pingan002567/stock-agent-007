import Foundation

/// Turns assistant answer text into readable blocks for bubble / detail views.
/// Block grammar mirrors desktop `MarkdownRenderer.tsx` for visual parity.
enum AnswerFormatter {
    enum Block: Equatable {
        case heading(level: Int, text: String)
        case paragraph(String)
        case unorderedList([String])
        case orderedList([String])
        case code(String)
        case table(headers: [String], rows: [[String]])
        case horizontalRule
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

        // Split on fenced code first (same as desktop MarkdownRenderer).
        var out: [Block] = []
        let outerParts = splitKeepingDelimiters(prepared, pattern: #"```[\s\S]*?```"#)
        for part in outerParts {
            let trimmedPart = part.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmedPart.isEmpty else { continue }
            if trimmedPart.hasPrefix("```") {
                out.append(.code(stripFence(trimmedPart)))
            } else {
                out.append(contentsOf: parseNonCode(part))
            }
        }
        return out
    }

    // MARK: - Non-code line groups (desktop parity)

    private static func parseNonCode(_ part: String) -> [Block] {
        let lines = part.split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
        var blocks: [Block] = []
        var i = 0

        while i < lines.count {
            let trimmed = lines[i].trimmingCharacters(in: .whitespaces)
            if trimmed.isEmpty {
                i += 1
                continue
            }

            if let heading = matchHeading(trimmed) {
                blocks.append(.heading(level: heading.level, text: heading.text))
                i += 1
                continue
            }

            if isHorizontalRule(trimmed) {
                blocks.append(.horizontalRule)
                i += 1
                continue
            }

            // Table: consecutive | / tab lines with a separator row
            if (trimmed.contains("|") || trimmed.contains("\t")),
               i + 1 < lines.count,
               lines[i + 1].contains("|") || lines[i + 1].contains("\t") {
                var tableLines: [String] = [trimmed]
                i += 1
                while i < lines.count, lines[i].contains("|") || lines[i].contains("\t") {
                    tableLines.append(lines[i].trimmingCharacters(in: .whitespaces))
                    i += 1
                }
                if tableLines.contains(where: isTableSep) {
                    if let table = parseTable(tableLines) {
                        blocks.append(table)
                    } else {
                        blocks.append(.paragraph(tableLines.joined(separator: "\n")))
                    }
                } else {
                    blocks.append(.paragraph(tableLines.joined(separator: "\n")))
                }
                continue
            }

            // Ordered list
            if matchesOrdered(trimmed) {
                var items: [String] = []
                while i < lines.count {
                    let l = lines[i].trimmingCharacters(in: .whitespaces)
                    if matchesOrdered(l) {
                        items.append(stripOrderedPrefix(l))
                        i += 1
                    } else if l.isEmpty {
                        var j = i + 1
                        while j < lines.count, lines[j].trimmingCharacters(in: .whitespaces).isEmpty {
                            j += 1
                        }
                        if j < lines.count, matchesOrdered(lines[j].trimmingCharacters(in: .whitespaces)) {
                            i = j
                        } else {
                            break
                        }
                    } else {
                        break
                    }
                }
                blocks.append(.orderedList(items))
                continue
            }

            // Unordered list
            if matchesUnordered(trimmed) {
                var items: [String] = []
                while i < lines.count {
                    let l = lines[i].trimmingCharacters(in: .whitespaces)
                    if matchesUnordered(l) {
                        items.append(stripUnorderedPrefix(l))
                        i += 1
                    } else if l.isEmpty {
                        var j = i + 1
                        while j < lines.count, lines[j].trimmingCharacters(in: .whitespaces).isEmpty {
                            j += 1
                        }
                        if j < lines.count, matchesUnordered(lines[j].trimmingCharacters(in: .whitespaces)) {
                            i = j
                        } else {
                            break
                        }
                    } else {
                        break
                    }
                }
                blocks.append(.unorderedList(items))
                continue
            }

            var paraLines: [String] = []
            while i < lines.count {
                let t = lines[i].trimmingCharacters(in: .whitespaces)
                if t.isEmpty { break }
                if t.contains("|") {
                    var peek = i + 1
                    while peek < lines.count, lines[peek].trimmingCharacters(in: .whitespaces).isEmpty {
                        peek += 1
                    }
                    if peek < lines.count, lines[peek].trimmingCharacters(in: .whitespaces).contains("|") {
                        break
                    }
                }
                if matchHeading(t) != nil || matchesOrdered(t) || matchesUnordered(t) || isHorizontalRule(t) {
                    break
                }
                paraLines.append(lines[i])
                i += 1
            }
            let para = paraLines
                .map { $0.trimmingCharacters(in: .whitespaces) }
                .joined(separator: "\n")
                .trimmingCharacters(in: .whitespacesAndNewlines)
            if !para.isEmpty {
                blocks.append(.paragraph(para))
            }
        }
        return blocks
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

    /// Markdown treats single `\n` as space; convert to hard breaks (inline path).
    private static func softBreaksToHard(_ s: String) -> String {
        let parts = s.components(separatedBy: "\n\n")
        return parts
            .map { $0.replacingOccurrences(of: "\n", with: "  \n") }
            .joined(separator: "\n\n")
    }

    // MARK: - Matchers

    private static func matchHeading(_ line: String) -> (level: Int, text: String)? {
        guard let regex = try? NSRegularExpression(pattern: #"^(#{1,4})\s+(.+)$"#, options: []),
              let match = regex.firstMatch(
                  in: line,
                  options: [],
                  range: NSRange(line.startIndex..<line.endIndex, in: line)
              ),
              match.numberOfRanges == 3,
              let hashesRange = Range(match.range(at: 1), in: line),
              let textRange = Range(match.range(at: 2), in: line)
        else { return nil }
        return (line[hashesRange].count, String(line[textRange]))
    }

    private static func isHorizontalRule(_ line: String) -> Bool {
        guard let regex = try? NSRegularExpression(pattern: #"^[-*_]{3,}$"#, options: []) else {
            return false
        }
        let range = NSRange(line.startIndex..<line.endIndex, in: line)
        return regex.firstMatch(in: line, options: [], range: range) != nil
    }

    private static func matchesOrdered(_ line: String) -> Bool {
        guard let regex = try? NSRegularExpression(pattern: #"^\d+[\.、]\s+"#, options: []) else {
            return false
        }
        let range = NSRange(line.startIndex..<line.endIndex, in: line)
        return regex.firstMatch(in: line, options: [], range: range) != nil
    }

    private static func stripOrderedPrefix(_ line: String) -> String {
        guard let regex = try? NSRegularExpression(pattern: #"^\d+[\.、]\s+"#, options: []),
              let match = regex.firstMatch(
                  in: line,
                  options: [],
                  range: NSRange(line.startIndex..<line.endIndex, in: line)
              ),
              let range = Range(match.range, in: line)
        else { return line }
        return String(line[range.upperBound...])
    }

    private static func matchesUnordered(_ line: String) -> Bool {
        // Desktop: ^[-*+]\s ; also accept · / • for Chinese LLM output
        let prefixes = ["- ", "* ", "+ ", "• ", "· ", "– "]
        return prefixes.contains(where: { line.hasPrefix($0) })
    }

    private static func stripUnorderedPrefix(_ line: String) -> String {
        let prefixes = ["- ", "* ", "+ ", "• ", "· ", "– "]
        for p in prefixes where line.hasPrefix(p) {
            return String(line.dropFirst(p.count))
        }
        return line
    }

    private static func isTableSep(_ line: String) -> Bool {
        let stripped = line.replacingOccurrences(of: "|", with: "").trimmingCharacters(in: .whitespaces)
        guard !stripped.isEmpty else { return false }
        return stripped.unicodeScalars.allSatisfy { ch in
            ch == " " || ch == ":" || ch == "-" || ch == "\t"
        }
    }

    private static func parseTable(_ lines: [String]) -> Block? {
        guard !lines.isEmpty else { return nil }
        let headers = splitTableRow(lines[0])
        guard !headers.isEmpty else { return nil }
        var rows: [[String]] = []
        for line in lines.dropFirst() {
            if isTableSep(line) { continue }
            let cells = splitTableRow(line)
            if !cells.isEmpty { rows.append(cells) }
        }
        return .table(headers: headers, rows: rows)
    }

    private static func splitTableRow(_ line: String) -> [String] {
        line.split(separator: "|", omittingEmptySubsequences: false)
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
    }

    private static func stripFence(_ fenced: String) -> String {
        var body = fenced
        if body.hasPrefix("```") {
            if let nl = body.firstIndex(of: "\n") {
                body = String(body[body.index(after: nl)...])
            } else {
                body = String(body.dropFirst(3))
            }
        }
        if body.hasSuffix("```") {
            body = String(body.dropLast(3))
        }
        return body.trimmingCharacters(in: CharacterSet(charactersIn: "\n"))
    }

    /// Split string while keeping regex matches as their own parts (desktop `split(/(```...)/)`).
    private static func splitKeepingDelimiters(_ text: String, pattern: String) -> [String] {
        guard let regex = try? NSRegularExpression(pattern: pattern, options: []) else {
            return [text]
        }
        let ns = text as NSString
        let matches = regex.matches(in: text, options: [], range: NSRange(location: 0, length: ns.length))
        guard !matches.isEmpty else { return [text] }

        var parts: [String] = []
        var cursor = 0
        for match in matches {
            if match.range.location > cursor {
                parts.append(ns.substring(with: NSRange(location: cursor, length: match.range.location - cursor)))
            }
            parts.append(ns.substring(with: match.range))
            cursor = match.range.location + match.range.length
        }
        if cursor < ns.length {
            parts.append(ns.substring(from: cursor))
        }
        return parts
    }
}

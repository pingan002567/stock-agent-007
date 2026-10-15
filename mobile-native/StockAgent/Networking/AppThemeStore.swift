import SwiftUI
import UIKit

@MainActor
final class AppThemeStore: ObservableObject {
    static let shared = AppThemeStore()

    enum SchemeOption: String, CaseIterable, Identifiable {
        case system, light, dark
        var id: String { rawValue }
        var title: String {
            switch self {
            case .system: return "跟随系统"
            case .light: return "浅色"
            case .dark: return "深色"
            }
        }
        var preferred: ColorScheme? {
            switch self {
            case .system: return nil
            case .light: return .light
            case .dark: return .dark
            }
        }
    }

    struct Preset: Identifiable, Hashable {
        let id: String
        let name: String
        let hex: String
    }

    static let presets: [Preset] = [
        .init(id: "brand", name: "柴犬棕", hex: "#5C4033"),
        .init(id: "blue", name: "系统蓝", hex: "#007AFF"),
        .init(id: "teal", name: "青绿", hex: "#0A7C6B"),
        .init(id: "orange", name: "橙红", hex: "#E85D04"),
        .init(id: "indigo", name: "靛蓝", hex: "#4F46E5"),
        .init(id: "rose", name: "玫红", hex: "#E11D48"),
        .init(id: "forest", name: "森林", hex: "#2F6B3A"),
        .init(id: "slate", name: "石板", hex: "#475569"),
    ]

    @Published var accentHex: String {
        didSet {
            UserDefaults.standard.set(accentHex, forKey: Keys.accent)
        }
    }

    @Published var scheme: SchemeOption {
        didSet { UserDefaults.standard.set(scheme.rawValue, forKey: Keys.scheme) }
    }

    private enum Keys {
        static let accent = "stockagent.themeAccentHex"
        static let scheme = "stockagent.themeScheme"
    }

    private init() {
        let hex = UserDefaults.standard.string(forKey: Keys.accent) ?? Self.presets[0].hex
        accentHex = Self.normalizeHex(hex) ?? Self.presets[0].hex
        if let raw = UserDefaults.standard.string(forKey: Keys.scheme),
           let opt = SchemeOption(rawValue: raw) {
            scheme = opt
        } else {
            scheme = .system
        }
    }

    var accentColor: Color {
        Color(hex: accentHex) ?? Color(hex: Self.presets[0].hex)!
    }

    var selectedPresetId: String? {
        Self.presets.first(where: { Self.normalizeHex($0.hex) == Self.normalizeHex(accentHex) })?.id
    }

    func applyPreset(_ preset: Preset) {
        accentHex = Self.normalizeHex(preset.hex) ?? preset.hex
    }

    func setCustomColor(_ color: Color) {
        if let hex = color.toHexString() {
            accentHex = hex
        }
    }

    static func normalizeHex(_ raw: String) -> String? {
        var s = raw.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        if s.hasPrefix("#") { s.removeFirst() }
        guard s.count == 6, s.allSatisfy({ $0.isHexDigit }) else { return nil }
        return "#\(s)"
    }
}

extension Color {
    init?(hex: String) {
        var s = hex.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        if s.hasPrefix("#") { s.removeFirst() }
        guard s.count == 6, let value = UInt64(s, radix: 16) else { return nil }
        let r = Double((value >> 16) & 0xFF) / 255
        let g = Double((value >> 8) & 0xFF) / 255
        let b = Double(value & 0xFF) / 255
        self.init(.sRGB, red: r, green: g, blue: b, opacity: 1)
    }

    func toHexString() -> String? {
        let ui = UIColor(self)
        var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
        if ui.getRed(&r, green: &g, blue: &b, alpha: &a) {
            return String(format: "#%02X%02X%02X", Int(r * 255), Int(g * 255), Int(b * 255))
        }
        var w: CGFloat = 0
        guard ui.getWhite(&w, alpha: &a) else { return nil }
        let v = Int(w * 255)
        return String(format: "#%02X%02X%02X", v, v, v)
    }
}

import Foundation
import UIKit
import SwiftUI

/// Persists chat wallpaper and readability overlay.
@MainActor
final class ChatAppearanceStore: ObservableObject {
    static let shared = ChatAppearanceStore()

    @Published private(set) var backgroundImage: UIImage?
    /// Dark overlay on top of wallpaper so bubbles stay readable (0…0.85).
    @Published var dimOpacity: Double {
        didSet { UserDefaults.standard.set(dimOpacity, forKey: Keys.dim) }
    }

    private enum Keys {
        static let dim = "stockagent.chatBgDim"
        static let fileName = "chat-background.jpg"
    }

    private var fileURL: URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent(Keys.fileName)
    }

    private init() {
        let stored = UserDefaults.standard.object(forKey: Keys.dim) as? Double
        dimOpacity = stored ?? 0.35
        loadFromDisk()
    }

    var hasBackground: Bool { backgroundImage != nil }

    func setBackground(image: UIImage) {
        let normalized = Self.normalized(image)
        backgroundImage = normalized
        if let data = normalized.jpegData(compressionQuality: 0.85) {
            try? data.write(to: fileURL, options: .atomic)
        }
    }

    func setBackground(data: Data) {
        guard let image = UIImage(data: data) else { return }
        setBackground(image: image)
    }

    func clearBackground() {
        backgroundImage = nil
        try? FileManager.default.removeItem(at: fileURL)
    }

    private func loadFromDisk() {
        guard FileManager.default.fileExists(atPath: fileURL.path),
              let data = try? Data(contentsOf: fileURL),
              let image = UIImage(data: data) else {
            backgroundImage = nil
            return
        }
        backgroundImage = image
    }

    /// Cap longest side to keep Documents lean.
    private static func normalized(_ image: UIImage) -> UIImage {
        let maxSide: CGFloat = 2048
        let size = image.size
        let longest = max(size.width, size.height)
        guard longest > maxSide, longest > 0 else { return image }
        let scale = maxSide / longest
        let newSize = CGSize(width: size.width * scale, height: size.height * scale)
        let renderer = UIGraphicsImageRenderer(size: newSize)
        return renderer.image { _ in
            image.draw(in: CGRect(origin: .zero, size: newSize))
        }
    }
}

enum ChatClipboard {
    static func copy(_ text: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        UIPasteboard.general.string = trimmed
        UINotificationFeedbackGenerator().notificationOccurred(.success)
    }
}

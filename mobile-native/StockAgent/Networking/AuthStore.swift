import Foundation
import Security

/// Persists connection profile. Token in Keychain; base URL in UserDefaults.
/// Does not auto-connect — caller must probe after user taps Connect.
@MainActor
final class AuthStore: ObservableObject {
    static let shared = AuthStore()

    private let urlKey = "stockagent.remoteUrl"
    private let lastSuccessURLKey = "stockagent.lastSuccessfulUrl"
    private let keychainService = "com.stockagent.app"
    private let keychainAccount = "accessToken"

    @Published private(set) var remoteURL: String
    @Published private(set) var lastSuccessfulURL: String
    @Published private(set) var accessToken: String
    @Published var isConnected: Bool = false

    private init() {
        remoteURL = UserDefaults.standard.string(forKey: urlKey) ?? ""
        lastSuccessfulURL = UserDefaults.standard.string(forKey: lastSuccessURLKey) ?? ""
        accessToken = Self.loadToken(service: keychainService, account: keychainAccount) ?? ""
    }

    var hasSavedProfile: Bool {
        !remoteURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    func saveDraft(url: String, token: String) {
        let trimmedURL = url.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedToken = token.trimmingCharacters(in: .whitespacesAndNewlines)
        remoteURL = trimmedURL
        accessToken = trimmedToken
        UserDefaults.standard.set(trimmedURL, forKey: urlKey)
        Self.saveToken(trimmedToken, service: keychainService, account: keychainAccount)
    }

    func recordSuccessfulURL(_ url: String) {
        let trimmed = url.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        lastSuccessfulURL = trimmed
        UserDefaults.standard.set(trimmed, forKey: lastSuccessURLKey)
    }

    func markConnected() {
        isConnected = true
    }

    func disconnect() {
        isConnected = false
    }

    func clearCredentials() {
        remoteURL = ""
        accessToken = ""
        isConnected = false
        UserDefaults.standard.removeObject(forKey: urlKey)
        Self.deleteToken(service: keychainService, account: keychainAccount)
    }

    private static func saveToken(_ token: String, service: String, account: String) {
        deleteToken(service: service, account: account)
        guard !token.isEmpty, let data = token.data(using: .utf8) else { return }
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ]
        SecItemAdd(query as CFDictionary, nil)
    }

    private static func loadToken(service: String, account: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        guard status == errSecSuccess, let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private static func deleteToken(service: String, account: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(query as CFDictionary)
    }
}

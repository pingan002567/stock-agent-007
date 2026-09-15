import Foundation
import UIKit
import UserNotifications

@MainActor
final class PushNotificationManager: NSObject, ObservableObject {
    static let shared = PushNotificationManager()

    @Published private(set) var authorizationStatus: UNAuthorizationStatus = .notDetermined
    @Published private(set) var deviceTokenHex: String?

    private var pendingDeepLinkSymbol: String?

    func configure() {
        UNUserNotificationCenter.current().delegate = self
        UIApplication.shared.registerForRemoteNotifications()
        refreshStatus()
    }

    func requestAuthorizationAndRegister() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge]) { granted, _ in
            Task { @MainActor in
                self.refreshStatus()
                if granted {
                    UIApplication.shared.registerForRemoteNotifications()
                }
            }
        }
    }

    func refreshStatus() {
        UNUserNotificationCenter.current().getNotificationSettings { settings in
            Task { @MainActor in
                self.authorizationStatus = settings.authorizationStatus
            }
        }
    }

    func didRegister(deviceToken: Data) {
        let hex = deviceToken.map { String(format: "%02x", $0) }.joined()
        deviceTokenHex = hex
        Task {
            guard APIClient.shared.isConfigured else { return }
            #if DEBUG
            let env = "sandbox"
            #else
            let env = "production"
            #endif
            try? await APIClient.shared.registerAPNsDevice(token: hex, environment: env)
        }
    }

    func didFailToRegister(error: Error) {
        // Keep silent; Settings can show status later.
        _ = error
    }

    func handleNotificationUserInfo(_ userInfo: [AnyHashable: Any]) {
        if let symbol = userInfo["symbol"] as? String {
            pendingDeepLinkSymbol = symbol
            NotificationCenter.default.post(
                name: .stockAgentOpenMonitor,
                object: nil,
                userInfo: ["symbol": symbol]
            )
        } else {
            NotificationCenter.default.post(name: .stockAgentOpenMonitor, object: nil)
        }
    }

    func consumePendingSymbol() -> String? {
        defer { pendingDeepLinkSymbol = nil }
        return pendingDeepLinkSymbol
    }
}

extension PushNotificationManager: UNUserNotificationCenterDelegate {
    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        completionHandler([.banner, .sound, .badge])
    }

    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        let info = response.notification.request.content.userInfo
        Task { @MainActor in
            self.handleNotificationUserInfo(info)
        }
        completionHandler()
    }
}

extension Notification.Name {
    static let stockAgentOpenMonitor = Notification.Name("stockAgentOpenMonitor")
}

final class AppDelegate: NSObject, UIApplicationDelegate {
    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        Task { @MainActor in
            PushNotificationManager.shared.configure()
        }
        return true
    }

    func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        Task { @MainActor in
            PushNotificationManager.shared.didRegister(deviceToken: deviceToken)
        }
    }

    func application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: Error) {
        Task { @MainActor in
            PushNotificationManager.shared.didFailToRegister(error: error)
        }
    }
}

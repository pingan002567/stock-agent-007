import Foundation
import UIKit
import UserNotifications

@MainActor
final class PushNotificationManager: NSObject, ObservableObject {
    static let shared = PushNotificationManager()

    @Published private(set) var authorizationStatus: UNAuthorizationStatus = .notDetermined
    @Published private(set) var deviceTokenHex: String?

    private var pendingUserInfo: [AnyHashable: Any]?

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
        _ = error
    }

    func handleNotificationUserInfo(_ userInfo: [AnyHashable: Any]) {
        pendingUserInfo = userInfo
        let kind = (userInfo["kind"] as? String) ?? ""
        if kind == "scheduled_task" {
            var info: [AnyHashable: Any] = ["kind": "scheduled_task"]
            if let sessionId = userInfo["session_id"] as? String { info["session_id"] = sessionId }
            if let reportId = userInfo["report_id"] as? String { info["report_id"] = reportId }
            if let taskId = userInfo["task_id"] as? String { info["task_id"] = taskId }
            NotificationCenter.default.post(
                name: .stockAgentOpenScheduledTask,
                object: nil,
                userInfo: info
            )
            return
        }

        let eventId = (userInfo["event_id"] as? String)
            ?? (userInfo["eventId"] as? String)
        let symbol = userInfo["symbol"] as? String
        var info: [AnyHashable: Any] = [:]
        if let eventId { info["event_id"] = eventId }
        if let symbol { info["symbol"] = symbol }
        NotificationCenter.default.post(
            name: .stockAgentOpenMonitor,
            object: nil,
            userInfo: info.isEmpty ? nil : info
        )
    }

    func consumePendingUserInfo() -> [AnyHashable: Any]? {
        defer { pendingUserInfo = nil }
        return pendingUserInfo
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
    static let stockAgentOpenScheduledTask = Notification.Name("stockAgentOpenScheduledTask")
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

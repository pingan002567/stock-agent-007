import SwiftUI

struct ConnectivityBanner: View {
    @ObservedObject var reachability: NetworkReachability

    var body: some View {
        if let text = reachability.bannerText {
            HStack(spacing: 8) {
                Image(systemName: reachability.isOnline ? "exclamationmark.triangle.fill" : "wifi.slash")
                Text(text)
                    .font(.footnote.weight(.medium))
                Spacer(minLength: 0)
                if reachability.authFailureMessage != nil {
                    Button("知道了") {
                        reachability.clearAuthFailure()
                    }
                    .font(.footnote.bold())
                }
            }
            .foregroundStyle(.white)
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .frame(maxWidth: .infinity)
            .background(Color.orange.gradient)
        }
    }
}

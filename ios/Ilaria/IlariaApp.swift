import SwiftUI

@main
struct IlariaApp: App {
    @StateObject private var prefs = Prefs()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(prefs)
                .preferredColorScheme(.dark)
                .onOpenURL { url in
                    handleDeepLink(url)
                }
        }
    }

    private func handleDeepLink(_ url: URL) {
        guard url.scheme?.lowercased() == "ilaria" else { return }
        // ilaria://sync?url=https://….ngrok…  |  ilaria://connected?ip=…
        let host = (url.host ?? "").lowercased()
        let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        if host == "sync" {
            if let remote = items.first(where: { $0.name == "url" })?.value, !remote.isEmpty {
                prefs.baseUrl = Prefs.normalizeBase(remote)
            }
            return
        }
        if host == "connected" || host == "lan" {
            if let ip = items.first(where: { $0.name == "ip" })?.value, !ip.isEmpty {
                prefs.baseUrl = Prefs.normalizeBase(ip.contains("://") ? ip : "http://\(ip):8787")
            }
        }
    }
}

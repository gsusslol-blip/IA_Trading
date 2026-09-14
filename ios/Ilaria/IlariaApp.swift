import SwiftUI

@main
struct IlariaApp: App {
    @StateObject private var prefs = Prefs()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(prefs)
                .preferredColorScheme(.dark)
        }
    }
}

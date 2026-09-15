import AVFoundation
import Foundation
import UIKit

/// Executes allowlisted phone actions. User confirms calls/SMS in system UI.
enum PhoneHands {
    @discardableResult
    static func run(_ raw: [String: Any]) -> String? {
        let action = ((raw["action"] as? String) ?? "").lowercased()
        let target = (raw["target"] as? String) ?? ""
        let text = (raw["text"] as? String) ?? ""

        switch action {
        case "call":
            open(URL(string: "tel:\(target)"))
        case "sms":
            var url = "sms:\(target)"
            if !text.isEmpty {
                url += "?body=\(text.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? text)"
            }
            open(URL(string: url))
        case "whatsapp":
            let digits = target.filter(\.isNumber)
            var url = "https://wa.me/\(digits)"
            if !text.isEmpty {
                url += "?text=\(text.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? text)"
            }
            open(URL(string: url))
        case "maps", "navigate":
            let q = (target.isEmpty ? text : target)
                .addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ""
            open(URL(string: "http://maps.apple.com/?q=\(q)"))
        case "browser":
            let url = target.hasPrefix("http") ? target : (text.hasPrefix("http") ? text : "https://\(target)")
            open(URL(string: url))
        case "translate":
            let q = (text.isEmpty ? target : text)
                .addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ""
            if target.hasPrefix("http") {
                open(URL(string: target))
            } else {
                open(URL(string: "https://translate.google.com/?sl=auto&tl=es&text=\(q)&op=translate"))
            }
        case "search":
            let q = (target.isEmpty ? text : target)
                .addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ""
            open(URL(string: "https://www.google.com/search?q=\(q)"))
        case "youtube":
            let q = (target.isEmpty ? text : target)
                .addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ""
            open(URL(string: "https://www.youtube.com/results?search_query=\(q)"))
        case "music":
            let q = (target.isEmpty ? text : target)
                .addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ""
            if let spotify = URL(string: "spotify:search:\(q)"), UIApplication.shared.canOpenURL(spotify) {
                open(spotify)
            } else {
                open(URL(string: "https://open.spotify.com/search/\(q)"))
            }
        case "open_app":
            openApp(target.isEmpty ? text : target)
        case "torch":
            torch(on: target != "off")
        case "camera":
            // No public camera:// scheme on modern iOS — open Photos as fallback.
            open(URL(string: "photos-redirect://"))
            if let settings = URL(string: UIApplication.openSettingsURLString) {
                // Keep camera permission path discoverable if Photos scheme fails.
                _ = settings
            }
        case "gallery":
            open(URL(string: "photos-redirect://"))
        case "settings", "open_app_settings":
            if let url = URL(string: UIApplication.openSettingsURLString) {
                open(url)
            }
        case "wifi", "open_wifi_settings":
            open(URL(string: "App-Prefs:root=WIFI"))
            open(URL(string: UIApplication.openSettingsURLString))
        case "bluetooth":
            open(URL(string: UIApplication.openSettingsURLString))
        case "volume":
            // iOS blocks programmatic volume without UI; open Sounds settings.
            open(URL(string: UIApplication.openSettingsURLString))
            return "volume_hint"
        case "share":
            share(text.isEmpty ? target : text)
        case "clipboard":
            UIPasteboard.general.string = text.isEmpty ? target : text
        case "clipboard_get":
            return "clipboard:\(UIPasteboard.general.string ?? "")"
        case "alarm", "timer", "calendar", "contacts", "email":
            openSystem(action, target: target, text: text)
        case "screenshot":
            return "screenshot_hint"
        case "lock":
            return "lock_hint"
        case "clear_http", "refresh_device_snap":
            return action
        default:
            break
        }
        return nil
    }

    private static func openSystem(_ action: String, target: String, text: String) {
        switch action {
        case "calendar":
            open(URL(string: "calshow://"))
        case "contacts":
            open(URL(string: "contacts://"))
        case "email":
            var url = "mailto:\(target)"
            if !text.isEmpty {
                url += "?body=\(text.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? text)"
            }
            open(URL(string: url))
        case "alarm", "timer":
            open(URL(string: "clock-alarm://"))
            open(URL(string: "clock-timer://"))
        default:
            break
        }
    }

    private static func openApp(_ raw: String) {
        let hint = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !hint.isEmpty, !BankApps.blocked(hint) else { return }
        let aliases: [String: String] = [
            "whatsapp": "whatsapp://",
            "telegram": "tg://",
            "instagram": "instagram://",
            "youtube": "youtube://",
            "spotify": "spotify://",
            "maps": "maps://",
            "gmail": "googlegmail://",
            "chrome": "googlechrome://",
            "netflix": "nflx://",
            "discord": "discord://",
            "twitch": "twitch://",
        ]
        let key = hint.lowercased()
        if let scheme = aliases[key], let url = URL(string: scheme), UIApplication.shared.canOpenURL(url) {
            open(url)
            return
        }
        let q = hint.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? hint
        open(URL(string: "https://apps.apple.com/search?term=\(q)"))
    }

    private static func torch(on: Bool) {
        guard let device = AVCaptureDevice.default(for: .video),
              device.hasTorch
        else { return }
        do {
            try device.lockForConfiguration()
            if on {
                try device.setTorchModeOn(level: 1.0)
            } else {
                device.torchMode = .off
            }
            device.unlockForConfiguration()
        } catch {
            // ignore
        }
    }

    private static func share(_ text: String) {
        guard !text.isEmpty else { return }
        let av = UIActivityViewController(activityItems: [text], applicationActivities: nil)
        guard let scene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
              let root = scene.windows.first?.rootViewController
        else { return }
        root.present(av, animated: true)
    }

    private static func open(_ url: URL?) {
        guard let url else { return }
        DispatchQueue.main.async {
            UIApplication.shared.open(url, options: [:], completionHandler: nil)
        }
    }
}

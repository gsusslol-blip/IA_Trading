import Foundation
import UIKit

/// Talks to the PC-hosted Ilaria FastAPI when linked. Solo / local commands use PhoneLocal first.
@MainActor
final class Brain {
    private let prefs: Prefs
    private let session: URLSession

    init(prefs: Prefs) {
        self.prefs = prefs
        let cfg = URLSessionConfiguration.default
        cfg.timeoutIntervalForRequest = 90
        cfg.timeoutIntervalForResource = 120
        self.session = URLSession(configuration: cfg)
    }

    func login(user: String, password: String) async throws -> String {
        let body: [String: Any] = [
            "username": user.trimmingCharacters(in: .whitespaces),
            "password": password,
        ]
        let json = try await post("/api/login", body: body, auth: false)
        prefs.token = json["token"] as? String ?? ""
        if let profile = json["user"] as? [String: Any] {
            prefs.username = profile["username"] as? String ?? user
            prefs.displayName = profile["display_name"] as? String ?? ""
            prefs.city = profile["city"] as? String ?? ""
        }
        return prefs.displayName
    }

    func chat(_ message: String) async throws -> ChatOut {
        // Always prefer on-device routing for phone actions (parity with Android PhoneLocal).
        if let local = PhoneLocal.handle(raw: message, prefs: prefs) {
            return local
        }
        if prefs.token.isEmpty || prefs.solo {
            return ChatOut(text: PhoneLocal.fallback(prefs: prefs, linked: false))
        }
        guard prefs.resolveUrl("/api/chat") != nil else {
            return ChatOut(text: PhoneLocal.fallback(prefs: prefs, linked: false))
        }
        UIDevice.current.isBatteryMonitoringEnabled = true
        let battery = UIDevice.current.batteryLevel
        let device: [String: Any] = [
            "model": UIDevice.current.model,
            "app_version": Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0.0",
            "battery": battery >= 0 ? Int(battery * 100) : -1,
        ]
        // speak:false — iOS uses AVSpeech locally; avoid unused Piper render on the PC.
        let body: [String: Any] = [
            "message": message,
            "speak": false,
            "client": "ios",
            "device": device,
            "pack": "",
        ]
        do {
            let json = try await post("/api/chat", body: body, auth: true)
            let reply = json["reply"] as? String ?? "Sin respuesta."
            let phone = json["phone_actions"] as? [[String: Any]] ?? []
            return ChatOut(text: reply, phone: phone, fromPc: true)
        } catch {
            if let local = PhoneLocal.handle(raw: message, prefs: prefs) {
                return local
            }
            throw error
        }
    }

    private func post(_ path: String, body: [String: Any], auth: Bool) async throws -> [String: Any] {
        guard let url = prefs.resolveUrl(path) else {
            throw NSError(
                domain: "Ilaria",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey: "Falta la URL de la PC."],
            )
        }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        if auth, !prefs.token.isEmpty {
            req.setValue("Bearer \(prefs.token)", forHTTPHeaderField: "Authorization")
            req.setValue("jarvis_sid=\(prefs.token)", forHTTPHeaderField: "Cookie")
            req.setValue(prefs.token, forHTTPHeaderField: "X-Ilaria-Token")
        }
        req.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, resp) = try await session.data(for: req)
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        guard let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw NSError(domain: "Ilaria", code: code, userInfo: [NSLocalizedDescriptionKey: "JSON inválido"])
        }
        if code >= 400 {
            let detail = obj["detail"] as? String ?? "HTTP \(code)"
            throw NSError(domain: "Ilaria", code: code, userInfo: [NSLocalizedDescriptionKey: detail])
        }
        return obj
    }
}

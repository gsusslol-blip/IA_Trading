import Foundation
import UIKit

/// Shared preferences for LAN link + solo mode.
@MainActor
final class Prefs: ObservableObject {
    @Published var baseUrl: String {
        didSet { UserDefaults.standard.set(Self.normalizeBase(baseUrl), forKey: "base") }
    }
    @Published var token: String {
        didSet { UserDefaults.standard.set(token, forKey: "token") }
    }
    @Published var username: String {
        didSet { UserDefaults.standard.set(username, forKey: "username") }
    }
    @Published var displayName: String {
        didSet { UserDefaults.standard.set(displayName, forKey: "display") }
    }
    @Published var city: String {
        didSet { UserDefaults.standard.set(city, forKey: "city") }
    }
    @Published var solo: Bool {
        didSet { UserDefaults.standard.set(solo, forKey: "solo") }
    }
    @Published var telegramBot: String {
        didSet {
            UserDefaults.standard.set(
                telegramBot.trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: CharacterSet(charactersIn: "@")),
                forKey: "tg_bot"
            )
        }
    }

    init() {
        let ud = UserDefaults.standard
        baseUrl = ud.string(forKey: "base") ?? ""
        token = ud.string(forKey: "token") ?? ""
        username = ud.string(forKey: "username") ?? ""
        displayName = ud.string(forKey: "display") ?? ""
        city = ud.string(forKey: "city") ?? ""
        solo = ud.bool(forKey: "solo")
        telegramBot = ud.string(forKey: "tg_bot") ?? ""
    }

    var loggedIn: Bool { !token.isEmpty }
    var inSession: Bool { solo || loggedIn }

    static func normalizeBase(_ raw: String) -> String {
        var value = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        while value.hasSuffix("/") { value.removeLast() }
        if value.isEmpty { return "" }
        if !value.hasPrefix("http://") && !value.hasPrefix("https://") {
            value = "http://\(value)"
        }
        while value.hasSuffix("/") { value.removeLast() }
        return value
    }

    func resolveUrl(_ path: String) -> URL? {
        if path.hasPrefix("http://") || path.hasPrefix("https://") {
            return URL(string: path)
        }
        let base = Self.normalizeBase(baseUrl)
        guard !base.isEmpty else { return nil }
        let joined = path.hasPrefix("/") ? "\(base)\(path)" : "\(base)/\(path)"
        return URL(string: joined)
    }

    func logout() {
        token = ""
        solo = false
    }

    func facts() -> [String: String] {
        guard let raw = UserDefaults.standard.string(forKey: "facts"),
              let data = raw.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: String]
        else { return [:] }
        return obj
    }

    func putFact(key: String, value: String) {
        var next = facts()
        next[key.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()] =
            value.trimmingCharacters(in: .whitespacesAndNewlines)
        if let data = try? JSONSerialization.data(withJSONObject: next),
           let raw = String(data: data, encoding: .utf8) {
            UserDefaults.standard.set(raw, forKey: "facts")
        }
    }

    func notes() -> [String] {
        UserDefaults.standard.stringArray(forKey: "notes") ?? []
    }

    func addNote(_ text: String) {
        var items = notes()
        items.insert(text, at: 0)
        UserDefaults.standard.set(Array(items.prefix(80)), forKey: "notes")
    }
}

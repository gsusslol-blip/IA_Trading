import Foundation

struct ChatOut {
    var text: String
    var phone: [[String: Any]] = []
    var fromPc: Bool = false
}

/// Offline / local command router for iPhone (parity with Android PhoneLocal).
enum PhoneLocal {
    static func handle(raw: String, prefs: Prefs) -> ChatOut? {
        var text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if let r = try? NSRegularExpression(pattern: #"^(?:hey\s+)?ilaria\b[\s,.:\-]*"#, options: .caseInsensitive) {
            text = r.stringByReplacingMatches(in: text, range: NSRange(text.startIndex..., in: text), withTemplate: "")
                .trimmingCharacters(in: .whitespacesAndNewlines)
        }
        if text.isEmpty { return ChatOut(text: "Te escucho.") }
        let lower = text.lowercased()

        if lower.range(of: #"\b(ayuda|help|comandos)\b"#, options: .regularExpression) != nil {
            return ChatOut(text: "En iPhone: apps (no bancarias), Spotify/YouTube, linterna, mapas, llamadas, SMS/WhatsApp borrador, portapapeles, traducir, notas. Enlazá la PC por Wi‑Fi para el cerebro completo.")
        }
        if lower.range(of: #"\b(hora|fecha)\b"#, options: .regularExpression) != nil || ["ahora", "hora", "fecha"].contains(lower) {
            let f = DateFormatter()
            f.locale = Locale(identifier: "es_AR")
            f.dateFormat = "EEEE d 'de' MMMM, HH:mm"
            return ChatOut(text: f.string(from: Date()))
        }
        if lower.range(of: #"\b(linterna|torch)\b"#, options: .regularExpression) != nil {
            let off = lower.range(of: #"\b(apag|off)\b"#, options: .regularExpression) != nil
            return hands("torch", target: off ? "off" : "on", reply: "Listo.")
        }
        if lower.contains("camara") || lower.contains("cámara") {
            return hands("camera", reply: "Cámara.")
        }
        if lower.range(of: #"\b(wifi|wi-?fi)\b"#, options: .regularExpression) != nil {
            return hands("wifi", reply: "Wi‑Fi.")
        }
        if lower.contains("bluetooth") { return hands("bluetooth", reply: "Bluetooth.") }
        if lower.range(of: #"\b(ajustes|settings)\b"#, options: .regularExpression) != nil {
            return hands("settings", reply: "Ajustes.")
        }
        if lower.range(of: #"\b(silenci|mute)\b"#, options: .regularExpression) != nil {
            return hands("volume", target: "mute", reply: "Abrí Sonidos en Ajustes (iOS no deja mute silencioso a apps).")
        }
        if let m = lower.range(of: #"volumen\s+(\d{1,3})"#, options: .regularExpression) {
            let num = String(lower[m]).components(separatedBy: CharacterSet.decimalDigits.inverted).joined()
            return hands("volume", target: num, reply: "Volumen: usá los botones laterales o Ajustes.")
        }
        if lower.contains("captura") || lower.contains("screenshot") {
            return hands("screenshot", reply: "Captura: botón lateral + volumen arriba.")
        }
        if lower.contains("traduc") {
            let q = text.replacingOccurrences(of: #"(?i)^(?:traduc[ií]|traducir|translate)\s+"#, with: "", options: .regularExpression)
            return hands("translate", text: q, reply: "Traduzco.")
        }
        if lower.hasPrefix("copia ") || lower.hasPrefix("copiá ") || lower.hasPrefix("copiar ") {
            let body = text.replacingOccurrences(of: #"(?i)^(?:copi[aá]|copiar)\s*[:\-]?\s*"#, with: "", options: .regularExpression)
            return hands("clipboard", text: body, reply: "Copiado.")
        }
        if lower.contains("portapapeles") {
            return hands("clipboard_get", reply: "Leo el portapapeles.")
        }
        if let call = match(#"(?i)(?:llam[aá]|marca)\s+(?:al\s+|a\s+)?([+\d][\d\s\-()]{6,})"#, text) {
            let digits = call.replacingOccurrences(of: #"[^\d+]"#, with: "", options: .regularExpression)
            return hands("call", target: digits, reply: "Abro el marcador.")
        }
        if let wa = match(#"(?i)(?:whats?app|wpp)\s+(?:a|al)?\s*([+\d][\d\s\-]{7,18})\s*[:\-]\s*(.+)$"#, text) {
            let parts = wa.split(separator: "|", maxSplits: 1).map(String.init)
            if parts.count == 2 {
                return hands("whatsapp", target: parts[0].filter(\.isNumber), text: parts[1], reply: "WhatsApp borrador.")
            }
        }
        if let maps = match(#"(?i)^(?:c[oó]mo\s+llego(?:\s+a)?|mapas?|ruta(?:\s+a)?|ll[eé]vame\s+a)\s+(.+)$"#, text) {
            return hands("maps", target: maps, reply: "Mapas.")
        }
        if lower.hasPrefix("anotá ") || lower.hasPrefix("anota ") || lower.hasPrefix("nota:") {
            let body = text.replacingOccurrences(of: #"(?i)^(?:anot[aá]|nota[:\s]+)\s*"#, with: "", options: .regularExpression)
            prefs.addNote(body)
            return ChatOut(text: "Nota guardada en el iPhone.")
        }
        if ["notas", "mis notas"].contains(lower) {
            let lines = prefs.notes()
            return ChatOut(text: lines.isEmpty ? "No hay notas." : lines.enumerated().map { "\($0.offset + 1). \($0.element)" }.joined(separator: "\n"))
        }
        if text.lowercased().hasPrefix("http") {
            return hands("browser", target: text, reply: "Abro el link.")
        }
        if let opened = match(#"(?i)(?:abr[ií]|abrime|abrir|abre|open)\s+(?:la\s+|el\s+)?(.+)$"#, text) {
            if BankApps.blocked(opened) { return ChatOut(text: "No abro apps bancarias.") }
            let t = opened.lowercased()
            if t == "youtube" || t == "yt" {
                return hands("browser", target: "https://www.youtube.com", reply: "YouTube.")
            }
            if t == "gmail" || t == "correo" {
                return hands("browser", target: "https://mail.google.com", reply: "Gmail.")
            }
            return hands("open_app", target: opened, reply: "Abro \(opened).")
        }
        let bare = ["spotify", "whatsapp", "telegram", "instagram", "youtube", "chrome", "maps", "netflix"]
        if bare.contains(lower) {
            return hands("open_app", target: lower, reply: "Abro \(lower).")
        }
        return nil
    }

    static func fallback(prefs: Prefs, linked: Bool) -> String {
        let who = prefs.displayName.isEmpty ? (prefs.username.isEmpty ? "vos" : prefs.username) : prefs.displayName
        if linked { return "No pude completar eso en el iPhone. Probá de nuevo." }
        return "Estoy en el iPhone, \(who). Apps, notas y linterna van acá. Enlazá la PC (mismo Wi‑Fi) en Perfil."
    }

    private static func hands(_ action: String, target: String = "", text: String = "", reply: String) -> ChatOut {
        var obj: [String: Any] = ["action": action]
        if !target.isEmpty { obj["target"] = target }
        if !text.isEmpty { obj["text"] = text }
        return ChatOut(text: reply, phone: [obj])
    }

    private static func match(_ pattern: String, _ text: String) -> String? {
        guard let re = try? NSRegularExpression(pattern: pattern) else { return nil }
        let range = NSRange(text.startIndex..., in: text)
        guard let m = re.firstMatch(in: text, range: range), m.numberOfRanges > 1,
              let r = Range(m.range(at: 1), in: text)
        else { return nil }
        if m.numberOfRanges > 2, let r2 = Range(m.range(at: 2), in: text) {
            return "\(text[r])|\(text[r2])"
        }
        return String(text[r])
    }
}

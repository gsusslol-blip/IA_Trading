import Foundation

enum BankApps {
    private static let shortTokens = [
        "bank", "bna", "bbva", "hsbc", "icbc", "itau", "n26", "modo", "uala",
        "reba", "prex", "wise", "bind",
    ]
    private static let longNeedles = [
        "banco", "bancar", "banking", "mercadopago", "mercado pago",
        "brubank", "naranjax", "naranja x", "galicia", "santander",
        "paypal", "revolut", "homebanking", "home banking",
    ]

    static func fold(_ text: String) -> String {
        text.folding(options: .diacriticInsensitive, locale: .current).lowercased()
    }

    static func blocked(_ parts: String...) -> Bool {
        let blob = fold(parts.joined(separator: " "))
        if blob.isEmpty { return false }
        let packed = blob.replacingOccurrences(of: " ", with: "")
        for needle in longNeedles {
            let n = fold(needle)
            if blob.contains(n) || packed.contains(n.replacingOccurrences(of: " ", with: "")) {
                return true
            }
        }
        for token in shortTokens {
            if blob.range(of: "\\b\(token)\\b", options: .regularExpression) != nil {
                return true
            }
        }
        return false
    }
}

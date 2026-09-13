package app.gsuss.asistente

import java.text.Normalizer

/** Blocks bank / bank-wallet apps. Launch still uses the system UI. */
object BankApps {
    private val shortTokens = listOf(
        "bank", "bna", "bbva", "hsbc", "icbc", "itau", "n26", "modo", "uala",
        "reba", "prex", "wise", "bind",
    )
    private val longNeedles = listOf(
        "banco", "bancar", "banking", "mbanking", "mercadopago", "mercado pago",
        "brubank", "naranjax", "naranja x", "galicia", "santander", "hipotecario",
        "credicoop", "supervielle", "personalpay", "personal pay", "rebanking",
        "paypal", "revolut", "citibank", "openbank", "nubank", "cuentadni",
        "bnaplus", "banca movil", "bancamovil", "homebanking", "home banking",
        "walletnfcrel", "comafi", "patagoniabank",
    )

    fun fold(text: String): String {
        val nfd = Normalizer.normalize(text.lowercase(), Normalizer.Form.NFD)
        return nfd.replace("\\p{Mn}+".toRegex(), "")
    }

    fun blocked(vararg parts: String): Boolean {
        val blob = fold(parts.joinToString(" "))
        if (blob.isBlank()) return false
        val packed = blob.replace(" ", "")
        for (needle in longNeedles) {
            val n = fold(needle)
            if (n in blob || n.replace(" ", "") in packed) return true
        }
        for (token in shortTokens) {
            if (Regex("(^|[^a-z0-9])${Regex.escape(token)}([^a-z0-9]|$)").containsMatchIn(blob)) {
                return true
            }
        }
        return false
    }
}

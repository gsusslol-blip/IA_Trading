package app.gsuss.asistente

import android.content.Context
import android.content.Intent
import android.net.Uri

/**
 * Hybrid PC discovery: LAN UDP → last HTTPS prefs → Telegram deep link (human).
 */
object RemoteSync {
    const val SYNC_HOST = "sync"
    const val REQUEST_TEXT = "ILARIA_REQUEST_SYNC_URL"

    fun applyDeepLink(prefs: Prefs, uri: Uri?): Boolean {
        if (uri == null) return false
        if (!uri.scheme.equals("ilaria", ignoreCase = true)) return false
        val host = uri.host?.lowercase() ?: return false
        when (host) {
            SYNC_HOST -> {
                val url = uri.getQueryParameter("url")?.trim().orEmpty()
                if (url.isBlank()) return false
                prefs.baseUrl = prefs.normalizeBase(url)
                return true
            }
            "connected", "lan" -> {
                val ip = uri.getQueryParameter("ip")?.trim().orEmpty()
                if (ip.isBlank()) return false
                prefs.baseUrl = prefs.normalizeBase(
                    if (ip.contains("://")) ip else "http://$ip:8787",
                )
                return true
            }
        }
        return false
    }

    /**
     * Phase 1 LanFind → Phase 2 saved remote prefs probe → else null (UI opens Telegram).
     */
    fun resolveHybrid(context: Context, prefs: Prefs): String? {
        val found = LanFind.find(context)
        if (found != null && Brain.probe(found)) {
            prefs.baseUrl = prefs.normalizeBase(found)
            return prefs.baseUrl
        }
        val saved = prefs.normalizeBase(prefs.baseUrl)
        if (saved.isNotBlank() && !prefs.looksLikeRouter(saved) && Brain.probe(saved)) {
            return saved
        }
        return null
    }

    fun openTelegramSync(context: Context, botUsername: String) {
        val bot = botUsername.trim().removePrefix("@")
        val uri = if (bot.isNotBlank()) {
            Uri.parse("https://t.me/$bot?text=${Uri.encode(REQUEST_TEXT)}")
        } else {
            Uri.parse("https://t.me/")
        }
        context.startActivity(Intent(Intent.ACTION_VIEW, uri).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }
}

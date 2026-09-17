package app.gsuss.asistente

import android.content.Context

class Prefs(context: Context) {
    val appCtx: Context = context.applicationContext
    private val sp = appCtx.getSharedPreferences("ilaria", Context.MODE_PRIVATE)

    var baseUrl: String
        get() = sp.getString("base", "") ?: ""
        set(value) { sp.edit().putString("base", normalizeBase(value)).apply() }

    var token: String
        get() = sp.getString("token", "") ?: ""
        set(value) { sp.edit().putString("token", value).apply() }

    var username: String
        get() = sp.getString("username", "") ?: ""
        set(value) { sp.edit().putString("username", value).apply() }

    var displayName: String
        get() = sp.getString("display", "") ?: ""
        set(value) { sp.edit().putString("display", value).apply() }

    var city: String
        get() = sp.getString("city", "") ?: ""
        set(value) { sp.edit().putString("city", value).apply() }

    var packs: List<String>
        get() {
            val raw = sp.getString("packs", "diario") ?: "diario"
            return raw.split(",").map { it.trim() }.filter { it.isNotEmpty() }
        }
        set(value) { sp.edit().putString("packs", value.joinToString(",")).apply() }

    val loggedIn: Boolean
        get() = token.isNotBlank()

    fun normalizeBase(raw: String): String {
        var value = raw.trim().trimEnd('/')
        if (value.isEmpty()) return ""
        if (!value.startsWith("http://") && !value.startsWith("https://")) {
            value = "http://$value"
        }
        return value.trimEnd('/')
    }

    /** .1 on 192.168/10/172 is almost always the router, not the PC. */
    fun looksLikeRouter(raw: String): Boolean {
        val host = normalizeBase(raw)
            .substringAfter("://")
            .substringBefore("/")
            .substringBefore(":")
        val last = host.substringAfterLast('.', "").toIntOrNull() ?: return false
        return last == 1
    }

    fun resolveUrl(path: String): String {
        if (path.startsWith("http://") || path.startsWith("https://")) return path
        val base = normalizeBase(baseUrl)
        return if (path.startsWith("/")) "$base$path" else "$base/$path"
    }

    fun logout() {
        sp.edit()
            .remove("token")
            .apply()
        solo = false
    }

    var notesRev: Int
        get() = sp.getInt("notes_rev", 0)
        set(value) { sp.edit().putInt("notes_rev", value).apply() }

    var solo: Boolean
        get() = sp.getBoolean("solo", false)
        set(value) { sp.edit().putBoolean("solo", value).apply() }

    val inSession: Boolean
        get() = solo || token.isNotBlank()

    fun facts(): Map<String, String> {
        val raw = sp.getString("facts", "") ?: ""
        if (raw.isBlank()) return emptyMap()
        return try {
            val obj = org.json.JSONObject(raw)
            buildMap {
                val keys = obj.keys()
                while (keys.hasNext()) {
                    val key = keys.next()
                    put(key, obj.optString(key))
                }
            }
        } catch (_: Exception) {
            emptyMap()
        }
    }

    fun putFact(key: String, value: String) {
        val next = facts().toMutableMap()
        next[key.trim().lowercase()] = value.trim()
        saveFacts(next)
    }

    fun saveFacts(map: Map<String, String>) {
        val obj = org.json.JSONObject()
        map.forEach { (k, v) -> if (k.isNotBlank() && v.isNotBlank()) obj.put(k, v) }
        sp.edit().putString("facts", obj.toString()).apply()
    }

    fun enterSolo(user: String) {
        val who = user.trim().ifBlank { username.ifBlank { "ilaria" } }
        username = who
        if (displayName.isBlank()) displayName = who
        solo = true
    }

    fun unlinkPc() {
        sp.edit().remove("token").apply()
        solo = true
    }
}

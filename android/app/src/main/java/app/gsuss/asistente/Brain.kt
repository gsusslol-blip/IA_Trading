package app.gsuss.asistente

import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.media.MediaPlayer
import android.os.Build
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.sse.EventSource
import okhttp3.sse.EventSourceListener
import okhttp3.sse.EventSources
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

data class ChatOut(val text: String, val phone: List<JSONObject> = emptyList(), val fromPc: Boolean = false)

private fun phoneActions(json: JSONObject): List<JSONObject> {
    val arr = json.optJSONArray("phone_actions") ?: return emptyList()
    return (0 until arr.length()).map { arr.getJSONObject(it) }
}

/**
 * Talks to the PC-hosted Ilaria FastAPI when linked. The app also runs solo.
 */
class Brain(private val prefs: Prefs) {
    @Volatile
    private var http = buildHttp()
    private val jsonType = "application/json; charset=utf-8".toMediaType()
    @Volatile
    private var pulse = buildPulse()
    @Volatile
    private var sseHttp = buildSse()
    private var player: MediaPlayer? = null
    private var focusRequest: AudioFocusRequest? = null
    private val audioManager: AudioManager?
        get() = try {
            prefs.appCtx.getSystemService(AudioManager::class.java)
        } catch (_: Exception) {
            null
        }

    /** Drop keep-alive pools after clear_http maintenance from the PC. */
    fun rebuildClients() {
        http = buildHttp()
        pulse = buildPulse()
        sseHttp = buildSse()
    }

    private fun buildHttp(): OkHttpClient =
        OkHttpClient.Builder()
            .connectTimeout(20, TimeUnit.SECONDS)
            .readTimeout(90, TimeUnit.SECONDS)
            .build()

    private fun buildPulse(): OkHttpClient =
        OkHttpClient.Builder()
            .connectTimeout(3, TimeUnit.SECONDS)
            .readTimeout(3, TimeUnit.SECONDS)
            .build()

    private fun buildSse(): OkHttpClient =
        OkHttpClient.Builder()
            .connectTimeout(20, TimeUnit.SECONDS)
            .readTimeout(0, TimeUnit.MILLISECONDS)
            .writeTimeout(20, TimeUnit.SECONDS)
            .retryOnConnectionFailure(false)
            .build()

    fun login(user: String, password: String): String {
        val body = JSONObject()
            .put("username", user.trim())
            .put("password", password)
        val json = post("/api/login", body, auth = false)
        prefs.token = json.getString("token")
        val profile = json.getJSONObject("user")
        prefs.username = profile.optString("username")
        prefs.displayName = profile.optString("display_name")
        prefs.city = profile.optString("city")
        prefs.packs = packsFrom(profile.optJSONArray("packs"))
        return prefs.displayName
    }

    fun register(
        user: String,
        password: String,
        name: String,
        city: String,
        packs: List<String>,
        groqKey: String,
    ): String {
        val body = JSONObject()
            .put("username", user.trim())
            .put("password", password)
            .put("display_name", name.ifBlank { user })
            .put("address_as", name.ifBlank { user })
            .put("city", city)
            .put("packs", JSONArray(packs))
            .put("groq_key", groqKey)
        val json = post("/api/register", body, auth = false)
        prefs.token = json.getString("token")
        val profile = json.getJSONObject("user")
        prefs.username = profile.optString("username")
        prefs.displayName = profile.optString("display_name")
        prefs.city = profile.optString("city")
        prefs.packs = packsFrom(profile.optJSONArray("packs"))
        return prefs.displayName
    }

    fun welcome(): String {
        val json = get("/api/welcome-report")
        val text = json.optString("voice_text").ifBlank { json.optString("ui_display") }
        playUrl(json.optString("audio_url"))
        return text
    }

    fun reply(userText: String, speak: Boolean = true, device: JSONObject = JSONObject()): String {
        return replyStream(userText, speak, device) {}.text
    }

    /**
     * POST /api/chat/stream as SSE. [onToken] runs on OkHttp's thread.
     * Falls back to JSON /api/chat if the PC build has no stream route.
     */
    fun replyStream(
        userText: String,
        speak: Boolean = true,
        device: JSONObject = JSONObject(),
        onToken: (String) -> Unit,
    ): ChatOut {
        val body = JSONObject()
            .put("message", userText)
            .put("speak", speak)
            .put("client", "android")
            .put("device", device)
        return try {
            streamChat(body, onToken)
        } catch (first: Exception) {
            if (!streamMissing(first)) throw first
            val json = post("/api/chat", body, auth = true)
            val text = json.optString("reply").ifBlank { "Sin respuesta." }
            if (text.isNotBlank()) onToken(text)
            playUrl(json.optString("audio_url"))
            ChatOut(text, phoneActions(json), fromPc = true)
        }
    }

    private fun streamChat(body: JSONObject, onToken: (String) -> Unit): ChatOut {
        val req = Request.Builder()
            .url(prefs.resolveUrl("/api/chat/stream"))
            .header("Accept", "text/event-stream")
            .header("Cache-Control", "no-cache")
            .header("Authorization", "Bearer ${prefs.token}")
            .header("X-Ilaria-Token", prefs.token)
            .post(body.toString().toRequestBody(jsonType))
            .build()
        val latch = CountDownLatch(1)
        val finished = AtomicBoolean(false)
        val acc = StringBuilder()
        var reply = ""
        var audio = ""
        var phone = listOf<JSONObject>()
        var failure: Exception? = null
        fun finish() {
            if (finished.compareAndSet(false, true)) latch.countDown()
        }
        val listener = object : EventSourceListener() {
            override fun onEvent(eventSource: EventSource, id: String?, type: String?, data: String) {
                val event = (type ?: "message").lowercase()
                val payload = try {
                    JSONObject(data)
                } catch (_: Exception) {
                    return
                }
                when (event) {
                    "token" -> {
                        val piece = payload.optString("text")
                        if (piece.isNotEmpty()) {
                            acc.append(piece)
                            onToken(piece)
                        }
                    }
                    "error" -> {
                        failure = IllegalStateException(
                            payload.optString("detail").ifBlank { "Error en el stream." },
                        )
                        finish()
                    }
                    "done" -> {
                        reply = payload.optString("reply").ifBlank { acc.toString() }
                        audio = payload.optString("audio_url")
                        phone = phoneActions(payload)
                        eventSource.cancel()
                        finish()
                    }
                }
            }

            override fun onFailure(eventSource: EventSource, t: Throwable?, response: Response?) {
                val code = response?.code ?: 0
                val raw = try {
                    response?.body?.string().orEmpty()
                } catch (_: Exception) {
                    ""
                }
                val detail = try {
                    JSONObject(raw).optString("detail").ifBlank { raw }
                } catch (_: Exception) {
                    raw
                }
                failure = when {
                    t != null -> t as? Exception ?: IllegalStateException(t.message)
                    code in 400..599 -> IllegalStateException(detail.ifBlank { "HTTP $code" })
                    else -> IllegalStateException("Se cortó el stream.")
                }
                finish()
            }

            override fun onClosed(eventSource: EventSource) {
                if (reply.isBlank() && acc.isNotBlank()) reply = acc.toString()
                finish()
            }
        }
        val source = EventSources.createFactory(sseHttp).newEventSource(req, listener)
        val ok = latch.await(120, TimeUnit.SECONDS)
        source.cancel()
        if (!ok) throw IllegalStateException("La PC no terminó de hablar a tiempo.")
        failure?.let { throw it }
        val text = reply.ifBlank { acc.toString() }.ifBlank { "Sin respuesta." }
        playUrl(audio)
        return ChatOut(text, phone, fromPc = true)
    }

    private fun streamMissing(err: Exception): Boolean {
        val msg = err.message.orEmpty()
        return msg.contains("404") || msg.contains("405") || msg.contains("Not Found", ignoreCase = true)
    }

    fun mergeFacts(local: Map<String, String>): Map<String, String> {
        val obj = JSONObject()
        local.forEach { (k, v) -> obj.put(k, v) }
        val json = put("/api/memory/facts", JSONObject().put("facts", obj))
        val remote = json.optJSONObject("facts") ?: JSONObject()
        return buildMap {
            val keys = remote.keys()
            while (keys.hasNext()) {
                val key = keys.next()
                put(key, remote.optString(key))
            }
        }
    }

    fun fetchNotes(): NotesBundle {
        return NotesBundle.fromExport(get("/api/notes"))
    }

    fun getAlerts(after: Int): JSONObject {
        return get("/api/alerts?after=$after")
    }

    fun syncNotes(bundle: NotesBundle): NotesBundle {
        val arr = org.json.JSONArray()
        bundle.items.forEach { arr.put(it.toJson()) }
        val body = JSONObject()
            .put("rev", bundle.rev)
            .put("items", arr)
        return NotesBundle.fromExport(put("/api/notes/sync", body))
    }

    fun logoutRemote() {
        try {
            post("/api/logout", JSONObject(), auth = true)
        } catch (_: Exception) {
        }
        stopAudio()
        prefs.logout()
    }

    fun stopAudio() {
        try {
            player?.stop()
        } catch (_: Exception) {
        }
        player?.release()
        player = null
        abandonDuckFocus()
    }

    private fun requestDuckFocus() {
        val mgr = audioManager ?: return
        try {
            if (Build.VERSION.SDK_INT >= 26) {
                val attrs = AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ASSISTANCE_SONIFICATION)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build()
                val req = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)
                    .setAudioAttributes(attrs)
                    .setAcceptsDelayedFocusGain(false)
                    .setWillPauseWhenDucked(false)
                    .build()
                focusRequest = req
                mgr.requestAudioFocus(req)
            } else {
                @Suppress("DEPRECATION")
                mgr.requestAudioFocus(
                    null,
                    AudioManager.STREAM_MUSIC,
                    AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK,
                )
            }
        } catch (_: Exception) {
        }
    }

    private fun abandonDuckFocus() {
        val mgr = audioManager ?: return
        try {
            if (Build.VERSION.SDK_INT >= 26) {
                focusRequest?.let { mgr.abandonAudioFocusRequest(it) }
            } else {
                @Suppress("DEPRECATION")
                mgr.abandonAudioFocus(null)
            }
        } catch (_: Exception) {
        }
        focusRequest = null
    }

    private fun playUrl(path: String) {
        if (path.isBlank() || prefs.token.isBlank()) return
        val joined = prefs.resolveUrl(path)
        val tok = java.net.URLEncoder.encode(prefs.token, "UTF-8")
        val url = if ("?" in joined) "$joined&token=$tok" else "$joined?token=$tok"
        stopAudio()
        try {
            requestDuckFocus()
            val next = MediaPlayer()
            // SONIFICATION + MAY_DUCK: lower music briefly instead of pausing Spotify/YouTube.
            next.setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ASSISTANCE_SONIFICATION)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build(),
            )
            next.setDataSource(url)
            next.setOnPreparedListener { it.start() }
            next.setOnCompletionListener {
                it.release()
                if (player === it) player = null
                abandonDuckFocus()
            }
            next.setOnErrorListener { mp, _, _ ->
                mp.release()
                if (player === mp) player = null
                abandonDuckFocus()
                true
            }
            player = next
            next.prepareAsync()
        } catch (_: Exception) {
            stopAudio()
        }
    }

    private fun packsFrom(arr: JSONArray?): List<String> {
        if (arr == null) return listOf("diario")
        return buildList {
            for (i in 0 until arr.length()) add(arr.optString(i))
        }.ifEmpty { listOf("diario") }
    }

    private fun get(path: String): JSONObject {
        val req = Request.Builder()
            .url(prefs.resolveUrl(path))
            .header("Authorization", "Bearer ${prefs.token}")
            .header("X-Ilaria-Token", prefs.token)
            .get()
            .build()
        return execute(req)
    }

    private fun post(path: String, body: JSONObject, auth: Boolean): JSONObject {
        val builder = Request.Builder()
            .url(prefs.resolveUrl(path))
            .post(body.toString().toRequestBody(jsonType))
        if (auth) {
            builder.header("Authorization", "Bearer ${prefs.token}")
            builder.header("X-Ilaria-Token", prefs.token)
        }
        return execute(builder.build())
    }

    private fun put(path: String, body: JSONObject): JSONObject {
        val req = Request.Builder()
            .url(prefs.resolveUrl(path))
            .header("Authorization", "Bearer ${prefs.token}")
            .header("X-Ilaria-Token", prefs.token)
            .put(body.toString().toRequestBody(jsonType))
            .build()
        return execute(req)
    }

    private fun execute(req: Request): JSONObject {
        http.newCall(req).execute().use { resp ->
            val raw = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) {
                val detail = try {
                    JSONObject(raw).optString("detail").ifBlank { raw }
                } catch (_: Exception) {
                    raw
                }
                throw IllegalStateException(detail.ifBlank { "HTTP ${resp.code}" })
            }
            return if (raw.isBlank()) JSONObject() else JSONObject(raw)
        }
    }

    fun pingMe(): Boolean {
        if (prefs.token.isBlank()) return false
        val req = Request.Builder()
            .url(prefs.resolveUrl("/api/me"))
            .header("Authorization", "Bearer ${prefs.token}")
            .header("X-Ilaria-Token", prefs.token)
            .get()
            .build()
        return try {
            pulse.newCall(req).execute().use { it.isSuccessful }
        } catch (_: Exception) {
            false
        }
    }

    fun heartbeat(): Boolean {
        if (pingMe()) return true
        return probe(prefs.baseUrl)
    }

    companion object {
        fun probe(baseUrl: String): Boolean {
            val normalized = baseUrl.trim().trimEnd('/').let {
                when {
                    it.startsWith("http://") || it.startsWith("https://") -> it
                    else -> "http://$it"
                }
            }
            val client = OkHttpClient.Builder().connectTimeout(4, TimeUnit.SECONDS).build()
            val req = Request.Builder().url("$normalized/health").get().build()
            return try {
                client.newCall(req).execute().use { it.isSuccessful }
            } catch (_: Exception) {
                false
            }
        }
    }
}

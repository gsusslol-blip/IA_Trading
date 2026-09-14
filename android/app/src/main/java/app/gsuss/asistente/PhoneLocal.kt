package app.gsuss.asistente

import android.content.Context
import org.json.JSONObject
import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.util.Locale

/**
 * Runs on the phone without the PC. PhoneHands still executes the intents.
 * Mirrors everyday local commands from jarvis/local.py for offline/mobile use.
 */
object PhoneLocal {
    private val openRe = Regex(
        """(?:abr[ií]|abrime|abrir|abre|open|lanz[aá]|ejecut[aá]|and[aá]\s+a|quiero\s+que\s+abras?|sac[aá])\s+(?:la\s+|el\s+|app\s+(?:de\s+)?)?(.+)$""",
        RegexOption.IGNORE_CASE,
    )
    private val noteRe = Regex(
        """^(?:anot[aá]|nota[:\s]+|record[aá]\s+esto[:\s]*|tom[aá]\s+nota(?:\s+de(?:\s+que)?)?)\s*(.+)$""",
        setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL),
    )
    private val rememberRe = Regex(
        """^(?:acordate(?:\s+que)?|record[aá]\s+que)\s+(.+?)\s+(?:es|=|:)\s+(.+)$""",
        setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL),
    )
    private val callRe = Regex(
        """(?:llam[aá]|marca[lr]?|disc[aá])\s+(?:al\s+|a\s+)?([+\d][\d\s\-()]{6,})""",
        RegexOption.IGNORE_CASE,
    )
    private val smsRe = Regex(
        """(?:sms|mensaje(?:\s+de\s+texto)?)\s+(?:a|al)\s+([+\d][\d\s\-()]{6,})\s*[:\-]?\s*(.*)$""",
        setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL),
    )
    private val waRe = Regex(
        """(?:whats?app|wpp|wasap)\s+(?:a|al|para)?\s*([+\d][\d\s\-]{7,18})\s*[:\-]\s*(.+)$""",
        setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL),
    )
    private val mapsRe = Regex(
        """^(?:c[oó]mo\s+llego(?:\s+a)?|mapas?|ruta(?:\s+a)?|llevame\s+a|ll[eé]vame\s+a)\s+(.+)$""",
        RegexOption.IGNORE_CASE,
    )
    private val musicRe = Regex(
        """(?:poneme|pon[eé]|reproduc[ií]|reproducir|escuchar|play|tirame)\s+""" +
            """(?:a\s+reproducir\s+)?""" +
            """(?:un\s+tema\s+de\s+|una\s+canci[oó]n\s+(?:de\s+)?|la\s+canci[oó]n\s+(?:de\s+)?|""" +
            """el\s+tema\s+(?:de\s+)?|m[uú]sica\s+(?:de\s+)?)?""" +
            """(.+?)""" +
            """(?:\s+en\s+(?:el\s+)?(spotify|youtube))?\s*$""",
        RegexOption.IGNORE_CASE,
    )
    private val timerRe = Regex(
        """(?:timer|temporizador|avis[aá]me|record[aá]me)\s+(?:en\s+)?(\d+)\s*(min|mins|minuto|minutos|hora|horas)\b(?:\s+(?:para|que|:|de)\s*(.+))?""",
        RegexOption.IGNORE_CASE,
    )
    private val alarmRe = Regex(
        """\b(?:alarma|alarm)\s+(?:a\s+las\s+|para\s+las\s+|a\s+)?(\d{1,2})(?:[:\.](\d{2}))?\b""",
        RegexOption.IGNORE_CASE,
    )
    private val bareApps = setOf(
        "spotify", "whatsapp", "telegram", "instagram", "youtube", "tiktok",
        "chrome", "gmail", "maps", "netflix", "discord", "twitch",
    )

    fun handle(
        context: Context,
        raw: String,
        notes: NotesCache,
        prefs: Prefs,
    ): ChatOut? {
        val text = raw.replace(Regex("""^(?:hey\s+)?ilaria\b[\s,.:\-]*""", RegexOption.IGNORE_CASE), "").trim()
        if (text.isBlank()) return ChatOut("Te escucho.")
        val lower = text.lowercase(Locale.getDefault())

        if (Regex("""\b(ayuda|help|qu[eé] pod[eé]s|comandos)\b""").containsMatchIn(lower)) {
            return ChatOut(
                "En el celular: apps (no bancarias), Spotify/YouTube, linterna, cámara, mapas, " +
                    "llamadas, SMS/WhatsApp borrador, volumen, alarma/timer, wifi/bluetooth, " +
                    "portapapeles, traducir, notas. Con la PC en Wi‑Fi, pienso con Ilaria de ahí.",
            )
        }
        if (Regex("""\b(hora|fecha|qu[eé] d[ií]a)\b""").containsMatchIn(lower) || lower in setOf("ahora", "hora", "fecha")) {
            val zone = try {
                ZoneId.of("America/Argentina/Buenos_Aires")
            } catch (_: Exception) {
                ZoneId.systemDefault()
            }
            val now = ZonedDateTime.now(zone)
            val fmt = DateTimeFormatter.ofPattern("EEEE d 'de' MMMM, HH:mm", Locale("es", "AR"))
            return ChatOut(now.format(fmt))
        }
        if (Regex("""\b(linterna|flashlight|torch)\b""").containsMatchIn(lower)) {
            val off = Regex("""\b(apag|off|sac[aá])\b""").containsMatchIn(lower)
            return hands("torch", if (off) "off" else "on", "Listo.")
        }
        if (Regex("""\b(c[aá]mara|camera)\b""").containsMatchIn(lower) &&
            Regex("""\b(abr|sac[aá]|pon|tir[aá])\b""").containsMatchIn(lower)
        ) {
            return hands("camera", reply = "Cámara.")
        }
        if (Regex("""\b(galer[ií]a|fotos|photos)\b""").containsMatchIn(lower) &&
            Regex("""\b(abr|mostr)\b""").containsMatchIn(lower)
        ) {
            return hands("gallery", reply = "Galería.")
        }
        if (Regex("""\b(wifi|wi[\-\s]?fi)\b""").containsMatchIn(lower) &&
            Regex("""\b(abr|ajustes|config)\b""").containsMatchIn(lower)
        ) {
            return hands("open_wifi_settings", reply = "Wi‑Fi.")
        }
        if (Regex("""\b(bluetooth)\b""").containsMatchIn(lower)) {
            return hands("bluetooth", reply = "Bluetooth.")
        }
        if (Regex("""\b(ajustes|configuraci[oó]n|settings)\b""").containsMatchIn(lower)) {
            return hands("settings", reply = "Ajustes.")
        }
        if (Regex("""\b(silenci(?:ar|[oaá])|mute)\b""").containsMatchIn(lower)) {
            return hands("volume", "mute", "Silencio.")
        }
        val volN = Regex("""(?:volumen|volume)(?:\s+(?:al|a|en))?\s+(\d{1,3})""").find(lower)
        if (volN != null) return hands("volume", volN.groupValues[1], "Volumen ${volN.groupValues[1]}%.")
        if (Regex("""\b(sub[ií]|m[aá]s).{0,12}volumen|volumen.{0,12}(sub[ií]|m[aá]s)\b""").containsMatchIn(lower)) {
            return hands("volume", "up", "Subo volumen.")
        }
        if (Regex("""\b(baj[aá]|menos).{0,12}volumen|volumen.{0,12}(baj[aá]|menos)\b""").containsMatchIn(lower)) {
            return hands("volume", "down", "Bajo volumen.")
        }
        if (Regex("""\b(captura|screenshot)\b""").containsMatchIn(lower)) {
            return hands("screenshot", reply = "Power + Volumen abajo para capturar.")
        }
        if (Regex("""\b(bloque[aá]|lock).{0,12}(pantalla|tel[eé]fono|celular)\b""").containsMatchIn(lower)) {
            return hands("lock", reply = "Bloqueo.")
        }
        val clipSet = Regex("""^(?:copi[aá]|copiar)\s*[:\-]?\s+(.+)$""", setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL)).find(text)
        if (clipSet != null) {
            return hands("clipboard", text = clipSet.groupValues[1].trim(), reply = "Copiado.")
        }
        if (Regex("""\b(portapapeles|qu[eé]\s+copi[eé])\b""").containsMatchIn(lower)) {
            return hands("clipboard_get", reply = "Leo el portapapeles.")
        }
        val translate = Regex("""^(?:traduc[ií]|traducir|translate)\s+(.+)$""", RegexOption.IGNORE_CASE).find(text)
        if (translate != null) {
            return hands("translate", text = translate.groupValues[1].trim(), reply = "Traduzco.")
        }
        val yt = Regex("""^(?:busc[aá]|busca)\s+(?:en\s+)?youtube\s+(.+)$""", RegexOption.IGNORE_CASE).find(text)
        if (yt != null) return hands("youtube", yt.groupValues[1].trim(), "YouTube.")

        val alarm = alarmRe.find(lower)
        if (alarm != null) {
            val hh = alarm.groupValues[1]
            val mm = alarm.groupValues.getOrNull(2)?.ifBlank { "00" } ?: "00"
            return hands("alarm", "$hh:$mm", "Alarma $hh:$mm.")
        }
        val timer = timerRe.find(lower)
        if (timer != null) {
            var mins = timer.groupValues[1].toIntOrNull() ?: 5
            if (timer.groupValues[2].startsWith("hora")) mins *= 60
            return hands("timer", mins.toString(), "Timer $mins min.")
        }

        val call = callRe.find(text)
        if (call != null) return hands("call", call.groupValues[1].filter { it.isDigit() || it == '+' }, "Abro el marcador.")
        val sms = smsRe.find(text)
        if (sms != null) {
            return hands(
                "sms",
                sms.groupValues[1].filter { it.isDigit() || it == '+' },
                text = sms.groupValues.getOrNull(2)?.trim().orEmpty(),
                reply = "Borrador SMS.",
            )
        }
        val wa = waRe.find(text)
        if (wa != null) {
            return hands(
                "whatsapp",
                wa.groupValues[1].filter { it.isDigit() },
                text = wa.groupValues[2].trim(),
                reply = "WhatsApp borrador.",
            )
        }
        val maps = mapsRe.find(text)
        if (maps != null) return hands("maps", maps.groupValues[1].trim(), "Mapas.")

        if (Regex("""\b(contactos)\b""").containsMatchIn(lower)) return hands("contacts", reply = "Contactos.")
        if (Regex("""\b(calendario|agenda)\b""").containsMatchIn(lower)) return hands("calendar", reply = "Calendario.")

        val music = musicRe.find(text)
        if (music != null && !Regex("""\b(volumen|timer|alarma|linterna|recordatorio)\b""").containsMatchIn(lower)) {
            var query = music.groupValues[1].trim().trim('.', '!', '?')
            query = query.replace(Regex("""\s+en\s+(el\s+)?(spotify|youtube)$""", RegexOption.IGNORE_CASE), "").trim()
            query = query.replace(Regex("""^(spotify|youtube)\s+""", RegexOption.IGNORE_CASE), "").trim()
            val platform = music.groupValues.getOrNull(2)?.lowercase(Locale.getDefault()).orEmpty()
            val apps = setOf("spotify", "youtube", "whatsapp", "telegram", "instagram", "maps", "gmail", "chrome", "tiktok")
            when {
                query in setOf("spotify", "youtube", "musica", "música") -> {
                    val target = if ("youtube" in query) "youtube" else "spotify"
                    return hands("open_app", target, "Abro $target.")
                }
                query.isNotBlank() && query !in apps -> {
                    return if (platform == "youtube" || "youtube" in lower) {
                        hands("youtube", query, "Busco $query en YouTube.")
                    } else {
                        hands("music", query, "Busco $query en Spotify.")
                    }
                }
            }
        }

        val remembered = rememberRe.find(text)
        if (remembered != null) {
            prefs.putFact(remembered.groupValues[1].trim(), remembered.groupValues[2].trim())
            return ChatOut("Anotado.")
        }
        if (Regex("""\b(qu[eé] sab[eé]s|mis datos|memoria)\b""").containsMatchIn(lower)) {
            val facts = prefs.facts()
            val body = if (facts.isEmpty()) "Todavía no me dijiste datos." else facts.entries.joinToString("\n") { "- ${it.key}: ${it.value}" }
            return ChatOut(body)
        }
        val note = noteRe.find(text)
        if (note != null) {
            notes.addLocal(note.groupValues[1].trim())
            return ChatOut("Nota guardada en el celular. Se sincroniza con la PC cuando hay enlace.")
        }
        if (Regex("""^(notas|mis notas|lista(r)? notas)$""").containsMatchIn(lower)) {
            val lines = notes.snapshot().texts()
            return ChatOut(if (lines.isEmpty()) "No hay notas." else lines.mapIndexed { i, t -> "${i + 1}. $t" }.joinToString("\n"))
        }
        if (text.startsWith("http://", true) || text.startsWith("https://", true)) {
            return hands("browser", text.trim(), "Abro el link.")
        }
        val opened = openRe.find(text)
        if (opened != null) {
            val target = opened.groupValues[1].trim().trim('.', '!', '?')
            if (BankApps.blocked(target)) return ChatOut("No abro apps bancarias.")
            when (target.lowercase(Locale.getDefault())) {
                "youtube", "yt" -> return hands("browser", "https://www.youtube.com", "YouTube.")
                "gmail", "correo", "mail" -> return hands("browser", "https://mail.google.com", "Gmail.")
                "maps", "mapas" -> return hands("maps", "acá", "Mapas.")
                "netflix" -> return hands("browser", "https://www.netflix.com", "Netflix.")
            }
            return hands("open_app", target, "Abro $target.")
        }
        val bare = bareApps.firstOrNull { it == lower.trim() }
        if (bare != null) return hands("open_app", bare, "Abro $bare.")
        return null
    }

    fun fallback(prefs: Prefs, linked: Boolean): String {
        val who = prefs.displayName.ifBlank { prefs.username }.ifBlank { "vos" }
        return if (linked) {
            "No pude completar eso en el celular. Probá de nuevo."
        } else {
            "Estoy en el celular, $who. Apps, notas, volumen y linterna van acá. " +
                "En Perfil podés enlazar la PC (mismo Wi-Fi) y sincronizamos."
        }
    }

    private fun hands(
        action: String,
        target: String = "",
        reply: String,
        text: String = "",
    ): ChatOut {
        val obj = JSONObject().put("action", action)
        if (target.isNotBlank()) obj.put("target", target)
        if (text.isNotBlank()) obj.put("text", text)
        return ChatOut(reply, listOf(obj))
    }
}

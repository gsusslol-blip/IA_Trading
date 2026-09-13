package app.gsuss.asistente

import android.content.Context
import org.json.JSONObject
import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.util.Locale

/**
 * Runs on the phone without the PC. PhoneHands still executes the intents.
 * Conversation that needs the LLM is left to Brain when a PC session exists.
 */
object PhoneLocal {
    private val openRe = Regex(
        """(?:abr[ií]|abrime|abrir|abre|open|lanz[aá]|sac[aá])\s+(?:la\s+|el\s+|app\s+(?:de\s+)?)?(.+)$""",
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
        """(?:llam[aá]|marca[lr]?|disc[aá])\s+(?:al\s+|a\s+)?([+\d][\d\s\-()]{6,})$""",
        RegexOption.IGNORE_CASE,
    )
    private val mapsRe = Regex(
        """^(?:c[oó]mo\s+llego(?:\s+a)?|mapas?|ruta(?:\s+a)?)\s+(.+)$""",
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
                "En el celular abro apps (no bancarias), pongo música en Spotify, linterna, cámara, mapas, llamadas y notas. " +
                    "Cuando la PC está en el Wi-Fi, me sincronizo y pienso con Ilaria de ahí.",
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
        val call = callRe.find(text)
        if (call != null) return hands("call", call.groupValues[1].filter { it.isDigit() || it == '+' }, "Abro el marcador.")
        val maps = mapsRe.find(text)
        if (maps != null) return hands("maps", maps.groupValues[1].trim(), "Mapas.")

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
        val opened = openRe.find(text)
        if (opened != null) {
            val target = opened.groupValues[1].trim().trim('.', '!', '?')
            if (BankApps.blocked(target)) return ChatOut("No abro apps bancarias.")
            return hands("open_app", target, "Abro $target.")
        }
        if (Regex("""\b(spotify|whatsapp|telegram|instagram|youtube|tiktok)\b""").containsMatchIn(lower) &&
            Regex("""\b(abr|sac[aá]|lanz)\b""").containsMatchIn(lower)
        ) {
            val name = listOf("spotify", "whatsapp", "telegram", "instagram", "youtube", "tiktok")
                .first { it in lower }
            return hands("open_app", name, "Abro $name.")
        }
        return null
    }

    fun fallback(prefs: Prefs, linked: Boolean): String {
        val who = prefs.displayName.ifBlank { prefs.username }.ifBlank { "vos" }
        return if (linked) {
            "No pude completar eso en el celular. Probá de nuevo."
        } else {
            "Estoy en el celular, $who. Apps, notas y linterna van acá. " +
                "En Perfil podés enlazar la PC (mismo Wi-Fi) y sincronizamos."
        }
    }

    private fun hands(action: String, target: String = "", reply: String): ChatOut {
        val obj = JSONObject().put("action", action)
        if (target.isNotBlank()) obj.put("target", target)
        return ChatOut(reply, listOf(obj))
    }
}

package app.gsuss.asistente

import android.content.Context
import android.os.Bundle
import android.speech.tts.TextToSpeech
import android.speech.tts.Voice
import java.util.Locale
import java.util.concurrent.atomic.AtomicBoolean

/** On-device voice when the PC Piper stream is not in play. */
object SoloTts {
    private var engine: TextToSpeech? = null
    private val ready = AtomicBoolean(false)

    fun warm(context: Context) {
        if (engine != null) return
        engine = TextToSpeech(context.applicationContext) { status ->
            val ok = status == TextToSpeech.SUCCESS
            ready.set(ok)
            if (!ok) return@TextToSpeech
            val tts = engine ?: return@TextToSpeech
            tts.language = Locale("es", "AR")
            tts.setSpeechRate(0.90f)
            tts.setPitch(1.06f)
            pickVoice(tts)?.let { tts.voice = it }
        }
    }

    fun say(text: String) {
        val spoken = soften(text)
        if (spoken.isBlank() || !ready.get()) return
        val params = Bundle()
        params.putFloat(TextToSpeech.Engine.KEY_PARAM_VOLUME, 1.0f)
        engine?.speak(spoken.take(420), TextToSpeech.QUEUE_FLUSH, params, "ilaria-solo")
    }

    fun stop() {
        try {
            engine?.stop()
        } catch (_: Exception) {
        }
    }

    private fun soften(text: String): String {
        return text.trim()
            .replace(Regex("https?://\\S+"), "enlace")
            .replace(Regex("[#*_`]+"), "")
            .replace(Regex("\\s+"), " ")
    }

    private fun pickVoice(tts: TextToSpeech): Voice? {
        val voices = try {
            tts.voices
        } catch (_: Exception) {
            return null
        } ?: return null
        val scored = voices.map { voice ->
            val loc = voice.locale
            val lang = loc.language.lowercase()
            val country = loc.country.uppercase()
            val name = voice.name.lowercase()
            var score = 0
            if (lang == "es") score += 8
            if (country == "AR") score += 12
            if (country in setOf("UY", "CL", "MX", "ES")) score += 3
            if (voice.quality >= Voice.QUALITY_HIGH) score += 4
            if (voice.latency <= Voice.LATENCY_NORMAL) score += 1
            if (!voice.isNetworkConnectionRequired) score += 2
            if (listOf("female", "mujer", "fema", "elena", "sabina", "monica", "lucia", "paulina")
                    .any { it in name }
            ) {
                score += 6
            }
            if (listOf("male", "hombre", "daniel", "jorge", "carlos").any { it in name }) {
                score -= 4
            }
            score to voice
        }
        return scored.maxByOrNull { it.first }?.takeIf { it.first >= 8 }?.second
    }
}

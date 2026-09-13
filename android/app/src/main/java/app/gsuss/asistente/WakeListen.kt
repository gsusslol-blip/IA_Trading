package app.gsuss.asistente

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat
import java.util.Locale

private val WAKE = Regex(
    """\b(ilaria|hilaria|ilaría|oye\s+ilaria|hey\s+ilaria|ok\s+ilaria)\b""",
    RegexOption.IGNORE_CASE,
)

@Composable
fun WakeListen(
    enabled: Boolean,
    busy: Boolean,
    onRms: (Float) -> Unit = {},
    onHeard: (String) -> Unit,
) {
    val context = LocalContext.current
    var granted by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO)
                == PackageManager.PERMISSION_GRANTED,
        )
    }
    val ask = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        granted = ok
    }
    LaunchedEffect(enabled) {
        if (enabled && !granted) ask.launch(Manifest.permission.RECORD_AUDIO)
    }
    DisposableEffect(enabled, granted, busy) {
        if (!enabled || !granted || busy) {
            return@DisposableEffect onDispose { }
        }
        if (!SpeechRecognizer.isRecognitionAvailable(context)) {
            return@DisposableEffect onDispose { }
        }
        val speech = SpeechRecognizer.createSpeechRecognizer(context)
        val main = Handler(Looper.getMainLooper())
        fun listen() {
            val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                putExtra(RecognizerIntent.EXTRA_LANGUAGE, "es-AR")
                putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
                putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3)
            }
            try {
                speech.startListening(intent)
            } catch (_: Exception) {
            }
        }
        speech.setRecognitionListener(object : RecognitionListener {
            override fun onReadyForSpeech(params: Bundle?) {}
            override fun onBeginningOfSpeech() {}
            override fun onRmsChanged(rmsdB: Float) {
                val level = ((rmsdB + 2f) / 12f).coerceIn(0f, 1f)
                main.post { onRms(level) }
            }
            override fun onBufferReceived(buffer: ByteArray?) {}
            override fun onEndOfSpeech() {}
            override fun onError(error: Int) {
                listen()
            }
            override fun onResults(results: Bundle?) {
                val text = results
                    ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                    ?.firstOrNull()
                    .orEmpty()
                    .trim()
                val gated = gateWake(text)
                if (gated.isNotBlank()) onHeard(gated)
                listen()
            }
            override fun onPartialResults(partialResults: Bundle?) {}
            override fun onEvent(eventType: Int, params: Bundle?) {}
        })
        listen()
        onDispose {
            try {
                speech.cancel()
                speech.destroy()
            } catch (_: Exception) {
            }
        }
    }
}

fun gateWake(raw: String, followMs: Long = 0L, lastTalk: Long = 0L): String {
    val text = raw.trim()
    if (text.isEmpty()) return ""
    val woke = WAKE.containsMatchIn(text)
    val follow = lastTalk > 0L && (System.currentTimeMillis() - lastTalk) < followMs
    if (!woke && !follow) return ""
    val cleaned = WAKE.replace(text, " ").replace(Regex("""\s+"""), " ").trim()
    if (woke && cleaned.isEmpty()) return "hola"
    return cleaned.ifBlank { text }
}

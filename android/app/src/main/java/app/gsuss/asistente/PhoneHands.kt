package app.gsuss.asistente

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.media.AudioManager
import android.net.Uri
import android.os.Build
import android.provider.AlarmClock
import android.provider.ContactsContract
import android.provider.MediaStore
import android.provider.Settings
import org.json.JSONObject

/** Runs allowlisted intents on this phone. User confirms calls/SMS in the system app. */
object PhoneHands {
    /** Returns a signal for MainActivity when the action is client-side only. */
    fun run(context: Context, raw: JSONObject): String? {
        val action = raw.optString("action").lowercase()
        val target = raw.optString("target")
        val text = raw.optString("text")
        val app = context.applicationContext
        when (action) {
            "call" -> start(app, Intent(Intent.ACTION_DIAL, Uri.parse("tel:$target")))
            "sms" -> {
                val intent = Intent(Intent.ACTION_SENDTO, Uri.parse("smsto:$target"))
                if (text.isNotBlank()) intent.putExtra("sms_body", text)
                start(app, intent)
            }
            "whatsapp" -> {
                val digits = target.filter { it.isDigit() }
                val url = "https://wa.me/$digits" + if (text.isNotBlank()) "?text=${Uri.encode(text)}" else ""
                start(app, Intent(Intent.ACTION_VIEW, Uri.parse(url)))
            }
            "maps", "navigate" -> {
                val q = Uri.encode(target.ifBlank { text })
                val uri = if (action == "navigate") {
                    Uri.parse("google.navigation:q=$q")
                } else {
                    Uri.parse("geo:0,0?q=$q")
                }
                start(app, Intent(Intent.ACTION_VIEW, uri))
            }
            "browser" -> start(app, Intent(Intent.ACTION_VIEW, Uri.parse(target)))
            "search" -> start(
                app,
                Intent(Intent.ACTION_VIEW, Uri.parse("https://www.google.com/search?q=${Uri.encode(target.ifBlank { text })}")),
            )
            "youtube" -> start(
                app,
                Intent(Intent.ACTION_VIEW, Uri.parse("https://www.youtube.com/results?search_query=${Uri.encode(target.ifBlank { text })}")),
            )
            "music" -> playSpotifySearch(app, target.ifBlank { text })
            "open_app" -> openInstalledApp(app, target.ifBlank { text })
            "torch" -> torch(app, target != "off")
            "camera" -> start(app, Intent(MediaStore.ACTION_IMAGE_CAPTURE))
            "gallery" -> start(app, Intent(Intent.ACTION_VIEW).setDataAndType(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, "image/*"))
            "settings" -> start(app, Intent(Settings.ACTION_SETTINGS))
            "wifi" -> start(app, Intent(Settings.ACTION_WIFI_SETTINGS))
            "open_wifi_settings" -> start(app, Intent(Settings.ACTION_WIFI_SETTINGS))
            "open_app_settings" -> {
                val intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
                intent.data = Uri.fromParts("package", app.packageName, null)
                start(app, intent)
            }
            "clear_http", "refresh_device_snap" -> return action
            "bluetooth" -> start(app, Intent(Settings.ACTION_BLUETOOTH_SETTINGS))
            "volume" -> volume(app, target)
            "share" -> {
                val intent = Intent(Intent.ACTION_SEND).setType("text/plain")
                intent.putExtra(Intent.EXTRA_TEXT, text.ifBlank { target })
                start(app, Intent.createChooser(intent, "Ilaria"))
            }
            "clipboard" -> {
                val cm = app.getSystemService(Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager
                cm.setPrimaryClip(android.content.ClipData.newPlainText("ilaria", text.ifBlank { target }))
            }
            "alarm" -> {
                val hour = target.substringBefore(":").toIntOrNull() ?: 8
                val minute = target.substringAfter(":", "0").toIntOrNull() ?: 0
                val intent = Intent(AlarmClock.ACTION_SET_ALARM)
                    .putExtra(AlarmClock.EXTRA_HOUR, hour.coerceIn(0, 23))
                    .putExtra(AlarmClock.EXTRA_MINUTES, minute.coerceIn(0, 59))
                    .putExtra(AlarmClock.EXTRA_MESSAGE, text.ifBlank { "Ilaria" })
                    .putExtra(AlarmClock.EXTRA_SKIP_UI, false)
                start(app, intent)
            }
            "timer" -> {
                val minutes = target.toIntOrNull() ?: 5
                val intent = Intent(AlarmClock.ACTION_SET_TIMER)
                    .putExtra(AlarmClock.EXTRA_LENGTH, (minutes.coerceIn(1, 180) * 60))
                    .putExtra(AlarmClock.EXTRA_MESSAGE, text.ifBlank { "Ilaria" })
                    .putExtra(AlarmClock.EXTRA_SKIP_UI, false)
                start(app, intent)
            }
            "calendar" -> start(app, Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_APP_CALENDAR))
            "contacts" -> start(app, Intent(Intent.ACTION_VIEW, ContactsContract.Contacts.CONTENT_URI))
            "email" -> start(app, Intent(Intent.ACTION_SENDTO, Uri.parse("mailto:${target}")).putExtra(Intent.EXTRA_TEXT, text))
            "screenshot" -> {
                // No public screenshot API; open share sheet with hint + gallery fallback.
                val share = Intent(Intent.ACTION_SEND).setType("text/plain")
                share.putExtra(Intent.EXTRA_TEXT, "Captura: usá Power + Volumen abajo, o el botón de captura del sistema.")
                start(app, Intent.createChooser(share, "Ilaria"))
                return "screenshot_hint"
            }
            "lock" -> {
                val dpm = app.getSystemService(Context.DEVICE_POLICY_SERVICE) as? android.app.admin.DevicePolicyManager
                try {
                    dpm?.lockNow()
                } catch (_: Exception) {
                }
                // Fallback: open lock-screen settings if no device-admin.
                start(app, Intent(Settings.ACTION_SECURITY_SETTINGS))
            }
            "clipboard_get" -> {
                val cm = app.getSystemService(Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager
                val clip = cm.primaryClip?.getItemAt(0)?.coerceToText(app)?.toString().orEmpty()
                return "clipboard:$clip"
            }
            "translate" -> {
                val q = Uri.encode(text.ifBlank { target })
                start(app, Intent(Intent.ACTION_VIEW, Uri.parse("https://translate.google.com/?sl=auto&tl=es&text=$q&op=translate")))
            }
            else -> { }
        }
        return null
    }

    private fun playSpotifySearch(app: Context, raw: String) {
        val query = raw.trim()
        if (query.isBlank()) {
            openInstalledApp(app, "spotify")
            return
        }
        val encoded = Uri.encode(query)
        val candidates = listOf(
            Uri.parse("spotify:search:$encoded"),
            Uri.parse("https://open.spotify.com/search/${encoded}"),
        )
        for (uri in candidates) {
            val intent = Intent(Intent.ACTION_VIEW, uri).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            for (pkg in listOf("com.spotify.music", "com.spotify.lite")) {
                intent.setPackage(pkg)
                if (intent.resolveActivity(app.packageManager) != null) {
                    try {
                        app.startActivity(intent)
                        return
                    } catch (_: Exception) {
                    }
                }
            }
            intent.setPackage(null)
            try {
                app.startActivity(intent)
                return
            } catch (_: Exception) {
            }
        }
        openInstalledApp(app, "spotify")
    }

    private fun openInstalledApp(app: Context, raw: String) {
        val hint = raw.trim()
        if (hint.isBlank()) return
        if (BankApps.blocked(hint)) return
        val launch = resolveLauncher(app, hint)
        if (launch != null) {
            start(app, launch)
            return
        }
        if (hint.contains("spotify", ignoreCase = true)) {
            start(app, Intent(Intent.ACTION_VIEW, Uri.parse("spotify:")))
            return
        }
        start(app, Intent(Intent.ACTION_VIEW, Uri.parse("market://search?q=${Uri.encode(hint)}")))
    }

    private fun resolveLauncher(app: Context, hint: String): Intent? {
        val pm = app.packageManager
        val aliases = mapOf(
            "whatsapp" to listOf("com.whatsapp", "com.whatsapp.w4b"),
            "telegram" to listOf("org.telegram.messenger"),
            "instagram" to listOf("com.instagram.android"),
            "youtube" to listOf("com.google.android.youtube"),
            "spotify" to listOf("com.spotify.music", "com.spotify.lite"),
            "maps" to listOf("com.google.android.apps.maps"),
            "gmail" to listOf("com.google.android.gm"),
            "chrome" to listOf("com.android.chrome"),
            "fotos" to listOf("com.google.android.apps.photos"),
            "photos" to listOf("com.google.android.apps.photos"),
            "tiktok" to listOf("com.zhiliaoapp.musically"),
            "discord" to listOf("com.discord"),
            "twitter" to listOf("com.twitter.android"),
            "x" to listOf("com.twitter.android"),
            "netflix" to listOf("com.netflix.mediaclient"),
            "twitch" to listOf("tv.twitch.android.app"),
        )
        val foldedHint = BankApps.fold(hint)
        val fromAlias = aliases.entries.firstOrNull { BankApps.fold(it.key) == foldedHint }?.value
        val direct = buildList {
            if (fromAlias != null) addAll(fromAlias)
            add(hint)
        }
        direct.firstNotNullOfOrNull { pkg ->
            val intent = pm.getLaunchIntentForPackage(pkg)
            if (intent != null && !BankApps.blocked(pkg)) intent else null
        }?.let { return it }

        val query = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        val found = if (Build.VERSION.SDK_INT >= 33) {
            pm.queryIntentActivities(query, PackageManager.ResolveInfoFlags.of(0L))
        } else {
            @Suppress("DEPRECATION")
            pm.queryIntentActivities(query, 0)
        }
        var containsHit: Intent? = null
        for (info in found) {
            val pkg = info.activityInfo.packageName
            val label = info.loadLabel(pm).toString()
            if (BankApps.blocked(pkg, label)) continue
            val launch = pm.getLaunchIntentForPackage(pkg) ?: continue
            val foldedLabel = BankApps.fold(label)
            if (pkg.equals(hint, ignoreCase = true) || foldedLabel == foldedHint) return launch
            if (containsHit == null && foldedHint.length >= 3 && foldedLabel.length >= 3 &&
                (
                    foldedLabel.contains(foldedHint) ||
                        (foldedLabel.length >= 5 && foldedHint.contains(foldedLabel))
                    )
            ) {
                containsHit = launch
            }
        }
        return containsHit
    }

    private fun start(context: Context, intent: Intent) {
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        try {
            context.startActivity(intent)
        } catch (_: Exception) {
        }
    }

    private fun volume(context: Context, how: String) {
        val am = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        when (how) {
            "mute" -> am.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_MUTE, AudioManager.FLAG_SHOW_UI)
            "down" -> am.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_LOWER, AudioManager.FLAG_SHOW_UI)
            else -> {
                val n = how.toIntOrNull()
                if (n != null) {
                    val max = am.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
                    am.setStreamVolume(AudioManager.STREAM_MUSIC, (n.coerceIn(0, 100) * max / 100), AudioManager.FLAG_SHOW_UI)
                } else {
                    am.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_RAISE, AudioManager.FLAG_SHOW_UI)
                }
            }
        }
    }

    private var torchOn = false

    private fun torch(context: Context, on: Boolean) {
        try {
            val cm = context.getSystemService(Context.CAMERA_SERVICE) as CameraManager
            val id = cm.cameraIdList.firstOrNull { cam ->
                cm.getCameraCharacteristics(cam).get(CameraCharacteristics.FLASH_INFO_AVAILABLE) == true
            } ?: return
            cm.setTorchMode(id, on)
            torchOn = on
        } catch (_: Exception) {
            start(context, Intent(MediaStore.ACTION_IMAGE_CAPTURE))
        }
    }
}

object DeviceSnap {
    fun json(context: Context): JSONObject {
        val bm = context.registerReceiver(null, android.content.IntentFilter(android.content.Intent.ACTION_BATTERY_CHANGED))
        val level = bm?.getIntExtra(android.os.BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = bm?.getIntExtra(android.os.BatteryManager.EXTRA_SCALE, 100) ?: 100
        val plugged = (bm?.getIntExtra(android.os.BatteryManager.EXTRA_PLUGGED, 0) ?: 0) != 0
        val pct = if (level >= 0 && scale > 0) (level * 100 / scale) else -1
        val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as android.net.ConnectivityManager
        val wifi = if (Build.VERSION.SDK_INT >= 23) {
            cm.getNetworkCapabilities(cm.activeNetwork)?.hasTransport(android.net.NetworkCapabilities.TRANSPORT_WIFI) == true
        } else {
            @Suppress("DEPRECATION")
            cm.activeNetworkInfo?.type == android.net.ConnectivityManager.TYPE_WIFI
        }
        var versionName = ""
        var versionCode = 0
        try {
            val info = context.packageManager.getPackageInfo(context.packageName, 0)
            versionName = info.versionName ?: ""
            versionCode = if (Build.VERSION.SDK_INT >= 28) info.longVersionCode.toInt() else @Suppress("DEPRECATION") info.versionCode
        } catch (_: Exception) {
        }
        return JSONObject()
            .put("battery", pct)
            .put("charging", plugged)
            .put("wifi", wifi)
            .put("model", Build.MODEL)
            .put("app_version", versionName)
            .put("versionName", versionName)
            .put("versionCode", versionCode)
    }
}

package app.gsuss.asistente

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.net.Uri
import android.os.Build
import android.provider.Settings
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.io.File
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

data class ApkUpdate(val code: Int, val name: String, val bytes: Long)

class UpdateReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)
        if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
            val confirm = if (Build.VERSION.SDK_INT >= 33) {
                intent.getParcelableExtra(Intent.EXTRA_INTENT, Intent::class.java)
            } else {
                @Suppress("DEPRECATION")
                intent.getParcelableExtra(Intent.EXTRA_INTENT)
            }
            confirm?.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            if (confirm != null) context.startActivity(confirm)
        }
    }
}

object AppUpdate {
    const val ACTION = "app.gsuss.asistente.INSTALL"
    private val applying = AtomicBoolean(false)
    private val http = OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .build()

    fun localCode(context: Context): Int {
        val info = context.packageManager.getPackageInfo(context.packageName, 0)
        return if (Build.VERSION.SDK_INT >= 28) info.longVersionCode.toInt() else @Suppress("DEPRECATION") info.versionCode
    }

    fun applyOnLaunch(context: Context, prefs: Prefs) {
        if (!applying.compareAndSet(false, true)) return
        try {
            var base = prefs.baseUrl
            if (base.isBlank() || prefs.looksLikeRouter(base)) {
                LanFind.find(context)?.let {
                    prefs.baseUrl = it
                    base = it
                }
            }
            if (base.isBlank()) return
            val remote = check(prefs, localCode(context)) ?: return
            if (Build.VERSION.SDK_INT >= 26 && !context.packageManager.canRequestPackageInstalls()) {
                android.os.Handler(android.os.Looper.getMainLooper()).post {
                    context.startActivity(
                        Intent(
                            Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                            Uri.parse("package:${context.packageName}"),
                        ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                    )
                }
                return
            }
            val apk = File(context.cacheDir, "Ilaria-update.apk")
            download(prefs, apk)
            install(context, apk)
        } finally {
            applying.set(false)
        }
    }

    fun check(prefs: Prefs, installed: Int): ApkUpdate? {
        val req = Request.Builder().url(prefs.resolveUrl("/api/android/update")).get().build()
        http.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) return null
            val json = JSONObject(resp.body?.string().orEmpty())
            if (!json.optBoolean("ready", false)) return null
            val code = json.optInt("versionCode", 0)
            if (code <= installed) return null
            return ApkUpdate(code, json.optString("versionName"), json.optLong("bytes"))
        }
    }

    fun download(prefs: Prefs, dest: File) {
        dest.parentFile?.mkdirs()
        val req = Request.Builder().url(prefs.resolveUrl("/api/android/apk")).get().build()
        http.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) throw IllegalStateException("No pude bajar el APK (${resp.code}).")
            val body = resp.body ?: throw IllegalStateException("APK vacío.")
            dest.outputStream().use { out -> body.byteStream().copyTo(out) }
        }
        if (dest.length() < 100_000) {
            dest.delete()
            throw IllegalStateException("APK incompleto.")
        }
    }

    fun install(context: Context, apk: File) {
        val installer = context.packageManager.packageInstaller
        val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
        params.setAppPackageName(context.packageName)
        val sessionId = installer.createSession(params)
        installer.openSession(sessionId).use { session ->
            session.openWrite("ilaria", 0, apk.length()).use { out ->
                apk.inputStream().use { input -> input.copyTo(out) }
                session.fsync(out)
            }
            val flags = PendingIntent.FLAG_UPDATE_CURRENT or
                if (Build.VERSION.SDK_INT >= 31) PendingIntent.FLAG_MUTABLE else 0
            val callback = Intent(context, UpdateReceiver::class.java).setAction(ACTION)
            val pending = PendingIntent.getBroadcast(context, sessionId, callback, flags)
            session.commit(pending.intentSender)
        }
    }
}

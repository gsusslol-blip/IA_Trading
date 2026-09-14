package app.gsuss.asistente

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import org.json.JSONObject

/** Local notifications for PC /api/alerts while the app is linked. */
object AlertNotify {
    private const val CHANNEL = "ilaria_alerts"
    private var afterId = 0

    fun ensureChannel(context: Context) {
        if (Build.VERSION.SDK_INT < 26) return
        val mgr = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val channel = NotificationChannel(CHANNEL, "Ilaria avisos", NotificationManager.IMPORTANCE_HIGH)
        channel.description = "Recordatorios y avisos desde tu PC"
        mgr.createNotificationChannel(channel)
    }

    fun canPost(context: Context): Boolean {
        if (Build.VERSION.SDK_INT < 33) return true
        return ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) ==
            PackageManager.PERMISSION_GRANTED
    }

    fun show(context: Context, title: String, body: String, id: Int) {
        ensureChannel(context)
        if (!canPost(context)) return
        val open = Intent(context, MainActivity::class.java)
        val pending = PendingIntent.getActivity(
            context,
            id,
            open,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val note = NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setContentIntent(pending)
            .setAutoCancel(true)
            .build()
        NotificationManagerCompat.from(context).notify(1000 + (id % 10000), note)
    }

    fun poll(context: Context, brain: Brain, prefs: Prefs) {
        if (!prefs.loggedIn || prefs.baseUrl.isBlank()) return
        try {
            val json = brain.getAlerts(afterId)
            val items = json.optJSONArray("items") ?: return
            for (i in 0 until items.length()) {
                val item = items.getJSONObject(i)
                val id = item.optInt("id")
                val text = item.optString("text")
                if (id > afterId) afterId = id
                if (text.isNotBlank()) {
                    show(context, "Ilaria", text, id)
                }
            }
        } catch (_: Exception) {
        }
    }
}

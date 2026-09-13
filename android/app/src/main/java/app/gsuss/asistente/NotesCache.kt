package app.gsuss.asistente

import android.content.Context
import org.json.JSONObject
import java.io.File
import java.util.UUID
import kotlin.concurrent.withLock
import java.util.concurrent.locks.ReentrantLock

/**
 * Local JSON cache. Merges with the PC when a session is linked.
 */
class NotesCache(context: Context, private val prefs: Prefs) {
    private val root = File(context.filesDir, "notes")
    private val lock = ReentrantLock()

    fun snapshot(): NotesBundle {
        lock.withLock {
            val file = file()
            if (!file.isFile) return NotesBundle(rev = prefs.notesRev, items = emptyList())
            return try {
                NotesBundle.fromExport(JSONObject(file.readText(Charsets.UTF_8)))
            } catch (_: Exception) {
                NotesBundle(rev = prefs.notesRev, items = emptyList())
            }
        }
    }

    fun remember(bundle: NotesBundle) {
        lock.withLock {
            root.mkdirs()
            file().writeText(bundle.toJson().toString(), Charsets.UTF_8)
            prefs.notesRev = bundle.rev
        }
    }

    fun addLocal(text: String): NotesBundle {
        val body = text.trim()
        val now = System.currentTimeMillis() / 1000.0
        val item = NoteItem(
            id = UUID.randomUUID().toString().replace("-", "").take(12),
            text = body,
            updated = now,
        )
        val current = snapshot()
        val next = NotesBundle(rev = current.rev, items = current.items + item)
        remember(next)
        return next
    }

    fun clear() {
        lock.withLock {
            file().delete()
            prefs.notesRev = 0
        }
    }

    fun syncWith(brain: Brain): NotesBundle {
        val local = snapshot()
        val remote = if (local.items.isEmpty()) {
            brain.fetchNotes()
        } else {
            brain.syncNotes(local)
        }
        remember(remote)
        try {
            prefs.saveFacts(brain.mergeFacts(prefs.facts()))
        } catch (_: Exception) {
        }
        return remote
    }

    private fun file(): File {
        val who = prefs.username.ifBlank { "anon" }
        return File(root, "$who.json")
    }
}

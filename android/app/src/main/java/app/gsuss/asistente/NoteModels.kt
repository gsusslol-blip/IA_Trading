package app.gsuss.asistente

import org.json.JSONArray
import org.json.JSONObject

data class NoteItem(
    val id: String,
    val text: String,
    val updated: Double,
    val deleted: Boolean = false,
) {
    fun toJson(): JSONObject {
        val obj = JSONObject()
            .put("id", id)
            .put("text", text)
            .put("updated", updated)
        if (deleted) obj.put("deleted", true)
        return obj
    }

    companion object {
        fun fromJson(obj: JSONObject): NoteItem {
            return NoteItem(
                id = obj.optString("id"),
                text = obj.optString("text"),
                updated = obj.optDouble("updated", 0.0),
                deleted = obj.optBoolean("deleted", false),
            )
        }
    }
}

data class NotesBundle(
    val rev: Int,
    val items: List<NoteItem>,
) {
    fun texts(): List<String> = items.filter { !it.deleted }.map { it.text }

    fun toJson(): JSONObject {
        val arr = JSONArray()
        items.forEach { arr.put(it.toJson()) }
        return JSONObject().put("rev", rev).put("items", arr)
    }

    companion object {
        fun fromExport(json: JSONObject): NotesBundle {
            val arr = json.optJSONArray("items") ?: JSONArray()
            val items = buildList {
                for (i in 0 until arr.length()) {
                    val row = arr.optJSONObject(i) ?: continue
                    add(NoteItem.fromJson(row))
                }
            }
            return NotesBundle(rev = json.optInt("rev", 0), items = items)
        }
    }
}

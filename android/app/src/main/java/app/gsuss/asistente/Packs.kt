package app.gsuss.asistente

data class Pack(
    val id: String,
    val title: String,
    val blurb: String,
    val style: String,
)

val PACKS = listOf(
    Pack("diario", "Día a día", "Clima, recordatorios y lo básico.", "Daily life: weather, short lists, timers."),
    Pack("estudio", "Estudio", "Explicaciones, Wikipedia, foco.", "Study: clear explanations, sources."),
    Pack("trabajo", "Trabajo", "Listas, borradores, directo.", "Work: concise and actionable."),
    Pack("trading", "Mercados", "Noticias y contexto. No es consejo financiero.", "Markets info only, never financial advice."),
    Pack("salud", "Salud y hábito", "Hábitos. No reemplaza un médico.", "Habits only. No diagnoses."),
    Pack("hogar", "Hogar", "Listas y timers de casa.", "Home lists and timers."),
    Pack("programacion", "Programación", "Docs y snippets.", "Dev: precise, copy-paste ready."),
    Pack("viajes", "Viajes", "Clima y mapas.", "Travel weather and directions."),
)

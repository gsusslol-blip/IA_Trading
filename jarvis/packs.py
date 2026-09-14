"""Preloaded interest packs and time-of-day assistant style."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from jarvis.memory import Memory


@dataclass(frozen=True)
class Pack:
    id: str
    title: str
    blurb: str
    facts: dict[str, str]
    notes: tuple[str, ...]
    style: str


PACKS: dict[str, Pack] = {
    "diario": Pack(
        id="diario",
        title="Día a día",
        blurb="Clima, recordatorios, notas y lo básico para vivir más liviano.",
        facts={
            "perfil": "uso diario",
            "prioridad": "organizar el día, no saturar",
        },
        notes=(
            "Plantilla rápida: hoy / pendiente / no olvidar",
            "Pedime el clima de tu ciudad, un timer, o ‘tomá nota’ para el diario del día.",
        ),
        style=(
            "Daily-life / general mode: organize the day — weather, timers, short lists, "
            "daily_journal, gentle nudges. Be executive, not chatty."
        ),
    ),
    "estudio": Pack(
        id="estudio",
        title="Estudio",
        blurb="Materias, Wikipedia, timers de foco y resúmenes.",
        facts={
            "perfil": "estudiante",
            "metodo_foco": "pomodoro 25/5 salvo que pida otro",
        },
        notes=(
            "Materia / tema / próximo examen / duda",
            "Pedime: ‘explicame X como si tuviera 15’ o un timer de 25 minutos.",
        ),
        style=(
            "Study / academic mode: concept maps, long-text summaries, practice quizzes from "
            "local notes when possible. Prefer Wikipedia + search for sources. Offer focus timers."
        ),
    ),
    "trabajo": Pack(
        id="trabajo",
        title="Trabajo",
        blurb="Notas, mail, abrir apps y cortes de foco.",
        facts={
            "perfil": "trabajo",
            "tono_laboral": "directo, listas accionables",
        },
        notes=(
            "Hoy: 3 prioridades. Bloqueadores. Follow-ups.",
            "Puedo abrir Chrome, Cursor o copiar un texto al portapapeles.",
        ),
        style=(
            "Office / work mode: meeting minutes, professional email drafts, actionable task lists. "
            "Concise. Open apps, timers for deep work, clipboard when useful."
        ),
    ),
    "trading": Pack(
        id="trading",
        title="Mercados",
        blurb="Dólar, noticias y contexto. No es consejo financiero.",
        facts={
            "perfil": "mercados",
            "disclaimer": "informativo, no recomendación de inversión",
        },
        notes=(
            "Pedime dólar, noticias del activo o un resumen del día.",
            "No operes solo porque lo dije: contrastá fuentes.",
        ),
        style=(
            "Markets mode: search live prices/news, summarize risk, never present guesses as certainty. "
            "Always remind this is information, not financial advice."
        ),
    ),
    "salud": Pack(
        id="salud",
        title="Salud y hábito",
        blurb="Agua, movimiento, timers. No reemplaza un médico.",
        facts={
            "perfil": "habitos",
            "disclaimer_salud": "no soy médico ni receto",
        },
        notes=(
            "Hábitos: agua / movimiento / dormir.",
            "Pedime un recordatorio para tomar agua o un timer de estirar.",
        ),
        style="Health-habit mode: reminders and routines only. No diagnoses, no drug advice, suggest a professional when relevant.",
    ),
    "hogar": Pack(
        id="hogar",
        title="Hogar",
        blurb="Listas, cocina, timers. Luces si hay Home Assistant.",
        facts={
            "perfil": "hogar",
        },
        notes=(
            "Lista: super / limpieza / mantenimiento",
            "Timer de horno o abrir la carpeta de Descargas.",
        ),
        style=(
            "Home mode: shopping lists, kitchen timers, household reminders, volume/media, "
            "rest nudges, daily_journal, Home Assistant if configured."
        ),
    ),
    "programacion": Pack(
        id="programacion",
        title="Programación",
        blurb="Abrir el editor, notas técnicas, buscar docs.",
        facts={
            "perfil": "dev",
            "stack_preferido": "el del usuario, si lo dice",
        },
        notes=(
            "Proyecto actual / bug / idea",
            "Pedime abrir Cursor o VS Code y buscar la doc.",
        ),
        style=(
            "Dev / programming mode: extremely concise. Prefer clean code blocks, error digests, "
            "refactors. Open Cursor/VS Code, search current docs, keep snippets paste-ready."
        ),
    ),
    "viajes": Pack(
        id="viajes",
        title="Viajes",
        blurb="Clima del destino, mapas y una checklist simple.",
        facts={
            "perfil": "viajes",
        },
        notes=(
            "Destino / fechas / documentos / checklist",
            "Pedime el clima allá o cómo llegar en Maps.",
        ),
        style="Travel mode: weather at destination, maps, compact packing/checklists, current travel info via search.",
    ),
}


def public_packs() -> list[dict[str, str]]:
    return [
        {"id": pack.id, "title": pack.title, "blurb": pack.blurb}
        for pack in PACKS.values()
    ]


def normalize_pack_ids(raw: list[str] | None) -> list[str]:
    chosen: list[str] = []
    for item in raw or []:
        key = str(item).strip().lower()
        if key in PACKS and key not in chosen:
            chosen.append(key)
    if not chosen:
        chosen = ["diario"]
    return chosen


def packs_style(pack_ids: list[str]) -> str:
    chunks = [PACKS[pid].style for pid in pack_ids if pid in PACKS]
    return "\n".join(chunks)


def resolve_focus_pack(enabled: list[str], requested: str = "", message: str = "") -> str:
    """Pick one active work mode from the user's enabled packs (never invent packs)."""
    ids = normalize_pack_ids(enabled)
    req = (requested or "").strip().lower()
    if req in {"general", "diario"}:
        req = "diario"
    if req in ids:
        return req
    lower = (message or "").lower()
    keywords: list[tuple[str, tuple[str, ...]]] = [
        ("programacion", ("código", "codigo", "bug", "python", "cursor", "vscode", "refactor", "compile")),
        ("estudio", ("estudi", "examen", "materia", "resumen", "cuestionario", "universidad")),
        ("trading", ("dólar", "dolar", "btc", "eth", "vela", "broker", "cotiz", "mercado")),
        ("trabajo", ("mail", "correo", "reunión", "reunion", "minuta", "oficina", "cliente")),
        ("hogar", ("super", "compra", "cocina", "limpieza", "horno", "casa")),
        ("salud", ("agua", "estirar", "dormir", "paseo", "pomodoro")),
        ("viajes", ("viaje", "vuelo", "hotel", "valija", "mapa")),
    ]
    for pack_id, words in keywords:
        if pack_id in ids and any(w in lower for w in words):
            return pack_id
    return ids[0]


def get_user_pack_prompt(
    enabled_packs: list[str] | None,
    current_pack: str = "",
    user_role: str = "member",
    message: str = "",
) -> str:
    """
    Dynamic multi-work instructions from this user's enabled packs.
    Safe for public installs: no hardcoded owner identity.
    """
    ids = normalize_pack_ids(enabled_packs)
    focus = resolve_focus_pack(ids, current_pack, message)
    focus_style = PACKS[focus].style if focus in PACKS else PACKS["diario"].style
    enabled_lines = "\n".join(f"- {pid}: {PACKS[pid].style}" for pid in ids if pid in PACKS)
    role_line = (
        "Role: OWNER — full PC tools when the host grants them."
        if user_role == "owner"
        else "Role: member — helpful assistant; privileged PC tools only if the owner enabled members_pc_hands."
    )
    return (
        f"{role_line}\n"
        "VOICE LOCK: packs change TASKS only (markets, study, home, code). "
        "They never rewrite identity. Owner stays daughter-figure companion; "
        "members never get papá/hija roleplay. Trading/executive = shorter sentences, same girl.\n"
        f"Enabled interest packs for this user:\n{enabled_lines}\n"
        f"[ACTIVE WORK MODE: {focus.upper()}]\n{focus_style}\n"
        "If the user pivots topic, switch emphasis to another enabled pack; do not invent packs."
    )


def apply_packs(memory: Memory, pack_ids: list[str], display_name: str, city: str) -> None:
    ids = normalize_pack_ids(pack_ids)
    memory.remember("nombre", display_name)
    if city.strip():
        memory.remember("ciudad", city.strip())
    memory.remember("intereses", ", ".join(ids))
    for pid in ids:
        pack = PACKS[pid]
        for key, value in pack.facts.items():
            memory.remember(key, value)
        for note in pack.notes:
            memory.add_note(note)


_DAYS_ES = (
    "lunes",
    "martes",
    "miércoles",
    "jueves",
    "viernes",
    "sábado",
    "domingo",
)
_MONTHS_ES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)

ROUTINE_STYLES = {
    "mañana": (
        "Time of day: morning. Be executive: clock, weather if useful, one focus line. "
        "Do not wait to be asked for the obvious. Keep it short."
    ),
    "trabajo_trading": (
        "Time of day: work/trading hours. Minimize long answers. "
        "If you search the web, synthesize at most three key points. "
        "Offer to log market notes with daily_journal when it fits."
    ),
    "tarde_noche": (
        "Time of day: evening. Stay respectful, slightly more relaxed. "
        "Offer to consolidate today's journal or set a reminder for tomorrow when it fits."
    ),
}


def routine_slot(hour: int) -> str:
    if 5 <= hour < 12:
        return "mañana"
    if 12 <= hour < 19:
        return "trabajo_trading"
    return "tarde_noche"


def format_local_when(timezone: str) -> str:
    now = datetime.now(ZoneInfo(timezone))
    weekday = _DAYS_ES[now.weekday()]
    month = _MONTHS_ES[now.month - 1]
    return f"{weekday} {now.day} de {month} de {now.year}, {now.strftime('%H:%M')}"


def routine_style(timezone: str) -> str:
    now = datetime.now(ZoneInfo(timezone))
    slot = routine_slot(now.hour)
    return f"{ROUTINE_STYLES[slot]}\nLocal clock context: {format_local_when(timezone)}."


def welcome_script(
    *,
    address: str,
    status: str = "",
    weather: str = "",
    hour: int = 12,
    pending: str = "",
    journal: str = "",
) -> str:
    """Spoken briefing: greeting + optional pending / journal / weather crumbs."""
    if 5 <= hour < 12:
        hello = "Buen día"
    elif 12 <= hour < 19:
        hello = "Buenas tardes"
    else:
        hello = "Buenas noches"
    who = address.strip() or "señor"
    lower = who.lower()
    if lower in {"papá", "papa", "pá", "pa"} or lower.startswith("papá") or lower.startswith("papa"):
        base = f"{hello}, {who}. Ya estoy acá con vos."
    else:
        base = f"{hello}, {who}."
    bits: list[str] = []
    pend = (pending or "").strip()
    if pend and pend.lower() not in {"no pending reminders.", "(none)", "none"}:
        first = pend.splitlines()[0].lstrip("- ").strip()
        if first:
            bits.append(f"Pendiente: {first[:90]}")
    j = (journal or "").strip()
    if j and "vacío" not in j.lower() and "no hay" not in j.lower() and "empty" not in j.lower():
        line = j.splitlines()[-1].strip()[:80]
        if line:
            bits.append(f"Ayer anotaste: {line}")
    w = (weather or "").strip()
    if w and len(w) < 120:
        bits.append(w.split(".")[0][:90])
    if not bits:
        return base
    return f"{base} {' · '.join(bits)}"

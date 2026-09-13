"""Useful replies without an LLM key: weather, math, notes, search, timers."""

from __future__ import annotations

import json
import re
from typing import Callable

from jarvis.config import Settings
from jarvis.memory import Memory

Execute = Callable[[str, str], str]


def try_local_command(
    text: str,
    execute: Execute,
    memory: Memory,
    settings: Settings,
    allowed: set[str] | None = None,
    surface: str = "hud",
) -> str | None:
    """Run deterministic tools. None = leave it to the LLM."""
    raw = text.strip()
    raw = re.sub(r"^(?:hey\s+)?ilaria\b[\s,.:\-]*", "", raw, flags=re.I).strip()
    lower = raw.lower()
    city = _city(raw, memory)
    android = (surface or "hud").strip().lower() == "android"

    def run(tool: str, **args: object) -> str:
        if allowed is not None and tool not in allowed:
            return "Eso en esta cuenta no esta habilitado."
        return execute(tool, json.dumps(args, ensure_ascii=False))

    if re.search(r"\b(ayuda|help|que podes|qué podés|que podes hacer|capacidades|comandos)\b", lower):
        return _help(settings)

    if re.search(r"\b(hora|fecha|que dia|qué día|que dia es|ahora mismo)\b", lower) or lower in {
        "ahora",
        "hora",
        "fecha",
    }:
        return run("now")

    if re.search(r"\b(estado(?:\s+de)?(?:\s+la)?\s+pc|qu[eé] hay abierto|qu[eé] apps)\b", lower):
        return run("system_status")

    if re.search(
        r"\b(diagn[oó]stic|salud(?:\s+del)?\s+sistema|qu[eé] est[aá] ca[ií]d|"
        r"estado(?:\s+de)?(?:\s+)?ilaria|revis[aá](?:\s+el)?\s+stack|"
        r"ollama(?:\s+ca[ií]d)?|piper(?:\s+ca[ií]d)?)\b",
        lower,
    ):
        return run("get_system_health")

    if re.search(
        r"\b(estado(?:\s+de)?(?:\s+la)?\s+(?:red|lan|wifi)|ip(?:\s+local)?|"
        r"descubrimiento|puerto\s+8788)\b",
        lower,
    ):
        return run("check_lan_status")

    if re.search(r"\b(reinici[aá]|levant[aá]|despert[aá])\s+ollama\b", lower):
        return run("relaunch_service", service="ollama")
    if re.search(r"\b(reinici[aá]|refresc[aá])\s+piper\b", lower):
        return run("relaunch_service", service="piper")
    if re.search(r"\b(ping|prob[aá]|refresc[aá])\s+(?:home\s*assistant|ha)\b", lower):
        return run("relaunch_service", service="ha_ping")

    if android:
        if re.search(
            r"(?:abr[ií]|abrime|abrir|abre|open).{0,24}\b(?:wifi|wi[\-\s]?fi)\b|"
            r"\b(?:ajustes|configuraci[oó]n)\s+(?:de\s+)?(?:el\s+)?(?:wifi|wi[\-\s]?fi)\b",
            lower,
        ):
            return run("queue_phone_fix", action="open_wifi_settings")
        if re.search(
            r"\b(?:ajustes|configuraci[oó]n|permisos)\s+(?:de\s+)?(?:la\s+)?(?:app|aplicaci[oó]n|ilaria)\b|"
            r"\bapp\s+settings\b",
            lower,
        ):
            return run("queue_phone_fix", action="open_app_settings")
        if re.search(
            r"\b(?:limpi[aá]|reset(?:ear)?|reinici[aá])\s+(?:la\s+)?(?:conexi[oó]n|http|okhttp|cliente)\b|"
            r"\bclear\s*http\b",
            lower,
        ):
            return run("queue_phone_fix", action="clear_http")
        if re.search(
            r"\b(?:refresc[aá]|actualiz[aá])\s+(?:el\s+)?(?:snap|estado(?:\s+del)?\s+celular|device(?:\s*snap)?)\b",
            lower,
        ):
            return run("queue_phone_fix", action="refresh_device_snap")

    vol = re.search(r"volumen(?:\s+(?:al|a|en))?\s+(\d{1,3})\s*%?", lower)
    if vol:
        return run("set_volume", level=int(vol.group(1)))

    if re.search(r"\b(silenci(?:ar|[oaá])|mute(?:ar)?|sin\s+sonido)\b", lower):
        return run("media", action="mute")

    if re.search(
        r"\b(paus[aá]|pause|play|reproduc[ií]|siguiente|next|anterior|previous|prev)\b",
        lower,
    ) and re.search(r"\b(m[uú]sica|canci[oó]n|tema|spotify|media|track|pista)\b", lower):
        if re.search(r"\b(siguiente|next)\b", lower):
            return run("media", action="next")
        if re.search(r"\b(anterior|previous|prev)\b", lower):
            return run("media", action="previous")
        if re.search(r"\b(paus[aá]|pause)\b", lower):
            return run("media", action="pause")
        return run("media", action="play")

    if re.search(
        r"\b(captura(?:\s+de\s+pantalla)?|screenshot|sac[aá](?:me)?\s+(?:una\s+)?(?:foto|captura)|"
        r"foto\s+de\s+pantalla)\b",
        lower,
    ):
        return run("screenshot")

    folder = re.search(
        r"(?:abr[ií]|abrime|abrir|abre|open|mostr[aá]|and[aá]\s+a)\s+"
        r"(?:la\s+|el\s+)?(?:carpeta\s+(?:de\s+)?)?(escritorio|desktop|descargas|downloads|"
        r"documentos|documents|workspace)\b",
        lower,
    )
    if folder:
        return run("open_folder", name=folder.group(1))

    if re.search(r"\b(portapapeles|clipboard)\b", lower) and re.search(
        r"\b(le[eé]|mostr|qu[eé] hay|copi)\b", lower
    ):
        if re.search(r"\b(copi[aá]|pon[eé]|peg)\b", lower):
            clipped = re.sub(
                r"^.*(?:al\s+)?(?:portapapeles|clipboard)\s*[:\-]?\s*",
                "",
                raw,
                flags=re.I,
            ).strip()
            if clipped:
                return run("set_clipboard", text=clipped)
        return run("get_clipboard")

    if re.search(r"\b(cancel[aá]|abort)\b", lower) and re.search(r"\b(apagad|reinici|shutdown)\b", lower):
        return run("power_control", action="abort")
    if re.search(r"\b(apag[aá]|prender|encend[eé]|luces?|foco|interruptor|velador)\b", lower) and re.search(
        r"\b(luz|luces|foco|living|pieza|cuarto|lampara|lámpara|lamparita|velador|enchufe|bombilla)\b",
        lower,
    ):
        entity = "light.living"
        match = re.search(r"\b((?:light|switch|fan)\.[a-z0-9_]+)\b", lower)
        if match:
            entity = match.group(1)
        action = "off" if re.search(r"\bapag", lower) else "on"
        return run("control_device", entity_id=entity, action=action)

    if re.search(
        r"\b(apag[aá]|shutdown)\b.{0,24}\b(pc|computadora|equipo|windows|sistema)\b|"
        r"\b(apaga(?:r)?\s+la\s+(?:pc|computadora|equipo))\b",
        lower,
    ):
        return run("power_control", action="shutdown")
    if re.search(r"\b(reinici[aá]|reboot|restart)\b", lower) and re.search(
        r"\b(pc|computadora|equipo|sistema|windows)\b", lower
    ):
        return run("power_control", action="restart")

    if android:
        phone = _android_hands(lower)
        if phone is not None and not _looks_like_play(lower):
            return run("phone_hands", **phone)

    music = re.search(
        r"(?:poneme|pon[eé]|reproduc[ií]|reproducir|escuchar|play|tirame)\s+"
        r"(?:a\s+reproducir\s+)?"
        r"(?:un\s+tema\s+de\s+|una\s+canci[oó]n\s+(?:de\s+)?|la\s+canci[oó]n\s+(?:de\s+)?|"
        r"el\s+tema\s+(?:de\s+)?|m[uú]sica\s+(?:de\s+)?)?"
        r"(.+?)"
        r"(?:\s+en\s+(?:el\s+)?(spotify|youtube))?\s*$",
        lower,
        re.I,
    )
    if music and not re.search(r"\b(volumen|timer|alarma|linterna|recordatorio)\b", lower):
        platform = (music.group(2) or "spotify").strip()
        query = music.group(1).strip(" .")
        query = re.sub(r"\s+en\s+(el\s+)?(spotify|youtube)$", "", query, flags=re.I).strip()
        query = re.sub(r"^(spotify|youtube)\s+", "", query, flags=re.I).strip()
        apps = {
            "spotify",
            "youtube",
            "whatsapp",
            "telegram",
            "instagram",
            "maps",
            "gmail",
            "chrome",
            "tiktok",
        }
        if query in {"spotify", "youtube", "musica", "música"}:
            target = "youtube" if "youtube" in query else "spotify"
            if android:
                return run("phone_hands", action="open_app", target=target)
            return run("open_app", name=target)
        if query and query not in apps:
            if android:
                action = "youtube" if platform == "youtube" else "music"
                return run("phone_hands", action=action, target=query)
            return run("play_music", query=query, platform=platform)

    if android:
        phone = _android_hands(lower)
        if phone is not None:
            return run("phone_hands", **phone)

    if re.fullmatch(
        r"(diario( de hoy)?|minuta(s)?( de hoy)?|le[eé] el diario|mostr[aá] el diario|"
        r"en qu[eé] me qued[eé]|qu[eé] anot[eé]|bit[aá]cora( de hoy)?)",
        lower,
    ):
        return run("read_daily_journal")

    journal = re.match(
        r"^(?:tom[aá]\s+nota(?:\s+de(?:\s+que)?)?|anot[aá]\s+en\s+el\s+diario(?:\s+que)?|"
        r"bit[aá]cora[:\s]+)\s*(.+)$",
        raw,
        re.I | re.S,
    )
    if journal:
        return run("daily_journal", content=journal.group(1).strip())

    if re.search(r"\b(clima|tiempo|temperatura|llueve|pronostico|pronóstico)\b", lower):
        return run("weather", city=city)

    math = _math(raw)
    if math:
        return run("calculate", expression=math)

    minutes, timer_text = _timer(raw)
    if minutes is not None:
        return run("set_timer", minutes=minutes, text=timer_text)

    if re.search(r"\b(recordatorios|pendientes|timers?)\b", lower) and re.search(
        r"\b(lista|listar|mostr|cuales|cuáles|mis)\b", lower
    ):
        return run("list_reminders")

    cancel = re.search(r"(?:cancel[aeá]|borra[rd]?)\s+(?:el\s+)?recordatorio(?:\s+de)?\s+(.+)", lower)
    if cancel:
        return run("cancel_reminder", query=cancel.group(1).strip())

    if re.fullmatch(r"(notas|mis notas|lista(r)? notas)", lower):
        return run("note", text="")

    note = re.match(r"^(?:anot[aá]|nota[:\s]+|record[aá]\s+esto[:\s]*)\s*(.+)$", raw, re.I | re.S)
    if note:
        return run("note", text=note.group(1).strip())

    remembered = re.match(
        r"^(?:acordate(?:\s+que)?|record[aá]\s+que|remember)\s+(.+?)\s+(?:es|=|:)\s+(.+)$",
        raw,
        re.I | re.S,
    )
    if remembered:
        return run("remember", key=remembered.group(1).strip(), value=remembered.group(2).strip())

    if re.search(r"\b(que sabes|qué sabés|mis datos|memoria)\b", lower):
        return run("recall")

    wiki = re.match(r"^(?:qu[eé]\s+es|qui[eé]n\s+es|wikipedia)\s+(.+)$", raw, re.I)
    if wiki:
        return run("wikipedia", topic=wiki.group(1).strip())

    maps = re.match(
        r"^(?:c[oó]mo\s+llego(?:\s+a)?|mapas?|ruta(?:\s+a)?)\s+(.+)$",
        raw,
        re.I,
    )
    if maps:
        return run("open_maps", destination=maps.group(1).strip(), origin="")

    opened = re.search(
        r"(?:abr[ií]|abrime|abrir|abre|open|lanz[aá]|ejecut[aá]|and[aá]\s+a|"
        r"quiero\s+que\s+abras?|necesito\s+que\s+abras?|pod[eé]s\s+abrir|"
        r"hac[eé](?:me)?\s+(?:el\s+favor\s+de\s+)?abrir)\s+"
        r"(?:la\s+|el\s+|app\s+(?:de\s+)?)?(.+)$",
        raw,
        re.I,
    )
    if opened:
        target = opened.group(1).strip().strip(" .!?")
        target = re.sub(r"\s+(por favor|please)$", "", target, flags=re.I).strip()
        if re.match(r"https?://", target, re.I):
            return run("open_browser", url=target)
        from jarvis.bank_apps import is_banking

        aliases = {"code": "vscode", "vs": "vscode", "navegador": "chrome"}
        key = aliases.get(target.split()[0].lower().rstrip("."), target.lower())
        if is_banking(target) or is_banking(key):
            return "No abro apps bancarias."
        if android:
            return run("phone_hands", action="open_app", target=target)
        return run("open_app", name=key)

    if re.search(r"\b(d[oó]lar(?:es)?|blue|cripto|bitcoin|btc)\b", lower):
        return run("web_search", query=raw, max_results=5)

    search = re.match(
        r"^(?:busca[r]?|busc[aá]|search|noticias(?:\s+de)?|google(?:a[rd]?)?)\s+(.+)$",
        raw,
        re.I,
    )
    if search:
        query = search.group(1).strip()
        if lower.startswith("google"):
            return run("google", query=query)
        return run("web_search", query=query, max_results=5)

    if len(raw) >= 12 and re.search(
        r"\b(noticia|precio|quien gan[oó]|resultado|cuando sale|cuándo)\b",
        lower,
    ):
        return run("web_search", query=raw, max_results=5)

    return None


def local_reply(
    text: str,
    execute: Execute,
    memory: Memory,
    settings: Settings,
    allowed: set[str] | None = None,
    surface: str = "hud",
) -> str:
    hit = try_local_command(text, execute, memory, settings, allowed, surface=surface)
    if hit is not None:
        return hit
    return (
        "Modo local (sin key de Groq): clima, hora, cuentas, notas, timers, Wikipedia y búsqueda.\n"
        "Ejemplos: «clima», «cuánto es 12*1.21», «anotá comprar leche», «timer 10 minutos», "
        "«busca dólar blue».\n"
        f"Para charlar de verdad, pegá una key gratis en Perfil: https://console.groq.com/keys"
    )


def _help(settings: Settings) -> str:
    name = settings.assistant_name
    return (
        f"{name} en modo local, útil sin pagar nada:\n"
        "- Clima: «clima» o «clima en Córdoba»\n"
        "- Hora: «qué hora es»\n"
        "- Cuentas: «cuánto es 250*1.21»\n"
        "- Nota: «anotá llamar al médico» / diario: «tomá nota: backtesting +3%»\n"
        "- Volumen: «volumen al 30»\n"
        "- Timer: «timer 10 minutos» / «pomodoro»\n"
        "- Buscar: «busca dólar blue» / «qué es la inflación»\n"
        "- Ruta: «cómo llego a Palermo»\n"
        "- Apps: «abrí Spotify» / cualquier app instalada (no bancarias)\n"
        "Charla completa: key Groq gratis en Perfil."
    )


def _city(text: str, memory: Memory) -> str:
    match = re.search(r"\b(?:en|de)\s+([A-Za-zÁÉÍÓÚÜáéíóúüñÑ .]{3,40})$", text.strip())
    if match:
        return match.group(1).strip()
    stored = memory.recall("ciudad")
    if stored and not stored.startswith("No fact"):
        return stored
    return "Buenos Aires"


def _math(text: str) -> str | None:
    stripped = text.strip()
    match = re.match(
        r"^(?:calcul[aeá]|cu[aá]nto\s+es|cuanto\s+es|cu[aá]nto\s+da)\s+(.+)$",
        stripped,
        re.I,
    )
    if match:
        return match.group(1).strip()
    compact = stripped.replace(" ", "")
    if re.fullmatch(r"[\d\.\,\+\-\*/\(\)%]+", compact) and re.search(r"[\+\-\*/%]", compact):
        return compact.replace(",", ".")
    return None


def _timer(text: str) -> tuple[float | None, str]:
    lower = text.lower().strip()
    if re.fullmatch(r"pomodoro|foco|timer\s*25", lower):
        return 25.0, "Pomodoro"
    match = re.search(
        r"(?:timer|temporizador|avis[aá]me)\s+(?:en\s+)?(\d+(?:[.,]\d+)?)\s*"
        r"(min|mins|minuto|minutos|hora|horas)\b(?:\s+(?:para|que|:)\s*(.+))?",
        lower,
    )
    if not match:
        match = re.match(
            r"en\s+(\d+(?:[.,]\d+)?)\s*(min|mins|minuto|minutos|hora|horas)\b"
            r"(?:\s+(?:para|que|:)\s*(.+))?",
            lower,
        )
    if not match:
        return None, ""
    amount = float(match.group(1).replace(",", "."))
    unit = match.group(2)
    label = (match.group(3) if match.lastindex and match.lastindex >= 3 else "") or "Timer"
    if unit.startswith("hora"):
        amount *= 60
    return amount, label.strip() or "Timer"


_PHONE_APP = (
    r"spotify|whatsapp|telegram|instagram|youtube|maps|gmail|chrome|"
    r"fotos|photos|c[aá]mara|camera"
)


def _looks_like_play(lower: str) -> bool:
    """True when the user wants a song/search, not just opening an app."""
    if re.search(
        r"\b(canci[oó]n|tema|playlist|album|álbum|reproduc|escuchar|play)\b",
        lower,
    ):
        return True
    if re.search(
        r"\b(poneme|pon[eé]|tirame)\s+(?:un\s+|una\s+|el\s+|la\s+)?(?!spotify\b|youtube\b|whatsapp\b)",
        lower,
    ):
        return True
    return False


def _android_hands(lower: str) -> dict[str, str] | None:
    if re.search(r"\b(linterna|flashlight|torch)\b", lower):
        off = bool(re.search(r"\b(apag|off|sac[aá])\b", lower))
        return {"action": "torch", "target": "off" if off else "on"}
    # Opening an app — do not steal "poneme X" song requests.
    if _looks_like_play(lower) and not re.fullmatch(
        rf"(?:abr[ií]|abrime|abrir|abre|open|lanz[aá])\s+(?:la\s+|el\s+|app\s+(?:de\s+)?)?(?:{_PHONE_APP})\b",
        lower.strip(),
    ):
        if not re.search(
            rf"(?:abr[ií]|abrime|abrir|abre|open|lanz[aá])\s+(?:la\s+|el\s+|app\s+(?:de\s+)?)?({_PHONE_APP})\b",
            lower,
        ):
            return None
    opened = re.search(
        rf"(?:abr[ií]|abrime|abrir|abre|open|lanz[aá]|sac[aá]|pon(?:eme|[eé])?|pr[eé]nd(?:e|[eé])?)\s+"
        rf"(?:la\s+|el\s+|app\s+(?:de\s+)?)?({_PHONE_APP})\b",
        lower,
    )
    if not opened and re.fullmatch(rf"(?:{_PHONE_APP})", lower.strip()):
        opened = re.search(rf"({_PHONE_APP})", lower)
    if not opened:
        return None
    name = opened.group(1)
    if re.match(r"c[aá]mara|camera", name):
        return {"action": "camera"}
    if name in {"fotos", "photos"}:
        return {"action": "gallery"}
    if name in {"maps"}:
        return {"action": "maps", "target": "acá"}
    if name == "youtube":
        return {"action": "open_app", "target": "youtube"}
    return {"action": "open_app", "target": name}


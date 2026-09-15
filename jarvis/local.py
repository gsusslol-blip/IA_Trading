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
    phone = (surface or "hud").strip().lower() in {"android", "ios", "iphone", "ipad"}
    android = phone  # local phone routing (Android + iOS apps)

    def run(tool: str, **args: object) -> str:
        if allowed is not None and tool not in allowed:
            return "Eso en esta cuenta no esta habilitado."
        return execute(tool, json.dumps(args, ensure_ascii=False))

    if re.search(r"\b(ayuda|help|que podes|qué podés|que podes hacer|capacidades|comandos)\b", lower):
        return _help(settings)

    if re.search(r"\b(deshac[eé]r?|undo|arrepent)\b", lower):
        return run("undo_last")

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
        if re.search(r"\b(bluetooth)\b", lower) and re.search(
            r"\b(abr[ií]|ajustes|configuraci[oó]n|settings)\b", lower
        ):
            return run("phone_hands", action="bluetooth")
        if re.search(r"\b(ajustes|configuraci[oó]n|settings)\b", lower) and not re.search(
            r"\b(wifi|wi[\-\s]?fi|app|ilaria)\b", lower
        ):
            return run("phone_hands", action="settings")
        # Phone volume / mute / media — never PC pycaw/VK.
        vol_phone = re.search(
            r"(?:volumen|volume)(?:\s+(?:al|a|en|del?))?\s+(\d{1,3})\s*%?",
            lower,
        )
        if vol_phone:
            return run("phone_hands", action="volume", target=str(int(vol_phone.group(1))))
        if re.search(
            r"\b(sub[ií]|aument[aá]|m[aá]s|arriba)\b.{0,16}\b(volumen|volume|sonido)\b|"
            r"\b(volumen|volume|sonido)\b.{0,12}\b(sub[ií]|aument[aá]|m[aá]s|arriba)\b|"
            r"\bvol[\+\s]*up\b",
            lower,
        ):
            return run("phone_hands", action="volume", target="up")
        if re.search(
            r"\b(baj[aá]|reduc[ií]|menos|abajo)\b.{0,16}\b(volumen|volume|sonido)\b|"
            r"\b(volumen|volume|sonido)\b.{0,12}\b(baj[aá]|reduc[ií]|menos|abajo)\b|"
            r"\bvol[\-\s]*down\b",
            lower,
        ):
            return run("phone_hands", action="volume", target="down")
        if re.search(r"\b(silenci(?:ar|[oaá])|mute(?:ar)?|sin\s+sonido)\b", lower):
            return run("phone_hands", action="volume", target="mute")
        if re.search(
            r"\b(captura(?:\s+de\s+pantalla)?|screenshot|sac[aá](?:me)?\s+(?:una\s+)?(?:foto|captura)|"
            r"foto\s+de\s+pantalla)\b",
            lower,
        ):
            return run("phone_hands", action="screenshot")
        clip_set_p = re.match(
            r"^(?:copi[aá]|copiar|al\s+portapapeles|clipboard)\s*[:\-]?\s+(.+)$",
            raw,
            re.I | re.S,
        )
        if clip_set_p and not re.search(r"\b(le[eé]|mostr|qu[eé] hay)\b", lower):
            return run("phone_hands", action="clipboard", target="", text=clip_set_p.group(1).strip())
        if re.search(
            r"\b(portapapeles|clipboard|lo\s+que\s+copi[eé]|qu[eé]\s+copi[eé])\b",
            lower,
        ):
            return run("phone_hands", action="clipboard_get")
        if re.search(r"\b(contactos)\b", lower) and re.search(r"\b(abr[ií]|mostr|lista)\b", lower):
            return run("phone_hands", action="contacts")
        if re.search(r"\b(calendario|agenda)\b", lower) and re.search(
            r"\b(abr[ií]|mostr)\b", lower
        ):
            return run("phone_hands", action="calendar")
        if re.search(r"\b(compart[ií]|share)\b", lower):
            body = re.sub(r"^.*\b(?:compart[ií]|share)\s+", "", raw, flags=re.I).strip()
            if body:
                return run("phone_hands", action="share", text=body)
        alarm = re.search(
            r"\b(?:alarma|alarm)\s+(?:a\s+las\s+|para\s+las\s+|a\s+)?(\d{1,2})(?:[:\.](\d{2}))?\b",
            lower,
        )
        if alarm:
            hh = int(alarm.group(1))
            mm = int(alarm.group(2) or "0")
            return run("phone_hands", action="alarm", target=f"{hh}:{mm:02d}")
        call = re.search(
            r"(?:llam[aá]|marca[lr]?|disc[aá])\s+(?:al\s+|a\s+)?([+\d][\d\s\-()]{6,})",
            raw,
            re.I,
        )
        if call:
            return run("phone_hands", action="call", target=re.sub(r"[^\d+]", "", call.group(1)))
        sms = re.search(
            r"(?:sms|mensaje(?:\s+de\s+texto)?)\s+(?:a|al)\s+([+\d][\d\s\-()]{6,})\s*[:\-]?\s*(.*)$",
            raw,
            re.I | re.S,
        )
        if sms:
            return run(
                "phone_hands",
                action="sms",
                target=re.sub(r"[^\d+]", "", sms.group(1)),
                text=(sms.group(2) or "").strip(),
            )

    vol = re.search(
        r"(?:volumen|volume)(?:\s+(?:al|a|en|del?))?\s+(\d{1,3})\s*%?",
        lower,
    )
    if vol:
        return run("set_volume", level=int(vol.group(1)))
    if re.search(
        r"\b(sub[ií]|aument[aá]|m[aá]s|arriba)\b.{0,16}\b(volumen|volume|sonido)\b|"
        r"\b(volumen|volume|sonido)\b.{0,12}\b(sub[ií]|aument[aá]|m[aá]s|arriba)\b|"
        r"\bvol[\+\s]*up\b",
        lower,
    ):
        return run("media", action="vol_up")
    if re.search(
        r"\b(baj[aá]|reduc[ií]|menos|abajo)\b.{0,16}\b(volumen|volume|sonido)\b|"
        r"\b(volumen|volume|sonido)\b.{0,12}\b(baj[aá]|reduc[ií]|menos|abajo)\b|"
        r"\bvol[\-\s]*down\b",
        lower,
    ):
        return run("media", action="vol_down")

    if re.search(r"\b(silenci(?:ar|[oaá])|mute(?:ar)?|sin\s+sonido)\b", lower):
        if android:
            return run("phone_hands", action="volume", target="mute")
        return run("media", action="mute")
    if re.search(
        r"\b(desilenci|unmute|con\s+sonido|sac[aá]\s+el\s+silencio|quit[aá]\s+el\s+silencio)\b",
        lower,
    ):
        if android:
            return run("phone_hands", action="volume", target="unmute")
        return run("media", action="mute")

    if re.fullmatch(r"(escritorio|desktop)", lower):
        if android:
            return "Eso es de la PC. Pedilo desde el HUD del escritorio."
        return run("open_folder", name="escritorio")
    if re.fullmatch(r"(descargas|downloads)", lower):
        if android:
            return "Eso es de la PC. Pedilo desde el HUD del escritorio."
        return run("open_folder", name="descargas")
    if re.fullmatch(r"(documentos|documents)", lower):
        if android:
            return "Eso es de la PC. Pedilo desde el HUD del escritorio."
        return run("open_folder", name="documentos")

    media_key = _media_key(lower)
    if media_key:
        if android:
            # Phone: map media keys to music / open Spotify when possible.
            if media_key in {"play_pause", "next", "prev", "stop"}:
                return run("phone_hands", action="music", target="")
            if media_key == "mute":
                return run("phone_hands", action="volume", target="mute")
        return run("media", action=media_key)

    if re.search(
        r"\b(captura(?:\s+de\s+pantalla)?|screenshot|sac[aá](?:me)?\s+(?:una\s+)?(?:foto|captura)|"
        r"foto\s+de\s+pantalla|imprimir\s+pantalla)\b",
        lower,
    ):
        return run("screenshot")

    folder = re.search(
        r"(?:abr[ií]|abrime|abrir|abre|open|mostr[aá]|and[aá]\s+a)\s+"
        r"(?:la\s+|el\s+)?(?:carpeta\s+(?:de\s+)?)?(escritorio|desktop|descargas|downloads|"
        r"documentos|documents|workspace|mis\s+documentos)\b",
        lower,
    )
    if folder:
        if android:
            return "Eso es de la PC. Pedilo desde el HUD del escritorio."
        name = folder.group(1).replace("mis ", "")
        return run("open_folder", name=name)

    if re.search(
        r"\b(qu[eé]\s+hay\s+en\s+(?:el\s+)?workspace|list[aá]\s+(?:los\s+)?archivos|"
        r"archivos\s+del\s+workspace|mostr[aá]\s+(?:el\s+)?workspace)\b",
        lower,
    ):
        return run("list_files", relative="")

    clip_set = re.match(
        r"^(?:copi[aá]|copiar|al\s+portapapeles|clipboard)\s*[:\-]?\s+(.+)$",
        raw,
        re.I | re.S,
    )
    if clip_set and not re.search(r"\b(le[eé]|mostr|qu[eé] hay)\b", lower):
        return run("set_clipboard", text=clip_set.group(1).strip())

    if re.search(
        r"\b(portapapeles|clipboard|lo\s+que\s+copi[eé]|qu[eé]\s+copi[eé])\b",
        lower,
    ) and (
        re.search(r"\b(le[eé]|mostr|qu[eé] hay|dec[ií]me|peg)\b", lower)
        or re.fullmatch(r"(portapapeles|clipboard|qu[eé]\s+copi[eé]|lo\s+que\s+copi[eé])", lower)
    ):
        return run("get_clipboard")

    if re.search(
        r"\b(cancel[aá]|abort|abort[aá])\b.{0,20}\b(apagad|reinici|shutdown)\b|"
        r"\b(cancel[aá]\s+el\s+apagado|no\s+apagues)\b",
        lower,
    ):
        return run("power_control", action="abort")

    if re.search(
        r"\b(bloque[aá]|bloquear|lock)\b.{0,20}\b(pc|computadora|pantalla|sesi[oó]n|windows)\b|"
        r"\b(bloque[aá]\s+la\s+pantalla|lock\s+screen|win\s*\+\s*l)\b",
        lower,
    ):
        if android:
            return run("phone_hands", action="lock")
        return run("power_control", action="lock")

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
        if android:
            return "Apagar la PC solo desde el HUD del escritorio (dueño)."
        return run("power_control", action="shutdown")
    if re.search(r"\b(reinici[aá]|reboot|restart)\b", lower) and re.search(
        r"\b(pc|computadora|equipo|sistema|windows)\b", lower
    ):
        if android:
            return "Reiniciar la PC solo desde el HUD del escritorio (dueño)."
        return run("power_control", action="restart")

    wa = _whatsapp_draft(raw, lower)
    if wa is not None:
        if android:
            return run("phone_hands", action="whatsapp", target=wa[0], text=wa[1])
        return run("compose_whatsapp", phone=wa[0], text=wa[1])

    yt = re.match(
        r"^(?:busc[aá]|busca[r]?|pon[eé]|poneme|reproduc[ií])\s+(?:en\s+)?youtube\s+(.+)$",
        raw,
        re.I,
    )
    if yt:
        q = yt.group(1).strip()
        if android:
            return run("phone_hands", action="youtube", target=q)
        return run("play_music", query=q, platform="youtube")

    translate = re.match(
        r"^(?:traduc[ií]|traducir|translate)\s+(?:al?\s+\w+\s+)?(.+)$",
        raw,
        re.I,
    )
    if translate:
        q = translate.group(1).strip()
        if android:
            return run("phone_hands", action="translate", text=q)
        return run(
            "open_browser",
            url=f"https://translate.google.com/?sl=auto&tl=es&text={_url_quote(q)}&op=translate",
        )

    define = re.match(r"^(?:defin[ií]|definici[oó]n\s+de|significado\s+de)\s+(.+)$", raw, re.I)
    if define:
        return run("wikipedia", topic=define.group(1).strip())

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

    if re.fullmatch(r"(clima|tiempo|temperatura)", lower):
        return run("weather", city=city)

    if re.fullmatch(r"(estado|status|sistema)", lower):
        return run("system_status")

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
        r"^(?:c[oó]mo\s+llego(?:\s+a)?|mapas?|ruta(?:\s+a)?|llevame\s+a|ll[eé]vame\s+a|"
        r"direcciones?\s+(?:a|para))\s+(.+)$",
        raw,
        re.I,
    )
    if maps:
        dest = maps.group(1).strip()
        if android:
            return run("phone_hands", action="maps", target=dest)
        return run("open_maps", destination=dest, origin="")

    if re.fullmatch(r"https?://\S+", raw.strip(), re.I):
        url = raw.strip()
        if android:
            return run("phone_hands", action="browser", target=url)
        return run("open_browser", url=url)

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
        hit = _open_target(target, run, android=android)
        if hit is not None:
            return hit

    bare = _bare_app(lower)
    if bare is not None:
        hit = _open_target(bare, run, android=android)
        if hit is not None:
            return hit

    if re.search(r"\b(d[oó]lar(?:es)?|blue|cripto|bitcoin|btc|euro|eur)\b", lower):
        return run("web_search", query=raw, max_results=5)

    search = re.match(
        r"^(?:busca[r]?|busc[aá]|search|noticias(?:\s+de)?|google(?:a[rd]?)?)\s+(.+)$",
        raw,
        re.I,
    )
    if search:
        query = search.group(1).strip()
        if lower.startswith("google"):
            if android:
                return run("phone_hands", action="search", target=query)
            return run("google", query=query)
        return run("web_search", query=query, max_results=5)

    if len(raw) >= 12 and re.search(
        r"\b(noticia|precio|quien gan[oó]|resultado|cuando sale|cuándo|c[oó]mo\s+se\s+hace)\b",
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
        f"{name} — comandos locales (sin esperar al LLM):\n"
        "- Hora / clima: «qué hora es», «clima en Córdoba»\n"
        "- Cuentas: «cuánto es 250*1.21»\n"
        "- Notas / diario: «anotá comprar leche», «tomá nota: …», «diario»\n"
        "- Memoria: «acordate que mi team es River», «qué sabés»\n"
        "- Timers: «timer 10 minutos», «avisame en 5 minutos», «pomodoro»\n"
        "- Buscar: «busca dólar blue», «google receta de milanesa», «qué es X»\n"
        "- Traducir / definir: «traducí hello world», «definí inflación»\n"
        "- Ruta: «cómo llego a Palermo»\n"
        "- Apps: «abrí Spotify», «chrome», «calculadora», «youtube», «gmail»\n"
        "- Carpetas: «abrí descargas / escritorio / documentos»\n"
        "- Audio: «volumen al 30», «subí el volumen», «silenciá», «siguiente», «pausá»\n"
        "- Música: «poneme Cerati», «buscá en youtube Bohemian Rhapsody»\n"
        "- Pantalla: «sacá una captura», «bloqueá la pc»\n"
        "- Portapapeles: «copiá hola», «qué hay en el portapapeles»\n"
        "- Deshacer: «deshacer» (volumen/portapapeles, ~30s)\n"
        "- WhatsApp borrador: «whatsapp a 54911…: llegué»\n"
        "- PC: «estado de la pc», «apagá la pc», «cancelá el apagado»\n"
        "Charla completa: key Groq en Perfil."
    )


def _url_quote(text: str) -> str:
    from urllib.parse import quote

    return quote(text.strip()[:500])


def _media_key(lower: str) -> str | None:
    """Map natural language to Windows media VK names used by actions.media."""
    mediaish = bool(
        re.search(
            r"\b(m[uú]sica|canci[oó]n|tema|spotify|media|track|pista|video|"
            r"reproduc|paus|play|siguiente|anterior|next|prev|stop|deten)\b",
            lower,
        )
    )
    short = lower.strip() in {
        "play",
        "pause",
        "pausá",
        "pausa",
        "siguiente",
        "anterior",
        "stop",
        "detener",
        "next",
        "prev",
        "mute",
        "silencio",
        "silenciá",
        "silencia",
    }
    if not mediaish and not short:
        return None
    if re.search(r"\b(siguiente|next|pr[oó]xima)\b", lower):
        return "next"
    if re.search(r"\b(anterior|previous|prev|atr[aá]s)\b", lower):
        return "prev"
    if re.search(r"\b(silenci|mute)\b", lower):
        return "mute"
    if re.search(r"\b(stop|deten[eé]r?|parar)\b", lower):
        return "stop"
    if re.search(r"\b(paus[aá]|pause|play|reproduc[ií]|continuar|segu[ií])\b", lower):
        return "play_pause"
    return None


def _whatsapp_draft(raw: str, lower: str) -> tuple[str, str] | None:
    match = re.search(
        r"(?:whats?app|wpp|wasap)\s+(?:a|al|para)?\s*(\+?\d[\d\s\-]{7,18})\s*[:\-]\s*(.+)$",
        raw,
        re.I | re.S,
    )
    if not match:
        match = re.search(
            r"(?:mand[aá](?:le)?|envi[aá](?:le)?)\s+(?:un\s+)?(?:whats?app|wpp|mensaje)\s+"
            r"(?:a|al|para)\s+(\+?\d[\d\s\-]{7,18})\s+(?:que|diciendo|con|:)\s*(.+)$",
            raw,
            re.I | re.S,
        )
    if not match:
        return None
    phone = re.sub(r"\D", "", match.group(1))
    text = match.group(2).strip()
    if len(phone) < 8 or not text:
        return None
    return phone, text


_APP_ALIASES = {
    "code": "vscode",
    "vs": "vscode",
    "navegador": "chrome",
    "internet": "chrome",
    "google chrome": "chrome",
    "bloc": "notepad",
    "bloc de notas": "notepad",
    "notas de windows": "notepad",
    "calc": "calculadora",
    "explorador": "explorer",
    "archivos": "explorer",
    "administrador": "taskmgr",
    "task manager": "taskmgr",
    "config": "configuracion",
    "ajustes": "configuracion",
    "corte": "recortes",
    "recortadora": "recortes",
}

_WEB_TARGETS = {
    "youtube": "https://www.youtube.com",
    "yt": "https://www.youtube.com",
    "gmail": "https://mail.google.com",
    "correo": "https://mail.google.com",
    "mail": "https://mail.google.com",
    "maps": "https://maps.google.com",
    "mapas": "https://maps.google.com",
    "drive": "https://drive.google.com",
    "docs": "https://docs.google.com",
    "netflix": "https://www.netflix.com",
    "twitch": "https://www.twitch.tv",
    "github": "https://github.com",
    "chatgpt": "https://chatgpt.com",
}

_BARE_APPS = {
    "spotify",
    "chrome",
    "edge",
    "firefox",
    "notepad",
    "calculadora",
    "calculator",
    "paint",
    "discord",
    "telegram",
    "whatsapp",
    "steam",
    "cursor",
    "vscode",
    "excel",
    "word",
    "explorer",
    "youtube",
    "gmail",
    "maps",
    "netflix",
    "twitch",
    "github",
    "taskmgr",
    "terminal",
    "powershell",
    "wifi",
    "bluetooth",
    "configuracion",
    "configuración",
}


def _bare_app(lower: str) -> str | None:
    key = lower.strip().rstrip(".!?")
    if key in _BARE_APPS or key in _APP_ALIASES or key in _WEB_TARGETS:
        return key
    return None


def _open_target(target: str, run: Callable[..., str], *, android: bool) -> str | None:
    from jarvis.bank_apps import is_banking

    if re.match(r"https?://", target, re.I):
        if android:
            return run("phone_hands", action="browser", target=target)
        return run("open_browser", url=target)
    lowered = target.lower().strip()
    if lowered in _WEB_TARGETS:
        if android:
            return run("phone_hands", action="browser", target=_WEB_TARGETS[lowered])
        return run("open_browser", url=_WEB_TARGETS[lowered])
    if is_banking(target) or is_banking(lowered):
        return "No abro apps bancarias."
    key = _APP_ALIASES.get(lowered)
    if key is None:
        first = lowered.split()[0].rstrip(".")
        key = _APP_ALIASES.get(first, lowered)
    if android:
        return run("phone_hands", action="open_app", target=target)
    return run("open_app", name=key)


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
        r"(?:timer|temporizador|avis[aá]me|record[aá]me|despert[aá]me)\s+(?:en\s+)?(\d+(?:[.,]\d+)?)\s*"
        r"(min|mins|minuto|minutos|hora|horas|seg|segs|segundo|segundos)\b(?:\s+(?:para|que|:|de)\s*(.+))?",
        lower,
    )
    if not match:
        match = re.match(
            r"en\s+(\d+(?:[.,]\d+)?)\s*(min|mins|minuto|minutos|hora|horas|seg|segs|segundo|segundos)\b"
            r"(?:\s+(?:para|que|:|de)\s*(.+))?",
            lower,
        )
    if not match:
        return None, ""
    amount = float(match.group(1).replace(",", "."))
    unit = match.group(2)
    label = (match.group(3) if match.lastindex and match.lastindex >= 3 else "") or "Timer"
    if unit.startswith("hora"):
        amount *= 60
    elif unit.startswith("seg"):
        amount /= 60.0
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


"""
Filtro de noticias macro: calendario económico vía XML/RSS ligero (sin API de pago).

Por defecto usa el feed semanal público de Forex Factory (XML vía faireconomy.media).
DailyFX/IG no ofrece un RSS oficial del calendario; podés override con ``IA_NEWS_FEED_URL``.

Solo stdlib (urllib + xml.etree); zonas horarias con ``zoneinfo``.
"""

from __future__ import annotations

import os
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_DEFAULT_FEED = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"

_CACHE_EVENTS_UTC: list[datetime] = []
_CACHE_FETCH_MONO: float = 0.0
_CACHE_LAST_ERROR: str = ""


def news_filter_enabled() -> bool:
    return os.environ.get("IA_NEWS_FILTER_ENABLE", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _feed_url() -> str:
    return (
        os.environ.get("IA_NEWS_FEED_URL", "").strip()
        or os.environ.get("IA_NEWS_RSS_URL", "").strip()
        or _DEFAULT_FEED
    )


def _calendar_tz() -> ZoneInfo:
    name = os.environ.get("IA_NEWS_CALENDAR_TZ", "America/New_York").strip() or "America/New_York"
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("America/New_York")


def _impact_is_high(raw: str) -> bool:
    t = (raw or "").strip().lower()
    if t in ("high", "3", "red"):
        return True
    allow = os.environ.get("IA_NEWS_IMPACT_LEVELS", "high").strip().lower()
    levels = {x.strip() for x in allow.split(",") if x.strip()}
    return t in levels


def _currencies_wanted() -> set[str]:
    raw = os.environ.get("IA_NEWS_CURRENCIES", "USD").strip() or "USD"
    return {c.strip().upper() for c in raw.split(",") if c.strip()}


def _parse_event_datetime(date_s: str, time_s: str, tz: ZoneInfo) -> datetime | None:
    ds = (date_s or "").strip()
    if not ds:
        return None
    try:
        local_date = datetime.strptime(ds, "%m-%d-%Y")
    except ValueError:
        return None

    ts = (time_s or "").strip()
    skip_times = ("", "all day", "tentative")
    if ts.lower() in skip_times or ts.lower().startswith("day "):
        local_dt = local_date.replace(hour=12, minute=0, second=0, microsecond=0)
    else:
        parsed = None
        for fmt in ("%I:%M%p", "%I:%M %p", "%H:%M"):
            try:
                tpart = datetime.strptime(ts, fmt)
                parsed = local_date.replace(
                    hour=tpart.hour,
                    minute=tpart.minute,
                    second=0,
                    microsecond=0,
                )
                break
            except ValueError:
                continue
        if parsed is None:
            return None
        local_dt = parsed

    return local_dt.replace(tzinfo=tz).astimezone(timezone.utc)


def _fetch_feed_xml(url: str, timeout_s: float) -> bytes | None:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": os.environ.get("IA_NEWS_USER_AGENT", "IA_Trading-news/1")},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            if int(getattr(resp, "status", 200) or 200) != 200:
                return None
            return resp.read()
    except urllib.error.HTTPError as e:
        global _CACHE_LAST_ERROR
        _CACHE_LAST_ERROR = f"HTTP {e.code}"
        return None
    except Exception as e:
        _CACHE_LAST_ERROR = str(e)
        return None


def _parse_forexfactory_weekly_xml(payload: bytes, tz: ZoneInfo) -> list[datetime]:
    """Formato ``weeklyevents`` / hijos con ``country``, ``date``, ``time``, ``impact``."""
    out: list[datetime] = []
    root = ET.fromstring(payload)
    wanted_ccy = _currencies_wanted()
    for ev in root.findall("event"):
        country = (ev.findtext("country") or "").strip().upper()
        if country not in wanted_ccy:
            continue
        impact = ev.findtext("impact") or ""
        if not _impact_is_high(impact):
            continue
        dt = _parse_event_datetime(ev.findtext("date") or "", ev.findtext("time") or "", tz)
        if dt is not None:
            out.append(dt)
    return out


def _parse_generic_rss_xml(payload: bytes, tz: ZoneInfo) -> list[datetime]:
    """
    Intento genérico para RSS/Atom con extensiones ``currency`` / ``importance`` / ``date``.
    Útil si en el futuro hay un feed DailyFX con esos tags.
    """
    out: list[datetime] = []
    root = ET.fromstring(payload)
    items = root.findall(".//item") or root.findall(".//{*}entry")
    wanted_ccy = _currencies_wanted()
    for item in items:
        ccy = (item.findtext("currency") or item.findtext("{*}currency") or "").strip().upper()
        if not ccy:
            for child in item:
                tag = child.tag.split("}")[-1].lower()
                if tag == "currency" and child.text:
                    ccy = child.text.strip().upper()
                    break
        if ccy and ccy not in wanted_ccy:
            continue
        imp = (item.findtext("importance") or item.findtext("{*}importance") or "").strip()
        if imp and not _impact_is_high(imp):
            continue
        date_raw = item.findtext("date") or item.findtext("pubDate") or ""
        if not date_raw:
            continue
        dt = None
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%m-%d-%Y %I:%M%p"):
            try:
                local = datetime.strptime(date_raw.strip()[:19], fmt[: len(date_raw.strip())])
                if fmt.endswith("Z"):
                    dt = local.replace(tzinfo=timezone.utc)
                else:
                    dt = local.replace(tzinfo=tz).astimezone(timezone.utc)
                break
            except ValueError:
                continue
        if dt is not None:
            out.append(dt)
    return out


def obtener_noticias_alto_impacto(
    *,
    url: str | None = None,
    timeout_s: float | None = None,
) -> list[datetime]:
    """
    Descarga el calendario y devuelve instantes UTC de eventos de alto impacto (monedas filtradas).
    """
    global _CACHE_LAST_ERROR
    if not news_filter_enabled():
        return []

    feed = url or _feed_url()
    try:
        to = float(os.environ.get("IA_NEWS_FETCH_TIMEOUT_S", "12").strip() or "12")
    except ValueError:
        to = 12.0
    if timeout_s is not None:
        to = float(timeout_s)

    raw = _fetch_feed_xml(feed, to)
    if not raw:
        print(f"[news] No se pudo descargar calendario ({_CACHE_LAST_ERROR or 'sin datos'}).", flush=True)
        return list(_CACHE_EVENTS_UTC)

    tz = _calendar_tz()
    try:
        if b"<weeklyevents" in raw[:800] or b"<event>" in raw[:4000]:
            events = _parse_forexfactory_weekly_xml(raw, tz)
        else:
            events = _parse_generic_rss_xml(raw, tz)
        events.sort()
        _CACHE_LAST_ERROR = ""
        return events
    except ET.ParseError as e:
        _CACHE_LAST_ERROR = f"XML: {e}"
        print(f"[news] Error parseando calendario: {e}", flush=True)
        return list(_CACHE_EVENTS_UTC)


def refresh_high_impact_cache(force: bool = False) -> list[datetime]:
    """Actualiza caché en memoria como máximo cada ``IA_NEWS_CACHE_TTL_S`` (default 3600)."""
    global _CACHE_EVENTS_UTC, _CACHE_FETCH_MONO
    if not news_filter_enabled():
        return []

    try:
        ttl = float(os.environ.get("IA_NEWS_CACHE_TTL_S", "3600").strip() or "3600")
    except ValueError:
        ttl = 3600.0
    ttl = max(300.0, ttl)
    now = time.monotonic()
    if not force and _CACHE_FETCH_MONO > 0 and (now - _CACHE_FETCH_MONO) < ttl:
        return list(_CACHE_EVENTS_UTC)

    events = obtener_noticias_alto_impacto()
    _CACHE_EVENTS_UTC = events
    _CACHE_FETCH_MONO = now
    print(
        f"[news] Calendario actualizado: {len(events)} eventos "
        f"({','.join(sorted(_currencies_wanted()))} alto impacto).",
        flush=True,
    )
    return list(_CACHE_EVENTS_UTC)


def get_cached_high_impact_events() -> list[datetime]:
    return list(_CACHE_EVENTS_UTC)


def verificar_bloqueo_por_noticias(
    noticias_lista: list[datetime] | None = None,
    *,
    ventana_minutos: int | None = None,
) -> bool:
    """
    True si ``now`` (UTC) está dentro de ±``ventana_minutos`` de algún evento cacheado.
    """
    if not news_filter_enabled():
        return False
    events = noticias_lista if noticias_lista is not None else _CACHE_EVENTS_UTC
    if not events:
        return False

    try:
        win = int(
            os.environ.get("IA_NEWS_WINDOW_MIN", str(ventana_minutos or 15)).strip()
            or str(ventana_minutos or 15)
        )
    except ValueError:
        win = ventana_minutos or 15
    win = max(1, min(120, win))

    ahora = datetime.now(timezone.utc)
    delta = timedelta(minutes=win)
    for hora_noticia in events:
        if hora_noticia - delta <= ahora <= hora_noticia + delta:
            return True
    return False


def describe_active_news_block() -> str:
    """Texto corto del evento más cercano (para logs/Telegram)."""
    events = _CACHE_EVENTS_UTC
    if not events:
        return "evento macro USD"
    ahora = datetime.now(timezone.utc)
    nearest = min(events, key=lambda t: abs((t - ahora).total_seconds()))
    return nearest.strftime("%Y-%m-%d %H:%M UTC")

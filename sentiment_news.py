"""
Sentimiento de titulares (TextBlob) como filtro opcional para alinear técnica con “ánimo” del texto.

- Sin dependencias extra: polaridad 0 (neutral), no bloquea.
- Con `pip install textblob`: polaridad media de titulares (-1 … 1).
- Con `NEWS_API_KEY` (newsapi.org): intenta titulares reales vía HTTPS.

Variables .env:
  NEWS_API_KEY          — opcional (NewsAPI)
  SENTIMENT_POS_THRESHOLD   — default 0.1 (≥ → sesgo alcista)
  SENTIMENT_NEG_THRESHOLD   — default -0.1 (≤ → sesgo bajista)
  SENTIMENT_VERBOSE=0       — imprimir diagnósticos
"""

from __future__ import annotations

import os
from typing import Any

from local_env import load_env_file


def _textblob_available() -> Any:
    try:
        from textblob import TextBlob

        return TextBlob
    except ImportError:
        return None


def _news_query_for_symbol(activo: str) -> str:
    u = activo.upper()
    if "XAU" in u or "GOLD" in u:
        return os.environ.get("SENTIMENT_QUERY_XAU", "gold price OR XAUUSD")
    return os.environ.get("SENTIMENT_QUERY_INDEX", "dow jones OR DJIA OR stock market")


def _demo_headlines(activo: str) -> list[str]:
    """Titulares de ejemplo solo si no hay API (modo demostración)."""
    u = activo.upper()
    if "XAU" in u or "GOLD" in u:
        return [
            "Gold slides as dollar strengthens after Fed comments",
            "Investors seek safety in gold amid geopolitical tensions",
        ]
    return [
        "Wall Street futures dip after earnings warnings",
        "Dow industrials rally on tech sector strength",
    ]


def _fetch_headlines_newsapi(query: str, api_key: str) -> list[str]:
    import urllib.error
    import urllib.parse
    import urllib.request

    params = urllib.parse.urlencode(
        {
            "q": query,
            "language": "en",
            "pageSize": int(os.environ.get("SENTIMENT_NEWS_PAGE_SIZE", "10")),
            "apiKey": api_key,
        }
    )
    url = f"https://newsapi.org/v2/everything?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "IA_Trading-sentiment/1"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    import json

    data = json.loads(raw)
    arts = data.get("articles") or []
    out = [str(a.get("title") or "").strip() for a in arts]
    return [t for t in out if t]


def analizar_sentimiento_noticias(activo: str) -> float:
    """
    Polaridad media entre -1 y 1. Sin TextBlob o sin titulares → 0.0.
    """
    load_env_file()
    TextBlob = _textblob_available()
    if TextBlob is None:
        return 0.0

    headlines: list[str] = []
    api_key = os.environ.get("NEWS_API_KEY", "").strip()
    query = _news_query_for_symbol(activo)
    if api_key:
        try:
            headlines = _fetch_headlines_newsapi(query, api_key)
        except Exception:
            headlines = []
    if not headlines:
        headlines = _demo_headlines(activo)

    scores: list[float] = []
    for t in headlines:
        try:
            scores.append(float(TextBlob(t).sentiment.polarity))
        except Exception:
            continue
    if not scores:
        return 0.0
    return sum(scores) / len(scores)


def obtener_veredicto_final(simbolo: str, *, verbose: bool | None = None) -> str:
    """
    SOLO_COMPRAS | SOLO_VENTAS | NEUTRAL
    """
    if verbose is None:
        verbose = os.environ.get("SENTIMENT_VERBOSE", "0").strip().lower() in (
            "1",
            "true",
            "yes",
        )
    try:
        pos_th = float(os.environ.get("SENTIMENT_POS_THRESHOLD", "0.1"))
    except ValueError:
        pos_th = 0.1
    try:
        neg_th = float(os.environ.get("SENTIMENT_NEG_THRESHOLD", "-0.1"))
    except ValueError:
        neg_th = -0.1

    s = analizar_sentimiento_noticias(simbolo)
    if s > pos_th:
        if verbose:
            print(f"[sentiment] {simbolo}: alcista ({s:.3f})")
        return "SOLO_COMPRAS"
    if s < neg_th:
        if verbose:
            print(f"[sentiment] {simbolo}: bajista ({s:.3f})")
        return "SOLO_VENTAS"
    if verbose:
        print(f"[sentiment] {simbolo}: neutral ({s:.3f})")
    return "NEUTRAL"


def sentiment_allows_trade(sym: str, analizar_ia_result: str) -> bool:
    """True si el veredicto de sentimiento no contradice la señal técnica."""
    v = obtener_veredicto_final(sym, verbose=False)
    if "COMPRA CONFIRMADA" in analizar_ia_result:
        return v != "SOLO_VENTAS"
    if "VENTA CONFIRMADA" in analizar_ia_result:
        return v != "SOLO_COMPRAS"
    return True


def analizar_sentimiento_basico(activo: str) -> str:
    """
    Sentimiento binario como en el snippet de ejemplo: **ALCISTA** si la polaridad media
    de titulares es > 0; si no **BAJISTA** (incluye neutro y negativo).
    Los titulares vienen de NewsAPI si hay `NEWS_API_KEY`, si no del set demo en este módulo.
    """
    p = analizar_sentimiento_noticias(activo)
    return "ALCISTA" if p > 0 else "BAJISTA"

"""Refuse banking / payment-bank apps. Names only; no bypass of OS auth."""

from __future__ import annotations

import re
import unicodedata

_SHORT = (
    "bank",
    "bna",
    "bbva",
    "hsbc",
    "icbc",
    "itau",
    "n26",
    "modo",
    "uala",
    "reba",
    "prex",
    "wise",
    "bind",
)

_LONG = (
    "banco",
    "bancar",
    "banking",
    "mbanking",
    "mercadopago",
    "mercado pago",
    "brubank",
    "naranjax",
    "naranja x",
    "galicia",
    "santander",
    "hipotecario",
    "credicoop",
    "supervielle",
    "personalpay",
    "personal pay",
    "rebanking",
    "paypal",
    "revolut",
    "citibank",
    "openbank",
    "nubank",
    "cuentadni",
    "bnaplus",
    "banca movil",
    "bancamovil",
    "homebanking",
    "home banking",
)

_PACK_BITS = (
    "mercadopago",
    "brubank",
    "naranjax",
    "uala",
    "galicia",
    "santander",
    "bbva",
    "hsbc",
    "icbc",
    "bancamovil",
    "mbanking",
    "personalpay",
    "rebanking",
    "paypal",
    "revolut",
    "walletnfcrel",
    "bnaplus",
    "hipotecario",
    "credicoop",
    "supervielle",
    "openbank",
    "nubank",
    "cuentadni",
    "comafi",
    "patagoniabank",
    "banco",
    ".bank.",
    "banking",
)


def fold(text: str) -> str:
    raw = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(ch for ch in raw if unicodedata.category(ch) != "Mn")


def is_banking(name: str) -> bool:
    blob = fold(name)
    if not blob.strip():
        return False
    packed = blob.replace(" ", "")
    for bit in _PACK_BITS:
        if bit in blob or bit in packed:
            return True
    for needle in _LONG:
        if needle in blob or needle.replace(" ", "") in packed:
            return True
    for token in _SHORT:
        if re.search(rf"(^|[^a-z0-9]){re.escape(token)}([^a-z0-9]|$)", blob):
            return True
    return False

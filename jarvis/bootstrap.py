"""Create the single Owner account for this PC."""

from __future__ import annotations

import os
import secrets
from jarvis.accounts import AccountStore
from jarvis.config import DATA_DIR
from jarvis.packs import PACKS

OWNER_FILE = DATA_DIR / "OWNER_CREDENTIALS.txt"
ALL_PACKS = list(PACKS.keys())


def should_lock_owner() -> bool:
    """Only this PC is locked if OWNER_USERNAME is set. Public copies stay open."""
    return bool(os.getenv("OWNER_USERNAME", "").strip())


def ensure_owner(accounts: AccountStore) -> str:
    username = (os.getenv("OWNER_USERNAME") or "gsuss").strip().lower()
    existing = accounts.get_by_username(username)
    created = False
    password = os.getenv("OWNER_PASSWORD", "").strip()
    if existing is None:
        if not password:
            password = secrets.token_urlsafe(16)
        accounts.register(
            username=username,
            password=password,
            display_name="gSuss",
            address_as=os.getenv("USER_NAME", "senor").strip() or "senor",
            city="Buenos Aires",
            packs=ALL_PACKS,
            groq_key=os.getenv("GROQ_API_KEY", "").strip(),
            role="owner",
            force=True,
        )
        created = True
    elif not existing.is_owner:
        accounts.set_role(existing.id, "owner")
    accounts.demote_other_owners(username)
    # Keep member registration open on this PC; owner lock is only the reserved username.
    accounts.set_meta("allow_signups", "1")
    note = (
        "Ilaria - cuenta dueno (solo esta PC)\n"
        f"usuario: {username}\n"
        + (f"contrasena: {password}\n" if created else "contrasena: (la que ya tenias, no se cambio)\n")
        + "registro de terceros: ABIERTO (miembros)\n"
        "cambia la clave en /admin si la genero el sistema\n"
    )
    OWNER_FILE.write_text(note, encoding="utf-8")
    if created:
        return f"Dueno creado: {username}. Clave en data/OWNER_CREDENTIALS.txt"
    return f"Dueno activo: {username}."

"""Local accounts with a single Owner per install."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from jarvis.config import DATA_DIR

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,24}$")
RESERVED_USERNAMES = {"gsuss"}
ITERATIONS = 180_000
# Long-lived sessions for desktop WebView + Android LAN clients (10 years).
SESSION_MAX_AGE_SECONDS = 315_360_000
SESSION_DAYS = SESSION_MAX_AGE_SECONDS // 86400
ALLOWED_TONES = frozenset({"equilibrado", "serio", "seco", "calido", "ejecutivo", "tierno"})


@dataclass(frozen=True)
class User:
    id: int
    username: str
    display_name: str
    address_as: str
    city: str
    packs: list[str]
    groq_key: str
    openai_key: str
    gemini_key: str
    role: str
    disabled: bool
    custom_tone: str = "equilibrado"

    @property
    def is_owner(self) -> bool:
        return self.role == "owner" and not self.disabled

    def public(self) -> dict[str, object]:
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "address_as": self.address_as,
            "city": self.city,
            "packs": self.packs,
            "custom_tone": self.custom_tone,
            "has_own_key": bool(self.groq_key or self.openai_key or self.gemini_key),
            "role": self.role,
            "is_owner": self.is_owner,
            "disabled": self.disabled,
        }


class AccountStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (DATA_DIR / "accounts.sqlite")
        self._lock = Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    address_as TEXT NOT NULL DEFAULT '',
                    city TEXT NOT NULL DEFAULT '',
                    packs TEXT NOT NULL DEFAULT '[]',
                    groq_key TEXT NOT NULL DEFAULT '',
                    openai_key TEXT NOT NULL DEFAULT '',
                    gemini_key TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    expires REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            _migrate(db)
            db.commit()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def get_meta(self, key: str, default: str = "") -> str:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            db.commit()

    @property
    def allow_signups(self) -> bool:
        return self.get_meta("allow_signups", "1") == "1"

    @property
    def members_pc_hands(self) -> bool:
        return self.get_meta("members_pc_hands", "0") == "1"

    def register(
        self,
        username: str,
        password: str,
        display_name: str,
        address_as: str,
        city: str,
        packs: list[str],
        groq_key: str = "",
        role: str | None = None,
        force: bool = False,
    ) -> User:
        user_key = username.strip().lower()
        if not USERNAME_RE.match(user_key):
            raise ValueError("Usuario: 3-24 letras, numeros o _")
        if user_key in RESERVED_USERNAMES and not force:
            raise ValueError("Ese usuario esta reservado.")
        if len(password) < 8:
            raise ValueError("La contrasena tiene que tener al menos 8 caracteres.")
        owner = self.owner()
        if role is None:
            role = "owner" if owner is None else "member"
        if role == "member" and not force:
            if not self.allow_signups:
                raise ValueError("El registro esta cerrado. Solo el dueno puede habilitar cuentas nuevas.")
            if owner is not None and user_key == owner.username:
                raise ValueError("Ese usuario esta reservado.")
        if role == "owner" and owner is not None and not force:
            raise ValueError("Ya hay un dueno en esta instalacion.")
        name = display_name.strip() or user_key
        digest, salt = _hash_password(password)
        with self._lock, self._connect() as db:
            try:
                cursor = db.execute(
                    """
                    INSERT INTO users (
                        username, password_hash, salt, display_name, address_as,
                        city, packs, groq_key, openai_key, gemini_key, created_at,
                        role, disabled
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', '', ?, ?, 0)
                    """,
                    (
                        user_key,
                        digest,
                        salt,
                        name,
                        address_as.strip(),
                        city.strip(),
                        json.dumps(packs, ensure_ascii=False),
                        groq_key.strip(),
                        time.time(),
                        role,
                    ),
                )
                db.commit()
                user_id = int(cursor.lastrowid)
            except sqlite3.IntegrityError as exc:
                raise ValueError("Ese usuario ya existe.") from exc
        user = self.get_by_id(user_id)
        self.issue_recovery_code(user.username)
        return user

    def login(self, username: str, password: str) -> User:
        user_key = username.strip().lower()
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM users WHERE username = ?", (user_key,)).fetchone()
        if row is None or not _verify_password(password, row["salt"], row["password_hash"]):
            raise ValueError("Usuario o contrasena incorrectos.")
        user = _row_to_user(row)
        if user.disabled:
            raise ValueError("Esta cuenta esta deshabilitada.")
        return user

    def update_profile(
        self,
        user_id: int,
        display_name: str,
        address_as: str,
        city: str,
        packs: list[str],
        groq_key: str | None,
        custom_tone: str | None = None,
    ) -> User:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                raise ValueError("Usuario no encontrado.")
            key = row["groq_key"] if groq_key is None else groq_key.strip()
            tone = normalize_tone(
                custom_tone
                if custom_tone is not None
                else (row["custom_tone"] if "custom_tone" in row.keys() else "equilibrado")
            )
            db.execute(
                """
                UPDATE users SET display_name=?, address_as=?, city=?, packs=?, groq_key=?, custom_tone=?
                WHERE id=?
                """,
                (
                    display_name.strip() or row["display_name"],
                    address_as.strip(),
                    city.strip(),
                    json.dumps(packs, ensure_ascii=False),
                    key,
                    tone,
                    user_id,
                ),
            )
            db.commit()
        return self.get_by_id(user_id)

    def get_full_profile_by_username(self, username: str) -> dict[str, object]:
        """
        Safe customization payload for prompts/UI — never includes password hashes or raw API keys.
        Preferences live here so the brain core stays untouched.
        """
        user = self.get_by_username(username)
        if user is None:
            return {
                "id": 0,
                "username": "guest",
                "role": "guest",
                "display_name": "guest",
                "address_as": "señor",
                "city": "",
                "packs": ["diario"],
                "custom_tone": "equilibrado",
                "is_owner": False,
                "disabled": False,
                "has_own_key": False,
            }
        return user.public()

    def change_password(self, user_id: int, current: str, new: str) -> None:
        if len(new) < 8:
            raise ValueError("La contrasena nueva tiene que tener al menos 8 caracteres.")
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                raise ValueError("Usuario no encontrado.")
            if not _verify_password(current, row["salt"], row["password_hash"]):
                raise ValueError("La contrasena actual no coincide.")
            digest, salt = _hash_password(new)
            db.execute(
                "UPDATE users SET password_hash=?, salt=? WHERE id=?",
                (digest, salt, user_id),
            )
            db.commit()

    def lookup_usernames(self, display_name: str) -> list[str]:
        name = display_name.strip().lower()
        if len(name) < 2:
            raise ValueError("Escribí el nombre que usaste al crear la cuenta.")
        with self._lock, self._connect() as db:
            rows = db.execute(
                "SELECT username, display_name, disabled FROM users"
            ).fetchall()
        found: list[str] = []
        for row in rows:
            if int(row["disabled"] or 0):
                continue
            if str(row["display_name"] or "").strip().lower() == name:
                found.append(str(row["username"]))
        if not found:
            raise ValueError("No encontré una cuenta con ese nombre.")
        return found

    def issue_recovery_code(self, username: str, display_name: str = "") -> tuple[str, Path]:
        """Create/replace recovery code and write plaintext to data/recovery/<user>.txt."""
        user_key = username.strip().lower()
        user = self.get_by_username(user_key)
        if user is None or user.disabled:
            raise ValueError("Usuario no encontrado.")
        if display_name.strip():
            if user.display_name.strip().lower() != display_name.strip().lower():
                raise ValueError("El nombre no coincide con esa cuenta.")
        code = _new_recovery_code()
        digest, salt = _hash_password(code)
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE users SET recovery_hash=?, recovery_salt=? WHERE id=?",
                (digest, salt, user.id),
            )
            db.commit()
        path = _write_recovery_file(user_key, code)
        return code, path

    def ensure_recovery_code(self, username: str) -> Path | None:
        """If missing, create recovery code on disk. Returns path when newly created."""
        user_key = username.strip().lower()
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT id, recovery_hash FROM users WHERE username=?",
                (user_key,),
            ).fetchone()
        if row is None:
            raise ValueError("Usuario no encontrado.")
        if row["recovery_hash"]:
            return None
        code = _new_recovery_code()
        digest, salt = _hash_password(code)
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE users SET recovery_hash=?, recovery_salt=? WHERE id=?",
                (digest, salt, int(row["id"])),
            )
            db.commit()
        return _write_recovery_file(user_key, code)

    def reset_password_with_recovery(self, username: str, recovery_code: str, new_password: str) -> None:
        if len(new_password) < 8:
            raise ValueError("La contraseña nueva tiene que tener al menos 8 caracteres.")
        user_key = username.strip().lower()
        code = recovery_code.strip().replace(" ", "").upper()
        if len(code) < 8:
            raise ValueError("Código de recuperación inválido.")
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM users WHERE username = ?", (user_key,)).fetchone()
            if row is None:
                raise ValueError("Usuario no encontrado.")
            if int(row["disabled"] or 0):
                raise ValueError("Esta cuenta está deshabilitada.")
            rh = row["recovery_hash"] if "recovery_hash" in row.keys() else ""
            rs = row["recovery_salt"] if "recovery_salt" in row.keys() else ""
            if not rh or not rs:
                raise ValueError(
                    "Esta cuenta aún no tiene código. Pedí uno con tu nombre de perfil."
                )
            if not _verify_password(code, rs, rh):
                raise ValueError("Código de recuperación incorrecto.")
            digest, salt = _hash_password(new_password)
            db.execute(
                "UPDATE users SET password_hash=?, salt=? WHERE id=?",
                (digest, salt, int(row["id"])),
            )
            db.commit()
        # Rotate recovery code after successful reset
        self.issue_recovery_code(user_key)

    def set_disabled(self, user_id: int, disabled: bool) -> User:
        user = self.get_by_id(user_id)
        if user.is_owner:
            raise ValueError("No se puede deshabilitar al dueno.")
        with self._lock, self._connect() as db:
            db.execute("UPDATE users SET disabled=? WHERE id=?", (1 if disabled else 0, user_id))
            if disabled:
                db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            db.commit()
        return self.get_by_id(user_id)

    def delete_member(self, user_id: int) -> None:
        user = self.get_by_id(user_id)
        if user.is_owner:
            raise ValueError("No se puede borrar al dueno.")
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM users WHERE id=?", (user_id,))
            db.commit()

    def set_role(self, user_id: int, role: str) -> User:
        if role not in {"owner", "member"}:
            raise ValueError("Rol invalido.")
        with self._lock, self._connect() as db:
            db.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
            db.commit()
        return self.get_by_id(user_id)

    def demote_other_owners(self, keep_username: str) -> None:
        keep = keep_username.strip().lower()
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE users SET role='member' WHERE username != ? AND role='owner'",
                (keep,),
            )
            db.commit()

    def get_by_id(self, user_id: int) -> User:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise ValueError("Usuario no encontrado.")
        return _row_to_user(row)

    def get_by_username(self, username: str) -> User | None:
        key = username.strip().lower()
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM users WHERE username = ?", (key,)).fetchone()
        return _row_to_user(row) if row else None

    def owner(self) -> User | None:
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT * FROM users WHERE role='owner' AND disabled=0 ORDER BY id LIMIT 1"
            ).fetchone()
        return _row_to_user(row) if row else None

    def list_users(self) -> list[User]:
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT * FROM users ORDER BY id").fetchall()
        return [_row_to_user(row) for row in rows]

    def purge_expired_sessions(self) -> None:
        now = time.time()
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM sessions WHERE expires <= ?", (now,))
            db.commit()

    def create_session(self, user_id: int) -> str:
        self.purge_expired_sessions()
        token = os.urandom(32).hex()
        expires = time.time() + SESSION_MAX_AGE_SECONDS
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO sessions (token, user_id, expires) VALUES (?, ?, ?)",
                (token, user_id, expires),
            )
            db.commit()
        return token

    def user_from_session(self, token: str | None) -> User | None:
        if not token:
            return None
        now = time.time()
        with self._lock, self._connect() as db:
            row = db.execute(
                """
                SELECT users.* FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.token = ? AND sessions.expires > ?
                """,
                (token, now),
            ).fetchone()
            if row is None:
                return None
            # Sliding persistence: bump expiry on every successful auth check.
            db.execute(
                "UPDATE sessions SET expires = ? WHERE token = ?",
                (now + SESSION_MAX_AGE_SECONDS, token),
            )
            db.commit()
        user = _row_to_user(row)
        if user.disabled:
            return None
        return user

    def drop_session(self, token: str | None) -> None:
        if not token:
            return
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM sessions WHERE token = ?", (token,))
            db.commit()


def _migrate(db: sqlite3.Connection) -> None:
    cols = {str(row[1]) for row in db.execute("PRAGMA table_info(users)")}
    if "role" not in cols:
        db.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'member'")
    if "disabled" not in cols:
        db.execute("ALTER TABLE users ADD COLUMN disabled INTEGER NOT NULL DEFAULT 0")
    if "custom_tone" not in cols:
        db.execute("ALTER TABLE users ADD COLUMN custom_tone TEXT NOT NULL DEFAULT 'equilibrado'")
    if "recovery_hash" not in cols:
        db.execute("ALTER TABLE users ADD COLUMN recovery_hash TEXT NOT NULL DEFAULT ''")
    if "recovery_salt" not in cols:
        db.execute("ALTER TABLE users ADD COLUMN recovery_salt TEXT NOT NULL DEFAULT ''")
    owner = db.execute("SELECT id FROM users WHERE role='owner' LIMIT 1").fetchone()
    if owner is None:
        first = db.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
        if first is not None:
            db.execute("UPDATE users SET role='owner' WHERE id=?", (int(first["id"]),))
    if db.execute("SELECT 1 FROM meta WHERE key='allow_signups'").fetchone() is None:
        db.execute("INSERT INTO meta(key, value) VALUES('allow_signups', '1')")
    if db.execute("SELECT 1 FROM meta WHERE key='members_pc_hands'").fetchone() is None:
        db.execute("INSERT INTO meta(key, value) VALUES('members_pc_hands', '0')")


def normalize_tone(raw: str | None) -> str:
    key = (raw or "equilibrado").strip().lower()
    for accented, plain in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u")):
        key = key.replace(accented, plain)
    aliases = {
        "warm": "calido",
        "dry": "seco",
        "balanced": "equilibrado",
        "executive": "ejecutivo",
        "sarcastico": "seco",
        "tecnico": "ejecutivo",
        "jarvis": "seco",
        "dulce": "tierno",
        "nina": "tierno",
        "niña": "tierno",
        "sweet": "tierno",
    }
    key = aliases.get(key, key)
    return key if key in ALLOWED_TONES else "equilibrado"


def _hash_password(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    salt = bytes.fromhex(salt_hex) if salt_hex else os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return digest.hex(), salt.hex()


def _verify_password(password: str, salt_hex: str, expected_hex: str) -> bool:
    digest, _ = _hash_password(password, salt_hex)
    return hmac.compare_digest(digest, expected_hex)


def _new_recovery_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    raw = os.urandom(10)
    return "".join(alphabet[b % len(alphabet)] for b in raw)


def _write_recovery_file(username: str, code: str) -> Path:
    folder = DATA_DIR / "recovery"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{username}.txt"
    path.write_text(
        "Ilaria — código de recuperación (solo esta PC)\n"
        f"usuario: {username}\n"
        f"codigo: {code}\n"
        "Usalo en /welcome → Olvidé usuario o contraseña.\n"
        "Después de restablecer la clave se genera un código nuevo.\n",
        encoding="utf-8",
    )
    return path


def _row_to_user(row: sqlite3.Row) -> User:
    try:
        packs = json.loads(row["packs"] or "[]")
    except json.JSONDecodeError:
        packs = []
    if not isinstance(packs, list):
        packs = []
    role = str(row["role"] if "role" in row.keys() else "member") or "member"
    disabled = int(row["disabled"] if "disabled" in row.keys() else 0) == 1
    tone = normalize_tone(str(row["custom_tone"]) if "custom_tone" in row.keys() else "equilibrado")
    return User(
        id=int(row["id"]),
        username=str(row["username"]),
        display_name=str(row["display_name"]),
        address_as=str(row["address_as"] or ""),
        city=str(row["city"] or ""),
        packs=[str(item) for item in packs],
        groq_key=str(row["groq_key"] or ""),
        openai_key=str(row["openai_key"] or ""),
        gemini_key=str(row["gemini_key"] or ""),
        role=role,
        disabled=disabled,
        custom_tone=tone,
    )

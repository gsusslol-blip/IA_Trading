"""Per-user brains, memory and workspace."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from threading import Lock

from jarvis.accounts import AccountStore, User
from jarvis.brain import Brain
from jarvis.bus import EventBus
from jarvis.config import DATA_DIR, Settings
from jarvis.memory import Memory
from jarvis.packs import apply_packs, packs_style
from jarvis.tools import ALL_TOOL_NAMES, MEMBER_TOOLS, OWNER_ONLY_TOOLS


class AppState:
    def __init__(
        self,
        settings: Settings,
        accounts: AccountStore,
        data_dir: Path | None = None,
    ) -> None:
        self.settings = settings
        self.accounts = accounts
        self.data_dir = data_dir or DATA_DIR
        self._brains: dict[int, Brain] = {}
        self._lock = Lock()

    def user_dir(self, username: str) -> Path:
        path = self.data_dir / "users" / username
        path.mkdir(parents=True, exist_ok=True)
        (path / "workspace").mkdir(exist_ok=True)
        return path

    def settings_for(self, user: User) -> Settings:
        address = user.address_as.strip() or user.display_name
        return replace(
            self.settings,
            groq_api_key=user.groq_key or self.settings.groq_api_key,
            openai_api_key=user.openai_key or self.settings.openai_api_key,
            gemini_api_key=user.gemini_key or self.settings.gemini_api_key,
            user_name=address or self.settings.user_name,
        )

    def drop_brain(self, user_id: int) -> None:
        with self._lock:
            self._brains.pop(user_id, None)

    def brain_for(self, user: User, first_time: bool = False) -> Brain:
        with self._lock:
            existing = self._brains.get(user.id)
            if existing is not None:
                return existing
            folder = self.user_dir(user.username)
            memory_path = folder / "memory.json"
            is_new = first_time or not memory_path.exists()
            memory = Memory(memory_path)
            if is_new:
                apply_packs(memory, user.packs, user.display_name, user.city)
            if user.is_owner:
                allowed = ALL_TOOL_NAMES
            elif self.accounts.members_pc_hands:
                allowed = ALL_TOOL_NAMES - OWNER_ONLY_TOOLS
            else:
                allowed = MEMBER_TOOLS
            brain = Brain(
                settings=self.settings_for(user),
                memory=memory,
                bus=EventBus(),
                workspace=folder / "workspace",
                profile_style=packs_style(user.packs),
                enabled_packs=list(user.packs),
                custom_tone=user.custom_tone,
                city=user.city,
                allowed_tools=allowed,
                is_owner=user.is_owner,
            )
            self._brains[user.id] = brain
            return brain

    def iter_brains(self) -> list[Brain]:
        with self._lock:
            return list(self._brains.values())

    def all_user_brains(self) -> list[Brain]:
        brains: list[Brain] = []
        for user in self.accounts.list_users():
            brains.append(self.brain_for(user))
        return brains

"""Alias for the friendly Health Importer (see jarvis.health_inbox).

Design name `health_importer`; runtime watches workspace/inbox/ via
health_inbox.start_health_inbox_watcher.
"""

from jarvis.health_inbox import (  # noqa: F401
    ensure_inbox_readme,
    escanear_inbox_usuario,
    escanear_todas_las_inboxes,
    inbox_dir,
    procesar_archivo_inbox,
    start_health_inbox_watcher,
)

vigilar_inbox_usuario = escanear_inbox_usuario

__all__ = [
    "ensure_inbox_readme",
    "escanear_inbox_usuario",
    "escanear_todas_las_inboxes",
    "inbox_dir",
    "procesar_archivo_inbox",
    "start_health_inbox_watcher",
    "vigilar_inbox_usuario",
]

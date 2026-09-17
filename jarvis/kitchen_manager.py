"""Local kitchen recipes — fast index + optional LLM save into user workspace."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from jarvis.config import DATA_DIR
from jarvis.security import safe_under

# Ultra-low latency static DB (Argentine / everyday plates). Aliases share the same payload.
RECETAS_LOCALES: dict[str, dict[str, Any]] = {
    "milanesa": {
        "nombre": "Milanesas clásicas",
        "ingredientes": [
            "Carne (nalga, bola de lomo o peceto)",
            "Huevos",
            "Ajo y perejil fresco",
            "Pan rallado",
            "Sal y pimienta",
        ],
        "pasos": [
            "Marinar la carne en los huevos batidos con ajo, perejil, sal y pimienta al menos 30 min.",
            "Pasar cada filete por pan rallado presionando bien con la palma.",
            "Cocinar al horno fuerte con un hilo de aceite o freír en aceite caliente hasta dorar.",
        ],
    },
    "tortilla": {
        "nombre": "Tortilla de papas",
        "ingredientes": [
            "Papas (4 medianas)",
            "Huevos (5 unidades)",
            "Cebolla (1 grande)",
            "Aceite para freír",
            "Sal",
        ],
        "pasos": [
            "Cortar las papas en rodajas finas y la cebolla en juliana.",
            "Pochár en aceite a fuego medio hasta que las papas estén tiernas (sin dorar de más).",
            "Escurrir, mezclar con los huevos batidos y salar.",
            "Cuajar en sartén caliente con un hilo de aceite 3–4 minutos por lado.",
        ],
    },
    "fideos_caruso": {
        "nombre": "Fideos con salsa Caruso",
        "ingredientes": [
            "Pasta (fideos cortos o largos)",
            "Crema de leche (200 cc)",
            "Jamón cocido (100 g)",
            "Champiñones (100 g)",
            "Extracto de carne o caldo concentrado (1 cdita)",
            "Queso rallado",
        ],
        "pasos": [
            "Hervir la pasta al dente en agua con sal.",
            "Dorar champiñones fileteados y jamón en tiras.",
            "Sumar crema y disolver el extracto de carne.",
            "Espesar a fuego bajo, volcar sobre la pasta y espolvorear queso.",
        ],
    },
    "guiso_lentejas": {
        "nombre": "Guiso de lentejas",
        "ingredientes": [
            "Lentejas (400 g)",
            "Chorizo colorado (1 unidad)",
            "Panceta (100 g)",
            "Cebolla, morrón y zanahoria",
            "Puré de tomate (400 g)",
            "Caldo de verdura",
            "Pimentón, comino y sal",
        ],
        "pasos": [
            "Dorar panceta y chorizo en rodajas en olla grande.",
            "Sumar cebolla, morrón y zanahoria hasta que estén tiernos.",
            "Agregar lentejas, puré de tomate y cubrir con caldo caliente.",
            "Condimentar y cocinar a fuego lento ~40 min, revolviendo de vez en cuando.",
        ],
    },
    "fideos con tuco": {
        "nombre": "Fideos con tuco",
        "ingredientes": ["Fideos", "Tomate", "Cebolla", "Ajo", "Aceite", "Sal", "Orégano"],
        "pasos": [
            "Rehogar cebolla y ajo, sumar tomate y cocinar 15–20 min.",
            "Hervir los fideos al dente.",
            "Servir con el tuco y orégano.",
        ],
    },
    "omelette": {
        "nombre": "Omelette simple",
        "ingredientes": ["Huevos", "Sal", "Manteca o aceite", "Queso (opcional)"],
        "pasos": [
            "Batir los huevos con sal.",
            "Cocinar en sartén antiadherente a fuego medio.",
            "Opcional: agregar queso y doblar.",
        ],
    },
}

# Alias keys → canonical dish id
_ALIASES: dict[str, str] = {
    "milanesas": "milanesa",
    "milanesa napolitana": "milanesa",
    "tortilla de papas": "tortilla",
    "tortilla de papa": "tortilla",
    "caruso": "fideos_caruso",
    "fideos caruso": "fideos_caruso",
    "salsa caruso": "fideos_caruso",
    "lentejas": "guiso_lentejas",
    "guiso de lentejas": "guiso_lentejas",
    "fideos tuco": "fideos con tuco",
    "tuco": "fideos con tuco",
    "omelet": "omelette",
}


def _canonical(comida: str) -> str:
    clean = _normalize_dish(comida)
    underscored = clean.replace(" ", "_")
    if underscored in RECETAS_LOCALES:
        return underscored
    if clean in RECETAS_LOCALES:
        return clean
    if underscored in _ALIASES:
        return _ALIASES[underscored]
    if clean in _ALIASES:
        return _ALIASES[clean]
    for key in RECETAS_LOCALES:
        if key in clean or clean in key or key.replace("_", " ") in clean:
            return key
    for alias, target in _ALIASES.items():
        if alias in clean or clean in alias:
            return target
    return clean


def _normalize_dish(comida: str) -> str:
    clean = " ".join((comida or "").lower().strip().split())
    clean = re.sub(r"^(receta\s+(de\s+)?|cómo\s+hacer\s+|como\s+hacer\s+)", "", clean)
    return clean.strip(" .?¿!")


def format_recipe(receta: dict[str, Any]) -> str:
    lines = [str(receta.get("nombre") or "Receta"), "", "Ingredientes:"]
    for item in receta.get("ingredientes") or []:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("Pasos:")
    for i, step in enumerate(receta.get("pasos") or [], start=1):
        lines.append(f"{i}. {step}")
    return "\n".join(lines)


def user_workspace(usuario: str) -> Path:
    user = (usuario or "guest").strip().lower() or "guest"
    path = DATA_DIR / "users" / user / "workspace"
    path.mkdir(parents=True, exist_ok=True)
    return path


def listar_recetas_locales(usuario_activo: str = "gsuss") -> str:
    """Catalog: static DB + workspace receta_*.txt (JSON string)."""
    return listar_recetas_disponibles(user_workspace(usuario_activo))


def buscar_receta_core(comida_id: str, usuario_activo: str = "gsuss") -> str:
    """Strict local lookup only (no LLM save). JSON string."""
    return buscar_o_generar_receta(
        comida_id,
        user_workspace(usuario_activo),
        llm_fallback_content=None,
        save=False,
    )


def buscar_o_generar_receta(
    comida: str,
    workspace: Path,
    *,
    llm_fallback_content: str | None = None,
    save: bool = True,
) -> str:
    """Look up local index or persist an LLM-authored recipe into the workspace."""
    comida_clean = _normalize_dish(comida)
    hit_key = _canonical(comida_clean)
    root = Path(workspace)
    root.mkdir(parents=True, exist_ok=True)

    if hit_key in RECETAS_LOCALES:
        receta = RECETAS_LOCALES[hit_key]
        payload = {
            "status": "success",
            "source": "local_db",
            "found_in": "local_db",
            "dish": comida_clean,
            "receta": receta,
            "datos": receta,
            "speakable": format_recipe(receta),
        }
        return json.dumps(payload, ensure_ascii=False)

    # Workspace TXT (receta_<slug>.txt)
    slug = re.sub(r"[^a-z0-9áéíóúüñ]+", "_", hit_key.replace(" ", "_"), flags=re.I).strip("_")
    if slug:
        candidate = root / f"receta_{slug}.txt"
        if candidate.is_file():
            try:
                contenido = candidate.read_text(encoding="utf-8")
            except OSError:
                contenido = ""
            payload = {
                "status": "success",
                "source": "workspace_file",
                "found_in": "workspace_file",
                "dish": comida_clean,
                "datos": {
                    "nombre": slug.replace("_", " ").capitalize(),
                    "texto_completo": contenido,
                },
                "speakable": contenido.strip()[:900] or slug,
            }
            return json.dumps(payload, ensure_ascii=False)

    if llm_fallback_content and llm_fallback_content.strip():
        slug = re.sub(r"[^a-z0-9áéíóúüñ]+", "_", comida_clean, flags=re.I).strip("_") or "custom"
        filename = f"receta_{slug[:48]}.txt"
        try:
            path = safe_under(root, filename) if save else root / filename
        except ValueError as exc:
            return json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False)
        if save:
            path.write_text(llm_fallback_content.strip() + "\n", encoding="utf-8")
        return json.dumps(
            {
                "status": "success",
                "source": "llm_generated",
                "file_saved": filename if save else None,
                "preview": llm_fallback_content.strip()[:160],
                "speakable": llm_fallback_content.strip()[:900],
            },
            ensure_ascii=False,
        )

    known = sorted({str(v["nombre"]) for v in RECETAS_LOCALES.values()})
    return json.dumps(
        {
            "status": "not_found",
            "trigger_llm_fallback": True,
            "dish": comida_clean,
            "comida": comida_clean,
            "message": (
                "La receta no existe localmente. Generá ingredientes + pasos en texto breve "
                "y volvé a llamar kitchen_recipe con recipe_text para guardarla."
            ),
            "known": known,
        },
        ensure_ascii=False,
    )


def listar_recetas_disponibles(workspace: Path) -> str:
    """List static index + workspace receta_*.txt files (sandboxed)."""
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for clave, datos in RECETAS_LOCALES.items():
        nombre = str(datos.get("nombre") or clave)
        if nombre.lower() in seen:
            continue
        seen.add(nombre.lower())
        found.append(
            {
                "id": clave,
                "nombre": nombre,
                "tipo": "Base Local",
                "origen": "local_db",
                "identificador": clave,
            }
        )

    root = Path(workspace)
    if root.is_dir():
        for path in sorted(root.glob("receta_*.txt")):
            if not path.is_file():
                continue
            slug = path.stem.removeprefix("receta_").replace("_", " ").strip()
            nombre_legible = slug[:1].upper() + slug[1:] if slug else path.name
            found.append(
                {
                    "id": path.stem,
                    "nombre": nombre_legible,
                    "tipo": "Guardada en Workspace",
                    "origen": "workspace_file",
                    "identificador": path.name,
                }
            )

    speakable = "Recetas disponibles: " + (
        "; ".join(item["nombre"] for item in found[:12]) if found else "todavía ninguna guardada."
    )
    return json.dumps(
        {
            "status": "success",
            "total": len(found),
            "count": len(found),
            "recetas": found,
            "speakable": speakable,
        },
        ensure_ascii=False,
        indent=2,
    )

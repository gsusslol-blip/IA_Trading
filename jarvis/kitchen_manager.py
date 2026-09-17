"""Local kitchen recipes — fast index + optional LLM save into user workspace."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from jarvis.security import safe_under

RECETAS_LOCALES: dict[str, dict[str, Any]] = {
    "milanesa": {
        "nombre": "Milanesas clásicas",
        "ingredientes": [
            "Carne (nalga/bola de lomo)",
            "Huevo",
            "Ajo y perejil",
            "Pan rallado",
            "Sal",
        ],
        "pasos": [
            "Pasar la carne por huevo batido con ajo y perejil.",
            "Empanar con pan rallado presionando bien.",
            "Freír en aceite caliente o cocinar al horno.",
        ],
    },
    "milanesas": {
        "nombre": "Milanesas clásicas",
        "ingredientes": [
            "Carne (nalga/bola de lomo)",
            "Huevo",
            "Ajo y perejil",
            "Pan rallado",
            "Sal",
        ],
        "pasos": [
            "Pasar la carne por huevo batido con ajo y perejil.",
            "Empanar con pan rallado presionando bien.",
            "Freír en aceite caliente o cocinar al horno.",
        ],
    },
    "tortilla": {
        "nombre": "Tortilla de papas",
        "ingredientes": ["Papas", "Huevos", "Cebolla (opcional)", "Aceite", "Sal"],
        "pasos": [
            "Cortar las papas en rodajas finas y freírlas hasta que estén tiernas.",
            "Mezclar con los huevos batidos.",
            "Cocinar en sartén caliente dando la vuelta a mitad de cocción.",
        ],
    },
    "tortilla de papas": {
        "nombre": "Tortilla de papas",
        "ingredientes": ["Papas", "Huevos", "Cebolla (opcional)", "Aceite", "Sal"],
        "pasos": [
            "Cortar las papas en rodajas finas y freírlas hasta que estén tiernas.",
            "Mezclar con los huevos batidos.",
            "Cocinar en sartén caliente dando la vuelta a mitad de cocción.",
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


def buscar_o_generar_receta(
    comida: str,
    workspace: Path,
    *,
    llm_fallback_content: str | None = None,
    save: bool = True,
) -> str:
    """Look up local index or persist an LLM-authored recipe into the workspace."""
    comida_clean = _normalize_dish(comida)
    root = Path(workspace)
    root.mkdir(parents=True, exist_ok=True)

    # Fuzzy: substring match against keys
    hit_key = None
    if comida_clean in RECETAS_LOCALES:
        hit_key = comida_clean
    else:
        for key in RECETAS_LOCALES:
            if key in comida_clean or comida_clean in key:
                hit_key = key
                break

    if hit_key:
        receta = RECETAS_LOCALES[hit_key]
        payload = {
            "status": "success",
            "source": "local_db",
            "dish": comida_clean,
            "receta": receta,
            "speakable": format_recipe(receta),
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

    return json.dumps(
        {
            "status": "not_found",
            "dish": comida_clean,
            "message": (
                "No está en el índice local. Generá la receta en texto breve "
                "(ingredientes + pasos) y volvé a llamar kitchen_recipe "
                "con recipe_text, o pedí web_search si querés fuentes."
            ),
            "known": sorted(set(RECETAS_LOCALES.keys())),
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
                "nombre": nombre,
                "tipo": "Base Local",
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
                    "nombre": nombre_legible,
                    "tipo": "Guardada en Workspace",
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
            "recetas": found,
            "speakable": speakable,
        },
        ensure_ascii=False,
        indent=2,
    )

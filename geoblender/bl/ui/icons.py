# SPDX-License-Identifier: GPL-3.0-or-later
"""Iconos propios de Geoblender (spec 003; RF-003-22; RNF-003-09; II §1.4, §1.6 y §1.8).

Los 58 iconos propios de ``core/catalog/data/icons.toml`` (II §1.4) son PNG generados de sus
fuentes SVG (``tools/build_icons.py``) en ``resources/icons/<nombre>_32.png`` y ``_64.png``.
:func:`register` los carga en una colección de ``bpy.utils.previews``: los de 32 px si la
escala efectiva (``ui_scale`` × ``pixel_size``) es menor que 1,5 y los de 64 si no (II §1.8).
:func:`unregister` la elimina; «Reparar la interfaz» los vuelve a cargar (:func:`reload`), por
ejemplo tras cambiar la escala.

- :func:`icon_id`: el ``icon_id`` de un icono propio, o 0 si no se puede mostrar (sin
  interfaz gráfica siempre es 0: ``docs/trampas.md``).
- :func:`icon_kwargs` (RF-003-22): los argumentos de icono de un dibujo, ``{"icon_value":
  n}`` o, si el propio no se puede mostrar, su reserva nativa (``{"icon": "FILE_FOLDER"}``;
  ``NONE`` si no tiene). Nunca deja un control sin el icono que le corresponde.
- :func:`fallback_text`: la reserva en texto («GB» del logotipo, «[MED]»…) de los que no
  tienen un icono nativo.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import bpy
import bpy.utils.previews

from .. import compat
from .commands import catalog

ICONS_DIR = Path(__file__).resolve().parents[2] / "resources" / "icons"
SIZES: tuple[int, ...] = (32, 64)
LARGE_FROM_SCALE = 1.5  # escala efectiva a partir de la que se usan los de 64 px (II §1.8)


class _State:
    def __init__(self) -> None:
        self.collection: Any = None
        self.size = 0  # los PNG cargados (32 o 64)


_STATE = _State()


def effective_scale() -> float:
    """La escala efectiva de la interfaz: ``ui_scale`` × ``pixel_size`` (1,0 sin
    interfaz)."""
    try:
        pixel_size = float(bpy.context.preferences.system.pixel_size) or 1.0
    except (AttributeError, TypeError, ValueError):
        pixel_size = 1.0
    return compat.ui_scale() * pixel_size


def png_size(scale: float) -> int:
    """32 si la escala efectiva es menor que 1,5; si no, 64 (II §1.8)."""
    return SIZES[0] if scale < LARGE_FROM_SCALE else SIZES[1]


def png_path(name: str, size: int) -> Path:
    """El PNG de un icono propio de ``size`` px."""
    return ICONS_DIR / f"{name}_{size}.png"


def register() -> None:
    """Carga los iconos propios del catálogo (los que tienen su PNG)."""
    if _STATE.collection is not None:
        return
    collection = bpy.utils.previews.new()
    size = png_size(effective_scale())
    for name in catalog().icons:
        path = png_path(name, size)
        if path.is_file():
            collection.load(name, str(path), "IMAGE")
    _STATE.collection = collection
    _STATE.size = size


def unregister() -> None:
    """Elimina la colección de iconos."""
    collection, _STATE.collection = _STATE.collection, None
    _STATE.size = 0
    if collection is not None:
        bpy.utils.previews.remove(collection)


def reload() -> None:
    """Vuelve a cargar los iconos (con el tamaño de la escala de ahora)."""
    unregister()
    register()


def loaded_size() -> int:
    """El tamaño de los PNG cargados (0 sin cargar)."""
    return _STATE.size


def loaded_count() -> int:
    """Cuántos iconos propios hay cargados (0 sin cargar)."""
    collection = _STATE.collection
    return len(collection) if collection is not None else 0


def preview(name: str) -> Any:
    """El ``ImagePreview`` de un icono propio cargado, o ``None``."""
    collection = _STATE.collection
    if collection is None or name not in collection:
        return None
    return collection[name]


def icon_id(name: str | None) -> int:
    """El ``icon_id`` de un icono propio, o 0 si no se puede mostrar."""
    if not name:
        return 0
    found = preview(name)
    try:
        return int(found.icon_id) if found is not None else 0
    except (AttributeError, ReferenceError):
        return 0


def icon_kwargs(name: str | None, fallback: str = "NONE") -> dict[str, Any]:
    """``{"icon_value": n}`` del icono propio ``name`` o, si no se puede mostrar,
    ``{"icon": fallback}`` (su reserva nativa)."""
    value = icon_id(name)
    if value:
        return {"icon_value": value}
    return {"icon": fallback}


def fallback_text(name: str) -> str:
    """La reserva en texto de un icono propio ("" si su reserva es un icono nativo)."""
    spec = catalog().icons.get(name)
    return spec.fallback_text if spec is not None else ""

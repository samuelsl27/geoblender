# SPDX-License-Identifier: GPL-3.0-or-later
"""Único sitio con las diferencias entre versiones de Blender (principio 8).

Todo lo que cambia entre versiones de la API de Python de Blender (p. ej. las entradas
del modificador de Geometry Nodes en 5.2) se envuelve aquí, con su prueba en
``tests/blender/``, y el resto de ``bl`` lo usa a través de este módulo.

- :func:`topbar_patchable` (spec 003; RF-003-05): si la barra superior tiene la forma
  que sustituye la interfaz de Geoblender (``tests/blender/test_topbar_draw.py``).
- :func:`topbar_width_constants` (spec 003; RF-003-10; BS §2.3; plan 003 DT13): las
  constantes del modelo de anchura de la barra superior medidas en la versión de Blender
  en ejecución, y :func:`quick_access_width_constants`, las de la fila 2 de la Vista 3D
  (AR §3.2 y §3.3), con los ajustes nativos de la herramienta por modo
  (:func:`native_tool_settings_px`). Las mide en la GUI ``tools/inblender/
  measure_topbar.py`` (T19); una versión sin medir usa las de la última medida
  (``tests/blender/test_topbar_width.py``).
- :func:`ui_scale`: la escala de la interfaz (``preferences.system.ui_scale``, que ya
  incluye la del sistema operativo); sin interfaz vale 0 (``docs/trampas.md`` §3) y se
  toma 1,0.
- :data:`VIEW_SENSOR_MM` y :data:`VIEW_ZOOM` (spec 003; RF-003-13): la proyección de una
  Vista 3D que no mira por una cámara (``BKE_camera_params_from_view3d``: sensor de 36 mm
  y factor 2, con el campo en el lado mayor de la región). Comprobado en 5.2.1 con
  ``view3d.view_selected``: un cubo de 2 m en una región de 1574 × 954 px queda a 3,208 m
  (1,4 / (36 / 50) × 1574 / 954).
"""

from __future__ import annotations

import inspect

import bpy

from ..core.catalog.width import QuickAccessWidthConstants, TopbarWidthConstants


def blender_version() -> tuple[int, int, int]:
    """Versión de Blender en ejecución, p. ej. ``(5, 2, 1)`` (``bpy.app.version``)."""
    major, minor, patch = bpy.app.version
    return int(major), int(minor), int(patch)


# Barra superior (spec 003; RF-003-05; ADR-0012; CW §5) ---------------------------------

TOPBAR_HEADER = "TOPBAR_HT_upper_bar"
TOPBAR_MENUS = "TOPBAR_MT_editor_menus"


def topbar_patchable(header: type | None = None) -> bool:
    """Verdadero si la barra superior tiene la forma que Geoblender sustituye
    (ADR-0012, técnica B): un ``draw_left`` que se llama como ``draw_left(self,
    context)`` y un ``draw`` cuyo código lo llama (Blender 5.2). Si falta, tiene otra
    firma o no se puede comprobar, la interfaz usa el respaldo de compatibilidad
    (técnica A: añadir el conmutador y «Geoblender ▾» tras la Ayuda de Blender)."""
    cls = getattr(bpy.types, TOPBAR_HEADER, None) if header is None else header
    function = getattr(cls, "draw_left", None)
    if cls is None or not callable(function):
        return False
    try:
        inspect.signature(function).bind(None, None)
        source = inspect.getsource(cls.draw)
    except (TypeError, ValueError, OSError):
        return False
    return "draw_left" in source


# Anchuras de la interfaz (spec 003; RF-003-10, RF-003-11; BS §2.2–§2.3; AR §3.2–§3.3) ---

VIEW_SENSOR_MM = 36.0  # sensor de la Vista 3D (DEFAULT_SENSOR_WIDTH)
VIEW_ZOOM = 2.0  # factor de la Vista 3D (CAMERA_PARAM_ZOOM_INIT_PERSP)
UI_FONT_POINTS = 11  # fuente de la interfaz (los títulos de los menús), en puntos
UI_UNIT_PX = 20  # una unidad de interfaz (ui_units_x) a escala 1,0, en px

# Por versión (mayor, menor) de Blender: medidas en la GUI el 05/10/2026 en 5.2.1 (BS §2.2 y
# AR §3.2); tools/inblender/measure_topbar.py las vuelve a medir (T19).
_TOPBAR_WIDTHS: dict[tuple[int, int], TopbarWidthConstants] = {
    (5, 2): TopbarWidthConstants(blender_version="5.2.1", measured="2026-10-05"),
}
_QUICK_ACCESS_WIDTHS: dict[tuple[int, int], QuickAccessWidthConstants] = {
    (5, 2): QuickAccessWidthConstants(blender_version="5.2.1", measured="2026-10-05"),
}
# Ajustes nativos de la herramienta activa en la fila 2, por modo de Blender, en px a
# escala 1,0 (con «Opciones»). Modo Objeto, medido (AR §3.2: 93 + 64); los demás son
# estimaciones de la herramienta de selección por defecto que la T19 mide en la GUI.
_NATIVE_TOOL_SETTINGS_PX: dict[tuple[int, int], dict[str, float]] = {
    (5, 2): {"OBJECT": 160.0, "EDIT_MESH": 300.0, "EDIT_CURVE": 220.0},
}
NATIVE_TOOL_SETTINGS_OTHER_PX = 300.0  # cualquier otro modo (escultura, pintura…)


def _by_version[T](table: dict[tuple[int, int], T]) -> T:
    major, minor, _patch = blender_version()
    found = table.get((major, minor))
    return table[max(table)] if found is None else found  # sin medir: la última medida


def topbar_width_constants() -> TopbarWidthConstants:
    """Las constantes del modelo de anchura de la barra superior de esta versión."""
    return _by_version(_TOPBAR_WIDTHS)


def quick_access_width_constants() -> QuickAccessWidthConstants:
    """Las anchuras de los controles de la fila 2 de la Vista 3D de esta versión."""
    return _by_version(_QUICK_ACCESS_WIDTHS)


def native_tool_settings_px(mode: str) -> float:
    """Lo que ocupan en la fila 2 los ajustes nativos de la herramienta activa en el modo
    de Blender ``mode`` (``context.mode``: ``OBJECT``, ``EDIT_MESH``…), a escala 1,0."""
    return float(_by_version(_NATIVE_TOOL_SETTINGS_PX).get(mode, NATIVE_TOOL_SETTINGS_OTHER_PX))


def ui_scale() -> float:
    """La escala efectiva de la interfaz (``preferences.system.ui_scale``); 1,0 sin
    interfaz, donde Blender da 0."""
    try:
        scale = float(bpy.context.preferences.system.ui_scale)
    except (AttributeError, TypeError, ValueError):
        return 1.0
    return scale if scale > 0 else 1.0

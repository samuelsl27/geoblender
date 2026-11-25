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
- :func:`topbar_right_block_px` (convergencia, T42; hallazgo D2): en 5.2 la barra superior
  son dos regiones de cabecera, la de ``draw_left`` (``TOP``) y la del bloque derecho
  (``RIGHT``, de tamaño dinámico), y la anchura de la primera ya no incluye el bloque
  derecho; restarlo otra vez daba D con escala efectiva 1,25 donde cabe C.
- :func:`statusbar_widths` (spec 003, RF-003-28; spec 008, T69): lo que ocupa en la barra de
  estado cada elemento (etiqueta, botón, desplegable, separador) además de su texto, medido
  en la GUI de esta versión; con ello se calcula qué campos caben y cuáles se pliegan.
- :func:`ui_scale`: la escala efectiva de la interfaz (``preferences.system.ui_scale``:
  la «Escala de resolución» por la del sistema operativo, p. ej. 1,0 × 125 % = 1,25); sin
  interfaz vale 0 (``docs/trampas.md`` §3) y se toma 1,0.
- :func:`set_mesh_positions`, :func:`mesh_positions`, :func:`set_corner_verts` y
  :func:`mesh_corner_verts` (spec 006, T50; RNF-006-06, RNF-006-09): las coordenadas de los
  vértices y el vértice de cada esquina de una malla grande de una vez, con sus atributos
  («position», «.corner_vert») y ``np.intc``; si la versión no los tiene así, con
  ``vertices``/``loops`` como siempre (``tests/blender/gis/test_gis_views.py``).
- :func:`modifier_input` y :func:`set_modifier_input` (spec 005, T29; RF-005-23): el valor de
  una entrada de un modificador de Geometry Nodes por el identificador de su socket
  («Socket_1»). En 5.2 es ``mod.properties.inputs.Socket_1.value`` (``mod["Socket_1"]`` da
  ``TypeError``: el modificador ya no admite propiedades de ID); antes, ``mod["Socket_1"]``
  (``tests/blender/test_dh_view.py``, el radio de los tubos de los sondeos).
- :data:`VIEW_SENSOR_MM` y :data:`VIEW_ZOOM` (spec 003; RF-003-13): la proyección de una
  Vista 3D que no mira por una cámara (``BKE_camera_params_from_view3d``: sensor de 36 mm
  y factor 2, con el campo en el lado mayor de la región). Comprobado en 5.2.1 con
  ``view3d.view_selected``: un cubo de 2 m en una región de 1574 × 954 px queda a 3,208 m
  (1,4 / (36 / 50) × 1574 / 954).
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass

import bpy
import numpy as np

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

# Por versión (mayor, menor) de Blender: medidas en la GUI de 5.2.1 con
# tools/inblender/measure_topbar.py el 07/10/2026 (convergencia, T42: 1920 px, escalas
# efectivas 1,0 y 1,25; BS §2.2 y §2.3); antes, las del 05/10/2026.
_TOPBAR_WIDTHS: dict[tuple[int, int], TopbarWidthConstants] = {
    (5, 2): TopbarWidthConstants(
        menu_pad=23.0, menu_gap=8.0, title_icon=21.0, icon_menu=28.0, fixed_b=363.0,
        version_compact=91.0, right_block=337.0, margin=24.0, blender_version="5.2.1",
        measured="2026-10-07"),
}
_QUICK_ACCESS_WIDTHS: dict[tuple[int, int], QuickAccessWidthConstants] = {
    (5, 2): QuickAccessWidthConstants(native_object_mode=170.0, blender_version="5.2.1",
                                      measured="2026-10-07"),
}
# Ajustes nativos de la herramienta activa en la fila 2, por modo de Blender, en px a
# escala 1,0 (con «Opciones» si la hay), medidos con la herramienta de selección por
# defecto el 07/10/2026 en 5.2.1 (T42; antes, 160 medidos y 300 y 220 estimados).
_NATIVE_TOOL_SETTINGS_PX: dict[tuple[int, int], dict[str, float]] = {
    (5, 2): {"OBJECT": 170.0, "EDIT_MESH": 279.0, "EDIT_CURVE": 105.0},
}
NATIVE_TOOL_SETTINGS_OTHER_PX = 300.0  # cualquier otro modo (escultura, pintura…)
# Fila 1 de la Vista 3D (spec 003; RF-003-17; PC §1), en px a escala 1,0: lo nativo (menús,
# orientación, pivote, encaje, proporcional, visibilidad, superposiciones y sombreado) y lo
# de Geoblender (Herramientas, el menú del tipo, 2 iconos y la chincheta), medidos en 5.2.1
# (PC §1); lo que ahorran la chincheta y los 2 iconos (3 botones de icono) es una
# estimación que se mide en la GUI (M14).
_VIEW3D_ROW1_PX: dict[tuple[int, int], dict[str, float]] = {
    (5, 2): {"native": 795.0, "full": 262.0, "pin_and_icons": 78.0},
}


def _by_version[T](table: dict[tuple[int, int], T]) -> T:
    major, minor, _patch = blender_version()
    found = table.get((major, minor))
    return table[max(table)] if found is None else found  # sin medir: la última medida


def topbar_right_block_px(context: object) -> float | None:
    """Lo que ocupa el bloque derecho de la barra superior dentro de ``context.region``,
    en px reales: 0 si Blender lo dibuja en otra región, la cabecera alineada a la derecha
    de la misma área (5.2.1: ``context.region`` es entonces solo la parte izquierda; a 1920
    px medidos el 07/10/2026, 1583 + 337 px con escala efectiva 1,0 y 1500 + 420 con 1,25);
    ``None`` si no la hay (la región es la barra entera y el modelo resta la constante
    ``right_block``)."""
    region = getattr(context, "region", None)
    if getattr(region, "alignment", "") == "RIGHT":
        return None
    for other in getattr(getattr(context, "area", None), "regions", None) or ():
        if getattr(other, "type", "") == "HEADER" and getattr(other, "alignment", "") == "RIGHT":
            return 0.0
    return None


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


# Filtro de paneles nativos (spec 019, T15; ADR-0032 punto 2) ---------------------------------


@dataclass(frozen=True)
class NativeFilterShape:
    """La forma que debe tener el árbol de paneles del editor de Propiedades para filtrarlo
    (R-8): el contexto de la pestaña visible y el mínimo de clases esperado."""

    context: str
    min_classes: int
    blender_version: str
    measured: str


# Medido el 25/11/2026 (T01) en 5.2.1: el contexto Objeto tiene 26 clases de Python (con las
# de Cycles); sin Cycles habría 19. Si una versión nueva cambia el árbol, el filtro cae al
# modo degradado y lo dice una vez.
_NATIVE_FILTER: dict[tuple[int, int], NativeFilterShape] = {
    (5, 2): NativeFilterShape(context="object", min_classes=19, blender_version="5.2.1",
                              measured="2026-11-25"),
}


def native_filter_shape() -> NativeFilterShape:
    """El árbol de paneles que filtra :mod:`bl.ui.native_filter` en esta versión."""
    return _by_version(_NATIVE_FILTER)


# Barra de estado (spec 003; RF-003-28; AR §6): lo que dejan ocupado a escala 1,0 las ayudas
# de teclado de la herramienta (izquierda) y la información de Blender (derecha) antes de los
# campos de Geoblender. Estimación que se mide en la GUI (M15).
STATUSBAR_RESERVED_PX = 480.0


@dataclass(frozen=True)
class StatusbarWidths:
    """Lo que ocupa en la barra de estado cada elemento, a escala 1,0, además del ancho
    ``blf`` de su texto con la fuente de la interfaz (spec 003, RF-003-28; spec 008, T69).

    ``label``: una etiqueta sin icono (su texto + 0,25 unidades); ``icon_label``: con icono
    (+ 1,75); ``button``: el botón de una orden con texto y sin icono (+ 1,5); ``icon_button``:
    el de una orden solo con su icono (1 unidad); ``popover``: un desplegable con texto
    (+ 1,25); ``separator``: el separador de línea entre dos campos con el espacio a cada lado;
    ``spacer``: un separador dentro de una fila alineada (0,3 unidades, del código de Blender,
    sin medir)."""

    label: float
    icon_label: float
    button: float
    icon_button: float
    popover: float
    separator: float
    spacer: float
    blender_version: str
    measured: str


# Medidas en las capturas de la barra de estado de 5.2.1 a 1920 px con escalas efectivas 1,0
# y 1,5 (comprobación M6 de la spec 008, 10/10/2026): las posiciones de los textos y de los
# separadores frente al ancho blf de cada texto a 11 pt.
_STATUSBAR_WIDTHS: dict[tuple[int, int], StatusbarWidths] = {
    (5, 2): StatusbarWidths(label=5.0, icon_label=35.0, button=30.0, icon_button=20.0,
                            popover=25.0, separator=22.0, spacer=6.0, blender_version="5.2.1",
                            measured="2026-10-10"),
}


def view3d_row1_widths() -> dict[str, float]:
    """Anchuras de la fila 1 de la Vista 3D de esta versión (``native``, ``full`` y
    ``pin_and_icons``), a escala 1,0."""
    return dict(_by_version(_VIEW3D_ROW1_PX))


def statusbar_widths() -> StatusbarWidths:
    """Lo que ocupa cada elemento de la barra de estado en esta versión, a escala 1,0."""
    return _by_version(_STATUSBAR_WIDTHS)


def ui_scale() -> float:
    """La escala efectiva de la interfaz (``preferences.system.ui_scale``); 1,0 sin
    interfaz, donde Blender da 0."""
    try:
        scale = float(bpy.context.preferences.system.ui_scale)
    except (AttributeError, TypeError, ValueError):
        return 1.0
    return scale if scale > 0 else 1.0


# Mallas grandes (spec 006, T50; RNF-006-06, RNF-006-09) --------------------------------
# En 5.2 las posiciones de los vértices y el vértice de cada esquina son atributos de la
# malla («position», POINT FLOAT_VECTOR; «.corner_vert», CORNER INT). Con sus datos,
# ``foreach_set``/``foreach_get`` copian de una vez si el array de numpy tiene el tipo exacto
# (en Windows, ``np.int32`` se anuncia como «l», el ``long`` de C, y Blender copia valor a
# valor: hay que darle ``np.intc``, «i»). Medido en 5.2.1 con 2,8 M vértices y 16,9 M
# esquinas: posiciones 0,002 s frente a 0,23 s con ``vertices.foreach_set("co")``; esquinas
# 0,004 s frente a 0,88 s con ``loops.foreach_set("vertex_index")`` (y 0,005 s frente a 0,75 s
# al leerlas). Si una versión no los tiene así, las propiedades de siempre.

POSITION_ATTRIBUTE = ("position", "POINT", "FLOAT_VECTOR")
CORNER_VERT_ATTRIBUTE = (".corner_vert", "CORNER", "INT")
EDGE_VERTS_ATTRIBUTE = (".edge_verts", "EDGE", "INT32_2D")
# Los vértices de cada arista (T55): con su atributo, 1 M de aristas se leen en 0,0005 s frente a
# 0,06 s con ``edges.foreach_get("vertices")`` (5.2.1).


def _mesh_attribute(mesh: bpy.types.Mesh, spec: tuple[str, str, str], count: int) -> object:
    """El atributo ``spec`` (nombre, dominio y tipo) de ``mesh`` con ``count`` valores, o
    ``None`` si esta versión no lo tiene así."""
    attributes = getattr(mesh, "attributes", None)
    found = None if attributes is None else attributes.get(spec[0])
    if found is None or (found.domain, found.data_type) != spec[1:]:
        return None
    return found if len(found.data) == count else None


def set_mesh_positions(mesh: bpy.types.Mesh, local: np.ndarray) -> None:
    """Las coordenadas locales (float32, ``(n, 3)``) de los ``n`` vértices ya añadidos de
    ``mesh``, de una vez."""
    flat = np.ascontiguousarray(local, dtype=np.float32).ravel()
    found = _mesh_attribute(mesh, POSITION_ATTRIBUTE, len(mesh.vertices))
    if found is None:
        mesh.vertices.foreach_set("co", flat)
    else:
        found.data.foreach_set("vector", flat)  # type: ignore[attr-defined]


def mesh_positions(mesh: bpy.types.Mesh) -> np.ndarray:
    """Las coordenadas de los vértices de ``mesh`` tal como las guarda Blender: float32
    ``(n, 3)``."""
    count = len(mesh.vertices)
    flat = np.empty(count * 3, dtype=np.float32)
    found = _mesh_attribute(mesh, POSITION_ATTRIBUTE, count)
    if found is None:
        mesh.vertices.foreach_get("co", flat)
    else:
        found.data.foreach_get("vector", flat)  # type: ignore[attr-defined]
    return flat.reshape(-1, 3)


def set_corner_verts(mesh: bpy.types.Mesh, corners: np.ndarray) -> None:
    """El vértice de cada una de las esquinas ya añadidas de ``mesh`` (enteros), de una
    vez."""
    flat = np.ascontiguousarray(corners, dtype=np.intc).ravel()
    found = _mesh_attribute(mesh, CORNER_VERT_ATTRIBUTE, len(mesh.loops))
    if found is None:
        mesh.loops.foreach_set("vertex_index", flat)
    else:
        found.data.foreach_set("value", flat)  # type: ignore[attr-defined]


def mesh_corner_verts(mesh: bpy.types.Mesh) -> np.ndarray:
    """El vértice de cada esquina de ``mesh``, en su orden (``np.intc``)."""
    count = len(mesh.loops)
    flat = np.empty(count, dtype=np.intc)
    found = _mesh_attribute(mesh, CORNER_VERT_ATTRIBUTE, count)
    if found is None:
        mesh.loops.foreach_get("vertex_index", flat)
    else:
        found.data.foreach_get("value", flat)  # type: ignore[attr-defined]
    return flat


def mesh_edge_verts(mesh: bpy.types.Mesh) -> np.ndarray:
    """Los dos vértices de cada arista de ``mesh``, en su orden (``np.intc``, ``(k, 2)``)."""
    count = len(mesh.edges)
    flat = np.empty(count * 2, dtype=np.intc)
    found = _mesh_attribute(mesh, EDGE_VERTS_ATTRIBUTE, count)
    if found is None:
        mesh.edges.foreach_get("vertices", flat)
    else:
        found.data.foreach_get("value", flat)  # type: ignore[attr-defined]
    return flat.reshape(-1, 2)


# Entradas del modificador de Geometry Nodes (spec 005, T29; docs/trampas.md) --------------
# En 5.2 se leen y se escriben en ``mod.properties.inputs.<identificador>.value``; el
# modificador ya no admite propiedades de ID (``mod["Socket_1"]`` da ``TypeError``). Las
# versiones anteriores las guardaban como propiedades de ID del modificador.


def _modifier_socket(modifier: bpy.types.Modifier, identifier: str) -> object | None:
    """La entrada ``identifier`` de ``modifier`` en ``properties.inputs`` (5.2), o ``None``
    si esta versión no la tiene así."""
    properties = getattr(modifier, "properties", None)
    inputs = None if properties is None else getattr(properties, "inputs", None)
    return None if inputs is None else getattr(inputs, identifier, None)


def modifier_input(modifier: bpy.types.Modifier, identifier: str) -> object:
    """El valor de la entrada ``identifier`` («Socket_1») del modificador de Geometry Nodes
    ``modifier``. ``KeyError`` si no la tiene."""
    socket = _modifier_socket(modifier, identifier)
    if socket is not None:
        return socket.value  # type: ignore[attr-defined]
    return modifier[identifier]


def set_modifier_input(modifier: bpy.types.Modifier, identifier: str, value: object) -> None:
    """Pone ``value`` en la entrada ``identifier`` («Socket_1») del modificador de Geometry
    Nodes ``modifier``. ``KeyError`` si no la tiene."""
    socket = _modifier_socket(modifier, identifier)
    if socket is not None:
        socket.value = value  # type: ignore[attr-defined]
        return
    if identifier not in modifier.keys():
        raise KeyError(f"el modificador «{modifier.name}» no tiene la entrada {identifier!r}")
    modifier[identifier] = value

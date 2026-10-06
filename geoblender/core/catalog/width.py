# SPDX-License-Identifier: GPL-3.0-or-later
"""Modelo de anchura de la barra superior (niveles A–E) y plegado de la fila 2 de la Vista
3D (spec 003; RF-003-10, RF-003-11, RNF-003-01; BS §2.2, §2.3 y §3; AR §3.2 y §3.3).

**Barra superior.** ``gb_draw_left`` mide los títulos de los menús con ``blf`` en el idioma
activo (a 11 pt y escala 1,0) y elige el primer nivel, de A a E, cuya anchura cabe junto al
bloque derecho de Blender con un margen (todo por ``ui_scale``):

- A: icono de familia y título en los 11 menús del flujo y en Herramientas;
- B: títulos de texto (el nivel por defecto a 1920 px y escala 1,0 en español);
- C: como B, pero Herramientas y Ayuda en icono y la versión solo con su punto de color;
- D: los 11 menús del flujo también en icono;
- E: un único menú «Geoblender ▾» con los 13 menús.

Un menú de texto ocupa su título más ``menu_pad`` (BS §2.3: 27 px, con el espacio entre
botones). Los elementos fijos (conmutador, Disposición ▾, ≡, el acceso rápido del proyecto y
los separadores) son ``fixed_b`` en el nivel B (289 px). Las constantes son las de BS §2.3,
medidas el 05/10/2026 en Blender 5.2.1; la T19 las vuelve a medir en la interfaz gráfica y
``bl/compat.py`` las guarda por versión de Blender. Con ellas el modelo reproduce la tabla
de BS §2.2 y §3 (B a 1920 px y 1,0 en español con unos 254 px libres; C a 1,25; D a
1366 px y a 1,5; A en inglés y a 2200 px).

**Fila 2.** :func:`fold_view_quick_access` aplica los pasos de plegado de AR §3.3 hasta que
los controles caben: (1) Banda y Objeto actual a solo icono; a «»», (2) Comando,
(3) Cálculo y control, (4) Consulta y (5) Plano de trabajo, Edición de polilíneas, Filtro
de selección y Objeto actual. Vista, Sección, Nueva polilínea y Encaje no se pliegan nunca.
En los modos de edición solo quedan los controles con ``edit_modes``. Anchos de la regla del
encargo (botón de icono 26 px, desplegable 36, texto 7 px por letra + 20, separador 8): la
fila entera da unos 920 px, como la regla de AR §3.2 (918; medidos, unos 870).

Puro: no importa ``bpy`` (las anchuras de ``blf`` llegan como números).
"""

from __future__ import annotations

import enum
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .schema import QuickAccessItem

# Menús de la barra con papel propio en el modelo; los demás títulos son del flujo.
TOOLS_MENU = "GEOBLENDER_MT_ui_tools"
HELP_MENU = "GEOBLENDER_MT_ui_help"
GEOBLENDER_MENU = "GEOBLENDER_MT_ui_geoblender"


class Level(enum.Enum):
    """Nivel de compactación de la barra superior (BS §3)."""

    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"


@dataclass(frozen=True)
class TopbarWidthConstants:
    """Constantes del modelo de la barra, en px a escala 1,0 (BS §2.3)."""

    menu_pad: float = 27.0  # un menú de texto: título blf + menu_pad
    title_icon: float = 21.0  # nivel A: lo que añade el icono de familia a un título
    icon_menu: float = 31.0  # un menú en icono (niveles C, D y E)
    fixed_b: float = 289.0  # conmutador, Disposición, ≡, acceso rápido y separadores (B)
    # Lo que ahorra la versión con solo su punto (C, D, E): de «● V10.r12 ▾» (89 px por la
    # regla de BS §2.1) a un botón de icono (26 px).
    version_compact: float = 63.0
    right_block: float = 340.0  # bloque derecho de Blender (333 medidos + margen)
    margin: float = 24.0  # lo que se deja libre como mínimo
    blender_version: str = "5.2.1"
    measured: str = "2026-10-05"


@dataclass(frozen=True)
class QuickAccessWidthConstants:
    """Anchos de los controles de la fila 2, en px a escala 1,0 (AR §3.2 y §3.3)."""

    icon: float = 26.0
    menu: float = 36.0  # desplegable de icono (menú o ventana emergente)
    icon_text: float = 40.0  # botón de icono con un número o una insignia
    toggle_menu: float = 52.0  # conmutador nativo y su desplegable (Encaje)
    text_icon: float = 20.0  # icono de un control con texto
    text_char: float = 7.0  # por letra del texto
    text_pad: float = 20.0  # flecha y relleno de un control con texto
    separator: float = 8.0
    more: float = 20.0  # el botón «»» del final
    native_object_mode: float = 160.0  # ajustes nativos de la herramienta en modo Objeto
    margin: float = 24.0
    blender_version: str = "5.2.1"
    measured: str = "2026-10-05"


@dataclass(frozen=True)
class FoldResult:
    """Cómo queda la fila 2: el paso de plegado (0–5), los controles visibles en orden,
    los que van en solo icono, los que van en «»» y la anchura total en px reales."""

    step: int
    visible: tuple[str, ...]
    compact: frozenset[str]
    folded: tuple[str, ...]
    more: bool
    width_px: float


def _split_titles(titles_px: Mapping[str, float]) -> tuple[list[float], float, float, float]:
    flow = [value for key, value in titles_px.items()
            if key not in (TOOLS_MENU, HELP_MENU, GEOBLENDER_MENU)]
    return (flow, titles_px.get(TOOLS_MENU, 0.0), titles_px.get(HELP_MENU, 0.0),
            titles_px.get(GEOBLENDER_MENU, 0.0))


def topbar_width(level: Level, *, scale: float, titles_px: Mapping[str, float],
                 k: TopbarWidthConstants) -> float:
    """Anchura de la parte izquierda de la barra en ``level``, en px reales (×
    ``scale``). ``titles_px``: ancho ``blf`` de cada título a escala 1,0, por clase del
    menú (los del flujo, Herramientas, Ayuda y, para el nivel E, «Geoblender ▾»)."""
    flow, tools, help_, geoblender = _split_titles(titles_px)
    text_flow = sum(title + k.menu_pad for title in flow)
    trailing = (tools + k.menu_pad) + (help_ + k.menu_pad)
    if level is Level.A:
        width = text_flow + trailing + (len(flow) + 1) * k.title_icon + k.fixed_b
    elif level is Level.B:
        width = text_flow + trailing + k.fixed_b
    elif level is Level.C:
        width = text_flow + 2 * k.icon_menu + k.fixed_b - k.version_compact
    elif level is Level.D:
        width = (len(flow) + 2) * k.icon_menu + k.fixed_b - k.version_compact
    else:
        width = (geoblender + k.menu_pad) + k.fixed_b - k.version_compact
    return width * scale


def topbar_free_px(level: Level, *, region_width_px: float, scale: float,
                   titles_px: Mapping[str, float], k: TopbarWidthConstants) -> float:
    """Los px que quedan libres entre la parte izquierda y el bloque derecho."""
    return (region_width_px - k.right_block * scale
            - topbar_width(level, scale=scale, titles_px=titles_px, k=k))


def choose_topbar_level(*, region_width_px: float, scale: float, titles_px: Mapping[str, float],
                        k: TopbarWidthConstants, forced: Level | None = None) -> Level:
    """El nivel fijado en las preferencias o, si no, el primero de A a E que cabe dejando
    ``margin`` libre; si no cabe ninguno, E (RF-003-10)."""
    if forced is not None:
        return forced
    for level in Level:
        free = topbar_free_px(level, region_width_px=region_width_px, scale=scale,
                              titles_px=titles_px, k=k)
        if free >= k.margin * scale:
            return level
    return Level.E


def quick_access_available_px(*, region_width_px: float, scale: float, native_px: float,
                              k: QuickAccessWidthConstants) -> float:
    """Lo que queda para el acceso rápido en la fila 2: la región menos los ajustes
    nativos de la herramienta activa (por modo, de ``bl/compat.py``) y el margen."""
    return region_width_px - (native_px + k.margin) * scale


def item_width(item: QuickAccessItem, *, compact: bool, k: QuickAccessWidthConstants) -> float:
    """Anchura de un control a escala 1,0."""
    display = item.display
    if display in ("menu_text", "popover_text"):
        if compact or not item.width_text:
            return k.menu
        return k.text_icon + k.text_char * len(item.width_text) + k.text_pad
    if display in ("menu", "popover"):
        return k.menu
    if display == "icon_text":
        return k.icon_text
    if display in ("toggle_menu", "switch"):
        return k.toggle_menu
    return k.icon


def _layout(items: Sequence[QuickAccessItem], step: int, edit_mode: bool,
            k: QuickAccessWidthConstants) -> FoldResult:
    visible: list[QuickAccessItem] = []
    folded: list[str] = []
    for item in items:
        hidden = (edit_mode and not item.edit_modes) or (
            item.fold_step is not None and item.fold_step <= step)
        (folded.append(item.key) if hidden else visible.append(item))
    compact = frozenset(item.key for item in visible
                        if item.compact_step is not None and item.compact_step <= step)
    width = sum(item_width(item, compact=item.key in compact, k=k) for item in visible)
    groups = [item.group for item in visible]
    width += k.separator * sum(1 for a, b in zip(groups, groups[1:], strict=False) if a != b)
    if folded:
        width += k.more
    return FoldResult(step, tuple(item.key for item in visible), compact, tuple(folded),
                      bool(folded), width)


def fold_view_quick_access(*, available_px: float, scale: float, edit_mode: bool,
                           items: Sequence[QuickAccessItem],
                           k: QuickAccessWidthConstants) -> FoldResult:
    """El primer paso de plegado (0–5, AR §3.3) con el que los controles caben en
    ``available_px`` (px reales); si ninguno basta, el paso 5. ``width_px`` va en px
    reales (× ``scale``)."""
    result = _layout(items, 0, edit_mode, k)
    for step in range(6):
        result = _layout(items, step, edit_mode, k)
        if result.width_px * scale <= available_px:
            break
    return FoldResult(result.step, result.visible, result.compact, result.folded, result.more,
                      result.width_px * scale)

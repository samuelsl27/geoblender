# SPDX-License-Identifier: GPL-3.0-or-later
"""Las etiquetas, las leyendas y las marcas de los sondeos en la Vista 3D (spec 005, T30;
HU-005-5; RF-005-17, RF-005-22, RF-005-23 a RF-005-25; plan 005 §5.1, §5.5 y §5.6.8;
comprobación manual M3).

Una superposición ``POST_PIXEL`` (``SpaceView3D.draw_handler_add``) dibuja, encima de la escena
y en píxeles de la región, lo que cada vista de los sondeos visible en esa Vista 3D dejó al
cargarse (``bl.scene.dh_view.Overlay``, en la memoria de la sesión con sus objetos: no se guarda
en el ``.blend`` y se rehace al cargar otra vez), según la representación de la escena
(``Scene.geoblender_dh_display``), con las superposiciones de la vista encendidas:

- **las etiquetas** (RF-005-25, con «Etiquetas»): en la boca de cada sondeo su nombre y su
  profundidad total («S-12 (160,00 m)») y, con «Profundidad en el fondo», la del fondo en su
  sitio sobre la traza (las dos vienen ya del trabajo de la vista, así que cambiarlo no recarga
  nada), en blanco con sombra;
- **las leyendas** (RF-005-23, RF-005-24, con «Leyenda»), abajo a la izquierda sobre un fondo
  oscuro translúcido: la de la litología del esquema («Litología (esquema)», cada código con su
  color del catálogo y su descripción, y «Sin dato») y la de las clases del elemento («Au
  (g/t)», cada clase y «< LD»), con sus colores sRGB;
- **las marcas de la boca** (siempre): un aspa roja con los códigos de sus errores de alcance S
  en un sondeo sin traza (RF-005-17: «El sondeo con error de desviación muestra un aspa roja con
  su código», M3), los códigos de alcance T de la validación guardada en rojo, sin aspa, en uno
  con traza cuya tabla no se pinta, y «Traza obsoleta» en naranja en uno de traza obsoleta
  (RF-005-22).

Lo que se dibuja se calcula sin ``gpu`` (:func:`screen_items`: textos, aspas y cuadros en
píxeles, con la matriz de la vista y la medida de los textos que se le dé) y después se pinta
(:func:`paint`, con ``gpu`` y ``blf``), para que se pueda probar sin GPU. Las posiciones son
locales (las de la escena, respecto al GeoOrigin): la proyección es la de la vista
(``RegionView3D.perspective_matrix``); lo que queda detrás de la cámara o lejos de la región no
se dibuja. :func:`register` y :func:`unregister` ponen y quitan el manejador (principio 8):
desactivar Geoblender quita etiquetas, leyendas y marcas. Un error al dibujar se registra una
vez y la superposición deja de dibujar hasta volver a registrarla: nunca una traza por fotograma.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import blf
import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader

from ...core.i18n import tr
from ..props.core import OBJECT_PROPERTY
from ..props.dh import SCENE_PROPERTY
from ..scene import dh_view
from ..scene.dh_view import MARK_EXCLUDED, MARK_PARTIAL, MARK_STALE, Overlay

__all__ = ["BOTTOM_OFFSET", "EXCLUDED", "LABEL_OFFSET", "MARK_PX", "PARTIAL", "STALE", "Box", "LegendRow",
           "Lines", "Text", "drawing", "legend_rows", "paint", "register", "screen_items",
           "shown_overlays", "to_screen", "unregister"]

LOGGER = logging.getLogger("geoblender.bl.draw")

EXCLUDED = MARK_EXCLUDED
"""La marca de un sondeo sin traza (alcance S): aspa y códigos."""
PARTIAL = MARK_PARTIAL
"""La de un sondeo con una tabla que no se pinta (alcance T): sus códigos."""
STALE = MARK_STALE
"""La de un sondeo de traza obsoleta."""

FONT_ID = 0
FONT_PX = 12.0
"""El tamaño de los textos, en px (por la escala de la interfaz)."""
ROW_PX = 18.0
"""El alto de una fila de la leyenda."""
SWATCH_PX = 12.0
"""El lado del cuadro de color de una entrada de la leyenda."""
GAP_PX = 6.0
"""El hueco entre el cuadro de color y su texto."""
MARGIN_PX = 16.0
"""La distancia de la leyenda a la esquina inferior izquierda de la región."""
PAD_PX = 6.0
"""El margen del fondo de la leyenda alrededor de sus filas."""
MARK_PX = 6.0
"""La mitad del lado del aspa."""
MARK_WIDTH_PX = 2.0
"""El trazo del aspa."""
LABEL_OFFSET = (8.0, 6.0)
"""Dónde va una etiqueta respecto a su boca (arriba a la derecha)."""
BOTTOM_OFFSET = (8.0, -16.0)
"""Dónde va la del fondo respecto a su sitio (abajo a la derecha: en planta, la de un sondeo
vertical no tapa la de su boca)."""
CODE_OFFSET = (MARK_PX + 4.0, -(MARK_PX + 10.0))
"""Dónde van los códigos de una marca respecto a su boca (abajo a la derecha)."""
CULL_PX = 64.0
"""Lo que puede quedar fuera de la región algo que se dibuja (más lejos, no)."""
LABEL_COLOR = (1.0, 1.0, 1.0, 1.0)
LEGEND_COLOR = (1.0, 1.0, 1.0, 1.0)
EXCLUDED_COLOR = (0.92, 0.12, 0.10, 1.0)
STALE_COLOR = (1.0, 0.62, 0.10, 1.0)
PANEL = (0.0, 0.0, 0.0, 0.45)
"""El fondo translúcido de la leyenda."""
SHADOW = (0.0, 0.0, 0.0, 0.85)
FILL_SHADER = "UNIFORM_COLOR"
LINE_SHADER = "POLYLINE_UNIFORM_COLOR"


@dataclass(frozen=True)
class Text:
    """Un texto en ``(x, y)`` px (su línea base, a la izquierda) con su color RGBA."""

    x: float
    y: float
    text: str
    color: tuple[float, float, float, float]


@dataclass(frozen=True, eq=False)
class Lines:
    """Unos segmentos (cada dos filas de ``points``, en px) con su color y su trazo."""

    points: np.ndarray
    color: tuple[float, float, float, float]
    width: float


@dataclass(frozen=True)
class Box:
    """Un rectángulo relleno de ``(x0, y0)`` a ``(x1, y1)`` px con su color RGBA."""

    x0: float
    y0: float
    x1: float
    y1: float
    color: tuple[float, float, float, float]


@dataclass(frozen=True)
class LegendRow:
    """Una fila de la leyenda: su texto y su color «#RRGGBB» (``None``: un título)."""

    text: str
    color: str | None = None


def _rgba(color: str) -> tuple[float, float, float, float]:
    """«#RRGGBB» (sRGB) en RGBA (0–1)."""
    return (int(color[1:3], 16) / 255.0, int(color[3:5], 16) / 255.0,
            int(color[5:7], 16) / 255.0, 1.0)


def to_screen(points: Sequence[Sequence[float]] | np.ndarray, matrix: Any,
              size: tuple[float, float]) -> np.ndarray:
    """Las posiciones en píxeles de la región (``size``: ancho y alto) de unas posiciones
    locales ``points`` (n, 3) con la matriz de la vista ``matrix`` (la de proyección por la de
    vista, 4 × 4); NaN las que quedan detrás de la cámara."""
    found = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    clip = np.column_stack((found, np.ones(len(found)))) @ np.asarray(matrix,
                                                                     dtype=np.float64).T
    w = clip[:, 3]
    shown = np.full((len(found), 2), np.nan)
    ahead = w > 0.0
    ndc = clip[ahead, :2] / w[ahead, None]
    shown[ahead] = (ndc + 1.0) / 2.0 * np.asarray(size, dtype=np.float64)
    return shown


def _inside(x: float, y: float, size: tuple[float, float]) -> bool:
    return bool(-CULL_PX <= x <= size[0] + CULL_PX and -CULL_PX <= y <= size[1] + CULL_PX)


def legend_rows(overlay: Overlay, display: Any) -> list[LegendRow]:
    """Las filas de la leyenda de una vista (RF-005-23, RF-005-24): la de la litología de su
    esquema (su título, cada código con su descripción y «Sin dato») y la de las clases de su
    elemento (su título, cada clase y «< LD»), en el idioma de Geoblender."""
    rows: list[LegendRow] = []
    if overlay.lithology:
        rows.append(LegendRow(tr("Lithology ({scheme})", scheme=overlay.log_set)))
        rows.extend(LegendRow(" · ".join((entry.label, entry.description))
                              if entry.description else entry.label, entry.color)
                    for entry in overlay.lithology)
    if overlay.grade is not None:
        rows.append(LegendRow(f"{overlay.element} ({overlay.grade.unit})"))
        rows.extend(LegendRow(entry.label, entry.color) for entry in overlay.grade.entries())
    return rows


def _legend_items(rows: Sequence[LegendRow], measure: Callable[[str], float],
                  scale: float) -> list[Any]:
    """La leyenda abajo a la izquierda: su fondo y, de arriba abajo, cada fila (los títulos a
    la izquierda; las entradas, su cuadro de color y su texto)."""
    if not rows:
        return []
    row, swatch, gap = ROW_PX * scale, SWATCH_PX * scale, GAP_PX * scale
    margin, pad = MARGIN_PX * scale, PAD_PX * scale
    width = max(float(measure(item.text)) + (swatch + gap if item.color else 0.0)
                for item in rows)
    height = len(rows) * row
    items: list[Any] = [Box(margin - pad, margin - pad, margin + width + pad,
                            margin + height + pad, PANEL)]
    baseline = (row - FONT_PX * scale) / 2.0 + 2.0 * scale
    for index, item in enumerate(rows):
        bottom = margin + height - (index + 1) * row
        if item.color is None:
            items.append(Text(margin, bottom + baseline, item.text, LEGEND_COLOR))
            continue
        low = bottom + (row - swatch) / 2.0
        items.append(Box(margin, low, margin + swatch, low + swatch, _rgba(item.color)))
        items.append(Text(margin + swatch + gap, bottom + baseline, item.text, LEGEND_COLOR))
    return items


def screen_items(overlays: Sequence[Overlay], display: Any, matrix: Any,
                 size: tuple[float, float], *, measure: Callable[[str], float],
                 scale: float = 1.0) -> list[Any]:
    """Lo que dibuja la superposición en una Vista 3D (véase el módulo), en píxeles de su
    región (``size``) con la matriz de la vista ``matrix``: las etiquetas de cada vista
    ``overlays`` (si la representación ``display`` las pide; las del fondo, con «Profundidad
    en el fondo»), las marcas de sus bocas y la leyenda de la primera (con «Leyenda»).
    ``measure`` da el ancho en px de un texto; ``scale``, la escala de la interfaz."""
    items: list[Any] = []
    offsets = {False: (LABEL_OFFSET[0] * scale, LABEL_OFFSET[1] * scale),
               True: (BOTTOM_OFFSET[0] * scale, BOTTOM_OFFSET[1] * scale)}
    code_dx, code_dy = CODE_OFFSET[0] * scale, CODE_OFFSET[1] * scale
    half = MARK_PX * scale
    for overlay in overlays:
        if display.show_labels:
            shown = [label for label in overlay.labels
                     if display.labels_at_end or not label.bottom]
            for label, (x, y) in zip(shown, to_screen([label.xyz for label in shown], matrix,
                                                      size).tolist(), strict=True):
                if _inside(x, y, size):
                    dx, dy = offsets[label.bottom]
                    items.append(Text(x + dx, y + dy, label.text, LABEL_COLOR))
        marks = overlay.marks
        for mark, (x, y) in zip(marks, to_screen([mark.xyz for mark in marks], matrix,
                                                 size).tolist(), strict=True):
            if not _inside(x, y, size):
                continue
            if mark.kind == EXCLUDED:
                cross = np.array([[x - half, y - half], [x + half, y + half],
                                  [x - half, y + half], [x + half, y - half]])
                items.append(Lines(cross, EXCLUDED_COLOR, MARK_WIDTH_PX * scale))
            if mark.kind in (EXCLUDED, PARTIAL):
                items.append(Text(x + code_dx, y + code_dy, " · ".join(mark.codes),
                                  EXCLUDED_COLOR))
            elif mark.kind == STALE:
                items.append(Text(x + code_dx, y + code_dy - ROW_PX * scale, tr("Stale trace"),
                                  STALE_COLOR))
    if display.show_legend and overlays:
        items.extend(_legend_items(legend_rows(overlays[0], display), measure, scale))
    return items


def paint(items: Sequence[Any], size: tuple[float, float], *, scale: float = 1.0) -> None:
    """Pinta ``items`` (los de :func:`screen_items`) en la región activa (``POST_PIXEL``, de
    ancho y alto ``size``): los cuadros y las aspas con ``gpu``, los textos con ``blf`` y su
    sombra; deja el estado de ``gpu`` y de la fuente como estaban."""
    fill = gpu.shader.from_builtin(FILL_SHADER)
    line = gpu.shader.from_builtin(LINE_SHADER)
    blend = gpu.state.blend_get()
    gpu.state.blend_set("ALPHA")
    blf.size(FONT_ID, FONT_PX * scale)
    blf.enable(FONT_ID, blf.SHADOW)
    blf.shadow(FONT_ID, 3, *SHADOW)
    blf.shadow_offset(FONT_ID, 1, -1)
    try:
        for item in items:
            if isinstance(item, Box):
                corners = [(item.x0, item.y0, 0.0), (item.x1, item.y0, 0.0),
                           (item.x1, item.y1, 0.0), (item.x0, item.y1, 0.0)]
                batch = batch_for_shader(fill, "TRIS", {"pos": corners},
                                         indices=((0, 1, 2), (0, 2, 3)))
                fill.uniform_float("color", item.color)
                batch.draw(fill)
            elif isinstance(item, Lines):
                points = [(float(x), float(y), 0.0) for x, y in item.points.tolist()]
                batch = batch_for_shader(line, "LINES", {"pos": points})
                line.uniform_float("viewportSize", tuple(float(value) for value in size))
                line.uniform_float("lineWidth", float(item.width))
                line.uniform_float("color", item.color)
                batch.draw(line)
            else:
                blf.position(FONT_ID, float(item.x), float(item.y), 0.0)
                blf.color(FONT_ID, *item.color)
                blf.draw(FONT_ID, item.text)
    finally:
        blf.disable(FONT_ID, blf.SHADOW)
        gpu.state.blend_set(blend)


def shown_overlays(context: Any, space: Any) -> list[Overlay]:
    """Lo que dibujan las vistas de los sondeos visibles en la Vista 3D ``space`` (una vez cada
    una, aunque tenga tubos y barras)."""
    view_layer = context.view_layer
    found: list[Overlay] = []
    seen: set[int] = set()
    for obj in view_layer.objects:
        if getattr(obj, OBJECT_PROPERTY).kind != dh_view.KIND:
            continue
        overlay = dh_view.overlay_of(obj)
        if overlay is None or id(overlay) in seen:
            continue
        if obj.visible_get(view_layer=view_layer, viewport=space):
            seen.add(id(overlay))
            found.append(overlay)
    return found


_handle: Any = None
_failed = False


def drawing() -> bool:
    """Si la superposición está registrada (dibuja en cada Vista 3D)."""
    return _handle is not None


def _measure(text: str) -> float:
    return float(blf.dimensions(FONT_ID, text)[0])


def _draw() -> None:
    """El manejador ``POST_PIXEL`` de cada Vista 3D (véase el módulo)."""
    global _failed
    if _failed:
        return
    try:
        context = bpy.context
        space, region, rv3d = context.space_data, context.region, context.region_data
        if space is None or region is None or rv3d is None or not space.overlay.show_overlays:
            return
        display = getattr(context.scene, SCENE_PROPERTY, None)
        overlays = shown_overlays(context, space) if display is not None else []
        if not overlays:
            return
        scale = float(context.preferences.system.ui_scale)
        size = (float(region.width), float(region.height))
        blf.size(FONT_ID, FONT_PX * scale)
        items = screen_items(overlays, display, np.array(rv3d.perspective_matrix), size,
                             measure=_measure, scale=scale)
        if items:
            paint(items, size, scale=scale)
    except Exception:  # una traza por fotograma no ayuda a nadie
        _failed = True
        LOGGER.exception("No se pueden dibujar las etiquetas, las leyendas y las marcas de los "
                         "sondeos: la superposición se apaga")


def register() -> None:
    """Pone el manejador de dibujo; si ya está, nada."""
    global _handle, _failed
    if _handle is None:
        _handle = bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_PIXEL")
    _failed = False


def unregister() -> None:
    """Quita el manejador de dibujo; si no está, nada."""
    global _handle
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, "WINDOW")
        _handle = None

# SPDX-License-Identifier: GPL-3.0-or-later
"""La vista previa de una entidad de diseño en la Vista 3D (spec 015, T29; HU-015-3; RF-015-26; RNF-015-06;
plan 015 §5.1 y §5.5; comprobación manual M4).

Con ella activa (``geoblender.des_entity_preview`` o el botón «Vista previa» del diálogo de «Plataforma…»), la
Vista 3D enseña, encima de la escena y **sin escribir nada en el proyecto ni crear objetos** (como la vista
previa de la 013, ``bl.draw.design``, de la que reutiliza lo que se dibuja: :class:`bl.draw.design.Built`, el
resumen y la leyenda), lo que va a ser una plataforma **antes de calcularla** (``design.preview.EntityPreview``):

- **la huella**, el contorno de sus celdas con sus huecos (:data:`FOOTPRINT`);
- **el eje con la flecha de su sentido** (:data:`AXIS` y :data:`ARROW`): la abscisa 0 está en el inicio del eje (el
  primer vértice de una línea; en un polígono con línea enlazada, donde la línea entra: T45, D-8), que es lo que
  decide el signo de la pendiente, y la flecha apunta al final; con **la cota de la rasante en sus
  dos extremos** escrita junto a cada uno;
- **lo que se le apoya** (:data:`RESTING`): las huellas de lo que se apoya en ella o parte de su superficie, con
  su nombre y su volumen (solo si la entidad ya está en la versión; una nueva no tiene nada apoyado);
- **las restricciones que declarará** (:data:`ZONE`): si protege, la zona de su huella con su resguardo, en el
  color de su tipo, con su nombre como se leerá en «Ver restricciones y límites»;
- **su leyenda** (una fila por pieza presente) y **su resumen** arriba a la izquierda (también en la vista,
  ``bl.ui.des_panels.show_preview``); sin dato, o con el rechazo de la preparación (RF-015-08, RF-015-09), **el
  aviso en lugar del dibujo**, con los mismos mensajes que «Calcular».

Con la **016** (spec 016, T32; HU-016-1 y HU-016-3; RF-016-23; plan 016 §5.5; comprobación manual M4) dibuja además, **antes de
calcular** y con el mismo patrón, lo que va a leer una **detección de acopios** (:class:`EntityPlan` con ``stockpile``: **las marcas**
de su capa, con las celdas que leerá la detección, :data:`MARKS`, y **la marca ampliada por su margen**, :data:`MARGIN`; con su nombre
y su margen junto a cada una) y la **zona de coronación de un contrafuerte** (``buttress``: la zona de coronación, :data:`CROWN`, y, si
protege y ha elegido el resguardo, **la zona que declarará «sin corte»** con él, :data:`ZONE`), cada una con su leyenda y su
resumen; lo que rechazaría «Calcular» de la capa, de los campos o de la geometría es el aviso en lugar del dibujo.

Con la **017** (spec 017, T28; HU-017-1; RF-017-26, RF-015-26; RNF-017-08; plan 017 §5.5; comprobación manual M5) dibuja también **una pista** (:class:`EntityPlan` con ``road``, una
``design.preview.RoadAsk``): **antes de calcular**, sin escribir nada, **el origen y el destino** (una cruz en cada uno con su cota: :data:`ORIGIN` y :data:`DESTINATION`; la zona de la cota de destino
de una rampa, :data:`TARGET`) y **el pasillo de la ruta** (:data:`CORRIDOR`: el contorno de los nodos de la red 2D en el pasillo, RF-017-09) o, en «sobre un eje» y «eje 3D», la línea que sigue
(:data:`LINE`); y **tras calcular** (lo que dejó «Calcular», o una pista de la versión por su código: ``geoblender.des_entity_preview``) **el eje con sus curvas y la flecha de su sentido**
(:data:`AXIS` y :data:`ARROW`), **las cotas y las pendientes de la rasante por tramos coloreados según pd y pm** (:data:`GRADIENT_WITHIN`, :data:`GRADIENT_MEAN` y :data:`GRADIENT_DESIGN`, con la cota
y la pendiente de cada tramo junto a él), **la anchura de la sección** (:data:`SECTION`: sus dos bordes) y **lo que se le apoya** (:data:`RESTING`), con su leyenda. Los lotes los arma
:func:`_build_road` sin ``gpu``, como los de la plataforma.

Aquí **no se calcula nada de minería**: lo dice ``design.preview.entity_preview_steps`` (que solo lee: ni compila
las máscaras) y este módulo lo dibuja. Lo que se dibuja se construye sin ``gpu`` y se prueba en sus lotes
(``docs/trampas.md`` §3: sin GPU en ``blender -b``), **por pasos** de :data:`STEP_BUDGET_S` s con el temporizador
(:func:`tick`; RNF-015-06: activarla con 200 entidades ≤ 1 s y cada redibujo ≤ 5 ms). Se **rehace**
(:func:`rebuild`) al cambiar la versión activa o lo que lee (:func:`stamp`, el de la 012) y al cambiar lo que se
prepara (:func:`replace`: la orden la llama al cambiar los campos de su diálogo), y se **quita**
(:func:`disable`) al pulsar su control otra vez, **al cancelar** la orden, al crearla, al cerrar o cambiar de
proyecto, al **conmutar a la interfaz de Blender** (``bl.ui.switcher.add_blender_hook``) y al desactivar
Geoblender (:func:`unregister`, principio 8). Un error al dibujar se registra una vez y deja de dibujar: nunca una
traza por fotograma. Las posiciones son locales respecto al GeoOrigin (float64 hasta el último paso, ADR-0005).
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable, Generator, Sequence
from dataclasses import dataclass
from typing import Any

import blf
import bpy
import gpu
import numpy as np

from ...core.errors import GeoblenderError
from ...core.i18n import format_number, language, tr
from ...design import preview as design_preview
from ...design.preview import EntityPreview, GradientStatus
from ..scene import project_session
from ..scene import versions as scene_versions
from ..scene.constraint_views import declared_text
from . import constraints, design as design_draw, dh_overlay
from .constraints import Batch, Label
from .dh_overlay import LegendRow

__all__ = [
    "ARROW", "ARROW_COLOR", "AXIS", "AXIS_COLOR", "CORRIDOR", "CORRIDOR_COLOR", "CROWN", "CROWN_COLOR", "DESTINATION",
    "DESTINATION_COLOR", "EntityPlan", "FOOTPRINT", "FOOTPRINT_COLOR", "GRADIENT_COLORS", "GRADIENT_DESIGN",
    "GRADIENT_MEAN", "GRADIENT_WITHIN", "LINE", "LINE_COLOR", "MARGIN", "MARGIN_COLOR", "MARKS", "MARK_COLOR", "ORIGIN",
    "ORIGIN_COLOR", "RESTING", "RESTING_COLOR", "Request", "SECTION", "SECTION_COLOR", "TARGET", "ZONE", "arrow_segments",
    "build_steps", "building", "built", "cross_segments", "disable", "drawing", "enable", "enabled", "on_project_changed",
    "on_project_read", "on_version_changed", "plan", "preview", "rebuild", "register", "replace", "stamp", "tick",
    "unregister",
]

LOGGER = logging.getLogger("geoblender.bl.draw")

FOOTPRINT = "entity_footprint"
AXIS = "entity_axis"
ARROW = "entity_arrow"
RESTING = "entity_resting"
ZONE = "entity_zone"
"""Las claves (y los papeles: todos con ``constraints.OUTLINE``) de los lotes de la vista previa: la huella, el eje, la
flecha de su sentido, lo que se le apoya y la zona que declarará."""

MARKS = "stockpile_marks"
MARGIN = "stockpile_margin"
CROWN = "buttress_crown"
"""Las claves (con el papel ``constraints.OUTLINE``) de los lotes de la vista previa de la 016: las marcas de una detección de acopios,
las marcas ampliadas por su margen y la zona de coronación de un contrafuerte (la zona con su resguardo es :data:`ZONE`)."""

ORIGIN = "road_origin"
DESTINATION = "road_destination"
TARGET = "road_target"
CORRIDOR = "road_corridor"
LINE = "road_line"
SECTION = "road_section"
GRADIENT_WITHIN = "road_gradient_within"
GRADIENT_MEAN = "road_gradient_mean"
GRADIENT_DESIGN = "road_gradient_design"
"""Las claves (con el papel ``constraints.OUTLINE``) de los lotes de la vista previa de una pista (spec 017, T28): el origen y el destino (una cruz cada uno), la zona de la cota de destino de una rampa,
el pasillo de la ruta, la línea que sigue «sobre un eje» o «eje 3D», los bordes de la sección y los tramos de la rasante por su estado (dentro de los límites, por encima de pm y por encima de pd); el
eje y su flecha son :data:`AXIS` y :data:`ARROW` y lo que se le apoya, :data:`RESTING`."""

STEP_BUDGET_S = constraints.STEP_BUDGET_S
"""Lo que dura como mucho cada paso de la construcción (ninguna llamada de más de 0,2 s)."""
TICK_BUDGET_S = constraints.TICK_BUDGET_S
TICK_INTERVAL_S = constraints.TICK_INTERVAL_S
"""Lo que avanza como mucho cada llamada del temporizador y la espera entre dos."""

FOOTPRINT_COLOR: constraints.Color = (0.10, 0.80, 0.70, 1.0)
AXIS_COLOR: constraints.Color = (1.0, 1.0, 1.0, 1.0)
ARROW_COLOR: constraints.Color = (1.0, 1.0, 1.0, 1.0)
RESTING_COLOR: constraints.Color = (1.0, 0.65, 0.10, 1.0)
"""El color de la huella (verde azulado, el del objeto de la entidad), del eje y de su flecha (blanco) y de lo que se
le apoya (naranja). La zona que declarará, el de su tipo de restricción (``constraints.color_of``)."""
MARK_COLOR: constraints.Color = (1.0, 0.85, 0.15, 1.0)
MARGIN_COLOR: constraints.Color = (1.0, 0.45, 0.05, 1.0)
CROWN_COLOR: constraints.Color = FOOTPRINT_COLOR
"""El color de las marcas (amarillo), de la marca ampliada por su margen (naranja oscuro, distinto del de lo que se apoya) y de la zona de
coronación de un contrafuerte (verde azulado, el de la huella: es la huella que se le da). Son de dibujo, no un dato minero."""
ORIGIN_COLOR: constraints.Color = (0.20, 0.95, 0.45, 1.0)
DESTINATION_COLOR: constraints.Color = (0.95, 0.30, 0.85, 1.0)
CORRIDOR_COLOR: constraints.Color = (0.45, 0.62, 1.0, 1.0)
LINE_COLOR: constraints.Color = (0.85, 0.85, 0.85, 1.0)
SECTION_COLOR: constraints.Color = (0.75, 0.80, 0.95, 1.0)
GRADIENT_COLORS: dict[str, constraints.Color] = {
    GRADIENT_WITHIN: (0.55, 0.85, 0.25, 1.0),
    GRADIENT_MEAN: (1.0, 0.75, 0.10, 1.0),
    GRADIENT_DESIGN: (0.95, 0.20, 0.20, 1.0),
}
"""Los colores de la pista (spec 017, T28; de dibujo, no un dato minero): el origen (verde), el destino y la zona de su cota (magenta), el pasillo (azul), la línea que sigue un eje (gris claro), los bordes de
la sección (azul grisáceo) y los tramos de la rasante: dentro de los límites del perfil (verde amarillento), con la media por encima de pm (ámbar) y con un paso por encima de pd (rojo)."""
FOOTPRINT_PX = 3.0
AXIS_PX = 2.5
RESTING_PX = 2.5
ZONE_PX = constraints.OUTLINE_PX
MARK_PX = 3.0
MARGIN_PX = 2.0
CROWN_PX = 3.0
POINT_PX = 3.0
CORRIDOR_PX = 1.5
LINE_PX = 1.5
SECTION_PX = 1.5
GRADIENT_PX = 4.0
"""El trazo (px) de cada pieza."""
POINT_ARM_CELLS = 3.0
"""El brazo de la cruz del origen y del destino de una pista: :data:`bl.draw.constraints.POINT_ARM_M` m o, si es más, esta cantidad de celdas (de dibujo, no un dato minero)."""
ARROW_HALF_ANGLE_DEG = 25.0
"""El ángulo entre cada lado de la punta de la flecha y el eje (° ; es de dibujo, no un dato minero)."""
ARROW_HEAD_FRACTION = 0.10
ARROW_HEAD_MIN_CELLS = 2.0
ARROW_HEAD_MAX_M = 20.0
"""El largo de la punta de la flecha: la décima parte del eje, de dos celdas a 20 m (de dibujo, no un dato minero)."""


# --- Los datos de lo que se prepara ---------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class EntityPlan:
    """Lo que se previsualiza: la plataforma **que se prepara** (``request``, la ``design.model.PlatformRequest`` del
    diálogo de «Plataforma…»: una entidad nueva), **una que ya está en la versión** (``code``: su código o su
    nombre, con sus parámetros vigentes), las **marcas de una detección de acopios** que se prepara (``stockpile``, la
    ``design.model.StockpileRequest``; spec 016, T32), **la zona de coronación de un contrafuerte** que se prepara
    (``buttress``, la ``design.model.ButtressRequest``) o **una pista** (``road``, la ``design.preview.RoadAsk``: la que se prepara,
    con lo que ya hizo «Calcular», o una de la versión por su código; spec 017, T28). Uno de los cinco, no más. ``insert_before``
    (T31; RF-015-05): si la plataforma que se prepara se **inserta** antes de otra entidad de la versión, el código de esa entidad
    (la que pasaría a partir de la nueva); solo con ``request``."""

    request: Any = None
    code: str | None = None
    insert_before: str | None = None
    stockpile: Any = None
    buttress: Any = None
    road: Any = None

    def __post_init__(self) -> None:
        asked = [name for name in ("request", "code", "stockpile", "buttress", "road") if getattr(self, name) is not None]
        if len(asked) != 1:
            raise ValueError("la vista previa de una entidad es de una sola cosa: la plataforma que se prepara (su petición), una "
                             "entidad de la versión (su código), las marcas de una detección de acopios, la zona de coronación "
                             "de un contrafuerte o una pista, no de dos ni de ninguna")
        if self.insert_before is not None and self.request is None:
            raise ValueError("una inserción se previsualiza con la plataforma que se prepara (su petición), no con una "
                             "entidad que ya está en la versión")

    @property
    def kind(self) -> str:
        """Qué se previsualiza: ``"platform"`` (la que se prepara), ``"entity"`` (una de la versión), ``"stockpile"``, ``"buttress"`` o ``"road"``."""
        if self.stockpile is not None:
            return "stockpile"
        if self.buttress is not None:
            return "buttress"
        if self.road is not None:
            return "road"
        return "platform" if self.request is not None else "entity"


@dataclass(frozen=True, eq=False)
class Request:
    """Lo que se construye: el proyecto, la versión (``None``: ninguna) y su código, lo que se previsualiza, el
    idioma de los textos y el sello de lo que se lee."""

    project: Any
    version_uid: str | None
    version_code: str
    plan: EntityPlan
    language: str
    stamp: tuple[Any, ...]


# --- Funciones puras (sin gpu) --------------------------------------------------------------------


def arrow_segments(axis: Sequence[tuple[float, float]], head_m: float) -> np.ndarray:
    """Los dos lados de la punta de la flecha del sentido de ``axis`` (los vértices ``(x, y)`` absolutos, de la
    abscisa 0 al último): segmentos ``(2, 2, 2)`` absolutos (float64) que salen **del último vértice**, hacia atrás
    sobre su último tramo con un largo de ``head_m`` m y ±:data:`ARROW_HALF_ANGLE_DEG` ° respecto a él. El último
    tramo es el último de longitud > 0; sin ninguno (un eje sin longitud), ``(0, 2, 2)``."""
    points = np.asarray(axis, dtype=np.float64).reshape(-1, 2)
    end = points[-1]
    for before in points[-2::-1]:
        step = end - before
        length = float(np.hypot(step[0], step[1]))
        if length > 0.0:
            back = -step / length
            break
    else:
        return np.empty((0, 2, 2), dtype=np.float64)
    angle = np.radians(ARROW_HALF_ANGLE_DEG)
    found = np.empty((2, 2, 2), dtype=np.float64)
    for index, sign in enumerate((1.0, -1.0)):
        cos, sin = np.cos(sign * angle), np.sin(sign * angle)
        side = np.array([back[0] * cos - back[1] * sin, back[0] * sin + back[1] * cos])
        found[index] = (end, end + head_m * side)
    return found


def _head_m(length_m: float, cell_m: float) -> float:
    """El largo de la punta de la flecha de un eje de ``length_m`` m sobre una rejilla de celdas de ``cell_m`` m."""
    return float(min(max(ARROW_HEAD_FRACTION * length_m, ARROW_HEAD_MIN_CELLS * cell_m), ARROW_HEAD_MAX_M))


def _axis_segments(axis: Sequence[tuple[float, float]]) -> np.ndarray:
    """Los tramos ``(k, 2, 2)`` absolutos del eje."""
    points = np.asarray(axis, dtype=np.float64).reshape(-1, 2)
    return np.stack([points[:-1], points[1:]], axis=1)


def _level(value: float) -> str:
    """Una cota para un nombre: al centímetro, con el formato del idioma activo."""
    return format_number(value, 2)


def _hex(color: constraints.Color) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(round(float(part) * 255.0) for part in color[:3]))


# --- Construir ------------------------------------------------------------------------------------


def _drape(parts: Sequence[np.ndarray], key: str, color: constraints.Color, width_px: float, ground: Any,
           origin: Any, budget_s: float) -> Generator[None, None, Batch | None]:
    """El lote ``key`` de los segmentos ``parts`` (cada uno ``(k, 2, 2)`` absolutos), ajustado a ``ground`` (o a la
    cota del GeoOrigin sin ella); ``None`` si no hay ninguno."""
    drawn = [piece for piece in parts if len(piece)]
    if not drawn:
        return None
    positions = yield from constraints.drape_segments_steps(np.concatenate(drawn), ground, origin,
                                                            budget_s=budget_s)
    return Batch(key, constraints.OUTLINE, color, width_px, positions)


def _legend(request: Request, found: EntityPreview, ground: Any, drawn: set[str]) -> tuple[LegendRow, ...]:
    """La leyenda: el título con la entidad y la versión, una fila por pieza dibujada (con su color) y las notas (la
    superficie sobre la que se dibuja)."""
    shown = request.language
    version = request.version_code or tr("No version")
    rows = [LegendRow(tr("Preview of «{name}» ({code}) · {version}", name=found.name, code=found.code,
                         version=version) if found.code
                      else tr("Preview of «{name}» · {version}", name=found.name, version=version))]
    if FOOTPRINT in drawn:
        rows.append(LegendRow(tr("Footprint ({area} m²)", area=format_number(found.area_m2, 0)),
                              _hex(FOOTPRINT_COLOR)))
    if AXIS in drawn:
        rows.append(LegendRow(tr("Axis: the arrow shows its sense; the abscissa 0 is at its start (in a polygon with a "
                                "linked line, where the line enters)"),
                              _hex(AXIS_COLOR)))
        rows.append(LegendRow(tr("Level of the platform at the ends of the axis (m)")))
    if RESTING in drawn:
        rows.append(LegendRow(tr("Rests on it or starts from it ({count})", count=len(found.resting)),
                              _hex(RESTING_COLOR)))
    elif found.resting:
        rows.append(LegendRow(tr("Rests on it or starts from it ({count}), without a footprint of its own",
                                 count=len(found.resting))))
    if ZONE in drawn and found.declares is not None and found.guard_m is not None:
        rows.append(LegendRow(
            tr("Declares «{type}» with a guard of {guard} m ({area} m²)", type=found.declares.label(shown),
               guard=format_number(found.guard_m, 1), area=format_number(found.zone_area_m2, 0)),
            _hex(constraints.color_of(found.declares.value))))
    if found.drawable:
        rows.append(LegendRow(tr("At the elevation of the GeoOrigin") if ground is None
                              else tr("On the surface «{name}»", name=ground.name)))
    return tuple(rows)


def build_steps(request: Request, *, budget_s: float = STEP_BUDGET_S) -> Generator[None, None, design_draw.Built]:
    """:func:`_build` sin la preparación de la entidad: el resultado es solo lo que se dibuja (un
    :class:`bl.draw.design.Built`)."""
    built_view, _found = yield from _build(request, budget_s)
    return built_view


def _run_preview(steps: Any) -> Generator[None, None, Any]:
    """Los pasos de una preparación de ``design.preview`` (``Progress`` con el resumen en el último) dados de uno en uno: lo que
    lleva el último. Cerrarlo a mitad cierra la preparación."""
    found = None
    try:
        for step in steps:
            if step.result is not None:
                found = step.result
            yield
    finally:
        close = getattr(steps, "close", None)
        if close is not None:
            close()
    return found


def _without_version(request: Request) -> tuple[design_draw.Built, None]:
    """Lo que dibuja la vista previa de una entidad sin versión activa: nada, y lo dice."""
    lines = constraints.Built(request.version_uid, request.version_code, "", "", (), (),
                              (LegendRow(tr("Preview of an entity")),
                               LegendRow(tr("No active version: nothing to preview"))), request.stamp)
    notice = tr("There is no active version: the preview of an entity needs one")
    return design_draw.Built(lines, None, (), ((notice, True),)), None


def _build(request: Request, budget_s: float) -> Generator[None, None, tuple[design_draw.Built, Any]]:
    """Los pasos que construyen lo que dibuja la vista previa para ``request`` según lo que se previsualiza
    (:attr:`EntityPlan.kind`): la plataforma (:func:`_build_platform`), las marcas de una detección de acopios
    (:func:`_build_stockpile`), la zona de coronación de un contrafuerte (:func:`_build_buttress`) o una pista (:func:`_build_road`). El resultado es el
    ``StopIteration.value``: lo que se dibuja (un :class:`bl.draw.design.Built`) y la preparación (``None`` sin versión activa)."""
    kind = request.plan.kind
    if kind == "stockpile":
        return (yield from _build_stockpile(request, budget_s))
    if kind == "buttress":
        return (yield from _build_buttress(request, budget_s))
    if kind == "road":
        return (yield from _build_road(request, budget_s))
    return (yield from _build_platform(request, budget_s))


def _build_platform(request: Request, budget_s: float
                    ) -> Generator[None, None, tuple[design_draw.Built, EntityPreview | None]]:
    """Los pasos que construyen lo que dibuja la vista previa de una plataforma para ``request`` (véase el módulo): la preparación de
    la entidad (``design.preview.entity_preview_steps``: solo lee y no compila las máscaras), la superficie sobre la que
    se dibuja (la de partida) y los lotes, los nombres, la leyenda y el resumen. Cada paso dura como mucho
    ``budget_s`` s (salvo una lectura, nunca de más de 0,2 s); el resultado es el ``StopIteration.value``: lo que se
    dibuja (un :class:`bl.draw.design.Built`, sin semillas ni sectores) y la preparación de la entidad
    (``None`` sin versión activa). Lo que rechazaría «Calcular» sale en el resumen, no como un error; los demás
    errores (una versión o una entidad que no están) salen al avanzar. Cerrarlo a mitad no deja nada. Sin versión
    activa, solo lo dice."""
    project, version_uid, shown = request.project, request.version_uid, request.language
    origin = project.origin
    found: EntityPreview | None = None
    if version_uid:
        asked = request.plan
        steps = design_preview.entity_preview_steps(project, asked.request, version_uid, code=asked.code,
                                                    insert_before=asked.insert_before, budget_s=budget_s)
        found = yield from _run_preview(steps)
    if found is None:  # sin versión: lo dice, no hay nada que dibujar
        return _without_version(request)
    ground = None
    batches: list[Batch] = []
    labels: list[Label] = []
    drawn: set[str] = set()
    if found.drawable:
        ground = yield from constraints.ground_steps(project, found.start_surface, version_uid,
                                                     budget_s=budget_s)
        cell = found.cell_m
        pieces: list[tuple[str, constraints.Color, float, list[np.ndarray]]] = [
            (FOOTPRINT, FOOTPRINT_COLOR, FOOTPRINT_PX, [design_draw.ring_segments(found.outline)]),
            (AXIS, AXIS_COLOR, AXIS_PX, [_axis_segments(found.axis)]),
            (ARROW, ARROW_COLOR, AXIS_PX, [arrow_segments(found.axis, _head_m(found.length_m, cell))]),
            (RESTING, RESTING_COLOR, RESTING_PX,
             [design_draw.ring_segments(item.rings) for item in found.resting if item.rings])]
        if found.zone and found.declares is not None:
            pieces.append((ZONE, constraints.color_of(found.declares.value), ZONE_PX,
                           [design_draw.ring_segments(found.zone)]))
        for key, color, width, parts in pieces:
            batch = yield from _drape(parts, key, color, width, ground, origin, budget_s)
            if batch is not None:
                batches.append(batch)
                drawn.add(key)
        named: list[tuple[str, tuple[float, float], constraints.Color]] = []
        for end in found.ends:
            text = (tr("Start (abscissa 0) · level {level} m", level=_level(end.level_m)) if end.which == "start"
                    else tr("End · level {level} m", level=_level(end.level_m)))
            named.append((text, (end.x, end.y), AXIS_COLOR))
        for item in found.resting:
            place = design_draw.ring_center(item.rings)
            if place is not None:
                text = (tr("«{name}» · {volume} m³ rest on it", name=item.name,
                           volume=format_number(item.volume_m3, 0)) if item.volume_m3 is not None
                        else tr("«{name}» starts from its surface", name=item.name))
                named.append((text, place, RESTING_COLOR))
        if found.zone and found.declares is not None and found.guard_m is not None:
            place = design_draw.ring_center(found.zone)
            if place is not None:
                zone_color = constraints.color_of(found.declares.value)
                named.append((tr("{name} · guard {guard} m",
                                 name=declared_text(found.code or "PLT-000", found.name),
                                 guard=format_number(found.guard_m, 1)), place, zone_color))
        places = np.array([place for _text, place, _color in named], dtype=np.float64).reshape(-1, 2)
        spots = yield from constraints.drape_points_steps(places, ground, origin, budget_s=budget_s)
        labels.extend(Label(text, (float(x), float(y), float(z)), color)
                      for (text, _place, color), (x, y, z) in zip(named, spots.tolist(), strict=True))
    lines = constraints.Built(version_uid, request.version_code, found.masks.value,
                              "" if ground is None else ground.name, tuple(batches), tuple(labels),
                              _legend(request, found, ground, drawn), request.stamp)
    return design_draw.Built(lines, None, (), found.lines(shown)), found


def _span(values: Sequence[float]) -> str:
    """Un margen o un rango de márgenes (m) para la leyenda: ``10,0 m`` o ``6,0 – 10,0 m``."""
    low, high = min(values), max(values)
    return f"{format_number(low, 1)} m" if low == high else f"{format_number(low, 1)} – {format_number(high, 1)} m"


def _mark_label(found: Any) -> str:
    """El nombre de una marca (:class:`design.preview.MarkPreview`) junto a ella: su nombre y su margen, su material y su base."""
    text = tr("«{name}» · margin {margin} m", name=found.name, margin=format_number(found.margin_m, 1))
    if found.material:
        text = tr("{text} · material {material}", text=text, material=found.material)
    if found.base:
        text = tr("{text} · base «{base}»", text=text, base=found.base)
    return text


def _stockpile_legend(request: Request, found: Any, ground: Any, drawn: set[str]) -> tuple[LegendRow, ...]:
    """La leyenda de las marcas: el título con la detección y su ámbito, una fila por pieza dibujada (con su color) y la superficie."""
    where = found.version or tr("Project")
    rows = [LegendRow(tr("Preview of «{name}» ({code}) · {version}", name=found.name, code=found.code, version=where)
                      if found.code else tr("Preview of «{name}» · {version}", name=found.name, version=where))]
    if MARKS in drawn:
        rows.append(LegendRow(tr("Marks ({count}, {area} m²): the cells the detection will read", count=len(found.marks),
                                 area=format_number(sum(item.area_m2 for item in found.marks), 0)), _hex(MARK_COLOR)))
    if MARGIN in drawn:
        margins = [item.margin_m for item in found.marks if item.enlarged]
        rows.append(LegendRow(tr("Marks enlarged by their margin ({margins})", margins=_span(margins)), _hex(MARGIN_COLOR)))
    if found.drawable:
        rows.append(LegendRow(tr("At the elevation of the GeoOrigin") if ground is None
                              else tr("On the surface «{name}»", name=ground.name)))
    return tuple(rows)


def _build_stockpile(request: Request, budget_s: float) -> Generator[None, None, tuple[design_draw.Built, Any]]:
    """Los pasos que construyen lo que dibuja la vista previa de las marcas de una detección de acopios (spec 016, T32; RF-016-23):
    la preparación (``design.preview.stockpile_preview_steps``: solo lee la capa de marcas y la rejilla del proyecto; la detección de una
    superficie del proyecto no necesita versión, D-15), la superficie sobre la que se detecta, los lotes de las marcas y de sus
    ampliadas por el margen, el nombre de cada marca junto a ella, la leyenda y el resumen. Como :func:`_build_platform`: lo que
    rechazaría «Calcular» sale en el resumen, en lugar del dibujo."""
    project, version_uid, shown = request.project, request.version_uid, request.language
    origin = project.origin
    steps = design_preview.stockpile_preview_steps(project, request.plan.stockpile, version_uid or None, budget_s=budget_s)
    found = yield from _run_preview(steps)
    ground = None
    batches: list[Batch] = []
    labels: list[Label] = []
    drawn: set[str] = set()
    if found.drawable:
        ground = yield from constraints.ground_steps(project, found.surface, version_uid, budget_s=budget_s)
        pieces = [(MARKS, MARK_COLOR, MARK_PX, [design_draw.ring_segments(item.rings) for item in found.marks]),
                  (MARGIN, MARGIN_COLOR, MARGIN_PX, [design_draw.ring_segments(item.enlarged) for item in found.marks
                                                     if item.enlarged])]
        for key, color, width, parts in pieces:
            batch = yield from _drape(parts, key, color, width, ground, origin, budget_s)
            if batch is not None:
                batches.append(batch)
                drawn.add(key)
        places = np.array([(item.x, item.y) for item in found.marks], dtype=np.float64).reshape(-1, 2)
        spots = yield from constraints.drape_points_steps(places, ground, origin, budget_s=budget_s)
        labels.extend(Label(_mark_label(item), (float(x), float(y), float(z)), MARK_COLOR)
                      for item, (x, y, z) in zip(found.marks, spots.tolist(), strict=True))
    lines = constraints.Built(version_uid, request.version_code, "", "" if ground is None else ground.name, tuple(batches),
                              tuple(labels), _stockpile_legend(request, found, ground, drawn), request.stamp)
    return design_draw.Built(lines, None, (), found.lines(shown)), found


def _buttress_legend(request: Request, found: Any, ground: Any, drawn: set[str]) -> tuple[LegendRow, ...]:
    """La leyenda de la zona de coronación: el título con el contrafuerte y su versión, una fila por pieza dibujada y la superficie."""
    shown = request.language
    version = request.version_code or tr("No version")
    rows = [LegendRow(tr("Preview of «{name}» ({code}) · {version}", name=found.name, code=found.code, version=version)
                      if found.code else tr("Preview of «{name}» · {version}", name=found.name, version=version))]
    if CROWN in drawn:
        rows.append(LegendRow(tr("Crown zone ({cells} cells, {area} m²)", cells=found.crown_cells,
                                 area=format_number(found.crown_area_m2, 0)), _hex(CROWN_COLOR)))
    if ZONE in drawn and found.declares is not None and found.guard_m is not None:
        rows.append(LegendRow(
            tr("Declares «{type}» with a guard of {guard} m ({area} m²)", type=found.declares.label(shown),
               guard=format_number(found.guard_m, 1), area=format_number(found.zone_area_m2, 0)),
            _hex(constraints.color_of(found.declares.value))))
    if found.drawable:
        rows.append(LegendRow(tr("At the elevation of the GeoOrigin") if ground is None
                              else tr("On the surface «{name}»", name=ground.name)))
    return tuple(rows)


def _top_of(rings: Sequence[np.ndarray]) -> tuple[float, float] | None:
    """El punto medio del borde norte de la caja de unos anillos (donde se escribe el nombre de una zona que rodea a otra)."""
    points = [np.asarray(ring, dtype=np.float64).reshape(-1, 2) for ring in rings if len(ring)]
    if not points:
        return None
    every = np.concatenate(points)
    low, high = every.min(axis=0), every.max(axis=0)
    return (float((low[0] + high[0]) / 2.0), float(high[1]))


def _build_buttress(request: Request, budget_s: float) -> Generator[None, None, tuple[design_draw.Built, Any]]:
    """Los pasos que construyen lo que dibuja la vista previa de la zona de coronación de un contrafuerte (spec 016, T32; RF-016-23):
    la preparación (``design.preview.buttress_preview_steps``: solo lee la capa de las zonas y la rejilla del proyecto), la superficie
    de partida, los lotes de la zona de coronación y, si protege y ha elegido el resguardo, de la zona que declarará «sin corte», sus
    nombres, la leyenda y el resumen. Como :func:`_build_platform`: lo que rechazaría «Calcular» sale en el resumen, en lugar del
    dibujo; sin versión activa, solo lo dice."""
    project, version_uid, shown = request.project, request.version_uid, request.language
    origin = project.origin
    found = None
    if version_uid:
        steps = design_preview.buttress_preview_steps(project, request.plan.buttress, version_uid, budget_s=budget_s)
        found = yield from _run_preview(steps)
    if found is None:
        return _without_version(request)
    ground = None
    batches: list[Batch] = []
    labels: list[Label] = []
    drawn: set[str] = set()
    if found.drawable:
        ground = yield from constraints.ground_steps(project, found.start_surface, version_uid, budget_s=budget_s)
        pieces: list[tuple[str, constraints.Color, float, list[np.ndarray]]] = [
            (CROWN, CROWN_COLOR, CROWN_PX, [design_draw.ring_segments(found.crown_rings)])]
        if found.zone and found.declares is not None:
            pieces.append((ZONE, constraints.color_of(found.declares.value), ZONE_PX, [design_draw.ring_segments(found.zone)]))
        for key, color, width, parts in pieces:
            batch = yield from _drape(parts, key, color, width, ground, origin, budget_s)
            if batch is not None:
                batches.append(batch)
                drawn.add(key)
        crown_text = tr("Crown zone of «{name}» ({code})", name=found.name, code=found.code or "BTR-000")
        if found.crown_m is not None:
            crown_text = tr("{text} · crown at {crown} m", text=crown_text, crown=format_number(found.crown_m, 2))
        named: list[tuple[str, tuple[float, float], constraints.Color]] = [(crown_text, (found.x, found.y), CROWN_COLOR)]
        if found.zone and found.declares is not None and found.guard_m is not None:
            place = _top_of(found.zone)
            if place is not None:
                named.append((tr("{name} · guard {guard} m", name=declared_text(found.code or "BTR-000", found.name),
                                 guard=format_number(found.guard_m, 1)), place, constraints.color_of(found.declares.value)))
        places = np.array([place for _text, place, _color in named], dtype=np.float64).reshape(-1, 2)
        spots = yield from constraints.drape_points_steps(places, ground, origin, budget_s=budget_s)
        labels.extend(Label(text, (float(x), float(y), float(z)), color)
                      for (text, _place, color), (x, y, z) in zip(named, spots.tolist(), strict=True))
    lines = constraints.Built(version_uid, request.version_code, "", "" if ground is None else ground.name, tuple(batches),
                              tuple(labels), _buttress_legend(request, found, ground, drawn), request.stamp)
    return design_draw.Built(lines, None, (), found.lines(shown)), found


# --- La pista (spec 017, T28; RF-017-26) ----------------------------------------------------------

_GRADIENT_KEYS: dict[GradientStatus, str] = {
    GradientStatus.WITHIN: GRADIENT_WITHIN,
    GradientStatus.ABOVE_MEAN: GRADIENT_MEAN,
    GradientStatus.ABOVE_DESIGN: GRADIENT_DESIGN,
}
"""El lote de cada estado de un tramo de la rasante (:class:`design.preview.GradientStatus`)."""
ROAD_AXIS_PX = 1.5
"""El trazo del eje de una pista: una línea fina blanca sobre los tramos coloreados (:data:`GRADIENT_PX`)."""


def cross_segments(points: Sequence[tuple[float, float]], arm_m: float) -> np.ndarray:
    """Las dos rayas de la cruz de cada punto absoluto ``(x, y)`` de ``points``, de ``arm_m`` m de brazo hacia el este y el norte (y hacia el oeste y el sur): segmentos ``(2k, 2, 2)`` absolutos (float64);
    sin puntos, ``(0, 2, 2)``. Es lo que dibuja el origen y el destino de una pista."""
    found = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    if not len(found):
        return np.empty((0, 2, 2), dtype=np.float64)
    east, north = np.array([arm_m, 0.0]), np.array([0.0, arm_m])
    return np.concatenate([np.stack([found - east, found + east], axis=1), np.stack([found - north, found + north], axis=1)])


def _stretch_pieces(found: Any) -> dict[str, list[np.ndarray]]:
    """Los segmentos del eje de cada tramo de la rasante, agrupados por el lote de su estado: ``{clave: [(k, 2, 2), …]}`` con solo los estados que hay."""
    pieces: dict[str, list[np.ndarray]] = {}
    axis = found.axis
    for item in found.stretches:
        pieces.setdefault(_GRADIENT_KEYS[item.status], []).append(np.stack([axis[item.first:item.last], axis[item.first + 1:item.last + 1]], axis=1))
    return pieces


def _point_text(point: Any) -> str:
    """El nombre del origen o del destino junto a su cruz, con la cota de la rasante ahí si se conoce."""
    if point.which == "origin":
        return tr("Origin") if point.level_m is None else tr("Origin · level {level} m", level=_level(point.level_m))
    return tr("Destination") if point.level_m is None else tr("Destination · level {level} m", level=_level(point.level_m))


def _road_legend(request: Request, found: Any, ground: Any, drawn: set[str]) -> tuple[LegendRow, ...]:
    """La leyenda de la pista: el título con la pista y su versión, una fila por pieza dibujada (con su color: los tramos de la rasante con los límites del perfil, pd y pm) y la superficie."""
    version = request.version_code or tr("No version")
    rows = [LegendRow(tr("Preview of «{name}» ({code}) · {version}", name=found.name, code=found.code, version=version) if found.code
                      else tr("Preview of «{name}» · {version}", name=found.name, version=version))]
    if CORRIDOR in drawn:
        rows.append(LegendRow(tr("Corridor of the route ({nodes} nodes, margin {margin} m)", nodes=found.corridor_nodes, margin=format_number(found.margin_m or 0.0, 1)),
                              _hex(CORRIDOR_COLOR)))
    if LINE in drawn:
        rows.append(LegendRow(tr("Line the axis follows"), _hex(LINE_COLOR)))
    if ORIGIN in drawn:
        rows.append(LegendRow(tr("Origin"), _hex(ORIGIN_COLOR)))
    if DESTINATION in drawn:
        rows.append(LegendRow(tr("Destination"), _hex(DESTINATION_COLOR)))
    if TARGET in drawn:
        rows.append(LegendRow(tr("Destination zone: level {level} m, tolerance {tolerance} m", level=format_number(found.target_level_m or 0.0, 2),
                                 tolerance=format_number(found.target_tolerance_m or 0.0, 2)), _hex(DESTINATION_COLOR)))
    if AXIS in drawn:
        rows.append(LegendRow(tr("Axis with its curves ({length} m): the arrow shows its sense; the abscissa 0 is at the origin", length=format_number(found.length_m, 1)),
                              _hex(AXIS_COLOR)))
    if GRADIENT_WITHIN in drawn:
        rows.append(LegendRow(tr("Stretch within the limits of the profile (mean up to {mean} %)", mean=format_number(found.max_mean_gradient_pct or 0.0, 1)),
                              _hex(GRADIENT_COLORS[GRADIENT_WITHIN])))
    if GRADIENT_MEAN in drawn:
        rows.append(LegendRow(tr("Stretch with a mean gradient above the mean limit pm ({mean} %)", mean=format_number(found.max_mean_gradient_pct or 0.0, 1)), _hex(GRADIENT_COLORS[GRADIENT_MEAN])))
    if GRADIENT_DESIGN in drawn:
        rows.append(LegendRow(tr("Stretch with a step above the design gradient pd ({design} %)", design=format_number(found.max_gradient_pct or 0.0, 1)),
                              _hex(GRADIENT_COLORS[GRADIENT_DESIGN])))
    if SECTION in drawn:
        rows.append(LegendRow(tr("Edges of the section: {section} m wide (carriageway {carriageway} m)", section=format_number(found.section_m, 1),
                                 carriageway=format_number(found.carriageway_m, 1)), _hex(SECTION_COLOR)))
    if RESTING in drawn:
        rows.append(LegendRow(tr("Rests on it or starts from it ({count})", count=len(found.resting)), _hex(RESTING_COLOR)))
    elif found.resting:
        rows.append(LegendRow(tr("Rests on it or starts from it ({count}), without a footprint of its own", count=len(found.resting))))
    if found.drawable:
        rows.append(LegendRow(tr("At the elevation of the GeoOrigin") if ground is None else tr("On the surface «{name}»", name=ground.name)))
    return tuple(rows)


def _build_road(request: Request, budget_s: float) -> Generator[None, None, tuple[design_draw.Built, Any]]:
    """Los pasos que construyen lo que dibuja la vista previa de una pista (spec 017, T28; RF-017-26): la preparación (``design.preview.road_preview_steps``: solo lee, y con ``RoadAsk.outcome`` solo
    convierte lo que dejó «Calcular»), la superficie de partida sobre la que se dibuja y los lotes —**antes de calcular**, el pasillo de la ruta, la zona de la cota de destino o la línea que sigue, y
    el origen y el destino en cruz; **tras calcular** (o de una pista de la versión), los tramos de la rasante por su estado, el eje fino encima, su flecha, los bordes de la sección y lo que se le apoya—,
    el nombre de cada punto y de cada tramo con su cota y su pendiente, la leyenda y el resumen. Como :func:`_build_platform`: lo que rechazaría «Calcular» (o las máscaras sin compilar) sale en el
    resumen, en lugar del dibujo; sin versión activa, solo lo dice. Cada paso dura como mucho ``budget_s`` s; cerrarlo a mitad no deja nada."""
    project, version_uid, shown = request.project, request.version_uid, request.language
    origin = project.origin
    found = None
    if version_uid:
        steps = design_preview.road_preview_steps(project, request.plan.road, version_uid, budget_s=budget_s)
        found = yield from _run_preview(steps)
    if found is None:
        return _without_version(request)
    ground = None
    batches: list[Batch] = []
    labels: list[Label] = []
    drawn: set[str] = set()
    if found.drawable:
        ground = yield from constraints.ground_steps(project, found.start_surface, version_uid, budget_s=budget_s)
        arm = max(constraints.POINT_ARM_M, POINT_ARM_CELLS * found.cell_m)
        axis = found.axis
        by_status = _stretch_pieces(found)
        crosses = {which: [(point.x, point.y) for point in found.points if point.which == which] for which in ("origin", "destination")}
        pieces: list[tuple[str, constraints.Color, float, list[np.ndarray]]] = [
            (CORRIDOR, CORRIDOR_COLOR, CORRIDOR_PX, [design_draw.ring_segments(found.corridor)]),
            (TARGET, DESTINATION_COLOR, ZONE_PX, [design_draw.ring_segments(found.zone)]),
            (RESTING, RESTING_COLOR, RESTING_PX, [design_draw.ring_segments(item.rings) for item in found.resting if item.rings]),
            (SECTION, SECTION_COLOR, SECTION_PX, [] if found.edges is None else [_axis_segments(edge) for edge in found.edges]),
            (LINE, LINE_COLOR, LINE_PX, [] if found.line is None else [_axis_segments(found.line)]),
            *((key, GRADIENT_COLORS[key], GRADIENT_PX, by_status.get(key, [])) for key in (GRADIENT_WITHIN, GRADIENT_MEAN, GRADIENT_DESIGN)),
            (AXIS, AXIS_COLOR, ROAD_AXIS_PX, [] if axis is None else [_axis_segments(axis)]),
            (ARROW, ARROW_COLOR, AXIS_PX, [] if axis is None else [arrow_segments(axis, _head_m(found.length_m, found.cell_m))]),
            (ORIGIN, ORIGIN_COLOR, POINT_PX, [cross_segments(crosses["origin"], arm)]),
            (DESTINATION, DESTINATION_COLOR, POINT_PX, [cross_segments(crosses["destination"], arm)])]
        for key, color, width, parts in pieces:
            batch = yield from _drape(parts, key, color, width, ground, origin, budget_s)
            if batch is not None:
                batches.append(batch)
                drawn.add(key)
        named: list[tuple[str, tuple[float, float], constraints.Color]] = [
            (_point_text(point), (point.x, point.y), ORIGIN_COLOR if point.which == "origin" else DESTINATION_COLOR) for point in found.points]
        for item in found.stretches:
            middle = axis[(item.first + item.last) // 2]
            named.append((tr("{gradient} % · level {start} → {end} m", gradient=format_number(item.gradient_pct, 1), start=_level(item.start_level_m), end=_level(item.end_level_m)),
                          (float(middle[0]), float(middle[1])), GRADIENT_COLORS[_GRADIENT_KEYS[item.status]]))
        for item in found.resting:
            place = design_draw.ring_center(item.rings)
            if place is not None:
                text = (tr("«{name}» · {volume} m³ rest on it", name=item.name, volume=format_number(item.volume_m3, 0)) if item.volume_m3 is not None
                        else tr("«{name}» starts from its surface", name=item.name))
                named.append((text, place, RESTING_COLOR))
        places = np.array([place for _text, place, _color in named], dtype=np.float64).reshape(-1, 2)
        spots = yield from constraints.drape_points_steps(places, ground, origin, budget_s=budget_s)
        labels.extend(Label(text, (float(x), float(y), float(z)), color) for (text, _place, color), (x, y, z) in zip(named, spots.tolist(), strict=True))
    lines = constraints.Built(version_uid, request.version_code, found.masks.value, "" if ground is None else ground.name, tuple(batches), tuple(labels),
                              _road_legend(request, found, ground, drawn), request.stamp)
    return design_draw.Built(lines, None, (), found.lines(shown)), found


# --- Qué cambió -----------------------------------------------------------------------------------


def stamp(project: Any, version_uid: str | None) -> tuple[Any, ...]:
    """El sello de lo que lee la vista previa para ``version_uid`` (``None``: ninguna): el mismo de la superposición
    de la 012 (``bl.draw.constraints.stamp``: la versión, el estado de sus máscaras y de las búsquedas, las
    operaciones, los datos y los parámetros). Solo lee."""
    return constraints.stamp(project, version_uid)


# --- Activar y quitar -----------------------------------------------------------------------------


class _State:
    """Lo de la sesión (no se guarda en el ``.blend``)."""

    def __init__(self) -> None:
        self.enabled = False
        self.handles: list[Any] = []
        self.built: design_draw.Built | None = None
        self.steps: Generator[None, None, tuple[design_draw.Built, Any]] | None = None
        self.request: Request | None = None
        self.plan: EntityPlan | None = None
        self.preview: Any = None
        self.undo: list[Callable[[], object]] = []
        self.failed = False


_STATE = _State()


def enabled() -> bool:
    """Si la vista previa está activa."""
    return _STATE.enabled


def drawing() -> bool:
    """Si los manejadores de dibujo están puestos."""
    return bool(_STATE.handles)


def building() -> bool:
    """Si quedan pasos por dar para construirla."""
    return _STATE.steps is not None


def built() -> design_draw.Built | None:
    """Lo último construido (se dibuja mientras se rehace); ``None`` si no hay."""
    return _STATE.built


def plan() -> EntityPlan | None:
    """Lo que se previsualiza ahora; ``None`` si no está activa."""
    return _STATE.plan


def preview() -> Any:
    """La última preparación de lo que se previsualiza, en números: ``design.preview.EntityPreview`` (una plataforma),
    ``StockpilePreview`` (las marcas de una detección) o ``ButtressPreview`` (la zona de coronación de un contrafuerte); ``None``
    si no hay."""
    return _STATE.preview


def _fail(what: str) -> None:
    _STATE.failed = True
    LOGGER.exception("No se pueden dibujar %s de la vista previa de la entidad: se apaga", what)


def _draw_view() -> None:
    """El manejador ``POST_VIEW`` de cada Vista 3D: los lotes de líneas."""
    if _STATE.failed or _STATE.built is None:
        return
    try:
        ready = design_draw.region_ready()
        if ready is None:
            return
        _space, region, rv3d = ready
        lines = _STATE.built.lines
        if lines.batches:
            constraints.draw_lines(lines, view_matrix=gpu.matrix.get_model_view_matrix(),
                                   projection_matrix=gpu.matrix.get_projection_matrix(),
                                   perspective=bool(rv3d.is_perspective),
                                   view_distance=float(rv3d.view_distance),
                                   viewport_size=(float(region.width), float(region.height)),
                                   pixel_size=float(bpy.context.preferences.system.pixel_size))
    except Exception:  # una traza por fotograma no ayuda a nadie
        _fail("las líneas")


def _draw_pixels() -> None:
    """El manejador ``POST_PIXEL`` de cada Vista 3D: los nombres, la leyenda y el resumen."""
    if _STATE.failed or _STATE.built is None:
        return
    try:
        ready = design_draw.region_ready()
        if ready is None:
            return
        space, region, rv3d = ready
        context = bpy.context
        scale = float(context.preferences.system.ui_scale)
        size = (float(region.width), float(region.height))
        covered = design_draw.toolbar_covered_px(space, context.area,
                                                 bool(context.preferences.system.use_region_overlap))
        blf.size(dh_overlay.FONT_ID, dh_overlay.FONT_PX * scale)
        items = design_draw.screen_items(_STATE.built, np.array(rv3d.perspective_matrix), size,
                                         measure=design_draw.measure, scale=scale, covered_px=covered)
        if items:
            dh_overlay.paint(items, size, scale=scale)
    except Exception:  # una traza por fotograma no ayuda a nadie
        _fail("el resumen y la leyenda")


def _close_steps() -> None:
    steps, _STATE.steps = _STATE.steps, None
    if steps is not None:
        steps.close()


def rebuild(project: Any = None, version_uid: str | None = None) -> None:
    """Empieza a construir de nuevo lo que dibuja la vista previa para la versión activa (o ``version_uid``) del
    proyecto de la sesión (o ``project``), y deja un temporizador que da los pasos (:func:`tick`); lo anterior se
    sigue dibujando hasta que acabe. Lo que se construía a mitad se cierra. Sin proyecto o sin nada que
    previsualizar, no dibuja nada."""
    project = project or project_session.current()
    _close_steps()
    if project is None or _STATE.plan is None:
        _STATE.built = None
        return
    shown = scene_versions.active()
    uid = version_uid if version_uid is not None else (None if shown is None else shown.uid)
    code = "" if shown is None or shown.uid != uid else shown.code
    try:
        sealed = stamp(project, uid)
    except (GeoblenderError, sqlite3.Error, OSError):
        sealed = ("error",)
    request = Request(project, uid, code, _STATE.plan, language(), sealed)
    _STATE.request = request
    _STATE.steps = _build(request, STEP_BUDGET_S)
    if not bpy.app.timers.is_registered(tick):
        bpy.app.timers.register(tick, first_interval=TICK_INTERVAL_S, persistent=True)


def tick() -> float | None:
    """El temporizador: da pasos de la construcción durante :data:`TICK_BUDGET_S` s como mucho; devuelve cuándo volver
    (``None``: acabó o no hay nada que construir). Al acabar deja el resumen en la vista. Si falla un paso (una
    versión o una entidad que ya no están…), avisa con el motivo y quita la vista previa."""
    steps = _STATE.steps
    if steps is None:
        return None
    started = time.perf_counter()
    try:
        while time.perf_counter() - started < TICK_BUDGET_S:
            next(steps)
    except StopIteration as done:
        if _STATE.steps is steps:
            _STATE.steps = None
            _STATE.built, _STATE.preview = done.value
            design_draw.publish(_STATE.built.summary)
            design_draw.redraw()
        return None
    except Exception as exc:  # noqa: BLE001 - lo dice el aviso y el registro
        LOGGER.warning("No se pudo preparar la vista previa de la entidad", exc_info=True)
        project_session.notify(tr("The preview of the entity could not be prepared: {detail}",
                                  detail=design_draw.error_text(exc)))
        disable()
        return None
    return TICK_INTERVAL_S


def on_version_changed() -> None:
    """Lo que se apunta en ``bl.scene.versions``: con otra versión activa, la rehace."""
    if not _STATE.enabled:
        return
    shown = scene_versions.active()
    request = _STATE.request
    if request is None or request.version_uid != (None if shown is None else shown.uid):
        rebuild()


def on_project_read(project: Any) -> None:
    """Lo que se apunta en los indicadores de la procedencia (``add_change_listener``): si el proyecto cambió en
    algo que lee la vista previa (:func:`stamp`), la rehace."""
    if not _STATE.enabled or project is not project_session.current():
        return
    request = _STATE.request
    try:
        changed = request is None or stamp(project, request.version_uid) != request.stamp
    except (GeoblenderError, sqlite3.Error, OSError):
        return
    if changed:
        rebuild(project)


def on_project_changed(project: Any) -> None:
    """Lo que se apunta en ``bl.scene.project_session``: cerrar el proyecto o abrir otro la quita."""
    request = _STATE.request
    if _STATE.enabled and (project is None or request is None or project is not request.project):
        disable()


def _listen() -> None:
    """Apunta lo que la rehace o la quita y cómo deshacerlo."""
    from ..ui import provenance, switcher  # al usarlo: bl.ui importa bl.draw

    scene_versions.add_listener(on_version_changed)
    provenance.add_change_listener(on_project_read)
    project_session.add_listener(on_project_changed)
    switcher.add_blender_hook(disable)
    _STATE.undo += [
        lambda: scene_versions.remove_listener(on_version_changed),
        lambda: provenance.remove_change_listener(on_project_read),
        lambda: project_session.remove_listener(on_project_changed),
        lambda: switcher.remove_blender_hook(disable),
    ]


def enable(wanted: EntityPlan) -> None:
    """Activa la vista previa de ``wanted`` (la plataforma que se prepara o una entidad de la versión): quita la
    vista previa de semillas y dominios si estaba (comparten el resumen de la vista), pone los manejadores de
    dibujo, apunta lo que la rehace o la quita y empieza a construirla (:func:`rebuild`). Ya activa, la cambia
    por ``wanted`` (:func:`replace`). Sin proyecto abierto, ``RuntimeError``."""
    if _STATE.enabled:
        replace(wanted)
        return
    project = project_session.current()
    if project is None:
        raise RuntimeError("no hay un proyecto abierto: no hay entidad que previsualizar")
    design_draw.disable()  # comparten el resumen de la vista: solo una a la vez
    _STATE.failed = False
    _STATE.enabled = True
    _STATE.plan = wanted
    try:
        space = bpy.types.SpaceView3D
        _STATE.handles = [space.draw_handler_add(_draw_view, (), "WINDOW", "POST_VIEW"),
                          space.draw_handler_add(_draw_pixels, (), "WINDOW", "POST_PIXEL")]
        _listen()
        rebuild(project)
    except BaseException:
        disable()
        raise


def replace(wanted: EntityPlan) -> None:
    """Cambia lo que se previsualiza por ``wanted`` y lo rehace (la orden lo llama al cambiar los campos de su
    diálogo: redibuja con lo nuevo); lo de antes se sigue dibujando hasta que acabe. Sin la vista previa activa,
    nada."""
    if not _STATE.enabled:
        return
    _STATE.plan = wanted
    rebuild()


def disable() -> None:
    """Quita la vista previa: los manejadores de dibujo, los lotes, lo que se construía, lo que la rehacía y su
    resumen de la vista. Ya quitada, nada."""
    was = _STATE.enabled
    _STATE.enabled = False
    _close_steps()
    if bpy.app.timers.is_registered(tick):
        bpy.app.timers.unregister(tick)
    handles, _STATE.handles = _STATE.handles, []
    for handle in handles:
        bpy.types.SpaceView3D.draw_handler_remove(handle, "WINDOW")
    while _STATE.undo:
        try:
            _STATE.undo.pop()()
        except Exception:  # noqa: BLE001 - se sigue quitando lo demás
            LOGGER.debug("No se pudo quitar una escucha de la vista previa de la entidad", exc_info=True)
    _STATE.built = None
    _STATE.request = None
    _STATE.plan = None
    _STATE.preview = None
    if was:
        design_draw.publish(())
        design_draw.redraw()


def register() -> None:
    """Nada que poner: los manejadores solo están mientras la vista previa está activa."""
    _STATE.failed = False


def unregister() -> None:
    """Quita la vista previa si está activa (principio 8)."""
    disable()

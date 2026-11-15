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
from ...design.preview import EntityPreview
from ..scene import project_session
from ..scene import versions as scene_versions
from ..scene.constraint_views import declared_text
from . import constraints, design as design_draw, dh_overlay
from .constraints import Batch, Label
from .dh_overlay import LegendRow

__all__ = [
    "ARROW", "ARROW_COLOR", "AXIS", "AXIS_COLOR", "EntityPlan", "FOOTPRINT", "FOOTPRINT_COLOR", "RESTING",
    "RESTING_COLOR", "Request", "ZONE", "arrow_segments", "build_steps", "building", "built", "disable", "drawing",
    "enable", "enabled", "on_project_changed", "on_project_read", "on_version_changed", "plan", "preview",
    "rebuild", "register", "replace", "stamp", "tick", "unregister",
]

LOGGER = logging.getLogger("geoblender.bl.draw")

FOOTPRINT = "entity_footprint"
AXIS = "entity_axis"
ARROW = "entity_arrow"
RESTING = "entity_resting"
ZONE = "entity_zone"
"""Las claves (y los papeles: todos con ``constraints.OUTLINE``) de los lotes de la vista previa: la huella, el eje, la
flecha de su sentido, lo que se le apoya y la zona que declarará."""

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
FOOTPRINT_PX = 3.0
AXIS_PX = 2.5
RESTING_PX = 2.5
ZONE_PX = constraints.OUTLINE_PX
"""El trazo (px) de cada pieza."""
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
    diálogo de «Plataforma…»: una entidad nueva) o **una que ya está en la versión** (``code``: su código o su
    nombre, con sus parámetros vigentes). Uno de los dos, no los dos. ``insert_before`` (T31; RF-015-05): si la que se
    prepara se **inserta** antes de otra entidad de la versión, el código de esa entidad (la que pasaría a partir de la
    nueva); solo con ``request``."""

    request: Any = None
    code: str | None = None
    insert_before: str | None = None

    def __post_init__(self) -> None:
        if (self.request is None) == (self.code is None):
            raise ValueError("la vista previa de una entidad es de la plataforma que se prepara (su petición) o "
                             "de una entidad de la versión (su código), no de las dos ni de ninguna")
        if self.insert_before is not None and self.request is None:
            raise ValueError("una inserción se previsualiza con la plataforma que se prepara (su petición), no con una "
                             "entidad que ya está en la versión")


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


def _build(request: Request, budget_s: float
           ) -> Generator[None, None, tuple[design_draw.Built, EntityPreview | None]]:
    """Los pasos que construyen lo que dibuja la vista previa para ``request`` (véase el módulo): la preparación de la
    entidad (``design.preview.entity_preview_steps``: solo lee y no compila las máscaras), la superficie sobre la que
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
        try:
            for step in steps:
                if step.result is not None:
                    found = step.result
                yield
        finally:
            close = getattr(steps, "close", None)
            if close is not None:
                close()
    if found is None:  # sin versión: lo dice, no hay nada que dibujar
        lines = constraints.Built(version_uid, request.version_code, "", "", (), (),
                                  (LegendRow(tr("Preview of an entity")),
                                   LegendRow(tr("No active version: nothing to preview"))), request.stamp)
        notice = tr("There is no active version: the preview of an entity needs one")
        return design_draw.Built(lines, None, (), ((notice, True),)), None
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
        self.steps: Generator[None, None, tuple[design_draw.Built, EntityPreview | None]] | None = None
        self.request: Request | None = None
        self.plan: EntityPlan | None = None
        self.preview: EntityPreview | None = None
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


def preview() -> EntityPreview | None:
    """La última preparación de la entidad (``design.preview.EntityPreview``: lo que se dibuja, en números); ``None``
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

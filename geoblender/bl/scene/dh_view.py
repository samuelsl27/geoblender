# SPDX-License-Identifier: GPL-3.0-or-later
"""La vista de los sondeos: el cargador de sus trazas (spec 005, T24 y T29; RF-005-22,
RF-005-23, RF-005-24; RF-006-29; plan 005 §5.1, §5.4 «Vista» y §5.6.8; D9 del plan; ADR-0005).

:func:`register` registra en ``bl.scene.views`` el cargador de las trazas de los sondeos, por
el comienzo del nombre de su dato (:data:`PREFIX`, ``dh_trace``), con objetos del tipo
``DRILLHOLES`` en la rama «Sondeos» de la colección del proyecto; :func:`unregister` lo quita
(el de otro con el mismo comienzo, no). Los dos son idempotentes.

**Cargar** (:func:`load_traces`) va en pasos de décimas de segundo como mucho: desde «Cargar en
la vista…» (con su avance y Esc) y, tras calcular las trazas, desde la cola de incorporación de
los sondeos (``bl.ops.dh.start_view``: la vista se recarga sola, plan §5.6.8):

1. lee del proyecto, por pasos, lo que dice la desviación que escribió ``dh_trace``
   (``drillholes.store.trace_view``: su método, sus parámetros, sus sondeos y los de traza
   obsoleta) y la base que necesita la vista (las bocas, las desviaciones, la litología, los
   análisis y los catálogos; ``drillholes.store.read_steps``);
2. lanza el trabajo ``dh_view_arrays`` (``bl.ops.core_provenance.submit_job``: no es de
   ninguna operación, porque la vista no escribe en el proyecto) con la base en ``in/`` (una
   parte por tabla), la representación de la escena (``Scene.geoblender_dh_display``: el
   esquema de logueo, el elemento con su leyenda, que es la de sus clases si la representación
   las tiene, RF-005-24, y si no la de por defecto, y la separación y el ancho de las barras) y
   los sondeos con traza («cada sondeo calculado», RF-005-23), y espera a que acabe sondeando
   el lanzador (en ``blender -b`` no corren los temporizadores);
3. con sus arrays (``drillholes.jobs.read_view``, absolutos en float64) crea **los tubos**:
   unas curvas ``POLY`` (``bl.scene.mesh.curves_steps``, en locales respecto al GeoOrigin), una
   por tramo del esquema y por hueco, con los atributos :data:`COLOR` (de punto: el color
   lineal de su litología; gris en los huecos), :data:`HOLE` y :data:`ROW` (de curva: la
   posición de la boca en la base y la fila del tramo, −1 en un hueco) y :data:`STALE` (de
   curva: su sondeo tiene la traza obsoleta, RF-005-22), con el modificador de
   ``GB_DrillTubes`` (``bl.gn.drill_tubes``) y el radio de la representación; y **las barras**
   del elemento: una malla de cuadriláteros con, por cara, :data:`COLOR` (el color de su
   clase), :data:`CLASS` (su entrada en la leyenda), :data:`HOLE`, :data:`ROW` y
   :data:`STALE`, y el material de la vista.

Devuelve los objetos sin enlazar y con matriz identidad (``bl.scene.views`` les pone
``Object.geoblender`` y los lleva a la colección del dato en «Sondeos»), su extensión local y
sus avisos (un elemento que no está en el catálogo o es de texto; valores en otra unidad que
la de la leyenda). Cerrar los pasos antes de terminar (Esc) cancela el trabajo, borra lo creado
y deja la vista como estaba; si el trabajo no termina bien, ``dh.view_failed`` con su motivo.

**Lo que no se pinta y la superposición** (T30; RF-005-17, RF-005-22, RF-005-25; plan §5.6.8):
el trabajo recibe en ``excluded`` lo que excluye la validación guardada en el proyecto (sus
errores de alcance T y R, ``drillholes.validate.stored_exclusions``: esa litología o ese
elemento de ese sondeo no se pinta); las etiquetas siempre con las del fondo (la
superposición enseña las que pide la representación sin recargar). Lo que dibuja
``bl.draw.dh_overlay`` de una vista (:class:`Overlay`, :func:`build_overlay`: las etiquetas en
locales, las leyendas y las marcas de la boca, un aspa con los códigos de alcance S de un
sondeo sin traza, los de alcance T de la validación guardada y la traza obsoleta) se queda en
la memoria del módulo con sus objetos (:func:`remember`, :func:`overlay_of`): no va al
``.blend`` ni al proyecto, y se rehace al cargar otra vez. :func:`display_key` es la
representación con que se cargó (:func:`up_to_date`); :func:`apply_radius` cambia en vivo el
radio de los tubos y :func:`fill_classes`, las clases propias desde la leyenda de la vista.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Generator, Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import bpy
import numpy as np

from ...core.errors import GeoblenderError, ValidationError
from ...core.georef import GeoOrigin, world_to_local
from ...core.i18n import format_number, language, tr, translate
from ...core.numbers import parse_decimal
from ...drillholes import jobs, store, validate
from ...drillholes.arrays import tables_arrays
from ...drillholes.model import DrillholeSet, name_key
from ...drillholes.params import DEPTH_TOLERANCE, TRACE_STEP
from ...drillholes.provenance import MODULE
from ...drillholes.schema import LAYOUTS
from ...drillholes.view_data import DEFAULT_RAMP, TEXT_UNIT, GradeLegend, LegendEntry
from ...gis import jobs as gis_jobs
from ...jobs.ingest import job_outcome
from ..gn import drill_tubes
from ..props.core import OBJECT_PROPERTY
from ..props.dh import LOG_SET, SCENE_PROPERTY
from . import views

LOGGER = logging.getLogger("geoblender.bl.scene")
from .mesh import (
    curves_positions_local,
    curves_steps,
    mesh_steps,
    mesh_vertices_local,
    set_attribute,
)

PREFIX = LAYOUTS["dh_trace"].name
"""El comienzo del nombre del dato que se carga: las trazas de los sondeos (``dh_trace``)."""
KIND = "DRILLHOLES"
"""El tipo de sus objetos (``Object.geoblender.kind``)."""
LABEL = "Drillholes"
"""El ``msgid`` de ese tipo en el nombre generado de sus objetos."""
NOT_DELIVERED = "dh.not_delivered"
"""El código del error de lo que aún no está disponible de los sondeos (spec 005)."""
VIEW_FAILED = "dh.view_failed"
"""El código del error de una vista de los sondeos que no se pudo cargar."""
JOB_LABEL = "View arrays of the drillholes"
"""El nombre visible (``msgid``) del trabajo de la vista."""
COLOR = drill_tubes.COLOR_ATTRIBUTE
"""El atributo del color lineal (de punto en los tubos; de cara en las barras)."""
HOLE = "gb_hole"
"""El atributo con la posición en la base de la boca (de curva en los tubos; de cara)."""
ROW = "gb_row"
"""El atributo con la fila del tramo de litología o del análisis (−1 en un hueco)."""
STALE = "gb_stale"
"""El atributo que marca los sondeos de traza obsoleta (RF-005-22)."""
CLASS = "gb_class"
"""El atributo de cara de las barras con su entrada en la leyenda de clases."""
READ_PARTS: tuple[str, ...] = ("dh_survey", "dh_lithology", "dh_assay")
"""Lo que se lee de la base además de las bocas y los catálogos."""
SENT_TABLES: tuple[str, ...] = ("collars", "surveys", "lithology", "assays")
"""Las tablas del ``DrillholeSet`` que van al trabajo (una parte de ``in/`` cada una)."""
WAIT_S = 0.005
"""Lo que espera cada paso mientras el trabajo no acaba (s): pasos cortos, sin gastar CPU."""
_SUCCEEDED = "succeeded"
_OBJ = "Sondeos en la vista"
_DEFAULT_DISPLAY = SimpleNamespace(log_set=LOG_SET, tube_radius=drill_tubes.DEFAULT_RADIUS_M,
                                   element="", grade_classes=(), bar_width=2.0,
                                   bar_offset=1.0, labels_at_end=False)


def _text(msgid: str) -> str:
    return translate(language(), msgid)


def _display() -> Any:
    """La representación de los sondeos de la escena (``Scene.geoblender_dh_display``); sin
    ella, la de por defecto."""
    scene = getattr(bpy.context, "scene", None)
    found = None if scene is None else getattr(scene, SCENE_PROPERTY, None)
    return _DEFAULT_DISPLAY if found is None else found


def _span(steps: Generator[float, None, Any], low: float,
          high: float) -> Generator[float, None, Any]:
    """Los avances (0–1) de unos pasos llevados al tramo [``low``, ``high``], y lo que
    devuelven."""
    try:
        while True:
            try:
                done = next(steps)
            except StopIteration as stop:
                return stop.value
            yield low + (high - low) * min(max(float(done), 0.0), 1.0)
    finally:
        steps.close()


# --- La leyenda y la petición ---------------------------------------------------------------


def _hex(color: Any) -> str:
    """Un color de la representación (sRGB, 0–1) como «#RRGGBB»."""
    return "#" + "".join(f"{round(min(max(float(value), 0.0), 1.0) * 255):02X}"
                         for value in tuple(color)[:3])


def grade_legend(display: Any, element: str, unit: str) -> GradeLegend | None:
    """La leyenda de las barras de ``element`` en ``unit`` con las clases de la representación
    ``display`` (RF-005-24, editable: cada clase, desde dónde empieza, escrito con coma o
    punto, y su color; la primera, desde el valor más bajo); sin clases, ``None`` (la de por
    defecto). ``ValidationError`` con la clase que no vale."""
    classes = list(display.grade_classes)
    if not classes:
        return None
    where = f"Leyenda de «{element}»"
    breaks = [parse_decimal(item.lower, obj=where, field=f"clase {number}")
              for number, item in enumerate(classes[1:], start=2)]
    try:
        return GradeLegend(unit, tuple(breaks), tuple(_hex(item.color) for item in classes))
    except ValueError as error:
        raise ValidationError("dh.legend_invalid", str(error), obj=where, field="clases",
                              value=" · ".join(item.lower for item in classes)) from None


def _excluded(records: Sequence[Mapping[str, Any]], count: int) -> dict[str, list[Any]]:
    """Lo que excluye la validación guardada (``records``, las filas de
    ``dh_validation_issue``) para ``excluded`` del trabajo: sus tablas (alcance T) y sus
    registros (R). Si no es de esta base (apunta a otras bocas), nada (queda en el registro
    técnico)."""
    try:
        found = validate.stored_exclusions(records, count)
    except ValueError:
        LOGGER.info("La validación guardada no es de la base de los sondeos de ahora: la vista "
                    "no la usa", exc_info=True)
        return {}
    return {"tables": [[hole, table, key] for hole, table, key in
                       sorted(found.tables, key=lambda item: (item[0], item[1], item[2] or ""))],
            "records": [[table, row] for table, row in sorted(found.records)]}


def _job_params(dset: Any, source: store.TraceView, display: Any,
                records: Sequence[Mapping[str, Any]] = ()) -> tuple[dict[str, Any], list[str]]:
    """Los parámetros de ``dh_view_arrays`` (la desviación de ``source``, la representación
    ``display`` y lo que excluye la validación guardada ``records``) y los avisos de lo que no
    se dibuja. Las etiquetas, siempre con las del fondo (T30: la superposición enseña las que
    pide la representación)."""
    rows = sum(len(getattr(dset, table)) for table in SENT_TABLES)
    params: dict[str, Any] = {
        "crs": gis_jobs.crs_json(dset.crs), "vertical": gis_jobs.vertical_json(dset.vertical),
        "method": source.method, "depth_tolerance_m": source.params[DEPTH_TOLERANCE],
        "max_step_m": source.params[TRACE_STEP],
        "log_set": display.log_set.strip() or LOG_SET,
        "labels_at_end": True, "holes": list(source.holes),
        "excluded": _excluded(records, len(dset.collars)), "count": rows + 1,
    }
    notes: list[str] = []
    typed = display.element.strip()
    if not typed:
        return params, notes
    found = next((item for item in dset.catalogs.elements
                  if name_key(item.code) == name_key(typed)), None)
    if found is None:
        notes.append(tr("«{element}» is not an element of the drillhole catalog: it has no "
                        "grade bars", element=typed))
    elif name_key(found.unit) == TEXT_UNIT:
        notes.append(tr("«{element}» is a text element: it has no grade bars",
                        element=found.code))
    else:
        params.update(element=found.code, offset_m=float(display.bar_offset),
                      width_m=float(display.bar_width))
        legend = grade_legend(display, found.code, found.unit)
        if legend is None:
            params["unit"] = found.unit
        else:
            params["legend"] = {"unit": legend.unit, "breaks": list(legend.breaks),
                                "colors": list(legend.colors),
                                "below_dl_color": legend.below_dl_color}
    return params, notes


def _base_arrays(dset: Any) -> Generator[float, None, dict[str, np.ndarray]]:
    """La base de la vista para ``in/`` (``drillholes.jobs.packed_arrays``): una parte por
    tabla y una con los catálogos, una por paso."""
    found: dict[str, np.ndarray] = {}
    for index, table in enumerate(SENT_TABLES, start=1):
        found.update(jobs.packed_arrays(jobs.INPUT_BASE, table,
                                        tables_arrays({table: getattr(dset, table)})))
        yield index / (len(SENT_TABLES) + 1)
    found.update(jobs.packed_arrays(jobs.INPUT_BASE, "catalogs",
                                    tables_arrays({}, dset.catalogs)))
    return found


def _wait(handle: Any, poll: Callable[[], object], low: float,
          high: float) -> Generator[float, None, Any]:
    """Los pasos mientras el trabajo ``handle`` no acaba (``poll`` sondea el lanzador), con su
    avance en [``low``, ``high``]; devuelve su ``JobResult``."""
    while True:
        result = handle.result()
        if result is None:
            poll()
            result = handle.result()
        if result is not None:
            return result
        time.sleep(WAIT_S)
        yield low + (high - low) * min(max(float(handle.frac), 0.0), 1.0)


# --- Los objetos --------------------------------------------------------------------------------


def _tubes(name: str, curves: Any, stale: np.ndarray, radius_m: float, origin: Any,
           created: list[Any]) -> Generator[float, None, bpy.types.Object]:
    """Los pasos del objeto de los tubos (véase el módulo); lo que crea, en ``created``."""
    data = yield from curves_steps(name, curves.points_abs, curves.curve_sizes, origin=origin)
    created.append(data)
    set_attribute(data, COLOR, "POINT", "FLOAT_COLOR", curves.color_linear)
    set_attribute(data, HOLE, "CURVE", "INT", curves.hole)
    set_attribute(data, ROW, "CURVE", "INT", curves.row)
    set_attribute(data, STALE, "CURVE", "BOOLEAN", stale[curves.hole])
    yield 1.0
    obj = bpy.data.objects.new(name, data)
    created.insert(0, obj)
    drill_tubes.add_tubes(obj, radius_m)
    return obj


def _bars(name: str, bars: Any, stale: np.ndarray, origin: Any,
          created: list[Any]) -> Generator[float, None, bpy.types.Object]:
    """Los pasos del objeto de las barras (véase el módulo); lo que crea, en ``created``."""
    mesh = yield from mesh_steps(name, bars.vertices_abs, bars.faces, origin=origin)
    created.append(mesh)
    set_attribute(mesh, COLOR, "FACE", "FLOAT_COLOR", bars.color_linear)
    set_attribute(mesh, CLASS, "FACE", "INT", bars.grade_class)
    set_attribute(mesh, HOLE, "FACE", "INT", bars.hole)
    set_attribute(mesh, ROW, "FACE", "INT", bars.row)
    set_attribute(mesh, STALE, "FACE", "BOOLEAN", stale[bars.hole])
    mesh.materials.append(drill_tubes.ensure_material())
    yield 1.0
    obj = bpy.data.objects.new(name, mesh)
    created.insert(0, obj)
    return obj


def _remove(created: list[Any]) -> None:
    """Borra lo que creó una carga que no terminó: los objetos y, después, sus datos."""
    for item in created:
        if isinstance(item, bpy.types.Object):
            bpy.data.objects.remove(item)
        elif isinstance(item, bpy.types.Curves):
            bpy.data.hair_curves.remove(item)
        elif isinstance(item, bpy.types.Mesh):
            bpy.data.meshes.remove(item)
    created.clear()


def _bounds(objects: list[bpy.types.Object]) -> tuple[np.ndarray, np.ndarray] | None:
    """Los mínimos y máximos locales de los puntos de los tubos y de las barras, tal como los
    guarda Blender."""
    points = [curves_positions_local(obj.data) if isinstance(obj.data, bpy.types.Curves)
              else mesh_vertices_local(obj.data) for obj in objects]
    points = [item for item in points if len(item)]
    if not points:
        return None
    joined = np.vstack(points)
    return joined.min(axis=0).astype(np.float64), joined.max(axis=0).astype(np.float64)


# --- El cargador -------------------------------------------------------------------------------


def load_traces(request: views.ViewRequest) -> Generator[float, None, views.ViewParts]:
    """Las trazas de los sondeos en la vista (``bl.scene.views.ViewLoader``, en pasos; véase
    el módulo)."""
    from ..ops import core_provenance  # bl/ops importa bl/scene: al usarlo
    from ..ops import jobs as jobs_ops

    project = request.project
    display = _display()
    with project.read() as conn:
        source = store.trace_view(conn)
        if source is None:
            raise GeoblenderError(VIEW_FAILED, "el proyecto no tiene las trazas de los "
                                  "sondeos: calcúlelas antes", obj=_OBJ, field="dato",
                                  value=request.record.name)
        dset = yield from _span(store.read_steps(conn, parts=READ_PARTS), 0.0, 0.2)
        stored = store.stored_validation(conn)
    records = () if stored is None else stored.records
    params, notes = _job_params(dset, source, display, records)
    arrays = yield from _span(_base_arrays(dset), 0.2, 0.3)
    abandoned: list[bool] = []

    def finished(result: Any) -> None:
        if abandoned:  # la carga se cerró antes: nadie lee sus resultados
            core_provenance.release_job(result.job_uid)

    try:
        handle = core_provenance.submit_job(
            jobs.VIEW_ARRAYS, label=_text(JOB_LABEL), owner=MODULE, params=params,
            arrays=arrays, on_finish=finished, project_uid=project.uid,
            grace_s=jobs.CANCEL_GRACE_S)
    except RuntimeError as error:
        raise GeoblenderError(VIEW_FAILED, str(error), obj=_OBJ, field="trabajo",
                              value=jobs.VIEW_ARRAYS) from None
    created: list[Any] = []
    try:
        result = yield from _wait(handle, jobs_ops.MONITOR.tick, 0.3, 0.7)
        try:
            if result.state != _SUCCEEDED:
                reason = result.error_text or result.state
                raise GeoblenderError(VIEW_FAILED, f"no se calculó ({reason})", obj=_OBJ,
                                      field="trabajo", value=jobs.VIEW_ARRAYS)
            view = jobs.read_view(job_outcome(result, result.job_dir).file(jobs.OUT_VIEW.role))
        finally:
            core_provenance.release_job(result.job_uid)
        yield 0.75
        wanted = set(source.stale)
        stale = np.array([name in wanted for name in dset.collars.name.tolist()],
                         dtype=np.bool_)
        objects: list[bpy.types.Object] = []
        curves, bars = view.curves, view.bars
        if curves is not None and len(curves.curve_sizes):
            objects.append((yield from _span(_tubes(request.name, curves, stale,
                                                    float(display.tube_radius),
                                                    request.origin, created), 0.75, 0.88)))
        if bars is not None and len(bars.faces):
            element = params.get("element", "")
            objects.append((yield from _span(_bars(f"{request.name} · {element}", bars, stale,
                                                   request.origin, created), 0.88, 0.98)))
        if bars is not None and bars.skipped_units:
            notes.append(tr("{count} values of «{element}» are not in «{unit}»: they have no "
                            "bar (DH-W07)", count=format_number(int(bars.skipped_units), 0),
                            element=params["element"], unit=view.grade_legend.unit))
        remember(objects, build_overlay(
            dset, view, origin=request.origin, stale=source.stale, records=records,
            depth_tolerance_m=source.params[DEPTH_TOLERANCE], log_set=params["log_set"],
            element=params.get("element", ""), display_key=display_key(display)))
        return views.ViewParts(tuple(objects), _bounds(objects), tuple(notes))
    except BaseException:
        abandoned.append(True)
        if handle.result() is None:
            handle.cancel()
        _remove(created)
        raise


# --- Lo que dibuja la superposición (T30) ---------------------------------------------------

MARK_EXCLUDED = "excluded"
"""La marca de un sondeo sin traza por sus errores de alcance S (RF-005-17): aspa y códigos."""
MARK_PARTIAL = "partial"
"""La de un sondeo con traza y errores de alcance T en la validación guardada: sus códigos."""
MARK_STALE = "stale"
"""La de un sondeo de traza obsoleta (RF-005-22)."""


@dataclass(frozen=True)
class ViewLabel:
    """Una etiqueta de la vista (RF-005-25): su texto, su posición LOCAL (respecto al GeoOrigin,
    float64) y si es la del fondo."""

    text: str
    xyz: tuple[float, float, float]
    bottom: bool = False


@dataclass(frozen=True)
class Mark:
    """Una marca en la boca de un sondeo (RF-005-17, RF-005-22): el sondeo, su clase
    (:data:`MARK_EXCLUDED`, :data:`MARK_PARTIAL` o :data:`MARK_STALE`), sus códigos y la
    posición LOCAL de su boca."""

    hole: str
    kind: str
    codes: tuple[str, ...]
    xyz: tuple[float, float, float]


@dataclass(frozen=True, eq=False)
class Overlay:
    """Lo que dibuja la superposición de una vista de los sondeos: sus etiquetas y sus marcas
    (en locales), el esquema de logueo y la leyenda de su litología, el elemento y la leyenda
    de sus barras (``None`` sin barras), los esquemas y los elementos de ley del catálogo
    (código y unidad: los campos de la Leyenda genérica) y la representación con que se
    cargó (:func:`display_key`)."""

    labels: tuple[ViewLabel, ...]
    marks: tuple[Mark, ...]
    log_set: str
    lithology: tuple[LegendEntry, ...]
    element: str
    grade: GradeLegend | None
    log_sets: tuple[str, ...]
    elements: tuple[tuple[str, str], ...]
    display_key: tuple[Any, ...] = ()


def _local(points: Sequence[Sequence[float]], origin: GeoOrigin) -> list[tuple[float, ...]]:
    """Unas posiciones absolutas (float64) en locales, como tuplas."""
    found = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    return [tuple(row) for row in world_to_local(found, origin).tolist()] if len(found) else []


def build_overlay(dset: DrillholeSet, view: jobs.ViewArrays, *, origin: GeoOrigin,
                  stale: Iterable[str], records: Sequence[Mapping[str, Any]],
                  depth_tolerance_m: float, log_set: str, element: str,
                  display_key: tuple[Any, ...] = ()) -> Overlay:
    """Lo que dibuja la superposición de la vista ``view`` de la base ``dset`` (T30; véase el
    módulo): sus etiquetas en locales respecto a ``origin``; en la boca de cada sondeo con X,
    Y y Z, el aspa con los códigos de sus errores de alcance S (sin traza,
    ``drillholes.validate.exclusion_codes`` con ``depth_tolerance_m``) o, si tiene traza, los
    de alcance T de la validación guardada ``records``, y la marca de los de traza obsoleta
    ``stale`` (sus nombres); las leyendas de la vista, el esquema ``log_set`` y el elemento
    ``element`` ("" sin barras)."""
    collars = dset.collars
    names = collars.name.tolist()
    xyz = np.column_stack((collars.x, collars.y, collars.z))
    placed = np.flatnonzero(np.isfinite(xyz).all(axis=1)).tolist()
    local = dict(zip(placed, _local(xyz[placed], origin), strict=True))
    codes = validate.exclusion_codes(dset, depth_tolerance_m=depth_tolerance_m)
    try:
        partial = validate.stored_codes(records, validate.Scope.TABLE)
    except ValueError:
        partial = {}
    wanted = set(stale)
    marks: list[Mark] = []
    for k in placed:
        where = local[k]
        if codes[k]:
            marks.append(Mark(names[k], MARK_EXCLUDED, codes[k], where))
        elif k in partial:
            marks.append(Mark(names[k], MARK_PARTIAL, partial[k], where))
        if names[k] in wanted:
            marks.append(Mark(names[k], MARK_STALE, (), where))
    labels = tuple(ViewLabel(label.text, where, bool(label.bottom)) for label, where in zip(
        view.labels, _local([label.xyz for label in view.labels], origin), strict=True))
    log_sets: dict[str, str] = {name_key(log_set): log_set}
    for entry in dset.catalogs.lithology:
        log_sets.setdefault(name_key(entry.log_set), entry.log_set)
    elements = tuple((item.code, item.unit) for item in dset.catalogs.elements
                     if name_key(item.unit) != TEXT_UNIT)
    grade = view.grade_legend
    return Overlay(labels, tuple(marks), log_set, tuple(view.lithology_legend),
                   element if grade is not None else "", grade, tuple(log_sets.values()),
                   elements, tuple(display_key))


_OVERLAYS: dict[int, Overlay] = {}
"""Lo que dibuja la superposición, por el ``session_uid`` de cada objeto de la vista: vive
con los objetos en esta sesión (no se guarda)."""


def remember(objects: Iterable[bpy.types.Object], overlay: Overlay) -> None:
    """Lo que dibuja la superposición de ``objects`` (los de una vista); olvida lo de los
    objetos que ya no existen."""
    alive = {obj.session_uid for obj in bpy.data.objects}
    for key in [key for key in _OVERLAYS if key not in alive]:
        del _OVERLAYS[key]
    for obj in objects:
        _OVERLAYS[obj.session_uid] = overlay


def overlay_of(obj: Any) -> Overlay | None:
    """Lo que dibuja la superposición del objeto ``obj`` de una vista de los sondeos, o
    ``None`` (no es de una vista cargada en esta sesión, o se cargó antes de abrir el
    fichero)."""
    try:
        key = obj.session_uid
    except (AttributeError, ReferenceError):
        return None
    return _OVERLAYS.get(key)


def forget_overlays() -> None:
    """Olvida lo de todas las vistas (al desregistrar)."""
    _OVERLAYS.clear()


def display_key(display: Any) -> tuple[Any, ...]:
    """Lo que de la representación ``display`` cambia los objetos de la vista (el esquema, el
    elemento, sus clases y las barras; no el radio, las etiquetas ni la leyenda)."""
    return (display.log_set.strip() or LOG_SET, display.element.strip(),
            tuple((item.lower.strip(), _hex(item.color)) for item in display.grade_classes),
            round(float(display.bar_width), 6), round(float(display.bar_offset), 6))


def loaded_objects(project: Any) -> list[bpy.types.Object]:
    """Los objetos de la vista de los sondeos del proyecto ``project`` en el fichero."""
    uid = getattr(project, "uid", None)
    return [obj for obj in bpy.data.objects
            if getattr(obj, OBJECT_PROPERTY).kind == KIND
            and getattr(obj, OBJECT_PROPERTY).project_uid == uid]


def up_to_date(project: Any, display: Any) -> bool:
    """Si la vista de los sondeos de ``project`` es ya la de la representación ``display``
    (todos sus objetos cargados en esta sesión con ella; sin ninguno, también)."""
    key = display_key(display)
    found = (overlay_of(obj) for obj in loaded_objects(project))
    return all(item is not None and item.display_key == key for item in found)


def apply_radius(radius_m: float) -> int:
    """El radio ``radius_m`` (m) en los tubos de todas las vistas de los sondeos, en vivo
    (``bl.gn.drill_tubes.set_tube_radius``: sin recargar nada); devuelve cuántos cambió."""
    changed = 0
    for obj in bpy.data.objects:
        if getattr(obj, OBJECT_PROPERTY).kind == KIND and drill_tubes.tube_radius(obj) is not None:
            drill_tubes.set_tube_radius(obj, radius_m)
            changed += 1
    return changed


def _srgb(color: str) -> tuple[float, float, float]:
    """«#RRGGBB» en sRGB (0–1), como lo guarda la representación."""
    return tuple(int(color[i:i + 2], 16) / 255.0 for i in (1, 3, 5))  # type: ignore[return-value]


def _break_text(value: float) -> str:
    """Un corte de una leyenda como se escribe en la representación (su decimal más corto,
    con la coma del español)."""
    text = np.format_float_positional(float(value), unique=True, trim="-")
    return text if language() == "en" else text.replace(".", ",")


def fill_classes(display: Any) -> int:
    """Las clases propias de la representación ``display`` desde la leyenda de las barras del
    mismo elemento de una vista cargada en esta sesión (sus cortes y sus colores); sin ninguna,
    una clase con todos los valores. Sustituye las que tuviera; devuelve cuántas pone."""
    wanted = name_key(display.element)
    legend = next((item.grade for item in (overlay_of(obj) for obj in bpy.data.objects)
                   if item is not None and item.grade is not None
                   and name_key(item.element) == wanted), None)
    breaks = () if legend is None else legend.breaks
    colors = (DEFAULT_RAMP[0],) if legend is None else legend.colors
    display.grade_classes.clear()
    for index, color in enumerate(colors):
        item = display.grade_classes.add()
        item.lower = "" if index == 0 else _break_text(breaks[index - 1])
        item.color = _srgb(color)
    return len(colors)


def register() -> None:
    """Registra el cargador de las trazas si no hay otro para su comienzo; idempotente."""
    if PREFIX not in views.loaders():
        views.register_loader(PREFIX, KIND, LABEL, load_traces)


def unregister() -> None:
    """Quita el cargador de las trazas si es el suyo (el de otro, no) y olvida lo que dibuja
    la superposición; idempotente."""
    forget_overlays()
    found = views.loaders().get(PREFIX)
    if found is not None and found.load is load_traces:
        views.unregister_loader(PREFIX)


__all__ = ["CLASS", "COLOR", "HOLE", "JOB_LABEL", "KIND", "LABEL", "MARK_EXCLUDED",
           "MARK_PARTIAL", "MARK_STALE", "NOT_DELIVERED", "PREFIX", "ROW", "STALE",
           "VIEW_FAILED", "Mark", "Overlay", "ViewLabel", "apply_radius", "build_overlay",
           "display_key", "fill_classes", "forget_overlays", "grade_legend", "load_traces",
           "loaded_objects", "overlay_of", "register", "remember", "unregister", "up_to_date"]

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
"""

from __future__ import annotations

import time
from collections.abc import Callable, Generator
from types import SimpleNamespace
from typing import Any

import bpy
import numpy as np

from ...core.errors import GeoblenderError, ValidationError
from ...core.i18n import format_number, language, tr, translate
from ...core.numbers import parse_decimal
from ...drillholes import jobs, store
from ...drillholes.arrays import tables_arrays
from ...drillholes.model import name_key
from ...drillholes.params import DEPTH_TOLERANCE, TRACE_STEP
from ...drillholes.provenance import MODULE
from ...drillholes.schema import LAYOUTS
from ...drillholes.view_data import TEXT_UNIT, GradeLegend
from ...gis import jobs as gis_jobs
from ...jobs.ingest import job_outcome
from ..gn import drill_tubes
from ..props.dh import LOG_SET, SCENE_PROPERTY
from . import views
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


def _job_params(dset: Any, source: store.TraceView,
                display: Any) -> tuple[dict[str, Any], list[str]]:
    """Los parámetros de ``dh_view_arrays`` (la desviación de ``source`` y la representación
    ``display``) y los avisos de lo que no se dibuja."""
    rows = sum(len(getattr(dset, table)) for table in SENT_TABLES)
    params: dict[str, Any] = {
        "crs": gis_jobs.crs_json(dset.crs), "vertical": gis_jobs.vertical_json(dset.vertical),
        "method": source.method, "depth_tolerance_m": source.params[DEPTH_TOLERANCE],
        "max_step_m": source.params[TRACE_STEP],
        "log_set": display.log_set.strip() or LOG_SET,
        "labels_at_end": bool(display.labels_at_end), "holes": list(source.holes),
        "count": rows + 1,
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
    params, notes = _job_params(dset, source, display)
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
        return views.ViewParts(tuple(objects), _bounds(objects), tuple(notes))
    except BaseException:
        abandoned.append(True)
        if handle.result() is None:
            handle.cancel()
        _remove(created)
        raise


def register() -> None:
    """Registra el cargador de las trazas si no hay otro para su comienzo; idempotente."""
    if PREFIX not in views.loaders():
        views.register_loader(PREFIX, KIND, LABEL, load_traces)


def unregister() -> None:
    """Quita el cargador de las trazas si es el suyo (el de otro, no); idempotente."""
    found = views.loaders().get(PREFIX)
    if found is not None and found.load is load_traces:
        views.unregister_loader(PREFIX)


__all__ = ["CLASS", "COLOR", "HOLE", "JOB_LABEL", "KIND", "LABEL", "NOT_DELIVERED", "PREFIX",
           "ROW", "STALE", "VIEW_FAILED", "grade_legend", "load_traces", "register",
           "unregister"]

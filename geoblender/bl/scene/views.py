# SPDX-License-Identifier: GPL-3.0-or-later
"""Los datos del proyecto en la vista de Blender (spec 006, T27; RF-006-19, RF-006-20,
RF-006-29; plan 006 §5.1, §5.5 y §5.6.7; D12, D16; ADR-0005).

Un mecanismo general (D-10 de la spec): cada módulo registra el **cargador** de sus datos por el
comienzo de su nombre en ``gb_dataset`` (:func:`register_loader`: ``gis_dtm_`` → la rejilla de
la 006; la 005 y las siguientes, los suyos), y una sola orden, «Cargar en la vista…», los carga
todos (:func:`load_steps`, en pasos, desde el temporizador de su ventana con su avance y Esc;
:func:`load_datasets`, de una vez, desde un guion; T50, RNF-006-09). Un cargador recibe el dato
(:class:`ViewRequest`) y devuelve sus objetos sin enlazar, en coordenadas **locales** respecto
al GeoOrigin y con matriz identidad (``bl.scene.mesh``), y su extensión local
(:class:`ViewParts`), o un generador que da su avance tras cada paso y los devuelve al final
(los de la topografía: la rejilla de 2,81 M celdas en pasos de unas décimas de segundo como
mucho); lo demás es de aquí:

- **lo que dice el proyecto del dato** (``core.provenance.view``, sin escribir nada): se cargan
  los vigentes, los bloqueados y los dañados, con su estado a la vista; de uno que falta se
  avisa y no se carga (plan §5.6.7); cargar uno ya cargado lo sustituye (otro nivel de detalle,
  o el dato al día), en el último paso: si se cancela antes, la vista queda como estaba;
- **``Object.geoblender``** en cada objeto (RF-006-29): su tipo, el uid de su dato y de su
  proyecto, su hash de contenido, su estado, la fecha de la operación que escribió su
  contenido y si estaba obsoleto (la caché de la 008); nombre **generado** con su tipo, su
  nombre corto y su estado («MDT mdt_norte [VIGENTE]», «… [VIGENTE · OBSOLETO]»), sin cifras;
- **colecciones tipadas** (:func:`ensure_collection`; plan §5.5): la de su rama («Datos base /
  Topografía»; el ancla, «Proyecto»; los sondeos, «Sondeos») y una por dato, con su nombre
  generado. Se reconocen por la propiedad de ID ``geoblender_key`` (no por su nombre, que sigue
  el idioma): se crean cuando tienen contenido y al descargar se quitan las que quedan vacías;
- **el ancla** del proyecto (:func:`ensure_anchor`): un vacío en el origen local con las
  esquinas absolutas de la ventana de trabajo, el GeoOrigin y el CRS **en texto** (nunca
  coordenadas flotantes, ADR-0005), en «Proyecto»;
- **el recorte** de cada Vista 3D (:func:`fit_clip`): su ``clip_end`` cubre lo cargado y
  ``clip_start`` lo sigue con lejano/cercano ≤ 10⁵ (``bl.ui.views.clip_range``, el del
  encuadre de la 003; los datos están a kilómetros del origen y los 1 000 m de Blender los
  recortarían, Silvestre UI-01);
- **la precisión** de lo que se lleva a la escena (:func:`scene_precision`; RF-002-26, spec
  006 §8, T51): si algún vértice pasa de 8 000 m del GeoOrigin en X o en Y, un aviso con
  ``core.georef.precision_report`` (cuántos puntos y el error máximo estimado en mm).

**Descargar** (:func:`unload_datasets`; RF-006-20) quita los objetos de un dato, sus mallas y
las colecciones que quedan vacías; nunca toca el proyecto. Ni cargar ni descargar escriben en el
proyecto ni registran una operación (plan §5.6.4): solo la vista, que deshace Ctrl+Z (los
operadores llevan ``UNDO``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Generator, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

import bpy
import numpy as np
from mathutils import Vector

from ...core.datasets.model import DatasetRecord, DatasetStatus
from ...core.errors import GeoblenderError
from ...core.georef import (
    PRECISION_LIMIT_M,
    GeoOrigin,
    PrecisionReport,
    local_to_world,
    precision_report,
)
from ...core.i18n import language, tr, translate
from ...core.project.model import Progress
from ..props.core import OBJECT_PROPERTY
from .mesh import curves_positions_local, mesh_vertices_world

LOGGER = logging.getLogger("geoblender.bl.scene")

KEY_PROPERTY = "geoblender_key"
"""La propiedad de ID con la que se reconoce cada colección de la vista."""
DATASET_KEY = "dataset:"
"""El comienzo de la clave de la colección de un dato (``dataset:<uid>``)."""
ANCHOR_KIND = "PROJECT_ANCHOR"
ANCHOR_WINDOW = ("xmin", "ymin", "xmax", "ymax")
"""Las esquinas de la ventana en el ancla: ``window_xmin``…, en texto (``repr`` del float64)."""

# La rama de cada tipo (plan §5.5; RF-006-29): (clave, msgid de su nombre) de fuera a dentro.
_TOPOGRAPHY: tuple[tuple[str, str], ...] = (("base", "Base data"),
                                            ("base.topography", "Topography"))
BRANCHES: dict[str, tuple[tuple[str, str], ...]] = {
    ANCHOR_KIND: (("project", "Project"),),
    "DTM": _TOPOGRAPHY,
    "TIN": _TOPOGRAPHY,
    "POINTS": _TOPOGRAPHY,
    "BREAKLINES": _TOPOGRAPHY,
    "CONTOURS": _TOPOGRAPHY,
    "BOUNDARY": _TOPOGRAPHY,
    "DRILLHOLES": (("drillholes", "Drillholes"),),
}
# El estado de un dato vivo en su nombre generado y en Object.geoblender.status.
STATUS_TEXT: dict[DatasetStatus, str] = {
    DatasetStatus.CURRENT: "CURRENT",
    DatasetStatus.MISSING: "MISSING",
    DatasetStatus.BLOCKED: "BLOCKED",
    DatasetStatus.DAMAGED: "DAMAGED",
}
_DATA_COLLECTIONS = {"MESH": "meshes", "CURVE": "curves", "CURVES": "hair_curves",
                     "POINTCLOUD": "pointclouds"}


@dataclass(frozen=True)
class ViewRequest:
    """Lo que recibe un cargador: el proyecto abierto, el registro del dato, el nombre generado
    de sus objetos y el nivel de detalle pedido (0: el dato entero; 1 y 2: las versiones para
    la vista general, si su tipo las tiene; RF-006-22)."""

    project: Any
    record: DatasetRecord
    name: str
    lod: int = 0

    @property
    def origin(self) -> Any:
        """El GeoOrigin del proyecto (``core.georef.GeoOrigin``)."""
        return self.project.origin


@dataclass(frozen=True)
class ViewParts:
    """Lo que devuelve un cargador: sus objetos, sin enlazar a ninguna colección y con matriz
    identidad; su extensión local (mínimos y máximos en X, Y, Z; ``None`` si no tiene nada) y
    sus avisos, en el idioma de la interfaz."""

    objects: tuple[bpy.types.Object, ...]
    bounds: tuple[np.ndarray, np.ndarray] | None
    notes: tuple[str, ...] = ()


ViewLoader = Callable[[ViewRequest], "ViewParts | Generator[float, None, ViewParts]"]
"""Un cargador: devuelve las partes del dato o, si lo carga en pasos (T50), un generador que da
su avance (0–1) tras cada paso y devuelve las partes (``StopIteration.value``); cerrado antes
de terminar, borra lo que creó."""


@dataclass(frozen=True)
class Loader:
    """Un cargador registrado: el comienzo del nombre de sus datos, el tipo de sus objetos
    (``Object.geoblender.kind``), el ``msgid`` de ese tipo en el nombre generado y la
    función."""

    prefix: str
    kind: str
    label: str
    load: ViewLoader


@dataclass(frozen=True)
class LoadOutcome:
    """Lo que hizo :func:`load_datasets`: los datos cargados (por nombre), sus objetos, los
    avisos (un dato que falta, un nivel de detalle que no hace falta) y los errores de lo que
    no se cargó, en el idioma de la interfaz."""

    loaded: tuple[str, ...]
    objects: tuple[bpy.types.Object, ...]
    notes: tuple[str, ...]
    errors: tuple[str, ...]


_LOADERS: dict[str, Loader] = {}


# --- Cargadores ------------------------------------------------------------------------------


def register_loader(prefix: str, kind: str, label: str, load: ViewLoader) -> None:
    """Registra el cargador de los datos cuyo nombre empieza por ``prefix`` (D-10): sus
    objetos son del tipo ``kind`` (uno de :data:`BRANCHES`) y su nombre empieza por el
    ``msgid`` ``label``. ``ValueError`` si ya hay uno para ese comienzo o el tipo no tiene
    rama."""
    if not isinstance(prefix, str) or not prefix:
        raise ValueError(f"un cargador se registra por el comienzo de un nombre, no {prefix!r}")
    if kind not in BRANCHES or kind == ANCHOR_KIND:
        raise ValueError(f"{kind!r} no es un tipo de dato de la vista: es uno de "
                         f"{', '.join(k for k in BRANCHES if k != ANCHOR_KIND)}")
    if prefix in _LOADERS:
        raise ValueError(f"ya hay un cargador para los datos «{prefix}…»")
    _LOADERS[prefix] = Loader(prefix, kind, label, load)


def unregister_loader(prefix: str) -> None:
    """Quita el cargador de ``prefix``; si no está, nada."""
    _LOADERS.pop(prefix, None)


def loaders() -> dict[str, Loader]:
    """Los cargadores registrados, por el comienzo de su nombre (una copia)."""
    return dict(_LOADERS)


def loader_for(name: str) -> Loader | None:
    """El cargador del dato ``name``: el del comienzo más largo que le sirve, o ``None``."""
    found = [prefix for prefix in _LOADERS if name.startswith(prefix)]
    return _LOADERS[max(found, key=len)] if found else None


# --- Nombres y colecciones ---------------------------------------------------------------------


def _text(msgid: str) -> str:
    """``msgid`` (uno de los de este módulo o de un cargador) en el idioma de la interfaz."""
    return translate(language(), msgid)


def view_name(loader: Loader, record: DatasetRecord, *, stale: bool) -> str:
    """El nombre generado de lo que muestra ``record`` (RF-006-29): su tipo, su nombre sin el
    comienzo de su familia y su estado, «MDT mdt_norte [VIGENTE]» o «… [VIGENTE · OBSOLETO]»;
    sin cifras de cálculo."""
    short = record.name[len(loader.prefix):] if record.name.startswith(loader.prefix) else (
        record.name)
    state = _text(STATUS_TEXT.get(record.status, "CURRENT"))
    if stale:
        state = f"{state} · {tr('STALE')}"
    # Sin nombre corto (el dato es su familia entera: las trazas de los sondeos, dh_trace),
    # «Sondeos [VIGENTE]».
    return " ".join(part for part in (_text(loader.label), short, f"[{state}]") if part)


def _child(parent: bpy.types.Collection, key: str, name: str) -> bpy.types.Collection:
    """La colección ``key`` dentro de ``parent``: la que ya está, la que existe en otro sitio
    (enlazada aquí) o una nueva con ``name``."""
    for child in parent.children:
        if child.get(KEY_PROPERTY) == key:
            return child
    found = next((item for item in bpy.data.collections if item.get(KEY_PROPERTY) == key),
                 None)
    if found is None:
        found = bpy.data.collections.new(name)
        found[KEY_PROPERTY] = key
    parent.children.link(found)
    return found


def ensure_collection(kind: str, dataset: DatasetRecord | None = None, *,
                      name: str | None = None,
                      scene: bpy.types.Scene | None = None) -> bpy.types.Collection:
    """La colección tipada de ``kind`` en ``scene`` (por defecto, la de la ventana): su rama
    («Datos base / Topografía», «Proyecto», «Sondeos»), creada o enlazada donde falte, y, con
    ``dataset``, la de ese dato dentro de ella, con el nombre ``name`` (por defecto, el del
    dato). ``KeyError`` si ``kind`` no tiene rama."""
    chosen = bpy.context.scene if scene is None else scene
    parent = chosen.collection
    for key, label in BRANCHES[kind]:
        parent = _child(parent, key, _text(label))
    if dataset is not None:
        wanted = dataset.name if name is None else name
        parent = _child(parent, f"{DATASET_KEY}{dataset.uid}", wanted)
        if parent.name != wanted:
            parent.name = wanted
    return parent


def collection_path(collection: bpy.types.Collection,
                    scene: bpy.types.Scene | None = None) -> list[str]:
    """Los nombres de las colecciones de ``scene`` desde su raíz hasta ``collection``
    (vacía si no está en ella)."""
    chosen = bpy.context.scene if scene is None else scene
    pending: list[tuple[bpy.types.Collection, list[str]]] = [(chosen.collection, [])]
    while pending:
        current, path = pending.pop()
        for child in current.children:
            here = [*path, child.name]
            if child == collection:
                return here
            pending.append((child, here))
    return []


# --- Ancla y recorte -------------------------------------------------------------------------


def _reference_text(project: Any) -> str:
    """«EPSG:25830 + EPSG:5782» o «EPSG:25830 + referencia local (nota)»."""
    record = project.record
    if record.vcrs_epsg is None:
        vertical = tr("local reference ({note})", note=record.vcrs_note or "")
    else:
        vertical = f"EPSG:{record.vcrs_epsg}"
    return f"EPSG:{record.crs_epsg} + {vertical}"


def ensure_anchor(project: Any, scene: bpy.types.Scene | None = None) -> bpy.types.Object:
    """Crea o pone al día el ancla de ``project`` (RF-006-29; Silvestre UI-01): un vacío en el
    origen local, con matriz identidad, en «Proyecto», con las esquinas absolutas de la
    ventana de trabajo (``window_xmin``…), el GeoOrigin (``geoorigin``, «X0 Y0 Z0») y el CRS
    (``crs``) como propiedades de texto."""
    anchor = next((obj for obj in bpy.data.objects
                   if getattr(obj, OBJECT_PROPERTY).kind == ANCHOR_KIND
                   and getattr(obj, OBJECT_PROPERTY).project_uid == project.uid), None)
    if anchor is None:
        anchor = bpy.data.objects.new(tr("Project anchor"), None)
        anchor.empty_display_type = "PLAIN_AXES"
        props = getattr(anchor, OBJECT_PROPERTY)
        props.kind = ANCHOR_KIND
        props.project_uid = project.uid
    collection = ensure_collection(ANCHOR_KIND, scene=scene)
    if collection not in anchor.users_collection:
        collection.objects.link(anchor)
    window = project.window
    for key in ANCHOR_WINDOW:
        if window is None:
            anchor.pop(f"window_{key}", None)
        else:
            anchor[f"window_{key}"] = repr(float(getattr(window, key)))
    anchor["geoorigin"] = " ".join(str(value) for value in project.origin.as_tuple())
    anchor["crs"] = _reference_text(project)
    return anchor


def _view3d_spaces() -> Iterable[Any]:
    for screen in bpy.data.screens:
        for area in screen.areas:
            for space in area.spaces:
                if space.type == "VIEW_3D" and space.region_3d is not None:
                    yield space


def fit_clip(low: Sequence[float], high: Sequence[float]) -> None:
    """Ajusta el recorte de cada Vista 3D para que no recorte la caja local ``low``–``high``
    vista desde su ojo, en perspectiva y en ortográfica, con lejano/cercano ≤ 10⁵
    (``bl.ui.views.clip_range``); un ``clip_end`` mayor se conserva si cabe."""
    from ..ui.views import clip_range  # bl.ui importa bl.scene: se importa al usarlo

    corners = [Vector((x, y, z)) for x in (low[0], high[0]) for y in (low[1], high[1])
               for z in (low[2], high[2])]
    for space in _view3d_spaces():
        rv3d = space.region_3d
        centre = Vector(rv3d.view_location)
        radius = max((corner - centre).length for corner in corners)
        start, end = clip_range(space.clip_end, rv3d.view_distance, radius)
        space.clip_end = end
        space.clip_start = start


# --- Cargar y descargar ----------------------------------------------------------------------


def _mark(obj: bpy.types.Object, kind: str, shown: Any, project: Any) -> None:
    props = getattr(obj, OBJECT_PROPERTY)
    record = shown.record
    props.kind = kind
    props.dataset_uid = record.uid
    props.project_uid = project.uid
    props.content_sha256 = record.content_sha256
    props.status = STATUS_TEXT.get(record.status, "NONE")
    props.date = shown.date
    props.stale = shown.stale


def scene_precision(parts: ViewParts, origin: GeoOrigin) -> PrecisionReport | None:
    """El aviso de RF-002-26 de lo que lleva a la escena un cargador (T51): el de
    ``core.georef.precision_report`` de los vértices de sus mallas (y, spec 005, de los
    puntos de sus curvas), tal como los guarda Blender, vueltos a absolutas (cuántos pasan de
    8 000 m del GeoOrigin en X o en Y y el error máximo estimado en mm). ``None`` si su
    extensión local queda dentro (no se leen los vértices) o si no tiene ninguna malla ni
    curvas con puntos."""
    if parts.bounds is None:
        return None
    low, high = (np.asarray(corner, dtype=np.float64)[:2] for corner in parts.bounds)
    if max(float(np.abs(low).max()), float(np.abs(high).max())) <= PRECISION_LIMIT_M:
        return None
    vertices = [mesh_vertices_world(obj.data, origin) for obj in parts.objects
                if isinstance(obj.data, bpy.types.Mesh) and len(obj.data.vertices)]
    vertices += [local_to_world(curves_positions_local(obj.data), origin)
                 for obj in parts.objects
                 if isinstance(obj.data, bpy.types.Curves) and len(obj.data.points)]
    if not vertices:
        return None
    return precision_report(np.vstack(vertices), origin)


LOAD_PHASE = "Load into the view"
"""La fase de los pasos de :func:`load_steps` (``Progress.phase``, un ``msgid``)."""
STEPS_TOTAL = 1000
"""El total de los pasos de :func:`load_steps` (``Progress.total``): su avance, en milésimas."""


@dataclass
class _Built:
    """Lo que :func:`load_steps` deja preparado de un dato antes de ponerlo en la escena: los
    avisos que van en su sitio (uno que falta) o su cargador, lo que dice el proyecto de él,
    su nombre generado y sus partes, sin enlazar."""

    notes: list[str] = field(default_factory=list)
    loader: Loader | None = None
    shown: Any = None
    name: str = ""
    parts: ViewParts | None = None


def _parts(found: Any, start: float, width: float,
           label: str) -> Generator[Progress, None, ViewParts]:
    """Las partes de un cargador: las que devuelve o, si carga en pasos, las de su generador,
    con su avance (0–1) llevado al tramo [``start``, ``start + width``] del total."""
    if not isinstance(found, Generator):
        return found
    try:
        while True:
            try:
                done = next(found)
            except StopIteration as stop:
                return stop.value
            fraction = start + width * min(max(float(done), 0.0), 1.0)
            yield Progress(LOAD_PHASE, int(STEPS_TOTAL * fraction), STEPS_TOTAL, label)
    finally:
        found.close()


def _discard(objects: Iterable[bpy.types.Object]) -> None:
    """Borra los objetos sin enlazar de ``objects`` y sus mallas (si nadie más las usa)."""
    for obj in list(objects):
        data = obj.data
        bpy.data.objects.remove(obj)
        owner = getattr(bpy.data, _DATA_COLLECTIONS.get(getattr(data, "id_type", ""), ""),
                        None) if data is not None else None
        if owner is not None and data.users == 0:
            owner.remove(data)


def load_steps(context: Any, project: Any, refs: Iterable[str], *,
               lod: int = 0) -> Generator[Progress, None, None]:
    """Los pasos que cargan en la escena de ``context`` los datos ``refs`` (uids o nombres)
    del proyecto abierto ``project`` con su cargador (RF-006-19, RF-006-29; T50: en pasos de
    décimas de segundo como mucho, para la orden desde el temporizador de su ventana, con su
    avance y Esc, RNF-006-09): cada uno da su ``Progress`` (fase :data:`LOAD_PHASE`, hecho de
    :data:`STEPS_TOTAL`, el nombre del dato) y el último, el :class:`LoadOutcome` en
    ``result``. Primero se preparan todos sin tocar la escena (los objetos, sin enlazar) y en
    el último paso, de una vez, cada uno pasa a la colección de su dato con
    ``Object.geoblender`` y su nombre generado, sustituyendo lo que hubiera de él, con el aviso
    de RF-002-26 si pasa de 8 km del GeoOrigin (:func:`scene_precision`), y después el ancla y
    el recorte. Cerrar los pasos antes del último (Esc), o un error que no es para la persona,
    borra lo preparado: la vista queda como estaba. Un dato que falta se avisa y no se carga;
    uno que el proyecto no tiene, sin cargador o que su cargador rechaza (``GeoblenderError``:
    otro CRS, una malla no válida…) es un error y los demás se cargan. No escribe nada en el
    proyecto."""
    from ...core.provenance.view import dataset_view  # al usarlo: no al habilitar

    scene = getattr(context, "scene", None) or bpy.context.scene
    wanted = list(refs)
    built: list[_Built] = []
    errors: list[str] = []
    width = 1.0 / max(1, len(wanted))
    try:
        for index, ref in enumerate(wanted):
            yield Progress(LOAD_PHASE, int(STEPS_TOTAL * index * width), STEPS_TOTAL, str(ref))
            try:
                shown = dataset_view(project, ref)
            except GeoblenderError as error:
                errors.append(str(error))
                continue
            if shown is None:
                errors.append(tr("There is no data «{name}» in the project", name=ref))
                continue
            record = shown.record
            if record.status is DatasetStatus.MISSING:
                built.append(_Built([tr("«{name}» is missing from the project: it is not "
                                        "loaded into the view", name=record.name)]))
                continue
            loader = loader_for(record.name)
            if loader is None:
                errors.append(tr("«{name}» cannot be shown in the view: no module loads it",
                                 name=record.name))
                continue
            name = view_name(loader, record, stale=shown.stale)
            entry = _Built([], loader, shown, name)
            built.append(entry)
            try:
                entry.parts = yield from _parts(
                    loader.load(ViewRequest(project, record, name, lod)), index * width, width,
                    record.name)
            except GeoblenderError as error:
                LOGGER.info("No se carga «%s» en la vista: %s", record.name, error)
                errors.append(str(error))
                built.remove(entry)
    except BaseException:
        _discard(obj for entry in built if entry.parts is not None
                 for obj in entry.parts.objects)
        raise
    yield Progress(LOAD_PHASE, STEPS_TOTAL, STEPS_TOTAL, "",
                   _place(scene, project, built, errors))


def _place(scene: Any, project: Any, built: Sequence[_Built],
           errors: Sequence[str]) -> LoadOutcome:
    """El último paso de :func:`load_steps`: lo preparado, a la escena (véase allí)."""
    loaded: list[str] = []
    objects: list[bpy.types.Object] = []
    notes: list[str] = []
    lows: list[np.ndarray] = []
    highs: list[np.ndarray] = []
    for entry in built:
        notes.extend(entry.notes)
        parts, loader, shown = entry.parts, entry.loader, entry.shown
        if parts is None or loader is None:
            continue
        record = shown.record
        unload_datasets([record.uid])  # otro nivel de detalle, o el dato al día
        collection = ensure_collection(loader.kind, record, name=entry.name, scene=scene)
        for obj in parts.objects:
            collection.objects.link(obj)
            _mark(obj, loader.kind, shown, project)
        loaded.append(record.name)
        objects.extend(parts.objects)
        notes.extend(parts.notes)
        far = scene_precision(parts, project.origin)
        if far is not None and not far.within_limit:
            notes.append(tr("«{name}» in the view: {warning}", name=record.name,
                            warning=far.message))
        if parts.bounds is not None:
            lows.append(np.asarray(parts.bounds[0], dtype=np.float64))
            highs.append(np.asarray(parts.bounds[1], dtype=np.float64))
    if loaded:
        ensure_anchor(project, scene)
    if lows:
        fit_clip(np.min(lows, axis=0), np.max(highs, axis=0))
    return LoadOutcome(tuple(loaded), tuple(objects), tuple(notes), tuple(errors))


def load_datasets(context: Any, project: Any, refs: Iterable[str], *,
                  lod: int = 0) -> LoadOutcome:
    """Carga de una vez en la escena de ``context`` los datos ``refs`` (uids o nombres) del
    proyecto abierto ``project``: todos los pasos de :func:`load_steps` seguidos (desde un
    guion; la orden desde la interfaz los da desde su temporizador). Devuelve su
    :class:`LoadOutcome`."""
    outcome: LoadOutcome | None = None
    for step in load_steps(context, project, refs, lod=lod):
        if isinstance(step.result, LoadOutcome):
            outcome = step.result
    assert outcome is not None
    return outcome


def loaded_uids(objects: Iterable[bpy.types.Object]) -> list[str]:
    """Los datos que muestran ``objects`` (sin repetir, por orden de aparición)."""
    found: dict[str, None] = {}
    for obj in objects:
        uid = getattr(obj, OBJECT_PROPERTY).dataset_uid
        if uid:
            found[uid] = None
    return list(found)


def _remove_empty(collection: bpy.types.Collection) -> None:
    """Quita ``collection`` si está vacía y, después, las de su rama que queden vacías (nunca
    «Proyecto», la del ancla)."""
    key = collection.get(KEY_PROPERTY, "")
    if collection.objects or collection.children or key == "project":
        return
    parents = [item for item in bpy.data.collections if collection in item.children.values()]
    bpy.data.collections.remove(collection)
    for parent in parents:
        if parent.get(KEY_PROPERTY):
            _remove_empty(parent)


def unload_datasets(uids: Iterable[str]) -> int:
    """Quita de la escena los objetos que muestran los datos ``uids``, sus mallas (si nadie
    más las usa) y las colecciones de la vista que quedan vacías (RF-006-20); devuelve
    cuántos objetos quitó. No toca el proyecto."""
    wanted = set(uids)
    found = [obj for obj in bpy.data.objects
             if getattr(obj, OBJECT_PROPERTY).dataset_uid in wanted]
    collections = {collection for obj in found for collection in obj.users_collection
                   if str(collection.get(KEY_PROPERTY, "")).startswith(DATASET_KEY)}
    for obj in found:
        data = obj.data
        bpy.data.objects.remove(obj)
        owner = getattr(bpy.data, _DATA_COLLECTIONS.get(getattr(data, "id_type", ""), ""),
                        None) if data is not None else None
        if owner is not None and data.users == 0:
            owner.remove(data)
    for collection in collections:
        _remove_empty(collection)
    return len(found)

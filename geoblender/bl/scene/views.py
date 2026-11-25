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
  el idioma): se crean cuando tienen contenido y al descargar se quitan las que quedan vacías.
  Un dato de una versión va en la colección de su versión, bajo «Versiones», y lleva en su
  nombre el código de su versión; un dato con título, su título en lugar de su nombre (spec
  009, T22; RF-009-30, RF-009-22). Lo que nombra Geoblender queda anotado (:data:`NAME_PROPERTY`)
  para saber si después lo renombra la persona;
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

**Al día sin recargar** (spec 010, T07; RF-010-01, RF-010-02, RF-010-08; plan 010 §5.3.2, A1 a
A3, D-9 a D-13 y D-17; generaliza lo de los sondeos, spec 005, T47):

- cada objeto cargado anota además el GeoOrigin con que se cargó (``Object.geoblender.origin``,
  «X0 Y0 Z0» en metros enteros), «al día» (``view_state``) y las cifras registradas de su dato
  como texto ya escrito (``figures``: las de la operación que escribió su contenido, sin marcas,
  ``core.views.card.dataset_figures``; solo para mostrarlas: solo las escribe este módulo y
  solo las lee ``bl/ui``, D-17), que Refrescar vuelve a poner también en lo que no vuelve a
  cargar (:func:`show_figures`; spec 010, T16);
- :func:`loaded_items` agrupa por dato los objetos de Geoblender de la escena (no los del
  usuario ni los de «99 Trabajo», que no tienen dato) y :func:`loaded_item` dice con qué se
  cargaron (``core.views.state.LoadedItem``), para ``core.views.state.view_states``;
- :func:`show_view_state` pone al día, sin volver a cargar nada ni escribir en el proyecto, lo
  que dice hoy el proyecto de cada dato (``core.views.state.ItemView``): ``view_state``, su
  estado y si está obsoleto en ``Object.geoblender`` y el nombre generado de sus objetos y de la
  colección del dato (:func:`view_name`: «MDT mdt_norte [VIGENTE · NO AL DÍA]», «… [SIN
  RESPALDO]»), con las colecciones buscadas una vez por su clave, ``ID.rename`` y, si se le da,
  un presupuesto de tiempo por tanda (sustituye a la marca propia de los sondeos de la 005,
  T47: spec 010, T09);
- un cargador declara con :func:`extend_loader` lo suyo que se pone al día en vivo
  (:class:`LiveHook`: lo que lee en la misma instantánea, :func:`live_reads`, y cómo lo aplica)
  y lo que no se guarda en el ``.blend`` (:class:`SessionParts`; la superposición de los
  sondeos, ``bl.scene.dh_view``, que la marca en vivo rehace tras abrir el proyecto);
- un cargador declara al registrarse (:func:`register_loader`) los **datos compañeros** de su
  dato (:data:`CompanionsReader`; spec 017, T31c): los otros datos del proyecto con que dibuja su
  objeto (la superficie y el eje de una entidad de diseño: la cota de lo que se ve es suya y no
  la de la tabla). Al cargar, el objeto anota su uid y su hash (``Object.geoblender.companions``,
  ``core.views.state.companions_text``) y ``core.views.state`` los cuenta para «no al día»;
- :func:`load_steps` vuelve a cargar con Refrescar (F5): en su último paso, además, quita lo
  sustituido por lo que carga (``replaces``), marca «sin respaldo en el proyecto» sin borrarlos
  los objetos de los datos ``unbacked`` y, con ``clear_view_stale``, quita la marca de vista
  desfasada de las escenas (RF-002-29);
- cargar y descargar piden la marca en vivo (``bl.scene.live.request``; spec 010, T08): lo que
  no está al día cambia, y con él el control 7; y después, una vez por carga o descarga, llaman
  a lo apuntado con :func:`add_view_listener` (spec 010, T21: el inventario de N ▸ Proyecto
  pone al día su columna «En la escena» sin volver a leer el proyecto).
"""

from __future__ import annotations

import logging
import re
import sqlite3
import time
from collections.abc import Callable, Collection, Generator, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
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
from ...core.versions import read as versions_read
from ...core.views.state import ItemState, ItemView, LoadedItem, companions_text, origin_text
from ..props.core import OBJECT_PROPERTY
from . import georef
from .mesh import curves_positions_local, mesh_vertices_world

LOGGER = logging.getLogger("geoblender.bl.scene")

KEY_PROPERTY = "geoblender_key"
"""La propiedad de ID con la que se reconoce cada colección de la vista."""
DATASET_KEY = "dataset:"
"""El comienzo de la clave de la colección de un dato (``dataset:<uid>``)."""
NAME_PROPERTY = "geoblender_name"
"""La propiedad de ID con el nombre que le puso Geoblender a un objeto o una colección de la
vista (el generado, tal como quedó; spec 009, T22): si el de hoy es otro, lo renombró la persona
(RF-009-22, ``bl.scene.versions.on_name_changed``)."""
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
    # La rejilla de diferencias de una cubicación (spec 011, T22): siempre de una versión, va
    # en la colección de su versión; sin ella, en «Cubicación».
    "VOLUME_DIFFERENCE": (("volumetrics", "Volumetrics"),),
    # Las intenciones del cliente (spec 012, T25; RF-012-26): datos del proyecto, no de una versión.
    "CLIENT_INTENTION": (("constraints", "Constraints"),),
    # Las restricciones y los límites (spec 012, T27; RF-012-19): datos del proyecto, como las
    # intenciones; con ellas en la misma rama.
    "CONSTRAINT": (("constraints", "Constraints"),),
    # La rejilla de incumplimientos de una verificación por recinto (spec 012, T28; RF-012-23,
    # D-42): siempre de una versión, va en la colección de su versión; sin ella, en «Cubicación».
    "COMPLIANCE_GRID": (("volumetrics", "Volumetrics"),),
    # La envolvente, la superficie de diseño y la rejilla de cotas de berma de un diseño (spec
    # 013, T27; RF-013-32, D-32): siempre de una versión, van en la colección de su versión; sin
    # ella, en «Diseño».
    "DESIGN": (("design", "Design"),),
    # Una entidad de diseño (spec 015, T28; RF-015-25): siempre de una versión, va en la colección de su
    # versión; sin ella, en «Diseño», como las rejillas de un diseño.
    "DESIGN_ENTITY": (("design", "Design"),),
}
# El estado de un dato vivo en su nombre generado y en Object.geoblender.status.
STATUS_TEXT: dict[DatasetStatus, str] = {
    DatasetStatus.CURRENT: "CURRENT",
    DatasetStatus.MISSING: "MISSING",
    DatasetStatus.BLOCKED: "BLOCKED",
    DatasetStatus.DAMAGED: "DAMAGED",
}
_STATUS_OF: dict[str, DatasetStatus] = {text: status for status, text in STATUS_TEXT.items()}
OUTDATED_TEXT = "NOT UP TO DATE"
"""El ``msgid`` de «no al día» en el nombre generado (spec 010, D-10)."""
UNBACKED_TEXT = "UNBACKED"
"""El ``msgid`` de «sin respaldo en el proyecto» en el nombre generado (spec 010, D-10)."""
# Object.geoblender.view_state (bl.props.core.VIEW_STATES).
VIEW_CURRENT = "CURRENT"
VIEW_OUTDATED = "OUTDATED"
VIEW_UNBACKED = "UNBACKED"
_LIVE_HOOKED = frozenset({ItemState.CURRENT, ItemState.RESTATE})
"""Los estados en que se aplica el :class:`LiveHook` de un cargador: lo que muestra el
contenido de hoy (lo de otro contenido lo pone al día volver a cargarlo)."""
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
class LiveHook:
    """Lo que pone al día en vivo un cargador, además de lo general (spec 010, D-13): ``read``
    lee del proyecto lo que necesita, en la instantánea de quien lo llama (:func:`live_reads`;
    los sondeos, los de traza obsoleta), y ``apply`` lo aplica a los objetos de un dato que
    muestran su contenido de hoy, con lo que dice de él el proyecto (``ItemView``) y lo leído;
    devuelve si cambió algo. Ninguno escribe en el proyecto."""

    read: Callable[[sqlite3.Connection], Any]
    apply: Callable[[Sequence[bpy.types.Object], ItemView, Any], bool]


@dataclass(frozen=True)
class SessionParts:
    """Lo de un cargador que no se guarda en el ``.blend`` (spec 010, RF-010-03, D-13; la
    superposición de los sondeos): ``missing`` dice si a sus objetos de la escena les falta en
    esta sesión (con el proyecto abierto) y ``rebuild`` lo rehace en segundo plano (devuelve si
    lo lanzó)."""

    missing: Callable[[Any, Sequence[bpy.types.Object]], bool]
    rebuild: Callable[[Any], bool]


CompanionsReader = Callable[[sqlite3.Connection, DatasetRecord], Sequence[DatasetRecord]]
"""Lo que declara un cargador de sus **datos compañeros** (spec 017, T31c): dado el registro del
dato que se va a cargar y una conexión de lectura, los registros de los otros datos del proyecto con
que dibuja su objeto (los vivos que lee: no los de otra versión que no lee). Cuentan como su
contenido para «no al día». Solo lee."""


OwnTitleReader = Callable[[Any, sqlite3.Connection, str, str], str]
"""Lo que declara un cargador del **nombre propio** de sus datos (spec 018, T40e, H3-6): dado el proyecto, una conexión de lectura, el uid de la versión del dato y su nombre, el que lleva el
objeto en lugar del nombre del dato (que es el del cálculo en minúsculas y sin acentos: «corta_e1»; la corta de la que sale se llama «Corta E1»); ``""``: el del dato. Solo lee."""


@dataclass(frozen=True)
class Loader:
    """Un cargador registrado: el comienzo del nombre de sus datos, el tipo de sus objetos
    (``Object.geoblender.kind``), el ``msgid`` de ese tipo en el nombre generado y la
    función; y, si los declara (:func:`extend_loader`; spec 010), su marca en vivo y lo que
    no guarda el ``.blend``; y, si los declara al registrarse (:func:`register_loader`; spec
    017, T31c), sus datos compañeros."""

    prefix: str
    kind: str
    label: str
    load: ViewLoader
    live: LiveHook | None = None
    session_parts: SessionParts | None = None
    companions: CompanionsReader | None = None
    own_title: OwnTitleReader | None = None


@dataclass(frozen=True)
class LoadOutcome:
    """Lo que hizo :func:`load_datasets`: los datos cargados (por nombre), sus objetos, los
    avisos (un dato que falta, un nivel de detalle que no hace falta) y los errores de lo que
    no se cargó, en el idioma de la interfaz; ``labels``, lo cargado como lo nombra el informe
    de la orden: el nombre y, el de una versión, con su código («des_final · V10»; spec 009,
    T32), en el orden de ``loaded`` (vacío: los nombres)."""

    loaded: tuple[str, ...]
    objects: tuple[bpy.types.Object, ...]
    notes: tuple[str, ...]
    errors: tuple[str, ...]
    labels: tuple[str, ...] = ()


_LOADERS: dict[str, Loader] = {}

ViewListener = Callable[[], None]
"""Lo que se llama tras cargar o descargar algo de la vista (:func:`add_view_listener`; spec
010, T21)."""
_VIEW_LISTENERS: list[ViewListener] = []


# --- Cargadores ------------------------------------------------------------------------------


def register_loader(prefix: str, kind: str, label: str, load: ViewLoader, *,
                    companions: CompanionsReader | None = None,
                    own_title: OwnTitleReader | None = None) -> None:
    """Registra el cargador de los datos cuyo nombre empieza por ``prefix`` (D-10): sus
    objetos son del tipo ``kind`` (uno de :data:`BRANCHES`) y su nombre empieza por el
    ``msgid`` ``label``; con ``companions``, los otros datos del proyecto con que dibuja su
    objeto (:data:`CompanionsReader`: cuentan para «no al día»). ``ValueError`` si ya hay uno
    para ese comienzo o el tipo no tiene rama."""
    if not isinstance(prefix, str) or not prefix:
        raise ValueError(f"un cargador se registra por el comienzo de un nombre, no {prefix!r}")
    if kind not in BRANCHES or kind == ANCHOR_KIND:
        raise ValueError(f"{kind!r} no es un tipo de dato de la vista: es uno de "
                         f"{', '.join(k for k in BRANCHES if k != ANCHOR_KIND)}")
    if prefix in _LOADERS:
        raise ValueError(f"ya hay un cargador para los datos «{prefix}…»")
    if companions is not None and not callable(companions):
        raise TypeError(f"los datos compañeros de un cargador los lee una función, no {companions!r}")
    _LOADERS[prefix] = Loader(prefix, kind, label, load, companions=companions, own_title=own_title)


def unregister_loader(prefix: str) -> None:
    """Quita el cargador de ``prefix`` con lo que declaró (:func:`extend_loader`); si no está,
    nada."""
    _LOADERS.pop(prefix, None)


def extend_loader(prefix: str, *, live: LiveHook | None = None,
                  session_parts: SessionParts | None = None) -> None:
    """Declara lo que el cargador de ``prefix`` pone al día en vivo (``live``) y lo que no se
    guarda en el ``.blend`` (``session_parts``), en lugar de lo que declarara antes (sin
    nada: ninguno), sin cambiar su función (spec 010, D-13). :class:`TypeError` si no son un
    :class:`LiveHook` y un :class:`SessionParts`; ``ValueError`` si no hay cargador para ese
    comienzo."""
    if live is not None and not isinstance(live, LiveHook):
        raise TypeError(f"la marca en vivo de un cargador es un LiveHook, no {live!r}")
    if session_parts is not None and not isinstance(session_parts, SessionParts):
        raise TypeError("lo que no se guarda en el .blend es un SessionParts, no "
                        f"{session_parts!r}")
    found = _LOADERS.get(prefix)
    if found is None:
        raise ValueError(f"no hay ningún cargador para los datos «{prefix}…»")
    _LOADERS[prefix] = replace(found, live=live, session_parts=session_parts)


def live_reads(conn: sqlite3.Connection,
               prefixes: Collection[str] | None = None) -> dict[str, Any]:
    """Lo que lee de ``conn`` (en la instantánea de quien llama) el :class:`LiveHook` de cada
    cargador que lo declara, por su comienzo: lo que :func:`show_view_state` le da a su
    ``apply``. Con ``prefixes``, solo el de esos cargadores (la marca en vivo pide solo los de
    lo que está en la escena: un proyecto con sondeos sin su vista no los lee). No
    escribe."""
    return {prefix: loader.live.read(conn) for prefix, loader in _LOADERS.items()
            if loader.live is not None and (prefixes is None or prefix in prefixes)}


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


def view_name(loader: Loader, record: DatasetRecord, *, stale: bool, outdated: bool = False,
              unbacked: bool = False, title: str | None = None,
              version: str | None = None) -> str:
    """El nombre generado de lo que muestra ``record`` (RF-006-29): su tipo, su nombre sin el
    comienzo de su familia y su estado, «MDT mdt_norte [VIGENTE]» o «… [VIGENTE · OBSOLETO]»;
    con ``outdated``, si muestra un contenido anterior, «… [VIGENTE · OBSOLETO · NO AL DÍA]»;
    con ``unbacked``, si su dato ya no está en el proyecto, «MDT mdt_norte [SIN RESPALDO]»
    (spec 010, D-10). Con ``title``, el título que le dio la persona (spec 009, RF-009-22) en
    lugar de su nombre: «MDT Fondo de la corta [VIGENTE]»; un dato de una versión lleva su
    código (``version``): «MDT des_final · V10 [VIGENTE]» (dos versiones pueden tener un dato
    con el mismo nombre, y Blender no admite dos objetos con el mismo). En el idioma de la
    interfaz y sin cifras de cálculo."""
    short = record.name[len(loader.prefix):] if record.name.startswith(loader.prefix) else (
        record.name)
    if title:
        short = title
    if version:
        short = f"{short} · {version}" if short else version
    if unbacked:
        return " ".join(part for part in (_text(loader.label), short,
                                          f"[{_text(UNBACKED_TEXT)}]") if part)
    state = _text(STATUS_TEXT.get(record.status, "CURRENT"))
    if stale:
        state = f"{state} · {tr('STALE')}"
    if outdated:
        state = f"{state} · {_text(OUTDATED_TEXT)}"
    # Sin nombre corto (el dato es su familia entera: las trazas de los sondeos, dh_trace),
    # «Sondeos [VIGENTE]».
    return " ".join(part for part in (_text(loader.label), short, f"[{state}]") if part)


def relabel(project: Any, obj: bpy.types.Object, label: str) -> bool:
    """Pone a ``obj`` el nombre que ve el Outliner con el rótulo ``label`` en lugar del título (spec 019, T10; P-2): el
    mismo :func:`view_name` de siempre, con ``title=label``; vacío, vuelve al título que tenía el dato. **Solo** cambia
    el nombre del objeto: ni ``gb_dataset.name`` ni la identidad del dato. Devuelve si lo cambió; ``False`` si el dato ya
    no está o ningún módulo lo carga. No escribe en el proyecto."""
    from ...core.provenance.view import dataset_view  # al usarlo: no al habilitar

    uid = getattr(obj, OBJECT_PROPERTY).dataset_uid
    shown = dataset_view(project, uid) if uid else None
    loader = None if shown is None else loader_for(shown.record.name)
    if shown is None or loader is None:
        return False
    _owner, code, title = _dataset_label(project, uid)
    name = view_name(loader, shown.record, stale=shown.stale, title=label.strip() or title or None,
                     version=code or None)
    return named(obj, name)


def child_collection(parent: bpy.types.Collection, key: str, name: str) -> bpy.types.Collection:
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
                      name: str | None = None, scene: bpy.types.Scene | None = None,
                      version: tuple[Any, Any] | None = None) -> bpy.types.Collection:
    """La colección tipada de ``kind`` en ``scene`` (por defecto, la de la ventana): su rama
    («Datos base / Topografía», «Proyecto», «Sondeos»), creada o enlazada donde falte, y, con
    ``dataset``, la de ese dato dentro de ella, con el nombre ``name`` (por defecto, el del
    dato). Un dato de una versión (``version``: su ``Version`` y la revisión que se enseña con
    ella, spec 009, RF-009-30) va en la colección de su versión, bajo «Versiones», en lugar de
    su rama (``bl.scene.versions.ensure_version_collection``). ``KeyError`` si ``kind`` no
    tiene rama."""
    chosen = bpy.context.scene if scene is None else scene
    parent = chosen.collection
    if version is not None and dataset is not None:
        from . import versions as scene_versions  # al usarlo: versions importa este módulo

        parent = scene_versions.ensure_version_collection(*version, scene=chosen)
    else:
        for key, label in BRANCHES[kind]:
            parent = child_collection(parent, key, _text(label))
    if dataset is not None:
        wanted = dataset.name if name is None else name
        parent = child_collection(parent, f"{DATASET_KEY}{dataset.uid}", wanted)
        named(parent, wanted)
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
    anchor["geoorigin"] = origin_text(project.origin)
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


@dataclass(frozen=True)
class FigureText:
    """Una cifra registrada como la anota cada objeto (``Object.geoblender.figures``; spec 010,
    D-17): su uid y su clave, su nombre con su ámbito y su valor con su unidad, escritos en el
    idioma de la interfaz, el código de su unidad y su tipo («CALCULADO»)."""

    uid: str
    key: str
    label: str
    value_text: str
    unit: str
    kind: str

    @classmethod
    def of(cls, figure: Any, shown_language: str) -> FigureText:
        """La de ``figure`` (``core.provenance.figures.FigureRecord``) en ``shown_language``:
        lo que escribe ``FigureRecord.text`` («Volumen · fase 2 = 1 563 631 m³»), partido en su
        nombre y su valor; la superficie del ámbito de una cifra de la 014, en ese idioma
        (``design.provenance.figure_text``; spec 014, T61)."""
        from ...design.provenance import figure_text  # al usarlo: no al habilitar

        text = figure_text(figure, language=shown_language)
        label, found, value = text.rpartition(" = ")
        if not found:
            label, value = text, ""
        return cls(figure.uid, figure.key, label, value, figure.unit, str(figure.kind))


def _put_figures(props: Any, figures: Sequence[FigureText]) -> None:
    """Las cifras ``figures`` en ``Object.geoblender.figures`` (``props``), en lugar de las que
    tuviera. Solo este módulo las escribe y solo ``bl/ui`` las lee (spec 010, D-17; lo vigila
    ``tests/unit/architecture/test_views_figures.py``): son para mostrarlas; ningún cálculo las
    lee (las cifras se leen del proyecto, con su tipo y su procedencia)."""
    props.figures.clear()
    for figure in figures:
        item = props.figures.add()
        item.uid = figure.uid
        item.key = figure.key
        item.label = figure.label
        item.value_text = figure.value_text
        item.unit = figure.unit
        item.kind = figure.kind


def _figure_texts(project: Any, uids: Iterable[str]) -> dict[str, tuple[FigureText, ...]]:
    """Las cifras registradas de hoy de los datos ``uids`` del proyecto ``project`` (las de la
    operación que escribió su contenido, sin marcas: ``core.views.card.dataset_figures``),
    escritas en el idioma de la interfaz, por el uid de cada dato que tiene el proyecto. No
    escribe en el proyecto."""
    from ...core.views import card  # al usarlo: no al habilitar

    shown_language = language()
    return {item.record.uid: tuple(FigureText.of(figure, shown_language)
                                   for figure in item.figures)
            for item in card.dataset_figures(project, list(uids), marks=False)}


def show_figures(project: Any, groups: Mapping[str, Sequence[bpy.types.Object]]) -> int:
    """Pone en los objetos de cada dato de ``groups`` (los de :func:`loaded_items`) las cifras
    registradas de hoy de su dato en el proyecto abierto ``project``, en lugar de las que
    anotaran (``Object.geoblender.figures``; spec 010, RF-010-08; plan A2, A8, D-17): lo que
    hace Refrescar con lo que no vuelve a cargar (lo que sí, las pone al cargarlo). Un dato que
    el proyecto no tiene no se toca. No escribe en el proyecto; devuelve en cuántos datos las
    puso."""
    wanted = [uid for uid, objects in groups.items() if objects]
    if not wanted:
        return 0
    found = _figure_texts(project, wanted)
    for uid, texts in found.items():
        for obj in groups[uid]:
            _put_figures(getattr(obj, OBJECT_PROPERTY), texts)
    return len(found)


def _mark(obj: bpy.types.Object, kind: str, shown: Any, project: Any, origin: str,
          figures: Sequence[FigureText], companions: str = "") -> None:
    props = getattr(obj, OBJECT_PROPERTY)
    record = shown.record
    props.kind = kind
    props.dataset_uid = record.uid
    props.project_uid = project.uid
    props.content_sha256 = record.content_sha256
    props.companions = companions
    props.status = STATUS_TEXT.get(record.status, "NONE")
    props.date = shown.date
    props.stale = shown.stale
    props.view_state = VIEW_CURRENT
    props.origin = origin
    _put_figures(props, figures)


def _shown_name(obj: bpy.types.Object, collection: bpy.types.Collection | None) -> str | None:
    """El nombre generado con que se cargó ``obj``: el de la colección de su dato si su nombre
    empieza por él; si no, hasta el «]» de su estado; ``None`` si no lo lleva."""
    if collection is not None and obj.name.startswith(collection.name):
        return collection.name
    end = obj.name.find("]")
    return obj.name[:end + 1] if end >= 0 else None


def _restated(shown: str, state: str) -> str:
    """El nombre generado ``shown`` («MDT mdt_norte [VIGENTE]») con ``state`` en lugar de su
    estado: «MDT mdt_norte [SIN RESPALDO]»."""
    start = shown.rfind(" [")
    base = shown[:start] if start >= 0 and shown.endswith("]") else shown
    return f"{base} [{state}]"


def loaded_items(project_uid: str | None = None) -> dict[str, tuple[bpy.types.Object, ...]]:
    """Los objetos de la escena que muestran un dato de un proyecto, por el uid de su dato, en
    el orden de ``bpy.data.objects`` (spec 010): con ``project_uid``, solo los de ese proyecto;
    sin él, los de todos (los de otro proyecto están sin respaldo en el abierto, plan A1). No
    entran el ancla, los objetos del usuario ni los de «99 Trabajo», que no tienen dato."""
    found: dict[str, list[bpy.types.Object]] = {}
    for obj in bpy.data.objects:
        props = getattr(obj, OBJECT_PROPERTY)
        uid = props.dataset_uid
        if uid and (project_uid is None or props.project_uid == project_uid):
            found.setdefault(uid, []).append(obj)
    return {uid: tuple(objects) for uid, objects in found.items()}


def loaded_item(uid: str, objects: Sequence[bpy.types.Object]) -> LoadedItem:
    """Lo que dicen los objetos ``objects`` del dato ``uid`` de con qué se cargaron
    (``core.views.state.LoadedItem``: su proyecto, sus hashes, sus GeoOrigin, sus estados y si
    estaban obsoletos), para ``core.views.state.view_states``. ``ValueError`` sin objetos."""
    if not objects:
        raise ValueError(f"el dato {uid} no tiene objetos en la escena")
    marks = [getattr(obj, OBJECT_PROPERTY) for obj in objects]
    return LoadedItem(uid, marks[0].project_uid, [props.content_sha256 for props in marks],
                      [props.origin for props in marks], [props.status for props in marks],
                      [bool(props.stale) for props in marks],
                      [props.companions for props in marks])


def _dataset_collections() -> dict[str, bpy.types.Collection]:
    """La colección de cada dato de la vista, por su uid (por su clave ``dataset:<uid>``,
    buscadas de una vez)."""
    found: dict[str, bpy.types.Collection] = {}
    for item in bpy.data.collections:
        key = item.get(KEY_PROPERTY)
        if isinstance(key, str) and key.startswith(DATASET_KEY):
            found.setdefault(key[len(DATASET_KEY):], item)
    return found


@dataclass(frozen=True)
class _Shown:
    """Lo que tienen que decir los objetos de un dato: «al día» (``view_state``), su estado y
    si está obsoleto (``None``: lo que ya dicen) y su nombre generado (``name``) o, sin él, el
    estado que sustituye al de su nombre (``state_text``); sin ninguno, no se renombran."""

    view_state: str
    status: str | None
    stale: bool | None
    name: str | None
    state_text: str | None = None


def _shown(objects: Sequence[bpy.types.Object], view: ItemView, loader: Loader | None,
           title: str | None = None, version: str | None = None) -> _Shown:
    """Lo que dicen los objetos ``objects`` según lo que dice hoy el proyecto de su dato
    (``view``; plan 010 A1, D-10, D-11), con el cargador de su dato (``None``: el proyecto no lo
    tiene o ningún módulo lo carga), su título y el código de su versión (spec 009)."""
    record = view.record
    if view.state is ItemState.UNBACKED or record is None:
        name = None if loader is None or record is None else view_name(
            loader, record, stale=False, unbacked=True, title=title, version=version)
        return _Shown(VIEW_UNBACKED, None, None, name, _text(UNBACKED_TEXT))
    if view.state is ItemState.REPLACED:
        # Muestra lo de antes, como se cargó: su estado y su obsoleto, «no al día».
        first = getattr(objects[0], OBJECT_PROPERTY)
        loaded = replace(record, status=_STATUS_OF.get(first.status, DatasetStatus.CURRENT))
        name = None if loader is None else view_name(loader, loaded, stale=bool(first.stale),
                                                     outdated=True, title=title,
                                                     version=version)
        return _Shown(VIEW_OUTDATED, None, None, name)
    outdated = view.state is ItemState.OUTDATED
    stale = bool(view.stale)
    name = None if loader is None else view_name(loader, record, stale=stale, outdated=outdated,
                                                 title=title, version=version)
    return _Shown(VIEW_OUTDATED if outdated else VIEW_CURRENT,
                  STATUS_TEXT.get(record.status, "NONE"), stale, name)


def remember(item: bpy.types.ID) -> None:
    """Anota en ``item`` (:data:`NAME_PROPERTY`) que su nombre de hoy es el que le puso
    Geoblender (spec 009, T22): así se sabe si después lo renombra la persona."""
    if item.get(NAME_PROPERTY) != item.name:
        item[NAME_PROPERTY] = item.name


def named(item: bpy.types.ID, name: str) -> bool:
    """Renombra ``item`` a ``name`` si no se llama así (``ID.rename``, sin quitarle el nombre a
    otro: si lo tiene otro, Blender le pone un número a este) y anota el nombre con que queda
    (:func:`remember`). Devuelve si lo renombró."""
    changed = item.name != name
    if changed:
        item.rename(name, mode="NEVER")
    remember(item)
    return changed


def _own_label(objects: Sequence[bpy.types.Object]) -> str:
    """El rótulo que la persona dio a estos objetos (``Object.geoblender.look.label``; spec 019, RF-019-07, P-2): manda sobre el
    título en el nombre que se les genera, para que marcar el dato obsoleto o al día no lo pierda (T34, F-2). '' sin rótulo."""
    for obj in objects:
        label = getattr(obj, OBJECT_PROPERTY).look.label.strip()
        if label:
            return label
    return ""


def _show_group(objects: Sequence[bpy.types.Object], view: ItemView, loader: Loader | None,
                collection: bpy.types.Collection | None, live: Mapping[str, Any],
                title: str | None = None, version: str | None = None) -> bool:
    """Pone al día los objetos ``objects`` de un dato y la colección del dato (véase
    :func:`show_view_state`); devuelve si cambió algo."""
    wanted = _shown(objects, view, loader, _own_label(objects) or title, version)
    name = wanted.name
    if name is None and wanted.state_text is not None:
        shown = collection.name if collection is not None else _shown_name(objects[0], None)
        name = None if shown is None else _restated(shown, wanted.state_text)
    changed = False
    for obj in objects:
        props = getattr(obj, OBJECT_PROPERTY)
        if props.view_state != wanted.view_state:
            props.view_state = wanted.view_state
            changed = True
        if wanted.status is not None and props.status != wanted.status:
            props.status = wanted.status
            changed = True
        if wanted.stale is not None and props.stale != wanted.stale:
            props.stale = wanted.stale
            changed = True
        before = None if name is None else _shown_name(obj, collection)
        if before is not None and before != name:
            # Lo que sigue al nombre de la carga (« · Au» de los sondeos) se conserva.
            changed = named(obj, name + obj.name[len(before):]) or changed
        elif before is not None:
            remember(obj)  # el generado, como estaba (uno sin él, del usuario, no se anota)
    if collection is not None and name is not None:
        changed = named(collection, name) or changed
    hook = None if loader is None else loader.live
    if hook is not None and view.state in _LIVE_HOOKED and loader.prefix in live:
        changed = bool(hook.apply(objects, view, live[loader.prefix])) or changed
    return changed


def show_view_state(groups: Mapping[str, Sequence[bpy.types.Object]],
                    states: Mapping[str, ItemView], *, budget_s: float | None = None,
                    live: Mapping[str, Any] | None = None,
                    titles: Mapping[str, str] | None = None,
                    versions: Mapping[str, str] | None = None) -> tuple[bool, list[str]]:
    """Pone al día, sin volver a cargar nada, los objetos de cada dato de ``groups`` (los de
    :func:`loaded_items`) con lo que dice hoy de él el proyecto (``states``, los de
    ``core.views.state.view_states``; un dato sin estado no se toca) (spec 010, RF-010-02; plan
    A3, D-10, D-11):

    - al día o con otro estado u otro obsoleto (``CURRENT``, ``RESTATE``): su estado y si está
      obsoleto, «al día»; con otro contenido u otro GeoOrigin (``OUTDATED``), además «no al
      día»; lo sustituido (``REPLACED``), «no al día» con lo que mostraba; lo que falta
      (``MISSING``), su estado («FALTA»); sin respaldo en el proyecto (``UNBACKED``), «sin
      respaldo», sin borrar nada;
    - ``Object.geoblender`` (``view_state``, ``status``, ``stale``) y el nombre generado de los
      objetos (lo que sigue al de la carga, como « · Au», se conserva; un nombre que no lo
      lleva, del usuario, no se toca) y de la colección del dato, buscada por su clave;
    - el :class:`LiveHook` de su cargador, en lo que muestra el contenido de hoy, con lo que leyó
      (``live``, por su comienzo: :func:`live_reads`);
    - con ``titles`` (el título de cada dato que lo tiene, por su uid; spec 009, RF-009-22), el
      título en lugar de su nombre en el nombre generado, y con ``versions`` (el código de la
      versión de cada dato de una versión, por su uid), su código (:func:`view_name`).

    Con ``budget_s``, para en cuanto lo pasa (tras uno, como poco) y devuelve los que quedan,
    para la siguiente tanda (D-12). No escribe en el proyecto. Devuelve si cambió algo y los uid
    que quedan."""
    wanted = [uid for uid, objects in groups.items() if uid in states and objects]
    collections = _dataset_collections() if wanted else {}
    shared: Mapping[str, Any] = {} if live is None else live
    given: Mapping[str, str] = {} if titles is None else titles
    codes: Mapping[str, str] = {} if versions is None else versions
    started = time.perf_counter()
    changed = False
    for index, uid in enumerate(wanted):
        if budget_s is not None and index and time.perf_counter() - started >= budget_s:
            return changed, wanted[index:]
        view = states[uid]
        loader = None if view.record is None else loader_for(view.record.name)
        changed = _show_group(groups[uid], view, loader, collections.get(uid), shared,
                              given.get(uid) or None, codes.get(uid) or None) or changed
    return changed, []


def _mark_unbacked(uids: Collection[str]) -> bool:
    """Marca «sin respaldo en el proyecto», sin borrarlos, los objetos de los datos ``uids``
    (los de todos los proyectos); devuelve si cambió algo."""
    groups = {uid: objects for uid, objects in loaded_items().items() if uid in uids}
    states = {uid: ItemView(uid, ItemState.UNBACKED, None, False, None) for uid in groups}
    return show_view_state(groups, states)[0]


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
    version_uid: str = ""  # la versión del dato ('' del proyecto; spec 009, RF-009-30)
    companions: str = ""  # sus datos compañeros con su hash al empezar a cargarlo (T31c)


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


def _uid_texts(values: Iterable[str] | str, what: str) -> tuple[str, ...]:
    if isinstance(values, str):
        values = (values,)
    found = tuple(dict.fromkeys(values))
    for value in found:
        if not isinstance(value, str) or not value:
            raise TypeError(f"{what}: cada dato se indica por su uid, no {value!r}")
    return found


def _replacements(
        replaces: Mapping[str, str | Iterable[str]] | None) -> dict[str, tuple[str, ...]]:
    """``replaces`` de :func:`load_steps` como sucesor → lo que sustituye (uno o varios)."""
    if replaces is None:
        return {}
    if not isinstance(replaces, Mapping):
        raise TypeError(f"replaces: sucesor → sustituido, no {replaces!r}")
    return {key: _uid_texts(replaces[key], "replaces")
            for key in _uid_texts(tuple(replaces), "replaces")}


def load_steps(context: Any, project: Any, refs: Iterable[str], *, lod: int = 0,
               replaces: Mapping[str, str | Iterable[str]] | None = None,
               unbacked: Iterable[str] = (),
               clear_view_stale: bool = False) -> Generator[Progress, None, None]:
    """Los pasos que cargan en la escena de ``context`` los datos ``refs`` (uids o nombres)
    del proyecto abierto ``project`` con su cargador (RF-006-19, RF-006-29; T50: en pasos de
    décimas de segundo como mucho, para la orden desde el temporizador de su ventana, con su
    avance y Esc, RNF-006-09): cada uno da su ``Progress`` (fase :data:`LOAD_PHASE`, hecho de
    :data:`STEPS_TOTAL`, el nombre del dato) y el último, el :class:`LoadOutcome` en
    ``result``. Primero se preparan todos sin tocar la escena (los objetos, sin enlazar) y se
    leen las cifras registradas de cada dato (``core.views.card.dataset_figures``, sin marcas);
    en el último paso, de una vez, cada uno pasa a la colección de su dato con
    ``Object.geoblender`` (también el GeoOrigin del proyecto, «al día» y sus cifras en texto,
    spec 010) y su nombre generado, sustituyendo lo que hubiera de él (sin el «.001» que les
    puso Blender al crearlos mientras estaba, spec 005, T48), con el aviso de RF-002-26 si pasa
    de 8 km del GeoOrigin (:func:`scene_precision`), y después el ancla y el recorte. Cerrar
    los pasos antes del último (Esc), o un error que no es para la persona, borra lo preparado:
    la vista queda como estaba. Un dato que falta se avisa y no se carga; uno que el proyecto no
    tiene, sin cargador o que su cargador rechaza (``GeoblenderError``: otro CRS, una malla no
    válida…) es un error y los demás se cargan. No escribe nada en el proyecto.

    Para Refrescar (spec 010, RF-010-01; plan A2), en el mismo último paso: ``replaces``
    (sucesor → el uid del dato sustituido que carga en su lugar, o varios) quita lo de cada
    sustituido cuyo sucesor se cargó (antes de ponerlo: así toma su nombre); ``unbacked`` marca
    «sin respaldo en el proyecto», sin borrarlos, los objetos de esos datos; y, con
    ``clear_view_stale`` y sin errores, se quita la marca de vista desfasada de las escenas
    (RF-002-29; D-9)."""
    from ...core.provenance.view import dataset_view  # al usarlo: no al habilitar

    scene = getattr(context, "scene", None) or bpy.context.scene
    wanted = list(refs)
    swaps = _replacements(replaces)
    marked = _uid_texts(unbacked, "unbacked")
    if not isinstance(clear_view_stale, bool):
        raise TypeError(f"clear_view_stale es verdadero o falso, no {clear_view_stale!r}")
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
            owner, code, title = _dataset_label(project, record.uid)
            name = view_name(loader, record, stale=shown.stale, title=title or None,
                             version=code or None)
            entry = _Built([], loader, shown, name, version_uid=owner,
                           companions=_companions_of(project, loader, record))
            built.append(entry)
            try:
                entry.parts = yield from _parts(
                    loader.load(ViewRequest(project, record, name, lod)), index * width, width,
                    record.name)
            except GeoblenderError as error:
                LOGGER.info("No se carga «%s» en la vista: %s", record.name, error)
                errors.append(str(error))
                built.remove(entry)
        placed = [entry.shown.record.uid for entry in built
                  if entry.parts is not None and entry.loader is not None]
        figures = _figure_texts(project, placed)
        owners = _version_rows(project, {entry.version_uid for entry in built
                                         if entry.parts is not None and entry.version_uid})
    except BaseException:
        _discard(obj for entry in built if entry.parts is not None
                 for obj in entry.parts.objects)
        raise
    # El último paso, fuera del try: cerrar los pasos después de él no borra lo puesto.
    yield Progress(LOAD_PHASE, STEPS_TOTAL, STEPS_TOTAL, "",
                   _place(scene, project, built, errors, figures=figures, replaces=swaps,
                          unbacked=marked, clear_view_stale=clear_view_stale, versions=owners))


_SUFFIX = re.compile(r"(.+)\.\d{3,}")
"""Un nombre con el número que le pone Blender si ya está en uso («Sondeos [VIGENTE].001»)."""


def _unsuffixed(obj: bpy.types.Object, name: str) -> None:
    """Quita a ``obj`` y a sus datos el número que les puso Blender por crearlos mientras
    estaba lo de la carga anterior (spec 005, T48), si sin él su nombre empieza por el generado
    ``name``: quitado eso, su nombre queda libre (si otro lo usa, Blender les pone otro)."""
    for item in (obj, obj.data):
        found = None if item is None else _SUFFIX.fullmatch(item.name)
        if found is not None and found.group(1).startswith(name):
            item.name = found.group(1)


def _companions_of(project: Any, loader: Loader, record: DatasetRecord) -> str:
    """Los datos compañeros de ``record`` que declara su cargador (``Loader.companions``) con su
    hash de hoy, como los anota su objeto (``core.views.state.companions_text``; ``""`` si no
    declara ninguno). Se leen **antes** de que el cargador lea el dato: si cambian mientras tanto,
    el objeto queda «no al día» (nunca «al día» con lo que no es). Solo lee."""
    if loader.companions is None:
        return ""
    with project.read() as conn:
        found = loader.companions(conn, record)
    return companions_text((item.uid, item.content_sha256) for item in found)


def dataset_titles(project: Any, conn: sqlite3.Connection, uids: Iterable[str]) -> dict[str, tuple[str, str]]:
    """La versión (su uid; ``''``, del proyecto) y el título de cada dato de ``uids`` (``core.versions.read.dataset_titles``) y, **en los que no tienen título**, el nombre propio que declara su
    cargador (:data:`OwnTitleReader`; spec 018, T40e, H3-6: el TIN de una corta se llama como la corta). El título que dio la persona manda siempre. Solo lee."""
    marks = versions_read.dataset_titles(conn, uids)
    bare = [uid for uid, (owner, title) in marks.items() if owner and not title]
    if not bare or not any(loader.own_title is not None for loader in _LOADERS.values()):
        return marks
    for uid in bare:
        row = conn.execute("SELECT name FROM gb_dataset WHERE uid = ?", (uid,)).fetchone()
        loader = None if row is None else loader_for(str(row[0]))
        if loader is None or loader.own_title is None:
            continue
        try:
            own = loader.own_title(project, conn, marks[uid][0], str(row[0]))
        except (GeoblenderError, sqlite3.Error, ValueError):
            LOGGER.debug("No se pudo leer el nombre propio de «%s»", row[0], exc_info=True)
            continue
        if own:
            marks[uid] = (marks[uid][0], own)
    return marks


def _dataset_label(project: Any, uid: str) -> tuple[str, str, str]:
    """La versión (su uid y su código; '' del proyecto) y el título ('' sin él) del dato
    ``uid`` del proyecto abierto ``project`` (spec 009, T22; ``core.versions.read``; el
    nombre propio de su cargador, si no tiene título: :func:`dataset_titles`). No
    escribe."""
    with project.read() as conn:
        owner, title = dataset_titles(project, conn, [uid]).get(uid, ("", ""))
        version = versions_read.version(conn, owner) if owner else None
    return owner, "" if version is None else version.code, title


def _version_rows(project: Any, uids: Collection[str]) -> dict[str, tuple[Any, Any]]:
    """De cada versión ``uids`` del proyecto abierto ``project``, su ``Version`` y la revisión
    que se enseña con ella (la abierta o, si ya no tiene, la última; ``None`` sin ninguna): lo
    que nombra la colección de su versión (spec 009, RF-009-30). No escribe."""
    if not uids:
        return {}
    with project.read() as conn:
        found = {version.uid: version for version in versions_read.versions(conn)
                 if version.uid in uids}
        latest = versions_read.latest_revisions(conn)
    return {uid: (version, latest.get(uid)) for uid, version in found.items()}


def _restore_look(objects: Sequence[bpy.types.Object]) -> None:
    """Lo guardado del aspecto, a lo recién puesto en la escena (spec 019, T14; ADR-0033 punto 4: manda la tabla), en el
    mismo gesto y sin crear versión. Solo lee; un fallo no para la carga."""
    from . import appearance  # al usarlo: appearance usa la sesión del proyecto

    try:
        appearance.restore(objects)
    except Exception:  # noqa: BLE001 - la vista ya está en la escena; sin aspecto guardado queda el predefinido
        LOGGER.exception("No se pudo aplicar el aspecto guardado a la vista")


def _place(scene: Any, project: Any, built: Sequence[_Built], errors: Sequence[str], *,
           figures: Mapping[str, Sequence[FigureText]],
           replaces: Mapping[str, Sequence[str]], unbacked: Sequence[str],
           clear_view_stale: bool,
           versions: Mapping[str, tuple[Any, Any]] | None = None) -> LoadOutcome:
    """El último paso de :func:`load_steps`: lo preparado, a la escena (véase allí); un dato de
    una versión, en la colección de su versión (``versions``: la ``Version`` y la revisión que
    se enseña con ella, por su uid; spec 009, RF-009-30). Avisa una sola vez de que cambió la
    vista (:func:`_view_changed`), al final, también si se para a medias tras quitar o poner
    algo."""
    owners: Mapping[str, tuple[Any, Any]] = {} if versions is None else versions
    loaded: list[str] = []
    labels: list[str] = []
    placed: set[str] = set()
    objects: list[bpy.types.Object] = []
    notes: list[str] = []
    lows: list[np.ndarray] = []
    highs: list[np.ndarray] = []
    gone: list[str] = []
    removed = 0
    origin = origin_text(project.origin)
    try:
        for entry in built:
            notes.extend(entry.notes)
            parts, loader, shown = entry.parts, entry.loader, entry.shown
            if parts is None or loader is None:
                continue
            record = shown.record
            # Otro nivel de detalle, el dato al día o lo que sustituye (spec 010): fuera antes
            # de ponerlo, para que tome su nombre.
            removed += _unload([record.uid, *replaces.get(record.uid, ())])
            collection = ensure_collection(loader.kind, record, name=entry.name, scene=scene,
                                           version=owners.get(entry.version_uid))
            texts = figures.get(record.uid, ())
            for obj in parts.objects:
                _unsuffixed(obj, entry.name)
                collection.objects.link(obj)
                _mark(obj, loader.kind, shown, project, origin, texts, entry.companions)
                remember(obj)
            loaded.append(record.name)
            owner = owners.get(entry.version_uid)
            labels.append(record.name if owner is None else f"{record.name} · {owner[0].code}")
            placed.add(record.uid)
            objects.extend(parts.objects)
            notes.extend(parts.notes)
            far = scene_precision(parts, project.origin)
            if far is not None and not far.within_limit:
                notes.append(tr("«{name}» in the view: {warning}", name=record.name,
                                warning=far.message))
            if parts.bounds is not None:
                lows.append(np.asarray(parts.bounds[0], dtype=np.float64))
                highs.append(np.asarray(parts.bounds[1], dtype=np.float64))
        if objects:
            _restore_look(objects)
        if loaded:
            ensure_anchor(project, scene)
        if lows:
            fit_clip(np.min(lows, axis=0), np.max(highs, axis=0))
        gone = [uid for uid in unbacked if uid not in placed]
        if gone:
            _mark_unbacked(gone)
        if clear_view_stale and not errors:
            georef.clear_stale()  # y pide redibujar: el panel Proyecto (spec 009, T43)
    finally:
        if loaded or gone or removed:
            _view_changed()
    return LoadOutcome(tuple(loaded), tuple(objects), tuple(notes), tuple(errors),
                       tuple(labels))


# --- Lo que escucha la vista (spec 010, T21) -------------------------------------------------


def add_view_listener(listener: ViewListener) -> None:
    """Apunta ``listener`` para que se llame, sin argumentos, cada vez que se carga o se
    descarga algo de la vista (desde una orden, un menú o un guion: :func:`load_steps`,
    :func:`load_datasets`, :func:`unload_datasets`), una vez por carga o descarga y justo
    después de su petición de la marca en vivo (``bl.scene.live.request``: una más en
    ``live.view_generation``). Es del inventario de N ▸ Proyecto (``bl.ui.view_panels``): su
    columna «En la escena» se pone al día sin volver a leer el proyecto (RF-010-07). Si ya
    estaba, nada."""
    if listener not in _VIEW_LISTENERS:
        _VIEW_LISTENERS.append(listener)


def remove_view_listener(listener: ViewListener) -> None:
    """Quita ``listener``; si no estaba, nada."""
    if listener in _VIEW_LISTENERS:
        _VIEW_LISTENERS.remove(listener)


def view_listeners() -> tuple[ViewListener, ...]:
    """Lo apuntado con :func:`add_view_listener`, por orden."""
    return tuple(_VIEW_LISTENERS)


def _view_changed() -> None:
    """Lo cargado o descargado cambia lo que no está al día y lo que está en la escena: pide la
    marca en vivo del proyecto de la sesión (``bl.scene.live.request``, spec 010, T08), que lo
    cuenta otra vez (control 7) desde su temporizador, y después llama a lo apuntado con
    :func:`add_view_listener` (spec 010, T21). No lee nada; una escucha que falla va al
    registro técnico y no para lo demás."""
    from . import live, project_session  # al usarlo: live importa este módulo

    live.request(project_session.current())
    for listener in tuple(_VIEW_LISTENERS):
        try:
            listener()
        except Exception:  # noqa: BLE001 - lo cargado o descargado ya está en la escena
            LOGGER.exception("Falló una escucha de lo cargado en la vista")


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
    cuántos objetos quitó. No toca el proyecto; si quitó algo, pide la marca en vivo y avisa
    a lo apuntado con :func:`add_view_listener`."""
    count = _unload(uids)
    if count:
        _view_changed()
    return count


def _unload(uids: Iterable[str]) -> int:
    """Lo de :func:`unload_datasets` sin avisar de que cambió la vista (lo hace quien lo
    llama, una vez: :func:`_place`)."""
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

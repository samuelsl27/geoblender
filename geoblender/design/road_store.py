# SPDX-License-Identifier: GPL-3.0-or-later
"""Preparar la pista —lo que se lee y se rechaza **antes de calcular**— (spec 017, T19; HU-017-1 y HU-017-2; RF-017-01 a RF-017-06; RF-015-06, RF-015-07, RF-015-08 y RF-015-09;
plan 017 §5.1, §5.2.1 a §5.2.3, §5.3.1, §5.7 P-1, P-5 y P-14; D-3, D-13 y D-16).

El homólogo, para la pista (``des.road``: una entidad **con cadena**, ``RDW-001``: una red de pistas es una cadena y cada ramal parte de la superficie que deja la anterior, D-16),
de ``design.entity_store.prepare_platform_units``: **solo lee**. Nada se escribe en el proyecto (RF-015-03) salvo las máscaras de la versión si no estaban al día (una operación
propia, RF-013-04, y solo si no se dan cargadas). **Calcular por pasos** (:func:`road_compute_steps`, T20 (a): la orquestación por modos, las cifras de RF-017-23 y el ``RoadOutcome``, sin proyecto
y sin escribir nada); **el resumen, las dos confirmaciones y con qué se compara** (T20b: :func:`road_summary` y :func:`summary_of`, :func:`carriageway_notices`, :func:`road_held_notices`,
:func:`check_road_confirmed` y :class:`RoadConfirmed`, :func:`road_previous` y :func:`road_obsolete`; la ``Calculation`` es ``design.steps.road_run``); **crear** (T21: :func:`create_road_steps` y :func:`create_road`, con lo que guarda —:func:`road_entity_rows`, :func:`road_axis_rows`,
:func:`road_report_rows` y :func:`road_geometry_sha256`, funciones puras del resultado— y lo que anota la operación, :func:`road_operation_start`); **recalcular** (T22: :func:`run_road` y
:func:`recompute_road`, con lo confirmado que arrastra y los otros diseños que anota al completarla y, desde la T24b, **las cotas de inicio y de fin derivadas, que se vuelven a derivar de su origen**:
:func:`resolve_level`, :class:`LevelFollow` y :func:`write_followed`) y **reproducir** (T22: lo que lee de lo congelado, :func:`frozen_profile` y
:func:`frozen_geometry`; la función de reproducir es ``design.reproduce.reproduce_road``); traer a otra versión y «Cambiar parámetro…», de la T22b; los modos «sobre un eje» y «eje 3D», de la T23: la línea con su Z de una línea de rotura o de la capa propuesta
(:class:`Lines3D`, :func:`read_layer_3d`, :func:`read_lines_3d` y :func:`line_3d`), la Z de cada estación en la abscisa de la línea y el radio de su planta medido en las estaciones
(``road_axis.plan_of_line``, ``road_gradient.check_axis_3d``); **«Proponer el trazado»** (T27, al final: ``des.road_propose``, la ruta y la rasante de «trazar» sin la sección, como una capa de líneas con Z editable
en QGIS, ``des_rpl_``: :func:`prepare_propose_units`, :func:`propose_compute_steps`, :func:`create_propose_steps`, :func:`run_propose` y :func:`recompute_propose`).

- :func:`prepare_road_units` y :func:`prepare_road` (de una vez): la versión editable (RF-009-21), el código ``RDW-nnn`` y el nombre únicos, **la partida** (RF-017-05, D-3: la persona
  la elige; sin ella, :func:`default_start`: la de explotación de la cantera de la 014 de la versión y, si no, la última de la cadena de entidades) con la cadena (una pista por
  superficie y sin ciclos: ``des.entity_start_taken``), **la geometría de origen por modo** (RF-017-02): en «trazar», el origen —un punto de la capa de puntos del proyecto, por su
  ``fid`` o su nombre, o un punto del eje de otra pista, ``RDW-001@s``— y el destino —un punto de la capa, **un punto de la capa que cae en la huella de una entidad** (T19-c,
  ``entity:PLT-001``) o una cota con su zona (un polígono de una capa: ``capa:nombre``) y su tolerancia: la rampa, D-4—; en «sobre un eje», la línea de su capa (una parte, sin cortarse,
  sin longitud cero ni vértice repetido); el perfil de la versión (:class:`~.road_profiles.RoadProfile`) con sus rechazos; **las cotas de inicio y de fin** (D-13: las del usuario, que
  no pueden salirse de las del terreno ± 1.000 m, o las de la superficie de partida en esos puntos, las del eje de otra pista o las de la entidad de destino, **anotadas con su
  origen**), los parámetros resueltos **sin valor por defecto** (RF-015-08: uno que falta se rechaza nombrando capa, pista, campo y valor) y las máscaras de la versión por el contrato
  de la 012 (RF-017-06, RF-015-06: el corte y el relleno admitidos, lo intocable y el peso de «preferible no afectar»), con **la búsqueda de intocables** de los sectores
  (RF-015-07: ``refuse_pending`` **se llama aquí**, nada lo hace solo) y las **dependencias «se apoya en» declaradas** (RF-017-03, RF-015-15: el eje de otra pista y la entidad de
  destino, con la superficie y la huella de cada una como entradas). Da una :class:`PreparedRoad`: el ``RoadJob`` listo para calcular (todo lo leído y nada del proyecto), la
  ``OperationStart`` (ajustes, entradas y parámetros), las filas de los parámetros de la entidad y los avisos de la partida (RF-017-05 (a)). **Los rechazos de RF-017-04** salen aquí,
  antes de calcular y sin escribir nada.
- Los avisos de RF-017-05: (a) :func:`start_is_final_notice` —«no llega al fondo»: la cota mínima alcanzable desde el origen sobre la final restaurada y sobre la de explotación, con la
  pendiente de diseño y la calzada del perfil (T19-a)— se calcula al preparar, porque solo depende de la partida; (b) :func:`other_design_notices` —la partida difiere en más del espesor
  mínimo de la 012 de la de otro diseño de la versión que no parte de ella (:func:`other_designs`, T19-b) **en la huella de la pista**— necesita la huella, que sale del cálculo: lo
  llama :func:`road_compute_steps` con ella (T20).

Python puro (nivel 8), con numpy. ``design.road_store`` es un módulo pesado de la 017: lo importan las órdenes al usarlo, no ``bl`` al registrarse
(``tests/unit/architecture/test_lazy_registration.py``).
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections.abc import Callable, Generator, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any, NamedTuple

import numpy as np

from ..core.datasets import registry as dataset_registry
from ..core.datasets.model import DatasetStatus
from ..core.errors import GeoblenderError
from ..core.gpkg.wkb import decode_geometry
from ..core.params import PROJECT_SCOPE, VERSION_SCOPE, ParameterRecord, ParameterStore, SourceKind, definition
from ..core.params.store import default_reason
from ..core.project.model import Progress
from ..core.provenance import stale
from ..core.provenance.operations import OperationHandle, OperationStatus, Use
from ..core.provenance.recompute import RecomputeRequest
from ..core.timeutil import format_utc
from ..core.versions import read as versions_read
from ..core.versions.model import Version
from ..gis.grid import Grid
from ..gis.masks import access
from ..gis.masks.combine import ClassBit
from ..gis.messages import GisError
from ..gis.provenance import BREAKLINES as _BREAKLINES
from ..gis.provenance import FAMILIES_BY_CODE as _GIS_FAMILIES
from ..gis.provenance import FEATURES as _FEATURES
from ..gis.raster import Raster
from ..gis.store import StoreProject, load_features
from ..gis.vector import FeatureLayer, FieldColumn, column_type, feature_parts
from . import (
    edges,
    entities,
    entity_store,
    pipeline,
    provenance,
    road_access,
    road_axis,
    road_engrave,
    road_gradient,
    road_layer,
    road_net,
    road_profiles,
    road_route,
    road_section,
)
from .compose import admitted_pair
from .entities import EntityKind, EntityRegistry, EntityState
from .entity_store import EntityParamRow
from .messages import DesignError
from .model import DECLARED_PREFIX
from .params import (
    VERIFY_MIN_THICKNESS,
    WARNING_RATIO,
    RoadParam,
    RoadProfileParam,
    check_entity_param,
    entity_key,
    entity_params,
    road_profile_key,
)
from .platform import QuarryOrder, _project_number, _window_grid, magnitude_notices
from .preview import (
    _INNER,
    Named,
    Notice,
    Obsolete,
    ObsoleteKind,
    RoadAsk,
    RoadPoint,
    RoadPreview,
    RoadSummary,
    _listed_names,
    _resting_units,
    _rule,
    gradient_stretches,
    held_notices,
    obsolete_notices,
    section_edges,
    zone_rings,
)
from .report import Previous, _thickness
from .road_model import (
    AccessJob,
    AccessRequest,
    EntryPoint,
    LayerFields,
    LevelDestination,
    ProposalOutcome,
    RoadGeometry,
    RoadJob,
    RoadMode,
    RoadOutcome,
    RoadRequest,
    RouteParams,
    RouteReport,
)
from .sectors import design_sectors, refuse_pending
from .seeds import pace_progress, sector_layout
from .store import DesignWriter, OperationStart, Stored, _LateSupports, _loaded_masks, _real, _seen, _start, _store_steps, require_version
from .stockpiles import runs_cells
from .surfaces import project_frame, read_surface_steps, read_surface_window
from .zones import polygons_cells

__all__ = [
    "COMPUTE_PHASE",
    "CONFIRMED",
    "PROPOSE_CODE",
    "AxisReference",
    "DefaultStart",
    "DerivedLevel",
    "EntityReference",
    "LevelFollow",
    "Lines3D",
    "OtherReader",
    "PointReference",
    "PreparedProposal",
    "PreparedRoad",
    "ResolvedLevel",
    "RoadConfirmed",
    "avoid_weight",
    "axis_point_at",
    "carriageway_notices",
    "check_road_confirmed",
    "confirmed_of",
    "create_propose",
    "create_propose_steps",
    "create_road",
    "create_road_steps",
    "default_start",
    "frozen_geometry",
    "frozen_profile",
    "line_3d",
    "other_design_notices",
    "other_designs",
    "other_reader",
    "parse_reference",
    "prepare_propose",
    "prepare_propose_units",
    "prepare_road",
    "prepare_road_units",
    "preview_road_units",
    "read_layer_3d",
    "propose_compute_steps",
    "propose_layer_rows",
    "read_lines_3d",
    "recompute_propose",
    "recompute_road",
    "resolve_level",
    "road_axis_rows",
    "road_compute_steps",
    "road_confirmation",
    "road_entity_rows",
    "road_geometry_sha256",
    "road_held_notices",
    "road_obsolete",
    "road_operation_start",
    "road_previous",
    "road_report_rows",
    "road_summary",
    "road_values",
    "run_propose",
    "run_road",
    "start_is_final_notice",
    "summary_of",
    "untouchable_cells",
    "write_followed",
]

_KINDS_ES = MappingProxyType({"point": "puntos", "line": "líneas", "polygon": "polígonos"})
_NUMERIC = frozenset({"INTEGER", "DOUBLE"})
_NAME_FIELDS = ("nombre", "name")
_DIALOG = "diálogo de «Pista…»"
"""El origen de lo que elige la persona en el diálogo de la orden (la entidad al final)."""
_START_ROLE = "superficie de partida"
_PIT_ROLE = "superficie de explotación de la cantera"
_ENTITY_ROLE = "superficie de la entidad de destino"
_LEVEL_LIMIT_M = 1000.0
"""RF-017-04: una cota de inicio o de fin no puede salirse de las del terreno en más de esto (m)."""
_LIVE_STATES = (EntityState.CURRENT, EntityState.STALE, EntityState.SUPPORT_REMOVED)
"""Los estados de una entidad **viva y calculada**: lo único en lo que se puede apoyar una pista (RF-015-15)."""
_MISSING_SUPPORT = "no existe en la versión, no está calculada o se descartó"
_SECTION_COLUMNS = "station_m, x, y, terrain_m, level_m"
_AXIS_REFERENCE = entities.AXIS_REFERENCE
_FEATURE_PREFIX = _GIS_FAMILIES[_FEATURES].prefix
"""El comienzo del nombre de una capa de entidades del proyecto (``gis_fea_``: guarda solo X e Y)."""
_LINES_3D_PREFIXES = (_GIS_FAMILIES[_BREAKLINES].prefix, provenance.FAMILIES_BY_CODE[provenance.ROUTE_LAYER_TABLE].prefix)
"""Las capas que dan la Z de una línea en el modo «eje 3D» (T23-a): las líneas de rotura (``gis_brk_``) y la capa propuesta de «Proponer el trazado…» (``des_rpl_``)."""
_ROUTE_PREFIX = provenance.FAMILIES_BY_CODE[provenance.ROUTE_LAYER_TABLE].prefix
"""El comienzo del nombre de la capa propuesta (``des_rpl_``): un dato **de una versión**, no del proyecto."""
_LINE_NAME_FIELD = "line_id"
"""El campo del nombre de una línea de rotura (``gis_brk_``): lo que identifica una línea en su capa si la persona no elige otro campo."""
_ROUTE_PARAMS = (RoadParam.MESH, RoadParam.LEVEL_STEP, RoadParam.MAX_CUT_FILL, RoadParam.LAMBDA, RoadParam.TURN, RoadParam.MARGIN, RoadParam.SIMPLIFY, RoadParam.ARRIVAL_TOL,
                 RoadParam.SEARCH_BUDGET)
"""Los parámetros de la ruta (solo los lee el modo «trazar», P-14)."""


# --- Lo que se prepara --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class PreparedRoad:
    """Lo que se lee y se comprueba antes de calcular una pista (:func:`prepare_road_units`): el ``job`` (``design.road_model.RoadJob``: todo lo leído y nada del proyecto), lo que anotará
    la operación (``start``: su tipo ``des.road``, sus ajustes, entradas y parámetros), el ``code`` de la entidad (``RDW-001``, correlativo por versión), la ``version`` (la editable),
    el nombre del dato de la superficie de partida (``start_surface``) y lo que dice su parámetro ``start`` (``start_ref``: el nombre de un dato o ``entity:<código>``), el de la de
    apoyo (``support_surface``; ``None`` sin ella), la capa de origen (``layer``), el ``profile`` (el perfil de pista de la versión, ya comprobado), las ``rows`` de los parámetros de
    la entidad —**todas** las que lee la operación: sin su fila, ``begin_operation`` crearía la del valor por defecto en el proyecto, trampa de la T04 de la 015— y sus ``values``
    resueltos y comprobados (por último segmento de su clave), los parámetros del proyecto que lee el cálculo (``common``: la tolerancia de cara, el umbral de magnitud, el espesor
    mínimo y el salto creado), los códigos de las entidades en que **se apoya** (``supports``: el eje de otra pista del origen y la entidad de destino; RF-017-03), los nombres de los
    datos de **otros diseños** de la versión que no parten de la partida (``others``, T19-b: con los que compara el aviso de RF-017-05 (b) la T20, cuando tiene la huella) y los
    ``notices`` de la partida (RF-017-05 (a), que no impiden crearla). ``existing``: la entidad ya estaba en su versión (se preparó con su ``code``: recalcularla), así que «Crear» no
    escribe otra vez sus parámetros salvo ``followed``. ``fid``: el de la geometría de la capa de la que sale la pista (la línea de «sobre un eje» y «eje 3D»; en «trazar», el primer punto de la capa que usa, el origen
    o, si este es el eje de otra pista, el destino; 0 si ninguno es de la capa): lo que lleva ``des_epr_`` (``source_fid``). ``followed`` (T24b; RF-017-03, D-13): las cotas de inicio y de fin que la pista
    **vuelve a tomar de su origen** al recalcularla porque la fila las anotó como «algoritmo» y la cota de ahora es otra (:class:`LevelFollow`); ya van en ``values``, y quien crea o recalcula las
    escribe (:func:`write_followed`) antes de abrir la operación, para que anote la revisión nueva."""

    job: RoadJob
    start: OperationStart
    code: str
    version: Version
    start_surface: str
    start_ref: str
    support_surface: str | None
    layer: str
    profile: road_profiles.RoadProfile
    rows: tuple[EntityParamRow, ...]
    values: Mapping[str, Any]
    common: Mapping[str, float]
    supports: tuple[str, ...] = ()
    others: tuple[str, ...] = ()
    notices: tuple[Notice, ...] = ()
    existing: bool = False
    fid: int = 0
    followed: tuple[LevelFollow, ...] = ()

    @property
    def op_type(self) -> str:
        """El tipo de la operación (``des.road``)."""
        return self.start.op_type

    @property
    def version_uid(self) -> str:
        """El uid de la versión de la pista: lo que reciben ``design_writer`` y ``set_entity_params``."""
        return self.version.uid


# --- Las cotas que siguen a su origen (spec 017, T24b; RF-017-03, D-13, RF-015-01) -----------------------------------------------------------------------------------------------------------


_LEVEL_EPS_M = 1e-9
"""Lo que puede pasar una cota nueva de la guardada y seguir siendo la misma (m): el ruido de la última cifra, no un cambio."""
_LEVEL_WORD = MappingProxyType({RoadParam.START_LEVEL.value: "inicio", RoadParam.END_LEVEL.value: "fin"})


class DerivedLevel(NamedTuple):
    """Una cota que da hoy el origen (D-13): la superficie de partida en el punto, la rasante del eje de otra pista a esa abscisa o la superficie de la entidad de destino en ese punto. ``value``, la cota (m);
    ``text``, su origen como se anota en la fila del parámetro; ``target``, lo que se nombra al decir de dónde se vuelve a tomar (``«P1» (PLT-001)``: solo nombres, vale en los dos idiomas)."""

    value: float
    text: str
    target: str


@dataclass(frozen=True, slots=True)
class LevelFollow:
    """Una cota que la pista **vuelve a tomar de su origen** al recalcularla (T24b; RF-017-03, D-13): ``param`` (``START_LEVEL`` o ``END_LEVEL``), la de antes (``old_m``), la de ahora (``new_m``), su origen
    como se anota en la fila (``source``) y de dónde se vuelve a tomar (``target``)."""

    param: RoadParam
    old_m: float
    new_m: float
    source: str
    target: str

    def notice(self, entity: str) -> Notice:
        """El aviso del resumen (``des.road_start_level_followed`` o ``des.road_end_level_followed``): la pista ``entity``, la cota de antes y la de ahora y de dónde se vuelve a tomar."""
        code = "des.road_start_level_followed" if self.param is RoadParam.START_LEVEL else "des.road_end_level_followed"
        return Notice(code, {"entity": entity, "old": self.old_m, "new": self.new_m, "source": self.target})

    def reason(self, entity: str) -> str:
        """El motivo con que se anota el cambio en la fila del parámetro (RF-008-02): la cota, de cuánto a cuánto y de dónde, en español, a la centésima."""
        old, new = (f"{value:.2f}".replace(".", ",") for value in (self.old_m, self.new_m))
        return f"La cota de {_LEVEL_WORD[self.param.value]} de la pista «{entity}» pasa de {old} a {new} m: se vuelve a tomar de {self.target}, que cambió"


@dataclass(frozen=True, slots=True)
class ResolvedLevel:
    """La cota de inicio o de fin que usa la pista (:func:`resolve_level`): su valor (``value_m``; ``None`` si no hay), el origen que se anota en su fila (``origin``: su texto y su clase, ``algorithm``; ``None``
    si la cota la dio la persona o no sale de ningún origen) y, si la pista la volvió a tomar de su origen y cambió, ``follow``."""

    value_m: float | None
    origin: tuple[str, str] | None
    follow: LevelFollow | None


def resolve_level(param: RoadParam, asked_m: float | None, kind: str | None, derived: DerivedLevel | None) -> ResolvedLevel:
    """La cota de inicio o de fin ``param`` de una pista (D-13, RF-017-03; **pura**: lo que dice la fila, lo pedido y lo que da hoy el origen). ``asked_m``: la cota de la petición (la de la fila del parámetro al
    recalcular, la que da la persona al crear; ``None`` si no hay); ``kind``: el origen **anotado** en su fila (``source_kind``; ``None`` al crear, que aún no tiene fila); ``derived``: la que da hoy su origen
    (``None`` si no hay origen que la dé: el destino por cota, «eje 3D»).

    Sin cota pedida, la del origen con su procedencia (como al crear). Con ella, **solo la que anotó el algoritmo** (``algorithm``: lo que derivó el código) se vuelve a tomar de su origen —de modo que si
    cambia la plataforma de destino, el eje de la otra pista o la superficie de partida, la pista la sigue—; si cambió, ``follow`` lo dice. **Las demás se conservan**: la que dio la persona (``person``) y la
    que anotó un documento, una norma o una cifra adoptada (``document``, ``standard``, ``operation``), que no las derivó el código."""
    if derived is None:
        return ResolvedLevel(asked_m, None, None)
    origin = (derived.text, SourceKind.ALGORITHM.value)
    if asked_m is None:
        return ResolvedLevel(derived.value, origin, None)
    if kind != SourceKind.ALGORITHM.value:
        return ResolvedLevel(asked_m, None, None)
    if abs(asked_m - derived.value) <= _LEVEL_EPS_M:
        return ResolvedLevel(asked_m, origin, None)
    return ResolvedLevel(derived.value, origin, LevelFollow(param, asked_m, derived.value, derived.text, derived.target))


def _level_kinds(project: StoreProject, version: Version, code: str) -> dict[str, str]:
    """El origen anotado (``source_kind``) de las filas de las cotas de inicio y de fin de la pista ``code`` en su versión (T24b; D-13): lo único que decide cuáles se vuelven a derivar al recalcular. Una
    cota sin fila o sin valor no sale. Solo lee."""
    store = ParameterStore(project)
    found: dict[str, str] = {}
    with project.read() as conn:
        for param in (RoadParam.START_LEVEL, RoadParam.END_LEVEL):
            record = store.get(entity_key(code, param), version=version.uid, conn=conn)
            if record is not None and record.value is not None:
                found[param.value] = str(record.source_kind)
    return found


def write_followed(project: StoreProject, prepared: PreparedRoad, *, decided_by: str | None = None, conn: sqlite3.Connection | None = None) -> tuple[ParameterRecord, ...]:
    """Escribe las cotas que la pista ``prepared`` vuelve a tomar de su origen (``prepared.followed``; T24b; RF-017-03, D-13): el valor nuevo de cada una en la fila de la versión, con **su origen** (la clase
    ``algorithm`` y el texto del origen de ahora), el decisor ``decided_by`` (por defecto, quien tiene abierto el proyecto) y su motivo (:meth:`LevelFollow.reason`), con su historial. Lo llama quien
    recalcula **antes de abrir la operación** (:func:`run_road`) o en la transacción que la abre (:func:`create_road_steps`, ``before_begin``): la operación anota la revisión nueva y lo congelado se
    reproduce con ella. Con ``conn``, en la transacción de quien llama; si no, en una propia. Sin nada que seguir, no escribe nada. Devuelve las filas escritas."""
    if not prepared.followed:
        return ()
    store = ParameterStore(project)
    who = entity_store._decider(decided_by, project)
    name = prepared.job.request.name

    def write(target: sqlite3.Connection) -> tuple[ParameterRecord, ...]:
        return tuple(store.change(target, entity_key(prepared.code, item.param), value=item.new_m, source=item.source, source_kind=SourceKind.ALGORITHM.value, decided_by=who,
                                  reason=item.reason(name), version=prepared.version_uid) for item in prepared.followed)

    if conn is not None:
        return write(conn)
    with project.write_transaction() as writing:
        return write(writing)


# --- Las referencias del origen y del destino ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class PointReference:
    """Un punto de la capa de la pista, por su nombre o su ``fid`` (como texto)."""

    name: str


@dataclass(frozen=True, slots=True)
class AxisReference:
    """Un punto del eje de otra pista: la pista (``code``, ``RDW-001``) y la abscisa (``station_m``, m)."""

    code: str
    station_m: float


@dataclass(frozen=True, slots=True)
class EntityReference:
    """Una entidad de la versión (``entity:PLT-001``): el destino es el punto de la capa que cae en su huella (T19-c)."""

    code: str


def parse_reference(text: str) -> PointReference | AxisReference | EntityReference:
    """Lo que dice el texto del origen o del destino de una pista (RF-017-02, RF-017-03): ``RDW-001@100,5`` es el eje de otra pista a la abscisa 100,5 m (con coma o con punto);
    ``entity:PLT-001``, una entidad de la versión; lo demás, un punto de la capa por su nombre o su ``fid``. :class:`TypeError` si no es un texto."""
    if not isinstance(text, str):
        raise TypeError(f"el origen o el destino de una pista es un texto, no {text!r}")
    wanted = text.strip()
    found = _AXIS_REFERENCE.fullmatch(wanted)
    if found is not None:
        return AxisReference(found["code"], float(found["station"].replace(",", ".")))
    code = entities.ref_code(wanted)
    if code is not None:
        return EntityReference(code)
    return PointReference(wanted)


def axis_point_at(stations: np.ndarray, station_m: float) -> tuple[float, float, float] | None:
    """El lugar absoluto ``(x, y)`` y la cota de la rasante (m) del eje de una pista a la abscisa ``station_m`` (RF-017-03), por interpolación lineal entre sus estaciones
    (``stations``: una fila por estación, ``[abscisa, x, y, cota del terreno, cota de la rasante]`` en el orden de la abscisa; exacta en una recta). ``None`` si la abscisa queda
    antes del origen o más allá de su longitud."""
    table = np.asarray(stations, dtype=np.float64)
    if table.ndim != 2 or table.shape[1] < 5 or table.shape[0] < 1:
        raise ValueError("las estaciones de un eje son una tabla (n, 5): abscisa, x, y, cota del terreno y cota de la rasante")
    s = float(station_m)
    if not (float(table[0, 0]) <= s <= float(table[-1, 0])):
        return None
    return (float(np.interp(s, table[:, 0], table[:, 1])), float(np.interp(s, table[:, 0], table[:, 2])), float(np.interp(s, table[:, 0], table[:, 4])))


# --- La partida por defecto (RF-017-05, D-3) ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class DefaultStart:
    """La partida que propone el diálogo (RF-017-05, D-3): ``ref`` (el nombre del dato de la superficie de explotación, o ``entity:<código>`` de la última de la cadena), de qué
    viene (``kind``: ``exploitation`` o ``chain_tail``), ``name`` (el nombre que se enseña: el del dato o el de la entidad) y ``conflict`` (el nombre de la entidad que **ya parte**
    de ella —de cada superficie parte una sola—, ``None`` si está libre)."""

    ref: str
    kind: str
    name: str
    conflict: str | None = None


def default_start(project: StoreProject, version: Version) -> DefaultStart | None:
    """La partida por defecto de una pista en la versión ``version`` (RF-017-05, D-3): **la superficie de explotación de la cantera de la 014** si la versión la tiene viva, al día y es
    una sola (``des_exp_<cantera>``; una cantera obsoleta no cuenta) y, si no hay ninguna, **la última de la cadena de entidades** (``entities.chain_tails``: la que deja una entidad calculada y viva) si es una sola;
    con la partida, la entidad que ya parte de ella (``conflict``). ``None`` si no hay candidata o hay varias (no se elige una por la persona). Solo lee."""
    registry = entities.registry(project, version.uid)
    prefix = provenance.FAMILIES_BY_CODE[provenance.EXPLOITATION_GRID].prefix
    with project.read() as conn:
        found = [str(name) for uid, name in conn.execute("SELECT uid, name FROM gb_dataset WHERE version_uid = ? AND status = ? ORDER BY name",
                                                         (version.uid, DatasetStatus.CURRENT.value)).fetchall()
                 if str(name).startswith(prefix) and not stale.item_causes(conn, "dataset", str(uid))]
    if len(found) == 1:
        taken = entities.start_conflict(registry.records, found[0])
        return DefaultStart(found[0], "exploitation", found[0], None if taken is None else taken.name)
    if found:
        return None
    tails = [tail for tail in entities.chain_tails(registry.records) if tail.state not in (EntityState.UNCALCULATED, EntityState.DISCARDED)]
    if len(tails) != 1:
        return None
    ref = entities.surface_ref(tails[0].code)
    taken = entities.start_conflict(registry.records, ref)
    return DefaultStart(ref, "chain_tail", tails[0].name, None if taken is None else taken.name)


def _entity_object(code: str, name: str) -> str:
    """El objeto de un rechazo sobre la pista de código ``code`` y nombre ``name`` (``Pista «X»``)."""
    return entity_store._entity_object(code, name)


def _start_dataset(registry: EntityRegistry, version: Version, name: str, code: str, ref: str, param: RoadParam) -> str:
    """El nombre del dato de la superficie ``ref`` de la pista (``start`` o ``support``): el nombre de una superficie, tal cual; ``entity:<código>``, la de esa entidad
    (``des_psf_<nombre>``), que ha de estar calculada y no descartada (``des.entity_start_unknown``)."""
    target = entities.ref_code(ref)
    if target is None:
        return ref
    entry = registry.get(target)
    if entry is None or entry.record.state in (EntityState.UNCALCULATED, EntityState.DISCARDED):
        raise DesignError("des.entity_start_unknown", obj=_entity_object(code, name), field=entity_key(code, param), value=ref, entity=name, version=version.code)
    return provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, entry.record.name)


def _identify(project: StoreProject, version: Version, request: RoadRequest, code: str | None) -> tuple[str, EntityRegistry]:
    """El código de la pista (``code`` si se da: una entidad que ya está en la versión; si no, el siguiente ``RDW-nnn``) y el registro de las entidades de la versión, tras comprobar
    que su nombre es único (RF-015-01: ``des.entity_name_repeated``)."""
    registry = entities.registry(project, version.uid)
    chosen = code if code is not None else entities.next_code(EntityKind.ROAD, (entry.record.code for entry in registry))
    entity_store._check_name(registry, request.name, chosen, version.code)
    return chosen, registry


def _reject(error: str, request: RoadRequest, code: str, param: RoadParam | str, value: object, **values: object) -> DesignError:
    """El rechazo ``error`` de la pista ``request`` (código ``code``) por el valor ``value`` del parámetro ``param``: nombra la capa, la pista, el campo y el valor (RF-017-04)."""
    return DesignError(error, obj=f"Pista «{request.name}» de la capa «{request.layer}»", field=entity_key(code, param), value=value, layer=request.layer, entity=request.name,
                       **values)


# --- La capa y su geometría ---------------------------------------------------------------------


def _layer(project: StoreProject, name: str) -> FeatureLayer:
    """La capa de entidades ``name`` del proyecto (solo lee); ``ValueError`` si no es una capa de entidades (``gis_fea_``)."""
    found = load_features(project, name)
    if not isinstance(found, FeatureLayer):
        raise ValueError(f"«{name}» no es una capa de entidades del proyecto (gis_fea_)")
    return found


def _kind(layer: FeatureLayer, wanted: str, request: RoadRequest, code: str) -> None:
    """La capa es de la geometría ``wanted`` (``point``, ``line`` o ``polygon``): si no, ``des.road_layer_kind`` con lo que es y lo que se necesita."""
    if layer.kind != wanted:
        raise _reject("des.road_layer_kind", request, code, RoadParam.LAYER, _KINDS_ES.get(layer.kind, layer.kind), expected=_KINDS_ES[wanted])


def _names(layer: FeatureLayer, request: RoadRequest, code: str) -> tuple[str | None, ...]:
    """El nombre de cada geometría de la capa: el campo que eligió la persona (``des.road_layer_field`` si la capa no lo tiene o no es de texto) o, sin él, el campo ``nombre`` o ``name``;
    ``None`` donde no lo tiene."""
    wanted = request.fields.name_field
    if wanted is None:
        found = entity_store._names(layer)
        if any(name is not None for name in found):
            return found
        for column in layer.columns:  # una línea de rotura (``gis_brk_``) no tiene «nombre»: su identificador es ``line_id``
            if column.sql_type == "TEXT" and column.field.casefold() == _LINE_NAME_FIELD:
                return tuple(None if value is None else str(value).strip() for value in layer.values[column.column])
        return found
    fit = [column for column in layer.columns if column.sql_type not in _NUMERIC]
    for column in fit:
        if wanted in (column.field, column.column):
            return tuple(None if found is None else str(found).strip() for found in layer.values[column.column])
    raise _reject("des.road_layer_field", request, code, RoadParam.LAYER, wanted, fields=", ".join(column.field for column in fit) or "—")


def _feature_index(layer: FeatureLayer, wanted: str, request: RoadRequest, code: str, param: RoadParam) -> int:
    """El índice (en el orden de la capa) de la geometría que se elige por su ``fid`` (un número que está en la capa) o por su nombre: ``des.entity_feature_unknown`` si la capa no la
    tiene y ``des.entity_feature_ambiguous`` si varias llevan ese nombre (con sus ``fid``)."""
    if wanted.isascii() and wanted.isdigit() and int(wanted) in layer.fids:
        return layer.fids.index(int(wanted))
    found = [index for index, name in enumerate(_names(layer, request, code)) if name == wanted]
    if len(found) == 1:
        return found[0]
    obj, field = f"Pista «{request.name}» de la capa «{request.layer}»", entity_key(code, param)
    if len(found) > 1:
        raise DesignError("des.entity_feature_ambiguous", obj=obj, field=field, value=wanted, layer=request.layer, fids=", ".join(str(layer.fids[i]) for i in found))
    raise DesignError("des.entity_feature_unknown", obj=obj, field=field, value=wanted, layer=request.layer)


def _point_of(layer: FeatureLayer, index: int) -> tuple[float, float]:
    """El punto absoluto ``(x, y)`` (float64) de la geometría ``index`` de una capa de puntos: el primero de la entidad."""
    row = np.asarray(layer.parts[index][0][0], dtype=np.float64).reshape(-1, 2)[0]
    return float(row[0]), float(row[1])


def _cell_of(grid: Grid, x: float, y: float) -> tuple[int, int] | None:
    """La celda ``(fila, columna)`` de la rejilla que contiene el punto absoluto (en el borde de dos, la del este y la del sur: como la malla de la ruta); ``None`` si cae fuera."""
    column = math.floor((x - grid.west) / grid.dx)
    row = math.floor((grid.north - y) / grid.dy)
    if not (0 <= row < grid.nrows and 0 <= column < grid.ncols):
        return None
    return row, column


def _check_point(grid: Grid, surface: np.ndarray, point: tuple[float, float], request: RoadRequest, code: str, param: RoadParam, value: object, surface_name: str) -> None:
    """RF-017-04: el punto está dentro de la rejilla (``des.road_point_outside_grid``) y tiene dato en la superficie de partida (``des.road_point_no_data``, con la superficie y el lugar)."""
    where = {"x": round(point[0], 2), "y": round(point[1], 2)}
    cell = _cell_of(grid, *point)
    if cell is None:
        raise _reject("des.road_point_outside_grid", request, code, param, value, **where)
    if not math.isfinite(float(surface[cell])):
        raise _reject("des.road_point_no_data", request, code, param, value, surface=surface_name, **where)


def _first_crossing(points: np.ndarray) -> tuple[float, float] | None:
    """El primer cruce de una línea consigo misma (de los segmentos que no son contiguos), o ``None``: dos tramos que se cortan o se tocan, o que se solapan en una misma recta."""
    start, end = points[:-1], points[1:]
    for i in range(len(start) - 2):
        others = np.arange(i + 2, len(start))
        p, r = start[i], end[i] - start[i]
        q, s = start[others], end[others] - start[others]
        offset = q - p
        cross = r[0] * s[:, 1] - r[1] * s[:, 0]
        with np.errstate(divide="ignore", invalid="ignore"):
            t = (offset[:, 0] * s[:, 1] - offset[:, 1] * s[:, 0]) / cross
            u = (offset[:, 0] * r[1] - offset[:, 1] * r[0]) / cross
            long = float(r @ r)
            t0 = (offset @ r) / long
            t1 = t0 + (s @ r) / long
        hit = (cross != 0.0) & (t >= 0.0) & (t <= 1.0) & (u >= 0.0) & (u <= 1.0)
        parallel = (cross == 0.0) & ((offset[:, 0] * r[1] - offset[:, 1] * r[0]) == 0.0) & (np.maximum(np.minimum(t0, t1), 0.0) <= np.minimum(np.maximum(t0, t1), 1.0))
        found = hit | parallel
        if found.any():
            k = int(np.argmax(found))
            point = p + t[k] * r if bool(hit[k]) else q[k]
            return float(point[0]), float(point[1])
    return None


def _read_line(layer: FeatureLayer, index: int, name: str, request: RoadRequest, code: str) -> np.ndarray:
    """La línea de la geometría ``index`` de una capa de líneas en absolutas float64 ``(k, 2)``, **sin corregirla** (RF-017-18) y con los rechazos de RF-017-04, en este orden: de
    varias partes (``des.road_line_multipart``), sin longitud (``des.road_line_no_length``), con un vértice repetido (``des.road_line_repeated_vertex``, con su número desde 1 y su
    lugar) y que se corta a sí misma (``des.road_line_self_intersects``, con el lugar del cruce)."""
    parts = layer.parts[index]
    field = RoadParam.FEATURE
    if len(parts) != 1:
        raise _reject("des.road_line_multipart", request, code, field, name, parts=len(parts))
    line = np.asarray(parts[0][0], dtype=np.float64).reshape(-1, 2)
    if len(line) < 2 or bool((line == line[0]).all()):
        raise _reject("des.road_line_no_length", request, code, field, name)
    repeated = np.flatnonzero((np.diff(line, axis=0) == 0.0).all(axis=1))
    if repeated.size:
        vertex = int(repeated[0]) + 2
        raise _reject("des.road_line_repeated_vertex", request, code, field, name, vertex=vertex, x=round(float(line[vertex - 1, 0]), 2), y=round(float(line[vertex - 1, 1]), 2))
    crossing = _first_crossing(line)
    if crossing is not None:
        raise _reject("des.road_line_self_intersects", request, code, field, name, x=round(crossing[0], 2), y=round(crossing[1], 2))
    return line


def _check_line_cells(grid: Grid, surface: np.ndarray, line: np.ndarray, name: str, request: RoadRequest, code: str, surface_name: str) -> None:
    """RF-017-04: todos los vértices de la línea caen dentro de la rejilla y tienen dato en la superficie de partida (el primero que no, con su lugar)."""
    column = np.floor((line[:, 0] - grid.west) / grid.dx).astype(np.int64)
    row = np.floor((grid.north - line[:, 1]) / grid.dy).astype(np.int64)
    inside = (row >= 0) & (row < grid.nrows) & (column >= 0) & (column < grid.ncols)
    for vertex in range(len(line)):
        if not inside[vertex]:
            raise _reject("des.road_point_outside_grid", request, code, RoadParam.FEATURE, name, x=round(float(line[vertex, 0]), 2), y=round(float(line[vertex, 1]), 2))
        if not math.isfinite(float(surface[row[vertex], column[vertex]])):
            raise _reject("des.road_point_no_data", request, code, RoadParam.FEATURE, name, surface=surface_name, x=round(float(line[vertex, 0]), 2),
                          y=round(float(line[vertex, 1]), 2))


# --- La capa de líneas con Z del modo «eje 3D» (T23-a; RF-017-02, RF-017-04, RF-017-18) ---------


@dataclass(frozen=True, slots=True, eq=False)
class Lines3D:
    """Una capa de líneas con Z leída **tal como está guardada** (T23-a): su ``layer`` en planta (los números de sus filas, sus campos y sus partes en X e Y absolutas, float64: una
    ``FeatureLayer``, así que la elección por número o por nombre y los rechazos de la planta son los de «sobre un eje») y, de cada línea, sus vértices ``xyz`` ``(k, 3)`` —la Z de la línea, que
    una capa de entidades no guarda— o ``(k, 2)`` si la geometría no la lleva, y ``None`` si la línea es de varias partes (la planta la rechaza antes). Es lo que lee la preparación del proyecto
    (:func:`read_layer_3d`) y la reproducción de lo congelado (:func:`read_lines_3d`)."""

    layer: FeatureLayer
    xyz: tuple[np.ndarray | None, ...]


def _stored_xyz(geometry: Any) -> np.ndarray | None:
    """Los vértices de una geometría de líneas tal como están guardados, ``(k, 2)`` o ``(k, 3)``, float64 y de solo lectura; ``None`` si es de varias partes."""
    coords = geometry.coords
    if geometry.geometry_type == "MULTILINESTRING":
        if len(coords) != 1:
            return None
        coords = coords[0]
    found = np.array(coords, dtype=np.float64)
    found.flags.writeable = False
    return found


def read_lines_3d(conn: sqlite3.Connection, table: str) -> Lines3D:
    """Las líneas de la tabla ``table`` de la conexión ``conn`` (la del proyecto o una copia congelada: una línea de rotura ``gis_brk_`` o la capa propuesta ``des_rpl_``, de ``LINESTRING``
    con Z) como :class:`Lines3D`, en el orden de su ``fid``: la planta y los campos de una capa de entidades —de cada columna, su tipo (``BOOLEAN`` es entero, como en el proyecto)— y, aparte, la
    geometría tal como está guardada con su Z. **Solo lee** (principio 7). ``read_features`` no vale: una línea de rotura lleva una columna ``hard`` ``BOOLEAN`` que una capa de entidades
    no admite. ``ValueError`` si no es una tabla o su geometría no es de líneas."""
    info = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    if not info:
        raise ValueError(f"«{table}» no es una tabla del proyecto")
    typed = [(str(row[1]), column_type(str(row[2]))) for row in info if str(row[1]).lower() not in ("fid", "geom")]
    columns = tuple(FieldColumn(name, name, kind) for name, kind in typed if kind is not None)
    selected = ", ".join(f'"{name}"' for name in ("fid", "geom", *(column.column for column in columns)))
    rows = conn.execute(f'SELECT {selected} FROM "{table}" ORDER BY fid').fetchall()
    parts: list[tuple[tuple[np.ndarray, ...], ...]] = []
    found: list[np.ndarray | None] = []
    for row in rows:
        geometry = decode_geometry(row[1])
        if geometry.geometry_type not in ("LINESTRING", "MULTILINESTRING"):
            raise ValueError(f"«{table}» no es una tabla de líneas: tiene una geometría {geometry.geometry_type}")
        parts.append(feature_parts(geometry.geometry_type, geometry.coords))
        found.append(_stored_xyz(geometry))
    values = {column.column: tuple(row[index + 2] for row in rows) for index, column in enumerate(columns)}
    layer = FeatureLayer("line", tuple(int(row[0]) for row in rows), tuple(parts), columns, values)
    return Lines3D(layer, tuple(found))


def read_layer_3d(project: StoreProject, request: RoadRequest, code: str, *, version_uid: str = "") -> Lines3D:
    """La capa de líneas con Z ``request.layer`` del proyecto para el modo «eje 3D» (T23-a, decisión de la sesión principal): una **línea de rotura** (``gis_brk_``) o la **capa propuesta**
    (``des_rpl_``). Una capa de **entidades** (``gis_fea_``) guarda solo X e Y (``docs/trampas.md`` §6) y se rechaza con ``des.road_line_no_z`` (nombrando la capa, la pista, el campo y el valor);
    un dato que no existe, ``gis.dataset_unknown``; cualquier otra capa es un error del programa (``ValueError``: el diálogo solo ofrece las anteriores). **Solo lee.** La capa propuesta es un dato **de
    una versión** (``des_rpl_<nombre>`` en la versión ``version_uid``: T27; una línea de rotura es del proyecto): sin ``version_uid`` se busca entre los del proyecto."""
    name = request.layer
    if name.startswith(_FEATURE_PREFIX):
        raise _reject("des.road_line_no_z", request, code, RoadParam.FEATURE, str(request.feature))
    if not name.startswith(_LINES_3D_PREFIXES):
        raise ValueError(f"«{name}» no es una capa de líneas con Z del proyecto ({' o '.join(prefix + '…' for prefix in _LINES_3D_PREFIXES)})")
    with project.read() as conn:
        record = dataset_registry.get(conn, name, version_uid=version_uid if name.startswith(_ROUTE_PREFIX) else "")
        if record is None:
            raise GisError("gis.dataset_unknown", obj="Dato de topografía", field="dato", value=name)
        return read_lines_3d(conn, record.locator)


def line_3d(lines: Lines3D, request: RoadRequest, code: str) -> tuple[np.ndarray, int]:
    """La línea con Z que elige ``request.feature`` (por su ``fid`` o su nombre) de ``lines``, en absolutas float64 ``(k, 3)`` de solo lectura, y su ``fid`` (RF-017-02, RF-017-18): la **planta**
    con los rechazos de «sobre un eje» (:func:`_read_line`: varias partes, sin longitud, un vértice repetido, que se corta a sí misma) y la **Z**, que ha de estar en cada vértice y ser un
    número: si no, ``des.road_line_no_z`` nombrando la capa, la pista, el campo y el valor; **sin elegir una cota por la persona**. Sin línea elegida, ``des.entity_param_missing``. No modifica
    nada: la línea es una entrada (RF-017-18, principio 7)."""
    if request.feature is None:
        raise _reject("des.entity_param_missing", request, code, RoadParam.FEATURE, None)
    layer = lines.layer
    index = _feature_index(layer, request.feature, request, code, RoadParam.FEATURE)
    plan = _read_line(layer, index, request.feature, request, code)
    stored = lines.xyz[index]
    if stored is None or stored.ndim != 2 or stored.shape[1] < 3 or stored.shape[0] != len(plan) or not bool(np.isfinite(stored[:, 2]).all()):
        raise _reject("des.road_line_no_z", request, code, RoadParam.FEATURE, str(request.feature))
    found = np.column_stack([plan, stored[:, 2]])
    found.flags.writeable = False
    return found, int(layer.fids[index])


# --- El perfil ----------------------------------------------------------------------------------


def _profile(project: StoreProject, version: Version, request: RoadRequest, code: str) -> road_profiles.RoadProfile:
    """El perfil de pista ``request.profile`` (su código) con los valores que tiene en la versión (RF-017-07, RF-009-24: el de la versión y, si no, el del proyecto; sin fila, el de su
    definición): ``des.road_profile_unknown`` si el proyecto no tiene ese perfil (con los que tiene), ``des.road_profile_name_repeated`` si el nombre de dos se repite y, de un
    perfil sin algún valor, con uno fuera de su rango o con un radio mínimo que no cabe, ``des.road_profile_value_missing``, ``_value_range``, ``_radius_order`` o ``_radius_narrow``
    nombrando el perfil, el campo y el valor (RF-017-04)."""
    wanted = request.profile.strip()
    with project.read() as conn:
        stored = road_profiles.read_profiles(conn)
        keys = tuple(road_profile_key(wanted, param) for param in RoadProfileParam) if any(item.code == wanted for item in stored) else ()
        resolved = ParameterStore(project).resolve_many(conn, keys, (VERSION_SCOPE, PROJECT_SCOPE), version=version.uid) if keys else {}
    road_profiles.check_names(stored)
    names = {item.code: item.name for item in stored}
    if wanted not in names:
        raise _reject("des.road_profile_unknown", request, code, RoadParam.PROFILE, wanted, profiles=", ".join(names.values()) or "—")
    values: dict[str, object] = {}
    for key in keys:
        found = resolved.get(key)
        if found is not None:
            values[key] = None if found.value_json is None else json.loads(found.value_json)
        else:
            declared = definition(key)
            values[key] = None if declared is None else declared.default
    return road_profiles.road_profiles_from(values, (wanted,), names)[wanted]


# --- Las máscaras (RF-017-06) --------------------------------------------------------------------


def untouchable_cells(masks: Any) -> np.ndarray:
    """Lo que la ruta y la sección no pisan (RF-017-06, T15-a): el bit ``UNTOUCHABLE`` de la rejilla de clases de las máscaras (los intocables y las exclusiones), como máscara booleana
    de la rejilla entera. Un array nuevo."""
    return (np.asarray(masks.classes) & np.uint16(int(ClassBit.UNTOUCHABLE))) != 0


def avoid_weight(masks: Any) -> np.ndarray | None:
    """El peso de cada celda de las zonas «preferible no afectar» de las máscaras (RF-017-06): el **mayor** de las zonas que la pisan, de 1 o más (un peso menor no abarata el paso);
    1 donde no hay ninguna. ``None`` si las máscaras no tienen ninguna zona de ese tipo: todo pesa 1."""
    zones = masks.avoid_weights()
    if not zones:
        return None
    shape = masks.grid.shape
    weight = np.ones(shape, dtype=np.float64)
    for runs, value in zones.values():
        weight = np.where(runs.mask(shape), np.maximum(weight, float(value)), weight)
    return weight


# --- Los parámetros -----------------------------------------------------------------------------


def _default(param: RoadParam) -> Any:
    return entity_params("road").template(param.value).default


def road_values(request: RoadRequest, code: str, *, start_ref: str, start_level_m: float | None = None, end_level_m: float | None = None) -> dict[str, Any]:
    """Los parámetros resueltos y comprobados de la pista ``request`` de código ``code`` (RF-015-08), por último segmento de su clave: lo que se pide (la petición no lleva ninguna cifra
    minera y **ninguna de la ruta tiene valor por defecto**, salvo el presupuesto de estados: uno que falta es ``des.entity_param_missing``; uno fuera de su rango,
    ``des.entity_param_range``) y, de lo que el modo no usa, nada (P-14: «sobre un eje» y «eje 3D» no buscan ruta ni llevan origen ni destino). ``start_ref`` es lo que dice la partida
    (el nombre de un dato o ``entity:<código>``) y ``start_level_m`` y ``end_level_m`` las cotas ya resueltas (D-13). **Sin proyecto**: lo comparten preparar y reproducir. No lleva
    ``protect`` ni ``guard_m`` (la pista no declara: D-15)."""
    if not isinstance(request, RoadRequest):
        raise TypeError(f"la pista se prepara con una RoadRequest, no {request!r}")
    trace = request.mode is RoadMode.TRACE
    by_level = any(getattr(request, attr) is not None for attr in ("dest_level_m", "dest_tol_m", "dest_zone"))
    asked: dict[RoadParam, object] = {
        RoadParam.NAME: request.name, RoadParam.MODE: request.mode.value, RoadParam.LAYER: request.layer, RoadParam.PROFILE: request.profile, RoadParam.START: start_ref,
        RoadParam.SUPPORT: request.support, RoadParam.START_LEVEL: start_level_m, RoadParam.END_LEVEL: end_level_m}
    required: dict[RoadParam, bool] = {}
    if trace:
        asked.update({RoadParam.ORIGIN: request.origin, RoadParam.DESTINATION: request.destination, RoadParam.DEST_LEVEL: request.dest_level_m,
                      RoadParam.DEST_TOL: request.dest_tol_m, RoadParam.DEST_ZONE: request.dest_zone})
        required = {RoadParam.ORIGIN: True, RoadParam.DESTINATION: not by_level, RoadParam.DEST_LEVEL: by_level, RoadParam.DEST_TOL: by_level, RoadParam.DEST_ZONE: by_level}
        for param in _ROUTE_PARAMS:
            asked[param] = _default(param) if request.search_budget is None and param is RoadParam.SEARCH_BUDGET else getattr(request, param.value)
    else:
        asked[RoadParam.FEATURE] = request.feature
        required = {RoadParam.FEATURE: True}
    values: dict[str, Any] = {}
    for param in RoadParam:
        if param not in asked:
            continue
        checked = check_entity_param(request.name, code, param.value, asked[param], layer=request.layer, required=required.get(param))
        if checked is not None:
            values[param.value] = checked
    return values


def _rows(request: RoadRequest, code: str, values: Mapping[str, Any], levels: Mapping[str, tuple[str, str]], supports: Sequence[str]) -> tuple[EntityParamRow, ...]:
    """Las filas de los parámetros de la entidad con su procedencia (RF-008-01): los valores por defecto, con la de su definición (el presupuesto de estados); las cotas que salen de la
    superficie, de otra pista o de una entidad (``levels``: su parámetro → origen y clase), con el origen anotado (D-13); las dependencias declaradas (``supports``), y el resto, lo
    que eligió la persona en el diálogo."""
    name = request.name
    rows: list[EntityParamRow] = []
    for param in RoadParam:
        value = values.get(param.value)
        if value is None:
            continue
        if param.value in levels:
            source, kind = levels[param.value]
            reason = f"Cota por defecto de la pista «{name}»: {source}"
        elif param is RoadParam.SEARCH_BUDGET and request.search_budget is None:
            declared = entity_params("road").template(param.value)
            source, kind, reason = declared.source, str(declared.source_kind), default_reason(declared)
        else:
            source, kind, reason = f"{_DIALOG}, entidad «{name}»", "person", f"Elegido al crear la pista «{name}»"
        rows.append(EntityParamRow(entity_key(code, param), param.value, value, source, kind, reason))
    if supports:
        rows.append(EntityParamRow(entity_key(code, RoadParam.SUPPORTS), RoadParam.SUPPORTS.value, ", ".join(supports),
                                   f"origen y destino de la pista «{name}»", "algorithm", f"Dependencias declaradas de la pista «{name}»: {', '.join(supports)}"))
    return tuple(rows)


# --- Lo que la pista pisa: el eje de otra pista y la entidad de destino (RF-017-03) --------------


def _supportable(project: StoreProject, version: Version, registry: EntityRegistry, name: str, code: str, target: str, field: str, kind: EntityKind | None = None
                 ) -> tuple[entities.EntityEntry, entity_store.EntitySurface]:
    """La entidad ``target`` en la que se apoya la pista: viva y calculada, de tipo ``kind`` si se pide, y que no sea ella ni parta de su superficie (un ciclo: RF-015-15). Con su
    entrada del registro y su superficie y su huella (``entity_store.EntitySurface``). ``des.entity_supports_unknown`` si no."""
    entry = registry.get(target)
    skip = entity_store._unsupportable(registry, code, ())
    reason = _MISSING_SUPPORT
    found: entity_store.EntitySurface | None = None
    if entry is not None and entry.record.state in _LIVE_STATES and (kind is None or entry.record.kind == kind):
        if target in skip:
            reason = entity_store._SUPPORT_CYCLE if target != code else entity_store._SUPPORT_ITSELF
        else:
            with project.read() as conn:
                found = entity_store.entity_surfaces(conn, registry).get(target)
    if entry is None or found is None:
        raise DesignError("des.entity_supports_unknown", obj=_entity_object(code, name), field=field, value=target, entity=name, target=target, reason=reason, version=version.code)
    return entry, found


def _axis_stations(project: StoreProject, entry: entities.EntityEntry) -> np.ndarray:
    """Las estaciones del eje (``des_rdx_``: abscisa, x, y, cota del terreno y cota de la rasante) de la pista ``entry`` calculada, por orden de abscisa. ``ValueError`` si no tiene tabla."""
    with project.read() as conn:
        table = entity_store.operation_table(conn, str(entry.operation_uid), provenance.ROAD_AXIS_ROLE)
        if table is None:
            raise ValueError(f"la pista {entry.record.code} no tiene la tabla de su eje")
        rows = conn.execute(f'SELECT {_SECTION_COLUMNS} FROM "{table}" ORDER BY station_m').fetchall()
    return np.asarray(rows, dtype=np.float64).reshape(-1, 5)


def _footprint_cells(project: StoreProject, version: Version, entry: entities.EntityEntry, ncols: int) -> np.ndarray:
    """Las celdas (índices de la rejilla en filas) de la huella de la entidad ``entry`` viva y calculada, de su ``des_epr_`` (se rechaza una huella que no se puede usar, como en la
    declaración de restricciones)."""
    with project.read() as conn:
        footprint = entity_store._usable_footprint(conn, entry, version)
    if not footprint.runs:
        return np.empty(0, dtype=np.int64)
    return runs_cells(np.asarray(footprint.runs, dtype=np.int64), ncols)


# --- Preparar -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Resolved:
    """El origen y el destino ya resueltos: sus puntos absolutos, sus cotas por defecto con su origen (D-13) y las entidades en que se apoya la pista."""

    origin: tuple[float, float]
    destination: tuple[float, float] | None
    origin_level: DerivedLevel | None
    destination_level: DerivedLevel | None
    supports: tuple[str, ...]
    surfaces: Mapping[str, entity_store.EntitySurface] = MappingProxyType({})
    fid: int = 0
    axis: str | None = None
    """El dato del eje por estaciones (``des_rdx_``) de la pista en cuyo eje está el origen, que se lee y es **entrada** de la operación (papel ``road_axis``): la reproducción lo lee congelado."""


def _terrain_level(grid: Grid, surface: np.ndarray, point: tuple[float, float]) -> float:
    """La cota de la superficie ``surface`` en el punto absoluto: la interpolación bilineal de la 011 (``road_section.sample_terrain``) o, donde falta algún vecino, la de su celda."""
    found = float(road_section.sample_terrain(surface, grid, np.array([point[0]]), np.array([point[1]]))[0])
    if math.isfinite(found):
        return found
    cell = _cell_of(grid, *point)
    assert cell is not None
    return float(surface[cell])


def _check_level(request: RoadRequest, code: str, param: RoadParam, value: float | None, surface: np.ndarray) -> None:
    """RF-017-04: una cota que da la persona no se sale de las del terreno de la partida en más de 1.000 m (``des.road_level_range``): no se elige otra por ella."""
    if value is None:
        return
    finite = surface[np.isfinite(surface)]
    low, high = float(finite.min()), float(finite.max())
    if value < low - _LEVEL_LIMIT_M or value > high + _LEVEL_LIMIT_M:
        raise _reject("des.road_level_range", request, code, param, value, low=round(low, 3), high=round(high, 3), limit=_LEVEL_LIMIT_M)


def _resolve_points(project: StoreProject, version: Version, registry: EntityRegistry, request: RoadRequest, code: str, name: str, layer: FeatureLayer, grid: Grid,
                    surface: np.ndarray, surface_name: str, frame: Any) -> Generator[None, None, _Resolved]:
    """Lo que dicen el origen y el destino de «trazar» (RF-017-02, RF-017-03): cada uno, un punto de la capa (por su nombre o su ``fid``: dentro de la rejilla y con dato en la
    partida, RF-017-04), el origen también un punto del eje de otra pista (``RDW-001@s``: su lugar y su cota a esa abscisa) y el destino también **el punto de la capa que cae en la
    huella de una entidad** (``entity:PLT-001``, T19-c: ni ninguno ni varios) con la cota de su superficie en él. Se rechaza que sean el mismo punto
    (``des.road_origin_is_destination``). Las entidades en que se apoya, de las dos, salen en ``supports``."""
    supports: list[str] = []
    surfaces: dict[str, entity_store.EntitySurface] = {}
    skip = -1
    taken: list[tuple[float, float]] = []
    fids: list[int] = []
    axis: str | None = None

    def point(ref: PointReference, param: RoadParam) -> tuple[float, float]:
        nonlocal skip
        found = _feature_index(layer, ref.name, request, code, param)
        where = _point_of(layer, found)
        _check_point(grid, surface, where, request, code, param, ref.name, surface_name)
        if param is RoadParam.ORIGIN:
            skip = found
        fids.append(int(layer.fids[found]))
        return where

    if request.origin is None:
        raise _reject("des.entity_param_missing", request, code, RoadParam.ORIGIN, None)
    origin_ref = parse_reference(request.origin)
    origin_level: DerivedLevel | None = None
    if isinstance(origin_ref, AxisReference):
        entry, listed = _supportable(project, version, registry, name, code, origin_ref.code, entity_key(code, RoadParam.ORIGIN), EntityKind.ROAD)
        surfaces[origin_ref.code] = listed
        stations = _axis_stations(project, entry)
        at = axis_point_at(stations, origin_ref.station_m)
        if at is None:
            raise _reject("des.road_origin_abscissa", request, code, RoadParam.ORIGIN, str(request.origin), target=origin_ref.code, length=round(float(stations[-1, 0]), 3))
        origin = (at[0], at[1])
        _check_point(grid, surface, origin, request, code, RoadParam.ORIGIN, str(request.origin), surface_name)
        origin_level = DerivedLevel(at[2], f"cota de la rasante de la pista «{entry.record.name}» ({origin_ref.code}) a la abscisa {origin_ref.station_m:g} m",
                                    f"«{entry.record.name}» ({origin_ref.code})")
        supports.append(origin_ref.code)
        axis = provenance.dataset_name(provenance.ROAD_AXIS_TABLE, entry.record.name)
    else:
        origin = point(PointReference(str(request.origin).strip()), RoadParam.ORIGIN)
        origin_level = DerivedLevel(_terrain_level(grid, surface, origin), f"cota de la superficie de partida «{surface_name}» en el origen (x = {origin[0]:.2f} m, y = {origin[1]:.2f} m)",
                                    f"«{surface_name}»")
    taken.append(origin)
    if request.destination is None:
        yield
        return _Resolved(origin, None, origin_level, None, tuple(supports), MappingProxyType(surfaces), fids[0] if fids else 0, axis)
    destination_ref = parse_reference(request.destination)
    destination_level: DerivedLevel | None
    if isinstance(destination_ref, EntityReference):
        entry, found = _supportable(project, version, registry, name, code, destination_ref.code, entity_key(code, RoadParam.DESTINATION))
        surfaces[destination_ref.code] = found
        cells = _footprint_cells(project, version, entry, grid.ncols)
        inside: list[int] = []
        for index in range(len(layer)):
            where = _point_of(layer, index)
            cell = _cell_of(grid, *where)
            if index != skip and cell is not None and bool(np.isin(cell[0] * grid.ncols + cell[1], cells)):
                inside.append(index)
        if not inside:
            raise _reject("des.road_destination_not_in_entity", request, code, RoadParam.DESTINATION, request.destination, target=destination_ref.code)
        if len(inside) > 1:
            raise _reject("des.road_destination_ambiguous", request, code, RoadParam.DESTINATION, request.destination, target=destination_ref.code, points=len(inside))
        destination = _point_of(layer, inside[0])
        fids.append(int(layer.fids[inside[0]]))
        cell = _cell_of(grid, *destination)
        assert cell is not None
        window = (slice(cell[0], cell[0] + 1), slice(cell[1], cell[1] + 1))
        level = float(read_surface_window(project, found.surface, window, version_uid=version.uid, expect=frame, role=_ENTITY_ROLE).values[0, 0])
        if not math.isfinite(level):
            raise _reject("des.road_point_no_data", request, code, RoadParam.DESTINATION, request.destination, surface=found.surface, x=round(destination[0], 2), y=round(destination[1], 2))
        destination_level = DerivedLevel(level, f"cota de la superficie de la entidad «{entry.record.name}» ({destination_ref.code}) en el destino (x = {destination[0]:.2f} m, y = {destination[1]:.2f} m)",
                                         f"«{entry.record.name}» ({destination_ref.code})")
        supports.append(destination_ref.code)
    else:
        destination = point(PointReference(request.destination.strip()), RoadParam.DESTINATION)
        destination_level = DerivedLevel(_terrain_level(grid, surface, destination), f"cota de la superficie de partida «{surface_name}» en el destino (x = {destination[0]:.2f} m, y = {destination[1]:.2f} m)",
                                         f"«{surface_name}»")
    if any(abs(destination[0] - other[0]) <= 1e-9 and abs(destination[1] - other[1]) <= 1e-9 for other in taken):
        raise _reject("des.road_origin_is_destination", request, code, RoadParam.DESTINATION, request.destination)
    yield
    return _Resolved(origin, destination, origin_level, destination_level, tuple(dict.fromkeys(supports)), MappingProxyType(surfaces), fids[0] if fids else 0, axis)


def _level_destination(project: StoreProject, request: RoadRequest, code: str) -> tuple[LevelDestination, str]:
    """El destino por cota de la pista (la rampa, D-4; RF-017-02): su cota, su tolerancia de llegada y la zona (los polígonos de la capa ``dest_zone``: ``capa`` o ``capa:geometría``,
    esta por su nombre o su ``fid``), y el nombre de la capa de la zona. ``des.road_layer_kind`` si no es de polígonos."""
    layer_name = str(request.dest_zone).partition(":")[0].strip()
    return _zone_destination(_layer(project, layer_name), request, code), layer_name


def _zone_destination(layer: FeatureLayer, request: RoadRequest, code: str) -> LevelDestination:
    """El destino por cota de ``request`` con la capa de su zona ``layer`` ya leída (la del proyecto al preparar; la congelada al reproducir): ``dest_zone`` dice la capa y, tras los dos puntos, el
    polígono por su nombre o su ``fid`` (sin él, todos los de la capa). ``des.road_layer_kind`` si no es de polígonos."""
    layer_name, _, wanted = str(request.dest_zone).partition(":")
    if layer.kind != "polygon":
        raise _reject("des.road_layer_kind", request, code, RoadParam.DEST_ZONE, _KINDS_ES.get(layer.kind, layer.kind), expected=_KINDS_ES["polygon"])
    if wanted.strip():
        indexes = [_feature_index(layer, wanted.strip(), replace(request, fields=LayerFields(layer_name.strip(), request.fields.name_field)), code, RoadParam.DEST_ZONE)]
    else:
        indexes = list(range(len(layer)))
    zone = tuple(part for index in indexes for part in layer.parts[index])
    assert request.dest_level_m is not None and request.dest_tol_m is not None
    return LevelDestination(request.dest_level_m, request.dest_tol_m, zone)


def _dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    """``mask`` ensanchada ``radius`` celdas en cada dirección (un cuadrado: contiene el círculo del mismo radio), con sumas acumuladas, sin bucles por celda."""
    found = mask.astype(np.int32)
    for axis in (0, 1):
        pad = [(0, 0), (0, 0)]
        pad[axis] = (radius + 1, radius)
        total = np.cumsum(np.pad(found, pad), axis=axis, dtype=np.int32)
        size = found.shape[axis]
        found = (np.take(total, np.arange(2 * radius + 1, 2 * radius + 1 + size), axis=axis) - np.take(total, np.arange(size), axis=axis) > 0).astype(np.int32)
    return found > 0


def _drain(steps: Iterator[Progress]) -> Generator[None, None, Any]:
    """Las unidades de unos pasos de ``Progress`` (cada uno, un ``yield``) y el resultado del último que lo lleva."""
    found = None
    for step in steps:
        yield
        found = step.result if step.result is not None else found
    return found


def _pending_zone(job: RoadJob, mesh: road_net.RouteMesh | None) -> Generator[None, None, np.ndarray]:
    """La zona donde la pista puede mover algo (RF-015-07): el pasillo de la ruta (los nodos de la red 2D que pueden estar en ella) o la línea, **ensanchados** por la semianchura de la
    sección y el alcance del borde, en la rejilla entera. Una cota **por exceso** (un cuadrado): pedir la búsqueda de un sector de más es un rechazo de más, no un dato mal medido."""
    grid, profile = job.grid, job.profile
    half = road_profiles.derived(profile).half_width_m
    radius = math.ceil((half + profile.reach_m) / grid.dx) + 2
    cells = np.zeros(grid.shape, dtype=bool)
    if job.mode is RoadMode.TRACE:
        assert mesh is not None and job.route is not None
        target = road_route.route_target(job, mesh)
        pd, height = profile.max_gradient_pct / 100.0, job.route.max_cut_fill_m
        net_dest = yield from _drain(road_net.network_steps(mesh, target, pd, height))
        net_origin = yield from _drain(road_net.network_steps(mesh, mesh.node_of(*job.geometry.origin), pd, height))  # type: ignore[misc]
        found = road_net.corridor(net_origin, net_dest, job.route.margin_m)
        block = np.kron(found.mask, np.ones((mesh.k, mesh.k), dtype=bool))[:grid.nrows, :grid.ncols]
        cells[:block.shape[0], :block.shape[1]] = block
    else:
        line = np.asarray(job.geometry.line, dtype=np.float64)[:, :2]
        length = np.hypot(*np.diff(line, axis=0).T)
        along = np.concatenate([[0.0], np.cumsum(length)])
        step = np.arange(0.0, along[-1] + grid.dx / 2.0, grid.dx / 2.0)
        x, y = np.interp(step, along, line[:, 0]), np.interp(step, along, line[:, 1])
        column, row = np.floor((x - grid.west) / grid.dx).astype(np.int64), np.floor((grid.north - y) / grid.dy).astype(np.int64)
        keep = (row >= 0) & (row < grid.nrows) & (column >= 0) & (column < grid.ncols)
        cells[row[keep], column[keep]] = True
    yield
    where = np.argwhere(cells)
    if not where.size:
        return cells
    top, left = np.maximum(where.min(axis=0) - radius, 0)
    bottom, right = np.minimum(where.max(axis=0) + radius + 1, grid.shape)
    zone = np.zeros(grid.shape, dtype=bool)
    zone[top:bottom, left:right] = _dilate(cells[top:bottom, left:right], radius)
    return zone


def start_is_final_notice(entity: str, surface: str, grid: Grid, final: np.ndarray, pit: np.ndarray, origin: tuple[float, float], walk_slope_pct: float, walk_width_m: float,
                          untouchable: np.ndarray) -> Notice | None:
    """El aviso de RF-017-05 (a), «no llega al fondo» (error 23): la partida de la pista ``entity`` es la superficie final restaurada ``surface`` de una cantera (``final``) y desde el
    origen de la pista, con la pendiente transitable ``walk_slope_pct`` (%: la de diseño del perfil) y el ancho mínimo ``walk_width_m`` (m: su calzada f·A: T19-a), la cota mínima
    alcanzable sobre ella es mayor que sobre la superficie de explotación (``pit``): da las dos. ``None`` si llega igual de hondo (o si sobre la de explotación no se alcanza nada). Es
    una llamada de dominio de la accesibilidad (``road_access``), **sin registrar una operación**."""

    def lowest(values: np.ndarray) -> float | None:
        asked = AccessRequest("Alcance de la pista", LayerFields("origen"), surface, walk_slope_pct=walk_slope_pct, walk_width_m=walk_width_m, min_berm_area_m2=0.0)
        job = AccessJob(asked, "ACC-001", grid, values, (EntryPoint("origen", origin[0], origin[1]),), untouchable, walk_slope_pct, walk_width_m, 0.0)
        try:
            return road_access.access(job).z_min_m
        except DesignError:  # el origen sin dato en esa superficie: no hay cota que dar
            return None

    z_pit, z_final = lowest(pit), lowest(final)
    if z_pit is None or (z_final is not None and z_final <= z_pit + 1e-9):
        return None
    return Notice("des.road_start_is_final", {"entity": entity, "surface": surface, "z_final": "—" if z_final is None else round(z_final, 3), "z_pit": round(z_pit, 3)})


def other_design_notices(entity: str, grid: Grid, footprint: np.ndarray, start: np.ndarray, others: Mapping[str, np.ndarray], min_thickness_m: float) -> tuple[Notice, ...]:
    """Los avisos de RF-017-05 (b): de cada diseño de la versión que no parte de la partida (``others``: su nombre → su superficie, de la forma de ``start`` y de ``footprint``), si
    **en la huella de la pista** (``footprint``: sección y borde) la partida difiere de él en más del espesor mínimo de la 012 (``min_thickness_m``), con el área (m²), la diferencia
    máxima (m) y el lugar de la mayor (el centro de su celda, absoluto): «un relleno que la pista no tiene en cuenta», que **no impide crearla**. Las celdas sin dato no cuentan. Uno por
    diseño que difiere, en el orden de ``others``. ``grid`` es la rejilla de esos arrays."""
    found: list[Notice] = []
    for name, values in others.items():
        with np.errstate(invalid="ignore"):
            difference = np.abs(np.asarray(values, dtype=np.float64) - start)
            differs = footprint & np.isfinite(difference) & (difference > min_thickness_m)
        if not differs.any():
            continue
        rows, columns = np.nonzero(differs)
        worst = int(np.argmax(difference[rows, columns]))
        row, column = int(rows[worst]), int(columns[worst])
        found.append(Notice("des.road_other_design_differs", {
            "entity": entity, "other": name, "area": float(rows.size * grid.cell_area), "difference": float(difference[row, column]),
            "x": float(grid.west + (column + 0.5) * grid.dx), "y": float(grid.north - (row + 0.5) * grid.dy)}))
    return tuple(found)


def _pit_name(project: StoreProject, version: Version, start_name: str) -> str | None:
    """El nombre de la superficie de **explotación** de la cantera de la 014 cuya final restaurada es ``start_name`` (``des_fin_<cantera>`` → ``des_exp_<cantera>``), si la versión la
    tiene viva; ``None`` si la partida no es la final de una cantera."""
    final = provenance.FAMILIES_BY_CODE[provenance.FINAL_GRID].prefix
    if not start_name.startswith(final):
        return None
    wanted = provenance.FAMILIES_BY_CODE[provenance.EXPLOITATION_GRID].prefix + start_name[len(final):]
    with project.read() as conn:
        record = dataset_registry.get(conn, wanted, version_uid=version.uid)
        owner = None if record is None else conn.execute("SELECT version_uid FROM gb_dataset WHERE uid = ?", (record.uid,)).fetchone()
    return None if record is None or not record.live or owner is None or owner[0] != version.uid else record.name


def other_designs(project: StoreProject, version: Version, start_name: str, *, own: str | None = None) -> tuple[str, ...]:
    """Los nombres de los datos de **otros diseños** de la versión con los que se compara la partida de una pista (RF-017-05 (b), T19-b): **la última superficie de cada cadena de
    entidades** (``entities.chain_tail_surfaces``) y **las superficies de diseño** (papel ``design_surface``) de la versión, **que no tienen a la partida como ancestro** en el grafo (la
    superficie que escribió la misma operación que la partida, o una cuya cadena de partidas pasa por la que la escribió, no es otro diseño), en el orden de su nombre. Solo lee. **Tampoco lo es
    aquello de lo que parte la partida** (H2, T25): con la partida de un relleno sobre la explotación de una cantera, la explotación y la final de esa cantera —las superficies que escribió una
    operación de la cadena de la partida— son su historia, no un diseño que la pista no tenga en cuenta; sin esto, toda pista de la última superficie de una cadena avisaría de las dos.

    ``own`` (T24): la operación de la pista que se recalcula (la que sustituye la nueva). **Lo que parte de lo que dejó ella** —su ramal, el relleno que se hizo luego sobre su calzada— **no es otro
    diseño**: depende de la pista, y anotarlo como entrada la haría depender de lo que depende de ella (un bucle que no se asienta). Con otra partida (rehacer la pista sobre otra superficie) esos
    diseños dejan de tener a la partida como ancestro, así que sin esto contarían."""
    from .entities import _surface_ancestors  # el grafo hacia atrás por la entrada «surface»: lo mismo que «apoyo retirado»

    with project.read() as conn:
        start = dataset_registry.get(conn, start_name, version_uid=version.uid) or dataset_registry.get(conn, start_name)  # la partida puede ser un dato del proyecto (un MDT importado)
        writer = None if start is None else start.operation_uid
        candidates: dict[str, str] = {}
        for uid in entities.chain_tail_surfaces(conn, version.uid):
            row = conn.execute("SELECT name FROM gb_dataset WHERE uid = ?", (uid,)).fetchone()
            if row is not None:
                candidates[str(row[0])] = str(uid)
        for uid, name in conn.execute(
                "SELECT DISTINCT d.uid, d.name FROM gb_dataset AS d JOIN gb_operation_io AS io ON io.item_uid = d.uid AND io.direction = 'out' AND io.item_kind = 'dataset' "
                "WHERE d.version_uid = ? AND io.role = ? ORDER BY d.name", (version.uid, provenance.DESIGN_SURFACE_ROLE)).fetchall():
            candidates[str(name)] = str(uid)
        before_start = set() if writer is None else _surface_ancestors(conn, writer)  # H2 (T25): de lo que parte la partida (la cantera, el relleno anterior) tampoco es «otro diseño»
        found: list[str] = []
        for name in sorted(candidates):
            record = dataset_registry.get(conn, name, version_uid=version.uid)
            if name == start_name or record is None or not record.live or record.operation_uid is None:
                continue
            if writer is not None and (record.operation_uid == writer or record.operation_uid in before_start or writer in _surface_ancestors(conn, record.operation_uid)):
                continue
            if own is not None and (record.operation_uid == own or own in _surface_ancestors(conn, record.operation_uid)):  # lo que deja la propia pista y lo que parte de ello (T24)
                continue
            found.append(name)
    return tuple(found)


def prepare_road_units(project: StoreProject, request: RoadRequest, version: Version, masks: access.MaskSet, *, code: str | None = None,
                       supersedes: str | None = None, released: Sequence[provenance.ReleasedSupport] = ()) -> Generator[None, None, PreparedRoad]:
    """Las unidades (cada ``yield``, una; para componerlas con ``pace_units``) que preparan la pista ``request`` en la versión editable ``version`` con las máscaras al día ``masks``
    (``store.masks_steps``; RF-015-06): el código y el nombre únicos (``code``: el de una entidad que ya está en su versión, que no choca consigo misma), la partida (``request.start``;
    en blanco, :func:`default_start`) y la cadena, la capa y la geometría de origen por modo (RF-017-02), el perfil, la superficie de partida y su rejilla comparada con la del proyecto
    **antes de leer una celda** (``design.surfaces.read_surface_steps``), el origen y el destino (:func:`_resolve_points`), las cotas de inicio y de fin (D-13), los parámetros
    (:func:`road_values`), el destino por cota con su zona, el corte y el relleno admitidos, lo intocable y el peso de «preferible no afectar» de las máscaras, **la búsqueda de
    intocables** de los sectores que toca el pasillo o la sección (RF-015-07: ``refuse_pending``), los avisos de la partida y lo que anotará la operación. ``supersedes``: la operación
    hecha a la que sustituye (un recálculo). **Nada se escribe** (RF-015-03). Los rechazos salen al avanzar, antes de calcular y en este orden: la versión, el nombre y la cadena, la
    capa y la geometría, el perfil, la superficie, los puntos, las cotas, los parámetros, la malla de la ruta, el destino por cota y un sector pendiente.

    «Sobre un eje» lee la línea de su capa de entidades (RF-017-04) y «eje 3D», la línea con su Z de una línea de rotura (``gis_brk_``) o de la capa propuesta (``des_rpl_``; T23-a: una capa de
    entidades, que guarda solo X e Y, se rechaza con ``des.road_line_no_z``): :func:`read_layer_3d` y :func:`line_3d`. En «eje 3D» la Z es la rasante: **no hay cota de inicio ni de fin**.

    **Recalcular sigue a lo que pisa** (T24b; RF-017-03, D-13, RF-015-01): con ``code`` (la entidad ya está en su versión) las cotas de inicio y de fin cuyo origen anotado en su fila es el del algoritmo **se
    vuelven a tomar de su origen** (la superficie de partida en el punto, el eje de otra pista a esa abscisa o la superficie de la entidad de destino en ese punto: :func:`resolve_level`) en vez de dar por
    buena la que guardó la creación; las que dio la persona se conservan. Las que cambian van en ``PreparedRoad.followed`` (y en ``values``); **preparar no escribe nada**: quien recalcula las escribe
    (:func:`write_followed`).

    ``released`` (T24; RF-015-17, A7, P-6): las entidades descartadas que la pista **da por buenas sin su apoyo** (:func:`~.entity_store.release_support`): lo que **declaró** la persona
    (``supports``) en ellas no se pide ni se rechaza —se descartaron—, se suman a las que ya soltaba la operación que sustituye (``supersedes``) y no entran en las entradas ni en lo que la
    operación lee. Lo que la pista toma de la entidad (su origen en el eje de otra pista, su destino en una entidad) **no se suelta**: sin ella no hay geometría (``entity_store.release_support``
    lo rechaza antes de empezar)."""
    if masks.version_uid != version.uid:
        raise ValueError(f"las máscaras son de otra versión, no de {version.code}")
    chosen, registry = _identify(project, version, request, code)
    name = request.name
    start_ref = request.start.strip()
    if not start_ref:
        proposed = default_start(project, version)
        if proposed is None:
            raise _reject("des.entity_param_missing", request, chosen, RoadParam.START, None)
        start_ref = proposed.ref
    entity_store._check_chain_of(registry, name, start_ref, request.support, chosen)
    start_name = _start_dataset(registry, version, name, chosen, start_ref, RoadParam.START)
    support_name = None if request.support is None else _start_dataset(registry, version, name, chosen, request.support, RoadParam.SUPPORT)
    yield
    mode = request.mode
    line: np.ndarray | None = None
    fid = 0
    if mode is RoadMode.AXIS_3D:  # la Z de la línea sale de una línea de rotura o de la capa propuesta; una capa de entidades no la guarda (T23-a)
        lines = read_layer_3d(project, request, chosen, version_uid=version.uid)
        layer = lines.layer
        line, fid = line_3d(lines, request, chosen)
    else:
        layer = _layer(project, request.layer)
        _kind(layer, "point" if mode is RoadMode.TRACE else "line", request, chosen)
    if mode is RoadMode.ON_AXIS:
        if request.feature is None:
            raise _reject("des.entity_param_missing", request, chosen, RoadParam.FEATURE, None)
        index = _feature_index(layer, request.feature, request, chosen, RoadParam.FEATURE)
        fid = int(layer.fids[index])
        line = _read_line(layer, index, request.feature, request, chosen)
    profile = _profile(project, version, request, chosen)
    yield
    frame = project_frame(project)
    grid = frame.grid
    surface = yield from read_surface_steps(project, start_name, version_uid=version.uid, expect=frame, role=_START_ROLE)
    values_start = surface.values
    if not frame.grid.same_geometry(masks.grid):
        raise ValueError("la rejilla de las máscaras no es la del proyecto")
    supports: tuple[str, ...] = ()
    listed: dict[str, entity_store.EntitySurface] = {}
    axis_data: str | None = None
    start_level: DerivedLevel | None
    end_level: DerivedLevel | None
    if mode is RoadMode.TRACE:
        resolved = yield from _resolve_points(project, version, registry, request, chosen, name, layer, grid, values_start, start_name, frame)
        geometry_points: tuple[tuple[float, float], tuple[float, float] | None] = (resolved.origin, resolved.destination)
        supports = resolved.supports
        fid = resolved.fid
        axis_data = resolved.axis
        listed = dict(resolved.surfaces)
        start_level, end_level = resolved.origin_level, resolved.destination_level
        by_level = any(getattr(request, attr) is not None for attr in ("dest_level_m", "dest_tol_m", "dest_zone"))
        if by_level and request.destination is None:
            end_level = None
    else:
        assert line is not None and request.feature is not None
        _check_line_cells(grid, values_start, line[:, :2], request.feature, request, chosen, start_name)
        geometry_points = ((float(line[0, 0]), float(line[0, 1])), (float(line[-1, 0]), float(line[-1, 1])))
        start_level = DerivedLevel(_terrain_level(grid, values_start, geometry_points[0]), f"cota de la superficie de partida «{start_name}» en el primer vértice de la línea", f"«{start_name}»")
        end_level = DerivedLevel(_terrain_level(grid, values_start, geometry_points[1]), f"cota de la superficie de partida «{start_name}» en el último vértice de la línea", f"«{start_name}»")
        if mode is RoadMode.AXIS_3D:  # la Z de la línea es la rasante (RF-017-18): no hay cota de inicio ni de fin que dar ni que tomar del terreno
            start_level = end_level = None
    levels: dict[str, tuple[str, str]] = {}
    chosen_levels: dict[RoadParam, float | None] = {RoadParam.START_LEVEL: None, RoadParam.END_LEVEL: None}
    followed: list[LevelFollow] = []
    if mode is not RoadMode.AXIS_3D:
        kinds = {} if code is None else _level_kinds(project, version, chosen)  # al recalcular, el origen anotado en la fila (T24b)
        for param, asked_level, derived in ((RoadParam.START_LEVEL, request.start_level_m, start_level), (RoadParam.END_LEVEL, request.end_level_m, end_level)):
            level = resolve_level(param, asked_level, kinds.get(param.value), derived)
            if level.origin is None:  # la da la persona (o no hay origen que la dé): se comprueba contra el terreno
                _check_level(request, chosen, param, level.value_m, values_start)
            else:
                levels[param.value] = level.origin
            chosen_levels[param] = level.value_m
            if level.follow is not None:
                followed.append(level.follow)
    resolved_start, resolved_end = chosen_levels[RoadParam.START_LEVEL], chosen_levels[RoadParam.END_LEVEL]
    values = road_values(request, chosen, start_ref=start_ref, start_level_m=resolved_start, end_level_m=resolved_end)
    yield
    route: RouteParams | None = None
    if mode is RoadMode.TRACE:
        try:
            road_net.mesh_factor(grid, values[RoadParam.MESH.value])
        except ValueError:
            raise _reject("des.road_mesh_not_multiple", request, chosen, RoadParam.MESH, values[RoadParam.MESH.value], step=grid.dx) from None
        route = RouteParams.from_values(values)
    destination: LevelDestination | None = None
    zone_layer: str | None = None
    if mode is RoadMode.TRACE and request.destination is None:
        destination, zone_layer = _level_destination(project, request, chosen)
    cut, fill = admitted_pair(masks, (slice(0, grid.nrows), slice(0, grid.ncols)))
    untouchable = untouchable_cells(masks)
    weight = avoid_weight(masks)
    if mode is RoadMode.TRACE:
        geometry = RoadGeometry(origin=geometry_points[0], destination=destination if destination is not None else geometry_points[1])
    else:
        geometry = RoadGeometry(line=line)
    asked = replace(request, start=start_ref)
    job = RoadJob(asked, chosen, profile, grid, values_start, cut, fill, untouchable, geometry, route, resolved_start, resolved_end, weight)
    yield
    mesh: road_net.RouteMesh | None = None
    if destination is not None or (mode is RoadMode.TRACE and any(item.pending for item in design_sectors(project, version.uid))):
        mesh = road_net.route_mesh(grid, values_start, route.mesh_m, untouchable, avoid_weight=weight)  # type: ignore[union-attr]
    if destination is not None:
        assert mesh is not None
        nodes = Grid(west=grid.west, north=grid.north, dx=mesh.mesh_m, dy=mesh.mesh_m, ncols=mesh.shape[1], nrows=mesh.shape[0])
        if not bool((polygons_cells(destination.zone, nodes) & mesh.walkable).any()):
            raise _reject("des.road_dest_zone_empty", request, chosen, RoadParam.DEST_ZONE, str(request.dest_zone))
        road_route.route_target(job, mesh)  # ``des.road_dest_level_out_of_zone``: la cota que ningún nodo de la zona alcanza
    yield
    sectors = design_sectors(project, version.uid)
    if any(item.pending for item in sectors):
        zone = yield from _pending_zone(job, mesh)
        refs, labels = sector_layout(project, masks)
        touched = pipeline.touched_in(refs, labels, zone)
        refuse_pending(item for item in sectors if item.code in touched)  # RF-015-07
    yield
    common = entity_store._common(project, version)
    notices: list[Notice] = []
    pit = _pit_name(project, version, start_name)
    if pit is not None:
        found = yield from read_surface_steps(project, pit, version_uid=version.uid, expect=frame, role=_PIT_ROLE)
        derived = road_profiles.derived(profile)
        origin_point = geometry_points[0]
        notice = start_is_final_notice(name, start_name, grid, values_start, found.values, origin_point, profile.max_gradient_pct, derived.carriageway_m, untouchable)
        if notice is not None:
            notices.append(notice)
    others = other_designs(project, version, start_name, own=supersedes)
    yield
    given = entity_store._released_codes(project, supersedes, released)  # lo que da por bueno sin su apoyo: la nueva y la que sustituye (T24)
    declared = tuple(target for target in entity_store._declared(entity_store._declared_row(project, version, chosen)) if target not in given)
    supported = tuple(dict.fromkeys((*supports, *declared)))
    surfaces: list[str] = [] if support_name is None else [support_name]
    tables: list[Use] = []
    for target in supported:
        if target not in listed:  # lo declarado por la persona en ``supports`` (RF-015-15), que no sale del origen ni del destino
            listed[target] = _supportable(project, version, registry, name, chosen, target, entity_key(chosen, RoadParam.SUPPORTS))[1]
        surfaces.append(listed[target].surface)
        tables.append(Use(listed[target].table, provenance.SUPPORT_FOOTPRINT_ROLE))
    inputs = provenance.road_inputs(request.layer, start_name, masks.uses(), tuple(dict.fromkeys(surfaces)))
    read = [] if axis_data is None else [Use(axis_data, provenance.ROAD_AXIS_ROLE)]  # lo que lee del eje de otra pista (RF-017-03): entrada, para congelarlo y reproducir (T22)
    extra = [use for use in (*([] if zone_layer is None else [Use(zone_layer, provenance.ENTITY_LAYER_ROLE)]), *tables, *read) if use not in inputs]
    valued = [param.value for param in (RoadParam.SUPPORT, RoadParam.DEST_LEVEL, RoadParam.DEST_TOL, RoadParam.DEST_ZONE, RoadParam.START_LEVEL, RoadParam.END_LEVEL) if param.value in values]
    begun = _start(project, provenance.ROAD, name, version, masks, provenance.road_settings(asked, chosen), (*inputs, *extra),
                   provenance.road_params(chosen, mode=mode.value, profile=request.profile, valued=valued, supports=bool(supported), level_destination=destination is not None),
                   supersedes)
    if others:  # el hash de cada otro diseño al preparar: si difiere en la huella, es una entrada (T21) y ``des.input_changed`` vigila que no cambie hasta crearla
        with project.read() as conn:
            seen = _seen(conn, tuple(Use(other, provenance.ROAD_OTHER_DESIGN_ROLE) for other in others), version)
        begun = replace(begun, seen=MappingProxyType({**begun.seen, **seen}))
    yield
    return PreparedRoad(job, begun, chosen, version, start_name, start_ref, support_name, request.layer, profile, _rows(asked, chosen, values, levels, supported),
                        MappingProxyType(values), MappingProxyType(common), supported, others, tuple(notices), code is not None, fid, tuple(followed))


def prepare_road(project: StoreProject, request: RoadRequest, *, version: str | None, masks: access.MaskSet | None = None, code: str | None = None,
                 supersedes: str | None = None, released: Sequence[provenance.ReleasedSupport] = ()) -> PreparedRoad:
    """La preparación entera de :func:`prepare_road_units` de una vez (plan 017 §5.3.1; sin ceder el hilo): la :class:`PreparedRoad`, con los mismos rechazos y sin escribir nada.
    ``version``: la versión activa (su uid o su código; ``VersionError`` ``core.version_required`` si no hay y ``core.version_not_editable`` si no se edita, RF-009-21); ``masks``: las
    de esa versión (al día; sin ellas se cargan, compilándolas antes si faltan); ``released``: lo que da por bueno sin su apoyo (T24)."""
    found = require_version(project, version, provenance.ROAD)
    work = prepare_road_units(project, request, found, _loaded_masks(project, found, masks), code=code, supersedes=supersedes, released=released)
    while True:
        try:
            next(work)
        except StopIteration as stop:
            result: PreparedRoad = stop.value
            return result


# --- Calcular por pasos (spec 017, T20 (a); RF-017-23, 17, 12, 05 (b), 06, 14, 16; RF-015-03, 09, 13, 29; RNF-017-04, 06, 07; plan 017 §5.3.2, §5.4 A0, §5.7 P-4, P-14, §5.8 H-10) -----------------

COMPUTE_PHASE = "road_compute"
"""La fase de los pasos propios de :func:`road_compute_steps` (la malla, el eje, la rasante, los otros diseños y el resultado); la red 2D, la ruta, la sección y el grabado llevan la suya
(``road_net``, ``road_route``, ``road_section`` y ``road_engrave``)."""
_STAGES = 8
"""Las etapas de los pasos propios (el ``total`` de sus ``Progress``): la malla, la red 2D, la ruta, el eje y la rasante, la sección, el grabado, los otros diseños y el resultado."""
_SECTION_PHASE = "road_section"
OtherReader = Callable[[str, tuple[slice, slice]], np.ndarray]
"""Lo que lee la superficie de **otro diseño** de la versión (RF-017-05 (b)) en una ventana de la rejilla: su nombre (el del dato) y la ventana de trabajo (filas y columnas de la rejilla) →
la superficie de esa ventana (m, float64, de su forma). Lo da quien calcula con el proyecto (T20b y T21: ``surfaces.read_surface_window``); el cálculo no lleva proyecto."""


def _stage(done: int, text: str) -> Progress:
    return Progress(COMPUTE_PHASE, done, _STAGES, text)


def _in_layer(job: RoadJob) -> str:
    """El objeto de un rechazo de la pista de ``job``: nombra la pista y su capa (RF-017-04)."""
    return f"Pista «{job.request.name}» de la capa «{job.request.layer}»"


def _no_data_error(job: RoadJob, shown: str, rows: np.ndarray, columns: np.ndarray) -> DesignError:
    """RF-015-09: ``des.entity_nodata`` de la pista de ``job`` por las celdas (filas y columnas de **la rejilla entera**, de norte a sur y de oeste a este) de la superficie de partida ``shown`` que no
    tienen dato bajo su sección o su eje: el área (m²) y el centro de la primera. **Sin ocultarlo con un valor.**"""
    grid = job.grid
    return DesignError("des.entity_nodata", obj=_in_layer(job), field=entity_key(job.code, RoadParam.START), value=shown, layer=job.request.layer, entity=job.request.name,
                       area=round(int(rows.size) * grid.cell_area, 2), surface=shown, role=_START_ROLE, x=float(grid.west + (int(columns[0]) + 0.5) * grid.dx),
                       y=float(grid.north - (int(rows[0]) + 0.5) * grid.dy))


def _route_steps(job: RoadJob, budget_s: float) -> Generator[Progress, None, tuple[road_route.Route, road_net.Corridor]]:
    """A1 y A2 de «trazar» (RF-017-09 a 12; P-14), por pasos: la malla de la ruta (con lo intocable y el peso de «preferible no afectar»), la red 2D desde el destino y desde el origen, el pasillo con la
    holgura de la ruta y la ruta 3D con su presupuesto de estados. Si no hay ruta, el rechazo de RF-017-12 (``des.road_no_route_network``, ``des.road_no_route_corridor`` o ``des.road_budget``: **la
    tercera causa no es «no hay ruta»**) con la capa, la pista, el campo y el valor; nada se registra ni se relaja un límite por su cuenta. ``des.road_dest_level_out_of_zone`` si el destino por cota
    no lo alcanza ningún nodo de su zona."""
    params = job.route
    assert params is not None and job.geometry.origin is not None
    pd, height = job.profile.max_gradient_pct / 100.0, params.max_cut_fill_m
    yield _stage(0, f"Preparando la malla de la ruta de «{job.request.name}»…")
    mesh = road_net.route_mesh(job.grid, job.start, params.mesh_m, job.untouchable, avoid_weight=job.avoid_weight)
    target = road_route.route_target(job, mesh)
    net_dest = yield from pipeline.forward(road_net.network_steps(mesh, target, pd, height, budget_s=budget_s))
    net_origin = yield from pipeline.forward(road_net.network_steps(mesh, mesh.node_of(*job.geometry.origin), pd, height, budget_s=budget_s))
    corridor = road_net.corridor(net_origin, net_dest, params.margin_m)
    found = yield from pipeline.forward(road_route.route_steps(job, corridor, budget_s=budget_s))
    if not found.ok:
        raise road_route.no_route(job, net_origin, net_dest, found).error(job)
    return found, corridor


def _form_axis(job: RoadJob, route: road_route.Route | None, arrival: road_route.Arrival | None) -> road_axis.Axis:
    """El eje con curvas de la pista (A4; RF-017-13, RF-017-14): en «trazar», la ruta simplificada con el origen y el destino **exactos** (el punto de la capa; con un destino por cota, el centro del
    nodo de llegada); en «sobre un eje», la línea dibujada y en «eje 3D», la línea con su Z, **sin modificarlas**. Si el radio que cabe es menor que Rmín, el rechazo de RF-017-14
    (``des.road_radius_below_min``) con la capa, la pista y el perfil; en «eje 3D», que no rechaza (la línea es una entrada: el radio es un aviso, RF-017-18)."""
    profile, geometry = job.profile, job.geometry
    radii = (profile.curve_radius_m, profile.min_radius_m, profile.station_step_m)
    try:
        if job.mode is RoadMode.TRACE:
            assert route is not None and arrival is not None and job.route is not None
            destination = (arrival.x, arrival.y) if isinstance(geometry.destination, LevelDestination) else geometry.destination
            return road_axis.axis_of(route.centers, *radii, simplify_m=job.route.simplify_m, origin=geometry.origin, destination=destination)
        return road_axis.axis_of(geometry.line, *radii, reject_below_minimum=job.mode is not RoadMode.AXIS_3D)
    except road_axis.RadiusBelowMinimum as error:
        raise error.error(layer=job.request.layer, entity=job.request.name, profile=profile) from None


def _terrain_on(job: RoadJob, axis: road_axis.Axis, shown: str) -> np.ndarray:
    """La superficie de partida bajo cada estación del eje (m): la interpolación bilineal de la 011 (``road_section.sample_terrain``) o, donde falta un vecino (una celda sin dato junto al eje o a menos
    de media celda del borde de la rejilla), la de **su propia celda** —como las cotas de inicio y de fin por defecto de la preparación—; si esa tampoco tiene dato, ``des.entity_nodata`` (RF-015-09).
    No se elige otra cota por la persona."""
    grid = job.grid
    x, y = axis.points[:, 0], axis.points[:, 1]
    found = np.array(road_section.sample_terrain(job.start, grid, x, y), dtype=np.float64)
    missing = ~np.isfinite(found)
    if not bool(missing.any()):
        return found
    column = np.floor((x[missing] - grid.west) / grid.dx).astype(np.int64)
    row = np.floor((grid.north - y[missing]) / grid.dy).astype(np.int64)
    inside = (row >= 0) & (row < grid.nrows) & (column >= 0) & (column < grid.ncols)
    if not bool(inside.all()):
        raise ValueError("el eje de la pista sale de la rejilla del proyecto: la preparación rechazó antes el origen, el destino y los vértices que caen fuera (RF-017-04)")
    own = job.start[row, column]
    if not bool(np.isfinite(own).all()):
        bad = ~np.isfinite(own)
        cells = np.unique(row[bad] * grid.ncols + column[bad])
        raise _no_data_error(job, shown, cells // grid.ncols, cells % grid.ncols)
    found[missing] = own
    return found


def _levels(job: RoadJob, axis: road_axis.Axis, terrain: np.ndarray) -> np.ndarray:
    """La rasante en las estaciones del eje (A5; RF-017-15, RF-017-16): en «eje 3D» la Z de la línea, **sin recalcularla**; en los demás modos, la rasante acotada de ``gradient_line`` entre la cota de
    inicio y la de fin (las del trabajo o, sin ellas, el terreno y, con un destino por cota, la pedida). ``des.road_drop_too_steep`` si el desnivel pasa de pd por la longitud del eje."""
    if job.mode is RoadMode.AXIS_3D:  # el contrato de la Z de «eje 3D» (T23): la de la línea en la abscisa de cada estación (``road_axis.plan_of_line``), sin recalcularla
        assert job.geometry.line is not None
        found = road_axis.plan_of_line(axis, job.geometry.line).levels
        assert found is not None
        return found
    destination = job.geometry.destination
    start = float(terrain[0]) if job.start_level_m is None else job.start_level_m
    if job.end_level_m is not None:
        end = job.end_level_m
    elif isinstance(destination, LevelDestination):
        end = destination.level_m
    else:
        end = float(terrain[-1])
    try:
        return road_gradient.gradient_line(axis.stations, terrain, job.profile.max_gradient_pct / 100.0, start, end)
    except road_gradient.DropTooSteep as error:
        raise error.error(layer=job.request.layer, entity=job.request.name, profile=job.profile) from None


def _axis_notices(job: RoadJob, axis: road_axis.Axis, levels: np.ndarray) -> tuple[tuple[Notice, ...], bool]:
    """Los avisos del eje y de la rasante, en orden, y si la pendiente media pasa de la media máxima del perfil: en «trazar» y «sobre un eje», los radios que bajaron del de diseño (RF-017-14) y el aviso
    de la media (RF-017-17: la media, el límite y los tramos de mayor pendiente con su abscisa y su lugar); en «eje 3D», **solo** la comprobación de la línea (RF-017-18: un aviso por tramo que pasa de
    pd, la media y cada estación cuyo radio de la planta, el del círculo por tres estaciones de la línea remuestreada, es menor que Rmín: T23): el radio de diseño no redondea nada de la persona, así que
    «el radio baja» no es un aviso de ese modo. La confirmación expresa y su motivo no son de este cálculo."""
    name = job.request.name
    if job.mode is RoadMode.AXIS_3D:
        assert job.geometry.line is not None
        checked = road_gradient.check_axis_3d(axis, levels, job.profile, name, job.geometry.line)
        return checked, any(notice.code == "des.road_mean_gradient" for notice in checked)
    found = [*axis.notices(name)]
    mean = road_gradient.mean_gradient_notice(axis, levels, job.profile, name)
    if mean is not None:
        found.append(mean)
    return tuple(found), mean is not None


def _road_figures(job: RoadJob, axis: road_axis.Axis, levels: np.ndarray, engraved: road_engrave.Engraved) -> tuple[Any, ...]:
    """Las veintitrés cifras CALCULADO de RF-017-23 (``provenance.road_figures``, con su unidad y el ámbito de la pista): las del eje y la rasante —la longitud, las cotas de inicio y de fin, el desnivel
    (``z_fin − z_inicio``, con signo), la pendiente media (Σ|Δcota| / S, D-7) y la máxima con su abscisa, el radio mínimo (no existe sin curvas), el número de curvas y las anchuras de la calzada y de la
    sección— y las del grabado (``Engraved.figure_values``: el área grabada, el corte y el relleno de la sección y del borde por separado y el neto, la pared, las alturas máximas y la afección de
    «preferible no afectar»)."""
    stations = axis.stations
    steps = np.abs(np.diff(levels)) / np.diff(stations)
    top = int(np.argmax(steps))
    widths = road_profiles.derived(job.profile)
    values: dict[str, float | None] = {
        "des.road_length_m": axis.length_m, "des.road_z_start_m": float(levels[0]), "des.road_z_end_m": float(levels[-1]), "des.road_drop_m": float(levels[-1] - levels[0]),
        "des.road_gradient_mean_pct": road_gradient.mean_gradient(stations, levels) * 100.0, "des.road_gradient_max_pct": float(steps[top]) * 100.0,
        "des.road_gradient_max_station_m": float(stations[top]), "des.road_radius_min_m": axis.min_radius_m, "des.road_curves": int(axis.curve_count),
        "des.road_width_m": widths.carriageway_m, "des.road_section_m": widths.section_m, **engraved.figure_values()}
    return provenance.road_figures(job.request.name, job.code, values)


def road_compute_steps(job: RoadJob, common: Mapping[str, object], *, surface: str | None = None, others: Sequence[str] = (), read_other: OtherReader | None = None,
                       quarry: QuarryOrder | None = None, previous: Previous | None = None, operation: str = "", budget_s: float = road_net.STEP_BUDGET_S
                       ) -> Generator[Progress, None, RoadOutcome]:
    """Los pasos que calculan la pista de ``job`` (RF-017-23, RF-015-03, RF-015-29; plan 017 §5.3.2: el ``road_compute_steps`` que **comparten «Calcular», el recálculo y la reproducción**, como
    ``entity_store.platform_compute_steps``), **sin proyecto y sin escribir nada** (``yield from``; cerrar el generador, Esc, no deja nada ni cambia ninguna entrada): devuelve (valor de ``StopIteration``)
    el :class:`~.road_model.RoadOutcome`, por pasos de ``budget_s`` como mucho (RNF-017-06).

    **Por modo** (P-14): «trazar» encadena A1 a A9 —la red 2D desde el destino y desde el origen, el pasillo, la ruta 3D con su presupuesto de estados (``road_net`` y ``road_route``; sin ruta, el rechazo
    de RF-017-12), el eje con curvas (A4), la rasante acotada (A5), la ventana de trabajo (A0), la sección (A6 y A7) y el grabado con su borde (A8 y A9)—; «sobre un eje», de A4 a A9 (la línea
    dibujada, sin ruta ni red 2D); «eje 3D», la comprobación de A5 (la Z de la línea es la rasante y no se recalcula: un aviso por incumplimiento) y de A6 a A9. **Una ventana de trabajo** por pista
    (A0: :func:`~.road_engrave.engrave_window`, la caja de la sección ampliada por el alcance del borde y dos celdas): la sección y el borde se miden en ella, la rejilla entera solo se lee y se escribe
    una vez (quien crea, T21; ``RoadOutcome.compose``).

    Los rechazos de la persona salen como ``DesignError`` al avanzar, con la capa, la pista, el campo y el valor (RF-017-04) y **sin registrar nada ni elegir un valor por ella**: sin ruta (RF-017-12:
    ``des.road_no_route_network``, ``des.road_no_route_corridor`` y ``des.road_budget``), el radio que cabe menor que Rmín (RF-017-14), el desnivel que pasa de pd por la longitud (RF-017-16) y la
    **falta de dato** en la superficie de partida bajo la sección (RF-015-09: ``des.entity_nodata``; bajo el borde, lo que llega a celdas sin dato es el aviso de RF-015-13, como en la plataforma).

    ``common`` son los parámetros del proyecto que lee el cálculo (``provenance.PLATFORM_COMMON_PARAMS``, ya resueltos: la tolerancia de cara, el umbral de la magnitud, el espesor mínimo y el salto
    creado); ``surface``, el nombre del dato de la superficie de partida (para el rechazo por falta de dato; por defecto, el de la petición); ``quarry``, la otra superficie de la cantera de la 014 si la
    pista parte de una de las dos (RF-015-14); ``previous`` y ``operation``, los de la magnitud de RF-013-30 (como ``platform_outcome``). **Los otros diseños** (RF-017-05 (b): ``others`` son los
    nombres de los datos de :attr:`PreparedRoad.others` y ``read_other``, quien lee su superficie **en la ventana de trabajo**, una a una): si en la huella de la pista (la sección y lo que su borde
    alcanza) la partida difiere de alguno en más del espesor mínimo, el aviso de :func:`other_design_notices` y el nombre en ``RoadOutcome.other_designs`` (lo que la T21 registra como entrada de la
    pista, con su hash: si cambia, la pista queda obsoleta con su causa); sin ninguno que difiera, no hay nada que registrar. **La huella que la rejilla recorta** (RF-015-13, T20b: la sección que sale
    de la rejilla, ``road_section.clipped_steps``) es un aviso más (``des.road_footprint_clipped``), tras los del eje. **No** arma la confirmación de la media por encima de pm ni la de la calzada fuera de
    su rasante, ni el resumen: son de :func:`check_road_confirmed` y :func:`summary_of` (T20b; ``RoadOutcome.mean_exceeded`` y ``RoadOutcome.off_level`` dan lo que decide)."""
    if not isinstance(job, RoadJob):
        raise TypeError(f"el trabajo de una pista es RoadJob, no {job!r}")
    names = tuple(others)
    if names and read_other is None:
        raise ValueError("las superficies de otros diseños (RF-017-05 (b)) se leen con read_other: el cálculo no lleva proyecto")
    name, grid, profile = job.request.name, job.grid, job.profile
    shown = job.request.start if surface is None else surface
    ratio = _project_number(common, WARNING_RATIO)
    thickness = _thickness(_project_number(common, VERIFY_MIN_THICKNESS))
    yield _stage(0, f"Calculando la pista «{name}»…")
    route: road_route.Route | None = None
    corridor: road_net.Corridor | None = None
    arrival: road_route.Arrival | None = None
    if job.mode is RoadMode.TRACE:
        route, corridor = yield from _route_steps(job, budget_s)
        arrival = road_route.arrival_of(job, route)
    yield _stage(3, f"Formando el eje y la rasante de «{name}»…")
    axis = _form_axis(job, route, arrival)
    terrain = _terrain_on(job, axis, shown)
    levels = _levels(job, axis, terrain)
    found, exceeded = _axis_notices(job, axis, levels)
    yield _stage(4, f"Midiendo la sección de «{name}»…")
    window = road_engrave.engrave_window(axis, profile, grid)  # A0: la ventana de trabajo de la pista
    carriageway = road_profiles.derived(profile).carriageway_m
    section = yield from pipeline.forward(pace_progress(
        road_section.section_steps(axis, carriageway, profile.shoulder_m, profile.berm_m, job.start, grid, window), budget_s, phase=_SECTION_PHASE,
        running=f"Midiendo la sección de «{name}»…", finished=f"Sección de «{name}» medida"))
    empty = section.cells & ~np.isfinite(job.start[window])  # RF-015-09: ninguna celda de la sección sin dato en la superficie de partida
    if bool(empty.any()):
        rows, columns = np.nonzero(empty)
        raise _no_data_error(job, shown, rows + window[0].start, columns + window[1].start)
    clipped = yield from pipeline.forward(pace_progress(
        road_section.clipped_steps(axis, carriageway, profile.shoulder_m, profile.berm_m, job.start, grid), budget_s, phase=_SECTION_PHASE,
        running=f"Comprobando lo que la rejilla recorta de la sección de «{name}»…", finished=f"Huella de «{name}» comprobada"))
    levels_by_cell = section.levels(axis.stations, levels)
    yield _stage(5, f"Grabando la pista «{name}»…")
    engraved = yield from pipeline.forward(road_engrave.engrave_steps(job, section, levels_by_cell, common, budget_s=budget_s, quarry=quarry))
    differing: list[str] = []
    others_found: list[Notice] = []
    if names:
        assert read_other is not None
        yield _stage(6, f"Comparando la partida de «{name}» con otros diseños…")
        influence = engraved.footprint | engraved.in_reach  # la huella de la pista: la sección y lo que su borde alcanza
        here = job.start[window]
        sub = _window_grid(grid, window)
        for other in names:
            values = np.asarray(read_other(other, window), dtype=np.float64)
            if values.shape != here.shape:
                raise ValueError(f"la superficie de «{other}» es de la forma {values.shape} y la ventana de trabajo de la pista, {here.shape}")
            differs = other_design_notices(name, sub, influence, here, {other: values}, thickness)
            if differs:
                differing.append(other)
                others_found.extend(differs)
            yield _stage(6, f"Comparada la partida de «{name}» con «{other}»")
    yield _stage(7, f"Cifras de la pista «{name}»…")
    figures = _road_figures(job, axis, levels, engraved)
    cut_off = (Notice("des.road_footprint_clipped", {"entity": name, "cells": clipped[0], "area": clipped[0] * grid.cell_area, "x": round(clipped[1], 2), "y": round(clipped[2], 2)}),) if clipped[0] else ()
    # RF-015-13: lo que la rejilla recorta de la huella, tras los avisos del eje
    notices = (*found, *cut_off, *others_found, *engraved.notices, *magnitude_notices(engraved.cut_m3, engraved.fill_m3, previous, ratio, operation))
    summary = None
    if route is not None and corridor is not None and arrival is not None:
        assert job.route is not None and route.cost is not None
        summary = RouteReport(route.mesh.mesh_m, job.route.margin_m, corridor.nodes, corridor.lower_bound_m, len(route.nodes), route.expanded, route.seen, route.budget, float(route.cost),
                              route.turns, arrival)
    outcome = RoadOutcome(name, job.code, job.mode, window, engraved.surface, engraved.footprint, figures, notices, axis=axis, terrain=terrain, levels=levels, engraved=engraved,
                          route=summary, other_designs=tuple(differing), mean_exceeded=exceeded)
    yield _stage(_STAGES, f"Pista «{name}» calculada")
    return outcome


# --- Calcular: con qué se compara, la calzada fuera de su rasante, las dos confirmaciones y el resumen (spec 017, T20b; RF-017-17, 22, 12, 23; RF-015-03, 13; D-6; plan 017 §5.3.2, §5.8 H-10) -----------

_MAGNITUDE_CUT = ("des.road_cut_m3", "des.road_edge_cut_m3")
_MAGNITUDE_FILL = ("des.road_fill_m3", "des.road_edge_fill_m3")
CONFIRMED = "road_confirmed"
"""La clave de los ajustes de ``des.road`` donde queda **lo que la persona confirmó expresamente** al crearla (:class:`RoadConfirmed`): la pendiente media por encima de pm (``mean_gradient``: la media, el límite
y **su motivo**) y la calzada que no queda en su rasante (``carriageway``: su área y su diferencia máxima), con quién lo confirmó y cuándo (RF-017-17, RF-017-22). No es de ``provenance.road_settings`` (que
no la conoce: se confirma después de calcular): la añade la creación (T21) y la arrastra el recálculo (T22), como ``CONFIRMED`` de la retirada y ``COUNTERSLOPE_CONFIRMED`` de la plataforma."""


def road_previous(conn: sqlite3.Connection, version: Version, code: str) -> Previous | None:
    """Con qué se compara el desmonte y el terraplén de una pista (RF-015-13, RF-013-30, D-25; como :func:`~.entity_store.platform_previous`): la operación ``des.road`` de la entidad de código ``code`` de la
    revisión **congelada** más reciente de la versión ``version`` y sus cifras de la sección y del borde sumadas (``des.road_cut_m3`` + ``des.road_edge_cut_m3`` y las del relleno), como
    ``report.Previous`` (``operation``: su nombre; ``revision``: ``V01.r1``). Por el código y no por el nombre: es inmutable en la versión y sobrevive a renombrarla. ``None`` si la versión no tiene ninguna
    congelada, ninguna operación de esa entidad o sin esas cifras. Solo lee."""
    revision = versions_read.last_frozen(conn, version.uid)
    if revision is None:
        return None
    rows = conn.execute(
        "SELECT uid, settings FROM gb_operation WHERE revision_uid = ? AND op_type = ? AND status = ? ORDER BY fid DESC",
        (revision.uid, provenance.ROAD, OperationStatus.DONE.value)).fetchall()
    keys = (*_MAGNITUDE_CUT, *_MAGNITUDE_FILL)
    for uid, settings in rows:
        found = json.loads(settings) if settings else {}
        if found.get("code") != code:
            continue
        figures = {str(key): float(value) for key, value in conn.execute(
            f"SELECT key, value FROM gb_figure WHERE operation_uid = ? AND key IN ({', '.join('?' for _ in keys)})", (uid, *keys)) if value is not None}
        if len(figures) < len(keys):
            return None
        name = found.get("name")
        return Previous(str(name) if isinstance(name, str) and name else code, f"{version.code}.r{revision.number}", sum(figures[key] for key in _MAGNITUDE_CUT),
                        sum(figures[key] for key in _MAGNITUDE_FILL))
    return None


def road_obsolete(project: StoreProject, prepared: PreparedRoad, *, supersedes: str | None = None) -> tuple[Obsolete, ...]:
    """**Lo que quedará obsoleto al crear** la pista ``prepared`` (RF-015-03, RF-015-16): una pista nueva no deja obsoleto nada (lo que se apoye después en ella sale de su vigencia, no de su creación); la que
    **sustituye** una operación (``supersedes``: un recálculo) deja obsoleto lo que dependía de lo que escribió, en cascada (``DEPENDENT``), como la retirada y el contrafuerte. Solo lee."""
    if supersedes is None:
        return ()
    with project.read() as conn:
        written = [str(row[0]) for row in conn.execute(
            "SELECT item_uid FROM gb_operation_io WHERE operation_uid = ? AND direction = 'out' AND item_kind = 'dataset' ORDER BY fid", (supersedes,))]
        found = entity_store._dependents(conn, written, prepared.version.uid, exclude=(supersedes,))
    return tuple(entity_store._consumer(ObsoleteKind.DEPENDENT, uid, op_type, name) for uid, op_type, name in found)


def _blocking_zone(masks: Any, window: tuple[slice, slice], group: road_engrave.OffLevelGroup) -> str | None:
    """El código de la zona de las máscaras que impide mover las celdas de ``group`` (un grupo de la calzada que no queda en su rasante, de la ventana ``window``): de las que prohíben **lo que se le pide**
    (el corte si está por encima, el relleno si está por debajo: ``preview._rule``, la misma regla que el resumen de la plataforma), la que cubre más de sus celdas (a igual cobertura, la de código
    menor); ``None`` si ninguna lo explica (un límite, su banda…)."""
    cut = group.cause is road_engrave.EngraveCause.CUT_DENIED
    rows, cols = np.divmod(group.index, window[1].stop - window[1].start)
    rows, cols = rows + window[0].start, cols + window[1].start
    top, bottom, left, right = int(rows.min()), int(rows.max()), int(cols.min()), int(cols.max()) + 1
    cells = np.zeros((bottom - top + 1, right - left), dtype=bool)
    cells[rows - top, cols - left] = True
    best: str | None = None
    most = 0
    for code in sorted(masks.zones):
        rule = _rule(masks, code)
        if rule is None or not (rule[0] if cut else rule[1]):
            continue
        runs = masks.zones[code].between_rows(top, bottom)
        if not len(runs):
            continue
        count = int(np.count_nonzero(runs.mask(cells.shape, (top, left)) & cells))
        if count > most:
            best, most = code, count
    return best


def carriageway_notices(outcome: RoadOutcome, masks: Any, *, names: Mapping[str, str], declared: Mapping[str, str]) -> tuple[Notice, ...]:
    """Los avisos de RF-017-22 de la calzada que no queda en su rasante, **antes de crear** y con la confirmación expresa, uno por grupo de celdas (``outcome.off_level``, en su orden), con el área (m²), la
    diferencia máxima (m) y el lugar **y la restricción o la entidad que lo impide**: si el grupo pasa de la altura máxima de desmonte y terraplén (``des.road_carriageway_height``), esa altura; si no, la zona
    de las máscaras que cubre más de sus celdas y prohíbe lo que se le pide (:func:`_blocking_zone`): la que declara una entidad (``dec__…``, ``declared``: código → nombre de la entidad), **con su nombre**
    (``des.road_carriageway_entity``), o una restricción normal con su nombre y su código (``names``: código → nombre; ``des.road_carriageway_masks``); y, si ninguna zona lo explica, el límite de las
    máscaras (``des.road_blocker_masks``, en el idioma de quien lee). ``masks`` son las de la versión. Sin calzada fuera de su rasante, ninguno."""
    engraved = outcome.engraved
    if engraved is None:
        return ()
    found: list[Notice] = []
    for group in engraved.off_level:
        if group.cause is road_engrave.EngraveCause.MAX_HEIGHT:
            found.append(road_engrave.carriageway_notice(group, outcome.name, height_m=engraved.max_height_m))
            continue
        code = _blocking_zone(masks, outcome.window, group)
        if code is None:
            found.append(road_engrave.carriageway_notice(group, outcome.name, blocker=(Named("des.road_blocker_masks"),)))
            continue
        base = code[:-len(_INNER)] if code.endswith(_INNER) else code
        if base.startswith(DECLARED_PREFIX):
            found.append(road_engrave.carriageway_notice(group, outcome.name, other_entity=declared.get(base, base[len(DECLARED_PREFIX):].upper().replace("_", "-"))))
            continue
        shown = names.get(base, "")
        found.append(road_engrave.carriageway_notice(group, outcome.name, blocker=f"{shown} ({base})" if shown and shown != base else base))
    return tuple(found)


def road_held_notices(outcome: RoadOutcome, masks: Any, *, names: Mapping[str, str], declared: Mapping[str, str]) -> tuple[Notice, ...]:
    """**Lo que la pista no mueve por una restricción** (RF-015-13): las celdas de su sección que las máscaras no dejan cortar ni rellenar (``Engraved.cut_denied`` y ``fill_denied``) y las de su borde que no
    dejan mover (``Engraved.held``), con la restricción que lo impide —la que declara otra entidad, con **su nombre**, o una restricción normal con su nombre y su código— y su área y su lugar
    (:func:`~.preview.held_notices`, la misma cuenta que el resumen de la plataforma). Sin celdas que no se muevan, ninguno."""
    engraved = outcome.engraved
    if engraved is None:
        return ()
    return held_notices(outcome.name, masks, outcome.window, cut=engraved.cut_denied, fill=engraved.fill_denied, edge=engraved.held, names=names, declared=declared)


def summary_of(outcome: RoadOutcome, *, version: str, profile: road_profiles.RoadProfile, start_notices: Sequence[Notice] = (), followed: Sequence[Notice] = (), carriageway: Sequence[Notice] = (),
               held: Sequence[Notice] = (), obsolete: Sequence[Obsolete] = ()) -> RoadSummary:
    """El resumen de «Calcular» la pista de ``outcome`` (RF-015-03, RF-017-23, RF-017-12, RF-017-17, RF-017-22; H-10; **puro**: sin proyecto) como :class:`~.preview.RoadSummary`: las cifras que se registrarán,
    la longitud, las cotas de inicio y de fin, la pendiente media y la máxima (con su abscisa y su lugar), el radio mínimo y las curvas, el corte y el relleno de la sección y del borde juntos y el neto,
    **la holgura del pasillo** (``margin_m``: la ruta cambia con ella, H-10) y si pide confirmar la media (``needs_mean_confirmation``, con el límite ``mean_limit_pct`` del perfil ``profile``) o la
    calzada (``needs_carriageway_confirmation``, con su área), y los avisos **en el orden en que se enseñan**: los de la partida (``start_notices``: RF-017-05 (a), «no llega al fondo», que ``prepare_road``
    calcula al preparar), **las cotas que la pista vuelve a tomar de su origen al recalcularla** (``followed``: T24b, RF-017-03; :meth:`LevelFollow.notice`), la nota de la ruta (solo «trazar»), los del cálculo (los tramos del salto creado, de diez en diez como en la plataforma: ``edges.summary_notices``), los de la calzada que no queda
    en su rasante (``carriageway``), lo que no se mueve por una restricción (``held``) y, al final, lo que quedará obsoleto (``obsolete``) con su causa. ``version`` es el código de la versión. ``ValueError`` si ``outcome`` no lleva el eje, la rasante y el grabado (el de :func:`road_compute_steps` siempre los lleva)."""
    engraved, axis, levels = outcome.engraved, outcome.axis, outcome.levels
    if engraved is None or axis is None or levels is None:
        raise ValueError("el resumen de una pista pide su eje, su rasante y su grabado: son los del resultado de road_compute_steps")
    found = {figure.key: figure.value for figure in outcome.figures}
    top = int(np.argmax(np.abs(np.diff(levels)) / np.diff(axis.stations)))
    cut = found["des.road_cut_m3"] + found["des.road_edge_cut_m3"]
    fill = found["des.road_fill_m3"] + found["des.road_edge_fill_m3"]
    route = outcome.route
    kept = tuple(obsolete)
    notes: list[Notice] = []
    if route is not None:
        notes.append(Notice("des.road_route_margin", {"entity": outcome.name, "mesh": route.mesh_m, "margin": route.margin_m, "expanded": route.expanded, "budget": route.budget}))
    notices = (*start_notices, *followed, *notes, *edges.summary_notices(outcome.notices), *carriageway, *held, *obsolete_notices(outcome.name, version, kept))
    return RoadSummary(
        outcome.name, outcome.code, version, outcome.mode.value, profile.code, outcome.figures, axis.length_m, float(levels[0]), float(levels[-1]), found["des.road_gradient_mean_pct"],
        found["des.road_gradient_max_pct"], found["des.road_gradient_max_station_m"], float(axis.points[top, 0]), float(axis.points[top, 1]), axis.min_radius_m, axis.curve_count, cut, fill,
        cut - fill, None if route is None else route.margin_m, bool(outcome.mean_exceeded), float(profile.max_mean_gradient_pct), engraved.needs_confirmation,
        sum(group.area_m2 for group in engraved.off_level), notices, kept)


def road_summary(project: StoreProject, version: Version, prepared: PreparedRoad, outcome: RoadOutcome, masks: Any, *, supersedes: str | None = None) -> RoadSummary:
    """El resumen de «Calcular» la pista ``prepared`` en ``version`` (RF-015-03, RF-017-23, RF-017-22, RF-015-13): :func:`summary_of` con la restricción o la entidad que impide mover la calzada
    (:func:`carriageway_notices`), los avisos de la partida (``prepared.notices``: RF-017-05 (a)) y lo que la pista no mueve por una restricción (:func:`road_held_notices`; las restricciones y las
    entidades que las declaran se leen del proyecto **solo si hay algo que nombrar**) y lo que quedará obsoleto al crearla (:func:`road_obsolete`; ``supersedes``: la operación que sustituye). ``masks`` son las de la versión. **Solo lee.**"""
    engraved = outcome.engraved
    carriageway: tuple[Notice, ...] = ()
    held: tuple[Notice, ...] = ()
    if engraved is not None and (engraved.off_level or bool((engraved.cut_denied | engraved.fill_denied | engraved.held).any())):
        names, declared = entity_store._restrictions(project, version)
        carriageway = carriageway_notices(outcome, masks, names=names, declared=declared)
        held = road_held_notices(outcome, masks, names=names, declared=declared)
    return summary_of(outcome, version=version.code, profile=prepared.profile, start_notices=prepared.notices, followed=tuple(item.notice(outcome.name) for item in prepared.followed),
                      carriageway=carriageway, held=held, obsolete=road_obsolete(project, prepared, supersedes=supersedes))


_CONFIRMED_EPS = 1e-9
"""Lo que puede pasar una cifra nueva de la confirmada y seguir siendo la misma (relativo y absoluto): el ruido de la última cifra, no un cambio."""
_DIFFERENCE_ROUNDING_M = 5e-4
"""La diferencia máxima de la calzada se anota redondeada al milímetro (:func:`road_confirmation`): la mitad de ese redondeo (m) no es un cambio de lo confirmado."""


@dataclass(frozen=True, slots=True)
class RoadConfirmed:
    """Lo que la persona confirmó **expresamente** al crear la pista (RF-017-17, RF-017-22): quién (``decided_by``) y cuándo (``decided_on``, UTC); de la pendiente media por encima de pm, la media
    (``mean_pct``), el límite del perfil (``mean_limit_pct``) y **su motivo** (``reason``; ``None``: nada que confirmar); de la calzada que no queda en su rasante, el área (``carriageway_m2``) y la diferencia
    máxima (``carriageway_difference_m``; ``None``: nada que confirmar). Es lo que :meth:`settings` anota en los ajustes de la operación (:data:`CONFIRMED`) y lo que :func:`confirmed_of` lee de vuelta."""

    decided_by: str
    decided_on: str
    mean_pct: float | None = None
    mean_limit_pct: float | None = None
    reason: str | None = None
    carriageway_m2: float | None = None
    carriageway_difference_m: float | None = None

    def covers_mean(self, mean_pct: float) -> bool:
        """Si una pendiente media ``mean_pct`` (%) entra en lo confirmado: no pasa de la que la persona confirmó (con el redondeo de la última cifra). Sin la media confirmada, nada entra."""
        return self.mean_pct is not None and mean_pct <= self.mean_pct * (1.0 + _CONFIRMED_EPS) + _CONFIRMED_EPS

    def covers_carriageway(self, area_m2: float, difference_m: float) -> bool:
        """Si una calzada fuera de su rasante de ``area_m2`` (m²) y ``difference_m`` (m) de diferencia máxima entra en lo confirmado: **ni su área ni su diferencia** pasan de lo confirmado (la diferencia
        se anota redondeada al milímetro: la mitad de ese redondeo no cuenta). Sin la calzada confirmada, nada entra."""
        return (self.carriageway_m2 is not None and self.carriageway_difference_m is not None
                and area_m2 <= self.carriageway_m2 * (1.0 + _CONFIRMED_EPS) + _CONFIRMED_EPS
                and difference_m <= self.carriageway_difference_m + _DIFFERENCE_ROUNDING_M + _CONFIRMED_EPS)

    def settings(self) -> dict[str, Any]:
        """Lo que se anota en los ajustes de la operación (JSON): ``mean_gradient`` (la media, el límite y el motivo) y ``carriageway`` (el área y la diferencia máxima), cada uno si se confirmó, con su
        decisor y su fecha."""
        found: dict[str, Any] = {}
        who = {"decided_by": self.decided_by, "decided_on": self.decided_on}
        if self.mean_pct is not None:
            found["mean_gradient"] = {"mean_pct": self.mean_pct, "limit_pct": self.mean_limit_pct, "reason": self.reason, **who}
        if self.carriageway_m2 is not None:
            found["carriageway"] = {"area_m2": self.carriageway_m2, "difference_m": self.carriageway_difference_m, **who}
        return found


def confirmed_of(settings: Mapping[str, Any]) -> RoadConfirmed | None:
    """Lo confirmado que guardan los ajustes ``settings`` de una operación ``des.road`` (:data:`CONFIRMED`), o ``None`` si no lo llevan (no hubo nada que confirmar). ``ValueError`` si lo llevan y no es una
    confirmación (nombrando el campo): sin quién ni cuándo, o no es un diccionario."""
    found = settings.get(CONFIRMED) if isinstance(settings, Mapping) else None
    if found is None:
        return None
    if not isinstance(found, Mapping):
        raise ValueError(f"los ajustes de una pista, «{CONFIRMED}», son un diccionario, no {found!r}")
    mean, carriageway = found.get("mean_gradient"), found.get("carriageway")
    kept = [item for item in (mean, carriageway) if isinstance(item, Mapping)]
    if not kept:
        return None
    who, when = kept[0].get("decided_by"), kept[0].get("decided_on")
    if not isinstance(who, str) or not isinstance(when, str):
        raise ValueError(f"los ajustes de una pista, «{CONFIRMED}», no dicen quién confirmó ni cuándo")
    reason = mean.get("reason") if isinstance(mean, Mapping) else None
    return RoadConfirmed(
        who, when, float(mean["mean_pct"]) if isinstance(mean, Mapping) else None, float(mean["limit_pct"]) if isinstance(mean, Mapping) else None, reason if isinstance(reason, str) else None,
        float(carriageway["area_m2"]) if isinstance(carriageway, Mapping) else None, float(carriageway["difference_m"]) if isinstance(carriageway, Mapping) else None)


def _mean_notice(outcome: RoadOutcome) -> Notice:
    """El aviso de la pendiente media por encima de pm del resultado (``des.road_mean_gradient``: la media y el límite); error del programa si el resultado dice que la pasa y no lo lleva."""
    for notice in outcome.notices:
        if notice.code == "des.road_mean_gradient":
            return notice
    raise ValueError("el resultado dice que la pendiente media pasa de pm y no lleva su aviso (des.road_mean_gradient)")


def check_road_confirmed(outcome: RoadOutcome, *, mean: bool = False, carriageway: bool = False, reason: str | None = None) -> None:
    """**No se crea la pista sin la confirmación expresa** (RF-017-17, RF-017-22, D-6; como la contrapendiente de RF-015-23): con la pendiente media por encima de pm (``outcome.mean_exceeded``) y sin
    ``mean``, ``des.road_mean_unconfirmed`` con la media y el límite; con ``mean`` y **sin un motivo** (``reason`` ausente, vacío o en blanco), ``des.road_mean_reason`` (el motivo queda registrado y **no
    bloquea**: con él se crea); con alguna celda de la calzada fuera de su rasante (``outcome.off_level``) y sin ``carriageway``, ``des.road_carriageway_unconfirmed`` con el área y la diferencia máxima. Sin
    nada que confirmar no pide nada, y confirmar de más no estorba. No escribe: la confirmación, su decisor, su fecha y el motivo los registra la creación (:func:`road_confirmation`, T21)."""
    obj = f"Pista «{outcome.name}»"
    if outcome.mean_exceeded:
        notice = _mean_notice(outcome)
        values = {"entity": outcome.name, "mean": round(float(notice.values["mean"]), 2), "limit": float(notice.values["limit"])}
        if not mean:
            raise DesignError("des.road_mean_unconfirmed", obj=obj, field="confirmación", value=False, **values)
        if reason is None or not reason.strip():
            raise DesignError("des.road_mean_reason", obj=obj, field="motivo", value=reason, **values)
    groups = outcome.off_level
    if groups and not carriageway:
        raise DesignError("des.road_carriageway_unconfirmed", obj=obj, field="confirmación", value=False, entity=outcome.name, area=sum(group.area_m2 for group in groups),
                          difference=round(max(group.max_m for group in groups), 3))


def road_confirmation(project: Any, outcome: RoadOutcome, *, mean: bool, carriageway: bool, reason: str | None, decided_by: str | None) -> RoadConfirmed | None:
    """Lo que se confirma al crear (con ``mean`` y ``carriageway``, de lo que haya que confirmar en ``outcome``): quién (``decided_by``; por defecto, quien tiene abierto el proyecto), cuándo (ahora, UTC),
    la media, el límite y el motivo, y el área y la diferencia máxima de la calzada; ``None`` si no había nada que confirmar. ``project`` es el ``StoreProject`` (su sesión y su reloj)."""
    asked_mean = bool(outcome.mean_exceeded) and mean
    groups = outcome.off_level
    asked_carriageway = bool(groups) and carriageway
    if not asked_mean and not asked_carriageway:
        return None
    notice = _mean_notice(outcome) if asked_mean else None
    return RoadConfirmed(
        decided_by or project.session.user_host, format_utc(project.clock.now()), None if notice is None else float(notice.values["mean"]), None if notice is None else float(notice.values["limit"]),
        ((reason or "").strip() or None) if asked_mean else None, sum(group.area_m2 for group in groups) if asked_carriageway else None,
        round(max(group.max_m for group in groups), 3) if asked_carriageway else None)


# --- Crear: la operación, los datos, la huella y las dependencias (spec 017, T21; RF-017-01, RF-017-03, RF-017-05 (b), RF-017-17, RF-017-22, RF-017-23; RF-015-01, RF-015-02, RF-015-04, RF-015-10, RF-015-12,
# RF-015-15 y RF-015-29; RNF-017-07 y RNF-017-10; plan 017 §5.2.3, §5.3.2, §5.7 P-1 y P-5; D-15) ---------------------------------------------------------------------------------------------------------

_STORE_PHASE = "road_store"
_CURVE_TOL_M = 1e-9
"""Lo que una estación puede quedar antes del comienzo de un arco (o después de su final) y seguir siendo de él: el ruido de la última cifra de una abscisa (m)."""
Row = tuple[Any, ...]


def _json(value: object) -> str:
    """``value`` como JSON compacto y estable (``allow_nan`` falso: nada que no sea finito)."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _plain(value: object) -> object:
    """Un valor de un aviso que ``json`` no escribe solo: un escalar de numpy y un texto que se dice en el idioma de quien lee (:class:`~.preview.Named`: su código y sus valores)."""
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Named):
        return {"code": value.code, "values": dict(value.values)}
    raise TypeError(f"el valor {value!r} de un aviso no se puede guardar como JSON")


def _notice_text(notice: Notice) -> str:
    """Un aviso o una nota como en ``des_prp_``: su código y sus valores en JSON (:func:`_plain`: las pistas llevan listas de tramos como ``Named``)."""
    return json.dumps({"code": notice.code, "values": dict(notice.values)}, sort_keys=True, ensure_ascii=False, allow_nan=False, default=_plain)


def _place(x: float | None, y: float | None, what: str) -> str | None:
    """El lugar absoluto ``x;y`` de una cifra (float64 en texto, como el de la 013, la 014 y la 015), o ``None`` sin él."""
    if x is None or y is None:
        return None
    return f"{_real(what + '.x', x)!r};{_real(what + '.y', y)!r}"


def road_geometry_sha256(geometry: RoadGeometry) -> str:
    """El hash de la geometría de origen de una pista (SHA-256 en hexadecimal; RF-017-01, RF-015-01): el origen y el destino (un punto: su X e Y absolutas en float64, ``<f8``, **tal cual**: el
    último bit cuenta; o un destino por cota: su cota, su tolerancia y los anillos de su zona) o la línea de su capa (con su Z si la tiene), cada cosa con su etiqueta. Lo que guarda ``des_epr_``
    (``geometry_sha256``): saber si la geometría de la capa es la de la entidad. **Sin proyecto**: lo repite la reproducción."""
    digest = hashlib.sha256()

    def feed(tag: str, values: object) -> None:
        array = np.ascontiguousarray(values, dtype="<f8")
        digest.update(f"{tag}:{array.shape};".encode())
        digest.update(array.tobytes())

    if geometry.origin is not None:
        feed("origin", geometry.origin)
    destination = geometry.destination
    if isinstance(destination, LevelDestination):
        feed("level", (destination.level_m, destination.tolerance_m))
        digest.update(f"zone:{len(destination.zone)};".encode())
        for part in destination.zone:
            digest.update(f"part:{len(part)};".encode())
            for ring in part:
                feed("ring", ring)
    elif destination is not None:
        feed("destination", destination)
    if geometry.line is not None:
        feed("line", geometry.line)
    return digest.hexdigest()


def road_entity_rows(job: RoadJob, outcome: RoadOutcome, *, fid: int, start_surface: str, support_surface: str | None) -> list[Row]:
    """La fila de ``des_epr_`` (columnas de :data:`~.store.ENTITY_COLUMNS`) de la pista de ``job`` con su ``outcome`` (RF-015-01, RF-017-23): **una**, con los atributos de la entidad —su código, su
    nombre, su tipo ``road``, los datos de su superficie de partida (``start_surface``) y de apoyo, la capa y el ``fid`` (``fid``) de su geometría de origen y el hash de esa geometría
    (:func:`road_geometry_sha256`), el modo y las celdas de **la huella de la sección**—, su ventana de trabajo, esa huella en tramos de fila (``entity_store.footprint_runs``: lo que leen la zona
    declarada de otra entidad, la capa de entidades y lo que se apoya en la pista) y los puntos de su eje (absolutos, float64, exactos). Solo depende de lo que se lee para calcular, no del proyecto:
    lo repite la reproducción desde lo congelado."""
    axis = outcome.axis
    if axis is None:
        raise ValueError("la fila de la huella de una pista pide su eje: es el del resultado de road_compute_steps")
    window = outcome.window
    runs = entity_store.footprint_runs(outcome.footprint, window)
    return [(job.code, job.request.name, EntityKind.ROAD.value, start_surface, support_surface, job.request.layer, int(fid), road_geometry_sha256(job.geometry), job.mode.value,
             int(np.count_nonzero(outcome.footprint)), 0, _json([int(window[0].start), int(window[0].stop), int(window[1].start), int(window[1].stop)]), _json([list(run) for run in runs]),
             _json(axis.points.tolist()))]


def road_axis_rows(outcome: RoadOutcome) -> list[Row]:
    """Las filas de ``des_rdx_`` (columnas de :data:`~.store.ROAD_AXIS_COLUMNS`; RF-017-03, RF-017-23) del resultado ``outcome``: **una por estación** del eje, en el orden de la abscisa, con su lugar
    absoluto (``x`` e ``y``), la cota del terreno de partida y la de la rasante, la pendiente del tramo que empieza en ella en % (con signo: positiva si sube en el sentido de la marcha; **la última
    repite la del último tramo**: no tiene tramo que empiece en ella), el radio de la curva en que está (vacío en una recta) y el número de esa curva (desde 1, en el orden del eje; 0 en una recta). Una
    estación es de un arco si queda entre su comienzo (incluido) y su final (excluido). Es lo que lee **otra pista que parte de este eje** (``RDW-001@s``, :func:`axis_point_at`). Nada es NaN ni
    infinito (``ValueError``)."""
    axis, terrain, levels = outcome.axis, outcome.terrain, outcome.levels
    if axis is None or terrain is None or levels is None:
        raise ValueError("el eje de una pista por estaciones pide su eje, el terreno y la rasante: son los del resultado de road_compute_steps")
    stations = axis.stations
    steps = np.diff(levels) / np.diff(stations) * 100.0
    gradient = np.append(steps, steps[-1])
    radius = np.full(stations.shape, np.nan)
    number = np.zeros(stations.shape, dtype=np.int64)
    for index, curve in enumerate(axis.curves, start=1):
        inside = (number == 0) & (stations >= curve.station_m - _CURVE_TOL_M) & (stations < curve.station_m + curve.length_m - _CURVE_TOL_M)
        radius[inside] = curve.radius_m
        number[inside] = index
    rows: list[Row] = []
    for at, (s, (x, y)) in enumerate(zip(stations.tolist(), axis.points.tolist(), strict=True)):
        rows.append((_real("station_m", s), _real("x", x), _real("y", y), _real("terrain_m", terrain[at]), _real("level_m", levels[at]), _real("gradient_pct", gradient[at]),
                     None if number[at] == 0 else _real("radius_m", radius[at]), int(number[at])))
    return rows


def road_report_rows(outcome: RoadOutcome) -> list[Row]:
    """Las filas de ``des_prp_`` (formato largo: ``quantity, value, unit_code, note``, como ``des_rpt_`` y ``des_qrp_``; RF-017-23, RF-017-17, RF-017-22, RF-015-02, RF-015-13) de la pista ``outcome``,
    en este orden: la huella (celdas y área), el eje (longitud, estaciones, paso, desviación, curvas, **una fila por curva** con su radio y, en la nota, el vértice, el radio de diseño, el cambio de
    dirección, la tangente, el largo, la abscisa y el lugar), la rasante (cotas, desnivel, pendientes con el lugar de la máxima, y ``mean_exceeded``: 1 si la media pasa de pm), la sección y el borde
    (corte y relleno, celdas, alturas máximas, lo que las máscaras no dejan mover, **una fila por grupo de la calzada que no queda en su rasante** con su causa, sus celdas, su área y su lugar, los
    ángulos, el alcance, la pared con una fila por causa y el salto creado de la 014 con una fila por tramo), la afección de «preferible no afectar», la ruta (solo «trazar») y, al final, **los avisos y
    notas** (``warning`` y ``note``, con su código y sus valores en JSON) **menos los de** ``entity_store._OUTSIDE_NOTICES``: la magnitud y el orden con la cantera dependen de algo que la
    operación no consume (la revisión congelada anterior y la otra superficie de la cantera) y el informe se reproduce sin el proyecto. Un valor que no es finito es un error del programa
    (``ValueError``): nada se escribe. Solo depende del resultado: lo repite la reproducción."""
    engraved, axis, levels = outcome.engraved, outcome.axis, outcome.levels
    if engraved is None or axis is None or levels is None:
        raise ValueError("el informe de una pista pide su eje, su rasante y su grabado: son los del resultado de road_compute_steps")
    rows: list[Row] = []

    def scalar(key: str, value: float, unit: str, note: str | None = None) -> None:
        rows.append((key, _real(key, value), unit, note))

    stations = axis.stations
    steps = np.abs(np.diff(levels)) / np.diff(stations) * 100.0
    top = int(np.argmax(steps))
    scalar("footprint_cells", engraved.footprint_cells, "-")
    scalar("area_m2", engraved.area_m2, "m2")
    scalar("axis_m", axis.length_m, "m")
    scalar("axis_stations", len(stations), "-")
    scalar("axis_step_m", axis.step_m, "m")
    scalar("axis_deviation_m", axis.deviation_m, "m")
    scalar("curves", axis.curve_count, "-")
    for curve in axis.curves:
        scalar("curve", curve.radius_m, "m", _json({"vertex": curve.vertex, "design_radius_m": curve.design_radius_m, "deflection_rad": curve.deflection, "tangent_m": curve.tangent_m,
                                                    "length_m": curve.length_m, "station_m": curve.station_m, "x": curve.x, "y": curve.y}))
    scalar("z_start_m", levels[0], "m")
    scalar("z_end_m", levels[-1], "m")
    scalar("drop_m", levels[-1] - levels[0], "m")
    scalar("gradient_mean_pct", road_gradient.mean_gradient(stations, levels) * 100.0, "%")
    scalar("gradient_max_pct", steps[top], "%", _place(float(axis.points[top, 0]), float(axis.points[top, 1]), "gradient_max"))
    scalar("gradient_max_station_m", stations[top], "m")
    scalar("mean_exceeded", 1.0 if outcome.mean_exceeded else 0.0, "-")
    for key, value, unit in (("section_cut_m3", engraved.section_cut_m3, "m3"), ("section_fill_m3", engraved.section_fill_m3, "m3"), ("section_cut_cells", engraved.section_cut_cells, "-"),
                             ("section_fill_cells", engraved.section_fill_cells, "-"), ("cut_height_max_m", engraved.cut_height_max_m, "m"), ("fill_height_max_m", engraved.fill_height_max_m, "m"),
                             ("cut_denied_cells", int(np.count_nonzero(engraved.cut_denied)), "-"), ("fill_denied_cells", int(np.count_nonzero(engraved.fill_denied)), "-"),
                             ("too_high_cells", 0 if engraved.too_high is None else int(np.count_nonzero(engraved.too_high)), "-"),
                             ("off_level_area_m2", math.fsum(group.area_m2 for group in engraved.off_level), "m2"), ("off_level_max_m", max((group.max_m for group in engraved.off_level), default=0.0), "m")):
        scalar(key, value, unit)
    for group in engraved.off_level:
        scalar("off_level_group", group.max_m, "m", _json({"group": group.group, "cause": group.cause.value, "cells": group.cells, "area_m2": _real("off_level.area_m2", group.area_m2),
                                                          "x": _real("off_level.x", group.x), "y": _real("off_level.y", group.y)}))
    for key, value, unit in (("cut_angle_deg", engraved.cut_angle_deg, "deg"), ("fill_angle_deg", engraved.fill_angle_deg, "deg"), ("edge_mesh_factor", engraved.mesh_factor, "-"),
                             ("edge_reach_m", engraved.reach_m, "m"), ("edge_cut_m3", engraved.edge_cut_m3, "m3"), ("edge_fill_m3", engraved.edge_fill_m3, "m3"),
                             ("edge_cut_cells", engraved.edge_cut_cells, "-"), ("edge_fill_cells", engraved.edge_fill_cells, "-"),
                             ("edge_changed_cells", int(np.count_nonzero(engraved.changed)), "-"), ("edge_held_cells", engraved.held_cells, "-"), ("edge_steep_cells", engraved.steep_cells, "-"),
                             ("edge_outside_cells", engraved.outside_cells, "-")):
        scalar(key, value, unit)
    if engraved.wall_x is not None:
        scalar("edge_wall_max_m", engraved.wall_max_m, "m", _place(engraved.wall_x, engraved.wall_y, "edge_wall"))
    for wall in engraved.walls:
        scalar("edge_wall", wall.max_deg, "deg", _json({"cause": wall.cause.value, "cells": wall.cells, "area_m2": _real("edge_wall.area_m2", wall.area_m2), "x": _real("edge_wall.x", wall.x),
                                                        "y": _real("edge_wall.y", wall.y)}))
    created = engraved.created
    for key, value, unit in (("created_pairs", created.pairs, "-"), ("created_over_pairs", created.over, "-"), ("created_over_pct", created.over_pct, "%"), ("created_within_pct", created.within_pct, "%")):
        scalar(key, value, unit)
    scalar("created_step_max_m", created.maximum_m, "m", _place(created.x, created.y, "created_step"))
    for key, value, unit in (("created_threshold_m", created.threshold_m, "m"), ("created_min_share_pct", created.min_share_pct, "%"), ("created_min_thickness_m", created.min_thickness_m, "m")):
        scalar(key, value, unit)
    for stretch in created.stretches:
        scalar("created_stretch", stretch.maximum_m, "m", _json({"stretch": stretch.stretch, "pairs": stretch.pairs, "x": _real("created_stretch.x", stretch.x),
                                                                 "y": _real("created_stretch.y", stretch.y)}))
    for key, value, unit in (("avoid_cells", engraved.avoid_cells, "-"), ("avoid_m2", engraved.avoid_m2, "m2"), ("avoid_m3", engraved.avoid_m3, "m3"),
                             ("avoid_weighted_m3", engraved.avoid_weighted_m3, "m3")):
        scalar(key, value, unit)
    route = outcome.route
    if route is not None:
        for key, value, unit in (("route_mesh_m", route.mesh_m, "m"), ("route_margin_m", route.margin_m, "m"), ("route_corridor_nodes", route.corridor_nodes, "-"), ("route_nodes", route.nodes, "-"),
                                 ("route_expanded", route.expanded, "-"), ("route_seen", route.seen, "-"), ("route_budget", route.budget, "-"), ("route_turns", route.turns, "-")):
            scalar(key, value, unit)
    for notice in outcome.notices:
        if notice.code not in entity_store._OUTSIDE_NOTICES:
            rows.append((notice.severity, None, None, _notice_text(notice)))
    return rows


def road_operation_start(start: OperationStart, outcome: RoadOutcome, confirmed: RoadConfirmed | None) -> OperationStart:
    """Lo que anota la operación de la pista al crearla, además de lo que preparó (``start``: :func:`prepare_road_units`): **los otros diseños de la versión que difieren en su huella**
    (``outcome.other_designs``, RF-017-05 (b), CE-017-05) como entradas con el papel :data:`~.provenance.ROAD_OTHER_DESIGN_ROLE` —su hash es el que tenían al preparar la pista (``start.seen``: la
    preparación lo midió; si cambia hasta crearla, ``des.input_changed``)—, de modo que **si cambian, la pista queda obsoleta con su causa**; sin repetir uno que ya lo era; y **lo confirmado**
    (``confirmed``: quién, cuándo y el motivo de la media por encima de pm; el área y la diferencia de la calzada fuera de su rasante: RF-017-17, RF-017-22) en sus ajustes, bajo :data:`CONFIRMED`. Una
    ``OperationStart`` es inmutable: da otra y no cambia la que recibe; sin nada que añadir, la misma. **La pista no declara nada** (RF-017-01, D-15): ni ``protect`` ni una declaración."""
    found = start
    have = {(use.item, str(use.role)) for use in start.inputs}
    extra = tuple(Use(name, provenance.ROAD_OTHER_DESIGN_ROLE) for name in outcome.other_designs if (name, provenance.ROAD_OTHER_DESIGN_ROLE) not in have)
    if extra:
        found = replace(found, inputs=(*found.inputs, *extra))
    if confirmed is not None:
        found = replace(found, settings={**found.settings, CONFIRMED: confirmed.settings()})
    return found


def create_road_steps(project: StoreProject, writer: DesignWriter, prepared: PreparedRoad, outcome: RoadOutcome, *, mean: bool = False, carriageway: bool = False, reason: str | None = None,
                      decided_by: str | None = None, budget_s: float = road_net.STEP_BUDGET_S) -> Generator[Progress, None, Stored]:
    """**«Crear» una pista** por pasos (spec 017, T21; RF-017-01, RF-017-03, RF-017-23, RF-015-01, RF-015-02, RF-015-04, RF-015-15, RF-015-29; RNF-017-06, RNF-017-07 y RNF-017-10): prepara cada salida en su
    temporal —**la superficie entera** (la de partida con la ventana de trabajo sustituida por el resultado, ``RoadOutcome.compose``; comprimida) y las tres tablas: la huella de la sección
    (``des_epr_``, :func:`road_entity_rows`), el eje por estaciones (``des_rdx_``, :func:`road_axis_rows`) y el informe (``des_prp_``, :func:`road_report_rows`)—, cada una montada y escrita por pasos
    de ``budget_s`` como mucho, y las registra en **una** transacción (:meth:`~.store.DesignWriter.commit` de ``writer``, el de «Calcular»): **los parámetros de la entidad** —todas sus filas, con su
    origen y el decisor ``decided_by`` (por defecto quien tiene abierto el proyecto)—, la operación (:func:`road_operation_start`: sus entradas —la capa de origen, la partida, las máscaras, **lo que
    pisa** (``supported_on``: el eje de otra pista y la entidad de destino, con la tabla de su huella) y los otros diseños que difieren— y sus ajustes, con lo confirmado), los datos, las cifras con el
    ámbito de la entidad y las que el gancho de las dependencias mide (``des.supported_m3`` de lo que rellena sobre otras entidades: RF-015-15) y el mensaje. **No se crea sin la confirmación
    expresa** de la pendiente media por encima de pm (``mean``, con su ``reason``, que no la bloquea) ni de la calzada que no queda en su rasante (``carriageway``): :func:`check_road_confirmed`,
    **antes de tocar nada**. Una entidad que ya estaba en su versión (``prepared.existing``) no vuelve a escribir sus parámetros. Si algo falla, o lo que consume cambió desde que se calculó
    (``des.input_changed``), no queda nada y el error sigue; **no modifica la capa de origen ni la superficie de partida y no declara ninguna restricción** (RF-017-01, D-15: la pista no llama a
    ``des.declare_constraints``). Cerrar el generador antes de que termine borra los temporales. Devuelve lo guardado (:class:`~.store.Stored`).

    **Con un escritor reanudado** (``DesignWriter.resume``: un recálculo, :func:`run_road`, T22) la operación **ya empezó**: ``commit`` la completa en vez de abrir otra, sus ajustes ya llevan lo
    confirmado (``road_confirmed``, que arrastró el recálculo) y los otros diseños que difieren en la huella, que solo se conocen al calcular, se anotan con ``add_inputs`` en la transacción que la
    completa (``_LateSupports``: con el hash que tenían al preparar; si cambió, ``des.input_changed`` y no queda nada)."""
    if not isinstance(outcome, RoadOutcome):
        raise TypeError(f"se crea la pista de un RoadOutcome, no {outcome!r}")
    check_road_confirmed(outcome, mean=mean, carriageway=carriageway, reason=reason)
    job = prepared.job
    name = job.request.name
    yield Progress(_STORE_PHASE, 0, 1, f"Guardando la pista «{name}»…")

    def grid_units() -> Generator[None, None, Any]:
        whole = outcome.compose(job.start)
        yield
        return (yield from writer.grid_steps(provenance.ENTITY_SURFACE_GRID, Raster(job.grid, whole, writer.crs, writer.vertical)))

    yield from pipeline.forward(_store_steps(grid_units(), budget_s, "la superficie de la pista"))
    tables: tuple[tuple[str, Callable[[], list[Row]], str], ...] = (
        (provenance.ENTITY_TABLE, lambda: road_entity_rows(job, outcome, fid=prepared.fid, start_surface=prepared.start_surface, support_surface=prepared.support_surface), "la huella de la pista"),
        (provenance.ROAD_AXIS_TABLE, lambda: road_axis_rows(outcome), "el eje de la pista"), (provenance.ENTITY_REPORT_TABLE, lambda: road_report_rows(outcome), "el informe de la pista"))
    for family, make, what in tables:
        yield from pipeline.forward(_store_steps(writer.table_steps(family, make()), budget_s, what))
    handle = writer.handle  # un recálculo: la operación empezó antes de calcular (:func:`run_road`) y sus ajustes ya llevan lo confirmado
    start = None if handle is not None else road_operation_start(prepared.start, outcome, road_confirmation(project, outcome, mean=mean, carriageway=carriageway, reason=reason, decided_by=decided_by))
    late = _LateSupports() if handle is None else _LateSupports(tuple(Use(other, provenance.ROAD_OTHER_DESIGN_ROLE) for other in outcome.other_designs), prepared.start.seen)
    yield Progress(_STORE_PHASE, 1, 1, f"Registrando la pista «{name}»…")

    def parameters(conn: sqlite3.Connection) -> None:
        if prepared.existing:
            if ParameterStore(project).get(entity_key(prepared.code, RoadParam.NAME), version=prepared.version_uid, conn=conn) is None:
                raise ValueError(f"la entidad {prepared.code} no tiene sus parámetros en su versión: no está en ella (se prepara sin su código)")
            if handle is None:  # la que se calculó antes de crear: las cotas que vuelve a tomar de su origen se escriben en la transacción que abre la operación (T24b); un recálculo ya las escribió
                write_followed(project, prepared, decided_by=decided_by, conn=conn)
        else:
            entity_store.set_entity_params(project, prepared.rows, version=prepared.version_uid, decided_by=decided_by, conn=conn)
        if handle is not None:  # los otros diseños que difieren en la huella se anotan al completarla, con el hash que tenían al preparar (``des.input_changed`` si cambiaron)
            late.register(conn, handle)

    return writer.commit(start, figures=outcome.figures, message=outcome.message, before_begin=parameters)


def create_road(project: StoreProject, writer: DesignWriter, prepared: PreparedRoad, outcome: RoadOutcome, *, mean: bool = False, carriageway: bool = False, reason: str | None = None,
                decided_by: str | None = None) -> Stored:
    """:func:`create_road_steps` de una vez (sin ceder el hilo): lo guardado (:class:`~.store.Stored`), con los mismos rechazos y la misma transacción."""
    work = create_road_steps(project, writer, prepared, outcome, mean=mean, carriageway=carriageway, reason=reason, decided_by=decided_by)
    while True:
        try:
            next(work)
        except StopIteration as stop:
            result: Stored = stop.value
            return result


# --- Recalcular (spec 017, T22; RF-017-01, RF-017-03, RF-017-17, RF-017-22, RF-015-02, RF-015-16; RF-008-26; plan 017 §5.3.2 y §5.7 P-5) -----------------------------------------------------------------


def other_reader(project: StoreProject, version: Version) -> OtherReader:
    """Lo que lee **la superficie de otro diseño** de la versión en la ventana de trabajo de la pista (:data:`OtherReader`; RF-017-05 (b)): ``read_surface_window`` del proyecto, en la rejilla del
    proyecto y solo las celdas de la ventana. Lo comparten «Calcular» (``steps.road_run``) y el recálculo (:func:`run_road`); la reproducción lee lo congelado."""
    frame = project_frame(project)

    def read_other(name: str, window: tuple[slice, slice]) -> np.ndarray:
        return read_surface_window(project, name, window, version_uid=version.uid, expect=frame, role="superficie de otro diseño de la versión").values

    return read_other


def _check_recorded(handle: OperationHandle, prepared: PreparedRoad) -> None:
    """Los parámetros que anotó la operación al empezar son los que leyó el cálculo al prepararse (RF-013-17, D-14; como ``Calculation.create``): los de la entidad, los del proyecto y **los del perfil**
    (``des.roadprofile.{p}.*``): si uno cambió entre las dos cosas, el resultado ya no le corresponde (``des.input_changed``, con el parámetro)."""
    read: dict[str, object] = {entity_key(prepared.code, RoadParam(name)): value for name, value in prepared.values.items()}
    read.update(prepared.common)
    profile = prepared.profile
    read.update({road_profile_key(profile.code, param): getattr(profile, param.value) for param in RoadProfileParam if param is not RoadProfileParam.CLASS})
    for param in handle.params:
        if param.key in read and param.value != read[param.key]:
            raise DesignError("des.input_changed", obj=f"Parámetro «{param.key}»", field="parámetros", value=param.key)


def _confirmed_covers(outcome: RoadOutcome, confirmed: RoadConfirmed | None) -> tuple[bool, bool, str | None]:
    """Lo que de la confirmación de la operación que se sustituye **cubre al resultado nuevo** (un recálculo no confirma por la persona): ``(media, calzada, motivo)`` para :func:`check_road_confirmed`. La
    media cubre si la nueva no pasa de la confirmada (:meth:`RoadConfirmed.covers_mean`) y la calzada, si ni su área ni su diferencia pasan de lo confirmado (:meth:`RoadConfirmed.covers_carriageway`);
    sin nada que confirmar en el resultado nuevo, ni lo uno ni lo otro hace falta (confirmar de más no estorba)."""
    if confirmed is None:
        return False, False, None
    mean = bool(outcome.mean_exceeded) and confirmed.covers_mean(float(_mean_notice(outcome).values["mean"]))
    groups = outcome.off_level
    carriageway = bool(groups) and confirmed.covers_carriageway(math.fsum(group.area_m2 for group in groups), max(group.max_m for group in groups))
    return mean, carriageway, confirmed.reason


def run_road(project: StoreProject, request: RoadRequest, *, version: str | None, code: str, masks: access.MaskSet | None = None, supersedes: str | None = None,
             confirmed: RoadConfirmed | None = None, released: Sequence[provenance.ReleasedSupport] = (), budget_s: float = road_net.STEP_BUDGET_S) -> tuple[OperationHandle, Iterator[Progress]]:
    """Calcula y registra ``request`` —la pista de la entidad ``code``, que ya está en su versión— de **una vez**, sin pedir confirmación a la persona (spec 017, T22; RF-017-01, RF-015-02, RF-015-16; el
    recálculo de lo obsoleto, :func:`~.store.recompute_run`; el «Crear» tras «Calcular» es :meth:`~.steps.Calculation.create`): prepara (:func:`prepare_road`: la entidad se reconoce por su ``code``),
    empieza la operación ``des.road`` **antes de calcular** —sustituye a ``supersedes``, quedándose con los nombres de sus datos y arrastrando lo que se le apoyaba— con lo que lee hoy (la capa de
    origen, la partida, las máscaras de la versión, los parámetros de la entidad —los del **perfil** con ellos—, el eje y la huella de la pista o la entidad en que se apoya) y devuelve su
    ``OperationHandle`` «en curso» y sus pasos, que avanza quien la llama: calculan (:func:`road_compute_steps`, con los otros diseños de la versión), escriben la superficie entera y las tres tablas en
    su temporal y completan la operación en una transacción (:func:`create_road_steps` con el escritor reanudado: no escribe los parámetros, que ya están, y anota con ``add_inputs`` los otros diseños que
    difieren en la huella); el último paso lleva lo guardado (:class:`~.store.Stored`). Cerrarlos antes, o un fallo, no dejan nada y la operación queda cancelada o fallida.

    **Un recálculo no confirma por la persona**: ``confirmed`` es lo que confirmó al crear la operación que sustituye (:func:`confirmed_of`: la media por encima de pm y la calzada fuera de su rasante,
    con quién, cuándo y el motivo) y **se arrastra tal cual** a la operación nueva —la misma decisión, no otra— mientras lo nuevo no pase de ello; si pasa, ``des.road_mean_unconfirmed`` o
    ``des.road_carriageway_unconfirmed`` al avanzar, antes de escribir nada, y la que sustituye sigue vigente. No calcula la magnitud contra la revisión congelada ni el orden con la otra superficie de
    la cantera (solo los avisos del resumen, que no van al informe: ``entity_store._OUTSIDE_NOTICES``).

    **Un recálculo sigue a lo que la pista pisa** (T24b; RF-017-03, D-13): las cotas de inicio y de fin cuyo origen anotado es el del algoritmo se vuelven a tomar de su origen
    (:func:`prepare_road_units`; si cambió la plataforma de destino o el eje de la otra pista, la pista acaba o sale a la cota nueva) y se **escriben en su fila antes de abrir la operación**
    (:func:`write_followed`, con su origen y su motivo y con su historial): la operación anota la revisión nueva y lo congelado se reproduce con ella. Las que dio la persona no cambian. El último paso
    lo dice en su mensaje (``Progress.message``: «su cota de fin pasa de X a Y m…»); sin cambios, no se escribe ningún parámetro.

    **Dar por buena la pista sin una entidad en que se apoyaba** (``released``, T24; RF-015-17, A7, P-6; :func:`~.entity_store.release_support`): la operación nueva **no lleva** las entradas de esa
    entidad (ni su superficie ni la tabla de su huella), anota el motivo y el decisor en sus ajustes (``supports_released``, acumulados con los de la que sustituye) y el gancho de las dependencias
    no vuelve a registrarla; su superficie, su huella y su eje no cambian. Se suma a lo que ya daba por bueno la operación que sustituye.

    Al llamar, sin empezar nada: los rechazos de :func:`prepare_road`. Al avanzar, antes de escribir nada, ``des.input_changed`` si un parámetro cambió entre prepararla y empezar la operación."""
    prepared = prepare_road(project, request, version=version, masks=masks, code=code, supersedes=supersedes, released=released)
    start = prepared.start
    if confirmed is not None:  # se arrastra a la operación nueva (la misma decisión, no una nueva)
        start = replace(start, settings={**start.settings, CONFIRMED: confirmed.settings()})
    write_followed(project, prepared)  # las cotas que vuelve a tomar de su origen (T24b), antes de abrir la operación: la anota con la revisión nueva
    handle = start.with_released(released).begin(project)
    return handle, _road_run(project, handle, prepared, budget_s, confirmed)


def _road_run(project: StoreProject, handle: OperationHandle, prepared: PreparedRoad, budget_s: float, confirmed: RoadConfirmed | None) -> Generator[Progress, None, None]:
    with DesignWriter.resume(project, handle) as writer:
        _check_recorded(handle, prepared)
        others = prepared.others
        outcome: RoadOutcome = yield from road_compute_steps(
            prepared.job, prepared.common, surface=prepared.start_surface, others=others, read_other=other_reader(project, prepared.version) if others else None,
            operation=prepared.job.request.name, budget_s=budget_s)
        mean, carriageway, reason = _confirmed_covers(outcome, confirmed)
        stored: Stored = yield from create_road_steps(project, writer, prepared, outcome, mean=mean, carriageway=carriageway, reason=reason, budget_s=budget_s)
        said = "; ".join(item.notice(outcome.name).text("es") for item in prepared.followed)  # las cotas que volvió a tomar de su origen (T24b): el resumen de un recálculo es este mensaje
        yield Progress(_STORE_PHASE, 1, 1, f"{outcome.message}; {said}" if said else outcome.message, result=stored)


def recompute_road(request: RecomputeRequest, *, budget_s: float = road_net.STEP_BUDGET_S, released: Sequence[provenance.ReleasedSupport] = ()
                   ) -> tuple[OperationHandle, Iterator[Progress]]:
    """Repite la operación ``des.road`` de ``request`` (:func:`~.store.recompute_run`; «Recalcular lo obsoleto», RF-008-26; spec 017, T22; RF-017-01, RF-015-02, RF-015-16): la pista de sus ajustes (el
    nombre, el código y el campo de los nombres de la capa) con los **parámetros vigentes de su entidad en su versión** (:func:`~.entity_store.entity_parameters`: el modo, la capa y su geometría, el
    perfil, la partida, el apoyo, el origen y el destino, las cotas de inicio y de fin y los parámetros de la ruta; los de la versión y, si no, los del proyecto) y no los que leyó la operación que
    sustituye: una entidad se define por sus parámetros (RF-015-01). La capa de origen (su geometría), la partida, los valores del perfil, el espesor mínimo de la 012, **los otros diseños de la versión
    que difieren en su huella** y lo que la pista pisa son entradas o parámetros de la operación: cambiar uno la deja obsoleta **entera**, con su causa, y recalcular la repite con lo nuevo. Devuelve lo
    de :func:`run_road`, con lo que la persona confirmó al crearla. **Dar por bueno un apoyo sin su entidad** (``released``, RF-015-17; T24): lo que la operación nueva da por bueno sin ese apoyo
    (:func:`~.entity_store.release_support`, sin pasar por el plan de «Recalcular lo obsoleto», que lo rehúsa) pasa a :func:`run_road`. ``TypeError`` si la petición no es una ``RecomputeRequest``;
    ``ValueError`` si no es de ``des.road`` o sus ajustes no son los de una pista."""
    if not isinstance(request, RecomputeRequest):
        raise TypeError(f"se recalcula una RecomputeRequest, no {request!r}")
    if request.op_type != provenance.ROAD:
        raise ValueError(f"recompute_road repite {provenance.ROAD}, no «{request.op_type}»")
    project: StoreProject = request.project  # type: ignore[assignment]
    code = provenance.supported_code(request.settings)
    found = require_version(project, request.version, provenance.ROAD)
    asked = provenance.road_request(request.settings, entity_store.entity_parameters(project, code, version=found))
    return run_road(project, asked, version=found.uid, code=code, supersedes=request.operation_uid, confirmed=confirmed_of(request.settings), released=released, budget_s=budget_s)


# --- Reproducir: lo que se lee de lo congelado, sin proyecto (spec 017, T22; RF-017-01 a RF-017-03, RF-015-02, RF-009-11) --------------------------------------------------------------------------------

_FROZEN_CLASS = "(no se lee al reproducir)"
"""La clase normativa de un perfil rehecho de lo congelado: no la lee la operación (no cambia ninguna cifra: ``provenance._ROAD_PROFILE_READ``) y no sale en ninguna salida de la pista."""


def frozen_profile(values: Mapping[str, object], code: str) -> road_profiles.RoadProfile:
    """El perfil de pista de código ``code`` rehecho de los **parámetros congelados** de la operación (``values``: clave completa → valor, ``des.roadprofile.{p}.*``; los 14 que lee, sin la clase normativa),
    como el de la preparación (:func:`_profile`) lo hace del proyecto: los mismos valores y las mismas comprobaciones (``des.road_profile_value_missing``, ``_value_range``… nombrando el perfil, el campo
    y el valor) y **sin el proyecto**. Su nombre es su código y su clase, un texto fijo (:data:`_FROZEN_CLASS`)."""
    found = dict(values)
    found[road_profile_key(code, RoadProfileParam.CLASS)] = _FROZEN_CLASS
    return road_profiles.road_profiles_from(found, (code,))[code]


def frozen_geometry(asked: RoadRequest, code: str, grid: Grid, layer: FeatureLayer, *, zone_layer: FeatureLayer | None = None, axis: np.ndarray | None = None,
                    footprint: np.ndarray | None = None, lines: Lines3D | None = None) -> tuple[RoadGeometry, int]:
    """La geometría de origen de la pista ``asked`` (de código ``code``) y el ``fid`` que escribe ``des_epr_``, leídos de lo **congelado** y sin proyecto (spec 017, T22; RF-017-02, RF-017-03, RF-015-02): lo
    mismo que resolvió la preparación (:func:`_resolve_points`, :func:`_read_line`), con la capa de origen ``layer`` ya leída del dato congelado, la capa de la zona del destino por cota (``zone_layer``),
    **el eje por estaciones de la pista en cuyo eje está el origen** (``axis``: ``(n, 5)``, abscisa, x, y, cota del terreno y cota de la rasante, el ``des_rdx_`` congelado; :func:`axis_point_at`) y **la
    huella de la entidad de destino** (``footprint``: sus celdas, ``fila · columnas + columna``, la ``des_epr_`` congelada). «Trazar»: el origen y el destino, un punto de la capa por su nombre o su ``fid``, el
    punto del eje de otra pista o el que cae en la huella de una entidad (sin contar el origen) o el destino por cota con los anillos de su zona; el ``fid`` es el del primer punto que es de la capa (el
    origen o, si este es el eje de otra pista, el destino; 0 si ninguno). «Sobre un eje»: la línea de la capa **sin corregirla** y el ``fid`` de su geometría. «Eje 3D» (T23): la línea **con su Z** de la
    capa de líneas congelada (``lines``: :func:`read_lines_3d` de la copia de su entrada) y el ``fid`` de su geometría. ``ValueError`` si lo que hace falta no se da o no es único (la preparación lo
    rechazó al crearla: un error del programa)."""
    if asked.mode is RoadMode.AXIS_3D:
        if lines is None:
            raise ValueError(f"la pista «{asked.name}» «eje 3D» necesita la capa de líneas con Z, que no está entre las entradas congeladas")
        line, found_fid = line_3d(lines, asked, code)
        return RoadGeometry(line=line), found_fid
    if asked.mode is RoadMode.ON_AXIS:
        if asked.feature is None:
            raise ValueError(f"la pista «{asked.name}» «sobre un eje» no dice su geometría (feature)")
        index = _feature_index(layer, asked.feature, asked, code, RoadParam.FEATURE)
        return RoadGeometry(line=_read_line(layer, index, asked.feature, asked, code)), int(layer.fids[index])
    if asked.origin is None:
        raise ValueError(f"la pista «{asked.name}» «trazar» no dice su origen")
    fids: list[int] = []
    skip = -1
    origin_ref = parse_reference(asked.origin)
    if isinstance(origin_ref, AxisReference):
        if axis is None:
            raise ValueError(f"el origen de la pista «{asked.name}» ({asked.origin}) está en el eje de otra pista y su eje por estaciones no está entre las entradas congeladas")
        at = axis_point_at(axis, origin_ref.station_m)
        if at is None:
            raise ValueError(f"la abscisa de {asked.origin} queda fuera del eje congelado de {origin_ref.code}")
        origin = (at[0], at[1])
    else:
        found = _feature_index(layer, str(asked.origin).strip(), asked, code, RoadParam.ORIGIN)
        origin, skip = _point_of(layer, found), found
        fids.append(int(layer.fids[found]))
    destination: tuple[float, float] | LevelDestination
    if asked.destination is None:
        if zone_layer is None or asked.dest_zone is None:
            raise ValueError(f"el destino por cota de la pista «{asked.name}» necesita la capa de su zona, que no está entre las entradas congeladas")
        destination = _zone_destination(zone_layer, asked, code)
    else:
        destination_ref = parse_reference(asked.destination)
        if isinstance(destination_ref, EntityReference):
            if footprint is None:
                raise ValueError(f"el destino de la pista «{asked.name}» ({asked.destination}) está en una entidad y su huella no está entre las entradas congeladas")
            inside = [index for index in range(len(layer)) if index != skip and _in_cells(grid, _point_of(layer, index), footprint)]
            if len(inside) != 1:
                raise ValueError(f"el destino de la pista «{asked.name}» ({asked.destination}) es un punto de la capa en la huella de la entidad: hay {len(inside)}, no uno")
            destination = _point_of(layer, inside[0])
            fids.append(int(layer.fids[inside[0]]))
        else:
            found = _feature_index(layer, str(asked.destination).strip(), asked, code, RoadParam.DESTINATION)
            destination = _point_of(layer, found)
            fids.append(int(layer.fids[found]))
    return RoadGeometry(origin=origin, destination=destination), (fids[0] if fids else 0)


def _in_cells(grid: Grid, point: tuple[float, float], cells: np.ndarray) -> bool:
    """Si el punto absoluto cae en alguna de las celdas ``cells`` (``fila · columnas + columna``) de la rejilla."""
    cell = _cell_of(grid, *point)
    return cell is not None and bool(np.isin(cell[0] * grid.ncols + cell[1], cells))


# --- Proponer el trazado (spec 017, T27; HU-017-1 y HU-017-4; RF-017-28, RF-017-27, RF-015-02, RF-015-29; plan 017 §5.2.3 «des.road_propose», §5.4 A1 a A5, §5.7 P-8 y P-14; D-19) --------------------------------

PROPOSE_CODE = "RDW-000"
"""El código de pista con el que una propuesta nombra el campo de sus rechazos (``des.road.rdw_000.origin``): **no es el de una entidad** (las entidades empiezan en ``RDW-001`` y una propuesta no
lo es: no está en el registro, no encadena y no tiene parámetros de entidad), sino el de la ficha de campos de la pista de la que la propuesta toma sus rechazos (P-14: lo mismo hasta la ruta y la rasante)."""


@dataclass(frozen=True, slots=True, eq=False)
class PreparedProposal:
    """Lo que se lee y se comprueba antes de calcular «Proponer el trazado» (:func:`prepare_propose_units`): el ``job`` (el ``RoadJob`` «trazar»: todo lo leído y nada del proyecto), lo que anotará la
    operación (``start``: su tipo ``des.road_propose``, sus ajustes con lo que resolvió la preparación —:data:`~.provenance.RESOLVED`—, sus entradas y los parámetros del perfil), la ``version`` (la
    editable), el nombre del dato de la superficie de partida (``start_surface``), la capa de origen (``layer``), el ``profile`` (el perfil de pista de la versión, ya comprobado), sus ``values``
    resueltos y comprobados (por último segmento de su clave) y el ``fid`` del primer punto que es de la capa. **No lleva** código de entidad, filas de parámetros de entidad, apoyos ni avisos de la
    partida: una propuesta no es una entidad (P-8) y no graba ninguna superficie."""

    job: RoadJob
    start: OperationStart
    version: Version
    start_surface: str
    layer: str
    profile: road_profiles.RoadProfile
    values: Mapping[str, Any]
    fid: int = 0

    @property
    def op_type(self) -> str:
        """El tipo de la operación (``des.road_propose``)."""
        return self.start.op_type

    @property
    def version_uid(self) -> str:
        """El uid de la versión de la propuesta."""
        return self.version.uid


def prepare_propose_units(project: StoreProject, request: RoadRequest, version: Version, masks: access.MaskSet, *, supersedes: str | None = None) -> Generator[None, None, PreparedProposal]:
    """Las unidades (cada ``yield``, una; para componerlas con ``pace_units``) que preparan «Proponer el trazado» ``request`` en la versión editable ``version`` con las máscaras al día ``masks``
    (RF-017-28, P-14): **lo mismo que la pista «trazar» hasta la ruta y la rasante** (:func:`prepare_road_units`) y nada de lo que es de una entidad —ni el código ni el nombre únicos en el
    registro, ni la cadena (la propuesta no parte de la cadena de nadie), ni los apoyos que declara una pista, ni los avisos de su partida—: la capa de los puntos (``gis_fea_``; el origen, un punto
    por su ``fid`` o su nombre, o un punto del eje de otra pista, ``RDW-001@s``, y el destino, otro punto, uno que cae en la huella de una entidad o una cota con su zona y su tolerancia), el
    perfil, la superficie de partida (por defecto, :func:`default_start`) comparada con la rejilla del proyecto **antes de leer una celda**, las cotas de inicio y de fin (D-13), los parámetros de
    la ruta (:func:`road_values`: ninguno tiene valor por defecto salvo el presupuesto), el destino por cota, las máscaras (RF-017-06: lo intocable y el peso de «preferible no afectar») y **la
    búsqueda de intocables** de los sectores que toca el pasillo (RF-015-07). **Nada se escribe** (RF-015-03). Los rechazos nombran la capa, la propuesta, el campo (con :data:`PROPOSE_CODE`) y el
    valor, y salen al avanzar y en este orden: la versión, la capa, el perfil, la superficie, los puntos, las cotas, los parámetros, la malla de la ruta, el destino por cota y un sector pendiente.
    ``supersedes``: la operación hecha a la que sustituye (un recálculo). ``ValueError`` (un error del programa) si ``request`` no es de «trazar» o las máscaras no son de la versión."""
    if masks.version_uid != version.uid:
        raise ValueError(f"las máscaras son de otra versión, no de {version.code}")
    if request.mode is not RoadMode.TRACE:
        raise ValueError(f"«Proponer el trazado» usa la ruta (modo «trazar»), no «{request.mode.value}» (P-14)")
    code, name = PROPOSE_CODE, request.name
    registry = entities.registry(project, version.uid)
    start_ref = request.start.strip()
    if not start_ref:
        proposed = default_start(project, version)
        if proposed is None:
            raise _reject("des.entity_param_missing", request, code, RoadParam.START, None)
        start_ref = proposed.ref
    start_name = _start_dataset(registry, version, name, code, start_ref, RoadParam.START)
    yield
    layer = _layer(project, request.layer)
    _kind(layer, "point", request, code)
    profile = _profile(project, version, request, code)
    yield
    frame = project_frame(project)
    grid = frame.grid
    surface = yield from read_surface_steps(project, start_name, version_uid=version.uid, expect=frame, role=_START_ROLE)
    values_start = surface.values
    if not grid.same_geometry(masks.grid):
        raise ValueError("la rejilla de las máscaras no es la del proyecto")
    resolved = yield from _resolve_points(project, version, registry, request, code, name, layer, grid, values_start, start_name, frame)
    start_level, end_level = resolved.origin_level, resolved.destination_level
    if any(getattr(request, attr) is not None for attr in ("dest_level_m", "dest_tol_m", "dest_zone")) and request.destination is None:
        end_level = None
    chosen_levels: dict[RoadParam, float | None] = {RoadParam.START_LEVEL: None, RoadParam.END_LEVEL: None}
    for param, asked_level, derived in ((RoadParam.START_LEVEL, request.start_level_m, start_level), (RoadParam.END_LEVEL, request.end_level_m, end_level)):
        level = resolve_level(param, asked_level, None, derived)
        if level.origin is None:  # la da la persona: se comprueba contra el terreno (RF-017-04)
            _check_level(request, code, param, level.value_m, values_start)
        chosen_levels[param] = level.value_m
    resolved_start, resolved_end = chosen_levels[RoadParam.START_LEVEL], chosen_levels[RoadParam.END_LEVEL]
    values = road_values(request, code, start_ref=start_ref, start_level_m=resolved_start, end_level_m=resolved_end)
    yield
    try:
        road_net.mesh_factor(grid, values[RoadParam.MESH.value])
    except ValueError:
        raise _reject("des.road_mesh_not_multiple", request, code, RoadParam.MESH, values[RoadParam.MESH.value], step=grid.dx) from None
    route = RouteParams.from_values(values)
    destination: LevelDestination | None = None
    zone_layer: str | None = None
    if request.destination is None:
        destination, zone_layer = _level_destination(project, request, code)
    cut, fill = admitted_pair(masks, (slice(0, grid.nrows), slice(0, grid.ncols)))
    untouchable = untouchable_cells(masks)
    weight = avoid_weight(masks)
    geometry = RoadGeometry(origin=resolved.origin, destination=destination if destination is not None else resolved.destination)
    asked = replace(request, start=start_ref)
    job = RoadJob(asked, code, profile, grid, values_start, cut, fill, untouchable, geometry, route, resolved_start, resolved_end, weight)
    yield
    sectors = design_sectors(project, version.uid)
    mesh: road_net.RouteMesh | None = None
    if destination is not None or any(item.pending for item in sectors):
        mesh = road_net.route_mesh(grid, values_start, route.mesh_m, untouchable, avoid_weight=weight)
    if destination is not None:
        assert mesh is not None
        nodes = Grid(west=grid.west, north=grid.north, dx=mesh.mesh_m, dy=mesh.mesh_m, ncols=mesh.shape[1], nrows=mesh.shape[0])
        if not bool((polygons_cells(destination.zone, nodes) & mesh.walkable).any()):
            raise _reject("des.road_dest_zone_empty", request, code, RoadParam.DEST_ZONE, str(request.dest_zone))
        road_route.route_target(job, mesh)  # ``des.road_dest_level_out_of_zone``: la cota que ningún nodo de la zona alcanza
    yield
    if any(item.pending for item in sectors):
        zone = yield from _pending_zone(job, mesh)
        refs, labels = sector_layout(project, masks)
        touched = pipeline.touched_in(refs, labels, zone)
        refuse_pending(item for item in sectors if item.code in touched)  # RF-015-07
    yield
    inputs = provenance.road_inputs(request.layer, start_name, masks.uses(), ())
    read: list[Use] = []
    if resolved.axis is not None:  # lo que lee del eje de otra pista (RF-017-03): entrada, para que si cambia la propuesta quede obsoleta; sin apoyo declarado: una propuesta no es una entidad
        read.append(Use(resolved.axis, provenance.ROAD_AXIS_ROLE))
    for item in resolved.surfaces.values():  # la superficie y la huella de la entidad del destino: lo que lee, no lo que pisa
        if item.surface != start_name:
            read.extend((Use(item.surface, provenance.ROAD_OTHER_DESIGN_ROLE), Use(item.table, provenance.ROAD_OTHER_DESIGN_ROLE)))
    if zone_layer is not None:
        read.append(Use(zone_layer, provenance.ENTITY_LAYER_ROLE))
    settled = {"origin": resolved.origin, "destination": None if destination is not None else resolved.destination, "start_level_m": resolved_start, "end_level_m": resolved_end}
    begun = _start(project, provenance.ROAD_PROPOSE, name, version, masks, provenance.propose_settings(asked, settled), (*inputs, *(use for use in read if use not in inputs)),
                   provenance.propose_params(profile.code), supersedes)
    yield
    return PreparedProposal(job, begun, version, start_name, request.layer, profile, MappingProxyType(values), resolved.fid)


def prepare_propose(project: StoreProject, request: RoadRequest, *, version: str | None, masks: access.MaskSet | None = None, supersedes: str | None = None) -> PreparedProposal:
    """La preparación entera de :func:`prepare_propose_units` de una vez (sin ceder el hilo): la :class:`PreparedProposal`, con los mismos rechazos y sin escribir nada. ``version``: la versión activa
    (su uid o su código; ``VersionError`` ``core.version_required`` si no hay y ``core.version_not_editable`` si no se edita, RF-009-21); ``masks``: las de esa versión (al día; sin ellas se
    cargan, compilándolas antes si faltan)."""
    found = require_version(project, version, provenance.ROAD_PROPOSE)
    work = prepare_propose_units(project, request, found, _loaded_masks(project, found, masks), supersedes=supersedes)
    while True:
        try:
            next(work)
        except StopIteration as stop:
            result: PreparedProposal = stop.value
            return result


def propose_compute_steps(job: RoadJob, *, surface: str | None = None, budget_s: float = road_net.STEP_BUDGET_S) -> Generator[Progress, None, ProposalOutcome]:
    """Los pasos que calculan «Proponer el trazado» de ``job`` (RF-017-28, RF-015-03, RF-015-29; plan 017 §5.4 A1 a A5, P-14), **sin proyecto y sin escribir nada** (``yield from``; cerrar el
    generador, Esc, no deja nada ni cambia ninguna entrada): devuelve (valor de ``StopIteration``) el :class:`~.road_model.ProposalOutcome`, por pasos de ``budget_s`` como mucho (RNF-017-06).
    **La ruta y la rasante de «trazar» y nada de la sección** (A6 a A9: la propuesta no toca ninguna superficie, D-19): la red 2D desde el destino y desde el origen, el pasillo, la ruta 3D
    con su presupuesto de estados (sin ruta, el rechazo de RF-017-12), el eje con curvas (A4, con el rechazo de RF-017-14) y la rasante acotada (A5, con el rechazo de RF-017-16); los avisos del
    eje y de la pendiente media (**avisa y no pide confirmación**: no graba nada). ``surface`` es el nombre del dato de la superficie de partida (para el rechazo por falta de dato). Las dos cifras
    del plan: la longitud del eje y la pendiente máxima. ``ValueError`` si el trabajo no es de «trazar»."""
    if not isinstance(job, RoadJob):
        raise TypeError(f"el trabajo de una propuesta es RoadJob, no {job!r}")
    if job.mode is not RoadMode.TRACE:
        raise ValueError(f"«Proponer el trazado» usa la ruta (modo «trazar»), no «{job.mode.value}» (P-14)")
    name = job.request.name
    shown = job.request.start if surface is None else surface
    yield _stage(0, f"Calculando el trazado «{name}»…")
    route, corridor = yield from _route_steps(job, budget_s)
    arrival = road_route.arrival_of(job, route)
    yield _stage(3, f"Formando el eje y la rasante de «{name}»…")
    axis = _form_axis(job, route, arrival)
    terrain = _terrain_on(job, axis, shown)
    levels = _levels(job, axis, terrain)
    found, exceeded = _axis_notices(job, axis, levels)
    yield _stage(_STAGES - 1, f"Cifras del trazado «{name}»…")
    stations = axis.stations
    steps = np.abs(np.diff(levels)) / np.diff(stations)
    figures = provenance.propose_figures(name, {"des.road_length_m": axis.length_m, "des.road_gradient_max_pct": float(steps[int(np.argmax(steps))]) * 100.0})
    assert job.route is not None and route.cost is not None
    summary = RouteReport(route.mesh.mesh_m, job.route.margin_m, corridor.nodes, corridor.lower_bound_m, len(route.nodes), route.expanded, route.seen, route.budget, float(route.cost), route.turns,
                          arrival)
    outcome = ProposalOutcome(name, axis, terrain, levels, figures, found, summary, exceeded)
    yield _stage(_STAGES, f"Trazado «{name}» calculado")
    return outcome


def propose_layer_rows(outcome: ProposalOutcome) -> tuple[road_layer.RouteLayerRow, ...]:
    """La fila de la capa propuesta ``des_rpl_`` (RF-017-28) del resultado ``outcome``: **una**, la línea con su nombre y, por vértice, la x y la y absolutas de cada estación del eje (float64,
    exactas) y **la rasante en la Z**. Solo depende de lo que se calcula, no del proyecto: lo repite la reproducción desde lo congelado."""
    if not isinstance(outcome, ProposalOutcome):
        raise TypeError(f"la capa propuesta sale de un ProposalOutcome, no {outcome!r}")
    return (road_layer.RouteLayerRow(outcome.name, np.column_stack([outcome.axis.points, outcome.levels])),)


def create_propose_steps(project: StoreProject, writer: DesignWriter, prepared: PreparedProposal, outcome: ProposalOutcome, *, budget_s: float = road_net.STEP_BUDGET_S
                         ) -> Generator[Progress, None, Stored]:
    """**«Crear» una propuesta del trazado** por pasos (spec 017, T27; RF-017-28, RF-015-29, P-8, D-19): prepara la capa propuesta en su temporal (``des_rpl_``, :func:`propose_layer_rows`) y la
    registra en **una** transacción (:meth:`~.store.DesignWriter.commit` de ``writer``, el de «Calcular»): la operación (``des.road_propose``: sus entradas —la capa de los puntos, la partida, las
    máscaras—, sus ajustes y los parámetros del perfil), **la capa, que es del usuario desde que se crea** (``qgis_editable``: se edita en QGIS y no se bloquea), las dos cifras con el ámbito del nombre
    de la operación y el mensaje. **No escribe ninguna superficie ni ningún parámetro, no llama a ``des.entity_layer`` ni a ``des.declare_constraints``: no es una entidad.** Si algo falla, o lo que
    consume cambió desde que se calculó (``des.input_changed``), no queda nada y el error sigue. Cerrar el generador antes de que termine borra los temporales. Con un escritor reanudado
    (``DesignWriter.resume``: un recálculo, :func:`run_propose`) la operación ya empezó y ``commit`` la completa. Devuelve lo guardado (:class:`~.store.Stored`)."""
    if not isinstance(outcome, ProposalOutcome):
        raise TypeError(f"se crea la propuesta de un ProposalOutcome, no {outcome!r}")
    name = outcome.name
    yield Progress(_STORE_PHASE, 0, 1, f"Guardando el trazado «{name}»…")
    yield from pipeline.forward(_store_steps(writer.route_layer_steps(propose_layer_rows(outcome)), budget_s, "la capa propuesta del trazado"))
    yield Progress(_STORE_PHASE, 1, 1, f"Registrando el trazado «{name}»…")
    return writer.commit(None if writer.handle is not None else prepared.start, figures=outcome.figures, message=outcome.message)


def create_propose(project: StoreProject, writer: DesignWriter, prepared: PreparedProposal, outcome: ProposalOutcome) -> Stored:
    """:func:`create_propose_steps` de una vez (sin ceder el hilo): lo guardado (:class:`~.store.Stored`), con los mismos rechazos y la misma transacción."""
    work = create_propose_steps(project, writer, prepared, outcome)
    while True:
        try:
            next(work)
        except StopIteration as stop:
            result: Stored = stop.value
            return result


def _refuse_edited_proposal(project: StoreProject, prepared: PreparedProposal, supersedes: str | None) -> None:
    """**Repetir una propuesta no sobrescribe lo que la persona dibujó** (principio 7, P-8): si la capa que va a sustituir se editó fuera de Geoblender (su dato ya no lo escribió la operación que se
    repite, sino la edición externa), ``des.route_layer_edited`` y no se empieza nada. Sin operación que sustituir, o con la capa tal como la escribió la operación, no hace nada. Solo lee."""
    if supersedes is None:
        return
    dataset = provenance.dataset_name(provenance.ROUTE_LAYER_TABLE, prepared.job.request.name)
    with project.read() as conn:
        record = dataset_registry.get(conn, dataset, version_uid=prepared.version.uid)
    if record is not None and record.live and record.operation_uid != supersedes:
        raise DesignError("des.route_layer_edited", obj=f"Propuesta «{prepared.job.request.name}»", field="capa propuesta", value=record.locator, table=record.locator,
                          operation=prepared.job.request.name)


def _check_recorded_proposal(handle: OperationHandle, prepared: PreparedProposal) -> None:
    """Los parámetros que anotó la operación al empezar son los que leyó el cálculo al prepararse (como :func:`_check_recorded`): los del perfil; si uno cambió entre las dos cosas, el resultado
    ya no le corresponde (``des.input_changed``, con el parámetro)."""
    profile = prepared.profile
    read = {road_profile_key(profile.code, param): getattr(profile, param.value) for param in RoadProfileParam if param is not RoadProfileParam.CLASS}
    for param in handle.params:
        if param.key in read and param.value != read[param.key]:
            raise DesignError("des.input_changed", obj=f"Parámetro «{param.key}»", field="parámetros", value=param.key)


def run_propose(project: StoreProject, request: RoadRequest, *, version: str | None, masks: access.MaskSet | None = None, supersedes: str | None = None,
                budget_s: float = road_net.STEP_BUDGET_S) -> tuple[OperationHandle, Iterator[Progress]]:
    """Calcula y registra la propuesta ``request`` de **una vez**, sin pedir confirmación (spec 017, T27; RF-017-28, RF-015-02; el recálculo de lo obsoleto, :func:`~.store.recompute_run`; el «Crear»
    tras «Calcular» es :func:`create_propose_steps`): prepara (:func:`prepare_propose`), empieza la operación ``des.road_propose`` **antes de calcular** —sustituye a ``supersedes``, quedándose con el
    nombre de su dato— y devuelve su ``OperationHandle`` «en curso» y sus pasos, que avanza quien la llama: calculan (:func:`propose_compute_steps`), escriben la capa en su temporal y completan la
    operación en una transacción (:func:`create_propose_steps` con el escritor reanudado); el último paso lleva lo guardado (:class:`~.store.Stored`). Cerrarlos antes, o un fallo, no dejan nada y la
    operación queda cancelada o fallida. **No sobrescribe lo que la persona dibujó**: si la capa a la que sustituye se editó en QGIS, ``des.route_layer_edited`` al llamar, sin empezar nada.
    Al llamar, sin empezar nada: los rechazos de :func:`prepare_propose`."""
    prepared = prepare_propose(project, request, version=version, masks=masks, supersedes=supersedes)
    _refuse_edited_proposal(project, prepared, supersedes)
    handle = prepared.start.begin(project)
    return handle, _propose_run(project, handle, prepared, budget_s)


def _propose_run(project: StoreProject, handle: OperationHandle, prepared: PreparedProposal, budget_s: float) -> Generator[Progress, None, None]:
    with DesignWriter.resume(project, handle) as writer:
        _check_recorded_proposal(handle, prepared)
        outcome: ProposalOutcome = yield from propose_compute_steps(prepared.job, surface=prepared.start_surface, budget_s=budget_s)
        stored: Stored = yield from create_propose_steps(project, writer, prepared, outcome, budget_s=budget_s)
        yield Progress(_STORE_PHASE, 1, 1, outcome.message, result=stored)


def recompute_propose(request: RecomputeRequest, *, budget_s: float = road_net.STEP_BUDGET_S) -> tuple[OperationHandle, Iterator[Progress]]:
    """Repite la operación ``des.road_propose`` de ``request`` (:func:`~.store.recompute_run`; «Recalcular lo obsoleto», RF-008-26; spec 017, T27; RF-017-28, RF-015-02): la propuesta de sus ajustes
    (:func:`~.provenance.propose_request`: la petición entera, sin parámetros de entidad) con **lo vigente hoy** —la capa de los puntos, la superficie de partida, las máscaras y los valores del
    perfil, que son entradas o parámetros de la operación: cambiar uno la deja obsoleta, con su causa, y recalcular la repite con lo nuevo; el origen, el destino y las cotas se resuelven otra
    vez—. Devuelve lo de :func:`run_propose`, que **no sobrescribe la capa si se editó en QGIS**. ``TypeError`` si la petición no es una ``RecomputeRequest``; ``ValueError`` si no es de
    ``des.road_propose`` o sus ajustes no son los de una propuesta."""
    if not isinstance(request, RecomputeRequest):
        raise TypeError(f"se recalcula una RecomputeRequest, no {request!r}")
    if request.op_type != provenance.ROAD_PROPOSE:
        raise ValueError(f"recompute_propose repite {provenance.ROAD_PROPOSE}, no «{request.op_type}»")
    project: StoreProject = request.project  # type: ignore[assignment]
    found = require_version(project, request.version, provenance.ROAD_PROPOSE)
    return run_propose(project, provenance.propose_request(request.settings), version=found.uid, supersedes=request.operation_uid, budget_s=budget_s)


# --- La vista previa de la pista (spec 017, T28; RF-017-26, RF-015-26, RF-017-09; RNF-017-06 y RNF-017-08; plan 017 §5.5) -----------------------------------------------------------------------


def corridor_units(job: RoadJob, budget_s: float = road_net.STEP_BUDGET_S) -> Generator[None, None, road_net.Corridor]:
    """Las unidades (cada ``yield``, una; para componerlas con ``pace_units``) del **pasillo** de la ruta de ``job`` («trazar»; RF-017-09, A1): la malla de la ruta (con lo intocable y el peso de «preferible no
    afectar»), la red 2D desde el destino —el nodo del punto o, en una rampa, los nodos de la zona de la cota: :func:`~.road_route.route_target`— y desde el origen, y el pasillo con la holgura de la
    ruta. Es lo que hace :func:`_route_steps` **antes de buscar la ruta 3D**: la vista previa lo dibuja y no busca nada más. Los pasos de la red 2D duran como mucho ``budget_s`` s; cerrarlo a mitad no deja
    nada. ``ValueError`` (error del programa) si ``job`` no es de «trazar»."""
    params = job.route
    if job.mode is not RoadMode.TRACE or params is None or job.geometry.origin is None:
        raise ValueError(f"el pasillo de la ruta es de «trazar», no de «{job.mode.value}»")
    pd, height = job.profile.max_gradient_pct / 100.0, params.max_cut_fill_m
    mesh = road_net.route_mesh(job.grid, job.start, params.mesh_m, job.untouchable, avoid_weight=job.avoid_weight)
    yield
    target = road_route.route_target(job, mesh)
    net_dest = yield from _drain(road_net.network_steps(mesh, target, pd, height, budget_s=budget_s))
    net_origin = yield from _drain(road_net.network_steps(mesh, mesh.node_of(*job.geometry.origin), pd, height, budget_s=budget_s))
    return road_net.corridor(net_origin, net_dest, params.margin_m)


def _corridor_rings(corridor: road_net.Corridor, grid: Grid) -> tuple[np.ndarray, ...]:
    """Los anillos (el exterior y sus huecos, de cada parte; ``(k, 2)`` absolutos, float64) de los nodos del pasillo, trazados sobre la rejilla de la malla de la ruta: ``()`` si el origen no es alcanzable."""
    if not corridor.reachable or not bool(corridor.mask.any()):
        return ()
    rows, cols = corridor.mesh.shape
    nodes = Grid(west=grid.west, north=grid.north, dx=corridor.mesh.mesh_m, dy=corridor.mesh.mesh_m, ncols=cols, nrows=rows)
    return zone_rings(entities.declared_zone(corridor.mask, nodes, 0.0))


def _locked(array: Any) -> np.ndarray:
    """Una vista de solo lectura de ``array`` como float64 (la vista previa no modifica lo que le dan)."""
    view = np.asarray(array, dtype=np.float64).view()
    view.flags.writeable = False
    return view


def _rasante_fields(profile: road_profiles.RoadProfile, points: Any, stations: Any, levels: Any) -> dict[str, Any]:
    """Los datos de **tras calcular** de una vista previa (:class:`~.preview.RoadPreview`): el eje por estaciones, la rasante, los bordes de la sección (a su semianchura), la longitud, la pendiente media
    (D-7: :func:`~.road_gradient.mean_gradient`) y los tramos con su estado frente a pd y pm del ``profile``."""
    axis, s, z = _locked(points), _locked(stations), _locked(levels)
    return {"calculated": True, "axis": axis, "stations": s, "levels": z, "edges": section_edges(axis, road_profiles.derived(profile).half_width_m), "length_m": float(s[-1] - s[0]),
            "gradient_mean_pct": road_gradient.mean_gradient(s, z) * 100.0,
            "stretches": gradient_stretches(s, z, profile.max_gradient_pct, profile.max_mean_gradient_pct)}


def _masks_notice(state: access.MaskState, version: Version, name: str) -> Notice | None:
    """El aviso de que las máscaras de la versión no están al día (no se compilan al previsualizar: escribiría): ``None`` si lo están."""
    if state is access.MaskState.CURRENT:
        return None
    code = "des.preview_entity_masks_missing" if state is access.MaskState.MISSING else "des.preview_entity_masks_stale"
    return Notice(code, {"version": version.code, "entity": name})


def preview_road_units(project: StoreProject, ask: RoadAsk, version_uid: str, *, budget_s: float = road_net.STEP_BUDGET_S) -> Generator[None, None, RoadPreview]:
    """Las unidades (cada ``yield``, una; para componerlas con ``pace_units``) de :func:`~.preview.road_preview_steps`: el :class:`~.preview.RoadPreview` de ``ask`` en la versión ``version_uid`` (RF-017-26).
    **Solo lee** (RF-015-26, RF-015-03).

    - **La pista que se prepara** (``ask.request``): con las máscaras de la versión al día (si no, el aviso en lugar del dibujo: no se compilan), la preparación entera de «Calcular»
      (:func:`prepare_road_units`; **o la que ya hizo** ``ask.prepared``: no se repite) —un rechazo suyo es ``RoadPreview.refusal``—; con ella, el origen y el destino (con su cota), en «trazar» **el
      pasillo** de la ruta (:func:`corridor_units`: la malla, las dos redes 2D y los nodos que pasan, RF-017-09) y, en una rampa, la zona del destino; en «sobre un eje» y «eje 3D», la línea y sus extremos.
      Con ``ask.outcome`` (lo que dejó «Calcular»), en cambio, el **eje con sus curvas, la rasante por tramos y los bordes de la sección**, sin repetir el pasillo (no es de después de calcular).
    - **Una pista de la versión** (``ask.code``): su eje por estaciones guardado (``des_rdx_``) con los valores vigentes de su perfil, el origen y el destino en sus extremos y lo que se le apoya
      (``design.entities.dependents``); una sin calcular se dice. ``ValueError`` si no es una pista de la versión.

    Cerrarlo a mitad no deja nada: no escribe en ningún sitio."""
    state, _pending = access.mask_state(project, version_uid)
    with project.read() as conn:
        version = versions_read.version(conn, version_uid)
    assert version is not None  # mask_state ya lo comprobó
    yield
    if ask.code is not None:
        return (yield from _preview_stored(project, version, ask.code, state))
    asked = ask.request
    prepared: PreparedRoad | None = ask.prepared
    if prepared is None:
        issue = _masks_notice(state, version, asked.name)
        if issue is not None:
            return RoadPreview(asked.name, "", version.code, state, notices=(issue,))
        masks = yield from access.load_masks_steps(project, version.uid)
        try:
            prepared = yield from prepare_road_units(project, asked, version, masks)
        except GeoblenderError as refused:  # lo que rechazaría «Calcular»: es el aviso
            return RoadPreview(asked.name, "", version.code, state, refusal=refused)
        yield
    return (yield from _preview_prepared(prepared, ask.outcome, state, budget_s))


def _preview_prepared(prepared: PreparedRoad, outcome: RoadOutcome | None, state: access.MaskState, budget_s: float) -> Generator[None, None, RoadPreview]:
    """La vista previa de la pista ya preparada ``prepared`` (:func:`preview_road_units`): de antes de calcular o, con su ``outcome``, de después."""
    job, profile = prepared.job, prepared.profile
    grid, request, geometry = job.grid, job.request, job.geometry
    derived = road_profiles.derived(profile)
    head: dict[str, Any] = {"entity": request.name, "code": prepared.code, "version": prepared.version.code}
    widths: dict[str, Any] = {"section": derived.section_m, "carriageway": derived.carriageway_m}
    fields: dict[str, Any] = {"mode": job.mode.value, "start_surface": prepared.start_surface, "profile": profile.name, "cell_m": float(max(grid.dx, grid.dy)),
                              "carriageway_m": derived.carriageway_m, "section_m": derived.section_m, "max_gradient_pct": profile.max_gradient_pct,
                              "max_mean_gradient_pct": profile.max_mean_gradient_pct}
    notices: list[Notice] = []
    if outcome is not None:  # tras calcular: el eje con sus curvas, la rasante por tramos y los bordes de la sección
        axis, levels = outcome.axis, outcome.levels
        if axis is None or levels is None:
            raise ValueError("el resultado de una pista lleva su eje y su rasante: es el de road_compute_steps")
        fields.update(_rasante_fields(profile, axis.points, axis.stations, levels))
        first, end = axis.points[0], axis.points[-1]
        fields.update(points=(RoadPoint("origin", float(first[0]), float(first[1]), float(levels[0])), RoadPoint("destination", float(end[0]), float(end[1]), float(levels[-1]))),
                      curves=int(axis.curve_count), min_radius_m=axis.min_radius_m)
        notices.append(Notice("des.preview_road_calculated", {**head, "length": float(axis.length_m), "curves": int(axis.curve_count), "start_level": float(levels[0]), "end_level": float(levels[-1]),
                                                              "gradient": fields["gradient_mean_pct"], "limit": profile.max_mean_gradient_pct, **widths}))
        notices.extend(prepared.notices)
        notices.extend(outcome.notices)
    elif job.mode is RoadMode.TRACE:  # antes de calcular: el origen, el destino y el pasillo de la ruta
        origin, destination = geometry.origin, geometry.destination
        assert origin is not None and destination is not None
        points = [RoadPoint("origin", origin[0], origin[1], job.start_level_m)]
        notices.append(Notice("des.preview_road_trace", {**head, "surface": prepared.start_surface, "profile": profile.name, **widths}))
        if isinstance(destination, LevelDestination):
            fields.update(zone=tuple(ring for part in destination.zone for ring in part), target_level_m=destination.level_m, target_tolerance_m=destination.tolerance_m)
            notices.append(Notice("des.preview_road_level_destination", {"level": destination.level_m, "tolerance": destination.tolerance_m}))
        else:
            points.append(RoadPoint("destination", destination[0], destination[1], job.end_level_m))
        yield
        corridor = yield from corridor_units(job, budget_s)
        fields.update(points=tuple(points), mesh_m=corridor.mesh.mesh_m, margin_m=corridor.margin_m, reachable=corridor.reachable, lower_bound_m=corridor.lower_bound_m,
                      corridor_nodes=corridor.nodes, corridor=_corridor_rings(corridor, grid))
        if corridor.reachable:
            notices.append(Notice("des.preview_road_corridor", {"mesh": corridor.mesh.mesh_m, "margin": corridor.margin_m, "nodes": corridor.nodes, "bound": corridor.lower_bound_m}))
        else:
            notices.append(Notice("des.preview_road_unreachable"))
        yield
        notices.extend(prepared.notices)
    else:  # «sobre un eje» y «eje 3D»: la línea que sigue, sin ruta ni pasillo
        line = geometry.line
        assert line is not None
        ends = (job.start_level_m, job.end_level_m) if job.mode is RoadMode.ON_AXIS else (float(line[0, 2]), float(line[-1, 2]))
        fields.update(line=_locked(line[:, :2]), points=(RoadPoint("origin", float(line[0, 0]), float(line[0, 1]), ends[0]), RoadPoint("destination", float(line[-1, 0]), float(line[-1, 1]), ends[1])))
        notices.append(Notice("des.preview_road_line", {**head, "feature": request.feature or "", "layer": prepared.layer, "surface": prepared.start_surface, "profile": profile.name, **widths}))
        notices.extend(prepared.notices)
    return RoadPreview(request.name, prepared.code, prepared.version.code, state, notices=tuple(notices), **fields)


def _preview_stored(project: StoreProject, version: Version, code: str, state: access.MaskState) -> Generator[None, None, RoadPreview]:
    """La vista previa de la pista ``code`` de la versión (:func:`preview_road_units`): su eje por estaciones guardado (``des_rdx_``: abscisa, x, y, cota del terreno y de la rasante) con el perfil que
    tiene hoy en la versión (los valores vigentes: pd y pm de los tramos, la anchura de los bordes), el origen y el destino en sus extremos y lo que se le apoya. Sin resultado, se dice. Los rechazos de su
    perfil o de su partida son ``refusal``."""
    registry = entities.registry(project, version.uid)
    entry = registry.get(code)
    if entry is None or entry.record.kind != EntityKind.ROAD:
        raise ValueError(f"«{code}» no es una pista de la versión {version.code}")
    name = entry.record.name
    if entry.operation_uid is None:
        return RoadPreview(name, code, version.code, state, notices=(Notice("des.preview_entity_uncalculated", {"entity": name, "code": code}),))
    with project.read() as conn:
        row = conn.execute("SELECT settings FROM gb_operation WHERE uid = ?", (entry.operation_uid,)).fetchone()
    settings = json.loads(str(row[0])) if row is not None and row[0] else {}
    asked = provenance.road_request(settings, entity_store.entity_parameters(project, code, version=version))
    try:
        profile = _profile(project, version, asked, code)
        start = _start_dataset(registry, version, name, code, asked.start, RoadParam.START)
    except GeoblenderError as refused:
        return RoadPreview(name, code, version.code, state, refusal=refused)
    table = _axis_stations(project, entry)
    yield
    grid = project_frame(project).grid
    derived = road_profiles.derived(profile)
    fields = _rasante_fields(profile, table[:, 1:3], table[:, 0], table[:, 4])
    resting = yield from _resting_units(project, version.uid, code, grid)
    levels = fields["levels"]
    first, end = fields["axis"][0], fields["axis"][-1]
    notices = [Notice("des.preview_road_stored", {"entity": name, "code": code, "version": version.code, "length": fields["length_m"], "start_level": float(levels[0]), "end_level": float(levels[-1]),
                                                  "gradient": fields["gradient_mean_pct"], "limit": profile.max_mean_gradient_pct, "section": derived.section_m,
                                                  "carriageway": derived.carriageway_m})]
    notices.append(Notice("des.preview_entity_supported", {"count": len(resting), "items": _listed_names(resting)}) if resting else Notice("des.preview_entity_supported_none"))
    points = (RoadPoint("origin", float(first[0]), float(first[1]), float(levels[0])), RoadPoint("destination", float(end[0]), float(end[1]), float(levels[-1])))
    return RoadPreview(name, code, version.code, state, mode=RoadMode(asked.mode).value, start_surface=start, profile=profile.name, cell_m=float(max(grid.dx, grid.dy)), points=points,
                       carriageway_m=derived.carriageway_m, section_m=derived.section_m, max_gradient_pct=profile.max_gradient_pct, max_mean_gradient_pct=profile.max_mean_gradient_pct, resting=resting,
                       notices=tuple(notices), **fields)

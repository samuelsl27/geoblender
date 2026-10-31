# SPDX-License-Identifier: GPL-3.0-or-later
"""Las operaciones de ``core`` de las restricciones (spec 012; plan 012 §5.2.3, A12, D-26).

- :data:`DECLARE_SECTORS` (``core.declare_sectors``): declarar los sectores de búsqueda de
  intocables (RF-012-07). Entrada ``source`` (la capa de polígonos de la que salen, si la hay);
  salida ``core_sector``. :func:`declare_sectors` sustituye los sectores guardados (ninguno: el
  perímetro de actuación es el único sector, D-26).
- :data:`FIND_UNTOUCHABLES` (``core.find_untouchables``): cerrar la búsqueda de intocables de un
  sector (RF-012-09). Entradas ``sector`` (``core_sector``, o la capa del perímetro si es el único
  sector) y ``layer_1``…``layer_10`` (las capas consultadas: su hash queda anotado, y si una cambia
  la operación queda obsoleta y la búsqueda deja de estar vigente, A12); lee el parámetro de la
  distancia de búsqueda; salidas ``core_untouchable_search`` y ``core_untouchable_hit``.
  :func:`close_search` la registra con el sector y su huella, lo hallado, lo convertido y lo
  descartado (con su motivo), quién y cuándo (la hora de la operación).

- :data:`EDIT_CONSTRAINTS` (``core.edit_constraints``): crear, completar y editar restricciones
  (RF-012-01, RF-012-02, RF-012-03; plan §5.2.2, D-22). Entrada ``source`` (la capa de la que
  se crean, si la hay); salidas, las capas de restricciones que escribe.
  :func:`edit_constraints` escribe las filas (una nueva o una dibujada en QGIS recibe su código
  inmutable, del nombre, único en las tres capas) y, de las que reciben código, los parámetros
  que pide su tipo como filas ``create`` de la persona (:class:`ParamDeclaration`), en la misma
  transacción. :func:`create_constraints` las crea desde las entidades de una capa
  (:class:`SourceEntity`) con un tipo para todas o el campo que lo da, su correspondencia de
  valores y los campos de nombre, motivo, decisor y fecha (:class:`LayerMapping`): las que no
  sirven se rechazan con su entidad y su motivo (:class:`Rejected`), y la capa de origen solo
  se lee. Una edición en QGIS no pasa por aquí: es una ``core.external_edit`` de la 008.
  Una restricción que sale de una intención del cliente (:func:`convert_intention`,
  RF-012-27) lleva su enlace y ``core_intention`` como entrada ``intention``.
- :data:`EDIT_INTENTIONS` (``core.edit_intentions``): guardar las marcas del cliente como
  intenciones (RF-012-26; D-8). Entradas ``source`` (la capa) y ``document`` (la entrada de
  tipo documento de origen); salida ``core_intention``, que solo crece. :func:`create_intentions`
  las lee de las entidades con su rol, su cota, su fecha y su nombre
  (:class:`IntentionMapping`). Ninguna máscara ni ninguna verificación las lee (error 30).

Las cuatro son de proyecto y no se repiten solas (una búsqueda es una decisión de una persona,
D-26). Las que crean las tablas (todas, la primera vez) escriben además el estilo por defecto de
las tres capas de restricciones en ``layer_styles`` y lo declaran como salida
(``core_layer_styles``, :mod:`.styles`; D-32, RF-012-20). Importar este módulo no registra
nada: lo registra ``bl`` (:data:`OPERATIONS`); las pruebas, a mano. La geometría (validar la capa, el área sin sector, la búsqueda) y la lectura
de las capas la hace ``gis.masks`` (``sectors``, ``sources``), que llama a estas funciones.
Python puro (``core``).
"""

from __future__ import annotations

import math
import sqlite3
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from types import MappingProxyType
from typing import Any

import numpy as np

from ..datasets.model import DatasetSpec
from ..i18n import translate
from ..params.store import ParameterStore
from ..provenance.contract import OperationDef
from ..inputs.model import INACTIVE_STATUSES
from ..provenance.operations import ItemKind, OperationProject, Use, begin_operation
from .messages import ConstraintError, render
from .model import (
    Constraint,
    ConstraintParam,
    ConstraintType,
    GeometryKind,
    Intention,
    IntentionRole,
    SearchHit,
    SearchRecord,
    Sector,
    constraint_code,
)
from .params import SEARCH_DISTANCE, family, param_key
from .store import (
    CONSTRAINT_LAYERS,
    HIT_TABLE,
    INTENTION_TABLE,
    SEARCH_TABLE,
    SECTOR_TABLE,
    append_search,
    create_tables,
    dataset_specs,
    layer_of,
    replace_sectors,
    taken_codes,
    write_constraints,
    write_intentions,
)
from .styles import dataset_spec as styles_spec
from .styles import write_styles

__all__ = [
    "DECLARE_SECTORS",
    "DOCUMENT_ROLE",
    "EDIT_COMMAND",
    "EDIT_CONSTRAINTS",
    "EDIT_INTENTIONS",
    "INTENTIONS_COMMAND",
    "INTENTION_ROLE",
    "FIND_COMMAND",
    "FIND_UNTOUCHABLES",
    "MAX_LAYERS",
    "MODULE",
    "OPERATIONS",
    "OP_VERSION",
    "SECTOR_ROLE",
    "SOURCE_ROLE",
    "EditedConstraints",
    "EditedIntentions",
    "IntentionMapping",
    "LayerMapping",
    "ParamDeclaration",
    "Rejected",
    "SourceEntity",
    "check_entities",
    "close_search",
    "constraint_from_intention",
    "constraints_from_entities",
    "convert_intention",
    "create_constraints",
    "create_intentions",
    "declare_sectors",
    "default_role_values",
    "default_type_values",
    "edit_constraints",
    "edit_intentions",
    "intentions_from_entities",
    "layer_role",
]

MODULE = "core"
OP_VERSION = "1.0"
DECLARE_SECTORS = "core.declare_sectors"
FIND_UNTOUCHABLES = "core.find_untouchables"
FIND_COMMAND = "geoblender.core_find_untouchables"
"""La orden que declara los sectores y busca (plan §5.5)."""
EDIT_CONSTRAINTS = "core.edit_constraints"
EDIT_COMMAND = "geoblender.core_edit_constraints"
"""La ventana Restricciones (plan §5.3.4), que crea, completa y edita (sus diálogos internos
``core_create_constraints`` y ``core_complete_constraint`` se añadirán con su clase real)."""
_EDIT_COMMANDS = (EDIT_COMMAND,)
EDIT_INTENTIONS = "core.edit_intentions"
INTENTIONS_COMMAND = "geoblender.core_edit_client_marks"
"""La orden «Intenciones del cliente…» del catálogo (R-32)."""
SOURCE_ROLE = "source"
DOCUMENT_ROLE = "document"
"""El papel del documento de origen de las intenciones (una entrada de tipo documento)."""
INTENTION_ROLE = "intention"
"""El papel de ``core_intention`` en una ``core.edit_constraints`` que convierte una."""
DOCUMENT_KIND = "document"
SECTOR_ROLE = "sector"
MAX_LAYERS = 10
"""Las capas que consulta una búsqueda, como mucho (plan §5.2.3)."""

OPERATIONS: tuple[OperationDef, ...] = (
    OperationDef(DECLARE_SECTORS, OP_VERSION, MODULE, "Declaration of the search sectors",
                 False, commands=(FIND_COMMAND,)),
    OperationDef(FIND_UNTOUCHABLES, OP_VERSION, MODULE, "Search of untouchable elements",
                 False, commands=(FIND_COMMAND,)),
    OperationDef(EDIT_CONSTRAINTS, OP_VERSION, MODULE, "Edition of the constraints", False,
                 commands=_EDIT_COMMANDS),
    OperationDef(EDIT_INTENTIONS, OP_VERSION, MODULE, "Client intentions", False,
                 commands=(INTENTIONS_COMMAND,)),
)
"""Las operaciones de este módulo, de proyecto y sin repetición."""


def layer_role(position: int) -> str:
    """El papel de entrada de la capa consultada ``position`` (1…:data:`MAX_LAYERS`)."""
    if isinstance(position, bool) or not isinstance(position, int) or not (
            1 <= position <= MAX_LAYERS):
        raise ValueError(f"una búsqueda consulta las capas 1…{MAX_LAYERS}, no {position!r}")
    return f"layer_{position}"


def _create_tables(conn: sqlite3.Connection, srs: int) -> tuple[str, ...]:
    """Crea las tablas que faltan y escribe el estilo por defecto de las capas de restricciones
    que no lo tengan (D-32; también si las capas ya estaban: así no queda ninguna sin él).
    Devuelve lo creado: las tablas y, si escribió estilos, el dato ``core_layer_styles``."""
    created = create_tables(conn, srs)
    return (*created, *write_styles(conn, CONSTRAINT_LAYERS.values()))


def _outputs(created: Sequence[str], written: Sequence[str], srs: int) -> tuple[DatasetSpec, ...]:
    """Los datos que registra la operación: los que escribe y las tablas que acaba de crear
    (vacías, para que no queden sin registrar), con los estilos de las capas si los escribió."""
    chosen = set(created) | set(written)
    return tuple(spec for spec in (*dataset_specs(crs_epsg=srs), styles_spec())
                 if spec.name in chosen)


def declare_sectors(project: OperationProject, sectors: Sequence[Sector], *,
                    source: str | None, field: str | None, uncovered_m2: float | None,
                    srs_id: int) -> str:
    """Registra ``core.declare_sectors``: sustituye los sectores del proyecto por ``sectors`` (ya
    comprobados, RF-012-07; ninguno: el perímetro como único sector) y devuelve el uid de la
    operación. ``source``: el dato de la capa de la que salen (su entrada ``source``) y ``field``
    su campo; ``uncovered_m2``, el área del perímetro sin sector (queda en sus ajustes);
    ``srs_id``, el CRS del proyecto.
    ``ValueError`` si un código se repite o está vacío, o si falta la capa o el campo."""
    sectors = tuple(sectors)
    codes = [sector.code for sector in sectors]
    if any(not code for code in codes) or len(set(codes)) != len(codes):
        raise ValueError(f"cada sector tiene un código propio y no vacío: {codes!r}")
    if (source is None) != (field is None) or (source is None and sectors):
        raise ValueError("los sectores salen de una capa y su campo (o no hay ninguno)")
    srs = int(srs_id)
    settings = {"field": field, "count": len(sectors), "uncovered_m2": uncovered_m2,
                "sectors": [[sector.code, sector.name] for sector in sectors]}
    handle = begin_operation(project, DECLARE_SECTORS, settings=settings,
                             inputs=() if source is None else (Use(source, SOURCE_ROLE),),
                             executor="blender")
    try:
        with project.write_transaction() as conn:
            created = _create_tables(conn, srs)
            replace_sectors(conn, sectors, srs_id=srs)
            handle.complete(conn, outputs=_outputs(created, (SECTOR_TABLE,), srs),
                            message=f"{len(sectors)} sectores de búsqueda declarados")
    except Exception as error:
        handle.fail(str(error) or type(error).__name__)
        raise
    return handle.uid


def close_search(project: OperationProject, *, sector_code: str, sector_sha256: str,
                 sector_dataset: str, layers: Sequence[str], distance_m: float,
                 hits: Sequence[SearchHit], closed_by: str, srs_id: int) -> SearchRecord:
    """Registra ``core.find_untouchables``: la búsqueda cerrada del sector ``sector_code``
    (``""``: el perímetro) con la huella de la geometría revisada, el dato del sector
    (``sector_dataset``: ``core_sector`` o la capa del perímetro), las capas consultadas
    (``layers``, nombres de datos del proyecto: sus entradas ``layer_1``…), la distancia leída
    y cada entidad hallada con su decisión (``hits``; su ``search_uid`` no cuenta); quién la
    cierra (``closed_by``) y cuándo (la hora de la operación); ``srs_id``, el CRS del proyecto
    (si hay que crear las tablas). Devuelve lo registrado.

    :class:`~.messages.ConstraintError` ``core.constraint_search_layers`` sin capas o con más
    de :data:`MAX_LAYERS`; ``ValueError`` si una capa se repite, una entidad es de otra capa, la
    distancia no es un número positivo o falta quién la cierra."""
    layers = tuple(layers)
    if not 1 <= len(layers) <= MAX_LAYERS:
        raise ConstraintError("core.constraint_search_layers", field="capas",
                              value=len(layers), max=MAX_LAYERS)
    if len(set(layers)) != len(layers):
        raise ValueError(f"una búsqueda no consulta dos veces la misma capa: {layers!r}")
    if isinstance(distance_m, bool) or not isinstance(distance_m, int | float) or not (
            math.isfinite(distance_m) and distance_m > 0.0):
        raise ValueError(f"la distancia de búsqueda es un número positivo, no {distance_m!r}")
    if not isinstance(closed_by, str) or not closed_by.strip():
        raise ValueError("una búsqueda la cierra una persona: falta quién")
    hits = tuple(hits)
    strangers = sorted({hit.layer_dataset for hit in hits} - set(layers))
    if strangers:
        raise ValueError(f"entidades de capas que no se consultaron: {strangers!r}")
    converted = sum(1 for hit in hits if hit.constraint_code is not None)
    settings = {"sector": sector_code, "sector_sha256": sector_sha256,
                "distance_m": float(distance_m), "layers": list(layers), "found": len(hits),
                "converted": converted, "discarded": len(hits) - converted}
    inputs = (Use(sector_dataset, SECTOR_ROLE),
              *(Use(name, layer_role(index)) for index, name in enumerate(layers, start=1)))
    srs = int(srs_id)
    handle = begin_operation(project, FIND_UNTOUCHABLES, settings=settings, inputs=inputs,
                             params=(SEARCH_DISTANCE.key,), executor="blender")
    record = SearchRecord(uuid.uuid4().hex, handle.uid, sector_code, sector_sha256,
                          float(distance_m), closed_by.strip(), handle.started_at)
    try:
        with project.write_transaction() as conn:
            created = _create_tables(conn, srs)
            append_search(conn, record, [replace(hit, search_uid=record.uid) for hit in hits])
            handle.complete(conn, outputs=_outputs(created, (SEARCH_TABLE, HIT_TABLE), srs),
                            message=f"Búsqueda de intocables cerrada: {len(hits)} halladas")
    except Exception as error:
        handle.fail(str(error) or type(error).__name__)
        raise
    return record


# --- Crear, completar y editar restricciones (RF-012-01, RF-012-02, RF-012-03) ------------------


@dataclass(frozen=True, slots=True)
class ParamDeclaration:
    """Lo que declara la persona de los parámetros de las restricciones que crea o completa
    (RF-012-02; plan §5.2.2; D-5: ningún valor por defecto): el valor de cada parámetro
    (``values``; de cada restricción se escriben solo los que pide su tipo), su origen
    (``source`` y ``source_kind``), quién lo decide y por qué; ``kinds``, el tipo de alguno
    (si no, el de su familia: ADOPTADO «activa», HIPÓTESIS los demás)."""

    values: Mapping[ConstraintParam, Any]
    source: str
    decided_by: str
    reason: str
    source_kind: str = "person"
    kinds: Mapping[ConstraintParam, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType(
            {ConstraintParam(param): value for param, value in self.values.items()}))
        object.__setattr__(self, "kinds", MappingProxyType(
            {ConstraintParam(param): str(kind) for param, kind in self.kinds.items()}))

    def kind_of(self, param: ConstraintParam) -> str:
        """El tipo con que se da de alta ``param``."""
        return self.kinds.get(param) or str(family(param).template.kind)


@dataclass(frozen=True, slots=True)
class LayerMapping:
    """Cómo se leen las restricciones de las entidades de una capa (RF-012-01): un tipo para
    todas (``ctype``) o el campo que lo da (``type_field``) con su correspondencia de valores
    (``type_values``, valor → tipo, sin distinguir mayúsculas ni los espacios de los extremos;
    sin ella, :func:`default_type_values`); el campo del nombre; el motivo, el decisor y la
    fecha, de un campo o fijos para todas; y la prioridad (solo ordena, D-13)."""

    ctype: ConstraintType | None = None
    type_field: str | None = None
    type_values: Mapping[str, ConstraintType] | None = None
    name_field: str | None = None
    reason_field: str | None = None
    reason: str | None = None
    decider_field: str | None = None
    decided_by: str | None = None
    date_field: str | None = None
    decided_on: date | None = None
    priority: int = 0

    def __post_init__(self) -> None:
        if (self.ctype is None) == (self.type_field is None):
            raise ValueError("el tipo es uno para todas (ctype) o el de un campo (type_field)")
        if self.ctype is not None:
            object.__setattr__(self, "ctype", ConstraintType(self.ctype))
        for chosen, fixed, what in ((self.reason_field, self.reason, "el motivo"),
                                    (self.decider_field, self.decided_by, "el decisor"),
                                    (self.date_field, self.decided_on, "la fecha")):
            if chosen is not None and fixed is not None:
                raise ValueError(f"{what} sale de un campo o es fijo, no las dos cosas")
        if self.type_values is not None:
            object.__setattr__(self, "type_values", MappingProxyType(
                {_key(value): ConstraintType(ctype)
                 for value, ctype in self.type_values.items()}))
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise ValueError(f"la prioridad es un entero, no {self.priority!r}")

    def fields(self) -> tuple[str, ...]:
        """Los campos de la capa que usa, en su orden y sin repetir."""
        chosen = (self.type_field, self.name_field, self.reason_field, self.decider_field,
                  self.date_field)
        return tuple(dict.fromkeys(name for name in chosen if name is not None))

    def with_fields(self, columns: Mapping[str, str]) -> LayerMapping:
        """La misma con cada campo cambiado por ``columns[campo]`` (su columna)."""
        def column(name: str | None) -> str | None:
            return None if name is None else columns[name]

        return replace(self, type_field=column(self.type_field),
                       name_field=column(self.name_field),
                       reason_field=column(self.reason_field),
                       decider_field=column(self.decider_field),
                       date_field=column(self.date_field))

    def settings(self) -> dict[str, Any]:
        """Sus ajustes en JSON (los de la operación)."""
        values = None if self.type_values is None else {
            value: ctype.value for value, ctype in sorted(self.type_values.items())}
        return {"ctype": None if self.ctype is None else self.ctype.value,
                "type_field": self.type_field, "type_values": values,
                "name_field": self.name_field, "reason_field": self.reason_field,
                "reason": self.reason, "decider_field": self.decider_field,
                "decided_by": self.decided_by, "date_field": self.date_field,
                "decided_on": None if self.decided_on is None else self.decided_on.isoformat(),
                "priority": self.priority}


@dataclass(frozen=True, slots=True)
class SourceEntity:
    """Una entidad de la capa de origen: su número, su geometría (``kind``), sus partes
    absolutas (de cada parte, sus anillos, su camino o su punto ``(1, 2)``) y sus atributos
    (columna → valor)."""

    fid: int
    kind: GeometryKind
    parts: tuple[tuple[np.ndarray, ...], ...]
    attributes: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class Rejected:
    """Una entidad de la capa de origen que no se crea (RF-012-01): su capa, su número, el
    problema (``no_geometry``, ``type_unknown``, ``field_empty``, ``kind_not_accepted`` o
    ``date_invalid``), el campo y el valor que lo causan, y el tipo y la geometría si
    cuentan."""

    layer: str
    fid: int
    problem: str
    field: str | None = None
    value: str | None = None
    ctype: ConstraintType | None = None
    kind: GeometryKind | None = None

    def text(self, language: str = "es") -> str:
        """El rechazo con su entidad y su motivo."""
        kind = None if self.kind is None else translate(language, self.kind.article_msgid)
        return render(f"core.constraint_source_{self.problem}", language=language,
                      fid=self.fid, layer=self.layer, field=self.field, value=self.value,
                      ctype=None if self.ctype is None else self.ctype.label(language),
                      kind=kind)


@dataclass(frozen=True, slots=True)
class EditedConstraints:
    """Lo que dejó ``core.edit_constraints``: su operación, las restricciones escritas (con su
    ``fid`` y su código, en su orden) y las entidades rechazadas."""

    operation_uid: str
    constraints: tuple[Constraint, ...]
    rejected: tuple[Rejected, ...] = ()


def _key(value: object) -> str:
    return str(value).strip().casefold()


def default_type_values() -> Mapping[str, ConstraintType]:
    """La correspondencia por defecto del campo del tipo: cada código (``untouchable``), su
    nombre en español («Intocable») y su ``msgid`` en inglés («Untouchable»)."""
    found: dict[str, ConstraintType] = {}
    for ctype in ConstraintType:
        for value in (ctype.value, ctype.label("es"), ctype.label_msgid):
            found[_key(value)] = ctype
    return MappingProxyType(found)


def _text(value: object) -> str | None:
    if value is None:
        return None
    shown = str(value).strip()
    return shown or None


def _when(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip()[:10])


def _rejection(entity: SourceEntity, mapping: LayerMapping,
               values: Mapping[str, ConstraintType]
               ) -> tuple[ConstraintType | None, tuple[str, str | None, object, Any]]:
    """El tipo de ``entity`` o lo que la rechaza: (problema, campo, valor, tipo)."""
    if not entity.parts:
        return None, ("no_geometry", None, None, None)
    ctype = mapping.ctype
    if mapping.type_field is not None:
        raw = entity.attributes.get(mapping.type_field)
        if _text(raw) is None:
            return None, ("field_empty", mapping.type_field, None, None)
        ctype = values.get(_key(raw))
        if ctype is None:
            return None, ("type_unknown", mapping.type_field, _text(raw), None)
    assert ctype is not None
    if not ctype.accepts(entity.kind):
        return None, ("kind_not_accepted", None, None, ctype)
    for name in (mapping.name_field, mapping.reason_field, mapping.decider_field):
        if name is not None and _text(entity.attributes.get(name)) is None:
            return None, ("field_empty", name, None, None)
    if mapping.date_field is not None:
        raw = entity.attributes.get(mapping.date_field)
        try:
            if _text(raw) is not None:
                _when(raw)
        except ValueError:
            return None, ("date_invalid", mapping.date_field, _text(raw), None)
    return ctype, ("", None, None, None)


def constraints_from_entities(entities: Sequence[SourceEntity], mapping: LayerMapping, *,
                              layer: str, source_input: str | None
                              ) -> tuple[tuple[Constraint, ...], tuple[Rejected, ...]]:
    """Las restricciones nuevas (``fid`` 0, sin código: lo reciben al escribirse) de
    ``entities`` de la capa ``layer`` según ``mapping`` (con los campos ya como columnas), con
    su origen (``source_input``, la entrada de la capa, y la entidad) y su geometría tal cual,
    y las entidades rechazadas con su motivo, en su orden: geometría vacía, tipo vacío o fuera
    de la correspondencia, un tipo que no cabe en esa geometría (un límite que no es un
    polígono), un campo de nombre, motivo o decisor vacío y una fecha que no lo es."""
    values = default_type_values() if mapping.type_values is None else mapping.type_values
    rows: list[Constraint] = []
    rejected: list[Rejected] = []
    for entity in entities:
        kind = GeometryKind(entity.kind)
        entity = replace(entity, kind=kind)
        ctype, (problem, name, value, wrong) = _rejection(entity, mapping, values)
        if ctype is None:
            rejected.append(Rejected(layer, int(entity.fid), problem, name,
                                     None if value is None else str(value), wrong,
                                     kind if problem == "kind_not_accepted" else None))
            continue
        attributes = entity.attributes

        def chosen(column: str | None, fixed: object) -> str | None:
            return _text(attributes.get(column) if column is not None else fixed)

        raw_date = None if mapping.date_field is None else attributes.get(mapping.date_field)
        decided_on = (mapping.decided_on if mapping.date_field is None
                      else None if _text(raw_date) is None else _when(raw_date))
        rows.append(Constraint(
            uid=uuid.uuid4().hex, code="", name=chosen(mapping.name_field, None) or "",
            ctype=ctype, kind=kind, parts=entity.parts, priority=mapping.priority,
            reason=chosen(mapping.reason_field, mapping.reason),
            decided_by=chosen(mapping.decider_field, mapping.decided_by),
            decided_on=decided_on, decision_uid=None, intention_uid=None,
            source_input=source_input, source_fid=int(entity.fid), layer=layer_of(kind),
            fid=0))
    return tuple(rows), tuple(rejected)


def _write_params(conn: Any, project: OperationProject, rows: Sequence[Constraint],
                  declared: ParamDeclaration) -> None:
    """Da de alta, en la transacción ``conn``, los parámetros que pide el tipo de cada una de
    ``rows`` y declara ``declared`` (filas ``create`` del proyecto; RF-008-01)."""
    store = ParameterStore(project)  # type: ignore[arg-type]
    for row in rows:
        if row.ctype is None:
            continue
        for param in row.ctype.requires:
            if param not in declared.values:
                continue
            store.create(conn, param_key(row.code, param), declared.values[param],
                         kind=declared.kind_of(param), source=declared.source,
                         source_kind=declared.source_kind, decided_by=declared.decided_by,
                         reason=declared.reason)


def edit_constraints(project: OperationProject, rows: Sequence[Constraint], *,
                     params: ParamDeclaration | None = None, source: str | None = None,
                     settings: Mapping[str, Any] | None = None,
                     rejected: Sequence[Rejected] = (), srs_id: int) -> EditedConstraints:
    """Registra ``core.edit_constraints``: escribe ``rows`` en su capa (``fid`` ≤ 0, nuevas;
    > 0, sustituyen la fila del mismo ``uid``: completar una dibujada en QGIS o cambiar sus
    atributos) y devuelve lo escrito. Cada una sin código (nueva o dibujada en QGIS) recibe el
    de su nombre, único en las tres capas (D-22), y de ellas se dan de alta los parámetros que
    pide su tipo según ``params`` (RF-012-02), en la misma transacción; las que ya tenían código
    no tocan sus parámetros (se cambian en Parámetros, con su ámbito, RF-009-24). ``source``: el
    dato de la capa de la que salen (su entrada ``source``); ``settings`` y ``rejected``, lo que
    se anota en los ajustes; ``srs_id``, el CRS del proyecto. Si alguna sale de una intención
    del cliente (``intention_uid``, RF-012-27), ``core_intention`` es la entrada
    ``intention`` (una intención que no está: ``ValueError``, sin registrar nada).

    Los rechazos de ``store.write_constraints`` (``core.constraint_code_taken``,
    ``core.constraint_code_immutable``) y de los parámetros (``ParamError``) no dejan nada
    escrito (la operación queda fallida); ``ValueError`` sin filas."""
    rows = tuple(rows)
    if not rows:
        raise ValueError("una edición de las restricciones escribe al menos una")
    srs = int(srs_id)
    noted = dict(settings or {})
    noted.update({
        "source": source, "count": len(rows),
        "created": sum(1 for row in rows if row.fid <= 0),
        "completed": sum(1 for row in rows if row.fid > 0 and not row.code),
        "rejected": [[item.fid, item.problem, item.field] for item in rejected],
    })
    intentions = sorted({row.intention_uid for row in rows if row.intention_uid})
    inputs = [] if source is None else [Use(source, SOURCE_ROLE)]
    if intentions:
        with project.read() as conn:
            known = {uid for (uid,) in conn.execute(
                f"SELECT uid FROM {INTENTION_TABLE}")} if INTENTION_TABLE in _tables(conn) \
                else set()
        missing = [uid for uid in intentions if uid not in known]
        if missing:
            raise ValueError(f"intenciones que no están en el proyecto: {missing!r}")
        noted["intentions"] = intentions
        inputs.append(Use(INTENTION_TABLE, INTENTION_ROLE))
    handle = begin_operation(project, EDIT_CONSTRAINTS, settings=noted, inputs=tuple(inputs),
                             executor="blender")
    try:
        with project.write_transaction() as conn:
            created = _create_tables(conn, srs)
            taken = taken_codes(conn)
            coded: list[Constraint] = []
            fresh: set[str] = set()
            for row in rows:
                if not row.code:
                    code = constraint_code(row.name, taken)
                    taken.add(code)
                    row = replace(row, code=code)
                    fresh.add(row.uid)
                coded.append(row)
            fids = write_constraints(conn, coded, srs_id=srs)
            written = tuple(replace(row, fid=fid) for row, fid in zip(coded, fids, strict=True))
            if params is not None:
                _write_params(conn, project, [row for row in written if row.uid in fresh],
                              params)
            tables = tuple(dict.fromkeys(layer_of(row.kind) for row in written))
            handle.complete(conn, outputs=_outputs(created, tables, srs),
                            message=f"{len(written)} restricciones escritas")
    except Exception as error:
        handle.fail(str(error) or type(error).__name__)
        raise
    return EditedConstraints(handle.uid, written, tuple(rejected))


def _named(rows: Sequence[Constraint], base: str) -> tuple[Constraint, ...]:
    """``rows`` con ``base`` de nombre en las que no lo tienen: ``base`` si es la única
    restricción y «``base`` <número en la capa>» si son varias."""
    only = len(rows) == 1
    return tuple(row if row.name else replace(
        row, name=base if only else f"{base} {row.source_fid}") for row in rows)


def check_entities(entities: Sequence[SourceEntity], mapping: LayerMapping, *, layer: str,
                   source_input: str | None
                   ) -> tuple[tuple[Constraint, ...], tuple[Rejected, ...]]:
    """:func:`constraints_from_entities` que rechaza la capa entera si no sirve ninguna entidad:
    :class:`~.messages.ConstraintError` ``core.constraint_source_nothing`` (con la lista de las
    rechazadas). No escribe nada: es lo que comprueba :func:`create_constraints` antes de
    registrar, para que una orden con varias capas lo mire todo antes de crear nada."""
    rows, rejected = constraints_from_entities(entities, mapping, layer=layer,
                                               source_input=source_input)
    if not rows:
        raise ConstraintError("core.constraint_source_nothing", field="capa",
                              value=len(rejected), layer=layer,
                              problems="; ".join(item.text() for item in rejected) or "—")
    return rows, rejected


def create_constraints(project: OperationProject, entities: Sequence[SourceEntity],
                       mapping: LayerMapping, *, layer: str, source: str | None,
                       source_input: str | None, params: ParamDeclaration | None,
                       srs_id: int, default_name: str | None = None) -> EditedConstraints:
    """Crea las restricciones de las entidades de la capa ``layer`` (RF-012-01) según
    ``mapping`` (con los campos ya como columnas) con :func:`edit_constraints`, anotando la
    correspondencia y las rechazadas. ``default_name`` (T22: los límites de una capa sin campo
    del nombre) da nombre a las que no lo tienen (:func:`_named`), y queda en los ajustes.
    :class:`~.messages.ConstraintError` ``core.constraint_source_nothing`` (con la lista) si no
    sirve ninguna, sin registrar nada (:func:`check_entities`)."""
    rows, rejected = check_entities(entities, mapping, layer=layer, source_input=source_input)
    settings: dict[str, Any] = {"mapping": mapping.settings()}
    if default_name:
        rows = _named(rows, default_name)
        settings["default_name"] = default_name
    return edit_constraints(project, rows, params=params, source=source, settings=settings,
                            rejected=rejected, srs_id=srs_id)



# --- Intenciones del cliente (RF-012-26, RF-012-27; D-8) ---------------------------------------


def _tables(conn: Any) -> set[str]:
    return {str(name) for (name,) in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}


@dataclass(frozen=True, slots=True)
class IntentionMapping:
    """Cómo se leen las intenciones de las entidades de una capa (RF-012-26): un rol para todas
    (``role``) o el campo que lo da (``role_field``) con su correspondencia de valores
    (``role_values``, valor → rol, sin distinguir mayúsculas ni los espacios de los extremos;
    sin ella, :func:`default_role_values`); el campo del nombre; la cota de «explotar a una
    cota» (m), de un campo o fija; y la fecha, de un campo o fija (una de las dos)."""

    role: IntentionRole | None = None
    role_field: str | None = None
    role_values: Mapping[str, IntentionRole] | None = None
    name_field: str | None = None
    elevation_field: str | None = None
    elevation_m: float | None = None
    date_field: str | None = None
    stated_on: date | None = None

    def __post_init__(self) -> None:
        if (self.role is None) == (self.role_field is None):
            raise ValueError("el rol es uno para todas (role) o el de un campo (role_field)")
        if self.role is not None:
            object.__setattr__(self, "role", IntentionRole(self.role))
        if self.elevation_field is not None and self.elevation_m is not None:
            raise ValueError("la cota sale de un campo o es fija, no las dos cosas")
        if (self.date_field is None) == (self.stated_on is None):
            raise ValueError("la fecha de las marcas sale de un campo o es fija (una de las "
                             "dos)")
        if self.elevation_m is not None and _elevation(self.elevation_m) is None:
            raise ValueError(f"la cota fija no es un número finito: {self.elevation_m!r}")
        if self.role_values is not None:
            object.__setattr__(self, "role_values", MappingProxyType(
                {_key(value): IntentionRole(role) for value, role in self.role_values.items()}))

    def fields(self) -> tuple[str, ...]:
        """Los campos de la capa que usa, en su orden y sin repetir."""
        chosen = (self.role_field, self.name_field, self.elevation_field, self.date_field)
        return tuple(dict.fromkeys(name for name in chosen if name is not None))

    def with_fields(self, columns: Mapping[str, str]) -> IntentionMapping:
        """La misma con cada campo cambiado por ``columns[campo]`` (su columna)."""
        def column(name: str | None) -> str | None:
            return None if name is None else columns[name]

        return replace(self, role_field=column(self.role_field),
                       name_field=column(self.name_field),
                       elevation_field=column(self.elevation_field),
                       date_field=column(self.date_field))

    def settings(self) -> dict[str, Any]:
        """Sus ajustes en JSON (los de la operación)."""
        values = None if self.role_values is None else {
            value: role.value for value, role in sorted(self.role_values.items())}
        return {"role": None if self.role is None else self.role.value,
                "role_field": self.role_field, "role_values": values,
                "name_field": self.name_field, "elevation_field": self.elevation_field,
                "elevation_m": self.elevation_m, "date_field": self.date_field,
                "stated_on": None if self.stated_on is None else self.stated_on.isoformat()}


@dataclass(frozen=True, slots=True)
class EditedIntentions:
    """Lo que dejó ``core.edit_intentions``: su operación, las intenciones guardadas (con su
    ``fid``, en su orden) y las entidades rechazadas."""

    operation_uid: str
    intentions: tuple[Intention, ...]
    rejected: tuple[Rejected, ...] = ()


def default_role_values() -> Mapping[str, IntentionRole]:
    """La correspondencia por defecto del campo del rol: cada código (``protect``), su nombre
    en español («Proteger») y su ``msgid`` en inglés («Protect»)."""
    found: dict[str, IntentionRole] = {}
    for role in IntentionRole:
        for value in (role.value, role.label("es"), role.label_msgid):
            found[_key(value)] = role
    return MappingProxyType(found)


def _elevation(value: object) -> float | None:
    """La cota de ``value`` (número o texto exacto, con punto o coma decimal) en float64;
    ``None`` si no es un número finito."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float | np.floating | np.integer):
        number = float(value)
    else:
        try:
            number = float(str(value).strip().replace(",", "."))
        except ValueError:
            return None
    return number if math.isfinite(number) else None


_NO_INTENTION: tuple[None, None, None] = (None, None, None)


def _intention_rejection(entity: SourceEntity, mapping: IntentionMapping,
                         values: Mapping[str, IntentionRole]
                         ) -> tuple[IntentionRole | None, float | None, date | None,
                                    tuple[str, str | None, object]]:
    """El rol, la cota y la fecha de ``entity``, o lo que la rechaza: (problema, campo,
    valor)."""
    if not entity.parts:
        return (*_NO_INTENTION, ("no_geometry", None, None))
    role = mapping.role
    if mapping.role_field is not None:
        raw = entity.attributes.get(mapping.role_field)
        if _text(raw) is None:
            return (*_NO_INTENTION, ("field_empty", mapping.role_field, None))
        role = values.get(_key(raw))
        if role is None:
            return (*_NO_INTENTION, ("role_unknown", mapping.role_field, _text(raw)))
    assert role is not None
    if mapping.name_field is not None and _text(
            entity.attributes.get(mapping.name_field)) is None:
        return (*_NO_INTENTION, ("field_empty", mapping.name_field, None))
    elevation = mapping.elevation_m
    if mapping.elevation_field is not None:
        raw_elevation = entity.attributes.get(mapping.elevation_field)
        given = _text(raw_elevation)
        elevation = None
        if given is not None:
            elevation = _elevation(raw_elevation)
            if elevation is None:
                return (*_NO_INTENTION, ("elevation_invalid", mapping.elevation_field, given))
            if not role.requires_elevation:
                return (*_NO_INTENTION, ("elevation_unexpected", mapping.elevation_field,
                                         given))
    if not role.requires_elevation:
        elevation = None
    elif elevation is None:
        return (*_NO_INTENTION, ("elevation_missing", mapping.elevation_field, None))
    stated_on = mapping.stated_on
    if mapping.date_field is not None:
        raw = entity.attributes.get(mapping.date_field)
        if _text(raw) is None:
            return (*_NO_INTENTION, ("field_empty", mapping.date_field, None))
        try:
            stated_on = _when(raw)
        except ValueError:
            return (*_NO_INTENTION, ("date_invalid", mapping.date_field, _text(raw)))
    return role, elevation, stated_on, ("", None, None)


def intentions_from_entities(entities: Sequence[SourceEntity], mapping: IntentionMapping, *,
                             layer: str, source_input: str, document_input: str,
                             decision_uid: str | None
                             ) -> tuple[tuple[Intention, ...], tuple[Rejected, ...]]:
    """Las intenciones nuevas (``fid`` 0) de ``entities`` de la capa ``layer`` según
    ``mapping`` (con los campos ya como columnas), con su origen (``source_input``, la entrada
    de la capa, y la entidad), su documento (``document_input``, una entrada de tipo
    documento), la decisión enlazada y su geometría tal cual; y las entidades rechazadas con su
    motivo, en su orden: geometría vacía, rol vacío o fuera de la correspondencia, nombre o
    fecha vacíos, una cota que no es un número, una cota en otro rol, «explotar a una cota» sin
    cota y una fecha que no lo es (RF-012-26)."""
    values = default_role_values() if mapping.role_values is None else mapping.role_values
    rows: list[Intention] = []
    rejected: list[Rejected] = []
    for entity in entities:
        kind = GeometryKind(entity.kind)
        entity = replace(entity, kind=kind)
        role, elevation, stated_on, (problem, name, value) = _intention_rejection(
            entity, mapping, values)
        if role is None:
            rejected.append(Rejected(layer, int(entity.fid), problem, name,
                                     None if value is None else str(value)))
            continue
        assert stated_on is not None
        shown = (None if mapping.name_field is None
                 else _text(entity.attributes.get(mapping.name_field)))
        rows.append(Intention(
            uid=uuid.uuid4().hex, name=shown or "", role=role, kind=kind, parts=entity.parts,
            elevation_m=elevation, stated_on=stated_on, document_input=document_input,
            decision_uid=decision_uid, source_input=source_input,
            source_fid=int(entity.fid), fid=0))
    return tuple(rows), tuple(rejected)


def _check_document(conn: Any, document: str) -> None:
    """Que ``document`` sea una entrada activa de tipo documento del proyecto."""
    row = conn.execute("SELECT name, kind, status FROM gb_input WHERE uid = ?",
                       (document,)).fetchone() if "gb_input" in _tables(conn) else None
    if row is None or str(row[2]) in {str(status) for status in INACTIVE_STATUSES}:
        raise ConstraintError("core.constraint_intention_document_unknown", field="documento",
                              value=document)
    if str(row[1]) != DOCUMENT_KIND:
        raise ConstraintError("core.constraint_intention_document_kind", field="documento",
                              value=document, input=str(row[0]), kind=str(row[1]))


def _check_decision(conn: Any, decision_uid: str) -> None:
    found = conn.execute("SELECT 1 FROM gb_decision WHERE uid = ?",
                         (decision_uid,)).fetchone() if "gb_decision" in _tables(conn) else None
    if found is None:
        raise ConstraintError("core.constraint_intention_decision_unknown", field="decisión",
                              value=decision_uid)


def edit_intentions(project: OperationProject, rows: Sequence[Intention], *, source: str,
                    settings: Mapping[str, Any] | None = None,
                    rejected: Sequence[Rejected] = (), srs_id: int) -> EditedIntentions:
    """Registra ``core.edit_intentions``: añade las intenciones ``rows`` a ``core_intention``
    (una intención no se cambia ni se borra, RF-012-27) y devuelve lo guardado. Entradas: la
    capa de la que salen (``source``, su dato) y cada documento de origen (``document``, la
    entrada de tipo documento). Las intenciones no entran en ninguna máscara ni en ninguna
    verificación (RF-012-26; error 30): ninguna compilación las lee.

    :class:`~.messages.ConstraintError`, sin registrar nada: un documento que no es una
    entrada activa del proyecto (``core.constraint_intention_document_unknown``) o no es de
    tipo documento (``_document_kind``), y una decisión que no está
    (``_decision_unknown``); ``ValueError`` sin filas."""
    rows = tuple(rows)
    if not rows:
        raise ValueError("una edición de las intenciones guarda al menos una")
    documents = list(dict.fromkeys(row.document_input for row in rows))
    decisions = sorted({row.decision_uid for row in rows if row.decision_uid})
    with project.read() as conn:
        for document in documents:
            _check_document(conn, document)
        for decision in decisions:
            _check_decision(conn, decision)
    srs = int(srs_id)
    noted = dict(settings or {})
    noted.update({"source": source, "count": len(rows), "documents": documents,
                  "decisions": decisions,
                  "rejected": [[item.fid, item.problem, item.field] for item in rejected]})
    inputs = (Use(source, SOURCE_ROLE),
              *(Use(document, DOCUMENT_ROLE, kind=ItemKind.INPUT) for document in documents))
    handle = begin_operation(project, EDIT_INTENTIONS, settings=noted, inputs=inputs,
                             executor="blender")
    try:
        with project.write_transaction() as conn:
            created = _create_tables(conn, srs)
            fids = write_intentions(conn, rows, srs_id=srs)
            written = tuple(replace(row, fid=fid) for row, fid in zip(rows, fids, strict=True))
            handle.complete(conn, outputs=_outputs(created, (INTENTION_TABLE,), srs),
                            message=f"{len(written)} intenciones del cliente guardadas")
    except Exception as error:
        handle.fail(str(error) or type(error).__name__)
        raise
    return EditedIntentions(handle.uid, written, tuple(rejected))


def create_intentions(project: OperationProject, entities: Sequence[SourceEntity],
                      mapping: IntentionMapping, *, layer: str, source: str,
                      source_input: str, document: str, decision_uid: str | None,
                      srs_id: int) -> EditedIntentions:
    """Guarda como intenciones las marcas de la capa ``layer`` (RF-012-26) según ``mapping``
    (con los campos ya como columnas) con :func:`edit_intentions`, anotando la
    correspondencia y las rechazadas. :class:`~.messages.ConstraintError`
    ``core.constraint_intention_nothing`` (con la lista) si no sirve ninguna, sin registrar
    nada."""
    rows, rejected = intentions_from_entities(
        entities, mapping, layer=layer, source_input=source_input, document_input=document,
        decision_uid=decision_uid)
    if not rows:
        raise ConstraintError("core.constraint_intention_nothing", field="capa",
                              value=len(rejected), layer=layer,
                              problems="; ".join(item.text() for item in rejected) or "—")
    return edit_intentions(project, rows, source=source,
                           settings={"mapping": mapping.settings()}, rejected=rejected,
                           srs_id=srs_id)


def constraint_from_intention(intention: Intention, *, ctype: ConstraintType, reason: str,
                              decided_by: str, decided_on: date | None,
                              name: str | None = None, priority: int = 0) -> Constraint:
    """La restricción nueva (``fid`` 0, sin código) que sale de ``intention`` con el tipo, el
    motivo y el decisor que declara la persona (RF-012-27): su geometría, su nombre (o
    ``name``), el origen de la intención y el enlace a ella. La intención no cambia.
    :class:`~.messages.ConstraintError` ``core.constraint_intention_kind_not_accepted`` si el
    tipo no cabe en su geometría (un límite que no es un polígono)."""
    ctype = ConstraintType(ctype)
    if not ctype.accepts(intention.kind):
        raise ConstraintError("core.constraint_intention_kind_not_accepted", field="tipo",
                              value=ctype.value, intention=intention.name,
                              kind=translate("es", intention.kind.article_msgid),
                              ctype=ctype.label("es"))
    return Constraint(
        uid=uuid.uuid4().hex, code="", name=intention.name if name is None else name,
        ctype=ctype, kind=intention.kind, parts=intention.parts, priority=priority,
        reason=_text(reason), decided_by=_text(decided_by), decided_on=decided_on,
        decision_uid=None, intention_uid=intention.uid,
        source_input=intention.source_input, source_fid=intention.source_fid,
        layer=layer_of(intention.kind), fid=0)


def convert_intention(project: OperationProject, intention: Intention, *,
                      ctype: ConstraintType, reason: str, decided_by: str,
                      decided_on: date | None, params: ParamDeclaration | None,
                      name: str | None = None, priority: int = 0,
                      srs_id: int) -> EditedConstraints:
    """Convierte ``intention`` en restricción (RF-012-27) con
    :func:`constraint_from_intention` y :func:`edit_constraints` (con ``core_intention`` como
    entrada ``intention`` y los parámetros ``params`` de su tipo); la intención no cambia ni se
    borra."""
    row = constraint_from_intention(intention, ctype=ctype, reason=reason,
                                    decided_by=decided_by, decided_on=decided_on, name=name,
                                    priority=priority)
    return edit_constraints(project, [row], params=params,
                            settings={"intention": intention.uid}, srs_id=srs_id)

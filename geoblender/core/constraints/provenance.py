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

Las tres son de proyecto y no se repiten solas (una búsqueda es una decisión de una persona,
D-26). Importar este módulo no registra nada: lo registra ``bl`` (:data:`OPERATIONS`); las
pruebas, a mano. La geometría (validar la capa, el área sin sector, la búsqueda) y la lectura
de las capas la hace ``gis.masks`` (``sectors``, ``sources``), que llama a estas funciones.
Python puro (``core``).
"""

from __future__ import annotations

import math
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
from ..provenance.operations import OperationProject, Use, begin_operation
from .messages import ConstraintError, render
from .model import (
    Constraint,
    ConstraintParam,
    ConstraintType,
    GeometryKind,
    SearchHit,
    SearchRecord,
    Sector,
    constraint_code,
)
from .params import SEARCH_DISTANCE, family, param_key
from .store import (
    HIT_TABLE,
    SEARCH_TABLE,
    SECTOR_TABLE,
    append_search,
    create_tables,
    dataset_specs,
    layer_of,
    replace_sectors,
    taken_codes,
    write_constraints,
)

__all__ = [
    "DECLARE_SECTORS",
    "EDIT_COMMAND",
    "EDIT_CONSTRAINTS",
    "FIND_COMMAND",
    "FIND_UNTOUCHABLES",
    "MAX_LAYERS",
    "MODULE",
    "OPERATIONS",
    "OP_VERSION",
    "SECTOR_ROLE",
    "SOURCE_ROLE",
    "EditedConstraints",
    "LayerMapping",
    "ParamDeclaration",
    "Rejected",
    "SourceEntity",
    "close_search",
    "constraints_from_entities",
    "create_constraints",
    "declare_sectors",
    "default_type_values",
    "edit_constraints",
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
SOURCE_ROLE = "source"
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
)
"""Las operaciones de este módulo, de proyecto y sin repetición."""


def layer_role(position: int) -> str:
    """El papel de entrada de la capa consultada ``position`` (1…:data:`MAX_LAYERS`)."""
    if isinstance(position, bool) or not isinstance(position, int) or not (
            1 <= position <= MAX_LAYERS):
        raise ValueError(f"una búsqueda consulta las capas 1…{MAX_LAYERS}, no {position!r}")
    return f"layer_{position}"


def _outputs(created: Sequence[str], written: Sequence[str], srs: int) -> tuple[DatasetSpec, ...]:
    """Los datos que registra la operación: los que escribe y las tablas que acaba de crear
    (vacías, para que no queden sin registrar)."""
    chosen = set(created) | set(written)
    return tuple(spec for spec in dataset_specs(crs_epsg=srs) if spec.name in chosen)


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
            created = create_tables(conn, srs)
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
            created = create_tables(conn, srs)
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
    se anota en los ajustes; ``srs_id``, el CRS del proyecto.

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
    handle = begin_operation(project, EDIT_CONSTRAINTS, settings=noted,
                             inputs=() if source is None else (Use(source, SOURCE_ROLE),),
                             executor="blender")
    try:
        with project.write_transaction() as conn:
            created = create_tables(conn, srs)
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


def create_constraints(project: OperationProject, entities: Sequence[SourceEntity],
                       mapping: LayerMapping, *, layer: str, source: str | None,
                       source_input: str | None, params: ParamDeclaration | None,
                       srs_id: int) -> EditedConstraints:
    """Crea las restricciones de las entidades de la capa ``layer`` (RF-012-01) según
    ``mapping`` (con los campos ya como columnas) con :func:`edit_constraints`, anotando la
    correspondencia y las rechazadas. :class:`~.messages.ConstraintError`
    ``core.constraint_source_nothing`` (con la lista) si no sirve ninguna, sin registrar
    nada."""
    rows, rejected = constraints_from_entities(entities, mapping, layer=layer,
                                               source_input=source_input)
    if not rows:
        raise ConstraintError("core.constraint_source_nothing", field="capa",
                              value=len(rejected), layer=layer,
                              problems="; ".join(item.text() for item in rejected) or "—")
    return edit_constraints(project, rows, params=params, source=source,
                            settings={"mapping": mapping.settings()}, rejected=rejected,
                            srs_id=srs_id)

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

Las dos son de proyecto y no se repiten solas (una búsqueda es una decisión de una persona,
D-26). Importar este módulo no registra nada: lo registra ``bl`` (:data:`OPERATIONS`); las
pruebas, a mano. La geometría (validar la capa, el área sin sector, la búsqueda) la hace
``gis.masks.sectors``, que llama a estas funciones. Python puro (``core``).
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Sequence
from dataclasses import replace

from ..datasets.model import DatasetSpec
from ..provenance.contract import OperationDef
from ..provenance.operations import OperationProject, Use, begin_operation
from .messages import ConstraintError
from .model import SearchHit, SearchRecord, Sector
from .params import SEARCH_DISTANCE
from .store import (
    HIT_TABLE,
    SEARCH_TABLE,
    SECTOR_TABLE,
    append_search,
    create_tables,
    dataset_specs,
    replace_sectors,
)

__all__ = [
    "DECLARE_SECTORS",
    "FIND_COMMAND",
    "FIND_UNTOUCHABLES",
    "MAX_LAYERS",
    "MODULE",
    "OPERATIONS",
    "OP_VERSION",
    "SECTOR_ROLE",
    "SOURCE_ROLE",
    "close_search",
    "declare_sectors",
    "layer_role",
]

MODULE = "core"
OP_VERSION = "1.0"
DECLARE_SECTORS = "core.declare_sectors"
FIND_UNTOUCHABLES = "core.find_untouchables"
FIND_COMMAND = "geoblender.core_find_untouchables"
"""La orden que declara los sectores y busca (plan §5.5)."""
SOURCE_ROLE = "source"
SECTOR_ROLE = "sector"
MAX_LAYERS = 10
"""Las capas que consulta una búsqueda, como mucho (plan §5.2.3)."""

OPERATIONS: tuple[OperationDef, ...] = (
    OperationDef(DECLARE_SECTORS, OP_VERSION, MODULE, "Declaration of the search sectors",
                 False, commands=(FIND_COMMAND,)),
    OperationDef(FIND_UNTOUCHABLES, OP_VERSION, MODULE, "Search of untouchable elements",
                 False, commands=(FIND_COMMAND,)),
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

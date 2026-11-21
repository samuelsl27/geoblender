# SPDX-License-Identifier: GPL-3.0-or-later
"""La verificación por recinto en el proyecto (spec 012, T17; RF-012-21, RF-012-23, RF-012-24,
RF-012-28; plan 012 §5.2.3, A11, D-15, D-28, D-40, D-42, D-43).

- **Declaraciones** (como ``reserves.provenance``; importar no registra nada, lo registra
  ``bl``): la operación de versión :data:`VERIFY` (``res.verify_constraints``, se repite sola y se
  reproduce con 10⁻⁹ relativo), su parámetro del proyecto :data:`MIN_THICKNESS` (el espesor
  mínimo de verificación, 0,02 m ADOPTADO «sin confirmar», D-6; en :data:`DEFINITIONS`), sus
  cifras (:data:`FIGURES`, con el ámbito ``{"check": nombre, "final": k, "zone": código}``) y sus
  datos de la versión (:func:`dataset_spec`): la tabla en formato largo ``res_chk_<nombre>``
  (:data:`TABLE`: zona, final, cantidad, valor, unidad, nota), la capa de grupos
  ``res_chkg_<nombre>`` (:data:`GROUPS`, un punto por grupo que incumple) y, solo de cada final
  que incumple, la rejilla de incumplimientos ``res_chkv_<nombre>_<k>`` (:data:`VIOLATIONS`,
  ``final − partida`` en las celdas que incumplen y NaN en las demás, D-42).
- :func:`verify_steps`: el cálculo por pasos de una :class:`~.compliance.ComplianceRequest` con
  sus superficies (``reserves.surfaces``, **en la rejilla de las máscaras**: si no, el rechazo de
  RF-011-03 al llamar), por bandas de filas al paso, con las rejillas de incumplimientos en sus
  temporales con su hash. Sin el proyecto: lo usan la orden y la reproducción. **A escala (T36;
  RNF-012-02, RNF-012-03, RNF-012-06)** cada unidad es corta (leer una superficie de una banda,
  sumar una final en una banda, unas decenas de grupos, una tesela de una rejilla: ≤ 20 ms) y
  :func:`_paced` las agrupa en pasos de ≈ ``budget_s``; lo que comparten las finales se hace una
  vez (``compliance.zone_index_steps``) y la rejilla de incumplimientos de cada una se va
  rellenando por bandas (no se guardan las celdas de cada recinto).
- En el proyecto: :func:`verify_project_steps` (lo que lanza la orden): comprueba las superficies
  y la versión al llamar, encadena una ``gis.compile_constraints`` propia si las máscaras no
  están al día (D-15, D-43: ``gis.masks.access.ensure_masks_steps``), empieza la operación
  (:func:`begin_verify`: las máscaras y las superficies como entradas, el espesor mínimo anotado,
  la marca de RF-012-10 en sus ajustes) y da sus pasos (:func:`verify_run`), que guarda el
  resultado con :class:`CheckWriter` (A11): las rejillas en su temporal, los hashes de las tablas
  fuera de la transacción (por tramos de filas, T36), ``os.replace`` a ``rasters/`` y **una**
  transacción con las dos tablas, las cifras y ``complete`` (lo único que no se trocea, R4).
  Cerrar los pasos o un fallo: nada (RF-012-28).
- :func:`recompute_run` (T21; RF-008-26, D-19): repite una verificación obsoleta —la operación
  nueva sustituye a la anterior en la revisión abierta de su versión, con el nombre y las
  superficies de sus ajustes, las máscaras de hoy y el espesor mínimo resuelto de nuevo—; la
  llama «Recalcular lo obsoleto» desde ``bl`` y avanza sus pasos la cola de ``res``.
- :func:`reproduce_verify` (:data:`REPRODUCE`): con las máscaras, las superficies y el espesor
  congelados, sin el proyecto.
- :func:`zone_check` (T27; RF-012-19): lo que dice la última verificación vigente de una versión
  de una restricción (su veredicto y sus cifras por final), para la barra N «Restricción».
- :func:`read_verification` (T28; RF-012-23): una verificación vigente de una versión tal como la
  guardó (su tabla, sus grupos y sus rejillas de incumplimientos), para la ventana de la
  verificación; :func:`verify_inputs`, las superficies como entradas de la puerta de la 008, y
  :func:`stored_violations` con :func:`violation_sources`, lo que se lee para ver una rejilla de
  incumplimientos en la vista.
- :func:`freeze_findings` (T18; RF-012-25; D-7, D-29): la comprobación de ``res`` al congelar,
  que ``bl`` registra con ``core.versions.freeze.register_freeze_check``: las verificaciones de
  la versión obsoletas, con recintos que no cumplen (m³ por recinto) o con la marca de
  RF-012-10, y las superficies de diseño sin verificación al día (las que fueron final de una
  verificación sustituida, las del papel ``design_surface`` de ``design.provenance``, T18 de
  la 013, y la última de cada cadena de entidades de la 015, T32: RF-015-04; las superficies
  intermedias de una cadena, ``entity_surface``, son de trabajo y se verifican a petición).
- **La base de los acopios (spec 016, T30; RF-012-24, RF-012-30, RF-012-31; plan 016 A12, P-10)**:
  :func:`select_bases` elige, de la partida, las detecciones de acopios **al día hechas sobre ella**
  (``design.stockpile_store.detections_on``) —una base por detección y material— y avisa de las que no
  usa y por qué (obsoleta u hecha sobre otra superficie: ``detections_excluded``); cada base es una
  **entrada** de la operación (el papel :func:`base_role`, ``stockpile_base_<k>``), va en sus ajustes y
  en la tabla (``stockpile_base`` y ``stockpile_skipped``, del final 0) y, por zona que cuenta el
  corte de terreno, también el corte de acopios (``stockpile_cut_m3`` y su cifra CALCULADO). Una base
  en otra rejilla, CRS o datum se rechaza como RF-011-03 (:func:`check_sources`). Si hay varias, rige
  la menor (``compliance.lowest_base``). Sin detecciones, lo de siempre.
- **La accesibilidad de las pistas (spec 017, T18; RF-012-21, RF-012-22, RF-012-24; plan 017 A12, P-9, DIFF-012)**:
  :func:`select_access` elige, de cada final, las accesibilidades **al día hechas sobre ella**
  (``design.access_store.accessibilities_on``, por su papel, sin importar ``design.entities`` ni ``design.road_*``) y avisa de
  las que no usa y por qué (obsoleta, o hecha sobre otra superficie: ``accessibilities_excluded``); la zona «requiere acceso»
  es «cumple» si la accesibilidad de **esa final** la comunica, «no cumple» si no y «sin comprobar» si esa final no tiene
  accesibilidad al día (``compliance.verdict``). La tabla de zonas de cada accesibilidad es una **entrada** de la operación (el
  papel :func:`access_role`, ``road_access_<k>``: cambiarla —una pista, una berma o una entrada— deja obsoleta la verificación,
  que se congela con su revisión y se reproduce leyendo la tabla congelada), va en sus ajustes y en la tabla (``access_used`` y
  ``access_skipped``) y el resumen da las tres respuestas. Con varias accesibilidades al día sobre la misma final, una zona está
  comunicada si **alguna** la comunica. Sin accesibilidad, lo de siempre.

Python puro (nivel 9).
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
import time
from collections.abc import Generator, Iterator, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType, TracebackType
from typing import Any

import numpy as np

from ..core.content import builtin as core_builtin
from ..core.content.builtin import GPKG_LAYER
from ..core.content.encoder import NORMALIZER, ContentDigest
from ..core.datasets import registry as dataset_registry
from ..core.datasets.model import (
    DATASET_DECLARATIONS,
    LIVE_STATUSES,
    DatasetRecord,
    DatasetSpec,
    Store,
)
from ..core.errors import GeoblenderError
from ..core.georef import CrsRef, VerticalRef
from ..core.gpkg.base import ColumnDef, create_attribute_table, create_base, create_feature_table
from ..core.gpkg.connection import GpkgConnection
from ..core.gpkg.wkb import decode_geometry, encode_geometry
from ..core.i18n import THIN_SPACE
from ..core.paths import check_path_length
from ..core.project.model import Progress
from ..core.provenance.figures import RECORD_COLUMNS as FIGURE_COLUMNS
from ..core.provenance.figures import FigureRecord, FigureSpec, scope_key
from ..core.provenance.operations import (
    CANCEL_REASON_PREFIX,
    CANCELLATIONS,
    NOT_COMPLETED_REASON,
    OperationHandle,
    OperationStatus,
    Use,
    begin_operation,
    cancel_reason,
    failure_reason,
)
from ..core.provenance.recompute import RecomputeRequest
from ..core.units import convert
from ..core.versions import read as versions_read
from ..core.versions import store as versions_store
from ..core.versions.freeze import FreezeFinding
from ..core.versions.model import ItemKind, VersionError, version_locator
from ..core.versions.reproduce import ReproducedOutput, ReproducedResult, ReproduceRequest
from ..design import access_store, stockpile_store
from ..design.entities import chain_tail_surfaces
from ..design.provenance import (
    DESIGN_SURFACE_ROLE,
    ENTITY_SURFACE_ROLE,
    ROAD_ACCESS_ROLE,
    STOCKPILE_BASE_ROLE,
)
from ..gis.content import GEOTIFF
from ..gis.geotiff.reader import read_geotiff
from ..gis.geotiff.writer import target_locked, write_failed
from ..gis.grid import Grid, project_grid
from ..gis.masks.access import MaskSet, MaskState, ensure_masks_steps, load_masks
from ..gis.masks.compile import ClassesGrid
from ..gis.masks.compile import _classes_steps as _raster_steps
from ..gis.masks.compile import pace_units
from ..gis.masks.store import current_pending, read_report, read_zone_runs
from ..gis.messages import GisError
from ..gis.provenance import dataset_slug
from ..gis.raster import Raster
from ..gis.store import StoreProject, backup_path, insert_rows, project_references, temporary_path
from .compliance import (
    INNER_SUFFIX,
    MAX_FINALS,
    OUTSIDE_LEGAL,
    OUTSIDE_PERIMETER,
    Checker,
    ComplianceRequest,
    Counts,
    FinalCheck,
    Verdict,
    check_zones_steps,
    lowest_base,
    zone_index_steps,
)
from .messages import render
from .provenance import (
    FIGURE_TOLERANCE,
    MODULE,
    VERIFY,
    VERIFY_COMMAND,
    VERIFY_DEFINITIONS,
    VERIFY_FIGURES,
    VERIFY_MIN_THICKNESS,
    VERIFY_MIN_THICKNESS_DEF,
    VERIFY_PHASE,
    verify_operation_def,
)
from .surfaces import (
    BAND_ROWS,
    SurfaceHeader,
    SurfaceRef,
    SurfaceSource,
    band_reader,
    check_pair,
    constant_source,
    grid_source,
    surface_source,
)

__all__ = [
    "CANCELLED_REASON",
    "COMMAND",
    "DEFINITIONS",
    "FIGURES",
    "FIGURE_TOLERANCE",
    "GROUPS",
    "MIN_THICKNESS",
    "MIN_THICKNESS_DEF",
    "MODULE",
    "PHASE",
    "REPRODUCE",
    "START_ROLE",
    "STEP_BUDGET_S",
    "TABLE",
    "VERIFY",
    "VIOLATIONS",
    "AccessSelection",
    "AccessUse",
    "BaseSelection",
    "CheckWriter",
    "SkippedAccess",
    "SkippedDetection",
    "StockpileBase",
    "StoredCheck",
    "StoredGroup",
    "StoredVerification",
    "StoredViolations",
    "StoredZone",
    "VerifyResult",
    "ZoneCheck",
    "ZoneFinal",
    "access_role",
    "base_role",
    "begin_verify",
    "check_sources",
    "dataset_locator",
    "dataset_name",
    "dataset_spec",
    "final_role",
    "freeze_findings",
    "operation_def",
    "planned_units",
    "previous_check",
    "project_sources",
    "read_communicated",
    "read_groups",
    "read_table",
    "read_verification",
    "recompute_run",
    "reproduce_verify",
    "select_access",
    "select_bases",
    "stored_violations",
    "verification_names",
    "verify_inputs",
    "verify_project_steps",
    "verify_run",
    "verify_settings",
    "verify_steps",
    "violation_sources",
    "zone_check",
]

# Las declaraciones de la verificación viven en ``reserves.provenance`` (spec 012, T38; RNF-001-03:
# habilitar la extensión las registra sin cargar este módulo) y se reexportan aquí con sus nombres.
COMMAND = VERIFY_COMMAND
STEP_BUDGET_S = 0.05
"""El presupuesto de un paso por defecto (s; RF-012-28)."""
CANCELLED_REASON = CANCEL_REASON_PREFIX + "la persona la paró antes de terminar (Esc)"

MIN_THICKNESS = VERIFY_MIN_THICKNESS
MIN_THICKNESS_DEF = VERIFY_MIN_THICKNESS_DEF
DEFINITIONS = VERIFY_DEFINITIONS

TABLE = "chk"
GROUPS = "chkg"
VIOLATIONS = "chkv"
START_ROLE = "start"
_MASKS_NAME = "las máscaras de las restricciones"
_OBJ = "Verificación por recinto"
_FIELD = "ubicación"
_WORK_FRACTION = 0.5
PHASE = VERIFY_PHASE
_PHASE = PHASE
_TEXT = "Verificando por recinto…"


def final_role(position: int) -> str:
    """El papel de la superficie final ``position`` (desde 1): ``final_1``…"""
    if isinstance(position, bool) or not isinstance(position, int) or not (
            1 <= position <= MAX_FINALS):
        raise ValueError(f"las finales se cuentan de 1 a {MAX_FINALS}, no {position!r}")
    return f"final_{position}"


def _violations_role(position: int) -> str:
    final_role(position)
    return f"violations_{position}"


# --- Datos de la versión -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Family:
    code: str
    kind: str
    store: Store
    reader: str
    role: str
    label: str


_FAMILIES: Mapping[str, _Family] = MappingProxyType({
    TABLE: _Family(TABLE, "table", Store.GPKG, GPKG_LAYER.id, "table", "Verificación por recinto"),
    GROUPS: _Family(GROUPS, "vector", Store.GPKG, GPKG_LAYER.id, "groups",
                    "Grupos que incumplen"),
    VIOLATIONS: _Family(VIOLATIONS, "raster", Store.RASTERS, GEOTIFF.id, "violations",
                        "Rejilla de incumplimientos"),
})


def _family(code: object) -> _Family:
    found = _FAMILIES.get(code) if isinstance(code, str) else None
    if found is None:
        raise ValueError(f"{code!r} no es una familia de la verificación: es una de "
                         f"{', '.join(_FAMILIES)}")
    return found


def dataset_name(family: str, name: str, final: int | None = None) -> str:
    """El nombre del dato de la familia ``family`` de la verificación ``name``:
    ``res_chk_<nombre>``, ``res_chkg_<nombre>`` o, del final ``final``,
    ``res_chkv_<nombre>_<k>``."""
    found = _family(family)
    base = f"{MODULE}_{found.code}_{dataset_slug(name)}"
    if (found.code == VIOLATIONS) != (final is not None):
        raise ValueError("solo la rejilla de incumplimientos es de un final (y siempre)")
    return base if final is None else f"{base}_{final_role(final).removeprefix('final_')}"


def dataset_locator(family: str, name: str, version_code: str, final: int | None = None) -> str:
    """La ubicación del dato en la versión ``version_code``: la tabla (``res_chk_<n>_v01``) o el
    GeoTIFF (``rasters/res_chkv_<n>_<k>_v01.tif``)."""
    found = _family(family)
    base = dataset_name(family, name, final)
    if found.store is Store.GPKG:
        return version_locator(base, version_code)
    return version_locator(f"{found.store}/{base}.tif", version_code)


def dataset_spec(family: str, name: str, version_code: str, *, final: int | None = None,
                 content: ContentDigest | None = None, crs_epsg: int | None = None
                 ) -> DatasetSpec:
    """La ``DatasetSpec`` del dato (no editable en QGIS; su papel: ``table``, ``groups`` o
    ``violations_<k>``)."""
    found = _family(family)
    role = found.role if final is None else _violations_role(final)
    return DatasetSpec(dataset_name(family, name, final), MODULE, found.kind, found.store,
                       dataset_locator(family, name, version_code, final), reader=found.reader,
                       role=role, content=content, crs_epsg=crs_epsg)


operation_def = verify_operation_def
"""El ``OperationDef`` de :data:`VERIFY` con las funciones de ``bl`` (``reserves.provenance``)."""
FIGURES = VERIFY_FIGURES
"""Las cifras de la verificación (plan §5.2.3; ``reserves.provenance``)."""

_TABLE_COLUMNS = (ColumnDef("zone", "TEXT", True), ColumnDef("final", "INTEGER", True),
                  ColumnDef("quantity", "TEXT", True), ColumnDef("value", "DOUBLE", False),
                  ColumnDef("unit_code", "TEXT", False), ColumnDef("note", "TEXT", False))
_GROUP_COLUMNS = (ColumnDef("final", "INTEGER", True), ColumnDef("zone", "TEXT", True),
                  ColumnDef("cells", "INTEGER", True), ColumnDef("area_m2", "DOUBLE", True),
                  ColumnDef("volume_m3", "DOUBLE", True), ColumnDef("max_m", "DOUBLE", True))


def _names(family: str) -> tuple[str, ...]:
    if family == TABLE:
        return tuple(column.name for column in _TABLE_COLUMNS)
    return ("geom", *(column.name for column in _GROUP_COLUMNS))


def _create(conn: sqlite3.Connection, family: str, table: str, srs_id: int,
            identifier: str, description: str = "") -> None:
    if family == TABLE:
        create_attribute_table(conn, table, _TABLE_COLUMNS, identifier, description)
    else:
        create_feature_table(conn, table, "POINT", srs_id, False, _GROUP_COLUMNS, identifier,
                             description)


_DIGEST_ROWS_PER_UNIT = 1000
"""Las filas que se insertan en cada unidad de :func:`_digest_steps` (un múltiplo de las 500 de
cada sentencia de ``insert_rows``)."""
_DIGEST_CHUNK_BYTES = 1 << 16
"""Lo que lee el hasher de una tabla entre dos unidades de :func:`_digest_steps` (una
dieciseisava parte del trozo por defecto: con él, un trozo de 32.768 filas del cierre del hash
tardaba unos 60 ms)."""
_GROUPS_PER_UNIT = 1500
"""Los grupos cuyo punto se codifica en cada unidad de :meth:`CheckWriter.prepare_steps`."""


def _digest_steps(family: str, rows: Sequence[tuple[Any, ...]], crs: CrsRef
                  ) -> Generator[None, None, ContentDigest]:
    """El hash (``core.gpkg_layer@1``) de la tabla ``family`` con ``rows``, en un GeoPackage en
    memoria con la misma estructura (R4: fuera de la transacción), por pasos: una unidad por
    cada trozo de filas que se inserta y por cada trozo que se lee y se hashea (T36)."""
    conn = sqlite3.connect(":memory:")
    try:
        create_base(conn, crs)
        _create(conn, family, "digest", crs.epsg, "digest")
        names = _names(family)
        for first in range(0, len(rows), _DIGEST_ROWS_PER_UNIT):
            insert_rows(conn, "digest", names, rows[first:first + _DIGEST_ROWS_PER_UNIT])
            yield None
        request = GPKG_LAYER.request(_family(family).kind, DATASET_DECLARATIONS,
                                     {"main": Path("digest")}, {"layer": "digest"},
                                     normalizer=NORMALIZER, chunk_bytes=_DIGEST_CHUNK_BYTES)
        steps = core_builtin.layer_steps(conn, request)
        try:
            for _done in steps:
                yield None
        finally:
            steps.close()
        return request.hasher.digest()
    finally:
        conn.close()


def _digest(family: str, rows: Sequence[tuple[Any, ...]], crs: CrsRef) -> ContentDigest:
    """:func:`_digest_steps` de una vez."""
    steps = _digest_steps(family, rows, crs)
    while True:
        try:
            next(steps)
        except StopIteration as stop:
            return stop.value  # type: ignore[no-any-return]


def read_table(conn: sqlite3.Connection, table: str
               ) -> list[tuple[str, int, str, float | None, str | None, str | None]]:
    """Las filas de una tabla ``res_chk_`` (zona, final, cantidad, valor, unidad, nota)."""
    return [(str(a), int(b), str(c), d, e, f) for a, b, c, d, e, f in conn.execute(
        f'SELECT zone, "final", quantity, value, unit_code, note FROM "{table}" ORDER BY fid')]


def read_groups(conn: sqlite3.Connection, table: str
                ) -> list[tuple[int, str, int, float, float, float, float, float]]:
    """Los puntos de una capa ``res_chkg_`` (final, zona, celdas, área, volumen, espesor máximo
    y el centro absoluto, x e y)."""
    found = []
    for blob, final, zone, cells, area, volume, top in conn.execute(
            f'SELECT geom, "final", zone, cells, area_m2, volume_m3, max_m FROM "{table}" '
            "ORDER BY fid"):
        x, y = np.asarray(decode_geometry(bytes(blob), external=True).coords,
                          dtype=np.float64).ravel()[:2]
        found.append((int(final), str(zone), int(cells), float(area), float(volume),
                      float(top), float(x), float(y)))
    return found


# --- La base de los acopios (spec 016, T30; RF-012-30, RF-012-31; plan 016 A12, P-10) ------------


def base_role(position: int) -> str:
    """El papel de la base de acopios número ``position`` (desde 1) entre las entradas de la verificación:
    ``stockpile_base_<k>`` (el papel con que la detección escribe su base, con el número)."""
    if isinstance(position, bool) or not isinstance(position, int) or position < 1:
        raise ValueError(f"las bases de los acopios se cuentan desde 1, no {position!r}")
    return f"{STOCKPILE_BASE_ROLE}_{position}"


@dataclass(frozen=True, slots=True)
class StockpileBase:
    """Una base de acopios que usa la verificación: la de los acopios de un ``material`` (``None``: «sin material») de la
    detección ``detection`` (``STK-001``) llamada ``name``, de ámbito ``scope`` (``project`` o ``version``), con su ``ref``
    (la rejilla de esa base: el uid de su dato, para que no se confunda con la de otra detección de igual nombre en otro
    ámbito; su ``label`` nombra la detección y el material, que es como se la nombra en un rechazo)."""

    detection: str
    name: str
    scope: str
    material: str | None
    ref: SurfaceRef

    def text(self, language: str = "es") -> str:
        """Cómo se nombra al usarla: «Base de acopios: detección STK-001 «Acopios» (mineral)»."""
        return render("res.verify_base_used", language=language, detection=self.detection, name=self.name,
                      material=stockpile_store.material_label(self.material))


@dataclass(frozen=True, slots=True)
class SkippedDetection:
    """Una detección de acopios que la verificación **no usa** (RF-012-31): su ``detection``, su ``name`` y su ``scope``, la
    ``reason`` (``other_surface``: se hizo sobre otra superficie que la de partida; ``stale``: está obsoleta), la ``surface``
    sobre la que está hecha y, si está obsoleta, su ``cause`` en español y su ``cause_en`` en inglés (lo que cambió; spec 016, T48,
    hallazgo D-5: se guardan las dos y el aviso escribe la del idioma de la interfaz; sin la inglesa —lo anotado antes—, la de siempre)."""

    detection: str
    name: str
    scope: str
    reason: str
    surface: str
    cause: str = ""
    cause_en: str = ""

    def text(self, start: str, language: str = "es") -> str:
        """El aviso, con la partida ``start`` de la verificación: nombra la detección y la causa (en ``language``); todo el corte cuenta."""
        if self.reason == stockpile_store.EXCLUDED_STALE:
            cause = self.cause_en if language == "en" and self.cause_en else self.cause
            return render("res.verify_base_stale", language=language, detection=self.detection, name=self.name,
                          cause=cause)
        return render("res.verify_base_other_surface", language=language, detection=self.detection, name=self.name,
                      surface=self.surface or "—", start=start)


@dataclass(frozen=True, slots=True)
class BaseSelection:
    """La base de los acopios de una verificación (D-a de la 012: **automática**): las bases que usa (``bases``, una por
    detección al día hecha sobre la partida y material, en el orden del registro) y las detecciones que no usa con su causa
    (``skipped``; RF-012-31). Vacía: sin acopios detectados, la verificación de siempre (RF-012-30)."""

    bases: tuple[StockpileBase, ...] = ()
    skipped: tuple[SkippedDetection, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "bases", tuple(self.bases))
        object.__setattr__(self, "skipped", tuple(self.skipped))
        if not all(isinstance(item, StockpileBase) for item in self.bases):
            raise ValueError("las bases de los acopios son StockpileBase")
        if not all(isinstance(item, SkippedDetection) for item in self.skipped):
            raise ValueError("lo que no se usa de los acopios son SkippedDetection")

    @property
    def refs(self) -> tuple[SurfaceRef, ...]:
        """Las rejillas de las bases, en su orden: ``ComplianceRequest.bases``."""
        return tuple(item.ref for item in self.bases)

    def settings(self) -> dict[str, Any]:
        """Lo que se anota en los ajustes de la operación (JSON sin rutas): ``bases`` y ``skipped``, y solo las que no están
        vacías (sin acopios, los ajustes de siempre)."""
        found: dict[str, Any] = {}
        if self.bases:
            found["bases"] = [{"dataset": item.ref.dataset, "label": item.ref.label, "detection": item.detection,
                               "name": item.name, "scope": item.scope, "material": item.material}
                              for item in self.bases]
        if self.skipped:
            found["skipped"] = [{"detection": item.detection, "name": item.name, "scope": item.scope,
                                 "reason": item.reason, "surface": item.surface, "cause": item.cause,
                                 "cause_en": item.cause_en}
                                for item in self.skipped]
        return found

    @classmethod
    def of_settings(cls, settings: Mapping[str, Any]) -> BaseSelection:
        """La selección que anotan los ajustes ``settings`` de una verificación (:meth:`settings`); sin ella, la vacía.
        ``ValueError`` si lo anotado no es lo que escribe :meth:`settings`."""
        bases: list[StockpileBase] = []
        skipped: list[SkippedDetection] = []
        try:
            for item in settings.get("bases") or ():
                material = item["material"]
                bases.append(StockpileBase(str(item["detection"]), str(item["name"]), str(item["scope"]),
                                           None if material is None else str(material),
                                           SurfaceRef(dataset=item["dataset"], label=str(item.get("label") or ""))))
            for item in settings.get("skipped") or ():
                skipped.append(SkippedDetection(str(item["detection"]), str(item["name"]), str(item["scope"]),
                                                str(item["reason"]), str(item["surface"]), str(item.get("cause") or ""),
                                                str(item.get("cause_en") or "")))
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError(f"los ajustes de la verificación anotan mal la base de los acopios: {error!r}") from None
        return cls(tuple(bases), tuple(skipped))


def _start_dataset(conn: sqlite3.Connection, start: SurfaceRef, version_uid: str) -> tuple[str | None, str]:
    """El nombre del dato de la partida ``start`` y el uid de la versión a la que pertenece (``''``: del proyecto), como lo
    resuelve ``reserves.surfaces.surface_source`` (el de la versión activa y, si no, el del proyecto); ``(None, '')`` si
    la partida no es un dato vivo (una cota constante o un dato congelado: ninguna detección se hizo sobre ella)."""
    if start.dataset is None:
        return None, ""
    record = dataset_registry.get(conn, start.dataset, version_uid=version_uid)
    if record is None and version_uid:
        record = dataset_registry.get(conn, start.dataset)
    if record is None or not record.live:
        return None, ""
    owner = (versions_read.dataset_versions(conn, [record.uid]).get(record.uid, "")
             if versions_read.has_versions(conn) else "")
    return record.name, owner


def select_bases(project: StoreProject, version: str | None, start: SurfaceRef, *,
                 conn: sqlite3.Connection | None = None) -> BaseSelection:
    """La base de los acopios de verificar, en la ``version`` (uid o código; ``None``: solo el proyecto), a partir de
    ``start`` (RF-012-30, RF-012-31; plan 016 A12, P-10): una base por detección de acopios **al día hecha sobre la partida**
    (``design.stockpile_store.detections_on``: las del proyecto y las de la versión; una versión solo si el dato de la
    partida es suyo) y por material, y, de las demás detecciones que ve la versión, las que **no usa** con su causa
    (obsoleta, u hecha sobre otra superficie: también todas si la partida es una cota constante o un dato congelado).
    Sin detecciones, la selección vacía. Solo lee; ``conn`` es una conexión de lectura de quien llama (con su
    instantánea). ``VersionError`` (``core.version_unknown``) si la versión no existe."""

    def read(reading: sqlite3.Connection) -> BaseSelection:
        found = None if version is None else versions_read.version(reading, str(version))
        if version is not None and found is None:
            raise VersionError("core.version_unknown", field="versión", value=version, version=version)
        surface, owner = _start_dataset(reading, start, "" if found is None else found.uid)
        skipped = [SkippedDetection(item.code, item.name, item.scope, item.reason, item.surface, item.cause, item.cause_en)
                   for item in stockpile_store.detections_excluded(project, version, surface, conn=reading)]
        bases: list[StockpileBase] = []
        for detection in (() if surface is None else
                          stockpile_store.detections_on(project, version, surface, conn=reading)):
            if (detection.version_uid or "") != owner:  # el mismo nombre, pero otro dato (el de otro ámbito)
                skipped.append(SkippedDetection(detection.code, detection.name, detection.scope,
                                                stockpile_store.EXCLUDED_OTHER_SURFACE, detection.surface))
                continue
            for material in detection.materials:
                shown = StockpileBase(detection.code, detection.name, detection.scope, material.material,
                                      SurfaceRef(dataset=material.base.uid))
                bases.append(replace(shown, ref=SurfaceRef(dataset=material.base.uid, label=shown.text())))
        return BaseSelection(tuple(bases), tuple(skipped))

    if conn is not None:
        return read(conn)
    with project.read() as reading:
        return read(reading)


# --- La accesibilidad de las pistas (spec 017, T18; RF-012-21, RF-012-22, RF-012-24; plan 017 A12, P-9) ----------


def access_role(position: int) -> str:
    """El papel de la accesibilidad número ``position`` (desde 1) entre las entradas de la verificación: ``road_access_<k>`` (el papel con que la accesibilidad
    escribe lo alcanzable, con el número; lo que se consume de ella es su tabla de zonas «requiere acceso»)."""
    if isinstance(position, bool) or not isinstance(position, int) or position < 1:
        raise ValueError(f"las accesibilidades se cuentan desde 1, no {position!r}")
    return f"{ROAD_ACCESS_ROLE}_{position}"


@dataclass(frozen=True, slots=True)
class AccessUse:
    """Una accesibilidad que usa la verificación, para la final número ``final`` (desde 1, ``shown`` es su nombre): la de código ``code`` (``ACC-001``) llamada ``name``, hecha
    sobre la superficie ``surface`` (el nombre de su dato) y ``dataset``, el uid de su **tabla de zonas** «requiere acceso» (lo que consume la verificación como entrada)."""

    final: int
    code: str
    name: str
    surface: str
    dataset: str
    shown: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.final, bool) or not isinstance(self.final, int) or self.final < 1:
            raise ValueError(f"las finales se cuentan desde 1, no {self.final!r}")
        if not all(isinstance(item, str) for item in (self.code, self.name, self.surface, self.dataset, self.shown)):
            raise ValueError("una accesibilidad usada se describe con textos")

    def text(self, language: str = "es") -> str:
        """Cómo se nombra al usarla: «Accesibilidad de «Pozo 1»: ACC-001 «Accesibilidad de la cantera»»."""
        return render("res.verify_access_used", language=language, final=self.shown, code=self.code, name=self.name)


@dataclass(frozen=True, slots=True)
class SkippedAccess:
    """Una accesibilidad que la verificación **no usa**: su ``code``, su ``name``, la ``reason`` (``other_surface``: se hizo sobre otra superficie que la de cualquier final;
    ``stale``: se hizo sobre la de la final ``final`` y está obsoleta), la ``surface`` sobre la que está hecha y, si está obsoleta, su ``cause`` en español y su ``cause_en`` en inglés (lo
    que cambió; se guardan las dos y el aviso escribe la del idioma de la interfaz; sin la inglesa, la de siempre) y el nombre de esa final (``shown``)."""

    code: str
    name: str
    reason: str
    surface: str
    final: int = 0
    shown: str = ""
    cause: str = ""
    cause_en: str = ""

    def __post_init__(self) -> None:
        if self.reason not in (access_store.EXCLUDED_STALE, access_store.EXCLUDED_OTHER_SURFACE):
            raise ValueError(f"una accesibilidad no se usa por «{access_store.EXCLUDED_STALE}» o «{access_store.EXCLUDED_OTHER_SURFACE}», no por {self.reason!r}")
        if isinstance(self.final, bool) or not isinstance(self.final, int) or self.final < 0:
            raise ValueError(f"las finales se cuentan desde 1 (0: ninguna), no {self.final!r}")

    def text(self, language: str = "es") -> str:
        """El aviso: nombra la accesibilidad y la causa (en ``language``); las zonas «requiere acceso» de la final quedan sin comprobar."""
        if self.reason == access_store.EXCLUDED_STALE:
            cause = self.cause_en if language == "en" and self.cause_en else self.cause
            return render("res.verify_access_stale", language=language, code=self.code, name=self.name, final=self.shown, cause=cause)
        return render("res.verify_access_other_surface", language=language, code=self.code, name=self.name, surface=self.surface or "—")


@dataclass(frozen=True, slots=True)
class AccessSelection:
    """La accesibilidad de una verificación (P-9: **la de cada final**, automática): las accesibilidades que usa (``uses``, una o más por final, por orden de final y de código) y las que no
    con su causa (``skipped``). Vacía: sin accesibilidades al día, la verificación de siempre y las zonas «requiere acceso» sin comprobar."""

    uses: tuple[AccessUse, ...] = ()
    skipped: tuple[SkippedAccess, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "uses", tuple(self.uses))
        object.__setattr__(self, "skipped", tuple(self.skipped))
        if not all(isinstance(item, AccessUse) for item in self.uses):
            raise ValueError("las accesibilidades usadas son AccessUse")
        if not all(isinstance(item, SkippedAccess) for item in self.skipped):
            raise ValueError("las accesibilidades que no se usan son SkippedAccess")

    @property
    def datasets(self) -> tuple[str, ...]:
        """Las tablas de zonas que consume la verificación, en el orden de ``uses`` (la de la posición ``k``, con el papel :func:`access_role` ``k + 1``)."""
        return tuple(item.dataset for item in self.uses)

    def uses_of(self, final: int) -> tuple[AccessUse, ...]:
        """Las accesibilidades que usa la final número ``final`` (desde 1)."""
        return tuple(item for item in self.uses if item.final == final)

    def communicated_by_final(self, zone_sets: Sequence[frozenset[str]], finals: int) -> tuple[frozenset[str] | None, ...]:
        """De cada una de las ``finals`` finales, las zonas «requiere acceso» que comunica su accesibilidad (``ComplianceRequest.communicated``): la **unión** de las de
        ``zone_sets`` (los códigos comunicados de cada accesibilidad de :attr:`uses`, en su orden) de las que usa, y ``None`` si no usa ninguna. ``ValueError`` si no hay un conjunto
        por accesibilidad o una es de una final que no existe."""
        if len(zone_sets) != len(self.uses):
            raise ValueError(f"un conjunto de zonas comunicadas por accesibilidad ({len(self.uses)}), no {len(zone_sets)}")
        found: list[frozenset[str] | None] = [None] * finals
        for item, codes in zip(self.uses, zone_sets, strict=True):
            if not 1 <= item.final <= finals:
                raise ValueError(f"la accesibilidad {item.code} es de la final {item.final} y la verificación tiene {finals}")
            found[item.final - 1] = frozenset(codes) | (found[item.final - 1] or frozenset())
        return tuple(found)

    def settings(self) -> dict[str, Any]:
        """Lo que se anota en los ajustes de la operación (JSON sin rutas): ``access`` y ``access_skipped``, y solo los que no están vacíos (sin accesibilidades, los ajustes de
        siempre)."""
        found: dict[str, Any] = {}
        if self.uses:
            found["access"] = [{"dataset": item.dataset, "final": item.final, "code": item.code, "name": item.name, "surface": item.surface, "shown": item.shown}
                               for item in self.uses]
        if self.skipped:
            found["access_skipped"] = [{"code": item.code, "name": item.name, "reason": item.reason, "surface": item.surface, "final": item.final, "shown": item.shown,
                                        "cause": item.cause, "cause_en": item.cause_en} for item in self.skipped]
        return found

    @classmethod
    def of_settings(cls, settings: Mapping[str, Any]) -> AccessSelection:
        """La selección que anotan los ajustes ``settings`` de una verificación (:meth:`settings`); sin ella, la vacía. ``ValueError`` si lo anotado no es lo que escribe :meth:`settings`."""
        uses: list[AccessUse] = []
        skipped: list[SkippedAccess] = []
        try:
            for item in settings.get("access") or ():
                uses.append(AccessUse(int(item["final"]), str(item["code"]), str(item["name"]), str(item["surface"]), str(item["dataset"]), str(item.get("shown") or "")))
            for item in settings.get("access_skipped") or ():
                skipped.append(SkippedAccess(str(item["code"]), str(item["name"]), str(item["reason"]), str(item["surface"]), int(item.get("final") or 0), str(item.get("shown") or ""),
                                             str(item.get("cause") or ""), str(item.get("cause_en") or "")))
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError(f"los ajustes de la verificación anotan mal la accesibilidad: {error!r}") from None
        return cls(tuple(uses), tuple(skipped))


def select_access(project: StoreProject, version: str | None, finals: Sequence[SurfaceRef], *, conn: sqlite3.Connection | None = None) -> AccessSelection:
    """La accesibilidad de verificar ``finals``, en la ``version`` (uid o código; ``None``: sin versión no hay accesibilidad, que es de versión) (RF-012-22, DIFF-017; plan 017 A12,
    P-9): de **cada final**, las accesibilidades **al día hechas sobre ella** (``design.access_store.accessibilities_on``, por el nombre de su dato) y, de las demás que ve la versión, las que
    **no usa** con su causa: las obsoletas hechas sobre una final (``stale``, con lo que cambió) y las hechas sobre otra superficie que la de cualquier final (``other_surface``; también todas
    si ninguna final es un dato vivo: una cota constante o un dato congelado). Sin accesibilidades, la selección vacía. Solo lee; ``conn`` es una conexión de lectura de quien llama (con su
    instantánea). ``VersionError`` (``core.version_unknown``) si la versión no existe."""

    def read(reading: sqlite3.Connection) -> AccessSelection:
        found = None if version is None else versions_read.version(reading, str(version))
        if version is not None and found is None:
            raise VersionError("core.version_unknown", field="versión", value=version, version=version)
        if found is None:
            return AccessSelection()
        uses: list[AccessUse] = []
        skipped: list[SkippedAccess] = []
        matched: set[str] = set()
        elsewhere: dict[str, access_store.ExcludedAccessibility] = {}
        for position, final in enumerate(finals, start=1):
            surface, _owner = _start_dataset(reading, final, found.uid)
            for item in () if surface is None else access_store.accessibilities_on(project, found.uid, surface, conn=reading):
                uses.append(AccessUse(position, item.code, item.name, str(surface), item.zones.uid, final.shown))
                matched.add(item.code)
            for excluded in access_store.accessibilities_excluded(project, found.uid, surface, conn=reading):
                if excluded.reason == access_store.EXCLUDED_STALE:
                    skipped.append(SkippedAccess(excluded.code, excluded.name, excluded.reason, excluded.surface, position, final.shown, excluded.cause, excluded.cause_en))
                    matched.add(excluded.code)
                else:
                    elsewhere.setdefault(excluded.code, excluded)
        skipped += [SkippedAccess(item.code, item.name, item.reason, item.surface) for code, item in elsewhere.items() if code not in matched]
        return AccessSelection(tuple(uses), tuple(skipped))

    if conn is not None:
        return read(conn)
    with project.read() as reading:
        return read(reading)


def read_communicated(project: StoreProject, selection: AccessSelection, finals: int, *, conn: sqlite3.Connection | None = None) -> tuple[frozenset[str] | None, ...]:
    """De cada una de las ``finals`` finales, las zonas «requiere acceso» que comunica su accesibilidad (:meth:`AccessSelection.communicated_by_final`), leídas de la tabla de zonas de cada una de
    ``selection`` (``design.access_store.read_zone_table``: los códigos con ``connected``); ``None`` si no usa ninguna. Solo lee; ``conn`` es una conexión de lectura de quien llama (con su
    instantánea). ``ValueError`` si la tabla de una accesibilidad ya no está viva en el proyecto."""

    def read(reading: sqlite3.Connection) -> tuple[frozenset[str] | None, ...]:
        sets: list[frozenset[str]] = []
        for item in selection.uses:
            record = dataset_registry.get(reading, item.dataset)
            if record is None or not record.live:
                raise ValueError(f"la tabla de zonas de la accesibilidad {item.code} («{item.name}») ya no está en el proyecto")
            sets.append(frozenset(row.code for row in access_store.read_access_zones(project, record.locator, conn=reading) if row.connected))
        return selection.communicated_by_final(sets, finals)

    if conn is not None:
        return read(conn)
    with project.read() as reading:
        return read(reading)


# --- El cálculo por pasos ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class VerifyResult:
    """Lo verificado: el nombre, el de cada final, lo de cada final (``FinalCheck``, en su
    orden), las rejillas de incumplimientos escritas (final desde 1 → rejilla en su temporal),
    los sectores sin búsqueda vigente (la marca de RF-012-10, sus nombres) y las cifras. Con la
    base de los acopios (T30), la selección que se usó (``selection``) y el nombre de la partida
    (``start_name``) para nombrar lo que no se usó en la tabla; y, con la accesibilidad de las
    pistas (spec 017, T18), la selección de las que usó cada final y las que no (``access``)."""

    name: str
    final_names: tuple[str, ...]
    finals: tuple[FinalCheck, ...]
    grids: Mapping[int, ClassesGrid]
    pending_names: tuple[str, ...]
    figures: tuple[FigureSpec, ...]
    selection: BaseSelection = BaseSelection()
    start_name: str = ""
    access: AccessSelection = AccessSelection()

    @property
    def fails(self) -> tuple[bool, ...]:
        """Si cada final tiene algún recinto que no cumple."""
        return tuple(found.fails for found in self.finals)

    def table_rows(self) -> list[tuple[str, int, str, float | None, str | None, str | None]]:
        """Las filas de ``res_chk_`` (formato largo; el final 0, lo de toda la verificación)."""
        rows: list[tuple[str, int, str, float | None, str | None, str | None]] = [
            ("", 0, "pending_sector", None, None, name) for name in self.pending_names]
        rows += [("", 0, "stockpile_base", None, None, base.text("es")) for base in self.selection.bases]
        rows += [("", 0, "stockpile_skipped", None, None, item.text(self.start_name, "es"))
                 for item in self.selection.skipped]
        rows += [("", 0, "access_skipped", None, None, item.text("es"))  # hechas sobre otra superficie
                 for item in self.access.skipped if item.final == 0]
        for position, (shown, found) in enumerate(zip(self.final_names, self.finals,
                                                      strict=True), start=1):
            rows.append(("", position, "surface", None, None, shown))
            rows += [("", position, "access_used", None, None, item.text("es"))  # spec 017, T18
                     for item in self.access.uses_of(position)]
            rows += [("", position, "access_skipped", None, None, item.text("es"))
                     for item in self.access.skipped if item.final == position]
            for item in found.totals:
                code = item.code
                rows += [(code, position, "cut_m3", item.cut_m3, "m3", None),
                         (code, position, "fill_m3", item.fill_m3, "m3", None),
                         (code, position, "moved_area_m2", item.moved_m2, "m2", None),
                         (code, position, "nodata_area_m2", item.nodata_m2, "m2", None),
                         (code, position, "counted_m3", item.counted_m3, "m3",
                          item.counts.value)]
                if item.counts is Counts.CUT_TERRAIN:  # con la base de los acopios (RF-012-30)
                    rows.append((code, position, "stockpile_cut_m3", item.stockpile_cut_m3, "m3", None))
                if item.weighted_m3 is not None:
                    rows += [(code, position, "weight", item.weight, "-", None),
                             (code, position, "weighted_m3", item.weighted_m3, "m3", None)]
                rows.append((code, position, "verdict", None, None, item.verdict.value))
            rows += [("", position, "notice", None, None, notice.text("es"))
                     for notice in found.notices]
        return rows

    def group_rows(self) -> list[tuple[int, str, int, float, float, float, float, float]]:
        """Un punto por grupo que incumple: (final, zona, celdas, área, volumen, espesor
        máximo, x, y absolutos)."""
        return [(position, group.zone, group.cells, group.area_m2, group.volume_m3, group.max_m,
                 group.center[0], group.center[1])
                for position, found in enumerate(self.finals, start=1) for group in found.groups]


def _figures(name: str, finals: Sequence[FinalCheck]) -> tuple[FigureSpec, ...]:
    found: list[FigureSpec] = []
    for position, check in enumerate(finals, start=1):
        for item in check.totals:
            scope = {"check": name, "final": position, "zone": item.code}
            found += [FigureSpec("res.check_cut_m3", item.cut_m3, "m3", scope=scope),
                      FigureSpec("res.check_fill_m3", item.fill_m3, "m3", scope=scope),
                      FigureSpec("res.check_moved_area_m2", item.moved_m2, "m2", scope=scope),
                      FigureSpec("res.check_nodata_area_m2", item.nodata_m2, "m2", scope=scope)]
            if item.counts is Counts.CUT_TERRAIN:  # el corte de acopios, solo con la base (RF-012-30)
                found.append(FigureSpec("res.check_stockpile_cut_m3", item.stockpile_cut_m3, "m3", scope=scope))
            if item.weighted_m3 is not None:
                found.append(FigureSpec("res.check_avoid_weighted_m3", item.weighted_m3, "m3",
                                        scope=scope))
    for spec in found:  # RF-012-24: ninguna NaN ni infinita
        if spec.value is None or not math.isfinite(spec.value):
            raise ValueError(f"la cifra «{spec.key}» ({dict(spec.scope)}) no es finita")
    return tuple(found)


def check_sources(sources: Mapping[str, SurfaceSource], masks: MaskSet,
                  references: tuple[CrsRef, VerticalRef]) -> None:
    """RF-011-03: cada superficie en la rejilla de las máscaras, con el CRS y el datum del
    proyecto (``reserves.surfaces.check_pair``; ``res.surfaces_mismatch``)."""
    header = SurfaceHeader(_MASKS_NAME, masks.grid, *references)
    for source in sources.values():
        check_pair(header, source)


def verify_steps(request: ComplianceRequest, sources: Mapping[str, SurfaceSource], *,
                 references: tuple[CrsRef, VerticalRef], budget_s: float = STEP_BUDGET_S,
                 grid_paths: Mapping[int, tuple[Path, Path | None]] | None = None,
                 band_rows: int = BAND_ROWS, selection: BaseSelection | None = None,
                 access: AccessSelection | None = None) -> Iterator[Progress]:
    """Los pasos de verificar ``request`` (véase el módulo) con ``sources`` (papel →
    ``SurfaceSource``: :data:`START_ROLE`, :func:`final_role` de cada final y :func:`base_role` de
    cada base de ``request.bases``), de ``budget_s`` como mucho. Con ``grid_paths`` (final desde 1
    → destino y temporal), la rejilla de incumplimientos de cada final que incumple queda escrita
    en su temporal con el CRS y el datum de ``references``. ``selection`` (T30), la selección de la
    que salen ``request.bases``, para nombrarla en la tabla; si se da con bases, sus rejillas son
    las de la petición. ``access`` (spec 017, T18), la selección de las accesibilidades de las que
    salen ``request.communicated`` (las zonas comunicadas de cada final), para nombrarla en la
    tabla; cada una de sus accesibilidades es de una final que tiene su conjunto en la petición.
    El último ``Progress`` lleva el :class:`VerifyResult`. Al llamar:
    ``TypeError``/``ValueError`` si la petición no casa, y el rechazo de RF-011-03 (también el de
    una base en otra rejilla, RF-012-31)."""
    if not isinstance(request, ComplianceRequest):
        raise TypeError(f"se verifica una ComplianceRequest, no {type(request).__name__}")
    if isinstance(budget_s, bool) or not isinstance(budget_s, int | float) or budget_s <= 0:
        raise ValueError(f"el presupuesto de un paso es un número positivo, no {budget_s!r}")
    selection = BaseSelection() if selection is None else selection
    if selection.bases and selection.refs != request.bases:
        raise ValueError("la selección de las bases de los acopios no es la de la petición")
    access = AccessSelection() if access is None else access
    for use in access.uses:
        if not 1 <= use.final <= len(request.finals) or request.communicated_of(use.final - 1) is None:
            raise ValueError(f"la accesibilidad {use.code} es de la final {use.final} y la petición no tiene las zonas comunicadas de esa final")
    roles = [START_ROLE, *(final_role(k) for k in range(1, len(request.finals) + 1)),
             *(base_role(k) for k in range(1, len(request.bases) + 1))]
    missing = [role for role in roles if role not in sources]
    if missing:
        raise ValueError(f"faltan las superficies {missing}")
    ordered = [sources[role] for role in roles]
    check_sources(dict(zip(roles, ordered, strict=True)), request.masks, references)
    work = _work(request, ordered, references, dict(grid_paths or {}), band_rows, selection, access)
    return _paced(work, float(budget_s),
                  planned_units(request.masks.grid, len(ordered), len(request.finals), band_rows,
                                with_base=bool(request.bases)))


def planned_units(grid: Grid, surfaces: int, finals: int, band_rows: int = BAND_ROWS, *,
                  with_base: bool = False) -> int:
    """Las unidades que se prevén al empezar a verificar ``finals`` finales de ``surfaces``
    superficies (las bases de los acopios, también) en ``grid`` (crece si hacen falta más; el
    total del primer aviso de avance): leer cada superficie y sumar cada final en cada banda; de
    cada final, los grupos (tres modos de contar por cada 64 filas, cuatro con la base de los
    acopios —el corte de terreno—, y unas 120 más entre vueltas y trozos de celdas) y las unidades
    de su rejilla de incumplimientos (hash y teselas); y lo que se prepara al guardar."""
    bands = -(-grid.nrows // band_rows)
    cells = grid.nrows * grid.ncols
    tiles = -(-grid.nrows // 256) * -(-grid.ncols // 256) + -(-cells // (1 << 18))
    groups = (4 if with_base else 3) * -(-grid.nrows // 64) + 120
    return bands * (surfaces + finals) + finals * (groups + tiles) + 180


def _work(request: ComplianceRequest, ordered: Sequence[SurfaceSource],
          references: tuple[CrsRef, VerticalRef],
          grid_paths: Mapping[int, tuple[Path, Path | None]], band_rows: int,
          selection: BaseSelection, access: AccessSelection) -> Generator[None, None, VerifyResult]:
    masks = request.masks
    grid = masks.grid
    zones = yield from check_zones_steps(masks.classes, masks.zones, masks.ctypes, masks.weights,
                                         with_base=bool(request.bases))
    index = yield from zone_index_steps(grid, zones)  # una vez, para todas las finales
    checkers = [Checker(grid, zones, request.min_thickness_m, index=index,
                        communicated=request.communicated_of(k))  # la accesibilidad de cada final
                for k in range(len(request.finals))]
    readers = [band_reader(source, grid, rows=band_rows) for source in ordered]
    first_base = 1 + len(request.finals)
    try:  # cerrar los pasos cierra los ficheros
        for top in range(0, grid.nrows, band_rows):
            values = []
            for reader in readers:  # cada superficie, y cada base, una unidad
                values.append(next(reader)[1])
                yield None
            base = lowest_base(values[first_base:])  # la menor de las bases (P-10); None sin ellas
            for position, checker in enumerate(checkers, start=1):
                checker.add(top, values[0], values[position], base)
                yield None
    finally:
        for reader in readers:
            reader.close()
    finals = []
    for checker in checkers:
        finals.append((yield from checker.result_steps(start_name=ordered[0].name)))
    written: dict[int, ClassesGrid] = {}
    try:
        for position, found in enumerate(finals, start=1):
            if found.violations is None or position not in grid_paths:
                continue
            path, temporary = grid_paths[position]
            written[position] = yield from _raster_steps(
                Raster(grid, found.violations, *references), Path(path), temporary)
        return VerifyResult(request.name, tuple(item.shown for item in request.finals),
                            tuple(finals), MappingProxyType(written), masks.pending_names,
                            _figures(request.name, finals), selection, ordered[0].name, access)
    except BaseException:
        for item in written.values():
            item.path.unlink(missing_ok=True)
        raise


def _paced(work: Generator[None, None, VerifyResult], budget_s: float,
           total: int) -> Iterator[Progress]:
    target = budget_s * _WORK_FRACTION
    done = 0
    with closing(work):  # cerrar los pasos (Esc) cierra el trabajo
        while True:
            start = last = time.perf_counter()
            slowest = 0.0
            try:
                while True:
                    next(work)
                    done += 1
                    now = time.perf_counter()
                    slowest = max(slowest, now - last)
                    last = now
                    if now - start + slowest > target:
                        break
            except StopIteration as stop:
                result: VerifyResult = stop.value
                break
            total = max(total, done + 1)
            yield Progress(_PHASE, done, total, _TEXT)
    yield Progress(_PHASE, total, total, _summary(result), result=result)


def _summary(result: VerifyResult) -> str:
    failing = [str(k) for k, fails in enumerate(result.fails, start=1) if fails]
    head = (f"«{result.name}»: no cumplen las finales {', '.join(failing)}" if failing
            else f"«{result.name}»: todas las finales cumplen")
    # Las tres respuestas de las zonas «requiere acceso» (spec 017, T18; RF-012-22): de cada final y zona.
    tally = dict.fromkeys((Verdict.COMPLIES, Verdict.FAILS, Verdict.UNCHECKED), 0)
    for found in result.finals:
        for item in found.totals:
            if item.counts is Counts.ACCESS:
                tally[item.verdict] += 1
    if not any(tally.values()):
        return head
    return (f"{head} · «requiere acceso»: cumplen {tally[Verdict.COMPLIES]}, "
            f"no cumplen {tally[Verdict.FAILS]}, sin comprobar {tally[Verdict.UNCHECKED]}")


# --- La petición en el proyecto ----------------------------------------------------------------


def _surface_use(ref: SurfaceRef, role: str, frozen: str | None) -> Use | None:
    if ref.dataset is not None:
        return Use(ref.dataset, role)
    if ref.frozen is not None:
        if frozen is None:
            raise ValueError(f"«{ref.shown}» está congelada: la versión no parte de una revisión")
        return Use(ref.frozen, role, frozen=frozen)
    return None


def _surface_setting(ref: SurfaceRef) -> dict[str, Any]:
    if ref.dataset is not None:
        return {"dataset": ref.dataset, "label": ref.label}
    if ref.frozen is not None:
        return {"frozen": ref.frozen, "label": ref.label}
    return {"elevation_m": ref.elevation, "label": ref.label}


def _surface_ref(value: object) -> SurfaceRef:
    if not isinstance(value, Mapping):
        raise ValueError(f"los ajustes de una superficie son un diccionario, no {value!r}")
    label = str(value.get("label") or "")
    for kind in ("dataset", "frozen", "elevation_m"):
        if value.get(kind) is not None:
            given = {"elevation_m": "elevation"}.get(kind, kind)
            return SurfaceRef(**{given: value[kind]}, label=label)
    raise ValueError(f"los ajustes de una superficie no dicen cuál es: {value!r}")


def verify_settings(name: str, start: SurfaceRef, finals: Sequence[SurfaceRef],
                    pending_sectors: Sequence[str] = (),
                    pending_names: Sequence[str] = (), bases: BaseSelection | None = None,
                    access: AccessSelection | None = None) -> dict[str, Any]:
    """Los ajustes de la verificación (JSON sin rutas): el nombre, la partida, las finales y los
    sectores sin búsqueda vigente al verificar, sus códigos y sus nombres (la marca de
    RF-012-10) y, con acopios detectados (T30), la base que usó y las detecciones que no
    (:meth:`BaseSelection.settings`) y, con accesibilidades de las pistas (spec 017, T18), las que
    usó cada final y las que no (:meth:`AccessSelection.settings`); sin ellos, los de siempre."""
    return {"name": name, "start": _surface_setting(start),
            "finals": [_surface_setting(ref) for ref in finals],
            "pending_sectors": list(pending_sectors), "pending_names": list(pending_names),
            **({} if bases is None else bases.settings()),
            **({} if access is None else access.settings())}


def _settings_request(settings: Mapping[str, Any]) -> tuple[str, SurfaceRef,
                                                            tuple[SurfaceRef, ...]]:
    name = settings.get("name")
    finals = settings.get("finals")
    if not isinstance(name, str) or not isinstance(finals, list):
        raise ValueError("los ajustes de la verificación llevan su nombre y sus finales")
    return name, _surface_ref(settings.get("start")), tuple(_surface_ref(item) for item in finals)


def _check_request(name: object, start: object, finals: Sequence[object]) -> None:
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"una verificación tiene nombre, no {name!r}")
    dataset_slug(name)
    if not all(isinstance(item, SurfaceRef) for item in (start, *finals)):
        raise ValueError("las superficies son SurfaceRef")
    if not 1 <= len(finals) <= MAX_FINALS or len(set(finals)) != len(finals):
        raise ValueError(f"de 1 a {MAX_FINALS} superficies finales distintas")


def project_sources(project: StoreProject, start: SurfaceRef, finals: Sequence[SurfaceRef], *,
                    version_uid: str, bases: Sequence[SurfaceRef] = ()) -> dict[str, SurfaceSource]:
    """Las superficies de la verificación en ``project`` con la versión ``version_uid`` (por
    papel: :data:`START_ROLE`, :func:`final_role` y, de cada base de los acopios de ``bases``,
    :func:`base_role`): ``reserves.surfaces.surface_source`` (un dato de otra versión, un TIN o
    uno que no está, sus rechazos)."""
    found = {START_ROLE: surface_source(project, start, version_uid=version_uid)}
    for position, ref in enumerate(finals, start=1):
        found[final_role(position)] = surface_source(project, ref, version_uid=version_uid)
    for position, ref in enumerate(bases, start=1):
        found[base_role(position)] = surface_source(project, ref, version_uid=version_uid)
    return found


def _with_bases(project: StoreProject, sources: Mapping[str, SurfaceSource],
                bases: Sequence[SurfaceRef], version_uid: str) -> dict[str, SurfaceSource]:
    """``sources`` con las bases de los acopios que le falten (las ya leídas se respetan)."""
    found = dict(sources)
    for position, ref in enumerate(bases, start=1):
        if base_role(position) not in found:
            found[base_role(position)] = surface_source(project, ref, version_uid=version_uid)
    return found


def previous_check(project: StoreProject, name: str, *, version: str) -> str | None:
    """La verificación hecha y sin sustituir con el nombre ``name`` en la versión ``version``
    (uid o código): a la que sustituye la nueva (``None`` si no hay ninguna)."""
    dataset = dataset_name(TABLE, name)
    with project.read() as conn:
        found = versions_read.version(conn, version)
        if found is None:
            raise VersionError("core.version_unknown", field="versión", value=version,
                               version=version)
        record = dataset_registry.get(conn, dataset, version_uid=found.uid)
        if record is None or record.name != dataset:
            return None
        row = conn.execute("SELECT op_type, status, superseded_by FROM gb_operation "
                           "WHERE uid = ?", (record.operation_uid,)).fetchone()
    if row is None or row[0] != VERIFY or row[1] != OperationStatus.DONE or row[2] is not None:
        return None
    return str(record.operation_uid)


def begin_verify(project: StoreProject, masks: MaskSet, *, name: str, start: SurfaceRef,
                 finals: Sequence[SurfaceRef], executor: str = "blender",
                 sources: Mapping[str, SurfaceSource] | None = None,
                 bases: BaseSelection | None = None,
                 access: AccessSelection | None = None) -> OperationHandle:
    """Empieza :data:`VERIFY` «en curso» en la versión de ``masks`` (al día): las máscaras
    (``MaskSet.uses``), las superficies y, si las hay, las bases de los acopios (:func:`base_role`)
    y las tablas de zonas de las accesibilidades de las pistas (:func:`access_role`) como
    entradas, el espesor mínimo del proyecto y los ajustes de :func:`verify_settings`;
    sustituye a la anterior con su nombre. Rechazos de la versión (RF-009-04) y de las
    superficies, también de una base (RF-011-03, RF-012-31) sin registrar nada. ``sources``: las
    superficies ya leídas de esas referencias (:func:`project_sources`), si las hay. ``bases``: la
    selección de las bases de los acopios (:func:`select_bases`, de la partida y la versión de
    ``masks``); sin ella, la que corresponde ahora (D-a, la automática), y
    ``BaseSelection()``, sin base. ``access``: la selección de las accesibilidades
    (:func:`select_access`, de cada final en la versión de ``masks``); sin ella, la de ahora (la
    automática), y ``AccessSelection()``, sin accesibilidad."""
    finals = tuple(finals)
    _check_request(name, start, finals)
    if not isinstance(masks, MaskSet) or masks.state is not MaskState.CURRENT:
        raise ValueError("se verifica con las máscaras al día (gis.masks.access)")
    with project.read() as conn:
        version = versions_store.require_editable(conn, masks.version_uid)
    selection = select_bases(project, version.uid, start) if bases is None else bases
    chosen = select_access(project, version.uid, finals) if access is None else access
    if sources is None:
        sources = project_sources(project, start, finals, version_uid=version.uid,
                                  bases=selection.refs)
    else:
        sources = _with_bases(project, sources, selection.refs, version.uid)
    check_sources(sources, masks, project_references(project))
    parent = version.parent_revision_uid
    inputs = list(masks.uses())
    for role, ref in ((START_ROLE, start),
                      *((final_role(k), ref) for k, ref in enumerate(finals, start=1)),
                      *((base_role(k), ref) for k, ref in enumerate(selection.refs, start=1))):
        use = _surface_use(ref, role, parent)
        if use is not None:
            inputs.append(use)
    inputs += [Use(dataset, access_role(k)) for k, dataset in enumerate(chosen.datasets, start=1)]
    return begin_operation(project, VERIFY,
                           settings=verify_settings(name, start, finals, masks.pending_sectors,
                                                    masks.pending_names, selection, chosen),
                           inputs=inputs, params=(MIN_THICKNESS,), executor=executor,
                           supersedes=previous_check(project, name, version=version.uid),
                           version=version.uid)


def verify_project_steps(project: StoreProject, *, version: str | None, name: str,
                         start: SurfaceRef, finals: Sequence[SurfaceRef],
                         budget_s: float = STEP_BUDGET_S, executor: str = "blender",
                         bases: BaseSelection | None = None,
                         access: AccessSelection | None = None) -> Iterator[Progress]:
    """Lo que lanza la orden «Verificar un diseño por recinto…» (véase el módulo). Al llamar,
    sin registrar nada: ``VersionError`` sin versión o en una no editable; los rechazos de las
    superficies, también el de una base de los acopios (RF-011-03, RF-012-31); los de compilar, si
    hay que hacerlo (D-43). ``bases``: la selección de las bases de los acopios
    (:func:`select_bases`); sin ella, la de ahora (D-a, la automática: las detecciones al día
    hechas sobre la partida) y ``BaseSelection()``, sin base. ``access``: la selección de las
    accesibilidades de las pistas (:func:`select_access`: las al día hechas sobre cada final);
    sin ella, la de ahora (la automática) y ``AccessSelection()``, sin accesibilidad. El último
    ``Progress`` lleva el :class:`StoredCheck`."""
    if version is None or not str(version).strip():
        raise VersionError("core.version_required", field="versión activa", value=version,
                           op_type=VERIFY)
    finals = tuple(finals)
    _check_request(name, start, finals)
    record = project.record
    if record is None:
        raise ValueError(f"el proyecto «{project.name}» se abrió solo con su cabecera")
    with project.read() as conn:
        found = versions_store.require_editable(conn, str(version))
    selection = select_bases(project, found.uid, start) if bases is None else bases
    chosen = select_access(project, found.uid, finals) if access is None else access
    sources = project_sources(project, start, finals, version_uid=found.uid, bases=selection.refs)
    grid = project_grid(record.window, float(record.grid_step_m))
    header = SurfaceHeader(_MASKS_NAME, grid, *project_references(project))
    for source in sources.values():
        check_pair(header, source)
    masks_steps = ensure_masks_steps(project, found.uid, budget_s=budget_s)
    return _project_steps(project, masks_steps, name, start, finals, sources, budget_s,
                          executor, selection, chosen)


def _project_steps(project: StoreProject, masks_steps: Iterator[Progress], name: str,
                   start: SurfaceRef, finals: tuple[SurfaceRef, ...],
                   sources: Mapping[str, SurfaceSource], budget_s: float,
                   executor: str, selection: BaseSelection,
                   access: AccessSelection) -> Iterator[Progress]:
    masks: MaskSet | None = None
    with closing(masks_steps):  # type: ignore[type-var]
        for step in masks_steps:
            if step.result is not None:
                masks = step.result
                break
            yield step
    assert isinstance(masks, MaskSet)
    handle = begin_verify(project, masks, name=name, start=start, finals=finals,
                          executor=executor, sources=sources, bases=selection, access=access)
    steps = verify_run(project, handle, budget_s=budget_s, masks=masks, sources=sources)
    with closing(steps):  # type: ignore[type-var]
        yield Progress(_PHASE, 0, 1, _TEXT)  # empezar la operación es un paso
        yield from steps


def recompute_run(request: RecomputeRequest, *, budget_s: float = STEP_BUDGET_S
                  ) -> tuple[OperationHandle, Iterator[Progress]]:
    """Repite :data:`VERIFY` de ``request`` (``RecomputeRequest`` de «Recalcular lo obsoleto»,
    RF-008-26; RF-012-16, RF-012-24; plan A12, D-19): empieza la verificación nueva, que
    sustituye a la anterior en la revisión abierta de **su** versión, con el nombre, la partida
    y las finales de sus ajustes (las superficies vigentes que designan), las máscaras de hoy
    de esa versión (:func:`~..gis.masks.access.load_masks`) y el espesor mínimo resuelto de
    nuevo, la base de los acopios de hoy (T30: las detecciones al día hechas sobre su partida,
    :func:`select_bases`: la repetición vuelve a elegirla, no copia la de antes) y la accesibilidad
    de hoy de cada final (spec 017, T18: :func:`select_access`, igual), y devuelve su
    ``OperationHandle`` «en curso» y sus pasos (:func:`verify_run`), que
    avanza quien la llama (en Blender, la cola de ``res``; la operación sigue «en curso» hasta
    el último). Las máscaras han de estar al día: si se recalculan también, «Recalcular lo
    obsoleto» las compila antes (son su entrada) y esta las lee ya nuevas.

    Al llamar, sin empezar nada: ``TypeError``/``ValueError`` si no es una petición de este tipo
    de operación o sus ajustes no llevan lo que pide; ``VersionError`` sin versión o en una no
    editable; ``MaskError`` si las máscaras no están al día; los rechazos de las superficies
    (RF-011-03)."""
    if not isinstance(request, RecomputeRequest):
        raise TypeError(f"se recalcula una RecomputeRequest, no {request!r}")
    if request.op_type != VERIFY:
        raise ValueError(f"recompute_run repite {VERIFY}, no «{request.op_type}»")
    if request.version is None or not str(request.version).strip():
        raise VersionError("core.version_required", field="versión activa",
                           value=request.version, op_type=VERIFY)
    project: StoreProject = request.project  # type: ignore[assignment]
    name, start, finals = _settings_request(request.settings)
    masks = load_masks(project, request.version)
    handle = begin_verify(project, masks, name=name, start=start, finals=finals)
    try:
        return handle, verify_run(project, handle, budget_s=budget_s, masks=masks)
    except BaseException as error:
        handle.fail(failure_reason(error))
        raise


# --- Escribir el resultado (A11) ---------------------------------------------------------------


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND "
                        "lower(name) = lower(?)", (name,)).fetchone() is not None


def _discard(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _disk_error(name: str, error: OSError) -> GisError:
    if isinstance(error, PermissionError):
        return target_locked(name)
    return write_failed(name, error)


@dataclass(slots=True)
class _Grid:
    final: Path
    temporary: Path
    backup: Path
    spec: DatasetSpec | None = None
    installed: bool = False
    replaced: bool = False


@dataclass(frozen=True, slots=True)
class _Table:
    spec: DatasetSpec
    family: str
    rows: tuple[tuple[Any, ...], ...]


@dataclass(frozen=True, slots=True, eq=False)
class StoredCheck:
    """Lo guardado de una verificación: su resultado y sus salidas registradas."""

    result: VerifyResult
    records: tuple[Any, ...]


class CheckWriter:
    """Los resultados de una :data:`VERIFY` «en curso» (``handle``) en ``project``: las rejillas
    de incumplimientos (:meth:`grid_paths`), la tabla y la capa de grupos (:meth:`prepare`) y
    :meth:`commit`, en una transacción; si se cierra sin confirmar, nada. Gestor de contexto."""

    def __init__(self, project: StoreProject, handle: OperationHandle) -> None:
        if not isinstance(handle, OperationHandle):
            raise TypeError(f"los resultados son de un OperationHandle, no {handle!r}")
        if handle.project_uid != project.uid or handle.op_type != VERIFY:
            raise ValueError(f"«{handle.op_type}» no es una verificación de este proyecto")
        self.project = project
        self.handle = handle
        with project.read() as conn:
            version = versions_read.version(conn, handle.version_uid)
        if version is None:
            raise ValueError(f"la versión de la operación {handle.uid} no existe")
        self.version_code = version.code
        self.crs, self.vertical = project_references(project)
        self._grids: dict[int, _Grid] = {}
        self._tables: list[_Table] = []
        self._committed = self._closed = False

    def __enter__(self) -> CheckWriter:
        return self

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None,
                 traceback: TracebackType | None) -> None:
        self.close(error)

    def _check_place(self, conn: sqlite3.Connection, spec: DatasetSpec) -> None:
        rows = conn.execute(
            "SELECT name, status, immutable FROM gb_dataset WHERE store = ? AND locator = ?",
            (str(spec.store), spec.locator)).fetchall()
        live = {str(status) for status in LIVE_STATUSES}
        mine = [row for row in rows if row[0] == spec.name and row[1] in live and not row[2]]
        if spec.store is Store.GPKG:
            exists = _table_exists(conn, spec.locator)
        else:
            exists = Path(self.project.root, *spec.locator.split("/")).exists()
        if len(mine) != len(rows) or (exists and not mine):
            raise GisError("gis.output_target_taken", obj=f"{_OBJ}: «{spec.name}»",
                           field=_FIELD, value=spec.locator, name=spec.name)

    def grid_paths(self, name: str, count: int) -> dict[int, tuple[Path, Path]]:
        """Prepara las rejillas de incumplimientos de los ``count`` finales de ``name``: cada
        sitio libre o del mismo dato, su temporal, su destino y la copia del anterior
        reclamados; devuelve final → ``(destino, temporal)``."""
        found: dict[int, tuple[Path, Path]] = {}
        for position in range(1, count + 1):
            spec = dataset_spec(VIOLATIONS, name, self.version_code, final=position)
            final = Path(self.project.root, *spec.locator.split("/"))
            temporary = temporary_path(self.project, final)
            backup = backup_path(self.project, final)
            for path in (temporary, backup):
                check_path_length(path, obj=final.name)
            with self.project.read() as conn:
                self._check_place(conn, spec)
            self.handle.claim_paths(temporary, final, backup)
            try:
                final.parent.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                raise write_failed(final.name, error) from None
            self._grids[position] = _Grid(final, temporary, backup)
            found[position] = (final, temporary)
        return found

    def prepare_steps(self, result: VerifyResult) -> Generator[None, None, None]:
        """Las rejillas escritas y las dos tablas con su hash (fuera de la transacción), por
        pasos (T36): una unidad por cada trozo de grupos cuyo punto se codifica y por cada trozo
        de filas que se inserta y se hashea (sin sostener una lectura abierta entre unidades)."""
        for position, written in result.grids.items():
            entry = self._grids.get(position)
            if entry is None or Path(written.path) != entry.temporary:
                raise ValueError(f"la rejilla del final {position} no está en su temporal")
            entry.spec = dataset_spec(VIOLATIONS, result.name, self.version_code, final=position,
                                      content=written.digest, crs_epsg=self.crs.epsg)
        yield None
        srs = self.crs.epsg
        table_rows = tuple(tuple(row) for row in result.table_rows())
        yield None
        points = result.group_rows()
        yield None
        group_rows: list[tuple[Any, ...]] = []
        for first in range(0, len(points), _GROUPS_PER_UNIT):
            group_rows += [(encode_geometry("POINT", np.array([x, y]), srs, False), *values)
                           for *values, x, y in points[first:first + _GROUPS_PER_UNIT]]
            yield None
        for family, rows in ((TABLE, table_rows), (GROUPS, tuple(group_rows))):
            content = yield from _digest_steps(family, rows, self.crs)
            spec = dataset_spec(family, result.name, self.version_code, content=content,
                                crs_epsg=srs if family == GROUPS else None)
            with self.project.read() as conn:
                self._check_place(conn, spec)
            self._tables.append(_Table(spec, family, rows))
            yield None

    def prepare(self, result: VerifyResult) -> None:
        """:meth:`prepare_steps` de una vez."""
        steps = self.prepare_steps(result)
        while True:
            try:
                next(steps)
            except StopIteration:
                return

    @property
    def specs(self) -> tuple[DatasetSpec, ...]:
        grids = [entry.spec for _k, entry in sorted(self._grids.items()) if entry.spec]
        return (*(table.spec for table in self._tables), *grids)

    def _install(self) -> None:
        for entry in self._grids.values():
            if entry.spec is None or entry.installed:
                continue
            if entry.final.exists():
                try:
                    os.replace(entry.final, entry.backup)
                except OSError as error:
                    raise _disk_error(entry.final.name, error) from None
                entry.replaced = True
            try:
                os.replace(entry.temporary, entry.final)
            except OSError as error:
                failure = _disk_error(entry.final.name, error)
                self._restore(entry)
                raise failure from None
            entry.installed = True

    @staticmethod
    def _restore(entry: _Grid) -> None:
        if entry.replaced:
            try:
                os.replace(entry.backup, entry.final)
                entry.replaced = False
            except OSError:
                pass

    def _write_table(self, conn: sqlite3.Connection, table: _Table) -> None:
        spec = table.spec
        self._check_place(conn, spec)
        if _table_exists(conn, spec.locator):
            conn.execute(f'DELETE FROM "{spec.locator}"')
        else:
            label = _family(table.family).label
            _create(conn, table.family, spec.locator, self.crs.epsg,
                    f"{label} «{spec.name}» {self.version_code}",
                    f"{label} de la versión {self.version_code}, de Geoblender")
        insert_rows(conn, spec.locator, _names(table.family), table.rows)

    def commit(self, *, figures: Sequence[FigureSpec], message: str | None = None
               ) -> tuple[Any, ...]:
        """Pone las rejillas en su sitio y confirma, en **una** transacción, las tablas, las
        cifras y ``complete``. Si falla, deshace lo de esta operación y el error sigue."""
        if self._committed or self._closed:
            raise RuntimeError("los resultados ya se confirmaron o se cerraron")
        try:
            self._install()
            with self.project.write_transaction() as conn:
                for table in self._tables:
                    self._write_table(conn, table)
                records = self.handle.complete(conn, outputs=self.specs, figures=figures,
                                               message=message)
        except BaseException as error:
            self.close(error)
            raise
        self._committed = True
        self.close()
        return records

    def close(self, error: BaseException | None = None) -> None:
        """Termina: confirmada, borra lo anterior apartado; si no, deshace lo puesto, borra los
        temporales y deja la operación «cancelada» o «fallida»."""
        if self._closed:
            return
        self._closed = True
        if self._committed:
            for entry in self._grids.values():
                _discard(entry.backup)
            return
        for entry in self._grids.values():
            if entry.installed:
                if entry.replaced:
                    self._restore(entry)
                else:
                    _discard(entry.final)
            _discard(entry.temporary)
        problem = self._abandon(error)
        if problem and error is not None:
            error.add_note(problem)

    def _abandon(self, error: BaseException | None) -> str | None:
        try:
            with self.project.read() as conn:
                row = conn.execute("SELECT status FROM gb_operation WHERE uid = ?",
                                   (self.handle.uid,)).fetchone()
            if row is None or row[0] != OperationStatus.RUNNING:
                return None
            if isinstance(error, GeneratorExit):
                self.handle.cancel(CANCELLED_REASON)
            elif isinstance(error, CANCELLATIONS):
                self.handle.cancel(cancel_reason(error))
            else:
                self.handle.fail(NOT_COMPLETED_REASON if error is None
                                 else failure_reason(error))
        except (GeoblenderError, OSError, sqlite3.Error) as exc:
            return (f"La operación «{self.handle.op_type}» ({self.handle.uid}) sigue «en curso» "
                    f"en el proyecto: no se pudo registrar cómo terminó ({exc}).")
        return None


def _thickness(handle: OperationHandle) -> float:
    found = next((param for param in handle.params if param.key == MIN_THICKNESS), None)
    if found is None or found.value is None:
        raise ValueError(f"la verificación no leyó «{MIN_THICKNESS}» al empezar")
    return convert(float(found.value), found.unit, "m")  # type: ignore[arg-type]


def verify_run(project: StoreProject, handle: OperationHandle, *,
               budget_s: float = STEP_BUDGET_S, masks: MaskSet | None = None,
               sources: Mapping[str, SurfaceSource] | None = None) -> Iterator[Progress]:
    """Los pasos de :data:`VERIFY` (``handle``, «en curso», de :func:`begin_verify`): las
    máscaras (``masks``, las que consumió; si no, ``load_masks``), las superficies de sus
    ajustes, el espesor que anotó; verificar y guardar. El último ``Progress`` lleva el
    :class:`StoredCheck`. Cerrarlo antes o un fallo: nada en el proyecto (RF-012-28).
    ``sources``: las superficies de sus ajustes ya leídas (:func:`project_sources`)."""
    if not isinstance(handle, OperationHandle) or handle.op_type != VERIFY:
        raise ValueError(f"verify_run es de {VERIFY}")
    return _run(project, handle, budget_s, masks, sources)


def _run(project: StoreProject, handle: OperationHandle, budget_s: float,
         masks: MaskSet | None, sources: Mapping[str, SurfaceSource] | None
         ) -> Iterator[Progress]:
    with CheckWriter(project, handle) as out:
        if masks is None:
            masks = load_masks(project, handle.version_uid)
        name, start, finals = _settings_request(handle.settings)
        selection = BaseSelection.of_settings(handle.settings)
        access = AccessSelection.of_settings(handle.settings)  # spec 017, T18: sus tablas de zonas son entradas
        communicated = (read_communicated(project, access, len(finals)) if access.uses else ())
        request = ComplianceRequest(name, start, finals, masks, _thickness(handle),
                                    bases=selection.refs, communicated=communicated)
        if sources is None:
            sources = project_sources(project, start, finals, version_uid=handle.version_uid,
                                      bases=selection.refs)
        else:
            sources = _with_bases(project, sources, selection.refs, handle.version_uid)
        paths = out.grid_paths(name, len(finals))
        yield Progress(_PHASE, 0, 1, _TEXT)
        steps = verify_steps(request, sources, references=(out.crs, out.vertical),
                             budget_s=budget_s, grid_paths=paths, selection=selection,
                             access=access)
        last: Progress | None = None
        with closing(steps):
            for step in steps:
                if step.result is not None:
                    last = step
                    break
                yield Progress(step.phase, step.done, step.total + 2, step.message)
        assert last is not None and isinstance(last.result, VerifyResult)
        result: VerifyResult = last.result
        total = last.total + 2
        done = last.total
        yield Progress("save", done, total, f"Guardando «{name}»…")  # el cierre del cálculo, aparte
        saving = pace_units(out.prepare_steps(result), budget_s)
        while True:  # los hashes de las tablas por tramos (fuera de la transacción, R4)
            try:
                next(saving)
            except StopIteration:
                break
            done += 1
            total = max(total, done + 1)
            yield Progress("save", done, total, f"Guardando «{name}»…")
        total = max(total, done + 2)
        yield Progress("save", total - 1, total, f"Guardando «{name}»…")
        records = out.commit(figures=result.figures, message=last.message)
    yield Progress("save", total, total, last.message, result=StoredCheck(result, records))


# --- Reproducir --------------------------------------------------------------------------------

_ROLE_CLASSES = "masks_classes"
_ROLE_ZONES = "masks_zones"
_ROLE_REPORT = "masks_report"


def _frozen_table(request: ReproduceRequest, role: str, read: Any) -> Any:
    item = request.input(role)
    layer = item.settings.get("layer")
    if not isinstance(layer, str) or not layer:
        raise ValueError(f"la entrada congelada «{item.name}» no dice su tabla (layer)")
    with GpkgConnection.open_read(Path(item.files["main"])) as gpkg:
        return read(gpkg.connection, layer)


def _frozen_masks(request: ReproduceRequest) -> MaskSet:
    """Las máscaras congeladas que consumió la verificación."""
    source = read_geotiff(Path(request.input(_ROLE_CLASSES).files["main"]),
                          max_cells=sys.maxsize)
    values = np.asarray(source.values, dtype=np.float64)
    classes = np.where(np.isfinite(values), values, 0.0).astype(np.uint16)
    zones = _frozen_table(request, _ROLE_ZONES, read_zone_runs)
    report = _frozen_table(request, _ROLE_REPORT, read_report)
    weights = {code: float(value) for code, quantity, value, _u, _n in report
               if quantity == "weight" and value is not None}
    ctypes = {code: str(note) for code, quantity, _v, _u, note in report
              if quantity == "zone_area" and note is not None}
    grid: Grid = source.grid
    return MaskSet(grid, "", "", MaskState.CURRENT,
                   tuple(request.settings.get("pending_sectors") or ()), classes,
                   tuple(request.settings.get("pending_names") or ()),
                   MappingProxyType(zones), MappingProxyType(weights), (),
                   MappingProxyType(ctypes))


def _frozen_source(request: ReproduceRequest, role: str, ref: SurfaceRef,
                   references: tuple[CrsRef, VerticalRef]) -> SurfaceSource:
    crs, vertical = references
    if ref.elevation is not None:
        return constant_source(ref.elevation, name=ref.shown, crs=crs, vertical=vertical)
    item = request.input(role)
    return grid_source(item.files["main"], name=ref.shown, crs=crs, vertical=vertical)


def _reproduced_table(request: ReproduceRequest, family: str, rows: Sequence[tuple[Any, ...]],
                      crs: CrsRef) -> ReproducedOutput:
    found = _family(family)
    path = Path(request.workdir) / f"{found.role}.gpkg"
    check_path_length(path, obj=_OBJ)
    with GpkgConnection.open_write(path, create=True) as gpkg, gpkg.transaction() as conn:
        create_base(conn, crs)
        _create(conn, family, found.role, crs.epsg, found.label)
        insert_rows(conn, found.role, _names(family), rows)
    return ReproducedOutput(found.role, found.reader, {"main": path}, {"layer": found.role})


def reproduce_verify(request: ReproduceRequest, *,
                     budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """Reproduce :data:`VERIFY` con sus máscaras, sus superficies y su espesor congelados y sus
    ajustes, sin el proyecto: sus pasos y, el último, el ``ReproducedResult``."""
    if not isinstance(request, ReproduceRequest) or request.op_type != VERIFY:
        raise ValueError(f"esta función reproduce {VERIFY}")
    return _reproduce(request, budget_s)


def _reproduce(request: ReproduceRequest, budget_s: float) -> Iterator[Progress]:
    references = request.references()
    crs = references[0]
    name, start, finals = _settings_request(request.settings)
    value, unit = request.params.get(MIN_THICKNESS, (None, ""))
    if value is None:
        raise ValueError(f"«{VERIFY}» no tiene «{MIN_THICKNESS}» entre sus parámetros")
    thickness = convert(float(value), unit, "m")  # type: ignore[arg-type]
    masks = _frozen_masks(request)
    selection = BaseSelection.of_settings(request.settings)
    sources = {START_ROLE: _frozen_source(request, START_ROLE, start, references)}
    for position, ref in enumerate(finals, start=1):
        role = final_role(position)
        sources[role] = _frozen_source(request, role, ref, references)
    for position, ref in enumerate(selection.refs, start=1):  # las bases de los acopios (T30)
        role = base_role(position)
        sources[role] = _frozen_source(request, role, ref, references)
    access = AccessSelection.of_settings(request.settings)
    zone_sets = [  # las tablas de zonas congeladas de las accesibilidades (spec 017, T18)
        frozenset(row.code for row in _frozen_table(request, access_role(position),
                                                    access_store.read_zone_table)
                  if row.connected)
        for position in range(1, len(access.uses) + 1)]
    communicated = access.communicated_by_final(zone_sets, len(finals)) if access.uses else ()
    paths: dict[int, tuple[Path, Path | None]] = {}
    for position in range(1, len(finals) + 1):
        path = Path(request.workdir) / f"{_violations_role(position)}.tif"
        temporary = path.with_name(path.name + ".tmp")
        check_path_length(temporary, obj=_OBJ)
        paths[position] = (path, temporary)
    steps = verify_steps(ComplianceRequest(name, start, finals, masks, thickness,
                                           bases=selection.refs, communicated=communicated),
                         sources, references=references, budget_s=budget_s, grid_paths=paths,
                         selection=selection, access=access)
    last: Progress | None = None
    with closing(steps):
        for step in steps:
            last = step
            if isinstance(step.result, VerifyResult):
                break
            yield step
    assert last is not None and isinstance(last.result, VerifyResult)
    result: VerifyResult = last.result
    outputs = [_reproduced_table(request, TABLE, result.table_rows(), crs),
               _reproduced_table(request, GROUPS, [
                   (encode_geometry("POINT", np.array([x, y]), crs.epsg, False), *values)
                   for *values, x, y in result.group_rows()], crs)]
    for position, written in sorted(result.grids.items()):
        path = paths[position][0]
        os.replace(written.path, path)
        outputs.append(ReproducedOutput(_violations_role(position), GEOTIFF.id, {"main": path}))
    yield Progress(last.phase, last.total, last.total, f"«{name}» reproducida",
                   result=ReproducedResult(tuple(outputs), result.figures))


REPRODUCE: Mapping[str, Any] = MappingProxyType({VERIFY: reproduce_verify})
"""La función de reproducir de la verificación (la que registra ``bl``)."""


# --- Congelar con lo que no cumple (RF-012-25; D-7, D-29) ---------------------------------------

_VERIFICATIONS = (  # por gb_operation_revision: las verificaciones hechas de cualquier revisión
    "SELECT o.uid, o.superseded_by IS NOT NULL, o.settings FROM gb_operation AS o "
    "JOIN gb_revision AS r ON r.uid = o.revision_uid "
    "WHERE o.op_type = ? AND o.status = 'done' AND r.version_uid = ? ORDER BY o.fid"
)
_FINALS = (  # por el índice único de (operation_uid, direction, …)
    "SELECT item_uid FROM gb_operation_io WHERE operation_uid = ? AND direction = 'in' "
    "AND item_kind = 'dataset' AND role GLOB 'final_[0-9]*' ORDER BY fid"
)
_DESIGN_SURFACES = (  # por los índices gb_dataset_version y gb_operation_io_item
    "SELECT DISTINCT d.uid FROM gb_dataset AS d JOIN gb_operation_io AS io "
    "ON io.item_kind = 'dataset' AND io.item_uid = d.uid AND io.direction = 'out' "
    "WHERE d.version_uid = ? AND io.role = ?"
)
_STALE = "SELECT 1 FROM gb_stale WHERE item_kind = 'operation' AND item_uid = ? LIMIT 1"
_DATASET = "SELECT name, version_uid, status FROM gb_dataset WHERE uid = ?"
_COUNTS_MESSAGE = {Counts.CUT.value: "res.freeze_cut", Counts.FILL.value: "res.freeze_fill",
                   Counts.ANY.value: "res.freeze_any",
                   Counts.CUT_TERRAIN.value: "res.freeze_cut_terrain",
                   Counts.ACCESS.value: "res.freeze_access"}
"""Qué se cuenta en un recinto (la nota de su fila ``counted_m3``) → su mensaje."""
_LIVE = frozenset(str(status) for status in LIVE_STATUSES)


def _volume_text(value: float | None) -> str:
    """Un volumen (m³) en español, con espacio fino de miles y coma decimal (sin depender del
    idioma activo: la nota se guarda en la revisión): sin decimales desde 100 m³ y con uno por
    debajo."""
    number = 0.0 if value is None or not math.isfinite(value) else float(value)
    text = f"{number:,.{0 if abs(number) >= 100 else 1}f}"
    return text.translate(str.maketrans({",": THIN_SPACE, ".": ","}))


def _zone_label(zone: str) -> str:
    """Cómo se nombra un recinto de la tabla en una nota: «torre»; los dos de fuera, con
    palabras; la banda hacia dentro de un límite, «concesion» (banda hacia dentro)."""
    if zone == OUTSIDE_PERIMETER:
        return render("res.freeze_zone_outside_perimeter")
    if zone == OUTSIDE_LEGAL:
        return render("res.freeze_zone_outside_legal")
    if zone.endswith(INNER_SUFFIX):
        return render("res.freeze_zone_inner", zone=zone.removesuffix(INNER_SUFFIX))
    return f"«{zone}»"


def _failures(rows: Sequence[tuple[str, int, str, float | None, str | None, str | None]],
              check: str) -> list[str]:
    """Una nota por final con recintos que no cumplen (``res.freeze_fails``): cada recinto con
    lo que cuenta en él (m³ de corte, de relleno o de movimiento), en el orden de la tabla."""
    shown = {final: str(note) for zone, final, quantity, _v, _u, note in rows
             if quantity == "surface" and not zone}
    counted = {(final, zone): (value, note) for zone, final, quantity, value, _u, note in rows
               if quantity == "counted_m3"}
    failing: dict[int, list[str]] = {}
    for zone, final, quantity, _value, _unit, note in rows:
        if quantity != "verdict" or note != Verdict.FAILS.value:
            continue
        value, counts = counted.get((final, zone), (None, None))
        code = _COUNTS_MESSAGE.get(counts or "", "res.freeze_any")
        failing.setdefault(final, []).append(
            render(code, zone=_zone_label(zone), volume=_volume_text(value)))
    return [render("res.freeze_fails", check=check, final=shown.get(final, str(final)),
                   zones="; ".join(zones)) for final, zones in sorted(failing.items())]


def _verification_findings(conn: sqlite3.Connection, version_uid: str, uid: str,
                           settings: Mapping[str, Any], pending: Sequence[str]
                           ) -> list[FreezeFinding]:
    """Los hallazgos de una verificación vigente: obsoleta, los recintos que no cumplen (con
    sus m³; o la tabla que no se pudo leer) y la marca de búsqueda pendiente (RF-012-10) con los
    sectores que ``pending`` dice sin búsqueda vigente ahora, todos sobre su operación."""
    check = str(settings.get("name") or uid[:8])
    notes: list[str] = []
    if conn.execute(_STALE, (uid,)).fetchone() is not None:
        notes.append(render("res.freeze_stale", check=check))
    try:
        table = dataset_registry.get(conn, dataset_name(TABLE, check), version_uid=version_uid)
    except ValueError:
        table = None
    if table is not None and table.operation_uid == uid:
        try:
            notes += _failures(read_table(conn, table.locator), check)
        except sqlite3.Error:
            notes.append(render("res.freeze_unreadable", check=check))
    if pending:
        notes.append(render("res.freeze_pending", check=check,
                            sectors=", ".join(f"«{name}»" for name in pending)))
    return [FreezeFinding(MODULE, ItemKind.OPERATION, uid, check, note) for note in notes]


def freeze_findings(conn: sqlite3.Connection, version_uid: str) -> tuple[FreezeFinding, ...]:
    """Lo que ``res`` pide aceptar al congelar la revisión abierta de la versión ``version_uid``
    (RF-012-25; D-7, D-29): la comprobación que registra ``bl`` con
    ``core.versions.freeze.register_freeze_check``. Lee ``conn`` (una instantánea de lectura) y
    no escribe. Por cada verificación **vigente** de la versión (hecha, sin sustituir, de
    cualquiera de sus revisiones), sobre su operación y con su nombre:

    - obsoleta (``gb_stale``, la caché de la 008): hay que repetirla;
    - con recintos que no cumplen: por cada final que incumple, sus recintos con lo que cuenta
      en ellos en m³ (de la tabla ``res_chk_``, tal como se guardó);
    - con la marca de RF-012-10: hay sectores sin búsqueda de intocables vigente **ahora**
      (calculados al vuelo, D-26: ``gis.masks.store.current_pending``, no los que anotó al
      hacerse; una búsqueda cerrada después, sin cambiar las máscaras, la quita).

    Y por cada **superficie de diseño sin verificación al día** (D-29, 013 D-28), sobre su dato
    y con la misma nota (``res.freeze_surface_unchecked``): la que fue final de una verificación
    sustituida y la que ``design`` declara con el papel
    :data:`~geoblender.design.provenance.DESIGN_SURFACE_ROLE` (el del escalonado, RF-013-31) en
    esta versión, si ya no es final de ninguna verificación vigente (una vigente obsoleta ya se
    lista por obsoleta) y sigue viva y es del proyecto o de la versión. Desde la 015 (T32;
    RF-015-04, P-2) cuenta también **la última de cada cadena de entidades**
    (:func:`~geoblender.design.entities.chain_tail_surfaces`: su ``des_psf_`` vivo, con el papel
    :data:`~geoblender.design.provenance.ENTITY_SURFACE_ROLE`) como una de diseño; las
    **intermedias** de una cadena son superficies de trabajo (se verifican a petición) y no se
    piden, tampoco por haber sido final de una verificación sustituida, y una entidad descartada
    o sin calcular no cuenta (la que queda como última de su cadena, sí). Una superficie que cae
    en varias se lista una vez. Una verificación cuya tabla no se puede leer no se da por buena
    (``res.freeze_unreadable``)."""
    found: list[FreezeFinding] = []
    current: set[str] = set()
    replaced: dict[str, None] = {}
    pending: tuple[str, ...] | None = None
    for uid, superseded, text in conn.execute(_VERIFICATIONS, (VERIFY, version_uid)).fetchall():
        finals = [str(row[0]) for row in conn.execute(_FINALS, (str(uid),))]
        if superseded:
            replaced.update(dict.fromkeys(finals))
            continue
        current.update(finals)
        if pending is None:  # una vez, y solo si hay alguna verificación vigente
            pending = current_pending(conn, None, version_uid)[1]
        settings = json.loads(str(text))
        found += _verification_findings(conn, version_uid, str(uid),
                                        settings if isinstance(settings, Mapping) else {},
                                        pending)
    unchecked = dict(replaced)  # las sustituidas, las de diseño y las últimas de cada cadena, una vez
    unchecked.update(dict.fromkeys(
        str(row[0]) for row in conn.execute(_DESIGN_SURFACES, (version_uid, DESIGN_SURFACE_ROLE))))
    tails = dict.fromkeys(chain_tail_surfaces(conn, version_uid))
    unchecked.update(tails)
    working = {str(row[0]) for row in conn.execute(  # las de las entidades que no son la última
        _DESIGN_SURFACES, (version_uid, ENTITY_SURFACE_ROLE))}.difference(tails)
    surfaces: list[FreezeFinding] = []
    for uid in unchecked:
        row = conn.execute(_DATASET, (uid,)).fetchone()
        if (uid in current or uid in working or row is None or str(row[2]) not in _LIVE
                or str(row[1]) not in ("", version_uid)):
            continue
        surfaces.append(FreezeFinding(MODULE, ItemKind.DATASET, uid, str(row[0]),
                                      render("res.freeze_surface_unchecked",
                                             surface=str(row[0]))))
    surfaces.sort(key=lambda item: (item.name, item.item_uid))
    return tuple(found + surfaces)


# --- La última verificación de una restricción (T27; RF-012-19) ---------------------------------

_LAST_VERIFICATION = (  # por gb_operation_revision: la última hecha y vigente de la versión
    "SELECT o.uid, o.settings FROM gb_operation AS o "
    "JOIN gb_revision AS r ON r.uid = o.revision_uid "
    "WHERE o.op_type = ? AND o.status = 'done' AND o.superseded_by IS NULL "
    "AND r.version_uid = ? ORDER BY o.fid DESC LIMIT 1"
)
_ZONE_ROWS = (  # lo del recinto y los nombres de los finales (recinto vacío)
    'SELECT zone, "final", quantity, value, note FROM "{table}" '
    "WHERE zone IN (?, ?, '') ORDER BY fid"
)
_ZONE_FIGURES = (  # por el índice (clave, ámbito): una consulta por final y recinto
    f"SELECT {FIGURE_COLUMNS} FROM gb_figure WHERE key IN ({{marks}}) AND scope_key = ? "
    "AND operation_uid = ? ORDER BY fid"
)
_VERDICT_RANK = {"": 0, Verdict.UNCHECKED.value: 1, Verdict.NOT_JUDGED.value: 2,
                 Verdict.COMPLIES.value: 3, Verdict.FAILS.value: 4}
"""Cuál manda cuando una restricción tiene dos recintos (un límite legal y su banda hacia
dentro): no cumplir manda sobre todo."""


@dataclass(frozen=True, slots=True)
class ZoneFinal:
    """Lo de una restricción en un final de una verificación: su posición (desde 1) y el nombre de
    su superficie, el veredicto (:class:`~.compliance.Verdict`; vacío si el recinto no entró en la
    verificación), lo que cuenta en él (:class:`~.compliance.Counts`) con sus m³ (``None`` si nada
    cuenta) y sus cifras registradas, en su orden. Con una banda hacia dentro (un límite legal),
    manda el peor veredicto de los dos recintos y las cifras son las de los dos."""

    position: int
    surface: str
    verdict: str
    counts: str
    counted_m3: float | None
    figures: tuple[FigureRecord, ...]


@dataclass(frozen=True, slots=True)
class ZoneCheck:
    """La última verificación vigente de una versión en lo que toca a una restricción: su
    operación y su nombre, si está obsoleta (``gb_stale``, la caché de la 008) y lo de cada final
    (:class:`ZoneFinal`)."""

    operation_uid: str
    name: str
    stale: bool
    finals: tuple[ZoneFinal, ...]


def zone_check(conn: sqlite3.Connection, version_uid: str, code: str) -> ZoneCheck | None:
    """Lo que dice de la restricción de código ``code`` la última verificación vigente (hecha, sin
    sustituir, de cualquier revisión) de la versión ``version_uid`` (RF-012-19): por cada final
    su superficie, su veredicto y sus cifras registradas (``gb_figure``, con el ámbito
    ``{check, final, zone}`` de :func:`_figures`). ``None`` si la versión no tiene ninguna
    verificación o su tabla no se puede leer. Lee ``conn`` (una instantánea) y no escribe; una
    restricción que no entró en la verificación (desactivada en la versión) sale con sus finales
    sin veredicto ni cifras."""
    found = conn.execute(_LAST_VERIFICATION, (VERIFY, version_uid)).fetchone()
    if found is None:
        return None
    uid, text = str(found[0]), json.loads(str(found[1]))
    name = str((text if isinstance(text, Mapping) else {}).get("name") or uid[:8])
    try:
        table = dataset_registry.get(conn, dataset_name(TABLE, name), version_uid=version_uid)
    except ValueError:
        return None
    if table is None or table.operation_uid != uid:
        return None
    inner = f"{code}{INNER_SUFFIX}"
    try:
        rows = conn.execute(_ZONE_ROWS.format(table=table.locator), (code, inner)).fetchall()
    except sqlite3.Error:
        return None
    surfaces = {int(final): str(note) for zone, final, quantity, _value, note in rows
                if quantity == "surface" and not zone}
    verdicts: dict[tuple[int, str], str] = {}
    counted: dict[tuple[int, str], tuple[float | None, str]] = {}
    for zone, final, quantity, value, note in rows:
        if not zone:
            continue
        if quantity == "verdict":
            verdicts[(int(final), str(zone))] = str(note)
        elif quantity == "counted_m3":
            counted[(int(final), str(zone))] = (None if value is None else float(value),
                                                str(note or ""))
    marks = ", ".join("?" for _ in FIGURES)
    keys = tuple(figure.key for figure in FIGURES)
    finals: list[ZoneFinal] = []
    for position in sorted(surfaces):
        figures: list[FigureRecord] = []
        for zone in (code, inner):
            scope = {"check": name, "final": position, "zone": zone}
            figures += [FigureRecord.from_row(row) for row in conn.execute(
                _ZONE_FIGURES.format(marks=marks), (*keys, scope_key(scope), uid))]
        decisive = max((code, inner), key=lambda zone: _VERDICT_RANK.get(
            verdicts.get((position, zone), ""), 0))
        verdict = verdicts.get((position, decisive), "")
        value, counts = counted.get((position, decisive), (None, ""))
        finals.append(ZoneFinal(position, surfaces[position], verdict, counts, value,
                                tuple(figures)))
    stale = conn.execute(_STALE, (uid,)).fetchone() is not None
    return ZoneCheck(uid, name, stale, tuple(finals))


# --- La ventana de la verificación y la rejilla de incumplimientos (T28; RF-012-23) --------------

_VERIFICATIONS_OF = (  # las vigentes de la versión, la más reciente primero
    "SELECT o.uid, o.settings FROM gb_operation AS o "
    "JOIN gb_revision AS r ON r.uid = o.revision_uid "
    "WHERE o.op_type = ? AND o.status = 'done' AND o.superseded_by IS NULL "
    "AND r.version_uid = ? ORDER BY o.fid DESC"
)
_SETTINGS = "SELECT settings FROM gb_operation WHERE uid = ?"


@dataclass(frozen=True, slots=True)
class StoredZone:
    """Lo verificado en un recinto de un final tal como lo guardó la tabla (``res_chk_``): el
    recinto (``zone``: el código de una restricción, su banda hacia dentro ``<código>:inner``,
    ``outside_perimeter`` u ``outside_legal``), el final (desde 1), lo que cuenta en él
    (``counts``: ``cut``, ``fill``, ``any``, ``nothing``, ``avoid`` o ``access``), el corte y el
    relleno (m³), el área con movimiento y sin dato (m²), los m³ que cuentan, el peso y el
    volumen por el peso (``None`` si no es de «preferible no afectar») y el veredicto
    (:class:`~.compliance.Verdict`). Con la base de los acopios (T30), ``counts`` de las zonas que
    cuentan el corte de terreno es ``cut_terrain``, ``counted_m3`` es el corte de terreno y
    ``stockpile_cut_m3`` el de acopios (``None`` en las demás y sin base)."""

    zone: str
    final: int
    counts: str
    cut_m3: float
    fill_m3: float
    moved_m2: float
    nodata_m2: float
    counted_m3: float
    weight: float | None
    weighted_m3: float | None
    verdict: str
    stockpile_cut_m3: float | None = None


@dataclass(frozen=True, slots=True)
class StoredGroup:
    """Un grupo de celdas contiguas que incumplía, tal como lo guardó la capa ``res_chkg_``: el
    final (desde 1), el recinto, las celdas, el área (m²), el volumen (m³), el espesor máximo (m)
    y su centro absoluto (``x``, ``y``)."""

    final: int
    zone: str
    cells: int
    area_m2: float
    volume_m3: float
    max_m: float
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class StoredVerification:
    """Una verificación vigente de una versión, leída de lo que guardó (RF-012-23): su operación y
    su nombre, si está obsoleta (``gb_stale``), la superficie de cada final (``surfaces``, desde
    el final 1), lo de cada recinto en cada final (``zones``, en el orden de la tabla), los
    grupos que incumplen, los sectores sin búsqueda vigente al verificar (la marca de RF-012-10,
    sus nombres), los avisos de cada final (final, texto) y, de cada final que incumplía, el
    ``uid`` del dato de su rejilla de incumplimientos si sigue vivo (``grids``; un dato de una
    versión solo se indica por su uid). Con acopios detectados (T30), las bases que usó
    (``bases``: «Base de acopios: detección STK-001 «Acopios» (mineral)») y los avisos de las
    detecciones que no usó con su causa (``skipped``), tal como los escribió la tabla (en español);
    y, de los ajustes de la operación (T42), esa misma selección (``selection``) y el nombre de la
    partida (``start_name``), para escribir esas líneas en el idioma de quien mira (vacías si los
    ajustes no las dicen). Con accesibilidades de las pistas (spec 017, T18), las que usó cada final
    (``access``: final y «Accesibilidad de «Pozo 1»: ACC-001 «Accesibilidad»») y las que no, con su
    causa (``access_skipped``: final, 0 si es de ninguna, y el aviso), tal como los escribió la
    tabla, y esa misma selección de los ajustes (``access_selection``)."""

    operation_uid: str
    name: str
    stale: bool
    surfaces: tuple[str, ...]
    zones: tuple[StoredZone, ...]
    groups: tuple[StoredGroup, ...]
    pending: tuple[str, ...]
    notices: tuple[tuple[int, str], ...]
    grids: Mapping[int, str]
    bases: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    selection: BaseSelection = BaseSelection()
    start_name: str = ""
    access: tuple[tuple[int, str], ...] = ()
    access_skipped: tuple[tuple[int, str], ...] = ()
    access_selection: AccessSelection = AccessSelection()


def _setting_name(text: object, uid: str) -> str:
    settings = json.loads(str(text))
    return str((settings if isinstance(settings, Mapping) else {}).get("name") or uid[:8])


def _stored_selection(text: object) -> tuple[BaseSelection, str]:
    """La selección de las bases de los acopios y el nombre de la partida que anotan los ajustes (JSON) ``text`` de una verificación
    (:func:`verify_settings`): lo que la ventana necesita para escribir esas líneas en el idioma de la interfaz (T42). Sin acopios, la
    selección vacía; unos ajustes que no se entienden dan lo que sí se entiende y, de lo demás, nada (la ventana enseña entonces lo que
    guardó la tabla): leer una verificación no se rompe por ello."""
    try:
        settings = json.loads(str(text))
    except ValueError:
        return BaseSelection(), ""
    if not isinstance(settings, Mapping):
        return BaseSelection(), ""
    try:
        selection = BaseSelection.of_settings(settings)
    except ValueError:
        selection = BaseSelection()
    try:
        start = _surface_ref(settings.get("start")).shown
    except (ValueError, TypeError):
        start = ""
    return selection, start


def _stored_access(text: object) -> AccessSelection:
    """La selección de las accesibilidades de las pistas que anotan los ajustes (JSON) ``text`` de una verificación (:func:`verify_settings`; spec 017, T18): lo que la ventana necesita
    para escribir esas líneas en el idioma de la interfaz. Sin accesibilidades, la selección vacía; unos ajustes que no se entienden dan también la vacía, sin lanzar: leer una
    verificación no se rompe por ello (la ventana enseña entonces lo que guardó la tabla)."""
    try:
        settings = json.loads(str(text))
        return AccessSelection.of_settings(settings) if isinstance(settings, Mapping) else AccessSelection()
    except ValueError:
        return AccessSelection()


def verification_names(conn: sqlite3.Connection, version_uid: str) -> tuple[str, ...]:
    """Los nombres de las verificaciones vigentes (hechas y sin sustituir, de cualquier
    revisión) de la versión ``version_uid``, la más reciente primero. Solo lee."""
    names: dict[str, None] = {}
    for uid, text in conn.execute(_VERIFICATIONS_OF, (VERIFY, version_uid)).fetchall():
        names.setdefault(_setting_name(text, str(uid)))
    return tuple(names)


def _quantity(found: Mapping[str, tuple[float | None, str | None]], key: str) -> float:
    value = found.get(key, (None, None))[0]
    return 0.0 if value is None else float(value)


def _optional(found: Mapping[str, tuple[float | None, str | None]], key: str) -> float | None:
    value = found.get(key, (None, None))[0]
    return None if value is None else float(value)


def _stored_zones(rows: Sequence[tuple[str, int, str, float | None, str | None, str | None]]
                  ) -> tuple[StoredZone, ...]:
    by_zone: dict[tuple[str, int], dict[str, tuple[float | None, str | None]]] = {}
    for zone, final, quantity, value, _unit, note in rows:
        if zone:
            by_zone.setdefault((zone, final), {})[quantity] = (value, note)
    return tuple(StoredZone(
        zone, final, str(found.get("counted_m3", (None, ""))[1] or ""),
        _quantity(found, "cut_m3"), _quantity(found, "fill_m3"),
        _quantity(found, "moved_area_m2"), _quantity(found, "nodata_area_m2"),
        _quantity(found, "counted_m3"), _optional(found, "weight"),
        _optional(found, "weighted_m3"), str(found.get("verdict", (None, ""))[1] or ""),
        _optional(found, "stockpile_cut_m3"))
        for (zone, final), found in by_zone.items())


def read_verification(conn: sqlite3.Connection, version_uid: str, name: str | None = None
                      ) -> StoredVerification | None:
    """La verificación vigente de la versión ``version_uid`` llamada ``name`` (por defecto, la
    más reciente) tal como la guardó (RF-012-23): su tabla, su capa de grupos y, de cada final
    que incumplía, el dato de su rejilla de incumplimientos. ``None`` si la versión no tiene
    esa verificación o su tabla no se puede leer. Lee ``conn`` (una instantánea) y no
    escribe."""
    found = None
    for uid, text in conn.execute(_VERIFICATIONS_OF, (VERIFY, version_uid)).fetchall():
        shown = _setting_name(text, str(uid))
        if name is None or shown == name:
            found = (str(uid), shown, text)
            break
    if found is None:
        return None
    uid, shown, settings_text = found
    try:
        table = dataset_registry.get(conn, dataset_name(TABLE, shown), version_uid=version_uid)
        if table is None or table.operation_uid != uid:
            return None
        rows = read_table(conn, table.locator)
        groups = dataset_registry.get(conn, dataset_name(GROUPS, shown),
                                      version_uid=version_uid)
        stored = (read_groups(conn, groups.locator)
                  if groups is not None and groups.operation_uid == uid else [])
    except (ValueError, sqlite3.Error):
        return None
    surfaces = {final: str(note) for zone, final, quantity, _v, _u, note in rows
                if quantity == "surface" and not zone}
    grids: dict[int, str] = {}
    for position in sorted(surfaces):
        grid = dataset_registry.get(conn, dataset_name(VIOLATIONS, shown, position),
                                    version_uid=version_uid)
        if grid is not None and grid.operation_uid == uid and grid.live:
            grids[position] = grid.uid
    selection, start_name = _stored_selection(settings_text)
    return StoredVerification(
        uid, shown, conn.execute(_STALE, (uid,)).fetchone() is not None,
        tuple(surfaces[position] for position in sorted(surfaces)), _stored_zones(rows),
        tuple(StoredGroup(final, zone, cells, area, volume, top, x, y)
              for final, zone, cells, area, volume, top, x, y in stored),
        tuple(str(note) for zone, final, quantity, _v, _u, note in rows
              if quantity == "pending_sector" and not zone),
        tuple((final, str(note)) for zone, final, quantity, _v, _u, note in rows
              if quantity == "notice" and not zone),
        MappingProxyType(grids),
        tuple(str(note) for zone, final, quantity, _v, _u, note in rows
              if quantity == "stockpile_base" and not zone),
        tuple(str(note) for zone, final, quantity, _v, _u, note in rows
              if quantity == "stockpile_skipped" and not zone),
        selection, start_name,
        tuple((final, str(note)) for zone, final, quantity, _v, _u, note in rows
              if quantity == "access_used" and not zone),
        tuple((final, str(note)) for zone, final, quantity, _v, _u, note in rows
              if quantity == "access_skipped" and not zone),
        _stored_access(settings_text))


def verify_inputs(project: StoreProject, version: str, start: SurfaceRef,
                  finals: Sequence[SurfaceRef], bases: BaseSelection | None = None,
                  access: AccessSelection | None = None) -> tuple[Use, ...]:
    """Las superficies de la verificación como entradas de la operación (``Use``, por su papel:
    :data:`START_ROLE`, :func:`final_role` y, de cada base de los acopios, :func:`base_role`) y las
    tablas de zonas de las accesibilidades de las pistas (:func:`access_role`; spec 017, T18), las
    que consume la puerta de la 008 antes de empezarla; una cota constante no es entrada.
    ``bases``: la selección de las bases (:func:`select_bases`); sin ella, la de ahora (D-a, la
    automática) y ``BaseSelection()``, sin base. ``access``: la selección de las accesibilidades
    (:func:`select_access`); sin ella, la de ahora y ``AccessSelection()``, sin accesibilidad.
    ``VersionError`` si ``version`` (uid o código) no existe o no es editable; ``ValueError`` si
    una superficie congelada no parte de una revisión."""
    with project.read() as conn:
        found = versions_store.require_editable(conn, str(version))
    selection = select_bases(project, found.uid, start) if bases is None else bases
    chosen = select_access(project, found.uid, finals) if access is None else access
    inputs: list[Use] = []
    for role, ref in ((START_ROLE, start),
                      *((final_role(k), item) for k, item in enumerate(finals, start=1)),
                      *((base_role(k), item) for k, item in enumerate(selection.refs, start=1))):
        use = _surface_use(ref, role, found.parent_revision_uid)
        if use is not None:
            inputs.append(use)
    inputs += [Use(dataset, access_role(k)) for k, dataset in enumerate(chosen.datasets, start=1)]
    return tuple(inputs)


@dataclass(frozen=True, slots=True)
class StoredViolations:
    """Una rejilla de incumplimientos que se quiere ver: su dato, el nombre de la verificación
    que la escribió, su final (desde 1), la superficie final de la verificación (la de sus
    ajustes) y la versión del dato."""

    record: DatasetRecord
    name: str
    final: int
    surface: SurfaceRef
    version_uid: str


def stored_violations(project: StoreProject, ref: str) -> StoredViolations:
    """La rejilla de incumplimientos ``ref`` (su uid o su nombre, ``res_chkv_<nombre>_<k>``) con lo
    que dice de ella su operación (:class:`StoredViolations`): lo que necesita su vista (D-42).
    ``ValueError`` si no es una rejilla de incumplimientos viva del proyecto. No escribe."""
    if not isinstance(ref, str) or not ref:
        raise TypeError("una rejilla de incumplimientos se indica por su uid o su nombre, no "
                        f"{ref!r}")
    with project.read() as conn:
        record = dataset_registry.get(conn, ref)
        prefix = f"{MODULE}_{VIOLATIONS}_"
        if record is None or not record.live or not record.name.startswith(prefix):
            raise ValueError(f"«{ref}» no es una rejilla de incumplimientos del proyecto")
        row = conn.execute(_SETTINGS, (record.operation_uid,)).fetchone()
        version_uid = versions_read.dataset_versions(conn, [record.uid]).get(record.uid, "")
    position = int(record.name.rpartition("_")[2])
    settings = json.loads(str(row[0] or "{}")) if row is not None else {}
    name, _start, finals = _settings_request(settings)
    if not 1 <= position <= len(finals):
        raise ValueError(f"«{record.name}» no es el final de una verificación")
    return StoredViolations(record, name, position, finals[position - 1], version_uid)


def violation_sources(project: StoreProject, stored: StoredViolations
                      ) -> tuple[SurfaceSource, SurfaceSource]:
    """Lo que se lee para ver ``stored``: su superficie final (``reserves.surfaces.surface_source``
    en su versión: un dato, lo congelado en la revisión de la que parte o la cota constante) y la
    propia rejilla (su GeoTIFF, en las referencias del proyecto si no las declara). Los errores de
    ``surface_source``; ``gis.dataset_file_missing`` si falta el fichero de la rejilla."""
    final = surface_source(project, stored.surface, version_uid=stored.version_uid)
    record = stored.record
    path = Path(project.root, *record.locator.split("/"))
    if not path.is_file():
        raise GisError("gis.dataset_file_missing", obj=f"{_OBJ}: «{record.name}»",
                       field=_FIELD, value=record.locator, file=path.name, name=record.name)
    crs, vertical = project_references(project)
    return final, grid_source(path, name=record.name, crs=crs, vertical=vertical)

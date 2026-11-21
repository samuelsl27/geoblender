# SPDX-License-Identifier: GPL-3.0-or-later
"""Reproducir lo congelado de las envolventes y el escalonado (spec 013, T15; HU-013-6;
RF-013-17, RF-013-31; CE-013-08; plan 013 §5.2.3, §5.3.2; RF-009-11).

Las funciones de reproducir de los dos tipos de ``des`` (``OperationDef.reproduce``,
:data:`REPRODUCE`). ``core.versions.reproduce`` da a cada una, por cada operación congelada de una
revisión, su ``ReproduceRequest``: sus ajustes, sus entradas congeladas (``FrozenInput``: el
GeoTIFF de la instantánea de cada superficie y de cada máscara, las tablas de ``entradas.gpkg``),
sus parámetros congelados (el valor de la fila del historial que usó), una carpeta de trabajo vacía
y el registro del proyecto. **No recibe el proyecto ni escribe en él.** Cada una hace **lo mismo
que el recálculo** —el mismo cálculo, ``design.pipeline``— con lo congelado:

- las máscaras de la versión (la rejilla de clases y las zonas), los sectores de búsqueda
  (``core_sector``; sin ellos, el perímetro de actuación como sector único, que sale de la propia
  rejilla de clases), las capas de polígonos, las superficies y las rejillas de cotas y de anclas
  se leen de las entradas congeladas, y el dominio y las semillas se forman con las mismas
  funciones que en el proyecto (``seeds.bounded_units``, ``seeds.assemble_units``);
- los perfiles, los taludes impuestos de los sectores, el espesor mínimo, la tolerancia de cara y
  el umbral de aviso son los valores congelados de los parámetros (``ReproduceRequest.params``);
  la operación con que se comparó el desmonte y el terraplén (D-25) y los sectores que tocó el
  dominio y los pendientes, los de sus ajustes;
- las salidas se escriben en la carpeta de trabajo: la rejilla de la envolvente (``env``) o la
  superficie de diseño y las cotas de las bermas (``srf``, ``brm``) como GeoTIFF del perfil del
  proyecto, y la tabla de bermas y el informe (``bmt``, ``rpt``) cada uno en su GeoPackage, con el
  papel con que los anotó la operación; y sus cifras, las mismas que se registraron.

De la cantera con dos superficies (spec 014, T19): :func:`reproduce_excavation_area` (el recinto)
y :func:`reproduce_quarry` (las dos superficies, con las piezas y el cálculo que comparte con el
proyecto, ``store.quarry_parts_units`` y ``store.quarry_compute_steps``; las capas, las rejillas
de las semillas y de las anclas se buscan por su nombre entre las entradas congeladas, con el
papel que tengan). De la transición con el terreno no afectado (spec 014, T28):
:func:`reproduce_edge_transition` (con el cálculo que comparte con el proyecto,
``store.transition_compute_steps``; la superficie de diseño y la de partida, por su papel). De
«Solo relleno…» (spec 014, T30): :func:`reproduce_fill_only` (con ``store.fill_only_compute_steps``;
la envolvente, la superficie de partida y las anclas por su papel y la capa de láminas por su
nombre). De la plataforma (spec 015, T14): :func:`reproduce_platform` (con el cálculo que comparte
con el proyecto, ``entity_store.platform_compute_steps``; la capa de plataformas, la de los ejes, la
superficie de partida y la de apoyo, por su papel, y los parámetros de la entidad, los congelados: **no**
los atributos de la capa). **Lo apoyado en las entidades** (spec 015, T23; RF-015-15, RF-009-11): las de la 013,
la 014 y la plataforma que se apoyan en una entidad devuelven también ``des.supported_m3``
(:func:`_support_figures`: la superficie y la tabla de la huella congeladas de cada entidad, con la partida y
el resultado; el mismo cálculo que el gancho de ``DesignWriter.commit``): sin ello, una cifra congelada sin
reproducir deja la operación como no reproducida. De la declaración de restricciones de las entidades (spec 015, T17):
:func:`reproduce_declare_constraints` (con el cálculo que comparte con el proyecto,
``entity_store.declared_rows_steps``; las tablas ``des_epr_`` congeladas de las entidades que recogió, por
el nombre de su dato, y los parámetros congelados de cada una; el decisor, la fecha de su decisión y la
versión, de los ajustes de la operación). **La capa de entidades** (``des.entity_layer``, spec 015, T30) **no se
reproduce**: su contenido incluye el estado de cada entidad (al día, obsoleta, descartada, «apoyo retirado»), que
deduce el grafo del proyecto y no se reproduce sin él; es una vista regenerable (como ``des.refit``, spec 010) y, en
una revisión congelada, se toma lo congelado (``core.versions.reproduce`` la da por no reproducible). **La detección de
acopios** (spec 016, T14; RF-016-10, RF-009-11): :func:`reproduce_stockpile_detect` (con el cálculo que comparte con el
proyecto, ``stockpile_store.detection_compute_steps`` sobre el mismo ``StockpileJob``: la capa de marcas, la superficie, las
bases propias y las máscaras congeladas por su nombre y su papel, y los parámetros de la entidad y el umbral de la huella
congelados, con las decisiones sobre los candidatos; las siete salidas, la base y el espesor de cada material **en el orden en
que las escribió** la operación, que es el que casa un papel repetido). **La retirada de un acopio** (spec 016, T20; RF-016-11, RF-009-11):
:func:`reproduce_stockpile_removal` (con el cálculo que comparte con el proyecto, ``supported_store.removal_compute_steps``
sobre el mismo ``RemovalJob``: la superficie de partida y las máscaras congeladas por su papel; la tabla de acopios, la base y la
superficie con que se detectó, las tres entradas ``removed_stockpile``, por el prefijo de su dato; los parámetros de la entidad y los del
proyecto congelados). **El cuerpo apoyado** (spec 016, T25; RF-016-20, RF-009-11): :func:`reproduce_body` (con el cálculo que
comparte con el proyecto, ``supported_store.body_compute_steps`` sobre el mismo ``BodyJob``: la huella, los datos de espesor, la
superficie conocida —y, «sobre una base», la de partida— y las máscaras congeladas por su nombre y su papel, y los parámetros de su
entidad congelados; el espesor disperso, la superficie o la base dispersa, la huella y el informe, y las cifras). **El otro tipo de la
016** (:func:`reproduce_buttress`; spec 016, T03) existe pero **sin comportamiento todavía**: dice qué tarea lo hace
(``NotImplementedError``); no hay ninguna operación de ese tipo que reproducir hasta que se crea. **La accesibilidad de las pistas** (spec 017, T17b;
RF-017-24, RF-017-25, RF-009-11): :func:`reproduce_road_access` (con el cálculo que comparte con el proyecto, ``access_store.access_compute_steps`` sobre el mismo ``AccessJob``
—``access_store.access_job``—: la superficie, la final, la capa de puntos de entrada, las rejillas de cotas de berma y las huellas de las plataformas, por su papel, las máscaras
congeladas —sus zonas «requiere acceso» y lo intocable— y los parámetros congelados de su entidad; la rejilla de lo alcanzable, las tres tablas y el informe, y las cifras). **La pista** (spec 017,
T22; RF-017-01 a RF-017-03, RF-015-02, RF-009-11): :func:`reproduce_road` (con el cálculo que comparte con el proyecto, ``road_store.road_compute_steps`` sobre el mismo ``RoadJob``: la capa de
origen, la partida y las máscaras congeladas —con **los pesos de «preferible no afectar»** de su informe—, los parámetros congelados de su entidad y del perfil —``road_store.frozen_profile``—, la
geometría de origen leída de lo congelado —``road_store.frozen_geometry``: **el eje por estaciones de la pista en cuyo eje está el origen** y la huella de la entidad de destino, que anotó la
operación como entradas— y **los otros diseños de la versión que difieren en su huella**, con los que se repite el aviso del informe; la superficie entera, la huella, el eje por estaciones y el
informe, y las cifras, con ``des.supported_m3`` de lo que rellena sobre otras entidades). **El otro tipo de la 017** (spec 017, T03; :func:`reproduce_road_propose`) existe igual, **sin
comportamiento todavía**: dice qué tarea lo hace (T27) con ``NotImplementedError``.

Con el mismo Geoblender y el mismo numpy, las salidas y las cifras salen **bit a bit**; con otros,
``core.versions.reproduce`` compara las cifras con ``figure_tolerance`` (10⁻⁹ relativo, plan
§5.2.3). Cerrar los pasos antes del final o un fallo dejan lo escrito en la carpeta de trabajo,
que borra quien la creó. Python puro con numpy (nivel 8).
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from collections.abc import Generator, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, closing, contextmanager
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import MappingProxyType

import numpy as np

from ..core.constraints import store as constraints_store
from ..core.constraints.declared import write_declared
from ..core.gpkg.base import create_attribute_table, create_base
from ..core.georef import CrsRef
from ..core.gpkg.connection import GpkgConnection
from ..core.paths import check_path_length
from ..core.project.model import Progress
from ..core.provenance.contract import ReproduceFunction
from ..core.provenance.figures import FigureSpec
from ..core.versions.reproduce import (
    FrozenInput,
    ReproducedOutput,
    ReproducedResult,
    ReproduceRequest,
)
from ..gis.geotiff import writer
from ..gis.geotiff.reader import read_geotiff, read_header, read_rows
from ..gis.grid import project_grid
from ..gis.masks import provenance as masks_declared
from ..gis.masks.access import MaskSet, MaskState
from ..gis.masks.combine import ClassBit
from ..gis.masks.compile import STEP_BUDGET_S
from ..gis.masks.store import PERIMETER_SECTOR_NAME, read_report, zone_runs_steps
from ..gis.raster import Raster
from ..gis.store import insert_rows, read_features
from ..gis.vector import FeatureLayer
from . import access_store, entities, entity_store, fronts, pipeline, provenance, quarry, removal, road_store, stockpile_store, store, supported_store
from .compose import admitted, admitted_in
from .model import BenchSense, BodySense, EnvelopeRequest, PlatformRequest, SeedKind, Surface
from .params import (
    ANTHROPIC_PRESENCE,
    PLATFORM_PARAMS,
    TOLERANCE_FACE,
    VERIFY_MIN_THICKNESS,
    WARNING_RATIO,
    PlatformParam,
    StockpileParam,
    entity_key,
)
from .buttress import ButtressJob
from .platform import PlatformJob
from .removal import RemovalJob
from .road_model import AccessCells, BermGrid, RoadJob, RoadMode, RouteParams
from .seeds import (
    SectorRef,
    SeedSet,
    assemble_units,
    bounded_units,
    check_source,
    domain_of,
    label_of,
    pace_progress,
)
from .surfaces import ProjectFrame, check_grid
from .thickness import BodyJob, body_window, no_data_error
from .zones import frozen_polygons, polygons_cells, sector_labels

__all__ = [
    "REPRODUCE",
    "reproduce_body",
    "reproduce_buttress",
    "reproduce_declare_constraints",
    "reproduce_design",
    "reproduce_edge_transition",
    "reproduce_envelope",
    "reproduce_excavation_area",
    "reproduce_fill_only",
    "reproduce_platform",
    "reproduce_quarry",
    "reproduce_road",
    "reproduce_road_access",
    "reproduce_road_propose",
    "reproduce_stockpile_detect",
    "reproduce_stockpile_removal",
]

_OBJ = "Reproducción del diseño"
_PHASE = "reproduce"
_MASKS_PREFIX = "masks_"
_READ_ROWS = 256
"""Las filas de la rejilla de clases que se leen en cada unidad."""


@contextmanager
def _open(path: Path) -> Iterator[sqlite3.Connection]:
    """Una conexión de lectura a ``path`` (una copia de las tablas congeladas)."""
    with GpkgConnection.open_read(Path(path)) as gpkg:
        yield gpkg.connection


class _Reading:
    """Lo que ``zone_runs_steps`` pide de un proyecto (``read()``), sobre un GeoPackage congelado."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> AbstractContextManager[sqlite3.Connection]:
        return _open(self.path)


def _drain[T](work: Generator[None, None, T]) -> T:
    while True:
        try:
            next(work)
        except StopIteration as stop:
            return stop.value  # type: ignore[no-any-return]


class _Frozen:
    """Lo congelado de una operación (``ReproduceRequest``), leído como lo leería el proyecto: la
    rejilla (la del registro del proyecto), las máscaras, los sectores, las capas y las
    superficies; y los valores de los parámetros."""

    def __init__(self, request: ReproduceRequest) -> None:
        self.request = request
        self.crs, self.vertical = request.references()
        self.grid = project_grid(request.record.window, float(request.record.grid_step_m))
        self.frame = ProjectFrame(self.grid, self.crs, self.vertical)
        self.values: dict[str, object] = {key: value for key, (value, _unit)
                                          in request.params.items()}

    def item(self, role: str) -> FrozenInput:
        return self.request.input(role)

    def raster(self, role: str, *, what: str) -> Raster:
        """La rejilla congelada con el papel ``role``, comparada con la del proyecto antes de
        usarla (``des.surface_mismatch``, RF-013-16)."""
        item = self.item(role)
        source = read_geotiff(Path(item.files["main"]), max_cells=sys.maxsize)
        found = Raster(source.grid, source.values, source.declared_crs or self.crs,
                       source.declared_vertical or self.vertical)
        check_grid(found, self.frame, role=what, name=item.name)
        return found

    def masks(self) -> MaskSet:
        """Las máscaras congeladas: la rejilla de clases y las zonas (``MaskSet``)."""
        classes_role = _MASKS_PREFIX + masks_declared.FAMILIES_BY_CODE[masks_declared.CLASSES].role
        zones_role = _MASKS_PREFIX + masks_declared.FAMILIES_BY_CODE[masks_declared.ZONES].role
        path = Path(self.item(classes_role).files["main"])
        classes = np.empty(self.grid.shape, dtype=np.uint16)
        with path.open("rb") as stream:
            header = read_header(stream, path.stat().st_size, path.name)
            if (header.height, header.width) != self.grid.shape:
                raise ValueError("la rejilla de clases congelada no es la del proyecto")
            for top in range(0, self.grid.nrows, _READ_ROWS):
                stop = min(top + _READ_ROWS, self.grid.nrows)
                values = read_rows(stream, header, top, stop)
                classes[top:stop] = np.where(np.isfinite(values), values, 0.0).astype(np.uint16)
        zones_item = self.item(zones_role)
        reading = _Reading(Path(zones_item.files["main"]))
        zones = _drain(zone_runs_steps(reading, str(zones_item.settings["layer"])))  # type: ignore[arg-type]
        return MaskSet(self.grid, "", "", MaskState.CURRENT, (), classes, (),
                       MappingProxyType(zones), ctypes=MappingProxyType(self._ctypes()))

    def _ctypes(self) -> dict[str, str]:
        """El tipo de cada restricción con zona, del informe congelado de las máscaras (como
        ``gis.masks.access.load_masks``): con él la cantera halla las zonas a sostener (T19)."""
        role = _MASKS_PREFIX + masks_declared.FAMILIES_BY_CODE[masks_declared.REPORT].role
        found = [item for item in self.request.inputs if item.role == role]
        if not found:
            return {}
        with _open(Path(found[0].files["main"])) as conn:
            report = read_report(conn, str(found[0].settings["layer"]))
        return {code: str(note) for code, quantity, _value, _unit, note in report
                if quantity == "zone_area" and note is not None}

    def weights(self) -> dict[str, float]:
        """El peso de cada zona «preferible no afectar» (código → peso), del informe congelado de las máscaras (como ``gis.masks.access.load_masks``): con él la pista cuenta la afección y la ruta
        evita esas zonas (spec 017, T22; RF-017-06). Vacío si no hay informe congelado."""
        role = _MASKS_PREFIX + masks_declared.FAMILIES_BY_CODE[masks_declared.REPORT].role
        found = [item for item in self.request.inputs if item.role == role]
        if not found:
            return {}
        with _open(Path(found[0].files["main"])) as conn:
            report = read_report(conn, str(found[0].settings["layer"]))
        return {code: float(value) for code, quantity, value, _unit, _note in report if quantity == "weight" and value is not None}

    def sector_layout(self, masks: MaskSet) -> tuple[tuple[SectorRef, ...], np.ndarray]:
        """Los sectores de búsqueda congelados y la etiqueta de cada celda; sin sectores
        declarados, el perímetro de actuación (la rejilla de clases) como sector único."""
        items = [item for item in self.request.inputs if item.role == provenance.SECTORS_ROLE]
        if items:
            item = items[0]
            if item.settings.get("layer") != constraints_store.SECTOR_TABLE:
                raise ValueError(f"los sectores congelados están en «{item.settings.get('layer')}»"
                                 f", no en «{constraints_store.SECTOR_TABLE}»")
            with _open(Path(item.files["main"])) as conn:
                found = constraints_store.read_sectors(conn)
            if found:
                return (tuple(SectorRef(sector.code, sector.name) for sector in found),
                        sector_labels(found, self.grid))
        perimeter = (masks.classes & np.uint16(int(ClassBit.PERIMETER))) != 0
        return (SectorRef("", PERIMETER_SECTOR_NAME),), perimeter.astype(np.int16)

    def layer_cells(self, name: str) -> np.ndarray:
        """Las celdas de la capa congelada ``name`` (por el nombre de su dato)."""
        for item in self.request.inputs:
            if item.name == name and item.role in (provenance.ZONE_LAYER_ROLE,
                                                   provenance.DOMAIN_LAYER_ROLE):
                with _open(Path(item.files["main"])) as conn:
                    polygons = frozen_polygons(conn, str(item.settings["layer"]), name)
                return polygons_cells(polygons, self.grid)
        raise ValueError(f"la capa «{name}» no está entre las entradas congeladas")

    def named(self, name: str) -> FrozenInput:
        """La entrada congelada del dato ``name``, con el papel que sea (la cantera lee un mismo
        dato con varios papeles: la superficie de partida y la rejilla de anclas…)."""
        for item in self.request.inputs:
            if item.name == name:
                return item
        raise ValueError(f"«{name}» no está entre las entradas congeladas")

    def named_raster(self, name: str, *, what: str) -> Raster:
        """La rejilla congelada del dato ``name``, comparada con la del proyecto antes de usarla
        (como :meth:`raster`)."""
        item = self.named(name)
        source = read_geotiff(Path(item.files["main"]), max_cells=sys.maxsize)
        found = Raster(source.grid, source.values, source.declared_crs or self.crs,
                       source.declared_vertical or self.vertical)
        check_grid(found, self.frame, role=what, name=item.name)
        return found

    def features(self, name: str) -> FeatureLayer:
        """La capa de entidades congelada ``name`` (sus geometrías y sus campos)."""
        item = self.named(name)
        with _open(Path(item.files["main"])) as conn:
            return read_features(conn, str(item.settings["layer"]))

    def cells_named(self, name: str) -> np.ndarray:
        """Las celdas de la capa de polígonos congelada ``name``, con el papel que sea."""
        item = self.named(name)
        with _open(Path(item.files["main"])) as conn:
            polygons = frozen_polygons(conn, str(item.settings["layer"]), name)
        return polygons_cells(polygons, self.grid)


def _paced[T](work: Generator[None, None, T], budget_s: float, text: str
              ) -> Generator[Progress, None, T]:
    """Las unidades de ``work`` como pasos de ``budget_s`` como mucho; devuelve su resultado."""
    result: T = yield from pipeline.forward(pace_progress(
        work, budget_s, phase=_PHASE, running=text, finished=text))
    return result


def _grid_output(request: ReproduceRequest, family: str, raster: Raster, budget_s: float, *, part: str | None = None
                 ) -> Generator[Progress, None, ReproducedOutput]:
    """Escribe ``raster`` como la salida ``family`` de la operación, en la carpeta de trabajo. ``part``: una familia con
    varias rejillas (la base de cada material de una detección) las distingue en el nombre del fichero."""
    found = provenance.FAMILIES_BY_CODE[family]
    suffix = "" if part is None else f"_{part}"
    path = Path(request.workdir) / f"{found.role}_{family}{suffix}.tif"  # dos superficies, un papel
    temporary = path.with_name(path.name + ".tmp")
    check_path_length(temporary, obj=_OBJ)
    steps = writer.write_steps(raster, path, profile="project", temporary=temporary,
                               replace=False)
    with closing(steps):
        yield from _paced(steps, budget_s, f"Escribiendo {found.label}…")  # type: ignore[arg-type]
    os.replace(temporary, path)
    return ReproducedOutput(found.role, found.reader, {"main": path})


def _table_output(request: ReproduceRequest, family: str, rows: list[tuple[object, ...]],
                  crs: CrsRef) -> ReproducedOutput:
    """Escribe ``rows`` como la tabla ``family`` de la operación, en su GeoPackage de la carpeta
    de trabajo, con las columnas de su tipo (``store.columns_of``)."""
    found = provenance.FAMILIES_BY_CODE[family]
    name = str(request.settings.get("name", ""))
    table = provenance.dataset_locator(family, name, "V01")
    path = Path(request.workdir) / f"{found.role}.gpkg"
    check_path_length(path, obj=_OBJ)
    columns = store.columns_of(request.op_type, family)
    with GpkgConnection.open_write(path, create=True) as gpkg, gpkg.transaction() as conn:
        create_base(conn, crs)
        create_attribute_table(conn, table, columns, f"{found.label} {name}",
                               f"{found.label} «{name}» reproducido, de Geoblender")
        insert_rows(conn, table, tuple(column.name for column in columns), rows)
    return ReproducedOutput(found.role, found.reader, {"main": path}, {"layer": table})


def _support_figures(frozen: _Frozen, results: Sequence[np.ndarray], start: np.ndarray
                     ) -> tuple[FigureSpec, ...]:
    """Las cifras ``des.supported_m3`` de la operación que se reproduce (spec 015, T23; RF-015-15, RF-009-11):
    lo que apoyan sus superficies ``results`` (desde ``start``) sobre cada entidad cuya superficie
    (``supported_on``) y cuya huella (``support_footprint``, la tabla ``des_epr_`` de la entidad) consumió, con
    lo **congelado** y el espesor mínimo congelado: el mismo cálculo que el gancho de ``DesignWriter.commit``
    (``entities.detect_supports``), con el mismo ``máx(partida, entidad)``, sin el proyecto. Una entrada
    ``supported_on`` que no es la superficie de una entidad (la de apoyo de una plataforma puede ser
    cualquiera) o sin la tabla de su huella no da cifra. Sin entidades, ninguna.

    **Los acopios** (spec 016, T15; RF-016-14, P-1): la superficie con que se detectó una detección (``des_stp_``) y su tabla de acopios
    (``des_stk_``) dan **un acopio por cada fila** de la tabla (``STK-001#clave``, el código de la detección lo dice la tabla), todos
    sobre la misma superficie; y, como en el gancho, solo salen los acopios sobre los que se rellena (no se declaran los demás)."""
    inputs = frozen.request.inputs
    held = [item for item in inputs if item.role == provenance.SUPPORTED_ON_ROLE]
    if not held:
        return ()
    surface_prefix = provenance.FAMILIES_BY_CODE[provenance.ENTITY_SURFACE_GRID].prefix
    table_prefix = provenance.FAMILIES_BY_CODE[provenance.ENTITY_TABLE].prefix
    detected_prefix = provenance.FAMILIES_BY_CODE[provenance.STOCKPILE_SURFACE_GRID].prefix
    stockpiles_prefix = provenance.FAMILIES_BY_CODE[provenance.STOCKPILES_TABLE].prefix
    tables = {item.name: item for item in inputs if item.role == provenance.SUPPORT_FOOTPRINT_ROLE}
    surfaces: dict[str, np.ndarray] = {}
    cells: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for item in held:
        if item.name.startswith(detected_prefix):  # lo apoyado en un acopio de una detección
            stockpiles = tables.get(stockpiles_prefix + item.name.removeprefix(detected_prefix))
            if stockpiles is None:
                continue
            with _open(Path(stockpiles.files["main"])) as conn:
                code, found_stockpiles = entity_store.read_stockpile_footprints(conn, str(stockpiles.settings["layer"]))
            detected = frozen.named_raster(item.name, what="superficie de apoyo").values
            for key, runs in found_stockpiles.items():
                ref = provenance.support_ref(code, key)
                surfaces[ref] = detected
                cells[ref] = entities.runs_cells(runs)
            continue
        table = tables.get(table_prefix + item.name.removeprefix(surface_prefix))
        if not item.name.startswith(surface_prefix) or table is None:
            continue
        with _open(Path(table.files["main"])) as conn:
            found = entity_store.read_entity_footprint(conn, str(table.settings["layer"]))
        surfaces[found.code] = frozen.named_raster(item.name, what="superficie de apoyo").values
        cells[found.code] = entities.runs_cells(found.runs)
    if not cells:
        return ()
    thickness = store.number(frozen.values, VERIFY_MIN_THICKNESS)
    area = float(frozen.grid.cell_area)
    best = entities.strongest(
        item for array in results for item in entities.detect_supports(
            array, start, surfaces, cells, thickness, area,
            declared=sorted(ref for ref in cells if provenance.SUPPORT_REF_SEPARATOR not in ref)))
    return provenance.supported_figures(str(frozen.request.settings.get("name", "")),
                                        {item.ref: item.volume_m3 for item in best})


def _check(request: object, op_type: str) -> ReproduceRequest:
    if not isinstance(request, ReproduceRequest):
        raise TypeError(f"se reproduce una ReproduceRequest, no {request!r}")
    if request.op_type != op_type:
        raise ValueError(f"esta función reproduce {op_type}, no «{request.op_type}»")
    return request


# --- La envolvente ---------------------------------------------------------------------------


def reproduce_envelope(request: ReproduceRequest, *, budget_s: float = STEP_BUDGET_S
                       ) -> Iterator[Progress]:
    """Reproduce ``des.envelope`` con sus entradas y sus parámetros congelados y sus ajustes, sin
    el proyecto: sus pasos y, el último, el ``ReproducedResult`` con la rejilla de la envolvente y
    sus cifras."""
    return _reproduce_envelope(_check(request, provenance.ENVELOPE), budget_s)


def _seed_units(frozen: _Frozen, envelope: EnvelopeRequest, masks: MaskSet,
                refs: Sequence[SectorRef], labels: np.ndarray) -> Generator[None, None, SeedSet]:
    """Las unidades del dominio y de las semillas congelados (las de ``seeds.seed_units``)."""
    source = envelope.seeds
    check_source(source)
    wanted = [label_of(code, refs) for code in envelope.domain.sectors]
    yield
    mask = yield from bounded_units(envelope.domain, masks, labels, wanted, frozen.layer_cells)
    domain = domain_of(mask, labels, refs, masks.grid.cell_area)
    role = (provenance.SURFACE_ROLE if SeedKind(source.kind) is SeedKind.SURFACE
            else provenance.SEEDS_GRID_ROLE)
    found = yield from assemble_units(
        source, masks, domain, layer=frozen.layer_cells,
        surface=lambda _name, what: frozen.raster(role, what=what).values)
    return found


def _reproduce_envelope(request: ReproduceRequest, budget_s: float) -> Iterator[Progress]:
    frozen = _Frozen(request)
    envelope = provenance.envelope_request(request.settings)
    yield Progress(_PHASE, 0, 1, "Leyendo lo congelado…")
    masks = frozen.masks()
    refs, labels = frozen.sector_layout(masks)
    seeds = yield from _paced(_seed_units(frozen, envelope, masks, refs, labels), budget_s,
                              "Preparando las semillas…")
    slope = pipeline.envelope_slope(envelope, refs, labels, frozen.values)
    start = None
    if pipeline.uses_start_surface(envelope):
        start = frozen.raster(provenance.SURFACE_ROLE, what="semillas").values
    job = pipeline.EnvelopeJob(envelope, seeds, slope, start,
                               store.number(frozen.values, VERIFY_MIN_THICKNESS))
    outcome: pipeline.EnvelopeOutcome = yield from pipeline.forward(
        pipeline.envelope_compute_steps(job, budget_s=budget_s))
    raster = Raster(seeds.geometry, outcome.grid, frozen.crs, frozen.vertical)
    output = yield from _grid_output(request, provenance.ENVELOPE_GRID, raster, budget_s)
    yield Progress(_PHASE, 1, 1, "Envolvente reproducida",
                   result=ReproducedResult((output,), outcome.figures))


# --- El escalonado ---------------------------------------------------------------------------


def reproduce_design(request: ReproduceRequest, *, budget_s: float = STEP_BUDGET_S
                     ) -> Iterator[Progress]:
    """Reproduce ``des.stepped_design`` con sus entradas y sus parámetros congelados y sus ajustes,
    sin el proyecto: sus pasos y, el último, el ``ReproducedResult`` con la superficie de diseño,
    las cotas y la tabla de las bermas, el informe y sus cifras."""
    return _reproduce_design(_check(request, provenance.STEPPED), budget_s)


def _reproduce_design(request: ReproduceRequest, budget_s: float) -> Iterator[Progress]:
    frozen = _Frozen(request)
    design = provenance.design_request(request.settings)
    yield Progress(_PHASE, 0, 1, "Leyendo lo congelado…")
    masks = frozen.masks()
    refs, labels = frozen.sector_layout(masks)
    envelope = frozen.raster(provenance.ENVELOPE_ROLE, what="envolvente")
    start = frozen.raster(provenance.SURFACE_ROLE, what="superficie de partida")
    anchors = None
    if design.anchor_grid is not None:
        anchors = frozen.raster(provenance.ANCHORS_ROLE, what="anclas").values
    profiles = pipeline.bench_profiles(
        frozen.values, [design.base_profile, *(profile for _sector, profile in
                                               design.sector_profiles)])
    waiting = set(provenance.settings_pending(request.settings))
    job = pipeline.DesignJob(
        design, start.grid, start.values, envelope.values, masks, refs, labels,
        pipeline.imposed_from(frozen.values, refs), profiles, anchors,
        store.number(frozen.values, VERIFY_MIN_THICKNESS),
        store.number(frozen.values, TOLERANCE_FACE), store.number(frozen.values, WARNING_RATIO),
        pipeline.previous_of(provenance.settings_previous(request.settings)),
        tuple(ref.name for ref in refs if ref.code in waiting))
    outcome: pipeline.DesignOutcome = yield from pipeline.forward(
        pipeline.design_compute_steps(job, budget_s=budget_s))
    geometry, crs, vertical = start.grid, frozen.crs, frozen.vertical
    outputs = []
    for family, grid in ((provenance.DESIGN_GRID, outcome.design),
                         (provenance.BERMS_GRID, outcome.berms.grid)):
        outputs.append((yield from _grid_output(
            request, family, Raster(geometry, grid, crs, vertical), budget_s)))
    outputs.append(_table_output(request, provenance.BERM_TABLE, store.berm_rows(outcome.berms),
                                 crs))
    outputs.append(_table_output(
        request, provenance.REPORT_TABLE,
        store.report_rows(outcome.report, unassigned_area_m2=outcome.unassigned_area_m2), crs))
    yield Progress(_PHASE, 1, 1, "Escalonado reproducido",
                   result=ReproducedResult(tuple(outputs), (
                       *outcome.figures, *_support_figures(frozen, [outcome.design], start.values))))


# --- La cantera con dos superficies y su recinto (spec 014, T19) -------------------------------


def reproduce_excavation_area(request: ReproduceRequest, *, budget_s: float = STEP_BUDGET_S
                              ) -> Iterator[Progress]:
    """Reproduce ``des.excavation_area`` (spec 014, T19; RF-014-01) con su superficie de partida y
    sus máscaras congeladas y sus ajustes, sin el proyecto: sus pasos y, el último, el
    ``ReproducedResult`` con la rejilla del recinto y su cifra."""
    return _reproduce_area(_check(request, provenance.EXCAVATION_AREA), budget_s)


def _reproduce_area(request: ReproduceRequest, budget_s: float) -> Iterator[Progress]:
    frozen = _Frozen(request)
    name, _surface = provenance.excavation_area_start(request.settings)
    yield Progress(_PHASE, 0, 1, "Leyendo lo congelado…")
    masks = frozen.masks()
    start = frozen.raster(provenance.SURFACE_ROLE, what="superficie de partida")
    area = quarry.excavation_area(masks, start.values)
    outcome = quarry.area_outcome(name, area, start.grid)
    raster = Raster(start.grid, outcome.grid, frozen.crs, frozen.vertical)
    output = yield from _grid_output(request, provenance.EXCAVATION_AREA_GRID, raster, budget_s)
    yield Progress(_PHASE, 1, 1, "Recinto reproducido",
                   result=ReproducedResult((output,), outcome.figures))


def reproduce_quarry(request: ReproduceRequest, *, budget_s: float = STEP_BUDGET_S
                     ) -> Iterator[Progress]:
    """Reproduce ``des.quarry`` (spec 014, T19; RF-014-29) con sus entradas congeladas (la
    superficie de partida, las máscaras, los sectores, las capas de fondos, corredores, zonas a
    conservar, relleno y «explotación hasta la final», y lo que leen las semillas y las anclas de
    cada lado), sus parámetros congelados y sus ajustes, sin el proyecto: el mismo cálculo que el
    proyecto (``store.quarry_parts_units`` y ``store.quarry_compute_steps``). Sus pasos y, el
    último, el ``ReproducedResult`` con las cinco rejillas, las dos tablas y sus cifras."""
    return _reproduce_quarry(_check(request, provenance.QUARRY), budget_s)


def _reproduce_quarry(request: ReproduceRequest, budget_s: float) -> Iterator[Progress]:
    frozen = _Frozen(request)
    wanted = provenance.quarry_request(request.settings)
    yield Progress(_PHASE, 0, 1, "Leyendo lo congelado…")
    masks = frozen.masks()
    refs, labels = frozen.sector_layout(masks)
    start = frozen.raster(provenance.SURFACE_ROLE, what="superficie de partida")
    domain = store.quarry_domain(masks, start.values, refs, labels)
    parts = yield from _paced(store.quarry_parts_units(
        wanted, masks, start, domain, features=frozen.features, layer=frozen.cells_named,
        surface=lambda name, what: frozen.named_raster(name, what=what).values),
        budget_s, "Leyendo las capas de la cantera…")
    waiting = set(provenance.settings_pending(request.settings))
    calculated: store.QuarryCalculated = yield from store.quarry_compute_steps(
        wanted, masks, parts, frozen.values,
        pending=tuple(ref.name for ref in refs if ref.code in waiting),
        previous={side: provenance.settings_previous(request.settings, side) for side in Surface},
        budget_s=budget_s)
    outcome = calculated.outcome
    outputs = []
    surfaces = []
    for family, grid, _what in store.quarry_grids(outcome):
        outputs.append((yield from _grid_output(
            request, family, Raster(start.grid, grid, frozen.crs, frozen.vertical), budget_s)))
        if provenance.FAMILIES_BY_CODE[family].role == provenance.DESIGN_SURFACE_ROLE:
            surfaces.append(grid)
    outputs.append(_table_output(request, provenance.BERM_TABLE,
                                 store.quarry_berm_rows(outcome), frozen.crs))
    outputs.append(_table_output(request, provenance.QUARRY_REPORT_TABLE,
                                 store.quarry_report_rows(outcome, calculated.notices),
                                 frozen.crs))
    yield Progress(_PHASE, 1, 1, "Cantera reproducida",
                   result=ReproducedResult(tuple(outputs), (
                       *outcome.figures, *_support_figures(frozen, surfaces, start.values))))


# --- La transición con el terreno no afectado (spec 014, T28) ----------------------------------


def reproduce_edge_transition(request: ReproduceRequest, *, budget_s: float = STEP_BUDGET_S
                              ) -> Iterator[Progress]:
    """Reproduce ``des.edge_transition`` (spec 014, T28; RF-014-19 a RF-014-21, RF-014-29) con su
    superficie de diseño, su superficie de partida y sus máscaras congeladas, sus parámetros
    congelados y sus ajustes, sin el proyecto: el mismo cálculo que el proyecto
    (``store.transition_compute_steps``). Sus pasos y, el último, el ``ReproducedResult`` con la
    superficie con la transición, el informe del salto creado y sus cifras."""
    return _reproduce_transition(_check(request, provenance.EDGE_TRANSITION), budget_s)


def _reproduce_transition(request: ReproduceRequest, budget_s: float) -> Iterator[Progress]:
    frozen = _Frozen(request)
    name, _surface, _start = provenance.transition_start(request.settings)
    yield Progress(_PHASE, 0, 1, "Leyendo lo congelado…")
    masks = frozen.masks()
    surface = frozen.raster(provenance.DESIGN_SURFACE_ROLE, what="superficie de diseño")
    start = frozen.raster(provenance.SURFACE_ROLE, what="superficie de partida")
    outcome = yield from store.transition_compute_steps(name, surface.values, start.values,
                                                        masks, frozen.values,
                                                        budget_s=budget_s)
    raster = Raster(start.grid, outcome.grid, frozen.crs, frozen.vertical)
    output = yield from _grid_output(request, provenance.TRANSITION_GRID, raster, budget_s)
    report = _table_output(request, provenance.EDGE_REPORT_TABLE,
                           store.edge_report_rows(outcome), frozen.crs)
    yield Progress(_PHASE, 1, 1, "Transición reproducida",
                   result=ReproducedResult((output, report), (
                       *outcome.figures, *_support_figures(frozen, [outcome.grid], start.values))))


# --- Solo relleno (spec 014, T30) ----------------------------------------------------------------


def reproduce_fill_only(request: ReproduceRequest, *, budget_s: float = STEP_BUDGET_S
                        ) -> Iterator[Progress]:
    """Reproduce ``des.fill_only`` (spec 014, T30; RF-014-22 a RF-014-25, RF-014-29) con sus
    entradas congeladas (la envolvente, la superficie de partida, la rejilla de anclas, la capa de
    láminas de agua, las máscaras y los sectores), sus parámetros congelados y sus ajustes, sin el
    proyecto: el mismo cálculo que el proyecto (``store.fill_only_compute_steps``; los intocables,
    los de las máscaras congeladas). Sus pasos y, el último, el ``ReproducedResult`` con la
    superficie, el informe y sus cifras."""
    return _reproduce_fill_only(_check(request, provenance.FILL_ONLY), budget_s)


def _reproduce_fill_only(request: ReproduceRequest, budget_s: float) -> Iterator[Progress]:
    frozen = _Frozen(request)
    wanted = provenance.fill_only_request(request.settings)
    yield Progress(_PHASE, 0, 1, "Leyendo lo congelado…")
    masks = frozen.masks()
    refs, labels = frozen.sector_layout(masks)
    envelope = frozen.raster(provenance.ENVELOPE_ROLE, what="envolvente")
    start = frozen.raster(provenance.SURFACE_ROLE, what="superficie de partida")
    anchors = None
    if wanted.anchor_grid is not None:
        anchors = frozen.raster(provenance.ANCHORS_ROLE, what="anclas").values
    water = None
    if wanted.water is not None:
        water = fronts.water_sheets(frozen.features(wanted.water.layer), wanted.water,
                                    masks.grid)
    parts = store.FillOnlyParts(envelope, start, anchors, tuple(refs), labels, water,
                                fronts.untouchable_zones(masks))
    waiting = set(provenance.settings_pending(request.settings))
    outcome = yield from store.fill_only_compute_steps(
        wanted, masks, parts, frozen.values,
        pending=tuple(ref.name for ref in refs if ref.code in waiting),
        previous=provenance.settings_previous(request.settings), budget_s=budget_s)
    surface = yield from _grid_output(
        request, provenance.DESIGN_GRID,
        Raster(start.grid, outcome.surface, frozen.crs, frozen.vertical), budget_s)
    report = _table_output(request, provenance.REPORT_TABLE, store.fill_only_report_rows(outcome),
                           frozen.crs)
    yield Progress(_PHASE, 1, 1, "Diseño «solo relleno» reproducido",
                   result=ReproducedResult((surface, report), (
                       *outcome.figures, *_support_figures(frozen, [outcome.surface], start.values))))


# --- La plataforma (spec 015, T14) --------------------------------------------------------------


def reproduce_platform(request: ReproduceRequest, *, budget_s: float = STEP_BUDGET_S
                       ) -> Iterator[Progress]:
    """Reproduce ``des.platform`` (spec 015, T14; RF-015-02, RF-015-04, RF-009-11) con su capa de
    plataformas y, si un polígono enlaza su eje, la capa de ejes, su superficie de partida, su apoyo y sus
    máscaras congelados y los parámetros congelados de su entidad (``des.platform.{e}.*``: la capa, la
    geometría, la partida, la cota inicial, la pendiente, el ancho, el modo y el borde; **no** los
    atributos de la capa, que se copiaron a ellos al crearla, P-3) y del proyecto (el espesor mínimo, la
    tolerancia de cara, el umbral de magnitud y el salto creado), con los ajustes de su operación (el
    nombre, el código y los campos), **sin el proyecto**: el mismo cálculo
    (``entity_store.platform_compute_steps``). Sus pasos y, el último, el ``ReproducedResult`` con la
    superficie (``des_psf_``), la tabla de la entidad (``des_epr_``), su informe (``des_prp_``) y sus
    cifras.

    El informe no lleva lo que depende de lo que la operación no consume (la revisión congelada con que se
    comparó la magnitud y la otra superficie de una cantera), así que sale sin ello. Lo que no es una
    ``ReproduceRequest`` es ``TypeError``; una de otro tipo, ``ValueError``."""
    return _reproduce_platform(_check(request, provenance.PLATFORM), budget_s)


def _support_dataset(request: ReproduceRequest, asked: PlatformRequest) -> str | None:
    """El nombre del dato de la superficie de apoyo de la plataforma que se reproduce: ``None`` sin apoyo;
    el nombre de la superficie si el parámetro es uno; y si es ``entity:<código>``, el primero de sus
    entradas ``supported_on`` (la de la petición se anota antes que las que añade el cálculo al crear, y la
    008 las guarda por orden de registro)."""
    if asked.support is None:
        return None
    if entities.ref_code(asked.support) is None:
        return asked.support
    found = [item.name for item in request.inputs if item.role == provenance.SUPPORTED_ON_ROLE]
    if not found:
        raise ValueError(f"la plataforma «{asked.name}» se apoya en {asked.support!r} y su operación no "
                         "anotó ninguna superficie «supported_on»")
    return found[0]


def _reproduce_platform(request: ReproduceRequest, budget_s: float) -> Iterator[Progress]:
    frozen = _Frozen(request)
    code = provenance.platform_code(request.settings)
    kept = provenance.platform_values(code, frozen.values)
    asked = provenance.platform_request(request.settings, kept)
    yield Progress(_PHASE, 0, 1, "Leyendo lo congelado…")
    masks = frozen.masks()
    start_item = frozen.item(provenance.SURFACE_ROLE)
    start = frozen.raster(provenance.SURFACE_ROLE, what="superficie de partida")
    cut, fill = admitted(masks, BenchSense.CUT), admitted(masks, BenchSense.FILL)
    removed = None
    if asked.stockpile is not None:
        # RF-016-16 (T21): la plataforma que retira un acopio «como plataforma»: su geometría es la huella del acopio que consumió (su tabla, su
        # base y la superficie con que se detectó, congeladas) y su cota y su pendiente, las de su plano; nada de una capa
        row, removed, detection = _frozen_removed(request, frozen, asked.stockpile, asked.name)
        flat = removal.platform_of_stockpile(removed, frozen.grid)
        fid = int(row["source_fid"] or 0)
        asked = replace(asked, fields=replace(asked.fields, layer=str(row["layer"] or detection)), feature=str(fid))
        geometry = flat.geometry
        copied = {PlatformParam.START_LEVEL: flat.start_level_m, PlatformParam.GRADIENT: flat.gradient_pct}
        values = entity_store.entity_values(asked, code, fid, copied, line=False)
        whole = (slice(0, frozen.grid.nrows), slice(0, frozen.grid.ncols))
        cut = cut | entity_store._stockpile_cut(removed, masks, whole)
    else:
        layer = frozen.features(asked.layer)
        index = entity_store.feature_index(layer, asked, code)
        geometry = entity_store.read_geometry(frozen.features, layer, index, asked)
        copied = {param: store.number(kept, param.value)
                  for param, attribute in entity_store.LAYER_FIELDS.items()
                  if getattr(asked.fields, attribute) is not None}
        fid = layer.fids[index]
        values = entity_store.entity_values(asked, code, fid, copied, line=layer.kind == "line")
    job = PlatformJob(asked, code, masks.grid, start.values, geometry, values, cut, fill)
    common = {key: store.number(frozen.values, key) for key in provenance.PLATFORM_COMMON_PARAMS}
    outcome = yield from entity_store.platform_compute_steps(
        job, common, operation=asked.name, removed=removed, budget_s=budget_s)
    surface = np.array(job.start, dtype=np.float64, copy=True)
    surface[outcome.footprint.window] = outcome.result
    raster = Raster(job.grid, surface, frozen.crs, frozen.vertical)
    made = yield from _grid_output(request, provenance.ENTITY_SURFACE_GRID, raster, budget_s)
    entity = entity_store.platform_entity_rows(
        job, outcome, fid=fid, start_surface=start_item.name,
        support_surface=_support_dataset(request, asked))
    table = _table_output(request, provenance.ENTITY_TABLE, entity, frozen.crs)
    report = _table_output(request, provenance.ENTITY_REPORT_TABLE,
                           entity_store.platform_report_rows(outcome), frozen.crs)
    yield Progress(_PHASE, 1, 1, "Plataforma reproducida",
                   result=ReproducedResult((made, table, report), (
                       *outcome.figures, *_support_figures(frozen, [surface], start.values))))


def reproduce_declare_constraints(request: ReproduceRequest, *, budget_s: float = STEP_BUDGET_S
                                  ) -> Iterator[Progress]:
    """Reproduce ``des.declare_constraints`` (spec 015, T17; RF-015-10, RF-015-02, RF-009-11) con las tablas
    ``des_epr_`` congeladas de las entidades que recogió (papel ``entity``, por el nombre de su dato), los
    parámetros congelados de cada una (``des.platform.{e}.protect``, ``mode``, ``guard_m``, ``reason`` y
    ``name``) y los ajustes de su operación (las entidades, la versión y, de las que declaran, su decisor y
    la fecha de su decisión), **sin el proyecto**: el mismo cálculo (``entity_store.declared_rows_steps``).
    Sus pasos y, el último, el ``ReproducedResult`` con la tabla de las declaradas (``des_decl_``, una capa
    de polígonos con las mismas filas, los mismos bytes y el mismo hash) y su cifra. Lo que no es una
    ``ReproduceRequest`` es ``TypeError``; una de otro tipo, ``ValueError``."""
    return _reproduce_declaration(_check(request, provenance.DECLARE_CONSTRAINTS), budget_s)


def _frozen_source(frozen: _Frozen, code: str, calc_name: str, decisions: Mapping[str, tuple[str, date]]
                   ) -> entity_store.DeclaredSource:
    """Lo que la declaración sabe de la entidad ``code`` según lo congelado: su tabla ``des_epr_`` (el dato
    ``des_epr_<calc_name>``), sus parámetros congelados y la decisión de los ajustes."""
    item = frozen.named(provenance.dataset_name(provenance.ENTITY_TABLE, calc_name))
    with _open(Path(item.files["main"])) as conn:
        found = entity_store.read_entity_footprint(conn, str(item.settings["layer"]))
    if found.code != code:
        raise ValueError(f"el dato congelado «{item.name}» es de la entidad {found.code}, no de {code}")

    def value(param: PlatformParam) -> object:
        return frozen.values.get(entity_key(code, param))

    name = value(PlatformParam.NAME)
    protect = value(PlatformParam.PROTECT)
    guard, reason, mode = value(PlatformParam.GUARD), value(PlatformParam.REASON), value(PlatformParam.MODE)
    who, when = decisions.get(code, (None, None))
    return entity_store.DeclaredSource(
        code=code, kind=entities.EntityKind(found.kind), name=str(name or found.name),
        calc_name=calc_name, layer=found.layer, protect=bool(protect),
        mode=str(PLATFORM_PARAMS[PlatformParam.MODE.value].default if mode is None else mode),
        guard_m=None if guard is None else float(guard),  # type: ignore[arg-type]
        reason=(reason.strip() or None) if isinstance(reason, str) else None, decided_by=who,
        decided_on=when, runs=found.runs, zone=found.zone)


def _declared_output(request: ReproduceRequest, rows: Sequence[object], crs: CrsRef
                     ) -> ReproducedOutput:
    """Escribe ``rows`` (``DeclaredConstraint``) como la tabla de las declaradas de la operación, en su
    GeoPackage de la carpeta de trabajo (``write_declared``: la misma capa que escribe el proyecto)."""
    found = provenance.FAMILIES_BY_CODE[provenance.DECLARED_TABLE]
    table = provenance.dataset_locator(provenance.DECLARED_TABLE, "", "V01")
    path = Path(request.workdir) / f"{found.role}.gpkg"
    check_path_length(path, obj=_OBJ)
    with GpkgConnection.open_write(path, create=True) as gpkg, gpkg.transaction() as conn:
        create_base(conn, crs)
        write_declared(conn, table, rows, srs_id=crs.epsg)  # type: ignore[arg-type]
    return ReproducedOutput(found.role, found.reader, {"main": path}, {"layer": table})


def _reproduce_declaration(request: ReproduceRequest, budget_s: float) -> Iterator[Progress]:
    frozen = _Frozen(request)
    version_uid = provenance.settings_version(request.settings)
    if version_uid is None:
        raise ValueError("los ajustes de la declaración no anotan su versión: sin ella no se puede "
                         "reproducir el uid de sus restricciones")
    decisions = provenance.settings_decisions(request.settings)
    yield Progress(_PHASE, 0, 1, "Leyendo lo congelado…")
    sources = [_frozen_source(frozen, code, calc_name, decisions)
               for code, calc_name in provenance.settings_entities(request.settings)]
    rows = yield from entity_store.declared_rows_steps(sources, frozen.grid, version_uid)
    output = _declared_output(request, rows, frozen.crs)
    yield Progress(_PHASE, 1, 1, "Restricciones declaradas reproducidas",
                   result=ReproducedResult((output,), provenance.declare_figures(len(rows))))


# --- Los cuatro tipos de la 016 (spec 016, T03): sin comportamiento todavía ---------------------------------------


def _not_yet(request: object, op_type: str, task: str, spec: str = "016") -> Iterator[Progress]:
    """La reproducción de un tipo de la 016 o de la 017 (``spec``) que aún no tiene su cálculo: comprueba que es una
    ``ReproduceRequest`` de ``op_type`` (``TypeError`` y ``ValueError``, errores del programa) y dice qué tarea lo hace
    (``NotImplementedError``). No hay ninguna operación de estos tipos que reproducir hasta que las tareas siguientes
    las crean."""
    _check(request, op_type)
    raise NotImplementedError(f"«{op_type}» aún no se reproduce: lo hace {task} de la {spec}")


def reproduce_stockpile_detect(request: ReproduceRequest, *, budget_s: float = STEP_BUDGET_S
                               ) -> Iterator[Progress]:
    """Reproduce ``des.stockpile_detect`` y ``des.stockpile_detect_project`` (spec 016, T14; RF-016-10, RF-016-02, RF-009-11;
    T04, D-15: la misma operación en los dos ámbitos) con la capa de marcas, la superficie sobre la que se detectó, las
    superficies de base propia de las marcas y, en una versión, sus máscaras congeladas, y los parámetros congelados de su
    entidad (``des.stockpile.{e}.*``: la capa, la superficie, los candidatos, los umbrales y las decisiones sobre los
    candidatos) y el umbral de la huella (``res.anthropic_presence_m``), con los ajustes de su operación (el nombre, el código y
    los campos de la capa), **sin el proyecto**: el mismo cálculo (``stockpile_store.detection_compute_steps``). Sus pasos y,
    el último, el ``ReproducedResult`` con las tablas de acopios, de candidatos y del informe, la base y el espesor de cada
    material, el terreno sin acopios y la superficie con que se detectó, y sus cifras. Una detección **del proyecto** con
    candidatos no se reproduce (su perímetro sale de la restricción del proyecto, que ninguna revisión congela: ``ValueError``).
    Lo que no es una ``ReproduceRequest`` es ``TypeError``; una de otro tipo, ``ValueError``."""
    named = getattr(request, "op_type", None)
    return _reproduce_stockpile_detect(
        _check(request, named if named in provenance.STOCKPILE_DETECT_TYPES else provenance.STOCKPILE_DETECT), budget_s)


def _reproduce_stockpile_detect(request: ReproduceRequest, budget_s: float) -> Iterator[Progress]:
    frozen = _Frozen(request)
    code = provenance.supported_code(request.settings)
    asked = provenance.stockpile_request(request.settings, provenance.supported_values(code, frozen.values))
    values, _defaulted = stockpile_store.detection_values(asked, code)
    candidates = bool(values[StockpileParam.CANDIDATES.value])
    if candidates and request.op_type == provenance.STOCKPILE_DETECT_PROJECT:
        raise ValueError(f"la detección «{asked.name}» del proyecto pide candidatos: su perímetro sale de la restricción del "
                         "proyecto, que ninguna revisión congela, así que no se reproduce")
    yield Progress(_PHASE, 0, 1, "Leyendo lo congelado…")
    layer = frozen.features(asked.fields.layer)
    marks, fids = yield from _paced(stockpile_store.marks_of_layer(layer, asked, frozen.grid, candidates=candidates),
                                    budget_s, "Leyendo las marcas…")
    surface = frozen.named_raster(asked.surface, what="superficie de detección").values
    bases: dict[str, np.ndarray] = {}
    for mark in marks:
        if mark.base is not None and mark.base not in bases:
            bases[mark.base] = frozen.named_raster(
                mark.base, what=f"superficie de base de la marca «{mark.key}»").values
    perimeter = stockpile_store.version_perimeter(frozen.masks(), frozen.grid) if candidates else None
    job = stockpile_store.detection_job(asked, code, values, frozen.grid, surface, marks, bases, perimeter,
                                        store.number(frozen.values, ANTHROPIC_PRESENCE))
    decisions = stockpile_store.parse_decisions(values[StockpileParam.DECISIONS.value], entity=asked.name)
    outcome = yield from stockpile_store.detection_compute_steps(job, decisions=decisions, budget_s=budget_s)
    crs, vertical = frozen.crs, frozen.vertical
    made = [
        _table_output(request, provenance.STOCKPILES_TABLE,
                      stockpile_store.stockpile_rows_of(job, asked.fields.layer, fids, outcome), crs),
        _table_output(request, provenance.STOCKPILE_CANDIDATES_TABLE,
                      stockpile_store.candidate_rows(outcome, job.grid.ncols), crs)]
    if outcome.stockpiles:  # sin ningún acopio no hay base, espesor, terreno ni superficie (como al crearla)
        for family, make in ((provenance.STOCKPILE_BASE_GRID, outcome.base_grid),
                             (provenance.STOCKPILE_THICKNESS_GRID, outcome.thickness_grid)):
            for number, material in enumerate(outcome.materials, start=1):
                made.append((yield from _grid_output(
                    request, family, Raster(job.grid, make(material), crs, vertical), budget_s, part=str(number))))
        for family, whole in ((provenance.STOCKPILE_GROUND_GRID, outcome.ground_grid),
                              (provenance.STOCKPILE_SURFACE_GRID, outcome.surface_grid)):
            made.append((yield from _grid_output(request, family, Raster(job.grid, whole(), crs, vertical), budget_s)))
    made.append(_table_output(request, provenance.ENTITY_REPORT_TABLE, stockpile_store.detection_report_rows(outcome), crs))
    yield Progress(_PHASE, 1, 1, "Detección de acopios reproducida",
                   result=ReproducedResult(tuple(made), tuple(outcome.figures)))


def reproduce_stockpile_removal(request: ReproduceRequest, *, budget_s: float = STEP_BUDGET_S
                                ) -> Iterator[Progress]:
    """Reproduce ``des.stockpile_removal`` (spec 016, T20; RF-016-11, RF-016-13, RF-016-15, RF-009-11) con su superficie de partida y sus
    máscaras congeladas, **el acopio que retira** (su tabla ``des_stk_``, su base ``des_stb_`` y la superficie con que se detectó
    ``des_stp_``: las tres entradas ``removed_stockpile``, por el prefijo de su dato) y los parámetros congelados de su entidad
    (``des.removal.{e}.*``: el acopio, la partida, el ángulo de transición, el factor de malla y la métrica) y del proyecto (la
    tolerancia de cara, el espesor mínimo y el salto creado), con los ajustes de su operación (el nombre y el código), **sin el
    proyecto**: el mismo cálculo (``supported_store.removal_compute_steps``). Sus pasos y, el último, el ``ReproducedResult`` con la
    superficie (``des_psf_``), la huella (``des_epr_``), el informe (``des_prp_``) y las cifras. Lo apoyado que confirmó la persona
    no se reproduce (es una decisión suya, de los ajustes). Lo que no es una ``ReproduceRequest`` es ``TypeError``; una de otro tipo,
    ``ValueError``."""
    return _reproduce_removal(_check(request, provenance.STOCKPILE_REMOVAL), budget_s)


def _frozen_removed(request: ReproduceRequest, frozen: _Frozen, stockpile: str, name: str
                    ) -> tuple[Mapping[str, object], removal.RemovedStockpile, str]:
    """El acopio ``stockpile`` (``STK-001#Acopio 7``) que consumió la operación ``name`` (una retirada o la plataforma que lo retira «como
    plataforma», T21), **de lo congelado**: sus tres entradas ``removed_stockpile`` (su tabla ``des_stk_``, la base de su material ``des_stb_``
    y la superficie con que se detectó ``des_stp_``, por el prefijo de su dato) dan la fila del acopio, su huella, su base y su superficie de
    detección (:func:`~.supported_store.read_removed`), **sin el proyecto**. Devuelve la fila de su tabla, el acopio y el código de su detección.
    ``ValueError`` si no consumió uno de los tres o la tabla congelada no tiene el acopio."""
    prefixes = {family: provenance.FAMILIES_BY_CODE[family].prefix for family in (
        provenance.STOCKPILES_TABLE, provenance.STOCKPILE_BASE_GRID, provenance.STOCKPILE_SURFACE_GRID)}
    removed = [item for item in request.inputs if item.role == provenance.REMOVED_STOCKPILE_ROLE]

    def of(family: str) -> FrozenInput:
        found = [item for item in removed if item.name.startswith(prefixes[family])]
        if len(found) != 1:
            raise ValueError(f"la retirada «{name}» consume {len(found)} datos «{family}» del acopio, no uno")
        return found[0]

    table = of(provenance.STOCKPILES_TABLE)
    names = [column.name for column in store.columns_of(provenance.STOCKPILE_DETECT, provenance.STOCKPILES_TABLE)]
    detection, key = provenance.split_support_ref(stockpile)
    with _open(Path(table.files["main"])) as conn:
        rows = [dict(zip(names, found, strict=True)) for found in conn.execute(
            f'SELECT {", ".join(names)} FROM "{table.settings["layer"]}" ORDER BY fid')]
    row = next((item for item in rows if item["key"] == key), None)
    if row is None:
        raise ValueError(f"la tabla congelada de acopios no tiene el acopio «{key}»")
    base = frozen.named_raster(of(provenance.STOCKPILE_BASE_GRID).name, what="base del acopio").values
    detected = frozen.named_raster(of(provenance.STOCKPILE_SURFACE_GRID).name, what="superficie con que se detectó").values
    item = supported_store.read_removed(row, frozen.grid, lambda window: base[window], lambda window: detected[window])
    return row, item, detection


def _reproduce_removal(request: ReproduceRequest, budget_s: float) -> Iterator[Progress]:
    frozen = _Frozen(request)
    code = provenance.supported_code(request.settings)
    asked = provenance.removal_request(request.settings, provenance.supported_values(code, frozen.values))
    values, _defaulted = supported_store.removal_values(asked, code)
    yield Progress(_PHASE, 0, 1, "Leyendo lo congelado…")
    masks = frozen.masks()
    start_item = frozen.item(provenance.SURFACE_ROLE)
    start = frozen.raster(provenance.SURFACE_ROLE, what="superficie de partida")
    row, item, _detection = _frozen_removed(request, frozen, asked.stockpile, asked.name)
    window = (slice(0, frozen.grid.nrows), slice(0, frozen.grid.ncols))
    job = RemovalJob(asked, code, frozen.grid, start.values, item, supported_store.default_domain(masks, window),
                     MappingProxyType(dict(values)))
    common = {name: store.number(frozen.values, name) for name in provenance.PLATFORM_COMMON_PARAMS}
    outcome = yield from supported_store.removal_compute_steps(job, common, budget_s=budget_s)
    surface = np.array(job.start, dtype=np.float64, copy=True)
    surface[outcome.window] = outcome.surface
    made = yield from _grid_output(request, provenance.ENTITY_SURFACE_GRID, Raster(job.grid, surface, frozen.crs, frozen.vertical),
                                   budget_s)
    runs = [tuple(int(value) for value in run) for run in json.loads(str(row["footprint"]))]
    entity = supported_store.removal_entity_rows(
        job, outcome, layer=str(row["layer"] or _detection), source_fid=int(row["source_fid"] or 0), runs=runs,
        start_surface=start_item.name, support_surface=_removal_support(request, asked))
    report = _table_output(request, provenance.ENTITY_REPORT_TABLE, supported_store.removal_report_rows(outcome), frozen.crs)
    yield Progress(_PHASE, 1, 1, "Retirada del acopio reproducida",
                   result=ReproducedResult((made, _table_output(request, provenance.ENTITY_TABLE, entity, frozen.crs), report), (
                       *outcome.figures, *_support_figures(frozen, [surface], start.values))))


def _removal_support(request: ReproduceRequest, asked: Any) -> str | None:
    """El nombre del dato de la superficie de apoyo de la retirada que se reproduce (como :func:`_support_dataset`): ``None`` sin apoyo."""
    return _support_dataset(request, asked)


def reproduce_buttress(request: ReproduceRequest, *, budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """Reproduce ``des.buttress`` (spec 016, T27; RF-016-17, RF-016-18, RF-009-11) con la capa de las zonas de coronación, la superficie de
    partida y sus máscaras congeladas y los parámetros congelados de su entidad (``des.buttress.{e}.*``: la capa y su geometría, la
    partida, el perfil, el alcance, la cota de coronación y la métrica), los del perfil (``des.bench.{p}.*``) y los del proyecto, con los
    ajustes de su operación (el nombre, el código y el campo de la cota), **sin el proyecto**: el mismo cálculo
    (``supported_store.buttress_compute_steps``, con la misma ventana de trabajo: ``supported_store.buttress_work_window``, y con el espesor
    mínimo y el salto admitido congelados para el pie cortado de RF-016-19: sus cifras y su aviso del informe salen iguales). Sus pasos y, el
    último, el ``ReproducedResult`` con la superficie (``des_psf_``), la huella con su zona de coronación (``des_epr_``), el informe
    (``des_prp_``) y las cifras. Lo que no es una ``ReproduceRequest`` es ``TypeError``; una de otro tipo, ``ValueError``."""
    return _reproduce_buttress(_check(request, provenance.BUTTRESS), budget_s)


def _reproduce_buttress(request: ReproduceRequest, budget_s: float) -> Iterator[Progress]:
    frozen = _Frozen(request)
    code = provenance.supported_code(request.settings)
    # lo que declara (``protect``, ``guard_m``, ``reason``) no lo lee el cálculo (``provenance.buttress_params``): no está congelado y no hace falta
    asked = replace(provenance.buttress_request(request.settings, provenance.supported_values(code, frozen.values)), protect=False)
    yield Progress(_PHASE, 0, 1, "Leyendo lo congelado…")
    masks = frozen.masks()
    layer = frozen.features(asked.layer)
    index = entity_store.feature_index(layer, asked, code)  # type: ignore[arg-type]
    fid = layer.fids[index]
    values, _defaulted = supported_store.buttress_values(asked, code, fid)
    profile = pipeline.bench_profiles(frozen.values, [asked.profile])[asked.profile]
    whole = polygons_cells(tuple(tuple(part) for part in layer.parts[index]), frozen.grid)
    start_item = frozen.item(provenance.SURFACE_ROLE)
    whole_start = frozen.raster(provenance.SURFACE_ROLE, what="superficie de partida").values
    lowest = supported_store._lowest_of(whole_start) if values.get("reach_m") is None else None
    window = supported_store.buttress_work_window(asked, code, whole, frozen.grid, profile, values, lowest)
    job = ButtressJob(asked, code, frozen.grid, profile, np.array(whole_start[window], dtype=np.float64, copy=True), whole[window],
                      admitted_in(masks, BenchSense.FILL, window), MappingProxyType(dict(values)), region=window, lowest_m=lowest,
                      parts=tuple(tuple(part) for part in layer.parts[index]))
    common = {name: store.number(frozen.values, name) for name in provenance.PLATFORM_COMMON_PARAMS}
    outcome = yield from supported_store.buttress_compute_steps(job, common, budget_s=budget_s)
    surface = outcome.compose(whole_start)
    made = yield from _grid_output(request, provenance.ENTITY_SURFACE_GRID, Raster(job.grid, surface, frozen.crs, frozen.vertical),
                                   budget_s)
    entity = supported_store.buttress_entity_rows(job, outcome, layer=asked.layer, source_fid=fid, start_surface=start_item.name,
                                                  support_surface=_support_dataset(request, asked))  # type: ignore[arg-type]
    table = _table_output(request, provenance.ENTITY_TABLE, entity, frozen.crs)
    report = _table_output(request, provenance.ENTITY_REPORT_TABLE, supported_store.buttress_report_rows(outcome), frozen.crs)
    yield Progress(_PHASE, 1, 1, "Contrafuerte reproducido",
                   result=ReproducedResult((made, table, report), (*outcome.figures, *_support_figures(frozen, [surface], whole_start))))


def reproduce_body(request: ReproduceRequest, *, budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """Reproduce ``des.body`` (spec 016, T25; RF-016-20 a RF-016-22, RF-009-11) con su huella (la capa de la huella), sus datos de
    espesor (la capa de los datos, con el papel ``body_data``), la superficie conocida, la de partida («sobre una base») y sus máscaras
    congeladas y los parámetros congelados de su entidad (``des.body.{e}.*``: la huella, los datos y cómo se leen, la superficie, el
    sentido, la partida, la distancia máxima y el «cero en el borde»), con los ajustes de su operación (el nombre y el código), **sin el
    proyecto**: el mismo cálculo (``supported_store.body_compute_steps``). Sus pasos y, el último, el ``ReproducedResult`` con el
    espesor disperso (``des_bdt_``), la superficie (``des_psf_``) o la base dispersa (``des_bds_``), la huella (``des_epr_``), el
    informe (``des_prp_``) y las cifras. Lo que no es una ``ReproduceRequest`` es ``TypeError``; una de otro tipo, ``ValueError``."""
    return _reproduce_body(_check(request, provenance.BODY), budget_s)


def _frozen_known_surface(request: ReproduceRequest, frozen: _Frozen, asked: Any) -> tuple[str, np.ndarray]:
    """La superficie conocida del cuerpo que se reproduce, **de lo congelado**: «bajo un techo», la entrada ``surface``; «sobre una
    base», la del parámetro (el nombre de un dato) o, si es ``entity:<código>``, la primera de sus entradas ``supported_on`` (la
    conocida se anota antes que las que añade el cálculo al crear). Devuelve el nombre de su dato y sus celdas."""
    if asked.sense is not BodySense.ON_BASE:
        item = frozen.item(provenance.SURFACE_ROLE)
        return item.name, frozen.raster(provenance.SURFACE_ROLE, what="superficie conocida").values
    name = asked.surface
    if entities.ref_code(name) is not None:
        found = [item.name for item in request.inputs if item.role == provenance.SUPPORTED_ON_ROLE]
        if not found:
            raise ValueError(f"el cuerpo «{asked.name}» se apoya en {asked.surface!r} y su operación no anotó ninguna superficie "
                             "«supported_on»")
        name = found[0]
    return name, frozen.named_raster(name, what="superficie conocida").values


def _reproduce_body(request: ReproduceRequest, budget_s: float) -> Iterator[Progress]:
    frozen = _Frozen(request)
    code = provenance.supported_code(request.settings)
    asked = provenance.body_request(request.settings, provenance.supported_values(code, frozen.values))
    yield Progress(_PHASE, 0, 1, "Leyendo lo congelado…")
    masks = frozen.masks()
    layer = frozen.features(asked.layer)
    index = entity_store.feature_index(layer, asked, code)  # type: ignore[arg-type]
    fid = layer.fids[index]
    values, _defaulted = supported_store.body_values(asked, code, fid)
    whole = polygons_cells(tuple(tuple(part) for part in layer.parts[index]), frozen.grid)
    window = body_window(whole, frozen.grid)
    if window is None:
        raise no_data_error(asked)
    on_base = asked.sense is BodySense.ON_BASE
    known_name, known = _frozen_known_surface(request, frozen, asked)
    start_item = frozen.item(provenance.SURFACE_ROLE)
    start = whole_start = fill = None
    if on_base:
        whole_start = frozen.raster(provenance.SURFACE_ROLE, what="superficie de partida").values
        start = whole_start[window]
        fill = admitted_in(masks, BenchSense.FILL, window)
    data_item = frozen.named(asked.data_layer)
    with _open(Path(data_item.files["main"])) as conn:
        data = supported_store.frozen_thickness_data(conn, str(data_item.settings["layer"]), asked)
    job = BodyJob(asked, code, frozen.grid, frozen.crs, frozen.vertical, known[window], whole[window], data,
                  MappingProxyType(dict(values)), start=start, fill_allowed=fill, region=window,
                  parts=tuple(tuple(part) for part in layer.parts[index]))
    outcome = yield from supported_store.body_compute_steps(job, budget_s=budget_s)
    crs, vertical, grid = frozen.crs, frozen.vertical, job.grid
    made = [(yield from _grid_output(
        request, provenance.BODY_THICKNESS_GRID, Raster(grid, supported_store._sparse(grid, outcome, outcome.thickness), crs, vertical),
        budget_s))]
    surface = None
    if on_base:
        surface = outcome.compose(whole_start)
        made.append((yield from _grid_output(request, provenance.ENTITY_SURFACE_GRID, Raster(grid, surface, crs, vertical), budget_s)))
    else:
        made.append((yield from _grid_output(
            request, provenance.BODY_BASE_GRID, Raster(grid, supported_store._sparse(grid, outcome, outcome.base), crs, vertical),
            budget_s)))
    entity = supported_store.body_entity_rows(
        job, outcome, layer=asked.layer, source_fid=fid, runs=entity_store.footprint_runs(job.footprint, window),
        start_surface=start_item.name, support_surface=known_name if on_base else None)
    made.append(_table_output(request, provenance.ENTITY_TABLE, entity, crs))
    made.append(_table_output(request, provenance.ENTITY_REPORT_TABLE, supported_store.body_report_rows(outcome), crs))
    supports = () if surface is None else _support_figures(frozen, [surface], whole_start)  # type: ignore[arg-type]
    yield Progress(_PHASE, 1, 1, "Cuerpo apoyado reproducido",
                   result=ReproducedResult(tuple(made), (*outcome.figures, *supports)))


# --- Los tres tipos de la 017 (spec 017, T03): sin comportamiento todavía ----------------------------------------


def reproduce_road(request: ReproduceRequest, *, budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """Reproduce ``des.road`` (spec 017, T22; RF-017-01 a RF-017-03, RF-015-02, RF-009-11) con la capa de origen, la superficie de partida y las máscaras congeladas —con los pesos de «preferible no
    afectar» de su informe—, los parámetros congelados de su entidad (``des.road.{e}.*``: el modo, la capa, el perfil, la partida, el apoyo, el origen y el destino, las cotas de inicio y de fin y los
    de la ruta) y de su perfil (``des.roadprofile.{p}.*``) y del proyecto (el espesor mínimo, la tolerancia de cara, el umbral de magnitud y el salto creado), con los ajustes de su operación (el nombre, el
    código y el campo de los nombres de la capa), **sin el proyecto**: el mismo cálculo (``road_store.road_compute_steps`` sobre el mismo ``RoadJob``). La geometría de origen y el ``fid`` salen de lo
    **congelado** (:func:`~.road_store.frozen_geometry`): la capa, **el eje por estaciones de la pista en cuyo eje está el origen** (la entrada de papel ``road_axis``), la huella de la entidad de destino
    (``support_footprint``) y la capa de la zona de un destino por cota. Los otros diseños de la versión que difieren en la huella son las entradas ``other_design``: con ellos se repite el aviso del informe.
    Sus pasos y, el último, el ``ReproducedResult`` con la superficie entera (``des_psf_``), la huella (``des_epr_``), el eje por estaciones (``des_rdx_``), el informe (``des_prp_``) y las cifras (con
    ``des.supported_m3`` de lo que apoya). Lo confirmado por la persona no se reproduce (es una decisión suya, de los ajustes). Lo que no es una ``ReproduceRequest`` es ``TypeError``; una de otro tipo,
    ``ValueError``; el modo «eje 3D», ``NotImplementedError`` (T23)."""
    return _reproduce_road(_check(request, provenance.ROAD), budget_s)


def _frozen_axis(request: ReproduceRequest) -> np.ndarray | None:
    """El eje por estaciones (abscisa, x, y, cota del terreno y cota de la rasante) de la pista en cuyo eje está el origen, de su entrada congelada de papel ``road_axis``; ``None`` si la operación no la tiene."""
    found = [item for item in request.inputs if item.role == provenance.ROAD_AXIS_ROLE]
    if not found:
        return None
    with _open(Path(found[0].files["main"])) as conn:
        rows = conn.execute(f'SELECT {road_store._SECTION_COLUMNS} FROM "{found[0].settings["layer"]}" ORDER BY station_m').fetchall()
    return np.asarray(rows, dtype=np.float64).reshape(-1, 5)


def _frozen_footprint(request: ReproduceRequest, ncols: int, code: str) -> np.ndarray | None:
    """Las celdas (``fila · columnas + columna``) de la huella de la entidad ``code``, de su entrada congelada de papel ``support_footprint`` (su ``des_epr_``); ``None`` si la operación no la tiene."""
    for item in request.inputs:
        if item.role != provenance.SUPPORT_FOOTPRINT_ROLE:
            continue
        with _open(Path(item.files["main"])) as conn:
            footprint = entity_store.read_entity_footprint(conn, str(item.settings["layer"]))
        if footprint.code == code:
            return road_store.runs_cells(np.asarray(footprint.runs, dtype=np.int64), ncols)
    return None


def _reproduce_road(request: ReproduceRequest, budget_s: float) -> Iterator[Progress]:
    frozen = _Frozen(request)
    code = provenance.supported_code(request.settings)
    asked = provenance.road_request(request.settings, provenance.supported_values(code, frozen.values))
    values = road_store.road_values(asked, code, start_ref=asked.start, start_level_m=asked.start_level_m, end_level_m=asked.end_level_m)
    yield Progress(_PHASE, 0, 1, "Leyendo lo congelado…")
    masks = replace(frozen.masks(), weights=MappingProxyType(frozen.weights()))
    start_item = frozen.item(provenance.SURFACE_ROLE)
    start = frozen.raster(provenance.SURFACE_ROLE, what="superficie de partida").values
    layer = frozen.features(asked.layer)
    zone = frozen.features(str(asked.dest_zone).partition(":")[0].strip()) if asked.destination is None and asked.dest_zone is not None else None
    origin_ref = road_store.parse_reference(asked.origin) if asked.origin is not None else None
    destination_ref = road_store.parse_reference(asked.destination) if asked.destination is not None else None
    footprint = _frozen_footprint(request, frozen.grid.ncols, destination_ref.code) if isinstance(destination_ref, road_store.EntityReference) else None
    axis = _frozen_axis(request) if isinstance(origin_ref, road_store.AxisReference) else None
    geometry, fid = road_store.frozen_geometry(asked, code, frozen.grid, layer, zone_layer=zone, axis=axis, footprint=footprint)
    whole = (slice(0, frozen.grid.nrows), slice(0, frozen.grid.ncols))
    cut, fill = admitted(masks, BenchSense.CUT)[whole], admitted(masks, BenchSense.FILL)[whole]
    job = RoadJob(asked, code, road_store.frozen_profile(frozen.values, asked.profile), frozen.grid, start, cut, fill, road_store.untouchable_cells(masks), geometry,
                  RouteParams.from_values(values) if asked.mode is RoadMode.TRACE else None, asked.start_level_m, asked.end_level_m, road_store.avoid_weight(masks))
    common = {name: store.number(frozen.values, name) for name in provenance.PLATFORM_COMMON_PARAMS}
    others = tuple(item.name for item in request.inputs if item.role == provenance.ROAD_OTHER_DESIGN_ROLE)

    def read_other(name: str, window: tuple[slice, slice]) -> np.ndarray:
        """La superficie de otro diseño de la versión, **congelada**, en la ventana de trabajo de la pista."""
        return np.asarray(frozen.named_raster(name, what="superficie de otro diseño").values[window], dtype=np.float64)

    outcome = yield from road_store.road_compute_steps(job, common, surface=start_item.name, others=others, read_other=read_other if others else None, operation=asked.name, budget_s=budget_s)
    surface = outcome.compose(job.start)
    made = yield from _grid_output(request, provenance.ENTITY_SURFACE_GRID, Raster(job.grid, surface, frozen.crs, frozen.vertical), budget_s)
    entity = road_store.road_entity_rows(job, outcome, fid=fid, start_surface=start_item.name, support_surface=_support_dataset(request, asked))
    tables = (_table_output(request, provenance.ENTITY_TABLE, entity, frozen.crs),
              _table_output(request, provenance.ROAD_AXIS_TABLE, road_store.road_axis_rows(outcome), frozen.crs),
              _table_output(request, provenance.ENTITY_REPORT_TABLE, road_store.road_report_rows(outcome), frozen.crs))
    yield Progress(_PHASE, 1, 1, "Pista reproducida", result=ReproducedResult((made, *tables), (*outcome.figures, *_support_figures(frozen, [surface], start))))


def reproduce_road_access(request: ReproduceRequest, *, budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """Reproduce ``des.road_access`` (spec 017, T17b; RF-017-24, RF-017-25, RF-015-02, RF-009-11) con la superficie (y la final de una cantera de dos superficies), la capa de los puntos
    de entrada, las rejillas de cotas de berma, las huellas de las plataformas y las máscaras congeladas y los parámetros congelados de su entidad (``des.access.{e}.*``: la superficie,
    la capa de entradas, los datos de bermas y los tres umbrales), con los ajustes de su operación (el nombre, el código y el campo del nombre de los puntos), **sin el proyecto**: el
    mismo cálculo (``access_store.access_compute_steps`` sobre el mismo ``AccessJob``). Sus pasos y, el último, el ``ReproducedResult`` con la rejilla de lo alcanzable
    (``des_acc_``), las tablas de bermas, plataformas y zonas (``des_acb_``, ``des_acp_`` y ``des_acz_``), el informe (``des_prp_``) y las cifras. Lo que no es una ``ReproduceRequest`` es
    ``TypeError``; una de otro tipo, ``ValueError``."""
    return _reproduce_road_access(_check(request, provenance.ROAD_ACCESS), budget_s)


def _reproduce_road_access(request: ReproduceRequest, budget_s: float) -> Iterator[Progress]:
    frozen = _Frozen(request)
    code = provenance.supported_code(request.settings)
    asked = provenance.access_request(request.settings, provenance.supported_values(code, frozen.values))
    values = access_store.access_values(asked, code)
    yield Progress(_PHASE, 0, 1, "Leyendo lo congelado…")
    masks = frozen.masks()
    surface = frozen.raster(provenance.SURFACE_ROLE, what="superficie de la accesibilidad").values
    finals = [item for item in request.inputs if item.role == provenance.ACCESS_FINAL_ROLE]
    final = frozen.raster(provenance.ACCESS_FINAL_ROLE, what="superficie final de la cantera").values if finals else None
    entries = access_store.entry_points(frozen.features(asked.layer), asked, code)
    berms = tuple(BermGrid(item.name, frozen.named_raster(item.name, what="rejilla de cotas de berma").values)
                  for item in request.inputs if item.role == provenance.FAMILIES_BY_CODE[provenance.BERMS_GRID].role)
    platforms: list[AccessCells] = []
    for item in request.inputs:
        if item.role != provenance.ENTITY_ROLE:
            continue
        with _open(Path(item.files["main"])) as conn:
            footprint = entity_store.read_entity_footprint(conn, str(item.settings["layer"]))
        platforms.append(AccessCells(footprint.code, footprint.name, access_store.platform_cells(footprint.runs, frozen.grid.ncols)))
    job = access_store.access_job(asked, code, values, frozen.grid, surface, entries, access_store.untouchable_cells(masks), final=final, berms=berms, platforms=platforms,
                                  zones=access_store.access_zones(masks))
    outcome = yield from access_store.access_compute_steps(job, budget_s=budget_s)
    crs, vertical = frozen.crs, frozen.vertical
    made = [(yield from _grid_output(request, provenance.ACCESS_GRID, Raster(job.grid, access_store.reachable_grid(outcome), crs, vertical), budget_s))]
    for family, rows in ((provenance.ACCESS_BERMS_TABLE, access_store.berm_rows(outcome)), (provenance.ACCESS_PLATFORMS_TABLE, access_store.platform_rows(outcome)),
                         (provenance.ACCESS_ZONES_TABLE, access_store.zone_rows(outcome)), (provenance.ENTITY_REPORT_TABLE, access_store.access_report_rows(outcome))):
        made.append(_table_output(request, family, rows, crs))
    yield Progress(_PHASE, 1, 1, "Accesibilidad reproducida", result=ReproducedResult(tuple(made), tuple(outcome.figures)))


def reproduce_road_propose(request: ReproduceRequest, *, budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """Reproduce ``des.road_propose`` (spec 017, T03; RF-017-28, RF-009-11): sin comportamiento todavía (T27)."""
    return _not_yet(request, provenance.ROAD_PROPOSE, "la T27", "017")


REPRODUCE:Mapping[str, ReproduceFunction] = MappingProxyType({
    provenance.ENVELOPE: reproduce_envelope, provenance.STEPPED: reproduce_design})
"""Las funciones de reproducir de los dos tipos de la 013 (las que registra ``bl``; las de la
014 las registra por su nombre: :func:`reproduce_excavation_area` y :func:`reproduce_quarry`)."""

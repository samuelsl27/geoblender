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
nombre).

Con el mismo Geoblender y el mismo numpy, las salidas y las cifras salen **bit a bit**; con otros,
``core.versions.reproduce`` compara las cifras con ``figure_tolerance`` (10⁻⁹ relativo, plan
§5.2.3). Cerrar los pasos antes del final o un fallo dejan lo escrito en la carpeta de trabajo,
que borra quien la creó. Python puro con numpy (nivel 8).
"""

from __future__ import annotations

import os
import sqlite3
import sys
from collections.abc import Generator, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, closing, contextmanager
from pathlib import Path
from types import MappingProxyType

import numpy as np

from ..core.constraints import store as constraints_store
from ..core.gpkg.base import create_attribute_table, create_base
from ..core.georef import CrsRef
from ..core.gpkg.connection import GpkgConnection
from ..core.paths import check_path_length
from ..core.project.model import Progress
from ..core.provenance.contract import ReproduceFunction
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
from . import fronts, pipeline, provenance, quarry, store
from .model import EnvelopeRequest, SeedKind, Surface
from .params import TOLERANCE_FACE, VERIFY_MIN_THICKNESS, WARNING_RATIO
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
from .zones import frozen_polygons, polygons_cells, sector_labels

__all__ = [
    "REPRODUCE",
    "reproduce_design",
    "reproduce_edge_transition",
    "reproduce_envelope",
    "reproduce_excavation_area",
    "reproduce_fill_only",
    "reproduce_quarry",
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


def _grid_output(request: ReproduceRequest, family: str, raster: Raster, budget_s: float
                 ) -> Generator[Progress, None, ReproducedOutput]:
    """Escribe ``raster`` como la salida ``family`` de la operación, en la carpeta de trabajo."""
    found = provenance.FAMILIES_BY_CODE[family]
    path = Path(request.workdir) / f"{found.role}_{family}.tif"  # dos superficies, un papel
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
                   result=ReproducedResult(tuple(outputs), outcome.figures))


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
    for family, grid, _what in store.quarry_grids(outcome):
        outputs.append((yield from _grid_output(
            request, family, Raster(start.grid, grid, frozen.crs, frozen.vertical), budget_s)))
    outputs.append(_table_output(request, provenance.BERM_TABLE,
                                 store.quarry_berm_rows(outcome), frozen.crs))
    outputs.append(_table_output(request, provenance.QUARRY_REPORT_TABLE,
                                 store.quarry_report_rows(outcome, calculated.notices),
                                 frozen.crs))
    yield Progress(_PHASE, 1, 1, "Cantera reproducida",
                   result=ReproducedResult(tuple(outputs), outcome.figures))


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
                   result=ReproducedResult((output, report), outcome.figures))


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
                   result=ReproducedResult((surface, report), outcome.figures))


REPRODUCE:Mapping[str, ReproduceFunction] = MappingProxyType({
    provenance.ENVELOPE: reproduce_envelope, provenance.STEPPED: reproduce_design})
"""Las funciones de reproducir de los dos tipos de la 013 (las que registra ``bl``; las de la
014 las registra por su nombre: :func:`reproduce_excavation_area` y :func:`reproduce_quarry`)."""

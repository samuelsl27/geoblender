# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendimiento de los sondeos con V-ref (spec 005 §5; T31: RNF-005-01, RNF-005-02 y
RNF-005-03, y los riesgos R12 y R17 del plan 005; plan 005 §7, ``tests/rendimiento``).

Se ejecuta con ``tools/check.py --rendimiento``: el Python de Blender (su numpy 2.3.4) en el
PC de referencia de la spec 001 §5, en disco local (``%TEMP%``). Cada cifra es la mediana de
5 repeticiones (la importación de principio a fin, de :data:`IMPORT_REPETITIONS`), se imprime
en una línea ``RNF-005-nn: …`` con el equipo y el intérprete (``tools/check.py`` las recoge)
y se compara con su presupuesto, sin relajarlo. RNF-005-04 y RNF-005-06 se miden dentro de
Blender (T32) y RNF-005-05, con el motor de Access (T33 y T43).

**Datos** (spec 005 §5; se generan y no se versionan): V-ref de
``tests/data/dh/sintetico.py`` (semilla fija) en una carpeta temporal del módulo, leído con el
lector real (``interop.csv_tables.read_table`` e ``interop.drillholes_tabular.read_drillholes``):
2.000 sondeos, 20.000 estaciones, 50.000 tramos de litología y 25.000 tramos con 20
elementos (500.000 valores), en convenios internos (azimut de cuadrícula, inclinación
negativa hacia abajo). El MDT, una rejilla de 1 m (``gis.raster.Raster``) con la superficie
de ``tests/data/gis`` sobre la que están las bocas de V-ref, muestreado con la bilineal de la
006 (``drillholes.surface.raster_sampler``), y la ventana de trabajo, la de las bocas con
50 m de margen: V-ref no tiene incidencias.

- RNF-005-01 (:class:`ImportTest`): importar los seis CSV de V-ref (bocas, desviaciones,
  litología, análisis en columnas y los catálogos de litologías y elementos) **de principio a
  fin**, como lo hace Blender (``bl/ops/dh.py``; plan §5.6.5), en un proyecto nuevo con su MDT
  (la rejilla del proyecto ``gis_dtm_terreno``) y su ventana de trabajo: sus seis operaciones
  «en curso» en una transacción, la lectura de cada fichero (``dh_import_tabular`` en proceso
  aparte, con el fichero por ruta, dos a la vez como el lanzador de Blender y la del fichero
  más grande primero: la copia verificada, el hash de contenido de la fuente con
  ``io.dh_csv@1`` y lo leído), su aplicación (``dh_import_apply``, con lo leído por ruta: las
  filas de lo importado y su hash), su escritura por pasos (``drillholes.store.SourceWriter``:
  las entradas, lo importado, el informe y el original de cada fichero), la base
  (``dh.build_base``: lo importado leído por pasos y a arrays por partes, el trabajo
  ``dh_build_base`` con las conversiones y el hash de cada tabla, y su escritura con
  ``BaseWriter``) y su validación (``dh.validate``: la base leída por pasos y a arrays por
  partes, el trabajo ``dh_validate`` con el MDT por ruta, que copia a ``in/``, y su
  escritura), desde que empiezan sus operaciones hasta que se confirma la validación: ≤ 30 s
  (lo que hace Blender, sin Blender, con ``tests.support.dh_import``). Fuera de la medida:
  crear el proyecto y su MDT, la propuesta de columnas del asistente y la decisión de la
  persona sobre los códigos nuevos (se dan de alta, como propone «Importación pendiente»); las
  pausas de los temporizadores de Blender entre pasos y el sondeo del monitor (0,25 s) son de
  RNF-005-06 (T32). La línea dice también dónde corrió cada trabajo (en proceso aparte o en
  el hilo). Se anotan también el tamaño del proyecto (R12: las filas, en lo importado y en la
  base) y la base reconstruida con lo mismo (R17: sus tablas se crean de nuevo y se siguen
  después de llenarlas, así que los disparadores ``gbtc_`` no saltan por fila; lo que
  costarían, medido aparte con las filas de ``dh_assay``).
- RNF-005-02: ``drillholes.validate.validate`` de V-ref con el MDT y la ventana de trabajo
  (las 27 comprobaciones de la tabla 4.4.1, DH-W05 incluida): ≤ 5 s.
- RNF-005-03: las trazas por mínima curvatura de los 2.000 sondeos
  (``drillholes.desurvey.desurvey``) más la posición de 100.000 profundidades al azar
  (``drillholes.desurvey.md_to_xyz``): ≤ 2 s.
"""

from __future__ import annotations

import dataclasses
import gc
import json
import math
import sqlite3
import statistics
import tempfile
import time
import unittest
from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np

from tests.data.dh import sintetico
from tests.support import dh_import, dh_sets
from tests.support import gis_perf as perf
from tests.support.core_fixtures import make_session, make_settings
from tests.support.dh_fakes import gis_surface
from tests.support.package import import_geoblender

csv_tables = import_geoblender("interop.csv_tables")
tabular = import_geoblender("interop.drillholes_tabular")
model = import_geoblender("drillholes.model")
validate = import_geoblender("drillholes.validate")
desurvey = import_geoblender("drillholes.desurvey")
surface = import_geoblender("drillholes.surface")
dh_arrays = import_geoblender("drillholes.arrays")
dh_jobs = import_geoblender("drillholes.jobs")
dh_params = import_geoblender("drillholes.params")
provenance = import_geoblender("drillholes.provenance")
schema = import_geoblender("drillholes.schema")
store = import_geoblender("drillholes.store")
georef = import_geoblender("core.georef")
gpkg_base = import_geoblender("core.gpkg.base")
inputs_mod = import_geoblender("core.inputs")
tracking = import_geoblender("core.datasets.tracking")
operations = import_geoblender("core.provenance.operations")
create = import_geoblender("core.project.create")
userdata_mod = import_geoblender("core.userdata")
core_params = import_geoblender("core.params")
grid = import_geoblender("gis.grid")
raster = import_geoblender("gis.raster")
gis_crs = import_geoblender("gis.crs")
gis_jobs = import_geoblender("gis.jobs")
gis_provenance = import_geoblender("gis.provenance")
gis_store = import_geoblender("gis.store")

IMPORT_BUDGET_S = 30.0  # RNF-005-01
VALIDATE_BUDGET_S = 5.0  # RNF-005-02
TRACES_BUDGET_S = 2.0  # RNF-005-03

# V-ref (spec 005 §5).
VREF_HOLES = 2_000
VREF_STATIONS = 20_000
VREF_LITHOLOGY = 50_000
VREF_VALUES = 500_000
POSITIONS = 100_000  # RNF-005-03
POSITIONS_SEED = 20_261_014

DTM_STEP_M = 1.0
DTM_MARGIN_M = 20.0
WINDOW_MARGIN_M = 50.0
DTM_FIT_M = 0.01  # la bilineal de 1 m sobre la superficie y las cotas a 3 decimales

FILES = {
    tabular.TableRole.COLLAR: "bocas.csv",
    tabular.TableRole.SURVEY: "desviaciones.csv",
    tabular.TableRole.LITHOLOGY: "litologia.csv",
    tabular.TableRole.ASSAY_WIDE: "analisis_columnas.csv",
    tabular.TableRole.LITHOLOGY_CATALOG: "litologias.csv",
    tabular.TableRole.ELEMENT_CATALOG: "elementos.csv",
}
MACHINE = perf.MACHINE

# Cómo se leen los CSV de V-ref (el formato de csv_basico): los ajustes de lectura de una
# entrada (``drillholes.provenance.READING_SETTINGS``), el decimal y el formato de las fechas.
READING = {"encoding": "utf-8", "separator": ";"}
ENTRY_READING = {**READING, "header_row": 0}
DECIMAL = ","
DATE_FORMAT = "%d/%m/%Y"

# RNF-005-01: la importación de principio a fin (ImportTest).
IMPORT_REPETITIONS = perf.REPETITIONS  # cada una, un proyecto nuevo que se borra en seguida
PROJECT_SURFACE = "terreno"  # la rejilla del proyecto con que se valida (gis_dtm_terreno)
TRIGGER_ROWS = 100_000  # las filas de dh_assay con que se miden los disparadores (R17)
CATALOG_ROLES = frozenset({str(tabular.TableRole.LITHOLOGY_CATALOG),
                           str(tabular.TableRole.ELEMENT_CATALOG)})
COUNTED = ("dh_collar", "dh_survey", "dh_lithology", "dh_assay", "dh_validation_issue")
"""Las tablas cuyas filas se comprueban tras la importación (las incidencias, ninguna)."""
PHASES = ("lectura", "aplicación", "lo importado", "base", "validación")
"""Las fases de la importación de principio a fin (véase el módulo), en su orden."""


# --- Datos ---------------------------------------------------------------------------------


def _declaration(units: dict[str, str]) -> object:
    """Lo que declara quien importa V-ref (el formato de ``csv_basico``): EPSG:25830 y
    EPSG:5782, azimut de cuadrícula, inclinación negativa hacia abajo, coma decimal, fechas
    dd/mm/aaaa y la unidad de cada elemento de su catálogo."""
    return model.SourceDeclaration(
        crs=dh_sets.H25830, vertical=dh_sets.V5782, azimuth_ref=model.AzimuthRef.GRID,
        declination_deg=None, inclination_convention=model.InclinationConvention.NEGATIVE_DOWN,
        units=units, value_rules=model.ValueRules(decimal_mark=DECIMAL),
        date_format=DATE_FORMAT)


def _read_vref(folder: Path) -> object:
    """V-ref escrito en ``folder`` y leído con el lector real."""
    sintetico.write_vref(folder)
    tables = {role: csv_tables.read_table(folder / name, **READING)
              for role, name in FILES.items()}
    units = {row[0]: row[2] for row in tables[tabular.TableRole.ELEMENT_CATALOG].rows}
    dset, report = tabular.read_drillholes(tables, None, _declaration(units))
    if report.rejected:
        raise AssertionError(f"V-ref con filas rechazadas: {report.rejected[:3]}")
    return dset


def _dtm(dset: object) -> object:
    """Una rejilla de 1 m con la superficie de ``tests/data/gis`` (en los centros de las
    celdas) que cubre las bocas con margen."""
    x, y = dset.collars.x, dset.collars.y
    west = math.floor(float(x.min()) - DTM_MARGIN_M)
    north = math.ceil(float(y.max()) + DTM_MARGIN_M)
    ncols = math.ceil(float(x.max()) + DTM_MARGIN_M - west)
    nrows = math.ceil(north - (float(y.min()) - DTM_MARGIN_M))
    cells = grid.Grid(west, north, DTM_STEP_M, DTM_STEP_M, ncols, nrows)
    east = west + (np.arange(ncols) + 0.5) * DTM_STEP_M
    northing = north - (np.arange(nrows) + 0.5) * DTM_STEP_M
    xy = np.column_stack((np.tile(east, nrows), np.repeat(northing, ncols)))
    values = gis_surface(xy).reshape(nrows, ncols)
    return raster.Raster(cells, values, dh_sets.H25830, dh_sets.V5782)


def _window(dset: object) -> object:
    x, y = dset.collars.x, dset.collars.y
    return georef.Window(float(x.min()) - WINDOW_MARGIN_M, float(y.min()) - WINDOW_MARGIN_M,
                         float(x.max()) + WINDOW_MARGIN_M, float(y.max()) + WINDOW_MARGIN_M)


def _positions(dset: object) -> tuple[np.ndarray, np.ndarray]:
    """100.000 profundidades al azar (semilla fija) entre la boca y el fondo de sondeos al
    azar: (sondeo, profundidad)."""
    rng = np.random.default_rng(POSITIONS_SEED)
    hole = rng.integers(0, len(dset.collars), POSITIONS, dtype=np.int64)
    md = rng.random(POSITIONS) * dset.collars.depth[hole]
    return hole, md


class _Data:
    """Lo que comparten las pruebas, creado una vez en :func:`setUpModule`."""

    folder: Path  # la carpeta temporal del módulo; V-ref, en «vref/»
    dset: object
    units: dict[str, str]
    dtm: object
    window: object


_DATA = _Data()


def setUpModule() -> None:
    """V-ref en una carpeta temporal del módulo (que se borra al final), leído; su MDT y su
    ventana."""
    stack = ExitStack()
    unittest.addModuleCleanup(stack.close)
    _DATA.folder = Path(stack.enter_context(tempfile.TemporaryDirectory(
        prefix="gb-dh-perf-", ignore_cleanup_errors=True)))
    vref = _DATA.folder / "vref"
    vref.mkdir()
    _DATA.dset = _read_vref(vref)
    elements = csv_tables.read_table(vref / FILES[tabular.TableRole.ELEMENT_CATALOG], **READING)
    _DATA.units = {row[0]: row[2] for row in elements.rows}
    _DATA.dtm = _dtm(_DATA.dset)
    _DATA.window = _window(_DATA.dset)


def _volume() -> str:
    dset = _DATA.dset
    return (f"{perf.count(len(dset.collars))} sondeos, {perf.count(len(dset.surveys))} "
            f"estaciones, {perf.count(len(dset.lithology))} tramos de litología y "
            f"{perf.count(len(dset.assays))} valores")


# --- Validación (RNF-005-02) ---------------------------------------------------------------


class ValidateTest(unittest.TestCase):
    """RNF-005-02: validar V-ref."""

    def test_vref_volume(self) -> None:
        """RNF-005-02, RNF-005-03: el V-ref leído es el de la spec 005 §5."""
        dset = _DATA.dset
        self.assertEqual(len(dset.collars), VREF_HOLES)
        self.assertEqual(len(dset.surveys), VREF_STATIONS)
        self.assertEqual(len(dset.lithology), VREF_LITHOLOGY)
        self.assertEqual(len(dset.assays), VREF_VALUES)

    def test_validate_vref(self) -> None:
        """RNF-005-02: ``validate`` de V-ref con el MDT de 1 m y la ventana de trabajo en
        ≤ 5 s (mediana de 5), sin incidencias ni notas (cada boca a ≤ 1 cm del MDT)."""
        sampler = surface.raster_sampler(_DATA.dtm)
        params = dh_sets.params()
        times, report = perf.measure(lambda: validate.validate(
            _DATA.dset, params, surface=sampler, work_window=_DATA.window))
        cells = _DATA.dtm.grid.ncols * _DATA.dtm.grid.nrows
        perf.report(f"RNF-005-02: validar V-ref ({_volume()}) con un MDT de 1 m de "
                    f"{perf.count(cells)} celdas y la ventana de trabajo "
                    f"({len(report.issues)} incidencias; {MACHINE}): "
                    f"{perf.median_line(times)}, presupuesto "
                    f"{perf.number(VALIDATE_BUDGET_S, 0)} s")
        self.assertEqual(report.issues, ())
        self.assertEqual(report.notes, ())
        self.assertLessEqual(float(np.max(np.abs(report.collar_dem_dz))), DTM_FIT_M)
        self.assertLessEqual(statistics.median(times), VALIDATE_BUDGET_S)


# --- Trazas y posiciones (RNF-005-03) ------------------------------------------------------


class TracesTest(unittest.TestCase):
    """RNF-005-03: las trazas de V-ref y 100.000 posiciones."""

    def test_traces_and_positions(self) -> None:
        """RNF-005-03: las trazas por mínima curvatura de los 2.000 sondeos de V-ref más la
        posición de 100.000 profundidades al azar en ≤ 2 s (mediana de 5); todas las trazas
        calculadas, sin avisos, y las posiciones finitas."""
        hole, md = _positions(_DATA.dset)
        split: list[tuple[float, float]] = []

        def run() -> tuple[object, np.ndarray]:
            start = time.perf_counter()
            traces = desurvey.desurvey(_DATA.dset, desurvey.Method.MINIMUM_CURVATURE)
            middle = time.perf_counter()
            xyz = desurvey.md_to_xyz(traces, hole, md)
            split.append((middle - start, time.perf_counter() - middle))
            return traces, xyz

        times, (traces, xyz) = perf.measure(run)
        trace_s = statistics.median(t for t, _ in split)
        position_s = statistics.median(p for _, p in split)
        perf.report(f"RNF-005-03: trazas por mínima curvatura de "
                    f"{perf.count(len(_DATA.dset.collars))} sondeos "
                    f"({perf.count(len(traces.md))} nodos) y la posición de "
                    f"{perf.count(len(md))} profundidades (trazas {perf.number(trace_s)} s, "
                    f"posiciones {perf.number(position_s)} s; {MACHINE}): "
                    f"{perf.median_line(times)}, presupuesto "
                    f"{perf.number(TRACES_BUDGET_S, 0)} s")
        self.assertTrue(bool(traces.computed.all()))
        self.assertEqual(traces.warnings, ())
        self.assertEqual(xyz.shape, (POSITIONS, 3))
        self.assertTrue(bool(np.isfinite(xyz).all()))
        self.assertLessEqual(statistics.median(times), TRACES_BUDGET_S)


# --- La importación de principio a fin (RNF-005-01; R12 y R17) -------------------------------


def _new_project(folder: Path) -> tuple[Any, Any]:
    """Un proyecto nuevo en ``folder`` (EPSG:25830 y EPSG:5782, con la ventana de trabajo de
    V-ref) con su rejilla del proyecto ``gis_dtm_terreno`` (el MDT de 1 m de V-ref, escrita
    con la API de la 006 como la deja «Rejilla del proyecto desde un MDT»): el proyecto y el
    registro de la rejilla."""
    (folder / "proyectos").mkdir()
    window = _DATA.window
    settings = make_settings(window=(window.xmin, window.ymin, window.xmax, window.ymax))
    project = create.create_project(folder / "proyectos", settings, make_session(),
                                    userdata_mod.UserData(folder / "u")).project
    try:
        handle = operations.begin_operation(project, gis_provenance.RESAMPLE, settings={},
                                            executor="blender")
        crs, vertical = gis_store.project_references(project)
        dtm = raster.Raster(_DATA.dtm.grid, _DATA.dtm.values, crs, vertical)
        with gis_store.ResultWriter(project, handle) as out:
            out.raster(PROJECT_SURFACE, dtm)
            out.commit(software=dict([gis_crs.crs_library()]))
        (found,) = gis_store.list_gis_datasets(project, families=(gis_provenance.PROJECT_GRID,))
    except BaseException:
        project.close()
        raise
    return project, found


@dataclasses.dataclass(eq=False)
class _Entry:
    """Un fichero de V-ref en la orden de importación: su papel, su ruta, su correspondencia
    de columnas, su operación y sus trabajos (como ``_Entry`` de ``bl/ops/dh.py``)."""

    role: str
    path: Path
    mapping: Mapping[str, str]
    handle: Any
    read: Any = None  # el JobHandle y, terminado, el JobResult de su lectura
    outcome: Any = None
    spec: Any = None
    applied: Any = None  # el JobHandle y, terminado, el JobResult de su aplicación


def _launch_order(entries: Sequence[_Entry]) -> list[_Entry]:
    """El orden en que lanza las lecturas ``bl/ops/dh.py`` (``launch_order``): la del fichero
    más grande primero; los del mismo tamaño, en su orden."""
    return sorted(entries, key=lambda entry: entry.path.stat().st_size, reverse=True)


class _Importer(dh_import.ImportDriver):
    """La importación de V-ref en ``project`` con el lanzador ``runner``, como la hace
    ``bl/ops/dh.py`` (plan §5.6.5: ``start_order``, ``_read_job``, ``_after_reading``,
    ``_apply`` e ``_import_steps``, y la base y su validación de
    ``tests.support.dh_import``): sus pasos seguidos, con la hora en que acaba cada fase
    (:data:`PHASES`). ``mappings``: la columna de cada campo por papel (la propuesta del
    asistente); ``surface``: la rejilla del proyecto con que se valida."""

    def __init__(self, project: Any, runner: Any, mappings: Mapping[str, Mapping[str, str]],
                 surface: Any) -> None:
        super().__init__(project, runner, job_label="Rendimiento")
        self.mappings = mappings
        self.surface = surface
        self.declaration = _declaration(_DATA.units)
        self.catalogs: Any = None  # los del proyecto al empezar la orden
        self.marks: list[float] = []

    def mark(self) -> None:
        self.marks.append(time.perf_counter())

    def run(self) -> list[float]:
        """La importación entera; la hora en que acaba cada fase (``time.perf_counter``)."""
        entries = self.read()
        self.mark()
        self.apply(entries)
        self.mark()
        self.write_sources(entries)
        self.mark()
        self.build_base()
        self.mark()
        self.validate(self.surface)
        self.mark()
        return self.marks

    # --- Lectura y aplicación de cada fichero (start_order, _after_reading, _apply) ---------

    def operation_settings(self, entry_role: str, path: Path,
                           mapping: Mapping[str, str]) -> dict[str, Any]:
        conventions = self.declaration.conventions()
        conventions["sentinels"] = ";".join(conventions["sentinels"])
        return {"name": path.stem, "file": path.name, "reader": provenance.DH_CSV,
                "role": entry_role, "mapping": dict(mapping), **ENTRY_READING,
                "decimal": DECIMAL, "date_format": DATE_FORMAT, **conventions}

    def read(self) -> list[_Entry]:
        """Las importaciones ``dh.import_tabular`` de los ficheros, «en curso» a la vez (una
        transacción, ``begin_operations``), y sus lecturas (``dh_import_tabular``, en proceso
        aparte, con el fichero por ruta), lanzadas en el orden de ``bl/ops/dh.py``
        (:func:`_launch_order`), hasta que terminan todas."""
        with self.project.read() as conn:
            catalogs = store.read_catalogs(conn)
            holes = store.holes_by_table(conn)
        self.catalogs = catalogs
        files = [(str(role), _DATA.folder / "vref" / name) for role, name in FILES.items()]
        handles = operations.begin_operations(
            self.project, provenance.IMPORT_TABULAR,
            settings=[self.operation_settings(role, path, self.mappings[role])
                      for role, path in files], executor="job_process")
        entries = [_Entry(role, path, self.mappings[role], handle)
                   for (role, path), handle in zip(files, handles, strict=True)]
        for entry in _launch_order(entries):
            params = {"name": entry.path.stem,
                      "declaration": dh_jobs.declaration_json(self.declaration),
                      "settings": {**ENTRY_READING, "decimal": DECIMAL,
                                   "date_format": DATE_FORMAT},
                      "crs": gis_jobs.crs_json(self.crs),
                      "vertical": gis_jobs.vertical_json(self.vertical),
                      "project_holes": {table: list(names) for table, names in holes.items()},
                      "catalogs": dh_arrays.catalogs_json(catalogs),
                      "size": entry.path.stat().st_size, "reader": provenance.DH_CSV,
                      "role": entry.role, "mapping": dict(entry.mapping)}
            entry.read = self.submit(entry.handle, dh_jobs.IMPORT_TABULAR, params,
                                     name=entry.path.stem,
                                     paths={gis_jobs.path_name("main"): entry.path})
        for entry, result in zip(entries, self.wait_all([entry.read for entry in entries]),
                                 strict=True):
            entry.read = result
            entry.outcome = self.outcome(result)
        return entries

    def input_spec(self, entry: _Entry) -> Any:
        found = entry.outcome.summary["source"]
        main = found["files"]["main"]
        anchor = inputs_mod.locate_source(entry.path, self.project, self.project.userdata,
                                          role="main")
        prints = [inputs_mod.SourcePrint(main["sha256"], size=main["size"],
                                         mtime_ns=main["mtime_ns"])]
        return provenance.input_spec(
            provenance.DH_CSV, entry.path.stem, files=[anchor], file_prints=prints,
            digest=gis_jobs.digest_of(found["digest"]), declaration=self.declaration,
            role=entry.role, mapping=dict(entry.mapping), settings=dict(ENTRY_READING))

    @staticmethod
    def register_for(entries: Sequence[_Entry], entry: _Entry) -> dict[str, list[Any]]:
        """Los códigos nuevos que da de alta ``entry`` (los suyos, salvo los que trae un
        catálogo de la orden), como ``_register_for`` de ``bl/ops/dh.py``."""
        found = dict(entry.outcome.summary.get("register_codes") or {})
        if entry.role in CATALOG_ROLES:
            return found
        provided: dict[str, set[str]] = {}
        for other in entries:
            if other.role in CATALOG_ROLES:
                for kind, items in dict(other.outcome.summary.get("register_codes")
                                        or {}).items():
                    provided.setdefault(kind, set()).update(json.dumps(item) for item in items)
        chosen = {kind: [item for item in items
                         if json.dumps(item) not in provided.get(kind, set())]
                  for kind, items in found.items()}
        return {kind: items for kind, items in chosen.items() if items}

    def apply(self, entries: Sequence[_Entry]) -> None:
        """Cada entrada, clasificada (una entrada nueva) y aplicada con los códigos nuevos
        dados de alta (``dh_import_apply``, con lo leído por ruta: lo copia su trabajo),
        hasta que terminan todas."""
        with self.project.read() as conn:
            for entry in entries:
                entry.spec = self.input_spec(entry)
                found = inputs_mod.classify_import(conn, entry.spec)
                if not isinstance(found, inputs_mod.New):
                    raise AssertionError(f"«{entry.path.name}» no es una entrada nueva: {found}")
        taken = [code.color for code in self.catalogs.lithology]
        for entry in entries:
            summary = entry.outcome.summary
            params = {"name": entry.path.stem, "crs": gis_jobs.crs_json(self.crs),
                      "keep_holes": [],
                      "replace_holes": {str(table): list(names) for table, names in
                                        dict(summary.get("existing_tables") or {}).items()},
                      "register_codes": self.register_for(entries, entry),
                      "taken_colors": taken,
                      "count": int(dict(summary.get("counts") or {}).get("imported", 0)) + 1}
            entry.applied = self.submit(
                entry.handle, dh_jobs.IMPORT_APPLY, params, name=entry.path.stem,
                paths={dh_jobs.INPUT_SOURCE: entry.outcome.file(dh_jobs.OUT_SOURCE.role)})
        for entry, result in zip(entries, self.wait_all([entry.applied for entry in entries]),
                                 strict=True):
            entry.applied = result

    # --- Lo importado (_import_steps) -------------------------------------------------------

    def write_sources(self, entries: Sequence[_Entry]) -> None:
        """Lo importado de la orden por pasos en una transacción (``SourceWriter``), la regla
        bajo el límite de detección de la primera importación y el original de cada fichero
        desde la copia verificada de su lectura; los trabajos, incorporados."""
        writer = store.SourceWriter(self.project)
        written = []
        for entry in entries:
            applied = self.outcome(entry.applied)
            tables: dict[str, Any] = {}
            contents: dict[str, Any] = {}
            for name, output in dict(applied.summary["outputs"]).items():
                role = name.removeprefix("dh_src_")
                tables[role] = dh_jobs.read_table_output(applied.file(name), name)
                contents[role] = gis_jobs.digest_of(output["digest"])
            report = json.loads(entry.outcome.file(dh_jobs.OUT_REPORT.role)
                                .read_text(encoding="utf-8"))
            counts = dict(report.get("counts") or {})
            log = [store.LogLine.summary(entry.role, int(counts.get("read", 0)),
                                         int(counts.get("imported", 0)),
                                         int(counts.get("rejected", 0)))]
            log += [store.LogLine.rejection(model.Rejection(*item))
                    for item in report.get("rejected", ())]
            log += [store.LogLine.warning(entry.role, str(text))
                    for text in report.get("warnings", ())]
            item = writer.add(entry.handle, entry.spec, tables, name=entry.path.stem,
                              contents=contents, log=log,
                              message=f"Tabla de sondeos «{entry.path.name}» importada",
                              interpreter=entry.outcome.interpreter,
                              executor=entry.outcome.executor, job_uid=entry.read.job_uid)
            written.append((entry, item))
        dh_import.drive(writer.steps(software=self.software))
        parameters = core_params.ParameterStore(self.project)
        with self.project.write_transaction() as conn:
            for key in dh_params.BELOW_DL_KEYS:
                parameters.ensure_default(
                    conn, key, geoblender_version=self.project.session.geoblender_version)
        for entry, item in written:
            verified = entry.read.job_dir.inputs_dir / (gis_jobs.path_name("main")
                                                        + entry.path.suffix)
            dh_import.drive(writer.originals(item, [verified]))
        for entry in entries:
            self.release(entry.read, entry.applied)


def _mappings() -> dict[str, dict[str, str]]:
    """La correspondencia de columnas que propone el asistente para cada fichero de V-ref
    (con las primeras filas que enseña)."""
    found = {}
    for role, name in FILES.items():
        columns = csv_tables.preview_table(_DATA.folder / "vref" / name, **READING).columns
        found[str(role)] = dict(tabular.suggest_mapping(role, columns))
    return found


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _megabytes(value: int) -> str:
    return perf.number(value / 1e6, 1)


class ImportTest(unittest.TestCase):
    """RNF-005-01: importar V-ref desde CSV de principio a fin (y R12 y R17 del plan, con el
    proyecto de la última repetición)."""

    times: list[float]
    phases: list[list[float]]
    executors: str  # dónde corrió cada trabajo de la última, por tipo
    counts: dict[str, int]  # las filas de la base y de las incidencias tras la última
    statuses: list[tuple[str, str, int]]  # sus operaciones, por tipo y estado

    @classmethod
    def setUpClass(cls) -> None:
        """:data:`IMPORT_REPETITIONS` importaciones de V-ref, cada una en un proyecto nuevo
        con su MDT; la última queda abierta para las pruebas."""
        stack = ExitStack()
        cls.addClassCleanup(stack.close)
        dh_import.registrations(stack)
        mappings = _mappings()
        cls.times, cls.phases = [], []
        for number in range(IMPORT_REPETITIONS):
            last = number == IMPORT_REPETITIONS - 1
            run_stack = stack if last else ExitStack()  # la última sigue abierta
            try:
                folder = Path(run_stack.enter_context(tempfile.TemporaryDirectory(
                    prefix="gb-dhi-", ignore_cleanup_errors=True)))
                project, found = _new_project(folder)
                run_stack.callback(project.close)
                runner = dh_import.new_runner(folder, project)
                run_stack.callback(runner.shutdown)
                importer = _Importer(project, runner, mappings, found)
                gc.collect()
                start = time.perf_counter()
                marks = importer.run()
                cls.times.append(marks[-1] - start)
                cls.phases.append([end - begin for begin, end
                                   in zip([start, *marks[:-1]], marks, strict=True)])
                cls.executors = importer.executors_text()
                cls.folder, cls.project, cls.runner = folder, project, runner
                cls.importer, cls.surface = importer, found
                with project.read() as conn:
                    cls.counts = {table: conn.execute(f'SELECT count(*) FROM "{table}"')
                                  .fetchone()[0] for table in COUNTED}
                    cls.levels = conn.execute(
                        "SELECT level, count(*) FROM dh_validation_issue GROUP BY level "
                        "ORDER BY level").fetchall()
                    cls.statuses = conn.execute(
                        "SELECT op_type, status, count(*) FROM gb_operation "
                        "GROUP BY op_type, status ORDER BY op_type").fetchall()
            finally:
                if not last:
                    run_stack.close()

    def query(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def test_import_vref_end_to_end(self) -> None:
        """RNF-005-01: importar los seis CSV de V-ref de principio a fin (lectura con el hash
        de cada fuente, aplicación con el de lo importado, su escritura con los originales,
        la base con sus conversiones y su hash y su validación con el MDT) en ≤ 30 s (mediana
        de :data:`IMPORT_REPETITIONS`); el proyecto queda con la base de V-ref entera, sin
        incidencias, y cada operación hecha."""
        phases = [statistics.median(run[index] for run in self.phases)
                  for index in range(len(PHASES))]
        shown = ", ".join(f"{name} {perf.number(value)} s"
                          for name, value in zip(PHASES, phases, strict=True))
        perf.report(f"RNF-005-01: importar V-ref desde sus 6 CSV de principio a fin "
                    f"({_volume()}; {shown}; trabajos: {self.executors}; {MACHINE}): "
                    f"{perf.median_line(self.times)}, presupuesto "
                    f"{perf.number(IMPORT_BUDGET_S, 0)} s")
        # Sin incidencias: en dh_validation_issue (T56, RF-005-18), solo la diferencia de cada
        # boca con el MDT, dentro de la tolerancia.
        self.assertEqual(self.counts, dict(zip(COUNTED, (
            VREF_HOLES, VREF_STATIONS, VREF_LITHOLOGY, VREF_VALUES, VREF_HOLES), strict=True)))
        self.assertEqual(self.levels, [("info", VREF_HOLES)])
        self.assertEqual(self.statuses, [("dh.build_base", "done", 1),
                                         ("dh.import_tabular", "done", len(FILES)),
                                         ("dh.validate", "done", 1),
                                         ("gis.resample", "done", 1)])
        self.assertLessEqual(statistics.median(self.times), IMPORT_BUDGET_S)

    def test_project_size(self) -> None:
        """RNF-005-01 (riesgo R12 del plan): el proyecto con V-ref importado, anotado: el
        tamaño de ``project.gpkg`` y de la carpeta del proyecto (con los originales y el MDT)
        y las filas de lo importado (``dh_src_*``) y de la base, que están dos veces."""
        def rows(pattern: str) -> int:
            tables = [name for (name,) in self.query(
                "SELECT table_name FROM gpkg_contents WHERE table_name GLOB ? "
                "ORDER BY table_name", pattern)]
            return sum(self.query(f'SELECT count(*) FROM "{name}"')[0][0] for name in tables)

        imported = rows("dh_src_*")
        base = sum(self.query(f'SELECT count(*) FROM "{name}"')[0][0]
                   for name in schema.BASE_TABLES)
        database = _size(Path(self.project.database_path))
        folder = _size(Path(self.project.root))
        perf.report(f"RNF-005-01: tamaño del proyecto con V-ref (R12): project.gpkg "
                    f"{_megabytes(database)} MB y la carpeta del proyecto {_megabytes(folder)} MB "
                    f"(con los originales de los 6 CSV y el MDT); {perf.count(imported)} filas "
                    f"en lo importado y {perf.count(base)} en la base ({MACHINE})")
        self.assertGreaterEqual(min(imported, base), VREF_VALUES)

    def test_base_rebuilt_without_triggers_per_row(self) -> None:
        """RNF-005-01 (riesgo R17 del plan; RF-008-21, RF-008-26): la base reconstruida con lo
        mismo (otra ``dh.build_base``, como un recálculo) da el mismo hash de cada tabla y sus
        tablas se crean de nuevo y se siguen (``gbtc_``) con todas sus filas ya escritas: los
        disparadores no saltan por fila. Lo que costarían por fila, medido aparte insertando
        :data:`TRIGGER_ROWS` filas de ``dh_assay`` en una tabla seguida y en otra sin seguir;
        se anotan las dos cifras."""
        before = dict(self.query(
            "SELECT name, content_sha256 FROM gb_dataset WHERE status = 'current' AND name IN "
            f"({', '.join('?' * len(schema.BASE_TABLES))})", *schema.BASE_TABLES))
        filled: dict[str, int] = {}
        track = tracking.track_table

        def noted(conn: sqlite3.Connection, table: str) -> bool:
            filled[table] = conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            return track(conn, table)

        with mock.patch.object(tracking, "track_table", noted):
            start = time.perf_counter()
            self.importer.build_base()
            rebuilt = time.perf_counter() - start
        after = dict(self.query(
            "SELECT name, content_sha256 FROM gb_dataset WHERE status = 'current' AND name IN "
            f"({', '.join('?' * len(schema.BASE_TABLES))})", *schema.BASE_TABLES))
        self.assertEqual(after, before)
        self.assertEqual(set(filled), set(schema.BASE_TABLES))
        self.assertEqual(filled["dh_assay"], VREF_VALUES)
        triggers = {name for (name,) in self.query(
            "SELECT name FROM sqlite_master WHERE type = 'trigger' AND name GLOB 'gbtc_dh_*'")}
        self.assertTrue({name for table in schema.BASE_TABLES
                         for name in tracking.tracking_trigger_names(table)} <= triggers)
        columns = ", ".join(f'"{name}"' for name in schema.LAYOUTS["dh_assay"].insert_columns)
        sample = self.query(f"SELECT {columns} FROM dh_assay ORDER BY fid LIMIT ?",
                            TRIGGER_ROWS)
        plain, with_triggers = (_insert_seconds(self.folder / f"disparadores-{follow}.gpkg",
                                                sample, tracked=follow)
                                for follow in (False, True))
        per_row = (with_triggers - plain) / len(sample)
        total_rows = sum(filled.values())
        perf.report(f"RNF-005-01: la base de V-ref reconstruida con lo mismo (R17; lectura de "
                    f"lo importado, dh_build_base y escritura): {perf.number(rebuilt)} s, el "
                    f"mismo hash de sus 11 tablas, cada una seguida con sus filas ya escritas "
                    f"(los disparadores gbtc_ no saltan por fila); insertar "
                    f"{perf.count(len(sample))} filas de dh_assay: {perf.number(plain)} s sin "
                    f"seguir y {perf.number(with_triggers)} s seguida, "
                    f"{perf.number(per_row * 1e6, 2)} µs más por fila (con las "
                    f"{perf.count(total_rows)} filas de la base serían "
                    f"{perf.number(per_row * total_rows)} s; {MACHINE})")


def _insert_seconds(path: Path, rows: Sequence[Sequence[Any]], *, tracked: bool) -> float:
    """Lo que tarda insertar ``rows`` (filas de ``dh_assay``, sin su ``fid``) con
    ``schema.insert_rows`` en una tabla ``dh_assay`` nueva de un GeoPackage nuevo en
    ``path``, en una transacción, con los disparadores del seguimiento (``tracked``) o sin
    ellos."""
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        conn.execute("BEGIN")
        gpkg_base.create_base(conn, dh_sets.H25830)
        layout = schema.LAYOUTS["dh_assay"]
        schema.create_table(conn, layout, layout.name, None)
        if tracked:
            tracking.track_table(conn, layout.name)
        conn.execute("COMMIT")
        conn.execute("BEGIN")
        start = time.perf_counter()
        schema.insert_rows(conn, layout, layout.name, rows)
        conn.execute("COMMIT")
        return time.perf_counter() - start
    finally:
        conn.close()
        path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()

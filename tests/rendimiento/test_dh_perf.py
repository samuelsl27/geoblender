# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendimiento de los sondeos con V-ref (spec 005 §5; hito H1.4, medida preliminar de
RNF-005-02 y RNF-005-03; plan 005 §7, ``tests/rendimiento``).

Se ejecuta con ``tools/check.py --rendimiento``: el Python de Blender (su numpy 2.3.4) en el
PC de referencia de la spec 001 §5, en disco local (``%TEMP%``). Cada cifra es la mediana de
5 repeticiones, se imprime en una línea ``RNF-005-nn: …`` con el equipo y el intérprete
(``tools/check.py`` las recoge) y se compara con su presupuesto. La T31 añade aquí
RNF-005-01 (la importación de principio a fin, con el almacén de la fase 2) y deja las cifras
definitivas; RNF-005-04 y RNF-005-06 se miden dentro de Blender (T32) y RNF-005-05, con el
motor de Access (T43).

**Datos** (spec 005 §5; se generan y no se versionan): V-ref de
``tests/data/dh/sintetico.py`` (semilla fija) en una carpeta temporal, leído con el lector
real (``interop.csv_tables.read_table`` e ``interop.drillholes_tabular.read_drillholes``):
2.000 sondeos, 20.000 estaciones, 50.000 tramos de litología y 25.000 tramos con 20
elementos (500.000 valores), en convenios internos (azimut de cuadrícula, inclinación
negativa hacia abajo). El MDT, una rejilla de 1 m (``gis.raster.Raster``) con la superficie
de ``tests/data/gis`` sobre la que están las bocas de V-ref, muestreado con la bilineal de la
006 (``drillholes.surface.raster_sampler``), y la ventana de trabajo, la de las bocas con
50 m de margen: V-ref no tiene incidencias.

- RNF-005-02: ``drillholes.validate.validate`` de V-ref con el MDT y la ventana de trabajo
  (las 27 comprobaciones de la tabla 4.4.1, DH-W05 incluida): ≤ 5 s.
- RNF-005-03: las trazas por mínima curvatura de los 2.000 sondeos
  (``drillholes.desurvey.desurvey``) más la posición de 100.000 profundidades al azar
  (``drillholes.desurvey.md_to_xyz``): ≤ 2 s.
"""

import math
import statistics
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

from tests.data.dh import sintetico
from tests.support import dh_sets
from tests.support import gis_perf as perf
from tests.support.dh_fakes import gis_surface
from tests.support.package import import_geoblender

csv_tables = import_geoblender("interop.csv_tables")
tabular = import_geoblender("interop.drillholes_tabular")
model = import_geoblender("drillholes.model")
validate = import_geoblender("drillholes.validate")
desurvey = import_geoblender("drillholes.desurvey")
surface = import_geoblender("drillholes.surface")
georef = import_geoblender("core.georef")
grid = import_geoblender("gis.grid")
raster = import_geoblender("gis.raster")

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


# --- Datos ---------------------------------------------------------------------------------


def _declaration(units: dict[str, str]) -> object:
    """Lo que declara quien importa V-ref (el formato de ``csv_basico``): EPSG:25830 y
    EPSG:5782, azimut de cuadrícula, inclinación negativa hacia abajo, coma decimal, fechas
    dd/mm/aaaa y la unidad de cada elemento de su catálogo."""
    return model.SourceDeclaration(
        crs=dh_sets.H25830, vertical=dh_sets.V5782, azimuth_ref=model.AzimuthRef.GRID,
        declination_deg=None, inclination_convention=model.InclinationConvention.NEGATIVE_DOWN,
        units=units, value_rules=model.ValueRules(decimal_mark=","),
        date_format="%d/%m/%Y")


def _read_vref(folder: Path) -> object:
    """V-ref escrito en ``folder`` y leído con el lector real."""
    sintetico.write_vref(folder)
    tables = {role: csv_tables.read_table(folder / name, encoding="utf-8", separator=";")
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

    dset: object
    dtm: object
    window: object


_DATA = _Data()


def setUpModule() -> None:
    """V-ref en una carpeta temporal (que se borra en seguida), leído; su MDT y su ventana."""
    with tempfile.TemporaryDirectory(prefix="gb-dh-perf-") as folder:
        _DATA.dset = _read_vref(Path(folder))
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


if __name__ == "__main__":
    unittest.main()

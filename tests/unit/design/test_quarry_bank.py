# SPDX-License-Identifier: GPL-3.0-or-later
"""La comparación del banco de la cantera con dos superficies con una carpeta sintética con la
forma del banco (spec 014, T37; CE-014-09; HU-014-3, HU-014-4; RF-014-13 a RF-014-18; plan 014
§7.1).

``tests/banco/silvestre/test_quarry.py`` solo lo ejecuta el arnés de los bancos con el banco real
(lo hace una persona en el H3). Aquí se comprueba que se omite sin la variable y que, con una
carpeta **sintética** con la forma que espera (creada en ``%TEMP%`` y señalada por la variable solo
dentro de cada prueba), reproduce las dos superficies, sus cifras y «explotación hasta la final» de
su ficha; que cada diferencia cae en su clase y hace fallar solo la comprobación que le toca; y que
dice todo lo que no encuentra.

La carpeta (rejilla de 40 × 60 celdas de 2 m; terreno en ladera, ``z = 180 + 0,25·y + 0,0625·x``
con ``x`` e ``y`` en m desde la esquina suroeste, exacto en binario, en un MDT del doble de
resolución fuera de las versiones): en la versión vigente, la ficha de la cantera y sus rásteres
(las tres superficies de la referencia en Float32 con −9999 sin dato, como las del proyecto de
referencia; las zonas de «explotación hasta la final» en un ``.npy``); en una superada, una ficha y
una superficie final que no se usan.

- **El recinto**: las filas 4 a 35 y las columnas 4 a 55 (1.664 celdas). **Los fondos**: un
  rectángulo a 172 m (filas 14 a 23, columnas 10 a 21). **El relleno**: las filas 8 a 13 y las
  columnas 46 a 53.
- **La final** (``REST``: 5 m, 35°, 6 m, ancla 125 m), desde la coronación de 3 celdas del recinto.
- **La explotación** (``EXPL``: 10 m, 60°, 6 m), con el ancla «al fondo de cada muro» y sus semillas
  en la coronación y en el terreno de la franja este del recinto (columnas 40 a 55), que se queda
  sin explotar: allí la final queda muy por debajo y sale el aviso de desdoblado sobre terreno sin
  explotar (con un área mínima de 0,05 ha en la ficha); «explotación hasta la final» la baja en las
  zonas avisadas.
- «Final primero».

Las superficies de la referencia las hace esta prueba con ``design.quarry.quarry_steps`` y su
propio montaje (no el de la comparación), y las cifras de la ficha, a mano con numpy sobre ellas tal
como quedan guardadas en Float32.
"""

from __future__ import annotations

import contextlib
import functools
import io
import json
import math
import os
import shutil
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any
from unittest import mock

import numpy as np

from tests.banco.silvestre import test_quarry as bank
from tests.support import bank_folder as shape
from tests.support import constraints_fixtures as fx
from tests.support.package import import_geoblender

gis = import_geoblender("gis")
geotiff = import_geoblender("gis.geotiff")
model = import_geoblender("design.model")
params = import_geoblender("design.params")
quarry = import_geoblender("design.quarry")
seeds_mod = import_geoblender("design.seeds")

WEST, NORTH = 700_000.0, 4_400_000.0
STEP = 2.0
ROWS, COLS = 40, 60
GRID = gis.Grid(WEST, NORTH, STEP, STEP, COLS, ROWS)
AREA_BOX = ((4, 36), (4, 56))
FLOOR_BOX, FLOOR_LEVEL = ((14, 24), (10, 22)), 172.0
FILL_BOX = ((8, 14), (46, 54))
EAST_COLUMNS = slice(40, 56)
RING_CELLS = 3
MIN_AREA_HA = 0.05
E = 0.02  # el espesor mínimo de la comparación (D-6 de la 012)
FINAL_PROFILE = model.BenchProfile("final", "final", 5.0, 35.0, 6.0, 125.0, 1.0)
EXPLOITATION_PROFILE = model.BenchProfile("explotacion", "explotacion", 10.0, 60.0, 6.0, 125.0,
                                          1.0)
VERSION = Path("disenos") / "V10_prueba_VIGENTE" / "modelos"
OLD = Path("disenos") / "V09_prueba_SUPERADO"
NAMES = MappingProxyType({
    "final": "Final_cantera_V10", "exploitation": "Explotacion_cantera_V10",
    "previous": "Explotacion_previa_V10", "area": "Recinto_V10", "fill": "Relleno_restauracion",
    "floors": "Fondos_V10", "seeds": "Semillas_explotacion_V10",
    "zones": "Zonas_hasta_la_final_V10"})
SHEET_NAME = "ficha_cantera.json"

THIN = "thin"
SHALLOW = "shallow"
ANCHOR = "anchor"
ORDER = "order"
FIGURE = "figure"
LOWERING = "lowering"
THIN_CELLS = 50
THIN_M = 0.01
SHALLOW_M = 0.03
ANCHOR_CELLS = 20
ORDER_CELLS = 30
LOWERING_CELLS = 15
THICKNESS_FIELD = "espesor_minimo_m"
SHEET_THICKNESS = 0.05
"""Otro espesor mínimo en la ficha (T52): más que el de la 012 por defecto (0,02 m) y que
:data:`SHALLOW_M`."""


def _box(box: tuple[tuple[int, int], tuple[int, int]]) -> np.ndarray:
    found = np.zeros(GRID.shape, dtype=bool)
    (row0, row1), (col0, col1) = box
    found[row0:row1, col0:col1] = True
    return found


def _terrain(grid: Any) -> np.ndarray:
    """``180 + 0,25·y + 0,0625·x`` en los centros de ``grid`` (m desde la esquina suroeste)."""
    rows, cols = np.indices(grid.shape)
    x = (cols + 0.5) * grid.dx
    y = (grid.nrows - rows - 0.5) * grid.dy
    return 180.0 + 0.25 * y + 0.0625 * x


def _write(path: Path, grid: Any, values: np.ndarray, *, deliverable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = gis.WriteProfile.DELIVERABLE if deliverable else gis.WriteProfile.PROJECT
    geotiff.GeoTiffIO().write(gis.Raster(grid, values, fx.CRS, fx.VERTICAL), path,
                              profile=profile)


def _stored(values: np.ndarray) -> np.ndarray:
    """``values`` como quedan en un GeoTIFF de coma flotante de 32 bits."""
    return values.astype(np.float32).astype(np.float64)


def _last(steps: Any) -> Any:
    found = None
    for found in steps:
        pass
    return found.result


@functools.cache
def _start() -> np.ndarray:
    """El terreno como lo ve la comparación: el MDT de 1 m llevado a la rejilla de 2 m por
    ``bank_folder.on_grid`` (la media por área) y leído; se hace una vez por proceso."""
    fine = gis.Grid(WEST, NORTH, STEP / 2.0, STEP / 2.0, COLS * 2, ROWS * 2)
    with tempfile.TemporaryDirectory(prefix="gb-014-t37-mdt-") as name:
        source = Path(name) / "MDT_sintetico.tif"
        _write(source, fine, _terrain(fine))
        ready = shape.on_grid(source, GRID, fx.CRS, fx.VERTICAL, Path(name), "partida",
                              "la superficie de partida")
        found = np.asarray(geotiff.read_geotiff(ready).values, dtype=np.float64)
    found.flags.writeable = False
    return found


class _Masks:
    """Las máscaras de mano de la referencia: el corte admitido en el recinto y nada más."""

    def __init__(self, cut: np.ndarray) -> None:
        self.grid = GRID
        self._cut = cut
        self.zones: dict[str, Any] = {}
        self.ctypes: Mapping[str, str] = MappingProxyType({})

    def zone(self, code: str) -> Any:
        return self.zones[code]

    def cut_allowed(self) -> np.ndarray:
        return self._cut.copy()

    def fill_allowed(self) -> np.ndarray:
        return np.zeros(GRID.shape, dtype=bool)

    def fill_strip(self) -> np.ndarray:
        return np.zeros(GRID.shape, dtype=bool)


def _seeds(start: np.ndarray) -> np.ndarray:
    """Las semillas de la explotación: el terreno en la coronación del recinto y en su franja
    este."""
    area = _box(AREA_BOX)
    chosen = quarry.crown_ring(area, start, RING_CELLS)
    east = np.zeros(GRID.shape, dtype=bool)
    east[:, EAST_COLUMNS] = True
    chosen |= area & east
    return np.where(chosen, start, np.nan)


@functools.cache
def _reference() -> Any:
    """Las superficies de la referencia y sus máscaras (sin defectos), una vez por proceso: el
    ``QuarryOutcome`` de ``quarry_steps`` con «explotación hasta la final» en las zonas avisadas."""
    start = _start()
    area = _box(AREA_BOX)
    domain = seeds_mod.domain_of(area & np.isfinite(start), np.zeros(GRID.shape, np.int16), (),
                                 GRID.cell_area)
    values = {params.bench_key(profile.code, param): getattr(profile, param.value)
              for profile in (FINAL_PROFILE, EXPLOITATION_PROFILE)
              for param in params.BenchParam}
    floor = _box(FLOOR_BOX)
    floors = quarry.FloorMap("fondos", "cota", np.where(floor, FLOOR_LEVEL, np.nan),
                             floor.astype(np.int32), (1,), (FLOOR_LEVEL,),
                             (int(floor.sum()),), GRID.cell_area)
    request = model.QuarryRequest(
        name="Referencia", start="terreno",
        final=model.QuarrySide(base_profile=FINAL_PROFILE.code),
        exploitation=model.QuarrySide(base_profile=EXPLOITATION_PROFILE.code,
                                      seeds=model.SeedSource("grid", grid="semillas"),
                                      anchor="nearest_floor"),
        order="final_first", fill_zones="relleno", to_final="warned")
    seeds = seeds_mod.collect_seeds(_seeds(start), None, domain, GRID)
    job = quarry.QuarryJob(
        request=request, start=start, masks=_Masks(area), domain=domain, values=values,
        ring_cells=RING_CELLS, min_thickness_m=E, face_tolerance_deg=1.0, warning_ratio=2.0,
        seeds={model.Surface.EXPLOITATION: seeds}, floors=floors, fill_zones=_box(FILL_BOX),
        unsplit_min_area_ha=MIN_AREA_HA)
    return _last(quarry.quarry_steps(job))


def _sheet(**changes: Any) -> dict[str, Any]:
    profile = {"altura_m": 5, "cara_deg": 35, "berma_m": 6, "ancla_m": 125}
    sheet: dict[str, Any] = {
        "orden": "final primero", "recinto": NAMES["area"], "relleno": NAMES["fill"],
        "fondos": NAMES["floors"],
        "final": {"referencia": NAMES["final"], "perfil": profile},
        "explotacion": {"referencia": NAMES["exploitation"], "previa": NAMES["previous"],
                        "semillas": NAMES["seeds"], "ancla": "al fondo de cada muro",
                        "perfil": {"altura_m": 10, "cara_deg": 60, "berma_m": 6,
                                   "ancla_m": 125}},
        "hasta_la_final": {"zonas": NAMES["zones"], "area_minima_ha": MIN_AREA_HA},
    }
    sheet.update(changes)
    return sheet


def figures(start: np.ndarray, final: np.ndarray, exploitation: np.ndarray,
            previous: np.ndarray, *, thin: bool = False, e: float = E) -> dict[str, float]:
    """Las cifras de la referencia a mano: la excavación de la explotación (``z − E > e``), el
    desdoblado y el relleno (``E − F > e``, fuera y dentro de las zonas de relleno; con ``thin``,
    el desdoblado de todo ``E − F > 0``, como si la referencia no tuviera espesor mínimo) y lo que
    pasó a la explotación (``Σ (previa − E) > 0``), en el recinto, con la celda de 4 m²; ``e``, el
    espesor mínimo (el de la 012 por defecto)."""
    area = _box(AREA_BOX)
    fill = _box(FILL_BOX)
    dug = start - exploitation
    delta = exploitation - final
    passed = previous - exploitation
    cell = GRID.cell_area
    return {
        "explotacion_m3": float(dug[area & (dug > e)].sum() * cell),
        "desdoblado_m3": float(delta[area & ~fill & (delta > (0.0 if thin else e))].sum() * cell),
        "relleno_m3": float(delta[area & fill & (delta > e)].sum() * cell),
        "hasta_la_final_m3": float(passed[area & (passed > 0.0)].sum() * cell),
    }


def _pick(mask: np.ndarray, count: int) -> tuple[np.ndarray, np.ndarray]:
    """Las ``count`` primeras celdas de ``mask``, fila a fila."""
    rows, cols = np.nonzero(mask)
    if rows.size < count:
        raise AssertionError(f"la prueba necesita {count} celdas y hay {rows.size}")
    return rows[:count], cols[:count]


def build_bank(root: Path, *, flaw: str | None = None, drop: tuple[str, ...] = (),
               sheet: dict[str, Any] | None = None, thickness: float | None = None) -> Path:
    """La carpeta sintética en ``root``. ``flaw``: ``"thin"`` (la final 1 cm por debajo de la
    explotación en 50 celdas iguales, y el desdoblado de la ficha contado sin espesor mínimo),
    ``"shallow"`` (la final 3 cm por debajo en esas 50 celdas, y las cifras con el espesor
    mínimo), ``"anchor"`` (en 20 celdas de las zonas, la explotación de la referencia baja hasta
    la final), ``"thin"`` y ``"anchor"`` juntos con ``"thin+anchor"``, ``"order"`` (la explotación
    0,5 m por encima del terreno en 30 celdas sin excavar; las cifras, las de antes), ``"figure"``
    (600 m³ más de desdoblado en la ficha) o ``"lowering"`` (en 15 celdas de las zonas, la
    explotación de la referencia a medio camino entre la final y la cota de ancla de encima).
    ``drop``: lo que no se escribe (``"sheet"``, ``"area"``, ``"previous"``, ``"start"``).
    ``sheet``: otra ficha. ``thickness``: el espesor mínimo de la ficha (``espesor_minimo_m``;
    las cifras se cuentan con él); sin él, la ficha no lo trae (el de la 012 por defecto)."""
    start = _start()
    outcome = _reference()
    final = _stored(outcome.final_grid)
    exploitation = _stored(outcome.exploitation_grid)
    previous = _stored(outcome.ordered.exploitation)
    zones = outcome.to_final.target
    area = _box(AREA_BOX)
    flaws = set() if flaw is None else set(flaw.split("+"))
    if flaws & {THIN, SHALLOW}:
        rows, cols = _pick(area & ~zones & ~_box(FILL_BOX) & (exploitation == final)
                           & (exploitation < start - 1.0), THIN_CELLS)
        depth = THIN_M if THIN in flaws else SHALLOW_M
        final[rows, cols] = _stored(exploitation[rows, cols] - depth)
    if ANCHOR in flaws:
        rows, cols = _pick(zones & (exploitation > final + 0.1), ANCHOR_CELLS)
        exploitation[rows, cols] = final[rows, cols]
    if LOWERING in flaws:
        rows, cols = _pick(zones & (exploitation > final + 0.1), LOWERING_CELLS)
        exploitation[rows, cols] = _stored((final[rows, cols] + exploitation[rows, cols]) / 2.0)
    found = figures(start, final, exploitation, previous, thin=THIN in flaws,
                    e=E if thickness is None else thickness)
    if FIGURE in flaws:
        found["desdoblado_m3"] += 600.0
    if ORDER in flaws:
        rows, cols = _pick(area & ~zones & (exploitation == start) & (final == start),
                           ORDER_CELLS)
        exploitation[rows, cols] = _stored(start[rows, cols] + 0.5)
    fine = gis.Grid(WEST, NORTH, STEP / 2.0, STEP / 2.0, COLS * 2, ROWS * 2)
    if "start" not in drop:
        _write(root / "entradas" / "MDT_sintetico.tif", fine, _terrain(fine))
    _write(root / OLD / f"{NAMES['final']}.tif", GRID, np.full(GRID.shape, 1.0))
    if "sheet" not in drop:
        (root / OLD / SHEET_NAME).write_text("{}", encoding="utf-8")
    folder = root / VERSION
    _write(folder / f"{NAMES['final']}.tif", GRID, final, deliverable=True)
    _write(folder / f"{NAMES['exploitation']}.tif", GRID, exploitation, deliverable=True)
    if "previous" not in drop:
        _write(folder / f"{NAMES['previous']}.tif", GRID, previous, deliverable=True)
    if "area" not in drop:
        _write(folder / f"{NAMES['area']}.tif", GRID, area.astype(np.float64))
    _write(folder / f"{NAMES['fill']}.tif", GRID, _box(FILL_BOX).astype(np.float64))
    floor = _box(FLOOR_BOX)
    _write(folder / f"{NAMES['floors']}.tif", GRID, np.where(floor, FLOOR_LEVEL, np.nan))
    _write(folder / f"{NAMES['seeds']}.tif", GRID, _seeds(start))
    np.save(folder / f"{NAMES['zones']}.npy", zones.astype(np.float64), allow_pickle=False)
    if "sheet" not in drop:
        text = _sheet(cifras={key: round(value, 3) for key, value in found.items()})
        if thickness is not None:
            text[THICKNESS_FIELD] = thickness
        (folder / SHEET_NAME).write_text(
            json.dumps(sheet if sheet is not None else text, ensure_ascii=False, indent=1),
            encoding="utf-8")
    return root


def _run(folder: Path | None) -> tuple[unittest.TestResult, str]:
    """La comparación del banco con ``folder`` en la variable (``None``: sin ella)."""
    environ = {key: value for key, value in os.environ.items() if key != bank.ENV}
    if folder is not None:
        environ[bank.ENV] = str(folder)
    suite = unittest.TestLoader().loadTestsFromTestCase(bank.ReferenceQuarryTest)
    result = unittest.TestResult()
    output = io.StringIO()
    with mock.patch.dict(os.environ, environ, clear=True), contextlib.redirect_stderr(output):
        suite.run(result)
    return result, output.getvalue()


def _state(folder: Path) -> list[tuple[str, int, int]]:
    return sorted((str(path.relative_to(folder)), path.stat().st_size, path.stat().st_mtime_ns)
                  for path in folder.rglob("*") if path.is_file())


def _failed(result: unittest.TestResult) -> list[str]:
    return sorted(str(test).split(" ")[0] for test, _ in result.failures)


def _shape_error(result: unittest.TestResult) -> str:
    """El mensaje del ``BankShapeError`` del único error de ``result``."""
    (_, text), = result.errors
    return text.rsplit("BankShapeError:", 1)[1]


class QuarryBankHarnessTest(unittest.TestCase):
    """CE-014-09: la comparación del banco de la cantera, con una carpeta sintética (RF-014-13 a
    RF-014-18)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = Path(tempfile.mkdtemp(prefix="gb-014-t37-"))
        cls.good = build_bank(cls.temp / "bien")

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.temp, ignore_errors=True)

    def test_a_skipped_without_the_variable(self) -> None:
        """CE-014-09: sin ``GEOBLENDER_SILVESTRE_DIR``, o si no es una carpeta, la comparación se
        omite con la orden que la activa, sin fallar."""
        for folder in (None, self.temp / "no-existe"):
            with self.subTest(folder=folder):
                result, _ = _run(folder)
                self.assertTrue(result.wasSuccessful())
                self.assertEqual(result.testsRun, 0)
                (_, reason), = result.skipped
                self.assertIn("OMITIDO: silvestre", reason)
                if folder is None:
                    self.assertIn("tools/check.py --banco", reason)

    def test_b_synthetic_bank_passes_and_stays_untouched(self) -> None:
        """CE-014-09, RF-014-13 a RF-014-18: con la carpeta sintética, la regla de orden no mueve
        las superficies de la referencia, sus cuatro cifras son las de la ficha, «explotación hasta
        la final» de Geoblender es la suya en todas las celdas de sus zonas y la cadena reproduce
        las dos superficies; imprime una línea por parte sin nombres del banco y no cambia la
        carpeta."""
        before = _state(self.good)
        result, output = _run(self.good)
        self.assertEqual(_state(self.good), before)
        self.assertEqual((result.testsRun, result.failures, result.errors, result.skipped),
                         (3, [], [], []), output)
        lines = [line for line in output.splitlines() if line.startswith(bank.NAME)]
        self.assertEqual(len(lines), 2 + 1 + 1 + 1)
        for word in (*NAMES.values(), "V10", "V09", "MDT", "ficha_cantera", str(self.good)):
            self.assertNotIn(word, output)
        found = bank.ReferenceQuarryTest.result
        cells = (AREA_BOX[0][1] - AREA_BOX[0][0]) * (AREA_BOX[1][1] - AREA_BOX[1][0])
        self.assertEqual(found.cells, cells)
        self.assertEqual((found.cell_area_m2, found.nominal_m2), (4.0, 4.0))
        # La ficha no trae el espesor mínimo: el de la 012 por defecto (D-6 de la 012).
        self.assertEqual(found.min_thickness_m, E)
        self.assertIn("espesor mínimo 0,02 m", output)
        for item in found.order:
            self.assertEqual((item.cells, item.equal, item.final_above, item.above_terrain,
                              item.nodata, item.changed_m3), (cells, cells, 0, 0, 0, 0.0))
            self.assertGreater(item.moved_m3, 0.0)
        self.assertEqual([item.key for item in found.figures], list(bank.FIGURES))
        for item in found.figures:
            self.assertEqual(item.verdict, bank.EQUAL)
            self.assertGreater(item.reference_m3, 0.0)
            self.assertLessEqual(abs(item.relative), 1e-6)
        outcome = _reference()
        to_final = found.to_final
        zone_cells = int(outcome.to_final.target.sum())
        self.assertEqual((to_final.zone_cells, to_final.equal, to_final.by_anchor,
                          to_final.unexplained, to_final.transition_cells),
                         (zone_cells, zone_cells, 0, 0, 0))
        self.assertAlmostEqual(to_final.found_m3, outcome.to_final.volume_m3, delta=1e-2)
        self.assertAlmostEqual(to_final.reference_m3, to_final.found_m3, delta=1e-2)
        self.assertGreaterEqual(to_final.warned_zones, 1)
        self.assertEqual(to_final.warned_in_reference, zone_cells)
        chain = found.chain
        self.assertIsNone(chain.error)
        self.assertEqual((chain.final.differing, chain.exploitation.differing), (0, 0))
        self.assertEqual((chain.final.cells, chain.exploitation.cells), (cells, cells))
        self.assertGreater(chain.adjusted, 0)
        self.assertEqual([item.verdict for item in chain.figures], [bank.EQUAL] * 4)

    def test_c_the_thickness_and_the_anchor_explain_their_differences(self) -> None:
        """CE-014-09, RF-014-15, RF-014-18: un desdoblado de la referencia contado sin espesor
        mínimo (50 celdas de 1 cm, 2 m³ más) queda explicado por el espesor mínimo, y 20 celdas
        de las zonas en que la referencia bajó la explotación hasta la final (Geoblender se queda
        en la cota de ancla de encima), por la cota de ancla; nada falla."""
        folder = build_bank(self.temp / "explicadas", flaw=f"{THIN}+{ANCHOR}")
        result, output = _run(folder)
        self.assertEqual((result.testsRun, result.failures, result.errors), (3, [], []), output)
        found = bank.ReferenceQuarryTest.result
        verdicts = {item.key: item for item in found.figures}
        unsplit = verdicts["desdoblado_m3"]
        self.assertEqual(unsplit.verdict, bank.THIN)
        # Geoblender da de menos justo lo que suma la clase hasta el espesor mínimo: los 2 m³ del
        # defecto y lo poco que la referencia ya tenía entre 0 y 2 cm.
        self.assertAlmostEqual(unsplit.found_m3 - unsplit.reference_m3, -unsplit.thin_m3,
                               delta=1e-2)
        self.assertGreaterEqual(unsplit.thin_m3, THIN_CELLS * THIN_M * GRID.cell_area - 1e-2)
        self.assertEqual({key: item.verdict for key, item in verdicts.items()
                          if key != "desdoblado_m3"},
                         dict.fromkeys(("explotacion_m3", "relleno_m3", "hasta_la_final_m3"),
                                       bank.EQUAL))
        self.assertEqual((found.to_final.by_anchor, found.to_final.unexplained),
                         (ANCHOR_CELLS, 0))
        self.assertIn(f"explicadas por la cota de ancla {ANCHOR_CELLS}", output)
        self.assertIn("explicada por el espesor mínimo", output)

    def test_d_an_exploitation_above_the_terrain_fails_only_the_order(self) -> None:
        """CE-014-09, RF-014-14: la explotación de la referencia 0,5 m por encima del terreno en
        30 celdas: la regla de orden mueve 30 · 0,5 · 4 = 60 m³, más de 10⁻⁴ de la excavación, y
        falla solo la comprobación del orden; las cifras, de las superficies ya ordenadas, y
        «explotación hasta la final» siguen bien."""
        folder = build_bank(self.temp / "orden", flaw=ORDER)
        result, _ = _run(folder)
        failed = _failed(result)
        self.assertEqual(len(failed), 1, failed)
        self.assertIn("test_the_reference_keeps_the_order_rule", failed[0])
        self.assertEqual(result.errors, [])
        self.assertIn("la explotación vigente", str(result.failures[0][1]))
        current, previous = bank.ReferenceQuarryTest.result.order
        self.assertEqual((current.above_terrain, current.final_above), (ORDER_CELLS, 0))
        self.assertAlmostEqual(current.changed_m3, ORDER_CELLS * 0.5 * GRID.cell_area, delta=1e-6)
        self.assertEqual(previous.changed_m3, 0.0)

    def test_e_a_figure_off_by_600_m3_fails_only_the_figures(self) -> None:
        """CE-014-09, RF-014-15: 600 m³ más de desdoblado en la ficha no los explica el espesor
        mínimo: falla solo la comprobación de las cifras, con el desdoblado en el mensaje."""
        folder = build_bank(self.temp / "cifra", flaw=FIGURE)
        result, _ = _run(folder)
        failed = _failed(result)
        self.assertEqual(len(failed), 1, failed)
        self.assertIn("test_the_figures_of_the_reference_are_reproduced", failed[0])
        self.assertIn("desdoblado", str(result.failures[0][1]))
        verdicts = {item.key: item.verdict for item in bank.ReferenceQuarryTest.result.figures}
        self.assertEqual(verdicts["desdoblado_m3"], bank.UNEXPLAINED)
        self.assertEqual(sum(verdict == bank.EQUAL for verdict in verdicts.values()), 3)

    def test_f_a_lowering_between_the_final_and_the_anchor_fails_only_to_final(self) -> None:
        """CE-014-09, RF-014-18: 15 celdas de las zonas con la explotación de la referencia a medio
        camino entre la final y la cota de ancla de encima (ni la suya ni la final) quedan sin
        explicar: falla solo la comprobación de «explotación hasta la final»."""
        folder = build_bank(self.temp / "bajada", flaw=LOWERING)
        result, _ = _run(folder)
        failed = _failed(result)
        self.assertEqual(len(failed), 1, failed)
        self.assertIn("test_to_final_in_the_reference_zones_is_explained", failed[0])
        item = bank.ReferenceQuarryTest.result.to_final
        self.assertEqual((item.unexplained, item.by_anchor), (LOWERING_CELLS, 0))
        self.assertGreater(item.unexplained_max_m, bank.EQUAL_M)

    def test_g_says_everything_it_does_not_find(self) -> None:
        """CE-014-09: sin el recinto, sin la explotación previa y sin el MDT, la comparación falla
        con la lista de todo lo que no encuentra, sin nombrar ningún fichero del banco; sin la
        ficha, lo dice con el patrón de su nombre."""
        folder = build_bank(self.temp / "incompleto", drop=("area", "previous", "start"))
        result, _ = _run(folder)
        self.assertEqual((result.testsRun, result.failures), (0, []))
        message = _shape_error(result)
        self.assertIn("el recinto", message)
        self.assertIn("la explotación previa de la referencia", message)
        self.assertIn("la superficie de partida", message)
        self.assertNotIn("la ficha de la cantera", message)
        for word in NAMES.values():
            self.assertNotIn(word, message)
        folder = build_bank(self.temp / "sin-ficha", drop=("sheet",))
        result, _ = _run(folder)
        message = _shape_error(result)
        self.assertIn("la ficha de la cantera", message)
        self.assertIn("ficha_cantera", message)

    def test_h_a_wrong_sheet_says_what_is_wrong_with_it(self) -> None:
        """CE-014-09: una ficha con un orden que no existe, una cara de 95°, el ancla «al fondo de
        cada muro» sin fondos, «previa» en la final y una cifra que no es de la ficha dice cada
        cosa, con su lado o su campo, y no calcula nada."""
        sheet = _sheet(orden="al revés", cifras={"desdoblado_m3": 1, "volumen_m3": 2})
        del sheet["fondos"]
        sheet["final"]["perfil"]["cara_deg"] = 95
        sheet["final"]["previa"] = NAMES["previous"]
        sheet[THICKNESS_FIELD] = 11
        folder = build_bank(self.temp / "ficha-mala", sheet=sheet)
        result, _ = _run(folder)
        self.assertEqual((result.testsRun, result.failures), (0, []))
        message = _shape_error(result)
        for text in ("«orden»", "al revés", "el lado «final»: el perfil no es válido",
                     "«previa» es de la explotación", "el lado «explotacion»: el ancla «al fondo "
                     "de cada muro» necesita «fondos»", "«volumen_m3» no es un campo",
                     "la ficha de la cantera: «espesor_minimo_m»: Parámetro "
                     "«res.verify.min_thickness_m»: 11", "fuera de su rango"):
            self.assertIn(text, message)

    def test_i_the_minimum_thickness_comes_from_the_sheet(self) -> None:
        """CE-014-09 (T52, F-21): la ficha trae el espesor mínimo del proyecto de referencia (su
        ``res.verify.min_thickness_m``, aquí 0,05 m) y la comparación cuenta con él, no con el de
        la 012 por defecto (0,02 m): 50 celdas con 3 cm de desdoblado (entre los dos) no cuentan
        ni en la ficha ni en Geoblender, pero sí en lo que suma su clase hasta el espesor mínimo;
        las cuatro cifras, las de la cadena y la excavación de la explotación (la base de la
        tolerancia del orden) son las de la ficha, y la línea de las cifras dice el espesor."""
        folder = build_bank(self.temp / "espesor", flaw=SHALLOW, thickness=SHEET_THICKNESS)
        result, output = _run(folder)
        self.assertEqual((result.testsRun, result.failures, result.errors, result.skipped),
                         (3, [], [], []), output)
        found = bank.ReferenceQuarryTest.result
        self.assertEqual(found.min_thickness_m, SHEET_THICKNESS)
        self.assertIn("espesor mínimo 0,05 m", output)
        verdicts = {item.key: item for item in found.figures}
        self.assertEqual(list(verdicts), list(bank.FIGURES))
        for item in found.figures:
            with self.subTest(figure=item.key):
                self.assertEqual(item.verdict, bank.EQUAL, bank._figure_text(item))
                self.assertLessEqual(abs(item.relative), 1e-6)
        self.assertGreaterEqual(verdicts["desdoblado_m3"].thin_m3,
                                THIN_CELLS * SHALLOW_M * GRID.cell_area - 1e-2)
        current = found.order[0]
        self.assertAlmostEqual(current.moved_m3, verdicts["explotacion_m3"].reference_m3,
                               delta=1e-2)
        self.assertIsNone(found.chain.error)
        self.assertEqual([item.verdict for item in found.chain.figures], [bank.EQUAL] * 4)


if __name__ == "__main__":
    unittest.main()

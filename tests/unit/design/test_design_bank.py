# SPDX-License-Identifier: GPL-3.0-or-later
"""La comparación del banco de las envolventes y el escalonado con una carpeta sintética con la
forma del banco (spec 013, T33; CE-013-10; HU-013-6; RF-013-11, RF-013-22, RF-013-25; plan 013
§7.1).

``tests/banco/silvestre/test_design.py`` solo lo ejecuta el arnés de los bancos con el banco real
(lo hace una persona en el H3). Aquí se comprueba que se omite sin la variable y que, con una
carpeta **sintética** con la forma que espera (creada en ``%TEMP%`` y señalada por la variable solo
dentro de cada prueba), reproduce las envolventes y los escalonados de su ficha y los explica; que
dice todo lo que no encuentra; y que cada tipo de diferencia hace fallar solo la comprobación que
le toca.

La carpeta (rejilla de 60 × 80 celdas de 2 m, terreno llano a 200 m en un MDT del doble de
resolución, fuera de las versiones): en la versión vigente, la ficha del diseño, las semillas, las
referencias y la máscara del sector; en una superada, una ficha y una referencia que no se usan.

- **Envolvente 1 (descendente)**: las semillas son la fila norte a 200 m, con una pendiente de
  10,6° (factor de malla 1); la referencia es el *chamfer* 5×5 hecho aparte con Dijkstra
  (``design_oracles``) en un dominio de 50 filas.
- **Envolvente 2 (ascendente)**: las semillas, la fila norte a 205 m, con 20° y factor de malla
  0,97; su referencia, el mismo cálculo, en un dominio interior (filas 5 a 54, columnas 4 a 75).
- **Escalonado 1 (corte)** sobre la envolvente 1 con un perfil de 5 m de altura, cara de 35°, berma
  de 6 m, ancla de 125 m y factor de malla 0,98, y un sector (la mitad oeste) con un talud general
  de 10,6° y la berma de la referencia, 19,6 m (la regla da 19,5765 m: el redondeo del literal).
- **Escalonado 2 (relleno)** sobre la envolvente 2 con un perfil de 10 m, cara de 60° y berma de
  6 m, sin sector.

Las referencias de los escalonados las hace esta prueba con el cálculo del dominio y su propio
montaje (no el de la comparación) sobre las envolventes de la referencia ya guardadas en float32.
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
import types
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

import numpy as np

from tests.banco.silvestre import test_design as bank
from tests.support import constraints_fixtures as fx
from tests.support import design_oracles as oracles
from tests.support.package import import_geoblender

gis = import_geoblender("gis")
geotiff = import_geoblender("gis.geotiff")
design_model = import_geoblender("design.model")
benching = import_geoblender("design.benching")
pipeline = import_geoblender("design.pipeline")
seeds_mod = import_geoblender("design.seeds")

WEST, NORTH = 700_000.0, 4_400_000.0
STEP = 2.0
ROWS, COLS = 60, 80
GRID = gis.Grid(WEST, NORTH, STEP, STEP, COLS, ROWS)
GROUND = 200.0
SLOPE_DOWN_DEG, SLOPE_UP_DEG, MESH_UP = 10.6, 20.0, 0.97
CREST_UP = 205.0
DOMAIN_DOWN = (slice(0, 50), slice(0, COLS))
DOMAIN_UP = (slice(5, 55), slice(4, 76))
SECTOR_COLUMNS = slice(0, 40)
CUT_PROFILE = (5.0, 35.0, 6.0, 125.0, 0.98)
FILL_PROFILE = (10.0, 60.0, 6.0, 125.0, 1.0)
IMPOSED_DEG = 10.6
LITERAL_BERM = 19.6
RULE_BERM = 5.0 / math.tan(math.radians(IMPOSED_DEG)) - 5.0 / math.tan(math.radians(35.0))
"""La berma de la regla (RF-013-25): 5/tan 10,6° − 5/tan 35° = 19,5765237 m."""

METRIC = "metric"
CONVERGENCE = "convergence"
WRONG_WAY = "wrong_way"
STEPPED = "stepped"
BERM = "berm"


def _write(path: Path, grid: object, values: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    geotiff.GeoTiffIO().write(gis.Raster(grid, values, fx.CRS, fx.VERTICAL), path,
                              profile=gis.WriteProfile.PROJECT)


def _stored(values: np.ndarray) -> np.ndarray:
    """``values`` como quedan en un GeoTIFF de coma flotante de 32 bits."""
    return values.astype(np.float32).astype(np.float64)


def _seeds(value: float) -> np.ndarray:
    found = np.full(GRID.shape, np.nan)
    found[0, :] = value
    return found


def _chamfer(seeds: np.ndarray, degrees: float, mesh: float, direction: str) -> np.ndarray:
    return oracles.dijkstra(seeds, math.tan(math.radians(degrees)) * mesh, STEP,
                            direction=direction)


def _exact(seeds: np.ndarray, degrees: float, mesh: float, direction: str) -> np.ndarray:
    return oracles.brute_force_euclidean(seeds, math.tan(math.radians(degrees)) * mesh, STEP,
                                         direction=direction)


def _clip(values: np.ndarray, domain: tuple[slice, slice]) -> np.ndarray:
    found = np.full(GRID.shape, np.nan)
    found[domain] = values[domain]
    return found


def _steps(envelope: np.ndarray, sense: str, profile: tuple[float, ...], *,
           sector: np.ndarray | None = None, berm: float | None = None) -> np.ndarray:
    """El escalonado del dominio sobre ``envelope`` con el montaje de esta prueba: terreno llano
    a ``GROUND``, nada vedado, y el sector con la berma ``berm`` de la referencia (sin talud
    impuesto) si la hay."""
    height, face, base_berm, anchor, mesh = profile
    base = design_model.BenchProfile("base", "base", height, face, base_berm, anchor, mesh)
    profiles = {"base": base}
    labels = np.zeros(GRID.shape, dtype=np.int16)
    sectors: tuple[object, ...] = ()
    assigned: dict[str, str] = {}
    if sector is not None:
        sectors = (seeds_mod.SectorRef("s", "Sector"),)
        labels[sector] = 1
        profiles["sector"] = replace(base, code="sector", name="sector", berm_m=berm)
        assigned = {"s": "sector"}
    everything = np.ones(GRID.shape, dtype=bool)
    masks = types.SimpleNamespace(cut_allowed=lambda: everything.copy(),
                                  fill_allowed=lambda: everything.copy(),
                                  fill_strip=lambda: np.zeros(GRID.shape, dtype=bool))
    job = pipeline.DesignJob(
        request=design_model.DesignRequest("Prueba", "Envolvente", sense, "base", assigned),
        geometry=GRID, start=np.full(GRID.shape, GROUND), envelope=envelope, masks=masks,
        sectors=sectors, labels=labels, imposed={}, profiles=profiles, anchors=None,
        min_thickness_m=0.02, face_tolerance_deg=1.0, warning_ratio=2.0)
    found = None
    for found in pipeline.design_compute_steps(job):
        pass
    return np.where(np.isfinite(envelope), found.result.design, np.nan)


@functools.cache
def _references(kind: str | None) -> tuple[np.ndarray, np.ndarray]:
    """Las referencias de las dos envolventes (con el defecto ``kind`` en la primera); se hacen
    una vez por proceso, porque el oráculo es lento: ``build_bank`` las copia."""
    function = _exact if kind == METRIC else _chamfer
    first = _clip(function(_seeds(GROUND), SLOPE_DOWN_DEG, 1.0, "down"), DOMAIN_DOWN)
    second = _clip(_chamfer(_seeds(CREST_UP), SLOPE_UP_DEG, MESH_UP, "up"), DOMAIN_UP)
    if kind == CONVERGENCE:
        first[40:50, :] -= 0.3
    if kind == WRONG_WAY:
        first[45, 10] += 0.5
    first.flags.writeable = second.flags.writeable = False
    return first, second


@functools.cache
def _cut_steps(kind: str | None, literal: float) -> np.ndarray:
    """La referencia del escalonado 1, de la envolvente de la referencia ya guardada."""
    sector = np.zeros(GRID.shape, dtype=bool)
    sector[:, SECTOR_COLUMNS] = True
    found = _steps(_stored(_references(kind)[0]), "cut", CUT_PROFILE, sector=sector,
                   berm=literal)
    found.flags.writeable = False
    return found


@functools.cache
def _fill_steps() -> np.ndarray:
    found = _steps(_stored(_references(None)[1]), "fill", FILL_PROFILE)
    found.flags.writeable = False
    return found


def _sheet(*, literal: float = LITERAL_BERM) -> dict[str, object]:
    return {
        "envolventes": [
            {"nombre": "talud", "sentido": "baja", "semillas": "Semillas_cresta_V03",
             "referencia": "Envolvente_talud_V03", "pendiente_deg": SLOPE_DOWN_DEG},
            {"nombre": "relleno", "sentido": "sube", "semillas": "Semillas_fondo_V03",
             "referencia": "Envolvente_relleno_V03",
             "pendiente_deg": SLOPE_UP_DEG, "factor_malla": MESH_UP},
        ],
        "escalonados": [
            {"nombre": "bancos", "sentido": "corte", "envolvente": "talud",
             "referencia": "Escalonado_corte_V03",
             "perfil": {"altura_m": 5, "cara_deg": 35, "berma_m": 6, "ancla_m": 125},
             "factor_malla": 0.98,
             "sector": {"mascara": "Sector_tendido", "talud_deg": IMPOSED_DEG,
                        "berma_m": literal}},
            {"nombre": "tongadas", "sentido": "relleno", "envolvente": "relleno",
             "referencia": "Escalonado_relleno_V03",
             "perfil": {"altura_m": 10, "cara_deg": 60, "berma_m": 6, "ancla_m": 125}},
        ],
    }


def build_bank(root: Path, *, flaw: str | None = None, drop: tuple[str, ...] = (),
               literal: float = LITERAL_BERM) -> Path:
    """La carpeta sintética en ``root``. ``flaw``: ``"metric"`` (la referencia de la envolvente 1
    hecha con la euclídea exacta), ``"convergence"`` (a 0,3 m por debajo en 800 celdas, del lado
    de un barrido que no llegó al punto fijo), ``"wrong_way"`` (una celda 0,5 m por encima),
    ``"stepped"`` (3 m más de corte en 50 celdas de la referencia del escalonado 1) o ``"berm"``
    (la berma de la referencia del sector, ``literal``, a más de medio decimal de la regla).
    ``drop``: lo que no se escribe (``"sheet"``, ``"seeds"``, ``"mask"``, ``"start"``)."""
    fine = gis.Grid(WEST, NORTH, STEP / 2.0, STEP / 2.0, COLS * 2, ROWS * 2)
    if "start" not in drop:
        _write(root / "entradas" / "MDT_sintetico.tif", fine, np.full(fine.shape, GROUND))
    old = root / "disenos" / "V02_prueba_SUPERADO"
    _write(old / "Envolvente_talud_V03.tif", GRID, np.full(GRID.shape, 1.0))  # la vigente manda
    if "sheet" not in drop:
        (old / "ficha_diseno.json").write_text("{}", encoding="utf-8")
    version = root / "disenos" / "V03_prueba_VIGENTE" / "modelos"
    if "seeds" not in drop:
        _write(version / "Semillas_cresta_V03.tif", GRID, _seeds(GROUND))
    _write(version / "Semillas_fondo_V03.tif", GRID, _seeds(CREST_UP))
    kind = flaw if flaw in (METRIC, CONVERGENCE, WRONG_WAY) else None
    first, second = _references(kind)
    _write(version / "Envolvente_talud_V03.tif", GRID, first)
    _write(version / "Envolvente_relleno_V03.tif", GRID, second)
    mask = np.zeros(GRID.shape)
    mask[:, SECTOR_COLUMNS] = 1.0
    if "mask" not in drop:
        _write(version / "Sector_tendido.tif", GRID, mask)
    cut = _cut_steps(kind, literal).copy()
    if flaw == STEPPED:
        cut[30:35, 60:70] -= 3.0
    _write(version / "Escalonado_corte_V03.tif", GRID, cut)
    _write(version / "Escalonado_relleno_V03.tif", GRID, _fill_steps())
    if "sheet" not in drop:
        (version / "ficha_diseno.json").write_text(
            json.dumps(_sheet(literal=literal), ensure_ascii=False, indent=1), encoding="utf-8")
    return root


def _run(folder: Path | None) -> tuple[unittest.TestResult, str]:
    """La comparación del banco con ``folder`` en la variable (``None``: sin ella)."""
    environ = {key: value for key, value in os.environ.items() if key != bank.ENV}
    if folder is not None:
        environ[bank.ENV] = str(folder)
    suite = unittest.TestLoader().loadTestsFromTestCase(bank.ReferenceDesignTest)
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


class BankHarnessTest(unittest.TestCase):
    """CE-013-10: la comparación del banco, con una carpeta sintética (RF-013-11, RF-013-22,
    RF-013-25)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = Path(tempfile.mkdtemp(prefix="gb-013-t33-"))
        cls.good = build_bank(cls.temp / "bien")

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.temp, ignore_errors=True)

    def test_a_skipped_without_the_variable(self) -> None:
        """CE-013-10: sin ``GEOBLENDER_SILVESTRE_DIR``, o si no es una carpeta, la comparación
        se omite con la orden que la activa, sin fallar."""
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
        """CE-013-10, RF-013-11, RF-013-22, RF-013-25: con la carpeta sintética, las dos
        envolventes reproducen sus referencias (sin diferencias que explicar), los dos
        escalonados reproducen las suyas sobre la envolvente de la referencia (ni una celda
        distinta; ni una por debajo de la envolvente) y la berma del sector es la de la regla
        dentro del redondeo de su literal; imprime una línea por cifra sin nombres del banco y no
        cambia la carpeta."""
        before = _state(self.good)
        result, output = _run(self.good)
        self.assertEqual(_state(self.good), before)
        self.assertEqual((result.testsRun, result.failures, result.errors, result.skipped),
                         (3, [], [], []), output)
        lines = [line for line in output.splitlines() if line.startswith(bank.NAME)]
        self.assertEqual(len(lines), 2 + 2)
        for word in ("V03", "V02", "Semillas", "Envolvente", "Escalonado", "Sector_", "MDT",
                     "ficha", "talud", "tongadas", "bancos", str(self.good)):
            self.assertNotIn(word, output)
        found = bank.ReferenceDesignTest.result
        first, second = found.envelopes
        self.assertEqual((first.direction, second.direction), ("down", "up"))
        self.assertEqual(first.cells, 50 * COLS)
        self.assertEqual(second.cells, 50 * 72)
        for item in found.envelopes:
            self.assertEqual((item.unexplained, item.by_metric, item.by_convergence), (0, 0, 0))
            self.assertEqual(item.equal, item.cells)
            self.assertLess(item.max_abs_m, 1e-3)
            self.assertGreater(item.exact_max_abs_m, 1e-3)  # la euclídea sí difiere del chamfer
        cut, fill = found.steps
        self.assertEqual((cut.sense, fill.sense), ("cut", "fill"))
        for item in found.steps:
            self.assertEqual(item.on_reference.differing, 0)
            self.assertEqual(item.below_envelope, 0)
            self.assertLess(item.on_reference.max_abs_m, 1e-3)
            reference = item.reference
            self.assertGreater(reference.cut_m3 + reference.fill_m3, 0.0)
            self.assertLessEqual(item.on_reference.relative_cut, 1e-6)
            self.assertLessEqual(item.on_reference.relative_fill, 1e-6)
        self.assertGreater(cut.reference.cut_m3, 0.0)
        self.assertGreater(fill.reference.fill_m3, 0.0)
        self.assertEqual(fill.chain.differing, 0)  # sin sector la cadena es lo mismo
        self.assertGreater(cut.chain.max_abs_m, 0.0)  # la regla (19,5765 m), no el literal (19,6)
        self.assertLess(cut.chain.max_abs_m, 1e-2)
        self.assertIsNone(fill.berm)
        self.assertAlmostEqual(cut.berm.rule_m, RULE_BERM, delta=1e-9)
        self.assertEqual(cut.berm.literal_m, LITERAL_BERM)
        self.assertAlmostEqual(cut.berm.half_unit_m, 0.05, delta=1e-12)
        self.assertTrue(cut.berm.within)

    def test_c_the_exact_metric_is_explained_by_the_metric(self) -> None:
        """CE-013-10, RF-013-11, RF-013-12: una referencia hecha con la euclídea exacta difiere
        del *chamfer* en celdas de las dos signos, todas dentro del 1,4 % de la caída desde la
        semilla más alta: se explican por la métrica, y nada falla."""
        folder = build_bank(self.temp / "metrica", flaw=METRIC)
        result, output = _run(folder)
        self.assertEqual((result.failures, result.errors), ([], []), output)
        item = bank.ReferenceDesignTest.result.envelopes[0]
        self.assertEqual(item.unexplained, 0)
        self.assertGreater(item.by_metric, 0)
        self.assertLess(item.exact_max_abs_m, 1e-3)  # la referencia es la euclídea
        self.assertEqual(item.by_metric + item.equal + item.by_convergence, item.cells)

    def test_d_a_reference_that_did_not_converge_is_explained_by_the_convergence(self) -> None:
        """CE-013-10, RF-013-11: una referencia 0,3 m por debajo en 800 celdas (más que el 1,4 %
        de la caída) del lado de un barrido que no llegó al punto fijo se cuenta como explicada
        por la convergencia, y se dice cuántas son."""
        folder = build_bank(self.temp / "convergencia", flaw=CONVERGENCE)
        result, output = _run(folder)
        self.assertEqual((result.failures, result.errors), ([], []), output)
        item = bank.ReferenceDesignTest.result.envelopes[0]
        self.assertEqual((item.by_convergence, item.unexplained), (10 * COLS, 0))
        self.assertAlmostEqual(item.max_abs_m, 0.3, delta=1e-3)
        self.assertIn(f"por la convergencia {10 * COLS}", output.replace(".", ""))

    def test_e_a_difference_the_other_way_fails_only_the_envelope(self) -> None:
        """CE-013-10, RF-013-11: una celda de la referencia 0,5 m por encima de la envolvente de
        Geoblender (más que la métrica, y del lado contrario al de la convergencia) no se
        explica: falla solo la comprobación de las envolventes, con la celda contada."""
        folder = build_bank(self.temp / "al-reves", flaw=WRONG_WAY)
        result, _ = _run(folder)
        failed = _failed(result)
        self.assertEqual(len(failed), 1, failed)
        self.assertIn("test_envelopes_are_explained", failed[0])
        self.assertEqual(result.errors, [])
        item = bank.ReferenceDesignTest.result.envelopes[0]
        self.assertEqual(item.unexplained, 1)
        self.assertIn("envolvente 1 de 2", str(result.failures[0][1]))

    def test_f_a_different_stepped_surface_fails_only_the_volumes(self) -> None:
        """CE-013-10, RF-013-22: 3 m más de corte en 50 celdas de la referencia del escalonado
        (50 · 4 · 3 = 600 m³ de desmonte más) pasan de ±10⁻⁴ del movimiento de tierras: falla solo
        la comprobación del escalonado, y las envolventes y la berma siguen bien."""
        folder = build_bank(self.temp / "escalonado", flaw=STEPPED)
        result, _ = _run(folder)
        failed = _failed(result)
        self.assertEqual(len(failed), 1, failed)
        self.assertIn("test_steps_on_the_reference_envelope_reproduce", failed[0])
        self.assertIn("escalonado 1 de 2", str(result.failures[0][1]))
        item = bank.ReferenceDesignTest.result.steps[0]
        self.assertEqual(item.on_reference.differing, 50)
        self.assertAlmostEqual(item.on_reference.max_abs_m, 3.0, delta=1e-3)

    def test_g_a_berm_outside_the_rounding_fails_only_the_rule(self) -> None:
        """CE-013-10, RF-013-25: una berma de la referencia de 19,7 m con una regla de 19,5765 m
        (más de medio decimal: 0,05 m) hace fallar solo la comprobación de la berma del sector;
        los escalonados sobre la envolvente de la referencia, con esa berma, la reproducen."""
        folder = build_bank(self.temp / "berma", flaw=BERM, literal=19.7)
        result, _ = _run(folder)
        failed = _failed(result)
        self.assertEqual(len(failed), 1, failed)
        self.assertIn("test_sector_berm_is_the_rule_within_the_rounding", failed[0])
        berm = bank.ReferenceDesignTest.result.steps[0].berm
        self.assertEqual((berm.literal_m, berm.within), (19.7, False))
        self.assertAlmostEqual(berm.half_unit_m, 0.05, delta=1e-12)

    def test_h_says_everything_it_does_not_find(self) -> None:
        """CE-013-10: sin la ficha, sin las semillas de la primera envolvente, sin la máscara del
        sector y sin el MDT, la comparación falla con la lista de todo lo que no encuentra (no
        solo lo primero), sin nombrar ningún fichero del banco."""
        folder = build_bank(self.temp / "incompleto", drop=("seeds", "mask", "start"))
        result, _ = _run(folder)
        self.assertEqual((result.testsRun, result.failures), (0, []))
        (_, text), = result.errors
        message = text.rsplit("BankShapeError:", 1)[1]
        self.assertIn("las semillas de la envolvente 1 de 2", message)
        self.assertIn("la máscara del sector del escalonado 1 de 2", message)
        self.assertIn("la superficie de partida", message)
        self.assertNotIn("la ficha del diseño", message)
        self.assertNotIn("Semillas_cresta", message)
        self.assertNotIn("Sector_tendido", message)
        folder = build_bank(self.temp / "sin-ficha", drop=("sheet",))
        result, _ = _run(folder)
        (_, text), = result.errors
        self.assertIn("BankShapeError", text)
        self.assertIn("la ficha del diseño", text.rsplit("BankShapeError:", 1)[1])
        self.assertIn("ficha_diseno", text.rsplit("BankShapeError:", 1)[1])

    def test_i_a_wrong_sheet_says_what_is_wrong_with_it(self) -> None:
        """CE-013-10: una ficha con un sentido que no existe, una pendiente fuera de rango y un
        escalonado sobre una envolvente que no existe dice cada cosa, con su envolvente o su
        escalonado, y no calcula nada."""
        folder = build_bank(self.temp / "ficha-mala")
        path = folder / "disenos" / "V03_prueba_VIGENTE" / "modelos" / "ficha_diseno.json"
        sheet = _sheet()
        sheet["envolventes"][0]["sentido"] = "arriba"
        sheet["envolventes"][1]["pendiente_deg"] = 95
        sheet["escalonados"][1]["envolvente"] = "no-existe"
        path.write_text(json.dumps(sheet), encoding="utf-8")
        result, _ = _run(folder)
        self.assertEqual((result.testsRun, result.failures), (0, []))
        (_, text), = result.errors
        message = text.rsplit("BankShapeError:", 1)[1]
        self.assertIn("envolvente 1 de 2", message)
        self.assertIn("sentido", message)
        self.assertIn("envolvente 2 de 2", message)
        self.assertIn("escalonado 2 de 2", message)
        self.assertIn("no existe", message)


if __name__ == "__main__":
    unittest.main()

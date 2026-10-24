# SPDX-License-Identifier: GPL-3.0-or-later
"""La comparación del banco de la cubicación con una carpeta sintética con la forma del banco
(spec 011, T29; CE-011-05; HU-011-3; RF-011-12, RF-011-16; D-14 d).

``tests/banco/silvestre/test_res_volumes.py`` solo lo ejecuta el arnés de los bancos con el banco
real (lo hace una persona en el H3). Aquí se comprueba que se omite sin la variable y que, con una
carpeta **sintética** con la forma que espera (creada en ``%TEMP%`` y señalada por la variable
solo dentro de cada prueba), pasa; y que una referencia desviada un 0,05 % la hace fallar.

La carpeta: un MDT de 24 × 20 celdas de 1,0003 × 1,0002 m fuera de las versiones; una versión
superada (con otra superficie, que no se usa) y la vigente, con su superficie de excavación de
12 × 10 celdas de 2,0006 × 2,0004 m (área nominal 4 m²; real 4,00200024 m²), la base de la
unidad 1 en GeoTIFF y la de la 2 en ``.npy`` con un hueco sin dato (la unidad 2 no existe allí y
su espesor pasa a la 3), y la tabla de referencia calculada aparte como el proyecto de referencia
(espesor por celda en el centro de celda, la base sin dato en la de arriba, por 4 m²; densidades
sintéticas de prueba). Todo son planos: la media por área del MDT es exacta.
"""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from tests.banco.silvestre import test_res_volumes as bank
from tests.support import res_fixtures as fx
from tests.support.package import import_geoblender

gis = import_geoblender("gis")
geotiff = import_geoblender("gis.geotiff")

WEST, NORTH = 700_000.0, 4_400_000.0
FINE = (1.0003, 1.0002, 24, 20)
COARSE = (2.0006, 2.0004, 12, 10)
DENSITIES = (2.5, 2.2, 2.0)
"""Densidades sintéticas de prueba (t/m³) de las tres unidades."""


def _grid(dx: float, dy: float, ncols: int, nrows: int) -> object:
    return gis.Grid(WEST, NORTH, dx, dy, ncols, nrows)


def _terrain(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return 200.0 + 0.2 * (x - WEST) - 0.3 * (NORTH - y)


def _excavation(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return 150.0 + 0.1 * (x - WEST)


def _base_1(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return 190.0 + 0.0 * x


def _base_2(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    values = 170.0 - 0.05 * (NORTH - y) + 0.0 * x
    values[:3, :4] = np.nan  # la unidad 2 no existe en esa esquina
    return values


def _write(path: Path, grid: object, values: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    geotiff.GeoTiffIO().write(gis.Raster(grid, values, fx.CRS, fx.VERTICAL), path,
                              profile=gis.WriteProfile.PROJECT)


def _spanish(value: float) -> str:
    return f"{value:,.6f}".translate(str.maketrans(",.", ".,"))


def build_bank(root: Path, *, bias: float = 0.0) -> Path:
    """La carpeta sintética en ``root``; ``bias``, la desviación relativa del volumen y las
    toneladas de la unidad 2 en la tabla de referencia."""
    fine, coarse = _grid(*FINE), _grid(*COARSE)
    x, y = fine.centers()
    _write(root / "entradas" / "MDT_sintetico.tif", fine, _terrain(x, y))
    x, y = coarse.centers()
    old = root / "disenos" / "V01_prueba_SUPERADO"
    _write(old / "V01_Superficie_excavacion.tif", coarse, _excavation(x, y) - 5.0)
    version = root / "disenos" / "V02_prueba_VIGENTE"
    _write(version / "modelos" / "V02_Superficie_excavacion.tif", coarse, _excavation(x, y))
    _write(version / "geologia" / "Base_uno.tif", coarse, _base_1(x, y))
    (root / "geologia").mkdir()
    np.save(root / "geologia" / "Base_dos.npy", _base_2(x, y), allow_pickle=False)

    top, bottom = _terrain(x, y), _excavation(x, y)
    base_1 = _base_1(x, y)
    base_2 = np.where(np.isnan(_base_2(x, y)), base_1, _base_2(x, y))  # ausente: espesor 0
    limits = [1e4, base_1, base_2, -1e4]
    rows = ["unidad;base;volumen_m3;densidad_t_m3;toneladas_t"]
    names = ("Uno", "Dos", "Tres")
    files = ("Base_uno", "Base_dos", "")
    for number in range(3):
        above, below = limits[number], limits[number + 1]
        cells = np.clip(np.minimum(top, above) - np.maximum(bottom, below), 0.0, None)
        volume = float(cells.sum()) * 4.0 * (1.0 + (bias if number == 1 else 0.0))
        rows.append(f"{names[number]};{files[number]};{_spanish(volume)};"
                    f"{_spanish(DENSITIES[number])};{_spanish(volume * DENSITIES[number])}")
    (version / "V02_cubicacion_unidades.csv").write_text("\n".join(rows) + "\n",
                                                         encoding="utf-8")
    return root


def _run(folder: Path | None) -> tuple[unittest.TestResult, str]:
    """La comparación del banco con ``folder`` en la variable (``None``: sin ella)."""
    environ = {key: value for key, value in os.environ.items() if key != bank.ENV}
    if folder is not None:
        environ[bank.ENV] = str(folder)
    suite = unittest.TestLoader().loadTestsFromTestCase(bank.ReferenceVolumesTest)
    result = unittest.TestResult()
    output = io.StringIO()
    with mock.patch.dict(os.environ, environ, clear=True), contextlib.redirect_stderr(output):
        suite.run(result)
    return result, output.getvalue()


def _state(folder: Path) -> list[tuple[str, int, int]]:
    return sorted((str(path.relative_to(folder)), path.stat().st_size, path.stat().st_mtime_ns)
                  for path in folder.rglob("*") if path.is_file())


class BankHarnessTest(unittest.TestCase):
    """CE-011-05: la comparación del banco, con una carpeta sintética (RF-011-12, RF-011-16)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = Path(tempfile.mkdtemp(prefix="gb-011-t29-"))
        cls.good = build_bank(cls.temp / "bien")
        cls.biased = build_bank(cls.temp / "desviada", bias=5e-4)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.temp, ignore_errors=True)

    def test_skipped_without_the_variable(self) -> None:
        """CE-011-05: sin ``GEOBLENDER_SILVESTRE_DIR``, o si no es una carpeta, la comparación
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

    def test_synthetic_bank_passes_and_stays_untouched(self) -> None:
        """CE-011-05, RF-011-12, RF-011-16: con la carpeta sintética, la versión vigente
        cubicada por unidades (el MDT llevado a su rejilla, una base en ``.npy`` con hueco)
        reproduce los volúmenes y las toneladas por unidad corregidos por el área real de la
        celda (±0,01 %), imprime una línea por unidad sin nombres del banco y no cambia la
        carpeta."""
        before = _state(self.good)
        result, output = _run(self.good)
        self.assertEqual(_state(self.good), before)
        self.assertEqual((result.testsRun, result.failures, result.errors, result.skipped),
                         (3, [], [], []))
        lines = [line for line in output.splitlines() if line.startswith("CE-011-05")]
        self.assertEqual(len(lines), 3)
        for word in ("V02", "Uno", "Base_", "MDT", str(self.good)):
            self.assertNotIn(word, output)
        found = bank.ReferenceVolumesTest.result
        self.assertEqual(found.nominal_m2, 4.0)
        self.assertAlmostEqual(found.cell_area_m2, 2.0006 * 2.0004, delta=1e-12)
        for unit in found.units:
            self.assertGreater(unit.volume_m3, 0.0)
            self.assertLessEqual(abs(unit.volume_difference), 1e-9)
            self.assertLessEqual(abs(unit.mass_difference), 1e-9)

    def test_a_biased_reference_fails(self) -> None:
        """CE-011-05 (D-14 d): una referencia desviada un 0,05 % en la unidad 2 (más que la
        tolerancia de ±0,01 %) hace fallar el volumen y las toneladas, no el reparto."""
        result, _ = _run(self.biased)
        failed = sorted(test.id() for test, _ in result.failures)
        self.assertEqual(len(failed), 2)
        self.assertIn("test_tonnes_by_unit_match_the_reference", failed[0])
        self.assertIn("unidad 2 de 3", failed[0])
        self.assertIn("test_volume_by_unit_matches_the_reference", failed[1])
        self.assertIn("unidad 2 de 3", failed[1])
        self.assertEqual(result.errors, [])


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: GPL-3.0-or-later
"""La comparación del banco de las restricciones con una carpeta sintética con la forma del
banco (spec 012, T32; CE-012-08; HU-012-5; RF-012-21, RF-012-22; plan 012 §7.1).

``tests/banco/silvestre/test_constraints.py`` solo lo ejecuta el arnés de los bancos con el banco
real (lo hace una persona en el H3). Aquí se comprueba que se omite sin la variable y que, con
una carpeta **sintética** con la forma que espera (creada en ``%TEMP%`` y señalada por la variable
solo dentro de cada prueba), declara las restricciones, verifica las tres superficies y reproduce
la cifra de referencia del relleno fuera del límite legal; que dice todo lo que no encuentra; y
que cada tipo de incumplimiento hace fallar solo la comprobación que le toca.

La carpeta (rejilla de 100 × 80 celdas de 1,0003 × 1,0002 m, celda nominal de 1 m²): una
superficie de partida en una rejilla del doble de resolución (MDT, fuera de las versiones); los
GeoPackage del límite legal (con otro de un huso distinto, que se descarta por su CRS) y de los
seis recintos fuera de la versión, y el del perímetro dentro; la versión vigente con sus tres
superficies de diseño (más un sombreado, que no cuenta) y una superada con una superficie que
incumple (que no se usa). El límite legal y el perímetro se desplazan 0,37 celdas de las aristas de
las celdas; el perímetro sobresale 25 celdas de ancho del límite legal por el este (la franja,
1.500 celdas), con un relleno de **1.126 celdas** en la final dentro de la franja (la cifra del
error 27 en celdas nominales), 552 en el desdoblado y ninguno en la excavación. La zona 1 se
excava; las zonas 4 y 5 (solo restauración) se rellenan; la zona 6 («preferible no afectar») se
corta; las zonas 2 y 3 (intocables) no se tocan. Todo son planos: la media por área del MDT es
exacta.
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

from tests.banco.silvestre import test_constraints as bank
from tests.support import constraints_fixtures as fx
from tests.support.package import import_geoblender

gis = import_geoblender("gis")
geotiff = import_geoblender("gis.geotiff")

WEST, NORTH = 700_000.0, 4_400_000.0
DX, DY = 1.0003, 1.0002
COLS, ROWS = 100, 80
GRID = gis.Grid(WEST, NORTH, DX, DY, COLS, ROWS)
CELL_M2 = DX * DY
LEGAL_BOX = (10.37, 10.37, 70.37, 70.37)
PERIMETER_BOX = (10.37, 10.37, 95.37, 70.37)
ZONE_BOXES = {
    1: (20.37, 20.37, 50.37, 40.37),
    2: (52.37, 20.37, 60.37, 28.37),
    3: (52.37, 32.37, 60.37, 40.37),
    4: (20.37, 44.37, 30.37, 54.37),
    5: (34.37, 44.37, 44.37, 54.37),
    6: (48.37, 44.37, 58.37, 54.37),
}
"""Los recintos y los límites, en celdas (columna, fila, columna, fila; la fila 0 al norte)."""
EXCAVATION = (slice(21, 40), slice(21, 50))
ZONE_4 = (slice(45, 54), slice(21, 30))
ZONE_5 = (slice(45, 54), slice(35, 44))
ZONE_6 = (slice(45, 54), slice(49, 58))
PATCH = (slice(14, 62), slice(72, 95))
PATCH_TAIL = (slice(62, 63), slice(72, 94))
HALF_PATCH = (slice(14, 38), slice(72, 95))
"""Las celdas de cada trabajo (filas, columnas): 23 × 48 + 22 = 1.126 de relleno en la franja."""
FILL_CELLS = 23 * 48 + 22
HALF_CELLS = 23 * 24
STRIP_COLS, STRIP_ROWS = 25, 60
FLAWED = "flawed"
FILL_MORE = "fill_more"


def _xy(column: float, row: float) -> tuple[float, float]:
    return WEST + column * DX, NORTH - row * DY


def _ring(box: tuple[float, float, float, float]) -> np.ndarray:
    left, top, right, bottom = box
    return np.array([_xy(left, top), _xy(left, bottom), _xy(right, bottom), _xy(right, top),
                     _xy(left, top)], dtype=np.float64)


def _feature(fid: int, box: tuple[float, float, float, float], **attributes: object):
    return fx.SourceFeature(fid, "POLYGON", (_ring(box),), attributes)


def _plane(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return 650.0 + 0.02 * (x - WEST) + 0.03 * (y - (NORTH - ROWS * DY))


def _noise() -> np.ndarray:
    rows, columns = np.indices(GRID.shape)
    return 0.01 * np.sin(0.7 * rows + 1.3 * columns)  # por debajo de los 0,02 m de D-6


def _write(path: Path, grid: object, values: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    geotiff.GeoTiffIO().write(gis.Raster(grid, values, fx.CRS, fx.VERTICAL), path,
                              profile=gis.WriteProfile.PROJECT)


def _surfaces(flaw: str | None) -> dict[str, np.ndarray]:
    """Las tres superficies de diseño: desdoblado, excavación y final."""
    x, y = GRID.centers()
    ground = _plane(x, y) + _noise()
    third = ground.copy()
    third[EXCAVATION] -= 4.0
    third[HALF_PATCH] += 0.5
    excavation = ground.copy()
    excavation[EXCAVATION] -= 10.0
    final = ground.copy()
    final[EXCAVATION] -= 8.0
    final[ZONE_4] += 1.5
    final[ZONE_5] += 1.0
    final[ZONE_6] -= 2.0
    final[PATCH] += 0.6
    final[PATCH_TAIL] += 0.6
    if flaw == FLAWED:
        final[50, 25] -= 2.0  # corte de 0,5 m en la zona 4 (solo restauración): CA-2
        third[65, 80] -= 1.5  # corte de 1 m en la franja, fuera del límite legal: CA-13
        excavation[75, 50] += 1.0  # relleno fuera del perímetro: CA-13
    if flaw == FILL_MORE:
        final[63:64, 72:95] += 0.6  # 23 celdas más de relleno en la franja
    return {"desdoblado": third, "excavacion": excavation, "final": final}


def build_bank(root: Path, *, flaw: str | None = None, drop: tuple[str, ...] = (),
               legal_epsg: int | None = None) -> Path:
    """La carpeta sintética en ``root``. ``flaw``: ``"flawed"`` (un corte en la zona 4, otro en
    la franja y un relleno fuera del perímetro) o ``"fill_more"`` (23 celdas más de relleno en la
    franja). ``drop``: lo que no se escribe (``"perimeter"``, ``"surface"``). ``legal_epsg``: el
    EPSG del GeoPackage del límite legal (por defecto, el de las superficies)."""
    x, y = GRID.centers()
    fine = gis.Grid(WEST, NORTH, DX / 2.0, DY / 2.0, COLS * 2, ROWS * 2)
    fx_, fy_ = fine.centers()
    _write(root / "entradas" / "MDT_sintetico.tif", fine, _plane(fx_, fy_))
    old = root / "disenos" / "V02_prueba_SUPERADO"
    bad = _plane(x, y)
    bad[75:78, 50:53] -= 20.0  # un corte fuera del perímetro: no debe usarse
    _write(old / "V02_Superficie_final.tif", GRID, bad)
    version = root / "disenos" / "V03_prueba_VIGENTE"
    for name, values in _surfaces(flaw).items():
        if name == "desdoblado" and "surface" in drop:
            continue
        _write(version / "modelos" / f"V03_Superficie_{name}.tif", GRID, values)
    _write(version / "modelos" / "V03_Superficie_final_sombreado.tif", GRID,
           np.full(GRID.shape, 128.0))
    inputs = root / "entradas"
    crs = None if legal_epsg is None else fx.CATALOG.horizontal(legal_epsg)
    fx.write_gpkg_layer(inputs / "C_M_prueba_Catastro.gpkg", "concesion", "POLYGON",
                        (("nombre", "TEXT"),), [_feature(1, LEGAL_BOX, nombre="Concesión")],
                        crs=crs)
    if legal_epsg is None:
        fx.write_gpkg_layer(inputs / "Otro_huso_Catastro.gpkg", "concesion", "POLYGON",
                            (("nombre", "TEXT"),), [_feature(1, LEGAL_BOX, nombre="Otra")],
                            crs=fx.CATALOG.horizontal(25831))
    if "perimeter" not in drop:
        fx.write_gpkg_layer(version / "Limites_v1.gpkg", "limites", "POLYGON",
                            (("nombre", "TEXT"),), [_feature(1, PERIMETER_BOX, nombre="L1")])
    fx.write_gpkg_layer(version / "V03_Zonas.gpkg", "zonas", "POLYGON", (("tipo", "TEXT"),),
                        [_feature(1, ZONE_BOXES[1], tipo="corte")])
    fx.write_gpkg_layer(inputs / "Limite_PIT.gpkg", "recintos", "POLYGON",
                        (("nombre", "TEXT"), ("zona", "INTEGER")),
                        [_feature(number, box, nombre=f"Recinto {number}", zona=number)
                         for number, box in ZONE_BOXES.items()])
    return root


def _run(folder: Path | None) -> tuple[unittest.TestResult, str]:
    """La comparación del banco con ``folder`` en la variable (``None``: sin ella)."""
    environ = {key: value for key, value in os.environ.items() if key != bank.ENV}
    if folder is not None:
        environ[bank.ENV] = str(folder)
    suite = unittest.TestLoader().loadTestsFromTestCase(bank.ReferenceConstraintsTest)
    result = unittest.TestResult()
    output = io.StringIO()
    with mock.patch.dict(os.environ, environ, clear=True), contextlib.redirect_stderr(output):
        suite.run(result)
    return result, output.getvalue()


def _state(folder: Path) -> list[tuple[str, int, int]]:
    return sorted((str(path.relative_to(folder)), path.stat().st_size, path.stat().st_mtime_ns)
                  for path in folder.rglob("*") if path.is_file())


class BankHarnessTest(unittest.TestCase):
    """CE-012-08: la comparación del banco, con una carpeta sintética (RF-012-21, RF-012-22)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = Path(tempfile.mkdtemp(prefix="gb-012-t32-"))
        cls.good = build_bank(cls.temp / "bien")

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.temp, ignore_errors=True)

    def test_skipped_without_the_variable(self) -> None:
        """CE-012-08: sin ``GEOBLENDER_SILVESTRE_DIR``, o si no es una carpeta, la comparación
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
        """CE-012-08, RF-012-21, RF-012-22: con la carpeta sintética, declara el límite legal,
        el perímetro y los recintos 2 a 6, verifica las tres superficies con CA-2 y CA-13 a
        0 m³, reproduce los 1.126 m² de relleno fuera del límite legal, imprime una línea por
        cifra sin nombres del banco y no cambia la carpeta."""
        before = _state(self.good)
        result, output = _run(self.good)
        self.assertEqual(_state(self.good), before)
        self.assertEqual((result.testsRun, result.failures, result.errors, result.skipped),
                         (3, [], [], []))
        lines = [line for line in output.splitlines() if line.startswith("CE-012-08")]
        self.assertEqual(len(lines), 1 + 3 + 1)
        for word in ("V03", "V02", "C_M_", "Limites_v1", "Limite_PIT", "MDT", "Otro_huso",
                     "sombreado", str(self.good)):
            self.assertNotIn(word, output)
        found = bank.ReferenceConstraintsTest.result
        self.assertEqual(found.nominal_m2, 1.0)
        self.assertAlmostEqual(found.cell_area_m2, CELL_M2, delta=1e-12)
        self.assertEqual(sorted(found.zone_codes), ["2", "3", "4", "5", "6"])
        self.assertEqual(found.declared, 2 + 5)
        self.assertEqual([item.label for item in found.surfaces],
                         [f"superficie {number} de 3" for number in (1, 2, 3)])
        legal, strip = 60 * DX * 60 * DY, STRIP_COLS * DX * STRIP_ROWS * DY
        self.assertLessEqual(abs(found.report.legal_m2 - legal), 1e-9 * legal)
        self.assertLessEqual(abs(found.report.strip_m2 - strip), 1e-9 * strip)
        self.assertEqual([item.fill_cells for item in found.surfaces],
                         [HALF_CELLS, 0, FILL_CELLS])
        self.assertEqual([item.edge_fill_cells for item in found.surfaces], [0, 0, 0])
        for item in found.surfaces:
            self.assertFalse(item.check.fails)
        final = found.surfaces[2].check
        avoid = final.zone(found.zone_codes["6"][0])
        self.assertAlmostEqual(avoid.moved_m2, 81 * CELL_M2, delta=1e-9)
        # las superficies se guardan en float32 (cuantos de 6·10⁻⁵ m a 650 m de cota)
        self.assertAlmostEqual(avoid.cut_m3, 81 * 2.0 * CELL_M2, delta=1e-3)

    def test_every_kind_of_flaw_fails_only_its_check(self) -> None:
        """CE-012-08, RF-012-22: un corte en la zona 4 de la final (CA-2), otro en la franja del
        desdoblado y un relleno fuera del perímetro de la excavación (CA-13) hacen fallar
        solo CA-2 y CA-13 de su superficie, cada uno con su comprobación; el declarado y la
        cifra del relleno siguen bien."""
        folder = build_bank(self.temp / "defectos", flaw=FLAWED)
        result, _ = _run(folder)
        failed = sorted(str(test) for test, _ in result.failures)
        self.assertEqual(len(failed), 3, failed)
        self.assertTrue(all("test_ca2_and_ca13_are_zero_in_every_surface" in text
                            for text in failed))
        self.assertIn("superficie 1 de 3", failed[0])
        self.assertIn("CA-13 corte fuera del límite legal", failed[0])
        self.assertIn("superficie 2 de 3", failed[1])
        self.assertIn("CA-13 movimiento fuera del perímetro", failed[1])
        self.assertIn("superficie 3 de 3", failed[2])
        self.assertIn("CA-2 zonas 2 a 5", failed[2])
        self.assertEqual(result.errors, [])
        self.assertEqual(result.testsRun, 3)

    def test_a_larger_fill_than_the_reference_fails(self) -> None:
        """CE-012-08: 23 celdas más de relleno en la franja que las 1.126 de la referencia (lejos
        del borde del límite legal: no las explica la regla de borde) hacen fallar solo la
        reproducción de la cifra; CA-2 y CA-13 siguen en 0 m³ (el relleno en la franja es
        admisible)."""
        folder = build_bank(self.temp / "mas-relleno", flaw=FILL_MORE)
        result, _ = _run(folder)
        failed = [str(test) for test, _ in result.failures]
        self.assertEqual(len(failed), 1, failed)
        self.assertIn("test_unintersected_perimeter_reproduces_the_fill_outside", failed[0])
        self.assertEqual(result.errors, [])

    def test_says_everything_it_does_not_find(self) -> None:
        """CE-012-08: sin el GeoPackage del perímetro y con solo dos superficies de diseño, la
        comparación falla con la lista de todo lo que no encuentra (no solo lo primero)."""
        folder = build_bank(self.temp / "incompleto", drop=("perimeter", "surface"))
        result, _ = _run(folder)
        self.assertEqual((result.testsRun, result.failures), (0, []))
        (_, text), = result.errors
        self.assertIn("BankShapeError", text)
        self.assertIn("el perímetro de actuación", text)
        self.assertIn("superficies de diseño de la versión vigente", text)
        self.assertIn("se esperaban 3", text)
        self.assertIn("hay 2", text)
        self.assertNotIn("el límite legal", text.rsplit("BankShapeError:", 1)[1])

    def test_a_layer_in_another_crs_is_not_the_limit(self) -> None:
        """CE-012-08 («por su nombre y su CRS»): un GeoPackage del límite legal en otro CRS que
        el de las superficies no se usa, y se dice que está en otro CRS."""
        folder = build_bank(self.temp / "otro-crs", legal_epsg=25831)
        result, _ = _run(folder)
        (_, text), = result.errors
        self.assertIn("el límite legal", text)
        self.assertIn("otro CRS", text)


if __name__ == "__main__":
    unittest.main()

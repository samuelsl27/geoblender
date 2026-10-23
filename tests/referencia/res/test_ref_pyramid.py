# SPDX-License-Identifier: GPL-3.0-or-later
"""CE-011-01: la pirámide de referencia, la corta circular de la 006 y el prisma B24 cubicados
con el núcleo de la 011 (spec 011, T08; RF-011-01, RF-011-07, RF-011-09, RF-011-10; plan 011
A2, A3, §7.1 y D-14; constitución, principio 2).

- **Pirámide** (``tests/support/res_fixtures.py``): base cuadrada de 100 m y 50 m de altura sobre
  el plano de cota 600, **166.666,667 m³**; sus rodajas de 10 m desde la base, V·[(1 − h₀/H)³ −
  (1 − h₁/H)³]. Muestreada en el centro de celda con 2, 1 y 0,5 m y el vértice en sus 24
  posiciones (6 de x y 4 de y), como rejilla y como TIN de cinco vértices llevado a rejilla
  (``gis.tin_to_raster``, sin dato fuera de la base), se cubica de una vez con rodajas de 10 m
  ancladas en 600: el total, con error ≤ 0,1 % (D-14 a); cada rodaja, ≤ 0,1 % **del total**; las
  rodajas suman el total ≤ 10⁻⁹ (D-14 b). El peor error de cada paso queda anotado en
  ``PYRAMID_WORST_PCT`` y la prueba comprueba que sigue siendo ese (los del plan §2.2, los mismos
  con la rejilla y con el TIN: 0,0800 %, 0,0200 % y 0,0050 %; las rodajas, 0,0160 %, 0,0040 % y
  0,0010 %). El TIN queda en algunas celdas del borde de la base unas décimas de pm por debajo
  de ella: un terraplén de ruido (≤ 1,9·10⁻¹² m³) que abre una rodaja [590, 600) sin desmonte.
  Sus **cuatro cuadrantes** como dominios (cortados por el vértice, parten la ventana), con las
  rodajas: cuadrantes, «Fuera de los dominios» y rodajas suman el total ≤ 10⁻⁹; cada cuadrante,
  su cuarta parte del volumen analítico ≤ 0,1 % (peor, 0,08 %) y, con el vértice en un nodo, la
  cuarta parte del total ≤ 10⁻⁹.
- **Corta circular de la 006** (RF-006-03): con 4, 2, 1 y 0,5 m en sus 6 posiciones, dentro de
  ≤ 0,025 % (4 m) y ≤ 0,01 %, y con el error anotado de cada posición en
  ``tests/referencia/gis/test_ref_volume.py`` (el núcleo da, bit a bit, el volumen de la 006).
- **Prisma B24** (RF-006-02): 10 m sobre 1.000 × 1.000 celdas de 1,000294 × 1,000302 m,
  10.005.966,77 m³ con error ≤ 10⁻⁹, de una vez y por bandas de 256 filas.
"""

from __future__ import annotations

import unittest

import numpy as np

from tests.referencia.gis import test_ref_volume as ref006
from tests.support import res_fixtures as fx
from tests.support.package import import_geoblender

kernel = import_geoblender("reserves.kernel")
slices_module = import_geoblender("reserves.slices")
polygons = import_geoblender("reserves.polygons")

PYRAMID_SLICES = slices_module.Slices(10.0, fx.PYRAMID_FLOOR_Z, None)
PYRAMID_BOUNDS = (600.0, 610.0, 620.0, 630.0, 640.0, 650.0)
CLOSURE = 1e-9
"""Cierre de cuadrantes y rodajas con el total (D-14 b)."""
B24_TOLERANCE = 1e-9
# Peor error (en %, con 4 decimales) de cada paso en las 24 posiciones del vértice: el del
# total y el de la peor rodaja de 10 m sobre el total; el mismo con la rejilla y con el TIN.
PYRAMID_WORST_PCT = {
    2.0: (0.0800, 0.0160),
    1.0: (0.0200, 0.0040),
    0.5: (0.0050, 0.0010),
}
WORST_DELTA_PCT = 5e-5
"""Media unidad del último decimal anotado."""
B24_BAND_ROWS = 256


def _cubicate(pair, *, slices=None, domains=(), band: int | None = None):
    """El resultado del núcleo con e = 0 sobre ``pair``, de una vez o por bandas."""
    grid = pair.grid
    accumulators = kernel.Accumulators(grid, slices=slices, domains=len(domains))
    height = grid.nrows if band is None else band
    for first in range(0, grid.nrows, height):
        rows = slice(first, min(first + height, grid.nrows))
        weights = polygons.weights(domains, None, grid, rows) if domains else None
        kernel.band_step(accumulators, kernel.BandValues(
            first, pair.start.values[rows], pair.final.values[rows]), weights)
    return accumulators.result()


class PyramidTest(unittest.TestCase):
    """CE-011-01 (RF-011-01, RF-011-09): la pirámide, como rejilla y como TIN."""

    def _check(self, make, what: str, *, noise: bool = False) -> None:
        """Con ``noise``, las cotas de la superficie pueden quedar unas décimas de pm por debajo
        de la base (el TIN): un terraplén de ruido (≤ 10⁻⁹ del volumen) que abre una rodaja
        [590, 600) sin desmonte."""
        volume = fx.pyramid_volume()
        expected = [item[2] for item in fx.pyramid_slices(10.0)]
        for step in fx.PYRAMID_STEPS:
            worst_total = worst_slice = 0.0
            for apex in fx.pyramid_apexes(step):
                pair = make(step, apex)
                result = _cubicate(pair, slices=PYRAMID_SLICES)
                where = f"{what}, paso {step} m, vértice {apex}"
                total = result.cut_m3[kernel.ALL]
                error = abs(total - volume) / volume
                self.assertLessEqual(error, fx.PYRAMID_TOLERANCE,
                                     f"{where}: {total:.3f} m³ frente a {volume:.3f} m³")
                fill = result.fill_m3[kernel.ALL]
                self.assertLessEqual(fill, CLOSURE * volume if noise else 0.0, where)
                first = int(np.searchsorted(result.bounds, PYRAMID_BOUNDS[0]))
                self.assertLessEqual(first, 1 if noise and fill else 0, where)
                np.testing.assert_array_equal(result.bounds[first:], PYRAMID_BOUNDS, where)
                self.assertTrue(np.all(result.slice_cut_m3[kernel.ALL][:first] == 0.0), where)
                by_slice = result.slice_cut_m3[kernel.ALL][first:]
                slice_error = float(np.max(np.abs(by_slice - expected))) / volume
                self.assertLessEqual(slice_error, fx.PYRAMID_TOLERANCE,
                                     f"{where}: rodajas {by_slice!r} frente a {expected!r}")
                closure = abs(float(np.sum(by_slice)) - total) / total
                self.assertLessEqual(closure, CLOSURE, f"{where}: las rodajas no suman")
                worst_total = max(worst_total, error)
                worst_slice = max(worst_slice, slice_error)
            annotated = PYRAMID_WORST_PCT[step]
            self.assertAlmostEqual(100 * worst_total, annotated[0], delta=WORST_DELTA_PCT,
                                   msg=f"{what}, paso {step} m: peor error del total "
                                       f"{100 * worst_total:.5f} %, anotado {annotated[0]} %")
            self.assertAlmostEqual(100 * worst_slice, annotated[1], delta=WORST_DELTA_PCT,
                                   msg=f"{what}, paso {step} m: peor error de una rodaja "
                                       f"{100 * worst_slice:.5f} %, anotado {annotated[1]} %")

    def test_as_a_grid(self) -> None:
        """CE-011-01: la pirámide muestreada en el centro de celda, con 2, 1 y 0,5 m en las 24
        posiciones del vértice: total y rodajas de 10 m ≤ 0,1 %; las rodajas suman el total."""
        self._check(fx.pyramid, "rejilla")

    def test_as_a_tin(self) -> None:
        """CE-011-01: la pirámide como TIN de cinco vértices llevado a rejilla (sin dato fuera de
        la base), con 2, 1 y 0,5 m en las 24 posiciones: lo mismo que la rejilla, con un
        terraplén de ruido (≤ 10⁻⁹ del volumen) donde el TIN queda por debajo de la base."""
        self._check(fx.pyramid_from_tin, "TIN", noise=True)

    def test_quadrants_and_slices_add_up(self) -> None:
        """CE-011-01 (RF-011-07, RF-011-10): los cuatro cuadrantes como dominios y las rodajas,
        en el mismo cálculo, con 2, 1 y 0,5 m y el vértice en un nodo, en un centro de celda y
        en una posición cualquiera: cada cuadrante, «Fuera de los dominios» (vacía: parten la
        ventana) y cada rodaja de cada cuadrante suman su total ≤ 10⁻⁹; cada cuadrante, V/4
        ≤ 0,1 %, y con el vértice en un nodo, la cuarta parte del total (≤ 10⁻⁹)."""
        quarter = fx.pyramid_volume() / 4.0
        for step in fx.PYRAMID_STEPS:
            apexes = fx.pyramid_apexes(step)
            for position in (0, 14, 5):  # un nodo, (+0,5 m, +medio paso) y una cualquiera
                apex = apexes[position]
                with self.subTest(step=step, apex=apex):
                    pair = fx.pyramid(step, apex)
                    quadrants = [polygons.Polygon(item.fid, item.value, item.rings)
                                 for item in fx.pyramid_quadrants(apex)]
                    domains = [item.edges for item in polygons.domain_edges(quadrants,
                                                                            pair.grid)]
                    result = _cubicate(pair, slices=PYRAMID_SLICES, domains=domains)
                    total = result.cut_m3[kernel.ALL]
                    rows = result.cut_m3[1:]
                    self.assertLessEqual(abs(float(np.sum(rows)) - total) / total, CLOSURE)
                    self.assertLessEqual(abs(rows[-1]) / total, CLOSURE)  # fuera
                    by_slice = result.slice_cut_m3
                    self.assertLessEqual(
                        float(np.max(np.abs(by_slice.sum(axis=1) - result.cut_m3))) / total,
                        CLOSURE)
                    self.assertLessEqual(
                        float(np.max(np.abs(by_slice[1:].sum(axis=0) - by_slice[0]))) / total,
                        CLOSURE)
                    self.assertLessEqual(float(np.max(np.abs(rows[:4] - quarter))) / quarter,
                                         fx.PYRAMID_TOLERANCE)
                    if position == 0:
                        self.assertLessEqual(
                            float(np.max(np.abs(rows[:4] - total / 4.0))) / total, CLOSURE)


class CircularPitTest(unittest.TestCase):
    """CE-011-01 (RF-011-01; RF-006-03): la corta circular de la 006 cubicada con la 011."""

    def test_pit_volume(self) -> None:
        """RF-011-01: con 4, 2, 1 y 0,5 m en las 6 posiciones del eje, error ≤ 0,025 % (4 m) y
        ≤ 0,01 % (2, 1 y 0,5 m), el anotado en la 006 para cada posición; todo desmonte."""
        volume = fx.circular_pit_volume()
        for index, (step, tolerance) in enumerate(ref006.PIT_TOLERANCE.items()):
            for name, axis in fx.circular_pit_axes():
                with self.subTest(step=step, position=name):
                    result = _cubicate(fx.circular_pit(step, axis))
                    cut = result.cut_m3[kernel.ALL]
                    error = (cut - volume) / volume
                    self.assertLessEqual(abs(error), tolerance,
                                         f"{cut:.3f} m³, error {100 * error:+.5f} %")
                    self.assertAlmostEqual(100 * error, ref006.PIT_ERRORS_PCT[name][index],
                                           delta=ref006.PIT_ERROR_DELTA_PCT)
                    self.assertEqual(result.fill_m3[kernel.ALL], 0.0)
                    self.assertEqual(result.area_m2[kernel.ALL], 260.0 * 260.0)


class B24PrismTest(unittest.TestCase):
    """CE-011-01 (RF-011-01; RF-006-02): el prisma B24, con el área real de sus celdas."""

    def test_prism_volume(self) -> None:
        """RF-011-01: 10.005.966,77 m³ (10 · 10⁶ · dx · dy) con error ≤ 10⁻⁹, de una vez y por
        bandas de 256 filas; suponer celdas de 1 m² daría un −0,06 %."""
        pair = fx.b24_prism()
        volume = fx.b24_volume()
        self.assertAlmostEqual(volume, ref006.B24_EXPECTED_M3, delta=0.005)
        for band in (None, B24_BAND_ROWS):
            with self.subTest(band=band):
                result = _cubicate(pair, band=band)
                cut = result.cut_m3[kernel.ALL]
                self.assertLessEqual(abs(cut - volume) / volume, B24_TOLERANCE,
                                     f"{cut:.6f} m³ frente a {volume:.6f} m³")
                self.assertEqual(result.fill_m3[kernel.ALL], 0.0)
                self.assertEqual(result.cell_area_m2, fx.B24_DX * fx.B24_DY)


if __name__ == "__main__":
    unittest.main()

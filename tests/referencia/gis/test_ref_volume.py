# SPDX-License-Identifier: GPL-3.0-or-later
"""Casos de referencia del volumen entre superficies (spec 006, T04; RF-006-03, RF-006-02;
CE-006-01 y CE-006-02; plan 006 §5.4 A2 y §7.2; ADR-0014; constitución, principio 2).

- **Corta circular** (investigación 07 §3.10, «Validación»; ADR-0014): fondo de radio
  R0 = 50 m, 6 bancos de h = 10 m con cara de 70° y berma de 8 m, en un terreno llano.
  Volumen analítico: V = Σᵢ πh/3 (rᵢ² + rᵢRᵢ + Rᵢ²), rᵢ = 50 + i(d + 8), Rᵢ = rᵢ + d,
  d = 10/tan 70°, i = 0…5 → **1.308.944,006 m³** (plan §5.4 A2, recalculado). La corta se
  muestrea en el centro de cada celda de la rejilla del proyecto (paso 4, 2, 1 y 0,5 m, en
  UTM) y se cubica con ``volume_between`` (terreno − corta). Tolerancia (RF-006-03, plan
  §7.2): error relativo ≤ 0,02 % con 4 m y ≤ 0,01 % con 2, 1 y 0,5 m.

  La posición del eje de la corta respecto a la rejilla cambia el error (el muestreo en el
  centro de celda de las aristas circulares): se prueban el centro de la ventana (centro de
  celda con 4 m y nodo con 2, 1 y 0,5 m) y cuatro posiciones más dentro de una celda de
  4 m, con semilla fija. Errores medidos a 4 m: de −0,01995 % a +0,0132 %; a 2, 1 y 0,5 m,
  ≤ 0,0039 % en valor absoluto. Con el eje exactamente en un nodo de la rejilla de 4 m (la
  configuración del prototipo de inv. 07 §3.10), el error a 4 m es +0,0202 % (el «+0,02 %»
  de inv. 07, redondeado), 0,0002 puntos por encima de la tolerancia: esa posición
  simétrica, en la que se suma el error de los cuatro cuadrantes, no está entre las
  probadas.
- **Prisma B24** (Silvestre ``test_B24_area_real_celda``, recreado con datos sintéticos;
  CE-006-02): un espesor de 10 m sobre 1.000 × 1.000 celdas de 1,0002942907592702 ×
  1,0003022974607014 m da 10 · 10⁶ · dx · dy = **10.005.966,77 m³** (plan §5.4 A2); error
  relativo ≤ 10⁻⁹. Suponer celdas de 1 m² habría dado un −0,06 %.
"""

import math
import unittest

import numpy as np

from tests.support.package import import_geoblender

gis = import_geoblender("gis")
georef = import_geoblender("core.georef")

CATALOG = georef.load_catalog()
CRS = CATALOG.horizontal(25830)
VERTICAL = CATALOG.vertical(5782)

# Corta circular de inv. 07 §3.10.
PIT_R0 = 50.0  # radio del fondo (m)
PIT_BENCH = 10.0  # altura de banco (m)
PIT_FACE_DEG = 70.0  # ángulo de la cara del banco
PIT_BERM = 8.0  # ancho de berma (m)
PIT_BENCHES = 6
PIT_EXPECTED_M3 = 1_308_944.006  # plan 006 §5.4 A2 [V, recalculado], redondeado al dm³
TERRAIN_Z = 860.0  # cota del terreno llano (m)
WINDOW = georef.Window(700_000.0, 4_400_000.0, 700_260.0, 4_400_260.0)  # alineada a 4 m
PIT_AXIS = (700_130.0, 4_400_130.0)  # centro de la ventana
PIT_SEED = 20_261_008
PIT_OFFSETS = 4  # posiciones más del eje, dentro de ±2 m (una celda de 4 m)
PIT_TOLERANCE = {4.0: 2e-4, 2.0: 1e-4, 1.0: 1e-4, 0.5: 1e-4}  # 0,02 % y 0,01 %

# Prisma B24 de Silvestre.
B24_DX = 1.0002942907592702
B24_DY = 1.0003022974607014
B24_CELLS = 1_000
B24_THICKNESS = 10.0
B24_EXPECTED_M3 = 10_005_966.77  # plan 006 §5.4 A2 [V], redondeado a la centésima de m³
B24_TOLERANCE = 1e-9


def _pit_analytic() -> float:
    """Volumen de la corta: suma de los troncos de cono de los 6 bancos (plan §5.4 A2)."""
    d = PIT_BENCH / math.tan(math.radians(PIT_FACE_DEG))
    total = 0.0
    for i in range(PIT_BENCHES):
        r = PIT_R0 + i * (d + PIT_BERM)
        big = r + d
        total += math.pi * PIT_BENCH / 3.0 * (r * r + r * big + big * big)
    return total


def _pit_height(r: np.ndarray) -> np.ndarray:
    """Altura de la corta sobre su fondo a la distancia horizontal ``r`` del eje: cara de
    70° de cada banco y berma plana, hasta el terreno (6 bancos, 60 m)."""
    tan = math.tan(math.radians(PIT_FACE_DEG))
    face = PIT_BENCH / tan  # proyección horizontal de la cara (d)
    module = face + PIT_BERM
    s = np.maximum(r - PIT_R0, 0.0)
    bench = np.floor(s / module)
    rise = np.minimum(s - bench * module, face) * tan
    return np.minimum(bench * PIT_BENCH + rise, PIT_BENCHES * PIT_BENCH)


def _pit_axes() -> list[tuple[float, float]]:
    rng = np.random.default_rng(PIT_SEED)
    offsets = rng.uniform(-2.0, 2.0, (PIT_OFFSETS, 2))
    return [PIT_AXIS] + [(PIT_AXIS[0] + float(ox), PIT_AXIS[1] + float(oy))
                         for ox, oy in offsets]


class CircularPitTest(unittest.TestCase):
    """RF-006-03 (CE-006-01): corta circular de inv. 07 §3.10."""

    def test_analytic_volume(self) -> None:
        """La fórmula del plan da 1.308.944,006 m³ (al dm³)."""
        self.assertAlmostEqual(_pit_analytic(), PIT_EXPECTED_M3, delta=0.0005)

    def test_pit_volume(self) -> None:
        """Error relativo ≤ 0,02 % con 4 m y ≤ 0,01 % con 2, 1 y 0,5 m, en 5 posiciones del
        eje; todo corte (sin relleno) y toda la ventana con dato."""
        expected = _pit_analytic()
        for step, tolerance in PIT_TOLERANCE.items():
            surface_grid = gis.project_grid(WINDOW, step)
            x, y = surface_grid.centers()
            terrain = gis.Raster(surface_grid, np.full(surface_grid.shape, TERRAIN_Z), CRS,
                                 VERTICAL)
            floor = TERRAIN_Z - PIT_BENCHES * PIT_BENCH
            for axis in _pit_axes():
                with self.subTest(step=step, axis=axis):
                    pit = floor + _pit_height(np.hypot(x - axis[0], y - axis[1]))
                    result = gis.volume_between(
                        terrain, gis.Raster(surface_grid, pit, CRS, VERTICAL)
                    )
                    error = (result.cut_m3 - expected) / expected
                    self.assertLessEqual(
                        abs(error), tolerance,
                        f"paso {step} m, eje {axis}: {result.cut_m3:.3f} m³, "
                        f"error {100 * error:+.5f} % (tolerancia {100 * tolerance:.2f} %)",
                    )
                    self.assertEqual(result.fill_m3, 0.0)
                    self.assertEqual(result.net_m3, result.cut_m3)
                    self.assertEqual(result.cell_area_m2, step * step)
                    self.assertEqual(result.area_m2, 260.0 * 260.0)
                    self.assertEqual(result.nodata_area_m2, 0.0)


class B24PrismTest(unittest.TestCase):
    """RF-006-03 y RF-006-02 (CE-006-02): prisma de 10 m sobre la rejilla «de 1 m» de
    Silvestre, que mide 1,0002942907592702 × 1,0003022974607014 m."""

    def test_prism_volume(self) -> None:
        """10 · 10⁶ · dx · dy = 10.005.966,77 m³ con error relativo ≤ 10⁻⁹; la base es la
        superficie sintética de ``tests/data/gis`` (z = 800 + 0,5x − 0,25y + 3 sin(x/7))."""
        prism_grid = gis.Grid(west=700_000.0, north=4_401_000.0, dx=B24_DX, dy=B24_DY,
                              ncols=B24_CELLS, nrows=B24_CELLS)
        x, y = prism_grid.centers()
        lx = x - 700_000.0
        base = 800.0 + 0.5 * lx - 0.25 * (y - 4_400_000.0) + 3.0 * np.sin(lx / 7.0)
        top = base + B24_THICKNESS
        result = gis.volume_between(
            gis.Raster(prism_grid, top, CRS, VERTICAL),
            gis.Raster(prism_grid, base, CRS, VERTICAL),
        )
        analytic = B24_THICKNESS * B24_CELLS * B24_CELLS * B24_DX * B24_DY
        self.assertAlmostEqual(analytic, B24_EXPECTED_M3, delta=0.005)
        error = abs(result.cut_m3 - analytic) / analytic
        self.assertLessEqual(error, B24_TOLERANCE,
                             f"{result.cut_m3:.6f} m³ frente a {analytic:.6f} m³")
        self.assertEqual(result.fill_m3, 0.0)
        self.assertEqual(result.cell_area_m2, B24_DX * B24_DY)
        nominal = B24_THICKNESS * B24_CELLS * B24_CELLS  # celdas supuestas de 1 m²
        self.assertAlmostEqual((nominal - analytic) / analytic, -0.000596, delta=0.000001)


if __name__ == "__main__":
    unittest.main()

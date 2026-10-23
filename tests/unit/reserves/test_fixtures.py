# SPDX-License-Identifier: GPL-3.0-or-later
"""Datos de referencia de la cubicación entre superficies (spec 011, T02; plan 011 §7.1).

Comprueba ``tests.support.res_fixtures`` antes de que lo usen las pruebas del núcleo, sin el
núcleo (``reserves`` aún no calcula nada): los volúmenes analíticos y, sumando a mano celda a
celda (Σ (partida − final)·área de celda), que las rejillas los dan.

- **Pirámide** (CE-011-01; RF-011-01, RF-011-07, RF-011-09): base cuadrada de 100 m, 50 m de
  altura sobre el plano de cota 600, 166.666,667 m³; sus cinco rodajas de 10 m desde la base,
  81.333,333, 49.333,333, 25.333,333, 9.333,333 y 1.333,333 m³; muestreada en el centro de celda
  con 2, 1 y 0,5 m y el vértice en 24 posiciones (6 de x y 4 de y), en rejillas de ≤ 400 × 400;
  como TIN de cinco vértices llevado a rejilla con ``gis.tin.tin_to_raster``; y sus cuatro
  cuadrantes como polígonos (V/4 cada uno). Con 1 m y cuatro posiciones, la suma a mano da su
  volumen con error ≤ 0,1 % (D-14 a).
- **Corta circular de la 006** (RF-006-03): la de ``tests/referencia/gis/test_ref_volume.py``
  (su generador, sin copiarlo), 1.308.944,006 m³.
- **Prisma B24** (RF-006-02): 10 m sobre celdas de 1,000294 × 1,000302 m, 10.005.966,77 m³ con
  1.000 × 1.000 celdas.
- **Columna sintética** (CE-011-02, CE-011-03; RF-011-12, RF-011-14, RF-011-16): acopio, escombro
  de 5 m sobre la capa útil, montera, capa útil compuesta y muro, con superficies planas
  inclinadas y huellas alineadas con las celdas (así la suma en los centros de celda es la
  integral exacta): 3.600, 2.000, 58.570, 107.940 y 64.410 m³ (236.520 m³ de desmonte y 600 m³ de
  terraplén, que no se reparte); sin la unidad de escombro, la capa útil no cambia.

Ningún dato de cliente: todo es sintético.
"""

import unittest

import numpy as np

from tests.support import res_fixtures as fx

PYRAMID_M3 = 100.0 * 100.0 * 50.0 / 3.0  # A²·H/3
PYRAMID_SLICES_M3 = (81_333.333, 49_333.333, 25_333.333, 9_333.333, 1_333.333)
CIRCULAR_PIT_M3 = 1_308_944.006  # plan 006 §5.4 A2, al dm³
B24_M3 = 10_005_966.77  # plan 006 §5.4 A2, a la centésima de m³
ROUNDED = 5e-4  # media unidad del último decimal de las cifras redondeadas al dm³
HAND_SUM = 1e-12  # suma a mano de superficies lineales en celdas alineadas: exacta salvo redondeo

# Columna sintética, de arriba abajo (u = x − oeste, v = y − sur, en m; 100 × 80 m = 8.000 m²):
# muro bajo z_m = 600 + 0,05u + 0,02v; capa útil hasta z_c = 614 + 0,03u + 0,04v; montera hasta
# el terreno z_g = 622 + 0,02u + 0,05v; escombro de 5 m sobre la capa útil en [10, 30] × [10, 30]
# (400 m², sin montera); acopio de 4 m sobre el terreno en [60, 90] × [40, 70] (900 m²); final a
# la cota 595 salvo un terraplén de 3 m en [90, 100] × [0, 20] (200 m²). Por la media de cada plano
# en su rectángulo: muro 8.000·8,3 − 200·9,95 = 64.410; capa útil 8.000·13,8 − 200·12,3 = 107.940;
# montera 8.000·7,9 − 400·8 − 200·7,15 = 58.570; escombro 400·5; acopio 900·4.
COLUMN_M3 = {
    "acopio": 3_600.0,
    "escombro": 2_000.0,
    "montera": 58_570.0,
    "capa_util": 107_940.0,
    "muro": 64_410.0,
}
COLUMN_CUT_M3 = 236_520.0
COLUMN_FILL_M3 = 600.0
COMPONENTS_M3 = {"caliza": 89_050.5, "arcilla": 18_889.5}  # 82,50 % y 17,50 % de 107.940
ANALYTIC = 1e-12  # cifras analíticas de la columna frente a las de arriba (cuentas en float64)


def _close(test: unittest.TestCase, found: dict[str, float], expected: dict[str, float]) -> None:
    """Las mismas claves y cada valor a ≤ :data:`ANALYTIC` relativo del esperado."""
    test.assertEqual(found.keys(), expected.keys())
    for key, value in expected.items():
        test.assertLessEqual(abs(found[key] - value) / value, ANALYTIC,
                             f"{key}: {found[key]!r} frente a {value!r}")


def _hand_volume(start: np.ndarray, final: np.ndarray, cell_area: float) -> float:
    """Σ (partida − final)·A en las celdas con dato en las dos (el desmonte menos el terraplén),
    sin el núcleo."""
    valid = np.isfinite(start) & np.isfinite(final)
    return float(np.sum(start[valid] - final[valid])) * cell_area


def _ring_area(ring: np.ndarray) -> float:
    """Área con signo (m²) de un anillo cerrado (positiva si es antihorario)."""
    x, y = ring[:, 0], ring[:, 1]
    return 0.5 * float(np.sum(x[:-1] * y[1:] - x[1:] * y[:-1]))


class PyramidAnalyticTest(unittest.TestCase):
    """CE-011-01: la pirámide de referencia, su volumen, sus rodajas, sus posiciones y sus
    cuadrantes."""

    def test_volume_and_slices(self) -> None:
        """RF-011-01, RF-011-09 (CE-011-01): V = A²·H/3 = 166.666,667 m³; las rodajas de 10 m
        desde la base (cotas 600 a 650), V·[(1 − h₀/H)³ − (1 − h₁/H)³], dan las cinco cifras del
        plan y suman V; fuera de la pirámide, cero, y una rodaja que empieza bajo la base cuenta
        solo lo que hay sobre ella."""
        self.assertEqual(fx.pyramid_volume(), PYRAMID_M3)
        self.assertAlmostEqual(fx.pyramid_volume(), 166_666.667, delta=ROUNDED)
        slices = fx.pyramid_slices(10.0)
        self.assertEqual([(low, high) for low, high, _ in slices],
                         [(600.0, 610.0), (610.0, 620.0), (620.0, 630.0), (630.0, 640.0),
                          (640.0, 650.0)])
        for (low, high, volume), expected in zip(slices, PYRAMID_SLICES_M3, strict=True):
            with self.subTest(slice=(low, high)):
                self.assertAlmostEqual(volume, expected, delta=ROUNDED)
        total = sum(volume for _, _, volume in slices)
        self.assertLessEqual(abs(total - PYRAMID_M3) / PYRAMID_M3, HAND_SUM)
        self.assertEqual(fx.pyramid_slice_volume(600.0, 650.0), PYRAMID_M3)
        self.assertEqual(fx.pyramid_slice_volume(650.0, 700.0), 0.0)
        self.assertEqual(fx.pyramid_slice_volume(550.0, 600.0), 0.0)
        self.assertEqual(fx.pyramid_slice_volume(590.0, 610.0), slices[0][2])

    def test_positions(self) -> None:
        """RF-011-01 (CE-011-01): con 2, 1 y 0,5 m, el vértice en 24 posiciones distintas (6 de x
        y 4 de y) cerca del centro de una ventana de 200 m, con la base entera dentro; la rejilla
        de cada paso, de ≤ 400 × 400 celdas con el área de celda del paso."""
        self.assertEqual(fx.PYRAMID_STEPS, (2.0, 1.0, 0.5))
        extent = fx.PYRAMID_WINDOW
        half = fx.PYRAMID_BASE_M / 2.0
        for step in fx.PYRAMID_STEPS:
            with self.subTest(step=step):
                grid = fx.pyramid_grid(step)
                cells = round(200.0 / step)
                self.assertEqual(grid.shape, (cells, cells))
                self.assertLessEqual(max(grid.shape), 400)
                self.assertEqual(grid.cell_area, step * step)
                self.assertEqual(grid.extent, extent)
                apexes = fx.pyramid_apexes(step)
                self.assertEqual(len(apexes), 24)
                self.assertEqual(len(set(apexes)), 24)
                self.assertEqual(len({x for x, _ in apexes}), 6)
                self.assertEqual(len({y for _, y in apexes}), 4)
                for x, y in apexes:
                    self.assertTrue(extent.xmin < x - half and x + half < extent.xmax)
                    self.assertTrue(extent.ymin < y - half and y + half < extent.ymax)

    def test_quadrants(self) -> None:
        """RF-011-07 (CE-011-01): los cuatro cuadrantes de la pirámide, cortados por su vértice,
        son polígonos con su identificador y su valor, anillos cerrados y antihorarios que parten
        la ventana; con el vértice en un nodo de la rejilla, cada uno tiene a mano la misma
        cuarta parte del volumen muestreado, y los cuatro suman el total."""
        for apex in (fx.pyramid_apexes(2.0)[5], fx.PYRAMID_CENTER):
            quadrants = fx.pyramid_quadrants(apex)
            self.assertEqual([q.fid for q in quadrants], [1, 2, 3, 4])
            self.assertEqual(len({q.value for q in quadrants}), 4)
            areas = []
            for quadrant in quadrants:
                with self.subTest(apex=apex, quadrant=quadrant.value):
                    (ring,) = quadrant.rings
                    self.assertEqual(ring.dtype, np.float64)
                    np.testing.assert_array_equal(ring[0], ring[-1])
                    self.assertGreater(_ring_area(ring), 0.0)
                    self.assertIn(tuple(apex), {tuple(point) for point in ring})
                    areas.append(_ring_area(ring))
            window = fx.PYRAMID_WINDOW
            whole = (window.xmax - window.xmin) * (window.ymax - window.ymin)
            self.assertLessEqual(abs(sum(areas) - whole) / whole, HAND_SUM)
        case = fx.pyramid(1.0, fx.PYRAMID_CENTER)  # el centro es un nodo con 1 m
        x, y = case.start.grid.centers()
        height = (case.start.values - case.final.values) * case.start.grid.cell_area
        apex_x, apex_y = fx.PYRAMID_CENTER
        parts = [float(np.sum(height[(x > apex_x) & (y > apex_y)])),
                 float(np.sum(height[(x < apex_x) & (y > apex_y)])),
                 float(np.sum(height[(x < apex_x) & (y < apex_y)])),
                 float(np.sum(height[(x > apex_x) & (y < apex_y)]))]
        total = float(np.sum(height))
        for part in parts:
            self.assertLessEqual(abs(part - total / 4.0) / total, HAND_SUM)
        self.assertLessEqual(abs(sum(parts) - total) / total, HAND_SUM)


class PyramidSampledTest(unittest.TestCase):
    """CE-011-01: la pirámide muestreada en el centro de celda y la de su TIN."""

    def test_hand_sum_one_metre(self) -> None:
        """RF-011-01 (CE-011-01, D-14 a): con celdas de 1 m y el vértice en cuatro de sus 24
        posiciones, la suma a mano Σ (partida − final)·área de celda da el volumen de la pirámide
        con error ≤ 0,1 %; la final es el plano de la cota 600 y nunca queda por encima de la de
        partida (todo desmonte)."""
        apexes = fx.pyramid_apexes(1.0)
        for apex in (apexes[0], apexes[7], apexes[14], apexes[23]):
            with self.subTest(apex=apex):
                case = fx.pyramid(1.0, apex)
                self.assertEqual(case.center, apex)
                self.assertEqual(case.cut_m3, PYRAMID_M3)
                self.assertEqual(case.fill_m3, 0.0)
                self.assertTrue(case.start.grid.same_geometry(case.final.grid))
                self.assertEqual(case.start.crs, case.final.crs)
                self.assertEqual(case.start.vertical, case.final.vertical)
                self.assertTrue(np.all(case.final.values == fx.PYRAMID_FLOOR_Z))
                self.assertTrue(np.all(case.start.values >= case.final.values))
                volume = _hand_volume(case.start.values, case.final.values,
                                      case.start.grid.cell_area)
                error = abs(volume - PYRAMID_M3) / PYRAMID_M3
                self.assertLessEqual(error, fx.PYRAMID_TOLERANCE,
                                     f"{volume:.3f} m³, error {100 * error:.4f} %")

    def test_tin(self) -> None:
        """RF-011-01, RF-011-02 (CE-011-01): la pirámide como TIN de cinco vértices y cuatro caras
        antihorarias, llevada a rejilla con ``gis.tin.tin_to_raster`` (sin remuestrear nada
        más), da en cada celda con dato la cota de la pirámide analítica (≤ 1 µm); sin dato,
        solo donde la analítica está en su base; y su volumen a mano, el de la analítica
        (≤ 10⁻⁹)."""
        apex = fx.pyramid_apexes(2.0)[-1]
        tin = fx.pyramid_tin(apex)
        self.assertEqual(tin.vertices.shape, (5, 3))
        self.assertEqual(tin.faces.shape, (4, 3))
        xy = tin.vertices[:, :2]
        for face in tin.faces:
            a, b, c = xy[face]
            cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            self.assertGreater(cross, 0.0)
        from_tin = fx.pyramid_from_tin(2.0, apex)
        analytic = fx.pyramid(2.0, apex)
        self.assertTrue(from_tin.start.grid.same_geometry(analytic.start.grid))
        np.testing.assert_array_equal(from_tin.final.values, analytic.final.values)
        values = from_tin.start.values
        finite = np.isfinite(values)
        self.assertGreater(int(np.count_nonzero(finite)), 0)
        self.assertLessEqual(float(np.max(np.abs(values[finite] - analytic.start.values[finite]))),
                             1e-6)
        self.assertTrue(np.all(analytic.start.values[~finite] == fx.PYRAMID_FLOOR_Z))
        cell_area = analytic.start.grid.cell_area
        expected = _hand_volume(analytic.start.values, analytic.final.values, cell_area)
        volume = _hand_volume(values, from_tin.final.values, cell_area)
        self.assertLessEqual(abs(volume - expected) / expected, 1e-9)
        self.assertEqual(from_tin.cut_m3, PYRAMID_M3)


class OtherReferencesTest(unittest.TestCase):
    """La corta circular de la 006 y el prisma B24, como pares de superficies de la 011."""

    def test_circular_pit(self) -> None:
        """RF-011-01 (RF-006-03): la corta circular del generador de la 006, 1.308.944,006 m³
        analíticos; con 4 m y el eje en sus 6 posiciones, la suma a mano (terreno − corta) da su
        volumen dentro de su tolerancia (0,025 %); todo desmonte."""
        self.assertAlmostEqual(fx.circular_pit_volume(), CIRCULAR_PIT_M3, delta=ROUNDED)
        self.assertEqual(fx.CIRCULAR_PIT_TOLERANCE,
                         {4.0: 2.5e-4, 2.0: 1e-4, 1.0: 1e-4, 0.5: 1e-4})
        axes = fx.circular_pit_axes()
        self.assertEqual(len(axes), 6)
        for name, axis in axes:
            with self.subTest(position=name):
                case = fx.circular_pit(4.0, axis)
                self.assertEqual(case.start.grid.shape, (65, 65))
                self.assertEqual(case.cut_m3, fx.circular_pit_volume())
                self.assertTrue(np.all(case.start.values >= case.final.values))
                volume = _hand_volume(case.start.values, case.final.values,
                                      case.start.grid.cell_area)
                error = abs(volume - CIRCULAR_PIT_M3) / CIRCULAR_PIT_M3
                self.assertLessEqual(error, fx.CIRCULAR_PIT_TOLERANCE[4.0])

    def test_b24_prism(self) -> None:
        """RF-011-01 (RF-006-02, B24): el prisma de 10 m sobre celdas de 1,0002942907592702 ×
        1,0003022974607014 m da 10.005.966,77 m³ con 1.000 × 1.000 celdas; con 20 × 20, la suma a
        mano con el área real de celda (nunca 1 m²) da 10·400·dx·dy (≤ 10⁻⁹)."""
        self.assertAlmostEqual(fx.b24_volume(), B24_M3, delta=0.005)
        case = fx.b24_prism(20)
        grid = case.start.grid
        self.assertEqual(grid.shape, (20, 20))
        self.assertEqual(grid.cell_area, fx.B24_DX * fx.B24_DY)
        self.assertEqual(case.cut_m3, fx.b24_volume(20))
        self.assertEqual(case.cut_m3, 10.0 * 400 * fx.B24_DX * fx.B24_DY)
        volume = _hand_volume(case.start.values, case.final.values, grid.cell_area)
        self.assertLessEqual(abs(volume - case.cut_m3) / case.cut_m3, 1e-9)


class MaterialColumnTest(unittest.TestCase):
    """CE-011-02 y CE-011-03: la columna de materiales sintética."""

    def test_units(self) -> None:
        """RF-011-11, RF-011-14, RF-011-16 (CE-011-02, CE-011-03): la columna de arriba abajo es
        acopio (antrópica, suelta, útil), escombro (antrópica, suelta, estéril), montera (natural,
        in situ, estéril), capa útil (compuesta: caliza útil 82,50 % y arcilla estéril 17,50 %) y
        muro (la última, sin base); las antrópicas, con base y espesor (≥ 0, sobre el umbral de
        presencia donde están y 0 fuera); todas las superficies en la misma rejilla, CRS y datum;
        cada unidad o componente con una densidad y un K sintéticos de prueba (K ≥ 1)."""
        column = fx.material_column()
        self.assertEqual([u.code for u in column.units],
                         ["acopio", "escombro", "montera", "capa_util", "muro"])
        kinds = {u.code: (u.kind, u.role, u.state) for u in column.units}
        self.assertEqual(kinds, {
            "acopio": ("anthropic", "useful", "loose"),
            "escombro": ("anthropic", "waste", "loose"),
            "montera": ("natural", "waste", "in_situ"),
            "capa_util": ("compound", None, "in_situ"),
            "muro": ("natural", "waste", "in_situ"),
        })
        self.assertIsNone(column.units[-1].base)
        surfaces = [column.start, column.final]
        for unit in column.units:
            with self.subTest(unit=unit.code):
                self.assertTrue(unit.name)
                if unit is not column.units[-1]:
                    self.assertIsNotNone(unit.base)
                    surfaces.append(unit.base)
                if unit.kind == "anthropic":
                    thickness = unit.thickness.values
                    self.assertTrue(np.all(thickness >= 0.0))
                    present = thickness > fx.ANTHROPIC_PRESENCE_M
                    self.assertTrue(np.any(present))
                    self.assertTrue(np.all(thickness[~present] == 0.0))
                    surfaces.append(unit.thickness)
                else:
                    self.assertIsNone(unit.thickness)
                if unit.kind == "compound":
                    self.assertIsNone(unit.density_t_m3)
                    self.assertEqual([c.code for c in unit.components], ["caliza", "arcilla"])
                    self.assertEqual([c.role for c in unit.components], ["useful", "waste"])
                    self.assertEqual(sum(c.percent for c in unit.components), 100.0)
                    materials = unit.components
                else:
                    self.assertEqual(unit.components, ())
                    materials = (unit,)
                for material in materials:
                    self.assertGreater(material.density_t_m3, 0.0)
                    self.assertGreaterEqual(material.swell, 1.0)
        for surface in surfaces:
            self.assertTrue(surface.grid.same_geometry(column.grid))
            self.assertEqual(surface.crs, column.start.crs)
            self.assertEqual(surface.vertical, column.start.vertical)
            self.assertTrue(np.all(np.isfinite(surface.values)))
        self.assertEqual(column.grid.cell_area, 4.0)

    def test_volumes_by_hand(self) -> None:
        """RF-011-12, RF-011-14 (CE-011-02): los volúmenes analíticos de cada unidad (acopio
        3.600, escombro 2.000, montera 58.570, capa útil 107.940 y muro 64.410 m³) son su espesor
        sumado a mano en las celdas de desmonte (el acopio y el escombro, su espesor donde
        están; la montera, entre su base y la del acopio fuera del escombro; la capa útil, entre
        su base y la de la montera, también bajo el escombro; el muro, entre su base y la
        final); suman el desmonte, 236.520 m³ (≤ 10⁻¹²), y los 600 m³ de terraplén quedan
        aparte; los componentes de la capa útil, por sus porcentajes, suman su unidad."""
        column = fx.material_column()
        units = {u.code: u for u in column.units}
        _close(self, {code: u.expected_m3 for code, u in units.items()}, COLUMN_M3)
        _close(self, {"cut": column.cut_m3, "fill": column.fill_m3},
               {"cut": COLUMN_CUT_M3, "fill": COLUMN_FILL_M3})
        area = column.grid.cell_area
        start, final = column.start.values, column.final.values
        cut = start > final
        hand_cut = float(np.sum((start - final)[cut])) * area
        hand_fill = float(np.sum((final - start)[~cut])) * area
        self.assertLessEqual(abs(hand_cut - COLUMN_CUT_M3) / COLUMN_CUT_M3, HAND_SUM)
        self.assertLessEqual(abs(hand_fill - COLUMN_FILL_M3) / COLUMN_FILL_M3, HAND_SUM)
        debris = units["escombro"].thickness.values > fx.ANTHROPIC_PRESENCE_M
        by_hand = {
            "acopio": units["acopio"].thickness.values[cut],
            "escombro": units["escombro"].thickness.values[cut],
            "montera": (units["acopio"].base.values
                        - units["montera"].base.values)[cut & ~debris],
            "capa_util": (units["montera"].base.values - units["capa_util"].base.values)[cut],
            "muro": (units["capa_util"].base.values - final)[cut],
        }
        for code, thickness in by_hand.items():
            with self.subTest(unit=code):
                volume = float(np.sum(thickness)) * area
                self.assertLessEqual(abs(volume - COLUMN_M3[code]) / COLUMN_M3[code], HAND_SUM,
                                     f"{volume:.6f} m³")
        self.assertLessEqual(abs(sum(COLUMN_M3.values()) - COLUMN_CUT_M3) / COLUMN_CUT_M3,
                             HAND_SUM)
        compound = units["capa_util"]
        _close(self, {c.code: c.expected_m3 for c in compound.components}, COMPONENTS_M3)
        parts = sum(c.expected_m3 for c in compound.components)
        self.assertLessEqual(abs(parts - compound.expected_m3) / compound.expected_m3, HAND_SUM)

    def test_without_debris(self) -> None:
        """RF-011-12, RF-011-14 (CE-011-02): con las mismas superficies y sin la unidad de
        escombro, la capa útil tiene el mismo volumen analítico (el escombro no la resta) y la
        montera recibe los 2.000 m³ que había sobre ella; el desmonte no cambia."""
        with_debris = fx.material_column()
        without = fx.material_column(debris=False)
        self.assertEqual([u.code for u in without.units],
                         ["acopio", "montera", "capa_util", "muro"])
        np.testing.assert_array_equal(without.start.values, with_debris.start.values)
        np.testing.assert_array_equal(without.final.values, with_debris.final.values)
        _close(self, {u.code: u.expected_m3 for u in without.units},
               {"acopio": 3_600.0, "montera": 60_570.0, "capa_util": 107_940.0,
                "muro": 64_410.0})
        self.assertEqual(without.units[2].expected_m3, with_debris.units[3].expected_m3)
        self.assertEqual(without.cut_m3, with_debris.cut_m3)


if __name__ == "__main__":
    unittest.main()

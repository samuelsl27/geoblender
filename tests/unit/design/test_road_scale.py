# SPDX-License-Identifier: GPL-3.0-or-later
"""Los datos puros de las pistas a escala (spec 017, T34; RNF-017-01 a 04 y 08; plan 017 §7.1 y §7.3): ``tests/support/road_scale.py`` no carga ``geoblender`` (lo usan las pruebas de
dentro de Blender, ``perf_roads.py``, donde no se puede cargar otra copia del paquete: ``docs/trampas.md`` §4) y da **lo mismo, bit a bit,** que ``tests/support/road_data.py`` (T01) en las
clases de la copia del paquete, de modo que las pruebas de rendimiento de dentro y de fuera de Blender miden los mismos datos.
"""

from __future__ import annotations

import ast
import math
import unittest
from pathlib import Path

import numpy as np

from tests.support import road_data as rd
from tests.support import road_scale as scale
from tests.support.package import import_geoblender

road_axis = import_geoblender("design.road_axis")
road_engrave = import_geoblender("design.road_engrave")
params = import_geoblender("design.params")


class PureDataTest(unittest.TestCase):
    def test_the_module_does_not_load_geoblender(self) -> None:
        """RNF-017-06 y 08: ``road_scale`` solo importa numpy, la biblioteca estándar y los datos puros de las pruebas (``constraints_data``): ni ``import_geoblender`` ni ``bpy``."""
        tree = ast.parse(Path(scale.__file__).read_text(encoding="utf-8"))
        imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module and node.level == 0}
        self.assertEqual(imported - {"__future__", "numpy", "tests"}, set())
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        self.assertNotIn("import_geoblender", names)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("tests"):
                self.assertEqual(node.module, "tests.support", node.module)
                self.assertEqual({alias.name for alias in node.names}, {"constraints_data"})


class SameAsTheFixtureTest(unittest.TestCase):
    def test_the_grid_the_ravine_and_the_ends_are_the_ones_of_the_fixture(self) -> None:
        """RNF-017-01, RNF-017-02: la rejilla de 1.654 × 1.699 celdas de 1 m, el barranco de 14 m (x = 827) y la ruta de 1.500 m de ``road_data`` (T01), bit a bit."""
        grid = rd.scale_grid()
        self.assertEqual((grid.ncols, grid.nrows, grid.dx, grid.dy), (scale.COLS, scale.ROWS, scale.STEP_M, scale.STEP_M))
        self.assertEqual(rd.origin_of(grid), (scale.WEST, scale.SOUTH))
        spec = rd.scale_ravine_spec()
        self.assertEqual((spec.origin, spec.destination, spec.axis_x), (scale.RAVINE_ORIGIN, scale.RAVINE_DESTINATION, scale.RAVINE_X_M))
        np.testing.assert_array_equal(scale.ravine_terrain(), rd.scale_ravine_terrain())
        x, y = scale.local_centers()
        ex, ey = rd.local_centers(grid)
        np.testing.assert_array_equal((x, y), (ex, ey))
        points = np.array([[1.0, 2.0], [300.5, 40.25]])
        np.testing.assert_array_equal(scale.absolute(points), rd.absolute(points, grid))

    def test_the_axes_and_the_twenty_lines_are_the_ones_of_the_fixture(self) -> None:
        """RNF-017-03, RNF-017-04, RNF-017-08: los ejes de 2 km y de 5 km y las veinte pistas de 5.000 vértices son los de ``road_data`` (T01), bit a bit; los veinte ejes de la revisión
        son los de la vista previa muestreados (de ``(k, 2)`` y en el orden de las pistas)."""
        np.testing.assert_array_equal(scale.axis_2km(), rd.scale_axis_2km())
        np.testing.assert_array_equal(scale.axis_5km(), rd.scale_axis_5km())
        np.testing.assert_array_equal(scale.preview_lines(), rd.scale_preview_lines())
        chain = scale.chain_axes()
        self.assertEqual(len(chain), rd.SCALE_ROADS)
        for index, line in enumerate(chain):
            self.assertEqual(line.shape[1], 2)
            self.assertGreaterEqual(len(line), 100)
            np.testing.assert_array_equal(line[0], rd.scale_preview_lines()[index, 0, :2])

    def test_the_reference_profile_is_the_one_of_the_fixture(self) -> None:
        """RNF-017-04: el perfil de pista de referencia de ``road_scale`` tiene los mismos valores que ``road_data.PROFILE`` (cada parámetro de ``RoadProfileParam``, por su nombre)."""
        self.assertEqual({param.value for param in params.RoadProfileParam}, set(scale.PROFILE))
        for param in params.RoadProfileParam:
            expected = getattr(rd.PROFILE, "class_name" if param.value == "class" else param.value)
            self.assertEqual(scale.PROFILE[param.value], expected, param.value)
        self.assertEqual((scale.CURVE_RADIUS_M, scale.MIN_RADIUS_M), (rd.PROFILE.curve_radius_m, rd.PROFILE.min_radius_m))


class CompactAxisTest(unittest.TestCase):
    def test_the_compact_axis_has_61_curves_of_70_degrees_that_fit_and_a_window_of_at_most_2_m_cells(self) -> None:
        """RNF-017-04: el eje compacto tiene 63 vértices y 61 curvas (R = 20 m), que giran 70° con tangentes de 14 m que caben en sus tramos de 32,8 m, y la ventana de grabado de la caja
        de la spec es de ≤ 2 M celdas (la del eje en diagonal, de más: 2,42 M)."""
        line = scale.compact_axis_2km()
        self.assertEqual(len(line), 63)
        legs = np.diff(line, axis=0)
        np.testing.assert_allclose(np.hypot(*legs.T), 2_035.0 / 62.0, rtol=1e-9)
        headings = np.degrees(np.arctan2(legs[:, 0], legs[:, 1]))
        turn = np.abs(np.diff(headings))
        np.testing.assert_allclose(turn, 70.0, atol=1e-9)
        self.assertLess(scale.CURVE_RADIUS_M * math.tan(math.radians(35.0)) * 2.0, 2_035.0 / 62.0)
        axis = road_axis.axis_of(line, scale.CURVE_RADIUS_M, scale.MIN_RADIUS_M, 1.0)
        self.assertEqual(axis.curve_count, 61)
        grid = rd.scale_grid()
        profile = rd.road_profile(rd.PROFILE)
        for found, low, high in ((line, 1_600_000, 2_000_000), (scale.axis_2km(), 2_300_000, 2_500_000)):
            window = road_engrave.engrave_window(road_axis.axis_of(found, scale.CURVE_RADIUS_M, scale.MIN_RADIUS_M, 1.0), profile, grid)
            cells = (window[0].stop - window[0].start) * (window[1].stop - window[1].start)
            self.assertGreater(cells, low)
            self.assertLessEqual(cells, high)


if __name__ == "__main__":
    unittest.main()

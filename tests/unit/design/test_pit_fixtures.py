# SPDX-License-Identifier: GPL-3.0-or-later
"""Los terrenos y las cortas de prueba de la corta por bancos (spec 018, T01; plan 018 §5.1, §7.1 y §7.4; CE-018-01 a
04, 06 y 07).

Recorre ``tests.support.pit_data`` antes de que la usen las pruebas de la 018, con cuentas hechas aquí otra vez de otra
manera (integración numérica del perfil, un polígono redondeado a trozos, un bucle de Python por banco, fuerza bruta),
no con el código que genera los datos; y que los nombres de ``main`` en los que se apoya el plan 018 (§5) siguen ahí.
Todo es sintético (ningún dato de cliente) y rápido (mallas de ≤ 200 × 200); el proyecto, la rejilla de 1 m y la escala,
en ``milestone_pit_fixtures.py``.
"""

from __future__ import annotations

import ast
import math
import tomllib
import unittest

import numpy as np

from tests.support import pit_data as pd
from tests.support.package import import_geoblender
from tests.support.repo import EXTENSION_DIR


def shoelace(points: np.ndarray) -> float:
    """El área con signo del anillo ``points`` (fórmula de la lazada)."""
    x, y = points[:, 0], points[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


class ProfilesAndRoseTest(unittest.TestCase):
    """Los perfiles de la 013 con el ancla de la corta y la roseta de CE-018-02."""

    def test_profiles_and_their_derived_figures(self) -> None:
        """CE-018-01, CE-018-04: ``EXPL_10_60_6`` avanza 10/tan 60° + 6 = 11,7735 m y ``DESD_10_45_6`` 10 + 6 = 16 m."""
        self.assertEqual((pd.EXPL.height_m, pd.EXPL.face_deg, pd.EXPL.berm_m), (10.0, 60.0, 6.0))
        self.assertEqual((pd.DESD.height_m, pd.DESD.face_deg, pd.DESD.berm_m), (10.0, 45.0, 6.0))
        self.assertAlmostEqual(pd.EXPL.advance_m, 10.0 / math.sqrt(3.0) + 6.0, places=12)
        self.assertAlmostEqual(pd.EXPL.advance_m, 11.7735, places=4)
        self.assertAlmostEqual(pd.DESD.advance_m, 16.0, places=12)
        self.assertEqual((pd.EXPL.anchor_m, pd.DESD.anchor_m), (125.0, 100.0))

    def test_the_rose_of_two_ranges(self) -> None:
        """CE-018-02: 5,7735 m donde la cara tiene azimut 90° y 10,0000 m donde tiene 270°; sin huecos entre rangos."""
        self.assertAlmostEqual(pd.rose_distance_by_hand(pd.ROSE_TWO_RANGES, 90.0), 5.7735, places=4)
        self.assertAlmostEqual(pd.rose_distance_by_hand(pd.ROSE_TWO_RANGES, 270.0), 10.0, places=12)
        self.assertAlmostEqual(pd.rose_distance_by_hand(pd.ROSE_TWO_RANGES, -90.0), 10.0, places=12)
        self.assertAlmostEqual(pd.rose_distance_by_hand(pd.ROSE_TWO_RANGES, 180.0), 10.0, places=12)
        for first, second in zip(pd.ROSE_TWO_RANGES, pd.ROSE_TWO_RANGES[1:]):
            self.assertEqual(first.to_deg, second.from_deg)
        self.assertEqual((pd.ROSE_TWO_RANGES[0].from_deg, pd.ROSE_TWO_RANGES[-1].to_deg), (0.0, 360.0))
        with self.assertRaises(ValueError):
            pd.rose_distance_by_hand(pd.ROSE_TWO_RANGES[:1], 270.0)

    def test_the_hypotheses_are_marked_and_simple(self) -> None:
        """T01-a (D-14, D-15, P-5): arco de 1 mm en las cifras a mano y de 5 cm en las demás, simplificación de 0,05 m y
        ventana de 12 m, todo HIPÓTESIS."""
        self.assertEqual(pd.HYPOTHESIS_NAMES, ("arc_hand_m", "arc_m", "simplify_m", "az_window_m"))
        self.assertEqual((pd.HYPOTHESES.arc_hand_m, pd.HYPOTHESES.arc_m, pd.HYPOTHESES.simplify_m,
                          pd.HYPOTHESES.az_window_m), (0.001, 0.05, 0.05, 12.0))
        self.assertIn("HIPÓTESIS", pd.__doc__ or "")


class TerrainTest(unittest.TestCase):
    """Los tres terrenos: llano a 175 m, inclinado un 10 % y llano a 100 m."""

    grid = pd.grid_of(2.0)

    def test_the_flat_terrain(self) -> None:
        """CE-018-03: 175 m en todas las celdas (cinco bancos de 10 m sobre el fondo a 125 m)."""
        terrain = pd.flat_terrain(self.grid)
        self.assertEqual(terrain.shape, (200, 200))
        self.assertTrue(np.all(terrain == 175.0))
        self.assertEqual(pd.TOP_Z_M - pd.FLOOR_Z_M, pd.BENCHES * pd.EXPL.height_m)

    def test_the_inclined_terrain_by_columns(self) -> None:
        """CE-018-07: el terreno sube 0,1 m por metro hacia el este: el centro de la columna ``c`` de 2 m (x = 2c + 1)
        está a 130 + 0,1·x y no depende de la fila; 150 m en x = 200."""
        terrain = pd.inclined_terrain(self.grid)
        for column in (0, 1, 50, 99, 100, 199):
            x = 2.0 * column + 1.0
            self.assertTrue(np.allclose(terrain[:, column], 130.0 + 0.1 * x, atol=1e-12), column)
        self.assertAlmostEqual(float(terrain[0, 99]) / 2.0 + float(terrain[0, 100]) / 2.0, 150.0, places=12)
        self.assertAlmostEqual(float(terrain[10, 100] - terrain[10, 99]), 0.2, places=12)  # 10 % de 2 m

    def test_the_limit_terrain(self) -> None:
        """CE-018-04: llano a 100 m."""
        self.assertTrue(np.all(pd.limit_terrain(self.grid) == 100.0))

    def test_each_call_is_a_new_array(self) -> None:
        first, second = pd.flat_terrain(self.grid), pd.flat_terrain(self.grid)
        first[0, 0] = -1.0
        self.assertEqual(second[0, 0], 175.0)

    def test_the_project_rasters_name_the_three_terrains(self) -> None:
        self.assertEqual(tuple(pd.RASTERS), ("corta_llano", "corta_inclinado", "corta_limite"))
        self.assertEqual(pd.dataset_of("corta_llano"), "gis_dtm_corta_llano")
        for make in pd.RASTERS.values():
            self.assertEqual(make(self.grid).shape, self.grid.shape)


class RingsTest(unittest.TestCase):
    """Los fondos y los límites."""

    def test_the_circle(self) -> None:
        """CE-018-03: 720 vértices a 50 m del centro, antihorario, sin repetir el primero; el área es la del polígono
        inscrito ``n/2·r²·sin(2π/n)``."""
        ring = pd.circle_ring()
        self.assertEqual(ring.shape, (720, 2))
        radius = np.hypot(ring[:, 0] - 200.0, ring[:, 1] - 200.0)
        self.assertTrue(np.allclose(radius, 50.0, atol=1e-12))
        self.assertAlmostEqual(shoelace(ring), 360.0 * 2500.0 * math.sin(2.0 * math.pi / 720.0), places=6)
        self.assertGreater(shoelace(ring), 0.0)
        self.assertFalse(np.allclose(ring[0], ring[-1]))

    def test_the_squares_and_the_rectangle(self) -> None:
        """CE-018-01, 04 y 06: cuadrado de 100 m, límite de 200 m y rectángulo de 200 × 60 m, antihorarios desde el
        suroeste y con el centro en (200, 200)."""
        for ring, side_x, side_y in ((pd.square_ring(pd.SQUARE_SIDE_M), 100.0, 100.0),
                                     (pd.square_ring(pd.LIMIT_SIDE_M), 200.0, 200.0),
                                     (pd.rect_ring(pd.ZIGZAG_LENGTH_M, pd.ZIGZAG_WIDTH_M), 200.0, 60.0)):
            self.assertEqual(ring.shape, (4, 2))
            self.assertAlmostEqual(shoelace(ring), side_x * side_y, places=9)
            self.assertTrue(np.allclose(ring.mean(axis=0), (200.0, 200.0)))
            self.assertAlmostEqual(float(np.ptp(ring[:, 0])), side_x)
            self.assertAlmostEqual(float(np.ptp(ring[:, 1])), side_y)
        self.assertTrue(np.allclose(pd.square_ring(100.0)[0], (150.0, 150.0)))


class CircleByHandTest(unittest.TestCase):
    """CE-018-03: el volumen analítico del círculo, comprobado con la integral del perfil y con la rejilla."""

    def test_radii_by_hand(self) -> None:
        """Pies y crestas: ``cresta = pie + 5,7735`` y ``pie_{k+1} = cresta_k + 6`` desde 50 m (un bucle a mano)."""
        run = 10.0 / math.tan(math.radians(60.0))
        foot = 50.0
        expected = []
        for _ in range(5):
            expected.append((foot, foot + run))
            foot += run + 6.0
        found = pd.circle_radii_by_hand()
        self.assertEqual(len(found), 5)
        for (a, b), (c, d) in zip(found, expected):
            self.assertAlmostEqual(a, c, places=12)
            self.assertAlmostEqual(b, d, places=12)
        self.assertAlmostEqual(found[-1][1], 102.8675, places=4)  # 50 + 5·5,7735 + 4·6

    def test_volume_matches_the_profile_integral(self) -> None:
        """El volumen analítico (961.661,6 m³) es la integral de ``π·r(z)²`` del radio de la corta a cada cota, con 400.000
        muestras de punto medio (otra manera que la suma de troncos de cono)."""
        volume = pd.circle_volume_by_hand()
        self.assertAlmostEqual(volume, 961_661.6, delta=0.05)
        tan_face = math.tan(math.radians(60.0))
        samples = 400_000
        z = (np.arange(samples) + 0.5) * (50.0 / samples)
        bench = np.minimum((z // 10.0).astype(int), 4)
        feet = np.array([foot for foot, _crest in pd.circle_radii_by_hand()])
        radius = feet[bench] + (z - 10.0 * bench) / tan_face
        self.assertAlmostEqual(float(np.sum(np.pi * radius * radius) * (50.0 / samples)), volume, delta=1.0)

    def test_surface_volume_on_the_grid(self) -> None:
        """CE-018-03 (D-11): la superficie analítica muestreada en celdas de 4 y 2 m da el volumen a ≤ 0,1 % del analítico."""
        analytic = pd.circle_volume_by_hand()
        for step in (4.0, 2.0):
            grid = pd.grid_of(step)
            cut = pd.flat_terrain(grid) - pd.circle_surface(grid)
            self.assertGreaterEqual(float(cut.min()), 0.0)
            volume = float(cut.sum()) * step * step
            self.assertLessEqual(abs(volume / analytic - 1.0), 1e-3, step)

    def test_surface_levels(self) -> None:
        """El fondo a 125 m, las bermas a 135, 145, 155 y 165 m, la cara a 60° y el terreno fuera de la última cresta."""
        grid = pd.grid_of(2.0)
        surface = pd.circle_surface(grid)
        x, y = pd.local_centers(grid)
        radius = np.hypot(x - 200.0, y - 200.0)
        self.assertTrue(np.all(surface[radius < 49.9] == 125.0))
        self.assertTrue(np.all(surface[radius > 103.0] == 175.0))
        crest_1 = pd.circle_radii_by_hand()[0][1]
        berm = (radius > crest_1 + 0.01) & (radius < crest_1 + 5.99)
        self.assertTrue(np.all(surface[berm] == 135.0))
        face = (radius > 50.0) & (radius < crest_1)
        slope = (surface[face] - 125.0) / (radius[face] - 50.0)
        self.assertTrue(np.allclose(slope, math.tan(math.radians(60.0)), atol=1e-9))


class SquareByHandTest(unittest.TestCase):
    """CE-018-01: el área de la cresta del cuadrado."""

    def test_rounded_and_mitered_areas(self) -> None:
        """12.414,12 m² redondeada (a ≤ 0,01 con un polígono de 4 lados y 4 cuartos de círculo de 20.000 puntos) y
        ``(L + 2d)²`` con inglete."""
        side, distance = 100.0, 10.0 / math.tan(math.radians(60.0))
        self.assertAlmostEqual(pd.square_crest_area_by_hand(side, distance, rounded=True), 12_414.12, delta=0.005)
        self.assertAlmostEqual(pd.square_crest_area_by_hand(side, distance, rounded=False),
                               (side + 2.0 * distance) ** 2, places=9)
        half = side / 2.0
        points = []
        for corner, start in (((half, half), 0.0), ((-half, half), 90.0), ((-half, -half), 180.0),
                              ((half, -half), 270.0)):
            angle = np.radians(start + np.linspace(0.0, 90.0, 20_000))
            points.append(np.column_stack([corner[0] + distance * np.cos(angle), corner[1] + distance * np.sin(angle)]))
        rounded = np.vstack(points)
        self.assertAlmostEqual(shoelace(rounded), pd.square_crest_area_by_hand(side, distance, rounded=True), delta=0.01)


class LimitByHandTest(unittest.TestCase):
    """CE-018-04: la corta descendente cuadrada."""

    def test_five_benches_and_the_stop(self) -> None:
        """Lados de pie 180, 148, 116, 84 y 52 m, fondo a 50 m, cotas de cresta 100 a 60 m; se detiene porque el siguiente
        pie sería de 20 m (< 30 m)."""
        benches, why = pd.limit_benches_by_hand()
        self.assertEqual(why, "min_width")
        self.assertEqual([b.foot_side_m for b in benches], [180.0, 148.0, 116.0, 84.0, 52.0])
        self.assertEqual([b.crest_side_m for b in benches], [200.0, 168.0, 136.0, 104.0, 72.0])
        self.assertEqual([b.crest_z_m for b in benches], [100.0, 90.0, 80.0, 70.0, 60.0])
        self.assertEqual([b.foot_z_m for b in benches], [90.0, 80.0, 70.0, 60.0, 50.0])
        self.assertEqual(benches[-1].foot_z_m, pd.LIMIT_FLOOR_Z_M)
        next_foot = benches[-1].foot_side_m - 2.0 * 6.0 - 2.0 * 10.0
        self.assertEqual(next_foot, 20.0)
        self.assertLess(next_foot, pd.MIN_FLOOR_WIDTH_M)

    def test_the_bottom_level_stops_at_three_benches(self) -> None:
        """Con la cota de fondo a 70 m se detiene a los 3 bancos por ese criterio."""
        benches, why = pd.limit_benches_by_hand(bottom_m=pd.LIMIT_BOTTOM_Z_M)
        self.assertEqual((len(benches), why), (3, "bottom"))
        self.assertEqual(benches[-1].foot_z_m, 70.0)
        self.assertEqual(benches[-1].foot_side_m, 116.0)

    def test_a_cut_that_is_empty_before_the_first_bench(self) -> None:
        """Un límite de 45 m daría un primer pie de 25 m (< 30 m): 0 bancos."""
        benches, why = pd.limit_benches_by_hand(side_m=45.0)
        self.assertEqual((len(benches), why), (0, "min_width"))


class RampByHandTest(unittest.TestCase):
    """CE-018-05 y 06: la longitud de eje de cada banco."""

    def test_run_per_bench(self) -> None:
        """h = 10 m: 125 m de eje con g = 8 % (la espiral) y 100 m con g = 10 % (el zig-zag)."""
        self.assertAlmostEqual(pd.ramp_run_by_hand(10.0, pd.SPIRAL_GRADE_PCT), 125.0, places=9)
        self.assertAlmostEqual(pd.ramp_run_by_hand(10.0, pd.ZIGZAG_GRADE_PCT), 100.0, places=9)
        self.assertEqual(pd.ZIGZAG_LENGTH_M / 2.0, pd.ramp_run_by_hand(10.0, pd.ZIGZAG_GRADE_PCT))  # un tramo ocupa media corta


class RoughRingTest(unittest.TestCase):
    """La polilínea rugosa y los 300 casos de la batería de la T09."""

    def test_a_ring_is_star_shaped_and_therefore_simple(self) -> None:
        """Un anillo en orden de ángulo creciente alrededor del centro, con radio positivo, es simple; ruido a 0,8 m."""
        ring = pd.rough_ring(7, 500, 0.8)
        self.assertEqual(ring.shape, (500, 2))
        dx, dy = ring[:, 0] - 200.0, ring[:, 1] - 200.0
        angle = np.unwrap(np.arctan2(dy, dx))
        self.assertTrue(np.all(np.diff(angle) > 0.0))
        self.assertLess(angle[-1] - angle[0], 2.0 * math.pi)
        self.assertGreater(float(np.hypot(dx, dy).min()), 40.0)
        self.assertGreater(shoelace(ring), 0.0)

    def test_the_noise_is_bounded(self) -> None:
        """Contra el mismo anillo sin ruido, ningún vértice se mueve más de ``noise_m`` en radio; sin ruido es liso."""
        for noise in (0.0, 0.05, 0.8):
            smooth, rough = pd.rough_ring(3, 400, 0.0), pd.rough_ring(3, 400, noise)
            deviation = np.hypot(rough[:, 0] - 200.0, rough[:, 1] - 200.0) - np.hypot(smooth[:, 0] - 200.0, smooth[:, 1] - 200.0)
            self.assertLessEqual(float(np.abs(deviation).max()), noise + 1e-9)
        self.assertGreater(float(np.abs(deviation).max()), 0.5)  # con 0,8 m se nota

    def test_the_three_hundred_cases_are_fixed(self) -> None:
        """Semillas fijas: dos recorridos dan los mismos anillos bit a bit; 300 a 1.500 vértices, ruido de 0 a 0,8 m y las
        cuatro combinaciones de ascendente o descendente con y sin roseta; todos en estrella."""
        first = list(pd.rough_cases())
        second = list(pd.rough_cases())
        self.assertEqual(len(first), pd.ROUGH_CASES)
        self.assertEqual(len({case.seed for case in first}), 300)
        combos = set()
        for one, two in zip(first, second):
            self.assertTrue(np.array_equal(one.ring, two.ring))
            self.assertTrue(300 <= one.vertices <= 1500, one.vertices)
            self.assertEqual(one.ring.shape, (one.vertices, 2))
            self.assertTrue(0.0 <= one.noise_m <= 0.8 + 1e-12)
            combos.add((one.descending, one.with_rose))
            angle = np.unwrap(np.arctan2(one.ring[:, 1] - 200.0, one.ring[:, 0] - 200.0))
            self.assertTrue(np.all(np.diff(angle) > 0.0), one.index)
        self.assertEqual(combos, {(False, False), (False, True), (True, False), (True, True)})
        self.assertEqual(min(case.vertices for case in first) >= 300 and max(case.vertices for case in first) <= 1500, True)
        self.assertGreater(max(case.noise_m for case in first), 0.79)
        self.assertEqual(first[0].noise_m, 0.0)


class ScaleTest(unittest.TestCase):
    """La escala (plan §7.3): solo la forma, sin construir el terreno de 2,81 M celdas."""

    def test_the_scale_grid(self) -> None:
        grid = pd.scale_grid()
        self.assertEqual((grid.ncols, grid.nrows), (1654, 1699))
        self.assertEqual(grid.ncols * grid.nrows, 2_810_146)

    def test_the_scale_rings_fit_in_the_grid(self) -> None:
        """60 bancos de ``EXPL`` desde 100 m llegan a 100 + 60·5,7735 + 59·6 = 800,41 m, dentro de 1.654 × 1.699 m; pie y
        cresta de cada banco, con los vértices pedidos (probado con 1.200 para no construir los 160.000)."""
        rings = pd.scale_rings(60, total_vertices=1200)
        self.assertEqual(rings.shape, (120, 10, 2))
        self.assertAlmostEqual(float(np.hypot(rings[-1, :, 0] - 827.0, rings[-1, :, 1] - 849.5).max()), 800.41, delta=0.01)
        self.assertGreater(float(rings[:, :, 0].min()), 0.0)
        self.assertLess(float(rings[:, :, 0].max()), 1654.0)
        self.assertGreater(float(rings[:, :, 1].min()), 0.0)
        self.assertLess(float(rings[:, :, 1].max()), 1699.0)
        self.assertEqual(pd.SCALE_BENCH_COUNTS, (40, 60))
        self.assertEqual(pd.SCALE_VERTICES, 160_000)


class MainNamesTest(unittest.TestCase):
    """Los nombres de ``main`` en los que se apoya el plan 018 (§2.1, §5.1)."""

    def test_domain_names(self) -> None:
        names = {
            "design.entities": ("EntityKind", "EntityType", "_TYPES", "register_entity_type", "registry"),
            "design.entity_store": ("entity_surfaces", "check_parameter_change", "bring_entities",
                                    "layers_sync_steps", "platform_compute_steps"),
            "design.entity_layer": (),
            "design.params": ("EntityParams", "entity_family", "entity_params", "check_entity_param"),
            "design.provenance": ("OPERATION_TYPES_BY_NAME", "ENTITY_OP_NAMES", "ENTITY_LAYER"),
            "design.store": ("DesignWriter", "RECOMPUTED", "recompute_run", "masks_steps"),
            "design.steps": ("Calculation",),
            "design.reproduce": (), "design.preview": (), "design.export": (),
            "design.compose": ("compose",), "design.sectors": (), "design.zones": ("cells_inside",),
            "design.profiles": (), "design.quarry": ("axis_abscissa",), "design.edges": (),
            "design.envelopes": (), "design.benching": (),
            "design.road_axis": ("axis_of",), "design.road_gradient": ("check_axis_3d",),
            "design.report": ("max_tangents",),
            "gis.polygons": ("clip", "overlay", "problems", "box_pairs", "crossings", "splice", "chain",
                             "ray_counts", "following", "expand"),
            "gis.cdt": ("PureTriangulator", "STEP_POINTS"),
            "gis.tin": ("tin_to_raster",),
            "gis.contours": ("contours_from_raster",),
        }
        for module, found in names.items():
            loaded = import_geoblender(module)
            for name in found:
                self.assertTrue(hasattr(loaded, name), f"{module}.{name}")

    def test_the_pit_type_is_registered_but_not_the_new_modules(self) -> None:
        """Estado tras la T27 (``design/pit_layer.py`` ya existe, como los demás módulos nuevos del plan): el tipo ``pit`` está registrado (T02), la roseta, la definición de rampa y los
        datos existen (T04 y T05) y los módulos nuevos del plan que quedan, como ``gis/offset.py`` (T06), existen."""
        entities = import_geoblender("design.entities")
        self.assertIn("pit", {str(getattr(item, "value", item)) for item in entities._TYPES})
        self.assertTrue((EXTENSION_DIR / "design" / "pit_layer.py").exists())  # T27
        self.assertTrue((EXTENSION_DIR / "gis" / "offset.py").exists())  # T06
        self.assertTrue((EXTENSION_DIR / "design" / "pit_offset.py").exists())  # T08
        self.assertTrue((EXTENSION_DIR / "design" / "pit_sky.py").exists())  # T19
        self.assertTrue((EXTENSION_DIR / "design" / "pit_report.py").exists())  # T20
        self.assertTrue((EXTENSION_DIR / "design" / "pit_check013.py").exists())  # T20
        self.assertTrue((EXTENSION_DIR / "design" / "pit_bench.py").exists())  # T10
        self.assertTrue((EXTENSION_DIR / "design" / "pit_store.py").exists())  # T21
        self.assertTrue((EXTENSION_DIR / "design" / "pit_ramp.py").exists())  # T15
        self.assertTrue((EXTENSION_DIR / "design" / "pit_surface.py").exists())  # T18

    def test_blender_names(self) -> None:
        """``bl/ops/des.py``, ``bl/scene/des_views.LOADERS``, ``bl/props/core.OBJECT_KINDS`` y ``bl/scene/views.BRANCHES``
        (que ``bl`` no deja importar aquí) se declaran en el código."""
        for module, found in (("ops/des.py", ("OPERATION_DEFS", "RECOMPUTE", "PARAMETER_PREFIXES")),
                              ("scene/des_views.py", ("LOADERS",)), ("props/core.py", ("OBJECT_KINDS",)),
                              ("scene/views.py", ("BRANCHES",))):
            source = (EXTENSION_DIR / "bl" / module).read_text(encoding="utf-8")
            declared = set()
            for node in ast.parse(source).body:
                target = node.targets[0] if isinstance(node, ast.Assign) else getattr(node, "target", None)
                if isinstance(target, ast.Name):
                    declared.add(target.id)
                if isinstance(node, ast.FunctionDef):
                    declared.add(node.name)
            for name in found:
                self.assertIn(name, declared, f"bl/{module} no declara {name}")

    def test_the_provisional_catalog_entries(self) -> None:
        """D-20: las órdenes de la corta (T35: las seis del menú y la de R-49) están en el catálogo y las cuatro provisionales de R-35 no."""
        text = (EXTENSION_DIR / "core" / "catalog" / "data" / "menus" / "07_design.toml").read_text(encoding="utf-8")
        tomllib.loads(text)
        for key in ("des_create_pit", "des_edit_pit_ramp", "des_edit_pit_rose", "des_pit_skyline", "des_pit_surface",
                    "des_expand_bench", "des_design_pit_from_shell"):
            self.assertIn(f"geoblender.{key}", text, key)
        for key in ("des_new_pit", "des_add_ramp", "des_compute_daylight", "des_create_design_surface"):
            self.assertNotIn(f"geoblender.{key}", text, key)


if __name__ == "__main__":
    unittest.main()

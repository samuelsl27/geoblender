# SPDX-License-Identifier: GPL-3.0-or-later
"""La huella y la rasante de una plataforma (spec 015, T06; RF-015-19 y RF-015-08 para la geometría;
plan 015 §5.4, A0 y A1; CE-015-03).

Las cuentas están hechas a mano y se comparan a ≤ 10⁻⁹ m (D-9):

- **Con eje y ancho** (el corredor de extremos planos de RF-014-09): la huella es la de
  ``quarry.corridor_cells`` y la abscisa σ, la del punto más próximo de **todo** el eje (a igual
  distancia, la menor); la rasante, ``cota inicial + σ · pendiente / 100``. El eje de 200 m y 20 m de
  ancho de «Plataforma de carga» mide 200 m ± 1 celda, **no 220 m** (error 20, CE-015-03); un eje en L
  (la «Plataforma de taller»: 4.754 celdas contadas a mano) y otro que vuelve sobre sí mismo
  (un empate entre dos tramos).
- **Con polígono** (las celdas por su centro, D-16 de la 013): el eje enlazado es la parte de la línea
  que está dentro del polígono, de lado a lado; sin enlace, el eje principal de las celdas (su matriz
  de covarianza), con su extremo más al oeste (a igual abscisa, al sur) como abscisa 0 y el aviso
  ``des.platform_axis_principal``; la rasante, la de la abscisa de su punto más próximo del eje, fijada
  en los extremos.
- **La ventana de trabajo** (A0): la huella ampliada por el alcance y dos celdas, recortada a la
  rejilla.
- **Los rechazos de RF-015-08** para la geometría: línea que se corta, sin longitud, cerrada o de
  varias partes; polígono que se corta, sin área o sin celdas; eje que no cruza su polígono de lado a
  lado; y los de lo que falta o sale de rango (ancho, cotas, alcance), cada uno con la capa, la
  entidad, el campo y el valor. Ninguna entrada se modifica y lo absoluto va en float64.
"""

from __future__ import annotations

import math
import unittest
from collections.abc import Mapping
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import entity_fixtures as efx
from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender

platform = import_geoblender("design.platform")
quarry = import_geoblender("design.quarry")
model = import_geoblender("design.model")
messages = import_geoblender("design.messages")
vector = import_geoblender("gis.vector")
gis = import_geoblender("gis")

DesignError = messages.DesignError
GRID = efx.GRID
X, Y = qfx.local_centers(GRID)
"""Los centros de celda de la cantera (locales, m desde ``BASE``), de forma ``GRID.shape``."""
AXES_DATA, POLYGONS_DATA = efx.platform_layers()
TOL = 1e-9
"""La tolerancia de las cuentas a mano (D-9)."""
PRIVATE_NAMES = ("_axis_paths", "_corridor_window")
"""Los nombres que la T06 promueve (ya no existen con guion bajo)."""


# --- Lo que construyen las pruebas -------------------------------------------------------------


def values(**changes: object) -> dict[str, object]:
    """Los parámetros resueltos de una plataforma de eje de 20 m (por último segmento de su clave)."""
    found: dict[str, object] = {"width_m": 20.0, "start_level_m": 250.0, "gradient_pct": 1.0,
                                "reach_m": 30.0}
    found.update(changes)
    return found


def line_request(name: str = "Plataforma de carga") -> Any:
    return model.PlatformRequest(
        name=name, feature=name, start="Terreno",
        fields=model.PlatformFields(layer=efx.AXES_LAYER, start_level_field="cota_inicial",
                                    gradient_field="pendiente", width_field="ancho"))


def polygon_request(name: str, *, linked: bool) -> Any:
    link = {"axis_field": efx.LINK_FIELD, "axis_layer": efx.AXES_LAYER} if linked else {}
    return model.PlatformRequest(
        name=name, feature=name, start="Terreno",
        fields=model.PlatformFields(layer=efx.POLYGONS_LAYER, start_level_field="cota_inicial",
                                    gradient_field="pendiente", **link))


def axis_geometry(name: str) -> Any:
    """La geometría de la línea ``name`` de la capa de ejes de la cantera."""
    return platform.PlatformGeometry("line", AXES_DATA.entities[efx.axis_fid(name) - 1])


def line_path(path_local: tuple[tuple[float, float], ...]) -> Any:
    return platform.PlatformGeometry("line", ((cfx.absolute(path_local),),))


def polygon_geometry(name: str, *, linked: bool = True) -> Any:
    names = [spec.name for spec in efx.POLYGONS]
    spec = efx.POLYGONS[names.index(name)]
    parts = POLYGONS_DATA.entities[names.index(name)]
    if not linked or spec.axis is None:
        return platform.PlatformGeometry("polygon", parts)
    return platform.PlatformGeometry("polygon", parts,
                                     axis_parts=AXES_DATA.entities[efx.axis_fid(spec.axis) - 1],
                                     axis_name=spec.axis)


def make_job(geometry: Any, request: Any, parameters: Mapping[str, object], *,
             start: np.ndarray | None = None, grid: Any = GRID) -> Any:
    surface = efx.plane_terrain(grid) if start is None else start
    allowed = np.ones(grid.shape, dtype=bool)
    return platform.PlatformJob(request, "PLT-001", grid, surface, geometry, parameters, allowed,
                                allowed.copy())


def axis_job(name: str, **changes: object) -> Any:
    """El trabajo de un eje válido de la capa, con sus campos como parámetros."""
    spec = efx.AXES[efx.axis_fid(name) - 1]
    return make_job(axis_geometry(name), line_request(name),
                    values(width_m=spec.width_m, start_level_m=spec.start_m,
                           gradient_pct=spec.gradient_pct, **changes))


def polygon_job(name: str, *, linked: bool = True, **changes: object) -> Any:
    spec = [s for s in efx.POLYGONS if s.name == name][0]
    return make_job(polygon_geometry(name, linked=linked),
                    polygon_request(name, linked=linked and spec.axis is not None),
                    values(start_level_m=spec.start_m, gradient_pct=spec.gradient_pct, **changes))


def on_grid(footprint: Any, array: np.ndarray, fill: object = np.nan) -> np.ndarray:
    """``array`` (de la ventana de trabajo) puesto en la rejilla entera."""
    full = np.full(GRID.shape, fill, dtype=array.dtype)
    full[footprint.window] = array
    return full


def local(point: tuple[float, float]) -> tuple[float, float]:
    """Un punto absoluto en locales (m desde ``BASE``)."""
    return (point[0] - cfx.BASE[0], point[1] - cfx.BASE[1])


def corridor_layer(path_local: tuple[tuple[float, float], ...], width: float, start: float,
                   gradient: float) -> Any:
    """Una capa de líneas de un solo corredor, como la que lee ``quarry.corridor_cells``."""
    columns = (vector.FieldColumn("ancho", "ancho", "DOUBLE"),
               vector.FieldColumn("cota_inicial", "cota_inicial", "DOUBLE"),
               vector.FieldColumn("pendiente", "pendiente", "DOUBLE"))
    return vector.FeatureLayer("line", (1,), (((cfx.absolute(path_local),),),), columns,
                               {"ancho": (width,), "cota_inicial": (start,),
                                "pendiente": (gradient,)})


# --- Lo público --------------------------------------------------------------------------------


class PublicNamesTest(unittest.TestCase):
    """RF-015-19: los dos ayudantes del corredor que usa la plataforma son públicos."""

    def test_the_two_helpers_are_public_and_the_private_names_are_gone(self) -> None:
        """``quarry.axis_paths`` y ``quarry.corridor_window`` están en ``__all__``, con su
        documentación, y los nombres con guion bajo ya no existen (sin alias), como en la T05."""
        for name in ("axis_paths", "corridor_window"):
            with self.subTest(name=name):
                self.assertIn(name, quarry.__all__)
                function = getattr(quarry, name)
                self.assertEqual(function.__module__, quarry.__name__)
                self.assertTrue(function.__doc__ and function.__doc__.strip())
        for name in PRIVATE_NAMES:
            with self.subTest(private=name):
                self.assertFalse(hasattr(quarry, name))

    def test_the_platform_module_publishes_its_names(self) -> None:
        """``design.platform`` exporta lo que usarán las tareas siguientes, cada nombre con su
        documentación."""
        names = ("Footprint", "PlatformGeometry", "PlatformJob", "axis_of_polygon",
                 "platform_footprint", "work_window",
                 # T44: la huella por unidades (test_long_axes.py).
                 "platform_footprint_units",
                 # T07: aplicar la plataforma (test_platform_apply.py).
                 "Applied", "OffLevel", "OffLevelCause", "apply_platform", "apply_platform_steps",
                 # T08: el borde (test_platform_edge.py).
                 "Edge", "EdgeWall", "WallCause", "magnitude_notices", "platform_edge",
                 "platform_edge_steps",
                 # T09: la contrapendiente, las cifras y los avisos (test_platform_profile.py).
                 "HeldGroup", "LongProfile", "OrderBreach", "PlatformOutcome", "QuarryOrder",
                 "order_check", "platform_outcome", "platform_profile",
                 # T12: el resumen de «Calcular» (test_platform_operation.py).
                 "summary_notices",
                 # T37: leer solo la ventana de la plataforma (test_platform_window.py).
                 "NeedsWholeSurface", "reading_window", "window_part")
        self.assertEqual(sorted(platform.__all__), sorted(names))
        for name in names:
            with self.subTest(name=name):
                self.assertTrue(getattr(platform, name).__doc__.strip())


class JobTest(unittest.TestCase):
    """Lo leído por el cálculo: errores del programa si no casa con la rejilla."""

    def test_arrays_must_have_the_shape_of_the_grid(self) -> None:
        """La superficie de partida y las dos máscaras son de la forma de la rejilla (``ValueError``)."""
        good = np.zeros(GRID.shape, dtype=bool)
        small = np.zeros((3, 3), dtype=bool)
        for start, cut, fill in ((np.zeros((3, 3)), good, good), (efx.plane_terrain(), small, good),
                                 (efx.plane_terrain(), good, small)):
            with self.assertRaises(ValueError):
                platform.PlatformJob(line_request(), "PLT-001", GRID, start, axis_geometry(
                    "Plataforma de carga"), values(), cut, fill)

    def test_the_code_and_the_values_must_be_those_of_a_platform(self) -> None:
        """Un código que no es de una entidad o un valor que no es de una plataforma son errores
        del programa."""
        for code, parameters in (("P1", values()), ("PLT-001", {"width": 20.0})):
            with self.subTest(code=code, parameters=parameters):
                with self.assertRaises(ValueError):
                    make_job_with_code(code, parameters)

    def test_a_geometry_is_a_point_a_line_or_a_polygon(self) -> None:
        """Un tipo que no es de una capa de entidades y un eje enlazado en una línea (que no lo
        lleva) son errores del programa."""
        parts = AXES_DATA.entities[0]
        with self.assertRaises(ValueError):
            platform.PlatformGeometry("circle", parts)
        with self.assertRaises(ValueError):
            platform.PlatformGeometry("line", parts, axis_parts=parts)


def make_job_with_code(code: str, parameters: Mapping[str, object]) -> Any:
    allowed = np.ones(GRID.shape, dtype=bool)
    return platform.PlatformJob(line_request(), code, GRID, efx.plane_terrain(),
                                axis_geometry("Plataforma de carga"), parameters, allowed,
                                allowed.copy())


# --- Eje y ancho -------------------------------------------------------------------------------


class StraightAxisTest(unittest.TestCase):
    """RF-015-19, CE-015-03 (error 20): un eje recto de 200 m y 20 m de ancho."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.job = axis_job("Plataforma de carga")
        cls.found = platform.platform_footprint(cls.job)
        cls.box = qfx.in_box((110.0, 270.0, 310.0, 290.0))

    def test_the_footprint_measures_the_axis_and_not_a_buffer(self) -> None:
        """CE-015-03: el eje mide 200 m; la huella, 200 columnas de 20 filas = 4.000 celdas
        (4.000 m², no los 4.400 m² de un *buffer* de extremos redondos) y su longitud medida, la
        de los centros: de 0,5 a 199,5 m = 199 m, dentro de ``L − 2 celdas < medida ≤ L + 1
        celda`` (198 a 201 m), no 220 m."""
        self.assertEqual(self.found.axis.length_m, 200.0)
        self.assertEqual(self.found.cell_count, 4000)
        self.assertEqual(self.found.area_m2, 4000.0)
        self.assertEqual(self.found.length_m, 199.0)
        self.assertTrue(198.0 < self.found.length_m <= 201.0)
        self.assertNotAlmostEqual(self.found.length_m, 220.0, delta=10.0)
        self.assertEqual(self.found.cell_area_m2, 1.0)

    def test_the_cells_are_those_of_the_corridor_box(self) -> None:
        """A mano: los centros con x de 110 a 310 e y de 270 a 290 (en la rejilla entera)."""
        np.testing.assert_array_equal(on_grid(self.found, self.found.cells, False), self.box)

    def test_the_grade_is_the_level_of_its_abscissa_cell_by_cell(self) -> None:
        """RF-015-19: la abscisa de cada celda es ``x − 110`` (el punto más próximo del eje) y la
        rasante, ``250 + σ · 1 / 100``, a ≤ 10⁻⁹ m: 250,005 m en la primera columna y 251,995 m en
        la última."""
        grid = on_grid(self.found, self.found.levels)
        sigma = on_grid(self.found, self.found.sigma)
        np.testing.assert_allclose(sigma[self.box], (X - 110.0)[self.box], rtol=0, atol=TOL)
        np.testing.assert_allclose(grid[self.box], (250.0 + (X - 110.0) * 0.01)[self.box],
                                   rtol=0, atol=TOL)
        self.assertTrue(np.isnan(grid[~self.box]).all())
        self.assertAlmostEqual(float(grid[self.box & (X == 110.5)].min()), 250.005, delta=TOL)
        self.assertAlmostEqual(float(grid[self.box & (X == 309.5)].max()), 251.995, delta=TOL)
        self.assertEqual((self.found.start_level_m, self.found.gradient_pct), (250.0, 1.0))
        self.assertAlmostEqual(self.found.end_level_m, 252.0, delta=TOL)

    def test_the_footprint_is_the_one_of_the_corridor_of_the_014(self) -> None:
        """Con eje y ancho la huella y la rasante son **las del corredor** de RF-014-09, bit a bit
        (``quarry.corridor_cells`` con los mismos campos)."""
        corridor = quarry.corridor_cells(
            corridor_layer(efx.AXES[0].path, 20.0, 250.0, 1.0),
            model.CorridorFields(efx.AXES_LAYER, "ancho", start_level_field="cota_inicial",
                                 gradient_field="pendiente"), GRID)
        np.testing.assert_array_equal(on_grid(self.found, self.found.levels), corridor.floors.grid)

    def test_the_axis_and_its_sense(self) -> None:
        """El eje usado es el de la capa, en su sentido (abscisa 0 en el primer vértice), con
        coordenadas absolutas float64 y sin ser el principal; sin avisos."""
        self.assertEqual(self.found.axis.vertices, ((cfx.BASE[0] + 110.0, cfx.BASE[1] + 280.0),
                                                    (cfx.BASE[0] + 310.0, cfx.BASE[1] + 280.0)))
        self.assertFalse(self.found.axis.principal)
        self.assertEqual(self.found.notices, ())
        for x, y in self.found.axis.vertices:
            self.assertIs(type(x), float)
            self.assertIs(type(y), float)

    def test_the_work_window_is_the_footprint_plus_the_reach_and_two_cells(self) -> None:
        """A0: la huella ocupa las filas 110 a 129 y las columnas 110 a 309; con un alcance de
        30 m se amplía 32 celdas por cada lado: filas 78 a 161 y columnas 78 a 341. Todas las
        rejillas de la huella son de la ventana."""
        window = self.found.window
        self.assertEqual(((window[0].start, window[0].stop), (window[1].start, window[1].stop)),
                         ((78, 162), (78, 342)))
        for array in (self.found.cells, self.found.sigma, self.found.levels):
            self.assertEqual(array.shape, (84, 264))
        self.assertEqual(self.found.cells.dtype, np.bool_)
        self.assertEqual(self.found.levels.dtype, np.float64)

    def test_the_window_is_clipped_to_the_grid(self) -> None:
        """Con un alcance de 5.000 m la ventana es la rejilla entera, y no pasa de ella."""
        found = platform.platform_footprint(axis_job("Plataforma de carga", reach_m=5000.0))
        self.assertEqual(found.window, (slice(0, 400), slice(0, 400)))
        np.testing.assert_array_equal(found.cells, self.box)

    def test_work_window_by_hand(self) -> None:
        """``work_window`` da la caja de la huella ampliada en ``⌈alcance / paso⌉ + 2`` celdas, con
        el paso de cada eje (un alcance de 2,5 m con celdas de 1 m son 3 + 2 celdas)."""
        window = platform.work_window(slice(100, 120), slice(50, 80), 2.5, GRID)
        self.assertEqual(window, (slice(95, 125), slice(45, 85)))
        edge = platform.work_window(slice(0, 10), slice(395, 400), 2.5, GRID)
        self.assertEqual(edge, (slice(0, 15), slice(390, 400)))
        coarse = qfx.grid_of(qfx.COARSE_STEP_M)
        self.assertEqual(platform.work_window(slice(50, 60), slice(50, 60), 5.0, coarse),
                         (slice(45, 65), slice(45, 65)))

    def test_nothing_that_was_read_is_modified(self) -> None:
        """La entrada no se modifica (principio 7): los vértices, la superficie y las máscaras
        quedan bit a bit como estaban."""
        job = axis_job("Plataforma de taller")
        parts = [np.array(path, copy=True) for part in job.geometry.parts for path in part]
        start, cut, fill = job.start.copy(), job.cut_allowed.copy(), job.fill_allowed.copy()
        platform.platform_footprint(job)
        for before, path in zip(parts, [p for part in job.geometry.parts for p in part],
                                strict=True):
            np.testing.assert_array_equal(before, path)
        np.testing.assert_array_equal(start, job.start)
        np.testing.assert_array_equal(cut, job.cut_allowed)
        np.testing.assert_array_equal(fill, job.fill_allowed)


class SeveralStretchesTest(unittest.TestCase):
    """RF-015-19: un eje de varios tramos (el L de la «Plataforma de taller»: de (125, 90) a (245,
    90) y a (245, 130), 30 m de ancho, 200 m al 2 %) y el empate entre dos tramos."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.found = platform.platform_footprint(axis_job("Plataforma de taller"))
        cls.sigma = on_grid(cls.found, cls.found.sigma)
        cls.levels = on_grid(cls.found, cls.found.levels)

    def at(self, array: np.ndarray, x: float, y: float) -> float:
        return float(array[(X == x) & (Y == y)][0])

    def test_the_cell_count_by_hand(self) -> None:
        """A mano: 3.600 celdas en la banda del primer tramo (120 columnas × 30 filas), 1.200 en la
        del segundo (30 × 40), 225 en las dos (15 × 15) y 179 en la unión redonda de fuera del
        vértice (el cuarto de círculo de 15 m contado por filas): 4.754."""
        self.assertEqual(self.found.cell_count, 3600 + 1200 - 225 + 179)
        self.assertEqual(self.found.cell_count, 4754)

    def test_the_abscissa_cell_by_cell(self) -> None:
        """A mano: ``x − 125`` en el primer tramo; ``120 + (y − 90)`` en el segundo; en la unión
        redonda de fuera, el vértice (120 m); en el solape, la del tramo más próximo y, a igual
        distancia, la menor."""
        for (x, y), expected in (
                ((125.5, 90.5), 0.5),      # la primera columna
                ((125.5, 75.5), 0.5),      # el borde sur de la banda
                ((200.5, 100.5), 75.5),    # el primer tramo
                ((232.5, 100.5), 107.5),   # solape: a 10,5 m del primero y a 12,5 m del segundo
                ((236.5, 100.5), 130.5),   # solape: a 8,5 m del segundo y a 10,5 m del primero
                ((250.5, 100.5), 130.5),   # el segundo tramo
                ((250.5, 85.5), 120.0),    # la unión redonda de fuera: el vértice
                ((245.5, 129.5), 159.5),   # la última fila
                ((259.5, 129.5), 159.5)):  # el borde este de la banda
            with self.subTest(cell=(x, y)):
                self.assertAlmostEqual(self.at(self.sigma, x, y), expected, delta=TOL)
                self.assertAlmostEqual(self.at(self.levels, x, y), 200.0 + expected * 0.02,
                                       delta=TOL)

    def test_a_tie_between_two_stretches_takes_the_lower_abscissa(self) -> None:
        """RF-015-19: en la diagonal del lado de dentro del codo, a igual distancia de los dos
        tramos, la rasante es la de la menor abscisa: (240,5; 94,5) está a 4,5 m de los dos (σ =
        115,5 en el primero, 124,5 en el segundo) y (244,5; 90,5) a 0,5 m de los dos (119,5 y
        120,5)."""
        self.assertAlmostEqual(self.at(self.sigma, 240.5, 94.5), 115.5, delta=TOL)
        self.assertAlmostEqual(self.at(self.levels, 240.5, 94.5), 200.0 + 115.5 * 0.02, delta=TOL)
        self.assertAlmostEqual(self.at(self.sigma, 244.5, 90.5), 119.5, delta=TOL)

    def test_the_ends_are_flat(self) -> None:
        """Fuera de los extremos planos y de las bandas no hay huella: antes del principio, tras el
        final y a más de medio ancho."""
        for x, y in ((124.5, 90.5), (245.5, 130.5), (261.5, 100.5), (200.5, 74.5)):
            with self.subTest(cell=(x, y)):
                self.assertTrue(math.isnan(self.at(self.levels, x, y)))

    def test_the_lengths(self) -> None:
        """El eje mide 160 m (120 + 40) y la huella, de 0,5 a 159,5 m de abscisa sin recortar:
        159 m (la suma de los tramos de los centros), dentro de 158 < medida ≤ 161."""
        self.assertEqual(self.found.axis.length_m, 160.0)
        self.assertEqual(self.found.length_m, 159.0)
        self.assertAlmostEqual(self.found.end_level_m, 203.2, delta=TOL)

    def test_a_polyline_that_comes_back_ties_on_the_first_stretch(self) -> None:
        """Un eje que vuelve sobre sí mismo (este, norte y oeste; 12 m de ancho): una celda a igual
        distancia de la ida (y = 200) y de la vuelta (y = 211) toma la ida: en la fila y = 205,5, σ
        = x − 100 y la rasante ``250 + σ / 100``; junto a la vuelta, la de la vuelta (311 − x)."""
        path = ((100.0, 200.0), (200.0, 200.0), (200.0, 211.0), (100.0, 211.0))
        job = make_job(line_path(path), line_request(), values(width_m=12.0, reach_m=10.0))
        found = platform.platform_footprint(job)
        level_grid = on_grid(found, found.levels)
        along = (X > 101.0) & (X < 190.0)
        for y, expected in ((205.5, X - 100.0), (201.5, X - 100.0), (209.5, 311.0 - X)):
            with self.subTest(row=y):
                row = (Y == y) & along
                self.assertEqual(int(row.sum()), 89)
                np.testing.assert_allclose(level_grid[row], (250.0 + expected * 0.01)[row], rtol=0,
                                           atol=TOL)


class AbsoluteCoordinatesTest(unittest.TestCase):
    """Principio 6: nortes de 4,4 Mm sin perder precisión (un float32 los redondea a 0,5 m)."""

    def test_the_grade_at_4_4_million_metres_north(self) -> None:
        """Una plataforma de eje de 200 m en (500.100, 4.400.200,456): sus vértices salen tal cual
        (float de Python) y la rasante de cada celda es la de la abscisa a mano a ≤ 10⁻⁹ m."""
        grid = gis.Grid(500_000.0, 4_400_400.456, 1.0, 1.0, 400, 400)
        path = np.array([[500_100.0, 4_400_200.456], [500_300.0, 4_400_200.456]])
        geometry = platform.PlatformGeometry("line", ((path,),))
        flat = np.full(grid.shape, 200.0)
        found = platform.platform_footprint(make_job(geometry, line_request(), values(),
                                                     start=flat, grid=grid))
        self.assertEqual(found.axis.vertices, ((500_100.0, 4_400_200.456),
                                               (500_300.0, 4_400_200.456)))
        self.assertEqual(found.cell_count, 4000)
        inside = found.cells
        x_centers = 500_000.0 + (np.arange(400) + 0.5)
        columns = np.tile(x_centers[found.window[1]], (found.cells.shape[0], 1))
        np.testing.assert_allclose(found.sigma[inside], (columns - 500_100.0)[inside], rtol=0,
                                   atol=TOL)
        np.testing.assert_allclose(found.levels[inside],
                                   (250.0 + (columns - 500_100.0) * 0.01)[inside], rtol=0, atol=TOL)


# --- Polígono ----------------------------------------------------------------------------------


class PolygonAxisTest(unittest.TestCase):
    """RF-015-19: un polígono con su eje enlazado: la parte de la línea que está dentro."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.found = platform.platform_footprint(polygon_job("Explanada con eje", reach_m=20.0))
        cls.box = qfx.in_box((120.0, 210.0, 200.0, 260.0))

    def test_the_cells_are_those_whose_centre_is_inside(self) -> None:
        """D-16: las celdas del rectángulo de 80 × 50 m (x de 120 a 200, y de 210 a 260): 4.000."""
        self.assertEqual(self.found.cell_count, 4000)
        np.testing.assert_array_equal(on_grid(self.found, self.found.cells, False), self.box)

    def test_the_axis_is_the_part_of_the_line_inside(self) -> None:
        """El eje enlazado va de (110, 235) a (210, 235) y cruza el polígono de lado a lado: se
        usa su parte de dentro, de (120, 235) a (200, 235), 80 m, en el sentido de la línea."""
        vertices = [local(vertex) for vertex in self.found.axis.vertices]
        self.assertEqual(len(vertices), 2)
        for found, expected in zip(vertices, ((120.0, 235.0), (200.0, 235.0)), strict=True):
            self.assertAlmostEqual(found[0], expected[0], delta=TOL)
            self.assertAlmostEqual(found[1], expected[1], delta=TOL)
        self.assertAlmostEqual(self.found.axis.length_m, 80.0, delta=TOL)
        self.assertFalse(self.found.axis.principal)
        self.assertEqual(self.found.notices, ())

    def test_the_grade_is_that_of_the_nearest_point_of_the_axis(self) -> None:
        """A mano: σ = x − 120 (de 0,5 a 79,5 m) y la rasante, ``235 + σ · 1,5 / 100``; la longitud
        medida, 79 m; la ventana, las filas 118 a 211 y las columnas 98 a 221 (alcance de 20 m)."""
        level_grid = on_grid(self.found, self.found.levels)
        np.testing.assert_allclose(level_grid[self.box], (235.0 + (X - 120.0) * 0.015)[self.box],
                                   rtol=0, atol=TOL)
        self.assertTrue(np.isnan(level_grid[~self.box]).all())
        self.assertAlmostEqual(self.found.length_m, 79.0, delta=TOL)
        self.assertEqual(((self.found.window[0].start, self.found.window[0].stop),
                          (self.found.window[1].start, self.found.window[1].stop)),
                         ((118, 212), (98, 222)))

    def test_a_bent_axis_is_cut_where_it_enters_and_leaves(self) -> None:
        """Un eje con un vértice dentro: de (110, 235) a (160, 235) y a (160, 200) entra por el lado
        oeste en (120, 235) y sale por el sur en (160, 210): su parte de dentro, de tres vértices y
        65 m; σ es la del punto más próximo (fijada en el extremo: (190,5; 235,5) está a 30,5 m
        del final del primer tramo y de la cabeza del segundo, que son el mismo vértice: 40 m; y
        (150,5; 215,5), a 9,5 m del segundo tramo: 40 + 19,5 = 59,5 m)."""
        axis = platform.PlatformGeometry(
            "polygon", polygon_geometry("Explanada con eje").parts,
            axis_parts=((cfx.absolute(((110.0, 235.0), (160.0, 235.0), (160.0, 200.0))),),),
            axis_name="Eje quebrado")
        found = platform.platform_footprint(make_job(
            axis, polygon_request("Explanada con eje", linked=True),
            values(start_level_m=235.0, gradient_pct=1.5)))
        vertices = [local(v) for v in found.axis.vertices]
        self.assertEqual(len(vertices), 3)
        for got, expected in zip(vertices, ((120.0, 235.0), (160.0, 235.0), (160.0, 210.0)),
                                 strict=True):
            self.assertAlmostEqual(got[0], expected[0], delta=TOL)
            self.assertAlmostEqual(got[1], expected[1], delta=TOL)
        self.assertAlmostEqual(found.axis.length_m, 65.0, delta=TOL)
        level_grid = on_grid(found, found.levels)
        for (x, y), sigma in (((190.5, 235.5), 40.0), (((150.5, 215.5)), 59.5)):
            with self.subTest(cell=(x, y)):
                self.assertAlmostEqual(float(level_grid[(X == x) & (Y == y)][0]), 235.0 + sigma * 0.015,
                                       delta=TOL)


class PrincipalAxisTest(unittest.TestCase):
    """RF-015-19: sin eje enlazado, el eje principal de las celdas, con su aviso."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.found = platform.platform_footprint(polygon_job("Explanada sin eje"))
        cls.box = qfx.in_box((310.0, 180.0, 350.0, 260.0))

    def test_the_principal_axis_runs_along_the_long_side_from_the_south(self) -> None:
        """A mano: el polígono es de 40 × 80 m (x de 310 a 350, y de 180 a 260): su eje principal
        es el norte-sur por x = 330, de y = 180 a y = 260 (los centros extremos, ampliados media
        celda en cada extremo); los dos extremos tienen la misma abscisa x y la abscisa 0 es la del
        sur."""
        self.assertTrue(self.found.axis.principal)
        vertices = [local(vertex) for vertex in self.found.axis.vertices]
        for got, expected in zip(vertices, ((330.0, 180.0), (330.0, 260.0)), strict=True):
            self.assertAlmostEqual(got[0], expected[0], delta=TOL)
            self.assertAlmostEqual(got[1], expected[1], delta=TOL)
        self.assertAlmostEqual(self.found.axis.length_m, 80.0, delta=TOL)

    def test_the_warning_names_the_polygon_and_the_sense(self) -> None:
        """El aviso ``des.platform_axis_principal`` lleva la plataforma, el punto de la abscisa 0
        y el del otro extremo (absolutos) y se lee en español: «eje principal»."""
        self.assertEqual(len(self.found.notices), 1)
        notice = self.found.notices[0]
        self.assertEqual(notice.code, "des.platform_axis_principal")
        self.assertEqual(notice.severity, "warning")
        self.assertEqual(notice.values["entity"], "Explanada sin eje")
        for key, expected in (("x", 330.0 + cfx.BASE[0]), ("y", 180.0 + cfx.BASE[1]),
                              ("x_end", 330.0 + cfx.BASE[0]), ("y_end", 260.0 + cfx.BASE[1])):
            self.assertAlmostEqual(float(notice.values[key]), expected, delta=TOL)
        self.assertIn("eje principal", notice.text("es"))
        self.assertIn("principal axis", notice.text("en"))

    def test_the_grade_follows_the_principal_axis(self) -> None:
        """3.200 celdas (40 × 80); σ = y − 180 y la rasante ``240 + σ · 0,5 / 100``; la longitud
        medida, 79 m."""
        self.assertEqual(self.found.cell_count, 3200)
        level_grid = on_grid(self.found, self.found.levels)
        np.testing.assert_allclose(level_grid[self.box], (240.0 + (Y - 180.0) * 0.005)[self.box],
                                   rtol=0, atol=TOL)
        self.assertAlmostEqual(self.found.length_m, 79.0, delta=TOL)


class AxisOfPolygonTest(unittest.TestCase):
    """``axis_of_polygon(cells, grid)``: la dirección propia mayor, el extremo más al oeste (a igual
    abscisa, al sur) como abscisa 0."""

    @staticmethod
    def axis(cells: np.ndarray, **kwargs: Any) -> list[tuple[float, float]]:
        found = platform.axis_of_polygon(cells, GRID, **kwargs)
        return [local(vertex) for vertex in found.vertices]

    def test_an_east_west_rectangle_starts_at_the_west(self) -> None:
        """20 × 6 celdas (x de 100 a 120, y de 150 a 156): el eje va de (100, 153) a (120, 153)."""
        found = self.axis(qfx.in_box((100.0, 150.0, 120.0, 156.0)))
        self.assertEqual(len(found), 2)
        for got, expected in zip(found, ((100.0, 153.0), (120.0, 153.0)), strict=True):
            self.assertAlmostEqual(got[0], expected[0], delta=TOL)
            self.assertAlmostEqual(got[1], expected[1], delta=TOL)

    def test_a_north_south_rectangle_starts_at_the_south(self) -> None:
        """6 × 20 celdas: los dos extremos tienen la misma x y la abscisa 0 es la del sur."""
        found = self.axis(qfx.in_box((200.0, 150.0, 206.0, 170.0)))
        for got, expected in zip(found, ((203.0, 150.0), (203.0, 170.0)), strict=True):
            self.assertAlmostEqual(got[0], expected[0], delta=TOL)
            self.assertAlmostEqual(got[1], expected[1], delta=TOL)

    def test_a_diagonal_band_runs_from_the_west_end_towards_the_north_east(self) -> None:
        """Una banda de 7 celdas de ancho a lo largo de la diagonal (x de 150 a 250): su eje
        principal tiene la dirección de 45° (± 3°), mide unos 141 m (± 6 m) y la abscisa 0 es su
        extremo más al oeste."""
        cells = (np.abs((X - Y) - 50.0) < 3.6) & (X > 150.0) & (X < 250.0)
        found = self.axis(cells)
        (x0, y0), (x1, y1) = found
        self.assertLess(x0, x1)
        direction = np.array([x1 - x0, y1 - y0]) / math.hypot(x1 - x0, y1 - y0)
        self.assertGreater(float(direction @ np.array([1.0, 1.0]) / math.sqrt(2.0)),
                           math.cos(math.radians(3.0)))
        self.assertAlmostEqual(math.hypot(x1 - x0, y1 - y0), 141.0, delta=6.0)

    def test_one_cell_gives_an_axis_of_one_cell(self) -> None:
        """Una sola celda (centro en (200,5; 200,5)) da un eje este-oeste de una celda, de (200, 200,5)
        a (201, 200,5)."""
        found = self.axis((X == 200.5) & (Y == 200.5))
        for got, expected in zip(found, ((200.0, 200.5), (201.0, 200.5)), strict=True):
            self.assertAlmostEqual(got[0], expected[0], delta=TOL)
            self.assertAlmostEqual(got[1], expected[1], delta=TOL)

    def test_a_square_has_no_main_direction_and_takes_the_east_west(self) -> None:
        """Con la misma varianza en las dos direcciones (un cuadrado) se toma la este-oeste."""
        found = self.axis(qfx.in_box((100.0, 100.0, 110.0, 110.0)))
        self.assertAlmostEqual(found[0][1], found[1][1], delta=TOL)
        self.assertLess(found[0][0], found[1][0])

    def test_a_window_with_its_offset_gives_the_same_axis(self) -> None:
        """Una ventana de la rejilla con su ``offset`` (fila, columna) da el mismo eje que la
        rejilla entera, y no se modifica."""
        cells = qfx.in_box((100.0, 150.0, 120.0, 156.0))
        rows, cols = np.nonzero(cells)
        window = cells[rows.min():rows.max() + 1, cols.min():cols.max() + 1].copy()
        before = window.copy()
        self.assertEqual(self.axis(window, offset=(int(rows.min()), int(cols.min()))),
                         self.axis(cells))
        np.testing.assert_array_equal(window, before)

    def test_no_cells_is_a_program_error(self) -> None:
        """Sin ninguna celda no hay eje (``ValueError``; lo rechaza antes ``platform_footprint``)."""
        with self.assertRaises(ValueError):
            platform.axis_of_polygon(np.zeros(GRID.shape, dtype=bool), GRID)


# --- Los rechazos ------------------------------------------------------------------------------


class RejectionTest(unittest.TestCase):
    """RF-015-08: cada rechazo nombra la capa, la entidad, el campo y el valor, y no calcula."""

    def reject(self, job: Any, code: str) -> Any:
        with self.assertRaises(DesignError) as caught:
            platform.platform_footprint(job)
        error = caught.exception
        self.assertEqual(error.code, code)
        self.assertNotIn("{", error.text)
        self.assertNotIn("?", error.text.replace("¿", ""))
        self.assertTrue(error.field)
        return error

    def named(self, error: Any, job: Any) -> None:
        """El texto nombra la capa y la entidad."""
        self.assertIn(f"«{job.request.layer}»", error.text)
        self.assertIn(f"«{job.request.name}»", error.text)

    def test_a_line_that_crosses_itself(self) -> None:
        """El eje en aspa de la capa (de (365, 300) a (395, 330), a (395, 300) y a (365, 330)): se
        corta en (380, 315); el error da el punto (absoluto) y el campo «geometría»."""
        job = axis_job("Eje que se corta")
        error = self.reject(job, "des.platform_self_intersects")
        self.named(error, job)
        self.assertAlmostEqual(float(error.values["x"]), 380.0 + cfx.BASE[0], delta=1e-6)
        self.assertAlmostEqual(float(error.values["y"]), 315.0 + cfx.BASE[1], delta=1e-6)
        self.assertEqual(error.field, "geometría")

    def test_a_line_that_ends_on_itself_or_folds_back(self) -> None:
        """Un eje que acaba tocando su propio tramo (un 6) y uno que vuelve sobre sí mismo por el
        mismo camino también se cortan."""
        six = ((100.0, 100.0), (140.0, 100.0), (140.0, 140.0), (120.0, 140.0), (120.0, 100.0))
        for name, path in (("seis", six), ("doblez", ((100.0, 100.0), (140.0, 100.0),
                                                       (120.0, 100.0), (120.0, 140.0)))):
            with self.subTest(path=name):
                job = make_job(line_path(path), line_request(), values())
                self.reject(job, "des.platform_self_intersects")

    def test_a_closed_line(self) -> None:
        """El eje cuadrado de la capa acaba donde empieza: ni sentido ni abscisa 0."""
        job = axis_job("Eje cerrado")
        self.named(self.reject(job, "des.platform_axis_closed"), job)

    def test_a_line_without_length(self) -> None:
        """Dos vértices iguales: la longitud (0 m) es el valor."""
        job = axis_job("Eje de longitud cero")
        error = self.reject(job, "des.platform_axis_length_zero")
        self.named(error, job)
        self.assertEqual(error.values["value"], 0.0)

    def test_a_line_of_several_parts(self) -> None:
        """Una geometría de dos líneas no es un eje (¿cuál es la abscisa 0?): ``des.platform_axis_parts``
        con el número de partes."""
        parts = ((cfx.absolute(((100.0, 100.0), (150.0, 100.0))),),
                 (cfx.absolute(((200.0, 100.0), (250.0, 100.0))),))
        job = make_job(platform.PlatformGeometry("line", parts), line_request(), values())
        error = self.reject(job, "des.platform_axis_parts")
        self.assertEqual(error.values["value"], 2)
        self.named(error, job)

    def test_a_layer_of_points(self) -> None:
        """Una capa de puntos no da plataformas: ``des.platform_layer_kind`` con «puntos»."""
        point = ((cfx.absolute(((200.0, 200.0),)),),)
        job = make_job(platform.PlatformGeometry("point", point), line_request(), values())
        error = self.reject(job, "des.platform_layer_kind")
        self.assertEqual(error.values["value"], "puntos")

    def test_a_polygon_that_crosses_itself(self) -> None:
        """El moño de la capa: su área con signo es 0 y también se corta; gana lo segundo."""
        job = polygon_job("Polígono que se corta", linked=False)
        self.named(self.reject(job, "des.platform_self_intersects"), job)

    def test_a_polygon_without_area(self) -> None:
        """Un anillo con todos los vértices alineados no tiene área: el valor es 0 m²."""
        job = polygon_job("Polígono sin área", linked=False)
        error = self.reject(job, "des.platform_area_zero")
        self.named(error, job)
        self.assertEqual(error.values["value"], 0.0)

    def test_a_polygon_without_cells(self) -> None:
        """Un polígono de 0,3 × 0,3 m que no contiene ningún centro de celda."""
        job = polygon_job("Polígono sin celdas", linked=False)
        self.named(self.reject(job, "des.platform_no_cells"), job)

    def test_a_line_outside_the_grid_has_no_cells(self) -> None:
        """Una línea fuera de la rejilla no tiene ninguna celda."""
        job = make_job(line_path(((1000.0, 200.0), (1100.0, 200.0))), line_request(), values())
        self.named(self.reject(job, "des.platform_no_cells"), job)

    def test_an_axis_that_does_not_cross_its_polygon(self) -> None:
        """El eje «Eje corto» entra en su polígono y acaba dentro: no lo cruza de lado a lado. El
        campo es el del enlace y el valor, el nombre del eje."""
        job = polygon_job("Explanada con eje que no la cruza")
        error = self.reject(job, "des.platform_axis_not_crossing")
        self.named(error, job)
        self.assertEqual(error.field, efx.LINK_FIELD)
        self.assertEqual(error.values["value"], "Eje corto")

    def test_other_axes_that_do_not_cross(self) -> None:
        """No cruzan de lado a lado: el que empieza dentro y acaba fuera, el que pasa de largo, el
        que cruza dos veces (dos tramos dentro: ninguno es «el» eje) y el que roza el polígono sin
        entrar."""
        box = polygon_geometry("Explanada con eje").parts
        u_shape = ((cfx.absolute(((100.0, 100.0), (200.0, 100.0), (200.0, 200.0), (180.0, 200.0),
                                  (180.0, 120.0), (120.0, 120.0), (120.0, 200.0), (100.0, 200.0),
                                  (100.0, 100.0))),),)
        cases = (
            ("empieza dentro", box, ((150.0, 235.0), (230.0, 235.0))),
            ("pasa de largo", box, ((100.0, 300.0), (250.0, 300.0))),
            ("sin llegar", box, ((100.0, 235.0), (110.0, 235.0))),
            ("dos veces", u_shape, ((90.0, 180.0), (210.0, 180.0))),
        )
        for name, parts, path in cases:
            with self.subTest(case=name):
                geometry = platform.PlatformGeometry("polygon", parts, axis_parts=(
                    (cfx.absolute(path),),), axis_name="Eje de prueba")
                job = make_job(geometry, polygon_request("Explanada con eje", linked=True),
                               values(start_level_m=235.0, gradient_pct=1.5))
                self.reject(job, "des.platform_axis_not_crossing")

    def test_a_linked_axis_of_several_parts(self) -> None:
        """Un eje enlazado de dos partes tampoco es un eje: ``des.platform_axis_parts``."""
        axis = ((cfx.absolute(((110.0, 235.0), (130.0, 235.0))),),
                (cfx.absolute(((150.0, 235.0), (210.0, 235.0))),))
        geometry = platform.PlatformGeometry("polygon", polygon_geometry("Explanada con eje").parts,
                                             axis_parts=axis, axis_name="Eje partido")
        job = make_job(geometry, polygon_request("Explanada con eje", linked=True),
                       values(start_level_m=235.0, gradient_pct=1.5))
        self.assertEqual(self.reject(job, "des.platform_axis_parts").values["value"], 2)

    def test_a_missing_width(self) -> None:
        """El eje sin ancho de la capa: el valor falta y no se elige uno
        (``des.entity_param_missing``, con la clave de su campo)."""
        spec = efx.AXES[efx.axis_fid("Eje sin ancho") - 1]
        job = make_job(axis_geometry("Eje sin ancho"), line_request("Eje sin ancho"),
                       {"width_m": None, "start_level_m": spec.start_m,
                        "gradient_pct": spec.gradient_pct, "reach_m": 30.0})
        error = self.reject(job, "des.entity_param_missing")
        self.assertEqual(error.field, "des.platform.plt_001.width_m")
        self.assertIn("«Eje sin ancho»", error.text)
        self.assertIn(f"«{efx.AXES_LAYER}»", error.text)  # RF-015-08: también la capa

    def test_a_polygon_does_not_need_a_width(self) -> None:
        """Un polígono no tiene ancho: sin el valor se calcula igual."""
        job = make_job(polygon_geometry("Explanada con eje"),
                       polygon_request("Explanada con eje", linked=True),
                       {"start_level_m": 235.0, "gradient_pct": 1.5, "reach_m": 30.0})
        self.assertEqual(platform.platform_footprint(job).cell_count, 4000)

    def test_a_value_out_of_range_or_missing(self) -> None:
        """Un ancho negativo, una pendiente que no es un número y un alcance que falta se rechazan
        antes de tocar la geometría, con la clave del campo y el valor."""
        for changes, code, field in (
                ({"width_m": -5.0}, "des.entity_param_range", "width_m"),
                ({"width_m": 0.0}, "des.entity_param_range", "width_m"),
                ({"gradient_pct": math.nan}, "des.entity_param_range", "gradient_pct"),
                ({"start_level_m": None}, "des.entity_param_missing", "start_level_m"),
                ({"reach_m": None}, "des.entity_param_missing", "reach_m"),
                ({"reach_m": 0.0}, "des.entity_param_range", "reach_m")):
            with self.subTest(changes=changes):
                job = make_job(axis_geometry("Plataforma de carga"), line_request(),
                               values(**changes))
                error = self.reject(job, code)
                self.assertEqual(error.field, f"des.platform.plt_001.{field}")
                self.assertEqual(error.values["layer"], efx.AXES_LAYER)

    def test_a_level_outside_the_terrain_plus_or_minus_1000_m(self) -> None:
        """RF-015-08: el terreno va de 180,15625 a 304,84375 m, así que una cota válida está entre
        -819,84375 y 1.304,84375 m: una cota inicial de 2.000 m se rechaza con el campo de la capa y,
        con una pendiente de 1.000 % en 200 m, la final (2.250 m) con «cota_inicial + pendiente»."""
        job = make_job(axis_geometry("Plataforma de carga"), line_request(),
                       values(start_level_m=2000.0))
        error = self.reject(job, "des.platform_level_range")
        self.assertEqual((error.field, error.values["value"]), ("cota_inicial", 2000.0))
        self.assertEqual((error.values["low"], error.values["high"]), (-819.84375, 1304.84375))
        self.named(error, job)
        steep = make_job(axis_geometry("Plataforma de carga"), line_request(),
                         values(gradient_pct=1000.0))
        error = self.reject(steep, "des.platform_level_range")
        self.assertEqual((error.field, error.values["value"]),
                         ("cota_inicial + pendiente", 2250.0))
        edge = make_job(axis_geometry("Plataforma de carga"), line_request(),
                        values(start_level_m=1304.84375, gradient_pct=0.0))
        self.assertEqual(platform.platform_footprint(edge).cell_count, 4000)

    def test_errors_read_in_both_languages(self) -> None:
        """El texto del error sale también en inglés con sus valores (``text_in``)."""
        error = self.reject(axis_job("Eje cerrado"), "des.platform_axis_closed")
        self.assertIn("is closed", error.text_in("en"))
        self.assertIn("«Eje cerrado»", error.text_in("en"))


if __name__ == "__main__":
    unittest.main()

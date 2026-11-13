# SPDX-License-Identifier: GPL-3.0-or-later
"""Los corredores de la cantera (spec 014, T09; HU-014-2; RF-014-09, RF-014-10; plan 014 A6,
§5.3.1; CE-014-03).

- ``design.quarry.corridor_cells``: cada corredor de una capa de líneas (eje, ancho en m y una cota
  fija o una rasante: cota inicial en m y pendiente en %) convertido en un fondo con **extremos
  planos**, perpendiculares al eje: dentro, las celdas a ≤ ancho/2 de algún tramo cuya proyección
  no cae antes del principio ni después del final del eje; su longitud medida (máximo menos mínimo
  de la abscisa ``σ`` de sus celdas) es la del eje con error ≤ 1 celda (error 20: 200 m, no 220 m).
- La cota de cada celda: la fija, o ``cota inicial + σ · pendiente / 100`` a ≤ 10⁻⁹ m.
- Un eje quebrado (el corredor en L de la cantera sintética): la abscisa sigue el eje y la
  longitud medida, la del eje.
- Extremos planos también con un tramo extremo corto (T41, hallazgo F-2 de la T38): «dentro» por
  el punto más próximo de **todo** el eje, fuera si es un extremo y la proyección pasa de él; el
  eje de CE-014-03 digitalizado 198 + 2 m o 2 + 198 m da el rectángulo de 200 × 20 m (antes,
  4.118 celdas), y 30 ejes al azar con un tramo extremo más corto que medio ancho, celda a celda
  el rectángulo de extremos planos (punto en polígono). La longitud medida es la extensión de la
  huella a lo largo del eje (la abscisa sin recortar de sus celdas): en 60 ejes quebrados al azar
  no pasa de la del eje más una celda (A6) ni baja de ella en dos celdas o más (los centros).
- ``design.quarry.corridor_too_long``: el aviso de RF-014-10 con las dos longitudes en m.
- Los rechazos: ancho ≤ 0 (``des.corridor_width``), eje de longitud cero
  (``des.corridor_length_zero``), sin cota (``des.corridor_level_missing``), capa que no es de
  líneas (``des.corridor_not_lines``), campo que falta (``des.quarry_layer_field``) y dos
  corredores que se solapan, como dos fondos (``des.floor_overlap``, RF-014-06).
- El corredor, como fondo (T42, hallazgo F-3 de la T38): con la superficie de partida, su cota
  —la fija, o la inicial y la final de su rasante— en el rango de los fondos, ``[mín(z) − 1.000,
  máx(z) + 1.000]`` m (RF-014-06, ``des.corridor_level`` —el rango de ``des.floor_level``, con
  «corredor N», T51— con la capa, el corredor, el campo y el valor: un corredor a 5.000 m o a
  10⁶ m ya no anula la corta en silencio); uno por encima del
  terreno se admite y cuenta en lo de los fondos sobre el terreno (RF-014-05,
  ``floors_above_terrain`` con los corredores, cada celda una vez).

Sobre la rejilla de la cantera sintética de ``tests.support.quarry_fixtures`` (T01), sin proyecto
(la capa se arma como la escribe ``write_feature_layer``).
"""

from __future__ import annotations

import math
import random
import unittest
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender

quarry = import_geoblender("design.quarry")
model = import_geoblender("design.model")
messages = import_geoblender("design.messages")
vector = import_geoblender("gis.vector")
gis = import_geoblender("gis")
i18n = import_geoblender("core.i18n")

TOLERANCE_M = 1e-9
FIXED = model.CorridorFields(qfx.CORRIDORS_LAYER, "ancho", level_field="cota")
GRADIENT = model.CorridorFields(qfx.CORRIDORS_LAYER, "ancho",
                                start_level_field="cota_inicial", gradient_field="pendiente")
STRAIGHT = ((100.0, 200.0), (300.0, 200.0))
"""Un eje recto de 200 m hacia el este (local), sobre bordes de celda."""


def corridor_layer(paths: tuple[tuple[tuple[float, float], ...], ...], **fields: tuple[Any, ...],
                   ) -> Any:
    """Una capa de líneas (``FeatureLayer``) con un eje local por entidad (fids 1…n), el campo
    ``nombre`` y los campos numéricos ``fields`` (campo → valor por entidad)."""
    parts = tuple(((cfx.absolute(path),),) for path in paths)
    columns = (vector.FieldColumn("nombre", "nombre", "TEXT"),
               *(vector.FieldColumn(name, name, "DOUBLE") for name in fields))
    values = {"nombre": tuple(f"Corredor {index}" for index in range(1, len(paths) + 1)),
              **fields}
    return vector.FeatureLayer("line", tuple(range(1, len(paths) + 1)), parts, columns, values)


def fixture_layer() -> Any:
    """La capa de corredores de la cantera (el eje en L de 200 m con su rasante)."""
    data = next(item for item in qfx.layers() if item.name == qfx.CORRIDORS_LAYER)
    paths = tuple(tuple(map(tuple, (part[0] - np.asarray(cfx.BASE)).tolist()))
                  for entity in data.entities for part in entity)
    return corridor_layer(paths, **data.fields)


class StraightCorridorTest(unittest.TestCase):
    """RF-014-09, CE-014-03: un corredor recto de 200 m de eje y 20 m de ancho."""

    def test_flat_ends_and_length(self) -> None:
        """Las celdas son exactamente las del rectángulo de 200 × 20 m (4.000, extremos planos:
        ni media circunferencia en cada punta) y mide 200 m ± 1 celda, no 220 m."""
        layer = corridor_layer((STRAIGHT,), ancho=(20.0,), cota=(150.0,))
        found = quarry.corridor_cells(layer, FIXED, qfx.GRID)
        inside = np.isfinite(found.floors.grid)
        np.testing.assert_array_equal(inside, qfx.in_box((100.0, 190.0, 300.0, 210.0)))
        self.assertEqual(found.floors.cells, (4000,))
        self.assertEqual(found.axes_m, (200.0,))
        self.assertEqual(found.widths_m, (20.0,))
        self.assertLessEqual(abs(found.lengths_m[0] - 200.0), qfx.GRID.dx)
        self.assertEqual(found.notices, ())
        np.testing.assert_array_equal(found.floors.grid[inside], 150.0)
        self.assertEqual(found.floors.levels, (150.0,))
        self.assertEqual((found.floors.layer, found.floors.field), (qfx.CORRIDORS_LAYER, "cota"))
        np.testing.assert_array_equal(found.floors.owner, inside.astype(np.int32))

    def test_gradient_level(self) -> None:
        """Con rasante, cada celda a ``cota inicial + σ · pendiente / 100`` a ≤ 10⁻⁹ m (σ, la
        distancia del centro al principio del eje, medida a lo largo de él)."""
        layer = corridor_layer((STRAIGHT,), ancho=(20.0,), cota_inicial=(125.0,),
                               pendiente=(-3.0,))
        found = quarry.corridor_cells(layer, GRADIENT, qfx.GRID)
        x, _ = qfx.local_centers()
        inside = np.isfinite(found.floors.grid)
        expected = 125.0 + (x[inside] - 100.0) * -3.0 / 100.0
        np.testing.assert_allclose(found.floors.grid[inside], expected, rtol=0, atol=TOLERANCE_M)
        self.assertEqual(found.floors.field, "cota_inicial")

    def test_input_not_modified(self) -> None:
        """La capa no se modifica."""
        layer = corridor_layer((STRAIGHT,), ancho=(20.0,), cota=(150.0,))
        before = layer.parts[0][0][0].copy()
        quarry.corridor_cells(layer, FIXED, qfx.GRID)
        np.testing.assert_array_equal(layer.parts[0][0][0], before)


class BrokenAxisTest(unittest.TestCase):
    """RF-014-09, A6: el corredor en L de la cantera (120 m al este y 80 m al sur, rasante de 8 %
    desde 125 m)."""

    def setUp(self) -> None:
        self.found = quarry.corridor_cells(fixture_layer(), GRADIENT, qfx.GRID)
        self.x, self.y = qfx.local_centers()

    def cell(self, x: float, y: float) -> float:
        """La cota del corredor en la celda del centro local ``(x, y)``."""
        hit = (self.x == x) & (self.y == y)
        return float(self.found.floors.grid[hit][0])

    def test_length_of_the_axis(self) -> None:
        """Mide 200 m ± 1 celda (CE-014-03 sobre la cantera) y no avisa."""
        self.assertEqual(self.found.axes_m, (qfx.CORRIDOR_LENGTH_M,))
        self.assertLessEqual(abs(self.found.lengths_m[0] - qfx.CORRIDOR_LENGTH_M), qfx.GRID.dx)
        self.assertEqual(self.found.notices, ())

    def test_cells(self) -> None:
        """Las celdas: los dos rectángulos (120 × 20 y 20 × 80 m, con 10 × 10 comunes) y, en la
        esquina exterior, el cuarto de círculo de 10 m de radio alrededor del vértice (contado a
        mano celda a celda); nada antes del principio ni después del final."""
        corner = sum(1 for i in range(10) for j in range(10)
                     if (i + 0.5) ** 2 + (j + 0.5) ** 2 <= 100.0)
        self.assertEqual(self.found.floors.cells, (2400 + 1600 - 100 + corner,))
        for x, y in ((199.5, 160.5), (320.5, 79.5), (329.5, 169.5)):
            self.assertTrue(np.isnan(self.cell(x, y)), (x, y))
        for x, y in ((200.5, 169.5), (329.5, 80.5), (320.5, 160.5)):
            self.assertFalse(np.isnan(self.cell(x, y)), (x, y))

    def test_gradient_follows_the_axis(self) -> None:
        """La abscisa sigue el eje: en el primer tramo, ``x − 200``; en el segundo, ``120 + (160 −
        y)``; en el cuarto de círculo de la esquina, la del vértice (120 m). Cotas a ≤ 10⁻⁹ m."""
        gradient = qfx.CORRIDOR_GRADIENT_PCT / 100.0
        start = qfx.CORRIDOR_START_M
        for (x, y), sigma in (((200.5, 160.5), 0.5), ((250.5, 151.5), 50.5),
                              ((325.5, 100.5), 179.5), ((310.5, 80.5), 199.5),
                              ((325.5, 165.5), 120.0)):
            self.assertAlmostEqual(self.cell(x, y), start + sigma * gradient, delta=TOLERANCE_M)


CORNER_CELLS = sum(1 for i in range(10) for j in range(10)
                   if (i + 0.5) ** 2 + (j + 0.5) ** 2 <= 100.0)
"""Las celdas de 1 m de un cuarto de círculo de 10 m de radio centrado en una esquina de celda
(79), contadas a mano celda a celda."""
WINDOW_M = 80.0
"""El lado de la ventana de los ejes al azar (m, desde ``cfx.BASE``)."""


def window_grid(step: float) -> Any:
    """La rejilla de ``WINDOW_M`` m de lado con celdas de ``step`` m y la esquina suroeste en
    ``cfx.BASE`` (el origen de las coordenadas locales de los ejes)."""
    cells = round(WINDOW_M / step)
    return gis.Grid(cfx.BASE[0], cfx.BASE[1] + WINDOW_M, step, step, cells, cells)


def window_centers(grid: Any) -> tuple[np.ndarray, np.ndarray]:
    """Los centros locales de las celdas de ``grid`` (una de :func:`window_grid`; fila 0 al
    norte)."""
    columns = (np.arange(grid.ncols) + 0.5) * grid.dx
    rows = WINDOW_M - (np.arange(grid.nrows) + 0.5) * grid.dy
    return np.meshgrid(columns, rows)


def point_in_polygon(x: np.ndarray, y: np.ndarray,
                     polygon: list[tuple[float, float]]) -> np.ndarray:
    """Los puntos ``(x, y)`` dentro del polígono ``polygon`` (sus vértices en orden), por el
    número de cruces de un rayo hacia el este con sus lados."""
    inside = np.zeros(x.shape, dtype=bool)
    for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1], strict=True):
        if y1 == y2:
            continue
        crosses = (y1 > y) != (y2 > y)
        at = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
        inside ^= crosses & (x < at)
    return inside


def straight_short_end(rng: random.Random) -> dict[str, Any]:
    """Un eje recto al azar con el primer tramo, el último o los dos más cortos que medio ancho
    (y, a veces, otro vértice en medio): sus vértices locales, su ancho, su rejilla (celdas de 1 o
    2 m), su principio, su dirección, su longitud y el rectángulo de extremos planos del corredor.
    Se descarta el que deja un centro de celda a menos de 10⁻⁶ m del borde del rectángulo."""
    while True:
        step = rng.choice((1.0, 2.0))
        width = rng.choice((6.0, 10.0, 16.0, 20.0))
        half = width / 2.0
        ends = rng.choice(("first", "last", "both"))
        first = rng.uniform(0.2, 0.9) * half if ends != "last" else 0.0
        last = rng.uniform(0.2, 0.9) * half if ends != "first" else 0.0
        main = rng.uniform(12.0, 30.0)
        cuts = [0.0, *((first,) if first else ()),
                *((first + rng.uniform(0.3, 0.7) * main,) if rng.random() < 0.5 else ()),
                first + main, *((first + main + last,) if last else ())]
        length = cuts[-1]
        heading = rng.uniform(0.0, 2.0 * math.pi)
        ux, uy = math.cos(heading), math.sin(heading)
        cx, cy = rng.uniform(35.0, 45.0), rng.uniform(35.0, 45.0)
        x0, y0 = cx - length / 2.0 * ux, cy - length / 2.0 * uy
        points = tuple((x0 + s * ux, y0 + s * uy) for s in cuts)
        grid = window_grid(step)
        x, y = window_centers(grid)
        along = (x - x0) * ux + (y - y0) * uy
        across = (y - y0) * ux - (x - x0) * uy
        near = (along > -1.0) & (along < length + 1.0) & (np.abs(across) < half + 1.0)
        margin = np.minimum(np.minimum(np.abs(along), np.abs(along - length)),
                            np.abs(np.abs(across) - half))[near]
        if margin.min() < 1e-6:
            continue
        nx, ny = -uy * half, ux * half
        xn, yn = x0 + length * ux, y0 + length * uy
        polygon = [(x0 - nx, y0 - ny), (xn - nx, yn - ny), (xn + nx, yn + ny), (x0 + nx, y0 + ny)]
        return {"points": points, "width": width, "grid": grid, "origin": (x0, y0),
                "direction": (ux, uy), "length": length, "polygon": polygon}


def broken_axis(rng: random.Random) -> tuple[list[tuple[float, float]], float, Any]:
    """Un eje quebrado al azar de 2 a 4 vértices (tramos de 1,2 anchos a 25 m, giros de hasta
    55°) dentro de la ventana, su ancho (4 a 10 m) y su rejilla (celdas de 1 o 2 m)."""
    while True:
        step = rng.choice((1.0, 2.0))
        width = rng.choice((4.0, 6.0, 8.0, 10.0))
        x, y = rng.uniform(15.0, 65.0), rng.uniform(15.0, 65.0)
        heading = rng.uniform(0.0, 2.0 * math.pi)
        points = [(x, y)]
        for _ in range(rng.randint(1, 3)):
            stretch = rng.uniform(1.2 * width, 25.0)
            x, y = x + stretch * math.cos(heading), y + stretch * math.sin(heading)
            points.append((x, y))
            heading += math.radians(rng.uniform(-55.0, 55.0))
        if all(8.0 < px < WINDOW_M - 8.0 and 8.0 < py < WINDOW_M - 8.0 for px, py in points):
            return points, width, window_grid(step)


class ShortEndStretchTest(unittest.TestCase):
    """RF-014-09, RF-014-10, CE-014-03 (T41, hallazgo F-2): extremos planos también cuando el
    primer o el último tramo del eje es más corto que medio ancho."""

    def test_ce03_axis_digitized_198_plus_2_and_2_plus_198_m(self) -> None:
        """El eje de CE-014-03 (200 m, 20 m de ancho) digitalizado 198 + 2 m y 2 + 198 m da las
        4.000 celdas del rectángulo de 200 × 20 m (antes, 4.118: centros hasta 307,5 m o desde
        92,5 m), la rasante del eje de un tramo a ≤ 10⁻⁹ m y la misma longitud medida, 199 m
        (de 0,5 a 199,5), sin aviso."""
        fields = {"ancho": (20.0,), "cota_inicial": (125.0,), "pendiente": (-3.0,)}
        single = quarry.corridor_cells(corridor_layer((STRAIGHT,), **fields), GRADIENT, qfx.GRID)
        box = qfx.in_box((100.0, 190.0, 300.0, 210.0))
        for axis in (((100.0, 200.0), (298.0, 200.0), (300.0, 200.0)),
                     ((100.0, 200.0), (102.0, 200.0), (300.0, 200.0))):
            with self.subTest(axis=axis):
                found = quarry.corridor_cells(corridor_layer((axis,), **fields), GRADIENT,
                                              qfx.GRID)
                inside = np.isfinite(found.floors.grid)
                np.testing.assert_array_equal(inside, box)
                self.assertEqual(found.floors.cells, (4000,))
                np.testing.assert_allclose(found.floors.grid[inside],
                                           single.floors.grid[inside], rtol=0,
                                           atol=TOLERANCE_M)
                self.assertEqual(found.lengths_m, (199.0,))
                self.assertEqual(found.lengths_m, single.lengths_m)
                self.assertEqual(found.notices, ())

    def test_axis_of_32_m_digitized_30_plus_2_m(self) -> None:
        """Un eje recto de 32 m digitalizado 30 + 2 m con 20 m de ancho: las 640 celdas del
        rectángulo de 32 × 20 m (antes, 758: la unión redonda del vértice a 30 m pasaba del
        extremo hasta 49,5 m)."""
        layer = corridor_layer((((10.0, 40.0), (40.0, 40.0), (42.0, 40.0)),), ancho=(20.0,),
                               cota=(150.0,))
        found = quarry.corridor_cells(layer, FIXED, qfx.GRID)
        np.testing.assert_array_equal(np.isfinite(found.floors.grid),
                                      qfx.in_box((10.0, 30.0, 42.0, 50.0)))
        self.assertEqual(found.floors.cells, (640,))
        self.assertEqual(found.lengths_m, (31.0,))

    def test_quarry_axis_with_short_first_and_last_stretches(self) -> None:
        """El eje en L de la cantera con un primer tramo de 2 m y un último de 2 m (5 vértices)
        da las mismas celdas que el de 3 vértices (3.979), su rasante a ≤ 10⁻⁹ m y la misma
        longitud medida (199 m)."""
        whole = quarry.corridor_cells(fixture_layer(), GRADIENT, qfx.GRID)
        data = next(item for item in qfx.layers() if item.name == qfx.CORRIDORS_LAYER)
        axis = ((200.0, 160.0), (202.0, 160.0), (320.0, 160.0), (320.0, 82.0), (320.0, 80.0))
        found = quarry.corridor_cells(corridor_layer((axis,), **data.fields), GRADIENT, qfx.GRID)
        inside = np.isfinite(found.floors.grid)
        np.testing.assert_array_equal(inside, np.isfinite(whole.floors.grid))
        self.assertEqual(found.floors.cells, whole.floors.cells)
        np.testing.assert_allclose(found.floors.grid[inside], whole.floors.grid[inside],
                                   rtol=0, atol=TOLERANCE_M)
        self.assertEqual(found.lengths_m, whole.lengths_m)

    def test_short_hook_at_the_end_keeps_the_band_and_stops_at_its_end(self) -> None:
        """Un gancho de 2 m a 90° al final de un eje de 200 m (20 m de ancho): el rectángulo
        del primer tramo entero (4.000), el del gancho fuera de él (10 × 2 = 20) y la unión
        redonda de fuera del vértice (el cuarto de círculo de 10 m, 79): 4.099 celdas; nada
        después del final del gancho (antes, 4.158: la media circunferencia del vértice) ni un
        hueco en la banda del primer tramo. La longitud medida, la extensión de la huella a lo
        largo del eje sin recortar: de 0,5 a 209,5 m (la unión redonda pasa 10 m del vértice a
        lo largo del primer tramo), 209 m, sin aviso (no pasa de 202 + 20 m)."""
        layer = corridor_layer((((100.0, 200.0), (300.0, 200.0), (300.0, 202.0)),),
                               ancho=(20.0,), cota=(150.0,))
        found = quarry.corridor_cells(layer, FIXED, qfx.GRID)
        x, y = qfx.local_centers()
        quarter = (x > 300.0) & (y < 200.0) & ((x - 300.0) ** 2 + (y - 200.0) ** 2 <= 100.0)
        expected = (qfx.in_box((100.0, 190.0, 300.0, 210.0))
                    | qfx.in_box((300.0, 200.0, 310.0, 202.0)) | quarter)
        np.testing.assert_array_equal(np.isfinite(found.floors.grid), expected)
        self.assertEqual(found.floors.cells, (4000 + 20 + CORNER_CELLS,))
        self.assertEqual(found.lengths_m, (209.0,))
        self.assertEqual(found.notices, ())


class RandomShortEndTest(unittest.TestCase):
    """RF-014-09, RF-014-10 (T41, hallazgo F-2): ejes al azar frente a un punto en polígono y la
    longitud medida."""

    def test_30_straight_axes_with_a_short_end_stretch_by_point_in_polygon(self) -> None:
        """30 ejes rectos al azar con el primer tramo, el último o los dos más cortos que medio
        ancho (anchos de 6 a 20 m, celdas de 1 o 2 m): celda a celda, las del rectángulo de
        extremos planos de 0 a L (punto en polígono); la longitud medida, la extensión de sus
        centros a lo largo del eje a ≤ 10⁻⁹ m, que no pasa de L ni baja de L − 2 celdas."""
        rng = random.Random(41)
        for case in range(30):
            axis = straight_short_end(rng)
            with self.subTest(case=case, axis=axis["points"], width=axis["width"]):
                layer = corridor_layer((axis["points"],), ancho=(axis["width"],), cota=(150.0,))
                found = quarry.corridor_cells(layer, FIXED, axis["grid"])
                x, y = window_centers(axis["grid"])
                expected = point_in_polygon(x, y, axis["polygon"])
                np.testing.assert_array_equal(np.isfinite(found.floors.grid), expected)
                (x0, y0), (ux, uy) = axis["origin"], axis["direction"]
                along = ((x - x0) * ux + (y - y0) * uy)[expected]
                self.assertAlmostEqual(found.lengths_m[0], float(along.max() - along.min()),
                                       delta=TOLERANCE_M)
                self.assertLessEqual(found.lengths_m[0], axis["length"] + TOLERANCE_M)
                self.assertGreater(found.lengths_m[0], axis["length"] - 2.0 * axis["grid"].dx)

    def test_measured_length_of_60_broken_axes(self) -> None:
        """60 ejes quebrados al azar (2 a 4 vértices, tramos de al menos 1,2 anchos, giros de
        hasta 55°, celdas de 1 o 2 m): ningún centro antes del plano perpendicular del principio
        ni después del del final, y la longitud medida no pasa de L + 1 celda (A6) ni baja de L −
        2 celdas (es la de los centros: a cada extremo, el primero dentro queda a menos de una
        celda de su plano)."""
        rng = random.Random(4141)
        for case in range(60):
            points, width, grid = broken_axis(rng)
            with self.subTest(case=case, points=points, width=width):
                layer = corridor_layer((tuple(points),), ancho=(width,), cota=(150.0,))
                found = quarry.corridor_cells(layer, FIXED, grid)
                x, y = window_centers(grid)
                inside = np.isfinite(found.floors.grid)
                (ax, ay), (bx, by) = points[0], points[1]
                (cx, cy), (dx, dy) = points[-2], points[-1]
                start = ((x - ax) * (bx - ax) + (y - ay) * (by - ay))[inside]
                end = ((x - dx) * (dx - cx) + (y - dy) * (dy - cy))[inside]
                self.assertGreaterEqual(start.min(), -TOLERANCE_M)
                self.assertLessEqual(end.max(), TOLERANCE_M)
                length = sum(math.dist(a, b) for a, b in zip(points, points[1:], strict=False))
                self.assertLessEqual(found.lengths_m[0], length + grid.dx)
                self.assertGreater(found.lengths_m[0], length - 2.0 * grid.dx)


class NoticeTest(unittest.TestCase):
    """RF-014-10: el aviso de un corredor más largo que su eje más su ancho."""

    def test_too_long(self) -> None:
        """221 m con un eje de 200 m y 20 m de ancho avisa con las dos longitudes en m; 220 m, no."""
        text = quarry.corridor_too_long(3, 200.0, 221.0, 20.0)
        self.assertIsNotNone(text)
        self.assertIn("221 m", text)
        self.assertIn("200 m", text)
        self.assertIn("corredor 3", text)
        self.assertIsNone(quarry.corridor_too_long(3, 200.0, 220.0, 20.0))

    def test_map_notices(self) -> None:
        """Un ``CorridorMap`` con una longitud medida que pasa del eje más el ancho lo avisa."""
        found = quarry.corridor_cells(corridor_layer((STRAIGHT,), ancho=(20.0,), cota=(150.0,)),
                                      FIXED, qfx.GRID)
        longer = quarry.CorridorMap(found.floors, found.widths_m, found.axes_m, (230.0,))
        self.assertEqual(longer.notices,
                         (quarry.corridor_too_long(1, 200.0, 230.0, 20.0),))


class RejectionTest(unittest.TestCase):
    """RF-014-09 y casos límite (§8): los rechazos nombran la capa, el corredor, el campo y el
    valor, y no suponen nada."""

    def rejected(self, layer: Any, fields: Any = FIXED) -> Any:
        """El ``DesignError`` de convertir ``layer``."""
        with self.assertRaises(messages.DesignError) as caught:
            quarry.corridor_cells(layer, fields, qfx.GRID)
        return caught.exception

    def test_width_not_positive(self) -> None:
        """Ancho 0, negativo, sin valor o no finito: ``des.corridor_width`` nombrando el campo."""
        for width in (0.0, -5.0, None, float("nan")):
            with self.subTest(width=width):
                error = self.rejected(corridor_layer((STRAIGHT, ((0.0, 0.0), (50.0, 0.0))),
                                                     ancho=(20.0, width), cota=(150.0, 150.0)))
                self.assertEqual(error.code, "des.corridor_width")
                self.assertEqual(error.values["field"], "ancho")
                self.assertEqual(error.values["corridor"], 2)
                self.assertEqual(error.values["layer"], qfx.CORRIDORS_LAYER)

    def test_length_zero(self) -> None:
        """Un eje de longitud cero: ``des.corridor_length_zero``."""
        error = self.rejected(corridor_layer((((100.0, 100.0), (100.0, 100.0)),),
                                             ancho=(20.0,), cota=(150.0,)))
        self.assertEqual(error.code, "des.corridor_length_zero")
        self.assertEqual(error.values["corridor"], 1)

    def test_level_missing(self) -> None:
        """Sin cota fija, sin cota inicial o sin pendiente: ``des.corridor_level_missing`` con el
        campo."""
        cases = ((FIXED, {"cota": (None,)}, "cota"),
                 (GRADIENT, {"cota_inicial": (float("inf"),), "pendiente": (5.0,)}, "cota_inicial"),
                 (GRADIENT, {"cota_inicial": (125.0,), "pendiente": (None,)}, "pendiente"))
        for fields, values, field in cases:
            with self.subTest(field=field):
                error = self.rejected(corridor_layer((STRAIGHT,), ancho=(20.0,), **values),
                                      fields)
                self.assertEqual(error.code, "des.corridor_level_missing")
                self.assertEqual(error.values["field"], field)

    def test_not_lines(self) -> None:
        """Una capa de polígonos: ``des.corridor_not_lines``."""
        layer = vector.FeatureLayer("polygon", (1,), ((cfx.rectangle(0.0, 0.0, 10.0, 10.0),),),
                                    (vector.FieldColumn("ancho", "ancho", "DOUBLE"),),
                                    {"ancho": (20.0,)})
        error = self.rejected(layer)
        self.assertEqual(error.code, "des.corridor_not_lines")
        self.assertEqual(error.values["value"], "polígonos")

    def test_missing_field(self) -> None:
        """Un campo que la capa no tiene: ``des.quarry_layer_field``."""
        error = self.rejected(corridor_layer((STRAIGHT,), ancho=(20.0,), altura=(150.0,)))
        self.assertEqual(error.code, "des.quarry_layer_field")
        self.assertEqual(error.values["value"], "cota")

    def test_overlap(self) -> None:
        """Dos corredores que se cruzan son dos fondos que se solapan (RF-014-06):
        ``des.floor_overlap`` con los dos."""
        error = self.rejected(corridor_layer((STRAIGHT, ((200.0, 100.0), (200.0, 300.0))),
                                             ancho=(20.0, 10.0), cota=(150.0, 150.0)))
        self.assertEqual(error.code, "des.floor_overlap")
        self.assertEqual((error.values["value"], error.values["other"]), (1, 2))
        self.assertEqual(error.values["cells"], 200)


LOW_M = -819.84375
"""La cota más baja que admite un fondo en la cantera: la mínima del terreno (180,15625 m) menos
1.000 m, a mano."""
HIGH_M = 1307.84375
"""La más alta: la máxima del terreno (307,84375 m) más 1.000 m, a mano."""


class LevelRangeTest(unittest.TestCase):
    """RF-014-06, RF-014-09, RF-014-05 (T42, hallazgo F-3): un corredor es un polígono de fondo,
    también para el rango de su cota y para lo que queda por encima del terreno."""

    terrain: Any

    @classmethod
    def setUpClass(cls) -> None:
        cls.terrain = qfx.terrain()

    def rejected(self, layer: Any, fields: Any = FIXED) -> Any:
        """El ``DesignError`` de convertir ``layer`` con la superficie de partida."""
        with self.assertRaises(messages.DesignError) as caught:
            quarry.corridor_cells(layer, fields, qfx.GRID, start=self.terrain)
        return caught.exception

    def test_a_fixed_level_out_of_the_terrain_range_is_refused(self) -> None:
        """Una cota fija de 5.000 m o de 10⁶ m (la T38: se admitían y anulaban la corta en
        silencio), o medio metro fuera de ``[−819,84375, 1.307,84375]`` m: ``des.corridor_level``
        con la capa, el corredor 2, el campo, el valor y el rango, y su texto dice «corredor 2», no
        «polígono 2» (T51 (h); en inglés, «corridor 2»); el corredor 1, en el rango, no."""
        for level in (5000.0, 1.0e6, LOW_M - 0.5, HIGH_M + 0.5):
            with self.subTest(level=level):
                error = self.rejected(corridor_layer((STRAIGHT, ((0.0, 0.0), (50.0, 0.0))),
                                                     ancho=(20.0, 10.0), cota=(150.0, level)))
                self.assertEqual(error.code, "des.corridor_level")
                self.assertEqual(error.values["layer"], qfx.CORRIDORS_LAYER)
                self.assertEqual(error.values["corridor"], 2)
                self.assertEqual(error.values["field"], "cota")
                self.assertEqual(error.values["value"], level)
                self.assertEqual((error.values["low"], error.values["high"]), (LOW_M, HIGH_M))
                self.assertEqual(error.obj, f"Corredor 2 de la capa «{qfx.CORRIDORS_LAYER}»")
                self.assertIn(f"Capa «{qfx.CORRIDORS_LAYER}», corredor 2: «cota» = ", error.text)
                self.assertNotIn("polígono", error.text)
                self.assertIn(f"Layer «{qfx.CORRIDORS_LAYER}», corridor 2: «cota» = ",
                              error.text_in("en"))

    def test_the_start_and_the_end_of_a_gradient_out_of_the_range_are_refused(self) -> None:
        """Con rasante, la cota inicial fuera del rango (``cota_inicial``) y la final, la del
        final del eje de 200 m: 300 + 200 · 600 / 100 = 1.500 m y 0 − 200 · 500 / 100 = −1.000 m
        (``cota_inicial + pendiente``, con la cota final)."""
        cases = (((-900.0,), (1.0,), "cota_inicial", -900.0),
                 ((300.0,), (600.0,), "cota_inicial + pendiente", 1500.0),
                 ((0.0,), (-500.0,), "cota_inicial + pendiente", -1000.0))
        for start, gradient, field, value in cases:
            with self.subTest(field=field, value=value):
                error = self.rejected(corridor_layer((STRAIGHT,), ancho=(20.0,),
                                                     cota_inicial=start, pendiente=gradient),
                                      GRADIENT)
                self.assertEqual(error.code, "des.corridor_level")
                self.assertEqual((error.values["corridor"], error.values["field"]), (1, field))
                self.assertEqual(error.values["value"], value)

    def test_the_ends_of_the_range_and_a_level_above_the_terrain_are_admitted(self) -> None:
        """Las cotas justo en los extremos del rango se admiten, y también la de un corredor por
        encima del terreno (290 m sobre 233,75 a 251,25 m): sus 4.000 celdas cuentan en lo de los
        fondos sobre el terreno (RF-014-05), que se admite y se avisa con su área."""
        found: dict[float, Any] = {}
        for level in (LOW_M, HIGH_M, 290.0):
            with self.subTest(level=level):
                found[level] = quarry.corridor_cells(
                    corridor_layer((STRAIGHT,), ancho=(20.0,), cota=(level,)), FIXED, qfx.GRID,
                    start=self.terrain)
                self.assertEqual(found[level].floors.cells, (4000,))
        above = quarry.floors_above_terrain(found[290.0].floors, self.terrain)
        self.assertEqual((above.cells, above.area_m2), (4000, 4000.0))
        self.assertIn("4000 m² de los fondos quedan por encima del terreno",
                      above.notice.replace(i18n.THIN_SPACE, ""))

    def test_floors_and_corridors_above_the_terrain_are_counted_once(self) -> None:
        """``floors_above_terrain`` con los fondos y los corredores (RF-014-05, RF-014-09): un
        fondo de 200 × 20 m a 290 m y el corredor recto a 290 m sobre él cuentan 4.000 celdas, no
        8.000; con otro corredor de 200 × 20 m a 290 m más al sur, 8.000."""
        polygon = vector.FeatureLayer(
            "polygon", (1,), (((cfx.rectangle(100.0, 190.0, 300.0, 210.0),),),),
            (vector.FieldColumn("cota", "cota", "DOUBLE"),), {"cota": (290.0,)})
        floors = quarry.floor_map(polygon, model.LayerField(qfx.FLOORS_LAYER, "cota"),
                                  self.terrain, qfx.GRID)
        same = quarry.corridor_cells(corridor_layer((STRAIGHT,), ancho=(20.0,), cota=(290.0,)),
                                     FIXED, qfx.GRID, start=self.terrain)
        south = quarry.corridor_cells(corridor_layer((((100.0, 100.0), (300.0, 100.0)),),
                                                     ancho=(20.0,), cota=(290.0,)),
                                      FIXED, qfx.GRID, start=self.terrain)
        self.assertEqual(quarry.floors_above_terrain(floors, self.terrain, same.floors).cells,
                         4000)
        self.assertEqual(quarry.floors_above_terrain(floors, self.terrain, south.floors).cells,
                         8000)
        self.assertEqual(quarry.floors_above_terrain(floors, self.terrain, same.floors,
                                                     south.floors).area_m2, 8000.0)


if __name__ == "__main__":
    unittest.main()

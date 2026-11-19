# SPDX-License-Identifier: GPL-3.0-or-later
"""La regla del espesor y el cuerpo apoyado, en el dominio (spec 016, T23; HU-016-4; RF-016-01, RF-016-20, RF-016-21,
RF-016-22; plan 016 §5.4 A11 y §5.7 P-7; D-8, D-9; errores 26 y B9).

:func:`design.thickness.derive` (RF-016-01) y :func:`design.thickness.body_steps` (A11) reciben un :class:`BodyJob` (todo lo
leído y nada del proyecto) y dan el :class:`BodyOutcome`. Cada cifra esperada sale de **un cálculo a mano o de un bucle de
Python independiente** (el más próximo por fuerza bruta con enteros, la envolvente convexa por la cadena monótona, el plano por
tres puntos con ``numpy.linalg.solve``, las celdas del borde por sus cuatro vecinas, la media de varios datos de una celda en
un diccionario): **ninguna** se calcula llamando al código bajo prueba.

- **La regla** (:class:`DeriveTest`): ``derive`` en los dos sentidos —«sobre una base», techo = apoyo + espesor; «bajo un
  techo», base = techo − espesor—, la base nunca por encima del techo ni un espesor negativo (rechazado con su celda) y el
  espesor, la diferencia de las dos a ≤ 10⁻⁹.
- **Los datos llevados a su celda** (:class:`CarryTest`): varios en una celda, su media; un punto sobre el borde de una celda
  es de la que tiene ese borde al oeste o al norte; un polígono, una celda por cada centro que contiene (con la media de los que
  coinciden); y los que caen fuera de la huella, ignorados con su aviso.
- **El espesor interpolado** (:class:`InterpolationTest`): con datos de un plano, el plano en toda la envolvente convexa y el
  dato más próximo fuera de ella; reproduce cada dato a ≤ 10⁻⁹ m, entre el menor y el mayor y sin ser negativo; los
  triángulos de lado mayor que ``2·max_distance_m`` se descartan (el más próximo donde caían); sin triángulos (menos de tres
  datos o alineados), el más próximo; y «cero en el borde» = sumar datos de valor 0 en las celdas del borde.
- **Lo lejano** (:class:`FarTest`, RF-016-21): las celdas a más de la distancia máxima con su área, su volumen y su lugar (la
  más lejana), sin impedir calcular; el límite es estricto («a más de»).
- **Los rechazos** (:class:`RejectionTest`, RF-016-22): sin datos en la huella o con todas las celdas lejos, nombrando la huella
  y la capa; sin distancia máxima (D-9) o fuera de rango, nombrando la clave.
- **La superficie y las cifras** (:class:`SurfaceTest`, :class:`FiguresTest`) y **los pasos** (:class:`StepsTest`): la
  ventana de trabajo da lo mismo que la rejilla entera, bit a bit; ninguna entrada se modifica.
- **El escalón del borde** (:class:`EdgeStepTest`, T46; RF-015-13, hallazgo C-1): un cuerpo «sobre una base» cuyo espesor en el borde de la
  huella no es 0 termina en un escalón; el renglón informativo (``des.body_edge_step``) da el mayor y su lugar, contra un bucle de Python.
"""

from __future__ import annotations

import dataclasses
import itertools
import math
import random
import unittest
from typing import Any

import numpy as np

from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender

gis = import_geoblender("gis")
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")
provenance = import_geoblender("design.provenance")
thickness = import_geoblender("design.thickness")

DesignError = messages.DesignError
STEP = 2.0
N = 24
GRID = sdata.window_grid(STEP, STEP * N)
AREA = STEP * STEP
EXACT = 1e-9
LAYER = "Espesores de la ladera"
FEATURE = "Cuerpo de la ladera"
DATA_OUTSIDE = "des.body_data_outside"
FAR = "des.body_far"
NO_DATA = "des.body_no_data"
ALL_FAR = "des.body_all_far"
ALL_UNSUPPORTED = "des.body_all_unsupported"


# --- Lo que se construye -----------------------------------------------------------------------------------------------


def center(row: int, col: int, grid: Any = GRID) -> tuple[float, float]:
    """El centro ABSOLUTO de la celda ``(row, col)`` de ``grid`` (fila 0 al norte)."""
    return grid.west + (col + 0.5) * grid.dx, grid.north - (row + 0.5) * grid.dy


def box(r0: int, r1: int, c0: int, c1: int) -> np.ndarray:
    """La máscara de las celdas de las filas ``r0 … r1 − 1`` y las columnas ``c0 … c1 − 1``."""
    found = np.zeros(GRID.shape, dtype=bool)
    found[r0:r1, c0:c1] = True
    return found


def ring(r0: int, r1: int, c0: int, c1: int) -> np.ndarray:
    """Un anillo ABSOLUTO que rodea justo esas celdas (sus bordes son los de las celdas: los centros no son ambiguos)."""
    west, east = GRID.west + c0 * GRID.dx, GRID.west + c1 * GRID.dx
    north, south = GRID.north - r0 * GRID.dy, GRID.north - r1 * GRID.dy
    return np.array([[west, south], [east, south], [east, north], [west, north]], dtype=np.float64)


def points_of(cells: dict[tuple[int, int], float]) -> np.ndarray:
    """Los datos ``(x, y, espesor)`` en el centro de cada celda de ``cells``."""
    return np.array([(*center(row, col), value) for (row, col), value in cells.items()], dtype=np.float64).reshape(-1, 3)


def request(sense: str = "under_roof", **extra: Any) -> Any:
    start = {"start": "Superficie de partida"} if sense == "on_base" else {}
    return model.BodyRequest(name="Cuerpo A", layer="Cuerpos", feature=FEATURE, data_layer=LAYER, data_field="espesor",
                             data_from="field", surface="Terreno", sense=sense, **start, **extra)


def job_of(footprint: np.ndarray, *, points: Any = None, polygons: Any = (), support: np.ndarray | None = None,
           sense: str = "under_roof", distance: float | None = 5000.0, zero: bool | None = False,
           start: np.ndarray | None = None, fill: np.ndarray | None = None, region: Any = None,
           grid: Any = GRID, values: dict[str, Any] | None = None) -> Any:
    """El trabajo de un cuerpo en ``grid``: por defecto el apoyo es un plano a 100 m y la distancia máxima, enorme (nada se
    descarta ni es lejano)."""
    given = np.empty((0, 3)) if points is None else np.asarray(points, dtype=np.float64)
    data = thickness.ThicknessData(given, tuple(polygons))
    floor = np.full(grid.shape, 100.0) if support is None else support
    if values is None:
        values = {}
        if distance is not None:
            values["max_distance_m"] = distance
        if zero is not None:
            values["zero_at_edge"] = zero
    extra: dict[str, Any] = {}
    if sense == "on_base":
        extra["start"] = floor.copy() if start is None else start
        extra["fill_allowed"] = np.ones(grid.shape, dtype=bool) if fill is None else fill
    return thickness.BodyJob(request(sense), "BDY-001", grid, sdata.CRS, sdata.VERTICAL, floor, footprint, data, values,
                             region=region, **extra)


def run(job: Any) -> Any:
    return thickness.compute_body(job)


# --- Los oráculos independientes ---------------------------------------------------------------------------------------


def hand_edges(footprint: np.ndarray) -> list[tuple[int, int]]:
    """Las celdas de la huella con alguna de sus cuatro vecinas fuera de ella (un bucle; fuera del array = «sigue»)."""
    rows, cols = footprint.shape
    found = []
    for row, col in itertools.product(range(rows), range(cols)):
        if not footprint[row, col]:
            continue
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            r, c = row + dr, col + dc
            if 0 <= r < rows and 0 <= c < cols and not footprint[r, c]:
                found.append((row, col))
                break
    return found


def hand_nearest(data: dict[tuple[int, int], float], shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """Por cada celda, el cuadrado de la distancia (en celdas²) al dato más próximo y su valor (a igual distancia, el menor),
    por fuerza bruta con enteros."""
    d2 = np.zeros(shape, dtype=np.int64)
    value = np.zeros(shape)
    for row, col in itertools.product(range(shape[0]), range(shape[1])):
        best: tuple[int, float] | None = None
        for (r, c), v in data.items():
            found = ((row - r) ** 2 + (col - c) ** 2, v)
            if best is None or found < best:
                best = found
        assert best is not None
        d2[row, col], value[row, col] = best
    return d2, value


def hand_hull(cells: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """La envolvente convexa de ``cells`` (columna, fila enteras) por la cadena monótona, en sentido antihorario."""
    pts = sorted({(col, row) for row, col in cells})

    def cross(o: tuple[int, int], a: tuple[int, int], b: tuple[int, int]) -> int:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[int, int]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[tuple[int, int]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def in_hull(hull: list[tuple[int, int]], row: int, col: int) -> bool:
    """Si la celda está dentro de la envolvente o en su borde (enteros exactos)."""
    for a, b in zip(hull, hull[1:] + hull[:1], strict=True):
        if (b[0] - a[0]) * (row - a[1]) - (b[1] - a[1]) * (col - a[0]) < 0:
            return False
    return True


def plane_through(three: list[tuple[int, int, float]]) -> tuple[float, float, float]:
    """``(a, b, c)`` de ``t = a + b·col + c·fila`` por tres datos ``(fila, columna, valor)`` (``numpy.linalg.solve``)."""
    matrix = np.array([[1.0, col, row] for row, col, _v in three])
    return tuple(np.linalg.solve(matrix, np.array([v for _r, _c, v in three])))  # type: ignore[return-value]


def in_triangle(three: list[tuple[int, int, float]], row: int, col: int) -> bool:
    """Si la celda está dentro del triángulo de los tres datos o en su borde (enteros exactos)."""
    pts = [(c, r) for r, c, _v in three]
    area = (pts[1][0] - pts[0][0]) * (pts[2][1] - pts[0][1]) - (pts[1][1] - pts[0][1]) * (pts[2][0] - pts[0][0])
    sign = 1 if area > 0 else -1
    return all(sign * ((b[0] - a[0]) * (row - a[1]) - (b[1] - a[1]) * (col - a[0])) >= 0
               for a, b in zip(pts, pts[1:] + pts[:1], strict=True))


def absolute(row: int, col: int) -> tuple[float, float]:
    return center(row, col)


# --- La regla (RF-016-01) ----------------------------------------------------------------------------------------------


class DeriveTest(unittest.TestCase):
    """RF-016-01: ``derive(apoyo, espesor, sentido) → (base, techo)`` con la base ≤ el techo y el espesor ≥ 0."""

    SUPPORT = np.array([[100.0, 101.5, np.nan], [99.25, 100.0, 120.0]])
    THICK = np.array([[2.0, 0.0, 3.0], [np.nan, 4.5, 0.25]])

    def test_on_a_base_the_top_is_the_support_plus_the_thickness(self) -> None:
        """RF-016-01, RF-016-20 («sobre una base»): la base es el apoyo y el techo, el apoyo más el espesor, a mano en cada
        celda; donde falta el apoyo o el espesor, sin dato en las dos."""
        base, top = thickness.derive(self.SUPPORT, self.THICK, "on_base")
        nan = np.nan
        np.testing.assert_array_equal(base, [[100.0, 101.5, nan], [nan, 100.0, 120.0]])
        np.testing.assert_array_equal(top, [[102.0, 101.5, nan], [nan, 104.5, 120.25]])

    def test_under_a_roof_the_base_is_the_roof_minus_the_thickness(self) -> None:
        """RF-016-01, RF-016-20 («bajo un techo», el escombro existente): el techo es la superficie conocida y la base, el techo
        menos el espesor; un espesor de 0 deja la base en el techo."""
        base, top = thickness.derive(self.SUPPORT, self.THICK, thickness.BodySense.UNDER_ROOF)
        nan = np.nan
        np.testing.assert_array_equal(top, [[100.0, 101.5, nan], [nan, 100.0, 120.0]])
        np.testing.assert_array_equal(base, [[98.0, 101.5, nan], [nan, 95.5, 119.75]])

    def test_the_base_is_never_above_the_top_and_the_thickness_is_their_difference(self) -> None:
        """RF-016-01: con espesores ≥ 0 cualesquiera (también 0 y muy pequeños), base ≤ techo en **todas** las celdas y
        techo − base = espesor a ≤ 10⁻⁹ m, en los dos sentidos, sobre cotas de 4,4 Mm de norte no hace falta: las cotas son m."""
        rng = random.Random(26)
        support = np.array([[rng.uniform(80.0, 400.0) for _ in range(40)] for _ in range(30)])
        thick = np.array([[rng.choice((0.0, 1e-12, rng.uniform(0.0, 40.0))) for _ in range(40)] for _ in range(30)])
        for sense in ("on_base", "under_roof"):
            with self.subTest(sentido=sense):
                base, top = thickness.derive(support, thick, sense)
                self.assertTrue(np.all(base <= top))
                self.assertLessEqual(float(np.max(np.abs((top - base) - thick))), EXACT)

    def test_a_negative_thickness_is_refused_with_its_cell(self) -> None:
        """RF-016-01 (error 26): un espesor negativo no entra —ni se «arregla»—: ``ValueError`` con la primera celda (fila,
        columna) y su valor."""
        bad = self.THICK.copy()
        bad[1, 2] = -0.5
        with self.assertRaises(ValueError) as caught:
            thickness.derive(self.SUPPORT, bad, "on_base")
        text = str(caught.exception)
        self.assertIn("(1, 2)", text)
        self.assertIn("-0.5", text)

    def test_shapes_and_values_are_checked(self) -> None:
        """Una forma que no casa, un valor infinito o un sentido desconocido son errores del programa."""
        with self.assertRaises(ValueError):
            thickness.derive(self.SUPPORT, self.THICK[:1], "on_base")
        infinite = self.THICK.copy()
        infinite[0, 0] = np.inf
        with self.assertRaises(ValueError):
            thickness.derive(self.SUPPORT, infinite, "on_base")
        with self.assertRaises(ValueError):
            thickness.derive(self.SUPPORT, self.THICK, "en el aire")

    def test_nothing_is_modified_and_the_results_are_new(self) -> None:
        """Ninguna entrada se modifica y la base y el techo son arrays nuevos."""
        support, thick = self.SUPPORT.copy(), self.THICK.copy()
        base, top = thickness.derive(support, thick, "under_roof")
        np.testing.assert_array_equal(support, self.SUPPORT)
        np.testing.assert_array_equal(thick, self.THICK)
        self.assertFalse(np.shares_memory(top, support))
        self.assertFalse(np.shares_memory(base, support))


# --- Los datos llevados a su celda (A11) -------------------------------------------------------------------------------


class CarryTest(unittest.TestCase):
    """RF-016-20: los datos se llevan al centro de su celda; varios en una celda, su media; los de fuera de la huella, ignorados
    con aviso."""

    FOOT = box(2, 14, 2, 14)

    def test_several_data_in_a_cell_are_their_mean(self) -> None:
        """RF-016-20: dos datos en la celda (5, 5) (1 y 2 m) dan 1,5 m y tres en la (8, 9) (1, 2 y 6 m), 3 m, a ≤ 10⁻⁹ m; las
        celdas con un solo dato lo tienen tal cual. Cada dato está en un punto distinto de su celda."""
        x5, y5 = center(5, 5)
        x8, y8 = center(8, 9)
        rows = [(x5 - 0.7, y5 + 0.4, 1.0), (x5 + 0.9, y5 - 0.9, 2.0),
                (x8 - 0.9, y8 + 0.9, 1.0), (x8, y8, 2.0), (x8 + 0.3, y8 - 0.3, 6.0),
                (*center(3, 11), 2.0), (*center(11, 3), 4.0), (*center(12, 12), 0.5)]
        outcome = run(job_of(self.FOOT, points=rows))
        self.assertLessEqual(abs(outcome.thickness[5, 5] - 1.5), EXACT)
        self.assertLessEqual(abs(outcome.thickness[8, 9] - 3.0), EXACT)
        self.assertLessEqual(abs(outcome.thickness[3, 11] - 2.0), EXACT)
        self.assertLessEqual(abs(outcome.thickness[11, 3] - 4.0), EXACT)
        self.assertEqual(outcome.data_cells, 5)
        self.assertEqual(outcome.ignored, 0)
        self.assertEqual(outcome.notices, ())

    def test_a_point_on_the_edge_of_a_cell_belongs_to_the_one_east_and_south_of_it(self) -> None:
        """Un punto exactamente sobre el borde oeste y el borde norte de la celda (4, 3) es de **esa** celda (intervalos
        semiabiertos: el borde oeste y el norte son de la celda a su este y a su sur); a mano: x = oeste + 3·paso, y = norte −
        4·paso."""
        x, y = GRID.west + 3 * GRID.dx, GRID.north - 4 * GRID.dy
        other = [(*center(8, 8), 2.0), (*center(10, 4), 2.0), (*center(4, 10), 2.0)]
        outcome = run(job_of(self.FOOT, points=[(x, y, 7.0), *other]))
        self.assertEqual(outcome.data_cells, 4)
        self.assertEqual(outcome.thickness[4, 3], 7.0)

    def test_data_outside_the_footprint_are_ignored_with_a_warning(self) -> None:
        """RF-016-20: los datos fuera de la huella —y fuera de la rejilla, y los de un polígono sin ninguna celda dentro— se
        ignoran con ``des.body_data_outside`` y su número; los de dentro no cambian."""
        inside = [(*center(5, 5), 2.0), (*center(9, 9), 3.0), (*center(5, 11), 1.0)]
        outside = [(*center(20, 20), 9.0), (*center(0, 0), 9.0), (GRID.west - 50.0, GRID.north + 50.0, 9.0)]
        far_polygon = ((ring(18, 21, 18, 21),), 8.0)
        job = job_of(self.FOOT, points=[*inside, *outside], polygons=[far_polygon])
        outcome = run(job)
        self.assertEqual(outcome.ignored, 4)
        notice = [n for n in outcome.notices if n.code == DATA_OUTSIDE]
        self.assertEqual(len(notice), 1)
        self.assertEqual(notice[0].values["ignored"], 4)
        self.assertEqual(notice[0].values["entity"], "Cuerpo A")
        self.assertEqual(outcome.data_cells, 3)
        self.assertLessEqual(float(np.nanmax(outcome.thickness)), 3.0)

    def test_a_polygon_is_one_datum_per_cell_whose_center_it_holds(self) -> None:
        """Duda de la T23 (RF-016-20, polígonos): cada celda con el centro dentro del polígono es un dato con su valor, y donde
        coinciden varios polígonos, su media; un punto en la misma celda cuenta como un dato más. A mano con dos bandas y un
        punto: P1 (filas 3 a 5, columnas 2 a 8, 2 m), P2 (filas 5 a 8, columnas 6 a 12, 4 m) y un punto de 1 m en la (3, 3)."""
        p1 = ((ring(3, 6, 2, 9),), 2.0)
        p2 = ((ring(5, 9, 6, 13),), 4.0)
        expected: dict[tuple[int, int], list[float]] = {}
        for row, col in itertools.product(range(3, 6), range(2, 9)):
            expected.setdefault((row, col), []).append(2.0)
        for row, col in itertools.product(range(5, 9), range(6, 13)):
            expected.setdefault((row, col), []).append(4.0)
        expected.setdefault((3, 3), []).append(1.0)
        outcome = run(job_of(box(2, 13, 2, 13), points=[(*center(3, 3), 1.0)], polygons=[p1, p2]))
        self.assertEqual(outcome.data_cells, len(expected))
        self.assertEqual(outcome.ignored, 0)
        for (row, col), found in expected.items():
            self.assertLessEqual(abs(outcome.thickness[row, col] - sum(found) / len(found)), EXACT, (row, col))
        self.assertEqual(expected[(5, 7)], [2.0, 4.0])  # el solape: 3 m
        self.assertLessEqual(abs(outcome.thickness[5, 7] - 3.0), EXACT)
        self.assertLessEqual(abs(outcome.thickness[3, 3] - 1.5), EXACT)

    def test_a_polygon_with_a_hole_does_not_give_the_hole(self) -> None:
        """Un polígono con un hueco (par-impar) solo da las celdas del anillo: las del hueco no son un dato."""
        outer, hole = ring(3, 12, 3, 12), ring(6, 9, 6, 9)
        outcome = run(job_of(box(2, 13, 2, 13), polygons=[((outer, hole), 2.0), ((ring(10, 12, 10, 12),), 4.0)]))
        self.assertEqual(outcome.data_cells, 9 * 9 - 3 * 3)

    def test_a_datum_in_a_hole_of_the_footprint_is_outside(self) -> None:
        """La huella se toma por celdas: un dato en un hueco de la huella no cae en ella (se ignora)."""
        foot = box(2, 14, 2, 14)
        foot[6:9, 6:9] = False
        rows = [(*center(5, 5), 2.0), (*center(10, 10), 3.0), (*center(12, 4), 1.0), (*center(7, 7), 9.0)]
        outcome = run(job_of(foot, points=rows))
        self.assertEqual(outcome.ignored, 1)
        self.assertEqual(outcome.data_cells, 3)


# --- El espesor interpolado (A11, P-7) ---------------------------------------------------------------------------------


class InterpolationTest(unittest.TestCase):
    """RF-016-20 (P-7): el TIN lineal sobre los datos de sus celdas, con el más próximo donde no llega."""

    def test_plane_data_give_the_plane_in_the_hull_and_the_nearest_outside(self) -> None:
        """RF-016-20: siete datos de un plano ``1 + 0,1·columna + 0,05·fila`` dan el **plano** en toda la envolvente convexa (a
        ≤ 10⁻⁹ m: cualquier triangulación lo reproduce) y, fuera de ella, el dato más próximo (por fuerza bruta); la envolvente
        sale de la cadena monótona; con una distancia máxima enorme no se descarta ningún triángulo."""
        cells = [(4, 5), (5, 16), (9, 10), (13, 4), (15, 18), (18, 9), (12, 13)]
        data = {cell: 1.0 + 0.1 * cell[1] + 0.05 * cell[0] for cell in cells}
        foot = box(2, 22, 3, 21)
        outcome = run(job_of(foot, points=points_of(data)))
        hull = hand_hull(cells)
        _d2, nearest = hand_nearest(data, GRID.shape)
        checked = 0
        for row, col in itertools.product(range(N), range(N)):
            if not foot[row, col]:
                self.assertTrue(np.isnan(outcome.thickness[row, col]))
                continue
            want = 1.0 + 0.1 * col + 0.05 * row if in_hull(hull, row, col) else nearest[row, col]
            self.assertLessEqual(abs(outcome.thickness[row, col] - want), EXACT, (row, col))
            checked += 1
        self.assertEqual(checked, 20 * 18)
        self.assertGreater(outcome.tin_cells, 0)
        self.assertGreater(outcome.nearest_cells, 0)
        self.assertEqual(outcome.tin_cells + outcome.nearest_cells, 20 * 18)

    def test_every_datum_is_reproduced_inside_its_bounds_and_never_negative(self) -> None:
        """RF-016-20: con 35 datos al azar (con ceros, y un espesor 0 junto a uno de 5 m), el espesor **reproduce cada dato a
        ≤ 10⁻⁹ m**, queda entre el menor y el mayor **sin tolerancia** y no es negativo en ninguna celda."""
        rng = random.Random(16)
        cells = rng.sample(list(itertools.product(range(3, 21), range(3, 21))), 35)
        data = {cell: rng.choice((0.0, 0.0, round(rng.uniform(0.0, 5.0), 3))) for cell in cells}
        data[cells[0]], data[cells[1]] = 5.0, 0.0
        foot = box(3, 21, 3, 21)
        outcome = run(job_of(foot, points=points_of(data)))
        for (row, col), value in data.items():
            self.assertLessEqual(abs(outcome.thickness[row, col] - value), EXACT, (row, col))
        inside = outcome.thickness[foot]
        self.assertGreaterEqual(float(inside.min()), min(data.values()))
        self.assertLessEqual(float(inside.max()), max(data.values()))
        self.assertGreaterEqual(float(inside.min()), 0.0)
        self.assertEqual(outcome.data_cells, 35)

    def test_long_triangles_are_discarded_and_the_nearest_takes_their_place(self) -> None:
        """RF-016-20 (A11): con dos grupos de tres datos separados por mucho más de ``2·max_distance_m`` (12 m = 6 celdas), la
        triangulación solo conserva el triángulo de cada grupo (plano por sus tres datos, ``numpy.linalg.solve``) y **todo lo
        demás** toma el dato más próximo (fuerza bruta), también donde el triángulo de unión lo habría interpolado."""
        a = [(3, 3, 1.0), (3, 6, 2.0), (6, 4, 3.0)]
        b = [(16, 17, 0.5), (17, 20, 1.5), (20, 18, 4.0)]
        data = {(r, c): v for r, c, v in (*a, *b)}
        foot = box(1, 23, 1, 23)
        outcome = run(job_of(foot, points=points_of(data), distance=6.0))
        _d2, nearest = hand_nearest(data, GRID.shape)
        planes = [(a, plane_through(a)), (b, plane_through(b))]
        in_a_triangle = 0
        for row, col in itertools.product(range(1, 23), range(1, 23)):
            want = nearest[row, col]
            for three, (p0, p1, p2) in planes:
                if in_triangle(three, row, col):
                    want = p0 + p1 * col + p2 * row
                    in_a_triangle += 1
            self.assertLessEqual(abs(outcome.thickness[row, col] - want), EXACT, (row, col))
        self.assertGreater(in_a_triangle, 6)
        self.assertEqual(outcome.tin_cells, in_a_triangle)

    def test_rounding_never_makes_a_thickness_negative(self) -> None:
        """RF-016-01, RF-016-20 (error 26): con muchos datos de 0 m y unos pocos de más, las coordenadas baricéntricas de una
        celda **sobre** una arista pueden salir en −10⁻¹⁷ (la tercera es ``1 − a − b``) y dar un espesor de −10⁻¹⁷ m (la semilla
        12 de este bucle lo da sin el recorte al intervalo de los datos): el espesor es exactamente ≥ 0 y ≤ el mayor dato en
        todas las celdas de 40 casos al azar, y ``derive`` no lo rechaza."""
        for seed in range(40):
            with self.subTest(semilla=seed):
                rng = random.Random(seed)
                cells = rng.sample(list(itertools.product(range(3, 21), range(3, 21))), 25)
                data = {cell: rng.choice((0.0, 0.0, 0.0, round(rng.uniform(0.5, 5.0), 3))) for cell in cells}
                foot = box(3, 21, 3, 21)
                outcome = run(job_of(foot, points=points_of(data)))
                inside = outcome.thickness[foot]
                self.assertGreaterEqual(float(inside.min()), 0.0)
                self.assertLessEqual(float(inside.max()), max(data.values()))

    def test_a_triangle_is_kept_up_to_twice_the_maximum_distance(self) -> None:
        """RF-016-20 (A11): solo se descartan los triángulos con un lado **mayor que** ``2·max_distance_m``: con 6 m (12 m = 6
        celdas de 2 m) un triángulo cuyo lado mayor mide **exactamente** 6 celdas se conserva (el plano por sus tres datos) y
        otro de 7 celdas se descarta (el dato más próximo de cada celda); a mano en cada celda."""
        foot = box(1, 23, 1, 23)
        for length, kept in ((6, True), (7, False)):
            with self.subTest(lado=length):
                data = {(5, 5): 1.0, (5, 5 + length): 2.0, (9, 8): 4.0}
                three = [(row, col, value) for (row, col), value in data.items()]
                p0, p1, p2 = plane_through(three)
                _d2, nearest = hand_nearest(data, GRID.shape)
                outcome = run(job_of(foot, points=points_of(data), distance=6.0))
                inside = 0
                for row, col in itertools.product(range(1, 23), range(1, 23)):
                    in_it = in_triangle(three, row, col)
                    inside += in_it
                    want = p0 + p1 * col + p2 * row if kept and in_it else nearest[row, col]
                    self.assertLessEqual(abs(outcome.thickness[row, col] - want), EXACT, (row, col))
                self.assertGreater(inside, 10)
                self.assertEqual(outcome.tin_cells, inside if kept else 0)

    def test_without_a_triangle_the_nearest_datum_takes_everything(self) -> None:
        """RF-016-20: con un solo dato, con dos o con tres alineados (nada que triangular), el espesor de cada celda es el del
        dato más próximo; no es un error."""
        foot = box(3, 21, 3, 21)
        cases = {"uno": {(8, 8): 2.5}, "dos": {(5, 5): 1.0, (15, 15): 3.0},
                 "alineados": {(10, 4): 1.0, (10, 9): 2.0, (10, 17): 0.5}}
        for name, data in cases.items():
            with self.subTest(datos=name):
                outcome = run(job_of(foot, points=points_of(data)))
                _d2, nearest = hand_nearest(data, GRID.shape)
                for row, col in itertools.product(range(3, 21), range(3, 21)):
                    self.assertLessEqual(abs(outcome.thickness[row, col] - nearest[row, col]), EXACT, (row, col))
                self.assertEqual(outcome.tin_cells, 0)

    def test_zero_at_the_edge_adds_zero_data_in_the_edge_cells(self) -> None:
        """RF-016-20 (A11: «las celdas del borde de la huella suman datos de valor 0»): con ``zero_at_edge`` las celdas del
        borde de la huella (con una vecina de fuera) valen 0, el interior reproduce sus datos y no pasa del mayor; y es
        **exactamente** lo mismo, bit a bit, que dar sin él esos ceros como datos (el borde de cada celda por sus cuatro
        vecinas, un bucle). Un dato sobre una celda del borde se promedia con su cero (3 m → 1,5 m): la regla de «varios en una
        celda»."""
        foot = box(4, 17, 4, 19)
        interior = {(8, 8): 2.0, (10, 14): 3.0, (13, 7): 1.0, (7, 13): 4.0, (12, 12): 2.5}
        at_edge = {(4, 10): 3.0}
        edges = hand_edges(foot)
        self.assertEqual(len(edges), 13 * 15 - 11 * 13)
        with_zero = run(job_of(foot, points=points_of({**interior, **at_edge}), zero=True))
        by_hand = {**interior, **{cell: 0.0 for cell in edges if cell not in at_edge}, **{(4, 10): 1.5}}
        plain = run(job_of(foot, points=points_of(by_hand), zero=False))
        np.testing.assert_array_equal(with_zero.thickness, plain.thickness)
        for cell in edges:
            want = 1.5 if cell == (4, 10) else 0.0
            self.assertEqual(with_zero.thickness[cell], want, cell)
        for cell, value in interior.items():
            self.assertLessEqual(abs(with_zero.thickness[cell] - value), EXACT, cell)
        self.assertLessEqual(float(np.nanmax(with_zero.thickness)), 4.0)
        self.assertEqual(with_zero.data_cells, len(interior) + 1)
        self.assertEqual(with_zero.zero_cells, len(edges) - 1)
        self.assertTrue(with_zero.zero_at_edge)

    def test_the_edge_of_a_footprint_with_a_hole_includes_the_hole(self) -> None:
        """El borde de la huella incluye el de sus huecos (las celdas que tocan por un lado una celda de fuera) y el borde del
        array no cuenta como borde de la huella: la rejilla solo la recorta."""
        foot = np.ones((10, 10), dtype=bool)  # la huella llena el array entero: su borde no cuenta
        foot[4:6, 4:6] = False
        found = np.argwhere(thickness.edge_cells(foot))
        self.assertEqual({tuple(cell) for cell in found.tolist()}, set(hand_edges(foot)))
        self.assertEqual(len(found), 8)  # las 8 celdas que tocan el hueco de 2 × 2 por un lado (las de la esquina, no)


# --- Lo lejano (RF-016-21) ---------------------------------------------------------------------------------------------


class FarTest(unittest.TestCase):
    """RF-016-21: las celdas a más de la distancia máxima, con su área, su volumen y su lugar; sin impedir calcular."""

    DATA = {(3, 3): 1.0, (3, 5): 2.0, (5, 4): 3.0, (5, 6): 1.5}
    FOOT = box(2, 22, 2, 22)

    def far_by_hand(self, distance_m: float) -> tuple[list[tuple[int, int]], np.ndarray, np.ndarray]:
        d2, nearest = hand_nearest(self.DATA, GRID.shape)
        far = [(row, col) for row, col in itertools.product(range(N), range(N))
               if self.FOOT[row, col] and d2[row, col] * STEP * STEP > distance_m * distance_m]
        return far, d2, nearest

    def test_the_far_cells_with_their_area_volume_and_place(self) -> None:
        """RF-016-21, B9: con los datos en una esquina y una distancia máxima de 8 m, las celdas a más de 8 m (por fuerza bruta,
        con enteros) son lo lejano: su **área**, su **volumen** (su espesor es el del dato más próximo, que ahí es lo que cuenta:
        todas quedan fuera de la envolvente) y su **lugar** (el centro de la más lejana, la primera de arriba abajo y de oeste a
        este si hay empate) y el aviso las dice, sin impedir calcular."""
        far, d2, nearest = self.far_by_hand(8.0)
        hull = hand_hull(list(self.DATA))
        self.assertTrue(far and not any(in_hull(hull, row, col) for row, col in far))
        outcome = run(job_of(self.FOOT, points=points_of(self.DATA), distance=8.0))
        self.assertEqual(int(outcome.far.sum()), len(far))
        self.assertLessEqual(abs(outcome.far_m2 - len(far) * AREA), EXACT)
        want_volume = math.fsum(nearest[cell] for cell in far) * AREA
        self.assertLessEqual(abs(outcome.far_m3 - want_volume) / want_volume, EXACT)
        worst = max(far, key=lambda cell: (int(d2[cell]), -cell[0], -cell[1]))
        x, y = absolute(*worst)
        self.assertEqual((outcome.far_x, outcome.far_y), (x, y))
        self.assertLessEqual(abs(outcome.farthest_m - math.sqrt(float(d2[worst])) * STEP), EXACT)
        notice = [n for n in outcome.notices if n.code == FAR]
        self.assertEqual(len(notice), 1)
        values = notice[0].values
        self.assertEqual((values["area"], values["distance"]), (round(len(far) * AREA, 2), 8.0))
        self.assertEqual((values["x"], values["y"]), (round(x, 2), round(y, 2)))
        self.assertEqual(values["volume"], round(want_volume, 2))
        self.assertIn("8", notice[0].text())

    def test_the_limit_is_strict(self) -> None:
        """RF-016-21: «a más de» la distancia: una celda a **exactamente** 8 m (cuatro celdas de 2 m) del dato más próximo no es
        lejana, y la de 10 m sí; con una distancia máxima mayor que la mayor de todas, nada es lejano y no hay aviso."""
        outcome = run(job_of(self.FOOT, points=points_of({(3, 3): 1.0, (10, 10): 2.0, (14, 6): 3.0}), distance=8.0))
        self.assertFalse(outcome.far[3, 7])  # 4 celdas = 8 m
        self.assertTrue(outcome.far[3, 8])  # 5 celdas = 10 m
        everything = run(job_of(self.FOOT, points=points_of(self.DATA), distance=1000.0))
        self.assertEqual((everything.far_m2, everything.far_m3, everything.far_x, everything.far_y), (0.0, 0.0, None, None))
        self.assertEqual([n for n in everything.notices if n.code == FAR], [])

    def test_the_figures_of_what_is_far_are_the_declared_ones(self) -> None:
        """RF-016-21: ``des.bdy_far_m2`` y ``des.bdy_far_m3`` son el área y el volumen de lo lejano (CALCULADO, con el ámbito de
        la entidad) y valen 0 sin nada lejano."""
        far, _d2, nearest = self.far_by_hand(8.0)
        found = {figure.key: figure for figure in run(job_of(self.FOOT, points=points_of(self.DATA), distance=8.0)).figures}
        self.assertLessEqual(abs(found["des.bdy_far_m2"].value - len(far) * AREA), EXACT)
        self.assertLessEqual(abs(found["des.bdy_far_m3"].value - math.fsum(nearest[c] for c in far) * AREA), 1e-6)
        zero = {figure.key: figure for figure in run(job_of(self.FOOT, points=points_of(self.DATA))).figures}
        self.assertEqual((zero["des.bdy_far_m2"].value, zero["des.bdy_far_m3"].value), (0.0, 0.0))


# --- Los rechazos (RF-016-22) ------------------------------------------------------------------------------------------


class RejectionTest(unittest.TestCase):
    """RF-016-22 y D-9: sin datos, con todo lejos o sin distancia máxima, no se calcula, nombrando lo que falta."""

    FOOT = box(2, 14, 2, 14)

    def test_no_datum_inside_the_footprint_is_refused_naming_the_footprint_and_the_layer(self) -> None:
        """RF-016-22: si ningún dato cae en la huella (todos fuera, o ninguno), ``des.body_no_data`` con la huella y la capa de
        los datos; también con una huella sin celdas."""
        outside = [(*center(20, 20), 2.0), (*center(18, 4), 3.0), (*center(21, 12), 1.0)]
        cases = {"todos fuera": (self.FOOT, outside), "ninguno": (self.FOOT, []), "huella vacía": (box(0, 0, 0, 0), outside)}
        for name, (foot, rows) in cases.items():
            with self.subTest(caso=name), self.assertRaises(DesignError) as caught:
                run(job_of(foot, points=rows))
            self.assertEqual(caught.exception.code, NO_DATA)
            text = str(caught.exception)
            self.assertIn(LAYER, text)
            self.assertIn(FEATURE, text)

    def test_only_zero_data_at_the_edge_do_not_count_as_data(self) -> None:
        """RF-016-22: los ceros del borde no son datos: con ``zero_at_edge`` y ningún dato dentro, se rechaza igual."""
        with self.assertRaises(DesignError) as caught:
            run(job_of(self.FOOT, points=[(*center(20, 20), 2.0)], zero=True))
        self.assertEqual(caught.exception.code, NO_DATA)

    def test_every_cell_far_is_refused(self) -> None:
        """RF-016-22: hay datos en la huella, pero la superficie conocida solo existe lejos de ellos (a más de la distancia
        máxima): ninguna celda del cuerpo queda a menos de ella, ``des.body_all_far`` con la huella y la distancia; con el apoyo
        también cerca de un dato, se calcula."""
        foot = box(2, 22, 2, 22)
        support = np.full(GRID.shape, np.nan)
        support[14:22, 14:22] = 100.0
        data = {(3, 3): 1.0, (3, 5): 2.0, (5, 4): 3.0}
        with self.assertRaises(DesignError) as caught:
            run(job_of(foot, points=points_of(data), support=support, distance=8.0))
        self.assertEqual(caught.exception.code, ALL_FAR)
        self.assertIn(FEATURE, str(caught.exception))
        self.assertIn("8", str(caught.exception))
        support[3:5, 6:8] = 100.0
        run(job_of(foot, points=points_of(data), support=support, distance=8.0))

    def test_a_known_surface_missing_in_the_whole_footprint_is_said_as_such_and_not_as_far_from_the_data(self) -> None:
        """RF-016-22 (T48; hallazgo C-10 a de la verificación única): si lo que falta es **la superficie conocida entera** en la huella
        (los datos de espesor están dentro), el rechazo no dice «ninguna celda queda a menos de X m de los datos» (``des.body_all_far``:
        engaña, los datos están ahí): es el suyo, ``des.body_all_unsupported``, que nombra la huella y la superficie conocida; con
        una sola celda de la huella con superficie sigue siendo lo de antes (lejos de los datos)."""
        foot = box(2, 22, 2, 22)
        data = points_of({(3, 3): 1.0, (3, 5): 2.0, (5, 4): 3.0})
        with self.assertRaises(DesignError) as caught:
            run(job_of(foot, points=data, support=np.full(GRID.shape, np.nan), distance=8.0))
        error = caught.exception
        self.assertEqual(error.code, ALL_UNSUPPORTED)
        for text in (error.text_in("es"), error.text_in("en")):
            self.assertIn(FEATURE, text)
            self.assertIn("«Terreno»", text)
            self.assertNotIn("8 m", text, "no habla de la distancia a los datos")
            self.assertNotIn("{", text)
        self.assertIn("no tiene dato", error.text_in("es"))
        self.assertIn("has no data", error.text_in("en"))
        support = np.full(GRID.shape, np.nan)
        support[14:22, 14:22] = 100.0  # con superficie, pero lejos de los datos: lo de siempre
        with self.assertRaises(DesignError) as far:
            run(job_of(foot, points=data, support=support, distance=8.0))
        self.assertEqual(far.exception.code, ALL_FAR)

    def test_without_a_maximum_distance_nothing_is_computed(self) -> None:
        """D-9, RF-015-08: la distancia máxima no tiene valor por defecto: sin ella, ``des.entity_param_missing`` con la clave de
        la entidad **al llamar** (antes de calcular nada); con 0 o negativa, ``des.entity_param_range``."""
        data = points_of({(5, 5): 1.0, (8, 8): 2.0, (10, 4): 3.0})
        with self.assertRaises(DesignError) as caught:
            thickness.body_steps(job_of(self.FOOT, points=data, distance=None))
        self.assertEqual(caught.exception.code, "des.entity_param_missing")
        self.assertIn("des.body.bdy_001.max_distance_m", str(caught.exception))
        for bad in (0.0, -3.0):
            with self.subTest(valor=bad), self.assertRaises(DesignError) as ranged:
                thickness.body_steps(job_of(self.FOOT, points=data, distance=bad))
            self.assertEqual(ranged.exception.code, "des.entity_param_range")

    def test_a_negative_thickness_does_not_enter_the_job(self) -> None:
        """RF-016-01, RF-015-08: un dato de espesor negativo o no finito no entra en el trabajo (``ValueError``: la preparación
        de la orden lo rechaza antes con capa, entidad, campo y valor); un polígono tampoco."""
        for rows in ([(*center(5, 5), -0.1)], [(*center(5, 5), np.nan)], [(*center(5, 5), np.inf)]):
            with self.subTest(dato=rows[0][2]), self.assertRaises(ValueError):
                job_of(self.FOOT, points=rows)
        with self.assertRaises(ValueError):
            job_of(self.FOOT, polygons=[((ring(3, 6, 3, 6),), -2.0)])


# --- La superficie y las cifras ----------------------------------------------------------------------------------------


class SurfaceTest(unittest.TestCase):
    """RF-016-01, RF-016-20: «sobre una base», la superficie de la cadena es máx(partida, techo) en la huella admitida;
    «bajo un techo» no cambia la superficie."""

    FOOT = box(3, 17, 3, 17)
    DATA = {(5, 5): 2.0, (5, 14): 3.0, (14, 6): 1.0, (13, 13): 2.5}

    def scene(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Un apoyo en pendiente, una partida que lo cubre en parte (un montón de 4 m sobre la columna 10 a 12) y el relleno
        admitido solo en las filas 3 a 10."""
        rows, cols = np.indices(GRID.shape)
        support = 100.0 + 0.25 * cols - 0.125 * rows
        start = support.copy()
        start[:, 10:13] += 4.0
        fill = np.zeros(GRID.shape, dtype=bool)
        fill[3:11, :] = True
        return support, start, fill

    def test_on_a_base_the_surface_is_the_maximum_where_the_fill_is_admitted(self) -> None:
        """RF-016-01, RF-016-20, RF-015-06: en las celdas de la huella con relleno admitido, ``máx(partida, apoyo + espesor)``;
        en todas las demás, la partida **bit a bit** (también dentro de la huella donde no se admite); el techo es el apoyo más
        el espesor y la base, el apoyo; cuenta cada celda a mano."""
        support, start, fill = self.scene()
        outcome = run(job_of(self.FOOT, points=points_of(self.DATA), support=support, sense="on_base", start=start, fill=fill))
        t = outcome.thickness
        for row, col in itertools.product(range(N), range(N)):
            if self.FOOT[row, col]:
                self.assertEqual(outcome.top[row, col], support[row, col] + t[row, col])
                self.assertEqual(outcome.base[row, col], support[row, col])
            else:
                self.assertTrue(np.isnan(outcome.base[row, col]) and np.isnan(outcome.top[row, col]))
            want = start[row, col]
            if self.FOOT[row, col] and fill[row, col]:
                want = max(start[row, col], support[row, col] + t[row, col])
            self.assertEqual(outcome.surface[row, col], want, (row, col))
        self.assertTrue(np.any(outcome.surface > start))  # algo sube
        self.assertTrue(np.any(outcome.surface[self.FOOT & ~fill] == start[self.FOOT & ~fill]))
        self.assertTrue(np.array_equal(outcome.surface[~self.FOOT], start[~self.FOOT]))

    def test_under_a_roof_the_surface_does_not_change(self) -> None:
        """RF-016-20 («bajo un techo»): no hay superficie nueva (``None``: no encadena); el techo es la superficie conocida y la
        base, el techo menos el espesor, con base ≤ techo en todas las celdas."""
        support, _start, _fill = self.scene()
        outcome = run(job_of(self.FOOT, points=points_of(self.DATA), support=support, sense="under_roof"))
        self.assertIsNone(outcome.surface)
        body = self.FOOT
        np.testing.assert_array_equal(outcome.top[body], support[body])
        np.testing.assert_array_equal(outcome.base[body], support[body] - outcome.thickness[body])
        self.assertTrue(np.all(outcome.base[body] <= outcome.top[body]))
        with self.assertRaises(ValueError):
            outcome.compose(support)

    def test_the_body_exists_only_where_the_known_surface_has_data(self) -> None:
        """Donde la superficie conocida no tiene dato no hay cuerpo (ni espesor, base o techo, ni cuenta en su volumen): la
        huella entera se interpola y esas celdas se cuentan aparte."""
        support, _start, _fill = self.scene()
        support[6:9, 6:9] = np.nan
        outcome = run(job_of(self.FOOT, points=points_of(self.DATA), support=support))
        gap = np.zeros(GRID.shape, dtype=bool)
        gap[6:9, 6:9] = True
        self.assertEqual(outcome.unsupported_cells, 9)
        self.assertTrue(np.all(np.isnan(outcome.thickness[gap])))
        self.assertFalse(np.any(outcome.body[gap]))
        self.assertEqual(int(outcome.body.sum()), int(self.FOOT.sum()) - 9)
        want = math.fsum(outcome.thickness[outcome.body].ravel().tolist()) * AREA
        self.assertLessEqual(abs(outcome.volume_m3 - want) / want, EXACT)

    def test_compose_puts_the_work_window_back_into_the_whole_surface(self) -> None:
        """La superficie entera que deja el cuerpo «sobre una base»: una rejilla **nueva** igual a la partida con la ventana de
        trabajo sustituida; no modifica la partida."""
        support, start, fill = self.scene()
        whole = run(job_of(self.FOOT, points=points_of(self.DATA), support=support, sense="on_base", start=start, fill=fill))
        before = start.copy()
        composed = whole.compose(start)
        np.testing.assert_array_equal(start, before)
        np.testing.assert_array_equal(composed, whole.surface)  # la ventana es la rejilla entera
        self.assertFalse(np.shares_memory(composed, start))


class FiguresTest(unittest.TestCase):
    """RF-016-20: el volumen y el espesor máximo con su lugar; las cifras declaradas (plan 016 §5.2.3)."""

    FOOT = box(3, 17, 3, 17)
    DATA = {(5, 5): 2.0, (5, 14): 3.5, (14, 6): 1.0, (13, 13): 2.5}

    def test_the_volume_and_the_maximum_thickness_with_its_place(self) -> None:
        """RF-016-20: el volumen es la suma de los espesores de la huella por el área de la celda (a ≤ 10⁻⁹ relativo) y el
        espesor máximo, el mayor dato (3,5 m: el interpolado no lo pasa) con el centro de su celda."""
        outcome = run(job_of(self.FOOT, points=points_of(self.DATA)))
        want = math.fsum(outcome.thickness[self.FOOT].ravel().tolist()) * AREA
        self.assertLessEqual(abs(outcome.volume_m3 - want) / want, EXACT)
        self.assertEqual(outcome.thickness_max_m, 3.5)
        # El lugar: la primera celda (de arriba abajo y de oeste a este) con 3,5 m. Dentro de la envolvente solo el dato la
        # tiene (una combinación convexa no llega al mayor en otro sitio); fuera, el más próximo.
        _d2, nearest = hand_nearest(self.DATA, GRID.shape)
        hull = hand_hull(list(self.DATA))
        first = next((row, col) for row, col in itertools.product(range(N), range(N)) if self.FOOT[row, col]
                     and ((row, col) == (5, 14) or (not in_hull(hull, row, col) and nearest[row, col] == 3.5)))
        self.assertEqual((outcome.thickness_max_x, outcome.thickness_max_y), center(*first))

    def test_a_constant_thickness_gives_the_volume_by_hand(self) -> None:
        """RF-016-20: un espesor constante de 2,5 m sobre una huella de 6 × 8 celdas de 2 m: 48 celdas · 4 m² · 2,5 m =
        480 m³, exactos, y el espesor máximo es 2,5 m (el primer lugar de arriba abajo y de oeste a este)."""
        foot = box(5, 11, 5, 13)
        rows = [(*center(5, 5), 2.5), (*center(10, 12), 2.5), (*center(5, 12), 2.5), (*center(10, 5), 2.5)]
        outcome = run(job_of(foot, points=rows))
        self.assertEqual(outcome.volume_m3, 480.0)
        self.assertEqual((outcome.thickness_max_m, outcome.thickness_max_x, outcome.thickness_max_y),
                         (2.5, *center(5, 5)))

    def test_the_declared_figures(self) -> None:
        """Plan 016 §5.2.3: ``des.bdy_volume_m3``, ``des.bdy_thickness_max_m``, ``des.bdy_far_m2``, ``des.bdy_far_m3`` y
        ``des.bdy_ignored``, en ese orden, CALCULADO, con el ámbito de la entidad (``BDY-001``) y su unidad; ``des.bdy_ignored``
        es el recuento de datos fuera de la huella."""
        rows = [*points_of(self.DATA), (*center(20, 20), 9.0)]
        outcome = run(job_of(self.FOOT, points=rows))
        found = {figure.key: figure for figure in outcome.figures}
        self.assertEqual(list(found), [figure.key for figure in provenance.BODY_FIGURES])
        self.assertEqual(found["des.bdy_ignored"].value, 1)
        self.assertEqual(found["des.bdy_thickness_max_m"].value, 3.5)
        self.assertEqual(found["des.bdy_volume_m3"].unit, "m3")
        scopes = [dict(figure.scope) for figure in found.values()]
        self.assertTrue(all(scope == scopes[0] for scope in scopes))
        self.assertEqual(scopes[0][provenance.ENTITY_SCOPE_KEY], "BDY-001")
        corners = [(*center(5, 5), 2.5), (*center(10, 12), 2.5), (*center(5, 12), 2.5), (*center(10, 5), 2.5)]
        self.assertIn("480", thickness.compute_body(job_of(box(5, 11, 5, 13), points=corners)).message)


# --- Los pasos y la ventana --------------------------------------------------------------------------------------------


class StepsTest(unittest.TestCase):
    """RNF-016-03, A0: por pasos, la ventana de trabajo da lo mismo que la rejilla entera y ninguna entrada se modifica."""

    DATA = {(9, 9): 2.0, (9, 14): 3.0, (13, 10): 1.0, (12, 15): 2.5, (11, 12): 4.0}
    FOOT = box(8, 16, 8, 17)

    def test_the_steps_end_with_the_outcome_of_the_one_shot_call(self) -> None:
        """Por pasos (``budget_s`` mínimo: una unidad por paso), varios ``Progress`` de la fase ``body`` y el último, con el
        :class:`BodyOutcome` **idéntico**, bit a bit, al de una vez."""
        job = job_of(self.FOOT, points=points_of(self.DATA))
        steps = list(thickness.body_steps(job, budget_s=1e-9))
        self.assertGreaterEqual(len(steps), 4)
        self.assertTrue(all(step.phase == "body" for step in steps))
        self.assertEqual([step.done for step in steps], sorted(step.done for step in steps))
        self.assertTrue(all(step.result is None for step in steps[:-1]))
        last, once = steps[-1].result, run(job)
        for name in ("thickness", "base", "top", "far", "body"):
            np.testing.assert_array_equal(getattr(last, name), getattr(once, name), name)
        self.assertEqual((last.volume_m3, last.far_m3, last.ignored), (once.volume_m3, once.far_m3, once.ignored))

    def test_closing_midway_leaves_nothing_and_modifies_nothing(self) -> None:
        """RNF-016-03: cerrar el generador a mitad no deja nada ni toca ninguna entrada (apoyo, huella, datos y valores)."""
        job = job_of(self.FOOT, points=points_of(self.DATA), zero=True)
        before = (job.support.copy(), job.footprint.copy(), job.data.points.copy(), dict(job.values))
        steps = thickness.body_steps(job, budget_s=1e-9)
        next(steps)
        next(steps)
        steps.close()
        np.testing.assert_array_equal(job.support, before[0])
        np.testing.assert_array_equal(job.footprint, before[1])
        np.testing.assert_array_equal(job.data.points, before[2])
        self.assertEqual(dict(job.values), before[3])

    def test_the_work_window_gives_the_same_bits_as_the_whole_grid(self) -> None:
        """A0: la ventana que da ``body_window`` (la caja de la huella y una celda más) da el mismo espesor, base, techo, lejanía y
        cifras, **bit a bit**, que la rejilla entera; ``compose`` pone la superficie de la ventana en la entera; con ceros en el
        borde y datos fuera de la ventana, lo mismo."""
        rows = [*points_of(self.DATA), (*center(20, 20), 9.0)]
        support = 100.0 + 0.5 * np.indices(GRID.shape)[1]
        for sense, zero in itertools.product(("under_roof", "on_base"), (False, True)):
            with self.subTest(sentido=sense, ceros=zero):
                whole = run(job_of(self.FOOT, points=rows, support=support, sense=sense, zero=zero, distance=6.0))
                window = thickness.body_window(self.FOOT, GRID)
                self.assertEqual(window, (slice(7, 17), slice(7, 18)))
                cut: Any = (window[0], window[1])
                part = job_of(self.FOOT[cut], points=rows, support=support[cut], sense=sense, zero=zero, distance=6.0,
                              region=window, grid=GRID, start=None if sense == "under_roof" else support[cut].copy(),
                              fill=None if sense == "under_roof" else np.ones(self.FOOT[cut].shape, dtype=bool))
                small = run(part)
                self.assertEqual(small.window, window)
                for name in ("thickness", "base", "top", "far", "body"):
                    np.testing.assert_array_equal(getattr(small, name), getattr(whole, name)[cut], name)
                self.assertEqual((small.far_m2, small.ignored, small.thickness_max_m, small.thickness_max_x,
                                  small.thickness_max_y, small.far_x, small.far_y),
                                 (whole.far_m2, whole.ignored, whole.thickness_max_m, whole.thickness_max_x,
                                  whole.thickness_max_y, whole.far_x, whole.far_y))
                # Las sumas por bandas de filas solo coinciden bit a bit si las bandas son las mismas: ≤ 10⁻¹² relativo.
                self.assertLessEqual(abs(small.volume_m3 - whole.volume_m3) / whole.volume_m3, 1e-12)
                self.assertLessEqual(abs(small.far_m3 - whole.far_m3), 1e-12 * max(whole.far_m3, 1.0))
                if sense == "on_base":
                    np.testing.assert_array_equal(small.compose(support), whole.surface)

    def test_the_window_must_hold_the_footprint(self) -> None:
        """Una ventana que corta la huella (sin estar en el borde de la rejilla) o una forma que no casa son errores del
        programa; ``body_window`` de una huella sin celdas es ``None``."""
        window = thickness.body_window(self.FOOT, GRID)
        tight = (slice(8, 16), slice(8, 17))
        with self.assertRaises(ValueError):
            job_of(self.FOOT[tight], points=points_of(self.DATA), support=np.full((8, 9), 100.0), region=tight)
        with self.assertRaises(ValueError):
            job_of(self.FOOT[window], points=points_of(self.DATA), region=window)  # el apoyo es de la rejilla
        self.assertIsNone(thickness.body_window(np.zeros(GRID.shape, dtype=bool), GRID))

    def test_the_job_is_checked(self) -> None:
        """Errores del programa: un código que no es el de un cuerpo, un valor que no es de él, un cuerpo «sobre una base» sin
        partida o sin relleno admitido y celdas no cuadradas."""
        foot = box(8, 16, 8, 17)
        good = job_of(foot, points=points_of(self.DATA))
        for change in ({"code": "PLT-001"}, {"code": "BDY-1"}, {"values": {"width_m": 3.0}}):
            with self.subTest(cambio=change), self.assertRaises(ValueError):
                dataclasses.replace(good, **change)
        with self.assertRaises(ValueError):  # «sobre una base» sin partida ni relleno admitido
            thickness.BodyJob(request("on_base"), "BDY-001", GRID, sdata.CRS, sdata.VERTICAL, good.support, foot,
                              good.data, good.values)
        slim = gis.Grid(GRID.west, GRID.north, 2.0, 3.0, N, N)
        with self.assertRaises(ValueError):
            job_of(foot, points=points_of(self.DATA), grid=slim)


# --- El escalón del borde (RF-015-13, RF-016-20; T46, hallazgo C-1) -----------------------------------------------------


EDGE_STEP = "des.body_edge_step"


def hand_step(footprint: np.ndarray, support: np.ndarray, start: np.ndarray, fill: np.ndarray, thick: np.ndarray
              ) -> tuple[float, tuple[int, int]] | None:
    """El mayor escalón del borde a mano: de las celdas del borde de la huella (:func:`hand_edges`: sus cuatro vecinas) con cuerpo y con
    relleno admitido, lo que sube la superficie sobre la partida (``máx(partida, apoyo + espesor) − partida``, en un bucle), el mayor
    y la **primera** celda (de arriba abajo y de oeste a este) que lo tiene; ``None`` si ninguna sube."""
    best: tuple[float, tuple[int, int]] | None = None
    for row, col in hand_edges(footprint):
        if not fill[row, col] or math.isnan(float(thick[row, col])):
            continue
        rise = max(float(start[row, col]), float(support[row, col] + thick[row, col])) - float(start[row, col])
        if rise > 0.0 and (best is None or rise > best[0]):
            best = (rise, (row, col))
    return best


class EdgeStepTest(unittest.TestCase):
    """RF-015-13, RF-016-20 (T46, hallazgo C-1; decisión de la sesión principal, 19/11/2026): un cuerpo «sobre una base» cuyo espesor en el
    borde de la huella no es 0 termina en un escalón (la sonda de C: 5 m con el borde recto, 80 de 80 parejas con 5,0 m, sin aviso); el
    resumen lo dice con **un renglón informativo** (``des.body_edge_step``, una nota: no un aviso), con el mayor escalón y su lugar, sin
    parámetros nuevos del borde y sin cambiar nada de lo que anota la operación. Con «cero en el borde» no sale."""

    FOOT = box(5, 11, 5, 13)
    CORNERS = ((5, 5), (5, 12), (10, 5), (10, 12))

    def corners(self, value: float) -> np.ndarray:
        """Cuatro datos del mismo espesor, uno por esquina de la huella: el espesor es ``value`` en toda ella."""
        return points_of({cell: value for cell in self.CORNERS})

    def told(self, outcome: Any) -> list[Any]:
        return [notice for notice in outcome.notices if notice.code == EDGE_STEP]

    def test_a_straight_edge_of_5_m_is_told_with_its_step_and_its_place(self) -> None:
        """RF-015-13, RF-016-20: un cuerpo de 5,0 m con el borde recto (la sonda p9b de C) deja **un** renglón: el cuerpo de la
        entidad, el escalón (5,0 m) y el lugar de la primera celda del borde con él (la esquina noroeste), que es una nota, no un aviso."""
        outcome = run(job_of(self.FOOT, points=self.corners(5.0), sense="on_base"))
        (found,) = self.told(outcome)
        self.assertEqual(found.severity, "note")
        x, y = center(5, 5)
        self.assertEqual(dict(found.values), {"entity": "Cuerpo A", "step": 5.0, "x": round(x, 2), "y": round(y, 2)})
        self.assertEqual(hand_step(self.FOOT, np.full(GRID.shape, 100.0), np.full(GRID.shape, 100.0),
                                   np.ones(GRID.shape, dtype=bool), outcome.thickness), (5.0, (5, 5)))
        self.assertEqual([item.code for item in outcome.notices if item.severity == "warning"], [], "no es un aviso")

    def test_the_text_is_in_both_languages_and_names_the_step_and_the_place(self) -> None:
        """Principio 10, RF-016-20: el renglón dice en español y en inglés el cuerpo, el escalón de su borde y su lugar, sin marcadores
        por llenar."""
        (found,) = self.told(run(job_of(self.FOOT, points=self.corners(5.0), sense="on_base")))
        x, y = center(5, 5)
        es, en = found.text("es"), found.text("en")
        for text in (es, en):
            self.assertNotIn("{", text)
            self.assertIn("«Cuerpo A»", text)
        self.assertIn("escalón de hasta 5,00 m", es)
        self.assertIn("step of up to 5.00 m", en)
        self.assertIn("x = ", es)
        self.assertIn(f"x = {round(x, 2):,.1f} m", en)
        self.assertIn(f"y = {round(y, 2):,.1f} m", en)

    def test_the_step_is_what_the_surface_rises_at_the_edge_where_the_fill_is_admitted(self) -> None:
        """RF-015-13, RF-016-20: con un apoyo en pendiente, una partida con un montón de 4 m (que se come parte del espesor) y el relleno
        admitido solo en las filas 3 a 10, el escalón es lo que **sube la superficie** en las celdas del borde (el mayor y la primera
        celda que lo tiene, contra un bucle de Python): ni donde el montón ya cubre el espesor (no se crea pared) ni donde no se admite
        relleno, aunque ahí el espesor sea el mayor de todos."""
        rows, cols = np.indices(GRID.shape)
        support = 100.0 + 0.25 * cols - 0.125 * rows
        start = support.copy()
        start[:, 10:13] += 4.0
        fill = np.zeros(GRID.shape, dtype=bool)
        fill[3:11, :] = True
        foot = box(3, 17, 3, 17)
        data = {(5, 5): 2.0, (5, 14): 3.0, (16, 8): 9.0, (13, 13): 2.5, (3, 11): 3.5}
        outcome = run(job_of(foot, points=points_of(data), support=support, sense="on_base", start=start, fill=fill))
        wanted = hand_step(foot, support, start, fill, outcome.thickness)
        self.assertIsNotNone(wanted)
        assert wanted is not None
        step, (row, col) = wanted
        self.assertLessEqual(row, 10, "el mayor escalón está donde se admite el relleno")
        self.assertLess(step, outcome.thickness_max_m, "hay más espesor donde no se admite relleno (el sur): no cuenta")
        self.assertEqual(float(outcome.surface[3, 11] - start[3, 11]), 0.0, "el montón de 4 m cubre el dato de 3,5 m: no hay pared")
        (found,) = self.told(outcome)
        x, y = center(row, col)
        self.assertAlmostEqual(float(found.values["step"]), round(step, 2), places=9)
        self.assertEqual((found.values["x"], found.values["y"]), (round(x, 2), round(y, 2)))

    def test_without_a_step_at_the_edge_nothing_is_said(self) -> None:
        """RF-016-20: con un espesor de 0 m en todas las celdas del borde (datos de 0 m en ellas y un montículo dentro) el cuerpo
        termina a ras: ningún renglón, aunque el espesor máximo sea de 4 m."""
        edge = {cell: 0.0 for cell in hand_edges(self.FOOT)}
        outcome = run(job_of(self.FOOT, points=points_of({**edge, (8, 9): 4.0}), sense="on_base"))
        self.assertEqual(outcome.thickness_max_m, 4.0)
        self.assertEqual(self.told(outcome), [])

    def test_with_zero_at_the_edge_it_is_not_given(self) -> None:
        """RF-016-20, decisión de la sesión principal: con «cero en el borde» el renglón no sale, sea cual sea el espesor del borde; con
        él falso, el mismo cuerpo lo da."""
        with_zero = run(job_of(self.FOOT, points=self.corners(5.0), sense="on_base", zero=True))
        self.assertEqual(self.told(with_zero), [])
        self.assertEqual(len(self.told(run(job_of(self.FOOT, points=self.corners(5.0), sense="on_base", zero=False)))), 1)

    def test_under_a_roof_the_body_does_not_change_the_surface_and_does_not_say_it(self) -> None:
        """RF-016-20: «bajo un techo» no cambia la superficie: no deja ninguna pared y no hay renglón."""
        self.assertEqual(self.told(run(job_of(self.FOOT, points=self.corners(5.0), sense="under_roof"))), [])

    def test_what_rounds_to_zero_at_the_centimetre_is_not_a_step(self) -> None:
        """RF-016-20: el escalón se enseña al centímetro: un espesor de 4 mm en el borde no es un escalón («hasta 0,00 m») y uno de 6 mm
        sí («0,01 m»)."""
        self.assertEqual(self.told(run(job_of(self.FOOT, points=self.corners(0.004), sense="on_base"))), [])
        (found,) = self.told(run(job_of(self.FOOT, points=self.corners(0.006), sense="on_base")))
        self.assertEqual(found.values["step"], 0.01)

    def test_the_work_window_gives_the_same_notice_as_the_whole_grid(self) -> None:
        """A0, RF-016-20: con la ventana de trabajo (la huella y una celda más) el renglón es el mismo que con la rejilla entera, con
        y sin «cero en el borde»; el borde del array no es borde de la huella."""
        window = thickness.body_window(self.FOOT, GRID)
        assert window is not None
        cut: Any = (window[0], window[1])
        support = 100.0 + 0.5 * np.indices(GRID.shape)[1]
        for zero in (False, True):
            with self.subTest(ceros=zero):
                whole = run(job_of(self.FOOT, points=self.corners(3.0), support=support, sense="on_base", zero=zero))
                part = run(job_of(self.FOOT[cut], points=self.corners(3.0), support=support[cut], sense="on_base", zero=zero,
                                  region=window, start=support[cut].copy(), fill=np.ones(self.FOOT[cut].shape, dtype=bool)))
                self.assertEqual(self.told(part), self.told(whole))
                self.assertEqual(len(self.told(whole)), 0 if zero else 1)


if __name__ == "__main__":
    unittest.main()

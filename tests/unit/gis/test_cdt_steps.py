# SPDX-License-Identifier: GPL-3.0-or-later
"""``PureTriangulator.triangulate_steps``: la triangulación por pasos de 256 puntos (spec 016, T24; HU-016-4; RF-016-20;
RNF-016-02, RNF-016-03; plan 016 §2.1, §5.4 A11, §5.7 P-7, §7.3, §8).

La triangulación de Delaunay de ``gis.cdt`` no cedía el control: 0,45 s con 8.000 puntos colineales (plan §2.1), y el hilo de
Blender no puede estar más de 0,2 s en una llamada (RNF-016-03). ``triangulate_steps`` es un generador que **cede cada
:data:`gis.cdt.STEP_POINTS` (256) puntos** y devuelve lo que devolvía ``triangulate``, con la **misma salida bit a bit**; el
contrato ``gis.ports.Triangulator`` no cambia y ``triangulate`` es hoy ese mismo generador agotado, así que:

- la igualdad con ``triangulate`` se prueba **además** contra los hashes que dio el código de antes de la T24 (``6979f37``:
  las 200 nubes de ``test_cdt_pure.py``, la malla regular con y sin restricción, 6.000 datos en secciones diagonales y 8.000
  puntos colineales con uno fuera de la recta): una refactorización que cambie un solo triángulo cae aquí;
- los errores (menos de 3 puntos, alineados, repetidos, una arista obligatoria que pasa por un vértice o dos que se cruzan)
  salen **al avanzar** el generador, con el mismo código, campo y valor que ``triangulate``;
- el avance y la cancelación del trabajo ``gis_triangulate`` (RF-006-28) siguen funcionando, y cerrar a mitad no deja nada.
"""

from __future__ import annotations

import hashlib
import time
import unittest
from collections.abc import Generator
from typing import Any
from unittest import mock

import numpy as np

from tests.support.package import import_geoblender
from tests.unit.gis import test_cdt_pure as pure

cdt = import_geoblender("gis.cdt")
ports = import_geoblender("gis.ports")
worker_api = import_geoblender("jobs.worker_api")

NO_EDGES = pure.NO_EDGES
LIMIT_S = 0.2
"""RNF-016-03: ninguna llamada del hilo de Blender dura más."""
# Los hashes de lo que dio ``triangulate`` ANTES de la T24 (código de 6979f37): sha256 de la forma y los bytes de cada salida.
BEFORE_CLOUDS = "d571bb346ad011c0294a3985407a28349f479efb2a4af2e110a5733eb57b848b"
BEFORE_SECTIONS = "8764159c064fe2b05f0dc9feb5fdd0940a0c6a7fa63f3e2d2e0873c4bdad6417"
BEFORE_COLLINEAR = "0d010b679a1f208d1ed2445003e381180272f8bfa225b3d2e5b972baa795f9d7"
BEFORE_GRID = "4f5959f01e63fc56fcda309d43fe553ddead7ec2a995686b657261ed49de5561"


def digest(arrays: list[np.ndarray]) -> str:
    """El sha256 de la forma y los bytes de cada array."""
    hasher = hashlib.sha256()
    for array in arrays:
        flat = np.ascontiguousarray(array)
        hasher.update(str(flat.shape).encode())
        hasher.update(flat.tobytes())
    return hasher.hexdigest()


def run_steps(work: Generator[None, None, Any]) -> tuple[Any, list[float]]:
    """Agota ``work``: lo que devuelve y lo que dura cada llamada (``next``), en segundos."""
    laps: list[float] = []
    while True:
        started = time.perf_counter()
        try:
            next(work)
        except StopIteration as done:
            laps.append(time.perf_counter() - started)
            return done.value, laps
        laps.append(time.perf_counter() - started)


def run_units(work: Generator[None, None, Any]) -> tuple[Any, int]:
    """Agota ``work``: lo que devuelve y cuántas veces cedió."""
    units = 0
    while True:
        try:
            next(work)
        except StopIteration as done:
            return done.value, units
        units += 1


def stepped(xy: np.ndarray, edges: np.ndarray = NO_EDGES, **options: Any) -> np.ndarray:
    """La triangulación por pasos, agotada."""
    return run_steps(cdt.PureTriangulator(**options).triangulate_steps(xy, edges))[0]


def clouds() -> list[tuple[np.ndarray, np.ndarray]]:
    """Las 200 nubes de ``test_cdt_pure`` (la mitad con aristas obligatorias), con sus aristas."""
    found = []
    for seed in range(pure.CLOUDS):
        xy = pure._xy(pure._random_cloud(seed))
        edges = NO_EDGES
        if seed % 2:
            edges = pure._random_constraints(np.random.default_rng(5000 + seed), xy, max(1, len(xy) // 3))
        found.append((xy, edges))
    return found


def sections() -> np.ndarray:
    """6.000 datos en 8 secciones diagonales de una ventana de 1.000 × 1.000 celdas, en unidades de celda."""
    found = []
    for k in range(8):
        t = np.arange(1000)
        r = t + k * 125 - 500
        ok = (r >= 0) & (r < 1000)
        found.append(np.column_stack([t[ok] + 0.5, -(r[ok] + 0.5)]))
    return np.vstack(found).astype(np.float64)


def collinear_plus_one() -> np.ndarray:
    """8.000 puntos en una recta y uno fuera de ella: sin él no hay triangulación; con él, el abanico desde ese punto."""
    x = np.arange(8000, dtype=np.float64)
    return np.vstack([np.column_stack([x, 2.0 * x]), [[0.0, 100.0]]])


def regular_grid() -> tuple[np.ndarray, np.ndarray]:
    cols, rows = np.meshgrid(np.arange(12), np.arange(9))
    xy = pure._xy(np.column_stack([-7999.5 + 0.5 * cols.ravel(), 5000.25 + 0.5 * rows.ravel()]))
    return xy, pure._pairs([(k * 12 + k, (k + 1) * 12 + k + 1) for k in range(8)])


class SameBitsTest(unittest.TestCase):
    """RNF-016-03, RF-016-20: la misma salida bit a bit que ``triangulate`` y que el código de antes de la T24."""

    def test_the_200_clouds_of_the_pure_triangulator(self) -> None:
        """Las 200 nubes de ``test_cdt_pure`` (con y sin aristas obligatorias): ``triangulate_steps`` y ``triangulate`` dan los
        mismos bytes (tipo, forma y orden) y los dos, los que dio el código de antes."""
        once, steps = [], []
        for number, (xy, edges) in enumerate(clouds()):
            with self.subTest(seed=number):
                first = pure._triangulate(xy, edges)
                second = stepped(xy, edges)
                self.assertEqual((second.dtype, second.shape), (first.dtype, first.shape))
                self.assertEqual(second.tobytes(), first.tobytes())
                self.assertTrue(second.flags.c_contiguous)
            once.append(first)
            steps.append(second)
        self.assertEqual(digest(once), BEFORE_CLOUDS)
        self.assertEqual(digest(steps), BEFORE_CLOUDS)

    def test_the_regular_grid_with_and_without_a_constraint(self) -> None:
        """Una malla regular (todos sus cuadrados cocirculares: el resultado depende del orden de inserción) con y sin una
        restricción en diagonal."""
        xy, diagonal = regular_grid()
        found = []
        for edges in (NO_EDGES, diagonal):
            with self.subTest(edges=len(edges)):
                first, second = pure._triangulate(xy, edges), stepped(xy, edges)
                self.assertEqual(second.tobytes(), first.tobytes())
                found.append(second)
        self.assertEqual(digest(found), BEFORE_GRID)

    def test_a_hull_edge_missed_by_the_super_triangle(self) -> None:
        """Con un supertriángulo pequeño la triangulación de Delaunay deja fuera aristas del borde y se añaden como
        restricción (A9): también por pasos."""
        with mock.patch.object(cdt, "SUPER_SCALE", 1.0):
            for seed in range(0, 40, 4):
                small = pure._xy(pure._random_cloud(seed))
                with self.subTest(seed=seed):
                    self.assertEqual(stepped(small).tobytes(), pure._triangulate(small).tobytes())

    def test_six_thousand_data_in_diagonal_sections(self) -> None:
        """Lo que triangula el cuerpo apoyado con datos en líneas (plan §5.7 P-7), en unidades de celda."""
        xy = sections()
        self.assertEqual(len(xy), 6000)
        self.assertEqual(digest([stepped(xy)]), BEFORE_SECTIONS)

    def test_eight_thousand_collinear_points(self) -> None:
        """8.000 puntos colineales y uno fuera de la recta (0,45 s de una vez, plan §2.1): la misma salida, y ninguna llamada de
        más de 0,2 s. El casco convexo de los puntos alineados cuesta 0,12 s de una vez (cada predicado cae en la aritmética
        exacta): cede cada 256 puntos de cada una de sus dos cadenas."""
        xy = collinear_plus_one()
        triangles, laps = run_steps(cdt.PureTriangulator().triangulate_steps(xy, NO_EDGES))
        self.assertEqual(digest([triangles]), BEFORE_COLLINEAR)
        self.assertEqual(len(triangles), 7999)
        self.assertGreaterEqual(len(laps), 8000 // cdt.STEP_POINTS)
        self.assertLessEqual(max(laps), LIMIT_S, f"la llamada más larga, {max(laps):.3f} s")
        _checked, units = run_units(cdt._check_input_units(xy, NO_EDGES, name="prueba@0"))
        self.assertGreaterEqual(units, 2 * (len(xy) // cdt.STEP_POINTS), "el casco cede en sus dos cadenas")

    def test_all_collinear_points_are_rejected_in_steps_too(self) -> None:
        """Puntos todos alineados (el caso de error: cada uno se comprueba con la aritmética exacta): el filtro cede cada 256 y
        el rechazo es el de siempre."""
        line = np.column_stack([np.arange(1000, dtype=np.float64), 3.0 * np.arange(1000, dtype=np.float64)])
        found, units = run_units(cdt._all_collinear_units(line, 0, 999))
        self.assertTrue(found)
        self.assertGreaterEqual(units, 1000 // cdt.STEP_POINTS)
        crooked = line.copy()
        crooked[700, 1] += 0.5  # uno fuera de la recta: el filtro lo ve de una vez
        self.assertFalse(run_units(cdt._all_collinear_units(crooked, 0, 999))[0])
        with self.assertRaises(ports.TriangulationError) as caught:
            run_steps(cdt.PureTriangulator().triangulate_steps(line, NO_EDGES))
        self.assertEqual((caught.exception.field, caught.exception.value), ("puntos", 1000))


class StepsTest(unittest.TestCase):
    """RNF-016-03: cede cada 256 puntos, también en el casco y en las aristas obligatorias; y todo lo de ``triangulate``."""

    def test_it_gives_up_control_every_256_points(self) -> None:
        """Entre dos cesiones, a lo sumo 256 puntos insertados, y los 1.000 se insertan (cada uno una vez)."""
        self.assertEqual(cdt.STEP_POINTS, 256)
        rng = np.random.default_rng(11)
        xy = pure._xy(rng.uniform(0.0, 500.0, (1000, 2)))
        inserted = []
        original = cdt._Mesh.insert

        def counting(mesh: Any, p: int, start: int) -> int:
            inserted.append(p)
            return original(mesh, p, start)

        between: list[int] = []
        with mock.patch.object(cdt._Mesh, "insert", counting):
            work = cdt.PureTriangulator().triangulate_steps(xy, NO_EDGES)
            while True:
                before = len(inserted)
                try:
                    next(work)
                except StopIteration:
                    between.append(len(inserted) - before)
                    break
                between.append(len(inserted) - before)
        self.assertEqual(len(inserted), 1000)
        self.assertEqual(sorted(inserted), list(range(1000)))
        self.assertLessEqual(max(between), 256)
        self.assertGreaterEqual(len(between), 1000 // 256 + 1)

    def test_the_constraints_and_the_hull_edges_also_give_up_control(self) -> None:
        """Cada 256 aristas obligatorias (y cada 256 del casco) hay una cesión: con 300 aristas obligatorias paralelas y
        pocos puntos, más cesiones que sin ellas."""
        columns = 301
        xy = pure._xy([(float(c), float(r)) for r in (0, 1) for c in range(columns)])
        edges = pure._pairs([(c, columns + c) for c in range(columns)])  # 301 verticales
        _plain, laps_plain = run_steps(cdt.PureTriangulator().triangulate_steps(xy, NO_EDGES))
        triangles, laps = run_steps(cdt.PureTriangulator().triangulate_steps(xy, edges))
        self.assertGreater(len(laps), len(laps_plain))
        self.assertEqual(triangles.tobytes(), pure._triangulate(xy, edges).tobytes())

    def test_the_contract_does_not_change(self) -> None:
        """El puerto ``Triangulator`` es el de siempre: ``triangulate(xy, edges)`` da los triángulos de una vez; el generador es
        una pieza más del triangulador propio, no del puerto."""
        triangulator = cdt.PureTriangulator()
        self.assertIsInstance(triangulator, ports.Triangulator)
        self.assertEqual(triangulator.name, "pure@1")
        self.assertFalse(hasattr(ports.Triangulator, "triangulate_steps"))
        work = triangulator.triangulate_steps(pure._xy([(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]), NO_EDGES)
        self.assertTrue(hasattr(work, "send"), "un generador")
        triangles, _laps = run_steps(work)
        self.assertEqual(triangles.dtype, np.int32)
        self.assertEqual(pure._canonical(triangles), {(0, 1, 2)})

    def test_the_errors_come_when_advancing_with_the_same_content(self) -> None:
        """Los datos sin triangulación dan el mismo ``TriangulationError`` (código, campo, valor y texto) que ``triangulate``,
        pero **al avanzar** el generador, antes de insertar nada."""
        line = [(-7000.0 + 0.5 * k, 3000.0 + 0.25 * k) for k in range(10)]
        cases = {
            "alineados": (pure._xy(line), NO_EDGES),
            "menos de tres": (pure._xy([(0.0, 0.0), (1.0, 1.0)]), NO_EDGES),
            "repetidos": (pure._xy([(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 0.0)]), NO_EDGES),
            "no finitos": (pure._xy([(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (float("nan"), 1.0)]), NO_EDGES),
            "pasa por un vértice": (pure._xy([(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (1.0, 1.0)]), pure._pairs([(0, 2)])),
            "se cruzan": (pure._xy([(0.0, 0.0), (2.0, 2.0), (0.0, 2.0), (2.0, 0.0), (1.0, 5.0)]), pure._pairs([(0, 1), (2, 3)])),
        }
        for name, (xy, edges) in cases.items():
            with self.subTest(caso=name):
                expected = pure._error(xy, edges)
                work = cdt.PureTriangulator().triangulate_steps(xy, edges)  # llamar no falla
                with self.assertRaises(ports.TriangulationError) as caught:
                    while True:
                        next(work)
                self.assertEqual((caught.exception.code, caught.exception.field, caught.exception.value, str(caught.exception)),
                                 (expected.code, expected.field, expected.value, str(expected)))

    def test_the_program_errors_are_the_same(self) -> None:
        """Una forma o un tipo que el contrato no admite es un error del programa, como en ``triangulate``."""
        for xy, edges, kind in ((np.zeros((4, 3)), NO_EDGES, ValueError), (np.zeros((4, 2), dtype=np.int64), NO_EDGES, TypeError),
                                (pure._xy([(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]), pure._pairs([(0, 5)]), ValueError)):
            with self.subTest(kind=kind.__name__), self.assertRaises(kind):
                run_steps(cdt.PureTriangulator().triangulate_steps(xy, edges))

    def test_progress_and_cancel_still_work(self) -> None:
        """RF-006-28: el avance (``progress``) y la cancelación (``cancelled``) del trabajo ``gis_triangulate`` siguen
        funcionando por pasos."""
        xy = pure._xy(np.random.default_rng(5).uniform(0.0, 50.0, (200, 2)))
        seen: list[float] = []
        with mock.patch.object(cdt, "PROGRESS_STEP", 16):
            stepped(xy, progress=lambda fraction, text: seen.append(fraction))
            self.assertGreater(len(seen), 5)
            self.assertEqual(seen, sorted(seen))
            self.assertEqual(seen[-1], 1.0)
            with self.assertRaises(worker_api.JobCancelled):
                stepped(xy, cancelled=lambda: True)

    def test_closing_midway_leaves_nothing_and_modifies_nothing(self) -> None:
        """Cerrar el generador a mitad no deja nada ni toca la entrada (de solo lectura)."""
        xy = pure._xy(np.random.default_rng(3).uniform(0.0, 100.0, (700, 2)))
        before = xy.tobytes()
        work = cdt.PureTriangulator().triangulate_steps(xy, NO_EDGES)
        next(work)
        next(work)
        work.close()
        self.assertEqual(xy.tobytes(), before)
        self.assertEqual(stepped(xy).tobytes(), pure._triangulate(xy).tobytes())  # y se puede volver a triangular


if __name__ == "__main__":
    unittest.main()

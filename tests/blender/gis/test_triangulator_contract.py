# SPDX-License-Identifier: GPL-3.0-or-later
"""El triangulador de Blender y el propio dan lo mismo (spec 006, T23; plan 006 §5.4 A10 y
§7.2; ADR-0021; RF-006-13).

``bl.scene.triangulator.BlenderTriangulator`` implementa el puerto ``gis.ports.Triangulator``
con ``mathutils.geometry.delaunay_2d_cdt`` (triángulos con la envolvente convexa, ``epsilon``
10⁻⁶), que trabaja con los puntos en float32 (``Vector``):

- **RF-006-13**: en 5 conjuntos aleatorios no degenerados, en coordenadas locales a ±8 km del
  origen (de 20 m a 16 km de lado, de 1.000 a 3.000 puntos, con roturas de tramos cortos
  encadenados), da el mismo array de triángulos que ``PureTriangulator`` (los dos en orden
  canónico) y las mismas aristas obligatorias; los triángulos son índices de la entrada (los
  vértices conservan sus coordenadas float64), antihorarios (normal hacia arriba) y cumplen
  ``gis.cdt.check_contract``. Un conjunto es **no degenerado** si ``PureTriangulator`` da lo
  mismo con sus coordenadas en float64 que redondeadas a float32 (0,24 mm a 8 km): ningún
  grupo de 4 puntos casi cocirculares ni ningún punto casi sobre una rotura cambia de lado al
  redondear. Se comprueba antes de comparar. En uno degenerado, la CDT de Blender da
  exactamente la triangulación de los puntos redondeados a float32, válida (con el contrato)
  para los float64.
- El contrato se comprueba **tras cada llamada** a la CDT: sin vértices nuevos ni fundidos
  (``orig_verts`` uno a uno), solo triángulos, antihorarios, sin solapes, la envolvente
  completa y cada arista obligatoria (``gis.triangulation_contract`` con el nombre del
  triangulador). Con salidas rotas a propósito y con las de Blender ante dos aristas que se
  cruzan (crea un vértice) o dos puntos distintos que coinciden en float32 (los funde).
- Lo que no tiene triangulación (menos de 3 puntos, no finitos, repetidos, alineados) da
  ``gis.triangulation_input`` sin llamar a Blender.
- El **estimador** (la CDT, unos 5,5 µs por punto según A10, más 1 µs por punto de las
  comprobaciones del contrato, medido en T23: 6,5 µs) elige la CDT en proceso si la
  estimación no pasa de ``gis.tin.blender_cdt_max_s`` (2 s: hasta 307.692 puntos; 1 s: hasta
  153.846) y el trabajo ``gis_triangulate`` por encima.

Las entradas no se modifican (arrays de solo lectura).
"""

import importlib
import math
import unittest
from types import ModuleType
from unittest import mock

import bpy
import numpy as np

from tests.support import blender_ext
from tests.support.blender_ext import module_name

SEED = 20_261_008
HALF_SIDE_M = 8_000.0
# (semilla, puntos, centro en locales (m), lado (m), tramos de rotura). El tercero (1.000
# puntos en 20 m, a 0,6 m unos de otros) con la semilla 3 es degenerado en float32 (una
# cuaterna cambia de lado al redondear 0,24 mm, y lo detecta la comprobación); con la 6, no.
SETS = (
    (1, 2_000, (0.0, 0.0), 16_000.0, 60),
    (2, 1_500, (7_880.0, -7_880.0), 200.0, 80),
    (6, 1_000, (-7_990.0, 7_990.0), 20.0, 40),
    (4, 3_000, (0.0, 0.0), 2_000.0, 100),
    (5, 2_500, (7_500.0, 7_500.0), 1_000.0, 80),
)
NEIGHBOURS = 6  # cada tramo de rotura va a uno de los 6 puntos más cercanos
MAX_CHAIN = 8  # tramos por rotura
MAX_S_KEY = "gis.tin.blender_cdt_max_s"


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def _frozen(rows, dtype) -> np.ndarray:
    array = np.array(rows, dtype=dtype)
    array.flags.writeable = False  # una entrada nunca se modifica
    return array


def _pairs(rows=()) -> np.ndarray:
    return _frozen(rows, np.int32).reshape(-1, 2)


def _cloud(rng: np.random.Generator, count: int, center, side: float) -> np.ndarray:
    """``count`` puntos al azar en el cuadrado de ``side`` centrado en ``center`` (locales)."""
    xy = rng.uniform(-side / 2.0, side / 2.0, (count, 2)) + np.asarray(center, dtype=np.float64)
    return _frozen(xy, np.float64)


def _orient(a, b, c) -> np.ndarray:
    """(b − a) × (c − a), vectorizado en la última fila de ``c`` (o de ``a`` y ``b``)."""
    return (b[..., 0] - a[..., 0]) * (c[..., 1] - a[..., 1]) - (
        b[..., 1] - a[..., 1]
    ) * (c[..., 0] - a[..., 0])


def _segment_distances(xy: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    ab = b - a
    t = np.clip(((xy - a) @ ab) / float(ab @ ab), 0.0, 1.0)
    return np.hypot(*(xy - (a + t[:, None] * ab)).T)


def _valid_segment(xy: np.ndarray, chosen: list[tuple[int, int]], i: int, j: int,
                   margin: float) -> bool:
    """El tramo i–j no repite otro, no pasa a ``margin`` o menos de otro punto y no cruza
    ningún tramo elegido (los que comparten extremo solo se tocan en él)."""
    if (min(i, j), max(i, j)) in chosen:
        return False
    distances = _segment_distances(xy, xy[i], xy[j])
    distances[[i, j]] = np.inf
    if distances.min() <= margin:
        return False
    if not chosen:
        return True
    segments = xy[np.array(chosen, dtype=np.int64)]  # (k, 2, 2)
    c, d = segments[:, 0], segments[:, 1]
    a, b = xy[i][None, :], xy[j][None, :]
    crossing = (_orient(a, b, c) * _orient(a, b, d) < 0) & (_orient(c, d, a) * _orient(c, d, b) < 0)
    return not crossing.any()


def _breaklines(rng: np.random.Generator, xy: np.ndarray, segments: int) -> np.ndarray:
    """``segments`` tramos de rotura encadenados (de 1 a ``MAX_CHAIN`` por rotura), cada uno
    hasta uno de los ``NEIGHBOURS`` puntos más cercanos, sin cruces y lejos de los demás
    puntos (1 % de la separación media)."""
    n = len(xy)
    span = xy.max(axis=0) - xy.min(axis=0)
    margin = 0.01 * math.sqrt(float(span[0] * span[1]) / n)
    chosen: list[tuple[int, int]] = []
    for _attempt in range(50 * segments):
        if len(chosen) >= segments:
            break
        current = int(rng.integers(n))
        for _step in range(int(rng.integers(1, MAX_CHAIN + 1))):
            distances = np.hypot(*(xy - xy[current]).T)
            distances[current] = np.inf
            following = int(rng.choice(np.argpartition(distances, NEIGHBOURS)[:NEIGHBOURS]))
            if not _valid_segment(xy, chosen, current, following, margin):
                break
            chosen.append((min(current, following), max(current, following)))
            current = following
            if len(chosen) >= segments:
                break
    return _pairs(chosen)


def _long_edge(xy: np.ndarray, edges: np.ndarray) -> np.ndarray:
    """``edges`` y una arista más entre dos puntos de los extremos en X que no pasa a menos de
    1 cm de otro punto ni cruza ``edges`` (la primera pareja así, de fuera hacia dentro):
    cruza muchos triángulos de Delaunay, así que solo aparece si se impone."""
    chosen = [(int(a), int(b)) for a, b in edges.tolist()]
    order = np.argsort(xy[:, 0]).tolist()
    for i in order[:40]:
        for j in order[::-1][:40]:
            if _valid_segment(xy, chosen, i, j, 0.01):
                return _pairs([*chosen, (min(i, j), max(i, j))])
    raise AssertionError("ninguna pareja de extremos sirve como arista larga")


def _undirected(tri: np.ndarray) -> set[tuple[int, int]]:
    edges = set()
    for a, b, c in np.asarray(tri).tolist():
        for u, v in ((a, b), (b, c), (c, a)):
            edges.add((min(u, v), max(u, v)))
    return edges


def _constrained(tri: np.ndarray, edges: np.ndarray) -> set[tuple[int, int]]:
    """Las aristas obligatorias que son aristas de los triángulos."""
    present = _undirected(tri)
    return {(min(a, b), max(a, b)) for a, b in np.asarray(edges).tolist()} & present


def _twice_areas(xy: np.ndarray, tri: np.ndarray) -> np.ndarray:
    p = xy[tri]
    return _orient(p[:, 0], p[:, 1], p[:, 2])


class _Spy:
    """Sustituye a ``delaunay_2d_cdt`` en el módulo del triangulador: anota cada llamada y
    devuelve la salida de la real después de pasarla por ``corrupt``."""

    def __init__(self, real, corrupt=None, *, drop_edges: bool = False) -> None:
        self.real = real
        self.corrupt = corrupt
        self.drop_edges = drop_edges
        self.calls = 0

    def __call__(self, coords, edges, faces, output_type, epsilon, need_ids=True):
        self.calls += 1
        result = self.real(coords, [] if self.drop_edges else edges, faces, output_type,
                           epsilon, need_ids)
        return result if self.corrupt is None else self.corrupt([list(item) for item in result])


class _TriangulatorTestCase(unittest.TestCase):
    """Importa la copia de pruebas de la extensión sin habilitarla."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.unload()
        blender_ext.import_root()
        cls.triangulator = _module("bl.scene.triangulator")
        cls.real_cdt = cls.triangulator.delaunay_2d_cdt
        cls.cdt = _module("gis.cdt")
        cls.ports = _module("gis.ports")
        cls.params = _module("gis.params")
        cls.messages = _module("gis.messages")

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.unload()

    def blender(self, xy, edges=None) -> np.ndarray:
        return self.triangulator.BlenderTriangulator().triangulate(
            xy, _pairs() if edges is None else edges
        )

    def pure(self, xy, edges=None) -> np.ndarray:
        return self.cdt.PureTriangulator().triangulate(xy, _pairs() if edges is None else edges)

    def spy(self, corrupt=None, *, drop_edges: bool = False) -> _Spy:
        spy = _Spy(type(self).real_cdt, corrupt, drop_edges=drop_edges)
        patcher = mock.patch.object(self.triangulator, "delaunay_2d_cdt", spy)
        patcher.start()
        self.addCleanup(patcher.stop)
        return spy


class SameAsPureTest(_TriangulatorTestCase):
    def test_port_and_name(self) -> None:
        """RF-006-13 (ADR-0021; RF-006-26): ``BlenderTriangulator`` cumple el puerto
        ``Triangulator`` y se llama ``blender-cdt@<versión de Blender>`` (va a la
        procedencia)."""
        triangulator = self.triangulator.BlenderTriangulator()
        self.assertIsInstance(triangulator, self.ports.Triangulator)
        version = ".".join(str(part) for part in bpy.app.version)
        self.assertEqual(triangulator.name, f"blender-cdt@{version}")
        self.assertEqual(self.triangulator.NAME, triangulator.name)

    def test_random_sets_match_pure(self) -> None:
        """RF-006-13: en 5 conjuntos aleatorios no degenerados a ±8 km del origen (locales),
        la CDT de Blender da el mismo array de triángulos que ``PureTriangulator`` y las
        mismas aristas obligatorias, todas presentes; antihorarios y con el contrato."""
        for index, (seed, count, center, side, segments) in enumerate(SETS, start=1):
            with self.subTest(conjunto=index):
                rng = np.random.default_rng(SEED + seed)
                xy = _cloud(rng, count, center, side)
                edges = _breaklines(rng, xy, segments)
                self.assertEqual(len(edges), segments)
                self.assertLessEqual(float(np.abs(xy).max()), HALF_SIDE_M)
                pure = self.pure(xy, edges)
                rounded = _frozen(xy.astype(np.float32).astype(np.float64), np.float64)
                self.assertTrue(np.array_equal(pure, self.pure(rounded, edges)),
                                f"el conjunto {index} es degenerado en float32: otra semilla")
                blender = self.blender(xy, edges)
                self.assertEqual(blender.dtype, np.int32)
                np.testing.assert_array_equal(blender, pure)
                wanted = {(int(a), int(b)) for a, b in edges.tolist()}
                self.assertEqual(_constrained(blender, edges), wanted)
                self.assertEqual(_constrained(pure, edges), wanted)
                self.assertTrue((_twice_areas(xy, blender) > 0.0).all())
                self.cdt.check_contract(xy, edges, blender, name="prueba@0")
                print(f"\nconjunto {index} (semilla {seed}): {count} puntos, {segments} tramos, "
                      f"lado {side:g} m, {len(blender)} triángulos iguales", end="")

    def test_degenerate_set_is_delaunay_in_float32(self) -> None:
        """RF-006-13: en un conjunto degenerado en float32 (el tercero con la semilla 3), la
        CDT de Blender da la triangulación de Delaunay restringida de los puntos redondeados
        a float32 (la de ``PureTriangulator`` sobre ellos), distinta de la de float64 pero
        válida para los puntos float64: cumple el contrato."""
        _seed, count, center, side, segments = SETS[2]
        rng = np.random.default_rng(SEED + 3)
        xy = _cloud(rng, count, center, side)
        edges = _breaklines(rng, xy, segments)
        rounded = _frozen(xy.astype(np.float32).astype(np.float64), np.float64)
        pure32 = self.pure(rounded, edges)
        self.assertFalse(np.array_equal(self.pure(xy, edges), pure32))
        blender = self.blender(xy, edges)
        np.testing.assert_array_equal(blender, pure32)
        self.cdt.check_contract(xy, edges, blender, name="prueba@0")

    def test_repeated_edges_and_types(self) -> None:
        """RF-006-13: una arista repetida (también al revés) cuenta una vez, como en
        ``PureTriangulator``; se admiten puntos float32 y aristas int64; la misma entrada da
        siempre el mismo array."""
        rng = np.random.default_rng(SEED + 10)
        xy = _cloud(rng, 300, (-4_000.0, 6_000.0), 500.0)
        edges = _breaklines(rng, xy, 20)
        expected = self.blender(xy, edges)
        repeated = _frozen(np.vstack([edges, edges[:5], edges[5:10, ::-1]]), np.int64)
        np.testing.assert_array_equal(self.blender(xy, repeated), expected)
        np.testing.assert_array_equal(self.blender(xy, edges), expected)
        single = _frozen(xy.astype(np.float32), np.float32)
        np.testing.assert_array_equal(self.blender(single, edges),
                                      self.pure(single.astype(np.float64), edges))


class ContractTest(_TriangulatorTestCase):
    """El contrato del puerto se comprueba tras cada llamada a la CDT de Blender."""

    def setUp(self) -> None:
        rng = np.random.default_rng(SEED + 20)
        self.xy = _cloud(rng, 200, (7_000.0, -7_000.0), 300.0)
        self.edges = _long_edge(self.xy, _breaklines(rng, self.xy, 15))

    def broken(self, corrupt=None, *, drop_edges: bool = False, xy=None, edges=None) -> str:
        """El texto del ``gis.triangulation_contract`` que da una llamada (una sola a la CDT)."""
        spy = self.spy(corrupt, drop_edges=drop_edges)
        with self.assertRaises(self.ports.TriangulationError) as caught:
            self.blender(self.xy if xy is None else xy, self.edges if edges is None else edges)
        self.assertEqual(spy.calls, 1)
        self.assertEqual(caught.exception.code, "gis.triangulation_contract")
        text = str(caught.exception)
        self.assertIn(self.triangulator.NAME, text)
        return text

    def test_checked_after_every_call(self) -> None:
        """RF-006-13: cada llamada a la CDT va seguida de la comprobación del contrato
        (``gis.cdt.check_output``), también cuando la salida es buena."""
        spy = self.spy()
        with mock.patch.object(self.cdt, "check_output", wraps=self.cdt.check_output) as check:
            for count in (3, 50, 200):
                self.blender(self.xy[:count], _pairs())
            self.blender(self.xy, self.edges)
        self.assertEqual(spy.calls, 4)
        self.assertEqual(check.call_count, 4)

    def test_new_or_merged_vertices_rejected(self) -> None:
        """RF-006-13 (A10): un vértice nuevo o dos fundidos (``orig_verts`` no es uno a uno)
        incumplen el contrato."""

        def new_vertex(result):
            verts, _edges, faces, origins = result[0], result[1], result[2], result[3]
            verts.append(verts[faces[0][0]].copy())
            origins.append([])
            faces[0] = [len(verts) - 1, faces[0][1], faces[0][2]]
            return tuple(result)

        def merged(result):
            verts, faces, origins = result[0], result[2], result[3]
            last = len(verts) - 1
            keep = origins[last][0]
            origins[0] = origins[0] + [keep]
            del verts[last], origins[last]
            result[2] = [[0 if v == last else v for v in face] for face in faces]
            return tuple(result)

        self.assertIn("vértice nuevo", self.broken(new_vertex))
        self.assertIn("fundió", self.broken(merged))

    def test_broken_faces_rejected(self) -> None:
        """RF-006-13: una cara que no es un triángulo, una con un vértice que no existe, una
        horaria, ninguna cara, un hueco en la envolvente o una arista obligatoria que falta
        incumplen el contrato."""

        def quad(result):
            face = result[2][0]
            other = next(v for v in result[2][1] if v not in face)
            result[2][0] = [*face, other]
            return tuple(result)

        def clockwise(result):
            result[2][0] = result[2][0][::-1]
            return tuple(result)

        def empty(result):
            result[2] = []
            return tuple(result)

        def unknown_vertex(result):
            face = result[2][0]
            result[2][0] = [face[0], face[1], len(result[0])]
            return tuple(result)

        def hole(result):  # sin un triángulo cuyos vértices están también en otros
            counts = np.bincount(np.array(result[2]).ravel())
            row = next(r for r, face in enumerate(result[2]) if counts[face].min() >= 2)
            del result[2][row]
            return tuple(result)

        self.assertIn("triángulo", self.broken(quad))
        self.assertIn("no existen", self.broken(unknown_vertex))
        self.assertIn("horario", self.broken(clockwise))
        self.assertIn("ningún triángulo", self.broken(empty))
        self.assertIn("envolvente", self.broken(hole))
        self.assertIn("falta la arista obligatoria", self.broken(drop_edges=True))

    def test_blender_outputs_rejected(self) -> None:
        """RF-006-13 (A10): la CDT de Blender con dos aristas obligatorias que se cruzan
        crea un vértice en el cruce, y con dos puntos distintos en float64 que coinciden en
        float32 (a 7 km, 0,1 mm) los funde: las dos salidas incumplen el contrato."""
        square = _frozen([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [3.0, 8.0]],
                         np.float64)
        text = self.broken(xy=square, edges=_pairs([[0, 2], [1, 3]]))
        self.assertIn("vértice nuevo", text)
        self.assertIn("(5; 5)", text)
        twins = _frozen([[7_000.0, 100.0], [7_000.0001, 100.0], [7_010.0, 100.0],
                         [7_005.0, 110.0]], np.float64)
        self.assertEqual(np.float32(twins[0, 0]), np.float32(twins[1, 0]))
        text = self.broken(xy=twins, edges=_pairs())
        self.assertIn("fundió", text)
        self.assertIn("0 y 1", text)

    def test_untriangulable_input_rejected_before_calling(self) -> None:
        """RF-006-13: menos de 3 puntos, coordenadas no finitas, puntos repetidos o todos
        alineados dan ``gis.triangulation_input`` sin llamar a la CDT; una forma, un tipo o
        un índice que el contrato no admite, ``ValueError`` o ``TypeError``."""
        spy = self.spy()
        cases = {
            "al menos 3 puntos": [[0.0, 0.0], [1.0, 0.0]],
            "no tiene coordenadas finitas": [[0.0, 0.0], [1.0, 0.0], [np.nan, 1.0]],
            "coinciden": [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 0.0]],
            "alineados": [[0.0, 0.0], [1.0, 1.0], [2.0, 2.0], [3.0, 3.0]],
        }
        for expected, rows in cases.items():
            with self.subTest(caso=expected):
                with self.assertRaises(self.ports.TriangulationError) as caught:
                    self.blender(_frozen(rows, np.float64))
                self.assertEqual(caught.exception.code, "gis.triangulation_input")
                self.assertIn(expected, str(caught.exception))
                self.assertIn(self.triangulator.NAME, str(caught.exception))
        xy = _frozen([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]], np.float64)
        with self.assertRaises(ValueError):
            self.blender(_frozen([[0.0, 0.0, 0.0]] * 3, np.float64))
        with self.assertRaises(TypeError):
            self.blender(_frozen([[0, 0], [1, 0], [0, 1]], np.int64))
        with self.assertRaises(ValueError):
            self.blender(xy, _pairs([[0, 3]]))
        self.assertEqual(spy.calls, 0)


class EstimatorTest(_TriangulatorTestCase):
    """El estimador decide entre la CDT en proceso y el trabajo ``gis_triangulate``."""

    def test_estimate_per_point(self) -> None:
        """RF-006-13 (A10): la CDT, unos 5,5 µs por punto, más 1 µs de las comprobaciones
        del contrato: 6,5 µs por punto; no admite cantidades negativas ni que no son
        enteras."""
        triangulator = self.triangulator
        estimate = triangulator.estimate_seconds
        self.assertEqual(triangulator.CDT_SECONDS_PER_POINT, 5.5e-6)
        self.assertEqual(triangulator.CHECK_SECONDS_PER_POINT, 1.0e-6)
        self.assertAlmostEqual(triangulator.SECONDS_PER_POINT, 6.5e-6, delta=1e-18)
        self.assertEqual(estimate(0), 0.0)
        self.assertAlmostEqual(estimate(200_000), 1.3, places=12)
        with self.assertRaises(ValueError):
            estimate(-1)
        with self.assertRaises(TypeError):
            estimate(1.5)

    def test_choice_around_the_limit(self) -> None:
        """RF-006-13, RF-006-28 (plan §9, D-12): CDT en proceso si la estimación no pasa de
        ``gis.tin.blender_cdt_max_s`` (2 s por defecto: hasta 307.692 puntos; con 1 s, hasta
        153.846; con 0 s, nunca) y el trabajo ``gis_triangulate`` por encima."""
        choose = self.triangulator.choose_triangulation
        self.assertEqual(self.params.default(MAX_S_KEY), 2.0)
        for limit, last in ((None, 307_692), (2.0, 307_692), (1.0, 153_846)):
            with self.subTest(limite=limit):
                inside, outside = choose(last, limit_s=limit), choose(last + 1, limit_s=limit)
                self.assertEqual((inside.points, outside.points), (last, last + 1))
                self.assertTrue(inside.in_process)
                self.assertEqual(inside.runner, self.triangulator.NAME)
                self.assertLessEqual(inside.estimate_s, inside.limit_s)
                self.assertFalse(outside.in_process)
                self.assertEqual(outside.runner, "gis_triangulate")
                self.assertEqual(outside.runner, self.triangulator.JOB_TYPE)
                self.assertGreater(outside.estimate_s, outside.limit_s)
                self.assertEqual(outside.limit_s, 2.0 if limit is None else limit)
        never = choose(3, limit_s=0.0)
        self.assertEqual((never.in_process, never.runner), (False, "gis_triangulate"))
        self.assertTrue(choose(0, limit_s=0.0).in_process)  # igual al límite: no pasa de él
        choice = choose(150_000)
        self.assertEqual((choice.points, choice.in_process), (150_000, True))
        self.assertAlmostEqual(choice.estimate_s, 0.975, places=12)

    def test_invalid_limit(self) -> None:
        """RF-006-13 (plan §9, D-12): el límite es un parámetro de 0 a 2 s; fuera de ese
        rango, o si no es un número, ``gis.param_*`` con la clave."""
        choose = self.triangulator.choose_triangulation
        for value, code in ((2.5, "gis.param_out_of_range"), (-0.1, "gis.param_out_of_range"),
                            ("1", "gis.param_not_number"), (math.nan, "gis.param_not_number")):
            with self.subTest(valor=value):
                with self.assertRaises(self.messages.GisError) as caught:
                    choose(1_000, limit_s=value)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(caught.exception.field, MAX_S_KEY)
        with self.assertRaises(ValueError):
            choose(-5)


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: GPL-3.0-or-later
"""TIN desde curvas de nivel con corrección de triángulos planos (spec 006, T20; plan 006
§5.3.2 y §5.4 A12, ``gis.tin_contours``).

- **RF-006-16**: las curvas se densifican a ≤ ``gis.tin.contour_densify_m`` y son aristas
  obligatorias del TIN; los puntos acotados son vértices. El % de planos «antes» es el de la
  triangulación de las curvas solas (la de inv. 08 §6.3); después, mientras el % no baje de
  ``gis.tin.max_flat_pct`` y queden pasadas (``gis.tin.flat_max_passes``), cada triángulo
  plano de una región plana abierta (que toca, por una arista que no es de curva, un
  triángulo con otra cota) recibe un punto en su circuncentro (o en su baricentro si el
  circuncentro cae fuera de la región) con la cota interpolada entre su curva y la cota
  vecina que alcanza la región; la corrección para también cuando ya no queda ningún plano
  así. Una cima o un fondo sin punto acotado (región cerrada) queda plana y se informa con su
  número y su área (D-6).
- **RF-006-14**: curvas que se cruzan con cotas distintas → conflicto, sin TIN.

Las entradas no se modifican (arrays de solo lectura).
"""

import math
import unittest

import numpy as np

from tests.support.package import import_geoblender

gis = import_geoblender("gis")
tin_contours = import_geoblender("gis.tin_contours")
points = import_geoblender("gis.points")
cdt = import_geoblender("gis.cdt")
georef = import_geoblender("core.georef")
worker_api = import_geoblender("jobs.worker_api")

E0, N0 = 700_000.0, 4_400_000.0
ORIGIN = georef.GeoOrigin(700_000, 4_400_000, 0)
CENTER = (E0 + 100.0, N0 + 100.0)
LEVELS = (850.0, 855.0, 860.0)
RADII = (36.0, 24.0, 12.0)
OFFSETS = (0.0, 0.03, 0.06)  # sin trapecios isósceles (cocirculares) entre anillos
SUMMIT = 863.0
CIRCLE_TRIANGLES = 243  # 2·147 − 49 − 2: 49 vértices en cada uno de los tres anillos
CIRCLE_FLAT = 47  # el 49-gono de la cima, triangulado: 49 − 2 triángulos planos


def _frozen(rows) -> np.ndarray:
    array = np.array(rows, dtype=np.float64).reshape(-1, 3)
    array.flags.writeable = False  # una entrada nunca se modifica
    return array


def _closed(line_id: str, xy, z: float, center=CENTER) -> object:
    """Curva cerrada (el primer vértice repetido al final) con vértices relativos al
    centro."""
    rows = [(center[0] + x, center[1] + y, z) for x, y in xy]
    rows.append(rows[0])
    return points.Breakline(line_id, _frozen(rows))


def _circle(radius: float, z: float, offset: float = 0.0, count: int = 49,
            center=CENTER) -> object:
    angle = offset + 2.0 * math.pi * np.arange(count) / count
    xy = np.column_stack([radius * np.cos(angle), radius * np.sin(angle)])
    return _closed(f"C{z:g}", xy, z, center)


def _circles(center=CENTER) -> list:
    return [_circle(r, z, offset, center=center)
            for r, z, offset in zip(RADII, LEVELS, OFFSETS, strict=True)]


def _square(half: float, z: float) -> object:
    """Cuadrado de lado 2·``half`` con solo sus cuatro esquinas (se densifica)."""
    return _closed(f"Q{z:g}", [(-half, -half), (half, -half), (half, half), (-half, half)], z)


def _squares() -> list:
    return [_square(60.0, 850.0), _square(40.0, 855.0), _square(20.0, 860.0)]


def _spots(*rows, center=CENTER) -> object:
    xyz = _frozen([(center[0] + x, center[1] + y, z) for x, y, z in rows])
    count = len(xyz)
    return points.PointSet(xyz, tuple(f"A{i + 1}" for i in range(count)), ("",) * count,
                           tuple(range(2, count + 2)))


def _build(contours, spots=None, triangulator=None, **options):
    return gis.tin_from_contours(list(contours), spot_heights=spots,
                                 triangulator=triangulator or cdt.PureTriangulator(),
                                 origin=ORIGIN, **options)


def _ring_vertices(lines) -> np.ndarray:
    """Los vértices de las curvas sin el de cierre, en orden."""
    return np.concatenate([line.xyz[:-1] for line in lines])


def _shoelace(xy: np.ndarray) -> float:
    rel = xy - xy.mean(axis=0)
    x, y = rel[:, 0], rel[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y)))


def _normal_z(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    a, b, c = (vertices[faces[:, k]] for k in range(3))
    u, v = b - a, c - a
    return u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]


def _edge_set(faces: np.ndarray) -> set[tuple[int, int]]:
    pairs = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    pairs.sort(axis=1)
    return set(map(tuple, pairs.tolist()))


def _flat(tin) -> np.ndarray:
    z = tin.vertices[:, 2][tin.faces]
    return (z[:, 0] == z[:, 1]) & (z[:, 1] == z[:, 2])


class _Recording:
    """Triangulador que guarda lo que recibe y delega en ``PureTriangulator``."""

    name = "recording@1"

    def __init__(self) -> None:
        self.calls: list[tuple[np.ndarray, np.ndarray]] = []

    def triangulate(self, xy_local: np.ndarray, edges: np.ndarray) -> np.ndarray:
        self.calls.append((xy_local.copy(), edges.copy()))
        return cdt.PureTriangulator().triangulate(xy_local, edges)


class CirclesTest(unittest.TestCase):
    """RF-006-16 con las curvas concéntricas de inv. 08 §6.3 (850, 855 y 860 m)."""

    def test_spot_height_removes_the_flat_summit(self) -> None:
        """Con el punto acotado de 863 m: antes, 47 de 243 planos (19,3 %, la cima de las
        curvas solas); después, ninguno. Vértices de las curvas bit a bit (origen 3), el
        punto acotado (origen 0) y los 147 tramos de curva como aristas obligatorias."""
        lines = _circles()
        recording = _Recording()
        tin, report = _build(lines, _spots((0.0, 0.0, SUMMIT)), recording, name="cerro")
        self.assertEqual(report.flat_pct_before, 100.0 * CIRCLE_FLAT / CIRCLE_TRIANGLES)
        self.assertEqual((report.flat_pct, tin.flat_faces, report.points_added), (0.0, 0, 0))
        self.assertEqual((report.unresolved_flat_regions, report.unresolved_flat_area_m2),
                         (0, 0.0))
        self.assertEqual(report.notes, ())
        self.assertEqual((report.vertices, report.triangles), (148, 245))
        self.assertEqual(report.input_points, 3 * 50 + 1)
        want = np.concatenate([_spots((0.0, 0.0, SUMMIT)).xyz, _ring_vertices(lines)])
        self.assertEqual(tin.vertices.tobytes(), want.tobytes())
        self.assertEqual(tin.vertex_source.tolist(), [0] + [3] * 147)
        self.assertEqual(report.constraint_edges, 147)
        edges = _edge_set(tin.faces)
        self.assertTrue(set(map(tuple, tin.constraint_edges.tolist())) <= edges)
        self.assertTrue((_normal_z(tin.vertices, tin.faces) > 0.0).all())
        # Antes, las curvas solas; después, también el punto acotado, en locales.
        self.assertEqual([len(xy) for xy, _edges in recording.calls], [147, 148])
        local = georef.world_to_local(want[:, :2], ORIGIN)
        self.assertEqual(recording.calls[1][0].tobytes(), local.tobytes())
        self.assertEqual(recording.calls[0][0].tobytes(), local[1:].tobytes())
        self.assertEqual(report.triangulator, "recording@1")

    def test_summit_without_spot_height_stays_flat(self) -> None:
        """Sin punto acotado (D-6): la cima queda plana (47 de 243 antes y después), sin
        puntos añadidos, informada como una región cerrada con el área del 49-gono, y la
        corrección para enseguida (una sola triangulación): no queda ningún plano entre
        curvas de cota distinta."""
        lines = _circles()
        recording = _Recording()
        tin, report = _build(lines, triangulator=recording, name="cerro")
        pct = 100.0 * CIRCLE_FLAT / CIRCLE_TRIANGLES
        self.assertEqual((report.flat_pct_before, report.flat_pct), (pct, pct))
        self.assertEqual((report.points_added, report.unresolved_flat_regions), (0, 1))
        area = _shoelace(lines[2].xyz[:-1, :2])
        self.assertAlmostEqual(report.unresolved_flat_area_m2, area, delta=1e-9 * area)
        self.assertEqual(len(recording.calls), 1)
        self.assertEqual(int(_flat(tin).sum()), CIRCLE_FLAT)
        self.assertEqual(set(tin.vertices[:, 2][tin.faces[_flat(tin)]].ravel()), {860.0})
        self.assertEqual(len(report.notes), 1)
        self.assertIn("cerro", report.notes[0])
        self.assertIn("1 ", report.notes[0])

    def test_plateau_with_spot_height_is_not_unresolved(self) -> None:
        """Un punto acotado de 860 m en la cima (a la cota de su curva): la cima es llana
        según los datos (49 planos en abanico alrededor del punto, de 245) y no es una cima
        sin acotar; sin nada que corregir, no se añade ningún punto."""
        tin, report = _build(_circles(), _spots((0.0, 0.0, 860.0)))
        self.assertEqual((tin.flat_faces, report.triangles), (49, 245))
        self.assertEqual(report.points_added, 0)
        self.assertEqual((report.unresolved_flat_regions, report.unresolved_flat_area_m2),
                         (0, 0.0))
        self.assertEqual(report.notes, ())

    def test_far_from_the_origin(self) -> None:
        """A ±8 km del GeoOrigin: vértices bit a bit y el triangulador recibe locales."""
        center = (E0 + 7_950.0, N0 - 8_000.0)
        lines = _circles(center)
        recording = _Recording()
        tin, report = _build(lines, _spots((0.0, 0.0, SUMMIT), center=center), recording)
        want = np.concatenate([_spots((0.0, 0.0, SUMMIT), center=center).xyz,
                               _ring_vertices(lines)])
        self.assertEqual(tin.vertices.tobytes(), want.tobytes())
        local = georef.world_to_local(want[:, :2], ORIGIN)
        self.assertEqual(recording.calls[-1][0].tobytes(), local.tobytes())
        self.assertEqual(report.flat_pct, 0.0)


class SquaresTest(unittest.TestCase):
    """RF-006-16: planos entre curvas de cota distinta (las esquinas de cuadrados
    concéntricos de 850, 855 y 860 m, densificados) corregidos con puntos interpolados."""

    @staticmethod
    def _band(xyz: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """La cota de abajo y la de arriba de la franja de cada punto: por su distancia de
        Chebyshev al centro (60, 40 y 20 m son las curvas; dentro, el punto de 863 m)."""
        r = np.max(np.abs(xyz[:, :2] - CENTER), axis=1)
        low = np.select([r > 40.0, r > 20.0], [850.0, 855.0], 860.0)
        high = np.select([r > 40.0, r > 20.0], [855.0, 860.0], SUMMIT)
        return low, high

    def test_added_points_correct_the_flats(self) -> None:
        """Las curvas solas (192 vértices tras densificar a 5 m; 96 en el borde, alineados:
        2·192 − 96 − 2 = 286 triángulos) dejan 54 planos: los 30 del 32-gono de la cima y 3
        en cada esquina de las curvas de 850 y 855 m. Con el punto acotado, 36 de 288 (las
        esquinas, también las de la cima); una pasada añade un punto por plano y no deja
        ninguno. Los puntos añadidos tienen origen 4 y una cota estrictamente entre la curva
        de su franja y la siguiente hacia arriba (la vecina que alcanza su región, no la más
        cercana en planta), y ninguno está sobre una curva. Las curvas siguen siendo
        aristas; todas las normales, +Z."""
        recording = _Recording()
        tin, report = _build(_squares(), _spots((0.0, 0.0, SUMMIT)), recording)
        self.assertEqual(report.flat_pct_before, 100.0 * 54 / 286)
        self.assertEqual((report.flat_pct, tin.flat_faces), (0.0, 0))
        added = tin.vertex_source == 4
        self.assertEqual(report.points_added, 36)
        self.assertEqual(report.points_added, int(added.sum()))
        self.assertEqual(report.vertices, 192 + 1 + report.points_added)
        low, high = self._band(tin.vertices[added])
        z = tin.vertices[added, 2]
        self.assertTrue(((z > low) & (z < high)).all())
        self.assertEqual(report.unresolved_flat_regions, 0)
        self.assertEqual(report.constraint_edges, 192)
        edges = _edge_set(tin.faces)
        self.assertTrue(set(map(tuple, tin.constraint_edges.tolist())) <= edges)
        self.assertTrue((_normal_z(tin.vertices, tin.faces) > 0.0).all())
        self.assertEqual(len(recording.calls), 3)  # antes, la de trabajo y una pasada

    def test_stops_when_only_closed_flats_remain(self) -> None:
        """Sin punto acotado y con 10 pasadas permitidas: la primera corrige las 24 esquinas
        de 850 y 855 m y la corrección para (dos triangulaciones en total) porque solo
        quedan los 30 planos de la cima (región cerrada), aunque sean más del 1 %: la cima
        (40 × 40 m) se informa (D-6)."""
        recording = _Recording()
        tin, report = _build(_squares(), triangulator=recording, max_passes=10)
        self.assertEqual(report.points_added, 24)
        self.assertEqual(len(recording.calls), 2)
        self.assertEqual(tin.flat_faces, 30)
        self.assertEqual(report.flat_pct, 100.0 * 30 / report.triangles)
        flat = _flat(tin)
        self.assertEqual(set(tin.vertices[:, 2][tin.faces[flat]].ravel()), {860.0})
        centroid = tin.vertices[tin.faces[flat]][:, :, :2].mean(axis=1) - CENTER
        self.assertTrue((np.abs(centroid) < 20.0).all())
        self.assertEqual(report.unresolved_flat_regions, 1)
        self.assertAlmostEqual(report.unresolved_flat_area_m2, 1600.0, delta=1e-9)
        low, high = self._band(tin.vertices[tin.vertex_source == 4])
        z = tin.vertices[tin.vertex_source == 4, 2]
        self.assertTrue(((z > low) & (z < np.minimum(high, 860.0))).all())
        # Sin pasadas quedan también las 24 esquinas (abiertas): solo la cima es cerrada.
        tin, report = _build(_squares(), max_passes=0)
        self.assertEqual((tin.flat_faces, report.points_added), (54, 0))
        self.assertEqual(report.unresolved_flat_regions, 1)
        self.assertAlmostEqual(report.unresolved_flat_area_m2, 1600.0, delta=1e-9)

    def test_threshold_and_passes(self) -> None:
        """Con un umbral del 20 % (las curvas y el punto acotado ya dan el 12,5 %) o sin
        pasadas, no se añade ningún punto: dos triangulaciones (antes y la de trabajo)."""
        for options in ({"max_flat_pct": 20.0}, {"max_passes": 0}):
            with self.subTest(**options):
                recording = _Recording()
                tin, report = _build(_squares(), _spots((0.0, 0.0, SUMMIT)), recording,
                                     **options)
                self.assertEqual(report.points_added, 0)
                self.assertEqual(len(recording.calls), 2)
                self.assertEqual((tin.flat_faces, report.triangles), (36, 288))
                self.assertEqual(report.flat_pct, 12.5)
        # «Hasta que baje del umbral»: con el 12,5 % justo en el umbral, se corrige.
        _tin, report = _build(_squares(), _spots((0.0, 0.0, SUMMIT)), max_flat_pct=12.5)
        self.assertEqual((report.points_added, report.flat_pct), (36, 0.0))


class SaddleTest(unittest.TestCase):
    """RF-006-16 en un collado: dos cimas de 860 m sin acotar dentro de una curva de 855 m."""

    def test_saddle_is_corrected_and_summits_stay_flat(self) -> None:
        """Los planos que unen las dos curvas de 860 m (el collado) se abren a la de 855 m y
        se corrigen con cotas entre 855 y 860 m, fuera de las dos cimas; las cimas, regiones
        cerradas por su curva, no se unen al collado a través de ella: quedan planas y se
        informan (dos, con el área de los dos 24-gonos)."""
        def ellipse(a, b, z, count, cx=0.0, offset=0.0):
            t = offset + 2.0 * math.pi * np.arange(count) / count
            return _closed(f"E{z:g}{cx:+g}", np.column_stack([cx + a * np.cos(t),
                                                              b * np.sin(t)]), z)

        summits = [ellipse(10.0, 10.0, 860.0, 24, cx=-15.0, offset=0.05),
                   ellipse(10.0, 10.0, 860.0, 24, cx=15.0, offset=0.07)]
        lines = [ellipse(60.0, 40.0, 850.0, 80), ellipse(45.0, 25.0, 855.0, 64, offset=0.02),
                 *summits]
        tin, report = _build(lines, name="collado")
        added = tin.vertex_source == 4
        self.assertGreater(report.points_added, 0)
        rel = tin.vertices[added, :2] - CENTER
        for cx in (-15.0, 15.0):
            self.assertTrue((np.hypot(rel[:, 0] - cx, rel[:, 1]) > 10.0).all())
        z = tin.vertices[added, 2]
        self.assertTrue(((z > 855.0) & (z < 860.0)).all())
        self.assertEqual(report.unresolved_flat_regions, 2)
        area = sum(_shoelace(line.xyz[:-1, :2]) for line in summits)
        self.assertAlmostEqual(report.unresolved_flat_area_m2, area, delta=1e-9 * area)


class ValleyTest(unittest.TestCase):
    """RF-006-16: en un valle (curvas en V con el vértice aguas arriba), los planos dentro
    de cada V se corrigen hacia la curva de abajo, la que alcanza la región por su boca, y
    no hacia la de arriba, que está más cerca en planta, al otro lado de la curva."""

    @staticmethod
    def _terrain(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        return 95.0 + 0.5 * np.abs(x) + 0.1 * y

    def test_points_go_down_the_valley(self) -> None:
        """Curvas de z = 95 + 0,5·|x| + 0,1·y (95, 100 y 105 m, vértices en y = 0, 50 y
        100 m): cada punto añadido tiene una cota entre la de su curva menos 5 m y la de su
        curva, a menos de media equidistancia (2,5 m) de la del terreno (la fórmula de A12
        mide d de lado, hasta los brazos de la V, y d′ a lo largo del eje, hasta la V de
        abajo: en esta vaguada estrecha sube la cota hasta 1,9 m; hacia la curva de arriba
        el error pasaría de 5 m). Dentro de la V de 95 m, abierta solo al borde del TIN, la
        zona queda plana: una región cerrada de 500 m² (las astillas degeneradas de los
        brazos rectos densificados en el borde no cuentan)."""
        lines = []
        for level in (95.0, 100.0, 105.0):
            tip = 10.0 * (level - 95.0)
            half = 2.0 * (level - 95.0) + 10.0  # |x| en y = −50
            rows = [(E0 - half, N0 - 50.0, level), (E0, N0 + tip, level),
                    (E0 + half, N0 - 50.0, level)]
            lines.append(points.Breakline(f"V{level:g}", _frozen(rows)))
        tin, report = _build(lines, name="valle")
        added = tin.vertex_source == 4
        self.assertGreater(report.points_added, 0)
        x = tin.vertices[added, 0] - E0
        y = tin.vertices[added, 1] - N0
        z = tin.vertices[added, 2]
        terrain = self._terrain(x, y)
        level = np.select([terrain > 100.0, terrain > 95.0], [105.0, 100.0], 95.0)
        self.assertTrue(((z < level) & (z > level - 5.0)).all(), (z, level))
        self.assertLess(float(np.abs(z - terrain).max()), 2.5)
        self.assertEqual(report.unresolved_flat_regions, 1)
        self.assertAlmostEqual(report.unresolved_flat_area_m2, 500.0, delta=1e-9)


class CorrectionPointTest(unittest.TestCase):
    """A12 en triángulos hechos a mano (``tin_contours._correction_points``)."""

    def test_barycenter_when_the_circumcenter_is_outside(self) -> None:
        """Triángulo plano obtuso A(0; 0), B(10; 1), C(20; 0) a 10 m entre los tramos de
        curva A–B y B–C, abierto por A–C a un triángulo con D(10; −10) a 5 m: su
        circuncentro (10; −49,5) cae fuera de la región y el punto va al baricentro
        (10; 1/3), con z = 10 + (5 − 10)·d/(d + d′), d a la curva y d′ a D."""
        xy = np.array([(0.0, 0.0), (10.0, 1.0), (20.0, 0.0), (10.0, -10.0)])
        z = np.array([10.0, 10.0, 10.0, 5.0])
        faces = np.array([[0, 2, 1], [0, 3, 2]], dtype=np.int64)
        edges = np.array([[0, 1], [1, 2]], dtype=np.int32)
        got_xy, got_z = tin_contours._correction_points(xy, z, faces, edges,
                                                        np.ones(2, dtype=bool), 0.01)
        bary = np.array([10.0, 1.0 / 3.0])
        self.assertEqual(got_xy.shape, (1, 2))
        np.testing.assert_allclose(got_xy[0], bary, rtol=0, atol=1e-12)
        d = abs(10.0 * bary[1] - 1.0 * bary[0]) / math.hypot(10.0, 1.0)
        d2 = math.hypot(*(bary - (10.0, -10.0)))
        self.assertAlmostEqual(float(got_z[0]), 10.0 - 5.0 * d / (d + d2), delta=1e-12)

    def test_circumcenter_with_the_nearest_level(self) -> None:
        """Oreja A(0; 0), B(4; 0), C(0; 4) a 10 m entre los tramos A–B y A–C, abierta por
        B–C a D(6; 6) a 5 m, con el tramo de curva D–E, E(6; 3), a 5 m: circuncentro (2; 2),
        d = 2 y d′ = distancia al segmento D–E (a su extremo E, √17; no a su recta, 4)."""
        xy = np.array([(0.0, 0.0), (4.0, 0.0), (0.0, 4.0), (6.0, 6.0), (6.0, 3.0)])
        z = np.array([10.0, 10.0, 10.0, 5.0, 5.0])
        faces = np.array([[0, 1, 2], [1, 3, 2], [1, 4, 3]], dtype=np.int64)
        edges = np.array([[0, 1], [0, 2], [3, 4]], dtype=np.int32)
        got_xy, got_z = tin_contours._correction_points(xy, z, faces, edges,
                                                        np.ones(3, dtype=bool), 0.01)
        np.testing.assert_allclose(got_xy, [(2.0, 2.0)], rtol=0, atol=1e-12)
        far = math.sqrt(17.0)
        self.assertAlmostEqual(float(got_z[0]), 10.0 - 5.0 * 2.0 / (2.0 + far), delta=1e-12)

    def test_only_level_edges_are_contours(self) -> None:
        """Una arista obligatoria con los extremos a cotas distintas (D a 5 m y F(3; 6,5) a
        8 m, a 4,61 m del punto) no es una curva: d′ sigue siendo la distancia a D (√32)."""
        xy = np.array([(0.0, 0.0), (4.0, 0.0), (0.0, 4.0), (6.0, 6.0), (3.0, 6.5)])
        z = np.array([10.0, 10.0, 10.0, 5.0, 8.0])
        faces = np.array([[0, 1, 2], [1, 3, 2], [2, 3, 4]], dtype=np.int64)
        edges = np.array([[0, 1], [0, 2], [3, 4]], dtype=np.int32)
        got_xy, got_z = tin_contours._correction_points(xy, z, faces, edges,
                                                        np.ones(3, dtype=bool), 0.01)
        np.testing.assert_allclose(got_xy, [(2.0, 2.0)], rtol=0, atol=1e-12)
        far = math.sqrt(32.0)
        self.assertAlmostEqual(float(got_z[0]), 10.0 - 5.0 * 2.0 / (2.0 + far), delta=1e-12)

    def test_point_on_its_contour_is_discarded(self) -> None:
        """Si el punto cae sobre la curva de su región (el circuncentro de un triángulo
        rectángulo cuya hipotenusa B–C es un tramo de curva), d = 0 ≤ 1 cm: se descarta."""
        xy = np.array([(0.0, 0.0), (4.0, 0.0), (0.0, 4.0), (2.0, -3.0)])
        z = np.array([10.0, 10.0, 10.0, 5.0])
        faces = np.array([[0, 1, 2], [0, 3, 1]], dtype=np.int64)
        edges = np.array([[1, 2]], dtype=np.int32)
        got_xy, _got_z = tin_contours._correction_points(xy, z, faces, edges,
                                                         np.ones(2, dtype=bool), 0.01)
        self.assertEqual(got_xy.shape, (0, 2))

    def test_closed_region_and_duplicates(self) -> None:
        """Una región cerrada por tramos de curva no da puntos; dos triángulos planos con el
        mismo circuncentro (un cuadrado partido por su diagonal) dan uno solo."""
        square = np.array([(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)])
        faces = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
        ring = np.array([[0, 1], [1, 2], [2, 3], [0, 3]], dtype=np.int32)
        got_xy, _got_z = tin_contours._correction_points(
            square, np.full(4, 7.0), faces, ring, np.ones(2, dtype=bool), 0.01)
        self.assertEqual(got_xy.shape, (0, 2))
        xy = np.vstack([square, [(2.0, -6.0)]])
        z = np.array([7.0, 7.0, 7.0, 7.0, 3.0])
        faces = np.array([[0, 1, 2], [0, 2, 3], [0, 4, 1]], dtype=np.int64)
        edges = np.array([[1, 2], [2, 3], [0, 3]], dtype=np.int32)
        got_xy, got_z = tin_contours._correction_points(xy, z, faces, edges,
                                                        np.ones(3, dtype=bool), 0.01)
        np.testing.assert_allclose(got_xy, [(2.0, 2.0)], rtol=0, atol=1e-12)
        self.assertTrue(3.0 < float(got_z[0]) < 7.0)

    def test_excluded_neighbours_do_not_open_a_region(self) -> None:
        """Un vecino quitado por el contorno no abre la región (como el borde del TIN)."""
        xy = np.array([(0.0, 0.0), (4.0, 0.0), (0.0, 4.0), (6.0, 6.0)])
        z = np.array([10.0, 10.0, 10.0, 5.0])
        faces = np.array([[0, 1, 2], [1, 3, 2]], dtype=np.int64)
        edges = np.array([[0, 1], [0, 2]], dtype=np.int32)
        got_xy, _got_z = tin_contours._correction_points(
            xy, z, faces, edges, np.array([True, False]), 0.01)
        self.assertEqual(got_xy.shape, (0, 2))


class ContourInputTest(unittest.TestCase):
    """Densificación, conflictos (RF-006-14), parámetros, contorno, avance y cancelación."""

    def test_densify(self) -> None:
        """Dos curvas rectas de 23 m (850 y 855 m): con 5 m, 5 trozos de 4,6 m (vértices
        nuevos en a + k/5·(b − a), origen 3); con 10 m, 3; los vértices de entrada, bit a
        bit. Las curvas siguen siendo cadenas de aristas obligatorias."""
        low = points.Breakline("C850", _frozen([(E0, N0, 850.0), (E0 + 23.0, N0, 850.0)]))
        high = points.Breakline("C855", _frozen([(E0, N0 + 10.0, 855.0),
                                                 (E0 + 23.0, N0 + 10.0, 855.0)]))
        for step, pieces in ((None, 5), (5.0, 5), (10.0, 3), (23.0, 1), (100.0, 1)):
            with self.subTest(step=step):
                tin, report = _build([low, high], densify_m=step)
                self.assertEqual(report.vertices, 2 * (pieces + 1))
                self.assertEqual(report.constraint_edges, 2 * pieces)
                self.assertEqual(tin.vertex_source.tolist(), [3] * (2 * (pieces + 1)))
                for line, first in ((low, 0), (high, pieces + 1)):
                    got = tin.vertices[first:first + pieces + 1]
                    self.assertEqual(got[0].tobytes(), line.xyz[0].tobytes())
                    self.assertEqual(got[-1].tobytes(), line.xyz[1].tobytes())
                    t = np.arange(pieces + 1)[:, None] / pieces
                    np.testing.assert_allclose(got, line.xyz[0] + t * (line.xyz[1]
                                                                       - line.xyz[0]),
                                               rtol=0, atol=1e-9)
                self.assertEqual(report.flat_pct_before, 0.0)
                self.assertEqual(report.flat_pct, 0.0)

    def test_spot_height_on_a_contour(self) -> None:
        """Un punto acotado sobre un tramo de curva con su misma cota la parte (A8): sigue
        siendo un punto (origen 0), es vértice de la curva y entra en la triangulación de
        las curvas solas."""
        low = points.Breakline("C850", _frozen([(E0, N0, 850.0), (E0 + 20.0, N0, 850.0)]))
        high = points.Breakline("C855", _frozen([(E0, N0 + 10.0, 855.0),
                                                 (E0 + 20.0, N0 + 10.0, 855.0)]))
        recording = _Recording()
        tin, report = _build([low, high], _spots((7.5, 0.0, 850.0), center=(E0, N0)),
                             recording)
        self.assertEqual(report.vertices, 11)
        self.assertEqual(tin.vertex_source.tolist(), [0] + [3] * 10)
        self.assertEqual(report.constraint_edges, 9)
        edges = set(map(tuple, tin.constraint_edges.tolist()))
        self.assertTrue({(0, 2), (0, 3)} <= edges)  # 5 m → 7,5 m → 10 m
        self.assertEqual([len(xy) for xy, _edges in recording.calls], [11])

    def test_crossing_contours_are_a_conflict(self) -> None:
        """Dos curvas de 850 y 855 m que se cruzan: ``ConflictError`` sin triangular; un
        punto acotado sobre una curva con otra cota, también."""
        first = points.Breakline("C850", _frozen([(E0, N0, 850.0), (E0 + 20.0, N0 + 20.0,
                                                                    850.0)]))
        second = points.Breakline("C855", _frozen([(E0, N0 + 20.0, 855.0),
                                                   (E0 + 20.0, N0, 855.0)]))
        recording = _Recording()
        with self.assertRaises(gis.ConflictError) as caught:
            _build([first, second], triangulator=recording, name="curvas")
        self.assertEqual(caught.exception.code, "gis.constraint_conflicts")
        self.assertEqual([c.kind for c in caught.exception.conflicts],
                         [gis.ConflictKind.CROSSING_LINES])
        self.assertEqual(recording.calls, [])
        third = points.Breakline("C860", _frozen([(E0, N0 + 30.0, 860.0),
                                                  (E0 + 20.0, N0 + 30.0, 860.0)]))
        on_line = _spots((10.0, 10.0, 852.0), center=(E0, N0))
        with self.assertRaises(gis.ConflictError) as caught:
            _build([first, third], on_line, triangulator=recording)
        self.assertEqual([c.kind for c in caught.exception.conflicts],
                         [gis.ConflictKind.POINT_ON_LINE])
        self.assertEqual(recording.calls, [])

    def test_spot_height_duplicates(self) -> None:
        """Dos puntos acotados a 0,5 mm con cotas distintas: «preguntar» para; «máxima» lo
        resuelve (A7, RF-006-14)."""
        spots = _spots((0.0, 0.0, 863.0), (0.0005, 0.0, 864.0))
        with self.assertRaises(gis.ConflictError) as caught:
            _build(_circles(), spots)
        self.assertEqual(caught.exception.code, "gis.duplicate_conflicts")
        tin, report = _build(_circles(), spots, duplicate_policy="max")
        self.assertEqual(report.duplicates_merged, 1 + 3)  # y el vértice de cierre de cada curva
        self.assertEqual(tin.vertices[0].tobytes(), spots.xyz[1].tobytes())

    def test_parameters(self) -> None:
        """Los valores por defecto salen de ``gis/params.py``; uno fuera de rango o que no es
        un número → ``GisError`` ``gis.param_*`` con la clave."""
        self.assertEqual((tin_contours.params.default("gis.tin.contour_densify_m"),
                          tin_contours.params.default("gis.tin.flat_max_passes"),
                          tin_contours.params.default("gis.tin.max_flat_pct")), (5.0, 3, 1.0))
        cases = (({"densify_m": 0.0}, "gis.tin.contour_densify_m", "gis.param_out_of_range"),
                 ({"max_passes": 1.5}, "gis.tin.flat_max_passes", "gis.param_not_integer"),
                 ({"max_passes": 11}, "gis.tin.flat_max_passes", "gis.param_out_of_range"),
                 ({"max_flat_pct": 101.0}, "gis.tin.max_flat_pct", "gis.param_out_of_range"),
                 ({"max_flat_pct": "1"}, "gis.tin.max_flat_pct", "gis.param_not_number"))
        for options, key, code in cases:
            with self.subTest(**options), self.assertRaises(gis.GisError) as caught:
                _build(_circles(), **options)
            self.assertEqual((caught.exception.code, caught.exception.field), (code, key))

    def test_boundary(self) -> None:
        """Con un contorno (cuadrado de 50 m centrado), fuera los triángulos con el
        centroide fuera; los porcentajes son de lo que queda."""
        half = 25.0
        ring = np.array([(CENTER[0] - half, CENTER[1] - half), (CENTER[0] + half,
                                                                CENTER[1] - half),
                         (CENTER[0] + half, CENTER[1] + half), (CENTER[0] - half,
                                                                CENTER[1] + half)])
        ring.flags.writeable = False
        tin, report = _build(_circles(), _spots((0.0, 0.0, SUMMIT)), boundary=ring)
        self.assertGreater(report.removed_outside, 0)
        centroid = tin.vertices[tin.faces][:, :, :2].mean(axis=1) - CENTER
        self.assertTrue((np.abs(centroid) < half).all())
        self.assertEqual(report.flat_pct, 0.0)
        self.assertGreater(report.flat_pct_before, 100.0 * CIRCLE_FLAT / CIRCLE_TRIANGLES)

    def test_contours_alone_cannot_be_triangulated(self) -> None:
        """Una sola curva recta con tres puntos acotados: el TIN se crea y el % de antes no
        se puede calcular (``None``)."""
        line = points.Breakline("C850", _frozen([(E0, N0, 850.0), (E0 + 20.0, N0, 850.0)]))
        spots = _spots((0.0, 10.0, 852.0), (20.0, 10.0, 853.0), (10.0, -10.0, 848.0),
                       center=(E0, N0))
        tin, report = _build([line], spots)
        self.assertIsNone(report.flat_pct_before)
        self.assertEqual(report.vertices, 3 + 5)
        self.assertTrue((_normal_z(tin.vertices, tin.faces) > 0.0).all())

    def test_progress_and_cancel(self) -> None:
        """El avance crece hasta 1; al cancelar, ``JobCancelled`` sin triangular."""
        seen: list[float] = []
        _build(_squares(), _spots((0.0, 0.0, SUMMIT)),
               progress=lambda fraction, _text: seen.append(fraction))
        self.assertEqual(seen, sorted(seen))
        self.assertEqual(seen[-1], 1.0)
        recording = _Recording()
        with self.assertRaises(worker_api.JobCancelled):
            _build(_squares(), triangulator=recording, cancelled=lambda: True)
        self.assertEqual(recording.calls, [])

    def test_wrong_inputs(self) -> None:
        """Errores del programa: curvas que no son ``Breakline`` o puntos acotados que no
        son un ``PointSet``."""
        with self.assertRaises(TypeError):
            _build([_circles()[0].xyz])
        with self.assertRaises(TypeError):
            _build(_circles(), _circles()[0].xyz)


if __name__ == "__main__":
    unittest.main()

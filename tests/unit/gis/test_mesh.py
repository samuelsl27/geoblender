# SPDX-License-Identifier: GPL-3.0-or-later
"""Mallas de vista de una superficie, su comprobación y sus niveles de detalle (spec 006, T22;
plan 006 §5.3.2 y §5.4 A15; ``gis.mesh``).

- **RF-006-21**: ``surface_mesh_from_raster`` da la triangulación de A13 (la de
  ``raster_to_tin``) y ``surface_mesh_from_tin`` las caras del TIN, todas con la normal hacia
  arriba (+Z), también las de un TIN con triángulos horarios. ``check_surface_mesh(vértices
  ABS, caras, referencia)`` marca como no válida la malla con caras con la normal hacia abajo
  o degeneradas (área en planta nula, con signo exacto) o cuyo volumen sobre la cota mínima de
  la superficie difiere del de la rejilla o el TIN en más que su área en planta por 0,5 mm, y
  dice cuántas caras fallan, cuántas tiene la malla y la superficie y la diferencia en m³: la
  malla correcta pasa (diferencia 0), la invertida no (ΔV ≈ −2V), ni la que pierde caras, ni
  la que tiene una sola cara hacia abajo o degenerada aunque su volumen cuadre; la que vuelve
  de float32 en locales a ±8 km del origen (como la de la vista, HU-006-4) pasa.
- **RF-006-22**: ``lod_rasters`` da, de una rejilla de paso menor que el primer nivel
  (``gis.view.lod_steps_m``, 2 y 5 m), sus versiones de 2 y 5 m por media de área en rejillas
  alineadas (``aligned_grid``) sin tocar la rejilla de cálculo; de una de 2 m o más, ninguna.

Las referencias son independientes: el volumen de un plano sobre el rectángulo de los centros
(analítico), prismas contados cara a cara y medias de celda contadas a mano. Las entradas no
se modifican (arrays de solo lectura).
"""

import dataclasses
import json
import math
import unittest

import numpy as np

from tests.support.package import import_geoblender

gis = import_geoblender("gis")
mesh = import_geoblender("gis.mesh")
params = import_geoblender("gis.params")
ParamError = import_geoblender("core.params").ParamError
points = import_geoblender("gis.points")
cdt = import_geoblender("gis.cdt")
georef = import_geoblender("core.georef")
worker_api = import_geoblender("jobs.worker_api")

NAN = math.nan
CATALOG = georef.load_catalog()
CRS = CATALOG.horizontal(25830)
VERTICAL = CATALOG.vertical(5782)
E0, N0 = 700_000.0, 4_400_000.0
ORIGIN = georef.GeoOrigin(700_000, 4_400_000, 0)
HALF_MM = 0.0005  # RF-006-21: la diferencia admitida es el área en planta por 0,5 mm
B24_DX = 1.0002942907592702
B24_DY = 1.0003022974607014


def _frozen(array, dtype=np.float64) -> np.ndarray:
    array = np.array(array, dtype=dtype)
    array.flags.writeable = False  # una entrada nunca se modifica
    return array


def _raster(values, *, dx: float = 1.0, dy: float = 1.0, west: float = E0,
            north: float = N0 + 50.0):
    array = _frozen(values)
    nrows, ncols = array.shape
    grid = gis.Grid(west=west, north=north, dx=dx, dy=dy, ncols=ncols, nrows=nrows)
    return gis.Raster(grid, array, CRS, VERTICAL)


def _surface(nrows: int, ncols: int, *, dx: float = 1.0, dy: float = 1.0, mask=None):
    """z = 800 + 0,5x − 0,25y + 3 sin(x/7) en los centros (x, y relativas a la esquina
    noroeste, y hacia el norte), sin dato en ``mask``."""
    x = (np.arange(ncols, dtype=np.float64) + 0.5) * dx
    y = -(np.arange(nrows, dtype=np.float64) + 0.5) * dy
    values = 800.0 + 0.5 * x[None, :] - 0.25 * y[:, None] + 3.0 * np.sin(x[None, :] / 7.0)
    if mask is not None:
        values[mask] = NAN
    return values


def _hole(nrows: int, ncols: int) -> np.ndarray:
    mask = np.zeros((nrows, ncols), dtype=bool)
    mask[nrows // 3:nrows // 3 + 4, ncols // 2:ncols // 2 + 5] = True
    mask[0, :3] = True  # una esquina sin dato
    return mask


def _normal_z(vertices, faces) -> np.ndarray:
    """La Z de (b − a) × (c − a) de cada cara: > 0 si la normal va hacia arriba."""
    a, b, c = (vertices[faces[:, k]] for k in range(3))
    u, v = b - a, c - a
    return u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]


def _prisms(vertices, faces, base: float) -> np.ndarray:
    """Volumen con signo de cada prisma (área en planta con signo × altura media sobre
    ``base``), cara a cara en Python."""
    out = []
    for a, b, c in faces.tolist():
        (ax, ay, az), (bx, by, bz), (cx, cy, cz) = vertices[a], vertices[b], vertices[c]
        area = 0.5 * ((bx - ax) * (cy - ay) - (by - ay) * (cx - ax))
        out.append(area * ((az - base) + (bz - base) + (cz - base)) / 3.0)
    return np.array(out)


def _point_set(xyz):
    xyz = _frozen(xyz)
    count = len(xyz)
    return points.PointSet(xyz, tuple(f"P{i + 1}" for i in range(count)), ("",) * count,
                           tuple(range(2, count + 2)))


def _cloud_tin(count: int = 200, seed: int = 7, *, left: float = 0.0, bottom: float = 0.0,
               size: float = 60.0):
    """TIN (``PureTriangulator``) de una nube al azar con sus cuatro esquinas en
    [left, left + size] × [bottom, bottom + size] (relativas a E0 y N0) sobre una superficie
    como la de :func:`_surface` desde su esquina suroeste."""
    rng = np.random.default_rng(seed)
    corners = [[0.0, 0.0], [size, 0.0], [size, size], [0.0, size]]
    xy = np.vstack([corners, rng.uniform(0.0, size, size=(count, 2))])
    x, y = left + xy[:, 0], bottom + xy[:, 1]
    z = 800.0 + 0.5 * xy[:, 0] + 0.25 * xy[:, 1] + 3.0 * np.sin(xy[:, 0] / 7.0)
    tin, _report = gis.build_tin(_point_set(np.column_stack([E0 + x, N0 + y, z])),
                                 triangulator=cdt.PureTriangulator(), origin=ORIGIN)
    return tin


def _frozen_tin(tin):
    for array in (tin.vertices, tin.faces, tin.constraint_edges, tin.vertex_source):
        array.flags.writeable = False
    return tin


def _area_mean(raster, grid) -> np.ndarray:
    """La media por área de ``raster`` en cada celda de ``grid``, celda a celda: Σ z·w / Σ w
    con w el área de solape de cada celda de origen; sin dato si las de origen no la cubren
    entera (10⁻⁹ de holgura) o si alguna que la toca no tiene dato."""
    src = raster.grid
    xs = src.west + np.arange(src.ncols + 1) * src.dx
    ys = src.north - np.arange(src.nrows + 1) * src.dy
    out = np.full(grid.shape, NAN)
    for row in range(grid.nrows):
        top = grid.north - row * grid.dy
        oy = np.clip(np.minimum(ys[:-1], top) - np.maximum(ys[1:], top - grid.dy), 0.0, None)
        for col in range(grid.ncols):
            left = grid.west + col * grid.dx
            ox = np.clip(np.minimum(xs[1:], left + grid.dx) - np.maximum(xs[:-1], left), 0.0,
                         None)
            weight = oy[:, None] * ox[None, :]
            touched = weight > 1e-9 * grid.cell_area
            if weight.sum() < (1.0 - 1e-9) * grid.cell_area:
                continue
            if np.isfinite(raster.values[touched]).all():
                out[row, col] = (np.sum(weight[touched] * raster.values[touched])
                                 / np.sum(weight[touched]))
    return out


def _triangles(vertices, faces) -> set:
    """Las caras como conjuntos de coordenadas (sin orden ni orientación)."""
    return {frozenset(map(tuple, vertices[face].tolist())) for face in faces}


class SurfaceMeshTest(unittest.TestCase):
    """RF-006-21: mallas de rejilla y de TIN en absolutas con las normales hacia arriba."""

    def test_grid_mesh_is_the_triangulation_of_the_grid(self) -> None:
        """La malla de una rejilla (con un hueco y una esquina sin dato; pasos de 1 m y de
        B24) son los vértices y las caras de ``raster_to_tin`` (A13), bit a bit, en float64 e
        int32, con todas las normales hacia arriba."""
        for dx, dy in ((1.0, 1.0), (B24_DX, B24_DY)):
            with self.subTest(dx=dx, dy=dy):
                raster = _raster(_surface(14, 18, dx=dx, dy=dy, mask=_hole(14, 18)), dx=dx,
                                 dy=dy)
                result = mesh.surface_mesh_from_raster(raster, name="mdt")
                tin = gis.raster_to_tin(raster)
                self.assertIsInstance(result, mesh.MeshArrays)
                self.assertEqual(result.vertices.dtype, np.float64)
                self.assertEqual(result.faces.dtype, np.int32)
                self.assertEqual(result.vertices.tobytes(), tin.vertices.tobytes())
                np.testing.assert_array_equal(result.faces, tin.faces)
                self.assertTrue((_normal_z(result.vertices, result.faces) > 0.0).all())
                self.assertEqual(len(result.faces), len(tin.faces))
                self.assertEqual(result.vertices.shape, (len(tin.vertices), 3))

    def test_tin_mesh_keeps_its_vertices_and_faces(self) -> None:
        """La malla de un TIN son sus vértices (bit a bit) y sus caras, con las normales
        hacia arriba; un TIN con la mitad de los triángulos horarios da los mismos triángulos
        vueltos hacia arriba."""
        tin = _frozen_tin(_cloud_tin())
        result = mesh.surface_mesh_from_tin(tin)
        self.assertEqual(result.vertices.tobytes(), tin.vertices.tobytes())
        np.testing.assert_array_equal(result.faces, tin.faces)
        self.assertEqual(result.faces.dtype, np.int32)
        self.assertTrue((_normal_z(result.vertices, result.faces) > 0.0).all())

        faces = tin.faces.copy()
        faces[::2] = faces[::2][:, [0, 2, 1]]
        clockwise = _frozen_tin(gis.Tin(tin.vertices, faces, tin.constraint_edges,
                                        tin.vertex_source, triangulator="otro"))
        self.assertTrue((_normal_z(clockwise.vertices, clockwise.faces) < 0.0).any())
        turned = mesh.surface_mesh_from_tin(clockwise)
        self.assertTrue((_normal_z(turned.vertices, turned.faces) > 0.0).all())
        self.assertEqual(_triangles(turned.vertices, turned.faces),
                         _triangles(tin.vertices, tin.faces))
        np.testing.assert_array_equal(clockwise.faces, faces)  # el TIN no cambia

    def test_grid_without_triangles(self) -> None:
        """Una rejilla sin ningún cuadro con tres centros con dato no tiene malla:
        ``gis.grid_tin_empty`` con su nombre."""
        values = np.full((4, 4), NAN)
        values[::2, ::2] = 800.0
        with self.assertRaises(gis.GisError) as caught:
            mesh.surface_mesh_from_raster(_raster(values), name="mdt_vacio")
        self.assertEqual(caught.exception.code, "gis.grid_tin_empty")
        self.assertIn("mdt_vacio", str(caught.exception))

    def test_progress_and_cancel(self) -> None:
        """La malla de una rejilla pasa el avance y la cancelación a ``raster_to_tin``."""
        raster = _raster(_surface(6, 7))
        steps = []
        mesh.surface_mesh_from_raster(raster, progress=lambda f, text: steps.append(f))
        self.assertEqual(steps[-1], 1.0)
        with self.assertRaises(worker_api.JobCancelled):
            mesh.surface_mesh_from_raster(raster, cancelled=lambda: True)

    def test_mesh_arrays_and_bad_inputs(self) -> None:
        """``MeshArrays`` exige vértices float64 (n, 3) finitos y caras int32 (m, 3) con
        índices que existen; las funciones, su tipo de superficie."""
        vertices = _frozen([[E0, N0, 800.0], [E0 + 1, N0, 801.0], [E0, N0 + 1, 802.0]])
        faces = _frozen([[0, 1, 2]], np.int32)
        arrays = mesh.MeshArrays(vertices, faces)
        self.assertIs(arrays.vertices, vertices)
        self.assertIs(arrays.faces, faces)
        bad = (
            (TypeError, vertices.astype(np.float32), faces),
            (TypeError, vertices, faces.astype(np.int64)),
            (ValueError, vertices[:, :2].copy(), faces),
            (ValueError, vertices, np.array([[0, 1, 3]], dtype=np.int32)),
            (ValueError, vertices, np.array([[0, 1, -1]], dtype=np.int32)),
            (ValueError, vertices, np.array([0, 1, 2], dtype=np.int32)),
            (ValueError, np.array([[E0, N0, NAN]] * 3), faces),
        )
        for error, bad_vertices, bad_faces in bad:
            with self.subTest(error=error.__name__, shape=bad_faces.shape):
                with self.assertRaises(error):
                    mesh.MeshArrays(bad_vertices, bad_faces)
        tin = _cloud_tin(20)
        raster = _raster(_surface(3, 3))
        with self.assertRaises(TypeError):
            mesh.surface_mesh_from_raster(tin)
        with self.assertRaises(TypeError):
            mesh.surface_mesh_from_tin(raster)

    def test_exported(self) -> None:
        """``gis`` reexporta la API de la malla (plan §5.3.2)."""
        for name in ("MeshArrays", "MeshReport", "surface_mesh_from_raster",
                     "surface_mesh_from_tin", "check_surface_mesh", "lod_rasters"):
            with self.subTest(name=name):
                self.assertIn(name, gis.__all__)
                self.assertIs(getattr(gis, name), getattr(mesh, name))


class CheckSurfaceMeshTest(unittest.TestCase):
    """RF-006-21: caras hacia abajo o degeneradas, o volumen que no cuadra → malla no
    válida, con cuántas caras fallan y la diferencia en m³."""

    def setUp(self) -> None:
        self.raster = _raster(_surface(30, 40, mask=_hole(30, 40)))
        self.grid_mesh = mesh.surface_mesh_from_raster(self.raster)
        self.vertices = _frozen(self.grid_mesh.vertices)
        self.faces = _frozen(self.grid_mesh.faces, np.int32)
        self.base = float(self.grid_mesh.vertices[:, 2].min())
        self.volume = float(np.sum(_prisms(self.vertices, self.faces, self.base)))
        self.area = float(np.sum(0.5 * _normal_z(self.vertices, self.faces)))

    def _check(self, vertices, faces, reference=None, **options):
        reference = self.raster if reference is None else reference
        return mesh.check_surface_mesh(_frozen(vertices), _frozen(faces, faces.dtype),
                                       reference, **options)

    def test_correct_grid_mesh_is_valid(self) -> None:
        """La malla de la rejilla frente a la rejilla: válida, sin caras que fallen, mismas
        caras, diferencia 0 y volumen, área y tolerancia como los prismas contados cara a
        cara."""
        report = self._check(self.vertices, self.faces, name="mdt_2026")
        self.assertTrue(report.valid)
        self.assertEqual(report.surface, "mdt_2026")
        self.assertEqual((report.faces, report.reference_faces), (len(self.faces),) * 2)
        self.assertEqual((report.faces_down, report.faces_degenerate, report.failed_faces),
                         (0, 0, 0))
        self.assertEqual(report.difference_m3, 0.0)
        self.assertEqual(report.base_m, self.base)
        self.assertAlmostEqual(report.volume_m3, self.volume, delta=1e-9 * self.volume)
        self.assertEqual(report.reference_volume_m3, report.volume_m3)
        self.assertAlmostEqual(report.plan_area_m2, self.area, delta=1e-12 * self.area)
        self.assertEqual(report.reference_area_m2, report.plan_area_m2)
        self.assertEqual(report.tolerance_m3, report.plan_area_m2 * HALF_MM)
        self.assertIsNone(report.message())
        self.assertIsNone(report.error())

    def test_volume_of_a_plane_is_analytic(self) -> None:
        """Un plano en una rejilla llena de 2 × 1,5 m: el volumen sobre la cota mínima es el
        área del rectángulo de los centros por la altura de su centro (≤ 10⁻¹² relativo)."""
        ncols, nrows, dx, dy = 25, 17, 2.0, 1.5
        x = (np.arange(ncols) + 0.5) * dx
        y = 50.0 - (np.arange(nrows) + 0.5) * dy
        values = 812.5 + 0.37 * x[None, :] - 0.21 * y[:, None]
        raster = _raster(values, dx=dx, dy=dy)
        arrays = mesh.surface_mesh_from_raster(raster)
        report = mesh.check_surface_mesh(arrays.vertices, arrays.faces, raster)
        width, height = (ncols - 1) * dx, (nrows - 1) * dy
        base = 812.5 + 0.37 * x[0] - 0.21 * y[0]
        middle = 812.5 + 0.37 * (x[0] + x[-1]) / 2 - 0.21 * (y[0] + y[-1]) / 2
        expected = width * height * (middle - base)
        self.assertTrue(report.valid)
        self.assertEqual(report.base_m, float(values.min()))
        self.assertAlmostEqual(report.reference_volume_m3, expected, delta=1e-12 * expected)
        self.assertAlmostEqual(report.plan_area_m2, width * height, delta=1e-12)

    def test_inverted_mesh_is_rejected(self) -> None:
        """La malla invertida (cada cara con el orden al revés): todas sus caras hacia
        abajo y ΔV ≈ −2V; no válida, y el mensaje y el error lo dicen con las cifras."""
        report = self._check(self.vertices, self.faces[:, [0, 2, 1]], name="mdt_2026")
        count = len(self.faces)
        self.assertFalse(report.valid)
        self.assertEqual((report.faces_down, report.faces_degenerate), (count, 0))
        self.assertEqual(report.failed_faces, count)
        self.assertAlmostEqual(report.volume_m3, -self.volume, delta=1e-9 * self.volume)
        self.assertAlmostEqual(report.difference_m3, -2.0 * self.volume,
                               delta=1e-9 * self.volume)
        self.assertAlmostEqual(report.plan_area_m2, self.area, delta=1e-9 * self.area)
        difference = round(report.difference_m3, 3) + 0.0
        text = report.message()
        self.assertIn(f"{count} de sus {count} caras", text)
        self.assertIn(f"tiene {count})", text)
        self.assertIn(f"en {difference!r} m³".replace(".", ","), text)
        self.assertIn("«mdt_2026»", text)
        error = report.error()
        self.assertIsInstance(error, gis.GisError)
        self.assertEqual(error.code, "gis.mesh_invalid")
        self.assertEqual(error.value, count)
        self.assertEqual(str(error), text)
        self.assertNotIn("{", report.message(language="en"))

    def test_mesh_that_loses_faces_is_rejected(self) -> None:
        """La malla sin el último 10 % de sus caras: ninguna falla, pero tiene menos que la
        superficie y su volumen difiere en el de los prismas perdidos, más que la tolerancia;
        no válida."""
        count = len(self.faces)
        kept = count - count // 10
        report = self._check(self.vertices, self.faces[:kept])
        lost = float(np.sum(_prisms(self.vertices, self.faces[kept:], self.base)))
        self.assertFalse(report.valid)
        self.assertEqual(report.failed_faces, 0)
        self.assertEqual((report.faces, report.reference_faces), (kept, count))
        self.assertAlmostEqual(report.difference_m3, -lost, delta=1e-9 * self.volume)
        self.assertGreater(abs(report.difference_m3), report.tolerance_m3)
        self.assertAlmostEqual(report.tolerance_m3, (self.area - float(np.sum(0.5 * _normal_z(
            self.vertices, self.faces[kept:])))) * HALF_MM, delta=1e-9)
        self.assertIn(f"0 de sus {kept} caras", report.message())
        self.assertIn(f"tiene {count})", report.message())

    def test_extra_faces_are_rejected(self) -> None:
        """Con todas las caras dos veces, el volumen es el doble: no válida."""
        report = self._check(self.vertices, np.vstack([self.faces, self.faces]))
        self.assertFalse(report.valid)
        self.assertEqual(report.faces, 2 * len(self.faces))
        self.assertAlmostEqual(report.difference_m3, self.volume, delta=1e-9 * self.volume)

    def test_one_face_down_is_enough(self) -> None:
        """Sobre una meseta a la cota mínima, una sola cara vuelta hacia abajo no cambia el
        volumen (0 m³), pero la malla no es válida: falla una cara."""
        values = np.maximum(_surface(20, 24), 806.0)
        raster = _raster(values)
        arrays = mesh.surface_mesh_from_raster(raster)
        z = arrays.vertices[:, 2][arrays.faces]
        flat = int(np.flatnonzero((z == 806.0).all(axis=1))[0])
        faces = arrays.faces.copy()
        faces[flat] = faces[flat][[0, 2, 1]]
        report = mesh.check_surface_mesh(arrays.vertices, faces, raster)
        self.assertEqual(report.base_m, 806.0)
        self.assertEqual(report.difference_m3, 0.0)
        self.assertEqual((report.faces_down, report.faces_degenerate), (1, 0))
        self.assertFalse(report.valid)
        self.assertIn("1 de sus", report.message())

    def test_degenerate_faces(self) -> None:
        """Caras sin normal hacia arriba que no van hacia abajo: con un vértice repetido,
        vertical (tres vértices alineados en planta, signo exacto) o con un vértice no finito;
        cuentan como degeneradas y la malla no es válida. Una astilla de 4,7·10⁻¹⁰ m² (un ulp
        del norte) sí tiene la normal hacia arriba, y también una casi alineada de 5,4·10⁻²⁰
        m² cuyo determinante en float64 sale 0 (signo exacto); al revés, van hacia abajo."""
        # a − c = (p, q) ulp y b − c = (r, s) ulp con p·s − q·r = 1: área exacta de medio
        # ulp(E0)·ulp(N0) = 2⁻⁶⁴ m², que los productos en float64 redondean a lo mismo.
        p, q, r, s = 2**33 - 1, 1_073_754_169, 2_465_101_874, 308_141_277
        self.assertEqual(p * s - q * r, 1)
        ux, uy = math.ulp(E0), math.ulp(N0)
        vertices = np.array([[E0, N0, 800.0], [E0 + 1.0, N0, 801.0], [E0, N0 + 1.0, 802.0],
                             [E0 + 1.0, N0 + 1.0, 803.0], [E0 + 3.0, N0 + 1.0, 800.0],
                             [E0 + 1.5, N0 + 0.5, 830.0], [E0 + 0.5, N0, 810.0],
                             [E0 + 0.5, N0 + math.ulp(N0), 805.0], [E0, NAN, 800.0],
                             [E0 + p * ux, N0 + q * uy, 801.0],
                             [E0 + r * ux, N0 + s * uy, 802.0]])
        a, b = vertices[9, :2] - vertices[0, :2], vertices[10, :2] - vertices[0, :2]
        self.assertEqual(a[0] * b[1] - a[1] * b[0], 0.0)  # en float64, alineados
        tin = _frozen_tin(gis.Tin(vertices[:4].copy(), np.array([[0, 1, 3], [0, 3, 2]],
                                                                dtype=np.int32),
                                  np.empty((0, 2), dtype=np.int32),
                                  np.zeros(4, dtype=np.uint8)))
        good = np.array([[0, 1, 3], [0, 3, 2]], dtype=np.int32)
        cases = (
            ("vértice repetido", [[0, 1, 1]], 1, 0),
            ("vertical", [[0, 5, 4]], 1, 0),
            ("no finito", [[0, 1, 8]], 1, 0),
            ("astilla", [[0, 1, 7]], 0, 0),
            ("astilla al revés", [[0, 7, 1]], 0, 1),
            ("casi alineada", [[9, 10, 0]], 0, 0),
            ("casi alineada al revés", [[10, 9, 0]], 0, 1),
        )
        for label, extra, degenerate, down in cases:
            with self.subTest(label):
                faces = np.vstack([good, np.array(extra, dtype=np.int32)])
                report = mesh.check_surface_mesh(_frozen(vertices), _frozen(faces, np.int32),
                                                 tin)
                self.assertEqual((report.faces_degenerate, report.faces_down),
                                 (degenerate, down))
                self.assertEqual(report.valid, degenerate + down == 0)
                self.assertTrue(math.isfinite(report.volume_m3))
                self.assertLessEqual(abs(report.difference_m3), 1e-6)

    def test_check_in_steps_is_the_check(self) -> None:
        """RF-006-21, RNF-006-09 (T50): la comprobación por trozos (``check_surface_mesh_steps``)
        da su avance (de 0 a 1, sin bajar) tras cada trozo y el mismo informe que de una vez:
        los recuentos y la cota base, iguales; el volumen y las áreas, sumados por trozos, a
        ≤ 1·10⁻¹² de ellos; con un solo trozo, bit a bit (``check_surface_mesh``). También con
        caras hacia abajo, degeneradas y con un vértice no finito, y sin caras."""
        vertices = self.vertices.copy()
        vertices[5, 2] = np.nan
        faces = self.faces.copy()
        faces[3] = faces[3][[0, 2, 1]]
        faces[7] = (faces[7][0], faces[7][0], faces[7][1])
        for label, verts, tris in (("válida", self.vertices, self.faces),
                                   ("con fallos", vertices, faces),
                                   ("sin caras", self.vertices, np.empty((0, 3), np.int32))):
            with self.subTest(label):
                whole = mesh.check_surface_mesh(_frozen(verts), _frozen(tris, np.int32),
                                                self.raster, name="mdt")
                for chunk in (1, 7, 100, len(tris) + 1):
                    steps = mesh.check_surface_mesh_steps(
                        _frozen(verts), _frozen(tris, np.int32), self.raster, name="mdt",
                        chunk_faces=chunk)
                    done = []
                    while True:
                        try:
                            done.append(next(steps))
                        except StopIteration as stop:
                            report = stop.value
                            break
                    self.assertEqual(done, sorted(done))
                    self.assertEqual((done[0], done[-1]), (0.0, 1.0))
                    for key in ("surface", "faces", "reference_faces", "faces_down",
                                "faces_degenerate", "base_m"):
                        self.assertEqual(getattr(report, key), getattr(whole, key), key)
                    for key in ("volume_m3", "reference_volume_m3", "plan_area_m2",
                                "reference_area_m2", "tolerance_m3"):
                        expected = getattr(whole, key)
                        if chunk >= max(len(tris), whole.reference_faces):  # un solo trozo
                            self.assertEqual(getattr(report, key), expected, key)
                        else:
                            self.assertAlmostEqual(getattr(report, key), expected,
                                                   delta=1e-12 * max(1.0, abs(expected)))
                    self.assertEqual(report.valid, whole.valid)
        with self.assertRaises(ValueError):
            next(mesh.check_surface_mesh_steps(self.vertices, self.faces, self.raster,
                                               chunk_faces=0))

    def test_tolerance_is_plan_area_times_half_a_millimetre(self) -> None:
        """La malla subida 0,4 mm cabe en la tolerancia (área en planta × 0,5 mm) y es
        válida; subida 0,6 mm, no."""
        for lift, valid in ((0.0004, True), (0.0006, False)):
            with self.subTest(lift=lift):
                vertices = self.vertices + np.array([0.0, 0.0, lift])
                report = self._check(vertices, self.faces)
                self.assertEqual(report.base_m, self.base)  # la de la superficie
                self.assertEqual(report.failed_faces, 0)
                self.assertAlmostEqual(report.difference_m3, lift * self.area,
                                       delta=1e-6 * lift * self.area)
                self.assertEqual(report.valid, valid)

    def test_tin_mesh_and_round_trip_through_float32_at_8_km(self) -> None:
        """HU-006-4: la malla de una rejilla y la de un TIN a ±8 km del origen, pasadas a
        locales en float32 (como en la vista) y vueltas a absolutas, están a ≤ 0,5 mm y son
        válidas frente a su superficie; invertidas, no."""
        raster = _raster(_surface(30, 50), west=E0 + 7_940.0, north=N0 - 7_960.0)
        tin = _frozen_tin(_cloud_tin(300, left=-8_000.0, bottom=7_900.0, size=100.0))
        for label, arrays, reference in (
                ("rejilla", mesh.surface_mesh_from_raster(raster), raster),
                ("TIN", mesh.surface_mesh_from_tin(tin), tin)):
            with self.subTest(label):
                local = georef.world_to_local(arrays.vertices, ORIGIN).astype(np.float32)
                back = georef.local_to_world(local, ORIGIN)
                self.assertLessEqual(float(np.abs(back - arrays.vertices).max()), 0.0005)
                self.assertGreater(float(np.abs(back - arrays.vertices).max()), 0.0)
                report = mesh.check_surface_mesh(back, arrays.faces, reference)
                self.assertTrue(report.valid, (report.difference_m3, report.tolerance_m3))
                self.assertLessEqual(abs(report.difference_m3), report.tolerance_m3 / 10)
                inverted = mesh.check_surface_mesh(back, arrays.faces[:, [0, 2, 1]],
                                                   reference)
                self.assertFalse(inverted.valid)
                self.assertEqual(inverted.faces_down, len(arrays.faces))

    def test_reference_tin_orientation_does_not_matter(self) -> None:
        """El volumen y el área de un TIN de referencia no dependen de cómo estén orientados
        sus triángulos: con la mitad horarios dan lo mismo y su malla (vuelta hacia arriba)
        es válida frente a él, con diferencia 0."""
        tin = _frozen_tin(_cloud_tin(120, seed=3))
        faces = tin.faces.copy()
        faces[1::2] = faces[1::2][:, [0, 2, 1]]
        clockwise = _frozen_tin(gis.Tin(tin.vertices, faces, tin.constraint_edges,
                                        tin.vertex_source))
        arrays = mesh.surface_mesh_from_tin(tin)
        straight = mesh.check_surface_mesh(arrays.vertices, arrays.faces, tin)
        turned = mesh.check_surface_mesh(arrays.vertices, arrays.faces, clockwise)
        self.assertTrue(straight.valid)
        self.assertTrue(turned.valid)
        self.assertEqual(straight.difference_m3, 0.0)
        self.assertAlmostEqual(turned.reference_volume_m3, straight.reference_volume_m3,
                               delta=1e-9 * straight.reference_volume_m3)
        self.assertAlmostEqual(turned.reference_area_m2, 3600.0, delta=1e-9)
        expected = float(np.sum(_prisms(tin.vertices, tin.faces, straight.base_m)))
        self.assertAlmostEqual(straight.reference_volume_m3, expected, delta=1e-9 * expected)

    def test_empty_mesh(self) -> None:
        """Una malla sin caras no es válida: área 0, tolerancia 0 y diferencia −V."""
        report = self._check(self.vertices, np.empty((0, 3), dtype=np.int32))
        self.assertFalse(report.valid)
        self.assertEqual((report.faces, report.failed_faces), (0, 0))
        self.assertEqual((report.plan_area_m2, report.tolerance_m3), (0.0, 0.0))
        self.assertAlmostEqual(report.difference_m3, -self.volume, delta=1e-9 * self.volume)

    def test_report_text_and_json(self) -> None:
        """El texto del informe (español e inglés) con las caras, la cota base y la
        diferencia y la tolerancia en m³ al litro; el informe pasa a JSON."""
        report = mesh.MeshReport(surface="topo", faces=120, reference_faces=130, faces_down=2,
                                 faces_degenerate=1, base_m=806.25, volume_m3=1500.0,
                                 reference_volume_m3=1612.3456, plan_area_m2=240.0,
                                 reference_area_m2=260.0, tolerance_m3=0.12)
        self.assertEqual(report.failed_faces, 3)
        self.assertAlmostEqual(report.difference_m3, -112.3456, delta=1e-9)
        self.assertFalse(report.valid)
        self.assertEqual(
            report.message(),
            "La malla de «topo» no es válida y no se muestra como superficie del proyecto: "
            "3 de sus 120 caras tienen la normal hacia abajo o son degeneradas (la "
            "superficie tiene 130) y su volumen sobre la cota 806,25 m difiere del de la "
            "superficie en -112,346 m³ (se admiten 0,12 m³). Vuelva a cargarla en la vista.")
        self.assertEqual(
            report.message(language="en"),
            "The mesh of «topo» is not valid and is not shown as a project surface: 3 of its "
            "120 faces face down or are degenerate (the surface has 130) and its volume above "
            "806.25 m differs from that of the surface by -112.346 m³ (0.12 m³ is allowed). "
            "Load it into the view again.")
        self.assertEqual(json.loads(json.dumps(dataclasses.asdict(report)))["faces"], 120)
        within = dataclasses.replace(report, faces_down=0, faces_degenerate=0,
                                     volume_m3=1612.4656)
        self.assertTrue(within.valid)
        self.assertFalse(dataclasses.replace(within, volume_m3=1612.4657).valid)

    def test_bad_inputs(self) -> None:
        """Vértices que no son ABS float64 (n, 3), caras que no son enteros (m, 3) con
        índices que existen o una referencia que no es rejilla ni TIN: errores del
        programa."""
        bad = (
            (TypeError, self.vertices.astype(np.float32), self.faces, self.raster),
            (TypeError, self.vertices, self.faces.astype(np.float64), self.raster),
            (ValueError, self.vertices[:, :2].copy(), self.faces, self.raster),
            (ValueError, self.vertices, self.faces[:, :2].copy(), self.raster),
            (ValueError, self.vertices, self.faces + len(self.vertices), self.raster),
            (ValueError, self.vertices, self.faces - 1, self.raster),
            (TypeError, self.vertices, self.faces, self.grid_mesh),
        )
        for error, vertices, faces, reference in bad:
            with self.subTest(error=error.__name__, dtype=str(faces.dtype)):
                with self.assertRaises(error):
                    mesh.check_surface_mesh(vertices, faces, reference)
        with self.assertRaises(TypeError):
            mesh.check_surface_mesh(self.vertices.tolist(), self.faces, self.raster)


class LodRastersTest(unittest.TestCase):
    """RF-006-22: versiones de 2 y 5 m por media de área, alineadas, de una rejilla de paso
    menor de 2 m, sin tocar la rejilla de cálculo."""

    def setUp(self) -> None:
        # 0,5 m de x ∈ [3; 30] e y ∈ [25; 47] (relativas): alineada a 1 m, no a 2 ni a 5.
        self.mask = np.zeros((44, 54), dtype=bool)
        self.mask[10:13, 20:27] = True
        self.values = _frozen(_surface(44, 54, dx=0.5, dy=0.5, mask=self.mask))
        self.raster = gis.Raster(gis.Grid(west=E0 + 3.0, north=N0 + 47.0, dx=0.5, dy=0.5,
                                          ncols=54, nrows=44), self.values, CRS, VERTICAL)

    def test_two_and_five_metre_versions_by_area_mean(self) -> None:
        """De 0,5 m: niveles de 2 y 5 m (los de ``gis.view.lod_steps_m``) en la rejilla
        alineada que cubre la de cálculo, cada celda la media de sus celdas de 0,5 m (sin
        dato si no está cubierta entera por celdas con dato), el volumen de las celdas con
        dato conservado (≤ 10⁻¹²) y su malla válida; la rejilla de cálculo, intacta."""
        before = self.values.tobytes()
        levels = mesh.lod_rasters(self.raster)
        self.assertEqual(tuple(levels), params.default("gis.view.lod_steps_m"))
        self.assertEqual(tuple(levels), (2.0, 5.0))
        for step, lod in levels.items():
            with self.subTest(step=step):
                self.assertIsInstance(lod, gis.Raster)
                self.assertIsNot(lod.values, self.values)
                self.assertTrue(lod.grid.same_geometry(gis.aligned_grid(
                    self.raster.grid.extent, step)))
                self.assertEqual((lod.grid.dx, lod.grid.dy), (step, step))
                unit = georef.alignment_unit(step)
                for edge in (lod.grid.west, lod.grid.north):
                    self.assertEqual(math.fmod(edge, unit), 0.0)
                self.assertIs(lod.crs, self.raster.crs)
                self.assertIs(lod.vertical, self.raster.vertical)
                expected = _area_mean(self.raster, lod.grid)
                np.testing.assert_array_equal(np.isnan(lod.values), np.isnan(expected))
                keep = np.isfinite(expected)
                self.assertGreater(int(keep.sum()), 4)
                np.testing.assert_allclose(lod.values[keep], expected[keep], rtol=0,
                                           atol=1e-9)
                # Volumen: el de las celdas de 0,5 m cuyo centro cae en una celda con dato.
                cx, cy = self.raster.grid.centers()
                col = np.floor((cx - lod.grid.west) / step).astype(np.int64)
                row = np.floor((lod.grid.north - cy) / step).astype(np.int64)
                source = float(np.sum(self.values[keep[row, col]])) * 0.25
                volume = float(np.sum(lod.values[keep])) * lod.grid.cell_area
                self.assertAlmostEqual(volume, source, delta=1e-12 * volume)
                arrays = mesh.surface_mesh_from_raster(lod)
                self.assertTrue(mesh.check_surface_mesh(arrays.vertices, arrays.faces,
                                                        lod).valid)
        self.assertEqual(self.values.tobytes(), before)

    def test_only_for_grids_below_the_first_level(self) -> None:
        """Con paso de 2 m o más, ninguna versión; con 1,5 m o los pasos de B24 (celdas que
        no encajan en las del nivel), las dos, alineadas y con la media ponderada por el área
        de solape de cada celda."""
        for step in (2.0, 2.5, 5.0):
            with self.subTest(step=step):
                raster = _raster(_surface(8, 9, dx=step, dy=step), dx=step, dy=step)
                self.assertEqual(mesh.lod_rasters(raster), {})
        for dx, dy in ((1.5, 1.5), (B24_DX, B24_DY)):
            with self.subTest(dx=dx, dy=dy):
                raster = _raster(_surface(23, 31, dx=dx, dy=dy), dx=dx, dy=dy,
                                 west=E0 + 0.25)
                levels = mesh.lod_rasters(raster)
                self.assertEqual(tuple(levels), (2.0, 5.0))
                for step, lod in levels.items():
                    self.assertTrue(lod.grid.same_geometry(gis.aligned_grid(
                        raster.grid.extent, step)))
                    expected = _area_mean(raster, lod.grid)
                    keep = np.isfinite(expected)
                    self.assertTrue(keep.any())
                    np.testing.assert_array_equal(np.isfinite(lod.values), keep)
                    np.testing.assert_allclose(lod.values[keep], expected[keep], rtol=0,
                                               atol=1e-9)

    def test_custom_steps_and_fraction(self) -> None:
        """Otros niveles (1 y 2,5 m) y otra fracción mínima: con 0,5 las celdas del borde
        a medio cubrir tienen la media de lo cubierto."""
        levels = mesh.lod_rasters(self.raster, steps_m=(1.0, 2.5))
        self.assertEqual(tuple(levels), (1.0, 2.5))
        strict = mesh.lod_rasters(self.raster)[5.0]
        loose = mesh.lod_rasters(self.raster, min_valid_fraction=0.5)[5.0]
        self.assertGreater(int(np.isfinite(loose.values).sum()),
                           int(np.isfinite(strict.values).sum()))
        same = np.isfinite(strict.values)
        np.testing.assert_array_equal(loose.values[same], strict.values[same])

    def test_invalid_steps(self) -> None:
        """Niveles que no son una lista creciente de dos pasos del parámetro, o que no son
        pasos de rejilla del proyecto: ``ParamError`` ``core.param_*`` con la clave (RF-006-22)
        o ``gis.step_invalid``."""
        cases = (
            ((2.0, 2.0), ParamError, "core.param_not_list"),
            ((5.0, 2.0), ParamError, "core.param_not_list"),
            ((2.0,), ParamError, "core.param_not_list"),
            ("2", ParamError, "core.param_not_list"),
            ((2.0, 300.0), ParamError, "core.param_out_of_range"),
            ((2.0, 10.0), gis.GisError, "gis.step_invalid"),
            ((0.75, 2.0), gis.GisError, "gis.step_invalid"),
        )
        coarse = _raster(_surface(4, 4, dx=5.0, dy=5.0), dx=5.0, dy=5.0)
        for steps, error, code in cases:
            for raster in (self.raster, coarse):  # también sin niveles que calcular
                with self.subTest(steps=steps, dx=raster.grid.dx):
                    with self.assertRaises(error) as caught:
                        mesh.lod_rasters(raster, steps_m=steps)
                    self.assertEqual(caught.exception.code, code)
                    if error is ParamError:
                        self.assertEqual(caught.exception.field, mesh.LOD_STEPS_KEY)
        with self.assertRaises(TypeError):
            mesh.lod_rasters(_cloud_tin(20))

    def test_progress_and_cancel(self) -> None:
        """El avance crece hasta 1 por los dos niveles; la cancelación lanza
        ``JobCancelled``."""
        steps = []
        mesh.lod_rasters(self.raster, progress=lambda f, text: steps.append((f, text)))
        fractions = [f for f, _text in steps]
        self.assertEqual(fractions, sorted(fractions))
        self.assertEqual(fractions[-1], 1.0)
        self.assertEqual(max(f for f, text in steps if " 2 m:" in text), 0.5)
        self.assertTrue(any(" 5 m:" in text for _f, text in steps))
        with self.assertRaises(worker_api.JobCancelled):
            mesh.lod_rasters(self.raster, cancelled=lambda: True)


if __name__ == "__main__":
    unittest.main()

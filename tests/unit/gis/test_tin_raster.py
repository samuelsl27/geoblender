# SPDX-License-Identifier: GPL-3.0-or-later
"""TIN ⇄ rejilla, muestreo de un TIN y validación de un TIN (spec 006, T19; plan 006 §5.3.2 y
§5.4 A13 y A17; ``gis.tin`` y ``gis.validate``).

- **RF-006-17**: ``tin_to_raster(tin, grid, *, crs, vertical)`` interpola linealmente dentro
  de cada triángulo en los centros de celda (coordenadas baricéntricas, todas ≥ −10⁻¹²: un
  centro sobre una arista o sobre el borde del TIN tiene cota) y deja sin dato las celdas
  fuera del TIN o en sus huecos; ``raster_to_tin(raster)`` triangula los centros de las
  celdas con dato: dos triángulos por cuadro de cuatro centros con dato, con la diagonal fija
  (i, j)–(i+1, j+1), y uno si tiene tres. Un plano se reproduce en las dos direcciones
  (≤ 10⁻⁹ m); la ida y vuelta rejilla → TIN → rejilla devuelve las mismas cotas bit a bit
  (el RF pide ≤ 10⁻⁶ m), también con el MDT de ``geotiff/f64_strip.tif`` (con su hueco) y con
  los pasos de B24; solo una celda con dato sin dos vecinas con dato en un cuadro (aislada o
  en una línea de una celda de ancho) queda sin dato al volver. A ambos lados de una línea de
  rotura cada celda toma la cota de su triángulo: un tejado con la cumbrera oblicua como
  rotura dura sale exacto (≤ 10⁻⁹ m) y, sin la rotura, con más de 1 cm de error.
  ``sample_tin`` da lo mismo en puntos cualesquiera (bit a bit en los centros).
- **RF-006-23**: ``validate_tin(tin, *, window, z_range)`` informa del % de triángulos planos,
  del lado máximo y de los degenerados (área < 10⁻⁶ m²; los tres, iguales a los del informe de
  ``build_tin``), del área (la que encierra su borde exterior) y del área neta de cada hueco
  interior (de mayor a menor; con una isla dentro, sin ella; dos huecos que se tocan en un
  vértice son dos), de los triángulos con algún vértice fuera de la ventana de trabajo y de
  los vértices con la cota fuera del rango plausible.

Las referencias son independientes: interpolación por cocientes de áreas triángulo a
triángulo, cuadros contados celda a celda y áreas de hueco contadas a mano en cuadros de la
rejilla. Las entradas no se modifican (arrays de solo lectura).
"""

import math
import unittest
from unittest import mock

import numpy as np

from tests.support.package import import_geoblender
from tests.support.repo import ROOT

gis = import_geoblender("gis")
tin_module = import_geoblender("gis.tin")
validate = import_geoblender("gis.validate")
points = import_geoblender("gis.points")
cdt = import_geoblender("gis.cdt")
geotiff = import_geoblender("gis.geotiff")
georef = import_geoblender("core.georef")
ParamError = import_geoblender("core.params").ParamError
csv_tables = import_geoblender("interop.csv_tables")
worker_api = import_geoblender("jobs.worker_api")

NAN = math.nan
DATA = ROOT / "tests" / "data" / "gis"
CATALOG = georef.load_catalog()
CRS = CATALOG.horizontal(25830)
VERTICAL = CATALOG.vertical(5782)
E0, N0 = 700_000.0, 4_400_000.0
ORIGIN = georef.GeoOrigin(700_000, 4_400_000, 0)
TOL = 1e-12  # tolerancia de las coordenadas baricéntricas (plan A13)
B24_DX = 1.0002942907592702
B24_DY = 1.0003022974607014
ROLES = {"point_id": "P", "x": "X", "y": "Y", "z": "Z", "code": "Código", "line": "Línea"}


def _frozen(array) -> np.ndarray:
    array = np.array(array, dtype=np.float64)
    array.flags.writeable = False  # una entrada nunca se modifica
    return array


def _raster(values, *, dx: float = 1.0, dy: float = 1.0, west: float = E0,
            north: float = N0 + 50.0):
    array = _frozen(values)
    nrows, ncols = array.shape
    grid = gis.Grid(west=west, north=north, dx=dx, dy=dy, ncols=ncols, nrows=nrows)
    return gis.Raster(grid, array, CRS, VERTICAL)


def _grid(ncols: int, nrows: int, *, dx: float = 1.0, dy: float = 1.0, west: float = E0,
          north: float = N0 + 50.0):
    return gis.Grid(west=west, north=north, dx=dx, dy=dy, ncols=ncols, nrows=nrows)


def _mask(layout) -> np.ndarray:
    return np.array([[cell == "#" for cell in row] for row in layout], dtype=bool)


def _surface(nrows: int, ncols: int, *, mask=None, dx: float = 1.0, dy: float = 1.0):
    """La superficie de ``tests/data/gis`` (z = 800 + 0,5x − 0,25y + 3 sin(x/7), relativas a
    E0 y N0, en los centros) en una rejilla con norte N0 + 50 m, sin dato en ``mask``."""
    cols = np.arange(ncols, dtype=np.float64)
    rows = np.arange(nrows, dtype=np.float64)
    x = (cols + 0.5) * dx
    y = 50.0 - (rows + 0.5) * dy
    values = 800.0 + 0.5 * x[None, :] - 0.25 * y[:, None] + 3.0 * np.sin(x[None, :] / 7.0)
    if mask is not None:
        values[mask] = NAN
    return values


def _plane(x, y):
    """El plano de las pruebas, con x e y ABSOLUTAS."""
    return 812.5 + 0.37 * (x - E0) - 0.21 * (y - N0)


def _point_set(xyz):
    xyz = _frozen(xyz)
    count = len(xyz)
    return points.PointSet(xyz, tuple(f"P{i + 1}" for i in range(count)), ("",) * count,
                           tuple(range(2, count + 2)))


def _plane_cloud(count: int = 160, seed: int = 19):
    """Nube al azar en x ∈ [0, 80], y ∈ [0, 40] (relativas) con sus cuatro esquinas, sobre
    el plano: su TIN (con ``PureTriangulator``)."""
    rng = np.random.default_rng(seed)
    xy = np.vstack([[[0.0, 0.0], [80.0, 0.0], [80.0, 40.0], [0.0, 40.0]],
                    rng.uniform((0.0, 0.0), (80.0, 40.0), size=(count, 2))])
    x, y = E0 + xy[:, 0], N0 + xy[:, 1]
    return _point_set(np.column_stack([x, y, _plane(x, y)]))


def _build(point_set, lines=(), **options):
    tin, _report = gis.build_tin(point_set, list(lines), triangulator=cdt.PureTriangulator(),
                                 origin=ORIGIN, **options)
    return tin


def _centers(grid):
    x, y = grid.centers()
    return x, y


def _brute(tin, x, y) -> np.ndarray:
    """Interpolación de referencia, triángulo a triángulo: la cota del primer triángulo (en su
    orden) cuyas tres coordenadas de área (cocientes de áreas, otra fórmula que la del
    módulo) son ≥ −10⁻¹²; NaN si ninguno."""
    x = np.asarray(x, dtype=np.float64).ravel()
    y = np.asarray(y, dtype=np.float64).ravel()
    out = np.full(x.shape, NAN)
    v = tin.vertices
    for a, b, c in tin.faces.tolist():
        (ax, ay, az), (bx, by, bz), (cx, cy, cz) = v[a], v[b], v[c]
        total = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
        if total == 0.0:
            continue
        with np.errstate(invalid="ignore"):  # puntos no finitos: ningún triángulo
            wa = ((bx - x) * (cy - y) - (by - y) * (cx - x)) / total
            wb = ((cx - x) * (ay - y) - (cy - y) * (ax - x)) / total
            wc = ((ax - x) * (by - y) - (ay - y) * (bx - x)) / total
            inside = np.isnan(out) & (wa >= -TOL) & (wb >= -TOL) & (wc >= -TOL)
            out[inside] = (wa * az + wb * bz + wc * cz)[inside]
    return out


def _same(test, got: np.ndarray, expected: np.ndarray) -> None:
    """Iguales bit a bit, con NaN en los mismos sitios."""
    test.assertEqual(got.shape, expected.shape)
    np.testing.assert_array_equal(np.isnan(got), np.isnan(expected))
    keep = ~np.isnan(expected)
    test.assertEqual(got[keep].tobytes(), expected[keep].tobytes())


def _covered(valid: np.ndarray) -> np.ndarray:
    """Las celdas con dato que son vértice de algún triángulo de ``raster_to_tin``: esquina
    con dato de un cuadro de 2 × 2 con al menos tres esquinas con dato, celda a celda."""
    nrows, ncols = valid.shape
    covered = np.zeros_like(valid)
    for row in range(nrows - 1):
        for col in range(ncols - 1):
            quad = valid[row:row + 2, col:col + 2]
            if quad.sum() >= 3:
                covered[row:row + 2, col:col + 2] |= quad
    return covered


def _normal_z(tin) -> np.ndarray:
    a, b, c = (tin.vertices[tin.faces[:, k]] for k in range(3))
    u, v = b - a, c - a
    return u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]


def _triangle_area(tin) -> float:
    return float(np.sum(0.5 * _normal_z(tin)))


def _validate(tin, **options):
    xy = tin.vertices[:, :2]
    window = options.pop("window", georef.Window(*xy.min(axis=0), *(xy.max(axis=0) + 1.0)))
    return validate.validate_tin(tin, window=window, **options)


class TinToRasterTest(unittest.TestCase):
    """RF-006-17: TIN → rejilla, interpolación lineal en los centros; fuera, sin dato."""

    def test_plane_and_cells_outside(self) -> None:
        """Un TIN de un plano (164 puntos al azar) en una rejilla de 1 m que se sale de él por
        los cuatro lados: las celdas con centro en el TIN dan el plano (≤ 10⁻⁹ m) y las mismas
        que la referencia triángulo a triángulo; las de fuera, sin dato. El ráster lleva la
        rejilla, el CRS y la referencia vertical pedidos."""
        tin = _build(_plane_cloud())
        grid = _grid(96, 52, west=E0 - 8.0, north=N0 + 46.0)
        raster = gis.tin_to_raster(tin, grid, crs=CRS, vertical=VERTICAL)
        self.assertIs(raster.grid, grid)
        self.assertIs(raster.crs, CRS)
        self.assertIs(raster.vertical, VERTICAL)
        self.assertEqual(raster.values.dtype, np.float64)
        x, y = _centers(grid)
        expected = _brute(tin, x, y).reshape(grid.shape)
        np.testing.assert_array_equal(np.isnan(raster.values), np.isnan(expected))
        inside = (x > E0) & (x < E0 + 80.0) & (y > N0) & (y < N0 + 40.0)
        np.testing.assert_array_equal(~np.isnan(raster.values), inside)
        self.assertEqual(int(inside.sum()), 80 * 40)
        np.testing.assert_allclose(raster.values[inside], _plane(x, y)[inside], rtol=0,
                                   atol=1e-9)
        np.testing.assert_allclose(raster.values[inside], expected[inside], rtol=0, atol=1e-9)

    def test_holes_are_nodata(self) -> None:
        """Un TIN con dos huecos (``build_tin`` con ``holes``): las celdas con el centro en un
        hueco (sin triángulo) quedan sin dato, igual que en la referencia."""
        hole_a = _frozen([(E0 + 10.0, N0 + 10.0), (E0 + 30.0, N0 + 10.0),
                          (E0 + 30.0, N0 + 25.0), (E0 + 10.0, N0 + 25.0)])
        hole_b = _frozen([(E0 + 50.0, N0 + 5.0), (E0 + 70.0, N0 + 20.0),
                          (E0 + 55.0, N0 + 30.0)])
        tin = _build(_plane_cloud(400, seed=5), holes=[hole_a, hole_b])
        grid = _grid(80, 40, north=N0 + 40.0)
        raster = gis.tin_to_raster(tin, grid, crs=CRS, vertical=VERTICAL)
        x, y = _centers(grid)
        expected = _brute(tin, x, y).reshape(grid.shape)
        np.testing.assert_array_equal(np.isnan(raster.values), np.isnan(expected))
        holes = int(np.isnan(raster.values).sum())
        self.assertGreater(holes, 200)
        middle = (x == E0 + 20.5) & (y == N0 + 17.5)
        self.assertEqual(int(middle.sum()), 1)
        self.assertTrue(np.isnan(raster.values[middle]).all())
        keep = ~np.isnan(expected)
        np.testing.assert_allclose(raster.values[keep], _plane(x, y)[keep], rtol=0, atol=1e-9)

    def test_each_cell_takes_its_triangle_across_a_breakline(self) -> None:
        """Tejado con la cumbrera oblicua y = 0,3x + 2 (cota 100 m) y faldones planos
        z = 100 − 0,5·|y − 0,3x − 2|: con la cumbrera como rotura dura, ningún triángulo la
        cruza y cada una de las 2.000 celdas de 1 m toma la cota de su faldón (≤ 10⁻⁹ m),
        también las que están a menos de un metro de la cumbrera, a uno y otro lado. Sin la
        rotura, con los mismos vértices, hay celdas con más de 1 cm de error."""
        rng = np.random.default_rng(23)
        xy = np.vstack([[[0.0, -20.0], [40.0, -20.0], [40.0, 30.0], [0.0, 30.0]],
                        rng.uniform((0.0, -20.0), (40.0, 30.0), size=(120, 2))])

        def roof(rel_x, rel_y):
            return 100.0 - 0.5 * np.abs(rel_y - 0.3 * rel_x - 2.0)

        cloud = _point_set(np.column_stack([E0 + xy[:, 0], N0 + xy[:, 1],
                                            roof(xy[:, 0], xy[:, 1])]))
        ridge_x = np.array([0.0, 10.0, 20.0, 30.0, 40.0])
        ridge = np.column_stack([E0 + ridge_x, N0 + 0.3 * ridge_x + 2.0,
                                 np.full(5, 100.0)])
        grid = _grid(40, 50, north=N0 + 30.0)
        x, y = _centers(grid)
        want = roof(x - E0, y - N0)

        line = points.Breakline("cumbrera", _frozen(ridge), hard=True)
        with_line = gis.tin_to_raster(_build(cloud, [line]), grid, crs=CRS, vertical=VERTICAL)
        self.assertFalse(np.isnan(with_line.values).any())
        np.testing.assert_allclose(with_line.values, want, rtol=0, atol=1e-9)
        near = np.abs((y - N0) - 0.3 * (x - E0) - 2.0) < 1.0
        self.assertGreater(int(near.sum()), 60)
        above = near & ((y - N0) > 0.3 * (x - E0) + 2.0)
        self.assertGreater(int(above.sum()), 20)
        self.assertGreater(int((near & ~above).sum()), 20)

        merged = _point_set(np.vstack([cloud.xyz, ridge]))
        without = gis.tin_to_raster(_build(merged), grid, crs=CRS, vertical=VERTICAL)
        self.assertGreater(float(np.max(np.abs(without.values - want))), 0.01)

    def test_centres_on_shared_edges_and_on_the_border(self) -> None:
        """Dos triángulos plegados por la diagonal SO–NE, con los vértices en centros de
        celda: los 25 centros tienen cota, también los de la diagonal compartida y los del
        borde del TIN, la de su faldón (los de la diagonal, la de la arista: los dos
        triángulos dan lo mismo), y los vértices, su cota exacta."""
        def rel(x, y):
            return (E0 + x, N0 + y)

        vertices = np.array([(*rel(0.5, 0.5), 0.0), (*rel(4.5, 0.5), 10.0),
                             (*rel(4.5, 4.5), 4.0), (*rel(0.5, 4.5), -10.0)])
        tin = gis.Tin(vertices, np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int32),
                      np.empty((0, 2), dtype=np.int32), np.zeros(4, dtype=np.uint8))
        grid = _grid(5, 5, north=N0 + 5.0)
        raster = gis.tin_to_raster(tin, grid, crs=CRS, vertical=VERTICAL)
        x, y = _centers(grid)
        u, v = x - E0 - 0.5, y - N0 - 0.5
        want = np.where(u >= v, 2.5 * u - 1.5 * v, 3.5 * u - 2.5 * v)
        self.assertFalse(np.isnan(raster.values).any())
        np.testing.assert_allclose(raster.values, want, rtol=0, atol=1e-12)
        corners = {(4, 0): 0.0, (4, 4): 10.0, (0, 4): 4.0, (0, 0): -10.0}
        for (row, col), z in corners.items():
            self.assertEqual(raster.values[row, col], z)

    def test_batches_progress_and_cancel(self) -> None:
        """Por lotes de un triángulo y de 7 parejas (triángulo, celda) el resultado es el
        mismo bit a bit; el avance llega a 1 y la cancelación lanza ``JobCancelled``."""
        tin = _build(_plane_cloud(60, seed=3))
        grid = _grid(40, 20, dx=2.0, dy=2.0, north=N0 + 40.0)
        whole = gis.tin_to_raster(tin, grid, crs=CRS, vertical=VERTICAL)
        steps = []
        with mock.patch.object(tin_module, "_TRIANGLE_BATCH", 1), \
                mock.patch.object(tin_module, "_SAMPLE_PAIRS", 7):
            parts = gis.tin_to_raster(tin, grid, crs=CRS, vertical=VERTICAL,
                                      progress=lambda f, text: steps.append((f, text)))
        _same(self, parts.values, whole.values)
        self.assertEqual(len(steps), len(tin.faces))
        self.assertEqual(steps[-1][0], 1.0)
        self.assertEqual([f for f, _ in steps], sorted(f for f, _ in steps))
        self.assertIn("TIN", steps[0][1])
        with self.assertRaises(worker_api.JobCancelled):
            gis.tin_to_raster(tin, grid, crs=CRS, vertical=VERTICAL, cancelled=lambda: True)

    def test_centres_on_diagonals_do_not_depend_on_batches(self) -> None:
        """TIN de una rejilla de pasos B24 y rejilla desplazada medio paso: cada centro cae,
        salvo el redondeo de las coordenadas, en la diagonal de un cuadro y vale la media de
        sus dos extremos (≤ 10⁻⁹ m); por lotes de un triángulo sale lo mismo, bit a bit."""
        raster = _raster(_surface(12, 15, dx=B24_DX, dy=B24_DY), dx=B24_DX, dy=B24_DY)
        tin = gis.raster_to_tin(raster)
        grid = _grid(14, 11, dx=B24_DX, dy=B24_DY, west=E0 + 0.5 * B24_DX,
                     north=N0 + 50.0 - 0.5 * B24_DY)
        whole = gis.tin_to_raster(tin, grid, crs=CRS, vertical=VERTICAL)
        values = raster.values
        np.testing.assert_allclose(whole.values, 0.5 * (values[:-1, :-1] + values[1:, 1:]),
                                   rtol=0, atol=1e-9)
        with mock.patch.object(tin_module, "_TRIANGLE_BATCH", 1):
            parts = gis.tin_to_raster(tin, grid, crs=CRS, vertical=VERTICAL)
        _same(self, parts.values, whole.values)

    def test_bad_inputs(self) -> None:
        tin = _build(_plane_cloud(20))
        grid = _grid(10, 10)
        with self.assertRaises(TypeError):
            gis.tin_to_raster(tin.vertices, grid, crs=CRS, vertical=VERTICAL)
        with self.assertRaises(TypeError):
            gis.tin_to_raster(tin, (E0, N0, 1.0), crs=CRS, vertical=VERTICAL)
        with self.assertRaises(TypeError):
            gis.tin_to_raster(tin, grid, crs="EPSG:25830", vertical=VERTICAL)
        with self.assertRaises(TypeError):
            gis.tin_to_raster(tin, grid, crs=CRS, vertical=None)


class RasterToTinTest(unittest.TestCase):
    """RF-006-17: rejilla → TIN con los centros de las celdas con dato; ida y vuelta."""

    def test_plane_grid_to_tin(self) -> None:
        """Un plano en una rejilla de pasos B24 (13 × 9): 117 vértices en los centros, bit a
        bit, con su cota y origen «centro de celda» (5); 2 triángulos por cuadro (192), con la
        normal hacia arriba y la diagonal (i, j)–(i+1, j+1); sin aristas obligatorias; el TIN
        da el plano en 500 puntos al azar (≤ 10⁻⁹ m)."""
        grid = _grid(13, 9, dx=B24_DX, dy=B24_DY, west=E0 + 123.25, north=N0 + 321.5)
        x, y = grid.centers()
        raster = gis.Raster(grid, _frozen(_plane(x, y)), CRS, VERTICAL)
        tin = gis.raster_to_tin(raster)
        want = np.column_stack([x.ravel(), y.ravel(), raster.values.ravel()])
        self.assertEqual(tin.vertices.dtype, np.float64)
        self.assertEqual(tin.vertices.tobytes(), want.tobytes())
        self.assertEqual(tin.vertex_source.tolist(), [5] * 117)
        self.assertEqual(tin.faces.dtype, np.int32)
        self.assertEqual(len(tin.faces), 2 * 12 * 8)
        self.assertEqual(tin.constraint_edges.shape, (0, 2))
        self.assertEqual(tin.triangulator, tin_module.GRID_TRIANGULATOR)
        self.assertTrue((_normal_z(tin) > 0.0).all())
        edges = {tuple(sorted(pair)) for face in tin.faces.tolist()
                 for pair in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0]))}
        self.assertIn((0, 14), edges)       # (0, 0)–(1, 1)
        self.assertNotIn((1, 13), edges)    # (0, 1)–(1, 0)
        rng = np.random.default_rng(7)
        extent = (x.min(), y.min(), x.max(), y.max())
        px = rng.uniform(extent[0], extent[2], 500)
        py = rng.uniform(extent[1], extent[3], 500)
        got = gis.sample_tin(tin, _frozen(np.column_stack([px, py])))
        self.assertFalse(np.isnan(got).any())
        np.testing.assert_allclose(got, _plane(px, py), rtol=0, atol=1e-9)

    def test_round_trip_of_the_fixture(self) -> None:
        """``geotiff/f64_strip.tif`` (64 × 48, hueco de 3 × 4 celdas) → TIN → la misma
        rejilla: las 3.060 cotas con dato, bit a bit (error 0 ≤ 10⁻⁶ m), y el hueco, sin
        dato."""
        source = geotiff.read_geotiff(DATA / "geotiff" / "f64_strip.tif")
        source.values.flags.writeable = False
        raster = gis.Raster(source.grid, source.values, CRS, VERTICAL)
        back = gis.tin_to_raster(gis.raster_to_tin(raster), raster.grid, crs=CRS,
                                 vertical=VERTICAL)
        _same(self, back.values, raster.values)
        self.assertEqual(int(np.isfinite(back.values).sum()), 64 * 48 - 12)
        self.assertLessEqual(float(np.nanmax(np.abs(back.values - raster.values))), 1e-6)

    def test_round_trip_with_nodata_and_b24_steps(self) -> None:
        """Rejilla de pasos B24 con sin dato exterior, huecos, esquinas de tres celdas, una
        celda aislada y una línea de una celda de ancho: vuelven bit a bit todas las celdas
        que son esquina de un cuadro con tres o cuatro centros con dato (contadas celda a
        celda); la aislada y la línea quedan sin dato, como el sin dato."""
        layout = (
            "##..........#.##",
            "#...........#.##",
            "#..##.......#.##",
            "...#....#...####",
            "...##...........",
            "................",
            "................",
            "............####",
            "###.........##.#",
            "####.......#####",
        )
        mask = _mask(layout)
        raster = _raster(_surface(10, 16, mask=mask, dx=B24_DX, dy=B24_DY), dx=B24_DX,
                         dy=B24_DY)
        tin = gis.raster_to_tin(raster)
        back = gis.tin_to_raster(tin, raster.grid, crs=CRS, vertical=VERTICAL)
        covered = _covered(~mask)
        expected = np.where(covered, raster.values, NAN)
        _same(self, back.values, expected)
        self.assertEqual(len(tin.vertices), int(covered.sum()))
        lost = ~mask & ~covered
        self.assertEqual(sorted(zip(*np.nonzero(lost), strict=True)),
                         [(0, 13), (1, 13), (2, 13), (8, 14)])

    def test_three_of_four_corners(self) -> None:
        """Un cuadro de 2 × 2 con una esquina sin dato da un triángulo antihorario con las
        otras tres; con las cuatro, dos con la diagonal NO–SE."""
        cases = {(0, 0): {(0, 1), (1, 0), (1, 1)}, (0, 1): {(0, 0), (1, 0), (1, 1)},
                 (1, 0): {(0, 0), (0, 1), (1, 1)}, (1, 1): {(0, 0), (0, 1), (1, 0)}}
        for missing, cells in cases.items():
            with self.subTest(missing=missing):
                values = np.array([[10.0, 11.0], [12.0, 13.0]])
                values[missing] = NAN
                raster = _raster(values)
                tin = gis.raster_to_tin(raster)
                self.assertEqual(len(tin.faces), 1)
                self.assertGreater(float(_normal_z(tin)[0]), 0.0)
                x, y = raster.grid.centers()
                want = {(float(x[c]), float(y[c]), float(values[c])) for c in cells}
                self.assertEqual({tuple(map(float, v)) for v in tin.vertices}, want)
        tin = gis.raster_to_tin(_raster([[10.0, 11.0], [12.0, 13.0]]))
        self.assertEqual(tin.faces.tolist(), [[0, 2, 3], [0, 3, 1]])

    def test_without_triangles(self) -> None:
        """Sin ningún cuadro con tres celdas con dato (todo sin dato, una sola fila, un
        tablero de ajedrez) → ``gis.grid_tin_empty`` con el número de celdas con dato."""
        board = np.where((np.indices((6, 6)).sum(axis=0) % 2) == 0, 800.0, NAN)
        for name, values, valid in (("vacía", np.full((4, 5), NAN), 0),
                                    ("fila", np.full((1, 6), 800.0), 6),
                                    ("columna", np.full((5, 1), 800.0), 5),
                                    ("tablero", board, 18)):
            with self.subTest(name), self.assertRaises(gis.GisError) as caught:
                gis.raster_to_tin(_raster(values), name="mdt")
            self.assertEqual(caught.exception.code, "gis.grid_tin_empty")
            self.assertEqual(caught.exception.value, valid)
            self.assertIn("mdt", str(caught.exception))

    def test_row_blocks_progress_and_cancel(self) -> None:
        """Por bloques de un cuadro el TIN es el mismo; avance hasta 1 y cancelación."""
        raster = _raster(_surface(10, 16, mask=_mask(("#" * 3 + "." * 13,) + ("." * 16,) * 9)))
        whole = gis.raster_to_tin(raster)
        steps = []
        with mock.patch.object(tin_module, "_QUAD_BLOCK", 1):
            parts = gis.raster_to_tin(raster, progress=lambda f, text: steps.append(f))
        self.assertEqual(parts.vertices.tobytes(), whole.vertices.tobytes())
        self.assertEqual(parts.faces.tobytes(), whole.faces.tobytes())
        self.assertEqual(len(steps), 9)
        self.assertEqual(steps[-1], 1.0)
        with self.assertRaises(worker_api.JobCancelled):
            gis.raster_to_tin(raster, cancelled=lambda: True)
        calls = iter([False, False, True])
        with mock.patch.object(tin_module, "_QUAD_BLOCK", 1), \
                self.assertRaises(worker_api.JobCancelled) as caught:
            gis.raster_to_tin(raster, cancelled=lambda: next(calls))
        self.assertIn("bloque 3 de 9", str(caught.exception))

    def test_steps_give_the_same_tin(self) -> None:
        """RF-006-17, RNF-006-09 (T50): ``raster_to_tin_steps`` da ``(hechos, bloques)`` antes
        del primer bloque y tras cada uno y el mismo TIN, bit a bit (así lo convierte la vista
        en pasos desde un temporizador); con una sola fila, ``(0, 0)`` y el error de siempre."""
        raster = _raster(_surface(10, 16, mask=_mask(("#" * 3 + "." * 13,) + ("." * 16,) * 9)))
        whole = gis.raster_to_tin(raster)
        with mock.patch.object(tin_module, "_QUAD_BLOCK", 1):
            steps = tin_module.raster_to_tin_steps(raster)
            seen = []
            while True:
                try:
                    seen.append(next(steps))
                except StopIteration as stop:
                    tin = stop.value
                    break
        self.assertEqual(seen, [(index, 9) for index in range(10)])
        for array in ("vertices", "faces", "constraint_edges", "vertex_source"):
            self.assertEqual(getattr(tin, array).tobytes(), getattr(whole, array).tobytes())
        steps = tin_module.raster_to_tin_steps(_raster(np.full((1, 6), 800.0)), name="mdt")
        self.assertEqual(next(steps), (0, 0))
        with self.assertRaises(gis.GisError):
            next(steps)

    def test_input_untouched_and_bad_inputs(self) -> None:
        raster = _raster(_surface(5, 6))
        before = raster.values.copy()
        tin = gis.raster_to_tin(raster)
        gis.tin_to_raster(tin, raster.grid, crs=CRS, vertical=VERTICAL)
        np.testing.assert_array_equal(raster.values, before)
        self.assertFalse(np.shares_memory(tin.vertices, raster.values))
        with self.assertRaises(TypeError):
            gis.raster_to_tin(raster.values)


class SampleTinTest(unittest.TestCase):
    """RF-006-17: el TIN en puntos cualesquiera (la misma regla que en los centros)."""

    def test_matches_tin_to_raster_and_reference(self) -> None:
        """En los centros de una rejilla, bit a bit lo de ``tin_to_raster``; en 2.000 puntos
        al azar (dentro y fuera), lo de la referencia (≤ 10⁻⁹ m), NaN fuera."""
        tin = _build(_plane_cloud(200, seed=11))
        grid = _grid(45, 25, dx=2.0, dy=2.0, west=E0 - 5.0, north=N0 + 45.0)
        x, y = grid.centers()
        sampled = gis.sample_tin(tin, _frozen(np.column_stack([x.ravel(), y.ravel()])))
        raster = gis.tin_to_raster(tin, grid, crs=CRS, vertical=VERTICAL)
        _same(self, sampled, raster.values.ravel())
        rng = np.random.default_rng(31)
        px = rng.uniform(E0 - 10.0, E0 + 90.0, 2000)
        py = rng.uniform(N0 - 10.0, N0 + 50.0, 2000)
        got = gis.sample_tin(tin, _frozen(np.column_stack([px, py])))
        expected = _brute(tin, px, py)
        np.testing.assert_array_equal(np.isnan(got), np.isnan(expected))
        keep = ~np.isnan(expected)
        self.assertGreater(int(keep.sum()), 900)
        np.testing.assert_allclose(got[keep], expected[keep], rtol=0, atol=1e-9)

    def test_degenerate_query_sets(self) -> None:
        """Puntos no finitos → NaN; todos en el mismo sitio, en una vertical o en una
        horizontal; ninguno; uno sobre un vértice → su cota exacta."""
        tin = _build(_plane_cloud(50, seed=2))
        vertex = tin.vertices[7]
        cases = {
            "no finitos": [(NAN, N0 + 5.0), (E0 + 5.0, math.inf), (E0 + 5.0, N0 + 5.0)],
            "mismo sitio": [(E0 + 5.0, N0 + 5.0)] * 3,
            "vertical": [(E0 + 5.0, N0 + k) for k in (1.0, 2.0, 30.0)],
            "horizontal": [(E0 + k, N0 + 5.0) for k in (1.0, 2.0, 70.0)],
            "vértice": [(vertex[0], vertex[1])],
        }
        for name, xy in cases.items():
            with self.subTest(name):
                xy = _frozen(xy)
                got = gis.sample_tin(tin, xy)
                expected = _brute(tin, xy[:, 0], xy[:, 1])
                np.testing.assert_array_equal(np.isnan(got), np.isnan(expected))
                np.testing.assert_allclose(got, expected, rtol=0, atol=1e-9)
        self.assertEqual(gis.sample_tin(tin, _frozen([(vertex[0], vertex[1])]))[0], vertex[2])
        empty = gis.sample_tin(tin, np.empty((0, 2), dtype=np.float64))
        self.assertEqual(empty.shape, (0,))

    def test_points_on_a_shared_edge_take_the_first_triangle(self) -> None:
        """200 puntos exactamente sobre la arista vertical que comparten dos triángulos (la
        coordenada del vértice opuesto es 0 en los dos, que redondean distinto): la cota es
        la lineal a lo largo de la arista (≤ 10⁻⁹ m), la del primer triángulo, y no cambia
        con lotes de un triángulo (bit a bit)."""
        vertices = np.array([(E0 + 10.0, N0, 803.17), (E0 + 10.0, N0 + 30.0, 811.93),
                             (E0 + 25.3, N0 + 11.7, 795.41), (E0 - 7.1, N0 + 19.9, 820.77)])
        faces = np.array([[0, 2, 1], [1, 3, 0]], dtype=np.int32)
        tin = gis.Tin(vertices, faces, np.empty((0, 2), dtype=np.int32),
                      np.zeros(4, dtype=np.uint8))
        y = N0 + np.random.default_rng(4).uniform(0.0, 30.0, 200)
        xy = _frozen(np.column_stack([np.full(200, E0 + 10.0), y]))
        whole = gis.sample_tin(tin, xy)
        np.testing.assert_allclose(whole, 803.17 + (811.93 - 803.17) * (y - N0) / 30.0,
                                   rtol=0, atol=1e-9)
        first = tin_module._barycentric(tin, np.zeros(200, dtype=np.int64), xy[:, 0], xy[:, 1])
        self.assertTrue(first[0].all())
        _same(self, whole, first[1])
        with mock.patch.object(tin_module, "_TRIANGLE_BATCH", 1):
            _same(self, gis.sample_tin(tin, xy), whole)

    def test_batches(self) -> None:
        """Con lotes de un triángulo y de 5 parejas, lo mismo bit a bit."""
        tin = _build(_plane_cloud(40, seed=9))
        rng = np.random.default_rng(1)
        xy = _frozen(np.column_stack([rng.uniform(E0 - 5.0, E0 + 85.0, 300),
                                      rng.uniform(N0 - 5.0, N0 + 45.0, 300)]))
        whole = gis.sample_tin(tin, xy)
        with mock.patch.object(tin_module, "_TRIANGLE_BATCH", 1), \
                mock.patch.object(tin_module, "_SAMPLE_PAIRS", 5):
            parts = gis.sample_tin(tin, xy)
        _same(self, parts, whole)

    def test_bad_inputs(self) -> None:
        tin = _build(_plane_cloud(20))
        with self.assertRaises(TypeError):
            gis.sample_tin(tin.vertices, _frozen([(E0, N0)]))
        with self.assertRaises(TypeError):
            gis.sample_tin(tin, [(E0, N0)])
        with self.assertRaises(TypeError):
            gis.sample_tin(tin, np.array([(E0, N0)], dtype=np.float32))
        with self.assertRaises(ValueError):
            gis.sample_tin(tin, _frozen([(E0, N0, 1.0)]))


class ValidateTinTest(unittest.TestCase):
    """RF-006-23: informe de un TIN (planos, lado máximo, degenerados, huecos, ventana y
    rango)."""

    def test_statistics_match_the_build_report(self) -> None:
        """``taludes.csv`` con sus roturas: % de planos, lado máximo y degenerados iguales bit
        a bit a los del informe de ``build_tin``; sin huecos; el área, la de sus triángulos."""
        table = csv_tables.read_table(DATA / "points" / "taludes.csv", encoding="utf-8",
                                      separator=";")
        mapping = points.ColumnMapping.by_name(table.columns, **ROLES)
        point_set, lines, _ = points.points_from_rows(table.columns, table.rows, mapping, ",",
                                                      row_numbers=table.lines)
        tin, report = gis.build_tin(point_set, lines, triangulator=cdt.PureTriangulator(),
                                    origin=ORIGIN)
        result = _validate(tin)
        self.assertEqual(result.surface_type, "tin")
        self.assertEqual(result.flat_pct, report.flat_pct)
        self.assertEqual(result.max_edge_m, report.max_edge_m)
        self.assertEqual(result.degenerate, report.degenerate)
        self.assertEqual(result.hole_areas_m2, ())
        self.assertEqual(result.nodata_area_m2, 0.0)
        self.assertAlmostEqual(result.area_m2, _triangle_area(tin), delta=1e-9)

    def test_flat_long_and_degenerate_triangles(self) -> None:
        """Tres triángulos: uno plano (5 m en sus tres vértices), uno con pendiente y uno de
        5·10⁻⁷ m²: 33,33 % planos, 1 degenerado y lado máximo √200 m (la diagonal)."""
        def rel(x, y, z):
            return (E0 + x, N0 + y, z)

        vertices = np.array([rel(0, 0, 5.0), rel(10, 0, 5.0), rel(0, 10, 5.0),
                             rel(10, 10, 7.0), rel(20, 0, 6.0), rel(20, 1e-7, 6.0)])
        faces = np.array([[0, 1, 2], [1, 3, 2], [1, 4, 5]], dtype=np.int32)
        tin = gis.Tin(vertices, faces, np.empty((0, 2), dtype=np.int32),
                      np.zeros(6, dtype=np.uint8))
        result = _validate(tin)
        self.assertEqual(result.flat_pct, 100.0 / 3.0)
        self.assertEqual(result.degenerate, 1)
        self.assertEqual(result.max_edge_m, float(np.hypot(10.0, 10.0)))
        self.assertAlmostEqual(result.max_edge_m, math.sqrt(200.0), delta=1e-12)
        self.assertEqual(result.hole_areas_m2, ())
        sliver = 0.5 * 10.0 * (vertices[5, 1] - vertices[4, 1])  # N0 + 10⁻⁷ redondeado
        self.assertLess(sliver, 1e-6)
        self.assertAlmostEqual(result.area_m2, 100.0 + sliver, delta=1e-12)

    def test_holes_of_a_grid_tin(self) -> None:
        """TIN de una rejilla de 2 × 1,5 m (cuadros de 3 m²) con dos bloques sin dato
        rodeados de celdas con dato (3 × 4 y 1 × 1) y sin dato en una esquina: dos huecos de
        ((4 + 1)(3 + 1) − 2)·3 = 54 m² y (2·2 − 2)·3 = 6 m², de mayor a menor (las cuatro
        esquinas de cuadro con tres celdas tapan medio cuadro cada una); la esquina no es un
        hueco; área = triángulos + huecos y % sin dato. El MDT de ``f64_strip.tif``: un hueco
        de 18 m²."""
        layout = (
            "##..........",
            "#...........",
            "............",
            "...####.....",
            "...####..#..",
            "...####.....",
            "............",
            "............",
        )
        raster = _raster(_surface(8, 12, mask=_mask(layout)), dx=2.0, dy=1.5)
        tin = gis.raster_to_tin(raster)
        result = _validate(tin)
        self.assertEqual(result.hole_areas_m2, (54.0, 6.0))
        self.assertEqual(result.nodata_area_m2, 60.0)
        self.assertAlmostEqual(result.area_m2, _triangle_area(tin) + 60.0, delta=1e-9)
        self.assertAlmostEqual(result.nodata_pct, 6000.0 / result.area_m2, delta=1e-12)
        source = geotiff.read_geotiff(DATA / "geotiff" / "f64_strip.tif")
        fixture = gis.raster_to_tin(gis.Raster(source.grid, source.values, CRS, VERTICAL))
        self.assertEqual(_validate(fixture).hole_areas_m2, (18.0,))

    def test_island_inside_a_hole(self) -> None:
        """Anillo sin dato (8 × 8 celdas, de 2 de ancho) con una isla de 4 × 4 celdas con
        dato dentro: el hueco neto son 79 − 9 = 70 cuadros (210 m²), no 79; la isla no es
        un hueco; área = 169 cuadros (507 m²)."""
        mask = np.zeros((14, 14), dtype=bool)
        mask[3:11, 3:11] = True
        mask[5:9, 5:9] = False
        tin = gis.raster_to_tin(_raster(_surface(14, 14, mask=mask), dx=2.0, dy=1.5))
        result = _validate(tin)
        self.assertEqual(result.hole_areas_m2, (210.0,))
        self.assertAlmostEqual(result.area_m2, 507.0, delta=1e-9)
        self.assertAlmostEqual(_triangle_area(tin), 297.0, delta=1e-9)

    def test_nested_islands(self) -> None:
        """Hueco (anillo de 16 × 16 celdas) con una isla que tiene su propio hueco (anillo de
        6 × 6) con otra isla (2 × 2) dentro: cada isla se resta del hueco más pequeño que la
        contiene: 287 − 121 = 166 cuadros (498 m²) y 47 − 1 = 46 (138 m²); área = 441
        cuadros (1.323 m²)."""
        mask = np.zeros((22, 22), dtype=bool)
        mask[3:19, 3:19] = True
        mask[5:17, 5:17] = False
        mask[8:14, 8:14] = True
        mask[10:12, 10:12] = False
        tin = gis.raster_to_tin(_raster(_surface(22, 22, mask=mask), dx=2.0, dy=1.5))
        result = _validate(tin)
        self.assertEqual(result.hole_areas_m2, (498.0, 138.0))
        self.assertAlmostEqual(result.area_m2, 1323.0, delta=1e-9)
        self.assertAlmostEqual(_triangle_area(tin), 229 * 3.0, delta=1e-9)

    def test_holes_touching_at_a_vertex(self) -> None:
        """Dos celdas sin dato a dos columnas: sus rombos (2 cuadros) se tocan en un vértice
        y son dos huecos de 6 m², no uno; otra junto al borde del TIN, que su rombo toca en
        un vértice, también es un hueco de 6 m²."""
        mask = np.zeros((7, 9), dtype=bool)
        mask[3, 2] = mask[3, 4] = True
        mask[1, 7] = True
        tin = gis.raster_to_tin(_raster(_surface(7, 9, mask=mask), dx=2.0, dy=1.5))
        result = _validate(tin)
        self.assertEqual(result.hole_areas_m2, (6.0, 6.0, 6.0))
        self.assertAlmostEqual(result.area_m2, 6 * 8 * 3.0, delta=1e-9)

    def test_window_and_range(self) -> None:
        """Triángulos con algún vértice fuera de la ventana (contados a mano) y vértices con
        la cota fuera de [−500; 5.000] m (−9999 y 6.000 m; los extremos, dentro), o de un
        rango explícito, que se comprueba como el parámetro (``ParamError`` ``core.param_*``
        con la clave; RF-006-23)."""
        values = _surface(6, 8)
        values[1, 1], values[1, 2] = -9999.0, 6000.0
        values[2, 1], values[2, 2] = -500.0, 5000.0
        tin = gis.raster_to_tin(_raster(values))
        x, y = tin.vertices[:, 0], tin.vertices[:, 1]
        window = georef.Window(E0 + 2.0, N0 + 45.0, E0 + 6.0, N0 + 49.0)
        out = (x < window.xmin) | (x > window.xmax) | (y < window.ymin) | (y > window.ymax)
        result = validate.validate_tin(tin, window=window)
        self.assertEqual(result.cells_outside_window, int(out[tin.faces].any(axis=1).sum()))
        self.assertGreater(result.cells_outside_window, 0)
        self.assertEqual(_validate(tin).cells_outside_window, 0)
        self.assertEqual(result.out_of_range, 2)
        self.assertEqual(result.z_range_m, (-500.0, 5000.0))
        explicit = _validate(tin, z_range=(0.0, 1000.0))
        self.assertEqual(explicit.out_of_range, 4)
        self.assertEqual(explicit.z_range_m, (0.0, 1000.0))
        with self.assertRaises(ParamError) as caught:
            _validate(tin, z_range=(1000.0, 0.0))
        self.assertEqual(caught.exception.code, "core.param_not_list")
        self.assertEqual(caught.exception.field, "gis.validate.z_range_m")

    def test_input_untouched_and_bad_inputs(self) -> None:
        tin = gis.raster_to_tin(_raster(_surface(5, 6)))
        for array in (tin.vertices, tin.faces):
            array.flags.writeable = False
        _validate(tin)
        window = georef.Window(E0, N0, E0 + 10.0, N0 + 60.0)
        with self.assertRaises(TypeError):
            validate.validate_tin(tin.vertices, window=window)
        with self.assertRaises(TypeError):
            validate.validate_tin(tin, window=(E0, N0, E0 + 10.0, N0 + 60.0))


class ExportTest(unittest.TestCase):
    """La API nueva, en ``gis``."""

    def test_exported(self) -> None:
        for name in ("tin_to_raster", "raster_to_tin", "sample_tin"):
            self.assertIs(getattr(gis, name), getattr(tin_module, name))
            self.assertIn(name, gis.__all__)
        self.assertIs(gis.validate_tin, validate.validate_tin)
        self.assertIn("validate_tin", gis.__all__)


if __name__ == "__main__":
    unittest.main()

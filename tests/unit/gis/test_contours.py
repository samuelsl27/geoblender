# SPDX-License-Identifier: GPL-3.0-or-later
"""Curvas de nivel de una rejilla o de un TIN (spec 006, T21; plan 006 §5.3.2 y §5.4 A14;
``gis.contours``).

- **RF-006-18**: con equidistancia, cota base e intervalo de maestras, polilíneas 3D con Z igual
  a su cota (``elevation``), marcadas como maestras si la cota dividida por el intervalo de
  maestras es entera (±10⁻⁹), abiertas solo en el borde de la superficie o de sus huecos y con
  los vértices sobre la superficie interpolada linealmente (|Δz| ≤ 1 mm; aquí, ≤ 10⁻⁶ m).
  *Rejilla*: cuadros duales de 4 centros, clasificación «≥ L», vértices en las aristas entre
  centros (una de sus coordenadas, la del centro, bit a bit); sillas por el valor medio del
  cuadro, sin cruces entre curvas; cuadros con algún sin dato fuera. *TIN*: segmento por
  triángulo y nivel entre dos aristas. Simplificación de Douglas–Peucker, longitud mínima y
  desfase de maestras (se trazan a L + desfase con Z = L) según sus parámetros
  (``gis.contours.*``). La cota más alta del terreno a la vista queda en el lado izquierdo de
  cada curva (cerradas antihorarias alrededor de una cima).

Las referencias son independientes: la interpolación lineal en la arista que contiene cada
vértice, calculada aquí punto a punto, y cruces de segmentos por fuerza bruta. Las entradas
no se modifican (arrays de solo lectura).
"""

import math
import unittest
from unittest import mock

import numpy as np

from tests.support.package import import_geoblender

gis = import_geoblender("gis")
contours = import_geoblender("gis.contours")
messages = import_geoblender("gis.messages")
params = import_geoblender("gis.params")
points = import_geoblender("gis.points")
cdt = import_geoblender("gis.cdt")
georef = import_geoblender("core.georef")
worker_api = import_geoblender("jobs.worker_api")

NAN = math.nan
E0, N0 = 700_000.0, 4_400_000.0
ORIGIN = georef.GeoOrigin(700_000, 4_400_000, 0)
CATALOG = georef.load_catalog()
CRS = CATALOG.horizontal(25830)
VERTICAL = CATALOG.vertical(5782)
B24_DX = 1.0002942907592702
B24_DY = 1.0003022974607014
SURFACE_TOL = 1e-6  # RF-006-18 pide |Δz| ≤ 1 mm; aquí solo cuenta el redondeo de las absolutas
EDGE_TOL = 1e-6  # m: un vértice de una curva de TIN está en una arista del TIN


# Superficies -------------------------------------------------------------------------------


def _frozen(values) -> np.ndarray:
    array = np.array(values, dtype=np.float64)
    array.flags.writeable = False  # una entrada nunca se modifica
    return array


def _raster(values, *, dx: float = 1.0, dy: float = 1.0):
    """Ráster con su esquina noroeste en (E0, N0 + filas·dy): las coordenadas relativas de
    los centros van de 0 a columnas·dx y de 0 a filas·dy."""
    array = _frozen(values)
    nrows, ncols = array.shape
    grid = gis.Grid(west=E0, north=N0 + nrows * dy, dx=dx, dy=dy, ncols=ncols, nrows=nrows)
    return gis.Raster(grid, array, CRS, VERTICAL)


def _sampled(func, nrows: int, ncols: int, *, dx: float = 1.0, dy: float = 1.0,
             mask=None):
    """``func(x, y)`` (relativas a E0, N0) en los centros de una rejilla de ``nrows`` ×
    ``ncols``; sin dato en ``mask``."""
    x = (np.arange(ncols, dtype=np.float64) + 0.5) * dx
    y = nrows * dy - (np.arange(nrows, dtype=np.float64) + 0.5) * dy
    values = func(x[None, :], y[:, None]) + np.zeros((nrows, ncols))
    if mask is not None:
        values[mask] = NAN
    return _raster(values, dx=dx, dy=dy)


def _plane(x, y):
    return 800.0 + 0.5 * x - 0.25 * y


def _hill(x, y, sign: float = 1.0):
    """Cima (o fondo, con ``sign`` −1) gaussiana de 20 m en (25,3; 24,6), sobre 850 m."""
    return 850.0 + sign * 20.0 * np.exp(-((x - 25.3) ** 2 + (y - 24.6) ** 2) / 128.0)


def _saddles(x, y):
    """Cimas, fondos y sillas alternos (una «huevera»)."""
    return 820.0 + 6.0 * np.sin(x / 2.3 + 0.1) * np.cos(y / 1.9 - 0.2)


# Referencias -------------------------------------------------------------------------------


def _centers(raster):
    g = raster.grid
    xs = g.west + (np.arange(g.ncols, dtype=np.float64) + 0.5) * g.dx
    ys = g.north - (np.arange(g.nrows, dtype=np.float64) + 0.5) * g.dy
    return xs, ys


def _edge_of(raster, x: float, y: float):
    """La arista entre centros que contiene (x, y): ``("h", fila, columna, s)`` (de la
    columna a la siguiente) o ``("v", fila, columna, s)`` (de la fila a la siguiente), con la
    otra coordenada igual a la del centro **bit a bit**; ``None`` si no está en ninguna."""
    g = raster.grid
    xs, ys = _centers(raster)
    rows = np.flatnonzero(ys == y)
    if rows.size:
        col = min(int(np.searchsorted(xs, x, side="right")) - 1, g.ncols - 2)
        if col < 0 or x > xs[-1]:
            return None
        return ("h", int(rows[0]), col, (x - xs[col]) / (xs[col + 1] - xs[col]))
    cols = np.flatnonzero(xs == x)
    if cols.size:
        row = min(int(np.count_nonzero(ys > y)) - 1, g.nrows - 2)
        row = max(row, 0)
        if y > ys[0] or y < ys[-1]:
            return None
        return ("v", row, int(cols[0]), (ys[row] - y) / (ys[row] - ys[row + 1]))
    return None


def _edge_z(raster, xyz: np.ndarray) -> np.ndarray:
    """La cota interpolada linealmente en la arista entre centros que contiene cada punto
    (una de sus coordenadas es la de una fila o una columna de centros, bit a bit; NaN si no
    está en ninguna)."""
    g = raster.grid
    v = raster.values
    xs, ys = _centers(raster)
    x, y = xyz[:, 0], xyz[:, 1]
    out = np.full(len(x), NAN)
    row = np.minimum(np.searchsorted(-ys, -y), g.nrows - 1)
    col = np.minimum(np.searchsorted(xs, x), g.ncols - 1)
    on_row = (ys[row] == y) & (x >= xs[0]) & (x <= xs[-1])
    on_col = ~on_row & (xs[col] == x) & (y <= ys[0]) & (y >= ys[-1])
    c = np.clip(np.searchsorted(xs, x, side="right") - 1, 0, g.ncols - 2)
    s = (x - xs[c]) / (xs[c + 1] - xs[c])
    out[on_row] = (v[row, c] + s * (v[row, c + 1] - v[row, c]))[on_row]
    r = np.clip(np.searchsorted(-ys, -y, side="right") - 1, 0, g.nrows - 2)
    s = (ys[r] - y) / (ys[r] - ys[r + 1])
    out[on_col] = (v[r, col] + s * (v[r + 1, col] - v[r, col]))[on_col]
    return out


def _quad_valid(raster, row: int, col: int) -> bool:
    g = raster.grid
    if not (0 <= row < g.nrows - 1 and 0 <= col < g.ncols - 1):
        return False
    return bool(np.isfinite(raster.values[row:row + 2, col:col + 2]).all())


def _at_data_border(raster, x: float, y: float) -> bool:
    """Verdadero si el punto está en una arista con algún cuadro vecino fuera de la rejilla
    o con un sin dato: el borde de la superficie o de un hueco."""
    edge = _edge_of(raster, x, y)
    if edge is None:
        return False
    kind, row, col, _s = edge
    if kind == "h":
        neighbours = ((row - 1, col), (row, col))
    else:
        neighbours = ((row, col - 1), (row, col))
    return not all(_quad_valid(raster, r, c) for r, c in neighbours)


def _segments(lines) -> np.ndarray:
    """Los tramos ``(x1, y1, x2, y2)`` (relativos a E0, N0) de las curvas, con el de cierre
    de las cerradas."""
    rows = []
    for line in lines:
        xy = line.xyz[:, :2] - (E0, N0)
        if line.closed:
            xy = np.vstack([xy, xy[:1]])
        rows.append(np.hstack([xy[:-1], xy[1:]]))
    return np.vstack(rows) if rows else np.empty((0, 4))


def _proper_crossings(segments: np.ndarray) -> int:
    """Parejas de tramos que se cruzan en un punto interior de los dos (fuerza bruta;
    tocarse en un extremo no cuenta)."""
    a = segments[:, None, :]
    b = segments[None, :, :]

    def orient(px, py, qx, qy, rx, ry):
        return (qx - px) * (ry - py) - (qy - py) * (rx - px)

    eps = 1e-12
    d1 = orient(a[..., 0], a[..., 1], a[..., 2], a[..., 3], b[..., 0], b[..., 1])
    d2 = orient(a[..., 0], a[..., 1], a[..., 2], a[..., 3], b[..., 2], b[..., 3])
    d3 = orient(b[..., 0], b[..., 1], b[..., 2], b[..., 3], a[..., 0], a[..., 1])
    d4 = orient(b[..., 0], b[..., 1], b[..., 2], b[..., 3], a[..., 2], a[..., 3])
    proper = (d1 * d2 < -eps) & (d3 * d4 < -eps)
    return int(np.count_nonzero(np.triu(proper, 1)))


def _signed_area(line) -> float:
    xy = line.xyz[:, :2] - (E0, N0)
    x, y = xy[:, 0], xy[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def _higher_on_left(func, line, step: float = 1e-3) -> bool:
    """Verdadero si, en el punto medio de cada tramo, la superficie analítica ``func`` es
    más alta a la izquierda que a la derecha."""
    seg = _segments([line])
    mx, my = (seg[:, 0] + seg[:, 2]) / 2, (seg[:, 1] + seg[:, 3]) / 2
    dx, dy = seg[:, 2] - seg[:, 0], seg[:, 3] - seg[:, 1]
    norm = np.hypot(dx, dy)
    nx, ny = -dy / norm * step, dx / norm * step
    return bool((func(mx + nx, my + ny) > func(mx - nx, my - ny)).all())


def _by_level(lines) -> dict:
    grouped: dict = {}
    for line in lines:
        grouped.setdefault(line.elevation, []).append(line)
    return grouped


def _same_lines(test, got, expected) -> None:
    test.assertEqual(len(got), len(expected))
    for a, b in zip(got, expected, strict=True):
        test.assertEqual((a.elevation, a.is_index, a.closed), (b.elevation, b.is_index, b.closed))
        np.testing.assert_array_equal(a.xyz, b.xyz)


def _point_set(xyz):
    xyz = _frozen(xyz)
    count = len(xyz)
    return points.PointSet(xyz, tuple(f"P{i + 1}" for i in range(count)), ("",) * count,
                           tuple(range(2, count + 2)))


def _cloud_tin(func, count: int = 220, seed: int = 7, size=(40.0, 30.0)):
    """TIN de una nube al azar (con sus cuatro esquinas) sobre ``func``."""
    rng = np.random.default_rng(seed)
    w, h = size
    xy = np.vstack([[[0.0, 0.0], [w, 0.0], [w, h], [0.0, h]],
                    rng.uniform((0.0, 0.0), size, size=(count, 2))])
    xyz = np.column_stack([E0 + xy[:, 0], N0 + xy[:, 1], func(xy[:, 0], xy[:, 1])])
    tin, _report = gis.build_tin(_point_set(xyz), [], triangulator=cdt.PureTriangulator(),
                                 origin=ORIGIN)
    return tin


def _tin_reference(tin, xyz: np.ndarray):
    """Para cada punto: la distancia en planta a la arista del TIN más cercana entre las que
    tocan su cubeta, la cota interpolada linealmente en ella y si es de borde (de un solo
    triángulo). Cada arista va a todas las cubetas (del lado de la arista mediana) que toca su
    caja ampliada 1 mm: la que contiene un punto está en la cubeta del punto."""
    f = tin.faces.astype(np.int64)
    pairs = np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), axis=1)
    count = len(tin.vertices)
    unique, counts = np.unique(pairs[:, 0] * count + pairs[:, 1], return_counts=True)
    edges = np.column_stack(np.divmod(unique, count))
    a, b = tin.vertices[edges[:, 0]], tin.vertices[edges[:, 1]]
    size = float(np.median(np.hypot(b[:, 0] - a[:, 0], b[:, 1] - a[:, 1])))
    left, bottom = tin.vertices[:, 0].min() - 1.0, tin.vertices[:, 1].min() - 1.0

    def cells(x, y):
        return (np.floor((x - left) / size).astype(np.int64),
                np.floor((y - bottom) / size).astype(np.int64))

    x0, y0 = cells(np.minimum(a[:, 0], b[:, 0]) - 1e-3, np.minimum(a[:, 1], b[:, 1]) - 1e-3)
    x1, y1 = cells(np.maximum(a[:, 0], b[:, 0]) + 1e-3, np.maximum(a[:, 1], b[:, 1]) + 1e-3)
    height = y1 - y0 + 1
    spans = (x1 - x0 + 1) * height
    owner = np.repeat(np.arange(len(edges)), spans)
    local = np.arange(int(spans.sum())) - np.repeat(np.cumsum(spans) - spans, spans)
    stride = int(y1.max()) + 2
    keys = (x0[owner] + local // height[owner]) * stride + y0[owner] + local % height[owner]
    order = np.argsort(keys, kind="stable")
    keys, owner = keys[order], owner[order]
    px, py = cells(xyz[:, 0], xyz[:, 1])
    wanted = px * stride + py
    lo = np.searchsorted(keys, wanted, side="left")
    hi = np.searchsorted(keys, wanted, side="right")
    point = np.repeat(np.arange(len(xyz)), hi - lo)
    edge = owner[np.arange(len(point)) - np.repeat(np.cumsum(hi - lo) - (hi - lo) - lo, hi - lo)]
    pa, pb, p = a[edge], b[edge], xyz[point]
    ux, uy = pb[:, 0] - pa[:, 0], pb[:, 1] - pa[:, 1]
    t = np.clip(((p[:, 0] - pa[:, 0]) * ux + (p[:, 1] - pa[:, 1]) * uy) / (ux * ux + uy * uy),
                0.0, 1.0)
    d = np.hypot(pa[:, 0] + t * ux - p[:, 0], pa[:, 1] + t * uy - p[:, 1])
    pick = np.lexsort((d, point))
    found, first = np.unique(point[pick], return_index=True)
    assert len(found) == len(xyz), "un punto sin ninguna arista en su cubeta"
    best = pick[first]
    return d[best], pa[best, 2] + t[best] * (pb[best, 2] - pa[best, 2]), counts[edge[best]] == 1

class GridContoursTest(unittest.TestCase):
    """RF-006-18: curvas de una rejilla (marching squares sobre los cuadros de 4 centros)."""

    def _check_on_surface(self, raster, lines) -> None:
        for line in lines:
            self.assertTrue((line.xyz[:, 2] == line.elevation).all())
            z = _edge_z(raster, line.xyz)
            self.assertFalse(np.isnan(z).any())
            self.assertLessEqual(float(np.abs(z - line.elevation).max()), SURFACE_TOL)

    def test_plane_one_open_line_per_level(self) -> None:
        """RF-006-18: en un plano, una curva abierta por cota de 796 a 814 m, de borde a
        borde, con Z = cota, sus vértices en las aristas entre centros (la coordenada del
        centro bit a bit) y sobre la superficie; maestras las de 800, 805 y 810 m; lo más
        alto, a la izquierda."""
        raster = _sampled(_plane, 20, 30)
        lines = gis.contours_from_raster(raster, interval_m=1.0)
        self.assertEqual([line.elevation for line in lines],
                         [float(level) for level in range(796, 815)])
        self.assertTrue(all(isinstance(line, gis.ContourLine) for line in lines))
        for line in lines:
            self.assertFalse(line.closed)
            self.assertEqual(line.xyz.dtype, np.float64)
            self.assertEqual(line.is_index, line.elevation % 5 == 0)
            self.assertTrue(_at_data_border(raster, *line.xyz[0, :2]))
            self.assertTrue(_at_data_border(raster, *line.xyz[-1, :2]))
            self.assertTrue(_higher_on_left(_plane, line))
        self._check_on_surface(raster, lines)
        self.assertEqual([line.is_index for line in lines].count(True), 3)

    def test_hill_rings_counterclockwise_and_pit_clockwise(self) -> None:
        """RF-006-18: una cima da un anillo cerrado por cota (851 a 869 m), antihorario (lo
        alto a la izquierda), sin repetir el primer vértice y empezando en su menor punto de
        corte (fila, columna y sentido de la arista); un fondo, horarios."""
        raster = _sampled(_hill, 50, 50)
        lines = gis.contours_from_raster(raster, interval_m=1.0)
        self.assertEqual([line.elevation for line in lines],
                         [float(level) for level in range(851, 870)])
        for line in lines:
            self.assertTrue(line.closed)
            self.assertGreater(_signed_area(line), 0.0)
            self.assertFalse((line.xyz[0] == line.xyz[-1]).all())
            self.assertTrue(_higher_on_left(_hill, line))
            keys = []
            for x, y in line.xyz[:, :2].tolist():
                kind, row, col, _s = _edge_of(raster, x, y)
                keys.append((row, col, kind == "v"))
            self.assertEqual(keys[0], min(keys))
        self._check_on_surface(raster, lines)

        pit = _sampled(lambda x, y: _hill(x, y, -1.0), 50, 50)
        rings = gis.contours_from_raster(pit, interval_m=2.0)
        self.assertEqual([line.elevation for line in rings],
                         [float(level) for level in range(832, 850, 2)])
        for line in rings:
            self.assertTrue(line.closed)
            self.assertLess(_signed_area(line), 0.0)

    def test_saddle_decided_by_the_mean_of_the_square(self) -> None:
        """RF-006-18: un cuadro en silla (10 y 10 en una diagonal, 0 y 0 en la otra; media
        5) a 4 m (media ≥ L) separa las esquinas bajas; a 8 m (media < L), las altas; a 5 m,
        la media cuenta como «≥» (separa las bajas)."""
        raster = _raster([[10.0, 0.0], [0.0, 10.0]])
        got = gis.contours_from_raster(raster, interval_m=4.0, index_every_m=1000.0)
        rel = {(line.elevation, tuple(map(tuple, np.round(line.xyz[:, :2] - (E0, N0), 6))))
               for line in got}
        self.assertEqual(rel, {
            (4.0, ((1.5, 1.1), (1.1, 1.5))),  # recorta la esquina NE (baja)
            (4.0, ((0.5, 0.9), (0.9, 0.5))),  # recorta la SO (baja)
            (8.0, ((0.5, 1.3), (0.7, 1.5))),  # recorta la NO (alta)
            (8.0, ((1.5, 0.7), (1.3, 0.5))),  # recorta la SE (alta)
        })
        self.assertTrue(all(not line.closed for line in got))
        at_mean = gis.contours_from_raster(raster, interval_m=5.0)
        self.assertEqual({tuple(map(tuple, np.round(line.xyz[:, :2] - (E0, N0), 6)))
                          for line in at_mean},
                         {((1.5, 1.0), (1.0, 1.5)), ((0.5, 1.0), (1.0, 0.5))})

    def test_saddles_never_cross(self) -> None:
        """RF-006-18: en una superficie con muchas sillas, cimas y fondos, ningún tramo de una
        curva cruza otro (de su curva o de otra, de su cota o de otra)."""
        raster = _sampled(_saddles, 14, 18)
        lines = gis.contours_from_raster(raster, interval_m=0.75, base_m=0.1)
        segments = _segments(lines)
        self.assertGreater(len(segments), 300)
        self.assertEqual(_proper_crossings(segments), 0)
        self._check_on_surface(raster, lines)
        self.assertTrue(any(line.closed for line in lines))
        for line in lines:
            if not line.closed:
                self.assertTrue(_at_data_border(raster, *line.xyz[0, :2]))
                self.assertTrue(_at_data_border(raster, *line.xyz[-1, :2]))

    def test_open_only_at_the_border_and_at_holes(self) -> None:
        """RF-006-18: con un hueco interior y sin dato en una esquina, las curvas que los
        tocan quedan abiertas con los extremos en el borde de los datos; las demás, cerradas;
        un cuadro con algún sin dato no tiene curva."""
        mask = np.zeros((50, 50), dtype=bool)
        mask[14:18, 20:24] = True  # hueco en la ladera
        mask[:6, :5] = True  # esquina sin dato
        raster = _sampled(_hill, 50, 50, mask=mask)
        lines = gis.contours_from_raster(raster, interval_m=1.0)
        opened = [line for line in lines if not line.closed]
        self.assertTrue(opened)
        self.assertTrue(any(line.closed for line in lines))
        for line in opened:
            self.assertTrue(_at_data_border(raster, *line.xyz[0, :2]))
            self.assertTrue(_at_data_border(raster, *line.xyz[-1, :2]))
        self._check_on_surface(raster, lines)
        full = _by_level(gis.contours_from_raster(_sampled(_hill, 50, 50), interval_m=1.0))
        cut = _by_level(lines)
        for level, rings in full.items():
            hole_x = (E0 + 20.5, E0 + 23.5)
            hole_y = (N0 + 50 - 17.5, N0 + 50 - 14.5)
            ring = rings[0].xyz
            near = ((ring[:, 0] >= hole_x[0] - 1) & (ring[:, 0] <= hole_x[1] + 1)
                    & (ring[:, 1] >= hole_y[0] - 1) & (ring[:, 1] <= hole_y[1] + 1)).any()
            if not near:
                np.testing.assert_array_equal(cut[level][0].xyz, ring)

    def test_levels_base_interval_and_index(self) -> None:
        """RF-006-18: cotas base + k·equidistancia dentro del rango; maestras si la cota
        dividida por el intervalo de maestras es entera (±10⁻⁹)."""
        raster = _sampled(_plane, 20, 30)
        lines = gis.contours_from_raster(raster, interval_m=0.5, base_m=0.25,
                                         index_every_m=0.75)
        levels = [line.elevation for line in lines]
        self.assertEqual(levels, [0.25 + 0.5 * k for k in range(1591, 1629)])
        self.assertEqual([line.is_index for line in lines],
                         [level / 0.75 == round(level / 0.75) for level in levels])
        self.assertIn(True, [line.is_index for line in lines])
        none = gis.contours_from_raster(raster, interval_m=1.0, base_m=0.5)
        self.assertFalse(any(line.is_index for line in none))
        tenths = gis.contours_from_raster(raster, interval_m=0.1, index_every_m=0.3)
        expected = [abs(line.elevation / 0.3 - round(line.elevation / 0.3)) <= 1e-9
                    for line in tenths]
        self.assertEqual([line.is_index for line in tenths], expected)
        self.assertEqual(expected.count(True), 64)  # 795,6 (2652·0,3) a 814,5 (2715·0,3)
        inexact = [line.elevation / 0.3 for line in tenths
                   if line.is_index and line.elevation / 0.3 != round(line.elevation / 0.3)]
        self.assertTrue(inexact)  # sin la tolerancia de 10⁻⁹ no serían maestras

    def test_index_offset_traces_at_level_plus_offset(self) -> None:
        """RF-006-18: con desfase, las maestras se trazan a L + desfase con Z = L; las demás
        no cambian. La cima llega a 869,99 m: la maestra de 870 m, trazada a 869,75 m,
        aparece."""
        raster = _sampled(_hill, 50, 50)
        plain = _by_level(gis.contours_from_raster(raster, interval_m=1.0))
        shifted = _by_level(gis.contours_from_raster(raster, interval_m=1.0,
                                                     index_offset_m=-0.25))
        self.assertEqual(sorted(shifted), sorted([*plain, 870.0]))
        for level, (line,) in shifted.items():
            self.assertTrue(line.closed)
            self.assertEqual(line.is_index, level % 5 == 0)
            if not line.is_index:
                np.testing.assert_array_equal(line.xyz, plain[level][0].xyz)
                continue
            self.assertTrue((line.xyz[:, 2] == level).all())
            self.assertLessEqual(float(np.abs(_edge_z(raster, line.xyz) - (level - 0.25)).max()),
                                 SURFACE_TOL)
            if level in plain:  # más abajo en la cima: más largo
                self.assertGreater(_signed_area(line), _signed_area(plain[level][0]))

    def test_simplification(self) -> None:
        """RF-006-18: Douglas–Peucker con ``simplify_m``: los vértices que quedan son de la
        curva y en su orden, se conservan los extremos de las abiertas y al menos tres en las
        cerradas, cada vértice quitado queda a ≤ la tolerancia del tramo que lo sustituye y
        quedan menos; con 0, nada cambia."""
        for raster in (_sampled(_hill, 50, 50), _sampled(_saddles, 14, 18)):
            plain = gis.contours_from_raster(raster, interval_m=1.0)
            _same_lines(self, gis.contours_from_raster(raster, interval_m=1.0, simplify_m=0.0),
                        plain)
            for tolerance in (0.05, 0.4, 50.0):
                simple = gis.contours_from_raster(raster, interval_m=1.0, simplify_m=tolerance)
                self.assertEqual(len(simple), len(plain))
                for a, b in zip(plain, simple, strict=True):
                    self._check_simplified(a, b, tolerance)
            self.assertLess(sum(len(line.xyz) for line in simple),
                            sum(len(line.xyz) for line in plain))

    def _check_simplified(self, original, simple, tolerance: float) -> None:
        self.assertEqual((original.elevation, original.closed), (simple.elevation, simple.closed))
        rows = {tuple(row): i for i, row in enumerate(original.xyz.tolist())}
        kept = [rows[tuple(row)] for row in simple.xyz.tolist()]
        self.assertEqual(kept, sorted(kept))
        if original.closed:
            self.assertEqual(kept[0], 0)
            self.assertGreaterEqual(len(kept), min(3, len(original.xyz)))
            kept = [*kept, len(original.xyz)]
            xy = np.vstack([original.xyz[:, :2], original.xyz[:1, :2]])
        else:
            self.assertEqual((kept[0], kept[-1]), (0, len(original.xyz) - 1))
            xy = original.xyz[:, :2]
        for start, stop in zip(kept[:-1], kept[1:], strict=True):
            a, b = xy[start], xy[stop]
            u = b - a
            for p in xy[start + 1:stop]:
                denom = float(u @ u)
                t = 0.0 if denom == 0.0 else min(max(float((p - a) @ u) / denom, 0.0), 1.0)
                self.assertLessEqual(float(np.hypot(*(a + t * u - p))), tolerance + 1e-12)

    def test_minimum_length(self) -> None:
        """RF-006-18: se quitan las curvas más cortas que ``min_length_m`` (longitud con el
        tramo de cierre de las cerradas, ``length_m``); las demás no cambian."""
        raster = _sampled(_hill, 50, 50)
        plain = gis.contours_from_raster(raster, interval_m=1.0)
        lengths = [line.length_m for line in plain]
        for line in plain:
            xy = np.vstack([line.xyz[:, :2], line.xyz[:1, :2]])
            self.assertAlmostEqual(line.length_m, float(np.hypot(*np.diff(xy, axis=0).T).sum()),
                                   delta=1e-9)
        limit = float(np.median(lengths))
        longer = gis.contours_from_raster(raster, interval_m=1.0, min_length_m=limit)
        _same_lines(self, longer, [line for line in plain if line.length_m >= limit])
        self.assertLess(len(longer), len(plain))
        self.assertEqual(gis.contours_from_raster(raster, interval_m=1.0, min_length_m=1e4), [])

    def test_elevations_exactly_at_levels(self) -> None:
        """RF-006-18: cotas enteras con equidistancia 1 m (las curvas pasan por centros): sin
        vértices repetidos seguidos ni curvas de longitud nula, sin cruces y sobre la
        superficie; una celda aislada justo a la cota no da curva (longitud nula); un pico de
        1,5 m, un rombo de 4 vértices."""
        raster = _raster(np.round(_sampled(_saddles, 14, 18).values))
        lines = gis.contours_from_raster(raster, interval_m=1.0)
        self.assertTrue(lines)
        for line in lines:
            xy = line.xyz[:, :2]
            if line.closed:
                xy = np.vstack([xy, xy[:1]])
            self.assertTrue((np.hypot(*np.diff(xy, axis=0).T) > 0.0).all())
            self.assertGreater(line.length_m, 0.0)
        self.assertEqual(_proper_crossings(_segments(lines)), 0)
        self._check_on_surface(raster, lines)

        spike = np.zeros((3, 3))
        spike[1, 1] = 1.0
        self.assertEqual(gis.contours_from_raster(_raster(spike), interval_m=1.0), [])
        spike[1, 1] = 1.5
        (ring,) = gis.contours_from_raster(_raster(spike), interval_m=1.0)
        self.assertTrue(ring.closed)
        rel = ring.xyz[:, :2] - (E0 + 1.5, N0 + 1.5)
        self.assertEqual(len(rel), 4)
        np.testing.assert_allclose(np.abs(rel).sum(axis=1), 1.0 / 3.0, atol=1e-9)
        self.assertGreater(_signed_area(ring), 0.0)

        plateau = np.zeros((4, 4))
        plateau[1:3, 1:3] = 1.0  # meseta justo a la cota máxima: su borde es la curva
        (edge,) = gis.contours_from_raster(_raster(plateau), interval_m=1.0)
        self.assertTrue(edge.closed)
        self.assertEqual({tuple(row) for row in (edge.xyz[:, :2] - (E0, N0)).tolist()},
                         {(1.5, 2.5), (2.5, 2.5), (1.5, 1.5), (2.5, 1.5)})
        self.assertGreater(_signed_area(edge), 0.0)

    def test_steps_of_b24_and_absolute_coordinates(self) -> None:
        """RF-006-18: con los pasos no redondos de B24 los vértices siguen en las aristas
        entre centros y sobre la superficie."""
        raster = _sampled(_hill, 30, 34, dx=B24_DX, dy=B24_DY)
        lines = gis.contours_from_raster(raster, interval_m=2.0)
        self.assertTrue(lines)
        self._check_on_surface(raster, lines)

    def test_defaults_are_the_parameters(self) -> None:
        """RF-006-18: sin argumentos, los valores por defecto de ``gis.contours.*`` (1 m,
        maestras cada 5 m, sin desfase, sin simplificar ni longitud mínima) y base 0."""
        self.assertEqual(params.default(contours.INTERVAL_KEY), 1.0)
        raster = _sampled(_hill, 50, 50)
        explicit = gis.contours_from_raster(
            raster, interval_m=params.default(contours.INTERVAL_KEY), base_m=0.0,
            index_every_m=params.default(contours.INDEX_EVERY_KEY),
            index_offset_m=params.default(contours.INDEX_OFFSET_KEY),
            simplify_m=params.default(contours.SIMPLIFY_KEY),
            min_length_m=params.default(contours.MIN_LENGTH_KEY))
        _same_lines(self, gis.contours_from_raster(raster), explicit)
        self.assertEqual(sum(line.is_index for line in explicit), 3)

    def test_invalid_parameters(self) -> None:
        """RF-006-18: un parámetro no válido → ``GisError`` ``gis.param_*`` con su clave; una
        cota base que no es un número → ``gis.contours_base_invalid``; demasiadas cotas →
        ``gis.contours_too_many``."""
        raster = _sampled(_hill, 20, 20)
        cases = (
            ({"interval_m": 0.0}, "gis.param_out_of_range", contours.INTERVAL_KEY),
            ({"interval_m": "1"}, "gis.param_not_number", contours.INTERVAL_KEY),
            ({"index_every_m": -5.0}, "gis.param_out_of_range", contours.INDEX_EVERY_KEY),
            ({"index_offset_m": 500.0}, "gis.param_out_of_range", contours.INDEX_OFFSET_KEY),
            ({"simplify_m": -0.1}, "gis.param_out_of_range", contours.SIMPLIFY_KEY),
            ({"min_length_m": math.nan}, "gis.param_not_number", contours.MIN_LENGTH_KEY),
        )
        for options, code, key in cases:
            with self.subTest(options=options), self.assertRaises(messages.GisError) as caught:
                gis.contours_from_raster(raster, **options)
            self.assertEqual((caught.exception.code, caught.exception.field), (code, key))
        for base in (math.nan, math.inf, "0", True):
            with self.subTest(base=base), self.assertRaises(messages.GisError) as caught:
                gis.contours_from_raster(raster, base_m=base, name="MDT")
            self.assertEqual(caught.exception.code, "gis.contours_base_invalid")
            self.assertEqual(caught.exception.field, "cota base")
            self.assertIn("MDT", str(caught.exception))
        with self.assertRaises(messages.GisError) as caught:
            gis.contours_from_raster(raster, interval_m=1e-5, name="MDT")
        self.assertEqual(caught.exception.code, "gis.contours_too_many")
        self.assertGreater(caught.exception.value, contours.MAX_LEVELS)
        with self.assertRaises(TypeError):
            gis.contours_from_raster(raster.values)

    def test_no_lines(self) -> None:
        """RF-006-18: sin datos, con una sola fila o columna, o llana, no hay curvas."""
        self.assertEqual(gis.contours_from_raster(_raster(np.full((4, 5), NAN))), [])
        self.assertEqual(gis.contours_from_raster(_raster([[800.0, 803.0, 806.0]])), [])
        self.assertEqual(gis.contours_from_raster(_raster([[800.0], [803.0]])), [])
        self.assertEqual(gis.contours_from_raster(_raster(np.full((4, 5), 800.0))), [])
        lone = np.full((4, 5), NAN)
        lone[1:3, 1:3] = [[799.0, 800.5], [800.5, 800.6]]
        (line,) = gis.contours_from_raster(_raster(lone))
        self.assertEqual(line.elevation, 800.0)

    def test_blocks_progress_and_cancel(self) -> None:
        """RF-006-18: por bloques de un cuadro y de una pareja (cuadro, cota) el resultado es
        el mismo, bit a bit; el avance llega a 1 y la cancelación lanza ``JobCancelled``."""
        raster = _sampled(_saddles, 14, 18)
        whole = gis.contours_from_raster(raster, interval_m=0.75)
        steps = []
        with mock.patch.object(contours, "_QUAD_BLOCK", 1), \
                mock.patch.object(contours, "_PAIR_BUDGET", 1):
            parts = gis.contours_from_raster(raster, interval_m=0.75,
                                             progress=lambda f, text: steps.append((f, text)))
        _same_lines(self, parts, whole)
        fractions = [f for f, _text in steps]
        self.assertEqual(fractions, sorted(fractions))
        self.assertEqual(fractions[-1], 1.0)
        self.assertTrue(all(isinstance(text, str) and text for _f, text in steps))
        with self.assertRaises(worker_api.JobCancelled):
            gis.contours_from_raster(raster, cancelled=lambda: True)
        calls = []

        def late() -> bool:
            calls.append(1)
            return len(calls) > 3

        with mock.patch.object(contours, "_QUAD_BLOCK", 1), \
                self.assertRaises(worker_api.JobCancelled) as caught:
            gis.contours_from_raster(raster, cancelled=late)
        self.assertIn("bloque", str(caught.exception))


class ContourLineTest(unittest.TestCase):
    """RF-006-18: la curva (``ContourLine``) y la API del paquete."""

    def test_contour_line(self) -> None:
        """RF-006-18: xyz float64 (n ≥ 2, 3) ABSOLUTO, cota, maestra y cerrada; la longitud
        en planta cuenta el tramo de cierre; tipos o formas que no son → error."""
        xyz = _frozen([[E0, N0, 5.0], [E0 + 3, N0, 5.0], [E0 + 3, N0 + 4, 5.0]])
        self.assertEqual(gis.ContourLine(xyz, 5.0, True, False).length_m, 7.0)
        self.assertEqual(gis.ContourLine(xyz, 5.0, True, True).length_m, 12.0)
        with self.assertRaises(TypeError):
            gis.ContourLine(xyz.astype(np.float32), 5.0, False, False)
        with self.assertRaises(ValueError):
            gis.ContourLine(xyz[:1], 5.0, False, False)
        with self.assertRaises(ValueError):
            gis.ContourLine(xyz[:, :2].copy(), 5.0, False, False)
        self.assertIs(gis.contours_from_raster, contours.contours_from_raster)
        self.assertIs(gis.contours_from_tin, contours.contours_from_tin)
        for name in ("ContourLine", "contours_from_raster", "contours_from_tin"):
            self.assertIn(name, gis.__all__)


# TIN ---------------------------------------------------------------------------------------


class TinContoursTest(unittest.TestCase):
    """RF-006-18: curvas de un TIN (segmento por triángulo y cota)."""

    def _check_on_tin(self, tin, lines, shift: float = 0.0) -> None:
        """Z = cota y cada vértice en una arista del TIN, sobre ella a la cota (+ ``shift``)."""
        xyz = np.vstack([line.xyz for line in lines])
        level = np.concatenate([np.full(len(line.xyz), line.elevation) for line in lines])
        self.assertTrue((xyz[:, 2] == level).all())
        distance, z, _border = _tin_reference(tin, xyz)
        self.assertLessEqual(float(distance.max()), EDGE_TOL)
        self.assertLessEqual(float(np.abs(z - (level + shift)).max()), SURFACE_TOL)

    def _check_open_at_boundary(self, tin, lines) -> None:
        """Los extremos de las abiertas, en aristas de borde (exterior o de un hueco)."""
        ends = [line.xyz[[0, -1]] for line in lines if not line.closed]
        if ends:
            distance, _z, border = _tin_reference(tin, np.vstack(ends))
            self.assertLessEqual(float(distance.max()), EDGE_TOL)
            self.assertTrue(border.all())

    def test_plane_cloud(self) -> None:
        """RF-006-18: TIN de una nube sobre un plano: una curva abierta por cota, de borde a
        borde, con Z = cota y los vértices en aristas del TIN y sobre él; lo alto a la
        izquierda."""
        tin = _cloud_tin(_plane, size=(40.3, 30.2))
        lines = gis.contours_from_tin(tin, interval_m=1.0)
        z = tin.vertices[:, 2]
        expected = [float(level) for level in range(math.floor(z.min()) + 1,
                                                     math.floor(z.max()) + 1)]
        self.assertEqual([line.elevation for line in lines], expected)
        for line in lines:
            self.assertFalse(line.closed)
            self.assertEqual(line.is_index, line.elevation % 5 == 0)
            self.assertTrue(_higher_on_left(_plane, line))
        self._check_on_tin(tin, lines)
        self._check_open_at_boundary(tin, lines)

    def test_rings_and_holes_of_a_grid_tin(self) -> None:
        """RF-006-18: el TIN de los centros de una cima da anillos cerrados antihorarios; con
        un hueco, las curvas que lo tocan quedan abiertas con los extremos en aristas de
        borde."""
        tin = gis.raster_to_tin(_sampled(_hill, 50, 50))
        lines = gis.contours_from_tin(tin, interval_m=2.0)
        self.assertEqual([line.elevation for line in lines],
                         [float(level) for level in range(852, 870, 2)])
        for line in lines:
            self.assertTrue(line.closed)
            self.assertGreater(_signed_area(line), 0.0)
        self._check_on_tin(tin, lines)

        mask = np.zeros((50, 50), dtype=bool)
        mask[14:18, 20:24] = True
        holed = gis.raster_to_tin(_sampled(_hill, 50, 50, mask=mask))
        cut = gis.contours_from_tin(holed, interval_m=2.0)
        self.assertTrue(any(not line.closed for line in cut))
        self.assertTrue(any(line.closed for line in cut))
        self._check_open_at_boundary(holed, cut)
        self._check_on_tin(holed, cut)

    def test_saddles_never_cross(self) -> None:
        """RF-006-18: en el TIN de una superficie con sillas, ningún tramo cruza otro."""
        tin = _cloud_tin(_saddles, count=160, seed=11, size=(18.0, 14.0))
        lines = gis.contours_from_tin(tin, interval_m=0.75, base_m=0.1)
        segments = _segments(lines)
        self.assertGreater(len(segments), 200)
        self.assertEqual(_proper_crossings(segments), 0)
        self._check_on_tin(tin, lines)
        self._check_open_at_boundary(tin, lines)

    def test_clockwise_faces_give_the_same_lines(self) -> None:
        """RF-006-18: con los triángulos en sentido horario las curvas son las mismas."""
        tin = gis.raster_to_tin(_sampled(_saddles, 10, 12))
        flipped = gis.Tin(tin.vertices, np.ascontiguousarray(tin.faces[:, [0, 2, 1]]),
                          tin.constraint_edges, tin.vertex_source, tin.triangulator)
        _same_lines(self, gis.contours_from_tin(flipped, interval_m=0.5),
                    gis.contours_from_tin(tin, interval_m=0.5))

    def test_broken_tin_still_gives_lines_on_it(self) -> None:
        """RF-006-18: un TIN roto (cada triángulo dos veces: dos segmentos por punto de
        corte) no deja el encadenado en un bucle: las curvas siguen sobre el TIN."""
        tin = gis.raster_to_tin(_sampled(_saddles, 8, 9))
        doubled = gis.Tin(tin.vertices, np.ascontiguousarray(np.vstack([tin.faces, tin.faces])),
                          tin.constraint_edges, tin.vertex_source, tin.triangulator)
        lines = gis.contours_from_tin(doubled, interval_m=0.5)
        self.assertGreaterEqual(sum(len(line.xyz) for line in lines),
                                sum(len(line.xyz) for line in
                                    gis.contours_from_tin(tin, interval_m=0.5)))
        self._check_on_tin(tin, lines)

    def test_parameters_apply_to_tin(self) -> None:
        """RF-006-18: maestras, desfase, simplificación y longitud mínima también en un TIN."""
        tin = gis.raster_to_tin(_sampled(_hill, 50, 50))
        plain = gis.contours_from_tin(tin, interval_m=1.0)
        self.assertEqual([line.is_index for line in plain],
                         [line.elevation % 5 == 0 for line in plain])
        by_level = _by_level(plain)
        shifted = _by_level(gis.contours_from_tin(tin, interval_m=1.0, index_offset_m=0.4))
        self.assertEqual(sorted(shifted), sorted([850.0, *by_level]))  # 850 m, a 850,4 m
        for level, (line,) in shifted.items():
            if not line.is_index:
                np.testing.assert_array_equal(line.xyz, by_level[level][0].xyz)
                continue
            self._check_on_tin(tin, [line], shift=0.4)
        simple = gis.contours_from_tin(tin, interval_m=1.0, simplify_m=0.3)
        for a, b in zip(plain, simple, strict=True):
            GridContoursTest._check_simplified(self, a, b, 0.3)
        limit = float(np.median([line.length_m for line in plain]))
        _same_lines(self, gis.contours_from_tin(tin, interval_m=1.0, min_length_m=limit),
                    [line for line in plain if line.length_m >= limit])

    def test_flat_tin_and_wrong_type(self) -> None:
        """RF-006-18: un TIN llano no tiene curvas; lo que no es un ``Tin`` → ``TypeError``."""
        flat = gis.raster_to_tin(_raster(np.full((3, 3), 812.0)))
        self.assertEqual(gis.contours_from_tin(flat), [])
        with self.assertRaises(TypeError):
            gis.contours_from_tin(_sampled(_plane, 3, 3))
        with self.assertRaises(messages.GisError) as caught:
            gis.contours_from_tin(gis.raster_to_tin(_sampled(_plane, 5, 5)), interval_m=-1.0)
        self.assertEqual(caught.exception.field, contours.INTERVAL_KEY)

    def test_blocks_progress_and_cancel(self) -> None:
        """RF-006-18: por bloques de un triángulo y de una pareja el resultado es el mismo;
        avance hasta 1 y cancelación."""
        tin = _cloud_tin(_saddles, count=120, seed=3, size=(18.0, 14.0))
        whole = gis.contours_from_tin(tin, interval_m=0.5)
        steps = []
        with mock.patch.object(contours, "_TRIANGLE_BLOCK", 1), \
                mock.patch.object(contours, "_PAIR_BUDGET", 1):
            parts = gis.contours_from_tin(tin, interval_m=0.5,
                                          progress=lambda f, text: steps.append(f))
        _same_lines(self, parts, whole)
        self.assertEqual(steps, sorted(steps))
        self.assertEqual(steps[-1], 1.0)
        with self.assertRaises(worker_api.JobCancelled):
            gis.contours_from_tin(tin, cancelled=lambda: True)


if __name__ == "__main__":
    unittest.main()

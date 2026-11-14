# SPDX-License-Identifier: GPL-3.0-or-later
"""Casos de referencia de la plataforma (spec 015, T10, hito H1; HU-015-3; RF-015-19 a RF-015-24,
RF-015-08 y RF-015-13; CE-015-02, CE-015-03 y CE-015-07; escenarios E1 y E2 de la §2; B7, errores
8 y 20; D-9).

Verifica **de forma independiente** lo que hicieron T06 a T09 (``design.platform``): cada cifra sale
de un cálculo a mano (aritmética entera o racional y bucles obvios, en este fichero) y **ningún**
valor esperado se calcula llamando al código bajo prueba. Tolerancia de D-9: ≤ 10⁻⁹ m (cotas) o
10⁻⁹ relativo (volúmenes y alturas) frente al cálculo a mano en las mismas celdas. Todo es
sintético, en el dominio y sin Blender; el terreno es el de ``tests.support.entity_fixtures``.

- **CE-015-03 · regresión del error 20** (RF-015-19): una plataforma de eje de 200 m y 20 m de ancho
  mide 200 m ± 1 celda (``L − 2 celdas < medida ≤ L + 1 celda``, RF-014-10), no los 220 m de un
  *buffer*: 4.000 celdas (y no 4.400), medida 199 m, y la rasante en los extremos es la cota inicial
  y la cota inicial más ``L · pendiente``. El eje horizontal y uno oblicuo de 3-4-5 (120 m al este y
  160 m al norte: 200 m exactos), cuya huella se cuenta con aritmética entera exacta (sin empates).
- **CE-015-02 · regresión de B7 y del error 8** (RF-015-20, RF-015-21, RF-015-22, RF-015-23,
  RF-015-24): la franja de 40 m al 1 % con 5 m de terreno por debajo de la rasante **aguas abajo**
  (``strip_case(hollow="downstream")``; decisión de la sesión principal, revisable: la zona por debajo
  de la rasante del CE-015-02 está aguas abajo). «En corte»: 0 m³ de relleno (nada sube: ningún lomo),
  38.400 m³ de corte (6 m × 6.400 celdas), el aviso de los 1.600 m² por debajo (5 m), la rasante a
  ≤ 10⁻⁹ m en las 6.400 celdas cortadas, ninguna contrapendiente y ninguna pared del borde más
  empinada que el ángulo de borde más la tolerancia de cara (41°). Con **un alcance corto** la pared
  aparece, solo en el límite del alcance. Con **un intocable** que cruza la huella, la contrapendiente
  (5,99 m) con su aviso y la confirmación. Con el tramo **en el medio** (``strip_case()``), el perfil
  baja en él y vuelve a subir aguas abajo: es una contrapendiente de 4,99 m (RF-015-23), no una
  plataforma sin ella.
- **CE-015-07 · borde de referencia** (RF-015-22, RF-015-08, D-20): una plataforma plana a 200 m, «en
  corte», sobre el plano inclinado ``z = 180 + y/4 + x/16`` (de 20 m de ancho, de oeste a este de
  lado a lado de la rejilla: ocupa las filas de y = 180 a 200, 8.000 celdas, y corta ``40 m`` de media),
  con el borde a 40° y un alcance de 30,5 m. La envolvente de una celda del borde a ``k`` celdas de
  la huella, en la misma columna (la semilla más próxima, a distancia ``k``), es ``200 + k · tan 40°``
  y el terreno en ella ``z(x, y)``: lo que corta el borde en esa celda es
  ``m(k) = z − 200 − k · tan 40° = A − s · k`` mientras es positivo (``A`` es el desmonte de la celda
  pegada a la huella y ``s = tan 40° ∓ 1/4``: el terreno sube hacia el norte, ``−``, y baja hacia el
  sur, ``+``). Cada fila de la cuña suma una serie aritmética: con ``K = mín(30, ⌈A/s⌉ − 1)`` celdas,
  ``V = Σ m(k) = K · A − s · K (K + 1) / 2``; el volumen del borde es la suma de las 800 columnas (sus
  celdas de la rejilla, por su centro), la **altura de su pared** es el mayor ``m(k)`` y las celdas de
  la pared más empinada que el ángulo más la tolerancia son las del límite del alcance (``k = 30``)
  con ``|z(31) − 200 − 30 tan 40°| > tan 41°``. El salto creado en ese límite es ``m(30)``. Sin
  alcance, el rechazo de RF-015-08.
- **E1 y E2** (§2): E1, el eje de 200 m, 20 m de ancho, cota 175 m y 1 % con su borde (el borde, contra
  una fuerza bruta de la envolvente sobre los bordes de la huella) y E2, «en corte» en una ladera con
  el terreno por debajo de la rasante en su parte baja: sin lomo y con el aviso de lo que no llega.
"""

from __future__ import annotations

import math
import unittest
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import entity_fixtures as efx
from tests.support.package import import_geoblender

platform = import_geoblender("design.platform")
model = import_geoblender("design.model")
params = import_geoblender("design.params")
messages = import_geoblender("design.messages")

DesignError = messages.DesignError
TOL = 1e-9
"""Metros (D-9): la rasante y la posición."""
RELATIVE = 1e-9
"""Relativo (D-9): los volúmenes y la altura de la pared."""
PROJECT = {params.TOLERANCE_FACE: 1.0, params.VERIFY_MIN_THICKNESS: 0.05,
           params.EDGE_MAX_STEP: 1.0, params.EDGE_MIN_SHARE: 99.0, params.WARNING_RATIO: 2.0}
"""Los parámetros del proyecto que leen el borde y el resumen (valores de la prueba)."""
GRID = efx.GRID
"""La rejilla de las pruebas: 400 × 400 celdas de 1 m, esquina suroeste en ``BASE``."""
ROWS, COLS = GRID.nrows, GRID.ncols
EDGE_ANGLE = 40.0
"""El ángulo de borde de las pruebas (°)."""
FACE_TOLERANCE = PROJECT[params.TOLERANCE_FACE]
LIMIT_DEG = EDGE_ANGLE + FACE_TOLERANCE
"""Lo que una pared del borde puede tener sin avisar: el ángulo más la tolerancia de cara (41°)."""


# --- Lo que construyen las pruebas ---------------------------------------------------------------


def request(name: str = "P1") -> Any:
    return model.PlatformRequest(
        name=name, feature=name, start="Terreno",
        fields=model.PlatformFields(layer=efx.AXES_LAYER, start_level_field="cota_inicial",
                                    gradient_field="pendiente", width_field="ancho"))


def line_job(terrain: np.ndarray, axis: tuple[tuple[float, float], ...], *, width: float,
             start: float, gradient: float, mode: str = "cut", reach: float | None = 12.5,
             angle: float = EDGE_ANGLE, cut_allowed: np.ndarray | None = None,
             fill_allowed: np.ndarray | None = None) -> Any:
    """El trabajo de una plataforma de eje ``axis`` (local) sobre ``terrain`` (toda la rejilla);
    ``reach=None`` no lleva alcance."""
    values: dict[str, object] = {
        "width_m": width, "start_level_m": start, "gradient_pct": gradient,
        "edge_angle_deg": angle, "mode": mode}
    if reach is not None:
        values["reach_m"] = reach
    allowed = np.ones(terrain.shape, dtype=bool)
    return platform.PlatformJob(
        request(), "PLT-001", GRID, terrain, platform.PlatformGeometry(
            "line", ((cfx.absolute(axis),),)), values,
        allowed.copy() if cut_allowed is None else cut_allowed,
        allowed.copy() if fill_allowed is None else fill_allowed)


@dataclass(frozen=True, slots=True, eq=False)
class Calc:
    """Todo el cálculo de una plataforma: el trabajo, la huella, lo aplicado, el borde y el resultado
    (``outcome``), con el terreno y las máscaras de la ventana de trabajo (``z0``, ``cut_ok``)."""

    job: Any
    footprint: Any
    applied: Any
    edge: Any
    outcome: Any

    @property
    def window(self) -> tuple[slice, slice]:
        return self.footprint.window

    @property
    def z0(self) -> np.ndarray:
        return self.job.start[self.window]

    @property
    def cut_ok(self) -> np.ndarray:
        return self.job.cut_allowed[self.window]

    @property
    def result(self) -> np.ndarray:
        return self.outcome.result


def calculate(job: Any, **kwargs: Any) -> Calc:
    footprint = platform.platform_footprint(job)
    applied = platform.apply_platform(job, footprint)
    edge = platform.platform_edge(job, footprint, applied, PROJECT)
    outcome = platform.platform_outcome(job, footprint, applied, edge, PROJECT, **kwargs)
    return Calc(job, footprint, applied, edge, outcome)


def codes(calc: Calc) -> list[str]:
    return [item.code for item in calc.outcome.notices]


def notice(calc: Calc, code: str) -> dict[str, object]:
    """Los valores del aviso ``code`` del resultado (y ``AssertionError`` si no está)."""
    for item in calc.outcome.notices:
        if item.code == code:
            return dict(item.values)
    raise AssertionError(f"el resultado no trae el aviso {code}: {codes(calc)}")


def figures(calc: Calc) -> dict[str, float | None]:
    return {item.key: item.value for item in calc.outcome.figures}


def absolute(x: float, y: float) -> tuple[float, float]:
    """El punto local (m desde ``BASE``) en absolutas."""
    return float(cfx.BASE[0]) + x, float(cfx.BASE[1]) + y


# --- Oráculos: el cálculo a mano de este fichero -------------------------------------------------


def centres(window: tuple[slice, slice]) -> tuple[np.ndarray, np.ndarray]:
    """Los centros locales (m desde la esquina suroeste) de las celdas de ``window``: ``x`` al este e
    ``y`` al norte; la fila 0 es el norte."""
    rows, cols = window
    x = (np.arange(cols.start, cols.stop) + 0.5)[None, :] + np.zeros((rows.stop - rows.start, 1))
    y = (ROWS - np.arange(rows.start, rows.stop) - 0.5)[:, None] + np.zeros(
        (1, cols.stop - cols.start))
    return x, y


def plane(x: np.ndarray | float, y: np.ndarray | float) -> np.ndarray | float:
    """El plano inclinado del terreno de CE-015-07 en un punto local: ``180 + y/4 + x/16`` (exacto
    en binario)."""
    return 180.0 + y / 4.0 + x / 16.0


def hand_corridor(axis: tuple[tuple[int, int], tuple[int, int]], width: int,
                  window: tuple[slice, slice]) -> tuple[np.ndarray, np.ndarray]:
    """La huella de un corredor de extremos planos y su abscisa, **en aritmética entera**: para un eje
    de extremos enteros ``a`` → ``b`` con ``|b − a| = L`` entero y un ancho entero, el centro de la
    celda ``(px, py)`` (semientero) da ``m = 2·(px − ax)`` y ``n = 2·(py − ay)`` enteros y, con
    ``v = b − a``, la abscisa es ``t = (m·vx + n·vy) / (2·L)`` y la distancia al eje
    ``|m·vy − n·vx| / (2·L)``: la celda es de la huella si ``0 ≤ m·vx + n·vy ≤ 2·L²`` y
    ``|m·vy − n·vx| ≤ ancho · L`` (sin empates si ``2·L`` y los semienteros no los dan: se
    comprueba). Devuelve ``(celdas, t)`` de la forma de ``window`` (``t`` es ``NaN`` fuera)."""
    (ax, ay), (bx, by) = axis
    vx, vy = bx - ax, by - ay
    length = math.isqrt(vx * vx + vy * vy)
    if length * length != vx * vx + vy * vy:
        raise AssertionError("el eje de la prueba debe medir un número entero de metros")
    rows, cols = window
    m = (2 * np.arange(cols.start, cols.stop) + 1 - 2 * ax)[None, :].astype(np.int64)
    n = (2 * (ROWS - np.arange(rows.start, rows.stop)) - 1 - 2 * ay)[:, None].astype(np.int64)
    along = m * vx + n * vy
    across = np.abs(m * vy - n * vx)
    if ((along == 0) | (along == 2 * length * length) | (across == width * length)).any():
        raise AssertionError("la prueba debe evitar los empates con el contorno de la huella")
    cells = (along > 0) & (along < 2 * length * length) & (across < width * length)
    return cells, np.where(cells, along / (2.0 * length), np.nan)


def hand_grade(position_m: float, origin_m: float, start: float, gradient_pct: float) -> float:
    """La rasante a mano en un centro de celda (semientero) a ``position_m`` m en el eje, desde
    ``origin_m``: ``cota inicial + (posición − origen) · pendiente / 100``, en racionales."""
    centre = Fraction(round(2 * position_m), 2)
    return float(Fraction(start) + (centre - Fraction(origin_m)) * Fraction(gradient_pct) / 100)


def dilate8(mask: np.ndarray) -> np.ndarray:
    """``mask`` y sus 8 vecinas."""
    padded = np.pad(mask, 1, constant_values=False)
    found = np.zeros(mask.shape, dtype=bool)
    for d_row in (-1, 0, 1):
        for d_col in (-1, 0, 1):
            found |= padded[1 + d_row:1 + d_row + mask.shape[0], 1 + d_col:1 + d_col + mask.shape[1]]
    return found


def max_tangent8(z: np.ndarray) -> np.ndarray:
    """La mayor pendiente (tangente) de cada celda a sus 8 vecinas con dato, de celdas de 1 m
    (D-13: la diferencia de cota entre la distancia entre centros)."""
    padded = np.pad(z, 1, constant_values=np.nan)
    best = np.zeros(z.shape)
    for d_row in (-1, 0, 1):
        for d_col in (-1, 0, 1):
            if d_row == 0 and d_col == 0:
                continue
            neighbour = padded[1 + d_row:1 + d_row + z.shape[0], 1 + d_col:1 + d_col + z.shape[1]]
            with np.errstate(invalid="ignore"):
                best = np.fmax(best, np.abs(z - neighbour) / math.hypot(d_row, d_col))
    return best


def brute_edge(z: np.ndarray, seeds: np.ndarray, seed_level: np.ndarray, tan: float
               ) -> tuple[np.ndarray, np.ndarray]:
    """La envolvente ascendente ``mín_q [nivel_q + tan · |p − q|]`` y la distancia a la semilla más
    próxima ``mín_q |p − q|`` (m, centros de celdas de 1 m) **por fuerza bruta** sobre las semillas
    del borde del conjunto de semillas (las que tienen una vecina que no lo es: la semilla más
    próxima a una celda de fuera, y con ella la que da la envolvente si ``tan`` pasa de la pendiente
    de la rasante, siempre es de ese borde: un paso hacia la celda la acerca más de lo que sube)."""
    inner = np.pad(seeds, 1, constant_values=False)
    interior = np.ones(seeds.shape, dtype=bool)
    for d_row in (-1, 0, 1):
        for d_col in (-1, 0, 1):
            interior &= inner[1 + d_row:1 + d_row + seeds.shape[0],
                              1 + d_col:1 + d_col + seeds.shape[1]]
    rows, cols = np.indices(seeds.shape)
    envelope = np.full(seeds.shape, np.inf)
    nearest = np.full(seeds.shape, np.inf)
    for row, col in zip(*np.nonzero(seeds & ~interior), strict=True):
        distance = np.hypot(rows - row, cols - col)
        np.minimum(envelope, seed_level[row, col] + tan * distance, out=envelope)
        np.minimum(nearest, distance, out=nearest)
    return envelope, nearest


@dataclass(frozen=True, slots=True, eq=False)
class HandEdge:
    """El borde y la plataforma a mano (``brute_edge``) en la ventana: ``surface`` (huella aplicada y
    borde), ``changed`` (las celdas que el borde corta), ``nearest`` (la distancia a las semillas),
    ``volume`` (m³ del borde: ``Σ (z − envolvente)``) y ``wall`` (el mayor corte, la altura de la
    pared del borde)."""

    surface: np.ndarray
    changed: np.ndarray
    nearest: np.ndarray
    volume: float
    wall: float
    filled: np.ndarray
    fill_volume: float


def hand_edge(z0: np.ndarray, footprint: np.ndarray, grade: np.ndarray, cut_ok: np.ndarray,
              reach: float, angle: float = EDGE_ANGLE, *, mode: str = "cut",
              fill_ok: np.ndarray | None = None) -> HandEdge:
    """La plataforma y su borde a mano: dentro de la huella, ``mín(z, rasante)`` donde se corta (y, en
    «en corte y relleno», ``rasante`` donde se rellena); semillas, las celdas de la huella que quedan
    en la rasante; fuera de la huella y donde el alcance llega, ``z' = ENV↑`` si ``z`` está por encima
    de ella y se corta y, en «en corte y relleno», ``z' = ENV↓ = máx_q [nivel_q − tan · d]`` si ``z``
    está por debajo y se rellena (gana la descendente si se cruzan)."""
    fill_ok = np.ones(z0.shape, dtype=bool) if fill_ok is None else fill_ok
    plat = np.where(footprint & cut_ok, np.minimum(z0, grade), z0)
    if mode == "cut_fill":
        plat = np.where(footprint & fill_ok & (z0 < grade), grade, plat)
    seeds = footprint & (np.abs(plat - grade) <= 1e-9)
    tan = math.tan(math.radians(angle))
    level = np.where(seeds, grade, np.nan)
    up, nearest = brute_edge(z0, seeds, level, tan)
    near = ~footprint & (nearest <= reach)
    changed = near & cut_ok & (z0 > up)
    surface = np.where(changed, up, plat)
    cut = (z0 - surface)[changed]
    filled = np.zeros(z0.shape, dtype=bool)
    fill_volume = 0.0
    if mode == "cut_fill":
        down = -brute_edge(z0, seeds, -level, tan)[0]
        filled = near & fill_ok & (z0 < down)
        surface = np.where(filled, down, surface)
        changed &= ~filled
        cut = (z0 - surface)[changed]
        fill_volume = math.fsum((surface - z0)[filled].tolist())
    return HandEdge(surface, changed, nearest, math.fsum(cut.tolist()),
                    float(cut.max()) if cut.size else 0.0, filled, fill_volume)


def steep_by_hand(z0: np.ndarray, surface: np.ndarray, changed: np.ndarray) -> np.ndarray:
    """Las celdas que el borde mueve y quedan más empinadas que el ángulo de borde más la tolerancia
    de cara (41°) y que lo que el terreno ya tenía en ellas (RF-015-22: el terreno no cuenta)."""
    new, own = max_tangent8(surface), max_tangent8(z0)
    return changed & (np.degrees(np.arctan(new)) > LIMIT_DEG) & (new > own)


def counter_rise(levels: list[float], gradient_pct: float) -> list[float]:
    """La contrapendiente de cada tramo del perfil (``levels``, en abscisa creciente) **por fuerza
    bruta**: recorrido en el sentido en que baja la rasante (hacia las abscisas grandes con pendiente
    negativa, hacia las pequeñas con positiva), lo que sube su cota sobre el mínimo de los tramos
    ya recorridos; con 0 %, sobre el mínimo de todos (D-16)."""
    count = len(levels)
    if gradient_pct == 0.0:
        low = min(levels)
        return [level - low for level in levels]
    order = list(range(count)) if gradient_pct < 0.0 else list(range(count - 1, -1, -1))
    found = [0.0] * count
    for position, k in enumerate(order):
        before = [levels[j] for j in order[:position]]
        found[k] = max(levels[k] - min(before), 0.0) if before else 0.0
    return found


def column_profile(result: np.ndarray, footprint: np.ndarray) -> list[float]:
    """El perfil longitudinal de una plataforma de eje horizontal (oeste a este), a mano: la cota más
    alta de la huella en cada columna (un tramo de una celda de abscisa), de oeste a este."""
    return [float(result[footprint[:, c], c].max()) for c in np.flatnonzero(footprint.any(axis=0))]


def row_profile(result: np.ndarray, footprint: np.ndarray) -> list[float]:
    """El de una plataforma de eje vertical (sur a norte): la cota más alta de cada fila de la huella,
    de sur a norte (la abscisa crece hacia el norte)."""
    rows = np.flatnonzero(footprint.any(axis=1))[::-1]
    return [float(result[r, footprint[r]].max()) for r in rows]


def close(test: unittest.TestCase, found: float, expected: float, *, absolute_m: float = 0.0,
          relative: float = RELATIVE, msg: str | None = None) -> None:
    """``found`` y ``expected`` a ≤ ``absolute_m`` (m) o a ≤ ``relative`` (relativo): D-9."""
    limit = max(absolute_m, relative * abs(expected))
    test.assertLessEqual(abs(found - expected), limit,
                         msg or f"{found!r} y {expected!r} difieren en {abs(found - expected)!r}")


# --- CE-015-03: el eje de 200 m mide 200 m, no 220 m -----------------------------------------------


class AxisLengthCE03Test(unittest.TestCase):
    """CE-015-03 (regresión del error 20; RF-015-19, RF-014-10): una plataforma de eje de 200 m (de
    (100, 100) a (300, 100)) y 20 m de ancho, cota 175 m y 1 % (el E1 de la spec)."""

    AXIS = ((100.0, 100.0), (300.0, 100.0))

    @classmethod
    def setUpClass(cls) -> None:
        cls.job = line_job(efx.plane_terrain(), cls.AXIS, width=20.0, start=175.0, gradient=1.0,
                           reach=12.5)
        cls.fp = platform.platform_footprint(cls.job)
        cls.hand, cls.hand_t = hand_corridor(((100, 100), (300, 100)), 20, cls.fp.window)

    def test_the_footprint_is_200_by_20_cells_not_a_220_m_buffer(self) -> None:
        """RF-015-19: son las 4.000 celdas del rectángulo de 200 × 20 m (x de 100 a 300, y de 90 a
        110: no los 4.400 m² de 220 × 20 de un *buffer* de extremos redondos o cuadrados), iguales
        a las de la aritmética entera."""
        fp = self.fp
        np.testing.assert_array_equal(fp.cells, self.hand)
        self.assertEqual(fp.cell_count, 4_000)
        self.assertEqual(fp.area_m2, 4_000.0)
        self.assertNotEqual(fp.area_m2, 220.0 * 20.0)
        columns = np.flatnonzero(fp.cells.any(axis=0))
        rows = np.flatnonzero(fp.cells.any(axis=1))
        self.assertEqual((columns.size, rows.size), (200, 20))  # no 220 columnas
        self.assertEqual(columns[-1] - columns[0] + 1, 200)

    def test_the_measured_length_is_the_axis_within_one_cell(self) -> None:
        """RF-015-19, RF-014-10: ``L − 2 celdas < medida ≤ L + 1 celda`` con L = 200 m y celdas de
        1 m: la medida es el máximo menos el mínimo de la abscisa de las celdas, de 0,5 a 199,5 m =
        199 m; y el eje usado mide 200 m."""
        fp = self.fp
        self.assertLess(198.0, fp.length_m)
        self.assertLessEqual(fp.length_m, 201.0)
        self.assertNotAlmostEqual(fp.length_m, 220.0, delta=1.0)
        close(self, fp.length_m, 199.0, absolute_m=TOL)
        close(self, float(np.nanmax(self.hand_t) - np.nanmin(self.hand_t)), fp.length_m,
              absolute_m=TOL)
        close(self, fp.axis.length_m, 200.0, absolute_m=TOL)

    def test_the_grade_at_the_ends_is_the_start_level_and_start_plus_length_by_slope(self) -> None:
        """RF-015-19: la rasante es ``175 + σ · 0,01``: ``cota_inicial = 175`` en el primer vértice y
        ``175 + 200 · 0,01 = 177`` en el último; en los centros de la primera y la última columna,
        175,005 y 176,995; en cada celda de la huella, a ≤ 10⁻⁹ m de la cuenta a mano en
        racionales."""
        fp = self.fp
        close(self, fp.start_level_m, 175.0, absolute_m=TOL)
        close(self, fp.end_level_m, 177.0, absolute_m=TOL)
        x, _y = centres(fp.window)
        expected = np.array([hand_grade(float(value), 100.0, 175.0, 1.0)
                             for value in x[0]])  # una cuenta por columna: la sección es horizontal
        found = fp.levels
        for column in np.flatnonzero(fp.cells.any(axis=0)):
            level = found[fp.cells[:, column], column]
            self.assertLessEqual(float(np.abs(level - expected[column]).max()), TOL)
        values = found[fp.cells]
        close(self, float(values.min()), 175.005, absolute_m=TOL)
        close(self, float(values.max()), 176.995, absolute_m=TOL)
        self.assertTrue(np.isnan(found[~fp.cells]).all())


class ObliqueAxisCE03Test(unittest.TestCase):
    """CE-015-03: un eje oblicuo de 3-4-5 (de (100, 100) a (220, 260): 120 m al este y 160 m al
    norte, 200 m exactos) de 20 m de ancho, cota 175 m y 1 %: la huella no pasa de los 200 m, y se
    cuenta con aritmética entera (sin empates con el contorno)."""

    @classmethod
    def setUpClass(cls) -> None:
        axis = ((100.0, 100.0), (220.0, 260.0))
        cls.job = line_job(efx.plane_terrain(), axis, width=20.0, start=175.0, gradient=1.0,
                           reach=12.5)
        cls.fp = platform.platform_footprint(cls.job)
        cls.hand, cls.hand_t = hand_corridor(((100, 100), (220, 260)), 20, cls.fp.window)

    def test_the_footprint_is_the_integer_count(self) -> None:
        """RF-015-19: las celdas son las que da la aritmética entera (``0 < t < 200`` y a menos de
        10 m del eje), ni una más: un *buffer* de extremos planos de 200 × 20 m tiene ~4.000 celdas
        y uno redondo o cuadrado de 220 m, más."""
        self.assertEqual(self.fp.cell_count, int(self.hand.sum()))
        np.testing.assert_array_equal(self.fp.cells, self.hand)
        self.assertLess(abs(self.fp.cell_count - 4_000), 40)  # 200 × 20 m, con el escalón oblicuo
        self.assertLess(self.fp.cell_count, 4_400 - 200)

    def test_it_measures_the_axis_within_one_cell_and_the_grade_is_by_hand(self) -> None:
        """RF-015-19, RF-014-10: la medida es el máximo menos el mínimo de ``t`` de las celdas (la del
        cálculo a mano) y cae en ``(L − 2 celdas; L + 1 celda]``; la rasante de cada celda es
        ``175 + t · 0,01`` a ≤ 10⁻⁹ m; los extremos, 175 m y 177 m."""
        fp = self.fp
        measured = float(np.nanmax(self.hand_t) - np.nanmin(self.hand_t))
        close(self, fp.length_m, measured, absolute_m=TOL)
        self.assertLess(198.0, fp.length_m)
        self.assertLessEqual(fp.length_m, 201.0)
        close(self, fp.axis.length_m, 200.0, absolute_m=TOL)
        close(self, fp.start_level_m, 175.0, absolute_m=TOL)
        close(self, fp.end_level_m, 177.0, absolute_m=TOL)
        expected = 175.0 + self.hand_t[self.hand] * 1.0 / 100.0
        self.assertLessEqual(float(np.abs(fp.levels[fp.cells] - expected).max()), TOL)


# --- CE-015-02: la franja «en corte» con el terreno por debajo de la rasante --------------------


class StripCE02Test(unittest.TestCase):
    """CE-015-02 (regresión de B7 y del error 8; RF-015-20, RF-015-22, RF-015-23, RF-015-24): una
    plataforma «en corte» al 1 % en una franja de 40 m, 200 m de eje, desde 230 m, con el terreno 6 m
    por encima de la rasante y 5 m por debajo en sus 40 primeros metros (aguas abajo: la rasante baja
    hacia ellos)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.case = efx.strip_case(hollow="downstream")
        cls.calc = calculate(line_job(cls.case.terrain, efx.STRIP_AXIS_LOCAL, width=40.0,
                                      start=230.0, gradient=1.0))
        c = cls.calc
        x, _y = centres(c.window)
        cls.footprint = c.footprint.cells
        cls.grade = np.where(cls.footprint, np.vectorize(
            lambda value: hand_grade(float(value), 100.0, 230.0, 1.0))(x), np.nan)
        cls.hollow = cls.case.hollow[c.window]
        cls.hand = hand_edge(c.z0, cls.footprint, cls.grade, c.cut_ok, 12.5)

    def test_no_fill_and_no_ridge(self) -> None:
        """RF-015-20, B7: «en corte» no sube ninguna celda: 0 m³ de relleno en la huella y en el
        borde y en toda la ventana ``z' ≤ z``; el tramo bajo la rasante queda **intacto, bit a bit**,
        5 m por debajo de ella (no es un lomo subido a la rasante)."""
        c = self.calc
        self.assertEqual(c.applied.fill_m3, 0.0)
        self.assertEqual(c.edge.fill_m3, 0.0)
        self.assertEqual(c.outcome.total_fill_m3, 0.0)
        self.assertEqual((c.applied.fill_cells, c.edge.fill_cells), (0, 0))
        self.assertEqual(float(np.maximum(c.result - c.z0, 0.0).sum()), 0.0)
        np.testing.assert_array_equal(c.result[self.hollow], c.z0[self.hollow])
        self.assertLessEqual(float(np.abs((self.grade - c.result)[self.hollow] - 5.0).max()), TOL)
        self.assertEqual(figures(c)["des.plat_fill_m3"], 0.0)
        self.assertEqual(figures(c)["des.edge_fill_m3"], 0.0)

    def test_the_cut_of_the_footprint_is_6_m_over_6400_cells(self) -> None:
        """RF-015-20, RF-015-24: 6 m × (8.000 − 1.600) celdas = 38.400 m³ de corte de la huella, a ≤ 10⁻⁹
        relativo, igual a la suma de ``z − rasante`` en las celdas por encima (cuenta a mano) y a la
        cifra ``des.plat_cut_m3``."""
        c = self.calc
        above = self.footprint & (c.z0 > self.grade)
        by_hand = math.fsum((c.z0 - self.grade)[above].tolist())
        self.assertEqual(int(above.sum()), 8_000 - 1_600)
        close(self, by_hand, 6.0 * 6_400.0)
        close(self, c.applied.cut_m3, 38_400.0)
        close(self, c.applied.cut_m3, by_hand)
        close(self, figures(c)["des.plat_cut_m3"], 38_400.0)
        self.assertEqual(c.applied.cut_cells, 6_400)

    def test_the_grade_is_met_at_every_cut_cell(self) -> None:
        """RF-015-19, RF-015-20: la superficie en las 6.400 celdas cortadas es la rasante a mano (en
        racionales, ``230 + (x − 100) · 0,01``), a ≤ 10⁻⁹ m."""
        c = self.calc
        cut = self.footprint & (c.z0 > self.grade)
        self.assertLessEqual(float(np.abs(c.result - self.grade)[cut].max()), TOL)
        self.assertEqual(int(cut.sum()), 6_400)
        close(self, float(self.grade[self.footprint].min()), 230.005, absolute_m=TOL)
        close(self, float(self.grade[self.footprint].max()), 231.995, absolute_m=TOL)

    def test_the_notice_of_the_area_below_the_grade(self) -> None:
        """RF-015-24, RF-015-13: «en corte» avisa del área por debajo de la rasante (que no rellena): un
        grupo de 1.600 m², 5 m de diferencia y su lugar, el centro del tramo, (120, 200) local, al cm;
        y las cifras ``des.plat_below_m2`` y ``des.plat_below_max_m``."""
        c = self.calc
        summary = notice(c, "des.platform_below")
        self.assertEqual((summary["area"], summary["maximum"], summary["groups"]), (1_600.0, 5.0, 1))
        group = notice(c, "des.platform_below_group")
        self.assertEqual((group["cells"], group["area"], group["maximum"]), (1_600, 1_600.0, 5.0))
        x, y = absolute(120.0, 200.0)
        self.assertAlmostEqual(float(group["x"]), x, places=2)  # type: ignore[arg-type]
        self.assertAlmostEqual(float(group["y"]), y, places=2)  # type: ignore[arg-type]
        self.assertEqual(figures(c)["des.plat_below_m2"], 1_600.0)
        self.assertEqual(figures(c)["des.plat_below_max_m"], 5.0)
        below = c.applied.below
        self.assertEqual(len(below), 1)
        self.assertEqual(below[0].cause, platform.OffLevelCause.NOT_FILLED)
        self.assertEqual(c.applied.above, ())
        self.assertNotIn("des.platform_above", codes(c))

    def test_there_is_no_counterslope(self) -> None:
        """RF-015-23: el perfil longitudinal (la cota más alta de cada columna), recorrido en el sentido
        en que baja la rasante (hacia la abscisa 0), solo baja: ninguna contrapendiente, con la
        contrapendiente de cada tramo calculada por fuerza bruta sobre la superficie resultante; se
        puede crear sin confirmar y no hay aviso."""
        c = self.calc
        levels = column_profile(c.result, self.footprint)
        self.assertEqual(len(levels), 200)
        rise = counter_rise(levels, 1.0)
        self.assertEqual(max(rise), 0.0)
        profile = c.outcome.profile
        np.testing.assert_allclose(profile.level_m, levels, rtol=0.0, atol=TOL)
        np.testing.assert_allclose(profile.rise_m, rise, rtol=0.0, atol=TOL)
        self.assertEqual(profile.counter_sections, 0)
        self.assertFalse(c.outcome.counter_slope or c.outcome.needs_confirmation)
        self.assertIsNone(c.outcome.ensure_creatable())
        self.assertFalse([item for item in codes(c) if "counter" in item])
        # Los 40 primeros tramos son los del hueco (5 m por debajo): bajan y no vuelven a subir.
        self.assertLess(levels[39], levels[40] - 4.0)

    def test_the_edge_is_the_brute_force_one(self) -> None:
        """RF-015-22: la superficie entera (huella y borde) y el volumen del borde coinciden con una
        fuerza bruta de la envolvente a 40° sobre los bordes de las semillas (a ≤ 10⁻⁹ m y a ≤ 10⁻⁹
        relativo), el mismo conjunto de celdas y la altura de la pared (el mayor corte del borde); los
        avisos de la pared solo existen si algo pasa de 41°."""
        c, hand = self.calc, self.hand
        self.assertLessEqual(float(np.abs(c.result - hand.surface).max()), TOL)
        np.testing.assert_array_equal(c.edge.changed, hand.changed)
        close(self, c.edge.cut_m3, hand.volume)
        self.assertEqual(c.edge.cut_cells, int(hand.changed.sum()))
        close(self, c.edge.wall_max_m, hand.wall)
        close(self, figures(c)["des.edge_cut_m3"], hand.volume)
        close(self, figures(c)["des.edge_wall_max_m"], hand.wall)
        self.assertEqual(c.edge.fill_m3, 0.0)

    def test_no_wall_is_steeper_than_the_edge_angle_plus_the_face_tolerance(self) -> None:
        """RF-015-22 (error 8): con el alcance (12,5 m) cubriendo todo el desmonte del borde (6 m a
        40°: 7 celdas), ninguna celda que el borde mueve queda más empinada que 41° (ni más que lo que
        el terreno tenía): ni a mano ni en el borde; y el borde a 40° (no a 87°, el disco de la
        balsa) llega a 40,000°."""
        c, hand = self.calc, self.hand
        by_hand = steep_by_hand(c.z0, c.result, hand.changed)
        self.assertFalse(by_hand.any())
        self.assertEqual(c.edge.steep_cells, 0)
        self.assertEqual(c.edge.walls, ())
        self.assertNotIn("des.platform_edge_steep", codes(c))
        # Una celda del borde pegada a un tramo cortado a la rasante: 40°, no más.
        new = np.degrees(np.arctan(max_tangent8(c.result)))
        edge_cells = hand.changed & ~dilate8(self.hollow)
        self.assertAlmostEqual(float(new[edge_cells].max()), EDGE_ANGLE, delta=0.5)
        self.assertLessEqual(float(new[edge_cells].max()), LIMIT_DEG)

    def test_the_default_mode_is_cut(self) -> None:
        """D-5: sin el valor ``mode`` el modo es «en corte»: el mismo resultado, bit a bit."""
        c = self.calc
        values = {key: value for key, value in c.job.values.items() if key != "mode"}
        other = calculate(platform.PlatformJob(
            c.job.request, c.job.code, c.job.grid, c.job.start, c.job.geometry, values,
            c.job.cut_allowed, c.job.fill_allowed))
        np.testing.assert_array_equal(other.result, c.result)
        self.assertEqual(other.applied.mode, model.PlatformMode.CUT)


class StripCutFillCE02Test(unittest.TestCase):
    """RF-015-21 como contraste de CE-015-02: la misma franja en «en corte y relleno» sí rellena el
    tramo bajo la rasante, 5 m × 1.600 celdas = 8.000 m³, y deja toda la huella en la rasante."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.case = efx.strip_case(hollow="downstream")
        cls.calc = calculate(line_job(cls.case.terrain, efx.STRIP_AXIS_LOCAL, width=40.0,
                                      start=230.0, gradient=1.0, mode="cut_fill"))

    def test_the_stretch_is_filled_exactly_and_the_whole_footprint_is_at_the_grade(self) -> None:
        """RF-015-21: 8.000 m³ de relleno, 38.400 m³ de corte, ningún grupo por debajo ni por encima
        de la rasante, y la huella entera en la rasante a ≤ 10⁻⁹ m; ninguna contrapendiente."""
        c = self.calc
        close(self, c.applied.fill_m3, 5.0 * 1_600.0)
        close(self, c.applied.cut_m3, 6.0 * 6_400.0)
        self.assertEqual((c.applied.above, c.applied.below), ((), ()))
        self.assertEqual(int(c.applied.at_level.sum()), 8_000)
        x, _y = centres(c.window)
        grade = np.vectorize(lambda value: hand_grade(float(value), 100.0, 230.0, 1.0))(x)
        footprint = c.footprint.cells
        self.assertLessEqual(float(np.abs(c.result - grade)[footprint].max()), TOL)
        self.assertEqual(c.edge.fill_m3, 0.0)  # el terreno de fuera queda 6 m por encima
        self.assertFalse(c.outcome.counter_slope)
        self.assertEqual(c.outcome.off_level_area_m2, 0.0)


class StripReachLimitCE02Test(unittest.TestCase):
    """CE-015-02 y RF-015-22: la pared **sí** aparece en el límite del alcance, y solo ahí. La misma
    franja con un alcance de 3,5 m (el borde a 40° necesita 7 celdas para llegar al terreno): lo que el
    borde mueve queda cortado en seco contra lo que el alcance deja sin tocar."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.case = efx.strip_case(hollow="downstream")
        cls.calc = calculate(line_job(cls.case.terrain, efx.STRIP_AXIS_LOCAL, width=40.0,
                                      start=230.0, gradient=1.0, reach=3.5))
        c = cls.calc
        x, _y = centres(c.window)
        cls.grade = np.where(c.footprint.cells, np.vectorize(
            lambda value: hand_grade(float(value), 100.0, 230.0, 1.0))(x), np.nan)
        cls.hand = hand_edge(c.z0, c.footprint.cells, cls.grade, c.cut_ok, 3.5)

    def test_the_walls_are_the_ones_by_hand_and_all_at_the_reach_limit(self) -> None:
        """RF-015-22: las celdas más empinadas son las de la oráculo a mano (el mismo conjunto), no
        son pocas (la pared de ~3,5 m del límite, sobre 74°), y **todas** tocan una celda que el alcance
        deja sin tocar (a más de 3,5 m de la huella): causa ``reach``, ninguna de las máscaras ni de la
        propia plataforma."""
        c, hand = self.calc, self.hand
        np.testing.assert_array_equal(c.result == hand.surface, np.ones(c.result.shape, bool))
        steep = steep_by_hand(c.z0, c.result, hand.changed)
        np.testing.assert_array_equal(c.edge.steep, steep)
        self.assertGreater(int(steep.sum()), 100)
        beyond = (hand.nearest > 3.5) & ~c.footprint.cells
        self.assertTrue((~steep | dilate8(beyond)).all(),
                        "una celda más empinada que 41° que no toca el límite del alcance")
        self.assertEqual([(wall.cause, wall.cells) for wall in c.edge.walls],
                         [(platform.WallCause.REACH, int(steep.sum()))])
        degrees = np.degrees(np.arctan(max_tangent8(c.result)))
        self.assertAlmostEqual(c.edge.walls[0].max_deg, float(degrees[steep].max()), places=9)
        self.assertGreater(c.edge.walls[0].max_deg, 70.0)

    def test_the_notices_give_the_steep_wall_and_the_created_step(self) -> None:
        """RF-015-22, RF-015-13: ``des.platform_edge_steep`` con el límite de 41° y el alcance de 3,5 m y
        todas las celdas «del alcance», y el salto creado (RF-014-21) avisado, de 3,6 m."""
        c = self.calc
        steep = notice(c, "des.platform_edge_steep")
        self.assertEqual((steep["limit"], steep["reach"], steep["at_masks"], steep["other"]),
                         (41.0, 3.5, 0, 0))
        self.assertEqual(steep["cells"], steep["at_reach"])
        created = notice(c, "des.edge_surface_step")
        self.assertGreater(float(created["maximum"]), 3.0)  # type: ignore[arg-type]
        self.assertTrue(c.edge.created.warned)
        self.assertGreater(c.edge.created.maximum_m, 3.0)


class StripPitCE02Test(unittest.TestCase):
    """RF-015-20 y RF-015-22 (B7): **ni el borde** de una plataforma «en corte» sube nada. La franja
    con un foso de 18 × 80 m y 25 m de profundidad pegado al norte de la huella (de y = 222 a 240, de
    x = 180 a 260: la envolvente descendente del borde, ``rasante − tan 40° · d``, queda muy por encima
    de su fondo): «en corte» lo deja intacto, bit a bit; «en corte y relleno» lo sube hasta esa
    envolvente, con el volumen de una fuerza bruta (el contraste que prueba que la prueba mira lo que
    debe)."""

    @classmethod
    def setUpClass(cls) -> None:
        case = efx.strip_case(hollow="downstream")
        x, y = centres((slice(0, ROWS), slice(0, COLS)))
        cls.pit = (x > 180.0) & (x < 260.0) & (y > 222.0) & (y < 240.0)
        cls.terrain = np.where(cls.pit, case.terrain - 25.0, case.terrain)
        cls.cut = cls.mode_case("cut")
        cls.cut_fill = cls.mode_case("cut_fill")

    @classmethod
    def mode_case(cls, mode: str) -> tuple[Calc, HandEdge, np.ndarray]:
        calc = calculate(line_job(cls.terrain, efx.STRIP_AXIS_LOCAL, width=40.0, start=230.0,
                                  gradient=1.0, mode=mode))
        x, _y = centres(calc.window)
        grade = np.where(calc.footprint.cells, np.vectorize(
            lambda value: hand_grade(float(value), 100.0, 230.0, 1.0))(x), np.nan)
        return calc, hand_edge(calc.z0, calc.footprint.cells, grade, calc.cut_ok, 12.5, mode=mode), \
            grade

    def test_cut_mode_leaves_the_pit_untouched_and_does_not_fill_with_the_edge(self) -> None:
        """RF-015-20, RF-015-22: «en corte» no rellena: 0 m³ en la huella y en el borde, ninguna celda
        de la ventana sube y las celdas del foso quedan **iguales a como estaban**; la superficie y el
        volumen del borde son los de la fuerza bruta."""
        c, hand, _grade = self.cut
        pit = self.pit[c.window]
        self.assertTrue(pit.any())
        self.assertEqual((c.applied.fill_m3, c.edge.fill_m3, c.edge.fill_cells), (0.0, 0.0, 0))
        self.assertEqual(float(np.maximum(c.result - c.z0, 0.0).sum()), 0.0)
        np.testing.assert_array_equal(c.result[pit], c.z0[pit])
        self.assertLessEqual(float(np.abs(c.result - hand.surface).max()), TOL)
        close(self, c.edge.cut_m3, hand.volume)
        self.assertFalse(hand.filled.any())

    def test_cut_and_fill_mode_raises_the_pit_to_the_descending_envelope(self) -> None:
        """RF-015-22: en «en corte y relleno» el borde sube el foso hasta ``rasante − tan 40° · d``
        (hasta 12,5 m de la huella): superficie, volumen de relleno y celdas, iguales a la fuerza bruta
        a ≤ 10⁻⁹ (más de mil m³: el contraste); el relleno de la huella son los 8.000 m³ del tramo."""
        c, hand, _grade = self.cut_fill
        close(self, c.applied.fill_m3, 5.0 * 1_600.0)
        self.assertGreater(hand.fill_volume, 1_000.0)
        close(self, c.edge.fill_m3, hand.fill_volume)
        self.assertEqual(c.edge.fill_cells, int(hand.filled.sum()))
        self.assertLessEqual(float(np.abs(c.result - hand.surface).max()), TOL)
        close(self, c.edge.cut_m3, hand.volume)


class StripUntouchableCE02Test(unittest.TestCase):
    """CE-015-02: con un intocable que cruza la huella (la banda de 10 m de x de 140 a 150, de lado a
    lado de la huella y sobresaliendo 10 m por cada lado) la plataforma queda 6 m por encima de su
    rasante en esas 400 celdas: **contrapendiente** con su aviso, y no se puede crear sin
    confirmación expresa (RF-015-23, B7)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.case = efx.strip_case(untouchable=True, hollow="downstream")
        cls.job = line_job(cls.case.terrain, efx.STRIP_AXIS_LOCAL, width=40.0, start=230.0,
                           gradient=1.0, cut_allowed=cls.case.cut_allowed,
                           fill_allowed=cls.case.fill_allowed)
        cls.calc = calculate(cls.job)
        c = cls.calc
        x, _y = centres(c.window)
        cls.grade = np.where(c.footprint.cells, np.vectorize(
            lambda value: hand_grade(float(value), 100.0, 230.0, 1.0))(x), np.nan)

    def test_the_untouchable_keeps_400_cells_6_m_above_the_grade(self) -> None:
        """RF-015-20, RF-015-13: 400 celdas de la huella sin cortar (intactas, 6 m por encima), 36.000
        m³ de corte (6 m × 6.000) y un grupo «por encima» de 400 m² y 6 m en su centro (145, 200)."""
        c = self.calc
        blocked = self.case.blocked[c.window]
        self.assertEqual(int(blocked.sum()), 400)
        np.testing.assert_array_equal(c.result[blocked], c.z0[blocked])
        self.assertLessEqual(float(np.abs((c.z0 - self.grade)[blocked] - 6.0).max()), TOL)
        close(self, c.applied.cut_m3, 6.0 * 6_000.0)
        self.assertEqual(c.applied.fill_m3, 0.0)
        summary = notice(c, "des.platform_above")
        self.assertEqual((summary["area"], summary["maximum"], summary["groups"]), (400.0, 6.0, 1))
        group = notice(c, "des.platform_above_group")
        x, y = absolute(145.0, 200.0)
        self.assertAlmostEqual(float(group["x"]), x, places=2)  # type: ignore[arg-type]
        self.assertAlmostEqual(float(group["y"]), y, places=2)  # type: ignore[arg-type]

    def test_the_counterslope_is_the_one_by_hand(self) -> None:
        """RF-015-23: de la abscisa 40 a la 50 la huella sin cortar queda en ``236 + 0,01 (k + 0,5)``
        y el mínimo aguas arriba (tramo 50) es ``230,505``: la contrapendiente es ``5,495 + 0,01
        (k + 0,5)`` en los tramos 40 a 49 (10 tramos) y la peor, 5,99 m, en la abscisa 49,5 (la celda
        (149,5; 219,5), la más al norte de su columna); los demás tramos, 0."""
        c = self.calc
        levels = column_profile(c.result, c.footprint.cells)
        rise = counter_rise(levels, 1.0)
        expected = [5.495 + 0.01 * (k + 0.5) if 40 <= k <= 49 else 0.0 for k in range(200)]
        np.testing.assert_allclose(rise, expected, rtol=0.0, atol=TOL)
        profile = c.outcome.profile
        np.testing.assert_allclose(profile.rise_m, expected, rtol=0.0, atol=TOL)
        np.testing.assert_array_equal(np.flatnonzero(profile.flagged), np.arange(40, 50))
        self.assertEqual((profile.counter_sections, profile.worst), (10, 49))
        close(self, float(profile.rise_m[49]), 5.99, absolute_m=TOL)
        close(self, float(profile.chainage_m[49]), 49.5, absolute_m=TOL)
        x, y = absolute(149.5, 219.5)
        close(self, float(profile.x[49]), x, absolute_m=TOL)
        close(self, float(profile.y[49]), y, absolute_m=TOL)

    def test_it_warns_and_needs_the_express_confirmation(self) -> None:
        """RF-015-23: el aviso lleva la abscisa (49,5 m), la cuantía (5,99 m), el lugar y la tolerancia
        (0,1 m, D-8); sin confirmar no se puede crear (``des.platform_counter_unconfirmed`` con la
        entidad, la cuantía y la tolerancia) y confirmada sí, con el aviso en la lista."""
        c = self.calc
        warned = notice(c, "des.platform_counter_slope")
        x, y = absolute(149.5, 219.5)
        self.assertEqual((warned["entity"], warned["amount"], warned["chainage"],
                          warned["tolerance"]), ("P1", 5.99, 49.5, 0.1))
        self.assertAlmostEqual(float(warned["x"]), x, places=2)  # type: ignore[arg-type]
        self.assertAlmostEqual(float(warned["y"]), y, places=2)  # type: ignore[arg-type]
        outcome = c.outcome
        self.assertTrue(outcome.counter_slope)
        self.assertTrue(outcome.needs_confirmation)
        with self.assertRaises(DesignError) as caught:
            outcome.ensure_creatable()
        error = caught.exception
        self.assertEqual(error.code, "des.platform_counter_unconfirmed")
        self.assertEqual((error.values["entity"], error.values["amount"],
                          error.values["tolerance"]), ("P1", 5.99, 0.1))
        sure = calculate(self.job, confirm_counterslope=True).outcome
        self.assertTrue(sure.confirmed)
        self.assertFalse(sure.needs_confirmation)
        self.assertIsNone(sure.ensure_creatable())
        self.assertIn("des.platform_counter_slope", [item.code for item in sure.notices])
        np.testing.assert_array_equal(sure.result, outcome.result)

    def test_the_walls_are_only_at_the_edge_of_what_the_masks_allow(self) -> None:
        """RF-015-22: junto al intocable el borde queda cortado en seco contra lo que las máscaras no
        dejan mover: las celdas empinadas (más de 41° y más que el terreno) son las de la oráculo a
        mano, todas pegadas a una celda sin corte admitido, de causa ``masks``: ninguna del alcance ni
        de la propia plataforma."""
        c = self.calc
        x, _y = centres(c.window)
        hand = hand_edge(c.z0, c.footprint.cells, self.grade, c.cut_ok, 12.5)
        np.testing.assert_array_equal(c.result == hand.surface, np.ones(c.result.shape, bool))
        steep = steep_by_hand(c.z0, c.result, hand.changed)
        self.assertTrue(steep.any())
        np.testing.assert_array_equal(c.edge.steep, steep)
        self.assertTrue((~steep | dilate8(~c.cut_ok)).all())
        self.assertEqual([wall.cause for wall in c.edge.walls], [platform.WallCause.MASKS])
        self.assertEqual(x.shape, c.result.shape)


class StripMiddleHollowCE02Test(unittest.TestCase):
    """RF-015-23 con el tramo bajo la rasante **en el medio** de la huella (``strip_case()``, de 80 a
    120 m del eje): la plataforma «en corte» no lo rellena y el perfil, recorrido hacia la abscisa 0,
    baja 5 m en el tramo y vuelve a subir al salir: **es** una contrapendiente (de 4,99 m), con su aviso
    y la confirmación; es el caso «aviso de la contrapendiente» que la T09 marcó."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.case = efx.strip_case()
        cls.job = line_job(cls.case.terrain, efx.STRIP_AXIS_LOCAL, width=40.0, start=230.0,
                           gradient=1.0)
        cls.calc = calculate(cls.job)

    def test_the_profile_goes_up_after_the_stretch_by_4_99_m(self) -> None:
        """RF-015-23: los tramos 0 a 79 (aguas abajo del hueco, que baja a ``225,805`` en la abscisa
        80,5) suben sobre ese mínimo ``230 + 0,01 (k + 0,5) − 225,805``: 80 tramos con la peor, 4,99 m
        en la abscisa 79,5, la celda (179,5; 219,5)."""
        c = self.calc
        levels = column_profile(c.result, c.footprint.cells)
        rise = counter_rise(levels, 1.0)
        expected = [230.0 + 0.01 * (k + 0.5) - 225.805 if k < 80 else 0.0 for k in range(200)]
        np.testing.assert_allclose(rise, expected, rtol=0.0, atol=TOL)
        profile = c.outcome.profile
        np.testing.assert_allclose(profile.rise_m, expected, rtol=0.0, atol=TOL)
        self.assertEqual((profile.counter_sections, profile.worst), (80, 79))
        close(self, float(profile.rise_m[79]), 4.99, absolute_m=TOL)
        close(self, float(profile.chainage_m[79]), 79.5, absolute_m=TOL)
        x, y = absolute(179.5, 219.5)
        close(self, float(profile.x[79]), x, absolute_m=TOL)
        close(self, float(profile.y[79]), y, absolute_m=TOL)

    def test_it_is_warned_and_not_creatable_without_confirmation(self) -> None:
        """RF-015-23: aviso de 4,99 m en la abscisa 79,5 y rechazo de crear sin confirmación; no hay
        relleno (el hueco queda 5 m por debajo, sin lomo) y el área por debajo se avisa."""
        c = self.calc
        warned = notice(c, "des.platform_counter_slope")
        self.assertEqual((warned["amount"], warned["chainage"]), (4.99, 79.5))
        self.assertTrue(c.outcome.needs_confirmation)
        with self.assertRaises(DesignError) as caught:
            c.outcome.ensure_creatable()
        self.assertEqual(caught.exception.code, "des.platform_counter_unconfirmed")
        self.assertIsNone(c.outcome.confirm().ensure_creatable())
        self.assertEqual(c.outcome.total_fill_m3, 0.0)
        close(self, c.applied.cut_m3, 38_400.0)
        group = notice(c, "des.platform_below_group")
        x, y = absolute(200.0, 200.0)
        self.assertAlmostEqual(float(group["x"]), x, places=2)  # type: ignore[arg-type]
        self.assertAlmostEqual(float(group["y"]), y, places=2)  # type: ignore[arg-type]


# --- CE-015-07: el borde sobre un plano inclinado, a mano ----------------------------------------


class Ce07Hand:
    """El cálculo a mano de CE-015-07 (véase el módulo): la cuña del borde de una plataforma plana a
    ``level`` de ``width`` m de ancho, de oeste a este de lado a lado de la rejilla (las filas de
    ``y = 180`` a ``y = 200``), sobre ``plane``, con el borde a ``angle`` y el alcance en celdas. Dos
    derivaciones de lo mismo: la suma celda a celda y la serie aritmética de cada columna."""

    LEVEL = 200.0
    BOTTOM, TOP = 180.0, 200.0
    REACH_M = 30.5
    REACH_CELLS = 30  # la última celda a ≤ 30,5 m de la semilla más próxima: k = 30

    def __init__(self, angle: float = EDGE_ANGLE) -> None:
        self.tan = math.tan(math.radians(angle))
        self.moved: list[float] = []
        self.wall = (0.0, 0.0, 0.0)  # corte, x, y de la celda
        self.steep: list[tuple[float, float, float]] = []  # tangente, x, y
        self.outside = 0
        self.series = 0.0
        self.created_max = (0.0, 0.0, 0.0)
        limit = math.tan(math.radians(LIMIT_DEG))
        for north in (True, False):
            for column in range(COLS):
                x = column + 0.5
                y_edge = self.TOP - 0.5 if north else self.BOTTOM + 0.5
                sign = 1.0 if north else -1.0
                last_k = 0
                for k in range(1, self.REACH_CELLS + 1):
                    y = y_edge + sign * k
                    moved = plane(x, y) - (self.LEVEL + self.tan * k)
                    if moved > 0.0:
                        self.moved.append(moved)
                        last_k = k
                        if column in (0, COLS - 1):
                            self.outside += 1
                        if moved > self.wall[0]:
                            self.wall = (moved, x, y)
                if last_k == self.REACH_CELLS:  # el alcance corta el desmonte: el borde acaba en seco
                    k = self.REACH_CELLS
                    envelope = self.LEVEL + self.tan * k
                    here, beyond = plane(x, y_edge + sign * k), plane(x, y_edge + sign * (k + 1))
                    if abs(beyond - envelope) > max(limit, 0.25):  # más que 41° y que el terreno
                        self.steep.append((abs(beyond - envelope), x, y_edge + sign * k))
                    created = abs(beyond - envelope) - abs(here - beyond)
                    if created > self.created_max[0]:
                        self.created_max = (created, x, y_edge + sign * (k + 0.5))
                # La serie aritmética de la columna: m(k) = A − s·k mientras es positivo.
                start = plane(x, y_edge) - self.LEVEL
                slope = self.tan - 0.25 if north else self.tan + 0.25
                cells = min(self.REACH_CELLS, math.ceil(start / slope) - 1)
                if cells > 0:
                    self.series += cells * start - slope * cells * (cells + 1) / 2.0

    @property
    def volume(self) -> float:
        return math.fsum(self.moved)

    @property
    def cells(self) -> int:
        return len(self.moved)


class PlaneEdgeCE07Test(unittest.TestCase):
    """CE-015-07 (RF-015-22, D-7, D-17, D-9): una plataforma plana a 200 m, «en corte», sobre el plano
    inclinado ``z = 180 + y/4 + x/16`` (de 20 m de ancho de oeste a este de lado a lado: 8.000 celdas),
    con el borde a 40° y 30,5 m de alcance. La cuña, a mano: véase el módulo."""

    AXIS = ((0.0, 190.0), (400.0, 190.0))

    @classmethod
    def setUpClass(cls) -> None:
        x, y = centres((slice(0, ROWS), slice(0, COLS)))
        cls.terrain = efx.plane_terrain()
        np.testing.assert_array_equal(cls.terrain, plane(x, y))  # el terreno de la fixture es el plano
        cls.calc = calculate(line_job(cls.terrain, cls.AXIS, width=20.0, start=200.0, gradient=0.0,
                                      reach=Ce07Hand.REACH_M))
        cls.hand = Ce07Hand()

    def test_the_two_hand_derivations_agree(self) -> None:
        """La suma celda a celda y la serie aritmética por columna (``K·A − s·K(K+1)/2``) dan lo mismo:
        la cuña es consistente antes de compararla con el código."""
        hand = self.hand
        close(self, hand.series, hand.volume, relative=1e-12)
        self.assertGreater(hand.cells, 20_000)

    def test_the_footprint_is_cut_to_the_platform_level(self) -> None:
        """RF-015-20: las 8.000 celdas de la huella bajan a 200 m (0 % de pendiente): 40 m de media
        (``180 + 47,5 + 12,5 − 200``), 320.000 m³ exactos; ninguna sube."""
        c = self.calc
        self.assertEqual(c.footprint.cell_count, 8_000)
        self.assertEqual(c.applied.cut_cells, 8_000)
        close(self, c.applied.cut_m3, 40.0 * 8_000.0)
        footprint = c.footprint.cells
        self.assertTrue((c.result[footprint] == 200.0).all())
        self.assertEqual(c.applied.fill_m3, 0.0)

    def test_the_edge_volume_is_the_wedge_by_hand(self) -> None:
        """RF-015-22: el volumen del borde, ``Σ m(k)`` sobre las celdas de la cuña (23.521 celdas),
        igual al cálculo a mano a ≤ 10⁻⁹ relativo; y su cifra ``des.edge_cut_m3``; el borde no rellena."""
        c, hand = self.calc, self.hand
        close(self, c.edge.cut_m3, hand.volume)
        close(self, figures(c)["des.edge_cut_m3"], hand.volume)
        self.assertEqual(c.edge.cut_cells, hand.cells)
        self.assertEqual(c.edge.cut_cells, c.edge.changed_cells)
        self.assertEqual((c.edge.fill_m3, c.edge.fill_cells), (0.0, 0))
        close(self, c.outcome.total_cut_m3, 320_000.0 + hand.volume)

    def test_the_wall_height_is_the_largest_cut_of_the_edge(self) -> None:
        """RF-015-22: la altura máxima de la pared es el mayor ``m(k)``: la celda pegada a la huella
        (k = 1) por el norte en la última columna, ``54,84375 − (tan 40° − 1/4)``, a ≤ 10⁻⁹ relativo; su
        lugar, (399,5; 200,5) local."""
        c = self.calc
        height, x, y = self.hand.wall
        close(self, height, 54.84375 - (math.tan(math.radians(EDGE_ANGLE)) - 0.25))
        close(self, c.edge.wall_max_m, height)
        close(self, figures(c)["des.edge_wall_max_m"], height)
        place = absolute(x, y)
        self.assertEqual((x, y), (399.5, 200.5))
        close(self, c.edge.wall_x, place[0], absolute_m=TOL)
        close(self, c.edge.wall_y, place[1], absolute_m=TOL)

    def test_the_cut_walls_are_only_at_the_reach_limit(self) -> None:
        """RF-015-22 (error 8): la única pared más empinada que 41° (y que el terreno) del borde es la
        de las celdas del límite del alcance (k = 30) en las que el alcance corta el desmonte, con la
        caída a la celda de al lado, ``|z(31) − envolvente(30)|``, de más de ``tan 41°``: son
        661 celdas, todas de causa ``reach``, y la peor, 88,47°, en (399,5; 229,5), a mano."""
        c, hand = self.calc, self.hand
        self.assertEqual(c.edge.steep_cells, len(hand.steep))
        self.assertEqual(len(hand.steep), 661)
        self.assertEqual([(wall.cause, wall.cells) for wall in c.edge.walls],
                         [(platform.WallCause.REACH, len(hand.steep))])
        worst, x, y = max(hand.steep)
        wall = c.edge.walls[0]
        close(self, wall.max_deg, math.degrees(math.atan(worst)))
        place = absolute(x, y)
        self.assertEqual((x, y), (399.5, 229.5))
        close(self, wall.x, place[0], absolute_m=TOL)
        close(self, wall.y, place[1], absolute_m=TOL)
        # Todas las demás celdas que el borde mueve quedan a 41° o menos (o como el terreno).
        z0 = c.z0
        surface = c.result
        steep = steep_by_hand(z0, surface, c.edge.changed)
        np.testing.assert_array_equal(steep, c.edge.steep)
        near = (~c.edge.in_reach) & ~c.footprint.cells
        self.assertTrue((~steep | dilate8(near)).all())
        notice_values = notice(c, "des.platform_edge_steep")
        self.assertEqual((notice_values["cells"], notice_values["at_reach"], notice_values["other"],
                          notice_values["at_masks"]), (661, 661, 0, 0))

    def test_the_created_step_at_the_limit_is_given(self) -> None:
        """RF-015-22, RF-015-13: donde el alcance corta el desmonte, el aviso da el salto creado
        (RF-014-21): el mayor es el corte de la celda del límite, ``m(30)`` (37,17 m), con el
        punto medio de la pareja en (399,5; 230) local, y el aviso está en la lista."""
        c = self.calc
        created = c.edge.created
        height, x, y = self.hand.created_max
        close(self, created.maximum_m, height)
        place = absolute(x, y)
        self.assertEqual((x, y), (399.5, 230.0))
        close(self, float(created.x), place[0], absolute_m=TOL)
        close(self, float(created.y), place[1], absolute_m=TOL)
        self.assertTrue(created.warned)
        warned = notice(c, "des.edge_surface_step")
        self.assertEqual(warned["maximum"], round(height, 2))
        self.assertEqual(warned["pairs"], created.pairs)

    def test_what_reaches_the_grid_border_is_warned(self) -> None:
        """RF-015-13: lo que el borde mueve en la primera y la última columna de la rejilla
        (``x = 0,5`` y ``399,5``) llega al borde de la rejilla y se avisa con su área y su lugar: las
        celdas de la cuña de esas dos columnas, a mano."""
        c, hand = self.calc, self.hand
        self.assertEqual(c.edge.outside_cells, hand.outside)
        outside = notice(c, "des.entity_edge_outside")
        self.assertEqual((outside["cells"], outside["area"]), (hand.outside, float(hand.outside)))

    def test_there_is_no_counterslope_on_a_flat_platform(self) -> None:
        """RF-015-23, D-16: una plataforma plana cortada del todo (todas sus secciones a 200 m) no
        tiene contrapendiente (máximo menos mínimo = 0)."""
        c = self.calc
        self.assertEqual(c.outcome.profile.spread_m, 0.0)
        self.assertEqual(c.outcome.profile.counter_sections, 0)
        self.assertTrue(c.outcome.profile.flat)
        self.assertFalse(c.outcome.needs_confirmation)


class WithoutReachCE07Test(unittest.TestCase):
    """CE-015-07 y RF-015-08 (D-20): sin alcance, el rechazo; no se elige uno por la persona."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.terrain = efx.plane_terrain()
        cls.axis = PlaneEdgeCE07Test.AXIS

    def job(self, **changes: object) -> Any:
        base = line_job(self.terrain, self.axis, width=20.0, start=200.0, gradient=0.0, reach=30.5)
        values = {key: value for key, value in {**base.values, **changes}.items()
                  if value is not None}
        return platform.PlatformJob(base.request, base.code, base.grid, base.start, base.geometry,
                                    values, base.cut_allowed, base.fill_allowed)

    def test_a_platform_without_reach_is_rejected_naming_entity_field_and_value(self) -> None:
        """RF-015-08: sin ``reach_m``, ``des.entity_param_missing`` con el campo
        ``des.platform.plt_001.reach_m``, el valor vacío y la plataforma, y no se elige ninguno por la
        persona (no se calcula nada). El mensaje de un **parámetro** (T02) nombra la entidad, el
        campo y el valor, y no la capa que RF-015-08 también cita: queda anotado en la
        verificación de T10."""
        with self.assertRaises(DesignError) as caught:
            platform.platform_footprint(self.job(reach_m=None))
        error = caught.exception
        self.assertEqual(error.code, "des.entity_param_missing")
        self.assertEqual(error.field, "des.platform.plt_001.reach_m")
        self.assertIsNone(error.value)
        self.assertEqual(error.values["entity"], "P1")
        self.assertIn("«P1»", error.text)
        self.assertIn("des.platform.plt_001.reach_m", error.text)

    def test_a_rejected_geometry_names_layer_entity_field_and_value(self) -> None:
        """RF-015-08: un eje cerrado (acaba donde empieza) se rechaza con ``des.platform_axis_closed``
        nombrando la capa, la plataforma, el campo (la geometría) y el valor (su longitud, 34,14 m)."""
        closed = ((10.0, 10.0), (20.0, 10.0), (20.0, 20.0), (10.0, 10.0))
        job = line_job(self.terrain, closed, width=5.0, start=200.0, gradient=0.0, reach=12.5)
        with self.assertRaises(DesignError) as caught:
            platform.platform_footprint(job)
        error = caught.exception
        self.assertEqual(error.code, "des.platform_axis_closed")
        self.assertEqual((error.values["layer"], error.values["entity"], error.field),
                         (efx.AXES_LAYER, "P1", "geometría"))
        self.assertAlmostEqual(float(error.values["value"]), 10.0 + 10.0 + math.hypot(10.0, 10.0),  # type: ignore[arg-type]
                               places=9)
        self.assertIn(efx.AXES_LAYER, error.text)

    def test_an_edge_without_reach_is_rejected_too(self) -> None:
        """RF-015-08: el borde de una huella calculada con alcance rechaza el trabajo sin él
        (``des.entity_param_missing``) y un alcance de 0 o de más de 10.000 m es
        ``des.entity_param_range`` con su valor."""
        good = self.job()
        footprint = platform.platform_footprint(good)
        applied = platform.apply_platform(good, footprint)
        with self.assertRaises(DesignError) as caught:
            platform.platform_edge(self.job(reach_m=None), footprint, applied, PROJECT)
        self.assertEqual(caught.exception.code, "des.entity_param_missing")
        for value in (0.0, 10_000.5):
            with self.subTest(reach=value), self.assertRaises(DesignError) as caught:
                platform.platform_edge(self.job(reach_m=value), footprint, applied, PROJECT)
            self.assertEqual(caught.exception.code, "des.entity_param_range")
            self.assertEqual(caught.exception.value, value)

    def test_the_other_required_values_are_rejected_not_chosen(self) -> None:
        """RF-015-08: sin ancho, sin cota inicial o sin pendiente se rechaza nombrando el campo, no se
        elige un valor."""
        for key in ("width_m", "start_level_m", "gradient_pct"):
            with self.subTest(field=key), self.assertRaises(DesignError) as caught:
                platform.platform_footprint(self.job(**{key: None}))
            self.assertEqual(caught.exception.code, "des.entity_param_missing")
            self.assertEqual(caught.exception.field, f"des.platform.plt_001.{key}")


# --- E1: la plataforma de la planta, 200 m, 20 m, 175 m y 1 % con su borde ---------------------------


class ScenarioE1Test(unittest.TestCase):
    """E1 (spec §2) recorrido en el dominio, sin Blender: la plataforma de la planta, eje de 200 m,
    20 m de ancho, cota 175 m y 1 %, con su borde, sobre el terreno inclinado. Las cifras de RF-015-24
    a mano; el borde, contra una fuerza bruta de la envolvente a 40° (alcance de 60,5 m) sobre los
    bordes de la huella."""

    AXIS = ((100.0, 100.0), (300.0, 100.0))

    @classmethod
    def setUpClass(cls) -> None:
        cls.terrain = efx.plane_terrain()
        cls.calc = calculate(line_job(cls.terrain, cls.AXIS, width=20.0, start=175.0, gradient=1.0,
                                      reach=60.5))
        c = cls.calc
        x, _y = centres(c.window)
        cls.grade = np.where(c.footprint.cells, np.vectorize(
            lambda value: hand_grade(float(value), 100.0, 175.0, 1.0))(x), np.nan)
        cls.hand = hand_edge(c.z0, c.footprint.cells, cls.grade, c.cut_ok, 60.5)

    def test_the_figures_of_the_footprint(self) -> None:
        """RF-015-24: área 4.000 m², eje de 200 m, huella de 199 m, cotas de la rasante en los extremos
        175 y 177 m y un corte de la huella de 166.000 m³ (``Σ(z − rasante)`` con el terreno a 217,5 m de
        media y la rasante a 176 m: 4.000 · 41,5); sin relleno ni nada por encima o por debajo."""
        c = self.calc
        values = figures(c)
        self.assertEqual(values["des.plat_area_m2"], 4_000.0)
        close(self, values["des.plat_axis_m"] or 0.0, 200.0, absolute_m=TOL)
        close(self, values["des.plat_footprint_m"] or 0.0, 199.0, absolute_m=TOL)
        close(self, values["des.plat_start_level_m"] or 0.0, 175.0, absolute_m=TOL)
        close(self, values["des.plat_end_level_m"] or 0.0, 177.0, absolute_m=TOL)
        close(self, values["des.plat_cut_m3"] or 0.0, 166_000.0)
        self.assertEqual(values["des.plat_fill_m3"], 0.0)
        self.assertEqual(values["des.plat_below_m2"], 0.0)
        self.assertNotIn("des.plat_below_max_m", values)
        self.assertEqual((c.applied.above, c.applied.below), ((), ()))
        self.assertFalse(c.outcome.no_cut)

    def test_the_edge_is_the_brute_force_envelope(self) -> None:
        """RF-015-22: la superficie con el borde (``z' = mín(z, 175 + 0,01 σ_q + tan 40° · d)`` sobre las
        semillas del borde de la huella, hasta 60,5 m de ella) es la de la fuerza bruta a ≤ 10⁻⁹ m, y
        el volumen, la altura de la pared y las celdas, a ≤ 10⁻⁹ relativo."""
        c, hand = self.calc, self.hand
        self.assertLessEqual(float(np.abs(c.result - hand.surface).max()), TOL)
        close(self, c.edge.cut_m3, hand.volume)
        close(self, figures(c)["des.edge_cut_m3"], hand.volume)
        close(self, c.edge.wall_max_m, hand.wall)
        self.assertEqual(c.edge.cut_cells, int(hand.changed.sum()))
        self.assertGreater(hand.volume, 100_000.0)
        self.assertEqual(c.edge.fill_m3, 0.0)

    def test_the_profile_goes_down_to_the_start_and_it_can_be_created(self) -> None:
        """RF-015-23: el perfil (la rasante, ``175 + 0,01 σ``) baja hacia la abscisa 0: ninguna
        contrapendiente, ningún aviso de ella y se puede crear sin confirmar."""
        c = self.calc
        levels = column_profile(c.result, c.footprint.cells)
        self.assertEqual(max(counter_rise(levels, 1.0)), 0.0)
        close(self, levels[0], 175.005, absolute_m=TOL)
        close(self, levels[-1], 176.995, absolute_m=TOL)
        self.assertFalse(c.outcome.needs_confirmation)
        self.assertIsNone(c.outcome.ensure_creatable())
        self.assertFalse([item for item in codes(c) if "counter" in item])


# --- E2: «en corte» en una ladera con el terreno por debajo de la rasante en parte -------------------


class ScenarioE2Test(unittest.TestCase):
    """E2 (spec §2) recorrido en el dominio, sin Blender: una plataforma «en corte» en una ladera (el
    plano ``180 + y/4 + x/16``) cuyo terreno queda en parte **por debajo de la rasante**. El eje de
    (200, 20) a (200, 120) (hacia el norte, 100 m), 20 m de ancho, cota inicial 200 m y + 1 %: el
    terreno sube 0,25 m por metro y la rasante 0,01, así que al sur del eje (``y ≲ 30``) el terreno queda
    por debajo (la parte baja, aguas abajo) y al norte por encima. Sin lomo y con el aviso de lo que no
    llega; todo a mano, en racionales."""

    AXIS = ((200.0, 20.0), (200.0, 120.0))

    @classmethod
    def setUpClass(cls) -> None:
        cls.terrain = efx.plane_terrain()
        cls.calc = calculate(line_job(cls.terrain, cls.AXIS, width=20.0, start=200.0, gradient=1.0,
                                      reach=12.5))
        c = cls.calc
        window = c.window
        cls.hand_cells, cls.hand_t = hand_corridor(((200, 20), (200, 120)), 20, window)
        x, y = centres(window)
        # La diferencia terreno − rasante de cada celda de la huella, exacta (racionales).
        cls.gap = np.full(x.shape, np.nan)
        for row, col in zip(*np.nonzero(cls.hand_cells), strict=True):
            ground = Fraction(180) + Fraction(round(2 * y[row, col]), 2) / 4 \
                + Fraction(round(2 * x[row, col]), 2) / 16
            grade = Fraction(200) + (Fraction(round(2 * y[row, col]), 2) - 20) / 100
            cls.gap[row, col] = float(ground - grade)

    def test_the_hand_footprint_is_2000_cells_with_a_clear_split(self) -> None:
        """La cuenta a mano: 20 × 100 = 2.000 celdas, sin ninguna a ≤ 10⁻⁶ m de la rasante (sin
        empates), una parte por debajo de la rasante y el resto por encima: la ladera cruza la rasante."""
        gap = self.gap[self.hand_cells]
        self.assertEqual(int(self.hand_cells.sum()), 2_000)
        self.assertGreater(float(np.abs(gap).min()), 1e-6)
        self.assertTrue((gap < 0).any() and (gap > 0).any())
        np.testing.assert_array_equal(self.calc.footprint.cells, self.hand_cells)

    def test_no_ridge_the_low_part_is_left_as_it_was(self) -> None:
        """RF-015-20, B7: no sube nada (0 m³ de relleno, ``z' ≤ z`` en toda la ventana) y las celdas
        por debajo de la rasante quedan **iguales, bit a bit**, a la ladera: no se rellenan a ella."""
        c = self.calc
        below = self.hand_cells & (self.gap < 0)
        self.assertEqual(float(np.maximum(c.result - c.z0, 0.0).sum()), 0.0)
        self.assertEqual((c.applied.fill_m3, c.edge.fill_m3, c.outcome.total_fill_m3),
                         (0.0, 0.0, 0.0))
        np.testing.assert_array_equal(c.result[below], c.z0[below])

    def test_the_cut_and_the_notice_of_what_does_not_reach_are_by_hand(self) -> None:
        """RF-015-24, RF-015-13: el corte de la huella es ``Σ (z − rasante)`` de las celdas por encima
        (en racionales) y lo que no llega, un grupo (la ladera por debajo de la rasante, conexa) con
        su área (el número de celdas), la diferencia máxima (la mayor ``rasante − z``) y su lugar (el
        centro de sus celdas), todo a ≤ 10⁻⁹ relativo; las cifras ``des.plat_below_*``."""
        c = self.calc
        above = self.hand_cells & (self.gap > 0)
        below = self.hand_cells & (self.gap < 0)
        close(self, c.applied.cut_m3, math.fsum(self.gap[above].tolist()))
        close(self, figures(c)["des.plat_cut_m3"], math.fsum(self.gap[above].tolist()))
        self.assertEqual(c.applied.cut_cells, int(above.sum()))
        summary = notice(c, "des.platform_below")
        self.assertEqual(summary["groups"], 1)
        close(self, float(summary["area"]), float(below.sum()))  # type: ignore[arg-type]
        self.assertAlmostEqual(float(summary["maximum"]), float((-self.gap[below]).max()),  # type: ignore[arg-type]
                               delta=0.0005 + TOL)  # el aviso redondea al mm
        close(self, figures(c)["des.plat_below_m2"] or 0.0, float(below.sum()))
        close(self, figures(c)["des.plat_below_max_m"] or 0.0, float((-self.gap[below]).max()))
        x, y = centres(c.window)
        centre = absolute(float(x[below].mean()), float(y[below].mean()))
        group = notice(c, "des.platform_below_group")
        self.assertEqual(group["cells"], int(below.sum()))
        self.assertAlmostEqual(float(group["x"]), centre[0], places=2)  # type: ignore[arg-type]
        self.assertAlmostEqual(float(group["y"]), centre[1], places=2)  # type: ignore[arg-type]
        self.assertEqual(c.applied.below[0].cause, platform.OffLevelCause.NOT_FILLED)
        self.assertEqual(c.applied.above, ())

    def test_the_cut_cells_are_at_the_grade(self) -> None:
        """RF-015-19, RF-015-20: la parte cortada queda a la rasante, ``200 + (y − 20) · 0,01``, a
        ≤ 10⁻⁹ m (en racionales)."""
        c = self.calc
        above = self.hand_cells & (self.gap > 0)
        by_hand = c.z0 - self.gap  # terreno − (terreno − rasante) = rasante, sin la huella de fuera
        self.assertLessEqual(float(np.abs(c.result - by_hand)[above].max()), TOL)

    def test_there_is_no_counterslope_going_down_the_slope(self) -> None:
        """RF-015-23: con la ladera bajando más que la rasante hacia el sur, el perfil (la cota más
        alta de cada fila) solo baja hacia la abscisa 0: ninguna contrapendiente y se puede crear."""
        c = self.calc
        levels = row_profile(c.result, c.footprint.cells)
        self.assertEqual(len(levels), 100)
        self.assertEqual(max(counter_rise(levels, 1.0)), 0.0)
        self.assertFalse(c.outcome.needs_confirmation)
        self.assertEqual(c.outcome.profile.counter_sections, 0)
        np.testing.assert_allclose(c.outcome.profile.level_m, levels, rtol=0.0, atol=TOL)


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: GPL-3.0-or-later
"""Retirar un acopio «como plataforma» (spec 016, T21; HU-016-2; RF-016-16, RF-015-19 a RF-015-24, RF-016-13, D-5; plan 016 §5.4
A9, §5.7 P-3, §5.8 H-5): **una plataforma de la 015 con la huella del acopio como geometría**, no otro cálculo del borde.

El acopio sintético de las cuentas a mano (80 × 80 m de celdas de 2 m, **plano de base de 3,76 %** como el del acopio 7 de la V10) es un
rectángulo de 20 × 16 celdas con alturas conocidas sobre su base; el terreno de fuera, un banco de cinco metros por encima del plano. Cada
cifra se compara con el cálculo **hecho aparte, celda a celda** (``Hand*``: bucles de Python, no el código que se prueba) a ≤ 10⁻⁹ relativo:

- **El plano y el eje** (``platform_of_stockpile``): la cota inicial y la pendiente del plano, el eje **por su centro en la dirección de máxima
  pendiente, de borde a borde de la huella** (las esquinas de todas sus celdas), las celdas de la huella (las mismas que la geometría) y su
  longitud; y **la huella entera en el plano** (la rasante de cada celda es el plano).
- **El borde y las cifras de la plataforma** (RF-015-19 a 24): el corte de la huella, el del borde por fuerza bruta (``mín_q [cota_q + t · d]``
  de todas las semillas) y las doce cifras de la plataforma, iguales con y sin lo de la retirada (la plataforma de una capa no cambia).
- **Las cifras de una retirada** (RF-016-13): lo retirado del acopio, lo que se le apoyaba y lo que las máscaras no dejan cortar, que suman lo que
  había sobre la base; con 0 m³, el aviso.
- **Los rechazos y los avisos**: una base propia que no es un plano, la pendiente que pasa de la máxima (una rampa), el borde sin ángulo ni
  alcance, proteger en «corte y relleno», y lo que las máscaras no dejan cortar (con su aviso).
- **El modelo**: el eje dado de la geometría (su hash, su ventana de lectura y lo que no admite) y la petición de la retirada.
"""

from __future__ import annotations

import dataclasses
import math
import unittest
from typing import Any

import numpy as np

from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender

entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")
params = import_geoblender("design.params")
platform = import_geoblender("design.platform")
provenance = import_geoblender("design.provenance")
removal = import_geoblender("design.removal")

DesignError = messages.DesignError
STEP = 2.0
AREA = STEP * STEP
N = 40
GRID = sdata.window_grid(STEP, STEP * N)
SOUTH = GRID.north - N * STEP
"""La y absoluta del borde sur de la rejilla (las locales de ``stockpile_data`` parten de ahí)."""
SLOPE = 0.0376
"""La pendiente del plano de base (m/m): 3,76 %, como la del acopio 7 de la V10."""
PLANE = sdata.plane(math.degrees(math.atan(SLOPE)), pivot=(40.0, 40.0), z_pivot=187.0)
ROWS, COLS = (12, 28), (10, 30)
"""Las filas y las columnas de la huella rectangular: 16 × 20 celdas (32 × 40 m)."""
BANK_M = 5.0
"""Lo que el terreno de fuera de la huella sube sobre el plano (m): un banco más alto que el talud del borde a su alcance."""
ANGLE, REACH = 45.0, 5.0
"""El ángulo de borde y el alcance de la plataforma (datos de ENTRADA: D-7 y D-20, sin valor por defecto)."""
TAN = math.tan(math.radians(ANGLE))
CODE = "PLT-001"
COMMON = {params.TOLERANCE_FACE: 1.0, params.WARNING_RATIO: 2.0, params.VERIFY_MIN_THICKNESS: 0.02,
          params.EDGE_MAX_STEP: 1.0, params.EDGE_MIN_SHARE: 99.0}
"""Los parámetros del proyecto que lee el cálculo (valores de la prueba, no de un proyecto)."""


# --- Lo que construyen las pruebas ---------------------------------------------------------------------------------------


def rectangle(rows: tuple[int, int] = ROWS, cols: tuple[int, int] = COLS) -> np.ndarray:
    """La huella: las celdas de las filas ``rows`` y las columnas ``cols`` (``[a, b)``)."""
    found = np.zeros((N, N), dtype=bool)
    found[rows[0]:rows[1], cols[0]:cols[1]] = True
    return found


def thickness_of(footprint: np.ndarray) -> np.ndarray:
    """Lo que el acopio sobresale de su base (m): de 1,00 a 2,75 m con un reparto fijo (``1 + 0,25·((3·fila + 5·columna) mod 8)``)."""
    rows, cols = np.indices((N, N))
    return np.where(footprint, 1.0 + 0.25 * ((3 * rows + 5 * cols) % 8), 0.0)


@dataclasses.dataclass(slots=True)
class Scene:
    """Lo leído de un acopio retirado: la ``footprint``, la ``base`` (el plano), lo que sobresale (``thickness``), la superficie de
    partida (``z``: la base más el acopio dentro de la huella y el banco fuera) y la de detección (``detected``)."""

    footprint: np.ndarray
    base: np.ndarray
    thickness: np.ndarray
    z: np.ndarray
    detected: np.ndarray

    @property
    def item(self) -> Any:
        flat = np.flatnonzero(self.footprint)
        return removal.RemovedStockpile("m07", "Acopio 7", flat, self.base.reshape(-1)[flat], self.detected.reshape(-1)[flat])


def scene(footprint: np.ndarray | None = None, *, base: np.ndarray | None = None, resting: np.ndarray | None = None) -> Scene:
    """El acopio sobre su plano: ``resting`` es lo que **se apoyó después** (m): la superficie con que se detectó queda por debajo de la de
    partida en eso."""
    found = rectangle() if footprint is None else footprint
    plane = PLANE.values(GRID) if base is None else base
    thickness = thickness_of(found)
    z = np.where(found, plane + thickness, plane + BANK_M)
    later = np.zeros((N, N)) if resting is None else resting
    return Scene(found, plane, thickness, z, np.where(found, z - later, np.nan))


def asked(**changes: Any) -> Any:
    """La petición de retirar el acopio 7 «como plataforma»: con el borde de la prueba."""
    options: dict[str, Any] = {"edge_angle_deg": ANGLE, "reach_m": REACH, **changes}
    return model.PlatformRequest.of_stockpile("Retirada del acopio 7", "STK-001#m07", "terreno", **options)


def job_of(found: Scene, *, cut: np.ndarray | None = None, request: Any = None, **given: Any) -> tuple[Any, Any]:
    """El trabajo de la plataforma del acopio de ``found``: su plataforma (``platform_of_stockpile``) y el ``PlatformJob`` con la huella
    como geometría, los valores resueltos como los resuelve la preparación (``entity_values``) y las máscaras de ``cut``."""
    made = removal.platform_of_stockpile(found.item, GRID)
    wanted = asked(**given) if request is None else request
    values = entity_store.entity_values(
        wanted, CODE, 7, {params.PlatformParam.START_LEVEL: made.start_level_m, params.PlatformParam.GRADIENT: made.gradient_pct},
        line=False)
    allowed = np.ones((N, N), dtype=bool) if cut is None else cut
    return made, platform.PlatformJob(wanted, CODE, GRID, found.z, made.geometry, values, allowed, np.ones((N, N), dtype=bool))


def drained(work: Any) -> Any:
    """Lo que devuelve (``yield from``) un generador de pasos."""
    while True:
        try:
            next(work)
        except StopIteration as done:
            return done.value


def computed(found: Scene, **options: Any) -> tuple[Any, Any, Any]:
    """La plataforma, el trabajo y el resultado de retirar el acopio de ``found`` como plataforma (con lo de la retirada)."""
    made, job = job_of(found, **options)
    return made, job, drained(entity_store.platform_compute_steps(job, COMMON, removed=found.item))


# --- Lo hecho a mano ----------------------------------------------------------------------------------------------------


def relative(value: float, wanted: float) -> float:
    return abs(value - wanted) / abs(wanted)


def hand_axis(footprint: np.ndarray) -> tuple[float, float, float, float, float, float]:
    """A mano: el centro de la huella (la media de los centros de sus celdas, locales desde el suroeste), la dirección de máxima pendiente
    del plano (``(sen az, cos az)``) y la menor y la mayor proyección **de las esquinas de todas sus celdas** sobre ella (m desde el
    centro): ``(xc, yc, ux, uy, t_min, t_max)``."""
    ux, uy = PLANE.east_slope, PLANE.north_slope
    norm = math.hypot(ux, uy)
    ux, uy = ux / norm, uy / norm
    cells = [(row, col) for row in range(N) for col in range(N) if footprint[row, col]]
    xs = [(col + 0.5) * STEP for _row, col in cells]
    ys = [(N - row - 0.5) * STEP for row, _col in cells]
    xc, yc = math.fsum(xs) / len(cells), math.fsum(ys) / len(cells)
    projections = [(corner_x - xc) * ux + (corner_y - yc) * uy
                   for (row, col) in cells for corner_x in (col * STEP, (col + 1) * STEP)
                   for corner_y in ((N - row - 1) * STEP, (N - row) * STEP)]
    return xc, yc, ux, uy, min(projections), max(projections)


def hand_edge(z: np.ndarray, levels: np.ndarray, seeds: np.ndarray, *, tan: float, reach: float,
              allowed: np.ndarray | None = None) -> tuple[float, int, np.ndarray]:
    """A mano: el borde de la plataforma: de cada celda de **fuera** de la huella a ≤ ``reach`` de alguna semilla, ``z' = mín(z, mín_q [cota_q + tan ·
    d(p, q)])`` con ``q`` todas las semillas (fuerza bruta), donde el corte se admite. Devuelve el corte (m³), las celdas que baja y la superficie."""
    seed_rows, seed_cols = np.nonzero(seeds)
    seed_levels = levels[seeds]
    surface = z.copy()
    total, count = 0.0, 0
    for row in range(N):
        for col in range(N):
            if seeds[row, col] or (allowed is not None and not allowed[row, col]):
                continue
            distance = STEP * np.hypot(seed_rows - row, seed_cols - col)
            if float(distance.min()) > reach:
                continue
            envelope = float((seed_levels + tan * distance).min())
            if z[row, col] > envelope:
                total += float(z[row, col]) - envelope
                count += 1
                surface[row, col] = envelope
    return total * AREA, count, surface


# --- El plano, el eje y la rasante --------------------------------------------------------------------------------------


class PlaneAndAxisTest(unittest.TestCase):
    """RF-016-16, RF-015-19, A9: el plano de la base, el eje de borde a borde y la rasante (la huella entera en el plano)."""

    def test_the_plane_the_axis_and_the_cells_of_the_footprint_are_the_ones_done_by_hand(self) -> None:
        """RF-016-16: la cota inicial y la pendiente de la rasante son las del plano de la base (3,76 %), el eje pasa por el centro de la huella
        con la dirección de máxima pendiente y va de la menor a la mayor proyección de las esquinas de sus celdas (de borde a borde), y la
        geometría es el contorno de las mismas celdas; todo a ≤ 10⁻⁹ relativo de lo hecho aparte."""
        found = scene()
        made = removal.platform_of_stockpile(found.item, GRID)
        xc, yc, ux, uy, low, high = hand_axis(found.footprint)
        start = (GRID.west + xc + low * ux, SOUTH + yc + low * uy)
        end = (GRID.west + xc + high * ux, SOUTH + yc + high * uy)
        for found_point, wanted in zip(made.axis.vertices, (start, end), strict=True):
            self.assertLessEqual(max(abs(found_point[0] - wanted[0]), abs(found_point[1] - wanted[1])), 1e-9)
        self.assertLessEqual(relative(made.axis.length_m, high - low), 1e-9)
        self.assertEqual(made.axis.principal, False, "el eje es el dado, no el principal")
        level = float(PLANE.at(xc + low * ux, yc + low * uy))
        self.assertLessEqual(relative(made.start_level_m, level), 1e-9)
        self.assertLessEqual(relative(made.gradient_pct, 100.0 * SLOPE), 1e-9)
        self.assertLessEqual(relative(made.gradient_pct, 3.76), 1e-9)
        self.assertLessEqual(abs(made.azimuth_deg - sdata.AZIMUTH_DEG), 1e-9)
        self.assertLessEqual(relative(made.centre_level_m, float(PLANE.at(xc, yc))), 1e-9)
        self.assertEqual((made.cells, made.area_m2, made.key, made.name), (320, 320 * AREA, "m07", "Acopio 7"))
        self.assertLessEqual(made.residual_m, 1e-9, "la base es un plano")
        self.assertEqual(made.geometry.kind, "polygon")
        self.assertIs(made.geometry.given_axis, made.axis)
        self.assertEqual(sum(len(rings) for rings in made.geometry.parts), 1, "un contorno, sin huecos")

    def test_the_whole_footprint_is_left_in_the_plane_and_the_footprint_is_the_one_of_the_stockpile(self) -> None:
        """RF-016-16, RF-015-20 (A9: ``z' = plano`` en toda la huella): la huella de la plataforma son **las mismas celdas** del acopio, su
        rasante es el plano de la base en cada una de ellas (a ≤ 10⁻⁹ m: la abscisa es la de la proyección, sin recortar) y la superficie
        que deja es el plano; la longitud de la huella, la de las celdas por su eje."""
        found = scene()
        made, job, outcome = computed(found)
        window = outcome.footprint.window
        flat = np.flatnonzero(found.footprint)
        rows, cols = np.nonzero(outcome.footprint.cells)
        np.testing.assert_array_equal((rows + window[0].start) * N + cols + window[1].start, flat)
        plane = found.base[found.footprint]
        self.assertLessEqual(float(np.max(np.abs(outcome.footprint.levels[outcome.footprint.cells] - plane))), 1e-9)
        self.assertLessEqual(float(np.max(np.abs(outcome.result[outcome.footprint.cells] - plane))), 1e-9, "la huella, en el plano")
        xc, yc, ux, uy, low, high = hand_axis(found.footprint)
        centres = [(((col + 0.5) * STEP - xc) * ux + ((N - row - 0.5) * STEP - yc) * uy)
                   for row, col in zip(*np.nonzero(found.footprint), strict=True)]
        self.assertLessEqual(relative(outcome.footprint.length_m, max(centres) - min(centres)), 1e-9)
        self.assertLessEqual(relative(outcome.footprint.end_level_m, float(PLANE.at(xc + high * ux, yc + high * uy))), 1e-9)
        self.assertLessEqual(relative(outcome.footprint.start_level_m, made.start_level_m), 1e-12)

    def test_a_flat_base_gives_an_east_west_axis_and_no_gradient(self) -> None:
        """RF-016-16, RF-015-19 (D-16: la pendiente 0 % se admite): sin pendiente no hay máxima pendiente: el eje es este-oeste, de borde a
        borde (la anchura de la huella) y la rasante, la cota del plano."""
        flat = np.full((N, N), 187.0)
        found = scene(base=flat)
        made, _job, outcome = computed(found)
        self.assertEqual(made.gradient_pct, 0.0)
        self.assertLessEqual(relative(made.start_level_m, 187.0), 1e-12)
        (x0, y0), (x1, y1) = made.axis.vertices
        self.assertLessEqual(abs(y0 - y1), 1e-9)
        self.assertLessEqual(relative(x1 - x0, 20 * STEP), 1e-9)
        self.assertLessEqual(float(np.max(np.abs(outcome.result[outcome.footprint.cells] - 187.0))), 1e-12)

    def test_a_footprint_with_a_hole_and_a_notch_keeps_its_cells_and_leaves_the_hole_alone(self) -> None:
        """RF-016-16 (H-5: la regla de la celda devuelve el contorno a las mismas celdas): con una muesca en una esquina y un hueco dentro, la
        huella de la plataforma son exactamente las celdas del acopio y las del hueco, que no son suyas, no se tocan (son terreno)."""
        shape = rectangle()
        shape[ROWS[0]:ROWS[0] + 3, COLS[0]:COLS[0] + 4] = False  # la muesca
        shape[19:22, 17:20] = False  # el hueco
        found = scene(shape)
        made, _job, outcome = computed(found)
        self.assertEqual(made.cells, int(shape.sum()))
        self.assertGreaterEqual(sum(len(rings) for rings in made.geometry.parts), 2, "el contorno tiene el hueco")
        window = outcome.footprint.window
        local = outcome.footprint.cells
        whole = np.zeros((N, N), dtype=bool)
        whole[window][local] = True
        np.testing.assert_array_equal(whole, shape)
        hole = outcome.result[19 - window[0].start:22 - window[0].start, 17 - window[1].start:20 - window[1].start]
        # la envolvente del borde rodea el hueco: nunca sube, y a ≤ alcance de la huella baja a la del terreno o menos
        self.assertTrue(np.all(hole <= found.z[19:22, 17:20] + 1e-12))
        self.assertLessEqual(float(np.max(np.abs(outcome.result[local] - found.base[shape]))), 1e-9)

    def test_a_base_of_its_own_is_not_a_plane_and_a_plane_with_noise_still_is(self) -> None:
        """RF-016-16, RF-016-03, D-11 (plano de base ≤ 10⁻⁶ m): con una base propia (una superficie, no un plano) se rechaza **nombrando el
        acopio y lo que se separa del mejor plano** (``des.removal_platform_no_plane``), sin calcular nada; con un ruido de 10⁻⁹ m,
        sigue siendo el plano."""
        bumped = PLANE.values(GRID).copy()
        bumped[16, 20] += 0.25
        with self.assertRaises(DesignError) as caught:
            removal.platform_of_stockpile(scene(base=bumped).item, GRID)
        error = caught.exception
        self.assertEqual(error.code, "des.removal_platform_no_plane")
        self.assertIn("Acopio 7", error.text)
        self.assertIn("0,2", error.text)
        self.assertNotIn("{", error.text_in("en"))
        self.assertGreater(error.values["residual"], 0.1)
        noisy = PLANE.values(GRID) + np.random.default_rng(7).uniform(-1e-9, 1e-9, (N, N))
        found = removal.platform_of_stockpile(scene(base=noisy).item, GRID)
        self.assertLessEqual(relative(found.gradient_pct, 100.0 * SLOPE), 1e-6)
        self.assertLessEqual(found.residual_m, removal.PLANE_TOLERANCE_M)


# --- El borde, las comprobaciones y las cifras --------------------------------------------------------------------------


class EdgeAndFiguresTest(unittest.TestCase):
    """RF-016-16, RF-015-20 a 24, RF-016-13: el borde de la plataforma, sus cifras y las de la retirada."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.found = scene()
        cls.made, cls.job, cls.outcome = computed(cls.found)

    def test_the_cut_of_the_footprint_and_of_the_edge_are_the_ones_done_by_hand(self) -> None:
        """RF-015-20, RF-015-22 (A2, A3): el corte de la huella es ``Σ espesor · área`` (la huella baja entera al plano) y el del borde, el de la
        envolvente ``mín_q [cota_q + tan α · d]`` de todas las semillas hasta el alcance, por fuerza bruta; sin relleno (el modo «en corte»)."""
        applied, edge = self.outcome.applied, self.outcome.edge
        self.assertLessEqual(relative(applied.cut_m3, math.fsum(self.found.thickness.ravel().tolist()) * AREA), 1e-9)
        self.assertEqual((applied.fill_m3, applied.blocked_cells, applied.above, applied.below), (0.0, 0, (), ()))
        wanted, cells, surface = hand_edge(self.found.z, self.found.base, self.found.footprint, tan=TAN, reach=REACH)
        self.assertGreater(cells, 100, "el banco da un talud de verdad")
        self.assertLessEqual(relative(edge.cut_m3, wanted), 1e-9)
        self.assertEqual((edge.cut_cells, edge.fill_m3), (cells, 0.0))
        window = self.outcome.footprint.window
        surface[self.found.footprint] = self.found.base[self.found.footprint]
        self.assertLessEqual(float(np.max(np.abs(self.outcome.result - surface[window]))), 1e-9, "toda la superficie, celda a celda")
        untouched = np.ones((N, N), dtype=bool)
        untouched[window] = False
        np.testing.assert_array_equal(surface[untouched], self.found.z[untouched])

    def test_the_twelve_figures_of_the_platform_and_the_figures_of_a_removal_by_hand(self) -> None:
        """RF-015-24, RF-016-16, RF-016-13: las cifras de la plataforma (el área, el eje, las cotas de la rasante en sus extremos, el corte y
        el relleno de la huella y del borde) y las de una retirada —retirado = ``Σ espesor · área``, sin apoyado, sin transición ni no
        retirado—, que suman lo que había sobre la base."""
        figures = {item.key: item.value for item in self.outcome.figures}
        xc, yc, ux, uy, low, high = hand_axis(self.found.footprint)
        thickness = math.fsum(self.found.thickness.ravel().tolist()) * AREA
        self.assertLessEqual(relative(figures["des.plat_area_m2"], 320 * AREA), 1e-9)
        self.assertLessEqual(relative(figures["des.plat_axis_m"], high - low), 1e-9)
        self.assertLessEqual(relative(figures["des.plat_start_level_m"], float(PLANE.at(xc + low * ux, yc + low * uy))), 1e-9)
        self.assertLessEqual(relative(figures["des.plat_end_level_m"], float(PLANE.at(xc + high * ux, yc + high * uy))), 1e-9)
        self.assertLessEqual(relative(figures["des.plat_cut_m3"], thickness), 1e-9)
        self.assertLessEqual(relative(figures["des.edge_cut_m3"], hand_edge(
            self.found.z, self.found.base, self.found.footprint, tan=TAN, reach=REACH)[0]), 1e-9)
        self.assertLessEqual(relative(figures["des.rmv_removed_m3"], thickness), 1e-9)
        self.assertEqual((figures["des.rmv_resting_m3"], figures["des.rmv_transition_m3"], figures["des.rmv_kept_m3"],
                          figures["des.rmv_transition_m2"]), (0.0, 0.0, 0.0, 0.0))
        self.assertNotIn("des.rmv_wall_max_m", figures, "la pared de una plataforma es la de su borde")
        removed = self.outcome.removal
        parts = math.fsum((removed.removed_m3, removed.resting_m3, removed.transition_m3, removed.kept_m3))
        self.assertLessEqual(relative(parts, removed.above_base_m3), 1e-9)
        scopes = {item.key: item.scope for item in self.outcome.figures if item.key.startswith(("des.rmv", "des.plat"))}
        for key, scope in scopes.items():
            self.assertEqual(scope, scopes["des.plat_area_m2"], f"{key}: las dos, con el ámbito de la entidad")
        self.assertEqual(scopes["des.rmv_removed_m3"]["entity"], CODE)

    def test_the_platform_of_a_layer_does_not_change_and_the_figures_of_the_platform_are_the_same_with_the_removal(self) -> None:
        """RF-015-24, P-3 (la plataforma de la 015 no cambia de resultado): el mismo trabajo sin lo de la retirada da el mismo resultado, bit
        a bit, y las mismas cifras de la plataforma, sin ninguna ``des.rmv_*`` ni ``removal``."""
        plain = drained(entity_store.platform_compute_steps(self.job, COMMON))
        self.assertIsNone(plain.removal)
        np.testing.assert_array_equal(plain.result, self.outcome.result)
        self.assertEqual(self.outcome.figures[:len(plain.figures)], plain.figures)
        self.assertFalse([item for item in plain.figures if item.key.startswith("des.rmv")])
        self.assertEqual(plain.notices, self.outcome.notices)

    def test_what_rested_on_the_stockpile_is_the_difference_with_the_surface_it_was_detected_on(self) -> None:
        """RF-016-13, RF-016-14: con lo que se le apoyó (la partida por encima de la superficie con que se detectó, en las celdas de un bloque), lo
        retirado del acopio es ``Σ (T − base)`` y lo apoyado, ``Σ (z − T)``; juntos, lo que había sobre la base."""
        later = np.zeros((N, N))
        later[14:18, 12:16] = 0.5
        found = scene(resting=later)
        _made, _job, outcome = computed(found)
        area = AREA
        base_removed = math.fsum((found.thickness - later)[found.footprint].tolist()) * area
        self.assertLessEqual(relative(outcome.removal.removed_m3, base_removed), 1e-9)
        self.assertLessEqual(relative(outcome.removal.resting_m3, 0.5 * 16 * area), 1e-9)
        total = math.fsum(found.thickness[found.footprint].tolist()) * area
        self.assertLessEqual(relative(outcome.removal.removed_m3 + outcome.removal.resting_m3, total), 1e-9)

    def test_with_nothing_left_of_the_stockpile_the_notice_of_zero_cubic_metres_comes(self) -> None:
        """RF-016-13: si la partida ya no tiene nada del acopio (su superficie es la base), se retiran 0 m³ y avisa que ya no está en la
        superficie de partida, **sin rechazar**: la plataforma se hace igual (RF-015-20)."""
        found = scene()
        gone = dataclasses.replace(found, z=np.where(found.footprint, found.base, found.z))
        made = removal.platform_of_stockpile(gone.item, GRID)
        values = entity_store.entity_values(
            asked(), CODE, 7, {params.PlatformParam.START_LEVEL: made.start_level_m,
                               params.PlatformParam.GRADIENT: made.gradient_pct}, line=False)
        job = platform.PlatformJob(asked(), CODE, GRID, gone.z, made.geometry, values, np.ones((N, N), dtype=bool),
                                   np.ones((N, N), dtype=bool))
        outcome = drained(entity_store.platform_compute_steps(job, COMMON, removed=found.item))
        self.assertEqual(outcome.removal.removed_m3, 0.0)
        self.assertIn("des.removal_nothing", [item.code for item in outcome.notices])
        self.assertEqual({item.key: item.value for item in outcome.figures}["des.rmv_removed_m3"], 0.0)

    def test_what_the_masks_do_not_let_cut_stays_and_is_the_not_removed_volume(self) -> None:
        """RF-016-13, RF-015-20, RF-015-24: donde las máscaras no dejan cortar (un bloque de 3 × 3 celdas de la huella) la superficie se queda
        como estaba y su volumen sobre la base es lo no retirado (``des.rmv_kept_m3``); lo demás baja al plano; los cuatro suman lo que
        había sobre la base y el aviso de lo que no queda en la rasante sale con su causa."""
        found = scene()
        allowed = np.ones((N, N), dtype=bool)
        allowed[16:19, 20:23] = False
        _made, _job, outcome = computed(found, cut=allowed)
        kept = math.fsum(found.thickness[16:19, 20:23].ravel().tolist()) * AREA
        self.assertLessEqual(relative(outcome.removal.kept_m3, kept), 1e-9)
        self.assertLessEqual(relative(outcome.removal.removed_m3, math.fsum(found.thickness.ravel().tolist()) * AREA - kept), 1e-9)
        window = outcome.footprint.window
        held = outcome.result[16 - window[0].start:19 - window[0].start, 20 - window[1].start:23 - window[1].start]
        np.testing.assert_array_equal(held, found.z[16:19, 20:23])
        removed = outcome.removal
        self.assertLessEqual(relative(math.fsum((removed.removed_m3, removed.resting_m3, removed.kept_m3)), removed.above_base_m3), 1e-9)
        self.assertEqual(outcome.applied.blocked_cells, 9)
        self.assertIn("des.platform_above", [item.code for item in outcome.notices])
        warned = [item for item in outcome.notices if item.code == "des.removal_kept"]  # T48, B-2: también «como plataforma»
        self.assertEqual(len(warned), 1)
        self.assertLessEqual(relative(warned[0].values["volume"], kept), 1e-9)
        self.assertEqual(warned[0].values["stockpile"], outcome.removal.name)
        x, y = warned[0].values["x"], warned[0].values["y"]
        centres_x, centres_y = GRID.centers()
        self.assertAlmostEqual(x, float(centres_x[16:19, 20:23].mean()), places=9)
        self.assertAlmostEqual(y, float(centres_y[16:19, 20:23].mean()), places=9)


# --- Los rechazos y el modelo -------------------------------------------------------------------------------------------


class RefusalsAndModelTest(unittest.TestCase):
    """RF-016-16, RF-015-08, RF-015-12: los rechazos de la plataforma con la huella y lo que se añade al modelo."""

    def refused(self, code: str, **given: Any) -> Any:
        with self.assertRaises(DesignError) as caught:
            job_of(scene(), **given)
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn("{", caught.exception.text)
        self.assertNotIn("{", caught.exception.text_in("en"))
        return caught.exception

    def test_the_edge_without_angle_or_reach_a_ramp_and_protecting_in_cut_and_fill_are_refused(self) -> None:
        """RF-015-08, RF-015-12, RF-015-22, D-6, D-7, D-20 (con la huella como geometría, los rechazos de siempre): el ángulo de borde y el
        alcance no tienen valor por defecto (``des.entity_param_missing``, nombrando la clave); una pendiente de 3,76 % con una máxima de
        2 % es una rampa (``des.platform_max_slope``); proteger en «corte y relleno» (``des.platform_protect_cut_fill``)."""
        error = self.refused("des.entity_param_missing", edge_angle_deg=None)
        self.assertEqual(error.values["field"], "des.platform.plt_001.edge_angle_deg")
        error = self.refused("des.entity_param_missing", reach_m=None)
        self.assertEqual(error.values["field"], "des.platform.plt_001.reach_m")
        self.refused("des.entity_param_range", edge_angle_deg=90.0)
        error = self.refused("des.platform_max_slope", max_slope_pct=2.0)
        self.assertEqual(error.values["maximum"], 2.0)
        self.refused("des.platform_protect_cut_fill", mode="cut_fill", protect=True, guard_m=5.0)

    def test_the_request_names_the_stockpile_and_gives_the_plane_as_the_origin_of_the_levels(self) -> None:
        """RF-016-16: ``PlatformRequest.of_stockpile`` es una plataforma con el acopio en ``stockpile`` (su parámetro: el 21.º de la familia,
        sin valor en la de una capa), la «capa» y la «geometría» provisionales (la referencia) y el plano como origen de la cota y la
        pendiente (``PLANE_FIELD``); ``entity_values`` lo copia a los parámetros y la plataforma de una capa no lo lleva."""
        request = asked()
        self.assertEqual((request.stockpile, request.layer, request.feature, request.start),
                         ("STK-001#m07", "STK-001#m07", "STK-001#m07", "terreno"))
        self.assertEqual((request.fields.start_level_field, request.fields.gradient_field), (model.PLANE_FIELD, model.PLANE_FIELD))
        _made, job = job_of(scene())
        self.assertEqual(job.values["stockpile"], "STK-001#m07")
        self.assertEqual(job.values["edge_angle_deg"], ANGLE)
        self.assertEqual(params.PlatformParam.STOCKPILE.value, "stockpile")
        self.assertEqual(len(params.ENTITY_FAMILIES), 21)
        self.assertIn("stockpile", params.entity_params("platform").names)
        self.assertIn("stockpile", params.entity_params("platform").optional)
        layer_values = entity_store.entity_values(
            dataclasses.replace(request, stockpile=None), CODE, 7, {params.PlatformParam.START_LEVEL: 187.0,
                                                                    params.PlatformParam.GRADIENT: 1.0}, line=False)
        self.assertNotIn("stockpile", layer_values, "la plataforma de una capa no lo lleva")

    def test_the_given_axis_is_part_of_the_geometry_and_of_its_hash_and_of_the_window_that_is_read(self) -> None:
        """RF-016-16, RF-015-01, RNF-015-03: el eje dado es de un polígono sin eje enlazado (si no, ``ValueError``); cuenta en el hash de la
        geometría (otro eje, otro hash; el de una geometría sin él, el de siempre) y en la ventana que basta leer, que lo contiene."""
        made = removal.platform_of_stockpile(scene().item, GRID)
        bare = platform.PlatformGeometry("polygon", made.geometry.parts)
        self.assertNotEqual(entity_store.geometry_sha256(made.geometry), entity_store.geometry_sha256(bare))
        other = platform.PlatformGeometry("polygon", made.geometry.parts, given_axis=model.Axis(
            tuple((x + 1.0, y) for x, y in made.axis.vertices)))
        self.assertNotEqual(entity_store.geometry_sha256(made.geometry), entity_store.geometry_sha256(other))
        self.assertEqual(entity_store.geometry_sha256(made.geometry),
                         entity_store.geometry_sha256(platform.PlatformGeometry("polygon", made.geometry.parts, given_axis=made.axis)))
        with self.assertRaises(ValueError):
            platform.PlatformGeometry("line", made.geometry.parts, given_axis=made.axis)
        with self.assertRaises(ValueError):
            platform.PlatformGeometry("polygon", made.geometry.parts, axis_parts=made.geometry.parts, given_axis=made.axis)
        with self.assertRaises(TypeError):
            platform.PlatformGeometry("polygon", made.geometry.parts, given_axis=((0.0, 0.0), (1.0, 1.0)))
        values = {"reach_m": REACH, "metric": "exact"}
        window = platform.reading_window(made.geometry, values, GRID)
        (x0, y0), (x1, y1) = made.axis.vertices
        for x, y in ((x0, y0), (x1, y1)):
            col, row = (x - GRID.west) / STEP, (GRID.north - y) / STEP
            self.assertTrue(window[1].start <= col < window[1].stop and window[0].start <= row < window[0].stop)

    def test_the_steps_are_paced_and_closing_them_halfway_changes_nothing(self) -> None:
        """RF-015-29, RNF-016-03: calcular por pasos de 0 s da varios pasos, cerrar el generador a mitad no deja nada ni modifica ninguna
        entrada (la superficie de partida, la base, la geometría) y el resultado es el mismo que de una vez."""
        found = scene()
        before = (found.z.copy(), found.base.copy())
        _made, job = job_of(found)
        work = entity_store.platform_compute_steps(job, COMMON, removed=found.item, budget_s=0.0)
        shown = [next(work) for _ in range(6)]
        self.assertGreaterEqual(len(shown), 6)
        work.close()
        np.testing.assert_array_equal(found.z, before[0])
        np.testing.assert_array_equal(found.base, before[1])
        again = drained(entity_store.platform_compute_steps(job, COMMON, removed=found.item, budget_s=0.0))
        once = drained(entity_store.platform_compute_steps(job, COMMON, removed=found.item))
        np.testing.assert_array_equal(again.result, once.result)
        self.assertEqual(again.figures, once.figures)


if __name__ == "__main__":
    unittest.main()

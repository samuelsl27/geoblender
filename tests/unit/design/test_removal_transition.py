# SPDX-License-Identifier: GPL-3.0-or-later
"""La transición y el dominio de la retirada de un acopio (spec 016, T17; HU-016-2; RF-016-11, RF-016-13; RNF-016-02,
RNF-016-03; plan 016 §5.4 A0 y A6; D-2, D-5; CA-10).

:func:`design.removal.removal_steps` (y :func:`remove_stockpile`, de una vez) recorre un :class:`RemovalJob` (todo lo
leído —rejilla, superficie de partida, el acopio con su base y la superficie con que se detectó, el dominio por defecto
de la 012, los valores de la retirada—; nada del proyecto) y da el :class:`RemovalOutcome`: las semillas son ``z`` en el
anillo de una celda de lo que se retira (la huella dentro del dominio, con dato), la envolvente descendente con
``tan(transición) · factor de malla`` y la métrica de la retirada, y la superficie nueva ``mín(z, máx(base,
envolvente))`` en lo que se retira (las demás celdas, ``z`` bit a bit). Se prueba con:

- **cuentas a mano** sobre un terreno llano de 100 m con un bloque de 6 × 6 celdas de 2 m a 104 m (576 m³ sobre su base):
  solo, con un relleno de 3 m al lado (la transición por columnas de celdas, con la euclídea, el *chamfer* y un factor de
  malla), ya bajado en parte, retirado del todo (0 m³ con el aviso, también la segunda vez), con una parte fuera del
  dominio (lo que no se retira, con su volumen), con algo apoyado encima y sin ninguna semilla;
- **una implementación independiente** (``tests.support.design_oracles.hand_removal``: un bucle de Python por celda, la
  envolvente por fuerza bruta o el *Dijkstra* del *chamfer*, las cifras como la longitud de la columna a cada lado de la
  superficie de detección y ``fsum``) en escenas con relieve, celdas sin dato, partes bajadas y cargadas y un dominio
  recortado, con las dos métricas y factores de malla;
- **las propiedades** de CA-10: la superficie no baja de la base en ninguna celda, nunca sube, no cambia un bit fuera de
  lo que se retira, y retirado + apoyado + transición + no retirado es lo que había sobre la base a ≤ 10⁻⁹ relativo;
- **la ventana de trabajo** (A0): la leída por :func:`removal_window` da el mismo resultado, bit a bit, que la rejilla
  entera, y :meth:`RemovalOutcome.compose` lo vuelve a poner en ella;
- **los pasos** (RNF-016-03): por pasos de ``budget_s`` como mucho, cancelables, sin modificar ninguna entrada, y los
  rechazos de RF-015-08 (el ángulo no tiene valor por defecto: D-2).
"""

from __future__ import annotations

import copy
import dataclasses
import math
import time
import unittest
from contextlib import closing
from typing import Any

import numpy as np

from tests.support import design_oracles as oracles
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.unit.design.test_stockpile_footprint import params_of

grids = import_geoblender("design.grids")
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")
platform = import_geoblender("design.platform")
provenance = import_geoblender("design.provenance")
removal = import_geoblender("design.removal")
stockpiles = import_geoblender("design.stockpiles")

DesignError = messages.DesignError
STEP = 2.0
AREA = STEP * STEP
ANGLE = 40.0
"""El ángulo de transición de las pruebas (un dato de ENTRADA: D-2, la retirada no tiene valor por defecto)."""
TAN = math.tan(math.radians(ANGLE))
CHAMFER_SCALE = 0.98644
"""La escala del *chamfer* 5×5 (ADR-0014): un paso de eje cuesta ``h · 0,98644``."""
NOTHING = "des.removal_nothing"
KEPT = "des.removal_kept"
BLOCK =(slice(7, 13), slice(7, 13))
"""Las celdas del bloque de las cuentas a mano: 6 × 6 en la rejilla de 20 × 20."""
BLOCK_M = 4.0
"""Lo que el bloque sobresale de su base (m): 36 celdas · 4 m · 4 m² = 576 m³."""


# --- Las escenas -----------------------------------------------------------------------------------------------------


@dataclasses.dataclass(slots=True)
class Scene:
    """Lo leído de una retirada: la ``grid``, la superficie de partida (``z``), la ``base`` y la superficie con que se
    ``detected`` (rejillas enteras; solo se leen en la huella), la ``footprint`` y el ``domain`` (máscaras)."""

    grid: Any
    z: np.ndarray
    base: np.ndarray
    detected: np.ndarray
    footprint: np.ndarray
    domain: np.ndarray


def block_scene(n: int = 20, *, fill: bool = False) -> Scene:
    """Un terreno llano de 100 m de ``n`` × ``n`` celdas de 2 m con un bloque de 6 × 6 a 104 m (su base es el llano) y,
    si ``fill``, un relleno de 3 m (a 103 m) en toda la parte este, desde la columna 13: pegado al bloque. Lo que se
    detectó es lo que hay en la partida."""
    grid = sdata.window_grid(STEP, STEP * n)
    z = np.full((n, n), 100.0)
    z[BLOCK] = 100.0 + BLOCK_M
    if fill:
        z[:, 13:] = 103.0
    footprint = np.zeros((n, n), dtype=bool)
    footprint[BLOCK] = True
    return Scene(grid, z, np.full((n, n), 100.0), z.copy(), footprint, np.ones((n, n), dtype=bool))


def job_of(scene: Scene, *, angle: float | None = ANGLE, mesh: float | None = None, metric: str | None = None,
           region: tuple[slice, slice] | None = None, **extra: object) -> Any:
    """El trabajo de retirada de ``scene``: el acopio con las celdas de su huella, su base y su superficie de detección;
    el ángulo (``None``: sin valor), el factor de malla y la métrica solo si se piden; ``region`` lee solo esa ventana."""
    flat = np.flatnonzero(scene.footprint)
    item = removal.RemovedStockpile("m01", "Acopio de prueba", flat, scene.base.reshape(-1)[flat],
                                    scene.detected.reshape(-1)[flat])
    request = model.RemovalRequest(name="Retirada de prueba", stockpile="STK-001#m01", start="terreno")
    values: dict[str, object] = {"transition_deg": angle, **extra}
    if mesh is not None:
        values["mesh_factor"] = mesh
    if metric is not None:
        values["metric"] = metric
    z, domain = scene.z, scene.domain
    if region is not None:
        z, domain = z[region], domain[region]
    return removal.RemovalJob(request, "RMV-001", scene.grid, z, item, domain, values, region=region)


def outcome_of(scene: Scene, **options: Any) -> Any:
    return removal.remove_stockpile(job_of(scene, **options))


def whole_mask(scene: Scene, outcome: Any, mask: np.ndarray) -> np.ndarray:
    """La máscara ``mask`` (de la ventana de trabajo del ``outcome``) puesta en la rejilla entera de ``scene``."""
    found = np.zeros(scene.z.shape, dtype=bool)
    found[outcome.window] = mask
    return found


def cells_of(outcome: Any, mask: np.ndarray) -> set[tuple[int, int]]:
    """Las celdas ``(fila, columna)`` de la rejilla entera de ``mask`` (de la ventana del ``outcome``)."""
    rows, cols = outcome.window[0].start, outcome.window[1].start
    return {(int(r) + rows, int(c) + cols) for r, c in zip(*np.nonzero(mask), strict=True)}


def hand_of(scene: Scene, *, angle: float = ANGLE, mesh: float = 1.0, metric: str = "exact") -> Any:
    """El cálculo independiente de la misma retirada (:func:`oracles.hand_removal`)."""
    return oracles.hand_removal(scene.z.tolist(), scene.base.tolist(), scene.detected.tolist(),
                                scene.footprint.tolist(), scene.domain.tolist(), step=STEP,
                                tan=math.tan(math.radians(angle)) * mesh, metric=metric)


class Close(unittest.TestCase):
    def close(self, found: float, wanted: float, *, rel: float = 1e-9, what: str = "") -> None:
        """``found`` es ``wanted`` a ≤ ``rel`` relativo (con un suelo de 1 m³ para los ceros)."""
        self.assertLessEqual(abs(found - wanted), rel * max(abs(wanted), 1.0), f"{what}: {found} frente a {wanted}")

    def same(self, found: np.ndarray, wanted: np.ndarray, *, what: str = "") -> None:
        """Las dos rejillas, bit a bit (los NaN, en los mismos sitios)."""
        self.assertEqual(found.shape, wanted.shape, what)
        self.assertTrue(np.array_equal(found, wanted, equal_nan=True), f"{what}: no son idénticas")

    def figures(self, outcome: Any, *, removed: float, resting: float = 0.0, transition: float = 0.0,
                kept: float = 0.0, cells: int = 0) -> None:
        """Las cuatro cifras de la retirada y el área de su transición."""
        self.close(outcome.removed_m3, removed, what="retirado")
        self.close(outcome.resting_m3, resting, what="apoyado")
        self.close(outcome.transition_m3, transition, what="transición")
        self.close(outcome.kept_m3, kept, what="no retirado")
        self.close(outcome.transition_m2, cells * AREA, what="área de la transición")


# --- Las cuentas a mano ----------------------------------------------------------------------------------------------


class HandCasesTest(Close):
    """RF-016-11 y RF-016-13 sobre el bloque de 576 m³: cada número sale de contar celdas en el papel."""

    def test_a_stockpile_on_flat_ground_goes_down_to_its_base(self) -> None:
        """RF-016-11, CA-10: con el terreno llano a la cota de la base, la envolvente desde el anillo (a 100 − 2·tan
        m) queda bajo la base: las 36 celdas pasan a 100 m, se retiran 576 m³ y no hay transición, ni apoyado, ni
        parte sin retirar, ni aviso; la superficie solo cambia en el bloque."""
        scene = block_scene()
        outcome = outcome_of(scene)
        self.assertTrue(np.all(outcome.compose(scene.z)[BLOCK] == 100.0))
        self.figures(outcome, removed=36 * BLOCK_M * AREA)
        self.assertEqual(outcome.notices, ())
        expected = scene.z.copy()
        expected[BLOCK] = 100.0
        self.same(outcome.compose(scene.z), expected, what="la superficie")

    def test_a_fill_beside_the_stockpile_leaves_a_transition_in_its_first_column(self) -> None:
        """RF-016-11, RF-016-13: con un relleno de 3 m pegado al lado este, el anillo de semillas tiene celdas a 103 m;
        con la euclídea, la columna del bloque pegada al relleno (a 2 m) queda a ``103 − 2·tan`` m (1,32 m sobre la
        base) y la siguiente, a 4 m, a 99,64 m: baja a la base. Transición: 6 celdas, ``6 · (3 − 2·tan) · 4`` m³ en
        24 m²; retirado, el resto de los 576 m³."""
        scene = block_scene(fill=True)
        outcome = outcome_of(scene)
        surface = outcome.compose(scene.z)
        wanted = 3.0 - 2.0 * TAN
        self.assertTrue(np.allclose(surface[7:13, 12], 100.0 + wanted, rtol=0.0, atol=1e-12))
        self.assertTrue(np.all(surface[7:13, 7:12] == 100.0))
        transition = 6 * wanted * AREA
        self.figures(outcome, removed=576.0 - transition, transition=transition, cells=6)
        self.same(surface[:, 13:], scene.z[:, 13:], what="el relleno, sin tocar")

    def test_the_chamfer_metric_measures_a_cell_with_its_scale(self) -> None:
        """RF-016-11, ADR-0014: con el *chamfer* 5×5 la celda a una de distancia cuesta ``2 · 0,98644`` m y la envolvente
        queda a ``103 − 2 · 0,98644 · tan`` (1,34 m sobre la base): ``6 · (3 − 2 · 0,98644 · tan) · 4`` m³."""
        outcome = outcome_of(block_scene(fill=True), metric="chamfer5")
        transition = 6 * (3.0 - 2.0 * CHAMFER_SCALE * TAN) * AREA
        self.figures(outcome, removed=576.0 - transition, transition=transition, cells=6)

    def test_the_mesh_factor_scales_the_tangent(self) -> None:
        """RF-016-11, D-2: con el factor de malla 0,4 la tangente efectiva es ``0,4 · tan`` y la envolvente baja ``2 ·
        0,4 · tan`` m por columna: cuatro columnas (3 − 2k·t > 0, k = 1 … 4) dejan transición, 6 · 4 = 24 celdas
        (96 m²); la quinta, no."""
        outcome = outcome_of(block_scene(fill=True), mesh=0.4)
        effective = 0.4 * TAN
        per_row = sum(max(3.0 - 2.0 * k * effective, 0.0) for k in range(1, 9))
        self.assertEqual(sum(1 for k in range(1, 9) if 3.0 - 2.0 * k * effective > 0.0), 4)
        self.figures(outcome, removed=576.0 - 6 * per_row * AREA, transition=6 * per_row * AREA, cells=24)
        self.assertEqual(outcome.mesh_factor, 0.4)

    def test_what_the_start_surface_already_lowered_counts_zero(self) -> None:
        """RF-016-11, D-2, CA-10: con las dos primeras columnas ya a 98 m (bajo la base), las dos siguientes a 102 m y
        las dos últimas a 104 m, se retiran 0 + 2 m + 4 m por celda: ``12 · 2 · 4 + 12 · 4 · 4`` = 288 m³; donde la
        partida ya estaba bajo la base no cambia ni un bit y la superficie no baja de la base en ninguna celda."""
        scene = block_scene()
        scene.z[7:13, 7:9] = 98.0
        scene.z[7:13, 9:11] = 102.0
        outcome = outcome_of(scene)
        surface = outcome.compose(scene.z)
        self.assertTrue(np.all(surface[7:13, 7:9] == 98.0))
        self.assertTrue(np.all(surface[7:13, 9:13] == 100.0))
        self.figures(outcome, removed=12 * 2.0 * AREA + 12 * 4.0 * AREA)
        self.assertEqual(outcome.notices, ())

    def test_a_stockpile_already_removed_gives_zero_with_the_notice(self) -> None:
        """RF-016-13: con la partida ya en la base (o bajo ella) en toda la huella, el acopio ya no está: 0 m³ retirados,
        la superficie idéntica a la de partida y el aviso ``des.removal_nothing`` con su nombre, sin que ninguna cifra
        sea negativa."""
        scene = block_scene()
        scene.z[BLOCK] = 100.0
        scene.z[7, 7] = 99.0
        outcome = outcome_of(scene)
        self.figures(outcome, removed=0.0)
        self.same(outcome.compose(scene.z), scene.z, what="la superficie")
        self.assertEqual([notice.code for notice in outcome.notices], [NOTHING])
        self.assertEqual(outcome.notices[0].values["stockpile"], "Acopio de prueba")
        self.assertIn("«Acopio de prueba»", outcome.notices[0].text())

    def test_a_thin_layer_is_still_something_to_remove(self) -> None:
        """RF-016-13: el aviso es de **0** m³ retirados, no de pocos: con una sola celda 1 cm sobre su base (0,04 m³) la
        retirada la quita, no avisa, y el resto de la huella (ya en la base) cuenta 0."""
        scene = block_scene()
        scene.z[BLOCK] = 100.0
        scene.z[9, 9] = 100.01
        outcome = outcome_of(scene)
        self.figures(outcome, removed=0.01 * AREA)
        self.assertEqual(outcome.notices, ())
        self.assertEqual(outcome.compose(scene.z)[9, 9], 100.0)

    def test_removing_it_twice_removes_nothing_the_second_time(self) -> None:
        """RF-016-11, RF-016-13: retirar otra vez desde la superficie que dejó la primera no mueve un bit (la envolvente
        es la misma, y la superficie ya está bajo ella): 0 m³ con el aviso y la misma transición sobre la base."""
        scene = block_scene(fill=True)
        first = outcome_of(scene)
        self.assertGreater(first.transition_m3, 0.0)
        scene.z = first.compose(scene.z)
        second = outcome_of(scene)
        self.same(second.compose(scene.z), scene.z, what="la segunda superficie")
        self.figures(second, removed=0.0, transition=first.transition_m3, cells=6)
        self.assertEqual([notice.code for notice in second.notices], [NOTHING])

    def test_what_the_domain_does_not_admit_stays_with_its_volume(self) -> None:
        """RF-016-11, RF-016-13, D-5: un acopio que cruza el límite legal (el dominio acaba en la columna 10) deja sus
        dos últimas columnas sin retirar (12 celdas · 4 m · 4 m² = 192 m³, bit a bit como estaban), y esas celdas son
        las semillas de la envolvente: la columna 10 queda a ``104 − 2·tan`` y la 9, a ``104 − 4·tan``, sobre la base
        (transición de ``6 · 4 · Σ (4 − 2k·tan)``), y el resto se retira; la suma, los 576 m³."""
        scene = block_scene()
        scene.domain[:, 11:] = False
        outcome = outcome_of(scene)
        surface = outcome.compose(scene.z)
        self.assertTrue(np.all(surface[7:13, 11:13] == 104.0))
        self.assertTrue(np.allclose(surface[7:13, 10], 104.0 - 2.0 * TAN, rtol=0.0, atol=1e-12))
        self.assertTrue(np.allclose(surface[7:13, 9], 104.0 - 4.0 * TAN, rtol=0.0, atol=1e-12))
        self.assertTrue(np.all(surface[7:13, 7:9] == 100.0))
        transition = 6 * AREA * sum(max(4.0 - 2.0 * k * TAN, 0.0) for k in (1, 2, 3, 4))
        self.figures(outcome, removed=576.0 - 192.0 - transition, transition=transition, kept=192.0, cells=12)
        self.assertEqual(int(np.count_nonzero(outcome.held)), 12)
        self.assertFalse(np.any(outcome.admitted & outcome.held))

    def test_what_the_domain_does_not_admit_is_warned_with_its_volume_and_its_place(self) -> None:
        """RF-016-13, RF-016-15 (T48; hallazgo B-2 de la verificación única): lo que las máscaras no dejan retirar **se avisa**
        (``des.removal_kept``: el volumen y el lugar), no solo es una línea del resumen. Con el dominio acabando en la columna 10
        (el caso de arriba: 192 m³ sin retirar en las columnas 11 y 12 de las filas 7 a 12) el aviso nombra el acopio, los 192 m³ y el
        centro de lo no retirado (a mano: columnas 11 y 12 → x = 23 y 25 m, media 24 m; filas 7 a 12 → y = 15 … 25 m bajo el norte,
        media 20 m); en español y en inglés, en alerta; sin nada sin retirar no avisa (los demás casos de este módulo, ``notices == ()``);
        y el aviso de los 0 m³ retirados va antes si también los hay."""
        scene = block_scene()
        scene.domain[:, 11:] = False
        outcome = outcome_of(scene)
        self.assertEqual([notice.code for notice in outcome.notices], [KEPT])
        notice = outcome.notices[0]
        self.assertEqual(notice.values["stockpile"], "Acopio de prueba")
        self.close(notice.values["volume"], 192.0, what="lo no retirado")
        self.assertAlmostEqual(notice.values["x"], scene.grid.west + 24.0, places=9)
        self.assertAlmostEqual(notice.values["y"], scene.grid.north - 20.0, places=9)
        self.assertEqual(notice.severity, "warning")
        self.assertIn("«Acopio de prueba»", notice.text("es"))
        self.assertIn("192", notice.text("es"))
        self.assertIn("no se retira", notice.text("es"))
        self.assertIn("192", notice.text("en"))
        self.assertIn("not removed", notice.text("en"))
        self.assertNotIn("{", notice.text("es") + notice.text("en"))
        wholly = block_scene()
        wholly.domain[:] = False  # el dominio no admite nada: 0 m³ retirados y todo sin retirar
        found = outcome_of(wholly)
        self.assertEqual([item.code for item in found.notices], [NOTHING, KEPT])
        self.close(found.notices[1].values["volume"], 576.0, what="todo el acopio sin retirar")

    def test_what_rests_on_the_stockpile_is_counted_apart(self) -> None:
        """RF-016-13: con 3 m más sobre la superficie con que se detectó en las tres columnas este (algo que se le
        apoyó después), cada celda retira 4 m del acopio (hasta su base) y 3 m de lo apoyado en 18 celdas: retirado 576
        m³, apoyado ``18 · 3 · 4`` = 216 m³."""
        scene = block_scene()
        scene.z[7:13, 10:13] += 3.0
        outcome = outcome_of(scene)
        self.figures(outcome, removed=576.0, resting=216.0)
        self.assertEqual(outcome.notices, ())

    def test_a_cell_without_data_is_neither_removed_nor_a_seed(self) -> None:
        """RF-016-11: una celda de la huella sin dato (NaN) queda sin dato y no cuenta; una del anillo sin dato no es
        semilla: se retiran 35 celdas · 4 m · 4 m² = 560 m³."""
        scene = block_scene()
        scene.z[9, 9] = np.nan
        scene.z[6, 9] = np.nan
        outcome = outcome_of(scene)
        surface = outcome.compose(scene.z)
        self.assertTrue(np.isnan(surface[9, 9]) and np.isnan(surface[6, 9]))
        self.figures(outcome, removed=35 * BLOCK_M * AREA)
        self.assertFalse(whole_mask(scene, outcome, outcome.seeds)[[6, 9], 9].any())

    def test_without_a_seed_everything_goes_to_the_base(self) -> None:
        """RF-016-11: si la huella es toda la rejilla no hay anillo ni semillas, la envolvente es −∞ y la superficie
        es ``mín(z, base)`` en todas las celdas (sin transición): 6 × 6 celdas a 104 m se retiran enteras."""
        scene = block_scene(6)
        scene.z[:] = 104.0
        scene.detected[:] = 104.0
        scene.footprint[:] = True
        outcome = outcome_of(scene)
        self.assertTrue(np.all(outcome.surface == 100.0))
        self.figures(outcome, removed=36 * 4.0 * AREA)
        self.assertFalse(outcome.seeds.any())


# --- Contra la implementación independiente --------------------------------------------------------------------------


def random_scene(seed: int, n: int = 26) -> Scene:
    """Un montón de forma y altura al azar sobre un plano con relieve, en ``n`` × ``n`` celdas de 2 m: lo que se detectó
    (``detected``: relieve + montón), una partida con partes **ya bajadas** (por debajo de la base y por encima de ella),
    partes **cargadas** encima de lo detectado, un relleno al este fuera de la huella, celdas sin dato (una de la
    huella y otra del anillo) y un dominio recortado por el este."""
    rng = np.random.default_rng(seed)
    grid = sdata.window_grid(STEP, STEP * n)
    rows, cols = np.mgrid[0:n, 0:n].astype(np.float64)
    plane = 100.0 + 0.04 * cols + 0.03 * rows
    relief = 0.3 * np.sin(cols / 3.0) + 0.2 * np.cos(rows / 4.0) + rng.normal(0.0, 0.05, (n, n))
    centre_row, centre_col = n / 2 + rng.uniform(-2.0, 2.0, 2)
    radius = rng.uniform(4.0, 6.0)
    distance = np.hypot(rows - centre_row, cols - centre_col)
    footprint = distance <= radius
    mound = np.where(footprint, rng.uniform(1.5, 5.0) * (1.0 - 0.8 * distance / radius), 0.0)
    detected = plane + relief + mound
    start = detected.copy()
    inside = np.argwhere(footprint)
    for kind in ("deep", "shallow", "load"):
        row, col = inside[int(rng.integers(len(inside)))]
        patch = (slice(max(row - 1, 0), row + 2), slice(max(col - 1, 0), col + 2))
        if kind == "load":  # algo puesto después sobre lo detectado
            start[patch] = detected[patch] + 2.5
        elif kind == "deep":  # ya bajado por debajo de la base
            start[patch] = plane[patch] - rng.uniform(0.2, 1.0)
        else:  # ya bajado en parte, sin llegar a la base
            start[patch] = np.minimum(detected[patch], plane[patch] + rng.uniform(0.2, 1.5))
    east = int(centre_col + radius) + 2
    start[:, east:] += 3.0
    row, col = inside[int(rng.integers(len(inside)))]
    start[row, col] = np.nan
    start[int(centre_row - radius) - 1, int(centre_col)] = np.nan
    domain = np.ones((n, n), dtype=bool)
    if seed % 3 != 0:  # el dominio acaba dentro de la huella (el límite legal la cruza)
        domain[:, int(centre_col + rng.uniform(-1.0, 3.0)):] = False
    return Scene(grid, start, plane, detected, footprint, domain)


class OracleTest(Close):
    """RF-016-11, RF-016-13: la superficie celda a celda y las cinco cifras iguales a :func:`oracles.hand_removal` en
    escenas con relieve, con las dos métricas y varios ángulos y factores de malla."""

    CASES = tuple((seed, metric, angle, mesh)
                  for seed in range(4) for metric in ("exact", "chamfer5")
                  for angle, mesh in ((25.0, 1.0), (40.0, 0.93), (55.0, 0.6)))

    def test_the_surface_and_the_figures_are_the_independent_calculation(self) -> None:
        """La superficie igual a ``hand_removal`` a ≤ 10⁻⁹ m en todas las celdas; las celdas que se retiran, las que no y
        las semillas, las mismas; el retirado, el apoyado, la transición y lo que no se retira, a ≤ 10⁻⁹ relativo; las
        celdas de la transición, las mismas."""
        for seed, metric, angle, mesh in self.CASES:
            with self.subTest(seed=seed, metric=metric, angle=angle, mesh=mesh):
                scene = random_scene(seed)
                outcome = outcome_of(scene, angle=angle, mesh=mesh, metric=metric)
                hand = hand_of(scene, angle=angle, mesh=mesh, metric=metric)
                surface = outcome.compose(scene.z)
                self.assertTrue(np.allclose(surface, hand.surface, rtol=0.0, atol=1e-9, equal_nan=True))
                self.assertEqual(cells_of(outcome, outcome.admitted), hand.admitted)
                self.assertEqual(cells_of(outcome, outcome.held), hand.held)
                self.assertEqual(cells_of(outcome, outcome.seeds), hand.ring)
                self.close(outcome.removed_m3, hand.removed, what="retirado")
                self.close(outcome.resting_m3, hand.resting, what="apoyado")
                self.close(outcome.transition_m3, hand.transition, what="transición")
                self.close(outcome.kept_m3, hand.kept, what="no retirado")
                self.close(outcome.above_base_m3, hand.above, what="lo que había sobre la base")
                self.assertEqual(outcome.transition_m2, hand.transition_cells * AREA)

    def test_the_scenes_exercise_every_case(self) -> None:
        """Las escenas no son triviales: en alguna hay retirado, apoyado, transición y parte sin retirar, y partes ya
        bajadas bajo la base (donde la partida no cambia)."""
        found = {name: 0 for name in ("removed", "resting", "transition", "kept")}
        lowered = 0
        for seed in range(4):
            scene = random_scene(seed)
            outcome = outcome_of(scene, angle=40.0, mesh=0.93)
            for name in found:
                found[name] += getattr(outcome, f"{name}_m3") > 0.0
            lowered += int(np.count_nonzero(whole_mask(scene, outcome, outcome.admitted) & (scene.z <= scene.base)))
        self.assertTrue(all(found.values()), found)
        self.assertGreater(lowered, 0)


class PropertiesTest(Close):
    """CA-10, RF-016-11, RF-016-13: lo que vale en cualquier escena."""

    def runs(self) -> list[tuple[Any, Any]]:
        found = []
        for seed in range(4):
            scene = random_scene(seed)
            for metric in ("exact", "chamfer5"):
                found.append((scene, outcome_of(scene, angle=40.0, mesh=0.93, metric=metric)))
        return found

    def test_the_surface_never_goes_below_the_base_or_rises(self) -> None:
        """CA-10: en toda celda de la huella con dato, ``z' ≥ mín(z, base)`` (no baja de la base, y donde la partida ya
        estaba más baja se queda donde estaba) y ``z' ≤ z`` en toda la rejilla (la retirada nunca sube nada)."""
        for scene, outcome in self.runs():
            surface = outcome.compose(scene.z)
            with np.errstate(invalid="ignore"):
                inside = scene.footprint & np.isfinite(scene.z)
                self.assertTrue(np.all(surface[inside] >= np.minimum(scene.z, scene.base)[inside]))
                self.assertTrue(np.all(surface[np.isfinite(scene.z)] <= scene.z[np.isfinite(scene.z)]))

    def test_nothing_changes_outside_what_is_removed(self) -> None:
        """RF-016-11: fuera de la huella, dentro de ella donde el dominio no admite la retirada y donde no hay dato, la
        superficie es la de partida **bit a bit** (también los NaN)."""
        for scene, outcome in self.runs():
            untouched = ~whole_mask(scene, outcome, outcome.admitted)
            surface = outcome.compose(scene.z)
            self.assertTrue(np.array_equal(surface[untouched], scene.z[untouched], equal_nan=True))
            self.assertEqual(int(np.count_nonzero(np.isnan(surface))), int(np.count_nonzero(np.isnan(scene.z))))

    def test_the_four_volumes_add_up_to_what_was_over_the_base(self) -> None:
        """RF-016-13: retirado + apoyado + transición + no retirado es lo que había sobre la base en la huella
        (``Σ máx(z − base, 0) · área``, contado a mano con ``fsum``) a ≤ 10⁻⁹ relativo, y ninguna cifra es negativa."""
        for scene, outcome in self.runs():
            wanted = math.fsum(float(max(z - b, 0.0)) for z, b in zip(scene.z[scene.footprint], scene.base[scene.footprint],
                                                                      strict=True) if math.isfinite(z)) * AREA
            total = math.fsum((outcome.removed_m3, outcome.resting_m3, outcome.transition_m3, outcome.kept_m3))
            self.close(total, wanted, what="la suma")
            self.close(outcome.above_base_m3, wanted, what="lo que había sobre la base")
            self.assertGreaterEqual(min(outcome.removed_m3, outcome.resting_m3, outcome.transition_m3,
                                        outcome.kept_m3), 0.0)

    def test_no_pair_beside_the_removal_is_steeper_than_the_transition(self) -> None:
        """RF-016-11: con la euclídea, la cota de una celda que la retirada baja sin llegar a la base no queda más de
        ``tan · distancia`` bajo ninguna semilla (ninguna pared entre el anillo y lo que se retira pasa del ángulo de
        transición por el factor de malla)."""
        for seed in range(4):
            scene = random_scene(seed)
            outcome = outcome_of(scene, angle=40.0, mesh=0.93)
            surface = outcome.compose(scene.z)
            tan = math.tan(math.radians(40.0)) * 0.93
            seeds = sorted(cells_of(outcome, outcome.seeds))
            for row, col in sorted(cells_of(outcome, outcome.admitted)):
                if surface[row, col] <= scene.base[row, col] or surface[row, col] == scene.z[row, col]:
                    continue  # en la base, o sin tocar (ya bajo la envolvente): no la fija ninguna semilla
                for seed_row, seed_col in seeds:
                    drop = scene.z[seed_row, seed_col] - surface[row, col]
                    self.assertLessEqual(drop, tan * STEP * math.hypot(row - seed_row, col - seed_col) + 1e-9)


# --- La ventana de trabajo (A0) y la superficie entera ----------------------------------------------------------------


class WindowTest(Close):
    """RF-016-11, plan 016 A0: el cálculo solo necesita la ventana de la huella."""

    def test_the_work_window_is_the_footprint_box_plus_two_cells(self) -> None:
        """A0: ``removal_window`` es la caja de la huella ampliada dos celdas (``platform.work_window`` con alcance 0),
        recortada a la rejilla: filas y columnas 5 a 15 del bloque de la rejilla de 20 × 20; en la esquina, recortada."""
        scene = block_scene()
        job = job_of(scene)
        window = removal.removal_window(job.stockpile, scene.grid)
        self.assertEqual(window, (slice(5, 15), slice(5, 15)))
        self.assertEqual(window, platform.work_window(BLOCK[0], BLOCK[1], 0.0, scene.grid))
        corner = block_scene()
        corner.footprint[:] = False
        corner.footprint[0:3, 0:3] = True
        item = job_of(corner).stockpile
        self.assertEqual(removal.removal_window(item, corner.grid), (slice(0, 5), slice(0, 5)))

    def test_reading_only_the_window_gives_the_same_result_bit_by_bit(self) -> None:
        """A0: con ``region`` = la ventana (solo se leen sus celdas), la superficie, las cifras y las máscaras son las de
        la rejilla entera, y ``compose`` la devuelve a su sitio en la rejilla entera."""
        for seed, metric in ((0, "exact"), (1, "chamfer5"), (2, "exact")):
            with self.subTest(seed=seed, metric=metric):
                scene = random_scene(seed, 40)
                whole = outcome_of(scene, angle=40.0, mesh=0.93, metric=metric)
                region = removal.removal_window(job_of(scene).stockpile, scene.grid)
                part = outcome_of(scene, angle=40.0, mesh=0.93, metric=metric, region=region)
                self.same(part.surface, whole.surface, what="la superficie de la ventana")
                self.same(part.compose(scene.z), whole.compose(scene.z), what="la superficie entera")
                for name in ("removed_m3", "resting_m3", "transition_m3", "kept_m3", "transition_m2"):
                    self.assertEqual(getattr(part, name), getattr(whole, name), name)
                self.assertEqual(part.window, region)
                self.assertLess(part.surface.size, scene.z.size)

    def test_a_region_that_does_not_cover_the_window_is_a_program_error(self) -> None:
        """Una ``region`` menor que la ventana de trabajo no se calcula con menos: ``ValueError`` al pedirla."""
        scene = random_scene(0)
        region = (slice(8, 18), slice(8, 18))
        with self.assertRaises(ValueError):
            outcome_of(scene, region=region)

    def test_compose_returns_a_new_surface_of_the_whole_grid(self) -> None:
        """``compose`` no modifica la partida y da una rejilla nueva; una que no cabe la ventana es ``ValueError``."""
        scene = block_scene()
        outcome = outcome_of(scene)
        before = scene.z.copy()
        composed = outcome.compose(scene.z)
        self.same(scene.z, before, what="la partida")
        self.assertIsNot(composed, scene.z)
        with self.assertRaises(ValueError):
            outcome.compose(np.zeros((8, 8)))


# --- Los pasos, los rechazos y la entrada -----------------------------------------------------------------------------


class StepsTest(Close):
    """RNF-016-03, RF-015-08, D-2: por pasos, cancelable, sin tocar la entrada, con sus rechazos."""

    def test_the_steps_end_with_the_outcome_and_match_the_one_shot_call(self) -> None:
        """``removal_steps`` da ``Progress`` de la fase ``removal``; solo el último lleva el resultado, y es el de
        ``remove_stockpile``. Con un presupuesto de 0 s cada unidad es un paso: son varios."""
        scene = random_scene(1)
        steps = list(removal.removal_steps(job_of(scene, mesh=0.93), budget_s=0.0))
        self.assertGreater(len(steps), 3)
        self.assertTrue(all(step.phase == "removal" for step in steps))
        self.assertTrue(all(step.result is None for step in steps[:-1]))
        self.assertEqual([step.done for step in steps[:-1]], list(range(1, len(steps))))
        last = steps[-1].result
        self.assertIsInstance(last, removal.RemovalOutcome)
        once = outcome_of(scene, mesh=0.93)
        self.same(last.surface, once.surface, what="la superficie")
        self.assertEqual(last.removed_m3, once.removed_m3)

    def test_closing_half_way_leaves_nothing_and_no_input_changes(self) -> None:
        """Cerrar el generador a mitad no deja nada y ni la partida, ni el dominio, ni el acopio se modifican (también al
        terminar)."""
        scene = random_scene(2)
        job = job_of(scene)
        before = (job.start.copy(), job.domain.copy(), job.stockpile.cells.copy(), job.stockpile.base.copy(),
                  job.stockpile.surface.copy(), copy.deepcopy(dict(job.values)))
        steps = removal.removal_steps(job, budget_s=0.0)
        next(steps)
        steps.close()
        removal.remove_stockpile(job)
        after = (job.start, job.domain, job.stockpile.cells, job.stockpile.base, job.stockpile.surface, dict(job.values))
        for found, wanted in zip(after, before, strict=True):
            if isinstance(wanted, np.ndarray):
                self.same(found, wanted)
            else:
                self.assertEqual(found, wanted)

    def test_each_step_takes_at_most_two_tenths_of_a_second(self) -> None:
        """RNF-016-03: en una ventana de ≈ 34.000 celdas (la mayor del plan §7.3: 184 × 184), con las dos métricas, cada llamada del
        hilo de Blender (cada paso con el presupuesto de 50 ms) tarda ≤ 0,2 s."""
        n = 200
        scene = block_scene(n)
        scene.z[:] = 100.0
        scene.footprint[:] = False
        scene.footprint[10:190, 10:190] = True
        scene.z[scene.footprint] = 104.0
        scene.detected[:] = scene.z
        scene.z[:, 190:] = 103.0
        for metric in ("exact", "chamfer5"):
            with self.subTest(metric=metric):
                steps = removal.removal_steps(job_of(scene, metric=metric), budget_s=0.05)
                worst = 0.0
                with closing(steps):
                    while True:
                        began = time.perf_counter()
                        step = next(steps)
                        worst = max(worst, time.perf_counter() - began)
                        if step.result is not None:
                            break
                self.assertLessEqual(worst, 0.2)

    def test_the_transition_angle_has_no_default_and_is_checked(self) -> None:
        """RF-015-08, D-2: sin ángulo de transición, ``des.entity_param_missing`` con el campo
        ``des.removal.rmv_001.transition_deg`` y la retirada por su nombre; con 0 o 90 (excluidos), ``des.entity_param_range``:
        no se elige un ángulo por la persona, y se rechaza **al pedir los pasos**, antes de calcular."""
        scene = block_scene()
        with self.assertRaises(DesignError) as caught:
            removal.removal_steps(job_of(scene, angle=None))
        self.assertEqual(caught.exception.code, "des.entity_param_missing")
        self.assertEqual(caught.exception.field, "des.removal.rmv_001.transition_deg")
        self.assertIn("«Retirada de prueba»", caught.exception.text)
        for value in (0.0, 90.0, -5.0, 120.0):
            with self.subTest(angle=value), self.assertRaises(DesignError) as caught:
                removal.removal_steps(job_of(scene, angle=value))
            self.assertEqual(caught.exception.code, "des.entity_param_range")
            self.assertEqual(caught.exception.value, value)

    def test_the_mesh_factor_and_the_metric_are_checked_and_have_their_defaults(self) -> None:
        """RF-015-08, D-2, D-22 de la 015: un factor de malla fuera de su rango es ``des.entity_param_range``; una métrica
        que no es de la lista, ``des.entity_param_choice``; sin ellos, el factor 1,0 y la euclídea exacta."""
        scene = block_scene(fill=True)
        for value in (0.0, -0.5, 11.0):
            with self.subTest(mesh=value), self.assertRaises(DesignError) as caught:
                removal.removal_steps(job_of(scene, mesh=value))
            self.assertEqual(caught.exception.code, "des.entity_param_range")
        with self.assertRaises(DesignError) as caught:
            removal.removal_steps(job_of(scene, metric="chamfer3"))
        self.assertEqual(caught.exception.code, "des.entity_param_choice")
        default = outcome_of(scene)
        self.assertEqual((default.mesh_factor, default.metric, default.transition_deg), (1.0, "exact", ANGLE))
        self.assertEqual(default.removed_m3, outcome_of(scene, mesh=1.0, metric="exact").removed_m3)

    def test_the_job_refuses_what_is_not_a_removal(self) -> None:
        """Errores del programa (``ValueError``): un código que no es el de una retirada, un valor que no es de ella,
        un acopio fuera de la rejilla o sin celdas, una superficie o un dominio de otra forma."""
        scene = block_scene()
        job = job_of(scene)
        for changes in ({"code": "PLT-001"}, {"code": "RMV-1"}, {"values": {"width_m": 3.0}},
                        {"start": np.zeros((5, 5))}, {"domain": np.ones((5, 5), dtype=bool)}):
            with self.subTest(changes=list(changes)), self.assertRaises(ValueError):
                dataclasses.replace(job, **changes)
        item = job.stockpile
        for cells, base, surface in ((np.array([], dtype=np.int64), [], []),
                                     (np.array([10_000]), [100.0], [104.0]),
                                     (np.array([5, 4]), [100.0, 100.0], [104.0, 104.0]),
                                     (np.array([5, 6]), [100.0], [104.0]),
                                     (np.array([5, 6]), [100.0, np.nan], [104.0, 104.0])):
            with self.subTest(cells=cells.tolist()), self.assertRaises(ValueError):
                removal.removal_window(removal.RemovedStockpile(item.key, item.name, cells, base, surface), scene.grid)

    def test_the_outcome_gives_the_figures_of_the_removal(self) -> None:
        """RF-016-13: ``figures`` son las ``des.rmv_*`` de ``provenance.removal_figures`` (CALCULADO, con el ámbito de la
        entidad): el retirado, el apoyado, la transición, lo no retirado y el área de la transición; sin pared
        (todavía: la T19), no hay ``des.rmv_wall_max_m``."""
        outcome = outcome_of(block_scene(fill=True))
        found = {figure.key: figure.value for figure in outcome.figures}
        self.assertEqual(set(found), {"des.rmv_removed_m3", "des.rmv_resting_m3", "des.rmv_transition_m3",
                                      "des.rmv_kept_m3", "des.rmv_transition_m2"})
        self.assertEqual(found["des.rmv_removed_m3"], outcome.removed_m3)
        self.assertEqual(found["des.rmv_transition_m2"], outcome.transition_m2)
        walled = dataclasses.replace(outcome, wall_max_m=2.5)
        self.assertEqual({figure.key: figure.value for figure in walled.figures}["des.rmv_wall_max_m"], 2.5)


# --- Con una detección de verdad -------------------------------------------------------------------------------------


class DetectedStockpileTest(Close):
    """RF-016-11, RF-016-13: un acopio detectado de verdad (A2 a A5) y retirado: el cono de CE-016-02 sobre un plano de
    3° con sus celdas atípicas."""

    @classmethod
    def setUpClass(cls) -> None:
        case = sdata.mound_case("cone", 3.0)
        mark = np.zeros(case.grid.shape, dtype=bool)
        left, bottom, right, top = case.mark_box
        x, y = sdata.local_centers(case.grid)
        mark[(x > left) & (x < right) & (y > bottom) & (y < top)] = True
        job = stockpiles.StockpileJob(name="Detección de prueba", code="STK-001", grid=case.grid, surface=case.terrain,
                                      marks=(stockpiles.StockpileMark(key="Cono", cells=np.flatnonzero(mark)),),
                                      params=params_of())
        cls.case = case
        cls.detection = stockpiles.detect_stockpiles(job)
        cls.item = cls.detection.stockpiles[0]

    def retire(self, z: np.ndarray, **options: Any) -> Any:
        request = model.RemovalRequest(name="Retirada del cono", stockpile="STK-001#Cono", start="terreno")
        job = removal.RemovalJob(request, "RMV-001", self.case.grid, z, removal.RemovedStockpile.of(self.item),
                                 np.ones(z.shape, dtype=bool), {"transition_deg": ANGLE, **options})
        return removal.remove_stockpile(job)

    def test_the_stockpile_is_taken_from_the_detection_as_it_is(self) -> None:
        """``RemovedStockpile.of`` lleva las celdas, la base y la superficie con que se detectó del acopio detectado, sin
        copiar su identidad (la clave y el nombre de su marca)."""
        found = removal.RemovedStockpile.of(self.item)
        self.assertEqual((found.key, found.name), (self.item.key, self.item.name))
        self.assertTrue(np.array_equal(found.cells, self.item.cells))
        self.assertTrue(np.array_equal(found.base, self.item.base))
        self.assertTrue(np.array_equal(found.surface, self.item.surface))

    def test_removing_it_from_the_surface_it_was_detected_on_gives_its_volume_and_the_sums_hold(self) -> None:
        """RF-016-13: desde la superficie con que se detectó, no hay nada apoyado ni sin retirar; el retirado más la
        transición es lo que hay sobre su base en la huella (incluidas las celdas bajo el umbral de huella, que el
        volumen de la detección no cuenta: el retirado no es menor), y la superficie no baja de la base."""
        outcome = self.retire(self.case.terrain)
        self.assertEqual((outcome.resting_m3, outcome.kept_m3), (0.0, 0.0))
        self.assertGreaterEqual(outcome.removed_m3, self.item.volume_m3 - outcome.transition_m3 - 1e-6)
        self.close(outcome.removed_m3 + outcome.transition_m3, outcome.above_base_m3)
        surface = outcome.compose(self.case.terrain)
        footprint = np.zeros(self.case.grid.shape, dtype=bool)
        footprint.reshape(-1)[self.item.cells] = True
        base = np.full(self.case.grid.shape, np.nan)
        base.reshape(-1)[self.item.cells] = self.item.base
        self.assertTrue(np.all(surface[footprint] >= np.minimum(self.case.terrain, base)[footprint]))
        hand = oracles.hand_removal(self.case.terrain.tolist(), base.tolist(), self.case.terrain.tolist(),
                                    footprint.tolist(), np.ones(self.case.grid.shape, dtype=bool).tolist(),
                                    step=self.case.grid.dx, tan=TAN)
        self.assertTrue(np.allclose(surface, hand.surface, rtol=0.0, atol=1e-9))
        self.close(outcome.removed_m3, hand.removed)

    def test_the_same_stockpile_loaded_afterwards_counts_what_rests_on_it(self) -> None:
        """RF-016-13: con una capa de 2 m más puesta después sobre la mitad de la huella, el apoyado es esa capa por su
        área y el retirado sigue siendo el del acopio."""
        loaded = self.case.terrain.copy()
        footprint = np.zeros(self.case.grid.shape, dtype=bool)
        footprint.reshape(-1)[self.item.cells] = True
        rows, cols = np.nonzero(footprint)
        half = footprint & (np.arange(footprint.shape[1])[None, :] < int(np.median(cols)))
        loaded[half] += 2.0
        outcome = self.retire(loaded)
        self.close(outcome.resting_m3, 2.0 * np.count_nonzero(half) * self.case.grid.cell_area, rel=1e-9)
        self.close(outcome.removed_m3, self.retire(self.case.terrain).removed_m3, rel=1e-3)


if __name__ == "__main__":
    unittest.main()

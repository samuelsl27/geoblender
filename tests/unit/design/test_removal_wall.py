# SPDX-License-Identifier: GPL-3.0-or-later
"""La pared que deja la retirada de un acopio y sus confirmaciones (spec 016, T19; HU-016-2; RF-016-15; RNF-016-03; plan 016
§5.4 A8 y §8; D-6; CA-9, CA-10; errores 41 y 47).

:func:`design.removal.measure_wall` (y :func:`wall_steps`, por pasos) mide, sobre el :class:`RemovalOutcome` de A6, la pared que
queda en el borde de lo retirado: las **parejas** de celdas vecinas con una movida y la otra no que la 014 mide como salto creado
(``edges``: ``|S_a − S_b| − |z_a − z_b|``), las que pasan del salto admitido (``des.edge.max_created_step_m``) y de la inclinación
del ángulo de transición más la tolerancia de cara de la 013 (``des.tolerance.face_deg``), y sus **tramos**: la altura recorre la cara
(la mayor cota de sus parejas menos la menor, no el relieve local de una pareja: error 41) y la inclinación es la de su peor pareja.
Se prueba con:

- **cuentas a mano** (un bloque de 6 × 6 celdas a 104 m sobre un llano de 100 m con el dominio terminando en el perímetro): la
  superficie que dejaría retirar sin transición (error 47: cada celda a su base) deja un tramo de 6 parejas de 4 m a 63,43°; la altura
  recorre la cara cuando las cotas del borde difieren; el ángulo de transición más la tolerancia; el salto admitido; lo que el
  terreno ya tenía no es una pared creada;
- **el acopio de 12 m junto a un relleno** (CE-016-03): con la transición de A6, ninguna pared alrededor de la huella pasa del ángulo
  más la tolerancia (con los saltos creados que quedan, comprobados con la implementación independiente) y sin ella (la superficie del
  error 47), una pared de 3 m a 71,57° que pide confirmación y motivo;
- **el ruido** de 5 cm en el terreno sin falsos avisos (también con el salto admitido casi a 0);
- **la implementación independiente** (:func:`tests.support.design_oracles.hand_wall`: un bucle de Python por pareja) en escenas al
  azar, con la retirada de A6 y con la superficie sin transición, y la comprobación cruzada con ``edges.created_steps``;
- **las confirmaciones** (RF-016-15, CA-9): sin confirmar no se crea; con una pared de más de 45° y 3 m o más, tampoco sin un motivo
  (los límites exactos de cada umbral); el aviso con su altura, su inclinación, el salto creado y su lugar;
- **los pasos** (RNF-016-03: ≤ 0,2 s cada llamada), la entrada intacta y los rechazos.

La pared **no la crea la transición de A6** (con la métrica exacta, ninguna pareja creada pasa de ``tan · factor de malla``: una celda
movida junto a una semilla queda a ``≥ z_s − tan · d``): se mide para que lo demuestre cada retirada y para lo que sí la crea (una
superficie sin transición, el factor de malla fuera de rango, una métrica nueva), y se prueba **forzando** esa superficie.
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
from tests.unit.design.test_removal_transition import (
    ANGLE,
    BLOCK,
    STEP,
    Close,
    Scene,
    job_of,
    random_scene,
)

edges = import_geoblender("design.edges")
messages = import_geoblender("design.messages")
preview = import_geoblender("design.preview")
removal = import_geoblender("design.removal")
stockpiles = import_geoblender("design.stockpiles")

DesignError = messages.DesignError
TOLERANCE_KEY = "des.tolerance.face_deg"
THICKNESS_KEY = "res.verify.min_thickness_m"
JUMP_KEY = "des.edge.max_created_step_m"
UMBRAL = 0.3
"""El umbral de huella de la 011 (``res.anthropic_presence_m``): un dato de ENTRADA de la prueba."""
TALL_ANGLE = 35.0
"""El ángulo de transición del acopio alto (el de referencia de D-2, un dato de ENTRADA)."""


def project(*, tolerance: float = 1.0, thickness: float = 0.01, jump: float = 1.0) -> dict[str, float]:
    """Los parámetros del proyecto que lee la pared (datos de ENTRADA: la tolerancia de cara de la 013, el espesor mínimo de la 012 y el
    salto admitido de la 014): ninguno lleva valor por defecto en ``design.removal``."""
    return {TOLERANCE_KEY: tolerance, THICKNESS_KEY: thickness, JUMP_KEY: jump}


def measure(job: Any, outcome: Any, **options: float) -> Any:
    """La retirada ``outcome`` con la pared de ``job`` medida (:func:`removal.measure_wall`)."""
    return removal.measure_wall(job, outcome, project(**options))


def column_scene(step: float = STEP, height: float = 4.0, *, held_from: int | None = 10, n: int = 20) -> Scene:
    """Un llano de 100 m de ``n`` × ``n`` celdas de ``step`` m con un bloque de 6 × 6 celdas (:data:`BLOCK`) a ``100 + height``
    (su base es el llano; lo detectado, lo que hay) y el dominio que acaba en la columna ``held_from`` (el perímetro cruza el
    bloque: lo de las columnas ``held_from`` en adelante no se retira); sin ella, todo el dominio."""
    grid = sdata.window_grid(step, step * n)
    z = np.full((n, n), 100.0)
    z[BLOCK] = 100.0 + height
    footprint = np.zeros((n, n), dtype=bool)
    footprint[BLOCK] = True
    domain = np.ones((n, n), dtype=bool)
    if held_from is not None:
        domain[:, held_from:] = False
    return Scene(grid, z, np.full((n, n), 100.0), z.copy(), footprint, domain)


def forged(scene: Scene, outcome: Any) -> Any:
    """``outcome`` con la superficie que dejaría retirar **sin transición** (el error 47): cada celda que se retira baja a su base
    (o se queda, si ya estaba más baja) y el resto no cambia."""
    start, base = scene.z[outcome.window], scene.base[outcome.window]
    return dataclasses.replace(outcome, surface=np.where(outcome.admitted, np.minimum(start, base), start))


def level_of(outcome: Any, level: float) -> Any:
    """``outcome`` con todas las celdas que se retiran a la cota ``level``."""
    return dataclasses.replace(outcome, surface=np.where(outcome.admitted, level, outcome.surface))


def window_of(scene: Scene, outcome: Any) -> tuple[Any, Any]:
    """La rejilla de la ventana de trabajo de ``outcome`` (su esquina noroeste) y la superficie de partida en ella."""
    rows, cols = outcome.window
    return stockpiles.window_grid(scene.grid, outcome.window), scene.z[rows, cols]


def hand_of(scene: Scene, outcome: Any, *, angle: float = ANGLE, tolerance: float = 1.0, thickness: float = 0.01,
            jump: float = 1.0) -> Any:
    """La pared de ``outcome`` por la implementación independiente (:func:`oracles.hand_wall`), en su ventana de trabajo."""
    sub, start = window_of(scene, outcome)
    return oracles.hand_wall(start.tolist(), outcome.surface.tolist(), outcome.admitted.tolist(), dx=sub.dx, dy=sub.dy,
                             west=sub.west, north=sub.north, thickness=thickness, threshold=jump, limit_deg=angle + tolerance)


class Same(Close):
    def agree(self, wall: Any, hand: Any, *, what: str = "") -> None:
        """La pared medida y la de la implementación independiente: las parejas, las que pasan del salto admitido y cada tramo (sus
        parejas, su altura, su inclinación, su salto y su lugar)."""
        self.assertEqual((wall.pairs, wall.over), (hand.pairs, hand.over), what)
        self.assertEqual(len(wall.stretches), len(hand.stretches), what)
        for index, (found, wanted) in enumerate(zip(wall.stretches, hand.stretches, strict=True), start=1):
            self.assertEqual((found.stretch, found.pairs), (index, wanted.pairs), what)
            for name in ("height", "angle", "step", "x", "y"):
                suffix = {"height": "_m", "angle": "_deg", "step": "_m", "x": "", "y": ""}[name]
                self.close(getattr(found, f"{name}{suffix}"), getattr(wanted, name), rel=1e-9, what=f"{what} {name}")


# --- Las cuentas a mano -----------------------------------------------------------------------------------------------


class HandCasesTest(Same):
    """RF-016-15: cada número sale de contar parejas en el papel."""

    def setUp(self) -> None:
        self.scene = column_scene()
        self.job = job_of(self.scene)
        self.natural = removal.remove_stockpile(self.job)
        self.forged = forged(self.scene, self.natural)

    def test_a_wall_at_the_edge_of_the_perimeter_is_measured_with_its_height_angle_step_and_place(self) -> None:
        """RF-016-15, error 47: con el dominio acabando en la columna 10 y la superficie sin transición, las 18 celdas de las columnas
        7 a 9 bajan a 100 m y las de 10 a 12 siguen a 104 m: 6 parejas de 4 m (4 m / 2 m = 63,43°), cuyo salto creado es 4 m (el
        terreno no tenía ninguno): **un** tramo de altura 4 m, con el lugar de su primera pareja (x = 20 m, y = −15 m de la esquina).
        Las parejas del borde son 18: esas 6 y las 12 de las celdas que se retiran con las de fuera de la huella (que ya estaban a
        100 m: su salto creado es negativo)."""
        result = measure(self.job, self.forged)
        wall = result.wall
        self.assertEqual((wall.pairs, wall.over), (18, 6))
        (item,) = wall.stretches
        self.assertEqual((item.stretch, item.pairs, item.height_m, item.step_m), (1, 6, 4.0, 4.0))
        self.close(item.angle_deg, math.degrees(math.atan2(4.0, 2.0)), rel=1e-12)
        grid = self.scene.grid
        self.close(item.x, grid.west + 20.0, rel=1e-12)
        self.close(item.y, grid.north - 15.0, rel=1e-12)
        self.assertEqual((wall.transition_deg, wall.tolerance_deg, wall.limit_deg), (ANGLE, 1.0, ANGLE + 1.0))
        self.assertEqual(wall.height_m, 4.0)
        self.assertEqual(result.wall_max_m, 4.0)
        self.assertIs(wall.worst, item)

    def test_the_wall_gives_the_notice_and_the_figure_of_the_removal(self) -> None:
        """RF-016-15, RF-016-13: el resultado lleva **un** aviso ``des.removal_wall`` (el acopio, la altura, la inclinación, el límite,
        el salto creado y el lugar, redondeados) y la cifra ``des.rmv_wall_max_m`` es la altura de la mayor pared."""
        result = measure(self.job, self.forged)
        (notice,) = [item for item in result.notices if item.code == "des.removal_wall"]
        grid = self.scene.grid
        self.assertEqual(dict(notice.values), {
            "stockpile": "Acopio de prueba", "height": 4.0, "angle": 63.43, "limit": ANGLE + 1.0, "step": 4.0,
            "x": round(grid.west + 20.0, 2), "y": round(grid.north - 15.0, 2)})
        self.assertEqual(notice.severity, "warning")
        for language in ("es", "en"):
            text = notice.text(language)
            self.assertNotIn("?", text)
            self.assertIn("4", text)
        figures = {figure.key: figure.value for figure in result.figures}
        self.assertEqual(figures["des.rmv_wall_max_m"], 4.0)

    def test_the_transition_of_the_removal_leaves_no_wall(self) -> None:
        """RF-016-15, CE-016-03: con la transición de A6 (40° con la métrica exacta), las parejas del borde quedan a ``tan · 2`` = 1,68
        m (más que el salto admitido de 1 m: hay saltos creados) y a 40°, que no pasan de 41°: ni un tramo, la cifra de la pared es 0 m
        (con la cifra presente) y el resultado sin medir sigue sin pared (``None``)."""
        result = measure(self.job, self.natural)
        wall = result.wall
        self.assertEqual(wall.stretches, ())
        self.assertGreater(wall.pairs, 0)
        self.assertGreater(wall.over, 0)
        self.assertEqual((wall.height_m, wall.worst, result.wall_max_m), (0.0, None, 0.0))
        self.assertEqual([item.code for item in result.notices if item.code == "des.removal_wall"], [])
        self.assertEqual({figure.key: figure.value for figure in result.figures}["des.rmv_wall_max_m"], 0.0)
        self.assertEqual((self.natural.wall, self.natural.wall_max_m), (None, None))

    def test_the_height_runs_along_the_face_and_is_not_the_relief_of_a_pair(self) -> None:
        """RF-016-15, error 41: con la parte del perímetro a 104 m en las filas 7 a 9 y a 103 m en las filas 10 a 12, y la columna 9
        retirada a 102 m (filas 7 a 9) y a 100 m (filas 10 a 12), las parejas son de 2 m (45°) y de 3 m (56,31°) y su salto creado, 2
        m las dos: **un** tramo (las dos mitades se tocan) de altura 104 − 100 = **4 m**, más que el relieve de cualquiera de sus
        parejas; su inclinación es la de la peor (56,31°) y su lugar, el de la primera con ella (fila 10)."""
        scene = column_scene()
        scene.z[10:13, 10:13] = 103.0
        scene.detected[:] = scene.z
        job = job_of(scene)
        outcome = removal.remove_stockpile(job)
        surface = forged(scene, outcome).surface
        surface[2:5, 4] = 102.0
        outcome = dataclasses.replace(outcome, surface=surface)
        result = measure(job, outcome)
        (item,) = result.wall.stretches
        self.assertEqual((item.pairs, item.height_m, item.step_m), (6, 4.0, 2.0))
        self.assertGreater(item.height_m, max(2.0, 3.0))
        self.close(item.angle_deg, math.degrees(math.atan2(3.0, 2.0)), rel=1e-12)
        self.close(item.x, scene.grid.west + 20.0, rel=1e-12)
        self.close(item.y, scene.grid.north - 21.0, rel=1e-12)
        self.agree(result.wall, hand_of(scene, outcome))

    def test_the_limit_is_the_transition_angle_plus_the_face_tolerance(self) -> None:
        """RF-016-15, RF-013: una pared de 1,70 m sobre 2 m (40,36°) no pasa de 40° + 1° pero sí de 40° + 0°; una de 1,75 m (41,19°)
        pasa de 41°; una de 1,65 m (39,52°), de 40° no pasa. Con el salto de 1,70 m creado mayor que el admitido de 1 m."""
        for drop, tolerance, warned in ((1.70, 1.0, False), (1.75, 1.0, True), (1.70, 0.0, True), (1.65, 0.0, False)):
            with self.subTest(drop=drop, tolerance=tolerance):
                result = measure(self.job, level_of(self.natural, 104.0 - drop), tolerance=tolerance)
                self.assertEqual(len(result.wall.stretches), int(warned))
                self.assertEqual(result.wall.over, 6)
                self.close(result.wall_max_m, drop if warned else 0.0, rel=1e-9)

    def test_the_boundary_is_strict_and_a_roundoff_does_not_warn(self) -> None:
        """RF-016-15: «más empinada» es estricto: con la pared exactamente a 45° y el límite en 45° (transición 44° + tolerancia 1°)
        no se avisa, aunque el redondeo de la tangente la deje una millonésima por encima; con 44,9° + 0,0°, sí."""
        scene = column_scene(step=3.0, height=3.0)
        job = job_of(scene, angle=44.0)
        outcome = forged(scene, removal.remove_stockpile(job))
        self.assertEqual(len(measure(job, outcome, tolerance=1.0).wall.stretches), 0)
        self.assertEqual(len(measure(job, outcome, tolerance=0.0).wall.stretches), 1)
        job = job_of(scene, angle=45.0)
        self.assertEqual(len(measure(job, forged(scene, removal.remove_stockpile(job)), tolerance=0.0).wall.stretches), 0)
        for angle in (20.0, 33.3, 40.0, 57.0):
            drop = 2.0 * math.tan(math.radians(angle))
            with self.subTest(angle=angle):
                job = job_of(column_scene(), angle=angle)
                outcome = level_of(removal.remove_stockpile(job), 104.0 - drop)
                self.assertEqual(measure(job, outcome, tolerance=0.0, jump=0.5).wall.stretches, ())

    def test_a_step_that_does_not_pass_the_admitted_jump_is_not_a_wall(self) -> None:
        """RF-016-15, RF-014-20: una pared de 0,8 m sobre celdas de 0,5 m (58°) es más empinada que el límite pero su salto creado
        (0,8 m) no pasa del admitido de 1 m: no hay tramo; con el salto admitido de 0,5 m, sí."""
        scene = column_scene(step=0.5, height=0.8)
        job = job_of(scene)
        outcome = forged(scene, removal.remove_stockpile(job))
        quiet = measure(job, outcome).wall
        self.assertEqual((quiet.stretches, quiet.over), ((), 0))
        loud = measure(job, outcome, jump=0.5).wall
        self.assertEqual((len(loud.stretches), loud.over), (1, 6))

    def test_what_the_terrain_already_had_is_not_a_wall_created_by_the_removal(self) -> None:
        """RF-016-15, RF-014-20: con el bloque a 108 m y la parte del perímetro ya cortada a 100 m, retirar el resto a 104 m deja una
        pared de 4 m a 63°, pero el terreno ya tenía una de 8 m: su salto creado es 4 − 8 < 0 y no cuenta (como en la 014)."""
        scene = column_scene(height=8.0)
        scene.z[7:13, 10:13] = 100.0
        scene.detected[:] = scene.z
        job = job_of(scene)
        outcome = level_of(removal.remove_stockpile(job), 104.0)
        wall = measure(job, outcome).wall
        self.assertEqual((wall.pairs, wall.over, wall.stretches), (18, 0, ()))

    def test_a_wall_only_counts_where_the_removal_moved_a_cell(self) -> None:
        """RF-016-15: una celda que la superficie no mueve más del espesor mínimo de la 012 no es movida: con la pared de 4 m y un
        espesor mínimo de 5 m, nada se mueve y no hay parejas; con el de 0,01 m (el de las pruebas), 18."""
        self.assertEqual(measure(self.job, self.forged, thickness=5.0).wall.pairs, 0)
        self.assertEqual(measure(self.job, self.forged).wall.pairs, 18)

    def test_two_walls_are_two_stretches_numbered_in_reading_order(self) -> None:
        """RF-016-15: con dos huecos del dominio dentro del bloque (el nordeste, filas 7 y 8 de las columnas 11 y 12, y el sudoeste,
        filas 11 y 12 de las columnas 7 y 8), la superficie sin transición deja dos paredes de 4 m que no se tocan: dos tramos de 4
        parejas, el 1 al norte y el 2 al sur; ``wall_max_m`` es la mayor altura y el aviso enseña uno solo."""
        scene = column_scene(held_from=None)
        scene.domain[7:9, 11:13] = False
        scene.domain[11:13, 7:9] = False
        job = job_of(scene)
        outcome = forged(scene, removal.remove_stockpile(job))
        result = measure(job, outcome)
        first, second = result.wall.stretches
        self.assertEqual((first.stretch, first.pairs, first.height_m), (1, 4, 4.0))
        self.assertEqual((second.stretch, second.pairs, second.height_m), (2, 4, 4.0))
        self.assertGreater(first.y, second.y)
        self.assertEqual(result.wall_max_m, 4.0)
        self.assertEqual(len([item for item in result.notices if item.code == "des.removal_wall"]), 1)
        self.agree(result.wall, hand_of(scene, outcome))

    def test_what_the_removal_does_not_admit_is_never_a_moved_cell(self) -> None:
        """RF-016-15, RF-016-11: lo movido es lo que la retirada admite: aunque la superficie baje además una celda que el dominio no
        deja retirar (la columna 10, a 102 m), esa celda no es movida: la pared de 2 m (45°) queda en la cara de la columna 9 con la
        10 (x = 20 m), no en la de la 10 con la 11 (x = 22 m)."""
        surface = forged(self.scene, self.natural).surface.copy()
        surface[2:8, 5] = 102.0  # la columna 10 de la rejilla entera, en las coordenadas de la ventana (que empieza en 5)
        result = measure(self.job, dataclasses.replace(self.natural, surface=surface))
        (item,) = result.wall.stretches
        self.assertEqual((item.pairs, item.height_m, item.step_m), (6, 2.0, 2.0))
        self.close(item.x, self.scene.grid.west + 20.0, rel=1e-12)

    def test_the_cells_without_data_make_no_pair(self) -> None:
        """RF-016-15: una pareja con una celda sin dato no se mide: con la celda (9, 10) de la cara del perímetro sin dato, esa
        pareja desaparece (17 parejas del borde y 5 con salto creado) y los 5 quedan en dos tramos (de 2 y 3 parejas: la fila 9 los
        separa), cada uno de 4 m."""
        scene = column_scene()
        scene.z[9, 10] = np.nan
        job = job_of(scene)
        outcome = forged(scene, removal.remove_stockpile(job))
        result = measure(job, outcome)
        self.assertEqual((result.wall.pairs, result.wall.over), (17, 5))
        self.assertEqual([(item.pairs, item.height_m) for item in result.wall.stretches], [(2, 4.0), (3, 4.0)])
        self.agree(result.wall, hand_of(scene, outcome))


# --- El acopio de 12 m junto a un relleno (CE-016-03; error 47) --------------------------------------------------------


class TallStockpileTest(Same):
    """RF-016-11, RF-016-13, RF-016-15, CE-016-03: el acopio de 12 m con el relleno de 3 m que pisa su pie y sale por fuera."""

    @classmethod
    def setUpClass(cls) -> None:
        case = sdata.tall_stockpile_with_fill()
        footprint = case.stockpile_height > UMBRAL
        scene = Scene(case.grid, case.start, case.base, case.base + case.stockpile_height, footprint,
                      np.ones(case.start.shape, dtype=bool))
        cls.case, cls.scene = case, scene
        cls.job = job_of(scene, angle=TALL_ANGLE)
        cls.outcome = removal.remove_stockpile(cls.job)

    def test_no_wall_around_the_footprint_passes_the_transition_angle_plus_the_tolerance(self) -> None:
        """CE-016-03: tras retirarlo, ninguna pared alrededor de la huella pasa de 35° + 1° (ni con el salto admitido casi a 0 y
        sin tolerancia: no hay una sola pareja con salto creado más empinada que 35°), la superficie no baja de la base en ninguna celda
        (CA-10) y lo retirado (del acopio y de lo apoyado) más la transición y lo no retirado es lo que había sobre la base a ≤ 10⁻⁹."""
        outcome, scene = self.outcome, self.scene
        self.assertGreater(outcome.resting_m3, 0.0)
        self.assertEqual(measure(self.job, outcome).wall.stretches, ())
        for tolerance, jump in ((1.0, 1.0), (0.001, 1e-6)):
            with self.subTest(tolerance=tolerance, jump=jump):
                wall = measure(self.job, outcome, tolerance=tolerance, jump=jump).wall
                self.assertEqual(wall.stretches, ())
                self.agree(wall, hand_of(scene, outcome, angle=TALL_ANGLE, tolerance=tolerance, jump=jump))
        sub, start = window_of(scene, outcome)
        every = oracles.hand_wall(start.tolist(), outcome.surface.tolist(), outcome.admitted.tolist(), dx=sub.dx, dy=sub.dy,
                                  west=sub.west, north=sub.north, thickness=0.01, threshold=0.0, limit_deg=TALL_ANGLE + 1e-6)
        self.assertEqual(every.stretches, ())
        self.assertGreater(every.pairs, 100)
        surface = outcome.compose(scene.z)
        inside = scene.footprint
        self.assertTrue(np.all(surface[inside] >= np.minimum(scene.z, scene.base)[inside]))
        total = math.fsum((outcome.removed_m3, outcome.resting_m3, outcome.transition_m3, outcome.kept_m3))
        self.close(total, outcome.above_base_m3, rel=1e-9)

    def test_without_the_transition_the_wall_of_error_47_is_found_and_asks_for_confirmation_and_a_reason(self) -> None:
        """RF-016-15, error 47: con la superficie sin transición (la huella a su base), el relleno que sale de ella deja una pared de
        3 m (118 m sobre 115 m) a 71,57° en las 40 parejas de su cara: **un** tramo; avisa, no se crea sin confirmación y, por ser de
        más de 45° y de 3 m, tampoco sin un motivo."""
        outcome = forged(self.scene, self.outcome)
        result = measure(self.job, outcome)
        (item,) = result.wall.stretches
        self.assertEqual((item.pairs, item.height_m, item.step_m), (40, 3.0, 3.0))
        self.close(item.angle_deg, math.degrees(math.atan2(3.0, 1.0)), rel=1e-12)
        self.agree(result.wall, hand_of(self.scene, outcome, angle=TALL_ANGLE))
        with self.assertRaises(DesignError) as caught:
            removal.check_wall_confirmed("Acopio de 12 m", result.wall, confirmed=False, reason="Se retira todo")
        self.assertEqual(caught.exception.code, "des.removal_wall_unconfirmed")
        with self.assertRaises(DesignError) as caught:
            removal.check_wall_confirmed("Acopio de 12 m", result.wall, confirmed=True)
        self.assertEqual(caught.exception.code, "des.removal_wall_reason")
        removal.check_wall_confirmed("Acopio de 12 m", result.wall, confirmed=True, reason="Relleno apoyado a conservar")


# --- El ruido ---------------------------------------------------------------------------------------------------------------


class NoiseTest(Same):
    """RF-016-15, plan 016 §8: el terreno con ruido de 5 cm no da falsos avisos."""

    @staticmethod
    def noisy(step: float, height: float, seed: int) -> Scene:
        scene = column_scene(step=step, height=height)
        scene.z += np.random.default_rng(seed).uniform(-0.05, 0.05, scene.z.shape)
        scene.detected[:] = scene.z
        return scene

    def test_the_removal_on_a_noisy_terrain_has_no_false_wall(self) -> None:
        """RF-016-15: con celdas de 2 m y de 0,5 m (donde 5 cm de ruido son hasta 11° de pendiente local) y el bloque con el perímetro
        cruzándolo, la retirada de A6 no deja ningún tramo ni con el salto admitido casi a 0 y la tolerancia 0,001°: las parejas del
        borde (que hay) nunca pasan del ángulo de la transición, porque la semilla más alta solo sube la envolvente."""
        for step in (2.0, 0.5):
            for seed in range(3):
                with self.subTest(step=step, seed=seed):
                    scene = self.noisy(step, 4.0, seed)
                    job = job_of(scene, angle=35.0)
                    outcome = removal.remove_stockpile(job)
                    wall = measure(job, outcome, tolerance=0.001, jump=1e-6).wall
                    self.assertEqual(wall.stretches, ())
                    self.assertGreater(wall.over, 0)
                    self.assertEqual(measure(job, outcome).wall.stretches, ())

    def test_a_low_step_on_a_noisy_terrain_is_not_a_wall_and_a_high_one_is(self) -> None:
        """RF-016-15: sin transición y con 5 cm de ruido, una pared de 0,8 m sobre celdas de 0,5 m no pasa del salto admitido de 1 m
        (0,8 ± 0,1 m); una de 4 m sí, con la altura del bloque ± el ruido."""
        low = self.noisy(0.5, 0.8, 5)
        job = job_of(low)
        self.assertEqual(measure(job, forged(low, removal.remove_stockpile(job))).wall.stretches, ())
        high = self.noisy(0.5, 4.0, 6)
        job = job_of(high)
        outcome = forged(high, removal.remove_stockpile(job))
        (item,) = measure(job, outcome).wall.stretches
        self.assertAlmostEqual(item.height_m, 4.0, delta=0.11)
        self.agree(measure(job, outcome).wall, hand_of(high, outcome))


# --- La implementación independiente ---------------------------------------------------------------------------------------


class OracleTest(Same):
    """RF-016-15: la pared de la retirada de A6 y la de la superficie sin transición, en escenas con relieve, celdas sin dato y
    un dominio recortado, iguales a :func:`oracles.hand_wall`; y lo que mide es lo que ``edges.created_steps`` (la 014) da."""

    CASES = tuple((seed, metric, angle, mesh)
                  for seed in range(8) for metric in ("exact", "chamfer5")
                  for angle, mesh in ((25.0, 1.0), (40.0, 0.93), (55.0, 0.6)))
    OPTIONS = ((1.0, 1.0), (0.0, 0.2), (3.0, 0.05))

    def test_the_wall_of_the_forged_surface_is_the_independent_calculation(self) -> None:
        """Con la superficie sin transición, los tramos, sus parejas, su altura, su inclinación, su salto creado y su lugar iguales a
        la implementación independiente con varias tolerancias y saltos admitidos; y en conjunto hay tramos (las escenas no son
        triviales)."""
        stretches = 0
        for seed, metric, angle, mesh in self.CASES:
            scene = random_scene(seed)
            job = job_of(scene, angle=angle, mesh=mesh, metric=metric)
            outcome = forged(scene, removal.remove_stockpile(job))
            for tolerance, jump in self.OPTIONS:
                with self.subTest(seed=seed, metric=metric, angle=angle, tolerance=tolerance, jump=jump):
                    wall = measure(job, outcome, tolerance=tolerance, jump=jump).wall
                    self.agree(wall, hand_of(scene, outcome, angle=angle, tolerance=tolerance, jump=jump))
                    stretches += len(wall.stretches)
        self.assertGreater(stretches, 20)

    def test_the_transition_of_the_removal_leaves_no_wall_in_any_scene(self) -> None:
        """RF-016-11, RF-016-15, CE-016-03: con la retirada de A6, con las dos métricas y cualquier ángulo y factor de malla, ninguna
        pareja creada pasa del ángulo de transición (con la tolerancia a 0,001° y el salto admitido casi a 0) y la implementación
        independiente da lo mismo: las parejas hay (no es vacío) y la pared, ninguna."""
        pairs = 0
        for seed, metric, angle, mesh in self.CASES:
            with self.subTest(seed=seed, metric=metric, angle=angle, mesh=mesh):
                scene = random_scene(seed)
                job = job_of(scene, angle=angle, mesh=mesh, metric=metric)
                outcome = removal.remove_stockpile(job)
                wall = measure(job, outcome, tolerance=0.001, jump=1e-6).wall
                self.assertEqual(wall.stretches, ())
                self.agree(wall, hand_of(scene, outcome, angle=angle, tolerance=0.001, jump=1e-6))
                pairs += wall.over
        self.assertGreater(pairs, 100)

    def test_the_pairs_and_the_created_steps_are_the_ones_of_the_014(self) -> None:
        """RF-014-20 (la 014 es lo que se reutiliza): las parejas del borde y las que pasan del salto admitido son las de
        ``edges.created_steps`` con el dominio de lo que se retira y el espesor mínimo de la 012, en la superficie sin transición y
        en la de A6; y el mayor salto creado de los tramos no pasa del suyo."""
        for seed in range(4):
            scene = random_scene(seed)
            job = job_of(scene, angle=40.0, mesh=0.93)
            natural = removal.remove_stockpile(job)
            for label, outcome in (("A6", natural), ("sin transición", forged(scene, natural))):
                with self.subTest(seed=seed, surface=label):
                    sub, start = window_of(scene, outcome)
                    last = None
                    for last in edges.created_steps(outcome.surface, start, outcome.admitted, sub, 0.01, 1.0, 99.0):
                        pass
                    report = last.result
                    wall = measure(job, outcome).wall
                    self.assertEqual((wall.pairs, wall.over), (report.pairs, report.over))
                    for item in wall.stretches:
                        self.assertLessEqual(item.step_m, report.maximum_m + 1e-12)


# --- Las confirmaciones --------------------------------------------------------------------------------------------------


class ConfirmationTest(Close):
    """RF-016-15, CA-9, D-6: sin confirmar no se crea y, con una pared de más de 45° y 3 m o más, tampoco sin un motivo."""

    @staticmethod
    def wall(step: float, height: float, *, angle: float = ANGLE) -> Any:
        """La pared de ``height`` m sobre celdas de ``step`` m (cada celda que se retira a su base, sin transición)."""
        scene = column_scene(step=step, height=height)
        job = job_of(scene, angle=angle)
        return measure(job, forged(scene, removal.remove_stockpile(job))).wall

    def test_the_two_thresholds_of_ca_9_are_named_constants_with_their_provenance(self) -> None:
        """CA-9, D-6 (decisión de la sesión principal del 18/11/2026): los 45° y los 3 m **no son parámetros** de la retirada: son
        constantes nombradas de ``design.removal`` (45° y 3 m), citadas con su procedencia en su docstring, y la pared las lleva para
        el informe."""
        self.assertEqual((removal.WALL_REASON_MIN_ANGLE_DEG, removal.WALL_REASON_MIN_HEIGHT_M), (45.0, 3.0))
        doc = " ".join((removal.__doc__ or "").split())
        for text in ("CA-9", "D-6", "WALL_REASON_MIN_ANGLE_DEG", "WALL_REASON_MIN_HEIGHT_M", "decisión de la sesión principal"):
            self.assertIn(text, doc)
        wall = self.wall(2.0, 4.0)
        self.assertEqual((wall.reason_min_angle_deg, wall.reason_min_height_m), (45.0, 3.0))

    def test_without_a_wall_nothing_is_asked(self) -> None:
        """RF-016-15: sin ninguna pared, ni confirmación ni motivo, y ningún aviso."""
        scene = column_scene()
        job = job_of(scene)
        wall = measure(job, removal.remove_stockpile(job)).wall
        removal.check_wall_confirmed("Acopio", wall, confirmed=False)
        removal.check_wall_confirmed("Acopio", wall, confirmed=False, reason=None)
        self.assertEqual(removal.wall_notices("Acopio", wall), ())
        self.assertFalse(wall.needs_confirmation)
        self.assertFalse(wall.needs_reason)

    def test_a_wall_is_not_created_without_the_express_confirmation(self) -> None:
        """RF-016-15: con una pared (4 m a 63°) y sin confirmar, ``des.removal_wall_unconfirmed`` con el acopio, la altura y la
        inclinación (nada se crea); un motivo no hace las veces de la confirmación."""
        wall = self.wall(2.0, 4.0)
        self.assertTrue(wall.needs_confirmation)
        for reason in (None, "Zona de restauración"):
            with self.subTest(reason=reason), self.assertRaises(DesignError) as caught:
                removal.check_wall_confirmed("Acopio de prueba", wall, confirmed=False, reason=reason)
            error = caught.exception
            self.assertEqual(error.code, "des.removal_wall_unconfirmed")
            self.assertEqual((error.values["stockpile"], error.values["height"]), ("Acopio de prueba", 4.0))
            self.assertAlmostEqual(error.values["angle"], 63.43, delta=0.01)
            self.assertIn("Acopio de prueba", error.text)
            self.assertNotIn("?", error.text)

    def test_over_45_degrees_and_3_m_a_recorded_reason_is_also_needed(self) -> None:
        """RF-016-15, CA-9: confirmada una pared de 4 m a 63° sin motivo (o con uno en blanco), ``des.removal_wall_reason`` con la
        altura, la inclinación y los dos umbrales (45° y 3 m); con un motivo, se puede crear."""
        wall = self.wall(2.0, 4.0)
        self.assertTrue(wall.needs_reason)
        for reason in (None, "", "   "):
            with self.subTest(reason=reason), self.assertRaises(DesignError) as caught:
                removal.check_wall_confirmed("Acopio de prueba", wall, confirmed=True, reason=reason)
            error = caught.exception
            self.assertEqual(error.code, "des.removal_wall_reason")
            self.assertEqual((error.values["min_angle"], error.values["min_height"], error.values["height"]), (45.0, 3.0, 4.0))
            self.assertNotIn("?", error.text)
        removal.check_wall_confirmed("Acopio de prueba", wall, confirmed=True, reason="Se conserva para el relleno de la fase 2")

    def test_the_exact_limits_of_the_reason(self) -> None:
        """CA-9: el motivo hace falta con **más** de 45° y con 3 m **o más**: una pared de 3,9 m a 44,3° (celdas de 4 m), una de 3
        m a exactamente 45° (celdas de 3 m) y una de 2,999 m a 56° no lo piden; una de 3 m a 56° (celdas de 2 m) y una de 3,0001 m a
        45,002° (celdas de 3 m) sí. Las cinco piden la confirmación."""
        cases = ((4.0, 3.9, False), (3.0, 3.0, False), (2.0, 2.999, False), (2.0, 3.0, True), (3.0, 3.0001, True))
        for step, height, needs in cases:
            with self.subTest(step=step, height=height):
                wall = self.wall(step, height)
                self.assertEqual(len(wall.stretches), 1)
                self.assertTrue(wall.needs_confirmation)
                self.assertEqual(wall.needs_reason, needs)
                if needs:
                    with self.assertRaises(DesignError) as caught:
                        removal.check_wall_confirmed("A", wall, confirmed=True)
                    self.assertEqual(caught.exception.code, "des.removal_wall_reason")
                else:
                    removal.check_wall_confirmed("A", wall, confirmed=True)

    def test_the_reason_asks_for_any_of_the_walls_and_the_notice_shows_the_highest(self) -> None:
        """RF-016-15: con dos paredes, una alta pero tendida (≤ 45°) y otra más empinada de menos de 3 m, ninguna pide motivo; con una
        que cumple las dos condiciones, se pide aunque no sea la más alta, y el aviso enseña la más alta."""
        scene = column_scene(step=4.0, height=4.0)
        job = job_of(scene, angle=30.0)
        outcome = removal.remove_stockpile(job)
        surface = np.where(outcome.admitted, 100.0, scene.z[outcome.window])
        wall = measure(job, dataclasses.replace(outcome, surface=surface)).wall
        self.assertEqual((len(wall.stretches), wall.needs_reason), (1, False))
        self.assertEqual(wall.worst.height_m, 4.0)
        wide = dataclasses.replace(wall, stretches=(
            dataclasses.replace(wall.stretches[0], stretch=1, height_m=3.9, angle_deg=44.0),
            dataclasses.replace(wall.stretches[0], stretch=2, height_m=3.0, angle_deg=60.0)))
        self.assertTrue(wide.needs_reason)
        self.assertEqual((wide.worst.stretch, wide.reason_stretch.stretch), (1, 2))
        level = dataclasses.replace(wall, stretches=(
            dataclasses.replace(wall.stretches[0], stretch=1, height_m=4.0, angle_deg=50.0),
            dataclasses.replace(wall.stretches[0], stretch=2, height_m=4.0, angle_deg=70.0),
            dataclasses.replace(wall.stretches[0], stretch=3, height_m=4.0, angle_deg=70.0)))
        self.assertEqual((level.worst.stretch, level.reason_stretch.stretch), (2, 2))  # a igual altura, el más empinado; luego, el primero
        with self.assertRaises(DesignError) as caught:
            removal.check_wall_confirmed("A", wide, confirmed=True)
        self.assertEqual((caught.exception.values["height"], caught.exception.values["angle"]), (3.0, 60.0))
        (notice,) = removal.wall_notices("A", wide)
        self.assertEqual((notice.values["height"], notice.values["angle"]), (3.9, 44.0))

    def test_the_notice_names_the_stockpile_and_keeps_the_notices_that_were_there(self) -> None:
        """RF-016-13, RF-016-15: ``measure_wall`` suma el aviso de la pared a los que el resultado ya llevaba (el de «0 m³» de
        RF-016-13) sin quitar ninguno, y no cambia el resultado que recibe."""
        scene = column_scene()
        job = job_of(scene)
        natural = removal.remove_stockpile(job)
        nothing = preview.Notice("des.removal_nothing", {"stockpile": "Acopio de prueba"})
        outcome = dataclasses.replace(forged(scene, natural), notices=(nothing,))
        result = measure(job, outcome)
        self.assertEqual([item.code for item in result.notices], ["des.removal_nothing", "des.removal_wall"])
        self.assertEqual(outcome.notices, (nothing,))
        self.assertIsNone(outcome.wall)
        self.assertEqual(removal.wall_notices("Acopio de prueba", result.wall), result.notices[1:])


# --- Los pasos, la entrada y los rechazos -------------------------------------------------------------------------------


class StepsTest(Same):
    """RNF-016-03: por pasos, cancelable, sin tocar la entrada, con sus rechazos."""

    def test_the_steps_end_with_the_outcome_and_match_the_one_shot_call(self) -> None:
        """``wall_steps`` da ``Progress`` de la fase ``removal_wall``; solo el último lleva el resultado y es el de ``measure_wall``;
        con un presupuesto de 0 s, cada unidad es un paso."""
        scene = random_scene(1)
        job = job_of(scene, angle=40.0, mesh=0.93)
        outcome = forged(scene, removal.remove_stockpile(job))
        steps = list(removal.wall_steps(job, outcome, project(tolerance=0.0, jump=0.2), budget_s=0.0))
        self.assertGreater(len(steps), 2)
        self.assertTrue(all(step.phase == "removal_wall" for step in steps))
        self.assertTrue(all(step.result is None for step in steps[:-1]))
        self.assertEqual([step.done for step in steps[:-1]], list(range(1, len(steps))))
        last = steps[-1].result
        self.assertIsInstance(last, removal.RemovalOutcome)
        once = measure(job, outcome, tolerance=0.0, jump=0.2)
        self.assertEqual(last.wall_max_m, once.wall_max_m)
        self.assertEqual(last.wall.stretches, once.wall.stretches)
        self.assertGreater(len(last.wall.stretches), 0)
        self.assertTrue(np.array_equal(last.surface, once.surface, equal_nan=True))

    def test_closing_half_way_leaves_nothing_and_no_input_changes(self) -> None:
        """Cerrar el generador a mitad no deja nada y ni el trabajo, ni el resultado (que no gana ninguna pared), ni los
        parámetros del proyecto se modifican (también al terminar)."""
        scene = random_scene(2)
        job = job_of(scene, mesh=0.93)
        outcome = forged(scene, removal.remove_stockpile(job))
        settings = project(tolerance=0.0)
        before = (outcome.surface.copy(), outcome.admitted.copy(), outcome.held.copy(), job.start.copy(), job.domain.copy(),
                  copy.deepcopy(settings), outcome.notices)
        steps = removal.wall_steps(job, outcome, settings, budget_s=0.0)
        next(steps)
        steps.close()
        removal.measure_wall(job, outcome, settings)
        after = (outcome.surface, outcome.admitted, outcome.held, job.start, job.domain, settings, outcome.notices)
        for found, wanted in zip(after, before, strict=True):
            if isinstance(wanted, np.ndarray):
                self.assertTrue(np.array_equal(found, wanted, equal_nan=True))
            else:
                self.assertEqual(found, wanted)
        self.assertEqual((outcome.wall, outcome.wall_max_m), (None, None))

    def test_each_step_takes_at_most_two_tenths_of_a_second(self) -> None:
        """RNF-016-03: en una ventana de ≈ 34.000 celdas (184 × 184), con la pared de 4 m de todo el borde del perímetro, cada llamada
        del hilo de Blender (cada paso con el presupuesto de 50 ms) tarda ≤ 0,2 s."""
        n = 200
        scene = column_scene(n=n, height=4.0, held_from=100)
        scene.footprint[:] = False
        scene.footprint[10:190, 10:190] = True
        scene.z[:] = 100.0
        scene.z[scene.footprint] = 104.0
        scene.detected[:] = scene.z
        job = job_of(scene)
        outcome = forged(scene, removal.remove_stockpile(job))
        steps = removal.wall_steps(job, outcome, project(), budget_s=0.05)
        worst = 0.0
        with closing(steps):
            while True:
                began = time.perf_counter()
                step = next(steps)
                worst = max(worst, time.perf_counter() - began)
                if step.result is not None:
                    break
        self.assertLessEqual(worst, 0.2)
        self.assertEqual(step.result.wall.stretches[0].pairs, 180)

    def test_the_project_values_are_checked(self) -> None:
        """RF-015-08: sin la tolerancia de cara, el espesor mínimo o el salto admitido, o con uno que no es un número finito, o una
        tolerancia o un espesor negativos, ``ValueError`` (errores del programa: quien llama los lee del proyecto); un salto admitido
        fuera de su rango, ``des.quarry_param_range``."""
        scene = column_scene()
        job = job_of(scene)
        outcome = forged(scene, removal.remove_stockpile(job))
        for key in (TOLERANCE_KEY, THICKNESS_KEY, JUMP_KEY):
            with self.subTest(missing=key), self.assertRaises(ValueError) as caught:
                removal.measure_wall(job, outcome, {k: v for k, v in project().items() if k != key})
            self.assertIn(key, str(caught.exception))
        for options in ({"tolerance": -0.5}, {"tolerance": math.nan}, {"thickness": -1.0}, {"thickness": math.inf}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                measure(job, outcome, **options)
        for jump in (0.0, -1.0, 1000.0):
            with self.subTest(jump=jump), self.assertRaises(DesignError) as caught:
                measure(job, outcome, jump=jump)
            self.assertEqual(caught.exception.code, "des.quarry_param_range")

    def test_an_outcome_that_is_not_of_the_job_is_a_program_error(self) -> None:
        """Errores del programa (``ValueError``): un resultado de otra retirada (otro código o acopio), de otra ventana que la que
        leyó el trabajo o con una superficie de otra forma."""
        scene = column_scene()
        job = job_of(scene)
        outcome = removal.remove_stockpile(job)
        for changes in ({"code": "RMV-002"}, {"stockpile": "m02"}, {"surface": np.zeros((3, 3))},
                        {"window": (slice(0, 5), slice(0, 5))}):
            with self.subTest(changes=list(changes)), self.assertRaises(ValueError):
                measure(job, dataclasses.replace(outcome, **changes))
        small = job_of(scene, region=removal.removal_window(job.stockpile, job.grid))
        self.assertEqual(measure(small, outcome).wall.stretches, ())
        shifted = dataclasses.replace(outcome, window=(slice(0, outcome.surface.shape[0]), slice(0, outcome.surface.shape[1])))
        with self.assertRaises(ValueError):
            measure(small, shifted)


if __name__ == "__main__":
    unittest.main()

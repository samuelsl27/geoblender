# SPDX-License-Identifier: GPL-3.0-or-later
"""Aplicar la plataforma sobre su superficie de partida (spec 015, T07; RF-015-20, RF-015-21,
RF-015-06 y RF-015-13; plan 015 §5.4, A2; CE-015-02 y B7).

Las cuentas están hechas a mano y se comparan a ≤ 10⁻⁹ m o relativo (D-9):

- **La franja de CE-015-02** (``entity_fixtures.strip_case``: eje de 200 m, 40 m de ancho, 1 % desde
  230 m; el terreno queda 6 m por encima de la rasante salvo en un tramo de 40 × 40 celdas que queda
  **5 m por debajo**): en el modo «en corte» baja 6 m en 6.400 celdas (38.400 m³), **no sube ninguna**
  (0 m³ de relleno: el lomo de B7) y el tramo bajo la rasante queda como estaba, en un grupo de
  1.600 celdas con su lugar; en «en corte y relleno» sube además 5 m en las 1.600 celdas (8.000 m³).
  Con el intocable (una banda de 10 × 60 celdas que cruza la huella: 400 celdas dentro de ella) esas
  celdas no se mueven y suman al aviso con su área, su lugar y la máscara que lo impide.
- **Una rejilla de 2 × 3 m**, con la huella dibujada a mano, para el área de la celda, los grupos
  4-conexos (dos celdas en diagonal son dos grupos), su orden y su centro absoluto.
- **Propiedades** con un terreno al azar, máscaras al azar y celdas sin dato fuera de la huella:
  en «en corte» ``z' ≤ z`` en todas partes; fuera de la huella no cambia nada; los volúmenes son los
  de una suma celda a celda; ninguna entrada se modifica.
"""

from __future__ import annotations

import dataclasses
import math
import unittest
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import entity_fixtures as efx
from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender

platform = import_geoblender("design.platform")
model = import_geoblender("design.model")
messages = import_geoblender("design.messages")
gis = import_geoblender("gis")

DesignError = messages.DesignError
GRID = efx.GRID
X, _Y = qfx.local_centers(GRID)
"""Los centros de celda de la cantera (locales, m desde ``BASE``), de forma ``GRID.shape``."""
TOL = 1e-9
"""La tolerancia de las cuentas a mano (D-9)."""


# --- Lo que construyen las pruebas -------------------------------------------------------------


def request(name: str = "Franja") -> Any:
    return model.PlatformRequest(
        name=name, feature=name, start="Terreno",
        fields=model.PlatformFields(layer=efx.AXES_LAYER, start_level_field="cota_inicial",
                                    gradient_field="pendiente", width_field="ancho"))


def strip_job(case: Any, mode: Any = "cut", *, cut_allowed: np.ndarray | None = None,
              fill_allowed: np.ndarray | None = None, start: np.ndarray | None = None,
              reach_m: float = 30.0) -> Any:
    """El trabajo de la franja de ``case`` en el ``mode`` (``None``: sin el valor ``mode``, que lleva
    el de por defecto)."""
    parameters: dict[str, object] = {
        "width_m": case.width_m, "start_level_m": case.grade_start_m, "gradient_pct": case.slope_pct,
        "reach_m": reach_m}
    if mode is not None:
        parameters["mode"] = mode
    return platform.PlatformJob(
        request(), "PLT-001", case.grid, case.terrain if start is None else start,
        platform.PlatformGeometry("line", ((case.axis,),)), parameters,
        case.cut_allowed if cut_allowed is None else cut_allowed,
        case.fill_allowed if fill_allowed is None else fill_allowed)


def run(job: Any) -> tuple[Any, Any]:
    """La huella del trabajo y la plataforma aplicada."""
    footprint = platform.platform_footprint(job)
    return footprint, platform.apply_platform(job, footprint)


def in_window(footprint: Any, array: np.ndarray) -> np.ndarray:
    """``array`` (de la rejilla entera) en la ventana de trabajo de la huella."""
    return array[footprint.window]


def centre(x: float, y: float) -> tuple[float, float]:
    """El punto local (m desde ``BASE``) en coordenadas absolutas."""
    point = cfx.absolute([(x, y)])[0]
    return float(point[0]), float(point[1])


def box(*bounds: float) -> np.ndarray:
    """Las celdas de la rejilla de la cantera con el centro dentro de la caja local."""
    return qfx.in_box(tuple(bounds))  # type: ignore[arg-type]


# --- Lo público --------------------------------------------------------------------------------


class PublicNamesTest(unittest.TestCase):
    """RF-015-20: lo que entrega esta tarea es público y está documentado."""

    def test_the_module_publishes_what_the_edge_and_the_figures_need(self) -> None:
        """``design.platform`` exporta la aplicación, sus pasos y sus datos, cada uno con su
        documentación."""
        names = ("Applied", "OffLevel", "OffLevelCause", "apply_platform", "apply_platform_steps")
        for name in names:
            with self.subTest(name=name):
                self.assertIn(name, platform.__all__)
                self.assertTrue(getattr(platform, name).__doc__.strip())

    def test_the_causes_name_the_mask_that_does_not_allow(self) -> None:
        """RF-015-13: la causa de lo que no se mueve es la máscara que lo impide (``cut_allowed`` o
        ``fill_allowed``) o, por debajo en «en corte», que ese modo no rellena."""
        self.assertEqual({cause.value for cause in platform.OffLevelCause},
                         {"cut_allowed", "fill_allowed", "cut_mode"})


# --- El modo «en corte»: el lomo de B7 ---------------------------------------------------------


class CutModeTest(unittest.TestCase):
    """RF-015-20, CE-015-02 (B7): «en corte» baja a la rasante y no sube ninguna celda."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.case = efx.strip_case()
        cls.job = strip_job(cls.case, "cut")
        cls.footprint, cls.applied = run(cls.job)
        cls.cells = cls.footprint.cells
        cls.z = in_window(cls.footprint, cls.case.terrain)
        cls.hollow = in_window(cls.footprint, cls.case.hollow)

    def test_the_footprint_is_the_strip_of_the_fixture(self) -> None:
        """La huella de la franja son las 8.000 celdas de 200 × 40 m de la fixture."""
        np.testing.assert_array_equal(self.cells, in_window(self.footprint, self.case.footprint))
        self.assertEqual(self.footprint.cell_count, 8000)

    def test_nothing_is_filled_over_the_hollow(self) -> None:
        """RF-015-20, B7: sobre un terreno con un tramo 5 m por debajo de la rasante, 0 m³ de
        relleno: el tramo queda como estaba (la plataforma es el fondo de su corredor, no una cota
        mínima)."""
        self.assertEqual(self.applied.fill_m3, 0.0)
        self.assertEqual(self.applied.fill_cells, 0)
        np.testing.assert_array_equal(self.applied.surface[self.hollow], self.z[self.hollow])

    def test_the_cut_is_6_m_over_the_6400_cells_above_the_grade(self) -> None:
        """CE-015-02 a mano: 6 m × (8.000 − 1.600) celdas de 1 m² = 38.400 m³, a ≤ 10⁻⁹ relativo."""
        self.assertEqual(self.applied.cut_cells, 6400)
        self.assertAlmostEqual(self.applied.cut_m3 / (6.0 * 6400.0), 1.0, delta=TOL)
        self.assertAlmostEqual(self.applied.cut_m3 / efx.STRIP_CUT_M3, 1.0, delta=TOL)

    def test_the_cells_above_go_down_to_the_grade_to_1e_9(self) -> None:
        """RF-015-20: cada celda de la huella por encima de la rasante queda en ella (la de la
        fixture, ``230 + σ · 0,01`` a mano), a ≤ 10⁻⁹ m."""
        above = self.cells & ~self.hollow
        grade = in_window(self.footprint, self.case.grade)
        np.testing.assert_allclose(self.applied.surface[above], grade[above], rtol=0, atol=TOL)
        first = above & (in_window(self.footprint, X) == 100.5)
        self.assertAlmostEqual(float(self.applied.surface[first].max()), 230.005, delta=TOL)
        self.assertAlmostEqual(float(self.applied.surface[first].min()), 230.005, delta=TOL)

    def test_nothing_rises_and_nothing_outside_the_footprint_changes(self) -> None:
        """RF-015-20: ``z' ≤ z`` en toda la ventana y, fuera de la huella, la superficie es la de
        partida bit a bit."""
        self.assertTrue(np.all(self.applied.surface <= self.z))
        np.testing.assert_array_equal(self.applied.surface[~self.cells], self.z[~self.cells])
        self.assertEqual(self.applied.surface.shape, self.cells.shape)
        self.assertEqual(self.applied.surface.dtype, np.float64)

    def test_the_cells_at_the_grade_are_the_seeds_of_the_edge(self) -> None:
        """RF-015-20 y RF-015-22: ``at_level`` marca las celdas de la huella que quedan en la
        rasante (a 10⁻⁹ m): las 6.400 cortadas, no las 1.600 del tramo bajo."""
        np.testing.assert_array_equal(self.applied.at_level, self.cells & ~self.hollow)
        self.assertEqual(self.applied.at_level.dtype, np.bool_)

    def test_the_hollow_is_one_group_below_the_grade_with_its_place(self) -> None:
        """RF-015-24 (la parte que ya se da): el tramo bajo la rasante, en «en corte», es un
        grupo de 1.600 celdas y 1.600 m², hasta 5 m por debajo, con el centro de la caja (200, 200)
        en coordenadas absolutas y por causa el modo; por encima, ninguno."""
        self.assertEqual(self.applied.above, ())
        (group,) = self.applied.below
        self.assertEqual((group.group, group.cells), (1, 1600))
        self.assertAlmostEqual(group.area_m2, 1600.0, delta=TOL)
        self.assertAlmostEqual(group.max_m, 5.0, delta=TOL)
        self.assertEqual(group.cause, platform.OffLevelCause.NOT_FILLED)
        x, y = centre(200.0, 200.0)
        self.assertAlmostEqual(group.x, x, delta=TOL)
        self.assertAlmostEqual(group.y, y, delta=TOL)

    def test_no_mask_stops_anything(self) -> None:
        """RF-015-13: sin restricciones en la huella, nada queda sin mover por una máscara."""
        self.assertEqual(self.applied.blocked_area_m2, 0.0)
        self.assertFalse(self.applied.cut_denied.any())
        self.assertFalse(self.applied.fill_denied.any())

    def test_the_applied_surface_is_new_and_the_input_is_not_modified(self) -> None:
        """Principio 7: la superficie de partida, las máscaras y la rasante quedan como estaban y
        el resultado no es una vista de ellas."""
        case = efx.strip_case()
        job = strip_job(case)
        start, cut, fill = job.start.copy(), job.cut_allowed.copy(), job.fill_allowed.copy()
        footprint = platform.platform_footprint(job)
        levels = footprint.levels.copy()
        applied = platform.apply_platform(job, footprint)
        np.testing.assert_array_equal(start, job.start)
        np.testing.assert_array_equal(cut, job.cut_allowed)
        np.testing.assert_array_equal(fill, job.fill_allowed)
        np.testing.assert_array_equal(levels, footprint.levels, strict=True)
        self.assertFalse(np.shares_memory(applied.surface, job.start))
        applied.surface[:] = 0.0
        np.testing.assert_array_equal(start, job.start)


# --- El modo «en corte y relleno» --------------------------------------------------------------


class CutFillModeTest(unittest.TestCase):
    """RF-015-21: «en corte y relleno» sube además a la rasante donde el relleno se admite."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.case = efx.strip_case()
        cls.footprint, cls.applied = run(strip_job(cls.case, "cut_fill"))
        cls.cells = cls.footprint.cells
        cls.z = in_window(cls.footprint, cls.case.terrain)
        cls.hollow = in_window(cls.footprint, cls.case.hollow)

    def test_the_fill_is_5_m_over_the_1600_cells_of_the_hollow(self) -> None:
        """CE-015-02 a mano: 5 m × 1.600 celdas = 8.000 m³ de relleno exacto, y el mismo corte de
        38.400 m³."""
        self.assertEqual(self.applied.fill_cells, 1600)
        self.assertAlmostEqual(self.applied.fill_m3 / (5.0 * 1600.0), 1.0, delta=TOL)
        self.assertAlmostEqual(self.applied.fill_m3 / efx.STRIP_FILL_M3, 1.0, delta=TOL)
        self.assertAlmostEqual(self.applied.cut_m3 / efx.STRIP_CUT_M3, 1.0, delta=TOL)

    def test_the_whole_footprint_is_at_the_grade_to_1e_9(self) -> None:
        """RF-015-21: toda la huella queda en la rasante (a ≤ 10⁻⁹ m), y ``at_level`` la marca
        entera: son las semillas del borde."""
        grade = in_window(self.footprint, self.case.grade)
        np.testing.assert_allclose(self.applied.surface[self.cells], grade[self.cells], rtol=0,
                                   atol=TOL)
        np.testing.assert_array_equal(self.applied.at_level, self.cells)
        self.assertEqual((self.applied.above, self.applied.below), ((), ()))

    def test_nothing_outside_the_footprint_changes(self) -> None:
        """RF-015-21: fuera de la huella la superficie es la de partida, bit a bit."""
        np.testing.assert_array_equal(self.applied.surface[~self.cells], self.z[~self.cells])

    def test_the_mode_is_taken_as_text_or_as_enum_and_cut_is_the_default(self) -> None:
        """D-5: ``PlatformMode.CUT_FILL`` y ``"cut_fill"`` son lo mismo; sin el valor ``mode`` es
        «en corte» (el de la familia de parámetros), y un modo que no es de la lista es el rechazo
        ``des.entity_param_choice`` con la entidad, el campo y el valor."""
        case = efx.strip_case()
        enum_run = run(strip_job(case, model.PlatformMode.CUT_FILL))[1]
        self.assertEqual(enum_run.mode, model.PlatformMode.CUT_FILL)
        self.assertEqual(enum_run.fill_m3, self.applied.fill_m3)
        default = run(strip_job(case, None))[1]
        self.assertEqual(default.mode, model.PlatformMode.CUT)
        self.assertEqual(default.fill_m3, 0.0)
        job = strip_job(case, "fill")
        footprint = platform.platform_footprint(job)
        with self.assertRaises(DesignError) as caught:
            platform.apply_platform(job, footprint)
        self.assertEqual(caught.exception.code, "des.entity_param_choice")
        self.assertIn("«Franja»", caught.exception.text)
        self.assertIn("plt_001.mode", caught.exception.text)


# --- El intocable que cruza la huella -----------------------------------------------------------


class UntouchableTest(unittest.TestCase):
    """RF-015-06, RF-015-13, CE-015-02: una banda de 10 m que cruza la huella de lado a lado deja
    400 celdas sin cortar ni rellenar."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.case = efx.strip_case(untouchable=True)
        cls.cut = run(strip_job(cls.case, "cut"))
        cls.cut_fill = run(strip_job(cls.case, "cut_fill"))

    def test_the_cells_of_the_band_do_not_move_and_the_cut_is_36000(self) -> None:
        """RF-015-06: «cortar solo en el corte admitido»: las 400 celdas de la banda quedan como en
        la partida, bit a bit, y el corte es 6 m × 6.000 celdas = 36.000 m³."""
        for footprint, applied in (self.cut, self.cut_fill):
            blocked = in_window(footprint, self.case.blocked)
            z = in_window(footprint, self.case.terrain)
            self.assertEqual(int(blocked.sum()), 400)
            np.testing.assert_array_equal(applied.surface[blocked], z[blocked])
            self.assertEqual(applied.cut_cells, 6000)
            self.assertAlmostEqual(applied.cut_m3 / efx.STRIP_CUT_BLOCKED_M3, 1.0, delta=TOL)
            self.assertAlmostEqual(applied.cut_m3 / (6.0 * 6000.0), 1.0, delta=TOL)

    def test_the_blocked_cells_are_one_group_above_with_area_place_and_cause(self) -> None:
        """RF-015-13: lo que no se mueve por una máscara suma al aviso con su área (400 m²), su
        lugar (el centro de la banda dentro de la huella, (145, 200)) y la causa (``cut_allowed``
        falso), y la máscara de las celdas, lista para que se mire la zona."""
        for footprint, applied in (self.cut, self.cut_fill):
            (group,) = applied.above
            self.assertEqual((group.group, group.cells), (1, 400))
            self.assertAlmostEqual(group.area_m2, 400.0, delta=TOL)
            self.assertAlmostEqual(group.max_m, 6.0, delta=TOL)
            self.assertEqual(group.cause, platform.OffLevelCause.CUT_DENIED)
            x, y = centre(145.0, 200.0)
            self.assertAlmostEqual(group.x, x, delta=TOL)
            self.assertAlmostEqual(group.y, y, delta=TOL)
            np.testing.assert_array_equal(applied.cut_denied,
                                          in_window(footprint, self.case.blocked))
            self.assertFalse(applied.fill_denied.any())
            self.assertAlmostEqual(applied.blocked_area_m2, 400.0, delta=TOL)

    def test_the_blocked_cells_are_not_seeds_of_the_edge(self) -> None:
        """RF-015-22: ``at_level`` no incluye las celdas que no se mueven: en «en corte», 6.000
        (la huella menos el tramo bajo y la banda); en «en corte y relleno», 7.600 (la huella menos
        la banda)."""
        self.assertEqual(int(self.cut[1].at_level.sum()), 6000)
        self.assertEqual(int(self.cut_fill[1].at_level.sum()), 7600)
        blocked = in_window(self.cut[0], self.case.blocked)
        self.assertFalse((self.cut[1].at_level & blocked).any())

    def test_cut_mode_keeps_the_hollow_apart_from_what_the_mask_stops(self) -> None:
        """RF-015-13 y RF-015-24: en «en corte» el tramo bajo la rasante sigue siendo un grupo por
        debajo, pero su causa es el modo, no una máscara: no cuenta como lo que se impide mover; en
        «en corte y relleno» se rellena y no queda ninguno por debajo, y el relleno es 8.000 m³."""
        (hollow,) = self.cut[1].below
        self.assertEqual((hollow.cells, hollow.cause), (1600, platform.OffLevelCause.NOT_FILLED))
        self.assertAlmostEqual(self.cut[1].blocked_area_m2, 400.0, delta=TOL)
        self.assertEqual(self.cut_fill[1].below, ())
        self.assertAlmostEqual(self.cut_fill[1].fill_m3 / efx.STRIP_FILL_M3, 1.0, delta=TOL)
        self.assertEqual(self.cut[1].fill_m3, 0.0)


class FillDeniedTest(unittest.TestCase):
    """RF-015-06 y RF-015-13: el relleno solo donde se admite."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.case = efx.strip_case()
        cls.fill_allowed = ~box(190.0, 190.0, 200.0, 200.0)  # 10 × 10 celdas dentro del tramo bajo
        cls.cut_fill = run(strip_job(cls.case, "cut_fill", fill_allowed=cls.fill_allowed))
        cls.cut = run(strip_job(cls.case, "cut", fill_allowed=cls.fill_allowed))

    def test_the_fill_stops_where_the_mask_does_not_allow_it(self) -> None:
        """RF-015-06: 5 m × (1.600 − 100) celdas = 7.500 m³; las 100 celdas no se rellenan y
        quedan por debajo, 5 m, en un grupo de 100 m² centrado en (195, 195), con la causa
        ``fill_allowed``."""
        footprint, applied = self.cut_fill
        self.assertAlmostEqual(applied.fill_m3 / (5.0 * 1500.0), 1.0, delta=TOL)
        self.assertEqual(applied.fill_cells, 1500)
        (group,) = applied.below
        self.assertEqual((group.cells, group.cause), (100, platform.OffLevelCause.FILL_DENIED))
        self.assertAlmostEqual(group.area_m2, 100.0, delta=TOL)
        self.assertAlmostEqual(group.max_m, 5.0, delta=TOL)
        x, y = centre(195.0, 195.0)
        self.assertAlmostEqual(group.x, x, delta=TOL)
        self.assertAlmostEqual(group.y, y, delta=TOL)
        self.assertEqual(applied.above, ())
        np.testing.assert_array_equal(applied.fill_denied,
                                      in_window(footprint, ~self.fill_allowed & self.case.hollow))
        self.assertFalse(applied.cut_denied.any())
        self.assertAlmostEqual(applied.blocked_area_m2, 100.0, delta=TOL)

    def test_the_same_masks_in_cut_mode_stop_nothing(self) -> None:
        """RF-015-20: en «en corte» no se quiere rellenar, así que el que se prohíba rellenar no
        impide nada: el tramo bajo (1.600 celdas, un grupo) queda por el modo."""
        _footprint, applied = self.cut
        (group,) = applied.below
        self.assertEqual((group.cells, group.cause), (1600, platform.OffLevelCause.NOT_FILLED))
        self.assertEqual(applied.blocked_area_m2, 0.0)
        self.assertFalse(applied.fill_denied.any())
        self.assertEqual(applied.fill_m3, 0.0)


# --- Los grupos, el área de la celda y el lugar ------------------------------------------------

SMALL = gis.Grid(500_123.5, 4_400_000.25, 2.0, 3.0, 12, 10)
"""Una rejilla de 12 × 10 celdas de 2 × 3 m (6 m² la celda) a un norte de 4,4 Mm; todas sus
coordenadas son exactas en binario."""
SMALL_WINDOW = (slice(2, 6), slice(3, 9))
"""La ventana de la huella a mano: las filas 2 a 5 y las columnas 3 a 8 de la rejilla."""
SMALL_FOOTPRINT_ROWS = slice(1, 3)
SMALL_FOOTPRINT_COLS = slice(1, 5)
SMALL_TERRAIN = np.array([[103.0, 99.0, 101.5, 102.5],
                          [100.0, 101.0, 98.0, 105.0]])
"""El terreno de la huella (dos filas, de norte a sur, por cuatro columnas) frente a su rasante
``100 + 0,5·j`` (100,5; 101; 101,5; 102 m en cada columna)."""
SMALL_LEVELS = np.array([100.5, 101.0, 101.5, 102.0])


def small_job(*, cut_denied: tuple[tuple[int, int], ...] = (),
              fill_denied: tuple[tuple[int, int], ...] = (), mode: str = "cut"
              ) -> tuple[Any, Any]:
    """La plataforma de la rejilla de 2 × 3 m: el trabajo y su huella hecha a mano. Las celdas que
    se prohíben son ``(fila, columna)`` de la ventana de trabajo."""
    start = np.full(SMALL.shape, 50.0)
    start[SMALL_WINDOW[0], SMALL_WINDOW[1]][SMALL_FOOTPRINT_ROWS, SMALL_FOOTPRINT_COLS] = (
        SMALL_TERRAIN)
    cut_allowed = np.ones(SMALL.shape, dtype=bool)
    fill_allowed = np.ones(SMALL.shape, dtype=bool)
    for mask, cells in ((cut_allowed, cut_denied), (fill_allowed, fill_denied)):
        for row, col in cells:
            mask[SMALL_WINDOW[0].start + row, SMALL_WINDOW[1].start + col] = False
    shape = (4, 6)
    cells = np.zeros(shape, dtype=bool)
    cells[SMALL_FOOTPRINT_ROWS, SMALL_FOOTPRINT_COLS] = True
    levels = np.full(shape, np.nan)
    levels[SMALL_FOOTPRINT_ROWS, SMALL_FOOTPRINT_COLS] = SMALL_LEVELS
    footprint = platform.Footprint(
        SMALL_WINDOW, cells, np.full(shape, np.nan), levels,
        model.Axis(((500_127.5, 4_399_990.0), (500_135.5, 4_399_990.0))), 8.0, 100.0, 0.0,
        SMALL.cell_area)
    job = platform.PlatformJob(
        request("Rejilla de 2 por 3"), "PLT-007", SMALL, start,
        platform.PlatformGeometry("line", ((np.array([[500_127.5, 4_399_990.0],
                                                       [500_135.5, 4_399_990.0]]),),)),
        {"mode": mode}, cut_allowed, fill_allowed)
    return job, footprint


def small_centre(row: int, col: int) -> tuple[float, float]:
    """El centro absoluto de la celda ``(fila, columna)`` de la ventana de trabajo."""
    return (SMALL.west + (SMALL_WINDOW[1].start + col + 0.5) * SMALL.dx,
            SMALL.north - (SMALL_WINDOW[0].start + row + 0.5) * SMALL.dy)


class SmallGridTest(unittest.TestCase):
    """RF-015-20, RF-015-21, RF-015-13: una plataforma de ocho celdas de 6 m² a mano (el terreno y
    la rasante de ``SMALL_TERRAIN`` y ``SMALL_LEVELS``)."""

    def test_cut_mode_by_hand(self) -> None:
        """RF-015-20: baja 2,5 + 0,5 + 3 = 6 m de profundidad, × 6 m² = 36 m³; no sube nada; las
        tres celdas por debajo (2; 0,5 y 3,5 m) quedan como estaban, en tres grupos (dos celdas en
        diagonal no son vecinas) por el orden de su primera celda; la celda a 101,5 m ya está en la
        rasante."""
        job, footprint = small_job()
        applied = platform.apply_platform(job, footprint)
        self.assertAlmostEqual(applied.cut_m3, 36.0, delta=TOL)
        self.assertEqual((applied.fill_m3, applied.cut_cells, applied.fill_cells), (0.0, 3, 0))
        expected = SMALL_TERRAIN.copy()
        expected[0, 0], expected[0, 3], expected[1, 3] = 100.5, 102.0, 102.0
        np.testing.assert_allclose(
            applied.surface[SMALL_FOOTPRINT_ROWS, SMALL_FOOTPRINT_COLS], expected, rtol=0,
            atol=TOL)
        np.testing.assert_array_equal(applied.at_level[SMALL_FOOTPRINT_ROWS, SMALL_FOOTPRINT_COLS],
                                      [[True, False, True, True], [False, True, False, True]])
        self.assertEqual(applied.above, ())
        self.assertEqual([(g.group, g.cells, g.max_m) for g in applied.below],
                         [(1, 1, 2.0), (2, 1, 0.5), (3, 1, 3.5)])
        for group, cell in zip(applied.below, ((1, 2), (2, 1), (2, 3)), strict=True):
            x, y = small_centre(*cell)
            self.assertAlmostEqual(group.area_m2, 6.0, delta=TOL)
            self.assertAlmostEqual(group.x, x, delta=TOL)
            self.assertAlmostEqual(group.y, y, delta=TOL)
            self.assertEqual(group.cause, platform.OffLevelCause.NOT_FILLED)

    def test_cut_fill_mode_by_hand(self) -> None:
        """RF-015-21: sube 2 + 0,5 + 3,5 = 6 m de profundidad, × 6 m² = 36 m³, y baja los mismos
        36 m³: toda la huella en la rasante."""
        job, footprint = small_job(mode="cut_fill")
        applied = platform.apply_platform(job, footprint)
        self.assertAlmostEqual(applied.cut_m3, 36.0, delta=TOL)
        self.assertAlmostEqual(applied.fill_m3, 36.0, delta=TOL)
        self.assertEqual((applied.cut_cells, applied.fill_cells), (3, 3))
        np.testing.assert_allclose(
            applied.surface[SMALL_FOOTPRINT_ROWS, SMALL_FOOTPRINT_COLS],
            np.tile(SMALL_LEVELS, (2, 1)), rtol=0, atol=TOL)
        np.testing.assert_array_equal(applied.at_level, footprint.cells)

    def test_a_cell_the_mask_does_not_cut_and_one_it_does_not_fill(self) -> None:
        """RF-015-13: sin cortar la celda (1, 1) (103 m, 2,5 m sobre su rasante) y sin rellenar la
        (2, 3) (98 m, 3,5 m bajo la suya): en «en corte y relleno» el corte es 0,5 + 3 = 3,5 m ×
        6 = 21 m³, el relleno 2 + 0,5 = 2,5 m × 6 = 15 m³, y quedan dos grupos de una celda, uno
        por cada causa, con su lugar."""
        job, footprint = small_job(cut_denied=((1, 1),), fill_denied=((2, 3),), mode="cut_fill")
        applied = platform.apply_platform(job, footprint)
        self.assertAlmostEqual(applied.cut_m3, 21.0, delta=TOL)
        self.assertAlmostEqual(applied.fill_m3, 15.0, delta=TOL)
        (above,) = applied.above
        (below,) = applied.below
        self.assertEqual((above.cells, above.cause, above.max_m),
                         (1, platform.OffLevelCause.CUT_DENIED, 2.5))
        self.assertEqual((below.cells, below.cause, below.max_m),
                         (1, platform.OffLevelCause.FILL_DENIED, 3.5))
        self.assertEqual((above.x, above.y), small_centre(1, 1))
        self.assertEqual((below.x, below.y), small_centre(2, 3))
        self.assertEqual((above.x, above.y), (500_132.5, 4_399_989.75))
        self.assertEqual((below.x, below.y), (500_136.5, 4_399_986.75))
        self.assertAlmostEqual(applied.blocked_area_m2, 12.0, delta=TOL)
        np.testing.assert_array_equal(
            np.argwhere(applied.cut_denied), [[1, 1]])
        np.testing.assert_array_equal(np.argwhere(applied.fill_denied), [[2, 3]])
        self.assertEqual(float(applied.surface[1, 1]), 103.0)
        self.assertEqual(float(applied.surface[2, 3]), 98.0)
        np.testing.assert_array_equal(
            applied.at_level[SMALL_FOOTPRINT_ROWS, SMALL_FOOTPRINT_COLS],
            [[False, True, True, True], [True, True, False, True]])

    def test_two_neighbouring_cells_are_one_group_with_the_mean_of_their_centres(self) -> None:
        """RF-015-13: sin cortar las dos celdas de la última columna (0,5 y 3 m sobre la rasante,
        una sobre la otra) forman un grupo de 2 celdas = 12 m², hasta 3 m, con el centro en la
        media de los suyos (x = 500.138,5; y = 4.399.988,25) y el corte es 2,5 m × 6 = 15 m³."""
        job, footprint = small_job(cut_denied=((1, 4), (2, 4)))
        applied = platform.apply_platform(job, footprint)
        (group,) = applied.above
        self.assertEqual((group.cells, group.max_m), (2, 3.0))
        self.assertAlmostEqual(group.area_m2, 12.0, delta=TOL)
        self.assertEqual((group.x, group.y), (500_138.5, 4_399_988.25))
        self.assertAlmostEqual(applied.cut_m3, 15.0, delta=TOL)

    def test_the_groups_come_in_the_order_of_their_first_cell(self) -> None:
        """RF-015-13: los grupos se numeran desde 1 en el orden de su primera celda recorriendo la
        rejilla fila a fila desde el norte, no en el orden en que se prohíben."""
        job, footprint = small_job(cut_denied=((2, 4), (1, 1)))
        applied = platform.apply_platform(job, footprint)
        self.assertEqual([(g.group, g.cells) for g in applied.above], [(1, 1), (2, 1)])
        self.assertEqual((applied.above[0].x, applied.above[0].y), small_centre(1, 1))
        self.assertEqual((applied.above[1].x, applied.above[1].y), small_centre(2, 4))


class GroupsInTheStripTest(unittest.TestCase):
    """RF-015-13: grupos separados de lo que no se corta, en la franja (a mano, celdas de 1 m²)."""

    def test_separate_groups_diagonal_cells_and_their_order(self) -> None:
        """Tres cajas y dos celdas en diagonal sin cortar (todas a 6 m sobre la rasante): una de
        10 × 20 (x de 260 a 270, y de 190 a 210), otra de 10 × 10 (x de 110 a 120, y de 185 a
        195) y las dos celdas (150,5; 200,5) y (151,5; 201,5), que se tocan solo por la esquina:
        cuatro grupos en el orden de su primera celda desde el norte (la caja de 200 celdas, la
        celda de (151,5; 201,5), la de (150,5; 200,5) y la caja de 100), con sus centros."""
        case = efx.strip_case()
        denied = (box(260.0, 190.0, 270.0, 210.0) | box(110.0, 185.0, 120.0, 195.0)
                  | box(150.0, 200.0, 151.0, 201.0) | box(151.0, 201.0, 152.0, 202.0))
        job = strip_job(case, "cut", cut_allowed=~denied)
        footprint, applied = run(job)
        self.assertEqual(int(denied.sum()), 200 + 100 + 1 + 1)
        self.assertEqual([(g.group, g.cells) for g in applied.above],
                         [(1, 200), (2, 1), (3, 1), (4, 100)])
        for group, place in zip(applied.above, ((265.0, 200.0), (151.5, 201.5), (150.5, 200.5),
                                                (115.0, 190.0)), strict=True):
            x, y = centre(*place)
            self.assertAlmostEqual(group.x, x, delta=TOL)
            self.assertAlmostEqual(group.y, y, delta=TOL)
            self.assertAlmostEqual(group.max_m, 6.0, delta=TOL)
            self.assertAlmostEqual(group.area_m2, float(group.cells), delta=TOL)
        self.assertAlmostEqual(applied.blocked_area_m2, 302.0, delta=TOL)
        self.assertAlmostEqual(applied.cut_m3 / (6.0 * (6400 - 302)), 1.0, delta=TOL)


# --- Propiedades -------------------------------------------------------------------------------


class PropertyTest(unittest.TestCase):
    """RF-015-20, RF-015-21, RF-015-06: con un terreno y unas máscaras al azar (semilla fija), lo
    que debe cumplirse siempre."""

    @classmethod
    def setUpClass(cls) -> None:
        rng = np.random.default_rng(1507)
        cls.case = efx.strip_case()
        cls.terrain = cls.case.terrain + rng.uniform(-8.0, 8.0, GRID.shape)
        cls.terrain[240:242, 150:152] = np.nan  # sin dato, dentro de la ventana y fuera de la huella
        cls.cut_allowed = rng.random(GRID.shape) > 0.2
        cls.fill_allowed = rng.random(GRID.shape) > 0.3
        cls.cases = {}
        for mode in ("cut", "cut_fill"):
            job = strip_job(cls.case, mode, start=cls.terrain, cut_allowed=cls.cut_allowed,
                            fill_allowed=cls.fill_allowed)
            footprint, applied = run(job)
            cls.cases[mode] = (job, footprint, applied)

    def check_mode(self, mode: str) -> tuple[Any, Any, np.ndarray, np.ndarray]:
        job, footprint, applied = self.cases[mode]
        cells = footprint.cells
        z = job.start[footprint.window]
        return footprint, applied, cells, z

    def test_cut_mode_never_rises_and_cuts_only_where_it_may(self) -> None:
        """RF-015-20, RF-015-06: en «en corte», ``z' ≤ z`` en toda la ventana (donde hay dato, y
        las celdas sin dato siguen sin él); ``z' = mín(z, rasante)`` en la huella con el corte
        admitido y ``z' = z`` donde no se admite y fuera de la huella."""
        footprint, applied, cells, z = self.check_mode("cut")
        finite = np.isfinite(z)
        self.assertTrue(np.all(applied.surface[finite] <= z[finite]))
        np.testing.assert_array_equal(np.isnan(applied.surface), np.isnan(z))
        allowed = in_window(footprint, self.cut_allowed)
        levels = footprint.levels
        both = cells & allowed
        np.testing.assert_array_equal(applied.surface[both], np.minimum(z[both], levels[both]))
        keep = ~both
        np.testing.assert_array_equal(applied.surface[keep], z[keep])
        self.assertEqual(applied.fill_m3, 0.0)
        self.assertEqual(applied.fill_cells, 0)

    def test_cut_fill_mode_goes_to_the_grade_where_the_masks_allow(self) -> None:
        """RF-015-21, RF-015-06: en «en corte y relleno», además ``z' = rasante`` donde ``z <
        rasante`` y el relleno se admite; donde no, ``z' = z`` (y por encima de la rasante sin
        corte admitido, igual)."""
        footprint, applied, cells, z = self.check_mode("cut_fill")
        cut = in_window(footprint, self.cut_allowed)
        fill = in_window(footprint, self.fill_allowed)
        levels = footprint.levels
        with np.errstate(invalid="ignore"):
            down = cells & cut & (z > levels)
            up = cells & fill & (z < levels)
        np.testing.assert_array_equal(applied.surface[down], levels[down])
        np.testing.assert_array_equal(applied.surface[up], levels[up])
        rest = ~(down | up)
        kept = rest & np.isfinite(z)
        np.testing.assert_array_equal(applied.surface[kept], z[kept])

    def test_the_volumes_are_the_cell_by_cell_sums(self) -> None:
        """RF-015-20, RF-015-21: el corte y el relleno de la huella son las sumas celda a celda
        (con ``math.fsum``) de lo que baja y de lo que sube, por 1 m² la celda, a ≤ 10⁻⁹
        relativo."""
        for mode in ("cut", "cut_fill"):
            with self.subTest(mode=mode):
                _footprint, applied, cells, z = self.check_mode(mode)
                after = applied.surface[cells]
                before = z[cells]
                cut = math.fsum(float(b - a) for b, a in zip(before, after, strict=True) if a < b)
                fill = math.fsum(float(a - b) for b, a in zip(before, after, strict=True) if a > b)
                self.assertAlmostEqual(applied.cut_m3 / cut, 1.0, delta=TOL)
                if fill:
                    self.assertAlmostEqual(applied.fill_m3 / fill, 1.0, delta=TOL)
                else:
                    self.assertEqual(applied.fill_m3, 0.0)

    def test_the_cells_off_the_grade_are_exactly_those_in_the_groups(self) -> None:
        """RF-015-24: las celdas de la huella que no quedan en la rasante (a 10⁻⁹ m) son
        exactamente las de los grupos por encima y por debajo; ``at_level`` es el resto de la
        huella; la diferencia máxima de cada lado es la mayor de sus celdas, y las máscaras
        ``cut_denied`` y ``fill_denied`` son lo que las máscaras no dejan mover."""
        for mode in ("cut", "cut_fill"):
            with self.subTest(mode=mode):
                footprint, applied, cells, _z = self.check_mode(mode)
                gap = applied.surface - footprint.levels
                with np.errstate(invalid="ignore"):
                    near = cells & (np.abs(gap) <= TOL)
                np.testing.assert_array_equal(applied.at_level, near)
                with np.errstate(invalid="ignore"):
                    above = cells & (gap > TOL)
                    below = cells & (gap < -TOL)
                self.assertEqual(sum(g.cells for g in applied.above), int(above.sum()))
                self.assertEqual(sum(g.cells for g in applied.below), int(below.sum()))
                self.assertEqual(int(above.sum()) + int(below.sum()) + int(near.sum()),
                                 int(cells.sum()))
                np.testing.assert_array_equal(applied.cut_denied, above)
                np.testing.assert_array_equal(applied.fill_denied,
                                              below if mode == "cut_fill" else np.zeros_like(below))
                if above.any():
                    self.assertAlmostEqual(max(g.max_m for g in applied.above),
                                           float(gap[above].max()), delta=TOL)
                if below.any():
                    self.assertAlmostEqual(max(g.max_m for g in applied.below),
                                           float((-gap[below]).max()), delta=TOL)
                self.assertAlmostEqual(
                    sum(g.area_m2 for g in applied.above) + sum(g.area_m2 for g in applied.below),
                    float(above.sum() + below.sum()), delta=TOL)
                self.assertTrue(all(g.cause == platform.OffLevelCause.CUT_DENIED
                                    for g in applied.above))

    def test_nothing_that_was_read_is_modified(self) -> None:
        """Principio 7: la superficie de partida (con sus celdas sin dato) y las máscaras quedan
        bit a bit como estaban tras aplicar."""
        job, footprint, _applied = self.cases["cut_fill"]
        np.testing.assert_array_equal(job.start, self.terrain)
        np.testing.assert_array_equal(job.cut_allowed, self.cut_allowed)
        np.testing.assert_array_equal(job.fill_allowed, self.fill_allowed)
        self.assertTrue(np.isnan(footprint.levels[~footprint.cells]).all())


# --- Sin dato y entradas que no cuadran --------------------------------------------------------


class InputsTest(unittest.TestCase):
    """RF-015-09 (lo rechaza otra tarea) y los errores del programa."""

    def test_no_data_in_the_footprint_is_a_program_error(self) -> None:
        """Sin dato en la huella lo rechaza la preparación (T11, RF-015-09); aquí no se oculta con
        ningún valor: error del programa (``ValueError``) que cuenta las celdas y nombra la
        plataforma."""
        case = efx.strip_case()
        terrain = case.terrain.copy()
        terrain[200, 200:203] = np.nan  # y = 199,5 m: dentro de la huella (de 180 a 220)
        job = strip_job(case, "cut", start=terrain)
        footprint = platform.platform_footprint(job)
        with self.assertRaises(ValueError) as caught:
            platform.apply_platform(job, footprint)
        self.assertIn("sin dato", str(caught.exception))
        self.assertIn("3 celdas", str(caught.exception))
        self.assertIn("«Franja»", str(caught.exception))

    def test_a_footprint_that_is_not_of_the_job_is_a_program_error(self) -> None:
        """Una huella cuya ventana se sale de la rejilla del trabajo, o cuyas rejillas no son de
        la forma de su ventana, es un error del programa."""
        case = efx.strip_case()
        job = strip_job(case)
        footprint = platform.platform_footprint(job)
        outside = dataclasses.replace(footprint, window=(slice(300, 500), slice(0, 264)))
        wrong = dataclasses.replace(footprint, window=(slice(0, 3), slice(0, 3)))
        for other in (outside, wrong):
            with self.subTest(window=other.window):
                with self.assertRaises(ValueError):
                    platform.apply_platform(job, other)


# --- Por pasos ---------------------------------------------------------------------------------


class StepsTest(unittest.TestCase):
    """Plan 015 §5.3.2: pasos de ≤ 0,05 s, como el resto de ``design``."""

    def test_the_steps_end_with_the_same_result(self) -> None:
        """El último ``Progress`` (fase ``platform_apply``) lleva lo mismo que la llamada directa."""
        case = efx.strip_case(untouchable=True)
        job = strip_job(case, "cut_fill")
        footprint = platform.platform_footprint(job)
        steps = list(platform.apply_platform_steps(job, footprint))
        self.assertTrue(steps)
        self.assertTrue(all(step.phase == "platform_apply" for step in steps))
        self.assertTrue(all(step.result is None for step in steps[:-1]))
        done = steps[-1].result
        direct = platform.apply_platform(job, footprint)
        self.assertIsInstance(done, platform.Applied)
        np.testing.assert_array_equal(done.surface, direct.surface)
        np.testing.assert_array_equal(done.at_level, direct.at_level)
        self.assertEqual((done.cut_m3, done.fill_m3), (direct.cut_m3, direct.fill_m3))
        self.assertEqual(done.above, direct.above)
        self.assertEqual(done.below, direct.below)

    def test_the_mode_is_rejected_on_the_call_and_closing_leaves_nothing(self) -> None:
        """El modo que no es de la lista se rechaza al llamar (como ``transition_steps``); cerrar a
        mitad no deja nada."""
        case = efx.strip_case()
        job = strip_job(case, "fill")
        footprint = platform.platform_footprint(job)
        with self.assertRaises(DesignError):
            platform.apply_platform_steps(job, footprint)
        good = strip_job(case, "cut")
        work = platform.apply_platform_steps(good, platform.platform_footprint(good))
        next(work)
        work.close()


if __name__ == "__main__":
    unittest.main()

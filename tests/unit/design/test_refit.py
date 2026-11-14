# SPDX-License-Identifier: GPL-3.0-or-later
"""El ajuste de un diseño a un límite nuevo (spec 014, T32; HU-014-7; RF-014-27, RF-014-28,
RF-014-29, RF-014-31; CE-014-08; plan 014 A13, P-3, §5.2.3; error 46 del análisis).

- ``design.refit.refit_steps`` (A13, el ajuste): con el límite nuevo de las máscaras
  (``design.refit.limit_cells``: para cortar, el perímetro de actuación ∩ el límite legal sin su
  resguardo hacia dentro, ``D``; para rellenar, el perímetro), **fuera** de ``D`` el terreno
  intacto (un relleno dentro del perímetro sigue: es del límite); **dentro**, cada superficie sube
  hasta la envolvente descendente de la 013 desde el terreno del anillo exterior de ``D`` con la
  **cara de su propio perfil por su factor de malla** (``tan α · malla`` de cada celda, por
  sectores), sin superar el terreno: ``S' = máx(S, mín(z, ENV↓))``. El volumen de ajuste es ``Σ |S'
  − S| · área de celda``. Un límite nuevo que no deja nada de la superficie fuera (la comprobación
  de la T31) no la toca: 0 m³ y el aviso ``des.refit_not_needed``.
- ``design.refit.check_angle`` (RF-014-28): pedir otro ángulo que la cara del perfil de la
  superficie se rechaza con ``des.refit_angle`` nombrando la superficie y los dos ángulos.
- **CE-014-08** (error 46) en la rejilla, el perímetro y el límite legal de la cantera sintética
  (``quarry_fixtures``, T01) con el límite legal 30 m más corto por el este y el terreno llano (con
  la ladera, la envolvente desde el anillo no tiene una fórmula a mano; como el CE-014-05 de la
  T24): la explotación se ajusta con 60° y la final con 35°, cada una con los m³ del cálculo a
  mano a ≤ 10⁻⁶ relativo; con 35° la explotación saldría con m³ de más (los falsos del error 46),
  y pedirlo se rechaza.
- ``design.steps.refit_run`` (RF-014-27 a RF-014-29): «Calcular» el ajuste de las superficies de
  una cantera de la versión deja una rejilla por superficie en su temporal y **nada registrado**;
  «Crear» registra ``des.refit`` con una ``des_adj_`` por superficie (papel ``design_surface``) y
  su cifra ``des.refit_m3``; el ángulo de cada una sale del perfil de la operación que la creó
  (P-3): la cara y el factor de malla que **anotó** esa operación, no los de hoy (T49, hallazgo
  F-10), que el ajuste anota en sus ajustes; se recalcula (no se reproduce: depende del límite
  vigente); cambiar el perfil de la cantera de la que sale lo deja obsoleto con esa causa, y
  «Recalcular lo obsoleto» va cantera → ajuste (T50, hallazgo F-11).
- **El orden de las dos superficies después del ajuste** (T53; RF-014-14 frente a RF-014-27,
  hallazgo F-15; la propuesta por defecto que aceptó Samuel): ajustada cada una con la cara de su
  perfil, la final (35°) queda por encima de la explotación (60°) junto al límite nuevo (la sonda
  de la T38, con ``store.refit_compute_steps`` en celdas de 10 m); si el ajuste lleva las dos
  superficies de una misma cantera, la regla de orden de esa cantera (su ajuste «order») las ata y
  ``check_order`` las comprueba antes de «Crear», con una nota con las celdas que cambió; los m³
  de cada una siguen siendo los de su cara (CE-014-08 igual); con una sola, un aviso si queda del
  lado equivocado de la otra.
- **El ajuste frente a lo obsoleto del diseño del que sale** (T54; RF-014-27, RF-014-31, hallazgo
  F-16; la propuesta por defecto (b) que aceptó Samuel): el límite nuevo deja obsoleta la cantera
  (sus máscaras), así que el ajuste nace obsoleto y «Recalcular lo obsoleto» rediseña la cantera con
  el límite vigente y rehace el ajuste sobre ella; el resumen lo avisa (``des.refit_source_stale``),
  una vez por diseño obsoleto; con la cantera ya recalculada, no.
"""

from __future__ import annotations

import dataclasses
import json
import math
import unittest
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any, ClassVar
from unittest import mock

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import constraints_project as cp
from tests.support import design_oracles as oracles
from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered

edges = import_geoblender("design.edges")
refit = import_geoblender("design.refit")
quarry = import_geoblender("design.quarry")
messages = import_geoblender("design.messages")
steps = import_geoblender("design.steps")
store = import_geoblender("design.store")
model = import_geoblender("design.model")
provenance = import_geoblender("design.provenance")
design_params = import_geoblender("design.params")
core_params = import_geoblender("core.params")
res_provenance = import_geoblender("reserves.provenance")
recompute_mod = import_geoblender("core.provenance.recompute")
figures_mod = import_geoblender("core.provenance.figures")
access = import_geoblender("gis.masks.access")
combine = import_geoblender("gis.masks.combine")
geotiff_reader = import_geoblender("gis.geotiff.reader")
cstore = import_geoblender("core.constraints.store")
gis = import_geoblender("gis")

THICKNESS_M = 0.02
"""El espesor mínimo de la 012 de las pruebas (un dato de entrada)."""
SCALE = oracles.CHAMFER_SCALE
P, L, B = (int(combine.ClassBit.PERIMETER), int(combine.ClassBit.LEGAL),
           int(combine.ClassBit.INNER_BAND))


def finish(found: Iterator[Any]) -> Any:
    """El resultado del último ``Progress`` de unos pasos."""
    last = None
    for last in found:
        pass
    return last.result


def drive(work: Iterator[Any]) -> Any:
    """Lleva unos pasos hasta el final y devuelve el último ``Progress``."""
    found = None
    for found in work:
        pass
    return found


# --- Una rejilla a mano: 6 filas × 12 columnas de 2 m (4 m² por celda), la de la T31 -------------
HAND_GRID = gis.Grid(700_000.0, 4_400_012.0, 2.0, 2.0, 12, 6)
COLUMN_BITS = (0, P, P, P | L | B, *([P | L] * 6), P | L | B, L)
"""Los bits de cada columna, a mano: la 0 fuera de todo; la 1 y la 2, la franja de solo relleno; la
3 y la 10, el resguardo hacia dentro del límite; de la 4 a la 9, dentro (``D``); la 11, en el límite
legal pero fuera del perímetro. El anillo exterior de ``D``: las columnas 3 y 10."""
HAND_FACE = refit.ProfileFace("expl", "EXPL", 60.0, 0.5)
"""Un perfil de 60° con factor de malla 0,5: ``tan α · malla = 0,866``."""
HAND_DROP = math.tan(math.radians(60.0)) * 0.5 * 2.0 * SCALE
"""Lo que baja la envolvente *chamfer* en una celda de 2 m de eje con ese perfil (m)."""


def hand_masks() -> Any:
    """Las máscaras de :data:`HAND_GRID` con los bits de :data:`COLUMN_BITS`."""
    classes = np.tile(np.array(COLUMN_BITS, dtype=np.uint16), (HAND_GRID.nrows, 1))
    return access.MaskSet(HAND_GRID, "v-mano", "op-mano", access.MaskState.CURRENT, (), classes)


def hand_case() -> tuple[np.ndarray, np.ndarray]:
    """La partida (100 m, sin dato en la celda (0, 0)) y la superficie, a mano: un corte de 2 m en
    las filas 0 y 1, un relleno de 3 m en las 2 y 3 (sin dato en la celda (3, 0)), 0,01 m en la 4
    y la partida en la 5."""
    start = np.full(HAND_GRID.shape, 100.0)
    start[0, 0] = np.nan
    surface = start.copy()
    surface[0:2] -= 2.0
    surface[2:4] += 3.0
    surface[3, 0] = np.nan
    surface[4] += 0.01
    return start, surface


def ring_steps(columns: np.ndarray) -> np.ndarray:
    """Las celdas de eje hasta el anillo de ``D`` de :data:`HAND_GRID` (columnas 3 y 10)."""
    return np.minimum(columns - 3, 10 - columns)


class RefitByHandTest(unittest.TestCase):
    """RF-014-27, RF-014-28 sin proyecto, en una rejilla a mano."""

    def test_the_refit_by_hand(self) -> None:
        """RF-014-27 (A13): fuera de ``D``, el terreno: el corte de las columnas 0 a 3, 10 y 11 y el
        relleno fuera del perímetro (columnas 0 y 11) vuelven a 100 m; el relleno de la franja de
        solo relleno y del resguardo (columnas 1 a 3 y 10) sigue (es del límite). Dentro, el corte
        sube hasta la envolvente desde el anillo con la cara del perfil por su factor de malla,
        ``100 − 0,866 · 2 · 0,98644 · k``: 98,29 m en las columnas 4 y 9 (k = 1) y 98 en las demás;
        el relleno no cambia. Las celdas sin dato siguen sin tocar. El volumen, a mano, por 4 m²;
        ninguna entrada se modifica."""
        start, surface = hand_case()
        masks = hand_masks()
        before = (start.copy(), surface.copy(), masks.classes.copy())
        slope = refit.face_slope(np.zeros(HAND_GRID.shape, dtype=np.int16), HAND_FACE, ())
        found = finish(refit.refit_steps(surface, start, masks, slope, THICKNESS_M,
                                         name="des_exp_mano"))
        self.assertIsInstance(found, refit.Refit)
        expected = surface.copy()
        columns = np.arange(HAND_GRID.ncols)
        inside = (columns >= 4) & (columns <= 9)
        raised = 100.0 - HAND_DROP * ring_steps(columns)
        for row in (0, 1):
            expected[row] = np.where(inside, np.maximum(98.0, raised), 100.0)
        expected[0, 0] = np.nan  # sin dato (la superficie sale de la partida): no se toca
        for row in (2, 3, 4):
            expected[row, 0] = surface[row, 0] if row == 3 else 100.0
            expected[row, 11] = 100.0
        np.testing.assert_allclose(found.grid, expected, rtol=0.0, atol=1e-12)
        self.assertTrue(np.isnan(found.grid[0, 0]) and np.isnan(found.grid[3, 0]))
        self.assertEqual(found.grid[1, 4], 100.0 - HAND_DROP)
        self.assertGreater(found.grid[1, 4], 98.0)
        changed = 20
        moved_m = 10.0 + 12.0 + 6.0 + 3.0 + 0.02 + 4.0 * (2.0 - HAND_DROP)
        self.assertEqual((found.surface, found.cells, found.outside_cells), ("des_exp_mano",
                                                                             changed, 16))
        self.assertAlmostEqual(found.volume_m3, moved_m * 4.0, delta=1e-9)
        self.assertEqual((found.area_m2, found.cell_area_m2), (changed * 4.0, 4.0))
        self.assertTrue(found.needed)
        self.assertIsNone(found.notice)
        self.assertEqual(found.check.cells, 14)  # la comprobación de la T31, antes del ajuste
        for current, old in zip((start, surface, masks.classes), before, strict=True):
            np.testing.assert_array_equal(current, old)
        after = refit.outside_volume(found.grid, start, masks, THICKNESS_M, name="x")
        self.assertEqual(after.cells, 0)

    def test_the_faces_of_each_sector_against_dijkstra(self) -> None:
        """RF-014-27 (ADR-0029): con perfiles por sector, cada celda baja con la cara de su
        sector por su factor de malla (las de ningún sector, con la del perfil base); el ajuste es
        el del oráculo de Dijkstra *chamfer* de la 013 con esas pendientes, a ≤ 10⁻⁹ m."""
        start = np.full(HAND_GRID.shape, 100.0)
        surface = start.copy()
        surface[:, 3:10] = 94.0
        labels = np.zeros(HAND_GRID.shape, dtype=np.int16)
        labels[0:3, :6] = 1
        labels[3:6, :8] = 2
        base = refit.ProfileFace("base", "BASE", 45.0, 1.0)
        north = refit.ProfileFace("norte", "NORTE", 60.0, 1.0)
        south = refit.ProfileFace("sur", "SUR", 30.0, 0.8)
        slope = refit.face_slope(labels, base, (north, south))
        tangents = np.choose(labels, [math.tan(math.radians(45.0)), math.tan(math.radians(60.0)),
                                      math.tan(math.radians(30.0)) * 0.8])
        np.testing.assert_allclose(slope.tan, tangents, rtol=1e-15)
        found = finish(refit.refit_steps(surface, start, hand_masks(), slope, THICKNESS_M,
                                         name="des_fin_mano"))
        ring = np.zeros(HAND_GRID.shape, dtype=bool)
        ring[:, [3, 10]] = True
        lower = oracles.dijkstra(np.where(ring, start, np.nan), tangents, 2.0, direction="down")
        inside = np.zeros(HAND_GRID.shape, dtype=bool)
        inside[:, 4:10] = True
        expected = np.where(inside, np.maximum(surface, np.minimum(start, lower)), start)
        np.testing.assert_allclose(found.grid, expected, rtol=0.0, atol=1e-9)
        self.assertGreater(found.volume_m3, 0.0)

    def test_the_slope_of_the_faces(self) -> None:
        """RF-014-27: la pendiente de cada celda es ``tan α · malla`` del perfil de su sector (la
        etiqueta ``k`` es el sector ``k``) y la del perfil base en las celdas sin sector; con un
        solo perfil, una constante."""
        labels = np.array([[0, 1, 2], [2, 1, 0]], dtype=np.int16)
        base = refit.ProfileFace("a", "A", 45.0, 1.0)
        other = refit.ProfileFace("b", "B", 60.0, 0.5)
        field = refit.face_slope(labels, base, (other, base))
        np.testing.assert_allclose(field.tan, [[1.0, math.sqrt(3.0) * 0.5, 1.0],
                                               [1.0, math.sqrt(3.0) * 0.5, 1.0]], rtol=1e-15)
        uniform = refit.face_slope(labels, base, (base, base))
        self.assertTrue(uniform.uniform)
        self.assertAlmostEqual(uniform.tan, 1.0, delta=1e-15)
        self.assertEqual(base.rule.effective, math.tan(math.radians(45.0)))
        with self.assertRaises(ValueError):
            refit.face_slope(labels, base, (other,))  # falta el perfil del sector 2

    def test_another_angle_is_refused(self) -> None:
        """RF-014-28 (error 46): pedir para una superficie otro ángulo que la cara de su perfil
        se rechaza con ``des.refit_angle`` nombrando la superficie, el perfil y los dos ángulos;
        el de su cara (o ninguno) se admite; con perfiles de caras distintas, ninguno vale."""
        expl = refit.ProfileFace("expl_10_60_6", "EXPL_10_60_6", 60.0, 1.0)
        rest = refit.ProfileFace("rest_5_35_6", "REST_5_35_6", 35.0, 1.0)
        refit.check_angle("des_exp_corta", (expl,), None)
        refit.check_angle("des_exp_corta", (expl, expl), 60.0)
        with self.assertRaises(messages.DesignError) as caught:
            refit.check_angle("des_exp_corta", (expl,), 35.0)
        error = caught.exception
        self.assertEqual(error.code, "des.refit_angle")
        self.assertEqual((error.values["surface"], error.values["profile"],
                          error.values["face"], error.values["value"]),
                         ("des_exp_corta", "EXPL_10_60_6", 60.0, 35.0))
        self.assertIn("«des_exp_corta»", error.text)
        self.assertIn("(60°)", error.text)
        self.assertIn("35°", error.text)
        with self.assertRaises(messages.DesignError) as caught:
            refit.check_angle("des_fin_corta", (rest, expl), 35.0)
        self.assertEqual(caught.exception.values["profile"], "EXPL_10_60_6")
        with self.assertRaises(messages.DesignError):
            refit.check_angle("des_fin_corta", (rest,), math.nan)

    def test_a_limit_that_leaves_nothing_outside_is_not_needed(self) -> None:
        """RF-014-27 (caso límite de la spec §8): si el límite nuevo no deja nada de la superficie
        fuera (la comprobación de la T31), no se toca: 0 m³, ninguna celda y el aviso
        ``des.refit_not_needed`` con su nombre, aunque la envolvente del anillo quede por encima de
        alguna celda de dentro."""
        start = np.full(HAND_GRID.shape, 100.0)
        surface = start.copy()
        surface[0:2, 4:10] -= 2.0
        slope = refit.face_slope(np.zeros(HAND_GRID.shape, dtype=np.int16), HAND_FACE, ())
        found = finish(refit.refit_steps(surface, start, hand_masks(), slope, THICKNESS_M,
                                         name="des_exp_dentro"))
        np.testing.assert_array_equal(found.grid, surface)
        self.assertEqual((found.cells, found.outside_cells, found.volume_m3), (0, 0, 0.0))
        self.assertFalse(found.needed)
        notice = found.notice
        self.assertEqual((notice.code, notice.severity), ("des.refit_not_needed", "warning"))
        self.assertIn("«des_exp_dentro»", notice.text("es"))
        self.assertIn("no hacía falta", notice.text("es"))
        self.assertIn("was not needed", notice.text("en"))

    def test_the_outcome_its_figures_and_its_message(self) -> None:
        """RF-014-27, RF-014-29 (plan §5.2.3): la cifra CALCULADO ``des.refit_m3`` de cada
        superficie (m³), con el ámbito del nombre del ajuste y de la superficie; los avisos de las
        que no hacía falta; el mensaje dice el nombre y lo de cada una."""
        start, surface = hand_case()
        slope = refit.face_slope(np.zeros(HAND_GRID.shape, dtype=np.int16), HAND_FACE, ())
        one = finish(refit.refit_steps(surface, start, hand_masks(), slope, THICKNESS_M,
                                       name="des_exp_mano"))
        inside = start.copy()
        inside[0:2, 4:10] -= 2.0
        two = finish(refit.refit_steps(inside, start, hand_masks(), slope, THICKNESS_M,
                                       name="des_fin_mano"))
        outcome = refit.refit_outcome("Ajuste Ñ", (one, two))
        self.assertEqual(outcome.refits, (one, two))
        self.assertEqual(outcome.refit("des_fin_mano"), two)
        self.assertEqual(outcome.volume_m3, one.volume_m3)
        self.assertEqual([(f.key, f.value, f.unit) for f in outcome.figures],
                         [("des.refit_m3", one.volume_m3, "m3"), ("des.refit_m3", 0.0, "m3")])
        self.assertEqual([dict(f.scope) for f in outcome.figures],
                         [{"name": "ajuste_n", "surface": "des_exp_mano"},
                          {"name": "ajuste_n", "surface": "des_fin_mano"}])
        self.assertEqual(outcome.figures, refit.refit_figures("Ajuste Ñ", (one, two)))
        self.assertEqual([n.code for n in outcome.notices], ["des.refit_not_needed"])
        self.assertIn("Ajuste Ñ", outcome.message)
        self.assertIn("«des_exp_mano»", outcome.message)
        self.assertIn("«des_fin_mano»", outcome.message)

    def test_the_steps_and_their_refusals(self) -> None:
        """RF-014-27: por pasos (fase ``refit``); cerrar a mitad no deja nada; una rejilla de otra
        forma, un espesor negativo o una métrica que no es de la 013, error del programa al
        llamar."""
        start, surface = hand_case()
        slope = refit.face_slope(np.zeros(HAND_GRID.shape, dtype=np.int16), HAND_FACE, ())
        found = list(refit.refit_steps(surface, start, hand_masks(), slope, THICKNESS_M,
                                       name="x", budget_s=0.0))
        self.assertGreater(len(found), 2)
        self.assertEqual({step.phase for step in found}, {"refit"})
        running = refit.refit_steps(surface, start, hand_masks(), slope, THICKNESS_M, name="x",
                                    budget_s=0.0)
        next(running)
        running.close()
        for arguments in ((surface[:, :5], start), (surface, start[:3])):
            with self.subTest(forma=arguments[0].shape):
                with self.assertRaises(ValueError):
                    refit.refit_steps(*arguments, hand_masks(), slope, THICKNESS_M, name="x")
        with self.assertRaises(ValueError):
            refit.refit_steps(surface, start, hand_masks(), slope, -1.0, name="x")
        with self.assertRaises(ValueError):
            refit.refit_steps(surface, start, hand_masks(), slope, THICKNESS_M, name="x",
                              metric="chamfer3")


# --- CE-014-08 en la geometría de la cantera, con el terreno llano --------------------------------
Z0 = 234.25
"""El terreno llano (m), el de la T24."""
FINAL_FLOOR_M, EXPLOITATION_FLOOR_M = 185.25, 205.25
"""Los fondos de las dos superficies de prueba (m)."""
NEW_LEGAL_LOCAL = (qfx.LEGAL_LOCAL[0], qfx.LEGAL_LOCAL[1], qfx.LEGAL_LOCAL[2] - 30.0,
                   qfx.LEGAL_LOCAL[3])
"""El límite legal 30 m más corto por el este (local), el de la T31."""
NEW_INNER_LOCAL = (NEW_LEGAL_LOCAL[0] + qfx.LEGAL_INWARD_M, NEW_LEGAL_LOCAL[1] + qfx.LEGAL_INWARD_M,
                   NEW_LEGAL_LOCAL[2] - qfx.LEGAL_INWARD_M, NEW_LEGAL_LOCAL[3] - qfx.LEGAL_INWARD_M)
OLD_RING = (44, 355, 59, 340)
"""El anillo del recinto con que se diseñó (columna oeste, columna este, fila norte, fila sur):
el recinto, de (45, 60) a (355, 340) local."""
NEW_RING = (44, 325, 59, 340)
"""El anillo de ``D`` con el límite nuevo: de (45, 60) a (325, 340) local."""
EXPL_FACE = refit.ProfileFace(qfx.EXPLOITATION_PROFILE.code, qfx.EXPLOITATION_PROFILE.name,
                              qfx.EXPLOITATION_PROFILE.face_deg)
REST_FACE = refit.ProfileFace(qfx.FINAL_PROFILE.code, qfx.FINAL_PROFILE.name,
                              qfx.FINAL_PROFILE.face_deg)


def quarry_masks() -> Any:
    """Las máscaras de la cantera con el límite nuevo, a mano: el perímetro de actuación, el
    límite legal 30 m más corto por el este y su resguardo de 5 m hacia dentro."""
    perimeter = qfx.in_box(qfx.PERIMETER_LOCAL)
    legal = qfx.in_box(NEW_LEGAL_LOCAL)
    band = legal & ~qfx.in_box(NEW_INNER_LOCAL)
    classes = (perimeter * P | legal * L | band * B).astype(np.uint16)
    return access.MaskSet(qfx.GRID, "v-cantera", "op-cantera", access.MaskState.CURRENT, (),
                          classes)


def ring_cells(ring: tuple[int, int, int, int]) -> tuple[np.ndarray, np.ndarray]:
    """Dentro del recinto de ``ring`` y las celdas de eje hasta él (el *chamfer* hasta una
    recta de semillas va por el eje)."""
    rows, columns = np.indices(qfx.GRID.shape)
    west, east, north, south = ring
    inside = (columns > west) & (columns < east) & (rows > north) & (rows < south)
    steps_to = np.minimum.reduce([columns - west, east - columns, rows - north, south - rows])
    return inside, steps_to


def ce_surfaces() -> tuple[np.ndarray, np.ndarray]:
    """La final y la explotación de prueba, diseñadas con el recinto de antes: la final con el
    talud general de ``REST_5_35_6`` hasta su fondo, la explotación con el de ``EXPL_10_60_6``
    hasta el suyo y nunca por debajo de la final («final primero»), el terreno fuera."""
    inside, k = ring_cells(OLD_RING)
    final_tan = qfx.FINAL_PROFILE.general_tan * SCALE
    exploitation_tan = qfx.EXPLOITATION_PROFILE.general_tan * SCALE
    final = np.where(inside, np.maximum(FINAL_FLOOR_M, Z0 - final_tan * k), Z0)
    exploitation = np.where(inside, np.maximum(
        final, np.maximum(EXPLOITATION_FLOOR_M, Z0 - exploitation_tan * k)), Z0)
    return final, exploitation


def ce_by_hand(surface: np.ndarray, face_deg: float) -> np.ndarray:
    """A13 a mano: dentro de ``D``, ``máx(S, mín(z, z − tan α · 0,98644 · k))`` con ``k`` las
    celdas de eje hasta el anillo nuevo; fuera, el terreno."""
    inside, k = ring_cells(NEW_RING)
    lower = Z0 - math.tan(math.radians(face_deg)) * SCALE * k
    return np.where(inside, np.maximum(surface, np.minimum(Z0, lower)), Z0)


class Ce01408Test(unittest.TestCase):
    """CE-014-08 (error 46): el ajuste con la cara de cada superficie, a mano (véase el módulo)."""

    found: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.start = np.full(qfx.GRID.shape, Z0)
        cls.final, cls.exploitation = ce_surfaces()
        cls.masks = quarry_masks()
        labels = np.zeros(qfx.GRID.shape, dtype=np.int16)
        cls.found = {}
        for key, surface, face in (("exploitation", cls.exploitation, EXPL_FACE),
                                   ("final", cls.final, REST_FACE),
                                   ("false", cls.exploitation, REST_FACE)):
            cls.found[key] = finish(refit.refit_steps(
                surface, cls.start, cls.masks, refit.face_slope(labels, face, ()), THICKNESS_M,
                name=f"des_{key}"))

    def test_the_new_limit_by_hand(self) -> None:
        """CE-014-08: ``D`` es el perímetro ∩ el límite legal nuevo sin su resguardo, de (45, 60)
        a (325, 340) local; para rellenar, el perímetro."""
        cut, fill = refit.limit_cells(self.masks)
        np.testing.assert_array_equal(cut, ring_cells(NEW_RING)[0])
        np.testing.assert_array_equal(fill, qfx.in_box(qfx.PERIMETER_LOCAL))

    def test_ce_014_08_each_surface_with_the_face_of_its_profile(self) -> None:
        """CE-014-08 (error 46), RF-014-27: la explotación con 60° (``EXPL_10_60_6``) y la final con
        35° (``REST_5_35_6``) dan, celda a celda, el ajuste a mano a ≤ 10⁻⁹ m y los m³ del cálculo
        a mano a ≤ 10⁻⁶ relativo; al oeste, al norte y al sur (el límite no cambió) no se toca nada;
        al este del límite nuevo, el terreno; y ya no queda nada fuera (la comprobación de la
        T31)."""
        old_inside, old_k = ring_cells(OLD_RING)
        new_inside, new_k = ring_cells(NEW_RING)
        same_side = new_inside & (new_k == old_k)
        for key, surface, face in (("exploitation", self.exploitation, 60.0),
                                   ("final", self.final, 35.0)):
            with self.subTest(superficie=key):
                found = self.found[key]
                expected = ce_by_hand(surface, face)
                np.testing.assert_allclose(found.grid, expected, rtol=0.0, atol=1e-9)
                volume = float(np.sum(expected - surface))
                self.assertGreater(volume, 0.0)
                self.assertLessEqual(abs(found.volume_m3 - volume), 1e-6 * volume)
                np.testing.assert_array_equal(found.grid[same_side], surface[same_side])
                np.testing.assert_array_equal(found.grid[~new_inside], self.start[~new_inside])
                self.assertEqual(found.outside_cells,
                                 int(np.count_nonzero(old_inside & ~new_inside)))
                self.assertTrue(found.check.outside)
                after = refit.outside_volume(found.grid, self.start, self.masks, THICKNESS_M,
                                             name="x")
                self.assertEqual(after.cells, 0)
        self.assertGreater(self.found["final"].volume_m3, self.found["exploitation"].volume_m3)

    def test_ce_014_08_35_degrees_for_the_exploitation_is_refused(self) -> None:
        """CE-014-08 (error 46), RF-014-28: con 35° en el muro de explotación el ajuste saldría con
        m³ de más (los falsos del error 46: la cara de la final, no la suya), a mano, y pedirlo se
        rechaza nombrando la superficie y los dos ángulos."""
        false = self.found["false"]
        true = self.found["exploitation"]
        expected = ce_by_hand(self.exploitation, 35.0)
        np.testing.assert_allclose(false.grid, expected, rtol=0.0, atol=1e-9)
        volume = float(np.sum(expected - self.exploitation))
        self.assertLessEqual(abs(false.volume_m3 - volume), 1e-6 * volume)
        self.assertGreater(false.volume_m3 - true.volume_m3, 10_000.0)
        with self.assertRaises(messages.DesignError) as caught:
            refit.check_angle("des_exp_corta", (EXPL_FACE,), 35.0)
        self.assertEqual(caught.exception.code, "des.refit_angle")
        self.assertEqual((caught.exception.values["face"], caught.exception.values["value"]),
                         (60.0, 35.0))


# --- El orden de las dos superficies después del ajuste (T53; hallazgo F-15) ----------------------
ORDER_CELL_M = 10.0
"""El paso de la rejilla de la sonda de la T38 (rf-b) más grueso que conserva sus bordes y su rojo
(con celdas de 2 m, las de la sonda: 2.340 celdas con la final más de 1 mm por encima de la
explotación, hasta 20,72 m; con 10 m, 84 celdas, hasta 20,721 m)."""
ORDER_SIZE = 24
ORDER_GRID = gis.Grid(500_000.0, 4_400_000.0 + ORDER_SIZE * ORDER_CELL_M, ORDER_CELL_M,
                      ORDER_CELL_M, ORDER_SIZE, ORDER_SIZE)
"""240 × 240 m en celdas de 10 m."""
ORDER_LOW, ORDER_HIGH, ORDER_EAST = 2, 22, 19
"""El perímetro de actuación y el recinto con que se diseñó, de la fila y la columna 2 a la 21 (de
20 a 220 m); el límite legal nuevo, 30 m más corto por el este (hasta la columna 18: 190 m)."""
ORDER_FLOORS = {35.0: 170.0, 60.0: 180.0}
"""El fondo de la final (35°) y el de la explotación (60°) de la sonda (m)."""
ORDER_QUARRY = "Corta T53"
ORDER_FINAL = provenance.dataset_name("fin", ORDER_QUARRY)
ORDER_EXPLOITATION = provenance.dataset_name("exp", ORDER_QUARRY)


def order_masks() -> Any:
    """Las máscaras de la sonda: el perímetro y el límite legal nuevo, sin resguardo (``D``, de las
    columnas 2 a 18)."""
    rows, columns = np.indices(ORDER_GRID.shape)
    perimeter = ((rows >= ORDER_LOW) & (rows < ORDER_HIGH) & (columns >= ORDER_LOW)
                 & (columns < ORDER_HIGH))
    legal = perimeter & (columns < ORDER_EAST)
    classes = (perimeter * P | legal * L).astype(np.uint16)
    return access.MaskSet(ORDER_GRID, "v-orden", "op-orden", access.MaskState.CURRENT, (),
                          classes)


def order_pit(face_deg: float) -> np.ndarray:
    """Una corta del recinto de antes con la cara ``face_deg`` (el *chamfer* hasta una recta de
    semillas va por el eje: ``k`` celdas hasta el anillo) hasta su fondo, el terreno fuera."""
    rows, columns = np.indices(ORDER_GRID.shape)
    k = np.minimum.reduce([rows - ORDER_LOW + 1, ORDER_HIGH - rows, columns - ORDER_LOW + 1,
                           ORDER_HIGH - columns])
    drop = math.tan(math.radians(face_deg)) * SCALE * ORDER_CELL_M
    return np.where(k >= 1, np.maximum(ORDER_FLOORS[face_deg], Z0 - drop * k), Z0)


def order_part(side: Any, surface: np.ndarray, order: Any) -> Any:
    """La superficie ``side`` de la cantera de la sonda, como la prepara
    ``store.prepare_refit_units``: su rejilla, su perfil con la cara de la sonda (factor de malla
    1) y de qué cantera sale, con su lado y su orden."""
    profile, face = ((qfx.FINAL_PROFILE, 35.0) if side is model.Surface.FINAL
                     else (qfx.EXPLOITATION_PROFILE, 60.0))
    name = ORDER_FINAL if side is model.Surface.FINAL else ORDER_EXPLOITATION
    values = {design_params.bench_key(profile.code, "face_deg"): face,
              design_params.bench_key(profile.code, "mesh_factor"): 1.0}
    return store.RefitPart(name, SimpleNamespace(values=surface), profile.code, (), values,
                           quarry=ORDER_QUARRY, side=side, order=order)


class RefitOrderTest(unittest.TestCase):
    """RF-014-14 frente a RF-014-27 (T53; hallazgo F-15; la decisión de Samuel del 13/11/2026: la
    propuesta por defecto) sin proyecto, con ``store.refit_compute_steps``: la sonda de la T38 (el
    terreno llano a 234,25 m, una corta con la explotación a 60° y la final a 35° atadas con «final
    primero», el límite legal 30 m más corto por el este). Ajustada cada una con la cara de su
    perfil, la final queda por encima de la explotación junto al límite nuevo (la de 35° sube más);
    si el ajuste lleva las dos superficies de la cantera, la regla de orden de la cantera las ata
    otra vez y el resumen dice las celdas que cambió; con una sola, un aviso si queda del lado
    equivocado de la otra. Los m³ de ajuste de cada superficie siguen siendo los de su cara
    (CE-014-08 igual)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.start = np.full(ORDER_GRID.shape, Z0)
        ordered = quarry.order_surfaces(model.Order.FINAL_FIRST, order_pit(35.0), order_pit(60.0),
                                        cls.start)
        cls.final, cls.exploitation = ordered.final, ordered.exploitation
        cls.masks = order_masks()
        labels = np.zeros(ORDER_GRID.shape, dtype=np.int16)
        cls.faced = {}  # cada una ajustada sola con la cara de su perfil (``refit_steps``)
        for name, surface, face in ((ORDER_FINAL, cls.final, REST_FACE),
                                    (ORDER_EXPLOITATION, cls.exploitation, EXPL_FACE)):
            face = refit.ProfileFace(face.code, face.name, face.face_deg, 1.0)
            cls.faced[name] = finish(refit.refit_steps(
                surface, cls.start, cls.masks, refit.face_slope(labels, face, ()), THICKNESS_M,
                name=name))

    def calculate(self, parts: tuple[Any, ...], others: dict[str, np.ndarray] | None = None,
                  masks: Any = None) -> Any:
        """``store.refit_compute_steps`` del ajuste «Ajuste T53» de ``parts`` con lo de la sonda;
        ``others``, la otra superficie de la cantera de cada una que va sola; ``masks``, otras
        máscaras que las de la sonda."""
        prepared = store.PreparedRefit(
            parts, SimpleNamespace(values=self.start), (),
            np.zeros(ORDER_GRID.shape, dtype=np.int16), {},
            SimpleNamespace(version_code="V01"),
            {name: SimpleNamespace(values=grid) for name, grid in (others or {}).items()})
        request = model.RefitRequest("Ajuste T53", [part.name for part in parts], "gis_dtm_llano")
        work = store.refit_compute_steps(request, self.masks if masks is None else masks,
                                         prepared,
                                         {design_params.VERIFY_MIN_THICKNESS: THICKNESS_M})
        while True:  # lo que devuelve (``yield from``), no el último ``Progress``
            try:
                next(work)
            except StopIteration as done:
                return done.value

    def test_each_surface_with_its_face_breaks_the_order(self) -> None:
        """RF-014-27 (T53, el rojo de la T38): antes del ajuste, ``final ≤ explotación ≤ terreno``
        en todas las celdas; ajustada cada una sola con la cara de su perfil, la final queda más de
        1 mm por encima de la explotación en 84 celdas, hasta 20,721 m (junto al límite nuevo)."""
        quarry.check_order(ORDER_QUARRY, self.final, self.exploitation, self.start, ORDER_GRID)
        above = self.faced[ORDER_FINAL].grid - self.faced[ORDER_EXPLOITATION].grid
        self.assertEqual(int(np.count_nonzero(above > quarry.ORDER_TOLERANCE_M)), 84)
        self.assertAlmostEqual(float(above.max()), 20.721, places=3)

    def test_final_first_raises_the_exploitation_to_the_refitted_final(self) -> None:
        """RF-014-14, RF-014-27, CE-014-08 (T53): con las dos superficies de la cantera, «final
        primero» deja la final ajustada con su cara y sube la explotación ajustada hasta ella
        (``máx``): ninguna celda con la final más de 1 mm por encima (``check_order`` la acepta);
        el volumen de ajuste, las celdas y la cifra de cada superficie, los de su cara; la nota
        ``des.refit_order`` dice la cantera, la superficie que cambió y sus celdas, las que la
        regla cambió más de 1 mm (en los dos idiomas; T60: no en sentido estricto), y el mensaje,
        la regla."""
        order = model.Order.FINAL_FIRST
        outcome = self.calculate((order_part(model.Surface.EXPLOITATION, self.exploitation, order),
                                  order_part(model.Surface.FINAL, self.final, order)))
        final, exploitation = (outcome.refit(ORDER_FINAL).grid,
                               outcome.refit(ORDER_EXPLOITATION).grid)
        faced_final, faced_exploitation = (self.faced[ORDER_FINAL].grid,
                                           self.faced[ORDER_EXPLOITATION].grid)
        np.testing.assert_array_equal(final, faced_final)
        np.testing.assert_array_equal(exploitation, np.maximum(faced_exploitation, faced_final))
        self.assertEqual(int(np.count_nonzero(final > exploitation + quarry.ORDER_TOLERANCE_M)),
                         0)
        quarry.check_order(ORDER_QUARRY, final, exploitation, self.start, ORDER_GRID)
        for name, item in self.faced.items():
            with self.subTest(superficie=name):
                found = outcome.refit(name)
                self.assertEqual((found.volume_m3, found.cells, found.outside_cells),
                                 (item.volume_m3, item.cells, item.outside_cells))
        self.assertEqual(outcome.figures, refit.refit_figures("Ajuste T53",
                                                              (self.faced[ORDER_EXPLOITATION],
                                                               self.faced[ORDER_FINAL])))
        ruled = int(np.count_nonzero(faced_final > faced_exploitation))
        self.assertEqual(ruled, int(np.count_nonzero(exploitation != faced_exploitation)))
        # T60 (el punto 1 de la T53): la nota cuenta las celdas que la regla cambia más de 1 mm
        # (84; las otras 56 que cambia, por menos de 3·10⁻¹⁴ m, no).
        changed = int(np.count_nonzero(faced_final - faced_exploitation
                                       > quarry.ORDER_TOLERANCE_M))
        self.assertEqual((ruled, changed), (140, 84))
        (note,) = outcome.notices
        self.assertEqual((note.code, note.severity, dict(note.values)),
                         ("des.refit_order", "note", {"quarry": ORDER_QUARRY,
                                                      "surface": ORDER_EXPLOITATION,
                                                      "cells": changed}))
        self.assertEqual(note.text(), (
            f"Regla de orden de la cantera «{ORDER_QUARRY}» con sus dos superficies ajustadas: "
            f"«{ORDER_EXPLOITATION}» cambia en {changed} celdas para que final ≤ explotación ≤ "
            "terreno; el volumen de ajuste de cada una sigue siendo el de la cara de su perfil."))
        self.assertIn(f"«{ORDER_EXPLOITATION}» changes in {changed} cells so that final ≤ "
                      "exploitation ≤ terrain", note.text("en"))
        self.assertIn("cambia en 1 celda para", messages.render("des.refit_order", cells=1))
        self.assertIn("changes in 1 cell so", messages.render("des.refit_order", language="en",
                                                              cells=1))
        self.assertIn(f"regla de orden de la cantera «{ORDER_QUARRY}»: {changed} celdas de "
                      f"«{ORDER_EXPLOITATION}»", outcome.message)

    def test_no_note_when_the_rule_changes_no_cell(self) -> None:
        """RF-014-14, RF-014-27 (T61; lo que vio el H3): si la regla de orden de la cantera no
        cambia ninguna celda más de 1 mm —aquí, con el límite legal en el perímetro de antes, que
        no corta ninguna de las dos: no hacía falta ajustarlas—, el ajuste de las dos no lleva la
        nota ``des.refit_order`` («cambia en 0 celdas…»), ni su mensaje la regla; solo lo de cada
        superficie."""
        rows, columns = np.indices(ORDER_GRID.shape)
        perimeter = ((rows >= ORDER_LOW) & (rows < ORDER_HIGH) & (columns >= ORDER_LOW)
                     & (columns < ORDER_HIGH))
        same = access.MaskSet(ORDER_GRID, "v-orden", "op-orden", access.MaskState.CURRENT, (),
                              (perimeter * P | perimeter * L).astype(np.uint16))
        order = model.Order.FINAL_FIRST
        outcome = self.calculate((order_part(model.Surface.EXPLOITATION, self.exploitation, order),
                                  order_part(model.Surface.FINAL, self.final, order)), masks=same)
        self.assertEqual([notice.code for notice in outcome.notices],
                         ["des.refit_not_needed", "des.refit_not_needed"])
        self.assertEqual(outcome.order_notices, ())
        self.assertNotIn("regla de orden", outcome.message)
        np.testing.assert_array_equal(outcome.refit(ORDER_FINAL).grid, self.final)
        np.testing.assert_array_equal(outcome.refit(ORDER_EXPLOITATION).grid, self.exploitation)

    def test_exploitation_first_lowers_the_final_to_the_refitted_exploitation(self) -> None:
        """RF-014-13, RF-014-14 (T53): con «explotación primero», la explotación ajustada se queda
        y la final ajustada baja hasta ella (``mín``); la nota nombra la final."""
        order = model.Order.EXPLOITATION_FIRST
        outcome = self.calculate((order_part(model.Surface.FINAL, self.final, order),
                                  order_part(model.Surface.EXPLOITATION, self.exploitation,
                                             order)))
        faced_final, faced_exploitation = (self.faced[ORDER_FINAL].grid,
                                           self.faced[ORDER_EXPLOITATION].grid)
        np.testing.assert_array_equal(outcome.refit(ORDER_EXPLOITATION).grid, faced_exploitation)
        np.testing.assert_array_equal(outcome.refit(ORDER_FINAL).grid,
                                      np.minimum(faced_final, faced_exploitation))
        self.assertEqual(outcome.refit(ORDER_FINAL).volume_m3,
                         self.faced[ORDER_FINAL].volume_m3)
        (note,) = outcome.notices
        self.assertEqual(dict(note.values), {
            "quarry": ORDER_QUARRY, "surface": ORDER_FINAL,
            "cells": int(np.count_nonzero(faced_final - faced_exploitation
                                          > quarry.ORDER_TOLERANCE_M))})

    def test_a_broken_order_after_the_rule_is_a_program_error(self) -> None:
        """RF-014-14 (T53): las dos ajustadas pasan por ``check_order`` antes de ofrecer «Crear»:
        si la regla no las atara, ``des.quarry_order_broken`` nombrando la cantera."""
        order = model.Order.FINAL_FIRST

        def untied(order: Any, final: Any, exploitation: Any, start: Any) -> Any:
            return quarry.OrderedSurfaces(final, exploitation, model.Order(order), 0)

        with mock.patch.object(quarry, "order_surfaces", untied):
            with self.assertRaises(messages.DesignError) as caught:
                self.calculate((order_part(model.Surface.EXPLOITATION, self.exploitation, order),
                                order_part(model.Surface.FINAL, self.final, order)))
        self.assertEqual((caught.exception.code, caught.exception.obj),
                         ("des.quarry_order_broken", f"Cantera «{ORDER_QUARRY}»"))

    def test_one_surface_alone_warns_when_it_ends_on_the_wrong_side(self) -> None:
        """RF-014-14 (T53): con una sola de las dos superficies de la cantera, la ajustada no se
        ata (la de su cara), y si queda del lado equivocado de la otra (la final más de 1 mm por
        encima de la explotación) el aviso ``des.refit_order_side`` lo dice con la cantera, las
        dos superficies, las celdas y cuánto por encima; la explotación sola, que el ajuste solo
        sube, no avisa."""
        order = model.Order.FINAL_FIRST
        alone = self.calculate((order_part(model.Surface.FINAL, self.final, order),),
                               {ORDER_EXPLOITATION: self.exploitation})
        faced = self.faced[ORDER_FINAL]
        np.testing.assert_array_equal(alone.refit(ORDER_FINAL).grid, faced.grid)
        above = faced.grid - self.exploitation
        broken = above > quarry.ORDER_TOLERANCE_M
        self.assertGreater(int(np.count_nonzero(broken)), 0)
        (warning,) = alone.notices
        self.assertEqual((warning.code, warning.severity, dict(warning.values)), (
            "des.refit_order_side", "warning",
            {"surface": ORDER_FINAL, "quarry": ORDER_QUARRY, "other": ORDER_EXPLOITATION,
             "cells": int(np.count_nonzero(broken)),
             "above": round(float(above[broken].max()), 3)}))
        for language, shown in (("es", "final ≤ explotación ≤ terreno"),
                                ("en", "final ≤ exploitation ≤ terrain")):
            with self.subTest(idioma=language):
                text = warning.text(language)
                for value in (ORDER_FINAL, ORDER_QUARRY, ORDER_EXPLOITATION, shown):
                    self.assertIn(value, text)
        self.assertIn("en 1 celda,", messages.render("des.refit_order_side", cells=1))
        self.assertIn("in 1 cell,", messages.render("des.refit_order_side", language="en",
                                                    cells=1))
        exploitation = self.calculate(
            (order_part(model.Surface.EXPLOITATION, self.exploitation, order),),
            {ORDER_FINAL: self.final})
        self.assertEqual(exploitation.notices, ())
        np.testing.assert_array_equal(exploitation.refit(ORDER_EXPLOITATION).grid,
                                      self.faced[ORDER_EXPLOITATION].grid)

    def test_two_of_one_side_are_not_tied(self) -> None:
        """RF-014-14 (T53): con dos superficies de un mismo lado de la cantera (la final y otra
        que sale de ella) y la explotación, no se sabe a cuál atarla: ninguna se ata y cada una se
        compara con la otra de la cantera tal como está (las dos finales avisan; la explotación,
        no)."""
        order = model.Order.FINAL_FIRST
        twin = dataclasses.replace(order_part(model.Surface.FINAL, self.final, order),
                                   name="des_adj_otro_des_fin_corta_t53")
        outcome = self.calculate(
            (order_part(model.Surface.EXPLOITATION, self.exploitation, order),
             order_part(model.Surface.FINAL, self.final, order), twin),
            {ORDER_FINAL: self.final, ORDER_EXPLOITATION: self.exploitation})
        for name in (ORDER_FINAL, ORDER_EXPLOITATION):
            np.testing.assert_array_equal(outcome.refit(name).grid, self.faced[name].grid)
        self.assertEqual([(notice.code, notice.values["surface"]) for notice in outcome.notices],
                         [("des.refit_order_side", ORDER_FINAL),
                          ("des.refit_order_side", twin.name)])


# --- La operación (con proyecto) ------------------------------------------------------------------

START = qfx.START_DATASET
EXPL, REST = qfx.EXPLOITATION_PROFILE, qfx.FINAL_PROFILE
BY_HAND = {"source": "Perfil de prueba", "source_kind": "person", "decided_by": "Samuel (IMGA)"}
QUARRY_NAME = "Corta E8"
NAME = "Ajuste E8"
EXPLOITATION = provenance.dataset_name("exp", QUARRY_NAME)
FINAL = provenance.dataset_name("fin", QUARRY_NAME)
ADJUSTED = {EXPLOITATION: provenance.refit_output(NAME, EXPLOITATION),
            FINAL: provenance.refit_output(NAME, FINAL)}
CREATED_STEP = ("des.edge_surface_step", "des.edge_stretch")
"""Los códigos del salto creado de cada superficie ajustada en el resumen (T56)."""


def recompute_function(request: Any) -> Any:
    """Lo que registra ``bl`` como función de recálculo: lleva los pasos hasta el final."""
    handle, work = store.recompute_run(request)
    drive(work)
    return handle


def never(request: Any) -> Any:  # nunca se llama: solo declara que se repite sola
    raise AssertionError("esta historia no recalcula ni reproduce ese tipo")


def definitions() -> tuple[Any, ...]:
    """Los tipos de la 013 y de la 014 con sus cifras, como los registra ``bl``: el ajuste con su
    función **real** de recálculo (no se reproduce)."""
    found = [*provenance.operation_defs({t: never for t in provenance.REPRODUCIBLE},
                                        {t: never for t in provenance.REPRODUCIBLE})]
    for op_type in provenance.QUARRY_VERSION_TYPES:
        recompute = recompute_function if op_type == provenance.REFIT else never
        found.append(provenance.operation_def(op_type, recompute))
    return (*found, *provenance.FIGURES, *provenance.QUARRY_FIGURES)


def declare(project: Any, clock: Any, key: str, value: object) -> None:
    """Declara el parámetro ``key`` en el proyecto."""
    clock.advance(minutes=1)
    with project.write_transaction() as conn:
        core_params.ParameterStore(project).create(
            conn, key, value, kind="ADOPTADO", reason="Prueba de la 014", **BY_HAND)


class RefitOperationTest(qfx.QuarryProjectCase):
    """RF-014-27 a RF-014-29 y RF-014-31 con proyecto (véase el módulo): la cantera «Corta E8» de
    V01 creada con el límite de la cantera; después, el límite legal 30 m más corto por el este y
    las máscaras recompiladas; el ajuste de sus dos superficies con un ángulo de más (rechazado),
    calculado, creado, recalculado y obsoleto."""

    STEP_M = qfx.COARSE_STEP_M
    """La rejilla gruesa de 2 m (T35; plan 014 §7.4): la historia no comprueba ninguna cifra hecha
    a mano con celdas de 1 m."""
    calculation: ClassVar[Any]
    stored: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_definitions(design_params.DEFINITIONS)
        core_params.register_definitions(design_params.QUARRY_DEFINITIONS)
        cls.addClassCleanup(core_params.unregister_definitions, "des")
        core_params.register_families(design_params.FAMILIES)
        cls.addClassCleanup(core_params.unregister_families, "des")
        core_params.register_definitions(res_provenance.VERIFY_DEFINITIONS)
        cls.addClassCleanup(core_params.unregister_definitions, "res")
        cls.enterClassContext(registered(*definitions()))
        for profile in (EXPL, REST):
            for param in ("height_m", "face_deg", "berm_m", "anchor_m", "mesh_factor"):
                declare(cls.project, cls.clock, design_params.bench_key(profile.code, param),
                        getattr(profile, param))
        cls.clock.advance(minutes=1)
        request = model.QuarryRequest(name=QUARRY_NAME, start=START,
                                      final=model.QuarrySide(REST.code),
                                      exploitation=model.QuarrySide(EXPL.code))
        drive(steps.quarry_run(cls.project, request, version=cls.v1.uid,
                               masks=access.load_masks(cls.project, cls.v1.uid))).result.create()
        with cls.project.read() as conn:
            (legal,) = [item for item in cstore.read_constraints(conn)
                        if item.code == "concesion"]
        cls.clock.advance(minutes=1)
        cp.edit_constraints(cls.project, [dataclasses.replace(
            legal, parts=((cfx.rectangle(*NEW_LEGAL_LOCAL),),))])
        cls.clock.advance(minutes=1)
        drive(access.ensure_masks_steps(cls.project, cls.v1.uid))
        cls.masks_new = access.load_masks(cls.project, cls.v1.uid)
        cls.before = cls.des_state()
        try:
            drive(cls.refit_steps(angles={EXPLOITATION: 35.0}))
        except messages.DesignError as error:
            cls.refused = error
        cls.refused_state = cls.des_state()
        cls.clock.advance(minutes=1)
        cls.calculation = drive(cls.refit_steps()).result
        cls.calculated = cls.des_state()
        cls.stored = cls.calculation.create()
        start, labels = qfx.terrain(cls.grid), np.zeros(cls.grid.shape, dtype=np.int16)
        thickness = float(core_params.definition(design_params.VERIFY_MIN_THICKNESS).default)
        cls.faced = {}  # cada una ajustada sola con la cara de su perfil, sin la regla de orden
        for surface, face in ((EXPLOITATION, EXPL_FACE), (FINAL, REST_FACE)):
            designed = store.read_surface(cls.project, surface, version_uid=cls.v1.uid).values
            cls.faced[surface] = finish(refit.refit_steps(
                designed, start, cls.masks_new, refit.face_slope(labels, face, ()), thickness,
                name=surface))

    @classmethod
    def refit_steps(cls, name: str = NAME, surfaces: tuple[str, ...] = (EXPLOITATION, FINAL),
                    angles: dict[str, float] | None = None, **options: Any) -> Iterator[Any]:
        options.setdefault("masks", cls.masks_new)
        request = model.RefitRequest(name, surfaces, START, angles or {})
        return steps.refit_run(cls.project, request, version=cls.v1.uid, **options)

    @classmethod
    def query_of(cls, sql: str, *values: Any) -> list[Any]:
        with cls.project.read() as conn:
            return conn.execute(sql, values).fetchall()

    @classmethod
    def des_state(cls) -> dict[str, Any]:
        """Lo que ``des`` ha dejado en el proyecto: operaciones, datos, cifras y ficheros."""
        return {
            "operations": cls.query_of("SELECT uid, op_type, status FROM gb_operation WHERE "
                                       "op_type LIKE 'des.%' ORDER BY fid"),
            "datasets": cls.query_of("SELECT name, status FROM gb_dataset WHERE name LIKE "
                                     "'des!_%' ESCAPE '!' ORDER BY name"),
            "figures": cls.query_of("SELECT count(*) FROM gb_figure WHERE key LIKE 'des.%'"),
            "files": sorted(path.name for path in (cls.root / "rasters").iterdir())}

    def grid_of(self, name: str) -> np.ndarray:
        record = self.record(name, self.v1)
        return geotiff_reader.read_geotiff(self.root / record.locator).values

    def figures_of(self, uid: str) -> dict[tuple[str, str], float]:
        return {(key, scope): value for key, scope, value in self.query_of(
            "SELECT key, scope, value FROM gb_figure WHERE operation_uid = ?", uid)}

    def thickness(self) -> float:
        return float(core_params.definition(design_params.VERIFY_MIN_THICKNESS).default)

    def test_a_calculating_writes_nothing_and_creating_registers(self) -> None:
        """RF-014-27, RF-014-29 (P-3): «Calcular» deja una rejilla por superficie en su temporal
        y no registra nada; «Crear» registra ``des.refit`` de V01 hecha con una ``des_adj_`` por
        superficie (papel ``design_surface``) y la cifra ``des.refit_m3`` de cada una; lo escrito
        es el ajuste de A13 de cada superficie con la cara de **su** perfil (60° la explotación,
        35° la final) atadas por la regla de orden de su cantera («final primero»: la explotación,
        nunca por debajo de la final; T53), la cifra de cada una es la de su cara (CE-014-08), y
        ya no deja nada fuera del límite vigente (la comprobación de la T31)."""
        for key in ("operations", "datasets", "figures"):
            self.assertEqual(self.calculated[key], self.before[key], key)
        temporaries = sorted(set(self.calculated["files"]) - set(self.before["files"]))
        self.assertEqual(len(temporaries), 2)
        for name in ADJUSTED.values():
            self.assertTrue(any(item.startswith(f"{name}_v01.tif.tmp-") for item in temporaries),
                            (name, temporaries))
        calculation = self.calculation
        self.assertEqual((calculation.op_type, calculation.name, calculation.version),
                         (provenance.REFIT, NAME, "V01"))
        self.assertEqual([spec.name for spec in calculation.specs],
                         [ADJUSTED[EXPLOITATION], ADJUSTED[FINAL]])
        uid = self.stored.handle.uid
        self.assertEqual(self.query_of("SELECT op_type, status FROM gb_operation WHERE uid = ?",
                                       uid), [(provenance.REFIT, "done")])
        roles = dict(self.query_of(
            "SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON "
            "d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'out'", uid))
        self.assertEqual(roles, {name: "design_surface" for name in ADJUSTED.values()})
        start = qfx.terrain(self.grid)
        ordered = quarry.order_surfaces(model.Order.FINAL_FIRST, self.faced[FINAL].grid,
                                        self.faced[EXPLOITATION].grid, start)
        tied = {EXPLOITATION: ordered.exploitation, FINAL: ordered.final}
        figures = {}
        for surface, expected in self.faced.items():
            with self.subTest(superficie=surface):
                written = self.grid_of(ADJUSTED[surface])
                np.testing.assert_array_equal(written, tied[surface])
                np.testing.assert_array_equal(
                    written, calculation.outcome.refit(surface).grid)
                self.assertGreater(expected.volume_m3, 0.0)
                scope = figures_mod.scope_json(provenance.refit_figure_scope(NAME, surface))
                figures[("des.refit_m3", scope)] = expected.volume_m3
        self.assertEqual(self.figures_of(uid), figures)
        self.assertIn(NAME, calculation.message)
        checks = store.limit_checks(self.project, self.v1.uid, names=tuple(ADJUSTED.values()))
        self.assertEqual(sorted(check.surface for check in checks), sorted(ADJUSTED.values()))
        self.assertEqual([check.cells for check in checks], [0, 0])
        before = store.limit_checks(self.project, self.v1.uid, names=(EXPLOITATION, FINAL))
        self.assertTrue(all(check.outside for check in before))

    def test_a_what_is_registered_repeats_the_request(self) -> None:
        """RF-014-29, RF-014-31: los ajustes son el nombre, las superficies y la de partida (lo que
        lo vuelve a pedir; el ángulo no se pide: sale del perfil) y, por superficie, la cara y el
        factor de malla con que se ajustó, los que anotó la operación que hizo su diseño (T49, P-3:
        el recálculo los vuelve a leer de ella); las entradas, cada superficie
        (``design_surface``), la de partida (``surface``) y las máscaras; los parámetros que lee
        del proyecto, el espesor mínimo y, para el salto creado de cada superficie ajustada (T56),
        el salto y el porcentaje admitidos."""
        uid = self.stored.handle.uid
        settings = json.loads(self.query_of("SELECT settings FROM gb_operation WHERE uid = ?",
                                            uid)[0][0])
        request = model.RefitRequest(NAME, (EXPLOITATION, FINAL), START)
        faces = {surface: {design_params.bench_key(profile.code, "face_deg"): profile.face_deg,
                           design_params.bench_key(profile.code, "mesh_factor"):
                               profile.mesh_factor}
                 for surface, profile in ((EXPLOITATION, EXPL), (FINAL, REST))}
        self.assertEqual(settings, provenance.refit_settings(request, faces))
        self.assertEqual(settings, {"name": NAME, "surfaces": [EXPLOITATION, FINAL],
                                    "start": START, "faces": faces})
        self.assertEqual(provenance.refit_request(settings), request)
        inputs = {(name, role) for name, role in self.query_of(
            "SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON "
            "d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'in'", uid)}
        self.assertIn((EXPLOITATION, "design_surface"), inputs)
        self.assertIn((FINAL, "design_surface"), inputs)
        self.assertIn((START, "surface"), inputs)
        self.assertTrue(any(role.startswith("masks_") for _name, role in inputs), inputs)
        params = {key for (key,) in self.query_of(
            "SELECT key FROM gb_operation_param WHERE operation_uid = ?", uid)}
        self.assertEqual(params, {design_params.VERIFY_MIN_THICKNESS,
                                  design_params.EDGE_MAX_STEP, design_params.EDGE_MIN_SHARE})
        with self.project.read() as conn:
            origin = store.design_surface_of(conn, ADJUSTED[FINAL], self.v1.uid)
        self.assertEqual((origin.op_type, origin.start), (provenance.REFIT, START))

    def test_a_the_created_step_of_each_refitted_surface_is_in_its_summary(self) -> None:
        """RF-014-20, RF-014-21 (T56; hallazgo F-18, la propuesta por defecto que aceptó Samuel):
        el resumen del ajuste dice el salto creado de cada superficie ajustada, en el orden de la
        petición, como A11 a mano sobre lo escrito (atadas por la regla de orden de su cantera):
        en las celdas que mueve cada una donde las máscaras del límite nuevo admiten mover el
        terreno (el dominio de la transición), con el espesor mínimo y el salto y el porcentaje
        admitidos (D-6). Lo que dé, con el nombre de la superficie ajustada, lo de cada superficie
        delante de la nota del orden (T53) y del aviso de la cantera obsoleta, que sigue el último
        (T54): aquí avisan las dos (en la rejilla de 2 m,
        la explotación hasta 2,49 m y la final hasta 1,26 m). El resumen enseña los 10 primeros
        tramos de cada una y cuántos faltan (T61, lo que vio el H3): de los 13 de la explotación,
        «… y 3 tramos más (un ajuste no guarda informe)»."""
        start = qfx.terrain(self.grid)
        allowed = self.masks_new.cut_allowed() | self.masks_new.fill_allowed()
        expected = []
        for surface in (EXPLOITATION, FINAL):
            grid = self.grid_of(ADJUSTED[surface])
            domain = edges.transition_domain(grid, start, self.thickness(), allowed)
            report = finish(edges.created_steps(
                grid, start, domain, self.grid, self.thickness(),
                core_params.definition(design_params.EDGE_MAX_STEP).default,
                core_params.definition(design_params.EDGE_MIN_SHARE).default))
            self.assertGreater(report.pairs, 0, surface)
            self.assertTrue(report.warned, surface)
            expected += edges.edge_notices(report, surface=ADJUSTED[surface])
        codes = ("des.edge_surface_step", "des.edge_stretch")
        notices = list(self.calculation.outcome.notices)
        self.assertEqual([notice for notice in notices if notice.code in codes], expected)
        self.assertEqual(notices[:len(expected)], expected)
        self.assertEqual([notice.code for notice in notices[len(expected):]],
                         ["des.refit_order", "des.refit_source_stale"])
        shown = list(self.calculation.notices)  # el resumen (T61)
        self.assertEqual(shown, list(edges.summary_notices(notices, reported=False)))
        more = [notice for notice in shown if notice.code.startswith("des.edge_more_")]
        self.assertEqual([(notice.code, dict(notice.values)) for notice in more],
                         [("des.edge_more_stretches_refit", {"stretches": 3})])
        self.assertEqual(more[0].text(), "… y 3 tramos más (un ajuste no guarda informe).")

    def test_a_the_order_rule_of_the_quarry_ties_its_two_refitted_surfaces(self) -> None:
        """RF-014-14, RF-014-27 (T53; hallazgo F-15): ajustadas cada una con la cara de su perfil,
        la final de «Corta E8» queda más de 1 mm por encima de su explotación junto al límite
        nuevo; el ajuste de las dos (la petición lleva la explotación y la final de la misma
        cantera) les aplica la regla de orden de la cantera, que lee de sus ajustes («final
        primero»): las dos creadas cumplen ``final ≤ explotación ≤ terreno`` a 1 mm y el resumen
        dice, en una nota, la cantera, la superficie que cambió y sus celdas."""
        start = qfx.terrain(self.grid)
        final, exploitation = self.faced[FINAL].grid, self.faced[EXPLOITATION].grid
        with np.errstate(invalid="ignore"):
            self.assertGreater(
                int(np.count_nonzero(final > exploitation + quarry.ORDER_TOLERANCE_M)), 0)
            changed = int(np.count_nonzero(final - exploitation > quarry.ORDER_TOLERANCE_M))
        written = {surface: self.grid_of(ADJUSTED[surface]) for surface in (FINAL, EXPLOITATION)}
        quarry.check_order(QUARRY_NAME, written[FINAL], written[EXPLOITATION], start, self.grid)
        notes = [dict(notice.values) for notice in self.calculation.notices
                 if notice.code == "des.refit_order"]
        self.assertEqual(notes, [{"quarry": QUARRY_NAME, "surface": EXPLOITATION,
                                  "cells": changed}])
        self.assertNotIn("des.refit_order_side",
                         [notice.code for notice in self.calculation.notices])

    def test_a_the_refit_of_a_stale_quarry_says_that_recomputing_it_replaces_it(self) -> None:
        """RF-014-27, RF-014-31 (T54, hallazgo F-16; la propuesta por defecto (b) que aceptó
        Samuel): el límite nuevo deja obsoleta «Corta E8» (lee las máscaras), de la que salen las
        dos superficies, así que el ajuste nace obsoleto y «Recalcular lo obsoleto» la rediseña con
        el límite vigente y rehace el ajuste sobre ella. El resumen lo avisa una sola vez por
        diseño, al final, con la cantera y las superficies que salen de ella, en los dos
        idiomas."""
        ((quarry_uid,),) = self.query_of("SELECT uid FROM gb_operation WHERE op_type = ? AND "
                                         "superseded_by IS NULL", provenance.QUARRY)
        self.assertTrue(self.stale_causes(quarry_uid), "la cantera, obsoleta por el límite nuevo")
        notices = self.calculation.notices
        stale = [notice for notice in notices if notice.code == "des.refit_source_stale"]
        self.assertEqual([dict(notice.values) for notice in stale],
                         [{"design": QUARRY_NAME, "surfaces": f"«{EXPLOITATION}», «{FINAL}»"}])
        self.assertIs(notices[-1], stale[0])
        self.assertEqual(stale[0].severity, "warning")
        self.assertEqual(stale[0].text(), (
            f"El diseño «{QUARRY_NAME}» está obsoleto: Proyecto ▸ Recalcular lo obsoleto lo "
            "vuelve a calcular con el límite vigente y después rehace sobre él este ajuste de "
            f"«{EXPLOITATION}», «{FINAL}», que sustituye al que se cree ahora."))
        self.assertIn(stale[0].text(), self.calculation.warnings())
        self.assertEqual(stale[0].text("en"), (
            f"The design «{QUARRY_NAME}» is stale: Project ▸ Recompute the stale results computes "
            "it again with the current limit and then redoes this refit of "
            f"«{EXPLOITATION}», «{FINAL}» on it, which replaces the one created now."))

    def test_b_the_final_alone_warns_when_it_ends_above_the_exploitation(self) -> None:
        """RF-014-14 (T53): el ajuste de la final de «Corta E8» sola no la ata a la explotación
        (es la de su cara); como queda más de 1 mm por encima de la explotación de la cantera, el
        resumen lo avisa (``des.refit_order_side``) con la cantera, las dos superficies, las celdas
        y cuánto por encima, sin escribir nada; y, detrás, que la cantera de la que sale está
        obsoleta (T54). Delante de los dos, el salto creado de la final ajustada (T56), con el
        nombre de su salida."""
        before = self.des_state()
        with drive(self.refit_steps("Solo la final", (FINAL,))).result as alone:
            (only,) = alone.outcome.refits
            np.testing.assert_array_equal(only.grid, self.faced[FINAL].grid)
            with np.errstate(invalid="ignore"):
                above = only.grid - self.grid_of(EXPLOITATION)
                broken = above > quarry.ORDER_TOLERANCE_M
            self.assertGreater(int(np.count_nonzero(broken)), 0)
            notices = alone.notices
            self.assertEqual([(notice.code, dict(notice.values)) for notice in notices
                              if notice.code not in CREATED_STEP], [
                ("des.refit_order_side", {"surface": FINAL, "quarry": QUARRY_NAME,
                                          "other": EXPLOITATION,
                                          "cells": int(np.count_nonzero(broken)),
                                          "above": round(float(above[broken].max()), 3)}),
                ("des.refit_source_stale", {"design": QUARRY_NAME, "surfaces": f"«{FINAL}»"})])
            created = notices[:-2]
            self.assertTrue(created and all(notice.code in CREATED_STEP for notice in created))
            self.assertEqual({notice.values["surface"] for notice in created},
                             {provenance.refit_output("Solo la final", FINAL)})
        self.assertEqual(self.des_state(), before)

    def test_b_the_rule_is_the_one_of_the_quarry(self) -> None:
        """RF-014-13, RF-014-14 (T53): la regla es la del ajuste «order» de la cantera de la que
        salen las dos superficies: con «explotación primero» (los ajustes de «Corta E8» leídos con
        ese orden), la explotación ajustada se queda y la final baja hasta ella; la nota nombra la
        final. Sin escribir nada."""
        real = provenance.quarry_request

        def exploitation_first(settings: Any) -> Any:
            return dataclasses.replace(real(settings), order=model.Order.EXPLOITATION_FIRST)

        final, exploitation = self.faced[FINAL].grid, self.faced[EXPLOITATION].grid
        with mock.patch.object(provenance, "quarry_request", exploitation_first):
            calculation = drive(self.refit_steps("Explotación primero")).result
        with calculation:
            np.testing.assert_array_equal(calculation.outcome.refit(EXPLOITATION).grid,
                                          exploitation)
            np.testing.assert_array_equal(calculation.outcome.refit(FINAL).grid,
                                          np.minimum(final, exploitation))
            self.assertEqual([dict(notice.values) for notice in calculation.notices
                              if notice.code == "des.refit_order"],
                             [{"quarry": QUARRY_NAME, "surface": FINAL,
                               "cells": int(np.count_nonzero(
                                   final - exploitation > quarry.ORDER_TOLERANCE_M))}])

    def test_b_another_angle_is_refused_before_writing(self) -> None:
        """CE-014-08, RF-014-28 (error 46): pedir por guion 35° para la explotación (su perfil es
        de 60°) se rechaza con ``des.refit_angle`` nombrando la superficie, su perfil y los dos
        ángulos, sin escribir nada."""
        error = self.refused
        self.assertEqual(error.code, "des.refit_angle")
        self.assertIn(f"«{EXPLOITATION}»", error.text)
        self.assertIn(f"«{EXPL.code}» (60°)", error.text)
        self.assertIn("con 35°", error.text)
        self.assertEqual(self.refused_state, self.before)

    def test_b_a_surface_that_is_not_of_a_design_is_refused(self) -> None:
        """RF-014-27: la superficie de partida, la envolvente de la cantera o un nombre que la
        versión no tiene no se ajustan: ``des.edge_not_design_surface`` nombrándolos, sin escribir
        nada."""
        before = self.des_state()
        envelope = provenance.dataset_name("fen", QUARRY_NAME)
        for surface in (START, envelope, "des_fin_no_existe"):
            with self.subTest(surface=surface):
                with self.assertRaises(messages.DesignError) as caught:
                    drive(self.refit_steps("Otro", (surface,)))
                self.assertEqual(caught.exception.code, "des.edge_not_design_surface")
                self.assertIn(surface, caught.exception.text)
        self.assertEqual(self.des_state(), before)

    def test_b_an_adjusted_surface_needs_no_refit(self) -> None:
        """RF-014-27 (spec §8), P-3: la superficie ajustada ya no deja nada fuera: ajustarla otra
        vez es de 0 m³ con el aviso ``des.refit_not_needed``; su perfil es el de la superficie de
        la que sale (la explotación de la cantera), y el diseño del que sale, la cantera obsoleta
        (T54: recalcularla lo sustituye). Su salto creado (T56) es el de la superficie ajustada,
        que no cambia: el mismo aviso y los mismos tramos que el del primer ajuste, con el nombre
        de su salida."""
        with self.project.read() as conn:
            origin = store.design_surface_of(conn, ADJUSTED[EXPLOITATION], self.v1.uid)
            self.assertEqual(store.refit_profiles(conn, origin, self.v1.uid), (EXPL.code, ()))
        with drive(self.refit_steps("Otra vez", (ADJUSTED[EXPLOITATION],))).result as again:
            (only,) = again.outcome.refits
            self.assertEqual((only.cells, only.volume_m3), (0, 0.0))
            self.assertEqual([(notice.code, dict(notice.values))
                              for notice in again.outcome.notices
                              if notice.code not in CREATED_STEP],
                             [("des.refit_not_needed", {"surface": ADJUSTED[EXPLOITATION]}),
                              ("des.refit_source_stale",
                               {"design": QUARRY_NAME,
                                "surfaces": f"«{ADJUSTED[EXPLOITATION]}»"})])
            output = provenance.refit_output("Otra vez", ADJUSTED[EXPLOITATION])
            first = [{**notice.values, "surface": output}
                     for notice in self.calculation.outcome.notices if notice.code in CREATED_STEP
                     and notice.values["surface"] == ADJUSTED[EXPLOITATION]]
            self.assertTrue(first)
            self.assertEqual([dict(notice.values) for notice in again.outcome.notices
                              if notice.code in CREATED_STEP], first)

    def change(self, key: str, value: float) -> None:
        """Cambia el parámetro ``key`` del proyecto a ``value``, un minuto después."""
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            core_params.ParameterStore(self.project).change(conn, key, value=value,
                                                            reason="Prueba de la T49")
        self.clock.advance(minutes=1)

    def by_hand(self, surface: str, face_deg: float) -> Any:
        """El ajuste de ``surface`` (su dato de V01 de hoy) al límite nuevo con una cara de
        ``face_deg`` y el factor de malla del perfil de explotación (``design.refit.refit_steps``,
        como en la prueba a)."""
        face = refit.ProfileFace(EXPL.code, EXPL.code, face_deg, EXPL.mesh_factor)
        labels = np.zeros(self.grid.shape, dtype=np.int16)
        return finish(refit.refit_steps(
            self.grid_of(surface), qfx.terrain(self.grid), self.masks_new,
            refit.face_slope(labels, face, ()), self.thickness(), name=surface))

    def test_d_a_design_that_did_not_record_its_face_is_refused(self) -> None:
        """RF-014-27 (T49, hallazgo F-10; plan A13, P-3): si la operación que hizo el diseño de una
        superficie no anotó la cara o el factor de malla de su perfil, el ajuste se rechaza con
        ``des.refit_face_missing`` nombrando la superficie, el perfil y la clave, en los dos
        idiomas, sin escribir nada. Aquí, la explotación como si la hubiera escrito el ajuste ya
        creado, que solo anota el espesor mínimo."""
        real = store.design_surface_of
        other = self.stored.handle.uid

        def without(conn: Any, name: str, version_uid: str) -> Any:
            found = real(conn, name, version_uid)
            if found is None or name != EXPLOITATION:
                return found
            return dataclasses.replace(found, operation_uid=other)

        before = self.des_state()
        key = design_params.bench_key(EXPL.code, "face_deg")
        with mock.patch.object(store, "design_surface_of", without):
            with self.assertRaises(messages.DesignError) as caught:
                drive(self.refit_steps("Sin la cara", (EXPLOITATION,)))
        error = caught.exception
        self.assertEqual(error.code, "des.refit_face_missing")
        self.assertEqual((error.values["surface"], error.values["profile"], error.field),
                         (EXPLOITATION, EXPL.code, key))
        for language in ("es", "en"):
            with self.subTest(idioma=language):
                text = error.text_in(language)
                for shown in (f"«{EXPLOITATION}»", f"«{EXPL.code}»", f"«{key}»"):
                    self.assertIn(shown, text)
        self.assertEqual(self.des_state(), before)

    def test_d_the_refit_uses_the_face_recorded_by_the_operation_that_made_it(self) -> None:
        """RF-014-27, RF-014-28 (T49, hallazgo F-10; plan A13, P-3; error 46): la cara y el factor
        de malla del ajuste son los que anotó la operación que escribió el contenido de hoy de la
        superficie, no los del perfil de hoy. Con el perfil de explotación cambiado a 50° después
        de crear la cantera (diseñada con 60°), el ajuste de su explotación da los m³ del ajuste a
        mano con 60°, no los de 50°; pedir 50° por guion se rechaza nombrando la cara de 60° y
        pedir 60° vale; «Crear» anota en sus ajustes esa cara y ese factor de malla por superficie
        (``faces``) y, como parámetro, solo el espesor mínimo. Recalculada la cantera con el perfil
        de 50° (reescribe el mismo dato; con el límite nuevo ya no hace falta ajustarla), la cara
        es la de 50° que anotó la operación que escribió su contenido de hoy, no la de 60° de la
        primera: pedir 50° vale y es lo que anota; y, con la cantera al día, el resumen ya no
        avisa de que recalcularla sustituye el ajuste (T54)."""
        face_key = design_params.bench_key(EXPL.code, "face_deg")
        mesh_key = design_params.bench_key(EXPL.code, "mesh_factor")
        (quarry, settings), = self.query_of(
            "SELECT uid, settings FROM gb_operation WHERE op_type = ? AND superseded_by IS NULL",
            provenance.QUARRY)
        self.change(face_key, 50.0)
        self.addCleanup(self.change, face_key, EXPL.face_deg)
        designed, today = self.by_hand(EXPLOITATION, EXPL.face_deg), self.by_hand(EXPLOITATION,
                                                                                  50.0)
        self.assertGreater(today.volume_m3 - designed.volume_m3, 100.0)
        with self.assertRaises(messages.DesignError) as caught:
            drive(self.refit_steps("Tras el perfil", (EXPLOITATION,),
                                   angles={EXPLOITATION: 50.0}))
        self.assertEqual(caught.exception.code, "des.refit_angle")
        self.assertEqual((caught.exception.values["face"], caught.exception.values["value"]),
                         (EXPL.face_deg, 50.0))
        calculation = drive(self.refit_steps("Tras el perfil", (EXPLOITATION,),
                                             angles={EXPLOITATION: EXPL.face_deg})).result
        (only,) = calculation.outcome.refits
        np.testing.assert_array_equal(only.grid, designed.grid)
        self.assertEqual(only.volume_m3, designed.volume_m3)
        uid = calculation.create().handle.uid
        stored = json.loads(self.query_of("SELECT settings FROM gb_operation WHERE uid = ?",
                                          uid)[0][0])
        self.assertEqual(stored["faces"], {EXPLOITATION: {face_key: EXPL.face_deg,
                                                          mesh_key: EXPL.mesh_factor}})
        self.assertEqual({key for (key,) in self.query_of(
            "SELECT key FROM gb_operation_param WHERE operation_uid = ?", uid)},
            set(provenance.refit_params()))  # ni la cara ni el factor de malla (T49)
        request = recompute_mod.RecomputeRequest(self.project, quarry, provenance.QUARRY,
                                                 json.loads(settings), (), (),
                                                 version=self.v1.uid)
        _handle, work = store.recompute_run(request)
        drive(work)
        with drive(self.refit_steps("Tras recalcular", (EXPLOITATION,),
                                    angles={EXPLOITATION: 50.0})).result as again:
            self.assertEqual(again.settings["faces"], {EXPLOITATION: {face_key: 50.0,
                                                                      mesh_key: EXPL.mesh_factor}})
            self.assertNotIn("des.refit_source_stale", [notice.code for notice in again.notices])

    def test_c_the_refit_is_recomputed_with_its_settings(self) -> None:
        """RF-014-29, RF-014-31: «Recalcular lo obsoleto» repite el ajuste con sus ajustes y lo
        que lee hoy: las mismas rejillas (el mismo hash) y las mismas cifras."""
        uid = self.stored.handle.uid
        settings = json.loads(self.query_of("SELECT settings FROM gb_operation WHERE uid = ?",
                                            uid)[0][0])
        hashes = {name: self.record(name, self.v1).content_sha256 for name in ADJUSTED.values()}
        request = recompute_mod.RecomputeRequest(self.project, uid, provenance.REFIT, settings,
                                                 (), (), version=self.v1.uid)
        self.clock.advance(minutes=1)
        handle = recompute_function(request)
        self.assertEqual(self.query_of("SELECT status FROM gb_operation WHERE uid = ?",
                                       handle.uid), [("done",)])
        self.assertEqual({name: self.record(name, self.v1).content_sha256
                          for name in ADJUSTED.values()}, hashes)
        self.assertEqual(sorted(self.figures_of(handle.uid).values()),
                         sorted(self.figures_of(uid).values()))

    def test_c_then_a_changed_profile_stales_the_refit_after_its_quarry(self) -> None:
        """RF-014-31, RF-008-24, RF-008-26 (T50, hallazgo F-11): cambiar la cara del perfil de
        explotación deja obsoleta la cantera de la que sale el ajuste con la causa «cambió la
        cara» (``parameter_changed``) y, aguas abajo, el ajuste, que lee su explotación, con esa
        causa además de las que ya tenía (nace obsoleto con las de la cantera: las máscaras del
        límite nuevo; T54); «Recalcular lo obsoleto» los repite en ese orden, cantera → ajuste.
        Va tras el recálculo del ajuste y antes de las pruebas que cambian el perfil o recalculan
        la cantera; vuelve a dejar el perfil como estaba."""
        ((quarry,),) = self.query_of("SELECT uid FROM gb_operation WHERE op_type = ? AND "
                                     "superseded_by IS NULL", provenance.QUARRY)
        ((adjusted,),) = self.query_of(
            "SELECT uid FROM gb_operation WHERE op_type = ? AND superseded_by IS NULL AND "
            "settings LIKE ?", provenance.REFIT, f'%"name":"{NAME}"%')
        born = {uid: self.stale_causes(uid) for uid in (quarry, adjusted)}
        self.assertTrue(born[adjusted], "nace obsoleto con las causas de la cantera")
        face = design_params.bench_key(EXPL.code, "face_deg")
        self.change(face, EXPL.face_deg - 1.0)
        self.addCleanup(self.change, face, EXPL.face_deg)
        for uid in (quarry, adjusted):
            with self.subTest(operation=uid):
                self.assertEqual(self.stale_causes(uid) - born[uid], {("parameter_changed", face)})
                self.assertLessEqual(born[uid], self.stale_causes(uid))
        self.assertEqual(self.recompute_plan(), [(provenance.QUARRY,), (provenance.REFIT,)])


if __name__ == "__main__":
    unittest.main()

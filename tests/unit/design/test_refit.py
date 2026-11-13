# SPDX-License-Identifier: GPL-3.0-or-later
"""El ajuste de un diseño a un límite nuevo (spec 014, T32; HU-014-7; RF-014-27, RF-014-28,
RF-014-29; CE-014-08; plan 014 A13, P-3, §5.2.3; error 46 del análisis).

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
  (P-3); se recalcula (no se reproduce: depende del límite vigente).
"""

from __future__ import annotations

import dataclasses
import json
import math
import unittest
from collections.abc import Iterator
from typing import Any, ClassVar

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import constraints_project as cp
from tests.support import design_oracles as oracles
from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered

refit = import_geoblender("design.refit")
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
    """RF-014-27 a RF-014-29 con proyecto (véase el módulo): la cantera «Corta E8» de V01 creada
    con el límite de la cantera; después, el límite legal 30 m más corto por el este y las máscaras
    recompiladas; el ajuste de sus dos superficies con un ángulo de más (rechazado), calculado,
    creado y recalculado."""

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
        35° la final), y ya no deja nada fuera del límite vigente (la comprobación de la T31)."""
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
        start = qfx.terrain()
        labels = np.zeros(qfx.GRID.shape, dtype=np.int16)
        figures = {}
        for surface, face in ((EXPLOITATION, EXPL_FACE), (FINAL, REST_FACE)):
            with self.subTest(superficie=surface):
                expected = finish(refit.refit_steps(
                    self.grid_of(surface), start, self.masks_new,
                    refit.face_slope(labels, face, ()), self.thickness(), name=surface))
                written = self.grid_of(ADJUSTED[surface])
                np.testing.assert_array_equal(written, expected.grid)
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
        lo vuelve a pedir; el ángulo no se pide: sale del perfil); las entradas, cada superficie
        (``design_surface``), la de partida (``surface``) y las máscaras; los parámetros, la cara y
        el factor de malla de los perfiles de las dos superficies y el espesor mínimo."""
        uid = self.stored.handle.uid
        settings = json.loads(self.query_of("SELECT settings FROM gb_operation WHERE uid = ?",
                                            uid)[0][0])
        request = model.RefitRequest(NAME, (EXPLOITATION, FINAL), START)
        self.assertEqual(settings, provenance.refit_settings(request))
        self.assertEqual(settings, {"name": NAME, "surfaces": [EXPLOITATION, FINAL],
                                    "start": START})
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
        self.assertEqual(params, {
            *(design_params.bench_key(code, value) for code in (EXPL.code, REST.code)
              for value in ("face_deg", "mesh_factor")),
            design_params.VERIFY_MIN_THICKNESS})
        with self.project.read() as conn:
            origin = store.design_surface_of(conn, ADJUSTED[FINAL], self.v1.uid)
        self.assertEqual((origin.op_type, origin.start), (provenance.REFIT, START))

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
        la que sale (la explotación de la cantera)."""
        with self.project.read() as conn:
            origin = store.design_surface_of(conn, ADJUSTED[EXPLOITATION], self.v1.uid)
            self.assertEqual(store.refit_profiles(conn, origin, self.v1.uid), (EXPL.code, ()))
        with drive(self.refit_steps("Otra vez", (ADJUSTED[EXPLOITATION],))).result as again:
            (only,) = again.outcome.refits
            self.assertEqual((only.cells, only.volume_m3), (0, 0.0))
            self.assertEqual([notice.code for notice in again.notices],
                             ["des.refit_not_needed"])

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


if __name__ == "__main__":
    unittest.main()

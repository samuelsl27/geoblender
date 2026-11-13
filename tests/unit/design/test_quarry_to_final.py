# SPDX-License-Identifier: GPL-3.0-or-later
"""«Explotación hasta la final» (spec 014, T18; HU-014-4; RF-014-17, RF-014-18; plan 014 A9, P-2;
CE-014-05).

El aviso (RF-014-17, error 60): el **desdoblado** de más del umbral
(``des.quarry.unsplit_threshold_m``) sobre **terreno sin explotar** (la explotación a menos de 0,3 m
del terreno) en zonas conexas (4 vecinos) de más del área mínima
(``des.quarry.unsplit_min_area_ha``; la igualdad no avisa, también en coma flotante), con el área, el volumen y el centro de cada zona
(``design.quarry.unsplit_zones_steps``). El modo (RF-014-18; P-2: por
diseño, no zona a zona): ninguna zona, todas las avisadas o las celdas del aviso dentro de una capa
de polígonos; donde se aplica, la explotación baja con bancos de su perfil anclados a sus cotas
hasta la cota de su ancla inmediatamente por encima de la final, ``T = a + h·⌈(final − a)/h⌉``, sin
quedar por debajo de la final y con transición al resto a la cara de su perfil:
``máx(final, mín(explotación, ENV↑(T, tan(cara)·malla)))`` (``design.quarry.to_final_steps``); el
volumen que pasa del desdoblado a la explotación es ``Σ (antes − después) · área de celda``.

Las reglas, con una rejilla a mano de 100 × 200 celdas de 2 m (la zona de 2 ha con 10 m de
desdoblado de CE-014-05 y una de cada caso que no se avisa) y, el ``ENV↑`` exacto, frente a la
fuerza bruta; ``quarry_steps`` con los dos lados sustituidos por esas rejillas (el orden, la
clasificación, el aviso, los tres modos, las tres anclas y las cifras).
"""

from __future__ import annotations

import math
import unittest
from types import SimpleNamespace
from typing import Any, ClassVar
from unittest import mock

import numpy as np

from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender

quarry = import_geoblender("design.quarry")
model = import_geoblender("design.model")
params = import_geoblender("design.params")
seeds_mod = import_geoblender("design.seeds")
messages = import_geoblender("design.messages")
envelopes = import_geoblender("design.envelopes")
provenance = import_geoblender("design.provenance")
store = import_geoblender("design.store")
figures_module = import_geoblender("core.provenance.figures")
project_model = import_geoblender("core.project.model")
gis_grid = import_geoblender("gis.grid")

NAN = math.nan
CellClass = model.CellClass
Surface = model.Surface
SectorRef = seeds_mod.SectorRef
SECTORS = (SectorRef("sector_1", "Sector oeste"), SectorRef("sector_2", "Sector este"))
EXPL = qfx.EXPLOITATION_PROFILE
REST = qfx.FINAL_PROFILE
MIN_THICKNESS_M = 0.02
THRESHOLD_M = 1.0
MIN_AREA_HA = 0.2
"""Los valores por defecto de D-5 (ADOPTADO «sin confirmar»): 1 m y 0,2 ha."""


def last_result(steps: Any) -> Any:
    found = None
    for found in steps:
        pass
    return found.result


def profile_values() -> dict[str, object]:
    """Los parámetros de los dos perfiles de la cantera (clave → valor)."""
    found: dict[str, object] = {}
    for profile in (EXPL, REST):
        for param, value in (("height_m", profile.height_m), ("face_deg", profile.face_deg),
                             ("berm_m", profile.berm_m), ("anchor_m", profile.anchor_m),
                             ("mesh_factor", profile.mesh_factor)):
            found[params.bench_key(profile.code, param)] = value
    return found


# --- La rejilla a mano ---------------------------------------------------------------------------

GRID = gis_grid.Grid(500_000.0, 4_400_200.0, 2.0, 2.0, 200, 100)
"""100 filas × 200 columnas de 2 m (4 m² por celda): el centro de la celda (fila ``i``, columna
``j``) está en ``x = 500.000 + (j + 0,5)·2``, ``y = 4.400.200 − (i + 0,5)·2``."""
Z = 194.5
"""El terreno, llano (exacto en binario)."""
PIT = 185.0
"""La explotación y la final del fondo del dominio: excavado y sin diferencia."""
BOXES = {
    "M": (10, 60, 10, 110),   # CE-014-05: 2 ha (5.000 celdas) con 10 m de desdoblado sin explotar
    "S": (75, 85, 10, 20),    # lo mismo en 400 m² (0,04 ha): bajo el área mínima, sin aviso
    "D": (10, 35, 130, 155),  # 1 m de desdoblado exacto (= el umbral): sin aviso
    "P": (45, 70, 130, 155),  # 10 m de desdoblado con la explotación 0,5 m bajo el terreno
    "R": (70, 95, 60, 85),    # 10 m dentro de una zona de restauración por relleno: relleno
    "W": (70, 95, 165, 190),  # 3,25 m sin explotar (0,25 m bajo el terreno), 0,25 ha: aviso
}
"""Filas y columnas (de la primera a la última más uno) de cada rectángulo."""
LEVELS = {"M": (Z, 184.5), "S": (Z, 184.5), "D": (Z, 193.5), "P": (194.0, 184.0),
          "R": (Z, 184.5), "W": (194.25, 191.0)}
"""La explotación y la final de cada rectángulo (m)."""


def box(name: str) -> np.ndarray:
    """La máscara del rectángulo ``name``."""
    row0, row1, col0, col1 = BOXES[name]
    found = np.zeros(GRID.shape, bool)
    found[row0:row1, col0:col1] = True
    return found


def hand_case() -> dict[str, Any]:
    """Las dos superficies ya ordenadas, el terreno, el dominio (filas 2 a 97, columnas 2 a 197;
    ``sector_1`` las columnas 0 a 99 y ``sector_2`` las demás) y la zona de relleno (``R``).
    Fuera del dominio las dos son el terreno (y la celda (0, 0) no tiene dato); dentro, el fondo
    (185 m, excavado y sin diferencia) y los rectángulos de :data:`BOXES`, a 10 celdas o más de
    los demás, para que la transición de uno no toque a otro."""
    terrain = np.full(GRID.shape, Z)
    terrain[0, 0] = NAN
    rows, cols = np.indices(GRID.shape)
    domain = (rows >= 2) & (rows < 98) & (cols >= 2) & (cols < 198)
    exploitation = np.where(domain, PIT, terrain)
    final = exploitation.copy()
    for name, (upper, lower) in LEVELS.items():
        inside = box(name)
        exploitation[inside], final[inside] = upper, lower
    labels = np.where(cols < 100, 1, 2).astype(np.int16)
    return {"terrain": terrain, "exploitation": exploitation, "final": final,
            "domain": seeds_mod.domain_of(domain, labels, SECTORS, GRID.cell_area),
            "fill": box("R")}


def classify(case: dict[str, Any], exploitation: np.ndarray | None = None) -> Any:
    return last_result(quarry.classify_steps(
        case["final"], case["exploitation"] if exploitation is None else exploitation,
        case["terrain"], case["domain"], GRID, MIN_THICKNESS_M, fill_zones=case["fill"]))


def zones_of(case: dict[str, Any], **changes: Any) -> Any:
    values: dict[str, Any] = {"threshold_m": THRESHOLD_M, "min_area_ha": MIN_AREA_HA}
    values.update(changes)
    return last_result(quarry.unsplit_zones_steps(
        case["final"], case["exploitation"], case["terrain"], classify(case), GRID, **values))


def centre(name: str) -> tuple[float, float]:
    """El centro absoluto del rectángulo ``name`` a mano: la media de los centros de celda."""
    row0, row1, col0, col1 = BOXES[name]
    return (GRID.west + ((col0 + col1 - 1) / 2 + 0.5) * GRID.dx,
            GRID.north - ((row0 + row1 - 1) / 2 + 0.5) * GRID.dy)


def cells(name: str) -> int:
    row0, row1, col0, col1 = BOXES[name]
    return (row1 - row0) * (col1 - col0)


FINE = gis_grid.Grid(500_000.0, 4_400_100.0, 1.0, 1.0, 80, 40)
"""40 filas × 80 columnas de 1 m (1 m² por celda), para la frontera del área mínima."""
FINE_ZONES = {29: (1, 2, 1, 30), 30: (3, 4, 1, 31), 51: (5, 8, 1, 18), 52: (9, 13, 1, 14),
              700: (15, 25, 1, 71), 701: (27, 37, 1, 71)}
"""Las zonas de :func:`fine_case` por su número de celdas: filas y columnas (de la primera a la
última más uno) de su rectángulo; la de 701 es el de 700 y la celda (37, 1), debajo."""


def fine_case() -> dict[str, Any]:
    """Las zonas de :data:`FINE_ZONES` en :data:`FINE`, a una fila vacía o más unas de otras: el
    terreno llano, la explotación en el terreno (sin explotar) y la final 10 m por debajo en las
    zonas (desdoblado) y en el terreno fuera (sin diferencia); el dominio, toda la rejilla, en el
    primer sector."""
    terrain = np.full(FINE.shape, Z)
    final = terrain.copy()
    for row0, row1, col0, col1 in FINE_ZONES.values():
        final[row0:row1, col0:col1] = Z - 10.0
    final[37, 1] = Z - 10.0
    domain = seeds_mod.domain_of(np.ones(FINE.shape, bool), np.ones(FINE.shape, np.int16),
                                 SECTORS[:1], FINE.cell_area)
    return {"terrain": terrain, "exploitation": terrain.copy(), "final": final, "domain": domain}


# --- El aviso (RF-014-17) -------------------------------------------------------------------------


class UnsplitZonesTest(unittest.TestCase):
    """RF-014-17 (error 60; D-5): las zonas de desdoblado sobre terreno sin explotar, a mano."""

    case: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.case = hand_case()

    def test_ce_014_05_the_zone_of_2_ha_is_warned(self) -> None:
        """CE-014-05 (primera mitad): la zona de 2 ha con 10 m de desdoblado sobre terreno sin
        explotar da el aviso con su área (2 ha), su volumen (10 m · 20.000 m² = 200.000 m³) y el
        centro de sus celdas en absolutas; la de 0,25 ha con 3,25 m (8.125 m³), también. Las zonas
        se numeran por su primera celda fila a fila."""
        found = zones_of(self.case)
        self.assertIsInstance(found, quarry.UnsplitZones)
        self.assertEqual(len(found.zones), 2)
        first, second = found.zones
        self.assertEqual((first.zone, first.cells, first.area_m2, first.volume_m3),
                         (1, 5_000, 20_000.0, 200_000.0))
        self.assertEqual(first.area_ha, 2.0)
        self.assertEqual((first.x, first.y), centre("M"))
        self.assertEqual((first.x, first.y), (500_120.0, 4_400_130.0))
        self.assertEqual((second.zone, second.cells, second.area_m2, second.volume_m3),
                         (2, 625, 2_500.0, 8_125.0))
        self.assertEqual((second.x, second.y), centre("W"))
        self.assertEqual((found.area_ha, found.volume_m3), (2.25, 208_125.0))
        self.assertEqual((found.threshold_m, found.min_area_ha), (THRESHOLD_M, MIN_AREA_HA))

    def test_what_is_not_warned(self) -> None:
        """Las celdas del aviso (``candidates``) son las del desdoblado de más del umbral sobre
        terreno sin explotar (``M``, ``S`` y ``W``); no lo son 1 m de desdoblado justo en el umbral
        (``D``: sin aviso, pero cuenta en la clasificación), la explotación a 0,5 m del terreno
        (``P``) ni lo que es relleno (``R``). La zona de 0,04 ha (``S``) es de las celdas del aviso
        pero no se avisa: bajo el área mínima (``warned``, las de las zonas avisadas)."""
        found = zones_of(self.case)
        np.testing.assert_array_equal(found.candidates, box("M") | box("S") | box("W"))
        np.testing.assert_array_equal(found.warned, box("M") | box("W"))
        classes = classify(self.case)
        self.assertTrue(bool(np.all(classes.grid[box("D")] == CellClass.UNSPLIT.code)))
        self.assertTrue(bool(np.all(classes.grid[box("P")] == CellClass.UNSPLIT.code)))
        self.assertTrue(bool(np.all(classes.grid[box("R")] == CellClass.FILL.code)))

    def test_the_bounds_of_the_threshold_and_of_the_area(self) -> None:
        """El desdoblado ha de pasar del umbral (3,25 m no pasa de 3,25 m: ``W`` sale) y la zona,
        del área mínima («de más del área mínima»): con 0,25 ha exactas, ``W`` (625 celdas de
        4 m², 2.500 m²) no se avisa (y el aviso de su única zona dice «en 1 zona», T51); con
        0,2496 ha (624 celdas), ``W`` tiene una celda más y se avisa; con 0,26 ha, no."""
        higher = zones_of(self.case, threshold_m=3.25)
        np.testing.assert_array_equal(higher.candidates, box("M") | box("S"))
        self.assertEqual([zone.cells for zone in higher.zones], [5_000])
        exact = zones_of(self.case, min_area_ha=0.25)
        self.assertEqual([zone.cells for zone in exact.zones], [5_000])
        np.testing.assert_array_equal(exact.candidates, box("M") | box("S") | box("W"))
        np.testing.assert_array_equal(exact.warned, box("M"))
        self.assertEqual(exact.notices[0], messages.render(
            "des.quarry_unsplit_zones", zones=1, area=2.0, volume=200_000.0, threshold=1.0,
            min_area=0.25))
        self.assertIn("La explotación no llega a la final en 1 zona: 2 ha", exact.notices[0])
        one_more = zones_of(self.case, min_area_ha=0.2496)
        self.assertEqual([zone.cells for zone in one_more.zones], [5_000, 625])
        above = zones_of(self.case, min_area_ha=0.26)
        self.assertEqual([zone.cells for zone in above.zones], [5_000])

    def test_the_equality_does_not_warn_in_floating_point(self) -> None:
        """«De más del área mínima», estable en coma flotante: el área mínima se da en ha y
        ``ha · 10⁴`` no siempre es el entero de m² que se tecleó (0,0029 ha da 28,999999999999996
        m²; 0,0051 ha, 51,00000000000001 m²; 0,07 ha, 700,0000000000001 m²). En celdas de 1 m
        (:data:`FINE`), la zona de justo el área mínima no se avisa en ninguno de los tres casos y la
        de una celda más, sí."""
        self.assertLess(0.0029 * 10_000.0, 29.0)
        self.assertGreater(0.0051 * 10_000.0, 51.0)
        self.assertGreater(0.07 * 10_000.0, 700.0)
        case = fine_case()
        classes = last_result(quarry.classify_steps(
            case["final"], case["exploitation"], case["terrain"], case["domain"], FINE,
            MIN_THICKNESS_M))
        for area_ha, warned in ((0.0029, [30, 51, 52, 700, 701]), (0.0051, [52, 700, 701]),
                                (0.07, [701])):
            with self.subTest(area_ha=area_ha):
                found = last_result(quarry.unsplit_zones_steps(
                    case["final"], case["exploitation"], case["terrain"], classes, FINE,
                    THRESHOLD_M, area_ha))
                self.assertEqual(int(found.candidates.sum()), sum(FINE_ZONES))
                self.assertEqual([zone.cells for zone in found.zones], warned)
                self.assertEqual([zone.area_m2 for zone in found.zones],
                                 [float(cells) for cells in warned])
                self.assertEqual(int(found.warned.sum()), sum(warned))
                self.assertEqual(found.min_area_ha, area_ha)

    def test_the_warning_text(self) -> None:
        """El aviso en español: las zonas, el área (ha) y el volumen (m³), el umbral y el área
        mínima («en zonas de más de 0,2 ha»; en inglés, «in zones of more than 0.2 ha»), y una nota
        por zona con su área, su volumen y su centro (al cm). Sin zonas, nada."""
        found = zones_of(self.case)
        warning, *notes = found.notices
        self.assertEqual(warning, messages.render(
            "des.quarry_unsplit_zones", zones=2, area=2.25, volume=208_125.0, threshold=1.0,
            min_area=0.2))
        self.assertIn("2 zonas", warning)
        self.assertIn("«Explotación hasta la final»", warning)
        self.assertIn("sobre terreno sin explotar, en zonas de más de 0,2 ha.", warning)
        self.assertIn("on unexploited terrain, in zones of more than 0.2 ha.", messages.render(
            "des.quarry_unsplit_zones", language="en", zones=2, area=2.25, volume=208_125.0,
            threshold=1.0, min_area=0.2))
        self.assertEqual(notes, [
            messages.render("des.quarry_unsplit_zone", zone=1, area=2.0, volume=200_000.0,
                            x=500_120.0, y=4_400_130.0),
            messages.render("des.quarry_unsplit_zone", zone=2, area=0.25, volume=8_125.0,
                            x=500_355.0, y=4_400_035.0)])
        self.assertEqual(zones_of(self.case, min_area_ha=1000.0).notices, ())

    def test_what_is_left_in_the_treated_cells_has_its_own_warning(self) -> None:
        """RF-014-17, RF-014-18, HU-014-4 (T57, hallazgo F-19): con las celdas donde ya se aplicó
        «explotación hasta la final» (``treated``: ``M`` y ``S``), las celdas del aviso se buscan
        por separado dentro y fuera de ellas, con el mismo umbral y la misma área mínima: fuera,
        ``W`` (zona 1), con el aviso que ofrece el modo; dentro, ``M`` (zona 2, numerada detrás) en
        ``remaining``, con el aviso de lo que queda tras el modo (menos de una altura de banco: la
        cota de ancla inmediatamente por encima de la final), que no lo ofrece; ``S`` no llega al
        área mínima. Las celdas avisadas son las de las dos; sin ``treated``, todo como antes."""
        treated = box("M") | box("S")
        found = zones_of(self.case, treated=treated)
        self.assertEqual([(zone.zone, zone.cells) for zone in found.zones], [(1, 625)])
        self.assertEqual([(zone.zone, zone.cells) for zone in found.remaining], [(2, 5_000)])
        np.testing.assert_array_equal(found.candidates, box("M") | box("S") | box("W"))
        np.testing.assert_array_equal(found.warned, box("M") | box("W"))
        self.assertEqual((found.area_ha, found.volume_m3), (0.25, 8_125.0))
        self.assertEqual((found.remaining_area_ha, found.remaining_volume_m3), (2.0, 200_000.0))
        values = {"threshold": 1.0, "min_area": 0.2}
        left = messages.render("des.quarry_unsplit_remaining", zones=1, area=2.0,
                               volume=200_000.0, **values)
        self.assertEqual(found.notices, (
            messages.render("des.quarry_unsplit_zones", zones=1, area=0.25, volume=8_125.0,
                            **values),
            messages.render("des.quarry_unsplit_zone", zone=1, area=0.25, volume=8_125.0,
                            x=500_355.0, y=4_400_035.0),
            left,
            messages.render("des.quarry_unsplit_zone", zone=2, area=2.0, volume=200_000.0,
                            x=500_120.0, y=4_400_130.0)))
        self.assertIn("Use «Explotación hasta la final»", found.notices[0])
        self.assertEqual(left, "Tras «Explotación hasta la final», la explotación sigue sin llegar "
                               "a la final en 1 zona dentro de las tratadas: 2 ha y 200000 m³ de "
                               "desdoblado de más de 1 m sobre terreno sin explotar, en una zona "
                               "de más de 0,2 ha. Es menos de una altura de banco: el modo no baja "
                               "de la cota de ancla inmediatamente por encima de la final, y allí "
                               "esa cota deja el terreno sin explotar.")
        english = messages.render("des.quarry_unsplit_remaining", language="en", zones=2,
                                  area=2.0, volume=200_000.0, **values)
        self.assertIn("still does not reach the final surface in 2 zones within the treated ones",
                      english)
        self.assertIn("less than one bench height", english)
        for language in ("es", "en"):
            for zones in (1, 2):
                with self.subTest(language=language, zones=zones):
                    text = messages.render("des.quarry_unsplit_remaining", language=language,
                                           zones=zones, area=2.0, volume=1.0, **values)
                    self.assertNotIn("Use «", text)
                    self.assertNotIn("«Use", text)
        plain = zones_of(self.case)
        self.assertEqual(plain.remaining, ())
        self.assertEqual(zones_of(self.case, treated=np.zeros(GRID.shape, bool)).notices,
                         plain.notices)
        with self.assertRaises(ValueError):
            zones_of(self.case, treated=treated[:, :10])

    def test_by_steps_and_closing(self) -> None:
        """Por pasos (fase ``unsplit``; solo el último lleva el resultado); cerrar a mitad no deja
        nada; ninguna entrada cambia."""
        before = {key: np.array(value) for key, value in self.case.items() if key != "domain"}
        classes = classify(self.case)
        steps = list(quarry.unsplit_zones_steps(
            self.case["final"], self.case["exploitation"], self.case["terrain"], classes, GRID,
            THRESHOLD_M, MIN_AREA_HA, budget_s=1e-9))
        self.assertGreaterEqual(len(steps), 2)
        self.assertTrue(all(step.phase == "unsplit" for step in steps))
        self.assertTrue(all(step.result is None for step in steps[:-1]))
        steps = quarry.unsplit_zones_steps(
            self.case["final"], self.case["exploitation"], self.case["terrain"], classes, GRID,
            THRESHOLD_M, MIN_AREA_HA, budget_s=1e-9)
        next(steps)
        steps.close()
        for key, value in before.items():
            np.testing.assert_array_equal(value, self.case[key])

    def test_rejections(self) -> None:
        """El umbral y el área mínima, como sus parámetros (``des.quarry_param_range`` fuera de
        rango, ``des.quarry_param_missing`` sin valor) al llamar; rejillas de otra forma, error del
        programa."""
        classes = classify(self.case)
        arguments = (self.case["final"], self.case["exploitation"], self.case["terrain"],
                     classes, GRID)
        for threshold, area, code in ((0.0, 0.2, "des.quarry_param_range"),
                                      (1.0, 1001.0, "des.quarry_param_range"),
                                      (None, 0.2, "des.quarry_param_missing")):
            with self.subTest(threshold=threshold, area=area), \
                    self.assertRaises(messages.DesignError) as caught:
                quarry.unsplit_zones_steps(*arguments, threshold, area)
            self.assertEqual(caught.exception.code, code)
        with self.assertRaises(ValueError):
            quarry.unsplit_zones_steps(self.case["final"][:, :10], *arguments[1:], 1.0, 0.2)


# --- Bajar la explotación (RF-014-18) -------------------------------------------------------------

SMALL = gis_grid.Grid(500_000.0, 4_400_040.0, 2.0, 2.0, 24, 20)
"""20 filas × 24 columnas de 2 m."""


def small_case() -> dict[str, Any]:
    """Una cantera pequeña con terreno inclinado, la explotación excavada a trozos, la final por
    debajo (en múltiplos de 1/4 m), unas celdas donde se aplica y un ancla que cambia por
    columna."""
    rng = np.random.default_rng(14018)
    rows, cols = np.indices(SMALL.shape)
    terrain = 150.0 + 0.25 * cols + 0.125 * rows
    domain = (rows >= 1) & (rows < 19) & (cols >= 1) & (cols < 23)
    dug = np.where(rng.random(SMALL.shape) < 0.5, 0.0, rng.integers(1, 40, SMALL.shape) / 4.0)
    exploitation = np.where(domain, terrain - dug, terrain)
    final = np.where(domain, exploitation - rng.integers(0, 60, SMALL.shape) / 4.0,
                     exploitation)
    target = domain & (((rows - 6) ** 2 + (cols - 7) ** 2 <= 9) | ((rows >= 12) & (cols >= 15)
                                                                     & (cols < 19)))
    anchor = 100.0 + 0.5 * (cols % 3)
    labels = np.where(cols < 12, 1, 2).astype(np.int16)
    return {"terrain": terrain, "exploitation": exploitation, "final": final, "target": target,
            "anchor": anchor, "domain": seeds_mod.domain_of(domain, labels, SECTORS,
                                                            SMALL.cell_area)}


def brute_force(case: dict[str, Any], height: float, tan: float) -> np.ndarray:
    """A9 a mano con la distancia euclídea entre centros de celda: ``T`` en cada celda donde se
    aplica, ``ENV↑(p) = mín_q T_q + t·|p − q|``, ``máx(final, mín(explotación, ENV↑))`` en el
    dominio y ``≤ z``."""
    final, exploitation = case["final"], case["exploitation"]
    anchor = case["anchor"]
    rows, cols = np.indices(SMALL.shape)
    level = anchor + height * np.ceil((final - anchor - 1e-9) / height)
    picked = np.flatnonzero(case["target"])
    rising = np.full(SMALL.shape, np.inf)
    for index in picked:
        row, col = divmod(int(index), SMALL.ncols)
        cost = level[row, col] + tan * SMALL.dx * np.hypot(rows - row, cols - col)
        np.minimum(rising, cost, out=rising)
    inside = case["domain"].mask
    found = np.where(inside, np.maximum(final, np.minimum(exploitation, rising)), exploitation)
    return np.minimum(found, case["terrain"])


def lower(case: dict[str, Any], **changes: Any) -> Any:
    values: dict[str, Any] = {
        "anchor": case["anchor"], "height_m": 5.0,
        "slope": envelopes.SlopeField(math.tan(math.radians(50.0))), "metric": "exact"}
    values.update(changes)
    return last_result(quarry.to_final_steps(
        case["final"], case["exploitation"], case["terrain"], case["domain"], SMALL,
        values.pop("target", case["target"]), **values))


class ToFinalStepsTest(unittest.TestCase):
    """RF-014-18 (A9): la explotación bajada, frente a la fuerza bruta."""

    def test_the_exact_rising_envelope_matches_the_brute_force(self) -> None:
        """Con la métrica euclídea exacta, la explotación bajada es la de la fuerza bruta a
        ≤ 10⁻⁹ m en todas las celdas (el ancla, una rejilla por columna; la altura, 5 m; la cara,
        50°), nunca por debajo de la final ni por encima de la explotación; y el volumen que pasa
        es ``Σ (antes − después) · 4 m²``, en total y por sector."""
        case = small_case()
        found = lower(case)
        self.assertIsInstance(found, quarry.ToFinal)
        expected = brute_force(case, 5.0, math.tan(math.radians(50.0)))
        np.testing.assert_allclose(found.exploitation, expected, rtol=0.0, atol=1e-9)
        self.assertTrue(bool(np.all(found.exploitation >= case["final"])))
        self.assertTrue(bool(np.all(found.exploitation <= case["exploitation"])))
        moved = case["exploitation"] - found.exploitation
        self.assertGreater(found.lowered_cells, 20)
        self.assertAlmostEqual(found.volume_m3, float(moved.sum()) * 4.0, delta=1e-6)
        cols = np.indices(SMALL.shape)[1]
        by_sector = dict(found.sectors)
        self.assertEqual(tuple(by_sector), SECTORS)
        self.assertAlmostEqual(by_sector[SECTORS[0]], float(moved[cols < 12].sum()) * 4.0,
                               delta=1e-6)
        self.assertAlmostEqual(by_sector[SECTORS[1]], float(moved[cols >= 12].sum()) * 4.0,
                               delta=1e-6)
        np.testing.assert_array_equal(found.target, case["target"])

    def test_the_level_is_the_anchor_level_just_above_the_final(self) -> None:
        """``T = a + h·⌈(final − a)/h⌉``: con la final justo en una cota de ancla (110 m, ancla
        100 m, 5 m) la explotación baja a ella, no a la siguiente; a 0,25 m por debajo (109,75 m),
        también a 110 m (queda 0,25 m); y una zona sin otra explotación alrededor no tiene
        transición: el volumen es el de la zona a mano."""
        rows, cols = np.indices(SMALL.shape)
        terrain = np.full(SMALL.shape, 130.0)
        domain = (rows >= 1) & (rows < 19) & (cols >= 1) & (cols < 23)
        zone = (rows >= 5) & (rows < 10) & (cols >= 5) & (cols < 15)
        for level, rest in ((110.0, 0.0), (109.75, 0.25)):
            final = np.where(zone, level, terrain)
            case = {"terrain": terrain, "exploitation": terrain.copy(), "final": final,
                    "target": zone, "anchor": 100.0,
                    "domain": seeds_mod.domain_of(domain, np.zeros(SMALL.shape, np.int16), (),
                                                  SMALL.cell_area)}
            with self.subTest(level=level):
                found = lower(case, anchor=100.0, metric="chamfer5")
                np.testing.assert_array_equal(found.exploitation[zone], 110.0)
                np.testing.assert_array_equal(found.exploitation[~zone], terrain[~zone])
                self.assertEqual(float(np.max(found.exploitation[zone] - final[zone])), rest)
                self.assertEqual(found.volume_m3, 20.0 * 50 * 4.0)
                self.assertEqual(found.lowered_cells, 50)
                self.assertEqual(found.sectors, ())

    def test_nothing_to_apply_changes_nothing(self) -> None:
        """Sin celdas donde aplicar, la explotación no cambia y no pasa nada a ella."""
        case = small_case()
        found = lower(case, target=np.zeros(SMALL.shape, bool))
        np.testing.assert_array_equal(found.exploitation, case["exploitation"])
        self.assertEqual((found.volume_m3, found.lowered_cells, found.zones), (0.0, 0, ()))

    def test_the_zones_where_it_is_applied(self) -> None:
        """Las zonas conexas de las celdas donde se aplica, con su desdoblado de antes: el
        círculo y el rectángulo de la prueba, en el orden de su primera celda."""
        case = small_case()
        found = lower(case)
        self.assertEqual(len(found.zones), 2)
        delta = case["exploitation"] - case["final"]
        for zone, mask in zip(found.zones, (case["target"] & (np.indices(SMALL.shape)[0] < 10),
                                            case["target"] & (np.indices(SMALL.shape)[0] >= 12)),
                              strict=True):
            self.assertEqual(zone.cells, int(np.count_nonzero(mask)))
            self.assertAlmostEqual(zone.volume_m3, float(delta[mask].sum()) * 4.0, delta=1e-9)
        self.assertEqual(found.area_ha, sum(zone.area_m2 for zone in found.zones) / 10_000.0)

    def test_the_inputs_do_not_change_and_bad_inputs_are_program_errors(self) -> None:
        case = small_case()
        before = {key: np.array(value) for key, value in case.items() if key != "domain"}
        lower(case)
        for key, value in before.items():
            np.testing.assert_array_equal(value, case[key])
        tan = envelopes.SlopeField(math.tan(math.radians(50.0)))
        good: dict[str, Any] = {"anchor": case["anchor"], "height_m": 5.0, "slope": tan}
        sectors = envelopes.SlopeField(np.where(np.indices(SMALL.shape)[1] < 12, 1.0, 2.0))
        for target, changes in ((case["target"][:5], {}), (case["target"], {"height_m": 0.0}),
                                (case["target"], {"height_m": np.full((3, 3), 5.0)}),
                                (case["target"], {"anchor": np.zeros((3, 3))}),
                                (case["target"], {"metric": "exact", "slope": sectors})):
            values = {**good, **changes}
            with self.subTest(changes=list(changes)), self.assertRaises(ValueError):
                quarry.to_final_steps(case["final"], case["exploitation"], case["terrain"],
                                      case["domain"], SMALL, target, **values)

    def test_by_steps_and_closing(self) -> None:
        case = small_case()
        steps = quarry.to_final_steps(
            case["final"], case["exploitation"], case["terrain"], case["domain"], SMALL,
            case["target"], anchor=case["anchor"], height_m=5.0,
            slope=envelopes.SlopeField(1.0), budget_s=1e-9)
        found = list(steps)
        self.assertTrue(all(step.phase == "to_final" for step in found))
        self.assertTrue(all(step.result is None for step in found[:-1]))
        steps = quarry.to_final_steps(
            case["final"], case["exploitation"], case["terrain"], case["domain"], SMALL,
            case["target"], anchor=case["anchor"], height_m=5.0,
            slope=envelopes.SlopeField(1.0), budget_s=1e-9)
        next(steps)
        steps.close()


# --- En la cantera con dos superficies (quarry_steps) --------------------------------------------

LAYER_ZONES = np.zeros(GRID.shape, bool)
LAYER_ZONES[:, :60] = True
LAYER_ZONES[45:70, 130:140] = True
"""Los polígonos de la capa de «explotación hasta la final» como máscara: las columnas 0 a 59 (la
mitad oeste de ``M`` y toda ``S``) y una parte de ``P``, que no es del aviso."""


def fake_sides(case: dict[str, Any], anchors: Any = None) -> Any:
    """Un ``side_steps`` que da, de cada lado, la superficie de ``case`` (y de la explotación,
    las anclas «al fondo de cada muro» ``anchors``)."""

    def side_steps(job: Any, *, budget_s: float = 0.05) -> Any:
        surface = model.Surface(job.surface)
        grid = case["final"] if surface is Surface.FINAL else case["exploitation"]
        outcome = quarry.SideOutcome(surface, None, None, None,
                                     anchors if surface is Surface.EXPLOITATION else None, None,
                                     SimpleNamespace(design=grid))
        yield project_model.Progress("side", 1, 1, "lado", result=outcome)

    return side_steps


def request(**changes: Any) -> Any:
    values: dict[str, Any] = {
        "name": "Cantera a mano", "start": qfx.START_DATASET,
        "final": model.QuarrySide(base_profile=REST.code),
        "exploitation": model.QuarrySide(base_profile=EXPL.code)}
    values.update(changes)
    return model.QuarryRequest(**values)


def job(case: dict[str, Any], **changes: Any) -> Any:
    values: dict[str, Any] = {
        "request": request(), "start": case["terrain"], "masks": SimpleNamespace(grid=GRID),
        "domain": case["domain"], "values": profile_values(), "ring_cells": 3,
        "min_thickness_m": MIN_THICKNESS_M, "face_tolerance_deg": 1.0, "warning_ratio": 2.0,
        "fill_zones": case["fill"], "unsplit_threshold_m": THRESHOLD_M,
        "unsplit_min_area_ha": MIN_AREA_HA}
    values.update(changes)
    return quarry.QuarryJob(**values)


def run(case: dict[str, Any], floor_anchors: Any = None, **changes: Any
        ) -> tuple[list[Any], Any]:
    """``quarry_steps`` del trabajo de ``case`` con ``changes`` y los lados de :func:`fake_sides`:
    sus pasos y su resultado."""
    with mock.patch.object(quarry, "side_steps", fake_sides(case, floor_anchors)):
        steps = list(quarry.quarry_steps(job(case, **changes)))
    return steps, steps[-1].result


def figure_values(outcome: Any, key: str) -> dict[str | None, float]:
    """Las cifras ``key`` del resultado por sector (``None``, el total)."""
    return {item.scope.get("sector"): item.value for item in outcome.figures if item.key == key}


class QuarryToFinalTest(unittest.TestCase):
    """RF-014-17 y RF-014-18 en ``quarry_steps``, con los dos lados sustituidos por las rejillas a
    mano (el cálculo de cada lado es de la T13)."""

    case: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.case = hand_case()
        cls.none_steps, cls.none = run(cls.case)
        cls.warned_steps, cls.warned = run(cls.case, request=request(to_final="warned"))
        _steps, cls.layer = run(cls.case, request=request(
            to_final="layer", to_final_layer="gis_fea_hasta_la_final"),
            to_final_zones=LAYER_ZONES)

    def test_without_the_mode_it_warns_and_changes_nothing(self) -> None:
        """RF-014-17: sin el modo, el resultado lleva el aviso (las zonas ``M`` y ``W``) en sus
        avisos, la explotación es la del orden y no hay cifra de lo que pasa a la explotación."""
        outcome = self.none
        self.assertIn("unsplit", {step.phase for step in self.none_steps})
        self.assertNotIn("to_final", {step.phase for step in self.none_steps})
        self.assertIsNone(outcome.to_final)
        self.assertEqual([zone.cells for zone in outcome.unsplit.zones], [5_000, 625])
        self.assertEqual(outcome.notices, zones_of(self.case).notices)
        np.testing.assert_array_equal(outcome.exploitation_grid, self.case["exploitation"])
        self.assertEqual(outcome.figures, quarry.classification_figures("Cantera a mano",
                                                                        outcome.classes))
        self.assertEqual(outcome.classes.total.unsplit_m3,
                         200_000.0 + 4_000.0 + 2_500.0 + 25_000.0 + 8_125.0)

    def test_ce_014_05_down_to_the_final_in_the_warned_zones(self) -> None:
        """CE-014-05 (error 60): con «explotación hasta la final» en las zonas avisadas, la zona
        de 2 ha baja a 185 m (la cota de ancla de ``EXPL_10_60_6``, 125 + 6·10, inmediatamente
        por encima de la final, 184,5 m): quedan 0,5 m ≤ 1 m y pasan a la explotación (194,5 −
        185) · 20.000 = 190.000 m³ (171.000 en ``sector_1`` y 19.000 en ``sector_2``), con su
        cifra CALCULADO ``des.to_final_m3``; ``W`` no baja (la cota de ancla por encima de su
        final, 195 m, está por encima del terreno) y sigue avisada; lo demás no cambia."""
        outcome = self.warned
        self.assertIn("to_final", {step.phase for step in self.warned_steps})
        found = outcome.to_final
        self.assertIsInstance(found, quarry.ToFinal)
        exploitation = outcome.exploitation_grid
        np.testing.assert_array_equal(exploitation[box("M")], 185.0)
        rest = exploitation[box("M")] - outcome.final_grid[box("M")]
        self.assertLessEqual(float(rest.max()), 1.0)
        self.assertEqual(float(rest.max()), 0.5)
        others = ~box("M")
        np.testing.assert_array_equal(exploitation[others], self.case["exploitation"][others])
        np.testing.assert_array_equal(outcome.ordered.exploitation, self.case["exploitation"])
        self.assertEqual(found.volume_m3, 190_000.0)
        self.assertEqual(found.lowered_cells, 5_000)
        self.assertEqual(dict(found.sectors), {SECTORS[0]: 171_000.0, SECTORS[1]: 19_000.0})
        self.assertEqual([zone.cells for zone in found.zones], [5_000, 625])
        self.assertEqual(figure_values(outcome, "des.to_final_m3"),
                         {None: 190_000.0, "sector_1": 171_000.0, "sector_2": 19_000.0})
        units = {item.unit for item in outcome.figures if item.key == "des.to_final_m3"}
        self.assertEqual(units, {"m3"})
        self.assertTrue(all(item.kind == figures_module.ParamKind.CALCULADO
                            for item in outcome.figures))

    def test_after_the_mode_it_classifies_again_and_warns_what_is_left(self) -> None:
        """La clasificación se rehace con la explotación bajada (el desdoblado baja en los
        190.000 m³ que pasan) y el aviso dice lo que queda (solo ``W``, «en 1 zona», T51): ``W``
        es de las zonas tratadas y queda menos de una altura de banco (3,25 m de 10 m), así que su
        aviso es el de lo que queda tras el modo, sin volver a ofrecerlo (T57, hallazgo F-19); el
        invariante se cumple y los avisos dicen lo que pasó."""
        outcome = self.warned
        np.testing.assert_array_equal(outcome.classes.grid,
                                      classify(self.case, outcome.exploitation_grid).grid)
        self.assertEqual(outcome.classes.total.unsplit_m3,
                         self.none.classes.total.unsplit_m3 - 190_000.0)
        self.assertEqual(outcome.unsplit.zones, ())
        self.assertEqual([zone.cells for zone in outcome.unsplit.remaining], [625])
        np.testing.assert_array_equal(outcome.unsplit.warned, box("W"))
        self.assertIn("sigue sin llegar a la final en 1 zona dentro de las tratadas: 0,25 ha",
                      outcome.unsplit.notices[0])
        self.assertNotIn("Use «", outcome.unsplit.notices[0])
        quarry.check_order("Cantera a mano", outcome.final_grid, outcome.exploitation_grid,
                           self.case["terrain"], GRID)
        note = messages.render("des.quarry_to_final", zones=2, area=2.25, volume=190_000.0)
        self.assertEqual(outcome.to_final.notice, note)
        self.assertEqual(outcome.notices, (*outcome.unsplit.notices, note))
        self.assertIn("«Explotación hasta la final»", note)
        self.assertIn("explotación hasta la final", outcome.message)
        expected = (*quarry.classification_figures("Cantera a mano", outcome.classes),
                    *quarry.to_final_figures("Cantera a mano", outcome.to_final))
        self.assertEqual(outcome.figures, expected)

    def test_the_zones_of_a_layer(self) -> None:
        """P-2, «las de una capa»: solo las celdas del aviso dentro de sus polígonos (la mitad
        oeste de ``M`` y ``S``, aunque ``S`` no llegue al área mínima; ``P`` no es del aviso). Bajan
        a 185 m y la transición con la mitad este de ``M`` sube a la cara de ``EXPL_10_60_6``
        (60°) con el *chamfer* 5×5: las dos columnas siguientes quedan en
        ``185 + tan 60°·k·2·0,98644`` (k = 1, 2) y la tercera ya no baja. El volumen, a mano."""
        found = self.layer.to_final
        np.testing.assert_array_equal(found.target, (box("M") & LAYER_ZONES) | box("S"))
        exploitation = self.layer.exploitation_grid
        tan = math.tan(math.radians(EXPL.face_deg)) * EXPL.mesh_factor
        step = GRID.dx * envelopes.CHAMFER_SCALE
        np.testing.assert_array_equal(exploitation[10:60, 10:60], 185.0)
        np.testing.assert_array_equal(exploitation[75:85, 10:20], 185.0)
        for col, k in ((60, 1), (61, 2)):
            np.testing.assert_allclose(exploitation[10:60, col], 185.0 + tan * k * step,
                                       rtol=0.0, atol=1e-9)
        np.testing.assert_array_equal(exploitation[10:60, 62:110], Z)
        np.testing.assert_array_equal(exploitation[box("P")], self.case["exploitation"][box("P")])
        transition = 50 * 4.0 * sum(Z - (185.0 + tan * k * step) for k in (1, 2))
        expected = (2_500 + 100) * 4.0 * (Z - 185.0) + transition
        self.assertAlmostEqual(found.volume_m3, expected, delta=1e-6)
        self.assertAlmostEqual(dict(found.sectors)[SECTORS[0]], expected, delta=1e-6)
        self.assertEqual(dict(found.sectors)[SECTORS[1]], 0.0)

    def test_f19_inside_the_treated_zones_the_mode_is_not_offered_again(self) -> None:
        """RF-014-17, RF-014-18, HU-014-4, CE-014-05 (T57, hallazgo F-19; E4 de la verificación
        única, en pequeño): con «las de una capa» que cubre la mitad oeste de ``M``, ``S`` y ``W``,
        lo que queda dentro de las zonas tratadas es ``W`` (su cota de ancla, 195 m, está por
        encima del terreno: queda 3,25 m, menos de un banco de 10 m) y se avisa como lo que queda
        tras el modo, sin ofrecerlo; fuera de ellas, la mitad este de ``M`` (columnas 62 a 109,
        tras las dos de la transición: 2.400 celdas, 0,96 ha y 96.000 m³) se avisa como siempre,
        ofreciendo el modo. El resumen de la cantera (``store.quarry_notices``) dice lo mismo, con
        sus valores como números, antes de lo que pasa a la explotación."""
        layer = LAYER_ZONES | box("W")
        _steps, outcome = run(self.case, request=request(
            to_final="layer", to_final_layer="gis_fea_hasta_la_final"), to_final_zones=layer)
        np.testing.assert_array_equal(outcome.to_final.target,
                                      (box("M") & LAYER_ZONES) | box("S") | box("W"))
        np.testing.assert_array_equal(outcome.exploitation_grid[box("W")], 194.25)
        east = box("M") & (np.indices(GRID.shape)[1] >= 62)
        unsplit = outcome.unsplit
        self.assertEqual([(zone.zone, zone.cells, zone.area_m2, zone.volume_m3, zone.x, zone.y)
                          for zone in unsplit.zones],
                         [(1, 2_400, 9_600.0, 96_000.0, 500_172.0, 4_400_130.0)])
        self.assertEqual([(zone.zone, zone.cells, zone.volume_m3, zone.x, zone.y)
                          for zone in unsplit.remaining],
                         [(2, 625, 8_125.0, 500_355.0, 4_400_035.0)])
        np.testing.assert_array_equal(unsplit.warned, east | box("W"))
        warning, _zone, left, _left_zone, moved = outcome.notices
        self.assertIn("Use «Explotación hasta la final»", warning)
        self.assertTrue(left.startswith("Tras «Explotación hasta la final», la explotación sigue "
                                         "sin llegar a la final en 1 zona dentro de las tratadas"),
                        left)
        self.assertIn("menos de una altura de banco", left)
        self.assertNotIn("Use «", left)
        self.assertEqual(moved, outcome.to_final.notice)
        parts = SimpleNamespace(start=SimpleNamespace(values=self.case["terrain"]), floors=None,
                                conserve=(), corridors=None, seeds={})
        found = store.quarry_notices(request(), SimpleNamespace(grid=GRID), parts, 3, outcome,
                                     compared=True)
        self.assertEqual([notice.code for notice in found], [
            "des.quarry_unsplit_zones", "des.quarry_unsplit_zone",
            "des.quarry_unsplit_remaining", "des.quarry_unsplit_zone", "des.quarry_to_final"])
        self.assertEqual(found[2].values, {"zones": 1, "area": 0.25, "volume": 8_125.0,
                                           "threshold": 1.0, "min_area": 0.2})
        self.assertEqual(found[3].values, {"zone": 2, "area": 0.25, "volume": 8_125.0,
                                           "x": 500_355.0, "y": 4_400_035.0})
        self.assertEqual(found[0].values["zones"], 1)
        self.assertEqual(found[2].severity, "warning")
        self.assertIn("Use «", messages.render(found[0].code, **found[0].values))
        self.assertNotIn("Use «", messages.render(found[2].code, **found[2].values))

    def test_the_anchor_of_the_exploitation_side(self) -> None:
        """Las cotas de ancla son las del lado de explotación: con una rejilla de anclas a 124 m,
        ``M`` baja a 194 m y ``W``, de 194,25 a 194 m (10.000 + 625 m³); «al fondo de cada muro»
        a 120 m, ``M`` baja a 190 m (90.000 m³) y ``W`` no (su cota, 200 m)."""
        grid_side = model.QuarrySide(base_profile=EXPL.code, anchor="grid",
                                     anchor_grid="gis_dtm_anclas")
        _steps, outcome = run(self.case, request=request(to_final="warned",
                                                         exploitation=grid_side),
                              anchors={"exploitation": np.full(GRID.shape, 124.0)})
        np.testing.assert_array_equal(outcome.exploitation_grid[box("M")], 194.0)
        np.testing.assert_array_equal(outcome.exploitation_grid[box("W")], 194.0)
        self.assertEqual(outcome.to_final.volume_m3, 10_625.0)
        self.assertEqual(outcome.unsplit.zones, ())
        nearest = model.QuarrySide(base_profile=EXPL.code, anchor="nearest_floor")
        floors = quarry.FloorAnchors("gis_fea_fondos", np.full(GRID.shape, 120.0),
                                     np.zeros(GRID.shape))
        _steps, outcome = run(self.case, floors, request=request(to_final="warned",
                                                                 exploitation=nearest))
        np.testing.assert_array_equal(outcome.exploitation_grid[box("M")], 190.0)
        np.testing.assert_array_equal(outcome.exploitation_grid[box("W")], 194.25)
        self.assertEqual(outcome.to_final.volume_m3, 90_000.0)

    def test_the_job_checks_the_mode_and_its_parameters(self) -> None:
        """Errores del programa al llamar: el modo «capa» sin la máscara de sus polígonos, la
        máscara con otro modo o de otra forma; el umbral y el área mínima fuera de rango,
        ``des.quarry_param_range`` (D-5). Por defecto, los valores de los parámetros."""
        for changes in ({"request": request(to_final="layer", to_final_layer="capa")},
                        {"to_final_zones": LAYER_ZONES},
                        {"request": request(to_final="layer", to_final_layer="capa"),
                         "to_final_zones": LAYER_ZONES[:10]}):
            with self.subTest(changes=list(changes)), self.assertRaises(ValueError):
                quarry.quarry_steps(job(self.case, **changes))
        for changes in ({"unsplit_threshold_m": 0.0}, {"unsplit_min_area_ha": -1.0}):
            with self.subTest(changes=list(changes)), \
                    self.assertRaises(messages.DesignError) as caught:
                quarry.quarry_steps(job(self.case, **changes))
            self.assertEqual(caught.exception.code, "des.quarry_param_range")
        default = quarry.QuarryJob(
            request=request(), start=self.case["terrain"], masks=SimpleNamespace(grid=GRID),
            domain=self.case["domain"], values={}, ring_cells=3, min_thickness_m=0.02,
            face_tolerance_deg=1.0, warning_ratio=2.0)
        self.assertEqual((default.unsplit_threshold_m, default.unsplit_min_area_ha),
                         (params.QUARRY_PARAMS[params.UNSPLIT_THRESHOLD].default,
                          params.QUARRY_PARAMS[params.UNSPLIT_MIN_AREA].default))
        self.assertIsNone(default.to_final_zones)

    def test_the_to_final_figures(self) -> None:
        """``to_final_figures``: ``des.to_final_m3`` (m³, CALCULADO) en total y por sector con
        código, con el ámbito de ``quarry_figure_scope``."""
        found = quarry.to_final_figures("Cantera a mano", self.warned.to_final)
        self.assertEqual([item.key for item in found], ["des.to_final_m3"] * 3)
        scopes = [figures_module.scope_json(item.scope) for item in found]
        self.assertEqual(scopes, [figures_module.scope_json(provenance.quarry_figure_scope(
            "Cantera a mano", sector=sector)) for sector in (None, "sector_1", "sector_2")])
        declared = {item.key: item.unit for item in provenance.TWO_SURFACES_FIGURES}
        self.assertEqual(declared["des.to_final_m3"], "m3")


if __name__ == "__main__":
    unittest.main()

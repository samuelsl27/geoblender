# SPDX-License-Identifier: GPL-3.0-or-later
"""Casos de referencia del hito H1 de la cantera con dos superficies (spec 014, T14; HU-014-1,
HU-014-2; RF-014-01 a RF-014-11; CE-014-01, CE-014-02 y CE-014-03; plan 014 A1 a A7, §7.1).

La corta de **E1** sobre la cantera sintética de ``tests.support.quarry_fixtures`` (T01): 400 × 400
celdas de 1 m, la ladera ``180 + 0,25·y + 0,0625·x`` con el escarpe de 3 m al norte de ``y = 300``,
las máscaras de V01 y las capas leídas del proyecto. Un lado, el de explotación (``EXPL_10_60_6``,
ancla «al fondo de cada muro»), con las semillas «coronación y zonas a sostener» (anillo de 3
celdas), los fondos de 125 m y 175 m, el corredor en L de 200 m y la zona a conservar con un talud
de conservación de 35° (D-9: un dato de entrada). El techo de conservación se calcula con la
euclídea exacta, que es la que tiene un cálculo a mano; el resto, con el *chamfer* 5×5 de la 013.

Cada cifra se compara con su cálculo a mano (coordenadas locales, en m desde la esquina suroeste):

- **Recinto** (A1, RF-014-01): el rectángulo de (45, 60) a (355, 340) —perímetro ∩ límite menos el
  resguardo de 5 m hacia dentro al oeste y al este— menos la torre (las 224 celdas que tocan el
  disco abierto de 8 m de su esquina) y «sin corte» (40 × 40): 310 · 280 − 224 − 1.600 = 84.976 m².
- **Semillas** (A2, RF-014-02): la coronación de 3 celdas es el anillo de (42, 57) a (358, 343)
  fuera del rectángulo, 316 · 286 − 310 · 280 = 3.576 celdas, más los anillos de 3 celdas de los
  dos agujeros: en «sin corte», 40² − 34² = 444, y en la torre, 224 − 4 · 17 = 156 (por cuadrante,
  las celdas ``(i, j)`` con ``(i + 3)² + (j + 3)² < 64`` no tocan fuera: 5 + 4 + 4 + 3 + 1 = 17);
  ``C ∪ H`` = 3.576 + 224 + 1.600 = 5.400 celdas.
- **Fondos** (A4, RF-014-05): 80 × 80 = 6.400 celdas a 125 m y 80 × 60 = 4.800 a 175 m, bajo el
  terreno (sus mínimos, 217,65625 m y 243,90625 m, en las esquinas suroeste).
- **Corredor** (A6, RF-014-09; CE-014-03): por regiones, 110 × 20 + 70 × 20 + 3 · 10 × 10 + el
  cuarto de círculo de 10 m de la esquina exterior (79 celdas, contadas abajo) = 3.979 celdas; la
  abscisa ``σ`` es ``x − 200`` en el primer tramo, ``280 − y`` en el segundo y 120 en la esquina,
  y la cota ``125 + 0,08·σ``; mide 199,5 − 0,5 = 199 m: 200 m ± 1 celda, no los 220 m de un
  *buffer* con los extremos redondos (error 20).
- **Semillas de la envolvente**: 5.400 + 6.400 + 4.800 + 3.979 + 2.400 (la zona a conservar, que el
  techo retiene) = 22.979, todas disjuntas.
- **Techo** (A5, RF-014-07; CE-014-02): ``U = mín_q [z(q) + tan 35°·|p − q|]`` sobre las celdas de
  la zona; dentro, ``U = z``. Como ``|∇z| = 0,2577 < tan 35° = 0,7002``, fuera de la zona el mínimo
  está siempre en su anillo de celdas de borde (avanzar una celda hacia ``p`` acorta la distancia
  al menos 0,47 m, que valen 0,33 m de techo frente a ≤ 0,26 m de terreno): la fuerza bruta sobre
  las 196 celdas del anillo es el cálculo a mano. En tres celdas, además, el mínimo explícito.
- **Ancla** (A7, RF-014-11): la cota del fondo más próximo en planta y su distancia², en cinco
  celdas a mano.

Y las tres regresiones: **CE-014-01** (error 10), sembrar en toda la ladera se avisa antes de
calcular, con dos grupos de celdas, área y centro a mano —«Calcular» se para tras armar las piezas,
sin escribir nada, y solo calcula con la confirmación (T43)—, y lo que se calcula con esas semillas
no excava nada (el fondo es el terreno); con «coronación y zonas a sostener» no queda ninguna fuera.
**CE-014-02** (error 37): la corta junto a la zona a conservar mueve 0 m³ en ella y su techo es el
del cálculo a mano a ≤ 10⁻⁹ m. **CE-014-03** (error 20): el corredor de 200 m de eje y 20 m de
ancho mide 200 m ± 1 celda.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, ClassVar

import numpy as np

from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered

quarry = import_geoblender("design.quarry")
model = import_geoblender("design.model")
params = import_geoblender("design.params")
seeds_mod = import_geoblender("design.seeds")
messages = import_geoblender("design.messages")
report_mod = import_geoblender("design.report")
steps = import_geoblender("design.steps")
dprov = import_geoblender("design.provenance")
core_params = import_geoblender("core.params")
res_provenance = import_geoblender("reserves.provenance")

TOLERANCE_M = 1e-9
RING_CELLS = 3
CONSERVE_SLOPE_DEG = 35.0
"""El talud de conservación del caso (D-9: un dato de entrada, el del análisis)."""
TAN_CONSERVE = math.tan(math.radians(CONSERVE_SLOPE_DEG))
MIN_THICKNESS_M = 0.02
"""El espesor mínimo de la 012 (``res.verify.min_thickness_m``)."""
FACE_TOLERANCE_DEG = 1.0
WARNING_RATIO = 2.0
EXPL = qfx.EXPLOITATION_PROFILE
REST = qfx.FINAL_PROFILE
CORRIDOR = model.CorridorFields(qfx.CORRIDORS_LAYER, "ancho", start_level_field="cota_inicial",
                                gradient_field="pendiente")
FLOORS = model.LayerField(qfx.FLOORS_LAYER, "cota")

AREA_BOX = (45.0, 60.0, 355.0, 340.0)
"""El rectángulo del recinto antes de quitar la torre y «sin corte» (local)."""
CROWN_BOX = (42.0, 57.0, 358.0, 343.0)
"""El rectángulo del recinto ampliado en las 3 celdas de la coronación (local)."""
OUTER_RING_CELLS = 316 * 286 - 310 * 280
"""La coronación exterior, a mano: 3.576 celdas."""
NO_CUT_RING_CELLS = 40 * 40 - 34 * 34
"""El anillo de 3 celdas dentro de «sin corte», a mano: 444 celdas."""
TOWER_CORE_PER_QUADRANT = sum(1 for a in range(3, 8) for b in range(3, 8) if a * a + b * b < 64)
"""Las celdas de un cuadrante de la torre sin ninguna vecina de Chebyshev ≤ 3 fuera: 17."""
TOWER_RING_CELLS = qfx.TOWER_ZONE_CELLS - 4 * TOWER_CORE_PER_QUADRANT
"""El anillo de 3 celdas dentro de la torre, a mano: 224 − 68 = 156 celdas."""
CROWN_CELLS = OUTER_RING_CELLS + NO_CUT_RING_CELLS + TOWER_RING_CELLS
"""La coronación de 3 celdas (con los anillos de los agujeros): 4.176 celdas."""
SEED_CELLS = OUTER_RING_CELLS + qfx.TOWER_ZONE_CELLS + qfx.NO_CUT_CELLS
"""``|C ∪ H|``: 5.400 celdas."""
FLOOR_CELLS = (80 * 80, 80 * 60)
"""Las celdas de los dos fondos: 6.400 y 4.800."""
FLOOR_MIN_TERRAIN_M = (180.0 + 0.25 * 120.5 + 0.0625 * 120.5, 180.0 + 0.25 * 200.5 + 0.0625 * 220.5)
"""El terreno más bajo de cada fondo (su celda suroeste): 217,65625 m y 243,90625 m."""
CORNER_CELLS = sum(1 for i in range(10) for j in range(10) if (i + 0.5) ** 2 + (j + 0.5) ** 2 <= 100)
"""El cuarto de círculo de 10 m de la esquina exterior del corredor, celda a celda: 79."""
CORRIDOR_CELLS = 110 * 20 + 70 * 20 + 3 * 10 * 10 + CORNER_CELLS
"""Las celdas del corredor, por regiones: 3.979."""
CORRIDOR_MEASURED_M = 199.5 - 0.5
"""La longitud medida del corredor: de la primera abscisa (0,5 m) a la última (199,5 m)."""
CONSERVE_CELLS = 40 * 60
"""Las celdas de la zona a conservar: 2.400."""
ENVELOPE_SEED_CELLS = SEED_CELLS + sum(FLOOR_CELLS) + CORRIDOR_CELLS + CONSERVE_CELLS
"""Las semillas de la envolvente del lado: 22.979."""
SLOPE_SEED_CELLS = qfx.SIZE * qfx.SIZE - SEED_CELLS
"""Las semillas de «toda la ladera» fuera de ``C ∪ H``: 160.000 − 5.400 = 154.600."""
OUTSIDE_CROWN_CELLS = qfx.SIZE * qfx.SIZE - 316 * 286
"""Lo de fuera del recinto ampliado: 69.624 celdas, centradas en (200, 200)."""


def last_result(steps: Any) -> Any:
    found = None
    for found in steps:
        pass
    return found.result


def never(request: Any) -> Any:  # nunca se llama: estas pruebas no recalculan ni reproducen
    raise AssertionError("estas pruebas no recalculan ni reproducen")


def absolute(x: float, y: float) -> tuple[float, float]:
    return qfx.BASE[0] + x, qfx.BASE[1] + y


def profile_values() -> dict[str, object]:
    """Los parámetros de los dos perfiles de la cantera (clave → valor)."""
    found: dict[str, object] = {}
    for profile in (EXPL, REST):
        for param, value in (("height_m", profile.height_m), ("face_deg", profile.face_deg),
                             ("berm_m", profile.berm_m), ("anchor_m", profile.anchor_m),
                             ("mesh_factor", profile.mesh_factor)):
            found[params.bench_key(profile.code, param)] = value
    return found


def tower_by_hand() -> np.ndarray:
    """Las celdas que tocan el disco abierto de 8 m de la torre: la distancia de su punto más
    próximo a la esquina (300, 120) es < 8 m."""
    x, y = qfx.local_centers()
    tx, ty = qfx.TOWER_LOCAL
    dx = np.maximum(np.abs(x - tx) - 0.5, 0.0)
    dy = np.maximum(np.abs(y - ty) - 0.5, 0.0)
    return dx * dx + dy * dy < qfx.TOWER_OUTWARD_M ** 2


def area_by_hand() -> np.ndarray:
    return qfx.in_box(AREA_BOX) & ~tower_by_hand() & ~qfx.in_box(qfx.NO_CUT_LOCAL)


def area_centre() -> tuple[float, float]:
    """El centro (absoluto) de las celdas del recinto: el rectángulo (centro (200, 200)) menos
    «sin corte» (centro (80, 300)) y la torre (simétrica alrededor de (300, 120))."""
    cells = 310 * 280 - qfx.NO_CUT_CELLS - qfx.TOWER_ZONE_CELLS
    x = (310 * 280 * 200.0 - qfx.NO_CUT_CELLS * 80.0 - qfx.TOWER_ZONE_CELLS * 300.0) / cells
    y = (310 * 280 * 200.0 - qfx.NO_CUT_CELLS * 300.0 - qfx.TOWER_ZONE_CELLS * 120.0) / cells
    return absolute(x, y)


def corridor_by_hand() -> np.ndarray:
    """La abscisa ``σ`` (m) de cada celda del corredor, ``NaN`` fuera, por regiones: el primer tramo
    (``x − 200``), el segundo (``280 − y``), el cuadrado común (el tramo más próximo; a igual
    distancia, el primero) y el cuarto de círculo de la esquina exterior (120, el vértice)."""
    x, y = qfx.local_centers()
    sigma = np.full(x.shape, np.nan)

    def box(left: float, bottom: float, right: float, top: float) -> np.ndarray:
        return (x > left) & (x < right) & (y > bottom) & (y < top)

    first = box(200.0, 150.0, 310.0, 170.0) | box(310.0, 160.0, 320.0, 170.0)
    second = box(310.0, 80.0, 330.0, 150.0) | box(320.0, 150.0, 330.0, 160.0)
    common = box(310.0, 150.0, 320.0, 160.0)
    nearer_first = common & ((160.0 - y) <= (320.0 - x))
    corner = (x > 320.0) & (y > 160.0) & ((x - 320.0) ** 2 + (y - 160.0) ** 2 <= 100.0)
    sigma[first | nearer_first] = (x - 200.0)[first | nearer_first]
    nearer_second = second | (common & ~nearer_first)
    sigma[nearer_second] = (280.0 - y)[nearer_second]
    sigma[corner] = 120.0
    return sigma


class QuarryH1Test(qfx.QuarryProjectCase):
    """La corta de E1 y los CE-014-01 a 03 sobre la cantera sintética (una copia por clase)."""

    outcome: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        access = import_geoblender("gis.masks.access")
        gstore = import_geoblender("gis.store")
        cls.loaded = access.load_masks(cls.project, cls.v1.uid)
        cls.refs, cls.labels = seeds_mod.sector_layout(cls.project, cls.loaded)
        cls.geometry = cls.loaded.grid
        cls.start = qfx.terrain()
        cls.area = quarry.excavation_area(cls.loaded, cls.start)
        cls.domain = seeds_mod.domain_of(cls.area, cls.labels, cls.refs, cls.geometry.cell_area)
        with cls.project.read() as conn:
            floors_layer = gstore.read_features(conn, qfx.FLOORS_LAYER)
            corridors_layer = gstore.read_features(conn, qfx.CORRIDORS_LAYER)
        cls.floor_part = quarry.floor_map(floors_layer, FLOORS, cls.start, cls.geometry)
        cls.corridors = quarry.corridor_cells(corridors_layer, CORRIDOR, cls.geometry)
        cls.floors = quarry.join_floors(cls.floor_part, cls.corridors)
        cls.zone = quarry.ConserveZone("Ladera a conservar", qfx.in_box(qfx.CONSERVE_LOCAL))
        cls.ceiling = last_result(quarry.conservation_ceiling_steps(
            (cls.zone,), cls.start, cls.geometry, CONSERVE_SLOPE_DEG, metric="exact"))
        cls.request = model.QuarryRequest(
            name="Cantera E1", start=qfx.START_DATASET,
            final=model.QuarrySide(base_profile=REST.code),
            exploitation=model.QuarrySide(base_profile=EXPL.code, anchor="nearest_floor"),
            floors=FLOORS, conserve=(model.Zone("layer", qfx.CONSERVE_LAYER),),
            corridors=CORRIDOR)
        cls.outcome = last_result(quarry.side_steps(cls.job()))

    @classmethod
    def job(cls, **changes: Any) -> Any:
        values: dict[str, Any] = {
            "request": cls.request, "surface": model.Surface.EXPLOITATION, "start": cls.start,
            "masks": cls.loaded, "domain": cls.domain, "values": profile_values(),
            "ring_cells": RING_CELLS, "min_thickness_m": MIN_THICKNESS_M,
            "face_tolerance_deg": FACE_TOLERANCE_DEG, "warning_ratio": WARNING_RATIO,
            "floors": cls.floors, "ceiling": cls.ceiling}
        values.update(changes)
        return quarry.SideJob(**values)

    def at(self, grid: np.ndarray, x: float, y: float) -> float:
        """El valor de ``grid`` en la celda del centro local ``(x, y)``."""
        cx, cy = qfx.local_centers()
        return float(grid[(cx == x) & (cy == y)][0])

    # --- E1: recinto, semillas, fondos, corredor, ancla -----------------------------------

    def test_e1_excavation_area_by_hand(self) -> None:
        """RF-014-01 (A1): el recinto es, celda a celda, el rectángulo de (45, 60) a (355, 340)
        menos la torre y «sin corte», 84.976 celdas, y su cifra, 84.976 m²."""
        hand = area_by_hand()
        self.assertEqual(int(np.count_nonzero(tower_by_hand())), qfx.TOWER_ZONE_CELLS)
        self.assertEqual(int(np.count_nonzero(hand)), 310 * 280 - 224 - 1600)
        np.testing.assert_array_equal(self.area, hand)
        measured = quarry.area_outcome("Cantera E1", self.area, self.geometry)
        self.assertEqual(measured.cells, 84_976)
        self.assertEqual(measured.area_m2, 84_976.0)
        self.assertEqual([(item.key, item.value) for item in measured.figures],
                         [("des.rcn_area_m2", 84_976.0)])

    def test_e1_seeds_are_the_crown_and_the_zones_to_hold(self) -> None:
        """RF-014-02 (A2): la coronación de 3 celdas son 3.576 + 444 + 156 = 4.176 celdas, y las
        semillas del lado, el terreno en ``C ∪ H`` (5.400 celdas) y en ninguna otra."""
        ring = quarry.crown_ring(self.area, self.start, RING_CELLS)
        outer = qfx.in_box(CROWN_BOX) & ~qfx.in_box(AREA_BOX)
        no_cut = qfx.in_box(qfx.NO_CUT_LOCAL)
        tower = tower_by_hand()
        self.assertEqual(int(np.count_nonzero(outer)), OUTER_RING_CELLS)
        self.assertEqual(TOWER_CORE_PER_QUADRANT, 17)
        self.assertEqual(int(np.count_nonzero(ring & no_cut)), NO_CUT_RING_CELLS)
        self.assertEqual(int(np.count_nonzero(ring & tower)), TOWER_RING_CELLS)
        np.testing.assert_array_equal(ring & ~no_cut & ~tower, outer)
        self.assertEqual(int(np.count_nonzero(ring)), CROWN_CELLS)
        self.assertEqual(CROWN_CELLS, 4_176)
        seeds = self.outcome.seeds
        self.assertEqual(seeds.cells, SEED_CELLS)
        self.assertEqual(SEED_CELLS, 5_400)
        hand = outer | no_cut | tower
        np.testing.assert_array_equal(np.isfinite(seeds.grid), hand)
        np.testing.assert_array_equal(seeds.grid[hand], self.start[hand])

    def test_e1_floors_by_hand(self) -> None:
        """RF-014-05, RF-014-06 (A4): los fondos de la capa del proyecto son las dos cajas con su
        cota (6.400 celdas a 125 m y 4.800 a 175 m), sin solapes, y ninguno queda por encima del
        terreno (sus mínimos, a mano)."""
        found = self.floor_part
        self.assertEqual(found.levels, (125.0, 175.0))
        self.assertEqual(found.cells, FLOOR_CELLS)
        hand = np.full(self.start.shape, np.nan)
        for floor in qfx.FLOORS:
            hand[qfx.in_box(floor.box)] = floor.level_m
        np.testing.assert_array_equal(found.grid, hand)
        for floor, low in zip(qfx.FLOORS, FLOOR_MIN_TERRAIN_M, strict=True):
            self.assertEqual(float(self.start[qfx.in_box(floor.box)].min()), low)
            self.assertGreater(low, floor.level_m)
        self.assertEqual(FLOOR_MIN_TERRAIN_M, (217.65625, 243.90625))
        above = quarry.floors_above_terrain(found, self.start)
        self.assertEqual(above.cells, 0)
        self.assertIsNone(above.notice)

    def test_e1_envelope_is_seeded_by_crown_floors_corridor_and_zone(self) -> None:
        """La envolvente del lado se siembra con las 22.979 celdas de la coronación y las zonas a
        sostener, los dos fondos, el corredor y la zona a conservar (disjuntas)."""
        self.assertEqual(ENVELOPE_SEED_CELLS, 22_979)
        self.assertEqual(self.outcome.envelope_seeds.cells, ENVELOPE_SEED_CELLS)
        self.assertEqual(int(np.count_nonzero(self.zone.mask)), CONSERVE_CELLS)

    def test_e1_anchor_by_hand(self) -> None:
        """RF-014-11 (A7): la rejilla de anclas da la cota del fondo más próximo en planta y su
        distancia² entre centros de celda: dentro del fondo de 125 m (0 m²), 20 m al oeste de él
        (400 m²), 21 m al norte de la plataforma (441 m²), 10 m al oeste de la plataforma (más
        cerca que el fondo, a √1.082 m: 175 m) y 11 m al este del final del corredor (su cota en
        ``σ = 179,5``: 139,36 m)."""
        anchors = self.outcome.anchors
        self.assertIsNotNone(anchors)
        gradient = qfx.CORRIDOR_GRADIENT_PCT / 100.0
        for (x, y), level, d2 in (((160.5, 160.5), 125.0, 0.0), ((100.5, 160.5), 125.0, 400.0),
                                  ((260.5, 280.5), 175.0, 441.0), ((210.5, 230.5), 175.0, 100.0),
                                  ((340.5, 100.5), qfx.CORRIDOR_START_M + 179.5 * gradient, 121.0)):
            with self.subTest(x=x, y=y):
                self.assertAlmostEqual(self.at(anchors.grid, x, y), level, delta=TOLERANCE_M)
                self.assertEqual(self.at(anchors.d2_m2, x, y), d2)
        berms = self.outcome.design.berms.grid
        found = np.isfinite(berms)
        self.assertGreater(int(np.count_nonzero(found)), 0)
        levels, floor = berms[found], anchors.grid[found]
        k = np.round((levels - floor) / EXPL.height_m)
        self.assertLessEqual(float(np.max(np.abs(levels - (floor + k * EXPL.height_m)))),
                             TOLERANCE_M)

    def test_e1_cut_stays_in_the_area_and_reaches_the_platform(self) -> None:
        """La corta de E1: fuera del recinto, el terreno bit a bit; dentro, nunca por encima de él;
        excava (más de 1 hm³) y llega a la plataforma de 175 m: donde su cota es la de la
        envolvente (la plataforma manda sobre las paredes), la superficie es 175 m exactos. El fondo
        de 125 m no llega a mandar: la envolvente de la coronación con el talud general de
        ``EXPL_10_60_6`` (40,34°) queda por encima de él en todas sus celdas (RF-014-05: el fondo es
        un suelo, la corta es el máximo)."""
        design = self.outcome.grid
        envelope = self.outcome.envelope.grid
        np.testing.assert_array_equal(design[~self.area], self.start[~self.area])
        self.assertTrue(bool(np.all(design[self.area] <= self.start[self.area])))
        self.assertGreater(self.outcome.design.report.cut_m3, 1.0e6)
        self.assertEqual(self.outcome.design.report.fill_m3, 0.0)
        platform = qfx.in_box(qfx.FLOORS[1].box)
        rules = platform & (envelope == 175.0)
        self.assertGreater(int(np.count_nonzero(rules)), 100)
        self.assertTrue(bool(np.all(design[rules] == 175.0)))
        bottom = qfx.in_box(qfx.FLOORS[0].box)
        self.assertTrue(bool(np.all(envelope[bottom] > 125.0)))

    # --- CE-014-01 (error 10) -------------------------------------------------------------

    def test_ce01_crown_seeds_leave_none_outside(self) -> None:
        """CE-014-01, RF-014-02: con «coronación y zonas a sostener», ninguna semilla fuera."""
        self.assertEqual(quarry.outside_crown(self.outcome.seeds, self.area, self.start,
                                              self.loaded, RING_CELLS), ())

    def test_ce01_seeds_all_over_the_slope_are_warned_before_calculating(self) -> None:
        """CE-014-01, RF-014-03 (T43, hallazgo F-4): sembrar en toda la ladera da dos grupos fuera
        de ``C ∪ H`` con sus celdas, su área y su centro absoluto a mano (lo de fuera del recinto
        ampliado, centrado en (200, 200), y el recinto), 154.600 celdas en total; y «Calcular»
        (``design.steps.quarry_run``) con esas semillas en la explotación **se para antes de
        calcular**, tras armar las piezas y sin escribir nada (ni operación ni temporal): su último
        paso lleva, en lugar del cálculo, el aviso de la superficie de explotación (154.600 celdas,
        154.600 m², 2 grupos) y un grupo por nota con sus celdas, su área y su centro (a 0,005 m:
        el aviso lo redondea a centímetros). Solo con la confirmación (``confirm_outside``) pasa a
        calcular."""
        groups = quarry.outside_crown(self.start, self.area, self.start, self.loaded, RING_CELLS)
        self.assertEqual([(item.group, item.cells) for item in groups],
                         [(1, OUTSIDE_CROWN_CELLS), (2, qfx.CUT_ALLOWED_CELLS)])
        self.assertEqual(sum(item.cells for item in groups), SLOPE_SEED_CELLS)
        self.assertEqual([item.area_m2 for item in groups], [69_624.0, 84_976.0])
        centres = (absolute(200.0, 200.0), area_centre())
        for item, (x, y) in zip(groups, centres, strict=True):
            self.assertAlmostEqual(item.x, x, delta=TOLERANCE_M)
            self.assertAlmostEqual(item.y, y, delta=TOLERANCE_M)
        text = messages.render("des.quarry_seeds_outside", cells=SLOPE_SEED_CELLS,
                               area=float(SLOPE_SEED_CELLS), groups=len(groups))
        self.assertIn("2 grupos", text)
        self.assertEqual(messages.lookup("des.quarry_seeds_outside").severity, "warning")

        self.ready_to_calculate()
        request = model.QuarryRequest(
            name="Toda la ladera", start=qfx.START_DATASET,
            final=model.QuarrySide(base_profile=REST.code),
            exploitation=model.QuarrySide(base_profile=EXPL.code, seeds=model.SeedSource(
                "surface", surface=qfx.START_DATASET)))
        before = self.written()
        found = list(steps.quarry_run(self.project, request, version=self.v1.uid,
                                      masks=self.loaded))
        last = found[-1]
        self.assertEqual(last.phase, "seeds_outside")
        self.assertEqual([step.result for step in found[:-1]], [None] * (len(found) - 1))
        self.assertNotIn("quarry", {step.phase for step in found})  # no empezó a calcular
        warning, *notes = last.result
        self.assertEqual((warning.code, dict(warning.values)), ("des.quarry_seeds_outside", {
            "surface": "exploitation", "cells": SLOPE_SEED_CELLS,
            "area": float(SLOPE_SEED_CELLS), "groups": 2}))
        self.assertEqual(warning.severity, "warning")
        self.assertRegex(warning.text("es"),
                         r"^154\D600 celdas de semillas \(154\D600 m²\) en 2 grupos caen fuera")
        self.assertEqual([note.code for note in notes], ["des.quarry_seed_group"] * 2)
        for note, number, cells, (x, y) in zip(notes, (1, 2), (69_624, 84_976), centres,
                                               strict=True):
            values = dict(note.values)
            self.assertEqual((values["group"], values["cells"], values["area"]),
                             (number, cells, float(cells)))
            self.assertAlmostEqual(values["x"], x, delta=0.005)
            self.assertAlmostEqual(values["y"], y, delta=0.005)
        self.assertEqual(self.written(), before)

        work = steps.quarry_run(self.project, request, version=self.v1.uid, masks=self.loaded,
                                confirm_outside=True)
        phases = []
        for step in work:  # con la confirmación, calcula: se cancela en cuanto empieza
            phases.append(step.phase)
            if step.phase == "quarry":
                work.close()
                break
        self.assertIn("quarry", phases)
        self.assertNotIn("seeds_outside", phases)
        self.assertEqual(self.written(), before)  # cancelado: no queda nada

    def ready_to_calculate(self) -> None:
        """Lo que «Calcular» lee además del proyecto de la cantera: las definiciones, las familias,
        los tipos de operación de la 013 y de la 014 y sus cifras registrados (hasta el final de
        la prueba), y los cinco valores de los dos perfiles declarados en el proyecto."""
        core_params.register_definitions(params.DEFINITIONS)
        core_params.register_definitions(params.QUARRY_DEFINITIONS)
        self.addCleanup(core_params.unregister_definitions, "des")
        core_params.register_families(params.FAMILIES)
        self.addCleanup(core_params.unregister_families, "des")
        core_params.register_definitions(res_provenance.VERIFY_DEFINITIONS)
        self.addCleanup(core_params.unregister_definitions, "res")
        self.enterContext(registered(
            *dprov.operation_defs(dict.fromkeys(dprov.REPRODUCIBLE, never),
                                  dict.fromkeys(dprov.REPRODUCIBLE, never)),
            *dprov.quarry_operation_defs(dict.fromkeys(dprov.QUARRY_VERSION_TYPES, never),
                                         dict.fromkeys(dprov.QUARRY_REPRODUCIBLE, never)),
            *dprov.FIGURES, *dprov.QUARRY_FIGURES))
        store = core_params.ParameterStore(self.project)
        for code, values in ((EXPL.code, EXPL), (REST.code, REST)):
            for param in ("height_m", "face_deg", "berm_m", "anchor_m", "mesh_factor"):
                self.clock.advance(minutes=1)
                with self.project.write_transaction() as conn:
                    store.create(conn, params.bench_key(code, param), getattr(values, param),
                                 kind="ADOPTADO", reason="Prueba de CE-014-01",
                                 source="Perfil de prueba", source_kind="person",
                                 decided_by="Samuel (IMGA)")

    def written(self) -> tuple[Any, ...]:
        """Lo que el diseño ha dejado en el proyecto: sus operaciones y los temporales de la
        carpeta del proyecto."""
        operations = self.query("SELECT uid, op_type, status FROM gb_operation WHERE op_type "
                                "LIKE 'des.%' ORDER BY fid")
        temporaries = sorted(str(path) for path in self.root.rglob("*") if ".tmp" in path.name)
        return operations, temporaries

    def test_ce01_seeds_all_over_the_slope_raise_the_floors(self) -> None:
        """CE-014-01 (error 10): con las semillas en toda la ladera la envolvente no baja del
        terreno en el recinto (los fondos «altísimos») y el lado no excava nada; con la coronación,
        la misma corta excava más de 1 hm³. El informe del lado no lo avisa (RF-014-12, T61: lo
        avisa la cantera sobre la superficie que crea)."""
        user = model.SeedSource("surface", surface=qfx.START_DATASET, zone=model.Zone("domain"))
        request = replace(self.request, exploitation=model.QuarrySide(
            base_profile=EXPL.code, seeds=user, anchor="nearest_floor"))
        slope = seeds_mod.collect_seeds(self.start, np.isfinite(self.start), self.domain,
                                        self.geometry)
        outcome = last_result(quarry.side_steps(self.job(request=request, seeds=slope)))
        envelope = outcome.envelope.grid[self.area]
        self.assertTrue(bool(np.all(envelope >= self.start[self.area])))
        self.assertEqual(outcome.design.report.cut_m3, 0.0)
        self.assertEqual(outcome.design.report.fill_m3, 0.0)
        moved = report_mod.moved_cells(self.start, outcome.grid, MIN_THICKNESS_M)
        self.assertFalse(bool(np.any(moved)))
        self.assertGreater(self.outcome.design.report.cut_m3, 1.0e6)
        # T61 (el H3): el informe de un lado no dice «El diseño no mueve…» de la 013: el lado es
        # la superficie antes de la regla de orden y del modo; lo dice la cantera, medido sobre la
        # superficie que crea y nombrándola (``store.quarry_notices``).
        self.assertNotIn("des.no_movement",
                         [notice.code for notice in outcome.design.report.notices])

    # --- CE-014-02 (error 37) -------------------------------------------------------------

    def test_ce02_ceiling_by_hand(self) -> None:
        """CE-014-02, RF-014-07 (A5): el techo es el terreno en la zona y, fuera, el mínimo de
        ``z(q) + tan 35°·|p − q|`` sobre el anillo de borde de la zona (196 celdas) a ≤ 10⁻⁹ m en una
        ventana de 120 × 140 m alrededor; y en tres celdas, el mínimo explícito: 11 m al norte, 10 m
        al sur (las dos con el mínimo en la celda de borde una al oeste, por la pendiente al este) y
        11 m al este (con el mínimo 4 m al sur, por la pendiente al norte)."""
        ceiling = self.ceiling.grid
        zone = self.zone.mask
        np.testing.assert_array_equal(ceiling[zone], self.start[zone])
        inner = (zone & np.roll(zone, 1, 0) & np.roll(zone, -1, 0) & np.roll(zone, 1, 1)
                 & np.roll(zone, -1, 1))
        ring = zone & ~inner
        self.assertEqual(int(np.count_nonzero(ring)), 2 * 40 + 2 * 60 - 4)
        x, y = qfx.local_centers()
        window = qfx.in_box((20.0, 140.0, 140.0, 280.0)) & ~zone
        px, py = x[window], y[window]
        hand = np.full(px.shape, np.inf)
        for qx, qy, qz in zip(x[ring], y[ring], self.start[ring], strict=True):
            np.minimum(hand, qz + TAN_CONSERVE * np.hypot(px - qx, py - qy), out=hand)
        self.assertLessEqual(float(np.max(np.abs(ceiling[window] - hand))), TOLERANCE_M)

        def z(qx: float, qy: float) -> float:
            return qfx.TERRAIN_Z0 + qfx.TERRAIN_NORTH * qy + qfx.TERRAIN_EAST * qx

        for (cx, cy), expected in (
                ((80.5, 250.5), z(79.5, 239.5) + TAN_CONSERVE * math.sqrt(122.0)),
                ((80.5, 170.5), z(79.5, 180.5) + TAN_CONSERVE * math.sqrt(101.0)),
                ((110.5, 210.5), z(99.5, 206.5) + TAN_CONSERVE * math.sqrt(137.0))):
            with self.subTest(x=cx, y=cy):
                self.assertAlmostEqual(self.at(ceiling, cx, cy), expected, delta=TOLERANCE_M)

    def test_ce02_cut_next_to_the_zone_moves_nothing_in_it(self) -> None:
        """CE-014-02, RF-014-07, RF-014-08: la corta excava junto a la zona a conservar (en el
        anillo de 3 m a su alrededor) y no mueve nada en ella: 0 m³, la superficie es su terreno y
        cumple las reglas del techo (``apply_ceiling`` no cambia ni un bit)."""
        design = self.outcome.grid
        zone = self.zone.mask
        around = qfx.in_box((57.0, 177.0, 103.0, 243.0)) & ~zone
        self.assertTrue(bool(np.any(around & (design < self.start - 1.0))))
        moved = quarry.conserve_moved(design, self.start, (self.zone,), self.geometry,
                                      MIN_THICKNESS_M)
        self.assertFalse(moved.moved)
        self.assertEqual(moved.volume_m3, 0.0)
        self.assertEqual(moved.notices, ())
        np.testing.assert_array_equal(design[zone], self.start[zone])
        np.testing.assert_array_equal(quarry.apply_ceiling(design, self.start, self.ceiling),
                                      design)

    # --- CE-014-03 (error 20) -------------------------------------------------------------

    def test_ce03_corridor_measures_its_axis_not_its_axis_plus_width(self) -> None:
        """CE-014-03, RF-014-09, RF-014-10: el corredor de la capa (200 m de eje, 20 m de ancho)
        mide 199 m, 200 m ± 1 celda y no 220 m, y no avisa de ser largo."""
        self.assertEqual(self.corridors.axes_m, (qfx.CORRIDOR_LENGTH_M,))
        self.assertEqual(self.corridors.widths_m, (qfx.CORRIDOR_WIDTH_M,))
        self.assertEqual(self.corridors.lengths_m, (CORRIDOR_MEASURED_M,))
        self.assertLessEqual(abs(self.corridors.lengths_m[0] - qfx.CORRIDOR_LENGTH_M),
                             qfx.GRID.dx)
        self.assertLess(self.corridors.lengths_m[0],
                        qfx.CORRIDOR_LENGTH_M + qfx.CORRIDOR_WIDTH_M - qfx.GRID.dx)
        self.assertEqual(self.corridors.notices, ())

    def test_ce03_corridor_cells_and_levels_by_hand(self) -> None:
        """CE-014-03, RF-014-09 (A6): las celdas del corredor son las de las regiones a mano (3.979,
        con extremos planos: nada al oeste de x = 200 ni al sur de y = 80) y su cota es
        ``125 + 0,08·σ`` a ≤ 10⁻⁹ m; al final, 140,96 m."""
        sigma = corridor_by_hand()
        inside = np.isfinite(sigma)
        self.assertEqual(CORNER_CELLS, 79)
        self.assertEqual(int(np.count_nonzero(inside)), CORRIDOR_CELLS)
        self.assertEqual(self.corridors.floors.cells, (CORRIDOR_CELLS,))
        found = self.corridors.floors.grid
        np.testing.assert_array_equal(np.isfinite(found), inside)
        gradient = qfx.CORRIDOR_GRADIENT_PCT / 100.0
        hand = qfx.CORRIDOR_START_M + sigma[inside] * gradient
        self.assertLessEqual(float(np.max(np.abs(found[inside] - hand))), TOLERANCE_M)
        self.assertAlmostEqual(float(found[inside].max()), 140.96, delta=TOLERANCE_M)
        x, y = qfx.local_centers()
        self.assertFalse(bool(np.any(inside & (x < 200.0))))
        self.assertFalse(bool(np.any(inside & (y < 80.0))))

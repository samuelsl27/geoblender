# SPDX-License-Identifier: GPL-3.0-or-later
"""«Solo relleno» (spec 014, T29; HU-014-6; RF-014-22 a RF-014-25; CE-014-07; plan 014 A12,
§5.3.1; DIS-17; errores 65 y 66).

- ``design.fronts.water_sheets`` y ``design.fronts.with_water`` (RF-014-24): las láminas de agua de
  una capa de polígonos con su cota y el terreno de partida del diseño ``z'``, **solo en memoria**:
  la cota de la lámina donde el terreno queda por debajo de ella o no tiene dato, el terreno donde
  queda por encima (la orilla seca dentro del polígono); con sus rechazos (una cota que falta o no
  es un número, dos láminas que se solapan, una capa que no es de polígonos o sin el campo).
- ``design.fronts.fill_only_steps`` (RF-014-22, RF-014-23): el escalonado en relleno de la 013 de
  la envolvente sobre ``z'``, solo en el relleno admitido de la 012 (la franja de solo relleno de
  fuera del límite legal, que el escalonado de la 013 sí rellena, no entra), y ``S = máx(z,
  compuesta)``: el corte es 0 m³; su informe, sus bermas y sus cifras son los de la 013 más
  ``des.fill_only_cut_m3``.
- ``design.fronts.check_fill_only`` (RF-014-25): los rechazos, un movimiento de más del espesor
  mínimo en un intocable (nombrándolo, con su volumen) y un corte de 1 m³ o más frente al terreno
  registrado (con el volumen).
- **CE-014-07** sobre la cantera sintética (``quarry_fixtures``, T01) con sus máscaras compiladas
  de V01: un tendido «solo relleno» junto a la torre intocable y a lo largo del límite corta 0 m³
  (< 1 m³), mueve 0 m³ en la torre y no rellena fuera del límite; la lámina de agua es su terreno
  de partida y el terreno registrado no cambia.

Las cifras a mano salen de las rejillas de los casos; la superficie de la 013 con que se comparan,
del escalonado de la 013 con las mismas entradas (``pipeline.design_compute_steps``).
"""

from __future__ import annotations

import hashlib
import math
import unittest
from collections.abc import Iterator
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any
from unittest import mock

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import design_fixtures as dfx
from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender

fronts = import_geoblender("design.fronts")
pipeline = import_geoblender("design.pipeline")
model = import_geoblender("design.model")
params = import_geoblender("design.params")
provenance = import_geoblender("design.provenance")
messages = import_geoblender("design.messages")
project_model = import_geoblender("core.project.model")
access = import_geoblender("gis.masks.access")
mask_zones = import_geoblender("gis.masks.zones")
gstore = import_geoblender("gis.store")
vector = import_geoblender("gis.vector")

THICKNESS_M = 0.02
"""El espesor mínimo de la 012 de las pruebas (un dato de entrada)."""
REST = "rest_5_35_6"
PROFILE = {"height_m": 5.0, "face_deg": 35.0, "berm_m": 6.0, "anchor_m": 125.0,
           "mesh_factor": 1.0}
"""El perfil ``REST_5_35_6`` de la 013 (D-7: un dato de entrada)."""
WATER_SOURCE = model.LayerField(qfx.WATER_LAYER, "cota")

# --- El caso a mano: 10 × 14 celdas de 2 m -----------------------------------------------------

ROWS, COLS, STEP = 10, 14, 2.0
GRID = dfx.grid_from(ROWS, COLS, STEP)
CELL_M2 = STEP * STEP
_R, _C = np.indices((ROWS, COLS))
STRIP = _C < 2
"""La franja de solo relleno de fuera del límite legal: las columnas 0 y 1 (20 celdas)."""
TOWER = (_R >= 4) & (_R <= 5) & (_C >= 8) & (_C <= 9)
"""La zona del intocable «torre»: 2 × 2 celdas, sin relleno admitido."""
NO_CUT = (_R <= 1) & (_C >= 12)
"""Una zona «sin corte» (con relleno admitido): no es un intocable."""
FILL = ~STRIP & ~TOWER
"""El relleno admitido de las máscaras de mano: todo menos la franja y la torre."""
WATER_BOX = (6.0, 14.0, 16.0, 18.0)
"""La lámina de mano (local): las filas 1 y 2 y las columnas 3 a 7."""
WATER = (_R >= 1) & (_R <= 2) & (_C >= 3) & (_C <= 7)
WATER_LEVEL_M = 103.25
"""La cota de la lámina de mano: por encima del terreno en las columnas 3 a 6 (101,5 a 103 m) y
por debajo en la 7 (103,5 m, la orilla)."""
NODATA_WATER = (2, 6)
"""Una celda de la lámina sin dato de terreno: toma la cota de la lámina."""
NODATA_DRY = (8, 5)
"""Una celda sin dato de terreno fuera de la lámina: sigue sin dato."""
RAISED = WATER & (_C <= 6)
"""Las celdas que toman la cota de la lámina, a mano: 2 filas × 4 columnas (con la sin dato)."""


def finish(found: Iterator[Any]) -> Any:
    """El resultado del último ``Progress`` de unos pasos."""
    last = None
    for last in found:
        pass
    return last.result


def hand_terrain() -> np.ndarray:
    """``100 + 0,5·columna`` (m: 0,25 m/m, 14°, más tendido que el talud general del perfil) con
    las dos celdas sin dato."""
    found = 100.0 + 0.5 * _C.astype(np.float64)
    found[NODATA_WATER] = np.nan
    found[NODATA_DRY] = np.nan
    return found


def hand_envelope() -> np.ndarray:
    """Una envolvente 6 m por encima de la ladera en toda la rejilla (también donde el terreno no
    tiene dato)."""
    return 106.0 + 0.5 * _C.astype(np.float64)


class HandMasks:
    """Unas máscaras de mano con lo que leen la composición de la 013 y los intocables: la
    rejilla, el relleno admitido (:data:`FILL`), la franja de solo relleno (:data:`STRIP`) y dos
    zonas, la torre intocable y una sin corte."""

    def __init__(self) -> None:
        self.grid = GRID
        self.zones = {"torre": mask_zones.Runs.from_mask(TOWER),
                      "sin_corte": mask_zones.Runs.from_mask(NO_CUT)}
        self.ctypes = MappingProxyType({"sin_corte": "no_cut", "torre": "untouchable"})

    def zone(self, code: str) -> Any:
        return self.zones[code]

    def cut_allowed(self) -> np.ndarray:
        return FILL & ~NO_CUT

    def fill_allowed(self) -> np.ndarray:
        return FILL.copy()

    def fill_strip(self) -> np.ndarray:
        return STRIP.copy()


def profiles() -> Any:
    values = {params.bench_key(REST, name): value for name, value in PROFILE.items()}
    return pipeline.bench_profiles(values, [REST])


def design_job(geometry: Any, start: np.ndarray, envelope: np.ndarray, masks: Any, *,
               name: str = "Tendido", sense: str = "fill") -> Any:
    """El escalonado de la 013 en relleno de ``envelope`` con ``REST_5_35_6`` y su ancla, sin
    sectores."""
    return pipeline.DesignJob(
        request=model.DesignRequest(name, "Envolvente", sense, REST), geometry=geometry,
        start=start, envelope=envelope, masks=masks, sectors=(),
        labels=np.zeros(geometry.shape, dtype=np.int16), imposed={}, profiles=profiles(),
        anchors=None, min_thickness_m=THICKNESS_M, face_tolerance_deg=1.0, warning_ratio=2.0)


def sheet_layer(boxes: tuple[tuple[float, float, float, float], ...], levels: tuple[Any, ...], *,
                kind: str = "polygon", field: str = "cota") -> Any:
    """Una capa de láminas (``FeatureLayer``) con un rectángulo local por entidad (fids 1…n) y su
    campo de cota, como la escribe ``quarry_fixtures.write_feature_layer``."""
    parts = tuple(((cfx.rectangle(*box),),) for box in boxes)
    columns = (vector.FieldColumn("nombre", "nombre", "TEXT"),
               vector.FieldColumn(field, field, "DOUBLE"))
    values = {"nombre": tuple(f"Balsa {index}" for index in range(1, len(boxes) + 1)),
              field: tuple(levels)}
    return vector.FeatureLayer(kind, tuple(range(1, len(boxes) + 1)), parts, columns, values)


def fake_design(design: np.ndarray) -> Any:
    """Un ``design_compute_steps`` que da ``design`` como la superficie compuesta de la 013."""

    def steps(job: Any, *, budget_s: float = 0.05) -> Any:
        outcome = pipeline.DesignOutcome(design, SimpleNamespace(count=0),
                                         SimpleNamespace(fill_m3=0.0, cut_m3=0.0), (), 0.0, "")
        yield project_model.Progress("benching", 1, 1, "escalonado", result=outcome)

    return steps


class WaterSheetsTest(unittest.TestCase):
    """RF-014-24 (D-10): la lámina de agua de la cantera y su terreno de partida."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.layer = sheet_layer((qfx.WATER_LOCAL,), (qfx.WATER_LEVEL_M,))
        cls.sheets = fronts.water_sheets(cls.layer, WATER_SOURCE, qfx.GRID)

    def test_each_cell_inside_the_sheet_takes_its_level(self) -> None:
        """RF-014-24 (D-10): cada celda con el centro dentro de la lámina lleva su cota (270 m en
        40 × 30 m: 1.200 celdas a mano) y las demás, ``NaN``."""
        inside = qfx.in_box(qfx.WATER_LOCAL)
        expected = np.where(inside, qfx.WATER_LEVEL_M, np.nan)
        self.assertEqual(self.sheets.grid.dtype, np.float64)
        np.testing.assert_array_equal(self.sheets.grid, expected)
        np.testing.assert_array_equal(self.sheets.owner, inside.astype(np.int32))
        self.assertEqual((self.sheets.layer, self.sheets.field), (qfx.WATER_LAYER, "cota"))
        self.assertEqual((self.sheets.fids, self.sheets.levels, self.sheets.cells),
                         ((1,), (qfx.WATER_LEVEL_M,), (1200,)))
        self.assertEqual(self.sheets.area_m2, 1200.0)

    def test_the_sheet_is_the_start_where_the_terrain_is_below_it(self) -> None:
        """RF-014-24: ``z'`` es la cota de la lámina donde el terreno de la ladera queda por debajo
        (a mano: ``0,25·y + 0,0625·x < 87`` en la columna ``130,5 + i`` da ``15 − ⌊i/4⌋`` filas, 420
        celdas) y el terreno donde queda por encima (las 780 de la orilla seca); fuera, el terreno
        bit a bit. Es una rejilla nueva: el terreno no cambia."""
        terrain = qfx.terrain()
        before = terrain.copy()
        found = fronts.with_water(terrain, self.sheets)
        np.testing.assert_array_equal(terrain, before)
        self.assertIsNot(found, terrain)
        raised = found != terrain
        self.assertEqual(int(np.count_nonzero(raised)),
                         sum(15 - i // 4 for i in range(40)))
        self.assertEqual(int(np.count_nonzero(raised)), 420)
        self.assertTrue(bool(np.all(found[raised] == qfx.WATER_LEVEL_M)))
        self.assertTrue(bool(np.all(terrain[raised] < qfx.WATER_LEVEL_M)))
        shore = qfx.in_box(qfx.WATER_LOCAL) & ~raised
        self.assertEqual(int(np.count_nonzero(shore)), 780)
        self.assertTrue(bool(np.all(terrain[shore] > qfx.WATER_LEVEL_M)))
        np.testing.assert_array_equal(fronts.with_water(terrain, None), terrain)

    def test_a_level_that_is_not_a_number_is_refused(self) -> None:
        """RF-014-24 (principio 6): una cota que falta o no es un número finito se rechaza
        nombrando la capa, la lámina, el campo y el valor; no se supone ninguna."""
        for value, shown in ((None, "—"), (math.nan, "nan"), (math.inf, "inf"),
                             ("alta", "alta")):
            layer = sheet_layer((qfx.WATER_LOCAL, (300.0, 300.0, 320.0, 320.0)),
                                (qfx.WATER_LEVEL_M, value))
            with self.subTest(value=value), self.assertRaises(messages.DesignError) as caught:
                fronts.water_sheets(layer, WATER_SOURCE, qfx.GRID)
            self.assertEqual(caught.exception.code, "des.fill_only_water_level")
            self.assertEqual(caught.exception.values["polygon"], 2)
            self.assertIn(f"«{qfx.WATER_LAYER}»", caught.exception.text)
            self.assertIn(f"«cota» = {shown}", caught.exception.text)

    def test_overlapping_sheets_a_layer_without_polygons_or_without_the_field(self) -> None:
        """Dos láminas que se solapan se rechazan con las dos y sus celdas comunes (no se elige
        ninguna cota por ellas); una capa que no es de polígonos o sin el campo de cota, también."""
        layer = sheet_layer((qfx.WATER_LOCAL, (160.0, 320.0, 180.0, 340.0)), (270.0, 272.0))
        with self.assertRaises(messages.DesignError) as caught:
            fronts.water_sheets(layer, WATER_SOURCE, qfx.GRID)
        self.assertEqual(caught.exception.code, "des.fill_only_water_overlap")
        self.assertEqual((caught.exception.values["value"], caught.exception.values["other"],
                          caught.exception.values["cells"]), (1, 2, 100))
        line = vector.FeatureLayer(
            "line", (1,), (((cfx.absolute(((130.0, 300.0), (170.0, 330.0))),),),),
            (vector.FieldColumn("cota", "cota", "DOUBLE"),), {"cota": (270.0,)})
        with self.assertRaises(messages.DesignError) as caught:
            fronts.water_sheets(line, WATER_SOURCE, qfx.GRID)
        self.assertEqual(caught.exception.code, "des.layer_not_polygons")
        with self.assertRaises(messages.DesignError) as caught:
            fronts.water_sheets(self.layer, model.LayerField(qfx.WATER_LAYER, "nivel"), qfx.GRID)
        self.assertEqual(caught.exception.code, "des.quarry_layer_field")
        with self.assertRaises(ValueError):
            fronts.with_water(np.zeros((3, 3)), self.sheets)


class FillOnlyTest(unittest.TestCase):
    """RF-014-22 a RF-014-24 en el caso a mano, frente al escalonado en relleno de la 013."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.terrain = hand_terrain()
        cls.envelope = hand_envelope()
        cls.layer = sheet_layer((WATER_BOX,), (WATER_LEVEL_M,))
        cls.sheets = fronts.water_sheets(cls.layer, WATER_SOURCE, GRID)
        cls.design = design_job(GRID, cls.terrain, cls.envelope, HandMasks())
        cls.job = fronts.FillOnlyJob(cls.design, water=cls.sheets)
        cls.before = (cls.terrain.copy(), cls.envelope.copy(), cls.sheets.grid.copy())
        cls.outcome = finish(fronts.fill_only_steps(cls.job))
        cls.plain = finish(pipeline.design_compute_steps(cls.design))

    def test_the_start_is_the_terrain_with_the_sheet_in_memory(self) -> None:
        """RF-014-24: el terreno de partida del diseño es la cota de la lámina en las 8 celdas en
        que el terreno queda por debajo o no tiene dato, y el terreno en las demás (la orilla de la
        columna 7, la celda sin dato de fuera); ninguna entrada se modifica."""
        expected = self.terrain.copy()
        expected[RAISED] = WATER_LEVEL_M
        np.testing.assert_array_equal(self.outcome.start, expected)
        self.assertEqual(self.outcome.water_cells, 8)
        self.assertTrue(math.isnan(self.outcome.start[NODATA_DRY]))
        for found, before in zip((self.terrain, self.envelope, self.sheets.grid), self.before,
                                 strict=True):
            np.testing.assert_array_equal(found, before)

    def test_it_is_the_fill_of_the_013_over_the_start_and_never_cuts(self) -> None:
        """RF-014-22: en el relleno admitido fuera de la lámina, la superficie es la del
        escalonado en relleno de la 013 bit a bit; en la lámina, ``máx(la de la 013, cota)`` (la
        composición sobre ``z'``); nunca queda por debajo del terreno (0 m³ de corte) y rellena."""
        surface, plain = self.outcome.surface, self.plain.design
        self.assertIs(self.outcome.grid, surface)
        dry = FILL & ~WATER & np.isfinite(self.terrain)
        np.testing.assert_array_equal(surface[dry], plain[dry])
        wet = RAISED & np.isfinite(self.terrain)
        np.testing.assert_array_equal(surface[wet], np.maximum(plain[wet], WATER_LEVEL_M))
        self.assertGreaterEqual(surface[NODATA_WATER], WATER_LEVEL_M)
        self.assertTrue(math.isnan(surface[NODATA_DRY]))
        known = np.isfinite(self.terrain)
        self.assertTrue(bool(np.all(surface[known] >= self.terrain[known])))
        self.assertGreater(int(np.count_nonzero(surface[known] > self.terrain[known] + 1.0)), 80)
        self.assertEqual(self.outcome.cut_m3, 0.0)

    def test_the_toe_stays_in_the_admitted_fill(self) -> None:
        """RF-014-23: fuera del relleno admitido —la franja de fuera del límite y la torre— la
        superficie es el terreno de partida bit a bit; el escalonado de la 013 sí rellena la
        franja (sus 20 celdas), «solo relleno» no; ninguna celda movida fuera de lo admitido."""
        np.testing.assert_array_equal(self.outcome.surface[~FILL], self.outcome.start[~FILL])
        self.assertEqual(int(np.count_nonzero(self.plain.design[STRIP]
                                              > self.terrain[STRIP] + THICKNESS_M)), 20)
        moved = np.abs(self.outcome.surface - self.outcome.start) > 0.0
        self.assertFalse(bool(np.any(moved & ~FILL)))

    def test_the_report_berms_and_figures_are_those_of_the_013_plus_its_cut(self) -> None:
        """RF-014-22, RF-014-29 (plan §5.2.3): el informe de la 013 mide la superficie frente a
        ``z'`` (corte 0 m³, terraplén = la suma a mano de lo que sube más que el espesor mínimo),
        y las cifras son las suyas más ``des.fill_only_cut_m3`` = 0 m³ con el ámbito del diseño."""
        report = self.outcome.design.report
        start, surface = self.outcome.start, self.outcome.surface
        with np.errstate(invalid="ignore"):
            moved = np.isfinite(start) & np.isfinite(surface) & (np.abs(surface - start)
                                                                 > THICKNESS_M)
        self.assertEqual(report.cut_m3, 0.0)
        self.assertAlmostEqual(report.fill_m3, float((surface - start)[moved].sum()) * CELL_M2,
                               delta=1e-9)
        np.testing.assert_array_equal(self.outcome.design.design, surface)
        figures = self.outcome.figures
        self.assertEqual(figures[:-1], self.outcome.design.figures)
        last = figures[-1]
        self.assertEqual((last.key, last.value, last.unit), ("des.fill_only_cut_m3", 0.0, "m3"))
        self.assertEqual(dict(last.scope), provenance.quarry_figure_scope("Tendido"))
        self.assertIn("«Tendido»", self.outcome.message)

    def test_the_untouchables_of_the_masks(self) -> None:
        """RF-014-25: los intocables son las zonas de las restricciones de tipo intocable de las
        máscaras (no las «sin corte»), con su código o el nombre que se dé."""
        zones = fronts.untouchable_zones(HandMasks())
        self.assertEqual([zone.name for zone in zones], ["torre"])
        np.testing.assert_array_equal(zones[0].mask, TOWER)
        named = fronts.untouchable_zones(HandMasks(), {"torre": "Torre"})
        self.assertEqual([zone.name for zone in named], ["Torre"])

    def test_a_moved_untouchable_is_refused_while_advancing(self) -> None:
        """RF-014-25: si el escalonado moviera una celda del intocable (aquí, sustituido en la
        prueba para que suba 1 m las 4 celdas de la torre), se rechaza al avanzar nombrándolo con
        su volumen (4 · 1 m · 4 m² = 16 m³) y no se da ningún resultado."""
        lifted = self.outcome.start.copy()
        lifted[TOWER] += 1.0
        with mock.patch.object(fronts, "design_compute_steps", fake_design(lifted)):
            with self.assertRaises(messages.DesignError) as caught:
                finish(fronts.fill_only_steps(self.job))
            self.assertEqual(caught.exception.code, "des.fill_only_untouchable")
            self.assertEqual(caught.exception.values["constraint"], "torre")
            self.assertEqual(caught.exception.values["value"], 16.0)
            named = fronts.FillOnlyJob(self.design, water=self.sheets,
                                       untouchables=fronts.untouchable_zones(
                                           HandMasks(), {"torre": "Torre"}))
            with self.assertRaises(messages.DesignError) as caught:
                finish(fronts.fill_only_steps(named))
            self.assertIn("«Torre»", caught.exception.text)
            free = fronts.FillOnlyJob(self.design, water=self.sheets, untouchables=())
            self.assertEqual(finish(fronts.fill_only_steps(free)).cut_m3, 0.0)

    def test_calling_errors(self) -> None:
        """Errores del programa al llamar: un escalonado en corte, unas láminas o un intocable de
        otra rejilla."""
        cut = design_job(GRID, self.terrain, self.envelope, HandMasks(), sense="cut")
        with self.assertRaises(ValueError):
            fronts.fill_only_steps(fronts.FillOnlyJob(cut))
        other = fronts.water_sheets(sheet_layer((qfx.WATER_LOCAL,), (270.0,)), WATER_SOURCE,
                                    qfx.GRID)
        with self.assertRaises(ValueError):
            fronts.fill_only_steps(fronts.FillOnlyJob(self.design, water=other))
        wrong = (fronts.UntouchableZone("torre", np.zeros((3, 3), dtype=bool)),)
        with self.assertRaises(ValueError):
            fronts.fill_only_steps(fronts.FillOnlyJob(self.design, untouchables=wrong))


class CheckFillOnlyTest(unittest.TestCase):
    """RF-014-25 (A12): los dos rechazos de un diseño «solo relleno», con sus límites."""

    def setUp(self) -> None:
        self.terrain = hand_terrain()
        self.start = self.terrain.copy()
        self.start[RAISED] = WATER_LEVEL_M
        self.zones = (fronts.UntouchableZone("Torre", TOWER.copy()),)

    def check(self, surface: np.ndarray) -> float:
        return fronts.check_fill_only("Tendido", surface, self.terrain, self.start, self.zones,
                                      GRID, THICKNESS_M)

    def test_a_cut_of_one_cubic_metre_or_more_is_refused(self) -> None:
        """RF-014-22, RF-014-25: el corte es ``Σ máx(z − S, 0) · área de celda`` frente al terreno
        registrado; con 1 m³ justo (una celda de 4 m² 0,25 m por debajo) o 4 m³ se rechaza con el
        volumen; con 0,9996 m³ se admite y se devuelve; una celda sin dato no cuenta."""
        for cells, depth, expected in ((((6, 3),), 0.25, 1.0),
                                       (((6, 3), (6, 4), (7, 3), (7, 4)), 0.25, 4.0)):
            surface = self.start.copy()
            for cell in cells:
                surface[cell] = self.terrain[cell] - depth
            with self.subTest(cells=len(cells)), self.assertRaises(messages.DesignError) as caught:
                self.check(surface)
            self.assertEqual(caught.exception.code, "des.fill_only_cuts")
            self.assertEqual(caught.exception.values["value"], expected)
            self.assertIn("«solo relleno»", caught.exception.text)
        surface = self.start.copy()
        surface[6, 3] = self.terrain[6, 3] - 0.2499
        surface[NODATA_DRY] = 0.0
        self.assertAlmostEqual(self.check(surface), 0.2499 * CELL_M2, delta=1e-12)
        self.assertEqual(self.check(self.start), 0.0)

    def test_moving_an_untouchable_more_than_the_minimum_thickness_is_refused(self) -> None:
        """RF-014-25 (error 65): más del espesor mínimo frente al terreno de partida ``z'`` en una
        celda del intocable se rechaza nombrándolo con su volumen (0,03 m · 4 m² = 0,12 m³); el
        espesor mínimo justo, no; tampoco un movimiento fuera de él ni la lámina, que es su
        partida."""
        surface = self.start.copy()
        surface[4, 8] += 0.03
        with self.assertRaises(messages.DesignError) as caught:
            self.check(surface)
        self.assertEqual(caught.exception.code, "des.fill_only_untouchable")
        self.assertEqual((caught.exception.values["constraint"],
                          caught.exception.values["value"]), ("Torre", 0.12))
        self.assertIn("«Torre»", caught.exception.text)
        surface = self.start.copy()
        surface[4, 8] += THICKNESS_M
        surface[4, 7] += 3.0
        self.assertEqual(self.check(surface), 0.0)
        wet = (fronts.UntouchableZone("Balsa", RAISED.copy()),)
        self.assertEqual(fronts.check_fill_only("Tendido", self.start, self.terrain, self.start,
                                                wet, GRID, THICKNESS_M), 0.0)


class QuarryFillOnlyTest(qfx.QuarryProjectCase):
    """CE-014-07 (errores 65 y 66), RF-014-22 a RF-014-25, en la cantera con las máscaras de V01:
    un tendido de 4 m sobre la ladera de 40 m de ancho de oeste a este, por la torre y por la franja
    de fuera del límite (``y`` de 100 a 140), y otro en la lámina de agua y su orilla."""

    BAND = (0.0, 100.0, 400.0, 140.0)
    POND = (120.0, 300.0, 180.0, 340.0)

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        record = cls.record_of(qfx.START_DATASET)
        cls.terrain_file = Path(cls.project.root, *record.locator.split("/"))
        cls.terrain_sha = hashlib.sha256(cls.terrain_file.read_bytes()).hexdigest()
        cls.masks_v1 = access.load_masks(cls.project, cls.v1.uid)
        with cls.project.read() as conn:
            layer = gstore.read_features(conn, qfx.WATER_LAYER)
        cls.terrain = qfx.terrain()
        cls.zone = qfx.in_box(cls.BAND) | qfx.in_box(cls.POND)
        envelope = np.where(cls.zone, cls.terrain + 4.0, np.nan)
        cls.untouchables = fronts.untouchable_zones(cls.masks_v1, {"torre": "Torre"})
        cls.job = fronts.FillOnlyJob(
            design_job(qfx.GRID, cls.terrain, envelope, cls.masks_v1,
                       name="Tendido junto a la torre"),
            water=fronts.water_sheets(layer, WATER_SOURCE, qfx.GRID),
            untouchables=cls.untouchables)
        cls.outcome = finish(fronts.fill_only_steps(cls.job))

    @classmethod
    def record_of(cls, name: str) -> Any:
        registry = import_geoblender("core.datasets.registry")
        with cls.project.read() as conn:
            return registry.get(conn, name, version_uid="")

    def test_ce_014_07_it_cuts_nothing(self) -> None:
        """CE-014-07, RF-014-22: el tendido corta menos de 1 m³ (0 m³: ninguna celda por debajo
        del terreno) y rellena (más de 10.000 m³ en la banda), con su cifra."""
        surface, terrain = self.outcome.surface, self.terrain
        self.assertEqual(float(np.maximum(terrain - surface, 0.0).sum()), 0.0)
        self.assertEqual(self.outcome.cut_m3, 0.0)
        self.assertEqual(self.outcome.figures[-1].value, 0.0)
        self.assertGreater(self.outcome.design.report.fill_m3, 10_000.0)

    def test_ce_014_07_it_moves_nothing_in_the_tower(self) -> None:
        """CE-014-07, RF-014-25 (error 65): la torre (sus 224 celdas con 8 m de resguardo) queda
        como el terreno bit a bit, 0 m³, aunque el tendido la rodea (más de 1 m de relleno en el
        anillo de una celda de su zona)."""
        self.assertEqual([zone.name for zone in self.untouchables], ["Torre"])
        tower = self.untouchables[0].mask
        self.assertEqual(int(np.count_nonzero(tower)), qfx.TOWER_ZONE_CELLS)
        np.testing.assert_array_equal(self.outcome.surface[tower], self.terrain[tower])
        ring = np.zeros_like(tower)
        rows, cols = np.nonzero(tower)
        ring[rows.min() - 1:rows.max() + 2, cols.min() - 1:cols.max() + 2] = True
        ring &= ~tower
        lifted = self.outcome.surface[ring] - self.terrain[ring]
        self.assertGreater(int(np.count_nonzero(lifted > 1.0)), 10)

    def test_ce_014_07_it_fills_nothing_outside_the_limit(self) -> None:
        """CE-014-07, RF-014-23: fuera del límite legal (la franja de solo relleno de 20 m al oeste,
        lo de fuera del perímetro y el este de 360 m) la superficie es el terreno bit a bit, también
        en la banda; el pie del relleno llega al límite (la primera columna dentro rellena) y toda
        celda movida tiene el relleno admitido de la 012."""
        surface = self.outcome.surface
        outside = ~qfx.in_box(qfx.LEGAL_LOCAL)
        np.testing.assert_array_equal(surface[outside], self.terrain[outside])
        self.assertGreater(int(np.count_nonzero(outside & self.zone)), 2_000)
        x, _y = qfx.local_centers()
        toe = qfx.in_box(self.BAND) & (x == 40.5)
        self.assertTrue(bool(np.all(surface[toe] > self.terrain[toe] + 1.0)))
        moved = surface != self.outcome.start
        self.assertFalse(bool(np.any(moved & ~self.masks_v1.fill_allowed())))

    def test_the_sheet_is_the_start_and_the_terrain_does_not_change(self) -> None:
        """RF-014-24: la lámina a 270 m es el terreno de partida en sus 420 celdas por debajo de esa
        cota y el tendido no queda por debajo de ella; el terreno registrado (su fichero) no cambia
        y el que se pasó, tampoco."""
        raised = self.outcome.start != self.terrain
        self.assertEqual(int(np.count_nonzero(raised)), 420)
        self.assertEqual(self.outcome.water_cells, 420)
        self.assertTrue(bool(np.all(self.outcome.start[raised] == qfx.WATER_LEVEL_M)))
        self.assertTrue(bool(np.all(self.outcome.surface[raised] >= qfx.WATER_LEVEL_M)))
        np.testing.assert_array_equal(self.terrain, qfx.terrain())
        self.assertEqual(hashlib.sha256(self.terrain_file.read_bytes()).hexdigest(),
                         self.terrain_sha)


if __name__ == "__main__":
    unittest.main()

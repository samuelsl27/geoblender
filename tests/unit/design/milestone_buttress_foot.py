# SPDX-License-Identifier: GPL-3.0-or-later
"""El pie cortado del contrafuerte, con proyecto (spec 016, T28; HU-016-3; RF-016-17, RF-016-19, RF-015-13, RF-015-02, RF-009-11; CE-016-06;
plan 016 §5.4 A10, §5.3.2; D-24). Va al paso «hito» de ``check.py --completo`` (P-13: la rejilla de 2 m con proyecto); el cálculo puro y el
caso de referencia están en ``test_buttress_foot.py`` y ``tests/referencia/des/test_ref_buttress_foot.py``, en el «verde».

La cantera de los acopios de 2 m (V01), con dos contrafuertes de las zonas de coronación de la T01 (``stockpile_data.CROWN_ZONES``):

- **junto al límite** (:class:`LimitFootTest`, sobre el terreno): el pie que el límite legal y el perímetro de la cantera cortan. El
  resumen avisa lo que falta —el área, el volumen y el salto creado de ese borde con su lugar, los del cálculo a mano en las mismas celdas
  de una ventana de la rejilla— y, aparte, lo que no admiten las máscaras, **sin impedir crearlo**; lo registrado (las cifras
  ``des.btr_cutoff_m2`` y ``des.btr_cutoff_m3``, el informe con su aviso) y reproducirlo (sin el proyecto) da lo mismo;
- **junto a la «Plataforma de carga» de la 015, «en corte» y protegida** (:class:`PlatformFootTest`: 4 m de resguardo, declara «sin
  relleno» sobre su huella y se compila en las máscaras de la versión), parte de **lo que deja la plataforma** (de la superficie del terreno
  parte solo una entidad: RF-015-04): sobre su huella el contrafuerte **rellena 0 m³** y el resumen da **el área que no rellena, con la
  plataforma** (RF-015-13).
"""

from __future__ import annotations

import unittest
from typing import Any, ClassVar

import numpy as np

from tests.support import buttress_data as bdata
from tests.support import design_fixtures as dfx
from tests.support.package import import_geoblender
from tests.unit.design import test_buttress_operation as bop
from tests.unit.design import test_platform_prepare as prep
from tests.unit.design import test_stockpile_operation as ops

access = import_geoblender("gis.masks.access")
compose = import_geoblender("design.compose")
design_model = import_geoblender("design.model")
entity_store = import_geoblender("design.entity_store")
freeze = import_geoblender("core.versions.freeze")
geotiff_reader = import_geoblender("gis.geotiff.reader")
provenance = import_geoblender("design.provenance")
reproduce_mod = import_geoblender("core.versions.reproduce")
stockpiles = import_geoblender("design.stockpiles")

FILL = design_model.BenchSense.FILL
GRID = bop.GRID
USER = bop.USER
NEXT_TO_PLATFORM = "Coronación junto a la plataforma"
NEXT_TO_LIMIT = "Coronación junto al límite"
PLATFORM = prep.LOADING
GUARD = 4.0
RELATIVE = 1e-9
FOOT_CUT = "des.buttress_foot_cut"


class FootChecks(bop.ButtressCase):
    """Lo común: el pie cortado de un cálculo contra el cálculo a mano."""

    START: ClassVar[str]

    def request(self, name: str, zone: str, crown: float) -> Any:
        return bop.asked(name, feature=zone, crown=crown, start=self.START)

    def start_grid(self) -> np.ndarray:
        """La partida del contrafuerte, tal como está en su fichero (la de V01 con ese nombre o la que deja la plataforma)."""
        if self.START.startswith("entity:"):
            record = self.record(provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, PLATFORM), self.v1)
        else:
            record = self.record(self.START) or self.record(self.START, self.v1)  # el terreno es del proyecto
        return np.array(geotiff_reader.read_geotiff(self.root / record.locator).values)

    def by_hand(self, calculation: Any, crown: float, masks: Any) -> tuple[Any, tuple[slice, slice]]:
        """El pie cortado a mano: el contrafuerte con y sin máscaras (el oráculo independiente) en una **ventana** de la rejilla de 2 m que
        rodea su zona de coronación (40 celdas de margen), con el relleno admitido de las ``masks`` y la partida que lee el cálculo (la zona
        es la que lee la preparación: su regla de la celda es de la T27). Devuelve ``(HandFoot, la ventana de la rejilla entera)``."""
        outcome = calculation.outcome
        mask = np.zeros(GRID.shape, dtype=bool)
        mask[outcome.window] = outcome.zone
        rows, cols = np.nonzero(mask)
        margin = 40
        window = (slice(max(int(rows.min()) - margin, 0), min(int(rows.max()) + margin + 1, GRID.nrows)),
                  slice(max(int(cols.min()) - margin, 0), min(int(cols.max()) + margin + 1, GRID.ncols)))
        start = self.start_grid()
        allowed = compose.admitted(masks, FILL)
        scene = bdata.Scene(stockpiles.window_grid(GRID, window), np.array(start[window]), mask[window], allowed[window],
                            bdata.profile(dfx.EXPL_10_60_6))
        thickness = float(calculation.entity.common["res.verify.min_thickness_m"])
        return bdata.hand_foot(scene, crown, thickness=thickness), window

    def check_against_the_hand(self, calculation: Any, crown: float, masks: Any) -> Any:
        """El pie cortado del cálculo es el del cálculo a mano (≤ 10⁻⁹ relativo): sus celdas (las mismas en la rejilla entera), su área, su
        volumen, las parejas del borde, el mayor salto creado y su lugar; el aviso y las cifras del resumen lo dicen."""
        outcome = calculation.outcome
        hand, window = self.by_hand(calculation, crown, masks)
        self.assertGreater(hand.cells, 30, "el caso no es vacío: el pie sí se corta")
        mine = np.zeros(GRID.shape, dtype=bool)
        mine[outcome.window] = outcome.cutoff
        wanted = np.zeros(GRID.shape, dtype=bool)
        wanted[window] = hand.mask
        self.assertTrue(np.array_equal(mine, wanted), "las celdas cortadas")
        for found, expected, what in ((outcome.cutoff_m2, hand.area_m2, "el área"), (outcome.cutoff_m3, hand.volume_m3, "el volumen"),
                                      (outcome.created.maximum_m, hand.step_m, "el salto creado"),
                                      (outcome.created.x, hand.x, "x"), (outcome.created.y, hand.y, "y")):
            self.assertLessEqual(abs(found - expected), RELATIVE * max(abs(expected), 1.0), f"{what}: {found} frente a {expected}")
        self.assertEqual(outcome.created.pairs, hand.pairs)
        (notice,) = [item for item in calculation.summary.notices if item.code == FOOT_CUT]
        self.assertEqual((notice.values["area"], notice.values["entity"]), (outcome.cutoff_m2, calculation.summary.name))
        self.assertAlmostEqual(float(notice.values["step"]), round(hand.step_m, 2), places=9)
        figures = {item.key: item.value for item in calculation.summary.figures}
        self.assertEqual((figures["des.btr_cutoff_m2"], figures["des.btr_cutoff_m3"]), (outcome.cutoff_m2, outcome.cutoff_m3))
        return hand


class LimitFootTest(FootChecks):
    """CE-016-06, RF-016-19, RF-015-13, RF-009-11, **en orden** (de la ``a`` a la ``d``): el contrafuerte de «Coronación junto al límite» sobre
    el terreno, que se calcula, se crea, se registra y se reproduce."""

    START = prep.START
    BUTTRESS = "Contrafuerte junto al límite"
    stored: ClassVar[Any]
    calculation: ClassVar[Any]

    def test_a_the_summary_gives_the_missing_foot_and_what_the_masks_do_not_admit(self) -> None:
        """RF-016-19, RF-015-13, CE-016-06: el pie del contrafuerte lo cortan el límite legal y el perímetro de la cantera: el resumen avisa lo
        que falta —el área, el volumen y el salto creado de ese borde con su lugar, los del cálculo a mano en las mismas celdas— y, aparte,
        **lo que no rellena porque las máscaras no lo admiten** (``des.entity_held_masks``: ninguna restricción de una entidad lo explica),
        con la misma área, después del aviso del pie; y **no impide calcularlo**."""
        calculation = self.calculate(self.request(self.BUTTRESS, NEXT_TO_LIMIT, 295.0))
        hand = self.check_against_the_hand(calculation, 295.0, self.masks_v1)
        outcome = calculation.outcome
        codes = [item.code for item in calculation.summary.notices]
        self.assertEqual(codes.count(FOOT_CUT), 1)
        held = [item for item in calculation.summary.notices if item.code.startswith("des.entity_held")]
        self.assertEqual([item.code for item in held], ["des.entity_held_masks"])
        self.assertEqual(held[0].values["area"], outcome.cutoff_m2)
        self.assertEqual(held[0].values["area"], hand.area_m2)
        self.assertLess(codes.index(FOOT_CUT), codes.index("des.entity_held_masks"), "primero el pie, luego lo que lo causa")
        for notice in calculation.summary.notices:
            for language in ("es", "en"):
                self.assertNotIn("{", notice.text(language))
        type(self).calculation = calculation

    def test_b_creating_it_is_not_prevented_and_registers_the_figures_and_the_note(self) -> None:
        """RF-016-19, RF-015-02: **sin impedir crearlo**: «Crear» registra el contrafuerte con el pie cortado, las cifras
        ``des.btr_cutoff_m2`` y ``des.btr_cutoff_m3`` (las del resumen) y el informe con las filas del pie y el aviso como nota."""
        calculation = type(self).calculation
        outcome = calculation.outcome
        stored = calculation.create(decided_by=USER)
        type(self).stored = stored
        uid = str(stored.handle.uid)
        figures = self.figures_by_key(uid)
        self.assertEqual((figures["des.btr_cutoff_m2"], figures["des.btr_cutoff_m3"]), (outcome.cutoff_m2, outcome.cutoff_m3))
        for key in ("des.btr_volume_m3", "des.btr_area_m2", "des.btr_height_max_m"):
            self.assertIn(key, figures)
        table = self.locator(provenance.ENTITY_REPORT_TABLE, self.BUTTRESS)
        by_key = {row[0]: row for row in self.query(f'SELECT quantity, value, unit_code, note FROM "{table}"')}
        self.assertEqual((by_key["cutoff_m2"][1], by_key["cutoff_m3"][1]), (outcome.cutoff_m2, outcome.cutoff_m3))
        self.assertEqual(by_key["cutoff_step_m"][1], outcome.created.maximum_m)
        self.assertIn(FOOT_CUT, by_key["warning"][3])
        self.assertEqual(self.stale_causes(uid), set())
        self.assertEqual(self.temporaries(), [])

    def test_c_the_surface_is_the_start_beyond_what_the_masks_admit(self) -> None:
        """RF-016-17, RF-016-19, D-24: lo registrado no sube ni una celda donde las máscaras no admiten el relleno (la superficie es la de
        partida bit a bit: **el pie cortado es lo que falta, no lo que se llevó**) y sí fuera de la zona dibujada, dentro de lo admitido."""
        surface = self.raster(provenance.ENTITY_SURFACE_GRID, self.BUTTRESS)
        start = self.start_grid()
        forbidden = ~compose.admitted(self.masks_v1, FILL)
        self.assertEqual(surface[forbidden].tobytes(), start[forbidden].tobytes())
        outcome = type(self).calculation.outcome
        zone = np.zeros(GRID.shape, dtype=bool)
        zone[outcome.window] = outcome.zone
        self.assertTrue(((surface > start) & ~zone).any(), "el pie sale de la zona dibujada (error 19)")

    def test_d_reproducing_the_frozen_revision_gives_the_same_report_figures_and_surface(self) -> None:
        """RF-009-11, RF-016-19: congelada ``V01.r1`` con el contrafuerte de pie cortado, reproducirla —sin el proyecto— da la misma
        superficie, el mismo informe (con su aviso y las filas del pie) y las mismas cifras, también ``des.btr_cutoff_*``."""
        self.clock.advance(minutes=1)
        frozen = ops.finish(freeze.freeze_steps(self.project, self.v1.uid, reason="Entrega de la prueba"))
        self.clock.advance(minutes=1)
        report = ops.finish(reproduce_mod.reproduce_steps(self.project, str(frozen.frozen.uid)))
        uid = str(type(self).stored.handle.uid)
        mine = [check for check in report.outputs if check.operation_uid == uid]
        self.assertEqual(len(mine), 3, f"{report.not_reproducible} {report.outputs}")
        self.assertTrue(all(check.same for check in mine), [check for check in mine if not check.same])
        figures = [check for check in report.figures if check.operation_uid == uid]
        self.assertEqual(len(figures), 5)
        self.assertTrue(all(check.same for check in figures), [check for check in figures if not check.same])
        self.assertTrue(report.matches, report)


class PlatformFootTest(FootChecks):
    """CE-016-06, RF-016-19, RF-015-13: el contrafuerte de «Coronación junto a la plataforma», que parte de lo que deja la «Plataforma de carga»
    «en corte» y protegida (declarada y con las máscaras compiladas con lo que declara)."""

    START = "entity:PLT-001"
    BUTTRESS = "Contrafuerte junto a la plataforma"
    masks: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request(protect=True, guard_m=GUARD))
        cls.clock.advance(minutes=1)
        chain = ops.finish(entity_store.after_entity_change(cls.project, cls.v1.uid))
        assert chain.failure is None and chain.masks_compiled, chain
        cls.clock.advance(minutes=1)
        cls.masks = access.load_masks(cls.project, cls.v1.uid)

    @classmethod
    def calculate(cls, request: Any, **options: Any) -> Any:
        options.setdefault("masks", cls.masks)
        return super().calculate(request, **options)

    def test_a_it_fills_nothing_over_its_footprint_and_the_summary_names_the_platform(self) -> None:
        """RF-015-13, CE-016-06: **sobre la huella de la plataforma el contrafuerte rellena 0 m³** (la superficie es la de la plataforma, bit
        a bit, donde las máscaras prohíben el relleno) y **su resumen da el área que no rellena, con la plataforma** (``des.entity_held`` con
        su nombre y la de las máscaras de lo que ninguna restricción explica): las dos suman el pie cortado, que es el de la mano."""
        calculation = self.calculate(self.request(self.BUTTRESS, NEXT_TO_PLATFORM, 285.0))
        hand = self.check_against_the_hand(calculation, 285.0, self.masks)
        outcome = calculation.outcome
        held = {item.code: item for item in calculation.summary.notices if item.code.startswith("des.entity_held")}
        platform = held["des.entity_held"]
        self.assertEqual((platform.values["entity"], platform.values["other"]), (self.BUTTRESS, PLATFORM))
        self.assertIn(f"«Plataforma {PLATFORM} (declarada)»", platform.text("es"))
        zone = self.masks.zone("dec__plt_001").mask(GRID.shape, (0, 0))
        self.assertTrue(zone.any())
        cut = np.zeros(GRID.shape, dtype=bool)
        cut[outcome.window] = outcome.cutoff
        by_platform = float(np.count_nonzero(cut & zone)) * GRID.cell_area
        loose = float(np.count_nonzero(cut & ~zone)) * GRID.cell_area
        self.assertGreater(by_platform, 0.0)
        self.assertEqual(platform.values["area"], by_platform, "lo que no rellena por la restricción de la plataforma")
        self.assertEqual("des.entity_held_masks" in held, loose > 0.0)
        if loose > 0.0:
            self.assertEqual(held["des.entity_held_masks"].values["area"], loose, "y lo que no admiten las máscaras")
        self.assertEqual(by_platform + loose, hand.area_m2, "entre las dos, lo que falta")
        start = self.start_grid()
        surface = outcome.compose(start)
        self.assertEqual(surface[zone].tobytes(), start[zone].tobytes(), "sobre su huella, la partida bit a bit")
        self.assertEqual(float((surface - start)[zone].sum()), 0.0, "0 m³ en su huella")
        calculation.discard()


if __name__ == "__main__":
    unittest.main()

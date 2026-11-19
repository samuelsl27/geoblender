# SPDX-License-Identifier: GPL-3.0-or-later
"""El pie cortado del contrafuerte (spec 016, T28; HU-016-3; RF-016-17, RF-016-19, RF-015-13; plan 016 §5.4 A10 —la última frase—;
D-24; CE-016-06; error 19): si el borde del relleno admitido corta el pie, ``design.buttress.measure_cutoff`` (y ``cutoff_steps``, por
pasos) da lo que falta —el **área** y el **volumen** (el escalonado sin máscara menos el compuesto) y el **salto creado** de ese borde
con su lugar (``design.edges.created_steps``)— como el aviso ``des.buttress_foot_cut`` y las cifras ``des.btr_cutoff_m2`` y
``des.btr_cutoff_m3``, **sin impedir crearlo**. Se prueba con:

- **la fórmula cerrada** (:func:`tests.support.buttress_data.strip_closed_form`): una franja de lado a lado con un borde del relleno
  admitido en una fila es un problema de una dimensión: lo que falta y el salto de ese borde salen del escalonado de cada fila, con
  las dos métricas;
- **una implementación independiente** (:func:`tests.support.buttress_data.hand_foot`: el contrafuerte con y sin máscaras del
  oráculo de la T26, lo que falta celda a celda y el salto creado por parejas, en bucles de Python) en un relieve con celdas sin
  dato y bloques sin relleno admitido;
- **las máscaras de verdad** (RF-012-13, D-24): un contrafuerte junto al límite y a una zona de «solo restauración» sale de la zona
  dibujada, entra en ella y lo que cortan el límite y la plataforma «en corte» protegida (su restricción «sin relleno» declarada)
  se avisa con su área, con la plataforma (RF-015-13);
- **lo que no hay**: sin pie cortado, 0 m² y 0 m³ (las cifras se dan), sin aviso y sin salto medido;
- **los rechazos** de lo que lee (el espesor mínimo y el salto admitido del proyecto), **los pasos** (RNF-016-03: ≤ 0,2 s cada
  llamada, cancelables, sin modificar ninguna entrada) y **el informe** del contrafuerte con sus filas y su aviso.
"""

from __future__ import annotations

import dataclasses
import math
import time
import unittest
from contextlib import closing
from typing import Any

import numpy as np

from tests.support import buttress_data as bdata
from tests.support import design_fixtures as dfx
from tests.support.package import import_geoblender
from tests.unit.gis.masks.test_combine import GRID as MASK_GRID
from tests.unit.gis.masks.test_combine import make as make_constraint
from tests.unit.gis.masks.test_combine import resolved_for

access = import_geoblender("gis.masks.access")
buttress = import_geoblender("design.buttress")
combine = import_geoblender("gis.masks.combine")
compose = import_geoblender("design.compose")
constraints = import_geoblender("core.constraints.model")
design_model = import_geoblender("design.model")
messages = import_geoblender("design.messages")
preview = import_geoblender("design.preview")
provenance = import_geoblender("design.provenance")
supported_store = import_geoblender("design.supported_store")

DesignError = messages.DesignError
FILL = design_model.BenchSense.FILL
T = constraints.ConstraintType
STEP = 2.0
THICKNESS = 0.02
JUMP = 1.0
SHARE = 99.0
PROJECT = {"des.tolerance.face_deg": 1.0, "des.warning.magnitude_ratio": 2.0, "res.verify.min_thickness_m": THICKNESS,
           "des.edge.max_created_step_m": JUMP, "des.edge.min_share": SHARE}
"""Los parámetros del proyecto que lee el pie cortado (el espesor mínimo de la 012 y el salto admitido de la 014 con su porcentaje):
datos de ENTRADA de la prueba, no de un proyecto."""
RELATIVE = 1e-9
FOOT_CUT = "des.buttress_foot_cut"


class Close(unittest.TestCase):
    def close(self, found: float, wanted: float, *, what: str = "", rel: float = RELATIVE) -> None:
        """``found`` es ``wanted`` a ≤ ``rel`` relativo (con un suelo de 1 para los ceros)."""
        self.assertLessEqual(abs(found - wanted), rel * max(abs(wanted), 1.0), f"{what}: {found} frente a {wanted}")

    def foot_notice(self, outcome: Any) -> Any:
        """El único aviso ``des.buttress_foot_cut`` del resultado."""
        (found,) = [notice for notice in outcome.notices if notice.code == FOOT_CUT]
        return found


def measured(scene: bdata.Scene, crown: float, **options: Any) -> tuple[Any, Any, Any]:
    """El trabajo, el contrafuerte calculado (A10) y el mismo con su pie cortado medido."""
    job = bdata.job_of(scene, crown, **options)
    outcome = buttress.compute_buttress(job)
    return job, outcome, buttress.measure_cutoff(job, outcome, PROJECT)


# --- La fórmula cerrada --------------------------------------------------------------------------------------------------------


class StripFootTest(Close):
    """RF-016-19: una franja de lado a lado (todas las columnas iguales) con el relleno prohibido desde la fila 40: lo que falta y el
    salto del borde salen del escalonado de cada fila (fórmula cerrada, sin el oráculo ni el código)."""

    ROWS, COLS, FIRST, LAST, LEVEL, LIMIT, CROWN = 60, 6, 28, 31, 102.0, 40, 120.0

    def scene(self) -> bdata.Scene:
        scene = bdata.strip_scene(self.ROWS, self.COLS, STEP, self.LEVEL, self.FIRST, self.LAST)
        scene.allowed[self.LIMIT:, :] = False
        return scene

    def check(self, metric: str) -> None:
        scene = self.scene()
        formula = bdata.strip_closed_form(self.ROWS, self.FIRST, self.LAST, level=self.LEVEL, crown=self.CROWN, found=scene.profile,
                                          step=STEP, metric=metric)
        rise = [value - self.LEVEL for value in formula.surface]
        cut = [r for r in range(self.LIMIT, self.ROWS) if rise[r] > 0.0]
        self.assertGreater(len(cut), 3, "el borde corta el pie")
        cell = STEP * STEP
        # el salto creado del borde de la superficie compuesta, por parejas de filas: una fila movida (admitida y que sube más del
        # espesor mínimo) junto a otra que no lo está; el mayor y, a igual salto, el primero de norte a sur
        moved = [r < self.LIMIT and rise[r] > THICKNESS for r in range(self.ROWS)]
        held = [formula.surface[r] if r < self.LIMIT else self.LEVEL for r in range(self.ROWS)]  # desde el borde, la partida
        border = [(r, abs(held[r] - held[r + 1])) for r in range(self.ROWS - 1) if moved[r] != moved[r + 1]]
        step_m = max(value for _r, value in border)
        row = min(r for r, value in border if value == step_m)
        _job, outcome, found = measured(scene, self.CROWN, metric=metric)
        self.assertIsNone(outcome.cutoff_m2)
        self.close(found.cutoff_m2, len(cut) * self.COLS * cell, what="el área que falta")
        self.close(found.cutoff_m3, math.fsum(rise[r] for r in cut) * self.COLS * cell, what="el volumen que falta")
        self.assertEqual(int(found.cutoff.sum()), len(cut) * self.COLS)
        self.assertEqual(found.created.pairs, len(border) * self.COLS)
        self.close(found.created.maximum_m, step_m, what="el salto creado")
        self.close(found.created.x, scene.grid.west + STEP / 2.0, what="su lugar (x: la primera columna)")
        self.close(found.created.y, scene.grid.north - (2 * row + 2) * STEP / 2.0, what="su lugar (y: entre dos filas)")
        notice = self.foot_notice(found)
        self.assertEqual(notice.severity, "warning")
        values = dict(notice.values)
        self.assertEqual(values["entity"], bdata.NAME)
        self.close(values["area"], found.cutoff_m2, what="el aviso: área")
        self.close(values["volume"], found.cutoff_m3, what="el aviso: volumen")
        self.close(values["step"], round(step_m, 2), what="el aviso: salto", rel=1e-12)

    def test_the_area_the_volume_and_the_created_step_are_the_closed_form_with_the_exact_metric(self) -> None:
        """RF-016-19: el pie cortado en la fila 40 de una franja: faltan las celdas de las filas del borde en adelante que el
        escalonado sube (área y volumen, a ≤ 10⁻⁹ relativo) y el salto creado del borde es el de la pareja de filas 39-40 (la
        última admitida y la primera cortada), con su lugar en la primera columna."""
        self.check("exact")

    def test_and_with_the_chamfer_metric(self) -> None:
        """RF-016-19: con la métrica *chamfer* la envolvente baja más despacio y lo que falta es otro número, el de la fórmula."""
        self.check("chamfer5")

    def test_the_summary_notice_says_it_in_both_languages_and_does_not_prevent_creating_it(self) -> None:
        """RF-016-19: el aviso nombra el contrafuerte, el área, el volumen, el salto y su lugar, sin marcadores por llenar, en español
        y en inglés; el contrafuerte es el de siempre (se calculó: sin impedir crearlo) y su superficie es la de A10, bit a bit."""
        _job, outcome, found = measured(self.scene(), self.CROWN)
        notice = self.foot_notice(found)
        for language in ("es", "en"):
            text = notice.text(language)
            self.assertNotIn("{", text)
            self.assertIn(bdata.NAME, text)
        self.assertIn("m²", notice.text("es"))
        self.assertIn("m²", notice.text("en"))
        self.assertIs(found.surface, outcome.surface)
        self.assertEqual(found.volume_m3, outcome.volume_m3)
        self.assertEqual(found.footprint.tobytes(), outcome.footprint.tobytes())

    def test_the_figures_are_the_five_of_the_operation(self) -> None:
        """RF-016-19, plan 016 §5.2.3: ``des.btr_cutoff_m2`` y ``des.btr_cutoff_m3`` (CALCULADO, con el ámbito de la entidad) se
        suman al volumen, el área y la altura máxima, por orden de ``BUTTRESS_FIGURES``; sin medir el pie, las tres de siempre."""
        _job, outcome, found = measured(self.scene(), self.CROWN)
        self.assertEqual([item.key for item in outcome.figures], [d.key for d in provenance.BUTTRESS_FIGURES[:3]])
        self.assertEqual([item.key for item in found.figures], [d.key for d in provenance.BUTTRESS_FIGURES])
        by_key = {item.key: item for item in found.figures}
        self.assertEqual((by_key["des.btr_cutoff_m2"].value, by_key["des.btr_cutoff_m2"].unit), (found.cutoff_m2, "m2"))
        self.assertEqual((by_key["des.btr_cutoff_m3"].value, by_key["des.btr_cutoff_m3"].unit), (found.cutoff_m3, "m3"))
        self.assertEqual(dict(by_key["des.btr_cutoff_m3"].scope), dict(by_key["des.btr_volume_m3"].scope))


# --- Una implementación independiente -----------------------------------------------------------------------------------------


class AgainstTheHandCalculationTest(Close):
    """RF-016-19: el relieve con celdas sin dato, un bloque sin relleno admitido dentro y la franja del este sin relleno, con las
    dos métricas: lo que falta, su área, su volumen y el salto creado (con su lugar) son los del cálculo a mano, celda a celda."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.scene = bdata.relief_scene()
        cls.runs: dict[str, tuple[Any, Any, Any, Any]] = {}
        for metric in ("exact", "chamfer5"):
            job, outcome, found = measured(cls.scene, 115.0, metric=metric)
            cls.runs[metric] = (job, outcome, found, bdata.hand_foot(cls.scene, 115.0, metric=metric, thickness=THICKNESS))

    def test_what_is_missing_is_the_hand_calculation_cell_by_cell(self) -> None:
        """RF-016-19: las celdas cortadas, su área y su volumen son los del bucle de Python (≤ 10⁻⁹ relativo) y hay pie cortado
        (el caso no es vacío): el bloque de dentro y la franja del este están en el alcance de la envolvente."""
        for metric, (_job, _outcome, found, hand) in self.runs.items():
            with self.subTest(metric=metric):
                self.assertGreater(hand.cells, 20)
                self.assertTrue(np.array_equal(found.cutoff, hand.mask))
                self.close(found.cutoff_m2, hand.area_m2, what="el área")
                self.close(found.cutoff_m3, hand.volume_m3, what="el volumen")

    def test_the_created_step_and_its_place_are_the_hand_calculation(self) -> None:
        """RF-016-19, RF-014-20: el salto creado del borde de la superficie compuesta —sus parejas, el mayor y su lugar— es el de los
        bucles de Python."""
        for metric, (_job, _outcome, found, hand) in self.runs.items():
            with self.subTest(metric=metric):
                self.assertEqual(found.created.pairs, hand.pairs)
                self.close(found.created.maximum_m, hand.step_m, what="el salto")
                self.close(found.created.x, hand.x, what="x")
                self.close(found.created.y, hand.y, what="y")
                values = self.foot_notice(found).values
                self.close(values["step"], round(max(hand.step_m, 0.0), 2), what="el aviso", rel=1e-12)
                self.close(values["x"], round(hand.x, 2), what="el aviso: x", rel=1e-12)
                self.close(values["y"], round(hand.y, 2), what="el aviso: y", rel=1e-12)

    def test_the_missing_foot_is_what_the_unmasked_stepping_has_over_the_composed_surface(self) -> None:
        """RF-016-19: lo que falta es **el escalonado sin máscara menos el compuesto**: ``máx(partida, recorte)`` con todo admitido
        menos la superficie con las máscaras, donde es mayor que 0; y solo en celdas sin relleno admitido."""
        for metric, (job, outcome, found, _hand) in self.runs.items():
            with self.subTest(metric=metric):
                free = compose.compose(job.start, outcome.stepped, np.ones(job.start.shape, dtype=bool), FILL)
                lost = free - outcome.surface
                self.assertTrue(np.array_equal(found.cutoff, lost > 0.0))
                self.assertFalse((found.cutoff & job.fill_allowed).any(), "una celda con relleno admitido no se corta")
                self.close(found.cutoff_m3, float(lost[lost > 0.0].sum()) * self.scene.grid.cell_area, what="el volumen")

    def test_the_summary_figures_follow_the_measure(self) -> None:
        """RF-016-19: las cifras ``des.btr_cutoff_*`` son el área y el volumen medidos."""
        for metric, (_job, _outcome, found, _hand) in self.runs.items():
            with self.subTest(metric=metric):
                by_key = {item.key: item.value for item in found.figures}
                self.assertEqual((by_key["des.btr_cutoff_m2"], by_key["des.btr_cutoff_m3"]), (found.cutoff_m2, found.cutoff_m3))


# --- Lo que no hay --------------------------------------------------------------------------------------------------------------


class NoFootCutTest(Close):
    """RF-016-19: sin pie cortado no hay aviso, y las cifras se dan: 0 m² y 0 m³ (medido y sin nada que faltar)."""

    def test_with_everything_admitted_nothing_is_missing(self) -> None:
        """RF-016-19: un llano con todo el relleno admitido: 0 m², 0 m³, ninguna celda cortada, ningún aviso y ningún salto medido
        (no hay borde que medir); las cifras ``des.btr_cutoff_*`` valen 0 y están."""
        _job, outcome, found = measured(bdata.plane_scene(), 110.0)
        self.assertEqual((found.cutoff_m2, found.cutoff_m3), (0.0, 0.0))
        self.assertFalse(found.cutoff.any())
        self.assertIsNone(found.created)
        self.assertEqual(found.notices, outcome.notices)
        self.assertEqual([item.key for item in found.figures], [d.key for d in provenance.BUTTRESS_FIGURES])
        self.assertEqual({item.key: item.value for item in found.figures}["des.btr_cutoff_m2"], 0.0)

    def test_what_the_footprint_does_not_reach_is_not_missing(self) -> None:
        """RF-016-19: una zona sin relleno admitido **donde la envolvente no llega** no es pie cortado: solo falta lo que el
        escalonado sin máscara subiría ahí."""
        scene = bdata.plane_scene()
        scene.allowed[:, :4] = False  # muy lejos de la zona (columnas 18 a 25) y de lo que alcanza el contrafuerte
        _job, _outcome, found = measured(scene, 110.0)
        self.assertEqual((found.cutoff_m2, found.cutoff_m3), (0.0, 0.0))

    def test_a_foot_cut_everywhere_is_still_no_buttress(self) -> None:
        """RF-016-17, T27: si el relleno no está admitido en ninguna celda que suba, no hay contrafuerte (no se calcula el pie
        cortado de lo que no existe): ``des.buttress_nothing_rises``, como antes."""
        scene = bdata.plane_scene()
        scene.allowed[:] = False
        job = bdata.job_of(scene, 110.0)
        with self.assertRaises(DesignError) as caught:
            list(supported_store.buttress_compute_steps(job, PROJECT, budget_s=0.05))
        self.assertEqual(caught.exception.code, "des.buttress_nothing_rises")


# --- Las máscaras de verdad -----------------------------------------------------------------------------------------------------


def real_masks(items: list[Any]) -> Any:
    """Las máscaras de la versión de las restricciones ``items`` (sin resguardo hacia dentro), con sus zonas y sus tipos como las lee
    un ``MaskSet``."""
    prepared = combine.prepare(items, resolved_for(items, inward=0.0), MASK_GRID)
    found = combine.combine(prepared.zones, prepared.limits, MASK_GRID)
    return access.MaskSet(MASK_GRID, "v-mano", "op-mano", access.MaskState.CURRENT, (), found.classes,
                          zones={code: zone.runs for code, zone in prepared.zones.items()},
                          ctypes={code: zone.ctype.value for code, zone in prepared.zones.items()})


class RealMasksTest(Close):
    """RF-016-19, RF-015-13, D-24, error 19, con las máscaras de la 012 de verdad (40 × 30 celdas de 1 m): el límite legal y el
    perímetro (0-40 × 0-30 y 1-39 × 1-29), una zona de «solo restauración» al este de la zona de coronación (x 22-30) y, más allá
    (x 30-38), la restricción «sin relleno» que declara la plataforma «en corte» ``PLT-001``."""

    PLATFORM = "Plataforma de carga"

    @classmethod
    def setUpClass(cls) -> None:
        items = [
            make_constraint("r_concesion", T.LEGAL_LIMIT, (0, 0, 40, 30), fid=1),
            make_constraint("r_perimetro", T.ACTION_PERIMETER, (1, 1, 39, 29), fid=2),
            make_constraint("r_restauracion", T.RESTORATION_ONLY, (22, 8, 30, 20), fid=3),
            make_constraint("dec__plt_001", T.NO_FILL, (30, 8, 38, 20), fid=4),
        ]
        cls.masks = real_masks(items)
        rows, cols = MASK_GRID.shape
        y, x = np.mgrid[0:rows, 0:cols]
        cls.x, cls.y = x + 0.5, rows - y - 0.5
        profile = bdata.profile(dfx.ProfileData("TWO_2_45_2", "two_2_45_2", 2.0, 45.0, 2.0, 100.0))
        zone = (cls.x > 12) & (cls.x < 18) & (cls.y > 10) & (cls.y < 18)
        cls.scene = bdata.Scene(MASK_GRID, np.full((rows, cols), 100.5), zone, compose.admitted(cls.masks, FILL), profile)
        cls.job, cls.outcome, cls.found = measured(cls.scene, 108.0)
        cls.hand = bdata.hand_foot(cls.scene, 108.0, thickness=THICKNESS)

    def zone_of(self, left: float, right: float) -> np.ndarray:
        return (self.x > left) & (self.x < right) & (self.y > 8) & (self.y < 20)

    def test_the_foot_leaves_the_drawn_zone_and_enters_the_restoration_one(self) -> None:
        """RF-016-17, D-24, error 19: el pie sale de la zona dibujada y sube dentro de la zona de solo restauración (el relleno está
        admitido ahí), y se corta donde el relleno no lo está: más allá de la restauración, en la zona de la plataforma, y fuera del
        perímetro por el oeste."""
        restoration = self.zone_of(22, 30)
        self.assertTrue((self.outcome.footprint & ~self.scene.zone).any())
        self.assertGreater(int((self.outcome.footprint & restoration).sum()), 10)
        self.assertFalse((self.found.cutoff & restoration).any(), "en la zona de restauración no se corta nada: el relleno se admite")
        self.assertGreater(int((self.found.cutoff & self.zone_of(30, 38)).sum()), 5, "la plataforma corta el pie del este")
        self.assertGreater(int((self.found.cutoff & (self.x < 1.0)).sum()), 5, "el perímetro corta el del oeste")

    def test_what_is_missing_the_created_step_and_the_place_are_the_hand_calculation(self) -> None:
        """RF-016-19: el área, el volumen, el salto creado y su lugar del pie cortado son los del cálculo a mano en estas máscaras."""
        self.assertTrue(np.array_equal(self.found.cutoff, self.hand.mask))
        self.close(self.found.cutoff_m2, self.hand.area_m2, what="el área")
        self.close(self.found.cutoff_m3, self.hand.volume_m3, what="el volumen")
        self.assertEqual(self.found.created.pairs, self.hand.pairs)
        self.close(self.found.created.maximum_m, self.hand.step_m, what="el salto")
        values = self.foot_notice(self.found).values
        self.assertEqual((values["x"], values["y"]), (round(self.hand.x, 2), round(self.hand.y, 2)))

    def test_the_platform_that_forbids_the_fill_is_named_with_the_area_it_holds(self) -> None:
        """RF-015-13, RF-015-10: el resumen da el área que el contrafuerte no rellena **por la restricción de la plataforma** (la
        suya, ``dec__plt_001``, «sin relleno»), con el nombre de la plataforma, y por separado lo que no admiten los límites; sus
        áreas suman el pie cortado: nada se pierde ni se cuenta dos veces."""
        held = supported_store.foot_held_notices(self.found, self.masks, names={}, declared={"dec__plt_001": self.PLATFORM})
        by_code = {notice.code: notice for notice in held}
        self.assertEqual(sorted(by_code), ["des.entity_held", "des.entity_held_masks"])
        platform = by_code["des.entity_held"]
        self.assertEqual((platform.values["entity"], platform.values["other"]), (bdata.NAME, self.PLATFORM))
        self.assertIn(f"«Plataforma {self.PLATFORM} (declarada)»", platform.text("es"))
        no_fill = self.zone_of(30, 38)
        self.assertEqual(platform.values["area"], float(np.count_nonzero(self.hand.mask & no_fill)))
        loose = by_code["des.entity_held_masks"]
        self.assertEqual(loose.values["area"], float(np.count_nonzero(self.hand.mask & ~no_fill)))
        self.close(platform.values["area"] + loose.values["area"], self.found.cutoff_m2, what="las dos suman el pie cortado")

    def test_over_the_platform_footprint_nothing_is_filled(self) -> None:
        """RF-015-13, CE-016-06: **sobre la zona de la plataforma el contrafuerte rellena 0 m³**: la superficie es la de partida bit a
        bit, aunque el escalonado sin máscara subiría ahí."""
        no_fill = self.zone_of(30, 38)
        self.assertTrue((self.outcome.stepped[no_fill] > self.scene.start[no_fill]).any())
        self.assertEqual(self.outcome.surface[no_fill].tobytes(), self.scene.start[no_fill].tobytes())
        self.assertEqual(float((self.outcome.surface - self.scene.start)[no_fill].sum()), 0.0)

    def test_without_a_cut_the_summary_has_no_held_notice(self) -> None:
        """RF-015-13: sin pie cortado no hay celdas que explicar: ningún aviso de lo que no se mueve."""
        none = dataclasses.replace(self.found, cutoff=np.zeros(self.found.cutoff.shape, dtype=bool), cutoff_m2=0.0, cutoff_m3=0.0)
        self.assertEqual(supported_store.foot_held_notices(none, self.masks, names={}, declared={}), ())


# --- Lo que rechaza -------------------------------------------------------------------------------------------------------------


class RefusalsTest(Close):
    """El pie cortado lee del proyecto el espesor mínimo de la 012 y el salto admitido de la 014 con su porcentaje (ninguno lleva
    valor por defecto): un valor que falta, no finito o fuera de rango se rechaza al llamar, sin medir nada."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.scene = bdata.strip_scene()
        cls.scene.allowed[40:, :] = False
        cls.job = bdata.job_of(cls.scene, 120.0)
        cls.outcome = buttress.compute_buttress(cls.job)

    def test_a_missing_or_not_finite_value_of_the_project_is_a_program_error(self) -> None:
        """Quien llama lee los parámetros del proyecto: sin ellos (o sin ser un número finito) es un error del programa."""
        for key in ("res.verify.min_thickness_m", "des.edge.max_created_step_m", "des.edge.min_share"):
            for bad in (None, math.nan, "1"):
                with self.subTest(key=key, value=bad):
                    given = {**PROJECT, key: bad}
                    with self.assertRaises(ValueError) as caught:
                        buttress.measure_cutoff(self.job, self.outcome, given)
                    self.assertIn(key, str(caught.exception))
            missing = {name: value for name, value in PROJECT.items() if name != key}
            with self.assertRaises(ValueError):
                buttress.measure_cutoff(self.job, self.outcome, missing)

    def test_a_negative_thickness_and_a_jump_out_of_range_are_refused(self) -> None:
        """El espesor mínimo es finito y ≥ 0 (``ValueError``) y el salto admitido y su porcentaje están en su rango (``des.quarry_
        param_range``, como en el borde de la plataforma): se rechazan al llamar."""
        with self.assertRaises(ValueError):
            buttress.measure_cutoff(self.job, self.outcome, {**PROJECT, "res.verify.min_thickness_m": -0.1})
        for key, bad in (("des.edge.max_created_step_m", 0.0), ("des.edge.max_created_step_m", -1.0), ("des.edge.min_share", 0.0),
                         ("des.edge.min_share", 120.0)):
            with self.subTest(key=key, value=bad), self.assertRaises(DesignError) as caught:
                buttress.measure_cutoff(self.job, self.outcome, {**PROJECT, key: bad})
            self.assertEqual(caught.exception.code, "des.quarry_param_range")

    def test_a_result_of_another_job_is_a_program_error(self) -> None:
        """Un resultado que no es de su trabajo (otro código o una ventana de otra forma) es un error del programa."""
        other = dataclasses.replace(self.outcome, code="BTR-002")
        with self.assertRaises(ValueError):
            buttress.measure_cutoff(self.job, other, PROJECT)
        short = dataclasses.replace(self.outcome, stepped=self.outcome.stepped[:-1])
        with self.assertRaises(ValueError):
            buttress.measure_cutoff(self.job, short, PROJECT)
        with self.assertRaises(ValueError):
            buttress.measure_cutoff(self.job, object(), PROJECT)  # type: ignore[arg-type]


# --- Los pasos y lo que no se modifica ------------------------------------------------------------------------------------------


class StepsTest(Close):
    """RNF-016-03, RF-016-19: por pasos de ``budget_s`` como mucho (≤ 0,2 s cada llamada), cancelable y sin modificar ninguna
    entrada; el mismo resultado de una vez que por pasos."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.scene = bdata.relief_scene()
        cls.job = bdata.job_of(cls.scene, 115.0)
        cls.outcome = buttress.compute_buttress(cls.job)

    def test_by_steps_it_is_the_same_as_at_once(self) -> None:
        """Los pasos (con un presupuesto de 0 s: uno por unidad) dan el mismo resultado que de una vez, con la fase
        ``buttress_cutoff`` al final y varios pasos antes."""
        once = buttress.measure_cutoff(self.job, self.outcome, PROJECT)
        found = list(buttress.cutoff_steps(self.job, self.outcome, PROJECT, budget_s=0.0))
        self.assertGreater(len(found), 5)
        self.assertEqual(found[-1].phase, "buttress_cutoff")
        self.assertTrue(all(step.result is None for step in found[:-1]))
        last = found[-1].result
        self.assertTrue(np.array_equal(last.cutoff, once.cutoff))
        self.assertEqual((last.cutoff_m2, last.cutoff_m3), (once.cutoff_m2, once.cutoff_m3))
        self.assertEqual((last.created.pairs, last.created.maximum_m, last.created.x, last.created.y),
                         (once.created.pairs, once.created.maximum_m, once.created.x, once.created.y))
        self.assertEqual([(n.code, dict(n.values)) for n in last.notices], [(n.code, dict(n.values)) for n in once.notices])

    def test_every_call_takes_at_most_a_fifth_of_a_second(self) -> None:
        """RNF-016-03: cada llamada de los pasos (con el presupuesto de la interfaz, 0,05 s) cuesta ≤ 0,2 s."""
        steps = buttress.cutoff_steps(self.job, self.outcome, PROJECT, budget_s=0.05)
        worst = 0.0
        while True:
            began = time.perf_counter()
            try:
                step = next(steps)
            except StopIteration:
                break
            worst = max(worst, time.perf_counter() - began)
            if step.result is not None:
                break
        self.assertLess(worst, 0.2)

    def test_closing_halfway_leaves_nothing_and_no_input_changes(self) -> None:
        """RF-015-29: cerrar los pasos a mitad no deja nada, y el trabajo y el resultado de A10 no cambian ni un bit (el resultado
        medido es **otro**: el original sigue sin su pie)."""
        before_job = [array.tobytes() for array in (self.job.start, self.job.zone, self.job.fill_allowed)]
        before_outcome = [array.tobytes() for array in (self.outcome.surface, self.outcome.stepped, self.outcome.footprint)]
        for stop in (1, 3):
            with closing(buttress.cutoff_steps(self.job, self.outcome, PROJECT, budget_s=0.0)) as steps:
                for _ in range(stop):
                    next(steps)
        full = buttress.measure_cutoff(self.job, self.outcome, PROJECT)
        self.assertIsNot(full, self.outcome)
        self.assertIsNone(self.outcome.cutoff_m2)
        self.assertEqual(self.outcome.notices, ())
        self.assertEqual([array.tobytes() for array in (self.job.start, self.job.zone, self.job.fill_allowed)], before_job)
        self.assertEqual([array.tobytes() for array in (self.outcome.surface, self.outcome.stepped, self.outcome.footprint)],
                         before_outcome)

    def test_the_compute_steps_of_the_store_measure_the_foot_too(self) -> None:
        """RF-016-19, plan 016 §5.3.2: ``buttress_compute_steps`` (el de «Calcular», el recálculo y la reproducción) da el
        contrafuerte con su pie ya medido —el mismo que A10 más ``measure_cutoff``— sin pasar por el proyecto."""
        generator = supported_store.buttress_compute_steps(self.job, PROJECT, budget_s=0.05)
        try:
            while True:
                next(generator)
        except StopIteration as done:
            found = done.value
        wanted = buttress.measure_cutoff(self.job, self.outcome, PROJECT)
        self.assertTrue(np.array_equal(found.cutoff, wanted.cutoff))
        self.assertEqual((found.cutoff_m2, found.cutoff_m3), (wanted.cutoff_m2, wanted.cutoff_m3))
        self.assertEqual([n.code for n in found.notices], [n.code for n in wanted.notices])


# --- El informe del contrafuerte --------------------------------------------------------------------------------------------------


class ReportRowsTest(Close):
    """RF-016-19: el informe del contrafuerte (``des_prp_``) lleva el pie cortado —su área, su volumen y el salto con su lugar— y
    el aviso como nota, para que lo repita la reproducción."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.scene = bdata.strip_scene()
        cls.scene.allowed[40:, :] = False
        cls.job, cls.outcome, cls.found = measured(cls.scene, 120.0)

    def test_the_rows_carry_the_foot_and_the_warning(self) -> None:
        """Las filas escalares ``cutoff_m2`` y ``cutoff_m3`` (con su unidad), el salto con su lugar y, al final, el aviso con su
        código y sus valores."""
        rows = supported_store.buttress_report_rows(self.found)
        by_key = {row[0]: row for row in rows}
        self.assertEqual(by_key["cutoff_m2"][1:3], (self.found.cutoff_m2, "m2"))
        self.assertEqual(by_key["cutoff_m3"][1:3], (self.found.cutoff_m3, "m3"))
        step = by_key["cutoff_step_m"]
        self.assertEqual((step[1], step[2]), (self.found.created.maximum_m, "m"))
        self.assertEqual(step[3], f"{self.found.created.x!r};{self.found.created.y!r}")
        warning = [row for row in rows if row[0] == "warning" and FOOT_CUT in row[3]]  # T46: la franja llega al borde de la rejilla: hay otro aviso
        self.assertEqual(len(warning), 1)
        self.assertEqual(rows[-1], warning[0], "los avisos van al final")

    def test_without_the_foot_measured_the_rows_are_the_old_ones(self) -> None:
        """Un resultado sin su pie medido (A10 solo) da las filas de siempre, sin las del pie."""
        old = supported_store.buttress_report_rows(self.outcome)
        self.assertFalse({row[0] for row in old} & {"cutoff_m2", "cutoff_m3", "cutoff_step_m"})
        new = supported_store.buttress_report_rows(self.found)
        self.assertEqual([row for row in new if row[0] not in ("cutoff_m2", "cutoff_m3", "cutoff_step_m")
                          and not (row[0] == "warning" and FOOT_CUT in row[3])], old)

    def test_a_foot_that_is_not_cut_reports_zeros_and_no_step(self) -> None:
        """Sin pie cortado: ``cutoff_m2`` y ``cutoff_m3`` valen 0, no hay fila del salto ni aviso."""
        _job, _outcome, found = measured(bdata.plane_scene(), 110.0)
        rows = {row[0]: row for row in supported_store.buttress_report_rows(found)}
        self.assertEqual((rows["cutoff_m2"][1], rows["cutoff_m3"][1]), (0.0, 0.0))
        self.assertNotIn("cutoff_step_m", rows)
        self.assertNotIn("warning", rows)


if __name__ == "__main__":
    unittest.main()

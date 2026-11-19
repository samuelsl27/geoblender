# SPDX-License-Identifier: GPL-3.0-or-later
"""Caso de referencia del pie cortado del contrafuerte (spec 016, T28; HU-016-3; RF-016-17, RF-016-19, RF-015-13; CE-016-06, la
regresión del error 19; plan 016 §5.4 A10; D-24; sin proyecto y sin datos de cliente).

**CE-016-06** · el llano de CE-016-10 (115 m, celdas de 1 m, ventana de 100 × 100 m) con una zona de coronación de 20 × 20 m
(``x`` 30-50, ``y`` 40-60: 400 celdas), el perfil ``EXPL_10_60_6`` (``h`` = 10 m, cara a 60°, berma de 6 m, ancla a 125 m) y su
coronación a **135 m** (dos bancos por encima del plano: el pie llega a unos 17,5 m de la zona), con las máscaras de la 012 de verdad:

- **junto a una zona de solo restauración y al límite** (A): el límite legal y el perímetro, de 0 a 60 m por el este, y la zona de
  «solo restauración» de 50 a 58 m (la 012 admite el relleno en ella y no el corte: D-24). El pie **sale de la zona dibujada**
  (error 19: las cuatro caras), **entra en la de solo restauración** —dentro de lo admitido, sin cortarse un metro— y **donde el
  límite lo corta**, desde ``x`` = 60 m, faltan **272 m² y 1.417,38 m³** (el escalonado sin máscara menos el compuesto) con un
  **salto creado de 10,00 m** en ese borde (la berma a 125 m sobre el plano de 115 m: lo que sube justo antes del límite);
- **junto a una plataforma «en corte» protegida de la 015** (B): su restricción «sin relleno» declarada (``dec__plt_001``) sobre una
  huella de 14 × 40 m (``x`` 10-24, ``y`` 30-70) que el pie del oeste pisaría: sobre ella el contrafuerte **rellena 0 m³** (la
  superficie es el plano, bit a bit) y el resumen da **el área que no rellena, 420 m², con la plataforma** (RF-015-13), con un salto
  creado de 10,00 m en el borde de su huella (2.959,65 m³ que faltan).

Las cifras salen del **cálculo a mano en las mismas celdas** (:func:`tests.support.buttress_data.hand_foot`: el oráculo
independiente de la T26 con y sin máscaras, la diferencia celda a celda y el salto creado por parejas, en bucles de Python con
``fsum``) y se escriben aquí como valores de referencia (:data:`CASES`); se comprueban a ≤ 10⁻⁹ relativo con las dos métricas.
"""

from __future__ import annotations

import unittest
from typing import Any

import numpy as np

from tests.support import buttress_data as bdata
from tests.support import design_fixtures as dfx
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.unit.gis.masks.test_combine import make as make_constraint
from tests.unit.gis.masks.test_combine import resolved_for

access = import_geoblender("gis.masks.access")
buttress = import_geoblender("design.buttress")
combine = import_geoblender("gis.masks.combine")
compose = import_geoblender("design.compose")
constraints = import_geoblender("core.constraints.model")
design_model = import_geoblender("design.model")
supported_store = import_geoblender("design.supported_store")

FILL = design_model.BenchSense.FILL
T = constraints.ConstraintType
RELATIVE = 1e-9
N = 100
GRID = dfx.grid_from(N, N, 1.0)
ZONE_LOCAL = (30.0, 40.0, 50.0, 60.0)
CROWN_M = 135.0
PLANE_M = 115.0
PLATFORM = "Plataforma de carga"
PLATFORM_LOCAL = (10.0, 30.0, 24.0, 70.0)
RESTORATION_LOCAL = (50.0, 0.0, 58.0, 100.0)
PROJECT = {"des.tolerance.face_deg": 1.0, "des.warning.magnitude_ratio": 2.0, "res.verify.min_thickness_m": 0.02,
           "des.edge.max_created_step_m": 1.0, "des.edge.min_share": 99.0}
"""Los parámetros del proyecto que lee el pie cortado (datos de ENTRADA de la prueba, no de un proyecto)."""

# escena, métrica -> celdas que faltan, volumen que falta (m³), parejas del borde, salto creado (m) y su lugar local (x, y): el cálculo a mano
CASES: dict[tuple[str, str], tuple[int, float, int, float, tuple[float, float]]] = {
    ("A", "exact"): (272, 1417.3839015379997, 202, 10.0, (60.0, 65.5)),
    ("A", "chamfer5"): (270, 1464.8572330535483, 202, 10.0, (60.0, 65.5)),
    ("B", "exact"): (420, 2959.6457924302404, 222, 10.0, (24.0, 69.5)),
    ("B", "chamfer5"): (418, 3008.2078261543916, 222, 10.0, (24.0, 69.5)),
}
BUTTRESS_M3 = {  # el contrafuerte de la huella entera con las máscaras: volumen (m³) y área (m²), el cálculo a mano
    ("A", "exact"): (26272.588246480824, 2392.0), ("A", "chamfer5"): (26475.037418175383, 2386.0),
    ("B", "exact"): (24730.326355588582, 2244.0), ("B", "chamfer5"): (24931.68682507454, 2238.0),
}
FREE_M3 = {  # y sin máscaras (todo admitido): lo que sería
    "exact": (27689.97214801882, 2664.0), "chamfer5": (27939.89465122893, 2656.0)}


def masks_of(items: list[Any]) -> Any:
    """Las máscaras de la 012 de las restricciones ``items`` (sin resguardo hacia dentro), con sus zonas y sus tipos."""
    prepared = combine.prepare(items, resolved_for(items, inward=0.0), GRID)
    found = combine.combine(prepared.zones, prepared.limits, GRID)
    return access.MaskSet(GRID, "v-mano", "op-mano", access.MaskState.CURRENT, (), found.classes,
                          zones={code: zone.runs for code, zone in prepared.zones.items()},
                          ctypes={code: zone.ctype.value for code, zone in prepared.zones.items()})


CONSTRAINTS = {
    "A": [make_constraint("r_concesion", T.LEGAL_LIMIT, (0, 0, 60, 100), fid=1),
          make_constraint("r_perimetro", T.ACTION_PERIMETER, (0, 0, 60, 100), fid=2),
          make_constraint("r_restauracion", T.RESTORATION_ONLY, RESTORATION_LOCAL, fid=3)],
    "B": [make_constraint("r_concesion", T.LEGAL_LIMIT, (0, 0, 100, 100), fid=1),
          make_constraint("r_perimetro", T.ACTION_PERIMETER, (0, 0, 100, 100), fid=2),
          make_constraint("dec__plt_001", T.NO_FILL, PLATFORM_LOCAL, fid=3)],
}


class FootCutTest(unittest.TestCase):
    """CE-016-06, RF-016-19, RF-015-13: las dos escenas con las dos métricas, calculadas una vez."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.masks: dict[str, Any] = {}
        cls.scenes: dict[str, bdata.Scene] = {}
        cls.results: dict[tuple[str, str], tuple[Any, Any]] = {}
        for name, items in CONSTRAINTS.items():
            masks = masks_of(items)
            cls.masks[name] = masks
            cls.scenes[name] = bdata.Scene(GRID, np.full((N, N), PLANE_M), sdata.in_box(ZONE_LOCAL, GRID), compose.admitted(masks, FILL),
                                           bdata.profile(dfx.EXPL_10_60_6))
            for metric in ("exact", "chamfer5"):
                job = bdata.job_of(cls.scenes[name], CROWN_M, metric=metric)
                outcome = buttress.compute_buttress(job)
                cls.results[name, metric] = (outcome, buttress.measure_cutoff(job, outcome, PROJECT))

    def each(self) -> Any:
        for (name, metric), (outcome, found) in self.results.items():
            with self.subTest(scene=name, metric=metric):
                yield name, metric, outcome, found

    def close(self, found: float, wanted: float, what: str, rel: float = RELATIVE) -> None:
        self.assertLessEqual(abs(found - wanted), rel * max(abs(wanted), 1.0), f"{what}: {found} frente a {wanted}")

    def zone_of(self, box: tuple[float, float, float, float]) -> np.ndarray:
        return sdata.in_box(box, GRID)

    def test_the_foot_leaves_the_drawn_zone_and_enters_the_restoration_zone(self) -> None:
        """RF-016-17, D-24, error 19: **el pie sale de la zona dibujada** (por las cuatro caras) y **entra en la zona de solo
        restauración** (la 012 admite ahí el relleno: sube y no se corta ni una celda), hasta donde el límite lo corta (x = 60 m)."""
        restoration = self.zone_of(RESTORATION_LOCAL)
        scene = self.scenes["A"]
        zone_rows, zone_cols = np.nonzero(scene.zone)
        for metric in ("exact", "chamfer5"):
            outcome, found = self.results["A", metric]
            with self.subTest(metric=metric):
                outside = outcome.footprint & ~scene.zone
                rows, cols = np.nonzero(outside)
                self.assertLess(int(rows.min()), int(zone_rows.min()))
                self.assertGreater(int(rows.max()), int(zone_rows.max()))
                self.assertLess(int(cols.min()), int(zone_cols.min()))
                self.assertGreater(int(cols.max()), int(zone_cols.max()))
                self.assertTrue(scene.allowed[restoration].all(), "la 012 admite el relleno en la zona de solo restauración")
                self.assertGreater(int((outcome.footprint & restoration).sum()), 100)
                self.assertFalse((found.cutoff & restoration).any(), "dentro de lo admitido no se corta nada")
                # y el límite lo corta: ni una celda de la superficie más allá de x = 60 m, y sí de lo que el escalonado sin máscara subiría
                beyond = self.zone_of((60.0, 0.0, 100.0, 100.0))
                self.assertFalse((outcome.surface[beyond] != scene.start[beyond]).any())
                self.assertTrue((outcome.stepped[beyond] > scene.start[beyond]).any())
                self.assertTrue(np.array_equal(found.cutoff & ~beyond, np.zeros(beyond.shape, dtype=bool)), "solo corta el límite")

    def test_where_the_limit_cuts_it_the_notice_gives_the_area_the_volume_and_the_created_step(self) -> None:
        """RF-016-19, CE-016-06: donde el límite corta el pie, el aviso da el área (272 m²), el volumen (1.417,38 m³) y el salto creado
        de ese borde con su lugar (10,00 m en x = 60 m: la berma a 125 m sobre el plano de 115 m), a ≤ 10⁻⁹ relativo de las cifras a
        mano, con las dos métricas; y es un **aviso**: el contrafuerte es el de A10, el mismo bit a bit."""
        for metric in ("exact", "chamfer5"):
            outcome, found = self.results["A", metric]
            cells, volume, pairs, step, (x, y) = CASES["A", metric]
            with self.subTest(metric=metric):
                self.assertEqual(int(found.cutoff.sum()), cells)
                self.close(found.cutoff_m2, float(cells), "el área")
                self.close(found.cutoff_m3, volume, "el volumen")
                self.assertEqual(found.created.pairs, pairs)
                self.close(found.created.maximum_m, step, "el salto creado")
                self.close(found.created.x - sdata.BASE[0], x, "x")
                self.close(found.created.y - sdata.BASE[1], y, "y")
                (notice,) = [item for item in found.notices if item.code == "des.buttress_foot_cut"]
                self.assertEqual(notice.severity, "warning")
                self.assertEqual((notice.values["area"], notice.values["step"]), (found.cutoff_m2, round(step, 2)))
                self.close(notice.values["volume"], volume, "el aviso: volumen")
                self.close(float(notice.values["x"]) - sdata.BASE[0], x, "el aviso: x", rel=1e-12)
                self.close(float(notice.values["y"]) - sdata.BASE[1], y, "el aviso: y", rel=1e-12)
                self.assertIs(found.surface, outcome.surface)
                self.assertEqual(found.footprint.tobytes(), outcome.footprint.tobytes())

    def test_the_figures_are_the_hand_calculation_of_the_missing_foot(self) -> None:
        """RF-016-19: lo que falta es el contrafuerte sin máscaras menos el de las máscaras, a mano e independiente: el volumen y el
        área de la huella entera con y sin ellas dan exactamente lo medido (la diferencia, a ≤ 10⁻⁹ relativo)."""
        for name, metric, outcome, found in self.each():
            held_volume, held_area = BUTTRESS_M3[name, metric]
            free_volume, free_area = FREE_M3[metric]
            self.close(outcome.volume_m3, held_volume, "el volumen del contrafuerte")
            self.close(outcome.area_m2, held_area, "su área")
            self.close(found.cutoff_m3, free_volume - held_volume, "el volumen que falta")
            self.close(found.cutoff_m2, free_area - held_area, "el área que falta")

    def test_it_is_the_independent_calculation(self) -> None:
        """RF-016-19: las celdas cortadas, el área, el volumen, las parejas, el salto y su lugar son los de
        :func:`tests.support.buttress_data.hand_foot` (el oráculo independiente, en bucles de Python), celda a celda."""
        for name, metric, _outcome, found in self.each():
            hand = bdata.hand_foot(self.scenes[name], CROWN_M, metric=metric, thickness=PROJECT["res.verify.min_thickness_m"])
            self.assertTrue(np.array_equal(found.cutoff, hand.mask))
            self.close(found.cutoff_m2, hand.area_m2, "el área")
            self.close(found.cutoff_m3, hand.volume_m3, "el volumen")
            self.assertEqual(found.created.pairs, hand.pairs)
            self.close(found.created.maximum_m, hand.step_m, "el salto")
            self.close(found.created.x, hand.x, "x")
            self.close(found.created.y, hand.y, "y")

    def test_next_to_a_protected_cut_platform_it_fills_nothing_over_its_footprint(self) -> None:
        """RF-015-13, CE-016-06: junto a una plataforma «en corte» protegida (su «sin relleno» declarado) el contrafuerte **rellena
        0 m³ en su huella**: la superficie es el plano, bit a bit, aunque el escalonado sin máscara subiría ahí; y lo hace **sin
        cortar nada más**: el pie del este, el de las otras caras y el del interior de la zona sí suben."""
        platform = self.zone_of(PLATFORM_LOCAL)
        scene = self.scenes["B"]
        for metric in ("exact", "chamfer5"):
            outcome, found = self.results["B", metric]
            with self.subTest(metric=metric):
                self.assertFalse(scene.allowed[platform].any(), "la plataforma prohíbe el relleno en toda su huella")
                self.assertTrue((outcome.stepped[platform] > scene.start[platform]).any(), "el escalonado sin máscara subiría ahí")
                self.assertEqual(outcome.surface[platform].tobytes(), scene.start[platform].tobytes())
                self.assertEqual(float((outcome.surface - scene.start)[platform].sum()), 0.0, "0 m³ en su huella")
                self.assertTrue(np.array_equal(found.cutoff & ~platform, np.zeros(platform.shape, dtype=bool)), "solo corta la plataforma")
                self.assertGreater(int((outcome.footprint & ~platform).sum()), 2000, "lo demás del pie sube")

    def test_the_summary_gives_the_area_it_does_not_fill_with_the_platform(self) -> None:
        """RF-015-13, CE-016-06: el resumen da **el área que no rellena, con la plataforma** (``des.entity_held`` con su nombre y los
        420 m² de su huella que el pie pisaría) y no la nombra por su código interno; y es el área que falta del pie cortado."""
        for metric in ("exact", "chamfer5"):
            _outcome, found = self.results["B", metric]
            with self.subTest(metric=metric):
                held = supported_store.foot_held_notices(found, self.masks["B"], names={}, declared={"dec__plt_001": PLATFORM})
                (notice,) = held
                self.assertEqual(notice.code, "des.entity_held")
                self.assertEqual((notice.values["entity"], notice.values["other"]), (bdata.NAME, PLATFORM))
                self.assertEqual(notice.values["area"], float(CASES["B", metric][0]))
                self.assertEqual(notice.values["area"], found.cutoff_m2, "es toda el área que falta")
                for language, wanted in (("es", f"«Plataforma {PLATFORM} (declarada)»"), ("en", f"«Platform {PLATFORM} (declared)»")):
                    self.assertIn(wanted, notice.text(language))
                    self.assertNotIn("dec__plt_001", notice.text(language))

    def test_what_the_limit_does_not_admit_is_told_apart_from_the_restrictions(self) -> None:
        """RF-015-13: lo que corta el límite (la escena A, sin restricción declarada) lo dice ``des.entity_held_masks`` («las máscaras
        de la versión no lo admiten»), con el mismo área que el pie cortado: ni lo suyo se atribuye a una restricción ni se pierde."""
        for metric in ("exact", "chamfer5"):
            _outcome, found = self.results["A", metric]
            with self.subTest(metric=metric):
                (notice,) = supported_store.foot_held_notices(found, self.masks["A"], names={}, declared={})
                self.assertEqual(notice.code, "des.entity_held_masks")
                self.assertEqual(notice.values["area"], found.cutoff_m2)


if __name__ == "__main__":
    unittest.main()

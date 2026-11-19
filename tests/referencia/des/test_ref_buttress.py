# SPDX-License-Identifier: GPL-3.0-or-later
"""Caso de referencia del contrafuerte (spec 016, T26; HU-016-3; RF-016-01, RF-016-17, RF-016-18; CE-016-10; plan 016 §5.4 A10,
§7.1; D-7, D-21, D-24).

**CE-016-10** · un **tronco de pirámide escalonado** sobre un plano, con la coronación en el ancla de su perfil de la 013:

- el llano de la T01 (``stockpile_data.flat_window``): un plano a 115 m en una ventana de 120 m con celdas de 1 m y una zona de
  coronación de 40 × 30 m (1.200 celdas), con el perfil ``EXPL_10_60_6`` (``h`` = 10 m, cara a 60°, berma de 6 m, ancla a 125
  m) y su coronación a **125 m** (un banco por encima del plano: una cara de 10 m y una sola berma a la cota del plano) y a
  **145 m** (tres bancos: coronación, dos bermas a 135 y 125 m y la del plano);
- el **volumen**, el **área** y la **altura máxima** son los del cálculo a mano en las mismas celdas
  (:func:`tests.support.design_oracles.hand_buttress`: la envolvente por fuerza bruta o el *Dijkstra* del *chamfer*, el escalonado
  de RF-013-23 en aritmética racional, su recorte final y la composición, con ``fsum``) a ≤ 10⁻⁹ relativo, con las dos métricas;
  sus cifras con celdas de 1 m (:data:`CASES`) salen de ese cálculo: con la euclídea exacta, 125 m: 15.555,93 m³ sobre 1.980 m²
  (los 1.200 m² de la zona y 780 de pie) y 145 m: 122.808,11 m³ sobre 7.852 m²;
- la **altura máxima** es la coronación menos el plano (10 y 30 m, a ≤ 10⁻⁹): las celdas de en medio de la zona no las baja el
  recorte;
- **ninguna celda cortada** (la superficie no baja en ninguna celda y lo que no sube es el plano bit a bit) y **el pie fuera de la
  zona dibujada** (error 19): hay contrafuerte —en las cuatro caras— fuera de los 40 × 30 m de la zona;
- las **bermas** están en las cotas del ancla ``125 + n·10`` m;
- una **coronación fuera del ancla se rechaza con la cota del ancla más próxima** (D-21, RF-016-18): 127 m, 125; 131 m, 135;
  130 m (a igual distancia, la menor), 125; y sin elegir ninguna por la persona ni crear nada.
"""

from __future__ import annotations

import math
import unittest
from typing import Any

import numpy as np

from tests.support import buttress_data as bdata
from tests.support.package import import_geoblender

buttress = import_geoblender("design.buttress")
messages = import_geoblender("design.messages")

DesignError = messages.DesignError
RELATIVE = 1e-9
PLANE_M = 115.0
CASES: tuple[tuple[float, str, float, float], ...] = (
    # coronación (m), métrica, volumen (m³) y área (m²) de la huella entera: el cálculo a mano (oráculo racional) con celdas de 1 m
    (125.0, "exact", 15555.9290852148, 1980.0),
    (125.0, "chamfer5", 15656.056754056714, 1980.0),
    (145.0, "exact", 122808.10856695555, 7852.0),
    (145.0, "chamfer5", 123807.31682579461, 7848.0),
)


class FlatButtressTest(unittest.TestCase):
    """CE-016-10: el tronco de pirámide escalonado del llano de la T01, con la coronación en el ancla de su perfil."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.scene = bdata.flat_window_scene(1.0)
        cls.hand: dict[tuple[float, str], Any] = {}
        cls.found: dict[tuple[float, str], Any] = {}
        for crown in (125.0, 145.0):
            for metric in ("exact", "chamfer5"):
                cls.hand[crown, metric] = bdata.hand_of(cls.scene, crown, metric=metric)
                cls.found[crown, metric] = buttress.compute_buttress(bdata.job_of(cls.scene, crown, metric=metric))

    def each(self) -> Any:
        for key, outcome in self.found.items():
            with self.subTest(crown=key[0], metric=key[1]):
                yield key[0], key[1], outcome, self.hand[key]

    def close(self, found: float, wanted: float, what: str, rel: float = RELATIVE) -> None:
        self.assertLessEqual(abs(found - wanted), rel * max(abs(wanted), 1.0), f"{what}: {found} frente a {wanted}")

    def test_the_scene_is_the_flat_window_of_the_spec(self) -> None:
        """La T01: un plano a 115 m, la zona de 40 × 30 m (1.200 m²) y el perfil ``EXPL_10_60_6`` con el ancla a 125 m."""
        scene = self.scene
        self.assertTrue(np.all(scene.start == PLANE_M))
        self.assertEqual(int(scene.zone.sum()) * scene.grid.cell_area, 1200.0)
        self.assertEqual((scene.profile.name, scene.profile.anchor_m, scene.profile.height_m), ("EXPL_10_60_6", 125.0, 10.0))

    def test_volume_area_and_height_are_the_hand_calculation(self) -> None:
        """RF-016-17, CE-016-10: el volumen, el área y la altura máxima son los del cálculo a mano en las mismas celdas, a ≤ 10⁻⁹
        relativo, con las dos métricas y con una y tres bancos; y la superficie y el recorte, celda a celda a ≤ 10⁻⁹ m."""
        for _crown, _metric, outcome, hand in self.each():
            self.close(outcome.volume_m3, hand.volume_m3, "el volumen")
            self.close(outcome.area_m2, hand.area_m2, "el área")
            self.close(outcome.height_max_m, hand.height_max_m, "la altura máxima")
            self.assertEqual(int(outcome.footprint.sum()), hand.cells)
            self.assertLessEqual(float(np.abs(outcome.surface - hand.surface).max()), 1e-9)
            self.assertLessEqual(float(np.abs(outcome.stepped - hand.stepped).max()), 1e-9)
            self.assertTrue(np.array_equal(outcome.seeds, self.scene.zone))

    def test_the_volumes_of_the_case_are_the_ones_of_the_hand_calculation(self) -> None:
        """Los volúmenes (m³) y las áreas (m²) con las dos métricas, calculados a mano con el oráculo racional y escritos aquí
        como valores de referencia: si el escalonado, el recorte o la composición cambian, cambian."""
        for crown, metric, volume, area in CASES:
            with self.subTest(crown=crown, metric=metric):
                outcome = self.found[crown, metric]
                self.close(outcome.volume_m3, volume, "el volumen", 1e-9)
                self.close(outcome.area_m2, area, "el área", 1e-9)

    def test_the_height_is_the_crown_over_the_plane(self) -> None:
        """RF-016-17: la altura máxima es la cota de coronación menos el plano (las celdas de en medio de la zona no las baja el
        recorte), a ≤ 10⁻⁹, y la coronación llega a la cota pedida."""
        for crown, _metric, outcome, _hand in self.each():
            self.close(outcome.height_max_m, crown - PLANE_M, "la altura")
            self.close(float(outcome.surface.max()), crown, "la cota más alta")

    def test_no_cell_is_cut_and_the_foot_is_outside_the_drawn_zone(self) -> None:
        """RF-016-17, error 19: la superficie no baja en ninguna celda, lo que no sube es el plano bit a bit y el contrafuerte sube
        fuera de la zona dibujada, en las cuatro caras."""
        scene = self.scene
        zone_rows, zone_cols = np.nonzero(scene.zone)
        for _crown, _metric, outcome, _hand in self.each():
            self.assertFalse((outcome.surface < scene.start).any())
            stays = ~outcome.footprint
            self.assertEqual(outcome.surface[stays].tobytes(), scene.start[stays].tobytes())
            foot = outcome.footprint & ~scene.zone
            self.assertGreater(int(foot.sum()), 200)
            rows, cols = np.nonzero(foot)
            self.assertLess(int(rows.min()), int(zone_rows.min()))
            self.assertGreater(int(rows.max()), int(zone_rows.max()))
            self.assertLess(int(cols.min()), int(zone_cols.min()))
            self.assertGreater(int(cols.max()), int(zone_cols.max()))

    def test_the_berms_are_at_the_anchor_levels(self) -> None:
        """RF-013-24: a lo largo de las cuatro líneas que salen del centro de la zona, dos celdas seguidas a la misma cota (las
        bermas) están en ``125 + n·10`` m a ≤ 10⁻⁹ m; con tres bancos salen la coronación, 135 m y 125 m."""
        zone = self.scene.zone
        rows, cols = np.flatnonzero(zone.any(axis=1)), np.flatnonzero(zone.any(axis=0))
        row, col = int(rows[0] + rows[-1]) // 2, int(cols[0] + cols[-1]) // 2
        for crown, _metric, outcome, _hand in self.each():
            stepped = outcome.stepped
            lines = (stepped[row, col:], stepped[row, :col + 1][::-1], stepped[row:, col], stepped[:row + 1, col][::-1])
            plateaus: set[float] = set()
            for line in lines:
                for first, second in zip(line[:-1].tolist(), line[1:].tolist(), strict=True):
                    if abs(first - second) <= 1e-12:
                        index = (first - 125.0) / 10.0
                        self.assertLessEqual(abs(index - round(index)) * 10.0, 1e-9, f"{first} no es de un ancla")
                        plateaus.add(round(first, 6))
            wanted = {crown, PLANE_M} | ({135.0, 125.0} if crown == 145.0 else set())
            self.assertTrue(wanted <= plateaus, f"las bermas son {sorted(plateaus)}")

    def test_a_crown_off_the_anchor_is_refused_with_the_nearest_anchor(self) -> None:
        """RF-016-18, D-21, CE-016-10: una coronación que no es del ancla (``crown_m − z₀`` no es múltiplo de ``h``) se rechaza
        con la cota del ancla más próxima —127 m, 125; 131 m, 135; 130 m, a igual distancia, la menor, 125— nombrando la capa, el
        contrafuerte y la cota, **al pedir los pasos** y sin elegir ninguna cota por la persona."""
        for crown, anchor in ((127.0, 125.0), (131.0, 135.0), (130.0, 125.0), (124.9, 125.0), (136.0, 135.0)):
            with self.subTest(crown=crown), self.assertRaises(DesignError) as caught:
                buttress.buttress_steps(bdata.job_of(self.scene, crown))
            error = caught.exception
            self.assertEqual(error.code, "des.buttress_crown_off_anchor")
            self.assertEqual(error.field, "des.buttress.btr_001.crown_m")
            self.assertEqual(error.value, crown)
            self.assertEqual(error.values["anchor"], anchor)
            self.assertEqual(error.values["profile"], "EXPL_10_60_6")
            self.assertIn("«Zonas de coronación»", error.text)
            self.assertIn("«Contrafuerte de prueba»", error.text)
            self.assertIn(f"{anchor:g}".replace(".", ","), error.text.replace(" ", ""))

    def test_an_anchor_level_is_never_refused_and_below_the_plane_there_is_no_buttress(self) -> None:
        """RF-016-18: cualquier ``125 + n·10`` pasa la comprobación del ancla; una coronación por debajo del plano en toda la
        zona (105 m) es del ancla pero no hay contrafuerte (``des.buttress_crown_below_support``), y a la cota del plano
        (115 m), tampoco (``des.buttress_crown_at_support`` desde la T48: la coronación no queda por debajo, queda igual)."""
        for crown in (115.0, 125.0, 135.0, 145.0, 105.0, 95.0, -5.0):
            with self.subTest(crown=crown):
                steps = buttress.buttress_steps(bdata.job_of(self.scene, crown))
                if crown <= PLANE_M:
                    with self.assertRaises(DesignError) as caught:
                        next(steps)
                    self.assertEqual(caught.exception.code, "des.buttress_crown_below_support" if crown < PLANE_M
                                     else "des.buttress_crown_at_support")
                    self.assertEqual(caught.exception.value, crown)
                else:
                    steps.close()
        self.assertTrue(math.isfinite(PLANE_M))


if __name__ == "__main__":
    unittest.main()

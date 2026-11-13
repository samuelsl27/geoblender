# SPDX-License-Identifier: GPL-3.0-or-later
"""El resumen de la vista previa de la cantera con dos superficies (spec 014, T12; HU-014-1;
RF-014-04; plan 014 §5.1 y §5.5).

``design.preview.quarry_summarize_steps`` prepara, por pasos y solo leyendo, lo que la vista previa de
la 013 enseña además con un diseño de la 014: el recinto excavable, la coronación, las zonas a
sostener, los fondos, las zonas a conservar que siembran los techos y los corredores, con lo que
dibuja la vista (las rejillas) y lo que dice (notas con código, en español y en inglés). Las
pruebas de la vista previa de la 013 están en ``test_seeds.py`` (``summarize_steps``).

Sobre la cantera sintética de ``tests.support.quarry_fixtures`` (T01), con las cifras a mano:
recinto :data:`~tests.support.quarry_fixtures.CUT_ALLOWED_CELLS` celdas de 1 m², anillo de
coronación de 3 celdas = 4.176 celdas (3.576 fuera de las zonas a sostener, T07), zonas a
sostener = la torre (224) + «sin corte» (1.600), fondos de 6.400 y 4.800 celdas a 125 y 175 m, zona a conservar de 40 × 60 m = 2.400 celdas.

Un corredor es un fondo (T42, hallazgo F-3 de la T38): su cota pasa por el rango de los fondos
(RF-014-06) y lo que queda por encima del terreno se avisa con los fondos (RF-014-05).
"""

from __future__ import annotations

import unittest
from dataclasses import replace
from typing import Any, ClassVar

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender

preview = import_geoblender("design.preview")
quarry = import_geoblender("design.quarry")
model = import_geoblender("design.model")
messages = import_geoblender("design.messages")
access = import_geoblender("gis.masks.access")
i18n = import_geoblender("core.i18n")

RING_CELLS = 3
OUTER_RING_CELLS = 3_576
"""La coronación fuera de las zonas a sostener: el anillo exterior de 3 celdas (a mano en T07)."""
CROWN_CELLS = 4_176
"""La coronación entera: el anillo exterior y el de 3 celdas dentro de los dos agujeros, que caen en
las zonas a sostener: «sin corte», 40² − 34² = 444, y la torre, 156."""
HOLD_CELLS = qfx.TOWER_ZONE_CELLS + qfx.NO_CUT_CELLS
"""Las zonas a sostener: la torre con su resguardo y «sin corte» (1.824 celdas)."""
CONSERVE_CELLS = 2_400
"""La zona a conservar: 40 × 60 m de celdas de 1 m."""
CORRIDOR = model.CorridorFields(qfx.CORRIDORS_LAYER, "ancho", start_level_field="cota_inicial",
                                gradient_field="pendiente")
QUARRY_NOTES = ("des.quarry_preview_area", "des.quarry_preview_crown", "des.quarry_preview_hold",
                "des.quarry_preview_floors", "des.quarry_preview_ceilings",
                "des.quarry_preview_corridors")
HIGH_CORRIDORS = "gis_fea_corredores_altos"
"""Una capa con un corredor por encima del terreno (T42)."""
IMPOSSIBLE_CORRIDORS = "gis_fea_corredores_imposibles"
"""Una capa con un corredor a 10⁶ m, fuera de las cotas del terreno ± 1.000 m (T42)."""


def lane_layer(name: str, level_m: float) -> Any:
    """Una capa de corredores ``name`` con uno de 80 m de eje hacia el este (local, de (220, 101)
    a (300, 101): lejos de los fondos) y 10 m de ancho, a la cota ``level_m`` (cota inicial y
    pendiente 0 %)."""
    axis = ((220.0, 101.0), (300.0, 101.0))
    return qfx.LayerData(name, "line", (((cfx.absolute(axis),),),), ("Corredor",),
                         {"ancho": (10.0,), "cota_inicial": (level_m,), "pendiente": (0.0,)})


def grouped(number: int) -> str:
    """Un entero como lo escribe el español de Geoblender: espacio fino de miles."""
    return f"{number:,}".replace(",", i18n.THIN_SPACE)


def finish(steps: Any) -> tuple[list[Any], Any]:
    """Los ``Progress`` de unos pasos (menos el último) y el resultado del último."""
    found = list(steps)
    return found[:-1], found[-1].result


def side(profile: str) -> Any:
    return model.QuarrySide(base_profile=profile)


def request(**changes: Any) -> Any:
    """La cantera de E1 y E2: los dos lados con «coronación y zonas a sostener», los fondos, la zona
    a conservar y el corredor de la cantera sintética."""
    values: dict[str, Any] = {
        "name": "Cantera V01", "start": qfx.START_DATASET, "final": side("rest_5_35_6"),
        "exploitation": side("expl_10_60_6"),
        "floors": model.LayerField(qfx.FLOORS_LAYER, "cota"),
        "conserve": (model.Zone("layer", qfx.CONSERVE_LAYER),), "corridors": CORRIDOR}
    values.update(changes)
    return model.QuarryRequest(**values)


class QuarryPreviewTest(qfx.QuarryProjectCase):
    summary: ClassVar[Any]
    progress: ClassVar[list[Any]]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.progress, cls.summary = finish(preview.quarry_summarize_steps(
            cls.project, request(), cls.v1.uid, ring_cells=RING_CELLS, budget_s=0.0))

    def summarize(self, version: Any = None, **changes: Any) -> Any:
        target = self.v1 if version is None else version
        return finish(preview.quarry_summarize_steps(self.project, request(**changes), target.uid,
                                                     ring_cells=RING_CELLS))[1]

    def snapshot(self) -> tuple[Any, ...]:
        """Lo que escribiría un cálculo: filas de operaciones, datos y cifras, y los ficheros."""
        counts = tuple(self.query(f"SELECT COUNT(*) FROM {table}")[0][0]
                       for table in ("gb_operation", "gb_dataset", "gb_operation_io",
                                     "gb_figure"))
        files = tuple(sorted((path.relative_to(self.root).as_posix(), path.stat().st_size)
                             for path in self.root.rglob("*") if path.is_file()))
        return counts, files

    def test_the_summary_carries_each_piece_with_its_cells(self) -> None:
        """RF-014-04: el resumen lleva el recinto (A1), la coronación (A2, anillo de 3 celdas), las
        zonas a sostener (intocables y sin corte), los fondos (A4), las zonas a conservar que
        siembran los techos (A5) y los corredores (A6), cada uno en la rejilla de las máscaras y
        con las celdas contadas a mano; son los mismos que dan las funciones de ``design.quarry``."""
        summary = self.summary
        masks = self.masks()
        start = qfx.terrain()
        self.assertIs(summary.masks_state, access.MaskState.CURRENT)
        self.assertEqual(summary.version, "V01")
        np.testing.assert_array_equal(summary.start, start)
        area = quarry.excavation_area(masks, start)
        np.testing.assert_array_equal(summary.area, area)
        self.assertEqual(int(summary.area.sum()), qfx.CUT_ALLOWED_CELLS)
        np.testing.assert_array_equal(summary.crown, quarry.crown_ring(area, start, RING_CELLS))
        self.assertEqual(int(summary.crown.sum()), CROWN_CELLS)
        self.assertEqual(int((summary.crown & ~summary.hold).sum()), OUTER_RING_CELLS)
        np.testing.assert_array_equal(summary.hold, quarry.hold_zones(masks))
        self.assertEqual(int(summary.hold.sum()), HOLD_CELLS)
        self.assertEqual(summary.floors.cells, (6_400, 4_800))
        self.assertEqual(summary.floors.levels, (125.0, 175.0))
        ((name, mask),) = ((zone.name, zone.mask) for zone in summary.conserve)
        self.assertEqual(name, qfx.CONSERVE_LAYER)
        np.testing.assert_array_equal(mask, qfx.in_box(qfx.CONSERVE_LOCAL))
        self.assertEqual(int(mask.sum()), CONSERVE_CELLS)
        corridors = quarry.corridor_cells(self.read_layer(qfx.CORRIDORS_LAYER), CORRIDOR,
                                          qfx.GRID)
        self.assertEqual(summary.corridors.floors.cells, corridors.floors.cells)
        np.testing.assert_array_equal(summary.corridors.floors.grid, corridors.floors.grid)
        self.assertEqual(summary.corridors.axes_m, (qfx.CORRIDOR_LENGTH_M,))

    def test_the_summary_says_each_piece_in_both_languages(self) -> None:
        """RF-014-04, principio 10: lo que dice el resumen, en orden —las máscaras al día y, después,
        recinto, coronación, zonas a sostener, fondos, techos y corredores—, como notas con su
        código; en español con espacio fino de miles y coma decimal, y en inglés; con un solo
        corredor, en singular («1 línea»; T60), y con dos fondos, en plural."""
        codes = [notice.code for notice in self.summary.notices]
        self.assertEqual(codes, ["des.preview_masks_current", *QUARRY_NOTES])
        self.assertEqual(self.summary.warnings("es"), ())
        lines = self.summary.lines("es")
        cells = grouped(qfx.CUT_ALLOWED_CELLS)
        self.assertEqual(lines[1], f"Recinto excavable: {cells} celdas ({cells} m², 8,5 ha).")
        self.assertIn(f"{grouped(CROWN_CELLS)} celdas", lines[2])
        self.assertIn("3 celdas", lines[2])
        self.assertIn(f"{grouped(HOLD_CELLS)} celdas", lines[3])
        self.assertIn("«gis_fea_fondos»", lines[4])
        self.assertIn("2 polígonos", lines[4])
        self.assertIn(f"{grouped(11_200)} celdas", lines[4])
        self.assertIn("cotas 125,0 a 175,0 m", lines[4])
        self.assertIn(f"{grouped(CONSERVE_CELLS)} celdas", lines[5])
        self.assertIn("gis_fea_conservar", lines[5])
        corridor_cells = sum(self.summary.corridors.floors.cells)
        self.assertEqual(lines[6], f"Corredores de «{qfx.CORRIDORS_LAYER}»: 1 línea, "
                                   f"{grouped(corridor_cells)} celdas ({grouped(corridor_cells)} "
                                   "m²), 200,0 m de eje.")
        english = self.summary.lines("en")
        self.assertEqual(english[1], f"Excavation area: {qfx.CUT_ALLOWED_CELLS:,} cells "
                                     f"({qfx.CUT_ALLOWED_CELLS:,} m², 8.5 ha).")
        self.assertIn("2 polygons", english[4])
        self.assertEqual(english[6], f"Corridors of «{qfx.CORRIDORS_LAYER}»: 1 line, "
                                     f"{corridor_cells:,} cells ({corridor_cells:,} m²), 200.0 m "
                                     "of axis.")
        for line in (*lines, *english):
            self.assertNotIn("{", line)

    def test_the_pieces_that_are_not_asked_are_not_shown(self) -> None:
        """RF-014-04: sin fondos, sin zonas a conservar y sin corredores, el resumen dice el recinto,
        la coronación y las zonas a sostener, y nada de lo que no se pidió."""
        summary = self.summarize(floors=None, conserve=(), corridors=None)
        self.assertIsNone(summary.floors)
        self.assertEqual(summary.conserve, ())
        self.assertIsNone(summary.corridors)
        self.assertEqual([notice.code for notice in summary.notices],
                         ["des.preview_masks_current", *QUARRY_NOTES[:3]])

    def test_masks_not_compiled_are_said_and_nothing_is_written(self) -> None:
        """RF-014-04, RF-013-03: con las máscaras de V02 sin compilar el resumen lo dice y no tiene
        recinto ni nada más; no compila nada ni escribe en el proyecto."""
        before = self.snapshot()
        summary = self.summarize(version=self.v2)
        self.assertIs(summary.masks_state, access.MaskState.MISSING)
        self.assertIsNone(summary.masks)
        self.assertIsNone(summary.area)
        self.assertIsNone(summary.floors)
        self.assertEqual([notice.code for notice in summary.notices],
                         ["des.preview_masks_missing"])
        self.assertEqual(self.snapshot(), before)

    def test_the_preview_writes_nothing_and_rejects_while_advancing(self) -> None:
        """RF-014-04: la vista previa no escribe en el proyecto —ni operaciones, ni datos, ni
        cifras, ni ficheros—, ni cuando todo va bien ni cuando rechaza un campo de cota que la capa
        no tiene (al avanzar, con el error de ``floor_map``)."""
        before = self.snapshot()
        self.summarize()
        with self.assertRaises(messages.DesignError) as caught:
            self.summarize(floors=model.LayerField(qfx.FLOORS_LAYER, "no_existe"))
        self.assertEqual(caught.exception.code, "des.quarry_layer_field")
        self.assertEqual(self.snapshot(), before)

    def test_a_corridor_is_a_floor_for_the_range_and_above_the_terrain(self) -> None:
        """RF-014-04, RF-014-05, RF-014-06, RF-014-09 (T42, hallazgo F-3): con un corredor de 80
        × 10 m a 290 m, por encima del terreno, la vista previa avisa de los fondos sobre el
        terreno con su área (800 celdas de 1 m², a mano; los fondos de la cantera quedan por debajo
        de él), como lo dirá el cálculo; con uno a 10⁶ m, rechaza al avanzar con
        ``des.corridor_level`` (la capa, el corredor, el campo y el valor; T51) y no escribe
        nada."""
        for name, level in ((HIGH_CORRIDORS, 290.0), (IMPOSSIBLE_CORRIDORS, 1.0e6)):
            qfx.write_feature_layer(self.project, self.clock, lane_layer(name, level))
        before = self.snapshot()
        summary = self.summarize(corridors=replace(CORRIDOR, layer=HIGH_CORRIDORS))
        above = [notice for notice in summary.notices if notice.code == "des.floor_above_terrain"]
        self.assertEqual([notice.values for notice in above], [{"area": 800.0}])
        self.assertEqual(summary.warnings("es"),
                         ("800 m² de los fondos quedan por encima del terreno: allí no hay corte "
                          "(la superficie nunca supera el terreno).",))
        with self.assertRaises(messages.DesignError) as caught:
            self.summarize(corridors=replace(CORRIDOR, layer=IMPOSSIBLE_CORRIDORS))
        error = caught.exception
        self.assertEqual(error.code, "des.corridor_level")
        self.assertEqual((error.values["layer"], error.values["corridor"], error.values["field"],
                          error.values["value"]),
                         (IMPOSSIBLE_CORRIDORS, 1, "cota_inicial", 1.0e6))
        self.assertEqual(self.snapshot(), before)

    def test_it_goes_by_steps_and_ends_with_the_summary(self) -> None:
        """RF-014-04 (D-20 de la 013): el resumen se prepara por pasos y el último lo lleva."""
        self.assertGreaterEqual(len(self.progress), 4)
        self.assertIsInstance(self.summary, preview.QuarryPreview)
        self.assertTrue(all(item.phase == "preview" for item in self.progress))


THIN = i18n.THIN_SPACE


class NoticeCountTest(unittest.TestCase):
    """RF-014-03, RF-014-04, RF-014-17, RF-014-18, RF-014-21 (T60; el punto 1 de la T57, la sonda
    E4): ``Notice.text`` escribe los números para una persona (espacio fino de miles y coma decimal
    en español) y elige el singular de un mensaje que cuenta algo con el número **sin escribir**: en
    el resumen, «en 1 zona», no «en 1 zonas» (antes lo elegía con el número ya escrito, «1», y salía
    siempre el plural); con 2, el plural; en los dos idiomas."""

    CASES: ClassVar[tuple[tuple[str, str, dict[str, object], str, str, str, str], ...]] = (
        ("des.quarry_to_final", "zones", {"area": 2.6, "volume": 14_902.4},
         f"«Explotación hasta la final» en 1 zona (2,6 ha): 14{THIN}902,4 m³ pasan del "
         "desdoblado a la explotación, con bancos anclados a sus cotas.",
         "«Exploitation down to the final» in 1 zone (2.6 ha): 14,902.4 m³ pass",
         "«Explotación hasta la final» en 2 zonas (2,6 ha)",
         "«Exploitation down to the final» in 2 zones (2.6 ha)"),
        ("des.quarry_unsplit_zones", "zones",
         {"area": 0.6, "volume": 14_902.4, "threshold": 1.0, "min_area": 0.2},
         "La explotación no llega a la final en 1 zona: 0,6 ha", "in 1 zone: 0.6 ha",
         "en 2 zonas: 0,6 ha", "in 2 zones: 0.6 ha"),
        ("des.quarry_seeds_outside", "groups", {"cells": 5_747, "area": 5_747.0},
         f"5{THIN}747 celdas de semillas (5{THIN}747 m²) en 1 grupo caen fuera",
         "5,747 seed cells (5,747 m²) in 1 group fall outside",
         f"5{THIN}747 celdas de semillas (5{THIN}747 m²) en 2 grupos caen fuera",
         "in 2 groups fall outside"),
        ("des.edge_created_step", "stretches",
         {"share": 60.77, "pairs": 520, "threshold": 1.0, "admitted": 99.0, "maximum": 4.0,
          "x": "500 010,00", "y": "4 400 010,00"},
         "en 1 tramo. Use «Transiciones", "in 1 stretch. Use «Transitions",
         "en 2 tramos. Use «Transiciones", "in 2 stretches. Use «Transitions"),
        ("des.refit_order", "cells", {"quarry": "Corta", "surface": "des_exp_corta"},
         "«des_exp_corta» cambia en 1 celda para", "«des_exp_corta» changes in 1 cell so",
         "«des_exp_corta» cambia en 2 celdas para", "«des_exp_corta» changes in 2 cells so"),
        ("des.quarry_preview_crown", "ring", {"cells": 4_176, "area": 4_176.0},
         f"Coronación: anillo de 1 celda fuera del recinto, 4{THIN}176 celdas",
         "Crown: ring of 1 cell outside the excavation area, 4,176 cells",
         "anillo de 2 celdas fuera", "ring of 2 cells outside"),
    )

    def test_a_count_of_one_takes_its_singular_in_the_summary(self) -> None:
        """Cada aviso o nota con un 1 en su recuento, en singular en español y en inglés, y los
        demás números escritos como siempre; con un 2, el plural."""
        for code, count, values, one_es, one_en, many_es, many_en in self.CASES:
            with self.subTest(code=code):
                one = preview.Notice(code, {**values, count: 1})
                many = preview.Notice(code, {**values, count: 2})
                self.assertIn(one_es, one.text("es"))
                self.assertIn(one_en, one.text("en"))
                self.assertIn(many_es, many.text())
                self.assertIn(many_en, many.text("en"))
                for text in (one.text("es"), one.text("en"), many.text("es")):
                    self.assertNotIn("{", text)


class QuarryPreviewMessagesTest(unittest.TestCase):
    def test_the_notes_have_both_languages_and_every_value_filled(self) -> None:
        """Principio 10: los códigos del resumen de la cantera son notas de la familia
        ``des.quarry_``, con su texto en español y en inglés, sin marcadores al rellenarlos."""
        for code in QUARRY_NOTES:
            message = messages.MESSAGES[code]
            values = {name: "V" for name in i18n.placeholders(message.es)}
            with self.subTest(code=code):
                self.assertEqual(message.severity, "note")
                for language in ("es", "en"):
                    self.assertNotIn("{", messages.render(code, language=language, **values))


if __name__ == "__main__":
    unittest.main()

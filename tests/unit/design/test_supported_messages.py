# SPDX-License-Identifier: GPL-3.0-or-later
"""Los mensajes de los cuatro tipos de entidad de la 016 (spec 016, T03; RF-016-04 a 07, 12 a 15, 18, 19 y 20 a 22;
plan 016 §5.1 y §5.5; principio 10).

Un código ``des.stockpile_*``, ``des.removal_*``, ``des.buttress_*`` o ``des.body_*`` por cada rechazo y aviso de la
spec, con su ``msgid`` en inglés y su texto en español, con los mismos marcadores con nombre en los dos; lo que dice
la spec que nombran (la marca, el caso y su lugar; las dos marcas; el acopio, su altura y su inclinación; la cota
del ancla más próxima…) está en el texto. No empiezan por ninguna de las familias cerradas de la 015
(``des.entity_``, ``des.platform_``, ``des.support_`` y ``des.event_``): ``test_entities_model`` fija la suya.
"""

from __future__ import annotations

import unittest

from tests.support.package import import_geoblender

messages = import_geoblender("design.messages")
i18n = import_geoblender("core.i18n")

SPANISH_LETTERS = frozenset("áéíóúüñÁÉÍÓÚÜÑ¿¡")
CLOSED_FAMILIES_015 = ("des.entity_", "des.platform_", "des.support_", "des.event_")
POSITION = {"x", "y"}

# Código → (gravedad, RF, marcadores que el texto tiene que llevar).
CODES: dict[str, tuple[str, str, set[str]]] = {
    # RF-016-04: el acopio que se rechaza, con su marca, el caso y su lugar; las dos marcas que se solapan.
    "des.stockpile_no_cells": ("warning", "RF-016-04", {"mark", "threshold", *POSITION}),
    "des.stockpile_no_terrain": ("warning", "RF-016-04", {"mark", "cells", *POSITION}),
    "des.stockpile_no_terrain_crown": ("warning", "RF-016-04", {"mark", "cells", *POSITION}),
    "des.stockpile_no_crown_cells": ("warning", "RF-016-04", {"mark", "inner", "outer", *POSITION}),
    "des.stockpile_marks_overlap": ("error", "RF-016-04", {"mark", "other", "area", *POSITION}),
    # T11: lo que rechaza la preparación antes de calcular (la capa de marcas, sus campos y polígonos, los nombres).
    "des.stockpile_layer_field": ("error", "RF-015-08", {"layer", "field", "value", "fields"}),
    "des.stockpile_mark_repeated": ("error", "RF-016-02", {"layer", "value", "fids"}),
    "des.stockpile_mark_geometry": ("error", "RF-016-04", {"layer", "entity", "value"}),
    "des.stockpile_mark_no_cells": ("error", "RF-016-04", {"layer", "entity"}),
    "des.stockpile_no_marks": ("error", "RF-016-02", {"layer"}),
    "des.stockpile_name_repeated_project": ("error", "RF-015-01", {"value", "other"}),
    # RF-016-05: lo que se avisa y se anota en el acopio.
    "des.stockpile_footprint_at_edge": ("warning", "RF-016-05", {"mark", *POSITION}),
    "des.stockpile_several_zones": ("warning", "RF-016-05", {"mark", "zones", *POSITION}),
    "des.stockpile_crown_few_flat": ("warning", "RF-016-05", {"mark", "area", "slope", "minimum", *POSITION}),
    "des.stockpile_not_converged": ("warning", "RF-016-05", {"mark", "turns", *POSITION}),
    # RF-016-06 y 07.
    "des.stockpile_shared_cells": ("warning", "RF-016-06", {"mark", "other", "area", *POSITION}),
    "des.stockpile_tilt_limited": ("warning", "RF-016-07", {"mark", "fitted", "limit", "quantile", *POSITION}),
    "des.stockpile_declared_reason": ("note", "RF-015-10", {"name"}),
    "des.stockpile_support_removed": ("note", "RF-015-17", {"name"}),
    # RF-016-12 a 15: la retirada.
    "des.removal_detection_stale": ("error", "RF-016-12", {"stockpile", "detection", "cause"}),
    "des.removal_nothing": ("warning", "RF-016-13", {"stockpile"}),
    "des.removal_resting": ("warning", "RF-016-14", {"stockpile", "volume", "items"}),
    "des.removal_resting_unconfirmed": ("error", "RF-016-14", {"stockpile", "volume"}),
    "des.removal_wall": ("warning", "RF-016-15",
                         {"stockpile", "height", "angle", "limit", "step", *POSITION}),
    "des.removal_wall_unconfirmed": ("error", "RF-016-15", {"stockpile", "height", "angle"}),
    "des.removal_wall_reason": ("error", "RF-016-15",
                                {"stockpile", "height", "angle", "min_angle", "min_height"}),
    "des.removal_declared_reason": ("note", "RF-015-10", {"name"}),
    "des.removal_support_removed": ("note", "RF-015-17", {"name"}),
    # RF-016-18 y 19: el contrafuerte.
    "des.buttress_crown_off_anchor": ("error", "RF-016-18", {"layer", "entity", "profile", "anchor"}),
    "des.buttress_crown_below_support": ("error", "RF-016-18", {"layer", "entity"}),
    "des.buttress_foot_cut": ("warning", "RF-016-19", {"entity", "area", "volume", "step", *POSITION}),
    "des.buttress_declared_reason": ("note", "RF-015-10", {"name"}),
    "des.buttress_support_removed": ("note", "RF-015-17", {"name"}),
    # RF-016-20 a 22: el cuerpo apoyado.
    "des.body_data_outside": ("warning", "RF-016-20", {"entity", "ignored"}),
    "des.body_far": ("warning", "RF-016-21", {"entity", "area", "volume", "distance", *POSITION}),
    "des.body_no_data": ("error", "RF-016-22", {"layer", "footprint", "entity"}),
    "des.body_all_far": ("error", "RF-016-22", {"entity", "distance", "footprint"}),
    "des.body_declared_reason": ("note", "RF-015-10", {"name"}),
    "des.body_support_removed": ("note", "RF-015-17", {"name"}),
}
"""Los códigos de la T03 con su gravedad, su RF y lo que su texto nombra."""
PREFIXES = ("des.stockpile_", "des.removal_", "des.buttress_", "des.body_")


class SupportedMessagesTest(unittest.TestCase):
    def test_the_codes_of_the_task(self) -> None:
        """RF-016-04 a 07, 12 a 15, 18 a 22 (plan 016 §5.1): cada rechazo y aviso de la spec tiene su código de una
        de las cuatro familias nuevas, con su gravedad; los de ``des.stockpile_*``, ``des.removal_*``,
        ``des.buttress_*`` y ``des.body_*`` del catálogo son exactamente estos, y ninguno es de las familias
        cerradas de la 015; ni un código ni un ``msgid`` se repite."""
        for code, (severity, _rf, _marks) in CODES.items():
            with self.subTest(code=code):
                self.assertIn(code, messages.MESSAGES)
                self.assertEqual(messages.MESSAGES[code].severity, severity)
                self.assertTrue(code.startswith(PREFIXES), code)
                self.assertFalse(code.startswith(CLOSED_FAMILIES_015), code)
                self.assertRegex(code, r"^des\.[a-z][a-z0-9_]*$")
        found = [m.code for m in messages.CATALOG if m.code.startswith(PREFIXES)]
        self.assertEqual(sorted(found), sorted(CODES))
        self.assertEqual(len({m.msgid for m in messages.CATALOG}), len(messages.CATALOG))

    def test_both_languages_with_the_same_placeholders(self) -> None:
        """Principio 10: cada código tiene su ``msgid`` en inglés (sin letras del español) y su texto en español,
        distintos, con los mismos marcadores con nombre; el texto nombra lo que dice la spec (la marca, el caso y
        su lugar, las dos marcas, la altura y la inclinación de la pared, la cota del ancla…); ``CATALOG_ES`` los
        da para ``core.i18n.install``."""
        for code, (_severity, _rf, marks) in CODES.items():
            message = messages.MESSAGES[code]
            with self.subTest(code=code):
                self.assertEqual(set(message.msgid) & SPANISH_LETTERS, set())
                self.assertNotEqual(message.msgid, message.es)
                self.assertEqual(i18n.placeholders(message.msgid), i18n.placeholders(message.es))
                self.assertLessEqual(marks, set(i18n.placeholders(message.es)))
                self.assertEqual(messages.CATALOG_ES[message.msgid], message.es)

    def test_a_rejection_names_the_entity_the_field_and_the_value(self) -> None:
        """RF-016-04, 12, 14, 15, 18, 22: cada error se lanza como ``DesignError`` con su objeto, su campo y su
        valor, en español y en inglés, y su texto no deja ningún marcador sin llenar; un aviso o una nota no se
        lanza (``ValueError``)."""
        values = {"mark": "Acopio 2", "other": "Acopio 3", "area": 12.5, "x": 725010.5, "y": 4400020.5,
                  "stockpile": "STK-001#m07", "detection": "Detección 1", "cause": "cambió «margin_m»",
                  "volume": 640.25, "items": "«Relleno V09»", "height": 12.0, "angle": 52.0,
                  "min_angle": 45.0, "min_height": 3.0, "layer": "gis_fea_zonas", "entity": "BTR-001",
                  "profile": "EXPL_10_60_6", "anchor": 250.0, "footprint": "Cuerpo 1", "distance": 30.0,
                  "fids": "3, 7", "fields": "nombre, margen"}
        for code, (severity, _rf, _marks) in CODES.items():
            with self.subTest(code=code):
                if severity == "error":
                    error = messages.DesignError(code, obj="Entidad", field="campo", value=1.5, **values)
                    self.assertNotIn("{", error.text)
                    self.assertNotIn("?", error.text)
                    self.assertNotIn("{", error.text_in("en"))
                    self.assertEqual(error.code, code)
                else:
                    with self.assertRaises(ValueError):
                        messages.DesignError(code, obj="Entidad", field="campo")
        self.assertEqual(messages.render("des.stockpile_declared_reason", name="Patio"),
                         "declarada por la detección de acopios Patio")
        self.assertEqual(messages.render("des.stockpile_declared_reason", name="Patio", language="en"),
                         "declared by stockpile detection Patio")

    def test_a_rejected_stockpile_is_not_registered_and_says_where(self) -> None:
        """RF-016-04, RF-016-05 (D-3): los rechazos y los avisos de un acopio nombran **su marca** y su lugar
        (``x`` e ``y`` absolutas), y los rechazos dicen que no se registra; el aviso de la inclinación limitada
        dice la ajustada y la limitada y que el acopio lleva la nota (RF-016-07)."""
        for code in ("des.stockpile_no_cells", "des.stockpile_no_terrain", "des.stockpile_no_terrain_crown",
                     "des.stockpile_no_crown_cells"):
            with self.subTest(code=code):
                text = messages.render(code, mark="Acopio 2", threshold=0.3, cells=4, x=1.0, y=2.0, inner=1.0,
                                       outer=3.0)
                self.assertIn("«Acopio 2»", text)
                self.assertIn("no se registra", text)
                self.assertIn("x = 1 m", text)
        text = messages.render("des.stockpile_tilt_limited", mark="Acopio 7", fitted=8.0, limit=4.0, quantile=0.6,
                               x=1.0, y=2.0)
        self.assertIn("«Acopio 7»", text)
        self.assertIn("8", text)
        self.assertIn("4", text)

    def test_the_wall_thresholds_are_not_written_in_the_text(self) -> None:
        """Principio 2, RF-016-15 (CA-9): los 45° y los 3 m de una pared que pide un motivo no están escritos en el
        texto: llegan como valores (``min_angle`` y ``min_height``), que salen de donde diga la tarea de la pared."""
        message = messages.MESSAGES["des.removal_wall_reason"]
        for text in (message.es, message.msgid):
            self.assertNotIn("45", text)
            self.assertNotIn("3 m", text)


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo puro de recalcular y traer la corta (spec 018, T24; RF-018-01, RF-018-06 a 09; RF-015-01, RF-015-02): la petición que repite una operación sale de sus ajustes y de los parámetros de su
entidad (con los valores por sector), **sin proyecto**. El recálculo, «Cambiar parámetro…» y traer sobre el proyecto son de ``milestone_pit_recompute``.
"""

from __future__ import annotations

import dataclasses
import unittest
from typing import Any

from tests.support.package import import_geoblender
from tests.unit.design.test_pit_prepare import CODE, request

pit_model = import_geoblender("design.pit_model")
pit_store = import_geoblender("design.pit_store")
provenance = import_geoblender("design.provenance")
road_model = import_geoblender("design.road_model")


def again(asked: Any) -> Any:
    """La petición que sale de los ajustes y de los valores de ``asked`` (lo que hace un recálculo con lo que anotó «Crear»)."""
    values = pit_store.pit_values(asked, CODE, start_ref=asked.start)
    for segment, profile in asked.sector_profiles:
        values[f"profile.{segment}"] = profile
    for segment, rose in asked.sector_roses:
        values[f"rose.{segment}"] = rose
    for segment, number in asked.sector_n_berm:
        values[f"n_berm.{segment}"] = number
    return provenance.pit_request(provenance.pit_settings(asked, CODE), values)


class PitRequestTest(unittest.TestCase):
    """RF-018-01, RF-015-02: ``pit_request`` es la inversa de ``pit_settings`` junto con ``pit_values``."""

    def test_an_ascending_pit_comes_back_the_same(self) -> None:
        asked = request(top_level_m=175.0)
        self.assertEqual(again(asked), dataclasses.replace(asked, n_berm=1, corner="round"))

    def test_a_descending_pit_with_layers_ramps_and_sectors(self) -> None:
        asked = request(mode="down", level_field=None, bottom_level_m=50.0, max_benches=3, min_floor_width_m=30.0, close_radius_m=1.0, az_window_m=5.0,
                        support="gis_dtm_apoyo", rose="rosa", ramps=("espiral", "zigzag"),
                        fixed=road_model.LayerFields("gis_brk_f", "nombre"), fixed_field="banco", noramp=road_model.LayerFields("gis_fea_z", "nombre"),
                        sector_profiles={"talud_norte": "rest_5_35_6", "perimeter__": "expl_10_60_6"}, sector_roses={"talud_norte": "rosa"},
                        sector_n_berm={"talud_norte": 1})
        found = again(asked)
        self.assertEqual(found, dataclasses.replace(asked, n_berm=1, corner="round"))
        self.assertEqual(found.sector_profiles, (("perimeter__", "expl_10_60_6"), ("talud_norte", "rest_5_35_6")))

    def test_what_is_not_a_pit_is_refused(self) -> None:
        settings = provenance.pit_settings(request(), CODE)
        values = pit_store.pit_values(request(), CODE, start_ref="gis_dtm_x")
        for bad in ({**values, "protect": True}, {**values, "otro.sector": "x"}, {**values, "profile.a": 3}):
            with self.subTest(bad=sorted(set(bad) - set(values))), self.assertRaises(ValueError):
                provenance.pit_request(settings, bad)
        with self.assertRaises(ValueError):
            provenance.pit_request(settings, {key: value for key, value in values.items() if key != "layer"})

    def test_the_name_fields_of_the_layers_are_in_the_settings_only_when_there_is_a_layer(self) -> None:
        self.assertEqual(provenance.pit_settings(request(), CODE)["fields"], {"name_field": "nombre", "level_field": "cota_m", "fixed_field": None})
        found = provenance.pit_settings(request(fixed=road_model.LayerFields("gis_brk_f", "nombre")), CODE)["fields"]
        self.assertEqual(found["fixed_name_field"], "nombre")
        self.assertNotIn("noramp_name_field", found)


if __name__ == "__main__":
    unittest.main()


class DeclaredSupportsTest(unittest.TestCase):
    """RF-015-15, RF-015-17 (T25): lo que la persona declara en ``supports`` de una corta pasa por las reglas entre entidades al cambiarlo, como en la pista."""

    def test_the_declared_supports_of_a_pit_are_ruled_like_the_ones_of_a_road(self) -> None:
        entity_store = import_geoblender("design.entity_store")
        entities = import_geoblender("design.entities")
        self.assertTrue(entity_store._ruled("pit", "supports"))
        self.assertTrue(entity_store._is_declared_supports(entities.EntityKind.PIT, "supports"))
        self.assertFalse(entity_store._is_declared_supports(entities.EntityKind.PIT, "layer"))
        self.assertFalse(entity_store._is_declared_supports(entities.EntityKind.PLATFORM, "supports"))

# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo puro de preparar la corta (spec 018, T21; RF-018-01, 02, 04, 08, 13; RF-015-08; plan 018 §5.2.2 y §5.4 A0): los valores resueltos y sus rechazos,
el hash de la geometría de origen y lo que la operación lee y anota, **sin proyecto** (el «verde» no suma ni 10 ms). Preparar sobre el proyecto, con sus
capas y sus sectores, es de ``milestone_pit_prepare_checks``.
"""

from __future__ import annotations

import unittest
from typing import Any

import numpy as np

from tests.support import pit_data as pd
from tests.support.package import import_geoblender

messages = import_geoblender("design.messages")
params = import_geoblender("design.params")
pit_model = import_geoblender("design.pit_model")
pit_store = import_geoblender("design.pit_store")
provenance = import_geoblender("design.provenance")
road_model = import_geoblender("design.road_model")

DesignError = messages.DesignError
CODE = "PIT-001"


def request(**changes: Any) -> Any:
    base: dict[str, Any] = {"profile": "expl_10_60_6", "arc_tol_m": 0.05, "simplify_m": 0.05, "level_field": "cota_m"}
    mode = changes.pop("mode", "up")
    return pit_model.PitRequest("Corta", road_model.LayerFields("gis_fea_x", "nombre"), mode, "gis_dtm_x", **{**base, **changes})


class ValuesTest(unittest.TestCase):
    """RF-015-08, RF-018-04: los parámetros resueltos y comprobados, sin proyecto."""

    def test_the_defaults_and_what_is_asked(self) -> None:
        values = pit_store.pit_values(request(top_level_m=175.0), CODE, start_ref="gis_dtm_x")
        self.assertEqual((values["mode"], values["corner"], values["n_berm"], values["top_level_m"]), ("up", "round", 1, 175.0))
        self.assertEqual((values["arc_tol_m"], values["simplify_m"], values["start"]), (0.05, 0.05, "gis_dtm_x"))
        for key in ("bottom_level_m", "max_benches", "min_floor_width_m", "close_radius_m", "az_window_m", "support"):
            self.assertNotIn(key, values)

    def test_the_hypotheses_have_no_default(self) -> None:
        for field in ("arc_tol_m", "simplify_m"):
            with self.subTest(field=field), self.assertRaises(DesignError) as caught:
                pit_store.pit_values(request(**{field: None}), CODE, start_ref="gis_dtm_x")
            self.assertEqual(caught.exception.code, "des.entity_param_missing")

    def test_a_descending_pit_needs_a_stop_criterion(self) -> None:
        with self.assertRaises(DesignError) as caught:
            pit_store.pit_values(request(mode="down"), CODE, start_ref="gis_dtm_x")
        self.assertEqual(caught.exception.code, "des.pit_no_stop")
        for changes in ({"bottom_level_m": 50.0}, {"max_benches": 3}, {"min_floor_width_m": 30.0}):
            with self.subTest(changes=changes):
                self.assertIn("mode", pit_store.pit_values(request(mode="down", **changes), CODE, start_ref="gis_dtm_x"))

    def test_the_bottom_must_be_below_the_top(self) -> None:
        with self.assertRaises(DesignError) as caught:
            pit_store.pit_values(request(top_level_m=100.0, bottom_level_m=100.0), CODE, start_ref="gis_dtm_x")
        self.assertEqual(caught.exception.code, "des.entity_param_range")

    def test_the_pit_declares_nothing(self) -> None:
        values = pit_store.pit_values(request(), CODE, start_ref="gis_dtm_x")
        self.assertFalse(any(key in values for key in ("protect", "guard_m")))


class SourceHashTest(unittest.TestCase):
    """RF-018-01: el hash cambia con la geometría y la cota, y es el mismo para lo mismo."""

    def test_the_hash(self) -> None:
        ring = pd.circle_ring()
        found = pit_store.source_sha256(ring, 125.0)
        self.assertEqual(found, pit_store.source_sha256(ring.copy(), 125.0))
        self.assertNotEqual(found, pit_store.source_sha256(ring, 135.0))
        self.assertNotEqual(found, pit_store.source_sha256(ring + 1e-9, 125.0))
        self.assertNotEqual(pit_store.source_sha256(ring, None), found)
        self.assertEqual(len(found), 64)
        self.assertTrue(np.isfinite(ring).all())


class ProvenanceTest(unittest.TestCase):
    """RF-018-01, 03, 05: lo que lee y anota ``des.pit``."""

    def test_the_inputs(self) -> None:
        uses = provenance.pit_inputs("gis_fea_f", "gis_dtm_t", (), ("des_psf_a",), fixed="gis_fea_b", noramp="gis_fea_z")
        self.assertEqual([(use.item, use.role) for use in uses],
                         [("gis_fea_f", provenance.ENTITY_LAYER_ROLE), ("gis_fea_b", provenance.ENTITY_LAYER_ROLE),
                          ("gis_fea_z", provenance.ENTITY_LAYER_ROLE), ("gis_dtm_t", provenance.SURFACE_ROLE),
                          ("des_psf_a", provenance.SUPPORTED_ON_ROLE)])
        with self.assertRaises(TypeError):
            provenance.pit_inputs("gis_fea_f", "gis_dtm_t", (), "des_psf_a")

    def test_the_parameters(self) -> None:
        keys = provenance.pit_params(CODE, valued=("profile", "bottom_level_m"), profiles=("expl_10_60_6",),
                                     sectors=("des.pit.pit_001.n_berm.sector_1",))
        self.assertEqual(keys[0], "des.pit.pit_001.mode")
        for wanted in ("des.pit.pit_001.profile", "des.pit.pit_001.bottom_level_m", "des.pit.pit_001.arc_tol_m", "des.pit.pit_001.n_berm.sector_1",
                       "des.bench.expl_10_60_6.height_m"):
            self.assertIn(wanted, keys)
        self.assertNotIn("des.pit.pit_001.top_level_m", keys)
        self.assertNotIn("des.pit.pit_001.name", keys)
        self.assertEqual(len(keys), len(set(keys)))
        with self.assertRaises(ValueError):
            provenance.pit_params(CODE, valued=("name",))
        with self.assertRaises(ValueError):
            provenance.pit_params("PLT-001")

    def test_the_settings_hold_no_figure(self) -> None:
        found = provenance.pit_settings(request(), CODE)
        self.assertEqual(found, {"name": "Corta", "code": CODE, "fields": {"name_field": "nombre", "level_field": "cota_m", "fixed_field": None}})
        with self.assertRaises(TypeError):
            provenance.pit_settings("no", CODE)


if __name__ == "__main__":
    unittest.main()

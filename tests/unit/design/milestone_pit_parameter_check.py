# SPDX-License-Identifier: GPL-3.0-or-later
"""«Cambiar parámetro…» de los valores de la corta con las reglas de crear (spec 018, T41; hallazgo F-1 de la T39; RF-015-08, RF-018-04, RF-018-06, RF-018-07,
RF-018-08, RF-018-15), como prueba de **hito** (lo que monta un proyecto no entra en el «verde»).

Sobre el proyecto de las cortas de ``milestone_pit_prepare_checks`` (el perfil de pista ``PISTA_PRINCIPAL``, la roseta ``roseta_del_tajo`` de dos rangos, la espiral y el zig-zag, los
perfiles de banco ``EXPL_10_60_6`` y ``REST_5_35_6`` —de otra altura—) y una corta ``PIT-001`` escrita como parámetros de V01: antes de la T41 los valores de una roseta, de una rampa y por
sector se escribían con la sola comprobación de tipo y rango de su definición; ahora ``design.pit_param_check`` aplica lo que dicen crear y calcular, **sin escribir nada** (el contador de
cambios de la base no se mueve).
"""

from __future__ import annotations

import unittest
from typing import Any

from tests.support.package import import_geoblender
from tests.support.versions_fixtures import change_counter
from tests.unit.design.milestone_pit_prepare_checks import EXPL, FLAT, REST, PitPrepareCase
from tests.unit.design.test_pit_ramp_def import PD

core_params = import_geoblender("core.params")
design_params = import_geoblender("design.params")
messages = import_geoblender("design.messages")
pit_param_check = import_geoblender("design.pit_param_check")

PERSON = "Samuel (IMGA)"
CODE = "PIT-001"
ROSE = "roseta_del_tajo"
RAMP = "espiral"


class PitParameterCase(PitPrepareCase):
    """El proyecto de las cortas más ``PIT-001`` en V01 (nombre, capa, modo, partida, perfil base y un solo banco por berma)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        store = core_params.ParameterStore(cls.project)
        with cls.project.write_transaction() as conn:
            for param, value in {"name": "Corta de la prueba", "layer": "gis_fea_corta_fondos", "mode": "up", "start": FLAT, "profile": EXPL, "n_berm": 1}.items():
                store.create(conn, design_params.entity_key(CODE, param), value, kind="ADOPTADO", source="Prueba de la T41", source_kind="person", decided_by=PERSON,
                             reason="Prueba de la T41", version=cls.v1.code)
        cls.clock.advance(minutes=1)

    def refused(self, call: Any, expected: str, field: str, shown: object) -> Any:  # type: ignore[override]
        """``call`` se rechaza con ``expected`` nombrando el campo ``field`` y el valor ``shown``, y no escribe nada; el texto no deja ningún marcador en ningún idioma."""
        before = change_counter(self.root)
        with self.assertRaises(messages.DesignError) as caught:
            call()
        error = caught.exception
        self.assertEqual((error.code, error.values["field"], error.values["value"]), (expected, field, shown))
        for text in (error.text, error.text_in("en")):
            self.assertNotIn("{", text)
        self.assertEqual(change_counter(self.root), before, "el rechazo ha escrito algo")
        return error

    def accepted(self, call: Any) -> None:
        before = change_counter(self.root)
        call()
        self.assertEqual(change_counter(self.root), before)

    def rose_change(self, key: str, value: object, version: Any = ...) -> Any:
        uid = self.v1.uid if version is ... else version
        return lambda: pit_param_check.check_pit_rose_change(self.project, key, value, version=uid)

    def ramp_change(self, key: str, value: object, version: Any = ...) -> Any:
        uid = self.v1.uid if version is ... else version
        return lambda: pit_param_check.check_pit_ramp_change(self.project, key, value, version=uid)

    def sector_change(self, key: str, value: object) -> Any:
        return lambda: pit_param_check.check_pit_sector_change(self.project, key, value, version=self.v1.uid)


class RoseValueTest(PitParameterCase):
    def test_a_boundary_that_leaves_a_gap_or_an_overlap_is_refused(self) -> None:
        """RF-018-04, RF-018-07: cambiar un azimut de un rango que deja un hueco o un solape de la roseta se rechaza nombrando la roseta, y no escribe."""
        key = design_params.rose_key(ROSE, "r1", "to_deg")
        for bad in (170.0, 200.0):
            with self.subTest(to_deg=bad):
                self.refused(self.rose_change(key, bad), "des.pit_rose_gap" if bad < 180.0 else "des.pit_rose_overlap", f"des.rose.{ROSE}", None)
        self.refused(self.rose_change(design_params.rose_key(ROSE, "r1", "from_deg"), 10.0), "des.pit_rose_gap", f"des.rose.{ROSE}", None)

    def test_a_range_that_ends_before_it_starts_is_refused(self) -> None:
        """RF-018-07: ``desde`` < ``hasta`` en cada rango."""
        key = design_params.rose_key(ROSE, "r1", "from_deg")
        self.refused(self.rose_change(key, 190.0), "des.pit_rose_value_range", design_params.rose_key(ROSE, "r1", "to_deg"), 180.0)

    def test_a_value_out_of_its_range_is_refused_with_the_name_of_the_rose(self) -> None:
        """RF-018-04: el ángulo de cara fuera de (0; 90)° se rechaza con la roseta, la clave y el valor."""
        key = design_params.rose_key(ROSE, "r2", "face_deg")
        error = self.refused(self.rose_change(key, 90.0), "des.pit_rose_value_range", key, 90.0)
        self.assertIn("Roseta del tajo", error.text)

    def test_a_valid_change_and_the_same_value_pass(self) -> None:
        """Un cambio que deja la roseta válida pasa, y no escribe (lo escribe la orden después)."""
        self.accepted(self.rose_change(design_params.rose_key(ROSE, "r1", "face_deg"), 55.0))
        self.accepted(self.rose_change(design_params.rose_key(ROSE, "r1", "to_deg"), 180.0))
        self.accepted(self.rose_change(design_params.rose_key(ROSE, "r2", "berm_m"), 0.0))

    def test_the_project_scope_is_checked_too(self) -> None:
        """RF-009-24: el cambio del proyecto (sin versión) se comprueba con los valores del proyecto, que es lo que ven las versiones sin valor propio."""
        self.refused(self.rose_change(design_params.rose_key(ROSE, "r1", "to_deg"), 200.0, None), "des.pit_rose_overlap", f"des.rose.{ROSE}", None)

    def test_a_key_that_is_not_a_rose_value_does_nothing(self) -> None:
        self.accepted(lambda: pit_param_check.check_pit_rose_change(self.project, "des.pit.pit_001.name", 5, version=self.v1.uid))
        self.accepted(self.rose_change(design_params.rose_key("no_existe", "r1", "face_deg"), 50.0))


class RampValueTest(PitParameterCase):
    def test_a_gradient_over_the_maximum_of_the_road_profile_is_refused(self) -> None:
        """RF-018-04, RF-018-15: ``g > pd`` del perfil de pista de la rampa se rechaza nombrando la rampa, el perfil, la clave, g y pd, y no escribe."""
        key = design_params.pitramp_key(RAMP, "gradient_pct")
        error = self.refused(self.ramp_change(key, PD + 1.0), "des.pit_ramp_gradient_over", key, PD + 1.0)
        self.assertEqual(error.values["limit"], PD)
        self.assertIn("Espiral", error.text)

    def test_the_maximum_itself_and_a_lower_gradient_pass(self) -> None:
        key = design_params.pitramp_key(RAMP, "gradient_pct")
        self.accepted(self.ramp_change(key, PD))
        self.accepted(self.ramp_change(key, 5.0))

    def test_a_value_out_of_its_range_is_refused(self) -> None:
        """RF-018-04: la transición negativa y la pendiente nula se rechazan con la rampa, la clave y el valor."""
        for param, bad in (("transition_m", -1.0), ("gradient_pct", 0.0)):
            key = design_params.pitramp_key(RAMP, param)
            self.refused(self.ramp_change(key, bad), "des.pit_ramp_value_range", key, bad)

    def test_the_project_scope_is_checked_too(self) -> None:
        key = design_params.pitramp_key(RAMP, "gradient_pct")
        self.refused(self.ramp_change(key, PD + 1.0, None), "des.pit_ramp_gradient_over", key, PD + 1.0)


class SectorValueTest(PitParameterCase):
    def test_a_sector_profile_of_another_height_is_refused(self) -> None:
        """RF-018-06: el perfil de un sector con otra altura que el base se rechaza con los dos y sus valores, y no escribe."""
        key = design_params.pit_sector_key(CODE, "profile", "talud_norte")
        error = self.refused(self.sector_change(key, REST), "des.pit_profiles_differ", design_params.entity_key(CODE, "profile"), EXPL)
        self.assertEqual((error.values["other"], error.values["profile"]), (REST, EXPL))
        self.accepted(self.sector_change(key, EXPL))

    def test_a_sector_with_another_number_of_benches_per_berm_is_refused(self) -> None:
        """RF-018-08: el número de bancos por berma de un sector que no es el de la corta se rechaza; el de la corta, no."""
        key = design_params.pit_sector_key(CODE, "n_berm", "talud_norte")
        self.refused(self.sector_change(key, 2), "des.pit_sector_n_berm", key, 2)
        self.accepted(self.sector_change(key, 1))

    def test_an_unknown_rose_for_a_sector_is_refused(self) -> None:
        """RF-018-07: la roseta de un sector que el proyecto no tiene; una que tiene y un valor en blanco, no."""
        key = design_params.pit_sector_key(CODE, "rose", "talud_norte")
        self.refused(self.sector_change(key, "no_existe"), "des.pit_rose_unknown", key, "no_existe")
        self.accepted(self.sector_change(key, ROSE))
        self.accepted(self.sector_change(key, ""))

    def test_the_project_scope_and_other_keys_do_nothing(self) -> None:
        key = design_params.pit_sector_key(CODE, "profile", "talud_norte")
        self.accepted(lambda: pit_param_check.check_pit_sector_change(self.project, key, REST, version=None))
        self.accepted(lambda: pit_param_check.check_pit_sector_change(self.project, "des.pit.pit_001.name", REST, version=self.v1.uid))


if __name__ == "__main__":
    unittest.main()

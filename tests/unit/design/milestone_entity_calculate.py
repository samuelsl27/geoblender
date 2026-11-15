# SPDX-License-Identifier: GPL-3.0-or-later
"""Calcular una entidad traída o heredada «sin calcular» (spec 015, T41; HU-015-2; RF-015-18; CE-015-01, última cláusula;
hallazgo C-12 de la verificación): «Traer las entidades de…» y la versión que parte de otra dejan la entidad con sus
parámetros y sin resultado, pero el diálogo de «Plataforma…» (``platform_run`` **sin** ``code``) la rechazaba
(``des.entity_name_repeated``: «sin calcular» ocupa su nombre; ``des.entity_start_taken``: ocupa su partida) y solo con
``code=`` (la API) se calculaba. La orden «Calcular…» de «Entidad ▾» la calcula con **sus** parámetros:

- ``design.entity_store.entity_request`` (nuevo, solo lee) da la ``PlatformRequest`` de una entidad **sin calcular** de
  la versión a partir de sus parámetros (``platform_parameters``: la capa, la geometría, la partida, el apoyo, el modo, el
  borde, lo que protege), con los campos de la capa que se le dan (la cota inicial, la pendiente y, de una capa de
  líneas, el ancho; un polígono, sin ancho y sin eje enlazado: el enlace del eje no es un parámetro) y nada más: lo que
  se calcula con ella es lo que ya tiene la versión (**no se escribe ningún parámetro**: la entidad conserva su código y
  su historial).
- ``platform_run(request, code=…)`` la calcula y «Crear» la registra: la **dependencia «se apoya en»** se detecta de nuevo
  (RF-015-18), con el mismo volumen que en la versión de origen (8.000 m³ a mano).
- Lo que se rechaza, **sin escribir nada** y diciendo por qué: una entidad que ya tiene resultado
  (``des.entity_calculate_done``), una descartada (``des.entity_already_discarded``), una sin partida porque la que tenía
  no existía en la versión (``des.entity_calculate_missing``) y una cuya partida es la superficie de otra que aún no
  está calculada (``des.entity_start_unknown``: se calculan por el orden de la cadena).

Sobre la cantera de la 014 con las capas de plataformas (rejilla gruesa de 2 m). V01: P1 («Plataforma de carga», del
terreno), P2 («Sobre la carga», de la superficie de P1, «en corte y relleno»: se apoya en ella con 8.000 m³) y P3 («Explanada
sin eje», un polígono sin eje enlazado); V02 recibe las tres traídas y V03, hija de V01, las hereda; V04, vacía, recibe solo P2
(sin su partida).
"""

from __future__ import annotations

import unittest
from typing import Any, ClassVar

from tests.support import entity_fixtures as efx
from tests.support.package import import_geoblender
from tests.support.versions_fixtures import change_counter, create_version
from tests.unit.design import test_entity_supports as sup
from tests.unit.design import test_platform_operation as ops_test
from tests.unit.design import test_platform_prepare as prep

core_params = import_geoblender("core.params")
design_params = import_geoblender("design.params")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
messages = import_geoblender("design.messages")
steps = import_geoblender("design.steps")
versions_model = import_geoblender("core.versions.model")

DesignError = messages.DesignError
EntityState = entities.EntityState
LOADING, OVER, NO_AXIS = prep.LOADING, sup.OVER, prep.NO_AXIS
FIELDS: dict[str, str] = {"start_level_field": "cota_inicial", "gradient_field": "pendiente", "width_field": "ancho"}
"""Los nombres de los campos de la capa que da la orden (los de por defecto del diálogo de «Plataforma…»)."""
WHY = "Prueba de la T41"
FINISH = ops_test.finish


def key(code: str, param: str) -> str:
    return design_params.entity_key(code, param)


class CalculateBroughtTest(sup.SupportsCase):
    """RF-015-18, CE-015-01, C-12: en el orden de las pruebas, (a) la petición de cada entidad sin calcular, (b) el orden de
    la cadena, (c) P1 en V02, (d) P2, que se apoya en ella, (e) la versión hija, (f) un polígono y (g) lo que se rechaza."""

    v3: ClassVar[Any]
    v4: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())
        cls.made(sup.over())
        cls.made(prep.polygon_request(NO_AXIS, linked=False, start=ops_test.EDGE_HOLE_DATASET))
        cls.clock.advance(minutes=1)
        cls.v3 = create_version(cls.project, feature="Hija", title="Hija de V01", parent="V01")
        cls.clock.advance(minutes=1)
        cls.v4 = create_version(cls.project, feature="Vacia", title="Sin entidades")
        cls.clock.advance(minutes=1)
        entity_store.bring_entities(cls.project, "V01", "V02")
        cls.clock.advance(minutes=1)
        entity_store.bring_entities(cls.project, "V01", "V04", codes=[OVER])

    # --- Ayudas ---------------------------------------------------------------------------------

    def states(self, version: Any) -> dict[str, Any]:
        return {entry.record.code: entry.record.state for entry in entities.registry(self.project, version.uid)}

    def value(self, code: str, param: str, version: Any) -> Any:
        return core_params.ParameterStore(self.project).get(key(code, param), version=version.uid).value

    def history(self, code: str, param: str, version: Any) -> list[Any]:
        return core_params.ParameterStore(self.project).history(key(code, param), version=version.uid)

    def rows(self, version: Any) -> list[tuple[Any, ...]]:
        """Los parámetros propios de ``version`` con su historial: lo que calcular **no** puede cambiar."""
        return self.query("SELECT key, value, rev, decided_by, decided_at FROM gb_parameter WHERE scope = 'version' "
                          "AND scope_uid = ? ORDER BY key", version.uid)

    def request(self, version: Any, code: str) -> Any:
        return entity_store.entity_request(self.project, version, code, **FIELDS)

    def calculate(self, version: Any, code: str) -> Any:
        """«Calcular» la entidad ``code`` de ``version`` como lo hace la orden: su petición y ``platform_run`` con su
        código; la ``Calculation`` (sin crear)."""
        asked = self.request(version, code)
        self.clock.advance(minutes=1)
        return self.calculate_in(asked, version=version.uid, masks=None, code=code)

    def refused(self, expected: str, version: Any, code: str) -> DesignError:
        """Pedir la petición de ``code`` se rechaza con ``expected`` y **no escribe nada**; devuelve el error."""
        before = (self.written(), change_counter(self.root))
        with self.assertRaises(DesignError) as caught:
            self.request(version, code)
        self.assertEqual(caught.exception.code, expected)
        self.assertEqual((self.written(), change_counter(self.root)), before, "el rechazo ha escrito algo")
        return caught.exception

    # --- (a) La petición ------------------------------------------------------------------------

    def test_a_an_entity_without_a_result_is_asked_from_its_own_parameters_and_nothing_is_written(self) -> None:
        """RF-015-18, C-12: la petición de P1 y de P2 de V02 sale de sus parámetros —el nombre, la capa, la geometría (su
        ``fid``), la partida, el apoyo, el modo y el borde— con los campos de la capa dados (el ancho, porque es una
        capa de líneas); la partida de P2 es la superficie de P1; no escribe nada (ni un parámetro ni un fichero)."""
        before = (self.written(), change_counter(self.root))
        first, second = self.request(self.v2, "PLT-001"), self.request(self.v2, "PLT-002")
        self.assertEqual((self.written(), change_counter(self.root)), before, "pedir la petición no escribe")
        self.assertEqual((first.name, first.fields.layer, first.fields.width_field, first.fields.axis_field,
                          first.start, first.support, first.mode.value, first.edge_angle_deg, first.reach_m,
                          first.protect),
                         (LOADING, efx.AXES_LAYER, "ancho", None, prep.START, None, "cut", 35.0, 20.0, False))
        self.assertEqual((first.fields.start_level_field, first.fields.gradient_field),
                         ("cota_inicial", "pendiente"))
        self.assertEqual(first.feature, str(self.value("PLT-001", "feature", self.v2)))
        self.assertEqual((second.name, second.start, second.mode.value, second.fields.layer),
                         (OVER, "entity:PLT-001", "cut_fill", sup.SUPPORT_LAYER))
        parent = entity_store.platform_parameters(self.project, self.v1, "PLT-002")
        self.assertEqual((second.edge_angle_deg, second.reach_m, second.counter_tol_m, second.mesh_factor),
                         (parent["edge_angle_deg"], parent["reach_m"], parent["counter_tol_m"], parent["mesh_factor"]))
        self.assertEqual(self.states(self.v2), {f"PLT-00{n}": EntityState.UNCALCULATED for n in (1, 2, 3)})

    def test_b_a_platform_cannot_be_calculated_before_the_one_it_starts_from(self) -> None:
        """RF-015-04, C-12: P2 parte de la superficie de P1, que en V02 aún no está calculada: se rechaza con
        ``des.entity_start_unknown`` (se calculan por el orden de la cadena); la entidad y sus parámetros no cambian (lo único
        que «Calcular» deja, antes de rechazar, son las máscaras de V02 compiladas, que es una operación propia)."""
        parameters = self.rows(self.v2)
        with self.assertRaises(DesignError) as caught:
            self.calculate(self.v2, "PLT-002")
        self.assertEqual(caught.exception.code, "des.entity_start_unknown")
        self.assertEqual(caught.exception.values["entity"], OVER)
        self.assertEqual(self.rows(self.v2), parameters)
        self.assertEqual(self.states(self.v2)["PLT-002"], EntityState.UNCALCULATED)

    # --- (c) Calcular la primera ------------------------------------------------------------------

    def test_c_the_first_is_calculated_and_created_with_the_same_code_and_without_touching_its_parameters(self) -> None:
        """RF-015-18, RF-015-01, C-12: P1 de V02 se calcula y se crea **con su código** y **sin cambiar ni un parámetro**:
        las mismas filas con el mismo historial («Traído de V01.r1»), ninguna otra entidad nueva y nada en V01; queda al
        día y no se apoya en nada."""
        parameters, in_v1, history = self.rows(self.v2), self.rows(self.v1), self.history("PLT-001", "name", self.v2)
        found = self.calculate(self.v2, "PLT-001")
        self.assertEqual(found.entity.code, "PLT-001")
        self.assertEqual(found.name, LOADING)
        found.create()
        self.assertEqual(self.states(self.v2),
                         {"PLT-001": EntityState.CURRENT, "PLT-002": EntityState.UNCALCULATED,
                          "PLT-003": EntityState.UNCALCULATED})
        self.assertEqual(self.rows(self.v2), parameters, "calcular no escribe ni cambia ningún parámetro")
        self.assertEqual(self.rows(self.v1), in_v1)
        self.assertEqual(self.history("PLT-001", "name", self.v2), history)
        self.assertEqual([item.reason for item in history], ["Traído de V01.r1"])
        self.assertEqual(len(entities.dependents(self.project, self.v2.uid, "PLT-001")), 0)

    # --- (d) La que se apoya en ella --------------------------------------------------------------

    def test_d_the_second_is_calculated_and_the_dependency_is_detected_again_with_the_same_volume(self) -> None:
        """RF-015-18, RF-015-15, CE-015-01 (D-9), C-12: P2 de V02, que rellena sobre la huella de P1, se calcula y se crea con
        su código y **se apoya de nuevo en P1** con los **8.000 m³ a mano** (≤ 10⁻⁹ relativo), los mismos que en V01; la
        cifra ``des.supported_m3`` lleva el ámbito de P1; sus parámetros siguen siendo los traídos."""
        parameters = self.rows(self.v2)
        found = self.calculate(self.v2, "PLT-002")
        self.assertEqual(found.entity.code, "PLT-002")
        stored = found.create()
        self.assertEqual(self.states(self.v2)["PLT-002"], EntityState.CURRENT)
        self.assertEqual(self.rows(self.v2), parameters)
        (row,) = entities.dependents(self.project, self.v2.uid, "PLT-001")
        self.assertEqual((row.name, set(row.roles)), (OVER, {"supported_on", "surface"}))
        self.assertLessEqual(abs(row.volume_m3 - sup.OVER_VOLUME_M3) / sup.OVER_VOLUME_M3, 1e-9, row.volume_m3)
        (original,) = entities.dependents(self.project, self.v1.uid, "PLT-001")
        self.assertEqual(row.volume_m3, original.volume_m3, "los mismos m³ que en la versión de origen")
        self.assertEqual(self.volumes_of(stored.handle.uid), {"PLT-001": row.volume_m3})

    # --- (e) La versión hija ------------------------------------------------------------------------

    def test_e_the_child_version_calculates_what_it_inherited_in_the_order_of_its_chain(self) -> None:
        """RF-015-18, RF-009-01, C-12: V03, que parte de V01, recibe sus entidades «sin calcular» (heredadas, con su
        historial «Heredado de V01.r1»): se calculan con su código y sin cambiar ningún parámetro, P1 y después P2, y P2
        se apoya en P1 con los mismos 8.000 m³."""
        parameters = self.rows(self.v3)
        self.assertEqual({code: state for code, state in self.states(self.v3).items()},
                         {f"PLT-00{n}": EntityState.UNCALCULATED for n in (1, 2, 3)})
        self.calculate(self.v3, "PLT-001").create()
        found = self.calculate(self.v3, "PLT-002")
        stored = found.create()
        self.assertEqual(self.rows(self.v3), parameters, "calcular no escribe ni cambia ningún parámetro")
        self.assertEqual([item.reason for item in self.history("PLT-002", "start", self.v3)], ["Heredado de V01.r1"])
        (row,) = entities.dependents(self.project, self.v3.uid, "PLT-001")
        self.assertLessEqual(abs(row.volume_m3 - sup.OVER_VOLUME_M3) / sup.OVER_VOLUME_M3, 1e-9, row.volume_m3)
        self.assertEqual(self.volumes_of(stored.handle.uid), {"PLT-001": row.volume_m3})
        self.assertEqual({state for state in self.states(self.v3).values()} - {EntityState.UNCALCULATED},
                         {EntityState.CURRENT})

    # --- (f) Un polígono -----------------------------------------------------------------------------

    def test_f_a_polygon_is_asked_without_a_width_and_without_a_linked_axis_and_says_it_uses_the_main_one(self) -> None:
        """RF-015-19, RF-015-18, C-12: la petición de un polígono (P3, «Explanada sin eje») no lleva ancho ni eje enlazado
        (el enlace del eje no es un parámetro de la entidad: no pasa a la versión que la trae) y su resumen avisa de que
        se usa el eje principal del polígono; se calcula con su código."""
        asked = self.request(self.v2, "PLT-003")
        self.assertEqual((asked.fields.width_field, asked.fields.axis_field, asked.fields.axis_layer),
                         (None, None, None))
        self.assertEqual(asked.fields.layer, efx.POLYGONS_LAYER)
        found = self.calculate(self.v2, "PLT-003")
        self.assertEqual(found.entity.code, "PLT-003")
        self.assertIn("des.platform_axis_principal", [notice.code for notice in found.summary.notices])
        found.create()
        self.assertEqual(self.states(self.v2)["PLT-003"], EntityState.CURRENT)

    # --- (g) Lo que se rechaza ----------------------------------------------------------------------

    def test_g_what_is_refused_says_why_and_writes_nothing(self) -> None:
        """RF-015-18, RF-015-17: una entidad que ya tiene resultado (P1 de V02), una descartada y una sin su partida (P2
        traída sola a V04: la superficie de P1 no es de V04) se rechazan con su código y el nombre de la entidad, sin
        escribir nada; una entidad que no es de la versión es un error del programa (``ValueError``) y una versión que no
        existe, la de ``core.version_unknown``."""
        done = self.refused("des.entity_calculate_done", self.v2, "PLT-001")
        self.assertEqual((done.values["entity"], done.values["code"], done.values["version"]), (LOADING, "PLT-001", "V02"))
        self.assertIn("ya tiene resultado", done.text)
        self.assertIn("«Recalcular lo obsoleto»", done.text)
        self.assertEqual(self.states(self.v4), {"PLT-002": EntityState.UNCALCULATED})
        missing = self.refused("des.entity_calculate_missing", self.v4, "PLT-002")
        self.assertEqual((missing.values["entity"], missing.values["field"]), (OVER, key("PLT-002", "start")))
        self.assertIn("«Descartar…»", missing.text)
        self.clock.advance(minutes=1)
        entity_store.discard_entity(self.project, self.v4, "PLT-002", reason=WHY, decided_by="Samuel (IMGA)")
        gone = self.refused("des.entity_already_discarded", self.v4, "PLT-002")
        self.assertEqual(gone.values["entity"], OVER)
        with self.assertRaises(ValueError) as unknown:
            self.request(self.v2, "PLT-099")
        self.assertIn("PLT-099", str(unknown.exception))
        with self.assertRaises(versions_model.VersionError) as no_version:
            entity_store.entity_request(self.project, "V99", "PLT-001", **FIELDS)
        self.assertEqual(no_version.exception.code, "core.version_unknown")

if __name__ == "__main__":
    unittest.main()

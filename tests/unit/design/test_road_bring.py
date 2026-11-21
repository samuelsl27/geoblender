# SPDX-License-Identifier: GPL-3.0-or-later
"""Traer las entidades de otra versión con la pista (spec 017, T22b; HU-017-1 y HU-017-2; RF-017-01, RF-017-02, RF-017-03; RF-015-18, RF-015-04, RF-009-01; CE-017-08, la parte de traer a
otra versión; plan 017 §5.2.3 y §5.7 P-5; el hallazgo C-4 de la 016).

``entity_store.bring_entities`` copia las **definiciones** de las entidades de otra versión y re-apunta lo que sigue los códigos nuevos: la partida, el apoyo y las dependencias declaradas
(``supports``). La pista añade dos referencias más, que son **un texto con el código de otra entidad**: su **origen**, que puede ser un punto del eje de otra pista (``RDW-001@100,5``), y su
**destino**, que puede ser una entidad de la versión (``entity:PLT-001``). Tras traer V01 a V02 **dos veces** (los códigos de la primera ya están ocupados: la pista recibe el siguiente)
el origen del ramal seguía diciendo ``RDW-001@100`` en lugar de ``RDW-004@100`` y el destino de la pista, ``entity:PLT-001`` en lugar de ``entity:PLT-003``: una pista que apuntaba a la
de la primera traída; y, si la entidad referida no se traía, no daba el aviso que sí dan ``start`` y ``support`` (``des.road_bring_origin_lost`` y ``des.road_bring_destination_lost``). Lo
que **no** es una entidad (el nombre de un punto de la capa, de una zona) se conserva tal cual.

Sobre la cantera de la 014 (rejilla gruesa) con las **cinco entidades** de la cadena de la T21 escritas como parámetros de V01 (sin operación: lo que se trae son definiciones): la plataforma
``PLT-001`` («P1»), la «Pista a P1» (``RDW-001``: destino en ella), el «Ramal» (``RDW-002``: origen en el eje de la anterior a 100,5 m), una rampa a una cota (``RDW-003``: destino por cota,
con su zona) y la «Relleno sobre la calzada» (``PLT-002``: parte de la superficie del ramal).
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from tests.support import entity_fixtures as efx
from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender
from tests.support.versions_fixtures import create_version

core_params = import_geoblender("core.params")
design_params = import_geoblender("design.params")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
messages = import_geoblender("design.messages")

GROUND = "gis_dtm_ladera"
OTHER_GROUND = "gis_dtm_levantamiento"
PERSON = "Samuel (IMGA)"
# Código → (nombre, valores que se escriben en V01). La cadena: terreno → PLT-001 → RDW-001 → RDW-002 → PLT-002; la rampa a una cota parte de otro terreno.
WORLD: dict[str, tuple[str, dict[str, Any]]] = {
    "PLT-001": ("P1", {"layer": "gis_fea_plataformas_ejes", "feature": "Eje 1", "start": OTHER_GROUND}),
    "RDW-001": ("Pista a P1", {"mode": "trace", "layer": "gis_fea_pistas_a_p1", "profile": "pista_principal", "start": "entity:PLT-001", "origin": "Entrada",
                               "destination": "entity:PLT-001", "supports": "PLT-001"}),
    "RDW-002": ("Ramal", {"mode": "trace", "layer": "gis_fea_pistas_puntos", "profile": "pista_principal", "start": "entity:RDW-001", "support": "entity:RDW-001",
                          "origin": "RDW-001@100,5", "destination": "Destino del ramal", "supports": "RDW-001"}),
    "RDW-003": ("Rampa a una cota", {"mode": "trace", "layer": "gis_fea_pistas_puntos", "profile": "pista_principal", "start": GROUND, "origin": "Entrada",
                                     "dest_level_m": 120.0, "dest_tol_m": 0.5, "dest_zone": "Cota 120"}),
    "PLT-002": ("Relleno sobre la calzada", {"layer": "gis_fea_plataformas_ejes", "feature": "Eje 2", "start": "entity:RDW-002", "mode": "cut_fill"}),
}


def key(code: str, param: str) -> str:
    return design_params.entity_key(code, param)


class AxisReferenceTest(unittest.TestCase):
    """RF-017-03, RF-015-18: lo que dice el texto de una referencia a una entidad (sin proyecto): el punto del eje de una pista y la superficie de una entidad."""

    def test_a_the_code_a_reference_points_at(self) -> None:
        """RF-017-03: ``entity:PLT-001`` apunta a ``PLT-001`` y ``RDW-001@100,5`` (un punto del eje de otra pista, con coma o con punto, con o sin parte decimal) a ``RDW-001``; el nombre de un
        punto de una capa, una abscisa mal escrita, un código en minúsculas, ``None`` y un texto en blanco no apuntan a ninguna."""
        for text, code in (("entity:PLT-001", "PLT-001"), ("  entity:PLT-001 ", "PLT-001"), ("RDW-001@100", "RDW-001"), ("RDW-001@100,5", "RDW-001"), ("RDW-012@0.25", "RDW-012")):
            with self.subTest(text=text):
                self.assertEqual(entities.refers_to(text), code)
        for text in ("Entrada", "RDW-001@", "RDW-001@abc", "rdw-001@10", "RDW-001", "entity:", "", "   ", None):
            with self.subTest(text=text):
                self.assertIsNone(entities.refers_to(text))
        with self.assertRaises(TypeError):
            entities.refers_to(5)  # type: ignore[arg-type]

    def test_b_pointing_the_same_reference_at_another_entity_keeps_the_station(self) -> None:
        """RF-015-18: ``with_code`` apunta la referencia a otro código **sin tocar lo demás**: la abscisa se queda escrita como estaba (con su coma) y ``entity:`` sigue siendo ``entity:``;
        un texto que no es una referencia es un error del programa (``ValueError``)."""
        self.assertEqual(entities.with_code("RDW-001@100,5", "RDW-004"), "RDW-004@100,5")
        self.assertEqual(entities.with_code(" RDW-001@100 ", "RDW-004"), "RDW-004@100")
        self.assertEqual(entities.with_code("entity:PLT-001", "PLT-003"), "entity:PLT-003")
        with self.assertRaises(ValueError):
            entities.with_code("Entrada", "RDW-004")


class BroughtRoadsTest(efx.EntityProjectCase):
    """RF-015-18, RF-017-03, RF-009-01, CE-017-08 (C-4): V01 con las cinco entidades; se traen a V02 (dos veces), a V03 (solo el ramal), a V04 (solo la pista a P1) y a V05 (la pista con una
    referencia que no existe). **En orden** (``test_a`` a ``test_e``): cada una parte de lo que dejó la anterior en V02."""

    STEP_M = qfx.COARSE_STEP_M

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_families((*design_params.ENTITY_FAMILIES, *design_params.ROAD_FAMILIES))
        cls.addClassCleanup(core_params.unregister_families, "des")
        store = core_params.ParameterStore(cls.project)
        cls.clock.advance(minutes=1)
        with cls.project.write_transaction() as conn:
            for code, (name, values) in WORLD.items():
                for param, value in {"name": name, **values}.items():
                    store.create(conn, key(code, param), value, kind="ADOPTADO", source="Prueba de la T22b de la 017", source_kind="person", decided_by=PERSON,
                                 reason="Prueba de la T22b", version=cls.v1.code)
        cls.clock.advance(minutes=1)

    def query(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def values(self, version: Any, code: str) -> dict[str, Any]:
        """Los parámetros de la entidad ``code`` en ``version``, por último segmento de su clave."""
        prefix = key(code, "name").removesuffix("name")
        return {found[len(prefix):]: json.loads(value) for found, value in self.query(
            "SELECT key, value FROM gb_parameter WHERE scope = 'version' AND scope_uid = ? AND key LIKE ? ORDER BY key", version.uid, f"{prefix}%")}

    def states(self, version: Any) -> dict[str, str]:
        return {entry.record.code: str(entry.record.state) for entry in entities.registry(self.project, version.uid)}

    def refs(self, version: Any, *codes: str) -> dict[str, tuple[Any, ...]]:
        """``(partida, apoyo, origen, destino, dependencias declaradas)`` de cada entidad pedida de ``version``."""
        registry = entities.registry(self.project, version.uid)
        found = {}
        for code in codes:
            record, values = registry.get(code).record, self.values(version, code)
            found[code] = (record.start, record.support, values.get("origin"), values.get("destination"), values.get("supports"))
        return found

    def test_a_the_five_entities_are_brought_uncalculated_and_the_references_keep_their_codes(self) -> None:
        """RF-015-18, RF-017-03, CE-017-08: traer V01 a V02 deja **las cinco** entidades «sin calcular» con los parámetros de la familia de su tipo (los de la pista, no los de la plataforma, y
        al revés), sin los resultados; los códigos libres se conservan y el origen en el eje de la pista (``RDW-001@100,5``, con su coma) y el destino en una entidad (``entity:PLT-001``) siguen
        diciendo lo mismo; el nombre de un punto de la capa (``Entrada``, ``Destino del ramal``) y el de la zona (``Cota 120``) también; lo de V01 no cambia."""
        before = self.states(self.v1)
        found = entity_store.bring_entities(self.project, "V01", "V02")
        self.assertEqual(sorted((item.source_code, item.code) for item in found.entities), sorted((code, code) for code in WORLD))
        self.assertEqual(set(self.states(self.v2).values()), {"uncalculated"})
        self.assertEqual(sorted(self.states(self.v2)), sorted(WORLD))
        self.assertEqual(self.states(self.v1), before)
        self.assertEqual(self.refs(self.v2, "RDW-001", "RDW-002", "RDW-003", "PLT-002"), {
            "RDW-001": ("entity:PLT-001", None, "Entrada", "entity:PLT-001", "PLT-001"),
            "RDW-002": ("entity:RDW-001", "entity:RDW-001", "RDW-001@100,5", "Destino del ramal", "RDW-001"),
            "RDW-003": (GROUND, None, "Entrada", None, None),
            "PLT-002": ("entity:RDW-002", None, None, None, None)})
        self.assertEqual(self.values(self.v2, "RDW-003")["dest_zone"], "Cota 120")
        self.assertEqual({name: value for name, value in self.values(self.v2, "RDW-001").items() if name in ("mode", "profile", "layer")},
                         {"mode": "trace", "profile": "pista_principal", "layer": "gis_fea_pistas_a_p1"})
        self.assertNotIn("guard_m", self.values(self.v2, "RDW-001"))
        self.assertEqual(self.query("SELECT count(*) FROM gb_dataset WHERE version_uid = ? AND name LIKE 'des!_%' ESCAPE '!'", self.v2.uid), [(0,)])
        self.assertEqual(found.notices[0].code, "des.entity_bring_done")
        self.assertEqual([item.code for item in found.notices if item.code.endswith("_lost")], [])

    def test_b_bringing_them_again_follows_the_new_codes_also_in_the_origin_and_the_destination(self) -> None:
        """RF-015-18, RF-017-03, RF-009-01 (C-4): al traerlas otra vez los códigos de la primera ya están ocupados: la plataforma pasa a ``PLT-003`` y ``PLT-004`` y las pistas a ``RDW-004``,
        ``RDW-005`` y ``RDW-006``; **el origen del ramal nuevo es el eje de la pista nueva** (``RDW-004@100,5``: otro código, la misma abscisa escrita igual) y **el destino de la pista nueva, la
        plataforma nueva** (``entity:PLT-003``), no los de la primera; lo que no es una entidad, igual que antes; lo ya traído, no se toca; y el motivo de la fila re-apuntada lo dice."""
        self.clock.advance(minutes=1)
        found = entity_store.bring_entities(self.project, "V01", "V02")
        recoded = {item.source_code: item.code for item in found.entities if item.recoded}
        self.assertEqual(recoded, {"PLT-001": "PLT-003", "PLT-002": "PLT-004", "RDW-001": "RDW-004", "RDW-002": "RDW-005", "RDW-003": "RDW-006"})
        self.assertEqual(self.refs(self.v2, "RDW-004", "RDW-005", "RDW-006", "PLT-004"), {
            "RDW-004": ("entity:PLT-003", None, "Entrada", "entity:PLT-003", "PLT-003"),
            "RDW-005": ("entity:RDW-004", "entity:RDW-004", "RDW-004@100,5", "Destino del ramal", "RDW-004"),
            "RDW-006": (None, None, "Entrada", None, None),  # el terreno ya es la partida de RDW-003: de cada superficie parte una entidad (RF-015-04)
            "PLT-004": ("entity:RDW-005", None, None, None, None)})
        self.assertEqual([dict(item.values)["name"] for item in found.notices if item.code == "des.entity_bring_start_taken"],
                         ["P1 (V01)", "Rampa a una cota (V01)"])  # sus nombres, ya ocupados en V02, llevan la versión de origen
        self.assertEqual(self.refs(self.v2, "RDW-002")["RDW-002"][2], "RDW-001@100,5", "lo ya traído no se toca")
        for code, param in (("RDW-004", "destination"), ("RDW-005", "origin")):
            (why,) = [reason for (reason,) in self.query(
                "SELECT h.reason FROM gb_parameter_history AS h JOIN gb_parameter AS p ON p.uid = h.parameter_uid "
                "WHERE p.key = ? AND p.scope = 'version' AND p.scope_uid = ? ORDER BY h.rev", key(code, param), self.v2.uid)]
            self.assertIn("sus referencias siguen los códigos", why)
        (plain,) = [reason for (reason,) in self.query(
            "SELECT h.reason FROM gb_parameter_history AS h JOIN gb_parameter AS p ON p.uid = h.parameter_uid WHERE p.key = ? AND p.scope = 'version' AND p.scope_uid = ?",
            key("RDW-005", "destination"), self.v2.uid)]
        self.assertNotIn("sus referencias siguen", plain, "el destino que es el nombre de un punto no se re-apunta")
        self.assertEqual(set(self.states(self.v2).values()), {"uncalculated"})
        self.assertEqual(len(self.states(self.v2)), 10)

    def test_c_the_origin_on_the_axis_of_a_road_that_is_not_brought_is_lost_with_its_notice(self) -> None:
        """RF-015-18, RF-017-03 (C-4): traer **solo el ramal** deja su origen (un punto del eje de una pista que no se trae) **sin valor** y dice cuál era (``des.road_bring_origin_lost``, con
        la pista, el nombre de la entidad referida, la versión de origen y la de destino); **no se escribe** ``origin`` (hasta que se elija otro), y el destino que es el nombre de un punto
        se conserva sin aviso; la partida, el apoyo y lo declarado se pierden con sus avisos de siempre; el ramal queda «sin calcular»."""
        v3 = create_version(self.project, feature="Solo el ramal", title="Solo el ramal")
        self.clock.advance(minutes=1)
        found = entity_store.bring_entities(self.project, "V01", v3.code, codes=["RDW-002"])
        self.assertEqual([(item.source_code, item.code) for item in found.entities], [("RDW-002", "RDW-002")])
        self.assertEqual(self.states(v3), {"RDW-002": "uncalculated"})
        values = self.values(v3, "RDW-002")
        self.assertNotIn("origin", values, "sin valor: no se escribe uno que apunta a una pista que no existe")
        self.assertEqual(values["destination"], "Destino del ramal")
        self.assertNotIn("supports", values)
        lost = [item for item in found.notices if item.code == "des.road_bring_origin_lost"]
        self.assertEqual(len(lost), 1, [item.code for item in found.notices])
        self.assertEqual(dict(lost[0].values), {"name": "Ramal", "target": "Pista a P1", "source": "V01", "version": v3.code})
        self.assertEqual(sorted(item.code for item in found.notices if item.code.endswith("_lost")),
                         ["des.entity_bring_start_lost", "des.entity_bring_support_lost", "des.entity_bring_supports_lost", "des.road_bring_origin_lost"])
        self.assertFalse([item for item in found.notices if item.code == "des.road_bring_destination_lost"])
        for language in ("es", "en"):
            text = lost[0].text(language)
            self.assertNotIn("{", text)
            for part in ("Ramal", "Pista a P1", "V01", v3.code):
                self.assertIn(part, text)
        self.assertEqual(messages.lookup("des.road_bring_origin_lost").severity, "warning")

    def test_d_the_destination_in_an_entity_that_is_not_brought_is_lost_with_its_notice(self) -> None:
        """RF-015-18, RF-017-03 (C-4): traer **solo la pista a P1** deja su destino (``entity:PLT-001``, una plataforma que no se trae) **sin valor** y dice cuál era
        (``des.road_bring_destination_lost``, con el nombre de la plataforma); su origen, que es el nombre de un punto de la capa, **se conserva**; y lo mismo la rampa a una cota,
        que no tiene destino que perder: ningún aviso."""
        v4 = create_version(self.project, feature="Solo la pista a P1", title="Solo la pista a P1")
        self.clock.advance(minutes=1)
        found = entity_store.bring_entities(self.project, "V01", v4.code, codes=["RDW-001"])
        values = self.values(v4, "RDW-001")
        self.assertNotIn("destination", values)
        self.assertEqual(values["origin"], "Entrada")
        lost = [item for item in found.notices if item.code == "des.road_bring_destination_lost"]
        self.assertEqual(len(lost), 1, [item.code for item in found.notices])
        self.assertEqual(dict(lost[0].values), {"name": "Pista a P1", "target": "P1", "source": "V01", "version": v4.code})
        self.assertFalse([item for item in found.notices if item.code == "des.road_bring_origin_lost"])
        for language in ("es", "en"):
            text = lost[0].text(language)
            self.assertNotIn("{", text)
            for part in ("Pista a P1", "P1", "V01", v4.code):
                self.assertIn(part, text)
        self.assertEqual(messages.lookup("des.road_bring_destination_lost").severity, "warning")
        v6 = create_version(self.project, feature="Solo la rampa", title="Solo la rampa")
        self.clock.advance(minutes=1)
        again = entity_store.bring_entities(self.project, "V01", v6.code, codes=["RDW-003"])
        self.assertEqual([item.code for item in again.notices if item.code.endswith("_lost")], [])
        self.assertEqual(self.values(v6, "RDW-003")["dest_zone"], "Cota 120")

    def test_e_a_reference_to_an_entity_that_does_not_exist_is_lost_naming_the_code(self) -> None:
        """RF-015-18, RF-017-03: un origen que apunta a una entidad que **ni siquiera existe** en la versión de origen (``RDW-009@10``) se pierde igual, con el código en lugar del nombre
        que no tiene; el destino de la pista traída junto a una plataforma que sí se trae se re-apunta (no es un aviso)."""
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            core_params.ParameterStore(self.project).change(conn, key("RDW-002", "origin"), value="RDW-009@10", source="Prueba de la T22b", source_kind="person",
                                                            decided_by=PERSON, reason="Un origen que no existe", version=self.v1.uid)
        v5 = create_version(self.project, feature="Referencias rotas", title="Referencias rotas")
        self.clock.advance(minutes=1)
        found = entity_store.bring_entities(self.project, "V01", v5.code, codes=["RDW-001", "PLT-001", "RDW-002"])
        lost = [item for item in found.notices if item.code == "des.road_bring_origin_lost"]
        self.assertEqual([dict(item.values)["target"] for item in lost], ["RDW-009"])
        self.assertNotIn("origin", self.values(v5, "RDW-002"))
        self.assertEqual(self.values(v5, "RDW-001")["destination"], "entity:PLT-001")
        self.assertEqual([item.code for item in found.notices if item.code == "des.road_bring_destination_lost"], [])

    def test_f_a_brought_road_has_the_row_of_its_name_in_the_project_and_a_brought_platform_does_not(self) -> None:
        """RF-015-08, RF-015-18, RF-017-01 (T29c): «Cambiar parámetro…» pide la fila del proyecto del nombre; una pista traída a otra versión (con el mismo código o con otro, si el suyo estaba ocupado)
        **la tiene** —la crea ``bring_entities``, «sin confirmar», sin valor y con el decisor por defecto; la fila de la versión es la que lleva el nombre—, de modo que se puede **renombrar antes de
        calcularla**; la plataforma traída sigue sin ella (su fila es la que deja la declaración al calcularla: el marco de la 015 no cambia)."""
        store = core_params.ParameterStore(self.project)
        for code in ("RDW-001", "RDW-002", "RDW-003", "RDW-004", "RDW-005", "RDW-006"):
            with self.subTest(code=code):
                row = store.get(key(code, "name"))
                self.assertIsNotNone(row)
                self.assertEqual((row.scope, row.unconfirmed, row.value, row.decided_by), (core_params.PROJECT_SCOPE, True, None, core_params.DEFAULT_DECIDER))
        self.assertEqual(store.get(key("RDW-004", "name"), version=self.v2.uid).value, "Pista a P1 (V01)", "el nombre es el de la fila de la versión")
        for code in ("PLT-001", "PLT-002", "PLT-003", "PLT-004"):
            with self.subTest(code=code):
                self.assertIsNone(store.get(key(code, "name")), "la plataforma no la tiene hasta que se declara")


if __name__ == "__main__":
    unittest.main()

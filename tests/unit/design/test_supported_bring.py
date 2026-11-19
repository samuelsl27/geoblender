# SPDX-License-Identifier: GPL-3.0-or-later
"""Traer las entidades de otra versión con los tipos de la 016 (spec 016, T47; hallazgo C-4 de la verificación única; RF-015-18,
RF-009-01; D-18 de la 015).

``entity_store.bring_entities`` copia las **definiciones** de las entidades de otra versión y re-apunta lo que sigue los códigos
nuevos: la partida, el apoyo y las dependencias declaradas. Con el cuerpo apoyado quedaba una referencia más: **su superficie
conocida** (``des.body.{e}.surface``, p. ej. ``entity:BDY-001``; no está en ``EntityRecord``): tras traer V01 a V02 **dos veces** (los
códigos de la primera ya están ocupados: el cuerpo recibe el siguiente) la del segundo cuerpo seguía diciendo
``entity:BDY-001`` en lugar de ``entity:BDY-003``, y, si la entidad referida no se traía, no daba el aviso que sí dan ``start`` y
``support``. La superficie conocida es ahora una referencia más (``des.body_bring_surface_lost``); la plataforma, igual que antes.

Sobre la cantera de la 014 (rejilla gruesa) con **las ocho entidades** del mundo de la T33 escritas como parámetros de V01 (sin
operación: lo que se trae son definiciones): la detección ``STK-001``, dos retiradas encadenadas (``RMV-001`` y ``RMV-002``), el
contrafuerte ``BTR-001``, los dos cuerpos (``BDY-001`` «sobre una base» y ``BDY-002`` «bajo un techo» de la superficie de
``BDY-001``) y dos plataformas (``PLT-001`` y ``PLT-002``, de la 015).
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
WORLD: dict[str, tuple[str, dict[str, Any]]] = {
    "STK-001": ("Detección 1", {"layer": "gis_fea_marcas", "surface": GROUND, "candidates": False}),
    "RMV-001": ("Retirada 1", {"stockpile": "STK-001#m01", "start": GROUND}),
    "RMV-002": ("Retirada 2", {"stockpile": "STK-001#m02", "start": "entity:RMV-001"}),
    "BTR-001": ("Contrafuerte 1", {"layer": "gis_fea_zonas", "feature": "Z1", "start": "entity:RMV-002", "support": GROUND,
                                   "profile": "EXPL", "crown_m": 115.0, "protect": True, "guard_m": 5.0}),
    "BDY-001": ("Cuerpo 1", {"layer": "gis_fea_cuerpos", "feature": "C1", "data_layer": "gis_fea_espesores", "data_field": "espesor",
                             "data_from": "field", "surface": GROUND, "sense": "on_base", "start": "entity:BTR-001"}),
    "BDY-002": ("Cuerpo 2", {"layer": "gis_fea_cuerpos", "feature": "C2", "data_layer": "gis_fea_espesores", "data_field": "espesor",
                             "data_from": "field", "surface": "entity:BDY-001", "sense": "under_roof"}),
    "PLT-001": ("P1", {"layer": "gis_fea_plataformas_ejes", "feature": "Eje 1", "start": OTHER_GROUND}),
    "PLT-002": ("P2", {"layer": "gis_fea_plataformas_ejes", "feature": "Eje 2", "start": "entity:PLT-001",
                       "support": "entity:PLT-001"}),
}


def key(code: str, param: str) -> str:
    return design_params.entity_key(code, param)


class BroughtSupportedTest(efx.EntityProjectCase):
    """RF-015-18, RF-009-01 (C-4): V01 con las ocho entidades; se traen a V02 (dos veces) y a V03 (solo un cuerpo)."""

    STEP_M = qfx.COARSE_STEP_M

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_families((*design_params.ENTITY_FAMILIES, *design_params.SUPPORTED_FAMILIES))
        cls.addClassCleanup(core_params.unregister_families, "des")
        store = core_params.ParameterStore(cls.project)
        cls.clock.advance(minutes=1)
        with cls.project.write_transaction() as conn:
            for code, (name, values) in WORLD.items():
                for param, value in {"name": name, **values}.items():
                    store.create(conn, key(code, param), value, kind="ADOPTADO", source="Prueba de la T47 de la 016",
                                 source_kind="person", decided_by=PERSON, reason="Prueba de la T47", version=cls.v1.code)
        cls.clock.advance(minutes=1)

    def query(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def surfaces(self, version: Any) -> dict[str, Any]:
        """El valor de ``surface`` de cada cuerpo de ``version``, por la clave de su parámetro."""
        return {found: json.loads(value) for found, value in self.query(
            "SELECT key, value FROM gb_parameter WHERE scope = 'version' AND scope_uid = ? AND key LIKE 'des.body.%.surface' "
            "ORDER BY key", version.uid)}

    def states(self, version: Any) -> dict[str, str]:
        return {entry.record.code: str(entry.record.state) for entry in entities.registry(self.project, version.uid)}

    def test_a_the_eight_entities_are_brought_uncalculated_and_the_known_surface_keeps_its_code(self) -> None:
        """RF-015-18, CE-016-04 (C-4): traer V01 a V02 deja **las ocho** entidades «sin calcular» con sus parámetros (los de cada
        familia, sin los de otro tipo: la detección no tiene partida) y la superficie conocida del cuerpo «bajo un techo», que
        sigue siendo la del primero (``entity:BDY-001``: el código se conserva); lo de V01 no cambia."""
        before = self.states(self.v1)
        found = entity_store.bring_entities(self.project, "V01", "V02")
        self.assertEqual(sorted((item.source_code, item.code) for item in found.entities), sorted((code, code) for code in WORLD))
        self.assertEqual(set(self.states(self.v2).values()), {"uncalculated"})
        self.assertEqual(sorted(self.states(self.v2)), sorted(WORLD))
        self.assertEqual(self.states(self.v1), before)
        self.assertEqual(self.surfaces(self.v2), {key("BDY-001", "surface"): GROUND, key("BDY-002", "surface"): "entity:BDY-001"})
        stockpile = [row for row in self.query("SELECT key FROM gb_parameter WHERE scope = 'version' AND scope_uid = ? "
                                               "AND key LIKE 'des.stockpile.%'", self.v2.uid)]
        self.assertFalse(any(name.endswith(".start") for (name,) in stockpile), "la detección no tiene partida")
        self.assertEqual(found.notices[0].code, "des.entity_bring_done")

    def test_b_bringing_them_again_follows_the_new_codes_also_in_the_known_surface_of_a_body(self) -> None:
        """RF-015-18, RF-009-01 (C-4): al traerlas otra vez los códigos de la primera ya están ocupados: los cuerpos pasan a
        ``BDY-003`` y ``BDY-004``, y **la superficie conocida del cuarto es la del tercero** (``entity:BDY-003``), no la del
        primero; la del tercero, el terreno, igual que antes; la plataforma, igual que antes (su apoyo y su partida siguen el código
        nuevo); y el motivo de la fila re-apuntada lo dice."""
        self.clock.advance(minutes=1)
        found = entity_store.bring_entities(self.project, "V01", "V02")
        recoded = {item.source_code: item.code for item in found.entities if item.recoded}
        self.assertEqual(recoded, {"STK-001": "STK-002", "RMV-001": "RMV-003", "RMV-002": "RMV-004", "BTR-001": "BTR-002",
                                   "BDY-001": "BDY-003", "BDY-002": "BDY-004", "PLT-001": "PLT-003", "PLT-002": "PLT-004"})
        surfaces = self.surfaces(self.v2)
        self.assertEqual(surfaces[key("BDY-003", "surface")], GROUND)
        self.assertEqual(surfaces[key("BDY-004", "surface")], "entity:BDY-003")
        self.assertEqual(surfaces[key("BDY-002", "surface")], "entity:BDY-001", "lo ya traído no se toca")
        registry = entities.registry(self.project, self.v2.uid)
        self.assertEqual((registry.get("PLT-004").record.start, registry.get("PLT-004").record.support),
                         ("entity:PLT-003", "entity:PLT-003"))
        self.assertEqual((registry.get("RMV-004").record.start, registry.get("BTR-002").record.start),
                         ("entity:RMV-003", "entity:RMV-004"))
        (why,) = [reason for (reason,) in self.query(
            "SELECT h.reason FROM gb_parameter_history AS h JOIN gb_parameter AS p ON p.uid = h.parameter_uid "
            "WHERE p.key = ? AND p.scope = 'version' AND p.scope_uid = ? ORDER BY h.rev", key("BDY-004", "surface"), self.v2.uid)]
        self.assertIn("sus referencias siguen los códigos", why)
        self.assertEqual(set(self.states(self.v2).values()), {"uncalculated"})
        self.assertEqual(len(self.states(self.v2)), 16)

    def test_c_the_known_surface_of_an_entity_that_is_not_brought_is_lost_with_its_notice(self) -> None:
        """RF-015-18 (C-4): traer **solo** el cuerpo «bajo un techo» deja su superficie conocida (la superficie de otra entidad que
        no se trae) **sin valor** y dice cuál era, como hacen ``start`` y ``support`` (``des.body_bring_surface_lost``, con el
        cuerpo, el nombre de la entidad, la versión de origen y la de destino); el cuerpo queda «sin calcular» y sin
        ``surface`` (hasta que se elija otra) y no se deja una referencia a una entidad que no existe."""
        v3 = create_version(self.project, feature="Solo un cuerpo", title="Solo un cuerpo")
        self.clock.advance(minutes=1)
        found = entity_store.bring_entities(self.project, "V01", v3.code, codes=["BDY-002"])
        self.assertEqual([(item.source_code, item.code) for item in found.entities], [("BDY-002", "BDY-002")])
        self.assertEqual(self.surfaces(v3), {}, "sin superficie conocida: no se escribe una que no existe")
        self.assertEqual(self.states(v3), {"BDY-002": "uncalculated"})
        lost = [item for item in found.notices if item.code == "des.body_bring_surface_lost"]
        self.assertEqual(len(lost), 1, [item.code for item in found.notices])
        self.assertEqual(dict(lost[0].values), {"name": "Cuerpo 2", "surface": "Cuerpo 1", "source": "V01", "version": v3.code})
        for language in ("es", "en"):
            text = lost[0].text(language)
            self.assertNotIn("{", text)
            for part in ("Cuerpo 2", "Cuerpo 1", "V01", v3.code):
                self.assertIn(part, text)
        self.assertEqual(messages.lookup("des.body_bring_surface_lost").severity, "warning")

    def test_d_the_known_surface_that_is_the_ground_is_kept_and_the_stockpile_surface_is_not_a_reference(self) -> None:
        """RF-015-18: la superficie conocida que es el terreno (del proyecto) se conserva sin aviso de superficie, y la superficie de
        una detección (un dato, no una referencia de la cadena) se copia tal cual (la partida de ese cuerpo, la del contrafuerte que
        no se trae, sí se pierde, con su aviso de siempre)."""
        v4 = create_version(self.project, feature="Cuerpo sobre el terreno", title="Cuerpo sobre el terreno")
        self.clock.advance(minutes=1)
        found = entity_store.bring_entities(self.project, "V01", v4.code, codes=["BDY-001", "STK-001"])
        self.assertEqual(self.surfaces(v4), {key("BDY-001", "surface"): GROUND})
        self.assertEqual([item.code for item in found.notices if item.code.endswith("surface_lost")], [])
        ((value,),) = self.query("SELECT value FROM gb_parameter WHERE scope = 'version' AND scope_uid = ? AND key = ?",
                                 v4.uid, key("STK-001", "surface"))
        self.assertEqual(json.loads(value), GROUND)


if __name__ == "__main__":
    unittest.main()

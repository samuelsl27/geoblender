# SPDX-License-Identifier: GPL-3.0-or-later
"""Traer las pistas de otra versión y «Cambiar parámetro…» con la pista calculada de verdad (spec 017, T22b; HU-017-1 y HU-017-2; RF-017-01, RF-017-02, RF-017-03; RF-015-01, RF-015-04, RF-015-08, RF-015-16,
RF-015-18 y RF-015-27; CE-017-08, la parte de traer a otra versión; plan 017 §5.2.3 y §5.7 P-5), como prueba de **hito**: ``check.py --completo`` la ejecuta; el «verde» tiene las suyas, sin calcular nada, en
``test_road_bring.py`` y ``test_road_parameter_check.py``.

Sobre la copia del proyecto de las pistas (rejilla de 2 m, 200 × 200 celdas) con las máscaras de V01 y el perfil de referencia (**solo de las pruebas**), y la cadena de la T21 calculada en V01 —la plataforma ``P1``
(``PLT-001``), la «Pista a P1» (``RDW-001``: destino en ella), el «Ramal» (``RDW-002``: origen en el eje de la anterior, ``RDW-001@100``) y la «Relleno sobre la calzada» (``PLT-002``)—:

- **Traerlas y calcularlas de nuevo** (:class:`BroughtChainTest`, RF-015-18, RF-017-03, CE-017-08; **en orden**): traer V01 a V02 deja las cuatro **sin calcular** y sin ningún resultado, con las referencias entre
  ellas como estaban y lo de V01 intacto; **calcularlas en V02** (la plataforma con su petición de «Calcular…», las pistas con la de sus parámetros) **detecta las dependencias de nuevo**: la plataforma en la que
  se apoya la pista, el eje de la pista en el ramal y la pista en que se apoya el relleno salen como lo que se apoya en cada una, con los mismos papeles y **las mismas cifras que en V01**; y traerlas otra vez, con
  los códigos ocupados, lleva el origen y la partida de las nuevas a las nuevas.
- **«Cambiar parámetro…»** (:class:`ParameterChangeTest`, RF-015-01, RF-015-08, RF-015-16, RF-015-27; **en orden**): sobre una pista calculada, un nombre vacío o repetido se rechaza sin escribir, **renombrarla no la
  deja obsoleta** (no lee su nombre) y la capa de entidades, que quedaba marcada, **se pone al día al instante** con lo que sigue al cambio (``after_entity_change``); cambiar su perfil la deja obsoleta **con su
  causa** (y, en cascada, el relleno) y la capa lo dice.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.support.versions_fixtures import change_counter
from tests.unit.design.milestone_road_create import FILL, FIRST, PLATFORM, SECOND, entity_layer_rows
from tests.unit.design.milestone_road_recompute import RecomputeCase
from tests.unit.design.test_platform_operation import finish
from tests.unit.design.test_road_prepare import BY

access = import_geoblender("gis.masks.access")
core_params = import_geoblender("core.params")
design_params = import_geoblender("design.params")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
messages = import_geoblender("design.messages")
provenance = import_geoblender("design.provenance")
road_profiles = import_geoblender("design.road_profiles")
steps = import_geoblender("design.steps")

PLATFORM_FIELDS = {"start_level_field": "cota_inicial", "gradient_field": "pendiente", "width_field": "ancho"}
"""Los campos de la capa de plataformas de la cadena (los de su diálogo): lo que da quien llama a ``entity_request``."""
DEPENDENCY_ROLES = (provenance.SUPPORTED_ON_ROLE, provenance.ROAD_AXIS_ROLE)
"""Los papeles de lo que se detecta al calcular (RF-015-15, RF-017-03): la superficie en que se apoya y el eje por estaciones de la pista del origen."""
CHAIN = ("PLT-001", "RDW-001", "RDW-002", "PLT-002")


def key(code: str, param: str) -> str:
    return design_params.entity_key(code, param)


class BringCase(RecomputeCase):
    """La cadena de la T21 calculada en V01, y las ayudas de lo que se mira en V01 y V02."""

    chain: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.chain = cls.build_chain()

    def states(self, version: Any) -> dict[str, str]:
        return {entry.record.code: str(entry.record.state) for entry in entities.registry(self.project, version.uid)}

    def operation_in(self, version: Any, code: str) -> str:
        """El uid de la operación vigente de la entidad ``code`` en ``version``."""
        entry = entities.registry(self.project, version.uid).get(code)
        assert entry is not None and entry.operation_uid is not None, code
        return str(entry.operation_uid)

    def dependency_inputs(self, uid: str) -> list[tuple[str, str]]:
        """Lo que la operación ``uid`` consumió de lo detectado: ``(nombre, papel)`` de sus entradas de apoyo, en su orden."""
        return [(name, role) for name, role in self.inputs(uid) if role in DEPENDENCY_ROLES]

    def value(self, version: Any, code: str, param: str) -> Any:
        """El valor del parámetro ``param`` de la entidad ``code`` en la versión ``version`` (``None`` si no lo tiene)."""
        found = self.query("SELECT value FROM gb_parameter WHERE scope = 'version' AND scope_uid = ? AND key = ?", version.uid, key(code, param))
        return json.loads(found[0][0]) if found else None


class BroughtChainTest(BringCase):
    """RF-015-18, RF-017-03, RF-009-01, CE-017-08: traer la cadena a V02, calcularla allí y traerla otra vez. **En orden** (``test_a`` a ``test_c``): cada una parte de lo que dejó la anterior."""

    def test_a_the_chain_is_brought_uncalculated_with_its_references_and_v01_is_untouched(self) -> None:
        """RF-015-18, CE-017-08: traer V01 a V02 deja la plataforma, las dos pistas y el relleno **sin calcular** y sin ningún resultado (ni datos, ni operaciones en V02), con los parámetros de la familia de su
        tipo y **las referencias entre ellas**: la partida de la pista a P1 es la de P1 y su destino, ``entity:PLT-001``; el ramal parte de la pista y su origen es el eje de la pista a 100 m; lo de V01 (el
        estado, las operaciones y los datos) no cambia, y no se pierde ninguna referencia."""
        operations = self.query("SELECT uid, status, superseded_by FROM gb_operation ORDER BY uid")
        names = tuple(provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, name) for name in (PLATFORM, FIRST, SECOND, FILL))
        hashes = self.hashes(*names)
        before = self.states(self.v1)
        self.clock.advance(minutes=1)
        found = entity_store.bring_entities(self.project, "V01", "V02")
        self.assertEqual(sorted((item.source_code, item.code) for item in found.entities), sorted((code, code) for code in CHAIN))
        self.assertEqual(self.states(self.v2), dict.fromkeys(CHAIN, "uncalculated"))
        self.assertEqual(self.query("SELECT count(*) FROM gb_dataset WHERE version_uid = ? AND name LIKE 'des!_%' ESCAPE '!'", self.v2.uid), [(0,)])
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation AS o JOIN gb_revision AS r ON r.uid = o.revision_uid WHERE r.version_uid = ?", self.v2.uid), [(0,)])
        self.assertEqual(self.states(self.v1), before)
        self.assertEqual(self.query("SELECT uid, status, superseded_by FROM gb_operation ORDER BY uid"), operations)
        self.assertEqual(self.hashes(*names), hashes)
        registry = entities.registry(self.project, self.v2.uid)
        self.assertEqual({code: registry.get(code).record.start for code in CHAIN},
                         {"PLT-001": rd.dataset_of("rampa"), "RDW-001": "entity:PLT-001", "RDW-002": "entity:RDW-001", "PLT-002": "entity:RDW-002"})
        self.assertEqual((self.value(self.v2, "RDW-001", "origin"), self.value(self.v2, "RDW-001", "destination")), ("Entrada", "entity:PLT-001"))
        self.assertEqual((self.value(self.v2, "RDW-002", "origin"), self.value(self.v2, "RDW-002", "supports")), ("RDW-001@100", "RDW-001"))
        self.assertEqual([item.code for item in found.notices if item.code.endswith("_lost")], [])

    def test_b_calculating_them_in_v02_detects_the_dependencies_again_with_the_same_figures(self) -> None:
        """RF-015-18, RF-017-03, RF-015-15, CE-017-08: las cuatro se calculan en V02 **por el camino de «Calcular…»** (la plataforma con ``entity_request``, las pistas con ``road_request`` de sus parámetros) y
        se crean **sin escribir otra vez sus parámetros**; la operación de cada una anota **de nuevo** lo que se apoya en otra —la superficie de ``P1`` en la pista, el eje por estaciones y la superficie de la
        pista en el ramal—, con los mismos nombres y papeles que en V01 y **las mismas cifras**; quedan al día y aparecen en lo que se apoya en cada una; lo de V01 no se toca."""
        self.profile_in_v2()
        for _step in access.ensure_masks_steps(self.project, self.v2.uid):
            pass
        masks = access.load_masks(self.project, self.v2.uid)
        parameters = self.query("SELECT key, value, rev FROM gb_parameter WHERE scope = 'version' AND scope_uid = ? AND key LIKE 'des.%' ORDER BY key", self.v2.uid)
        v1_ops = {code: self.operation_in(self.v1, code) for code in CHAIN}
        v1_inputs = {code: self.dependency_inputs(uid) for code, uid in v1_ops.items()}
        self.assertEqual([code for code in CHAIN if not v1_inputs[code]], ["PLT-001"], "en V01 las tres que parten de otra se apoyan en algo; la plataforma de la que parte todo, no")
        v2_ops: dict[str, str] = {}
        for code in CHAIN:
            self.clock.advance(minutes=1)
            if code.startswith("PLT"):
                asked = entity_store.entity_request(self.project, self.v2.uid, code, **PLATFORM_FIELDS)
                stored = finish(steps.platform_run(self.project, asked, masks=masks, version=self.v2.uid, code=code)).create()
            else:
                ((settings,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", v1_ops[code])
                asked = provenance.road_request(json.loads(settings), entity_store.entity_parameters(self.project, code, version=self.v2))
                stored = finish(steps.road_run(self.project, asked, masks=masks, version=self.v2.uid, code=code)).create(decided_by=BY)
            v2_ops[code] = str(stored.handle.uid)
        self.assertEqual(self.states(self.v2), dict.fromkeys(CHAIN, "current"))
        self.assertEqual(self.query("SELECT key, value, rev FROM gb_parameter WHERE scope = 'version' AND scope_uid = ? AND key LIKE 'des.%' ORDER BY key", self.v2.uid), parameters,
                         "calcular lo traído no reescribe sus parámetros")
        for code in CHAIN:
            self.assertEqual(self.dependency_inputs(v2_ops[code]), v1_inputs[code], code)
        on_platform = {item.entity: item for item in entities.dependents(self.project, "V02", "PLT-001")}
        on_road = {item.entity: item for item in entities.dependents(self.project, "V02", "RDW-001")}
        self.assertIn(provenance.SUPPORTED_ON_ROLE, on_platform["RDW-001"].roles)
        self.assertIn(provenance.SUPPORTED_ON_ROLE, on_road["RDW-002"].roles)
        self.assertIn("surface", on_road["RDW-002"].roles)
        self.assertIn(provenance.SUPPORTED_ON_ROLE, on_road["PLT-002"].roles)
        for code in CHAIN:
            again = {name: value for name, value, _scope in self.figures_of(v2_ops[code])}
            there = {name: value for name, value, _scope in self.figures_of(v1_ops[code])}
            self.assertEqual(sorted(again), sorted(there), code)
            for name, value in there.items():
                self.assertAlmostEqual(again[name], value, delta=1e-9 * max(1.0, abs(value)), msg=f"{code}: {name}")
            self.assertEqual(self.stale_causes(v2_ops[code]), set(), code)
        self.assertEqual({code: self.operation_in(self.v1, code) for code in CHAIN}, v1_ops, "V01 sigue con lo suyo")

    def test_c_bringing_them_again_points_the_origin_and_the_start_at_the_new_codes(self) -> None:
        """RF-015-18, RF-017-03 (C-4): traer la cadena a V02 **otra vez** (los códigos ya están ocupados): las pistas pasan a ``RDW-003`` y ``RDW-004``, la plataforma a ``PLT-003`` y el relleno a ``PLT-004``;
        **el origen del ramal nuevo es el eje de la pista nueva** (``RDW-003@100``) y la pista nueva parte de la plataforma nueva (``entity:PLT-003``) y su destino es esa plataforma, no las que ya están calculadas
        en V02; las nuevas quedan sin calcular y las primeras, como estaban."""
        before = self.states(self.v2)
        self.clock.advance(minutes=1)
        found = entity_store.bring_entities(self.project, "V01", "V02")
        self.assertEqual({item.source_code: item.code for item in found.entities if item.recoded}, {"PLT-001": "PLT-003", "RDW-001": "RDW-003", "RDW-002": "RDW-004", "PLT-002": "PLT-004"})
        self.assertEqual(self.states(self.v2), {**before, **dict.fromkeys(("PLT-003", "RDW-003", "RDW-004", "PLT-004"), "uncalculated")})
        self.assertEqual(self.value(self.v2, "RDW-004", "origin"), "RDW-003@100")
        self.assertEqual(self.value(self.v2, "RDW-003", "destination"), "entity:PLT-003")
        self.assertEqual(self.value(self.v2, "RDW-002", "origin"), "RDW-001@100", "lo ya traído no se toca")
        registry = entities.registry(self.project, self.v2.uid)
        self.assertEqual(registry.get("RDW-003").record.start, "entity:PLT-003")
        self.assertEqual(registry.get("RDW-004").record.start, "entity:RDW-003")

    def profile_in_v2(self) -> None:
        """El perfil de referencia, con sus valores en V02 (el perfil de V01 no se trae con las entidades: son parámetros de su versión)."""
        declared = road_profiles.ProfileDeclaration("ITC 07.1.03 de la prueba", BY, "Perfil de la prueba de la T22b", version=self.v2.code)
        values = {param: getattr(rd.PROFILE, "class_name" if param.value == "class" else param.value) for param in design_params.RoadProfileParam}
        self.clock.advance(minutes=1)
        road_profiles.edit_road_profiles(self.project, (road_profiles.ProfileEdit(code="pista_principal", values=values),), declared)


class ParameterChangeTest(BringCase):
    """RF-015-01, RF-015-08, RF-015-16, RF-015-27 (D-2 de la 016, con la pista): «Cambiar parámetro…» de una pista calculada y lo que sigue al cambio. **En orden** (``test_a`` a ``test_c``)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        for _step in entity_store.entity_layer_steps(cls.project, cls.v1):
            pass
        cls.clock.advance(minutes=1)

    def layer(self) -> dict[str, Any]:
        with self.project.read() as conn:
            return {row.code: row for row in entity_layer_rows(conn, self.v1.code)}

    def pending(self) -> bool:
        with self.project.read() as conn:
            return entity_store.layer_pending(self.project, conn, self.v1.uid)

    def command(self, param: str, value: Any, code: str = "RDW-002") -> None:
        """Lo que hace «Cambiar parámetro…»: la comprobación **antes** de escribir y, si pasa, el cambio de la versión (``ParameterStore.change``)."""
        entity_store.check_parameter_change(self.project, key(code, param), value, version=self.v1.uid)
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            core_params.ParameterStore(self.project).change(
                conn, key(code, param), value=value, source="prueba de «Cambiar parámetro…» (T22b)", source_kind="person", decided_by=BY, reason="Se cambia un parámetro de la pista",
                version=self.v1.uid)

    def test_a_an_empty_or_repeated_name_is_refused_without_writing_and_a_free_one_renames_the_road(self) -> None:
        """RF-015-01, RF-015-08: sobre la pista calculada, un nombre vacío o el de otra entidad (otra pista o una plataforma) se rechaza con la pista y el campo, **con 0 transacciones**; uno libre se admite y se
        escribe; **renombrarla no la deja obsoleta** (la operación no lee su nombre) y el registro de las entidades dice el nombre nuevo."""
        before = change_counter(self.root)
        for blank in ("", "   ", None):
            with self.subTest(value=blank), self.assertRaises(messages.DesignError) as caught:
                entity_store.check_parameter_change(self.project, key("RDW-002", "name"), blank, version=self.v1.uid)
            self.assertEqual((caught.exception.code, caught.exception.values["entity"], caught.exception.values["field"]), ("des.entity_param_missing", SECOND, key("RDW-002", "name")))
        for taken in (FIRST, PLATFORM, FILL):
            with self.subTest(value=taken), self.assertRaises(messages.DesignError) as caught:
                entity_store.check_parameter_change(self.project, key("RDW-002", "name"), taken, version=self.v1.uid)
            self.assertEqual((caught.exception.code, caught.exception.values["other"]), ("des.entity_name_repeated", taken))
        self.assertEqual(change_counter(self.root), before, "los rechazos no escriben")
        op = self.operation_in(self.v1, "RDW-002")
        self.command("name", "Ramal norte")
        self.assertEqual(entities.registry(self.project, self.v1.uid).get("RDW-002").record.name, "Ramal norte")
        self.assertEqual(self.stale_causes(op), set(), "renombrar una pista no la deja obsoleta: su operación no lee el nombre")
        self.assertEqual(self.states(self.v1)["RDW-002"], "current")

    def test_b_the_entity_layer_is_brought_up_to_date_at_once_after_the_change(self) -> None:
        """RF-015-27, RF-015-29 (D-2 de la 016, con la pista): tras renombrarla, la capa de entidades **queda marcada** (dice el nombre de antes) y lo que sigue al cambio (``after_entity_change``, lo que
        lanza «Cambiar parámetro…» por ``des_entity_refresh``) la **pone al día al instante**: la fila de la pista dice el nombre nuevo, al día, y ya no está marcada; la pista no declara nada."""
        self.assertTrue(self.pending())
        self.assertEqual(self.layer()["RDW-002"].name, SECOND)
        last = None
        for last in entity_store.after_entity_change(self.project, self.v1.uid):
            pass
        chain = last.result
        self.assertTrue(chain.layer_changed)
        self.assertIsNone(chain.layer_failure)
        self.assertIsNone(chain.failure)
        self.assertEqual(chain.declared, 0, "ni la pista ni las plataformas de la cadena protegen: nada que declarar")
        self.assertFalse(self.pending())
        self.assertEqual((self.layer()["RDW-002"].name, self.layer()["RDW-002"].state), ("Ramal norte", entities.EntityState.CURRENT))

    def test_c_a_value_the_operation_reads_makes_the_road_stale_with_its_cause_and_the_layer_says_so(self) -> None:
        """RF-015-16, RF-015-27: cambiar un parámetro que la pista **sí** lee (su perfil) la deja obsoleta **con su causa** —el parámetro— y, por la cadena, el relleno que parte de ella; lo que sigue al cambio
        pone al día la capa, que dice «obsoleta» de las dos; el perfil que no existe lo rechaza el cálculo, no el cambio."""
        op, fill = self.operation_in(self.v1, "RDW-002"), self.operation_in(self.v1, "PLT-002")
        self.command("profile", "otro_perfil")
        self.assertIn(("parameter_changed", key("RDW-002", "profile")), self.stale_causes(op))
        self.assertTrue(self.stale_causes(fill), "lo que parte de la pista queda obsoleto en cascada")
        self.assertTrue(self.pending())
        for _step in entity_store.after_entity_change(self.project, self.v1.uid):
            pass
        found = self.layer()
        self.assertEqual((found["RDW-002"].state, found["PLT-002"].state), (entities.EntityState.STALE, entities.EntityState.STALE))
        self.assertFalse(self.pending())
        self.assertEqual(self.states(self.v1)["RDW-002"], "stale")

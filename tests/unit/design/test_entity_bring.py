# SPDX-License-Identifier: GPL-3.0-or-later
"""Traer las entidades de otra versión y la versión que parte de otra (spec 015, T26; HU-015-2; RF-015-18,
RF-009-01; D-18; plan 015 §5.2.2, §5.3.3, §5.7 P-4; CE-015-01): el marco del error 59 entre versiones.

- **La versión que parte de otra** (RF-009-01, spec 0.4): ``ParameterStore.inherit`` le da los parámetros de entidad
  de la madre (``des.platform.{e}.*``) con su historial «Heredado de V01.r1» y **sin ningún resultado**: en
  ``entities.registry`` salen «sin calcular»; la declaración y las máscaras no las toman por calculadas.
- **Traer** (``entity_store.bring_entities``): copia las **definiciones** de las entidades de **cualquier otra
  versión** (los parámetros con su decisor, su fecha y su origen, y un historial «Traído de V01.r1»; la capa y la
  geometría de origen; las dependencias que declaró la persona), **sin superficies, tablas, cifras ni restricciones
  declaradas** (se regeneran al calcular), «sin calcular». Si un código ya está ocupado en la versión, la entidad
  recibe el siguiente y **las referencias entre las traídas** (``start``, ``support``, ``supports``) siguen el
  código nuevo; una partida que es un resultado de la versión de origen (la superficie de una entidad que no se
  trae, o una de diseño) no existe en la de destino y queda **sin valor**, con un aviso; el terreno, que es del
  proyecto, se conserva. Las descartadas no se traen. Una sola transacción.
- **Calcularlas** (``platform_run`` con ``code=``): las dependencias se detectan de nuevo (CE-015-01).

Sobre la cantera de la 014 con las capas de plataformas (rejilla gruesa de 2 m). El primer mundo: V01 con P1 («Plataforma
de carga», del terreno), P2 («Sobre la carga», de la superficie de P1, «en corte y relleno»: se apoya en P1), P3 («Plataforma
de taller», de la de P2, que protege con 4 m: declara una restricción), P4 (una «Explanada con eje» **sin calcular**, que
parte de la superficie de P1 por su nombre y declara apoyarse en P1 y en P5), P5 (una «Explanada sin eje», calculada y
**descartada**) y P6 (una «Plataforma de la torre» sin calcular y descartada); V02 (sin entidades), V03 (hija de V01) y
V04 (vacía).
"""

from __future__ import annotations

import unittest
from typing import Any, ClassVar
from unittest import mock

from tests.support.package import import_geoblender
from tests.support.versions_fixtures import change_counter, create_version
from tests.unit.design import test_entity_supports as sup
from tests.unit.design import test_platform_operation as ops_test
from tests.unit.design import test_platform_prepare as prep

access = import_geoblender("gis.masks.access")
core_params = import_geoblender("core.params")
design_params = import_geoblender("design.params")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
messages = import_geoblender("design.messages")
params_model = import_geoblender("core.params.model")
provenance = import_geoblender("design.provenance")
versions_model = import_geoblender("core.versions.model")

DesignError = messages.DesignError
EntityState = entities.EntityState
LOADING, OVER, WORKSHOP, TOWER = prep.LOADING, sup.OVER, prep.WORKSHOP, prep.TOWER
WITH_AXIS, NO_AXIS = prep.WITH_AXIS, prep.NO_AXIS
GUARD_M = 4.0
USER = "Samuel (IMGA)"
WHY = "Prueba de la T26"
PSF_LOADING = provenance.dataset_name("psf", LOADING)
NONE = {"datasets": [], "operations": [], "figures": []}
"""Lo que tiene una versión que solo tiene definiciones: ningún resultado."""
FINISH = ops_test.finish


def key(code: str, param: str) -> str:
    return design_params.entity_key(code, param)


def codes(found: Any) -> list[tuple[str, str]]:
    """Los ``(código de origen, código de destino)`` de lo traído."""
    return [(item.source_code, item.code) for item in found.entities]


# ---------------------------------------------------------------------------------------------
# La versión que parte de otra y traer las entidades de otra
# ---------------------------------------------------------------------------------------------


class BringTest(sup.SupportsCase):
    """RF-015-18, RF-009-01, D-18: V03 parte de V01 y se traen a V02 las entidades de V01, por el orden de las pruebas:
    (a) lo heredado, (b) traerlas todas, (c) otra vez, con los códigos y los nombres ocupados, (d) solo una, (e) las
    descartadas, (f) lo que se rechaza y (g) una sola transacción."""

    v3: ClassVar[Any]
    v4: ClassVar[Any]

    @classmethod
    def defined(cls, asked: Any) -> str:
        """Da de alta una entidad **sin calcular** en V01 (sus parámetros, como los escribe «Crear»): su código."""
        prepared = prep.drive(entity_store.prepare_platform_units(cls.project, asked, cls.v1, cls.masks_v1))
        cls.clock.advance(minutes=1)
        entity_store.set_entity_params(cls.project, prepared.rows, version=cls.v1.uid)
        return str(prepared.code)

    @classmethod
    def discard(cls, code: str) -> None:
        cls.clock.advance(minutes=1)
        entity_store.discard_entity(cls.project, cls.v1.uid, code, reason=WHY, decided_by=USER)

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())
        cls.made(sup.over())
        cls.made(prep.request(WORKSHOP, start="entity:PLT-002", protect=True, guard_m=GUARD_M))
        assert cls.defined(prep.polygon_request(WITH_AXIS, start=PSF_LOADING)) == "PLT-004"
        cls.clock.advance(minutes=1)
        with cls.project.write_transaction() as conn:
            core_params.ParameterStore(cls.project).create(
                conn, key("PLT-004", "supports"), "PLT-001, PLT-005", kind="ADOPTADO", source=WHY,
                source_kind="person", decided_by=USER, reason=WHY, version=cls.v1.uid)
        cls.made(prep.polygon_request(NO_AXIS, linked=False, start=ops_test.EDGE_HOLE_DATASET))
        cls.discard("PLT-005")
        assert cls.defined(prep.request(TOWER, start=prep.HOLE_DATASET)) == "PLT-006"
        cls.discard("PLT-006")
        cls.clock.advance(minutes=1)
        FINISH(entity_store.declare_constraints_steps(cls.project, cls.v1))
        cls.clock.advance(minutes=1)
        cls.v3 = create_version(cls.project, feature="Hija", title="Hija de V01", parent="V01")
        cls.clock.advance(minutes=1)
        cls.v4 = create_version(cls.project, feature="Vacia", title="Sin entidades")
        cls.clock.advance(minutes=1)

    # --- Ayudas ---------------------------------------------------------------------------------

    def registry(self, version: Any) -> Any:
        return entities.registry(self.project, version.uid)

    def record(self, code: str, param: str, version: Any) -> Any:
        return core_params.ParameterStore(self.project).get(key(code, param), version=version.uid)

    def version_rows(self, version: Any) -> list[tuple[Any, ...]]:
        """Los parámetros propios de ``version`` con todo lo que se copia, por clave."""
        return self.query("SELECT key, value, unit, kind, source, source_kind, decided_by, decided_at, rev, reason "
                          "FROM gb_parameter WHERE scope = 'version' AND scope_uid = ? ORDER BY key", version.uid)

    def results_of(self, version: Any) -> dict[str, Any]:
        """Todo **resultado** que tiene ``version``: datos, operaciones y cifras (ninguno si solo tiene definiciones)."""
        return {
            "datasets": self.query("SELECT name FROM gb_dataset WHERE version_uid = ?", version.uid),
            "operations": self.query(
                "SELECT o.uid FROM gb_operation AS o JOIN gb_revision AS r ON r.uid = o.revision_uid "
                "WHERE r.version_uid = ?", version.uid),
            "figures": self.query(
                "SELECT f.key FROM gb_figure AS f JOIN gb_operation AS o ON o.uid = f.operation_uid "
                "JOIN gb_revision AS r ON r.uid = o.revision_uid WHERE r.version_uid = ?", version.uid)}

    def states(self, version: Any) -> dict[str, Any]:
        return {entry.record.code: entry.record.state for entry in self.registry(version)}

    def history(self, code: str, param: str, version: Any) -> list[Any]:
        return core_params.ParameterStore(self.project).history(key(code, param), version=version.uid)

    def refused(self, expected: str, *args: Any, **options: Any) -> Any:
        """Traer se rechaza con ``expected`` y **no escribe nada**; devuelve el error."""
        before = (self.written(), change_counter(self.root))
        with self.assertRaises(DesignError) as caught:
            entity_store.bring_entities(self.project, *args, **options)
        self.assertEqual(caught.exception.code, expected)
        self.assertEqual((self.written(), change_counter(self.root)), before, "el rechazo ha escrito algo")
        return caught.exception

    # --- (a) La versión que parte de otra ------------------------------------------------------

    def test_a1_the_child_version_gets_the_definitions_without_any_result_and_they_are_not_calculated(self) -> None:
        """RF-015-18, RF-009-01, D-18: las entidades de V01 llegan a V03 (que parte de ella) con su nombre, su partida
        y sus parámetros, **sin calcular** (sin operación, sin obsolescencia, sin apoyo retirado), y V03 no tiene
        ningún dato, ninguna operación ni ninguna cifra de V01; la descartada sin calcular (P6) llega descartada."""
        mine = self.registry(self.v3)
        self.assertEqual([entry.record.code for entry in mine], [f"PLT-00{number}" for number in range(1, 7)])
        parent = {entry.record.code: entry.record for entry in self.registry(self.v1)}
        self.assertEqual(self.states(self.v1)["PLT-001"], EntityState.CURRENT)
        self.assertEqual(mine.get("PLT-006").record.state, EntityState.DISCARDED,
                         "la descartada sin calcular llega descartada")
        for number in (1, 2, 3, 4):
            code = f"PLT-00{number}"
            entry = mine.get(code)
            with self.subTest(entity=code):
                self.assertEqual((entry.record.state, entry.operation_uid, entry.causes, entry.retired),
                                 (EntityState.UNCALCULATED, None, frozenset(), ()))
                self.assertEqual((entry.record.name, entry.record.start, entry.record.support),
                                 (parent[code].name, parent[code].start, parent[code].support))
        self.assertEqual(self.results_of(self.v3), NONE)

    def test_a2_the_inherited_parameters_come_with_a_history_of_where_they_were_inherited_from(self) -> None:
        """RF-009-01, RF-015-18: cada parámetro de entidad de V03 lleva el valor, el decisor y la fecha de la decisión
        de V01 y una entrada de historial «Heredado de V01.r1»."""
        for code, param in (("PLT-001", "width_m"), ("PLT-003", "protect"), ("PLT-001", "start")):
            with self.subTest(param=param):
                parent, child = (self.record(code, param, version) for version in (self.v1, self.v3))
                self.assertEqual((child.value, child.decided_by, child.decided_at, child.source),
                                 (parent.value, parent.decided_by, parent.decided_at, parent.source))
                (entry,) = self.history(code, param, self.v3)
                self.assertEqual((str(entry.action), entry.reason), ("create", "Heredado de V01.r1"))

    def test_a3_the_declaration_and_the_chain_do_not_take_them_for_calculated(self) -> None:
        """RF-015-18, RF-015-10: la declaración de V03 no recoge ninguna entidad (P3 protege, pero no está calculada
        en V03): no declara nada, aunque herede su ``protect`` y su ``guard_m``, y la tabla queda vacía; la cadena de
        las heredadas es válida."""
        self.assertEqual(entity_store.declared_sources(self.project, self.v3), ())
        FINISH(entity_store.declare_constraints_steps(self.project, self.v3))
        with self.project.read() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM "des_decl_v03"').fetchall(), [(0,)])
        records = self.registry(self.v3).records
        entities.check_chain(records)
        self.assertIn("PLT-003", [record.code for record in entities.chain_tails(records)])

    # --- (b) Traerlas todas ---------------------------------------------------------------------

    def test_b1_all_the_live_entities_are_brought_without_any_result(self) -> None:
        """RF-015-18, RF-009-01: traer de V01 a V02 da las **cuatro** entidades vivas con sus códigos y nombres (V02
        no tenía ninguna), **sin calcular**, y nada más: ni superficies, ni tablas, ni cifras, ni la restricción
        declarada de P3 (se regenera al calcularla); V01 sigue como estaba y las capas de origen no se tocan. La
        partida de P1 (el terreno) se conserva, las de P2 y P3 siguen la cadena y la de P4, que era la superficie de
        P1 por su nombre (un resultado de V01), queda sin valor, con su aviso; de lo que P4 declaró apoyarse, P1 se
        copia y P5 (descartada, no se trae) no."""
        before_v1, layers = self.version_rows(self.v1), self.layers()
        found = entity_store.bring_entities(self.project, "V01", "V02")
        self.assertEqual((found.source, found.version, found.label), ("V01", "V02", "V01.r1"))
        self.assertEqual(codes(found), [(f"PLT-00{n}", f"PLT-00{n}") for n in range(1, 5)])
        self.assertEqual([(item.source_name, item.name) for item in found.entities],
                         [(LOADING, LOADING), (OVER, OVER), (WORKSHOP, WORKSHOP), (WITH_AXIS, WITH_AXIS)])
        self.assertFalse(any(item.recoded or item.renamed for item in found.entities))
        self.assertEqual(self.states(self.v2), {f"PLT-00{n}": EntityState.UNCALCULATED for n in range(1, 5)})
        mine = {entry.record.code: entry.record for entry in self.registry(self.v2)}
        self.assertEqual((mine["PLT-001"].start, mine["PLT-002"].start, mine["PLT-003"].start),
                         (prep.START, "entity:PLT-001", "entity:PLT-002"))
        self.assertIsNone(mine["PLT-004"].start)
        self.assertEqual(self.record("PLT-004", "supports", self.v2).value, "PLT-001")
        self.assertEqual(self.results_of(self.v2), NONE)
        with self.project.read() as conn:
            self.assertEqual(conn.execute("SELECT name FROM sqlite_master WHERE name = 'des_decl_v02'").fetchall(), [],
                             "la restricción declarada no se trae: se regenera al calcular")
        self.assertEqual(self.version_rows(self.v1), before_v1, "V01 no cambia")
        self.assertEqual(self.layers(), layers, "las capas de origen no se tocan")
        self.assertEqual({notice.code for notice in found.notices},
                         {"des.entity_bring_done", "des.entity_bring_start_lost", "des.entity_bring_supports_lost"})
        done = found.notices[0]
        self.assertEqual((done.code, done.values["count"]), ("des.entity_bring_done", 4))
        self.assertIn("4 entidades traídas de V01 a V02", done.text("es"))
        lost = [notice for notice in found.notices if notice.code == "des.entity_bring_start_lost"]
        self.assertEqual([notice.values["surface"] for notice in lost], [PSF_LOADING])
        self.assertIn("es un resultado de V01", lost[0].text("es"))

    def test_b2_the_parameters_keep_their_decision_and_get_a_history_of_where_they_were_brought_from(self) -> None:
        """RF-015-18: cada parámetro traído lleva el valor, el tipo, el origen, el decisor y la fecha de la decisión de
        V01, y una sola entrada de historial «Traído de V01.r1» (de quien lo trajo); lo que no tiene valor en V01 no
        tiene fila en V02; el ``discarded`` no se trae."""
        mine = {row[0]: row for row in self.version_rows(self.v2)}
        theirs = {row[0]: row for row in self.version_rows(self.v1)
                  if any(f".plt_00{n}." in row[0] for n in range(1, 5)) and not row[0].endswith(".discarded")}
        self.assertEqual(set(mine), set(theirs) - {key("PLT-004", "start")})
        for name, row in theirs.items():
            if name in (key("PLT-004", "start"), key("PLT-004", "supports")):
                continue  # la partida pierde su valor y las dependencias, las de lo que no se trae
            with self.subTest(key=name):
                self.assertEqual(mine[name][1:8], row[1:8], "valor, unidad, tipo, origen, decisor y fecha: los de V01")
                self.assertEqual(mine[name][8], 1)
        record = self.record("PLT-001", "width_m", self.v2)
        self.assertEqual((record.value, record.decided_by, record.kind),
                         (20.0, self.project.session.user_host, params_model.ParamKind.ADOPTADO))
        self.assertIn("campo «ancho»", record.source)
        (entry,) = self.history("PLT-001", "width_m", self.v2)
        self.assertEqual((str(entry.action), entry.reason, entry.changed_by),
                         ("create", "Traído de V01.r1", self.project.session.user_host))

    # --- (c) Traerlas otra vez ------------------------------------------------------------------

    def test_c_bringing_again_gives_new_codes_and_names_and_the_references_between_them_follow(self) -> None:
        """RF-015-18: V02 ya tiene PLT-001 a PLT-004 con esos nombres: las cuatro entidades de V01 llegan como PLT-005
        a PLT-008, con su nombre y el código de su versión de origen entre paréntesis, y **las referencias entre ellas
        siguen el código nuevo** (P2 parte de PLT-005, P3 de PLT-006, P4 apoya en PLT-005); la partida de P1, el
        terreno, ya es la de PLT-001: queda sin valor, con su aviso, porque de cada superficie parte una entidad."""
        found = entity_store.bring_entities(self.project, "V01", "V02")
        self.assertEqual(codes(found), [("PLT-001", "PLT-005"), ("PLT-002", "PLT-006"), ("PLT-003", "PLT-007"),
                                        ("PLT-004", "PLT-008")])
        self.assertEqual([item.name for item in found.entities],
                         [f"{name} (V01)" for name in (LOADING, OVER, WORKSHOP, WITH_AXIS)])
        self.assertTrue(all(item.recoded and item.renamed for item in found.entities))
        mine = {entry.record.code: entry.record for entry in self.registry(self.v2)}
        self.assertEqual((mine["PLT-005"].start, mine["PLT-006"].start, mine["PLT-007"].start),
                         (None, "entity:PLT-005", "entity:PLT-006"))
        self.assertEqual(self.record("PLT-008", "supports", self.v2).value, "PLT-005")
        self.assertEqual(mine["PLT-005"].name, f"{LOADING} (V01)")
        self.assertEqual({notice.code for notice in found.notices},
                         {"des.entity_bring_done", "des.entity_bring_recoded", "des.entity_bring_renamed",
                          "des.entity_bring_start_taken", "des.entity_bring_start_lost",
                          "des.entity_bring_supports_lost"})
        taken = next(notice for notice in found.notices if notice.code == "des.entity_bring_start_taken")
        self.assertEqual(taken.values["other"], LOADING)
        self.assertIn(f"«{LOADING}»", taken.text("es"))
        recoded = next(notice for notice in found.notices if notice.code == "des.entity_bring_recoded")
        self.assertIn("era PLT-001 en V01; aquí es PLT-005", recoded.text("es"))
        (entry,) = self.history("PLT-005", "name", self.v2)
        self.assertIn("Traído de V01.r1", entry.reason)
        self.assertIn(f"era la entidad PLT-001 «{LOADING}» de V01", entry.reason)
        entities.check_chain(self.registry(self.v2).records)
        self.assertEqual(self.results_of(self.v2), NONE)

    # --- (d) Solo las elegidas -----------------------------------------------------------------

    def test_d_only_the_chosen_ones_are_brought_and_what_they_started_from_is_not_kept(self) -> None:
        """RF-015-18: traer solo «Sobre la carga» (por su nombre) a V02, que ya tiene un PLT-001 —otra entidad—: la
        partida de P2 era la superficie de la PLT-001 **de V01**, que no se trae, y no vale en V02 (donde PLT-001 es
        otra): queda sin valor, con su aviso y el nombre de la entidad de V01; recibe el código siguiente (PLT-009) y
        un nombre que no choca con ninguno."""
        found = entity_store.bring_entities(self.project, "V01", "V02", codes=[OVER])
        self.assertEqual(codes(found), [("PLT-002", "PLT-009")])
        (item,) = found.entities
        self.assertEqual(item.name, f"{OVER} (V01) 2", "«Sobre la carga (V01)» ya está: un número más")
        self.assertIsNone(item.start)
        self.assertIsNone(self.registry(self.v2).get("PLT-009").record.start)
        lost = next(notice for notice in found.notices if notice.code == "des.entity_bring_start_lost")
        self.assertEqual(lost.values["surface"], LOADING)

    # --- (e) Las descartadas -------------------------------------------------------------------

    def test_e_the_discarded_ones_are_not_brought_and_asking_for_one_is_refused(self) -> None:
        """RF-015-18, RF-015-17: P5 (descartada con sus datos) y P6 (descartada sin calcular) no se traen con
        ``codes=None`` ni se pueden pedir: ``des.entity_bring_discarded``, nombrando la entidad y la versión de origen;
        una entidad que V01 no tiene, ``des.entity_bring_unknown``; sin escribir nada."""
        for ref in ("PLT-005", NO_AXIS, "PLT-006"):
            with self.subTest(ref=ref):
                error = self.refused("des.entity_bring_discarded", "V01", "V04", codes=[ref])
                self.assertEqual(error.values["source"], "V01")
                self.assertIn("está descartada en V01", error.text)
        error = self.refused("des.entity_bring_unknown", "V01", "V04", codes=["PLT-099"])
        self.assertEqual((error.values["entity"], error.values["source"]), ("PLT-099", "V01"))
        self.assertEqual(self.states(self.v4), {})

    # --- (f) Lo que se rechaza ------------------------------------------------------------------

    def test_f_the_same_version_a_version_that_is_not_editable_and_nothing_to_bring(self) -> None:
        """RF-015-18, RF-009-21: de V01 a V01, ``des.entity_bring_same``; a una versión SUPERADA, ``core.version_not_
        editable``; una versión de origen sin entidades no trae nada (una nota, sin escribir); una versión que no
        existe, ``core.version_unknown``."""
        self.refused("des.entity_bring_same", "V01", "V01")
        before = (self.written(), change_counter(self.root))
        found = entity_store.bring_entities(self.project, "V04", "V02")
        self.assertEqual((found.entities, [notice.code for notice in found.notices]),
                         ((), ["des.entity_bring_nothing"]))
        self.assertEqual((self.written(), change_counter(self.root)), before, "sin entidades, no escribe nada")
        with self.project.write_transaction() as conn:  # V04: VIGENTE y después SUPERADO
            conn.execute("UPDATE gb_version SET status = 'VIGENTE' WHERE uid = ?", (self.v4.uid,))
            conn.execute("UPDATE gb_version SET status = 'SUPERADO', reason_closed = ? WHERE uid = ?",
                         (WHY, self.v4.uid))
        before = (self.written(), change_counter(self.root))
        for source, target, code in (("V01", "V04", "core.version_not_editable"),
                                     ("V01", "V99", "core.version_unknown"),
                                     ("V99", "V02", "core.version_unknown")):
            with self.subTest(target=target, source=source), self.assertRaises(versions_model.VersionError) as caught:
                entity_store.bring_entities(self.project, source, target)
            self.assertEqual(caught.exception.code, code)
        self.assertEqual((self.written(), change_counter(self.root)), before)

    # --- (g) Una sola transacción ---------------------------------------------------------------

    def test_g_a_failure_midway_leaves_nothing(self) -> None:
        """RF-015-18: traer escribe en **una** transacción: si falla un parámetro a mitad, no queda ninguno de los
        anteriores en el destino; y después se puede traer."""
        target = create_version(self.project, feature="Destino", title="Destino")
        before = (self.version_rows(target), self.written(), change_counter(self.root))
        real = core_params.ParameterStore.create
        calls: list[str] = []

        def failing(store: Any, conn: Any, name: str, *args: Any, **kwargs: Any) -> Any:
            calls.append(name)
            if len(calls) == 7:
                raise RuntimeError("falla a mitad")
            return real(store, conn, name, *args, **kwargs)

        with mock.patch.object(core_params.ParameterStore, "create", failing), self.assertRaises(RuntimeError):
            entity_store.bring_entities(self.project, "V01", target.code)
        self.assertEqual(len(calls), 7)
        self.assertEqual((self.version_rows(target), self.written(), change_counter(self.root)), before)
        found = entity_store.bring_entities(self.project, "V01", target.code, codes="PLT-003")  # un código suelto
        self.assertEqual(codes(found), [("PLT-003", "PLT-003")])
        self.assertEqual(len(entity_store.bring_entities(self.project, "V01", target.code).entities), 4)

    # --- (h) La superficie de apoyo y lo CALCULADO -----------------------------------------------

    def test_h_the_support_surface_follows_the_codes_and_what_was_calculated_is_brought_as_adopted(self) -> None:
        """RF-015-18: la superficie de apoyo (``support``) sigue las mismas reglas que la partida: la de una entidad que
        se trae pasa a su código nuevo y la de un dato de V01 queda sin valor, con su aviso; y un parámetro que en V01
        es CALCULADO (la persona adoptó una cifra) llega como ADOPTADO con su valor y se dice en su motivo: la cifra
        de V01 no se trae."""
        store = core_params.ParameterStore(self.project)
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            store.create(conn, key("PLT-003", "support"), "entity:PLT-001", kind="ADOPTADO", source=WHY,
                         source_kind="person", decided_by=USER, reason=WHY, version=self.v1.uid)
            store.create(conn, key("PLT-002", "support"), PSF_LOADING, kind="ADOPTADO", source=WHY,
                         source_kind="person", decided_by=USER, reason=WHY, version=self.v1.uid)
            conn.execute("UPDATE gb_parameter SET kind = 'CALCULADO', source_kind = 'operation', operation_uid = "
                         "(SELECT uid FROM gb_operation ORDER BY fid LIMIT 1) WHERE key = ? AND scope_uid = ?",
                         (key("PLT-001", "reach_m"), self.v1.uid))
        target = create_version(self.project, feature="Apoyo", title="Con apoyo")
        found = entity_store.bring_entities(self.project, "V01", target.code, codes=["PLT-001", "PLT-002", "PLT-003"])
        self.assertEqual({item.source_code: (item.start, item.support) for item in found.entities},
                         {"PLT-001": (prep.START, None), "PLT-002": ("entity:PLT-001", None),
                          "PLT-003": ("entity:PLT-002", "entity:PLT-001")})
        lost = [notice for notice in found.notices if notice.code == "des.entity_bring_support_lost"]
        self.assertEqual([(notice.values["name"], notice.values["surface"]) for notice in lost],
                         [(OVER, PSF_LOADING)])
        self.assertIn("su superficie de apoyo", lost[0].text("es"))
        reach = self.record("PLT-001", "reach_m", target)
        self.assertEqual((reach.value, str(reach.kind)), (self.record("PLT-001", "reach_m", self.v1).value, "ADOPTADO"))
        (entry,) = self.history("PLT-001", "reach_m", target)
        self.assertEqual(entry.reason, "Traído de V01.r1; era CALCULADO en V01: se trae su valor, no la cifra")
        (entry,) = self.history("PLT-003", "support", target)
        self.assertEqual(entry.reason, "Traído de V01.r1", "el código de PLT-001 no cambia: nada que decir")


# ---------------------------------------------------------------------------------------------
# Calcularlas de nuevo: la dependencia se detecta otra vez (CE-015-01)
# ---------------------------------------------------------------------------------------------


class BroughtCalculatedTest(sup.SupportsCase):
    """RF-015-18, RF-015-15, CE-015-01, D-18: P1 y P2 (que parte de la superficie de P1 y se apoya en ella con 8.000 m³)
    de V01 se traen a V02, quedan sin calcular y, al calcularlas allí (``platform_run`` con su código), **la dependencia se
    detecta de nuevo**."""

    first: ClassVar[Any]
    second: ClassVar[Any]
    found: ClassVar[Any]
    masks_v2: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.first = cls.made(prep.request())
        cls.second = cls.made(sup.over())
        cls.clock.advance(minutes=1)
        cls.found = entity_store.bring_entities(cls.project, "V01", "V02")
        cls.clock.advance(minutes=1)
        for _step in access.ensure_masks_steps(cls.project, cls.v2.uid):
            pass
        cls.masks_v2 = access.load_masks(cls.project, cls.v2.uid)

    def states(self) -> dict[str, Any]:
        return {entry.record.code: entry.record.state for entry in entities.registry(self.project, self.v2.uid)}

    def test_a_they_are_brought_without_a_calculation_and_without_the_dependency(self) -> None:
        """RF-015-18, CE-015-01: en V02, P1 y P2 salen «sin calcular»: la partida de P2 es la superficie de P1 de V02,
        y nada se apoya en nada todavía (ningún dato ni ninguna cifra en V02)."""
        self.assertEqual([(item.source_code, item.code) for item in self.found.entities],
                         [("PLT-001", "PLT-001"), ("PLT-002", "PLT-002")])
        self.assertEqual(self.states(), {"PLT-001": EntityState.UNCALCULATED, "PLT-002": EntityState.UNCALCULATED})
        self.assertEqual(entities.registry(self.project, self.v2.uid).get("PLT-002").record.start, "entity:PLT-001")
        self.assertEqual(self.query("SELECT count(*) FROM gb_dataset WHERE version_uid = ? AND name LIKE 'des!_%' "
                                    "ESCAPE '!'", self.v2.uid), [(0,)])

    def test_b_calculating_them_in_the_new_version_detects_the_dependency_again(self) -> None:
        """RF-015-18, RF-015-15, CE-015-01: se calcula y se crea P1 en V02 (con su código: no escribe otra vez sus
        parámetros) y luego P2: su operación anota la superficie de P1 de V02 como ``supported_on`` y la tabla de su
        huella, y la cifra ``des.supported_m3`` con el ámbito de PLT-001 **vale lo mismo que en V01** (8.000 m³ a
        mano); ambas quedan al día y P2 aparece en lo que se apoya en P1 de V02; lo de V01 no se toca."""
        v1_ops = self.query("SELECT uid, status, superseded_by FROM gb_operation WHERE uid IN (?, ?) ORDER BY uid",
                            self.first.handle.uid, self.second.handle.uid)
        rows = self.query("SELECT key, rev FROM gb_parameter WHERE scope = 'version' AND scope_uid = ? ORDER BY key",
                          self.v2.uid)
        self.clock.advance(minutes=1)
        first = self.calculate_in(prep.request(), version=self.v2.uid, masks=self.masks_v2, code="PLT-001").create()
        self.clock.advance(minutes=1)
        second = self.calculate_in(sup.over(), version=self.v2.uid, masks=self.masks_v2, code="PLT-002").create()
        self.assertEqual(self.states(), {"PLT-001": EntityState.CURRENT, "PLT-002": EntityState.CURRENT})
        self.assertEqual(self.supports_of(first.handle.uid), [])
        uid = second.handle.uid
        self.assertEqual(self.supports_of(uid), [(sup.PSF1, "supported_on"), (sup.EPR1, "support_footprint")])
        again, before = self.volumes_of(uid), self.volumes_of(self.second.handle.uid)
        self.assertEqual(list(again), ["PLT-001"])
        self.assertLessEqual(abs(again["PLT-001"] - sup.OVER_VOLUME_M3) / sup.OVER_VOLUME_M3, 1e-9)
        self.assertLessEqual(abs(again["PLT-001"] - before["PLT-001"]) / before["PLT-001"], 1e-9,
                             "lo apoyado en V02 es lo mismo que lo apoyado en V01")
        listed = entities.dependents(self.project, self.v2.uid, "PLT-001")
        self.assertEqual([(row.name, set(row.roles)) for row in listed], [(sup.OVER, {"surface", "supported_on"})])
        self.assertEqual(self.query("SELECT uid, status, superseded_by FROM gb_operation WHERE uid IN (?, ?) "
                                    "ORDER BY uid", self.first.handle.uid, self.second.handle.uid), v1_ops)
        self.assertEqual(self.query("SELECT key, rev FROM gb_parameter WHERE scope = 'version' AND scope_uid = ? "
                                    "ORDER BY key", self.v2.uid), rows,
                         "calcular lo traído no reescribe sus parámetros")


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: GPL-3.0-or-later
"""La declaración de restricciones de las entidades (spec 015, T17; HU-015-1; RF-015-10, RF-015-12,
RF-012-29, RF-012-02; plan 015 §5.2.3, §5.3.2, §5.4 A8, P-7 y P-8; ADR-0030; D-19, D-21).

``des.declare_constraints`` es la operación de la **versión** que pone en ``des_decl_<vNN>`` una restricción
por cada entidad viva que protege (``protect``), de tipo «sin relleno», con el contorno de su huella
(``des_epr_``) y su resguardo (``guard_m``, obligatorio si protege: D-19), el motivo generado «declarada por la
plataforma P1» o el que editó la persona, como decisor quien creó o cambió la entidad y la fecha **de esa
decisión** (nunca la de ahora, para que repetir no cambie el hash). Sobre la cantera sintética de la 014 con las
capas de plataformas (``tests.support.entity_fixtures``) y su rejilla gruesa de 2 m:

- **La declaración** (:class:`DeclareTest`): crear una entidad que protege pone su restricción (con todo lo de
  RF-012-02 y RF-012-29, un contorno que pasa las comprobaciones de la 012 y las entradas, los parámetros, la
  cifra y el dato de la operación); repetirla da el mismo hash; cambiar el resguardo, el motivo o la protección
  la cambia o la quita (la obsolescencia deja la operación para «Recalcular lo obsoleto»); descartar la entidad
  la quita; una entidad sin calcular no declara; sin entidades que protejan, la tabla queda vacía.
- **Los rechazos** (:class:`RefusalTest`): proteger sin resguardo (D-19) y proteger en «corte y relleno»
  (RF-015-12) se rechazan con la entidad, el campo y el valor y sin escribir nada; sin versión editable, no se
  declara (RF-009-21).
- **Reproducir** (:class:`ReproduceTest`): la declaración congelada se reproduce desde lo congelado con el
  mismo hash y las mismas cifras (RF-015-02, RF-009-11), también tras cambiar lo vivo.
"""

from __future__ import annotations

import json
import unittest
from datetime import date, datetime
from typing import Any, ClassVar

from tests.support.package import import_geoblender
from tests.support.versions_fixtures import change_counter, files
from tests.unit.design import test_platform_operation as ops
from tests.unit.design import test_platform_prepare as prep

access = import_geoblender("gis.masks.access")
combine = import_geoblender("gis.masks.combine")
polygons = import_geoblender("gis.polygons")
core_params = import_geoblender("core.params")
declared_mod = import_geoblender("core.constraints.declared")
constraint_model = import_geoblender("core.constraints.model")
constraint_params = import_geoblender("core.constraints.params")
design_params = import_geoblender("design.params")
design_reproduce = import_geoblender("design.reproduce")
design_store = import_geoblender("design.store")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
contract = import_geoblender("core.provenance.contract")
freeze = import_geoblender("core.versions.freeze")
masks_provenance = import_geoblender("gis.masks.provenance")
masks_store = import_geoblender("gis.masks.store")
messages = import_geoblender("design.messages")
provenance = import_geoblender("design.provenance")
recompute_mod = import_geoblender("core.provenance.recompute")
reproduce_mod = import_geoblender("core.versions.reproduce")
versions_model = import_geoblender("core.versions.model")

LOADING, WORKSHOP = prep.LOADING, prep.WORKSHOP
DECLARE = provenance.DECLARE_CONSTRAINTS
TABLE = "des_decl_v01"
GUARD_M = 4.0
USER = "Samuel (IMGA)"
EDITOR = "Ana (IMGA)"
DAY_MINUTES = 24 * 60
NO_SCOPE = "{}"
"""El ámbito de una cifra sin ámbito en ``gb_figure`` (un objeto JSON vacío): hay una declaración por versión."""


def declare_definitions() -> tuple[Any, ...]:
    """Los tipos de las entidades con las funciones **reales** de la plataforma, de la declaración y de la capa de
    entidades (recalcular; la capa de entidades no se reproduce: T30) y de reproducir las de la plataforma y la
    declaración, y las cifras, como los registra ``bl``."""
    types = prep.ENTITY_TYPES
    recompute = dict.fromkeys(types, ops.recompute_function)
    reproduce = {kind: prep.never for kind in provenance.ENTITY_REPRODUCIBLE}
    reproduce[provenance.PLATFORM] = design_reproduce.reproduce_platform
    reproduce[DECLARE] = design_reproduce.reproduce_declare_constraints
    return (*provenance.entity_operation_defs(recompute, reproduce), *provenance.ENTITY_FIGURES)


def guard_key(code: str) -> str:
    return design_params.entity_key(code, "guard_m")


def protect_key(code: str) -> str:
    return design_params.entity_key(code, "protect")


def reason_key(code: str) -> str:
    return design_params.entity_key(code, "reason")


def compile_recompute(request: Any) -> Any:
    """Lo que registra ``bl`` como función de recálculo de ``gis.compile_constraints``: lleva sus pasos hasta
    el final."""
    handle, work = masks_store.recompute_run(request)
    ops.finish(work)
    return handle


def real_compile_registered(case: type[Any]) -> None:
    """Registra la compilación de las máscaras con **su recálculo real** (el de las pruebas de la 012 se niega a
    recalcular) mientras dura la clase ``case``; al salir, deja la que había (T19: desde el hueco H-1, recalcular
    una entidad que protege compila las máscaras, y «Recalcular lo obsoleto» las repite)."""
    old = contract.OPERATIONS[masks_provenance.COMPILE]
    contract.unregister_operation(masks_provenance.COMPILE)
    contract.register_operation(masks_provenance.operation_def(compile_recompute,
                                                               masks_store.REPRODUCE[masks_provenance.COMPILE]))

    def restore() -> None:
        contract.unregister_operation(masks_provenance.COMPILE)
        contract.register_operation(old)

    case.addClassCleanup(restore)


class DeclareCase(ops.RecomputeCase):
    """Lo de ``RecomputeCase`` con la declaración registrada con sus funciones reales (y la compilación de las
    máscaras con su recálculo real) y los ayudantes de las pruebas de esta tarea: declarar, leer la tabla y la
    operación vigente y cambiar o crear los parámetros de una entidad (cada cosa, un minuto después de la
    anterior)."""

    @classmethod
    def definitions(cls) -> tuple[Any, ...]:
        return declare_definitions()

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        real_compile_registered(cls)

    @classmethod
    def settle(cls, rounds: int = 12) -> list[Any]:
        """«Recalcular lo obsoleto» **tantas veces como haga falta** (T19): desde el hueco H-1 una entidad que
        protege cierra el ciclo entidad → declarada → máscaras → entidad (D-21) y cada pasada rehace una sola
        unidad (lo recalculado que vuelve a quedar obsoleto espera, RF-008-27). Devuelve las unidades hechas, en
        orden; se para en cuanto no queda nada que recalcular."""
        results: list[Any] = []
        for _ in range(rounds):
            cls.clock.advance(minutes=1)
            done = ops.finish(recompute_mod.recompute_steps(cls.project))
            results.extend(done.results)
            if not done.remaining.units:
                break
        return results

    @classmethod
    def entities_declared(cls) -> None:
        """Lo que sigue a la orden de una entidad (``after_entity_change``: declarar y compilar las máscaras con lo
        declarado) y «Recalcular lo obsoleto» hasta que no quede nada obsoleto: el punto de partida de quien mira
        lo que pasa **después** (el ciclo ya resuelto)."""
        cls.clock.advance(minutes=1)
        ops.finish(entity_store.after_entity_change(cls.project, cls.v1))
        cls.settle()

    @classmethod
    def declare(cls, version: Any = None) -> Any:
        """«Declarar» las restricciones de ``version`` (por defecto V01) hasta el final: el ``Stored``."""
        cls.clock.advance(minutes=1)
        return ops.finish(entity_store.declare_constraints_steps(
            cls.project, cls.v1 if version is None else version))

    @classmethod
    def declared(cls, version: Any = None) -> tuple[Any, ...]:
        """Las restricciones declaradas de ``version`` (por defecto V01), por ``fid``."""
        target = cls.v1 if version is None else version
        with cls.project.read() as conn:
            return declared_mod.read_declared(conn, declared_mod.declared_table(target.code))

    @classmethod
    def declared_dump(cls, version: Any = None) -> list[tuple[Any, ...]]:
        """Todo el contenido de la tabla de las declaradas, tal cual (bytes de la geometría incluidos)."""
        target = cls.v1 if version is None else version
        with cls.project.read() as conn:
            return conn.execute(f'SELECT * FROM "{declared_mod.declared_table(target.code)}" '
                                'ORDER BY fid').fetchall()

    @classmethod
    def record_of(cls, version: Any = None) -> Any:
        """El dato ``des_decl`` de ``version`` (por defecto V01)."""
        target = cls.v1 if version is None else version
        with cls.project.read() as conn:
            return import_geoblender("core.datasets.registry").get(conn, "des_decl",
                                                                   version_uid=target.uid)

    @classmethod
    def current_declaration(cls) -> str:
        """El uid de la operación de declaración vigente de V01 (hecha y sin sustituir)."""
        found = cls.query_of("SELECT o.uid FROM gb_operation AS o JOIN gb_revision AS r ON "
                             "r.uid = o.revision_uid WHERE r.version_uid = ? AND o.op_type = ? "
                             "AND o.status = 'done' AND o.superseded_by IS NULL ORDER BY o.fid",
                             cls.v1.uid, DECLARE)
        assert len(found) == 1, found
        return str(found[0][0])

    @classmethod
    def declaration_request(cls, uid: str) -> Any:
        """Lo que recibe ``bl`` para recalcular la declaración ``uid``: sus ajustes y su versión."""
        ((settings,),) = cls.query_of("SELECT settings FROM gb_operation WHERE uid = ?", uid)
        return recompute_mod.RecomputeRequest(cls.project, uid, DECLARE, json.loads(settings), (), (),
                                              version=cls.v1.uid)

    @classmethod
    def create_param(cls, key: str, value: object, *, who: str = USER, reason: str = "Prueba de la T17"
                     ) -> None:
        """Da de alta el parámetro ``key`` (de la versión V01) con ``value``: lo que el diálogo de la entidad
        escribe la primera vez que la persona fija un resguardo o edita el motivo."""
        cls.clock.advance(minutes=1)
        param = key.rsplit(".", 1)[1]
        with cls.project.write_transaction() as conn:
            core_params.ParameterStore(cls.project).create(
                conn, key, value, kind=design_params.PLATFORM_PARAMS[param].kind,
                source="Diálogo de la entidad", source_kind="person", decided_by=who, reason=reason,
                version=cls.v1.uid)

    @classmethod
    def change_as(cls, key: str, value: object, who: str) -> None:
        """Cambia el parámetro ``key`` de V01, decidido por ``who``."""
        cls.clock.advance(minutes=1)
        with cls.project.write_transaction() as conn:
            core_params.ParameterStore(cls.project).change(
                conn, key, value=value, version=cls.v1.uid, decided_by=who, reason="Prueba de la T17")

    @classmethod
    def entity_runs(cls, code: str) -> list[tuple[int, int, int]]:
        """Los tramos de la huella de la entidad ``code`` de V01, de su tabla ``des_epr_`` vigente."""
        entry = entities.registry(cls.project, cls.v1.uid).get(code)
        assert entry is not None and entry.operation_uid is not None, code
        (locator,) = cls.query_of(
            "SELECT d.locator FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'out' AND io.role = 'entity'",
            entry.operation_uid)[0]
        ((footprint,),) = cls.query_of(f'SELECT footprint FROM "{locator}"')
        return [tuple(run) for run in json.loads(footprint)]

    @classmethod
    def revision(cls) -> str:
        """La revisión abierta de V01."""
        return str(cls.query_of("SELECT uid FROM gb_revision WHERE version_uid = ? AND state = 'open'",
                                cls.v1.uid)[0][0])

    def declare_plan(self) -> list[tuple[str, ...]]:
        """Las unidades de «Recalcular lo obsoleto» que son la **declaración** (T19): desde el hueco H-1, recalcular
        una entidad que protege compila las máscaras con su zona (la declaración vigente no la consumían) y deja
        obsoletas las operaciones que las usaron (el ciclo entidad → declarada → máscaras → entidad, D-21): lo
        que estas pruebas miran es la obsolescencia **de la declaración**, no la de ellas."""
        return [unit for unit in self.recompute_plan() if unit == (DECLARE,)]

    def entity_datasets(self) -> dict[str, str]:
        """El hash de contenido de cada dato de ``des_epr_`` y de ``des_psf_`` de V01, por su nombre."""
        return dict(self.query("SELECT name, content_sha256 FROM gb_dataset WHERE (name LIKE 'des!_epr!_%' "
                               "ESCAPE '!' OR name LIKE 'des!_psf!_%' ESCAPE '!') AND status = 'current' "
                               "ORDER BY name"))


# ---------------------------------------------------------------------------------------------
# La declaración
# ---------------------------------------------------------------------------------------------


class DeclareTest(DeclareCase):
    """RF-015-10, RF-012-29, RF-012-02: P1 (la «Plataforma de carga», que no protege) y P2 (la «Plataforma
    de taller», de la superficie de P1, que protege con 4 m de resguardo en el modo «en corte») creadas en V01
    y declaradas, por el orden de los nombres de las pruebas: (a) lo que declara, (b) cambiar el resguardo,
    (c) editar el motivo, (d) retirar la protección y (e) descartar la entidad."""

    created_on: ClassVar[date]
    day_later: ClassVar[date]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())
        cls.clock.advance(minutes=1)
        cls.made(prep.request(WORKSHOP, start="entity:PLT-001", protect=True, guard_m=GUARD_M))
        cls.created_on = cls.clock.now().date()
        # T19: desde el hueco H-1, lo que sigue a crear una entidad que protege declara y compila las máscaras con
        # su zona (el ciclo D-21, que «Recalcular lo obsoleto» resuelve): las pruebas de abajo miran lo que pasa
        # con la declaración **después**, con las máscaras ya al día.
        cls.entities_declared()
        assert cls.clock.now().date() == cls.created_on
        cls.clock.advance(minutes=5 * DAY_MINUTES)  # declarar cinco días después: la fecha no es la de ahora
        assert cls.clock.now().date() != cls.created_on

    # --- (a) Lo que declara -----------------------------------------------------------------------

    def test_a1_one_restriction_per_entity_that_protects_with_what_the_012_asks(self) -> None:
        """RF-015-10, RF-012-02, RF-012-29: la declaración pone **una** restricción (la de P2, que protege; la
        de P1, no) con su código ``dec__plt_002`` (válido para la 012), «sin relleno», el nombre de la
        entidad, el motivo generado, quien creó la entidad como decisor, la fecha **en que se creó** (no la de
        ahora), la entidad como origen, el resguardo de la entidad, «activa» y la prioridad constante; su
        contorno es el de su huella con su resguardo y pasa las comprobaciones de la 012."""
        self.declare()
        (found,) = self.declared()
        self.assertEqual(found.code, declared_mod.declared_code("PLT-002"))
        self.assertTrue(constraint_model.is_code(found.code))
        self.assertEqual(found.ctype, constraint_model.ConstraintType.NO_FILL)
        self.assertEqual((found.name, found.entity_code, found.entity_name),
                         (WORKSHOP, "PLT-002", WORKSHOP))
        self.assertEqual(found.reason, entities.declared_reason(entities.EntityKind.PLATFORM, WORKSHOP))
        self.assertEqual(found.reason, f"declarada por la plataforma {WORKSHOP}")
        self.assertEqual((found.decided_by, found.decided_on), (self.project.session.user_host,
                                                                self.created_on))
        self.assertNotEqual(found.decided_on, self.clock.now().date())
        self.assertEqual((found.buffer_out_m, found.active, found.priority),
                         (GUARD_M, True, declared_mod.DECLARED_PRIORITY))
        self.assertEqual(found.uid, declared_mod.declared_uid(self.v1.uid, "PLT-002"))
        self.assertEqual((found.layer, found.fid), (TABLE, 1))
        zone = entities.declared_zone_of_runs(self.entity_runs("PLT-002"), self.grid, GUARD_M)
        self.assertEqual(len(found.parts), len(zone.parts))
        for mine, theirs in zip(found.parts, zone.parts, strict=True):
            self.assertEqual(len(mine), len(theirs))
            for got, expected in zip(mine, theirs, strict=True):
                self.assertEqual(got.tobytes(), expected.tobytes())
        self.assertEqual(polygons.drain(combine._geometry_problems_steps(found.as_constraint())), ())
        self.assertEqual(found.as_constraint().param_key(constraint_model.ConstraintParam.BUFFER_OUT),
                         "core.constraint.dec__plt_002.buffer_out_m")
        self.assertEqual(constraint_params.param_key(found.code, constraint_model.ConstraintParam.ACTIVE),
                         "core.constraint.dec__plt_002.active")

    def test_a2_the_operation_records_its_inputs_parameters_figure_and_data(self) -> None:
        """RF-015-10, RF-015-02: la operación ``des.declare_constraints`` de V01 consume el ``des_epr_`` **de
        las entidades vivas calculadas que protegen** (papel ``entity``: solo P2; T26, plan 015 §5.2.3: antes
        eran las de todas, P1 incluida), lee ``name`` y ``protect`` de cada una (P1 y P2) y, de la que protege,
        ``mode`` y ``guard_m`` (no el motivo: sin editar no hay fila), escribe ``des_decl_v01`` (``des_decl``, el
        papel de lo que consume la compilación de la 012, una capa de polígonos no editable en QGIS), la cifra
        ``des.declared_count`` y deja en sus ajustes **la entidad que declara** con su decisor y la fecha de la
        decisión, la versión y el mensaje."""
        uid = self.current_declaration()
        self.assertEqual(self.query("SELECT op_type, status, executor FROM gb_operation WHERE uid = ?", uid),
                         [(DECLARE, "done", "blender")])
        self.assertEqual(self.query("SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d "
                                    "ON d.uid = io.item_uid WHERE io.operation_uid = ? "
                                    "AND io.direction = 'in' ORDER BY io.fid", uid),
                         [(provenance.dataset_name(provenance.ENTITY_TABLE, WORKSHOP), "entity")])
        self.assertEqual({key for (key,) in self.query(
            "SELECT key FROM gb_operation_param WHERE operation_uid = ?", uid)},
            set(provenance.declare_params(["PLT-001", "PLT-002"], protecting=["PLT-002"])))
        self.assertEqual(self.figures_of(uid), {("des.declared_count", NO_SCOPE): 1.0})
        self.assertEqual(self.query("SELECT d.name, d.locator, d.kind, d.store, io.role FROM gb_operation_io AS "
                                    "io JOIN gb_dataset AS d ON d.uid = io.item_uid WHERE io.operation_uid = ? "
                                    "AND io.direction = 'out'", uid),
                         [("des_decl", TABLE, "vector", "gpkg", "constraints_declared")])
        record = self.record_of()
        self.assertEqual((record.operation_uid, record.qgis_editable, record.crs_epsg),
                         (uid, False, self.project.record.crs_epsg))
        self.assertRegex(record.content_sha256, r"^[0-9a-f]{64}$")
        ((settings, message),) = self.query("SELECT settings, message FROM gb_operation WHERE uid = ?", uid)
        found = json.loads(settings)
        self.assertEqual(provenance.settings_entities(found), (("PLT-002", WORKSHOP),))
        self.assertEqual(provenance.settings_decisions(found),
                         {"PLT-002": (self.project.session.user_host, self.created_on)})
        self.assertEqual(provenance.settings_version(found), self.v1.uid)
        self.assertIn("1", message)

    def test_a3_declaring_does_not_modify_what_it_reads_nor_the_project_layers(self) -> None:
        """RF-015-10, RF-012-29: la declaración no toca los datos de las entidades (sus ``des_epr_`` y
        ``des_psf_``, mismo hash) ni escribe nada en las capas de restricciones del proyecto (RF-012-29: «NO
        DEBERÁ guardarla en la capa de restricciones del proyecto»), y la tabla de V01 no está en V02."""
        before = self.entity_datasets()
        layers = self.query("SELECT name, content_sha256 FROM gb_dataset WHERE name LIKE 'core!_constraint%' "
                            "ESCAPE '!' ORDER BY name")
        self.assertTrue(before)
        self.declare()
        self.assertEqual(self.entity_datasets(), before)
        self.assertEqual(self.query("SELECT name, content_sha256 FROM gb_dataset WHERE name LIKE "
                                    "'core!_constraint%' ESCAPE '!' ORDER BY name"), layers)
        with self.project.read() as conn:
            codes = {row[0] for row in conn.execute(
                "SELECT code FROM core_constraint_polygon UNION SELECT code FROM core_constraint_line "
                "UNION SELECT code FROM core_constraint_point")}
        self.assertNotIn(declared_mod.declared_code("PLT-002"), codes)
        self.assertEqual(self.declared(self.v2), ())

    def test_a4_declaring_again_gives_the_same_table_and_hash_and_supersedes_the_previous(self) -> None:
        """RF-015-10, A8: el mismo contenido de entidades da la misma tabla, byte a byte, y el mismo hash
        (el ``uid`` y la fecha son deterministas): repetir la declaración, **cinco días después** y con otra
        hora, la sustituye (queda como historia) y no cambia nada de lo declarado."""
        previous = self.current_declaration()
        dump, digest = self.declared_dump(), self.record_of().content_sha256
        self.clock.advance(minutes=3 * DAY_MINUTES)
        self.declare()
        again = self.current_declaration()
        self.assertNotEqual(again, previous)
        self.assertEqual(self.query("SELECT superseded_by FROM gb_operation WHERE uid = ?", previous),
                         [(again,)])
        self.assertEqual(self.declared_dump(), dump)
        self.assertEqual(self.record_of().content_sha256, digest)
        self.assertEqual(self.query("SELECT COUNT(*) FROM gb_dataset WHERE name = 'des_decl'"), [(1,)])

    def test_a5_recomputing_the_entity_and_the_declaration_does_not_change_the_hash(self) -> None:
        """RF-015-10, RF-008-26, A8: recalcular P2 (otra operación que da los mismos datos) y la declaración
        con ``recompute_run`` (la función que registra ``bl``) deja la misma tabla y el mismo hash: la
        compilación de las máscaras no se queda obsoleta por recalcular."""
        digest, dump = self.record_of().content_sha256, self.declared_dump()
        self.clock.advance(minutes=2 * DAY_MINUTES)
        ops.recompute_function(self.request_for(self.current("PLT-002")))
        self.declare()
        self.assertEqual(self.record_of().content_sha256, digest)
        previous = self.current_declaration()
        self.clock.advance(minutes=1)
        handle = ops.recompute_function(self.declaration_request(previous))
        self.assertEqual((handle.op_type, handle.supersedes), (DECLARE, previous))
        self.assertEqual(self.current_declaration(), str(handle.uid))
        self.assertEqual(self.record_of().content_sha256, digest)
        self.assertEqual(self.declared_dump(), dump)
        self.assertEqual(self.declare_plan(), [])

    # --- (b) Cambiar el resguardo -----------------------------------------------------------------

    def test_b_changing_the_guard_changes_the_restriction_and_the_date_of_the_decision(self) -> None:
        """RF-015-10, RF-015-16: cambiar el resguardo de P2 (de otra persona, otro día) deja obsoleta la
        declaración, con la causa (el parámetro), y «Recalcular lo obsoleto» la repite: la restricción lleva
        el resguardo nuevo, a quien lo cambió como decisor y **la fecha del cambio**; la tabla y su hash
        cambian."""
        digest, dump = self.record_of().content_sha256, self.declared_dump()
        self.clock.advance(minutes=DAY_MINUTES)
        self.change_as(guard_key("PLT-002"), 6.0, EDITOR)
        changed_on = self.clock.now().date()
        self.assertGreater(changed_on, self.created_on)
        self.assertEqual(self.stale_causes(self.current_declaration()),
                         {("parameter_changed", guard_key("PLT-002"))})
        self.assertEqual(self.declare_plan(), [(DECLARE,)])
        self.clock.advance(minutes=1)
        done = self.settle()  # el ciclo entidad → declarada → máscaras → entidad: varias pasadas (T19, D-21)
        self.assertTrue(done and all(result.status is recompute_mod.UnitStatus.DONE for result in done), done)
        self.assertIn((DECLARE,), [tuple(self.query("SELECT op_type FROM gb_operation WHERE uid = ?", uid)[0][0]
                                         for uid in result.unit.operations) for result in done])
        (found,) = self.declared()
        self.assertEqual((found.buffer_out_m, found.decided_by, found.decided_on),
                         (6.0, EDITOR, changed_on))
        self.assertNotEqual(self.record_of().content_sha256, digest)
        self.assertNotEqual(self.declared_dump(), dump)
        self.assertEqual(self.declare_plan(), [])

    # --- (c) Editar el motivo ---------------------------------------------------------------------

    def test_c_editing_the_reason_declares_the_edited_one_and_a_change_to_it_stales_the_declaration(self) -> None:
        """RF-015-10: la persona edita el motivo en la entidad (el parámetro ``reason``, sin fila hasta
        entonces): la declaración siguiente lo lleva en lugar del generado, con quien lo editó como decisor, y
        desde entonces lee ese parámetro: cambiarlo otra vez deja obsoleta la declaración y recalcularla pone
        el nuevo."""
        self.create_param(reason_key("PLT-002"), "Acopio de áridos del cliente", who=EDITOR)
        edited_on = self.clock.now().date()
        self.declare()
        (found,) = self.declared()
        self.assertEqual((found.reason, found.decided_by, found.decided_on),
                         ("Acopio de áridos del cliente", EDITOR, edited_on))
        self.assertIn(reason_key("PLT-002"), {key for (key,) in self.query(
            "SELECT key FROM gb_operation_param WHERE operation_uid = ?", self.current_declaration())})
        self.change_as(reason_key("PLT-002"), "Zona de pistas protegida", USER)
        self.assertEqual(self.declare_plan(), [(DECLARE,)])
        self.clock.advance(minutes=1)
        self.settle()
        (found,) = self.declared()
        self.assertEqual((found.reason, found.decided_by), ("Zona de pistas protegida", USER))
        self.assertEqual(self.declare_plan(), [])

    # --- (d) Retirar la protección ----------------------------------------------------------------

    def test_d_retiring_the_protection_removes_the_restriction_and_putting_it_back_restores_it(self) -> None:
        """RF-015-10: P2 deja de proteger (``protect`` falso): la tabla se reescribe **entera** y su
        restricción **sale** (la tabla queda vacía, pero existe y la operación es válida: la compilación de
        las máscaras la necesita) con la cifra ``des.declared_count`` a 0; al proteger otra vez vuelve, con el
        mismo ``uid``."""
        uid_before = declared_mod.declared_uid(self.v1.uid, "PLT-002")
        self.change_as(protect_key("PLT-002"), False, USER)
        self.assertEqual(self.declare_plan(), [(DECLARE,)])
        self.clock.advance(minutes=1)
        self.settle()
        self.assertEqual(self.declared(), ())
        with self.project.read() as conn:
            self.assertEqual(conn.execute("SELECT name FROM sqlite_master WHERE name = ?", (TABLE,)
                                          ).fetchall(), [(TABLE,)])
        self.assertEqual(self.figures_of(self.current_declaration()), {("des.declared_count", NO_SCOPE): 0.0})
        self.assertEqual(self.record_of().operation_uid, self.current_declaration())
        self.change_as(protect_key("PLT-002"), True, USER)
        self.clock.advance(minutes=1)
        self.settle()
        (found,) = self.declared()
        self.assertEqual((found.uid, found.entity_code), (uid_before, "PLT-002"))

    # --- (e) Descartar la entidad -----------------------------------------------------------------

    def test_e_discarding_the_entity_removes_its_restriction(self) -> None:
        """RF-015-10, RF-015-25: una entidad descartada **no está viva** (sus datos descartados, nada se
        borra): su restricción sale de la tabla y su dato ya no es una entrada de la declaración (T26: la
        declaración se queda **sin entradas**, porque P1, la única que queda, no protege)."""
        self.assertEqual(len(self.declared()), 1)
        dataset_registry = import_geoblender("core.datasets.registry")
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            for family in ("psf", "epr", "prp"):
                found = dataset_registry.get(
                    conn, provenance.dataset_name(family, WORKSHOP), version_uid=self.v1.uid)
                dataset_registry.set_status(conn, self.project, found.uid, "discarded")
        self.assertEqual(entities.registry(self.project, self.v1.uid).get("PLT-002").record.state,
                         entities.EntityState.DISCARDED)
        self.declare()
        self.assertEqual(self.declared(), ())
        self.assertEqual([name for (name,) in self.query(
            "SELECT d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'in'", self.current_declaration())], [])
        self.assertEqual(self.figures_of(self.current_declaration()), {("des.declared_count", NO_SCOPE): 0.0})

    def test_f_an_entity_without_a_calculation_does_not_declare(self) -> None:
        """RF-015-10, RF-015-18: una entidad con parámetros y sin operación («sin calcular», la que deja
        «Traer las entidades de…») no declara nada aunque proteja: no tiene huella; ni es entrada de la
        declaración."""
        prepared = prep.drive(entity_store.prepare_platform_units(
            self.project, prep.request("Plataforma de la torre", start="gis_dtm_borde", protect=True,
                                       guard_m=GUARD_M), self.v1, self.masks_v1))
        self.clock.advance(minutes=1)
        entity_store.set_entity_params(self.project, prepared.rows, version=self.v1.uid)
        entry = entities.registry(self.project, self.v1.uid).get(prepared.code)
        self.assertEqual(entry.record.state, entities.EntityState.UNCALCULATED)
        self.declare()
        self.assertEqual(self.declared(), ())
        self.assertNotIn(prepared.code, [pair[0] for pair in provenance.settings_entities(json.loads(
            self.query("SELECT settings FROM gb_operation WHERE uid = ?", self.current_declaration())[0][0]))])

    def test_g_another_version_has_its_own_empty_table(self) -> None:
        """RF-012-29: la declarada es de su versión: declarar V02, que no tiene entidades, da su propia
        tabla (``des_decl_v02``, vacía) y no toca la de V01."""
        dump = self.declared_dump()
        self.clock.advance(minutes=1)
        ops.finish(entity_store.declare_constraints_steps(self.project, self.v2))
        self.assertEqual(self.declared(self.v2), ())
        with self.project.read() as conn:
            self.assertEqual(conn.execute("SELECT name FROM sqlite_master WHERE name = 'des_decl_v02'"
                                          ).fetchall(), [("des_decl_v02",)])
        self.assertEqual(self.declared_dump(), dump)
        self.assertEqual(self.record_of(self.v2).locator, "des_decl_v02")


# ---------------------------------------------------------------------------------------------
# Solo las que protegen
# ---------------------------------------------------------------------------------------------


class OnlyProtectingTest(DeclareCase):
    """RF-015-10 (plan 015 §5.2.3: «los datos ``des_epr_`` de las entidades vivas **que protegen**»; defecto de la
    T17 que descubrió la T25): la declaración consume solo el ``des_epr_`` de las entidades que protegen, más los
    parámetros ``protect`` de todas las vivas (ya son parámetros de la operación). Una entidad que no protege,
    **retirada o descartada**, no deja obsoleta la declaración (ni, en cascada, las máscaras y lo que las usó);
    una que protege y cambia de huella, sí; cambiar su ``protect``, también.

    V01: P1 (la «Plataforma de carga», no protege), P2 (la «Plataforma de taller», de la superficie de P1, que
    protege con 4 m de resguardo) y una cadena que no protege: P3 (la «Explanada con eje», del terreno con un
    hueco) y P4 (la «Explanada sin eje», de la superficie de P3); por el orden de las pruebas: (a) lo que
    consume, (b) descartar P3, que deja a P4 en «apoyo retirado», (c) descartar P4, (d) cambiar la huella de la
    que protege y (e) cambiar el ``protect`` de una que no protege."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())
        cls.made(prep.request(WORKSHOP, start="entity:PLT-001", protect=True, guard_m=GUARD_M))
        cls.made(prep.polygon_request(prep.WITH_AXIS, start=ops.EDGE_HOLE_DATASET))
        cls.made(prep.polygon_request(prep.NO_AXIS, linked=False, start="entity:PLT-003"))
        cls.entities_declared()

    def discard(self, code: str) -> None:
        """Descarta la entidad ``code`` de V01 (un minuto después de lo anterior): sus datos, ``DISCARDED``."""
        self.clock.advance(minutes=1)
        entity_store.discard_entity(self.project, self.v1.uid, code, reason="Prueba del defecto de la T17",
                                    decided_by=USER)

    def state_of(self, code: str) -> Any:
        return entities.registry(self.project, self.v1.uid).get(code).record.state

    def test_a_the_declaration_consumes_only_what_protects_and_reads_the_protect_of_all(self) -> None:
        """RF-015-10: de las cuatro entidades vivas y calculadas, la declaración consume el ``des_epr_`` **de
        P2** (la única que protege, papel ``entity``), anota solo a P2 en sus ajustes (es lo que se congela y se
        reproduce) y lee ``name`` y ``protect`` de las cuatro y, de P2, ``mode`` y ``guard_m``; nada queda
        obsoleto."""
        uid = self.current_declaration()
        self.assertEqual(self.query("SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d "
                                    "ON d.uid = io.item_uid WHERE io.operation_uid = ? "
                                    "AND io.direction = 'in' ORDER BY io.fid", uid),
                         [(provenance.dataset_name(provenance.ENTITY_TABLE, WORKSHOP), "entity")])
        ((settings,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", uid)
        self.assertEqual(provenance.settings_entities(json.loads(settings)), (("PLT-002", WORKSHOP),))
        codes = [f"PLT-00{number}" for number in range(1, 5)]
        self.assertEqual({key for (key,) in self.query(
            "SELECT key FROM gb_operation_param WHERE operation_uid = ?", uid)},
            set(provenance.declare_params(codes, protecting=["PLT-002"])))
        self.assertEqual(self.stale_causes(uid), set())
        self.assertEqual(self.declare_plan(), [])
        self.assertEqual(len(self.declared()), 1)

    def test_b_one_in_support_removed_or_discarded_that_does_not_protect_leaves_the_declaration_current(
            self) -> None:
        """RF-015-10, RF-015-17: P3 se descarta (sus datos, ``DISCARDED``) y P4, que parte de su superficie,
        queda en «apoyo retirado» (obsoleta y sin poder recalcularse): ninguna protege, así que la declaración
        **sigue al día** —sin causa, fuera del plan de «Recalcular lo obsoleto», la misma operación y la misma
        tabla— y las máscaras con ella (el defecto: los ``des_epr_`` de las que no protegen la dejaban obsoleta
        en cascada, sin motivo)."""
        uid, dump = self.current_declaration(), self.declared_dump()
        self.discard("PLT-003")
        self.assertEqual((self.state_of("PLT-003"), self.state_of("PLT-004")),
                         (entities.EntityState.DISCARDED, entities.EntityState.SUPPORT_REMOVED))
        self.assertEqual(self.stale_causes(uid), set())
        self.assertEqual(self.declare_plan(), [])
        self.assertEqual(self.current_declaration(), uid)
        self.assertEqual(self.declared_dump(), dump)
        state, _pending = access.mask_state(self.project, self.v1.uid)
        self.assertEqual(state, access.MaskState.CURRENT)

    def test_c_discarding_the_one_in_support_removed_leaves_it_current_too(self) -> None:
        """RF-015-10, RF-015-17: P4 (en «apoyo retirado», no protege) se descarta: la declaración sigue al
        día, y volver a declarar (lo que encadena la orden de descartar) da el mismo hash."""
        uid, digest = self.current_declaration(), self.record_of().content_sha256
        self.discard("PLT-004")
        self.assertEqual(self.state_of("PLT-004"), entities.EntityState.DISCARDED)
        self.assertEqual(self.stale_causes(uid), set())
        self.assertEqual(self.declare_plan(), [])
        self.declare()
        self.assertEqual(self.record_of().content_sha256, digest)

    def test_d_one_that_protects_and_changes_its_footprint_stales_the_declaration(self) -> None:
        """RF-015-10, RF-015-16: el ancho de P2 (que protege) baja de 30 a 20 m: su huella cambia, y la
        declaración, que consume su ``des_epr_``, queda obsoleta; «Recalcular lo obsoleto» la repite con la zona
        nueva (la tabla cambia)."""
        uid, dump = self.current_declaration(), self.declared_dump()
        self.change_as(design_params.entity_key("PLT-002", "width_m"), 20.0, EDITOR)
        self.assertTrue(self.stale_causes(uid), "la declaración consume la huella de la que protege")
        self.assertEqual(self.declare_plan(), [(DECLARE,)])
        self.clock.advance(minutes=1)
        self.settle()
        self.assertNotEqual(self.current_declaration(), uid)
        self.assertNotEqual(self.declared_dump(), dump)
        self.assertEqual(self.declare_plan(), [])

    def test_e_the_protect_of_one_that_does_not_protect_is_a_parameter_of_the_declaration(self) -> None:
        """RF-015-10: P1 no protege, y su ``protect`` es un parámetro de la declaración: cambiarlo (con su
        resguardo ya dado, que la declaración no lee mientras no proteja) la deja obsoleta, por ese parámetro, y
        repetida declara también a P1 y consume ya su ``des_epr_``."""
        self.create_param(guard_key("PLT-001"), GUARD_M)
        self.assertEqual(self.declare_plan(), [], "el resguardo de una que no protege no lo lee la declaración")
        uid = self.current_declaration()
        self.change_as(protect_key("PLT-001"), True, USER)
        self.assertIn(("parameter_changed", protect_key("PLT-001")), self.stale_causes(uid))
        self.assertEqual(self.declare_plan(), [(DECLARE,)])
        self.clock.advance(minutes=1)
        self.settle()
        self.assertEqual({found.entity_code for found in self.declared()}, {"PLT-001", "PLT-002"})
        self.assertEqual({name for (name,) in self.query(
            "SELECT d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'in'", self.current_declaration())},
            {provenance.dataset_name(provenance.ENTITY_TABLE, name) for name in (LOADING, WORKSHOP)})


# ---------------------------------------------------------------------------------------------
# Los rechazos
# ---------------------------------------------------------------------------------------------


class RefusalTest(DeclareCase):
    """RF-015-10, RF-015-12, D-19, D-21: con P1 (la «Plataforma de carga», que no protege) en V01, proteger
    sin resguardo, o en el modo «en corte y relleno», se rechaza con la entidad, el campo y el valor, **sin
    escribir nada**; sin entidades que protejan, la tabla queda vacía; sin versión editable no se declara."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())

    def written_now(self) -> dict[str, Any]:
        return {**self.written(), "counter": change_counter(self.root),
                "files": files(self.root, skip=(), skip_dirs=("cache",))}

    def refused(self, expected: str) -> Any:
        """Declarar V01 se rechaza con ``expected`` y no escribe nada; devuelve el error."""
        before = self.written_now()
        with self.assertRaises(messages.DesignError) as caught:
            self.declare()
        self.assertEqual(caught.exception.code, expected)
        self.assertEqual(self.written_now(), before, "el rechazo ha escrito algo")
        return caught.exception

    def test_a_without_an_entity_that_protects_the_table_is_empty_but_exists(self) -> None:
        """RF-015-10: P1 no protege (``protect`` falso por defecto, D-4): la declaración es válida y deja la
        tabla de V01 **vacía** (``des.declared_count`` 0), con el dato registrado: la compilación de las
        máscaras (T18 y T19) la necesita."""
        stored = self.declare()
        self.assertEqual(self.declared(), ())
        self.assertEqual(self.figures_of(str(stored.handle.uid)), {("des.declared_count", NO_SCOPE): 0.0})
        self.assertEqual(self.record_of().locator, TABLE)

    def test_b_protecting_without_a_guard_is_refused_with_the_entity_the_field_and_no_value(self) -> None:
        """RF-015-10, D-19: P1 pasa a proteger sin resguardo (``guard_m`` no tiene valor ni lo tiene por
        defecto: no se elige uno por la persona): se rechaza con el código de la falta de valor, la
        entidad, el campo ``des.platform.plt_001.guard_m`` y sin valor, y no se escribe nada."""
        self.addCleanup(self.change_as, protect_key("PLT-001"), False, USER)
        self.change_as(protect_key("PLT-001"), True, USER)
        error = self.refused("des.entity_param_missing")
        self.assertEqual(error.values["entity"], LOADING)
        self.assertEqual(error.values["field"], guard_key("PLT-001"))
        self.assertIn(LOADING, error.text)
        self.assertIn(guard_key("PLT-001"), error.text)

    def test_c_protecting_in_cut_and_fill_is_refused_with_the_entity_the_field_and_the_mode(self) -> None:
        """RF-015-12, D-21: P1 en «corte y relleno» que protege declararía «sin relleno» y prohibiría su
        propio movimiento: se rechaza (defensa en profundidad: la preparación ya lo rechaza al crearla) con
        ``des.platform_protect_cut_fill``, la entidad, el campo ``…mode`` y el valor ``cut_fill``, sin
        escribir nada. En el modo «en corte» sí declara."""
        self.addCleanup(self.change_as, protect_key("PLT-001"), False, USER)
        self.change_as("des.platform.plt_001.mode", "cut_fill", USER)
        self.create_param(guard_key("PLT-001"), GUARD_M)
        self.change_as(protect_key("PLT-001"), True, USER)
        error = self.refused("des.platform_protect_cut_fill")
        self.assertEqual((error.values["entity"], error.values["field"], error.values["value"]),
                         (LOADING, "des.platform.plt_001.mode", "cut_fill"))
        self.change_as("des.platform.plt_001.mode", "cut", USER)  # en corte, sí declara
        self.declare()
        (found,) = self.declared()
        self.assertEqual((found.entity_code, found.buffer_out_m), ("PLT-001", GUARD_M))

    def test_d_without_an_editable_version_nothing_is_declared(self) -> None:
        """RF-009-21, RF-015-10: sin versión (``core.version_required``) o con una que no existe
        (``core.version_unknown``) no se declara nada y no se escribe nada."""
        before = self.written_now()
        for version, code in ((None, "core.version_required"), ("V99", "core.version_unknown")):
            with self.subTest(version=version), self.assertRaises(versions_model.VersionError) as caught:
                ops.finish(entity_store.declare_constraints_steps(self.project, version))
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.written_now(), before)

    def test_e_the_writer_takes_the_declared_table_only_in_its_own_step(self) -> None:
        """RF-015-10 (el escritor de la versión): la tabla de las declaradas es una capa de polígonos y
        solo la prepara ``declared_steps`` (con ``DeclaredConstraint``); ``table_steps`` la rechaza, no se
        prepara dos veces, y sin ella no se confirma: errores del programa que no dejan nada."""
        before = self.written_now()
        with design_store.DesignWriter(self.project, DECLARE, "", version=self.v1.uid,
                                       supersedes=self.current_declaration()) as writer:
            with self.assertRaises(ValueError) as caught:
                writer.table_steps(provenance.DECLARED_TABLE, [])
            self.assertIn("capa de polígonos", str(caught.exception))
            with self.assertRaises(TypeError):
                writer.declared_steps(["no es una restricción"])
            with self.assertRaises(ValueError):
                writer.commit()  # faltan salidas por preparar (y falta su operación)
            prep.drive(writer.declared_steps([]))
            self.assertEqual([spec.locator for spec in writer.specs], [TABLE])
            with self.assertRaises(ValueError):
                writer.declared_steps([])  # ya está preparada
        self.assertEqual(self.written_now(), before)


class SettingsTest(unittest.TestCase):
    """RF-015-10, RF-009-11: lo que la declaración anota en sus ajustes para reproducirse sin proyecto."""

    def test_the_version_and_the_decisions_round_trip_and_the_old_shape_is_kept(self) -> None:
        """RF-015-10: ``declare_settings`` con la versión y las decisiones las guarda como JSON y se leen
        igual; sin ellas es la forma de la T04 (solo las entidades) y no dan nada."""
        when = date(2026, 11, 14)
        pairs = [("PLT-001", LOADING), ("PLT-002", WORKSHOP)]
        found = json.loads(json.dumps(provenance.declare_settings(
            pairs, version_uid="v" * 32, decisions={"PLT-002": (USER, when)})))
        self.assertEqual(found["version"], "v" * 32)
        self.assertEqual(provenance.settings_version(found), "v" * 32)
        self.assertEqual(provenance.settings_decisions(found), {"PLT-002": (USER, when)})
        self.assertEqual(provenance.settings_entities(found), tuple(pairs))
        old = provenance.declare_settings(pairs)
        self.assertEqual(old, {"entities": [{"code": code, "name": name} for code, name in pairs]})
        self.assertEqual((provenance.settings_version(old), provenance.settings_decisions(old)), (None, {}))

    def test_what_is_not_a_version_or_a_decision_is_a_program_error(self) -> None:
        """RF-015-10: una decisión de una entidad que la declaración no recoge, sin decisor o con una fecha
        que no lo es, una versión en blanco o unos ajustes mal formados son errores del programa."""
        pairs = [("PLT-001", LOADING)]
        when = date(2026, 11, 14)
        for decisions in ({"PLT-009": (USER, when)}, {"PLT-001": (" ", when)}):
            with self.subTest(decisions=decisions), self.assertRaises(ValueError):
                provenance.declare_settings(pairs, decisions=decisions)
        for stamp in ("2026-11-14", datetime(2026, 11, 14, 8, 0)):
            with self.subTest(stamp=stamp), self.assertRaises(TypeError):
                provenance.declare_settings(pairs, decisions={"PLT-001": (USER, stamp)})
        for blank in ("", "  ", 5):
            with self.subTest(version=blank), self.assertRaises(ValueError):
                provenance.declare_settings(pairs, version_uid=blank)
        for bad in ({"entities": "no"}, {"entities": [{"code": "PLT-001", "name": "A", "decided_by": USER}]},
                    {"entities": [{"code": "PLT-001", "name": "A", "decided_by": USER,
                                   "decided_on": "ayer"}]}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                provenance.settings_decisions(bad)
        with self.assertRaises(ValueError):
            provenance.settings_version({"version": 5})


# ---------------------------------------------------------------------------------------------
# Reproducir
# ---------------------------------------------------------------------------------------------


class ReproduceTest(DeclareCase):
    """RF-015-02, RF-009-11, RF-009-19: P1 y P2 (que protege) creadas y declaradas en V01, con el resguardo de
    P2 cambiado por otra persona, y congeladas en V01.r1: la declaración se reproduce sin el proyecto desde
    sus entradas congeladas (los ``des_epr_``), sus parámetros y sus ajustes."""

    revision: ClassVar[str]
    uid: ClassVar[str]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())
        cls.made(prep.request(WORKSHOP, start="entity:PLT-001", protect=True, guard_m=GUARD_M))
        cls.clock.advance(minutes=DAY_MINUTES)
        cls.change_as(guard_key("PLT-002"), 5.0, EDITOR)
        cls.declare()
        cls.uid = cls.current_declaration()
        cls.clock.advance(minutes=1)
        frozen = ops.finish(freeze.freeze_steps(cls.project, cls.v1.uid, reason="Entrega de la prueba"))
        cls.revision = str(frozen.frozen.uid)
        cls.clock.advance(minutes=1)

    def reproduce(self) -> Any:
        """La reproducción de V01.r1, comprobando que **no escribió** nada en el proyecto."""
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        report = ops.finish(reproduce_mod.reproduce_steps(self.project, self.revision))
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root)),
                         before, "reproducir no escribe en el proyecto")
        return report

    def assert_same(self, report: Any) -> None:
        mine = [check for check in report.outputs if check.operation_uid == self.uid]
        self.assertEqual([check.role for check in mine], ["constraints_declared"])
        self.assertTrue(all(check.same for check in mine), mine)
        found = [check for check in report.figures if check.operation_uid == self.uid]
        self.assertEqual([(check.key, check.same) for check in found], [("des.declared_count", True)])
        self.assertFalse(report.not_reproducible)
        self.assertTrue(report.matches)

    def test_a_reproducing_gives_the_same_table_hash_and_figure_without_writing(self) -> None:
        """RF-015-02, RF-009-11: reproducir V01.r1 rehace la tabla de las declaradas con el **mismo hash** que
        registró la operación (el contorno, el resguardo de la entidad congelado, el motivo, el decisor y la
        fecha de la decisión de sus ajustes y el ``uid`` de la versión) y la misma cifra, sin escribir nada."""
        self.assert_same(self.reproduce())

    def test_b_changing_what_is_live_after_freezing_leaves_the_frozen_declaration_as_it_was(self) -> None:
        """RF-015-16, RF-009-19, RF-009-11: congelada V01.r1, cambiar el resguardo de P2 y recalcular la
        declaración (en la revisión abierta) cambia lo vivo pero no lo congelado: V01.r1 se reproduce otra vez
        igual, con el hash de cuando se congeló."""
        frozen = self.query("SELECT content_sha256 FROM gb_operation_io WHERE operation_uid = ? AND "
                            "direction = 'out'", self.uid)
        self.clock.advance(minutes=DAY_MINUTES)
        self.change_as(guard_key("PLT-002"), 9.0, USER)
        self.assertEqual(self.recompute_plan(), [(DECLARE,)])
        self.clock.advance(minutes=1)
        self.settle()
        (found,) = self.declared()
        self.assertEqual(found.buffer_out_m, 9.0)
        self.assertEqual(self.query("SELECT content_sha256 FROM gb_operation_io WHERE operation_uid = ? "
                                    "AND direction = 'out'", self.uid), frozen)
        self.assert_same(self.reproduce())


class ReproduceFunctionTest(unittest.TestCase):
    """RF-015-02: la función de reproducir la declaración es la real (ya no dice que falta una tarea)."""

    def test_what_is_not_a_request_or_not_a_declaration_is_a_program_error(self) -> None:
        """RF-015-02: lo que no es una petición de reproducir es ``TypeError``; la de otro tipo de
        operación, ``ValueError`` (errores del programa, no ``NotImplementedError``)."""
        with self.assertRaises(TypeError):
            design_reproduce.reproduce_declare_constraints("petición")
        other = reproduce_mod.ReproduceRequest("des.quarry", {}, (), {}, ".", None)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            design_reproduce.reproduce_declare_constraints(other)

    def test_the_declaration_is_recomputed_by_the_function_of_the_008(self) -> None:
        """RF-015-02, RF-008-26: ``recompute_run`` repite también ``des.declare_constraints`` (es de
        ``RECOMPUTED``) y, desde la T30, la capa de entidades, y rechaza lo que no es de su lista."""
        self.assertIn(DECLARE, design_store.RECOMPUTED)
        self.assertIn(provenance.ENTITY_LAYER, design_store.RECOMPUTED)


if __name__ == "__main__":
    unittest.main()

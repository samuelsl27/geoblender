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
from typing import Any

from tests.support.package import import_geoblender
from tests.unit.design import test_platform_operation as ops
from tests.unit.design import test_platform_prepare as prep

access = import_geoblender("gis.masks.access")
declaring = import_geoblender("gis.masks.declaring")
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
        declaring.register(entity_store.DECLARATION_HOOK)  # lo que registra ``bl`` (T38)
        cls.addClassCleanup(declaring.unregister, entity_store.DECLARATION_HOOK)

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


# ---------------------------------------------------------------------------------------------
# Solo las que protegen
# ---------------------------------------------------------------------------------------------


# ---------------------------------------------------------------------------------------------
# Los rechazos
# ---------------------------------------------------------------------------------------------


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

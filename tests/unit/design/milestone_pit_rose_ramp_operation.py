# SPDX-License-Identifier: GPL-3.0-or-later
"""Las operaciones de proyecto de la roseta de taludes y de la definición de rampa de la corta, sobre un proyecto, como prueba de **hito**
(spec 018, T04; HU-018-1 y 3; RF-018-07, RF-018-15; plan 018 §5.1, §5.2.2 y §5.2.3; ADR-0027; RF-008-01, RF-009-24).

Como la 017 hizo con los perfiles de pista (``milestone_road_profiles_operation``, T48, RNF-017-09), lo que **monta un proyecto del diseño**
(≈ 1 s con el proyecto compartido) no entra en el «verde»: lo puro (los rangos, los derivados, la validación y el código) está en
``test_pit_rose`` y ``test_pit_ramp_def``. Aquí: la tabla ``des_pit_rose`` y ``des_pit_ramp``, la operación ``des.edit_pit_roses`` y
``des.edit_pit_ramps`` que crea, renombra y completa **en una versión**, el código inmutable, y cada rechazo, que no deja nada (ni una
operación fallida).
"""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from tests.support import constraints_project as cp
from tests.support import design_fixtures as dfx
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.unit.design.milestone_road_profiles_operation import declaration as road_declaration
from tests.unit.design.milestone_road_profiles_operation import new as new_road_profile
from tests.unit.design.test_pit_ramp_def import PD, values as ramp_values, zigzag
from tests.unit.design.test_pit_rose import ranges_of

params = import_geoblender("design.params")
messages = import_geoblender("design.messages")
pit_rose = import_geoblender("design.pit_rose")
pit_ramp_def = import_geoblender("design.pit_ramp_def")
road_profiles = import_geoblender("design.road_profiles")
core_params = import_geoblender("core.params")
registry = import_geoblender("core.datasets.registry")
versions_read = import_geoblender("core.versions.read")

NOBODY = "Samuel (IMGA)"
PARAM_KEYS = "(key LIKE 'des.rose.%' OR key LIKE 'des.pitramp.%')"


def declaration(**changes: Any) -> Any:
    base: dict[str, Any] = {"source": "Estudio geotécnico de la prueba", "decided_by": NOBODY, "reason": "Spec 018"}
    return pit_rose.Declaration(**{**base, **changes})


class _Case(dfx.DesignProjectCase):
    """El proyecto del diseño (una copia **por clase**), con el perfil de pista ``PISTA_PRINCIPAL`` creado y las familias y las operaciones
    registradas (lo hará ``bl``). Cada prueba usa nombres que no repite ninguna otra: el orden no importa."""

    @classmethod
    def setUpClass(cls) -> None:
        dfx.project_template()
        cls.enterClassContext(cp.constraints_registered())
        core_params.register_families(
            (*params.ROAD_PROFILE_FAMILIES, *params.ROSE_FAMILIES, *params.PITRAMP_FAMILIES))
        cls.addClassCleanup(core_params.unregister_families, "des")
        cls.enterClassContext(registered(*road_profiles.OPERATIONS, *pit_rose.OPERATIONS, *pit_ramp_def.OPERATIONS))
        cls.project, cls.clock = cls.enterClassContext(dfx.open_design_project("gb-pr-"))
        cls.root = Path(cls.project.root)
        with cls.project.read() as conn:
            cls.v1, cls.v2 = (versions_read.version(conn, uid) for uid in dfx.project_template()["versions"])
        cls.store = core_params.ParameterStore(cls.project)
        cls.clock.advance(minutes=1)
        road_profiles.edit_road_profiles(cls.project, (new_road_profile("PISTA_PRINCIPAL"),), road_declaration())

    def setUp(self) -> None:
        pass  # el proyecto es el de la clase

    def tick(self) -> None:
        self.clock.advance(minutes=1)

    def state(self) -> dict[str, Any]:
        """Lo que hay de rosetas y rampas: operaciones, tablas y sus filas, datos y filas de parámetros."""
        with self.project.read() as conn:
            def table(name: str) -> Any:
                made = conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (name,)).fetchone() is not None
                return conn.execute(f"SELECT code, name FROM {name} ORDER BY fid").fetchall() if made else None
            return {
                "operations": conn.execute("SELECT op_type, status FROM gb_operation WHERE op_type LIKE 'des.edit_pit_%' "
                                           "ORDER BY fid").fetchall(),
                "rose": table(pit_rose.TABLE), "ramp": table(pit_ramp_def.TABLE),
                "params": conn.execute(f"SELECT key, scope_uid, rev FROM gb_parameter WHERE {PARAM_KEYS} ORDER BY key, scope_uid").fetchall(),
            }

    def reject(self, call: Any) -> Any:
        """La edición se rechaza con un ``DesignError`` y no deja nada, ni una operación fallida."""
        before = self.state()
        with self.assertRaises(messages.DesignError) as caught:
            call()
        self.assertEqual(self.state(), before)
        return caught.exception

    def value(self, key: str, version: Any = None) -> Any:
        return self.store.get(key, version=version)

    def rose(self, name: str, **kw: Any) -> Any:
        self.tick()
        return pit_rose.edit_pit_roses(self.project, [pit_rose.RoseEdit(name=name, ranges=kw.pop("ranges", ranges_of()))],
                                       kw.pop("declared", declaration()))

    def ramp(self, name: str, data: Any = None, declared: Any = ...) -> Any:
        self.tick()
        return pit_ramp_def.edit_pit_ramps(self.project, [pit_ramp_def.RampEdit(name=name, values=data or ramp_values())],
                                           declaration() if declared is ... else declared)


class EmptyProjectTest(_Case):
    def test_without_roses_or_ramps_there_is_no_table(self) -> None:
        """RF-018-07, RF-018-15: un proyecto sin rosetas ni rampas no tiene sus tablas, y leerlas da vacío, sin error."""
        state = self.state()
        self.assertEqual((state["rose"], state["ramp"], state["operations"], state["params"]), (None, None, [], []))
        with self.project.read() as conn:
            self.assertEqual((pit_rose.read_roses(conn), pit_rose.rose_names(conn)), ((), {}))
            self.assertEqual((pit_ramp_def.read_ramps(conn), pit_ramp_def.ramp_names(conn)), ((), {}))


class RoseOperationTest(_Case):
    def test_the_first_rose_creates_the_table_its_rows_and_its_parameters(self) -> None:
        """RF-018-07: sin rosetas no hay tabla; la primera la crea (``fid``, ``uid``, ``code``, ``name`` únicos, ``created_by``,
        ``created_at``), como dato del proyecto de ``des`` leído con ``core.gpkg_layer@1`` y no editable, y escribe los cuatro valores
        de cada rango como filas ``create`` con su origen y decisor (``des.rose.{r}.r{i}.<valor>``)."""
        made = self.rose("ROSETA UNO")
        self.assertEqual((made.created, made.renamed, made.completed), (("roseta_uno",), (), ()))
        with self.project.read() as conn:
            record = registry.get(conn, pit_rose.TABLE)
            columns = [row[1] for row in conn.execute(f"PRAGMA table_info({pit_rose.TABLE})")]
            status = conn.execute("SELECT op_type, status FROM gb_operation WHERE uid = ?", (made.operation_uid,)).fetchone()
        self.assertEqual(columns, ["fid", "uid", "code", "name", "created_by", "created_at"])
        self.assertEqual((record.module, record.kind, record.reader, record.qgis_editable), ("des", "table", "core.gpkg_layer@1", False))
        self.assertEqual(status, ("des.edit_pit_roses", "done"))
        for position, item in enumerate(ranges_of()):
            index = pit_rose.range_index(position)
            for param, expected in zip(params.RoseParam, (item.from_deg, item.to_deg, item.face_deg, item.berm_m), strict=True):
                found = self.value(params.rose_key("roseta_uno", index, param))
                self.assertEqual(found.value, expected, (index, param))
                self.assertEqual((found.kind, found.decided_by, found.source), ("ADOPTADO", NOBODY, "Estudio geotécnico de la prueba"))

    def test_rename_keeps_the_code_and_the_values(self) -> None:
        """RF-018-07: el código sale del nombre al crear y no cambia nunca; renombrar no toca los valores."""
        self.rose("ROSETA DOS")
        before = self.state()["params"]
        self.tick()
        done = pit_rose.edit_pit_roses(self.project, [pit_rose.RoseEdit(name="ROSETA DOS RENOMBRADA", code="roseta_dos")])
        self.assertEqual((done.created, done.renamed, done.completed), ((), ("roseta_dos",), ()))
        with self.project.read() as conn:
            self.assertEqual(pit_rose.rose_names(conn)["roseta_dos"], "ROSETA DOS RENOMBRADA")
        self.assertEqual(self.state()["params"], before)
        self.tick()
        again = pit_rose.edit_pit_roses(self.project, [pit_rose.RoseEdit(name="ROSETA DOS", ranges=ranges_of())], declaration())
        self.assertEqual(again.created, ("roseta_dos_2",))  # el código viejo no se reutiliza ni cambia

    def test_a_rose_in_a_version_has_its_own_values(self) -> None:
        """RF-018-07, RF-009-24: con la versión en la declaración los valores son los propios de esa versión y no se escriben los del
        proyecto."""
        self.rose("ROSETA V2", declared=declaration(version=self.v2.code, reason="Alternativa con otra roseta"))
        key = params.rose_key("roseta_v2", "r1", "face_deg")
        self.assertEqual(self.value(key, version=self.v2.code).value, 60.0)
        self.assertIsNone(self.value(key))
        self.assertIsNone(self.value(key, version=self.v1.code))

    def test_a_rose_can_be_completed_in_a_version(self) -> None:
        """RF-018-07, RF-009-24: una roseta del proyecto recibe, con ``ranges``, los rangos propios de una versión sin tocar los del
        proyecto."""
        self.tick()
        row = pit_rose.edit_pit_roses(self.project, [pit_rose.RoseEdit(name="ROSETA A COMPLETAR", ranges=[(0, 360, 70, 5)])], declaration())
        code = row.created[0]
        self.tick()
        done = pit_rose.edit_pit_roses(self.project, [pit_rose.RoseEdit(code=code, ranges=ranges_of())],
                                       declaration(version=self.v1.code))
        self.assertEqual(done.completed, (code,))
        self.assertEqual(self.value(params.rose_key(code, "r1", "face_deg")).value, 70.0)
        self.assertEqual(self.value(params.rose_key(code, "r1", "face_deg"), version=self.v1.code).value, 60.0)
        self.assertEqual(self.value(params.rose_key(code, "r2", "face_deg"), version=self.v1.code).value, 45.0)
        self.assertIsNone(self.value(params.rose_key(code, "r2", "face_deg")))

    def test_what_the_scope_already_has_is_refused_and_undone(self) -> None:
        """RF-008-01: completar un valor que el ámbito ya tiene es ``core.param_exists``: se deshace entero y la operación queda
        «fallida»."""
        self.rose("ROSETA REPETIDA")
        before = self.state()
        self.tick()
        with self.assertRaises(core_params.ParamError):
            pit_rose.edit_pit_roses(self.project, [pit_rose.RoseEdit(code="roseta_repetida", ranges=ranges_of())], declaration())
        after = self.state()
        self.assertEqual((after["params"], after["rose"]), (before["params"], before["rose"]))
        self.assertEqual(after["operations"][-1][1], "failed")

    def test_the_rejections_leave_nothing(self) -> None:
        """RF-018-07, RF-018-04: un nombre vacío o repetido (sin distinguir mayúsculas), sin rangos, con un hueco, un solape o un valor
        fuera de rango se rechaza con su código y **no deja nada**: ni fila, ni parámetro, ni una operación fallida."""
        self.rose("ROSETA PARA REPETIR")
        cases = [
            ("des.pit_rose_name_missing", lambda: pit_rose.edit_pit_roses(self.project, [pit_rose.RoseEdit(name="  ", ranges=ranges_of())], declaration())),
            ("des.pit_rose_name_repeated", lambda: pit_rose.edit_pit_roses(
                self.project, [pit_rose.RoseEdit(name="roseta para repetir", ranges=ranges_of())], declaration())),
            ("des.pit_rose_no_ranges", lambda: pit_rose.edit_pit_roses(self.project, [pit_rose.RoseEdit(name="SIN RANGOS", ranges=[])], declaration())),
            ("des.pit_rose_gap", lambda: pit_rose.edit_pit_roses(
                self.project, [pit_rose.RoseEdit(name="CON HUECO", ranges=[(0, 100, 60, 6), (120, 360, 45, 6)])], declaration())),
            ("des.pit_rose_overlap", lambda: pit_rose.edit_pit_roses(
                self.project, [pit_rose.RoseEdit(name="CON SOLAPE", ranges=[(0, 200, 60, 6), (180, 360, 45, 6)])], declaration())),
            ("des.pit_rose_value_range", lambda: pit_rose.edit_pit_roses(
                self.project, [pit_rose.RoseEdit(name="ALFA MALA", ranges=[(0, 360, 95, 6)])], declaration())),
            ("des.pit_rose_value_range", lambda: pit_rose.edit_pit_roses(
                self.project, [pit_rose.RoseEdit(name="BERMA MALA", ranges=[(0, 360, 60, -1)])], declaration())),
        ]
        for code, call in cases:
            with self.subTest(code=code):
                self.assertEqual(self.reject(call).code, code)

    def test_the_program_errors(self) -> None:
        """Sin declaración con rangos, una roseta que no existe, sin ediciones o una edición que no cambia nada: ``ValueError``."""
        for call in (lambda: pit_rose.edit_pit_roses(self.project, [pit_rose.RoseEdit(name="X", ranges=ranges_of())]),
                     lambda: pit_rose.edit_pit_roses(self.project, [pit_rose.RoseEdit(code="no_existe", name="Y")]),
                     lambda: pit_rose.edit_pit_roses(self.project, []),
                     lambda: pit_rose.edit_pit_roses(self.project, [pit_rose.RoseEdit(code="roseta_uno")])):
            before = self.state()
            with self.assertRaises(ValueError):
                call()
            self.assertEqual(self.state(), before)

    def test_the_operation_is_declared_for_the_project_without_repetition(self) -> None:
        """RF-018-07: ``des.edit_pit_roses`` es de proyecto, no se repite sola y lleva la orden del catálogo."""
        (definition,) = pit_rose.OPERATIONS
        self.assertEqual((definition.op_type, definition.repeatable, definition.scope), ("des.edit_pit_roses", False, "project"))
        self.assertEqual(definition.commands, (pit_rose.EDIT_COMMAND,))


class RampOperationTest(_Case):
    def test_the_first_ramp_creates_the_table_its_row_and_its_parameters(self) -> None:
        """RF-018-15: la primera rampa crea ``des_pit_ramp`` y escribe sus valores (la espiral, sin radio ni plataforma)."""
        made = self.ramp("RAMPA UNO")
        self.assertEqual(made.created, ("rampa_uno",))
        for param, expected in (("type", "spiral"), ("sense", "cw"), ("start", "fondo"), ("gradient_pct", 8.0),
                                ("road_profile", "pista_principal"), ("transition_m", 10.0)):
            found = self.value(params.pitramp_key("rampa_uno", param))
            self.assertEqual(found.value, expected, param)
            self.assertEqual((found.kind, found.decided_by), ("ADOPTADO", NOBODY))
        self.assertIsNone(self.value(params.pitramp_key("rampa_uno", "turn_radius_m")))

    def test_a_zigzag_writes_its_radius_and_platform(self) -> None:
        self.ramp("ZIG ZAG UNO", zigzag(gradient_pct=PD), declaration(kind="HIPÓTESIS"))
        self.assertEqual(self.value(params.pitramp_key("zig_zag_uno", "turn_radius_m")).value, 15.0)
        self.assertEqual(self.value(params.pitramp_key("zig_zag_uno", "min_platform_m")).kind, "HIPÓTESIS")

    def test_a_ramp_in_a_version_has_its_own_values(self) -> None:
        """RF-018-15, RF-009-24: los valores propios de una versión; el perfil de pista, el del proyecto."""
        self.ramp("RAMPA V1", declared=declaration(version=self.v1.code))
        key = params.pitramp_key("rampa_v1", "gradient_pct")
        self.assertEqual(self.value(key, version=self.v1.code).value, 8.0)
        self.assertIsNone(self.value(key))

    def test_rename_keeps_the_code(self) -> None:
        self.ramp("RAMPA A RENOMBRAR")
        self.tick()
        done = pit_ramp_def.edit_pit_ramps(self.project, [pit_ramp_def.RampEdit(code="rampa_a_renombrar", name="RAMPA RENOMBRADA")])
        self.assertEqual(done.renamed, ("rampa_a_renombrar",))
        with self.project.read() as conn:
            self.assertEqual(pit_ramp_def.ramp_names(conn)["rampa_a_renombrar"], "RAMPA RENOMBRADA")

    def test_a_gradient_over_the_road_profile_maximum_is_refused_and_leaves_nothing(self) -> None:
        """RF-018-15: ``g > pd`` del perfil de pista **del ámbito**, al crear y al completar; no deja nada."""
        error = self.reject(lambda: self.ramp("RAMPA FUERTE", ramp_values(gradient_pct=PD + 1.0)))
        self.assertEqual((error.code, error.values["limit"], error.values["other"]), ("des.pit_ramp_gradient_over", PD, "PISTA_PRINCIPAL"))
        self.ramp("RAMPA SUAVE", ramp_values(road_profile="pista_principal", gradient_pct=PD - 1.0))
        self.tick()
        error = self.reject(lambda: pit_ramp_def.edit_pit_ramps(
            self.project, [pit_ramp_def.RampEdit(code="rampa_suave", values={"gradient_pct": PD + 2.0})], declaration(version=self.v1.code)))
        self.assertEqual(error.code, "des.pit_ramp_gradient_over")

    def test_the_rejections_leave_nothing(self) -> None:
        """RF-018-15, RF-018-04: nombre vacío o repetido, un valor sin valor o fuera de rango, el zig-zag sin radio y un perfil de pista
        que no existe se rechazan con su código y no dejan nada."""
        self.ramp("RAMPA PARA REPETIR")
        cases = [
            ("des.pit_ramp_name_missing", lambda: self.ramp("  ")),
            ("des.pit_ramp_name_repeated", lambda: self.ramp("rampa para repetir")),
            ("des.pit_ramp_value_missing", lambda: self.ramp("SIN INICIO", ramp_values(start=None))),
            ("des.pit_ramp_value_range", lambda: self.ramp("TRANSICION MALA", ramp_values(transition_m=-1.0))),
            ("des.pit_ramp_value_missing", lambda: self.ramp("ZIGZAG SIN RADIO", zigzag(turn_radius_m=None))),
            ("des.pit_ramp_value_range", lambda: self.ramp("SIN PERFIL", ramp_values(road_profile="no_existe"))),
            ("des.pit_ramp_value_missing", lambda: self.ramp("SIN PERFIL DE PISTA", ramp_values(road_profile=None))),
        ]
        for code, call in cases:
            with self.subTest(code=code, name=code):
                self.assertEqual(self.reject(call).code, code)

    def test_a_ramp_value_with_no_declaration_is_a_program_error(self) -> None:
        before = self.state()
        with self.assertRaises(ValueError):
            pit_ramp_def.edit_pit_ramps(self.project, [pit_ramp_def.RampEdit(name="SIN DECLARAR", values=ramp_values())])
        self.assertEqual(self.state(), before)

    def test_the_operation_is_declared_for_the_project_without_repetition(self) -> None:
        (definition,) = pit_ramp_def.OPERATIONS
        self.assertEqual((definition.op_type, definition.repeatable, definition.scope), ("des.edit_pit_ramps", False, "project"))
        self.assertEqual(definition.commands, (pit_ramp_def.EDIT_COMMAND,))


if __name__ == "__main__":
    unittest.main()

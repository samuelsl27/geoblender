# SPDX-License-Identifier: GPL-3.0-or-later
"""La operación que edita los perfiles de pista, sobre un proyecto, como prueba de **hito** (spec 017, T04, que la dejó en el «verde» dentro
de ``test_road_profiles``; T48, que la pasó al paso «hito» de ``tools/check.py --completo`` para que el «verde» vuelva a costar ≤ +3 s:
RNF-017-09; HU-017-1; RF-017-04, RF-017-07, RF-017-08; plan 017 §5.1, §5.2.2, §5.3.1 y §5.7 P-2; ADR-0027; RF-008-01, RF-009-24).

Lo que antes estaba en ``test_road_profiles`` junto con lo puro y monta un proyecto del diseño por prueba o por clase (≈ 0,9 s): la tabla
``des_road_profile`` (:class:`TableTest`), la operación ``des.edit_road_profiles`` que crea, completa y renombra perfiles en una transacción
(:class:`OperationTest`), cada rechazo, que no deja nada (:class:`RejectionTest`) y la declaración de la operación para ``bl``
(:class:`DeclarationTest`). **No cambia ninguna prueba**: solo el fichero. Lo puro (los derivados, las comprobaciones del perfil y el código del nombre)
sigue en ``test_road_profiles`` del «verde», de donde se importan los valores y las ayudas; ``milestone_road_profiles`` (la T04, lo que pasa de 1 s)
importa de aquí el proyecto de prueba (:class:`_RoadProfilesCase`, :class:`_SharedCase`) y las ayudas ``declaration`` y ``new``.
"""

from __future__ import annotations

import json
import math
import sqlite3
import unittest
from pathlib import Path
from typing import Any

from tests.support import constraints_project as cp
from tests.support import design_fixtures as dfx
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.unit.design.test_road_profiles import MAIN, NOBODY, OPTIONAL, OTHER, Param, profile_of, values_of

provenance = import_geoblender("design.provenance")
params = import_geoblender("design.params")
messages = import_geoblender("design.messages")
road_profiles = import_geoblender("design.road_profiles")
core_params = import_geoblender("core.params")
registry = import_geoblender("core.datasets.registry")
versions_read = import_geoblender("core.versions.read")
operations = import_geoblender("core.provenance.operations")
i18n = import_geoblender("core.i18n")

# --- La tabla del proyecto y la operación que edita los perfiles ------------------------------------------------------

REQUIRED = tuple(param for param in Param if param.value not in OPTIONAL)


def declaration(**changes: Any) -> Any:
    """Lo que declara la persona de los valores que escribe (origen, decisor y motivo)."""
    base: dict[str, Any] = {"source": "ITC 07.1.03 de la prueba", "decided_by": NOBODY, "reason": "Perfil de la spec 017"}
    return road_profiles.ProfileDeclaration(**{**base, **changes})


def new(name: str, **changes: Any) -> Any:
    """Un perfil nuevo con los trece valores de referencia (sin el factor de malla ni la métrica), con ``changes`` encima;
    con ``None`` en un valor, ese valor se quita."""
    values = {**{key: value for key, value in values_of().items() if key not in OPTIONAL}, **changes}
    return road_profiles.ProfileEdit(name=name, values={key: value for key, value in values.items() if value is not None})


class _RoadProfilesCase(dfx.DesignProjectCase):
    """El proyecto del diseño (una copia **por prueba**: estas pruebas escriben), con la familia del perfil de pista y las
    operaciones registradas (lo hará ``bl``)."""

    @classmethod
    def setUpClass(cls) -> None:
        dfx.project_template()  # la plantilla, antes de registrar lo de la 012 (T05)
        cls.enterClassContext(cp.constraints_registered())
        core_params.register_families(params.ROAD_PROFILE_FAMILIES)
        cls.addClassCleanup(core_params.unregister_families, "des")
        never = provenance.operation_def(provenance.ROAD, lambda request: None)  # la que lee los perfiles al probar la obsolescencia
        cls.enterClassContext(registered(*road_profiles.OPERATIONS, never))

    def setUp(self) -> None:
        self.project, self.clock = self.enterContext(dfx.open_design_project("gb-rp-"))
        self.root = Path(self.project.root)
        with self.project.read() as conn:
            self.v1, self.v2 = (versions_read.version(conn, uid) for uid in dfx.project_template()["versions"])
        self.store = core_params.ParameterStore(self.project)

    def edit(self, *edits: Any, declared: Any = ...) -> Any:
        """Edita los perfiles un minuto después, con la declaración de ``declaration()``."""
        self.clock.advance(minutes=1)
        return road_profiles.edit_road_profiles(self.project, edits, declaration() if declared is ... else declared)

    def state(self) -> dict[str, Any]:
        """Lo que hay de los perfiles en el proyecto: operaciones, tabla y sus filas, datos y las filas de parámetros."""
        with self.project.read() as conn:
            made = conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (road_profiles.TABLE,)).fetchone() is not None
            return {
                "operations": conn.execute("SELECT op_type, status FROM gb_operation WHERE op_type LIKE 'des.%' "
                                           "ORDER BY fid").fetchall(),
                "table": made,
                "rows": conn.execute(f"SELECT code, name FROM {road_profiles.TABLE} ORDER BY fid").fetchall() if made else None,
                "datasets": conn.execute("SELECT name FROM gb_dataset WHERE name LIKE 'des\\_%' ESCAPE '\\'").fetchall(),
                "params": conn.execute("SELECT key, scope_uid, rev FROM gb_parameter WHERE key LIKE 'des.roadprofile.%' "
                                       "ORDER BY key, scope_uid").fetchall(),
            }

    def stored(self) -> tuple[Any, ...]:
        with self.project.read() as conn:
            return road_profiles.read_profiles(conn)

    def value(self, code: str, field: str, version: Any = None) -> Any:
        """La fila del valor ``field`` del perfil ``code`` en el proyecto o en la versión."""
        return self.store.get(params.road_profile_key(code, field), version=version)

    def resolved(self, codes: list[str], version: Any = None) -> dict[str, Any]:
        """Clave → valor que resuelven los cálculos para esos perfiles (la versión y, si no, el proyecto o el valor por
        defecto de su definición)."""
        keys = [params.road_profile_key(code, param) for code in codes for param in Param]
        chain = ("version", "project") if version is not None else ("project",)
        with self.project.read() as conn:
            found = self.store.resolve_many(conn, keys, chain, version=version)
        values: dict[str, Any] = {}
        for key in keys:
            if key in found:
                text = found[key].value_json
                values[key] = None if text is None else json.loads(text)
            else:
                values[key] = core_params.definition(key).default
        return values

    def assertNothing(self, before: dict[str, Any]) -> None:  # noqa: N802
        """Que no se ha registrado nada desde ``before``: ni operación (ni fallida), ni tabla, ni fila, ni dato, ni parámetro."""
        self.assertEqual(self.state(), before)


class _SharedCase(_RoadProfilesCase):
    """Una copia del proyecto **por clase** con ``PISTA_PRINCIPAL`` y ``ACCESO_TAJO`` ya creados (en el proyecto), para las
    pruebas que solo rechazan (no escriben nada: :meth:`reject` lo comprueba) y las que escriben **perfiles propios** con
    nombres que no repite ninguna otra (cada prueba mira lo suyo: el orden no importa)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.project, cls.clock = cls.enterClassContext(dfx.open_design_project("gb-rp-"))
        cls.root = Path(cls.project.root)
        with cls.project.read() as conn:
            cls.v1, cls.v2 = (versions_read.version(conn, uid) for uid in dfx.project_template()["versions"])
        cls.store = core_params.ParameterStore(cls.project)
        cls.clock.advance(minutes=1)
        road_profiles.edit_road_profiles(cls.project, (new(MAIN), new(OTHER)), declaration())

    def setUp(self) -> None:
        pass  # el proyecto es el de la clase

    def reject(self, *edits: Any, **kw: Any) -> Any:
        """La edición se rechaza con un ``DesignError`` y no deja nada, ni una operación fallida."""
        before = self.state()
        with self.assertRaises(messages.DesignError) as caught:
            self.edit(*edits, **kw)
        self.assertNothing(before)
        return caught.exception


class TableTest(_RoadProfilesCase):
    def test_the_first_profile_creates_the_table_and_the_next_reuses_it(self) -> None:
        """RF-017-07 (plan §5.2.1 y P-2): sin perfiles no hay tabla (ni perfiles ni nombres, sin error); la tabla
        ``des_road_profile`` (``fid``, ``uid``, ``code``, ``name``, ``created_by``, ``created_at``, con su código y su nombre
        **únicos**) se crea en la transacción del primer perfil, en ``gpkg_contents`` como tabla de atributos, y se registra
        como dato del proyecto de ``des``, leído con ``core.gpkg_layer@1``, no editable en QGIS y salida de la operación; la
        segunda edición añade filas sin tocar las primeras y se registra en el mismo dato; los perfiles salen en el orden en
        que se crearon."""
        self.assertFalse(self.state()["table"])
        with self.project.read() as conn:
            self.assertEqual((road_profiles.read_profiles(conn), road_profiles.profile_names(conn)), ((), {}))
        made = self.edit(new(MAIN))
        with self.project.read() as conn:
            columns = [row[1] for row in conn.execute(f"PRAGMA table_info({road_profiles.TABLE})")]
            contents = conn.execute("SELECT data_type, identifier FROM gpkg_contents WHERE table_name = ?",
                                    (road_profiles.TABLE,)).fetchone()
            record = registry.get(conn, road_profiles.TABLE)
            roles = conn.execute("SELECT role FROM gb_operation_io WHERE operation_uid = ? AND direction = 'out'",
                                 (made.operation_uid,)).fetchall()
            titles = dict(conn.execute("SELECT column_name, title FROM gpkg_data_columns WHERE table_name = ?",
                                       (road_profiles.TABLE,)).fetchall())
            unique = set()
            for _seq, index, is_unique, *_rest in conn.execute(f"PRAGMA index_list({road_profiles.TABLE})").fetchall():
                if is_unique:
                    unique.add(tuple(row[2] for row in conn.execute(f"PRAGMA index_info({index})")))
            ddl = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (road_profiles.TABLE,)).fetchone()[0]
        self.assertEqual(columns, ["fid", "uid", "code", "name", "created_by", "created_at"])
        self.assertEqual(titles, {"uid": "Identificador", "code": "Código", "name": "Nombre", "created_by": "Creado por",
                                  "created_at": "Creado el"})
        self.assertEqual(contents, ("attributes", "Perfiles de pista"))
        self.assertEqual((record.module, record.kind, record.locator, record.reader, record.qgis_editable, record.status.value),
                         ("des", "table", road_profiles.TABLE, "core.gpkg_layer@1", False, "current"))
        self.assertEqual(record.operation_uid, made.operation_uid)
        self.assertEqual(roles, [(road_profiles.PROFILES_ROLE,)])
        self.assertEqual(self.state()["datasets"], [(road_profiles.TABLE,)])
        self.assertEqual(unique, {("uid",), ("code",), ("name",)})
        copy = sqlite3.connect(":memory:")  # una copia en memoria: en el proyecto, un fallo de escritura lo deja en solo lectura
        self.addCleanup(copy.close)
        copy.execute(ddl)
        insert = (f"INSERT INTO {road_profiles.TABLE} (uid, code, name, created_by, created_at) "
                  "VALUES (?, ?, ?, 'x', '2026-11-20T10:00:00Z')")
        copy.execute(insert, ("u1", "pista_principal", MAIN))
        for uid, code, name in (("u2", "pista_principal", "Otro"), ("u3", "otro", MAIN), ("u1", "otro", "Otro")):
            with self.subTest(code=code, name=name), self.assertRaises(sqlite3.IntegrityError):
                copy.execute(insert, (uid, code, name))
        (first,) = self.stored()
        second = self.edit(new(OTHER))
        after = self.stored()
        self.assertEqual(after[0], first)
        self.assertEqual([item.code for item in after], ["pista_principal", "acceso_tajo"])
        self.assertNotEqual(made.operation_uid, second.operation_uid)
        with self.project.read() as conn:
            self.assertEqual(registry.get(conn, road_profiles.TABLE).operation_uid, second.operation_uid)
            self.assertEqual(road_profiles.profile_names(conn), {"pista_principal": MAIN, "acceso_tajo": OTHER})


class OperationTest(_SharedCase):
    def test_a_profile_is_a_row_and_thirteen_created_parameters(self) -> None:
        """RF-017-07, RF-017-08 (D-2; RF-008-01; plan §5.2.2): crear un perfil escribe su fila (código fijado del nombre,
        quién y cuándo) y los trece valores que se declaran siempre como parámetros ADOPTADO con su fuente, su decisor y su
        motivo, con una fila ``create`` en el historial, con la unidad de su familia y sin «sin confirmar»; el factor de
        malla y la métrica no se escriben (valen 1,0 y la exacta por su definición); dos perfiles en una llamada son
        **una** operación de proyecto, ``des.edit_road_profiles``, y con lo escrito los cálculos arman los mismos perfiles
        (con el nombre de la tabla) y sus derivados."""
        before = self.state()
        made = self.edit(new("Pista nueva"), new("Acceso nuevo", vehicle_width_m=2.5, lane_factor=2.0, berm_m=0.5,
                                                **{"class": "Acceso al tajo"}))
        self.assertEqual((made.created, made.renamed, made.completed), (("pista_nueva", "acceso_nuevo"), (), ()))
        self.assertEqual(self.state()["operations"], [*before["operations"], (road_profiles.EDIT_ROAD_PROFILES, "done")])
        (operation,) = road_profiles.OPERATIONS
        self.assertEqual((operation.op_type, operation.scope, operation.repeatable), ("des.edit_road_profiles", "project", False))
        row = {item.code: item for item in self.stored()}["pista_nueva"]
        self.assertEqual((row.name, row.created_by), ("Pista nueva", self.project.session.user_host))
        with self.project.read() as conn:
            started = conn.execute("SELECT started_at FROM gb_operation WHERE uid = ?", (made.operation_uid,)).fetchone()[0]
        self.assertEqual(row.created_at, started)
        expected = values_of()
        for param in REQUIRED:
            with self.subTest(field=param.value):
                record = self.value(row.code, param)
                self.assertEqual(record.value, expected[param.value])
                self.assertEqual((record.kind, record.source_kind, record.source),
                                 ("ADOPTADO", "person", "ITC 07.1.03 de la prueba"))
                self.assertEqual((record.decided_by, record.reason, record.unconfirmed), (NOBODY, "Perfil de la spec 017", False))
                self.assertEqual((record.scope, record.scope_uid, record.rev), ("project", "", 1))
                history = self.store.history(params.road_profile_key(row.code, param))
                self.assertEqual([(entry.rev, entry.action.value) for entry in history], [(1, "create")])
        self.assertEqual((self.value(row.code, "vehicle_width_m").unit, self.value(row.code, "max_gradient_pct").unit), ("m", "%"))
        for last in OPTIONAL:
            self.assertIsNone(self.value(row.code, last))
        resolved = self.resolved(list(made.created))
        self.assertEqual((resolved["des.roadprofile.pista_nueva.mesh_factor"], resolved["des.roadprofile.pista_nueva.metric"]),
                         (1.0, "exact"))
        with self.project.read() as conn:
            names = road_profiles.profile_names(conn)
        found = road_profiles.road_profiles_from(resolved, made.created, names)
        self.assertEqual((found["pista_nueva"].name, found["acceso_nuevo"].name), ("Pista nueva", "Acceso nuevo"))
        self.assertEqual(found["pista_nueva"], profile_of("pista_nueva", "Pista nueva"))
        small = road_profiles.derived(found["acceso_nuevo"])
        self.assertEqual((small.carriageway_m, small.section_m, small.half_width_m), (5.0, 5.5, 2.75))
        self.assertEqual(found["acceso_nuevo"].class_name, "Acceso al tajo")

    def test_renaming_does_not_change_the_code_or_the_values_and_a_swap_is_valid(self) -> None:
        """RF-017-07, RF-017-04 (D-17): renombrar un perfil cambia solo su nombre: el código (la clave de sus parámetros),
        su ``uid``, quién lo creó y cuándo siguen igual, y sus valores y su historial no se tocan (sigue en la revisión 1);
        el renombrado es una operación registrada y el código antiguo no se reutiliza para un perfil nuevo; cambiar solo las
        mayúsculas es renombrar el mismo perfil, no repetir un nombre; y los nombres se miden sobre los que quedan:
        intercambiar los de dos perfiles en la misma llamada es válido y no se queda a medias."""
        self.edit(new("Rampa norte"), new("Rampa sur", reach_m=40.0))
        before = {item.code: item for item in self.stored()}["rampa_norte"]
        values_before = self.resolved(["rampa_norte"])
        made = self.edit(road_profiles.ProfileEdit(code="rampa_norte", name="Rampa del norte"), declared=None)
        after = {item.code: item for item in self.stored()}["rampa_norte"]
        self.assertEqual(after.name, "Rampa del norte")
        self.assertEqual((after.fid, after.uid, after.code, after.created_by, after.created_at),
                         (before.fid, before.uid, before.code, before.created_by, before.created_at))
        self.assertEqual(self.resolved(["rampa_norte"]), values_before)
        self.assertEqual(self.value("rampa_norte", "vehicle_width_m").rev, 1)
        self.assertEqual((made.created, made.renamed, made.completed), ((), ("rampa_norte",), ()))
        self.assertEqual(self.state()["operations"][-1], (road_profiles.EDIT_ROAD_PROFILES, "done"))
        self.edit(road_profiles.ProfileEdit(code="rampa_norte", name="RAMPA DEL NORTE"), declared=None)
        self.assertEqual({item.code: item.name for item in self.stored()}["rampa_norte"], "RAMPA DEL NORTE")
        self.assertEqual(self.edit(new("Rampa norte")).created, ("rampa_norte_2",))
        self.edit(road_profiles.ProfileEdit(code="rampa_norte", name="Rampa sur"),
                  road_profiles.ProfileEdit(code="rampa_sur", name="RAMPA DEL NORTE"), declared=None)
        names = {item.code: item.name for item in self.stored()}
        self.assertEqual((names["rampa_norte"], names["rampa_sur"]), ("Rampa sur", "RAMPA DEL NORTE"))
        self.assertEqual((self.value("rampa_norte", "reach_m").value, self.value("rampa_sur", "reach_m").value), (60.0, 40.0))

    def test_a_profile_is_completed_in_a_version_with_its_radii_checked_on_the_effective_values(self) -> None:
        """RF-017-07, RF-017-04 (RF-009-24): completar un perfil en V02 con el factor de malla y la métrica le escribe su valor
        propio de la versión (fila ``create`` del historial de la versión) sin tocar el del proyecto ni crear otra fila de
        perfil, y los cálculos arman el perfil de esa versión; los radios de lo que se completa se comprueban con los valores
        **efectivos** del ámbito (los de la versión y, si no, los del proyecto) más los que se dan: con A = 3,5 m y f = 3, un
        caballón de 5 m hace la semianchura 7,75 m, mayor que el radio mínimo de 7 m que se da, y un radio mínimo de 25 m es
        mayor que el radio de 20 m; los dos se rechazan sin escribir nada y uno que cabe, vale."""
        self.edit(new("Pista a completar"))
        project_row = self.value("pista_a_completar", "reach_m")
        count = len(self.stored())
        made = self.edit(road_profiles.ProfileEdit(code="pista_a_completar", values={"mesh_factor": 0.9, "metric": "chamfer5"}),
                         declared=declaration(version=self.v2.code, reason="Malla de la alternativa"))
        own = self.value("pista_a_completar", "mesh_factor", version=self.v2.code)
        self.assertEqual((own.value, own.kind, own.scope, own.scope_uid, own.rev), (0.9, "ADOPTADO", "version", self.v2.uid, 1))
        self.assertEqual(self.value("pista_a_completar", "metric", version=self.v2.code).value, "chamfer5")
        self.assertIsNone(self.value("pista_a_completar", "reach_m", version=self.v2.code))
        self.assertEqual(self.value("pista_a_completar", "reach_m"), project_row)
        self.assertEqual((made.created, made.renamed, made.completed), ((), (), ("pista_a_completar",)))
        self.assertEqual(len(self.stored()), count)
        found = road_profiles.road_profiles_from(self.resolved(["pista_a_completar"], self.v2.code), ["pista_a_completar"])
        self.assertEqual((found["pista_a_completar"].mesh_factor, found["pista_a_completar"].metric,
                          found["pista_a_completar"].reach_m), (0.9, "chamfer5", 60.0))
        for values, code in (({"berm_m": 5.0, "min_radius_m": 7.0}, "des.road_profile_radius_narrow"),
                             ({"min_radius_m": 25.0}, "des.road_profile_radius_order")):
            with self.subTest(values=values):
                error = self.reject(road_profiles.ProfileEdit(code="pista_a_completar", values=values),
                                    declared=declaration(version=self.v2.code))
                self.assertEqual((error.code, error.field), (code, "des.roadprofile.pista_a_completar.min_radius_m"))
        self.edit(road_profiles.ProfileEdit(code="pista_a_completar", values={"min_radius_m": 15.0, "berm_m": 2.0}),
                  declared=declaration(version=self.v2.code))
        self.assertEqual(self.value("pista_a_completar", "min_radius_m", version=self.v2.code).value, 15.0)

    def read_profile(self, code: str) -> str:
        """Registra una «pista» de prueba en V01 que lee los valores de su perfil ``code`` (lo que lee la real, según
        ``provenance.road_params``) y devuelve su uid."""
        keys = [key for key in provenance.road_params("RDW-001", mode="on_axis", profile=code)
                if key.startswith(f"des.roadprofile.{code}.")]
        self.assertEqual(len(keys), 14)  # los catorce que cambian el resultado (no la clase normativa)
        self.clock.advance(minutes=1)
        handle = operations.begin_operation(self.project, provenance.ROAD, settings={"profile": code}, inputs=[], params=keys,
                                            executor="blender", version=self.v1.uid)
        with self.project.write_transaction() as conn:
            handle.complete(conn, outputs=[])
        return str(handle.uid)

    def causes(self, uid: str) -> set[tuple[str, str]]:
        """Las causas de obsolescencia de la operación (la caché ``gb_stale`` de la 008): su clase y, por su nombre, lo que
        cambió (la clave del parámetro)."""
        with self.project.read() as conn:
            rows = conn.execute("SELECT cause_kind, subject_uid FROM gb_stale WHERE item_kind = 'operation' AND item_uid = ?",
                                (uid,)).fetchall()
            return {(kind, (conn.execute("SELECT key FROM gb_parameter WHERE uid = ?", (subject,)).fetchone() or (subject,))[0])
                    for kind, subject in rows}

    def test_changing_a_value_of_a_profile_makes_obsolete_only_the_roads_that_use_it(self) -> None:
        """RF-017-07, RF-009-24 (plan §5.2.2: el perfil es de la versión y cambiar uno de sus valores deja obsoletas las pistas
        que lo usan, con su causa, por el grafo de la 008; una operación **sintética** de tipo ``des.road`` hace de la pista
        que leerán las tareas siguientes): con los valores propios de V01 (y ninguno del proyecto), un valor cambiado de un
        perfil deja obsoleta la pista de prueba que lo lee, con la causa «cambió el parámetro» y su clave; la que usa otro
        perfil sigue al día; y la clase normativa, que no lee la pista ni cambia un cálculo, no deja obsoleta ninguna."""
        self.edit(new("Pista de V01"), new("Acceso de V01"), declared=declaration(version=self.v1.code))
        self.assertIsNone(self.value("pista_de_v01", "max_gradient_pct"))  # nada en el proyecto
        self.assertEqual(self.value("pista_de_v01", "max_gradient_pct", version=self.v1.code).scope, "version")
        uses_main, uses_other = self.read_profile("pista_de_v01"), self.read_profile("acceso_de_v01")
        self.assertEqual((self.causes(uses_main), self.causes(uses_other)), (set(), set()), "al crearlas, están al día")
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            self.store.change(conn, params.road_profile_key("pista_de_v01", "class"), value="Acceso al tajo",
                              reason="Cambio de la clase normativa", version=self.v1.code)
        self.assertEqual(self.causes(uses_main), set())
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            self.store.change(conn, params.road_profile_key("pista_de_v01", "max_gradient_pct"), value=8.0,
                              reason="Pendiente máxima de la ITC revisada", version=self.v1.code)
        self.assertEqual(self.causes(uses_main), {("parameter_changed", "des.roadprofile.pista_de_v01.max_gradient_pct")})
        self.assertEqual(self.causes(uses_other), set())
        self.assertEqual(self.value("pista_de_v01", "max_gradient_pct", version=self.v1.code).value, 8.0)


class RejectionTest(_SharedCase):
    def test_a_profile_without_a_name_is_rejected(self) -> None:
        """RF-017-04: un perfil sin nombre (vacío, de espacios, ``None``) se rechaza con ``des.road_profile_name_missing``
        nombrando el campo y el valor, antes de registrar nada; con varios nuevos, se nombra el que falla."""
        for name in ("", "\t"):
            with self.subTest(name=name):
                error = self.reject(new(name))
                self.assertEqual((error.code, error.field, error.value), ("des.road_profile_name_missing", "name", name))
        self.assertEqual(self.reject(road_profiles.ProfileEdit(name=None, values=values_of())).code,
                         "des.road_profile_name_missing")
        self.assertIn("nuevo 2", self.reject(new("Tercera"), new(" ")).text)
        error = self.reject(road_profiles.ProfileEdit(code="acceso_tajo", name="  "), declared=None)
        self.assertEqual(error.code, "des.road_profile_name_missing")
        self.assertIn("«acceso_tajo»", error.text)

    def test_a_repeated_name_is_rejected_naming_both(self) -> None:
        """RF-017-04: un nombre que ya es de otro perfil (sin distinguir mayúsculas ni espacios en los bordes) se rechaza con
        ``des.road_profile_name_repeated`` nombrando los dos; también dos nuevos con el mismo nombre en la misma llamada y
        un renombrado al nombre de otro perfil. Nada queda escrito."""
        for name in (MAIN, " pista_PRINCIPAL "):
            with self.subTest(name=name):
                error = self.reject(new(name))
                self.assertEqual((error.code, error.field), ("des.road_profile_name_repeated", "name"))
                self.assertIn("pista_principal_2", error.text)
                self.assertIn("«pista_principal»", error.text)
        self.assertEqual(self.reject(new("Tercera"), new("tercera")).code, "des.road_profile_name_repeated")
        error = self.reject(road_profiles.ProfileEdit(code="acceso_tajo", name=" pista_principal"), declared=None)
        self.assertEqual(error.code, "des.road_profile_name_repeated")
        self.assertIn("«acceso_tajo»", error.text)
        self.assertIn("«pista_principal»", error.text)

    def test_an_incomplete_profile_is_rejected_naming_the_profile_and_the_field(self) -> None:
        """RF-017-04, RF-017-07 (D-2): sin alguno de los trece valores (que falte la clave o sea ``None``) se rechaza con
        ``des.road_profile_value_missing`` nombrando el perfil por su nombre, la clave del campo y el valor; no hay valor por
        defecto que lo tape. Nada queda escrito."""
        for field in ("vehicle_width_m", "min_radius_m", "reach_m", "class"):
            with self.subTest(field=field):
                error = self.reject(new("Tercera", **{field: None}))
                self.assertEqual((error.code, error.field, error.value),
                                 ("des.road_profile_value_missing", f"des.roadprofile.tercera.{field}", None))
                self.assertEqual(error.obj, "Perfil de pista «Tercera»")
                self.assertIn("«Tercera»", error.text)
        error = self.reject(road_profiles.ProfileEdit(name="Tercera"))
        self.assertEqual((error.code, error.field), ("des.road_profile_value_missing", "des.roadprofile.tercera.vehicle_width_m"))
        error = self.reject(new("Tercera", **{"class": "   "}))
        self.assertEqual((error.code, error.field), ("des.road_profile_value_missing", "des.roadprofile.tercera.class"))

    def test_a_value_out_of_range_or_a_radius_that_does_not_fit_is_rejected(self) -> None:
        """RF-017-04, RF-017-07: un vehículo de 0 m, un arcén negativo, un ángulo de 90°, un factor de malla de más de 1, una
        métrica desconocida y un NaN se rechazan con ``des.road_profile_value_range``; un radio mínimo mayor que el radio, o
        menor que la semianchura de la sección (5,75 m con A = 3,5 m, f = 3, arcén 0 m y caballón 1 m), con
        ``des.road_profile_radius_order`` o ``_narrow``, nombrando el perfil, la clave del campo y el valor; un valor que no
        es un número, o una clave que no es de un perfil, un error del programa."""
        bad = (("vehicle_width_m", 0.0), ("shoulder_m", -1.0), ("cut_angle_deg", 90.0), ("mesh_factor", 1.5),
               ("metric", "manhattan"), ("vehicle_width_m", math.nan))
        for field, value in bad:
            with self.subTest(field=field, value=value):
                error = self.reject(new("Tercera", **{field: value}))
                self.assertEqual((error.code, error.field), ("des.road_profile_value_range", f"des.roadprofile.tercera.{field}"))
                self.assertIn("«Tercera»", error.text)
                if isinstance(value, float) and math.isfinite(value):
                    self.assertEqual(error.value, value)
        error = self.reject(new("Tercera", min_radius_m=25.0))
        self.assertEqual((error.code, error.field, error.value),
                         ("des.road_profile_radius_order", "des.roadprofile.tercera.min_radius_m", 25.0))
        error = self.reject(new("Tercera", min_radius_m=5.7))
        self.assertEqual((error.code, error.field, error.value),
                         ("des.road_profile_radius_narrow", "des.roadprofile.tercera.min_radius_m", 5.7))
        self.assertIn("5,75", error.text)
        self.assertEqual(self.reject(new("Tercera", berm_m=3.0, min_radius_m=6.0)).code, "des.road_profile_radius_narrow")
        before = self.state()
        with self.assertRaises(TypeError):
            self.edit(new("Tercera", vehicle_width_m=True))
        with self.assertRaises(ValueError):
            self.edit(road_profiles.ProfileEdit(name="Tercera", values={"altura": 5.0}))
        self.assertNothing(before)

    def test_everything_is_looked_at_before_writing_anything(self) -> None:
        """RF-017-04: se mira todo antes de escribir nada: un perfil válido y otro con un valor fuera de rango no dejan
        ninguno de los dos; y un valor que se completa fuera de rango o sin valor se rechaza nombrando el perfil por su
        NOMBRE (no su código), la clave del campo y el valor."""
        error = self.reject(new("Tercera"), new("Cuarta", fill_angle_deg=95.0))
        self.assertEqual(error.code, "des.road_profile_value_range")
        self.assertNotIn("tercera", [item.code for item in self.stored()])
        for values, code in (({"mesh_factor": 1.5}, "des.road_profile_value_range"),
                             ({"metric": None}, "des.road_profile_value_missing")):
            with self.subTest(values=values):
                error = self.reject(road_profiles.ProfileEdit(code="pista_principal", values=values),
                                    declared=declaration(version=self.v2.code))
                self.assertEqual((error.code, error.obj), (code, "Perfil de pista «PISTA_PRINCIPAL»"))
                self.assertEqual(error.field, f"des.roadprofile.pista_principal.{next(iter(values))}")

    def test_an_edit_that_changes_nothing_is_a_program_error(self) -> None:
        """RF-017-04: una edición que no cambia nada (el mismo nombre y sin valores), de un perfil que no existe, repetida en
        la misma llamada o con valores sin declaración es un error del programa (``ValueError``) y no deja nada."""
        before = self.state()
        edits = (road_profiles.ProfileEdit(code="acceso_tajo", name=OTHER), road_profiles.ProfileEdit(code="acceso_tajo"),
                 road_profiles.ProfileEdit(code="no_existe", name="Otro"))
        for edit in edits:
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                self.edit(edit, declared=None)
        with self.assertRaises(ValueError):
            self.edit(road_profiles.ProfileEdit(code="acceso_tajo", name="Uno"),
                      road_profiles.ProfileEdit(code="acceso_tajo", name="Otro"), declared=None)
        with self.assertRaises(ValueError):
            self.edit(road_profiles.ProfileEdit(code="acceso_tajo", values={"mesh_factor": 0.9}), declared=None)
        self.assertNothing(before)


class DeclarationTest(unittest.TestCase):
    def test_the_operation_is_declared_for_bl_and_has_its_spanish(self) -> None:
        """RF-017-07: ``des.edit_road_profiles`` es una operación de proyecto, de ``des``, no repetible, que lanza la orden
        del catálogo, y su nombre visible está en español en el catálogo de mensajes."""
        (operation,) = road_profiles.OPERATIONS
        self.assertEqual(operation.op_type, "des.edit_road_profiles")
        self.assertEqual((operation.module, operation.scope, operation.repeatable), ("des", "project", False))
        self.assertEqual(operation.commands, ("geoblender.des_edit_road_profile",))
        table = i18n.load_messages()
        self.assertIn(operation.label_msgid, table)
        self.assertNotEqual(table[operation.label_msgid], operation.label_msgid)

    def test_the_dataset_is_not_editable_in_qgis(self) -> None:
        """RF-017-07 (plan §5.2.1): el dato de los perfiles es una tabla de atributos de ``des`` que se lee con
        ``core.gpkg_layer@1`` y no se edita en QGIS (los valores están en parámetros, con su historial)."""
        spec = road_profiles.dataset_spec()
        self.assertEqual((spec.name, spec.module, spec.kind, spec.locator, spec.reader, spec.role, spec.qgis_editable),
                         ("des_road_profile", "des", "table", "des_road_profile", "core.gpkg_layer@1", "road_profiles", False))


if __name__ == "__main__":
    unittest.main()

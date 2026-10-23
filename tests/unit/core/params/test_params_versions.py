# SPDX-License-Identifier: GPL-3.0-or-later
"""Parámetros por versión (spec 009, T06; RF-009-24, RF-009-29, RF-009-04, RF-009-01; plan 009
A1, A3 y D-19).

``core.params.ParameterStore`` guarda, además del valor del proyecto, el de cada versión en los
parámetros que su módulo admite por versión (``ParamDef(scope="version")``; ``gb_parameter`` con
``scope = 'version'`` y ``scope_uid`` = el uid de la versión), con su historial:

- ``change(…, version=V)`` crea la fila de la versión (la primera vez, a partir del valor que
  hoy vale en ella, el del proyecto) o la cambia, con su motivo y su historial, y no toca el del
  proyecto ni el de otra versión (RF-009-29); ``create``, ``get`` e ``history`` admiten también
  ``version=`` (su uid o su código);
- ``resolve(…, ("version", "project"), version=V)`` da el de la versión si lo tiene y, si no, el
  del proyecto, con el ámbito y la revisión del historial que se usó (RF-009-24, D-19);
- un parámetro del proyecto (los de la 005 y la 006) no admite versión;
- en una versión SUPERADO o DESCARTADO, crear, cambiar o confirmar uno se rechaza con el texto
  de RF-009-04 antes de escribir (y, si se escribe en la base a mano, lo rechaza el disparador);
  la marca «revisar» de un cambio de definición no la toca (RF-008-60);
- ``list`` sigue siendo la lista del proyecto y ``scopes`` da el valor de cada ámbito (el del
  proyecto y los de cada versión, por número), para «V11: 1,25 [HIP] · proyecto: 1,23 [ADO]»;
- crear una versión que parte de otra le copia sus parámetros de versión con su fila de
  historial «Heredado de V01.r2» (``inherit``; RF-009-01, D-26).

Cada prueba crea su proyecto sintético (esquema 3) con un reloj simulado, el K de esponjamiento
del proyecto (1,23 ADOPTADO) y las versiones V01 y V02 en BORRADOR; las revisiones se congelan
con SQL (congelar es la T13).
"""

from __future__ import annotations

import sqlite3
import unittest
import uuid
from collections.abc import Callable
from typing import Any

from tests.support.core_fixtures import FakeClock, make_session, make_settings, project_tmp
from tests.support.package import import_geoblender

create = import_geoblender("core.project.create")
userdata_mod = import_geoblender("core.userdata")
params = import_geoblender("core.params")
store_mod = import_geoblender("core.params.store")
versions_model = import_geoblender("core.versions.model")
versions_schema = import_geoblender("core.versions.schema")
versions_store = import_geoblender("core.versions.store")
hashing = import_geoblender("core.hashing")
timeutil = import_geoblender("core.timeutil")
gis_params = import_geoblender("gis.params")
dh_params = import_geoblender("drillholes.params")

SESSION = make_session()
USER = SESSION.user_host
NOW = "2026-10-18T10:00:00.000Z"

K = "res.swell_factor"
"""De versión (D-19): el proyecto tiene 1,23 ADOPTADO y una versión puede probar otro."""
BENCH = "res.bench_height"
"""De versión, sin valor del proyecto."""
RECOVERY = "res.recovery"
"""Del proyecto: no admite versión."""

SWELL_DEF = params.ParamDef(
    K, "float", "-", 1.15, 1.0, 2.0, ("RF-009-29",), "Prueba: K de esponjamiento sin ensayo",
    kind="HIPÓTESIS", source_kind="document", scope="version",
)
DEFINITIONS = (
    SWELL_DEF,
    params.ParamDef(BENCH, "float", "m", 10.0, 0.0, 50.0, ("RF-009-24",),
                    "Prueba: altura de banco", min_exclusive=True, scope="version"),
    params.ParamDef(RECOVERY, "float", "-", 0.9, 0.0, 1.0, ("RF-009-24",),
                    "Prueba: recuperación minera"),
)
PROJECT_K: dict[str, Any] = {
    "kind": "ADOPTADO", "source": "Ensayo de la propiedad", "source_kind": "document",
    "decided_by": "La propiedad", "reason": "La propiedad adopta el K de su ensayo",
}
BY_HAND: dict[str, Any] = {
    "kind": "HIPÓTESIS", "source": "Bibliografía de calizas", "source_kind": "document",
    "decided_by": "Samuel (IMGA)",
}
NOT_EDITABLE = "{code} está en estado {state}: cree una versión nueva a partir de ella"
"""El rechazo de RF-009-04 («V09 está en estado SUPERADO: cree una versión nueva a partir de
ella»)."""
PROJECT_ONLY = "El parámetro «{key}» es del proyecto: no admite un valor propio en {code}."
TABLES = ("gb_parameter", "gb_parameter_history")


def _sha(value: object, unit: str) -> str:
    """``value_sha256`` (plan 008, D10): sha256 del JSON canónico de ``{value, unit}``."""
    return hashing.sha256_bytes(hashing.canonical_json({"unit": unit, "value": value}))


def _uid() -> str:
    return str(uuid.uuid4())


class VersionScopeCase(unittest.TestCase):
    """Un proyecto nuevo por prueba (``self.project``) con las definiciones de prueba de
    ``res`` registradas, el K del proyecto (``self.k``) y las versiones ``self.v1`` (V01) y
    ``self.v2`` (V02) en BORRADOR."""

    def setUp(self) -> None:
        params.register_definitions(DEFINITIONS)
        self.addCleanup(params.unregister_definitions, "res")
        tmp = self.enterContext(project_tmp("gb-t06-"))
        parent = tmp / "proyectos"
        parent.mkdir()
        self.clock = FakeClock()
        self.project = create.create_project(
            parent, make_settings(), SESSION, userdata_mod.UserData(tmp / "u"), clock=self.clock
        ).project
        self.addCleanup(self.project.close)
        self.store = store_mod.ParameterStore(self.project)
        self.k = self.write(lambda conn: self.store.create(conn, K, 1.23, **PROJECT_K))
        self.v1 = self.new_version("definitiva", "Definitiva")
        self.v2 = self.new_version("ampliacion", "Ampliación")

    # Ayudas -------------------------------------------------------------------------------

    def write(self, work: Callable[[sqlite3.Connection], Any]) -> Any:
        with self.project.write_transaction() as conn:
            return work(conn)

    def tick(self) -> str:
        self.clock.advance(minutes=1)
        return timeutil.format_utc(self.clock.now())

    def new_version(self, feature: str, title: str, parent: str | None = None) -> Any:
        self.tick()
        version, _ = self.write(lambda conn: versions_store.create_version(
            conn, self.project, feature=feature, title=title, reason="Prueba", parent=parent))
        return version

    def change(self, version: str | None, value: float, reason: str, **fields: Any) -> Any:
        """Cambia el K en ``version`` (``None``: el del proyecto), como HIPÓTESIS si no se
        dice otro tipo; el origen y el decisor, los que tenía."""
        fields.setdefault("kind", "HIPÓTESIS")
        self.tick()
        return self.write(lambda conn: self.store.change(
            conn, K, value=value, reason=reason, version=version, **fields))

    def rows(self, scope_uid: str = "") -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
        """Las filas de ``gb_parameter`` de un ámbito (``""``: el proyecto) y su historial."""
        with self.project.read() as conn:
            return (
                conn.execute("SELECT * FROM gb_parameter WHERE scope_uid = ? ORDER BY fid",
                             (scope_uid,)).fetchall(),
                conn.execute(
                    "SELECT h.* FROM gb_parameter_history AS h JOIN gb_parameter AS p "
                    "ON p.uid = h.parameter_uid WHERE p.scope_uid = ? ORDER BY h.fid",
                    (scope_uid,)).fetchall(),
            )

    def dump(self) -> dict[str, list[tuple[Any, ...]]]:
        with self.project.read() as conn:
            return {table: conn.execute(f"SELECT * FROM {table} ORDER BY fid").fetchall()
                    for table in TABLES}

    def freeze(self, version: Any) -> None:
        """Congela con SQL la revisión abierta de ``version`` y abre la siguiente."""

        def work(conn: sqlite3.Connection) -> None:
            uid, number = conn.execute(
                "SELECT uid, number FROM gb_revision WHERE version_uid = ? AND state = 'open'",
                (version.uid,),
            ).fetchone()
            conn.execute(
                "UPDATE gb_revision SET state = 'frozen', closed_at = ?, closed_by = ?, "
                "snapshot_dir = ?, snapshot_sha256 = ?, snapshot_bytes = 0, "
                "geoblender_version = ? WHERE uid = ?",
                (NOW, USER, f"snapshots/{version.code}.r{number}", "a" * 64, "0.1.0", uid),
            )
            conn.execute(
                "INSERT INTO gb_revision (uid, version_uid, number, state, reason, created_at, "
                "created_by) VALUES (?, ?, ?, 'open', 'Siguiente', ?, ?)",
                (_uid(), version.uid, number + 1, NOW, USER),
            )

        self.write(work)

    def set_status(self, version: Any, target: str, reason: str | None = None) -> None:
        self.tick()
        self.write(lambda conn: versions_store.set_status(conn, self.project, version.uid,
                                                          target, reason=reason))

    def assertRejected(self, *cases: tuple[type[Exception], str,
                                           Callable[[sqlite3.Connection], Any]]) -> list[Any]:
        """Cada caso (clase del error, código, trabajo) se rechaza con su código antes de
        escribir nada, en una sola transacción; al final nada ha cambiado y el proyecto sigue
        en escritura (un rechazo no es un fallo de la base). Devuelve los errores."""
        before = self.dump()
        found: list[Any] = []
        with self.project.write_transaction() as conn:
            for kind, code, work in cases:
                with self.subTest(code=code):
                    with self.assertRaises(kind) as caught:
                        work(conn)
                    self.assertEqual(caught.exception.code, code, str(caught.exception))
                    found.append(caught.exception)
        self.assertTrue(self.project.writable)
        self.assertEqual(self.dump(), before)
        return found


class ChangeTest(VersionScopeCase):
    def test_change_in_a_version_creates_then_changes_its_row(self) -> None:
        """RF-009-29 (D-19; RF-008-02): cambiar el K en V01 crea su fila de la versión (a
        partir del valor que hoy vale en ella, el del proyecto: mismo origen y decisor si no
        se dan) con una fila ``create`` de historial con su motivo, quién y cuándo; cambiarlo
        otra vez añade la ``change`` (rev 2); ni el K del proyecto ni el de V02 cambian, y
        cambiar el del proyecto o el de V02 no cambia el de V01. ``get`` e ``history`` lo leen
        por el uid o por el código de la versión."""
        project_before = self.rows()
        made_at = self.tick()
        record = self.write(lambda conn: self.store.change(
            conn, K, value=1.25, kind="HIPÓTESIS", reason="Prueba del esponjamiento en V01",
            version="V01"))
        self.assertEqual(
            (record.key, record.scope, record.scope_uid, record.module, record.value,
             record.value_json, record.unit, record.kind, record.source, record.source_kind,
             record.decided_by, record.decided_at, record.reason, record.unconfirmed,
             record.review, record.value_sha256, record.rev, record.created_at),
            (K, "version", self.v1.uid, "res", 1.25, "1.25", "-", "HIPÓTESIS",
             "Ensayo de la propiedad", "document", "La propiedad", made_at,
             "Prueba del esponjamiento en V01", False, None, _sha(1.25, "-"), 1, made_at),
        )
        self.assertNotEqual(record.uid, self.k.uid)
        self.assertEqual(record.def_sha256, params.definition_sha256(SWELL_DEF))
        self.assertEqual(self.store.get(K, version="V01"), record)
        self.assertEqual(self.store.get(K, "version", version=self.v1.uid), record)
        history = self.store.history(K, version=self.v1.uid)
        self.assertEqual(
            [(e.parameter_uid, e.rev, e.action, e.value, e.kind, e.reason, e.changed_by,
              e.changed_at, e.session_uid) for e in history],
            [(record.uid, 1, "create", 1.25, "HIPÓTESIS", "Prueba del esponjamiento en V01",
              USER, made_at, SESSION.session_uid)],
        )
        self.assertEqual(self.rows(), project_before)
        self.assertEqual(self.store.get(K), self.k)
        self.assertEqual(len(self.store.history(K)), 1)
        self.assertIsNone(self.store.get(K, version="V02"))
        self.assertEqual(self.store.history(K, version="V02"), [])

        # Otra vez en V01: su revisión 2; el proyecto, igual.
        changed = self.change("V01", 1.27, "Segundo ensayo en V01")
        self.assertEqual((changed.uid, changed.rev, changed.value), (record.uid, 2, 1.27))
        self.assertEqual([(e.rev, e.action, e.reason)
                          for e in self.store.history(K, version="V01")],
                         [(1, "create", "Prueba del esponjamiento en V01"),
                          (2, "change", "Segundo ensayo en V01")])
        self.assertEqual(self.rows(), project_before)

        # El del proyecto y el de V02 cambian sin tocar el de V01.
        v01 = self.rows(self.v1.uid)
        self.change(None, 1.24, "Nuevo ensayo de la propiedad")
        v02 = self.change(self.v2.uid, 1.30, "Prueba de V02")
        self.assertEqual(self.rows(self.v1.uid), v01)
        self.assertEqual((v02.scope_uid, v02.rev, v02.value), (self.v2.uid, 1, 1.30))
        self.assertEqual((self.store.get(K).value, self.store.get(K).rev), (1.24, 2))
        self.assertEqual(self.store.get(K, version="V01").value, 1.27)

    def test_create_in_a_version_and_its_rejections(self) -> None:
        """RF-009-29, RF-008-01, RF-008-02: ``create(…, version=)`` da de alta el valor de una
        versión con tipo, origen, decisor y motivo (aunque el proyecto no tenga el parámetro),
        y no dos veces; sin motivo, el alta de la fila de la versión pide el motivo de su valor;
        cambiar en una versión lo que no tiene ni ella ni el proyecto no está registrado; una
        versión que no existe se nombra."""
        made_at = self.tick()
        bench = self.write(lambda conn: self.store.create(
            conn, BENCH, 12.0, version="V01", reason="Bancos de 12 m en V01", **BY_HAND))
        self.assertEqual(
            (bench.scope, bench.scope_uid, bench.value, bench.unit, bench.kind, bench.rev,
             bench.created_at),
            ("version", self.v1.uid, 12.0, "m", "HIPÓTESIS", 1, made_at))
        self.assertIsNone(self.store.get(BENCH))
        self.assertEqual([entry.action for entry in self.store.history(BENCH, version="V01")],
                         ["create"])
        k_v2 = self.write(lambda conn: self.store.create(
            conn, K, 1.31, version="V02", reason="K propio de V02", **BY_HAND))
        self.assertEqual((k_v2.scope_uid, k_v2.value), (self.v2.uid, 1.31))
        errors = self.assertRejected(
            (params.ParamError, "core.param_exists", lambda conn: self.store.create(
                conn, BENCH, 15.0, version="V01", reason="Otra vez", **BY_HAND)),
            (params.ParamError, "core.param_reason_missing_new", lambda conn: self.store.change(
                conn, K, value=1.25, version="V01")),
            (params.ParamError, "core.param_not_registered", lambda conn: self.store.change(
                conn, BENCH, value=8.0, reason="Bancos de 8 m", version="V02")),
            (versions_model.VersionError, "core.version_unknown", lambda conn: self.store.change(
                conn, K, value=1.25, reason="Prueba", version="V09")),
            (params.ParamError, "core.param_out_of_range", lambda conn: self.store.change(
                conn, K, value=2.5, reason="Fuera de rango", version="V01")),
        )
        self.assertEqual(str(errors[1]), "Indique el motivo del valor de «res.swell_factor» (1,25).")
        self.assertEqual(str(errors[3]), "No hay ninguna versión V09 en el proyecto")
        for scope, version in (("version", None), ("project", "V01"), ("sector", None)):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                self.store.get(K, scope, version=version)
        with self.assertRaises(ValueError):
            self.store.history(K, "version")


class ResolveTest(VersionScopeCase):
    def test_version_value_then_project_value(self) -> None:
        """RF-009-24 (D-19; RF-008-05): con la cadena versión → proyecto, ``resolve`` da el
        valor de la versión si lo tiene (ámbito ``version``, su uid y la revisión de su
        historial) y, si no, el del proyecto; sin versión, el del proyecto. Un parámetro del
        proyecto se resuelve siempre en el proyecto; uno sin valor en ningún ámbito no se
        resuelve; la cadena y la versión tienen que ir juntas."""
        self.change("V01", 1.25, "Prueba en V01")
        v01 = self.change("V01", 1.26, "Segundo ensayo en V01")
        chain = ("version", "project")
        self.tick()
        self.write(lambda conn: (
            self.store.ensure_default(conn, RECOVERY, geoblender_version="0.3.0"),
            self.store.create(conn, BENCH, 12.0, version="V01", reason="Bancos", **BY_HAND)))
        with self.project.read() as conn:
            resolved = self.store.resolve(conn, K, chain, version="V01")
            self.assertEqual(resolved, store_mod.ResolvedParam(
                parameter_uid=v01.uid, key=K, scope="version", scope_uid=self.v1.uid, rev=2,
                value=1.26, value_json="1.26", unit="-", kind="HIPÓTESIS", unconfirmed=False,
                value_sha256=_sha(1.26, "-"),
            ))
            self.assertEqual(self.store.resolve(conn, K, chain, version=self.v1.uid), resolved)
            for version in ("V02", self.v2.uid):
                fallback = self.store.resolve(conn, K, chain, version=version)
                self.assertEqual(
                    (fallback.parameter_uid, fallback.scope, fallback.scope_uid, fallback.rev,
                     fallback.value, fallback.kind),
                    (self.k.uid, "project", "", 1, 1.23, "ADOPTADO"))
            self.assertEqual(self.store.resolve(conn, K).scope, "project")
            recovery = self.store.resolve(conn, RECOVERY, chain, version="V01")
            self.assertEqual((recovery.scope, recovery.value), ("project", 0.9))
            bench = self.store.resolve(conn, BENCH, chain, version="V01")
            self.assertEqual((bench.scope, bench.value, bench.unit), ("version", 12.0, "m"))
            for chain_tried in (chain, ("version",)):
                with self.subTest(chain=chain_tried), self.assertRaises(params.ParamError) as no:
                    self.store.resolve(conn, BENCH, chain_tried, version="V02")
                self.assertEqual(no.exception.code, "core.param_not_registered")
            with self.assertRaises(versions_model.VersionError) as unknown:
                self.store.resolve(conn, K, chain, version="V07")
            self.assertEqual(unknown.exception.code, "core.version_unknown")
            for wrong, version in (((), "V01"), (("version",), None), (chain, None),
                                   (("project",), "V01"), (("project", "sector"), None),
                                   (("version", "version", "project"), "V01")):
                with self.subTest(chain=wrong, version=version), self.assertRaises(ValueError):
                    self.store.resolve(conn, K, wrong, version=version)
            with self.assertRaises(TypeError):
                self.store.resolve(conn, K, "version", version="V01")


class ProjectOnlyTest(VersionScopeCase):
    def test_project_parameters_admit_no_version(self) -> None:
        """RF-009-24 (D-19): los parámetros de la 005 y de la 006 son del proyecto, y uno del
        proyecto no admite un valor por versión: darlo de alta o cambiarlo con ``version=`` se
        rechaza, nombrándolo, sin escribir nada; ninguna versión tiene valor suyo y ``scopes``
        solo da el del proyecto."""
        own = [definition for definition in (*gis_params.DEFINITIONS, *dh_params.DEFINITIONS)
               if definition.key not in params.DEFINITIONS]
        params.register_definitions(own)
        for module in sorted({definition.module for definition in own}):
            self.addCleanup(params.unregister_definitions, module)
        self.assertEqual((len(gis_params.DEFINITIONS), len(dh_params.DEFINITIONS)), (17, 8))
        self.assertEqual({definition.scope for definition in (*gis_params.DEFINITIONS,
                                                              *dh_params.DEFINITIONS)},
                         {"project"})
        interval, tolerance = "gis.contours.interval_m", dh_params.DEPTH_TOLERANCE
        self.write(lambda conn: [self.store.ensure_default(conn, key, geoblender_version="0.3.0")
                                 for key in (interval, tolerance, RECOVERY)])
        errors = self.assertRejected(
            (params.ParamError, "core.param_project_only", lambda conn: self.store.change(
                conn, interval, value=2.0, reason="Curvas cada 2 m en V01", version="V01",
                **BY_HAND)),
            (params.ParamError, "core.param_project_only", lambda conn: self.store.change(
                conn, tolerance, value=0.02, reason="Prueba", version=self.v2.uid, **BY_HAND)),
            (params.ParamError, "core.param_project_only", lambda conn: self.store.create(
                conn, RECOVERY, 0.95, version="V01", reason="Prueba", **BY_HAND)),
        )
        self.assertEqual(str(errors[0]), PROJECT_ONLY.format(key=interval, code="V01"))
        self.assertEqual(str(errors[1]), PROJECT_ONLY.format(key=tolerance, code="V02"))
        self.assertEqual(errors[0].values["version"], "V01")
        for key in (interval, tolerance, RECOVERY):
            with self.subTest(key=key):
                self.assertIsNone(self.store.get(key, version="V01"))
                self.assertEqual([record.scope for record in self.store.scopes(key)],
                                 ["project"])


class NotEditableTest(VersionScopeCase):
    """V01 SUPERADO y V03 DESCARTADO, cada una con su K; V02 VIGENTE con el suyo."""

    def setUp(self) -> None:
        super().setUp()
        self.change("V01", 1.25, "Prueba en V01")
        self.change("V02", 1.30, "Prueba en V02")
        self.v3 = self.new_version("descartada", "Descartada")
        self.change("V03", 1.40, "Prueba en V03")
        self.freeze(self.v1)
        self.set_status(self.v1, "VIGENTE")
        self.freeze(self.v2)
        self.set_status(self.v2, "VIGENTE")  # V01 pasa a SUPERADO (D-3)
        self.set_status(self.v3, "DESCARTADO", "No cumple")

    def test_rejected_in_a_version_that_is_not_editable(self) -> None:
        """RF-009-04: en una versión SUPERADO o DESCARTADO, crear, cambiar o confirmar un
        parámetro suyo se rechaza con «V01 está en estado SUPERADO: cree una versión nueva a
        partir de ella», sin escribir nada y sin dejar el proyecto en solo lectura; escrito en
        la base a mano, lo rechaza el disparador (``gb_parameter_version_ins`` y ``_upd``). En
        la VIGENTE sí se cambia."""
        cases = []
        for code in ("V01", self.v3.uid):
            cases += [
                (versions_model.VersionError, "core.version_not_editable",
                 lambda conn, code=code: self.store.change(
                     conn, K, value=1.26, reason="Otro", version=code)),
                (versions_model.VersionError, "core.version_not_editable",
                 lambda conn, code=code: self.store.create(
                     conn, BENCH, 12.0, version=code, reason="Bancos", **BY_HAND)),
                (versions_model.VersionError, "core.version_not_editable",
                 lambda conn, code=code: self.store.confirm(conn, K, version=code)),
            ]
        errors = self.assertRejected(*cases)
        self.assertEqual(str(errors[0]), NOT_EDITABLE.format(code="V01", state="SUPERADO"))
        self.assertEqual(str(errors[3]), NOT_EDITABLE.format(code="V03", state="DESCARTADO"))
        self.assertEqual(versions_model.render(errors[0].code, language="en", **errors[0].values),
                         "V01 is in state SUPERSEDED: create a new version from it")

        # La segunda barrera: quien escribe en la base sin pasar por el almacén.
        before = self.dump()
        k_v1 = self.store.get(K, version="V01")
        with self.project.write_transaction() as conn:
            row = conn.execute("SELECT * FROM gb_parameter WHERE uid = ?",
                               (k_v1.uid,)).fetchone()
            names = [column[0] for column in conn.execute(
                "SELECT * FROM gb_parameter LIMIT 0").description]
            copy = dict(zip(names, row, strict=True))
            copy.pop("fid")
            copy.update(uid=_uid(), key=BENCH)
            for sql, args in (
                (f"INSERT INTO gb_parameter ({', '.join(copy)}) "
                 f"VALUES ({', '.join('?' for _ in copy)})", tuple(copy.values())),
                ("UPDATE gb_parameter SET value = '1.5' WHERE uid = ?", (k_v1.uid,)),
            ):
                with self.subTest(sql=sql[:6]), self.assertRaises(sqlite3.IntegrityError) as db:
                    conn.execute(sql, args)
                self.assertIn(versions_schema.MSG_PARAMETER_VERSION, str(db.exception))
        self.assertEqual(self.dump(), before)
        self.assertEqual(self.change("V02", 1.32, "Segundo ensayo en V02").rev, 2)

    def test_definition_change_skips_closed_versions(self) -> None:
        """RF-009-04, RF-008-60: un cambio de la definición del K marca «revisar» el del
        proyecto y el de la versión VIGENTE, cada uno con su ámbito, y no el de V01 (SUPERADO)
        ni el de V03 (DESCARTADO), que no cambian (sin ese filtro, el disparador abortaría la
        comprobación de apertura); la lectura sin escribir da lo mismo, y confirmar el de V02
        quita su marca."""
        params.unregister_definitions("res")
        wider = params.ParamDef(
            K, "float", "-", 1.15, 1.0, 3.0, ("RF-009-29",), "Prueba: K de esponjamiento",
            kind="HIPÓTESIS", source_kind="document", scope="version")
        params.register_definitions((wider, *DEFINITIONS[1:]))
        closed = (self.rows(self.v1.uid), self.rows(self.v3.uid))
        found = self.store.definition_changes(params.DEFINITIONS)
        self.tick()
        written = self.write(lambda conn: self.store.mark_definition_changes(
            conn, params.DEFINITIONS))
        self.assertEqual(written, found)
        self.assertEqual([(change.key, change.scope, change.scope_uid) for change in written],
                         [(K, "project", ""), (K, "version", self.v2.uid)])
        self.assertEqual((self.rows(self.v1.uid), self.rows(self.v3.uid)), closed)
        self.assertIsNotNone(self.store.get(K, version="V02").review)
        self.tick()
        confirmed = self.write(lambda conn: self.store.confirm(conn, K, version="V02"))
        self.assertEqual((confirmed.scope_uid, confirmed.review, confirmed.rev),
                         (self.v2.uid, None, 2))
        self.assertEqual(self.store.history(K, version="V02")[-1].action, "confirm")
        self.assertIsNotNone(self.store.get(K).review)


class ScopesTest(VersionScopeCase):
    def test_list_is_the_project_and_scopes_gives_each_scope(self) -> None:
        """RF-009-29 (RF-008-06): la lista de parámetros sigue siendo la del proyecto (sin los
        de las versiones); ``scopes`` da el valor de cada ámbito: primero el del proyecto y
        después el de cada versión que lo tiene, por número (V02 antes que V10), para
        «V11: 1,25 [HIP] · proyecto: 1,23 [ADO]»; uno solo de una versión, solo ese."""
        self.tick()
        later = self.write(lambda conn: [versions_store.create_version(
            conn, self.project, feature=f"v{n}", title=f"Versión {n}", reason="Prueba")[0]
            for n in range(3, 11)])
        self.assertEqual(later[-1].code, "V10")
        self.change("V10", 1.20, "Prueba en V10")
        self.change("V02", 1.30, "Prueba en V02")
        self.change("V01", 1.25, "Prueba en V01")
        self.write(lambda conn: self.store.create(conn, BENCH, 12.0, version="V02",
                                                  reason="Bancos", **BY_HAND))
        listed = self.store.list()
        self.assertEqual([(row.record.key, row.record.scope, row.shown) for row in listed],
                         [(K, "project", "1,23")])
        found = self.store.scopes(K)
        self.assertEqual(
            [(record.scope, record.scope_uid, record.value, record.kind) for record in found],
            [("project", "", 1.23, "ADOPTADO"), ("version", self.v1.uid, 1.25, "HIPÓTESIS"),
             ("version", self.v2.uid, 1.30, "HIPÓTESIS"),
             ("version", later[-1].uid, 1.20, "HIPÓTESIS")])
        self.assertEqual(found[0], self.store.get(K))
        self.assertEqual(found[1], self.store.get(K, version="V01"))
        self.assertEqual([record.scope_uid for record in self.store.scopes(BENCH)],
                         [self.v2.uid])
        self.assertEqual(self.store.scopes("res.nothing"), ())
        with self.project.read() as conn:
            self.assertEqual(self.store.scopes(K, conn=conn), found)


class InheritTest(VersionScopeCase):
    def test_new_version_inherits_the_version_values_with_history(self) -> None:
        """RF-009-01 (plan A1, D-26): una versión que parte de V01 recibe el valor actual de
        cada parámetro de versión de V01 (mismo valor, unidad, tipo, origen y decisor) como su
        fila rev 1 con su historial ``create`` «Heredado de V01.r2», de quien la crea, y lo
        resuelve como suyo; los de V01 y el del proyecto no cambian, ni cambian al cambiar los
        de la nueva. ``inherit`` no hereda de sí misma ni sin etiqueta."""
        self.change("V01", 1.25, "Prueba en V01")
        self.change("V01", 1.26, "Segundo ensayo en V01")
        self.write(lambda conn: self.store.create(conn, BENCH, 12.0, version="V01",
                                                  reason="Bancos de 12 m", **BY_HAND))
        self.freeze(self.v1)  # r1 congelada, r2 abierta
        parent, project = self.rows(self.v1.uid), self.rows()
        child = self.new_version("hija", "Hija", parent="V01")
        made_at = timeutil.format_utc(self.clock.now())
        inherited = self.store.scopes(K)[-1]
        self.assertEqual(
            (inherited.scope_uid, inherited.value, inherited.kind, inherited.source,
             inherited.decided_by, inherited.rev, inherited.reason, inherited.created_at),
            (child.uid, 1.26, "HIPÓTESIS", "Ensayo de la propiedad", "La propiedad", 1,
             "Heredado de V01.r2", made_at))
        self.assertEqual(
            [(e.rev, e.action, e.reason, e.value, e.changed_by, e.changed_at)
             for e in self.store.history(K, version=child.code)],
            [(1, "create", "Heredado de V01.r2", 1.26, USER, made_at)])
        self.assertEqual(self.store.get(BENCH, version=child.uid).value, 12.0)
        with self.project.read() as conn:
            resolved = self.store.resolve(conn, K, ("version", "project"), version=child.code)
        self.assertEqual((resolved.scope_uid, resolved.value, resolved.rev), (child.uid, 1.26, 1))
        self.assertEqual((self.rows(self.v1.uid), self.rows()), (parent, project))
        self.change(child.code, 1.28, "Prueba en la hija")
        self.assertEqual((self.rows(self.v1.uid), self.rows()), (parent, project))
        for parent_uid, child_uid, label in ((self.v1.uid, self.v1.uid, "V01.r2"),
                                             (self.v1.uid, child.uid, "  ")):
            with self.subTest(label=label), self.assertRaises(ValueError):
                self.write(lambda conn, p=parent_uid, c=child_uid, label=label:
                           self.store.inherit(conn, p, c, label=label))

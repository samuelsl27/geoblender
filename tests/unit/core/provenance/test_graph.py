# SPDX-License-Identifier: GPL-3.0-or-later
"""Grafo de operaciones por versiones y obsolescencia deducida (spec 008, T26; RF-008-24,
RF-008-25; ADR-0024 §6; ADR-0025 §5; plan 008 §5.4.3 y D4).

``core.provenance.graph`` carga el grafo del proyecto (``load_graph``): las operaciones hechas,
las **versiones** de dato que consumen y producen (dato, hash), las versiones de parámetro que
consumen y el estado actual de datos, entradas, parámetros y cifras. ``deduce`` calcula sobre
él la obsolescencia completa, con sus causas raíz: una operación está obsoleta si lo que
consumió ya no es lo que consumió (otro hash de un dato que no escribió ella, otro valor o
unidad de un parámetro, una entrada sustituida o descartada, un dato que falta, bloqueado o
dañado), si consumió algo obsoleto, si lo está otra de su grupo acoplado o si el Geoblender
instalado declara una versión mayor de su algoritmo; un dato vivo, si lo está la operación que
escribió su contenido actual. Un cambio solo del tipo de un parámetro no deja nada obsoleto, y
un recálculo que da el mismo contenido (con el normalizador del dato, aunque haya otro vigente)
tampoco.

Cada prueba usa el proyecto sintético de ``test_operations`` (esquema 2, reloj simulado) con los
tipos de operación, los parámetros y la cifra de prueba de este módulo; las operaciones escriben
tablas reales de ``project.gpkg`` y sus hashes son los del lector ``core.gpkg_layer@1``.

La caché ``gb_stale`` (``core.provenance.stale``, T27) se escribe por diferencias, por región
(solo lo alcanzable desde lo que cambió), en la transacción de cada camino que escribe; cada
cálculo completo de estas pruebas comprueba además que la caché es, fila a fila, lo deducido.
La propiedad «región = completo» se prueba en grafos aleatorios sobre una base en memoria con
las tablas de la procedencia.
"""

from __future__ import annotations

import ast
import random
import re
import sqlite3
import unittest
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from unittest import mock

from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.unit.core.provenance.test_operations import (
    GPKG_READER,
    OperationsCase,
    _insert,
)
from tests.unit.core.provenance.test_schema import (
    dataset_row,
    input_row,
    io_row,
    op_param_row,
    operation_row,
    parameter_row,
)

provenance = import_geoblender("core.provenance")
graph_mod = import_geoblender("core.provenance.graph")
stale_mod = import_geoblender("core.provenance.stale")
contract = import_geoblender("core.provenance.contract")
operations = import_geoblender("core.provenance.operations")
figures = import_geoblender("core.provenance.figures")
messages = import_geoblender("core.provenance.messages")
schema = import_geoblender("core.provenance.schema")
params = import_geoblender("core.params")
datasets = import_geoblender("core.datasets")
dataset_registry = import_geoblender("core.datasets.registry")
inputs = import_geoblender("core.inputs")
content = import_geoblender("core.content")
encoder = import_geoblender("core.content.encoder")
base = import_geoblender("core.gpkg.base")
hashing = import_geoblender("core.hashing")
i18n = import_geoblender("core.i18n")
timeutil = import_geoblender("core.timeutil")

Cause = graph_mod.Cause
CauseKind = graph_mod.CauseKind
Use = operations.Use


def _recompute(request: Any) -> Any:  # pragma: no cover - ninguna prueba recalcula
    raise AssertionError("no se recalcula en estas pruebas")


def _op(op_type: str, version: str = "1.0", *, repeatable: bool = True,
        group: str | None = None) -> Any:
    return provenance.OperationDef(
        op_type, version, "res", f"Test {op_type}", repeatable, group=group,
        recompute=_recompute if repeatable else None,
    )


STEP_A = _op("res.step_a", "1.9")
STEP_B = _op("res.step_b")
STEP_C = _op("res.step_c")
STEP_D = _op("res.step_d")
EDIT = _op("res.edit", repeatable=False)
DIGITIZE = _op("res.digitize", repeatable=False)
IMPORT = _op("res.import_source", repeatable=False)
PAIR_FIRST = _op("res.pair_first", group="res.pair")
PAIR_SECOND = _op("res.pair_second", group="res.pair")
PAIR = provenance.CoupledGroupDef("res.pair", ("res.pair_first", "res.pair_second"))
MARKS = provenance.FigureDef("res.marks", "-", "Test marks")
DECLARATIONS = (STEP_A, STEP_B, STEP_C, STEP_D, EDIT, DIGITIZE, IMPORT, PAIR_FIRST,
                PAIR_SECOND, PAIR, MARKS)

PRODUCTION = params.ParamDef(
    "res.production", "float", "t/yr", 100000.0, 0.0, None, ("RF-008-24",),
    "Prueba: producción anual del plan de labores", min_exclusive=True, kind="HIPÓTESIS",
    source_kind="document", label_msgid="Test production",
)
DENSITY = params.ParamDef(
    "res.density", "float", "t/m3", 2.5, 0.0, None, ("RF-008-24",),
    "Prueba: densidad del todo uno", min_exclusive=True, label_msgid="Test density",
)
LABELS_ES = {"Test production": "Producción", "Test density": "Densidad", "Test marks": "Marcas"}

INPUT_1 = "00000000-0000-4000-8000-0000000002e1"
INPUT_2 = "00000000-0000-4000-8000-0000000002e2"
GBCH2 = "gbch/2"


def _replace_table(conn: sqlite3.Connection, name: str, values: Sequence[float]) -> None:
    """La tabla ``name`` (``valor``) con exactamente ``values``: lo que escribe un módulo."""
    exists = conn.execute("SELECT 1 FROM gpkg_contents WHERE table_name = ?",
                          (name,)).fetchone()
    if exists is None:
        base.create_attribute_table(conn, name, [base.ColumnDef("valor", "DOUBLE")], name)
    else:
        conn.execute(f'DELETE FROM "{name}"')
    conn.executemany(f'INSERT INTO "{name}" (valor) VALUES (?)', [(v,) for v in values])


def _spec(name: str, *, role: str = "result", digest: Any = None, input_uid: str | None = None
          ) -> Any:
    return datasets.DatasetSpec(
        name, "res", "table", "gpkg", name, reader=GPKG_READER, role=role, content=digest,
        input_uid=input_uid, immutable=input_uid is not None,
    )


def _uses(reads: Sequence[str | Any]) -> list[Any]:
    return [item if isinstance(item, Use) else Use(item, "source") for item in reads]


def _check_values(ddl: str) -> set[str]:
    found = re.search(r"cause_kind\s+TEXT\s+NOT NULL CHECK \(cause_kind IN \(([^)]*)\)\)", ddl)
    assert found is not None, ddl
    return set(re.findall(r"'([a-z_]+)'", found[1]))


class GraphCase(OperationsCase):
    """El proyecto de ``OperationsCase`` con los tipos, los parámetros y la cifra de prueba de
    este módulo, y ayudas para encadenar operaciones hechas."""

    def setUp(self) -> None:
        super().setUp()
        params.register_definitions((PRODUCTION, DENSITY))
        self.enterContext(registered(*DECLARATIONS))
        i18n.install(LABELS_ES)

    # --- Operaciones ------------------------------------------------------------------------

    def run_op(
        self,
        op_type: str,
        writes: Mapping[str, Sequence[float]] | None = None,
        *,
        reads: Sequence[str | Any] = (),
        params: Sequence[str] = (),
        group_uid: str | None = None,
        supersedes: str | None = None,
        digests: Mapping[str, Any] | None = None,
        figure: float | None = None,
        before: Callable[[sqlite3.Connection, Any], None] | None = None,
        outputs: Sequence[Any] = (),
        settings: Mapping[str, Any] | None = None,
    ) -> Any:
        """Una operación hecha de ``op_type`` (con sus ``settings``): consume ``reads``
        (nombres de datos vivos o ``Use``) y ``params``, escribe las tablas de ``writes`` (con
        el hash de ``digests`` si se da) y, si se pide, la cifra ``res.marks``."""
        handle = self.begin(op_type, inputs=_uses(reads), params=list(params),
                            group_uid=group_uid, supersedes=supersedes,
                            settings=dict(settings or {}))
        chosen = digests or {}

        def work(conn: sqlite3.Connection) -> None:
            if before is not None:
                before(conn, handle)
            specs = list(outputs)
            for name, values in (writes or {}).items():
                _replace_table(conn, name, values)
                specs.append(_spec(name, digest=chosen.get(name)))
            shown = () if figure is None else (figures.FigureSpec("res.marks", figure, "-"),)
            handle.complete(conn, outputs=specs, figures=shown)

        self.write(work)
        self.tick()
        return handle

    def import_input(self, input_uid: str, name: str, table: str) -> Any:
        """La importación de la entrada ``name`` (``input_uid``), con lo importado en
        ``table``."""

        def register(conn: sqlite3.Connection, handle: Any) -> None:
            _insert(conn, "gb_input", input_row(uid=input_uid, name=name,
                                                operation_uid=handle.uid))
            _replace_table(conn, table, [1.0, 2.0])

        return self.run_op("res.import_source", before=register,
                           outputs=[_spec(table, role="imported", input_uid=input_uid)])

    def change(self, key: str, value: float | None = None, **kw: Any) -> None:
        """Una persona cambia el parámetro ``key`` (su valor o, sin ``value``, lo demás)."""
        values: dict[str, Any] = {"source": "Acta de la propiedad", "source_kind": "document",
                                  "decided_by": "la propiedad", "reason": "Cambio de prueba"}
        if value is not None:
            values["value"] = value
        values.update(kw)
        self.write(lambda conn: self.store.change(conn, key, **values))
        self.tick()

    def set_status(self, name: str, status: str) -> None:
        uid = self.dataset(name)
        self.write(lambda conn: dataset_registry.set_status(conn, self.project, uid, status))

    def chain(self) -> tuple[Any, Any, Any, Any]:
        """A → B → C, que leen en cadena, y D, independiente."""
        a = self.run_op("res.step_a", {"res_a": [1.0, 2.0]}, params=["res.production"])
        b = self.run_op("res.step_b", {"res_b": [3.0]}, reads=["res_a"])
        c = self.run_op("res.step_c", {"res_c": [4.0]}, reads=["res_b"])
        d = self.run_op("res.step_d", {"res_d": [5.0]}, params=["res.density"])
        return a, b, c, d

    def mark_changed(self, input_uid: str) -> None:
        """La comprobación de las fuentes encuentra cambiada la entrada (como
        ``check_steps``: estado y contenido visto)."""
        seen = hashing.sha256_bytes(b"contenido visto de la fuente")
        self.write(lambda conn: conn.execute(
            "UPDATE gb_input SET status = 'changed', seen_sha256 = ?, modified_at = ? "
            "WHERE uid = ?", (seen, "2026-10-08T10:00:00.000Z", input_uid),
        ))

    # --- Lecturas -----------------------------------------------------------------------------

    def stale(self, *, cache: bool = True, **kw: Any) -> Any:
        """La obsolescencia completa del proyecto; con las versiones instaladas (sin
        ``versions``) y ``cache``, comprueba además que la caché es, fila a fila, lo deducido
        (la mantienen los caminos que escriben)."""
        with self.project.read() as conn:
            state = graph_mod.deduce(graph_mod.load_graph(conn), **kw)
            if cache and "versions" not in kw:
                self.assertEqual(stale_mod.cached_rows(conn), stale_mod.expected_rows(state))
        return state

    def cached(self) -> dict[tuple[str, str, str, str], str]:
        """Las filas de la caché ``gb_stale`` con su ``since``."""
        rows = self.query("SELECT item_kind, item_uid, cause_kind, subject_uid, since "
                          "FROM gb_stale")
        return {tuple(row[:4]): row[4] for row in rows}

    def dataset(self, name: str) -> str:
        """El uid del último dato registrado con ``name``."""
        rows = self.query("SELECT uid FROM gb_dataset WHERE name = ? ORDER BY fid DESC",
                          (name,))
        self.assertTrue(rows, name)
        return str(rows[0][0])

    def content_of(self, name: str) -> tuple[str, str]:
        (row,) = self.query("SELECT content_sha256, normalizer FROM gb_dataset WHERE uid = ?",
                            (self.dataset(name),))
        return str(row[0]), str(row[1])

    def parameter(self, key: str) -> str:
        record = self.store.get(key)
        self.assertIsNotNone(record, key)
        return str(record.uid)

    def changed(self, key: str) -> Any:
        return Cause(CauseKind.PARAMETER_CHANGED, self.parameter(key))

    def assertNothingStale(self, state: Any) -> None:
        self.assertEqual(dict(state.operations), {})
        self.assertEqual(dict(state.datasets), {})
        self.assertEqual(state.review, frozenset())

    def assertStale(self, state: Any, operations: Mapping[Any, set[Any]],
                    data: Mapping[str, set[Any]]) -> None:
        """Exactamente esas operaciones (vigentes) y esos datos vivos obsoletos, con esas
        causas."""
        self.assertEqual(dict(state.operations),
                         {handle.uid: causes for handle, causes in operations.items()})
        self.assertEqual(dict(state.datasets),
                         {self.dataset(name): causes for name, causes in data.items()})


class GraphLoadTest(GraphCase):
    def test_graph_by_versions_of_the_data(self) -> None:
        """RF-008-24 (plan §5.4.3, D4): el grafo tiene las operaciones hechas, en orden, con
        las versiones (dato, hash) que consumieron y produjeron y las de los parámetros que
        leyeron; el productor de una versión es la operación que la escribió (sin la que la
        consume) y cargarlo no escribe nada."""
        a = self.run_op("res.step_a", {"res_a": [1.0]}, params=["res.production"])
        first = self.content_of("res_a")[0]
        failed = self.begin("res.step_b", inputs=_uses(["res_a"]))
        failed.fail("prueba de una operación que no termina")
        b = self.run_op("res.step_b", {"res_b": [2.0]}, reads=["res_a"])
        e = self.run_op("res.edit", {"res_a": [1.0, 5.0]}, reads=["res_a"])
        second = self.content_of("res_a")[0]
        before = self.snapshot()
        with self.project.read() as conn:
            loaded = graph_mod.load_graph(conn)
        self.assertEqual(self.snapshot(), before)

        self.assertEqual(list(loaded.operations), [a.uid, b.uid, e.uid])
        uid_a, uid_b = self.dataset("res_a"), self.dataset("res_b")
        node_a, node_b = loaded.operations[a.uid], loaded.operations[b.uid]
        self.assertEqual((node_a.op_type, node_a.op_version, node_a.repeatable),
                         ("res.step_a", "1.9", True))
        self.assertEqual(node_a.consumed, ())
        self.assertEqual(node_a.produced,
                         (graph_mod.Version("dataset", uid_a, first, "result"),))
        (use,) = node_a.params
        record = self.store.get("res.production")
        self.assertEqual((use.parameter_uid, use.key, use.rev, use.value_sha256),
                         (record.uid, "res.production", record.rev, record.value_sha256))
        self.assertEqual(node_b.consumed,
                         (graph_mod.Version("dataset", uid_a, first, "source"),))
        self.assertEqual(node_b.produced[0].uid, uid_b)
        self.assertEqual(loaded.datasets[uid_a].content_sha256, second)
        self.assertEqual(loaded.datasets[uid_a].operation_uid, e.uid)
        self.assertEqual(loaded.parameters[record.uid].value_sha256, record.value_sha256)

        self.assertEqual(loaded.producer(uid_a, first), a.uid)
        self.assertEqual(loaded.producer(uid_a, second), e.uid)
        self.assertIsNone(loaded.producer(uid_a, first, excluding=a.uid))
        self.assertIsNone(loaded.producer(uid_a, "0" * 64))
        self.assertEqual(loaded.upstream(b.uid), (a.uid,))
        self.assertEqual(loaded.upstream(e.uid), (a.uid,))
        self.assertEqual(loaded.upstream(a.uid), ())

    def test_cause_kinds_are_those_of_the_cache(self) -> None:
        """RF-008-24, RF-008-25 (plan §5.2.1): las clases de causa son las de la caché
        ``gb_stale``."""
        self.assertEqual({str(kind) for kind in CauseKind},
                         _check_values(schema.TABLES["gb_stale"]))
        statuses = {str(status) for status in datasets.DatasetStatus}
        self.assertEqual(set(graph_mod.DATASET_STATUS_CAUSES), {"missing", "blocked", "damaged"})
        self.assertLessEqual(set(graph_mod.INACTIVE_CAUSES), statuses)
        self.assertEqual(set(graph_mod.INACTIVE_CAUSES), set(schema.INACTIVE_INPUT_STATUSES))

    def test_public_api(self) -> None:
        """RF-008-24 (plan §5.1): ``core.provenance`` reexporta el grafo al usarlo, sin
        cargarlo al importarse."""
        for name in provenance.GRAPH_API:
            with self.subTest(name=name):
                self.assertIn(name, provenance.__all__)
                self.assertIs(getattr(provenance, name), getattr(graph_mod, name))
        self.assertLessEqual({"load_graph", "deduce", "Cause", "CauseKind", "Staleness"},
                             set(provenance.GRAPH_API))
        tree = ast.parse(Path(provenance.__file__).read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                with self.subTest(line=node.lineno):
                    self.assertNotEqual(node.module, "graph")
                    self.assertNotIn("graph", [alias.name for alias in node.names])


class StaleTest(GraphCase):
    def test_parameter_change_cascades_to_what_depends_on_it(self) -> None:
        """RF-008-24: en A → B → C y D independiente, cambiar un parámetro de A deja
        obsoletos A, B y C y sus datos, no D, con la causa «cambió <parámetro>»."""
        a, b, c, d = self.chain()
        self.assertNothingStale(self.stale())

        self.change("res.production", 120000.0)
        state = self.stale()
        production = self.changed("res.production")
        self.assertStale(state, {a: {production}, b: {production}, c: {production}},
                         {"res_a": {production}, "res_b": {production},
                          "res_c": {production}})
        self.assertEqual(state.review, frozenset())  # se pueden repetir solas
        self.assertEqual(state.text(c.uid), "Obsoleto: cambió Producción")
        self.assertEqual(state.text(self.dataset("res_c"), language="en"),
                         "Stale: Test production changed")
        self.assertIsNone(state.text(d.uid))
        self.assertIsNone(state.text(self.dataset("res_d")))
        self.assertEqual(state.of(d.uid), frozenset())
        self.assertEqual(state.of(b.uid), {production})

    def test_kind_only_change_leaves_nothing_stale(self) -> None:
        """RF-008-24 (D10): cambiar solo el tipo de un parámetro (HIPÓTESIS → ADOPTADO con el
        mismo valor) o confirmarlo no deja nada obsoleto; cambiar su valor, sí."""
        a, b, c, d = self.chain()
        before = self.store.get("res.production")
        self.change("res.production", kind="ADOPTADO")
        self.write(lambda conn: self.store.confirm(conn, "res.density"))
        after = self.store.get("res.production")
        self.assertEqual((after.kind, after.value_sha256), ("ADOPTADO", before.value_sha256))
        self.assertGreater(after.rev, before.rev)
        self.assertNothingStale(self.stale())

        self.change("res.density", 2.6)
        density = self.changed("res.density")
        self.assertStale(self.stale(), {d: {density}}, {"res_d": {density}})

    def test_own_edit_of_what_it_reads_does_not_make_it_stale(self) -> None:
        """RF-008-24 (spec §8, «operación que reescribe el dato que lee»): una edición
        propia del dato que lee no deja obsoleta a la operación; lo que consumía el contenido
        anterior, sí, y lo de aguas arriba sigue llegando por la versión que leyó."""
        a = self.run_op("res.step_a", {"res_a": [1.0, 2.0]}, params=["res.production"])
        b = self.run_op("res.step_b", {"res_b": [3.0]}, reads=["res_a"])
        e = self.run_op("res.edit", {"res_a": [1.0, 2.0, 9.0]}, reads=["res_a"])
        f = self.run_op("res.step_c", {"res_f": [8.0]}, reads=["res_a"])
        g = self.run_op("res.edit", {"res_a": [9.0, 2.0, 1.0]}, reads=["res_a"])  # lo mismo
        edited = Cause(CauseKind.DATASET_CHANGED, self.dataset("res_a"))
        state = self.stale()
        self.assertStale(state, {b: {edited}}, {"res_b": {edited}})
        self.assertEqual(state.text(b.uid), "Obsoleto: cambió «res_a»")

        self.change("res.production", 90000.0)
        production = self.changed("res.production")
        state = self.stale()
        self.assertStale(
            state, {a: {production}, b: {edited, production}, e: {production},
                    f: {production}, g: {production}},
            {"res_a": {production}, "res_b": {edited, production}, "res_f": {production}},
        )
        self.assertEqual(state.review, {g.uid})  # no se repite sola y escribió «res_a»
        self.assertEqual(state.text(b.uid),
                         "Obsoleto: cambió «res_a»; cambió Producción")

    def test_coupled_group_is_stale_as_a_whole(self) -> None:
        """RF-008-25: si una operación de un grupo acoplado queda obsoleta, lo quedan todas
        las de esa ejecución del grupo (con la causa «grupo») y lo que depende de cualquiera
        de ellas, también por caminos que abre el grupo; otra ejecución del grupo, no."""
        first = self.run_op("res.pair_first", {"res_x1": [1.0]})
        i = self.run_op("res.step_c", {"res_i": [2.0]}, reads=["res_x1"])
        z = self.run_op("res.step_a", {"res_y": [3.0]}, params=["res.density"])
        second = self.run_op("res.pair_second", {"res_x2": [4.0]}, reads=["res_y"],
                             group_uid=first.group_uid)
        h = self.run_op("res.step_b", {"res_h": [5.0]}, reads=["res_x2"])
        other = self.run_op("res.pair_first", {"res_x3": [6.0]})
        self.run_op("res.pair_second", {"res_x4": [7.0]}, group_uid=other.group_uid)
        self.run_op("res.step_d", {"res_d": [8.0]}, params=["res.production"])
        self.assertNotEqual(first.group_uid, other.group_uid)
        self.assertNothingStale(self.stale())

        self.change("res.density", 2.7)
        density = self.changed("res.density")
        group = Cause(CauseKind.GROUP, first.group_uid)
        state = self.stale()
        self.assertStale(
            state,
            {z: {density}, second: {density, group}, first: {density, group}, i: {density},
             h: {density}},
            {name: {density} for name in ("res_y", "res_x2", "res_x1", "res_i", "res_h")},
        )
        self.assertEqual(state.text(first.uid),
                         "Obsoleto: cambió Densidad; está acoplada en el grupo «res.pair»")
        self.assertEqual(state.text(i.uid, language="en"), "Stale: Test density changed")

    def test_installed_algorithm_version(self) -> None:
        """RF-008-24: una versión instalada del algoritmo mayor que la registrada deja
        obsoletas las operaciones de su tipo y lo que depende de ellas; una igual o menor, o
        un tipo que no está instalado, no."""
        a, b, c, d = self.chain()
        self.assertNothingStale(self.stale())  # lo registrado: res.step_a 1.9
        algorithm = Cause(CauseKind.ALGORITHM, "res.step_a")
        state = self.stale(versions={"res.step_a": "1.10"})
        self.assertStale(state, {a: {algorithm}, b: {algorithm}, c: {algorithm}},
                         {"res_a": {algorithm}, "res_b": {algorithm}, "res_c": {algorithm}})
        self.assertEqual(
            state.text(c.uid),
            "Obsoleto: Geoblender cambia el algoritmo de res.step_a (1.9 → 1.10)",
        )
        for installed in ("1.9", "1.8", "0.12"):
            with self.subTest(installed=installed):
                self.assertNothingStale(self.stale(versions={"res.step_a": installed}))
        self.assertNothingStale(self.stale(versions={}))
        with self.assertRaises(ValueError):
            self.stale(versions={"res.step_a": "1.x"})

        contract.unregister_operation("res.step_a")
        contract.register_operation(_op("res.step_a", "2.0"))
        self.run_op("res.step_a", {"res_z": [9.0]})  # ya con el algoritmo 2.0
        # Cambiar lo instalado no es un camino que escriba: la caché la rehace la comprobación
        # de apertura (obsolescencia completa).
        state = self.stale(cache=False)
        self.assertEqual(set(state.operations), {a.uid, b.uid, c.uid})
        self.assertEqual(state.text(a.uid, language="en"),
                         "Stale: Geoblender changes the algorithm of res.step_a (1.9 → 2.0)")

    def test_inputs_superseded_or_discarded(self) -> None:
        """RF-008-24 (RF-008-11, RF-008-55): una entrada sustituida o descartada deja
        obsoleto lo que la consumió directamente o a través de lo importado de ella."""
        self.import_input(INPUT_1, "Entrada_1", "res_im1")
        second_import = self.import_input(INPUT_2, "Entrada_2", "res_im2")
        k1 = self.run_op("res.step_a", {"res_k1": [1.0]},
                         reads=[Use(INPUT_1, "source", kind="input")])
        k2 = self.run_op("res.step_b", {"res_k2": [2.0]}, reads=["res_im1"])
        k3 = self.run_op("res.step_c", {"res_k3": [3.0]},
                         reads=[Use(INPUT_2, "source", kind="input")])
        k4 = self.run_op("res.step_d", {"res_k4": [4.0]}, reads=["res_im2"])
        k5 = self.run_op("res.step_a", {"res_k5": [5.0]}, reads=["res_k4"])
        self.assertNothingStale(self.stale())

        self.write(lambda conn: inputs.discard(conn, self.project, INPUT_1,
                                               "entrega anulada"))
        reimport = self.begin("res.import_source", supersedes=second_import.uid)

        def update(conn: sqlite3.Connection) -> None:
            inputs.supersede(conn, self.project, INPUT_2, operation_uid=reimport.uid,
                             reason="nueva entrega")
            reimport.complete(conn)

        self.write(update)
        discarded = Cause(CauseKind.INPUT_DISCARDED, INPUT_1)
        updated = Cause(CauseKind.INPUT_UPDATED, INPUT_2)
        state = self.stale()
        self.assertStale(
            state,
            {k1: {discarded}, k2: {discarded}, k3: {updated}, k4: {updated}, k5: {updated}},
            {"res_k1": {discarded}, "res_k2": {discarded}, "res_k3": {updated},
             "res_k4": {updated}, "res_k5": {updated}},
        )
        self.assertEqual(state.text(k2.uid), "Obsoleto: se descartó la entrada «Entrada_1»")
        self.assertEqual(state.text(k4.uid),
                         "Obsoleto: se actualizó la entrada «Entrada_2»")
        self.assertEqual(state.text(k1.uid, language="en"),
                         "Stale: input «Entrada_1» was discarded")

    def test_missing_blocked_damaged_or_superseded_data(self) -> None:
        """RF-008-24 (RF-008-56, RF-008-57; ADR-0025 §4): un dato consumido que falta, está
        bloqueado o dañado da su causa a lo que lo consumió y a lo de aguas abajo; vuelto a
        vigente, nada; uno sustituido sin entrada, «cambió»."""
        a, b, c, d = self.chain()
        uid_a = self.dataset("res_a")
        cases = (
            ("missing", CauseKind.DATASET_MISSING, "Obsoleto: falta «res_a»"),
            ("blocked", CauseKind.DATASET_BLOCKED,
             "Obsoleto: «res_a» está bloqueado por una edición externa"),
            ("damaged", CauseKind.DATASET_DAMAGED,
             "Obsoleto: «res_a» está dañado: solo se puede reimportar"),
        )
        for status, kind, text in cases:
            with self.subTest(status=status):
                self.set_status("res_a", status)
                cause = Cause(kind, uid_a)
                state = self.stale()
                self.assertStale(state, {b: {cause}, c: {cause}},
                                 {"res_b": {cause}, "res_c": {cause}})
                self.assertEqual(state.text(c.uid), text)
        self.set_status("res_a", "current")
        self.assertNothingStale(self.stale())

        uid_b = self.dataset("res_b")
        self.write(lambda conn: dataset_registry.supersede(conn, self.project, uid_b))
        changed = Cause(CauseKind.DATASET_CHANGED, uid_b)
        self.assertStale(self.stale(), {c: {changed}}, {"res_c": {changed}})
        self.change("res.production", 95000.0)  # un dato que ya no está vivo no cuenta
        production = self.changed("res.production")
        self.assertStale(self.stale(),
                         {a: {production}, b: {production}, c: {changed, production}},
                         {"res_a": {production}, "res_c": {changed, production}})

    def test_recompute_with_another_normalizer_and_the_same_content(self) -> None:
        """RF-008-24, RF-008-26 (ADR-0024 §6): con un normalizador ``gbch/2`` vigente
        (simulado), recalcular un dato de ``gbch/1`` con el mismo contenido lo hashea con
        ``gbch/1`` y no deja nada obsoleto: la operación nueva sustituye a la anterior, que
        queda como historia con su causa."""
        a = self.run_op("res.step_a", {"res_a": [1.0, 2.0]}, params=["res.production"])
        b = self.run_op("res.step_b", {"res_b": [3.0]}, reads=["res_a"])
        before = self.content_of("res_a")
        self.assertEqual(before[1], content.NORMALIZER)
        self.change("res.production", 110000.0)
        production = self.changed("res.production")
        self.assertStale(self.stale(), {a: {production}, b: {production}},
                         {"res_a": {production}, "res_b": {production}})

        both = frozenset({content.NORMALIZER, GBCH2})
        with mock.patch.object(encoder, "NORMALIZERS", both), \
                mock.patch.object(encoder, "NORMALIZER", GBCH2), \
                mock.patch.object(dataset_registry, "NORMALIZERS", both), \
                mock.patch.object(dataset_registry, "NORMALIZER", GBCH2):
            data = hashing.sha256_bytes(b"res_a normalizado con gbch/2")
            digest = content.ContentDigest(
                data, content.content_sha256("table", {}, data, normalizer=GBCH2), GBCH2,
                GPKG_READER,
            )
            a2 = self.run_op("res.step_a", {"res_a": [2.0, 1.0]}, params=["res.production"],
                             supersedes=a.uid, digests={"res_a": digest})
        self.assertNotEqual(digest.content_sha256, before[0])
        self.assertEqual(self.content_of("res_a"), before)
        state = self.stale()
        self.assertNothingStale(state)
        self.assertEqual(state.causes[a.uid], {production})  # la historia, con su causa
        self.assertNotIn(a2.uid, state.causes)

        # La versión que leyó B la escribieron A y A2: su productor es la última.
        self.run_op("res.edit", {"res_a": [7.0]}, reads=["res_a"])
        edited = Cause(CauseKind.DATASET_CHANGED, self.dataset("res_a"))
        self.assertStale(self.stale(), {b: {edited}}, {"res_b": {edited}})

    def test_review_by_hand(self) -> None:
        """RF-008-24, RF-008-27 (plan §5.4.3): una operación obsoleta que no se repite sola
        espera revisión a mano si escribió el contenido actual de un dato vivo o una cifra
        vigente; no, si otra reescribió su dato o hay una cifra más reciente al día."""
        self.run_op("res.step_a", {"res_a": [1.0]}, params=["res.production"])
        r = self.run_op("res.digitize", {"res_r": [2.0]}, reads=["res_a"])
        s = self.run_op("res.digitize", reads=["res_a"], figure=3.0)
        q = self.run_op("res.digitize", {"res_q": [4.0]}, reads=["res_a"])
        self.run_op("res.step_d", {"res_q": [5.0]})
        self.change("res.production", 80000.0)
        state = self.stale()
        self.assertEqual(state.review, {r.uid, s.uid})
        self.assertIn(q.uid, state.operations)
        self.assertEqual(len(state.current_figures), 1)

        fresh = self.run_op("res.step_d", figure=6.0)
        later = self.run_op("res.digitize", reads=["res_a"], figure=7.0)  # obsoleta al nacer
        state = self.stale()
        self.assertEqual(state.review, {r.uid})
        self.assertLessEqual({s.uid, later.uid}, set(state.operations))
        ((key, figure_uid),) = state.current_figures.items()
        (row,) = self.query("SELECT operation_uid FROM gb_figure WHERE uid = ?", (figure_uid,))
        self.assertEqual((key[0], row[0]), ("res.marks", fresh.uid))


# --- Caché por región (T27) -------------------------------------------------------------------

PERSON = {"source": "Acta de la propiedad", "source_kind": "document",
          "decided_by": "la propiedad", "reason": "Cambio de prueba"}


class CacheTest(GraphCase):
    def now(self) -> str:
        return timeutil.format_utc(self.clock.now())

    def test_every_write_path_keeps_the_cache(self) -> None:
        """RF-008-24, RF-008-28 (plan §5.4.3): tras cada camino que escribe —cambiar el
        valor, solo el tipo o confirmar un parámetro; completar una operación, también un
        recálculo con el mismo contenido y una edición externa; un dato bloqueado, dañado, que
        falta o vuelto a vigente; mantener la copia, descartar y sustituir una entrada— la caché
        ``gb_stale`` es, fila a fila, la obsolescencia deducida (la historia incluida), y lo
        que no deja nada obsoleto no la toca."""
        (external,) = (definition for definition in contract.CORE_OPERATIONS
                       if definition.op_type == contract.EXTERNAL_EDIT)
        self.enterContext(registered(external))
        a, b, c, d = self.chain()
        self.import_input(INPUT_1, "Entrada_1", "res_im1")
        second = self.import_input(INPUT_2, "Entrada_2", "res_im2")
        k1 = self.run_op("res.step_b", {"res_k1": [1.0]}, reads=["res_im1"])
        k2 = self.run_op("res.step_c", {"res_k2": [2.0]},
                         reads=[Use(INPUT_2, "source", kind="input")])
        k3 = self.run_op("res.step_c", {"res_k3": [3.0]},
                         reads=[Use(INPUT_1, "source", kind="input")])
        self.assertNothingStale(self.stale())
        self.assertEqual(self.cached(), {})

        # Parámetros: el valor deja obsoleto lo que lo leyó; solo el tipo o confirmar, nada.
        self.change("res.production", 120000.0)
        production = self.changed("res.production")
        self.assertStale(self.stale(), {a: {production}, b: {production}, c: {production}},
                         {"res_a": {production}, "res_b": {production},
                          "res_c": {production}})
        rows = self.cached()
        self.assertEqual(len(rows), 6)
        self.change("res.production", kind="ADOPTADO")
        self.write(lambda conn: self.store.confirm(conn, "res.density"))
        self.assertEqual(self.cached(), rows)
        self.stale()

        # Completar: lo que lee algo obsoleto nace obsoleto; un recálculo con el mismo
        # contenido deja al día lo de aguas abajo, y la sustituida queda en la caché como
        # historia, con su causa.
        e = self.run_op("res.step_d", {"res_e": [6.0]}, reads=["res_c"])
        self.assertEqual(self.stale().of(e.uid), {production})
        self.run_op("res.step_a", {"res_a": [2.0, 1.0]}, params=["res.production"],
                    supersedes=a.uid)
        state = self.stale()
        self.assertNothingStale(state)
        self.assertEqual(state.causes[a.uid], {production})
        self.assertEqual(set(self.cached()),
                         {("operation", a.uid, "parameter_changed", production.subject)})

        # Una edición externa (``core.external_edit``, como la registrará T32): lo que leía
        # el contenido anterior queda obsoleto; bloqueado, también «bloqueado».
        edit = self.begin("core.external_edit", inputs=_uses(["res_b"]), executor="external")

        def edited(conn: sqlite3.Connection) -> None:
            _replace_table(conn, "res_b", [3.0, 30.0])
            edit.complete(conn, outputs=[_spec("res_b")])

        self.write(edited)
        changed_b = Cause(CauseKind.DATASET_CHANGED, self.dataset("res_b"))
        self.assertStale(self.stale(), {c: {changed_b}, e: {changed_b}},
                         {"res_c": {changed_b}, "res_e": {changed_b}})
        self.set_status("res_b", "blocked")
        blocked = Cause(CauseKind.DATASET_BLOCKED, self.dataset("res_b"))
        self.assertEqual(self.stale().of(c.uid), {changed_b, blocked})
        self.set_status("res_b", "current")
        self.assertEqual(self.stale().of(c.uid), {changed_b})

        # Lo importado dañado o que falta, y vuelto a vigente.
        imported = self.dataset("res_im1")
        self.set_status("res_im1", "damaged")
        self.assertEqual(self.stale().of(k1.uid), {Cause(CauseKind.DATASET_DAMAGED, imported)})
        self.set_status("res_im1", "missing")
        self.assertEqual(self.stale().of(k1.uid), {Cause(CauseKind.DATASET_MISSING, imported)})
        self.set_status("res_im1", "current")
        self.assertEqual(self.stale().of(k1.uid), frozenset())

        # Entradas: mantener la copia no deja nada; descartar y sustituir, sí.
        self.mark_changed(INPUT_1)
        rows = self.cached()
        self.write(lambda conn: inputs.keep_copy(conn, self.project, INPUT_1,
                                                 reason="se queda la copia"))
        self.assertEqual(self.cached(), rows)
        self.stale()
        self.write(lambda conn: inputs.discard(conn, self.project, INPUT_1, "entrega anulada"))
        discarded = Cause(CauseKind.INPUT_DISCARDED, INPUT_1)
        state = self.stale()
        self.assertEqual((state.of(k1.uid), state.of(k3.uid)), ({discarded}, {discarded}))
        reimport = self.begin("res.import_source", supersedes=second.uid)

        def update(conn: sqlite3.Connection) -> None:
            inputs.supersede(conn, self.project, INPUT_2, operation_uid=reimport.uid,
                             reason="nueva entrega")
            reimport.complete(conn)

        self.write(update)
        self.assertEqual(self.stale().of(k2.uid), {Cause(CauseKind.INPUT_UPDATED, INPUT_2)})
        self.assertEqual(self.stale().of(d.uid), frozenset())

    def test_written_by_differences_in_the_same_transaction(self) -> None:
        """RF-008-24 (plan §5.4.3): la caché se escribe en la transacción del camino que
        escribe (si se deshace, no queda nada de ella) y por diferencias: una causa que sigue
        conserva su fecha, la nueva lleva la de su cambio y la que ya no está se borra."""
        a, b, c, d = self.chain()
        with self.assertRaises(RuntimeError):
            with self.project.write_transaction() as conn:
                self.store.change(conn, "res.production", value=1.0, **PERSON)
                self.assertTrue(stale_mod.cached_rows(conn))
                raise RuntimeError("falla lo demás de la transacción")
        self.assertEqual(self.cached(), {})

        first_at = self.now()
        self.change("res.production", 120000.0)
        first = self.cached()
        self.assertEqual(set(first.values()), {first_at})
        second_at = self.now()
        self.change("res.density", 2.6)
        density = self.changed("res.density")
        second = self.cached()
        self.assertEqual({key: second[key] for key in first}, first)
        self.assertEqual({key: at for key, at in second.items() if key not in first}, {
            ("operation", d.uid, "parameter_changed", density.subject): second_at,
            ("dataset", self.dataset("res_d"), "parameter_changed", density.subject): second_at,
        })
        self.change("res.production", 100000.0)  # vuelve al valor que leyeron A, B y C
        self.assertEqual(set(self.cached()), set(second) - set(first))
        self.stale()

    def test_counts(self) -> None:
        """RF-008-28: «! n obsoletos» cuenta los datos vivos obsoletos más las operaciones que
        esperan revisión a mano (también por una cifra vigente, que deja de serlo con otra más
        reciente al día), y «⚠ n entradas», las entradas cambiadas sin decidir (ni las que
        mantienen la copia ni las descartadas)."""
        self.assertEqual(stale_mod.counts(self.project), stale_mod.Counts(0, 0, 0))
        self.run_op("res.step_a", {"res_a": [1.0]}, params=["res.production"])
        self.run_op("res.digitize", {"res_r": [2.0]}, reads=["res_a"])
        self.run_op("res.digitize", reads=["res_a"], figure=3.0)
        self.run_op("res.step_d", {"res_d": [5.0]})
        self.change("res.production", 80000.0)
        state = self.stale()
        found = stale_mod.counts(self.project)
        self.assertEqual(found, stale_mod.Counts(stale=2, review=2, inputs_changed=0))
        self.assertEqual(found.obsolete, 4)
        self.assertEqual((found.stale, found.review), (len(state.datasets), len(state.review)))
        self.run_op("res.step_d", figure=6.0)
        self.run_op("res.digitize", reads=["res_a"], figure=7.0)  # más reciente, obsoleta
        self.assertEqual(stale_mod.counts(self.project), stale_mod.Counts(2, 1, 0))
        self.assertEqual(len(self.stale().review), 1)

        self.import_input(INPUT_1, "Entrada_1", "res_im1")
        self.import_input(INPUT_2, "Entrada_2", "res_im2")
        self.mark_changed(INPUT_1)
        self.mark_changed(INPUT_2)
        self.assertEqual(stale_mod.counts(self.project).inputs_changed, 2)
        self.write(lambda conn: inputs.keep_copy(conn, self.project, INPUT_1))
        self.assertEqual(stale_mod.counts(self.project).inputs_changed, 1)
        self.write(lambda conn: inputs.discard(conn, self.project, INPUT_2, "entrega anulada"))
        with self.project.read() as conn:
            self.assertEqual(stale_mod.counts(self.project, conn=conn),
                             stale_mod.Counts(2, 1, 0))

    def test_list_of_what_is_stale(self) -> None:
        """RF-008-28: la lista de lo obsoleto tiene los resultados obsoletos y las operaciones
        que esperan revisión a mano, con sus causas («Obsoleto: cambió Producción»), su
        módulo, la operación que los escribió y desde cuándo (la causa más antigua); y lo
        mismo en inglés."""
        self.import_input(INPUT_1, "Entrada_1", "res_im1")
        a = self.run_op("res.step_a", {"res_a": [1.0]}, params=["res.production"])
        r = self.run_op("res.digitize", {"res_r": [2.0]}, reads=["res_a"])
        k = self.run_op("res.step_b", {"res_k": [3.0]}, reads=["res_im1", "res_a"])
        self.run_op("res.step_d", {"res_d": [5.0]}, params=["res.density"])
        changed_at = self.now()
        self.change("res.production", 80000.0)
        self.write(lambda conn: inputs.discard(conn, self.project, INPUT_1, "entrega anulada"))
        report = stale_mod.stale_items(self.project)
        self.assertEqual(report.counts, stale_mod.counts(self.project))
        self.assertEqual(report.counts, stale_mod.Counts(stale=3, review=1, inputs_changed=0))
        self.assertEqual(
            [(item.item_kind, item.name, item.module, item.operation_uid, item.op_type,
              item.review, item.text) for item in report.items],
            [
                ("dataset", "res_a", "res", a.uid, "res.step_a", False,
                 "Obsoleto: cambió Producción"),
                ("dataset", "res_k", "res", k.uid, "res.step_b", False,
                 "Obsoleto: cambió Producción; se descartó la entrada «Entrada_1»"),
                ("dataset", "res_r", "res", r.uid, "res.digitize", True,
                 "Obsoleto: cambió Producción"),
                ("operation", "res.digitize", "res", r.uid, "res.digitize", True,
                 "Obsoleto: cambió Producción"),
            ],
        )
        self.assertEqual([item.uid for item in report.items],
                         [self.dataset("res_a"), self.dataset("res_k"), self.dataset("res_r"),
                          r.uid])
        self.assertEqual([item.since for item in report.items], [changed_at] * 4)
        self.assertEqual(report.items[1].causes, {self.changed("res.production"),
                                                  Cause(CauseKind.INPUT_DISCARDED, INPUT_1)})
        english = stale_mod.stale_items(self.project, language="en")
        self.assertEqual([item.text for item in english.items][1:3],
                         ["Stale: Test production changed; input «Entrada_1» was discarded",
                          "Stale: Test production changed"])

    def test_region_takes_whole_group_runs(self) -> None:
        """RF-008-25 (plan §5.4.3): el cálculo por región exige toda la ejecución de grupo de
        sus operaciones y que estén en el grafo; con ella da lo mismo que el completo, y las
        causas raíz (las de sus datos) no llevan la del grupo."""
        first = self.run_op("res.pair_first", {"res_x1": [1.0]}, params=["res.density"])
        second = self.run_op("res.pair_second", {"res_x2": [2.0]}, group_uid=first.group_uid)
        self.change("res.density", 2.6)
        density = self.changed("res.density")
        with self.project.read() as conn:
            loaded = graph_mod.load_graph(conn)
        with self.assertRaises(ValueError):
            graph_mod.deduce_region(loaded, {first.uid}, {})
        with self.assertRaises(ValueError):
            graph_mod.deduce_region(loaded, {first.uid, second.uid, INPUT_1}, {})
        found = graph_mod.deduce_region(loaded, {second.uid, first.uid}, {})
        full = graph_mod.deduce(loaded)
        self.assertEqual(dict(found.causes),
                         {uid: full.causes[uid] for uid in (first.uid, second.uid)})
        self.assertEqual(dict(found.roots), {first.uid: {density}, second.uid: {density}})
        self.assertEqual(self.stale().of(self.dataset("res_x2")), {density})

    def test_full_refresh_repairs_the_cache(self) -> None:
        """RF-008-24 (plan §5.4.6, paso 8): la obsolescencia completa rehace una caché
        alterada a mano (una fila de menos y una de más) sin tocar lo que estaba bien."""
        a, b, c, d = self.chain()
        self.change("res.production", 120000.0)
        rows = self.cached()
        missing = ("dataset", self.dataset("res_c"), "parameter_changed",
                   self.changed("res.production").subject)
        self.write(lambda conn: conn.execute(
            "DELETE FROM gb_stale WHERE item_kind = ? AND item_uid = ? AND cause_kind = ? "
            "AND subject_uid = ?", missing))
        self.write(lambda conn: conn.execute(
            "INSERT INTO gb_stale (item_kind, item_uid, cause_kind, subject_uid, since) "
            "VALUES ('operation', ?, 'algorithm', 'res.step_d', ?)", (d.uid, self.now())))
        later = self.now()
        update = self.write(lambda conn: stale_mod.refresh_all(conn, now=later))
        self.assertEqual(len(update.added), 1)
        self.assertEqual(len(update.removed), 1)
        self.assertEqual(self.cached(), {**rows, missing: later})
        self.stale()

    def test_public_api(self) -> None:
        """RF-008-24, RF-008-28 (plan §5.3.1): ``core.provenance`` reexporta la caché al
        usarla, sin cargarla al importarse."""
        for name in provenance.STALE_API:
            with self.subTest(name=name):
                self.assertIn(name, provenance.__all__)
                self.assertIs(getattr(provenance, name), getattr(stale_mod, name))
        self.assertLessEqual({"counts", "stale_items", "refresh_region", "refresh_all"},
                             set(provenance.STALE_API))
        tree = ast.parse(Path(provenance.__file__).read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                with self.subTest(line=node.lineno):
                    self.assertNotIn("stale", [alias.name for alias in node.names])


# --- Grafos aleatorios: región = completo (T27) -------------------------------------------------

_RANDOM_TABLES = ("gb_parameter", "gb_input", "gb_dataset", "gb_operation", "gb_operation_io",
                  "gb_operation_param", "gb_figure", "gb_stale")
_RANDOM_TYPES: dict[str, bool] = {"res.t0": True, "res.t1": True, "res.t2": True,
                                  "res.manual": False}  # tipo → se repite sola
_RANDOM_VERSIONS = {"res.t0": "1.1", "res.t1": "1.0", "res.t2": "1.0", "res.manual": "1.0"}
_POOL = tuple(hashing.sha256_bytes(f"contenido {n}".encode()) for n in range(3))
_VALUES = tuple(hashing.sha256_bytes(f"valor {n}".encode()) for n in range(3))


class RandomProject:
    """Una base en memoria con solo las tablas de la procedencia (sin disparadores) que cambia
    con pasos aleatorios como los caminos que escriben; cada paso devuelve lo que cambió, como
    lo pasan esos caminos a la caché."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.conn = sqlite3.connect(":memory:", isolation_level=None)
        for table in _RANDOM_TABLES:
            self.conn.execute(schema.TABLES[table])
        for sql in schema.INDEXES.values():
            self.conn.execute(sql)
        self.serial = 0
        self.live: dict[str, bool] = {}  # dato vivo → es lo importado
        self.content: dict[str, str] = {}
        self.versions: dict[str, list[str]] = {}
        self.inputs: list[str] = []  # entradas activas
        self.current: list[str] = []  # operaciones sin sustituir
        self.groups: list[str] = []
        self.params: dict[str, str] = {}
        for n in range(3):
            uid = self.uid()
            self.params[uid] = rng.choice(_VALUES)
            self.insert("gb_parameter", parameter_row(uid=uid, key=f"res.p{n}",
                                                      value_sha256=self.params[uid]))

    def uid(self) -> str:
        self.serial += 1
        return f"00000000-0000-4000-8000-{self.serial:012x}"

    def stamp(self) -> str:
        self.serial += 1
        minutes, seconds = divmod(self.serial, 60)
        return f"2026-10-08T{10 + minutes // 60:02d}:{minutes % 60:02d}:{seconds:02d}.000Z"

    def insert(self, table: str, row: Mapping[str, Any]) -> None:
        self.conn.execute(f"INSERT INTO {table} ({', '.join(row)}) "
                          f"VALUES ({', '.join('?' for _ in row)})", tuple(row.values()))

    def step(self) -> dict[str, list[str]]:
        roll = self.rng.random()
        if roll < 0.15:
            return self.change_parameter()
        if roll < 0.3 and self.live:
            return self.dataset_status()
        if roll < 0.37 and not all(self.live.values()):
            return self.supersede_dataset()
        if roll < 0.45 and self.inputs:
            return self.input_status()
        return self.operation()

    def operation(self) -> dict[str, list[str]]:
        rng = self.rng
        uid, now = self.uid(), self.stamp()
        op_type = rng.choice(tuple(_RANDOM_TYPES))
        importing = rng.random() < 0.15
        group_uid = None
        if not importing and rng.random() < 0.25:
            if self.groups and rng.random() < 0.6:
                group_uid = rng.choice(self.groups)
            else:
                group_uid = self.uid()
                self.groups.append(group_uid)
        supersedes = rng.choice(self.current) if self.current and rng.random() < 0.2 else None
        self.insert("gb_operation", operation_row(
            uid=uid, op_type=op_type, module="res", repeatable=int(_RANDOM_TYPES[op_type]),
            op_version=rng.choice(("1.0", "1.1")) if op_type == "res.t0" else "1.0",
            group_name=None if group_uid is None else "res.pair", group_uid=group_uid,
            supersedes_uid=supersedes, started_at=now, finished_at=now,
        ))
        live = sorted(self.live)
        for item in rng.sample(live, min(len(live), rng.randint(0, 3))):
            sha = self.content[item] if rng.random() < 0.85 else rng.choice(self.versions[item])
            self.insert("gb_operation_io", io_row(operation_uid=uid, direction="in",
                                                  item_uid=item, content_sha256=sha,
                                                  role="source"))
        if self.inputs and rng.random() < 0.2:
            self.insert("gb_operation_io", io_row(
                operation_uid=uid, direction="in", item_kind="input",
                item_uid=rng.choice(self.inputs), content_sha256=_POOL[0], role="entry",
            ))
        for parameter in rng.sample(sorted(self.params), rng.randint(0, 2)):
            value = self.params[parameter] if rng.random() < 0.9 else rng.choice(_VALUES)
            self.insert("gb_operation_param", op_param_row(
                operation_uid=uid, parameter_uid=parameter, value_sha256=value))
        written: list[str] = []
        if importing:
            entry = self.uid()
            self.insert("gb_input", input_row(uid=entry, name=f"Entrada_{self.serial}",
                                              operation_uid=uid))
            self.inputs.append(entry)
            written.append(self.new_dataset(uid, entry))
        for _ in range(0 if importing else rng.randint(1, 2)):
            targets = [item for item in live if not self.live[item] and item not in written]
            if targets and rng.random() < 0.4:
                item = rng.choice(targets)
                sha = rng.choice(_POOL)
                self.conn.execute("UPDATE gb_dataset SET content_sha256 = ?, operation_uid = ?, "
                                  "status = 'current' WHERE uid = ?", (sha, uid, item))
                self.content[item] = sha
                self.versions[item].append(sha)
                self.insert("gb_operation_io", io_row(operation_uid=uid, item_uid=item,
                                                      content_sha256=sha, role="result"))
                written.append(item)
            else:
                written.append(self.new_dataset(uid, None))
        if supersedes is not None:
            self.conn.execute("UPDATE gb_operation SET superseded_by = ? WHERE uid = ?",
                              (uid, supersedes))
            self.current.remove(supersedes)
        self.current.append(uid)
        return {"operations": [uid], "datasets": written}

    def new_dataset(self, operation_uid: str, entry: str | None) -> str:
        uid = self.uid()
        sha = self.rng.choice(_POOL)
        name = f"res_d{self.serial}"
        self.insert("gb_dataset", dataset_row(
            uid=uid, name=name, module="res", kind="table", locator=name, selector="",
            content_sha256=sha, operation_uid=operation_uid, input_uid=entry,
            immutable=int(entry is not None),
        ))
        self.insert("gb_operation_io", io_row(
            operation_uid=operation_uid, item_uid=uid, content_sha256=sha,
            role="result" if entry is None else "imported",
        ))
        self.live[uid] = entry is not None
        self.content[uid] = sha
        self.versions[uid] = [sha]
        return uid

    def change_parameter(self) -> dict[str, list[str]]:
        uid = self.rng.choice(sorted(self.params))
        self.params[uid] = self.rng.choice(_VALUES)  # puede volver al que leyeron
        self.conn.execute("UPDATE gb_parameter SET value_sha256 = ? WHERE uid = ?",
                          (self.params[uid], uid))
        return {"parameters": [uid]}

    def dataset_status(self) -> dict[str, list[str]]:
        item = self.rng.choice(sorted(self.live))
        status = self.rng.choice(("current", "missing", "blocked", "damaged"))
        self.conn.execute("UPDATE gb_dataset SET status = ? WHERE uid = ?", (status, item))
        return {"datasets": [item]}

    def supersede_dataset(self) -> dict[str, list[str]]:
        item = self.rng.choice(sorted(uid for uid, imported in self.live.items() if not imported))
        self.conn.execute("UPDATE gb_dataset SET status = 'superseded' WHERE uid = ?", (item,))
        del self.live[item]
        return {"datasets": [item]}

    def input_status(self) -> dict[str, list[str]]:
        """Una entrada sustituida o descartada, con lo importado de ella: se pasa solo la
        entrada (la caché busca sus datos)."""
        entry = self.rng.choice(self.inputs)
        status = self.rng.choice(("superseded", "discarded"))
        self.conn.execute("UPDATE gb_input SET status = ? WHERE uid = ?", (status, entry))
        for (item,) in self.conn.execute("SELECT uid FROM gb_dataset WHERE input_uid = ?",
                                         (entry,)).fetchall():
            if item in self.live:
                self.conn.execute("UPDATE gb_dataset SET status = ? WHERE uid = ?",
                                  (status, item))
                del self.live[item]
        self.inputs.remove(entry)
        return {"inputs": [entry]}

    def refresh(self, changes: Mapping[str, list[str]] | None = None) -> Any:
        """La caché por región con ``changes`` (o completa), en su transacción."""
        now = self.stamp()
        self.conn.execute("BEGIN")
        try:
            if changes is None:
                found = stale_mod.refresh_all(self.conn, now=now, versions=_RANDOM_VERSIONS)
            else:
                found = stale_mod.refresh_region(self.conn, now=now, versions=_RANDOM_VERSIONS,
                                                 **changes)
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")
        return found

    def expected(self) -> Any:
        state = graph_mod.deduce(graph_mod.load_graph(self.conn), versions=_RANDOM_VERSIONS)
        return stale_mod.expected_rows(state)

    def done(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM gb_operation").fetchone()[0])


class RegionPropertyTest(unittest.TestCase):
    def test_region_matches_full_on_random_graphs(self) -> None:
        """RF-008-24, RF-008-25 (plan §5.4.3, D3): en 200 grafos aleatorios —operaciones
        repetibles y no, grupos acoplados, sustituidas, ediciones propias, versiones anteriores
        consumidas, entradas sustituidas y descartadas, datos que faltan, bloqueados, dañados o
        sustituidos, parámetros que cambian y vuelven, algoritmos más nuevos—, tras cada cambio
        la obsolescencia por región (solo lo alcanzable desde lo que cambió, con la caché para
        lo de fuera) deja la caché igual que el cálculo completo, y casi siempre recalcula menos
        que el grafo entero."""
        seeds = random.Random(20261008)
        smaller = total = 0
        for case in range(200):
            world = RandomProject(random.Random(seeds.getrandbits(64)))
            try:
                for _ in range(world.rng.randint(4, 14)):
                    world.step()
                world.refresh()
                self.assertEqual(stale_mod.cached_rows(world.conn), world.expected(),
                                 f"caso {case}, completo")
                for step in range(5):
                    changes = world.step()
                    update = world.refresh(changes)
                    self.assertEqual(stale_mod.cached_rows(world.conn), world.expected(),
                                     f"caso {case}, paso {step}: {changes}")
                    total += 1
                    smaller += len(update.operations) < world.done()
            finally:
                world.conn.close()
        self.assertGreater(smaller, total // 2)


if __name__ == "__main__":
    unittest.main()

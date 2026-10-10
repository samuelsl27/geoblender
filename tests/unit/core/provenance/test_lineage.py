# SPDX-License-Identifier: GPL-3.0-or-later
"""Procedencia de una cifra o un dato, marcas de las cifras, cifra vigente y estado de lo
mostrado (spec 008, T35; RF-008-23, RF-008-29, RF-008-30, RF-008-31; plan 008 §5.3.1, §5.3.4
y §5.4.10).

``core.provenance.lineage`` solo lee el proyecto:

- ``lineage`` da la cadena de una cifra, un dato o una operación hasta sus entradas: desde la
  operación de la cifra (o la que escribió el contenido actual del dato), hacia arriba por las
  **versiones** que consumió cada operación, hasta las importaciones y sus entradas; cada
  entrada con su estado (también «cambiada · se mantiene la copia» y «sustituida»), cada
  operación con los parámetros que leyó (valor, unidad, tipo, «sin confirmar», quién lo
  decidió), las versiones de su algoritmo, de Geoblender y de sus bibliotecas, quién, cuándo y
  dónde, y si está obsoleta y por qué;
- ``figure_marks``: «depende de una hipótesis» y «depende de un valor sin confirmar» según el
  estado **de hoy** de los parámetros de aguas arriba (un cambio solo de tipo quita o pone la
  marca sin dejar nada obsoleto) y «obsoleta», si lo está su operación;
- ``current_figure``: la cifra vigente de una clave y un ámbito, la de la operación más
  reciente (sin sustituir) que no está obsoleta, o la más reciente si todas lo están;
- ``result_state``: resultado, pendiente de incorporar, no incorporada, vista previa o
  medición.

``lineage`` carga solo lo que está aguas arriba de lo pedido (T63, RNF-008-03): cada
procedencia de estas pruebas se compara con la que da el grafo entero (``load_graph``), que tiene
que ser idéntica, también en grafos aleatorios.

Cada prueba usa el proyecto sintético de ``test_graph`` (esquema 2, reloj simulado) con sus
tipos de operación, sus parámetros (``res.production``, HIPÓTESIS por defecto, y
``res.density``, ADOPTADO por defecto, los dos «sin confirmar» hasta que una persona los
confirma o los cambia) y su cifra ``res.marks``.
"""

from __future__ import annotations

import ast
import random
import sqlite3
import types
import unittest
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from unittest import mock

from tests.support.core_fixtures import make_session
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.unit.core.provenance.test_graph import (
    _RANDOM_VERSIONS,
    INPUT_1,
    GraphCase,
    RandomProject,
    Use,
    _replace_table,
    _spec,
    _uses,
)
from tests.unit.core.provenance.test_operations import INTERPRETER, SOFTWARE, _insert
from tests.unit.core.provenance.test_schema import input_row, io_row, operation_row

provenance = import_geoblender("core.provenance")
lineage_mod = import_geoblender("core.provenance.lineage")
graph_mod = import_geoblender("core.provenance.graph")
stale_mod = import_geoblender("core.provenance.stale")
schema = import_geoblender("core.provenance.schema")
figures = import_geoblender("core.provenance.figures")
operations = import_geoblender("core.provenance.operations")
messages = import_geoblender("core.provenance.messages")
inputs = import_geoblender("core.inputs")
dataset_registry = import_geoblender("core.datasets.registry")
params = import_geoblender("core.params")
store_mod = import_geoblender("core.params.store")
i18n = import_geoblender("core.i18n")
timeutil = import_geoblender("core.timeutil")

Cause = graph_mod.Cause
CauseKind = graph_mod.CauseKind
ProvenanceError = messages.ProvenanceError
HYPOTHESIS = params.ParamKind.HIPOTESIS
INPUT_3 = "00000000-0000-4000-8000-0000000002e3"
SESSION = make_session()
BENCH = {"bench": 125}
OTHER_BENCH = {"bench": 130}
NOT_INGESTED = "La carpeta del trabajo «job-0001» se borró sin incorporar su resultado"

HYPOTHESIS_ES = "depende de una hipótesis"
UNCONFIRMED_ES = "depende de un valor sin confirmar"
STALE_ES = "obsoleta"


def _local_day(moment: str) -> str:
    return timeutil.parse_utc(moment).astimezone().strftime("%d/%m/%Y")


def whole_graph_lineage(project: Any, item: str, *, conn: sqlite3.Connection | None = None,
                        language: str = "es", versions: Mapping[str, str] | None = None) -> Any:
    """La procedencia de ``item`` construida sobre el grafo **entero** del proyecto
    (``load_graph`` con lo que cambió mientras se calculaba cada operación): la referencia con
    que se compara la que carga solo lo de aguas arriba."""
    chosen = dict(graph_mod.installed_versions() if versions is None else versions)
    with lineage_mod._reading(project, conn) as reading:
        found = lineage_mod._find(reading, item)
        assert found is not None, item
        whole = graph_mod.load_graph(reading, during=True)
        return lineage_mod._Builder(reading, whole, chosen, language).tree(found)


def same_lineage(case: unittest.TestCase, tree: Any, reference: Any, what: str = "") -> None:
    """``tree`` es idéntica a ``reference``: lo mismo, en el mismo orden, con las mismas
    filas."""
    case.assertEqual(tree, reference, what)
    case.assertEqual(list(tree.operations), list(reference.operations), what)
    case.assertEqual(list(tree.inputs), list(reference.inputs), what)
    case.assertEqual(tree.rows(), reference.rows(), what)


class LineageCase(GraphCase):
    """El proyecto de ``GraphCase`` con cifras en un ámbito y la cadena de una cifra hasta su
    entrada."""

    def run_figures(
        self,
        op_type: str,
        writes: Mapping[str, Sequence[float]] | None = None,
        *,
        reads: Sequence[Any] = (),
        params: Sequence[str] = (),
        figures: Sequence[tuple[float, Mapping[str, Any]]] = (),
        supersedes: str | None = None,
    ) -> Any:
        """Una operación hecha como ``GraphCase.run_op`` que registra las cifras
        ``res.marks`` de ``figures`` (valor, ámbito)."""
        handle = self.begin(op_type, inputs=_uses(reads), params=list(params),
                            supersedes=supersedes)
        shown = [figures_spec(value, scope) for value, scope in figures]

        def work(conn: sqlite3.Connection) -> None:
            specs = []
            for name, values in (writes or {}).items():
                _replace_table(conn, name, values)
                specs.append(_spec(name))
            handle.complete(conn, outputs=specs, figures=shown)

        self.write(work)
        self.tick()
        return handle

    def figure(self, handle: Any, scope: Mapping[str, Any] | None = None) -> str:
        """El uid de la cifra ``res.marks`` de la operación ``handle`` en ``scope``."""
        rows = self.query("SELECT uid FROM gb_figure WHERE operation_uid = ? AND scope = ?",
                          (handle.uid, figures.scope_json(scope or {})))
        self.assertEqual(len(rows), 1, (handle.op_type, scope))
        return str(rows[0][0])

    def figure_chain(self) -> tuple[Any, Any, Any, str]:
        """Entrada_1 → lo importado («res_im1») → A («res_a», lee la producción) → B
        («res_b», lee la densidad y da la cifra 7)."""
        imported = self.import_input(INPUT_1, "Entrada_1", "res_im1")
        a = self.run_op("res.step_a", {"res_a": [1.0, 2.0]}, reads=["res_im1"],
                        params=["res.production"])
        b = self.run_figures("res.step_b", {"res_b": [3.0]}, reads=["res_a"],
                             params=["res.density"], figures=[(7.0, {})])
        return imported, a, b, self.figure(b)

    def lineage(self, item: str, **kw: Any) -> Any:
        """La procedencia de ``item``, comprobando que no escribe nada y que es idéntica a la
        del grafo entero."""
        before = self.snapshot()
        tree = lineage_mod.lineage(self.project, item, **kw)
        self.assertEqual(self.snapshot(), before)
        same_lineage(self, tree, whole_graph_lineage(self.project, item, **kw), item)
        return tree

    def loaded(self, item: str, **kw: Any) -> tuple[Any, Any]:
        """La procedencia de ``item`` y el grafo con que se construyó."""
        seen: list[Any] = []
        build = lineage_mod._Builder.__init__

        def spy(builder: Any, conn: Any, graph: Any, *args: Any) -> None:
            seen.append(graph)
            build(builder, conn, graph, *args)

        with mock.patch.object(lineage_mod._Builder, "__init__", spy):
            tree = lineage_mod.lineage(self.project, item, **kw)
        (graph,) = seen
        same_lineage(self, tree, whole_graph_lineage(self.project, item, **kw), item)
        return tree, graph

    def marks(self, *uids: str) -> Any:
        before = self.snapshot()
        found = lineage_mod.figure_marks(self.project, list(uids))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(set(found), set(uids))
        return found

    def current(self, key: str = "res.marks", scope: Mapping[str, Any] | None = None) -> Any:
        """La cifra vigente de ``key`` en ``scope``; comprueba que es la que deduce el grafo
        (``Staleness.current_figures``)."""
        found = lineage_mod.current_figure(self.project, key, scope)
        state = self.stale()
        expected = state.current_figures.get((key, figures.scope_key(scope or {})))
        self.assertEqual(None if found is None else found.uid, expected)
        return found

    def state(self, item: str | None = None, **kw: Any) -> Any:
        before = self.snapshot()
        found = lineage_mod.result_state(self.project, item, **kw)
        self.assertEqual(self.snapshot(), before)
        return found


def figures_spec(value: float, scope: Mapping[str, Any]) -> Any:
    return figures.FigureSpec("res.marks", value, "-", scope=dict(scope))


def _row_ids(tree: Any) -> list[tuple[int, str, str, bool]]:
    return [(row.depth, str(row.kind), row.uid, row.repeated) for row in tree.rows()]


class LineageTest(LineageCase):
    def test_figure_lineage_up_to_its_inputs(self) -> None:
        """RF-008-29, RF-008-30: la procedencia de una cifra lleva, por las versiones que
        consumió cada operación, hasta la importación y su entrada (con su estado), con los
        parámetros que leyó cada una (valor, unidad, tipo, «sin confirmar» y quién lo
        decidió), las versiones de su algoritmo, de Geoblender y de las bibliotecas, quién,
        cuándo y dónde; sin nada obsoleto, ningún eslabón lo está. Se pide también por el uid
        o el nombre de un dato vivo y por una operación; lo que no es nada de eso se
        rechaza nombrándolo."""
        imported, a, b, fig = self.figure_chain()
        tree = self.lineage(fig)
        self.assertEqual((tree.kind, tree.uid, tree.root), ("figure", fig, b.uid))
        record = tree.figure
        self.assertEqual(
            (record.key, record.label, record.value, record.unit, record.kind,
             record.operation_uid, dict(record.scope)),
            ("res.marks", "Marcas", 7.0, "-", "CALCULADO", b.uid, {}),
        )
        self.assertIsNone(tree.dataset)
        self.assertEqual(list(tree.operations), [b.uid, a.uid, imported.uid])
        node_b, node_a, node_i = (tree.operations[h.uid] for h in (b, a, imported))

        row = self.row(b.uid)
        self.assertEqual(
            (node_b.op_type, node_b.op_version, node_b.module, node_b.status,
             node_b.geoblender_version, dict(node_b.software), node_b.executor, node_b.job_uid,
             node_b.user_host, node_b.host, node_b.started_at, node_b.finished_at),
            ("res.step_b", "1.0", "res", "done", row["geoblender_version"], {}, "blender", None,
             SESSION.user_host, row["host"], row["started_at"], row["finished_at"]),
        )
        self.assertEqual((node_a.op_version, node_i.op_type, node_i.repeatable),
                         ("1.9", "res.import_source", False))
        self.assertEqual((node_b.upstream, node_a.upstream, node_i.upstream),
                         ((a.uid,), (imported.uid,), ()))
        (version,) = node_b.consumed
        self.assertEqual(
            (version.uid, version.name, version.role, version.producer_uid, version.current,
             version.content_sha256),
            (self.dataset("res_a"), "res_a", "source", a.uid, True, self.content_of("res_a")[0]),
        )
        (imported_version,) = node_a.consumed
        self.assertEqual((imported_version.name, imported_version.producer_uid,
                          imported_version.input_uid), ("res_im1", imported.uid, INPUT_1))
        self.assertEqual(node_i.inputs, (lineage_mod.InputUse(INPUT_1, None),))
        self.assertEqual((node_b.inputs, node_i.consumed), ((), ()))
        entry = tree.inputs[INPUT_1]
        self.assertEqual((entry.name, entry.status, entry.operation_uid, entry.text()),
                         ("Entrada_1", "current", imported.uid, "Entrada_1: vigente"))
        self.assertEqual(entry.text(language="en"), "Entrada_1: current")

        (density,) = node_b.params
        self.assertEqual(
            (density.key, density.value, density.unit, density.kind, density.unconfirmed,
             density.rev, density.decided_by, density.changed),
            ("res.density", 2.5, "t/m3", "ADOPTADO", True, 1, store_mod.DEFAULT_DECIDER, False),
        )
        self.assertEqual(density.value_text(), "2,5 t/m³")
        (production,) = node_a.params
        self.assertEqual(
            (production.key, production.value, production.unit, production.kind,
             production.unconfirmed, production.current_kind),
            ("res.production", 100000.0, "t/yr", HYPOTHESIS, True, HYPOTHESIS),
        )
        self.assertEqual(node_i.params, ())

        self.assertEqual(tree.stale_operations, ())
        for node in tree.operations.values():
            with self.subTest(op_type=node.op_type):
                self.assertEqual((node.stale, node.causes, node.stale_text, node.review),
                                 (False, frozenset(), None, False))
                self.assertEqual(node.result.state, "result")
        self.assertEqual(tree.result.state, "result")
        self.assertEqual((tree.marks.hypotheses, tree.marks.unconfirmed_params),
                         (("res.production",), ("res.density", "res.production")))
        self.assertEqual((tree.marks.stale, tree.marks.current), (False, True))
        self.assertEqual(tree.marks.texts(), (HYPOTHESIS_ES, UNCONFIRMED_ES))

        uid_a, uid_im = self.dataset("res_a"), self.dataset("res_im1")
        density_uid, production_uid = self.parameter("res.density"), self.parameter(
            "res.production")
        self.assertEqual(_row_ids(tree), [
            (0, "figure", fig, False),
            (1, "operation", b.uid, False),
            (2, "parameter", density_uid, False),
            (2, "dataset", uid_a, False),
            (3, "operation", a.uid, False),
            (4, "parameter", production_uid, False),
            (4, "dataset", uid_im, False),
            (5, "operation", imported.uid, False),
            (6, "input", INPUT_1, False),
        ])

        by_name = self.lineage("res_b")
        self.assertEqual((by_name.kind, by_name.uid, by_name.root),
                         ("dataset", self.dataset("res_b"), b.uid))
        self.assertEqual((by_name.dataset.name, by_name.dataset.current, by_name.figure),
                         ("res_b", True, None))
        self.assertEqual(list(by_name.operations), [b.uid, a.uid, imported.uid])
        self.assertEqual(self.lineage(self.dataset("res_b")).uid, by_name.uid)
        self.assertEqual(by_name.marks, lineage_mod.FigureMarks(
            self.dataset("res_b"), ("res.production",), ("res.density", "res.production"),
            frozenset(), True))
        of_a = self.lineage(a.uid)
        self.assertEqual((of_a.kind, of_a.root, list(of_a.operations)),
                         ("operation", a.uid, [a.uid, imported.uid]))
        self.assertEqual(_row_ids(of_a)[0], (0, "operation", a.uid, False))

        error = self.assertRejected(ProvenanceError, "core.lineage_unknown",
                                    lambda: lineage_mod.lineage(self.project, "res_nada"))
        self.assertIn("«res_nada» no es un dato, una cifra ni una operación del proyecto",
                      str(error))
        with self.assertRaises(TypeError):
            lineage_mod.lineage(self.project, None)

    def test_code_versions_and_where_it_ran(self) -> None:
        """RF-008-29 (RF-008-18): un eslabón calculado en un trabajo de la 004 lleva la
        versión de su algoritmo, las de las bibliotecas que influyen en sus cifras, su
        ejecutor con su trabajo, la procedencia técnica del intérprete y el equipo."""
        self.run_op("res.step_a", {"res_a": [1.0]})
        handle = self.begin("res.balance", inputs=_uses(["res_a"]), executor="job_process")

        def work(conn: sqlite3.Connection) -> None:
            _replace_table(conn, "res_saldo", [2.0])
            handle.complete(conn, outputs=[_spec("res_saldo")], software=SOFTWARE,
                            interpreter=INTERPRETER, job_uid="job-0002",
                            figures=[figures_spec(6.0, {})])

        self.write(work)
        node = self.lineage(self.figure(handle)).operations[handle.uid]
        self.assertEqual(
            (node.op_type, node.op_version, dict(node.software), node.executor, node.job_uid,
             dict(node.interpreter), node.host, node.result.state),
            ("res.balance", "1.2", SOFTWARE, "job_process", "job-0002", INTERPRETER,
             SESSION.host, "result"),
        )

    def test_input_used_directly_review_and_superseded_dataset(self) -> None:
        """RF-008-29: una entrada que una operación consume directamente sale bajo ella con su
        papel; un eslabón que espera revisión a mano lo dice; la procedencia de un dato que ya
        no está vivo sigue su cadena, con la obsolescencia de la operación que lo escribió."""
        self.import_input(INPUT_1, "Entrada_1", "res_im1")
        a = self.run_op("res.step_a", {"res_a": [1.0]}, params=["res.production"],
                        reads=[Use(INPUT_1, "boundary", kind="input")])
        d = self.run_op("res.digitize", {"res_r": [2.0]}, reads=["res_a"])
        tree = self.lineage(a.uid)
        self.assertEqual(list(tree.operations), [a.uid])
        self.assertEqual(tree.operations[a.uid].inputs, (lineage_mod.InputUse(INPUT_1,
                                                                             "boundary"),))
        rows = tree.rows()
        self.assertEqual([(row.depth, str(row.kind), row.uid, row.role) for row in rows],
                         [(0, "operation", a.uid, None),
                          (1, "parameter", self.parameter("res.production"), None),
                          (1, "input", INPUT_1, "boundary")])

        self.change("res.production", 80000.0)
        production = Cause(CauseKind.PARAMETER_CHANGED, self.parameter("res.production"))
        uid_a = self.dataset("res_a")
        chain = self.lineage("res_r")
        self.assertEqual((chain.operations[d.uid].review, chain.operations[a.uid].review),
                         (True, False))  # no se repite sola y escribió un dato vivo
        self.assertEqual(self.lineage(uid_a).marks.causes, frozenset({production}))
        self.write(lambda conn: dataset_registry.supersede(conn, self.project, uid_a))
        gone = self.lineage(uid_a)
        self.assertEqual((gone.dataset.status, gone.dataset.current, gone.root),
                         ("superseded", False, a.uid))
        self.assertEqual((gone.marks.causes, gone.marks.current, gone.result.state),
                         (frozenset({production}), False, "result"))
        with self.assertRaises(ProvenanceError):
            lineage_mod.lineage(self.project, "res_a")  # ya no hay ninguno vivo con ese nombre

    def test_diamond_is_shown_once_and_marked_repeated(self) -> None:
        """RF-008-29: una operación a la que se llega por dos caminos sale una vez con lo suyo
        y la segunda como repetida, sin sus ramas."""
        a = self.run_op("res.step_a", {"res_a": [1.0]}, params=["res.production"])
        b = self.run_op("res.step_b", {"res_b": [2.0]}, reads=["res_a"])
        c = self.run_op("res.step_c", {"res_c": [3.0]}, reads=["res_a"])
        d = self.run_figures("res.step_d", reads=["res_b", "res_c"], figures=[(4.0, {})])
        tree = self.lineage(self.figure(d))
        self.assertEqual(list(tree.operations), [d.uid, b.uid, c.uid, a.uid])
        rows = [(depth, kind, uid, repeated) for depth, kind, uid, repeated in _row_ids(tree)
                if kind == "operation"]
        self.assertEqual(rows, [(1, "operation", d.uid, False), (3, "operation", b.uid, False),
                                (5, "operation", a.uid, False), (3, "operation", c.uid, False),
                                (5, "operation", a.uid, True)])
        repeated = [row for row in tree.rows() if row.repeated]
        self.assertEqual(len(repeated), 1)
        index = tree.rows().index(repeated[0])
        self.assertEqual(tree.rows()[index + 1:], ())  # sin ramas tras la repetida

    def test_stale_links_kept_and_superseded_inputs(self) -> None:
        """RF-008-29 (spec §8, «Mantener la copia» y «Actualizar dos veces una entrada»): un
        cambio de parámetro deja obsoletos los eslabones que dependen de él, con su causa; la
        entrada sale «cambiada · se mantiene la copia (quién, cuándo)» y, actualizada, la
        procedencia de la cifra antigua lleva a la entrada sustituida y la de la nueva, a la
        que la sustituye."""
        imported, a, b, fig = self.figure_chain()
        self.change("res.production", 120000.0)
        production = Cause(CauseKind.PARAMETER_CHANGED, self.parameter("res.production"))
        tree = self.lineage(fig)
        self.assertEqual(tree.stale_operations, (b.uid, a.uid))
        node_b, node_a, node_i = (tree.operations[h.uid] for h in (b, a, imported))
        self.assertEqual((node_a.causes, node_b.causes, node_i.stale),
                         (frozenset({production}), frozenset({production}), False))
        self.assertEqual(node_b.stale_text, "Obsoleto: cambió Producción")
        self.assertEqual(self.lineage(fig, language="en").operations[a.uid].stale_text,
                         "Stale: Test production changed")
        (used,) = node_a.params
        self.assertEqual(
            (used.value, used.unconfirmed, used.current_value, used.current_unconfirmed,
             used.current_kind, used.changed),
            (100000.0, True, 120000.0, False, HYPOTHESIS, True),
        )
        self.assertEqual((used.rev, used.current_rev, used.decided_by),
                         (1, 2, store_mod.DEFAULT_DECIDER))  # quién decidió lo que leyó
        self.assertEqual((tree.marks.stale, tree.marks.causes), (True, frozenset({production})))
        self.assertEqual(tree.marks.texts(), (HYPOTHESIS_ES, UNCONFIRMED_ES, STALE_ES))
        self.assertEqual(tree.marks.texts(language="en"),
                         ("depends on a hypothesis", "depends on an unconfirmed value", "stale"))

        self.mark_changed(INPUT_1)
        self.assertEqual(self.lineage(fig).inputs[INPUT_1].text(), "Entrada_1: cambiada")
        self.write(lambda conn: inputs.keep_copy(conn, self.project, INPUT_1,
                                                 reason="la entrega nueva no está validada"))
        kept = self.lineage(fig).inputs[INPUT_1]
        (row,) = self.query("SELECT status_at FROM gb_input WHERE uid = ?", (INPUT_1,))
        self.assertEqual(kept.status, "kept")
        self.assertEqual(kept.text(), "Entrada_1: cambiada · se mantiene la copia "
                                      f"({SESSION.user_host}, {_local_day(row[0])})")
        self.assertEqual(kept.text(language="en"), "Entrada_1: changed · copy kept "
                                                   f"({SESSION.user_host}, {_local_day(row[0])})")

        def update(conn: sqlite3.Connection, handle: Any) -> None:
            inputs.supersede(conn, self.project, INPUT_1, operation_uid=handle.uid,
                             reason="nueva entrega")
            _insert(conn, "gb_input", input_row(
                uid=INPUT_3, name="Entrada_1", operation_uid=handle.uid, previous_uid=INPUT_1,
                status_at="2026-10-05T08:12:44.000Z", status_by=SESSION.user_host))
            _replace_table(conn, "res_im3", [1.0, 3.0])

        reimport = self.run_op("res.import_source", supersedes=imported.uid, before=update,
                               outputs=[_spec("res_im3", role="imported", input_uid=INPUT_3)])
        a2 = self.run_op("res.step_a", {"res_a": [5.0, 6.0]}, reads=["res_im3"],
                         params=["res.production"], supersedes=a.uid)
        b2 = self.run_figures("res.step_b", {"res_b": [7.0]}, reads=["res_a"],
                              params=["res.density"], figures=[(8.0, {})], supersedes=b.uid)

        old = self.lineage(fig)
        self.assertEqual(list(old.operations), [b.uid, a.uid, imported.uid])
        (row,) = self.query("SELECT status_at FROM gb_input WHERE uid = ?", (INPUT_1,))
        superseded = old.inputs[INPUT_1]
        self.assertEqual((superseded.status, superseded.successor_uid, superseded.text()),
                         ("superseded", INPUT_3,
                          f"Entrada_1: sustituida ({SESSION.user_host}, {_local_day(row[0])})"))
        self.assertFalse(old.operations[a.uid].consumed[0].current)  # lo importado, sustituido
        self.assertFalse(old.operations[b.uid].consumed[0].current)  # «res_a» se reescribió
        self.assertEqual((old.marks.current, old.marks.stale), (False, True))
        self.assertEqual((self.lineage(a.uid).marks.current, self.lineage(a2.uid).marks.current),
                         (False, True))

        new = self.lineage(self.figure(b2))
        self.assertEqual(list(new.operations), [b2.uid, a2.uid, reimport.uid])
        self.assertEqual(new.stale_operations, ())
        replacement = new.inputs[INPUT_3]
        self.assertEqual((replacement.status, replacement.previous_uid, replacement.text()),
                         ("current", INPUT_1, "Entrada_1: vigente"))
        self.assertEqual((new.marks.current, new.marks.stale), (True, False))


class MarksTest(LineageCase):
    def test_marks_follow_the_current_state_of_the_parameters(self) -> None:
        """RF-008-31, RF-008-04 (spec §8): una HIPÓTESIS aguas arriba pone «depende de una
        hipótesis» y un valor por defecto, «depende de un valor sin confirmar»; pasar la
        HIPÓTESIS a ADOPTADO con el mismo valor quita la marca (y volver a HIPÓTESIS la pone)
        sin dejar nada obsoleto, confirmar el valor por defecto quita la suya y cambiar un
        valor deja la cifra «obsoleta»."""
        self.run_op("res.step_a", {"res_a": [1.0]}, params=["res.production"])
        f_op = self.run_figures("res.step_b", {"res_b": [2.0]}, reads=["res_a"],
                                figures=[(3.0, {})])
        g_op = self.run_figures("res.step_d", params=["res.density"], figures=[(4.0, BENCH)])
        f, g = self.figure(f_op), self.figure(g_op, BENCH)
        found = self.marks(f, g)
        self.assertEqual(found[f], lineage_mod.FigureMarks(
            f, ("res.production",), ("res.production",), frozenset(), True))
        self.assertEqual((found[f].hypothesis, found[f].unconfirmed, found[f].stale),
                         (True, True, False))
        self.assertEqual(found[f].texts(), (HYPOTHESIS_ES, UNCONFIRMED_ES))
        self.assertEqual(found[g].texts(), (UNCONFIRMED_ES,))
        self.assertEqual(found[g].marks, (lineage_mod.Mark.UNCONFIRMED,))
        self.assertEqual(self.lineage(f).marks, found[f])

        self.change("res.production", kind="ADOPTADO")  # el mismo valor
        self.assertNothingStale(self.stale())
        self.assertEqual(self.marks(f)[f].texts(), ())
        self.change("res.production", kind=HYPOTHESIS)
        self.assertEqual(self.marks(f)[f].texts(), (HYPOTHESIS_ES,))
        self.write(lambda conn: self.store.confirm(conn, "res.density"))
        self.assertEqual(self.marks(g)[g].texts(), ())
        self.assertNothingStale(self.stale())

        self.change("res.production", 90000.0)
        production = Cause(CauseKind.PARAMETER_CHANGED, self.parameter("res.production"))
        after = self.marks(f, g)
        self.assertEqual((after[f].stale, after[f].causes, after[f].current),
                         (True, frozenset({production}), True))
        self.assertEqual(after[f].texts(), (HYPOTHESIS_ES, STALE_ES))
        self.assertEqual(after[f].marks, (lineage_mod.Mark.HYPOTHESIS, lineage_mod.Mark.STALE))
        self.assertEqual(after[g].texts(), ())
        self.assertEqual(self.lineage(f).marks, after[f])

        self.assertEqual(lineage_mod.figure_marks(self.project, []), {})
        with self.assertRaises(TypeError):
            lineage_mod.figure_marks(self.project, f)
        self.assertRejected(ProvenanceError, "core.lineage_unknown",
                            lambda: lineage_mod.figure_marks(self.project, [f, "otra"]))

    def test_current_figure_is_the_latest_one_not_stale(self) -> None:
        """RF-008-30, RF-008-31 (spec §6): la cifra vigente de una clave y un ámbito es la de
        la operación más reciente (sin sustituir) que no está obsoleta; si todas lo están, la
        más reciente, con su marca; cada ámbito por su lado."""
        p = self.run_figures("res.step_a", params=["res.production"],
                             figures=[(1.0, BENCH), (9.0, OTHER_BENCH)])
        q = self.run_figures("res.step_d", params=["res.density"], figures=[(2.0, BENCH)])
        found = self.current(scope=BENCH)
        self.assertEqual((found.uid, found.value, dict(found.scope)),
                         (self.figure(q, BENCH), 2.0, BENCH))
        self.assertEqual(self.current(scope=OTHER_BENCH).uid, self.figure(p, OTHER_BENCH))
        self.assertIsNone(self.current())  # el ámbito vacío es otro
        self.assertIsNone(self.current("res.other", BENCH))

        self.change("res.density", 2.6)  # q obsoleta: la vigente pasa a la anterior al día
        self.assertEqual(self.current(scope=BENCH).uid, self.figure(p, BENCH))
        self.change("res.production", 95000.0)  # todas obsoletas: la más reciente
        self.assertEqual(self.current(scope=BENCH).uid, self.figure(q, BENCH))
        found = self.marks(self.figure(p, BENCH), self.figure(q, BENCH))
        self.assertEqual([(m.stale, m.current) for m in found.values()],
                         [(True, False), (True, True)])

        r = self.run_figures("res.step_d", params=["res.density"], figures=[(3.0, BENCH)],
                             supersedes=q.uid)
        self.assertEqual(self.current(scope=BENCH).uid, self.figure(r, BENCH))
        self.assertEqual(self.current(scope=OTHER_BENCH).uid, self.figure(p, OTHER_BENCH))
        old = self.marks(self.figure(q, BENCH))[self.figure(q, BENCH)]
        self.assertEqual((old.current, old.stale), (False, True))

        s1 = self.run_figures("res.step_d", figures=[(5.0, {"bench": 140})])
        self.run_figures("res.step_d", supersedes=s1.uid)  # sin esa cifra
        self.assertIsNone(self.current(scope={"bench": 140}))
        with self.assertRaises(TypeError):
            lineage_mod.current_figure(self.project, None, BENCH)
        with self.assertRaises(ValueError):
            lineage_mod.current_figure(self.project, "res.marks", {"Bench": 1})


class ResultStateTest(LineageCase):
    def test_result_pending_not_ingested_preview_and_measurement(self) -> None:
        """RF-008-23 (spec §8): lo guardado en el proyecto es «resultado»; lo de un trabajo aún
        sin incorporar, «pendiente de incorporar» (también en su procedencia), y «no
        incorporada», con el motivo, si su carpeta se borró; lo que solo está en la vista,
        «vista previa, sin guardar» o «medición, no registrada», y nunca un resultado (tampoco
        lo de una operación que falló o lo que el proyecto no tiene)."""
        a = self.run_figures("res.step_a", {"res_a": [1.0]}, figures=[(5.0, {})])
        for item in (a.uid, self.dataset("res_a"), "res_a", self.figure(a)):
            with self.subTest(item=item):
                found = self.state(item)
                self.assertEqual((found.state, found.saved, found.text()),
                                 ("result", True, "resultado"))
        self.assertEqual(self.state(a.uid).operation_uid, a.uid)

        job = self.begin("res.step_b", inputs=_uses(["res_a"]), params=["res.density"],
                         executor="job_thread", job_uid="job-0001")
        pending = self.state(job.uid)
        self.assertEqual((pending.state, pending.saved, pending.operation_uid, pending.text(),
                          pending.text(language="en")),
                         ("pending", False, job.uid, "pendiente de incorporar",
                          "pending ingestion"))
        tree = self.lineage(job.uid)
        self.assertEqual((tree.kind, tree.root, tree.result.state, list(tree.operations)),
                         ("operation", job.uid, "pending", [job.uid, a.uid]))
        node = tree.operations[job.uid]
        self.assertEqual((node.status, node.executor, node.job_uid, node.finished_at),
                         ("running", "job_thread", "job-0001", None))
        self.assertEqual(([p.key for p in node.params], node.consumed[0].producer_uid),
                         (["res.density"], a.uid))

        self.assertTrue(operations.mark_not_ingested(self.project, job.uid, NOT_INGESTED))
        lost = self.state(job.uid)
        self.assertEqual((lost.state, lost.saved, lost.reason, lost.text()),
                         ("not_ingested", False, NOT_INGESTED,
                          f"no incorporada: {NOT_INGESTED}"))
        self.assertEqual(lost.text(language="en"), f"not ingested: {NOT_INGESTED}")
        self.assertEqual(self.lineage(job.uid).result, lost)

        for view, spanish, english in (("preview", "vista previa, sin guardar",
                                        "preview, not saved"),
                                       ("measurement", "medición, no registrada",
                                        "measurement, not recorded")):
            with self.subTest(view=view):
                shown = self.state(view=view)
                self.assertEqual((shown.state, shown.saved, shown.text(),
                                  shown.text(language="en")), (view, False, spanish, english))
                self.assertEqual(self.state(a.uid, view=view).state, view)

        failed = self.begin("res.step_c")  # en curso, en el hilo de Blender
        self.assertEqual(self.state(failed.uid).state, "preview")
        failed.fail("prueba de una operación que no termina")
        for item in (failed.uid, "00000000-0000-4000-8000-0000000009ff"):
            with self.subTest(item=item):
                found = self.state(item)
                self.assertEqual((found.state, found.saved), ("preview", False))
        self.assertEqual(self.state(failed.uid).reason,
                         "prueba de una operación que no termina")
        with self.assertRaises(ValueError):
            lineage_mod.result_state(self.project, a.uid, view="result")
        with self.assertRaises(TypeError):
            lineage_mod.result_state(self.project)


class UpstreamTest(LineageCase):
    def test_only_what_is_upstream_is_loaded(self) -> None:
        """RNF-008-03, RF-008-29: la procedencia de una cifra, de un dato o de una operación
        (también en curso) carga solo las operaciones de aguas arriba de lo pedido (las que
        escribieron lo que consumió cada una, hasta las importaciones) y los datos que
        consumieron, más lo pedido: ni otra cadena ni lo que depende de lo pedido. Es idéntica
        a la que da el grafo entero."""
        imported, a, b, fig = self.figure_chain()
        other = self.run_op("res.step_c", {"res_c": [9.0]}, params=["res.density"])
        later = self.run_op("res.step_d", {"res_d": [1.0]}, reads=["res_b"])
        uid_a, uid_im, uid_b = (self.dataset(name) for name in ("res_a", "res_im1", "res_b"))
        chain = {b.uid, a.uid, imported.uid}

        tree, graph = self.loaded(fig)
        self.assertEqual(list(tree.operations), [b.uid, a.uid, imported.uid])
        self.assertEqual((set(graph.operations), set(graph.datasets)), (chain, {uid_a, uid_im}))
        self.assertTrue({other.uid, later.uid}.isdisjoint(graph.operations))

        _tree, graph = self.loaded("res_b")
        self.assertEqual((set(graph.operations), set(graph.datasets)),
                         (chain, {uid_a, uid_im, uid_b}))

        job = self.begin("res.step_c", inputs=_uses(["res_b"]), executor="job_thread",
                         job_uid="job-0003")
        tree, graph = self.loaded(job.uid)
        self.assertEqual(list(tree.operations), [job.uid, b.uid, a.uid, imported.uid])
        self.assertEqual((set(graph.operations), set(graph.datasets)),
                         (chain, {uid_a, uid_im, uid_b}))  # la que está en curso no es del grafo

    def test_causes_are_told_as_in_the_whole_graph(self) -> None:
        """RF-008-25, RF-008-20, RF-008-29: las causas de los eslabones se cuentan como en el
        grafo entero aunque nombren lo que no está aguas arriba: la otra operación de su grupo
        acoplado y el parámetro que solo lee ella («cambió Densidad»); y lo que cambió
        mientras se calculaba un eslabón, «… mientras se calculaba», que no se dice del que se
        calculó después."""
        first = self.run_op("res.pair_first", {"res_x1": [1.0]}, figure=5.0)
        self.run_op("res.pair_second", {"res_x2": [2.0]}, reads=["res_x1"],
                    params=["res.density"], group_uid=first.group_uid)
        self.change("res.density", 2.7)
        tree, _graph = self.loaded(self.figure(first))
        self.assertEqual(list(tree.operations), [first.uid])
        self.assertEqual(tree.operations[first.uid].stale_text,
                         "Obsoleto: cambió Densidad; está acoplada en el grupo «res.pair»")

        self.run_op("res.step_a", {"res_a": [1.0]})
        running = self.begin("res.step_c", inputs=_uses(["res_a"]), params=["res.production"])
        self.tick()
        self.change("res.production", 90000.0)

        def finish(conn: sqlite3.Connection) -> None:
            _replace_table(conn, "res_c", [3.0])
            running.complete(conn, outputs=[_spec("res_c")])

        self.write(finish)
        self.tick()
        after = self.run_figures("res.step_d", reads=["res_c"], figures=[(4.0, {})])
        tree = self.lineage(self.figure(after))
        self.assertEqual(
            (tree.operations[running.uid].stale_text, tree.operations[after.uid].stale_text),
            ("Obsoleto: cambió Producción mientras se calculaba", "Obsoleto: cambió Producción"),
        )

    def test_inputs_in_their_order_and_successor_of_a_dataset(self) -> None:
        """RF-008-29: las entradas que registró una operación salen bajo ella en el orden en
        que se registraron, y un dato consumido que se sustituyó dice cuál lo sustituye, como
        en el grafo entero."""

        def register(conn: sqlite3.Connection, handle: Any) -> None:
            for uid, name in ((INPUT_1, "Entrada_1"), (INPUT_3, "Entrada_3")):
                _insert(conn, "gb_input", input_row(uid=uid, name=name,
                                                    operation_uid=handle.uid))
            _replace_table(conn, "res_im1", [1.0, 2.0])

        imported = self.run_op("res.import_source", before=register, outputs=[
            _spec("res_im1", role="imported", input_uid=INPUT_1)])
        a = self.run_figures("res.step_a", {"res_a": [1.0]}, reads=["res_im1"],
                             figures=[(2.0, {})])
        self.run_op("res.step_c", {"res_c": [3.0]})
        old, new = self.dataset("res_a"), self.dataset("res_c")
        b = self.run_figures("res.step_b", reads=["res_a"], figures=[(4.0, {})])
        self.write(lambda conn: dataset_registry.supersede(conn, self.project, old, by=new))
        tree, _graph = self.loaded(self.figure(a))
        self.assertEqual(tree.operations[imported.uid].inputs,
                         (lineage_mod.InputUse(INPUT_1, None), lineage_mod.InputUse(INPUT_3, None)))
        tree, _graph = self.loaded(self.figure(b))
        (version,) = tree.operations[b.uid].consumed
        self.assertEqual((version.uid, version.superseded_by), (old, new))

    def test_calculated_parameter_from_outside_the_chain(self) -> None:
        """RF-008-29 (plan §5.4.10): un parámetro CALCULADO que leyó un eslabón dice de qué
        operación es la cifra que se adoptó y si hoy está obsoleta, aunque esa operación no
        esté aguas arriba de lo pedido."""
        self.enterContext(registered(MEASURED_DENSITY))
        i18n.install({"Test measured density": "Densidad medida"})
        measure = self.begin("res.step_c", params=["res.production"])
        spec = figures.FigureSpec("res.measured_density", 2.6, "t/m3",
                                  parameter_key="res.density")
        self.write(lambda conn: measure.complete(conn, outputs=[], figures=[spec]))
        self.tick()
        (row,) = self.query("SELECT uid FROM gb_figure WHERE operation_uid = ?", (measure.uid,))
        self.write(lambda conn: self.store.change(conn, "res.density", from_figure=row[0],
                                                  decided_by="Samuel (IMGA)",
                                                  reason="Ensayo de densidad"))
        self.tick()
        use = self.run_figures("res.step_d", params=["res.density"], figures=[(1.0, {})])
        self.change("res.production", 95000.0)  # la medida queda obsoleta; la otra, no
        tree, graph = self.loaded(self.figure(use))
        self.assertEqual(list(tree.operations), [use.uid])
        self.assertNotIn(measure.uid, graph.operations)
        (density,) = tree.operations[use.uid].params
        self.assertEqual((density.kind, density.source_operation_uid, density.source_stale),
                         ("CALCULADO", measure.uid, True))


MEASURED_DENSITY = provenance.FigureDef("res.measured_density", "t/m3", "Test measured density")


class RandomUpstreamTest(unittest.TestCase):
    def test_same_as_the_whole_graph_on_random_graphs(self) -> None:
        """RF-008-29, RF-008-24, RF-008-25 (RNF-008-03): en grafos aleatorios —grupos
        acoplados, operaciones sustituidas, versiones anteriores de un dato consumidas,
        ediciones propias, entradas sustituidas y descartadas, datos que faltan, bloqueados,
        dañados o sustituidos, parámetros que cambian y algoritmos más nuevos que nombran las
        versiones registradas fuera de la cadena—, la procedencia de operaciones (también una
        en curso) y datos al azar, cargando solo lo de aguas arriba, es idéntica a la del grafo
        entero."""
        seeds = random.Random(20261010)
        newer = {**_RANDOM_VERSIONS, "res.t0": "1.2"}
        project = types.SimpleNamespace(name="aleatorio")
        compared = 0
        for case in range(RANDOM_CASES):
            world = RandomProject(random.Random(seeds.getrandbits(64)))
            try:
                world.conn.execute(schema.TABLES["gb_parameter_history"])
                for _ in range(world.rng.randint(6, 16)):
                    world.step()
                versions = newer if case % 2 else _RANDOM_VERSIONS
                world.conn.execute("BEGIN")
                stale_mod.refresh_all(world.conn, now=world.stamp(), versions=versions)
                world.conn.execute("COMMIT")
                items = [str(uid) for (uid,) in world.conn.execute(
                    "SELECT uid FROM gb_operation UNION ALL SELECT uid FROM gb_dataset")]
                items = world.rng.sample(items, min(len(items), RANDOM_ITEMS))
                items.append(_running(world))
                for item in items:
                    tree = lineage_mod.lineage(project, item, conn=world.conn,
                                               versions=versions)
                    reference = whole_graph_lineage(project, item, conn=world.conn,
                                                    versions=versions)
                    same_lineage(self, tree, reference, f"caso {case}, {item}")
                    compared += 1
            finally:
                world.conn.close()
        self.assertEqual(compared, RANDOM_CASES * (RANDOM_ITEMS + 1))


RANDOM_CASES = 30
RANDOM_ITEMS = 5


def _running(world: RandomProject) -> str:
    """Una operación en curso que consume hasta dos datos vivos del mundo aleatorio."""
    uid = world.uid()
    world.insert("gb_operation", operation_row(
        uid=uid, op_type="res.t1", module="res", repeatable=1, status="running",
        started_at=world.stamp(), finished_at=None,
    ))
    live = sorted(world.live)
    for item in world.rng.sample(live, min(len(live), 2)):
        world.insert("gb_operation_io", io_row(operation_uid=uid, direction="in", item_uid=item,
                                               content_sha256=world.content[item],
                                               role="source"))
    return uid


class SearchTest(LineageCase):
    def test_current_figures_and_live_datasets_are_found(self) -> None:
        """RF-008-29, RF-008-31 (plan §5.5, la búsqueda del panel de la procedencia):
        ``search_items`` encuentra, sin escribir nada, las cifras **vigentes** cuya clave, cuyo
        nombre (en español o en inglés, sin distinguir mayúsculas) o cuyo ámbito contienen el
        texto, por orden de registro, y después los datos vivos cuyo nombre lo contiene, por
        nombre; como mucho ``limit``. El texto de una cifra es su nombre, su ámbito y su valor
        con su unidad (``FigureRecord.text``), en el idioma pedido. Lo que ya no es vigente
        (la cifra de una operación sustituida) no sale; un texto vacío no busca nada."""
        _imported, _a, _b, seven = self.figure_chain()
        c = self.run_figures("res.step_c", {"res_c": [1.0]}, reads=["res_b"],
                             figures=[(2.5, BENCH), (1_250_000 / 300_000, OTHER_BENCH)])
        bench, other = self.figure(c, BENCH), self.figure(c, OTHER_BENCH)
        before = self.snapshot()
        found = lineage_mod.search_items(self.project, "MARCAS")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual([(str(item.kind), item.uid, item.text) for item in found], [
            ("figure", seven, "Marcas = 7"),
            ("figure", bench, "Marcas · 125 = 2,5"),
            ("figure", other, "Marcas · 130 = 4,166666666666667"),
        ])
        english = lineage_mod.search_items(self.project, "test marks", language="en")
        self.assertEqual([item.text for item in english][1:],
                         ["Test marks · 125 = 2.5", "Test marks · 130 = 4.166666666666667"])
        self.assertEqual([item.uid for item in lineage_mod.search_items(self.project, "130")],
                         [other])
        self.assertEqual([item.uid for item in lineage_mod.search_items(
            self.project, "res.marks", limit=2)], [seven, bench])
        self.assertEqual([(str(item.kind), item.text)
                          for item in lineage_mod.search_items(self.project, "RES_")],
                         [("dataset", "res_a"), ("dataset", "res_b"), ("dataset", "res_c"),
                          ("dataset", "res_im1")])
        self.assertEqual(lineage_mod.search_items(self.project, "  "), ())
        self.run_figures("res.step_c", {"res_c": [2.0]}, reads=["res_b"],
                         figures=[(2.0, BENCH)], supersedes=c.uid)
        self.assertEqual([item.text for item in lineage_mod.search_items(self.project, "marcas")],
                         ["Marcas = 7", "Marcas · 125 = 2"])
        record = lineage_mod.lineage(self.project, seven).figure
        self.assertEqual((record.text(), record.text(language="en")), ("Marcas = 7",
                                                                       "Test marks = 7"))
        with self.assertRaises(TypeError):
            lineage_mod.search_items(self.project, None)


class ApiTest(unittest.TestCase):
    def test_public_api(self) -> None:
        """RF-008-29, RF-008-31 (plan §5.1): ``core.provenance`` reexporta la procedencia al
        usarla, sin cargarla al importarse; su función ``lineage`` se llama como el módulo,
        que es lo que el paquete tiene con ese nombre."""
        self.assertLessEqual({"figure_marks", "current_figure", "result_state", "LineageTree",
                              "FigureMarks", "ResultState", "ResultStatus", "LineageMatch",
                              "search_items"},
                             set(provenance.LINEAGE_API))
        for name in provenance.LINEAGE_API:
            with self.subTest(name=name):
                self.assertIn(name, provenance.__all__)
                self.assertIn(name, dir(provenance))
                self.assertIs(getattr(provenance, name), getattr(lineage_mod, name))
        self.assertNotIn("lineage", provenance.LINEAGE_API)
        self.assertNotIn("lineage", provenance.__all__)
        self.assertIs(provenance.lineage, lineage_mod)
        self.assertTrue(callable(lineage_mod.lineage))
        tree = ast.parse(Path(provenance.__file__).read_text(encoding="utf-8"))
        imported = {alias.name for node in tree.body if isinstance(node, ast.ImportFrom)
                    for alias in node.names} | {node.module for node in tree.body
                                                if isinstance(node, ast.ImportFrom)}
        self.assertNotIn("lineage", imported)
        self.assertEqual({str(state) for state in lineage_mod.ResultState},
                         {"result", "pending", "not_ingested", "preview", "measurement"})


if __name__ == "__main__":
    unittest.main()

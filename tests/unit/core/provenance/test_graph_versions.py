# SPDX-License-Identifier: GPL-3.0-or-later
"""La cascada, el recálculo y las cifras con versiones (spec 009, T09; RF-009-19, RF-009-20,
RF-009-01, CE-009-05; plan 009 A4, D-23 y D-27).

La obsolescencia de la 008 (``core.provenance.graph``, ``stale``, ``recompute`` y ``lineage``)
con las versiones de la 009, sobre el proyecto de la demostración de versiones
(``tests/support/versions_fixtures.py``):

1. Las operaciones de una versión SUPERADO o DESCARTADO **no entran en la cascada**: sin causas,
   no propagan ni se cuentan en «! n obsoletos» (al cerrarse la versión, la caché las suelta).
2. Las de una versión BORRADOR o VIGENTE se evalúan como siempre, también las registradas en una
   revisión ya congelada (lo «en curso» de su revisión abierta, D-23); la revisión congelada no
   cambia (sus elementos, con el estado que tenían al congelarse).
3. Lo que una operación de versión tomó **congelado** de la versión de la que parte
   (``Use.frozen``, D-27) no queda obsoleto aunque la padre cambie después: solo si su revisión
   está alterada (``dataset_damaged``, «lo congelado de «…» está alterado»).
4. Una fila de versión nueva de un parámetro deja obsoleta la operación de esa versión que leyó
   el del proyecto (``parameter_changed``, sujeto: la fila de la versión).
5. ``current_figure`` sin versión elige entre las cifras de operaciones de proyecto, y con ella
   solo entre las de esa versión; las **vigentes** de una versión (``version_figures``) son las
   de su última revisión congelada (D-9) y las «en curso», las de ahora; una versión que parte de
   otra no tiene ninguna cifra ni ningún resultado de la otra (CE-009-05).
6. Recalcular una operación de versión la registra en la revisión abierta de **su** versión.

Las consultas nuevas usan sus índices (``EXPLAIN QUERY PLAN`` sin recorrer ``gb_operation`` ni
``gb_operation_io``) y lo de antes funciona igual con un proyecto del esquema 2 abierto en solo
lectura. Datos solo sintéticos.
"""

from __future__ import annotations

import contextlib
import re
import sqlite3
import unittest
from collections.abc import Iterator
from typing import Any

from tests.support import schema2_project
from tests.support import versions_demo as vdemo
from tests.support import versions_fixtures as fixtures
from tests.support.core_fixtures import make_session, project_tmp
from tests.support.package import import_geoblender

graph_mod = import_geoblender("core.provenance.graph")
stale = import_geoblender("core.provenance.stale")
recompute = import_geoblender("core.provenance.recompute")
lineage = import_geoblender("core.provenance.lineage")
versions_read = import_geoblender("core.versions.read")
versions_model = import_geoblender("core.versions.model")
versions_store = import_geoblender("core.versions.store")
open_mod = import_geoblender("core.project.open")
userdata_mod = import_geoblender("core.userdata")

Cause = graph_mod.Cause
CauseKind = graph_mod.CauseKind

SOURCE = "Plan de labores (prueba)"
DECIDER = "Samuel (IMGA)"
VOLUME_12 = 3_818_400.0
"""``demo.pit_volume`` con bancos de 12 m sobre ``Limites_v1`` (T08)."""
VOLUME_10 = 3_182_000.0
"""… y con los 10 m por defecto."""
PIT_DATA = (vdemo.PIT_GRID, vdemo.PIT_MESH, vdemo.PIT_BENCHES)
"""Lo que escribe ``demo.pit`` en su versión."""
_ALIAS = re.compile(r"\b(gb_operation(?:_io)?)\s+(?:AS\s+)?(\w+)", re.IGNORECASE)


@contextlib.contextmanager
def undone(conn: sqlite3.Connection) -> Iterator[None]:
    """Lo que se escribe dentro, en un punto de guardado que se deshace al salir (la
    transacción de escritura del proyecto se confirma sin nada)."""
    conn.execute("SAVEPOINT prueba")
    try:
        yield
    finally:
        conn.execute("ROLLBACK TO prueba")
        conn.execute("RELEASE prueba")


class GraphVersionsCase(fixtures.VersionsProjectCase):
    """Ayudas para las pruebas de la cascada con versiones."""

    def bench(self, value: float, *, version: str | None = None,
              reason: str = "Banco de la prueba") -> Any:
        """Cambia ``demo.bench_height`` del proyecto o, con ``version``, el propio de esa versión
        (la primera vez, su fila nueva), un minuto después."""
        self.tick()
        return self.write(lambda conn: self.store.change(
            conn, vdemo.BENCH_HEIGHT, value=value, source=SOURCE, decided_by=DECIDER,
            reason=reason, version=version))

    def cache(self) -> set[tuple[str, str, str, str]]:
        """Las filas de la caché ``gb_stale`` (sin su fecha)."""
        return {tuple(row) for row in self.query(
            "SELECT item_kind, item_uid, cause_kind, subject_uid FROM gb_stale")}

    def cached(self) -> set[str]:
        """Los elementos (operaciones y datos) con alguna fila en la caché."""
        return {uid for _kind, uid, _cause, _subject in self.cache()}

    def causes(self, uid: str) -> set[Any]:
        """Las causas de ``uid`` en la caché."""
        return {Cause(CauseKind(cause), subject)
                for _kind, item, cause, subject in self.cache() if item == uid}

    def data(self, code: str, names: tuple[str, ...] = PIT_DATA) -> set[str]:
        """Los uid de los datos vivos ``names`` de la versión ``code``."""
        return {self.record(name, code).uid for name in names}

    def assertCacheIsWhole(self) -> None:  # noqa: N802 - unittest
        """La caché es la obsolescencia completa: rehacerla entera no cambia ninguna fila (y la
        comprobación de apertura, que mira primero sin cargar el grafo, tampoco)."""
        with self.project.write_transaction() as conn, undone(conn):
            difference = graph_mod.drain(stale.full_difference_steps(
                lambda: contextlib.nullcontext(conn), rows=1))
            update = stale.refresh_all(conn, now=self.now())
        self.assertEqual((update.added, update.removed), (frozenset(), frozenset()))
        self.assertTrue(difference.empty, difference)

    def revision_items(self) -> list[tuple[Any, ...]]:
        return self.query("SELECT * FROM gb_revision_item ORDER BY fid")

    def open_revision(self, version: Any) -> str:
        return self.read(lambda conn: versions_read.open_revision(conn, version.uid)).uid

    def figure(self, handle: Any) -> Any:
        (figure,), _warnings = self.demo.figures(self.project, handle.uid)
        return figure

    def successor(self, op_uid: str) -> tuple[str, str]:
        """La operación que sustituye a ``op_uid`` y su revisión."""
        ((uid, revision),) = self.query(
            "SELECT uid, revision_uid FROM gb_operation WHERE supersedes_uid = ?", (op_uid,))
        return str(uid), str(revision)


class ClosedVersionsTest(GraphVersionsCase):
    def test_closed_versions_leave_the_cascade(self) -> None:
        """RF-009-19, D-23 (plan A4 (1) y (2)): con V01 SUPERADO, V02 VIGENTE (su r1 congelada),
        V03 BORRADOR y V04 DESCARTADO, todas con su hueco y su volumen calculados con la altura
        de banco del proyecto, cambiar esa altura (un parámetro común) deja obsoleto lo de V02
        —aunque se registró en su r1, ya congelada: es lo «en curso» de su r2— y lo de V03, y
        nada de V01 ni de V04: «! n obsoletos» = 3 + 3 datos y 2 volúmenes que solo dejan cifra
        (la vigente de cada versión). V04, obsoleta antes de descartarla (una altura propia),
        sale de la caché al descartarse. Las revisiones congeladas y sus elementos no cambian, y
        la caché es la obsolescencia completa."""
        made = {}
        v3 = self.new_version("tercera", "Tercera")
        v4 = self.new_version("cuarta", "Cuarta")
        for code in ("V01", "V02", "V03", "V04"):
            made[code] = (self.demo.pit(self.project, code),
                          self.demo.pit_volume(self.project, code))
            self.tick()
        self.assertEqual(stale.counts(self.project).obsolete, 0)

        # V04, obsoleta (su propia altura), y después descartada: sale de la caché.
        own = self.bench(12.0, version="V04")
        pit4, volume4 = made["V04"]
        self.assertEqual(self.causes(pit4.uid),
                         {Cause(CauseKind.PARAMETER_CHANGED, own.uid)})
        self.assertEqual(stale.counts(self.project).obsolete, 4)
        self.set_status(v4, "DESCARTADO", "No sigue")
        self.assertEqual(self.cache(), set())
        self.assertEqual(stale.counts(self.project).obsolete, 0)

        r1_v1 = self.freeze(self.v1)
        self.set_status(self.v1, "VIGENTE")
        r1_v2 = self.freeze(self.v2)
        self.set_status(self.v2, "VIGENTE", "Segunda entrega")
        self.assertEqual([(v.code, str(v.status)) for v in self.read(versions_read.versions)],
                         [("V01", "SUPERADO"), ("V02", "VIGENTE"), ("V03", "BORRADOR"),
                          ("V04", "DESCARTADO")])
        items = self.revision_items()
        revisions = self.query("SELECT * FROM gb_revision WHERE uid IN (?, ?) ORDER BY fid",
                               (r1_v1, r1_v2))

        project_row = self.bench(12.0, reason="Banco común de 12 m")
        live = {code: (*made[code], self.data(code)) for code in ("V02", "V03")}
        expected = {uid for pit, volume, data in live.values()
                    for uid in (pit.uid, volume.uid, *data)}
        self.assertEqual(self.cached(), expected)
        for pit, volume, data in live.values():
            for uid in (pit.uid, *data):
                self.assertEqual(self.causes(uid),
                                 {Cause(CauseKind.PARAMETER_CHANGED, project_row.uid)})
        counts = stale.counts(self.project)
        self.assertEqual((counts.stale, counts.figures, counts.review, counts.obsolete),
                         (6, 2, 0, 8))
        report = stale.stale_items(self.project)
        self.assertEqual({(item.item_kind, item.uid) for item in report.items},
                         {*(("dataset", uid) for _p, _v, data in live.values() for uid in data),
                          ("operation", live["V02"][1].uid), ("operation", live["V03"][1].uid)})
        self.assertEqual(self.revision_items(), items)
        self.assertEqual(self.query("SELECT * FROM gb_revision WHERE uid IN (?, ?) ORDER BY fid",
                                    (r1_v1, r1_v2)), revisions)

        with self.project.read() as conn:
            graph = graph_mod.load_graph(conn)
        state = graph_mod.deduce(graph)
        for code, closed in (("V01", True), ("V02", False), ("V03", False), ("V04", True)):
            pit, volume = made[code]
            with self.subTest(version=code):
                self.assertEqual(graph.closed(pit.uid), closed)
                self.assertEqual(graph.version_of(pit.uid), self.version(code).uid)
                self.assertEqual(pit.uid in state.causes, not closed)
                self.assertEqual(volume.uid in state.figure_only, not closed)
        self.assertFalse(graph.closed(self.chain["area"]))
        self.assertEqual(graph.version_of(self.chain["area"]), "")
        self.assertEqual(graph.revisions[made["V02"][0].revision_uid].state, "frozen")
        self.assertEqual(graph_mod.direct_causes(graph, graph.operations[made["V01"][0].uid],
                                                 {}), set())
        self.assertCacheIsWhole()


class InProgressTest(GraphVersionsCase):
    def test_recompute_in_the_open_revision_of_its_version(self) -> None:
        """RF-009-19, RF-009-20, D-23 (plan A4 (2) y (6)): con V01 congelada en r1 (su hueco y
        su volumen se registraron en r1) y V02 sin congelar, cambiar la altura común deja
        obsoleto lo de las dos («en curso» en V01.r2), y «Recalcular lo obsoleto» registra cada
        operación nueva en la revisión abierta de **su** versión (V01.r2 y V02.r1), con la
        versión en su petición; después nada está obsoleto, las de r1 quedan sustituidas como
        historia y r1 y sus elementos no cambian."""
        pit1 = self.demo.pit(self.project, "V01")
        volume1 = self.demo.pit_volume(self.project, "V01")
        r1 = self.freeze(self.v1)
        r2 = self.open_revision(self.v1)
        pit2 = self.demo.pit(self.project, "V02")
        volume2 = self.demo.pit_volume(self.project, "V02")
        v2_r1 = self.open_revision(self.v2)
        items = self.revision_items()
        self.bench(12.0)
        self.assertEqual(stale.counts(self.project).obsolete, 8)
        self.assertLessEqual({pit1.uid, volume1.uid, pit2.uid, volume2.uid}, self.cached())

        with self.project.read() as conn:
            graph = graph_mod.load_graph(conn)
            plan = recompute.plan_recompute(graph)
            requests = {uid: recompute._request(conn, self.project, graph, uid, None)[0]
                        for uid in plan.operations}
        self.assertEqual(set(plan.operations), {pit1.uid, volume1.uid, pit2.uid, volume2.uid})
        self.assertEqual({uid: request.version for uid, request in requests.items()},
                         {pit1.uid: self.v1.uid, volume1.uid: self.v1.uid,
                          pit2.uid: self.v2.uid, volume2.uid: self.v2.uid})
        self.assertIsNone(recompute.RecomputeRequest(
            self.project, "x", "demo.area", {}, (), ()).arguments()["version"])

        outcome = list(recompute.recompute_steps(self.project))[-1].result
        self.assertEqual([str(result.status) for result in outcome.results], ["done"] * 4)
        for old, revision in ((pit1, r2), (volume1, r2), (pit2, v2_r1), (volume2, v2_r1)):
            with self.subTest(op_type=old.op_type, revision=revision):
                self.assertEqual(self.successor(old.uid)[1], revision)
        self.assertEqual(stale.counts(self.project).obsolete, 0)
        self.assertEqual(self.figure_value(volume1), VOLUME_12)
        self.assertEqual(self.revision_items(), items)
        self.assertEqual(self.query("SELECT state FROM gb_revision WHERE uid = ?", (r1,)),
                         [("frozen",)])
        self.assertEqual(self.query("SELECT revision_uid FROM gb_operation WHERE uid = ?",
                                    (pit1.uid,)), [(r1,)])
        self.assertCacheIsWhole()

    def figure_value(self, old: Any) -> float:
        """El valor de la cifra de la operación que sustituye a ``old``."""
        uid, _revision = self.successor(old.uid)
        ((value,),) = self.query("SELECT value FROM gb_figure WHERE operation_uid = ?", (uid,))
        return float(value)


class FrozenParentTest(GraphVersionsCase):
    def test_frozen_input_is_stale_only_when_its_revision_is_altered(self) -> None:
        """RF-009-01, RF-009-19, D-27 (plan A4 (3)): V03 parte de V01.r1 y diseña con la tabla
        de bancos congelada en r1 (``Use.frozen``). Que V01 cambie esa tabla en r2 y que su hueco
        quede obsoleto por la altura común no deja obsoleto el diseño de V03 (lo congelado no
        cambia, y no es aguas arriba suyo en la cascada); cuando r1 está alterada, sí:
        ``dataset_damaged`` sobre la tabla, «lo congelado de «demo_pit_benches» está alterado»,
        en el diseño y en su dato; y cuando vuelve a coincidir, deja de estarlo. La caché es
        siempre la obsolescencia completa."""
        self.demo.pit(self.project, "V01")
        benches = self.record(vdemo.PIT_BENCHES, "V01")
        r1 = self.freeze(self.v1, [(benches, "produced")])
        self.new_version("desde_v01", "Desde V01", parent=self.v1.uid)
        design = self.demo.design_from_parent(self.project, "V03", frozen=r1)
        designed = self.record(vdemo.DESIGN_TABLE, "V03")
        with self.project.read() as conn:
            graph = graph_mod.load_graph(conn)
        node = graph.operations[design.uid]
        self.assertTrue(graph.frozen_use(node, benches.uid))
        self.assertEqual(graph.upstream(design.uid), ())
        self.assertEqual(graph.revisions[r1].label, "V01.r1")

        changed = self.demo.pit(self.project, "V01", benches=2)
        self.assertNotEqual(self.record(vdemo.PIT_BENCHES, "V01").content_sha256,
                            benches.content_sha256)
        self.bench(12.0)
        self.assertIn(changed.uid, self.cached())
        self.assertNotIn(design.uid, self.cached())
        self.assertNotIn(designed.uid, self.cached())
        self.assertCacheIsWhole()

        def alter(when: str | None) -> None:
            def work(conn: sqlite3.Connection) -> None:
                conn.execute("UPDATE gb_revision SET altered_at = ?, altered_detail = ? "
                             "WHERE uid = ?",
                             (when, None if when is None else '{"files": ["V01.r1.gpkg"]}', r1))
                stale.refresh_region(conn, now=self.now(), revisions=[r1])
            self.tick()
            self.write(work)

        alter(self.now())
        damaged = {Cause(CauseKind.DATASET_DAMAGED, benches.uid)}
        self.assertEqual(self.causes(design.uid), damaged)
        self.assertEqual(self.causes(designed.uid), damaged)
        texts = {item.uid: item.text for item in stale.stale_items(self.project).items}
        self.assertEqual(texts[designed.uid],
                         "Obsoleto: lo congelado de «demo_pit_benches» está alterado")
        self.assertEqual(stale.stale_items(self.project, language="en").items[0].text[:6],
                         "Stale:")
        self.assertCacheIsWhole()

        alter(None)
        self.assertNotIn(design.uid, self.cached())
        self.assertCacheIsWhole()


class VersionParameterTest(GraphVersionsCase):
    def test_new_version_row_makes_its_operations_stale(self) -> None:
        """RF-009-24, RF-009-29, D-19 (plan A4 (4)): V01 y V02 calcularon su hueco con la altura
        del proyecto; crear la fila propia de V01 (``create``) deja obsoleto el hueco de V01 (y
        sus datos) con la causa «cambió» sobre esa fila, y nada de V02; la primera fila de V02
        (``change``) deja obsoleto el de V02. Recalcular lee la fila de cada versión y deja todo
        al día. La caché es siempre la obsolescencia completa (la comprobación de apertura lo ve
        sin cargar el grafo)."""
        pit1 = self.demo.pit(self.project, "V01")
        pit2 = self.demo.pit(self.project, "V02")
        self.tick()
        own = self.write(lambda conn: self.store.create(
            conn, vdemo.BENCH_HEIGHT, 12.0, kind="ADOPTADO", source=SOURCE,
            source_kind="document", decided_by=DECIDER, reason="Banco de V01", version="V01"))
        changed = {Cause(CauseKind.PARAMETER_CHANGED, own.uid)}
        for uid in (pit1.uid, *self.data("V01")):
            self.assertEqual(self.causes(uid), changed)
        self.assertEqual(self.cached(), {pit1.uid, *self.data("V01")})
        with self.project.read() as conn:
            self.assertEqual(stale.item_text(conn, "operation", pit1.uid),
                             "Obsoleto: cambió Altura de banco (demostración)")
        self.assertCacheIsWhole()

        second = self.bench(11.0, version="V02", reason="Banco de V02")
        self.assertEqual(self.causes(pit2.uid),
                         {Cause(CauseKind.PARAMETER_CHANGED, second.uid)})
        self.assertCacheIsWhole()

        list(recompute.recompute_steps(self.project))
        self.assertEqual(stale.counts(self.project).obsolete, 0)
        for old, row in ((pit1, own), (pit2, second)):
            uid, _revision = self.successor(old.uid)
            self.assertEqual(self.query("SELECT parameter_uid, scope FROM gb_operation_param "
                                        "WHERE operation_uid = ?", (uid,)),
                             [(row.uid, "version")])
            self.assertNotIn(uid, self.cached())
        self.assertCacheIsWhole()


class FiguresTest(GraphVersionsCase):
    def test_figures_by_version_and_error_32(self) -> None:
        """RF-009-20, D-9, RF-009-01, CE-009-05 (plan A4 (5)): ``current_figure`` sin versión
        solo da cifras de operaciones de proyecto, y con una versión (uid o código) solo las
        suyas; cada versión tiene su cifra vigente (las marcas también); las vigentes de V01,
        VIGENTE con r2 abierta, son las de r1 (D-9) y las «en curso», las recalculadas en r2. V03,
        que parte de V01.r1, no tiene ninguna cifra ni ningún resultado de una operación de V01
        (error 32), tampoco después de diseñar con lo congelado."""
        area = lineage.current_figure(self.project, "demo.boundary_area")
        self.assertIsNotNone(area)
        self.assertIsNone(lineage.current_figure(self.project, "demo.boundary_area",
                                                 version="V01"))
        self.write(lambda conn: self.store.create(
            conn, vdemo.BENCH_HEIGHT, 12.0, kind="ADOPTADO", source=SOURCE,
            source_kind="document", decided_by=DECIDER, reason="Banco de V01", version="V01"))
        self.demo.pit(self.project, "V01")
        first = self.figure(self.demo.pit_volume(self.project, "V01"))
        self.demo.pit(self.project, "V02")
        second = self.figure(self.demo.pit_volume(self.project, "V02"))
        self.assertEqual((first.value, second.value), (VOLUME_12, VOLUME_10))
        key = vdemo.PIT_VOLUME_FIGURE
        self.assertIsNone(lineage.current_figure(self.project, key))
        self.assertEqual(lineage.current_figure(self.project, key, version="V01").uid, first.uid)
        self.assertEqual(lineage.current_figure(self.project, key, version=self.v2.uid).uid,
                         second.uid)
        with self.assertRaises(versions_model.VersionError) as caught:
            lineage.current_figure(self.project, key, version="V99")
        self.assertEqual(caught.exception.code, "core.version_unknown")
        marks = lineage.figure_marks(self.project, [first.uid, second.uid, area.uid])
        self.assertEqual([marks[uid].current for uid in (first.uid, second.uid, area.uid)],
                         [True, True, True])
        in_project = lineage.current_figures(self.project)
        self.assertIn(area.uid, [record.uid for record in in_project])
        self.assertNotIn(key, {record.key for record in in_project})
        self.assertEqual([record.uid for record in lineage.current_figures(
            self.project, version="V01")], [first.uid])

        r1 = self.freeze(self.v1)  # con su cifra vigente
        self.assertEqual(self.query("SELECT item_uid, part FROM gb_revision_item WHERE "
                                    "revision_uid = ? AND item_kind = 'figure'", (r1,)),
                         [(first.uid, "produced")])
        self.set_status(self.v1, "VIGENTE")

        # CE-009-05: V03 parte de V01.r1 y no tiene nada de V01.
        v3 = self.new_version("desde_v01", "Desde V01", parent="V01")
        self.assertEqual(v3.parent_revision_uid, r1)

        def nothing_of_v01() -> None:
            with self.project.read() as conn:
                self.assertEqual(versions_read.version_figures(conn, v3.uid), ())
                self.assertEqual(versions_read.version_figures(conn, v3.uid, frozen=False), ())
            self.assertIsNone(lineage.current_figure(self.project, key, version="V03"))
            self.assertEqual(lineage.current_figures(self.project, version="V03"), ())
            self.assertEqual(self.query(
                "SELECT d.name FROM gb_dataset AS d JOIN gb_operation AS op "
                "ON op.uid = d.operation_uid WHERE d.version_uid = ? AND op.revision_uid NOT IN "
                "(SELECT uid FROM gb_revision WHERE version_uid = ?)", (v3.uid, v3.uid)), [])
            self.assertEqual(self.query(
                "SELECT f.uid FROM gb_figure AS f JOIN gb_operation AS op "
                "ON op.uid = f.operation_uid JOIN gb_revision AS r ON r.uid = op.revision_uid "
                "WHERE r.version_uid = ?", (v3.uid,)), [])

        nothing_of_v01()
        self.assertEqual(self.query("SELECT count(*) FROM gb_dataset WHERE version_uid = ? "
                                    "AND version_uid <> ''", (v3.uid,)), [(0,)])
        design = self.demo.design_from_parent(self.project, "V03", frozen=r1)
        nothing_of_v01()
        self.assertEqual(self.query("SELECT name FROM gb_dataset WHERE version_uid = ? "
                                    "AND version_uid <> ''", (v3.uid,)),
                         [(vdemo.DESIGN_TABLE,)])

        # V01 (VIGENTE, r2 abierta) vuelve a 10 m y se recalcula en r2: «en curso».
        self.bench(10.0, version="V01", reason="Vuelta a 10 m")
        list(recompute.recompute_steps(self.project))
        again = lineage.current_figure(self.project, key, version="V01")
        self.assertEqual(again.value, VOLUME_10)
        self.assertEqual(stale.counts(self.project).obsolete, 0)
        self.assertNotIn(design.uid, self.cached())
        with self.project.read() as conn:
            self.assertEqual([f.uid for f in versions_read.version_figures(conn, self.v1.uid)],
                             [first.uid])
            self.assertEqual([f.uid for f in versions_read.version_figures(
                conn, self.v1.uid, frozen=False)], [again.uid])
            self.assertEqual(versions_read.version_figures(conn, self.v2.uid), ())
            self.assertEqual([f.uid for f in versions_read.version_figures(
                conn, "V02", frozen=False)], [second.uid])
            self.assertEqual(versions_read.version_figures(conn, "V99"), ())
            graph = graph_mod.load_graph(conn)
        state = graph_mod.deduce(graph)
        self.assertNotIn((key, ""), state.current_figures)
        self.assertEqual(state.current_version_figures[(self.v1.uid, key, "")], again.uid)
        self.assertEqual(state.current_version_figures[(self.v2.uid, key, "")], second.uid)
        self.assertIn(area.uid, state.current_figure_uids)
        nothing_of_v01()
        self.assertCacheIsWhole()


class QueriesTest(GraphVersionsCase):
    def test_new_queries_use_their_indexes(self) -> None:
        """Plan §2.1 (trampa §6), A4: las consultas nuevas de la cascada, los recuentos, las
        cifras y los estados (con una fila de versión nueva, una revisión alterada, lo congelado
        de la padre y una versión que se descarta) no recorren ``gb_operation`` ni
        ``gb_operation_io`` enteras (``EXPLAIN QUERY PLAN``)."""
        self.demo.pit(self.project, "V01")
        self.demo.pit_volume(self.project, "V01")
        benches = self.record(vdemo.PIT_BENCHES, "V01")
        r1 = self.freeze(self.v1, [(benches, "produced")])
        self.new_version("desde_v01", "Desde V01", parent=self.v1.uid)
        self.demo.design_from_parent(self.project, "V03", frozen=r1)
        self.demo.pit(self.project, "V02")
        statements: list[str] = []
        with self.project.write_transaction() as conn, undone(conn):
            conn.set_trace_callback(statements.append)
            try:
                self.store.create(conn, vdemo.BENCH_HEIGHT, 12.0, kind="ADOPTADO",
                                  source=SOURCE, source_kind="document", decided_by=DECIDER,
                                  reason="Banco de V02", version="V02")
                conn.execute("UPDATE gb_revision SET altered_at = ?, altered_detail = '{}' "
                             "WHERE uid = ?", (self.now(), r1))
                stale.refresh_region(conn, now=self.now(), revisions=[r1])
                stale.counts(self.project, conn=conn)
                stale.stale_items(self.project, conn=conn)
                lineage.current_figure(self.project, vdemo.PIT_VOLUME_FIGURE, version="V01",
                                       conn=conn)
                lineage.current_figure(self.project, "demo.boundary_area", conn=conn)
                lineage.current_figures(self.project, version="V01", conn=conn)
                versions_read.version_figures(conn, self.v1.uid)
                versions_read.version_figures(conn, self.v1.uid, frozen=False)
                graph_mod.drain(stale.full_difference_steps(
                    lambda: contextlib.nullcontext(conn), rows=None))
                versions_store.set_status(conn, self.project, self.v2.uid, "DESCARTADO",
                                          reason="No sigue")
            finally:
                conn.set_trace_callback(None)
            new = [sql for sql in statements if sql.lstrip().upper().startswith(("SELECT",
                                                                                  "WITH"))
                   and re.search(r"revision|version_uid|scope_uid|scope = 'version'", sql)]
            self.assertGreaterEqual(len(new), 8, statements)
            # … y las que no han hecho falta aquí (la comprobación de apertura paró en la
            # revisión alterada; ninguna operación con cifra obsoleta).
            new += [graph_mod._OWN_ROW_CAUSE,
                    stale._FIGURES_OF_KEY.format(version=stale._OPERATION_VERSION).replace(
                        "f.key = ? AND f.scope_key = ?", "f.key = 'k' AND f.scope_key = ''"),
                    lineage._OPERATION_VERSIONS.format(marks="'x'")]
            for sql in new:
                tables = {alias for _table, alias in _ALIAS.findall(sql)}
                tables |= {table for table, _alias in _ALIAS.findall(sql)}
                with self.subTest(sql=sql):
                    plan = [row[3] for row in conn.execute(f"EXPLAIN QUERY PLAN {sql}")]
                    self.assertFalse([step for step in plan if step.startswith("SCAN ")
                                      and step.split()[1] in tables], plan)


class Schema2Test(unittest.TestCase):
    def test_schema_2_read_only(self) -> None:
        """RF-009-23, RF-008-24 (plan §5.2.3): un proyecto del esquema 2 abierto en solo lectura
        (sin versiones) se lee como antes: el grafo, la obsolescencia, los recuentos, la lista,
        las cifras vigentes y sus marcas y la comprobación de apertura, sin versiones; pedir la
        cifra de una versión dice que no hay ninguna."""
        folder = self.enterContext(project_tmp("gb-gv2-"))
        root = schema2_project.extract(folder)
        project = open_mod.open_project(root, make_session(),
                                        userdata_mod.UserData(folder / "u"),
                                        want_write=False).project
        self.addCleanup(project.close)
        self.assertFalse(project.writable)
        with project.read() as conn:
            self.assertFalse(graph_mod.versioned(conn))
            graph = graph_mod.load_graph(conn)
            self.assertEqual(graph.revisions, {})
            self.assertTrue(graph.operations)
            self.assertFalse(any(graph.closed(uid) for uid in graph.operations))
            state = graph_mod.deduce(graph)
            difference = graph_mod.drain(stale.full_difference_steps(
                lambda: contextlib.nullcontext(conn), rows=None))
        self.assertTrue(difference.empty)
        self.assertEqual(set(state.causes), set())
        self.assertEqual(stale.counts(project).obsolete, 0)
        self.assertEqual(stale.stale_items(project).items, ())
        area = lineage.current_figure(project, "demo.boundary_area")
        self.assertIsNotNone(area)
        self.assertTrue(lineage.figure_marks(project, [area.uid])[area.uid].current)
        self.assertIn(area.uid, {record.uid for record in lineage.current_figures(project)})
        with self.assertRaises(versions_model.VersionError):
            lineage.current_figure(project, "demo.boundary_area", version="V01")


if __name__ == "__main__":
    unittest.main()

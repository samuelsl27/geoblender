# SPDX-License-Identifier: GPL-3.0-or-later
"""Ficha de un dato y cifras de varios datos (spec 010, T05; RF-010-06, RF-010-08; plan 010
§5.3.1, A6, A8, D-16 y D-17).

``core.views.card`` lee, en una instantánea y sin escribir nada, la ficha de «Elemento activo»
de un dato (:func:`item_card`): su registro, si está obsoleto, su versión («—» hasta la 009), la
operación que escribió su contenido, sus entradas con el hash que consumió y su papel, los
derivados de las operaciones vivas que lo consumen, la marca de obsoleto de cada uno y las
cifras de su operación con su unidad y su tipo; y las cifras de varios datos con sus marcas o sin
ellas (:func:`dataset_figures`, «Cifras de la selección» y lo que se anota en cada objeto). Cada
consulta nueva, con su ``EXPLAIN QUERY PLAN``, no recorre ``gb_operation_io`` ni ``gb_stale``
enteras (``docs/trampas.md`` §6), tampoco con las estadísticas de ``ANALYZE``.

Sobre un proyecto sintético con la cadena entera del módulo de demostración de la 008
(``tests/support/provenance_demo.py``): el límite importado de ``Limites_v1`` y su área
(``demo.boundary_area``), los bancos y las marcas, los años por banco (``demo.bench_years``, uno
por banco), los acopios y el balance. Cada lectura comprueba que el contador de cambios de la
cabecera de ``project.gpkg`` no se mueve.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from contextlib import closing
from typing import Any

from tests.support import provenance_data as data
from tests.support import provenance_demo as demo_support
from tests.support.demo_project import SESSION, DemoProjectTestCase
from tests.support.package import import_geoblender
from tests.unit.core.views.test_state import Traced

card = import_geoblender("core.views.card")
datasets = import_geoblender("core.datasets")
params = import_geoblender("core.params")
importer = import_geoblender("core.provenance.importer")
lineage = import_geoblender("core.provenance.lineage")
header = import_geoblender("core.gpkg.header")
ids = import_geoblender("core.ids")

Link = card.Link
Mark = lineage.Mark
REASON = "Plan de labores revisado"
WATCHED = re.compile(r"\b(gb_operation_io|gb_stale)\b(?:\s+AS\s+(\w+))?")
"""Las tablas que ninguna consulta nueva puede recorrer entera, con su alias si lo tienen."""


class CardTest(DemoProjectTestCase):
    """El proyecto de la demostración con la cadena entera y lo que dicen la ficha y las cifras
    de cada dato."""

    tmp_prefix = "gb-card-"

    def setUp(self) -> None:
        super().setUp()
        self.steps = self.chain()

    # --- Ayudas -----------------------------------------------------------------------------

    def counter(self) -> int:
        """El contador de cambios de la cabecera de ``project.gpkg``."""
        return int(header.read_header(self.project.database_path).change_counter)

    def write(self, work: Callable[[sqlite3.Connection], Any]) -> Any:
        """``work`` en una transacción de escritura del proyecto y un minuto más en el reloj."""
        with self.project.write_transaction() as conn:
            result = work(conn)
        self.clock.advance(minutes=1)
        return result

    def record(self, ref: str) -> Any:
        """El registro de ``gb_dataset`` del dato ``ref`` (uid o nombre vivo)."""
        found = self.read(lambda conn: datasets.get(conn, ref))
        self.assertIsNotNone(found, ref)
        return found

    def set_status(self, ref: str, status: str) -> None:
        uid = self.record(ref).uid
        self.write(lambda conn: datasets.set_status(conn, self.project, uid, status))

    def change_production(self, value: float) -> None:
        """La producción ``demo.production`` pasa a ``value`` t/año, ADOPTADO."""
        store = params.ParameterStore(self.project)
        self.write(lambda conn: store.change(
            conn, demo_support.PRODUCTION, value=value, kind="ADOPTADO",
            source="Plan de labores 2027", source_kind="document", decided_by="la propiedad",
            reason=REASON))

    def card_of(self, ref: str, **kw: Any) -> Any:
        """``item_card`` del dato ``ref`` (uid o nombre vivo), comprobando que no escribe."""
        uid = self.record(ref).uid
        before = self.counter()
        found = card.item_card(kw.pop("project", self.project), uid, **kw)
        self.assertEqual(self.counter(), before)
        return found

    def figures(self, *uids: str, project: Any = None, **kw: Any) -> Any:
        """``dataset_figures`` de ``uids``, comprobando que no escribe."""
        before = self.counter()
        found = card.dataset_figures(self.project if project is None else project, list(uids),
                                     **kw)
        self.assertEqual(self.counter(), before)
        return found

    def link(self, ref: str, role: str, *, stale: bool = False,
             content: str | None = None) -> Any:
        """El enlace al dato ``ref`` como está hoy (con ``content``, el hash consumido)."""
        record = self.record(ref)
        return Link("dataset", record.uid, record.name, str(record.status),
                    record.content_sha256 if content is None else content, role, stale)

    def stale_data(self) -> set[str]:
        """Los datos vivos obsoletos según la caché del proyecto."""
        return {uid for kind, uid in self.obsolete() if kind == "dataset"}

    # --- Pruebas ----------------------------------------------------------------------------

    def test_card_of_computed_data(self) -> None:
        """RF-010-06 (plan 010 A6 y D-16): la ficha de los años por banco dice su registro, que
        no está obsoleto, su versión «—» (``None``), la operación que escribió su contenido
        (tipo, versión de su algoritmo, cuándo terminó, versión de Geoblender, sus bibliotecas
        y dónde se ejecutó), su entrada (los bancos, con el hash que consumió y su papel), su
        derivado directo (los candidatos de acopio que escribió la detección, con su hash y
        su papel; no los acopios, que salen de los candidatos) y las cifras de su operación,
        una por banco, con su unidad y su tipo, en su orden. La de los acopios, su volumen
        esponjado en m³."""
        found = self.card_of("demo_bench_years")
        self.assertEqual(found.record, self.record("demo_bench_years"))
        self.assertEqual((found.stale, found.version), (False, None))
        operation = found.operation
        self.assertEqual(
            (operation.uid, operation.op_type, operation.op_version,
             operation.geoblender_version, dict(operation.software), operation.executor),
            (self.steps.years.uid, demo_support.BENCH_YEARS, "1.0", SESSION.geoblender_version,
             {}, "blender"))
        self.assertIsInstance(operation.finished_at, str)
        self.assertEqual(found.upstream, (self.link("demo_benches", "benches"),))
        self.assertEqual(found.downstream,
                         (self.link("demo_stockpile_candidates", "candidates"),))
        self.assertEqual(list(found.figures), self.figures_of(self.steps.years.uid))
        self.assertEqual(
            [(figure.key, dict(figure.scope), figure.unit, str(figure.kind))
             for figure in found.figures],
            [(demo_support.YEARS_FIGURE, {"bench": bench}, "yr", "CALCULADO")
             for bench in ("B-1", "B-2", "B-3")])
        for figure, years in zip(found.figures, (2.5, 1.96, 3.0), strict=True):
            self.assertClose(figure.value, years)

        stockpiles = self.card_of("demo_stockpiles")
        self.assertEqual(stockpiles.operation.uid, self.steps.filter.uid)
        self.assertEqual(stockpiles.upstream,
                         (self.link("demo_stockpile_candidates", "candidates"),))
        self.assertEqual(stockpiles.downstream, ())
        (volume,) = stockpiles.figures
        self.assertEqual((volume.key, volume.unit, str(volume.kind)),
                         (demo_support.STOCKPILE_VOLUME, "m3", "CALCULADO"))
        self.assertClose(volume.value, (12_000.0 + 6_500.0) * 1.15)

    def test_card_of_imported_data_without_figures(self) -> None:
        """RF-010-06, RF-010-08 (plan 010 A6, A8 y D-16): lo importado del límite tiene como
        entrada la que registró su importación (con su hash y su estado de hoy) y ningún
        derivado (el área lo consume y no escribe datos); es un dato sin cifras: su importación
        no registra ninguna, y el área del límite (``demo.boundary_area``) es una cifra de la
        operación del área, no de lo importado. Los bancos (digitalizados, sin entradas) tienen
        como derivado los años por banco. Actualizada la entrada, lo importado de la anterior
        queda sustituido, sin marca de obsoleto, con su entrada «superseded», y lo de la nueva,
        con la suya."""
        boundary = self.steps.boundary
        found = self.card_of(boundary.dataset.uid)
        self.assertEqual((found.record.uid, found.stale, found.version),
                         (boundary.dataset.uid, False, None))
        self.assertEqual((found.operation.uid, found.operation.op_type),
                         (boundary.operation_uid, "core.import_layer"))
        imported = Link("input", boundary.input.uid, boundary.input.name, "current",
                        boundary.input.content_sha256, importer.IMPORTED_ROLE, False)
        self.assertEqual(found.upstream, (imported,))
        self.assertEqual((found.downstream, found.figures), ((), ()))
        (area,) = self.figures_of(self.steps.area.uid)
        self.assertEqual((area.key, area.unit), (demo_support.BOUNDARY_AREA, "ha"))
        self.assertClose(area.value, 12.0)

        benches = self.card_of("demo_benches")
        self.assertEqual(benches.operation.uid, self.steps.digitize.uid)
        self.assertEqual((benches.upstream, benches.figures), ((), ()))
        self.assertEqual(benches.downstream, (self.link("demo_bench_years", "bench_years"),))

        self.deliver(data.BOUNDARY_V2)
        update = self.run_step(lambda: importer.reimport_input(self.project, "Limites_v1",
                                                               REASON))
        old = self.card_of(boundary.dataset.uid)
        self.assertEqual((str(old.record.status), old.stale), ("superseded", False))
        self.assertEqual(old.upstream, (Link("input", boundary.input.uid, boundary.input.name,
                                             "superseded", boundary.input.content_sha256,
                                             importer.IMPORTED_ROLE, False),))
        new = self.card_of(update.dataset.uid)
        self.assertEqual(new.operation.uid, update.operation_uid)
        self.assertEqual(new.upstream, (Link("input", update.input.uid, update.input.name,
                                             "current", update.input.content_sha256,
                                             importer.IMPORTED_ROLE, False),))

    def test_stale_marks_and_live_derivatives(self) -> None:
        """RF-010-06 (plan 010 A6 y D-16): cambiada la producción, los años por banco quedan
        obsoletos (la ficha lo dice, como la caché), y también lo que sale de ellos; sus bancos,
        no. Recalculado, cuentan las operaciones vivas: los bancos tienen un solo derivado, al
        día, y los años, la operación nueva con sus cifras (no las de la sustituida). Descartados
        los candidatos de acopio, los años ya no tienen derivados vivos."""
        self.change_production(400_000.0)
        stale = self.stale_data()
        years = self.record("demo_bench_years")
        candidates = self.record("demo_stockpile_candidates")
        self.assertIn(years.uid, stale)
        found = self.card_of(years.uid)
        self.assertTrue(found.stale)
        self.assertEqual(found.upstream, (self.link("demo_benches", "benches"),))
        self.assertEqual(found.downstream, (self.link("demo_stockpile_candidates", "candidates",
                                                      stale=candidates.uid in stale),))
        benches = self.card_of("demo_benches")
        self.assertFalse(benches.stale)
        self.assertEqual(benches.downstream,
                         (self.link("demo_bench_years", "bench_years", stale=True),))

        old_figures = {figure.uid for figure in found.figures}
        self.recompute_all()
        self.assertEqual(self.stale_data(), set())
        self.assertEqual(self.card_of("demo_benches").downstream,
                         (self.link("demo_bench_years", "bench_years"),))
        found = self.card_of(years.uid)
        self.assertFalse(found.stale)
        self.assertNotEqual(found.operation.uid, self.steps.years.uid)
        self.assertEqual(found.operation.uid, self.record(years.uid).operation_uid)
        self.assertFalse(old_figures & {figure.uid for figure in found.figures})
        for figure, years_now in zip(found.figures, (3.125, 2.45, 3.75), strict=True):
            self.assertClose(figure.value, years_now)
        self.assertEqual(found.downstream,
                         (self.link("demo_stockpile_candidates", "candidates"),))

        self.set_status("demo_stockpile_candidates", "discarded")
        self.assertEqual(self.card_of(years.uid).downstream, ())

    def test_dataset_figures(self) -> None:
        """RF-010-08 (plan 010 A8 y D-17): las cifras de varios datos son las de la operación que
        escribió el contenido de cada uno, en el orden pedido, sin repetir y sin lo que el
        proyecto no tiene; un dato sin cifras no tiene ninguna. Sin marcas, ninguna; con ellas,
        las de ``figure_marks`` de la 008: los años dependen de una hipótesis y de un valor sin
        confirmar (la producción, HIPÓTESIS y sin confirmar por defecto) y, con la producción
        ya ADOPTADA y cambiada, solo están obsoletos. Sin datos, nada."""
        years = self.record("demo_bench_years")
        benches = self.record("demo_benches")
        stockpiles = self.record("demo_stockpiles")
        found = self.figures(years.uid, benches.uid, years.uid, ids.new_uid(), stockpiles.uid,
                             marks=False)
        self.assertEqual([item.record for item in found], [years, benches, stockpiles])
        self.assertEqual(list(found[0].figures), self.figures_of(self.steps.years.uid))
        self.assertEqual(found[1].figures, ())
        self.assertEqual([(figure.key, figure.unit) for figure in found[2].figures],
                         [(demo_support.STOCKPILE_VOLUME, "m3")])
        self.assertEqual([dict(item.marks) for item in found], [{}, {}, {}])

        marked = self.figures(years.uid, benches.uid, stockpiles.uid)
        self.assertEqual([item.figures for item in marked], [item.figures for item in found])
        uids = [figure.uid for item in marked for figure in item.figures]
        self.assertEqual({uid: marks for item in marked for uid, marks in item.marks.items()},
                         lineage.figure_marks(self.project, uids))
        self.assertEqual([list(item.marks) for item in marked],
                         [[figure.uid for figure in item.figures] for item in marked])
        self.assertEqual({marks.marks for marks in marked[0].marks.values()},
                         {(Mark.HYPOTHESIS, Mark.UNCONFIRMED)})

        self.change_production(400_000.0)
        (again,) = self.figures(years.uid)
        self.assertEqual({marks.marks for marks in again.marks.values()}, {(Mark.STALE,)})
        self.assertEqual(self.figures(), ())

    def test_one_snapshot_and_query_plans(self) -> None:
        """RF-010-06, RF-010-08 (plan 010 §2.1 y A6; ``docs/trampas.md`` §6): la ficha y las
        cifras se leen cada una en una instantánea (``BEGIN`` … ``ROLLBACK``, solo lecturas) o
        en la transacción de quien llama, también las marcas; y ninguna de sus consultas recorre
        ``gb_operation_io`` ni ``gb_stale`` enteras, ni sin estadísticas (como los proyectos)
        ni con las de ``ANALYZE`` (en una copia)."""
        years = self.record("demo_bench_years")
        traced = Traced(self.project)
        self.card_of(years.uid, project=traced)
        self.figures(years.uid, self.record("demo_benches").uid,
                     self.record("demo_stockpiles").uid, project=traced, marks=False)
        self.assertEqual(traced.opened, 2)
        self.assertEqual([sql for sql in traced.sql if not sql.startswith("SELECT ")],
                         ["BEGIN", "ROLLBACK", "BEGIN", "ROLLBACK"])
        statements = list(dict.fromkeys(sql for sql in traced.sql if sql.startswith("SELECT ")))
        self.assertTrue(any("gb_operation_io" in sql for sql in statements), statements)
        self.assertTrue(any("gb_stale" in sql for sql in statements), statements)
        with self.project.read() as conn:
            self.assertEqual(self.scans(conn, statements), {})
            with closing(sqlite3.connect(self.tmp / "analizado.gpkg",
                                         isolation_level=None)) as copy:
                conn.backup(copy)
                copy.execute("ANALYZE")
                self.assertEqual(self.scans(copy, statements), {})

            conn.execute("BEGIN")
            seen: list[str] = []
            conn.set_trace_callback(seen.append)
            try:
                self.assertEqual(card.item_card(self.project, years.uid, conn=conn).record,
                                 years)
                (found,) = card.dataset_figures(self.project, [years.uid], conn=conn)
            finally:
                conn.set_trace_callback(None)
            self.assertTrue(conn.in_transaction)
            conn.execute("ROLLBACK")
        self.assertEqual(len(found.marks), 3)
        self.assertEqual([sql for sql in seen if sql in ("BEGIN", "ROLLBACK")], [])

    @staticmethod
    def scans(conn: sqlite3.Connection, statements: list[str]) -> dict[str, list[str]]:
        """De cada sentencia, las líneas de su plan que recorren entera ``gb_operation_io`` o
        ``gb_stale`` (por su nombre o por su alias)."""
        found: dict[str, list[str]] = {}
        for sql in statements:
            names = {name for match in WATCHED.finditer(sql) for name in match.groups() if name}
            plan = [str(row[-1]) for row in conn.execute(f"EXPLAIN QUERY PLAN {sql}")]
            bad = [line for line in plan
                   if line.startswith("SCAN ") and line.split()[1] in names]
            if bad:
                found[sql] = bad
        return found

    def test_unknown_and_malformed(self) -> None:
        """RF-010-06, RF-010-08 (plan 010 §5.3.1): la ficha de un dato que el proyecto no tiene
        es ``None``; un uid que no es un texto o está vacío, una lista de uid que es un texto o
        tiene algo que no lo es y unas marcas que no son verdadero o falso son errores del
        programa que llama."""
        before = self.counter()
        self.assertIsNone(card.item_card(self.project, ids.new_uid()))
        self.assertEqual(self.counter(), before)
        for wrong in (None, 7, ""):
            with self.subTest(uid=wrong), self.assertRaises(TypeError):
                card.item_card(self.project, wrong)
        uid = self.record("demo_benches").uid
        for wrong in (uid, [uid, 7], [""], None):
            with self.subTest(uids=wrong), self.assertRaises(TypeError):
                card.dataset_figures(self.project, wrong)
        with self.assertRaises(TypeError):
            card.dataset_figures(self.project, [uid], marks="sí")

# SPDX-License-Identifier: GPL-3.0-or-later
"""Regresiones de Silvestre de la procedencia, segunda parte (spec 008, T41; plan 008 §7;
Silvestre 00, §4.5): CE-008-02, CE-008-09 y CE-008-10. La primera parte (CE-008-01, 03 y 05) está
en ``test_silvestre_regresiones.py``.

Cada prueba recorre la demostración de la procedencia (``tests.support.provenance_demo``) sobre
un proyecto real en disco (``tests.support.demo_project``) con las fuentes sintéticas de
``tests/data/core/provenance/`` en ``fuentes/``, fuera del proyecto. Nada de clientes:

- **Errores 32, 58 y 68**: resultados calculados con una producción que ya había cambiado,
  presentados como buenos. Cambiar la producción deja obsoletos exactamente los años por banco
  y lo que depende de ellos (los acopios), con la causa, y nada más; cambiarle solo el tipo, nada.
- **Error 64**: dos operaciones acopladas (detectar y filtrar acopios) recalculadas por separado.
  Si una queda obsoleta, lo quedan las dos, y recalcular repite siempre las dos, juntas.
- **Principio 7**: lo importado no se sobrescribe. Actualizar dos veces el CSV de collares deja
  las tres copias de lo importado y los tres originales con sus huellas, y la procedencia de una
  cifra calculada con la primera lleva a ella (``tests.support.provenance_collars``).
- **Errores 32, 58 y 68 con un trabajo de la 004**: los años por banco calculados en un trabajo
  (el autodiagnóstico de la 004, con un ``JobRunner`` real) mientras cambia la producción se
  incorporan obsoletos, con la causa, y nunca como vigentes.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any
from unittest import mock

from tests.support import provenance_collars as collars
from tests.support import provenance_data as data
from tests.support import provenance_demo as demo
from tests.support.demo_project import DemoProjectTestCase
from tests.support.package import import_geoblender
from tests.support.provenance_checks import assert_source_untouched
from tests.support.repo import EXTENSION_DIR
from tests.support.trees import age_folders

catalog = import_geoblender("jobs.catalog")
protocol = import_geoblender("jobs.protocol")
records = import_geoblender("jobs.records")
runner = import_geoblender("jobs.runner")
jobs_ingest = import_geoblender("jobs.ingest")
graph = import_geoblender("core.provenance.graph")
importer = import_geoblender("core.provenance.importer")
lineage_mod = import_geoblender("core.provenance.lineage")
recompute = import_geoblender("core.provenance.recompute")
stale = import_geoblender("core.provenance.stale")
operations = import_geoblender("core.provenance.operations")
params = import_geoblender("core.params")
core_defs = import_geoblender("core.params.core_defs")
inputs = import_geoblender("core.inputs")
input_registry = import_geoblender("core.inputs.registry")
datasets = import_geoblender("core.datasets.registry")
hashing = import_geoblender("core.hashing")

PRODUCTION_CAUSE = "Obsoleto: cambió Producción (demostración)"
"""La causa que muestra lo que dependía de la producción (spec §8)."""
WHILE_RUNNING = f"{PRODUCTION_CAUSE} mientras se calculaba"
"""La causa de lo que se calculó en un trabajo mientras cambiaba la producción."""
NEW_PRODUCTION = 400_000.0
"""La producción del plan de labores revisado (t/año)."""
NEW_K = 1.20
"""El K del ensayo nuevo."""
KEPT_BANK_M3 = 12_000.0 + 6_500.0
"""El volumen en banco de los acopios que se quedan (B-1 y B-3, con 2,5 años o más)."""
UPDATE_REASON = "Topografía entrega los collares revisados"
SUM_PARAMS = {"n": 1000, "chunks": 2}
"""El trabajo del autodiagnóstico de la 004 que hace de cálculo de los años por banco."""
JOB_TIMEOUT_S = 120.0
DEADLINE_S = 60.0
POLL_S = 0.02


def _cents(version: int) -> list[tuple[str, int, int, int, int]]:
    """Las filas de ``collares_v<version>.csv`` en centésimas (sondeo, este, norte, cota,
    profundidad)."""
    rows = data.collar_rows()
    if version == 1:
        return rows
    return [(hole, e, n, z + data.CHANGED_COLLAR_DZ_CM if hole == data.CHANGED_COLLAR else z, d)
            for hole, e, n, z, d in rows]


def _mean_z(version: int) -> float:
    """La cota media de las bocas de ``collares_v<version>.csv`` (m), calculada a mano."""
    rows = _cents(version)
    return sum(z for _hole, _e, _n, z, _d in rows) / 100.0 / len(rows)


def _decide(project: Any, key: str, value: float | None, kind: str, reason: str) -> None:
    """Cambia el parámetro ``key`` (solo su tipo si ``value`` es ``None``) con la decisión de la
    propiedad."""
    values: dict[str, Any] = {} if value is None else {"value": value}
    with project.write_transaction() as conn:
        params.ParameterStore(project).change(
            conn, key, kind=kind, source="Plan de labores 2027", source_kind="document",
            decided_by="la propiedad", decided_at=dt.date(2026, 10, 1), reason=reason, **values)


class CascadeTest(DemoProjectTestCase):
    """La cadena entera de la demostración y lo que deja obsoleto un cambio de parámetro."""

    def operations_of(self, op_type: str) -> list[tuple[str, int, str | None]]:
        """Las operaciones de ``op_type`` (uid, sustituida o no y grupo), en su orden."""
        return self.read(lambda conn: [
            (uid, superseded, group_uid) for uid, superseded, group_uid in conn.execute(
                "SELECT uid, superseded_by IS NOT NULL, group_uid FROM gb_operation "
                "WHERE op_type = ? ORDER BY fid", (op_type,))])

    def marks(self, chain: Any) -> dict[str, bool]:
        """Si cada cifra de la cadena está obsoleta, por su clave y su ámbito."""
        found: dict[str, bool] = {}
        for handle in chain.operations:
            for figure in self.figures_of(handle.uid):
                label = figure.key + "".join(f"[{value}]" for value in figure.scope.values())
                found[label] = lineage_mod.figure_marks(
                    self.project, [figure.uid])[figure.uid].stale
        return found

    def test_err32_68_invalidacion_dag(self) -> None:
        """RF-008-24, RF-008-26, RF-008-29, RF-008-31 (CE-008-02; Silvestre, errores 32, 58 y
        68): con la cadena entera de la demostración (el límite y su área, bancos y marcas,
        años por banco, los acopios acoplados y el balance), cambiar solo el tipo de la
        producción no deja nada obsoleto. Cambiar su valor (500 000 → 400 000 t/año) deja
        obsoletos exactamente los años por banco y, en cascada, las dos operaciones acopladas de
        los acopios, sus tres datos y sus cuatro cifras, con la causa «Obsoleto: cambió
        Producción (demostración)»; el límite, su área, los bancos, las marcas y el balance
        siguen vigentes. Recalcular lo obsoleto repite los años por banco y, juntas, las dos
        acopladas, y nada más: los años son exactamente t / 400 000 y no queda nada obsoleto;
        las cifras antiguas siguen en el proyecto con la producción que leyeron."""
        chain = self.chain()
        self.assertEqual(self.obsolete(), set())
        _decide(self.project, demo.PRODUCTION, None, "ADOPTADO", "Solo cambia el tipo")
        self.assertEqual(self.obsolete(), set())

        _decide(self.project, demo.PRODUCTION, NEW_PRODUCTION, "ADOPTADO",
                "Plan de labores revisado")
        stale_ops = {chain.years.uid, chain.detect.uid, chain.filter.uid}
        stale_data = self.read(lambda conn: {
            datasets.get(conn, name).uid for name in (demo.YEARS_TABLE, demo.CANDIDATES_TABLE,
                                                      demo.STOCKPILES_TABLE)})
        self.assertEqual(self.obsolete(), {("operation", uid) for uid in stale_ops}
                         | {("dataset", uid) for uid in stale_data})
        report = stale.stale_items(self.project)
        self.assertEqual(
            [(item.name, item.op_type, item.review, item.text) for item in report.items],
            [(demo.YEARS_TABLE, demo.BENCH_YEARS, False, PRODUCTION_CAUSE),
             (demo.CANDIDATES_TABLE, demo.DETECT_STOCKPILES, False, PRODUCTION_CAUSE),
             (demo.STOCKPILES_TABLE, demo.FILTER_STOCKPILES, False, PRODUCTION_CAUSE)])
        self.assertEqual((report.counts.stale, report.counts.review), (3, 0))
        self.assertEqual(self.marks(chain), {
            demo.BOUNDARY_AREA: False,
            f"{demo.YEARS_FIGURE}[B-1]": True,
            f"{demo.YEARS_FIGURE}[B-2]": True,
            f"{demo.YEARS_FIGURE}[B-3]": True,
            demo.STOCKPILE_VOLUME: True,
            demo.SWELL_FIGURE: False,
        })
        old_years = self.figures_of(chain.years.uid)

        outcome = self.recompute_all()
        self.assertEqual(
            [(str(result.status), result.unit.operations) for result in outcome.results],
            [("done", (chain.years.uid,)), ("done", (chain.detect.uid, chain.filter.uid))])
        self.assertEqual(outcome.remaining.units, ())
        self.assertEqual(self.obsolete(), set())
        self.assertEqual(stale.counts(self.project).obsolete, 0)
        for op_type in (demo.AREA, demo.DIGITIZE, demo.BALANCE, "core.import_layer"):
            with self.subTest(sin_repetir=op_type):
                self.assertEqual(len(self.operations_of(op_type)), 1)
        (years_old, years_new) = self.operations_of(demo.BENCH_YEARS)
        self.assertEqual((years_old[1], years_new[1]), (True, False))
        detect_old, detect_new = self.operations_of(demo.DETECT_STOCKPILES)
        filter_old, filter_new = self.operations_of(demo.FILTER_STOCKPILES)
        self.assertEqual((detect_old[1:], filter_old[1:]),
                         ((True, chain.detect.group_uid), (True, chain.detect.group_uid)))
        self.assertEqual((detect_new[1], filter_new[1]), (False, False))
        self.assertEqual(detect_new[2], filter_new[2])
        self.assertNotEqual(detect_new[2], chain.detect.group_uid)
        self.assertEqual(self.years(years_new[0]),
                         {bench: tonnes / NEW_PRODUCTION for bench, tonnes in demo.DEFAULT_BENCHES})
        (volume,) = self.figures_of(filter_new[0])
        self.assertClose(volume.value, KEPT_BANK_M3 * 1.15)

        # Las cifras antiguas siguen en el proyecto, con la producción que leyeron.
        self.assertEqual(self.figures_of(chain.years.uid), old_years)
        tree = lineage_mod.lineage(self.project, old_years[0].uid)
        (production,) = tree.operations[tree.root].params
        self.assertEqual((production.value, production.rev, production.current_value,
                          production.changed), (500_000.0, 1, NEW_PRODUCTION, True))

    def test_err64_acopladas(self) -> None:
        """RF-008-25, RF-008-24, RF-008-26 (CE-008-02; Silvestre, error 64): el K solo lo lee
        el filtro de acopios, pero al cambiarlo (1,15 → 1,20) quedan obsoletas las dos
        operaciones acopladas, la detección por ser de su grupo, y sus dos datos; los años por
        banco, el área y el balance siguen vigentes. Recalcular desde cualquiera de las dos (o
        todo) planea una sola unidad con las dos, en su orden, y la ejecuta entera: dos
        operaciones nuevas del mismo grupo, nuevo, y el volumen esponjado con el K nuevo,
        18 500 × 1,20 = 22 200 m³."""
        chain = self.chain()
        _decide(self.project, demo.SWELL_FACTOR, NEW_K, "ADOPTADO", "Ensayo de esponjamiento")
        coupled = (chain.detect.uid, chain.filter.uid)
        candidates, kept = self.read(lambda conn: [
            datasets.get(conn, name).uid for name in (demo.CANDIDATES_TABLE,
                                                      demo.STOCKPILES_TABLE)])
        self.assertEqual(self.obsolete(), {("operation", uid) for uid in coupled}
                         | {("dataset", candidates), ("dataset", kept)})
        causes = self.read(lambda conn: {
            (uid, kind) for _item, uid, kind, _subject in stale.cached_rows(conn)
            if uid in coupled})
        self.assertEqual(causes, {(chain.detect.uid, "group"),
                                  (chain.detect.uid, "parameter_changed"),
                                  (chain.filter.uid, "group"),
                                  (chain.filter.uid, "parameter_changed")})
        self.assertEqual(self.read(lambda conn: conn.execute(
            "SELECT operation_uid FROM gb_operation_param WHERE key = ?",
            (demo.SWELL_FACTOR,)).fetchall()), [(chain.filter.uid,)])

        with self.project.read() as conn:
            loaded = graph.load_graph(conn)
        for scope in (chain.detect.uid, chain.filter.uid, kept, recompute.SCOPE_ALL):
            with self.subTest(ambito=scope):
                plan = recompute.plan_recompute(loaded, scope=scope)
                self.assertEqual([(unit.operations, unit.group_name) for unit in plan.units],
                                 [(coupled, demo.STOCKPILES)])
                self.assertEqual(plan.skipped, ())

        progress = list(recompute.recompute_steps(self.project, scope=chain.filter.uid))
        outcome = progress[-1].result
        (result,) = outcome.results
        self.assertEqual((str(result.status), result.unit.operations), ("done", coupled))
        detect_new, filter_new = result.operations
        new_groups = self.read(lambda conn: [group for (group,) in conn.execute(
            "SELECT group_uid FROM gb_operation WHERE uid IN (?, ?)",
            (detect_new, filter_new))])
        self.assertEqual(len(set(new_groups)), 1)
        self.assertNotIn(chain.detect.group_uid, new_groups)
        self.assertEqual(len(self.operations_of(demo.BENCH_YEARS)), 1)
        (volume,) = self.figures_of(filter_new)
        self.assertClose(volume.value, KEPT_BANK_M3 * NEW_K)
        self.assertEqual(self.obsolete(), set())


class ImportedCopiesTest(DemoProjectTestCase):
    """El CSV de collares importado, actualizado dos veces, y una cifra de la primera
    importación."""

    def setUp(self) -> None:
        super().setUp()
        if "core.original_copy_limit" not in params.DEFINITIONS:
            params.register_definitions(core_defs.DEFINITIONS)
            self.addCleanup(params.unregister_definitions, "core")
        self.enterContext(collars.registered())

    def update(self, name: str) -> Any:
        """El cliente entrega ``name`` como ``fuentes/collares.csv``: la entrada queda
        «cambiada» y se actualiza («Actualizar»), sin tocar nada junto a la fuente."""
        self.deliver(name, collars.SOURCE_NAME)
        age_folders(self.sources)
        with assert_source_untouched(self.sources):
            found = list(inputs.check_steps(self.project))[-1].result
            self.assertEqual([(item.name, item.verdict) for item in found.findings],
                             [(collars.INPUT_NAME, inputs.Verdict.CHANGED)])
            return self.run_step(lambda: importer.reimport_input(
                self.project, collars.INPUT_NAME, UPDATE_REASON))

    def test_principio7_tres_copias(self) -> None:
        """RF-008-52, RF-008-53, RF-008-11, RF-008-14 (CE-008-09; principio 7): el CSV de
        collares se importa (lo importado en una tabla propia, inmutable, y su original
        guardado con su huella) y su cota media es una cifra. Actualizarlo dos veces
        (``collares_v2``: la cota de S-07 1,20 m más alta; ``collares_v3``: la columna ``cota``
        pasa a ``z``) deja en el proyecto las tres entradas encadenadas (dos sustituidas y la
        vigente), las tres copias de lo importado con sus filas y su hash intactos y protegidas
        frente a otro programa, y los tres originales con sus huellas, los de cada versión. La
        procedencia de la cifra calculada con la primera lleva a la primera entrada y a su
        copia; recalcularla da la cota media nueva (+0,08 m) desde la tercera. Nada se escribe
        junto a la fuente."""
        source = self.deliver(data.COLLARS_V1, collars.SOURCE_NAME)
        age_folders(self.sources)
        with assert_source_untouched(self.sources):
            first = self.run_step(lambda: collars.import_collars(self.project, source))
        elevation = self.run_step(lambda: collars.mean_elevation(self.project))
        (old_figure,) = self.figures_of(elevation.uid)
        self.assertClose(old_figure.value, _mean_z(1))

        imports = [first, self.update(data.COLLARS_V2), self.update(data.COLLARS_V3)]
        entries = [self.read(lambda conn, uid=item.input.uid: input_registry.get(conn, uid))
                   for item in imports]
        self.assertEqual([(entry.name, str(entry.status)) for entry in entries],
                         [(collars.INPUT_NAME, "superseded"), (collars.INPUT_NAME, "superseded"),
                          (collars.INPUT_NAME, "current")])
        self.assertEqual([entry.previous_uid for entry in entries],
                         [None, entries[0].uid, entries[1].uid])
        names = (data.COLLARS_V1, data.COLLARS_V2, data.COLLARS_V3)
        headers = (data.COLLAR_HEADER, data.COLLAR_HEADER,
                   tuple("z" if column == "cota" else column for column in data.COLLAR_HEADER))
        for version, item, entry, name, header in zip((1, 2, 3), imports, entries, names, headers,
                                                       strict=True):
            with self.subTest(version=version):
                imported = self.read(lambda conn, uid=item.dataset.uid: datasets.get(conn, uid))
                self.assertEqual(
                    (imported.name, imported.status, imported.immutable, imported.input_uid,
                     imported.content_sha256),
                    (collars.DATASET, "current" if version == 3 else "superseded", True,
                     entry.uid, item.dataset.content_sha256))
                self.assertEqual(self.read(lambda conn, record=imported: datasets.content_digest(
                    conn, self.project, record).content_sha256), imported.content_sha256)
                self.assertEqual(self.read(lambda conn, table=imported.locator: [
                    row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')][1:]),
                    list(header))
                self.assertEqual(
                    self.read(lambda conn, table=imported.locator: conn.execute(
                        f'SELECT * FROM "{table}" ORDER BY fid').fetchall()),
                    [(index, hole, e / 100, n / 100, z / 100, d / 100)
                     for index, (hole, e, n, z, d) in enumerate(_cents(version), start=1)])
                (stored,) = entry.files
                expected = data.file_sha256(data.DATA_DIR / name)
                self.assertEqual(
                    (entry.original, stored.sha256, stored.original_path,
                     stored.original_sha256),
                    (inputs.OriginalState.STORED, expected,
                     f"originals/{entry.uid}/{collars.SOURCE_NAME}", expected))
                self.assertEqual(
                    hashing.sha256_file(self.project.root / stored.original_path), expected)
                qgis = sqlite3.connect(str(self.project.database_path), timeout=2.0,
                                       isolation_level=None)
                self.addCleanup(qgis.close)
                with self.assertRaises(sqlite3.IntegrityError) as caught:
                    qgis.execute(f'UPDATE "{imported.locator}" SET sondeo = \'S-99\'')
                self.assertIn("es lo importado de la entrada «collares»", str(caught.exception))

        tree = lineage_mod.lineage(self.project, old_figure.uid)
        self.assertEqual(list(tree.inputs), [first.input.uid])
        (consumed,) = tree.operations[tree.root].consumed
        self.assertEqual((consumed.uid, consumed.content_sha256, consumed.status),
                         (first.dataset.uid, first.dataset.content_sha256, "superseded"))
        self.assertEqual(tree.inputs[first.input.uid].successor_uid, entries[1].uid)

        outcome = self.recompute_all()
        self.assertEqual([result.unit.operations for result in outcome.results],
                         [(elevation.uid,)])
        (new_figure,) = self.figures_of(outcome.results[0].operations[0])
        self.assertClose(new_figure.value, _mean_z(3))
        self.assertAlmostEqual(new_figure.value - old_figure.value, 1.20 / 15, places=9)
        self.assertEqual(list(lineage_mod.lineage(self.project, new_figure.uid).inputs),
                         [entries[2].uid])
        self.assertEqual(sorted(path.relative_to(self.project.root).as_posix()
                                for path in (self.project.root / "originals").rglob("*")
                                if path.is_file()),
                         sorted(f"originals/{entry.uid}/{collars.SOURCE_NAME}"
                                for entry in entries))


class JobTest(DemoProjectTestCase):
    """Los años por banco calculados en un trabajo de la 004 (el autodiagnóstico, en un hilo,
    con un lanzador real)."""

    def setUp(self) -> None:
        super().setUp()
        self.enterContext(mock.patch.dict(catalog._REGISTRY, clear=True))
        builtin = next(info for info in catalog.BUILTIN_WORKERS if info.name == "selftest")
        catalog.register_worker(dataclasses.replace(builtin, default_timeout_s=JOB_TIMEOUT_S))
        jobs_root = self.tmp / "jobs"
        jobs_root.mkdir()
        self.runner = runner.JobRunner(jobs_root=jobs_root, package_dir=EXTENSION_DIR,
                                       blender_python=Path(sys.executable))
        self.addCleanup(self.runner.shutdown)

    def submit(self, handle: Any) -> Any:
        """El trabajo de la operación ``handle``, con su uid en la petición."""
        return self.runner.submit(protocol.new_request(
            "selftest", label="Años por banco (demostración)", owner=demo.DEMO_CODE,
            params=SUM_PARAMS, project_uid=self.project.uid, operation_uid=handle.uid))

    def finish(self, job: Any) -> Any:
        """Sondea el lanzador hasta que el trabajo termina; su ``JobResult``."""
        deadline = time.monotonic() + DEADLINE_S
        while job.result() is None:
            if time.monotonic() > deadline:
                raise AssertionError("el trabajo no terminó a tiempo")
            self.runner.poll()
            time.sleep(POLL_S)
        return job.result()

    def test_err32_trabajo_con_produccion_cambiada(self) -> None:
        """RF-008-20, RF-008-23, RF-008-24, RF-008-31 (CE-008-10; Silvestre, errores 32, 58 y
        68): los años por banco se calculan en un trabajo de la 004 con la producción de
        500 000 t/año que leyó la operación al empezar; mientras corre, «pendiente de
        incorporar», la propiedad la cambia a 400 000. Al incorporarlo, con su procedencia
        técnica (intérprete, hilo y trabajo), la operación queda hecha y obsoleta con la causa
        «Obsoleto: cambió Producción (demostración) mientras se calculaba», sus años
        (t / 500 000) en el proyecto pero con sus cifras marcadas obsoletas, y nunca como
        vigentes. Recalcular lo obsoleto da los años con la producción vigente, t / 400 000, y
        deja la del trabajo como historia."""
        self.run_step(lambda: self.demo.digitize(self.project))
        handle = self.run_step(lambda: self.demo.bench_years_job(self.project))
        job = self.submit(handle)
        self.assertEqual(lineage_mod.result_state(self.project, handle.uid).state,
                         lineage_mod.ResultState.PENDING)
        _decide(self.project, demo.PRODUCTION, NEW_PRODUCTION, "ADOPTADO",
                "Plan de labores revisado")
        self.clock.advance(minutes=1)
        result = self.finish(job)
        outcome = jobs_ingest.job_outcome(result, job.job_dir)
        done = self.run_step(lambda: self.demo.ingest_bench_years(self.project, handle,
                                                                  outcome))
        self.assertEqual((done.status, done.ingested, done.stale, done.text()),
                         ("done", True, True, WHILE_RUNNING))
        self.assertGreater(self.runner.mark_ingested(job.job_uid), 0)

        tree = lineage_mod.lineage(self.project, handle.uid)
        link = tree.operations[handle.uid]
        self.assertEqual(
            (link.status, link.executor, link.job_uid, dict(link.interpreter or {}),
             link.stale_text),
            ("done", "job_thread", job.job_uid,
             records.read_record(job.job_dir).interpreter.to_json(), WHILE_RUNNING))
        (production,) = link.params
        self.assertEqual((production.value, production.current_value, production.changed),
                         (500_000.0, NEW_PRODUCTION, True))
        self.assertEqual(self.years(handle.uid),
                         {bench: tonnes / 500_000.0 for bench, tonnes in demo.DEFAULT_BENCHES})
        report = stale.stale_items(self.project)
        self.assertEqual([(item.name, item.operation_uid, item.text) for item in report.items],
                         [(demo.YEARS_TABLE, handle.uid, WHILE_RUNNING)])
        figures = self.figures_of(handle.uid)
        marks = lineage_mod.figure_marks(self.project, [figure.uid for figure in figures])
        self.assertTrue(all(marks[figure.uid].stale for figure in figures))

        outcome = self.recompute_all()
        (unit,) = outcome.results
        self.assertEqual((str(unit.status), unit.unit.operations), ("done", (handle.uid,)))
        (redone,) = unit.operations
        self.assertEqual(self.years(redone),
                         {bench: tonnes / NEW_PRODUCTION for bench, tonnes in demo.DEFAULT_BENCHES})
        for bench, _tonnes in demo.DEFAULT_BENCHES:
            with self.subTest(banco=bench):
                current = self.demo.current_figure(self.project, demo.YEARS_FIGURE,
                                                   {"bench": bench})
                self.assertEqual(current.operation_uid, redone)
        self.assertEqual(stale.counts(self.project).obsolete, 0)
        self.assertEqual(self.read(lambda conn: conn.execute(
            "SELECT superseded_by FROM gb_operation WHERE uid = ?", (handle.uid,)).fetchone()),
            (redone,))

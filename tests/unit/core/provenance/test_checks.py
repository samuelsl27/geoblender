# SPDX-License-Identifier: GPL-3.0-or-later
"""Comprobaciones de apertura (spec 008, T36 y T37; RF-008-09, RF-008-19, RF-008-21,
RF-008-22, RF-008-24, RF-008-57, RF-008-60, RF-008-62 y RF-008-58; plan 008 §5.3.1 y §5.4.6).

``core.provenance.checks.open_check_steps`` hace, justo después de abrir y por pasos que avanza
un temporizador de ``bl``, con su progreso («Comprobando el proyecto… 42 %»), los pasos 1 a 6
(``survey_steps``, T36; ninguno pasa de 20 ms):

1. la **foto**: la hora de inicio, lo registrado (por páginas) y el listado de ``rasters/``,
   ``meshes/`` y ``originals/`` (tamaño y fecha por ``os.scandir``);
2. las operaciones «en curso» de otras sesiones, que quedan **interrumpidas**;
3. el **prefiltro de las entradas** vigentes, cambiadas sin decidir y mantenidas;
4. el **prefiltro de los datos** del proyecto y de los originales contra la foto (lo que esta
   sesión registró después de la foto no es una edición externa) y **lo que falta**;
5. los **restos** (apartados en escritura), los ficheros ajenos y las capas sin registrar;
6. las **versiones de algoritmo** mayores (con su aviso) y las **definiciones** de parámetros
   cambiadas.

Esos pasos no leen el contenido de nada ni escriben nada en la base. Después (T37):

7. la **cola de hashes** de lo que saltó: lo del proyecto en el hilo, por trozos, y las fuentes
   externas grandes en trabajos (``HashJobs``, que pone ``bl``), con lo que pidió la puerta;
8. **una sola transacción final** con ``Project.try_write`` (reintentada si otro programa está
   leyendo) con todo lo encontrado y la obsolescencia completa; en solo lectura, el informe.

Cada prueba usa el proyecto de ``test_external`` (esquema 2, reloj simulado): la entrada
«Limites_v1» importada en ``res_limites``; ``res_contorno`` (editable a mano) y ``res_bocas``
calculados de ella; ``res_area`` de ``res_contorno``.

La obsolescencia completa del paso 8 se calcula en pasos anteriores, leyendo sin escribir, y la
transacción final escribe solo su diferencia con la caché (T65; RNF-008-12): las pruebas de
:class:`OpenCacheTest` la comparan, con la demostración (``tests.support.demo_project``), con la
transacción final de antes (lo encontrado y, al final, ``refresh_all``) sobre la misma base,
también con un cambio del proyecto mientras se calcula y entre el cálculo y la escritura.
"""

from __future__ import annotations

import ast
import contextlib
import dataclasses
import json
import os
import re
import shutil
import sqlite3
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest import mock

from tests.support import open_check
from tests.support import provenance_data as data
from tests.support import provenance_demo as demo_support
from tests.support.core_fixtures import make_session
from tests.support.demo_project import DemoProjectTestCase
from tests.support.package import import_geoblender
from tests.support.provenance_checks import assert_source_untouched
from tests.support.provenance_contract import registered
from tests.support.timing import MAX_ATTEMPTS
from tests.support.trees import age_folders
from tests.unit.core.datasets.test_external import (
    BYTES,
    DAMAGED_TEXT,
    GRID,
    MISSING_TEXT,
    ORIGINAL,
    TERRAIN_FILE,
    ExternalCase,
)
from tests.unit.core.inputs.test_check import BASE_NS, SOURCE
from tests.unit.core.inputs.test_registry import GPKG, MTIME_NS, SESSION
from tests.unit.core.params.test_store import DENSITY, DENSITY_KG, SWELL
from tests.unit.core.provenance.test_gate import AREA, EDITED_AT, PLAN, _spec
from tests.unit.core.provenance.test_schema import dataset_row, operation_row

checks = import_geoblender("core.provenance.checks")
provenance = import_geoblender("core.provenance")
operations = import_geoblender("core.provenance.operations")
stale_mod = import_geoblender("core.provenance.stale")
graph_mod = import_geoblender("core.provenance.graph")
gate = import_geoblender("core.provenance.gate")
contract = import_geoblender("core.provenance.contract")
readers = import_geoblender("core.content.readers")
session_mod = import_geoblender("core.project.session")
external = import_geoblender("core.datasets.external")
dataset_registry = import_geoblender("core.datasets.registry")
datasets = import_geoblender("core.datasets")
tracking = import_geoblender("core.datasets.tracking")
check = import_geoblender("core.inputs.check")
inputs_registry = import_geoblender("core.inputs.registry")
inputs_model = import_geoblender("core.inputs.model")
lock = import_geoblender("core.project.lock")
project_model = import_geoblender("core.project.model")
params = import_geoblender("core.params")
base = import_geoblender("core.gpkg.base")
hashing = import_geoblender("core.hashing")
ids = import_geoblender("core.ids")

Use = operations.Use
ItemKind = operations.ItemKind
Signal = external.Signal
Verdict = external.DatasetVerdict
InputVerdict = check.Verdict
InputStatus = inputs_model.InputStatus
Status = datasets.DatasetStatus
OriginalVerdict = external.OriginalVerdict

SESSION_B = make_session(session_uid="00000000-0000-4000-8000-0000000000b2",
                         host="PC-PRUEBA-B", user="otra", pid=4242)
"""La sesión de otro Blender (otro equipo) que dejó operaciones «en curso»."""
BUDGET_S = 0.020
PROGRESS = r"^Comprobando el proyecto… \d{1,3} %$"
VOLUME_TABLE = "res_vol"
VOLUME_ROWS = 400  # datos de una tabla común (por selector)
VOLUME_FILES = 200  # datos de rasters/vol/
UNREACHABLE = ("No se encuentra la fuente de la entrada «planos» (plano.dxf): no localizable; se "
               "sigue con lo importado.")
GRAPH_READ = re.compile(
    r"^\s*SELECT\b.*\b(?:FROM|JOIN)\s+gb_(?:operation_io|operation_param|dataset|stale)\b", re.S)
"""Una lectura del grafo o de la caché en una sentencia SQL."""
CACHE_WRITE = re.compile(r"^\s*(?:INSERT INTO|DELETE FROM|UPDATE)\s+gb_stale\b")
"""Una escritura en la caché ``gb_stale``."""


class ChecksCase(ExternalCase):
    """El proyecto de ``test_external`` y lo que declara el Geoblender que lo abre."""

    def setUp(self) -> None:
        super().setUp()
        self.registries = checks.Registries.installed()

    # --- Ayudas -----------------------------------------------------------------------------

    def steps(self, **kw: Any) -> list[Any]:
        """Todos los pasos 1 a 6 de la comprobación de apertura (en escritura, por defecto)."""
        kw.setdefault("write", True)
        registries = kw.pop("registries", self.registries)
        return list(checks.survey_steps(self.project, registries, **kw))

    def open_check(self, **kw: Any) -> Any:
        """El resultado de los pasos 1 a 6 de la comprobación de apertura (el último paso)."""
        found = self.steps(**kw)
        for step in found:
            self.assertIsInstance(step, project_model.Progress)
        self.assertEqual([step.result is not None for step in found],
                         [False] * (len(found) - 1) + [True])
        outcome = found[-1].result
        self.assertIsInstance(outcome, checks.OpenCheckOutcome)
        return outcome

    def drive(self, steps: Iterator[Any]) -> tuple[Any, list[float]]:
        """Avanza los pasos hasta el final: el resultado y lo que tardó cada ``next``."""
        durations: list[float] = []
        outcome = None
        while True:
            start = time.perf_counter()
            try:
                step = next(steps)
            except StopIteration:
                durations.append(time.perf_counter() - start)
                return outcome, durations
            durations.append(time.perf_counter() - start)
            self.assertIsInstance(step, project_model.Progress)
            if step.result is not None:
                self.assertIsNone(outcome, "un solo paso lleva el resultado")
                outcome = step.result

    def through_photo(self, steps: Iterator[Any]) -> list[Any]:
        """Avanza los pasos de la foto (hasta el primero de otra fase)."""
        return self.until(steps, lambda step: step.phase != checks.OPEN_CHECK_STEPS[0])

    def until(self, steps: Iterator[Any], stop: Any) -> list[Any]:
        """Avanza los pasos hasta el primero que cumple ``stop`` (incluido)."""
        found: list[Any] = []
        for step in steps:
            found.append(step)
            if stop(step):
                return found
        self.fail("la comprobación terminó antes de lo esperado")

    def check_all(self, **kw: Any) -> tuple[Any, list[Any]]:
        """Todos los pasos 1 a 8 de la comprobación de apertura (en escritura, por defecto): su
        resultado (solo en el último paso) y los pasos."""
        kw.setdefault("write", True)
        registries = kw.pop("registries", self.registries)
        found = list(checks.open_check_steps(self.project, registries, **kw))
        for step in found:
            self.assertIsInstance(step, project_model.Progress)
        self.assertEqual([step.result is not None for step in found],
                         [False] * (len(found) - 1) + [True])
        outcome = found[-1].result
        self.assertIsInstance(outcome, checks.OpenCheckOutcome)
        return outcome, found

    def changes(self) -> Any:
        """Lo que pasa antes de abrir, uno de cada: otro Blender (``SESSION_B``) deja «res.plan»
        en curso; la fuente de «Limites_v1» pasa a la v2; QGIS edita ``res_contorno`` (editable
        a mano) y borra la capa ``res_bocas``; queda un resto en ``rasters/``; ``res.density``
        está registrado en t/m³. Devuelve lo que declara el Geoblender que abre: «res.area»
        2.0 y ``res.density`` en kg/m³ (en ``self.other``, la operación en curso)."""
        with self.as_session(SESSION_B):
            self.other = operations.begin_operation(self.project, PLAN.op_type, settings={},
                                                    executor="blender")
        params.register_definitions((DENSITY,))
        self.addCleanup(params.unregister_definitions, "res")
        store = params.ParameterStore(self.project)
        self.write(lambda conn: store.ensure_default(conn, DENSITY.key,
                                                     geoblender_version="0.3.0"))
        self.later()
        self.replace(data.BOUNDARY_V2)
        self.qgis('UPDATE "res_contorno" SET valor = 9 WHERE codigo = ?', ("C-01",),
                  table="res_contorno", at=EDITED_AT)
        self.foreign('DROP TABLE "res_bocas"')
        self.foreign("DELETE FROM gpkg_contents WHERE table_name = 'res_bocas'")
        leftover = self.path("rasters/res_resto.bin")
        leftover.parent.mkdir(parents=True, exist_ok=True)
        leftover.write_bytes(b"resto")
        os.utime(leftover, ns=(BASE_NS, BASE_NS))
        declared = dict(params.DEFINITIONS)
        declared[DENSITY.key] = DENSITY_KG
        return checks.Registries({**self.registries.versions, AREA.op_type: "2.0"}, declared)

    def events(self, kind: str) -> list[dict[str, Any]]:
        return self.rows("gb_event", "kind = ?", (kind,))

    def assertCacheDeduced(self, versions: Any) -> None:
        """La caché ``gb_stale`` es la obsolescencia completa deducida con ``versions``."""
        with self.project.read() as conn:
            state = graph_mod.deduce(graph_mod.load_graph(conn), versions=versions)
            self.assertEqual(stale_mod.cached_rows(conn), stale_mod.expected_rows(state))

    def assertRecorded(self, outcome: Any, registries: Any) -> None:
        """Lo de :meth:`changes`, registrado en el proyecto, una vez cada cosa."""
        self.assertTrue(outcome.writing and outcome.recorded)
        self.assertEqual(self.rows("gb_operation", "uid = ?", (self.other.uid,))[0]["status"],
                         "interrupted")
        self.assertEqual(self.input_row(self.record.uid)["status"], "changed")
        self.assertEqual(self.input_row(self.record.uid)["seen_sha256"],
                         self.content_of(self.target))
        (edit,) = self.external_edits()
        self.assertEqual(self.dataset("res_contorno").operation_uid, edit["uid"])
        self.assertEqual(self.dataset("res_contorno").status, Status.CURRENT)
        self.assertEqual(self.dataset("res_bocas").status, Status.MISSING)
        (parameter,) = self.rows("gb_parameter", "key = ?", (DENSITY.key,))
        self.assertIsNotNone(parameter["review"])
        for kind in ("operation_interrupted", "input_changed", "external_edit",
                     "dataset_missing", "orphans_moved", "definition_changed",
                     "algorithm_changed"):
            with self.subTest(kind=kind):
                self.assertEqual(len(self.events(kind)), 1)
        (algorithm,) = self.events("algorithm_changed")
        self.assertEqual(algorithm["message"], outcome.algorithms[0].text())
        (changed,) = self.events("input_changed")
        self.assertGreaterEqual(json.loads(changed["data"])["dependents"]["datasets"], 3)
        (definition,) = self.events("definition_changed")
        self.assertEqual((definition["entity_kind"], definition["entity_uid"]),
                         ("parameter", parameter["uid"]))
        self.assertTrue(outcome.orphans.recorded)
        self.assertFalse(self.path("rasters/res_resto.bin").exists())
        self.assertCacheDeduced(registries.versions)
        self.assertIn("res_area", self.stale_names())

    @contextlib.contextmanager
    def never_hashed(self) -> Iterator[None]:
        """Ni las fuentes de las entradas ni los datos ni los originales se leen enteros: lo
        que salta se hashea en el paso 7 (T37)."""
        never = AssertionError("los pasos 1 a 6 no leen el contenido de nada")
        with contextlib.ExitStack() as stack:
            for module, name in ((check, "read_steps"), (external, "read_steps"),
                                 (external, "content_digest"), (external, "sha256_file"),
                                 (dataset_registry, "content_digest")):
                stack.enter_context(mock.patch.object(module, name, side_effect=never))
            yield

    def read_only(self) -> Any:
        return mock.patch.object(type(self.project), "writable", property(lambda _s: False))

    def names(self, uids: Any) -> set[str]:
        return {self.dataset(uid).name for uid in uids}

    def file_dataset(self, name: str, locator: str, content: bytes,
                     mtime_ns: int | None = None) -> Any:
        """Un fichero de rejilla de ``rasters/`` que escribe «res.grid» (repetible); con
        ``mtime_ns``, con esa fecha."""
        path = self.path(locator)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        if mtime_ns is not None:
            os.utime(path, ns=(mtime_ns, mtime_ns))
        handle = operations.begin_operation(self.project, GRID.op_type, settings={},
                                            executor="blender")
        self.write(lambda conn: handle.complete(conn, outputs=[datasets.DatasetSpec(
            name, "res", "raster", "rasters", locator, reader=BYTES.id, role="terrain")]))
        return handle

    def holder(self, session: Any) -> None:
        """El cerrojo del proyecto pasa a ser de ``session`` (hasta el final de la prueba)."""
        path = lock.lock_path(self.project.root)
        saved = path.read_bytes()
        self.addCleanup(path.write_bytes, saved)
        path.write_bytes(lock.encode_lock(lock.LockInfo.new(session, lock.LockMode.LOCAL,
                                                            self.clock)))

    @contextlib.contextmanager
    def as_session(self, session: Any) -> Iterator[None]:
        """Lo que se hace dentro, lo hace el Blender de ``session`` (con el cerrojo)."""
        path = lock.lock_path(self.project.root)
        saved = path.read_bytes()
        path.write_bytes(lock.encode_lock(lock.LockInfo.new(session, lock.LockMode.LOCAL,
                                                            self.clock)))
        try:
            with mock.patch.object(self.project, "session", session):
                yield
        finally:
            path.write_bytes(saved)

    def volume(self) -> list[Path]:
        """Muchos datos de golpe: :data:`VOLUME_ROWS` en una tabla común (uno por selector) y
        :data:`VOLUME_FILES` ficheros de ``rasters/vol/``, de una operación «res.grid» hecha;
        devuelve los ficheros."""
        files = []
        for index in range(VOLUME_FILES):
            path = self.path(f"rasters/vol/res_v{index:03d}.bin")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"v" * (index + 1))
            files.append(path)
        op_uid = ids.new_uid()
        content = hashing.sha256_bytes(b"volumen")

        def work(conn: Any) -> None:
            base.create_attribute_table(conn, VOLUME_TABLE, [base.ColumnDef("codigo", "TEXT")],
                                        VOLUME_TABLE)
            tracking.track_table(conn, VOLUME_TABLE)
            conn.executemany(f'INSERT INTO "{VOLUME_TABLE}" (codigo) VALUES (?)',
                             [(f"V{index}",) for index in range(VOLUME_ROWS)])
            state = tracking.table_states(conn, [VOLUME_TABLE])[VOLUME_TABLE]
            row = operation_row(uid=op_uid, op_type=GRID.op_type, module="res", repeatable=1,
                                session_uid=SESSION.session_uid)
            conn.execute(f"INSERT INTO gb_operation ({', '.join(row)}) "
                         f"VALUES ({', '.join('?' for _ in row)})", tuple(row.values()))
            rows = [dataset_row(
                uid=ids.new_uid(), name=f"res_vol_{index}", module="res", kind="table",
                locator=VOLUME_TABLE,
                selector=hashing.canonical_json({"column": "codigo", "equals": f"V{index}"}
                                                ).decode("utf-8"),
                reader=GPKG, content_sha256=content, crs_epsg=None, operation_uid=op_uid,
                input_uid=None, immutable=0, tracked_last_change=state.last_change,
                tracked_schema_sha256=state.schema_sha256,
            ) for index in range(VOLUME_ROWS)]
            for index, path in enumerate(files):
                found = path.stat()
                rows.append(dataset_row(
                    uid=ids.new_uid(), name=f"res_v{index:03d}", module="res", kind="raster",
                    store="rasters", locator=f"rasters/vol/{path.name}", selector="",
                    reader=BYTES.id, content_sha256=content, crs_epsg=None,
                    operation_uid=op_uid, input_uid=None, immutable=0,
                    tracked_size=found.st_size, tracked_mtime_ns=found.st_mtime_ns,
                    tracked_last_change=None, tracked_schema_sha256=None,
                ))
            conn.executemany(f"INSERT INTO gb_dataset ({', '.join(rows[0])}) "
                             f"VALUES ({', '.join('?' for _ in rows[0])})",
                             [tuple(item.values()) for item in rows])

        self.write(work)
        return files

    def summary(self, outcome: Any) -> tuple[Any, ...]:
        """Lo que encontró la comprobación, sin el orden en que se encontró."""
        return (
            tuple(item.uid for item in outcome.interrupted),
            sorted((item.input_uid, item.verdict) for item in outcome.inputs),
            sorted(item.record.uid for item in outcome.input_probes),
            sorted((item.record.uid, item.verdict) for item in outcome.datasets),
            sorted((item.record.uid, item.signal) for item in outcome.dataset_probes),
            sorted(outcome.checked_datasets),
            sorted(outcome.stale),
            sorted((item.path, item.verdict) for item in outcome.originals),
            sorted(item.path for item in outcome.original_probes),
            sorted((item.path, item.state) for item in outcome.orphans.orphans),
            outcome.orphans.foreign,
            outcome.algorithms,
            outcome.definitions,
        )


class StepsTest(ChecksCase):
    def test_steps_in_order_with_progress_without_reading_or_writing(self) -> None:
        """RF-008-58, RF-008-09, RF-008-21, RF-009-09 (plan §5.4.6; plan 009 A8): sin nada
        cambiado, los siete pasos corren en orden (foto, interrumpidas, entradas, datos, restos,
        instantáneas —sin revisiones congeladas, nada— y versiones), con su
        progreso «Comprobando el proyecto… n %» que no retrocede y acaba en el 100 %; solo el
        último lleva el resultado, que no encuentra nada: «Limites_v1» sin cambios y todos los
        datos seguidos comprobados (también la rejilla de ``rasters/``), sin avisos. No se lee
        el contenido de nada (ni la fuente, ni los datos, ni los originales), no se escribe nada
        en el proyecto y la fuente queda intacta."""
        self.terrain()
        age_folders(self.sources)
        before = self.full_state()
        with assert_source_untouched(self.sources), self.never_hashed():
            found = self.steps()
        self.assertEqual(self.full_state(), before)
        phases = [step.phase for step in found]
        self.assertEqual(list(dict.fromkeys(phases)), list(checks.SURVEY_STEPS))
        self.assertEqual(checks.SURVEY_STEPS, ("foto", "interrumpidas", "entradas", "datos",
                                                   "restos", "instantáneas", "versiones"))
        order = [checks.SURVEY_STEPS.index(phase) for phase in phases]
        self.assertEqual(order, sorted(order))
        done = [step.done for step in found]
        self.assertEqual(done, sorted(done))
        self.assertEqual({step.total for step in found}, {checks.PROGRESS_TOTAL})
        self.assertEqual(done[-1], checks.PROGRESS_TOTAL)
        for step in found:
            self.assertRegex(step.message, PROGRESS)
        self.assertEqual(found[-1].message, "Comprobando el proyecto… 100 %")
        self.assertEqual([step.result is not None for step in found],
                         [False] * (len(found) - 1) + [True])
        outcome = found[-1].result
        self.assertTrue(outcome.writing)
        self.assertEqual([(item.name, item.verdict) for item in outcome.inputs],
                         [("Limites_v1", InputVerdict.UNCHANGED)])
        self.assertEqual(outcome.checked_inputs, (self.record.uid,))
        self.assertEqual(self.names(outcome.checked_datasets),
                         {"res_limites", "res_contorno", "res_bocas", "res_area", "res_mdt",
                          "res_plano"})
        self.assertEqual((outcome.interrupted, outcome.input_probes, outcome.datasets,
                          outcome.dataset_probes, outcome.originals, outcome.original_probes,
                          outcome.stale, outcome.algorithms, outcome.definitions),
                         ((),) * 9)
        self.assertEqual((outcome.orphans.orphans, outcome.orphans.foreign), ((), ()))
        self.assertEqual((outcome.warnings, outcome.texts("en")), ((), ()))
        self.assertLessEqual(outcome.started_at_ns, time.time_ns())

    def test_no_step_takes_longer_than_its_budget(self) -> None:
        """RF-008-58 (plan §5.4.6; RNF-008-12): con :data:`VOLUME_ROWS` datos de una tabla y
        :data:`VOLUME_FILES` ficheros más el proyecto de prueba, con cambios (ficheros tocados
        y que faltan), ningún paso pasa de 20 ms (con la máquina cargada se repite hasta
        encontrar un momento tranquilo); con un presupuesto mínimo, cada unidad de trabajo es un
        paso y lo encontrado es lo mismo."""
        files = self.volume()
        for path in files[:3]:
            self.touch(path)
        for path in files[-2:]:
            path.unlink()

        def run(budget_s: float = BUDGET_S) -> tuple[Any, list[float]]:
            return self.drive(checks.survey_steps(self.project, self.registries,
                                                  write=True, budget_s=budget_s))

        outcome, durations = run()
        worst = max(durations)
        for _attempt in range(MAX_ATTEMPTS // 4):
            if worst <= BUDGET_S:
                break
            worst = min(worst, max(run()[1]))
        self.assertLessEqual(worst, BUDGET_S, f"un paso tardó {worst * 1000:.1f} ms")
        self.assertEqual({item.record.name for item in outcome.dataset_probes},
                         {"res_v000", "res_v001", "res_v002"})
        self.assertEqual({(item.record.name, item.verdict) for item in outcome.datasets},
                         {("res_v198", Verdict.MISSING), ("res_v199", Verdict.MISSING)})
        # los 4 del proyecto de prueba y los del volumen, menos los 3 que esperan su hash
        self.assertEqual(len(outcome.checked_datasets), VOLUME_ROWS + VOLUME_FILES - 3 + 4)
        tiny, tiny_durations = run(1e-9)
        self.assertGreater(len(tiny_durations), VOLUME_FILES)
        self.assertGreater(len(tiny_durations), 3 * len(durations))
        self.assertEqual(self.summary(tiny), self.summary(outcome))


class InterruptedTest(ChecksCase):
    def test_operations_running_in_another_session_are_interrupted(self) -> None:
        """RF-008-19: las operaciones «en curso» de otra sesión (su Blender se cerró sin
        registrar su final; también la de un trabajo) se encuentran, en orden, con su sesión,
        quién, cuándo y su trabajo, y el aviso de la operación interrumpida (el texto que
        registrará la transacción final); las de esta sesión siguen en curso y las terminadas no
        cuentan. No se escribe nada. En solo lectura, las de la sesión que tiene el cerrojo
        siguen en curso en ella; las de una sesión que ya no lo tiene, sí."""
        with self.as_session(SESSION_B):
            other = operations.begin_operation(self.project, PLAN.op_type, settings={},
                                               executor="blender")
            job = operations.begin_operation(self.project, AREA.op_type, settings={},
                                             executor="job_process", job_uid="job-0007")
        self.later()
        mine = operations.begin_operation(self.project, PLAN.op_type, settings={},
                                          executor="blender")
        failed = operations.begin_operation(self.project, PLAN.op_type, settings={},
                                            executor="blender")
        failed.fail("Faltan las cotas de 3 sondeos")
        before = self.full_state()
        outcome = self.open_check()
        self.assertEqual(self.full_state(), before)
        started = self.rows("gb_operation", "uid = ?", (other.uid,))[0]["started_at"]
        self.assertEqual(
            [(item.uid, item.op_type, item.session_uid, item.user_host, item.started_at,
              item.job_uid) for item in outcome.interrupted],
            [(other.uid, PLAN.op_type, SESSION_B.session_uid, SESSION_B.user_host, started,
              None),
             (job.uid, AREA.op_type, SESSION_B.session_uid, SESSION_B.user_host, started,
              "job-0007")],
        )
        reason = operations.INTERRUPTED_REASON.format(user_host=SESSION_B.user_host)
        text = f"Operación «{PLAN.op_type}» interrumpida: {reason}"
        self.assertEqual(outcome.interrupted[0].text(), text)
        self.assertEqual(outcome.warnings[0], text)
        self.assertTrue(outcome.interrupted[0].text("en").startswith(
            f"Operation «{PLAN.op_type}» was interrupted: the session of "
            f"{SESSION_B.user_host}"))
        self.assertEqual([self.rows("gb_operation", "uid = ?", (h.uid,))[0]["status"]
                          for h in (other, job, mine, failed)],
                         ["running", "running", "running", "failed"])
        self.holder(SESSION_B)
        with self.read_only():
            outcome = self.open_check()
        self.assertFalse(outcome.writing)
        self.assertEqual(outcome.interrupted, ())
        self.holder(SESSION)
        with self.read_only():
            outcome = self.open_check()
        self.assertEqual([item.uid for item in outcome.interrupted], [other.uid, job.uid])
        self.assertEqual(self.full_state(), before)


class InputsTest(ChecksCase):
    def test_changed_and_kept_inputs_are_prefiltered_again(self) -> None:
        """RF-008-09, RF-008-12, RF-008-13: al abrir se comprueban por su tamaño y su fecha
        todas las entradas activas, también las cambiadas sin decidir y las que mantienen la
        copia: mientras su fuente siga como se vio, nada salta; si vuelve a cambiar
        («Limites_v1», cambiada, vuelve al contenido registrado con otra fecha; «planos»,
        mantenida, cambia otra vez), quedan para el hash del paso 7, sin hashear nada ni
        escribir nada ni tocar las fuentes. Una fuente que falta es «no localizable», con su
        aviso, y no se hashea."""
        (self.sources / "plano.dxf").write_bytes(b"dxf")
        (self.sources / "plano.txt").write_bytes(b"txt")
        for name in ("plano.dxf", "plano.txt"):
            os.utime(self.sources / name, ns=(MTIME_NS, MTIME_NS))
        plans = self.plans()
        registered_v1 = self.target.read_bytes()
        self.replace(data.BOUNDARY_V2)
        self.assertEqual(self.run_check().changed[0].input_uid, self.record.uid)
        self.detect(plans.uid, hashing.sha256_bytes(b"planos vistos"))
        self.write(lambda conn: inputs_registry.keep_copy(conn, self.project, plans.uid))
        self.assertEqual([self.input_row(uid)["status"] for uid in (self.record.uid, plans.uid)],
                         ["changed", "kept"])
        with self.never_hashed():
            outcome = self.open_check()
        self.assertEqual({item.name: (item.before, item.verdict) for item in outcome.inputs},
                         {"Limites_v1": (InputStatus.CHANGED, InputVerdict.UNCHANGED),
                          "planos": (InputStatus.KEPT, InputVerdict.UNCHANGED)})
        self.assertEqual(outcome.input_probes, ())
        self.target.write_bytes(registered_v1)
        self.set_mtime(self.target, step=5)
        (self.sources / "plano.txt").write_bytes(b"txt, otra vez")
        age_folders(self.sources)
        before = self.full_state()
        with assert_source_untouched(self.sources), self.never_hashed():
            outcome = self.open_check()
        self.assertEqual(self.full_state(), before)
        self.assertEqual(outcome.inputs, ())
        self.assertEqual(
            {item.record.name: (item.record.status, item.moved, item.needs_hash)
             for item in outcome.input_probes},
            {"Limites_v1": (InputStatus.CHANGED, True, True),
             "planos": (InputStatus.KEPT, True, True)},
        )
        (self.sources / "plano.dxf").unlink()
        with self.never_hashed():
            outcome = self.open_check()
        (found,) = [item for item in outcome.inputs if item.name == "planos"]
        self.assertEqual((found.verdict, found.file), (InputVerdict.UNREACHABLE, "plano.dxf"))
        self.assertIn(UNREACHABLE, outcome.warnings)
        self.assertEqual(outcome.checked_inputs, (plans.uid,))


class DatasetsTest(ChecksCase):
    def test_tables_against_the_photo(self) -> None:
        """RF-008-21, RF-008-57 (ADR-0025 §4; plan §5.4.6, I-5): antes de abrir, QGIS edita
        ``res_contorno`` y ``res_area``, borra la capa ``res_bocas`` y rehace ``res_limites`` (lo
        importado) sin sus disparadores. Después de la foto, esta sesión vuelve a calcular
        ``res_area``: no se toma por edición externa (queda para la próxima). ``res_contorno``
        queda para el hash del paso 7, ``res_bocas`` falta y ``res_limites`` está dañado, con
        sus avisos. No se lee el contenido de nada ni se escribe nada."""
        self.qgis('UPDATE "res_contorno" SET valor = 9 WHERE codigo = ?', ("C-01",),
                  table="res_contorno", at=EDITED_AT)
        self.qgis('UPDATE "res_area" SET valor = 13', table="res_area", at=EDITED_AT)
        self.foreign('DROP TABLE "res_bocas"')
        self.foreign("DELETE FROM gpkg_contents WHERE table_name = 'res_bocas'")
        self.rebuild("res_limites")
        steps = checks.survey_steps(self.project, self.registries, write=True)
        self.through_photo(steps)
        area = operations.begin_operation(self.project, AREA.op_type, settings={},
                                          executor="blender", supersedes=self.area.uid,
                                          inputs=[Use("res_contorno", "outline")])
        self.write(lambda conn: (conn.execute('UPDATE "res_area" SET valor = 14'),
                                 area.complete(conn, outputs=[_spec("res_area", "area")])))
        before = self.full_state()
        with self.never_hashed():
            outcome, _durations = self.drive(steps)
        self.assertEqual(self.full_state(), before)
        self.assertEqual([(item.record.name, item.signal) for item in outcome.dataset_probes],
                         [("res_contorno", Signal.MOVED)])
        self.assertEqual({item.record.name: (item.verdict, item.status)
                          for item in outcome.datasets},
                         {"res_bocas": (Verdict.MISSING, Status.MISSING),
                          "res_limites": (Verdict.DAMAGED, Status.DAMAGED)})
        self.assertEqual(self.names(outcome.stale), {"res_area"})
        self.assertNotIn(self.uid("res_area"), outcome.checked_datasets)
        self.assertIn(MISSING_TEXT.format(name="res_bocas", locator="res_bocas"),
                      outcome.warnings)
        self.assertIn(DAMAGED_TEXT.format(name="res_limites", input="Limites_v1"),
                      outcome.warnings)

    def test_files_and_originals_against_the_photo(self) -> None:
        """RF-008-21, RF-008-57, RF-008-53 (plan §5.4.6, I-5): los ficheros de ``rasters/`` se
        comparan con el listado de la foto. Otro programa borra ``res_mdt2`` (falta) y cambia la
        fecha de ``res_mdt3`` (en una subcarpeta: queda para el hash del paso 7); el fichero
        que reclama una operación en curso de esta sesión no se mira. Después de la foto, esta
        sesión vuelve a calcular ``res_mdt`` con otro contenido: no se toma por edición externa.
        El original de «Limites_v1» con otra fecha queda para su huella del paso 7 y, si falta,
        se avisa. Un dato ya registrado como «falta» no se vuelve a avisar mientras falte y, si
        vuelve, queda para el hash. No se lee el contenido de nada ni se escribe nada."""
        grid = self.terrain()
        self.file_dataset("res_mdt2", "rasters/res_mdt2.bin", b"rejilla 2")
        self.file_dataset("res_mdt3", "rasters/sub/res_mdt3.bin", b"rejilla 3")
        self.file_dataset("res_mdt4", "rasters/res_mdt4.bin", b"rejilla 4")
        original = self.store_original(self.record.uid, data.BOUNDARY_V1, ORIGINAL)
        self.path("rasters/res_mdt2.bin").unlink()
        self.touch(self.path("rasters/sub/res_mdt3.bin"))
        self.touch(original)
        running = operations.begin_operation(self.project, GRID.op_type, settings={},
                                             executor="blender")
        running.claim_paths(self.path("rasters/res_mdt4.bin"))
        self.path("rasters/res_mdt4.bin").write_bytes(b"rejilla 4, a medias")
        steps = checks.survey_steps(self.project, self.registries, write=True)
        self.through_photo(steps)
        self.path(TERRAIN_FILE).write_bytes(b"rejilla v2, recalculada")
        redo = operations.begin_operation(self.project, GRID.op_type, settings={},
                                          executor="blender", supersedes=grid.uid)
        self.write(lambda conn: redo.complete(conn, outputs=[datasets.DatasetSpec(
            "res_mdt", "res", "raster", "rasters", TERRAIN_FILE, reader=BYTES.id,
            role="terrain")]))
        before = self.full_state()
        with self.never_hashed():
            outcome, _durations = self.drive(steps)
        self.assertEqual(self.full_state(), before)
        self.assertEqual([(item.record.name, item.signal) for item in outcome.dataset_probes],
                         [("res_mdt3", Signal.MOVED)])
        self.assertEqual([(item.record.name, item.verdict) for item in outcome.datasets],
                         [("res_mdt2", Verdict.MISSING)])
        checked = self.names(outcome.checked_datasets)
        self.assertIn("res_mdt", checked)
        self.assertNotIn("res_mdt4", checked)
        self.assertEqual(outcome.stale, ())
        path = f"originals/{self.record.uid}/{data.BOUNDARY_V1}"
        stored = original.stat()
        self.assertEqual(
            [(item.input_uid, item.name, item.path, item.file, item.seen, item.needs_hash)
             for item in outcome.original_probes],
            [(self.record.uid, "Limites_v1", path, data.BOUNDARY_V1,
              (stored.st_size, stored.st_mtime_ns), True)],
        )
        self.assertEqual(outcome.originals, ())
        original.unlink()
        with self.never_hashed():
            outcome = self.open_check()
        self.assertEqual(outcome.original_probes, ())
        self.assertEqual([(item.path, item.verdict) for item in outcome.originals],
                         [(path, OriginalVerdict.MISSING)])
        self.assertIn(f"Falta el original «{data.BOUNDARY_V1}» de la entrada «Limites_v1» en "
                      "el proyecto: no sirve para reimportar.", outcome.warnings)
        # lo que ya se registró que falta sigue faltando sin otro aviso; si vuelve, salta
        self.write(lambda conn: external.mark_missing(conn, self.project, self.uid("res_mdt2")))
        with self.never_hashed():
            outcome = self.open_check()
        self.assertNotIn("res_mdt2", {item.record.name for item in outcome.datasets})
        self.assertIn("res_mdt2", self.names(outcome.checked_datasets))
        back = self.path("rasters/res_mdt2.bin")
        back.write_bytes(b"rejilla 2")  # vuelve igual: su tamaño y su fecha, los anotados
        tracked = self.dataset("res_mdt2")
        self.assertEqual(tracked.tracked_size, back.stat().st_size)
        os.utime(back, ns=(tracked.tracked_mtime_ns, tracked.tracked_mtime_ns))
        with self.never_hashed():
            outcome = self.open_check()
        self.assertIn(("res_mdt2", Signal.MOVED),
                      [(item.record.name, item.signal) for item in outcome.dataset_probes])


class OrphansTest(ChecksCase):
    def test_leftovers_set_aside_and_foreign_items_listed(self) -> None:
        """RF-008-22, RF-008-62 (plan §5.4.6, I-5): un fichero con nombre de Geoblender que
        no es de ningún dato se aparta a ``orphans/`` al abrir en escritura (nunca se borra; su
        evento lo escribe la transacción final, T37); uno escrito después de empezar o el de un
        dato (aunque sea antiguo), no. Un
        fichero ajeno y una tabla creada desde QGIS se avisan con su lista sin moverse. En solo
        lectura, o sin ``write``, solo se avisa."""
        self.file_dataset("res_mdt", TERRAIN_FILE, b"rejilla", mtime_ns=BASE_NS)  # de un dato
        leftover = self.path("rasters/res_resto.bin")
        foreign = self.path("rasters/notas.txt")
        recent = self.path("rasters/res_nuevo.bin")
        for path in (leftover, foreign):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")
            os.utime(path, ns=(BASE_NS, BASE_NS))
        recent.write_bytes(b"y")
        self.foreign("CREATE TABLE capa_qgis (fid INTEGER PRIMARY KEY, a TEXT)")
        for chosen, write in ((self.read_only(), True), (contextlib.nullcontext(), False)):
            with chosen:
                outcome = self.open_check(write=write)
            self.assertEqual([item.path for item in outcome.orphans.found],
                             ["rasters/res_resto.bin"])
            self.assertEqual(outcome.orphans.moved, ())
            self.assertEqual([item.name for item in outcome.orphans.foreign],
                             ["rasters/notas.txt", "capa_qgis"])
            self.assertTrue(leftover.exists())
            self.assertFalse(self.path("orphans").exists())
        before = self.full_state()
        outcome = self.open_check()
        self.assertEqual(self.full_state(), before)
        self.assertFalse(outcome.orphans.recorded)
        (moved,) = outcome.orphans.moved
        self.assertEqual(moved.path, "rasters/res_resto.bin")
        self.assertRegex(moved.moved_to,
                         r"^orphans/\d{8}T\d{6}Z_[0-9a-f]{8}/rasters/res_resto\.bin$")
        self.assertFalse(leftover.exists())
        self.assertEqual(self.path(moved.moved_to).read_bytes(), b"x")
        self.assertTrue(foreign.exists() and recent.exists() and self.path(TERRAIN_FILE).exists())
        self.assertEqual([item.name for item in outcome.orphans.foreign],
                         ["rasters/notas.txt", "capa_qgis"])
        self.assertTrue(any(text.startswith("Restos de operaciones interrumpidas apartados")
                            for text in outcome.warnings))


class VersionsTest(ChecksCase):
    def test_newer_algorithm_version_warns_with_its_results(self) -> None:
        """RF-008-24 (spec §8: «Geoblender 0.3.0 cambia el algoritmo de gis.resample (1.0 →
        1.1): 3 resultados obsoletos»): con un Geoblender que declara «res.grid» 1.1 y
        «res.area» 2.0, se avisa de cada tipo con los datos vivos cuyo contenido escribieron sus
        operaciones vigentes (las dos de «res.grid»: ``res_mdt``, porque ``res_cotas`` lo volvió a
        escribir después una de «res.area»; las dos de «res.area»: ``res_area`` y ``res_cotas``),
        en español y en inglés, sin escribir nada. La misma versión o una menor no avisan, y
        una vez en la caché (la obsolescencia completa del paso 8) no se repite."""
        self.terrain()
        self.levels()
        self.levels(AREA.op_type, value=2.0)
        version = SESSION.geoblender_version
        newer = checks.Registries({**self.registries.versions, GRID.op_type: "1.1",
                                   AREA.op_type: "2.0"}, self.registries.definitions)
        before = self.full_state()
        outcome = self.open_check(registries=newer)
        self.assertEqual(self.full_state(), before)
        self.assertEqual(
            [(item.op_type, item.registered, item.installed, item.geoblender_version,
              item.operations, item.results) for item in outcome.algorithms],
            [(AREA.op_type, "1.0", "2.0", version, 2, 2),
             (GRID.op_type, "1.0", "1.1", version, 2, 1)],
        )
        texts = [f"Geoblender {version} cambia el algoritmo de res.area (1.0 → 2.0): 2 "
                 "resultados obsoletos",
                 f"Geoblender {version} cambia el algoritmo de res.grid (1.0 → 1.1): 1 "
                 "resultado obsoleto"]
        self.assertEqual([item.text() for item in outcome.algorithms], texts)
        self.assertEqual(list(outcome.warnings[-2:]), texts)
        self.assertEqual(outcome.algorithms[0].text("en"),
                         f"Geoblender {version} changes the algorithm of res.area (1.0 → 2.0): "
                         "2 stale results")
        for same in (self.registries,
                     checks.Registries({**self.registries.versions, GRID.op_type: "0.9"},
                                       self.registries.definitions)):
            self.assertEqual(self.open_check(registries=same).algorithms, ())
        self.write(lambda conn: stale_mod.refresh_all(conn, now=self.later(),
                                                      versions=newer.versions))
        self.assertEqual(self.open_check(registries=newer).algorithms, ())


class DefinitionsTest(ChecksCase):
    def test_changed_parameter_definitions_are_found_without_writing(self) -> None:
        """RF-008-60: con un Geoblender que declara ``res.density`` en kg/m³ (otra unidad,
        otro rango y otro valor por defecto) y ya no declara ``res.swell_factor``, los dos se
        encuentran con su cambio para «revisar» y su aviso, sin escribir nada ni tocar ningún
        valor; es lo que marcará la transacción final y, una vez marcados, no se vuelven a
        encontrar."""
        params.register_definitions((DENSITY, SWELL))
        self.addCleanup(params.unregister_definitions, "res")
        store = params.ParameterStore(self.project)

        def add(conn: Any) -> None:
            for key in (DENSITY.key, SWELL.key):
                store.ensure_default(conn, key, geoblender_version="0.3.0")

        self.write(add)
        declared = {key: defn for key, defn in params.DEFINITIONS.items() if key != SWELL.key}
        declared[DENSITY.key] = DENSITY_KG
        changed = checks.Registries(self.registries.versions, declared)
        current = checks.Registries.installed()
        self.assertEqual(self.open_check(registries=current).definitions, ())
        before = self.full_state()
        outcome = self.open_check(registries=changed)
        self.assertEqual(self.full_state(), before)
        self.assertEqual(
            [(item.key, item.review["declared"] and item.review["declared"]["unit"])
             for item in outcome.definitions],
            [(DENSITY.key, "kg/m3"), (SWELL.key, None)],
        )
        for item in outcome.definitions:
            self.assertIn(item.text, outcome.warnings)
        self.assertIn("res.density", outcome.definitions[0].text)
        written = self.write(lambda conn: store.mark_definition_changes(conn, declared))
        self.assertEqual(written, list(outcome.definitions))
        self.assertEqual(self.open_check(registries=changed).definitions, ())


class ApiTest(ChecksCase):
    def test_public_api_registries_and_arguments(self) -> None:
        """RF-008-58 (plan §5.1, §5.3.1): ``core.provenance`` reexporta la comprobación de
        apertura al usarla (importar el paquete no la carga). ``Registries.installed()`` es una
        foto de lo registrado (lo que se registre después no cambia); una versión que no es
        «M.m» o una definición que no es ``ParamDef`` se rechazan. ``write`` es verdadero o
        falso, el presupuesto un número positivo y los registros, ``Registries``; un proyecto
        sin la procedencia (esquema 1) no tiene nada que comprobar."""
        for name in provenance.CHECKS_API:
            with self.subTest(name=name):
                self.assertIn(name, provenance.__all__)
                self.assertIn(name, dir(provenance))
                self.assertIs(getattr(provenance, name), getattr(checks, name))
        tree = ast.parse(Path(provenance.__file__).read_text(encoding="utf-8"))
        imported = {alias.name for node in tree.body if isinstance(node, ast.ImportFrom)
                    for alias in node.names} | {node.module for node in tree.body
                                                if isinstance(node, ast.ImportFrom)}
        self.assertNotIn("checks", imported)
        snapshot = checks.Registries.installed()
        later = provenance.OperationDef("res.later", "1.0", "res", "Test later", False)
        with registered(later):
            self.assertNotIn("res.later", snapshot.versions)
            self.assertIn("res.later", checks.Registries.installed().versions)
        self.assertEqual(snapshot.versions[GRID.op_type], "1.0")
        with self.assertRaises(TypeError):
            snapshot.versions["res.x"] = "1.0"  # type: ignore[index]
        with self.assertRaises(ValueError):
            checks.Registries({"res.grid": "1"}, {})
        with self.assertRaises(TypeError):
            checks.Registries({"res.grid": "1.0"}, {"res.density": "t/m3"})
        with self.assertRaises(ValueError):
            checks.Registries({}, {"res.otra": DENSITY})
        for bad in ({"write": None}, {"write": 1}, {"budget_s": 0}, {"budget_s": "0.02"}):
            with self.subTest(bad=bad), self.assertRaises((TypeError, ValueError)):
                kw = {"write": True, **bad}
                checks.open_check_steps(self.project, self.registries, **kw)
        with self.assertRaises(TypeError):
            checks.open_check_steps(self.project, {"res.grid": "1.0"}, write=True)
        found = list(checks.open_check_steps(self.project, write=False))
        self.assertIsInstance(found[-1].result, checks.OpenCheckOutcome)
        probe = checks.OriginalProbe("u", "Limites_v1", 0, "originals/u/a.csv", "0" * 64, 3, 7,
                                     (3, 7))
        self.assertEqual((probe.file, probe.needs_hash), ("a.csv", False))
        self.assertTrue(dataclasses.replace(probe, seen=(3, 8)).needs_hash)
        self.assertFalse(dataclasses.replace(probe, seen=None).needs_hash)
        with mock.patch.object(type(self.project), "schema_version", property(lambda _s: 1)):
            (only,) = self.steps()
        self.assertEqual((only.done, only.total), (checks.PROGRESS_TOTAL, checks.PROGRESS_TOTAL))
        self.assertEqual(self.summary(only.result)[:9], ((), [], [], [], [], [], [], [], []))


# --- Pasos 7 y 8 (T37) ------------------------------------------------------------------------


class FakeJobs:
    """Los trabajos de hash que pone ``bl`` (T47), simulados: anotan lo que se les pide y, tras
    ``waits`` consultas sin terminar, lo hashean con el lector registrado (como el trabajo) o
    devuelven ``result``; con ``refuse``, no se pueden lanzar."""

    def __init__(self, waits: int = 1, *, result: Any = None, refuse: bool = False) -> None:
        self.waits = waits
        self.result = result
        self.refuse = refuse
        self.submitted: list[Any] = []
        self.polls = 0
        self.cancelled: list[int] = []

    def submit(self, request: Any) -> int | None:
        self.submitted.append(request)
        return None if self.refuse else len(self.submitted)

    def poll(self, ticket: int) -> Any:
        self.polls += 1
        if self.polls <= self.waits:
            return None
        if self.result is not None:
            return self.result
        request = self.submitted[ticket - 1]
        found = readers.reader(request.reader)
        read = found.request(request.kind, request.declarations, dict(request.files),
                             dict(request.settings), normalizer=request.normalizer)
        return checks.HashResult(readers.read_content(found, read))

    def cancel(self, ticket: int) -> None:
        self.cancelled.append(ticket)


class FinalTest(ChecksCase):
    def test_hashes_and_records_everything_in_one_final_transaction(self) -> None:
        """RF-008-58, RF-008-09, RF-008-19, RF-008-21, RF-008-22, RF-008-24, RF-008-57,
        RF-008-60 (plan §5.4.6, pasos 7 y 8): con un cambio de cada clase antes de abrir, la
        comprobación corre sus ocho pasos en orden con su progreso hasta el 100 %; hashea lo
        que saltó (la fuente de «Limites_v1», ``res_contorno``) y registra todo en **una**
        transacción final: la operación del Blender que se cerró, interrumpida; «Limites_v1»,
        cambiada (con el contenido visto); la edición externa de ``res_contorno``;
        ``res_bocas``, que falta; el evento de los restos apartados; «revisar» en
        ``res.density`` y los eventos de la definición y del algoritmo; y la caché con la
        obsolescencia completa (``res_area``, obsoleto). La fuente queda intacta. Una segunda
        apertura no encuentra nada nuevo ni repite ningún evento."""
        newer = self.changes()
        age_folders(self.sources)
        real = self.project.write_transaction
        transactions: list[int] = []

        def counting() -> Any:
            transactions.append(1)
            return real()

        with assert_source_untouched(self.sources), \
                mock.patch.object(self.project, "write_transaction", counting):
            outcome, found = self.check_all(registries=newer)
        self.assertEqual(len(transactions), 1)
        phases = [step.phase for step in found]
        self.assertEqual(list(dict.fromkeys(phases)), list(checks.OPEN_CHECK_STEPS))
        self.assertEqual(checks.OPEN_CHECK_STEPS,
                         (*checks.SURVEY_STEPS, "contenido", "registro"))
        done = [step.done for step in found]
        self.assertEqual(done, sorted(done))
        self.assertEqual(found[-1].message, "Comprobando el proyecto… 100 %")
        self.assertRecorded(outcome, newer)
        self.assertEqual({item.name: item.verdict for item in outcome.inputs},
                         {"Limites_v1": InputVerdict.CHANGED})
        (missing, edited) = sorted(outcome.datasets, key=lambda item: item.record.name)
        self.assertEqual((edited.record.name, edited.verdict, edited.operation_uid),
                         ("res_contorno", Verdict.EDITED, self.external_edits()[0]["uid"]))
        self.assertEqual((missing.record.name, missing.verdict), ("res_bocas", Verdict.MISSING))
        self.assertEqual((outcome.input_probes, outcome.dataset_probes, outcome.original_probes),
                         ((), (), ()))
        self.assertIn(self.uid("res_contorno"), outcome.checked_datasets)
        self.assertEqual([item.key for item in outcome.definitions], [DENSITY.key])
        self.assertTrue(any(text.startswith("La entrada «Limites_v1» ha cambiado")
                            for text in outcome.warnings))
        events = self.rows("gb_event")
        again, _steps = self.check_all(registries=newer)
        self.assertEqual(self.rows("gb_event"), events)
        self.assertEqual((again.inputs[0].verdict, again.datasets, again.algorithms,
                          again.definitions, again.interrupted),
                         (InputVerdict.UNCHANGED, (), (), (), ()))

    def test_busy_database_retries_without_losing_anything(self) -> None:
        """RF-008-58 (plan §5.4.6, D22; I-7): con QGIS leyendo el proyecto, la transacción
        final devuelve el control enseguida con «… reintentando…» sin escribir nada, y se
        reintenta en el paso siguiente; cuando termina de leer, se registra todo lo encontrado
        (nada se pierde)."""
        newer = self.changes()
        before = self.full_state()
        reader = sqlite3.connect(self.project.database_path, isolation_level=None)
        self.addCleanup(reader.close)
        reader.execute("BEGIN")
        reader.execute("SELECT count(*) FROM gb_event").fetchone()
        steps = checks.open_check_steps(self.project, newer, write=True)
        busy = self.until(steps, lambda step: step.message == session_mod.BUSY_MESSAGE)[-1]
        self.assertEqual((busy.phase, busy.result), ("registro", None))
        self.assertEqual(self.full_state(), before)
        reader.execute("COMMIT")
        reader.close()
        rest = list(steps)  # el paso siguiente la reintenta (y el otro da el resultado, T65)
        self.assertNotIn(session_mod.BUSY_MESSAGE, [step.message for step in rest])
        self.assertEqual(len(rest), 2)
        self.assertRecorded(rest[-1].result, newer)

    def test_read_only_reports_everything_and_records_it_when_writable(self) -> None:
        """RF-008-58, RF-008-22 (plan §5.4.6): en solo lectura (o sin ``write``) se detecta
        todo —también lo que hay que hashear— y no cambia ni un byte del proyecto ni de la
        fuente (no se aparta nada): queda el informe con sus avisos, en español y en inglés.
        Al abrir después en escritura, todo se vuelve a detectar y se registra."""
        newer = self.changes()
        for chosen, write in ((contextlib.nullcontext(), False), (self.read_only(), True)):
            age_folders(self.project.root)
            age_folders(self.sources)
            with assert_source_untouched(self.project.root), \
                    assert_source_untouched(self.sources), chosen:
                outcome, _steps = self.check_all(registries=newer, write=write)
        self.assertEqual((outcome.writing, outcome.recorded, outcome.cache), (False, False, None))
        self.assertEqual([item.uid for item in outcome.interrupted], [self.other.uid])
        (changed,) = outcome.inputs
        self.assertEqual((changed.verdict, changed.status, changed.content_sha256),
                         (InputVerdict.CHANGED, InputStatus.CHANGED, self.content_of(self.target)))
        self.assertIn("res_area", [item.name for item in changed.dependents.datasets])
        self.assertEqual({item.record.name: (item.verdict, item.operation_uid)
                          for item in outcome.datasets},
                         {"res_contorno": (Verdict.EDITED, None),
                          "res_bocas": (Verdict.MISSING, None)})
        self.assertEqual([item.path for item in outcome.orphans.found],
                         ["rasters/res_resto.bin"])
        self.assertEqual([item.op_type for item in outcome.algorithms], [AREA.op_type])
        self.assertEqual([item.key for item in outcome.definitions], [DENSITY.key])
        texts = outcome.warnings
        for expected in (outcome.interrupted[0].text(), changed.warning,
                         outcome.datasets[0].text(), outcome.datasets[1].text(),
                         outcome.algorithms[0].text(), outcome.definitions[0].text):
            self.assertIn(expected, texts)
        self.assertEqual(len(outcome.texts("en")), len(texts))
        self.assertEqual(self.input_row(self.record.uid)["status"], "current")
        self.assertEqual(self.external_edits(), [])
        outcome, _steps = self.check_all(registries=newer)
        self.assertRecorded(outcome, newer)

    def test_full_staleness_repairs_a_cache_altered_by_hand(self) -> None:
        """RF-008-24, RF-008-58 (plan §5.4.6, paso 8): la obsolescencia completa de la
        transacción final corrige una caché alterada a mano (una fila de menos y una de más)
        y deja la de lo deducido; sin cambios, no escribe ninguna fila."""
        self.qgis('UPDATE "res_contorno" SET valor = 9 WHERE codigo = ?', ("C-01",),
                  table="res_contorno", at=EDITED_AT)
        self.check_all()
        self.assertCacheDeduced(None)
        (row,) = [item for item in self.read(stale_mod.cached_rows)
                  if item.item_uid == self.uid("res_area")]
        self.write(lambda conn: (
            conn.execute("DELETE FROM gb_stale WHERE item_kind = ? AND item_uid = ? AND "
                         "cause_kind = ? AND subject_uid = ?", tuple(row)),
            conn.execute("INSERT INTO gb_stale (item_kind, item_uid, cause_kind, subject_uid, "
                         "since) VALUES ('dataset', ?, 'algorithm', 'res.grid', ?)",
                         (self.uid("res_limites"), self.later()))))
        outcome, _steps = self.check_all()
        self.assertEqual((len(outcome.cache.added), len(outcome.cache.removed)), (1, 1))
        self.assertCacheDeduced(None)
        outcome, _steps = self.check_all()
        self.assertEqual((outcome.cache.added, outcome.cache.removed),
                         (frozenset(), frozenset()))

    def test_many_datasets_hold_many_objects(self) -> None:
        """RNF-008-12 (T65): la comprobación de apertura guarda muchos objetos entre pasos (y
        quien la lleva hace antes una recolección completa del GC de Python) desde
        ``MANY_DATASETS`` datos registrados: no con los del proyecto de prueba; sí con el
        límite en los que tiene, y no un dato por encima."""
        self.assertFalse(checks.holds_many_objects(self.project))
        last = self.read(lambda conn: conn.execute("SELECT MAX(fid) FROM gb_dataset").fetchone()[0])
        for limit, many in ((last, True), (last + 1, False)):
            with mock.patch.object(checks, "MANY_DATASETS", limit):
                self.assertEqual(checks.holds_many_objects(self.project), many)

    def final_statements(self) -> tuple[Any, list[str]]:
        """La comprobación de apertura entera (en escritura): su resultado y las sentencias SQL
        de su transacción final."""
        real = self.project.try_write
        statements: list[str] = []

        def traced(work: Callable[[sqlite3.Connection], Any]) -> Any:
            def spied(conn: sqlite3.Connection) -> Any:
                conn.set_trace_callback(statements.append)
                try:
                    return work(conn)
                finally:
                    conn.set_trace_callback(None)
            return real(spied)

        with mock.patch.object(self.project, "try_write", traced):
            outcome, _steps = self.check_all()
        return outcome, statements

    def test_final_transaction_only_writes_the_difference(self) -> None:
        """RF-008-58, RNF-008-12 (plan §5.4.6, paso 8; T65): la obsolescencia completa se
        calcula en pasos anteriores, leyendo sin escribir; la transacción final no lee el grafo
        ni la caché y escribe solo la diferencia: con una caché alterada a mano, borra la fila
        que sobra y añade la que falta, y queda la de lo deducido; sin nada que cambiar, no toca
        la caché."""
        self.qgis('UPDATE "res_contorno" SET valor = 9 WHERE codigo = ?', ("C-01",),
                  table="res_contorno", at=EDITED_AT)
        self.check_all()
        (row,) = [item for item in self.read(stale_mod.cached_rows)
                  if item.item_uid == self.uid("res_area")]
        self.write(lambda conn: (
            conn.execute("DELETE FROM gb_stale WHERE item_kind = ? AND item_uid = ? AND "
                         "cause_kind = ? AND subject_uid = ?", tuple(row)),
            conn.execute("INSERT INTO gb_stale (item_kind, item_uid, cause_kind, subject_uid, "
                         "since) VALUES ('dataset', ?, 'algorithm', 'res.grid', ?)",
                         (self.uid("res_limites"), self.later()))))
        outcome, statements = self.final_statements()
        self.assertTrue(outcome.recorded)
        self.assertEqual([text for text in statements if GRAPH_READ.search(text)], [])
        written = list(dict.fromkeys(text for text in statements if CACHE_WRITE.search(text)))
        self.assertEqual([text.split()[0] for text in written], ["DELETE", "INSERT"], written)
        self.assertIn(self.uid("res_limites"), written[0])
        self.assertIn(self.uid("res_area"), written[1])
        self.assertCacheDeduced(None)
        outcome, statements = self.final_statements()
        self.assertEqual((outcome.cache.added, outcome.cache.removed), (frozenset(), frozenset()))
        self.assertEqual([text for text in statements
                          if GRAPH_READ.search(text) or CACHE_WRITE.search(text)], [])


class OpenCacheTest(DemoProjectTestCase):
    """La comprobación de apertura con la demostración: la obsolescencia completa por pasos y la
    diferencia en la transacción final (T65), frente a la transacción final de antes sobre la
    misma base (``tests.support.open_check.as_before``)."""

    def base(self) -> None:
        """La cadena de la demostración y, antes de abrir, un cambio de cada clase: la
        producción cambia (lo que la lee, obsoleto), QGIS edita ``demo_marks``, la propiedad
        entrega otro límite con el mismo nombre, alguien altera la caché a mano (una fila de
        menos y una de más) y el Geoblender que abre declara «demo.area» y
        «demo.detect_stockpiles» 2.0 (la segunda lee las marcas). Guarda la base y el reloj."""
        self.chain()
        self.change(demo_support.PRODUCTION, 400_000.0)
        qgis = sqlite3.connect(self.project.database_path, isolation_level=None)
        try:
            qgis.execute(f'UPDATE "{demo_support.MARKS_TABLE}" SET bank_m3 = bank_m3 + 10 '
                         "WHERE fid = 1")
            qgis.execute("UPDATE gpkg_contents SET last_change = ? WHERE table_name = ?",
                         (EDITED_AT, demo_support.MARKS_TABLE))
        finally:
            qgis.close()
        with self.project.write_transaction() as conn:
            row = conn.execute("SELECT item_kind, item_uid, cause_kind, subject_uid FROM gb_stale "
                               "WHERE item_kind = 'dataset' ORDER BY rowid LIMIT 1").fetchone()
            conn.execute("DELETE FROM gb_stale WHERE item_kind = ? AND item_uid = ? AND "
                         "cause_kind = ? AND subject_uid = ?", row)
            conn.execute("INSERT INTO gb_stale (item_kind, item_uid, cause_kind, subject_uid, "
                         "since) SELECT 'dataset', uid, 'algorithm', 'demo.area', "
                         "'2026-10-08T10:00:00.000Z' FROM gb_dataset ORDER BY fid LIMIT 1")
        self.deliver(data.BOUNDARY_V2)
        self.registries = checks.Registries(
            {**checks.Registries.installed().versions, demo_support.AREA: "2.0",
             demo_support.DETECT_STOCKPILES: "2.0"},
            params.DEFINITIONS)
        self.saved = self.tmp / "base.gpkg"
        shutil.copyfile(self.project.database_path, self.saved)
        self.moment = (self.clock._now, self.clock._monotonic)

    def change(self, key: str, value: float) -> None:
        """Cambia el parámetro ``key`` del proyecto (con su caché por región)."""
        store = params.ParameterStore(self.project)
        with self.project.write_transaction() as conn:
            store.change(conn, key, value=value, kind="ADOPTADO", source="Plan de labores 2027",
                         source_kind="document", decided_by="la propiedad",
                         reason="Prueba de la comprobación")

    def checked(self, *, reference: bool = False,
                change: Callable[[], None] | None = None,
                when: str = "") -> tuple[Any, dict[str, list[Any]], tuple[int, int]]:
        """La comprobación de apertura entera sobre la base guardada, con el mismo reloj, los
        mismos uid nuevos y cada unidad de trabajo en su paso (un presupuesto mínimo); con
        ``reference``, la transacción final de antes. ``change`` es un
        cambio del proyecto que se hace ``when``: «calculando», en el segundo paso del registro
        (en la referencia, que no calcula nada, en el primero); «escribiendo», al empezar la
        primera transacción final. Devuelve el resultado, las filas de la base y cuántas veces
        se calculó la obsolescencia completa y se intentó la transacción final."""
        shutil.copyfile(self.saved, self.project.database_path)
        self.clock._now, self.clock._monotonic = self.moment
        real = self.project.try_write
        pending = [change] if change is not None else []
        attempts: list[int] = []

        def writing(work: Callable[[sqlite3.Connection], Any]) -> Any:
            attempts.append(1)
            if when == "escribiendo" and pending:
                pending.pop()()
            return real(work)

        with contextlib.ExitStack() as stack:
            stack.enter_context(open_check.same_uids())
            stack.enter_context(mock.patch.object(self.project, "try_write", writing))
            computed = stack.enter_context(mock.patch.object(
                checks, "full_difference_steps", wraps=stale_mod.full_difference_steps))
            if reference:
                stack.enter_context(open_check.as_before())
            recording = 0
            outcome = None
            for step in checks.open_check_steps(self.project, self.registries, write=True,
                                                budget_s=1e-9):
                if step.phase == checks.RECORD_STEP:
                    recording += 1
                    if (when == "calculando" and pending
                            and recording == (1 if reference else 2)):
                        pending.pop()()
                if step.result is not None:
                    outcome = step.result
        self.assertEqual(pending, [])
        return (outcome, open_check.project_rows(self.project),
                (computed.call_count, len(attempts)))

    def assertSameAsBefore(self, change: Callable[[], None] | None = None,
                           when: str = "") -> tuple[int, int]:
        """La comprobación da, fila a fila, la misma base y los mismos avisos que la de antes
        sobre la misma base (y con el mismo cambio en el mismo momento), y su caché es la
        obsolescencia completa deducida; devuelve cuántas veces se calculó y se intentó la
        transacción final."""
        outcome, rows, done = self.checked(change=change, when=when)
        expected, reference, _done = self.checked(reference=True, change=change, when=when)
        self.assertTrue(outcome.recorded and expected.recorded)
        self.assertEqual(outcome.texts("es"), expected.texts("es"))
        for table in sorted(reference):
            self.assertEqual(rows[table], reference[table], table)
        self.assertEqual(rows.keys(), reference.keys())
        with self.project.read() as conn:
            state = graph_mod.deduce(graph_mod.load_graph(conn),
                                     versions=self.registries.versions)
            self.assertEqual(stale_mod.cached_rows(conn), stale_mod.expected_rows(state))
        return done

    def test_same_cache_and_states_as_the_full_refresh(self) -> None:
        """RF-008-58, RF-008-24, RNF-008-12 (plan §5.4.6, paso 8; T65): con la demostración y
        un cambio de cada clase antes de abrir (un parámetro, una edición de QGIS, otro límite
        entregado, una caché alterada a mano y un algoritmo más nuevo), la obsolescencia
        completa por pasos y su diferencia en la transacción final dejan la caché (con sus
        fechas) y todo lo demás de la base idéntico, fila a fila, a lo que dejaba la
        transacción final con la completa al final, con los mismos avisos; se calcula una
        vez."""
        self.base()
        self.assertEqual(self.assertSameAsBefore(), (1, 1))
        rows = open_check.project_rows(self.project)
        external = [row for row in rows["gb_operation"] if contract.EXTERNAL_EDIT in row]
        self.assertEqual(len(external), 1)  # QGIS editó las marcas
        self.assertIn("algorithm", {row[2] for row in rows["gb_stale"]})

    def test_a_change_while_computing_or_before_writing_is_not_lost(self) -> None:
        """RF-008-58, RNF-008-12 (plan §5.4.6, paso 8; I-5, I-7; T65): si el proyecto cambia
        mientras se calcula la obsolescencia completa (la propia sesión cambia un parámetro) o
        entre el cálculo y la escritura (justo antes de la transacción final; la producción
        vuelve al valor que leyeron, y lo que dejaba obsoleto deja de estarlo), no se escribe
        nada calculado sobre la otra base: se vuelve a calcular (mientras se calcula, sin
        acabar el cálculo ni intentar la transacción; antes de escribir, sin escribir nada en
        ella) y lo que queda es, fila a fila, lo de la transacción final de antes con el mismo
        cambio en el mismo momento."""
        self.base()
        for when, key, value, attempts in (
                ("calculando", demo_support.SWELL_FACTOR, 1.3, 1),
                ("escribiendo", demo_support.PRODUCTION, 500_000.0, 2)):
            with self.subTest(when=when):
                done = self.assertSameAsBefore(
                    lambda key=key, value=value: self.change(key, value), when)
                self.assertEqual(done, (2, attempts))


class PendingTest(ChecksCase):
    def test_check_state_keeps_pending_what_is_not_checked_yet(self) -> None:
        """RF-008-58 (plan §5.4.5 y §5.4.6): mientras dura la comprobación, ``CheckState``
        deja como pendiente lo que aún no ha comprobado: todo al empezar; tras el prefiltro,
        solo lo que espera su hash o su registro (``res_contorno`` y «Limites_v1»), así que la
        puerta espera («Comprobando el proyecto…») para lo que depende de ello y no para lo
        demás (ni para la entrada «planos», sin cambios). Al terminar, nada queda pendiente, los
        hashes que había pedido la puerta están hechos y la puerta ve lo registrado."""
        for name in ("plano.dxf", "plano.txt"):
            (self.sources / name).write_bytes(name.encode("ascii")[-3:])
            os.utime(self.sources / name, ns=(MTIME_NS, MTIME_NS))
        plans = self.plans()
        self.replace(data.BOUNDARY_V2)
        self.qgis('UPDATE "res_contorno" SET valor = 9 WHERE codigo = ?', ("C-01",),
                  table="res_contorno", at=EDITED_AT)
        asked = gate.PendingItem(ItemKind.DATASET, self.uid("res_area"), "res_area",
                                 gate.PendingReason.HASHING)
        self.state.request_hash(asked)
        steps = checks.open_check_steps(self.project, self.registries, write=True,
                                        pending=self.state)
        self.assertFalse(self.state.running)
        next(steps)
        self.assertTrue(self.state.running)
        for kind, uid in ((ItemKind.INPUT, self.record.uid), (ItemKind.INPUT, plans.uid),
                          (ItemKind.DATASET, self.uid("res_area"))):
            self.assertTrue(self.state.is_pending(kind, uid))
        self.until(steps, lambda step: step.phase == "contenido")
        self.assertTrue(self.state.is_pending(ItemKind.INPUT, self.record.uid))
        self.assertFalse(self.state.is_pending(ItemKind.INPUT, plans.uid))
        self.assertTrue(self.state.is_pending(ItemKind.DATASET, self.uid("res_contorno")))
        for name in ("res_area", "res_limites", "res_bocas"):
            self.assertFalse(self.state.is_pending(ItemKind.DATASET, self.uid(name)), name)
        result = self.can_run(Use("res_contorno", "outline"))
        self.assertIsInstance(result, gate.Pending)
        self.assertEqual({(item.name, item.reason) for item in result.items},
                         {("res_contorno", gate.PendingReason.CHECKING),
                          ("Limites_v1", gate.PendingReason.CHECKING)})
        self.assertIsNotNone(list(steps)[-1].result)
        self.assertFalse(self.state.running)
        self.assertEqual(self.state.requests, ())
        self.assertEqual(len(self.external_edits()), 1)
        self.assertBlocked(self.can_run(Use("res_contorno", "outline")),
                           gate.BlockKind.INPUT_CHANGED)


class JobsTest(ChecksCase):
    def hashing(self) -> Any:
        """Anota en ``self.hashed`` lo que se hashea en el hilo (el fichero principal)."""
        self.hashed = []
        real = check.read_steps

        def counting(found: Any, request: Any) -> Any:
            self.hashed.append(request.files["main"].name)
            return real(found, request)

        return mock.patch.object(check, "read_steps", counting)

    def test_external_sources_are_hashed_in_jobs(self) -> None:
        """RF-008-58, RF-008-09 (plan §5.3.3, §5.4.1 y §5.4.6; RNF-008-11): una fuente externa
        cuyo hash no cabe en el hilo se pide a los trabajos de ``bl`` (``HashJobs``) con su
        lector, sus ajustes y la ruta de sus ficheros, y no se lee en el hilo; mientras no
        termina, la comprobación espera paso a paso; su resultado se registra como el del hilo.
        Lo del proyecto nunca va a un trabajo. Sin trabajos (o si ahora no se puede lanzar
        uno), se hashea en el hilo. Cerrar la comprobación mientras espera cancela el trabajo
        y no registra nada."""
        self.replace(data.BOUNDARY_V2)
        self.qgis('UPDATE "res_contorno" SET valor = 9 WHERE codigo = ?', ("C-01",),
                  table="res_contorno", at=EDITED_AT)
        jobs = FakeJobs(waits=2)
        with mock.patch.object(readers, "INLINE_LIMIT_S", 0.0), self.hashing():
            outcome, found = self.check_all(jobs=jobs)
        self.assertEqual(self.hashed, [])
        (request,) = jobs.submitted
        self.assertEqual(
            (request.input_uid, request.name, request.reader, request.kind, list(request.files),
             request.normalizer, request.size),
            (self.record.uid, "Limites_v1", GPKG, "vector", ["main"],
             self.record.normalizer, self.target.stat().st_size))
        self.assertTrue(request.files["main"].samefile(self.target))
        self.assertEqual(dict(request.declarations), dict(self.record.declarations))
        self.assertEqual(dict(request.settings), dict(self.record.settings))
        self.assertGreaterEqual(jobs.polls, 3)
        self.assertEqual(jobs.cancelled, [])
        self.assertGreaterEqual([step.phase for step in found].count("contenido"), 2)
        (changed,) = outcome.inputs
        self.assertEqual((changed.verdict, changed.content_sha256),
                         (InputVerdict.CHANGED, self.content_of(self.target)))
        self.assertEqual(self.input_row(self.record.uid)["status"], "changed")
        self.assertEqual(len(self.external_edits()), 1)
        # Sin trabajos (o si no se puede lanzar uno), en el hilo.
        for refused in (None, FakeJobs(refuse=True)):
            if refused is None:
                self.third_version()
            else:
                self.replace(data.BOUNDARY_V2, step=40)
            with mock.patch.object(readers, "INLINE_LIMIT_S", 0.0), self.hashing():
                outcome, _steps = self.check_all(jobs=refused)
            self.assertEqual(self.hashed, [SOURCE])
            self.assertEqual(outcome.inputs[0].content_sha256, self.content_of(self.target))
        # Cerrar la comprobación mientras espera: el trabajo se cancela y no se registra nada.
        self.replace(data.BOUNDARY_V1_QGIS)
        jobs = FakeJobs(waits=10**9)
        before = self.full_state()
        with mock.patch.object(readers, "INLINE_LIMIT_S", 0.0):
            steps = checks.open_check_steps(self.project, self.registries, write=True,
                                            jobs=jobs)
            self.until(steps, lambda step: bool(jobs.submitted) and jobs.polls >= 2)
            steps.close()
        self.assertEqual(jobs.cancelled, [1])
        self.assertEqual(self.full_state(), before)

    def test_a_job_that_cannot_read_the_source_is_a_notice(self) -> None:
        """RF-008-13, RF-008-58 (plan §5.3.3): un trabajo que termina sin el hash —la fuente
        cambió mientras se copiaba, o leyó con otro lector o normalizador— deja la entrada «sin
        leer» con el motivo (sin rutas absolutas); uno que ya no la encuentra, «no
        localizable». Ni lo uno ni lo otro es un cambio: no se registra nada de la entrada."""
        self.replace(data.BOUNDARY_V2)
        other = dataclasses.replace(self.record.digest, reader="test.otro@1")
        error = "source_changed: la fuente cambió mientras se copiaba (" + str(self.target) + ")"
        cases = ((checks.HashResult(error=error), InputVerdict.UNREADABLE, data.BOUNDARY_V1),
                 (checks.HashResult(other), InputVerdict.UNREADABLE, "test.otro@1"),
                 (checks.HashResult(gone=True), InputVerdict.UNREACHABLE, None))
        before = self.input_row(self.record.uid)
        for result, verdict, shown in cases:
            with self.subTest(verdict=verdict, shown=shown), \
                    mock.patch.object(readers, "INLINE_LIMIT_S", 0.0):
                outcome, _steps = self.check_all(jobs=FakeJobs(0, result=result))
                (found,) = outcome.inputs
                self.assertEqual(found.verdict, verdict)
                notice = found.render_notice()
                self.assertIn(notice, outcome.warnings)
                self.assertNotIn(str(self.target.parent), notice)
                if shown is not None:
                    self.assertIn(shown, found.reason)
                self.assertEqual(self.input_row(self.record.uid), before)

    def test_hashes_requested_by_the_gate_are_computed_and_recorded(self) -> None:
        """RF-008-58, RF-008-09, RF-008-21 (plan §5.4.5): lo que la puerta pidió hashear
        después de la comprobación de apertura (``CheckState.requests``) lo calcula y lo
        registra ``hash_requests_steps``, en una transacción, y deja de esperarse: la puerta
        ve entonces la entrada cambiada. Lo pedido que ya no hay que hashear solo se quita."""
        self.qgis('UPDATE "res_contorno" SET valor = 3.0', table="res_contorno", at=EDITED_AT)
        self.replace(data.BOUNDARY_V2)
        with mock.patch.object(gate, "HASH_LIMIT_S", 0.0):
            self.assertIsInstance(self.can_run(Use("res_area", "area")), gate.Pending)
        self.assertEqual({(item.item_kind, item.name) for item in self.state.requests},
                         {(ItemKind.DATASET, "res_contorno"), (ItemKind.INPUT, "Limites_v1")})
        self.state.request_hash(gate.PendingItem(ItemKind.DATASET, self.uid("res_area"),
                                                 "res_area", gate.PendingReason.HASHING))
        found = list(checks.hash_requests_steps(self.project, self.state))
        self.assertEqual(list(dict.fromkeys(step.phase for step in found)),
                         list(checks.REQUEST_STEPS))
        outcome = found[-1].result
        self.assertTrue(outcome.recorded)
        self.assertEqual(self.state.requests, ())
        self.assertEqual({item.record.name for item in outcome.datasets}, {"res_contorno"})
        self.assertEqual(len(self.external_edits()), 1)
        self.assertEqual(self.input_row(self.record.uid)["status"], "changed")
        self.assertBlocked(self.can_run(Use("res_area", "area")), gate.BlockKind.INPUT_CHANGED)

    def test_arguments(self) -> None:
        """Plan §5.3.1: lo pendiente es un ``CheckState`` y los trabajos, algo con ``submit``,
        ``poll`` y ``cancel``; un ``HashResult`` es un hash, un error o una fuente que ya no
        está, solo uno. Un proyecto sin la procedencia (esquema 1) no tiene nada que
        comprobar ni que registrar."""
        for bad in ({"pending": "x"}, {"jobs": object()}):
            with self.subTest(bad=bad), self.assertRaises(TypeError):
                checks.open_check_steps(self.project, self.registries, write=True, **bad)
        with self.assertRaises(TypeError):
            checks.hash_requests_steps(self.project, "x")
        with self.assertRaises(TypeError):
            checks.hash_requests_steps(self.project, self.state, jobs=object())
        digest = self.record.digest
        for bad in ({}, {"digest": digest, "error": "x"}, {"error": "x", "gone": True},
                    {"digest": "x"}):
            with self.subTest(bad=bad), self.assertRaises((TypeError, ValueError)):
                checks.HashResult(**bad)
        self.assertEqual(checks.HashResult(error="sin leer").error, "sin leer")
        before = self.full_state()
        with mock.patch.object(type(self.project), "schema_version", property(lambda _s: 1)):
            outcome, (only,) = self.check_all(pending=self.state)
        self.assertEqual((only.done, outcome.recorded), (checks.PROGRESS_TOTAL, False))
        self.assertFalse(self.state.running)
        self.assertEqual(self.full_state(), before)


class FullCheckTest(ChecksCase):
    def full_check(self, **kw: Any) -> tuple[Any, list[Any]]:
        """Todos los pasos de «Comprobar cambios en las entradas»: su resultado (solo en el
        último paso) y los pasos."""
        found = list(checks.full_check_steps(self.project, **kw))
        for step in found:
            self.assertIsInstance(step, project_model.Progress)
        self.assertEqual([step.result is not None for step in found],
                         [False] * (len(found) - 1) + [True])
        outcome = found[-1].result
        self.assertIsInstance(outcome, checks.OpenCheckOutcome)
        return outcome, found

    def test_hashes_every_input_and_checks_the_project_data(self) -> None:
        """RF-008-09, RF-008-21, RF-008-13 (plan §5.4.2, «a petición»; T51): «Comprobar
        cambios en las entradas» hashea siempre la fuente de cada entrada activa —también la de
        «Limites_v1», que tiene otro contenido con el mismo tamaño y la misma fecha, y que el
        prefiltro de la apertura no ve— y comprueba los datos del proyecto (la edición de QGIS
        en ``res_contorno``); una entrada cuya fuente no está queda «no localizable» sin
        leerla. En solo lectura lo detecta todo sin escribir nada. En escritura, con sus pasos
        en orden y su progreso, la fuente externa va a un trabajo de hash, lo que pidió la
        puerta también se hace, y todo se registra en una sola transacción final. La fuente
        queda intacta."""
        self.replace(data.BOUNDARY_V2, mtime_ns=self.files(self.record.uid)[0]["mtime_ns"])
        self.assertEqual(self.target.stat().st_size, self.record.files[0].size)
        self.assertFalse(check.probe_input(self.project, self.record).needs_hash)
        plans = self.plans()  # sus ficheros no están en fuentes/
        self.qgis('UPDATE "res_contorno" SET valor = 9 WHERE codigo = ?', ("C-01",),
                  table="res_contorno", at=EDITED_AT)
        self.state.request_hash(gate.PendingItem(ItemKind.DATASET, self.uid("res_area"),
                                                 "res_area", gate.PendingReason.HASHING))
        expected = {"Limites_v1": InputVerdict.CHANGED, "planos": InputVerdict.UNREACHABLE}
        age_folders(self.sources)
        before = self.full_state()
        with assert_source_untouched(self.sources), self.read_only():
            outcome, _steps = self.full_check()
        self.assertEqual(self.full_state(), before)
        self.assertEqual((outcome.writing, outcome.recorded), (False, False))
        self.assertEqual({item.name: item.verdict for item in outcome.inputs}, expected)
        self.assertEqual({item.record.name: item.verdict for item in outcome.datasets},
                         {"res_contorno": Verdict.EDITED})

        jobs = FakeJobs()
        real = self.project.write_transaction
        transactions: list[int] = []

        def counting() -> Any:
            transactions.append(1)
            return real()

        with assert_source_untouched(self.sources), \
                mock.patch.object(readers, "INLINE_LIMIT_S", 0.0), \
                mock.patch.object(self.project, "write_transaction", counting):
            outcome, found = self.full_check(pending=self.state, jobs=jobs)
        self.assertEqual(len(transactions), 1)
        self.assertEqual(list(dict.fromkeys(step.phase for step in found)),
                         list(checks.FULL_CHECK_STEPS))
        done = [step.done for step in found]
        self.assertEqual((done, done[-1]), (sorted(done), checks.PROGRESS_TOTAL))
        self.assertEqual([request.name for request in jobs.submitted], ["Limites_v1"])
        self.assertTrue(outcome.recorded)
        self.assertEqual({item.name: item.verdict for item in outcome.inputs}, expected)
        self.assertEqual(self.input_row(self.record.uid)["status"], "changed")
        self.assertEqual(self.input_row(plans.uid)["status"], "current")
        (edit,) = self.external_edits()
        self.assertEqual(self.dataset("res_contorno").operation_uid, edit["uid"])
        self.assertLessEqual({self.uid(name) for name in ("res_limites", "res_area")},
                             set(outcome.checked_datasets))
        self.assertEqual(self.state.requests, ())
        self.assertIn(UNREACHABLE, outcome.warnings)
        self.assertTrue(any(text.startswith("La entrada «Limites_v1» ha cambiado")
                            for text in outcome.warnings), outcome.warnings)
        with self.assertRaises(TypeError):
            checks.full_check_steps(self.project, pending="x")


if __name__ == "__main__":
    import unittest

    unittest.main()

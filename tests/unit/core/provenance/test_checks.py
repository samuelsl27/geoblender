# SPDX-License-Identifier: GPL-3.0-or-later
"""Comprobaciones de apertura, pasos 1 a 6 (spec 008, T36; RF-008-09, RF-008-19, RF-008-21,
RF-008-22, RF-008-24, RF-008-57, RF-008-60, RF-008-62 y RF-008-58; plan 008 §5.3.1 y §5.4.6).

``core.provenance.checks.open_check_steps`` hace, justo después de abrir y por pasos que avanza
un temporizador de ``bl`` (ninguno pasa de 20 ms), con su progreso («Comprobando el proyecto…
42 %»):

1. la **foto**: la hora de inicio, lo registrado (por páginas) y el listado de ``rasters/``,
   ``meshes/`` y ``originals/`` (tamaño y fecha por ``os.scandir``);
2. las operaciones «en curso» de otras sesiones, que quedan **interrumpidas**;
3. el **prefiltro de las entradas** vigentes, cambiadas sin decidir y mantenidas;
4. el **prefiltro de los datos** del proyecto y de los originales contra la foto (lo que esta
   sesión registró después de la foto no es una edición externa) y **lo que falta**;
5. los **restos** (apartados en escritura), los ficheros ajenos y las capas sin registrar;
6. las **versiones de algoritmo** mayores (con su aviso) y las **definiciones** de parámetros
   cambiadas.

Lo que hay que hashear queda para el paso 7 y las escrituras en la base, para la transacción
final (T37): estos pasos no leen el contenido de nada ni escriben nada en la base.

Cada prueba usa el proyecto de ``test_external`` (esquema 2, reloj simulado): la entrada
«Limites_v1» importada en ``res_limites``; ``res_contorno`` (editable a mano) y ``res_bocas``
calculados de ella; ``res_area`` de ``res_contorno``.
"""

from __future__ import annotations

import ast
import contextlib
import dataclasses
import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock

from tests.support import provenance_data as data
from tests.support.core_fixtures import make_session
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
from tests.unit.core.inputs.test_check import BASE_NS
from tests.unit.core.inputs.test_registry import GPKG, MTIME_NS, SESSION
from tests.unit.core.params.test_store import DENSITY, DENSITY_KG, SWELL
from tests.unit.core.provenance.test_gate import AREA, EDITED_AT, PLAN, _spec
from tests.unit.core.provenance.test_schema import dataset_row, operation_row

checks = import_geoblender("core.provenance.checks")
provenance = import_geoblender("core.provenance")
operations = import_geoblender("core.provenance.operations")
stale_mod = import_geoblender("core.provenance.stale")
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


class ChecksCase(ExternalCase):
    """El proyecto de ``test_external`` y lo que declara el Geoblender que lo abre."""

    def setUp(self) -> None:
        super().setUp()
        self.registries = checks.Registries.installed()

    # --- Ayudas -----------------------------------------------------------------------------

    def steps(self, **kw: Any) -> list[Any]:
        """Todos los pasos de la comprobación de apertura (en escritura, por defecto)."""
        kw.setdefault("write", True)
        registries = kw.pop("registries", self.registries)
        return list(checks.open_check_steps(self.project, registries, **kw))

    def open_check(self, **kw: Any) -> Any:
        """El resultado de la comprobación de apertura (el último paso)."""
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
        found: list[Any] = []
        for step in steps:
            found.append(step)
            if step.phase != checks.OPEN_CHECK_STEPS[0]:
                return found
        self.fail("la comprobación terminó sin pasar de la foto")

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
        """RF-008-58, RF-008-09, RF-008-21 (plan §5.4.6): sin nada cambiado, los seis pasos
        corren en orden (foto, interrumpidas, entradas, datos, restos, versiones), con su
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
        self.assertEqual(list(dict.fromkeys(phases)), list(checks.OPEN_CHECK_STEPS))
        self.assertEqual(checks.OPEN_CHECK_STEPS, ("foto", "interrumpidas", "entradas", "datos",
                                                   "restos", "versiones"))
        order = [checks.OPEN_CHECK_STEPS.index(phase) for phase in phases]
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
            return self.drive(checks.open_check_steps(self.project, self.registries,
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
        steps = checks.open_check_steps(self.project, self.registries, write=True)
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
        steps = checks.open_check_steps(self.project, self.registries, write=True)
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


if __name__ == "__main__":
    import unittest

    unittest.main()

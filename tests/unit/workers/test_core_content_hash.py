# SPDX-License-Identifier: GPL-3.0-or-later
"""El trabajo de hash de contenido ``core_content_hash`` (spec 008, T47; RF-008-09; RNF-008-11;
plan 008 §5.3.3, D6 y D17; ADR-0025 §2 y §7).

Las fuentes externas grandes se hashean en un trabajo de la 004 (``jobs.content_hash.run``, la
misma función en el hilo y en proceso aparte, que ``workers/core_content_hash.py`` envuelve tras
registrar los lectores de su lista estática). Aquí se lanzan de verdad, con un ``JobRunner`` y
``ContentHashJobs`` (el ``HashJobs`` de ``core.provenance.checks``), en proceso aparte: todos a
la vez al empezar el módulo (``setUpModule``), con un tamaño declarado enorme para que su
estimación pase de 5 s (RF-004-03). Lo que necesita provocar algo a mitad (la fuente que cambia
mientras se copia, cancelar entre dos trozos) se prueba con ``run`` en el hilo, con su
``WorkerContext``.
"""

import dataclasses
import json
import os
import shutil
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.support import jobs_fixtures as _support
from tests.support.package import import_geoblender
from tests.support.provenance_checks import source_changes, source_state
from tests.support.provenance_data import BOUNDARY_V1, BOUNDARY_V2, DATA_DIR, LAYER, make_wal_variant
from tests.support.repo import EXTENSION_DIR
from tests.support.trees import age_folders

content_hash = import_geoblender("jobs.content_hash")
worker = import_geoblender("workers.core_content_hash")
catalog = import_geoblender("jobs.catalog")
runner_mod = import_geoblender("jobs.runner")
interpreter = import_geoblender("jobs.interpreter")
job_paths_mod = import_geoblender("jobs.paths")
worker_api = import_geoblender("jobs.worker_api")
records = import_geoblender("jobs.records")
messages = import_geoblender("jobs.messages")
readers = import_geoblender("core.content.readers")
builtin = import_geoblender("core.content.builtin")
checks = import_geoblender("core.provenance.checks")

HUGE = 10**12  # bytes declarados: la estimación pasa de 5 s y el trabajo va a proceso aparte
DOC_BYTES = 5 * (1 << 20) // 2  # 2,5 MiB: tres trozos de 1 MiB
GPKG_DECLARATIONS = {"conventions": {}, "crs_h": {"epsg": 25830}, "crs_v": None}
LAYER_SETTINGS = {"layer": LAYER}
CANCEL_BUDGET_S = 2.0  # RNF-008-11: cancelación efectiva en ≤ 2 s
WAIT_S = 60.0  # plazo de seguridad: un trabajo colgado no cuelga la prueba

_STATE: dict = {}
_HANDLES: dict = {}
_RESULTS: dict = {}
_INPUTS: dict = {}
_COMMANDS: dict = {}
_EVENTS: dict = {}


def _request(name: str, reader: object, kind: str, files: dict, *, declarations=None,
             settings=None, size: int = HUGE) -> object:
    """La petición de hash de una entrada externa (como la que hace la comprobación)."""
    return checks.HashRequest(f"uid-{name}", name, reader.id, kind,
                              {} if declarations is None else declarations,
                              {} if settings is None else settings, files,
                              "gbch/1", size)


def _thread_digest(request: object) -> object:
    """El hash de la misma fuente leído en el hilo (``read_content``), la referencia."""
    found = readers.reader(request.reader)
    return readers.read_content(found, found.request(
        request.kind, request.declarations, request.files, dict(request.settings),
        normalizer=request.normalizer))


def _register_core_readers() -> None:
    for found in builtin.CONTENT_READERS:
        if found.id not in readers.READERS:
            readers.register_reader(found)
            unittest.addModuleCleanup(readers.unregister_reader, found.id)


def setUpModule() -> None:
    tmp = _support.jobs_tmp()
    base = tmp.__enter__()
    unittest.addModuleCleanup(tmp.__exit__, None, None, None)
    _register_core_readers()
    registry = mock.patch.dict(catalog._REGISTRY)
    registry.start()
    unittest.addModuleCleanup(registry.stop)
    catalog.register_worker(content_hash.WORKER_INFO)

    sources = base / "fuentes"
    sources.mkdir()
    document = sources / "informe.bin"
    document.write_bytes(os.urandom(DOC_BYTES))
    layer = sources / "limites.gpkg"
    shutil.copyfile(DATA_DIR / BOUNDARY_V1, layer)
    wal_folder = base / "wal"
    wal_folder.mkdir()
    variant = make_wal_variant(wal_folder)
    project = base / "proyecto"
    (project / "documentos").mkdir(parents=True)
    for folder in (sources, wal_folder):
        age_folders(folder)
    _STATE.update(base=base, sources=sources, wal_folder=wal_folder, variant=variant,
                  project=project, before=(source_state(sources), source_state(wal_folder)))

    requests = {
        "doc": _request("informe", builtin.DOCUMENT, "document", {"main": document}),
        "gpkg": _request("limites", builtin.GPKG_LAYER, "vector", {"main": layer},
                         declarations=GPKG_DECLARATIONS, settings=LAYER_SETTINGS),
        "wal": _request("limites_wal", builtin.GPKG_LAYER, "vector", {"main": variant.path},
                        declarations=GPKG_DECLARATIONS, settings=LAYER_SETTINGS),
        "missing": _request("borrado", builtin.DOCUMENT, "document",
                            {"main": sources / "borrado.bin"}),
        "cancel": _request("cancelado", builtin.DOCUMENT, "document", {"main": document}),
    }
    _STATE["requests"] = requests
    runner = runner_mod.JobRunner(jobs_root=base / "jobs", package_dir=EXTENSION_DIR,
                                  blender_python=Path(sys.executable), max_subprocess=5,
                                  forbidden_roots=[project])
    unittest.addModuleCleanup(runner.shutdown)
    _STATE["runner"] = runner
    jobs = content_hash.ContentHashJobs(lambda: runner)
    _STATE["jobs"] = jobs

    real_build = interpreter.build_command

    def build(*args, **kwargs):
        command = real_build(*args, **kwargs)
        _COMMANDS[Path(kwargs["job_dir"]).name] = command
        return command

    with mock.patch.object(runner_mod.interpreter, "build_command", side_effect=build):
        for name, request in requests.items():
            _HANDLES[name] = jobs.submit(request)
        jobs.cancel(_HANDLES["cancel"])
    deadline = time.monotonic() + WAIT_S
    while any(handle.result() is None for handle in _HANDLES.values()):
        if time.monotonic() > deadline:
            raise AssertionError("los trabajos de hash no terminan")
        for update in runner.poll():
            _EVENTS.setdefault(update.job_uid, []).extend(update.events)
        time.sleep(0.02)
    for name, handle in _HANDLES.items():
        _INPUTS[name] = sorted(path.name for path in handle.job_dir.inputs_dir.iterdir())
        _RESULTS[name] = jobs.poll(handle)
    _STATE["after"] = (source_state(sources), source_state(wal_folder))


class SubprocessTest(unittest.TestCase):
    """Los trabajos lanzados en proceso aparte al empezar el módulo."""

    def test_same_hash_as_in_the_thread(self) -> None:
        """RF-008-09, RNF-008-11 (plan §5.3.3): una fuente externa grande se hashea en un
        trabajo en proceso aparte, leída en su sitio, con el mismo hash de contenido (y de
        datos, lector y normalizador) que en el hilo; su resumen dice los bytes leídos."""
        for name in ("doc", "gpkg"):
            with self.subTest(fuente=name):
                handle = _HANDLES[name]
                record = records.read_record(handle.job_dir)
                self.assertEqual(record.executor, runner_mod.EXECUTOR_SUBPROCESS)
                self.assertEqual(handle.state, "succeeded", handle.message)
                result = _RESULTS[name]
                self.assertEqual(result, checks.HashResult(
                    digest=_thread_digest(_STATE["requests"][name])))
                main = _STATE["requests"][name].files["main"]
                self.assertEqual(handle.result().summary["bytes"],
                                 {"main": main.stat().st_size})
                self.assertEqual(_INPUTS[name], [])  # leída en su sitio, sin copia

    def test_path_goes_on_the_command_line_and_never_in_the_request(self) -> None:
        """RF-008-09 (ADR-0010, plan §5.3.3 y D17): la ruta de la fuente va en la línea de
        órdenes del worker (``--path source_main=…``) y nunca en ``request.json``, que solo
        nombra los papeles; el trabajo no lleva nada del proyecto."""
        base = str(_STATE["base"])
        for name in ("doc", "gpkg", "wal"):
            with self.subTest(fuente=name):
                handle = _HANDLES[name]
                main = _STATE["requests"][name].files["main"]
                command = _COMMANDS[handle.job_uid]
                at = command.index(f"source_main={main}")
                self.assertEqual(command[at - 1], "--path")
                text = (handle.job_dir.path / job_paths_mod.REQUEST_FILE).read_text("utf-8")
                for shown in (base, base.replace("\\", "/"), json.dumps(base)[1:-1]):
                    self.assertNotIn(shown, text)
                request = json.loads(text)
                self.assertEqual(request["params"]["roles"], {"main": "source_main"})
                self.assertIsNone(request["project_uid"])
                self.assertEqual(request["worker"], content_hash.WORKER)

    def test_wal_source_is_copied_with_its_wal(self) -> None:
        """RF-008-09, RF-008-14 (plan §5.3.3): una fuente SQLite con ``-wal`` se copia a
        ``in/`` con su ``-wal`` (``JobDir.copy_input``) y se lee sobre la copia, con su
        edición pendiente (el hash de ``Limites_v2``); junto a la fuente no cambia nada.
        Incorporado el resultado, la copia se borra (``mark_ingested``)."""
        self.assertEqual(_INPUTS["wal"], ["source_main.gpkg", "source_main.gpkg-wal"])
        request = _STATE["requests"]["wal"]
        expected = _thread_digest(dataclasses.replace(
            request, files={"main": DATA_DIR / BOUNDARY_V2}))
        self.assertEqual(_RESULTS["wal"], checks.HashResult(digest=expected))
        self.assertEqual(_thread_digest(request), expected)  # en el hilo, lo mismo
        for before, after in zip(_STATE["before"], _STATE["after"], strict=True):
            self.assertEqual(source_changes(before, after), [])
        handle = _HANDLES["wal"]
        copies = handle.job_dir.inputs_dir
        self.assertFalse(copies.exists() and any(copies.iterdir()))
        self.assertIsNotNone(records.read_record(handle.job_dir).ingested_at)

    def test_missing_source_is_gone(self) -> None:
        """RF-008-09: si la fuente ya no está, el trabajo falla con su código y la
        comprobación la da por no localizable (``gone``), no por ilegible."""
        handle = _HANDLES["missing"]
        self.assertEqual(handle.state, "failed")
        self.assertEqual(handle.result().error_code, content_hash.SOURCE_MISSING)
        self.assertIn("borrado.bin", handle.result().error_text)
        self.assertEqual(_RESULTS["missing"], checks.HashResult(gone=True))

    def test_cancel_stops_within_two_seconds(self) -> None:
        """RNF-008-11 (RF-004-09): cancelar el trabajo de hash lo para en ≤ 2 s (el worker mira
        la cancelación antes de copiar y entre dos trozos); la comprobación lo ve como un
        hash que no se pudo calcular."""
        handle = _HANDLES["cancel"]
        self.assertEqual(handle.state, "cancelled")
        events = {event.type: event for event in _EVENTS[handle.job_uid]}
        self.assertNotIn("result", events)
        # Horas del propio worker: pidió parar antes de que arrancase.
        self.assertLessEqual(events["cancelled"].ts - events["start"].ts, CANCEL_BUDGET_S)
        result = _RESULTS["cancel"]
        self.assertIsNone(result.digest)
        self.assertTrue(result.error)

    def test_project_files_never_reach_a_job(self) -> None:
        """ADR-0010, ADR-0025 §7 (plan §5.3.3): un fichero dentro de la raíz del proyecto
        (una ruta prohibida del lanzador) nunca va a un trabajo: ``submit`` dice que no
        (``None``: se hashea en el hilo) sin crear nada; sin lanzador, tampoco."""
        jobs = _STATE["jobs"]
        runner = _STATE["runner"]
        inside = _STATE["project"] / "documentos" / "acta.pdf"
        inside.write_bytes(b"%PDF-1.7\n")
        before = sorted(runner.jobs_root.iterdir())
        request = _request("acta", builtin.DOCUMENT, "document", {"main": inside})
        self.assertIsNone(jobs.submit(request))
        self.assertIsNone(content_hash.ContentHashJobs(lambda: None).submit(request))
        self.assertEqual(sorted(runner.jobs_root.iterdir()), before)


class InThreadTest(unittest.TestCase):
    """``run`` en el hilo, con su ``WorkerContext``, como el ejecutor en hilo."""

    def setUp(self) -> None:
        self.root = _STATE["base"] / "hilo" / self.id().rpartition(".")[2]
        self.root.mkdir(parents=True)

    def context(self, request: object, *, sink: object = None,
                cancel: threading.Event | None = None) -> object:
        job = content_hash.new_job(request)
        folder = job_paths_mod.job_dir(self.root, job.job_uid).create()
        return worker_api.WorkerContext(job, folder, sink or worker_api.QueueSink(),
                                        cancel_event=cancel,
                                        paths=content_hash.job_paths(request))

    def test_source_changed_during_the_copy(self) -> None:
        """RF-008-09 (plan §5.3.3): si la fuente cambia mientras se copia —su ``-wal`` durante
        su copia, o el fichero principal antes de copiar el ``-wal`` (un volcado del ``-wal``
        entre las dos copias)— el trabajo falla con ``source_changed``, que nombra la fuente y
        el trabajo, sin leerla."""
        real = job_paths_mod._digest
        for changed in ("wal", "principal"):
            with self.subTest(cambia=changed):
                folder = self.root / changed
                folder.mkdir()
                variant = make_wal_variant(folder)
                calls: list[Path] = []

                def tampering(path, sink=None, variant=variant, changed=changed, calls=calls):
                    calls.append(Path(path))
                    if Path(path) != variant.wal:
                        return real(path, sink)
                    if changed == "wal" and sink is not None:  # mientras se copia el -wal
                        digest = real(path, sink)
                        with open(variant.wal, "ab") as stream:
                            stream.write(b"\x00" * 512)
                        return digest
                    if changed == "principal" and calls.count(variant.wal) == 1:
                        with open(variant.path, "ab") as stream:  # el volcado del -wal
                            stream.write(b"\x00" * 1024)
                    return real(path, sink)

                request = _request("limites", builtin.GPKG_LAYER, "vector",
                                   {"main": variant.path}, declarations=GPKG_DECLARATIONS,
                                   settings=LAYER_SETTINGS)
                ctx = self.context(request)
                with mock.patch.object(job_paths_mod, "_digest", side_effect=tampering):
                    with self.assertRaises(messages.JobError) as caught:
                        content_hash.run(ctx)
                self.assertEqual(caught.exception.code, "source_changed")
                self.assertIn(variant.path.name, caught.exception.text)
                self.assertIn(variant.wal, calls)

    def test_cancel_between_chunks(self) -> None:
        """RNF-008-11 (RF-004-09): cancelar a mitad de la lectura para el trabajo entre dos
        trozos (``JobCancelled``) en mucho menos de 2 s, sin llegar al final."""
        cancel = threading.Event()
        sent: list[float] = []
        asked: list[float] = []

        class Sink:
            def send(self, event: object) -> None:
                if event.type == "progress":
                    sent.append(event.frac)
                    if event.frac >= 0.5 and not cancel.is_set():
                        asked.append(time.perf_counter())
                        cancel.set()

        document = self.root / "grande.bin"
        document.write_bytes(os.urandom(4 * (1 << 20)))
        request = _request("grande", builtin.DOCUMENT, "document", {"main": document})
        ctx = self.context(request, sink=Sink(), cancel=cancel)
        with mock.patch.object(worker_api, "PROGRESS_INTERVAL_S", 0.0):
            with self.assertRaises(worker_api.JobCancelled):
                content_hash.run(ctx)
        took = time.perf_counter() - asked[0]
        self.assertLess(max(sent), 1.0)
        self.assertLessEqual(took, CANCEL_BUDGET_S)

    def test_request_names_roles_and_never_paths(self) -> None:
        """RF-008-09 (plan §5.3.3): la petición lleva el lector, el tipo, lo declarado, los
        ajustes, el normalizador, el tamaño y el nombre de la ruta de cada papel
        (``source_<papel>``), sin rutas; las rutas van aparte (``job_paths``). Su tipo de
        trabajo es ``core_content_hash`` (automático, entorno de Blender, con la estimación de
        su lector y ``run``)."""
        document = _STATE["sources"] / "informe.bin"
        request = _request("informe", builtin.DOCUMENT, "document", {"main": document},
                           size=DOC_BYTES)
        job = content_hash.new_job(request)
        self.assertEqual(job.params, {
            "reader": "core.document@1", "kind": "document", "declarations": {},
            "settings": {}, "normalizer": "gbch/1", "roles": {"main": "source_main"},
            "size": DOC_BYTES})
        self.assertNotIn(str(_STATE["base"]), json.dumps(job.to_json()))
        self.assertEqual(content_hash.job_paths(request), {"source_main": document})
        info = content_hash.WORKER_INFO
        self.assertEqual((info.name, info.policy, info.environment, info.run),
                         ("core_content_hash", "auto", "blender", content_hash.run))
        self.assertEqual(info.estimate_s(job.params),
                         builtin.DOCUMENT.estimate_s(DOC_BYTES))
        self.assertIsNone(info.estimate_s({**job.params, "reader": "test.nadie@1"}))


class WorkerReadersTest(unittest.TestCase):
    """La lista estática de lectores del envoltorio en proceso aparte."""

    def test_static_list_is_core(self) -> None:
        """ADR-0025 §2 (plan §5.3.3): ``workers/core_content_hash.py`` carga los lectores de
        su lista estática de paquetes (``("core",)`` en la 008): los de ``core`` que pueden
        ir al trabajo, y los registra antes de llamar a ``jobs.content_hash.run`` (la
        comparación con lo que registra ``bl`` está en ``tests/blender``)."""
        self.assertEqual(tuple(worker.READER_PACKAGES), ("core",))
        expected = tuple(found for found in builtin.CONTENT_READERS if found.worker)
        self.assertEqual(worker.worker_readers(), expected)
        with mock.patch.dict(readers._REGISTRY, clear=True):
            worker.register_readers()
            worker.register_readers()  # idempotente
            self.assertEqual(sorted(readers.READERS), sorted(found.id for found in expected))
        self.assertIs(worker.run, content_hash.run)


if __name__ == "__main__":
    unittest.main()

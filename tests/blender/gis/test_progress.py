# SPDX-License-Identifier: GPL-3.0-or-later
"""Progreso, cancelación y fallos de las órdenes de la topografía en Blender (spec 006, T33;
HU-006-1; RF-006-28; RF-008-19, RF-008-22; plan 006 §5.3.4, §5.6.4 y §5.6.5).

Con el proyecto, las fuentes y la cadena del TIN de ``test_ops_tin`` (``TinOperatorsCase``):
cada orden lanza su operación de la 008 con sus trabajos de la 004, que sigue la barra de
estado (``bl.ops.jobs.JobMonitor``, campo «jobs» de ``bl/ui/jobs.py``) y cancela su botón
(``geoblender.jobs_cancel``). «En mitad» es en el primer aviso de progreso del trabajo a partir
de la mitad: la prueba envuelve su función (``WorkerInfo.run``, el registro de tipos de trabajo)
para que espere ahí a que la persona pulse cancelar, como haría si tardara.

«El proyecto con el mismo hash» (alineación con la 008 de la T33) se lee: ningún dato, entrada,
tabla ni fichero nuevo (fuera de la caché y de ``project.gpkg``, que registra la operación) y
los datos registrados con el mismo hash; la operación queda «cancelada» o «fallida» con su
motivo (RF-008-19). El progreso de una importación de 11,2 M celdas (un aviso cada ≤ 0,5 s) lo
mide ``tests/unit/workers/test_gis_progress.py``.

T50 (RNF-006-09): una importación de puntos se cancela también mientras su trabajo calcula el
hash de las tablas que serán lo importado; al terminar su trabajo, se incorpora por pasos desde
su temporizador (``bl.ops.gis.incorporation_tick``, que las pruebas avanzan a mano) sin que el
hilo de Blender vuelva a leer las tablas, con el mismo hash de antes; un fallo en su
transacción no deja nada.

T54 (RNF-006-09): la de un MDT, también por pasos (la comparación de cotas con las posiciones
que dejó su trabajo y la copia de su rejilla al proyecto, un trozo por paso); cerrarla o un
fallo a mitad de la copia no dejan nada en el proyecto ni ningún fichero a medias.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import dataclasses
import hashlib
import os
import threading
import time
import unittest
import uuid
from pathlib import Path
from typing import Any
from unittest import mock

import bpy

from tests.blender.gis.test_ops_dtm import DATA, IMPORT, JOB_WAIT_S, RESAMPLE, _module
from tests.blender.gis.test_ops_tin import IMPORT_POINTS, TIN_POINTS, TinOperatorsCase
from tests.support.core_fixtures import FakePids

CONTOURS = "geoblender.gis_create_contours"
MIDWAY = 0.5  # el primer aviso de progreso a partir de la mitad del trabajo
NOT_PROJECT_DATA = ("cache",)  # la caché (los trabajos) no es del proyecto
DATABASE_FILES = ("project.gpkg", "project.gpkg-journal", ".lock")
COPY_CHUNK = 256  # trozos de la copia al proyecto (T54): la rejilla importada, en más de 8


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _failing_copy(real: Any, error: BaseException, *, after: int) -> Any:
    """Los pasos de ``gis.store._copy_steps`` (``real``) que fallan con ``error`` dentro de la
    copia, como el disco, tras ``after`` trozos."""

    def copy_steps(source: Path, target: Path, name: str, cancelled: Any) -> Any:
        steps = real(source, target, name, cancelled)
        for _ in range(after):
            yield next(steps)
        steps.throw(error)

    return copy_steps


class _Gate:
    """Un tipo de trabajo cuya función se para en su primer aviso de progreso ≥ ``at`` (ya
    enviado a la barra de estado) hasta que la prueba lo suelta (:attr:`release`)."""

    def __init__(self, info: Any, at: float) -> None:
        self.at = at
        self.reached = threading.Event()
        self.release = threading.Event()
        self.message = ""
        self._real = info.run
        self.info = dataclasses.replace(info, run=self._run)

    def _run(self, ctx: Any) -> Any:
        return self._real(_PausingContext(ctx, self))


class _PausingContext:
    """El ``WorkerContext`` del trabajo, con :meth:`progress` parado en la puerta."""

    def __init__(self, ctx: Any, gate: _Gate) -> None:
        self._ctx = ctx
        self._gate = gate

    def __getattr__(self, name: str) -> Any:
        return getattr(self._ctx, name)

    def progress(self, frac: float, msg: str = "") -> None:
        gate = self._gate
        if frac >= gate.at and not gate.reached.is_set():
            self._ctx.progress(frac, msg)
            self._ctx.flush()
            gate.message = msg
            gate.reached.set()
            gate.release.wait(JOB_WAIT_S)
        self._ctx.progress(frac, msg)


class ProgressTest(TinOperatorsCase):
    def setUp(self) -> None:
        super().setUp()
        self.job_catalog = _module("jobs.catalog")
        self.jobs_ui = _module("bl.ui.jobs")
        self.store = _module("gis.store")

    # --- Ayudas -----------------------------------------------------------------------------

    def start(self) -> None:
        """El proyecto con un MDT importado (``gis_src_mdt_dron``) y los puntos y las roturas
        de los taludes (``gis_pts_taludes``, ``gis_brk_taludes``)."""
        self.open()
        self.import_dtm(self.source("geotiff/f64_strip.tif", "mdt/dron.tif"), "MDT dron")
        self.import_csv("points/taludes.csv", "Taludes")
        self.ps.take_notices()

    def state(self) -> tuple[Any, ...]:
        """Lo que es del proyecto: sus ficheros (fuera de la caché y de la base de datos) con
        su sha256, sus datos con su hash y su estado, sus entradas y sus tablas."""
        root = Path(self.project.root)
        files = {path.relative_to(root).as_posix(): _sha(path)
                 for path in sorted(root.rglob("*")) if path.is_file()
                 and path.relative_to(root).parts[0] not in NOT_PROJECT_DATA
                 and path.name not in DATABASE_FILES}
        return (files,
                self.rows("SELECT uid, name, locator, content_sha256, status FROM gb_dataset "
                          "ORDER BY uid"),
                self.rows("SELECT uid, name, content_sha256, status FROM gb_input ORDER BY uid"),
                self.rows("SELECT table_name FROM gpkg_contents ORDER BY table_name"))

    def wait(self, event: threading.Event) -> None:
        """Avanza a mano el monitor de los trabajos y el temporizador de la triangulación
        hasta que ``event`` está puesto."""
        deadline = time.monotonic() + JOB_WAIT_S
        while not event.wait(0.002):
            self.jobs_ops.tick()
            self.gis_ops.triangulation_tick()
            self.gis_ops.incorporation_tick()
            if time.monotonic() > deadline:
                self.fail("el trabajo no llega a la mitad")

    def variant(self, name: str, z: str = "999,999") -> Path:
        """``taludes.csv`` con la cota ``z`` en su primer punto, en ``entregas/topografia/``:
        otros datos, otra entrada (con los mismos, la importación reutilizaría la de
        ``start``)."""
        lines = (DATA / "points" / "taludes.csv").read_bytes().decode("utf-8").splitlines(
            keepends=True)
        fields = lines[1].split(";")
        fields[3] = z
        lines[1] = ";".join(fields)
        target = self.sources / "topografia" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes("".join(lines).encode("utf-8"))
        return target

    def points_props(self, path: Path, name: str) -> dict[str, Any]:
        return {"filepath": str(path), "name": name, "encoding": "UTF8",
                "separator": "SEMICOLON", "decimal": "COMMA", "crs": "EPSG:25830",
                "vertical": "PROJECT"}

    def cancel_midway(self, worker: str, idname: str, shown: str, at: float = MIDWAY,
                      message: str | None = None, **props: Any) -> str:
        """Lanza la orden ``idname`` y, cuando su trabajo ``worker`` llega a ``at`` (la mitad),
        comprueba que la barra de estado lo enseña (``shown`` en su nombre, su avance y su
        mensaje, que es ``message`` si se da) y lo cancela con su botón; sigue hasta que no
        queda nada en marcha. Devuelve el uid de la operación."""
        gate = _Gate(self.job_catalog.WORKERS[worker], at)
        with mock.patch.dict(self.job_catalog._REGISTRY, {worker: gate.info}):
            try:
                result, op_uid = self.run_op(idname, **props)
                self.assertEqual(result, {"FINISHED"})
                self.wait(gate.reached)
                self.jobs_ops.tick()
                view = self.jobs_ui.current_view()
                self.assertEqual(view.active, 1)
                self.assertIn(shown, view.current.name)
                self.assertGreaterEqual(view.percent, int(at * 100))
                self.assertEqual(self.jobs_ui.bar_text(view.current, view.percent),
                                 f"{view.current.name} · {view.percent} %")
                self.assertEqual(view.current.message, gate.message)
                if message is not None:
                    self.assertEqual(gate.message, message)
                self.assertEqual(bpy.ops.geoblender.jobs_cancel("EXEC_DEFAULT"), {"FINISHED"})
            finally:
                gate.release.set()
            self.settle()
        return op_uid

    def assertCancelled(self, op_uid: str, before: tuple[Any, ...]) -> None:
        """La operación ``op_uid`` quedó cancelada con su motivo, ya incorporada (nada
        pendiente ni esperando), sin carpeta de trabajo de su cadena, y el proyecto como
        estaba (``before``)."""
        _type, status, reason, *_ = self.operation(op_uid)
        self.assertEqual(status, "cancelled")
        self.assertTrue(reason and "cancel" in reason.lower(), reason)
        self.assertNotIn(op_uid, self.session.pending_ingests().values())
        self.assertEqual(self.gis_ops.pending_triangulations(), [])
        work = Path(self.project.cache_dir(), self.gis_ops.WORK_DIR)
        self.assertEqual(sorted(work.glob(f"tin-{op_uid.partition('-')[0]}")), [])
        self.assertEqual(self.state(), before)

    # --- Pruebas ----------------------------------------------------------------------------

    def test_cancel_midway_leaves_the_project_as_it_was(self) -> None:
        """RF-006-28, RF-008-19 (T33): con un trabajo a la mitad, la barra de estado enseña su
        nombre, su avance (≥ 50 %) y su mensaje; cancelarlo con su botón en mitad de importar
        un MDT, remuestrearlo a la rejilla del proyecto, crear un TIN desde puntos (al preparar
        las restricciones y, tras la triangulación de Blender, al terminarlo) y trazar curvas
        deja cada operación «cancelada» con su motivo y el proyecto como estaba: ningún dato,
        entrada, tabla ni fichero nuevo y los datos con el mismo hash."""
        self.start()
        before = self.state()
        flight = self.source("geotiff/f32_strip.tif", "mdt/vuelo.tif")
        cases = (
            ("gis_read_raster", IMPORT, "«MDT vuelo»",
             {"filepath": str(flight), "name": "MDT vuelo", "vertical": "PROJECT"}),
            ("gis_resample", RESAMPLE, "«Dron»", {"source": "gis_src_mdt_dron", "name": "Dron"}),
            ("gis_tin_prepare", TIN_POINTS, "«Taludes»",
             {"points": "gis_pts_taludes", "breaklines": "gis_brk_taludes", "name": "Taludes"}),
            ("gis_tin_finish", TIN_POINTS, "«Taludes»",
             {"points": "gis_pts_taludes", "breaklines": "gis_brk_taludes", "name": "Taludes"}),
            ("gis_contours", CONTOURS, "«Dron»",
             {"source": "gis_src_mdt_dron", "interval": "2", "name": "Dron"}),
        )
        for worker, idname, shown, props in cases:
            with self.subTest(trabajo=worker):
                op_uid = self.cancel_midway(worker, idname, shown, **props)
                self.assertCancelled(op_uid, before)
        # T50 (RNF-006-09): importar puntos, cancelado mientras su trabajo calcula el hash de
        # las tablas que serán lo importado (lo largo que antes hacía el hilo de Blender).
        with self.subTest(trabajo="gis_import_points"):
            op_uid = self.cancel_midway(
                "gis_import_points", IMPORT_POINTS, "«Taludes B»", at=0.6,
                message=_module("gis.jobs").TABLE_HASH_TEXT,
                **self.points_props(self.variant("taludes_b.csv"), "Taludes B"))
            self.assertCancelled(op_uid, before)
            self.assertEqual(self.gis_ops.pending_incorporations(), [])

    def test_import_is_incorporated_in_steps_with_the_hash_of_its_job(self) -> None:
        """RF-006-26, RF-006-28, RNF-006-09 (T50): al terminar el trabajo de una importación de
        puntos no se escribe nada aún; la incorporación va por pasos desde su temporizador (uno
        por llamada, varios) y el hilo de Blender no vuelve a leer las tablas (su hash es el
        que calculó el trabajo), que es el que da leerlas después en el proyecto (el mismo hash
        de antes de la T50). Un fallo en su transacción la deja «fallida» con su motivo y el
        proyecto como estaba."""
        self.start()
        before = self.state()
        registry = _module("core.datasets.registry")
        result, op_uid = self.run_op(IMPORT_POINTS, **self.points_props(
            self.variant("taludes_b.csv"), "Taludes B"))
        self.assertEqual(result, {"FINISHED"})
        runner = self.jobs_ops.MONITOR.runner
        deadline = time.monotonic() + JOB_WAIT_S
        while any(snapshot.active for snapshot in runner.snapshots()):
            self.assertLess(time.monotonic(), deadline, "el trabajo no termina")
            self.jobs_ops.tick()
            time.sleep(0.002)
        self.jobs_ops.tick()
        self.assertEqual(self.gis_ops.pending_incorporations(), [op_uid])
        self.assertEqual(self.operation(op_uid)[1], "running")
        self.assertEqual(self.state(), before)
        ticks = 0
        with mock.patch.object(registry, "_computed",
                               side_effect=AssertionError("el hilo de Blender leyó la tabla")):
            while self.gis_ops.pending_incorporations():
                self.gis_ops.incorporation_tick()
                ticks += 1
        self.assertGreaterEqual(ticks, 5)
        self.assertEqual(self.operation(op_uid)[1], "done")
        self.assertNotIn(op_uid, self.session.pending_ingests().values())
        for name in ("gis_pts_taludes_b", "gis_brk_taludes_b"):
            with self.subTest(dato=name), self.project.read() as conn:
                record = registry.get(conn, name)
                again = registry.content_digest(conn, self.project, record)
                self.assertEqual(again.content_sha256, record.content_sha256)
        self.assertIn("Taludes B", " ".join(self.ps.take_notices()))

        before = self.state()
        real = self.store.ResultWriter.write

        def failing(writer: Any, conn: Any) -> Any:
            real(writer, conn)
            raise RuntimeError("fallo provocado al incorporar")

        with mock.patch.object(self.store.ResultWriter, "write", failing):
            failed = self.launch(IMPORT_POINTS, **self.points_props(
                self.variant("taludes_c.csv", "998,998"), "Taludes C"))
        _type, status, reason, *_ = self.operation(failed)
        self.assertEqual(status, "failed")
        self.assertIn("fallo provocado al incorporar", reason)
        self.assertNotIn(failed, self.session.pending_ingests().values())
        self.assertEqual(self.state(), before)

    def finish_job(self) -> None:
        """Avanza el monitor hasta que el trabajo de la orden termina (y se llama a su aviso
        de fin), sin avanzar el temporizador de las incorporaciones."""
        runner = self.jobs_ops.MONITOR.runner
        deadline = time.monotonic() + JOB_WAIT_S
        while any(snapshot.active for snapshot in runner.snapshots()):
            self.assertLess(time.monotonic(), deadline, "el trabajo no termina")
            self.jobs_ops.tick()
            time.sleep(0.002)
        self.jobs_ops.tick()

    def test_dtm_import_is_incorporated_in_steps(self) -> None:
        """RF-006-28, RNF-006-09, RF-006-06, RF-008-19 (T54): al terminar el trabajo de la
        importación de un MDT no se escribe nada aún; la incorporación va por pasos desde su
        temporizador (la comparación de cotas con la rejilla del proyecto, con las posiciones
        que dejó el trabajo: el hilo de Blender no vuelve a leer la rejilla importada; la
        copia de la rejilla al proyecto, un trozo por paso; la transacción del final) y deja
        el dato con el hash de su trabajo. Cerrar los pasos a mitad de la copia (al quitar la
        extensión) no deja nada en el proyecto ni ningún fichero a medias en ``rasters/`` (la
        operación sigue «en curso»); un fallo del disco a mitad de la copia la deja «fallida»
        con su motivo y el proyecto como estaba."""
        self.start()
        self.launch(RESAMPLE, source="gis_src_mdt_dron", name="Dron")
        self.ps.take_notices()
        before = self.state()
        rasters = Path(self.project.root, "rasters")
        registry = _module("core.datasets.registry")
        flight = self.source("geotiff/f32_strip.tif", "mdt/vuelo.tif")
        self.enterContext(mock.patch.object(self.store, "COPY_CHUNK_BYTES", COPY_CHUNK))
        read = mock.Mock(wraps=self.store.read_geotiff)
        self.enterContext(mock.patch.object(self.store, "read_geotiff", read))
        result, op_uid = self.run_op(IMPORT, filepath=str(flight), name="MDT vuelo",
                                     vertical="PROJECT")
        self.assertEqual(result, {"FINISHED"})
        self.finish_job()
        self.assertEqual(self.gis_ops.pending_incorporations(), [op_uid])
        self.assertEqual(self.operation(op_uid)[1], "running")
        self.assertEqual(self.state(), before)
        ticks = 0
        while self.gis_ops.pending_incorporations():
            self.gis_ops.incorporation_tick()
            ticks += 1
        self.assertGreaterEqual(ticks, 8)
        _type, status, reason, message, *_ = self.operation(op_uid)
        self.assertEqual(status, "done", reason)
        self.assertIn("Mediana de la diferencia con el MDT «gis_dtm_dron»", message)
        # La comparación leyó la rejilla del proyecto, nunca la importada (en el trabajo).
        self.assertEqual({Path(call.args[0]).name for call in read.call_args_list},
                         {"gis_dtm_dron.tif"})
        self.assertNotIn(op_uid, self.session.pending_ingests().values())
        with self.project.read() as conn:
            record = registry.get(conn, "gis_src_mdt_vuelo")
            again = registry.content_digest(conn, self.project, record)
        self.assertEqual(again.content_sha256, record.content_sha256)
        self.assertSameCells(self.stored("gis_src_mdt_vuelo"), self.source_raster(flight))

        raster = self.source_raster(flight)
        before = self.state()
        disk = OSError(28, "No queda espacio en el disco")
        failing = _failing_copy(self.store._copy_steps, disk, after=3)
        cases = (("cerrada", "vuelo_b.tif", 1.0, self.store._copy_steps),
                 ("fallo", "vuelo_c.tif", 2.0, failing))
        for case, name, shift, copy_steps in cases:
            with (self.subTest(a_mitad=case),
                  mock.patch.object(self.store, "_copy_steps", copy_steps)):
                path = self.written(dataclasses.replace(raster, values=raster.values + shift),
                                    f"mdt/{name}")
                result, op_uid = self.run_op(IMPORT, filepath=str(path), name=f"MDT {case}",
                                             vertical="PROJECT")
                self.finish_job()
                while not list(rasters.glob("*.tmp-*")):  # hasta la mitad de la copia
                    self.assertTrue(self.gis_ops.pending_incorporations(), "no copia nada")
                    self.gis_ops.incorporation_tick()
                self.gis_ops.incorporation_tick()
                if case == "cerrada":
                    self.gis_ops._drop_incorporations()  # lo que hace unregister()
                    self.assertEqual(self.operation(op_uid)[1], "running")
                else:
                    while self.gis_ops.pending_incorporations():
                        self.gis_ops.incorporation_tick()
                    _type, status, reason, *_ = self.operation(op_uid)
                    self.assertEqual(status, "failed")
                    self.assertIn("No queda espacio en el disco", reason)
                    self.assertNotIn(op_uid, self.session.pending_ingests().values())
                self.assertEqual(self.gis_ops.pending_incorporations(), [])
                self.assertEqual(list(rasters.glob("*.tmp-*")), [])
                self.assertEqual(self.state(), before)

    def test_failure_while_ingesting_leaves_no_datasets(self) -> None:
        """RF-006-28, RF-008-19 (T33): un fallo provocado al incorporar el resultado (con su
        fichero ya en su sitio o su tabla ya escrita, dentro de la transacción) deja la
        operación «fallida» con el motivo y ningún dato: ni la rejilla importada con su entrada
        ni las curvas (fichero, tabla, entrada ni registro), y su trabajo, incorporado."""
        self.start()
        before = self.state()
        real = self.store.ResultWriter.write

        def failing(writer: Any, conn: Any) -> Any:
            real(writer, conn)
            raise RuntimeError("fallo provocado al incorporar")

        flight = self.source("geotiff/f32_strip.tif", "mdt/vuelo.tif")
        with mock.patch.object(self.store.ResultWriter, "write", failing):
            imported = self.launch(IMPORT, filepath=str(flight), name="MDT vuelo",
                                   vertical="PROJECT")
            contours = self.launch(CONTOURS, source="gis_src_mdt_dron", interval="2",
                                   name="Dron")
        for op_uid in (imported, contours):
            with self.subTest(operacion=op_uid):
                _type, status, reason, *_ = self.operation(op_uid)
                self.assertEqual(status, "failed")
                self.assertIn("fallo provocado al incorporar", reason)
                self.assertNotIn(op_uid, self.session.pending_ingests().values())
        self.assertEqual(self.state(), before)
        notices = " ".join(self.ps.take_notices())
        self.assertIn("fallo provocado al incorporar", notices)

    def test_import_cut_midway_is_interrupted_and_its_temporary_goes_to_orphans(self) -> None:
        """RF-006-28, RF-008-19, RF-008-22 (T33; ADR-0025 §8): Blender se cierra de golpe
        mientras incorpora una importación (su rejilla ya está en su temporal
        ``rasters/gis_src_<nombre>.tif.tmp-<sesión>``; nada más se ejecuta: ni la transacción
        ni la limpieza). Al volver a abrir el proyecto más tarde en otra sesión del mismo
        equipo, la operación queda «interrumpida» con quién la dejaba en curso, el temporal
        está en ``orphans/`` tal cual (sin borrar nada) y no hay dato ni entrada de la
        importación."""
        self.start()
        root = Path(self.project.root)
        datasets, inputs = self.state()[1:3]
        crashed: dict[str, Any] = {}

        def crash(handle: Any, *_args: Any, **_kwargs: Any) -> Any:
            crashed["temporaries"] = {path.name: _sha(path)
                                      for path in (root / "rasters").glob("*.tmp-*")}
            handle.project.set_read_only(self.core.ReadOnlyCode.LOCK_LOST,
                                         "Blender se cerró de golpe")
            raise RuntimeError("Blender se cerró de golpe")

        def nothing_runs(_writer: Any, _error: Any = None) -> None:
            """Tras cerrarse Blender no se limpia nada."""

        flight = self.source("geotiff/f32_strip.tif", "mdt/vuelo.tif")
        with (mock.patch.object(self.session, "ingest_job_result", crash),
              mock.patch.object(self.store.ResultWriter, "close", nothing_runs)):
            op_uid = self.launch(IMPORT, filepath=str(flight), name="MDT vuelo",
                                 vertical="PROJECT")
        (name, data), = crashed["temporaries"].items()
        self.assertRegex(name, r"^gis_src_mdt_vuelo\.tif\.tmp-[0-9a-f]{8}$")
        temporary = root / "rasters" / name
        self.assertTrue(temporary.is_file())
        self.assertFalse(self.project.writable)
        later = time.time_ns() - 10 * 10**9  # se vuelve a abrir más tarde
        os.utime(temporary, ns=(later, later))

        crashed_session = self.ps.session()
        other = dataclasses.replace(crashed_session, session_uid=str(uuid.uuid4()),
                                    pid=crashed_session.pid + 1)
        opened = self.core.open_project(root, other, self.ps.userdata(),
                                        pid_alive=FakePids({other.pid})).project
        self.assertTrue(opened.writable)
        self.ps.attach(opened)
        for _ in range(300):
            if self.session.check_tick() is None:
                break
        self.project = opened
        _type, status, reason, *_ = self.operation(op_uid)
        self.assertEqual(status, "interrupted")
        self.assertIn(crashed_session.user_host, reason)
        self.assertFalse(temporary.exists())
        moved = sorted((root / "orphans").rglob(name))
        self.assertEqual([_sha(path) for path in moved], [data])
        self.assertEqual(self.state()[1:3], (datasets, inputs))


if __name__ == "__main__":
    unittest.main()

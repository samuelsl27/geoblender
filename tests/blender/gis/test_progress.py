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

from tests.blender.gis.test_ops_dtm import IMPORT, JOB_WAIT_S, RESAMPLE, _module
from tests.blender.gis.test_ops_tin import TIN_POINTS, TinOperatorsCase
from tests.support.core_fixtures import FakePids

CONTOURS = "geoblender.gis_create_contours"
MIDWAY = 0.5  # el primer aviso de progreso a partir de la mitad del trabajo
NOT_PROJECT_DATA = ("cache",)  # la caché (los trabajos) no es del proyecto
DATABASE_FILES = ("project.gpkg", "project.gpkg-journal", ".lock")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
            if time.monotonic() > deadline:
                self.fail("el trabajo no llega a la mitad")

    def cancel_midway(self, worker: str, idname: str, shown: str, **props: Any) -> str:
        """Lanza la orden ``idname`` y, cuando su trabajo ``worker`` llega a la mitad, comprueba
        que la barra de estado lo enseña (``shown`` en su nombre, su avance y su mensaje) y lo
        cancela con su botón; sigue hasta que no queda nada en marcha. Devuelve el uid de la
        operación."""
        gate = _Gate(self.job_catalog.WORKERS[worker], MIDWAY)
        with mock.patch.dict(self.job_catalog._REGISTRY, {worker: gate.info}):
            try:
                result, op_uid = self.run_op(idname, **props)
                self.assertEqual(result, {"FINISHED"})
                self.wait(gate.reached)
                self.jobs_ops.tick()
                view = self.jobs_ui.current_view()
                self.assertEqual(view.active, 1)
                self.assertIn(shown, view.current.name)
                self.assertGreaterEqual(view.percent, int(MIDWAY * 100))
                self.assertEqual(self.jobs_ui.bar_text(view.current, view.percent),
                                 f"{view.current.name} · {view.percent} %")
                self.assertEqual(view.current.message, gate.message)
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

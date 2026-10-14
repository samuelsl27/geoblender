# SPDX-License-Identifier: GPL-3.0-or-later
"""El progreso de una importación grande (spec 006, T33; RF-006-28; plan 006 §5.3.4 y §5.6.4;
RNF-006-01).

Un MDT GeoTIFF de 3.399 × 3.309 celdas de 0,5 m (11,2 M; el tamaño de Silvestre, spec §5)
importado por el trabajo ``gis_read_raster`` (``workers/gis_read_raster.py``, la misma función
que corre en el hilo de Blender) con el ``WorkerContext`` de la 004: la barra de estado
(``bl.ops.jobs.JobMonitor``) enseña lo que llega a su sumidero, así que el hueco más largo
entre dos avisos de progreso (y desde que empieza hasta el primero y desde el último hasta que
termina) es lo que la persona espera sin ver avanzar la importación ni poder cancelarla (cada
aviso es un punto de cancelación).

Los huecos se miden en tiempo de CPU del hilo del trabajo (``time.thread_time``, también el
reloj del contexto): en reposo es el de pared, y no crece cuando ``tools/check.py`` llena el
equipo con otras pruebas. La fuente es una superficie suave en float32 con DEFLATE y predictor
3 escrita por ``GeoTiffIO`` (perfil ``deliverable``); el trabajo tarda unos 3 s.
"""

import threading
import time
import unittest
from unittest import mock

import numpy as np

from tests.support import jobs_fixtures as _support
from tests.support.package import import_geoblender

gis = import_geoblender("gis")
gis_jobs = import_geoblender("gis.jobs")
gis_content = import_geoblender("gis.content")
geotiff = import_geoblender("gis.geotiff")
georef = import_geoblender("core.georef")
readers = import_geoblender("core.content.readers")
protocol = import_geoblender("jobs.protocol")
job_paths = import_geoblender("jobs.paths")
worker_api = import_geoblender("jobs.worker_api")

COLUMNS, ROWS, STEP = 3399, 3309, 0.5  # 11,2 M celdas (RNF-006-01)
WEST, SOUTH = 700_000.0, 4_400_000.0
GAP_S = 0.5  # RF-006-28 (T33): un aviso de progreso al menos cada 0,5 s
CATALOG = georef.load_catalog()
CRS = CATALOG.horizontal(25830)
VERTICAL = CATALOG.vertical(5782)


class _Recorder:
    """El sumidero del trabajo: apunta cada aviso de progreso con el tiempo de CPU del hilo
    que lo envía (el del trabajo) y, si se le da ``cancel_when``, pide parar en cuanto llega
    uno que la cumple."""

    def __init__(self, cancel: threading.Event, cancel_when=None) -> None:
        self.cancel = cancel
        self.cancel_when = cancel_when
        self.events: list[tuple[float, float, str]] = []

    def send(self, event: object) -> None:
        if event.type != "progress":
            return
        self.events.append((time.thread_time(), event.frac, event.msg))
        if self.cancel_when is not None and self.cancel_when(event):
            self.cancel.set()


class BigImportProgressTest(unittest.TestCase):
    """La fuente de 11,2 M celdas se escribe una vez para la clase."""

    @classmethod
    def setUpClass(cls) -> None:
        tmp = _support.jobs_tmp(prefix="gb33-")
        cls.base = tmp.__enter__()
        cls.addClassCleanup(tmp.__exit__, None, None, None)
        registry = mock.patch.dict(readers._REGISTRY)
        registry.start()
        cls.addClassCleanup(registry.stop)
        cls.addClassCleanup(gis_content.use_table_reader, gis_content.use_table_reader(None))
        grid = gis.Grid(WEST, SOUTH + ROWS * STEP, STEP, STEP, COLUMNS, ROWS)
        east = (np.arange(COLUMNS, dtype=np.float64) + 0.5) * STEP
        north = (ROWS - 0.5 - np.arange(ROWS, dtype=np.float64)) * STEP
        values = (850.0 + 0.02 * east[None, :] + 3.0 * np.sin(east[None, :] / 37.0)
                  - 0.01 * north[:, None])
        cls.source = cls.base / "entregas" / "mdt_05m.tif"
        cls.source.parent.mkdir()
        geotiff.GeoTiffIO().write(gis.Raster(grid, values, CRS, VERTICAL), cls.source,
                                  profile="deliverable")

    def run_import(self, cancel_when=None) -> tuple[object, _Recorder, float, float]:
        """El trabajo de la importación de la fuente (en este hilo); devuelve su carpeta, lo
        que llegó al sumidero y el tiempo de CPU del hilo al empezar y al terminar (también
        si se canceló)."""
        params = {"reader": gis_content.GEOTIFF.id, "name": "MDT de 0,5 m", "settings": {},
                  "crs": {"epsg": 25830}, "vertical": {"epsg": 5782},
                  "max_cells": 100_000_000, "size": self.source.stat().st_size}
        request = protocol.new_request(gis_jobs.READ_RASTER, label="Importar el MDT",
                                       owner="gis", params=params, environment="blender",
                                       timeout_s=600.0, grace_s=gis_jobs.CANCEL_GRACE_S)
        folder = job_paths.job_dir(self.base / "jobs", request.job_uid).create()
        protocol.write_request(folder, request)
        self.folder = folder
        cancel = threading.Event()
        sink = _Recorder(cancel, cancel_when)
        ctx = worker_api.WorkerContext(protocol.read_request(folder), folder, sink,
                                       cancel_event=cancel, clock=time.thread_time,
                                       paths={gis_jobs.path_name("main"): self.source})
        main = import_geoblender("workers.gis_read_raster").main
        started = time.thread_time()
        try:
            self.summary = main(ctx)
            ctx.flush()  # el último avance retenido, como el ejecutor al acabar
        finally:
            ended = time.thread_time()
        return folder, sink, started, ended

    def test_progress_at_least_every_half_second(self) -> None:
        """RF-006-28 (T33): importar el MDT de 11,2 M celdas da un aviso de progreso al menos
        cada 0,5 s de principio a fin (copia verificada de la fuente, lectura, hash de la
        fuente, escritura de la rejilla de origen y su hash), con el avance hasta 1, y deja la
        rejilla con las 11,2 M celdas."""
        folder, sink, started, ended = self.run_import()
        times = [started, *(at for at, _frac, _msg in sink.events), ended]
        gaps = [(after - before, sink.events[index - 1][2] if index else "(inicio)")
                for index, (before, after) in enumerate(zip(times, times[1:]))]
        worst, where = max(gaps)
        self.assertLessEqual(worst, GAP_S,
                             f"{worst:.3f} s sin aviso de progreso después de «{where}» "
                             f"({len(sink.events)} avisos en {ended - started:.2f} s)")
        self.assertEqual(sink.events[-1][1], 1.0)
        fracs = [frac for _at, frac, _msg in sink.events]
        self.assertEqual(fracs, sorted(fracs))
        texts = {msg for _at, _frac, msg in sink.events}
        self.assertLessEqual({gis_jobs.COPYING_TEXT, gis_jobs.HASHING_TEXT,
                              gis_content.DIGEST_TEXT}, texts)
        grid = gis_jobs.grid_of(self.summary["grid"])
        self.assertEqual((grid.ncols, grid.nrows, self.summary["valid_cells"]),
                         (COLUMNS, ROWS, COLUMNS * ROWS))
        self.assertTrue((folder.outputs_dir / gis_jobs.OUT_SOURCE_GRID.file).is_file())

    def test_cancel_while_copying_the_source(self) -> None:
        """RF-006-28 (T33; RF-004-09): la copia verificada de la fuente también avisa de su
        progreso y es un punto de cancelación: cancelar mientras se copia para el trabajo
        (``JobCancelled``) sin dejar la copia, ni a medias, en ``in/`` ni nada en ``out/``."""

        def copying(event: object) -> bool:
            return event.msg == gis_jobs.COPYING_TEXT and 0.0 < event.frac

        # Cada aviso sale al momento: el primero de la copia ya es el de un bloque.
        with (mock.patch.object(worker_api, "PROGRESS_INTERVAL_S", 0.0),
              self.assertRaises(worker_api.JobCancelled)):
            self.run_import(cancel_when=copying)
        folder = self.folder
        left = [child.name for place in (folder.inputs_dir, folder.outputs_dir)
                if place.is_dir() for child in place.iterdir()]
        self.assertEqual(left, [])


if __name__ == "__main__":
    unittest.main()

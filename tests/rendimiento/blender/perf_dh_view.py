# SPDX-License-Identifier: GPL-3.0-or-later
"""La vista de los sondeos de V-ref dentro de Blender (spec 005, T32; RNF-005-04; plan 005
§5.6.8 y el riesgo R15 del plan).

Se ejecuta con ``tools/check.py --rendimiento`` (o, a mano, con ``tools/run_blender_tests.py
-- --carpeta tests/rendimiento/blender --patron "perf_dh_view.py"``). Los datos y el proyecto,
los de ``perf_dh_steps.py`` (:class:`perf_dh_steps.VrefCase`, en disco local): V-ref importado
con sus seis CSV, su base y su validación, y sus trazas por mínima curvatura, con las órdenes de
los sondeos, sin medir (y sin la carga de la vista que sigue a las trazas: la primera vista que
se construye es la de la medida).

**RNF-005-04** (:class:`DrillholeViewSpeedTest`): construir la vista de V-ref, los tubos de
litología (``GB_DrillTubes`` de Geometry Nodes sobre una curva ``POLY`` por tramo y por hueco)
y las barras del oro (una malla de cuadriláteros), en ≤ 3 s y con ≤ 1 GB más de memoria, con
los tubos evaluados: desde que se pide la carga de ``dh_trace`` (``bl.scene.views.load_datasets``:
la base leída del proyecto, el trabajo ``dh_view_arrays``, las curvas y la malla en la escena)
hasta su evaluación por el grafo de dependencias, dentro de la medida
(``bpy.context.evaluated_depsgraph_get().update()`` y la geometría evaluada de los dos
objetos, con el número de vértices de cada una). La de los tubos se pide con
``evaluated_get(dg).evaluated_geometry().mesh`` en vez de ``to_mesh()``, que con un objeto de
curvas con Geometry Nodes da ``RuntimeError`` (``docs/trampas.md`` §3, T29); la de las barras,
con ``to_mesh()``. La memoria es la privada del proceso (``GetProcessMemoryInfo``) tras evaluar,
menos la de antes de la carga (con la vista anterior quitada y la basura recogida). Mediana de 5
(spec 005 §5) del tiempo; de la memoria, la mayor de las cinco (la primera, con la de la carga
que estrena la vista).
"""

from __future__ import annotations

import gc
import statistics
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import bpy

from tests.rendimiento.blender import perf_dh_steps as steps
from tests.support.trees import remove_tree

VIEW_BUDGET_S = 3.0  # RNF-005-04
MEMORY_BUDGET = 1_000_000_000  # RNF-005-04: 1 GB más
REPETITIONS = 5  # spec 005 §5: 5 repeticiones, mediana
TRACE = steps.TRACE


class DrillholeViewSpeedTest(steps.VrefCase):
    """RNF-005-04 con V-ref en disco local (véase el módulo)."""

    def build(self, uid: str) -> tuple[float, float, float, int, int, int]:
        """Una vista de V-ref construida y evaluada (véase el módulo), con la anterior
        quitada: lo que tardó la carga, la evaluación y el trabajo de sus arrays, la memoria de
        más tras evaluar y los vértices evaluados de los tubos y de las barras."""
        views = self.views
        views.unload_datasets([uid])
        gc.collect()
        before = steps.private_bytes()
        runner = self.jobs_ops.MONITOR.runner
        known = {item.job_uid for item in runner.snapshots()}
        start = time.perf_counter()
        outcome = views.load_datasets(bpy.context, self.project, [TRACE])
        loaded = time.perf_counter()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        depsgraph.update()
        tubes = next(obj for obj in outcome.objects if obj.type == "CURVES")
        bars = next(obj for obj in outcome.objects if obj.type == "MESH")
        geometry = tubes.evaluated_get(depsgraph).evaluated_geometry()
        tube_mesh = geometry.mesh  # vive mientras ``geometry``
        tube_vertices = len(tube_mesh.vertices)
        evaluated_bars = bars.evaluated_get(depsgraph)
        bar_vertices = len(evaluated_bars.to_mesh().vertices)
        end = time.perf_counter()
        memory = steps.private_bytes() - before
        evaluated_bars.to_mesh_clear()
        del tube_mesh, geometry
        job = next(item for item in runner.snapshots()
                   if item.job_uid not in known and item.worker == "dh_view_arrays")
        self.assertEqual(outcome.errors, ())
        self.assertGreater(tube_vertices, 0)
        self.assertGreater(bar_vertices, 0)
        return (loaded - start, end - loaded, float(job.duration_s or 0.0), memory,
                tube_vertices, bar_vertices)

    def test_view_of_vref(self) -> None:
        """RNF-005-04 (plan §5.6.8; R15): construir la vista de V-ref (los tubos de litología
        y las barras del oro), desde que se pide su carga hasta los tubos y las barras
        evaluados por el grafo de dependencias, tarda ≤ 3 s (mediana de 5) y deja ≤ 1 GB más
        de memoria del proceso tras evaluar (la mayor de las cinco)."""
        parent = tempfile.mkdtemp(prefix="gb-t32-vw-")
        self.addCleanup(remove_tree, Path(parent))
        self.addCleanup(self.ps.close)  # antes de borrar su carpeta
        self.open_project(Path(parent))
        display = getattr(bpy.context.scene, self.props.SCENE_PROPERTY)
        display.element = steps.ELEMENT
        with mock.patch.object(self.dh_ops, "start_view", lambda project, **_: None), \
                steps.EventLoop(self, self.project) as loop:
            self.import_vref(loop)
            self.assertEqual(bpy.ops.geoblender.dh_desurvey("EXEC_DEFAULT"), {"FINISHED"})
            loop.until(lambda: self.idle() and bool(self.operations("dh.desurvey")),
                       "las trazas")
        self.jobs_ops.MONITOR.stop()
        self.assertEqual(self.view_objects(), [])
        with self.project.read() as conn:
            uid = steps.module("core.datasets.registry").get(conn, TRACE).uid
        runs = [self.build(uid) for _ in range(REPETITIONS)]
        totals = [load + evaluation for load, evaluation, *_ in runs]
        memory = max(run[3] for run in runs)
        tube_vertices, bar_vertices = runs[0][4], runs[0][5]
        steps.report(
            f"RNF-005-04: construir la vista de V-ref ({steps.count(steps.VREF_HOLES)} "
            f"sondeos: los tubos de litología, {steps.count(tube_vertices)} vértices evaluados, "
            f"y las barras de {steps.ELEMENT}, {steps.count(bar_vertices)} vértices; "
            f"{steps.MACHINE}), desde la carga hasta evaluarla: {steps.median_line(totals)}, "
            f"presupuesto {steps.number(VIEW_BUDGET_S, 1)} s (la carga, mediana "
            f"{steps.number(statistics.median(run[0] for run in runs))} s, de ella el trabajo "
            f"dh_view_arrays {steps.number(statistics.median(run[2] for run in runs))} s; la "
            f"evaluación {steps.number(statistics.median(run[1] for run in runs))} s); memoria "
            f"de más tras evaluar, la mayor de {REPETITIONS}: "
            f"{steps.number(memory / 1e9, 2)} GB (de cada una: "
            f"{', '.join(steps.number(run[3] / 1e9, 2) for run in runs)}), presupuesto "
            f"{steps.number(MEMORY_BUDGET / 1e9, 1)} GB")
        self.assertLessEqual(statistics.median(totals), VIEW_BUDGET_S)
        self.assertLessEqual(memory, MEMORY_BUDGET)


if __name__ == "__main__":
    unittest.main()

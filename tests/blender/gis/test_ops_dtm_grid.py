# SPDX-License-Identifier: GPL-3.0-or-later
"""La rejilla del proyecto desde un MDT en Blender (spec 006, T28; HU-006-1; plan 006 §5.3.5,
§5.6.1, §5.6.4 y §5.6.8).

Con el proyecto, las fuentes y el servicio de CRS de prueba de ``test_ops_dtm``
(``DtmOperatorsCase``): la orden ``geoblender.gis_resample_to_grid``, operador de la procedencia
de la 008, con su trabajo ``gis_resample`` de la 004.

- RF-006-11 (D18, RF-008-05): la rejilla del proyecto desde el MDT importado, con el método en
  el informe (media ponderada por área por defecto; bilineal a petición), las mismas celdas que
  ``gis.resample.resample_to_grid``, la fracción mínima del proyecto consumida y anotada o
  tecleada como ajuste (sin consumirla ni cambiar el parámetro).
- RF-006-05 (D11): un MDT importado en ED50 se reproyecta en un trabajo en proceso aparte con
  las ruedas de la extensión (``site_override``: pyproj de ``.deps/site``), con la
  transformación y su precisión en el informe.
- RF-008-10: con la fuente cambiada fuera, la orden lanzada desde la interfaz abre el diálogo
  Actualizar · Mantener la copia · Cancelar y no empieza.
- RF-008-26, RF-008-11: el recálculo del remuestreo y la reimportación del MDT lanzan sus
  trabajos y dejan la operación nueva sustituyendo a la anterior.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import json
import os
import shutil
import time
import unittest
from typing import Any
from unittest import mock

import numpy as np

from tests.blender.gis.test_ops_dtm import (
    DATA,
    ED50_WINDOW,
    FRACTION,
    RESAMPLE,
    SITE,
    STEP,
    DtmOperatorsCase,
    _module,
)


class DtmResampleTest(DtmOperatorsCase):
    def test_project_grid_with_the_method_in_its_report(self) -> None:
        """RF-006-11, RF-008-05, D18: la rejilla del proyecto (paso de 2 m) desde el MDT
        importado tiene las celdas de ``resample_to_grid`` con la media ponderada por área
        (el método por defecto al bajar resolución, en el informe) y la fracción mínima del
        proyecto, que el diálogo enseña con su insignia y «sin confirmar» y que, sin
        cambiarla, se consume y se anota; a petición, la bilineal con otra fracción tecleada,
        que es un ajuste: no se consume ni cambia el parámetro."""
        project = self.open()
        path = self.source("geotiff/f64_strip.tif")
        self.import_dtm(path, "MDT dron")
        # El diálogo sale con el valor del proyecto, su insignia y «sin confirmar»; sin
        # cambiarlo, la orden consume el parámetro.
        shown, note = self.gis_ops.fraction_field(project)
        self.assertEqual((shown, note), ("1", "[ADO] sin confirmar"))
        op_uid = self.launch(RESAMPLE, source="gis_src_mdt_dron", name="MDT dron",
                             min_valid_fraction=shown)
        _type, status, _reason, message, settings, software, _executor, _ = \
            self.operation(op_uid)
        self.assertEqual(status, "done")
        self.assertIn("media ponderada por área", message)
        self.assertEqual(json.loads(software), {"pyproj": "3.8.0"})
        self.assertNotIn("min_valid_fraction", json.loads(settings))
        target = self.grid.project_grid(project.window, STEP)
        expected, _report = self.resample.resample_to_grid(
            self.source_raster(path), target, method="area_mean", min_valid_fraction=1.0)
        self.assertSameCells(self.stored("gis_dtm_mdt_dron"), expected)
        self.assertEqual(json.loads(settings)["method"], "auto")
        self.assertEqual(self.rows("SELECT key, value, unconfirmed FROM gb_operation_param "
                                   "WHERE operation_uid = ?", op_uid),
                         [(FRACTION, "1.0", 1)])

        op_uid = self.launch(RESAMPLE, source="gis_src_mdt_dron", name="MDT bilineal",
                             method="BILINEAR", min_valid_fraction="0,5")
        message, settings = self.operation(op_uid)[3:5]
        self.assertIn("interpolación bilineal", message)
        self.assertEqual(json.loads(settings)["min_valid_fraction"], 0.5)
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation_param WHERE "
                                   "operation_uid = ?", op_uid), [(0,)])
        expected, _report = self.resample.resample_to_grid(
            self.source_raster(path), target, method="bilinear", min_valid_fraction=0.5)
        self.assertSameCells(self.stored("gis_dtm_mdt_bilineal"), expected)
        self.assertEqual(self.rows("SELECT value FROM gb_parameter WHERE key = ?", FRACTION),
                         [("1.0",)])

    def test_ed50_is_reprojected_in_a_separate_process(self) -> None:
        """RF-006-05, RF-006-11 (D11): remuestrear un MDT importado en ED50 lo reproyecta al
        CRS del proyecto en un trabajo en proceso aparte con las ruedas de la extensión
        (``site_override``: pyproj), con la transformación en el informe (una ventana de
        40 × 40 celdas donde cae el MDT)."""
        self.open(window=ED50_WINDOW)
        self.import_dtm(self.source("geotiff/f32_epsg23030.tif"), "Plano antiguo")
        monitor = self.jobs_ops.MONITOR
        with mock.patch.object(monitor, "submit", wraps=monitor.submit) as submitted:
            op_uid = self.launch(RESAMPLE, source="gis_src_plano_antiguo", name="Plano")
        self.assertEqual(submitted.call_args.kwargs["site_override"], SITE)
        _type, status, reason, message, _settings, _software, executor, _ = \
            self.operation(op_uid)
        self.assertEqual((status, executor), ("done", "job_process"), reason)
        self.assertIn("ED50 to ETRS89", message)
        self.assertIn("es_ign_SPED2ETV2.tif", message)
        values = self.stored("gis_dtm_plano").values
        self.assertGreater(int(np.count_nonzero(np.isfinite(values))), 500)

    def test_changed_source_opens_the_input_dialog(self) -> None:
        """RF-008-10, RF-008-61: con la fuente del MDT cambiada fuera de Geoblender, la orden
        lanzada desde la interfaz abre el diálogo Actualizar · Mantener la copia · Cancelar de
        esa entrada y no empieza el remuestreo."""
        self.open()
        path = self.source("geotiff/f64_strip.tif")
        self.import_dtm(path, "MDT dron")
        (input_uid,) = self.rows("SELECT uid FROM gb_input WHERE name = 'MDT dron'")[0]
        shutil.copyfile(DATA / "geotiff" / "f32_strip.tif", path)
        later = time.time() + 10
        os.utime(path, (later, later))
        opened: list[Any] = []

        def spy(reason: Any) -> set[str]:
            opened.append(reason)
            return {"CANCELLED"}

        cls = _module("bl.ui.commands").registered_class(RESAMPLE)
        with (mock.patch.object(self.session, "open_input_dialog", spy),
              mock.patch.object(cls, "provenance_dialog", True)):
            result, op_uid = self.run_op(RESAMPLE, source="gis_src_mdt_dron", name="MDT")
        self.assertEqual((result, op_uid), ({"CANCELLED"}, None))
        self.assertEqual([reason.uid for reason in opened], [input_uid])
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation WHERE op_type = "
                                   "'gis.resample'"), [(0,)])

    def test_recompute_and_reimport_launch_their_jobs(self) -> None:
        """RF-008-26, RF-008-11 (plan §5.6.8): con la fracción mínima del proyecto cambiada, el
        recálculo del remuestreo lanza su trabajo y la operación nueva sustituye a la
        anterior; reimportar la entrada del MDT (su fuente, otra entrega) lanza la importación
        con sus ajustes registrados como una entrada nueva que la sustituye."""
        project = self.open()
        path = self.source("geotiff/f64_strip.tif")
        self.import_dtm(path, "MDT dron")
        old = self.launch(RESAMPLE, source="gis_src_mdt_dron", name="MDT dron")
        params = _module("core.params")
        with project.write_transaction() as conn:
            params.ParameterStore(project).change(
                conn, FRACTION, value=0.5, kind="ADOPTADO", source="Criterio de la prueba",
                source_kind="document", decided_by="la prueba", reason="Media cobertura")
        recompute = _module("core.provenance.recompute")
        steps = recompute.recompute_steps(project)
        for step in steps:
            self.jobs_ops.tick()
            time.sleep(0.002)
        (unit,) = step.result.results
        self.assertEqual(str(unit.status), "done", unit)
        (new,) = unit.operations
        self.assertEqual(self.operation(new)[1], "done")
        self.assertEqual(self.operation(new)[7], old)
        self.assertEqual(self.rows("SELECT value FROM gb_operation_param WHERE operation_uid = ?",
                                   new), [("0.5",)])

        (input_uid,) = self.rows("SELECT uid FROM gb_input WHERE name = 'MDT dron'")[0]
        shutil.copyfile(DATA / "geotiff" / "f32_strip.tif", path)
        importer = _module("core.provenance.importer")
        handle = importer.reimport_input(project, input_uid, "Nueva entrega del vuelo")
        self.finish()
        self.assertEqual(self.operation(handle.uid)[1], "done")
        self.assertEqual(self.rows("SELECT status FROM gb_input WHERE uid = ?", input_uid),
                         [("superseded",)])
        (current,) = self.rows("SELECT previous_uid, status_reason FROM gb_input WHERE "
                               "name = 'MDT dron' AND status = 'current'")
        self.assertEqual(current[0], input_uid)
        self.assertSameCells(self.stored("gis_src_mdt_dron"), self.source_raster(path))


if __name__ == "__main__":
    unittest.main()

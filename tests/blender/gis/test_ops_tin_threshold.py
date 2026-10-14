# SPDX-License-Identifier: GPL-3.0-or-later
"""Dónde se triangula un TIN en Blender (spec 006, T29; plan 006 §5.3.4, §9 y A10; D-12).

Con la cadena de ``test_ops_tin`` (``TinOperatorsCase``) y los taludes importados: la
estimación de la CDT de Blender (``bl.scene.triangulator.SECONDS_PER_POINT``) se cambia para
caer en cada tramo.

- RF-006-13, RF-006-28, RNF-006-09 (D-12): estimada entre 1 y 2 s, la triangulación se avisa
  antes en la barra de estado (y en los avisos) y corre en el siguiente paso del temporizador
  con la CDT de Blender; por encima del umbral del proyecto (``gis.tin.blender_cdt_max_s``,
  2 s), en el trabajo ``gis_triangulate`` (``PureTriangulator``), que queda en ``software``.
  Su política (siempre en proceso aparte) la prueba ``tests/unit/workers/test_gis_workers``;
  aquí corre en el hilo para no pagar el arranque de otro proceso.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import dataclasses
import json
import time
import unittest
from unittest import mock

import numpy as np

from tests.blender.gis.test_ops_dtm import _module
from tests.blender.gis.test_ops_tin import TIN_POINTS, TinOperatorsCase


class TriangulationThresholdTest(TinOperatorsCase):
    def test_announced_in_process_and_job_above_the_threshold(self) -> None:
        """RF-006-13, RF-006-28, RNF-006-09 (D-12): con la triangulación estimada entre 1 y
        2 s, el temporizador primero la avisa («Triangulando 44 puntos (unos 1,8 s)…») y la
        hace en su siguiente paso con la CDT de Blender; estimada por encima del umbral del
        proyecto (2 s), va al trabajo ``gis_triangulate`` (``PureTriangulator``), que queda en
        la procedencia."""
        self.open()
        self.import_csv("points/taludes.csv", "Taludes")
        triangulator = _module("bl.scene.triangulator")
        self.ps.take_notices()
        with mock.patch.object(triangulator, "SECONDS_PER_POINT", 0.04):
            _result, uid = self.run_op(TIN_POINTS, points="gis_pts_taludes",
                                       breaklines="gis_brk_taludes", name="Lento")
            for _ in range(2000):  # hasta que la preparación termina
                self.jobs_ops.tick()
                if self.gis_ops.pending_triangulations():
                    break
                time.sleep(0.002)
            self.assertEqual(len(self.gis_ops.pending_triangulations()), 1)
            self.gis_ops.triangulation_tick()
            self.assertIn("Triangulando 44 puntos (unos 1,8 s)…", self.ps.take_notices())
            self.assertEqual(len(self.gis_ops.pending_triangulations()), 1)
            self.settle()
        self.assertEqual(json.loads(self.operation(uid)[5]),
                         {"triangulator": triangulator.NAME})
        catalog = _module("jobs.catalog")
        info = catalog.WORKERS["gis_triangulate"]
        self.assertEqual(info.policy, "subprocess")
        with (mock.patch.object(triangulator, "SECONDS_PER_POINT", 0.1),
              mock.patch.dict(catalog._REGISTRY,
                              {info.name: dataclasses.replace(info, policy="auto")})):
            uid = self.chain(TIN_POINTS, points="gis_pts_taludes",
                             breaklines="gis_brk_taludes", name="Grande")
        _type, status, _reason, _message, _settings, software, _executor, _ = \
            self.operation(uid)
        self.assertEqual((status, json.loads(software)), ("done", {"triangulator": "pure@1"}))
        self.assertTrue(np.array_equal(self.tin_file("gis_tin_grande").vertices,
                                       self.tin_file("gis_tin_lento").vertices))


if __name__ == "__main__":
    unittest.main()

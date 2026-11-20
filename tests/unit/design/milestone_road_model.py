# SPDX-License-Identifier: GPL-3.0-or-later
"""Pruebas de hito de «test_road_model» (spec 017, T05; plan 017 §2.1 y §5.1; RF-017-01, RF-017-02, RNF-017-09): lo que cuesta
casi un segundo en un proceso nuevo. El «verde» deja en ``test_road_model`` lo que cubre cada RF (los modos, las peticiones,
los trabajos, los resultados y, por el árbol sintáctico, que ``design.model`` no importa los datos de la pista y que estos no
importan ``design.road_profiles`` al importarse); esto lo ejecuta el paso «hito» de ``tools/check.py --completo`` (la
publicación lo pide siempre).

Es lo que no cabe en el presupuesto de ``check.py`` (≤ +3 s para toda la 017, RNF-017-09): importar ``design.model`` (lo que
hace habilitar Geoblender) y comprobar en ``sys.modules``, **en un proceso nuevo** (en este ya los cargaron otras pruebas), que
``design.road_model`` y ``design.road_profiles`` no están; que pedir ``design.road_model`` no trae ``design.road_profiles``; y
que construir un ``RoadJob`` sí lo trae, una vez (RNF-001-03).
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest

from tests.support.repo import ROOT

PROBE = """
import sys
from tests.support.package import import_geoblender
model = import_geoblender("design.model")
params = import_geoblender("design.params")
provenance = import_geoblender("design.provenance")
assert "geoblender.design.road_model" not in sys.modules, "cargado al importar design.model"
assert "geoblender.design.road_profiles" not in sys.modules, "cargado al importar design.model"
road_model = import_geoblender("design.road_model")
assert "geoblender.design.road_profiles" not in sys.modules, "road_model carga road_profiles al importarse"
assert [mode.value for mode in road_model.RoadMode] == list(provenance.ROAD_MODES)
assert not hasattr(model, "RoadRequest")
import numpy as np
gis = import_geoblender("gis")
road_profiles = import_geoblender("design.road_profiles")  # lo pide quien arma el perfil de un trabajo
profile = road_profiles.RoadProfile("pista_principal", "PISTA_PRINCIPAL", 3.5, 3.0, 0.0, 1.0, 10.0, 1.0, 10.0, 20.0, 12.0,
                                    60.0, 35.0, 60.0, "Pista de acceso")
grid = gis.Grid(west=500000.0, north=4400000.0, dx=2.0, dy=2.0, ncols=8, nrows=6)
request = road_model.RoadRequest(name="Acceso", fields=road_model.LayerFields(layer="puntos"), mode="trace",
                                 profile="pista_principal", start="gis_dtm_tajo")
shape = grid.shape
route = road_model.RouteParams(4.0, 0.28, 14.0, 2.0, 4.0, 60.0, 4.0, 0.28)
job = road_model.RoadJob(
    request, "RDW-001", profile, grid, np.zeros(shape), np.ones(shape, bool), np.ones(shape, bool), np.zeros(shape, bool),
    road_model.RoadGeometry(origin=(500002.0, 4399996.0), destination=(500012.0, 4399990.0)), route)
assert job.route.search_budget == 5_000_000
print("ok")
"""


class LazyTest(unittest.TestCase):
    def test_importing_the_model_does_not_create_the_road_data_and_the_road_data_do_not_load_the_profiles(self) -> None:
        """RF-017-01, RF-017-02, RNF-001-03: importar ``design.model`` (lo que hace habilitar) no importa ``design.road_model``
        ni ``design.road_profiles``; pedir los datos de la pista no trae los perfiles; y construir un trabajo con un perfil
        de pista sí funciona y le da el presupuesto de estados por defecto del parámetro. Se mira en un proceso nuevo: en
        este ya los cargaron otras pruebas."""
        done = subprocess.run(
            [sys.executable, "-B", "-s", "-X", "utf8", "-c", PROBE], cwd=ROOT, check=False, capture_output=True,
            text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "ok"), done.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()

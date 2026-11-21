# SPDX-License-Identifier: GPL-3.0-or-later
"""La capa propuesta del trazado frente a QGIS 4.2 (spec 017, T27; HU-017-1 y HU-017-4; RF-017-28, RF-008-56; plan 017 §5.2.3, §5.7 P-8 y §7.1; D-19; la gemela, para ``des_rpl_<nombre>_<vNN>``, de
``test_ref_road_layer_qgis``, que prueba la capa de ejes, **no editable**).

Caso de referencia: V01 con **una propuesta del trazado** (la rampa de la referencia de IMGA, que es de las pruebas) con su capa de verdad (``des_rpl_trazado_a_v01``, la que escribe ``des.road_propose`` en la
transacción de la operación) y, sobre una **copia** del GeoPackage del proyecto (QGIS puede pasar a WAL lo que abre: ``docs/trampas.md`` §6), QGIS 4.2 (``GEOBLENDER_QGIS_DIR``) por PyQGIS sin interfaz, con su
GDAL y un perfil temporal:

- **La abre como una línea con Z** (RF-017-28): ``LineStringZ`` válida, no multiparte, con las estaciones del eje y **la rasante en la Z** de cada vértice (bit a bit, las del cálculo).
- **Es editable** (P-8, D-19): a diferencia de la capa de ejes, **no** tiene el campo ``fid`` ni el ``name`` de solo lectura, ni nota de «no se edita a mano»; **se puede poner en edición, cambiar su
  geometría (mover un vértice y su Z) y su nombre y guardar** (``commitChanges``) sin error, y lo guardado es lo que lee Geoblender de vuelta (``read_route_layer``): la geometría con su Z y el nombre nuevos.
- **No lleva estilo de Geoblender** (no es una capa de versión de las que estila): QGIS la abre con el suyo por defecto.

Sin QGIS (sin la variable, o sin su GDAL) la clase se omite con «[ENTORNO] qgis», que ``tools/check.py`` cuenta como «VERDE CON OMISIONES»; la T27 no se cierra sin una ejecución con QGIS anotada.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from typing import Any, ClassVar

import numpy as np

from tests.support import qgis
from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender
from tests.support.resources import requires
from tests.unit.design.milestone_road_propose import NAME, TABLE, ProposeCase
from tests.unit.design.test_road_prepare import request

road_layer = import_geoblender("design.road_layer")

LINESTRING_Z = 1002
"""``Qgis.WkbType.LineStringZ``."""
MOVED_NAME = "Trazado A editado en QGIS"
DY_M, DZ_M = 5.0, 0.5
"""Lo que se mueve el segundo vértice en QGIS (m): al norte y arriba."""

EDIT_SCRIPT = r"""
import json
import sys

from qgis.core import Qgis, QgsGeometry, QgsLineString, QgsPoint, QgsVectorLayer

gpkg, table, dy, dz, new_name = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4]), sys.argv[5]


def plain(value):
    return getattr(value, "value", value)


layer = QgsVectorLayer(f"{gpkg}|layername={table}", table, "ogr")
config = layer.editFormConfig()
found = {"qgis": Qgis.version(), "valid": layer.isValid(), "wkb": int(plain(layer.wkbType())), "features": layer.featureCount(), "layer_read_only": layer.readOnly(),
         "fields": [field.name() for field in layer.fields()], "read_only": [config.readOnly(index) for index in range(layer.fields().count())]}
feature = next(layer.getFeatures())
line = feature.geometry().constGet()
found["multi"] = feature.geometry().isMultipart()
found["valid_geometry"] = feature.geometry().isGeosValid()
found["points"] = [[line.xAt(i), line.yAt(i), line.zAt(i)] for i in range(line.numPoints())]
found["started"] = layer.startEditing()
points = [QgsPoint(line.xAt(i), line.yAt(i) + (dy if i == 1 else 0.0), line.zAt(i) + (dz if i == 1 else 0.0)) for i in range(line.numPoints())]
found["changed_geometry"] = layer.changeGeometry(feature.id(), QgsGeometry(QgsLineString(points)))
found["changed_name"] = layer.changeAttributeValue(feature.id(), layer.fields().indexOf("name"), new_name)
found["committed"] = layer.commitChanges()
found["errors"] = layer.commitErrors()
print("RESULT" + json.dumps(found))
"""
"""El guion de PyQGIS: abre la capa propuesta de una copia del GeoPackage (``argv``: la copia, la tabla, lo que sube el segundo vértice en y y en Z y el nombre nuevo), dice lo que ve (válida, tipo,
campos y cuáles son de solo lectura, la línea con su Z), la pone en edición, cambia su geometría y su nombre y guarda."""


@requires(qgis.QGIS, qgis.QGIS_HINT)
class QgisRouteLayerReferenceTest(ProposeCase):
    """V01 con una propuesta del trazado y su capa de verdad, abierta, editada y guardada con QGIS en una copia (véase el módulo)."""

    seen: ClassVar[dict[str, Any]]
    outcome: ClassVar[Any]
    copy: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        started = cls.enterClassContext(qgis.PyqgisProcess(EDIT_SCRIPT))  # QGIS arranca (≈ 1 s) mientras se prepara el proyecto
        super().setUpClass()
        cls.outcome = cls.propose(request(NAME))[1]
        out = cls.enterClassContext(project_tmp("gb-rr-"))
        copy = out / "copia"
        copy.mkdir()
        cls.copy = copy / "project.gpkg"
        shutil.copyfile(cls.project.database_path, cls.copy)
        result = started.finish(str(cls.copy), TABLE, str(DY_M), str(DZ_M), MOVED_NAME)
        if result.returncode != 0:
            raise RuntimeError(f"PyQGIS no abrió la capa: {qgis.output_of(result)}")
        (line,) = [text for text in result.stdout.splitlines() if text.startswith("RESULT")]
        cls.seen = json.loads(line.removeprefix("RESULT"))

    def test_a_it_opens_as_a_line_with_z_and_the_z_of_each_vertex_is_the_grade(self) -> None:
        """RF-017-28: ``des_rpl_trazado_a_v01`` se abre en QGIS como **una línea con Z** (``LineStringZ``, no multiparte, válida) con **una** línea, cuyos vértices son las estaciones del eje y **la Z de
        cada uno, su rasante** (las x, y y z del cálculo, bit a bit)."""
        seen = self.seen
        self.assertTrue(seen["valid"])
        self.assertEqual((seen["wkb"], seen["features"]), (LINESTRING_Z, 1))
        self.assertTrue(seen["valid_geometry"] and not seen["multi"])
        wanted = np.column_stack([self.outcome.axis.points, self.outcome.levels])
        self.assertEqual(np.array(seen["points"], dtype=np.float64).tobytes(), wanted.tobytes())

    def test_b_it_is_editable_unlike_the_roads_layer(self) -> None:
        """RF-017-28, P-8, D-19: la capa propuesta **no** tiene ningún campo de solo lectura (ni ``fid`` ni ``name``), no es de solo lectura como capa, no lleva el estilo de las capas de versión de
        Geoblender (ni nota de «no se edita a mano») y su dato es **editable a mano** (``qgis_editable``)."""
        seen = self.seen
        self.assertEqual(seen["fields"], ["fid", *road_layer.ROUTE_COLUMN_NAMES])
        self.assertFalse(any(seen["read_only"]), dict(zip(seen["fields"], seen["read_only"], strict=True)))
        self.assertFalse(seen["layer_read_only"])
        self.assertTrue(self.record().qgis_editable)
        conn = sqlite3.connect(self.copy)
        try:
            styled = conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'layer_styles'").fetchone()
            self.assertIsNone(None if styled is None else conn.execute("SELECT 1 FROM layer_styles WHERE f_table_name = ?", (TABLE,)).fetchone())
        finally:
            conn.close()

    def test_c_qgis_edits_its_geometry_and_name_and_saves_without_error_and_geoblender_reads_it_back(self) -> None:
        """RF-017-28, P-8: QGIS **pone la capa en edición, mueve un vértice y su Z, cambia el nombre y guarda sin error**; lo guardado es lo que lee Geoblender de vuelta (``read_route_layer``): el
        segundo vértice 5 m al norte y 0,5 m más arriba, el resto de las estaciones **bit a bit como estaban**, y el nombre nuevo."""
        seen = self.seen
        self.assertTrue(seen["started"] and seen["changed_geometry"] and seen["changed_name"] and seen["committed"], seen)
        self.assertTrue(all(message.startswith("SUCCESS") for message in seen["errors"]), seen["errors"])  # ``commitErrors`` también cuenta lo que fue bien
        conn = sqlite3.connect(self.copy)
        try:
            (line,) = road_layer.read_route_layer(conn, TABLE)
        finally:
            conn.close()
        before = np.column_stack([self.outcome.axis.points, self.outcome.levels])
        wanted = before.copy()
        wanted[1] += np.array([0.0, DY_M, DZ_M])
        self.assertEqual(line.name, MOVED_NAME)
        self.assertLessEqual(float(np.abs(line.points - wanted).max()), 1e-9)
        self.assertTrue(np.array_equal(np.delete(line.points, 1, axis=0), np.delete(before, 1, axis=0)))


if __name__ == "__main__":
    import unittest

    unittest.main()

# SPDX-License-Identifier: GPL-3.0-or-later
"""La capa de ejes de pistas de una versión frente a QGIS 4.2 (spec 017, T26; HU-017-1 y HU-017-3; RF-017-27, RF-012-20, RF-015-27, RF-008-56; plan 017 §5.2.3 y §7.1; D-19; la gemela de
``test_ref_declared_qgis`` para ``des_rax_<vNN>``).

Caso de referencia: V01 con **una pista** (la rampa de la referencia de IMGA, que es de las pruebas) calculada y su capa de ejes de verdad (``des_rax_v01``, la que escribe ``des.road_layer`` tras cada orden
de pistas, con su estilo en la misma transacción) y, en una **copia** del GeoPackage del proyecto, una capa de ejes de prueba (``des_rax_v99``) con las columnas de ``design.road_layer``, seis pistas de tres
clases en todos los estados y su estilo escrito por ``insert_version_styles``. La referencia externa es QGIS 4.2 (``GEOBLENDER_QGIS_DIR``): PyQGIS sin interfaz, con su GDAL y un perfil temporal, sobre esa
copia (QGIS puede pasar a WAL lo que abre: ``docs/trampas.md`` §6):

- **La geometría** (RF-017-27): líneas **con Z** (``LineStringZ``, no multipartes, válidas) cuyos vértices son las estaciones del eje de la pista, **con la rasante en su Z** (bit a bit, las de ``des_rdx_``).
- **El estilo por clase** (RF-017-27, RF-012-20): la capa se abre con el estilo por defecto de ``layer_styles``: un renderizador por reglas con **una categoría por clase** (el campo ``class_name``) y por estado
  (normal, atenuada si está descartada y marcada si perdió el apoyo), más «otra clase»; cada pista cae en **una** sola regla; los símbolos son líneas, con el color de su clase.
- **La marca «no editable»** (RF-008-56, D-19): QGIS da por de solo lectura **todos** los campos (``fid`` y las columnas) y enseña la nota de la capa; la marca de **capa** no viaja en el estilo (QGIS 4.2
  la ignora): la protección de la capa entera es el bloqueo de RF-008-56 (``qgis_editable`` falso en el dato).
- **Los valores** (RF-017-27): lo que lee QGIS son los de la tabla (el código, el nombre, la clase, el estado, el perfil y las cifras, con las que faltan sin valor).

Sin QGIS (sin la variable, o sin su GDAL) la clase se omite con «[ENTORNO] qgis», que ``tools/check.py`` cuenta como «VERDE CON OMISIONES»; la T26 no se cierra sin una ejecución con QGIS anotada.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from tests.support import qgis
from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender
from tests.support.resources import requires
from tests.unit.design.milestone_road_layer import SingleRoadCase
from tests.unit.gis.masks.test_declared_blocked import core_operations_registered

cstyles = import_geoblender("core.constraints.styles")
gpkg = import_geoblender("core.gpkg")
road_layer = import_geoblender("design.road_layer")
provenance = import_geoblender("design.provenance")

REAL = "des_rax_v01"
"""La capa de ejes de verdad de V01 (``des.road_layer``)."""
TEST = "des_rax_v99"
"""La capa de ejes de prueba, en la copia (una versión que el proyecto no tiene: no choca con la real)."""
ROWS = (
    ("RDW-001", "Principal 1", "Principal", "current", 100.0),
    ("RDW-002", "Principal 2", "Principal", "stale", 110.0),
    ("RDW-003", "Principal 3", "Principal", "discarded", 120.0),
    ("RDW-004", "Principal 4", "Principal", "support_removed", 130.0),
    ("RDW-005", "Secundaria 1", "Secundaria", "current", 140.0),
    ("RDW-006", "Terciaria 1", "Terciaria", "current", 150.0),
)
"""Las pistas de la capa de prueba: (código, nombre, clase, estado, cota de inicio); las clases del estilo son las dos primeras y la tercera, «otra»."""
STYLED = ("Principal", "Secundaria")
LINE = 1
"""``Qgis.SymbolType.Line``."""
LINESTRING_Z = 1002
"""``Qgis.WkbType.LineStringZ``."""

INSPECT_SCRIPT = r"""
import json
import sqlite3
import sys

from osgeo import gdal
from qgis.core import (Qgis, QgsExpression, QgsExpressionContext, QgsLayerNotesUtils,
                       QgsVectorLayer)
from qgis.PyQt.QtXml import QDomDocument

gdal.UseExceptions()
gpkg, names, probe = sys.argv[1], json.loads(sys.argv[2]), sys.argv[3]


def plain(value):
    return getattr(value, "value", value)


def matching(layer, feature):
    context = QgsExpressionContext()
    context.setFields(layer.fields())
    context.setFeature(feature)
    labels = []
    for rule in layer.renderer().rootRule().children():
        if rule.filterExpression() == "ELSE":
            continue
        expression = QgsExpression(rule.filterExpression())
        expression.prepare(context)
        if expression.evaluate(context):
            labels.append(rule.label())
    return labels


def look(symbol):
    layer = symbol.symbolLayer(0)
    found = {"type": int(plain(symbol.type())), "color": symbol.color().name()}
    if int(plain(symbol.type())) == 1:
        found.update({"alpha": layer.color().alpha(), "pen_style": int(plain(layer.penStyle())), "width": layer.width()})
    return found


found = {"qgis": Qgis.version(), "layers": {}}
for name in names:
    layer = QgsVectorLayer(f"{gpkg}|layername={name}", name, "ogr")
    info = {"valid": layer.isValid(), "features": layer.featureCount(), "wkb": int(plain(layer.wkbType()))}
    renderer = layer.renderer()
    info["renderer"] = renderer.type()
    rules = renderer.rootRule().children() if renderer.type() == "RuleRenderer" else []
    info["rules"] = [[rule.label(), rule.filterExpression(), look(rule.symbol())] for rule in rules]
    config = layer.editFormConfig()
    info["fields"] = [field.name() for field in layer.fields()]
    info["read_only"] = [config.readOnly(index) for index in range(layer.fields().count())]
    info["notes"] = QgsLayerNotesUtils.layerNotes(layer)
    info["layer_read_only"] = layer.readOnly()
    info["matches"] = [[[str(value) for value in feature.attributes()], matching(layer, feature)]
                       for feature in layer.getFeatures()] if rules else []
    info["geometry"] = []
    for feature in layer.getFeatures():
        geometry = feature.geometry()
        line = geometry.constGet()
        info["geometry"].append({
            "valid": geometry.isGeosValid(), "wkb": int(plain(geometry.wkbType())), "multi": geometry.isMultipart(),
            "points": [[line.xAt(i), line.yAt(i), line.zAt(i)] for i in range(line.numPoints())], "length": geometry.length()})
    found["layers"][name] = info
connection = sqlite3.connect(f"file:{gpkg}?mode=ro", uri=True)
row = connection.execute("SELECT styleQML FROM layer_styles WHERE f_table_name = ?", (probe,)).fetchone()
connection.close()
found["layer_flag"] = None
if row is not None:
    marked = row[0].replace("<qgis version", '<qgis readOnly="1" version', 1)
    assert marked != row[0]
    document = QDomDocument()
    document.setContent(marked)
    layer = QgsVectorLayer(f"{gpkg}|layername={probe}", probe, "ogr")
    result = layer.importNamedStyle(document)
    found["layer_flag"] = {"applied": bool(plain(result[0]) if isinstance(result, tuple) else result),
                           "read_only": layer.readOnly(), "editing": layer.startEditing()}
print("RESULT" + json.dumps(found))
"""
"""El guion de PyQGIS: el GeoPackage (una copia), las capas a mirar y la capa con la que se prueba la marca de capa de solo lectura; en la salida, lo que ve QGIS de cada capa (válida, tipo de geometría,
reglas con su símbolo, campos y cuáles son de solo lectura, nota y marca de capa, las reglas que cumple cada pista y la geometría con sus vértices) y qué hace con ``readOnly="1"`` en un estilo."""


@requires(qgis.QGIS, qgis.QGIS_HINT)
class QgisRoadLayerReferenceTest(SingleRoadCase):
    """V01 con una pista y su capa de ejes de verdad, y una capa de ejes de prueba en la copia, vistas con QGIS (véase el módulo)."""

    seen: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        started = cls.enterClassContext(qgis.PyqgisProcess(INSPECT_SCRIPT))  # QGIS arranca (≈ 1 s) mientras se prepara el proyecto
        super().setUpClass()
        cls.enterClassContext(core_operations_registered())
        cls.clock.advance(minutes=1)
        cls.after_chain()
        out = cls.enterClassContext(project_tmp("gb-rq-"))
        copy = out / "copia"
        copy.mkdir()
        target = copy / "project.gpkg"
        shutil.copyfile(cls.project.database_path, target)
        cls.write_test_layer(target)
        result = started.finish(str(target), json.dumps([REAL, TEST]), REAL)
        if result.returncode != 0:
            raise RuntimeError(f"PyQGIS no abrió las capas: {qgis.output_of(result)}")
        (line,) = [text for text in result.stdout.splitlines() if text.startswith("RESULT")]
        cls.seen = json.loads(line.removeprefix("RESULT"))

    @classmethod
    def after_chain(cls) -> None:
        """Lo que sigue a la orden de pistas: la capa de ejes de verdad, con su estilo."""
        entity_store = import_geoblender("design.entity_store")
        for _step in entity_store.after_entity_change(cls.project, cls.v1.uid):
            pass

    @classmethod
    def write_test_layer(cls, path: Path) -> None:
        """La capa de ejes de prueba (:data:`ROWS`) en ``path`` (la copia), con el formato y la escritura de ``design.road_layer`` y su estilo por defecto."""
        srs = cls.project.record.crs_epsg
        rows = []
        for number, (code, name, class_name, state, z0) in enumerate(ROWS):
            west = 725_000.0 + 100.0 * number
            points = np.array([[west, 4_400_000.0, z0], [west + 40.0, 4_400_020.0, z0 + 2.0], [west + 80.0, 4_400_000.0, z0 + 3.5]])
            rows.append(road_layer.RoadLayerRow(code=code, name=name, class_name=class_name, state=state, profile="PISTA_PRINCIPAL", points=points, length_m=95.0, z_start_m=z0, z_end_m=z0 + 3.5,
                                                drop_m=3.5, gradient_mean_pct=3.7, gradient_max_pct=5.0, radius_min_m=None if number % 2 else 25.0, width_m=10.5, section_m=11.5))
        db = gpkg.GpkgConnection.open_write(path)
        try:
            with db.transaction() as conn:
                road_layer.write_road_layer(conn, TEST, rows[:5], srs_id=srs)  # las pistas de las dos clases del estilo...
                assert cstyles.insert_version_styles(conn, [TEST]) == (TEST,)
                road_layer.write_road_layer(conn, TEST, rows)  # ...y una clase que aparece después, sin rehacer el estilo (como si lo hubiese guardado otra persona)
        finally:
            db.close()

    def layer(self, name: str) -> dict[str, Any]:
        info = self.seen["layers"][name]
        self.assertTrue(info["valid"], name)
        return info

    def test_a_the_real_layer_is_a_line_with_z_and_the_z_of_each_vertex_is_the_gradient(self) -> None:
        """RF-017-27: ``des_rax_v01`` se abre en QGIS como **una línea con Z** (``LineStringZ``, no multiparte, válida) con **una pista**, cuyos vértices son las estaciones de su eje y **la Z de cada uno, su
        rasante** (las x, y y z de su ``des_rdx_``, bit a bit)."""
        info = self.layer(REAL)
        self.assertEqual((info["wkb"], info["features"]), (LINESTRING_Z, 1))
        (geometry,) = info["geometry"]
        self.assertTrue(geometry["valid"] and not geometry["multi"])
        self.assertEqual(geometry["wkb"], LINESTRING_Z)
        self.assertEqual(np.array(geometry["points"], dtype=np.float64).tobytes(), self.axis_of("Pista de la rampa").tobytes())
        self.assertGreater(geometry["length"], 100.0)

    def test_b_the_real_layer_opens_with_the_style_by_class_and_every_field_read_only(self) -> None:
        """RF-017-27, RF-012-20, RF-008-56, D-19: ``des_rax_v01`` se abre **con su estilo por defecto**, escrito por la operación en su transacción: un renderizador por reglas con **una categoría por clase
        normativa** (la de la pista) y «otra clase», cada una en sus tres estados (seis reglas), y la pista cae en **una** sola, la de su clase; sus campos (``fid`` y las catorce columnas) son de solo lectura
        todos y la capa lleva su nota; la marca de capa no viaja en el estilo y el dato no es editable a mano."""
        info = self.layer(REAL)
        self.assertEqual(info["renderer"], "RuleRenderer")
        labels = [label for label, _condition, _symbol in info["rules"]]
        class_name = self.layer_rows()["RDW-001"].class_name
        self.assertEqual(labels, [class_name, f"{class_name} descartada", f"{class_name} con el apoyo retirado", cstyles.ROAD_OTHER_LABEL, f"{cstyles.ROAD_OTHER_LABEL} descartada",
                                  f"{cstyles.ROAD_OTHER_LABEL} con el apoyo retirado"])
        ((attributes, matched),) = info["matches"]
        self.assertEqual(matched, [class_name])
        self.assertEqual(attributes[1:3], ["RDW-001", "Pista de la rampa"])
        self.assertEqual(info["fields"], ["fid", *road_layer.COLUMN_NAMES])
        self.assertTrue(all(info["read_only"]), dict(zip(info["fields"], info["read_only"], strict=True)))
        self.assertIn("no se edita a mano", info["notes"])
        self.assertFalse(info["layer_read_only"], "la marca de capa no viaja en el estilo (RF-008-56 la protege)")
        self.assertFalse(self.layer_record().qgis_editable)
        flag = self.seen["layer_flag"]
        self.assertIsNotNone(flag, "la capa no tiene estilo por defecto en layer_styles")
        self.assertTrue(flag["applied"] and not flag["read_only"] and flag["editing"], flag)

    def test_c_each_road_falls_in_one_rule_by_class_and_state(self) -> None:
        """RF-017-27, RF-012-20: en la capa de prueba cada pista cae en **una** regla: de su clase si el estilo la conoce (la normal, la **atenuada** si está descartada o la **marcada** si perdió el apoyo) y,
        si no, en «otra clase»; 3 clases × 3 estados, sin solaparse."""
        info = self.layer(TEST)
        self.assertEqual((info["renderer"], info["wkb"], len(info["rules"])), ("RuleRenderer", LINESTRING_Z, 9))
        other = cstyles.ROAD_OTHER_LABEL
        expected = {
            "RDW-001": ["Principal"], "RDW-002": ["Principal"], "RDW-003": ["Principal descartada"], "RDW-004": ["Principal con el apoyo retirado"],
            "RDW-005": ["Secundaria"], "RDW-006": [other]}
        found = {attributes[1]: matched for attributes, matched in info["matches"]}
        self.assertEqual(found, expected)

    def test_d_the_symbols_are_lines_with_the_colour_of_the_class_faded_and_marked(self) -> None:
        """RF-017-27: los símbolos son **líneas**; cada clase tiene su color (distinto de las demás y de «otra clase»); la atenuada tiene el trazo menos opaco, discontinuo y más fino, y la marcada, el
        color de lo marcado (``MARK_COLOR``), de trazo y punto y más gruesa."""
        by_label = {label: symbol for label, _condition, symbol in self.layer(TEST)["rules"]}
        self.assertTrue(all(symbol["type"] == LINE for symbol in by_label.values()))
        colours = [by_label[label]["color"] for label in ("Principal", "Secundaria", cstyles.ROAD_OTHER_LABEL)]
        self.assertEqual(len(set(colours)), 3)
        for label, rgb in zip(("Principal", "Secundaria"), cstyles.ROAD_CLASS_COLORS, strict=False):
            self.assertEqual(by_label[label]["color"], "#{:02x}{:02x}{:02x}".format(*rgb))
        normal, faded, marked = (by_label[label] for label in ("Principal", "Principal descartada", "Principal con el apoyo retirado"))
        self.assertEqual(normal["alpha"], 255)
        self.assertLess(faded["alpha"], normal["alpha"])
        self.assertNotEqual(faded["pen_style"], normal["pen_style"])
        self.assertLess(faded["width"], normal["width"])
        self.assertEqual(marked["color"], "#{:02x}{:02x}{:02x}".format(*cstyles.MARK_COLOR))
        self.assertGreater(marked["width"], normal["width"])
        self.assertNotEqual(marked["pen_style"], normal["pen_style"])

    def test_e_the_values_of_the_test_layer_are_the_ones_of_the_table(self) -> None:
        """RF-017-27: lo que lee QGIS de cada pista de la capa de prueba son **los valores de la tabla** que escribió ``design`` (el código, el nombre, la clase, el estado, el perfil y las cifras; el radio
        mínimo, sin valor (``NULL``) en una de cada dos) y la geometría, la línea de tres estaciones con la Z de cada una."""
        info = self.layer(TEST)
        self.assertEqual((info["fields"], info["features"]), (["fid", *road_layer.COLUMN_NAMES], len(ROWS)))
        by_code = {attributes[1]: dict(zip(info["fields"], attributes, strict=True)) for attributes, _matched in info["matches"]}
        for number, (code, name, class_name, state, z0) in enumerate(ROWS):
            with self.subTest(code=code):
                names = by_code[code]
                self.assertEqual((names["name"], names["class_name"], names["state"], names["profile"]), (name, class_name, state, "PISTA_PRINCIPAL"))
                self.assertEqual((float(names["z_start_m"]), float(names["z_end_m"]), float(names["length_m"]), float(names["width_m"])), (z0, z0 + 3.5, 95.0, 10.5))
                self.assertEqual(names["radius_min_m"], "None" if number % 2 else "25.0")  # el NULL de la tabla, que el guion pasa a texto
        zs = [[point[2] for point in geometry["points"]] for geometry in info["geometry"]]
        self.assertEqual(zs, [[z0, z0 + 2.0, z0 + 3.5] for *_rest, z0 in ROWS])
        self.assertTrue(all(geometry["valid"] and not geometry["multi"] and geometry["wkb"] == LINESTRING_Z for geometry in info["geometry"]))


if __name__ == "__main__":
    import unittest

    unittest.main()

# SPDX-License-Identifier: GPL-3.0-or-later
"""La capa de restricciones y la rejilla de clases frente a QGIS 4.2 (spec 012, T20; RF-012-03,
RF-012-20, RF-008-62; CE-012-04; plan 012 §7, D-32, D-35 y riesgos R2 y R3; ADR-0006).

Caso de referencia: el proyecto de las restricciones (``tests.support.constraints_project``, con
sus cinco restricciones, sus estilos y los dos sectores) con las máscaras de V01 compiladas y su
rejilla de clases exportada a GeoTIFF (``gis.masks.export``). La referencia externa es QGIS 4.2
(``GEOBLENDER_QGIS_DIR``): PyQGIS sin interfaz, con su GDAL y un perfil temporal, sobre una
**copia** del GeoPackage del proyecto (QGIS puede pasar a WAL lo que abre: ``docs/trampas.md`` §6),
y el GDAL de QGIS para editar como QGIS el del proyecto (``tests.support.qgis.set_geometry``):

- **La lista de valores del tipo** (D-35, riesgo R2): GDAL la lee como dominio de campo de las tres
  capas (``GetFieldDomain``: de tipo codificado, los once códigos con su texto en español) y QGIS
  pone al campo un widget de lista de valores («ValueMap») con esos textos y el alias «Tipo».
- **El estilo por tipo** (D-32): las tres capas se abren con su estilo por defecto, un
  renderizador por reglas con una regla por tipo (su nombre en español y su filtro sobre
  ``ctype``) y una para lo sin tipo, con el símbolo de su geometría y el color de cada tipo.
  ``layer_styles`` está registrada como dato (``core_layer_styles``), así que la comprobación de
  la 008 no encuentra tablas sin registrar (RF-008-62).
- **El GeoTIFF de clases** (RF-012-20): lo abre QGIS georreferenciado en EPSG:25830, con la
  rejilla de las máscaras, sin dato −9999, los metadatos de GDAL con la leyenda en español y el
  ``.qml`` paletado aplicado solo (una entrada por código presente, con su etiqueta); el valor de
  cada celda es su código y el color que pinta QGIS, el de su entrada.
- **Redibujar el perímetro en QGIS** (RF-012-03, CE-012-04, riesgo R3): con el GDAL de QGIS se
  sustituye la geometría del perímetro por el redibujado (+1,43 ha) sin error; la comprobación de
  los datos de la 008 lo registra como edición externa de un dato editable a mano (no se bloquea),
  las máscaras de V01 quedan obsoletas con el dato cambiado como causa y, al compilar, el área
  ganada por el polígono del perímetro es 1,43 ha (≤ 10⁻⁹ ha).

Sin QGIS (sin la variable, o sin su GDAL) la clase se omite con «[ENTORNO] qgis», que
``tools/check.py`` cuenta como «VERDE CON OMISIONES»; la spec 012 no se cierra sin una ejecución
con QGIS anotada en su T20.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as fx
from tests.support import qgis
from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender
from tests.support.resources import requires
from tests.unit.core.constraints.test_operations import BUDGET_S, _LayersCase, _last

access = import_geoblender("gis.masks.access")
export = import_geoblender("gis.masks.export")
gstore_masks = import_geoblender("gis.masks.store")
cstore = import_geoblender("core.constraints.store")
cstyles = import_geoblender("core.constraints.styles")
cmodel = import_geoblender("core.constraints.model")
external = import_geoblender("core.datasets.external")
orphans = import_geoblender("core.datasets.orphans")
datasets = import_geoblender("core.datasets")
stale = import_geoblender("core.provenance.stale")
graph = import_geoblender("core.provenance.graph")
paths = import_geoblender("core.paths")

NO_READ_ONLY = paths.ReadOnlyDirs.from_sources(None, [])
LAYERS = tuple(cstore.CONSTRAINT_LAYERS.values())
HAND_LABELS = {
    12: "Franja de solo relleno + Dentro del perímetro de actuación",
    88: "Dentro del perímetro de actuación + Dentro del límite legal + Intocable o excluido",
}
"""Dos códigos de la rejilla de V01 (la franja de solo relleno y la torre) con su nombre a mano."""
SYMBOL_TYPES = {"core_constraint_polygon": 2, "core_constraint_line": 1,
                "core_constraint_point": 0}
"""``Qgis.SymbolType``: relleno (2), línea (1) y marcador (0)."""

INSPECT_SCRIPT = r"""
import json
import sys

from osgeo import gdal
from qgis.core import Qgis, QgsPointXY, QgsRaster, QgsRasterLayer, QgsVectorLayer
from qgis.PyQt.QtGui import QColor

gdal.UseExceptions()
gpkg, tif, cells = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
found = {"qgis": Qgis.version(), "gdal": gdal.__version__, "layers": {}}
for name in json.loads(sys.argv[4]):
    layer = QgsVectorLayer(f"{gpkg}|layername={name}", name, "ogr")
    info = {"valid": layer.isValid(), "features": layer.featureCount()}
    renderer = layer.renderer()
    info["renderer"] = renderer.type()
    rules = renderer.rootRule().children() if renderer.type() == "RuleRenderer" else []
    info["rules"] = [[rule.label(), rule.filterExpression(), int(rule.symbol().type()),
                      rule.symbol().color().name()] for rule in rules]
    index = layer.fields().indexFromName("ctype")
    setup = layer.editorWidgetSetup(index)
    config = setup.config()
    info["widget"] = {"type": setup.type(),
                      "map": {k: v for item in config.get("map", []) for k, v in item.items()}}
    info["alias"] = layer.attributeDisplayName(index)
    source = gdal.OpenEx(gpkg, gdal.OF_VECTOR)
    definition = source.GetLayerByName(name).GetLayerDefn()
    domain_name = definition.GetFieldDefn(definition.GetFieldIndex("ctype")).GetDomainName()
    domain = source.GetFieldDomain(domain_name) if domain_name else None
    info["domain"] = None if domain is None else {
        "name": domain_name, "type": int(domain.GetDomainType()),
        "values": domain.GetEnumeration()}
    found["layers"][name] = info
raster = QgsRasterLayer(tif, "clases")
renderer = raster.renderer()
extent = raster.extent()
step = raster.rasterUnitsPerPixelX()
block = renderer.block(1, extent, raster.width(), raster.height())
pixels = []
for row, col in cells:
    point = QgsPointXY(extent.xMinimum() + (col + 0.5) * step,
                       extent.yMaximum() - (row + 0.5) * step)
    value = raster.dataProvider().identify(point, QgsRaster.IdentifyFormatValue).results()[1]
    color = QColor.fromRgba(block.color(row, col) & 0xFFFFFFFF)
    pixels.append([value, color.name(), color.alpha()])
dataset = gdal.Open(tif)
found["raster"] = {
    "valid": raster.isValid(), "crs": raster.crs().authid(),
    "size": [raster.width(), raster.height(), raster.bandCount()], "renderer": renderer.type(),
    "classes": [[c.value, c.label, c.color.name(), c.color.alpha()] for c in renderer.classes()],
    "pixels": pixels, "geotransform": list(dataset.GetGeoTransform()),
    "nodata": dataset.GetRasterBand(1).GetNoDataValue(),
    "metadata": dataset.GetMetadata(), "projection": dataset.GetProjection()}
print("RESULT" + json.dumps(found))
"""
"""El guion de PyQGIS: el GeoPackage (una copia), el GeoTIFF, las celdas (fila, columna) cuyo
valor y color se piden y las capas a mirar; en la salida, lo que ve QGIS de cada capa (válida,
entidades, reglas del estilo, widget del tipo, alias y dominio de campo de GDAL) y del GeoTIFF."""


def _wkt(ring: Any) -> str:
    # float(): el repr de un float64 de numpy 2 es «np.float64(…)», no un número de WKT
    return "MULTIPOLYGON (((" + ", ".join(f"{float(x)!r} {float(y)!r}" for x, y in ring) + ")))"


@requires(qgis.QGIS, qgis.QGIS_HINT)
class QgisConstraintsReferenceTest(_LayersCase):
    """El proyecto de las restricciones visto y editado con QGIS (véase el módulo)."""

    seen: dict[str, Any]
    masks: Any
    tif: Path
    cells: list[tuple[int, int]]

    @classmethod
    def setUpClass(cls) -> None:
        # QGIS arranca (≈ 1 s) mientras se prepara el proyecto.
        started = cls.enterClassContext(qgis.PyqgisProcess(INSPECT_SCRIPT))
        super().setUpClass()
        out = cls.enterClassContext(project_tmp("gb-rc-"))
        cls.masks = _last(access.ensure_masks_steps(cls.project, cls.v1.uid, budget_s=BUDGET_S))
        cls.tif = export.export_classes(cls.project, cls.v1.uid, out / "clases.tif",
                                        read_only=NO_READ_ONLY)
        copy = out / "copia"
        copy.mkdir()
        shutil.copyfile(cls.project.database_path, copy / "project.gpkg")
        classes = cls.masks.classes
        cls.codes = export.present_codes(classes)
        cls.cells = [tuple(int(part) for part in np.argwhere(classes == code)[0])
                     for code in cls.codes]
        result = started.finish(str(copy / "project.gpkg"), str(cls.tif),
                                json.dumps(cls.cells), json.dumps(LAYERS))
        if result.returncode != 0:
            raise RuntimeError(f"PyQGIS no abrió las capas: {qgis.output_of(result)}")
        (line,) = [text for text in result.stdout.splitlines() if text.startswith("RESULT")]
        cls.seen = json.loads(line.removeprefix("RESULT"))

    def test_a_type_is_a_value_list_in_spanish(self) -> None:
        """RF-012-03, D-35 (riesgo R2): GDAL ve el tipo de las tres capas como un dominio de
        campo codificado con los once códigos y su español, y QGIS lo muestra como una lista de
        valores con esos textos y el alias «Tipo»."""
        expected = {ctype.value: ctype.label("es") for ctype in cmodel.ConstraintType}
        self.assertEqual(len(expected), 11)
        for name in LAYERS:
            with self.subTest(name):
                info = self.seen["layers"][name]
                self.assertTrue(info["valid"])
                domain = info["domain"]
                self.assertEqual((domain["name"], domain["type"]), (cstore.CTYPE_ENUM, 0))
                self.assertEqual(domain["values"], expected)
                self.assertEqual(info["widget"]["type"], "ValueMap")
                self.assertEqual({code: text for text, code in info["widget"]["map"].items()},
                                 expected)
                self.assertEqual(info["alias"], "Tipo")

    def test_b_layers_open_with_their_style_by_type(self) -> None:
        """RF-012-20, D-32: las tres capas se abren con el estilo por defecto de ``layer_styles``:
        un renderizador por reglas con una regla por tipo (nombre en español, filtro sobre
        ``ctype``, el símbolo de su geometría y el color del tipo) y la de lo sin tipo."""
        for name in LAYERS:
            with self.subTest(name):
                info = self.seen["layers"][name]
                self.assertEqual(info["renderer"], "RuleRenderer")
                rules = info["rules"]
                self.assertEqual(len(rules), 12)
                for rule, ctype in zip(rules, cmodel.ConstraintType, strict=False):
                    label, condition, symbol, color = rule
                    self.assertEqual(label, ctype.label("es"))
                    self.assertEqual(condition, f'"ctype" = \'{ctype.value}\'')
                    self.assertEqual(symbol, SYMBOL_TYPES[name])
                    red, green, blue = cstyles.COLORS[ctype]
                    self.assertEqual(color, f"#{red:02x}{green:02x}{blue:02x}")
                self.assertEqual(rules[-1][:2], [cstyles.ELSE_LABEL, "ELSE"])
        self.assertEqual({name: info["features"] for name, info in self.seen["layers"].items()},
                         {"core_constraint_polygon": 3, "core_constraint_line": 1,
                          "core_constraint_point": 1})

    def test_c_layer_styles_is_a_registered_dataset(self) -> None:
        """RF-008-62, D-32: ``layer_styles`` es el dato ``core_layer_styles`` del proyecto,
        editable en QGIS y al día, y el proyecto no tiene tablas sin registrar."""
        record = self.record("core_layer_styles")
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual((record.locator, record.status, record.qgis_editable),
                         ("layer_styles", datasets.DatasetStatus.CURRENT, True))
        with self.project.read() as conn:
            self.assertEqual(orphans.unregistered_tables(conn), ())

    def test_d_geotiff_opens_georeferenced_with_legend_and_palette(self) -> None:
        """RF-012-20, RF-006-24: QGIS abre el GeoTIFF de clases en EPSG:25830 con la rejilla de
        las máscaras, sin dato −9999 y los metadatos de la leyenda; aplica el ``.qml`` (paletado,
        una entrada por código con su etiqueta en español); el valor de cada celda es su código
        y QGIS la pinta con el color de su entrada."""
        raster = self.seen["raster"]
        grid = self.masks.grid
        self.assertTrue(raster["valid"])
        self.assertEqual(raster["crs"], "EPSG:25830")
        self.assertEqual(raster["size"], [grid.ncols, grid.nrows, 1])
        self.assertEqual(raster["geotransform"], [grid.west, grid.dx, 0.0, grid.north, 0.0,
                                                  -grid.dy])
        self.assertEqual(raster["nodata"], -9999.0)
        self.assertIn("25830", raster["projection"])
        legend = export.legend_items(self.codes, self.v1.code)
        shown = dict(raster["metadata"])
        self.assertEqual(shown.pop("AREA_OR_POINT"), "Area")
        self.assertEqual(shown, legend)
        for code, text in (("0", "Sin clase"), ("12", HAND_LABELS[12]), ("88", HAND_LABELS[88])):
            self.assertEqual(shown[f"CLASE_{code}"], text)
        self.assertEqual(shown["VERSION"], "V01")
        self.assertEqual(raster["renderer"], "paletted")
        self.assertEqual([item[0] for item in raster["classes"]], [float(c) for c in self.codes])
        for (value, label, color, alpha), code in zip(raster["classes"], self.codes, strict=True):
            red, green, blue, opacity = export.class_color(code)
            self.assertEqual((label, color, alpha),
                             (export.class_label(code), f"#{red:02x}{green:02x}{blue:02x}",
                              opacity))
            if code in HAND_LABELS:
                self.assertEqual(label, HAND_LABELS[code])
        for (value, color, alpha), code in zip(raster["pixels"], self.codes, strict=True):
            red, green, blue, opacity = export.class_color(code)
            self.assertEqual((value, alpha), (float(code), opacity))
            if opacity:
                self.assertEqual(color, f"#{red:02x}{green:02x}{blue:02x}")

    def test_e_perimeter_redrawn_in_qgis(self) -> None:
        """RF-012-03, CE-012-04 (riesgo R3): con el GDAL de QGIS se redibuja el perímetro (+1,43
        ha) sin error; la comprobación de los datos lo registra como edición externa de un dato
        editable (nada bloqueado), las máscaras de V01 quedan obsoletas con el dato cambiado
        como causa, y al compilar el polígono del perímetro ha ganado 1,43 ha."""
        polygons = cstore.layer_of("polygon")
        before = self.record(polygons)
        assert before is not None
        redrawn = _wkt(fx.absolute(fx.REDRAWN_PERIMETER_LOCAL))
        self.clock.advance(minutes=1)
        outcome = qgis.edit_gpkg(qgis.set_geometry(
            self.project.database_path, polygons, ("code", "perimetro"), redrawn))
        self.assertEqual([(item.ok, item.error) for item in outcome.results], [(True, None)])

        self.clock.advance(minutes=1)
        checked = _last(external.external_check_steps(self.project))
        (finding,) = [item for item in checked.findings if item.record.name == polygons]
        self.assertEqual((finding.verdict, finding.status),
                         (external.DatasetVerdict.EDITED, datasets.DatasetStatus.CURRENT))
        self.assertTrue(checked.texts())
        after = self.record(polygons)
        assert after is not None
        self.assertNotEqual(after.content_sha256, before.content_sha256)
        self.assertEqual(after.status, datasets.DatasetStatus.CURRENT)
        with self.project.read() as conn:
            self.assertEqual(external.unusable(conn), ())
            causes = stale.item_causes(conn, "operation", self.masks.operation_uid)
            self.assertEqual(orphans.unregistered_tables(conn), ())
        self.assertIn(graph.Cause(graph.CauseKind.DATASET_CHANGED, before.uid), causes)
        self.assertIs(access.mask_state(self.project, self.v1.uid)[0], access.MaskState.STALE)

        self.clock.advance(minutes=1)
        masks = _last(access.ensure_masks_steps(self.project, self.v1.uid, budget_s=BUDGET_S))
        self.assertIs(masks.state, access.MaskState.CURRENT)
        record = self.record("gis_mskr", self.v1)
        assert record is not None
        with self.project.read() as conn:
            report = gstore_masks.read_report(conn, record.locator)
        values = {(item[0], item[1]): item[2] for item in report}
        self.assertLessEqual(abs(values[("perimetro", "polygon_gained")] / 10_000.0 - 1.43),
                             1e-9)
        self.assertEqual(values[("perimetro", "polygon_lost")], 0.0)


if __name__ == "__main__":
    import unittest

    unittest.main()

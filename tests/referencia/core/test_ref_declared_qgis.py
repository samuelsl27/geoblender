# SPDX-License-Identifier: GPL-3.0-or-later
"""La capa de las restricciones declaradas por las entidades y la de entidades frente a QGIS 4.2 (spec 015,
T22 y T30; HU-015-1; RF-012-20, RF-015-27, RF-009-05, RF-008-56; plan 015 §5.7, §5.8 y §8; D-13; como
``test_ref_constraints_qgis``).

Caso de referencia: V01 con la «Plataforma de carga» (que no protege) y la «Plataforma de taller» (que
protege con 4 m) creadas y declaradas con las operaciones de verdad (``tests.unit.design.test_declare_operation``:
``des_decl_v01`` con la restricción de la segunda y su fila de estilo en ``layer_styles``, escrita por la
operación de versión) y **la capa de entidades de verdad** (``des_enl_v01``, T30: la que escribe ``des.entity_layer``
tras cada orden de entidades, con su estilo, en la misma transacción), tras **descartar la primera** (la segunda
queda con el «apoyo retirado»); y, en una **copia** del GeoPackage del proyecto, una capa de entidades de prueba
(``des_enl_v99``) con los campos del contrato del estilo (``core.constraints.styles.ENTITY_FIELDS``) y uno más, y
siete entidades de dos tipos en todos los estados, con su estilo escrito por ``insert_version_styles``. La referencia
externa es QGIS 4.2 (``GEOBLENDER_QGIS_DIR``): PyQGIS sin interfaz, con su GDAL y un perfil temporal, sobre esa copia
(QGIS puede pasar a WAL lo que abre: ``docs/trampas.md`` §6):

- **El estilo por tipo** (RF-012-20): ``des_decl_v01`` se abre con el estilo por defecto de ``layer_styles``, un
  renderizador por reglas con **el mismo** estilo que la capa de polígonos del proyecto (una regla por tipo, su
  nombre en español, su filtro sobre ``ctype`` y su color de ``COLORS``, más la de lo sin tipo), y la entidad
  que declara cae en la regla de su tipo («Sin relleno»).
- **La marca «no editable»** (RF-012-20, RF-008-56): QGIS da por de solo lectura **todos** los campos de las
  dos capas en el formulario y la tabla de atributos (``QgsEditFormConfig.readOnly``), también el que añade
  la tabla de entidades al contrato, y enseña la nota de la capa, que dice que no se edita a mano. La marca de
  **capa** de solo lectura **no viaja en el estilo**: QGIS 4.2 ignora ``readOnly="1"`` del QML al
  aplicarlo; la protección de la capa entera es el bloqueo de RF-008-56 (``qgis_editable=False``).
- **La capa de entidades** (RF-015-27): por tipo de entidad y por estado: la plataforma, con su color; la
  descartada, atenuada; la de «apoyo retirado», marcada; los tipos sin estilo propio, como «otra entidad»;
  cada entidad cae en **una** sola regla (las reglas no se solapan).
- **La capa de entidades de verdad** (T30, RF-015-27, D-13): ``des_enl_v01`` se abre en QGIS **con su estilo**
  (el mismo de las reglas anteriores, escrito por la operación): la entidad descartada en la regla atenuada y la que
  perdió el apoyo en la marcada, con sus campos (``fid``, el código, el nombre, el tipo, el estado, de qué parte, en
  qué se apoya, la cadena y las cifras) **todos de solo lectura** y su nota, los **mismos valores** que la tabla (el
  estado, la cadena, las cifras) y la **geometría de la huella**: el área que mide QGIS es la de las celdas de la
  entidad.
- **Las capas del proyecto**, igual que antes: sus tres estilos, con sus doce reglas y sin campos de solo
  lectura (la 015 no los toca).

Sin QGIS (sin la variable, o sin su GDAL) la clase se omite con «[ENTORNO] qgis», que ``tools/check.py`` cuenta
como «VERDE CON OMISIONES»; la T22 de la 015 no se cierra sin una ejecución con QGIS anotada.
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
from tests.unit.design import test_declare_operation as decl
from tests.unit.design import test_platform_operation as ops
from tests.unit.design import test_platform_prepare as prep

cstore = import_geoblender("core.constraints.store")
cstyles = import_geoblender("core.constraints.styles")
cmodel = import_geoblender("core.constraints.model")
declared_mod = import_geoblender("core.constraints.declared")
gpkg = import_geoblender("core.gpkg")
gbase = import_geoblender("core.gpkg.base")
gwkb = import_geoblender("core.gpkg.wkb")
entities = import_geoblender("design.entities")
entity_layer = import_geoblender("design.entity_layer")
entity_store = import_geoblender("design.entity_store")

T = cmodel.ConstraintType
DECLARED = decl.TABLE
ENTITIES = "des_enl_v99"
"""La capa de entidades **de prueba**, en la copia (una versión que el proyecto no tiene: no choca con la real)."""
REAL_ENTITIES = "des_enl_v01"
"""La capa de entidades de verdad de V01 (``des.entity_layer``, T30)."""
PROJECT_LAYERS = tuple(cstore.CONSTRAINT_LAYERS.values())
FILL = 2
"""``Qgis.SymbolType.Fill``."""
ENTITY_FIELDS = (*cstyles.ENTITY_FIELDS, "plat_area_m2")
"""Los campos de la capa de entidades de prueba: los del contrato y una cifra de más."""
ENTITY_ROWS = (
    ("platform", "P1", "current"), ("platform", "P2", "discarded"),
    ("platform", "P3", "support_removed"), ("platform", "P4", "stale"),
    ("stockpile", "A1", "current"), ("stockpile", "A2", "discarded"),
    ("stockpile", "A3", "support_removed"),
)
"""Las entidades de la capa de prueba: (``kind``, ``name``, ``state``); ``stockpile`` es un tipo de la 016, sin
estilo propio todavía."""

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
    if int(plain(symbol.type())) != 2:  # solo el relleno tiene contorno y relleno aparte
        return {"type": int(plain(symbol.type())), "color": symbol.color().name()}
    return {"type": int(plain(symbol.type())), "color": symbol.color().name(),
            "fill_alpha": layer.fillColor().alpha(), "stroke": layer.strokeColor().name(),
            "stroke_alpha": layer.strokeColor().alpha(),
            "stroke_style": int(plain(layer.strokeStyle())), "stroke_width": layer.strokeWidth(),
            "fill_style": int(plain(layer.brushStyle()))}


found = {"qgis": Qgis.version(), "layers": {}}
for name in names:
    layer = QgsVectorLayer(f"{gpkg}|layername={name}", name, "ogr")
    info = {"valid": layer.isValid(), "features": layer.featureCount()}
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
    info["areas"] = [feature.geometry().area() for feature in layer.getFeatures()]
    info["geometry"] = [[feature.geometry().isGeosValid(), feature.geometry().wkbType() in (6, 1006, 2006)]
                        for feature in layer.getFeatures()]
    found["layers"][name] = info
# la marca de capa de solo lectura en el QML: ¿la aplica QGIS 4.2 al aplicar un estilo?
connection = sqlite3.connect(f"file:{gpkg}?mode=ro", uri=True)
row = connection.execute("SELECT styleQML FROM layer_styles WHERE f_table_name = ?",
                         (probe,)).fetchone()
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
"""El guion de PyQGIS: el GeoPackage (una copia), las capas a mirar y la capa con la que se prueba la marca de
capa de solo lectura; en la salida, lo que ve QGIS de cada capa (válida, entidades, reglas con su símbolo,
campos y cuáles son de solo lectura, nota y marca de capa, y las reglas que cumple cada entidad) y qué hace con
``readOnly="1"`` en un estilo."""


@requires(qgis.QGIS, qgis.QGIS_HINT)
class QgisDeclaredReferenceTest(decl.DeclareCase):
    """V01 con sus restricciones declaradas y una capa de entidades de prueba, vistas con QGIS (véase el
    módulo)."""

    seen: ClassVar[dict[str, Any]]
    qml: ClassVar[str]
    discarded: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        # QGIS arranca (≈ 1 s) mientras se prepara el proyecto.
        started = cls.enterClassContext(qgis.PyqgisProcess(INSPECT_SCRIPT))
        super().setUpClass()
        cls.made(prep.request())
        cls.clock.advance(minutes=1)
        cls.made(prep.request(decl.WORKSHOP, start="entity:PLT-001", protect=True, guard_m=decl.GUARD_M))
        cls.entities_declared()
        cls.clock.advance(minutes=1)
        cls.discarded = ops.finish(entity_store.discard_entity_steps(
            cls.project, cls.v1.uid, "PLT-001", reason="Prueba de la T30", decided_by=decl.EDITOR))
        out = cls.enterClassContext(project_tmp("gb-dq-"))
        copy = out / "copia"
        copy.mkdir()
        target = copy / "project.gpkg"
        shutil.copyfile(cls.project.database_path, target)
        cls.write_entity_layer(target)
        result = started.finish(str(target), json.dumps([DECLARED, ENTITIES, REAL_ENTITIES, *PROJECT_LAYERS]),
                                DECLARED)
        if result.returncode != 0:
            raise RuntimeError(f"PyQGIS no abrió las capas: {qgis.output_of(result)}")
        (line,) = [text for text in result.stdout.splitlines() if text.startswith("RESULT")]
        cls.seen = json.loads(line.removeprefix("RESULT"))

    @classmethod
    def write_entity_layer(cls, path: Path) -> None:
        """Una capa de entidades de prueba en ``path`` (la copia), con los campos del contrato y una cifra, sus
        siete entidades y su estilo por defecto (``insert_version_styles``)."""
        srs = cls.project.record.crs_epsg
        columns = [gbase.ColumnDef(name, "TEXT", False) for name in cstyles.ENTITY_FIELDS]
        columns.append(gbase.ColumnDef("plat_area_m2", "DOUBLE", False))
        db = gpkg.GpkgConnection.open_write(path)
        try:
            with db.transaction() as conn:
                gbase.create_feature_table(conn, ENTITIES, "MULTIPOLYGON", srs, False, columns,
                                           "Entidades de la versión V01 (prueba)")
                for number, (kind, name, state) in enumerate(ENTITY_ROWS):
                    west = 725_000.0 + 100.0 * number
                    ring = np.array([[west, 4_400_000.0], [west + 50.0, 4_400_000.0],
                                     [west + 50.0, 4_400_050.0], [west, 4_400_050.0],
                                     [west, 4_400_000.0]])
                    blob = gwkb.encode_geometry("MULTIPOLYGON", [[ring]], srs, False)
                    conn.execute(f'INSERT INTO "{ENTITIES}" (geom, kind, name, state, supports, chain, '
                                 "plat_area_m2) VALUES (?, ?, ?, ?, '', 'cadena', 2500.0)",
                                 (blob, kind, name, state))
                assert cstyles.insert_version_styles(conn, [ENTITIES]) == (ENTITIES,)
        finally:
            db.close()

    def layer(self, name: str) -> dict[str, Any]:
        info = self.seen["layers"][name]
        self.assertTrue(info["valid"], name)
        return info

    def test_a_declared_layer_opens_with_the_style_by_type_of_the_project(self) -> None:
        """RF-012-20: ``des_decl_v01`` se abre con el estilo por defecto de ``layer_styles``: un renderizador
        por reglas con una regla por tipo (nombre en español, filtro sobre ``ctype``, símbolo de relleno y
        el color del tipo) y la de lo sin tipo, y la restricción que declara la «Plataforma de taller» cae en
        **una** regla, la de «Sin relleno»."""
        info = self.layer(DECLARED)
        self.assertEqual(info["renderer"], "RuleRenderer")
        rules = info["rules"]
        self.assertEqual(len(rules), 12)
        for (label, condition, symbol), ctype in zip(rules, T, strict=False):
            self.assertEqual(label, ctype.label("es"))
            self.assertEqual(condition, f'"ctype" = \'{ctype.value}\'')
            self.assertEqual(symbol["type"], FILL)
            red, green, blue = cstyles.COLORS[ctype]
            self.assertEqual(symbol["color"], f"#{red:02x}{green:02x}{blue:02x}")
        self.assertEqual(rules[-1][:2], [cstyles.ELSE_LABEL, "ELSE"])
        project = self.layer("core_constraint_polygon")["rules"]
        self.assertEqual(rules, project)  # el mismo estilo que la capa de polígonos del proyecto
        self.assertEqual(info["features"], 1)
        ((attributes, matched),) = info["matches"]
        self.assertEqual(matched, [T.NO_FILL.label("es")])
        self.assertIn("dec__plt_002", attributes)

    def test_b_every_field_of_the_declared_layer_is_read_only_with_its_note(self) -> None:
        """RF-012-20 («marcadas no editables a mano»), RF-008-56: QGIS da por de solo lectura **todos** los
        campos de ``des_decl_v01`` (``fid`` y las columnas de la 015) en el formulario y la tabla de
        atributos, y enseña la nota de la capa, en español, que dice que no se edita a mano."""
        info = self.layer(DECLARED)
        self.assertEqual(info["fields"], ["fid", *declared_mod.COLUMN_NAMES])
        self.assertTrue(all(info["read_only"]), dict(zip(info["fields"], info["read_only"], strict=True)))
        self.assertIn("no se edita a mano", info["notes"])
        self.assertIn("entidad", info["notes"])

    def test_c_the_layer_read_only_flag_does_not_travel_in_the_style(self) -> None:
        """RF-012-20, RF-008-56 (plan 015 §8: «el estilo no editable de QGIS no existe»): QGIS 4.2 **no** lleva
        al aplicar un estilo la marca de capa de solo lectura (``readOnly="1"`` en la raíz del QML, lo que
        escribe QGIS al exportar una capa marcada; solo la guarda en su proyecto): la capa se puede poner
        en edición. Por eso la marca es la de los campos (la prueba anterior) y la protección de la capa entera,
        el bloqueo de RF-008-56 (``qgis_editable=False`` en el dato). Si una versión de QGIS la admitiese,
        esta prueba avisa: se añadiría al QML."""
        flag = self.seen["layer_flag"]
        self.assertIsNotNone(flag, "la capa no tiene estilo por defecto en layer_styles")
        self.assertTrue(flag["applied"])
        self.assertFalse(flag["read_only"])
        self.assertTrue(flag["editing"])
        self.assertFalse(self.layer(DECLARED)["layer_read_only"])
        self.assertFalse(self.record_of().qgis_editable)  # el dato: no editable a mano (se bloquea)

    def test_d_entities_by_kind_and_state_each_in_one_rule(self) -> None:
        """RF-015-27, RF-012-20: la capa de entidades se abre con un estilo por tipo y por estado: cada entidad
        cae en **una** regla: la plataforma (normal u obsoleta) en la suya, la descartada en la atenuada, la de
        «apoyo retirado» en la marcada y los tipos sin estilo propio en «otra entidad» (con sus tres
        estados); la atenuada tiene el relleno y el contorno menos opacos y discontinuo, y la marcada, el
        contorno grueso y de otro color."""
        info = self.layer(ENTITIES)
        self.assertEqual(info["renderer"], "RuleRenderer")
        other = cstyles.ENTITY_OTHER_LABEL
        expected = {
            ("platform", "P1", "current"): ["Plataforma"],
            ("platform", "P2", "discarded"): ["Plataforma descartada"],
            ("platform", "P3", "support_removed"): ["Plataforma con el apoyo retirado"],
            ("platform", "P4", "stale"): ["Plataforma"],
            ("stockpile", "A1", "current"): [other],
            ("stockpile", "A2", "discarded"): [f"{other} descartada"],
            ("stockpile", "A3", "support_removed"): [f"{other} con el apoyo retirado"],
        }
        found = {tuple(attributes[1:4]): matched for attributes, matched in info["matches"]}
        self.assertEqual(found, expected)
        by_label = {label: symbol for label, _condition, symbol in info["rules"]}
        self.assertEqual(len(by_label), 6)
        red, green, blue = cstyles.ENTITY_KINDS["platform"][1]
        normal, faded, marked = (by_label[label] for label in (
            "Plataforma", "Plataforma descartada", "Plataforma con el apoyo retirado"))
        self.assertEqual(normal["color"], f"#{red:02x}{green:02x}{blue:02x}")
        self.assertEqual((normal["fill_alpha"], normal["stroke_alpha"]), (cstyles.FILL_ALPHA, 255))
        self.assertLess(faded["fill_alpha"], normal["fill_alpha"])
        self.assertLess(faded["stroke_alpha"], normal["stroke_alpha"])
        self.assertNotEqual(faded["stroke_style"], normal["stroke_style"])
        red, green, blue = cstyles.MARK_COLOR
        self.assertEqual(marked["stroke"], f"#{red:02x}{green:02x}{blue:02x}")
        self.assertGreater(marked["stroke_width"], normal["stroke_width"])
        self.assertNotEqual(by_label[other]["color"], normal["color"])
        for symbol in by_label.values():
            self.assertEqual(symbol["type"], FILL)

    def test_e_every_field_of_the_entity_layer_is_read_only_including_the_extra_ones(self) -> None:
        """RF-015-27, RF-012-20: los campos de la capa de entidades son de solo lectura **todos**, también la
        cifra que la tabla añade al contrato del estilo (el QML se escribe con las columnas que la tabla
        tiene de verdad), y la capa lleva su nota."""
        info = self.layer(ENTITIES)
        self.assertEqual(info["fields"], ["fid", *ENTITY_FIELDS])
        self.assertTrue(all(info["read_only"]))
        self.assertIn("no se edita a mano", info["notes"])

    def test_g_the_real_entity_layer_opens_with_its_style_and_every_field_read_only(self) -> None:
        """RF-015-27, RF-012-20, RF-008-56, D-13 (T30): ``des_enl_v01``, la que escribe ``des.entity_layer`` (no una de
        prueba), se abre en QGIS **con su estilo por defecto**, escrito por la operación en su transacción: un
        renderizador por reglas con las seis del estilo de entidades; la «Plataforma de carga» (**descartada**) cae en
        la regla atenuada y la «Plataforma de taller» (que perdió el apoyo al descartar la otra) en la marcada, cada
        una en **una** sola regla; sus campos (``fid`` y las doce columnas de la capa) son de solo lectura todos y la
        capa lleva su nota."""
        info = self.layer(REAL_ENTITIES)
        self.assertEqual(info["renderer"], "RuleRenderer")
        self.assertEqual(len(info["rules"]), 6)
        self.assertEqual(info["rules"], self.layer(ENTITIES)["rules"], "el mismo estilo que el de la capa de prueba")
        found = {attributes[1]: matched for attributes, matched in info["matches"]}
        self.assertEqual(found, {"PLT-001": ["Plataforma descartada"],
                                 "PLT-002": ["Plataforma con el apoyo retirado"]})
        self.assertEqual(info["fields"], ["fid", *entity_layer.COLUMN_NAMES])
        self.assertTrue(all(info["read_only"]), dict(zip(info["fields"], info["read_only"], strict=True)))
        self.assertIn("no se edita a mano", info["notes"])
        self.assertFalse(info["layer_read_only"], "la marca de capa no viaja en el estilo (RF-008-56 la protege)")
        self.assertFalse(self.layer_record().qgis_editable)

    def test_h_the_real_entity_layer_has_the_values_of_the_table_and_the_footprint_geometry(self) -> None:
        """RF-015-27 (T30): lo que QGIS lee de ``des_enl_v01`` son **los valores de la tabla** que escribió
        ``design`` (el código, el nombre, el tipo, el estado, la cadena y las cifras, que son las de la operación de
        cada entidad) y la geometría es **la de la huella**: un polígono válido cuya área, medida por QGIS, es la de
        las celdas de la entidad (``des.plat_area_m2``), con coordenadas del proyecto."""
        info = self.layer(REAL_ENTITIES)
        with self.project.read() as conn:
            rows = {item.code: item for item in entity_layer.read_entity_layer(conn, REAL_ENTITIES)}
        self.assertEqual(list(rows), ["PLT-001", "PLT-002"])
        by_code = {attributes[1]: attributes for attributes, _matched in info["matches"]}
        for code, item in rows.items():
            with self.subTest(code=code):
                names = dict(zip(["fid", *entity_layer.COLUMN_NAMES], by_code[code], strict=True))
                self.assertEqual((names["name"], names["kind"], names["state"], names["chain"]),
                                 (item.name, "platform", str(item.state), item.chain))
                self.assertEqual(float(names["area_m2"]), item.area_m2)
                self.assertEqual(float(names["cut_m3"]), item.cut_m3)
        self.assertEqual(rows["PLT-001"].state, entities.EntityState.DISCARDED)
        self.assertEqual(rows["PLT-002"].state, entities.EntityState.SUPPORT_REMOVED)
        self.assertEqual(info["features"], 2)
        for (valid, multi), area, code in zip(info["geometry"], info["areas"], rows, strict=True):
            with self.subTest(geometry=code):
                self.assertTrue(valid and multi)
                self.assertAlmostEqual(area, rows[code].area_m2, delta=1e-6 * rows[code].area_m2)

    def layer_record(self) -> Any:
        with self.project.read() as conn:
            return import_geoblender("core.datasets.registry").get(conn, "des_enl", version_uid=self.v1.uid)

    def test_f_the_project_layers_keep_their_style_and_stay_editable(self) -> None:
        """RF-012-20: las tres capas de restricciones del proyecto se abren como antes de la 015: sus doce
        reglas por tipo, con los colores de ``COLORS``, y **ningún** campo de solo lectura (la 015 solo marca
        las capas de versión), sin nota."""
        for name in PROJECT_LAYERS:
            with self.subTest(name):
                info = self.layer(name)
                self.assertEqual(info["renderer"], "RuleRenderer")
                self.assertEqual(len(info["rules"]), 12)
                for (label, _condition, symbol), ctype in zip(info["rules"], T, strict=False):
                    red, green, blue = cstyles.COLORS[ctype]
                    self.assertEqual((label, symbol["color"]),
                                     (ctype.label("es"), f"#{red:02x}{green:02x}{blue:02x}"))
                self.assertFalse(any(info["read_only"]))
                self.assertEqual(info["notes"], "")


if __name__ == "__main__":
    import unittest

    unittest.main()

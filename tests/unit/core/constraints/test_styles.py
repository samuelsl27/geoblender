# SPDX-License-Identifier: GPL-3.0-or-later
"""El estilo por tipo de las capas de restricciones en ``layer_styles`` (spec 012, T20; RF-012-20,
RF-008-62; plan 012 D-32).

La capa de restricciones se abre en QGIS 4.2 desde el GeoPackage del proyecto **con su estilo por
tipo** sin hacer nada: ``core.constraints.styles`` escribe en ``layer_styles`` un estilo por defecto
por capa (reglas por ``ctype``, un color por tipo, el nombre en español de cada regla) en la misma
transacción que crea las capas, y la tabla se registra como dato de ``core`` (``core_layer_styles``,
editable a mano: QGIS la escribe al guardar un estilo) para que la comprobación de la 008 no la
avise como «tabla sin registrar».

- **El QML** de cada capa (polígonos, líneas, puntos): un renderizador por reglas con una regla por
  cada uno de los once tipos (``"ctype" = '<tipo>'``, con su nombre en español) y una última, ``ELSE``,
  para lo sin completar (sin tipo); un símbolo de relleno, de línea o de punto según la capa; los
  límites (legal y de actuación) solo con contorno, para que no tapen lo que rodean; un color
  distinto por tipo, en el formato ``r,g,b,a`` de QGIS (no ``#rrggbbaa``: ``docs/trampas.md`` §6).
- **La tabla**: con el esquema que crea QGIS 4.2 (``gis.vector``), registrada en ``gpkg_contents``
  como ``attributes``, con una fila por capa (``useAsDefault`` = 1, la tabla y la columna de
  geometría de la capa). Repetir no duplica; un estilo por defecto que ya hay (de QGIS) se respeta.
- **El dato**: ``core_layer_styles``, tabla, ``layer_styles`` en ``project.gpkg``, ``core.gpkg_layer@1``,
  editable en QGIS.
- **En las operaciones de ``core``**: la primera que crea las tablas de las restricciones
  (aquí ``core.declare_sectors``) escribe los estilos y los registra como salida; el proyecto no
  tiene tablas sin registrar.
"""

from __future__ import annotations

import hashlib
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from tests.support import constraints_fixtures as fx
from tests.support.core_fixtures import FakeClock, make_session, make_settings, project_tmp
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered

gpkg = import_geoblender("core.gpkg")
base = import_geoblender("core.gpkg.base")
model = import_geoblender("core.constraints.model")
store = import_geoblender("core.constraints.store")
styles = import_geoblender("core.constraints.styles")
cprov = import_geoblender("core.constraints.provenance")
datasets = import_geoblender("core.datasets")
registry = import_geoblender("core.datasets.registry")
orphans = import_geoblender("core.datasets.orphans")
create = import_geoblender("core.project.create")
userdata_mod = import_geoblender("core.userdata")
gis_vector = import_geoblender("gis.vector")
declared_mod = import_geoblender("core.constraints.declared")
design_provenance = import_geoblender("design.provenance")
entities_mod = import_geoblender("design.entities")

T = model.ConstraintType
SRS = fx.SRS_ID
LAYERS = ("core_constraint_polygon", "core_constraint_line", "core_constraint_point")
SYMBOLS = {"core_constraint_polygon": "fill", "core_constraint_line": "line",
           "core_constraint_point": "marker"}
COLOR = re.compile(r"\d{1,3},\d{1,3},\d{1,3},\d{1,3}\Z")
OUTLINE_ONLY = (T.LEGAL_LIMIT, T.ACTION_PERIMETER)


def _new(path: Path) -> Any:
    db = gpkg.GpkgConnection.open_write(path, create=True)
    with db.transaction() as conn:
        base.create_base(conn, fx.CRS)
    return db


def _with_tables(path: Path) -> tuple[Any, tuple[str, ...]]:
    db = _new(path)
    with db.transaction() as conn:
        created = store.create_tables(conn, SRS)
    return db, created


def _options(symbol: ET.Element) -> dict[str, str]:
    layer = symbol.find("layer")
    assert layer is not None
    return {option.get("name", ""): option.get("value", "")
            for option in layer.iter("Option") if option.get("name")}


def _parsed(table: str) -> ET.Element:
    row = styles.style_for(table)
    return ET.fromstring(row.qml.split("\n", 1)[1])  # sin la línea del DOCTYPE


class StyleContentTest(unittest.TestCase):
    """El QML de cada capa."""

    def test_rules_by_type_with_spanish_names(self) -> None:
        """RF-012-20: un renderizador por reglas con una regla por tipo (en el orden de
        ``ConstraintType``), su filtro sobre ``ctype``, su nombre en español y su símbolo, y una
        última ``ELSE`` para lo sin tipo."""
        for table in LAYERS:
            with self.subTest(table):
                row = styles.style_for(table)
                self.assertTrue(row.qml.startswith("<!DOCTYPE qgis"))
                self.assertLessEqual(len(row.name), 30)  # TEXT(30) de QGIS
                root = _parsed(table)
                self.assertEqual(root.get("styleCategories"), "Symbology")
                (renderer,) = root.iter("renderer-v2")
                self.assertEqual(renderer.get("type"), "RuleRenderer")
                rules = list(renderer.iter("rule"))
                self.assertEqual(len(rules), 12)
                for rule, ctype in zip(rules[:-1], T, strict=True):
                    self.assertEqual(rule.get("filter"), f'"ctype" = \'{ctype.value}\'')
                    self.assertEqual(rule.get("label"), ctype.label("es"))
                self.assertEqual(rules[-1].get("filter"), "ELSE")
                self.assertEqual(rules[-1].get("label"), "Sin tipo (incompleta)")
                symbols = {symbol.get("name"): symbol for symbol in renderer.iter("symbol")}
                self.assertEqual(sorted(symbols, key=int), [str(index) for index in range(12)])
                self.assertEqual({rule.get("symbol") for rule in rules}, set(symbols))
                self.assertEqual({symbol.get("type") for symbol in symbols.values()},
                                 {SYMBOLS[table]})

    def test_colors_are_distinct_and_in_qgis_format(self) -> None:
        """RF-012-20: cada tipo tiene un color propio (el de su contorno o su línea o su punto) en
        el formato ``r,g,b,a``; los límites, de polígono, solo con contorno (sin relleno)."""
        for table in LAYERS:
            with self.subTest(table):
                root = _parsed(table)
                (renderer,) = root.iter("renderer-v2")
                symbols = {symbol.get("name"): symbol for symbol in renderer.iter("symbol")}
                by_rule = {rule.get("label"): symbols[rule.get("symbol")]
                           for rule in renderer.iter("rule")}
                colors = {}
                for label, symbol in by_rule.items():
                    options = _options(symbol)
                    keys = [key for key in options if key.endswith("color")]
                    self.assertTrue(keys, label)
                    for key in keys:
                        self.assertRegex(options[key], COLOR, f"{label}: {key}")
                    colors[label] = options["outline_color" if table != LAYERS[1] else
                                            "line_color"]
                self.assertEqual(len(set(colors.values())), 12, colors)
                if table == LAYERS[0]:
                    for ctype in OUTLINE_ONLY:
                        self.assertEqual(_options(by_rule[ctype.label("es")])["style"], "no")
                    self.assertEqual(_options(by_rule["Intocable"])["style"], "solid")

    def test_unknown_table_is_an_error(self) -> None:
        """RF-012-20: solo hay estilo de las tres capas de restricciones."""
        with self.assertRaises(ValueError):
            styles.style_for("core_sector")


PROJECT_QML_SHA256 = {
    "core_constraint_polygon": "57ca39b9848cbb249ca30b11966e2f10ec84dcc198eb66a7b010a75c38181387",
    "core_constraint_line": "506c300c52b5e7911b878f029dd58471f58079685146798cbc0b8deec20a6459",
    "core_constraint_point": "936b4454b1055281910b3157d2ab641d22ea27a55be03380140730d5bfe04c8b",
}
"""El sha256 del QML de cada capa del proyecto **antes** de la T22 de la 015: no cambia."""
DECLARED = "des_decl_v01"
ENTITIES = "des_enl_v01"
CATEGORIES = "Symbology|Forms|Notes"


def _version_root(table: str, fields: Any = None) -> ET.Element:
    return ET.fromstring(styles.style_for(table, fields).qml.split("\n", 1)[1])


def _symbols(root: ET.Element) -> dict[str, ET.Element]:
    (renderer,) = root.iter("renderer-v2")
    return {symbol.get("name", ""): symbol for symbol in renderer.iter("symbol")}


def _by_label(root: ET.Element) -> dict[str, ET.Element]:
    """Cada regla del estilo por su nombre (el símbolo que dibuja, ya resuelto)."""
    symbols = _symbols(root)
    (renderer,) = root.iter("renderer-v2")
    return {rule.get("label", ""): symbols[rule.get("symbol", "")] for rule in renderer.iter("rule")}


def _editable(root: ET.Element) -> dict[str, str]:
    (editable,) = root.iter("editable")
    return {field.get("name", ""): field.get("editable", "") for field in editable.iter("field")}


class VersionLayerStyleTest(unittest.TestCase):
    """El estilo de las capas de una versión, ``des_decl_<vNN>`` y ``des_enl_<vNN>`` (spec 015, T22;
    RF-012-20, RF-015-27, RF-009-05; plan 015 §5.7, §5.8 y §8)."""

    def test_version_layers_are_recognised_by_name(self) -> None:
        """RF-012-20, RF-015-27: ``des_decl_<vNN>`` y ``des_enl_<vNN>`` son las capas de una versión (la
        ubicación de ``des_decl`` y ``des_enl``: ``version_locator``); ninguna otra tabla lo es."""
        self.assertIs(styles.version_layer(DECLARED), styles.VersionLayer.DECLARED)
        self.assertIs(styles.version_layer("des_enl_v12"), styles.VersionLayer.ENTITIES)
        self.assertEqual((styles.DECLARED_LAYER, styles.ENTITY_LAYER), ("des_decl", "des_enl"))
        self.assertEqual(styles.DECLARED_LAYER, declared_mod.DATASET_NAME)
        self.assertEqual(styles.ENTITY_LAYER, design_provenance.dataset_name("enl"))
        self.assertIsNone(styles.version_layer(LAYERS[0]))  # una del proyecto no es de versión
        self.assertIsNone(styles.version_layer(None))
        for other in ("des_decl", "des_decl_v", "des_decl_V01", "des_decl_v01x", "des_enl_x_v01",
                      "des_epr_planta_v01", "layer_styles", ""):
            with self.subTest(other):
                self.assertIsNone(styles.version_layer(other))
                with self.assertRaises(ValueError):
                    styles.style_for(other)

    def test_declared_has_the_style_of_the_project_polygons_by_type(self) -> None:
        """RF-012-20: la capa de las declaradas se abre con **el mismo estilo** por tipo que la de polígonos
        del proyecto (una regla por tipo y la de lo sin tipo, el mismo filtro sobre ``ctype``, el mismo
        nombre en español, el mismo símbolo y el mismo color: :data:`COLORS`), con sus propias claves de
        regla y un nombre de estilo propio."""
        row = styles.style_for(DECLARED)
        self.assertTrue(row.qml.startswith("<!DOCTYPE qgis"))
        self.assertLessEqual(len(row.name), 30)  # TEXT(30) de QGIS
        self.assertEqual(row.name, styles.DECLARED_STYLE_NAME)
        self.assertNotEqual(row.name, styles.style_for(LAYERS[0]).name)
        root = _version_root(DECLARED)
        project = _parsed(LAYERS[0])
        self.assertEqual(root.get("styleCategories"), CATEGORIES)
        (renderer,) = root.iter("renderer-v2")
        (reference,) = project.iter("renderer-v2")
        self.assertEqual(renderer.get("type"), "RuleRenderer")
        rules, expected = list(renderer.iter("rule")), list(reference.iter("rule"))
        self.assertEqual(len(rules), 12)
        for rule, ctype in zip(rules[:-1], T, strict=True):
            self.assertEqual(rule.get("filter"), f'"ctype" = \'{ctype.value}\'')
            self.assertEqual(rule.get("label"), ctype.label("es"))
        self.assertEqual(rules[-1].get("filter"), "ELSE")
        self.assertEqual(rules[-1].get("label"), styles.ELSE_LABEL)
        mine, theirs = _symbols(root), _symbols(project)
        for rule, same in zip(rules, expected, strict=True):
            self.assertEqual((rule.get("filter"), rule.get("label"), rule.get("symbol")),
                             (same.get("filter"), same.get("label"), same.get("symbol")))
            self.assertEqual(_options(mine[rule.get("symbol", "")]),
                             _options(theirs[same.get("symbol", "")]))
            self.assertNotEqual(rule.get("key"), same.get("key"))
        for ctype in T:
            red, green, blue = styles.COLORS[ctype]
            self.assertEqual(_options(_by_label(root)[ctype.label("es")])["outline_color"],
                             f"{red},{green},{blue},255")
        self.assertEqual(len({rule.get("key") for rule in rules}), 12)

    def test_declared_fields_are_all_read_only_with_a_note(self) -> None:
        """RF-012-20 («marcadas no editables a mano»): el QML lleva la editabilidad de **todos** los campos
        de la capa (``fid`` y las columnas de ``des_decl_``) a ``0`` en la categoría de formularios, y la
        nota de la capa, en español, que dice que no se edita a mano; sin las categorías de campos ni
        de formularios de más (el resto de la capa queda como está)."""
        root = _version_root(DECLARED)
        self.assertEqual(_editable(root), {name: "0" for name in ("fid", *declared_mod.COLUMN_NAMES)})
        (note,) = root.iter("userNotes")
        text = note.get("value", "")
        self.assertIn("no se edita a mano", text)
        self.assertIn("entidad", text)
        categories = (root.get("styleCategories") or "").split("|")
        self.assertEqual(categories, ["Symbology", "Forms", "Notes"])

    def test_the_fields_of_the_live_table_are_the_ones_marked(self) -> None:
        """RF-012-20: con la lista de las columnas que tiene la tabla de verdad (``fields``), el QML las
        marca **todas** y solo ellas (una columna de más de la capa de entidades, una cifra, también)."""
        fields = ("fid", "kind", "name", "state", "supports", "chain", "plat_area_m2")
        root = _version_root(ENTITIES, fields)
        self.assertEqual(_editable(root), dict.fromkeys(fields, "0"))
        self.assertEqual(set(_editable(_version_root(ENTITIES))),
                         {"fid", *styles.ENTITY_FIELDS})

    def test_entities_by_kind_with_the_state_rule(self) -> None:
        """RF-015-27, RF-012-20: la capa de entidades se abre con un estilo **por tipo de entidad**
        (``kind``: la plataforma, los cuatro de la 016 —acopio, retirada, contrafuerte y cuerpo
        apoyado, con los colores de los objetos de la vista— y los dos de la 017 —la pista y la accesibilidad—,
        y «otra entidad» para un tipo que no tenga el suyo) y por estado (``state``): la descartada, atenuada (relleno casi transparente y contorno
        discontinuo); la de «apoyo retirado», marcada (contorno grueso y de otro color); las demás,
        normales. Los símbolos son de relleno, con colores ``r,g,b,a``."""
        root = _version_root(ENTITIES)
        self.assertEqual(root.get("styleCategories"), CATEGORIES)
        (renderer,) = root.iter("renderer-v2")
        self.assertEqual(renderer.get("type"), "RuleRenderer")
        rules = list(renderer.iter("rule"))
        self.assertEqual(len(rules), 27)  # ocho tipos y «otra entidad», cada uno en sus tres reglas
        self.assertEqual(len({rule.get("key") for rule in rules}), 27)
        by_label = _by_label(root)
        self.assertEqual({kind: (label, rgb) for kind, (label, rgb) in styles.ENTITY_KINDS.items()}, {
            "platform": ("Plataforma", (176, 96, 64)), "stockpile": ("Acopio", (217, 140, 26)), "removal": ("Retirada", (204, 77, 64)),
            "buttress": ("Contrafuerte", (128, 102, 204)), "body": ("Cuerpo apoyado", (77, 140, 217)),
            "road": ("Pista", (118, 118, 118)), "access": ("Accesibilidad", (51, 166, 153)), "pit": ("Corta", (166, 77, 128))},
            "los colores de la 016 son los de bl.scene.entity_views.COLORS (0 a 1) a 0 a 255")
        self.assertEqual(list(by_label), [
            f"{label}{suffix}" for label in ("Plataforma", "Acopio", "Retirada", "Contrafuerte", "Cuerpo apoyado", "Pista", "Accesibilidad", "Corta",
                          styles.ENTITY_OTHER_LABEL)
            for suffix in ("", " descartada", " con el apoyo retirado")])
        for symbol in by_label.values():
            self.assertEqual(symbol.get("type"), "fill")
            for key, value in _options(symbol).items():
                if key.endswith("color"):
                    self.assertRegex(value, COLOR, key)
        filters = [rule.get("filter") for rule in rules]
        self.assertEqual(filters[:3], [
            "\"kind\" = 'platform' AND coalesce(\"state\", '') NOT IN ('discarded', 'support_removed')",
            "\"kind\" = 'platform' AND \"state\" = 'discarded'",
            "\"kind\" = 'platform' AND \"state\" = 'support_removed'"])
        red, green, blue = styles.ENTITY_KINDS["platform"][1]
        normal, faded, marked = (_options(by_label[label]) for label in (
            "Plataforma", "Plataforma descartada", "Plataforma con el apoyo retirado"))
        self.assertEqual((normal["color"], normal["outline_color"], normal["outline_style"]),
                         (f"{red},{green},{blue},{styles.FILL_ALPHA}", f"{red},{green},{blue},255",
                          "solid"))
        self.assertLess(int(faded["color"].split(",")[3]), int(normal["color"].split(",")[3]))
        self.assertLess(int(faded["outline_color"].split(",")[3]), 255)
        self.assertEqual(faded["outline_style"], "dash")
        self.assertEqual(marked["color"], normal["color"])
        self.assertNotEqual(marked["outline_color"], normal["outline_color"])
        self.assertGreater(float(marked["outline_width"]), float(normal["outline_width"]))
        # la regla de los demás tipos no repite lo de los que tienen estilo propio
        self.assertTrue(str(filters[3 * len(styles.ENTITY_KINDS)]).startswith(
            "coalesce(\"kind\", '') NOT IN ('platform', 'stockpile', 'removal', 'buttress', 'body', 'road', 'access', 'pit')"))
        for index, kind in enumerate(styles.ENTITY_KINDS):  # cada tipo, en sus tres reglas (normal, descartada y con el apoyo retirado)
            self.assertEqual([str(item)[:len(f"\"kind\" = '{kind}'")] for item in filters[3 * index:3 * index + 3]], [f"\"kind\" = '{kind}'"] * 3)

    def test_entity_style_names_the_kinds_and_states_of_design(self) -> None:
        """RF-015-27: el contrato del estilo con la capa de entidades de ``design`` (T30): los tipos
        con estilo propio son los de ``EntityKind`` (los siete: los cuatro de la 016 desde su T35 y la pista y la accesibilidad de la 017,
        T03, tienen el suyo) y los
        estados que el estilo distingue son valores de ``EntityState``."""
        self.assertEqual(set(styles.ENTITY_KINDS), {kind.value for kind in entities_mod.EntityKind})
        self.assertIn("platform", styles.ENTITY_KINDS)
        states = {state.value for state in entities_mod.EntityState}
        self.assertLessEqual({*styles.ENTITY_FADED_STATES, *styles.ENTITY_MARKED_STATES}, states)
        self.assertEqual(styles.ENTITY_FADED_STATES, ("discarded",))
        self.assertEqual(styles.ENTITY_MARKED_STATES, ("support_removed",))
        self.assertEqual(styles.ENTITY_FIELDS, ("kind", "name", "state", "supports", "chain"))

    def test_the_project_styles_are_exactly_as_before(self) -> None:
        """RF-012-20: generalizar el estilo no cambia ni un byte de las tres capas del proyecto de la 012."""
        for table, digest in PROJECT_QML_SHA256.items():
            with self.subTest(table):
                self.assertEqual(hashlib.sha256(styles.style_for(table).qml.encode("utf-8")).hexdigest(),
                                 digest)
                self.assertEqual(styles.style_for(table).name, "Restricciones por tipo")


class StyleTableTest(unittest.TestCase):
    """La tabla ``layer_styles`` en un GeoPackage."""

    def test_written_with_the_qgis_schema_and_one_default_per_layer(self) -> None:
        """RF-012-20, RF-008-62: con las tres capas creadas, ``layer_styles`` tiene el esquema que
        escribe QGIS 4.2 (el de ``gis.vector``), está en ``gpkg_contents`` como ``attributes`` y
        lleva un estilo por defecto por capa, con la tabla y la columna de geometría; la función
        dice que escribió el dato ``core_layer_styles``."""
        with project_tmp() as tmp:
            db, created = _with_tables(tmp / "p.gpkg")
            with db:
                with db.transaction() as conn:
                    self.assertEqual(styles.write_styles(conn, created), ("core_layer_styles",))
                conn = db.connection
                columns = [row[1] for row in conn.execute("PRAGMA table_info(layer_styles)")]
                self.assertEqual(columns, [
                    "id", "f_table_catalog", "f_table_schema", "f_table_name",
                    "f_geometry_column", "styleName", "styleQML", "styleSLD", "useAsDefault",
                    "description", "owner", "ui", "update_time"])
                (sql,) = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'layer_styles'"
                                      ).fetchone()
                self.assertEqual(sql, gis_vector._STYLES_DDL)
                self.assertEqual(conn.execute(
                    "SELECT data_type, identifier FROM gpkg_contents WHERE "
                    "table_name = 'layer_styles'").fetchall(), [("attributes", "layer_styles")])
                rows = conn.execute(
                    "SELECT f_table_name, f_geometry_column, styleName, useAsDefault, "
                    "styleQML FROM layer_styles ORDER BY id").fetchall()
                self.assertEqual([row[:4] for row in rows], [
                    (table, "geom", styles.style_for(table).name, 1) for table in LAYERS])
                for row in rows:
                    self.assertEqual(row[4], styles.style_for(row[0]).qml)
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_repeating_writes_nothing_and_a_default_is_respected(self) -> None:
        """RF-012-20: repetir no duplica ni devuelve nada que registrar; una capa con un estilo
        por defecto que no es el nuestro (QGIS guardó el suyo) lo conserva; una capa creada
        después recibe el suyo en la tabla que ya existe."""
        with project_tmp() as tmp:
            db = _new(tmp / "p.gpkg")
            with db:
                with db.transaction() as conn:
                    store.create_tables(conn, SRS)
                    conn.execute(gis_vector._STYLES_DDL)
                    conn.execute("INSERT INTO layer_styles (f_table_name, f_geometry_column, "
                                 "styleName, styleQML, useAsDefault) VALUES "
                                 "('core_constraint_line', 'geom', 'Mío', '<qgis/>', 1)")
                    self.assertEqual(styles.write_styles(conn, LAYERS[:2]), ("core_layer_styles",))
                    self.assertEqual(styles.write_styles(conn, LAYERS[:2]), ())
                    self.assertEqual(styles.write_styles(conn, ("core_sector", "core_intention")),
                                     ())
                    self.assertEqual(styles.write_styles(conn, LAYERS), ("core_layer_styles",))
                    self.assertEqual(styles.write_styles(conn, LAYERS), ())
                rows = db.connection.execute(
                    "SELECT f_table_name, styleName FROM layer_styles ORDER BY id").fetchall()
                self.assertEqual(rows, [
                    ("core_constraint_line", "Mío"),
                    ("core_constraint_polygon", styles.style_for(LAYERS[0]).name),
                    ("core_constraint_point", styles.style_for(LAYERS[2]).name)])
                self.assertEqual(db.connection.execute(
                    "SELECT count(*) FROM gpkg_contents WHERE table_name = 'layer_styles'"
                ).fetchone()[0], 1)

    def test_other_tables_have_no_style(self) -> None:
        """RF-012-20: sin ninguna capa de restricciones entre las creadas no se crea la tabla."""
        with project_tmp() as tmp:
            db = _new(tmp / "p.gpkg")
            with db:
                with db.transaction() as conn:
                    store.create_tables(conn, SRS)
                    self.assertEqual(styles.write_styles(conn, ("core_sector",)), ())
                    self.assertEqual(styles.write_styles(conn, ()), ())
                tables = {row[0] for row in db.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'")}
                self.assertNotIn("layer_styles", tables)

    def test_dataset_spec(self) -> None:
        """RF-008-62, RF-008-56: el dato es ``core_layer_styles``, de ``core``, una tabla de
        ``project.gpkg`` (``layer_styles``) leída con ``core.gpkg_layer@1`` y editable en QGIS."""
        spec = styles.dataset_spec()
        self.assertIsInstance(spec, datasets.DatasetSpec)
        self.assertEqual((spec.name, spec.module, spec.kind, spec.store, spec.locator),
                         ("core_layer_styles", "core", "table", datasets.Store.GPKG,
                          "layer_styles"))
        self.assertEqual((spec.reader, spec.role, spec.qgis_editable),
                         ("core.gpkg_layer@1", "styles", True))
        self.assertEqual((styles.STYLES_TABLE, styles.STYLES_DATASET),
                         ("layer_styles", "core_layer_styles"))


class VersionStyleRowsTest(unittest.TestCase):
    """Las filas de ``layer_styles`` de las capas de una versión, en la transacción de quien las escribe
    (spec 015, T22; RF-012-20, RF-015-27, RF-009-05)."""

    def _db(self, tmp: Path) -> Any:
        db, created = _with_tables(tmp / "p.gpkg")
        with db.transaction() as conn:
            styles.write_styles(conn, created)  # lo que hizo la primera operación de la 012
            declared_mod.create_declared_table(conn, DECLARED, SRS)
        return db

    def test_row_with_the_columns_the_table_really_has(self) -> None:
        """RF-012-20, RF-015-27: ``insert_version_styles`` pone en ``layer_styles`` el estilo **por defecto**
        de la capa de la versión, con la tabla y la columna de geometría, el nombre propio, y en el QML
        la editabilidad de **cada columna que tiene la tabla** (``PRAGMA table_info``: las que añada
        la capa de entidades también); devuelve la tabla escrita; repetirlo no duplica ni cambia nada."""
        with project_tmp() as tmp:
            db = self._db(tmp)
            with db:
                with db.transaction() as conn:
                    conn.execute(f'ALTER TABLE "{DECLARED}" ADD COLUMN extra DOUBLE')
                    self.assertEqual(styles.insert_version_styles(conn, [DECLARED, "core_sector"]),
                                     (DECLARED,))
                    self.assertEqual(styles.insert_version_styles(conn, [DECLARED]), ())
                rows = db.connection.execute(
                    "SELECT f_table_name, f_geometry_column, styleName, useAsDefault, styleQML "
                    "FROM layer_styles WHERE f_table_name = ?", (DECLARED,)).fetchall()
                self.assertEqual([row[:4] for row in rows],
                                 [(DECLARED, "geom", styles.DECLARED_STYLE_NAME, 1)])
                root = ET.fromstring(rows[0][4].split("\n", 1)[1])
                self.assertEqual(set(_editable(root)),
                                 {"fid", *declared_mod.COLUMN_NAMES, "extra"})
                self.assertEqual(db.connection.execute(
                    "SELECT count(*) FROM layer_styles").fetchone()[0], 4)  # las tres del proyecto y esta

    def test_rows_belong_to_the_transaction(self) -> None:
        """RF-009-05, RF-015-27: la fila se escribe **en la transacción** de quien produce la capa: si esa
        transacción se deshace, ni la fila ni nada queda."""
        with project_tmp() as tmp:
            db = self._db(tmp)
            with db:
                with self.assertRaises(RuntimeError):
                    with db.transaction() as conn:
                        styles.insert_version_styles(conn, [DECLARED])
                        raise RuntimeError("falló lo que sigue")
                self.assertEqual(db.connection.execute(
                    "SELECT count(*) FROM layer_styles WHERE f_table_name = ?", (DECLARED,)
                ).fetchone()[0], 0)

    def test_a_default_that_qgis_saved_is_respected_and_no_table_is_created(self) -> None:
        """RF-012-20: un estilo por defecto que ya tiene la capa (lo guardó QGIS) se respeta; y si el
        proyecto no tiene ``layer_styles`` (ninguna operación de la 012 la creó) no se crea aquí: sin el
        dato ``core_layer_styles`` quedaría como «tabla sin registrar» (RF-008-62)."""
        with project_tmp() as tmp:
            db = self._db(tmp)
            with db:
                with db.transaction() as conn:
                    conn.execute("INSERT INTO layer_styles (f_table_name, f_geometry_column, styleName, "
                                 "styleQML, useAsDefault) VALUES (?, 'geom', 'Mío', '<qgis/>', 1)",
                                 (DECLARED,))
                    self.assertEqual(styles.insert_version_styles(conn, [DECLARED]), ())
                self.assertEqual(db.connection.execute(
                    "SELECT styleName FROM layer_styles WHERE f_table_name = ?", (DECLARED,)
                ).fetchall(), [("Mío",)])
        with project_tmp() as tmp:
            db = _new(tmp / "q.gpkg")
            with db:
                with db.transaction() as conn:
                    declared_mod.create_declared_table(conn, DECLARED, SRS)
                    self.assertEqual(styles.insert_version_styles(conn, [DECLARED]), ())
                names = {row[0] for row in db.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'")}
                self.assertNotIn("layer_styles", names)


class OperationStylesTest(unittest.TestCase):
    """La primera operación de ``core`` que crea las tablas escribe y registra los estilos."""

    def test_first_operation_writes_and_registers_the_styles(self) -> None:
        """RF-012-20, RF-008-62: ``core.declare_sectors`` (sin sectores) crea las siete tablas, los
        tres estilos y los registra como salida (``core_layer_styles``, al día y editable); la
        comprobación de tablas sin registrar no encuentra nada; una segunda operación no vuelve a
        escribirlos."""
        with project_tmp("gb-st-") as tmp, registered(*cprov.OPERATIONS):
            (tmp / "proyectos").mkdir()
            clock = FakeClock()
            project = create.create_project(
                tmp / "proyectos", make_settings(), make_session(),
                userdata_mod.UserData(tmp / "u"), clock=clock).project
            try:
                srs = project.record.crs_epsg
                cprov.declare_sectors(project, (), source=None, field=None, uncovered_m2=None,
                                      srs_id=srs)
                with project.read() as conn:
                    record = registry.get(conn, "core_layer_styles")
                    self.assertIsNotNone(record)
                    assert record is not None
                    self.assertEqual((record.locator, record.status, record.qgis_editable),
                                     ("layer_styles", datasets.DatasetStatus.CURRENT, True))
                    self.assertEqual(orphans.unregistered_tables(conn), ())
                    self.assertEqual(conn.execute("SELECT count(*) FROM layer_styles"
                                                  ).fetchone()[0], 3)
                    before = record.content_sha256
                clock.advance(minutes=1)
                cprov.declare_sectors(project, (), source=None, field=None, uncovered_m2=None,
                                      srs_id=srs)
                with project.read() as conn:
                    again = registry.get(conn, "core_layer_styles")
                    assert again is not None
                    self.assertEqual(again.content_sha256, before)
                    self.assertEqual(conn.execute("SELECT count(*) FROM layer_styles"
                                                  ).fetchone()[0], 3)
                    self.assertEqual(orphans.unregistered_tables(conn), ())
            finally:
                project.close()


if __name__ == "__main__":
    unittest.main()

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

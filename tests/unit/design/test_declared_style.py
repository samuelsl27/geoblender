# SPDX-License-Identifier: GPL-3.0-or-later
"""El estilo QGIS de la capa de las restricciones declaradas (spec 015, T22; HU-015-1; RF-012-20, RF-015-27,
RF-009-05, RF-008-21, RF-008-56, RF-008-62; plan 015 §5.7, §5.8 y §8).

La capa ``des_decl_<vNN>`` es **de una versión**, no editable a mano, y debe abrirse en QGIS 4.2 con su estilo
por tipo y con sus campos de solo lectura. Su estilo vive en la tabla ``layer_styles`` del GeoPackage del
proyecto, que es del proyecto (el dato ``core_layer_styles``, editable a mano: QGIS la escribe al guardar un
estilo) y no de una versión: una operación de versión no puede escribirla como salida (RF-009-05). Sobre la
cantera sintética de la 014 con las capas de plataformas (``tests.support.entity_fixtures``):

- **La fila** (:class:`DeclaredStyleTest`): la primera declaración de la versión escribe la fila por defecto de
  ``des_decl_v01`` **con la capa**, con el QML con las columnas que tiene la tabla de verdad; repetir la
  declaración no la duplica ni toca ``core_layer_styles``; otra versión tiene la suya; las tres capas del
  proyecto de la 012 siguen con su estilo exactamente como antes.
- **El dato del proyecto** (:class:`DeclaredStyleTest`): ``core_layer_styles`` queda **al día** (su hash y su
  seguimiento son los de lo escrito: la comprobación de datos no lo toma por una edición fuera de Geoblender, no
  se bloquea ni queda sin registrar) y la operación de versión **no** lo tiene como salida; el cambio queda en
  su historia con esa operación.
- **Una edición que ya había** (:class:`OutsideEditNotSwallowedTest`): si alguien tocó ``layer_styles`` en QGIS
  antes de declarar, la comprobación sigue viéndola como una edición (no se traga).
- **La transacción** (:class:`StyleRollbackTest`): si la operación no se completa, no quedan ni la capa, ni su
  fila, ni lo anotado en ``core_layer_styles``.
"""

from __future__ import annotations

import hashlib
import sqlite3
import xml.etree.ElementTree as ET
from typing import Any, ClassVar
from unittest import mock

from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.unit.design import test_declare_operation as decl
from tests.unit.design import test_platform_operation as ops
from tests.unit.design import test_platform_prepare as prep

cstyles = import_geoblender("core.constraints.styles")
declared_mod = import_geoblender("core.constraints.declared")
cstore = import_geoblender("core.constraints.store")
datasets = import_geoblender("core.datasets")
external = import_geoblender("core.datasets.external")
orphans = import_geoblender("core.datasets.orphans")
registry = import_geoblender("core.datasets.registry")
tracking = import_geoblender("core.datasets.tracking")
contract = import_geoblender("core.provenance.contract")
operations = import_geoblender("core.provenance.operations")

TABLE = decl.TABLE
GUARD_M = decl.GUARD_M
WORKSHOP = decl.WORKSHOP
STYLES = "core_layer_styles"
PROJECT_LAYERS = tuple(cstore.CONSTRAINT_LAYERS.values())
PROJECT_QML_SHA256 = {
    "core_constraint_polygon": "57ca39b9848cbb249ca30b11966e2f10ec84dcc198eb66a7b010a75c38181387",
    "core_constraint_line": "506c300c52b5e7911b878f029dd58471f58079685146798cbc0b8deec20a6459",
    "core_constraint_point": "936b4454b1055281910b3157d2ab641d22ea27a55be03380140730d5bfe04c8b",
}
"""El sha256 del QML de cada capa del proyecto antes de la T22: lo que escribió siempre la 012."""


class StyleCase(decl.DeclareCase):
    """Lo de ``DeclareCase`` (con ``core.external_edit``, que registra ``bl``, para la comprobación de datos) y
    los ayudantes para mirar ``layer_styles`` y su dato."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.enterClassContext(registered(*[item for item in contract.CORE_OPERATIONS
                                           if item.op_type not in contract.OPERATIONS]))

    @classmethod
    def style_rows(cls, table: str | None = None) -> list[tuple[Any, ...]]:
        """Las filas de ``layer_styles`` (de la capa ``table``, o todas), por ``id``: capa, columna de
        geometría, nombre, ``useAsDefault`` y el QML."""
        sql = ("SELECT f_table_name, f_geometry_column, styleName, useAsDefault, styleQML "
               "FROM layer_styles")
        if table is None:
            return cls.query_of(sql + " ORDER BY id")
        return cls.query_of(sql + " WHERE f_table_name = ? ORDER BY id", table)

    @classmethod
    def styles_record(cls) -> Any:
        """El dato ``core_layer_styles`` del proyecto."""
        with cls.project.read() as conn:
            return registry.get(conn, STYLES)

    @classmethod
    def styles_changes(cls) -> list[tuple[Any, ...]]:
        """La historia de ``core_layer_styles``: hash anterior, hash nuevo y tipo de operación que lo cambió."""
        return cls.query_of(
            "SELECT c.from_sha256, c.to_sha256, o.op_type FROM gb_dataset_change AS c JOIN gb_operation "
            "AS o ON o.uid = c.operation_uid JOIN gb_dataset AS d ON d.uid = c.dataset_uid WHERE "
            "d.name = ? ORDER BY c.fid", STYLES)

    @classmethod
    def checked(cls) -> Any:
        """La comprobación de los datos del proyecto (la de antes de operar) hasta el final."""
        cls.clock.advance(minutes=1)
        return ops.finish(external.external_check_steps(cls.project))

    @classmethod
    def edited_operations(cls) -> int:
        """Cuántas ediciones externas ha registrado la comprobación (de proyecto y de versión)."""
        return int(cls.query_of("SELECT count(*) FROM gb_operation WHERE op_type LIKE 'core.external_edit%'"
                                )[0][0])

    @classmethod
    def in_sync(cls) -> bool:
        """Si ``core_layer_styles`` está al día: lo anotado (hash y seguimiento) es lo que hay en la tabla."""
        with cls.project.read() as conn:
            record = registry.get(conn, STYLES)
            probe = external.probe_dataset(cls.project, record,
                                           tracking.table_states(conn, [record.locator]))
            same = registry.content_digest(conn, cls.project, record).content_sha256
        return probe.signal is external.Signal.UNCHANGED and same == record.content_sha256


def parsed(qml: str) -> ET.Element:
    """El QML sin la línea del ``DOCTYPE``."""
    return ET.fromstring(qml.split("\n", 1)[1])


class DeclaredStyleTest(StyleCase):
    """P1 (la «Plataforma de carga», que no protege) y P2 (la «Plataforma de taller», que protege con 4 m)
    creadas en V01 y declaradas: lo que queda en ``layer_styles`` y en su dato."""

    before_declaring: ClassVar[list[tuple[Any, ...]]]
    first_hash: ClassVar[str]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())
        cls.clock.advance(minutes=1)
        cls.made(prep.request(decl.WORKSHOP, start="entity:PLT-001", protect=True, guard_m=GUARD_M))
        cls.before_declaring = cls.style_rows()
        cls.entities_declared()

    def test_a_the_first_declaration_writes_the_default_style_of_its_layer(self) -> None:
        """RF-012-20, RF-015-27: tras declarar V01, ``layer_styles`` tiene, además de las tres del proyecto,
        **una** fila por defecto de ``des_decl_v01`` (su columna de geometría, el nombre propio), con el QML
        por tipo de ``core.constraints.styles``: sus reglas, sus colores y **todos** los campos de la tabla
        de verdad (``fid`` y las columnas de la 015) marcados de solo lectura."""
        self.assertEqual([row[0] for row in self.before_declaring], list(PROJECT_LAYERS))
        rows = self.style_rows(TABLE)
        self.assertEqual([row[:4] for row in rows], [(TABLE, "geom", cstyles.DECLARED_STYLE_NAME, 1)])
        self.assertEqual([row[0] for row in self.style_rows()], [*PROJECT_LAYERS, TABLE])
        with self.project.read() as conn:
            columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{TABLE}")') if row[1] != "geom"]
        self.assertEqual(columns, ["fid", *declared_mod.COLUMN_NAMES])
        root = parsed(rows[0][4])
        (editable,) = root.iter("editable")
        self.assertEqual({field.get("name"): field.get("editable") for field in editable.iter("field")},
                         dict.fromkeys(columns, "0"))
        self.assertEqual(rows[0][4], cstyles.style_for(TABLE, columns).qml)
        (renderer,) = root.iter("renderer-v2")
        self.assertEqual(len(list(renderer.iter("rule"))), 12)
        self.assertEqual(root.get("styleCategories"), "Symbology|Forms|Notes")

    def test_b_the_project_dataset_is_up_to_date_not_edited_outside(self) -> None:
        """RF-009-05, RF-008-21, RF-008-56, RF-008-62: ``core_layer_styles`` queda **al día** (el prefiltro de
        la comprobación de datos no salta y su hash es el de la tabla, con la fila nueva); la comprobación de
        todos los datos no registra ninguna edición externa, no deja nada bloqueado ni sin registrar y el
        dato sigue vigente y editable en QGIS."""
        self.assertTrue(self.in_sync())
        record = self.styles_record()
        self.assertEqual((record.status, record.qgis_editable, record.locator),
                         (datasets.DatasetStatus.CURRENT, True, "layer_styles"))
        checked = self.checked()
        mine = [item for item in checked.findings if item.record.name == STYLES]
        self.assertTrue(all(item.verdict in (external.DatasetVerdict.UNCHANGED, external.DatasetVerdict.SAME)
                            for item in mine), mine)
        self.assertEqual(self.edited_operations(), 0)
        with self.project.read() as conn:
            self.assertEqual(external.unusable(conn), ())
            self.assertEqual(orphans.unregistered_tables(conn), ())

    def test_c_the_version_operation_does_not_write_the_project_dataset(self) -> None:
        """RF-009-05: la operación de versión que escribió la fila (la primera declaración) **no** tiene
        ``core_layer_styles`` como salida ni lo hace «suyo» (el dato sigue siendo del proyecto y de la
        operación de la 012 que lo creó); su cambio queda en la historia del dato, atribuido a esa
        declaración: el hash de antes, el de ahora."""
        record = self.styles_record()
        history = self.styles_changes()
        types = [item[2] for item in history]
        self.assertTrue(all(kind.startswith("core.") for kind in types[:-1]), types)  # la 012 lo creó
        self.assertEqual(types[-1], "des.declare_constraints")
        self.assertEqual(types.count("des.declare_constraints"), 1)
        self.assertEqual(history[-1][0], history[-2][1])
        self.assertEqual(history[-1][1], record.content_sha256)
        ((scope, version, written_by),) = self.query_of(
            "SELECT o.op_type, d.version_uid, d.operation_uid FROM gb_dataset AS d JOIN gb_operation AS o "
            "ON o.uid = d.operation_uid WHERE d.name = ?", STYLES)
        self.assertTrue(scope.startswith("core.") and scope != "des.declare_constraints", scope)
        self.assertEqual(version, "")
        outputs = self.query_of(
            "SELECT count(*) FROM gb_operation_io AS io JOIN gb_operation AS o ON o.uid = io.operation_uid "
            "WHERE o.op_type = ? AND io.direction = 'out' AND io.item_uid = ?", decl.DECLARE, record.uid)
        self.assertEqual(outputs, [(0,)])
        self.assertNotEqual(written_by, self.current_declaration())

    def test_d_declaring_again_writes_nothing_more(self) -> None:
        """RF-015-27: repetir la declaración (la tabla se reescribe entera) no duplica la fila ni toca el
        dato del proyecto: mismas filas, mismo hash de ``core_layer_styles`` y la misma historia."""
        rows, history, record = self.style_rows(), self.styles_changes(), self.styles_record()
        self.declare()
        self.assertEqual(self.style_rows(), rows)
        self.assertEqual(self.styles_changes(), history)
        self.assertEqual(self.styles_record().content_sha256, record.content_sha256)
        self.assertTrue(self.in_sync())

    def test_e_another_version_has_its_own_row_and_the_dataset_stays_up_to_date(self) -> None:
        """RF-012-29, RF-012-20: la declarada es de su versión: declarar V02 pone la fila de ``des_decl_v02``
        (con el mismo estilo) y deja ``core_layer_styles`` al día otra vez, sin ninguna edición externa."""
        self.declare(self.v2)
        rows = self.style_rows("des_decl_v02")
        self.assertEqual([row[:4] for row in rows],
                         [("des_decl_v02", "geom", cstyles.DECLARED_STYLE_NAME, 1)])
        self.assertEqual(rows[0][4], self.style_rows(TABLE)[0][4])  # el mismo estilo, las mismas claves
        self.assertTrue(self.in_sync())
        self.checked()
        self.assertEqual(self.edited_operations(), 0)
        self.assertEqual([item[2] for item in self.styles_changes()][-1], "des.declare_constraints")

    def test_f_the_project_layers_keep_their_style_exactly_as_before(self) -> None:
        """RF-012-20: las tres capas de restricciones del proyecto de la 012 siguen con su fila y su QML
        exactamente como los escribió siempre (``PROJECT_QML_SHA256``); la 015 solo añade las suyas."""
        rows = {row[0]: row for row in self.style_rows()}
        for table, digest in PROJECT_QML_SHA256.items():
            with self.subTest(table):
                self.assertEqual((rows[table][1], rows[table][2], rows[table][3]),
                                 ("geom", "Restricciones por tipo", 1))
                self.assertEqual(hashlib.sha256(rows[table][4].encode("utf-8")).hexdigest(), digest)
        self.assertEqual({row[0] for row in self.style_rows()} - set(PROJECT_LAYERS) - {
            "des_decl_v01", "des_decl_v02"}, set())


class OutsideEditNotSwallowedTest(StyleCase):
    """RF-008-21: lo que la persona hizo en QGIS sobre ``layer_styles`` **antes** de declarar no se da por
    bueno al anotar la fila de la declaración."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())

    def test_a_a_pending_edit_is_still_an_edit_after_declaring(self) -> None:
        """RF-008-21: QGIS guardó un estilo (una fila más en ``layer_styles``) y nadie lo comprobó aún;
        se declara V01 (que escribe su fila) y la comprobación sigue viendo una edición externa de
        ``core_layer_styles`` (editable a mano: vigente, no bloqueada), con su operación; la fila de la
        declarada está igualmente."""
        self.assertTrue(self.in_sync())
        outside = sqlite3.connect(self.project.database_path)
        try:
            outside.execute(
                "INSERT INTO layer_styles (f_table_name, f_geometry_column, styleName, styleQML, "
                "useAsDefault) VALUES ('core_sector', 'geom', 'De QGIS', '<qgis/>', 0)")
            outside.execute("UPDATE gpkg_contents SET last_change = '2031-01-01T00:00:01.000Z' "
                            "WHERE table_name = 'layer_styles'")  # como lo deja QGIS al guardar
            outside.commit()
        finally:
            outside.close()
        self.assertFalse(self.in_sync())
        self.declare()
        self.assertEqual([row[0] for row in self.style_rows(TABLE)], [TABLE])
        self.assertFalse(self.in_sync())
        checked = self.checked()
        (mine,) = [item for item in checked.findings if item.record.name == STYLES]
        self.assertEqual((mine.verdict, mine.status),
                         (external.DatasetVerdict.EDITED, datasets.DatasetStatus.CURRENT))
        self.assertEqual(self.edited_operations(), 1)
        self.assertTrue(self.in_sync())


class StyleRollbackTest(StyleCase):
    """RF-009-05, RF-015-27: la fila y lo anotado en el dato del proyecto son de **la transacción** de la
    operación."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())

    def test_a_a_failure_completing_the_operation_leaves_no_layer_no_row_and_no_note(self) -> None:
        """RF-015-27: si la operación falla al completarse (con la capa y su fila ya escritas en la
        transacción) se deshace todo: no hay ``des_decl_v01``, ni su fila, ni cambio de
        ``core_layer_styles`` (su hash sigue siendo el de la tabla); declarada otra vez sin el fallo, la fila
        está y el dato al día."""
        rows, history, record = self.style_rows(), self.styles_changes(), self.styles_record()
        with mock.patch.object(operations.OperationHandle, "complete",
                               side_effect=RuntimeError("fallo de prueba")):
            with self.assertRaises(RuntimeError):
                self.declare()
        self.assertEqual(self.query_of("SELECT name FROM sqlite_master WHERE name = ?", TABLE), [])
        self.assertEqual(self.style_rows(), rows)
        self.assertEqual(self.styles_changes(), history)
        self.assertEqual(self.styles_record().content_sha256, record.content_sha256)
        self.assertTrue(self.in_sync())
        self.declare()
        self.assertEqual([row[0] for row in self.style_rows(TABLE)], [TABLE])
        self.assertTrue(self.in_sync())

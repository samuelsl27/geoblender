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

import sqlite3
import xml.etree.ElementTree as ET
from typing import Any
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

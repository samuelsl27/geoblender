# SPDX-License-Identifier: GPL-3.0-or-later
"""Pruebas de hito de «test_declared_style» (spec 015, T48; plan 015 §7.4): las clases que pesan,
movidas sin cambiar una aserción. El «verde» deja en ``test_declared_style`` las más ligeras de cada
requisito; las de aquí las ejecuta el paso «hito» de ``tools/check.py --completo`` (la publicación
lo pide siempre).
"""

from __future__ import annotations

import hashlib
from typing import Any, ClassVar

from tests.unit.design import test_declare_operation as decl
from tests.unit.design import test_platform_prepare as prep
from tests.unit.design.test_declared_style import (
    GUARD_M,
    PROJECT_LAYERS,
    PROJECT_QML_SHA256,
    STYLES,
    StyleCase,
    TABLE,
    cstyles,
    datasets,
    declared_mod,
    external,
    orphans,
    parsed,
)


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
        # La capa de entidades (T30) escribe la suya en su propia operación, tras la declaración.
        self.assertEqual([row[0] for row in self.style_rows()], [*PROJECT_LAYERS, TABLE, "des_enl_v01"])
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
        # La 012 lo creó; después, la primera declaración y (T30) la primera capa de entidades, que es otra
        # operación de versión que anota su fila de estilo igual, cada una en su transacción.
        self.assertTrue(all(kind.startswith("core.") for kind in types[:-2]), types)
        self.assertEqual(types[-2:], ["des.declare_constraints", "des.entity_layer"])
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
            "des_decl_v01", "des_decl_v02", "des_enl_v01"}, set())

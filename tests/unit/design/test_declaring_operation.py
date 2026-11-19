# SPDX-License-Identifier: GPL-3.0-or-later
"""Los tipos de operación que declaran restricciones y el gancho de la declaración pendiente (spec 016, T35, decisión de la sesión principal
del 19/11/2026; RF-015-10, RF-015-29, D-1, D-4; hallazgo E-1 de la 015).

El gancho de ``gis.masks.declaring`` (``entity_store.declaration_pending`` y su gemelo de ``bl``) empezaba por una consulta: sin ninguna
operación ``des.platform`` vigente en la versión, nada está pendiente. Pero **el contrafuerte también declara** («sin corte» sobre su zona de
coronación, D-1): en una versión con **solo un contrafuerte que protege**, un Esc entre crearlo y declararlo dejaba las máscaras al día **sin su
restricción**. ``provenance.has_declaring_operation`` lo mira por los dos tipos (``DECLARING_OP_NAMES``) y la consulta sigue siendo una sola; la
prueba de punta a punta (el contrafuerte creado sin que corra lo que sigue y la recuperación) es ``tests/blender/milestone_stockpile_ops.py``.
"""

import sqlite3
import unittest

from tests.support.package import import_geoblender

provenance = import_geoblender("design.provenance")
entity_store = import_geoblender("design.entity_store")

VERSION, OTHER = "uid-v01", "uid-v02"


def database(*operations: tuple[str, str, str, str | None]) -> sqlite3.Connection:
    """Una base de datos de mentira con lo que mira la consulta: las revisiones de dos versiones y las operaciones dadas
    (``(uid, tipo, estado, sustituida por)``, todas de la revisión de ``VERSION``)."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE gb_revision (uid TEXT PRIMARY KEY, version_uid TEXT)")
    conn.execute("CREATE TABLE gb_operation (uid TEXT PRIMARY KEY, revision_uid TEXT, op_type TEXT, status TEXT, superseded_by TEXT)")
    conn.executemany("INSERT INTO gb_revision VALUES (?, ?)", (("rev-1", VERSION), ("rev-2", OTHER)))
    conn.executemany("INSERT INTO gb_operation VALUES (?, 'rev-1', ?, ?, ?)", operations)
    return conn


class DeclaringOperationTest(unittest.TestCase):
    """RF-015-10, D-1 (decisión del 19/11/2026): el contrafuerte declara, como la plataforma, y la retirada, el cuerpo y la detección no."""

    def test_the_types_that_declare_are_the_platform_and_the_buttress(self) -> None:
        """Los tipos que declaran son los de ``entity_store._DECLARES``: la plataforma y el contrafuerte; la detección, la retirada y el cuerpo
        apoyado no declaran nada por defecto (D-1)."""
        self.assertEqual(provenance.DECLARING_OP_NAMES, (provenance.PLATFORM, provenance.BUTTRESS))
        declares = {kind.value for kind in entity_store._DECLARES}
        entities = import_geoblender("design.entities")
        self.assertEqual({entities.entity_type(kind).op_type for kind in declares}, set(provenance.DECLARING_OP_NAMES))
        self.assertTrue(set(provenance.DECLARING_OP_NAMES) < set(provenance.ENTITY_OP_NAMES))

    def test_a_version_with_only_a_buttress_has_a_declaring_operation(self) -> None:
        """RF-015-10: una versión con **solo** un contrafuerte (sin ninguna plataforma) tiene una operación que declara: el gancho **no** da
        por buenas las máscaras; la consulta antigua, solo de la plataforma, decía que no."""
        conn = database(("op-1", provenance.BUTTRESS, "done", None))
        self.addCleanup(conn.close)
        self.assertFalse(provenance.has_platform_operation(conn, VERSION))
        self.assertTrue(provenance.has_declaring_operation(conn, VERSION))

    def test_the_platform_still_declares_and_what_does_not_declare_is_not_counted(self) -> None:
        """Sin cambiar un resultado de la 015: la plataforma declara; la detección, la retirada y el cuerpo no cuentan; una sustituida o
        fallida, tampoco; ni lo de otra versión."""
        for op_type, expected in ((provenance.PLATFORM, True), (provenance.BUTTRESS, True), (provenance.STOCKPILE_DETECT, False),
                                  (provenance.STOCKPILE_REMOVAL, False), (provenance.BODY, False)):
            with self.subTest(tipo=op_type):
                conn = database(("op-1", op_type, "done", None))
                self.addCleanup(conn.close)
                self.assertEqual(provenance.has_declaring_operation(conn, VERSION), expected)
                self.assertFalse(provenance.has_declaring_operation(conn, OTHER), "lo de otra versión no cuenta")
        for status, superseded in (("failed", None), ("running", None), ("done", "op-2")):
            with self.subTest(estado=status, sustituida=superseded):
                conn = database(("op-1", provenance.BUTTRESS, status, superseded))
                self.addCleanup(conn.close)
                self.assertFalse(provenance.has_declaring_operation(conn, VERSION))

    def test_it_is_a_single_query(self) -> None:
        """RF-015-29: el gancho se pregunta con cada ``mask_state``, también al dibujar: la comprobación es **una consulta** (sin cargar las
        entidades)."""
        conn = database(("op-1", provenance.BUTTRESS, "done", None))
        self.addCleanup(conn.close)
        seen: list[str] = []
        conn.set_trace_callback(seen.append)
        self.assertTrue(provenance.has_declaring_operation(conn, VERSION))
        self.assertEqual(len(seen), 1)
        self.assertIn("op_type IN", seen[0])


if __name__ == "__main__":
    unittest.main()

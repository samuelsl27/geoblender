# SPDX-License-Identifier: GPL-3.0-or-later
"""Vectores de referencia del normalizador ``gbch/1`` (spec 008, T05 y T06; RF-008-08;
ADR-0024 §6, «Cómo se verifica»): ``tests/data/core/content/golden_gbch1.json``.

Una versión publicada del normalizador no cambia nunca: estos vectores fijan su salida para
cada tipo de dato, y cualquier cambio de forma los rompe (es un normalizador nuevo).
"""

import unittest

from tests.support import content_golden
from tests.support.package import import_geoblender

content = import_geoblender("core.content")


class GoldenTest(unittest.TestCase):
    """RF-008-08; ADR-0024 §6: los vectores de referencia de ``gbch/1`` (rejillas float32 y
    float64 con NaN de otras cargas, −0,0, infinitos, enteros, booleanos, CRS del fichero o
    ``null`` y sin dato NaN; documentos; compuestos; capas con geometrías nulas y vacías,
    atributos nulos, CRS de la capa o ``null``, curvas y M; tablas con y sin orden; mallas con
    claves de ``meta`` que no son contenido; nubes de puntos con y sin orden) dan exactamente su
    hash, y cubren todos los métodos de ``ContentHasher``."""

    def test_vectors(self) -> None:
        document = content_golden.load()
        self.assertEqual(document["normalizer"], content.NORMALIZER)
        by_id = content_golden.index(document)
        methods = set()
        for case in document["cases"]:
            with self.subTest(case=case["id"]):
                digest = content_golden.build(case, by_id)
                self.assertEqual(digest.data_sha256, case["data_sha256"])
                self.assertEqual(digest.content_sha256, case["content_sha256"])
                self.assertEqual(digest.reader, case["reader"])
                self.assertEqual(digest.normalizer, "gbch/1")
                methods.add(content_golden.method_of(case))
        self.assertEqual(methods, set(content_golden.METHODS))

    def test_same_data_written_otherwise(self) -> None:
        """RF-008-08: el mismo dato escrito de otra forma (WKB *big endian* o extendido, otro
        orden de las entidades o de las filas sin orden, float32) tiene el mismo hash de datos
        guardado; y el de contenido, si su tipo y sus declaraciones son los mismos."""
        by_id = content_golden.index(content_golden.load())
        pairs = [(case, by_id[case["same_data_as"]]) for case in by_id.values()
                 if "same_data_as" in case]
        self.assertGreaterEqual(len(pairs), 3)
        for case, other in pairs:
            with self.subTest(case=case["id"], same_as=other["id"]):
                self.assertEqual(case["data_sha256"], other["data_sha256"])
                if (case["kind"], case["declarations"]) == (other["kind"], other["declarations"]):
                    self.assertEqual(case["content_sha256"], other["content_sha256"])


if __name__ == "__main__":
    unittest.main()

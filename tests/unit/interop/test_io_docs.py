# SPDX-License-Identifier: GPL-3.0-or-later
"""Los importadores de sondeos frente a su documentación (spec 005, T35; plan 005 §5.6.2).

Como la topografía (``tests/unit/gis/test_gis_docs.py``), el código manda y la documentación lo
describe: ``docs/arquitectura/modulos/io.md`` nombra en su API lo que existe de ``interop`` y
cada módulo del paquete (también los de ``interop.recmin``), y cada lector de contenido de los
sondeos con su versión; (T59) y la orden que abre «Importar un fichero…» (``bl/ops/io.py``) con
cada extensión. Esta prueba avisa de que se separan.

Sin la carpeta de la documentación, se omite (recurso ``docs``).
"""

from __future__ import annotations

import pkgutil
import re
import unittest

from tests.support import docs, io_routes
from tests.support.bs_tables import backticked, section, tables
from tests.support.package import import_geoblender

interop = import_geoblender("interop")
recmin = import_geoblender("interop.recmin")
dh_content = import_geoblender("interop.dh_content")

IO_RELPATH = "docs/arquitectura/modulos/io.md"
IO_NAME = re.compile(r"^interop(?:\.[A-Za-z_]\w*)+$")
IMPORT_FILE_HEADING = "## «Importar un fichero…»"


def resolves(dotted: str) -> bool:
    """``interop.<módulo>[.<nombre>…]`` existe en el código."""
    parts = dotted.split(".")
    for cut in range(len(parts), 0, -1):
        try:
            obj = import_geoblender(".".join(parts[:cut]))
        except ModuleNotFoundError:
            continue
        for name in parts[cut:]:
            if not hasattr(obj, name):
                return False
            obj = getattr(obj, name)
        return True
    return False


@docs.requires_docs
class IoModuleDocTest(unittest.TestCase):
    """``modulos/io.md`` nombra la API y los lectores de contenido que existen."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = docs.read(IO_RELPATH)

    def test_named_api_exists(self) -> None:
        """RF-005-03, RF-005-05, RF-005-06, RF-005-13, RF-005-14 (plan 005 §5.3.2 y §5.6.2): todo
        lo que la API de la ficha nombra de ``interop`` existe, y la nombra cada módulo del
        paquete y de ``interop.recmin``."""
        api = section(self.text, "## API pública")
        named = {token for token in backticked(api) if IO_NAME.match(token)}
        self.assertGreater(len(named), 25)
        self.assertEqual(sorted(name for name in named if not resolves(name)), [])
        for package in (interop, recmin):
            prefix = package.__name__.partition(".")[2]
            for info in pkgutil.iter_modules(package.__path__):
                module = f"{prefix}.{info.name}"
                with self.subTest(module=module):
                    self.assertTrue(any(name == module or name.startswith(f"{module}.")
                                        for name in named))

    def test_content_readers(self) -> None:
        """RF-005-12 (plan 005 §5.6.2, D-16; ADR-0024): la ficha nombra cada lector de contenido
        de los sondeos con su versión."""
        readers = set(backticked(section(self.text, "## Lectores de contenido")))
        for reader in dh_content.CONTENT_READERS:
            with self.subTest(reader=reader.id):
                self.assertIn(reader.id, readers)

    def test_import_a_file_by_extension(self) -> None:
        """RF-006-27, RF-005-05, RF-005-13 (T59; F-4 de la verificación de la 005: la guía y el
        CHANGELOG decían que un ``.csv`` abría el asistente de los sondeos): la tabla de
        «Importar un fichero…» de la ficha da, para cada extensión que se importa, la orden que
        abre ``bl/ops/io.py`` (las dos de ``.xyz``, en su orden: su contenido decide), y
        ninguna otra extensión (``tests.support.io_routes``)."""
        (rows,) = tables(section(self.text, IMPORT_FILE_HEADING))
        documented: dict[str, tuple[str, ...]] = {}
        for extensions, opens, *_rest in rows:
            commands = tuple(token for token in backticked(opens)
                             if token.startswith("geoblender."))
            for extension in backticked(extensions):
                with self.subTest(extension=extension):
                    self.assertNotIn(extension, documented)
                documented[extension] = commands
        self.assertEqual(documented, io_routes.import_routes())


if __name__ == "__main__":
    unittest.main()

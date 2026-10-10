# SPDX-License-Identifier: GPL-3.0-or-later
"""El ``README.md`` del código documenta cada variable de entorno que lee la extensión
(spec 008, T61).

La tabla «Variables de entorno» del README es lo que lee quien instala Geoblender en un equipo
de IMGA. Una variable que la extensión lee y que no está en esa tabla no la define nadie: la de
las carpetas de solo lectura (``GEOBLENDER_READ_ONLY_DIRS``, RF-008-15 y la decisión S-3 del
plan 008) dejaría sin proteger los expedientes de clientes sin que nadie lo supiera.

Una variable de la extensión es una cadena del código de ``geoblender/`` que es entera un
nombre ``GEOBLENDER_*`` en mayúsculas, como la que se pasa a ``os.environ.get``; los prefijos
de las clases (``"GEOBLENDER_PT_"``) terminan en «_» y no cuentan. Una variable documentada es
la de la primera columna de una fila de la tabla. Las de las herramientas y las pruebas no se
comprueban aquí: están en la misma tabla, pero no las define quien usa Geoblender.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.support.repo import EXT, ROOT
from tests.support.trees import temp_tree

README = "README.md"
SECTION = "## Variables de entorno"
# Una cadena de Python que es entera el nombre de una variable (no un prefijo de clase).
_LITERAL = re.compile(r"""["'](GEOBLENDER_[A-Z0-9_]*[A-Z0-9])["']""")
# La primera columna de una fila de la tabla: | `GEOBLENDER_X` | …
_ROW = re.compile(r"^\|\s*`(GEOBLENDER_[A-Z0-9_]+)`\s*\|")


def extension_variables(root: Path) -> set[str]:
    """Las variables ``GEOBLENDER_*`` que nombra como cadena el código de la extensión."""
    found: set[str] = set()
    for path in (root / EXT).rglob("*.py"):
        found.update(_LITERAL.findall(path.read_text(encoding="utf-8")))
    return found


def readme_variables(root: Path) -> set[str]:
    """Las variables de la primera columna de la tabla «Variables de entorno» del README
    (hasta la sección siguiente)."""
    text = (root / README).read_text(encoding="utf-8")
    start = text.find(SECTION)
    if start < 0:
        return set()
    section = text[start + len(SECTION):]
    end = section.find("\n## ")
    if end >= 0:
        section = section[:end]
    return {match.group(1) for line in section.splitlines() if (match := _ROW.match(line))}


def missing_variables(root: Path) -> list[str]:
    """Las variables de la extensión que no están en la tabla del README, en orden."""
    return sorted(extension_variables(root) - readme_variables(root))


def _readme(*rows: str) -> str:
    table = "".join(f"| `{name}` | Para qué |\n" for name in rows)
    return (f"# Geoblender\n\n{SECTION}\n\n| Variable | Para qué |\n| --- | --- |\n{table}\n"
            "## Licencia\n\n| `GEOBLENDER_OTRA` | fuera de la tabla |\n")


_CODE = (
    "import os\n"
    'VARIABLE = "GEOBLENDER_EJEMPLO_DIRS"\n'
    'PANEL = "GEOBLENDER_PT_"  # un prefijo de clase\n'
    'TEXT = "La variable GEOBLENDER_EJEMPLO_DIRS añade las de la empresa"\n'
    "def folders():\n"
    "    return os.environ.get(VARIABLE)\n"
)


class ReadmeVariablesTest(unittest.TestCase):
    def test_readme_lists_every_variable_of_the_extension(self) -> None:
        """RF-008-15 (S-3; T61): cada variable de entorno que lee la extensión, también
        ``GEOBLENDER_READ_ONLY_DIRS`` (las carpetas de solo lectura de la empresa), tiene su
        fila en la tabla «Variables de entorno» del ``README.md`` del código."""
        self.assertIn("GEOBLENDER_READ_ONLY_DIRS", extension_variables(ROOT))
        self.assertEqual(missing_variables(ROOT), [],
                         "variables de la extensión sin su fila en «Variables de entorno» "
                         "del README.md")

    def test_a_variable_missing_from_the_table_is_reported(self) -> None:
        """RF-008-15 (T61): una variable que lee la extensión y que no está en la primera
        columna de la tabla se señala, aunque el README la cite en otra sección; un prefijo
        de clase y una frase que la menciona no cuentan como variables."""
        files = {f"{EXT}/bl/ops/ejemplo.py": _CODE, README: _readme("GEOBLENDER_DOCS_DIR")}
        with temp_tree(files) as root:
            self.assertEqual(extension_variables(root), {"GEOBLENDER_EJEMPLO_DIRS"})
            self.assertEqual(missing_variables(root), ["GEOBLENDER_EJEMPLO_DIRS"])
        files[README] = _readme("GEOBLENDER_DOCS_DIR", "GEOBLENDER_EJEMPLO_DIRS")
        with temp_tree(files) as root:
            self.assertEqual(missing_variables(root), [])


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: GPL-3.0-or-later
"""ARQ-17: SQLite nunca en WAL (spec 002, T06; RF-002-16; ADR-0006).

El modo WAL de SQLite no funciona en un sistema de ficheros en red, y los proyectos de
IMGA viven en ``Z:``. Ningún literal del código de la extensión pone una BD en WAL. El
texto prohibido se construye al ejecutar la prueba (plan 001 §5.4.1).
"""

import unittest

from tests.support.repo import EXT, ROOT, tools_on_path
from tests.support.trees import temp_tree

tools_on_path()

from gbtools.findings import format_findings  # noqa: E402
from gbtools.rules import FAMILIES, sqlite  # noqa: E402

SPDX = "# SPDX-License-Identifier: GPL-3.0-or-later\n"
HEAD = '"""Módulo de prueba."""\n\n'
OFFSET = (SPDX + HEAD).count("\n")
WAL = "W" + "AL"


def _found(files: dict[str, str]) -> list[tuple[str, int, str]]:
    tree = {f"{EXT}/{rel}": SPDX + HEAD + text for rel, text in files.items()}
    with temp_tree(tree) as root:
        findings = sqlite.check(root)
    return [(f.path.removeprefix(f"{EXT}/"), f.line - OFFSET, f.rule) for f in findings]


class NoWalTest(unittest.TestCase):
    def test_wal_literal_fails(self) -> None:
        """RF-002-16 / ARQ-17: un literal ``journal_mode=WAL`` (con espacios, comillas,
        minúsculas o dentro de una f-string) falla, en ``core`` y en cualquier otro
        paquete de la extensión."""
        text = (
            f'conn.execute("PRAGMA journal_mode={WAL}")\n'
            f"conn.execute('pragma JOURNAL_MODE = {WAL.lower()};')\n"
            f'sql = "PRAGMA main.journal_mode = \'{WAL}\'"\n'
            f'conn.execute(f"PRAGMA {{schema}}.journal_mode={WAL}")\n'
        )
        found = _found({"core/gpkg/db.py": text, "gis/x.py": f'Q = "journal_mode={WAL}"\n'})
        self.assertEqual(
            found,
            [
                ("core/gpkg/db.py", 1, "ARQ-17"),
                ("core/gpkg/db.py", 2, "ARQ-17"),
                ("core/gpkg/db.py", 3, "ARQ-17"),
                ("core/gpkg/db.py", 4, "ARQ-17"),
                ("gis/x.py", 1, "ARQ-17"),
            ],
        )

    def test_allowed(self) -> None:
        """RF-002-16 / ARQ-17: el diario clásico, leer el modo, la palabra suelta (una
        cabecera que dice «wal») y los docstrings no fallan."""
        text = (
            'conn.execute("PRAGMA journal_mode = DELETE")\n'
            'mode = conn.execute("PRAGMA journal_mode").fetchone()[0]\n'
            f'journal = "{WAL.lower()}"\n'
            f'def f():\n    """Nunca journal_mode={WAL} (ARQ-17)."""\n'
        )
        self.assertEqual(_found({"core/gpkg/db.py": text}), [])

    def test_real_tree_and_family(self) -> None:
        """RF-002-16 / ARQ-17: el repositorio real cumple y la regla está en
        ``FAMILIES``."""
        findings = sqlite.check(ROOT)
        self.assertEqual(findings, [], "\n" + format_findings(findings))
        self.assertIs(FAMILIES["sqlite"], sqlite.check)


if __name__ == "__main__":
    unittest.main()

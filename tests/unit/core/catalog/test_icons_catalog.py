# SPDX-License-Identifier: GPL-3.0-or-later
"""Los iconos propios del catálogo (spec 003, T31; RF-003-22; II §1.3 y §1.4).

Sin la documentación: ``icons.toml`` tiene los 58 iconos de II §1.4 (1 logotipo, 12 de menú,
4 de rama, 17 de acceso rápido, 7 de estado, 13 de tipo de entidad y 4 de tipo de cifra),
cada uno con su reserva nativa o, si no tiene (el logotipo y los tipos de cifra), su texto;
todo icono propio que nombra un comando está en él; y una fuente ``assets/icons/<nombre>.svg``
por icono, ni una más.

Con la documentación (recurso ``docs``), además, los nombres y las reservas son los de las
tablas de II §1.4.
"""

import re
import unittest
from collections import Counter

from tests.support import docs
from tests.support.package import import_geoblender
from tests.support.repo import ROOT

catalog = import_geoblender("core.catalog")

II_RELPATH = "docs/arquitectura/interfaz/iconos-e-idioma.md"
GROUPS = {"logo": 1, "menu": 12, "branch": 4, "qat": 17, "state": 7, "kind": 13, "type": 4}
TEXT_FALLBACKS = {"gb_logo": "GB", "gb_type_measured": "[MED]", "gb_type_calculated": "[CAL]",
                  "gb_type_adopted": "[ADO]", "gb_type_assumption": "[HIP]"}
_ROW = re.compile(r"^\| `(gb_[a-z0-9_]+)` \|.*\| ([^|]+) \|\s*$", re.MULTILINE)


def documented_icons(text: str) -> dict[str, tuple[str, str]]:
    """nombre → (reserva nativa o ``NONE``, reserva de texto) de las tablas de II §1.4."""
    section = text[text.index("### 1.4"):text.index("### 1.5")]
    found: dict[str, tuple[str, str]] = {}
    for name, reserve in _ROW.findall(section):
        native = re.search(r"`([A-Z][A-Z0-9_]*)`", reserve)
        quoted = re.search(r"«([^»]+)»", reserve)
        found[name] = (native.group(1) if native else "NONE",
                       quoted.group(1) if quoted and not native else "")
    return found


class IconsCatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cat = catalog.load()

    def test_58_icons_by_group(self) -> None:
        """II §1.4: 58 iconos por grupos; reserva nativa o, si no hay, de texto."""
        groups = Counter(name.split("_")[1] for name in self.cat.icons)
        self.assertEqual(dict(groups), GROUPS)
        self.assertEqual(len(self.cat.icons), 58)
        for name, spec in self.cat.icons.items():
            with self.subTest(icon=name):
                self.assertEqual(spec.fallback_text, TEXT_FALLBACKS.get(name, ""))
                if name in TEXT_FALLBACKS or name.startswith("gb_branch_"):
                    self.assertEqual(spec.fallback, "NONE")
                else:
                    self.assertNotEqual(spec.fallback, "NONE")

    def test_command_icons_in_catalog(self) -> None:
        """II §1.3: todo icono propio de un comando está en ``icons.toml`` y tiene la misma
        reserva que el comando, si este la da."""
        used = {cmd.icon: cmd for cmd in self.cat.commands.values() if cmd.icon}
        self.assertGreaterEqual(len(used), 30)
        for name, cmd in used.items():
            with self.subTest(icon=name):
                self.assertIn(name, self.cat.icons)
        self.assertEqual(catalog.validate(self.cat), [])

    def test_one_source_per_icon(self) -> None:
        """II §1.6: una fuente SVG por icono del catálogo, ni una más."""
        sources = {path.stem for path in (ROOT / "assets" / "icons").glob("*.svg")}
        self.assertEqual(sources, set(self.cat.icons))

    @docs.requires_docs
    def test_matches_ii(self) -> None:
        """II §1.4: los mismos nombres y reservas que las tablas."""
        expected = documented_icons(docs.read(II_RELPATH))
        self.assertEqual(len(expected), 58)
        actual = {name: (spec.fallback, spec.fallback_text)
                  for name, spec in self.cat.icons.items()}
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()

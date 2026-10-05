# SPDX-License-Identifier: GPL-3.0-or-later
"""ARQ-12: cabecera SPDX en cada ``.py`` del repositorio comprobado (RF-001-18)."""

import unittest

from tests.support.repo import EXT, ROOT, tools_on_path
from tests.support.trees import temp_tree

tools_on_path()

from gbtools.findings import format_findings  # noqa: E402
from gbtools.rules import headers  # noqa: E402

HEADER = "# SPDX-License-Identifier: GPL-3.0-or-later\n"


def _found(files: dict[str, str | bytes]) -> list[tuple[str, int, str]]:
    with temp_tree(files) as root:
        return [(f.path, f.line, f.rule) for f in headers.check(root)]


class SpdxHeaderTest(unittest.TestCase):
    def test_missing_header(self) -> None:
        """RF-001-18 / ARQ-12: un ``.py`` sin cabecera (también vacío) se detecta."""
        found = _found(
            {
                "tools/sin_cabecera.py": "import os\n",
                f"{EXT}/core/__init__.py": "",
                "tests/unit/test_bien.py": HEADER + "import os\n",
                "docs/nota.md": "sin cabecera, pero no es Python\n",
            }
        )
        self.assertEqual(
            found,
            [
                (f"{EXT}/core/__init__.py", 1, "ARQ-12"),
                ("tools/sin_cabecera.py", 1, "ARQ-12"),
            ],
        )

    def test_shebang_then_header(self) -> None:
        """RF-001-18 / ARQ-12: tras un ``#!``, la cabecera va en la segunda línea."""
        found = _found(
            {
                "tools/bien.py": "#!/usr/bin/env python\n" + HEADER + "import os\n",
                "tools/mal.py": "#!/usr/bin/env python\nimport os\n" + HEADER,
                "tools/solo.py": "#!/usr/bin/env python\n",
            }
        )
        self.assertEqual(
            found, [("tools/mal.py", 2, "ARQ-12"), ("tools/solo.py", 2, "ARQ-12")]
        )

    def test_header_on_third_line(self) -> None:
        """RF-001-18 / ARQ-12: en la tercera línea no vale, y se dice dónde está."""
        late = "# -*- coding: utf-8 -*-\n\n" + HEADER
        with temp_tree({"tools/tarde.py": late}) as root:
            findings = headers.check(root)
        found = [(f.path, f.line, f.rule) for f in findings]
        self.assertEqual(found, [("tools/tarde.py", 1, "ARQ-12")])
        self.assertIn("línea 3", findings[0].message)

    def test_header_must_be_exact(self) -> None:
        """RF-001-18 / ARQ-12: otra licencia o espacios de más no valen."""
        found = _found(
            {
                "a.py": "# SPDX-License-Identifier: MIT\n",
                "b.py": "# SPDX-License-Identifier: GPL-3.0-or-later \n",
                "c.py": "#SPDX-License-Identifier: GPL-3.0-or-later\n",
            }
        )
        self.assertEqual([path for path, _, _ in found], ["a.py", "b.py", "c.py"])

    def test_bom_is_reported_by_txt01_not_here(self) -> None:
        """RF-001-18 / ARQ-12: un BOM delante de la cabecera es asunto de TXT-01."""
        self.assertEqual(_found({"a.py": b"\xef\xbb\xbf" + HEADER.encode()}), [])

    def test_ignored_files_not_checked(self) -> None:
        """RF-001-18 / ARQ-12: lo excluido (``.gitignore``, Documentacion/) no cuenta."""
        found = _found(
            {
                ".gitignore": "build/\n",
                "build/generado.py": "x = 1\n",
                "Documentacion/prototipo.py": "x = 1\n",
                "Promts/ejemplo.py": "x = 1\n",
            }
        )
        self.assertEqual(found, [])

    def test_real_tree(self) -> None:
        """RF-001-18 / ARQ-12: todos los ``.py`` del repositorio llevan la cabecera."""
        findings = headers.check(ROOT)
        self.assertEqual(findings, [], "\n" + format_findings(findings))


if __name__ == "__main__":
    unittest.main()

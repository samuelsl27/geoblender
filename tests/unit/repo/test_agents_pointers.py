# SPDX-License-Identifier: GPL-3.0-or-later
"""AGT-01 y AGT-02: punteros ``CLAUDE.md`` y tamaño de los ``AGENTS.md`` (RF-001-21)."""

import unittest

from tests.support.repo import EXT, ROOT, tools_on_path
from tests.support.trees import temp_tree

tools_on_path()

from gbtools.findings import format_findings  # noqa: E402
from gbtools.rules import agents  # noqa: E402

POINTER = "@AGENTS.md\n"


def _found(files: dict[str, str | bytes]) -> list[tuple[str, str]]:
    with temp_tree(files) as root:
        return [(f.path, f.rule) for f in agents.check(root)]


def _lines(count: int, width: int = 10) -> str:
    return "".join(f"{i:0{width}d}\n" for i in range(count))


class PointerTest(unittest.TestCase):
    def test_missing_claude(self) -> None:
        """RF-001-21 / AGT-01: un ``AGENTS.md`` sin ``CLAUDE.md`` al lado falla."""
        found = _found(
            {
                "AGENTS.md": "# Reglas\n",
                f"{EXT}/AGENTS.md": "# Reglas del código\n",
                f"{EXT}/CLAUDE.md": POINTER,
                "tools/AGENTS.md": "# Reglas de las herramientas\n",
            }
        )
        expected = [("AGENTS.md", "AGT-01"), ("tools/AGENTS.md", "AGT-01")]
        self.assertEqual(found, expected)

    def test_claude_with_rules(self) -> None:
        """RF-001-21 / AGT-01: un ``CLAUDE.md`` con más que ``@AGENTS.md`` falla."""
        found = _found(
            {
                "AGENTS.md": "# Reglas\n",
                "CLAUDE.md": POINTER + "No empaquetes numpy.\n",
                "a/AGENTS.md": "# A\n",
                "a/CLAUDE.md": "Lee AGENTS.md antes de empezar.\n",
                "b/AGENTS.md": "# B\n",
                "b/CLAUDE.md": "@AGENTS.md",
                "c/AGENTS.md": "# C\n",
                "c/CLAUDE.md": POINTER,
            }
        )
        self.assertEqual(found, [("CLAUDE.md", "AGT-01"), ("a/CLAUDE.md", "AGT-01")])

    def test_orphan_claude(self) -> None:
        """RF-001-21 / AGT-01: un ``CLAUDE.md`` sin su ``AGENTS.md`` falla."""
        found = _found(
            {
                "AGENTS.md": "# Reglas\n",
                "CLAUDE.md": POINTER,
                "docs/CLAUDE.md": POINTER,
            }
        )
        self.assertEqual(found, [("docs/CLAUDE.md", "AGT-01")])


class SizeTest(unittest.TestCase):
    def test_root_too_long(self) -> None:
        """RF-001-21 / AGT-02: el ``AGENTS.md`` raíz, con más de 200 líneas o 16 KiB."""
        self.assertEqual(_found({"AGENTS.md": _lines(200), "CLAUDE.md": POINTER}), [])
        too_many = _found({"AGENTS.md": _lines(201), "CLAUDE.md": POINTER})
        self.assertEqual(too_many, [("AGENTS.md", "AGT-02")])
        self.assertEqual(
            _found({"AGENTS.md": _lines(16, 1023), "CLAUDE.md": POINTER}), []
        )
        too_big = _found({"AGENTS.md": _lines(17, 1023), "CLAUDE.md": POINTER})
        self.assertEqual(too_big, [("AGENTS.md", "AGT-02")])
        with temp_tree({"AGENTS.md": _lines(201), "CLAUDE.md": POINTER}) as root:
            message = agents.check(root)[0].message
        self.assertIn("201", message)
        self.assertIn("docs/trampas.md", message)

    def test_nested_too_long(self) -> None:
        """RF-001-21 / AGT-02: un ``AGENTS.md`` anidado, con más de 120 líneas."""
        ok = {f"{EXT}/AGENTS.md": _lines(120), f"{EXT}/CLAUDE.md": POINTER}
        self.assertEqual(_found(ok), [])
        long = {f"{EXT}/AGENTS.md": _lines(121), f"{EXT}/CLAUDE.md": POINTER}
        self.assertEqual(_found(long), [(f"{EXT}/AGENTS.md", "AGT-02")])
        no_final_newline = {
            f"{EXT}/AGENTS.md": _lines(120) + "121",
            f"{EXT}/CLAUDE.md": POINTER,
        }
        self.assertEqual(_found(no_final_newline), [(f"{EXT}/AGENTS.md", "AGT-02")])


class RealTreeTest(unittest.TestCase):
    def test_real_tree(self) -> None:
        """RF-001-21 / AGT-01 y AGT-02: los ``AGENTS.md`` del repositorio cumplen."""
        self.assertTrue((ROOT / "AGENTS.md").is_file())
        self.assertTrue((ROOT / EXT / "AGENTS.md").is_file())
        findings = agents.check(ROOT)
        self.assertEqual(findings, [], "\n" + format_findings(findings))


if __name__ == "__main__":
    unittest.main()

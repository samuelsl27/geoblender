# SPDX-License-Identifier: GPL-3.0-or-later
"""AGT-01 y AGT-02: punteros ``CLAUDE.md`` y tamaño de los ``AGENTS.md`` (RF-001-21);
AGT-03: el ``AGENTS.md`` mínimo del repositorio de código (spec 007, RF-007-05)."""

import re
import unittest

from tests.support.repo import EXT, ROOT, tools_on_path
from tests.support.trees import temp_tree

tools_on_path()

from gbtools.findings import Finding, format_findings  # noqa: E402
from gbtools.layout import CODE_AGENTS_MAX_LINES, ENV_DOCS_DIR  # noqa: E402
from gbtools.rules import DOCS_FAMILIES, FAMILIES, agents  # noqa: E402

POINTER = "@AGENTS.md\n"
DOCS_VARIABLE_LINE = f"La documentación: la carpeta madre o la de {ENV_DOCS_DIR}.\n"
# Una ruta de la documentación en un mensaje dice que es de la documentación (el código no
# tiene docs/: spec 007, T16).
_DOCS_PATH = re.compile(r"docs/\S+")


def _found(files: dict[str, str | bytes]) -> list[tuple[str, str]]:
    with temp_tree(files) as root:
        return [(f.path, f.rule) for f in agents.check(root)]


def _code(files: dict[str, str | bytes]) -> list[Finding]:
    """Los incumplimientos de la familia del código (AGT-01, AGT-02 y AGT-03)."""
    with temp_tree(files) as root:
        return FAMILIES["agents"](root)


def _lines(count: int, width: int = 10) -> str:
    return "".join(f"{i:0{width}d}\n" for i in range(count))


def _docs_paths_qualified(test: unittest.TestCase, message: str) -> None:
    """Cada ruta ``docs/…`` del mensaje va seguida de «de la documentación»."""
    for match in _DOCS_PATH.finditer(message):
        test.assertTrue(
            message[match.end() :].startswith(" de la documentación"), message
        )


class PointerTest(unittest.TestCase):
    def test_missing_claude(self) -> None:
        """RF-001-21 / AGT-01: un ``AGENTS.md`` sin ``CLAUDE.md`` al lado falla; el
        mensaje cita las trampas de la documentación, no una ruta del código
        (RF-007-05)."""
        files = {
            "AGENTS.md": "# Reglas\n",
            f"{EXT}/AGENTS.md": "# Reglas del código\n",
            f"{EXT}/CLAUDE.md": POINTER,
            "tools/AGENTS.md": "# Reglas de las herramientas\n",
        }
        found = _found(files)
        expected = [("AGENTS.md", "AGT-01"), ("tools/AGENTS.md", "AGT-01")]
        self.assertEqual(found, expected)
        with temp_tree(files) as root:
            message = agents.check(root)[0].message
        self.assertIn("docs/trampas.md de la documentación", message)
        _docs_paths_qualified(self, message)

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
        self.assertIn("docs/trampas.md de la documentación", message)
        _docs_paths_qualified(self, message)

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


class CodeAgentsTest(unittest.TestCase):
    def test_root_agents_without_docs_variable(self) -> None:
        """RF-007-05 / AGT-03: el ``AGENTS.md`` raíz del código que no nombra
        ``GEOBLENDER_DOCS_DIR`` (tal cual), o que falta, falla; uno anidado no la
        necesita."""
        ok = {"AGENTS.md": "# Reglas\n" + DOCS_VARIABLE_LINE, "CLAUDE.md": POINTER}
        self.assertEqual(_code(ok), [])
        nested = ok | {
            f"{EXT}/AGENTS.md": "# Reglas de la extensión\n",
            f"{EXT}/CLAUDE.md": POINTER,
        }
        self.assertEqual(_code(nested), [])
        without = "# Reglas\nLa documentación: la carpeta madre.\n"
        for text in (without, DOCS_VARIABLE_LINE.lower()):
            with self.subTest(texto=text):
                findings = _code({"AGENTS.md": text, "CLAUDE.md": POINTER})
                self.assertEqual(
                    [(f.path, f.rule) for f in findings],
                    [("AGENTS.md", "AGT-03")],
                    format_findings(findings),
                )
                self.assertIn(ENV_DOCS_DIR, findings[0].message)
        missing = _code({"README.md": "x\n"})
        self.assertEqual([(f.path, f.rule) for f in missing], [("AGENTS.md", "AGT-03")])
        self.assertIn("falta", missing[0].message)

    def test_root_agents_too_long(self) -> None:
        """RF-007-05 / AGT-03: el ``AGENTS.md`` raíz del código, con más de 60 líneas,
        falla (el de la documentación admite 200: AGT-03 no es de la documentación)."""
        self.assertEqual(CODE_AGENTS_MAX_LINES, 60)
        limit = _lines(CODE_AGENTS_MAX_LINES - 1) + DOCS_VARIABLE_LINE
        self.assertEqual(_code({"AGENTS.md": limit, "CLAUDE.md": POINTER}), [])
        findings = _code({"AGENTS.md": _lines(1) + limit, "CLAUDE.md": POINTER})
        self.assertEqual(
            [(f.path, f.rule) for f in findings],
            [("AGENTS.md", "AGT-03")],
            format_findings(findings),
        )
        self.assertIn("61", findings[0].message)
        self.assertIn("60", findings[0].message)
        docs = {
            "docs/constitution.md": "x\n",
            "AGENTS.md": _lines(CODE_AGENTS_MAX_LINES + 1),
            "CLAUDE.md": POINTER,
        }
        with temp_tree(docs) as root:
            self.assertEqual(DOCS_FAMILIES["agents"](root), [])

    def test_in_families(self) -> None:
        """RF-007-05: la familia ``agents`` del código lleva AGT-03; la de la
        documentación, solo AGT-01 y AGT-02."""
        self.assertIs(FAMILIES["agents"], agents.check_code)


class RealTreeTest(unittest.TestCase):
    def test_real_tree(self) -> None:
        """RF-001-21 / AGT-01 y AGT-02, RF-007-05 / AGT-03: los ``AGENTS.md`` del
        repositorio cumplen, y el raíz es el mínimo del código."""
        self.assertTrue((ROOT / "AGENTS.md").is_file())
        self.assertTrue((ROOT / EXT / "AGENTS.md").is_file())
        findings = FAMILIES["agents"](ROOT)
        self.assertEqual(findings, [], "\n" + format_findings(findings))


if __name__ == "__main__":
    unittest.main()

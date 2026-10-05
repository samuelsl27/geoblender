# SPDX-License-Identifier: GPL-3.0-or-later
"""REP: el árbol de la raíz del repositorio de código (spec 007; RF-007-01, RF-007-08)."""

import unittest

from tests.support.repo import EXT, ROOT, tools_on_path
from tests.support.trees import temp_tree

tools_on_path()

from gbtools.findings import Finding, format_findings  # noqa: E402
from gbtools.layout import CODE_ROOT_ENTRIES  # noqa: E402
from gbtools.rules import FAMILIES  # noqa: E402
from gbtools.rules import layout as layout_rules  # noqa: E402

SPDX = "# SPDX-License-Identifier: GPL-3.0-or-later\n"
# La carpeta de la extensión con otra mayúscula (el mismo nombre para Windows).
OTHER_CASE = EXT.lower() if EXT != EXT.lower() else EXT.capitalize()
REP01 = "REP-01"


def _extension(
    folder: str = EXT, *, manifest: bool = True, py: bool = True
) -> dict[str, str]:
    """Una extensión mínima en ``folder``: el manifiesto y un ``__init__.py``."""
    files = {"tools/check.py": SPDX}
    if manifest:
        files[f"{folder}/blender_manifest.toml"] = 'schema_version = "1.0.0"\n'
    if py:
        files[f"{folder}/core/__init__.py"] = SPDX
    if not manifest and not py:
        files[f"{folder}/LEEME.md"] = "x\n"
    return files


def _found(files: dict[str, str]) -> list[Finding]:
    with temp_tree(files) as root:
        return layout_rules.check(root)


def _rep01(files: dict[str, str]) -> list[Finding]:
    """Los incumplimientos de REP-01 de un árbol con una extensión válida y ``files``."""
    return [f for f in _found(_extension() | files) if f.rule == REP01]


class RootEntriesTest(unittest.TestCase):
    def test_docs_folder_fails(self) -> None:
        """RF-007-01 / REP-01: una entrada de la raíz que no es del repositorio de código
        (``docs/``, ``specs/``, la documentación, un *worktree* en ``.claude/``, un
        fichero suelto, una permitida con otra mayúscula) falla nombrándola, una vez por
        entrada."""
        files = {
            "docs/constitution.md": "x\n",
            "docs/adr/README.md": "x\n",
            "specs/README.md": "x\n",
            "Documentacion/informe.md": "x\n",
            "Promts/encargo.md": "x\n",
            ".claude/worktrees/rama/README.md": "x\n",
            "notas.txt": "x\n",
            "Tests/unit/test_a.py": SPDX,
        }
        findings = _rep01(files)
        entries = [".claude", "Documentacion", "Promts", "Tests", "docs", "notas.txt", "specs"]
        self.assertEqual(
            [(f.path, f.line) for f in findings],
            [(entry, 0) for entry in entries],
            format_findings(findings),
        )
        for finding, entry in zip(findings, entries, strict=True):
            self.assertIn(f"«{entry}»", finding.message)
        self.assertNotIn("Tests", CODE_ROOT_ENTRIES)
        self.assertIn("tests", CODE_ROOT_ENTRIES)

    def test_allowed_entries_ok(self) -> None:
        """RF-007-01 / REP-01: las entradas permitidas, con su mayúscula exacta, no dan
        ningún incumplimiento."""
        files = {
            "tests/unit/test_a.py": SPDX,
            "assets/LICENSE": "x\n",
            "packaging/app_template/__init__.py": SPDX,
            "LICENSE": "x\n",
            "LICENSES/GPL-3.0-or-later.txt": "x\n",
            "REUSE.toml": "version = 1\n",
            "README.md": "x\n",
            "CHANGELOG.md": "x\n",
            "AGENTS.md": "x\n",
            "CLAUDE.md": "@AGENTS.md\n",
            ".gitattributes": "* text=auto eol=lf\n",
            ".gitignore": "dist/\n",
            ".editorconfig": "root = true\n",
        }
        tops = {rel.split("/", 1)[0] for rel in (*files, *_extension())}
        self.assertEqual(tops, set(CODE_ROOT_ENTRIES))
        self.assertEqual(_rep01(files), [])

    def test_ignored_not_counted(self) -> None:
        """RF-007-01 / REP-01: lo que ignora el ``.gitignore`` (``dist/``, ``.deps/``, la
        configuración local de los agentes) y ``.git/`` no cuentan: no son entradas
        versionadas."""
        files = {
            ".gitignore": "dist/\n.deps/\n.claude/settings.local.json\nCLAUDE.local.md\n",
            "dist/geoblender-0.1.0.zip": "PK",
            ".deps/site/a.py": SPDX,
            ".claude/settings.local.json": "{}\n",
            "CLAUDE.local.md": "x\n",
            ".git/config": "[core]\n",
        }
        self.assertEqual(_rep01(files), [])
        self.assertEqual([f.rule for f in _rep01({".claude/settings.json": "{}\n"})], [REP01])


class ExtensionDirTest(unittest.TestCase):
    def assertOnlyRep02(self, findings: list[Finding], *mentions: str) -> None:
        # La extensión con otra mayúscula es también una entrada que REP-01 no admite.
        findings = [f for f in findings if f.rule != REP01]
        self.assertEqual(
            [(f.path, f.rule) for f in findings],
            [(EXT, "REP-02")],
            format_findings(findings),
        )
        for text in (f"«{EXT}»", *mentions):
            self.assertIn(text, findings[0].message)

    def test_extension_ok(self) -> None:
        """RF-007-08 / REP-02: la carpeta con su nombre exacto, el manifiesto y un ``.py``
        (en cualquier nivel) cumple."""
        self.assertEqual(_found(_extension()), [])

    def test_wrong_case_fails(self) -> None:
        """RF-007-08 / REP-02: la carpeta con otra mayúscula falla nombrando la esperada
        y la que hay, aunque Windows abra sus ficheros con cualquiera de las dos."""
        self.assertNotEqual(OTHER_CASE, EXT)
        self.assertEqual(OTHER_CASE.casefold(), EXT.casefold())
        self.assertOnlyRep02(_found(_extension(OTHER_CASE)), f"«{OTHER_CASE}»")

    def test_missing_extension_fails(self) -> None:
        """RF-007-08 / REP-02: sin la carpeta de la extensión, o si es un fichero, falla
        nombrando la carpeta esperada."""
        self.assertOnlyRep02(_found({"tools/check.py": SPDX}), "falta")
        self.assertOnlyRep02(_found({"tools/check.py": SPDX, EXT: "x\n"}), "carpeta")

    def test_extension_without_py_fails(self) -> None:
        """RF-007-08 / REP-02: una carpeta de la extensión sin ningún ``.py``, o sin el
        manifiesto, falla."""
        self.assertOnlyRep02(_found(_extension(py=False)), ".py")
        self.assertOnlyRep02(_found(_extension(manifest=False)), "blender_manifest.toml")
        findings = _found(_extension(manifest=False, py=False))
        self.assertEqual({f.rule for f in findings}, {"REP-02"})
        self.assertEqual(len(findings), 2, format_findings(findings))

    def test_in_families(self) -> None:
        """RF-007-01, RF-007-08: REP-01 y REP-02 están en ``FAMILIES`` (las ejecuta
        ``run_all``)."""
        self.assertIs(FAMILIES["layout"], layout_rules.check)

    def test_real_tree(self) -> None:
        """RF-007-01 / REP-01, RF-007-08 / REP-02: el repositorio real cumple."""
        findings = layout_rules.check(ROOT)
        self.assertEqual(findings, [], "\n" + format_findings(findings))


if __name__ == "__main__":
    unittest.main()

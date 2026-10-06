# SPDX-License-Identifier: GPL-3.0-or-later
"""Ficheros comprobados y patrones de exclusión (``gbtools.repo``, ``gbtools.ignore``).

Las reglas del repositorio (RF-001-18 a RF-001-21) se aplican a todos los ficheros
salvo ``.git/`` y lo que excluye ``.gitignore`` (spec 001 §4.4). ``Documentacion/`` y
``Promts/`` solo las excluye la documentación (``layout.DOCS_EXCLUDED``; spec 007, T15):
en el repositorio de código no existen, y si aparecen, REP-01 las señala.
"""

import os
import unittest
from pathlib import Path

from tests.support.repo import EXT, ROOT, tools_on_path
from tests.support.trees import age_folders, temp_tree

tools_on_path()

from gbtools import repo as gbrepo  # noqa: E402
from gbtools.findings import Finding, format_findings  # noqa: E402
from gbtools.ignore import IgnoreSpec, UnsupportedPattern  # noqa: E402
from gbtools.layout import DOCS_EXCLUDED, MANIFEST_RELPATH, ROOT_MARKERS  # noqa: E402
from gbtools.repo import (  # noqa: E402
    ALWAYS_EXCLUDED,
    is_text_file,
    iter_py_files,
    iter_repo_files,
    relpath,
    repo_root,
    snapshot,
    snapshot_changes,
)


def _spec(*lines: str) -> IgnoreSpec:
    return IgnoreSpec.from_lines(lines)


def _listed(root: Path) -> list[str]:
    return [relpath(root, p) for p in iter_repo_files(root)]


class IgnoreSpecTest(unittest.TestCase):
    def test_comments_and_blank_lines_ignored(self) -> None:
        """RF-001-19: las líneas vacías y los comentarios no excluyen nada."""
        spec = _spec("", "# __pycache__/", "   ")
        self.assertFalse(spec.matches("__pycache__", True))
        self.assertFalse(spec.matches("# __pycache__", False))

    def test_unanchored_dir_pattern_any_level(self) -> None:
        """RF-001-19: ``__pycache__/`` excluye esa carpeta en cualquier nivel."""
        spec = _spec("__pycache__/")
        self.assertTrue(spec.matches("__pycache__", True))
        self.assertTrue(spec.matches("tools/gbtools/__pycache__", True))
        self.assertTrue(spec.matches("tools/gbtools/__pycache__/repo.pyc", False))

    def test_dir_only_pattern_does_not_match_file(self) -> None:
        """RF-001-19: un patrón con «/» final solo casa con carpetas."""
        spec = _spec("dist/")
        self.assertTrue(spec.matches("dist", True))
        self.assertTrue(spec.matches("sub/dist", True))
        self.assertFalse(spec.matches("dist", False))
        self.assertFalse(spec.matches("sub/dist", False))

    def test_anchored_pattern_only_at_root(self) -> None:
        """RF-001-19: ``/dist/`` solo excluye la carpeta de la raíz."""
        spec = _spec("/dist/")
        self.assertTrue(spec.matches("dist", True))
        self.assertTrue(spec.matches("dist/geoblender-0.1.0.zip", False))
        self.assertFalse(spec.matches("tests/dist", True))
        self.assertFalse(spec.matches("tests/dist/a.zip", False))

    def test_middle_slash_anchors(self) -> None:
        """RF-001-19: un «/» intermedio ancla el patrón a la raíz, como en git."""
        spec = _spec(f"{EXT}/wheels/", ".claude/settings.local.json")
        self.assertTrue(spec.matches(f"{EXT}/wheels/duckdb-1.5.7.whl", False))
        self.assertTrue(spec.matches(".claude/settings.local.json", False))
        self.assertFalse(spec.matches(f"otra/{EXT}/wheels/x.whl", False))
        self.assertFalse(spec.matches("wheels/x.whl", False))
        self.assertFalse(spec.matches(".claude/settings.json", False))

    def test_glob_patterns(self) -> None:
        """RF-001-19: ``*``, ``?`` y ``[…]`` casan con el nombre en cualquier nivel."""
        spec = _spec("*.py[cod]", "*.blend[0-9]", "?.tmp", "~$*")
        self.assertTrue(spec.matches("a/b/modulo.pyc", False))
        self.assertTrue(spec.matches("modulo.pyo", False))
        self.assertFalse(spec.matches("modulo.py", False))
        self.assertTrue(spec.matches("escena.blend1", False))
        self.assertFalse(spec.matches("escena.blend", False))
        self.assertFalse(spec.matches("escena.blend12", False))
        self.assertTrue(spec.matches("x.tmp", False))
        self.assertFalse(spec.matches("xy.tmp", False))
        self.assertTrue(spec.matches("docs/~$informe.docx", False))

    def test_star_does_not_cross_folders(self) -> None:
        """RF-001-19: en un patrón anclado, ``*`` no atraviesa «/»."""
        spec = _spec("/docs/*.md")
        self.assertTrue(spec.matches("docs/trampas.md", False))
        self.assertFalse(spec.matches("docs/adr/0001-x.md", False))

    def test_double_star(self) -> None:
        """RF-001-19: ``**/x``, ``a/**/b`` y ``a/**``."""
        spec = _spec("**/salida", "a/**/b", "logs/**")
        self.assertTrue(spec.matches("salida", False))
        self.assertTrue(spec.matches("x/y/salida", False))
        self.assertTrue(spec.matches("a/b", False))
        self.assertTrue(spec.matches("a/x/y/b", False))
        self.assertFalse(spec.matches("c/a/b", False))
        self.assertTrue(spec.matches("logs/2026/registro.txt", False))
        self.assertFalse(spec.matches("logs", True))

    def test_child_of_excluded_dir_matches(self) -> None:
        """RF-001-19: lo que hay dentro de una carpeta excluida también lo está."""
        spec = _spec("build/")
        self.assertTrue(spec.matches("build/lib/a.py", False))
        self.assertTrue(spec.matches("x/build/lib/a.py", False))
        self.assertFalse(spec.matches("x/build.py", False))

    def test_negation_rejected(self) -> None:
        """RF-001-19: la negación «!» da un error claro en español."""
        with self.assertRaises(UnsupportedPattern) as ctx:
            _spec("*.log", "!importante.log")
        self.assertIn("!importante.log", str(ctx.exception))
        self.assertIn("negación", str(ctx.exception))
        self.assertIsInstance(ctx.exception, ValueError)

    def test_escaped_bang_is_literal(self) -> None:
        """RF-001-19: ``\\!`` es un «!» literal, no una negación."""
        spec = _spec("\\!raro.txt")
        self.assertTrue(spec.matches("!raro.txt", False))


class IterRepoFilesTest(unittest.TestCase):
    def test_always_excluded_folders(self) -> None:
        """RF-001-19, RF-007-01: en el código solo ``.git/`` (en cualquier nivel) no se
        comprueba: ``Documentacion/`` y ``Promts/`` sí (REP-01 las señala). Las excluye
        la documentación (``DOCS_EXCLUDED``), solo en su raíz, con la carpeta del
        código."""
        self.assertEqual(ALWAYS_EXCLUDED, (".git",))
        self.assertLessEqual({".git", "Documentacion", "Promts"}, set(DOCS_EXCLUDED))
        files = {
            ".git/config": "[core]\n",
            "Documentacion/informe.md": "x\n",
            "Promts/encargo.md": "x\n",
            "docs/constitution.md": "x\n",
            f"{EXT}/__init__.py": "x\n",
            "otra/Documentacion/nota.md": "x\n",
            "otra/.git": "gitdir: ../.git\n",
        }
        code = [
            f"{EXT}/__init__.py",
            "Documentacion/informe.md",
            "Promts/encargo.md",
            "docs/constitution.md",
            "otra/Documentacion/nota.md",
        ]
        docs = ["docs/constitution.md", "otra/Documentacion/nota.md"]
        with temp_tree(files) as root:
            # El orden depende de la mayúscula de la carpeta de la extensión.
            self.assertEqual(sorted(_listed(root)), sorted(code))
            listed = [relpath(root, p) for p in iter_repo_files(root, DOCS_EXCLUDED)]
            self.assertEqual(sorted(listed), docs)

    def test_gitignore_patterns_applied(self) -> None:
        """RF-001-19: se aplican los patrones del ``.gitignore``, con y sin ancla."""
        files = {
            ".gitignore": f"# x\n__pycache__/\n*.py[cod]\n/dist/\n{EXT}/wheels/\n",
            "tools/gbtools/__pycache__/repo.cpython-313.pyc": b"\x00",
            "tools/gbtools/repo.py": "x\n",
            "tools/viejo.pyc": b"\x00",
            "dist/geoblender-0.1.0.zip": b"PK",
            "tests/dist/caso.txt": "x\n",
            f"{EXT}/wheels/a-1.0-py3-none-any.whl": b"PK",
            f"{EXT}/__init__.py": "x\n",
        }
        expected = [
            ".gitignore",
            f"{EXT}/__init__.py",
            "tests/dist/caso.txt",
            "tools/gbtools/repo.py",
        ]
        with temp_tree(files) as root:
            self.assertEqual(_listed(root), expected)

    def test_negation_in_gitignore_is_an_error(self) -> None:
        """RF-001-19: un ``.gitignore`` con «!» no se recorre con otra semántica."""
        with temp_tree({".gitignore": "*.log\n!a.log\n", "a.log": "x\n"}) as root:
            with self.assertRaises(UnsupportedPattern):
                _listed(root)

    def test_without_gitignore(self) -> None:
        """RF-001-19: sin ``.gitignore`` solo se excluye ``.git/``."""
        with temp_tree({"a/__pycache__/b.pyc": b"\x00", "c.txt": "x\n"}) as root:
            self.assertEqual(_listed(root), ["a/__pycache__/b.pyc", "c.txt"])

    def test_excluded_folders_any_case(self) -> None:
        """RF-007-11: ``excluded`` deja fuera esas carpetas de la raíz sin distinguir
        mayúsculas (la documentación excluye así la carpeta del código), y solo en la
        raíz."""
        files = {"docs/a.md": "x\n", "codigo/b.py": "x\n", "docs/codigo/c.md": "x\n"}
        with temp_tree(files) as root:
            listed = [relpath(root, p) for p in iter_repo_files(root, (".git", "CODIGO"))]
        self.assertEqual(listed, ["docs/a.md", "docs/codigo/c.md"])

    def test_real_tree(self) -> None:
        """RF-001-19, RF-007-07: en el árbol real no sale nada de Documentacion/ ni
        Promts/ (y no se mira si hay documentación: el repositorio de código no la
        tiene)."""
        listed = _listed(ROOT)
        self.assertIn("AGENTS.md", listed)
        self.assertIn(MANIFEST_RELPATH, listed)
        self.assertIn("tests/support/repo.py", listed)
        tops = {rel.split("/", 1)[0] for rel in listed}
        self.assertFalse(tops & {".git", "Documentacion", "Promts"}, tops)
        self.assertFalse([rel for rel in listed if "__pycache__" in rel.split("/")])


class RepoHelpersTest(unittest.TestCase):
    def test_repo_root_from_nested_folder(self) -> None:
        """RF-001-19, RF-007-06: la raíz es la carpeta con el manifiesto de la extensión
        y ``tools/check.py`` (``layout.ROOT_MARKERS``)."""
        self.assertEqual(repo_root(ROOT / "tests" / "unit" / "tools"), ROOT)
        self.assertEqual(repo_root(), ROOT)
        files = dict.fromkeys(ROOT_MARKERS, "x\n") | {"t/g/x.py": "x\n"}
        with temp_tree(files) as root:
            self.assertEqual(repo_root(root / "t" / "g" / "x.py"), root.resolve())

    def test_repo_root_missing(self) -> None:
        """RF-001-19: sin raíz reconocible, error con mensaje en español."""
        with temp_tree({"a/b.txt": "x\n"}) as root:
            with self.assertRaises(FileNotFoundError) as ctx:
                repo_root(root / "a")
        self.assertIn("raíz del repositorio", str(ctx.exception))

    def test_is_text_file(self) -> None:
        """RF-001-19: son de texto todos salvo las binarias de ``.gitattributes``."""
        texts = ("a.py", "a.md", "LICENSE", "a.toml", "a.ps1", "a.svg", "Makefile")
        for name in texts:
            self.assertTrue(is_text_file(Path(name)), name)
        binaries = (
            "a.png", "a.PNG", "a.whl", "a.blend", "a.blend1", "a.blend12", "a.gpkg",
            "a.gpkg-wal", "a.gpkg-shm", "a.mdb", "a.accdb", "a.xlsx", "a.pdf",
        )
        for name in binaries:
            self.assertFalse(is_text_file(Path(name)), name)

    def test_iter_py_files_top(self) -> None:
        """RF-001-18: ``iter_py_files`` limita los ``.py`` a las carpetas pedidas."""
        files = {
            ".gitignore": "__pycache__/\n",
            f"{EXT}/core/__init__.py": "x\n",
            f"{EXT}/core/__pycache__/x.py": "x\n",
            f"{EXT}/blender_manifest.toml": "x\n",
            "tools/check.py": "x\n",
            "tests/unit/test_a.py": "x\n",
            ".git/hooks/viejo.py": "x\n",
        }
        with temp_tree(files) as root:
            every = [relpath(root, p) for p in iter_py_files(root)]
            chosen = iter_py_files(root, EXT, "tools")
            some = [relpath(root, p) for p in chosen]
        self.assertEqual(
            every,
            [f"{EXT}/core/__init__.py", "tests/unit/test_a.py", "tools/check.py"],
        )
        self.assertEqual(some, [f"{EXT}/core/__init__.py", "tools/check.py"])

    def test_relpath(self) -> None:
        """RF-001-19: las rutas de los incumplimientos son relativas y con «/»."""
        path = ROOT / "docs" / "adr" / "README.md"
        self.assertEqual(relpath(ROOT, path), "docs/adr/README.md")


class SnapshotTest(unittest.TestCase):
    def test_snapshot_skips_and_sees_changes(self) -> None:
        """RF-001-09: la foto del repositorio de ``tools/check.py`` (convergencia, T41)
        no recorre las carpetas de ``skip`` a ningún nivel ni las uniones de Windows, y
        sus diferencias nombran lo nuevo, lo borrado y lo cambiado."""
        files = {
            "a.txt": "a",
            "b.txt": "b",
            ".git/HEAD": "x",
            "sub/.git/HEAD": "x",
            "sub/c.txt": "c",
            "fuera/d.txt": "d",
        }
        with temp_tree(files) as tmp:
            junction = False
            if os.name == "nt":
                import _winapi

                _winapi.CreateJunction(str(tmp / "fuera"), str(tmp / "sub" / "union"))
                junction = True
            age_folders(tmp)
            before = snapshot(tmp, skip=(".git",))
            self.assertNotIn(".git/", before)
            self.assertNotIn("sub/.git/HEAD", before)
            self.assertEqual(before["sub/"], (-1, (tmp / "sub").stat().st_mtime_ns))
            self.assertEqual(before["./"], (-1, tmp.stat().st_mtime_ns))
            if junction:
                self.assertIn("sub/union", before)
                self.assertNotIn("sub/union/d.txt", before)
            (tmp / "a.txt").write_text("aa", encoding="utf-8")
            (tmp / "b.txt").unlink()
            (tmp / "sub" / "__pycache__").mkdir()
            (tmp / ".git" / "index").write_text("y", encoding="utf-8")
            after = snapshot(tmp, skip=(".git",))
        folder = f"({gbrepo.FOLDER_CHANGED})"
        self.assertEqual(
            snapshot_changes(before, after),
            [
                "nuevo: sub/__pycache__/",
                "borrado: b.txt",
                f"cambiado: ./ {folder}",
                "cambiado: a.txt",
                f"cambiado: sub/ {folder}",
            ],
        )

    def test_snapshot_sees_create_and_delete(self) -> None:
        """RF-001-09: crear un fichero y borrarlo deja la carpeta con otra fecha, y la
        foto lo ve; una carpeta sin cambios, no (hallazgo F4 de la ronda 3: la foto
        anotaba las carpetas como ``(-1, 0)``; convergencia, T51)."""
        with temp_tree({"tests/unit/test_a.py": "x\n", "docs/a.md": "a\n"}) as tmp:
            age_folders(tmp)
            before = snapshot(tmp)
            self.assertEqual(snapshot(tmp), before)
            path = tmp / "tests" / "unit" / "salida_temporal.json"
            path.write_text("{}", encoding="utf-8")
            path.unlink()
            after = snapshot(tmp)
        changes = snapshot_changes(before, after)
        self.assertEqual(len(changes), 1, changes)
        self.assertEqual(changes, [f"cambiado: tests/unit/ ({gbrepo.FOLDER_CHANGED})"])


class FindingsTest(unittest.TestCase):
    def test_format_sorted(self) -> None:
        """RF-001-18: ``fichero:línea: [REGLA] mensaje``, ordenado por ruta y línea."""
        findings = [
            Finding("tools/b.py", 3, "ARQ-12", "falta la cabecera"),
            Finding(f"{EXT}/a.py", 10, "ARQ-01", "importa bpy"),
            Finding(f"{EXT}/a.py", 2, "ARQ-01", "importa bmesh"),
        ]
        self.assertEqual(
            format_findings(findings),
            f"{EXT}/a.py:2: [ARQ-01] importa bmesh\n"
            f"{EXT}/a.py:10: [ARQ-01] importa bpy\n"
            "tools/b.py:3: [ARQ-12] falta la cabecera",
        )
        self.assertEqual(str(findings[0]), "tools/b.py:3: [ARQ-12] falta la cabecera")
        self.assertEqual(format_findings([]), "")


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: GPL-3.0-or-later
"""Las reglas analizan cada fichero una sola vez por proceso (spec 006, T47; RNF-001-01,
RNF-007-01).

``tools/check.py`` tiene que acabar en ≤ 40 s, y las pruebas que pasan todas las reglas
por el repositorio real (``run_all`` y las familias sueltas) eran el suelo del paso
«unitarias»: cada familia volvía a leer los ficheros y a recorrer sus árboles. Ahora el
texto de cada fichero se lee una vez (``repo.read_bytes``), cada ``.py`` se analiza una
vez (``pyast.parse_file``) y su árbol se recorre una vez (``pyast.walk`` e
``pyast.iter_statements``), mientras el fichero no cambie (ruta, fecha y tamaño), y lo
comparten todas las reglas y las pruebas que las llaman. Los hallazgos no cambian.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import unittest
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from tests.support.repo import EXT, TOOLS_DIR, manifest_without_wheels, tools_on_path
from tests.support.trees import temp_tree

tools_on_path()

from gbtools import layout, repo  # noqa: E402
from gbtools.rules import FAMILIES, pyast, run_all  # noqa: E402

SPDX = "# SPDX-License-Identifier: GPL-3.0-or-later\n"

# Un árbol pequeño con ficheros de la extensión, de pruebas, de herramientas y de texto,
# y un incumplimiento de varias familias (ARQ-01, TST-04, TXT-02).
FILES: dict[str, str | bytes] = {
    ".gitignore": "*.tmp\n",
    f"{EXT}/__init__.py": SPDX,
    f"{EXT}/core/__init__.py": SPDX,
    f"{EXT}/core/a.py": SPDX + '"""Docstring."""\nimport os\n\nX = os.sep\n',
    f"{EXT}/core/b.py": SPDX + "import bpy\n",
    f"{EXT}/bl/__init__.py": SPDX,
    f"{EXT}/bl/ops.py": SPDX + "import bpy\n\n\ndef f(x):\n    return x + 1\n",
    "tests/__init__.py": SPDX,
    "tests/unit/__init__.py": SPDX,
    "tests/unit/test_x.py": (
        SPDX + "import unittest\n\n\nclass T(unittest.TestCase):\n"
        "    @unittest.skip('siempre')\n"
        "    def test_x(self):\n"
        '        """RF-001-06: omitida."""\n'
    ),
    "tools/t.py": SPDX + "import json\n",
    "notas.txt": b"una\r\ndos\r\n",
    "README.md": "texto\n",
}


def _files() -> dict[str, str | bytes]:
    """:data:`FILES` con el manifiesto (el real, sin ruedas: se lee al usarlo)."""
    return {**FILES, layout.MANIFEST_RELPATH: manifest_without_wheels()}


def _under(root: Path, path: object) -> str | None:
    """La ruta de ``path`` relativa a ``root`` (con «/»), o ``None`` si no está dentro."""
    full = os.path.abspath(os.fspath(path))  # type: ignore[arg-type]
    base = os.path.abspath(root) + os.sep
    if not os.path.normcase(full).startswith(os.path.normcase(base)):
        return None
    return full[len(base):].replace(os.sep, "/")


@contextmanager
def _counting(root: Path) -> Iterator[tuple[Counter[str], Counter[str], Counter[str]]]:
    """Cuenta, mientras dura, las lecturas de cada fichero de ``root``
    (``Path.read_bytes`` y ``Path.read_text``), sus análisis (``ast.parse``) y los
    recorridos enteros de sus árboles (``ast.walk``, o el de ``pyast``, de un árbol
    entero)."""
    reads: Counter[str] = Counter()
    parses: Counter[str] = Counter()
    walks: Counter[str] = Counter()
    real_bytes, real_text = Path.read_bytes, Path.read_text
    real_parse, real_walk, real_traverse = ast.parse, ast.walk, pyast._traverse
    files_of: dict[int, str] = {}
    keep: list[ast.AST] = []  # los árboles contados no se liberan: su id no se reutiliza

    def read_bytes(self: Path) -> bytes:
        rel = _under(root, self)
        if rel is not None:
            reads[rel] += 1
        return real_bytes(self)

    def read_text(self: Path, *args: object, **kwargs: object) -> str:
        rel = _under(root, self)
        if rel is not None:
            reads[rel] += 1
        return real_text(self, *args, **kwargs)  # type: ignore[arg-type]

    def parse(source: object, filename: object = "<unknown>", *args: object,
              **kwargs: object) -> ast.AST:
        tree = real_parse(source, filename, *args, **kwargs)  # type: ignore[arg-type]
        rel = _under(root, filename)
        if rel is not None:
            parses[rel] += 1
            files_of[id(tree)] = rel
            keep.append(tree)
        return tree

    def counted(node: ast.AST) -> None:
        rel = files_of.get(id(node))
        if rel is not None:
            walks[rel] += 1

    def walk(node: ast.AST) -> Iterator[ast.AST]:
        counted(node)
        return real_walk(node)

    def traverse(node: ast.AST) -> list[ast.AST]:
        counted(node)
        return real_traverse(node)

    with (
        mock.patch.object(Path, "read_bytes", read_bytes),
        mock.patch.object(Path, "read_text", read_text),
        mock.patch.object(ast, "parse", parse),
        mock.patch.object(ast, "walk", walk),
        mock.patch.object(pyast, "_traverse", traverse),
    ):
        yield reads, parses, walks


class SharedAnalysisTest(unittest.TestCase):
    def test_each_file_once_per_process(self) -> None:
        """RNF-001-01, RNF-007-01 (spec 006, T47): ``run_all`` dos veces sobre un árbol
        y después cada familia suelta: cada fichero se lee una sola vez, cada ``.py`` se
        analiza una sola vez y su árbol se recorre entero una sola vez; los hallazgos son
        los mismos cada vez, y los de ``run_all``, los de todas las familias juntas."""
        files = _files()
        with temp_tree(files) as root, _counting(root) as (reads, parses, walks):
            first = run_all(root)
            second = run_all(root)
            separate = sorted({f for check in FAMILIES.values() for f in check(root)})
        self.assertEqual(first, second)
        self.assertEqual(first, separate)
        rules = {f.rule for f in first}
        self.assertTrue({"ARQ-01", "TST-04", "TXT-02"} <= rules, first)
        py_files = sorted(rel for rel in files if rel.endswith(".py"))
        self.assertEqual(sorted(parses), py_files)
        self.assertEqual({rel for rel, n in parses.items() if n != 1}, set(), parses)
        self.assertEqual(sorted(reads), sorted(files))
        self.assertEqual({rel for rel, n in reads.items() if n != 1}, set(), reads)
        self.assertLessEqual({rel for rel in py_files if rel.startswith(EXT)}, set(walks))
        self.assertEqual({rel for rel, n in walks.items() if n != 1}, set(), walks)

    def test_changed_file_is_read_again(self) -> None:
        """RNF-001-01 (spec 006, T47): un fichero que cambia (otra fecha u otro tamaño)
        se vuelve a leer y a analizar, y sus hallazgos son los nuevos."""
        with temp_tree(FILES) as root:
            before = {(f.path, f.rule) for f in run_all(root)}
            self.assertNotIn((f"{EXT}/core/a.py", "ARQ-01"), before)
            self.assertNotIn(("README.md", "TXT-02"), before)
            (root / EXT / "core" / "a.py").write_text(
                SPDX + '"""Docstring."""\nimport bpy\n', encoding="utf-8"
            )
            (root / "README.md").write_bytes(b"texto\r\n")
            after = {(f.path, f.rule) for f in run_all(root)}
        self.assertIn((f"{EXT}/core/a.py", "ARQ-01"), after)
        self.assertIn(("README.md", "TXT-02"), after)

    def test_walk_and_statements_shared(self) -> None:
        """RNF-001-01 (spec 006, T47): ``pyast.walk`` da los nodos en el orden de
        ``ast.walk`` (los mismos objetos), ``pyast.nodes_of`` los de unos tipos en ese
        orden y ``pyast.iter_statements`` las sentencias de siempre, recorriendo el árbol
        una sola vez para todas las llamadas; otro árbol, su propio recorrido."""
        source = (
            SPDX + "import os\n\n\nclass A:\n    def f(self, x):\n"
            "        if x:\n            return [y for y in x]\n        return None\n"
        )
        with temp_tree({"m.py": source}) as root:
            path = root / "m.py"
            tree = pyast.parse_file(path)
            self.assertIs(pyast.parse_file(path), tree)
            expected = list(ast.walk(tree))
            kinds = (ast.Module, ast.Name, ast.Return, ast.expr_context)
            with mock.patch.object(pyast, "_traverse", wraps=pyast._traverse) as walk:
                for _again in range(2):
                    found = list(pyast.walk(tree))
                    self.assertEqual(len(found), len(expected))
                    for mine, theirs in zip(found, expected, strict=True):
                        self.assertIs(mine, theirs)
                    self.assertEqual(
                        pyast.nodes_of(tree, kinds),
                        [node for node in expected if isinstance(node, kinds)],
                    )
                    self.assertEqual(pyast.nodes_of(tree, ast.Yield), [])
                statements = list(pyast.iter_statements(tree))
                self.assertEqual(list(pyast.iter_statements(tree)), statements)
            self.assertEqual(walk.call_count, 1)
            self.assertEqual(
                [type(node).__name__ for node in statements],
                ["Import", "ClassDef", "FunctionDef", "If", "Return", "Return"],
            )
            other = ast.parse(source)
            self.assertEqual(
                [type(node) for node in pyast.walk(other)], [type(n) for n in expected]
            )
            self.assertEqual(repo.read_bytes(path), source.encode("utf-8"))

    def test_caches_emptied_at_exit(self) -> None:
        """RNF-001-01 (spec 006, T47): ``pyast.clear_caches`` vacía los árboles, sus
        recorridos, sus imports y el texto (después, un fichero se vuelve a leer y a
        analizar), y se llama sola al salir del proceso, antes de que Python lo cierre:
        liberar al cerrar los árboles de todo el repositorio le costaba ≈ 2 s a cada
        proceso que había pasado las reglas, y vaciarlos antes, ≈ 0,1 s."""
        with temp_tree(FILES) as root:
            path = root / EXT / "core" / "a.py"
            tree = pyast.parse_file(path)
            list(pyast.walk(tree))
            pyast.clear_caches()
            for cache in (pyast._parse_cached, pyast._imports_cached, repo._read_cached):
                self.assertEqual(cache.cache_info().currsize, 0, cache)
            self.assertEqual(len(pyast._WALKS), 0)
            self.assertEqual(len(pyast._STATEMENTS), 0)
            self.assertIsNot(pyast.parse_file(path), tree)
            # Un proceso aparte: su manejador de salida, registrado antes de importar las
            # reglas, se ejecuta después del de ``pyast`` (atexit va en orden inverso).
            script = (
                "import atexit, sys\n"
                "from pathlib import Path\n"
                "sys.path.insert(0, sys.argv[1])\n"
                "def report():\n"
                "    print(pyast._parse_cached.cache_info().currsize, len(pyast._WALKS))\n"
                "atexit.register(report)\n"
                "from gbtools.rules import pyast, run_all\n"
                "run_all(Path(sys.argv[2]))\n"
                "print(pyast._parse_cached.cache_info().currsize > 0, len(pyast._WALKS) > 0)\n"
            )
            done = subprocess.run(
                [sys.executable, "-B", "-s", "-c", script, str(TOOLS_DIR), str(root)],
                capture_output=True, text=True, timeout=60, check=False,
            )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.split(), ["True", "True", "0", "0"], done.stdout)


if __name__ == "__main__":
    unittest.main()

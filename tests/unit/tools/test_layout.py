# SPDX-License-Identifier: GPL-3.0-or-later
"""El árbol del repositorio de código en un solo sitio, ``gbtools.layout`` (spec 007).

La raíz se reconoce por el manifiesto de la extensión y ``tools/check.py``, sin ningún
fichero de la documentación (RF-007-06).
"""

import ast
import os
import unittest
from pathlib import Path

from tests.support.repo import ROOT, real_manifest, tools_on_path
from tests.support.trees import temp_tree

tools_on_path()

from gbtools import layout  # noqa: E402
from gbtools.repo import iter_py_files, relpath, repo_root  # noqa: E402

LAYOUT_RELPATH = "tools/gbtools/layout.py"
EXTENSION_NAMES: tuple[str, ...] = ("Geoblender", "geoblender")
# Un literal que contiene uno de estos trozos es una ruta dentro de la extensión.
PATH_PIECES: tuple[str, ...] = tuple(
    f"{name}{separator}" for name in EXTENSION_NAMES for separator in ("/", "\\")
)
MODULE_OWNER = "<módulo>"
# Lista cerrada de excepciones (plan 007 §5.4.1): (fichero, dueño, literal) → motivo. El
# dueño es la constante o variable a la que se asigna el literal o, si no, la función o
# clase que lo contiene. Cada una tiene que seguir haciendo falta
# (``test_no_other_extension_literal`` lo comprueba).
_UPPER, _LOWER = EXTENSION_NAMES
_PROFILE = "la carpeta del perfil de desarrollo en %LOCALAPPDATA%, no la de la extensión"
ALLOWED: dict[tuple[str, str, str], str] = {
    ("tests/unit/tools/test_layout.py", "EXTENSION_NAMES", _UPPER):
        "los nombres que busca esta prueba",
    ("tests/unit/tools/test_layout.py", "EXTENSION_NAMES", _LOWER):
        "los nombres que busca esta prueba",
    ("tools/dev_install.py", "DEFAULT_PROFILE_PARTS", _UPPER): _PROFILE,
    ("tests/unit/tools/test_dev_install.py", "default", _UPPER): _PROFILE,
    ("tests/unit/tools/test_dev_install.py", "profile", _UPPER): _PROFILE,
    ("tools/gbtools/manifest.py", "EXPECTED", _LOWER): "el id de la extensión (MAN-01)",
    ("tests/unit/test_manifest.py", "test_identity_fields", _LOWER):
        "el id del manifiesto real",
    ("tests/unit/test_manifest.py", "test_identity_fields", _UPPER):
        "el nombre visible del manifiesto real (name)",
    ("tools/gbtools/package.py", "load_geoblender", _LOWER):
        "el nombre del paquete, el final de bl_ext.<repositorio>.<id>",
    ("tests/support/package.py", "PACKAGE_NAME", _LOWER): "el nombre del paquete",
    ("tools/gbtools/rules/imports.py", "INTERNAL_ROOTS", _UPPER):
        "un import absoluto de la extensión por su nombre (ARQ-09)",
    ("tools/gbtools/rules/imports.py", "INTERNAL_ROOTS", _LOWER):
        "un import absoluto de la extensión por su nombre (ARQ-09)",
    ("tools/gbtools/rules/imports.py", "_tools_findings", _LOWER):
        "el paquete cargado por ruta que HER-01 admite en tools/",
    ("tools/gbtools/rules/naming.py", "IDNAME_RE", f"^{_LOWER}\\.("):
        "el prefijo del bl_idname de los operadores (NOM-01)",
    ("tools/run_blender_tests.py", "EXTENSION_ID", _LOWER):
        "el id con que se instala la copia de las pruebas",
}


def _docstring_nodes(tree: ast.Module) -> set[int]:
    """Los ``id`` de los nodos que son docstrings (módulo, clases y funciones)."""
    found: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            found.add(id(body[0].value))
    return found


def _owner(node: ast.AST, parents: dict[int, ast.AST]) -> str:
    """La constante o variable a la que se asigna ``node`` o, si no, la función o clase
    que lo contiene (``MODULE_OWNER`` en el nivel del módulo)."""
    current = parents.get(id(node))
    while current is not None:
        if isinstance(current, (ast.Assign, ast.AnnAssign)):
            targets = current.targets if isinstance(current, ast.Assign) else [current.target]
            if len(targets) == 1 and isinstance(targets[0], ast.Name):
                return targets[0].id
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return current.name
        current = parents.get(id(current))
    return MODULE_OWNER


def extension_literals(root: Path) -> list[tuple[str, int, str, str]]:
    """Literales de cadena de ``tools/`` y ``tests/`` (sin docstrings ni ``layout.py``)
    que escriben la carpeta de la extensión: (fichero, línea, dueño, literal).

    Cuenta un literal que contiene un trozo de ruta (``Geoblender/``, ``geoblender\\``…)
    y uno que es exactamente el nombre, en mayúscula o en minúscula, se use donde se
    use: como parte de una ruta (operando de «/», argumento de ``Path(…)``,
    ``os.path.join(…)``, ``shutil.copytree(…)`` o ``blender.extension_cmd(…)``) o en una
    constante que después lo será. Lo que no es la carpeta (el ``id``, el paquete, el
    nombre visible) va en ``ALLOWED`` con su motivo."""
    found: list[tuple[str, int, str, str]] = []
    for path in iter_py_files(root, "tools", "tests"):
        rel = relpath(root, path)
        if rel == LAYOUT_RELPATH:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        docstrings = _docstring_nodes(tree)
        parents: dict[int, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[id(child)] = node
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if id(node) in docstrings:
                continue
            value = node.value
            if value in EXTENSION_NAMES or any(piece in value for piece in PATH_PIECES):
                found.append((rel, node.lineno, _owner(node, parents), value))
    return sorted(found)


class RepoRootTest(unittest.TestCase):
    def test_repo_root_without_docs(self) -> None:
        """RF-007-06: un árbol con el manifiesto de la extensión y ``tools/check.py``, sin
        ``docs/``, es la raíz del repositorio de código, también desde una carpeta de
        dentro."""
        files = {
            layout.MANIFEST_RELPATH: "x\n",
            "tools/check.py": "x\n",
            "tools/gbtools/repo.py": "x\n",
        }
        with temp_tree(files) as root:
            self.assertFalse((root / "docs").exists())
            self.assertEqual(repo_root(root / "tools" / "gbtools" / "repo.py"), root.resolve())
            self.assertEqual(repo_root(root), root.resolve())

    def test_repo_root_markers(self) -> None:
        """RF-007-06: los marcadores son el manifiesto y ``tools/check.py``; con uno solo
        no hay raíz (y el mensaje los nombra), y se elige la primera carpeta que tiene
        los dos, subiendo; en el repositorio real, ``ROOT``."""
        self.assertEqual(layout.ROOT_MARKERS, (layout.MANIFEST_RELPATH, "tools/check.py"))
        self.assertEqual(
            layout.MANIFEST_RELPATH, f"{layout.EXTENSION_DIR}/blender_manifest.toml"
        )
        for marker in layout.ROOT_MARKERS:
            with self.subTest(solo=marker), temp_tree({marker: "x\n", "a/b.txt": "x\n"}) as root:
                with self.assertRaises(FileNotFoundError) as ctx:
                    repo_root(root / "a")
                message = str(ctx.exception)
                self.assertIn("raíz del repositorio", message)
                for name in layout.ROOT_MARKERS:
                    self.assertIn(name, message)
        files = {
            layout.MANIFEST_RELPATH: "x\n",
            "tools/check.py": "x\n",
            f"sub/{layout.MANIFEST_RELPATH}": "x\n",
            "sub/t/x.py": "x\n",
        }
        with temp_tree(files) as root:
            self.assertEqual(repo_root(root / "sub" / "t" / "x.py"), root.resolve())
        self.assertEqual(repo_root(ROOT / "tests" / "unit" / "tools"), ROOT)
        self.assertEqual(repo_root(), ROOT)


class ExtensionDirTest(unittest.TestCase):
    def test_extension_dir_exact(self) -> None:
        """RF-007-02, RF-007-07: la carpeta de la extensión se llama como su ``id``, en
        minúsculas, y así está en el disco (``os.listdir`` de la raíz, con su
        mayúscula), sin la carpeta del nombre antiguo."""
        self.assertEqual(layout.EXTENSION_DIR, _LOWER)
        self.assertEqual(layout.EXTENSION_DIR, real_manifest()["id"])
        names = os.listdir(ROOT)
        self.assertIn(layout.EXTENSION_DIR, names)
        self.assertNotIn(_UPPER, names)


class RulesSplitTest(unittest.TestCase):
    def test_rules_split(self) -> None:
        """RF-007-07, RF-007-11: el verde del código (``FAMILIES``) no lleva ADR-01 ni
        NOM-03, que pasan a la documentación: ``DOCS_FAMILIES`` (ADR-01, AGT-01 y AGT-02,
        NOM-03, TXT y REP-03) y ``run_docs``, que no entra en la carpeta del código (con
        cualquier mayúscula)."""
        from gbtools import rules

        self.assertNotIn("adr", rules.FAMILIES)
        self.assertNotIn("specs", rules.FAMILIES)
        self.assertNotIn("docs_repo", rules.FAMILIES)
        self.assertEqual(
            sorted(rules.DOCS_FAMILIES), ["adr", "agents", "docs_repo", "specs", "text"]
        )
        code_folder = layout.CODE_DIR_IN_DOCS.lower()
        files = {
            "docs/constitution.md": "x\n",
            "docs/adr/README.md": "# ADR\n",
            "docs/adr/0001-mal.md": "sin título\n",
            "specs/7-mal/spec.md": "x\n",
            "AGENTS.md": "# Reglas\n",
            "nota.md": "a\r\nb\r\n",
            f"{code_folder}/nota.md": "a\r\nb\r\n",
            f"{code_folder}/AGENTS.md": "# Reglas del código\n",
        }
        with temp_tree(files) as root:
            code = {f.rule for f in rules.run_all(root)}
            docs = rules.run_docs(root)
        self.assertFalse(code & {"ADR-01", "NOM-03"}, code)
        self.assertLessEqual({"ADR-01", "NOM-03", "AGT-01", "TXT-02"}, {f.rule for f in docs})
        inside = [f for f in docs if f.path.casefold().startswith(code_folder + "/")]
        self.assertEqual(inside, [])
        self.assertIn(("nota.md", "TXT-02"), [(f.path, f.rule) for f in docs])


class ExtensionLiteralTest(unittest.TestCase):
    def test_no_other_extension_literal(self) -> None:
        """RF-007-06, RF-007-07: fuera de ``gbtools/layout.py``, ningún literal de
        ``tools/`` ni de ``tests/`` (salvo los docstrings) escribe la carpeta de la
        extensión: ni un trozo de ruta (``Geoblender/``, ``geoblender\\``…) ni el nombre
        solo, salvo las excepciones de la lista cerrada, que siguen haciendo falta, cada
        una."""
        found = extension_literals(ROOT)
        sites = [
            f"{rel}:{line}: «{value}» (en {owner})"
            for rel, line, owner, value in found
            if (rel, owner, value) not in ALLOWED
        ]
        self.assertEqual(sites, [], "\n" + "\n".join(sites))
        used = {(rel, owner, value) for rel, _line, owner, value in found}
        self.assertEqual(sorted(set(ALLOWED) - used), [], "excepciones que sobran")
        for key, reason in ALLOWED.items():
            self.assertTrue(reason.strip(), key)

    def test_detector_sees_paths(self) -> None:
        """RF-007-07: control positivo del detector: ve cada forma de escribir la
        carpeta (trozo de ruta, f-string, operando de «/», argumento de ``Path``,
        ``os.path.join`` y ``extension_cmd``, el nombre solo en una constante o en un
        diccionario) con su dueño, y no un docstring, otro nombre que lo contiene ni lo
        que está fuera de ``tools/`` y ``tests/`` o en ``layout.py``."""
        # Los nombres se ponen al construir las fuentes: así este fichero no escribe
        # ningún literal que la propia prueba señale.
        upper, lower = EXTENSION_NAMES
        sources = {
            "tools/a.py": (
                '"""Docstring con <G>/core/."""\n'
                "from pathlib import Path\n"
                "import os\n"
                'A = "<G>/wheels"\n'
                'B = f"<g>\\\\{x}"\n'
                'C = root / "<G>"\n'
                'D = Path(root, "<g>")\n'
                'E = os.path.join(root, "<G>")\n'
                'F = blender.extension_cmd(install, "validate", "<G>")\n'
                'G = "<G>"\n'
                'H = {"id": "<g>"}\n'
                "def f():\n"
                '    """<G>/ en un docstring."""\n'
                '    return "bl_ext.user_default.<g>", "<G> (pruebas)", "<g>-dev-"\n'
                "class K:\n"
                '    def g(self):\n'
                '        self.assertEqual(name, "<G>")\n'
            ),
            "tests/b.py": 'X = ["<G>/__init__.py"]\n',
            "otra/c.py": 'Y = "<G>/x.py"\n',
            LAYOUT_RELPATH: 'EXTENSION_DIR = "<G>/"\n',
        }
        sources = {
            rel: text.replace("<G>", upper).replace("<g>", lower)
            for rel, text in sources.items()
        }
        with temp_tree(sources) as root:
            found = extension_literals(root)
        self.assertEqual(
            found,
            [
                ("tests/b.py", 1, "X", f"{upper}/__init__.py"),
                ("tools/a.py", 4, "A", f"{upper}/wheels"),
                ("tools/a.py", 5, "B", f"{lower}\\"),
                ("tools/a.py", 6, "C", upper),
                ("tools/a.py", 7, "D", lower),
                ("tools/a.py", 8, "E", upper),
                ("tools/a.py", 9, "F", upper),
                ("tools/a.py", 10, "G", upper),
                ("tools/a.py", 11, "H", lower),
                ("tools/a.py", 17, "g", upper),
            ],
        )


if __name__ == "__main__":
    unittest.main()

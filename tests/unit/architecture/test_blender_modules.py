# SPDX-License-Identifier: GPL-3.0-or-later
"""ARQ-01: los módulos de Blender solo se importan en ``geoblender/bl/`` (RF-001-12).

También se aplica a ``tests/`` y ``tools/``, salvo las pruebas de Blender, su lanzador y
los guiones que se ejecutan dentro de Blender. Los nombres de los módulos de Blender se
construyen por concatenación: el texto del repositorio no contiene esos imports.
"""

import ast
import unittest

from tests.support.repo import EXT, ROOT, tools_on_path
from tests.support.trees import temp_tree

tools_on_path()

from gbtools.findings import format_findings  # noqa: E402
from gbtools.rules import imports, pyast  # noqa: E402

SPDX = "# SPDX-License-Identifier: GPL-3.0-or-later\n"
BPY = "b" + "py"
BMESH = "b" + "mesh"
GPU = "g" + "pu"
MATHUTILS = "math" + "utils"
RNA_KEYMAP_UI = "rna_" + "keymap_ui"


def _arq01(files: dict[str, str]) -> list[tuple[str, int]]:
    """``(fichero, línea)`` de cada incumplimiento de ARQ-01 en un árbol temporal."""
    tree = {rel: SPDX + text for rel, text in files.items()}
    with temp_tree(tree) as root:
        findings = imports.check_blender_modules(root)
    for finding in findings:
        assert finding.rule == "ARQ-01", finding
    return [(f.path, f.line) for f in findings]


class BlenderModulesTest(unittest.TestCase):
    def test_bpy_in_core(self) -> None:
        """RF-001-12 / ARQ-01: ``import bpy`` (u otro de la lista) en ``core/``."""
        found = _arq01(
            {
                f"{EXT}/core/__init__.py": f'"""Núcleo."""\nimport {BPY}\n',
                f"{EXT}/gis/grid.py": f"from {BPY}.types import Operator\n",
                f"{EXT}/design/mesh.py": f"import os\nimport {BMESH} as bm\n",
                f"{EXT}/__init__.py": f"import {GPU}\n",
            }
        )
        self.assertEqual(
            found,
            [
                (f"{EXT}/__init__.py", 2),
                (f"{EXT}/core/__init__.py", 3),
                (f"{EXT}/design/mesh.py", 3),
                (f"{EXT}/gis/grid.py", 2),
            ],
        )

    def test_import_inside_function(self) -> None:
        """RF-001-12 / ARQ-01: también dentro de funciones o de ``if TYPE_CHECKING``."""
        found = _arq01(
            {
                f"{EXT}/core/geom.py": (
                    "from typing import TYPE_CHECKING\n"
                    "if TYPE_CHECKING:\n"
                    f"    import {GPU}\n"
                    "def centre(points):\n"
                    f"    from {MATHUTILS} import Vector\n"
                    "    return Vector(points[0])\n"
                    "class Helper:\n"
                    "    def run(self):\n"
                    f"        import {BMESH}\n"
                ),
            }
        )
        self.assertEqual(
            found,
            [
                (f"{EXT}/core/geom.py", 4),
                (f"{EXT}/core/geom.py", 6),
                (f"{EXT}/core/geom.py", 10),
            ],
        )

    def test_dynamic_literal_import(self) -> None:
        """RF-001-12 / ARQ-01: ``importlib.import_module("bpy")`` y ``__import__``
        con nombre literal se detectan; con un nombre construido en ejecución, no
        (límite declarado)."""
        found = _arq01(
            {
                "tests/unit/test_dinamico.py": (
                    "import importlib\n"
                    "from importlib import import_module as load\n"
                    f'importlib.import_module("{BPY}")\n'
                    f'__import__("{GPU}")\n'
                    f'load("{BMESH}.ops")\n'
                    'importlib.import_module("os.path")\n'
                    f'name = "{BPY}"\n'
                    "importlib.import_module(name)\n"
                ),
            }
        )
        self.assertEqual(
            found,
            [
                ("tests/unit/test_dinamico.py", 4),
                ("tests/unit/test_dinamico.py", 5),
                ("tests/unit/test_dinamico.py", 6),
            ],
        )

    def test_tests_unit_cannot_import_bpy(self) -> None:
        """RF-001-12 / ARQ-01: ``tests/unit``, el resto de ``tests/`` y ``tools/``
        tampoco importan módulos de Blender."""
        found = _arq01(
            {
                "tests/unit/test_x.py": f"import {BPY}\n",
                "tests/support/helpers.py": f"import {MATHUTILS}\n",
                "tests/rendimiento/test_lento.py": f"import {BPY}\n",
                "tools/check.py": f"import {BPY}\n",
                "tools/gbtools/blender.py": f"from {BPY} import app\n",
            }
        )
        self.assertEqual(
            found,
            [
                ("tests/rendimiento/test_lento.py", 2),
                ("tests/support/helpers.py", 2),
                ("tests/unit/test_x.py", 2),
                ("tools/check.py", 2),
                ("tools/gbtools/blender.py", 2),
            ],
        )

    def test_bl_allowed(self) -> None:
        """RF-001-12 / ARQ-01: dentro de ``geoblender/bl/`` sí se importan."""
        found = _arq01(
            {
                f"{EXT}/bl/__init__.py": f"import {BPY}\n",
                f"{EXT}/bl/ops/core.py": (
                    f"import {BPY}\nimport {BMESH}\nimport {GPU}\n"
                    f"from {MATHUTILS} import Vector\n"
                ),
                f"{EXT}/bl/compat.py": (
                    f'import importlib\nimportlib.import_module("{BPY}")\n'
                ),
            }
        )
        self.assertEqual(found, [])

    def test_rna_keymap_ui_in_bl_ok_in_core_fails(self) -> None:
        """RF-001-12 / ARQ-01: ``rna_keymap_ui`` vale en ``bl/``; en ``core/``, no."""
        found = _arq01(
            {
                f"{EXT}/bl/ui/keymap.py": f"import {RNA_KEYMAP_UI}\n",
                f"{EXT}/core/keys.py": f"import {RNA_KEYMAP_UI}\n",
            }
        )
        self.assertEqual(found, [(f"{EXT}/core/keys.py", 2)])

    def test_rendimiento_blender_allowed(self) -> None:
        """RF-001-12 / ARQ-01: las pruebas de Blender (también las de rendimiento dentro
        de Blender) y su ayudante sí importan módulos de Blender."""
        found = _arq01(
            {
                "tests/blender/test_registration.py": f"import {BPY}\n",
                "tests/rendimiento/blender/perf_registration.py": f"import {BPY}\n",
                "tests/support/blender_ext.py": f"import {BPY}\nimport addon_utils\n",
            }
        )
        self.assertEqual(found, [])

    def test_tools_inblender_allowed(self) -> None:
        """RF-001-12 / ARQ-01: ``tools/inblender/`` y el lanzador de pruebas de Blender
        sí importan módulos de Blender."""
        found = _arq01(
            {
                "tools/inblender/render_icons.py": f"import {BPY}\nimport {GPU}\n",
                "tools/run_blender_tests.py": f"import {BPY}\nimport addon_utils\n",
            }
        )
        self.assertEqual(found, [])

    def test_whole_list_and_prefixes(self) -> None:
        """RF-001-12 / ARQ-01: toda la lista del plan y los prefijos ``_bpy`` y
        ``_bl_``; otros nombres parecidos, no."""
        internal = ["_" + BPY, "_bl_i18n", "_bpy_internal"]
        names = sorted(imports.BLENDER_MODULES) + internal
        body = "".join(f"import {name}\n" for name in names)
        similar = "import bplib\nimport blfx\n"
        found = _arq01({f"{EXT}/core/todos.py": body + similar})
        self.assertEqual(len(found), len(names))
        self.assertEqual(len(imports.BLENDER_MODULES), 22)

    def test_extra_modules_from_installation(self) -> None:
        """RF-001-12 / ARQ-01: la lista se amplía con los módulos de la instalación."""
        extra = "bl_" + "i18n_utils"
        files = {f"{EXT}/core/a.py": SPDX + f"import {extra}\n"}
        with temp_tree(files) as root:
            self.assertEqual(imports.check_blender_modules(root), [])
            wider = imports.BLENDER_MODULES | {extra}
            found = imports.check_blender_modules(root, blender_modules=wider)
        self.assertEqual(
            [(f.path, f.rule) for f in found], [(f"{EXT}/core/a.py", "ARQ-01")]
        )

    def test_installation_modules(self) -> None:
        """RF-001-12 / ARQ-01: los módulos de la instalación son los nombres de primer
        nivel de ``scripts/modules`` y ``scripts/startup`` (ficheros ``.py`` y
        carpetas), sin ``__pycache__`` ni ficheros que no son módulos."""
        files = {
            "scripts/modules/_rna_info.py": "",
            "scripts/modules/bl_keymap_utils/__init__.py": "",
            "scripts/modules/__pycache__/x.pyc": "",
            "scripts/modules/LEEME.txt": "",
            "scripts/startup/keyingsets_builtins.py": "",
            "scripts/startup/bl_operators/__init__.py": "",
            "scripts/startup/no-es-un-modulo.py": "",
        }
        with temp_tree(files) as root:
            found = imports.installation_modules(root / "scripts")
            missing = imports.installation_modules(root / "no-existe")
        self.assertEqual(
            sorted(found),
            ["_rna_info", "bl_keymap_utils", "bl_operators", "keyingsets_builtins"],
        )
        self.assertEqual(missing, frozenset())

    def test_modules_from_environment(self) -> None:
        """RF-001-12 / ARQ-01: ``tools/check.py`` pasa los módulos de la instalación en
        ``GEOBLENDER_BLENDER_MODULES``; sin la variable, queda la lista fija."""
        extra = "_rna_" + "info"
        self.assertEqual(imports.blender_modules({}), imports.BLENDER_MODULES)
        wider = imports.blender_modules(
            {imports.ENV_BLENDER_MODULES: f" {extra}, keyingsets_builtins ,,"}
        )
        self.assertEqual(
            wider, imports.BLENDER_MODULES | {extra, "keyingsets_builtins"}
        )
        files = {f"{EXT}/core/a.py": SPDX + f"import {extra}\n"}
        with temp_tree(files) as root:
            found = imports.check_blender_modules(root, blender_modules=wider)
        self.assertEqual([f.rule for f in found], ["ARQ-01"])

    def test_unparsable_file_reported(self) -> None:
        """RF-001-12 / ARQ-01: un ``.py`` que no se puede analizar no pasa callado."""
        with temp_tree({f"{EXT}/core/roto.py": SPDX + "def f(:\n"}) as root:
            findings = imports.check_blender_modules(root)
        self.assertEqual([(f.path, f.line, f.rule) for f in findings],
                         [(f"{EXT}/core/roto.py", 2, pyast.RULE_UNPARSABLE)])

    def test_real_tree(self) -> None:
        """RF-001-12 / ARQ-01: el repositorio real no importa módulos de Blender fuera
        de ``bl/`` y de las excepciones (con la lista ampliada por ``tools/check.py``
        si la hay)."""
        findings = imports.check_blender_modules(
            ROOT, blender_modules=imports.blender_modules()
        )
        self.assertEqual(findings, [], "\n" + format_findings(findings))


class ImportCollectorTest(unittest.TestCase):
    """El recolector de imports en el que se apoyan las reglas (plan 001 §5.4.2)."""

    def _refs(self, source: str, module: str = "core.a", is_package: bool = False):
        return pyast.collect_imports(ast.parse(source), module, is_package)

    def test_contexts(self) -> None:
        """RF-001-12: contexto de cada import (función, ``TYPE_CHECKING``, dinámico)."""
        refs = self._refs(
            "import os, json as j\n"
            "import typing\n"
            "if typing.TYPE_CHECKING:\n"
            "    from collections import abc\n"
            "def register():\n"
            "    from . import b\n"
            "    def inner():\n"
            "        import csv\n"
            "class K:\n"
            "    import re\n"
            "    def m(self):\n"
            "        import zlib\n"
            "__import__('sqlite3')\n"
        )
        summary = [
            (r.target, r.line, r.in_function, r.in_type_checking, r.dynamic,
             r.top_function)
            for r in refs
        ]
        self.assertEqual(
            summary,
            [
                ("os", 1, False, False, False, None),
                ("json", 1, False, False, False, None),
                ("typing", 2, False, False, False, None),
                ("collections.abc", 4, False, True, False, None),
                ("core.b", 6, True, False, False, "register"),
                ("csv", 8, True, False, False, "register"),
                ("re", 10, False, False, False, None),
                ("zlib", 12, True, False, False, None),
                ("sqlite3", 13, False, False, True, None),
            ],
        )

    def test_relative_resolution(self) -> None:
        """RF-001-12, RF-001-14: los relativos se resuelven dentro del paquete."""
        refs = self._refs("from ..gis import x\nfrom . import b\nfrom .c import d\n")
        self.assertEqual([(r.target, r.relative_level) for r in refs],
                         [("gis.x", 2), ("core.b", 1), ("core.c.d", 1)])
        root = self._refs("from . import bl\nfrom .core import units\n", "", True)
        self.assertEqual([r.target for r in root], ["bl", "core.units"])
        package = self._refs("from . import grid\nfrom .. import core\n", "gis", True)
        self.assertEqual([r.target for r in package], ["gis.grid", "core"])
        escaping = self._refs("from ... import x\n", "core.a", False)
        self.assertTrue(escaping[0].escapes)
        self.assertEqual(escaping[0].target, "...x")

    def test_statement_mode_is_complete(self) -> None:
        """RF-001-12: el recorrido rápido (solo sentencias, sin imports dinámicos) halla
        los mismos imports estáticos que el completo, también anidados."""
        source = (
            "import os\n"
            "try:\n    import json\nexcept ImportError:\n    import csv\n"
            "else:\n    import re\nfinally:\n    import zlib\n"
            "with open('x') as f:\n    import abc\n"
            "for i in range(2):\n    import io\nelse:\n    import gc\n"
            "while False:\n    import bz2\n"
            "match 1:\n    case 1:\n        import lzma\n"
            "class K:\n    def m(self):\n        if True:\n            import array\n"
            "x = [i for i in range(3)]\n"
        )
        tree = ast.parse(source)
        fast = pyast.collect_imports(tree, "core.a", False, scan_calls=False)
        full = pyast.collect_imports(tree, "core.a", False, scan_calls=True)
        self.assertEqual(fast, full)
        self.assertEqual(len(fast), 11)

    def test_module_name(self) -> None:
        """RF-001-12: nombre de módulo a partir de la ruta relativa a su base."""
        self.assertEqual(pyast.module_name("core/a.py"), ("core.a", False))
        self.assertEqual(pyast.module_name("core/__init__.py"), ("core", True))
        self.assertEqual(pyast.module_name("__init__.py"), ("", True))
        self.assertEqual(pyast.module_name("check.py"), ("check", False))


if __name__ == "__main__":
    unittest.main()

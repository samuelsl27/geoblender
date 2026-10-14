# SPDX-License-Identifier: GPL-3.0-or-later
"""La copia de pruebas de la extensión, compartida por las partes de «blender» y compilada
de antemano (``tools/gbtools/ext_copy.py``; spec 006, T48).

- RF-001-09: la copia es la de siempre de ``tools/run_blender_tests.py``: la extensión con
  las exclusiones del manifiesto, sin ``wheels/`` y con ``wheels = []`` en su manifiesto;
  copiarla otra vez sobre la misma carpeta la deja igual que el original.
- RNF-001-01, RNF-007-01: ``tools/check.py`` la prepara una vez, mientras corren las
  unitarias, para todas las partes de «blender»: cada parte se ahorraba copiarla, abrir
  cada fichero recién copiado por primera vez (el antivirus lo examina) y compilarla al
  habilitarla. Su código compilado va en ``pyc/`` con la disposición de
  ``sys.pycache_prefix`` (la ruta de cada fuente sin la unidad), válido para el
  intérprete en uso (número mágico y fecha y tamaño de la fuente).
"""

import importlib.machinery
import importlib.util
import os
import struct
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from tests.support.repo import tools_on_path

tools_on_path()

from gbtools import ext_copy, layout  # noqa: E402

SPDX = "# SPDX-License-Identifier: GPL-3.0-or-later\n"
MANIFEST = (
    'schema_version = "1.0.0"\n'
    "wheels = [\n"
    '  "./wheels/pyproj-3.8.0-cp313-cp313-win_amd64.whl",\n'
    "]\n\n"
    "[build]\n"
    'paths_exclude_pattern = ["__pycache__/", "*.py[cod]", "AGENTS.md"]\n'
)
EXT = layout.EXTENSION_DIR
SOURCES = {
    f"{EXT}/__init__.py": SPDX + "VALOR = 1\n",
    f"{EXT}/core/__init__.py": SPDX,
    f"{EXT}/core/calc.py": SPDX + "def doble(x):\n    return 2 * x\n",
    f"{EXT}/thirdparty/datos.bin": "binario",
    f"{EXT}/AGENTS.md": "reglas",
    f"{EXT}/core/__pycache__/calc.cpython-313.pyc": "basura",
    f"{EXT}/wheels/pyproj-3.8.0-cp313-cp313-win_amd64.whl": "rueda",
}


def _tree(root: Path) -> None:
    for rel, text in {**SOURCES, layout.MANIFEST_RELPATH: MANIFEST}.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _files(folder: Path) -> list[str]:
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())


class ExtensionCopyTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="gb-copia-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "repo"
        self.target = Path(tmp.name) / "copia"
        _tree(self.root)

    def test_copy_without_wheels_nor_excluded(self) -> None:
        """RF-001-09: la copia en ``<destino>/geoblender`` tiene la extensión sin lo que
        excluye el manifiesto, sin ``wheels/`` y con ``wheels = []``; lo demás del
        manifiesto, igual. Hacerla otra vez sobre la misma carpeta quita lo que sobra."""
        copy = ext_copy.make_copy(self.root, self.target)
        self.assertEqual(copy, self.target / ext_copy.EXTENSION_FOLDER)
        self.assertEqual(_files(copy), ["__init__.py", "blender_manifest.toml",
                                        "core/__init__.py", "core/calc.py",
                                        "thirdparty/datos.bin"])
        text = (copy / "blender_manifest.toml").read_text(encoding="utf-8")
        self.assertIn("wheels = []\n", text)
        self.assertNotIn("pyproj", text)
        self.assertIn('schema_version = "1.0.0"', text)
        (copy / "sobra.py").write_text(SPDX, encoding="utf-8")
        ext_copy.make_copy(self.root, self.target)
        self.assertFalse((copy / "sobra.py").exists())

    def test_bytecode_path_is_that_of_pycache_prefix(self) -> None:
        """RNF-001-01: la ruta del código compilado de una fuente es la que calcula
        ``importlib`` con ``sys.pycache_prefix``: el prefijo, la carpeta de la fuente sin
        la unidad y ``<nombre>.<etiqueta>.pyc``."""
        prefix = self.target / ext_copy.BYTECODE_FOLDER
        source = self.root / EXT / "core" / "calc.py"
        with mock.patch.object(sys, "pycache_prefix", str(prefix)):
            expected = importlib.util.cache_from_source(str(source))
        self.assertEqual(ext_copy.bytecode_path(prefix, source), Path(expected))

    def test_prepare_compiles_the_copy(self) -> None:
        """RNF-001-01, RNF-007-01: ``prepare`` deja la copia y su código compilado en
        ``pyc/``: un ``.pyc`` por fuente, con el número mágico del intérprete, validado por
        la fecha y el tamaño de la fuente de la copia, y que se ejecuta; devuelve el
        destino."""
        found = ext_copy.prepare(self.root, self.target)
        self.assertEqual(found, self.target)
        copy = self.target / ext_copy.EXTENSION_FOLDER
        prefix = self.target / ext_copy.BYTECODE_FOLDER
        sources = sorted(copy.rglob("*.py"))
        self.assertEqual(len(sources), 3)
        for source in sources:
            with self.subTest(fuente=source.name):
                data = ext_copy.bytecode_path(prefix, source).read_bytes()
                self.assertEqual(data[:4], importlib.util.MAGIC_NUMBER)
                flags, mtime, size = struct.unpack("<III", data[4:16])
                stat = source.stat()
                self.assertEqual((flags, mtime, size),
                                 (0, int(stat.st_mtime) & 0xFFFFFFFF, stat.st_size))
        compiled = ext_copy.bytecode_path(prefix, copy / "core" / "calc.py")
        loader = importlib.machinery.SourcelessFileLoader("gb_calc_compilado", str(compiled))
        module = types.ModuleType(loader.name)
        loader.exec_module(module)
        self.assertEqual(module.doble(21), 42)

    def test_prepare_with_a_broken_source_raises(self) -> None:
        """RNF-001-01: una fuente que no compila hace fallar ``prepare`` (check.py deja
        entonces que cada parte haga su copia, como antes)."""
        (self.root / EXT / "core" / "rota.py").write_text("def (\n", encoding="utf-8")
        with self.assertRaises(SyntaxError):
            ext_copy.prepare(self.root, self.target)
        self.assertTrue(os.path.isdir(self.target))


if __name__ == "__main__":
    unittest.main()

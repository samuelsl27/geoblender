# SPDX-License-Identifier: GPL-3.0-or-later
"""El código compilado de las órdenes de Python de ``tools/check.py``, fuera del repositorio
(``tools/gbtools/pyc_cache.py``; spec 005, T44).

- RNF-001-01: las órdenes de Python de la comprobación («unitarias», «referencia», «motor»…)
  van con ``-B`` (ningún ``__pycache__`` en el repositorio) y cada proceso compilaba en memoria
  todo lo que importaba: la extensión, las pruebas y las herramientas, y los módulos de la
  biblioteca de Python que Blender no trae compilados. :func:`refresh` deja ese código
  compilado en una carpeta de la temporal del sistema, una por raíz (:func:`default_folder`),
  con la disposición de ``PYTHONPYCACHEPREFIX``; las órdenes reciben esa variable y lo leen sin
  escribir nada.
- Lo del repositorio se valida por el hash de su fuente (``CHECKED_HASH``): una fuente
  cambiada, aunque conserve la fecha y el tamaño, se compila otra vez al importarla; lo del
  intérprete y de las carpetas de paquetes, por la fecha y el tamaño, como lo escribe Python.
- RF-001-09: nada se escribe junto a las fuentes; lo compilado de una fuente que ya no existe
  se borra, y también la carpeta de una raíz que ya no existe; de ``site-packages`` solo se
  compila lo que Blender trae compilado.
"""

import importlib.util
import os
import subprocess
import sys
import sysconfig
import tempfile
import unittest
from pathlib import Path

from tests.support.repo import ROOT, tools_on_path

tools_on_path()

from gbtools import ext_copy, layout, pyc_cache  # noqa: E402

SPDX = "# SPDX-License-Identifier: GPL-3.0-or-later\n"
TAG = sys.implementation.cache_tag


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _header(prefix: Path, source: Path) -> tuple[bytes, int, bytes]:
    """Número mágico, banderas y lo que valida el ``.pyc`` de ``source`` en ``prefix``."""
    data = ext_copy.bytecode_path(prefix, source).read_bytes()
    return data[:4], int.from_bytes(data[4:8], "little"), data[8:16]


def _files(folder: Path) -> list[str]:
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())


class _Folders(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="gb-pyc-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.tree = self.tmp / "arbol"
        self.prefix = self.tmp / "cache"
        self.sources = {
            "a": _write(self.tree / "a.py", SPDX + "VALOR = 1\n"),
            "b": _write(self.tree / "pkg" / "__init__.py", SPDX),
            "c": _write(self.tree / "pkg" / "c.py", SPDX + "def doble(x):\n    return 2 * x\n"),
        }
        _write(self.tree / "datos.txt", "no es Python")


class RefreshTest(_Folders):
    def test_compiles_each_source_outside_the_tree(self) -> None:
        """RNF-001-01, RF-001-09: cada ``.py`` del árbol queda compilado donde lo busca
        Python con ``PYTHONPYCACHEPREFIX`` (``ext_copy.bytecode_path``), validado por el hash
        de su fuente en un árbol del repositorio (``checked``) y por su fecha y tamaño en los
        demás; junto a las fuentes no se escribe nada."""
        before = _files(self.tree)
        found = pyc_cache.refresh(self.prefix, [pyc_cache.Tree(self.tree, checked=True)])
        self.assertEqual((found.compiled, found.fresh, found.removed, found.failed),
                         (3, 0, 0, []))
        self.assertEqual(_files(self.tree), before)
        for source in self.sources.values():
            with self.subTest(fuente=source.name):
                magic, flags, check = _header(self.prefix, source)
                self.assertEqual(magic, importlib.util.MAGIC_NUMBER)
                self.assertEqual(flags, 0b11)  # hash de la fuente, comprobado al importar
                self.assertEqual(check, importlib.util.source_hash(source.read_bytes()))
        other = self.tmp / "otro"
        _write(other / "d.py", SPDX)
        pyc_cache.refresh(self.prefix, [pyc_cache.Tree(other)])
        magic, flags, check = _header(self.prefix, other / "d.py")
        stat = (other / "d.py").stat()
        self.assertEqual(flags, 0)
        self.assertEqual(check, (int(stat.st_mtime) & 0xFFFFFFFF).to_bytes(4, "little")
                         + (stat.st_size & 0xFFFFFFFF).to_bytes(4, "little"))

    def test_only_what_changed_is_compiled_again(self) -> None:
        """RNF-001-01: otra vez sin cambios, nada se compila; una fuente del repositorio
        cambiada con la misma fecha y el mismo tamaño se compila otra vez (su hash), y una
        que ya no existe pierde su ``.pyc``."""
        trees = [pyc_cache.Tree(self.tree, checked=True)]
        pyc_cache.refresh(self.prefix, trees)
        again = pyc_cache.refresh(self.prefix, trees)
        self.assertEqual((again.compiled, again.fresh, again.removed), (0, 3, 0))
        source = self.sources["a"]
        stat = source.stat()
        source.write_text(SPDX + "VALOR = 2\n", encoding="utf-8")
        os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertEqual(source.stat().st_size, stat.st_size)
        changed = pyc_cache.refresh(self.prefix, trees)
        self.assertEqual((changed.compiled, changed.fresh), (1, 2))
        self.sources["c"].unlink()
        gone = pyc_cache.refresh(self.prefix, trees)
        self.assertEqual((gone.compiled, gone.fresh, gone.removed), (0, 2, 1))
        self.assertFalse(ext_copy.bytecode_path(self.prefix, self.sources["c"]).exists())

    def test_folders_skipped_and_only_precompiled(self) -> None:
        """RNF-001-01: las subcarpetas de ``skip`` no se recorren (``site-packages`` dentro de
        la biblioteca de Python) y, con ``precompiled_only``, solo se compila lo que ya tiene
        su ``.pyc`` junto a la fuente (lo que Blender trae compilado de ``site-packages``)."""
        _write(self.tree / "site-packages" / "x.py", SPDX)
        site = self.tmp / "site"
        used = _write(site / "usado.py", SPDX)
        _write(site / "__pycache__" / f"usado.{TAG}.pyc", "")
        unused = _write(site / "otro.py", SPDX)
        found = pyc_cache.refresh(self.prefix, [
            pyc_cache.Tree(self.tree, skip=("site-packages",)),
            pyc_cache.Tree(site, precompiled_only=True),
        ])
        self.assertEqual(found.compiled, 4)
        self.assertFalse(ext_copy.bytecode_path(
            self.prefix, self.tree / "site-packages" / "x.py").exists())
        self.assertTrue(ext_copy.bytecode_path(self.prefix, used).exists())
        self.assertFalse(ext_copy.bytecode_path(self.prefix, unused).exists())

    def test_a_broken_source_is_reported_and_the_rest_compiled(self) -> None:
        """RNF-001-01: una fuente que no compila no para el refresco (al importarla, Python
        dará su error, como sin la carpeta): se dice cuál y las demás se compilan."""
        broken = _write(self.tree / "rota.py", "def (\n")
        found = pyc_cache.refresh(self.prefix, [pyc_cache.Tree(self.tree, checked=True)])
        self.assertEqual(found.failed, [str(broken)])
        self.assertEqual(found.compiled, 3)
        self.assertFalse(ext_copy.bytecode_path(self.prefix, broken).exists())

    def test_a_child_python_reads_the_folder_without_writing(self) -> None:
        """RNF-001-01, RF-001-09: un Python hijo con ``-B`` y ``PYTHONPYCACHEPREFIX`` usa lo
        compilado: en un árbol validado por fecha y tamaño, una fuente cambiada sin cambiar ni
        la una ni el otro sigue dando lo compilado (lo lee); en uno del repositorio, por hash,
        da lo nuevo. No escribe nada, ni en la carpeta ni junto a las fuentes."""
        for checked, expected in ((False, "1"), (True, "2")):
            with self.subTest(hash=checked):
                tree = self.tmp / f"hijo-{int(checked)}"
                source = _write(tree / "modulo.py", SPDX + "VALOR = 1\n")
                prefix = self.tmp / f"cache-{int(checked)}"
                pyc_cache.refresh(prefix, [pyc_cache.Tree(tree, checked=checked)])
                stat = source.stat()
                source.write_text(SPDX + "VALOR = 2\n", encoding="utf-8")
                os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
                before = (_files(prefix), _files(tree))
                env = dict(os.environ, PYTHONPATH=str(tree),
                           **{pyc_cache.ENV_PREFIX: str(prefix)})
                env.pop("PYTHONDONTWRITEBYTECODE", None)
                result = subprocess.run(
                    [sys.executable, "-B", "-s", "-c", "import modulo; print(modulo.VALOR)"],
                    env=env, cwd=self.tmp, capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), expected)
                self.assertEqual((_files(prefix), _files(tree)), before)


class FoldersTest(_Folders):
    def test_default_folder_per_root(self) -> None:
        """RNF-001-01, RF-001-09: la carpeta está en la temporal del sistema, fuera del
        repositorio, y es una por raíz (cada clon o *worktree* tiene sus fuentes)."""
        default = pyc_cache.default_folder(ROOT)
        self.assertEqual(default.parent,
                         Path(tempfile.gettempdir()) / pyc_cache.STORE_FOLDER)
        self.assertEqual(default, pyc_cache.default_folder(Path(str(ROOT).upper())))
        self.assertNotEqual(default, pyc_cache.default_folder(ROOT / "otra"))
        self.assertFalse(str(default).lower().startswith(str(ROOT).lower()))

    def test_trees_of_a_root(self) -> None:
        """RNF-001-01: lo que se compila para una raíz: la extensión, las pruebas y las
        herramientas por el hash de su fuente; la biblioteca de Python del intérprete (sin
        ``site-packages``); de ``site-packages``, lo que trae compilado; ``.deps/site`` y las
        carpetas de paquetes que se den (la del motor de cálculo de pruebas)."""
        site = self.tmp / "motor" / "site"
        site.mkdir(parents=True)
        found = pyc_cache.trees(ROOT, [site])
        self.assertEqual(found, [
            pyc_cache.Tree(ROOT / layout.EXTENSION_DIR, checked=True),
            pyc_cache.Tree(ROOT / "tests", checked=True),
            pyc_cache.Tree(ROOT / "tools", checked=True),
            pyc_cache.Tree(Path(sysconfig.get_path("stdlib")), skip=(pyc_cache.SITE_PACKAGES,)),
            pyc_cache.Tree(Path(sysconfig.get_path("purelib")), precompiled_only=True),
            *([pyc_cache.Tree(ROOT / ".deps" / "site")]
              if (ROOT / ".deps" / "site").is_dir() else []),
            pyc_cache.Tree(site),
        ])

    def test_prepare_names_its_root_and_removes_those_of_missing_roots(self) -> None:
        """RNF-001-01, RF-001-09: ``prepare`` refresca la carpeta de una raíz, anota en ella
        qué raíz es y borra las carpetas de raíces que ya no existen (un *worktree* borrado);
        las de las demás, no."""
        store = self.tmp / "almacen"
        root = self.tmp / "raiz"
        for folder in pyc_cache.REPO_FOLDERS:
            _write(root / folder / "m.py", SPDX)
        gone = store / "a"
        _write(gone / pyc_cache.ROOT_FILE, str(self.tmp / "borrada"))
        _write(gone / "x.pyc", "")
        alive = store / "b"
        _write(alive / pyc_cache.ROOT_FILE, str(self.tree))
        folder = store / "c"
        found = pyc_cache.prepare(folder, root, [], interpreter=False)
        self.assertEqual(found.compiled, 3)
        self.assertEqual((folder / pyc_cache.ROOT_FILE).read_text(encoding="utf-8"), str(root))
        self.assertFalse(gone.exists())
        self.assertTrue(alive.exists())


if __name__ == "__main__":
    unittest.main()

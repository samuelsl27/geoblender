# SPDX-License-Identifier: GPL-3.0-or-later
"""Copia espejo de la extensión (``gbtools.sync``; plan 001 §5.4.5).

RF-001-28 y RF-001-09: la instalación de desarrollo y las pruebas de Blender trabajan
sobre una copia local de ``geoblender/`` hecha con las exclusiones del manifiesto, que
solo copia lo que ha cambiado, borra lo que sobra, nunca escribe fuera del destino y no
admite enlaces simbólicos en el origen (el repositorio vive en un recurso SMB).
"""

import os
import unittest
from pathlib import Path

from tests.support.repo import real_manifest, tools_on_path
from tests.support.resources import (
    SYMLINK,
    SYMLINK_HINT,
    WINDOWS,
    WINDOWS_HINT,
    skip_reason,
)
from tests.support.trees import temp_tree

tools_on_path()

from gbtools import manifest, sync  # noqa: E402
from gbtools.ignore import UnsupportedPattern  # noqa: E402


def _exclude() -> list[str]:
    """Las exclusiones reales del manifiesto (``AGENTS.md``, ``CLAUDE.md``,
    ``__pycache__/``, ``*.py[cod]``…), al usarlas y no al importar (T56)."""
    return manifest.exclude_patterns(real_manifest())


SOURCE = {
    "src/__init__.py": "# raíz\n",
    "src/AGENTS.md": "reglas\n",
    "src/CLAUDE.md": "@AGENTS.md\n",
    "src/core/__init__.py": "x = 1\n",
    "src/core/__pycache__/m.cpython-313.pyc": b"\x00\x01",
    "src/core/viejo.pyc": b"\x00",
    "src/bl/ui/AGENTS.md": "anidado\n",
    "src/bl/ui/__init__.py": "",
    "src/resources/escena.blend": b"BLENDER",
    "src/resources/escena.blend1": b"copia",
    "src/resources/escena.blend12": b"copia",
    "src/vacia/": "",
}
COPIED = [
    "__init__.py",
    "bl/ui/__init__.py",
    "core/__init__.py",
    "resources/escena.blend",
]


def _files(folder: Path) -> list[str]:
    """Ficheros bajo ``folder``, relativos y con «/», ordenados."""
    return sorted(
        path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file()
    )


def _dirs(folder: Path) -> list[str]:
    return sorted(
        path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_dir()
    )


class MirrorTest(unittest.TestCase):
    def test_copy_excludes(self) -> None:
        """RF-001-28: se copia todo salvo lo que excluye el manifiesto (también los
        ``AGENTS.md`` anidados, ``__pycache__``, ``.pyc`` y copias ``.blendN``)."""
        self.assertIn("AGENTS.md", _exclude())
        with temp_tree(SOURCE) as tmp:
            src, dst = tmp / "src", tmp / "dst"
            report = sync.mirror(src, dst, _exclude())
            self.assertEqual(_files(dst), COPIED)
            self.assertEqual(sorted(report.copied), COPIED)
            self.assertEqual(report.deleted, [])
            self.assertEqual(report.unchanged, 0)
            self.assertIn("vacia", _dirs(dst), "las carpetas vacías también se crean")
            self.assertNotIn("core/__pycache__", _dirs(dst))
            for rel in COPIED:
                with self.subTest(fichero=rel):
                    self.assertEqual((dst / rel).read_bytes(), (src / rel).read_bytes())
                    self.assertEqual(
                        (dst / rel).stat().st_mtime_ns, (src / rel).stat().st_mtime_ns
                    )

    def test_second_run_copies_nothing(self) -> None:
        """RF-001-28: una segunda pasada sin cambios no copia nada; un cambio de tamaño
        o de fecha se vuelve a copiar."""
        with temp_tree(SOURCE) as tmp:
            src, dst = tmp / "src", tmp / "dst"
            sync.mirror(src, dst, _exclude())
            again = sync.mirror(src, dst, _exclude())
            self.assertEqual(again.copied, [])
            self.assertEqual(again.deleted, [])
            self.assertEqual(again.unchanged, len(COPIED))

            (src / "core" / "__init__.py").write_text("x = 22\n", encoding="utf-8")
            stat = (src / "__init__.py").stat()
            os.utime(src / "__init__.py", ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))
            third = sync.mirror(src, dst, _exclude())
            self.assertEqual(sorted(third.copied), ["__init__.py", "core/__init__.py"])
            self.assertEqual(third.unchanged, len(COPIED) - 2)
            self.assertEqual((dst / "core" / "__init__.py").read_text("utf-8"), "x = 22\n")

    def test_deletes_extra(self) -> None:
        """RF-001-28: se borra del destino lo que ya no está en el origen o ahora está
        excluido; un fichero que pasa a carpeta (o al revés) se sustituye."""
        with temp_tree(SOURCE) as tmp:
            src, dst = tmp / "src", tmp / "dst"
            sync.mirror(src, dst, _exclude())
            (dst / "sobra.txt").write_text("x", encoding="utf-8")
            (dst / "core" / "sobra").mkdir()
            (dst / "core" / "sobra" / "a.py").write_text("", encoding="utf-8")
            (dst / "AGENTS.md").write_text("excluido", encoding="utf-8")
            (dst / "core" / "__pycache__").mkdir()
            (dst / "core" / "__pycache__" / "a.pyc").write_bytes(b"\x00")
            (src / "bl" / "ui" / "__init__.py").unlink()
            (src / "bl" / "ui" / "__init__.py").mkdir()  # ahora es una carpeta
            (dst / "resources" / "escena.blend").unlink()
            (dst / "resources" / "escena.blend").mkdir()  # en el destino, una carpeta

            report = sync.mirror(src, dst, _exclude())
            self.assertEqual(
                sorted(report.deleted),
                [
                    "AGENTS.md",
                    "bl/ui/__init__.py",
                    "core/__pycache__/",
                    "core/sobra/",
                    "resources/escena.blend/",
                    "sobra.txt",
                ],
            )
            self.assertEqual(report.copied, ["resources/escena.blend"])
            self.assertEqual(
                _files(dst), ["__init__.py", "core/__init__.py", "resources/escena.blend"]
            )
            self.assertTrue((dst / "bl" / "ui" / "__init__.py").is_dir())

    def test_symlink_source_rejected(self) -> None:
        """RF-001-28: un enlace simbólico o una unión en el origen es un error, y no se
        escribe nada en el destino."""
        with temp_tree(SOURCE) as tmp:
            src, dst = tmp / "src", tmp / "dst"
            try:
                os.symlink(src / "core" / "__init__.py", src / "enlace.py")
            except OSError:
                self.skipTest(skip_reason(SYMLINK, SYMLINK_HINT))
            with self.assertRaises(sync.SyncError) as ctx:
                sync.mirror(src, dst, _exclude())
            self.assertIn("enlace.py", str(ctx.exception))
            self.assertFalse(dst.exists())

    @unittest.skipUnless(os.name == "nt", skip_reason(WINDOWS, WINDOWS_HINT))
    def test_junction_source_rejected(self) -> None:
        """RF-001-28: una unión de Windows en el origen tampoco se sigue."""
        import _winapi

        with temp_tree({**SOURCE, "fuera/dato.txt": "x"}) as tmp:
            src, dst = tmp / "src", tmp / "dst"
            _winapi.CreateJunction(str(tmp / "fuera"), str(src / "core" / "union"))
            with self.assertRaises(sync.SyncError) as ctx:
                sync.mirror(src, dst, _exclude())
            self.assertIn("core/union", str(ctx.exception))
            self.assertFalse(dst.exists())

    def test_link_in_destination_removed_not_followed(self) -> None:
        """RF-001-28: un enlace en el destino se quita sin tocar aquello a lo que
        apunta (nunca se escribe fuera del destino)."""
        with temp_tree({**SOURCE, "fuera/dato.txt": "x"}) as tmp:
            src, dst = tmp / "src", tmp / "dst"
            sync.mirror(src, dst, _exclude())
            try:
                os.symlink(tmp / "fuera", dst / "enlace", target_is_directory=True)
            except OSError:
                self.skipTest(skip_reason(SYMLINK, SYMLINK_HINT))
            report = sync.mirror(src, dst, _exclude())
            self.assertEqual(report.deleted, ["enlace"])
            self.assertFalse(os.path.lexists(dst / "enlace"))
            self.assertEqual((tmp / "fuera" / "dato.txt").read_text("utf-8"), "x")

    def test_nested_folders_rejected(self) -> None:
        """RF-001-28: destino dentro del origen, origen dentro del destino o el mismo
        sitio: error sin escribir ni borrar nada."""
        with temp_tree(SOURCE) as tmp:
            src = tmp / "src"
            before = _files(tmp)
            for dst in (src, src / "copia", tmp):
                with self.subTest(destino=dst), self.assertRaises(sync.SyncError):
                    sync.mirror(src, dst, _exclude())
            self.assertEqual(_files(tmp), before)

    def test_bad_source_or_pattern(self) -> None:
        """RF-001-28: origen inexistente y patrón con «!»: error y nada escrito."""
        with temp_tree(SOURCE) as tmp:
            dst = tmp / "dst"
            with self.assertRaises(sync.SyncError):
                sync.mirror(tmp / "no-existe", dst, _exclude())
            with self.assertRaises(UnsupportedPattern):
                sync.mirror(tmp / "src", dst, ["*.py", "!a.py"])
            self.assertFalse(dst.exists())

    def test_report_type(self) -> None:
        """RF-001-28: ``SyncReport`` con ``copied``, ``deleted`` y ``unchanged``."""
        report = sync.SyncReport(copied=["a"], deleted=[], unchanged=2)
        self.assertEqual((report.copied, report.deleted, report.unchanged), (["a"], [], 2))


if __name__ == "__main__":
    unittest.main()

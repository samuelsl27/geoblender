# SPDX-License-Identifier: GPL-3.0-or-later
"""Cadena de los iconos propios (spec 003, T30; RF-003-22; RNF-003-09; II §1.6 y §1.7):
``tools/build_icons.py`` y ``gbtools.icons``, sin Blender.

- II §1.6, 1: una fuente válida no tiene problemas; una con texto y una referencia externa
  se rechaza con sus motivos, y sin los metadatos CC0 (§1.7), también. Con una fuente no
  válida, generar se detiene sin lanzar Blender ni escribir nada.
- II §1.6, 2–4: generar (con un Blender simulado que escribe los PNG) deja los dos PNG de
  cada fuente y el manifiesto con sus sha256 y la versión de Blender, y borra los PNG sin
  fuente.
- II §1.6, 5 (RNF-003-09): ``--check`` pasa con todo en orden y falla si se toca una
  fuente sin regenerar, si sobra un PNG, si falta uno, si un PNG no mide lo que debe o
  pasa de 8 KB; y no importa ``bpy`` (el módulo no lo importa y la comprobación se ejecuta
  aquí, fuera de Blender).
- Sin fuentes ni PNG no hay nada que comprobar.

El rasterizado de verdad, dentro de Blender, lo prueba
``tests/blender/test_rasterize_icons.py``.
"""

import ast
import contextlib
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path

from tests.support import icon_fixtures
from tests.support.repo import ROOT, TOOLS_DIR, tools_on_path

tools_on_path()

import build_icons  # noqa: E402
from gbtools import icons  # noqa: E402
from gbtools.blender import BlenderInstall  # noqa: E402

INSTALL = BlenderInstall(exe=Path("blender.exe"), python=Path("python.exe"), version=(5, 2, 1))


class FakeBlender:
    """Hace de Blender: escribe los PNG de cada fuente (de 32 y 64 px) y termina bien."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, cmd: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        args = [str(part) for part in cmd]
        self.calls.append(args)
        sources = Path(args[args.index("--fuentes") + 1])
        output = Path(args[args.index("--salida") + 1])
        for svg in sorted(sources.glob("*.svg")):
            for size in icons.SIZES:
                (output / f"{svg.stem}_{size}.png").write_bytes(
                    icon_fixtures.png_bytes(size, size))
        return subprocess.CompletedProcess(args, 0, f"{build_icons.END_LINE} 1 iconos\n", "")


def _no_blender(*_args: object, **_kwargs: object) -> object:
    raise AssertionError("no se tenía que lanzar Blender")


class IconsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="gb-iconos-prueba-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.svg_dir = self.work / "fuentes"
        self.png_dir = self.work / "salida"
        self.svg_dir.mkdir()

    def write_svg(self, name: str, text: str) -> Path:
        path = self.svg_dir / f"{name}.svg"
        path.write_bytes(text.encode("utf-8"))
        return path

    def run_main(self, *args: str, runner: object = _no_blender) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = build_icons.main(
                [*args, "--fuentes", str(self.svg_dir), "--salida", str(self.png_dir)],
                root=ROOT, runner=runner, locate=lambda _minimum: INSTALL)
        return code, out.getvalue()

    def generate(self) -> FakeBlender:
        fake = FakeBlender()
        code, output = self.run_main(runner=fake)
        self.assertEqual(code, 0, output)
        return fake

    def test_valid_and_invalid_sources(self) -> None:
        """II §1.6, 1 y §1.7: la válida, sin problemas; la de texto y referencia externa y
        la que no lleva los metadatos CC0, rechazadas con su motivo."""
        self.assertEqual(icons.svg_problems(self.write_svg("gb_test_valid",
                                                           icon_fixtures.VALID_SVG)), [])
        problems = icons.svg_problems(self.write_svg("gb_test_bad", icon_fixtures.INVALID_SVG))
        text = "\n".join(problems)
        self.assertIn("texto", text)
        self.assertIn("referencia externa", text)
        bare = icons.svg_problems(self.write_svg("gb_test_bare",
                                                 icon_fixtures.WITHOUT_LICENSE_SVG))
        self.assertEqual(len(bare), 3, bare)
        self.assertTrue(all("metadata" in problem for problem in bare))
        wrong_name = icons.svg_problems(self.write_svg("Logo", icon_fixtures.VALID_SVG))
        self.assertEqual(len(wrong_name), 1)

    def test_invalid_source_stops_generation(self) -> None:
        """II §1.6, 1: con una fuente no válida no se lanza Blender ni se escribe nada."""
        self.write_svg("gb_test_valid", icon_fixtures.VALID_SVG)
        self.write_svg("gb_test_bad", icon_fixtures.INVALID_SVG)
        code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("gb_test_bad.svg", output)
        self.assertFalse(self.png_dir.exists() and any(self.png_dir.iterdir()))

    def test_generate_and_check(self) -> None:
        """II §1.6, 2–5: dos PNG por fuente, el manifiesto y ``--check`` en verde; los PNG
        sin fuente se borran."""
        self.write_svg("gb_test_valid", icon_fixtures.VALID_SVG)
        self.png_dir.mkdir()
        (self.png_dir / "gb_old_icon_32.png").write_bytes(icon_fixtures.png_bytes(32, 32))
        fake = self.generate()
        self.assertEqual(len(fake.calls), 1)
        self.assertIn("--python-exit-code", fake.calls[0])
        self.assertEqual(sorted(path.name for path in self.png_dir.iterdir()),
                         ["gb_test_valid_32.png", "gb_test_valid_64.png", "manifest.json"])
        manifest = (self.png_dir / "manifest.json").read_text(encoding="utf-8")
        self.assertIn('"blender": "5.2.1"', manifest)
        self.assertIn(icons.sha256_file(self.svg_dir / "gb_test_valid.svg"), manifest)
        code, output = self.run_main("--check")
        self.assertEqual(code, 0, output)

    def test_check_detects_drift(self) -> None:
        """RNF-003-09: ``--check`` falla si la fuente cambió sin regenerar, si sobra o
        falta un PNG, si mide otra cosa o pasa de 8 KB."""
        svg = self.write_svg("gb_test_valid", icon_fixtures.VALID_SVG)
        self.generate()
        svg.write_bytes(svg.read_bytes() + b"<!-- tocado -->\n")
        code, output = self.run_main("--check")
        self.assertEqual(code, 1)
        self.assertIn("no se han regenerado", output)
        self.generate()
        extra = self.png_dir / "gb_test_extra_32.png"
        extra.write_bytes(icon_fixtures.png_bytes(32, 32))
        code, output = self.run_main("--check")
        self.assertEqual(code, 1)
        self.assertIn("sobra gb_test_extra_32.png", output)
        extra.unlink()
        small = self.png_dir / "gb_test_valid_64.png"
        small.write_bytes(icon_fixtures.png_bytes(32, 32))
        problems = icons.check_problems(self.svg_dir, self.png_dir)
        self.assertTrue(any("no es el del manifiesto" in problem for problem in problems))
        self.assertTrue(any("no 64 × 64" in problem for problem in problems))
        small.unlink()
        self.assertIn("falta gb_test_valid_64.png", icons.check_problems(self.svg_dir,
                                                                         self.png_dir))
        big = self.png_dir / "gb_test_valid_32.png"
        big.write_bytes(icon_fixtures.png_bytes(32, 32) + b"\x00" * icons.MAX_PNG_BYTES)
        self.assertTrue(any("bytes" in problem
                            for problem in icons.check_problems(self.svg_dir, self.png_dir)))

    def test_nothing_to_check(self) -> None:
        """Sin fuentes ni PNG, ``--check`` pasa."""
        code, output = self.run_main("--check")
        self.assertEqual(code, 0, output)

    def test_check_without_bpy(self) -> None:
        """II §1.6, 5: ni el lanzador ni ``gbtools.icons`` importan ``bpy``, y la
        comprobación se ejecuta fuera de Blender."""
        for path in (TOOLS_DIR / "build_icons.py", TOOLS_DIR / "gbtools" / "icons.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported = {alias.name.split(".")[0] for node in ast.walk(tree)
                        if isinstance(node, ast.Import) for alias in node.names}
            imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree)
                         if isinstance(node, ast.ImportFrom)}
            self.assertNotIn("bpy", imported, path.name)
        self.assertNotIn("bpy", sys.modules)

    def test_png_reader(self) -> None:
        """La cabecera y los píxeles de un PNG sintético."""
        path = self.work / "uno.png"
        path.write_bytes(icon_fixtures.png_bytes(3, 2, (1, 2, 3, 4)))
        self.assertEqual(icons.png_size(path), (3, 2))
        width, height, rows = icon_fixtures.png_rgba(path.read_bytes())
        self.assertEqual((width, height, rows[1][:4]), (3, 2, bytes((1, 2, 3, 4))))


if __name__ == "__main__":
    unittest.main()

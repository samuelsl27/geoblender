# SPDX-License-Identifier: GPL-3.0-or-later
"""Rasterizado de los iconos dentro de Blender (spec 003, T30; RF-003-22; RNF-003-09; plan
003 §5.4, 12; II §1.6, 2–4; ``tools/inblender/rasterize_icons.py``).

- II §1.6: una fuente válida da sus dos PNG, de 32 y 64 px, RGBA de 8 bits y ≤ 8 KB
  (RNF-003-09), leídos sin Blender (``tests.support.icon_fixtures.png_rgba``): el dibujo
  no sale volteado (el cuadrado gris claro arriba a la izquierda y la marca azul abajo a la
  derecha), los colores se conservan (``#E6E6E6`` → 230 ± 2) y el fondo es transparente.
- La reducción es un filtro de caja en alfa premultiplicada: un borde a medio píxel da un
  alfa intermedio con el color sin oscurecer.

Se ejecuta con ``tools/run_blender_tests.py`` (que pone ``tools/`` en ``sys.path``).
"""

import importlib
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

from tests.support import icon_fixtures

rasterize_icons = importlib.import_module("inblender.rasterize_icons")


def pixel(rows: list[bytes], x: int, y: int) -> tuple[int, ...]:
    return tuple(rows[y][4 * x:4 * x + 4])


class RasterizeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="gb-iconos-blender-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.svg = self.work / "gb_test_valid.svg"
        self.svg.write_bytes(icon_fixtures.VALID_SVG.encode("utf-8"))

    def test_valid_source_gives_two_pngs(self) -> None:
        """II §1.6: dos PNG RGBA de 8 bits, de 32 y 64 px, ≤ 8 KB, sin voltear y con su
        color."""
        written = rasterize_icons.rasterize(self.svg, self.work)
        self.assertEqual([path.name for path in written],
                         ["gb_test_valid_32.png", "gb_test_valid_64.png"])
        for path, size in zip(written, (32, 64), strict=True):
            with self.subTest(png=path.name):
                self.assertLessEqual(path.stat().st_size, 8 * 1024)
                width, height, rows = icon_fixtures.png_rgba(path.read_bytes())
                self.assertEqual((width, height), (size, size))
                quarter = size // 4
                grey = pixel(rows, quarter, quarter)  # arriba a la izquierda
                for value in grey[:3]:
                    self.assertAlmostEqual(value, 230, delta=2)
                self.assertEqual(grey[3], 255)
                blue = pixel(rows, size - 2, size - 2)  # abajo a la derecha
                self.assertEqual(blue[3], 255)
                self.assertGreater(blue[2], blue[0])
                self.assertEqual(pixel(rows, size - 2, 1)[3], 0)  # arriba a la derecha
                self.assertEqual(pixel(rows, 1, size - 2)[3], 0)  # abajo a la izquierda

    def test_box_filter_premultiplied(self) -> None:
        """La reducción promedia en alfa premultiplicada: medio bloque blanco y medio
        transparente (de color negro) da alfa 0,5 y blanco, no gris."""
        source = np.zeros((4, 4, 4), dtype=np.float32)
        source[:, :2] = (1.0, 1.0, 1.0, 1.0)
        reduced = rasterize_icons.downscale(source, 1)
        np.testing.assert_allclose(reduced[0, 0], (1.0, 1.0, 1.0, 0.5), atol=1e-6)
        with self.assertRaises(ValueError):
            rasterize_icons.downscale(source, 3)


if __name__ == "__main__":
    unittest.main()

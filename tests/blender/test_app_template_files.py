# SPDX-License-Identifier: GPL-3.0-or-later
"""Los ficheros de la plantilla de aplicación (spec 003, T34; RF-003-25; CW §7; plan 003
§5.4, 13; ``tools/inblender/make_app_template_blend.py``).

- La imagen de bienvenida se rasteriza con el rasterizador propio del subconjunto de SVG
  de Geoblender: un rectángulo relleno, un trazo con extremos redondeados y antialias, un
  polígono relleno par-impar y opacidades; trazados con órdenes absolutas y relativas.
- La de la plantilla (``assets/splash/splash.svg``) da 1000 × 500 con el fondo
  ``#1F2327`` y el logotipo claro; las de ``packaging/`` miden 1000 × 500 y 2000 × 1000.
- El ``startup.blend`` de la plantilla, con la extensión habilitada: el espacio principal
  de Geoblender (marcado, con la barra N cerrada como en ``geoblender_ui.blend``; T46) y
  «Layout» (sin marcar), sin objetos, en metros.

Se ejecuta con ``tools/run_blender_tests.py`` (que pone ``tools/`` en ``sys.path``).
"""

import importlib
import struct
import tomllib
import unittest
from pathlib import Path

import bpy
import numpy as np

from tests.support import blender_ext
from tests.support.repo import ROOT

maker = importlib.import_module("inblender.make_app_template_blend")
layout = importlib.import_module("gbtools.layout")

TEMPLATE = ROOT / layout.APP_TEMPLATE_RELPATH
SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
<rect x="0" y="0" width="10" height="10" fill="#FF0000"/>
<line x1="2" y1="2" x2="8" y2="2" stroke="#FFFFFF" stroke-width="2.25" stroke-linecap="round"/>
<polygon points="2,5 8,5 8,9 2,9" fill="#0000FF" fill-opacity="0.5" stroke="none"/>
<path d="m 1 4 h 2 v 1 Z" stroke="#00FF00" stroke-width="0.5" fill="none"/>
</svg>"""


def main_workspace() -> str:
    """El espacio principal de ``layouts.toml`` (como ``tools/make_app_template.py``, que
    no se importa aquí: al importarse apaga la caché de código compilado de la sesión)."""
    data = tomllib.loads((ROOT / layout.LAYOUTS_TOML_RELPATH).read_text(encoding="utf-8"))
    return next(str(item["workspace"]) for item in data["layout"] if item.get("main"))


def png_size(path: Path) -> tuple[int, int]:
    """(ancho, alto) de la cabecera IHDR de un PNG."""
    data = path.read_bytes()[:24]
    return struct.unpack(">II", data[16:24])


class RasterTest(unittest.TestCase):
    def test_synthetic_svg(self) -> None:
        """Relleno, trazo redondeado con antialias, polígono semitransparente."""
        rgba = maker.rasterize_svg(SVG, 4.0)  # 40 × 40, de arriba abajo
        self.assertEqual(rgba.shape, (40, 40, 4))
        np.testing.assert_allclose(rgba[38, 1], (1.0, 0.0, 0.0, 1.0), atol=1e-6)
        np.testing.assert_allclose(rgba[8, 20], (1.0, 1.0, 1.0, 1.0), atol=1e-6)  # el trazo
        self.assertEqual(tuple(rgba[8, 5][:3]), (1.0, 1.0, 1.0))  # extremo redondeado
        edge = rgba[12, 20]  # el borde del trazo (y = 3,125) pasa por el centro del píxel
        self.assertAlmostEqual(edge[1], 0.5, places=6)
        np.testing.assert_allclose(rgba[28, 20][:3], (0.5, 0.0, 0.5), atol=1e-6)  # mitad
        self.assertEqual(maker.parse_path("m 1 4 h 2 v 1 Z"),
                         (((1.0, 4.0), (3.0, 4.0), (3.0, 5.0), (1.0, 4.0)),))
        self.assertEqual(maker.parse_path("M 0 0 L 1 1 2 2"),
                         (((0.0, 0.0), (1.0, 1.0), (2.0, 2.0)),))

    def test_downscale(self) -> None:
        """La reducción a la mitad promedia en alfa premultiplicada."""
        rgba = np.zeros((2, 2, 4))
        rgba[0, 0] = (1.0, 1.0, 1.0, 1.0)
        small = maker.downscale(rgba, 2)
        np.testing.assert_allclose(small[0, 0], (1.0, 1.0, 1.0, 0.25))

    def test_splash(self) -> None:
        """CW §7: la imagen de bienvenida de 1000 × 500, fondo oscuro y logotipo claro;
        las de la plantilla, de 1000 × 500 y 2000 × 1000."""
        text = (ROOT / layout.SPLASH_SVG_RELPATH).read_text(encoding="utf-8")
        rgba = maker.rasterize_svg(text, 1.0)
        self.assertEqual(rgba.shape, (500, 1000, 4))
        np.testing.assert_allclose(rgba[2, 2], (0x1F / 255, 0x23 / 255, 0x27 / 255, 1.0),
                                   atol=1e-6)
        self.assertGreater(rgba[80:90, 95:105, :3].mean(), 0.8)  # el logotipo, claro
        self.assertEqual(png_size(TEMPLATE / "splash.png"), maker.SPLASH_SIZE)
        self.assertEqual(png_size(TEMPLATE / "splash_2x.png"),
                         tuple(2 * value for value in maker.SPLASH_SIZE))


class StartupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.unload()
        blender_ext.load_file()
        blender_ext.enable()

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.load_file()
        blender_ext.unload()

    def test_startup_blend(self) -> None:
        """RF-003-25: el espacio principal (marcado) y «Layout», sin objetos, en metros."""
        blender_ext.load_file(TEMPLATE / "startup.blend")
        main = main_workspace()
        marks = {ws.name: bool(ws.geoblender_mode) for ws in bpy.data.workspaces}
        self.assertEqual(marks, {main: True, maker.FALLBACK_WORKSPACE: False})
        views = [space for area in bpy.data.workspaces[main].screens[0].areas
                 for space in area.spaces if space.type == "VIEW_3D"]
        self.assertEqual(len(views), 1)  # la del principal de geoblender_ui.blend: la
        self.assertFalse(views[0].show_region_ui)  # barra N cerrada (T46; RNF-003-03)
        self.assertEqual(len(bpy.data.objects), 0)
        self.assertEqual(len(bpy.data.libraries), 0)
        for scene in bpy.data.scenes:
            self.assertEqual((scene.unit_settings.system, scene.unit_settings.length_unit,
                              scene.unit_settings.scale_length), ("METRIC", "METERS", 1.0))


if __name__ == "__main__":
    unittest.main()

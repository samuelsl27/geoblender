# SPDX-License-Identifier: GPL-3.0-or-later
"""El Blender y el numpy con los que se ejecuta la extensión (plan 001 §5.4.9).

- RF-001-07: la versión de Blender, leída a través de ``bl.compat``, no es anterior a
  ``blender_version_min`` del manifiesto.
- RF-001-03 (ADR-0009): con la extensión habilitada, numpy es el 2.3.4 que trae Blender,
  cargado desde su instalación y no desde ninguna carpeta de extensiones (la extensión
  nunca empaqueta numpy). Si una versión de Blender cambia su numpy, esta prueba es la
  alarma que pide ADR-0009.

Se ejecuta con ``tools/run_blender_tests.py``, que instala la copia de pruebas.
"""

import importlib
import unittest
from pathlib import Path

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.repo import ROOT, tools_on_path

tools_on_path()

from gbtools import manifest  # noqa: E402

BLENDER_NUMPY = "2.3.4"  # numpy de Blender 5.2 (ADR-0009)


class EnvironmentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.enterContext(blender_ext.fresh())

    def test_blender_at_least_manifest_min(self) -> None:
        """RF-001-07: ``bl.compat.blender_version()`` es la versión de Blender, como tupla
        de tres enteros, y no es anterior al mínimo del manifiesto."""
        blender_ext.import_root()
        compat = importlib.import_module(module_name() + ".bl.compat")
        version = compat.blender_version()
        self.assertIsInstance(version, tuple)
        self.assertEqual(len(version), 3)
        self.assertTrue(all(isinstance(part, int) for part in version))
        self.assertEqual(version, tuple(bpy.app.version))
        minimum = manifest.blender_min(manifest.load(ROOT / manifest.MANIFEST_RELPATH))
        self.assertGreaterEqual(version, minimum)

    def test_numpy_is_blenders(self) -> None:
        """RF-001-03 (ADR-0009): con la extensión habilitada, numpy es el de Blender."""
        blender_ext.enable()
        import numpy

        self.assertEqual(numpy.__version__, BLENDER_NUMPY)
        numpy_file = Path(numpy.__file__).resolve()
        blender_dir = Path(bpy.app.binary_path).resolve().parent
        self.assertTrue(
            numpy_file.is_relative_to(blender_dir),
            f"numpy viene de «{numpy_file}», fuera de «{blender_dir}»",
        )
        self.assertNotIn(
            "extensions",
            [part.lower() for part in numpy_file.relative_to(blender_dir).parts],
            "numpy no puede venir de una carpeta de extensiones",
        )

    def test_test_copy_without_wheels(self) -> None:
        """RNF-001-01 (spec 006, T11): la copia de pruebas va sin ``wheels/`` y con
        ``wheels = []`` (con ruedas, Blender instalaría y quitaría pyproj en cada habilitar
        y deshabilitar), y lo demás de la extensión sí está (``thirdparty/proj/``)."""
        copy = Path(blender_ext.import_root().__file__).resolve().parent
        self.assertFalse((copy / "wheels").exists())
        copied = manifest.load(copy / "blender_manifest.toml")
        self.assertEqual(manifest.wheel_files(copied), [])
        self.assertTrue((copy / "thirdparty" / "proj" / "es_ign_SPED2ETV2.tif").is_file())


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: GPL-3.0-or-later
"""Opciones del lanzador de las pruebas de Blender (``tools/run_blender_tests.py``),
sin Blender (spec 003, T40).

- RNF-007-01, RF-001-06: ``--parte i/n`` ejecuta solo la parte i de n de las pruebas
  descubiertas (``gbtools.parts``), para que ``tools/check.py`` reparta las de Blender
  en varios Blender a la vez; sin ella, todas, como siempre.
- RF-001-07: una parte que no es «i/n» con 1 ≤ i ≤ n es un error de uso (código 2).
- RNF-001-01, RNF-007-01 (spec 004, T39): ``--tiempos`` y ``--medidas`` dan los ficheros
  con que la parte reparte por tiempo y en que escribe la duración de sus módulos.
- RNF-001-01, RNF-007-01 (spec 006, T48): ``--copia`` da la copia de la extensión que
  prepara ``tools/check.py`` para todas las partes.

Lo que hace dentro de Blender con la parte (la línea «PARTE i de n: …» y solo sus
pruebas) lo prueba ``tests/arnes/test_harness_blender.py`` con el Blender real y, en
cada comprobación, ``tools/check.py`` al cuadrar las partes del paso «blender».
"""

import unittest

from tests.support.repo import ROOT, tools_on_path

tools_on_path()

import run_blender_tests  # noqa: E402
from gbtools import ext_copy, parts  # noqa: E402


class PartOptionTest(unittest.TestCase):
    def test_without_part_runs_everything(self) -> None:
        """RF-001-06: sin ``--parte``, la carpeta y el patrón de siempre y ninguna
        parte."""
        options = run_blender_tests.parse_args([])
        self.assertEqual(options.folder, ROOT / "tests" / "blender")
        self.assertEqual(options.pattern, "test_*.py")
        self.assertIsNone(options.part)

    def test_part(self) -> None:
        """RNF-007-01: ``--parte 2/3`` y ``--parte=2/3``, con las demás opciones."""
        for args in (
            ["--carpeta", "tests/blender", "--parte", "2/3"],
            ["--parte=2/3", "--carpeta", "tests/blender"],
        ):
            with self.subTest(argumentos=args):
                options = run_blender_tests.parse_args(args)
                self.assertEqual(options.part, (2, 3))
                self.assertEqual(options.folder, ROOT / "tests" / "blender")
        self.assertEqual(run_blender_tests.PART_OPTION, parts.OPTION)

    def test_invalid_part(self) -> None:
        """RF-001-07: una parte que no es «i/n» con 1 ≤ i ≤ n, o sin valor, es un error
        de uso que dice el formato."""
        for args in (["--parte", "0/2"], ["--parte", "3/2"], ["--parte", "x"], ["--parte"]):
            with self.subTest(argumentos=args):
                with self.assertRaises(run_blender_tests.UsageError) as caught:
                    run_blender_tests.parse_args(args)
                self.assertIn("--parte", str(caught.exception))

    def test_times_and_measures(self) -> None:
        """RNF-001-01, RNF-007-01 (spec 004, T39): ``--tiempos`` y ``--medidas`` dan el
        fichero con la duración de cada módulo (para repartir por tiempo) y el de las
        medidas de la parte (una ruta relativa, desde la raíz); sin ellas, ninguno; sin
        valor, un error de uso."""
        absolute = ROOT.parent / "tiempos.json"
        options = run_blender_tests.parse_args(
            ["--parte", "2/3", "--tiempos", str(absolute), "--medidas=medidas.json"]
        )
        self.assertEqual(options.times, absolute)
        self.assertEqual(options.measures, ROOT / "medidas.json")
        self.assertEqual(options.part, (2, 3))
        plain = run_blender_tests.parse_args(["--parte", "2/3"])
        self.assertIsNone(plain.times)
        self.assertIsNone(plain.measures)
        self.assertEqual(run_blender_tests.TIMES_OPTION, parts.TIMES_OPTION)
        self.assertEqual(run_blender_tests.MEASURES_OPTION, parts.MEASURES_OPTION)
        for args in (["--tiempos"], ["--medidas", "--parte", "1/2"]):
            with self.subTest(argumentos=args):
                with self.assertRaises(run_blender_tests.UsageError):
                    run_blender_tests.parse_args(args)

    def test_shared_copy(self) -> None:
        """RNF-001-01, RNF-007-01 (spec 006, T48): ``--copia DIR`` da la copia de la
        extensión que preparó ``tools/check.py`` para todas las partes (una ruta relativa,
        desde la raíz); sin ella, ninguna (cada lanzador hace la suya); sin valor, un error
        de uso. Su código compilado va en la carpeta de la copia que espera
        ``gbtools.ext_copy``."""
        absolute = ROOT.parent / "copia"
        options = run_blender_tests.parse_args(["--parte", "1/5", "--copia", str(absolute)])
        self.assertEqual(options.copy, absolute)
        self.assertEqual(run_blender_tests.parse_args(["--copia=c"]).copy, ROOT / "c")
        self.assertIsNone(run_blender_tests.parse_args([]).copy)
        with self.assertRaises(run_blender_tests.UsageError):
            run_blender_tests.parse_args(["--copia"])
        self.assertEqual(run_blender_tests.COPY_OPTION, "--copia")
        self.assertEqual(run_blender_tests.BYTECODE_DIR, ext_copy.BYTECODE_FOLDER)
        self.assertEqual(run_blender_tests.EXTENSION_ID, ext_copy.EXTENSION_FOLDER)


if __name__ == "__main__":
    unittest.main()

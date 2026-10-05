# SPDX-License-Identifier: GPL-3.0-or-later
"""Ficheros de prueba en disco frente a módulos que ``unittest`` cargó
(``tools/gbtools/discovery.py``; RF-001-06; convergencia de la spec 001, T35).

``tools/check.py`` y ``tools/run_blender_tests.py`` lo usan para no dar verde cuando
``unittest discover`` deja sin cargar, sin avisar, un fichero de pruebas (p. ej. en una
carpeta sin ``__init__.py``).
"""

import unittest

from tests.support.repo import ROOT, tools_on_path
from tests.support.trees import temp_tree

tools_on_path()

from gbtools import discovery  # noqa: E402

SPDX = "# SPDX-License-Identifier: GPL-3.0-or-later\n"


class ExpectedModulesTest(unittest.TestCase):
    def test_pattern_and_depth(self) -> None:
        """RF-001-06: los ``.py`` de la carpeta, a cualquier profundidad, cuyo nombre casa
        el patrón como en ``unittest`` (``fnmatch`` sin distinguir mayúsculas en Windows),
        con su módulo relativo a la carpeta superior; sin ``__pycache__``; los nombres que
        no son un módulo válido también cuentan (``unittest`` los salta sin avisar)."""
        files = {
            "tests/unit/__init__.py": SPDX,
            "tests/unit/test_a.py": SPDX,
            "tests/unit/ayuda.py": SPDX,
            "tests/unit/sub/test_b.py": SPDX,
            "tests/unit/sub/deep/test_c.py": SPDX,
            "tests/unit/test-guion.py": SPDX,
            "tests/unit/test_datos.csv": "x\n",
            "tests/unit/__pycache__/test_a.py": SPDX,
        }
        with temp_tree(files) as root:
            found = discovery.expected_modules(root / "tests" / "unit", "test*.py", root)
        self.assertEqual(
            found,
            {
                "tests.unit.sub.deep.test_c": "tests/unit/sub/deep/test_c.py",
                "tests.unit.sub.test_b": "tests/unit/sub/test_b.py",
                "tests.unit.test-guion": "tests/unit/test-guion.py",
                "tests.unit.test_a": "tests/unit/test_a.py",
            },
        )

    def test_launcher_pattern_and_missing_folder(self) -> None:
        """RF-001-06: con ``perf_*.py`` solo cuentan esos; una carpeta que no existe no
        tiene ficheros."""
        files = {"r/blender/perf_x.py": SPDX, "r/blender/test_y.py": SPDX}
        with temp_tree(files) as root:
            found = discovery.expected_modules(root / "r" / "blender", "perf_*.py", root)
            missing = discovery.expected_modules(root / "no-existe", "test*.py", root)
        self.assertEqual(found, {"r.blender.perf_x": "r/blender/perf_x.py"})
        self.assertEqual(missing, {})

    def test_real_unit_folder(self) -> None:
        """RF-001-06: en el repositorio real, ``tests/unit`` tiene esta misma prueba."""
        found = discovery.expected_modules(ROOT / "tests" / "unit", "test*.py", ROOT)
        self.assertEqual(
            found["tests.unit.tools.test_discovery"], "tests/unit/tools/test_discovery.py"
        )


class LoadedModulesTest(unittest.TestCase):
    def test_heads_of_verbose_output(self) -> None:
        """RF-001-06: los módulos que nombran las cabeceras de ``unittest -v`` (prueba con
        y sin docstring, ``setUpClass`` y ``setUpModule`` omitidos), sin las líneas de
        ``FAIL:``/``ERROR:`` ni el texto de las pruebas."""
        text = "\n".join(
            [
                "test_a (tests.unit.test_a.A.test_a) ... ok",
                "test_b (tests.unit.sub.test_b.B.test_b)",
                "RF-001-06: doc. ... ok",
                "setUpClass (tests.unit.test_c.C) ... skipped '[ENTORNO] x: y'",
                "setUpModule (tests.unit.test_d) ... skipped 'motivo'",
                "FAIL: test_e (tests.unit.test_e.E.test_e)",
                "  imprime test_f (tests.unit.test_f.F.test_f)",
            ]
        )
        self.assertEqual(
            discovery.loaded_in_output(text),
            {
                "tests.unit.test_a.A.test_a",
                "tests.unit.sub.test_b.B.test_b",
                "tests.unit.test_c.C",
                "tests.unit.test_d",
            },
        )

    def test_missing_modules(self) -> None:
        """RF-001-06: un módulo cuenta como cargado si alguna cabecera es él o algo de
        dentro de él (no un módulo con un nombre que empieza igual); los que faltan se
        devuelven con su ruta, ordenados."""
        expected = {
            "tests.unit.test_a": "tests/unit/test_a.py",
            "tests.unit.test_ab": "tests/unit/test_ab.py",
            "tests.unit.sub.test_b": "tests/unit/sub/test_b.py",
            "tests.unit.test_d": "tests/unit/test_d.py",
        }
        loaded = {"tests.unit.test_a.A.test_a", "tests.unit.test_d"}
        self.assertEqual(
            discovery.missing_modules(expected, loaded),
            ["tests/unit/sub/test_b.py", "tests/unit/test_ab.py"],
        )
        self.assertEqual(discovery.missing_modules({}, loaded), [])


class LauncherEndTest(unittest.TestCase):
    def test_end_line(self) -> None:
        """RF-001-06: la línea final del lanzador (T37) lleva el número de pruebas y el
        código, y la expresión de ``check.py`` la reconoce (solo como línea entera)."""
        self.assertEqual(
            discovery.launcher_end_line(12, 0), "FIN DEL LANZADOR: 12 pruebas, código 0"
        )
        self.assertEqual(
            discovery.launcher_end_line(1, 1), "FIN DEL LANZADOR: 1 prueba, código 1"
        )
        text = "Ran 12 tests\n\nOK\n" + discovery.launcher_end_line(12, 0) + "\n"
        self.assertEqual(discovery.LAUNCHER_END.findall(text), [("12", "0")])
        echoed = "eco: " + discovery.launcher_end_line(1, 0)
        self.assertEqual(discovery.LAUNCHER_END.findall(echoed), [])


if __name__ == "__main__":
    unittest.main()

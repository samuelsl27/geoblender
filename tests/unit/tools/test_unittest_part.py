# SPDX-License-Identifier: GPL-3.0-or-later
"""Una parte de ``python -m unittest discover`` (``tools/unittest_part.py``; spec 003,
T40).

- RNF-007-01, RF-001-06: ``tools/check.py`` reparte las pruebas unitarias en varios
  procesos con esta orden. Cada uno descubre lo mismo que ``python -m unittest
  discover`` con los mismos argumentos, ejecuta solo los módulos de su parte
  (``gbtools.parts``) y escribe antes «PARTE i de n: r de T pruebas»; entre todas las
  partes, cada prueba una vez. La salida y los códigos son los de ``unittest`` (0, 1 y
  5 «sin pruebas»), el ``-W`` del intérprete llega a las pruebas, y ``sys.path`` empieza
  por la carpeta actual y no por ``tools/``, como con ``-m unittest``.
- RF-001-07: unas opciones no válidas dan 2 sin ejecutar nada.

Lanza el Python en uso (el de Blender en ``tools/check.py``) sobre árboles temporales.
"""

import subprocess
import sys
import unittest
from pathlib import Path

from tests.support.repo import TOOLS_DIR, tools_on_path
from tests.support.trees import child_env, child_temp, temp_tree

tools_on_path()

from gbtools import blender, discovery, parts  # noqa: E402

SCRIPT = TOOLS_DIR / "unittest_part.py"
SPDX = "# SPDX-License-Identifier: GPL-3.0-or-later\n"
TIMEOUT_S = 120.0
DISCOVER = ("discover", "-v", "-s", "tests/unit", "-t", ".")


def _module(*names: str, body: str = "        pass\n") -> str:
    """Un módulo de pruebas con una clase y una prueba por nombre."""
    tests = "".join(f"    def {name}(self):\n{body}" for name in names)
    return SPDX + f"import unittest\n\n\nclass Pruebas(unittest.TestCase):\n{tests}"


# La carpeta de este guion no está en sys.path; la actual, sí (como con -m unittest).
PATH_CHECK = SPDX + (
    "import os\n"
    "import sys\n"
    "import unittest\n\n\n"
    "class Ruta(unittest.TestCase):\n"
    "    def test_ruta(self):\n"
    "        rutas = [os.path.normcase(os.path.abspath(p)) for p in sys.path]\n"
    f"        self.assertNotIn(os.path.normcase({str(TOOLS_DIR)!r}), rutas)\n"
    "        self.assertIn(os.path.normcase(os.getcwd()), rutas)\n"
)
TREE = {
    "tests/__init__.py": SPDX,
    "tests/unit/__init__.py": SPDX,
    "tests/unit/test_a.py": _module("test_a1", "test_a2"),
    "tests/unit/sub/__init__.py": SPDX,
    "tests/unit/sub/test_b.py": _module("test_b1"),
    "tests/unit/test_c.py": _module("test_c1", "test_c2", "test_c3"),
    "tests/unit/test_d.py": PATH_CHECK,
}
MODULES = {
    "tests.unit.test_a": 2,
    "tests.unit.sub.test_b": 1,
    "tests.unit.test_c": 3,
    "tests.unit.test_d": 1,
}


def run_script(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """``tools/unittest_part.py`` con ``arguments`` desde ``root``, con el ``-W`` de
    ``tools/check.py`` y su propia carpeta temporal."""
    command = [
        sys.executable, "-B", "-s", "-X", "utf8", "-W", discovery.UNITTEST_WARNINGS,
        str(SCRIPT), *arguments,
    ]
    with child_temp() as temp:
        return subprocess.run(
            command,
            env=child_env(blender.python_env(root), temp),
            cwd=root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_S,
            check=False,
        )


def run_part(root: Path, value: str) -> subprocess.CompletedProcess[str]:
    """``tools/unittest_part.py --parte value discover -v -s tests/unit -t .``"""
    return run_script(root, parts.OPTION, value, *DISCOVER)


def _text(result: subprocess.CompletedProcess[str]) -> str:
    return f"{result.stdout}\n{result.stderr}"


def _modules(text: str) -> set[str]:
    """Los módulos de las pruebas que nombra la salida de ``unittest -v``."""
    return {name.rsplit(".", 2)[0] for name in discovery.loaded_in_output(text)}


class PartsTest(unittest.TestCase):
    def test_parts_cover_every_test_once(self) -> None:
        """RNF-007-01, RF-001-06: con 1, 2 y 3 partes, cada parte sale con 0, dice su
        línea «PARTE i de n: r de 7 pruebas», ejecuta r pruebas («Ran r tests», «OK») de
        módulos enteros, y entre todas cargan cada módulo una sola vez; las líneas
        cuadran (``parts.consistency``)."""
        with temp_tree(TREE) as root:
            for count in (1, 2, 3):
                seen: dict[str, int] = {}
                lines: list[tuple[int, int, int, int] | None] = []
                for part in range(1, count + 1):
                    result = run_part(root, f"{part}/{count}")
                    text = _text(result)
                    with self.subTest(partes=count, parte=part):
                        self.assertEqual(result.returncode, 0, text)
                        found = parts.last_line(text)
                        lines.append(found)
                        self.assertIsNotNone(found, text)
                        assert found is not None
                        self.assertEqual((found[0], found[1], found[3]), (part, count, 7))
                        self.assertRegex(text, rf"(?m)^Ran {found[2]} tests? in ")
                        self.assertRegex(text, r"(?m)^OK$")
                        loaded = _modules(text)
                        self.assertEqual(found[2], sum(MODULES[m] for m in loaded))
                        for module in loaded:
                            seen[module] = seen.get(module, 0) + 1
                with self.subTest(partes=count):
                    self.assertEqual(seen, dict.fromkeys(MODULES, 1))
                    self.assertIsNone(parts.consistency(lines, count))

    def test_codes_are_those_of_unittest(self) -> None:
        """RF-001-06: una prueba que falla da 1 en su parte y 0 en la otra; una carpeta
        sin pruebas, 5 y «NO TESTS RAN» (con «0 de 0»); y una prueba que devuelve algo
        es un error gracias al ``-W`` (T54)."""
        red = _module("test_c1", body="        self.fail('roja')\n")
        with temp_tree({**TREE, "tests/unit/test_c.py": red}) as root:
            codes: list[int] = []
            for part in (1, 2):
                result = run_part(root, f"{part}/2")
                codes.append(result.returncode)
                if "tests.unit.test_c" in _modules(_text(result)):
                    self.assertEqual(result.returncode, 1, _text(result))
                    self.assertIn("FAILED (failures=1)", _text(result))
            self.assertEqual(sorted(codes), [0, 1], codes)

        empty = {"tests/__init__.py": SPDX, "tests/unit/__init__.py": SPDX}
        with temp_tree(empty) as root:
            result = run_part(root, "1/2")
        self.assertEqual(result.returncode, 5, _text(result))
        self.assertIn("NO TESTS RAN", _text(result))
        self.assertEqual(parts.last_line(_text(result)), (1, 2, 0, 0))

        returning = {
            "tests/__init__.py": SPDX,
            "tests/unit/__init__.py": SPDX,
            "tests/unit/test_e.py": _module("test_e1", body="        return 1\n"),
        }
        with temp_tree(returning) as root:
            result = run_part(root, "1/1")
        self.assertEqual(result.returncode, 1, _text(result))
        self.assertIn("It is deprecated to return a value", _text(result))

    def test_usage_errors_exit_2(self) -> None:
        """RF-001-07: sin «--parte i/n» válida, o sin «discover» detrás, sale con 2, lo
        dice (con la opción) y no ejecuta ninguna prueba."""
        cases = {
            "parte 0": (parts.OPTION, "0/2", *DISCOVER),
            "parte que no es i/n": (parts.OPTION, "x", *DISCOVER),
            "parte mayor que n": (parts.OPTION, "3/2", *DISCOVER),
            "sin valor": (parts.OPTION,),
            "sin discover": (parts.OPTION, "1/2", "tests.unit.test_a"),
            "nada tras la parte": (parts.OPTION, "1/2"),
            "sin la opción": DISCOVER,
            "nada": (),
        }
        with temp_tree(TREE) as root:
            for name, arguments in cases.items():
                with self.subTest(caso=name):
                    result = run_script(root, *arguments)
                    self.assertEqual(result.returncode, 2, _text(result))
                    self.assertIn("Error:", result.stderr)
                    self.assertIn(parts.OPTION, result.stderr)
                    self.assertNotIn("Ran ", _text(result))


if __name__ == "__main__":
    unittest.main()

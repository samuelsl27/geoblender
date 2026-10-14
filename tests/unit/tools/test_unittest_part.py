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
- RNF-001-01, RNF-007-01 (spec 004, T39): con ``--tiempos`` reparte por la duración
  medida de cada módulo y con ``--medidas`` escribe la de los suyos. Con tiempos (spec 006,
  T48), reparte los ficheros sin importarlos todos, solo importa los suyos y escribe
  «PARTE i de n: m de M módulos».
- RNF-001-01 (spec 006, T59): con ``--cola`` las partes se reparten los módulos según
  acaban (una cola en una carpeta que comparten), y cada una escribe su línea al terminar.

Lanza el Python en uso (el de Blender en ``tools/check.py``) sobre árboles temporales.
"""

import subprocess
import sys
import tempfile
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
            "tiempos sin valor": (parts.OPTION, "1/2", parts.TIMES_OPTION),
            "cola sin valor": (parts.OPTION, "1/2", parts.QUEUE_OPTION),
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

    def test_times_and_measures(self) -> None:
        """RNF-001-01, RNF-007-01 (spec 004, T39; spec 006, T48): con ``--tiempos`` (la
        duración de cada módulo) la parte reparte por tiempo y no por número de pruebas
        (por número, la 1 tendría test_c y test_d), y con ``--medidas`` escribe la
        duración de los módulos que ejecutó, con su parte; reparte los ficheros sin
        importarlos todos y su línea es «PARTE i de 2: m de 4 módulos» (las de las dos
        partes cuadran); el código, el de siempre."""
        times = {
            "tests.unit.test_a": 5.0,
            "tests.unit.sub.test_b": 0.2,
            "tests.unit.test_c": 0.1,
            "tests.unit.test_d": 0.3,
        }
        expected = {1: {"tests.unit.test_a"},
                    2: {"tests.unit.sub.test_b", "tests.unit.test_c", "tests.unit.test_d"}}
        lines: list[tuple[int, int, int, int] | None] = []
        with temp_tree(TREE) as root, tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            parts.write_times(folder / "tiempos.json", times)
            for part, modules in expected.items():
                measures = folder / f"medidas-{part}.json"
                result = run_script(
                    root, parts.OPTION, f"{part}/2", parts.TIMES_OPTION,
                    str(folder / "tiempos.json"), parts.MEASURES_OPTION, str(measures),
                    *DISCOVER,
                )
                text = _text(result)
                with self.subTest(parte=part):
                    self.assertEqual(result.returncode, 0, text)
                    self.assertEqual(_modules(text), modules)
                    ran = sum(MODULES[m] for m in modules)
                    self.assertRegex(text, rf"(?m)^Ran {ran} tests? in ")
                    lines.append(parts.last_module_line(text))
                    self.assertEqual(lines[-1], (part, 2, len(modules), 4))
                    self.assertIsNone(parts.last_line(text))
                    found = parts.read_measures(measures)
                    assert found is not None
                    self.assertEqual((found.part, found.parts), (part, 2))
                    self.assertEqual(set(found.modules), modules)
                    self.assertTrue(all(s >= 0 for s in found.modules.values()))
        self.assertIsNone(parts.consistency(lines, 2, unit=parts.MODULES_UNIT))

    def test_times_import_only_the_part(self) -> None:
        """RNF-001-01, RNF-007-01 (spec 006, T48): con ``--tiempos``, la parte no importa
        los módulos de la otra (uno que falla al importarse no la toca, y en la suya es un
        error de importación, como con ``unittest``); un módulo nuevo, sin tiempo, cuenta
        la media de los medidos; y los de la misma afinidad (``PART_AFFINITY`` en su
        fuente) van juntos."""
        tree = {
            **TREE,
            "tests/unit/test_a.py": 'PART_AFFINITY = "juntos"\n' + _module("test_a1", "test_a2"),
            "tests/unit/test_c.py": 'PART_AFFINITY = "juntos"\n' + _module(
                "test_c1", "test_c2", "test_c3"),
            "tests/unit/test_roto.py": SPDX + "raise RuntimeError('no se importa')\n",
        }
        times = {"tests.unit.test_a": 1.0, "tests.unit.sub.test_b": 0.5,
                 "tests.unit.test_c": 1.0, "tests.unit.test_d": 3.0}
        # juntos (a + c) 2 s; d 3 s; roto, sin tiempo, la media (1,375 s); b 0,5 s:
        # d → 1, juntos → 2, roto → 2, b → 1.
        expected = {1: ({"tests.unit.test_d", "tests.unit.sub.test_b"}, 0),
                    2: ({"tests.unit.test_a", "tests.unit.test_c", "tests.unit.test_roto"}, 1)}
        with temp_tree(tree) as root, tempfile.TemporaryDirectory() as tmp:
            parts.write_times(Path(tmp) / "tiempos.json", times)
            for part, (modules, code) in expected.items():
                result = run_script(root, parts.OPTION, f"{part}/2", parts.TIMES_OPTION,
                                    str(Path(tmp) / "tiempos.json"), *DISCOVER)
                text = _text(result)
                with self.subTest(parte=part):
                    self.assertEqual(result.returncode, code, text)
                    ran = {name for name in _modules(text) if name.startswith("tests.")}
                    self.assertEqual(ran, modules - {"tests.unit.test_roto"})
                    self.assertEqual(parts.last_module_line(text), (part, 2, len(modules), 5))
                    self.assertEqual("no se importa" in text, bool(code), text)


    def test_queue(self) -> None:
        """RNF-001-01 (spec 006, T59): con ``--cola DIR`` (y ``--tiempos``), las dos
        unidades que más tardan, una a cada parte, y las demás, para la que acabe antes:
        cada parte, al acabar una, toma la siguiente que nadie ha tomado (de más a menos
        tiempo). Una tras otra, la 1 ejecuta la suya y todas las de la cola, y la 2 solo la
        suya; a la vez, entre las dos, cada módulo una sola vez. Su línea «PARTE i de 2: m de
        M módulos», al terminar, y las dos cuadran; ``--medidas``, la duración de los
        suyos; el código, el de ``unittest``."""
        tree = {**TREE, "tests/unit/test_e.py": _module("test_e1"),
                "tests/unit/test_f.py": _module("test_f1", "test_f2")}
        modules = {**MODULES, "tests.unit.test_e": 1, "tests.unit.test_f": 2}
        times = {"tests.unit.test_a": 5.0, "tests.unit.test_c": 3.0, "tests.unit.test_e": 0.4,
                 "tests.unit.test_d": 0.3, "tests.unit.sub.test_b": 0.2,
                 "tests.unit.test_f": 0.1}
        queued = set(modules) - {"tests.unit.test_a", "tests.unit.test_c"}
        with temp_tree(tree) as root, tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            parts.write_times(folder / "tiempos.json", times)

            def arguments(part: int, queue: str) -> list[str]:
                return [parts.OPTION, f"{part}/2", parts.TIMES_OPTION,
                        str(folder / "tiempos.json"), parts.MEASURES_OPTION,
                        str(folder / f"medidas-{queue}-{part}.json"), parts.QUEUE_OPTION,
                        str(folder / queue), *DISCOVER]

            texts = [_text(run_script(root, *arguments(part, "una"))) for part in (1, 2)]
            self.assertEqual([_modules(text) for text in texts],
                             [{"tests.unit.test_a", *queued}, {"tests.unit.test_c"}])
            self.assertEqual([parts.last_module_line(text) for text in texts],
                             [(1, 2, 5, 6), (2, 2, 1, 6)])
            found = parts.read_measures(folder / "medidas-una-1.json")
            assert found is not None
            self.assertEqual(set(found.modules), {"tests.unit.test_a", *queued})

            command = [sys.executable, "-B", "-s", "-X", "utf8", "-W",
                       discovery.UNITTEST_WARNINGS, str(SCRIPT)]
            with child_temp() as temp:
                env = child_env(blender.python_env(root), temp)
                running = [subprocess.Popen([*command, *arguments(part, "ambas")], env=env,
                                            cwd=root, stdin=subprocess.DEVNULL,
                                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                            text=True, encoding="utf-8", errors="replace")
                           for part in (1, 2)]
                outputs = [process.communicate(timeout=TIMEOUT_S) for process in running]
            texts = [f"{out}\n{err}" for out, err in outputs]
        self.assertEqual([process.returncode for process in running], [0, 0], texts)
        loaded = [_modules(text) for text in texts]
        self.assertEqual(loaded[0] & loaded[1], set())
        self.assertEqual(loaded[0] | loaded[1], set(modules))
        self.assertIn("tests.unit.test_a", loaded[0])
        self.assertIn("tests.unit.test_c", loaded[1])
        lines = [parts.last_module_line(text) for text in texts]
        self.assertIsNone(parts.consistency(lines, 2, unit=parts.MODULES_UNIT))
        for text, found in zip(texts, loaded):
            self.assertRegex(text, rf"(?m)^Ran {sum(modules[m] for m in found)} tests? in ")


if __name__ == "__main__":
    unittest.main()

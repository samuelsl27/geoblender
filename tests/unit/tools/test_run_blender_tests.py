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
- RNF-001-01 (spec 006, T59): los módulos con ``RUN_LAST = True`` se ejecutan los últimos de
  su proceso, y lo declara todo módulo de ``tests/blender`` que inicia la GPU. Con la cola
  (spec 005, T44), no esperan al final de ella: la parte que toma uno no toma nada más.

Lo que hace dentro de Blender con la parte (la línea «PARTE i de n: …» y solo sus
pruebas) lo prueba ``tests/arnes/test_harness_blender.py`` con el Blender real y, en
cada comprobación, ``tools/check.py`` al cuadrar las partes del paso «blender».
"""

import ast
import contextlib
import io
import os
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest import mock

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

    def test_queue_option(self) -> None:
        """RNF-001-01 (spec 006, T59): ``--cola DIR`` da la carpeta de la cola que comparten
        las partes (una ruta relativa, desde la raíz); sin ella, ninguna; sin valor, un
        error de uso."""
        absolute = ROOT.parent / "cola"
        options = run_blender_tests.parse_args(["--parte", "1/2", "--cola", str(absolute)])
        self.assertEqual(options.queue, absolute)
        self.assertEqual(run_blender_tests.parse_args(["--cola=c"]).queue, ROOT / "c")
        self.assertIsNone(run_blender_tests.parse_args([]).queue)
        with self.assertRaises(run_blender_tests.UsageError):
            run_blender_tests.parse_args(["--cola"])
        self.assertEqual(run_blender_tests.QUEUE_OPTION, parts.QUEUE_OPTION)


# Tres módulos de prueba de una carpeta temporal: cada prueba anota su módulo en el fichero
# de ENV_LOG; el primero pide ejecutarse el último.
ENV_LOG = "GEOBLENDER_T59_LOG"
LAST_SOURCE = """# SPDX-License-Identifier: GPL-3.0-or-later
import os
import unittest

RUN_LAST = {value}


class Caso(unittest.TestCase):
    def test_it(self) -> None:
        with open(os.environ["{env}"], "a", encoding="utf-8") as log:
            log.write(__name__ + "\\n")
"""


def _gpu_modules(folder: Path) -> dict[str, bool]:
    """``{fichero: declara RUN_LAST = True}`` de los módulos de ``folder`` que llaman a
    ``gpu.init()``."""
    found: dict[str, bool] = {}
    for path in sorted(folder.rglob("*.py")):
        tree = ast.parse(path.read_bytes())
        calls = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "init"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "gpu"
            for node in ast.walk(tree)
        )
        if not calls:
            continue
        found[path.relative_to(ROOT).as_posix()] = any(
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == parts.RUN_LAST_ATTRIBUTE
                    for t in node.targets)
            and isinstance(node.value, ast.Constant)
            and node.value.value is True
            for node in tree.body
        )
    return found


class RunLastTest(unittest.TestCase):
    """Spec 006, T59 (RNF-001-01): lo que deja el proceso de Blender más lento para las
    pruebas que vienen detrás va al final."""

    def test_modules_that_run_last_run_at_the_end(self) -> None:
        """RNF-001-01: el lanzador ejecuta los módulos con ``RUN_LAST = True`` los últimos
        de su proceso (``gbtools.parts.last_at_the_end``), sin ``--parte`` y con ella; los
        demás, en el orden de ``unittest``."""
        names = {"test_t59_a": True, "test_t59_b": False, "test_t59_c": False}
        with tempfile.TemporaryDirectory(prefix="gb-t59-") as tmp:
            folder = Path(tmp)
            for name, value in names.items():
                (folder / f"{name}.py").write_text(
                    LAST_SOURCE.format(value=value, env=ENV_LOG), encoding="utf-8")
            log = folder / "orden.txt"
            self.addCleanup(lambda: [sys.modules.pop(n, None) for n in names])
            self.addCleanup(lambda: sys.path.remove(tmp) if tmp in sys.path else None)
            with mock.patch.dict(os.environ, {ENV_LOG: str(log)}):
                for extra in ([], ["--parte", "1/1"]):
                    with self.subTest(opciones=extra):
                        log.write_text("", encoding="utf-8")
                        options = run_blender_tests.parse_args(["--carpeta", tmp, *extra])
                        # _run_tests añade un filtro de avisos: que no quede en este proceso.
                        with warnings.catch_warnings(), \
                                contextlib.redirect_stderr(io.StringIO()):
                            code, count = run_blender_tests._run_tests(options)
                        self.assertEqual((code, count), (0, 3))
                        self.assertEqual(log.read_text(encoding="utf-8").split(),
                                         ["test_t59_b", "test_t59_c", "test_t59_a"])

    def test_queue(self) -> None:
        """RNF-001-01 (spec 006, T59; spec 005, T44): con ``--parte``, ``--tiempos`` y
        ``--cola DIR``, las partes se reparten los módulos según acaban
        (``gbtools.parts.Queue``), de más a menos tiempo, y el de ``RUN_LAST``, aunque tarde
        más, donde lo que queda detrás no pasa de lo que tarda él por cada otra parte
        (``parts.queue_order`` con las partes) y nunca entre los primeros: una tras otra, la
        1 ejecuta el que más tarda y después el de ``RUN_LAST``, y ya no toma más; la 2, el
        segundo y el que queda. Cada una escribe al terminar su línea «PARTE i de 2: r de 4
        pruebas», y cuadran; con ``--medidas``, la duración de los suyos."""
        names = {"test_t59_a": True, "test_t59_b": False, "test_t59_c": False,
                 "test_t59_d": False}
        times = {"test_t59_a": 9.0, "test_t59_b": 1.0, "test_t59_c": 5.0, "test_t59_d": 3.0}
        with tempfile.TemporaryDirectory(prefix="gb-t59-") as tmp:
            folder = Path(tmp)
            tests = folder / "pruebas"
            tests.mkdir()
            for name, value in names.items():
                (tests / f"{name}.py").write_text(
                    LAST_SOURCE.format(value=value, env=ENV_LOG), encoding="utf-8")
            parts.write_times(folder / "tiempos.json", times)
            log = folder / "orden.txt"
            self.addCleanup(lambda: [sys.modules.pop(n, None) for n in names])
            self.addCleanup(lambda: sys.path.remove(str(tests))
                            if str(tests) in sys.path else None)
            orders: list[list[str]] = []
            lines: list[tuple[int, int, int, int] | None] = []
            with mock.patch.dict(os.environ, {ENV_LOG: str(log)}):
                for part in (1, 2):
                    log.write_text("", encoding="utf-8")
                    options = run_blender_tests.parse_args([
                        "--carpeta", str(tests), "--parte", f"{part}/2", "--tiempos",
                        str(folder / "tiempos.json"), "--medidas",
                        str(folder / f"medidas-{part}.json"), "--cola", str(folder / "cola")])
                    errors = io.StringIO()
                    with warnings.catch_warnings(), contextlib.redirect_stderr(errors):
                        code, count = run_blender_tests._run_tests(options)
                    orders.append(log.read_text(encoding="utf-8").split())
                    lines.append(parts.last_line(errors.getvalue()))
                    self.assertEqual(code, 0, errors.getvalue())
                    self.assertEqual(count, len(orders[-1]))
            measures = parts.read_measures(folder / "medidas-1.json")
        # c (5 s) a la 1, d (3 s) a la 2; en la cola, a (9 s, el último de la parte que lo
        # toma: con b detrás, 1 s ≤ 9 s) y b (1 s).
        self.assertEqual(orders, [["test_t59_c", "test_t59_a"], ["test_t59_d", "test_t59_b"]])
        self.assertEqual(lines, [(1, 2, 2, 4), (2, 2, 2, 4)])
        self.assertIsNone(parts.consistency(lines, 2))
        assert measures is not None
        self.assertEqual(set(measures.modules), set(orders[0]))

    def test_gpu_modules_run_last(self) -> None:
        """RNF-001-01: cada módulo de ``tests/blender`` que inicia la GPU (``gpu.init()``)
        declara ``RUN_LAST = True``: tras ``gpu.init()``, abrir un ``.blend`` tarda en ese
        proceso unas 25 veces más (0,11 s frente a 0,004 s en Blender 5.2.1), y las pruebas
        que abren ficheros detrás de él en su parte de ``tools/check.py`` tardaban segundos
        de más. Hay al menos uno (la superposición de las curvas maestras, T55)."""
        found = _gpu_modules(ROOT / "tests" / "blender")
        self.assertTrue(found)
        self.assertEqual([name for name, last in found.items() if not last], [])


if __name__ == "__main__":
    unittest.main()

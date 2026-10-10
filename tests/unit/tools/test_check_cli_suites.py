# SPDX-License-Identifier: GPL-3.0-or-later
"""La comprobación completa, ``tools/check.py``, con un ejecutor simulado: suites vacías,
ficheros de prueba sin cargar y el resumen de ``unittest``.

- RF-001-07: una suite unitaria sin pruebas es un fallo y una de referencia vacía, «sin
  casos».
- RF-001-06 (convergencia, T35): un fichero de pruebas en disco que ``unittest`` no
  cargó pone su paso en fallo, aunque la orden termine con 0 o «sin pruebas».
- RF-001-06 (convergencia, T37): un código 0 solo vale si la salida llega al resumen de
  ``unittest`` («Ran N tests» y «OK») y, en el lanzador, a su línea final.

Las ayudas (el ejecutor simulado y ``run_check``), en ``tests/support/check_cli.py``
(spec 006, T46: estas pruebas estaban en ``test_check_cli.py``, partido en cuatro).
"""

import unittest

from tests.support.check_cli import (
    FakeRunner,
    NO_TESTS,
    NO_TESTS_END,
    SPDX,
    _launcher_output,
    _manifest_root,
    _step_line,
    _unittest_output,
    run_check,
)
from tests.support.repo import tools_on_path

tools_on_path()

import check  # noqa: E402


class SuitesTest(unittest.TestCase):
    def test_empty_unit_suite_fails(self) -> None:
        """RF-001-07: ``tests/unit`` sin pruebas (``unittest`` sale con 5) es un fallo:
        un arnés sin pruebas no demuestra nada."""
        result = run_check(runner=FakeRunner({"unitarias": (5, "", NO_TESTS)}))
        self.assertEqual(result.code, 1)
        line = _step_line(result.out, "unitarias")
        self.assertTrue(line.lstrip().startswith("fallo"), line)
        self.assertIn("sin pruebas", line)
        self.assertIn("«unitarias»", result.out.strip().splitlines()[-1])

    def test_empty_reference_suite_ok(self) -> None:
        """RF-001-07: ``tests/referencia`` sin casos (código 5) es correcto, «sin
        casos»; con casos que fallan, fallo. Sin casos, en una raíz temporal: el
        repositorio real los tiene desde la spec 002."""
        with _manifest_root() as tmp:
            empty = FakeRunner({"referencia": (5, "", NO_TESTS)})
            result = run_check(runner=empty, root=tmp)
        self.assertEqual(result.code, 0, result.out)
        self.assertIn("(sin casos)", _step_line(result.out, "referencia"))
        failing = _unittest_output(2, "FAILED (failures=1)", "FAIL: test_volumen")
        result = run_check(runner=FakeRunner({"referencia": (1, "", failing)}))
        self.assertEqual(result.code, 1)
        self.assertTrue(_step_line(result.out, "referencia").lstrip().startswith("fallo"))

    def test_empty_blender_suite_fails(self) -> None:
        """RF-001-07: ``tests/blender`` sin pruebas (el lanzador sale con 1 y «NO HAY
        PRUEBAS») es un fallo."""
        stderr = (
            "NO HAY PRUEBAS en «tests/blender» con el patrón «test_*.py»\n" + NO_TESTS_END
        )
        result = run_check(runner=FakeRunner({"blender": (1, "", stderr)}))
        self.assertEqual(result.code, 1)
        line = _step_line(result.out, "blender")
        self.assertTrue(line.lstrip().startswith("fallo"), line)
        self.assertIn("sin pruebas", line)

    def test_launcher_no_tests_needs_its_lines(self) -> None:
        """RF-001-06, RF-001-07: «sin pruebas» del lanzador (correcto en el paso opcional
        de rendimiento) solo vale con la línea «NO HAY PRUEBAS en …» al principio de una
        línea y la final «FIN DEL LANZADOR: 0 pruebas, código 1»: una medición que falla
        e imprime ese texto en otra parte, o sin la línea final, o con pruebas, es un
        fallo (hallazgo F10 de la ronda 3; convergencia, T57). En una raíz sin ficheros de
        rendimiento: si no, ya fallaría por los ficheros sin cargar (T35)."""
        cases = (
            "Traceback (most recent call last):\n"
            "RuntimeError: la medición dice NO HAY PRUEBAS en la escena\n"
            "FIN DEL LANZADOR: 1 prueba, código 1\n",
            "NO HAY PRUEBAS en «tests/rendimiento/blender»\n",
            "NO HAY PRUEBAS en «tests/rendimiento/blender»\n"
            "FIN DEL LANZADOR: 3 pruebas, código 1\n",
            "  NO HAY PRUEBAS en «x»\n" + NO_TESTS_END,
        )
        with _manifest_root() as tmp:
            for stderr in cases:
                with self.subTest(salida=stderr[-60:]):
                    perf = {
                        "rendimiento": (5, "", NO_TESTS),
                        "rendimiento-blender": (1, "", stderr),
                    }
                    runner = FakeRunner(perf)
                    result = run_check("--rendimiento", runner=runner, root=tmp)
                    self.assertEqual(result.code, 1, result.out)
                    line = _step_line(result.out, "rendimiento")
                    self.assertTrue(line.lstrip().startswith("fallo"), line)
                    self.assertIn("código 1", line)  # la parte del lanzador
            empty = {
                "rendimiento": (5, "", NO_TESTS),
                "rendimiento-blender": (
                    1,
                    "",
                    "NO HAY PRUEBAS en «tests/rendimiento/blender»\n" + NO_TESTS_END,
                ),
            }
            result = run_check("--rendimiento", runner=FakeRunner(empty), root=tmp)
        self.assertEqual(result.code, 0, result.out)
        self.assertIn("(sin pruebas)", _step_line(result.out, "rendimiento"))


class UnloadedFilesTest(unittest.TestCase):
    """Convergencia de la spec 001 (T35): ficheros de prueba en disco que ``unittest``
    no cargó (hallazgo 1, sabotajes S1 y S1b)."""

    FILES = {
        "tests/__init__.py": SPDX,
        "tests/unit/__init__.py": SPDX,
        "tests/unit/test_ok.py": SPDX,
        "tests/unit/nueva/test_falla.py": SPDX,
        "tests/blender/__init__.py": SPDX,
        "tests/blender/test_registro.py": SPDX,
        "tests/blender/otra/test_falla.py": SPDX,
        "tests/referencia/__init__.py": SPDX,
        "tests/referencia/caso/test_volumen.py": SPDX,
        "tests/rendimiento/__init__.py": SPDX,
        "tests/rendimiento/blender/perf_registro.py": SPDX,
    }
    UNIT = _unittest_output(1, body="test_ok (tests.unit.test_ok.Ok.test_ok) ... ok")
    BLENDER = _launcher_output(
        1, body="test_r (tests.blender.test_registro.R.test_r) ... ok"
    )

    def test_unloaded_test_file_fails(self) -> None:
        """RF-001-06: un fichero de pruebas en disco que ``unittest`` no cargó (p. ej. en
        una carpeta sin ``__init__.py``) pone su paso en fallo aunque la orden termine
        con 0, y la salida lo nombra: en «unitarias» y en «blender»."""
        runner = FakeRunner(
            {
                "unitarias": (0, "", self.UNIT),
                "blender": (0, "", self.BLENDER),
                "referencia": (5, "", NO_TESTS),
            },
            loaded=False,
        )
        with _manifest_root(self.FILES) as tmp:
            result = run_check(runner=runner, root=tmp)
        self.assertEqual(result.code, 1, result.out)
        for name, rel in (
            ("unitarias", "tests/unit/nueva/test_falla.py"),
            ("blender", "tests/blender/otra/test_falla.py"),
        ):
            with self.subTest(paso=name):
                line = _step_line(result.out, name)
                self.assertTrue(line.lstrip().startswith("fallo"), line)
                self.assertIn("1 fichero sin cargar", line)
                self.assertIn(rel, result.out)
        self.assertIn("«unitarias», «referencia», «blender»", result.out.splitlines()[-1])

    def test_empty_suite_with_files_fails(self) -> None:
        """RF-001-06, RF-001-07: «sin casos» o «sin pruebas» solo valen si no hay ficheros
        de prueba en disco: ``tests/referencia`` con un caso que no se cargó (código 5)
        o ``tests/rendimiento/blender`` con un ``perf_*.py`` que no se cargó («NO HAY
        PRUEBAS») son un fallo."""
        runner = FakeRunner(
            {
                "unitarias": (0, "", self.UNIT),
                "blender": (0, "", self.BLENDER),
                "referencia": (5, "", NO_TESTS),
                "rendimiento": (5, "", NO_TESTS),
                "rendimiento-blender": (1, "", "NO HAY PRUEBAS en «x»\n"),
            },
            loaded=False,
        )
        with _manifest_root(self.FILES) as tmp:
            result = run_check("--rendimiento", runner=runner, root=tmp)
        self.assertEqual(result.code, 1, result.out)
        for name, rel in (
            ("referencia", "tests/referencia/caso/test_volumen.py"),
            ("rendimiento", "tests/rendimiento/blender/perf_registro.py"),
        ):
            with self.subTest(paso=name):
                line = _step_line(result.out, name)
                self.assertTrue(line.lstrip().startswith("fallo"), line)
                self.assertNotIn("sin casos", line)
                self.assertIn(rel, result.out)

    def test_all_loaded_ok(self) -> None:
        """RF-001-06: control positivo: si la salida nombra cada módulo de prueba que
        hay en disco, los mismos pasos son correctos."""
        runner = FakeRunner({"referencia": (0, "", _unittest_output(1))})
        with _manifest_root(self.FILES) as tmp:
            result = run_check("--rendimiento", runner=runner, root=tmp)
        self.assertEqual(result.code, 0, result.out)
        self.assertNotIn("sin cargar", result.out)

    def test_real_suites_compared(self) -> None:
        """RF-001-06: en el repositorio real, ``tests/rendimiento`` con «sin pruebas»
        (código 5) es un fallo, porque tiene ficheros de prueba."""
        result = run_check(
            "--rendimiento", runner=FakeRunner({"rendimiento": (5, "", NO_TESTS)})
        )
        self.assertEqual(result.code, 1, result.out)
        self.assertIn("tests/rendimiento/test_sync_speed.py", result.out)

    def test_launcher_default_pattern(self) -> None:
        """RF-001-06: el patrón con el que ``check.py`` compara el paso «blender» es el
        del lanzador por defecto."""
        import run_blender_tests

        self.assertEqual(check.LAUNCHER_PATTERN, run_blender_tests.DEFAULT_PATTERN)
        self.assertEqual(check.UNITTEST_PATTERN, "test*.py")


class SummaryTest(unittest.TestCase):
    """Convergencia de la spec 001 (T37): un código 0 solo vale si la salida llega al
    resumen de ``unittest`` y, en el lanzador, a su línea final (hallazgo 3, sabotaje
    S5: un ``os._exit(0)`` a mitad daba verde)."""

    CUT = (
        "test_a (tests.unit.test_a.A.test_a) ... ok\n"
        "test_b (tests.unit.test_b.B.test_b) ... "
    )

    def test_unittest_exit_0_without_summary_fails(self) -> None:
        """RF-001-06: un paso de ``unittest`` con código 0 sin «Ran N tests» (salida
        vacía o cortada a mitad) o con algo distinto de «OK» tras él es un fallo; con
        «OK» u «OK (skipped=n)», correcto."""
        for stderr in (
            "",
            self.CUT,
            _unittest_output(3, "FAILED (failures=1)"),
            _unittest_output(3, "OKAY"),
        ):
            with self.subTest(salida=stderr[-40:]):
                runner = FakeRunner({"unitarias": (0, "", stderr)})
                result = run_check(runner=runner)
                self.assertEqual(result.code, 1, result.out)
                line = _step_line(result.out, "unitarias")
                self.assertTrue(line.lstrip().startswith("fallo"), line)
                self.assertIn("sin el resumen de unittest", line)
                self.assertIn("«unitarias»", result.out.strip().splitlines()[-1])
        for verdict in ("OK", "OK (skipped=1)"):
            with self.subTest(veredicto=verdict):
                stderr = _unittest_output(3, verdict)
                result = run_check(runner=FakeRunner({"unitarias": (0, "", stderr)}))
                self.assertEqual(result.code, 0, result.out)

    def test_launcher_needs_end_line(self) -> None:
        """RF-001-06: un paso del lanzador con código 0 necesita además su línea final
        («FIN DEL LANZADOR: n pruebas, código 0») con el número de «Ran n tests»; sin
        ella (Blender terminó antes que el lanzador), con otro número o con otro código,
        es un fallo; sin resumen de ``unittest``, también."""
        for stderr in (
            _unittest_output(12),
            _unittest_output(12) + "FIN DEL LANZADOR: 11 pruebas, código 0\n",
            _unittest_output(12) + "FIN DEL LANZADOR: 12 pruebas, código 1\n",
            "FIN DEL LANZADOR: 12 pruebas, código 0\n",
            "",
        ):
            with self.subTest(salida=stderr[-45:]):
                result = run_check(runner=FakeRunner({"blender": (0, "", stderr)}))
                self.assertEqual(result.code, 1, result.out)
                line = _step_line(result.out, "blender")
                self.assertTrue(line.lstrip().startswith("fallo"), line)
                self.assertRegex(line, "sin el resumen de unittest|sin la línea final")
        result = run_check(runner=FakeRunner({"blender": (0, "", _launcher_output(12))}))
        self.assertEqual(result.code, 0, result.out)
        perf = {"rendimiento-blender": (0, "", _unittest_output(1))}
        result = run_check("--rendimiento", runner=FakeRunner(perf))
        self.assertEqual(result.code, 1, result.out)
        self.assertIn("sin la línea final", _step_line(result.out, "rendimiento"))

    def test_expected_failures_are_not_green(self) -> None:
        """RF-001-06: «OK (expected failures=n)» (una prueba roja marcada con
        ``expectedFailure``, que ``unittest`` da por buena con código 0) no es verde: el
        paso de ``unittest`` y el del lanzador quedan en fallo «con fallos esperados»
        (hallazgo F1 de la ronda 4; convergencia, T59)."""
        for verdict in ("OK (expected failures=1)", "OK (skipped=1, expected failures=2)"):
            for step, output in (
                ("unitarias", _unittest_output(3, verdict)),
                ("blender", _launcher_output(12, verdict)),
            ):
                with self.subTest(paso=step, veredicto=verdict):
                    result = run_check(runner=FakeRunner({step: (0, "", output)}))
                    self.assertEqual(result.code, 1, result.out)
                    line = _step_line(result.out, step)
                    self.assertTrue(line.lstrip().startswith("fallo"), line)
                    self.assertIn("con fallos esperados", line)
                    self.assertIn("expectedFailure", result.out)

    def test_no_tests_needs_summary(self) -> None:
        """RF-001-06, RF-001-07: «sin casos» (código 5) solo vale con el resumen de
        ``unittest`` sin pruebas («Ran 0 tests» y «NO TESTS RAN»): un ``os._exit(5)`` a
        mitad no es «sin casos»."""
        result = run_check(runner=FakeRunner({"referencia": (5, "", "")}))
        self.assertEqual(result.code, 1, result.out)
        line = _step_line(result.out, "referencia")
        self.assertTrue(line.lstrip().startswith("fallo"), line)
        self.assertNotIn("sin casos", line)
        with _manifest_root() as tmp:
            empty = FakeRunner({"referencia": (5, "", NO_TESTS)})
            result = run_check(runner=empty, root=tmp)
        self.assertIn("(sin casos)", _step_line(result.out, "referencia"))


if __name__ == "__main__":
    unittest.main()

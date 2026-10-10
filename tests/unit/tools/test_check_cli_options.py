# SPDX-License-Identifier: GPL-3.0-or-later
"""La comprobación completa, ``tools/check.py``, con un ejecutor simulado: los pasos
opcionales y la orden que descarga las ruedas que faltan.

- RF-001-10, RF-001-11: sin opciones no se ejecutan ni el rendimiento ni el banco; con
  ``--rendimiento`` y ``--banco``, después de los obligatorios; el banco omitido (código 3
  de ``tools/bench_silvestre.py``) no es un fallo.
- RF-001-06, RF-001-07 (spec 001 0.6; spec 002, D-9 y T48): con ``--completo``, tras
  «blender», el paso «arnés» (``unittest`` de ``tests/arnes``, las pruebas del arnés que
  lanzan Blender entero), en el que «sin pruebas» o un fichero sin cargar son un fallo;
  sin la opción no se ejecuta, y el resumen lo dice antes de ``RESULTADO``.
- RF-007-14 (spec 007, T18): con ``--documentacion``, tras los obligatorios y los demás
  opcionales, ``tools/check_docs.py`` sobre la documentación que encuentra
  ``repo.find_docs``; sin documentación, «omitido» con el motivo, sin ser un fallo.
- RF-001-25, RF-001-06: si «licencias» falla porque faltan ruedas, el resumen da la orden
  que las descarga.

Las ayudas (el ejecutor simulado y ``run_check``), en ``tests/support/check_cli.py``
(spec 006, T46: estas pruebas estaban en ``test_check_cli.py``, partido en cuatro).
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support.check_cli import (
    DOCS_STEP,
    FakeRunner,
    HARNESS,
    INSTALL,
    MANDATORY,
    NOT_COMPLETE_NOTE,
    NO_DOCS,
    NO_TESTS,
    NO_TESTS_END,
    OPTIONAL,
    Outcome,
    RETURN_VALUE_IS_ERROR,
    SPDX,
    _launcher_output,
    _manifest_root,
    _project_root,
    _python_env,
    _step_line,
    _unittest_output,
    run_check,
)
from tests.support.repo import EXT, ROOT, tools_on_path
from tests.support.trees import temp_tree

tools_on_path()

import check  # noqa: E402
from gbtools import blender  # noqa: E402
from gbtools.layout import CODE_DIR_IN_DOCS, DOCS_MARKER, ENV_DOCS_DIR  # noqa: E402


class OptionalStepsTest(unittest.TestCase):
    def test_optional_steps_off_by_default(self) -> None:
        """RF-001-10: sin opciones, ni el rendimiento (tampoco el de dentro de Blender)
        ni el banco se ejecutan."""
        result = run_check()
        self.assertEqual(result.code, 0)
        self.assertEqual(result.runner.steps(), MANDATORY)
        self.assertNotIn("rendimiento", result.out)
        self.assertNotIn("banco", result.out)

    def test_rendimiento_flag(self) -> None:
        """RF-001-10: con ``--rendimiento``, después de los obligatorios, ``unittest`` de
        ``tests/rendimiento`` (``test_*.py``) y ``perf_*.py`` de
        ``tests/rendimiento/blender`` dentro de Blender, en una sola línea «rendimiento»
        con sus pruebas y sus medidas; sin pruebas en ninguna de las dos partes es
        correcto («sin pruebas»); si una falla, el paso falla."""
        result = run_check("--rendimiento")
        self.assertEqual(result.code, 0, result.out)
        runner = result.runner
        self.assertEqual(runner.steps(), [*MANDATORY, "rendimiento", "rendimiento-blender"])
        self.assertEqual(
            runner.call("rendimiento").cmd,
            blender.python_cmd(
                INSTALL,
                *RETURN_VALUE_IS_ERROR,
                "-m",
                "unittest",
                "discover",
                "-v",
                "-s",
                "tests/rendimiento",
                "-t",
                ".",
                "-p",
                "test_*.py",
            ),
        )
        perf = runner.call("rendimiento-blender")
        self.assertEqual(
            perf.cmd,
            blender.background_cmd(
                INSTALL,
                ROOT / "tools" / "run_blender_tests.py",
                "--carpeta",
                "tests/rendimiento/blender",
                "--patron",
                "perf_*.py",
            ),
        )
        self.assertTrue(perf.profile_existed)
        line = _step_line(result.out, "rendimiento")
        self.assertRegex(line, r"^  correcto  rendimiento\s+\d+,\d s  \(3 pruebas\)$")
        self.assertIn(
            "RNF-001-03: habilitar Geoblender, mediana de 3 ciclos: 0,006 s", result.out
        )

        # En una raíz sin ficheros de rendimiento, «sin pruebas» en las dos partes es
        # correcto, y en una sola, también.
        both_empty = {
            "rendimiento": (5, "", NO_TESTS),
            "rendimiento-blender": (
                1,
                "",
                "NO HAY PRUEBAS en «tests/rendimiento/blender»\n" + NO_TESTS_END,
            ),
        }
        with _manifest_root() as tmp:
            result = run_check("--rendimiento", runner=FakeRunner(both_empty), root=tmp)
            self.assertEqual(result.code, 0, result.out)
            self.assertIn("(sin pruebas)", _step_line(result.out, "rendimiento"))

            one = {"rendimiento": (5, "", NO_TESTS)}
            result = run_check("--rendimiento", runner=FakeRunner(one), root=tmp)
            self.assertEqual(result.code, 0, result.out)
            self.assertIn("(1 prueba)", _step_line(result.out, "rendimiento"))

        slow = _unittest_output(1, "FAILED (failures=1)", "FAIL: test_1000_files_under_10_s")
        result = run_check("--rendimiento", runner=FakeRunner({"rendimiento": (1, "", slow)}))
        self.assertEqual(result.code, 1)
        self.assertTrue(_step_line(result.out, "rendimiento").lstrip().startswith("fallo"))
        self.assertIn("FAIL: test_1000_files_under_10_s", result.out)

    def test_banco_flag(self) -> None:
        """RF-001-10, RF-001-11: con ``--banco``, ``tools/bench_silvestre.py`` después de
        los obligatorios; código 3 (sin banco) es «omitido» con el motivo y no es un
        fallo (código 0, «VERDE CON OMISIONES (1)»); 0 es correcto y 1, fallo."""
        result = run_check("--banco")
        self.assertEqual(result.code, 0, result.out)
        self.assertEqual(result.runner.steps(), [*MANDATORY, "banco"])
        call = result.runner.call("banco")
        self.assertEqual(call.cmd, blender.python_cmd(INSTALL, "tools/bench_silvestre.py"))
        self.assertEqual(call.cwd, ROOT)
        self.assertEqual(call.env["PYTHONPATH"], _python_env()["PYTHONPATH"])
        self.assertRegex(_step_line(result.out, "banco"), r"^  omitido   banco\s")
        self.assertIn("GEOBLENDER_SILVESTRE_DIR no está definida", result.out)
        last = result.out.strip().splitlines()[-1]
        self.assertRegex(last, r"^RESULTADO: VERDE CON OMISIONES \(1\) ")

        bank = str(Path(tempfile.gettempdir()) / "banco-sintetico")
        ok = FakeRunner({"banco": (0, "Bancos: correcto\n", "")})
        with mock.patch.dict(os.environ, {"GEOBLENDER_SILVESTRE_DIR": bank}):
            result = run_check("--banco", runner=ok)
        self.assertEqual(result.code, 0)
        self.assertEqual(result.runner.call("banco").env["GEOBLENDER_SILVESTRE_DIR"], bank)
        self.assertRegex(_step_line(result.out, "banco"), r"^  correcto  banco\s")
        self.assertRegex(result.out.strip().splitlines()[-1], r"^RESULTADO: VERDE \(")

        changed = (1, "", "FALLO: la carpeta del banco «silvestre» ha cambiado\n")
        result = run_check("--banco", runner=FakeRunner({"banco": changed}))
        self.assertEqual(result.code, 1)
        self.assertIn("ha cambiado", result.out)

    def test_both_flags_after_mandatory(self) -> None:
        """RF-001-10: con las dos opciones (en cualquier orden, repetidas o no),
        rendimiento y banco van después de todos los obligatorios."""
        for args in (
            ("--rendimiento", "--banco"),
            ("--banco", "--rendimiento"),
            ("--banco", "--rendimiento", "--banco"),
        ):
            with self.subTest(opciones=args):
                result = run_check(*args)
                self.assertEqual(result.code, 0, result.out)
                self.assertEqual(result.runner.steps(), [*MANDATORY, *OPTIONAL])

    def test_optional_step_order_in_table(self) -> None:
        """RF-001-10: en la tabla, los pasos opcionales llevan su opción y van tras los
        obligatorios aunque otra spec añada un paso obligatorio al final."""
        options = {step.name: step.option for step in check.STEPS}
        self.assertEqual(options["rendimiento"], "--rendimiento")
        self.assertEqual(options["banco"], "--banco")
        self.assertTrue(all(options[name] is None for name in MANDATORY))

        def extra(ctx: check.Context) -> list[check.Run]:
            return [ctx.python("tools/build_icons.py", "--check")]

        steps = (*check.STEPS, check.Step("iconos", extra))
        runner = FakeRunner({"iconos": (0, "", "")})
        result = run_check("--rendimiento", "--banco", runner=runner, steps=steps)
        self.assertEqual(result.code, 0, result.out)
        self.assertEqual(runner.steps(), [*MANDATORY, "iconos", *OPTIONAL])


class CompleteStepTest(unittest.TestCase):
    """RF-001-06, RF-001-07 (spec 001 0.6): el paso «arnés» de ``--completo``, con las
    pruebas del arnés que lanzan Blender entero (``tests/arnes``). La comprobación de cada
    tarea no lo ejecuta y lo dice; la publicación lo pide siempre (D-9 de la spec 002;
    T48)."""

    def _note_lines(self, out: str) -> list[str]:
        return [line for line in out.splitlines() if NOT_COMPLETE_NOTE in line]

    def test_without_completo_no_harness_and_summary_says_so(self) -> None:
        """RF-001-06: sin ``--completo``, solo los pasos obligatorios (ningún «arnés») y,
        justo antes de ``RESULTADO``, una línea que dice que no se han ejecutado las
        pruebas del arnés que lanzan Blender entero (``tests/arnes``), que las ejecuta
        ``--completo`` y que la publicación las pide siempre. El resultado sigue siendo
        «VERDE»: no es una omisión por un recurso."""
        result = run_check()
        self.assertEqual(result.code, 0, result.out)
        self.assertEqual(result.runner.steps(), MANDATORY)
        self.assertNotRegex(result.out, rf"(?m)^  \S+\s+{HARNESS}\s")
        self.assertNotIn("--completo", result.out.splitlines()[0])
        lines = result.out.strip().splitlines()
        self.assertRegex(lines[-1], r"^RESULTADO: VERDE \(\d+,\d s\)$")
        (note,) = self._note_lines(result.out)
        self.assertEqual(lines[-2], note)
        for text in ("no se han ejecutado", "tests/arnes", "Blender entero", "publicación"):
            with self.subTest(texto=text):
                self.assertIn(text, note)

        # También cuando la comprobación no es verde.
        failing = FakeRunner({"licencias": (1, "LIC-01\n", "")})
        result = run_check(runner=failing)
        lines = result.out.strip().splitlines()
        self.assertRegex(lines[-1], r"^RESULTADO: NO VERDE ")
        self.assertEqual(lines[-2], self._note_lines(result.out)[0])

    def test_completo_runs_harness_after_blender(self) -> None:
        """RF-001-06: con ``--completo``, el paso «arnés» va justo después de «blender»
        (y antes de los opcionales pedidos), con ``unittest discover -v`` de
        ``tests/arnes`` como «unitarias», desde la raíz; su línea lleva el número de
        pruebas, la cabecera nombra la opción y el resumen ya no dice que falten."""
        result = run_check("--completo")
        self.assertEqual(result.code, 0, result.out)
        runner = result.runner
        self.assertEqual(runner.steps(), [*MANDATORY, HARNESS])
        call = runner.call(HARNESS)
        self.assertEqual(
            call.cmd,
            blender.python_cmd(
                INSTALL,
                *RETURN_VALUE_IS_ERROR,
                "-m",
                "unittest",
                "discover",
                "-v",
                "-s",
                "tests/arnes",
                "-t",
                ".",
            ),
        )
        self.assertEqual(call.cwd, ROOT)
        self.assertEqual(call.env["PYTHONPATH"], _python_env()["PYTHONPATH"])
        self.assertRegex(
            _step_line(result.out, HARNESS), rf"^  correcto  {HARNESS}\s+\d+,\d s  \(23 pruebas\)$"
        )
        self.assertIn("--completo", result.out.splitlines()[0])
        self.assertNotIn("no se han ejecutado", result.out)
        self.assertRegex(result.out.strip().splitlines()[-1], r"^RESULTADO: VERDE \(")

        result = run_check("--rendimiento", "--completo", "--banco")
        self.assertEqual(result.code, 0, result.out)
        self.assertEqual(result.runner.steps(), [*MANDATORY, HARNESS, *OPTIONAL])

        options = {step.name: step.option for step in check.STEPS}
        self.assertEqual(options[HARNESS], "--completo")

    def test_completo_failures(self) -> None:
        """RF-001-06, RF-001-07: con ``--completo``, una prueba del arnés que falla, una
        carpeta ``tests/arnes`` sin pruebas (código 5 de ``unittest``) o un fichero de
        ``tests/arnes`` que ``unittest`` no cargó ponen el paso en fallo («NO VERDE»)."""
        red = _unittest_output(23, "FAILED (failures=1)", "FAIL: test_failing_test_exit_nonzero")
        result = run_check("--completo", runner=FakeRunner({HARNESS: (1, "", red)}))
        self.assertEqual(result.code, 1, result.out)
        self.assertTrue(_step_line(result.out, HARNESS).lstrip().startswith("fallo"))
        self.assertIn("FAIL: test_failing_test_exit_nonzero", result.out)
        self.assertIn(f"«{HARNESS}»", result.out.strip().splitlines()[-1])

        result = run_check("--completo", runner=FakeRunner({HARNESS: (5, "", NO_TESTS)}))
        self.assertEqual(result.code, 1, result.out)
        line = _step_line(result.out, HARNESS)
        self.assertTrue(line.lstrip().startswith("fallo"), line)
        self.assertIn("sin pruebas", line)

        files = {
            "tests/__init__.py": SPDX,
            "tests/arnes/__init__.py": SPDX,
            "tests/arnes/test_lanzador.py": SPDX,
            "tests/arnes/otra/test_falla.py": SPDX,
        }
        loaded = _unittest_output(
            1, body="test_x (tests.arnes.test_lanzador.L.test_x) ... ok"
        )
        runner = FakeRunner(
            {
                "unitarias": (0, "", _unittest_output(1)),
                "referencia": (5, "", NO_TESTS),
                "blender": (0, "", _launcher_output(1)),
                HARNESS: (0, "", loaded),
            },
            loaded=False,
        )
        with _manifest_root(files) as tmp:
            result = run_check("--completo", runner=runner, root=tmp)
        self.assertEqual(result.code, 1, result.out)
        line = _step_line(result.out, HARNESS)
        self.assertTrue(line.lstrip().startswith("fallo"), line)
        self.assertIn("1 fichero sin cargar", line)
        self.assertIn("tests/arnes/otra/test_falla.py", result.out)

    def test_usage_names_completo(self) -> None:
        """RF-001-06: la ayuda explica ``--completo``."""
        result = run_check("--ayuda")
        self.assertEqual(result.code, 0)
        self.assertIn("--completo", result.out)
        self.assertIn("tests/arnes", result.out)


class DocsStepTest(unittest.TestCase):
    """RF-007-14: el paso opcional «documentación» (``--documentacion``; D-4). Cada
    prueba pasa su entorno: ninguna lee ``GEOBLENDER_DOCS_DIR`` del puesto ni la
    documentación real."""

    def test_documentacion_flag(self) -> None:
        """RF-007-14: con ``--documentacion``, después de los obligatorios y de los demás
        opcionales, ``tools/check_docs.py <carpeta>`` con el Python de Blender, desde la
        raíz del código; su código 0 es «correcto» y otro, «fallo» con su salida."""
        options = {step.name: step.option for step in check.STEPS}
        self.assertEqual(options[DOCS_STEP], "--documentacion")
        self.assertIn("--documentacion", run_check("--ayuda").out)
        with _project_root() as tmp:
            root = tmp / CODE_DIR_IN_DOCS
            result = run_check("--documentacion", root=root, environ={})
            self.assertEqual(result.code, 0, result.out + result.err)
            runner = result.runner
            self.assertEqual(runner.steps(), [*MANDATORY, DOCS_STEP])
            call = runner.call(DOCS_STEP)
            self.assertEqual(
                call.cmd,
                blender.python_cmd(INSTALL, "tools/check_docs.py", str(tmp.resolve())),
            )
            self.assertEqual(call.cwd, root)
            expected_path = blender.python_env(root)["PYTHONPATH"]
            self.assertEqual(call.env["PYTHONPATH"], expected_path)
            line = _step_line(result.out, DOCS_STEP)
            self.assertRegex(line, r"^  correcto  documentación\s")
            self.assertRegex(result.out.strip().splitlines()[-1], r"^RESULTADO: VERDE \(")

            every = run_check(
                "--banco", "--documentacion", "--rendimiento", root=root, environ={}
            )
            self.assertEqual(every.code, 0, every.out)
            self.assertEqual(every.runner.steps(), [*MANDATORY, *OPTIONAL, DOCS_STEP])

            wrong = (
                1,
                "docs/nota.md:1: [TXT-02] tiene CRLF\n"
                "RESULTADO: DOCUMENTACIÓN CON INCUMPLIMIENTOS (1)\n",
                "",
            )
            usage = (2, "", "ERROR: no hay documentación\n")
            for result_of_docs, shown in ((wrong, "[TXT-02]"), (usage, "ERROR: no hay")):
                with self.subTest(codigo=result_of_docs[0]):
                    runner = FakeRunner({DOCS_STEP: result_of_docs})
                    failed = run_check(
                        "--documentacion", runner=runner, root=root, environ={}
                    )
                    self.assertEqual(failed.code, 1, failed.out)
                    line = _step_line(failed.out, DOCS_STEP)
                    self.assertTrue(line.lstrip().startswith("fallo"), line)
                    self.assertIn(shown, failed.out)
                    self.assertIn("RESULTADO: NO VERDE", failed.out)

    def test_documentacion_parent_folder(self) -> None:
        """RF-007-14, RF-007-12: sin variable (o vacía), la carpeta madre del código;
        con ``GEOBLENDER_DOCS_DIR``, la suya."""
        with _project_root() as tmp, temp_tree({DOCS_MARKER: "x\n"}) as other:
            root = tmp / CODE_DIR_IN_DOCS
            for environ, folder in (
                ({}, tmp),
                ({ENV_DOCS_DIR: ""}, tmp),
                ({ENV_DOCS_DIR: str(other)}, other),
            ):
                with self.subTest(entorno=environ):
                    result = run_check("--documentacion", root=root, environ=environ)
                    self.assertEqual(result.code, 0, result.out)
                    self.assertEqual(
                        result.runner.call(DOCS_STEP).cmd[-1], str(folder.resolve())
                    )

    def test_documentacion_omitted_without_docs(self) -> None:
        """RF-007-14: sin documentación (ni en la carpeta madre ni en la variable), o
        con una variable que no lleva a ella, el paso queda «omitido» con el motivo, no
        se ejecuta nada y no es un fallo: «VERDE CON OMISIONES (1)»."""
        with _project_root(docs=False) as tmp:
            root = tmp / CODE_DIR_IN_DOCS
            missing = str(tmp / "no-existe")
            cases = (({}, NO_DOCS), ({ENV_DOCS_DIR: missing}, "no existe"))
            for environ, reason in cases:
                with self.subTest(entorno=environ):
                    result = run_check("--documentacion", root=root, environ=environ)
                    self.assertEqual(result.code, 0, result.out + result.err)
                    self.assertEqual(result.runner.steps(), MANDATORY)
                    line = _step_line(result.out, DOCS_STEP)
                    self.assertRegex(line, r"^  omitido   documentación\s")
                    self.assertIn(reason, line)
                    omission = f"  {DOCS_STEP} (1): "
                    listed = [x for x in result.out.splitlines() if x.startswith(omission)]
                    self.assertEqual(len(listed), 1, result.out)
                    self.assertIn(reason, listed[0])
                    last = result.out.strip().splitlines()[-1]
                    self.assertRegex(last, r"^RESULTADO: VERDE CON OMISIONES \(1\) ")

    def test_documentacion_off_by_default(self) -> None:
        """RF-007-14: sin la opción, la documentación no se comprueba aunque esté en la
        carpeta madre."""
        with _project_root() as tmp:
            result = run_check(root=tmp / CODE_DIR_IN_DOCS, environ={})
        self.assertEqual(result.code, 0, result.out)
        self.assertEqual(result.runner.steps(), MANDATORY)
        self.assertNotIn(DOCS_STEP, result.out)


class MissingWheelsTest(unittest.TestCase):
    MISSING = (
        f"tools/wheels.toml:5: [LIC-02] falta «{EXT}/wheels/"
        "pyproj-3.8.0-cp313-cp313-win_amd64.whl»: ejecute tools/fetch_wheels.py\n"
        "Licencias (LIC-01 a LIC-04): NO VERDE, 1 incumplimientos\n"
    )

    def run_without_store(self, runner: FakeRunner, **variables: str) -> Outcome:
        environ = {k: v for k, v in os.environ.items() if k != "GEOBLENDER_WHEELHOUSE"}
        environ.update(variables)
        with mock.patch.dict(os.environ, environ, clear=True):
            return run_check(runner=runner)

    def test_missing_wheels_prints_fetch_command(self) -> None:
        """RF-001-25, RF-001-06: si el paso «licencias» falla porque faltan ruedas (un
        clon o *worktree* nuevo), el resumen da la orden exacta que las descarga, con
        ``--desde`` y el almacén si ``GEOBLENDER_WHEELHOUSE`` está definida; con otro
        fallo de licencias, no."""
        command = f'& "{INSTALL.python}" tools/fetch_wheels.py'
        result = self.run_without_store(FakeRunner({"licencias": (1, self.MISSING, "")}))
        self.assertEqual(result.code, 1)
        self.assertIn(command, result.out)
        self.assertNotIn("--desde", result.out)
        summary = result.out.split("\n--- Salida", 1)[0]
        self.assertIn(command, summary)

        store = str(Path(tempfile.gettempdir()) / "almacen-ruedas")
        result = self.run_without_store(
            FakeRunner({"licencias": (1, self.MISSING, "")}), GEOBLENDER_WHEELHOUSE=store
        )
        self.assertIn(f'{command} --desde "{store}"', result.out)

        other = "tools/wheels.toml:16: [LIC-01] la rueda «numpy»: está prohibida\n"
        result = self.run_without_store(FakeRunner({"licencias": (1, other, "")}))
        self.assertEqual(result.code, 1)
        self.assertNotIn("fetch_wheels", result.out)
        result = self.run_without_store(FakeRunner())
        self.assertNotIn("fetch_wheels", result.out)


if __name__ == "__main__":
    unittest.main()

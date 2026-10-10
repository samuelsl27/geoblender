# SPDX-License-Identifier: GPL-3.0-or-later
"""La comprobación completa, ``tools/check.py`` (plan 001 §5.4.7), con un ejecutor simulado:
los pasos, el entorno, el repositorio, el manifiesto, Blender y las medidas.

- RF-001-06: los pasos se ejecutan en el orden fijado (unitarias, referencia, licencias,
  manifiesto, blender), todos aunque falle alguno; el resumen da una línea por paso con
  su resultado, su duración y el número de pruebas; el código es 0 solo si ningún paso
  falla; una prueba omitida por un recurso opcional (``[ENTORNO] <recurso>: <orden>``)
  da «VERDE CON OMISIONES (n)» con el recurso y la orden que lo instala; otra spec
  puede añadir un paso en su lugar con los mismos estados.
- RF-001-07: Blender ausente o anterior al mínimo, otro intérprete o la comprobación
  lanzada desde Blender terminan con 2, sin ejecutar nada y con la orden correcta.
- RF-001-09: las pruebas de Blender se lanzan en segundo plano, de fábrica, con
  ``--python-exit-code 1`` y un perfil temporal local que se borra al terminar.
- RF-001-02: el paso «manifiesto» valida ``geoblender`` con ``extension validate`` y
  falla si la validación falla.
- RF-001-09 (convergencia, T41): si el repositorio (sin ``.git/``) cambia entre el
  primer paso y el último, «REPOSITORIO MODIFICADO» con la lista de cambios y «NO VERDE».

Las ayudas (el ejecutor simulado y ``run_check``), en ``tests/support/check_cli.py``
(spec 006, T46: estas pruebas estaban en ``test_check_cli.py``, partido en cuatro).
"""

import functools
import os
import subprocess
import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path
from unittest import mock

from tests.support import resources
from tests.support.check_cli import (
    FakeRunner,
    INSTALL,
    MANDATORY,
    RETURN_VALUE_IS_ERROR,
    SPDX,
    USER_VARIABLES,
    _launcher_output,
    _manifest_root,
    _python_env,
    _resources_file,
    _step_line,
    _unittest_output,
    blender_part_cmd,
    many_cpus,
    run_check,
    unit_part_cmd,
)
from tests.support.repo import EXT, ROOT, tools_on_path
from tests.support.resources import SKIP_PREFIX
from tests.support.trees import age_folders, temp_tree

tools_on_path()

import check  # noqa: E402
from gbtools import blender  # noqa: E402
from gbtools.blender import BlenderInstall  # noqa: E402
from gbtools import repo as gbrepo  # noqa: E402
from gbtools.rules import imports  # noqa: E402


class StepsTest(unittest.TestCase):
    def test_steps_run_in_order(self) -> None:
        """RF-001-06: unitarias, referencia, licencias, manifiesto y blender, en ese
        orden, con las órdenes del plan (§5.4.7) y desde la raíz del repositorio; las
        unitarias, repartidas en partes con ``tools/unittest_part.py`` (T40; con un solo
        módulo, la orden de siempre: ``PartsTest``)."""
        with many_cpus():
            result = run_check()
        self.assertEqual(result.code, 0, result.out + result.err)
        runner = result.runner
        self.assertEqual(runner.steps(), MANDATORY)
        units = runner.calls_of("unitarias")
        count = len(units)
        self.assertEqual([call.part for call in units], [(i, count) for i in range(1, count + 1)])
        for call in units:
            with self.subTest(parte=call.part):
                self.assertEqual(call.cmd, unit_part_cmd(*(call.part or (1, 1))))
        self.assertEqual(
            runner.call("referencia").cmd,
            blender.python_cmd(
                INSTALL,
                *RETURN_VALUE_IS_ERROR,
                "-m",
                "unittest",
                "discover",
                "-v",
                "-s",
                "tests/referencia",
                "-t",
                ".",
            ),
        )
        self.assertEqual(
            runner.call("licencias").cmd,
            blender.python_cmd(INSTALL, "tools/check_licenses.py"),
        )
        self.assertEqual(
            runner.call("manifiesto").cmd,
            blender.extension_cmd(INSTALL, "validate", EXT),
        )
        for call in runner.calls:
            with self.subTest(paso=call.step):
                self.assertEqual(call.cwd, ROOT)
                self.assertIsNotNone(call.timeout)
        expected_env = _python_env()
        for step in ("unitarias", "referencia", "licencias"):
            for call in runner.calls_of(step):
                with self.subTest(paso=step, parte=call.part):
                    for key in ("PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "PYTHONNOUSERSITE"):
                        self.assertEqual(call.env[key], expected_env[key])

    def test_failed_step_exit_1(self) -> None:
        """RF-001-06: si un paso falla, los demás se ejecutan igual, el código es 1, el
        resumen dice «NO VERDE» nombrando el paso y su salida se muestra entera."""
        failure = "tools/wheels.toml:3: [LIC-01] numpy no se admite como rueda\n"
        runner = FakeRunner({"licencias": (1, failure, "detalle en stderr\n")})
        result = run_check(runner=runner)
        self.assertEqual(result.code, 1)
        self.assertEqual(runner.steps(), MANDATORY)
        self.assertTrue(_step_line(result.out, "licencias").lstrip().startswith("fallo"))
        self.assertTrue(_step_line(result.out, "blender").lstrip().startswith("correcto"))
        self.assertIn(failure.strip(), result.out)
        self.assertIn("detalle en stderr", result.out)
        last = result.out.strip().splitlines()[-1]
        self.assertRegex(last, r"^RESULTADO: NO VERDE \(\d+,\d s\)")
        self.assertIn("«licencias»", last)
        self.assertNotIn("RESULTADO: VERDE", result.out)

    def test_failing_blender_step_exit_1(self) -> None:
        """RF-001-06: una prueba de Blender que falla, que lanza una excepción no
        capturada o un lanzador que no puede limpiar (código 1, o 2 por uso) ponen el
        paso «blender» en fallo, con su salida."""
        for code, stderr in (
            (1, _unittest_output(12, "FAILED (failures=1)", "FAIL: test_x")),
            (1, "RuntimeError: sabotaje\n"),
            (2, "Error: opción desconocida «--x»\n"),
        ):
            with self.subTest(codigo=code, salida=stderr):
                result = run_check(runner=FakeRunner({"blender": (code, "", stderr)}))
                self.assertEqual(result.code, 1)
                self.assertTrue(
                    _step_line(result.out, "blender").lstrip().startswith("fallo")
                )
                self.assertIn(stderr.strip().splitlines()[-1], result.out)

    def test_runner_errors_are_step_failures(self) -> None:
        """RF-001-06: una orden que no se puede lanzar o que no termina a tiempo es un
        fallo de su paso, y los siguientes se ejecutan."""
        for error in (
            OSError("no se encuentra el ejecutable"),
            subprocess.TimeoutExpired(["python"], 1.0),
        ):
            with self.subTest(error=type(error).__name__):
                runner = FakeRunner({"referencia": error})
                result = run_check(runner=runner)
                self.assertEqual(result.code, 1)
                self.assertEqual(runner.steps(), MANDATORY)
                line = _step_line(result.out, "referencia")
                self.assertTrue(line.lstrip().startswith("fallo"), line)

    def test_summary_lists_each_step(self) -> None:
        """RF-001-06: cabecera con la versión de Blender; una línea por paso con
        «correcto», la duración en segundos con coma decimal y el número de pruebas o
        «sin casos»; y «RESULTADO: VERDE (n s)» al final. La salida de los pasos
        correctos no se muestra."""
        result = run_check()
        self.assertEqual(result.code, 0)
        lines = result.out.strip().splitlines()
        self.assertIn("Blender 5.2.1", lines[0])
        self.assertIn(str(INSTALL.exe), lines[0])
        for name in MANDATORY:
            with self.subTest(paso=name):
                self.assertRegex(
                    _step_line(result.out, name), rf"^  correcto  {name}\s+\d+,\d s"
                )
        self.assertIn("(217 pruebas)", _step_line(result.out, "unitarias"))
        self.assertIn("(2 pruebas)", _step_line(result.out, "referencia"))
        self.assertIn("(12 pruebas)", _step_line(result.out, "blender"))
        self.assertRegex(lines[-1], r"^RESULTADO: VERDE \(\d+,\d s\)$")
        self.assertNotIn("Ran 217", result.out)
        self.assertNotIn("Success parsing", result.out)

    def test_skip_with_resource_is_green_with_omissions(self) -> None:
        """RF-001-06: una prueba omitida por un recurso opcional no es un fallo: código
        0 y «VERDE CON OMISIONES (n)», con cada recurso, la orden que lo instala y las
        pruebas omitidas; también una clase omitida en ``setUpClass``. El recurso es uno
        de la lista cerrada de ``tests/support/resources.py`` (aquí, ``blender`` y el
        ``runtime`` que añadiría la spec 004)."""
        body = "\n".join(
            [
                "setUpClass (tests.unit.tools.test_harness_blender.LauncherExitCodeTest)"
                ' ... skipped "' + SKIP_PREFIX + " blender: No se encuentra Blender en "
                "«C:\\\\Blender\\\\blender.exe»: defina GEOBLENDER_BLENDER\"",
                "test_motor (tests.unit.test_motor.MotorTest.test_motor)",
                "RF-004-28: doc. ... skipped '"
                + SKIP_PREFIX
                + " runtime: tools/install_runtime.py --desde <almacén>'",
            ]
        )
        stderr = _unittest_output(215, "OK (skipped=2)", body)
        with _manifest_root(_resources_file("blender", "runtime")) as tmp:
            result = run_check(runner=FakeRunner({"unitarias": (0, "", stderr)}), root=tmp)
        self.assertEqual(result.code, 0, result.out)
        self.assertIn("2 omitidas", _step_line(result.out, "unitarias"))
        last = result.out.strip().splitlines()[-1]
        self.assertRegex(last, r"^RESULTADO: VERDE CON OMISIONES \(2\) \(\d+,\d s\)$")
        self.assertIn("runtime", result.out)
        self.assertIn("tools/install_runtime.py --desde <almacén>", result.out)
        self.assertIn("tests.unit.test_motor.MotorTest.test_motor", result.out)
        self.assertIn("No se encuentra Blender en «C:\\Blender\\blender.exe»", result.out)
        self.assertIn(
            "tests.unit.tools.test_harness_blender.LauncherExitCodeTest (setUpClass)",
            result.out,
        )
        self.assertNotIn("sin recurso", result.out)

    def test_skip_without_resource_fails(self) -> None:
        """RF-001-06: una omisión sin «[ENTORNO] <recurso>: <orden>» (``@unittest.skip``
        o ``skipTest`` con otro motivo, también de un módulo entero o con el recurso
        vacío) no es «VERDE CON OMISIONES»: esconde una prueba que no se ejecuta, así
        que pone su paso en fallo, con la prueba, el motivo y cómo se omite bien
        (``tests.support.resources.requires``), en «unitarias» y en «blender»
        (hallazgo N1 de la reverificación; convergencia, T42)."""
        cases = {
            "skip": "test_pendiente (tests.unit.test_saltada.Saltada.test_pendiente)\n"
            "RF-001-06: doc. ... skipped 'pendiente de arreglar'",
            "módulo": "setUpModule (tests.unit.test_saltada) ... skipped 'sin hacer'",
            "recurso vacío": "test_x (tests.unit.test_saltada.S.test_x) ... skipped "
            f"'{SKIP_PREFIX} : orden'",
        }
        for case, body in cases.items():
            with self.subTest(caso=case):
                stderr = _unittest_output(3, "OK (skipped=1)", body)
                result = run_check(runner=FakeRunner({"unitarias": (0, "", stderr)}))
                self.assertEqual(result.code, 1, result.out)
                line = _step_line(result.out, "unitarias")
                self.assertTrue(line.lstrip().startswith("fallo"), line)
                self.assertIn("1 omisión sin recurso", line)
                self.assertIn("OMISIONES SIN RECURSO (1)", result.out)
                self.assertIn("tests.support.resources.requires", result.out)
                self.assertIn("tests.unit.test_saltada", result.out)
                last = result.out.strip().splitlines()[-1]
                self.assertRegex(
                    last, r"^RESULTADO: NO VERDE \(\d+,\d s\): falla «unitarias»$"
                )
        body = "test_b (tests.blender.test_b.B.test_b) ... skipped 'luego'"
        stderr = _launcher_output(14, "OK (skipped=1)", body)
        result = run_check(runner=FakeRunner({"blender": (0, "", stderr)}))
        self.assertEqual(result.code, 1, result.out)
        line = _step_line(result.out, "blender")
        self.assertTrue(line.lstrip().startswith("fallo"), line)
        self.assertIn("tests.blender.test_b.B.test_b: luego", result.out)

    def test_skip_with_unlisted_resource_fails(self) -> None:
        """RF-001-06: una omisión con «[ENTORNO] <recurso>: <orden>» cuyo recurso no está
        en la lista cerrada de ``tests/support/resources.py`` (``RESOURCES``: uno
        inventado, o el de una spec que aún no lo ha añadido) es una omisión sin
        recurso: el paso falla con la prueba, el recurso y dónde se declara la lista
        (hallazgo X1 de la reverificación de la ronda 2; convergencia, T47). Con los
        recursos en la lista (control positivo), «VERDE CON OMISIONES»."""
        body = "\n".join(
            [
                "test_pendiente (tests.unit.test_saltada.Saltada.test_pendiente)",
                f"RF-001-06: doc. ... skipped '{SKIP_PREFIX} futuro: instale el recurso'",
                "test_nada (tests.unit.test_saltada.Saltada.test_nada) ... skipped "
                f"'{SKIP_PREFIX} nada: nada'",
            ]
        )
        stderr = _unittest_output(3, "OK (skipped=2)", body)
        result = run_check(runner=FakeRunner({"unitarias": (0, "", stderr)}))
        self.assertEqual(result.code, 1, result.out)
        line = _step_line(result.out, "unitarias")
        self.assertTrue(line.lstrip().startswith("fallo"), line)
        self.assertIn("2 omisiones sin recurso", line)
        for name in ("«futuro»", "«nada»", "tests/support/resources.py", "RESOURCES"):
            with self.subTest(texto=name):
                self.assertIn(name, result.out)
        self.assertIn("tests.unit.test_saltada.Saltada.test_pendiente", result.out)
        self.assertNotIn("VERDE CON OMISIONES", result.out)

        with _manifest_root(_resources_file("symlink", "futuro", "nada")) as tmp:
            result = run_check(runner=FakeRunner({"unitarias": (0, "", stderr)}), root=tmp)
        self.assertEqual(result.code, 0, result.out)
        self.assertIn("VERDE CON OMISIONES (2)", result.out)
        self.assertNotIn("sin recurso", result.out)

    def test_resource_list_unreadable_fails(self) -> None:
        """RF-001-06: si no se puede leer la lista cerrada (falta
        ``tests/support/resources.py`` o su ``RESOURCES`` no es una tupla de textos
        literales), ninguna omisión cuenta como omisión por un recurso: el paso falla y
        el motivo lo dice."""
        stderr = _unittest_output(
            3,
            "OK (skipped=1)",
            f"test_x (a.X.test_x) ... skipped '{SKIP_PREFIX} symlink: orden'",
        )
        unreadable = {
            "sin fichero": {},
            "sin literal": {
                "tests/support/resources.py": SPDX + "RESOURCES = tuple('ab')\n"
            },
        }
        for case, files in unreadable.items():
            with self.subTest(caso=case), _manifest_root(files) as tmp:
                runner = FakeRunner({"unitarias": (0, "", stderr)})
                result = run_check(runner=runner, root=tmp)
                self.assertEqual(result.code, 1, result.out)
                line = _step_line(result.out, "unitarias")
                self.assertIn("1 omisión sin recurso", line)
                self.assertIn("no se puede leer la lista cerrada", result.out)

    def test_resource_list_is_the_support_one(self) -> None:
        """RF-001-06: ``check.py`` lee la lista cerrada del fichero, sin importar
        ``tests`` (HER-01), y es ``tests.support.resources.RESOURCES``, con los recursos
        de la plataforma (``symlink``, ``windows`` y ``blender``)."""
        self.assertEqual(check.known_resources(ROOT), frozenset(resources.RESOURCES))
        for name in (resources.SYMLINK, resources.WINDOWS, resources.BLENDER):
            with self.subTest(recurso=name):
                self.assertIn(name, resources.RESOURCES)

    def test_skips_in_blender_step_count(self) -> None:
        """RF-001-06: las omisiones del paso «blender» también cuentan."""
        stderr = _launcher_output(
            3,
            "OK (skipped=1)",
            "test_x (tests.blender.test_x.X.test_x) ... skipped '"
            + SKIP_PREFIX
            + " windows: ejecute las pruebas en Windows'",
        )
        result = run_check(runner=FakeRunner({"blender": (0, "", stderr)}))
        self.assertEqual(result.code, 0, result.out)
        self.assertIn("1 omitida", _step_line(result.out, "blender"))
        self.assertIn("VERDE CON OMISIONES (1)", result.out)
        self.assertIn("ejecute las pruebas en Windows", result.out)

    def test_omissions_do_not_hide_failures(self) -> None:
        """RF-001-06: con omisiones y un paso que falla, el resultado es «NO VERDE»."""
        stderr = _unittest_output(
            3,
            "OK (skipped=1)",
            "test_x (a.X.test_x) ... skipped '[ENTORNO] symlink: orden'",
        )
        runner = FakeRunner(
            {"unitarias": (0, "", stderr), "licencias": (1, "[LIC-01] mal\n", "")}
        )
        result = run_check(runner=runner)
        self.assertEqual(result.code, 1)
        self.assertNotIn("RESULTADO: VERDE", result.out)

    def test_icons_step(self) -> None:
        """RF-001-06 (spec 003, T30): el paso «iconos» va en su lugar de la tabla, tras
        «licencias», con ``tools/build_icons.py --check`` y los mismos estados y códigos."""
        names = [step.name for step in check.STEPS]
        self.assertEqual(names[: len(MANDATORY)], MANDATORY)
        self.assertEqual(names.index("iconos"), names.index("licencias") + 1)
        runner = FakeRunner()
        result = run_check(runner=runner)
        self.assertEqual(result.code, 0, result.out)
        self.assertEqual(runner.steps(), MANDATORY)
        self.assertEqual(
            runner.call("iconos").cmd,
            blender.python_cmd(INSTALL, "tools/build_icons.py", "--check"),
        )
        self.assertRegex(_step_line(result.out, "iconos"), r"^  correcto  iconos\s")

        runner = FakeRunner({"iconos": (1, "icons/a.png: hash distinto\n", "")})
        result = run_check(runner=runner)
        self.assertEqual(result.code, 1)
        self.assertIn("icons/a.png: hash distinto", result.out)
        self.assertIn("«iconos»", result.out.strip().splitlines()[-1])


class RepositoryUnchangedTest(unittest.TestCase):
    """Convergencia de la spec 001 (T41): la comprobación compara el repositorio antes
    del primer paso y después del último (hallazgo N5 de la reverificación: una prueba
    que escribía en el árbol daba verde y el fichero se quedaba)."""

    FILES = {
        "tests/__init__.py": SPDX,
        "tests/unit/__init__.py": SPDX,
        "tests/unit/test_a.py": SPDX,
        "docs/a.md": "a\n",
        "docs/b.md": "b\n",
        ".git/HEAD": "ref: refs/heads/main\n",
    }

    def test_write_into_repo_fails(self) -> None:
        """RF-001-09: una prueba unitaria que crea un fichero en el repositorio pone la
        comprobación en «NO VERDE» con «REPOSITORIO MODIFICADO» y la ruta, aunque todos
        los pasos terminen con 0 (spec 001 §11: las pruebas solo escriben en
        temporales)."""

        def write(root: Path) -> None:
            (root / "tests" / "unit" / "salida.json").write_text("{}", encoding="utf-8")

        runner = FakeRunner(effects={"unitarias": write})
        with _manifest_root(self.FILES) as tmp:
            age_folders(tmp)
            result = run_check(runner=runner, root=tmp)
        self.assertEqual(result.code, 1, result.out)
        for name in MANDATORY:
            with self.subTest(paso=name):
                line = _step_line(result.out, name)
                self.assertTrue(line.lstrip().startswith("correcto"), line)
        line = _step_line(result.out, "repositorio")
        self.assertTrue(line.lstrip().startswith("fallo"), line)
        self.assertIn("2 cambios", line)
        self.assertIn("REPOSITORIO MODIFICADO", result.out)
        self.assertIn("nuevo: tests/unit/salida.json", result.out)
        self.assertIn("cambiado: tests/unit/ (", result.out)
        last = result.out.strip().splitlines()[-1]
        self.assertRegex(last, r"^RESULTADO: NO VERDE \(\d+,\d s\)")
        self.assertIn("«repositorio»", last)

    def test_every_kind_of_change(self) -> None:
        """RF-001-09: también un fichero cambiado o borrado, y un ``__pycache__`` que
        deja el paso «blender» (antes, solo lo veía una prueba del paso «unitarias»), en
        cualquier paso."""

        def pycache(root: Path) -> None:
            folder = root / "tests" / "blender" / "__pycache__"
            folder.mkdir(parents=True)
            (folder / "test_x.cpython-313.pyc").write_bytes(b"\x00")

        effects = {
            "blender": pycache,
            "licencias": lambda root: (root / "docs" / "a.md").write_text(
                "aa\n", encoding="utf-8"
            ),
            "manifiesto": lambda root: (root / "docs" / "b.md").unlink(),
        }
        with _manifest_root(self.FILES) as tmp:
            age_folders(tmp)
            result = run_check(runner=FakeRunner(effects=effects), root=tmp)
        self.assertEqual(result.code, 1, result.out)
        self.assertIn("7 cambios", _step_line(result.out, "repositorio"))
        for change in (
            "nuevo: tests/blender/",
            "nuevo: tests/blender/__pycache__/",
            "nuevo: tests/blender/__pycache__/test_x.cpython-313.pyc",
            "borrado: docs/b.md",
            "cambiado: docs/a.md",
            f"cambiado: docs/ ({gbrepo.FOLDER_CHANGED})",
            f"cambiado: tests/ ({gbrepo.FOLDER_CHANGED})",
        ):
            with self.subTest(cambio=change):
                self.assertIn(f"  {change}\n", result.out)

    def test_create_and_delete_fails(self) -> None:
        """RF-001-09: una prueba que crea un fichero en el repositorio y lo borra al
        terminar (``addCleanup``) no deja el fichero, pero sí la fecha de su carpeta:
        la foto la compara y la comprobación queda en «NO VERDE» con «cambiado:
        tests/unit/» (hallazgo F4 de la ronda 3, sabotaje X5; convergencia, T51)."""

        def create_and_delete(root: Path) -> None:
            path = root / "tests" / "unit" / "salida_temporal.json"
            path.write_text("{}", encoding="utf-8")
            path.unlink()

        runner = FakeRunner(effects={"unitarias": create_and_delete})
        with _manifest_root(self.FILES) as tmp:
            age_folders(tmp)
            result = run_check(runner=runner, root=tmp)
        self.assertEqual(result.code, 1, result.out)
        line = _step_line(result.out, "repositorio")
        self.assertTrue(line.lstrip().startswith("fallo"), line)
        self.assertIn("1 cambio", line)
        self.assertIn(f"  cambiado: tests/unit/ ({gbrepo.FOLDER_CHANGED})\n", result.out)
        self.assertNotIn("salida_temporal.json", result.out)
        self.assertIn("«repositorio»", result.out.strip().splitlines()[-1])

    def test_git_folder_ignored_and_clean_run(self) -> None:
        """RF-001-09: lo que cambia dentro de ``.git/`` no cuenta; sin cambios (control
        positivo), verde y sin línea «repositorio»."""

        def git(root: Path) -> None:
            (root / ".git" / "index").write_bytes(b"DIRC")

        with _manifest_root(self.FILES) as tmp:
            age_folders(tmp)
            result = run_check(runner=FakeRunner(effects={"unitarias": git}), root=tmp)
            self.assertEqual(result.code, 0, result.out)
            self.assertNotIn("REPOSITORIO", result.out)
            self.assertNotIn("repositorio", result.out)
            result = run_check(runner=FakeRunner(), root=tmp)
        self.assertEqual(result.code, 0, result.out)
        self.assertNotIn("repositorio", result.out)


class EnvironmentTest(unittest.TestCase):
    def test_wrong_interpreter_exit_2(self) -> None:
        """RF-001-07: con un intérprete que no es el Python del Blender localizado, o
        dentro de Blender, sale con 2 sin ejecutar nada y da la orden correcta."""
        other = str(Path(tempfile.gettempdir()) / "Python313" / "python.exe")
        result = run_check(executable=other)
        self.assertEqual(result.code, 2)
        self.assertEqual(result.runner.calls, [])
        self.assertIn(other, result.err)
        self.assertIn(f'& "{INSTALL.python}" tools/check.py', result.err)
        self.assertNotIn("RESULTADO", result.out)

        result = run_check(modules=["bpy"])
        self.assertEqual(result.code, 2)
        self.assertEqual(result.runner.calls, [])
        self.assertIn("dentro de Blender", result.err)
        self.assertIn("tools/check.py", result.err)

    def test_missing_blender_exit_2(self) -> None:
        """RF-001-07, RF-001-08: si Blender no está, sale con 2 sin ejecutar nada, con
        el mensaje del localizador (la variable y su valor)."""
        with temp_tree({"vacia/": ""}) as tmp:
            missing = tmp / "no-existe" / "blender.exe"
            locate = functools.partial(
                blender.locate_blender, environ={blender.ENV_BLENDER: str(missing)}
            )
            result = run_check(locate=locate)
        self.assertEqual(result.code, 2)
        self.assertEqual(result.runner.calls, [])
        self.assertIn(blender.ENV_BLENDER, result.err)
        self.assertIn(str(missing), result.err)

    def test_old_blender_exit_2(self) -> None:
        """RF-001-07: un Blender 5.1.0 sale con 2 y el mensaje da las dos versiones."""

        def version_runner(cmd: Sequence[str], **kwargs: object):
            return subprocess.CompletedProcess(list(cmd), 0, "Blender 5.1.0\n", "")

        files = {"Blender/blender.exe": "", "Blender/5.1/python/bin/python.exe": ""}
        with temp_tree(files) as tmp:
            locate = functools.partial(
                blender.locate_blender,
                environ={blender.ENV_BLENDER: str(tmp / "Blender")},
                runner=version_runner,
            )
            result = run_check(locate=locate)
        self.assertEqual(result.code, 2)
        self.assertEqual(result.runner.calls, [])
        self.assertIn("5.1.0", result.err)
        self.assertIn("5.2.0", result.err)

    def test_minimum_from_manifest(self) -> None:
        """RF-001-07: el mínimo que se pide al localizador es el del manifiesto; con
        BOM se lee igual (lo señalan TXT-01, MAN-01 y el paso «manifiesto»), y un
        manifiesto ilegible es un «NO VERDE» que lo nombra, sin ejecutar nada."""
        asked: list[tuple[int, int, int]] = []

        def locate(minimum: tuple[int, int, int]) -> BlenderInstall:
            asked.append(minimum)
            return INSTALL

        run_check(locate=locate)
        self.assertEqual(asked, [(5, 2, 0)])

        bom = b"\xef\xbb\xbf"
        manifest = (ROOT / EXT / "blender_manifest.toml").read_bytes()
        manifest = bom + manifest.removeprefix(bom)  # uno solo, aunque el real ya lo tenga
        with temp_tree({f"{EXT}/blender_manifest.toml": manifest}) as tmp:
            result = run_check(locate=locate, root=tmp)
        self.assertEqual(result.code, 0, result.out + result.err)
        self.assertEqual(asked, [(5, 2, 0), (5, 2, 0)])

        with temp_tree({f"{EXT}/blender_manifest.toml": "id = \n"}) as tmp:
            result = run_check(locate=locate, root=tmp)
        self.assertEqual(result.code, 1)
        self.assertEqual(result.runner.calls, [])
        self.assertIn(f"{EXT}/blender_manifest.toml", result.err)
        self.assertIn("RESULTADO: NO VERDE", result.out)

    def test_usage(self) -> None:
        """RF-001-06: ``--ayuda`` muestra el uso; una opción desconocida sale con 2
        sin ejecutar nada (no hay modo «solo una parte»)."""
        result = run_check("--ayuda")
        self.assertEqual(result.code, 0)
        self.assertIn("tools/check.py", result.out)
        self.assertEqual(result.runner.calls, [])
        for option in ("--solo", "unitarias", "--rendimiento=no", "--bancos"):
            with self.subTest(opcion=option):
                result = run_check(option)
                self.assertEqual(result.code, 2)
                self.assertEqual(result.runner.calls, [])
                self.assertIn(option, result.err)


class ManifestStepTest(unittest.TestCase):
    def test_manifest_step_uses_validate(self) -> None:
        """RF-001-02: el paso «manifiesto» es ``blender --factory-startup --command
        extension validate Geoblender`` desde la raíz, con el perfil temporal; si la
        validación falla, el paso falla (código 1), con la salida de Blender."""
        result = run_check()
        call = result.runner.call("manifiesto")
        self.assertEqual(
            call.cmd,
            [str(INSTALL.exe), "--factory-startup", "--command", "extension", "validate",
             EXT],
        )
        self.assertEqual(call.cwd, ROOT)
        self.assertTrue(call.profile_existed)
        self.assertTrue(
            Path(call.env["BLENDER_USER_RESOURCES"]).parent.name.startswith(
                check.TEMP_PREFIX
            )
        )
        self.assertTrue(_step_line(result.out, "manifiesto").lstrip().startswith("correcto"))

        error = "Error: Invalid statement (at line 1, column 1)\n"
        runner = FakeRunner({"manifiesto": (1, "", error)})
        result = run_check(runner=runner)
        self.assertEqual(result.code, 1)
        self.assertEqual(runner.steps(), MANDATORY)
        self.assertTrue(_step_line(result.out, "manifiesto").lstrip().startswith("fallo"))
        self.assertIn(error.strip(), result.out)
        self.assertIn("«manifiesto»", result.out.strip().splitlines()[-1])


class BlenderStepTest(unittest.TestCase):
    def test_blender_command_flags(self) -> None:
        """RF-001-09: ``tools/run_blender_tests.py`` en segundo plano, de fábrica y con
        ``--python-exit-code 1``, sobre ``tests/blender``, en cada parte (T40)."""
        with many_cpus():
            result = run_check()
        calls = result.runner.calls_of("blender")
        self.assertEqual(len(calls), check.BLENDER_PARTS)
        for call in calls:
            with self.subTest(parte=call.part):
                self.assertEqual(call.cmd, blender_part_cmd(*(call.part or (1, 1))))
                self.assertEqual(
                    call.cmd[1:5], ["-b", "--factory-startup", "--python-exit-code", "1"]
                )
                self.assertEqual(call.cwd, ROOT)

    def test_blender_env_uses_temp_profile(self) -> None:
        """RF-001-09: los pasos «manifiesto» y «blender» usan perfiles temporales en
        ``%TEMP%`` (nunca el del usuario ni el repositorio), sin las variables
        ``BLENDER_USER_*`` que lo sustituirían: «manifiesto» y la parte 1 de «blender»,
        el mismo, y cada otra parte, el suyo, en la misma carpeta temporal (T40); los
        perfiles existen mientras se ejecutan y se borran al terminar, también si un
        paso falla o el ejecutor lanza."""
        planted = {name: str(ROOT / "perfil-real") for name in USER_VARIABLES}
        with mock.patch.dict(os.environ, planted), many_cpus():
            result = run_check()
        manifest_env = result.runner.call("manifiesto").env
        blender_calls = result.runner.calls_of("blender")
        profile = Path(blender_calls[0].env["BLENDER_USER_RESOURCES"])
        self.assertEqual(Path(manifest_env["BLENDER_USER_RESOURCES"]), profile)
        profiles = [Path(call.env["BLENDER_USER_RESOURCES"]) for call in blender_calls]
        self.assertEqual(len(set(profiles)), check.BLENDER_PARTS)
        self.assertEqual({other.parent for other in profiles}, {profile.parent})
        for env in (manifest_env, *(call.env for call in blender_calls)):
            for name in USER_VARIABLES:
                self.assertNotIn(name, env)
            self.assertEqual(env["PYTHONDONTWRITEBYTECODE"], "1")
        for call in (*blender_calls, result.runner.call("manifiesto")):
            self.assertTrue(call.profile_existed)
        temp = Path(tempfile.gettempdir()).resolve()
        self.assertEqual(profile.resolve().parents[1], temp)
        self.assertTrue(profile.parent.name.startswith(check.TEMP_PREFIX))
        appdata = Path(os.environ.get("APPDATA", str(ROOT))).resolve()
        for forbidden in (ROOT.resolve(), appdata):
            self.assertFalse(profile.resolve().is_relative_to(forbidden), forbidden)
        self.assertFalse(profile.parent.exists())

        with many_cpus():
            result = run_check(runner=FakeRunner({"blender": (1, "", "FAIL: x\n")}))
        profile = Path(result.runner.call("blender", 1).env["BLENDER_USER_RESOURCES"])
        self.assertFalse(profile.parent.exists())

        runner = FakeRunner({"blender#2": RuntimeError("fallo inesperado del ejecutor")})
        with self.assertRaises(RuntimeError), many_cpus():
            run_check(runner=runner)
        profile = Path(runner.call("blender", 2).env["BLENDER_USER_RESOURCES"])
        self.assertFalse(profile.parent.exists())

    def test_unit_step_extends_blender_modules(self) -> None:
        """RF-001-12 / ARQ-01: el paso «unitarias» recibe en ``GEOBLENDER_BLENDER_MODULES``
        los módulos de ``scripts/modules`` y ``scripts/startup`` de la instalación
        localizada, que amplían la lista fija de ARQ-01 (plan §5.4.1)."""
        files = {
            "Blender/blender.exe": "",
            "Blender/5.2/python/bin/python.exe": "",
            "Blender/5.2/scripts/modules/_rna_info.py": "",
            "Blender/5.2/scripts/modules/bl_keymap_utils/__init__.py": "",
            "Blender/5.2/scripts/modules/__pycache__/x.pyc": "",
            "Blender/5.2/scripts/startup/keyingsets_builtins.py": "",
            "Blender/5.2/scripts/startup/bl_operators/__init__.py": "",
            "Blender/5.2/scripts/startup/LEEME.txt": "",
        }
        with temp_tree(files) as tmp:
            folder = tmp / "Blender"
            install = BlenderInstall(
                folder / "blender.exe", folder / "5.2/python/bin/python.exe", (5, 2, 1)
            )
            result = run_check(locate=lambda minimum: install, executable=str(install.python))
        self.assertEqual(result.code, 0, result.out + result.err)
        for call in result.runner.calls_of("unitarias"):
            value = call.env[imports.ENV_BLENDER_MODULES]
            self.assertEqual(
                sorted(value.split(",")),
                ["_rna_info", "bl_keymap_utils", "bl_operators", "keyingsets_builtins"],
            )


class ParsingTest(unittest.TestCase):
    def test_measurements_are_reported(self) -> None:
        """RNF-001-01 a 05: las líneas de medida «RNF-…: …» de un paso se repiten en el
        resumen (sin la primera línea del docstring de la prueba)."""
        body = (
            "test_enable (tests.rendimiento.blender.perf_registration.R.test_enable)\n"
            "RNF-001-03: habilitar tarda poco (mediana de ... "
            "RNF-001-03: habilitar Geoblender, mediana de 3 ciclos: 0,006 s\n"
            "ok\n"
            "test_b (x.B.test_b)\nRNF-001-02: doc de la prueba. ... ok\n"
        )
        result = run_check(runner=FakeRunner({"blender": (0, "", _launcher_output(2, body=body))}))
        self.assertEqual(result.code, 0)
        self.assertIn("RNF-001-03: habilitar Geoblender, mediana de 3 ciclos: 0,006 s", result.out)
        self.assertNotIn("doc de la prueba", result.out)
        self.assertNotIn("habilitar tarda poco", result.out)


if __name__ == "__main__":
    unittest.main()

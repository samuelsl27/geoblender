# SPDX-License-Identifier: GPL-3.0-or-later
"""La comprobación completa, ``tools/check.py`` (plan 001 §5.4.7), con un ejecutor simulado.

- RF-001-06: los pasos se ejecutan en el orden fijado (unitarias, referencia, licencias,
  manifiesto, blender), todos aunque falle alguno; el resumen da una línea por paso con
  su resultado, su duración y el número de pruebas; el código es 0 solo si ningún paso
  falla; una prueba omitida por un recurso opcional (``[ENTORNO] <recurso>: <orden>``)
  da «VERDE CON OMISIONES (n)» con el recurso y la orden que lo instala; otra spec
  puede añadir un paso en su lugar con los mismos estados.
- RF-001-07: Blender ausente o anterior al mínimo, otro intérprete o la comprobación
  lanzada desde Blender terminan con 2, sin ejecutar nada y con la orden correcta; una
  suite unitaria sin pruebas es un fallo y una de referencia vacía, «sin casos».
- RF-001-09: las pruebas de Blender se lanzan en segundo plano, de fábrica, con
  ``--python-exit-code 1`` y un perfil temporal local que se borra al terminar.
- RF-001-02: el paso «manifiesto» valida ``geoblender`` con ``extension validate`` y
  falla si la validación falla.
- RF-001-10, RF-001-11: sin opciones no se ejecutan ni el rendimiento ni el banco; con
  ``--rendimiento`` y ``--banco``, después de los obligatorios; el banco omitido (código 3
  de ``tools/bench_silvestre.py``) no es un fallo.
- RF-001-06 (convergencia, T35): un fichero de pruebas en disco que ``unittest`` no
  cargó pone su paso en fallo, aunque la orden termine con 0 o «sin pruebas».
- RF-001-06 (convergencia, T37): un código 0 solo vale si la salida llega al resumen de
  ``unittest`` («Ran N tests» y «OK») y, en el lanzador, a su línea final.
- RF-001-09 (convergencia, T41): si el repositorio (sin ``.git/``) cambia entre el
  primer paso y el último, «REPOSITORIO MODIFICADO» con la lista de cambios y «NO VERDE».
- RF-007-14 (spec 007, T18): con ``--documentacion``, tras los obligatorios y los demás
  opcionales, ``tools/check_docs.py`` sobre la documentación que encuentra
  ``repo.find_docs``; sin documentación, «omitido» con el motivo, sin ser un fallo.

Ninguna prueba lanza Blender ni Python: el ejecutor simulado anota cada orden y
devuelve una salida fija por paso; en los pasos con pruebas que terminan con 0, la
salida nombra además los módulos de prueba que hay en disco, como haría ``unittest -v``.
"""

import contextlib
import fnmatch
import functools
import io
import os
import re
import subprocess
import tempfile
import unittest
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

from tests.support import resources
from tests.support.repo import EXT, ROOT, tools_on_path
from tests.support.resources import SKIP_PREFIX
from tests.support.trees import age_folders, temp_tree

tools_on_path()

import check  # noqa: E402
from gbtools import blender  # noqa: E402
from gbtools.blender import BlenderInstall, EnvironmentProblem  # noqa: E402
from gbtools import repo as gbrepo  # noqa: E402
from gbtools.layout import CODE_DIR_IN_DOCS, DOCS_MARKER, ENV_DOCS_DIR  # noqa: E402
from gbtools.rules import imports  # noqa: E402

FAKE_BLENDER = Path(tempfile.gettempdir()) / "geoblender-falso" / "Blender"
INSTALL = BlenderInstall(
    exe=FAKE_BLENDER / "blender.exe",
    python=FAKE_BLENDER / "5.2" / "python" / "bin" / "python.exe",
    version=(5, 2, 1),
)
MANDATORY = ["unitarias", "referencia", "licencias", "manifiesto", "blender"]
# Una prueba que devuelve algo (``async def`` en un TestCase, o con ``yield``) es un
# error y no solo un aviso (hallazgo F7 de la ronda 3; convergencia, T54).
RETURN_VALUE_IS_ERROR = ("-W", "error:It is deprecated to return a value:DeprecationWarning")
LINE = "-" * 70
USER_VARIABLES = (
    "BLENDER_USER_CONFIG",
    "BLENDER_USER_SCRIPTS",
    "BLENDER_USER_EXTENSIONS",
    "BLENDER_USER_DATAFILES",
)


def _unittest_output(ran: int, verdict: str = "OK", body: str = "") -> str:
    return f"{body}\n{LINE}\nRan {ran} tests in 1.234s\n\n{verdict}\n"


def _launcher_output(
    ran: int, verdict: str = "OK", body: str = "", code: int = 0
) -> str:
    """Salida del lanzador: la de ``unittest`` y su línea final (T37)."""
    noun = "prueba" if ran == 1 else "pruebas"
    end = f"FIN DEL LANZADOR: {ran} {noun}, código {code}\n"
    return _unittest_output(ran, verdict, body) + end


NO_TESTS = f"\n{LINE}\nRan 0 tests in 0.000s\n\nNO TESTS RAN\n"
NO_TESTS_END = "FIN DEL LANZADOR: 0 pruebas, código 1\n"  # el lanzador sin pruebas (T57)
DEFAULT_RESULTS: Mapping[str, tuple[int, str, str]] = {
    "unitarias": (
        0,
        "",
        _unittest_output(
            217, body="test_a (tests.unit.test_a.A.test_a)\nRF-001-01: doc. ... ok"
        ),
    ),
    # Desde la spec 002 (T03) el repositorio tiene casos de referencia: por defecto el
    # paso los carga (el ejecutor simulado nombra los módulos que hay en disco). «Sin
    # casos» se prueba en una raíz temporal sin ellos (test_empty_reference_suite_ok).
    "referencia": (0, "", _unittest_output(2)),
    "licencias": (0, "Licencias (LIC-01 a LIC-04): correcto\n", ""),
    "manifiesto": (0, 'Success parsing TOML in "Geoblender"\n', ""),
    "blender": (
        0,
        "Extensión de pruebas: bl_ext.gb_tests.geoblender\n",
        _launcher_output(12),
    ),
    "rendimiento": (0, "", _unittest_output(2)),
    "rendimiento-blender": (
        0,
        "",
        _launcher_output(
            1,
            body=(
                "test_enable_under_half_second (tests.rendimiento.blender.perf_registration"
                ".RegistrationSpeedTest.test_enable_under_half_second)\n"
                "RNF-001-03: habilitar Geoblender en segundo plano tarda poco (mediana de"
                " ... RNF-001-03: habilitar Geoblender, mediana de 3 ciclos: 0,006 s\nok"
            ),
        ),
    ),
    "banco": (
        3,
        "OMITIDO: silvestre: la variable GEOBLENDER_SILVESTRE_DIR no está definida; "
        "defínala con la carpeta del banco\nBancos: omitidos\n",
        "",
    ),
    "documentación": (
        0,
        "Geoblender · comprobación de la documentación · x\n"
        "RESULTADO: DOCUMENTACIÓN CORRECTA (6 ficheros, 0,0 s)\n",
        "",
    ),
}
OPTIONAL = ["rendimiento", "rendimiento-blender", "banco"]
DOCS_STEP = "documentación"
NO_DOCS = f"no hay documentación en la carpeta madre ni en {ENV_DOCS_DIR}"


def step_of(cmd: Sequence[str]) -> str:
    """Paso al que pertenece una orden simulada."""
    parts = [str(part) for part in cmd]
    if "validate" in parts:
        return "manifiesto"
    if any(part.replace("\\", "/").endswith("tools/check_licenses.py") for part in parts):
        return "licencias"
    if any(part.endswith("build_icons.py") for part in parts):
        return "iconos"
    if any(part.replace("\\", "/").endswith("tools/bench_silvestre.py") for part in parts):
        return "banco"
    if any(part.replace("\\", "/").endswith("tools/check_docs.py") for part in parts):
        return DOCS_STEP
    if any(part.endswith("run_blender_tests.py") for part in parts):
        if "tests/rendimiento/blender" in parts:
            return "rendimiento-blender"
        return "blender"
    if "unittest" in parts:
        folder = parts[parts.index("-s", parts.index("discover")) + 1]
        return {
            "tests/unit": "unitarias",
            "tests/referencia": "referencia",
            "tests/rendimiento": "rendimiento",
        }[folder]
    raise AssertionError(f"orden inesperada: {parts}")


TEST_STEPS = ("unitarias", "referencia", "rendimiento", "blender", "rendimiento-blender")


def suite_of(step: str, cmd: Sequence[str]) -> tuple[str, str]:
    """Carpeta y patrón de una orden de pruebas simulada (los de ``unittest`` y del
    lanzador por defecto si la orden no los da)."""
    parts = [str(part) for part in cmd]
    if step in ("blender", "rendimiento-blender"):
        folder = parts[parts.index("--carpeta") + 1]
        pattern = parts[parts.index("--patron") + 1] if "--patron" in parts else "test_*.py"
    else:
        folder = parts[parts.index("-s", parts.index("discover")) + 1]
        pattern = parts[parts.index("-p") + 1] if "-p" in parts else "test*.py"
    return folder, pattern


def disk_modules(root: Path, folder: str, pattern: str) -> list[str]:
    """Módulos de prueba de ``folder`` en disco (cálculo propio de la prueba, sin
    ``gbtools.discovery``)."""
    found: list[str] = []
    for path in sorted((root / folder).rglob("*.py")):
        if "__pycache__" not in path.parts and fnmatch.fnmatch(path.name, pattern):
            found.append(path.relative_to(root).with_suffix("").as_posix().replace("/", "."))
    return found


@dataclass
class Call:
    step: str
    cmd: list[str]
    env: dict[str, str]
    cwd: Path | None
    timeout: float | None
    profile_existed: bool | None


Result = tuple[int, str, str] | BaseException


class FakeRunner:
    """Ejecutor simulado: anota cada orden y devuelve la salida fijada para su paso.

    Con ``loaded=True`` (por defecto), un paso de pruebas que termina con 0 nombra al
    principio de su salida cada módulo de prueba que hay en disco (``unittest -v``).
    ``effects`` hace algo en la carpeta de trabajo (la raíz) cuando se ejecuta un paso,
    como una prueba que escribe donde no debe.
    """

    def __init__(
        self,
        overrides: Mapping[str, Result] | None = None,
        loaded: bool = True,
        effects: Mapping[str, Callable[[Path], object]] | None = None,
    ) -> None:
        self.results: dict[str, Result] = {**DEFAULT_RESULTS, **(overrides or {})}
        self.calls: list[Call] = []
        self.loaded = loaded
        self.effects = dict(effects or {})

    def __call__(
        self,
        cmd: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: Path | None = None,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        step = step_of(cmd)
        environment = dict(env or {})
        profile = environment.get("BLENDER_USER_RESOURCES")
        self.calls.append(
            Call(
                step,
                [str(part) for part in cmd],
                environment,
                cwd,
                timeout,
                Path(profile).is_dir() if profile else None,
            )
        )
        if step in self.effects and cwd is not None:
            self.effects[step](Path(cwd))
        result = self.results[step]
        if isinstance(result, BaseException):
            raise result
        code, stdout, stderr = result
        if self.loaded and code == 0 and step in TEST_STEPS and cwd is not None:
            heads = [
                f"test_cargado ({module}.Cargado.test_cargado) ... ok\n"
                for module in disk_modules(Path(cwd), *suite_of(step, cmd))
            ]
            stderr = "".join(heads) + stderr
        return subprocess.CompletedProcess(list(cmd), code, stdout, stderr)

    def steps(self) -> list[str]:
        return [call.step for call in self.calls]

    def call(self, step: str) -> Call:
        found = [call for call in self.calls if call.step == step]
        if len(found) != 1:
            raise AssertionError(f"«{step}» se ejecutó {len(found)} veces")
        return found[0]


@dataclass
class Outcome:
    code: int
    out: str
    err: str
    runner: FakeRunner


def run_check(
    *args: str,
    runner: FakeRunner | None = None,
    executable: str | None = None,
    modules: Sequence[str] = (),
    locate: Callable[[tuple[int, int, int]], BlenderInstall] | None = None,
    root: Path = ROOT,
    **kwargs: object,
) -> Outcome:
    """Ejecuta ``check.main`` con el ejecutor simulado y recoge la salida."""
    runner = FakeRunner() if runner is None else runner
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = check.main(
            list(args),
            root=root,
            runner=runner,
            locate=locate if locate is not None else (lambda minimum: INSTALL),
            executable=str(INSTALL.python) if executable is None else executable,
            loaded_modules=modules,
            **kwargs,
        )
    return Outcome(code, out.getvalue(), err.getvalue(), runner)


def _step_line(out: str, name: str) -> str:
    lines = [line for line in out.splitlines() if re.match(rf"^  \S+\s+{name}\s", line)]
    if len(lines) != 1:
        raise AssertionError(f"no hay una línea de «{name}» en:\n{out}")
    return lines[0]


def _python_env() -> dict[str, str]:
    return blender.python_env(ROOT)


def _manifest_root(
    files: Mapping[str, str] | None = None,
) -> contextlib.AbstractContextManager[Path]:
    """Raíz temporal con el manifiesto real y ``files``: ``check.main`` la acepta."""
    manifest = (ROOT / EXT / "blender_manifest.toml").read_bytes()
    return temp_tree({f"{EXT}/blender_manifest.toml": manifest, **(files or {})})


def _project_root(docs: bool = True) -> contextlib.AbstractContextManager[Path]:
    """Carpeta del proyecto temporal: el código (con el manifiesto real) en
    ``Geoblender/`` y, con ``docs``, la documentación en la carpeta madre."""
    manifest = (ROOT / EXT / "blender_manifest.toml").read_bytes()
    files: dict[str, str | bytes] = {
        f"{CODE_DIR_IN_DOCS}/{EXT}/blender_manifest.toml": manifest
    }
    if docs:
        files[DOCS_MARKER] = "# Constitución\n"
    return temp_tree(files)


def _resources_file(*names: str) -> dict[str, str]:
    """``tests/support/resources.py`` de una raíz temporal con la lista cerrada de
    recursos ``names`` (la que amplía cada spec con los suyos; T47)."""
    return {"tests/support/resources.py": f"{SPDX}RESOURCES: tuple[str, ...] = {names!r}\n"}


class StepsTest(unittest.TestCase):
    def test_steps_run_in_order(self) -> None:
        """RF-001-06: unitarias, referencia, licencias, manifiesto y blender, en ese
        orden, con las órdenes del plan (§5.4.7) y desde la raíz del repositorio."""
        result = run_check()
        self.assertEqual(result.code, 0, result.out + result.err)
        runner = result.runner
        self.assertEqual(runner.steps(), MANDATORY)
        self.assertEqual(
            runner.call("unitarias").cmd,
            blender.python_cmd(
                INSTALL,
                *RETURN_VALUE_IS_ERROR,
                "-m",
                "unittest",
                "discover",
                "-v",
                "-s",
                "tests/unit",
                "-t",
                ".",
            ),
        )
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
            env = runner.call(step).env
            with self.subTest(paso=step):
                for key in ("PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "PYTHONNOUSERSITE"):
                    self.assertEqual(env[key], expected_env[key])

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

    def test_extra_step_slot(self) -> None:
        """RF-001-06: otra spec añade un paso en su lugar de la tabla (p. ej. «iconos»
        de la 003, tras «licencias») con los mismos estados y códigos."""

        def icons(ctx: check.Context) -> list[check.Run]:
            return [ctx.python("tools/build_icons.py", "--check")]

        names = [step.name for step in check.STEPS]
        self.assertEqual(names[: len(MANDATORY)], MANDATORY)
        position = names.index("licencias") + 1
        steps = (*check.STEPS[:position], check.Step("iconos", icons), *check.STEPS[position:])
        runner = FakeRunner({"iconos": (0, "iconos: correcto\n", "")})
        result = run_check(runner=runner, steps=steps)
        self.assertEqual(result.code, 0, result.out)
        self.assertEqual(
            runner.steps(),
            ["unitarias", "referencia", "licencias", "iconos", "manifiesto", "blender"],
        )
        self.assertEqual(
            runner.call("iconos").cmd,
            blender.python_cmd(INSTALL, "tools/build_icons.py", "--check"),
        )
        self.assertRegex(_step_line(result.out, "iconos"), r"^  correcto  iconos\s")

        runner = FakeRunner({"iconos": (1, "icons/a.png: hash distinto\n", "")})
        result = run_check(runner=runner, steps=steps)
        self.assertEqual(result.code, 1)
        self.assertIn("icons/a.png: hash distinto", result.out)
        self.assertIn("«iconos»", result.out.strip().splitlines()[-1])


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


SPDX = "# SPDX-License-Identifier: GPL-3.0-or-later\n"


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
        ``--python-exit-code 1``, sobre ``tests/blender``."""
        result = run_check()
        cmd = result.runner.call("blender").cmd
        self.assertEqual(
            cmd,
            blender.background_cmd(
                INSTALL,
                ROOT / "tools" / "run_blender_tests.py",
                "--carpeta",
                "tests/blender",
            ),
        )
        self.assertEqual(cmd[1:5], ["-b", "--factory-startup", "--python-exit-code", "1"])
        self.assertEqual(result.runner.call("blender").cwd, ROOT)

    def test_blender_env_uses_temp_profile(self) -> None:
        """RF-001-09: los pasos «manifiesto» y «blender» usan el mismo perfil temporal
        en ``%TEMP%`` (nunca el del usuario ni el repositorio), sin las variables
        ``BLENDER_USER_*`` que lo sustituirían; el perfil existe mientras se ejecutan y
        se borra al terminar, también si un paso falla o el ejecutor lanza."""
        planted = {name: str(ROOT / "perfil-real") for name in USER_VARIABLES}
        with mock.patch.dict(os.environ, planted):
            result = run_check()
        manifest_env = result.runner.call("manifiesto").env
        blender_env = result.runner.call("blender").env
        profile = Path(blender_env["BLENDER_USER_RESOURCES"])
        self.assertEqual(Path(manifest_env["BLENDER_USER_RESOURCES"]), profile)
        for env in (manifest_env, blender_env):
            for name in USER_VARIABLES:
                self.assertNotIn(name, env)
            self.assertEqual(env["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertTrue(result.runner.call("blender").profile_existed)
        self.assertTrue(result.runner.call("manifiesto").profile_existed)
        temp = Path(tempfile.gettempdir()).resolve()
        self.assertEqual(profile.resolve().parents[1], temp)
        self.assertTrue(profile.parent.name.startswith(check.TEMP_PREFIX))
        appdata = Path(os.environ.get("APPDATA", str(ROOT))).resolve()
        for forbidden in (ROOT.resolve(), appdata):
            self.assertFalse(profile.resolve().is_relative_to(forbidden), forbidden)
        self.assertFalse(profile.parent.exists())

        result = run_check(runner=FakeRunner({"blender": (1, "", "FAIL: x\n")}))
        profile = Path(result.runner.call("blender").env["BLENDER_USER_RESOURCES"])
        self.assertFalse(profile.parent.exists())

        runner = FakeRunner({"blender": RuntimeError("fallo inesperado del ejecutor")})
        with self.assertRaises(RuntimeError):
            run_check(runner=runner)
        profile = Path(runner.call("blender").env["BLENDER_USER_RESOURCES"])
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
        value = result.runner.call("unitarias").env[imports.ENV_BLENDER_MODULES]
        self.assertEqual(
            sorted(value.split(",")),
            ["_rna_info", "bl_keymap_utils", "bl_operators", "keyingsets_builtins"],
        )


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

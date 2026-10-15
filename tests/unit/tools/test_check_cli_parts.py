# SPDX-License-Identifier: GPL-3.0-or-later
"""La comprobación completa, ``tools/check.py``, con un ejecutor simulado: las partes de
cada paso, el paso «motor» y el reparto por tiempo.

- RNF-007-01, RF-001-06 (spec 003, T40): las pruebas unitarias y las de Blender se
  reparten en varias partes (``tools/unittest_part.py`` y ``run_blender_tests.py
  --parte``) que se ejecutan a la vez dentro de su paso, cada parte de Blender con su
  propio perfil temporal; los pasos siguen uno tras otro y en su orden, con la misma
  línea, el mismo resumen y el mismo código. Un fichero cargado en cualquier parte
  cuenta como cargado; si las partes no suman las pruebas que dicen haber descubierto,
  el paso falla («reparto incompleto»); y con Ctrl+C se paran las partes en marcha y se
  borra la carpeta temporal.
- RF-004-28 (spec 004, T30; 0.4, spec 005, T50): con ``--completo`` y el motor de cálculo
  de pruebas, el paso «motor» ejecuta ``tests/unit`` de cada paquete de dominio con el numpy
  del motor (el Python de Blender con ``-S`` y la carpeta ``site`` del motor al principio de
  ``PYTHONPATH``), a la vez que «blender» (no cabe después: RNF-001-01), y su línea va tras
  la de «blender»; sin motor, se omite con ``[ENTORNO] runtime`` y la orden
  ``tools/make_runtime.py``: «VERDE CON OMISIONES»; sin ``--completo``, no se ejecuta
  (``test_check_cli_options.CompleteStepTest``). Salvo en esas pruebas, el motor de las
  demás es uno simulado (``find_runtime``), y el paso «motor» no cuenta en el orden de los
  pasos (``FakeRunner.steps``): va a la vez que «blender».
- RNF-001-01, RNF-007-01 (spec 004, T39): las partes de «unitarias», «blender» y «motor»
  se reparten por la duración medida de cada módulo, guardada fuera del repositorio (un
  almacén en la carpeta temporal del sistema, uno por raíz): sin medidas, como siempre;
  cada parte escribe las suyas y, al terminar, sustituyen a las guardadas. Salvo en esas
  pruebas, no hay almacén (``times_store``) y las órdenes son las de siempre.
- RNF-001-01 (spec 006, T59): los casos de referencia también van en partes a la vez.

Las ayudas (el ejecutor simulado y ``run_check``), en ``tests/support/check_cli.py``
(spec 006, T46: estas pruebas estaban en ``test_check_cli.py``, partido en cuatro).
"""

import _thread
import os
import shutil
import tempfile
import threading
import time
import unittest
from collections.abc import Sequence
from pathlib import Path
from unittest import mock

from tests.support.check_cli import (
    Call,
    DOMAIN_FOLDERS,
    FAKE_SITE,
    FakeRunner,
    HARNESS,
    INSTALL,
    MANDATORY,
    OPTIONAL,
    RETURN_VALUE_IS_ERROR,
    RUNTIME,
    Result,
    SPDX,
    _manifest_root,
    _python_env,
    _resources_file,
    _seconds_of,
    _step_line,
    _unittest_output,
    blender_part_cmd,
    disk_modules,
    many_cpus,
    reference_part_cmd,
    run_check,
    suite_of,
    unit_part_cmd,
)
from tests.support.repo import ROOT, tools_on_path
from tests.support.resources import SKIP_PREFIX

tools_on_path()

import check  # noqa: E402
from gbtools import blender, discovery, parts  # noqa: E402


TWO_UNIT_MODULES = {
    "tests/__init__.py": SPDX,
    "tests/unit/__init__.py": SPDX,
    "tests/unit/test_a.py": SPDX,
    "tests/unit/test_b.py": SPDX,
}
HEAD_A = "test_x (tests.unit.test_a.A.test_x) ... ok"
HEAD_B = "test_y (tests.unit.test_b.B.test_y) ... ok"
HEAD_OTHER = "test_z (tests.unit.otro.C.test_z) ... ok"  # un módulo que no está en disco


def _part(part: int, count: int, ran: int, total: int, body: str, verdict: str = "OK") -> Result:
    """La salida de una parte de las unitarias: su línea y el resumen de ``unittest``."""
    head = parts.line(part, count, ran, total)
    return (0, "", head + "\n" + _unittest_output(ran, verdict, body))


class PartsTest(unittest.TestCase):
    """Spec 003, T40 (RNF-007-01: ≤ 40 s sin quitar ninguna prueba): dentro de su paso,
    las pruebas unitarias y las de Blender se reparten en partes que se ejecutan a la
    vez; los pasos siguen uno tras otro y en su orden (RF-001-06)."""

    def test_part_count(self) -> None:
        """RNF-007-01: tantas partes como pide el paso, sin pasar del número de módulos
        de prueba en disco ni del de procesadores, y al menos una; las unitarias y las de
        Blender piden más de una."""
        self.assertGreaterEqual(check.UNIT_PARTS, 2)
        self.assertGreaterEqual(check.BLENDER_PARTS, 2)
        self.assertEqual(check.part_count(4, 76, 24), 4)
        self.assertEqual(check.part_count(4, 2, 24), 2)
        self.assertEqual(check.part_count(4, 76, 3), 3)
        self.assertEqual(check.part_count(4, 0, 24), 1)
        with mock.patch("os.cpu_count", return_value=2):
            self.assertEqual(check.part_count(4, 76), 2)
        with mock.patch("os.cpu_count", return_value=None):  # no se sabe: una
            self.assertEqual(check.part_count(4, 76), 1)

    def test_part_commands(self) -> None:
        """RNF-007-01, RF-001-09: en el repositorio real, «unitarias» son las partes
        1…n de ``tools/unittest_part.py --parte i/n discover -v -s tests/unit -t .``
        (con el ``-W`` y el entorno de siempre) y «blender», las del lanzador con
        ``--parte i/m``; el resumen, igual que con una orden (la línea y su número de
        pruebas)."""
        with many_cpus():
            result = run_check()
        self.assertEqual(result.code, 0, result.out)
        runner = result.runner
        units = runner.calls_of("unitarias")
        expected = [(i, check.UNIT_PARTS) for i in range(1, check.UNIT_PARTS + 1)]
        self.assertEqual([call.part for call in units], expected)
        python_env = _python_env()
        for call in units:
            with self.subTest(parte=call.part):
                self.assertEqual(call.cmd, unit_part_cmd(*(call.part or (1, 1))))
                self.assertEqual(call.cwd, ROOT)
                for key in ("PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "PYTHONNOUSERSITE"):
                    self.assertEqual(call.env[key], python_env[key])
        blenders = runner.calls_of("blender")
        expected = [(i, check.BLENDER_PARTS) for i in range(1, check.BLENDER_PARTS + 1)]
        self.assertEqual([call.part for call in blenders], expected)
        self.assertEqual(runner.steps(), MANDATORY)
        for step, count in (("unitarias", 217), ("blender", 12)):
            with self.subTest(paso=step):
                self.assertRegex(
                    _step_line(result.out, step),
                    rf"^  correcto  {step}\s+\d+,\d s  \({count} pruebas\)$",
                )
        last = result.out.strip().splitlines()[-1]
        self.assertRegex(last, r"^RESULTADO: VERDE \(\d+,\d s\)$")
        self.assertNotIn("PARTE", result.out)

    def test_reference_in_parts(self) -> None:
        """RNF-001-01 (spec 006, T59): en el repositorio real, «referencia» son las partes
        1…n de ``tools/unittest_part.py --parte i/n discover -v -s tests/referencia -t .``
        (n = ``REFERENCE_PARTS``, sin pasar de sus módulos), con el entorno de siempre y a la
        vez; su línea, la de una orden, con el número de casos. Sin casos de referencia en
        disco, la orden de siempre y «sin casos» (``test_empty_reference_suite_ok``)."""
        together = threading.Barrier(2, timeout=15)

        def meet(call: Call) -> None:
            if call.step == "referencia" and call.part is not None and call.part[0] <= 2:
                together.wait()

        with many_cpus():
            result = run_check(runner=FakeRunner(on_call=meet))
        self.assertEqual(result.code, 0, result.out)
        self.assertFalse(together.broken)
        modules = discovery.expected_modules(ROOT / "tests" / "referencia", "test*.py", ROOT)
        count = min(check.REFERENCE_PARTS, len(modules))
        self.assertGreaterEqual(count, 2)
        calls = result.runner.calls_of("referencia")
        self.assertEqual([call.part for call in calls], [(i, count) for i in range(1, count + 1)])
        python_env = _python_env()
        for call in calls:
            with self.subTest(parte=call.part):
                self.assertEqual(call.cmd, reference_part_cmd(*(call.part or (1, 1))))
                for key in ("PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "PYTHONNOUSERSITE"):
                    self.assertEqual(call.env[key], python_env[key])
        self.assertRegex(_step_line(result.out, "referencia"),
                         r"^  correcto  referencia\s+\d+,\d s  \(2 pruebas\)$")
        self.assertEqual(result.runner.steps(), MANDATORY)

    def test_shared_copy_for_the_blender_parts(self) -> None:
        """RNF-001-01, RNF-007-01 (spec 006, T48): la copia de pruebas de la extensión se
        prepara una vez, en otro hilo, en ``copia/`` de la carpeta temporal de la
        comprobación (``gbtools.ext_copy.prepare``), y cada parte de «blender» la recibe con
        ``--copia``; las demás órdenes, las de siempre. Si no se puede preparar, un aviso y
        cada parte hace la suya, como antes; el resultado no cambia."""
        prepared: list[tuple[Path, Path, str]] = []

        def prepare(root: Path, target: Path) -> Path:
            prepared.append((root, target, threading.current_thread().name))
            return target

        with many_cpus():
            result = run_check(test_copy=prepare)
        self.assertEqual(result.code, 0, result.out)
        ((root, target, thread),) = prepared
        self.assertEqual(root, ROOT)
        self.assertEqual(target.name, check.COPY_FOLDER)
        self.assertTrue(target.parent.name.startswith(check.TEMP_PREFIX))
        self.assertNotEqual(thread, threading.main_thread().name)
        for call in result.runner.calls_of("blender"):
            with self.subTest(parte=call.part):
                expected = blender_part_cmd(*(call.part or (1, 1)))
                self.assertEqual(call.cmd, [*expected, "--copia", str(target)])
        for call in result.runner.calls_of("unitarias"):
            self.assertNotIn("--copia", call.cmd)
        self.assertFalse(target.parent.exists())

        def broken(root: Path, target: Path) -> Path:
            raise OSError(28, "No queda espacio en el disco (simulado)")

        with many_cpus():
            result = run_check(test_copy=broken)
        self.assertEqual(result.code, 0, result.out)
        self.assertIn("AVISO: no se pudo preparar la copia de la extensión para las partes de "
                      "«blender»", result.out)
        self.assertIn("No queda espacio en el disco (simulado)", result.out)
        for call in result.runner.calls_of("blender"):
            self.assertEqual(call.cmd, blender_part_cmd(*(call.part or (1, 1))))

    def test_bytecode_folder_for_the_python_steps(self) -> None:
        """RNF-001-01 (spec 005, T44): el código compilado de las órdenes de Python va en la
        carpeta de la raíz fuera del repositorio (``gbtools.pyc_cache.default_folder``), que
        se refresca una vez, en otro hilo, con la raíz y, con ``--completo``, la carpeta
        ``site`` del motor de cálculo de pruebas (``pyc_cache.prepare``; sin la opción,
        «motor» no se ejecuta y su carpeta no se repasa: spec 005, T50); cada orden de Python
        («unitarias», «referencia», «motor», «licencias») la recibe en
        ``PYTHONPYCACHEPREFIX``, y las de Blender no. Sin carpeta, las órdenes de siempre, sin
        la variable; si el refresco falla, un aviso y el resultado no cambia."""
        folder = Path(tempfile.mkdtemp(prefix="gb-pyc-check-"))
        self.addCleanup(shutil.rmtree, folder, True)
        prepared: list[tuple[Path, Path, list[Path], str]] = []

        def prepare(target: Path, root: Path, sites: Sequence[Path]) -> None:
            prepared.append((target, root, list(sites), threading.current_thread().name))

        with many_cpus():
            result = run_check("--completo", bytecode=lambda root: folder,
                               refresh_bytecode=prepare)
        self.assertEqual(result.code, 0, result.out)
        ((target, root, sites, thread),) = prepared
        self.assertEqual((target, root, sites), (folder, ROOT, [FAKE_SITE]))
        self.assertNotEqual(thread, threading.main_thread().name)
        python_steps = ("unitarias", "referencia", RUNTIME, "licencias")
        for step in python_steps:
            self.assertTrue(result.runner.calls_of(step), step)
            for call in result.runner.calls_of(step):
                with self.subTest(paso=step, parte=call.part):
                    self.assertEqual(call.env[check.ENV_BYTECODE], str(folder))
        for call in result.runner.calls_of("blender"):
            self.assertNotEqual(call.env.get(check.ENV_BYTECODE), str(folder))

        prepared.clear()
        with many_cpus():
            result = run_check(bytecode=lambda root: folder, refresh_bytecode=prepare)
        self.assertEqual(result.code, 0, result.out)
        ((target, root, sites, _thread),) = prepared
        self.assertEqual((target, root, sites), (folder, ROOT, []))
        self.assertEqual([call.part for call in result.runner.calls_of(RUNTIME)], [])

        with many_cpus():
            result = run_check()
        self.assertEqual(result.code, 0, result.out)
        for step in python_steps:
            for call in result.runner.calls_of(step):
                self.assertNotIn(check.ENV_BYTECODE, call.env)

        def broken(target: Path, root: Path, sites: Sequence[Path]) -> None:
            raise OSError(28, "No queda espacio en el disco (simulado)")

        with many_cpus():
            result = run_check(bytecode=lambda root: folder, refresh_bytecode=broken)
        self.assertEqual(result.code, 0, result.out)
        self.assertIn("AVISO: no se pudo preparar el código compilado de las pruebas", result.out)
        self.assertIn("No queda espacio en el disco (simulado)", result.out)

    def test_few_modules(self) -> None:
        """RNF-007-01: con un solo módulo de prueba en disco, la orden de siempre, sin
        partes (``-m unittest discover`` y el lanzador sin ``--parte``); con dos, dos
        partes."""
        files = {
            "tests/__init__.py": SPDX,
            "tests/unit/__init__.py": SPDX,
            "tests/unit/test_a.py": SPDX,
            "tests/blender/__init__.py": SPDX,
            "tests/blender/test_b.py": SPDX,
        }
        with _manifest_root(files) as tmp, many_cpus():
            result = run_check(root=tmp)
            self.assertEqual(result.code, 0, result.out)
            single = blender.python_cmd(
                INSTALL, *RETURN_VALUE_IS_ERROR, "-m", "unittest", "discover", "-v",
                "-s", "tests/unit", "-t", ".",
            )
            self.assertEqual(result.runner.call("unitarias").cmd, single)
            launcher = blender.background_cmd(
                INSTALL, tmp / "tools" / "run_blender_tests.py", "--carpeta", "tests/blender"
            )
            self.assertEqual(result.runner.call("blender").cmd, launcher)

        with _manifest_root(TWO_UNIT_MODULES) as tmp, many_cpus():
            result = run_check(root=tmp)
        self.assertEqual(result.code, 0, result.out)
        self.assertEqual(
            [call.part for call in result.runner.calls_of("unitarias")], [(1, 2), (2, 2)]
        )

    def test_parts_run_at_the_same_time(self) -> None:
        """RNF-007-01: las partes de un paso se ejecutan a la vez: todas llegan a una
        barrera que, una tras otra, no se alcanzaría; la duración del paso cubre la de
        sus partes (una espera de 0,3 s en cada una)."""
        barriers = {
            "unitarias": threading.Barrier(check.UNIT_PARTS, timeout=15),
            "blender": threading.Barrier(check.BLENDER_PARTS, timeout=15),
        }

        def meet(call: Call) -> None:
            if call.part is not None and call.step in barriers:
                barriers[call.step].wait()
                time.sleep(0.3)

        runner = FakeRunner(on_call=meet)
        with many_cpus():
            result = run_check(runner=runner)
        self.assertEqual(result.code, 0, result.out)
        for step, barrier in barriers.items():
            with self.subTest(paso=step):
                self.assertFalse(barrier.broken)
                self.assertGreaterEqual(_seconds_of(_step_line(result.out, step)), 0.3)

    def test_steps_one_after_another(self) -> None:
        """RF-001-06: los pasos, también los opcionales, siguen uno tras otro y en el
        orden de la tabla: ninguna orden de un paso empieza antes de que terminen todas
        las del anterior, y el resumen da sus líneas en ese orden. La excepción es
        «motor» (spec 004, RF-004-28), que va a la vez que «blender»: empieza después de
        «manifiesto» y el paso siguiente («arnés») espera a que termine."""
        with many_cpus():
            result = run_check("--completo", "--rendimiento", "--banco")
        self.assertEqual(result.code, 0, result.out)
        runner = result.runner
        order = runner.steps()
        self.assertEqual(order, [*MANDATORY, HARNESS, *OPTIONAL])
        groups = [[c for c in runner.calls if c.step == step] for step in order]
        for before, after in zip(groups, groups[1:]):
            with self.subTest(paso=after[0].step):
                self.assertLessEqual(max(c.ended for c in before), min(c.started for c in after))
        motor = runner.calls_of(RUNTIME)
        self.assertTrue(motor)
        manifest_end = max(c.ended for c in runner.calls_of("manifiesto"))
        self.assertLessEqual(manifest_end, min(c.started for c in motor))
        self.assertLessEqual(max(c.ended for c in motor),
                             min(c.started for c in runner.calls_of(HARNESS)))
        names = [*MANDATORY, RUNTIME, HARNESS, "rendimiento", "banco"]
        positions = [result.out.index(_step_line(result.out, name)) for name in names]
        self.assertEqual(positions, sorted(positions))

    def test_failing_part(self) -> None:
        """RF-001-06: si falla una parte (la 2), su paso falla con su salida (una vez) y
        su orden (``--parte 2/n``), los demás pasos se ejecutan y el código es 1."""
        red = _unittest_output(
            5, "FAILED (failures=1)", "FAIL: test_roja (tests.unit.x.X.test_roja)"
        )
        broken = (1, "", "RuntimeError: rota\n")
        runner = FakeRunner({"unitarias#2": (1, "", red), "blender#2": broken})
        with many_cpus():
            result = run_check(runner=runner)
        self.assertEqual(result.code, 1, result.out)
        self.assertEqual(runner.steps(), MANDATORY)
        for step, text in (("unitarias", "FAIL: test_roja"), ("blender", "RuntimeError: rota")):
            with self.subTest(paso=step):
                line = _step_line(result.out, step)
                self.assertTrue(line.lstrip().startswith("fallo"), line)
                self.assertIn("código 1", line)
                self.assertEqual(result.out.count(text), 1, result.out)
        self.assertIn(f"{parts.OPTION} 2/{check.UNIT_PARTS} discover", result.out)
        self.assertIn(f"{parts.OPTION} 2/{check.BLENDER_PARTS}", result.out)
        last = result.out.strip().splitlines()[-1]
        self.assertRegex(
            last, r"^RESULTADO: NO VERDE \(\d+,\d s\): fallan «unitarias», «blender»$"
        )

    def test_loaded_in_any_part(self) -> None:
        """RF-001-06 (T35): un módulo que nombra la salida de cualquier parte está
        cargado; uno que no nombra ninguna (y las partes repartieron igual: ninguna
        ejecutó un fichero de otra) es «1 fichero sin cargar», dicho una vez, con la pista
        de ``__init__.py``; las pruebas de todas las partes se suman en la línea del
        paso."""
        loaded = {
            "unitarias#1": _part(1, 2, 1, 2, HEAD_A),
            "unitarias#2": _part(2, 2, 1, 2, HEAD_B),
        }
        with _manifest_root(TWO_UNIT_MODULES) as tmp, many_cpus():
            result = run_check(runner=FakeRunner(loaded, loaded=False), root=tmp)
            self.assertEqual(result.code, 0, result.out)
            self.assertIn("(2 pruebas)", _step_line(result.out, "unitarias"))

            missing = {**loaded, "unitarias#2": _part(2, 2, 1, 2, HEAD_OTHER)}
            result = run_check(runner=FakeRunner(missing, loaded=False), root=tmp)
        self.assertEqual(result.code, 1, result.out)
        line = _step_line(result.out, "unitarias")
        self.assertTrue(line.lstrip().startswith("fallo"), line)
        self.assertIn("1 fichero sin cargar", line)
        self.assertNotIn("reparto incompleto", line)
        self.assertIn("tests/unit/test_b.py", result.out)
        self.assertEqual(result.out.count("FICHEROS DE PRUEBA SIN CARGAR"), 1, result.out)
        self.assertIn(discovery.HINT, result.out)

    def test_different_distribution(self) -> None:
        """RF-001-06 (convergencia, T45): si las partes no repartieron igual (una ejecuta
        un fichero que también ejecutó otra, o dicen totales distintos) y por eso un
        fichero no lo carga ninguna, el diagnóstico es «reparto incompleto», con el
        fichero, y no la pista de ``__init__.py``; también si además falla una prueba."""
        red = _part(2, 2, 1, 2, HEAD_A.replace("... ok", "... FAIL"), "FAILED (failures=1)")
        cases = {
            "repetido": (_part(1, 2, 1, 2, HEAD_A), _part(2, 2, 1, 2, HEAD_A),
                         "tests/unit/test_a.py, en las partes 1 y 2"),
            "totales distintos": (_part(1, 2, 1, 2, HEAD_A), _part(2, 2, 1, 3, HEAD_OTHER),
                                  "total"),
            "repetido y rojo": (_part(1, 2, 1, 2, HEAD_A), (1, "", red[2]),
                                "tests/unit/test_a.py"),
        }
        with _manifest_root(TWO_UNIT_MODULES) as tmp, many_cpus():
            for name, (first, second, text) in cases.items():
                with self.subTest(caso=name):
                    outputs = {"unitarias#1": first, "unitarias#2": second}
                    result = run_check(runner=FakeRunner(outputs, loaded=False), root=tmp)
                    self.assertEqual(result.code, 1, result.out)
                    line = _step_line(result.out, "unitarias")
                    self.assertTrue(line.lstrip().startswith("fallo"), line)
                    self.assertIn("reparto incompleto", line)
                    self.assertNotIn("sin cargar", line)
                    self.assertEqual(result.out.count("REPARTO INCOMPLETO"), 1, result.out)
                    self.assertIn(text, result.out)
                    self.assertIn("tests/unit/test_b.py", result.out)
                    self.assertNotIn(discovery.HINT, result.out)
                    self.assertNotIn("FICHEROS DE PRUEBA SIN CARGAR", result.out)

    def test_partial_count(self) -> None:
        """RF-001-06 (convergencia, T45): si una parte termina sin el resumen de
        ``unittest`` (o sin poder contar sus pruebas), la línea del paso dice que su
        número es el de las partes que lo dieron («1 prueba en 1 de 2 partes»), además
        del fallo."""
        cut = (0, "", parts.line(2, 2, 1, 2) + "\n" + HEAD_B + "\n")
        crash = (1, "", parts.line(2, 2, 1, 2) + "\nRuntimeError: rota\n")
        with _manifest_root(TWO_UNIT_MODULES) as tmp, many_cpus():
            for name, second, text in (("sin resumen", cut, check.SUMMARY_MISSING),
                                       ("rota", crash, "código 1")):
                with self.subTest(caso=name):
                    outputs = {"unitarias#1": _part(1, 2, 1, 2, HEAD_A),
                               "unitarias#2": second}
                    result = run_check(runner=FakeRunner(outputs, loaded=False), root=tmp)
                    self.assertEqual(result.code, 1, result.out)
                    line = _step_line(result.out, "unitarias")
                    self.assertTrue(line.lstrip().startswith("fallo"), line)
                    self.assertIn("(1 prueba en 1 de 2 partes, ", line)
                    self.assertIn(text, line)
            outputs = {"unitarias#1": _part(1, 2, 1, 2, HEAD_A),
                       "unitarias#2": _part(2, 2, 1, 2, HEAD_B)}
            result = run_check(runner=FakeRunner(outputs, loaded=False), root=tmp)
        self.assertEqual(result.code, 0, result.out)
        self.assertNotIn(" de 2 partes", _step_line(result.out, "unitarias"))

    def test_parts_must_add_up(self) -> None:
        """RF-001-06: si una parte no dice su línea «PARTE i de n: r de T pruebas», si
        dice otra parte o si las partes no dicen el mismo total o no lo suman, el reparto
        perdió o repitió pruebas: el paso falla «reparto incompleto» con el motivo."""
        good = _part(1, 2, 1, 2, HEAD_A)
        cases = {
            "sin línea": (good, (0, "", _unittest_output(1, body=HEAD_B)), "parte 2"),
            "otra parte": (good, _part(1, 2, 1, 2, HEAD_B), "parte 2"),
            "totales distintos": (good, _part(2, 2, 1, 3, HEAD_B), "total"),
            "no suman": (_part(1, 2, 1, 3, HEAD_A), _part(2, 2, 1, 3, HEAD_B), "2 de 3"),
        }
        with _manifest_root(TWO_UNIT_MODULES) as tmp, many_cpus():
            for name, (first, second, text) in cases.items():
                with self.subTest(caso=name):
                    outputs = {"unitarias#1": first, "unitarias#2": second}
                    result = run_check(runner=FakeRunner(outputs, loaded=False), root=tmp)
                    self.assertEqual(result.code, 1, result.out)
                    line = _step_line(result.out, "unitarias")
                    self.assertTrue(line.lstrip().startswith("fallo"), line)
                    self.assertIn("reparto incompleto", line)
                    self.assertIn("REPARTO INCOMPLETO", result.out)
                    self.assertIn(text, result.out)
                    self.assertIn("«unitarias»", result.out.strip().splitlines()[-1])

    def test_module_lines_must_add_up(self) -> None:
        """RF-001-06 (spec 006, T48): las partes que reparten por ficheros dicen «PARTE i de
        n: m de M módulos»; si son 1…n, dicen el mismo total de módulos y lo suman, el paso
        es correcto y su línea cuenta las pruebas de todas; si una no dice la suya, dicen
        totales distintos o no suman, «reparto incompleto» con el motivo en módulos, como
        con las de pruebas."""

        def modules(part: int, chosen: int, total: int, body: str) -> Result:
            head = parts.module_line(part, 2, chosen, total)
            return (0, "", head + "\n" + _unittest_output(1, "OK", body))

        good = modules(1, 1, 2, HEAD_A)
        cases = {
            "sin línea": (good, _part(2, 2, 1, 2, HEAD_B), "cuántos módulos"),
            "totales distintos": (good, modules(2, 1, 3, HEAD_B), "total de módulos"),
            "no suman": (modules(1, 1, 3, HEAD_A), modules(2, 1, 3, HEAD_B), "2 de 3 módulos"),
        }
        with _manifest_root(TWO_UNIT_MODULES) as tmp, many_cpus():
            outputs = {"unitarias#1": good, "unitarias#2": modules(2, 1, 2, HEAD_B)}
            result = run_check(runner=FakeRunner(outputs, loaded=False), root=tmp)
            self.assertEqual(result.code, 0, result.out)
            self.assertRegex(_step_line(result.out, "unitarias"), r"\(2 pruebas\)")
            for name, (first, second, text) in cases.items():
                with self.subTest(caso=name):
                    outputs = {"unitarias#1": first, "unitarias#2": second}
                    result = run_check(runner=FakeRunner(outputs, loaded=False), root=tmp)
                    self.assertEqual(result.code, 1, result.out)
                    line = _step_line(result.out, "unitarias")
                    self.assertIn("reparto incompleto", line)
                    self.assertIn(text, result.out)
                    self.assertIn("PARTE 1 de 2: 1 de", result.out)

    def test_omissions_of_every_part(self) -> None:
        """RF-001-06: las omisiones por un recurso de todas las partes cuentan, cada una
        una vez, y el resultado es «VERDE CON OMISIONES (n)»."""
        skip = "skipped '" + SKIP_PREFIX + " symlink: active el modo de desarrollador'"
        verdict = "OK (skipped=1)"
        outputs = {
            "unitarias#1": _part(1, 2, 1, 2, HEAD_A.replace("... ok", f"... {skip}"), verdict),
            "unitarias#2": _part(2, 2, 1, 2, HEAD_B.replace("... ok", f"... {skip}"), verdict),
        }
        files = {**TWO_UNIT_MODULES, **_resources_file("symlink")}
        with _manifest_root(files) as tmp, many_cpus():
            result = run_check(runner=FakeRunner(outputs, loaded=False), root=tmp)
        self.assertEqual(result.code, 0, result.out)
        self.assertIn("(2 pruebas, 2 omitidas)", _step_line(result.out, "unitarias"))
        last = result.out.strip().splitlines()[-1]
        self.assertRegex(last, r"^RESULTADO: VERDE CON OMISIONES \(2\) ")
        self.assertIn("tests.unit.test_a.A.test_x", result.out)
        self.assertIn("tests.unit.test_b.B.test_y", result.out)

    def test_ctrl_c_stops_the_parts(self) -> None:
        """RF-001-09: con Ctrl+C mientras se ejecutan las partes, la comprobación para
        las órdenes en marcha (``blender.stop_all``), espera a sus hilos, borra su
        carpeta temporal (con los perfiles) y deja pasar la interrupción. La interrupción
        llega cuando ya están en marcha todas las partes de «blender» (la última en
        empezar la provoca): antes, con «motor» a la vez, a veces llegaba sin que hubiera
        empezado la tercera (spec 004, T30)."""
        stopped = threading.Event()
        begun: list[int] = []
        lock = threading.Lock()

        def interrupt(call: Call) -> None:
            if call.step == "blender" and call.part is not None:
                with lock:
                    begun.append(call.part[0])
                    last = len(begun) == check.BLENDER_PARTS
                if last:
                    _thread.interrupt_main()
                stopped.wait(15)

        runner = FakeRunner(on_call=interrupt)
        with (
            mock.patch.object(check.blender, "stop_all", side_effect=stopped.set) as stop,
            many_cpus(),
            self.assertRaises(KeyboardInterrupt),
        ):
            run_check("--completo", runner=runner)
        stop.assert_called()
        self.assertTrue(stopped.is_set())
        profiles = [Path(c.env["BLENDER_USER_RESOURCES"]) for c in runner.calls_of("blender")]
        self.assertEqual(len(profiles), check.BLENDER_PARTS)
        self.assertFalse(profiles[0].parent.exists())
        alive = [t for t in threading.enumerate() if t.name.startswith(check.THREAD_PREFIX)]
        self.assertEqual(alive, [])


def runtime_part_cmd(folder: str, part: int, count: int) -> list[str]:
    """La orden de la parte ``part`` de ``count`` de las pruebas de dominio de ``folder``
    con el numpy del motor (spec 004, T30): el Python de Blender sin su site-packages; con
    una sola parte, la de siempre (``-m unittest``)."""
    if count == 1:
        return blender.python_cmd(
            INSTALL, "-S", *RETURN_VALUE_IS_ERROR, "-m", "unittest", "discover", "-v",
            "-s", folder, "-t", ".",
        )
    return blender.python_cmd(
        INSTALL, "-S", *RETURN_VALUE_IS_ERROR, "tools/unittest_part.py", parts.OPTION,
        parts.label(part, count), "discover", "-v", "-s", folder, "-t", ".",
    )


def runtime_counts() -> dict[str, int]:
    """Las partes de «motor» de cada carpeta de dominio del repositorio real con 24
    procesadores: ``RUNTIME_PARTS``, sin pasar de sus módulos de prueba (``part_count``;
    una carpeta nueva con menos módulos, en menos partes; spec 006, T38)."""
    return {
        folder: check.part_count(check.RUNTIME_PARTS,
                                 len(disk_modules(ROOT, folder, "test*.py")), 24)
        for folder in DOMAIN_FOLDERS
    }


class RuntimeStepTest(unittest.TestCase):
    """RF-004-28 (spec 004, T30): el paso «motor», con ``--completo`` (spec 004 0.4; spec 005,
    T50)."""

    def test_domain_tests_with_the_engine_numpy(self) -> None:
        """RF-004-28: con el motor de pruebas, «motor» ejecuta ``tests/unit`` de cada
        paquete de dominio (los de ``imports.LEVELS`` con carpeta) en partes, con el Python
        de Blender sin su site-packages (``-S``: ni su numpy) y la carpeta ``site`` del
        motor al principio de ``PYTHONPATH``, a la vez que «blender» (sus partes y las de
        «blender» llegan a una barrera); su línea va tras la de «blender» y suma sus
        pruebas; si una parte falla, el paso falla y el código es 1."""
        self.assertIn("tests/unit/core", DOMAIN_FOLDERS)
        self.assertIn("tests/unit/jobs", DOMAIN_FOLDERS)
        counts = runtime_counts()
        self.assertEqual(counts["tests/unit/core"], check.RUNTIME_PARTS)
        # Una carpeta en una sola parte (con un solo módulo) va después, como toda orden
        # sin partes: no llega a la barrera.
        parted = sum(count for count in counts.values() if count > 1)
        together = threading.Barrier(check.BLENDER_PARTS + parted, timeout=15)

        def meet(call: Call) -> None:
            if call.step in ("blender", RUNTIME) and call.part is not None:
                together.wait()

        with many_cpus():
            result = run_check("--completo", runner=FakeRunner(on_call=meet))
        self.assertEqual(result.code, 0, result.out)
        self.assertFalse(together.broken)
        runner = result.runner
        self.assertEqual(runner.steps(), [*MANDATORY, HARNESS])
        calls = runner.calls_of(RUNTIME)
        expected = [runtime_part_cmd(folder, i, count)
                    for folder, count in counts.items() for i in range(1, count + 1)]
        self.assertCountEqual([call.cmd for call in calls], expected)
        python_env = _python_env()
        for call in calls:
            with self.subTest(parte=call.part, orden=call.cmd[-3]):
                self.assertEqual(call.cwd, ROOT)
                self.assertEqual(
                    call.env["PYTHONPATH"],
                    os.pathsep.join([str(FAKE_SITE), python_env["PYTHONPATH"]]),
                )
                for key in ("PYTHONDONTWRITEBYTECODE", "PYTHONNOUSERSITE"):
                    self.assertEqual(call.env[key], python_env[key])
        line = _step_line(result.out, RUNTIME)
        self.assertRegex(
            line, rf"^  correcto  {RUNTIME}\s+\d+,\d s  \({40 * len(DOMAIN_FOLDERS)} pruebas\)$"
        )
        self.assertLess(result.out.index(_step_line(result.out, "blender")),
                        result.out.index(line))
        self.assertRegex(result.out.strip().splitlines()[-1], r"^RESULTADO: VERDE \(")

    def test_failing_part_fails_the_step(self) -> None:
        """RF-004-28, RF-001-06: si falla una parte de «motor», el paso falla con su
        salida, «blender» sigue correcto y el código es 1."""
        broken = FakeRunner({f"{RUNTIME}#1": (1, "", "RuntimeError: rota\n")})
        with many_cpus():
            result = run_check("--completo", runner=broken)
        self.assertEqual(result.code, 1, result.out)
        self.assertTrue(_step_line(result.out, RUNTIME).lstrip().startswith("fallo"))
        self.assertTrue(_step_line(result.out, "blender").lstrip().startswith("correcto"))
        self.assertIn("RuntimeError: rota", result.out)
        self.assertRegex(result.out.strip().splitlines()[-1], rf"falla «{RUNTIME}»$")

    def test_without_engine_it_is_omitted(self) -> None:
        """RF-004-28, RF-001-06: sin motor de pruebas (``make_runtime.find_test_runtime``;
        aquí, ``GEOBLENDER_TEST_RUNTIME_SITE`` con una carpeta que no existe), «motor» no
        ejecuta nada y se omite por el recurso ``runtime`` con el motivo y la orden
        ``tools/make_runtime.py``: código 0 y «VERDE CON OMISIONES (1)». Sin ``--completo``
        (spec 005, T50), ni su línea ni la omisión: «VERDE»."""
        variable = check.ENV_TEST_RUNTIME_SITE
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "no_esta"
            with many_cpus():
                result = run_check("--completo", find_runtime=check.find_test_runtime,
                                   environ={variable: str(missing)})
            self.assertEqual(result.code, 0, result.out)
            self.assertEqual([call.part for call in result.runner.calls_of(RUNTIME)], [])
            self.assertEqual(result.runner.steps(), [*MANDATORY, HARNESS])
            line = _step_line(result.out, RUNTIME)
            self.assertTrue(line.lstrip().startswith("omitido"), line)
            self.assertIn(variable, line)
            self.assertIn(f"\n  {check.RUNTIME_RESOURCE} (1): ", result.out)
            self.assertIn("tools/make_runtime.py", result.out)
            self.assertIn(f"el paso «{RUNTIME}»", result.out)
            self.assertRegex(result.out.strip().splitlines()[-1],
                             r"^RESULTADO: VERDE CON OMISIONES \(1\) \(\d+,\d s\)$")

            with many_cpus():
                result = run_check(find_runtime=check.find_test_runtime,
                                   environ={variable: str(missing)})
            self.assertEqual(result.code, 0, result.out)
            self.assertNotRegex(result.out, rf"(?m)^  \S+\s+{RUNTIME}\s")
            self.assertNotIn(f"\n  {check.RUNTIME_RESOURCE} (1): ", result.out)
            self.assertRegex(result.out.strip().splitlines()[-1],
                             r"^RESULTADO: VERDE \(\d+,\d s\)$")

    def test_runtime_parts_by_time(self) -> None:
        """RF-004-28, RNF-001-01, RNF-007-01 (spec 006, T47): con medidas guardadas de las
        carpetas de «motor», sus partes se reparten entre ellas por su tiempo
        (``parts.share``, con las duraciones de sus módulos en disco): como mucho
        ``RUNTIME_PROCESSES`` órdenes y nunca más que las de siempre; más partes para la que
        más tarda, al menos dos para la que tiene más de un módulo (con una iría después de
        las demás) y una para la que tiene uno; cada carpeta, con sus partes 1…n y el
        fichero de sus tiempos. Si falta la medida de alguna carpeta, las de siempre."""
        each = {"tests/unit/core": 1.0, "tests/unit/jobs": 1.6, "tests/unit/gis": 0.3}
        modules = {folder: disk_modules(ROOT, folder, "test*.py") for folder in DOMAIN_FOLDERS}
        stored = {
            check.times_key(check.TIMES_RUNTIME, folder, "test*.py"):
                {name: each.get(folder, 0.5) for name in modules[folder]}
            for folder in DOMAIN_FOLDERS
            if len(modules[folder]) > 1
        }
        always = runtime_counts()
        parted = [folder for folder in DOMAIN_FOLDERS if len(modules[folder]) > 1]
        expected = parts.share(
            {folder: [each.get(folder, 0.5)] * len(modules[folder]) for folder in parted},
            {folder: check.part_count(check.RUNTIME_PROCESSES, len(modules[folder]), 24)
             for folder in parted},
            min(check.RUNTIME_PROCESSES, sum(always.values())) - (len(always) - len(parted)),
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "almacen.json"
            for name, saved in (("todas", stored), ("sin core", {
                key: value for key, value in stored.items() if "/core:" not in key
            })):
                with self.subTest(medidas=name):
                    parts.write_store(store, saved)
                    with many_cpus():
                        result = run_check("--completo", times_store=lambda root: store)
                    self.assertEqual(result.code, 0, result.out)
                    found: dict[str, list[tuple[int, int] | None]] = {}
                    for call in result.runner.calls_of(RUNTIME):
                        found.setdefault(suite_of(RUNTIME, call.cmd)[0], []).append(call.part)
                        if call.part is not None and name == "todas":
                            self.assertIsNotNone(_option(call.cmd, parts.TIMES_OPTION))
                    counts = {folder: len(found[folder]) for folder in DOMAIN_FOLDERS}
                    for folder, calls in found.items():
                        if len(calls) > 1:
                            self.assertCountEqual(
                                calls, [(i, len(calls)) for i in range(1, len(calls) + 1)]
                            )
                        else:
                            self.assertEqual(calls, [None], folder)
                    if name == "sin core":
                        self.assertEqual(counts, always)
                        continue
                    self.assertEqual({f: counts[f] for f in parted}, expected)
                    self.assertLessEqual(sum(counts.values()), check.RUNTIME_PROCESSES)
                    self.assertLessEqual(sum(counts.values()), sum(always.values()))
                    self.assertGreater(counts["tests/unit/core"], counts["tests/unit/jobs"])
                    # La carpeta de la 006 no está en todas las ramas (la 008 no la tiene).
                    if "tests/unit/gis" in counts:
                        self.assertGreater(counts["tests/unit/jobs"], counts["tests/unit/gis"])
                        self.assertGreaterEqual(counts["tests/unit/gis"], 2)
                    for folder in DOMAIN_FOLDERS:
                        if len(modules[folder]) == 1:
                            self.assertEqual(counts[folder], 1, folder)

    def test_engine_of_the_variable(self) -> None:
        """RF-004-28: con ``GEOBLENDER_TEST_RUNTIME_SITE`` en una carpeta que existe, esa
        es la carpeta ``site`` del motor de «motor» (al principio de ``PYTHONPATH``)."""
        variable = check.ENV_TEST_RUNTIME_SITE
        with tempfile.TemporaryDirectory() as tmp:
            with many_cpus():
                result = run_check("--completo", find_runtime=check.find_test_runtime,
                                   environ={variable: tmp})
        self.assertEqual(result.code, 0, result.out)
        calls = result.runner.calls_of(RUNTIME)
        self.assertTrue(calls)
        for call in calls:
            self.assertTrue(call.env["PYTHONPATH"].startswith(tmp + os.pathsep), call.env)
        self.assertRegex(result.out.strip().splitlines()[-1], r"^RESULTADO: VERDE \(")
# Los pasos con partes (spec 004, T39; «referencia», spec 006, T59).
TIMED_STEPS = ("unitarias", "referencia", "blender", RUNTIME)


def _option(cmd: Sequence[str], name: str) -> str | None:
    """El valor de la opción ``name`` de una orden, o ``None`` si no la lleva."""
    return cmd[cmd.index(name) + 1] if name in cmd else None


def _measured_module(call: Call) -> str:
    """El módulo que «mide» la parte simulada de ``call``: uno por paso, parte y carpeta."""
    folder = suite_of(call.step, call.cmd)[0].replace("/", ".")
    return f"{folder}.medida_{call.part[0] if call.part else 0}"


def _write_measures(call: Call, skip: Sequence[tuple[str, int]] = ()) -> None:
    """Lo que hace una parte con ``--medidas``: escribe la duración de su módulo (la de la
    parte i, i segundos), salvo las partes ``(paso, i)`` de ``skip``."""
    path = _option(call.cmd, parts.MEASURES_OPTION)
    if path is None or call.part is None or (call.step, call.part[0]) in skip:
        return
    seconds = float(call.part[0])
    parts.write_times(Path(path), {_measured_module(call): seconds},
                      part=call.part[0], parts=call.part[1])


def _measured_suites(runner: FakeRunner, skip: Sequence[tuple[str, int]] = ()
                     ) -> dict[str, dict[str, float]]:
    """``{suite: {módulo: s}}`` de lo que escribieron las partes de los pasos con partes."""
    found: dict[str, dict[str, float]] = {}
    for step in TIMED_STEPS:
        for call in runner.calls_of(step):
            # Una carpeta de «motor» con un solo módulo va sin partes, y sin medidas.
            if call.part is None or (step, call.part[0]) in skip:
                continue
            folder, pattern = suite_of(step, call.cmd)
            flavor = {"unitarias": check.TIMES_PYTHON, "referencia": check.TIMES_PYTHON,
                      "blender": check.TIMES_BLENDER, RUNTIME: check.TIMES_RUNTIME}[step]
            key = check.times_key(flavor, folder, pattern)
            found.setdefault(key, {})[_measured_module(call)] = float(call.part[0])
    return found


class PartTimesTest(unittest.TestCase):
    """Spec 004, T39 (RNF-001-01, RNF-007-01): las partes de los pasos se reparten por la
    duración medida de cada módulo, que se guarda fuera del repositorio."""

    def test_first_run_measures(self) -> None:
        """RF-004-28, RNF-001-01, RNF-007-01: sin medidas (el almacén no existe o no se
        puede leer), las partes son las de siempre, sin ``--tiempos``, y cada una escribe
        la duración de sus módulos (``--medidas``, un fichero por parte en la carpeta
        temporal de la comprobación, que se borra); al terminar, el almacén guarda las de
        cada suite con partes («unitarias», «referencia», «blender» y, con ``--completo``,
        las de «motor»). La salida y el
        código, los de siempre. El almacén por defecto está en la carpeta temporal del
        sistema, fuera del repositorio, uno por raíz del código."""
        default = check.default_times_store(ROOT)
        self.assertTrue(default.is_relative_to(Path(tempfile.gettempdir())))
        self.assertFalse(default.is_relative_to(ROOT))
        self.assertEqual(default, check.default_times_store(ROOT))
        self.assertNotEqual(default, check.default_times_store(ROOT / "otra"))
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "tiempos" / "almacen.json"
            for name, text in (("no existe", None), ("ilegible", "{")):
                with self.subTest(almacen=name):
                    if text is not None:
                        store.parent.mkdir(exist_ok=True)
                        store.write_text(text, encoding="utf-8")
                    runner = FakeRunner(on_call=_write_measures)
                    with many_cpus():
                        result = run_check("--completo", runner=runner,
                                           times_store=lambda root: store)
                    self.assertEqual(result.code, 0, result.out)
                    for call in runner.calls_of("unitarias"):
                        assert call.part is not None
                        self.assertIsNone(_option(call.cmd, parts.TIMES_OPTION))
                        measures = _option(call.cmd, parts.MEASURES_OPTION)
                        assert measures is not None
                        expected = unit_part_cmd(*call.part)
                        at = expected.index("discover")
                        self.assertEqual(call.cmd, [*expected[:at], parts.MEASURES_OPTION,
                                                    measures, *expected[at:]])
                        work = Path(measures).parent.parent
                        self.assertTrue(work.name.startswith(check.TEMP_PREFIX), measures)
                        self.assertFalse(work.exists())
                    for call in runner.calls_of("blender"):
                        assert call.part is not None
                        measures = _option(call.cmd, parts.MEASURES_OPTION)
                        self.assertEqual(call.cmd, [*blender_part_cmd(*call.part),
                                                    parts.MEASURES_OPTION, str(measures)])
                    for call in runner.calls_of(RUNTIME):
                        self.assertEqual(_option(call.cmd, parts.MEASURES_OPTION) is None,
                                         call.part is None)
                        self.assertIsNone(_option(call.cmd, parts.TIMES_OPTION))
                    self.assertEqual(parts.read_store(store), _measured_suites(runner))
                    for step, count in (("unitarias", 217), ("blender", 12)):
                        self.assertRegex(
                            _step_line(result.out, step),
                            rf"^  correcto  {step}\s+\d+,\d s  \({count} pruebas\)$",
                        )
                    self.assertNotIn(parts.MEASURES_OPTION, result.out)
                    last = result.out.strip().splitlines()[-1]
                    self.assertRegex(last, r"^RESULTADO: VERDE \(\d+,\d s\)$")
                    store.unlink()

    def test_measured_times_go_to_the_parts(self) -> None:
        """RF-004-28, RNF-001-01, RNF-007-01: con medidas guardadas de una suite, todas sus
        partes reciben el mismo fichero de tiempos (``--tiempos``, en la carpeta temporal
        de la comprobación) con ellas y la misma cola, una por suite (``--cola``, una
        carpeta a su lado; spec 006, T59); una suite sin medidas guardadas no los recibe. Al
        terminar, las medidas de todas las partes de una suite sustituyen a las guardadas;
        si alguna parte no escribió las suyas, se conservan las guardadas que no se
        midieron; las suites que no se ejecutaron se conservan."""
        unit = check.times_key(check.TIMES_PYTHON, "tests/unit", "test*.py")
        launcher = check.times_key(check.TIMES_BLENDER, "tests/blender", "test_*.py")
        other = check.times_key(check.TIMES_PYTHON, "tests/otra", "test*.py")
        stored = {
            unit: {"tests.unit.viejo": 7.0, "tests.unit.otro": 0.5},
            launcher: {"tests.blender.viejo": 2.0},
            other: {"tests.otra.m": 1.0},
        }
        skip = [("blender", 2)]
        received: dict[tuple[str, int], tuple[str | None, dict[str, float]]] = {}

        def measure(call: Call) -> None:
            if call.part is not None and call.step in TIMED_STEPS:
                times = _option(call.cmd, parts.TIMES_OPTION)
                read = parts.read_times(Path(times)) if times is not None else {}
                folder = suite_of(call.step, call.cmd)[0]
                received[(f"{call.step}:{folder}", call.part[0])] = (times, read)
            _write_measures(call, skip)

        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "almacen.json"
            parts.write_store(store, stored)
            runner = FakeRunner(on_call=measure)
            with many_cpus():
                result = run_check("--completo", runner=runner, times_store=lambda root: store)
            self.assertEqual(result.code, 0, result.out)
            queues: dict[str, set[str | None]] = {}
            for call in runner.calls_of("unitarias"):
                assert call.part is not None
                times, read = received[("unitarias:tests/unit", call.part[0])]
                assert times is not None
                self.assertEqual(read, stored[unit])
                measures = _option(call.cmd, parts.MEASURES_OPTION)
                queue = _option(call.cmd, parts.QUEUE_OPTION)
                assert queue is not None
                expected = unit_part_cmd(*call.part)
                at = expected.index("discover")
                self.assertEqual(call.cmd, [*expected[:at], parts.TIMES_OPTION, times,
                                            parts.QUEUE_OPTION, queue,
                                            parts.MEASURES_OPTION, str(measures),
                                            *expected[at:]])
                self.assertFalse(Path(times).exists())
                self.assertEqual(Path(queue).parent, Path(times).parent)
                self.assertFalse(Path(queue).parent.exists())
            files = {received[("unitarias:tests/unit", i)][0]
                     for i in range(1, check.UNIT_PARTS + 1)}
            self.assertEqual(len(files), 1)
            for i in range(1, check.BLENDER_PARTS + 1):
                self.assertEqual(received[("blender:tests/blender", i)][1], stored[launcher])
            for step in ("unitarias", "blender"):
                for call in runner.calls_of(step):
                    queues.setdefault(step, set()).add(_option(call.cmd, parts.QUEUE_OPTION))
            # Una cola por suite (spec 006, T59), la misma para todas sus partes.
            self.assertEqual([len(found) for found in queues.values()], [1, 1])
            self.assertNotEqual(queues["unitarias"], queues["blender"])
            for (name, _part), (times, _read) in received.items():
                if name.startswith(RUNTIME):
                    self.assertIsNone(times, name)
            for call in runner.calls_of(RUNTIME):
                self.assertIsNone(_option(call.cmd, parts.QUEUE_OPTION))  # sin tiempos
            expected_store = _measured_suites(runner, skip)
            expected_store[launcher] = {**stored[launcher], **expected_store[launcher]}
            expected_store[other] = stored[other]
            self.assertEqual(parts.read_store(store), expected_store)
            self.assertNotIn("tests.unit.viejo", parts.read_store(store)[unit])
        last = result.out.strip().splitlines()[-1]
        self.assertRegex(last, r"^RESULTADO: VERDE \(\d+,\d s\)$")


if __name__ == "__main__":
    unittest.main()

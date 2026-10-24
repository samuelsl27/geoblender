# SPDX-License-Identifier: GPL-3.0-or-later
"""La comprobación completa, ``tools/check.py``, con un ejecutor simulado: los pasos que van
a la vez que «blender» (spec 001 0.8, tarea 009/T34; 0.10, tarea 011/T30; RNF-001-01).

- RF-001-06 (0.8, 0.10): «unitarias», «referencia», «licencias» e «iconos» se ejecutan a la vez
  que «blender» (y
  que «motor», con ``--completo``), tras «manifiesto»: empiezan antes de que acabe ninguno, y
  el paso siguiente («arnés», con ``--completo``) espera a todos. Sus líneas del resumen van en
  su lugar de la tabla y con la duración de cada uno, aunque acaben en otro orden; el fallo de
  uno no para a los demás y el código es 1; con Ctrl+C se paran todos (RF-001-09: y se borra
  la carpeta temporal).

Las ayudas (el ejecutor simulado y ``run_check``), en ``tests/support/check_cli.py``.
"""

import _thread
import threading
import time
import unittest
from collections.abc import Callable, Sequence
from pathlib import Path
from unittest import mock

from tests.support.check_cli import (
    EXECUTED,
    HARNESS,
    MANDATORY,
    RUNTIME,
    WITH_BLENDER,
    Call,
    FakeRunner,
    _seconds_of,
    _step_line,
    many_cpus,
    run_check,
)
from tests.support.repo import ROOT, tools_on_path

tools_on_path()

import check  # noqa: E402
from gbtools import discovery  # noqa: E402

GROUP = (*WITH_BLENDER, "blender")
SLOW_S = 0.4  # lo que tarda cada orden de los que van con «blender» en test_report_in_table_order


def first_of_each(steps: Sequence[str], barrier: threading.Barrier) -> Callable[[Call], None]:
    """``on_call`` que lleva a ``barrier`` la primera orden de cada paso de ``steps``: si
    todas llegan, empezaron antes de que terminara ninguna."""
    seen: set[str] = set()
    lock = threading.Lock()

    def meet(call: Call) -> None:
        if call.step not in steps:
            return
        with lock:
            first = call.step not in seen
            seen.add(call.step)
        if first:
            barrier.wait()

    return meet


def unit_parts() -> int:
    """Las partes de «unitarias» con 24 procesadores en el repositorio real."""
    modules = discovery.expected_modules(ROOT / "tests" / "unit", "test*.py", ROOT)
    return check.part_count(check.UNIT_PARTS, len(modules), 24)


def reference_parts() -> int:
    """Las partes de «referencia» con 24 procesadores en el repositorio real."""
    modules = discovery.expected_modules(ROOT / "tests" / "referencia", "test*.py", ROOT)
    return check.part_count(check.REFERENCE_PARTS, len(modules), 24)


class TogetherTest(unittest.TestCase):
    """RF-001-06 (spec 001 0.8 y 0.10): «unitarias», «referencia», «licencias» e «iconos», a
    la vez que «blender»."""

    def test_table(self) -> None:
        """RF-001-06 (0.8, 0.10): en la tabla de pasos, «unitarias», «referencia», «licencias»,
        «iconos» y «motor» van a la vez que «blender» (``Step.alongside``), y ningún otro paso va a la vez
        que otro; «manifiesto» sigue solo."""
        alongside = {step.name: step.alongside for step in check.STEPS}
        self.assertEqual({name for name, other in alongside.items() if other == "blender"},
                         {*WITH_BLENDER, RUNTIME})
        self.assertEqual({name for name, other in alongside.items()
                          if other not in (None, "blender")}, set())
        self.assertIsNone(alongside["manifiesto"])
        self.assertIsNone(alongside["blender"])

    def test_they_start_before_any_ends(self) -> None:
        """RF-001-06 (0.8, 0.10): la primera orden de «unitarias», «referencia», «licencias»,
        «iconos» y «blender» (con ``--completo``, también la de «motor») llegan a una barrera:
        empiezan antes de que termine ninguna. Todas sus órdenes empiezan después de que
        terminen las de «manifiesto», el primer paso; con ``--completo``, «arnés» empieza
        cuando han terminado todas."""
        for args in ((), ("--completo",)):
            with self.subTest(opciones=args):
                steps = [*GROUP, *([RUNTIME] if args else [])]
                barrier = threading.Barrier(len(steps), timeout=15)
                runner = FakeRunner(on_call=first_of_each(steps, barrier))
                with many_cpus():
                    result = run_check(*args, runner=runner)
                self.assertEqual(result.code, 0, result.out)
                self.assertFalse(barrier.broken)
                together = [call for call in runner.calls if call.step in steps]
                self.assertEqual({call.step for call in together}, set(steps))
                manifest = runner.calls_of("manifiesto")
                self.assertEqual(runner.calls[0].step, "manifiesto")
                manifest_end = max(call.ended for call in manifest)
                self.assertLessEqual(manifest_end, min(call.started for call in together))
                if args:
                    self.assertLessEqual(max(call.ended for call in together),
                                         min(call.started for call in runner.calls_of(HARNESS)))
                    self.assertEqual(runner.steps(), [*EXECUTED, HARNESS])
                else:
                    self.assertEqual(runner.steps(), EXECUTED)

    def test_report_in_table_order(self) -> None:
        """RF-001-06 (0.8): el resumen da las líneas en el orden de la tabla aunque los pasos
        acaben en otro: «referencia», «licencias» e «iconos» (cada orden, ``SLOW_S``) acaban
        después de «blender», y sus líneas van, cada una con su duración, antes de la de
        «manifiesto», que acabó antes que ellos; la de «blender», con la suya (menos)."""

        def slow(call: Call) -> None:
            if call.step in WITH_BLENDER:
                time.sleep(SLOW_S)

        runner = FakeRunner(on_call=slow)
        with many_cpus():
            result = run_check(runner=runner)
        self.assertEqual(result.code, 0, result.out)
        blender_end = max(call.ended for call in runner.calls_of("blender"))
        manifest_end = max(call.ended for call in runner.calls_of("manifiesto"))
        seconds = {}
        for step in WITH_BLENDER:
            with self.subTest(paso=step):
                self.assertGreater(min(call.ended for call in runner.calls_of(step)), blender_end)
                self.assertGreater(min(call.ended for call in runner.calls_of(step)),
                                   manifest_end)
                seconds[step] = _seconds_of(_step_line(result.out, step))
                self.assertGreaterEqual(seconds[step], SLOW_S - 0.05)
        self.assertLess(_seconds_of(_step_line(result.out, "blender")), min(seconds.values()))
        positions = [result.out.index(_step_line(result.out, name)) for name in MANDATORY]
        self.assertEqual(positions, sorted(positions))
        self.assertRegex(result.out.strip().splitlines()[-1], r"^RESULTADO: VERDE \(\d+,\d s\)$")

    def test_a_failure_does_not_stop_the_others(self) -> None:
        """RF-001-06 (0.8): si fallan una parte de «referencia» y otra de «blender» cuando
        todos han empezado (sus primeras órdenes llegan a una barrera), «licencias» e
        «iconos» siguen y terminan correctos, y también las demás partes; el código es 1, la
        salida de cada fallo se muestra y el resultado nombra los que fallan en el orden de la
        tabla."""
        barrier = threading.Barrier(len(GROUP), timeout=15)
        meet = first_of_each(GROUP, barrier)
        failures = {
            "referencia#1": (1, "", "RuntimeError: referencia rota\n"),
            "blender#2": (1, "", "RuntimeError: blender roto\n"),
        }
        runner = FakeRunner(failures, on_call=meet)
        with many_cpus():
            result = run_check(runner=runner)
        self.assertEqual(result.code, 1, result.out)
        self.assertFalse(barrier.broken)
        self.assertEqual(runner.steps(), EXECUTED)
        self.assertEqual(len(runner.calls_of("blender")), check.BLENDER_PARTS)
        self.assertEqual(len(runner.calls_of("referencia")), reference_parts())
        for step, status in (("referencia", "fallo"), ("licencias", "correcto"),
                             ("iconos", "correcto"), ("manifiesto", "correcto"),
                             ("blender", "fallo")):
            with self.subTest(paso=step):
                self.assertTrue(_step_line(result.out, step).lstrip().startswith(status))
        self.assertIn("RuntimeError: referencia rota", result.out)
        self.assertIn("RuntimeError: blender roto", result.out)
        self.assertRegex(result.out.strip().splitlines()[-1],
                         r"^RESULTADO: NO VERDE \(\d+,\d s\): fallan «referencia», «blender»$")

    def test_ctrl_c_stops_them_all(self) -> None:
        """RF-001-06 (0.8, 0.10), RF-001-09: con Ctrl+C cuando ya están en marcha todas las órdenes
        de «blender» y de los que van a la vez que él (la última en empezar la provoca), se
        paran todas (``blender.stop_all``): ninguna había terminado antes de la interrupción,
        no queda ningún hilo de la comprobación, la carpeta temporal (con los perfiles) se
        borra y la interrupción sigue su camino."""
        total = check.BLENDER_PARTS + unit_parts() + reference_parts() + 2
        stopped = threading.Event()
        lock = threading.Lock()
        begun: list[Call] = []
        interrupted: list[float] = []

        def interrupt(call: Call) -> None:
            if call.step not in GROUP:
                return
            with lock:
                begun.append(call)
                last = len(begun) == total
                if last:
                    interrupted.append(time.perf_counter())
            if last:
                _thread.interrupt_main()
            stopped.wait(5)

        runner = FakeRunner(on_call=interrupt)
        with (
            mock.patch.object(check.blender, "stop_all", side_effect=stopped.set) as stop,
            many_cpus(),
            self.assertRaises(KeyboardInterrupt),
        ):
            run_check(runner=runner)
        stop.assert_called()
        self.assertTrue(stopped.is_set())
        (at,) = interrupted
        calls = [call for call in runner.calls if call.step in GROUP]
        self.assertEqual(len(calls), total)
        for call in calls:
            with self.subTest(paso=call.step, parte=call.part):
                self.assertLess(call.started, at)
                self.assertGreaterEqual(call.ended, at)
        profiles = [Path(c.env["BLENDER_USER_RESOURCES"]) for c in runner.calls_of("blender")]
        self.assertFalse(profiles[0].parent.exists())
        alive = [t for t in threading.enumerate() if t.name.startswith(check.THREAD_PREFIX)]
        self.assertEqual(alive, [])


if __name__ == "__main__":
    unittest.main()

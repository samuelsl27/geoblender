# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que un módulo pone al día tras cambiar sus parámetros y al terminar «Recalcular lo obsoleto» (spec 015, T43;
RF-015-10, RF-015-27, RF-015-29, RF-008-26; hallazgos E-2 y E-4 de la verificación única): los ganchos de
``bl.ops.core_provenance`` que usa ``des`` (``register_parameter_after`` y ``register_recompute_after``), sin proyecto y
con pasos sintéticos.

- **Tras cambiar un parámetro** (``parameter_changed``): lo registrado para el principio de la clave se llama con el
  proyecto, la clave y la versión; un cambio **del proyecto** (sin versión) no llama a nada; lo que no empieza por ese
  principio, tampoco; un fallo de lo registrado no se propaga (el cambio ya está escrito) y queda en el registro;
  registrar es idempotente, sustituye lo del mismo principio y quitar lo de otro no quita lo propio.
- **Al terminar «Recalcular lo obsoleto»** (``_with_afters``): los pasos de lo registrado corren **antes** del último paso
  (el del resultado), sin su ``result`` (que no termine el modal), en el orden en que se registraron; con el recálculo
  **cancelado** no corren; **Esc mientras corren** (T49) cierra el que está en curso, no corre lo que falta y el resultado
  llega cancelado; un fallo suyo no impide el resultado; sin nada registrado, los pasos de siempre; y cerrar el
  generador cierra los pasos del recálculo.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock

from tests.support import blender_ext


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{blender_ext.module_name()}.{name}")


class AftersTest(unittest.TestCase):
    """Con la extensión habilitada (los registros de ``des`` se quitan mientras dura cada prueba)."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.cp = _module("bl.ops.core_provenance")
        cls.model = _module("core.project.model")
        cls.recompute = _module("core.provenance.recompute")

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.release()

    def setUp(self) -> None:
        self.enterContext(mock.patch.dict(self.cp._PARAMETER_AFTERS, clear=True))  # noqa: SLF001 - los registros son de la prueba
        afters = self.cp._RECOMPUTE_AFTERS  # noqa: SLF001
        saved = list(afters)
        afters.clear()
        self.addCleanup(lambda: afters.__setitem__(slice(None), saved))

    # --- Tras cambiar un parámetro ----------------------------------------------------------------

    def test_a_a_registered_after_is_called_for_its_prefix_with_the_version_and_only_then(self) -> None:
        """RF-015-10: lo registrado para ``des.platform.`` se llama con el proyecto, la clave y la versión tras escribir un
        cambio de la versión; un cambio del proyecto (sin versión) y una clave de otro principio no llaman a nada."""
        calls: list[tuple[Any, ...]] = []
        mine, other = (lambda *args: calls.append(("mine", *args))), (lambda *args: calls.append(("other", *args)))
        self.cp.register_parameter_after("des.platform.", mine)
        self.cp.register_parameter_after("gis.", other)
        self.cp.parameter_changed("proyecto", "des.platform.plt_001.guard_m", "uid-v01")
        self.cp.parameter_changed("proyecto", "des.platform.plt_001.guard_m", None)
        self.cp.parameter_changed("proyecto", "des.quarry.algo", "uid-v01")
        self.assertEqual(calls, [("mine", "proyecto", "des.platform.plt_001.guard_m", "uid-v01")])

    def test_b_registering_replaces_the_same_prefix_and_unregistering_keeps_what_another_put_after(self) -> None:
        """Idempotente: registrar lo mismo no lo duplica, otro con el mismo principio lo sustituye y quitar uno que ya no
        es el registrado no quita el actual (lo de otro es suyo)."""
        calls: list[str] = []
        first, second = (lambda *_args: calls.append("first")), (lambda *_args: calls.append("second"))
        self.cp.register_parameter_after("des.platform.", first)
        self.cp.register_parameter_after("des.platform.", first)
        self.cp.parameter_changed("p", "des.platform.x", "v")
        self.assertEqual(calls, ["first"])
        self.cp.register_parameter_after("des.platform.", second)
        self.cp.unregister_parameter_after("des.platform.", first)
        self.cp.parameter_changed("p", "des.platform.x", "v")
        self.assertEqual(calls, ["first", "second"])
        self.cp.unregister_parameter_after("des.platform.", second)
        self.cp.unregister_parameter_after("des.platform.", second)
        self.cp.parameter_changed("p", "des.platform.x", "v")
        self.assertEqual(calls, ["first", "second"])

    def test_c_a_failing_after_does_not_undo_the_change_nor_stop_the_rest(self) -> None:
        """El cambio ya está escrito: un fallo de lo registrado (aquí un ``RuntimeError`` de un operador anidado) se
        anota en el registro técnico y no se propaga, y lo registrado para otro principio sigue llamándose."""
        calls: list[str] = []

        def failing(*_args: Any) -> None:
            raise RuntimeError("el operador anidado se negó")

        self.cp.register_parameter_after("des.platform.", failing)
        self.cp.register_parameter_after("des.", lambda *_args: calls.append("after"))
        with self.assertLogs("geoblender.bl.ops", level="WARNING") as logged:
            self.cp.parameter_changed("p", "des.platform.x", "v")
        self.assertEqual(calls, ["after"])
        self.assertTrue(any("des.platform.x" in line for line in logged.output), logged.output)

    # --- Al terminar «Recalcular lo obsoleto» -------------------------------------------------------

    def steps(self, closed: list[str], *, cancelled: bool = False) -> Any:
        """Unos pasos de recálculo sintéticos: dos pasos y el del resultado (``RecomputeOutcome``)."""
        progress = self.model.Progress
        outcome = self.recompute.RecomputeOutcome((), SimpleNamespace(skipped=()), cancelled)

        def work() -> Any:
            try:
                yield progress("recompute", 0, 2, "uno")
                yield progress("recompute", 1, 2, "dos")
                yield progress("recompute", 2, 2, "fin", result=outcome)
            finally:
                closed.append("cerrados")

        return work(), outcome

    def drive(self, work: Any) -> list[Any]:
        return list(self.cp._with_afters("proyecto", work))  # noqa: SLF001

    def test_d_the_steps_registered_run_before_the_last_step_without_its_result(self) -> None:
        """RF-015-27, RF-008-26: lo registrado corre **antes** del paso del resultado, en el orden en que se registró, con
        sus pasos sin ``result`` (si no, el modal acabaría con ellos); el último paso es el del recálculo, intacto."""
        order: list[str] = []
        progress = self.model.Progress

        def after(tag: str) -> Any:
            def make(project: Any) -> Any:
                self.assertEqual(project, "proyecto")
                order.append(f"empieza {tag}")
                yield progress("after", 0, 1, tag)
                yield progress("after", 1, 1, f"{tag} listo", result="no debe verse")

            return make

        self.cp.register_recompute_after(after("a"))
        self.cp.register_recompute_after(after("b"))
        self.cp.register_recompute_after(lambda _project: None)  # nada que hacer
        closed: list[str] = []
        work, outcome = self.steps(closed)
        found = self.drive(work)
        self.assertEqual([step.message for step in found], ["uno", "dos", "a", "a listo", "b", "b listo", "fin"])
        self.assertEqual([step.result for step in found], [None] * 6 + [outcome])
        self.assertEqual(order, ["empieza a", "empieza b"])
        self.assertEqual(closed, ["cerrados"], "los pasos del recálculo se cierran al acabar")

    def test_e_a_cancelled_recompute_runs_nothing_after_it(self) -> None:
        """Esc: lo demás sigue obsoleto y no se hace más; el resultado llega igual."""
        ran: list[str] = []
        self.cp.register_recompute_after(lambda _project: ran.append("corrió"))
        work, outcome = self.steps([], cancelled=True)
        found = self.drive(work)
        self.assertEqual(ran, [])
        self.assertIs(found[-1].result, outcome)

    def test_f_a_failing_after_is_logged_and_the_result_still_arrives(self) -> None:
        """Un fallo de lo registrado (el disco, un rechazo) se anota y no impide el resultado ni lo demás registrado."""
        progress = self.model.Progress

        def failing(_project: Any) -> Any:
            yield progress("after", 0, 1, "falla")
            raise OSError("disco lleno")

        self.cp.register_recompute_after(failing)
        self.cp.register_recompute_after(lambda _project: iter([progress("after", 1, 1, "otro")]))
        work, outcome = self.steps([])
        with self.assertLogs("geoblender.bl.ops", level="WARNING"):
            found = self.drive(work)
        self.assertEqual([step.message for step in found], ["uno", "dos", "falla", "otro", "fin"])
        self.assertIs(found[-1].result, outcome)

    def test_g_without_anything_registered_the_steps_are_the_same_and_closing_closes_them(self) -> None:
        """Sin nada registrado, los pasos de siempre; cerrar el generador a mitad cierra los del recálculo (Esc, o
        desactivar Geoblender) y no corre nada de lo registrado."""
        ran: list[str] = []
        self.cp.register_recompute_after(lambda _project: ran.append("corrió"))
        self.cp._RECOMPUTE_AFTERS.clear()  # noqa: SLF001
        closed: list[str] = []
        work, outcome = self.steps(closed)
        self.assertEqual([step.message for step in self.drive(work)], ["uno", "dos", "fin"])
        closed.clear()
        work, _outcome = self.steps(closed)
        wrapped = self.cp._with_afters("proyecto", work)  # noqa: SLF001
        self.assertEqual(next(wrapped).message, "uno")
        wrapped.close()
        self.assertEqual((closed, ran), (["cerrados"], []))


    # --- Esc mientras corre lo que sigue (T49) -------------------------------------------------------

    def test_h_esc_while_an_after_runs_closes_its_steps_skips_the_rest_and_the_result_says_cancelled(self) -> None:
        """RF-015-29, RNF-015-05 (T49; la regresión de la T43): Esc **mientras corren los pasos de lo registrado** (el recálculo
        ya había acabado) no se ignora: al reanudar se cierra el generador en curso (cada uno es una operación y una transacción:
        nada a medias), no corre lo demás registrado y el último paso lleva el mismo resultado **cancelado**, con lo
        recalculado (hasta la T43 corrían todos hasta el final y el modal acababa «FINISHED»)."""
        progress, flag = self.model.Progress, [False]
        order: list[str] = []

        def after(tag: str) -> Any:
            def make(_project: Any) -> Any:
                order.append(f"empieza {tag}")
                try:
                    for number in range(1, 4):
                        yield progress("after", number, 3, f"{tag}{number}")
                finally:
                    order.append(f"cierra {tag}")

            return make

        self.cp.register_recompute_after(after("a"))
        self.cp.register_recompute_after(after("b"))
        closed: list[str] = []
        work, outcome = self.steps(closed)
        wrapped = self.cp._with_afters("proyecto", work, cancelled=lambda: flag[0])  # noqa: SLF001
        found = [next(wrapped), next(wrapped), next(wrapped), next(wrapped)]
        self.assertEqual([step.message for step in found], ["uno", "dos", "a1", "a2"])
        flag[0] = True  # Esc: el modal lo pone y avanza otra vez
        last = next(wrapped)
        self.assertIs(type(last.result), type(outcome))
        self.assertTrue(last.result.cancelled, "el resultado dice que se canceló")
        self.assertEqual((last.result.results, last.result.remaining), (outcome.results, outcome.remaining))
        self.assertEqual(order, ["empieza a", "cierra a"], "a se cierra a mitad y b no empieza")
        self.assertEqual(closed, ["cerrados"], "los pasos del recálculo se cerraron al acabar")
        self.assertEqual(list(wrapped), [], "nada más tras el resultado")

    def test_i_esc_before_the_next_after_starts_does_not_start_it(self) -> None:
        """RF-015-29 (T49): Esc entre dos de lo registrado (la primera ya acabó): la segunda no empieza y el resultado dice
        que se canceló; sin Esc, corren las dos (como hasta ahora)."""
        progress, flag, order = self.model.Progress, [False], []

        def first(_project: Any) -> Any:
            order.append("a")
            yield progress("after", 1, 1, "a")
            flag[0] = True  # Esc justo tras su último paso

        self.cp.register_recompute_after(first)
        self.cp.register_recompute_after(lambda _project: order.append("b"))
        work, _outcome = self.steps([])
        found = list(self.cp._with_afters("proyecto", work, cancelled=lambda: flag[0]))  # noqa: SLF001
        self.assertEqual(order, ["a"])
        self.assertTrue(found[-1].result.cancelled)
        self.assertEqual([step.message for step in found], ["uno", "dos", "a", "Recalcular lo obsoleto: cancelado."])


if __name__ == "__main__":
    unittest.main()

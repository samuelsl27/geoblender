# SPDX-License-Identifier: GPL-3.0-or-later
"""HITO: Esc en **cada** evento de «Pista…» y «Accesibilidad de las pistas…» (spec 017, T32; HU-017-1, HU-017-3; RF-017-30, RF-015-29, RNF-017-06; plan 017 §5.3.2 y §7.3; comprobación manual M9).

El recorrido que ``test_road_steps.py`` (el «verde») hace por los puntos de corte de cada fase, aquí de **todos** los eventos del modal, con un paso por evento: mandar Esc tras 0, 1, 2… eventos de
«Calcular» una pista en sus tres modos («trazar»: la red 2D y la ruta 3D; «sobre un eje»; «eje 3D») y la accesibilidad; de «Crear» (cada tabla y cada rejilla en su temporal, y justo antes de la transacción
final) y de **lo que sigue a «Crear»** (la declaración, las máscaras, la capa de entidades y la de ejes de pistas, en el mismo modal). Cada Esc responde en ≤ 2 s; los de «Calcular» y de «Crear» **no dejan
nada** (ni operación, ni dato, ni parámetro, ni cifra, ni temporal: ninguna ``des_rdx_``, ``des_acc_`` ni ``des_rax_``) y los de lo que sigue dejan la entidad creada, ninguna operación en curso, ningún
temporal y ninguna capa a medias; y **ninguna llamada pasa de 0,2 s** de CPU (el máximo, sin la transacción final). Es del paso «hito» (el proyecto es el de la pista, en la rejilla de 2 m, y son decenas de
cálculos): ``tools/check.py --completo``; suelto, desde ``Geoblender\\``::

    & $B -b --factory-startup --python-exit-code 1 --python tools/run_blender_tests.py -- --patron milestone_road_steps.py

Se para cada recorrido cuando el cálculo acaba antes de que llegue Esc: así cubre todos los eventos aunque cambie su número (la cadena de lo que sigue depende de lo que ya hay en la versión).
"""

import itertools
import unittest

from tests.blender import test_road_steps as steps

CHAIN_LIMIT = 200
"""Cuántos eventos se recorren como mucho (la cadena de lo que sigue acaba mucho antes)."""


class RoadStepsMilestone(steps.RoadStepsCase):
    """El proyecto de la prueba de la pista y las ayudas de ``test_road_steps.py``, con los recorridos de todos los eventos."""

    def test_a_esc_in_every_event_of_calculating_leaves_nothing(self) -> None:
        """RF-017-30, RF-015-29, RNF-017-06 (M9): Esc tras **cada** evento de «Calcular» una pista (los tres modos) y la accesibilidad responde en ≤ 2 s y no deja nada; ninguna llamada pasa de 0,2 s."""
        start = self.fresh_surface()
        before = self.state()
        counted: dict[str, int] = {}
        for which in (*steps.KINDS, "ACCESS"):
            reached = 0
            for point in itertools.count():
                modal = self.start(self.command_of(which), **self.calc_form(which, start))
                state, _events = self.drive(modal, stop_after=point)
                if state != {"RUNNING_MODAL"}:  # el cálculo acabó antes de Esc: ya se recorrieron todos los eventos
                    self.des_ops.discard_calculation()
                    break
                with self.subTest(modo=which, eventos_antes_de_Esc=point):
                    self.escape(modal)
                    self.assertIn(steps.CANCELLED_CALC, modal.report_log)
                    self.assert_nothing_left(before, f"{which} tras {point} eventos")
                reached = point
            self.assertGreaterEqual(reached + 1, 3, f"{which}: «Calcular» tiene varios pasos (Esc cayó tras 0 a {reached} eventos)")
            counted[which] = reached + 1
        self.assertEqual(self.state(), before)
        self.assert_calls_within_budget("«Calcular» por pasos", commits=False)
        print(f"RNF-017-06 (T32): Esc tras cada evento de «Calcular»: {counted} eventos por orden; la llamada más larga, {max(self.calls)[0] * 1000:.0f} ms de CPU ({max(self.calls)[1]})")

    def test_b_esc_in_every_event_of_creating_leaves_nothing_half_done(self) -> None:
        """RF-017-30, RF-015-29, RNF-017-06 (M9): Esc tras **cada** evento de «Crear» la pista («trazar») y la accesibilidad —cada tabla y cada rejilla en su temporal y justo antes de la transacción
        final— responde en ≤ 2 s y deja el proyecto como estaba, con el cálculo descartado; en «sobre un eje» y «eje 3D», al empezar, con temporales y antes de la transacción final."""
        for which in (*steps.KINDS, "ACCESS"):
            command, probe, start = self.command_of(which), self.probe("TRACE" if which in steps.KINDS else which), self.fresh_surface()
            points = range(probe.commit + 1) if which in ("TRACE", "ACCESS") else sorted({0, probe.tmp + 1, probe.commit})
            for point in points:
                with self.subTest(orden=which, eventos_antes_de_Esc=point):
                    name = self.calculate(which, start)
                    before = self.state()
                    modal = self.start(command, confirm=True)
                    self.assertEqual(self.drive(modal, stop_after=point)[0], {"RUNNING_MODAL"}, "«Crear» aún no había acabado")
                    self.escape_and_check(which, name, modal, before, f"{which} tras {point} eventos")  # entre los pasos de crear o, si el número de eventos cambió, ya creada
        self.assert_calls_within_budget("«Crear» por pasos")
        trace, access = self.probe("TRACE"), self.probe("ACCESS")
        print(f"RNF-017-06 (T32): Esc tras cada evento de «Crear»: pista {trace.commit + 1} eventos (temporales desde el {trace.tmp + 1}.º), accesibilidad {access.commit + 1}; "
              f"la llamada más larga, {max(self.calls)[0] * 1000:.0f} ms de CPU ({max(self.calls)[1]}) y la transacción final, {max(self.commits) * 1000:.0f} ms")

    def test_c_esc_in_every_event_of_what_follows_creating_leaves_the_entity_and_nothing_half_done(self) -> None:
        """RF-015-29, RF-017-30, RNF-017-06 (M9): Esc tras **cada** evento de lo que sigue a «Crear» una pista («trazar») y una accesibilidad (la declaración, las máscaras, la capa de entidades y la de
        ejes) responde en ≤ 2 s y deja la entidad creada, ninguna operación en curso, ningún temporal y ninguna capa a medias; y lo que sigue, hasta el final, lo pone todo al día. En «sobre un eje» y «eje 3D»,
        tras el primero y el último."""
        lengths: dict[str, tuple[int, int]] = {}
        for which in (*steps.KINDS, "ACCESS"):
            command, probe = self.command_of(which), self.probe("TRACE" if which in steps.KINDS else which)
            first, every = probe.commit + 1, which in ("TRACE", "ACCESS")
            if every:  # los eventos de lo que sigue a crear ahora (la de la primera pista es más larga: compila las máscaras); crece con las pistas de la versión: se cortan en los de ahora
                steady = self.creation_run(which, self.fresh_surface())
                self.finish_chain()
                length = steady.events - steady.commit - 1
                self.assertGreater(length, 2, f"{which}: lo que sigue a crear tiene varios pasos")
                self.assertLess(length, CHAIN_LIMIT)
                lengths[which] = (probe.events - probe.commit - 1, length)
            for point in range(first, first + length + 1) if every else (first, first + 3):
                name = self.calculate(which, self.fresh_surface())
                before = self.state()
                modal = self.start(command, confirm=True)
                state, _events = self.drive(modal, stop_after=point)
                if state != {"RUNNING_MODAL"}:  # la cadena acabó antes de Esc
                    self.assertTrue(every, f"{which}: la cadena acabó antes del evento {point}")
                    self.assertEqual(state, {"FINISHED"})
                    self.finish_chain()
                    continue
                with self.subTest(orden=which, eventos_antes_de_Esc=point):
                    self.escape_and_check(which, name, modal, before, f"{which} tras {point} eventos")  # la cadena o, si el número de eventos cambió, crear
        self.assert_calls_within_budget("lo que sigue a «Crear»")
        print(f"RNF-017-06 (T32): Esc tras cada evento de lo que sigue a «Crear»: eventos de la cadena (la de la primera pista de la versión, la de ahora) {lengths}; la llamada más larga, "
              f"{max(self.calls)[0] * 1000:.0f} ms de CPU ({max(self.calls)[1]}) y la transacción final, {max(self.commits) * 1000:.0f} ms")


if __name__ == "__main__":
    unittest.main()

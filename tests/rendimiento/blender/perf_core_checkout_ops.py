# SPDX-License-Identifier: GPL-3.0-or-later
"""Copia local y publicación de un proyecto de 200 MB desde Blender (spec 002, T34;
RNF-002-06; RF-002-31, RF-002-32).

Con un proyecto sintético de 200 MB, los modales «Trabajar en copia local…» y «Publicar en
la red…» actualizan el progreso al menos cada segundo, ninguna llamada pasa de 1 s y Esc a
mitad de la copia cancela en ≤ 2 s. En ``blender -b`` no hay bucle de eventos: se toma el
modal de ``window.modal_operators`` y se le pasan los eventos ``TIMER`` seguidos (sin la
espera de 0,05 s del temporizador) y ``ESC``, midiendo cada llamada y el tiempo entre dos
actualizaciones del progreso. Cada medida sale como una línea «RNF-002-06: …».

Estaba en ``tests/blender/test_core_checkout_ops.py`` (T34), donde costaba unos 13 s de
cada comprobación (RNF-001-01); allí queda Esc a mitad de la copia con 32 MiB, y aquí la
medida (convergencia de la spec 002, T39). Se ejecuta con ``tools/check.py
--rendimiento`` o, a mano, con ``tools/run_blender_tests.py -- --carpeta
tests/rendimiento/blender --patron "perf_*.py"``.
"""

import unittest

from tests.blender.test_core_checkout_ops import (
    BIG,
    ORIGINAL,
    PREVIOUS,
    CheckoutOpsTestCase,
)


class ProgressAndEscapeSpeedTest(CheckoutOpsTestCase):
    def test_checkout_200mb_progress_and_escape(self) -> None:
        """RNF-002-06, RF-002-31: sacar copia de un proyecto de 200 MB actualiza el
        progreso al menos cada segundo; Esc a mitad de la copia cancela en ≤ 2 s sin dejar
        copia ni reserva y vuelve a abrir el original; y la copia completa también da
        progreso cada segundo."""
        self.open_project(big=BIG)
        checkout = ("core_checkout_project", "GEOBLENDER_OT_core_checkout_project")
        operator = self.start(*checkout, directory=str(self.copies))
        state, calls = self.drive(operator, until=self.copy_phase_half)
        self.assertEqual(state, {"RUNNING_MODAL"})
        self.assert_progress(operator, calls, "copia local de 200 MB, hasta la mitad")
        self.escape(operator, "copia local de 200 MB")
        self.assertEqual(list(self.copies.iterdir()), [])
        self.assertEqual(operator.outcome, "CANCELLED")
        self.finish_reopen()
        project = self.ps.current()
        self.assertEqual(project.root, self.root)
        self.assertTrue(project.writable)
        self.assertIs(self.lock.read_holder(self.root).mode, self.lock.LockMode.LOCAL)
        operator = self.start(*checkout, directory=str(self.copies))
        state, calls = self.drive(operator)
        self.assertEqual(state, {"FINISHED"})
        self.assert_progress(operator, calls, "copia local de 200 MB completa")
        self.assertIs(self.ps.current().mode, self.core.OpenMode.CHECKOUT)

    def test_publish_200mb_progress_and_escape(self) -> None:
        """RNF-002-06, RF-002-32: publicar una copia de 200 MB actualiza el progreso al
        menos cada segundo; Esc a mitad de la copia a ``.publicando`` cancela en ≤ 2 s sin
        sustituir nada (ni ``.publicando``, ni cambios en el original) y la copia sigue
        abierta; la publicación completa también da progreso cada segundo."""
        self.open_project(big=BIG)
        self.checkout()
        copy = self.ps.current()
        reservation = (self.root / ".lock").read_bytes()
        publish = ("core_publish_project", "GEOBLENDER_OT_core_publish_project")
        operator = self.start(*publish, open_published=False)
        state, calls = self.drive(operator, until=self.copy_phase_half)
        self.assertEqual(state, {"RUNNING_MODAL"})
        self.assert_progress(operator, calls, "publicación de 200 MB, hasta la mitad")
        self.escape(operator, "publicación de 200 MB")
        self.assertEqual(sorted(p.name for p in self.parent.iterdir()), [ORIGINAL])
        self.assertEqual((self.root / ".lock").read_bytes(), reservation)
        self.assertIs(self.ps.current(), copy)
        self.assertTrue(copy.writable)
        operator = self.start(*publish, open_published=False)
        state, calls = self.drive(operator)
        self.assertEqual(state, {"FINISHED"})
        self.assert_progress(operator, calls, "publicación de 200 MB completa")
        self.assertIsNone(self.ps.current())
        self.assertEqual(sorted(p.name for p in self.parent.iterdir()), [ORIGINAL, PREVIOUS])


if __name__ == "__main__":
    unittest.main()

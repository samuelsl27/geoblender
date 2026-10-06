# SPDX-License-Identifier: GPL-3.0-or-later
"""Registro, desregistro y cambio de idioma de la interfaz, dentro de Blender (spec 003,
T35; RNF-003-04, RNF-003-05; plan 003 §7).

Se ejecuta con ``tools/check.py --rendimiento`` (o, a mano, con
``tools/run_blender_tests.py -- --carpeta tests/rendimiento/blender --patron "perf_ui*.py"``).
Con la extensión habilitada (módulos importados y catálogo leído), se deshace y se rehace
la interfaz entera, ``bl.ui.unregister()`` y ``bl.ui.register()`` (el catálogo completo
con sus provisionales, menús, textos, barra, accesos, barra de estado, atajos e iconos),
5 veces, y se cambia el idioma de Geoblender (``bl.ui.i18n.apply``) a inglés y a español,
5 veces:

- RNF-003-04: registro ≤ 250 ms y desregistro ≤ 100 ms (mediana de 5).
- RNF-003-05: cambio de idioma aplicado ≤ 500 ms (el más lento de 10).

Aparte, solo para información: habilitar la extensión entera desde cero (importar y leer
el catálogo; RNF-001-03 tiene su propia prueba).
"""

import importlib
import statistics
import sys
import time
import unittest
from types import ModuleType

from tests.support import blender_ext
from tests.support.blender_ext import module_name

CYCLES = 5
REGISTER_BUDGET_MS = 250.0
UNREGISTER_BUDGET_MS = 100.0
LANGUAGE_BUDGET_MS = 500.0


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def _ms(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def report(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


class RegisterSpeedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.unload()
        blender_ext.load_file()
        start = time.perf_counter()
        blender_ext.enable()
        cls.cold_ms = (time.perf_counter() - start) * 1000.0
        cls.ui = _module("bl.ui")
        cls.ui_i18n = _module("bl.ui.i18n")
        cls.registry = _module("bl.ui.registry")

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.load_file()
        blender_ext.unload()

    def test_register_and_unregister(self) -> None:
        """RNF-003-04: la interfaz se registra en ≤ 250 ms y se desregistra en ≤ 100 ms."""
        registered: list[float] = []
        unregistered: list[float] = []
        for _ in range(CYCLES):
            start = time.perf_counter()
            self.ui.unregister()
            unregistered.append((time.perf_counter() - start) * 1000.0)
            start = time.perf_counter()
            self.ui.register()
            registered.append((time.perf_counter() - start) * 1000.0)
        classes = len(self.registry.own_classes())
        report(f"RNF-003-04: registro de la interfaz ({classes} clases generadas y "
               f"provisionales), mediana de {CYCLES}: {_ms(statistics.median(registered))} "
               f"ms (≤ {_ms(REGISTER_BUDGET_MS)} ms); desregistro: "
               f"{_ms(statistics.median(unregistered))} ms (≤ {_ms(UNREGISTER_BUDGET_MS)} ms); "
               f"habilitar la extensión en frío: {_ms(self.cold_ms)} ms")
        self.assertLessEqual(statistics.median(registered), REGISTER_BUDGET_MS)
        self.assertLessEqual(statistics.median(unregistered), UNREGISTER_BUDGET_MS)

    def test_language_change(self) -> None:
        """RNF-003-05: cambiar el idioma de Geoblender se aplica en ≤ 500 ms."""
        times: list[float] = []
        try:
            for _ in range(CYCLES):
                times.append(self.ui_i18n.apply("en"))
                times.append(self.ui_i18n.apply("es"))
        finally:
            self.ui_i18n.apply("es")
        report(f"RNF-003-05: cambio de idioma (inglés y vuelta, {len(times)} cambios): "
               f"mediana {_ms(statistics.median(times))} ms, el más lento "
               f"{_ms(max(times))} ms (≤ {_ms(LANGUAGE_BUDGET_MS)} ms)")
        self.assertLessEqual(max(times), LANGUAGE_BUDGET_MS)


if __name__ == "__main__":
    unittest.main()

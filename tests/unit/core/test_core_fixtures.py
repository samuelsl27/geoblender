# SPDX-License-Identifier: GPL-3.0-or-later
"""Ayudas de las pruebas de ``core`` (spec 002, T01; plan 002 §7).

La tarea no cubre ningún RF: prepara lo que usan las pruebas de los RF-002-01 a
RF-002-34. Comprueba que las ayudas se importan, que el reloj y los procesos simulados
hacen lo que dicen y que no llevan rutas absolutas ni datos de clientes (constitución,
principio 7: ``tests/`` solo usa datos sintéticos).
"""

import datetime as dt
import inspect
import re
import unittest
from pathlib import Path

from tests.support import core_fixtures
from tests.support.core_fixtures import (
    EXPECTED_ORIGIN,
    SYNTHETIC_WINDOW,
    FakeClock,
    FakePids,
    make_session,
    make_settings,
    project_tmp,
    session_values,
    settings_values,
)

# Lo que no puede aparecer en las ayudas: una unidad con barra, una UNC, carpetas
# absolutas de Linux o macOS, y datos de un expediente real (el origen de Silvestre).
_ABSOLUTE = re.compile(r"[A-Za-z]:[\\/]|\\\\|(?<![\w.])/(?:mnt|home|Users|tmp|var)/")
_CLIENT_DATA = ("silvestre", "736200", "736 200", "4435300", "4 435 300")


class CoreFixturesTest(unittest.TestCase):
    def test_imports(self) -> None:
        """Spec 002, T01: las ayudas se importan y ofrecen carpeta temporal, reloj,
        procesos simulados, sesión y ajustes."""
        names = ("project_tmp", "FakeClock", "FakePids", "make_session", "make_settings")
        for name in names:
            self.assertTrue(callable(getattr(core_fixtures, name)), name)

    def test_project_tmp(self) -> None:
        """Spec 002, T01: la carpeta temporal existe dentro del bloque, en ``%TEMP%`` y no
        en el repositorio, y desaparece al salir."""
        with project_tmp() as folder:
            self.assertTrue(folder.is_dir())
            (folder / "x.txt").write_text("x", encoding="utf-8")
            repo = Path(__file__).resolve().parents[3]
            self.assertFalse(folder.resolve().is_relative_to(repo))
        self.assertFalse(folder.exists())

    def test_fake_clock(self) -> None:
        """Spec 002, T01: el reloj simulado da horas UTC con zona y solo avanza cuando se
        le pide (``advance`` o ``sleep``); ``monotonic`` avanza lo mismo."""
        clock = FakeClock()
        start = clock.now()
        self.assertEqual(start.tzinfo, dt.UTC)
        self.assertEqual(clock.now(), start)
        before = clock.monotonic()
        clock.advance(minutes=29)
        self.assertEqual(clock.now() - start, dt.timedelta(minutes=29))
        clock.sleep(0.1)
        self.assertAlmostEqual(clock.monotonic() - before, 29 * 60 + 0.1, places=9)
        with self.assertRaises(ValueError):
            clock.advance(seconds=-1)

    def test_fake_pids(self) -> None:
        """Spec 002, T01: los procesos simulados dicen vivo solo a los PID declarados, y
        se pueden «terminar»."""
        pids = FakePids({100, 200})
        self.assertTrue(pids(100))
        self.assertFalse(pids(300))
        pids.kill(100)
        self.assertFalse(pids(100))

    def test_synthetic_values(self) -> None:
        """Spec 002, T01: los ajustes son sintéticos (CRS 25830 y 5782, ventana en torno a
        (700 000; 4 400 000)) y la sesión no es de una persona real; los dos admiten
        cambios por nombre."""
        values = settings_values()
        self.assertEqual(values["crs_epsg"], 25830)
        self.assertEqual(values["vcrs_epsg"], 5782)
        xmin, ymin, xmax, ymax = SYNTHETIC_WINDOW
        self.assertLess(abs((xmin + xmax) / 2 - 700_000), 1_000)
        self.assertLess(abs((ymin + ymax) / 2 - 4_400_000), 1_000)
        self.assertEqual(EXPECTED_ORIGIN, (700_000, 4_400_000, 0))
        self.assertEqual(settings_values(name="Otro")["name"], "Otro")
        self.assertEqual(session_values(host="PC-B")["host"], "PC-B")
        with self.assertRaises(KeyError):
            settings_values(no_existe=1)
        self.assertTrue(callable(make_session) and callable(make_settings))

    def test_no_absolute_paths_or_client_data(self) -> None:
        """Spec 002, T01: el texto de las ayudas no contiene rutas absolutas ni datos de
        clientes."""
        text = inspect.getsource(core_fixtures)
        self.assertIsNone(_ABSOLUTE.search(text))
        lowered = text.lower()
        for needle in _CLIENT_DATA:
            self.assertNotIn(needle, lowered)


if __name__ == "__main__":
    unittest.main()

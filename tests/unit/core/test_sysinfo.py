# SPDX-License-Identifier: GPL-3.0-or-later
"""Sesión, equipo, usuario y procesos; reloj UTC; errores del proyecto (spec 002, T11;
RF-002-04; plan 002 §5.1 y §5.4).

- ``pid_alive`` dice si un proceso de este equipo sigue en ejecución (un cerrojo de un
  proceso que ya no está es huérfano). En Windows con ``OpenProcess`` y
  ``GetExitCodeProcess``: ``os.kill(pid, 0)`` no comprueba nada, termina el proceso
  (docs/trampas.md §2).
- Las fechas se guardan en UTC, ISO 8601 con milisegundos y «Z»
  (``2026-10-05T08:12:44.000Z``); el reloj es inyectable.
- Cada error del proyecto lleva objeto, campo y valor, en español.
"""

import datetime as dt
import os
import subprocess
import sys
import unittest

from tests.support.core_fixtures import FakeClock, make_session, session_values
from tests.support.package import import_geoblender

sysinfo = import_geoblender("core.sysinfo")
timeutil = import_geoblender("core.timeutil")
errors = import_geoblender("core.errors")


class PidAliveTest(unittest.TestCase):
    def test_own_pid_alive(self) -> None:
        """RF-002-04: el PID propio está vivo."""
        self.assertTrue(sysinfo.pid_alive(os.getpid()))

    def test_finished_and_invalid_pids(self) -> None:
        """RF-002-04: el PID de un proceso que ya terminó no está vivo, ni uno que no puede
        existir (0, negativo, enorme); preguntar no termina ningún proceso."""
        finished = subprocess.Popen([sys.executable, "-B", "-s", "-c", "pass"])
        finished.wait(timeout=60)
        self.assertFalse(sysinfo.pid_alive(finished.pid))
        for pid in (0, -1, 2**31 - 1):
            with self.subTest(pid=pid):
                self.assertFalse(sysinfo.pid_alive(pid))

    def test_running_child_is_alive_and_survives(self) -> None:
        """RF-002-04: un proceso hijo en marcha está vivo, y comprobarlo no lo termina
        (con ``os.kill(pid, 0)`` en Windows moriría)."""
        child = subprocess.Popen(
            [sys.executable, "-B", "-s", "-c", "import time; time.sleep(30)"]
        )
        try:
            self.assertTrue(sysinfo.pid_alive(child.pid))
            self.assertTrue(sysinfo.pid_alive(child.pid))
            self.assertIsNone(child.poll())
        finally:
            child.kill()
            child.wait(timeout=60)
        self.assertFalse(sysinfo.pid_alive(child.pid))


class SessionTest(unittest.TestCase):
    def test_current_session(self) -> None:
        """RF-002-04: la sesión actual lleva un uid nuevo, el equipo, el usuario, el PID
        propio y la versión de Geoblender; ``user_host`` es «usuario@equipo»."""
        first = sysinfo.current_session("0.1.0")
        second = sysinfo.current_session("0.1.0")
        self.assertNotEqual(first.session_uid, second.session_uid)
        self.assertEqual(first.pid, os.getpid())
        self.assertTrue(first.host and first.user)
        self.assertEqual(first.geoblender_version, "0.1.0")
        self.assertEqual(first.user_host, f"{first.user}@{first.host}")

    def test_fixture_session(self) -> None:
        """RF-002-04: la sesión sintética de las pruebas se construye con los mismos
        campos (``make_session`` de T01)."""
        session = make_session(host="PC-PRUEBA-B")
        self.assertIsInstance(session, sysinfo.SessionInfo)
        self.assertEqual(session.host, "PC-PRUEBA-B")
        self.assertEqual(session.user_host, f"{session_values()['user']}@PC-PRUEBA-B")


class TimeTest(unittest.TestCase):
    def test_format(self) -> None:
        """RF-002-10, RF-002-11: UTC, ISO 8601 con milisegundos y «Z»
        (``2026-10-05T08:12:44.000Z``); otra zona se pasa a UTC y los microsegundos se
        truncan a milisegundos."""
        moment = dt.datetime(2026, 10, 5, 8, 12, 44, tzinfo=dt.UTC)
        self.assertEqual(timeutil.format_utc(moment), "2026-10-05T08:12:44.000Z")
        madrid = dt.timezone(dt.timedelta(hours=2))
        local = dt.datetime(2026, 10, 5, 10, 12, 44, 987_654, tzinfo=madrid)
        self.assertEqual(timeutil.format_utc(local), "2026-10-05T08:12:44.987Z")
        with self.assertRaises(ValueError):
            timeutil.format_utc(dt.datetime(2026, 10, 5, 8, 12, 44))  # sin zona

    def test_parse(self) -> None:
        """RF-002-10: se lee el mismo formato (y sin milisegundos) como UTC; otro texto
        es un error."""
        parsed = timeutil.parse_utc("2026-10-05T08:12:44.000Z")
        self.assertEqual(parsed, dt.datetime(2026, 10, 5, 8, 12, 44, tzinfo=dt.UTC))
        self.assertEqual(
            timeutil.parse_utc("2026-10-05T08:12:44Z"),
            dt.datetime(2026, 10, 5, 8, 12, 44, tzinfo=dt.UTC),
        )
        for text in ("2026-10-05 08:12:44", "2026-10-05T08:12:44.000+02:00", "ayer", ""):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    timeutil.parse_utc(text)
        text = "2026-10-05T08:12:44.123Z"
        self.assertEqual(timeutil.format_utc(timeutil.parse_utc(text)), text)

    def test_clocks(self) -> None:
        """RF-002-10, RF-002-11: el reloj del sistema da UTC con zona; el simulado de las
        pruebas cumple la misma interfaz; ``utc_now_text`` usa el reloj que se le pase."""
        now = timeutil.SYSTEM_CLOCK.now()
        self.assertEqual(now.utcoffset(), dt.timedelta(0))
        self.assertLess(abs((now - dt.datetime.now(dt.UTC)).total_seconds()), 5)
        before = timeutil.SYSTEM_CLOCK.monotonic()
        timeutil.SYSTEM_CLOCK.sleep(0.001)
        self.assertGreater(timeutil.SYSTEM_CLOCK.monotonic(), before)
        clock = FakeClock()
        self.assertIsInstance(clock, timeutil.Clock)
        self.assertIsInstance(timeutil.SYSTEM_CLOCK, timeutil.Clock)
        self.assertEqual(timeutil.utc_now_text(clock), "2026-10-05T08:12:44.000Z")


class ProjectErrorsTest(unittest.TestCase):
    def test_errors_name_object_field_value(self) -> None:
        """RF-002-04 (constitución, principio 10): cada error del proyecto lleva objeto,
        campo y valor, y su mensaje en español los nombra con el motivo."""
        cases = [
            errors.ProjectError(
                "core.project_exists",
                "ya existe una carpeta con ese nombre; elija otro",
                obj="Proyecto «Cantera Prueba»",
                field="carpeta",
                value="Cantera Prueba.gbproj",
            ),
            errors.LockError(
                "core.lock_active",
                "lo tiene abierto otra sesión desde 05/10/2026 08:12",
                obj="Cerrojo del proyecto",
                field="titular",
                value="andres@PC-CAD-2",
            ),
            errors.ValidationError(
                "core.window_inverted",
                "xmin debe ser menor que xmax",
                obj="Ventana de trabajo",
                field="xmin–xmax",
                value=(701_000.0, 700_000.0),
                shown="701000,0–700000,0",
            ),
        ]
        for error in cases:
            with self.subTest(error=type(error).__name__):
                self.assertIsInstance(error, errors.GeoblenderError)
                self.assertTrue(error.code.startswith("core."))
                for part in (error.obj, error.field, error.shown, error.reason):
                    self.assertIn(part, str(error))
                self.assertEqual(error.message, str(error))
        self.assertIsInstance(cases[1], errors.ProjectError)

    def test_object_and_field_are_mandatory(self) -> None:
        """RF-002-04: un error sin objeto o sin campo no se puede construir."""
        with self.assertRaises(TypeError):
            errors.ProjectError("core.x", "motivo", field="f", value=1)  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            errors.ProjectError("core.x", "motivo", obj="o", value=1)  # type: ignore[call-arg]

    def test_display_value(self) -> None:
        """RF-002-04: los valores se muestran como los lee una persona: textos entre
        comillas latinas, decimales con coma, «vacío» y «sí»/«no»."""
        self.assertEqual(errors.display_value("x"), "«x»")
        self.assertEqual(errors.display_value(700_099.6), "700099,6")
        self.assertEqual(errors.display_value(None), "vacío")
        self.assertEqual(errors.display_value(True), "sí")
        self.assertEqual(errors.display_value(25830), "25830")


if __name__ == "__main__":
    unittest.main()

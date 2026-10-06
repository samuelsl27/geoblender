# SPDX-License-Identifier: GPL-3.0-or-later
"""Ayudas de las pruebas de ``geoblender.core`` (spec 002, T01; plan 002 §7).

- :func:`project_tmp`: carpeta temporal en ``%TEMP%`` (nunca en el repositorio) que se
  borra al salir, para crear proyectos de prueba.
- :class:`FakeClock`: reloj UTC que solo avanza cuando la prueba lo pide (cerrojo
  caducado a 29 y 31 min, marcas de actividad…), con la interfaz del reloj de
  ``core.timeutil`` (``now``, ``monotonic``, ``sleep``).
- :class:`FakePids`: sustituto de ``core.sysinfo.pid_alive`` con los PID que se declaran
  vivos.
- :func:`session_values` / :func:`make_session` y :func:`settings_values` /
  :func:`make_settings`: una sesión y unos ajustes de proyecto sintéticos. Los
  ``*_values`` devuelven un diccionario y admiten cambios por nombre (un nombre que no
  existe es un error de la prueba); los ``make_*`` construyen el tipo del dominio
  (``core.sysinfo.SessionInfo`` y ``core.project.model.ProjectSettings``) y lo importan al
  llamarlos, no al importar este módulo, porque los crean tareas posteriores de la spec.

Datos solo sintéticos (constitución, principio 7): CRS 25830 y 5782 y una ventana en
torno a (700 000; 4 400 000), el origen de la prueba de precisión de ADR-0005. Ni rutas
absolutas ni datos de un expediente real: lo comprueba ``tests/unit/core/
test_core_fixtures.py``.
"""

from __future__ import annotations

import datetime as dt
import tempfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from tests.support.package import import_geoblender

# Ventana tecleada (xmin, ymin, xmax, ymax), en m: con paso de 1 m se amplía a
# (699 500; 4 399 500; 700 501; 4 400 501), de centro (700 000,5; 4 400 000,5), y el
# GeoOrigin sale (700 000; 4 400 000; 0) (RF-002-24).
SYNTHETIC_WINDOW: tuple[float, float, float, float] = (
    699_500.4,
    4_399_500.6,
    700_500.2,
    4_400_500.9,
)
EXPECTED_ORIGIN: tuple[int, int, int] = (700_000, 4_400_000, 0)

# Hora de partida del reloj simulado (la del ejemplo de formato-proyecto.md §5.2).
CLOCK_START = dt.datetime(2026, 10, 5, 8, 12, 44, tzinfo=dt.UTC)

_SESSION: dict[str, Any] = {
    "session_uid": "00000000-0000-4000-8000-000000000001",
    "host": "PC-PRUEBA-A",
    "user": "prueba",
    "pid": 4242,
    "geoblender_version": "0.1.0",
}

_SETTINGS: dict[str, Any] = {
    "name": "Cantera Prueba",
    "code": None,
    "client": None,
    "description": None,
    "crs_epsg": 25830,
    "vcrs_epsg": 5782,
    "vcrs_note": None,
    "window": SYNTHETIC_WINDOW,
    "grid_step_m": 1.0,
    "z0": 0,
}


@contextmanager
def project_tmp(prefix: str = "geoblender-002-") -> Iterator[Path]:
    """Carpeta temporal nueva en ``%TEMP%``; al salir se borra entera."""
    with tempfile.TemporaryDirectory(prefix=prefix, ignore_cleanup_errors=True) as tmp:
        yield Path(tmp)


class FakeClock:
    """Reloj simulado: ``now()`` en UTC con zona, ``monotonic()`` en segundos y
    ``sleep()`` que avanza sin esperar."""

    def __init__(self, start: dt.datetime = CLOCK_START) -> None:
        if start.tzinfo is None:
            raise ValueError("el reloj simulado necesita una hora con zona (UTC)")
        self._now = start.astimezone(dt.UTC)
        self._monotonic = 1_000.0

    def now(self) -> dt.datetime:
        """La hora simulada, en UTC."""
        return self._now

    def monotonic(self) -> float:
        """Segundos de un contador que solo avanza con :meth:`advance` y :meth:`sleep`."""
        return self._monotonic

    def advance(self, *, seconds: float = 0.0, minutes: float = 0.0) -> None:
        """Avanza el reloj; un salto negativo es un error de la prueba."""
        step = seconds + 60.0 * minutes
        if step < 0:
            raise ValueError(f"el reloj simulado no retrocede (salto de {step} s)")
        self._now += dt.timedelta(seconds=step)
        self._monotonic += step

    def sleep(self, seconds: float) -> None:
        """Como ``time.sleep``, pero sin esperar: avanza el reloj."""
        self.advance(seconds=seconds)


class FakePids:
    """``pid_alive`` simulado: vivos solo los PID declarados."""

    def __init__(self, alive: Iterable[int] = ()) -> None:
        self.alive: set[int] = set(alive)

    def __call__(self, pid: int) -> bool:
        return pid in self.alive

    def kill(self, pid: int) -> None:
        """Da el proceso por terminado (Blender cerrado de golpe)."""
        self.alive.discard(pid)


def _values(
    defaults: dict[str, Any], overrides: dict[str, Any], what: str
) -> dict[str, Any]:
    unknown = sorted(set(overrides) - set(defaults))
    if unknown:
        raise KeyError(
            f"{what}: campos desconocidos {unknown}; válidos: {sorted(defaults)}"
        )
    return {**defaults, **overrides}


def session_values(**overrides: Any) -> dict[str, Any]:
    """Los campos de una sesión sintética (equipo «PC-PRUEBA-A», usuario «prueba»)."""
    return _values(_SESSION, overrides, "sesión")


def settings_values(**overrides: Any) -> dict[str, Any]:
    """Los ajustes de un proyecto sintético: CRS 25830 y 5782, ventana
    :data:`SYNTHETIC_WINDOW`, paso 1 m y Z0 = 0."""
    return _values(_SETTINGS, overrides, "ajustes")


def make_session(**overrides: Any) -> Any:
    """La sesión sintética como ``core.sysinfo.SessionInfo``."""
    sysinfo = import_geoblender("core.sysinfo")
    return sysinfo.SessionInfo(**session_values(**overrides))


def make_settings(**overrides: Any) -> Any:
    """Los ajustes sintéticos como ``core.project.model.ProjectSettings``."""
    model = import_geoblender("core.project.model")
    return model.ProjectSettings(**settings_values(**overrides))

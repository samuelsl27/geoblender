# SPDX-License-Identifier: GPL-3.0-or-later
"""Reloj inyectable y fechas en UTC (spec 002; RF-002-10, RF-002-11; formato-proyecto
§3.1 y §5.2; plan 002 §5.1).

Todo lo que se guarda (cabecera, BD, cerrojo, eventos) va en UTC, ISO 8601 con
milisegundos y «Z»: ``2026-10-05T08:12:44.000Z``. El umbral del cerrojo (30 min) cubre los
desfases de reloj entre equipos. El reloj es un protocolo (:class:`Clock`): el del sistema
(:data:`SYSTEM_CLOCK`) o uno simulado en las pruebas, que avanza a voluntad.
"""

from __future__ import annotations

import datetime as dt
import re
import time
from typing import Protocol, runtime_checkable

_UTC_TEXT = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{3}))?Z$"
)


@runtime_checkable
class Clock(Protocol):
    """Reloj: hora UTC con zona, contador monótono (s) y espera."""

    def now(self) -> dt.datetime: ...

    def monotonic(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    """El reloj del sistema."""

    def now(self) -> dt.datetime:
        """La hora actual en UTC, con zona."""
        return dt.datetime.now(dt.UTC)

    def monotonic(self) -> float:
        """Segundos de un contador monótono de alta resolución."""
        return time.perf_counter()

    def sleep(self, seconds: float) -> None:
        """Espera ``seconds`` segundos."""
        time.sleep(seconds)


SYSTEM_CLOCK = SystemClock()


def format_utc(moment: dt.datetime) -> str:
    """``AAAA-MM-DDTHH:MM:SS.mmmZ`` en UTC (los microsegundos se truncan a
    milisegundos); ``ValueError`` si ``moment`` no tiene zona."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError(f"la hora {moment!r} no tiene zona: se guardan horas UTC")
    utc = moment.astimezone(dt.UTC)
    return f"{utc:%Y-%m-%dT%H:%M:%S}.{utc.microsecond // 1000:03d}Z"


def parse_utc(text: str) -> dt.datetime:
    """La hora UTC de un texto ``AAAA-MM-DDTHH:MM:SS[.mmm]Z``; ``ValueError`` si no
    tiene ese formato."""
    match = _UTC_TEXT.match(text) if isinstance(text, str) else None
    if match is None:
        raise ValueError(f"«{text}» no es una hora UTC ISO 8601 con «Z»")
    year, month, day, hour, minute, second, millis = match.groups()
    return dt.datetime(
        int(year),
        int(month),
        int(day),
        int(hour),
        int(minute),
        int(second),
        int(millis or 0) * 1000,
        tzinfo=dt.UTC,
    )


def utc_now_text(clock: Clock = SYSTEM_CLOCK) -> str:
    """La hora de ``clock`` como texto UTC."""
    return format_utc(clock.now())

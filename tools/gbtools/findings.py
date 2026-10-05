# SPDX-License-Identifier: GPL-3.0-or-later
"""Incumplimientos de las reglas del repositorio (plan 001 §5.2)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class Finding:
    """Un incumplimiento de una regla.

    ``path`` es relativa a la raíz del repositorio y usa «/»; ``line`` empieza en 1
    (0 si el incumplimiento no tiene línea); ``rule`` es el identificador (``ARQ-01``,
    ``TXT-02``…) y ``message`` explica en español qué falla y cómo se corrige.
    """

    path: str
    line: int
    rule: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: [{self.rule}] {self.message}"


def format_findings(findings: Iterable[Finding]) -> str:
    """Una línea ``fichero:línea: [REGLA] mensaje`` por incumplimiento, ordenadas."""
    return "\n".join(str(finding) for finding in sorted(findings))

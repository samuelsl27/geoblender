# SPDX-License-Identifier: GPL-3.0-or-later
"""El tipo de una migración del esquema del proyecto (spec 002; RF-002-20; plan 002 §5.4).

Está aparte del paquete para que cada migración (``m<NNNN>.py``) lo use sin importar el
paquete que la registra (un ciclo, ARQ-08); el paquete lo reexporta como
``core.project.migrations.Migration``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Migration:
    """Una migración del esquema ``from_version`` al ``from_version + 1``.

    ``apply`` hace los cambios en la base dentro de la transacción de la migración (sin
    confirmar ni deshacer: lo hace quien la llama); debe ser idempotente.
    ``min_reader_schema``: el esquema mínimo que hay que saber leer después de aplicarla
    (``None``: no cambia).
    """

    from_version: int
    to_version: int
    description: str
    apply: Callable[[sqlite3.Connection], None]
    min_reader_schema: int | None = None

    @property
    def step(self) -> str:
        """``«N → N+1»``, para los mensajes."""
        return f"{self.from_version} → {self.to_version}"

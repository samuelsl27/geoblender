# SPDX-License-Identifier: GPL-3.0-or-later
"""Tipo de trabajo ``selftest`` en un proceso aparte (spec 004; HU-004-1, HU-004-2; plan 004
§5.1 y §6).

Envoltorio: :func:`main` es ``jobs.selftest.run``, la misma función de dominio que ejecuta el
hilo dentro de Blender (``WorkerInfo.run``), así que los dos ejecutores calculan y cuentan lo
mismo. Parámetros (``jobs/selftest.py``): ``chunked_sum`` con ``n``, ``chunks``, ``sleep_s``
y los fallos provocables ``fail_at``, ``crash_at`` (``os._exit(7)``, que solo tiene sentido
aquí), ``ignore_cancel`` y ``stdout_noise``; y ``matmul``.
"""

from __future__ import annotations

from ..jobs.selftest import run as main

__all__ = ["main"]

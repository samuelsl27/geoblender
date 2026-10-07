# SPDX-License-Identifier: GPL-3.0-or-later
"""Tipo de trabajo ``probe_python``: sondea un intérprete externo (spec 004; HU-004-5;
RF-004-26; plan 004 §5.1).

Envoltorio: :func:`main` es ``jobs.interpreter.run_probe``, la misma función de dominio que
ejecuta el hilo dentro de Blender (``WorkerInfo.run``; estimado en ≤ 5 s, va en hilo). Lanza
el intérprete de la ruta ``--path python=…`` con un guion que cuenta su versión de Python, la
de numpy y su BLAS, espera su respuesta y falla con ``external_python_invalid`` y el motivo si
no es Python 3.13 con numpy. No guarda nada: lo guarda ``geoblender.jobs_set_external_python``
si el trabajo terminó bien.
"""

from __future__ import annotations

from ..jobs.interpreter import run_probe as main

__all__ = ["main"]

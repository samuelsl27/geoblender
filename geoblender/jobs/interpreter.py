# SPDX-License-Identifier: GPL-3.0-or-later
"""Intérprete de los workers en proceso aparte (spec 004; RF-004-04; plan 004 §5.1, §5.3.1,
§5.3.3 y §6, D-2).

Por ahora, el entorno del hijo: :func:`child_env` parte del entorno de Blender, quita toda
variable ``PYTHON*`` y ``PIP_*`` (que cambiarían qué Python o qué paquetes carga el worker, o
qué hace ``pip`` en la instalación del motor) y fija los hilos de BLAS
(``OPENBLAS_NUM_THREADS``, ``OMP_NUM_THREADS`` y ``MKL_NUM_THREADS``) si el usuario no los
fijó: :func:`blas_threads_for` reparte los procesadores entre los workers que pueden correr
a la vez (``max(1, cpu // máximo)``), para que dos cálculos de BLAS no se pisen.

La resolución del intérprete (``blender``, ``compute`` o externo), su orden de arranque y el
sondeo del intérprete externo llegan con T25.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

DROPPED_PREFIXES: tuple[str, ...] = ("PYTHON", "PIP_")
"""Las variables del entorno de Blender que empiezan así no llegan al worker (sin distinguir
mayúsculas, como Windows)."""
BLAS_THREAD_VARIABLES: tuple[str, ...] = (
    "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
)
"""Las variables de hilos de BLAS que fija :func:`child_env` si el usuario no las fijó."""


def child_env(base: Mapping[str, str], *, blas_threads: int) -> dict[str, str]:
    """El entorno de un worker en proceso aparte a partir de ``base`` (el de Blender, que no
    se toca): todo lo de ``base`` salvo las variables ``PYTHON*`` y ``PIP_*``, más
    :data:`BLAS_THREAD_VARIABLES` = ``blas_threads`` si ``base`` no las trae (sin distinguir
    mayúsculas; una vacía cuenta como no fijada y se sustituye). Las que fijó el usuario
    llegan tal cual (plan §5.3.3).

    ``blas_threads``: entero ≥ 1 (:class:`ValueError` si no). Un nombre o un valor de
    ``base`` que no es texto, :class:`TypeError`."""
    _check_count(blas_threads, "blas_threads")
    env: dict[str, str] = {}
    for name, value in base.items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise TypeError(f"la variable de entorno {name!r}={value!r} no es texto")
        upper = name.upper()
        if upper.startswith(DROPPED_PREFIXES):
            continue
        if upper in BLAS_THREAD_VARIABLES and not value.strip():
            continue  # vacía: no fija nada
        env[name] = value
    present = {name.upper() for name in env}
    for name in BLAS_THREAD_VARIABLES:
        if name not in present:
            env[name] = str(blas_threads)
    return env


def blas_threads_for(max_parallel: int, *, cpu_count: int | None = None) -> int:
    """Hilos de BLAS de cada worker cuando pueden correr ``max_parallel`` a la vez:
    ``max(1, cpu_count // max_parallel)`` (plan §5.3.3, D-2: 24 procesadores y 2 workers,
    12 hilos cada uno). Sin ``cpu_count``, los procesadores que puede usar este proceso
    (``os.process_cpu_count``), o 1 si no se saben. :class:`ValueError` si alguno no es un
    entero ≥ 1."""
    _check_count(max_parallel, "max_parallel")
    if cpu_count is None:
        cpu_count = os.process_cpu_count() or 1
    _check_count(cpu_count, "cpu_count")
    return max(1, cpu_count // max_parallel)


def _check_count(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} {value!r} no es un entero ≥ 1")

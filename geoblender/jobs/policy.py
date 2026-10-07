# SPDX-License-Identifier: GPL-3.0-or-later
"""Elección del ejecutor de un trabajo: hilo dentro de Blender o proceso aparte (spec 004;
RF-004-03; plan 004 §5.4.1 y §6; D-1, DP-31).

RF-004-03: va a **proceso aparte** todo trabajo que necesita el motor de cálculo
(``compute``), que su tipo declara de proceso aparte (``subprocess``) o cuyo tiempo estimado
pasa de :data:`INPROCESS_MAX_ESTIMATED_S` (5 s) o no se conoce; el resto, **en hilo**, si su
tipo tiene función ``run``. Ninguna política fuerza el hilo: un hilo no se puede matar, así
que solo va en él lo que se estima corto (RF-004-10, RF-004-11).

- :func:`resolve_environment`: el entorno del trabajo (``compute`` si lo pide la petición o
  lo exige el tipo con sus parámetros; si no, ``blender``). El lanzador lo fija en la
  petición antes de validarla.
- :func:`estimate_seconds`: la duración que estima el tipo, o ``None`` si no se conoce (un
  estimador que falla o devuelve algo que no es una duración queda avisado en el registro).
- :func:`choose_executor`: ``"inprocess"`` o ``"subprocess"``.
"""

from __future__ import annotations

import logging
import math
from typing import Literal

from .catalog import WorkerInfo, read_only
from .protocol import Environment, JobRequest

type Executor = Literal["inprocess", "subprocess"]

INPROCESS_MAX_ESTIMATED_S = 5.0
"""Máximo estimado, en s, de un trabajo en hilo (D-1, DP-31): 4,9 s → hilo; 5,1 s →
proceso aparte."""

LOGGER = logging.getLogger("geoblender.jobs")


def resolve_environment(info: WorkerInfo, request: JobRequest) -> Environment:
    """El entorno en que corre ``request``: ``compute`` si la petición lo pide o el tipo
    lo exige para sus parámetros (manda lo más exigente: ``matmul`` con n > 1000 corre en el
    motor aunque la petición diga ``blender``); si no, ``blender``. :class:`ValueError` si
    ``info`` no es el tipo de la petición."""
    _check_same_worker(info, request)
    required = info.environment_for(request.params)
    if request.environment == "compute" or required == "compute":
        return "compute"
    return "blender"


def estimate_seconds(info: WorkerInfo, request: JobRequest) -> float | None:
    """La duración en s que estima el tipo para ``request``, o ``None`` si no se conoce:
    sin estimador, si devuelve ``None``, si falla o si lo que da no es una duración (NaN,
    negativa, un booleano, un texto). Los dos últimos casos son un error del módulo que
    declaró el tipo: quedan avisados en el registro y el trabajo irá a proceso aparte."""
    _check_same_worker(info, request)
    if info.estimate_s is None:
        return None
    try:
        value = info.estimate_s(read_only(request.params))
    except Exception:  # noqa: BLE001 - un estimador roto no impide lanzar el trabajo
        LOGGER.warning(
            "El estimador del tipo de trabajo «%s» falló: duración desconocida, irá a un "
            "proceso aparte", info.name, exc_info=True,
        )
        return None
    if value is None:
        return None
    if (
        isinstance(value, bool) or not isinstance(value, int | float)
        or math.isnan(value) or value < 0
    ):
        LOGGER.warning(
            "El estimador del tipo de trabajo «%s» dio %r, que no es una duración en s: "
            "duración desconocida, irá a un proceso aparte", info.name, value,
        )
        return None
    return float(value)


def choose_executor(info: WorkerInfo, request: JobRequest) -> Executor:
    """``"subprocess"`` o ``"inprocess"`` para ``request`` según RF-004-03 (plan §5.4.1)."""
    if resolve_environment(info, request) == "compute":
        return "subprocess"  # necesita el motor
    if info.policy == "subprocess":
        return "subprocess"  # el tipo lo declara
    seconds = estimate_seconds(info, request)
    if seconds is None or seconds > INPROCESS_MAX_ESTIMATED_S:
        return "subprocess"  # desconocido o largo
    return "inprocess" if info.run is not None else "subprocess"


def _check_same_worker(info: WorkerInfo, request: JobRequest) -> None:
    if not isinstance(info, WorkerInfo):
        raise TypeError(f"se esperaba un WorkerInfo, no {type(info).__name__}")
    if info.name != request.worker:
        raise ValueError(
            f"la petición es del tipo de trabajo «{request.worker}» y no de «{info.name}»"
        )

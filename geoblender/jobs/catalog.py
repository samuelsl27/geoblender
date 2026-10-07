# SPDX-License-Identifier: GPL-3.0-or-later
"""Registro de tipos de trabajo (spec 004; RF-004-03, RF-004-11; plan 004 §5.3.1 y §6).

Cada módulo de Geoblender declara sus tipos de trabajo con un :class:`WorkerInfo` y los
registra **desde** ``bl/`` en su ``register()`` con :func:`register_worker` (y los quita en
``unregister()`` con :func:`unregister_worker`): ``jobs/`` (nivel 1) nunca importa un
paquete de dominio ni ``workers/`` (ADR-0004 R5, ARQ-06, ARQ-07). :data:`WORKERS` es la
vista de solo lectura del registro, que el lanzador usa para validar las peticiones
(``protocol.validate_request(..., catalog=WORKERS)``) y elegir el ejecutor (``policy``).

Un ``WorkerInfo`` declara:

- ``name``: ``<código>_<acción>`` en minúsculas, igual al módulo de ``workers/`` que lo
  ejecuta en proceso aparte (plan §5.2.2);
- ``label_msgid``: su nombre visible, un ``msgid`` en inglés con traducción al español;
- ``policy``: ``"subprocess"`` (siempre en proceso aparte) o ``"auto"`` (según su
  estimación). **Ninguna política fuerza el hilo** (RF-004-03);
- ``environment``: ``"blender"``, ``"compute"`` (el motor de cálculo) o una función de los
  parámetros que devuelve uno de los dos;
- ``default_timeout_s``: su tiempo máximo (RF-004-11; 3600 s si no declara otro);
- ``estimate_s``: función de los parámetros que estima la duración en s (``None``, o que
  devuelva ``None``, si no se conoce: proceso aparte);
- ``run``: la función de dominio ``run(ctx) -> resumen`` que ejecuta el hilo y que envuelve
  ``workers/<name>.py``. Obligatoria si la política o la estimación permiten el hilo; sin
  ella, el trabajo va siempre a proceso aparte.

Los de la spec 004 (:data:`BUILTIN_WORKERS`) los registra ``bl/ops/jobs.py`` con
:func:`register_builtin_workers`: ``selftest`` (autodiagnóstico, ``jobs/selftest.py``),
``runtime_install`` y ``runtime_check`` (instalar y verificar el motor de cálculo, siempre en
proceso aparte) y ``probe_python`` (sondeo del intérprete externo, estimado en ≤ 5 s; su
``run`` llega con el sondeo de ``jobs/interpreter.py``, tareas T25 y T33: hasta entonces va
a proceso aparte). Sus nombres visibles y los mensajes del autodiagnóstico están en
:data:`CATALOG_ES` para ``core.i18n.install``.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import KW_ONLY, dataclass
from types import MappingProxyType
from typing import Any, Literal

from . import selftest
from .protocol import (
    DEFAULT_TIMEOUT_S,
    ENVIRONMENTS,
    MAX_TIMEOUT_S,
    WORKER_NAME_PATTERN,
    Environment,
    JsonValue,
)

type Policy = Literal["subprocess", "auto"]
type EnvironmentRule = Environment | Callable[[Mapping[str, JsonValue]], Environment]
type Estimator = Callable[[Mapping[str, JsonValue]], float | None]
type WorkerRun = Callable[[Any], Mapping[str, JsonValue]]
"""``run(ctx: WorkerContext) -> resumen JSON`` (``jobs/worker_api.py``)."""

POLICIES: tuple[str, ...] = ("subprocess", "auto")
"""Las políticas de un tipo de trabajo: ninguna fuerza el hilo (RF-004-03)."""


@dataclass(frozen=True, slots=True)
class WorkerInfo:
    """Un tipo de trabajo (plan §5.3.1), comprobado al crearlo: :class:`ValueError` si no
    cumple. ``name`` y ``label_msgid`` pueden ir por posición; lo demás, por nombre."""

    name: str
    label_msgid: str
    _: KW_ONLY
    policy: Policy = "auto"
    environment: EnvironmentRule = "blender"
    default_timeout_s: float = DEFAULT_TIMEOUT_S
    estimate_s: Estimator | None = None
    run: WorkerRun | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not WORKER_NAME_PATTERN.fullmatch(self.name):
            raise ValueError(
                f"el nombre del tipo de trabajo {_shown(self.name)} no es <código>_<acción> "
                "en minúsculas (a-z, 0-9 y «_», empezando por una letra), como su módulo de "
                "workers/"
            )
        if not isinstance(self.label_msgid, str) or not self.label_msgid.strip():
            raise ValueError(
                f"el tipo de trabajo «{self.name}» no tiene nombre visible (label_msgid)"
            )
        if not isinstance(self.policy, str) or self.policy not in POLICIES:
            raise ValueError(
                f"la política {_shown(self.policy)} del tipo de trabajo «{self.name}» no es "
                f"una de {', '.join(POLICIES)}: ninguna fuerza el hilo"
            )
        if not callable(self.environment) and not (
            isinstance(self.environment, str) and self.environment in ENVIRONMENTS
        ):
            raise ValueError(
                f"el entorno {_shown(self.environment)} del tipo de trabajo «{self.name}» "
                "no es «blender», «compute» ni una función de los parámetros"
            )
        seconds = self.default_timeout_s
        if (
            isinstance(seconds, bool) or not isinstance(seconds, int | float)
            or not math.isfinite(seconds) or not 0 < seconds <= MAX_TIMEOUT_S
        ):
            raise ValueError(
                f"el tiempo máximo {_shown(seconds)} s del tipo de trabajo «{self.name}» "
                f"debe ser mayor que 0 s y no pasar de {int(MAX_TIMEOUT_S)} s"
            )
        object.__setattr__(self, "default_timeout_s", float(seconds))
        for field in ("estimate_s", "run"):
            value = getattr(self, field)
            if value is not None and not callable(value):
                raise ValueError(
                    f"{field} del tipo de trabajo «{self.name}» no es una función "
                    f"({type(value).__name__})"
                )

    def environment_for(self, params: Mapping[str, JsonValue]) -> Environment:
        """El entorno que exige este tipo para ``params`` (de solo lectura para la función
        del tipo). :class:`ValueError` si la función devuelve otra cosa (error del
        programa del módulo que lo declaró)."""
        rule = self.environment
        value = rule(read_only(params)) if callable(rule) else rule
        if not isinstance(value, str) or value not in ENVIRONMENTS:
            raise ValueError(
                f"el entorno {_shown(value)} que da el tipo de trabajo «{self.name}» no es "
                "«blender» ni «compute»"
            )
        return value  # type: ignore[return-value]


_REGISTRY: dict[str, WorkerInfo] = {}
_LOCK = threading.Lock()

WORKERS: Mapping[str, WorkerInfo] = MappingProxyType(_REGISTRY)
"""Los tipos de trabajo registrados, por nombre: vista de solo lectura que sigue los
registros."""


def register_worker(info: WorkerInfo) -> None:
    """Registra ``info`` (lo llama ``bl/`` en el ``register()`` de su módulo).
    :class:`ValueError` si ya hay un tipo con ese nombre (el registrado se queda);
    :class:`TypeError` si no es un :class:`WorkerInfo`."""
    _register_all((info,))


def unregister_worker(name: str) -> bool:
    """Quita el tipo ``name`` (en ``unregister()``) y dice si estaba. Quitar uno que no está
    no hace nada: ``unregister()`` es idempotente."""
    with _LOCK:
        return _REGISTRY.pop(name, None) is not None


def _register_all(infos: Iterable[WorkerInfo]) -> None:
    """Registra todos o ninguno."""
    infos = tuple(infos)
    for info in infos:
        if not isinstance(info, WorkerInfo):
            raise TypeError(
                f"solo se registra un WorkerInfo, no {type(info).__name__} ({info!r})"
            )
    names = [info.name for info in infos]
    with _LOCK:
        taken = [name for name in names if name in _REGISTRY]
        repeated = sorted({name for name in names if names.count(name) > 1})
        if taken or repeated:
            listed = ", ".join(f"«{name}»" for name in taken + repeated)
            raise ValueError(
                f"tipo de trabajo ya registrado: {listed}. Cada nombre se registra una sola "
                "vez (unregister_worker antes de volver a registrarlo)"
            )
        for info in infos:
            _REGISTRY[info.name] = info


def read_only(params: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
    """Los parámetros de una petición para una función de un tipo de trabajo (estimador o
    entorno), que no los puede cambiar."""
    return MappingProxyType(dict(params))


# --- Los tipos de trabajo de la spec 004 ---------------------------------------------------

_PROBE_PYTHON_ESTIMATE_S = 1.0
"""Arrancar un intérprete e importar numpy: 0,1–0,3 s medidos (plan §2.1)."""


def _probe_python_estimate(params: Mapping[str, JsonValue]) -> float:
    return _PROBE_PYTHON_ESTIMATE_S


_LABELS: tuple[tuple[str, str], ...] = (
    ("Background jobs self-test", "Autodiagnóstico de los trabajos en segundo plano"),
    ("Install the compute engine", "Instalar el motor de cálculo"),
    ("Verify the compute engine", "Verificar el motor de cálculo"),
    ("Probe the external interpreter", "Sondear el intérprete externo"),
)

BUILTIN_WORKERS: tuple[WorkerInfo, ...] = (
    WorkerInfo(
        "selftest",
        _LABELS[0][0],
        policy="auto",
        environment=selftest.environment,
        default_timeout_s=600.0,
        estimate_s=selftest.estimate_s,
        run=selftest.run,
    ),
    # Con el pip de Blender en un subproceso (plan §5.4.7): nunca en el hilo.
    WorkerInfo(
        "runtime_install",
        _LABELS[1][0],
        policy="subprocess",
        environment="blender",
        default_timeout_s=1800.0,
    ),
    # Verificación dentro del motor (RF-004-22).
    WorkerInfo(
        "runtime_check",
        _LABELS[2][0],
        policy="subprocess",
        environment="compute",
        default_timeout_s=300.0,
    ),
    # El hilo lanza el intérprete externo y espera (plan §5.1); ``run``: T25 y T33.
    WorkerInfo(
        "probe_python",
        _LABELS[3][0],
        policy="auto",
        environment="blender",
        default_timeout_s=30.0,
        estimate_s=_probe_python_estimate,
    ),
)
"""Los tipos de trabajo de la spec 004 (plan §5.1)."""

CATALOG_ES: Mapping[str, str] = MappingProxyType(dict(_LABELS) | dict(selftest.CATALOG_ES))
"""``msgid`` → español de los nombres visibles de :data:`BUILTIN_WORKERS` y de los mensajes
del autodiagnóstico, para ``core.i18n.install`` (solo lectura)."""


def register_builtin_workers() -> None:
    """Registra los tipos de trabajo de la 004 (todos o ninguno)."""
    _register_all(BUILTIN_WORKERS)


def unregister_builtin_workers() -> None:
    """Quita los tipos de trabajo de la 004; idempotente."""
    for info in BUILTIN_WORKERS:
        unregister_worker(info.name)


def _shown(value: object) -> str:
    if isinstance(value, str):
        return f"«{value}»"
    if isinstance(value, float) and math.isfinite(value):
        text = str(int(value)) if value.is_integer() else repr(value)
        return text.replace(".", ",")
    return repr(value)

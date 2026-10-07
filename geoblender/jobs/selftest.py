# SPDX-License-Identifier: GPL-3.0-or-later
"""Autodiagnóstico de los trabajos en segundo plano (spec 004; HU-004-1, HU-004-2,
RF-004-03; plan 004 §5.1, §5.2.2 y §5.4.1).

Es la lógica del tipo de trabajo ``selftest``: :func:`run` es su función de dominio (la que
ejecuta el hilo dentro de Blender y la que envuelve ``workers/selftest.py`` en un proceso
aparte), :func:`estimate_s` su estimador de duración y :func:`environment` el entorno que
exigen sus parámetros. Python puro: numpy se importa solo al calcular.

Parámetros (``params`` de la petición, :class:`SelftestParams`):

- ``op = "chunked_sum"`` (por defecto): suma ``0 + 1 + … + (n − 1)`` en ``chunks`` trozos,
  esperando ``sleep_s`` s en cada uno; avance «Trozo k de N»; deja la suma (exacta,
  n(n−1)/2) en ``out/sum.npy`` (``int64``, sin *pickle*) declarada con su huella. Fallos
  provocables: ``fail_at`` (trozo en que lanza :class:`~.worker_api.JobFailed`),
  ``crash_at`` (trozo en que termina el proceso con ``os._exit(7)``; nunca en un hilo),
  ``ignore_cancel`` (no atiende la cancelación: prueba el plazo de gracia) y
  ``stdout_noise`` (escribe con ``print()`` y directamente en el descriptor 1, como una
  librería en C: el canal de eventos no debe verlo).
- ``op = "matmul"``: producto float64 ``n × n`` (2000 por defecto), el mejor de ``repeats``
  (3), con su tiempo en s, GFLOP/s, la versión de numpy y su BLAS.

Atiende la cancelación al menos cada :data:`CANCEL_CHECK_S` s (plan §5.4.5: ≤ 0,5 s).

Estimador, calibrado con las mediciones del plan §2.1 (RF-004-03): la suma tarda
``chunks · sleep_s + n / 1,5·10⁹`` s; el producto, 0,52 s a n = 1000 con el numpy de Blender
y 0,041 s a n = 2000 con el motor (cúbico en n, por repetición), y con n > 1000 exige el
motor (``compute``). Con ``crash_at`` o ``stdout_noise`` la duración se da por desconocida,
así que van siempre a proceso aparte: dentro de Blender tumbarían o ensuciarían su proceso.
"""

from __future__ import annotations

import math
import os
import sys
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

from .messages import JobError, Message
from .protocol import Environment, JobRequest, JsonValue, OutputRef
from .worker_api import JobCancelled, JobFailed, blas_name

OPS: tuple[str, ...] = ("chunked_sum", "matmul")
DEFAULT_OP = "chunked_sum"

DEFAULT_SUM_N = 20_000
"""n de la suma por defecto: 0 + … + 19 999 = 199 990 000 (el ejemplo del plan §5.2.3)."""
MAX_SUM_N = 2**31
DEFAULT_CHUNKS = 20
MAX_CHUNKS = 10_000
DEFAULT_SLEEP_S = 0.0
MAX_SLEEP_S = 60.0

DEFAULT_MATMUL_N = 2000
"""El producto de CE-004-02 (2000 × 2000)."""
MAX_MATMUL_N = 4000
DEFAULT_REPEATS = 3
MAX_REPEATS = 10

SUM_RATE_PER_S = 1.5e9
"""Números sumados por segundo (estimador de la suma, plan §5.4.1)."""
BLENDER_MATMUL_MAX_N = 1000
"""Por encima, el producto exige el motor: el numpy de Blender no tiene BLAS optimizado
(0,52 s a n = 1000, 24,9 s a n = 2000; plan §2.1)."""
BLENDER_MATMUL_S_AT_1000 = 0.52
COMPUTE_MATMUL_S_AT_2000 = 0.041

CANCEL_CHECK_S = 0.1
"""Cada cuánto mira la cancelación durante una espera (plan §5.4.5: ≤ 0,5 s)."""
SUM_BLOCK = 1 << 20
"""Números por bloque al sumar (8 MiB de ``int64``): la memoria no crece con n."""
CRASH_EXIT_CODE = 7
SUM_OUTPUT = "sum.npy"
SUM_ROLE = "sum"
MATMUL_SEED = 20_261_005

_KEYS: Mapping[str, frozenset[str]] = MappingProxyType({
    "chunked_sum": frozenset({"op", "n", "chunks", "sleep_s", "fail_at", "crash_at",
                              "ignore_cancel", "stdout_noise"}),
    "matmul": frozenset({"op", "n", "repeats"}),
})

_CATALOG: tuple[Message, ...] = (
    Message(
        "selftest_failed",
        "Self-test: failure provoked at chunk {chunk} of {chunks}.",
        "Autodiagnóstico: fallo provocado en el trozo {chunk} de {chunks}.",
    ),
    Message(
        "selftest_crash_inprocess",
        "Self-test: the provoked crash is only done in a separate process, never inside "
        "Blender.",
        "Autodiagnóstico: la caída provocada solo se hace en un proceso aparte, nunca dentro "
        "de Blender.",
    ),
)

MESSAGES: Mapping[str, Message] = MappingProxyType({m.code: m for m in _CATALOG})
"""Los errores propios del autodiagnóstico, por código (solo lectura)."""

CATALOG_ES: Mapping[str, str] = MappingProxyType({m.msgid: m.es for m in _CATALOG})
"""``msgid`` → texto en español, para ``core.i18n.install`` (solo lectura)."""

_hard_exit = os._exit
"""La salida inmediata del proceso (las pruebas la sustituyen)."""


class _Context(Protocol):
    """Lo que :func:`run` usa del ``WorkerContext`` (``jobs/worker_api.py``)."""

    request: JobRequest

    def output_path(self, filename: str) -> Path: ...

    def progress(self, frac: float, msg: str = "") -> None: ...

    def log(self, level: str, msg: str) -> None: ...

    def check_cancelled(self) -> None: ...

    def add_output(self, path: Path, role: str) -> OutputRef: ...


@dataclass(frozen=True, slots=True)
class SelftestParams:
    """Los parámetros del autodiagnóstico, comprobados (:meth:`from_params`)."""

    op: str = DEFAULT_OP
    n: int = DEFAULT_SUM_N
    chunks: int = DEFAULT_CHUNKS
    sleep_s: float = DEFAULT_SLEEP_S
    repeats: int = DEFAULT_REPEATS
    fail_at: int | None = None
    crash_at: int | None = None
    ignore_cancel: bool = False
    stdout_noise: bool = False

    @classmethod
    def from_params(cls, params: Mapping[str, Any], *, job: str) -> SelftestParams:
        """Los parámetros de ``params``, con sus valores por defecto. :class:`JobError`
        ``request_invalid`` (que nombra el trabajo ``job``) si uno no vale o sobra."""
        if not isinstance(params, Mapping):
            raise _invalid(job, "los parámetros no son un objeto JSON")
        op = params.get("op", DEFAULT_OP)
        if not isinstance(op, str) or op not in OPS:
            raise _invalid(job, f"la operación op = {_shown(op)} no es chunked_sum ni matmul")
        extra = sorted(str(key) for key in params if key not in _KEYS[op])
        if extra:
            raise _invalid(job, f"{op} no admite {', '.join(extra)}")
        if op == "matmul":
            return cls(
                op=op,
                n=_integer(params, "n", DEFAULT_MATMUL_N, MAX_MATMUL_N, job),
                repeats=_integer(params, "repeats", DEFAULT_REPEATS, MAX_REPEATS, job),
            )
        chunks = _integer(params, "chunks", DEFAULT_CHUNKS, MAX_CHUNKS, job)
        return cls(
            op=op,
            n=_integer(params, "n", DEFAULT_SUM_N, MAX_SUM_N, job),
            chunks=chunks,
            sleep_s=_seconds(params, "sleep_s", job),
            fail_at=_chunk(params, "fail_at", chunks, job),
            crash_at=_chunk(params, "crash_at", chunks, job),
            ignore_cancel=_flag(params, "ignore_cancel", job),
            stdout_noise=_flag(params, "stdout_noise", job),
        )


def estimate_s(params: Mapping[str, Any]) -> float | None:
    """Duración estimada en s (RF-004-03, plan §5.4.1); ``None`` si no se conoce: con
    parámetros que no valen, ``crash_at`` o ``stdout_noise`` (solo en proceso aparte)."""
    try:
        p = SelftestParams.from_params(params, job="selftest")
    except JobError:
        return None
    if p.crash_at is not None or p.stdout_noise:
        return None
    if p.op == "matmul":
        if p.n > BLENDER_MATMUL_MAX_N:
            each = COMPUTE_MATMUL_S_AT_2000 * (p.n / 2000) ** 3
        else:
            each = BLENDER_MATMUL_S_AT_1000 * (p.n / 1000) ** 3
        return each * p.repeats
    return p.chunks * p.sleep_s + p.n / SUM_RATE_PER_S


def environment(params: Mapping[str, Any]) -> Environment:
    """El entorno que exigen los parámetros: ``compute`` para el producto con n > 1000;
    si no (también con parámetros que no valen, que fallarán al ejecutarse), ``blender``."""
    try:
        p = SelftestParams.from_params(params, job="selftest")
    except JobError:
        return "blender"
    return "compute" if p.op == "matmul" and p.n > BLENDER_MATMUL_MAX_N else "blender"


def run(ctx: _Context) -> dict[str, JsonValue]:
    """Ejecuta el autodiagnóstico de la petición de ``ctx`` y devuelve su resumen (JSON).
    :class:`JobFailed` si los parámetros no valen (``request_invalid``, antes de calcular)
    o con ``fail_at``; :class:`JobCancelled` («Cancelado en el trozo k de N») si se cancela."""
    job = _job_name(ctx.request)
    try:
        params = SelftestParams.from_params(ctx.request.params, job=job)
    except JobError as exc:
        raise JobFailed.from_error(exc) from None
    if params.op == "matmul":
        return _matmul(ctx, params)
    return _chunked_sum(ctx, params)


# --- Suma por trozos ----------------------------------------------------------------------


def _chunked_sum(ctx: _Context, p: SelftestParams) -> dict[str, JsonValue]:
    ignoring = ", sin atender la cancelación" if p.ignore_cancel else ""
    ctx.log(
        "info",
        f"Suma por trozos: n = {p.n}, {p.chunks} trozos, {_number(p.sleep_s)} s por "
        f"trozo{ignoring}",
    )
    if p.stdout_noise:
        _noise("inicio")
    total = 0
    chunk = 0
    try:
        for chunk in range(1, p.chunks + 1):
            if not p.ignore_cancel:
                ctx.check_cancelled()
            if p.fail_at == chunk:
                raise _failure("selftest_failed", chunk=chunk, chunks=p.chunks)
            if p.crash_at == chunk:
                _crash()
            low, high = (chunk - 1) * p.n // p.chunks, chunk * p.n // p.chunks
            total += _sum_range(ctx, low, high, p.ignore_cancel)
            _wait(ctx, p.sleep_s, p.ignore_cancel)
            if p.stdout_noise:
                _noise(f"trozo {chunk}")
            _progress(ctx, chunk / p.chunks, f"Trozo {chunk} de {p.chunks}", p.ignore_cancel)
    except JobCancelled:
        raise JobCancelled(f"Cancelado en el trozo {chunk} de {p.chunks}") from None
    path = ctx.output_path(SUM_OUTPUT)
    _save_int64(path, total)
    ctx.add_output(path, SUM_ROLE)
    return {"op": "chunked_sum", "n": p.n, "chunks": p.chunks, "sum": total}


def _sum_range(ctx: _Context, low: int, high: int, ignore_cancel: bool) -> int:
    """``low + … + (high − 1)``, exacta, por bloques de :data:`SUM_BLOCK` números."""
    import numpy as np

    total = 0
    for start in range(low, high, SUM_BLOCK):
        if start != low and not ignore_cancel:
            ctx.check_cancelled()
        stop = min(high, start + SUM_BLOCK)
        total += int(np.arange(start, stop, dtype=np.int64).sum(dtype=np.int64))
    return total


def _wait(ctx: _Context, seconds: float, ignore_cancel: bool) -> None:
    """Espera ``seconds`` s mirando la cancelación cada :data:`CANCEL_CHECK_S` s."""
    if seconds <= 0:
        return
    if ignore_cancel:
        time.sleep(seconds)
        return
    deadline = time.monotonic() + seconds
    while (remaining := deadline - time.monotonic()) > 0:
        time.sleep(min(CANCEL_CHECK_S, remaining))
        ctx.check_cancelled()


def _progress(ctx: _Context, frac: float, msg: str, ignore_cancel: bool) -> None:
    try:
        ctx.progress(frac, msg)
    except JobCancelled:
        if not ignore_cancel:
            raise


def _noise(where: str) -> None:
    """Lo que escribiría una librería: con ``print()`` (también una línea que parece un
    evento) y directamente en el descriptor 1, como el código en C."""
    print(f"Autodiagnóstico: ruido con print() ({where})")
    print('{"v": 1, "t": "result", "ts": 0, "outputs": [], "summary": {"ruido": true}}')
    sys.stdout.flush()
    line = f"Autodiagnóstico: ruido por el descriptor 1, como una librería en C ({where})\n"
    os.write(1, line.encode("utf-8"))


def _crash() -> None:
    """Termina el proceso sin limpiar (``os._exit(7)``), solo en el hilo principal, el del
    worker en proceso aparte: en un hilo de Blender tumbaría Blender."""
    if threading.current_thread() is not threading.main_thread():
        raise _failure("selftest_crash_inprocess")
    sys.stdout.flush()
    sys.stderr.flush()
    _hard_exit(CRASH_EXIT_CODE)


def _save_int64(path: Path, value: int) -> None:
    import numpy as np

    with open(path, "wb") as handle:
        np.save(handle, np.int64(value), allow_pickle=False)


# --- Producto de matrices -----------------------------------------------------------------


def _matmul(ctx: _Context, p: SelftestParams) -> dict[str, JsonValue]:
    import numpy as np

    ctx.log("info", f"Producto de matrices float64 {p.n} × {p.n}, el mejor de {p.repeats}")
    repeat = 0
    best = math.inf
    try:
        ctx.check_cancelled()
        rng = np.random.default_rng(MATMUL_SEED)
        a = rng.standard_normal((p.n, p.n))
        b = rng.standard_normal((p.n, p.n))
        for repeat in range(1, p.repeats + 1):
            ctx.check_cancelled()
            start = time.perf_counter()
            _product = a @ b
            best = min(best, time.perf_counter() - start)
            ctx.progress(repeat / p.repeats, f"Producto {repeat} de {p.repeats}")
    except JobCancelled:
        raise JobCancelled(f"Cancelado en el producto {repeat} de {p.repeats}") from None
    best = max(best, 1e-9)
    return {
        "op": "matmul",
        "n": p.n,
        "repeats": p.repeats,
        "best_s": best,
        "gflops": 2 * p.n**3 / best / 1e9,
        "numpy": np.__version__,
        "blas": blas_name(np),
    }


# --- Parámetros y mensajes ----------------------------------------------------------------


def _integer(params: Mapping[str, Any], name: str, default: int, high: int, job: str) -> int:
    value = params.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= high:
        raise _invalid(job, f"{name} = {_shown(value)} debe ser un entero entre 1 y {high}")
    return value


def _seconds(params: Mapping[str, Any], name: str, job: str) -> float:
    value = params.get(name, DEFAULT_SLEEP_S)
    ok = (
        isinstance(value, int | float) and not isinstance(value, bool)
        and math.isfinite(value) and 0 <= value <= MAX_SLEEP_S
    )
    if not ok:
        raise _invalid(
            job, f"{name} = {_shown(value)} s debe estar entre 0 y {_number(MAX_SLEEP_S)} s"
        )
    return float(value)


def _chunk(params: Mapping[str, Any], name: str, chunks: int, job: str) -> int | None:
    value = params.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= chunks:
        raise _invalid(
            job, f"{name} = {_shown(value)} debe ser el número de un trozo, de 1 a {chunks}"
        )
    return value


def _flag(params: Mapping[str, Any], name: str, job: str) -> bool:
    value = params.get(name, False)
    if not isinstance(value, bool):
        raise _invalid(job, f"{name} = {_shown(value)} debe ser verdadero o falso")
    return value


def _failure(code: str, **values: JsonValue) -> JobFailed:
    message = MESSAGES[code]
    return JobFailed(code, msgid=message.msgid, text=message.es.format(**values),
                     values=values)


def _invalid(job: str, detail: str) -> JobError:
    return JobError("request_invalid", job=job, detail=f"autodiagnóstico: {detail}")


def _job_name(request: JobRequest) -> str:
    for candidate in (request.label, request.worker):
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return "selftest"


def _number(value: float) -> str:
    """Un número como lo lee una persona en español (coma decimal)."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).replace(".", ",")


def _shown(value: object) -> str:
    if isinstance(value, str):
        return f"«{value}»"
    if isinstance(value, float):
        return _number(value) if math.isfinite(value) else repr(value)
    return repr(value)

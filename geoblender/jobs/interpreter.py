# SPDX-License-Identifier: GPL-3.0-or-later
"""Intérprete de los workers en proceso aparte (spec 004; RF-004-04, RF-004-25, RF-004-26;
plan 004 §5.1, §5.3.1, §5.3.3 y §6, D-2).

- :func:`resolve_interpreter`: qué intérprete ejecuta un trabajo según su entorno
  (:class:`Interpreter`). ``blender``: el Python de Blender con ``-I -B -u``. ``compute``:
  el intérprete externo si el usuario lo configuró (``-I -B -u``: sus propios paquetes; con
  ``-S`` perdería el ``site-packages`` de su entorno, plan §2.1) o, si no, el Python de
  Blender con ``-I -S -B -u`` y el motor de cálculo listo (``--site`` con su carpeta y
  ``--expect-numpy`` con la versión de numpy del lock): ``-S`` deja fuera el
  ``site-packages`` de Blender y el numpy de Blender no se puede colar (plan §6). Sin motor
  listo ni externo, ``runtime_missing``: el cálculo no se lanza (RF-004-25). Un externo
  configurado nunca pasa al motor sin avisar: si ya no existe, el trabajo falla al
  arrancarlo (``interpreter_not_found``).
- :func:`build_command`: la orden del arranque ``workers/_bootstrap.py`` (plan §5.3.3), con
  las rutas absolutas que el trabajo necesita fuera de su carpeta (``--path``,
  :func:`check_paths`).
- :func:`probe_external`: sondea un intérprete externo antes de guardarlo (RF-004-26): lo
  lanza con ``-I -B`` y un guion que cuenta su versión de Python, la de numpy y su BLAS; lo
  acepta si es Python 3.13 con numpy y, si no, dice por qué (:class:`ExternalProbe`).
- :func:`child_env`: el entorno del hijo, a partir del de Blender sin ninguna variable
  ``PYTHON*`` ni ``PIP_*`` (que cambiarían qué Python o qué paquetes carga el worker, o qué
  hace ``pip`` en la instalación del motor) y con los hilos de BLAS
  (``OPENBLAS_NUM_THREADS``, ``OMP_NUM_THREADS`` y ``MKL_NUM_THREADS``) si el usuario no los
  fijó: :func:`blas_threads_for` reparte los procesadores entre los workers que pueden correr
  a la vez (``max(1, cpu // máximo)``), para que dos cálculos de BLAS no se pisen.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from .messages import JobError

if TYPE_CHECKING:
    from .protocol import Environment
    from .runtime import RuntimeLock

DROPPED_PREFIXES: tuple[str, ...] = ("PYTHON", "PIP_")
"""Las variables del entorno de Blender que empiezan así no llegan al worker (sin distinguir
mayúsculas, como Windows)."""
BLAS_THREAD_VARIABLES: tuple[str, ...] = (
    "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
)
"""Las variables de hilos de BLAS que fija :func:`child_env` si el usuario no las fijó."""

KIND_BLENDER = "blender"
KIND_COMPUTE = "compute"
KIND_EXTERNAL = "external"
BLENDER_FLAGS: tuple[str, ...] = ("-I", "-B", "-u")
"""Python de Blender en el entorno ``blender`` (plan §5.3.3): aislado (sin el
``site-packages`` del usuario ni variables ``PYTHON*``), sin ``__pycache__`` (``-I`` implica
``-E``: ``PYTHONDONTWRITEBYTECODE`` no se lee) y sin búfer en el canal."""
COMPUTE_FLAGS: tuple[str, ...] = ("-I", "-S", "-B", "-u")
"""Python de Blender con el motor de cálculo: además, ``-S``, sin ningún ``site-packages``
(el arranque añade solo el del motor, con ``site.addsitedir``)."""
EXTERNAL_FLAGS: tuple[str, ...] = ("-I", "-B", "-u")
"""Intérprete externo: sin ``-S``, que le quitaría los paquetes de su entorno."""
BOOTSTRAP_PARTS: tuple[str, ...] = ("workers", "_bootstrap.py")
"""El arranque de los workers dentro del paquete (se lanza por ruta: ``jobs`` no importa
``workers``)."""
RUNTIME_READY = "ready"
"""El estado del motor de cálculo con el que se puede calcular (plan §5.2.6)."""
LOCK_NUMPY = "numpy"

REQUIRED_PYTHON = "3.13"
"""La versión de Python que tiene que ser un intérprete externo (RF-004-26)."""
PROBE_TIMEOUT_S = 15.0
PROBE_FLAGS: tuple[str, ...] = ("-I", "-B")
PROBE_MARK = "geoblender-probe:"
"""Comienzo de la línea con la que el guion del sondeo cuenta lo que encontró (JSON)."""
_PROBE_SOURCE = """\
import json, platform, sys
info = {"python": platform.python_version(), "numpy": None, "blas": None}
try:
    import numpy
except Exception:
    pass
else:
    info["numpy"] = str(getattr(numpy, "__version__", "") or "") or None
    try:
        info["blas"] = numpy.show_config(mode="dicts")["Build Dependencies"]["blas"]["name"]
    except Exception:
        info["blas"] = None
sys.stdout.write("%s" + json.dumps(info) + "\\n")
sys.stdout.flush()
"""
PROBE_SCRIPT = (
    "import base64;exec(base64.b64decode('"
    + base64.b64encode((_PROBE_SOURCE % PROBE_MARK).encode("utf-8")).decode("ascii")
    + "'))"
)
"""El guion del sondeo, en una línea y solo con letras, números, comillas simples y
``+/=();.``: si el «intérprete» es un ``.cmd``, ``cmd.exe`` no ve en sus argumentos nada que
pueda ejecutar (saltos de línea, ``&``, ``|``, ``>``, comillas dobles…)."""
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class ComputeRuntime(Protocol):
    """Lo que el lanzador necesita del motor de cálculo (``runtime.ComputeEnvironment``):
    su lock y su ``lock_id``, su estado (plan §5.2.6: ``missing``, ``outdated``, ``broken``
    o ``ready``) y la carpeta ``site`` con sus paquetes."""

    lock: RuntimeLock
    lock_id: str

    def status(self) -> str: ...

    def site_dir(self) -> Path: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class Interpreter:
    """El intérprete que ejecuta un trabajo en proceso aparte (:func:`resolve_interpreter`):
    ``kind`` (``blender``, ``compute`` o ``external``), su ejecutable ``python``, sus
    banderas, la carpeta ``site`` que el arranque añade a ``sys.path`` (``--site``), la
    versión de numpy que exige (``--expect-numpy``, solo ``compute``) y el ``lock_id`` del
    motor de cálculo (solo ``compute``)."""

    kind: str
    python: Path
    flags: tuple[str, ...]
    site: Path | None = None
    expect_numpy: str | None = None
    lock_id: str | None = None


def resolve_interpreter(
    environment: Environment,
    *,
    blender_python: Path,
    runtime: ComputeRuntime | None,
    external_python: Path | None,
    site_override: Path | None = None,
) -> Interpreter:
    """El intérprete de un trabajo del entorno ``environment`` (plan §5.3.3; RF-004-25,
    RF-004-26).

    - ``blender``: ``blender_python`` con :data:`BLENDER_FLAGS`; ``site_override``, si se da,
      es su ``--site`` (las ruedas de las extensiones, plan §5.3.3).
    - ``compute`` con ``site_override`` (la verificación de un motor recién instalado en
      ``<lock_id>.partial/site``): ``blender_python`` con :data:`COMPUTE_FLAGS` sobre esa
      carpeta, aunque el motor no esté listo y aunque haya intérprete externo; hace falta
      ``runtime`` (su lock dice la versión de numpy).
    - ``compute`` con ``external_python``: el externo, con :data:`EXTERNAL_FLAGS`.
    - ``compute`` sin externo: ``blender_python`` con :data:`COMPUTE_FLAGS`, la carpeta
      ``site`` del motor, la versión de numpy de su lock y su ``lock_id``, si el motor está
      listo.

    Sin motor listo (``runtime`` es ``None`` o su estado no es ``ready``) ni externo,
    :class:`~.messages.JobError` ``runtime_missing``: el cálculo no se lanza. Un entorno
    que no es ``blender`` ni ``compute`` es :class:`ValueError`. No comprueba que los
    ejecutables existan: si no, el trabajo falla al arrancarlo (``interpreter_not_found``)."""
    python = Path(blender_python)
    if environment == KIND_BLENDER:
        site = None if site_override is None else Path(site_override)
        return Interpreter(kind=KIND_BLENDER, python=python, flags=BLENDER_FLAGS, site=site)
    if environment != KIND_COMPUTE:
        raise ValueError(f"el entorno «{environment}» no es «{KIND_BLENDER}» ni "
                         f"«{KIND_COMPUTE}»")
    if site_override is None and external_python is not None:
        return Interpreter(kind=KIND_EXTERNAL, python=Path(external_python),
                           flags=EXTERNAL_FLAGS)
    if runtime is None:
        raise JobError("runtime_missing")
    if site_override is not None:
        site = Path(site_override)
    elif runtime.status() == RUNTIME_READY:
        site = Path(runtime.site_dir())
    else:
        # ``missing``, ``outdated`` o ``broken``: hay que instalar, actualizar o reparar el
        # motor con el diálogo del RF-004-20 (Herramientas ▸ Trabajos ▸ Motor de cálculo).
        raise JobError("runtime_missing")
    numpy = runtime.lock.package(LOCK_NUMPY)
    return Interpreter(
        kind=KIND_COMPUTE, python=python, flags=COMPUTE_FLAGS, site=site,
        expect_numpy=None if numpy is None else numpy.version, lock_id=runtime.lock_id,
    )


def build_command(
    interp: Interpreter,
    *,
    package_dir: Path,
    job_dir: Path,
    paths: Mapping[str, Path] | None = None,
) -> list[str]:
    """La orden del worker (plan §5.3.3)::

        <python> <banderas> <paquete>/workers/_bootstrap.py --package-dir <paquete>
            --job-dir <carpeta> --kind <tipo> [--site <dir>] [--expect-numpy <versión>]
            [--path <nombre>=<ruta> …]

    Las rutas absolutas viajan aquí, en la línea de órdenes, nunca en la petición: también
    las que necesita un trabajo fuera de su carpeta (``paths``, :func:`check_paths`; el
    worker las ve en ``WorkerContext.paths``), por orden de nombre."""
    package = Path(package_dir)
    command = [
        str(interp.python), *interp.flags, str(package.joinpath(*BOOTSTRAP_PARTS)),
        "--package-dir", str(package),
        "--job-dir", str(Path(job_dir)),
        "--kind", interp.kind,
    ]
    if interp.site is not None:
        command += ["--site", str(interp.site)]
    if interp.expect_numpy is not None:
        command += ["--expect-numpy", interp.expect_numpy]
    for name, path in sorted(check_paths(paths or {}).items()):
        command += ["--path", f"{name}={path}"]
    return command


PATH_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_]*")
"""Nombre de una ruta de un trabajo (``--path <nombre>=<ruta>``)."""


def check_paths(paths: Mapping[str, Path]) -> dict[str, Path]:
    """Las rutas de un trabajo fuera de su carpeta (``--path``), comprobadas: nombres
    :data:`PATH_NAME_PATTERN` y rutas completas. :class:`ValueError` si alguna no vale."""
    if not isinstance(paths, Mapping):
        raise ValueError(f"las rutas del trabajo deben ser un diccionario, no "
                         f"{type(paths).__name__}")
    checked: dict[str, Path] = {}
    for name, value in paths.items():
        if not isinstance(name, str) or not PATH_NAME_PATTERN.fullmatch(name):
            raise ValueError(f"el nombre de ruta {name!r} no es a-z, 0-9 y «_» empezando por "
                             "una letra")
        if not isinstance(value, str | os.PathLike) or not Path(value).is_absolute():
            raise ValueError(f"la ruta «{name}» = {value!r} no es una ruta completa")
        checked[name] = Path(value)
    return checked


@dataclass(frozen=True, slots=True, kw_only=True)
class ExternalProbe:
    """Lo que dijo el sondeo de un intérprete externo (:func:`probe_external`): su ruta
    ``exe``, sus versiones de Python y de numpy y su BLAS (``None`` si no se saben) y, si no
    sirve, ``reason``: el motivo en español, el ``{reason}`` del mensaje
    ``external_python_invalid`` del §8."""

    exe: Path
    python: str | None = None
    numpy: str | None = None
    blas: str | None = None
    reason: str | None = None

    @property
    def ok(self) -> bool:
        """Si es Python 3.13 con numpy (RF-004-26)."""
        return self.reason is None

    def error(self) -> JobError | None:
        """``external_python_invalid`` con la ruta y el motivo si no sirve; si sirve,
        ``None``."""
        if self.reason is None:
            return None
        return JobError("external_python_invalid", path=str(self.exe), reason=self.reason)


def probe_external(exe: Path, *, timeout_s: float = PROBE_TIMEOUT_S) -> ExternalProbe:
    """Sondea el intérprete ``exe`` (RF-004-26): lo lanza con :data:`PROBE_FLAGS` y
    :data:`PROBE_SCRIPT` (sin consola, sin entrada, con :func:`child_env`) y espera como
    mucho ``timeout_s`` s. Sirve si es Python :data:`REQUIRED_PYTHON` con numpy; si no, el
    :class:`ExternalProbe` dice por qué: que no existe, que no arranca, que no respondió a
    tiempo, que terminó con un código de error, que no respondió como un intérprete de
    Python, que es otra versión o que no tiene numpy. Bloquea: en Blender se llama desde un
    trabajo en hilo (``workers/probe_python.py``)."""
    path = Path(exe)
    if not path.is_file():
        return ExternalProbe(exe=path, reason="no existe")
    try:
        completed = subprocess.run(
            [str(path), *PROBE_FLAGS, "-c", PROBE_SCRIPT],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout_s,
            env=child_env(os.environ, blas_threads=1), creationflags=_CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return ExternalProbe(exe=path, reason=f"no respondió en {timeout_s:g} s")
    except OSError as exc:
        return ExternalProbe(exe=path,
                             reason=f"no se pudo arrancar ({exc.strerror or exc})")
    if completed.returncode != 0:
        reason = f"terminó con el código {completed.returncode}"
        last = _last_line(completed.stderr)
        return ExternalProbe(exe=path, reason=f"{reason} ({last})" if last else reason)
    info = _probe_info(completed.stdout)
    if info is None:
        return ExternalProbe(exe=path, reason="no respondió como un intérprete de Python")
    python, numpy, blas = info["python"], info["numpy"], info["blas"]
    reason = None
    if python is None or python.split(".")[:2] != REQUIRED_PYTHON.split("."):
        reason = f"es Python {python or 'de versión desconocida'}, no {REQUIRED_PYTHON}"
    elif numpy is None:
        reason = f"es Python {python} sin numpy"
    return ExternalProbe(exe=path, python=python, numpy=numpy, blas=blas, reason=reason)


def _last_line(data: bytes, limit: int = 200) -> str:
    """La última línea no vacía de ``data`` (la salida de error de un intérprete que
    falló), acortada a ``limit`` caracteres."""
    lines = [line.strip() for line in data.decode("utf-8", "replace").splitlines()]
    last = next((line for line in reversed(lines) if line), "")
    return last if len(last) <= limit else last[: limit - 1] + "…"


def _probe_info(stdout: bytes) -> dict[str, str | None] | None:
    """Lo que contó el guion del sondeo (la última línea con :data:`PROBE_MARK`; el resto
    de la salida, de un ``sitecustomize`` o del entorno, se ignora), o ``None``."""
    text = stdout.decode("utf-8", "replace")
    for line in reversed(text.splitlines()):
        if not line.startswith(PROBE_MARK):
            continue
        try:
            data = json.loads(line[len(PROBE_MARK):])
        except ValueError:
            return None
        if not isinstance(data, dict):
            return None
        return {key: _text(data.get(key)) for key in ("python", "numpy", "blas")}
    return None


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


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

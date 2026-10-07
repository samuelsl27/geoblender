# SPDX-License-Identifier: GPL-3.0-or-later
"""Localización de Blender y órdenes aisladas (plan 001 §5.3; ADR-0015).

- Blender: el de ``GEOBLENDER_BLENDER`` (ruta a ``blender.exe`` o a su carpeta) o, si no
  está definida, ``DEFAULT_BLENDER_EXE``; su versión sale de ``blender --version`` y no
  puede ser anterior a ``blender_version_min`` del manifiesto (RF-001-07, RF-001-08).
- Python: el de esa misma instalación, ``<carpeta>/<mayor>.<menor>/python/bin/python.exe``,
  lanzado con ``-B -s -X utf8`` (sin bytecode en ``Z:``, sin el ``site-packages`` del
  usuario) y ``PYTHONPATH`` a ``.deps/site`` (plan §2.1, 7).
- Pruebas dentro de Blender: ``-b --factory-startup --python-exit-code 1`` siempre (sin
  ``--python-exit-code`` una excepción sale con 0) y un perfil temporal con
  ``BLENDER_USER_RESOURCES`` (Blender escribe en el perfil aun de fábrica; plan §2.1, 4).

Todo error de entorno es :class:`EnvironmentProblem`, con un mensaje en español que dice
qué falta y cómo corregirlo.

:func:`run` anota cada orden mientras se ejecuta, y :func:`stop_all` las termina: así
``tools/check.py``, que ejecuta a la vez las partes de un paso en varios hilos, las para
al pulsar Ctrl+C igual que ``subprocess.run`` para la suya (spec 003, T40).
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

ENV_BLENDER = "GEOBLENDER_BLENDER"
DEFAULT_BLENDER_EXE = Path(r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe")
BLENDER_EXE_NAME = "blender.exe"
VERSION_TIMEOUT = 60.0  # s; «blender --version» tarda unos 0,14 s (plan §2.1, 10)

ENV_USER_RESOURCES = "BLENDER_USER_RESOURCES"
# Blender las antepone a BLENDER_USER_RESOURCES («Other 'BLENDER_USER_*' variables
# override when set», blender --help): en un perfil aislado no pueden quedar.
OVERRIDING_USER_VARIABLES: tuple[str, ...] = (
    "BLENDER_USER_CONFIG",
    "BLENDER_USER_SCRIPTS",
    "BLENDER_USER_EXTENSIONS",
    "BLENDER_USER_DATAFILES",
)
DEPS_SITE_RELPATH = Path(".deps") / "site"

_VERSION = re.compile(r"^\s*Blender\s+(\d+)\.(\d+)\.(\d+)\b", re.MULTILINE)


@dataclass(frozen=True)
class BlenderInstall:
    """Una instalación de Blender localizada: ejecutable, su Python y su versión."""

    exe: Path
    python: Path
    version: tuple[int, int, int]


class EnvironmentProblem(Exception):
    """El entorno no permite comprobar: el mensaje dice qué falta y cómo corregirlo."""


Runner = Callable[..., subprocess.CompletedProcess[str]]

# Las órdenes de run() en marcha, de cualquier hilo (stop_all las termina).
_RUNNING: set[subprocess.Popen[str]] = set()
_RUNNING_LOCK = threading.Lock()


def run(
    cmd: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Ejecuta ``cmd`` sin entrada estándar y devuelve su código y su salida (UTF-8).

    No lanza por un código distinto de 0; sí ``OSError`` si no se puede lanzar y
    ``subprocess.TimeoutExpired`` si se agota ``timeout``. Como ``subprocess.run``
    (``check=False``), termina el proceso si se agota el tiempo o llega una excepción
    (Ctrl+C) mientras espera; y mientras se ejecuta, :func:`stop_all` lo puede terminar
    desde otro hilo.
    """
    with subprocess.Popen(
        [str(part) for part in cmd],
        env=dict(env) if env is not None else None,
        cwd=str(cwd) if cwd is not None else None,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    ) as process:
        with _RUNNING_LOCK:
            _RUNNING.add(process)
        try:
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                process.kill()
                exc.stdout, exc.stderr = process.communicate()
                raise
            except BaseException:
                process.kill()
                raise
        finally:
            with _RUNNING_LOCK:
                _RUNNING.discard(process)
        code = process.poll()
    return subprocess.CompletedProcess(process.args, code, stdout, stderr)


def running() -> int:
    """Cuántas órdenes de :func:`run` se están ejecutando ahora (en cualquier hilo)."""
    with _RUNNING_LOCK:
        return len(_RUNNING)


def stop_all() -> None:
    """Termina las órdenes de :func:`run` en marcha (en cualquier hilo): devuelven
    enseguida su código. ``tools/check.py`` lo llama si llega Ctrl+C mientras espera a
    las partes de un paso. Sin órdenes en marcha, no hace nada."""
    with _RUNNING_LOCK:
        processes = list(_RUNNING)
    for process in processes:
        try:
            process.kill()
        except OSError:
            pass  # ya había terminado


def parse_version(text: str) -> tuple[int, int, int]:
    """Versión de la salida de ``blender --version``: «Blender 5.2.1 LTS» → (5, 2, 1).

    Lanza ``ValueError`` si ninguna línea empieza por «Blender X.Y.Z».
    """
    match = _VERSION.search(text)
    if match is None:
        first = text.strip().splitlines()[0] if text.strip() else ""
        raise ValueError(f"no se reconoce la versión de Blender en «{first}»")
    major, minor, patch = (int(group) for group in match.groups())
    return major, minor, patch


def _format_version(version: Sequence[int]) -> str:
    return ".".join(str(part) for part in version)


def _clean(value: str) -> str:
    """Quita espacios y comillas que envuelven el valor de una variable de entorno."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value


def _hint() -> str:
    return (
        f"defina {ENV_BLENDER} con la ruta a {BLENDER_EXE_NAME} o a su carpeta (en "
        f'PowerShell: $env:{ENV_BLENDER} = "<ruta>") o instale Blender 5.2 en la ruta '
        f"por defecto «{DEFAULT_BLENDER_EXE}»"
    )


def _hint_sentence() -> str:
    hint = _hint()
    return hint[:1].upper() + hint[1:]


def _blender_exe(environ: Mapping[str, str]) -> tuple[Path, str | None]:
    """Ejecutable que se usará y el valor de la variable (``None`` si no se usa)."""
    raw = environ.get(ENV_BLENDER)
    value = _clean(raw) if raw is not None else ""
    if not value:
        return DEFAULT_BLENDER_EXE, None
    path = Path(value)
    if path.is_dir():
        path = path / BLENDER_EXE_NAME
    return path, value


def _blender_python(exe: Path, version: tuple[int, int, int]) -> Path:
    major, minor, _patch = version
    return exe.parent / f"{major}.{minor}" / "python" / "bin" / "python.exe"


def locate_blender(
    min_version: tuple[int, int, int],
    environ: Mapping[str, str] | None = None,
    runner: Runner = run,
) -> BlenderInstall:
    """Localiza Blender y su Python y comprueba que la versión es ≥ ``min_version``.

    ``environ`` es el entorno donde se busca ``GEOBLENDER_BLENDER`` (por defecto, el del
    proceso); ``runner`` ejecuta ``blender --version``. Lanza :class:`EnvironmentProblem`
    si Blender no está, no dice su versión, es anterior al mínimo o le falta su Python.
    """
    env = os.environ if environ is None else environ
    exe, value = _blender_exe(env)
    if not exe.is_file():
        if value is None:
            raise EnvironmentProblem(
                f"No se encuentra Blender en la ruta por defecto «{exe}» y la variable "
                f"{ENV_BLENDER} no está definida: {_hint()}."
            )
        raise EnvironmentProblem(
            f"No se encuentra Blender en «{exe}», que sale de la variable "
            f"{ENV_BLENDER} = «{value}» (la ruta por defecto, sin la variable, es "
            f"«{DEFAULT_BLENDER_EXE}»): corrija la variable con la ruta a "
            f"{BLENDER_EXE_NAME} o a su carpeta, o bórrela para usar la ruta por defecto."
        )
    origin = (
        f"de la variable {ENV_BLENDER}" if value is not None else "de la ruta por defecto"
    )
    cmd = [str(exe), "--version"]
    try:
        result = runner(cmd, timeout=VERSION_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise EnvironmentProblem(
            f"«{exe} --version» ({origin}) no terminó en {VERSION_TIMEOUT:.0f} s: "
            f"compruebe que es un Blender que funciona o {_hint()}."
        ) from None
    except OSError as exc:
        raise EnvironmentProblem(
            f"No se puede ejecutar «{exe}» ({origin}): {exc}. {_hint_sentence()}."
        ) from None
    if result.returncode != 0:
        raise EnvironmentProblem(
            f"«{exe} --version» ({origin}) terminó con código {result.returncode}: "
            f"compruebe la instalación o {_hint()}."
        )
    try:
        version = parse_version(result.stdout or "")
    except ValueError as exc:
        raise EnvironmentProblem(
            f"«{exe} --version» ({origin}): {exc}. ¿Es un ejecutable de Blender? "
            f"{_hint_sentence()}."
        ) from None
    if version < tuple(min_version):
        raise EnvironmentProblem(
            f"Blender {_format_version(version)} («{exe}», {origin}) es anterior a la "
            f"versión mínima {_format_version(min_version)} del manifiesto: instale "
            f"Blender {_format_version(min_version[:2])} o apunte {ENV_BLENDER} a un "
            f"Blender {_format_version(min_version)} o posterior."
        )
    python = _blender_python(exe, version)
    if not python.is_file():
        raise EnvironmentProblem(
            f"No se encuentra el Python de Blender {_format_version(version)} en "
            f"«{python}»: la instalación de «{exe}» está incompleta; reinstale Blender."
        )
    return BlenderInstall(exe=exe, python=python, version=version)


def _same_file(a: str | os.PathLike[str], b: str | os.PathLike[str]) -> bool:
    def norm(path: str | os.PathLike[str]) -> str:
        return os.path.normcase(os.path.realpath(os.path.abspath(path)))

    return norm(a) == norm(b)


def is_blender_python(install: BlenderInstall, executable: str) -> bool:
    """Verdadero si ``executable`` es el Python de ``install`` (no otro intérprete)."""
    if not executable:
        return False
    return _same_file(executable, install.python)


def python_cmd(install: BlenderInstall, *args: str) -> list[str]:
    """``[python, -B, -s, -X, utf8, …]`` con el Python de ``install``."""
    return [str(install.python), "-B", "-s", "-X", "utf8", *args]


def background_cmd(install: BlenderInstall, script: Path, *script_args: str) -> list[str]:
    """Blender en segundo plano, de fábrica y con ``--python-exit-code 1`` (RF-001-09).

    ``[exe, -b, --factory-startup, --python-exit-code, 1, --python, script, --, …]``;
    se ejecuta con :func:`isolated_env` (perfil temporal).
    """
    return [
        str(install.exe),
        "-b",
        "--factory-startup",
        "--python-exit-code",
        "1",
        "--python",
        str(script),
        "--",
        *script_args,
    ]


def profile_cmd(install: BlenderInstall, script: Path, *script_args: str) -> list[str]:
    """Como :func:`background_cmd` pero **sin** ``--factory-startup``.

    Solo con :func:`isolated_env` sobre un perfil temporal o de desarrollo: con la
    configuración de fábrica no se ve la extensión instalada (plan §2.1, 13).
    """
    return [
        str(install.exe),
        "-b",
        "--python-exit-code",
        "1",
        "--python",
        str(script),
        "--",
        *script_args,
    ]


def extension_cmd(install: BlenderInstall, *args: str) -> list[str]:
    """``[exe, --factory-startup, --command, extension, …]`` (``validate``, ``build``…)."""
    return [str(install.exe), "--factory-startup", "--command", "extension", *args]


def python_env(root: Path, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Entorno para el Python de Blender fuera de Blender (copia de ``base``).

    ``PYTHONPATH`` = ``<root>/.deps/site`` (sustituye a cualquier otro),
    ``PYTHONDONTWRITEBYTECODE=1``, ``PYTHONNOUSERSITE=1`` y ``PYTHONUTF8=1``.
    """
    env = dict(os.environ if base is None else base)
    env["PYTHONPATH"] = str(Path(root) / DEPS_SITE_RELPATH)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONUTF8"] = "1"
    return env


def isolated_env(profile: Path, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Entorno para Blender con el perfil ``profile`` (copia de ``base``).

    ``BLENDER_USER_RESOURCES`` = ``profile`` y ``PYTHONDONTWRITEBYTECODE=1``; quita las
    variables ``BLENDER_USER_*`` que la sustituirían por carpetas del perfil real.
    """
    env = dict(os.environ if base is None else base)
    for name in OVERRIDING_USER_VARIABLES:
        env.pop(name, None)
    env[ENV_USER_RESOURCES] = str(profile)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env

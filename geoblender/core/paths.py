# SPDX-License-Identifier: GPL-3.0-or-later
"""Rutas del proyecto: nombres válidos, carpetas de red, fuentes externas y detector de
rutas absolutas (spec 002; RF-002-02, RF-002-18, RF-002-19, RF-002-30; ADR-0006 §5;
formato-proyecto §1; plan 002 §5.4).

- :func:`validate_project_name`: el nombre de ``<Nombre>.gbproj`` tiene que valer en
  Windows (sin ``<>:"/\\|?*`` ni caracteres de control, sin nombres reservados como
  ``CON`` o ``NUL``, sin punto ni espacio al final, hasta 100 caracteres).
- :func:`is_network_path`: UNC o unidad de red (``GetDriveTypeW`` = ``DRIVE_REMOTE``);
  la detección de la unidad es inyectable (las pruebas no tocan la red).
- :func:`make_external_ref` / :func:`resolve_external_ref`: la ubicación de un fichero
  externo se guarda relativa a la raíz del proyecto **original** (en una copia local, la
  ruta del original sale de los datos de usuario) si están en el mismo volumen; si no,
  solo su nombre, y la ruta completa se anota en los datos de usuario de ese equipo. Sin
  anotación, la fuente es «no localizable» (``None``): nunca se supone. Las rutas se
  comparan canónicas (``os.path.realpath``: una unidad de red da su UNC).
- :func:`find_absolute_paths`: rutas absolutas (Windows, UNC, Linux o macOS) dentro de
  un valor (texto, listas, diccionarios), para comprobar que el proyecto no guarda
  ninguna (RF-002-18).
- :func:`is_within`, :func:`same_volume` y :func:`next_free_path`: si un fichero está
  dentro de una carpeta (una vista de ``scenes/``), si dos rutas son del mismo volumen y
  el primer nombre libre (``principal.blend``, ``principal-2.blend``…).
- :func:`blend_relative_path`: la ruta del proyecto que guarda una escena de Blender,
  relativa al ``.blend`` con el prefijo ``//`` de Blender (``//../`` desde ``scenes/``),
  o vacía si no se puede expresar así (otro volumen, vista sin guardar): nunca absoluta
  (RF-002-18, RF-002-28).
"""

from __future__ import annotations

import ntpath
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import TYPE_CHECKING, Literal, Protocol

from .errors import ValidationError
from .ids import new_uid

if TYPE_CHECKING:
    from .userdata import UserData

DRIVE_REMOTE = 4  # GetDriveTypeW
MAX_PROJECT_NAME = 100
FORBIDDEN_NAME_CHARS = '<>:"/\\|?*'
RESERVED_NAMES: frozenset[str] = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"{device}{index}" for device in ("COM", "LPT") for index in range(1, 10)}
    | {f"{device}{digit}" for device in ("COM", "LPT") for digit in "¹²³"}
)
# Una ruta absoluta que no va pegada a una palabra, un punto, dos puntos o una barra (así
# no cuentan «m/s», «km/h» ni el resto de una URL): unidad y barra, dos barras (UNC) o
# una barra seguida de una carpeta y otra barra (Linux, macOS); hasta un blanco o comilla.
ABSOLUTE_PATH = re.compile(
    r"(?<![\w.:/\\])"
    r"(?:[A-Za-z]:[\\/]|\\\\(?=[^\\\s])|//(?=[^/\s])|/(?=[^/\s]+/))"
    r"[^\s\"'<>|]*"
)

Canonical = Callable[[Path], Path]
DriveType = Callable[[str], int]


class ProjectLike(Protocol):
    """Lo que estas funciones necesitan de un proyecto (``core.project.Project``)."""

    @property
    def uid(self) -> str: ...

    @property
    def root(self) -> Path: ...


@dataclass(frozen=True)
class ExternalRef:
    """Ubicación de un fichero externo tal como se guarda en el proyecto: ``"project"``
    y una ruta relativa con «/» a la raíz del original, o ``"external"`` y solo el
    nombre (la ruta completa está anotada en los datos de usuario con ``ref_uid``)."""

    anchor: Literal["project", "external"]
    path: str
    ref_uid: str


def _invalid_name(reason: str, value: object, shown: str | None = None) -> ValidationError:
    return ValidationError(
        "core.project_name_invalid",
        reason,
        obj="Proyecto nuevo",
        field="nombre",
        value=value,
        shown=shown,
    )


def validate_project_name(name: object) -> str:
    """El nombre sin espacios a los lados si vale como nombre de carpeta en Windows;
    :class:`ValidationError` con el carácter o el nombre si no."""
    if not isinstance(name, str) or not name.strip():
        raise _invalid_name("el nombre está vacío: escriba uno", name)
    text = name.strip()
    if len(text) > MAX_PROJECT_NAME:
        raise _invalid_name(
            f"tiene {len(text)} caracteres y el máximo es {MAX_PROJECT_NAME}",
            text,
            shown=f"«{text[:20]}…»",
        )
    for char in text:
        if char in FORBIDDEN_NAME_CHARS:
            raise _invalid_name(
                f"contiene «{char}», que Windows no admite en un nombre de carpeta", text
            )
        if ord(char) < 32:
            raise _invalid_name(
                f"contiene un carácter de control (código {ord(char)})", text
            )
    if text.endswith("."):
        raise _invalid_name("acaba en punto, que Windows no admite", text)
    stem = text.split(".", 1)[0].strip().upper()
    if stem in RESERVED_NAMES:
        raise _invalid_name(
            f"«{text.split('.', 1)[0].strip()}» es un nombre reservado de Windows", text
        )
    return text


def canonical_path(path: Path) -> Path:
    """La ruta canónica (``os.path.realpath``: absoluta, sin ``..`` y, en Windows, una
    unidad de red como su UNC)."""
    return Path(os.path.realpath(os.fspath(path)))


def windows_drive_type(root: str) -> int:
    """``GetDriveTypeW`` de la raíz de una unidad (``"X:\\\\"``); 0 fuera de Windows."""
    if sys.platform != "win32":
        return 0
    import ctypes  # solo en Windows

    return int(ctypes.windll.kernel32.GetDriveTypeW(root))  # type: ignore[attr-defined]


_SEPARATORS = "\\/"


def _is_unc(text: str) -> bool:
    """Verdadero si ``text`` empieza por un recurso UNC (``\\\\servidor\\recurso``, con
    barras invertidas o normales)."""
    drive = ntpath.splitdrive(text)[0]
    return len(drive) > 2 and drive[0] in _SEPARATORS and drive[1] in _SEPARATORS


def is_network_path(path: Path, drive_type: DriveType | None = None) -> bool:
    """Verdadero si ``path`` es una ruta UNC o está en una unidad de red (una relativa,
    según la carpeta de trabajo)."""
    text = os.fspath(path)
    if not ntpath.splitdrive(text)[0]:
        text = os.fspath(Path(path).absolute())
    if _is_unc(text):
        return True
    drive = ntpath.splitdrive(text)[0]
    if not drive:
        return False
    check = windows_drive_type if drive_type is None else drive_type
    return check(drive + "\\") == DRIVE_REMOTE


def _volume(path: Path) -> str:
    return ntpath.splitdrive(os.fspath(path))[0].replace("/", "\\").casefold()


def _anchor_root(project: ProjectLike, userdata: UserData) -> Path:
    original = userdata.checkout_original(project.uid)
    return Path(original) if original is not None else Path(project.root)


def make_external_ref(
    target: Path,
    project: ProjectLike,
    userdata: UserData,
    *,
    canonical: Canonical = canonical_path,
) -> ExternalRef:
    """La referencia de ``target`` para guardarla en el proyecto (RF-002-19); si está en
    otro volumen, anota su ruta completa en ``userdata``."""
    full = canonical(Path(target))
    root = canonical(_anchor_root(project, userdata))
    ref_uid = new_uid()
    if _volume(full) and _volume(full) == _volume(root):
        relative = PurePath(os.path.relpath(full, root)).as_posix()
        return ExternalRef("project", relative, ref_uid)
    userdata.set_external_ref(project.uid, ref_uid, full)
    return ExternalRef("external", full.name, ref_uid)


def resolve_external_ref(
    ref: ExternalRef,
    project: ProjectLike,
    userdata: UserData,
    *,
    canonical: Canonical = canonical_path,
) -> Path | None:
    """La ruta completa de una referencia en este equipo, o ``None`` si es de otro
    volumen y aquí no está anotada («no localizable»)."""
    if ref.anchor == "project":
        root = canonical(_anchor_root(project, userdata))
        return Path(os.path.normpath(root / Path(ref.path)))
    return userdata.external_ref(project.uid, ref.ref_uid)


def find_absolute_paths(value: object) -> list[str]:
    """Las rutas absolutas que aparecen en ``value`` (textos, y claves y elementos de
    diccionarios, listas y tuplas), en orden de aparición."""
    found: list[str] = []
    stack: list[object] = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            found.extend(match.group(0) for match in ABSOLUTE_PATH.finditer(item))
        elif isinstance(item, dict):
            for key, inner in reversed(list(item.items())):
                stack.extend([inner, key])
        elif isinstance(item, (list, tuple)):
            stack.extend(reversed(item))
    return found


BLEND_RELATIVE_PREFIX = "//"  # Blender: «relativa a la carpeta del .blend»


def blend_relative_path(target: Path, blend_file: Path | str | None) -> str:
    """``target`` (una carpeta) relativa a la carpeta de ``blend_file``, con «/», el
    prefijo ``//`` de Blender y la barra final (``//../`` para un ``.blend`` de
    ``scenes/``; ``//`` si es la misma carpeta). Vacía si ``blend_file`` falta (vista sin
    guardar) o está en otro volumen: nunca se devuelve una ruta absoluta (RF-002-18)."""
    if blend_file is None or not os.fspath(blend_file):
        return ""
    folder = Path(blend_file).parent
    if not same_volume(Path(target), folder):
        return ""
    try:
        relative = os.path.relpath(os.fspath(target), os.fspath(folder))
    except ValueError:  # otra unidad, en Windows
        return ""
    if relative == os.curdir:
        return BLEND_RELATIVE_PREFIX
    return f"{BLEND_RELATIVE_PREFIX}{PurePath(relative).as_posix()}/"


def same_volume(first: Path | str, second: Path | str) -> bool:
    """Verdadero si las dos rutas son de la misma unidad o del mismo recurso UNC (sin
    distinguir mayúsculas; dos relativas, del mismo)."""
    return _volume(Path(first)) == _volume(Path(second))


def is_within(path: Path | str | None, folder: Path | str) -> bool:
    """Verdadero si ``path`` es ``folder`` o está dentro (rutas canónicas, sin distinguir
    mayúsculas en Windows); ``None`` o vacía, no."""
    if path is None or not os.fspath(path):
        return False
    try:
        target = canonical_path(Path(path))
        base = canonical_path(Path(folder))
    except (OSError, ValueError):
        return False
    if not same_volume(target, base):
        return False
    inner = os.path.normcase(os.fspath(target))
    outer = os.path.normcase(os.fspath(base)).rstrip("\\/")
    return inner == outer or inner.startswith(outer + os.sep)


def next_free_path(folder: Path, stem: str, suffix: str) -> Path:
    """``<folder>/<stem><suffix>`` o, si existe, ``<stem>-2<suffix>``, ``<stem>-3<suffix>``…:
    nunca un fichero que ya existe."""
    candidate, number = Path(folder) / f"{stem}{suffix}", 1
    while candidate.exists():
        number += 1
        candidate = Path(folder) / f"{stem}-{number}{suffix}"
    return candidate

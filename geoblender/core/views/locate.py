# SPDX-License-Identifier: GPL-3.0-or-later
"""Dónde está el proyecto de una vista (spec 010; RF-010-04, RF-010-05; RF-002-08, RF-002-18,
RF-002-28, RF-002-29; plan 010 §5.3.1, A5 y D-14).

Una vista de Blender guarda en cada escena la identidad y el nombre de su proyecto y su carpeta
**relativa** al ``.blend`` (``//../`` desde ``scenes/``; vacía si no se puede expresar así, nunca
absoluta: ``core.paths.blend_relative_path``). Cuando se carga una vista de un proyecto que no está
abierto, ``bl`` ofrece «Abrir el proyecto de esta vista» (RF-010-04), y este módulo decide, sin
interfaz y sin escribir nada:

- :func:`offer_refusal`: cuándo no se ofrece (:class:`Refusal`): con Blender sin interfaz, en un
  fichero de recuperación (``quit.blend``) o de autoguardado (``*_autosave.blend``) de la carpeta
  temporal de Blender, y en una vista que está dentro de una copia de respaldo del proyecto
  (``<Nombre>.gbproj.anterior``, ``.publicando`` o ``.respaldo-esquema-N[-n]``, con las marcas de
  ``core.project``): allí la ruta relativa lleva a la copia, que tiene la misma identidad.
- :func:`project_identity`: el ``project_uid`` del ``manifest.json`` de una carpeta, leído sin
  cerrojo y sin escribir (``None`` si no lo tiene); :func:`project_name`, su nombre, igual.
- :func:`find_project`: (1) la ruta relativa de la vista desde la carpeta del ``.blend``, si allí
  está ese proyecto; (2) si no, entre los recientes del equipo (RF-002-08), el de esa identidad que
  existe y la tiene; (3) si no, :class:`NotFound` con la ubicación y la identidad esperadas y lo
  que hay allí (RF-010-05). Nunca da otro proyecto en su lugar.
- :func:`check_chosen`: si la carpeta que elige la persona en «Localizar el proyecto…» es ese
  proyecto (RF-010-05).

Lo que hace Blender 5.2.1 (comprobado en ``blender -b`` con un perfil temporal, 010/T06):
``wm.recover_last_session`` lee ``quit.blend`` de la carpeta temporal base (la de las
preferencias o, si no hay, ``%TEMP%``; ``bpy.app.tempdir`` es una subcarpeta ``blender_*`` de
ella), y ``wm.save_auto_save`` (y el autoguardado) escribe allí ``<nombre>_<pid>_autosave.blend``
(``<pid>_autosave.blend`` si el fichero no se ha guardado nunca), que lee
``wm.recover_auto_save``. Al recuperar, ``load_post`` recibe la ruta del fichero **leído** (el de
la carpeta temporal), pero ``bpy.data.filepath`` es la del **original** que anotó Blender al
escribirlo (la vista, en su carpeta; la del fichero leído si no anotó ninguna). Por eso ``bl``
pasa a :func:`offer_refusal` el argumento de ``load_post``, no ``bpy.data.filepath``: con este,
un autoguardado de una vista de ``scenes/`` parecería la vista. Python puro (ADR-0004).
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from ..paths import BLEND_RELATIVE_PREFIX, path_forms
from ..project.checkout import PREVIOUS_MARK, PROJECT_SUFFIX, PUBLISHING_MARK
from ..project.manifest import MANIFEST_FORMAT, manifest_path
from ..project.migrations import BACKUP_MARK
from ..userdata import RecentProject

__all__ = [
    "AUTOSAVE_SUFFIX",
    "CHOSEN",
    "RECENT",
    "RECOVERY_FILE",
    "RELATIVE",
    "Located",
    "NotFound",
    "Refusal",
    "ViewLink",
    "backup_copy_of",
    "check_chosen",
    "find_project",
    "offer_refusal",
    "project_identity",
    "project_name",
    "relative_root",
]

RECOVERY_FILE = "quit.blend"
"""El fichero de «Recuperar la última sesión» en la carpeta temporal de Blender."""
AUTOSAVE_SUFFIX = "_autosave.blend"
"""El final de los ficheros de autoguardado de Blender en su carpeta temporal
(``<nombre>_<pid>_autosave.blend`` o ``<pid>_autosave.blend``)."""

RELATIVE = "relative"
"""Encontrado por la ruta relativa que guarda la vista."""
RECENT = "recent"
"""Encontrado por su identidad entre los proyectos recientes del equipo."""
CHOSEN = "chosen"
"""La carpeta que eligió la persona en «Localizar el proyecto…»."""

_BACKUP_COPY = re.compile(
    re.escape(PROJECT_SUFFIX)
    + "(?:"
    + "|".join(
        (
            re.escape(PREVIOUS_MARK),
            re.escape(PUBLISHING_MARK),
            re.escape(BACKUP_MARK) + r"\d+(?:-\d+)?",
        )
    )
    + r")\Z",
    re.IGNORECASE,
)
"""El final del nombre de una copia de respaldo del proyecto: ``<Nombre>.gbproj.anterior``,
``.publicando`` o ``.respaldo-esquema-N`` (``-N-n`` si ya había una)."""


class Refusal(StrEnum):
    """Por qué no se ofrece abrir el proyecto de una vista (RF-010-04)."""

    BACKGROUND = "BACKGROUND"  # Blender sin interfaz (``blender -b``, guiones)
    RECOVERY = "RECOVERY"  # «Recuperar la última sesión» (``quit.blend``)
    AUTOSAVE = "AUTOSAVE"  # «Recuperar un autoguardado» (``*_autosave.blend``)
    BACKUP_COPY = "BACKUP_COPY"  # la vista está dentro de una copia de respaldo del proyecto


@dataclass(frozen=True)
class ViewLink:
    """Lo que guarda una escena de la vista sobre su proyecto (``Scene.geoblender``,
    RF-002-28): su identidad, su nombre y su carpeta relativa al ``.blend``."""

    project_uid: str
    project_name: str
    relative_path: str  # «//../» desde scenes/; vacía si no se pudo expresar así


@dataclass(frozen=True)
class Located:
    """El proyecto de la vista: su carpeta y cómo se encontró (:data:`RELATIVE`,
    :data:`RECENT` o :data:`CHOSEN`)."""

    root: Path
    how: str


@dataclass(frozen=True)
class NotFound:
    """El proyecto de la vista no está (RF-010-05): ``expected``, la ubicación donde se esperaba
    (la de su ruta relativa o, sin ella, la del reciente de esa identidad; ``None`` si no había
    ninguna); ``link``, lo que guarda la vista (la identidad y el nombre esperados); y
    ``found_uid``, la identidad que tiene lo que hay en ``expected`` (``None`` si nada)."""

    expected: Path | None
    link: ViewLink
    found_uid: str | None


def _same_folder(first_forms: Sequence[str], second: Path) -> bool:
    try:
        return bool(set(first_forms) & set(path_forms(second)))
    except (TypeError, ValueError):
        return False


def backup_copy_of(blend_file: Path | str) -> Path | None:
    """La copia de respaldo del proyecto que contiene ``blend_file`` (la carpeta más cercana
    que se llama ``<Nombre>.gbproj.anterior``, ``.publicando`` o ``.respaldo-esquema-N[-n]``,
    sin distinguir mayúsculas), o ``None``."""
    for parent in Path(blend_file).parents:
        if _BACKUP_COPY.search(parent.name):
            return parent
    return None


def offer_refusal(
    blend_file: str | None, *, background: bool, temp_dirs: Sequence[Path]
) -> Refusal | None:
    """Por qué no se ofrece «Abrir el proyecto de esta vista» tras cargar ``blend_file`` (el
    fichero que se ha leído: el argumento de ``load_post``), o ``None`` si se ofrece
    (RF-010-04; D-14).

    ``temp_dirs``, las carpetas temporales de Blender (la de las preferencias, la base de
    ``bpy.app.tempdir`` y la del sistema; las relativas o vacías no cuentan): ``quit.blend`` y
    ``*_autosave.blend`` solo son de recuperación dentro de una de ellas. No escribe nada."""
    if background:
        return Refusal.BACKGROUND
    if not blend_file:
        return None
    path = Path(blend_file)
    name = path.name.casefold()
    kind = (
        Refusal.RECOVERY if name == RECOVERY_FILE
        else Refusal.AUTOSAVE if name.endswith(AUTOSAVE_SUFFIX)
        else None
    )
    if kind is not None:
        try:
            folder = path_forms(path.parent)
        except (TypeError, ValueError):
            folder = ()
        if any(Path(temp).is_absolute() and _same_folder(folder, Path(temp))
               for temp in temp_dirs):
            return kind
    if backup_copy_of(path) is not None:
        return Refusal.BACKUP_COPY
    return None


def _header_text(folder: Path, key: str) -> str | None:
    """El texto ``key`` del ``manifest.json`` de Geoblender de ``folder`` (``None`` si no hay
    carpeta, cabecera legible de Geoblender o un texto no vacío). Solo lee la cabecera."""
    try:
        data = json.loads(manifest_path(Path(folder)).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("format") != MANIFEST_FORMAT:
        return None
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def project_identity(folder: Path) -> str | None:
    """El ``project_uid`` del ``manifest.json`` de ``folder``, o ``None`` si no hay carpeta,
    cabecera legible de Geoblender o identidad de texto. Solo lee la cabecera: sin cerrojo, sin
    abrir la base de datos y sin escribir nada (RF-010-04, RF-010-05)."""
    return _header_text(folder, "project_uid")


def project_name(folder: Path) -> str | None:
    """El nombre (``name``) del proyecto del ``manifest.json`` de ``folder``, o ``None`` si no
    hay carpeta, cabecera legible de Geoblender o nombre de texto: para decir qué proyecto es el
    que no se abre en «Localizar el proyecto…» (RF-010-05). Solo lee la cabecera, como
    :func:`project_identity`."""
    return _header_text(folder, "name")


def relative_root(relative_path: str, blend_file: Path | str | None) -> Path | None:
    """La carpeta a la que lleva ``relative_path`` (``//…``, relativa a la carpeta de
    ``blend_file``, como la guarda la vista), o ``None`` si está vacía, no es una ruta relativa
    de Blender (una absoluta no se usa nunca: RF-002-18) o falta el ``.blend``."""
    if not blend_file or not os.fspath(blend_file):
        return None
    if not relative_path.startswith(BLEND_RELATIVE_PREFIX):
        return None
    rest = relative_path[len(BLEND_RELATIVE_PREFIX):]
    if rest.startswith(("/", "\\")) or Path(rest).drive:
        return None
    folder = Path(blend_file).parent
    return Path(os.path.normpath(os.path.join(os.fspath(folder), rest or os.curdir)))


def find_project(
    link: ViewLink,
    blend_file: Path | str | None,
    recent: Sequence[RecentProject],
    *,
    identity: Callable[[Path], str | None] = project_identity,
) -> Located | NotFound:
    """Dónde está el proyecto de la vista ``blend_file`` (RF-010-04, RF-010-05; plan A5):

    1. la carpeta de su ruta relativa (:func:`relative_root`), si tiene esa identidad;
    2. si no, el primer reciente del equipo con esa identidad (``recent``, de
       ``UserData.recent_projects``) cuya carpeta existe y la tiene; los de otros proyectos no
       se leen;
    3. si no, :class:`NotFound` con la primera ubicación mirada y lo que hay en ella.

    Solo lee las cabeceras (``identity``); nunca da otro proyecto en su lugar."""
    looked: list[tuple[Path, str | None]] = []
    candidate = relative_root(link.relative_path, blend_file)
    if candidate is not None:
        found = identity(candidate)
        if found == link.project_uid:
            return Located(candidate, RELATIVE)
        looked.append((candidate, found))
    for item in recent:
        if item.uid != link.project_uid:
            continue
        folder = Path(item.path)
        if any(os.path.normcase(os.fspath(folder)) == os.path.normcase(os.fspath(seen))
               for seen, _ in looked):
            continue
        found = identity(folder)
        if found == link.project_uid:
            return Located(folder, RECENT)
        looked.append((folder, found))
    if not looked:
        return NotFound(None, link, None)
    expected, found_uid = looked[0]
    return NotFound(expected, link, found_uid)


def check_chosen(
    folder: Path,
    link: ViewLink,
    *,
    identity: Callable[[Path], str | None] = project_identity,
) -> Located | NotFound:
    """«Localizar el proyecto…»: :class:`Located` si ``folder`` tiene la identidad de la
    vista; si no, :class:`NotFound` con esa carpeta y la identidad que tiene (RF-010-05). Solo
    lee su cabecera."""
    folder = Path(folder)
    found = identity(folder)
    if found == link.project_uid:
        return Located(folder, CHOSEN)
    return NotFound(folder, link, found)

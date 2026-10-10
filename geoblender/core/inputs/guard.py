# SPDX-License-Identifier: GPL-3.0-or-later
"""Guarda de las escrituras de Geoblender (spec 008; RF-008-14, RF-008-15; S-3 del plan 008;
ADR-0025 §9; plan 008 §5.3.1, §5.3.4 «Exportar» y §5.4.13).

Antes de escribir un entregable (una exportación) o cualquier fichero fuera de lo que gestiona
el proyecto, un módulo llama a :func:`check_write_target` con la ruta de destino, el proyecto
abierto y las carpetas de solo lectura (``core.paths.ReadOnlyDirs``, que ``bl`` construye con la
variable ``GEOBLENDER_READ_ONLY_DIRS`` y la preferencia del usuario). Rechaza, con un
``ProvenanceError`` que nombra la carpeta o la entrada, y sin escribir nada:

1. una ruta dentro de una carpeta de solo lectura, o la propia carpeta, por su unidad o por su
   ruta UNC y sin distinguir mayúsculas (``core.write_target_read_only``, con la carpeta como
   se declaró); va primero: no lee el proyecto;
2. la fuente de una entrada registrada que está fuera del proyecto, o cualquier ruta dentro de
   la carpeta que la contiene (también un auxiliar como ``-wal`` o una subcarpeta nueva),
   salvo dentro del propio proyecto, que puede estar en esa carpeta
   (``core.write_target_source_folder``, el texto de la spec §8);
3. el propio fichero de una fuente que está dentro del proyecto (``core.write_target_source``).

Cuentan todas las entradas registradas, también las sustituidas y las descartadas (su fuente
sigue siendo un fichero del usuario), por su ubicación en este equipo (``resolve_source``): la
de otro volumen sin anotar es «no localizable» (RF-008-13) y no impide nada. Una tabla del
proyecto no es un fichero. Sin proyecto (``project=None``), o en uno sin las tablas de las
entradas (esquema 1 en solo lectura), solo cuentan las carpetas de solo lectura.

:func:`read_only_warnings` da los avisos de las carpetas de solo lectura: una entrada que no es
una ruta completa y la lista combinada vacía (S-3). Solo lee: no crea, cambia ni abre ningún
fichero de destino. Python puro (ADR-0004).
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import AbstractContextManager
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from ..paths import READ_ONLY_DIRS_ENV, Canonical, PathText, ReadOnlyDirs, forms_within
from ..provenance.messages import ProvenanceError, render
from .model import INACTIVE_STATUSES, FileAnchor, SourceFile
from .registry import resolve_source

if TYPE_CHECKING:
    from ..userdata import UserData

_INACTIVE = ", ".join(f"'{status}'" for status in INACTIVE_STATUSES)
_INPUT_TABLES = ("gb_input", "gb_input_file")
_SOURCES = (
    "SELECT i.name, f.role, f.anchor, f.path, f.ref_uid FROM gb_input_file AS f "
    "JOIN gb_input AS i ON i.uid = f.input_uid "
    f"WHERE f.anchor <> '{FileAnchor.PROJECT_TABLE}' "
    f"ORDER BY i.status IN ({_INACTIVE}), i.fid, f.ord"
)
"""Los ficheros de las fuentes, de las entradas activas primero y por su registro."""


class GuardProject(Protocol):
    """Lo que la guarda usa del proyecto (``core.project.Project``): su identidad, su raíz, los
    datos de usuario del equipo (dónde están las fuentes de otro volumen) y una lectura."""

    @property
    def uid(self) -> str: ...

    @property
    def root(self) -> Path: ...

    @property
    def userdata(self) -> UserData: ...

    def read(self) -> AbstractContextManager[sqlite3.Connection]: ...


def _sources(conn: sqlite3.Connection) -> list[tuple[str, SourceFile]]:
    """El nombre de la entrada y cada fichero de su fuente (sin las tablas del proyecto)."""
    found = conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type = 'table' AND name IN (?, ?)",
        _INPUT_TABLES,
    ).fetchone()[0]
    if found < len(_INPUT_TABLES):
        return []
    return [
        (name, SourceFile(path, role, anchor, ref_uid=ref_uid))
        for name, role, anchor, path, ref_uid in conn.execute(_SOURCES)
    ]


def _lenient(resolve: Canonical) -> Canonical:
    """``resolve`` que, si falla (la red no responde), da la ruta absoluta sin resolver."""

    def resolved(path: Path) -> Path:
        try:
            return resolve(path)
        except (OSError, ValueError):
            return Path(os.path.abspath(path))

    return resolved


def check_write_target(
    path: PathText,
    *,
    project: GuardProject | None,
    read_only: ReadOnlyDirs,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Rechaza (``ProvenanceError``, sin escribir nada) que Geoblender escriba en ``path``
    (un fichero o una carpeta) si es o está dentro de una carpeta de ``read_only``, de la
    carpeta de la fuente de una entrada de ``project`` que está fuera de él, o si es el fichero
    de una fuente que está dentro (véase el módulo; RF-008-15). ``conn``: la conexión de quien
    llama (ve lo que aún no confirmó); si no, se lee el proyecto. ``TypeError`` si ``read_only``
    no es un ``ReadOnlyDirs`` o ``path`` no es una ruta, y ``ValueError`` si está vacía."""
    if not isinstance(read_only, ReadOnlyDirs):
        raise TypeError(f"las carpetas de solo lectura son un ReadOnlyDirs, no {read_only!r}")
    target = read_only.forms(path)
    folder = read_only.folder_of(target)
    if folder is not None:
        raise ProvenanceError("core.write_target_read_only", folder=os.fspath(folder))
    if project is None:
        return
    if conn is None:
        with project.read() as reading:
            sources = _sources(reading)
    else:
        sources = _sources(conn)
    if not sources:
        return
    canonical = _lenient(read_only.resolve)
    project_forms = read_only.forms(project.root)
    in_project = forms_within(target, project_forms)
    for name, source in sources:
        found = resolve_source(source, project, project.userdata, canonical=canonical)
        if found is None:  # no localizable en este equipo (RF-008-13)
            continue
        source_forms = read_only.forms(found)
        if forms_within(source_forms, project_forms):
            if set(target) & set(source_forms):
                raise ProvenanceError("core.write_target_source", file=found.name, name=name)
            continue
        if in_project:
            continue
        parent = found.parent
        if forms_within(target, read_only.forms(parent)):
            raise ProvenanceError("core.write_target_source_folder",
                                  folder=parent.name or os.fspath(parent), name=name)


def read_only_warnings(read_only: ReadOnlyDirs, language: str = "es") -> tuple[str, ...]:
    """Los avisos de las carpetas de solo lectura, en ``language``: uno por cada entrada que no
    es una ruta completa (no protege nada) y, si no queda ninguna carpeta, el de la lista vacía
    (S-3); ninguno si todo está bien."""
    if not isinstance(read_only, ReadOnlyDirs):
        raise TypeError(f"las carpetas de solo lectura son un ReadOnlyDirs, no {read_only!r}")
    found = [render("core.read_only_dir_ignored", language=language, folder=entry)
             for entry in read_only.ignored]
    if read_only.empty:
        found.append(render("core.read_only_dirs_empty", language=language,
                            variable=READ_ONLY_DIRS_ENV))
    return tuple(found)

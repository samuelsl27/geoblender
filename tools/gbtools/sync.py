# SPDX-License-Identifier: GPL-3.0-or-later
"""Copia espejo de la extensión (plan 001 §5.4.5).

La usan las pruebas de Blender (copia local en ``%TEMP%``) y la instalación de
desarrollo (perfil aislado): ``mirror(src, dst, exclude)`` deja ``dst`` igual que
``src`` sin lo que excluyen los patrones (los de ``[build] paths_exclude_pattern`` del
manifiesto, con la sintaxis de ``gbtools.ignore``):

1. Recorre ``src`` sin seguir enlaces; un enlace simbólico o una unión en ``src`` es un
   error (:class:`SyncError`) y no se escribe nada.
2. Copia con ``shutil.copy2`` (conserva la fecha) cada fichero que falta en ``dst`` o
   difiere en tamaño o en ``mtime_ns``: la siguiente pasada sin cambios no copia nada.
3. Borra de ``dst`` lo que ya no existe en ``src`` o ahora está excluido, y crea las
   carpetas que faltan. Un enlace de ``dst`` se quita sin seguirlo.
4. Devuelve :class:`SyncReport`. Nunca escribe fuera de ``dst``; ``src`` y ``dst`` no
   pueden ser el mismo sitio ni estar uno dentro del otro.
"""

from __future__ import annotations

import os
import shutil
import stat
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .ignore import IgnoreSpec


class SyncError(Exception):
    """La copia espejo no se puede hacer; no se ha escrito nada en el destino."""


@dataclass
class SyncReport:
    """Resultado de una copia espejo, con rutas relativas y «/».

    ``copied``: ficheros copiados; ``deleted``: lo borrado del destino (las carpetas,
    una vez y con «/» final); ``unchanged``: ficheros que ya estaban al día.
    """

    copied: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    unchanged: int = 0


def _is_link(entry: os.DirEntry[str]) -> bool:
    return entry.is_symlink() or entry.is_junction()


def _scan_source(
    folder: Path, prefix: str, spec: IgnoreSpec, dirs: set[str], files: set[str]
) -> None:
    with os.scandir(folder) as scan:
        entries = sorted(scan, key=lambda entry: entry.name)
    for entry in entries:
        rel = prefix + entry.name
        if _is_link(entry):
            raise SyncError(
                f"«{rel}» es un enlace simbólico o una unión dentro de «{folder}»: la "
                "extensión no puede contener enlaces (el repositorio vive en un recurso "
                "SMB); sustitúyalo por el fichero o la carpeta real"
            )
        is_dir = entry.is_dir(follow_symlinks=False)
        if spec.matches_entry(rel, is_dir):
            continue
        if is_dir:
            dirs.add(rel)
            _scan_source(Path(entry.path), rel + "/", spec, dirs, files)
        elif entry.is_file(follow_symlinks=False):
            files.add(rel)


def _inside(path: Path, other: Path) -> bool:
    return path == other or other in path.parents


def _check_folders(src: Path, dst: Path) -> None:
    if not src.is_dir():
        raise SyncError(f"no existe la carpeta de origen «{src}»")
    real_src, real_dst = src.resolve(), dst.resolve()
    if _inside(real_dst, real_src) or _inside(real_src, real_dst):
        raise SyncError(
            f"el destino «{dst}» y el origen «{src}» no pueden ser el mismo sitio ni "
            "estar uno dentro del otro"
        )
    if dst.exists() and not dst.is_dir():
        raise SyncError(f"el destino «{dst}» existe y no es una carpeta")


def _clear_readonly(
    function: Callable[..., object], path: str, _error: BaseException
) -> None:
    """Para ``shutil.rmtree``: quita el atributo de solo lectura y reintenta."""
    os.chmod(path, stat.S_IWRITE)
    function(path)


def _remove_extra(
    folder: Path, prefix: str, dirs: set[str], files: set[str], report: SyncReport
) -> None:
    with os.scandir(folder) as scan:
        entries = sorted(scan, key=lambda entry: entry.name)
    for entry in entries:
        rel = prefix + entry.name
        if _is_link(entry):
            os.unlink(entry.path)  # quita el enlace (también a carpeta) sin seguirlo
            report.deleted.append(rel)
        elif entry.is_dir(follow_symlinks=False):
            if rel in dirs:
                _remove_extra(Path(entry.path), rel + "/", dirs, files, report)
            else:
                shutil.rmtree(entry.path, onexc=_clear_readonly)
                report.deleted.append(rel + "/")
        elif rel not in files:
            try:
                os.unlink(entry.path)
            except PermissionError:
                os.chmod(entry.path, stat.S_IWRITE)
                os.unlink(entry.path)
            report.deleted.append(rel)


def mirror(src: Path, dst: Path, exclude: Sequence[str]) -> SyncReport:
    """Deja ``dst`` igual que ``src`` salvo lo excluido; ver el docstring del módulo.

    Lanza :class:`SyncError` (origen inexistente, enlace en el origen, carpetas
    anidadas) o :class:`gbtools.ignore.UnsupportedPattern` (patrón con «!») antes de
    escribir nada.
    """
    src, dst = Path(src), Path(dst)
    spec = IgnoreSpec.from_lines(exclude)
    _check_folders(src, dst)
    dirs: set[str] = set()
    files: set[str] = set()
    _scan_source(src, "", spec, dirs, files)

    report = SyncReport()
    dst.mkdir(parents=True, exist_ok=True)
    _remove_extra(dst, "", dirs, files, report)
    for rel in sorted(dirs):
        (dst / rel).mkdir(parents=True, exist_ok=True)
    for rel in sorted(files):
        source, target = src / rel, dst / rel
        source_stat = source.stat()
        try:
            target_stat = target.stat()
        except FileNotFoundError:
            target_stat = None
        if (
            target_stat is not None
            and target_stat.st_size == source_stat.st_size
            and target_stat.st_mtime_ns == source_stat.st_mtime_ns
        ):
            report.unchanged += 1
            continue
        if target_stat is not None and not target_stat.st_mode & stat.S_IWRITE:
            os.chmod(target, stat.S_IWRITE)
        shutil.copy2(source, target)
        report.copied.append(rel)
    return report

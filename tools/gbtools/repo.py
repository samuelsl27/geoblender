# SPDX-License-Identifier: GPL-3.0-or-later
"""El «repositorio comprobado»: los ficheros que miran las reglas (spec 001 §4.4).

Todos los ficheros del repositorio salvo ``.git/`` (en cualquier nivel) y lo que excluye
el ``.gitignore`` raíz. El repositorio de código no tiene ``Documentacion/`` ni
``Promts/`` (spec 007: si aparecen, REP-01 las señala); la documentación las excluye con
``layout.DOCS_EXCLUDED``. El recorrido no entra en enlaces simbólicos ni en puntos de
reparación: los devuelve como ficheros para que la regla TXT-03 los señale.

La raíz del repositorio de código (:func:`repo_root`, por sus marcadores) y la carpeta de
la documentación (:func:`find_docs` y :func:`docs_root`; spec 007, RF-007-06, RF-007-12 y
RF-007-13).

También la foto de una carpeta (:func:`snapshot`, rutas, tamaños y ``mtime_ns``) y sus
diferencias (:func:`snapshot_changes`): con ella el banco comprueba que no escribe en
su carpeta y ``tools/check.py``, que la comprobación no escribe en el repositorio.

Y el texto de los ficheros que leen las reglas (:func:`read_bytes`; spec 006, T47;
RNF-001-01): cada fichero se lee una sola vez por proceso mientras no cambie (su ruta,
su fecha y su tamaño), y lo comparten todas las familias de reglas y las pruebas que las
llaman.
"""

from __future__ import annotations

import functools
import os
import re
from collections.abc import Collection, Iterator, Mapping, Sequence
from pathlib import Path

from .ignore import IgnoreSpec
from .layout import DOCS_MARKER, ENV_DOCS_DIR, ROOT_MARKERS

# Lo que el código nunca recorre (spec 007, T15: Documentacion/ y Promts/ pasaron a
# layout.DOCS_EXCLUDED, que usa la documentación).
ALWAYS_EXCLUDED: tuple[str, ...] = (".git",)

# Extensiones binarias de .gitattributes (plan 001 §5.4.1); las copias de seguridad
# .blend1, .blend2… se reconocen aparte.
BINARY_SUFFIXES: frozenset[str] = frozenset(
    {
        ".png", ".jpg", ".jpeg", ".ico", ".exe", ".dll", ".whl", ".zip", ".blend",
        ".tif", ".tiff", ".npz", ".npy", ".parquet", ".duckdb", ".gpkg", ".gpkg-wal",
        ".gpkg-shm", ".mdb", ".accdb", ".odt", ".ods", ".odp", ".docx", ".xlsx",
        ".pptx", ".pdf",
    }
)
_BLEND_BACKUP = re.compile(r"\.blend\d+$")

# El texto compartido de las reglas (spec 006, T47): cuántos ficheros guarda la caché
# (el repositorio tiene unos 800) y el tamaño a partir del cual un fichero se lee cada
# vez (ninguno del repositorio llega).
TEXT_CACHE_SIZE = 4096
TEXT_CACHE_MAX_BYTES = 4 * 1024 * 1024

FileKey = tuple[str, int, int]  # (ruta, mtime_ns, tamaño): identifica un contenido


def repo_root(start: Path | None = None) -> Path:
    """Sube desde ``start`` (por defecto, este fichero) hasta la raíz del repositorio.

    La raíz es la primera carpeta con los dos ``layout.ROOT_MARKERS`` (el manifiesto de
    la extensión y ``tools/check.py``): no necesita la documentación (RF-007-06).
    """
    here = (start if start is not None else Path(__file__)).resolve()
    for candidate in (here, *here.parents):
        if all((candidate / marker).is_file() for marker in ROOT_MARKERS):
            return candidate
    markers = " y ".join(f"«{marker}»" for marker in ROOT_MARKERS)
    raise FileNotFoundError(
        "No se encuentra la raíz del repositorio de Geoblender (una carpeta con "
        f"{markers}) en «{here}» ni por encima"
    )


class DocsProblem(Exception):
    """La carpeta de la documentación no existe, no se puede leer o no lo es."""


def find_docs(
    code_root: Path, environ: Mapping[str, str], argument: str | None = None
) -> Path | None:
    """La carpeta de la documentación (RF-007-12): el argumento; si no, la variable
    ``GEOBLENDER_DOCS_DIR`` (vacía no cuenta); si no, la carpeta madre del repositorio
    de código cuando tiene ``docs/constitution.md``; si no, ``None``. No comprueba la
    carpeta que dan el argumento o la variable: eso es :func:`docs_root`."""
    if argument:
        return Path(argument).resolve()
    value = environ.get(ENV_DOCS_DIR, "")
    if value:
        return Path(value).resolve()
    parent = Path(code_root).resolve().parent
    if (parent / DOCS_MARKER).is_file():
        return parent
    return None


def docs_root(path: Path) -> Path:
    """``path`` si es la carpeta de la documentación (existe, se lee y tiene
    ``docs/constitution.md``); si no, :class:`DocsProblem` con lo que falta (RF-007-13)."""
    folder = Path(path)
    if not folder.exists():
        raise DocsProblem(f"la carpeta de la documentación «{folder}» no existe")
    if not folder.is_dir():
        raise DocsProblem(f"«{folder}» no es una carpeta")
    try:
        os.listdir(folder)
    except OSError as exc:
        raise DocsProblem(f"no se puede leer la carpeta «{folder}»: {exc}") from exc
    if not (folder / DOCS_MARKER).is_file():
        raise DocsProblem(
            f"«{folder}» no es la documentación de Geoblender: no tiene «{DOCS_MARKER}»"
        )
    return folder


def file_key(path: Path) -> FileKey:
    """``(ruta, mtime_ns, tamaño)`` de ``path``: la clave de su contenido en las cachés
    de las reglas (:func:`read_bytes`, ``rules.pyast``)."""
    stat = Path(path).stat()
    return str(path), stat.st_mtime_ns, stat.st_size


@functools.lru_cache(maxsize=TEXT_CACHE_SIZE)
def _read_cached(path: str, mtime_ns: int, size: int) -> bytes:
    del mtime_ns, size  # forman parte de la clave de la caché
    return Path(path).read_bytes()


def read_bytes(path: Path, key: FileKey | None = None) -> bytes:
    """El contenido de ``path``, leído una sola vez por proceso mientras no cambien su
    ruta, su fecha y su tamaño (``key``, o :func:`file_key`): lo comparten todas las reglas
    (spec 006, T47; RNF-001-01). Un fichero de más de ``TEXT_CACHE_MAX_BYTES`` se lee cada
    vez. Límite declarado, el de la caché de árboles de ``rules.pyast``: un fichero que se
    reescribe con el mismo tamaño en el mismo instante (la misma ``mtime_ns``) no se
    vuelve a leer."""
    found = file_key(path) if key is None else key
    if found[2] > TEXT_CACHE_MAX_BYTES:
        return Path(path).read_bytes()
    return _read_cached(*found)


def clear_text_cache() -> None:
    """Vacía la caché de :func:`read_bytes` (``rules.pyast.clear_caches`` la vacía al salir
    del proceso)."""
    _read_cached.cache_clear()


def load_gitignore(root: Path) -> IgnoreSpec:
    """Patrones del ``.gitignore`` raíz (ninguno si no existe)."""
    path = root / ".gitignore"
    if not path.is_file():
        return IgnoreSpec()
    return IgnoreSpec.from_lines(read_bytes(path).decode("utf-8").splitlines())


def _walk(
    directory: Path, prefix: str, spec: IgnoreSpec, excluded: frozenset[str]
) -> Iterator[Path]:
    with os.scandir(directory) as scan:
        entries = sorted(scan, key=lambda entry: entry.name)
    for entry in entries:
        if entry.name == ".git" or (not prefix and entry.name.casefold() in excluded):
            continue
        rel = prefix + entry.name
        is_link = entry.is_symlink() or entry.is_junction()
        is_dir = not is_link and entry.is_dir()
        if spec.matches_entry(rel, is_dir):
            continue
        if is_dir:
            yield from _walk(Path(entry.path), rel + "/", spec, excluded)
        else:
            yield Path(entry.path)


def iter_repo_files(
    root: Path, excluded: Sequence[str] = ALWAYS_EXCLUDED
) -> Iterator[Path]:
    """Ficheros del repositorio comprobado bajo ``root``, en orden estable.

    ``excluded``: carpetas de la raíz que no se recorren, sin distinguir mayúsculas (como
    las trata Windows); ``.git`` no se recorre en ningún nivel. La documentación usa
    ``layout.DOCS_EXCLUDED``, que deja fuera también la carpeta del código (spec 007).
    Lanza :class:`gbtools.ignore.UnsupportedPattern` si el ``.gitignore`` usa «!».
    """
    folded = frozenset(name.casefold() for name in excluded)
    yield from _walk(root, "", load_gitignore(root), folded)


def iter_py_files(root: Path, *top: str) -> Iterator[Path]:
    """Los ``.py`` del repositorio comprobado; con ``top``, solo los de esas carpetas."""
    prefixes = tuple(folder.strip("/") + "/" for folder in top)
    for path in iter_repo_files(root):
        if path.suffix != ".py":
            continue
        if prefixes and not relpath(root, path).startswith(prefixes):
            continue
        yield path


def is_text_file(path: Path) -> bool:
    """Falso solo con las extensiones binarias de ``.gitattributes`` y ``.blendN``."""
    suffix = path.suffix.lower()
    return suffix not in BINARY_SUFFIXES and not _BLEND_BACKUP.search(path.name.lower())


def relpath(root: Path, path: Path) -> str:
    """Ruta de ``path`` relativa a ``root``, con «/»."""
    return path.relative_to(root).as_posix()


Snapshot = dict[str, tuple[int, int]]

ROOT_KEY = "./"  # la propia carpeta de la foto
FOLDER_CHANGED = "la fecha de la carpeta: se creó, se renombró o se borró algo en ella"


def snapshot(folder: Path, skip: Collection[str] = ()) -> Snapshot:
    """Ficheros y carpetas bajo ``folder`` con su tamaño y ``mtime_ns`` (las carpetas,
    con ``(-1, mtime_ns)`` y «/» final, y la propia ``folder`` como ``ROOT_KEY``), sin
    abrir ningún fichero ni seguir enlaces ni puntos de reparación. Crear, renombrar o
    borrar una entrada cambia la fecha de su carpeta (en NTFS y en el recurso SMB): así
    se ve también un fichero que se creó y se borró entre las dos fotos (convergencia
    de la spec 001, T51). Límite: en el recurso SMB, el servidor (Samba) publica la
    nueva fecha de la carpeta unos 2 s después, así que un fichero creado y borrado en
    los últimos 2 s antes de la segunda foto puede no verse (lo que se crea y se queda
    se ve siempre). Las carpetas cuyo nombre está en ``skip`` (p. ej. ``.git``) no se
    recorren ni se anotan, a ningún nivel. Lo que desaparece mientras se recorre, no
    cuenta. Límite declarado (hallazgo F8 de la ronda 4; convergencia, T63): un fichero
    que ya existía y se modifica y se restaura entre las dos fotos con los mismos bytes
    (el mismo tamaño) y la misma fecha (``os.utime``) no se ve: la foto no lee el
    contenido (no abre ningún fichero; RNF-001-02 y RNF-001-05) y escribir en un fichero
    que ya existe no cambia la fecha de su carpeta."""
    entries: Snapshot = {}
    try:
        entries[ROOT_KEY] = (-1, Path(folder).stat().st_mtime_ns)
        # En un disco local, NTFS actualiza con retraso la fecha de una carpeta en el
        # listado de la de fuera: se pide a la propia carpeta (una llamada más por
        # carpeta). En el recurso SMB (ruta UNC), el listado ya trae la del servidor.
        local = not str(Path(folder).resolve()).startswith("\\\\")
    except FileNotFoundError:
        return entries
    pending = [(Path(folder), "")]
    while pending:
        current, prefix = pending.pop()
        try:
            with os.scandir(current) as listing:
                found = list(listing)
        except FileNotFoundError:
            continue
        for entry in found:
            rel = prefix + entry.name
            try:
                link = entry.is_symlink() or entry.is_junction()
                if not link and entry.is_dir(follow_symlinks=False):
                    if entry.name not in skip:
                        stat = (
                            os.stat(entry.path, follow_symlinks=False)
                            if local
                            else entry.stat(follow_symlinks=False)
                        )
                        entries[rel + "/"] = (-1, stat.st_mtime_ns)
                        pending.append((Path(entry.path), rel + "/"))
                    continue
                stat = entry.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            entries[rel] = (stat.st_size, stat.st_mtime_ns)
    return entries


def snapshot_changes(before: Snapshot, after: Snapshot) -> list[str]:
    """Diferencias entre dos fotos: «nuevo: …», «borrado: …» y «cambiado: …» (una
    carpeta cambiada, con ``FOLDER_CHANGED``)."""
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(key for key in set(before) & set(after) if before[key] != after[key])
    return (
        [f"nuevo: {key}" for key in added]
        + [f"borrado: {key}" for key in removed]
        + [
            f"cambiado: {key} ({FOLDER_CHANGED})" if key.endswith("/") else f"cambiado: {key}"
            for key in changed
        ]
    )

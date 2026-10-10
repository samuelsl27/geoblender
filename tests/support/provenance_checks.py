# SPDX-License-Identifier: GPL-3.0-or-later
"""Comprobaciones de procedencia para las pruebas (spec 008, T01; plan 008 §5.1 y §5.3.4).

- :func:`assert_source_untouched`: gestor de contexto que falla (``AssertionError``) si en
  la carpeta de una fuente se creó, modificó, renombró o borró algo mientras se ejecutaba
  su bloque (RF-008-14), también un auxiliar (``-wal``, ``-shm``, ``-journal``,
  ``.aux.xml``, ``.ldb``, ``.laccdb``). Compara antes y después el listado (recursivo), el
  tamaño y el ``mtime_ns`` de cada fichero y de cada carpeta (``gbtools.repo.snapshot``) y
  el sha256 de cada fichero. La fecha de una carpeta cambia al crear, renombrar o borrar
  algo en ella: así se ve también un auxiliar que se creó y se borró dentro del bloque,
  siempre que el reloj del sistema de ficheros haya avanzado (que avanza a saltos de
  varios ms); para no depender de ello, la prueba retrasa antes la fecha de la carpeta
  (``tests.support.trees.age_folders``). Un cambio de contenido que conserva el tamaño y
  la fecha lo ve el sha256.
- :func:`source_state` y :func:`source_changes`: la foto y sus diferencias, por si una
  prueba necesita compararlas a su manera.

La usan las pruebas de la 008 y, para sus lectores e importadores, la 005 y la 006.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from tests.support.repo import tools_on_path

tools_on_path()

from gbtools import repo as _repo  # noqa: E402

# Ficheros que SQLite, GDAL y Access dejan junto a una base o un ráster (RF-008-14).
AUXILIARY_SUFFIXES: tuple[str, ...] = (
    "-wal",
    "-shm",
    "-journal",
    ".aux.xml",
    ".ldb",
    ".laccdb",
)
_CHUNK = 1 << 20


@dataclass(frozen=True)
class SourceState:
    """La foto de una carpeta: ``entries`` (ruta relativa con «/» → ``(tamaño,
    mtime_ns)``; las carpetas con «/» final y tamaño −1, la propia como «./») y
    ``digests`` (ruta relativa de cada fichero → sha256)."""

    folder: Path
    entries: dict[str, tuple[int, int]]
    digests: dict[str, str]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def source_state(folder: Path) -> SourceState:
    """La foto de ``folder``: listado, tamaños, fechas y sha256 (lee cada fichero, sin
    escribir nada)."""
    folder = Path(folder)
    entries = _repo.snapshot(folder)
    digests = {
        rel: _sha256(folder / rel) for rel in sorted(entries) if not rel.endswith("/")
    }
    return SourceState(folder, entries, digests)


def is_auxiliary(rel: str) -> bool:
    """Verdadero si ``rel`` es un auxiliar de SQLite, GDAL o Access (sin distinguir
    mayúsculas)."""
    return rel.lower().endswith(AUXILIARY_SUFFIXES)


def source_changes(before: SourceState, after: SourceState) -> list[str]:
    """Las diferencias entre dos fotos, una por línea, en español; vacía si no hay."""
    changes: list[str] = []
    for line in _repo.snapshot_changes(before.entries, after.entries):
        kind, _, rel = line.partition(": ")
        if kind == "nuevo" and is_auxiliary(rel):
            line = f"nuevo: {rel} (fichero auxiliar de SQLite, GDAL o Access)"
        changes.append(line)
    for rel in sorted(set(before.digests) & set(after.digests)):
        if before.digests[rel] != after.digests[rel]:
            changes.append(
                f"contenido cambiado: {rel} (sha256 {before.digests[rel][:12]}… → "
                f"{after.digests[rel][:12]}…)"
            )
    return changes


@contextmanager
def assert_source_untouched(folder: Path) -> Iterator[SourceState]:
    """Falla al salir del bloque si en ``folder`` cambió algo (RF-008-14). Si el bloque
    lanza una excepción, se propaga sin comprobar nada."""
    folder = Path(folder)
    before = source_state(folder)
    yield before
    changes = source_changes(before, source_state(folder))
    if changes:
        listed = "\n".join(f"  - {change}" for change in changes)
        raise AssertionError(
            f"La carpeta de la fuente «{folder.name}» ha cambiado y no debía "
            f"(RF-008-14):\n{listed}"
        )

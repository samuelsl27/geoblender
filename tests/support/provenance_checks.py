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
- :func:`assert_no_figures_in_names` (T55; RF-008-31): falla si un
  nombre (de un objeto, de una colección o de un fichero del proyecto: los reúne la prueba,
  que es la que tiene ``bpy``) contiene una cifra registrada, escrita con formato español
  («2,5», «1.250.000», «1 250 000») o inglés («2.5», «1,250,000»), con todos sus decimales o
  redondeada a los que lleve el nombre; :func:`figures_in_names` da lo que encuentra. Un
  número sin decimales cuenta solo si tiene al menos :data:`MIN_INTEGER_DIGITS` cifras: uno o
  dos dígitos sueltos (fase 2, banco B-3, ``v1``) no se distinguen de una numeración. Los uid
  (con guiones o en una tira de 16 o más caracteres hexadecimales) no son cifras.

La usan las pruebas de la 008 y, para sus lectores e importadores, la 005 y la 006.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
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


# --- Cifras en los nombres (T55; RF-008-31) ------------------------------------------------

MIN_INTEGER_DIGITS = 3
"""Las cifras de un número sin decimales para que cuente como una cifra registrada."""

_UID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{16,}",
                  re.IGNORECASE)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_SPACED = re.compile(r"(?<![\d.,])\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?(?![\d.,])")
_SPACES = re.compile(r"[   ]")
_GROUPS = re.compile(r"\d{1,3}")


def _grouped(head: str, groups: list[str]) -> bool:
    """Si ``head`` y ``groups`` son una parte entera con separador de miles (1–3 cifras y
    después grupos de 3)."""
    return bool(_GROUPS.fullmatch(head)) and all(len(group) == 3 for group in groups)


def number_readings(token: str) -> set[tuple[Decimal, int]]:
    """Las lecturas de un número escrito (``token``: cifras con «.» o «,» entre ellas) como
    (valor, decimales), en español (coma decimal y punto de miles) y en inglés (al revés):
    «2,5» → 2,5; «1.250» → 1,25 (inglés) o 1250 (español); «1.250.000» → 1250000; «0.1.0»
    (una versión) no es un número."""
    parts = re.split(r"([.,])", token)
    digits, separators = parts[0::2], parts[1::2]
    if not separators:
        return {(Decimal(token), 0)}
    found: set[tuple[Decimal, int]] = set()
    if len(set(separators)) == 1:
        if len(separators) == 1:
            found.add((Decimal(f"{digits[0]}.{digits[1]}"), len(digits[1])))
        if _grouped(digits[0], digits[1:]):
            found.add((Decimal("".join(digits)), 0))
        return found
    *thousands, decimal = separators
    if len(set(thousands)) == 1 and thousands[0] != decimal and _grouped(digits[0],
                                                                       digits[1:-1]):
        found.add((Decimal("".join(digits[:-1]) + "." + digits[-1]), len(digits[-1])))
    return found


def _tokens(name: str) -> set[str]:
    """Los números escritos en ``name`` (sin los uid), también los de miles con espacios."""
    shown = _UID.sub(" ", name)
    found = set(_NUMBER.findall(shown))
    found.update(_SPACES.sub("", match) for match in _SPACED.findall(shown))
    return found


def _matches(value: float, reading: Decimal, decimals: int) -> bool:
    """Si ``value`` (en valor absoluto) redondeado a ``decimals`` es ``reading``."""
    rounded = Decimal(repr(abs(float(value)))).quantize(Decimal(1).scaleb(-decimals),
                                                       rounding=ROUND_HALF_UP)
    if decimals == 0 and len(str(reading)) < MIN_INTEGER_DIGITS:
        return False
    return rounded == reading


def figures_in_names(names: Iterable[str],
                     figures: Iterable[float]) -> list[tuple[str, float, str]]:
    """(nombre, cifra, cómo está escrita) de cada cifra de ``figures`` que aparece en un
    nombre de ``names``, en su orden (véase el módulo)."""
    values = [float(value) for value in figures]
    found: list[tuple[str, float, str]] = []
    for name in names:
        tokens = sorted(_tokens(name), key=name.find)
        for value in values:
            for token in tokens:
                if any(_matches(value, reading, decimals)
                       for reading, decimals in number_readings(_SPACES.sub("", token))):
                    found.append((name, value, token))
                    break
    return sorted(found, key=lambda item: (item[0], item[0].find(item[2])))


def assert_no_figures_in_names(names: Iterable[str], figures: Iterable[float]) -> None:
    """Falla (``AssertionError``) si un nombre de ``names`` contiene una cifra de ``figures``
    (RF-008-31: ni en el de un objeto, ni en el de una colección, ni en el de un fichero), con
    la lista de lo que encontró."""
    found = figures_in_names(names, figures)
    if found:
        listed = "\n".join(f"  - «{name}» lleva la cifra {value!r} escrita «{token}»"
                           for name, value, token in found)
        raise AssertionError(f"Hay cifras registradas en los nombres (RF-008-31):\n{listed}")

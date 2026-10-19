# SPDX-License-Identifier: GPL-3.0-or-later
"""Comprobar las instantáneas (spec 009; RF-009-09, RF-009-23; plan 009 A8, D-5, D-11 y D-31).

Cada revisión congelada tiene su instantánea en ``snapshots/V10.r2/`` (``core.versions.copy``)
con su manifiesto, cuya huella guarda ``gb_revision.snapshot_sha256``. Lo congelado no lleva el
atributo de solo lectura del sistema (D-11): su integridad la da su huella, y esto la mira.

- **Rápida** (:func:`quick_steps`; el paso «instantáneas» de la comprobación de apertura de la
  008, tras «restos», ``core.provenance.checks``): por cada revisión congelada, la huella de su
  ``manifest.json`` (leído entero) frente a la anotada y, con un listado de cada carpeta
  (``os.scandir``, una vez cada una en toda la comprobación), la existencia y el tamaño de cada
  fichero propio (los del manifiesto), de cada fichero de otra instantánea que referencia
  (``gb_revision_item``: lo ya copiado en otra, D-28, y lo heredado de la versión de la que
  parte, D-27) y de cada original guardado de sus entradas (el tamaño del manifiesto); y lo
  importado que referencia (lo inmutable del proyecto, D-18), por su estado de la 008: ni
  ``missing`` ni ``damaged`` (RF-008-57). **Las fechas no se miran**: una copia de seguridad
  restaurada no avisa.
- **Entera** (:func:`check_steps` con ``full``, :func:`full_steps`; «Comprobar cambios en las
  entradas», RF-008-09, y antes de reproducir): además, la huella de cada fichero (sha256 por
  trozos de :data:`CHUNK_BYTES`), una vez cada uno aunque lo compartan varias revisiones. Lo que
  una entera dio con otra huella sigue así en las rápidas (que no miran huellas) mientras tenga
  su tamaño: solo otra entera dice que vuelve a coincidir.

Las dos **solo leen**: dan por cada revisión congelada un :class:`SnapshotFinding` con lo que no
coincide (:class:`Mismatch`); con algo, la revisión está **alterada** (D-5: solo ella y la que
comparte el fichero; el resto del proyecto sigue en escritura). Cada una cede —con lo hecho, de 0
a 1— cuando ``lap()`` lo pide (como ``core.provenance.stale.full_difference_steps``): la lleva
por pasos de ≤ 20 ms quien la llama (RNF-008-12); entre pasos no queda nada abierto (ni una
conexión ni un fichero). Una revisión que no se puede mirar (un error del disco o de la red que
no es «no está») no se da: queda como estaba hasta la próxima comprobación.

:func:`record_findings`, en la transacción final de la comprobación (solo en escritura): con el
estado de lo importado de ese momento (lo que acaba de registrar la 008), anota la marca
(``altered_at``, ``altered_detail``: qué no coincide) y el evento ``revision_altered`` en lo que
pasa a alterado o cambia de detalle, y la quita con ``revision_restored`` en lo que vuelve a
coincidir (D-31: una marca, no un estado: restaurar el fichero la arregla); y pone al día la
caché de la obsolescencia de lo que consumió lo congelado (plan A4 (3)). Una revisión alterada
no se usa (``Use.frozen``) ni se reproduce. El aviso grave de cada revisión que cambia,
:meth:`SnapshotFinding.text`, en los dos idiomas.

Python puro (ADR-0004). No importa ``core.provenance`` al cargarse (``core.provenance.checks``
lo importa a él: ARQ-08), solo al registrar.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from collections.abc import Callable, Generator, Iterable, Iterator, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Protocol

from ..datasets.model import DatasetStatus
from ..hashing import canonical_json
from ..project.events import EventKind, record_event
from ..project.model import Progress
from .model import SNAPSHOT_MANIFEST, expand_manifest, render, revision_label

if TYPE_CHECKING:
    from ..sysinfo import SessionInfo

PHASE = "instantáneas"
"""El nombre del paso (``Progress.phase``; el de la comprobación de apertura de la 008)."""
CHUNK_BYTES = 1 << 20
"""Lo que se lee de un fichero de una vez para su huella en la comprobación entera (1 MiB:
unos 6 ms con sha256 a 180 MB/s, trampa §2)."""
STEP_BUDGET_S = 0.020
"""Lo que puede durar un paso de :func:`full_steps` (como los de la comprobación de apertura,
RNF-008-12)."""
WORK_FRACTION = 0.5
"""La parte del presupuesto de un paso que se planea para el trabajo."""
PROGRESS_TOTAL = 1000
"""El total del progreso de :func:`full_steps` (milésimas)."""
UNUSABLE: frozenset[DatasetStatus] = frozenset({DatasetStatus.MISSING, DatasetStatus.DAMAGED})
"""Los estados de lo importado que dejan alterada la revisión que lo referencia (RF-009-09)."""

type Lap = Callable[[], bool]

_SHARE = 0.9  # la parte del progreso que es mirar las revisiones (sin huellas)
_FULL_SHARE = 0.3  # … en la entera (el resto, las huellas)
_CHUNK = 500  # uids por consulta (IN (…))
_REVISIONS_TABLE = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'gb_revision'"
_FROZEN = (  # las congeladas son pocas (una por revisión): sin índice por estado
    "SELECT r.uid, v.code, r.number, r.snapshot_dir, r.snapshot_sha256, r.altered_at, "
    "r.altered_detail FROM gb_revision AS r CROSS JOIN gb_version AS v ON v.uid = r.version_uid "
    "WHERE r.state = 'frozen' ORDER BY CAST(substr(v.code, 2) AS INTEGER), v.code, r.number"
)
_REFERENCED = (  # por el índice único de (revision_uid, item_kind, item_uid)
    "SELECT snapshot_path, file_size, file_sha256 FROM gb_revision_item "
    "WHERE revision_uid = ? AND item_kind = 'dataset' AND snapshot_path IS NOT NULL "
    "AND NOT copied ORDER BY fid"
)
_STATUSES = "SELECT uid, status FROM gb_dataset WHERE uid IN ({marks})"
_MARKS = (
    "SELECT uid, altered_at, altered_detail FROM gb_revision WHERE state = 'frozen' "
    "AND uid IN ({marks})"
)


class CheckProject(Protocol):
    """Lo que usa la comprobación del proyecto (``core.project.Project``): su raíz y una
    conexión de lectura."""

    @property
    def root(self) -> Path: ...

    def read(self) -> AbstractContextManager[sqlite3.Connection]: ...


class RecordProject(Protocol):
    """Lo que usa :func:`record_findings` del proyecto: la sesión (quién, en los eventos)."""

    @property
    def session(self) -> SessionInfo: ...


class Problem(StrEnum):
    """Qué no coincide de un fichero o de lo importado."""

    MISSING = "missing"  # falta
    SIZE = "size"  # otro tamaño
    SHA256 = "sha256"  # otra huella (en la rápida, solo la del manifiesto)
    DAMAGED = "damaged"  # lo importado, dañado (008)


_FILE_CODES: Mapping[Problem, str] = {
    Problem.MISSING: "core.version_mismatch_missing",
    Problem.SIZE: "core.version_mismatch_size",
    Problem.SHA256: "core.version_mismatch_sha256",
}
_IMPORTED_CODES: Mapping[Problem, str] = {
    Problem.MISSING: "core.version_mismatch_imported_missing",
    Problem.DAMAGED: "core.version_mismatch_imported_damaged",
}


@dataclass(frozen=True, slots=True)
class Mismatch:
    """Lo que no coincide de una instantánea: un fichero (``path``: el de la propia instantánea,
    relativo a su carpeta, «rasters/des_final_v10.tif», «manifest.json»; el de otra o un
    original, relativo al proyecto, «snapshots/V10.r1/V10.r1.gpkg») que falta, con otro tamaño
    u otra huella; o lo importado que referencia (``dataset_uid``, con su nombre en ``path``),
    que falta o está dañado. :class:`ValueError` con un problema que no es de su clase."""

    path: str
    problem: Problem
    dataset_uid: str | None = None

    def __post_init__(self) -> None:
        codes = _IMPORTED_CODES if self.dataset_uid is not None else _FILE_CODES
        if self.problem not in codes:
            raise ValueError(f"«{self.problem}» no es un problema de "
                             f"{'lo importado' if self.dataset_uid else 'un fichero'}")

    @property
    def imported(self) -> bool:
        """Verdadero si es lo importado que referencia la revisión (no un fichero)."""
        return self.dataset_uid is not None

    def text(self, language: str = "es") -> str:
        """«rasters/des_final_v10.tif: otro tamaño», «lo importado «Limites_v1»: dañado»…"""
        codes = _IMPORTED_CODES if self.imported else _FILE_CODES
        return render(codes[self.problem], language=language, path=self.path)

    def as_json(self) -> dict[str, str]:
        """Como va en ``altered_detail`` y en los eventos."""
        found = {"path": self.path, "problem": str(self.problem)}
        if self.dataset_uid is not None:
            found["dataset_uid"] = self.dataset_uid
        return found


@dataclass(frozen=True)
class SnapshotFinding:
    """Lo comprobado de una revisión congelada (``revision_uid``, ``label``: «V10.r2»): lo que no
    coincide (``what``; vacío, coincide), la marca que tenía (``altered_at``, ``altered_detail``,
    de la base) y lo importado que referencia (``imported``: uid y nombre; lo mira la 008)."""

    revision_uid: str
    label: str
    what: tuple[Mismatch, ...] = ()
    altered_at: str | None = None
    altered_detail: str | None = None
    imported: tuple[tuple[str, str], ...] = ()

    @property
    def altered(self) -> bool:
        """Verdadero si algo no coincide: la revisión está alterada (RF-009-09)."""
        return bool(self.what)

    @property
    def detail(self) -> str | None:
        """Lo que no coincide, en JSON canónico (``altered_detail``); ``None`` si nada."""
        if not self.what:
            return None
        return canonical_json([item.as_json() for item in self.what]).decode("utf-8")

    @property
    def was_altered(self) -> bool:
        """Verdadero si estaba marcada alterada."""
        return self.altered_at is not None

    @property
    def changed(self) -> bool:
        """Verdadero si hay que registrarla: pasa a alterada, deja de estarlo o cambia lo que
        no coincide."""
        return (self.altered != self.was_altered
                or (self.altered and self.detail != self.altered_detail))

    @property
    def restored(self) -> bool:
        """Verdadero si estaba alterada y vuelve a coincidir (D-31)."""
        return self.was_altered and not self.altered

    def text(self, language: str = "es") -> str | None:
        """El aviso en ``language`` si cambia: el grave de una revisión alterada («La revisión
        V10.r2 está alterada: 2 ficheros no coinciden con lo congelado (…). No se usará ni se
        reproducirá») o el de la que vuelve a coincidir; ``None`` si sigue como estaba."""
        if not self.changed:
            return None
        if not self.altered:
            return render("core.version_snapshot_restored", language=language,
                          revision=self.label)
        shown = "; ".join(item.text(language) for item in self.what)
        if len(self.what) == 1:
            return render("core.version_snapshot_altered_one", language=language,
                          revision=self.label, what=shown)
        return render("core.version_snapshot_altered", language=language, revision=self.label,
                      count=len(self.what), what=shown)


# --- Comprobar ------------------------------------------------------------------------------


class _Unreadable(Exception):
    """Algo de una revisión no se puede mirar (un error que no es «no está»)."""


@dataclass(frozen=True)
class _Row:
    uid: str
    code: str
    number: int
    snapshot_dir: str | None
    sha256: str | None
    altered_at: str | None
    altered_detail: str | None

    @property
    def label(self) -> str:
        return revision_label(self.code, self.number)


@dataclass
class _Revision:
    """Una revisión mientras se comprueba: lo que no coincide, las huellas que faltan por
    mirar (la entera) y lo importado que referencia."""

    row: _Row
    what: list[Mismatch] = field(default_factory=list)
    hashes: list[tuple[str, str, str]] = field(default_factory=list)  # ruta, la mostrada, huella
    imported: list[tuple[str, str]] = field(default_factory=list)
    seen: set[str] = field(default_factory=set)
    skipped: bool = False
    unverified: frozenset[str] = frozenset()  # las rutas mostradas con otra huella (la entera)

    def add(self, item: Mismatch) -> None:
        if item not in self.what:
            self.what.append(item)


def _safe(value: object) -> str | None:
    """Una ruta relativa con «/» dentro de su carpeta (sin «..», unidad ni raíz), o ``None``."""
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        return None
    parts = PurePosixPath(value).parts
    if not parts or value.startswith("/") or any(part in ("", ".", "..") for part in parts):
        return None
    return "/".join(parts)


def _key(rel: str) -> str:
    """La clave de una ruta relativa al proyecto para compararla (sin distinguir mayúsculas en
    Windows)."""
    return os.path.normcase(rel)


class _Listings:
    """El listado de cada carpeta del proyecto, leído una vez (``os.scandir``) y guardado como
    nombre → tamaño; nada queda abierto."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.folders: dict[str, dict[str, int]] = {}

    def size(self, rel: str) -> int | None:
        """El tamaño del fichero ``rel`` (relativo al proyecto) o ``None`` si no está.
        :class:`_Unreadable` si su carpeta no se puede listar."""
        folder, _, name = rel.rpartition("/")
        key = _key(folder)
        if key not in self.folders:
            self.folders[key] = self._list(folder)
        return self.folders[key].get(os.path.normcase(name))

    def _list(self, folder: str) -> dict[str, int]:
        path = self.root.joinpath(*folder.split("/")) if folder else self.root
        found: dict[str, int] = {}
        try:
            with os.scandir(path) as listing:
                for entry in listing:
                    if entry.is_file(follow_symlinks=False):
                        found[os.path.normcase(entry.name)] = entry.stat(
                            follow_symlinks=False).st_size
        except (FileNotFoundError, NotADirectoryError):
            return {}
        except OSError as exc:
            raise _Unreadable(folder) from exc
        return found


def _lap(value: object) -> Lap | None:
    if value is not None and not callable(value):
        raise TypeError(f"«lap» es una función sin argumentos que dice si ceder, no {value!r}")
    return value  # type: ignore[return-value]


def _uids(value: object) -> frozenset[str] | None:
    if value is None:
        return None
    if isinstance(value, str) or not isinstance(value, Iterable):
        raise TypeError(f"las revisiones son una lista de uid, no {value!r}")
    found = frozenset(value)
    if not all(isinstance(uid, str) and uid for uid in found):
        raise TypeError(f"las revisiones son uid (textos), no {value!r}")
    return found


def _seen(value: object) -> Mapping[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError(f"lo visto de los datos es un diccionario uid → estado, no {value!r}")
    return {str(uid): str(status) for uid, status in value.items()}


def quick_steps(project: CheckProject, *, lap: Lap | None = None,
                seen: Mapping[str, str] | None = None
                ) -> Generator[float, None, tuple[SnapshotFinding, ...]]:
    """La comprobación **rápida** de las instantáneas de ``project`` (al abrirlo; véase el
    módulo): :func:`check_steps` sin las huellas de los ficheros."""
    return check_steps(project, full=False, lap=lap, seen=seen)


def check_steps(project: CheckProject, revision_uids: Iterable[str] | None = None, *,
                full: bool, lap: Lap | None = None, seen: Mapping[str, str] | None = None
                ) -> Generator[float, None, tuple[SnapshotFinding, ...]]:
    """Comprueba las instantáneas de las revisiones congeladas de ``project`` (las de
    ``revision_uids``; ``None``, todas), por versión y número: la rápida o, con ``full``, la
    entera (véase el módulo). Cede lo hecho (de 0 a 1) cuando ``lap()`` lo pide (sin ``lap``,
    de una vez) y devuelve un :class:`SnapshotFinding` por revisión comprobada, con lo que no
    coincide y la marca que tenía. ``seen``: el estado de los datos que acaba de ver quien la
    llama (la 008) y aún no está en la base (uid → ``DatasetStatus``). Sin ``gb_revision`` (un
    esquema anterior al 3 en solo lectura), nada. No escribe nada. :class:`TypeError` (al
    llamarla) con un argumento mal dado."""
    if not isinstance(full, bool):
        raise TypeError(f"«full» es verdadero o falso, no {full!r}")
    return _check(project, _uids(revision_uids), full, _lap(lap), _seen(seen))


def _check(project: CheckProject, wanted: frozenset[str] | None, full: bool, lap: Lap | None,
           seen: Mapping[str, str]) -> Generator[float, None, tuple[SnapshotFinding, ...]]:
    root = Path(project.root)
    with project.read() as conn:
        if conn.execute(_REVISIONS_TABLE).fetchone() is None:
            return ()
        rows = [_Row(str(uid), str(code), int(number), dir_, sha, at, detail)
                for uid, code, number, dir_, sha, at, detail in conn.execute(_FROZEN)]
    if wanted is not None:
        rows = [row for row in rows if row.uid in wanted]
    listings = _Listings(root)
    share = _FULL_SHARE if full else _SHARE
    found: list[_Revision] = []
    index = 0
    while index < len(rows):
        with project.read() as conn:  # una conexión por paso: nada abierto entre pasos
            while index < len(rows):
                found.append(_survey(root, rows[index], conn, listings, full))
                index += 1
                if lap is not None and lap():
                    break
        if index < len(rows):
            yield share * index / len(rows)
    if full:
        yield from _hash_all(root, found, lap, share)
    checked = [item for item in found if not item.skipped]
    findings = tuple(SnapshotFinding(item.row.uid, item.row.label, tuple(item.what),
                                     item.row.altered_at, item.row.altered_detail,
                                     tuple(dict.fromkeys(item.imported)))
                     for item in checked)
    if any(finding.imported for finding in findings):
        with project.read() as conn:
            statuses = imported_statuses(conn, findings, seen)
        findings = conclude(findings, statuses)
    return findings


def _unverified(row: _Row, full: bool) -> frozenset[str]:
    """Los ficheros que la marca de la revisión daba con otra huella (lo vio una comprobación
    entera): la rápida no mira huellas, así que no puede decir que coinciden; si siguen con su
    tamaño, siguen sin coincidir hasta que otra entera lo diga."""
    if full or not row.altered_detail:
        return frozenset()
    try:
        detail = json.loads(row.altered_detail)
    except ValueError:
        return frozenset()
    return frozenset(
        str(entry["path"]) for entry in (detail if isinstance(detail, list) else ())
        if isinstance(entry, dict) and entry.get("problem") == Problem.SHA256.value
        and "dataset_uid" not in entry and entry.get("path") != SNAPSHOT_MANIFEST)


def _survey(root: Path, row: _Row, conn: sqlite3.Connection, listings: _Listings,
            full: bool) -> _Revision:
    """Lo que se mira de una revisión sin leer sus ficheros (salvo el manifiesto)."""
    item = _Revision(row, unverified=_unverified(row, full))
    folder = _safe(row.snapshot_dir)
    try:
        body = _manifest(root, folder, row, item)
        if body is not None and folder is not None:
            for entry in _entries(body.get("files")):
                rel = _safe(entry.get("path"))
                _file(item, listings, None if rel is None else f"{folder}/{rel}",
                      rel or str(entry.get("path")), entry.get("size"), entry.get("sha256"),
                      full)
        prefix = f"{folder}/" if folder is not None else None
        for path, size, sha in conn.execute(_REFERENCED, (row.uid,)):
            rel = _safe(path)
            shown = str(path)
            if rel is not None and prefix is not None and rel.startswith(prefix):
                shown = rel[len(prefix):]
            _file(item, listings, rel, shown, size, sha, full)
        if body is not None:
            for entry in _entries(body.get("inputs")):
                for original in _entries(entry.get("originals")):
                    rel = _safe(original.get("path"))
                    _file(item, listings, rel, rel or str(original.get("path")),
                          original.get("size"), original.get("sha256"), full)
            for entry in _entries(body.get("datasets")):
                uid = entry.get("uid")
                if entry.get("location") == "project" and isinstance(uid, str) and uid:
                    name = entry.get("name")
                    item.imported.append((uid, name if isinstance(name, str) and name else uid))
    except _Unreadable:
        item.skipped = True
    return item


def _entries(value: object) -> list[dict[str, Any]]:
    return [entry for entry in value if isinstance(entry, dict)] if isinstance(value, list) else []


def _manifest(root: Path, folder: str | None, row: _Row,
              item: _Revision) -> dict[str, Any] | None:
    """El manifiesto de la revisión si tiene la huella anotada (su contenido, entonces, es el
    congelado), entero (``expand_manifest``: igual el compacto de la T33 que el de la T13); si
    falta o no la tiene, lo anota en ``item`` y ``None``."""
    if folder is None:
        item.add(Mismatch(SNAPSHOT_MANIFEST, Problem.MISSING))
        return None
    path = root.joinpath(*folder.split("/"), SNAPSHOT_MANIFEST)
    try:
        data = path.read_bytes()
    except (FileNotFoundError, NotADirectoryError):
        item.add(Mismatch(SNAPSHOT_MANIFEST, Problem.MISSING))
        return None
    except OSError as exc:
        raise _Unreadable(SNAPSHOT_MANIFEST) from exc
    if hashlib.sha256(data).hexdigest() != row.sha256:
        item.add(Mismatch(SNAPSHOT_MANIFEST, Problem.SHA256))
        return None
    try:
        body = json.loads(data)
    except ValueError:  # pragma: no cover - con su huella, es el que se escribió
        item.add(Mismatch(SNAPSHOT_MANIFEST, Problem.SHA256))
        return None
    return expand_manifest(body) if isinstance(body, dict) else None


def _file(item: _Revision, listings: _Listings, rel: str | None, shown: str, size: object,
          sha256: object, full: bool) -> None:
    """Un fichero de la revisión (``rel``, relativo al proyecto; ``None`` si su ruta no es
    válida): su existencia y su tamaño por el listado y, en la entera, su huella después."""
    if rel is None:
        item.add(Mismatch(shown, Problem.MISSING))
        return
    key = _key(rel)
    if key in item.seen:
        return
    item.seen.add(key)
    found = listings.size(rel)
    if found is None:
        item.add(Mismatch(shown, Problem.MISSING))
    elif isinstance(size, int) and not isinstance(size, bool) and found != size:
        item.add(Mismatch(shown, Problem.SIZE))
    elif full and isinstance(sha256, str) and sha256:
        item.hashes.append((rel, shown, sha256))
    elif shown in item.unverified:
        item.add(Mismatch(shown, Problem.SHA256))


_GONE = object()  # el fichero ya no está


def _hash_all(root: Path, found: list[_Revision], lap: Lap | None,
              share: float) -> Generator[float, None, None]:
    """La huella de cada fichero que falta por mirar (una vez cada uno), por trozos; lo que no
    coincide, a cada revisión que lo tiene."""
    pending: dict[str, str] = {}
    for item in found:
        if not item.skipped:
            for rel, _shown, _sha in item.hashes:
                pending.setdefault(_key(rel), rel)
    sizes = {key: _size(root, rel) for key, rel in pending.items()}
    total = max(1, sum(sizes.values()))
    done = 0
    results: dict[str, object] = {}
    for key, rel in pending.items():
        digest = hashlib.sha256()
        offset = 0
        path = root.joinpath(*rel.split("/"))
        while True:
            try:
                with path.open("rb") as stream:
                    stream.seek(offset)
                    while block := stream.read(CHUNK_BYTES):
                        digest.update(block)
                        offset += len(block)
                        if lap is not None and lap():
                            break
                    else:
                        results[key] = digest.hexdigest()
            except (FileNotFoundError, NotADirectoryError):
                results[key] = _GONE
            except OSError:
                results[key] = None  # no se puede leer: sus revisiones, sin comprobar
            if key in results:
                done += sizes[key]
                break
            yield share + (1 - share) * min(done + offset, total) / total
    for item in found:
        for rel, shown, sha in item.hashes:
            result = results.get(_key(rel))
            if result is None:
                item.skipped = True
            elif result is _GONE:
                item.add(Mismatch(shown, Problem.MISSING))
            elif result != sha:
                item.add(Mismatch(shown, Problem.SHA256))


def _size(root: Path, rel: str) -> int:
    try:
        return os.stat(root.joinpath(*rel.split("/"))).st_size
    except OSError:
        return 0


def imported_statuses(conn: sqlite3.Connection, findings: Iterable[SnapshotFinding],
                      seen: Mapping[str, str] | None = None) -> dict[str, str]:
    """El estado (``gb_dataset.status``) de lo importado que referencian ``findings``, leído en
    ``conn`` y corregido con ``seen`` (lo que acaba de ver la 008 y aún no está en la base);
    lo que no está en la base, ``missing``."""
    wanted = list(dict.fromkeys(uid for finding in findings for uid, _name in finding.imported))
    found: dict[str, str] = {}
    for start in range(0, len(wanted), _CHUNK):
        chunk = wanted[start:start + _CHUNK]
        found.update((str(uid), str(status)) for uid, status in conn.execute(
            _STATUSES.format(marks=", ".join("?" for _ in chunk)), chunk))
    for uid in wanted:
        found.setdefault(uid, DatasetStatus.MISSING.value)
    found.update((uid, status) for uid, status in _seen(seen).items() if uid in found)
    return found


def conclude(findings: Iterable[SnapshotFinding],
             statuses: Mapping[str, str]) -> tuple[SnapshotFinding, ...]:
    """``findings`` con lo importado que referencian según ``statuses`` (uid → estado de la
    008): lo que falta o está dañado (:data:`UNUSABLE`) no coincide; lo demás de cada una, como
    estaba."""
    concluded = []
    for finding in findings:
        what = [item for item in finding.what if not item.imported]
        for uid, name in finding.imported:
            status = statuses.get(uid)
            if status == DatasetStatus.MISSING.value:
                what.append(Mismatch(name, Problem.MISSING, uid))
            elif status == DatasetStatus.DAMAGED.value:
                what.append(Mismatch(name, Problem.DAMAGED, uid))
        concluded.append(replace(finding, what=tuple(what)))
    return tuple(concluded)


def full_steps(project: CheckProject, revision_uids: Iterable[str] | None = None, *,
               budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """La comprobación **entera** de las instantáneas de ``revision_uids`` (``None``, todas; la
    de antes de reproducir, plan A9): cada paso de ``budget_s`` como mucho es un ``Progress`` de
    la fase :data:`PHASE` («Comprobando las instantáneas… 40 %») y el último lleva la tupla de
    :class:`SnapshotFinding`. No escribe nada. :class:`TypeError` o :class:`ValueError` (al
    llamarla) con un argumento mal dado."""
    if isinstance(budget_s, bool) or not isinstance(budget_s, int | float):
        raise TypeError(f"el presupuesto de un paso es un número de segundos, no {budget_s!r}")
    if not budget_s > 0:
        raise ValueError(f"el presupuesto de un paso es positivo, no {budget_s!r}")
    return _full(project, _uids(revision_uids), float(budget_s))


class _Pacer:
    """Mide un paso: termina cuando lo hecho más lo más lento del paso pasaría de su parte del
    presupuesto (siempre al menos una unidad de trabajo)."""

    def __init__(self, budget_s: float) -> None:
        self.target = budget_s * WORK_FRACTION
        self.restart()

    def restart(self) -> None:
        self.start = self.last = time.perf_counter()
        self.slowest = 0.0

    def lap(self) -> bool:
        now = time.perf_counter()
        self.slowest = max(self.slowest, now - self.last)
        self.last = now
        return now - self.start + self.slowest > self.target


def _progress(done: int, result: tuple[SnapshotFinding, ...] | None = None) -> Progress:
    return Progress(PHASE, done, PROGRESS_TOTAL,
                    f"Comprobando las instantáneas… {done * 100 // PROGRESS_TOTAL} %", result)


def _full(project: CheckProject, wanted: frozenset[str] | None,
          budget: float) -> Iterator[Progress]:
    pacer = _Pacer(budget)
    yield _progress(0)
    pacer.restart()
    steps = _check(project, wanted, True, pacer.lap, {})
    done = 0
    while True:
        try:
            fraction = next(steps)
        except StopIteration as stop:
            findings: tuple[SnapshotFinding, ...] = stop.value
            break
        done = max(done, min(int(fraction * PROGRESS_TOTAL), PROGRESS_TOTAL - 1))
        yield _progress(done)
        pacer.restart()
    yield _progress(PROGRESS_TOTAL, findings)


# --- Registrar ------------------------------------------------------------------------------


def record_findings(conn: sqlite3.Connection, project: RecordProject,
                    findings: Iterable[SnapshotFinding], *, now: str,
                    seen: Mapping[str, str] | None = None) -> tuple[SnapshotFinding, ...]:
    """Registra ``findings`` en la transacción de escritura ``conn`` (la final de la
    comprobación; no la confirma), con el estado de lo importado que hay en ella (y ``seen``):
    la marca ``altered_at`` (``now`` si no estaba alterada) y ``altered_detail`` con el evento
    ``revision_altered`` en la que pasa a alterada o cambia de detalle; sin marca, con
    ``revision_restored``, en la que vuelve a coincidir; y la caché de la obsolescencia de lo
    que consumió lo congelado de las que cambian (plan A4 (3)). Devuelve lo comprobado de cada
    una con la marca que tenía antes (``SnapshotFinding.changed`` y ``text`` dicen lo que se
    registró). Una revisión que ya no está congelada no se toca."""
    chosen = tuple(findings)
    concluded = conclude(chosen, imported_statuses(conn, chosen, seen))
    uids = [finding.revision_uid for finding in concluded]
    stored: dict[str, tuple[str | None, str | None]] = {}
    for start in range(0, len(uids), _CHUNK):
        chunk = uids[start:start + _CHUNK]
        stored.update((str(uid), (at, detail)) for uid, at, detail in conn.execute(
            _MARKS.format(marks=", ".join("?" for _ in chunk)), chunk))
    result: list[SnapshotFinding] = []
    changed: list[str] = []
    for finding in concluded:
        if finding.revision_uid not in stored:
            continue
        at, detail = stored[finding.revision_uid]
        finding = replace(finding, altered_at=at, altered_detail=detail)
        result.append(finding)
        if not finding.changed:
            continue
        message = finding.text("es") or ""
        if finding.altered:
            conn.execute("UPDATE gb_revision SET altered_at = ?, altered_detail = ? WHERE uid = ?",
                         (now if at is None else at, finding.detail, finding.revision_uid))
            record_event(conn, EventKind.REVISION_ALTERED, message, session=project.session,
                         at=now, entity_kind="revision", entity_uid=finding.revision_uid,
                         data={"revision": finding.label,
                               "what": [item.as_json() for item in finding.what]})
        else:
            conn.execute("UPDATE gb_revision SET altered_at = NULL, altered_detail = NULL "
                         "WHERE uid = ?", (finding.revision_uid,))
            record_event(conn, EventKind.REVISION_RESTORED, message, session=project.session,
                         at=now, entity_kind="revision", entity_uid=finding.revision_uid,
                         data={"revision": finding.label,
                               "was": None if detail is None else json.loads(detail)})
        changed.append(finding.revision_uid)
    if changed:
        # Aquí, no al cargar: core.provenance importa este módulo (ARQ-08).
        from ..provenance.stale import refresh_region

        refresh_region(conn, now=now, revisions=changed)
    return tuple(result)

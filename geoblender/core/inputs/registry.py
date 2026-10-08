# SPDX-License-Identifier: GPL-3.0-or-later
"""Registro de las entradas (spec 008; RF-008-07, RF-008-11, RF-008-54; RF-002-19; ADR-0024 §1,
§3 y §6; ADR-0025; plan 008 §5.2.1, §5.3.1, §5.3.4 y §5.4.8).

Un módulo que importa una fuente al proyecto (plan §5.3.4, «Importar»): empieza su operación de
importación (``begin_operation``), lee la fuente y calcula su ``ContentDigest`` con su lector
y las declaraciones de la entrada (``input_declarations``), la clasifica con
:func:`classify_import` antes de escribir nada y, en la transacción que escribe lo importado,
la registra con :func:`register_input` y completa la operación.

- :func:`classify_import` (RF-008-54): con los mismos datos que una entrada **activa** (mismo
  tipo, normalizador y hash de datos) y los mismos ajustes —CRS declarados, capa, ajustes y
  cuáles son contenido, es decir, la misma huella de ajustes—, :class:`Reuse` (no se duplica:
  aviso de la spec §8; :func:`reuse_input` deja la importación cancelada con él); con otros
  ajustes, :class:`Substitute` con cada :class:`Difference` (la importación sustituye a esa
  entrada, con motivo obligatorio: RF-008-11); si no, :class:`New`. El nombre lógico, la
  entrega y la huella de los bytes no cuentan: el mismo límite reescrito por QGIS es el mismo.
- :func:`register_input` (RF-008-07): la fila de ``gb_input`` y las de sus ficheros, con su
  importación **en curso**, quién y cuándo, en la transacción de quien llama, y el evento
  ``input_registered``. Rechaza (``ProvenanceError``, sin escribir nada) una entrada sin CRS
  declarado o con «no aplica» donde hay coordenadas (nunca lo supone), la misma que una activa
  (``core.input_reused``), la de otros ajustes sin sustituirla (``previous_uid``) o sin motivo,
  la que sustituye a una descartada o ya sustituida, un nombre lógico ocupado o una tabla del
  proyecto que no está; su lector tiene que estar registrado (``core.reader_unregistered``).
  Marcar la sustituida («sustituida», sus datos importados) es de ``supersede`` (T21), en la
  misma transacción y antes, si la nueva toma su nombre.
- :func:`get`: una entrada por su uid o por el nombre lógico de la activa.
- :func:`locate_source` y :func:`resolve_source` (RF-002-19): el ancla de un fichero de una
  fuente (dentro del proyecto, junto al original o, en otro volumen, con su ruta en los datos
  de usuario del equipo) y su ruta en este equipo (``None`` si no está anotada: «no
  localizable», RF-008-13). Solo usan la ruta: el fichero no se abre.

Ningún evento lleva rutas absolutas: las rutas se guardan relativas o solo con su nombre, y el
motivo de una sustitución, sin ellas (solo el nombre del fichero). Python puro (ADR-0004): los
eventos se importan al registrarlos (``core.project`` importa ``core.provenance``).
"""

from __future__ import annotations

import ntpath
import os
import sqlite3
from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import TYPE_CHECKING, Any, Protocol

from ..content.readers import reader as content_reader
from ..hashing import canonical_json
from ..i18n import LANGUAGES
from ..ids import new_uid
from ..paths import (
    ABSOLUTE_PATH,
    Canonical,
    ExternalRef,
    canonical_path,
    make_external_ref,
    resolve_external_ref,
)
from ..provenance.messages import ProvenanceError, render
from ..timeutil import Clock, format_utc, parse_utc
from .model import (
    COORDINATE_KINDS,
    ELEVATION_KINDS,
    FILE_COLUMNS,
    HORIZONTAL,
    INACTIVE_STATUSES,
    INPUT_COLUMNS,
    VERTICAL,
    FileAnchor,
    FileRole,
    InputFileRecord,
    InputRecord,
    InputSpec,
    InputStatus,
    OriginalState,
    SourceFile,
    crs_text,
    is_not_applicable,
)

if TYPE_CHECKING:
    from ..sysinfo import SessionInfo
    from ..userdata import UserData

RUNNING = "running"
"""El estado de una operación «en curso» (``gb_operation.status``)."""
MAX_REASON_CHARS = 500
"""Largo máximo del motivo de una sustitución que se guarda (el resto se corta con «…»)."""

_INACTIVE = ", ".join(f"'{status}'" for status in INACTIVE_STATUSES)
_INPUTS = ", ".join(INPUT_COLUMNS)
_FILES = ", ".join(FILE_COLUMNS)
_LABELS: Mapping[str, Mapping[str, str]] = {
    "es": {
        "crs_h": "CRS horizontal declarado",
        "crs_v": "CRS vertical declarado",
        "layer": "capa",
        "content_keys": "ajustes que son contenido",
        "setting": "ajuste «{key}»",
    },
    "en": {
        "crs_h": "declared horizontal CRS",
        "crs_v": "declared vertical CRS",
        "layer": "layer",
        "content_keys": "settings that are content",
        "setting": "setting «{key}»",
    },
}
_SETTING = "settings."


class InputProject(Protocol):
    """Lo que el registro usa del proyecto (``core.project.Project``): su identidad y su raíz
    (las rutas de las fuentes), el reloj, la sesión (quién registra) y, para
    :func:`reuse_input`, una transacción de escritura."""

    @property
    def uid(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def root(self) -> Path: ...

    @property
    def clock(self) -> Clock: ...

    @property
    def session(self) -> SessionInfo: ...

    def write_transaction(self) -> AbstractContextManager[sqlite3.Connection]: ...


# --- Clasificación ------------------------------------------------------------------------------


def _shown(item: str, value: Any, language: str) -> str:
    if item in ("crs_h", "crs_v"):
        return crs_text(value, language)
    if value is None or value == []:
        return "—"
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(key, str) for key in value):
        return ", ".join(value)
    return canonical_json(value).decode("utf-8")


@dataclass(frozen=True)
class Difference:
    """Un ajuste de importación que cambia respecto de la entrada registrada: ``item``
    (``"crs_h"``, ``"crs_v"``, ``"layer"``, ``"content_keys"`` o ``"settings.<clave>"``), su
    valor registrado y el importado (JSON; ``None`` si falta)."""

    item: str
    registered: Any
    imported: Any

    @property
    def text(self) -> str:
        """«CRS horizontal declarado: EPSG:25830 → EPSG:23030»."""
        return self.render("es")

    def render(self, language: str = "es") -> str:
        """La diferencia en ``language`` (``"es"`` o ``"en"``)."""
        labels = _LABELS[_language(language)]
        if self.item.startswith(_SETTING):
            label = labels["setting"].format(key=self.item.removeprefix(_SETTING))
        else:
            label = labels[self.item]
        return (f"{label}: {_shown(self.item, self.registered, language)} → "
                f"{_shown(self.item, self.imported, language)}")


@dataclass(frozen=True)
class Reuse:
    """La misma entrada que ``input`` (mismo contenido y mismos ajustes): se reutiliza, con el
    aviso de la spec §8 (:attr:`text`), y no se duplica (RF-008-54)."""

    input: InputRecord

    @property
    def text(self) -> str:
        """«La entrada «Limites_v1» ya está registrada con el mismo contenido (05/10/2026).»"""
        return self.render("es")

    def render(self, language: str = "es") -> str:
        """El aviso en ``language``; la fecha de su registro, en hora local."""
        return render("core.input_reused", language=_language(language), name=self.input.name,
                      registered_on=_local_date(self.input.registered_at))


@dataclass(frozen=True)
class Substitute:
    """El mismo contenido que ``input`` con otros ajustes (``differences``): la importación
    sustituye a esa entrada, con motivo obligatorio (RF-008-54, RF-008-11)."""

    input: InputRecord
    differences: tuple[Difference, ...]

    def describe(self, language: str = "es") -> str:
        """Las diferencias, separadas por «; »."""
        return "; ".join(item.render(language) for item in self.differences)


@dataclass(frozen=True)
class New:
    """Otro contenido: una entrada nueva."""


type Classification = Reuse | Substitute | New


def _language(language: str) -> str:
    if language not in LANGUAGES:
        raise ValueError(f"el idioma «{language}» no es de Geoblender: {', '.join(LANGUAGES)}")
    return language


def _local_date(moment: str) -> str:
    """Una fecha UTC guardada, como día en hora local (``05/10/2026``)."""
    try:
        return parse_utc(moment).astimezone().strftime("%d/%m/%Y")
    except ValueError:
        return moment


def _same(first: Any, second: Any) -> bool:
    """Igualdad exacta de dos valores JSON (``1`` no es ``1.0`` ni ``true``)."""
    return canonical_json(first) == canonical_json(second)


def _differences(record: InputRecord, spec: InputSpec) -> tuple[Difference, ...]:
    found: list[Difference] = []
    pairs: tuple[tuple[str, Any, Any], ...] = (
        ("crs_h", dict(record.crs_h), None if spec.crs_h is None else dict(spec.crs_h)),
        ("crs_v", dict(record.crs_v), None if spec.crs_v is None else dict(spec.crs_v)),
        ("layer", record.layer, spec.layer),
        ("content_keys", list(record.content_settings_keys),
         list(spec.content_settings_keys)),
    )
    for item, registered, imported in pairs:
        if not _same(registered, imported):
            found.append(Difference(item, registered, imported))
    for key in sorted(set(record.settings) | set(spec.settings)):
        registered = record.settings.get(key)
        imported = spec.settings.get(key)
        if (key in record.settings) != (key in spec.settings) or not _same(registered, imported):
            found.append(Difference(_SETTING + key, registered, imported))
    return tuple(found)


def _classify(conn: sqlite3.Connection, spec: InputSpec) -> Classification:
    rows = conn.execute(
        f"SELECT uid FROM gb_input WHERE kind = ? AND normalizer = ? AND data_sha256 = ? "
        f"AND status NOT IN ({_INACTIVE}) ORDER BY fid",
        (spec.kind, spec.digest.normalizer, spec.digest.data_sha256),
    ).fetchall()
    candidates = [_require(conn, str(row[0])) for row in rows]
    found = [(record, _differences(record, spec)) for record in candidates]
    for record, differences in found:
        if not differences:
            return Reuse(record)
    if found:
        return Substitute(*found[0])
    return New()


def _check_declared(spec: InputSpec) -> None:
    """Sus CRS declarados (RF-008-07; constitución, principio 6): nunca se suponen."""
    for axis, crs in ((HORIZONTAL, spec.crs_h), (VERTICAL, spec.crs_v)):
        if crs is None:
            raise ProvenanceError("core.input_crs_missing", name=spec.name, kind=spec.kind,
                                  axis=axis)
    if spec.kind in COORDINATE_KINDS and is_not_applicable(spec.crs_h):
        raise ProvenanceError("core.input_crs_not_applicable", name=spec.name, kind=spec.kind,
                              axis=HORIZONTAL)
    if spec.kind in ELEVATION_KINDS and is_not_applicable(spec.crs_v):
        raise ProvenanceError("core.input_crs_not_applicable", name=spec.name, kind=spec.kind,
                              axis=VERTICAL)


def _spec(spec: object) -> InputSpec:
    if not isinstance(spec, InputSpec):
        raise TypeError(f"se registra un InputSpec, no {type(spec).__name__}")
    return spec


def classify_import(conn: sqlite3.Connection, spec: InputSpec) -> Classification:
    """Qué es la importación ``spec`` frente a las entradas activas del proyecto (RF-008-54):
    :class:`Reuse`, :class:`Substitute` o :class:`New` (véase el módulo). Solo lee (``conn``
    puede ser de lectura). ``ProvenanceError`` si no declara su CRS (``core.input_crs_*``)."""
    _check_declared(_spec(spec))
    return _classify(conn, spec)


# --- Lectura ------------------------------------------------------------------------------------


def _load(conn: sqlite3.Connection, uid: str) -> InputRecord | None:
    row = conn.execute(f"SELECT {_INPUTS} FROM gb_input WHERE uid = ?", (uid,)).fetchone()
    if row is None:
        return None
    files = [
        InputFileRecord.from_row(found)
        for found in conn.execute(
            f"SELECT {_FILES} FROM gb_input_file WHERE input_uid = ? ORDER BY ord", (uid,)
        )
    ]
    return InputRecord.from_row(row, files)


def _require(conn: sqlite3.Connection, uid: str) -> InputRecord:
    record = _load(conn, uid)
    if record is None:  # pragma: no cover - solo con un uid que acaba de leerse
        raise LookupError(f"no hay ninguna entrada {uid}")
    return record


def get(conn: sqlite3.Connection, key: str) -> InputRecord | None:
    """La entrada con el uid ``key`` o, si no la hay, la activa con ese nombre lógico; ``None``
    si no hay ninguna."""
    if not isinstance(key, str):
        raise TypeError(f"una entrada se busca por su uid o su nombre, no {key!r}")
    record = _load(conn, key)
    if record is not None:
        return record
    row = conn.execute(
        f"SELECT uid FROM gb_input WHERE name = ? AND status NOT IN ({_INACTIVE})", (key,)
    ).fetchone()
    return None if row is None else _load(conn, str(row[0]))


# --- Registro -----------------------------------------------------------------------------------


def _clean(text: str) -> str:
    """Un motivo como se guarda: sus rutas absolutas, solo con el nombre de su fichero
    (ADR-0006 §5), y de :data:`MAX_REASON_CHARS` como mucho."""
    shown = ABSOLUTE_PATH.sub(
        lambda match: ntpath.basename(match.group(0).rstrip("\\/")) or "…", text
    )
    if len(shown) > MAX_REASON_CHARS:
        shown = shown[: MAX_REASON_CHARS - 1] + "…"
    return shown


def _check_operation(conn: sqlite3.Connection, spec: InputSpec, operation_uid: object) -> str:
    """Su importación: tiene que existir y estar en curso (se completa después)."""
    if operation_uid is not None and not isinstance(operation_uid, str):
        raise TypeError(f"una operación se indica por su uid, no {operation_uid!r}")
    if operation_uid is None or not operation_uid.strip():
        raise ProvenanceError("core.input_operation_missing", name=spec.name)
    row = conn.execute("SELECT op_type, status FROM gb_operation WHERE uid = ?",
                       (operation_uid,)).fetchone()
    if row is None:
        raise ProvenanceError("core.input_operation_unknown", name=spec.name,
                              operation=operation_uid)
    if row[1] != RUNNING:
        raise ProvenanceError("core.input_operation_not_running", name=spec.name,
                              op_type=row[0], operation=operation_uid)
    return operation_uid


def _check_previous(conn: sqlite3.Connection, spec: InputSpec, previous_uid: object,
                    reason: object) -> tuple[InputRecord | None, str | None]:
    """La entrada que sustituye (si la hay) y el motivo, obligatorio (RF-008-11)."""
    if reason is not None and not isinstance(reason, str):
        raise TypeError(f"el motivo de una sustitución es un texto, no {reason!r}")
    if previous_uid is None:
        if reason is not None:
            raise ValueError("el motivo acompaña a una sustitución: falta la entrada sustituida "
                             "(previous_uid)")
        return None, None
    if not isinstance(previous_uid, str):
        raise TypeError(f"la entrada sustituida se indica por su uid, no {previous_uid!r}")
    previous = _load(conn, previous_uid)
    if previous is None:
        raise ProvenanceError("core.input_previous_unknown", name=spec.name,
                              previous=previous_uid)
    if previous.status is InputStatus.DISCARDED:
        raise ProvenanceError("core.input_previous_discarded", previous=previous.name)
    other = conn.execute("SELECT name FROM gb_input WHERE previous_uid = ? ORDER BY fid",
                         (previous.uid,)).fetchone()
    if other is not None:
        raise ProvenanceError("core.input_previous_replaced", previous=previous.name,
                              other=other[0], name=spec.name)
    text = None if reason is None else reason.strip()
    if not text:
        raise ProvenanceError("core.input_reason_missing", previous=previous.name,
                              name=spec.name)
    return previous, _clean(text)


def _table_changes(conn: sqlite3.Connection, spec: InputSpec) -> dict[int, str]:
    """El ``last_change`` de cada tabla del proyecto de la entrada, al registrarla."""
    found: dict[int, str] = {}
    for ord_, source in enumerate(spec.files):
        if source.anchor is not FileAnchor.PROJECT_TABLE:
            continue
        row = conn.execute("SELECT last_change FROM gpkg_contents WHERE table_name = ?",
                           (source.path,)).fetchone()
        if row is None:
            raise ProvenanceError("core.input_table_missing", table=source.path,
                                  name=spec.name)
        found[ord_] = row[0]
    return found


def _record(conn: sqlite3.Connection, project: InputProject, kind: str, input_uid: str,
            message: str, data: Mapping[str, object], at: str) -> None:
    """Su evento en ``gb_event`` (``kind``: el nombre de ``core.project.events.EventKind``).
    Se importa aquí: ``core.project`` importa ``core.provenance``."""
    from ..project.events import EventKind, record_event

    record_event(conn, EventKind[kind], message, session=project.session, at=at,
                 entity_kind="input", entity_uid=input_uid, data=dict(data))


def _plain(crs: Mapping[str, Any] | None) -> dict[str, Any] | None:
    return None if crs is None else dict(crs)


def register_input(
    conn: sqlite3.Connection,
    project: InputProject,
    spec: InputSpec,
    *,
    operation_uid: str | None,
    previous_uid: str | None = None,
    reason: str | None = None,
) -> InputRecord:
    """Registra la entrada ``spec`` que importa la operación en curso ``operation_uid``, en la
    transacción de escritura ``conn`` de quien llama (la que escribe lo importado; no la
    confirma), y la devuelve (RF-008-07): su fila de ``gb_input`` («vigente», original «no
    aplica» hasta que se guarde, T22), la de cada fichero (con el ``last_change`` de una tabla
    del proyecto) y el evento ``input_registered``. ``previous_uid`` y ``reason``: la entrada
    que sustituye y el motivo, obligatorio (RF-008-11, RF-008-54).

    Rechazos, sin escribir nada: ``ProvenanceError`` (``core.input_crs_missing``/
    ``_not_applicable``, ``core.input_operation_missing``/``_unknown``/``_not_running``,
    ``core.input_previous_unknown``/``_discarded``/``_replaced``,
    ``core.input_reason_missing``, ``core.input_reused``,
    ``core.input_substitution_required``, ``core.input_name_taken``,
    ``core.input_table_missing``), ``ValidationError`` (``core.reader_unregistered``) y
    ``TypeError``/``ValueError`` con un argumento mal formado, un lector que no da su tipo o
    fuera de una transacción."""
    _spec(spec)
    if not isinstance(conn, sqlite3.Connection):
        raise TypeError(f"register_input recibe la conexión de una transacción de escritura, no "
                        f"{conn!r}")
    if not conn.in_transaction:
        raise ValueError("register_input se llama dentro de la transacción de escritura que "
                         "guarda lo importado (Project.write_transaction)")
    _check_declared(spec)
    found_reader = content_reader(spec.reader)
    if spec.kind not in found_reader.kinds:
        raise ValueError(f"el lector «{spec.reader}» da {list(found_reader.kinds)}, no "
                         f"«{spec.kind}»")
    operation = _check_operation(conn, spec, operation_uid)
    previous, text = _check_previous(conn, spec, previous_uid, reason)
    classified = _classify(conn, spec)
    if isinstance(classified, Reuse):
        raise ProvenanceError("core.input_reused", name=classified.input.name,
                              registered_on=_local_date(classified.input.registered_at))
    if isinstance(classified, Substitute) and (previous is None
                                               or previous.uid != classified.input.uid):
        raise ProvenanceError("core.input_substitution_required", name=spec.name,
                              existing=classified.input.name,
                              differences=classified.describe())
    if conn.execute(f"SELECT 1 FROM gb_input WHERE name = ? AND status NOT IN ({_INACTIVE})",
                    (spec.name,)).fetchone():
        raise ProvenanceError("core.input_name_taken", name=spec.name)
    changes = _table_changes(conn, spec)
    now = format_utc(project.clock.now())
    uid = new_uid()
    row: dict[str, object] = {
        "uid": uid,
        "name": spec.name,
        "kind": spec.kind,
        "module": spec.module,
        "reader": spec.reader,
        "normalizer": spec.digest.normalizer,
        "layer": spec.layer,
        "crs_h": canonical_json(_plain(spec.crs_h)).decode("utf-8"),
        "crs_v": canonical_json(_plain(spec.crs_v)).decode("utf-8"),
        "settings": spec.settings_json,
        "settings_sha256": spec.settings_sha256,
        "bytes_sha256": spec.bytes_sha256,
        "data_sha256": spec.digest.data_sha256,
        "content_sha256": spec.digest.content_sha256,
        "received_at": spec.received_at,
        "received_from": spec.received_from,
        "registered_by": project.session.user_host,
        "registered_at": now,
        "operation_uid": operation,
        "previous_uid": None if previous is None else previous.uid,
        "status": str(InputStatus.CURRENT),
        "original": str(OriginalState.NOT_APPLICABLE),
        "created_at": now,
        "modified_at": now,
    }
    conn.execute(
        f"INSERT INTO gb_input ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",
        tuple(row.values()),
    )
    conn.executemany(
        "INSERT INTO gb_input_file (input_uid, ord, role, anchor, path, ref_uid, size, "
        "mtime_ns, last_change, sha256) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(uid, ord_, str(source.role), str(source.anchor), source.path, source.ref_uid,
          printed.size, printed.mtime_ns, changes.get(ord_), printed.sha256)
         for ord_, (source, printed) in enumerate(zip(spec.files, spec.file_prints,
                                                      strict=True))],
    )
    if previous is None:
        message = f"Entrada «{spec.name}» registrada ({spec.kind}, {spec.reader})."
    else:
        message = f"Entrada «{spec.name}» registrada: sustituye a «{previous.name}» ({text})."
    _record(conn, project, "INPUT_REGISTERED", uid, message, {
        "name": spec.name,
        "kind": spec.kind,
        "module": spec.module,
        "reader": spec.reader,
        "normalizer": spec.digest.normalizer,
        "layer": spec.layer,
        "crs_h": _plain(spec.crs_h),
        "crs_v": _plain(spec.crs_v),
        "data_sha256": spec.digest.data_sha256,
        "content_sha256": spec.digest.content_sha256,
        "operation_uid": operation,
        "previous_uid": None if previous is None else previous.uid,
        "reason": text,
        "received_at": spec.received_at,
        "received_from": spec.received_from,
        "files": [{"anchor": str(source.anchor), "path": source.path, "role": str(source.role)}
                  for source in spec.files],
    }, now)
    return _require(conn, uid)


def reuse_input(project: InputProject, handle: Any, reuse: Reuse) -> None:
    """La fuente ya estaba registrada con el mismo contenido y los mismos ajustes (``reuse``,
    de :func:`classify_import`): deja la importación ``handle`` (``OperationHandle`` en curso)
    «cancelada» con el aviso de la spec §8 como motivo, sin escribir nada más de ella
    (``handle.cancel``), y anota después el evento ``input_reused`` (RF-008-54; plan §5.4.8).
    Los rechazos de ``cancel`` (solo lectura, ya terminada) pasan tal cual, sin evento."""
    if not isinstance(reuse, Reuse):
        raise TypeError(f"se reutiliza lo que clasificó classify_import como Reuse, no "
                        f"{reuse!r}")
    text = reuse.text
    handle.cancel(text)
    with project.write_transaction() as conn:
        _record(conn, project, "INPUT_REUSED", reuse.input.uid, text, {
            "name": reuse.input.name,
            "operation_uid": handle.uid,
            "op_type": handle.op_type,
            "content_sha256": reuse.input.content_sha256,
        }, format_utc(project.clock.now()))


# --- Ubicación de las fuentes (RF-002-19) -------------------------------------------------------


def _inside(full: Path, root: Path) -> str | None:
    """La ruta de ``full`` relativa a ``root`` con «/» si está dentro; si no, ``None``."""
    try:
        relative = os.path.relpath(full, root)
    except ValueError:  # otra unidad
        return None
    parts = PurePath(relative).parts
    if not parts or relative == os.curdir or parts[0] == os.pardir:
        return None
    return PurePath(relative).as_posix()


def locate_source(
    path: str | os.PathLike[str],
    project: InputProject,
    userdata: UserData,
    *,
    role: FileRole | str = FileRole.MAIN,
    canonical: Canonical = canonical_path,
) -> SourceFile:
    """El ancla del fichero ``path`` de una fuente (RF-002-19): dentro del proyecto, relativo a
    su raíz (``project``); en el volumen del proyecto original, relativo a la raíz del original
    (``original``); en otro volumen, solo su nombre, con su ruta completa anotada en
    ``userdata`` (``external``). Solo usa la ruta: el fichero no se abre ni cambia."""
    chosen = FileRole(role)
    full = canonical(Path(path))
    inside = _inside(full, canonical(Path(project.root)))
    if inside is not None:
        return SourceFile(inside, chosen, FileAnchor.PROJECT)
    ref = make_external_ref(Path(path), project, userdata, canonical=canonical)
    if ref.anchor == "project":
        return SourceFile(ref.path, chosen, FileAnchor.ORIGINAL)
    return SourceFile(ref.path, chosen, FileAnchor.EXTERNAL, ref_uid=ref.ref_uid)


def resolve_source(
    source: SourceFile | InputFileRecord,
    project: InputProject,
    userdata: UserData,
    *,
    canonical: Canonical = canonical_path,
) -> Path | None:
    """La ruta del fichero ``source`` en este equipo, o ``None`` si es de otro volumen y aquí
    no está anotada («no localizable», RF-008-13). Una tabla del proyecto no es un fichero
    (``ValueError``): se sigue por su ``last_change``."""
    anchor = FileAnchor(source.anchor)
    if anchor is FileAnchor.PROJECT_TABLE:
        raise ValueError(f"«{source.path}» es una tabla del proyecto, no un fichero: se "
                         "comprueba por su last_change")
    if anchor is FileAnchor.PROJECT:
        return Path(os.path.normpath(canonical(Path(project.root)) / Path(source.path)))
    if anchor is FileAnchor.ORIGINAL:
        return resolve_external_ref(ExternalRef("project", source.path, ""), project, userdata,
                                    canonical=canonical)
    if source.ref_uid is None:
        return None
    return resolve_external_ref(ExternalRef("external", source.path, source.ref_uid), project,
                                userdata, canonical=canonical)

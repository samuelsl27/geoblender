# SPDX-License-Identifier: GPL-3.0-or-later
"""Registro de los datos del proyecto (spec 008; RF-008-17, RF-008-52; ADR-0024 §6;
ADR-0025 §4 y §6; plan 008 §5.2.1, §5.3.1, §5.4.4 y §5.4.8).

Cada dato que escribe una operación queda en ``gb_dataset`` con la operación **en curso** que
escribió su contenido actual: sin ella no se registra (RF-008-17, D-2). Lo llama
``OperationHandle.complete`` (T17) en la misma transacción que escribe los resultados.

- :func:`register_dataset`: un dato nuevo. Su primer contenido deja su fila en
  ``gb_dataset_change`` (``from_sha256`` nulo) y su salida en ``gb_operation_io`` (con su
  papel).
- :func:`set_content`: un contenido nuevo de un dato vivo, que vuelve a estar vigente (uno
  que faltaba o estaba bloqueado, recalculado): su fila de cambio (si el hash cambia) con el
  detalle del módulo y su salida. Lo importado (``immutable``) no admite contenido nuevo
  (RF-008-52).
- :func:`note_content`: el contenido que una operación de **versión** escribió en la tabla de un dato
  **del proyecto** sin poder declararlo como salida (el estilo de QGIS de una capa de versión,
  spec 015, T22): su hash y su seguimiento al día, para que no parezca una edición externa.
- :func:`get`, :func:`successor`, :func:`supersede` y :func:`set_status`: buscar un dato por
  su uid o por el nombre de su dato vivo en su ámbito (el proyecto o, con la spec 009, una
  versión: :func:`register_dataset` anota la de un dato de versión), el sucesor vivo de uno
  sustituido, sustituirlo y
  cambiar su estado. Las dos últimas ponen al día en la misma transacción la caché de la
  obsolescencia por región de lo que lo consumió (``core.provenance.stale``, RF-008-24).
- :func:`content_digest` y :func:`spec_of`: el hash del contenido que tiene ahora un dato
  (cancelable entre trozos) y la declaración de un contenido nuevo con su misma identidad, para
  comprobar los datos del proyecto (``core.datasets.external``).

**Hash** (ADR-0024 §6). Cada dato se hashea siempre con **su** lector y **su** normalizador,
los que tenía al registrarse (los nuevos, los que trae su :class:`~.model.DatasetSpec`), y sin
declaraciones (:data:`~.model.DATASET_DECLARATIONS`). El hash que da el módulo se guarda tal
cual si es de esas versiones (y se comprueba que es el de un dato: su tipo y sin
declaraciones); si es de otras, o no lo da, lo calcula el registro: una tabla de
``project.gpkg``, con ``core.gpkg_layer`` en la conexión de la transacción (ve lo que aún no
se ha confirmado); un fichero, con su lector registrado (``core.content.reader``). Un modelo
de ``blocks.duckdb`` no se lee aquí: su módulo da su hash.

**Seguimiento** (ADR-0025 §6; T10). Tras la escritura, en la misma transacción: una tabla de
``project.gpkg`` queda con sus disparadores de ``last_change`` (``track_table``) y se anotan
``gpkg_contents.last_change`` y la huella de su SQL; un fichero, su tamaño y su fecha; lo de
``exports`` y ``duckdb``, nada (``tracked = 0``). Lo importado de una tabla queda además
protegido (``protect_immutable``, con su selector fijo si comparte la tabla) con el nombre de
su entrada.

**Sucesor** (plan 008 §5.4.4 y §5.4.8). Lo importado de una entrada actualizada queda
«sustituido» con su nombre y su contenido (el nombre lo puede tomar lo importado de la
entrada nueva: un nombre, un dato vivo). Su sucesor es el anotado (``superseded_by``) o, si no
lo hay, se resuelve **por papel**: la salida con su mismo papel de la operación que sustituye
a la que lo escribió (``gb_operation.superseded_by`` o ``supersedes_uid``), hasta llegar a un
dato vivo.

Todo se comprueba **antes** de escribir: un rechazo es un ``ValidationError``
(``core.dataset_*``) que solo deshace la transacción, nunca una restricción de SQLite, que
dejaría el proyecto en solo lectura. Las funciones que escriben reciben la conexión de una
transacción de escritura (``Project.write_transaction()``) y no la confirman. Python puro
(ADR-0004): al importarse no importa ``core.provenance``, que importa este módulo; su caché,
solo al ponerla al día.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Protocol

from ..content import builtin
from ..content.encoder import NORMALIZER, NORMALIZERS, ContentDigest, content_sha256
from ..content.readers import ReadCancelled, read_steps, reader
from ..errors import ValidationError
from ..hashing import canonical_json
from ..ids import new_uid
from ..timeutil import Clock, format_utc
from . import tracking
from .model import (
    DATASET_DECLARATIONS,
    FINAL_STATUSES,
    LIVE_STATUSES,
    RECORD_COLUMNS,
    DatasetRecord,
    DatasetSpec,
    DatasetStatus,
    Store,
)

RUNNING = "running"
"""El estado de una operación «en curso» (``gb_operation.status``)."""
SUCCESSOR_OPERATION_STATUSES: tuple[str, ...] = (RUNNING, "done")
"""Los estados de la operación que sustituye a otra en los que cuenta para el sucesor (una
reimportación cancelada o fallida no sustituye nada)."""
DIGEST_ROLE = "content"
"""El papel con que :func:`content_digest` declara el dato que hashea (no se escribe)."""

_COLUMNS = ", ".join(RECORD_COLUMNS)
_LIVE = ", ".join(f"'{status}'" for status in LIVE_STATUSES)
_OBJ = "Dato del proyecto"
_IDENTITY: tuple[tuple[str, str], ...] = (
    ("name", "nombre"),
    ("module", "módulo"),
    ("kind", "tipo"),
    ("store", "almacén"),
    ("locator", "ubicación"),
    ("selector_json", "selector"),
    ("input_uid", "entrada"),
    ("immutable", "inmutable"),
)
"""Lo que no cambia de un dato (su identidad y su ubicación) y cómo se nombra al rechazar."""


class DatasetProject(Protocol):
    """Lo que el registro usa del proyecto (``core.project.Project``): su raíz (los ficheros
    de los datos), su base (``project.gpkg``) y su reloj."""

    @property
    def root(self) -> Path: ...

    @property
    def database_path(self) -> Path: ...

    @property
    def clock(self) -> Clock: ...


def _error(code: str, name: str, reason: str, field: str, value: object) -> ValidationError:
    return ValidationError(code, reason, obj=f"{_OBJ} «{name}»", field=field, value=value)


# --- Lectura --------------------------------------------------------------------------------


def _load(conn: sqlite3.Connection, uid: str) -> DatasetRecord | None:
    row = conn.execute(f"SELECT {_COLUMNS} FROM gb_dataset WHERE uid = ?", (uid,)).fetchone()
    return None if row is None else DatasetRecord.from_row(row)


def get(conn: sqlite3.Connection, key: str, *, version_uid: str = "") -> DatasetRecord | None:
    """El dato con el uid ``key`` (de cualquier ámbito) o, si no lo hay, el dato vivo con ese
    nombre en su ámbito: el del proyecto o, con ``version_uid``, el de esa versión (spec 009:
    dos versiones, y una versión y el proyecto, pueden tener un dato con el mismo nombre);
    ``None`` si no hay ninguno. En un proyecto del esquema 2 sin migrar (en solo lectura), todo
    es del proyecto."""
    if not isinstance(key, str):
        raise TypeError(f"un dato se busca por su uid o su nombre, no {key!r}")
    if not isinstance(version_uid, str):
        raise TypeError(f"la versión de un dato es su uid ('' del proyecto), no {version_uid!r}")
    record = _load(conn, key)
    if record is not None:
        return record
    try:
        row = conn.execute(
            f"SELECT {_COLUMNS} FROM gb_dataset WHERE version_uid = ? AND name = ? "
            f"AND status IN ({_LIVE})",
            (version_uid, key),
        ).fetchone()
    except sqlite3.OperationalError as exc:  # el esquema 2: sin versiones
        if version_uid or "version_uid" not in str(exc):
            raise
        row = conn.execute(
            f"SELECT {_COLUMNS} FROM gb_dataset WHERE name = ? AND status IN ({_LIVE})", (key,)
        ).fetchone()
    return None if row is None else DatasetRecord.from_row(row)


def _require(conn: sqlite3.Connection, uid: object, name: str = "?") -> DatasetRecord:
    if not isinstance(uid, str):
        raise TypeError(f"un dato se indica por su uid, no {uid!r}")
    record = _load(conn, uid)
    if record is None:
        raise _error("core.dataset_unknown", name,
                     "no hay ningún dato con ese identificador en el proyecto", "uid", uid)
    return record


def _role_successor(conn: sqlite3.Connection, record: DatasetRecord) -> str | None:
    """El uid de la salida con el mismo papel de la operación que sustituye a la que
    escribió ``record`` (``None`` si no la hay)."""
    roles = [
        row[0]
        for row in conn.execute(
            "SELECT role FROM gb_operation_io WHERE operation_uid = ? AND direction = 'out' "
            "AND item_kind = 'dataset' AND item_uid = ?",
            (record.operation_uid, record.uid),
        )
    ]
    if not roles:
        return None
    row = conn.execute(
        "SELECT superseded_by FROM gb_operation WHERE uid = ?", (record.operation_uid,)
    ).fetchone()
    if row is not None and row[0] is not None:
        operations = [row[0]]
    else:
        marks = ", ".join("?" for _ in SUCCESSOR_OPERATION_STATUSES)
        operations = [
            found[0]
            for found in conn.execute(
                f"SELECT uid FROM gb_operation WHERE supersedes_uid = ? AND status IN ({marks})",
                (record.operation_uid, *SUCCESSOR_OPERATION_STATUSES),
            )
        ]
    if len(operations) > 1:
        raise _error("core.dataset_successor_ambiguous", record.name,
                     f"la sustituyen varias operaciones ({', '.join(sorted(operations))}): no se "
                     "sabe cuál es su sucesor", "operación", record.operation_uid)
    if not operations:
        return None
    marks = ", ".join("?" for _ in roles)
    found = sorted({
        row[0]
        for row in conn.execute(
            "SELECT item_uid FROM gb_operation_io WHERE operation_uid = ? AND direction = 'out' "
            f"AND item_kind = 'dataset' AND role IN ({marks}) AND item_uid <> ?",
            (operations[0], *roles, record.uid),
        )
    })
    if len(found) > 1:
        raise _error("core.dataset_successor_ambiguous", record.name,
                     f"la operación que la sustituye escribió varios datos con su papel "
                     f"({', '.join(roles)})", "operación", operations[0])
    return found[0] if found else None


def successor(conn: sqlite3.Connection, uid: str) -> DatasetRecord | None:
    """El dato vivo que sigue a ``uid``: él mismo si está vivo; si está sustituido, el que
    lo sustituye (anotado o por papel), y así hasta uno vivo; ``None`` si está descartado o
    no hay sucesor. ``ValidationError`` (``core.dataset_unknown``) si no existe."""
    record: DatasetRecord | None = _require(conn, uid)
    seen: set[str] = set()
    while record is not None and record.uid not in seen:
        if record.live:
            return record
        if record.status is DatasetStatus.DISCARDED:
            return None
        seen.add(record.uid)
        following = record.superseded_by or _role_successor(conn, record)
        record = None if following is None else _load(conn, following)
    return None


# --- Comprobaciones -------------------------------------------------------------------------


def _check_operation(conn: sqlite3.Connection, name: str, operation_uid: object) -> str:
    """La operación que escribe el dato: tiene que existir y estar en curso (RF-008-17)."""
    if operation_uid is not None and not isinstance(operation_uid, str):
        raise TypeError(f"una operación se indica por su uid, no {operation_uid!r}")
    if operation_uid is None or not operation_uid.strip():
        raise _error(
            "core.dataset_operation_missing", name,
            "un dato del proyecto se registra con la operación que escribió su contenido: sin "
            "procedencia no se admite (RF-008-17)",
            "operación", operation_uid,
        )
    row = conn.execute(
        "SELECT status FROM gb_operation WHERE uid = ?", (operation_uid,)
    ).fetchone()
    if row is None:
        raise _error("core.dataset_operation_unknown", name,
                     "no hay ninguna operación con ese identificador en el proyecto",
                     "operación", operation_uid)
    if row[0] != RUNNING:
        raise _error(
            "core.dataset_operation_finished", name,
            f"la operación ya no está en curso (estado «{row[0]}»): un dato se registra al "
            "completar su operación, antes de darla por terminada",
            "operación", operation_uid,
        )
    return operation_uid


def _check_new(conn: sqlite3.Connection, spec: DatasetSpec, operation_uid: str,
               version_uid: str) -> str | None:
    """Lo que se comprueba de un dato nuevo antes de escribir; devuelve el nombre de su
    entrada si es lo importado (para su protección)."""
    if conn.execute(
        f"SELECT 1 FROM gb_dataset WHERE version_uid = ? AND name = ? AND status IN ({_LIVE})",
        (version_uid, spec.name),
    ).fetchone():
        raise _error("core.dataset_name_taken", spec.name,
                     "ya hay otro dato vivo (ni sustituido ni descartado) con ese nombre",
                     "nombre", spec.name)
    if conn.execute(
        "SELECT 1 FROM gb_dataset WHERE store = ? AND locator = ? AND selector = ?",
        (str(spec.store), spec.locator, spec.selector_json),
    ).fetchone():
        raise _error("core.dataset_location_taken", spec.name,
                     "esa ubicación (almacén, tabla o ruta y selector) ya es de otro dato, "
                     "también si está sustituido o descartado: no se reutiliza",
                     "ubicación", spec.locator)
    input_name = None
    if spec.input_uid is not None:
        row = conn.execute("SELECT name FROM gb_input WHERE uid = ?",
                           (spec.input_uid,)).fetchone()
        if row is None:
            raise _error("core.dataset_input_unknown", spec.name,
                         "no hay ninguna entrada con ese identificador: lo importado se "
                         "registra después de su entrada", "entrada", spec.input_uid)
        input_name = str(row[0])
    return input_name


def _check_output(conn: sqlite3.Connection, spec: DatasetSpec, operation_uid: str,
                  uid: str) -> None:
    if conn.execute(
        "SELECT 1 FROM gb_operation_io WHERE operation_uid = ? AND direction = 'out' "
        "AND item_kind = 'dataset' AND item_uid = ? AND role = ?",
        (operation_uid, uid, spec.role),
    ).fetchone():
        raise _error("core.dataset_written_twice", spec.name,
                     f"la operación ya escribió este dato con el papel «{spec.role}»",
                     "operación", operation_uid)


def _check_digest(spec: DatasetSpec, digest: ContentDigest) -> None:
    """El hash que da el módulo tiene que ser el de un dato de su tipo, sin declaraciones."""
    expected = content_sha256(spec.kind, DATASET_DECLARATIONS, digest.data_sha256,
                              normalizer=digest.normalizer)
    if digest.content_sha256 != expected:
        raise _error(
            "core.dataset_content_declared", spec.name,
            f"su hash de contenido no es el de un dato de tipo «{spec.kind}» sin declaraciones "
            "(el CRS de un dato va en sus datos): calcúlelo con su lector",
            "hash de contenido", digest.content_sha256,
        )


def _check_normalizer(name: str, normalizer: str) -> None:
    if normalizer not in NORMALIZERS:
        raise _error("core.dataset_normalizer_unknown", name,
                     f"este Geoblender no sabe calcular ese normalizador (sabe "
                     f"{', '.join(sorted(NORMALIZERS))}): actualice Geoblender",
                     "normalizador", normalizer)


# --- Hash y seguimiento ---------------------------------------------------------------------


def _advance(steps: Iterator[float], reader_id: str,
             cancelled: Callable[[], bool] | None) -> None:
    """Lleva hasta el final los pasos de un lector; ``cancelled()``, antes de empezar y tras
    cada trozo: si es verdadero, ``ReadCancelled`` (el lector se cierra)."""
    done = 0.0
    try:
        if cancelled is not None and cancelled():
            raise ReadCancelled(reader_id, done)
        for done in steps:
            if cancelled is not None and cancelled():
                raise ReadCancelled(reader_id, done)
    finally:
        close = getattr(steps, "close", None)
        if close is not None:
            close()


def _computed(conn: sqlite3.Connection, project: DatasetProject, spec: DatasetSpec,
              reader_id: str, normalizer: str, *,
              cancelled: Callable[[], bool] | None = None) -> ContentDigest:
    """El hash del dato, leído con ``reader_id`` y ``normalizer``, sin declaraciones."""
    _check_normalizer(spec.name, normalizer)
    if spec.store is Store.GPKG:
        if reader_id != builtin.GPKG_LAYER.id:
            raise _error("core.dataset_reader_store", spec.name,
                         f"una tabla del proyecto se lee en su transacción con "
                         f"«{builtin.GPKG_LAYER.id}», no con otro lector", "lector", reader_id)
        request = builtin.GPKG_LAYER.request(
            spec.kind, DATASET_DECLARATIONS, {"main": project.database_path},
            {"layer": spec.locator, "selector": spec.selector}, normalizer=normalizer,
        )
        _advance(builtin.layer_steps(conn, request), reader_id, cancelled)
        return request.hasher.digest()
    if spec.store is Store.DUCKDB:
        raise _error("core.dataset_content_missing", spec.name,
                     "un modelo de blocks.duckdb no se lee aquí: su módulo da su hash "
                     "(ContentDigest) con su lector", "hash de contenido", None)
    path = _file(project, spec)
    content_reader = reader(reader_id)
    request = content_reader.request(spec.kind, DATASET_DECLARATIONS, {"main": path},
                                     normalizer=normalizer)
    _advance(read_steps(content_reader, request), reader_id, cancelled)
    return request.hasher.digest()


def _file(project: DatasetProject, spec: DatasetSpec) -> Path:
    path = Path(project.root, *spec.locator.split("/"))
    if not path.is_file():
        raise _error("core.dataset_file_missing", spec.name,
                     "el fichero no está en el proyecto: un dato se registra después de "
                     "escribirlo", "ubicación", spec.locator)
    return path


def spec_of(record: DatasetRecord, *, role: str,
            content: ContentDigest | None = None) -> DatasetSpec:
    """La declaración de un contenido nuevo del dato ``record``, con su misma identidad y su
    ubicación (lo que pide :func:`set_content`), su papel ``role`` en la operación que lo
    escribe y, si se da, su hash ``content`` (con su lector y su normalizador): la de una
    edición externa o la de dar por buena una operación."""
    return DatasetSpec(
        record.name, record.module, record.kind, record.store, record.locator,
        reader=record.reader, role=role, selector=record.selector, content=content,
        crs_epsg=record.crs_epsg, input_uid=record.input_uid, immutable=record.immutable,
        qgis_editable=record.qgis_editable,
    )


def content_digest(conn: sqlite3.Connection, project: DatasetProject, record: DatasetRecord, *,
                   cancelled: Callable[[], bool] | None = None) -> ContentDigest:
    """El hash del contenido que tiene ahora el dato ``record``, con **su** lector y **su**
    normalizador y sin declaraciones (ADR-0024 §6): una tabla de ``project.gpkg``, en la
    conexión ``conn`` (ve lo no confirmado de su transacción); un fichero, con su lector
    registrado. ``cancelled()`` se consulta antes de empezar y tras cada trozo: si es
    verdadero, ``ReadCancelled`` (``core.content.readers``). ``ValidationError`` si no se
    puede leer (``core.dataset_*``, ``core.content_*``, ``core.reader_unregistered``); los
    ``OSError`` y ``sqlite3.Error`` de la lectura pasan tal cual. No escribe nada."""
    if not isinstance(record, DatasetRecord):
        raise TypeError(f"se hashea un DatasetRecord, no {type(record).__name__}")
    spec = spec_of(record, role=DIGEST_ROLE)
    return _computed(conn, project, spec, record.reader, record.normalizer, cancelled=cancelled)


def _content(conn: sqlite3.Connection, project: DatasetProject, spec: DatasetSpec,
             reader_id: str, normalizer: str) -> str:
    """El hash de contenido del dato con su lector y su normalizador (ADR-0024 §6): el del
    módulo si es de esas versiones; si no, el calculado aquí."""
    digest = spec.content
    if digest is not None and digest.reader == reader_id and digest.normalizer == normalizer:
        _check_digest(spec, digest)
        return digest.content_sha256
    return _computed(conn, project, spec, reader_id, normalizer).content_sha256


def _tracking(conn: sqlite3.Connection, project: DatasetProject,
              spec: DatasetSpec) -> dict[str, object]:
    """Lo que se anota para seguir el dato tras escribirlo (ADR-0025 §6)."""
    if not spec.tracked:
        return {}
    if spec.store is Store.GPKG:
        state = tracking.table_states(conn, [spec.locator])[spec.locator]
        return {"tracked_last_change": state.last_change,
                "tracked_schema_sha256": state.schema_sha256}
    stat = os.stat(_file(project, spec))
    return {"tracked_size": stat.st_size, "tracked_mtime_ns": stat.st_mtime_ns}


def _track(conn: sqlite3.Connection, spec: DatasetSpec) -> None:
    """Pone (o repone) en la tabla de un dato los disparadores de ``last_change``, antes de
    leerla: rechaza lo que no es una tabla de datos (``core.dataset_table_*``)."""
    if spec.store is Store.GPKG:
        tracking.track_table(conn, spec.locator)


def _record_change(conn: sqlite3.Connection, uid: str, before: str | None, after: str,
                   spec: DatasetSpec, operation_uid: str, now: str) -> None:
    if before != after:
        conn.execute(
            "INSERT INTO gb_dataset_change (dataset_uid, from_sha256, to_sha256, "
            "operation_uid, detail, at) VALUES (?, ?, ?, ?, ?, ?)",
            (uid, before, after, operation_uid, spec.detail_json, now),
        )
    conn.execute(
        "INSERT INTO gb_operation_io (operation_uid, direction, item_kind, item_uid, "
        "content_sha256, role) VALUES (?, 'out', 'dataset', ?, ?, ?)",
        (operation_uid, uid, after, spec.role),
    )


# --- Escritura ------------------------------------------------------------------------------


def register_dataset(conn: sqlite3.Connection, project: DatasetProject, spec: DatasetSpec, *,
                     operation_uid: str | None, version_uid: str = "") -> DatasetRecord:
    """Registra el dato nuevo ``spec`` que acaba de escribir la operación en curso
    ``operation_uid`` (RF-008-17): su hash con el lector de ``spec`` y el normalizador de su
    hash (o el vigente), su primer cambio, su salida con su papel y su seguimiento; si es lo
    importado, la protección de su tabla (RF-008-52). ``version_uid``: la versión de la que es
    (la salida de una operación de versión, spec 009, RF-009-05); ``''``, del proyecto.

    ``ValidationError`` (``core.dataset_*``, ``core.content_*``, ``core.reader_unregistered``)
    sin escribir nada si falta la operación o no está en curso, si su nombre ya es de un
    dato vivo de su ámbito, si su ubicación ya es de otro dato, si su entrada no existe, si su
    tabla no es de datos o si su hash no se puede calcular o no es el de un dato."""
    if not isinstance(spec, DatasetSpec):
        raise TypeError(f"se registra un DatasetSpec, no {type(spec).__name__}")
    if not isinstance(version_uid, str):
        raise TypeError(f"la versión de un dato es su uid ('' del proyecto), no {version_uid!r}")
    operation = _check_operation(conn, spec.name, operation_uid)
    input_name = _check_new(conn, spec, operation, version_uid)
    normalizer = NORMALIZER if spec.content is None else spec.content.normalizer
    _check_normalizer(spec.name, normalizer)
    _track(conn, spec)
    sha = _content(conn, project, spec, spec.reader, normalizer)
    if spec.immutable and spec.store is Store.GPKG and input_name is not None:
        tracking.protect_immutable(conn, spec.locator, spec.selector, input_name=input_name)
    now = format_utc(project.clock.now())
    uid = new_uid()
    row: dict[str, object] = {
        "uid": uid,
        "name": spec.name,
        "module": spec.module,
        "kind": spec.kind,
        "store": str(spec.store),
        "locator": spec.locator,
        "selector": spec.selector_json,
        "reader": spec.reader,
        "normalizer": normalizer,
        "content_sha256": sha,
        "crs_epsg": spec.crs_epsg,
        "operation_uid": operation,
        "input_uid": spec.input_uid,
        "immutable": int(spec.immutable),
        "qgis_editable": int(spec.qgis_editable),
        "tracked": int(spec.tracked),
        "status": str(DatasetStatus.CURRENT),
        "checked_at": now if spec.tracked else None,
        "created_at": now,
        "modified_at": now,
        **_tracking(conn, project, spec),
    }
    if version_uid:
        row["version_uid"] = version_uid
    conn.execute(
        f"INSERT INTO gb_dataset ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",
        tuple(row.values()),
    )
    _record_change(conn, uid, None, sha, spec, operation, now)
    return _require(conn, uid, spec.name)


def set_content(conn: sqlite3.Connection, project: DatasetProject, uid: str, spec: DatasetSpec,
                *, operation_uid: str | None) -> DatasetRecord:
    """Registra el contenido nuevo del dato ``uid`` que acaba de escribir la operación en
    curso ``operation_uid`` (``spec``, con la misma identidad): su hash con el lector y el
    normalizador **del dato** (ADR-0024 §6), su fila de cambio con el detalle del módulo si
    el contenido cambia, su salida con su papel, su seguimiento, su CRS y si es editable; el
    dato vuelve a estar vigente (uno que faltaba, bloqueado o dañado, recalculado).

    ``ValidationError`` sin escribir nada si no existe (``core.dataset_unknown``), si está
    sustituido o descartado (``core.dataset_not_live``), si es lo importado
    (``core.dataset_immutable``, RF-008-52), si ``spec`` no tiene su identidad
    (``core.dataset_identity_changed``), si la operación falta o no está en curso o ya lo
    escribió, o si el hash no se puede calcular."""
    if not isinstance(spec, DatasetSpec):
        raise TypeError(f"se escribe un DatasetSpec, no {type(spec).__name__}")
    operation = _check_operation(conn, spec.name, operation_uid)
    record = _require(conn, uid, spec.name)
    if not record.live:
        raise _error("core.dataset_not_live", record.name,
                     f"está «{record.status}»: un dato sustituido o descartado queda como "
                     "historia y no admite contenido nuevo", "estado", str(record.status))
    if record.immutable:
        row = conn.execute("SELECT name FROM gb_input WHERE uid = ?",
                           (record.input_uid,)).fetchone()
        entry = record.input_uid if row is None else row[0]
        raise _error("core.dataset_immutable", record.name,
                     f"es lo importado de la entrada «{entry}»: su contenido no cambia "
                     "(RF-008-52); para otro contenido, actualice la entrada",
                     "contenido", record.content_sha256)
    for attribute, label in _IDENTITY:
        if getattr(spec, attribute) != getattr(record, attribute):
            raise _error("core.dataset_identity_changed", record.name,
                         "un contenido nuevo no cambia la identidad ni la ubicación del dato: "
                         f"su {label} es «{getattr(record, attribute)}»", label,
                         getattr(spec, attribute))
    _check_output(conn, spec, operation, record.uid)
    _track(conn, spec)
    sha = _content(conn, project, spec, record.reader, record.normalizer)
    now = format_utc(project.clock.now())
    changes: dict[str, object] = {
        "content_sha256": sha,
        "operation_uid": operation,
        "crs_epsg": spec.crs_epsg,
        "qgis_editable": int(spec.qgis_editable),
        "status": str(DatasetStatus.CURRENT),
        "checked_at": now if record.tracked else None,
        "modified_at": now,
        **_tracking(conn, project, spec),
    }
    conn.execute(
        f"UPDATE gb_dataset SET {', '.join(f'{column} = ?' for column in changes)} "
        "WHERE uid = ?",
        (*changes.values(), record.uid),
    )
    _record_change(conn, record.uid, record.content_sha256, sha, spec, operation, now)
    return _require(conn, record.uid, record.name)


def note_content(conn: sqlite3.Connection, project: DatasetProject, uid: str, *,
                 operation_uid: str | None,
                 detail: Mapping[str, object] | None = None) -> DatasetRecord:
    """Anota el contenido que tiene **ahora** la tabla del dato vivo ``uid``, que acaba de escribir
    Geoblender en la transacción ``conn`` dentro de la operación en curso ``operation_uid`` **sin que
    esa operación lo declare como salida**: su hash (con **su** lector y su normalizador), su
    seguimiento (``last_change`` y la huella del SQL), su fecha y, si el hash cambia, su fila de
    cambio con ``detail`` y esa operación. Es lo que hace una operación **de versión** con un dato
    **del proyecto** que no puede escribir como suyo (spec 009, RF-009-05: sus salidas son de su
    versión): el dato sigue siendo de la operación que lo escribió, no se le añade ninguna salida, y
    la comprobación de datos no lo toma luego por una edición hecha fuera de Geoblender
    (RF-008-21), ni lo bloquea (RF-008-56).

    Quien llama comprueba **antes de escribir** que el dato estaba al día (``external.probe_dataset``:
    lo que ya cambió fuera se queda como edición y no se da por bueno aquí). ``ValueError`` (un error
    del programa) si el dato no es una tabla del proyecto vigente y seguida, o es lo importado;
    ``ValidationError`` (``core.dataset_*``) si no existe o la operación falta o no está en curso, y
    si su hash no se puede calcular. No cambia el estado ni la operación del dato."""
    if not isinstance(uid, str):
        raise TypeError(f"un dato se indica por su uid, no {uid!r}")
    record = _require(conn, uid)
    operation = _check_operation(conn, record.name, operation_uid)
    if (record.store is not Store.GPKG or not record.tracked or record.immutable
            or record.status is not DatasetStatus.CURRENT):
        raise ValueError(f"el dato «{record.name}» no es una tabla del proyecto vigente y seguida "
                         f"(almacén {record.store}, estado {record.status}): no se anota su contenido")
    sha = content_digest(conn, project, record).content_sha256
    state = tracking.table_states(conn, [record.locator])[record.locator]
    now = format_utc(project.clock.now())
    conn.execute(
        "UPDATE gb_dataset SET content_sha256 = ?, tracked_last_change = ?, "
        "tracked_schema_sha256 = ?, checked_at = ?, modified_at = ? WHERE uid = ?",
        (sha, state.last_change, state.schema_sha256, now, now, record.uid),
    )
    if sha != record.content_sha256:
        conn.execute(
            "INSERT INTO gb_dataset_change (dataset_uid, from_sha256, to_sha256, operation_uid, "
            "detail, at) VALUES (?, ?, ?, ?, ?, ?)",
            (record.uid, record.content_sha256, sha, operation,
             None if detail is None else canonical_json(dict(detail)).decode("utf-8"), now),
        )
    return _require(conn, record.uid, record.name)


def supersede(conn: sqlite3.Connection, project: DatasetProject, uid: str, *,
              by: str | None = None) -> DatasetRecord:
    """Marca «sustituido» el dato vivo ``uid`` (lo importado de una entrada actualizada,
    RF-008-11), que conserva su nombre y su contenido; ``by`` anota su sucesor (si no, se
    resuelve por papel: :func:`successor`). ``ValidationError`` si no existe, si no está vivo
    o si ``by`` no es otro dato."""
    record = _require(conn, uid)
    if not record.live:
        raise _error("core.dataset_not_live", record.name,
                     f"ya está «{record.status}»", "estado", str(record.status))
    if by is not None:
        following = _require(conn, by, record.name)
        if following.uid == record.uid:
            raise _error("core.dataset_successor_self", record.name,
                         "un dato no se sustituye a sí mismo", "sucesor", by)
    now = format_utc(project.clock.now())
    conn.execute(
        "UPDATE gb_dataset SET status = ?, superseded_by = ?, modified_at = ? WHERE uid = ?",
        (str(DatasetStatus.SUPERSEDED), by, now, record.uid),
    )
    _refresh_stale(conn, now, record.uid)
    return _require(conn, record.uid, record.name)


def set_status(conn: sqlite3.Connection, project: DatasetProject, uid: str,
               status: DatasetStatus | str) -> DatasetRecord:
    """Cambia el estado del dato ``uid``: vigente, que falta (RF-008-57), bloqueado
    (RF-008-56), dañado (ADR-0025 §4) o descartado (RF-008-55). Sustituir es
    :func:`supersede` (``ValueError``). ``ValidationError`` (``core.dataset_status_final``) si
    está sustituido o descartado: ya no cambia."""
    target = DatasetStatus(status)
    if target is DatasetStatus.SUPERSEDED:
        raise ValueError("un dato se sustituye con supersede(), que anota su sucesor")
    record = _require(conn, uid)
    if record.status in FINAL_STATUSES:
        raise _error("core.dataset_status_final", record.name,
                     f"está «{record.status}» y queda como historia: su estado ya no cambia",
                     "estado", str(target))
    if record.status is not target:
        now = format_utc(project.clock.now())
        conn.execute(
            "UPDATE gb_dataset SET status = ?, modified_at = ? WHERE uid = ?",
            (str(target), now, record.uid),
        )
        _refresh_stale(conn, now, record.uid)
    return _require(conn, record.uid, record.name)


def _refresh_stale(conn: sqlite3.Connection, now: str, uid: str) -> None:
    """La obsolescencia por región de lo que consumió el dato ``uid``, que cambió de estado,
    en la misma transacción (RF-008-24: un dato que falta, bloqueado, dañado o que ya no está
    vivo). Se importa aquí: ``core.provenance`` importa ``core.datasets`` (ARQ-08)."""
    from ..provenance.stale import refresh_region

    refresh_region(conn, now=now, datasets=[uid])


# SPDX-License-Identifier: GPL-3.0-or-later
"""Crear versiones y cambiar su estado y su título (spec 009; RF-009-01, RF-009-02, RF-009-03,
RF-009-04, RF-009-12, RF-009-22, RF-009-25; plan 009 A1, A2, D-3 y D-24 a D-26; ADR-0013).

Cada función escribe en la transacción que recibe (``Project.write_transaction()`` o
``try_write()``, en el hilo de Blender) y lo comprueba todo **antes** de escribir: un rechazo es
un :class:`~.model.VersionError` (un error de Geoblender, que solo deshace la transacción) con
los textos de la spec, nunca una restricción de SQLite (los disparadores de
``core.versions.schema`` son la segunda barrera, para quien escribe en la base a mano).

- :func:`create_version` (A1): el código siguiente (V01, V02…), inmutable; el estado BORRADOR;
  la r1 abierta («Revisión inicial»); quién y cuándo; con versión de partida, su última revisión
  congelada (``parent_revision_uid``) y sus parámetros de versión copiados con la fila de
  historial «Heredado de V10.r2» (``core.params.ParameterStore.inherit``; D-26), y **nada
  más**: ni datos, ni operaciones, ni cifras de la otra versión (D-10; Silvestre, error 32). La
  primera versión sube ``min_reader_schema`` a 3 en la misma transacción (D-24): un Geoblender
  anterior abrirá el proyecto solo con la cabecera. Quien la llama regenera la cabecera tras
  confirmar (``Project.refresh_header()``; también al cerrar el proyecto).
- :func:`set_status` (A2): BORRADOR → VIGENTE (con al menos una revisión congelada; la VIGENTE
  anterior pasa a SUPERADO, «Superada por V11», en la misma transacción) y BORRADOR o VIGENTE →
  DESCARTADO (con motivo); toda versión que pasa a SUPERADO o DESCARTADO cierra su revisión
  abierta, sin instantánea («cerrada al superarse», RF-009-25). Cada estado, en **una**
  sentencia con su motivo, quién y cuándo (después, la base no deja cambiar nada de una versión
  cerrada). Solo escribe filas de ``gb_version``, ``gb_revision`` y ``gb_event`` y, si la que
  se cierra tiene operaciones, la caché de la obsolescencia (``gb_stale``: lo suyo sale de la
  cascada, plan A4 (1)): ningún fichero (RF-009-02).
- :func:`set_title` (RF-009-22): el título de una versión o de un dato, nunca su código ni su
  nombre.
- :func:`require_editable`: la versión, si es BORRADOR o VIGENTE; si no, el rechazo de
  RF-009-04 («V09 está en estado SUPERADO: cree una versión nueva a partir de ella»).

Cada cambio deja su evento (``version_created``, ``status_change``, ``revision_closed`` y
``title_changed``). Ninguna función borra nada (RF-009-12): descartar una versión la marca y la
conserva entera. Ningún texto guardado lleva una ruta absoluta. Python puro; no importa
``core.provenance`` al cargarse (ARQ-08): solo su caché, dentro de :func:`set_status`.
"""

from __future__ import annotations

import sqlite3
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Protocol

from ..ids import new_uid
from ..params.store import ParameterStore
from ..paths import find_absolute_paths
from ..project.events import EventKind, record_event
from ..timeutil import Clock, format_utc
from . import read
from .model import (
    CLOSED_ON_SUPERSEDING,
    FIRST_REVISION_REASON,
    REQUESTED,
    Revision,
    RevisionState,
    Version,
    VersionError,
    VersionStatus,
    ensure_editable,
    version_code,
)

if TYPE_CHECKING:
    from ..sysinfo import SessionInfo

MIN_READER_SCHEMA = 3
"""El esquema mínimo de lectura de un proyecto con versiones (D-24): lo pone la primera."""


class VersionProject(Protocol):
    """Lo que usan estas funciones del proyecto (``core.project.Project``): la sesión (quién y
    con qué sesión se escribe), el reloj y una conexión de lectura (la usa el almacén de
    parámetros al heredar)."""

    @property
    def session(self) -> SessionInfo: ...

    @property
    def clock(self) -> Clock: ...

    def read(self) -> AbstractContextManager[sqlite3.Connection]: ...


@dataclass(frozen=True, slots=True)
class StatusChange:
    """Lo que hizo :func:`set_status`: la versión en su estado nuevo, el que tenía, la VIGENTE
    anterior ya SUPERADO (al declarar VIGENTE otra; si no, ``None``) y las revisiones que se
    cerraron al superarse o descartarse (RF-009-25)."""

    version: Version
    previous: VersionStatus
    superseded: Version | None
    closed: tuple[Revision, ...]


# --- Comprobaciones -------------------------------------------------------------------------


def _text(value: object) -> str | None:
    """El texto sin espacios a los lados; ``None`` si falta o está vacío."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"se esperaba un texto, no {type(value).__name__} ({value!r})")
    return value.strip() or None


def _checked(value: object, field: str) -> str | None:
    """Como :func:`_text`, sin rutas absolutas: el proyecto no guarda ninguna (RF-002-18)."""
    text = _text(value)
    if text is not None and find_absolute_paths(text):
        raise VersionError("core.version_text_path", field=field, value=value, text=text)
    return text


def _required(value: object, code: str, field: str, **values: object) -> str:
    text = _checked(value, field)
    if text is None:
        raise VersionError(code, field=field, value=value, **values)
    return text


def _require(conn: sqlite3.Connection, uid_or_code: str, field: str) -> Version:
    found = read.version(conn, uid_or_code)
    if found is None:
        raise VersionError("core.version_unknown", field=field, value=uid_or_code,
                           version=uid_or_code)
    return found


def _status(target: object) -> VersionStatus:
    if isinstance(target, str) and target in VersionStatus:
        return VersionStatus(target)
    raise VersionError("core.version_state_unknown", field="estado", value=target, target=target)


def _now(project: VersionProject) -> str:
    return format_utc(project.clock.now())


def require_editable(conn: sqlite3.Connection, version_uid: str) -> Version:
    """La versión de uid (o código) ``version_uid`` si es BORRADOR o VIGENTE. Si es SUPERADO o
    DESCARTADO, :class:`~.model.VersionError` ``core.version_not_editable`` con el texto de
    RF-009-04; si no existe, ``core.version_unknown``. Solo lee."""
    return ensure_editable(_require(conn, version_uid, "versión"))


# --- Crear ----------------------------------------------------------------------------------


def _next_number(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT max(CAST(substr(code, 2) AS INTEGER)) FROM gb_version").fetchone()
    return 1 if row is None or row[0] is None else int(row[0]) + 1


def _inherited_from(conn: sqlite3.Connection, parent: Version) -> str:
    """La revisión de la padre en que sus parámetros tienen hoy su valor (D-26): su abierta
    o, si está cerrada, su última («V10.r2»); sin revisiones, su código."""
    current = read.open_revision(conn, parent.uid)
    if current is not None:
        return current.label(parent.code)
    known = read.revisions(conn, parent.uid)
    return known[-1].label(parent.code) if known else parent.code


def _raise_min_reader(conn: sqlite3.Connection, now: str) -> bool:
    """Sube ``min_reader_schema`` a 3 si es menor (D-24); verdadero si lo ha cambiado."""
    cursor = conn.execute(
        "UPDATE gb_project SET min_reader_schema = ?, modified_at = ? "
        "WHERE min_reader_schema < ?",
        (MIN_READER_SCHEMA, now, MIN_READER_SCHEMA),
    )
    return cursor.rowcount > 0


def create_version(
    conn: sqlite3.Connection,
    project: VersionProject,
    *,
    feature: str,
    title: str,
    reason: str,
    parent: str | None = None,
    request: str | None = None,
) -> tuple[Version, Revision]:
    """Crea una versión (RF-009-01; plan A1) con el rasgo ``feature`` (lo que la distingue, el
    ``<rasgo>`` de ``Vnn_<rasgo>``), el título, el motivo y, si se indican, la versión de la que
    parte (``parent``: uid o código, de cualquier estado) y el encargo (texto libre hasta
    R-63), y devuelve la versión y su revisión r1 abierta. Ver el módulo: código, herencia y
    ``min_reader_schema``; evento ``version_created``.

    :class:`~.model.VersionError` sin rasgo, título o motivo (``core.version_*_required``),
    con una versión de partida que no existe (``core.version_unknown``) o con una ruta
    absoluta en un texto (``core.version_text_path``); entonces no escribe nada."""
    feature_text = _required(feature, "core.version_feature_required", "rasgo")
    title_text = _required(title, "core.version_title_required", "título")
    reason_text = _required(reason, "core.version_reason_required", "motivo")
    request_text = _checked(request, "encargo")
    origin = None if parent is None else _require(conn, parent, "parte de")
    frozen = None if origin is None else read.last_frozen(conn, origin.uid)
    code = version_code(_next_number(conn))
    uid, revision_uid = new_uid(), new_uid()
    now, user = _now(project), project.session.user_host
    conn.execute(
        "INSERT INTO gb_version (uid, code, feature, title, status, parent_uid, "
        "parent_revision_uid, request, reason_created, created_at, created_by, "
        "status_changed_at, status_changed_by, modified_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            uid, code, feature_text, title_text, VersionStatus.BORRADOR.value,
            None if origin is None else origin.uid, None if frozen is None else frozen.uid,
            request_text, reason_text, now, user, now, user, now,
        ),
    )
    conn.execute(
        "INSERT INTO gb_revision (uid, version_uid, number, state, reason, created_at, "
        "created_by) VALUES (?, ?, 1, ?, ?, ?, ?)",
        (revision_uid, uid, RevisionState.OPEN.value, FIRST_REVISION_REASON, now, user),
    )
    inherited, label = 0, None
    if origin is not None:
        label = _inherited_from(conn, origin)
        inherited = ParameterStore(project).inherit(conn, origin.uid, uid, label=label)
    raised = _raise_min_reader(conn, now)
    message = (
        f"Versión {code} «{title_text}» creada por {user} en BORRADOR, con su revisión r1 "
        "abierta"
    )
    if origin is not None:
        message += f"; parte de {origin.code}"
        if frozen is not None:
            message += f" (su última revisión congelada, {frozen.label(origin.code)})"
        message += f" y hereda {inherited} parámetro(s) de versión de {label}"
    message += f". Motivo: {reason_text}"
    data: dict[str, Any] = {
        "code": code, "feature": feature_text, "title": title_text, "reason": reason_text,
        "request": request_text, "revision_uid": revision_uid,
        "parent": None if origin is None else origin.code,
        "parent_revision": None if frozen is None or origin is None
        else frozen.label(origin.code),
        "inherited": inherited, "inherited_from": label,
    }
    if raised:
        data["min_reader_schema"] = MIN_READER_SCHEMA
    record_event(conn, EventKind.VERSION_CREATED, message, session=project.session, at=now,
                 entity_kind="version", entity_uid=uid, data=data)
    created, opened = read.version(conn, uid), read.open_revision(conn, uid)
    if created is None or opened is None:  # inalcanzable: se acaban de escribir
        raise RuntimeError(f"la versión {code} no se ha podido leer tras crearla")
    return created, opened


# --- Estado ---------------------------------------------------------------------------------


def _close_open_revision(conn: sqlite3.Connection, project: VersionProject, version: Version,
                         target: VersionStatus, now: str) -> list[Revision]:
    """Cierra la revisión abierta de ``version``, que pasa a ``target`` (RF-009-25), sin
    instantánea: «cerrada al superarse». Devuelve la revisión cerrada (o nada)."""
    revision = read.open_revision(conn, version.uid)
    if revision is None:
        return []
    user = project.session.user_host
    conn.execute(
        "UPDATE gb_revision SET state = ?, closed_at = ?, closed_by = ? WHERE uid = ?",
        (RevisionState.CLOSED.value, now, user, revision.uid),
    )
    label = revision.label(version.code)
    record_event(
        conn, EventKind.REVISION_CLOSED,
        f"Revisión {label} {CLOSED_ON_SUPERSEDING} (sin instantánea): {version.code} pasa a "
        f"{target.value}; sus resultados quedan como historia no reproducible",
        session=project.session, at=now, entity_kind="revision", entity_uid=revision.uid,
        data={"version": version.code, "revision": label, "status": target.value},
    )
    return [replace(revision, state=RevisionState.CLOSED, closed_at=now, closed_by=user)]


def _write_status(conn: sqlite3.Connection, project: VersionProject, version: Version,
                  target: VersionStatus, *, reason: str | None, reason_closed: str | None,
                  now: str) -> None:
    """El estado nuevo con su motivo de cierre, quién y cuándo, en una sola sentencia (una
    versión SUPERADO o DESCARTADO ya no deja cambiar nada), y su evento ``status_change``."""
    user = project.session.user_host
    conn.execute(
        "UPDATE gb_version SET status = ?, reason_closed = ?, status_changed_at = ?, "
        "status_changed_by = ?, modified_at = ? WHERE uid = ?",
        (target.value, reason_closed, now, user, now, version.uid),
    )
    message = f"{version.code} «{version.title}» pasa de {version.status.value} a {target.value}"
    message += f" ({user})" + (f". Motivo: {reason}" if reason else "")
    record_event(
        conn, EventKind.STATUS_CHANGE, message, session=project.session, at=now,
        entity_kind="version", entity_uid=version.uid,
        data={"version": version.code, "from": version.status.value, "to": target.value,
              "reason": reason},
    )


_VERSION_OPERATIONS = (  # de sus revisiones a sus operaciones, por sus índices
    "SELECT op.uid FROM gb_revision AS r CROSS JOIN gb_operation AS op "
    "ON op.revision_uid = r.uid AND op.revision_uid <> '' "
    "WHERE r.version_uid = ? AND op.status = 'done'"
)


def _leave_cascade(conn: sqlite3.Connection, version_uids: list[str], now: str) -> None:
    """Lo de las versiones ``version_uids``, que acaban de pasar a SUPERADO o DESCARTADO, sale
    de la cascada (spec 009, plan A4 (1); RF-009-19): la caché de la obsolescencia suelta sus
    operaciones y sus datos (y lo que dependía de ellos se deduce otra vez) en la misma
    transacción."""
    operations = [str(uid) for version_uid in version_uids
                  for (uid,) in conn.execute(_VERSION_OPERATIONS, (version_uid,))]
    if operations:
        # Aquí: core.provenance importa core.versions (ARQ-08).
        from ..provenance.stale import refresh_region

        refresh_region(conn, now=now, operations=operations)


def set_status(
    conn: sqlite3.Connection,
    project: VersionProject,
    version_uid: str,
    target: VersionStatus | str,
    *,
    reason: str | None = None,
) -> StatusChange:
    """Cambia el estado de la versión ``version_uid`` (uid o código) a ``target`` (RF-009-03;
    plan A2): BORRADOR → VIGENTE o DESCARTADO y VIGENTE → DESCARTADO. Ver el módulo.

    :class:`~.model.VersionError`, sin escribir nada: la versión no existe
    (``core.version_unknown``); el estado no existe (``core.version_state_unknown``); la
    versión es SUPERADO o DESCARTADO (``core.version_not_editable``, RF-009-04); ya está en
    ese estado (``core.version_same_state``); el cambio no es de los admitidos (también pedir
    SUPERADO: lo hace declarar VIGENTE otra; ``core.version_transition``); descartar sin motivo
    (``core.version_discard_reason``); VIGENTE sin ninguna revisión congelada
    (``core.version_freeze_first``: «Congele antes una revisión de V11»); un motivo con una
    ruta absoluta (``core.version_text_path``)."""
    version = _require(conn, version_uid, "versión")
    wanted = _status(target)
    ensure_editable(version)
    if wanted is version.status:
        raise VersionError("core.version_same_state", field="estado", value=wanted.value,
                           version=version.code, state=version.status)
    if wanted not in REQUESTED.get(version.status, frozenset()):
        raise VersionError("core.version_transition", field="estado", value=wanted.value,
                           version=version.code, state=version.status, target=wanted)
    reason_text = _checked(reason, "motivo")
    if wanted is VersionStatus.DESCARTADO and reason_text is None:
        raise VersionError("core.version_discard_reason", field="motivo", value=reason,
                           version=version.code)
    if wanted is VersionStatus.VIGENTE and read.last_frozen(conn, version.uid) is None:
        raise VersionError("core.version_freeze_first", field="estado", value=wanted.value,
                           version=version.code)
    now = _now(project)
    closed: list[Revision] = []
    superseded: Version | None = None
    if wanted is VersionStatus.VIGENTE:
        previous = read.current_version(conn)
        if previous is not None:  # D-3: la anterior, a SUPERADO en la misma transacción
            because = f"Superada por {version.code}"
            closed += _close_open_revision(conn, project, previous, VersionStatus.SUPERADO, now)
            _write_status(conn, project, previous, VersionStatus.SUPERADO, reason=because,
                          reason_closed=because, now=now)
            superseded = read.version(conn, previous.uid)
    else:
        closed += _close_open_revision(conn, project, version, wanted, now)
    _write_status(conn, project, version, wanted, reason=reason_text,
                  reason_closed=reason_text if wanted is VersionStatus.DESCARTADO else None,
                  now=now)
    leaving = [version.uid] if wanted is VersionStatus.DESCARTADO else []
    if superseded is not None:
        leaving.append(superseded.uid)
    _leave_cascade(conn, leaving, now)
    changed = read.version(conn, version.uid)
    if changed is None:  # inalcanzable: nada se borra
        raise RuntimeError(f"la versión {version.code} no se ha podido leer tras cambiarla")
    return StatusChange(changed, version.status, superseded, tuple(closed))


# --- Título ---------------------------------------------------------------------------------


def set_title(
    conn: sqlite3.Connection,
    project: VersionProject,
    *,
    version_uid: str | None = None,
    dataset_uid: str | None = None,
    title: str,
) -> str:
    """Guarda ``title`` (sin espacios a los lados) como título de la versión ``version_uid``
    (uid o código) o del dato ``dataset_uid`` (RF-009-22: el renombrado desde el Outliner) y lo
    devuelve; no cambia su código, su nombre ni ninguna ruta. El mismo título no escribe nada.
    Evento ``title_changed`` con el anterior y el nuevo.

    :class:`~.model.VersionError`, sin escribir nada: sin título; la versión o el dato no
    existen; la versión (o la del dato) es SUPERADO o DESCARTADO (RF-009-04); una ruta absoluta.
    :class:`ValueError` si no se indica uno (y solo uno) de los dos."""
    if (version_uid is None) == (dataset_uid is None):
        raise ValueError("set_title cambia el título de una versión o de un dato: indique uno")
    now, user = _now(project), project.session.user_host
    if version_uid is not None:
        version = _require(conn, version_uid, "versión")
        text = _required(title, "core.version_title_required", "título")
        ensure_editable(version)
        if text == version.title:
            return text
        conn.execute("UPDATE gb_version SET title = ?, modified_at = ? WHERE uid = ?",
                     (text, now, version.uid))
        record_event(
            conn, EventKind.TITLE_CHANGED,
            f"Título de {version.code} cambiado por {user}: «{version.title}» → «{text}»",
            session=project.session, at=now, entity_kind="version", entity_uid=version.uid,
            data={"version": version.code, "from": version.title, "to": text},
        )
        return text
    row = conn.execute("SELECT name, title, version_uid FROM gb_dataset WHERE uid = ?",
                       (dataset_uid,)).fetchone()
    if row is None:
        raise VersionError("core.version_dataset_unknown", field="dato", value=dataset_uid,
                           dataset=dataset_uid)
    name, old, owner_uid = row
    text = _required(title, "core.version_dataset_title_required", "título", dataset=name)
    owner = ensure_editable(_require(conn, owner_uid, "versión")) if owner_uid else None
    if text == old:
        return text
    conn.execute("UPDATE gb_dataset SET title = ?, modified_at = ? WHERE uid = ?",
                 (text, now, dataset_uid))
    record_event(
        conn, EventKind.TITLE_CHANGED,
        f"Título del dato «{name}» cambiado por {user}: «{old or name}» → «{text}»",
        session=project.session, at=now, entity_kind="dataset", entity_uid=dataset_uid,
        data={"name": name, "version": None if owner is None else owner.code, "from": old,
              "to": text},
    )
    return text

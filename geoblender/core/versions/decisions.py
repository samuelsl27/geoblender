# SPDX-License-Identifier: GPL-3.0-or-later
"""Las decisiones de la propiedad (spec 009; RF-009-13, RF-009-12; HU-009-4; plan 009 A10 y
D-33; Silvestre PRJ-13).

Una decisión de la propiedad es quién decide, cuándo, qué y su origen: un documento o una
captura **registrado como entrada** (``gb_input`` de tipo ``document``, con su hash y su
procedencia, RF-008-53) o una **referencia en texto** («correo del 03/10/2026»), o las dos; y a
qué afecta: claves de parámetro (``res.swell_factor``: el enlace es a la clave, así que vale
para **todos sus ámbitos**, el del proyecto y el de cada versión, también los que se creen
después) y versiones (de cualquier estado: es un registro aparte, que no cambia la versión).

- :func:`record_decision` la registra en la transacción que recibe (``Project.write_transaction()``
  o ``try_write()``, en el hilo de Blender): la fila de ``gb_decision``, un enlace por clave y
  por versión en ``gb_decision_link`` y el evento ``decision_recorded``. Lo comprueba todo
  **antes** de escribir: un rechazo es un :class:`~.model.VersionError` con su texto.
- :func:`decisions`: todas, las de un parámetro o las de una versión (la lista «Encargos y
  decisiones de la propiedad»; en el control 8, las de una versión).
- :func:`deciders`: las de cada clave de parámetro (el decisor de la propiedad en Parámetros del
  proyecto, junto al suyo).

Se leen por el día de la decisión y, en el mismo día, por el orden en que se registraron. Nada
se cambia ni se borra (RF-009-12): este módulo no lo ofrece y la base lo rechaza (las dos tablas
son de solo inserción, ``core.versions.schema``); registrar una decisión no cambia el parámetro
(su decisor sigue siendo el suyo), ni la versión, ni la entrada. Un proyecto sin estas tablas
(el esquema 2 abierto en solo lectura) no tiene ninguna. Ningún texto guardado lleva una ruta
absoluta. Python puro; no importa ``core.provenance`` (ARQ-08).
"""

from __future__ import annotations

import datetime as dt
import re
import sqlite3
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any

from ..ids import new_uid
from ..paths import find_absolute_paths
from ..project.events import EventKind, record_event
from ..timeutil import format_utc
from . import read
from .model import Decision, VersionError

if TYPE_CHECKING:
    from .store import VersionProject

DOCUMENT_KIND = "document"
"""El tipo de entrada del documento o la captura de origen (``gb_input.kind``; D-33)."""
PARAMETER, VERSION = "parameter", "version"
"""Lo que enlaza una decisión (``gb_decision_link.item_kind``)."""

_CHUNK = 500
"""Claves o uids por consulta (``IN (…)``)."""
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_COLUMNS = (
    "d.uid, d.decided_by, d.decided_at, d.what, d.source_input_uid, i.name, "
    "d.source_text, d.recorded_by, d.recorded_at"
)
_SELECT = (
    f"SELECT {_COLUMNS} FROM gb_decision AS d "
    "LEFT JOIN gb_input AS i ON i.uid = d.source_input_uid"
)
_ORDER = " ORDER BY d.decided_at, d.fid"
_LINKED = (
    "d.uid IN (SELECT decision_uid FROM gb_decision_link WHERE item_kind = ? AND item_uid = ?)"
)


# --- Comprobaciones -------------------------------------------------------------------------


def _text(value: object, field: str) -> str | None:
    """El texto sin espacios a los lados, sin rutas absolutas (el proyecto no guarda ninguna,
    RF-002-18); ``None`` si falta o está vacío."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field}: se esperaba un texto, no {type(value).__name__} ({value!r})")
    text = value.strip()
    if text and find_absolute_paths(text):
        raise VersionError("core.version_text_path", field=field, value=value, text=text)
    return text or None


def _required(value: object, code: str, field: str) -> str:
    text = _text(value, field)
    if text is None:
        raise VersionError(code, field=field, value=value)
    return text


def _day(value: object) -> str:
    """El día de la decisión como se guarda, «AAAA-MM-DD» (de un ``date`` o de ese texto)."""
    if value is None:
        raise VersionError("core.version_decision_date_required", field="fecha")
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return value.isoformat()
    text = value.strip() if isinstance(value, str) else None
    if text is not None and _DATE.fullmatch(text) is not None:
        try:
            return dt.date.fromisoformat(text).isoformat()
        except ValueError:
            pass
    raise VersionError("core.version_decision_date", field="fecha", value=str(value),
                       date=str(value))


def _items(values: object, what: str) -> list[str]:
    """Los textos de ``values`` (una secuencia: un texto suelto es un error de programación),
    sin espacios a los lados y sin repetir, en su orden."""
    if isinstance(values, str | bytes) or not isinstance(values, Iterable):
        raise TypeError(f"{what} van en una secuencia de textos, no {values!r}")
    found: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise TypeError(f"{what}: se esperaba un texto, no {value!r}")
        text = value.strip()
        if text and text not in found:
            found.append(text)
    return found


def _source(conn: sqlite3.Connection, uid: object) -> tuple[str, str] | None:
    """La entrada de tipo documento ``uid`` (su uid y su nombre); ``None`` si no se indica."""
    text = _text(uid, "documento")
    if text is None:
        return None
    row = conn.execute("SELECT name, kind FROM gb_input WHERE uid = ?", (text,)).fetchone()
    if row is None:
        raise VersionError("core.version_decision_input_unknown", field="documento", value=text,
                           input=text)
    name, kind = str(row[0]), str(row[1])
    if kind != DOCUMENT_KIND:
        raise VersionError("core.version_decision_input_kind", field="documento", value=text,
                           input=name, kind=kind)
    return text, name


def _parameters(conn: sqlite3.Connection, keys: object) -> list[str]:
    found = _items(keys, "las claves de parámetro")
    for key in found:
        if conn.execute("SELECT 1 FROM gb_parameter WHERE key = ? LIMIT 1",
                        (key,)).fetchone() is None:
            raise VersionError("core.version_decision_parameter_unknown", field="parámetro",
                               value=key, key=key)
    return found


def _versions(conn: sqlite3.Connection, refs: object) -> list[tuple[str, str]]:
    """El uid y el código de cada versión de ``refs`` (uid o código), sin repetir."""
    found: list[tuple[str, str]] = []
    for ref in _items(refs, "las versiones"):
        version = read.version(conn, ref)
        if version is None:
            raise VersionError("core.version_unknown", field="versión", value=ref, version=ref)
        if (version.uid, version.code) not in found:
            found.append((version.uid, version.code))
    return found


# --- Registrar --------------------------------------------------------------------------------


def record_decision(
    conn: sqlite3.Connection,
    project: VersionProject,
    *,
    decided_by: str,
    decided_at: dt.date | str,
    what: str,
    source_input_uid: str | None = None,
    source_text: str | None = None,
    parameters: Sequence[str] = (),
    versions: Sequence[str] = (),
) -> Decision:
    """Registra una decisión de la propiedad (RF-009-13; plan A10) y la devuelve: quién decide
    (``decided_by``), el día (``decided_at``: ``date`` o «AAAA-MM-DD»), qué se decide
    (``what``), su origen (``source_input_uid``, una entrada registrada de tipo documento, y/o
    ``source_text``, una referencia en texto) y a qué afecta (``parameters``: claves de
    parámetro; ``versions``: uid o código de versiones de cualquier estado; cada una se enlaza
    una vez aunque se repita), con quién y cuándo la registra (la sesión y el reloj de
    ``project``) y el evento ``decision_recorded``, en la transacción ``conn``.

    :class:`~.model.VersionError`, sin escribir nada: sin quién, qué o cuándo
    (``core.version_decision_by_required``, ``_what_required``, ``_date_required``); un día
    que no lo es (``core.version_decision_date``); sin documento ni texto
    (``core.version_decision_source_required``); una entrada que no existe o que no es un
    documento (``core.version_decision_input_unknown``, ``_input_kind``); un parámetro sin
    ninguna fila en el proyecto (``core.version_decision_parameter_unknown``); una versión que
    no existe (``core.version_unknown``); una ruta absoluta en un texto
    (``core.version_text_path``). :class:`TypeError` si ``parameters`` o ``versions`` no son
    secuencias de textos."""
    who = _required(decided_by, "core.version_decision_by_required", "quién decide")
    decided = _required(what, "core.version_decision_what_required", "qué se decide")
    day = _day(decided_at)
    reference = _text(source_text, "referencia")
    source = _source(conn, source_input_uid)
    if source is None and reference is None:
        raise VersionError("core.version_decision_source_required", field="documento")
    keys = _parameters(conn, parameters)
    linked = _versions(conn, versions)
    uid, now, user = new_uid(), format_utc(project.clock.now()), project.session.user_host
    conn.execute(
        "INSERT INTO gb_decision (uid, decided_by, decided_at, what, source_input_uid, "
        "source_text, recorded_by, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (uid, who, day, decided, None if source is None else source[0], reference, user, now),
    )
    conn.executemany(
        "INSERT INTO gb_decision_link (decision_uid, item_kind, item_uid) VALUES (?, ?, ?)",
        [*((uid, PARAMETER, key) for key in keys),
         *((uid, VERSION, version_uid) for version_uid, _code in linked)],
    )
    codes = [code for _uid, code in linked]
    decision = Decision(
        uid, who, day, decided, None if source is None else source[0],
        None if source is None else source[1], reference, user, now, tuple(keys),
        tuple(version_uid for version_uid, _code in linked), tuple(codes),
    )
    message = (f"Decisión de la propiedad registrada por {user}: «{decided}» ({who}, "
               f"{decision.day})")
    if source is not None:
        message += f"; documento «{source[1]}»"
    if reference is not None:
        message += f"; referencia: {reference}"
    if keys or codes:
        message += f"; afecta a {', '.join([*keys, *codes])}"
    record_event(
        conn, EventKind.DECISION_RECORDED, message, session=project.session, at=now,
        entity_kind="decision", entity_uid=uid,
        data={"decided_by": who, "decided_at": day, "what": decided,
              "source_input": decision.source_input_uid, "source_name": decision.source_name,
              "source_text": reference, "parameters": keys, "versions": codes},
    )
    return decision


# --- Leer -----------------------------------------------------------------------------------


def _has_tables(conn: sqlite3.Connection) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'gb_decision'"
    ).fetchone() is not None


def _chunks(values: Sequence[str]) -> Iterable[Sequence[str]]:
    for start in range(0, len(values), _CHUNK):
        yield values[start:start + _CHUNK]


def _links(conn: sqlite3.Connection,
           uids: Sequence[str]) -> dict[str, tuple[list[str], list[tuple[str, str]]]]:
    """Las claves y las versiones (uid y código) que enlaza cada decisión de ``uids``, en el
    orden en que se enlazaron."""
    found: dict[str, tuple[list[str], list[tuple[str, str]]]] = {
        uid: ([], []) for uid in uids
    }
    for chunk in _chunks(uids):
        marks = ", ".join("?" for _ in chunk)
        for decision_uid, kind, item_uid, code in conn.execute(
            "SELECT l.decision_uid, l.item_kind, l.item_uid, v.code FROM gb_decision_link AS l "
            "LEFT JOIN gb_version AS v ON l.item_kind = 'version' AND v.uid = l.item_uid "
            f"WHERE l.decision_uid IN ({marks}) ORDER BY l.fid",
            tuple(chunk),
        ):
            keys, versions = found[str(decision_uid)]
            if kind == PARAMETER:
                keys.append(str(item_uid))
            else:
                versions.append((str(item_uid), str(code)))
    return found


def _build(conn: sqlite3.Connection, rows: Sequence[Sequence[Any]]) -> list[Decision]:
    """Una :class:`~.model.Decision` por fila (columnas de ``_COLUMNS``), con sus enlaces."""
    links = _links(conn, list(dict.fromkeys(str(row[0]) for row in rows)))
    built: list[Decision] = []
    for uid, who, day, what, source, name, text, user, at in rows:
        keys, versions = links[str(uid)]
        built.append(Decision(
            str(uid), str(who), str(day), str(what), source, None if source is None else name,
            text, str(user), str(at), tuple(keys), tuple(v_uid for v_uid, _code in versions),
            tuple(code for _uid, code in versions),
        ))
    return built


def decisions(
    conn: sqlite3.Connection,
    *,
    parameter_key: str | None = None,
    version_uid: str | None = None,
) -> tuple[Decision, ...]:
    """Las decisiones de la propiedad del proyecto por el día de la decisión (y, en el mismo
    día, por el orden en que se registraron): todas; con ``parameter_key``, las enlazadas a esa
    clave; con ``version_uid`` (uid o código), las enlazadas a esa versión (ninguna si no
    existe), y con los dos, las enlazadas a ambos. Solo lee."""
    if not _has_tables(conn):
        return ()
    conditions: list[str] = []
    args: list[str] = []
    if parameter_key is not None:
        conditions.append(_LINKED)
        args += [PARAMETER, parameter_key]
    if version_uid is not None:
        version = read.version(conn, version_uid)
        if version is None:
            return ()
        conditions.append(_LINKED)
        args += [VERSION, version.uid]
    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    return tuple(_build(conn, conn.execute(_SELECT + where + _ORDER, tuple(args)).fetchall()))


def deciders(conn: sqlite3.Connection, keys: Iterable[str]) -> dict[str, tuple[Decision, ...]]:
    """Las decisiones de la propiedad de cada clave de parámetro de ``keys`` (sin repetir), en
    el orden de :func:`decisions` (la última, la más reciente): el decisor de la propiedad que
    Parámetros del proyecto muestra junto al suyo, en todos los ámbitos del parámetro. Una clave
    sin ninguna, con una tupla vacía. Solo lee."""
    wanted = _items(keys, "las claves de parámetro")
    found: dict[str, list[Decision]] = {key: [] for key in wanted}
    if not wanted or not _has_tables(conn):
        return {key: () for key in wanted}
    for chunk in _chunks(wanted):  # cada clave, en una sola consulta: ya en su orden
        marks = ", ".join("?" for _ in chunk)
        rows = conn.execute(
            f"SELECT l.item_uid, {_COLUMNS} FROM gb_decision_link AS l "
            "JOIN gb_decision AS d ON d.uid = l.decision_uid "
            "LEFT JOIN gb_input AS i ON i.uid = d.source_input_uid "
            f"WHERE l.item_kind = ? AND l.item_uid IN ({marks})" + _ORDER,
            (PARAMETER, *chunk),
        ).fetchall()
        for row, decision in zip(rows, _build(conn, [row[1:] for row in rows]), strict=True):
            found[str(row[0])].append(decision)
    return {key: tuple(found[key]) for key in wanted}

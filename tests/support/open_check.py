# SPDX-License-Identifier: GPL-3.0-or-later
"""La transacción final de la comprobación de apertura de antes de T65, la referencia de sus
pruebas (spec 008, T65; RF-008-58, RNF-008-12; plan 008 §5.4.6, paso 8).

Hasta T65, la transacción final registraba lo encontrado (con la caché por región de cada camino
que escribe) y, al final, rehacía la caché con la obsolescencia completa
(``stale.refresh_all``), unos 0,25 s con el volumen de D-13 en un solo tic. Desde T65 la
completa se calcula antes, por pasos y sin escribir, y la transacción escribe solo su diferencia
con la caché. Para compararlas sobre la misma base:

- :func:`as_before`: mientras dura, la comprobación de apertura es la de antes (sin el cálculo
  por pasos y con ``refresh_all`` al final de la transacción final, con la misma fecha);
- :func:`same_uids`: mientras dura, los uid nuevos son siempre los mismos, en el mismo orden
  (los de las operaciones y los eventos que registra la transacción final);
- :func:`project_rows`: todas las filas de todas las tablas de la base del proyecto (las de la
  caché ordenadas: no tienen orden de registro).

Solo fuera de Blender: importa el paquete de ``tests.support.package``.
"""

from __future__ import annotations

import dataclasses
import itertools
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from unittest import mock

from tests.support.package import import_geoblender

checks = import_geoblender("core.provenance.checks")
stale = import_geoblender("core.provenance.stale")
ids = import_geoblender("core.ids")
timeutil = import_geoblender("core.timeutil")

CACHE_TABLE = "gb_stale"


def _no_cache_steps(_settlement: Any, _registries: Any) -> Iterator[Any]:
    """Sin la obsolescencia completa por pasos (la transacción de antes no la usa)."""
    return object()
    yield  # un generador, como el de verdad


def _final_write(settlement: Any, conn: sqlite3.Connection, survey: Any, registries: Any,
                 _basis: Any) -> Any:
    """La transacción final de antes: lo encontrado y, al final, ``refresh_all`` con la fecha
    del principio de la transacción."""
    now = timeutil.format_utc(settlement.project.clock.now())
    written = settlement._record(conn, survey, registries, now, None)
    if survey is None or registries is None:
        return written
    return dataclasses.replace(written, cache=stale.refresh_all(
        conn, now=now, versions=registries.versions))


@contextmanager
def as_before() -> Iterator[None]:
    """Mientras dura, la comprobación de apertura con la transacción final de antes de T65."""
    with mock.patch.object(checks._Settlement, "_cache_steps", _no_cache_steps), \
            mock.patch.object(checks._Settlement, "_write", _final_write):
        yield


@contextmanager
def same_uids() -> Iterator[None]:
    """Mientras dura, los uid nuevos son 1, 2, 3… (UUID v4 válidos), siempre los mismos."""
    serial = itertools.count(1)
    fake = SimpleNamespace(uuid4=lambda: uuid.UUID(int=next(serial), version=4))
    with mock.patch.object(ids, "uuid", fake):
        yield


def project_rows(project: Any) -> dict[str, list[Any]]:
    """Todas las filas de todas las tablas de la base de ``project``, por tabla, en su orden de
    registro (las de la caché, ordenadas)."""
    with project.read() as conn:
        tables = [str(name) for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
        found = {table: conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
                 for table in tables}
    if CACHE_TABLE in found:
        found[CACHE_TABLE] = sorted(found[CACHE_TABLE])
    return found

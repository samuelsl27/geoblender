# SPDX-License-Identifier: GPL-3.0-or-later
"""La topografía en Blender (código ``gis``, spec 006; plan 006 §5.1, §5.3.4 y §5.6; ADR-0025
§2).

Hoy registra lo que la topografía declara a las specs 004 y 008, sin operadores todavía (T28 y
siguientes):

- sus **definiciones de parámetros** (``gis.params.DEFINITIONS``) en ``core.params``, para el
  panel de parámetros y para que cada operación resuelva los del proyecto (RF-008-01,
  RF-008-06; plan §5.6.1; T26);
- sus **lectores de contenido** (``gis.content``) en ``core.content``, con el lector de tablas de
  texto de ``interop`` (``gis`` no puede importarlo, ARQ-07; RF-006-26, RF-008-09; T40): así la
  lista estática del trabajo ``core_content_hash`` (``workers/core_content_hash.py``) coincide con
  lo que registra Blender;
- sus **tipos de trabajo** (``gis.jobs.WORKER_INFOS``) en ``jobs.catalog`` con
  ``register_worker`` (RF-006-28; plan §5.3.4; T26): ``jobs/`` no importa ``gis``.

:func:`register` pone lo que falta y apunta cómo quitarlo; :func:`unregister` lo quita en orden
inverso (lo que otro cambió después es suyo). Los dos son simétricos e idempotentes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ...core import params as core_params
from ...core.content import readers as content_readers
from ...gis import content, jobs
from ...gis import params as gis_params
from ...interop.csv_tables import read_table
from ...jobs import catalog as job_catalog

classes: tuple[type, ...] = ()
"""Los operadores de ``gis`` (aún ninguno)."""

MODULE = "gis"
"""El módulo de las definiciones de parámetros de la topografía."""

_UNDO: list[Callable[[], None]] = []


def register() -> None:
    """Registra las definiciones de parámetros, el lector de tablas, los lectores de contenido y
    los tipos de trabajo de ``gis`` que aún no están; idempotente."""
    missing = [defn for defn in gis_params.DEFINITIONS
               if defn.key not in core_params.DEFINITIONS]
    if missing:
        core_params.register_definitions(missing)
        _UNDO.append(_unregister_definitions)
    if content.table_reader() is None:
        content.use_table_reader(read_table)
        _UNDO.append(_forget_table_reader)
    for reader in content.CONTENT_READERS:
        if reader.id not in content_readers.READERS:
            content_readers.register_reader(reader)
            _UNDO.append(_unregister_if(content_readers.READERS, reader.id, reader,
                                        content_readers.unregister_reader))
    for info in jobs.WORKER_INFOS:
        if info.name not in job_catalog.WORKERS:
            job_catalog.register_worker(info)
            _UNDO.append(_unregister_if(job_catalog.WORKERS, info.name, info,
                                        job_catalog.unregister_worker))


def unregister() -> None:
    """Quita lo que puso :func:`register`, en orden inverso (lo que otro cambió después es
    suyo); idempotente."""
    while _UNDO:
        _UNDO.pop()()


def _unregister_if(view: Any, key: str, item: object,
                   remove: Callable[[str], object]) -> Callable[[], None]:
    def undo() -> None:
        if view.get(key) is item:  # si otro lo cambió, es suyo
            remove(key)

    return undo


def _unregister_definitions() -> None:
    core_params.unregister_definitions(MODULE)


def _forget_table_reader() -> None:
    if content.table_reader() is read_table:
        content.use_table_reader(None)

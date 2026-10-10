# SPDX-License-Identifier: GPL-3.0-or-later
"""Tipo de trabajo ``core_content_hash`` en un proceso aparte (spec 008; RF-008-09;
RNF-008-11; plan 008 §5.3.3; ADR-0025 §2).

Envoltorio: :func:`main` registra los lectores de contenido de su **lista estática de paquetes**
(:data:`READER_PACKAGES`: en el proceso aparte no hay ``bl`` que los registre) y llama a
``jobs.content_hash.run``, la misma función que ejecuta el hilo dentro de Blender, así que los
dos ejecutores calculan el mismo hash. Cada spec que declara lectores añade aquí su paquete (la
006, ``gis``; la 005, los suyos), y una prueba de ``tests/blender`` comprueba que la lista da
los mismos lectores que registra ``bl`` (los que pueden ir al trabajo, ``worker``).

No importa ``core.project`` ni ``bl`` (ARQ-11): solo lee la fuente que le dan por la línea de
órdenes.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType, ModuleType

from ..core.content import builtin as core_readers
from ..core.content.readers import READERS, ContentReader, register_reader
from ..jobs.content_hash import run

READER_PACKAGES: Mapping[str, ModuleType] = MappingProxyType({
    "core": core_readers,
})
"""Los paquetes con lectores de contenido que puede usar el trabajo, con el módulo donde cada
uno los declara (su ``CONTENT_READERS``)."""


def worker_readers() -> tuple[ContentReader, ...]:
    """Los lectores de la lista estática que pueden ir al trabajo (``worker``), en orden."""
    return tuple(found for module in READER_PACKAGES.values()
                 for found in module.CONTENT_READERS if found.worker)


def register_readers() -> None:
    """Registra los lectores de :func:`worker_readers` que aún no están (idempotente)."""
    for found in worker_readers():
        if found.id not in READERS:
            register_reader(found)


def main(ctx: object) -> Mapping[str, object]:
    """El trabajo en proceso aparte: los lectores de la lista y ``jobs.content_hash.run``."""
    register_readers()
    return run(ctx)  # type: ignore[arg-type]


__all__ = ["READER_PACKAGES", "main", "register_readers", "run", "worker_readers"]

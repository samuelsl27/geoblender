# SPDX-License-Identifier: GPL-3.0-or-later
"""Tipo de trabajo ``core_content_hash`` en un proceso aparte (spec 008; RF-008-09;
RNF-008-11; plan 008 §5.3.3; ADR-0025 §2).

Envoltorio: :func:`main` registra los lectores de contenido de su **lista estática de paquetes**
(:data:`READER_PACKAGES`: en el proceso aparte no hay ``bl`` que los registre) y llama a
``jobs.content_hash.run``, la misma función que ejecuta el hilo dentro de Blender, así que los
dos ejecutores calculan el mismo hash. Cada spec que declara lectores añade aquí su paquete (la
006, ``gis``; la 005, los suyos), y una prueba de ``tests/blender`` comprueba que la lista da
los mismos lectores que registra ``bl`` (los que pueden ir al trabajo, ``worker``).

Los de ``gis`` (spec 006, T40) leen el texto de puntos con ``interop.csv_tables``, que ``gis``
no puede importar (ARQ-07): :func:`register_readers` se lo da (``gis.content.
use_table_reader``), como ``bl/ops/gis.py`` en Blender. Importar ``gis`` cuesta unas décimas
de segundo: la lista lo importa al pedirlo y :func:`main` mira antes la cancelación, para que
un trabajo cancelado nada más lanzarse la atienda dentro de su plazo de gracia (RNF-008-11).

No importa ``core.project`` ni ``bl`` (ARQ-11): solo lee la fuente que le dan por la línea de
órdenes.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from types import ModuleType

from ..core.content import builtin as core_readers
from ..core.content.readers import READERS, ContentReader, register_reader
from ..interop.csv_tables import read_table
from ..jobs.content_hash import run


def _gis_readers() -> ModuleType:
    from ..gis import content  # al pedirlo: importar gis cuesta unas décimas (T40)

    return content


class _ReaderPackages(Mapping[str, ModuleType]):
    """La lista estática de paquetes con lectores: su nombre y cómo se carga el módulo donde
    los declara (se importa al pedirlo)."""

    def __init__(self, loaders: Mapping[str, Callable[[], ModuleType]]) -> None:
        self._loaders = dict(loaders)

    def __getitem__(self, name: str) -> ModuleType:
        return self._loaders[name]()

    def __iter__(self) -> Iterator[str]:
        return iter(self._loaders)

    def __len__(self) -> int:
        return len(self._loaders)


READER_PACKAGES: Mapping[str, ModuleType] = _ReaderPackages({
    "core": lambda: core_readers,
    "gis": _gis_readers,
})
"""Los paquetes con lectores de contenido que puede usar el trabajo, con el módulo donde cada
uno los declara (su ``CONTENT_READERS``)."""


def worker_readers() -> tuple[ContentReader, ...]:
    """Los lectores de la lista estática que pueden ir al trabajo (``worker``), en orden."""
    return tuple(found for module in READER_PACKAGES.values()
                 for found in module.CONTENT_READERS if found.worker)


def register_readers() -> None:
    """Da a los lectores de ``gis`` el lector de tablas de ``interop`` y registra los de
    :func:`worker_readers` que aún no están (idempotente)."""
    READER_PACKAGES["gis"].use_table_reader(read_table)
    for found in worker_readers():
        if found.id not in READERS:
            register_reader(found)


def main(ctx: object) -> Mapping[str, object]:
    """El trabajo en proceso aparte: mira la cancelación, registra los lectores de la lista y
    llama a ``jobs.content_hash.run``."""
    ctx.check_cancelled()  # type: ignore[attr-defined]
    register_readers()
    return run(ctx)  # type: ignore[arg-type]


__all__ = ["READER_PACKAGES", "main", "register_readers", "run", "worker_readers"]

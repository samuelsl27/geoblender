# SPDX-License-Identifier: GPL-3.0-or-later
"""Registro de declaraciones de procedencia en las pruebas (spec 008, T15; ADR-0025 §2; plan
008 §5.3.1).

Los registros de ``core.provenance.contract`` (tipos de operación, grupos acoplados, cifras e
importadores) son del proceso, como el de lectores de ``core.content``. :func:`registered`
registra unas declaraciones en orden y las quita al salir en orden inverso (como haría el
``unregister()`` de un módulo), y :func:`snapshot` da el estado de los cuatro registros para
comprobar que una prueba los deja como estaban. Lo usan las pruebas de la procedencia (T15 y
siguientes) y la demostración de la 008 (T39).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from tests.support.package import import_geoblender

contract = import_geoblender("core.provenance.contract")


def _unregister(declaration: Any) -> None:
    if isinstance(declaration, contract.OperationDef):
        contract.unregister_operation(declaration.op_type)
    elif isinstance(declaration, contract.CoupledGroupDef):
        contract.unregister_group(declaration.name)
    elif isinstance(declaration, contract.FigureDef):
        contract.unregister_figure(declaration.key)
    elif isinstance(declaration, contract.ImporterDef):
        contract.unregister_importer(declaration.reader_id)


def _register(declaration: Any) -> None:
    if isinstance(declaration, contract.OperationDef):
        contract.register_operation(declaration)
    elif isinstance(declaration, contract.CoupledGroupDef):
        contract.register_group(declaration)
    elif isinstance(declaration, contract.FigureDef):
        contract.register_figure(declaration)
    elif isinstance(declaration, contract.ImporterDef):
        contract.register_importer(declaration)
    else:
        raise TypeError(f"no es una declaración de procedencia: {declaration!r}")


@contextmanager
def registered(*declarations: Any) -> Iterator[None]:
    """Registra ``declarations`` en su orden (los tipos antes que su grupo) y, al salir, quita
    las que se registraron, en orden inverso. Si un registro falla, quita las anteriores y
    deja pasar el error."""
    done: list[Any] = []
    try:
        for declaration in declarations:
            _register(declaration)
            done.append(declaration)
        yield
    finally:
        for declaration in reversed(done):
            _unregister(declaration)


def snapshot() -> tuple[Mapping[str, Any], ...]:
    """Copia de los cuatro registros (operaciones, grupos, cifras e importadores), para
    comparar con ``==`` (mismas claves y los mismos objetos)."""
    return tuple(dict(view) for view in (contract.OPERATIONS, contract.GROUPS,
                                         contract.FIGURES, contract.IMPORTERS))

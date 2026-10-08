# SPDX-License-Identifier: GPL-3.0-or-later
"""Procedencia de parámetros, entradas, operaciones y cifras (spec 008; ADR-0025; plan 008
§5.1).

- :mod:`.schema`: las tablas internas del esquema 2 del GeoPackage del proyecto (no se
  reexporta: lo importa ``core.project.schema``).
- :mod:`.contract`: lo que declara cada módulo (:class:`OperationDef`,
  :class:`CoupledGroupDef`, :class:`FigureDef` e :class:`ImporterDef`), sus registros y las
  operaciones de ``core`` (:data:`CORE_OPERATIONS`).
- :mod:`.messages`: los mensajes de la procedencia (código, ``msgid`` en inglés y español) y
  :class:`ProvenanceError`.
- :mod:`.operations`: el registro de las operaciones en dos pasos (:func:`begin_operation`,
  :class:`OperationHandle` con ``claim_paths``, ``complete``, ``fail`` y ``cancel``,
  :func:`operation` y :func:`claimed_paths`) y las que su sesión no pudo terminar
  (:func:`interrupt_orphaned` y :func:`mark_not_ingested`).
- :mod:`.figures`: las cifras con tipo y procedencia (:class:`FigureSpec`,
  :func:`record_figure`, :class:`FigureRecord`) y el aviso de una cifra que calcula un
  parámetro con otro valor (:class:`Divergence`, :func:`divergence` y :func:`divergences`).

La API pública (cifras, grafo, comprobaciones…) se reexporta aquí a medida que existe (plan
008 §5.3.1). Nada de lo que se importe aquí puede importar ``core.project``:
``core.project.schema`` importa ``core.provenance.schema``, que pasa por este fichero.

Por lo mismo, lo de :mod:`.operations` y :mod:`.figures` (que traen ``core.datasets``,
``core.content`` y ``core.params``) se reexporta **al usarlo** (``__getattr__``, PEP 562), no
al importar el paquete: así abrir un proyecto no carga ni compila esos módulos (las pruebas
de Blender rehabilitan la extensión muchas veces desde cero, con ``-B``).
"""

from typing import Any

from .contract import (
    ACCEPT_REVIEW,
    CORE_OPERATIONS,
    EXTERNAL_EDIT,
    FIGURES,
    GROUPS,
    IMPORT_LAYER,
    IMPORTERS,
    OPERATIONS,
    SCOPES,
    CoupledGroupDef,
    FigureDef,
    ImporterDef,
    OperationDef,
    figure_def,
    group_def,
    importer_def,
    operation_def,
    parse_version,
    register_figure,
    register_group,
    register_importer,
    register_operation,
    unregister_figure,
    unregister_group,
    unregister_importer,
    unregister_operation,
)
from .messages import CATALOG_ES, LABELS, MESSAGES, Message, ProvenanceError, render

OPERATIONS_API: tuple[str, ...] = (
    "JOB_EXECUTORS",
    "Consumed",
    "Executor",
    "ItemKind",
    "OperationHandle",
    "OperationStatus",
    "Use",
    "begin_operation",
    "claimed_paths",
    "interrupt_orphaned",
    "mark_not_ingested",
    "operation",
)
"""Lo de :mod:`.operations` que se reexporta al usarlo."""

FIGURES_API: tuple[str, ...] = (
    "Divergence",
    "FigureRecord",
    "FigureSpec",
    "divergence",
    "divergences",
    "record_figure",
    "scope_key",
)
"""Lo de :mod:`.figures` que se reexporta al usarlo."""


def __getattr__(name: str) -> Any:
    if name in OPERATIONS_API:
        from . import operations as source
    elif name in FIGURES_API:
        from . import figures as source
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(source, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *OPERATIONS_API, *FIGURES_API})


__all__ = [
    "ACCEPT_REVIEW",
    "CATALOG_ES",
    "CORE_OPERATIONS",
    "EXTERNAL_EDIT",
    "FIGURES",
    "GROUPS",
    "IMPORTERS",
    "IMPORT_LAYER",
    "JOB_EXECUTORS",
    "LABELS",
    "MESSAGES",
    "OPERATIONS",
    "SCOPES",
    "Consumed",
    "CoupledGroupDef",
    "Divergence",
    "Executor",
    "FigureDef",
    "FigureRecord",
    "FigureSpec",
    "ImporterDef",
    "ItemKind",
    "Message",
    "OperationDef",
    "OperationHandle",
    "OperationStatus",
    "ProvenanceError",
    "Use",
    "begin_operation",
    "claimed_paths",
    "divergence",
    "divergences",
    "figure_def",
    "group_def",
    "importer_def",
    "interrupt_orphaned",
    "mark_not_ingested",
    "operation",
    "operation_def",
    "parse_version",
    "record_figure",
    "register_figure",
    "register_group",
    "register_importer",
    "register_operation",
    "render",
    "scope_key",
    "unregister_figure",
    "unregister_group",
    "unregister_importer",
    "unregister_operation",
]

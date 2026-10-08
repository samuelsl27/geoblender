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

La API pública (operaciones, cifras, grafo, comprobaciones…) se reexporta aquí a medida que
existe (plan 008 §5.3.1). Nada de lo que se importe aquí puede importar ``core.project``:
``core.project.schema`` importa ``core.provenance.schema``, que pasa por este fichero.
"""

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

__all__ = [
    "ACCEPT_REVIEW",
    "CATALOG_ES",
    "CORE_OPERATIONS",
    "EXTERNAL_EDIT",
    "FIGURES",
    "GROUPS",
    "IMPORTERS",
    "IMPORT_LAYER",
    "LABELS",
    "MESSAGES",
    "OPERATIONS",
    "SCOPES",
    "CoupledGroupDef",
    "FigureDef",
    "ImporterDef",
    "Message",
    "OperationDef",
    "ProvenanceError",
    "figure_def",
    "group_def",
    "importer_def",
    "operation_def",
    "parse_version",
    "register_figure",
    "register_group",
    "register_importer",
    "register_operation",
    "render",
    "unregister_figure",
    "unregister_group",
    "unregister_importer",
    "unregister_operation",
]

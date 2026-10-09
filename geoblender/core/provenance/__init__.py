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
  :func:`operation` y :func:`claimed_paths`), las que su sesión no pudo terminar
  (:func:`interrupt_orphaned` y :func:`mark_not_ingested`) y la incorporación de un trabajo
  de la 004 (:func:`ingest_job` con su :class:`JobOutcome` → :class:`IngestOutcome`).
- :mod:`.figures`: las cifras con tipo y procedencia (:class:`FigureSpec`,
  :func:`record_figure`, :class:`FigureRecord`) y el aviso de una cifra que calcula un
  parámetro con otro valor (:class:`Divergence`, :func:`divergence` y :func:`divergences`).
- :mod:`.graph`: el grafo por versiones (:func:`load_graph`, :class:`ProvenanceGraph`) y la
  obsolescencia deducida con sus causas (:func:`deduce`, :func:`stale_state`,
  :class:`Staleness`, :class:`Cause`).
- :mod:`.stale`: la caché ``gb_stale`` puesta al día por región en cada camino que escribe
  (:func:`refresh_region`) o completa (:func:`refresh_all`), los recuentos «! n obsoletos» y
  «⚠ n entradas» (:func:`counts`) y la lista de lo obsoleto (:func:`stale_items`).
- :mod:`.recompute`: el plan de «Recalcular lo obsoleto» (:func:`plan_recompute`,
  :class:`RecomputePlan`): unidades en orden de dependencia y lo que se deja fuera, con su
  motivo (:class:`Skipped`, :class:`SkipReason`); su ejecución por unidades
  (:func:`recompute_steps`, :class:`RecomputeRequest`, :class:`RecomputeOutcome`) y «dar por
  buena» una operación que espera revisión a mano (:func:`accept_review`).
- :mod:`.gate`: la puerta antes de operar (:func:`can_run` → :class:`Ready`,
  :class:`Blocked` o :class:`Pending`) y lo que la comprobación de apertura aún no ha
  comprobado (:class:`CheckState`).
- :mod:`.importer`: «Registrar como entrada» una capa de un GeoPackage (:func:`import_layer`,
  la operación ``core.import_layer``, con lo importado en ``core_imported_<slug>``) y
  «Actualizar» una entrada con el importador de su lector (:func:`reimport_input`; el de
  ``core``, :data:`CORE_IMPORTERS`), que pide los ajustes que ya no sirven
  (:class:`SettingsNeeded`, con su :class:`ReimportRequest`).
- :mod:`.lineage`: la procedencia de una cifra, un dato o una operación hasta sus entradas
  (``lineage.lineage`` → :class:`LineageTree`), las marcas de las cifras (:func:`figure_marks` →
  :class:`FigureMarks`), la cifra vigente de una clave y un ámbito (:func:`current_figure`) y
  cómo se presenta lo que se muestra (:func:`result_state` → :class:`ResultStatus`).

La API pública (cifras, grafo, comprobaciones…) se reexporta aquí a medida que existe (plan
008 §5.3.1). Nada de lo que se importe aquí puede importar ``core.project``:
``core.project.schema`` importa ``core.provenance.schema``, que pasa por este fichero.

Por lo mismo, lo de :mod:`.operations`, :mod:`.figures`, :mod:`.graph`, :mod:`.stale`,
:mod:`.recompute`, :mod:`.gate`, :mod:`.importer` y :mod:`.lineage` (que traen
``core.datasets``, ``core.content``, ``core.params`` y ``core.inputs``) se reexporta
**al usarlo** (``__getattr__``, PEP 562), no al importar el paquete: así abrir un proyecto no
carga ni compila esos módulos (las pruebas de Blender rehabilitan la extensión muchas veces
desde cero, con ``-B``).
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
    ReimportRequest,
    SettingsNeeded,
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
    "JOB_FINAL_STATES",
    "Consumed",
    "Executor",
    "IngestOutcome",
    "ItemKind",
    "JobOutcome",
    "OperationHandle",
    "OperationStatus",
    "OutputPrint",
    "Use",
    "begin_in_transaction",
    "begin_operation",
    "claimed_paths",
    "ingest_job",
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

GRAPH_API: tuple[str, ...] = (
    "Cause",
    "CauseKind",
    "ProvenanceGraph",
    "Staleness",
    "Version",
    "deduce",
    "load_graph",
    "stale_state",
)
"""Lo de :mod:`.graph` que se reexporta al usarlo."""

STALE_API: tuple[str, ...] = (
    "CacheUpdate",
    "Counts",
    "StaleItem",
    "StaleReport",
    "StaleRow",
    "counts",
    "refresh_all",
    "refresh_region",
    "stale_items",
)
"""Lo de :mod:`.stale` que se reexporta al usarlo."""

RECOMPUTE_API: tuple[str, ...] = (
    "RECOMPUTE_PHASE",
    "SCOPE_ALL",
    "OperationRef",
    "RecomputeHandle",
    "RecomputeOutcome",
    "RecomputePlan",
    "RecomputeRequest",
    "RecomputeUnit",
    "SkipReason",
    "Skipped",
    "UnitResult",
    "UnitStatus",
    "accept_review",
    "plan_recompute",
    "recompute_steps",
)
"""Lo de :mod:`.recompute` que se reexporta al usarlo."""

GATE_API: tuple[str, ...] = (
    "BlockKind",
    "BlockReason",
    "Blocked",
    "CheckState",
    "Choice",
    "Notice",
    "Pending",
    "PendingItem",
    "PendingReason",
    "Ready",
    "can_run",
    "choice_label",
)
"""Lo de :mod:`.gate` que se reexporta al usarlo."""

IMPORTER_API: tuple[str, ...] = (
    "CORE_IMPORTERS",
    "IMPORTED_PREFIX",
    "LayerImport",
    "import_layer",
    "imported_name",
    "reimport_input",
    "reimport_layer",
)
"""Lo de :mod:`.importer` que se reexporta al usarlo."""

LINEAGE_API: tuple[str, ...] = (
    "VIEW_STATES",
    "DatasetLink",
    "FigureMarks",
    "InputLink",
    "InputUse",
    "LineageKind",
    "LineageRow",
    "LineageTree",
    "Mark",
    "OperationLink",
    "ParameterLink",
    "ResultState",
    "ResultStatus",
    "current_figure",
    "figure_marks",
    "result_state",
)
"""Lo de :mod:`.lineage` que se reexporta al usarlo. Su función ``lineage`` no: es el nombre
del módulo (``core.provenance.lineage.lineage``), que el paquete tiene como atributo en cuanto
se importa."""


def __getattr__(name: str) -> Any:
    if name in OPERATIONS_API:
        from . import operations as source
    elif name in FIGURES_API:
        from . import figures as source
    elif name in GRAPH_API:
        from . import graph as source
    elif name in STALE_API:
        from . import stale as source
    elif name in RECOMPUTE_API:
        from . import recompute as source
    elif name in GATE_API:
        from . import gate as source
    elif name in IMPORTER_API:
        from . import importer as source
    elif name in LINEAGE_API:
        from . import lineage as source
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(source, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *OPERATIONS_API, *FIGURES_API, *GRAPH_API, *STALE_API,
                   *RECOMPUTE_API, *GATE_API, *IMPORTER_API, *LINEAGE_API})


__all__ = [
    "ACCEPT_REVIEW",
    "CATALOG_ES",
    "CORE_IMPORTERS",
    "CORE_OPERATIONS",
    "EXTERNAL_EDIT",
    "FIGURES",
    "GROUPS",
    "IMPORTED_PREFIX",
    "IMPORTERS",
    "IMPORT_LAYER",
    "JOB_EXECUTORS",
    "JOB_FINAL_STATES",
    "LABELS",
    "MESSAGES",
    "OPERATIONS",
    "RECOMPUTE_PHASE",
    "SCOPES",
    "SCOPE_ALL",
    "VIEW_STATES",
    "BlockKind",
    "BlockReason",
    "Blocked",
    "CacheUpdate",
    "Cause",
    "CauseKind",
    "CheckState",
    "Choice",
    "Consumed",
    "Counts",
    "CoupledGroupDef",
    "DatasetLink",
    "Divergence",
    "Executor",
    "FigureDef",
    "FigureMarks",
    "FigureRecord",
    "FigureSpec",
    "ImporterDef",
    "IngestOutcome",
    "InputLink",
    "InputUse",
    "ItemKind",
    "JobOutcome",
    "LayerImport",
    "LineageKind",
    "LineageRow",
    "LineageTree",
    "Mark",
    "Message",
    "Notice",
    "OperationDef",
    "OperationHandle",
    "OperationLink",
    "OperationRef",
    "OperationStatus",
    "OutputPrint",
    "ParameterLink",
    "Pending",
    "PendingItem",
    "PendingReason",
    "ProvenanceError",
    "ProvenanceGraph",
    "Ready",
    "RecomputeHandle",
    "RecomputeOutcome",
    "RecomputePlan",
    "RecomputeRequest",
    "RecomputeUnit",
    "ReimportRequest",
    "ResultState",
    "ResultStatus",
    "SettingsNeeded",
    "SkipReason",
    "Skipped",
    "StaleItem",
    "StaleReport",
    "StaleRow",
    "Staleness",
    "UnitResult",
    "UnitStatus",
    "Use",
    "Version",
    "accept_review",
    "begin_in_transaction",
    "begin_operation",
    "can_run",
    "choice_label",
    "claimed_paths",
    "counts",
    "current_figure",
    "deduce",
    "divergence",
    "divergences",
    "figure_def",
    "figure_marks",
    "group_def",
    "import_layer",
    "imported_name",
    "importer_def",
    "ingest_job",
    "interrupt_orphaned",
    "load_graph",
    "mark_not_ingested",
    "operation",
    "operation_def",
    "parse_version",
    "plan_recompute",
    "recompute_steps",
    "record_figure",
    "refresh_all",
    "refresh_region",
    "register_figure",
    "register_group",
    "register_importer",
    "register_operation",
    "reimport_input",
    "reimport_layer",
    "render",
    "result_state",
    "scope_key",
    "stale_items",
    "stale_state",
    "unregister_figure",
    "unregister_group",
    "unregister_importer",
    "unregister_operation",
]

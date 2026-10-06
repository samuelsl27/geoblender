# SPDX-License-Identifier: GPL-3.0-or-later
"""El proyecto ``.gbproj`` (spec 002; ADR-0006): esquema de su GeoPackage, cabecera,
cerrojo de un solo escritor, creación, apertura, migraciones, copia local y publicación.

Python puro (biblioteca estándar y numpy). API pública:

- :func:`create_project` y :class:`ProjectSettings` (crear, RF-002-01 a RF-002-03);
- :func:`inspect_project`, :func:`open_steps` y :func:`open_project` (abrir sin escribir,
  por pasos o de una vez, RF-002-04 a RF-002-10);
- :class:`Project` (el proyecto abierto: leer, escribir, marca del cerrojo, caché y
  cerrar), con su :class:`OpenMode` y, en solo lectura, su :class:`ReadOnlyCode`.
"""

from .create import CreateResult, create_project, prepare
from .events import EventKind
from .lock import LockCheck, LockInfo, LockMode, LockState, LockStatus
from .manifest import Manifest, ManifestStatus, read_manifest
from .model import (
    OpenMode,
    OpenResult,
    OpenStatus,
    ProjectRecord,
    ProjectSettings,
    Progress,
    ReadOnlyCode,
)
from .open import PHASES, ProjectInspection, inspect_project, open_project, open_steps
from .schema import MIN_READER_SCHEMA, SCHEMA_VERSION
from .session import Project

__all__ = [
    "MIN_READER_SCHEMA",
    "PHASES",
    "SCHEMA_VERSION",
    "CreateResult",
    "EventKind",
    "LockCheck",
    "LockInfo",
    "LockMode",
    "LockState",
    "LockStatus",
    "Manifest",
    "ManifestStatus",
    "OpenMode",
    "OpenResult",
    "OpenStatus",
    "Progress",
    "Project",
    "ProjectInspection",
    "ProjectRecord",
    "ProjectSettings",
    "ReadOnlyCode",
    "create_project",
    "inspect_project",
    "open_project",
    "open_steps",
    "prepare",
    "read_manifest",
]

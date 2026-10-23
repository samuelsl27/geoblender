# SPDX-License-Identifier: GPL-3.0-or-later
"""Reproducir una revisión congelada (spec 009; RF-009-11, RF-009-09; CE-009-02; plan 009 A9,
§5.3.3, D-4, D-32 y T9).

:func:`reproduce_steps` vuelve a ejecutar, **aparte del proyecto y sin cambiar nada de él** (ni un
fichero ni la base: ni eventos), las operaciones de una revisión congelada y dice qué coincide
con lo congelado:

0. **Antes, sin escribir nada** (al llamarla): la revisión existe, está congelada y no está
   marcada alterada; y hay espacio en la caché para lo que se va a escribir (lo que ocupan las
   copias congeladas de lo que se reproduce, más un 10 %, como la copia de la 002). Después,
   en sus primeros pasos, **todas sus huellas** (la comprobación entera de
   ``core.versions.check``, la de A8, sin registrar nada): si algo no coincide, se rechaza antes
   de empezar (RF-009-09).
1. En ``<caché del proyecto>/reproducir/<V10.r2>-<8 hex>/`` (:data:`REPRODUCE_DIR`; la caché se
   puede borrar y no se copia ni se publica), cada operación congelada **en orden** (el de su
   registro), y cada una **con sus entradas y sus parámetros congelados**, no con lo reproducido
   aguas arriba (D-32: una diferencia se atribuye a quien la produce y no se arrastra):

   - de un tipo con función de reproducir (``OperationDef.reproduce``, plan §5.3.3): se le da un
     :class:`ReproduceRequest` con sus ajustes, sus entradas congeladas (:class:`FrozenInput`,
     de solo lectura: el fichero de la instantánea que guarda ese contenido, de esta revisión o
     de otra; lo importado de una tabla del proyecto, copiado antes por pasos a
     ``entradas.gpkg`` de esa carpeta, para no leer la base del proyecto mientras se trabaja;
     un fichero importado, en su sitio), los parámetros que usó (la fila de su historial: valor
     y unidad), su carpeta de trabajo y el registro del proyecto (su CRS); devuelve sus pasos
     (``Progress``) y el último lleva el :class:`ReproducedResult`. Si consumió un contenido
     que no se congeló (un obsoleto aceptado al congelar), «no reproducible»; si la función
     falla, también, con lo que dijo;
   - de un tipo sin ella (importaciones, ediciones a mano) o de un módulo que no está: se toma
     lo congelado y el informe lo dice (:class:`Why`).

2. **Comparar**: cada salida de la operación (las que anotó, por su papel), con el lector y el
   normalizador **de su dato** (ADR-0024 §6), ¿el mismo hash de contenido? Cada cifra
   congelada de la operación (por su clave y su ámbito), ¿el mismo valor, o dentro de la
   tolerancia que declara su tipo (``OperationDef.figure_tolerance``)? Si no, la causa probable
   (:func:`probable_cause`): otra versión del algoritmo, de Geoblender o de una biblioteca; si
   nada cambió, «sin causa conocida».
3. **El informe** (:class:`ReproduceReport`), en el último paso y en JSON (``informe.json``,
   sin rutas absolutas) en esa carpeta, con lo reproducido. Para trabajar a partir de una
   revisión, una versión nueva que parte de ella (D-4).

Cerrar los pasos antes del final (Esc), ``cancelled`` o un fallo propio (el disco) no dejan nada
en la caché (la carpeta de trabajo y las que creó). Python puro (ADR-0004).
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
from collections.abc import Callable, Generator, Iterable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import KW_ONLY, dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from ..content import readers
from ..datasets.model import (
    DATASET_DECLARATIONS,
    RECORD_COLUMNS,
    DatasetRecord,
    DatasetStatus,
    Store,
)
from ..errors import GeoblenderError
from ..georef.crs import load_catalog
from ..gpkg import base as gpkg_base
from ..gpkg.connection import GpkgConnection
from ..hashing import canonical_json
from ..ids import short_uid
from ..params.store import decode_value
from ..paths import check_path_length
from ..project import copytree
from ..project.manifest import PROJECT_STORE
from ..project.model import Progress
from ..provenance.contract import OPERATIONS, OperationDef, Tolerance
from ..provenance.figures import FigureSpec, ScopeValue, scope_json
from ..timeutil import format_utc
from ..units import convert
from ..version import geoblender_version
from . import check
from .copy import _existing, _Meter, _Pacer, _size_text, _Table, _Workspace
from .freeze import GPKG_BASE_BYTES
from .model import ItemKind, ItemPart, ItemState, RevisionState, VersionError, render

if TYPE_CHECKING:
    from ..georef.crs import CrsRef, VerticalRef
    from ..params.model import ParamValue
    from ..project.model import ProjectRecord
    from ..timeutil import Clock

STEP_BUDGET_S = 0.05
"""El trabajo entre dos progresos (como el modal de la 010); los pasos de dentro (un trozo de un
lector, unas filas, un paso de la función de un módulo) se agrupan hasta este tiempo."""
CHECK_PHASE = check.PHASE
PHASES: tuple[str, ...] = (CHECK_PHASE, "entradas", "reproducción", "comparación", "informe")
"""Las fases (``Progress.phase``): las huellas, las entradas de cada operación, su
reproducción, la comparación con lo congelado y el informe."""
REPRODUCE_DIR = "reproducir"
"""La carpeta de las reproducciones en la caché del proyecto (``reproducir/V10.r2-<8 hex>/``)."""
REPORT_NAME = "informe.json"
"""El informe, en la carpeta de cada reproducción."""
INPUTS_NAME = "entradas.gpkg"
"""Las tablas de ``project.gpkg`` que consumió lo que se reproduce, copiadas (sin selector)."""
REPORT_FORMAT = "geoblender-reproduction"
REPORT_SCHEMA = 1
UNUSABLE: frozenset[DatasetStatus] = frozenset(
    {DatasetStatus.MISSING, DatasetStatus.BLOCKED, DatasetStatus.DAMAGED})
"""Los estados de lo importado del proyecto que no se puede leer como entrada."""

_LABEL = re.compile(r"(V[0-9]{2,})\.r([1-9][0-9]*)")
_CHUNK = 500
_OBJ = "Reproducción"
_W_CHECK, _W_INPUTS, _W_RUN, _W_COMPARE, _W_REPORT = 10, 2, 10, 5, 1
"""El peso de cada parte en el avance."""

_T = TypeVar("_T")


class ReproduceProject(Protocol):
    """Lo que usa la reproducción del proyecto (``core.project.Project``): su raíz, su registro
    (el CRS), el reloj, una conexión de lectura y su caché."""

    @property
    def root(self) -> Path: ...

    record: ProjectRecord | None
    clock: Clock

    def read(self) -> AbstractContextManager[sqlite3.Connection]: ...

    def cache_dir(self) -> Path: ...


# --- Lo que da y recibe la función de reproducir de un módulo (plan §5.3.3) -----------------


@dataclass(frozen=True)
class FrozenInput:
    """Un contenido congelado que consumió la operación, de solo lectura: su papel en ella, el
    tipo, el lector y el normalizador de su dato, sus ficheros (``"main"``, como los de un
    lector), los ajustes para leerlo (``{"layer": …}`` en un GeoPackage) y su hash de contenido;
    además, el uid, el nombre y el CRS (EPSG) de su dato."""

    role: str
    kind: str
    reader: str
    normalizer: str
    files: Mapping[str, Path]
    settings: Mapping[str, Any]
    content_sha256: str
    _: KW_ONLY
    uid: str = ""
    name: str = ""
    crs_epsg: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "files", MappingProxyType(
            {str(key): Path(value) for key, value in self.files.items()}))
        object.__setattr__(self, "settings", MappingProxyType(dict(self.settings)))


@dataclass(frozen=True)
class ReproduceRequest:
    """Lo que recibe la función de reproducir de un tipo (``OperationDef.reproduce``): el tipo,
    sus ajustes (los de la operación congelada, una copia), sus entradas congeladas
    (:class:`FrozenInput`), sus parámetros congelados (clave → (valor, unidad), de la fila del
    historial que usó), una carpeta de trabajo vacía en la caché, donde escribe lo que
    reproduce, y el registro del proyecto (sus referencias: :meth:`references`). No recibe el
    proyecto ni escribe en él; si lanza un trabajo de la 004, le pasa las entradas como a
    cualquiera (copias o arrays). Además, el uid de la operación y la versión de su algoritmo
    con que se registró."""

    op_type: str
    settings: Mapping[str, Any]
    inputs: tuple[FrozenInput, ...]
    params: Mapping[str, tuple[ParamValue | None, str]]
    workdir: Path
    record: ProjectRecord
    _: KW_ONLY
    operation_uid: str = ""
    op_version: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "settings", MappingProxyType(dict(self.settings)))
        object.__setattr__(self, "inputs", tuple(self.inputs))
        object.__setattr__(self, "params", MappingProxyType(dict(self.params)))
        object.__setattr__(self, "workdir", Path(self.workdir))

    def input(self, role: str) -> FrozenInput:
        """La entrada congelada con el papel ``role``; :class:`ValueError` si no hay una sola."""
        found = [item for item in self.inputs if item.role == role]
        if len(found) != 1:
            raise ValueError(f"«{self.op_type}» tiene {len(found)} entradas con el papel "
                             f"«{role}»: se pide una")
        return found[0]

    def references(self) -> tuple[CrsRef, VerticalRef]:
        """El CRS horizontal y la referencia vertical del proyecto, del catálogo de la 002."""
        catalog = load_catalog()
        crs = catalog.horizontal(self.record.crs_epsg)
        if self.record.vcrs_epsg is None:
            return crs, catalog.local_vertical(self.record.vcrs_note)
        return crs, catalog.vertical(self.record.vcrs_epsg)


@dataclass(frozen=True)
class ReproducedOutput:
    """Una salida reproducida: el papel con que la anotó la operación, el lector con que la
    escribe el módulo (se compara con el lector y el normalizador **de su dato**, ADR-0024 §6),
    sus ficheros (en la carpeta de trabajo) y los ajustes para leerla (``{"layer": …}``)."""

    role: str
    reader: str
    files: Mapping[str, Path]
    settings: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "files", MappingProxyType(
            {str(key): Path(value) for key, value in self.files.items()}))
        object.__setattr__(self, "settings", MappingProxyType(dict(self.settings)))


@dataclass(frozen=True)
class ReproducedResult:
    """Lo que da la función de reproducir en su último paso: sus salidas, sus cifras
    (``FigureSpec``, como al registrarlas) y, si las declara su tipo, la versión de cada
    biblioteca con que se reprodujo (para la causa de lo que no coincide)."""

    outputs: tuple[ReproducedOutput, ...] = ()
    figures: tuple[FigureSpec, ...] = ()
    _: KW_ONLY
    software: Mapping[str, str] = field(default_factory=dict)


# --- El informe ------------------------------------------------------------------------------


class Why(StrEnum):
    """Por qué no se reproduce una operación: se toma lo congelado (una importación, una
    edición a mano, un tipo sin función de reproducir, un tipo cuyo módulo no está) o es «no
    reproducible» (consumió un contenido que no se congeló; la función falló)."""

    IMPORT = "import"
    MANUAL = "manual"
    TYPE = "type"
    MODULE = "module"
    UNFROZEN = "unfrozen"
    FAILED = "failed"

    @property
    def taken(self) -> bool:
        """Verdadero si se toma lo congelado (no es un fallo de la reproducción)."""
        return self in _TAKEN


_TAKEN = frozenset({Why.IMPORT, Why.MANUAL, Why.TYPE, Why.MODULE})
_WHY_CODES: Mapping[Why, str] = MappingProxyType({
    Why.IMPORT: "core.version_reproduce_why_import",
    Why.MANUAL: "core.version_reproduce_why_manual",
    Why.TYPE: "core.version_reproduce_why_type",
    Why.MODULE: "core.version_reproduce_why_module",
    Why.UNFROZEN: "core.version_reproduce_why_unfrozen",
    Why.FAILED: "core.version_reproduce_why_failed",
})


@dataclass(frozen=True)
class Cause:
    """La causa probable de que algo no coincida: sus partes (código del catálogo y valores),
    en los dos idiomas con :meth:`text`."""

    parts: tuple[tuple[str, Mapping[str, str]], ...]

    def text(self, language: str = "es") -> str:
        """«des.pit 1.2 instalada, congelada con 1.1; numpy 2.5.3 instalada, …»."""
        return "; ".join(render(code, language=language, **values)
                         for code, values in self.parts)

    def as_json(self) -> list[dict[str, Any]]:
        return [{"code": code, "values": dict(values)} for code, values in self.parts]


def _cause(code: str, **values: str) -> Cause:
    return Cause(((code, MappingProxyType(values)),))


@dataclass(frozen=True, slots=True)
class OperationNote:
    """Una operación que no se reproduce: su uid, su tipo, por qué (:class:`Why`) y, si falló,
    lo que dijo."""

    operation_uid: str
    op_type: str
    why: Why
    reason: str | None = None

    def text(self, language: str = "es") -> str:
        """«des.sketch, edición a mano», «des.pit: consumió un contenido que no se
        congeló»…"""
        return render(_WHY_CODES[self.why], language=language, op_type=self.op_type,
                      reason=self.reason)

    def as_json(self) -> dict[str, Any]:
        return {"operation_uid": self.operation_uid, "op_type": self.op_type,
                "why": str(self.why), "reason": self.reason, "text": self.text("es")}


@dataclass(frozen=True, slots=True)
class OutputCheck:
    """Una salida comparada: su dato (uid y nombre), el hash de contenido congelado (el que
    anotó la operación) y el reproducido (``None`` si no se reprodujo o no se pudo leer), si
    coinciden y, si no, la causa probable; de qué operación y con qué papel."""

    dataset_uid: str
    name: str
    frozen_sha256: str
    reproduced_sha256: str | None
    same: bool
    cause: Cause | None
    _: KW_ONLY
    operation_uid: str
    op_type: str
    role: str

    def as_json(self) -> dict[str, Any]:
        return {"operation_uid": self.operation_uid, "op_type": self.op_type,
                "role": self.role, "dataset_uid": self.dataset_uid, "name": self.name,
                "frozen_sha256": self.frozen_sha256,
                "reproduced_sha256": self.reproduced_sha256, "same": self.same,
                "cause": None if self.cause is None else self.cause.as_json()}


@dataclass(frozen=True, slots=True)
class FigureCheck:
    """Una cifra comparada: su clave y su ámbito, el valor congelado y el reproducido (en la
    unidad de la congelada; ``None`` si no se dio), la unidad, la tolerancia de su tipo, si
    coinciden y, si no, la causa probable; de qué operación y su uid."""

    key: str
    scope: Mapping[str, ScopeValue]
    frozen: float
    reproduced: float | None
    unit: str
    tolerance: Tolerance | None
    same: bool
    cause: Cause | None
    _: KW_ONLY
    operation_uid: str
    op_type: str
    figure_uid: str

    @property
    def name(self) -> str:
        """Su clave y los valores de su ámbito («res.sellable_t · 1»)."""
        shown = ", ".join(str(value) for value in self.scope.values())
        return f"{self.key} · {shown}" if shown else self.key

    def as_json(self) -> dict[str, Any]:
        tolerance = None if self.tolerance is None else {
            "relative": self.tolerance.relative, "absolute": self.tolerance.absolute}
        return {"operation_uid": self.operation_uid, "op_type": self.op_type,
                "figure_uid": self.figure_uid, "key": self.key, "scope": dict(self.scope),
                "frozen": self.frozen, "reproduced": self.reproduced, "unit": self.unit,
                "tolerance": tolerance, "same": self.same,
                "cause": None if self.cause is None else self.cause.as_json()}


@dataclass(frozen=True)
class ReproduceReport:
    """El informe de una reproducción (véase el módulo): la revisión («V10.r2») y su uid, las
    salidas y las cifras comparadas, lo que se tomó de lo congelado, lo no reproducible, cuándo
    empezó y acabó, la carpeta de la caché donde quedó (``None`` si se canceló) y si se
    canceló."""

    revision: str
    outputs: tuple[OutputCheck, ...]
    figures: tuple[FigureCheck, ...]
    taken_frozen: tuple[OperationNote, ...]
    not_reproducible: tuple[OperationNote, ...]
    started_at: str
    finished_at: str
    _: KW_ONLY
    revision_uid: str
    folder: Path | None
    cancelled: bool = False

    @property
    def matches(self) -> bool:
        """Verdadero si se reprodujo entera y todo coincide: ninguna salida ni cifra distinta y
        nada «no reproducible»."""
        return (not self.cancelled and not self.not_reproducible
                and all(item.same for item in (*self.outputs, *self.figures)))

    def text(self, language: str = "es") -> str:
        """«V10.r2 reproducida: coinciden 5 de 5 salidas y 12 de 12 cifras; 1 operación tomada
        de lo congelado (des.sketch, edición a mano)»; con lo que no coincide, «… «des_final»
        no coincide: des.pit 1.2 instalada, congelada con 1.1»."""
        if self.cancelled:
            return render("core.version_reproduce_cancelled", language=language)
        parts = [render(
            "core.version_reproduce_summary", language=language, revision=self.revision,
            outputs=sum(item.same for item in self.outputs), outputs_total=len(self.outputs),
            figures=sum(item.same for item in self.figures), figures_total=len(self.figures))]
        for item in (*self.outputs, *self.figures):
            if not item.same:
                parts.append(render("core.version_reproduce_differs", language=language,
                                    name=item.name, cause=None if item.cause is None
                                    else item.cause.text(language)))
        for notes, code in ((self.taken_frozen, "core.version_reproduce_taken"),
                            (self.not_reproducible, "core.version_reproduce_not_reproducible")):
            if notes:
                parts.append(render(code if len(notes) > 1 else f"{code}_one",
                                    language=language, count=len(notes),
                                    names="; ".join(note.text(language) for note in notes)))
        return "; ".join(parts)

    def as_json(self) -> dict[str, Any]:
        """Como se guarda en ``informe.json`` (sin rutas absolutas)."""
        return {
            "format": REPORT_FORMAT, "schema": REPORT_SCHEMA, "revision": self.revision,
            "revision_uid": self.revision_uid, "geoblender_version": geoblender_version(),
            "started_at": self.started_at, "finished_at": self.finished_at,
            "cancelled": self.cancelled, "matches": self.matches,
            "outputs": [item.as_json() for item in self.outputs],
            "figures": [item.as_json() for item in self.figures],
            "taken_frozen": [note.as_json() for note in self.taken_frozen],
            "not_reproducible": [note.as_json() for note in self.not_reproducible],
            "text": self.text("es"),
        }


def probable_cause(op_type: str, *, frozen_version: str, installed_version: str,
                   frozen_geoblender: str, frozen_software: Mapping[str, str],
                   software: Mapping[str, str] | None = None) -> Cause:
    """La causa probable de que una salida o una cifra de ``op_type`` no coincida (plan A9
    (3)): otra versión de su algoritmo (la instalada frente a la congelada), otra de Geoblender
    o, de cada biblioteca que anotó la operación (``gb_operation.software``), otra versión con
    que se reprodujo (``software``); si nada cambió, «sin causa conocida»."""
    parts: list[tuple[str, Mapping[str, str]]] = []
    if installed_version != frozen_version:
        parts.append(("core.version_cause_algorithm", MappingProxyType({
            "op_type": op_type, "installed": installed_version, "frozen": frozen_version})))
    installed = geoblender_version()
    if frozen_geoblender != installed:
        parts.append(("core.version_cause_geoblender", MappingProxyType({
            "installed": installed, "frozen": frozen_geoblender})))
    now = {} if software is None else dict(software)
    for library in sorted(frozen_software):
        found = now.get(library)
        if found is not None and str(found) != str(frozen_software[library]):
            parts.append(("core.version_cause_library", MappingProxyType({
                "library": library, "installed": str(found),
                "frozen": str(frozen_software[library])})))
    if not parts:
        parts.append(("core.version_cause_unknown", MappingProxyType({})))
    return Cause(tuple(parts))


# --- El plan: lo que se reproduce y de dónde salen sus entradas ----------------------------


@dataclass(frozen=True)
class _Source:
    """Dónde está el contenido congelado que consumió una operación: un fichero de una
    instantánea o del proyecto (``path``, relativa al proyecto, y su capa si es un GeoPackage)
    o una tabla de ``project.gpkg`` que hay que copiar (``copy``)."""

    role: str
    record: DatasetRecord
    content_sha256: str
    path: str
    layer: str | None
    copy: bool = False


@dataclass(frozen=True)
class _Output:
    dataset_uid: str
    role: str
    content_sha256: str
    record: DatasetRecord | None


@dataclass(frozen=True)
class _Figure:
    uid: str
    key: str
    value: float
    unit: str
    scope: Mapping[str, ScopeValue]
    scope_json: str


@dataclass(frozen=True)
class _Op:
    uid: str
    op_type: str
    op_version: str
    settings: str
    geoblender_version: str
    software: Mapping[str, str]
    definition: OperationDef | None
    sources: tuple[_Source, ...]
    params: Mapping[str, tuple[Any, str]]
    outputs: tuple[_Output, ...]
    figures: tuple[_Figure, ...]
    note: OperationNote | None


@dataclass(frozen=True)
class _Plan:
    revision_uid: str
    label: str
    operations: tuple[_Op, ...]
    checked: tuple[str, ...]  # las revisiones cuyas huellas se comprueban antes
    space: int

    @property
    def reproduced(self) -> tuple[_Op, ...]:
        return tuple(op for op in self.operations if op.note is None)


_REVISION = (
    "SELECT r.uid, v.code, r.number, r.state, r.altered_at, r.altered_detail FROM gb_revision "
    "AS r CROSS JOIN gb_version AS v ON v.uid = r.version_uid WHERE r.uid = ?"
)
_REVISION_BY_LABEL = (
    "SELECT r.uid, v.code, r.number, r.state, r.altered_at, r.altered_detail FROM gb_version "
    "AS v CROSS JOIN gb_revision AS r ON r.version_uid = v.uid WHERE v.code = ? AND r.number = ?"
)
_ITEMS = (  # por el índice único de (revision_uid, item_kind, item_uid)
    "SELECT item_kind, item_uid, part, state, content_sha256, snapshot_path, snapshot_layer, "
    "file_size FROM gb_revision_item WHERE revision_uid = ? ORDER BY fid"
)
_OPERATIONS = (
    "SELECT fid, uid, op_type, op_version, settings, geoblender_version, software "
    "FROM gb_operation WHERE uid IN ({marks})"
)
_IO = (  # por el índice único de (operation_uid, direction, …)
    "SELECT operation_uid, direction, item_kind, item_uid, content_sha256, role "
    "FROM gb_operation_io WHERE operation_uid IN ({marks}) ORDER BY fid"
)
_PARAMS = (  # por el índice único de (operation_uid, parameter_uid)
    "SELECT operation_uid, key, value, unit FROM gb_operation_param "
    "WHERE operation_uid IN ({marks}) ORDER BY fid"
)
_DATASETS = f"SELECT {', '.join(RECORD_COLUMNS)} FROM gb_dataset WHERE uid IN ({{marks}})"
_FIGURES = (  # por el uid único de gb_figure
    "SELECT uid, operation_uid, key, value, unit, scope FROM gb_figure WHERE uid IN ({marks}) "
    "ORDER BY fid"
)
_COPIED = (  # por gb_revision_item_copy: el contenido copiado en otra congelada no alterada
    "SELECT i.revision_uid, i.snapshot_path, i.snapshot_layer FROM gb_revision_item AS i "
    "CROSS JOIN gb_revision AS r ON r.uid = i.revision_uid "
    "CROSS JOIN gb_dataset AS d ON d.uid = i.item_uid "
    "WHERE i.content_sha256 = ? AND i.copied AND i.item_kind = 'dataset' "
    "AND r.state = 'frozen' AND r.altered_at IS NULL AND d.reader = ? AND d.normalizer = ? "
    "ORDER BY i.fid LIMIT 1"
)
_TABLE = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'gb_revision'"


def _select(conn: sqlite3.Connection, sql: str, values: Iterable[str]) -> list[tuple[Any, ...]]:
    items = list(dict.fromkeys(values))
    found: list[tuple[Any, ...]] = []
    for start in range(0, len(items), _CHUNK):
        chunk = items[start:start + _CHUNK]
        found.extend(conn.execute(sql.format(marks=", ".join("?" for _ in chunk)), chunk))
    return found


def detail_text(detail: str | None, language: str = "es") -> str:
    """Lo que no coincide de una marca ``altered_detail`` guardada, como texto en ``language``
    («rasters/des_final_v10.tif: otro tamaño; V10.r2.gpkg: falta»; «?» si no se puede leer):
    el ``what`` del rechazo ``core.version_reproduce_altered``, también para la interfaz (T23)."""
    try:
        entries = json.loads(detail) if detail else []
    except ValueError:
        entries = []
    shown: list[str] = []
    for entry in entries if isinstance(entries, list) else ():
        try:
            item = check.Mismatch(str(entry["path"]), check.Problem(entry["problem"]),
                                  entry.get("dataset_uid"))
        except (KeyError, TypeError, ValueError):
            continue
        shown.append(item.text(language))
    return "; ".join(shown) or "?"


def _find(conn: sqlite3.Connection, ref: str) -> tuple[Any, ...]:
    """La revisión ``ref`` (uid o «V10.r2»), sin escribir nada; ``VersionError`` si no está,
    no está congelada o está marcada alterada."""
    row = None
    if conn.execute(_TABLE).fetchone() is not None:
        row = conn.execute(_REVISION, (ref,)).fetchone()
        match = _LABEL.fullmatch(ref)
        if row is None and match is not None:
            row = conn.execute(_REVISION_BY_LABEL, (match[1], int(match[2]))).fetchone()
    if row is None:
        raise VersionError("core.version_reproduce_unknown", field="revisión", value=ref,
                           revision=ref)
    uid, code, number, state, altered_at, detail = row
    label = f"{code}.r{number}"
    if state != RevisionState.FROZEN.value:
        raise VersionError("core.version_reproduce_not_frozen", field="revisión", value=label,
                           version=str(code), revision=label)
    if altered_at is not None:
        raise VersionError("core.version_reproduce_altered", field="revisión", value=label,
                           version=str(code), revision=label, what=detail_text(detail))
    return str(uid), label


class _Planner:
    """Lo que se reproduce de una revisión, leído en una instantánea de la base."""

    def __init__(self, project: ReproduceProject, conn: sqlite3.Connection) -> None:
        self.project = project
        self.conn = conn
        self.others: dict[str, None] = {}
        self.sizes: dict[str, int] = {}

    def plan(self, ref: str) -> _Plan:
        uid, label = _find(self.conn, ref)
        items: dict[tuple[str, str], tuple[Any, ...]] = {}
        for row in self.conn.execute(_ITEMS, (uid,)):
            items[(str(row[0]), str(row[1]))] = row
        op_uids = [item_uid for kind, item_uid in items if kind == ItemKind.OPERATION.value]
        rows = sorted(_select(self.conn, _OPERATIONS, op_uids), key=lambda row: int(row[0]))
        io: dict[str, list[tuple[Any, ...]]] = {}
        for row in _select(self.conn, _IO, op_uids):
            io.setdefault(str(row[0]), []).append(row)
        params: dict[str, dict[str, tuple[Any, str]]] = {}
        for op_uid, key, value, unit in _select(self.conn, _PARAMS, op_uids):
            params.setdefault(str(op_uid), {})[str(key)] = (decode_value(value), str(unit))
        records = {record.uid: record for record in (
            DatasetRecord.from_row(tuple(row)) for row in _select(
                self.conn, _DATASETS, [str(row[3]) for rows_ in io.values() for row in rows_
                                       if row[2] == "dataset"]))}
        figures: dict[str, list[_Figure]] = {}
        for figure_uid, op_uid, key, value, unit, scope in _select(
                self.conn, _FIGURES,
                [item_uid for kind, item_uid in items if kind == ItemKind.FIGURE.value]):
            if value is None:
                continue
            parsed = json.loads(scope) if scope else {}
            figures.setdefault(str(op_uid), []).append(_Figure(
                str(figure_uid), str(key), float(value), str(unit), MappingProxyType(parsed),
                scope_json(parsed)))
        operations = []
        for _fid, op_uid, op_type, op_version, settings, software_version, software in rows:
            op_uid = str(op_uid)
            state = items[(ItemKind.OPERATION.value, op_uid)][3]
            uses = [row for row in io.get(op_uid, ()) if row[1] == "in"]
            outputs = tuple(_Output(str(row[3]), str(row[5]), str(row[4]),
                                    records.get(str(row[3])))
                            for row in io.get(op_uid, ()) if row[1] == "out"
                            and row[2] == "dataset")
            definition = OPERATIONS.get(str(op_type))
            why = self._why(definition, uses, outputs)
            sources: list[_Source] = []
            if why is None:
                if state == ItemState.NOT_REPRODUCIBLE.value:
                    why = Why.UNFROZEN
                for row in uses:
                    source = (None if row[2] != "dataset" or why is not None
                              else self._source(items, records.get(str(row[3])), str(row[4]),
                                                str(row[5])))
                    if source is None:
                        why = Why.UNFROZEN
                        break
                    sources.append(source)
            operations.append(_Op(
                op_uid, str(op_type), str(op_version), str(settings), str(software_version),
                MappingProxyType(json.loads(software) if software else {}), definition,
                tuple(sources), MappingProxyType(params.get(op_uid, {})), outputs,
                tuple(figures.get(op_uid, ())),
                None if why is None else OperationNote(op_uid, str(op_type), why)))
            if why is None:
                self._size(items, outputs)
        space = sum(self.sizes.values())
        return _Plan(uid, label, tuple(operations), (uid, *self.others),
                     space + int(space * copytree.SPACE_MARGIN + 0.5) if space else 0)

    @staticmethod
    def _why(definition: OperationDef | None, uses: Sequence[tuple[Any, ...]],
             outputs: Sequence[_Output]) -> Why | None:
        """Por qué se toma lo congelado de una operación (``None``: se reproduce)."""
        if definition is None:
            return Why.MODULE
        if definition.reproduce is not None:
            return None
        if any(row[2] == "input" for row in uses) or any(
                output.record is not None and output.record.immutable for output in outputs):
            return Why.IMPORT
        return Why.TYPE if definition.repeatable else Why.MANUAL

    def _source(self, items: Mapping[tuple[str, str], tuple[Any, ...]],
                record: DatasetRecord | None, content: str, role: str) -> _Source | None:
        """Dónde está el contenido ``content`` que consumió la operación con ``role``: en una
        instantánea (la de esta revisión o la que la referencia) o, si es lo importado y sigue
        en el proyecto, en él; ``None`` si no se congeló en ninguna parte."""
        if record is None or record.store is Store.DUCKDB:
            return None
        item = items.get((ItemKind.DATASET.value, record.uid))
        if item is not None and item[4] == content and item[5] is not None:
            return _Source(role, record, content, str(item[5]),
                           None if item[6] is None else str(item[6]))
        if item is None or item[4] != content or item[2] != ItemPart.IMMUTABLE.value:
            row = self.conn.execute(_COPIED, (content, record.reader, record.normalizer)
                                    ).fetchone()
            if row is not None:
                self.others[str(row[0])] = None
                return _Source(role, record, content, str(row[1]),
                               None if row[2] is None else str(row[2]))
        if (record.immutable and record.content_sha256 == content
                and record.status not in UNUSABLE):
            if record.store is Store.GPKG:
                return _Source(role, record, content, PROJECT_STORE, record.locator, copy=True)
            return _Source(role, record, content, record.locator, None)
        return None

    def _size(self, items: Mapping[tuple[str, str], tuple[Any, ...]],
              outputs: Sequence[_Output]) -> None:
        """Lo que ocupará lo reproducido: lo que ocupan las copias congeladas de sus salidas
        (cada fichero una vez) o su fichero en el proyecto; un GeoPackage, al menos su base."""
        for output in outputs:
            item = items.get((ItemKind.DATASET.value, output.dataset_uid))
            record = output.record
            if item is not None and item[5] is not None and item[7] is not None:
                self.sizes[str(item[5])] = int(item[7])
            elif record is not None and record.tracked_size is not None:
                self.sizes[record.locator] = int(record.tracked_size)
            if record is not None and record.store is Store.GPKG:
                self.sizes.setdefault(f"{output.dataset_uid}.gpkg", GPKG_BASE_BYTES)


def _plan(project: ReproduceProject, ref: str) -> _Plan:
    with project.read() as conn:
        conn.execute("BEGIN")  # todo en una instantánea de la base
        try:
            return _Planner(project, conn).plan(ref)
        finally:
            conn.execute("ROLLBACK")


# --- Reproducir ---------------------------------------------------------------------------


def _budget(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"el presupuesto de un paso es un número de segundos, no {value!r}")
    if not value > 0:
        raise ValueError(f"el presupuesto de un paso es positivo, no {value!r}")
    return float(value)


def _failed(label: str, exc: BaseException | str, file: str) -> VersionError:
    reason = exc if isinstance(exc, str) else (
        getattr(exc, "strerror", None) or str(exc) or type(exc).__name__)
    return VersionError("core.version_reproduce_failed", field="fichero", value=file,
                        revision=label, reason=reason)


def _check_space(plan: _Plan, cache: Path, disk_usage: copytree.DiskUsageFn) -> None:
    if not plan.space:
        return
    try:
        free = int(disk_usage(_existing(cache)).free)
    except OSError as exc:
        raise _failed(plan.label, exc, str(cache)) from exc
    if free < plan.space:
        raise VersionError("core.version_reproduce_no_space", field="espacio libre", value=free,
                           revision=plan.label, needed=_size_text(plan.space),
                           folder=str(cache), free=_size_text(free))


def reproduce_steps(project: ReproduceProject, revision_uid: str, *,
                    budget_s: float = STEP_BUDGET_S,
                    cancelled: Callable[[], bool] | None = None,
                    disk_usage: copytree.DiskUsageFn = shutil.disk_usage) -> Iterator[Progress]:
    """Reproduce la revisión congelada ``revision_uid`` (su uid o su etiqueta, «V10.r2») del
    proyecto: véase el módulo. Los pasos son ``Progress`` en las fases :data:`PHASES` (cada ``budget_s`` s de
    trabajo y, siempre, uno al empezar cada operación: «Reproduciendo V10.r2: «des.pit» (2 de
    5)…»); el último lleva el :class:`ReproduceReport`. ``cancelled()``, si se consulta
    verdadero tras un paso, cancela como cerrar los pasos (Esc) pero termina con un informe
    cancelado; ``disk_usage``, el de ``shutil`` (inyectable). No escribe nada en el proyecto.

    Al llamarla, sin escribir nada: ``VersionError`` si la revisión no está
    (``core.version_reproduce_unknown``), no está congelada (``…_not_frozen``), está marcada
    alterada (``…_altered``) o no hay espacio en la caché (``…_no_space``); :class:`TypeError`
    o :class:`ValueError` con un argumento mal dado. En sus pasos, antes de reproducir nada,
    ``core.version_reproduce_altered`` si alguna huella no coincide, y
    ``core.version_reproduce_failed`` con un error del disco (sin dejar nada)."""
    if not isinstance(revision_uid, str) or not revision_uid:
        raise TypeError(f"la revisión se indica por su uid o su etiqueta («V10.r2»), no "
                        f"{revision_uid!r}")
    budget = _budget(budget_s)
    if cancelled is not None and not callable(cancelled):
        raise TypeError(f"«cancelled» es una función sin argumentos, no {cancelled!r}")
    plan = _plan(project, revision_uid)
    cache = Path(project.cache_dir())
    _check_space(plan, cache, disk_usage)
    return _Run(project, plan, cache, budget).steps(cancelled)


class _Run:
    """Una reproducción en marcha (véase el módulo)."""

    def __init__(self, project: ReproduceProject, plan: _Plan, cache: Path,
                 budget: float) -> None:
        self.project = project
        self.plan = plan
        self.root = Path(project.root)
        self.cache = cache
        self.pacer = _Pacer(budget)
        self.budget = budget
        count = len(plan.reproduced)
        self.meter = _Meter(_W_CHECK + count * (_W_INPUTS + _W_RUN + _W_COMPARE) + _W_REPORT)
        self.started_at = format_utc(project.clock.now())
        self.workdir: Path | None = None
        self.copied: dict[tuple[str, str], str] = {}
        self.identifiers: set[str] = set()

    def progress(self, phase: str, message: str, result: object | None = None) -> Progress:
        return Progress(phase, self.meter.done, self.meter.total, message, result)

    def steps(self, cancelled: Callable[[], bool] | None) -> Iterator[Progress]:
        body = self._body()
        stopped = False
        try:
            for step in body:
                yield step
                if step.result is None and cancelled is not None and cancelled():
                    stopped = True
                    break
        finally:
            body.close()  # a medias, no queda nada
        if stopped:
            report = ReproduceReport(self.plan.label, (), (), (), (), self.started_at,
                                     format_utc(self.project.clock.now()),
                                     revision_uid=self.plan.revision_uid, folder=None,
                                     cancelled=True)
            yield self.progress(PHASES[-1], report.text("es"), report)

    def _paced(self, inner: Iterator[Any], phase: str, message: str) -> Generator[Progress]:
        """Lleva ``inner`` y da el progreso cuando toca (``message``)."""
        for _step in inner:
            if self.pacer.due():
                yield self.progress(phase, message)
                self.pacer.restart()

    def _body(self) -> Generator[Progress]:
        plan = self.plan
        finished = False
        workspace: _Workspace | None = None
        current = plan.label
        try:
            yield from self._check()
            try:
                workspace = self._workspace()
                assert self.workdir is not None
                notes: dict[str, OperationNote] = {op.uid: op.note for op in plan.operations
                                                   if op.note is not None}
                outputs: list[OutputCheck] = []
                figures: list[FigureCheck] = []
                count = len(plan.reproduced)
                for index, op in enumerate(plan.reproduced, 1):
                    current = op.op_type
                    yield self.progress(PHASES[2], render(
                        "core.version_reproduce_progress", revision=plan.label,
                        op_type=op.op_type, index=index, count=count))
                    self.pacer.restart()
                    inputs = yield from self._inputs(op)
                    workdir = self.workdir / f"{index:02d}_{op.op_type.replace('.', '_')}"
                    check_path_length(workdir, folder=True, obj=_OBJ)
                    workdir.mkdir()
                    outcome = yield from self._reproduce(op, inputs, workdir)
                    self.meter.finish(_W_RUN)
                    if isinstance(outcome, OperationNote):
                        notes[op.uid] = outcome
                        self.meter.finish(_W_COMPARE)
                        continue
                    found = yield from self._outputs(op, outcome)
                    outputs.extend(found)
                    figures.extend(self._figures(op, outcome))
                    self.meter.finish(_W_COMPARE)
                current = REPORT_NAME
                ordered = [notes[op.uid] for op in plan.operations if op.uid in notes]
                report = ReproduceReport(
                    plan.label, tuple(outputs), tuple(figures),
                    tuple(note for note in ordered if note.why.taken),
                    tuple(note for note in ordered if not note.why.taken), self.started_at,
                    format_utc(self.project.clock.now()), revision_uid=plan.revision_uid,
                    folder=self.workdir)
                (self.workdir / REPORT_NAME).write_bytes(canonical_json(report.as_json()))
            except (OSError, sqlite3.Error) as exc:
                raise _failed(plan.label, exc, current) from exc
            self.meter.finish(_W_REPORT)
            finished = True
            yield self.progress(PHASES[4], report.text("es"), report)
        finally:
            if not finished and workspace is not None:
                workspace.clean()

    def _check(self) -> Generator[Progress]:
        """Todas las huellas de la revisión (y de las que guardan lo que consumió), por pasos;
        ``VersionError`` si alguna no coincide (RF-009-09). No registra nada."""
        findings: tuple[check.SnapshotFinding, ...] = ()
        for step in check.full_steps(self.project, list(self.plan.checked),
                                     budget_s=self.budget):
            if step.result is not None:
                findings = step.result  # type: ignore[assignment]
            fraction = step.done / step.total if step.total else 0.0
            yield Progress(CHECK_PHASE, self.meter.at(_W_CHECK, fraction), self.meter.total,
                           step.message)
        self.meter.finish(_W_CHECK)
        self.pacer.restart()
        found = {finding.revision_uid: finding for finding in findings}
        for uid in self.plan.checked:
            finding = found.get(uid)
            if finding is None:
                raise _failed(self.plan.label, "no se ha podido leer su instantánea",
                              self.plan.label)
            if finding.altered:
                raise VersionError(
                    "core.version_reproduce_altered", field="revisión", value=finding.label,
                    revision=finding.label,
                    what="; ".join(item.text("es") for item in finding.what))

    def _workspace(self) -> _Workspace:
        """La carpeta de esta reproducción en la caché (y las que le falten), vacía."""
        base = self.cache / REPRODUCE_DIR
        while True:
            workdir = base / f"{self.plan.label}-{short_uid()}"
            if not workdir.exists():
                break
        check_path_length(workdir / INPUTS_NAME, obj=_OBJ)
        workspace = _Workspace(workdir, workdir / INPUTS_NAME, self.project.clock, [])
        workspace.make(workdir)
        self.workdir = workdir
        return workspace

    def _inputs(self, op: _Op) -> Generator[Progress, None, tuple[FrozenInput, ...]]:
        """Las entradas congeladas de ``op``: las tablas de ``project.gpkg``, copiadas antes a
        ``entradas.gpkg`` (una vez cada contenido); lo demás, en su sitio."""
        assert self.workdir is not None
        found: list[FrozenInput] = []
        for source in op.sources:
            record = source.record
            if source.copy:
                layer = yield from self._copy_table(source)
                files = {"main": self.workdir / INPUTS_NAME}
                settings: dict[str, Any] = {"layer": layer}
            else:
                files = {"main": self.root.joinpath(*source.path.split("/"))}
                settings = {} if source.layer is None else {"layer": source.layer}
            found.append(FrozenInput(source.role, record.kind, record.reader, record.normalizer,
                                     files, settings, source.content_sha256, uid=record.uid,
                                     name=record.name, crs_epsg=record.crs_epsg))
        self.meter.finish(_W_INPUTS)
        return tuple(found)

    def _copy_table(self, source: _Source) -> Generator[Progress, None, str]:
        """Copia la tabla de ``project.gpkg`` de ``source`` (sus filas, sin selector: el mismo
        contenido, D-29) a ``entradas.gpkg``, por pasos cortos sin retener la base del
        proyecto; devuelve su nombre allí."""
        assert self.workdir is not None
        record = source.record
        key = (record.uid, source.content_sha256)
        if key in self.copied:
            return self.copied[key]
        if self.project.record is None:  # pragma: no cover - se reproduce con la base
            raise ValueError("el proyecto se abrió solo con su cabecera")
        path = self.workdir / INPUTS_NAME
        created = not path.exists()
        with GpkgConnection.open_write(path, create=created) as build:
            if created:
                with build.transaction() as conn:
                    gpkg_base.create_base(conn, load_catalog().horizontal(
                        self.project.record.crs_epsg))
            with self.project.read() as conn_source:
                table = _Table.describe(conn_source, record, record.locator)
                if table is None:
                    raise _failed(self.plan.label, f"no está la tabla «{record.locator}»",
                                  record.locator)
                with build.transaction() as conn:
                    table.create(conn, conn_source, self.identifiers)
                yield from self._paced(table.rows(conn_source, build), PHASES[1],
                                       f"Copiando «{record.name}»…")
        self.copied[key] = record.locator
        return record.locator

    def _reproduce(self, op: _Op, inputs: tuple[FrozenInput, ...], workdir: Path
                   ) -> Generator[Progress, None, ReproducedResult | OperationNote]:
        """La función de reproducir de ``op`` con lo congelado; su resultado o, si falla o no
        lo da, la nota «no reproducible» con lo que dijo."""
        assert op.definition is not None and op.definition.reproduce is not None
        if self.project.record is None:  # pragma: no cover - se reproduce con la base
            raise ValueError("el proyecto se abrió solo con su cabecera")
        result: ReproducedResult | None = None
        try:
            request = ReproduceRequest(
                op.op_type, json.loads(op.settings), inputs, op.params, workdir,
                self.project.record, operation_uid=op.uid, op_version=op.op_version)
            produced = op.definition.reproduce(request)
            if isinstance(produced, ReproducedResult):
                result = produced
            else:
                steps = iter(produced)
                try:
                    for step in steps:
                        if isinstance(getattr(step, "result", None), ReproducedResult):
                            result = step.result
                        if self.pacer.due():
                            message = getattr(step, "message", None)
                            yield self.progress(PHASES[2], message if isinstance(message, str)
                                                else op.op_type)
                            self.pacer.restart()
                finally:
                    close = getattr(steps, "close", None)
                    if close is not None:
                        close()
        except Exception as exc:  # la función de un módulo: su fallo va al informe
            reason = str(exc) or type(exc).__name__
            return OperationNote(op.uid, op.op_type, Why.FAILED, reason)
        if result is None:
            return OperationNote(op.uid, op.op_type, Why.FAILED,
                                 "no ha dado su resultado (ReproducedResult)")
        return result

    def _cause(self, op: _Op, result: ReproducedResult) -> Cause:
        assert op.definition is not None
        return probable_cause(op.op_type, frozen_version=op.op_version,
                              installed_version=op.definition.version,
                              frozen_geoblender=op.geoblender_version,
                              frozen_software=op.software, software=result.software)

    def _outputs(self, op: _Op, result: ReproducedResult
                 ) -> Generator[Progress, None, list[OutputCheck]]:
        """Cada salida de ``op`` (por su papel) frente a lo reproducido, con el lector y el
        normalizador de su dato."""
        pending = list(result.outputs)
        checks: list[OutputCheck] = []
        for output in op.outputs:
            produced = next((item for item in pending if item.role == output.role), None)
            name = output.dataset_uid if output.record is None else output.record.name
            sha: str | None = None
            cause: Cause | None = None
            if produced is None or output.record is None:
                cause = _cause("core.version_cause_missing", op_type=op.op_type)
            else:
                pending.remove(produced)
                try:
                    sha = yield from self._hash(output.record, produced)
                except (GeoblenderError, OSError, ValueError, TypeError,
                        sqlite3.Error) as exc:
                    cause = _cause("core.version_cause_unreadable",
                                   reason=str(exc) or type(exc).__name__)
            same = sha is not None and sha == output.content_sha256
            if not same and cause is None:
                cause = self._cause(op, result)
            checks.append(OutputCheck(output.dataset_uid, name, output.content_sha256, sha,
                                      same, None if same else cause, operation_uid=op.uid,
                                      op_type=op.op_type, role=output.role))
        return checks

    def _hash(self, record: DatasetRecord, produced: ReproducedOutput
              ) -> Generator[Progress, None, str]:
        content_reader = readers.reader(record.reader)
        request = content_reader.request(record.kind, DATASET_DECLARATIONS, produced.files,
                                         produced.settings, normalizer=record.normalizer)
        steps = readers.read_steps(content_reader, request)
        try:
            yield from self._paced(steps, PHASES[3], f"Comprobando «{record.name}»…")
        finally:
            steps.close()  # type: ignore[attr-defined]
        return request.hasher.digest().content_sha256

    def _figures(self, op: _Op, result: ReproducedResult) -> list[FigureCheck]:
        """Cada cifra congelada de ``op`` (por su clave y su ámbito) frente a la reproducida,
        exacta o dentro de la tolerancia de su tipo."""
        assert op.definition is not None
        tolerance = op.definition.figure_tolerance
        checks: list[FigureCheck] = []
        for frozen in op.figures:
            spec = next((item for item in result.figures if _same_figure(item, frozen)), None)
            value: float | None = None
            cause: Cause | None = None
            if spec is None or spec.value is None:
                cause = _cause("core.version_cause_missing", op_type=op.op_type)
            else:
                try:
                    value = float(spec.value)
                    if spec.unit is not None and spec.unit != frozen.unit:
                        value = float(convert(value, spec.unit, frozen.unit))
                except (GeoblenderError, TypeError, ValueError) as exc:
                    cause = _cause("core.version_cause_unreadable",
                                   reason=str(exc) or type(exc).__name__)
            same = cause is None and value is not None and _within(frozen.value, value,
                                                                   tolerance)
            if not same and cause is None:
                cause = self._cause(op, result)
            checks.append(FigureCheck(frozen.key, frozen.scope, frozen.value, value,
                                      frozen.unit, tolerance, same, None if same else cause,
                                      operation_uid=op.uid, op_type=op.op_type,
                                      figure_uid=frozen.uid))
        return checks


def _same_figure(spec: FigureSpec, frozen: _Figure) -> bool:
    if spec.key != frozen.key:
        return False
    try:
        return scope_json(spec.scope) == frozen.scope_json
    except (TypeError, ValueError):
        return False


def _within(frozen: float, reproduced: float, tolerance: Tolerance | None) -> bool:
    """Si ``reproduced`` es ``frozen``: igual o, con ``tolerance``, a no más de su parte
    relativa del congelado o de su parte absoluta (la mayor)."""
    if reproduced == frozen:
        return True
    if tolerance is None:
        return False
    return abs(reproduced - frozen) <= max(tolerance.relative * abs(frozen), tolerance.absolute)

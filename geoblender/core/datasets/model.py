# SPDX-License-Identifier: GPL-3.0-or-later
"""Qué es un dato del proyecto (spec 008; RF-008-17, RF-008-52; ADR-0024 §6; ADR-0025 §4 y
§6; plan 008 §5.2.1 y §5.3.1).

Un **dato del proyecto** es lo que una operación consume o produce y queda guardado en el
proyecto: una capa o una tabla de ``project.gpkg``, una rejilla de ``rasters/``, una malla de
``meshes/``, un original de ``originals/``, un modelo de ``blocks.duckdb`` o un entregable de
``exports/``. Su fila de ``gb_dataset`` lo registra con nombre estable, módulo dueño, tipo,
ubicación, su lector y su normalizador (para siempre, ADR-0024 §6), su hash de contenido y la
operación que escribió su contenido actual (RF-008-17; la importación, en lo importado de una
entrada).

- :class:`DatasetSpec`: lo que declara el módulo al escribir un dato (lo recibe
  ``OperationHandle.complete``, T17), comprobado al crearlo: un dato mal declarado es un error
  del programa (``ValueError`` o ``TypeError``) y no llega a registrarse.
- :class:`DatasetRecord`: una fila de ``gb_dataset``.
- :class:`DatasetStatus` y :data:`LIVE_STATUSES`: los seis estados y los «vivos», que ocupan
  su nombre (un nombre, un dato vivo; I-9).
- :class:`Store`, :data:`UNTRACKED_STORES` y :data:`FILE_STORES`: dónde vive.
- :data:`DATASET_DECLARATIONS`: un dato del proyecto se hashea **sin declaraciones** (su CRS,
  si lo tiene, va en sus datos: la cabecera de la rejilla, el CRS de la capa, el ``meta`` de
  la malla); así el registro vuelve a calcular su hash con su lector y su normalizador sin
  saber nada más de él.

**Ubicación** (``locator``): en ``gpkg``, el nombre exacto de la tabla en ``gpkg_contents``;
en los almacenes de ficheros, la ruta relativa a la raíz del proyecto con «/», dentro de la
carpeta de su almacén (``rasters/gis_dtm_proyecto.tif``; ninguna ruta absoluta en el
proyecto, ADR-0006 §5); en ``duckdb``, el modelo o el campo (``bm_12``, ``bm_12.au_ok``).

**Selector** (solo en ``gpkg``): ``{"column": c, "equals": v}``, las filas de una entrada en
una tabla común (lo importado de cada entrada), o ``{"column": c, "of": "current_inputs"}``,
las filas de las entradas vigentes (el dato acumulado; plan 008 §5.4.8). Se guarda como JSON
canónico; sin selector, ``''``.

Python puro (ADR-0004): no importa ``core.provenance`` (que importará este paquete); sus
estados se comprueban contra el esquema en las pruebas.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import KW_ONLY, dataclass, field
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Any

from ..catalog.schema import MODULE_CODES
from ..content.encoder import ContentDigest
from ..hashing import canonical_json


class DatasetStatus(StrEnum):
    """El estado de un dato (``gb_dataset.status``)."""

    CURRENT = "current"  # vigente
    SUPERSEDED = "superseded"  # sustituido: lo importado de una entrada actualizada
    DISCARDED = "discarded"  # descartado con su entrada (RF-008-55)
    MISSING = "missing"  # falta: fichero borrado o tabla eliminada (RF-008-57)
    BLOCKED = "blocked"  # editado fuera sin ser editable a mano (RF-008-56)
    DAMAGED = "damaged"  # lo importado cambió o perdió su protección (ADR-0025 §4)


LIVE_STATUSES: tuple[DatasetStatus, ...] = (
    DatasetStatus.CURRENT,
    DatasetStatus.MISSING,
    DatasetStatus.BLOCKED,
    DatasetStatus.DAMAGED,
)
"""Los estados que ocupan el nombre del dato (índice ``gb_dataset_name_active``)."""
FINAL_STATUSES: tuple[DatasetStatus, ...] = (DatasetStatus.SUPERSEDED, DatasetStatus.DISCARDED)
"""Los estados de los que un dato ya no sale: queda como historia, con su contenido."""


class Store(StrEnum):
    """Dónde vive un dato (``gb_dataset.store``)."""

    GPKG = "gpkg"  # una capa o tabla de project.gpkg
    RASTERS = "rasters"  # rejillas GeoTIFF de rasters/
    MESHES = "meshes"  # mallas npz de meshes/
    DUCKDB = "duckdb"  # modelos de bloques de blocks.duckdb
    ORIGINALS = "originals"  # originales de las entradas (RF-008-53)
    EXPORTS = "exports"  # entregables de exports/


UNTRACKED_STORES: tuple[Store, ...] = (Store.DUCKDB, Store.EXPORTS)
"""Los almacenes sin seguimiento (``tracked = 0``): los entregables no son entradas de nada,
y los modelos de bloques no se comprueban hasta R-22 (ADR-0025 §6)."""
FILE_STORES: tuple[Store, ...] = (Store.RASTERS, Store.MESHES, Store.ORIGINALS, Store.EXPORTS)
"""Los almacenes de ficheros: su ubicación es una ruta relativa dentro de su carpeta."""
DATASET_KINDS: tuple[str, ...] = (
    "vector",
    "raster",
    "mesh",
    "table",
    "drillholes",
    "point_cloud",
    "block_model",
    "block_field",
    "report",
    "document",
)
"""Los tipos de un dato (``gb_dataset.kind``)."""
DATASET_DECLARATIONS: Mapping[str, Any] = MappingProxyType({})
"""Las declaraciones del hash de contenido de un dato del proyecto: ninguna."""
CURRENT_INPUTS = "current_inputs"
"""``{"column": c, "of": "current_inputs"}``: las filas de las entradas vigentes."""

_NAME_TAIL = re.compile(r"[a-z0-9_]+")
_READER_ID = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+@[1-9][0-9]*")
_ROLE = re.compile(r"[a-z][a-z0-9_]*")


def _text(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"«{name}» de un dato es un texto, no {value!r}")
    return value


def _check_name(name: str, module: str) -> None:
    prefix = f"{module}_"
    if not name.startswith(prefix) or _NAME_TAIL.fullmatch(name[len(prefix):]) is None:
        raise ValueError(
            f"el nombre de un dato es «<módulo>_<nombre>» en minúsculas, cifras y «_», con el "
            f"código de su módulo («{prefix}…»), no {name!r}"
        )


def _check_locator(store: Store, locator: str) -> None:
    if not locator or locator != locator.strip():
        raise ValueError(f"la ubicación de un dato no puede estar vacía ni con espacios a los "
                         f"lados: {locator!r}")
    if store not in FILE_STORES:
        return
    path = PurePosixPath(locator)
    windows = PureWindowsPath(locator)
    parts = path.parts
    if (
        "\\" in locator
        or path.is_absolute()
        or windows.drive
        or windows.is_absolute()
        or len(parts) < 2
        or parts[0] != str(store)
        or any(part in ("", ".", "..") for part in locator.split("/"))
    ):
        raise ValueError(
            f"la ubicación de un dato de «{store}» es una ruta relativa a la raíz del proyecto, "
            f"con «/» y dentro de «{store}/» («{store}/<fichero>»), no {locator!r}"
        )


def _check_selector(store: Store, selector: object) -> dict[str, Any] | None:
    if selector is None or selector == "":
        return None
    if not isinstance(selector, Mapping):
        raise TypeError(f"el selector de un dato es un diccionario, no {selector!r}")
    if store is not Store.GPKG:
        raise ValueError(f"solo un dato de una tabla del GeoPackage tiene selector, no uno de "
                         f"«{store}»")
    found = dict(selector)
    keys = set(found)
    column = found.get("column")
    if keys == {"column", "equals"}:
        value = found["equals"]
        valid = isinstance(value, str | int) and not isinstance(value, bool)
    elif keys == {"column", "of"}:
        valid = found["of"] == CURRENT_INPUTS
    else:
        valid = False
    if not valid or not isinstance(column, str) or not column:
        raise ValueError(
            'el selector es {"column": <columna>, "equals": <texto o entero>} (lo importado de '
            'una entrada) o {"column": <columna>, "of": "current_inputs"} (las entradas '
            f"vigentes), no {found!r}"
        )
    return found


@dataclass(frozen=True)
class DatasetSpec:
    """Lo que declara un módulo al escribir un dato del proyecto (plan 008 §5.3.1):

    - ``name``: nombre estable, ``<módulo>_<nombre>`` (``gis_dtm_proyecto``); un nombre tiene
      como mucho un dato vivo, y lo sustituido o descartado conserva el suyo;
    - ``module``: código del módulo dueño (``core.catalog.schema.MODULE_CODES``);
    - ``kind``: de :data:`DATASET_KINDS`; ``store`` (:class:`Store`) y ``locator`` (véase el
      módulo);
    - ``reader``: el lector con versión (``"core.gpkg_layer@1"``) con que se hashea;
    - ``role``: su papel en la operación que lo escribe (``"terrain"``, ``"imported"``…;
      ``gb_operation_io.role``): por él se resuelve el sucesor de lo sustituido;
    - ``selector``: ``None`` o el de una tabla común (véase el módulo);
    - ``content``: el :class:`~geoblender.core.content.ContentDigest` que calculó el módulo
      (con ``reader`` y sin declaraciones) o ``None``: entonces lo calcula el registro con el
      lector del dato (en ``gpkg``, en la transacción que lo escribe);
    - ``crs_epsg``: el código EPSG de su CRS, si lo tiene (para mostrarlo);
    - ``input_uid`` e ``immutable``: lo importado de una entrada (RF-008-52), que no admite
      contenido nuevo y queda protegido; ``immutable`` exige ``input_uid``;
    - ``qgis_editable``: su módulo lo declara editable a mano en QGIS (RF-008-56);
    - ``detail``: lo que el módulo cuenta del cambio (los elementos afectados, RF-005-22), en
      JSON; se guarda en ``gb_dataset_change.detail``.
    """

    name: str
    module: str
    kind: str
    store: Store
    locator: str
    _: KW_ONLY
    reader: str
    role: str
    selector: Mapping[str, Any] | None = None
    content: ContentDigest | None = None
    crs_epsg: int | None = None
    input_uid: str | None = None
    immutable: bool = False
    qgis_editable: bool = False
    detail: Any = None
    selector_json: str = field(init=False, repr=False)
    detail_json: str | None = field(init=False, repr=False)

    def __post_init__(self) -> None:
        name = _text("name", self.name)
        module = _text("module", self.module)
        if module not in MODULE_CODES:
            raise ValueError(f"módulo desconocido {module!r}: es uno de {', '.join(MODULE_CODES)}")
        _check_name(name, module)
        kind = _text("kind", self.kind)
        if kind not in DATASET_KINDS:
            raise ValueError(f"tipo de dato desconocido {kind!r}: es uno de "
                             f"{', '.join(DATASET_KINDS)}")
        try:
            store = Store(_text("store", self.store))
        except ValueError:
            raise ValueError(
                f"almacén desconocido {self.store!r}: es uno de {', '.join(Store)}"
            ) from None
        object.__setattr__(self, "store", store)
        _check_locator(store, _text("locator", self.locator))
        if _READER_ID.fullmatch(_text("reader", self.reader)) is None:
            raise ValueError(f"el lector de un dato lleva su versión («core.gpkg_layer@1»), "
                             f"no {self.reader!r}")
        if _ROLE.fullmatch(_text("role", self.role)) is None:
            raise ValueError(f"el papel de un dato es un nombre en minúsculas («terrain»), no "
                             f"{self.role!r}")
        selector = _check_selector(store, self.selector)
        object.__setattr__(self, "selector", None if selector is None
                           else MappingProxyType(selector))
        object.__setattr__(self, "selector_json", "" if selector is None
                           else canonical_json(selector).decode("utf-8"))
        if self.content is not None:
            if not isinstance(self.content, ContentDigest):
                raise TypeError(f"el hash de un dato es un ContentDigest, no {self.content!r}")
            if self.content.reader != self.reader:
                raise ValueError(
                    f"el hash de «{name}» lo dio el lector «{self.content.reader}», no el suyo "
                    f"(«{self.reader}»)"
                )
        if self.crs_epsg is not None:
            if isinstance(self.crs_epsg, bool) or not isinstance(self.crs_epsg, int):
                raise TypeError(f"el CRS de un dato es un código EPSG entero, no "
                                f"{self.crs_epsg!r}")
            if self.crs_epsg <= 0:
                raise ValueError(f"código EPSG no válido: {self.crs_epsg}")
        if self.input_uid is not None and not _text("input_uid", self.input_uid).strip():
            raise ValueError("la entrada de lo importado no puede quedar vacía")
        for flag in ("immutable", "qgis_editable"):
            if not isinstance(getattr(self, flag), bool):
                raise TypeError(f"«{flag}» de un dato es verdadero o falso, no "
                                f"{getattr(self, flag)!r}")
        if self.immutable:
            if self.input_uid is None:
                raise ValueError(f"«{name}» es lo importado (inmutable) y no dice de qué "
                                 "entrada: falta input_uid (RF-008-52)")
            if selector is not None and "equals" not in selector:
                raise ValueError(f"lo importado «{name}» son las filas de su entrada: su "
                                 'selector es {"column", "equals"}, no el de las vigentes')
        object.__setattr__(self, "detail_json", None if self.detail is None
                           else canonical_json(self.detail).decode("utf-8"))

    @property
    def tracked(self) -> bool:
        """Si se sigue (fuera de :data:`UNTRACKED_STORES`)."""
        return self.store not in UNTRACKED_STORES


@dataclass(frozen=True)
class DatasetRecord:
    """Una fila de ``gb_dataset``. ``selector`` es el diccionario (o ``None``) y
    ``selector_json``, el texto guardado; fechas en UTC (``AAAA-MM-DDTHH:MM:SS.mmmZ``)."""

    uid: str
    name: str
    module: str
    kind: str
    store: Store
    locator: str
    selector: dict[str, Any] | None
    selector_json: str
    reader: str
    normalizer: str
    content_sha256: str
    crs_epsg: int | None
    operation_uid: str
    input_uid: str | None
    immutable: bool
    qgis_editable: bool
    tracked: bool
    status: DatasetStatus
    superseded_by: str | None
    tracked_size: int | None
    tracked_mtime_ns: int | None
    tracked_last_change: str | None
    tracked_schema_sha256: str | None
    checked_at: str | None
    description: str | None
    created_at: str
    modified_at: str

    @property
    def live(self) -> bool:
        """Si ocupa su nombre (vigente, que falta, bloqueado o dañado)."""
        return self.status in LIVE_STATUSES

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> DatasetRecord:
        """El registro de una fila con las columnas de :data:`RECORD_COLUMNS`."""
        values = dict(zip(RECORD_COLUMNS, row, strict=True))
        text = values.pop("selector")
        return cls(
            **{
                **values,
                "store": Store(values["store"]),
                "selector": json.loads(text) if text else None,
                "selector_json": text,
                "immutable": bool(values["immutable"]),
                "qgis_editable": bool(values["qgis_editable"]),
                "tracked": bool(values["tracked"]),
                "status": DatasetStatus(values["status"]),
            }
        )


RECORD_COLUMNS: tuple[str, ...] = (
    "uid",
    "name",
    "module",
    "kind",
    "store",
    "locator",
    "selector",
    "reader",
    "normalizer",
    "content_sha256",
    "crs_epsg",
    "operation_uid",
    "input_uid",
    "immutable",
    "qgis_editable",
    "tracked",
    "status",
    "superseded_by",
    "tracked_size",
    "tracked_mtime_ns",
    "tracked_last_change",
    "tracked_schema_sha256",
    "checked_at",
    "description",
    "created_at",
    "modified_at",
)
"""Las columnas de ``gb_dataset`` que lee :meth:`DatasetRecord.from_row`, en su orden."""

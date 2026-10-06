# SPDX-License-Identifier: GPL-3.0-or-later
"""Cabecera del proyecto, ``manifest.json`` (spec 002; RF-002-05, RF-002-06, RF-002-07,
RF-002-18; ADR-0006; formato-proyecto §2; plan 002 §5.2 y §5.4).

Copia legible, sin SQLite, de la identidad, el CRS, el GeoOrigin, las versiones y las
fechas del proyecto. **La fuente de verdad es ``project.gpkg``**: la cabecera se
reescribe desde la base de datos (:func:`manifest_from_record`) y al abrir se compara con
ella (:func:`compare`):

- si difieren la identidad (``project_uid``), el CRS horizontal o vertical o el GeoOrigin,
  o el esquema sin una migración registrada que lo explique: **INCONSISTENT**, el proyecto
  no abre, se muestran los dos valores y no se corrige ninguno (síntoma de ficheros
  mezclados a mano);
- si solo difieren las fechas, la versión de Geoblender u otros datos que la base de datos
  manda (nombre, paso de rejilla…), o la base registra una migración que la cabecera no
  tiene: **REWRITE**, se regenera desde la base de datos;
- si no difiere nada: **CONSISTENT**.

Se escribe de forma atómica (:func:`write_manifest`): ``manifest.json.tmp-<sesión>``,
``fsync`` y ``os.replace``; una escritura interrumpida deja la cabecera anterior intacta.
Ninguna ruta absoluta: la de cada almacén es relativa a la raíz del proyecto (ADR-0006
§5). El GeoOrigin, en metros enteros.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from ..errors import GeoblenderError, ProjectError, display_value
from ..georef.origin import GeoOrigin
from ..gpkg.base import GPKG_VERSION
from ..paths import find_absolute_paths
from ..timeutil import parse_utc
from .model import ProjectRecord

MANIFEST_FILE = "manifest.json"
MANIFEST_FORMAT = "geoblender-project"
PROJECT_STORE = "project.gpkg"
_OBJ = "Cabecera del proyecto (manifest.json)"
_WKT_SHOWN = 60  # caracteres de un WKT que se muestran en un mensaje


class ManifestStatus(Enum):
    """Resultado de comparar la cabecera con la base de datos."""

    CONSISTENT = "consistent"
    REWRITE = "rewrite"  # solo difiere lo que se regenera desde la BD
    INCONSISTENT = "inconsistent"  # identidad, CRS, origen o esquema: no abre


@dataclass(frozen=True)
class Manifest:
    """La cabecera del proyecto (esquema 1). Las claves del JSON están en :meth:`to_dict`.

    ``vcrs_epsg`` es ``None`` en una referencia vertical local, con ``vcrs_note``.
    ``checkout`` es la sección de una copia local de trabajo (``None`` en el original).
    """

    schema_version: int
    min_reader_schema: int
    geoblender_version: str
    created_with: str
    project_uid: str
    name: str
    crs_epsg: int
    crs_name: str
    crs_wkt: str
    vcrs_epsg: int | None
    vcrs_name: str
    vcrs_note: str | None
    origin: GeoOrigin
    grid_step_m: float
    created_at: str
    modified_at: str
    stores: Mapping[str, Any] = field(default_factory=dict)
    inventory: tuple[Any, ...] = ()
    checkout: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """El JSON de la cabecera, con las claves en el orden de formato-proyecto §2."""
        return {
            "format": MANIFEST_FORMAT,
            "schema_version": self.schema_version,
            "min_reader_schema": self.min_reader_schema,
            "geoblender_version": self.geoblender_version,
            "created_with": self.created_with,
            "project_uid": self.project_uid,
            "name": self.name,
            "crs": {
                "epsg": self.crs_epsg,
                "name": self.crs_name,
                "wkt": self.crs_wkt,
                "vertical": {
                    "epsg": self.vcrs_epsg,
                    "name": self.vcrs_name,
                    "note": self.vcrs_note,
                },
            },
            "geo_origin": {"x0": self.origin.x0, "y0": self.origin.y0, "z0": self.origin.z0},
            "grid_step_m": self.grid_step_m,
            "created_at": self.created_at,
            "modified_at": self.modified_at,
            "stores": _plain(self.stores),
            "inventory": _plain(list(self.inventory)),
            "checkout": None if self.checkout is None else _plain(self.checkout),
        }


def _plain(value: Any) -> Any:
    """Copia de ``value`` con diccionarios y listas normales (para el JSON)."""
    if isinstance(value, Mapping):
        return {str(key): _plain(inner) for key, inner in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(inner) for inner in value]
    return value


# Lectura y validación ------------------------------------------------------------------

_MISSING = object()


def _missing(dotted: str) -> ProjectError:
    return ProjectError(
        "core.manifest_field_missing",
        "falta en la cabecera: el proyecto no se abre sin él; restaure el manifest.json "
        "del proyecto (o una copia de seguridad)",
        obj=_OBJ,
        field=dotted,
        shown="ausente",
    )


def _invalid(dotted: str, value: object, reason: str) -> ProjectError:
    return ProjectError(
        "core.manifest_field_invalid",
        f"{reason}; restaure el manifest.json del proyecto (o una copia de seguridad)",
        obj=_OBJ,
        field=dotted,
        value=value,
    )


def _lookup(data: object, dotted: str) -> object:
    node = data
    parts = dotted.split(".")
    for index, part in enumerate(parts):
        if not isinstance(node, Mapping) or part not in node:
            raise _missing(".".join(parts[: index + 1]))
        node = node[part]
    return node


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _int(data: object, dotted: str, *, minimum: int | None = None) -> int:
    value = _lookup(data, dotted)
    if not _is_int(value):
        raise _invalid(dotted, value, "debe ser un número entero")
    if minimum is not None and value < minimum:  # type: ignore[operator]
        raise _invalid(dotted, value, f"debe ser un entero mayor o igual que {minimum}")
    return value  # type: ignore[return-value]


def _optional_int(data: object, dotted: str) -> int | None:
    value = _lookup(data, dotted)
    if value is None:
        return None
    if not _is_int(value):
        raise _invalid(dotted, value, "debe ser un número entero o null")
    return value  # type: ignore[return-value]


def _text(data: object, dotted: str) -> str:
    value = _lookup(data, dotted)
    if not isinstance(value, str) or not value.strip():
        raise _invalid(dotted, value, "debe ser un texto no vacío")
    return value


def _optional_text(data: object, dotted: str) -> str | None:
    value = _lookup(data, dotted)
    if value is not None and not isinstance(value, str):
        raise _invalid(dotted, value, "debe ser un texto o null")
    return value


def _utc(data: object, dotted: str) -> str:
    value = _text(data, dotted)
    try:
        parse_utc(value)
    except ValueError as exc:
        raise _invalid(
            dotted, value, "debe ser una fecha UTC ISO 8601 con «Z» (2026-10-05T08:12:44.000Z)"
        ) from exc
    return value


def _is_absolute(text: str) -> bool:
    return (
        PureWindowsPath(text).is_absolute()
        or PureWindowsPath(text).drive != ""
        or PurePosixPath(text).is_absolute()
        or bool(find_absolute_paths(text))
    )


def _stores(data: object) -> dict[str, Any]:
    stores = _lookup(data, "stores")
    if not isinstance(stores, Mapping):
        raise _invalid("stores", stores, "debe ser un objeto con los almacenes")
    path = _text(data, "stores.project.path")
    if _is_absolute(path) or ".." in PurePosixPath(path.replace("\\", "/")).parts:
        raise _invalid(
            "stores.project.path",
            path,
            "debe ser una ruta relativa a la raíz del proyecto (ADR-0006 §5)",
        )
    _text(data, "stores.project.gpkg_version")
    return _plain(stores)


def _origin(data: object) -> GeoOrigin:
    values = {name: _int(data, f"geo_origin.{name}") for name in ("x0", "y0", "z0")}
    try:
        return GeoOrigin(**values)
    except GeoblenderError as exc:
        dotted = f"geo_origin.{exc.field.lower()}"
        raise _invalid(dotted, exc.value, exc.reason) from exc


def parse_manifest(data: object) -> Manifest:
    """La cabecera de un JSON ya leído; :class:`ProjectError` con el campo (``crs``,
    ``geo_origin.x0``…) si falta algo obligatorio o un valor no vale."""
    if not isinstance(data, Mapping):
        raise _invalid("(raíz)", type(data).__name__, "debe ser un objeto JSON")
    fmt = _lookup(data, "format")
    if fmt != MANIFEST_FORMAT:
        raise _invalid("format", fmt, f"debe ser «{MANIFEST_FORMAT}»")
    schema_version = _int(data, "schema_version", minimum=1)
    min_reader = _int(data, "min_reader_schema", minimum=1)
    if min_reader > schema_version:
        raise _invalid(
            "min_reader_schema", min_reader, f"no puede ser mayor que schema_version ({schema_version})"
        )
    vcrs_epsg = _optional_int(data, "crs.vertical.epsg")
    vcrs_name = _text(data, "crs.vertical.name")
    vcrs_note = _optional_text(data, "crs.vertical.note")
    if vcrs_epsg is None and (vcrs_note is None or not vcrs_note.strip()):
        raise _invalid(
            "crs.vertical.note",
            vcrs_note,
            "una referencia vertical local necesita su descripción",
        )
    if vcrs_epsg is not None and vcrs_note is not None:
        raise _invalid(
            "crs.vertical.note",
            vcrs_note,
            "un CRS vertical EPSG no lleva descripción (solo la referencia local)",
        )
    step = _lookup(data, "grid_step_m")
    if not isinstance(step, (int, float)) or isinstance(step, bool):
        raise _invalid("grid_step_m", step, "debe ser un número (m)")
    inventory = _lookup(data, "inventory")
    if not isinstance(inventory, list):
        raise _invalid("inventory", inventory, "debe ser una lista (puede estar vacía)")
    checkout = _lookup(data, "checkout")
    if checkout is not None and not isinstance(checkout, Mapping):
        raise _invalid("checkout", checkout, "debe ser un objeto o null")
    return Manifest(
        schema_version=schema_version,
        min_reader_schema=min_reader,
        geoblender_version=_text(data, "geoblender_version"),
        created_with=_text(data, "created_with"),
        project_uid=_text(data, "project_uid"),
        name=_text(data, "name"),
        crs_epsg=_int(data, "crs.epsg"),
        crs_name=_text(data, "crs.name"),
        crs_wkt=_text(data, "crs.wkt"),
        vcrs_epsg=vcrs_epsg,
        vcrs_name=vcrs_name,
        vcrs_note=vcrs_note,
        origin=_origin(data),
        grid_step_m=float(step),
        created_at=_utc(data, "created_at"),
        modified_at=_utc(data, "modified_at"),
        stores=_stores(data),
        inventory=tuple(_plain(inventory)),
        checkout=None if checkout is None else _plain(checkout),
    )


def manifest_path(root: Path) -> Path:
    """``<proyecto>/manifest.json``."""
    return Path(root) / MANIFEST_FILE


def read_manifest(root: Path) -> Manifest:
    """La cabecera del proyecto de ``root`` (no escribe nada).

    :class:`ProjectError` si no existe, no se puede leer, no es JSON o no es válida.
    """
    path = manifest_path(root)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ProjectError(
            "core.manifest_missing",
            "no existe: la carpeta no es un proyecto de Geoblender o le falta la "
            "cabecera; restaure el manifest.json del proyecto",
            obj="Proyecto",
            field="manifest.json",
            value=str(Path(root)),
        ) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise ProjectError(
            "core.manifest_unreadable",
            f"no se puede leer ({exc}); compruebe la carpeta y sus permisos",
            obj="Proyecto",
            field="manifest.json",
            value=str(Path(root)),
        ) from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProjectError(
            "core.manifest_unreadable",
            f"no es un JSON válido (línea {exc.lineno}, columna {exc.colno}); restaure el "
            "manifest.json del proyecto",
            obj="Proyecto",
            field="manifest.json",
            value=str(Path(root)),
        ) from exc
    return parse_manifest(data)


def manifest_text(manifest: Manifest) -> str:
    """El JSON de la cabecera tal como se escribe (UTF-8, sangría de 2, LF final)."""
    return json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2) + "\n"


def write_manifest(root: Path, manifest: Manifest, session_uid: str) -> None:
    """Escribe la cabecera de forma atómica: ``manifest.json.tmp-<sesión>``, ``fsync`` y
    ``os.replace``. Si algo falla, la cabecera anterior queda intacta, se borra el
    temporal y se lanza :class:`ProjectError`."""
    target = manifest_path(root)
    temporary = target.with_name(f"{MANIFEST_FILE}.tmp-{session_uid}")
    payload = manifest_text(manifest).encode("utf-8")
    try:
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise ProjectError(
            "core.manifest_write_failed",
            f"no se ha podido escribir ({exc.strerror or exc}); la cabecera anterior "
            "sigue intacta",
            obj="Proyecto",
            field="manifest.json",
            value=str(Path(root)),
        ) from exc


def manifest_from_record(record: ProjectRecord, *, previous: Manifest | None = None) -> Manifest:
    """La cabecera regenerada desde la fila de ``gb_project`` (la BD manda). De
    ``previous`` conserva lo que la base de datos no tiene: el inventario de lo congelado,
    la sección ``checkout`` y los demás almacenes."""
    stores: dict[str, Any] = dict(previous.stores) if previous is not None else {}
    stores["project"] = {"path": PROJECT_STORE, "gpkg_version": GPKG_VERSION}
    return Manifest(
        schema_version=record.schema_version,
        min_reader_schema=record.min_reader_schema,
        geoblender_version=record.last_written_with,
        created_with=record.created_with,
        project_uid=record.uid,
        name=record.name,
        crs_epsg=record.crs_epsg,
        crs_name=record.crs_name,
        crs_wkt=record.crs_wkt,
        vcrs_epsg=record.vcrs_epsg,
        vcrs_name=record.vcrs_name,
        vcrs_note=record.vcrs_note,
        origin=record.origin,
        grid_step_m=float(record.grid_step_m),
        created_at=record.created_at,
        modified_at=record.modified_at,
        stores=stores,
        inventory=() if previous is None else previous.inventory,
        checkout=None if previous is None else previous.checkout,
    )


# Comparación con la base de datos -------------------------------------------------------


def _shown(value: object) -> str:
    if isinstance(value, str) and len(value) > _WKT_SHOWN:
        return display_value(value[:_WKT_SHOWN] + "…")
    if value is None:
        return "null"
    return display_value(value)


@dataclass(frozen=True)
class ManifestDifference:
    """Un campo en el que la cabecera y la base de datos no coinciden."""

    field: str  # nombre en la cabecera («geo_origin.x0»)
    header_value: object
    db_value: object
    blocking: bool  # identidad, CRS, origen o esquema: el proyecto no abre

    @property
    def header_text(self) -> str:
        """El valor de la cabecera como se muestra."""
        return _shown(self.header_value)

    @property
    def db_text(self) -> str:
        """El valor de la base de datos como se muestra."""
        return _shown(self.db_value)


@dataclass(frozen=True)
class ManifestCheck:
    """Resultado de :func:`compare`."""

    status: ManifestStatus
    differences: tuple[ManifestDifference, ...]

    def error(self, project_name: str) -> ProjectError | None:
        """El error que impide abrir (con los dos valores de cada campo que difiere), o
        ``None`` si no es INCONSISTENT."""
        if self.status is not ManifestStatus.INCONSISTENT:
            return None
        blocking = [item for item in self.differences if item.blocking]
        listed = "; ".join(
            f"{item.field}: cabecera {item.header_text}, base de datos {item.db_text}"
            for item in blocking
        )
        return ProjectError(
            "core.project_inconsistent",
            "la cabecera (manifest.json) y la base de datos (project.gpkg) no coinciden, "
            "síntoma de ficheros mezclados a mano; el proyecto no se abre y no se ha "
            "corregido ninguno de los dos: restaure el fichero que no corresponde",
            obj=f"Proyecto «{project_name}»",
            field=", ".join(item.field for item in blocking),
            shown=listed,
            context={
                "differences": [
                    {"field": item.field, "header": item.header_value, "db": item.db_value}
                    for item in blocking
                ]
            },
        )


# (campo de la cabecera, cómo leerlo de la cabecera, cómo leerlo de la BD)
_Getter = Callable[[Any], object]
_BLOCKING: tuple[tuple[str, _Getter, _Getter], ...] = (
    ("project_uid", lambda m: m.project_uid, lambda r: r.uid),
    ("crs.epsg", lambda m: m.crs_epsg, lambda r: r.crs_epsg),
    ("crs.name", lambda m: m.crs_name, lambda r: r.crs_name),
    ("crs.wkt", lambda m: m.crs_wkt, lambda r: r.crs_wkt),
    ("crs.vertical.epsg", lambda m: m.vcrs_epsg, lambda r: r.vcrs_epsg),
    ("crs.vertical.name", lambda m: m.vcrs_name, lambda r: r.vcrs_name),
    ("crs.vertical.note", lambda m: m.vcrs_note, lambda r: r.vcrs_note),
    ("geo_origin.x0", lambda m: m.origin.x0, lambda r: r.origin_x),
    ("geo_origin.y0", lambda m: m.origin.y0, lambda r: r.origin_y),
    ("geo_origin.z0", lambda m: m.origin.z0, lambda r: r.origin_z),
)
_REWRITABLE: tuple[tuple[str, _Getter, _Getter], ...] = (
    ("name", lambda m: m.name, lambda r: r.name),
    ("min_reader_schema", lambda m: m.min_reader_schema, lambda r: r.min_reader_schema),
    ("geoblender_version", lambda m: m.geoblender_version, lambda r: r.last_written_with),
    ("created_with", lambda m: m.created_with, lambda r: r.created_with),
    ("grid_step_m", lambda m: m.grid_step_m, lambda r: float(r.grid_step_m)),
    ("created_at", lambda m: m.created_at, lambda r: r.created_at),
    ("modified_at", lambda m: m.modified_at, lambda r: r.modified_at),
)


def _migrated(low: int, high: int, migrations: Sequence[tuple[int, int]]) -> bool:
    """Verdadero si las migraciones registradas llevan, sin huecos, de ``low`` a
    ``high``."""
    steps = set(migrations)
    return low < high and all((version, version + 1) in steps for version in range(low, high))


def compare(
    manifest: Manifest,
    record: ProjectRecord,
    migrations: Sequence[tuple[int, int]] = (),
) -> ManifestCheck:
    """Compara la cabecera con la fila de ``gb_project`` y las migraciones registradas en
    ``gb_schema_migration`` ((de, a)). No corrige nada."""
    differences: list[ManifestDifference] = []
    for name, from_header, from_db in _BLOCKING:
        header_value, db_value = from_header(manifest), from_db(record)
        if header_value != db_value:
            differences.append(ManifestDifference(name, header_value, db_value, True))
    if manifest.schema_version != record.schema_version:
        explained = _migrated(manifest.schema_version, record.schema_version, migrations)
        differences.append(
            ManifestDifference(
                "schema_version", manifest.schema_version, record.schema_version, not explained
            )
        )
    for name, from_header, from_db in _REWRITABLE:
        header_value, db_value = from_header(manifest), from_db(record)
        if header_value != db_value:
            differences.append(ManifestDifference(name, header_value, db_value, False))
    if not differences:
        status = ManifestStatus.CONSISTENT
    elif any(item.blocking for item in differences):
        status = ManifestStatus.INCONSISTENT
    else:
        status = ManifestStatus.REWRITE
    return ManifestCheck(status, tuple(differences))

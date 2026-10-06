# SPDX-License-Identifier: GPL-3.0-or-later
"""Crear un proyecto ``.gbproj`` (spec 002; RF-002-01, RF-002-02, RF-002-03, RF-002-08,
RF-002-18, RF-002-23, RF-002-24, RF-002-26; ADR-0005, ADR-0006; plan 002 §5.3 y §5.4).

Coordenadas: la ventana de trabajo es **absoluta** (CRS del proyecto, m, float64); el
GeoOrigin, en metros enteros.

1. **Validar sin tocar el disco** (:func:`prepare`): nombre válido en Windows; CRS
   horizontal y vertical del catálogo propio (por defecto EPSG:25830 y EPSG:5782; o una
   referencia local con descripción), nunca de la configuración de PROJ o GDAL del
   equipo; paso de rejilla (0,5–5 m, múltiplo de 0,5); ventana no vacía y con los ejes en
   su sitio, ampliada hacia fuera a la unidad de alineación del paso y dentro del ámbito
   del CRS; GeoOrigin del centro de la ventana ampliada (empates hacia arriba) con Z0 en
   ±10 000 m. Un fallo es :class:`ValidationError` con el campo, el valor y el motivo, y
   no se crea nada. Si la ventana pasa de ±8 km del GeoOrigin se crea igual, con aviso de
   las esquinas y del error estimado (RF-002-26).
2. **Crear de forma atómica** (:func:`create_project`): todo se hace en
   ``<Nombre>.gbproj.creando-<uid>`` junto al destino (subcarpetas, ``project.gpkg`` con
   el esquema 1, la fila de ``gb_project`` y el evento ``create`` en una transacción,
   ``manifest.json`` y ``.lock`` de la sesión) y se renombra al final; ante cualquier
   error se borra la temporal y se informa del motivo con la ruta: nunca queda un
   proyecto a medias. El proyecto queda con el cerrojo de la sesión (en modo ``network``
   en una carpeta de red) y en la lista de recientes del equipo.

Ninguna ruta absoluta se guarda en el proyecto (RF-002-18).
"""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ..errors import GeoblenderError, ProjectError, ValidationError, display_value
from ..georef.crs import CrsCatalog, CrsRef, VerticalRef, load_catalog
from ..georef.origin import GeoOrigin, Window, align_window, check_grid_step, choose_origin
from ..georef.transform import PrecisionReport, precision_report
from ..gpkg.base import create_base
from ..gpkg.connection import GpkgConnection
from ..ids import new_uid
from ..paths import DriveType, is_network_path, validate_project_name
from ..sysinfo import SessionInfo
from ..timeutil import SYSTEM_CLOCK, Clock, format_utc
from ..userdata import UserData
from .events import EventKind, record_event
from .lock import Acquired, LockInfo, LockMode, acquire
from .manifest import PROJECT_STORE, manifest_from_record, write_manifest
from .model import ProjectRecord, ProjectSettings
from .schema import MIN_READER_SCHEMA, SCHEMA_VERSION, create_schema, insert_project

PROJECT_SUFFIX = ".gbproj"
CREATING_MARK = ".creando-"
SUBFOLDERS: tuple[str, ...] = ("rasters", "meshes", "snapshots", "scenes", "exports")
_NEW = "Proyecto nuevo"
_WINDOW = "Ventana de trabajo"
_THIN_SPACE = " "  # espacio fino de miles


@dataclass(frozen=True)
class PreparedProject:
    """Los ajustes de un proyecto nuevo, ya validados y resueltos con el catálogo."""

    name: str
    crs: CrsRef
    vertical: VerticalRef
    typed_window: Window
    window: Window  # ampliada a la unidad de alineación del paso
    grid_step_m: float
    origin: GeoOrigin
    precision: PrecisionReport
    code: str | None
    client: str | None
    description: str | None


@dataclass(frozen=True)
class CreateResult:
    """El proyecto recién creado: su carpeta, la fila de ``gb_project``, el cerrojo de la
    sesión, si está en una carpeta de red y los avisos (RF-002-26)."""

    root: Path
    record: ProjectRecord
    lock: LockInfo
    network: bool
    precision: PrecisionReport
    warnings: tuple[str, ...]


def project_folder_name(name: str) -> str:
    """``<Nombre>.gbproj``."""
    return f"{name}{PROJECT_SUFFIX}"


def _optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(
            "core.project_text_invalid", "debe ser un texto", obj=_NEW, field=field, value=value
        )
    return value.strip() or None


def _thousands(value: float) -> str:
    return f"{value:,.0f}".replace(",", _THIN_SPACE)


def _window(value: object) -> Window:
    if isinstance(value, Window):
        return value
    if not isinstance(value, Sequence) or isinstance(value, str) or len(value) != 4:
        raise ValidationError(
            "core.window_value_invalid",
            "la ventana son cuatro números: xmin, ymin, xmax, ymax (m)",
            obj=_WINDOW,
            field="ventana",
            value=value,
        )
    return Window(*value)


def _vertical(catalog: CrsCatalog, epsg: object, note: object) -> VerticalRef:
    if epsg is None:
        return catalog.local_vertical(note)
    vertical = catalog.vertical(epsg)
    if note is not None and (not isinstance(note, str) or note.strip()):
        raise ValidationError(
            "core.vcrs_note_unexpected",
            f"la descripción solo se usa con una referencia local; con EPSG:{vertical.epsg} "
            "déjela vacía o elija «referencia local»",
            obj="CRS vertical",
            field="descripción de la referencia local",
            value=note,
        )
    return vertical


def _check_inside(crs: CrsRef, typed: Window, aligned: Window) -> None:
    if crs.contains(aligned.xmin, aligned.ymin, aligned.xmax, aligned.ymax):
        return
    left, bottom, right, top = crs.bounds
    shown = (
        f"({display_value(typed.xmin)}; {display_value(typed.ymin)}) – "
        f"({display_value(typed.xmax)}; {display_value(typed.ymax)})"
    )
    raise ValidationError(
        "core.window_outside_crs",
        f"cae fuera del ámbito de EPSG:{crs.epsg} ({crs.name}: X de {_thousands(left)} a "
        f"{_thousands(right)} m, Y de {_thousands(bottom)} a {_thousands(top)} m); compruebe "
        "que X (Este) e Y (Norte) no están intercambiadas y que el CRS es el de las "
        "coordenadas",
        obj=_WINDOW,
        field="ventana",
        value=(typed.xmin, typed.ymin, typed.xmax, typed.ymax),
        shown=shown,
    )


def prepare(settings: ProjectSettings, catalog: CrsCatalog | None = None) -> PreparedProject:
    """Valida los ajustes sin tocar el disco (RF-002-03); :class:`ValidationError` con el
    campo, el valor y el motivo si algo no vale."""
    catalog = load_catalog() if catalog is None else catalog
    name = validate_project_name(settings.name)
    crs = catalog.horizontal(settings.crs_epsg)
    vertical = _vertical(catalog, settings.vcrs_epsg, settings.vcrs_note)
    step = check_grid_step(settings.grid_step_m)
    typed = _window(settings.window)
    aligned = align_window(typed, step)
    _check_inside(crs, typed, aligned)
    origin = choose_origin(aligned, settings.z0)
    return PreparedProject(
        name=name,
        crs=crs,
        vertical=vertical,
        typed_window=typed,
        window=aligned,
        grid_step_m=step,
        origin=origin,
        precision=precision_report(aligned, origin),
        code=_optional_text(settings.code, "código de expediente"),
        client=_optional_text(settings.client, "cliente"),
        description=_optional_text(settings.description, "descripción"),
    )


def _record(prepared: PreparedProject, session: SessionInfo, now: str) -> ProjectRecord:
    vertical = prepared.vertical
    window = prepared.window
    return ProjectRecord(
        uid=new_uid(),
        name=prepared.name,
        schema_version=SCHEMA_VERSION,
        min_reader_schema=MIN_READER_SCHEMA,
        created_with=session.geoblender_version,
        last_written_with=session.geoblender_version,
        crs_epsg=prepared.crs.epsg,
        crs_name=prepared.crs.name,
        crs_wkt=prepared.crs.wkt2,
        vcrs_epsg=vertical.epsg,
        vcrs_name=vertical.name,
        vcrs_wkt=vertical.wkt2,
        vcrs_note=vertical.note,
        origin_x=prepared.origin.x0,
        origin_y=prepared.origin.y0,
        origin_z=prepared.origin.z0,
        grid_step_m=prepared.grid_step_m,
        window_xmin=window.xmin,
        window_ymin=window.ymin,
        window_xmax=window.xmax,
        window_ymax=window.ymax,
        created_at=now,
        modified_at=now,
        code=prepared.code,
        client=prepared.client,
        description=prepared.description,
    )


def _vertical_text(record: ProjectRecord) -> str:
    if record.vcrs_epsg is None:
        return f"cotas referidas a «{record.vcrs_note}»"
    return f"cotas en {record.vcrs_name} (EPSG:{record.vcrs_epsg})"


def _create_event(record: ProjectRecord, network: bool) -> tuple[str, dict[str, object]]:
    origin = record.origin
    message = (
        f"Proyecto «{record.name}» creado con {record.crs_name} (EPSG:{record.crs_epsg}), "
        f"{_vertical_text(record)}, GeoOrigin ({origin.x0}; {origin.y0}; {origin.z0}) y "
        f"paso de rejilla {display_value(float(record.grid_step_m))} m"
    )
    data: dict[str, object] = {
        "crs_epsg": record.crs_epsg,
        "vcrs_epsg": record.vcrs_epsg,
        "geo_origin": list(origin.as_tuple()),
        "window": [record.window_xmin, record.window_ymin, record.window_xmax, record.window_ymax],
        "grid_step_m": record.grid_step_m,
        "network": network,
    }
    return message, data


# Pasos de la creación (cada uno se puede hacer fallar en las pruebas) -------------------


def _make_temporary(parent: Path, name: str) -> Path:
    folder = parent / f"{project_folder_name(name)}{CREATING_MARK}{new_uid()}"
    folder.mkdir()
    return folder


def _make_folders(folder: Path) -> None:
    for sub in SUBFOLDERS:
        (folder / sub).mkdir()


def _create_database(
    folder: Path,
    record: ProjectRecord,
    crs: CrsRef,
    session: SessionInfo,
    network: bool,
) -> None:
    message, data = _create_event(record, network)
    with GpkgConnection.open_write(folder / PROJECT_STORE, create=True) as db:
        with db.transaction() as conn:
            create_base(conn, crs)
            create_schema(conn)
            insert_project(conn, record)
            record_event(
                conn, EventKind.CREATE, message, session=session, at=record.created_at, data=data
            )


def _write_header(folder: Path, record: ProjectRecord, session: SessionInfo) -> None:
    write_manifest(folder, manifest_from_record(record), session.session_uid)


def _acquire_lock(folder: Path, session: SessionInfo, mode: LockMode, clock: Clock) -> Acquired:
    return acquire(folder, session, mode, clock=clock)


def _publish(folder: Path, target: Path) -> None:
    folder.rename(target)  # en Windows no sustituye un destino que ya existe


def _remove_temporary(folder: Path) -> None:
    shutil.rmtree(folder, ignore_errors=True)


def _failed(target: Path, exc: BaseException) -> ProjectError:
    reason = getattr(exc, "strerror", None) or str(exc) or type(exc).__name__
    return ProjectError(
        "core.project_create_failed",
        f"no se ha podido crear ({reason}); no queda nada a medias en el disco: compruebe "
        "el espacio y los permisos de la carpeta y vuelva a intentarlo",
        obj=_NEW,
        field="carpeta",
        value=str(target),
    )


def create_project(
    parent_dir: Path,
    settings: ProjectSettings,
    session: SessionInfo,
    userdata: UserData,
    clock: Clock = SYSTEM_CLOCK,
    *,
    network: bool | None = None,
    drive_type: DriveType | None = None,
    catalog: CrsCatalog | None = None,
) -> CreateResult:
    """Crea ``<parent_dir>/<Nombre>.gbproj`` y lo deja con el cerrojo de ``session``.

    ``network``: si la carpeta es de red (``None``: se detecta, con ``drive_type``
    inyectable). :class:`ValidationError` si los ajustes no valen; :class:`ProjectError`
    si la carpeta no existe, el destino ya existe, no se puede escribir o la creación
    falla (sin dejar nada en el disco).
    """
    prepared = prepare(settings, catalog)
    parent = Path(parent_dir)
    if not parent.is_dir():
        raise ProjectError(
            "core.project_parent_missing",
            "no existe o no es una carpeta: elija una carpeta existente",
            obj=_NEW,
            field="carpeta",
            value=str(parent),
        )
    target = parent / project_folder_name(prepared.name)
    if target.exists():
        raise ProjectError(
            "core.project_exists",
            "ya existe: elija otro nombre u otra carpeta (no se sobrescribe nada)",
            obj=_NEW,
            field="carpeta",
            value=str(target),
        )
    is_network = is_network_path(parent, drive_type) if network is None else bool(network)
    mode = LockMode.NETWORK if is_network else LockMode.LOCAL
    record = _record(prepared, session, format_utc(clock.now()))
    try:
        folder = _make_temporary(parent, prepared.name)
    except OSError as exc:
        raise ProjectError(
            "core.project_not_writable",
            f"no se puede escribir en ella ({exc.strerror or exc}): compruebe los permisos "
            "o elija otra carpeta",
            obj=_NEW,
            field="carpeta",
            value=str(parent),
        ) from exc
    try:
        _make_folders(folder)
        _create_database(folder, record, prepared.crs, session, is_network)
        _write_header(folder, record, session)
        acquired = _acquire_lock(folder, session, mode, clock)
        _publish(folder, target)
    except GeoblenderError:
        _remove_temporary(folder)
        raise
    except (OSError, sqlite3.Error) as exc:
        _remove_temporary(folder)
        raise _failed(target, exc) from exc
    except BaseException:
        _remove_temporary(folder)
        raise
    warnings = () if prepared.precision.within_limit else (prepared.precision.message,)
    try:
        userdata.add_recent(record.uid, record.name, target, record.created_at)
    except OSError:
        pass  # la lista de recientes es una comodidad del equipo, no parte del proyecto
    return CreateResult(target, record, acquired.info, is_network, prepared.precision, warnings)

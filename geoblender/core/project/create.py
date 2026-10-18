# SPDX-License-Identifier: GPL-3.0-or-later
"""Crear un proyecto ``.gbproj`` (spec 002; RF-002-01, RF-002-02, RF-002-03, RF-002-08,
RF-002-18, RF-002-23, RF-002-24, RF-002-26; ADR-0005, ADR-0006; plan 002 §5.3 y §5.4).

Coordenadas: la ventana de trabajo es **absoluta** (CRS del proyecto, m, float64); el
GeoOrigin, en metros enteros.

1. **Validar sin tocar el disco** (:func:`prepare`): nombre válido en Windows; CRS
   horizontal y vertical del catálogo propio (los que se indiquen, nunca supuestos: el
   diálogo propone EPSG:25830 y EPSG:5782; o una referencia local con descripción), nunca
   de la configuración de PROJ o GDAL del equipo; paso de rejilla (0,5–5 m, múltiplo de
   0,5); ventana no vacía y con los ejes en
   su sitio, ampliada hacia fuera a la unidad de alineación del paso y dentro del ámbito
   del CRS o de su huso extendido (:func:`check_window_inside`); GeoOrigin del centro de
   la ventana ampliada (empates hacia arriba) con Z0 en ±10 000 m. Un fallo es
   :class:`ValidationError` con el campo, el valor y el motivo, y no se crea nada. Si la
   ventana pasa de ±8 km del GeoOrigin, o queda fuera del ámbito del CRS pero en su huso
   extendido, se crea igual, con aviso (de las esquinas y el error estimado, RF-002-26; o
   de cuánto se sale del huso y la deformación de escala, RF-002-03 y D-12).
2. **Crear de forma atómica** (:func:`create_project`): antes, sin tocar el disco, se
   comprueba que el proyecto no quedaría en una carpeta de solo lectura (las que declaran la
   variable de IMGA y la preferencia: los expedientes de clientes; spec 008, RF-008-15, S-3;
   ``core.project_read_only_folder`` nombrando la carpeta) y que ninguna ruta que se va a usar
   pasa del límite de rutas de Windows (259 caracteres; Blender 5.2.1 no admite más:
   ``core.path_too_long`` con la ruta y el límite, T45). Todo se hace en ``<Nombre>.gbproj.creando-<8 cifras hexadecimales>``
   junto al destino (subcarpetas, ``project.gpkg`` con
   el esquema de esta versión —el 3: el 2 y después ``core.versions.schema.apply_schema_3``,
   lo mismo que hace migrar uno del 2 (spec 009)—, la fila de ``gb_project`` y el evento
   ``create`` en una transacción,
   ``manifest.json`` y ``.lock`` de la sesión) y se renombra al final; ante cualquier
   error se borra la temporal y se informa del motivo con la ruta: nunca queda un
   proyecto a medias. El proyecto queda con el cerrojo de la sesión (en modo ``network``
   en una carpeta de red), abierto en escritura (:class:`~.session.Project`) y en la lista
   de recientes del equipo.

Ninguna ruta absoluta se guarda en el proyecto (RF-002-18).
"""

from __future__ import annotations

import math
import shutil
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ..errors import GeoblenderError, ProjectError, ValidationError, display_value
from ..georef.crs import CrsCatalog, CrsRef, VerticalRef, load_catalog
from ..georef.origin import GeoOrigin, Window, align_window, check_grid_step, choose_origin
from ..georef.tm import tm_inverse, tm_scale
from ..georef.transform import PrecisionReport, precision_report
from ..gpkg.base import create_base
from ..gpkg.connection import GpkgConnection
from ..ids import SHORT_UID_CHARS, new_uid, short_uid
from ..paths import (
    DriveType,
    ReadOnlyDirs,
    check_path_length,
    is_network_path,
    validate_project_name,
)
from ..sysinfo import SessionInfo
from ..timeutil import SYSTEM_CLOCK, Clock, format_utc
from ..userdata import UserData
from .events import EventKind, record_event
from .lock import LOCK_FILE, Acquired, LockInfo, LockMode, acquire
from .manifest import (
    PROJECT_STORE,
    Manifest,
    manifest_from_record,
    manifest_temporary_path,
    write_manifest,
)
from .model import (
    OpenMode,
    ProjectRecord,
    ProjectSettings,
    read_only_folder,
    read_only_phrase,
)
from .schema import MIN_READER_SCHEMA, SCHEMA_VERSION, create_schema, insert_project
from .session import Project, write_status

PROJECT_SUFFIX = ".gbproj"
CREATING_MARK = ".creando-"
SUBFOLDERS: tuple[str, ...] = ("rasters", "meshes", "snapshots", "scenes", "exports")
_NEW = "Proyecto nuevo"
_WINDOW = "Ventana de trabajo"
_THIN_SPACE = " "  # espacio fino de miles
# El huso UTM es el meridiano central ± 3°; el extendido, ± 6°: hasta 3° de longitud fuera
# de cada límite del huso, entre las latitudes del ámbito EPSG (spec 002, D-12).
ZONE_HALF_WIDTH_DEG = 3.0
EXTENDED_ZONE_HALF_WIDTH_DEG = 6.0


@dataclass(frozen=True)
class ScopeWarning:
    """La ventana de trabajo queda fuera del ámbito EPSG de su CRS pero dentro de su huso
    extendido: se admite con este aviso (RF-002-03; D-12).

    ``side``, ``zone_edge`` y ``degrees_outside``: el lado («este» u «oeste») del punto de
    la ventana más alejado del meridiano central, la longitud del límite del huso por ese
    lado y cuántos grados se sale de él (0 si solo se sale del ámbito EPSG, que en algunos
    CRS es menor que el huso); ``scale_ppm``, la deformación de escala de la proyección en
    la ventana de mayor valor absoluto, (k − 1)·10⁶."""

    epsg: int
    zone: int
    side: str
    zone_edge: float
    degrees_outside: float
    scale_ppm: float

    @property
    def metres_per_km(self) -> float:
        """La deformación en metros por kilómetro."""
        return self.scale_ppm / 1000.0

    @property
    def message(self) -> str:
        """El aviso para la persona, en español."""
        deformation = (
            f"la escala de la proyección se deforma {_ppm(self.scale_ppm)} ppm "
            f"({_decimal(self.metres_per_km)} m por km)"
        )
        if self.degrees_outside > 0:
            where = (
                f"{_decimal(self.degrees_outside)}° al {self.side} del huso {self.zone} "
                f"({_degrees(self.zone_edge)})"
            )
        else:
            where = f"aunque dentro de su huso {self.zone}"
        return (
            f"La ventana de trabajo queda fuera del ámbito de EPSG:{self.epsg}, {where}: se "
            f"admite en el huso extendido (hasta {_degrees(ZONE_HALF_WIDTH_DEG)} fuera del "
            f"huso), pero {deformation}"
        )


def _decimal(value: float, decimals: int = 2) -> str:
    return f"{value:.{decimals}f}".replace(".", ",")


def _degrees(value: float) -> str:
    """«0°», «-9°» o «35,26°» (coma decimal; sin decimales si es entero)."""
    value = value + 0.0  # sin «-0»
    if float(value).is_integer():
        return f"{value:.0f}°"
    return f"{_decimal(value)}°"


def _ppm(value: float) -> str:
    """«+671» o «+2 778» (con signo y espacio fino de miles)."""
    return f"{value:+,.0f}".replace(",", _THIN_SPACE)


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
    scope: ScopeWarning | None = None  # fuera del ámbito del CRS, en su huso extendido


@dataclass(frozen=True)
class CreateResult:
    """El proyecto recién creado: su carpeta, la fila de ``gb_project``, el cerrojo de la
    sesión, si está en una carpeta de red, los avisos (huso extendido, RF-002-03; precisión,
    RF-002-26), el proyecto abierto en escritura (RF-002-01) y, si la ventana queda fuera
    del ámbito del CRS en su huso extendido, ese aviso (D-12)."""

    root: Path
    record: ProjectRecord
    lock: LockInfo
    network: bool
    precision: PrecisionReport
    warnings: tuple[str, ...]
    project: Project
    scope: ScopeWarning | None = None


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


def _scope_points(crs: CrsRef, window: Window) -> list[tuple[float, float]]:
    """Los puntos (x, y) absolutos que se comprueban: las cuatro esquinas y, si la ventana
    cruza el meridiano central, los dos puntos de sus bordes sobre él (en un borde de Y
    constante, la latitud es mayor sobre el meridiano central; la longitud más alejada de
    él está siempre en una esquina)."""
    points = [
        (window.xmin, window.ymin),
        (window.xmax, window.ymin),
        (window.xmin, window.ymax),
        (window.xmax, window.ymax),
    ]
    central_x = crs.projection.fe
    if window.xmin < central_x < window.xmax:
        points += [(central_x, window.ymin), (central_x, window.ymax)]
    return points


def _outside_crs(crs: CrsRef, typed: Window) -> ValidationError:
    left, bottom, right, top = crs.bounds
    _west, south, _east, north = crs.bbox_lonlat
    lon0 = crs.projection.lon0
    shown = (
        f"({display_value(typed.xmin)}; {display_value(typed.ymin)}) – "
        f"({display_value(typed.xmax)}; {display_value(typed.ymax)})"
    )
    return ValidationError(
        "core.window_outside_crs",
        f"cae fuera del ámbito de EPSG:{crs.epsg} ({crs.name}: X de {_thousands(left)} a "
        f"{_thousands(right)} m, Y de {_thousands(bottom)} a {_thousands(top)} m) y de su "
        f"huso extendido (longitud de {_degrees(lon0 - EXTENDED_ZONE_HALF_WIDTH_DEG)} a "
        f"{_degrees(lon0 + EXTENDED_ZONE_HALF_WIDTH_DEG)}, hasta "
        f"{_degrees(ZONE_HALF_WIDTH_DEG)} fuera del huso {crs.utm_zone}, y latitud de "
        f"{_degrees(south)} a {_degrees(north)}); compruebe que X (Este) e Y (Norte) no "
        "están intercambiadas y que el CRS es el de las coordenadas",
        obj=_WINDOW,
        field="ventana",
        value=(typed.xmin, typed.ymin, typed.xmax, typed.ymax),
        shown=shown,
    )


def check_window_inside(crs: CrsRef, typed: Window, aligned: Window) -> ScopeWarning | None:
    """Comprueba que la ventana ``aligned`` (la tecleada, ``typed``, ampliada) cae en el
    ámbito de ``crs`` o en su huso extendido; lo usan crear y cambiar la ventana de trabajo
    (RF-002-03, RF-002-27; D-12; plan 002 §5.4, «Ámbito del CRS y huso extendido»).

    Se comprueba en geográficas, con la inversa de la transversa de Mercator del CRS
    (``core.georef.tm``), en las esquinas de la ventana y, si cruza el meridiano central,
    en los puntos de sus bordes sobre él. ``None`` si todos caen en el ámbito EPSG
    (``bbox_lonlat``); un :class:`ScopeWarning` si no, pero todos están a 6° de longitud o
    menos del meridiano central (el huso, ± 3°, y 3° más) y entre las latitudes del
    ámbito; y si no, :class:`ValidationError` en el campo «ventana»."""
    projection = crs.projection
    try:
        geographic = [tm_inverse(x, y, projection) for x, y in _scope_points(crs, aligned)]
    except ValueError:
        raise _outside_crs(crs, typed) from None
    if not all(math.isfinite(lon) and math.isfinite(lat) for lon, lat in geographic):
        raise _outside_crs(crs, typed)
    west, south, east, north = crs.bbox_lonlat
    if all(west <= lon <= east and south <= lat <= north for lon, lat in geographic):
        return None
    lon0 = projection.lon0
    if not all(
        abs(lon - lon0) <= EXTENDED_ZONE_HALF_WIDTH_DEG and south <= lat <= north
        for lon, lat in geographic
    ):
        raise _outside_crs(crs, typed)
    farthest = max((lon for lon, _lat in geographic), key=lambda lon: abs(lon - lon0))
    east_side = farthest >= lon0
    scales = [(tm_scale(lon, lat, projection) - 1.0) * 1e6 for lon, lat in geographic]
    return ScopeWarning(
        epsg=crs.epsg,
        zone=crs.utm_zone,
        side="este" if east_side else "oeste",
        zone_edge=lon0 + (ZONE_HALF_WIDTH_DEG if east_side else -ZONE_HALF_WIDTH_DEG),
        degrees_outside=max(0.0, abs(farthest - lon0) - ZONE_HALF_WIDTH_DEG),
        scale_ppm=max(scales, key=abs),
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
    scope = check_window_inside(crs, typed, aligned)
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
        scope=scope,
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


TEMPORARY_ATTEMPTS = 3  # nombres temporales distintos que se prueban si ya existe uno


def _temporary_name(name: str, tag: str) -> str:
    """``<Nombre>.gbproj.creando-<8 cifras hexadecimales>`` (T45)."""
    return f"{project_folder_name(name)}{CREATING_MARK}{tag}"


def _check_lengths(parent: Path, name: str, session: SessionInfo) -> None:
    """Sin tocar el disco, :class:`ProjectError` si alguna ruta que se usa al crear el
    proyecto (en su carpeta temporal, más larga que la definitiva) pasaría del límite de
    Windows: primero los ficheros (la cabecera temporal es el más largo) y después las
    carpetas (RF-002-02; T45)."""
    folder = parent / _temporary_name(name, "0" * SHORT_UID_CHARS)
    for path in (
        manifest_temporary_path(folder, session.session_uid),
        folder / f"{PROJECT_STORE}-journal",
        folder / LOCK_FILE,
    ):
        check_path_length(path, obj=_NEW)
    for path in (folder, *(folder / sub for sub in SUBFOLDERS)):
        check_path_length(path, folder=True, obj=_NEW)


def _make_temporary(parent: Path, name: str) -> Path:
    for attempt in range(TEMPORARY_ATTEMPTS):
        folder = parent / _temporary_name(name, short_uid())
        try:
            folder.mkdir()
        except FileExistsError:
            if attempt == TEMPORARY_ATTEMPTS - 1:
                raise
            continue
        return folder
    raise AssertionError("inalcanzable")  # pragma: no cover


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


def _write_header(folder: Path, header: Manifest, session: SessionInfo) -> None:
    write_manifest(folder, header, session.session_uid)


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
    read_only: ReadOnlyDirs | None = None,
) -> CreateResult:
    """Crea ``<parent_dir>/<Nombre>.gbproj`` y lo deja con el cerrojo de ``session``.

    ``network``: si la carpeta es de red (``None``: se detecta, con ``drive_type``
    inyectable). ``read_only``: las carpetas de solo lectura (spec 008, S-3; ``None``,
    ninguna). :class:`ValidationError` si los ajustes no valen; :class:`ProjectError` si el
    proyecto quedaría en una carpeta de solo lectura (RF-008-15), la carpeta no existe, el
    destino ya existe, no se puede escribir o la creación falla (sin dejar nada en el disco).
    """
    prepared = prepare(settings, catalog)
    parent = Path(parent_dir)
    target = parent / project_folder_name(prepared.name)
    folder = read_only_folder(read_only, target)
    if folder is not None:
        raise ProjectError(
            "core.project_read_only_folder",
            f"quedaría dentro de {read_only_phrase(folder)}: no se ha creado nada; elija otra "
            "carpeta",
            obj=_NEW,
            field="carpeta",
            value=str(target),
            context={"read_only_folder": str(folder)},
        )
    if not parent.is_dir():
        raise ProjectError(
            "core.project_parent_missing",
            "no existe o no es una carpeta: elija una carpeta existente",
            obj=_NEW,
            field="carpeta",
            value=str(parent),
        )
    if target.exists():
        raise ProjectError(
            "core.project_exists",
            "ya existe: elija otro nombre u otra carpeta (no se sobrescribe nada)",
            obj=_NEW,
            field="carpeta",
            value=str(target),
        )
    _check_lengths(parent, prepared.name, session)
    is_network = is_network_path(parent, drive_type) if network is None else bool(network)
    mode = LockMode.NETWORK if is_network else LockMode.LOCAL
    record = _record(prepared, session, format_utc(clock.now()))
    header = manifest_from_record(record)
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
        _write_header(folder, header, session)
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
    warnings: tuple[str, ...] = ()
    if prepared.scope is not None:
        warnings += (prepared.scope.message,)
    if not prepared.precision.within_limit:
        warnings += (prepared.precision.message,)
    try:
        userdata.add_recent(record.uid, record.name, target, record.created_at)
    except OSError:
        pass  # la lista de recientes es una comodidad del equipo, no parte del proyecto
    project = Project(
        root=target,
        record=record,
        manifest=header,
        session=session,
        userdata=userdata,
        status=write_status(OpenMode.WRITE_NETWORK if is_network else OpenMode.WRITE_LOCAL),
        network=is_network,
        clock=clock,
    )
    return CreateResult(
        target,
        record,
        acquired.info,
        is_network,
        prepared.precision,
        warnings,
        project,
        prepared.scope,
    )

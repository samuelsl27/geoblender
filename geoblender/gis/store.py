# SPDX-License-Identifier: GPL-3.0-or-later
"""Resultados e importaciones de la topografía en el proyecto (spec 006, T42 y T43;
RF-006-04, RF-006-08, RF-006-10, RF-006-12, RF-006-26, RF-006-28; RF-008-07, RF-008-11,
RF-008-14, RF-008-17, RF-008-18, RF-008-19, RF-008-23, RF-008-52, RF-008-53, RF-008-54;
ADR-0025 §3 y §8; plan 006 §5.2, §5.6.3, §5.6.4 y §5.6.5; D20, D22).

Lo que produce una operación de la 006 se guarda en el proyecto con la API de procedencia de la
008, nunca escribiendo en las tablas ``gb_*``:

- **rejillas** en ``rasters/`` (GeoTIFF del perfil ``project``: Float64, NaN, cada celda con
  los mismos bits, RF-006-08), **TIN** en ``meshes/`` (npz de ``gis.tin.save_tin`` con su
  ``meta``) y **tablas** de ``project.gpkg`` (plan §5.2.3, :data:`TABLE_LAYOUTS`: puntos
  ``POINT`` y líneas de rotura ``LINESTRING`` con Z, curvas de nivel ``LINESTRING`` con Z y
  contornos ``MULTIPOLYGON`` sin Z, creadas con ``core.gpkg.create_feature_table``, con el SRS
  de sus coordenadas y la referencia vertical citada en su descripción; cada curva cerrada
  repite su primer vértice al final); cada una con la ``DatasetSpec`` de ``gis.provenance`` (su
  nombre, su almacén, su ubicación y su lector) y su ``ContentDigest``: el que da su lector al
  leer lo escrito, calculado aquí sin volver a leerlo (``gis.content.raster_digest`` y
  ``tin_digest``), el que trae el resultado de un trabajo de la 004 o, en una tabla, el que
  calcula el registro de la 008 en la transacción que la escribe.

:class:`ResultWriter` (un gestor de contexto por operación, con su ``OperationHandle``) sigue
el flujo del plan §5.6.4:

1. **Preparar** (:meth:`~ResultWriter.raster`, :meth:`~ResultWriter.tin`,
   :meth:`~ResultWriter.copy_file`, el de un trabajo, :meth:`~ResultWriter.contours`,
   :meth:`~ResultWriter.points`, :meth:`~ResultWriter.breaklines` y
   :meth:`~ResultWriter.boundary`): se comprueba que el sitio del resultado está libre o es
   del mismo dato (si no, ``gis.output_target_taken``, sin escribir nada), se reclaman con
   ``OperationHandle.claim_paths`` el temporal, el destino y la copia del anterior, y cada
   fichero se escribe entero en su temporal ``<fichero>.tmp-<sesión>`` (el patrón de restos de
   la 008, plan 008 §5.4.9: :func:`temporary_path`; el escritor de T07 recibe el nombre). Las
   filas de una tabla se codifican ya.
2. **Poner en su sitio** (:meth:`~ResultWriter.install`, antes de la transacción): el
   fichero anterior del mismo dato se aparta a ``<fichero>.old.tmp-<sesión>`` y el temporal
   pasa a su sitio con ``os.replace``. Si otro programa tiene abierto el destino (QGIS),
   ``gis.raster_target_locked``: no se escribe nada y el anterior sigue intacto (sin
   ``<nombre>__<hash8>.tif``, D20: la 008 no cambia la ubicación de un dato vivo).
3. **Confirmar** (:meth:`~ResultWriter.commit`, o :meth:`~ResultWriter.write` como función de
   escritura de ``ingest_job`` al incorporar un trabajo): en una transacción de
   ``Project.write_transaction``, la entrada de una importación (abajo), las tablas y
   ``OperationHandle.complete`` con las salidas, ``software``, el intérprete, el ejecutor y el
   mensaje (RF-008-18). Confirmada, se borran las copias de lo anterior.

**Importaciones** (``gis.import_dtm``, ``gis.import_points`` y ``gis.import_vector``; plan
§5.6.3 y §5.6.4). La entrada que importa (:class:`~..core.inputs.InputSpec`) la construye
:func:`source_input` con lo que da el trabajo de la importación (el ``ContentDigest`` de la
fuente con las declaraciones de :func:`source_declarations` y la huella de cada fichero) y el
ancla de cada fichero (``core.inputs.locate_source``: relativa al proyecto o a su original, o
solo su nombre; nunca una ruta absoluta). Antes de escribir nada,
:meth:`~ResultWriter.declare_input` la clasifica (``classify_import``, RF-008-54; también
:func:`classify_source`, para preguntar el motivo de una sustitución antes): la misma entrada
con los mismos ajustes se **reutiliza** (la operación queda «cancelada» con el aviso y no se
escribe nada); con otros ajustes (otro CRS declarado) es una **sustitución**, que necesita la
entrada a la que sustituye y el motivo (RF-008-11; si no, ``core.input_substitution_required``
sin escribir nada); si no, una entrada **nueva**. Lo importado (``gis_src_``, ``gis_pts_``,
``gis_brk_``, ``gis_cnt_`` y ``gis_bnd_``) es inmutable, con su entrada, en el CRS y la
referencia vertical declarados (las coordenadas de la fuente sin alterar, RF-006-12), y su
ubicación lleva el uid corto de su entrada (D22), que se conoce al registrarla: sus ficheros se
escriben antes en un temporal con el nombre del dato y, en la transacción, tras
``supersede`` (si sustituye) y ``register_input``, pasan a su sitio y se crean sus tablas
(protegidas por el registro de la 008: cambiarlas desde otra conexión aborta con el nombre de la
entrada, RF-008-52); después, ``complete``. El original del texto de puntos se guarda después
con :meth:`~ResultWriter.originals` (``store_originals_steps``, RF-008-53) desde la copia
verificada del trabajo, nunca desde la fuente (RF-008-14); de un ráster o una capa, no.

**Fallo o cancelación antes de confirmar** (RF-006-28, RF-008-19): al salir del bloque con un
error, o sin confirmar, lo puesto en su sitio se deshace (el anterior vuelve, lo nuevo se
borra), los temporales se borran y ni la entrada ni las tablas existen (la transacción se
deshizo); con un error, la operación queda «cancelada» (``JobCancelled`` de un escritor,
``ReadCancelled``, ``HashCancelled``) o «fallida», con su motivo
(``core.provenance.operations``). Ningún dato, fichero ni tabla nuevos. Si Blender se cierra de
golpe, los temporales sin reclamar los aparta a ``orphans/`` la comprobación de apertura de la
008 (ADR-0025 §8); mientras la operación está en curso, no (están reclamados y son de esta
sesión).

Ningún error del disco llega como ``OSError`` a la transacción del proyecto (lo pasaría a solo
lectura): es ``gis.raster_target_locked`` o ``gis.raster_write_failed``.

Para leer lo guardado: :func:`list_gis_datasets` (desde ``gb_dataset``), :func:`load_raster` y
:func:`load_tin`. Python puro y numpy (ADR-0004).
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import sys
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType, TracebackType
from typing import Any, Protocol

import numpy as np

from ..core.content.encoder import ContentDigest
from ..core.content.readers import ReadCancelled
from ..core.datasets import registry as dataset_registry
from ..core.datasets.model import (
    DATASET_DECLARATIONS,
    LIVE_STATUSES,
    RECORD_COLUMNS,
    DatasetRecord,
    DatasetSpec,
    Store,
)
from ..core.errors import GeoblenderError
from ..core.georef import CrsCatalog, CrsRef, VerticalRef, load_catalog
from ..core.gpkg.base import ColumnDef, create_feature_table
from ..core.gpkg.wkb import Geometry, encode_geometry
from ..core.hashing import HashCancelled
from ..core.ids import SHORT_UID_CHARS
from ..core.inputs.model import (
    InputRecord,
    InputSpec,
    InputStatus,
    SourceFile,
    SourcePrint,
    input_declarations,
)
from ..core.inputs.originals import STEP_BUDGET_S, store_originals_steps
from ..core.inputs.registry import (
    Classification,
    Reuse,
    Substitute,
    classify_import,
    register_input,
    reuse_input,
    supersede,
)
from ..core.inputs.registry import get as get_input
from ..core.paths import check_path_length
from ..core.project.model import Progress as ProjectProgress
from ..core.provenance.messages import ProvenanceError
from ..core.provenance.operations import (
    OperationHandle,
    OperationProject,
    OperationStatus,
    cancel_reason,
    failure_reason,
)
from ..jobs.worker_api import JobCancelled
from .content import (
    ASC,
    CONTENT_SETTINGS,
    GEOTIFF,
    GPKG_LAYER,
    POINTS_TEXT,
    READER_SETTINGS,
    XYZ_GRID,
    raster_digest,
    tin_digest,
)
from .contours import ContourLine
from .crs import ELLIPSOIDAL_ETRS89
from .geotiff.reader import read_geotiff
from .geotiff.writer import target_locked, write_failed, write_geotiff
from .messages import GisError
from .points import Breakline, PointSet
from .ports import Cancelled, Progress, WriteProfile
from .provenance import (
    BOUNDARY,
    BREAKLINES,
    CONTOUR_LINES,
    FAMILIES_BY_CODE,
    IMPORTS,
    MODULE,
    OPERATION_TYPES_BY_NAME,
    POINTS,
    PROJECT_GRID,
    SOURCE_GRID,
    TIN,
    DatasetFamily,
    dataset_name,
    dataset_spec,
    input_kind,
    layer_family,
)
from .raster import Raster
from .tin import Tin, save_tin
from .tin import load_tin as read_tin_file

__all__ = [
    "BACKUP_MARK",
    "BOUNDARY_ROLES",
    "COPY_CHUNK_BYTES",
    "ELLIPSOIDAL_EPSG",
    "TABLE_LAYOUTS",
    "TEMPORARY_MARK",
    "ResultWriter",
    "StoreProject",
    "TableLayout",
    "backup_path",
    "classify_source",
    "declared_crs",
    "declared_vertical",
    "list_gis_datasets",
    "load_raster",
    "load_tin",
    "project_references",
    "session_tag",
    "source_declarations",
    "source_input",
    "temporary_path",
]

TEMPORARY_MARK = ".tmp-"
"""``<fichero>.tmp-<sesión>``: el temporal de un fichero que escribe una operación, con las 8
últimas cifras de la sesión (el patrón de restos de la 008, como los de ``originals/``)."""
BACKUP_MARK = ".old"
"""``<fichero>.old.tmp-<sesión>``: el fichero anterior del mismo dato, apartado hasta que la
operación se confirma (un temporal de la sesión: si Blender se cierra de golpe, va a
``orphans/`` y no se borra)."""
COPY_CHUNK_BYTES = 4 * 1024 * 1024
"""Lo que se copia de una vez del resultado de un trabajo (entre dos, se mira la cancelación)."""
CANCELLATIONS: tuple[type[BaseException], ...] = (JobCancelled, ReadCancelled, HashCancelled)
"""Los errores con que una escritura, una lectura o una huella se paran a petición de la
persona: la operación queda «cancelada», no «fallida»."""
FILE_FAMILIES: tuple[str, ...] = (SOURCE_GRID, PROJECT_GRID, TIN)
"""Las familias que son un fichero de ``rasters/`` o ``meshes/``."""
GRID_FAMILIES: tuple[str, ...] = (SOURCE_GRID, PROJECT_GRID)
"""Las familias de rejilla."""
GRID_READERS: tuple[str, ...] = (GEOTIFF.id, ASC.id, XYZ_GRID.id)
"""Los lectores de las fuentes de un MDT (lo importado es su rejilla de origen)."""
ELLIPSOIDAL_EPSG = 4937
"""El código con que se declara una altura elipsoidal ETRS89 en una entrada (ETRS89
geográfico 3D; plan §5.3.3)."""
BOUNDARY_ROLES: tuple[str, ...] = ("boundary", "hole")
"""El papel de cada contorno en su tabla (``gis_bnd_*.role``, plan §5.2.3): contorno o hueco."""

_OBJ = "Dato de topografía"
_FIELD_LOCATION = "ubicación"
_FIELD_DATASET = "dato"
_GEOMETRY_COLUMN = "geom"


class StoreProject(OperationProject, Protocol):
    """Lo que usa del proyecto (``core.project.Project``): lo de las operaciones y las
    entradas de la 008 y su fila de ``gb_project`` (``record``: el CRS horizontal y la
    referencia vertical)."""

    @property
    def record(self) -> Any: ...


@dataclass(frozen=True, slots=True)
class TableLayout:
    """La tabla de una familia vectorial (plan §5.2.3): el nombre GeoPackage de su tipo de
    geometría (``POINT``, ``LINESTRING``, ``MULTIPOLYGON``), si lleva Z, sus columnas (además
    de ``fid`` y ``geom``) y cómo empieza su identificador en ``gpkg_contents``."""

    geometry_type: str
    has_z: bool
    columns: tuple[ColumnDef, ...]
    label: str


TABLE_LAYOUTS: Mapping[str, TableLayout] = MappingProxyType({
    POINTS: TableLayout(
        "POINT",
        True,
        (
            ColumnDef("point_id", "TEXT", not_null=True, default="''"),
            ColumnDef("code", "TEXT", not_null=True, default="''"),
            ColumnDef("source_row", "INTEGER"),
        ),
        "Puntos",
    ),
    BREAKLINES: TableLayout(
        "LINESTRING",
        True,
        (
            ColumnDef("line_id", "TEXT", not_null=True, default="''"),
            ColumnDef("hard", "BOOLEAN", not_null=True),
            ColumnDef("code", "TEXT", not_null=True, default="''"),
        ),
        "Líneas de rotura",
    ),
    CONTOUR_LINES: TableLayout(
        "LINESTRING",
        True,
        (
            ColumnDef("elevation", "DOUBLE", not_null=True),
            ColumnDef("is_index", "BOOLEAN", not_null=True),
            ColumnDef("closed", "BOOLEAN", not_null=True),
            ColumnDef("length_m", "DOUBLE", not_null=True),
        ),
        "Curvas de nivel",
    ),
    BOUNDARY: TableLayout(
        "MULTIPOLYGON",
        False,
        (ColumnDef("role", "TEXT", not_null=True),),
        "Contornos",
    ),
})
"""Las tablas de las familias vectoriales, por familia (plan §5.2.3). El ``CHECK`` del papel
de un contorno (:data:`BOUNDARY_ROLES`) lo comprueba :meth:`ResultWriter.boundary`: la
``ColumnDef`` de la 002 no lo escribe."""


# --- Nombres y referencias del proyecto ---------------------------------------------------------


def session_tag(project: StoreProject) -> str:
    """Las 8 últimas cifras hexadecimales de la sesión que tiene el proyecto abierto, en
    minúsculas (como los temporales de ``originals/`` y la carpeta de ``orphans/``)."""
    return (project.session.session_uid.replace("-", "")[-SHORT_UID_CHARS:] or "sesion").lower()


def temporary_path(project: StoreProject, final: Path) -> Path:
    """El temporal de ``final`` mientras se escribe: ``<fichero>.tmp-<sesión>``, en su carpeta."""
    final = Path(final)
    return final.with_name(f"{final.name}{TEMPORARY_MARK}{session_tag(project)}")


def backup_path(project: StoreProject, final: Path) -> Path:
    """Dónde se aparta el fichero anterior de ``final`` hasta confirmar:
    ``<fichero>.old.tmp-<sesión>``."""
    final = Path(final)
    return final.with_name(f"{final.name}{BACKUP_MARK}{TEMPORARY_MARK}{session_tag(project)}")


def project_references(
    project: StoreProject, *, catalog: CrsCatalog | None = None
) -> tuple[CrsRef, VerticalRef]:
    """El CRS horizontal y la referencia vertical del proyecto (``gb_project``), del catálogo
    de la 002 (por defecto, el de la extensión). ``ValueError`` con un proyecto abierto solo
    con su cabecera (de un esquema que esta versión no lee)."""
    record = project.record
    if record is None:
        raise ValueError(f"el proyecto «{project.name}» se abrió solo con su cabecera: no se "
                         "pueden leer ni escribir sus datos")
    found = load_catalog() if catalog is None else catalog
    crs = found.horizontal(record.crs_epsg)
    if record.vcrs_epsg is None:
        return crs, found.local_vertical(record.vcrs_note)
    return crs, found.vertical(record.vcrs_epsg)


def _vertical_text(vertical: VerticalRef) -> str:
    """La referencia vertical en el ``meta`` de un TIN: «EPSG:5782» o «Referencia local
    (nota)»."""
    if vertical.epsg is not None:
        return f"EPSG:{vertical.epsg}"
    return f"{vertical.name} ({vertical.note})"


def _z_description(vertical: VerticalRef) -> str:
    """Cómo se cita en ``gpkg_contents.description`` la referencia de las Z (plan §5.2.3)."""
    if vertical.epsg is not None:
        return f"Z en {vertical.name} (EPSG:{vertical.epsg})"
    if vertical.kind == "ellipsoidal":
        return f"Z en {vertical.name}"
    return f"Z referidas a «{vertical.note}» ({vertical.name})"


def _family(code: str, allowed: Sequence[str]) -> DatasetFamily:
    if code not in allowed:
        raise ValueError(f"{code!r} no es una familia de datos de esta escritura: es una de "
                         f"{', '.join(allowed)}")
    return FAMILIES_BY_CODE[code]


def _disk_error(name: str, error: OSError) -> GisError:
    """El error para la persona de un fallo del disco al escribir ``name``."""
    if isinstance(error, PermissionError):  # Windows: otro programa lo tiene abierto
        return target_locked(name)
    return write_failed(name, error)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """Si hay una tabla (o vista) con ese nombre en la base, sin distinguir mayúsculas."""
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND lower(name) = lower(?)",
        (table,),
    ).fetchone() is not None


def _owned(conn: sqlite3.Connection, spec: DatasetSpec) -> tuple[bool, bool]:
    """Si la ubicación de ``spec`` es del dato vivo con su nombre (que se puede volver a
    escribir: no es lo importado) y si es de algún otro dato, vivo o no."""
    rows = conn.execute(
        "SELECT name, status, immutable FROM gb_dataset WHERE store = ? AND locator = ?",
        (str(spec.store), spec.locator),
    ).fetchall()
    live = {str(status) for status in LIVE_STATUSES}
    mine = [row for row in rows if row[0] == spec.name and row[1] in live and not row[2]]
    return bool(mine), len(mine) != len(rows)


def _taken(spec: DatasetSpec) -> GisError:
    return GisError("gis.output_target_taken", obj=f"{_OBJ} «{spec.name}»",
                    field=_FIELD_LOCATION, value=spec.locator, name=spec.name)


def _ensure_srs(conn: sqlite3.Connection, crs: CrsRef) -> None:
    """El CRS de las coordenadas de una tabla en ``gpkg_spatial_ref_sys`` (el del proyecto ya
    está; uno declarado en una importación, como lo escribe ``core.gpkg.create_base``)."""
    if conn.execute("SELECT 1 FROM gpkg_spatial_ref_sys WHERE srs_id = ?",
                    (crs.epsg,)).fetchone() is not None:
        return
    conn.execute(
        "INSERT INTO gpkg_spatial_ref_sys (srs_name, srs_id, organization, "
        "organization_coordsys_id, definition, description) VALUES (?, ?, 'EPSG', ?, ?, ?)",
        (crs.name, crs.epsg, crs.epsg, crs.wkt1, crs.area or None),
    )


# --- Entradas de las importaciones (T43) -----------------------------------------------------


def declared_crs(crs: CrsRef | None) -> dict[str, Any] | None:
    """El CRS horizontal declarado de una entrada (``core.inputs``): ``{"epsg": n}``, o
    ``None`` si no se declaró (nunca se supone, RF-006-04)."""
    if crs is None:
        return None
    if not isinstance(crs, CrsRef):
        raise TypeError(f"el CRS horizontal declarado es un CrsRef del catálogo, no {crs!r}")
    return {"epsg": crs.epsg}


def declared_vertical(vertical: VerticalRef | None) -> dict[str, Any] | None:
    """La referencia vertical declarada de una entrada: ``{"epsg": n}``, ``{"local": nota}``
    o, la altura elipsoidal ETRS89, ``{"ellipsoidal": 4937}``; ``None`` si no se declaró."""
    if vertical is None:
        return None
    if not isinstance(vertical, VerticalRef):
        raise TypeError(f"la referencia vertical declarada es un VerticalRef, no {vertical!r}")
    if vertical.kind == "epsg":
        return {"epsg": vertical.epsg}
    if vertical.kind == "local":
        return {"local": vertical.note}
    if vertical == ELLIPSOIDAL_ETRS89:
        return {"ellipsoidal": ELLIPSOIDAL_EPSG}
    return {"ellipsoidal": vertical.name}


def _reader_settings(reader: object, settings: Mapping[str, Any] | None) -> dict[str, Any]:
    """Los ajustes de lectura de la importación con ``reader`` (los únicos que guarda su
    entrada y que vuelve a recibir su lector, ``gis.content.READER_SETTINGS``)."""
    allowed = READER_SETTINGS.get(reader) if isinstance(reader, str) else None
    if allowed is None:
        raise ValueError(f"{reader!r} no es el lector de una importación de la topografía (con "
                         f"versión): es uno de {', '.join(READER_SETTINGS)}")
    if settings is not None and not isinstance(settings, Mapping):
        raise TypeError(f"los ajustes de una importación son un diccionario, no {settings!r}")
    chosen = dict(settings or {})
    unknown = sorted(str(key) for key in chosen if key not in allowed)
    if unknown:
        raise ValueError(f"ajustes que no son de lectura de «{reader}»: {unknown} (son "
                         f"{list(allowed)})")
    if reader == POINTS_TEXT.id:
        missing = [key for key in ("encoding", "separator", "decimal", "columns")
                   if key not in chosen]
        if missing:
            raise ValueError(f"a la importación de un texto de puntos le faltan {missing}")
    if reader == GPKG_LAYER.id:
        layer = chosen.get("layer")
        if not isinstance(layer, str) or not layer:
            raise ValueError(f"la importación de una capa dice su capa («layer»), no {layer!r}")
        layer_family(chosen.get("role"))  # el papel decide su familia (ValueError si no)
    return chosen


def source_declarations(
    reader: str,
    crs: CrsRef | None,
    vertical: VerticalRef | None,
    settings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Las declaraciones (``DECL``, ADR-0024 §3) con que el trabajo de una importación con
    ``reader`` calcula el ``ContentDigest`` de la fuente: sus CRS declarados
    (:func:`declared_crs`, :func:`declared_vertical`) y sus convenciones, los ajustes de
    lectura que son contenido (``gis.content.CONTENT_SETTINGS``). Las mismas que comprueba
    :func:`source_input`."""
    chosen = _reader_settings(reader, settings)
    return input_declarations(declared_crs(crs), declared_vertical(vertical),
                              {key: chosen[key] for key in CONTENT_SETTINGS if key in chosen})


def source_input(
    reader: str,
    name: str,
    *,
    files: Sequence[SourceFile],
    file_prints: Sequence[SourcePrint],
    digest: ContentDigest,
    crs: CrsRef | None,
    vertical: VerticalRef | None,
    settings: Mapping[str, Any] | None = None,
    received_at: Any = None,
    received_from: str | None = None,
) -> InputSpec:
    """La entrada (``InputSpec`` de la 008, RF-008-07) de una importación de la 006 con el
    lector de importación ``reader`` (con versión): su nombre lógico ``name`` (el del
    diálogo), su tipo (el del lector: ``raster``, ``table`` o ``vector``), ``module="gis"``,
    sus ficheros (``files``, con el ancla de ``core.inputs.locate_source``: el principal el
    primero; el ``.prj`` de un ASC, compañero) y sus huellas, el ``digest`` que dio el trabajo
    con :func:`source_declarations`, sus CRS horizontal y vertical declarados (``None``: sin
    declarar; lo rechazan la clasificación y el registro, RF-006-04), la capa de una capa,
    los ajustes de lectura del lector (``gis.content.READER_SETTINGS``) con los que son
    contenido (``gis.content.CONTENT_SETTINGS``), y la entrega (fecha y quién, opcionales).

    ``ValueError`` (un error del programa: el diálogo solo ofrece lo válido) con un lector
    que no es de una importación de la 006, un ajuste que no es de lectura de su lector, una
    capa sin capa o con un papel que no es de ``gis.provenance.LAYER_ROLES``, un texto de
    puntos sin codificación, separador, decimal o columnas, o un hash que no es el de sus
    datos con esas declaraciones; ``TypeError`` con un argumento de otro tipo."""
    chosen = _reader_settings(reader, settings)
    return InputSpec(
        name,
        input_kind(reader),
        MODULE,
        reader,
        files=files,
        file_prints=file_prints,
        digest=digest,
        crs_h=declared_crs(crs),
        crs_v=declared_vertical(vertical),
        layer=chosen["layer"] if reader == GPKG_LAYER.id else None,
        settings=chosen,
        content_settings_keys=[key for key in CONTENT_SETTINGS if key in chosen],
        received_at=received_at,
        received_from=received_from,
    )


def classify_source(project: StoreProject, spec: InputSpec) -> Classification:
    """Qué es la importación de ``spec`` frente a las entradas activas del proyecto
    (``classify_import``, RF-008-54): ``Reuse`` (la misma, con los mismos ajustes),
    ``Substitute`` (los mismos datos con otros ajustes: pedir el motivo) o ``New``. Solo lee.
    ``ProvenanceError`` ``core.input_crs_missing`` si no declara su CRS o su referencia
    vertical (RF-006-04)."""
    with project.read() as conn:
        return classify_import(conn, spec)


def _references(spec: InputSpec) -> tuple[CrsRef, VerticalRef]:
    """El CRS y la referencia vertical que declara ``spec`` (ya comprobados al
    clasificarla), como objetos del catálogo."""
    catalog = load_catalog()
    crs_h = dict(spec.crs_h or {})
    crs_v = dict(spec.crs_v or {})
    if "epsg" not in crs_h:
        raise ValueError(f"la entrada «{spec.name}» de la topografía declara un CRS horizontal "
                         f"del catálogo ({{\"epsg\": n}}), no {crs_h!r}")
    crs = catalog.horizontal(crs_h["epsg"])
    if "epsg" in crs_v:
        return crs, catalog.vertical(crs_v["epsg"])
    if "local" in crs_v:
        return crs, catalog.local_vertical(crs_v["local"])
    if crs_v.get("ellipsoidal") == ELLIPSOIDAL_EPSG:
        return crs, ELLIPSOIDAL_ETRS89
    raise ValueError(f"la entrada «{spec.name}» de la topografía declara una referencia "
                     f"vertical de la 002 o la altura elipsoidal ETRS89, no {crs_v!r}")


def _import_families(spec: InputSpec) -> tuple[str, ...]:
    """Las familias de lo importado de ``spec``: la rejilla de origen de un MDT, los puntos
    y las líneas de un texto, o la de una capa según su papel."""
    if spec.reader in GRID_READERS:
        return (SOURCE_GRID,)
    if spec.reader == POINTS_TEXT.id:
        return (POINTS, BREAKLINES)
    return (layer_family(spec.settings.get("role")),)


@dataclass(frozen=True, slots=True)
class _Declared:
    """La entrada que declaró la importación: su ``InputSpec``, la que sustituye y el motivo,
    sus referencias y las familias de lo importado."""

    spec: InputSpec
    previous: InputRecord | None
    reason: str | None
    crs: CrsRef
    vertical: VerticalRef
    families: tuple[str, ...]


# --- Escritura de los resultados de una operación ----------------------------------------------


@dataclass(slots=True)
class _File:
    """Un fichero de ``rasters/`` o ``meshes/``: su dato (nombre, familia, nombre de la orden,
    hash y EPSG), el nombre con que se escribe (``path``: su destino o, en lo importado, el del
    dato sin la entrada), su temporal y, cuando se conocen (lo importado, al registrar su
    entrada), su ``DatasetSpec``, su destino y dónde se aparta el anterior; si ya está en su
    sitio y si había uno anterior apartado."""

    dataset: str
    family: str
    name: str
    content: ContentDigest
    crs_epsg: int | None
    path: Path
    temporary: Path
    spec: DatasetSpec | None = None
    final: Path | None = None
    backup: Path | None = None
    installed: bool = False
    replaced: bool = False


@dataclass(slots=True)
class _Table:
    """Una tabla de ``project.gpkg``: su dato (nombre, familia y nombre de la orden), su
    forma, sus filas ya codificadas (geometría y columnas), su extensión, el CRS de sus
    coordenadas, la referencia de sus Z y, cuando se conocen (lo importado, al registrar su
    entrada), su ``DatasetSpec``, su identificador y su descripción."""

    dataset: str
    family: str
    name: str
    layout: TableLayout
    rows: tuple[tuple[Any, ...], ...]
    extent: tuple[float, float, float, float] | None
    crs: CrsRef
    vertical: VerticalRef
    spec: DatasetSpec | None = None
    identifier: str | None = None
    description: str | None = None


def _extent(arrays: Iterable[np.ndarray]) -> tuple[float, float, float, float] | None:
    """La extensión en planta (xmin, ymin, xmax, ymax) de unas coordenadas, o ``None``."""
    lows: list[np.ndarray] = []
    highs: list[np.ndarray] = []
    for coords in arrays:
        lows.append(coords[:, :2].min(axis=0))
        highs.append(coords[:, :2].max(axis=0))
    if not lows:
        return None
    low = np.min(lows, axis=0)
    high = np.max(highs, axis=0)
    return (float(low[0]), float(low[1]), float(high[0]), float(high[1]))


def _ring(values: object) -> np.ndarray:
    """Un anillo en planta (X, Y; la Z se descarta: los contornos no la llevan), cerrado."""
    array = np.asarray(values)
    if array.ndim != 2 or array.shape[1] not in (2, 3) or len(array) < 3:
        raise ValueError(f"un anillo de un contorno tiene al menos 3 vértices (X, Y[, Z]), no "
                         f"la forma {array.shape}")
    ring = np.ascontiguousarray(array[:, :2])
    if not np.array_equal(ring[0], ring[-1]):
        ring = np.vstack([ring, ring[:1]])
    return ring


def _polygons(item: object) -> list[list[np.ndarray]]:
    """Los polígonos (cada uno, sus anillos) de un contorno: una ``Geometry`` de polígonos
    (de ``gis.vector.read_layer``), un anillo o una lista de anillos (un polígono)."""
    if isinstance(item, Geometry):
        if item.geometry_type == "POLYGON":
            parts = [item.coords]
        elif item.geometry_type == "MULTIPOLYGON":
            parts = list(item.coords)
        else:
            raise ValueError(f"un contorno es un polígono, no un {item.geometry_type}")
    elif isinstance(item, np.ndarray):
        parts = [[item]]
    elif isinstance(item, str | bytes) or not isinstance(item, Iterable):
        raise TypeError(f"un contorno es una Geometry de polígonos o una lista de anillos, no "
                        f"{item!r}")
    else:
        parts = [list(item)]
    return [[_ring(ring) for ring in polygon] for polygon in parts]


class ResultWriter:
    """Los resultados de la operación ``handle`` (``begin_operation`` de la 008, «en curso») en
    ``project`` (véase el módulo). Se usa como gestor de contexto::

        with ResultWriter(project, handle) as out:
            out.raster("MDT Norte", rejilla)
            out.commit(software={"pyproj": "3.8.0"}, message=informe)

    o, al incorporar un trabajo de la 004, con ``out.write`` como función de escritura de
    ``core.provenance.operations.ingest_job``. En una importación, antes de preparar lo
    importado, :meth:`declare_input`. ``TypeError`` si ``handle`` no es un
    ``OperationHandle``; ``ValueError`` si es de otro proyecto."""

    def __init__(self, project: StoreProject, handle: OperationHandle) -> None:
        if not isinstance(handle, OperationHandle):
            raise TypeError(f"los resultados son de un OperationHandle, no {handle!r}")
        if handle.project_uid != project.uid:
            raise ValueError(f"la operación {handle.uid} es de otro proyecto")
        self.project = project
        self.handle = handle
        self._crs, self._vertical = project_references(project)
        self._outputs: list[_File | _Table] = []
        self._declared: _Declared | None = None
        self._record: InputRecord | None = None
        self._reused: Reuse | None = None
        self._committed: bool | None = None
        self._closed = False

    def __enter__(self) -> ResultWriter:
        return self

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None,
                 traceback: TracebackType | None) -> None:
        self.close(error)

    @property
    def specs(self) -> tuple[DatasetSpec, ...]:
        """Las salidas preparadas con su ubicación, en su orden (lo importado, cuando se
        registra su entrada)."""
        return tuple(output.spec for output in self._outputs if output.spec is not None)

    @property
    def input(self) -> InputRecord | None:
        """La entrada que registró la importación, una vez confirmada (incorporada con
        ``ingest_job``, al cerrar los resultados); si no, ``None``."""
        return self._record if self._committed else None

    @property
    def reused(self) -> Reuse | None:
        """La entrada reutilizada si la importación la encontró ya registrada igual."""
        return self._reused

    def _files(self) -> list[_File]:
        return [output for output in self._outputs if isinstance(output, _File)]

    # --- La entrada de una importación (T43) -------------------------------------------------

    def _previous(self, previous_uid: object, reason: object) -> tuple[InputRecord | None,
                                                                       str | None]:
        """La entrada activa a la que sustituye y el motivo, obligatorio (RF-008-11)."""
        if reason is not None and not isinstance(reason, str):
            raise TypeError(f"el motivo de una sustitución es un texto, no {reason!r}")
        if previous_uid is None:
            if reason is not None:
                raise ValueError("el motivo acompaña a una sustitución: falta la entrada "
                                 "sustituida (previous_uid)")
            return None, None
        if not isinstance(previous_uid, str):
            raise TypeError(f"la entrada sustituida se indica por su uid, no {previous_uid!r}")
        with self.project.read() as conn:
            record = get_input(conn, previous_uid)
        if record is None:
            raise ProvenanceError("core.input_unknown", input=previous_uid,
                                  project=self.project.name)
        if record.status is InputStatus.SUPERSEDED:
            raise ProvenanceError("core.input_superseded", name=record.name)
        if record.status is InputStatus.DISCARDED:
            raise ProvenanceError("core.input_previous_discarded", previous=record.name)
        text = None if reason is None else reason.strip()
        if not text:
            raise ProvenanceError("core.input_supersede_reason_missing", name=record.name)
        return record, text

    def declare_input(
        self,
        spec: InputSpec,
        *,
        previous_uid: str | None = None,
        reason: str | None = None,
    ) -> Classification:
        """Declara la entrada ``spec`` (:func:`source_input`) que importa esta operación (una
        importación de la 006, con uno de sus lectores) y la clasifica antes de preparar nada
        (RF-008-54):

        - ``Reuse`` (la misma entrada con los mismos ajustes, sin ``previous_uid``): no se
          duplica; la operación queda «cancelada» con el aviso (``Reuse.text``,
          ``core.inputs.reuse_input``) y los resultados se cierran sin escribir nada;
        - ``Substitute`` (los mismos datos con otros ajustes): tiene que llegar con
          ``previous_uid`` (esa entrada) y ``reason``, el motivo (RF-008-11); si no,
          ``ProvenanceError`` ``core.input_substitution_required`` sin escribir nada;
        - ``New``: una entrada nueva (o la que sustituye a ``previous_uid``, al
          actualizarla).

        La entrada se registra al confirmar, en la transacción que escribe lo importado.
        ``ProvenanceError`` también sin CRS declarado (``core.input_crs_missing``), con un
        nombre lógico de otra entrada activa (``core.input_name_taken``) y con una
        ``previous_uid`` que no se puede sustituir o sin motivo; ``ValueError`` si la operación
        no es una importación con ese lector, si ya declaró una entrada o si ya preparó algún
        resultado; ``TypeError`` si ``spec`` no es un ``InputSpec``."""
        self._check_open()
        if not isinstance(spec, InputSpec):
            raise TypeError(f"una importación declara un InputSpec, no {type(spec).__name__}")
        declared = OPERATION_TYPES_BY_NAME.get(self.handle.op_type)
        if declared is None or not declared.readers:
            raise ValueError(f"solo una importación de la topografía declara su entrada, no "
                             f"«{self.handle.op_type}»")
        if spec.module != MODULE or spec.reader not in declared.readers:
            raise ValueError(f"«{self.handle.op_type}» importa con {list(declared.readers)}, no "
                             f"una entrada de «{spec.module}» con «{spec.reader}»")
        if self._declared is not None:
            raise ValueError(f"la importación ({self.handle.uid}) ya declaró su entrada "
                             f"«{self._declared.spec.name}»")
        if self._outputs:
            raise ValueError("la entrada se declara antes de preparar lo importado")
        previous, text = self._previous(previous_uid, reason)
        with self.project.read() as conn:
            found = classify_import(conn, spec)
            same_name = get_input(conn, spec.name)
        mismatched = previous is None or _found_uid(found) != previous.uid
        if isinstance(found, Substitute) and mismatched:
            raise ProvenanceError("core.input_substitution_required", name=spec.name,
                                  existing=found.input.name, differences=found.describe())
        if isinstance(found, Reuse) and previous is None:
            reuse_input(self.project, self.handle, found)
            self._reused = found
            self._closed = True
            return found
        if (same_name is not None and same_name.active
                and (previous is None or same_name.uid != previous.uid)):
            raise ProvenanceError("core.input_name_taken", name=spec.name)
        crs, vertical = _references(spec)
        self._declared = _Declared(spec, previous, text, crs, vertical, _import_families(spec))
        return found

    def _imported(self, family: str) -> bool:
        """Comprueba que la operación produce la familia ``family`` y dice si es lo importado
        de su entrada (en una importación, que ya la declaró y la produce)."""
        declared = OPERATION_TYPES_BY_NAME.get(self.handle.op_type)
        if declared is not None and family not in declared.outputs:
            raise ValueError(f"«{self.handle.op_type}» no produce datos «{family}»: produce "
                             f"{list(declared.outputs)}")
        if self.handle.op_type not in IMPORTS:
            return False
        if self._declared is None:
            raise ValueError("lo importado es de una entrada: la importación la declara antes "
                             "(declare_input)")
        if family not in self._declared.families:
            raise ValueError(f"la entrada «{self._declared.spec.name}» no produce datos "
                             f"«{family}»: produce {list(self._declared.families)}")
        return True

    # --- Preparar --------------------------------------------------------------------------

    def _check_open(self) -> None:
        if self._closed or self._committed:
            raise RuntimeError(f"los resultados de la operación «{self.handle.op_type}» "
                               f"({self.handle.uid}) ya se confirmaron o se cerraron")

    def _dataset(self, family: str, name: str) -> str:
        """El nombre del dato, que la operación escribe una vez."""
        found = dataset_name(family, name)
        if any(output.dataset == found for output in self._outputs):
            raise ValueError(f"una operación escribe cada dato una vez: «{found}» se repite")
        return found

    def _check_place(self, conn: sqlite3.Connection, spec: DatasetSpec) -> None:
        """El sitio de ``spec`` está libre o es del mismo dato vivo (si no, ``_taken``)."""
        owned, others = _owned(conn, spec)
        if spec.store is Store.GPKG:
            exists = _table_exists(conn, spec.locator)
        else:
            exists = Path(self.project.root, *spec.locator.split("/")).exists()
        if others or (exists and not owned):
            raise _taken(spec)

    def _plan_file(self, family: str, name: str, content: ContentDigest,
                   crs_epsg: int | None, imported: bool) -> _File:
        dataset = self._dataset(family, name)
        if imported:  # su ubicación lleva su entrada (D22): se sabe al registrarla
            found = FAMILIES_BY_CODE[family]
            path = Path(self.project.root, str(found.store), dataset + found.extension)
            entry = _File(dataset, family, name, content, crs_epsg, path,
                          temporary_path(self.project, path))
            check_path_length(entry.temporary, obj=path.name)
            self.handle.claim_paths(entry.temporary)
        else:
            spec = dataset_spec(family, name, content=content, crs_epsg=crs_epsg)
            final = Path(self.project.root, *spec.locator.split("/"))
            entry = _File(dataset, family, name, content, crs_epsg, final,
                          temporary_path(self.project, final), spec, final,
                          backup_path(self.project, final))
            for path in (entry.temporary, entry.backup):
                check_path_length(path, obj=final.name)
            with self.project.read() as conn:
                self._check_place(conn, spec)
            self.handle.claim_paths(entry.temporary, final, entry.backup)
        try:
            entry.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise write_failed(entry.path.name, error) from None
        self._outputs.append(entry)
        return entry

    def raster(
        self,
        name: str,
        raster: Raster,
        *,
        family: str = PROJECT_GRID,
        progress: Progress | None = None,
        cancelled: Cancelled | None = None,
    ) -> DatasetSpec | None:
        """Prepara la rejilla ``raster`` como el dato ``gis_<familia>_<nombre>``: por defecto,
        la rejilla del proyecto (``gis_dtm_``, en su CRS y su referencia vertical; si no,
        ``ValueError``); ``gis_src_``, lo importado de la entrada que declaró la importación,
        en el CRS y la referencia vertical declarados. Su hash (``gis.content.raster_digest``)
        y su GeoTIFF del perfil ``project`` en el temporal. Devuelve su ``DatasetSpec`` (lo
        importado, ``None``: su ubicación se sabe al registrar la entrada). ``GisError`` si su
        sitio es de otro (``gis.output_target_taken``) o falla el disco; ``JobCancelled`` si
        ``cancelled()`` pide parar entre teselas."""
        if not isinstance(raster, Raster):
            raise TypeError(f"se escribe un Raster, no {type(raster).__name__}")
        _family(family, GRID_FAMILIES)
        if family == PROJECT_GRID and (raster.crs.epsg != self._crs.epsg
                                       or raster.vertical != self._vertical):
            raise ValueError(
                f"la rejilla del proyecto «{name}» va en el CRS y la referencia vertical del "
                f"proyecto (EPSG:{self._crs.epsg} + {_vertical_text(self._vertical)}), no en "
                f"EPSG:{raster.crs.epsg} + {_vertical_text(raster.vertical)}: remuestréela antes"
            )
        self._check_open()
        imported = self._imported(family)
        if imported and self._declared is not None and (
                raster.crs.epsg != self._declared.crs.epsg
                or raster.vertical != self._declared.vertical):
            raise ValueError(f"lo importado de «{self._declared.spec.name}» va en el CRS y la "
                             "referencia vertical que declara su entrada")
        entry = self._plan_file(family, name, raster_digest(raster, DATASET_DECLARATIONS),
                                raster.crs.epsg, imported)
        write_geotiff(raster, entry.path, profile=WriteProfile.PROJECT,
                      temporary=entry.temporary, replace=False, progress=progress,
                      cancelled=cancelled)
        return entry.spec

    def tin(self, name: str, tin: Tin) -> DatasetSpec:
        """Prepara el TIN ``tin`` (absoluto, en el CRS y la referencia vertical del proyecto)
        como ``gis_tin_<nombre>``: su ``meta`` (el EPSG y la referencia vertical del proyecto
        y esta operación), su hash (``gis.content.tin_digest``) y su npz en el temporal.
        ``GisError`` si su sitio es de otro o falla el disco."""
        if not isinstance(tin, Tin):
            raise TypeError(f"se escribe un Tin, no {type(tin).__name__}")
        self._check_open()
        self._imported(TIN)
        meta = {"crs_epsg": self._crs.epsg, "vertical": _vertical_text(self._vertical),
                "operation_uid": self.handle.uid}
        entry = self._plan_file(TIN, name, tin_digest(tin, meta, DATASET_DECLARATIONS),
                                self._crs.epsg, False)
        try:
            save_tin(tin, entry.path, meta, temporary=entry.temporary, replace=False)
        except OSError as error:
            raise write_failed(entry.path.name, error) from None
        assert entry.spec is not None
        return entry.spec

    def copy_file(
        self,
        family: str,
        name: str,
        source: Path | str,
        *,
        content: ContentDigest,
        sha256: str | None = None,
        crs_epsg: int | None = None,
        progress: Progress | None = None,
        cancelled: Cancelled | None = None,
    ) -> DatasetSpec | None:
        """Prepara el fichero ``source`` que dejó un trabajo de la 004 en su ``out/`` (una
        rejilla del perfil ``project`` o un npz de TIN) como el dato de ``family`` llamado
        ``name`` (``gis_src_``: lo importado de la entrada declarada), con el ``content`` que
        calculó el trabajo con el lector del dato: lo copia al temporal por trozos de
        :data:`COPY_CHUNK_BYTES` con su huella, que tiene que ser ``sha256`` si se da (si no,
        ``gis.output_copy_mismatch``). ``crs_epsg``: por defecto, el del proyecto en la rejilla
        del proyecto y el TIN, y el declarado en lo importado. Devuelve su ``DatasetSpec``
        (lo importado, ``None``). ``JobCancelled`` si ``cancelled()`` pide parar entre
        trozos."""
        _family(family, FILE_FAMILIES)
        if not isinstance(content, ContentDigest):
            raise TypeError(f"el hash del trabajo es un ContentDigest, no {content!r}")
        self._check_open()
        imported = self._imported(family)
        if crs_epsg is None and family in (PROJECT_GRID, TIN):
            crs_epsg = self._crs.epsg
        if crs_epsg is None and imported and self._declared is not None:
            crs_epsg = self._declared.crs.epsg
        entry = self._plan_file(family, name, content, crs_epsg, imported)
        found = _copy(Path(source), entry.temporary, entry.path.name, progress, cancelled)
        if sha256 is not None and found != sha256:
            entry.temporary.unlink(missing_ok=True)
            raise GisError("gis.output_copy_mismatch", obj=f"{_OBJ} «{entry.dataset}»",
                           field="huella", value=found, file=entry.path.name,
                           detail=f"sha256 {found[:12]}… frente a {sha256[:12]}…")
        return entry.spec

    def _plan_table(self, family: str, name: str, rows: list[tuple[Any, ...]],
                    extent: tuple[float, float, float, float] | None,
                    imported: bool) -> DatasetSpec | None:
        """Prepara la tabla de ``family``: lo calculado, con su ubicación ya comprobada; lo
        importado, en el CRS y la referencia declarados, con su ubicación al registrar su
        entrada."""
        layout = TABLE_LAYOUTS[family]
        dataset = self._dataset(family, name)
        if imported:
            assert self._declared is not None
            self._outputs.append(_Table(dataset, family, name, layout, tuple(rows), extent,
                                        self._declared.crs, self._declared.vertical))
            return None
        spec = dataset_spec(family, name, crs_epsg=self._crs.epsg)
        identifier = f"{layout.label}: {name} ({spec.locator})"
        with self.project.read() as conn:
            clash = conn.execute(
                "SELECT 1 FROM gpkg_contents WHERE identifier = ? AND lower(table_name) <> "
                "lower(?)", (identifier, spec.locator)).fetchone()
            if clash is not None:
                raise _taken(spec)
            self._check_place(conn, spec)
        description = f"{layout.label} de Geoblender; {_z_description(self._vertical)}"
        self._outputs.append(_Table(dataset, family, name, layout, tuple(rows), extent,
                                    self._crs, self._vertical, spec, identifier, description))
        return spec

    def _srs(self, imported: bool) -> int:
        """El SRS de las coordenadas: el declarado en lo importado; si no, el del proyecto."""
        if imported and self._declared is not None:
            return self._declared.crs.epsg
        return self._crs.epsg

    def contours(self, name: str, lines: Iterable[ContourLine]) -> DatasetSpec | None:
        """Prepara las curvas ``lines`` como la tabla ``gis_cnt_<nombre>`` (plan §5.2.3): una
        fila por curva con su geometría ``LINESTRING`` con Z (la cerrada, con su primer
        vértice repetido al final), su cota, si es maestra, si es cerrada y su longitud en
        planta. Calculadas (``gis.contours``), absolutas en el CRS y la referencia vertical del
        proyecto; importadas de una capa (``gis.import_vector`` con el papel ``contours``), lo
        importado de su entrada, en los declarados. La tabla se escribe al confirmar; su hash,
        el del registro. Devuelve su ``DatasetSpec`` (lo importado, ``None``). ``GisError`` si
        su sitio es de otro."""
        chosen = list(lines)
        for line in chosen:
            if not isinstance(line, ContourLine):
                raise TypeError(f"una curva de nivel es un ContourLine, no {line!r}")
        self._check_open()
        imported = self._imported(CONTOUR_LINES)
        layout = TABLE_LAYOUTS[CONTOUR_LINES]
        srs = self._srs(imported)
        rows: list[tuple[Any, ...]] = []
        coords_all: list[np.ndarray] = []
        for line in chosen:
            coords = np.vstack([line.xyz, line.xyz[:1]]) if line.closed else line.xyz
            rows.append((encode_geometry(layout.geometry_type, coords, srs, layout.has_z),
                         float(line.elevation), int(bool(line.is_index)),
                         int(bool(line.closed)), line.length_m))
            coords_all.append(coords)
        return self._plan_table(CONTOUR_LINES, name, rows, _extent(coords_all), imported)

    def points(self, name: str, points: PointSet) -> DatasetSpec | None:
        """Prepara los puntos importados ``points`` (de un texto o de una capa) como la tabla
        ``gis_pts_<nombre>_<entrada8>`` (plan §5.2.3): un ``POINT`` con Z por punto, con las
        coordenadas tal como llegan (float64, en el CRS y la referencia declarados,
        RF-006-12), su identificador, su código y su fila (o entidad) de origen. Lo importado
        de la entrada declarada: devuelve ``None`` (su ubicación, al registrarla)."""
        if not isinstance(points, PointSet):
            raise TypeError(f"los puntos son un PointSet, no {type(points).__name__}")
        self._check_open()
        imported = self._imported(POINTS)
        layout = TABLE_LAYOUTS[POINTS]
        srs = self._srs(imported)
        rows = [(encode_geometry(layout.geometry_type, xyz, srs, layout.has_z), str(point_id),
                 str(code), int(row))
                for xyz, point_id, code, row in zip(points.xyz, points.point_ids, points.codes,
                                                    points.source_rows, strict=True)]
        return self._plan_table(POINTS, name, rows, _extent([points.xyz] if len(points) else []),
                                imported)

    def breaklines(self, name: str, lines: Iterable[Breakline]) -> DatasetSpec | None:
        """Prepara las líneas de rotura importadas ``lines`` como la tabla
        ``gis_brk_<nombre>_<entrada8>`` (plan §5.2.3): un ``LINESTRING`` con Z por línea, con
        sus vértices tal como llegan, su identificador, si es dura y su código. Lo importado
        de la entrada declarada: devuelve ``None``."""
        chosen = list(lines)
        for line in chosen:
            if not isinstance(line, Breakline):
                raise TypeError(f"una línea de rotura es un Breakline, no {line!r}")
        self._check_open()
        imported = self._imported(BREAKLINES)
        layout = TABLE_LAYOUTS[BREAKLINES]
        srs = self._srs(imported)
        rows = [(encode_geometry(layout.geometry_type, line.xyz, srs, layout.has_z),
                 str(line.line_id), int(bool(line.hard)), str(line.code)) for line in chosen]
        return self._plan_table(BREAKLINES, name, rows, _extent(line.xyz for line in chosen),
                                imported)

    def boundary(self, name: str, polygons: Iterable[Any], *,
                 holes: Iterable[Any] = ()) -> DatasetSpec | None:
        """Prepara los contornos importados como la tabla ``gis_bnd_<nombre>_<entrada8>``
        (plan §5.2.3): un ``MULTIPOLYGON`` sin Z por contorno (``polygons``, papel
        «boundary») o por hueco (``holes``, «hole»); cada uno, una ``Geometry`` de polígonos
        (de ``gis.vector.read_layer``), un anillo o una lista de anillos, con sus X e Y tal
        como llegan (cada anillo, cerrado). Lo importado de la entrada declarada: devuelve
        ``None``."""
        chosen = [(item, BOUNDARY_ROLES[0]) for item in polygons]
        chosen += [(item, BOUNDARY_ROLES[1]) for item in holes]
        self._check_open()
        imported = self._imported(BOUNDARY)
        layout = TABLE_LAYOUTS[BOUNDARY]
        srs = self._srs(imported)
        rows: list[tuple[Any, ...]] = []
        rings: list[np.ndarray] = []
        for item, role in chosen:
            parts = _polygons(item)
            rows.append((encode_geometry(layout.geometry_type, parts, srs, layout.has_z), role))
            rings += [ring for polygon in parts for ring in polygon]
        return self._plan_table(BOUNDARY, name, rows, _extent(rings), imported)

    # --- Poner en su sitio y confirmar --------------------------------------------------------

    def install(self) -> None:
        """Pone cada fichero preparado en su sitio: aparta el anterior del mismo dato a
        :func:`backup_path` y pasa el temporal al destino con ``os.replace``. Si otro programa
        tiene abierto el destino, ``gis.raster_target_locked`` (el anterior, intacto); otro
        fallo del disco, ``gis.raster_write_failed``. Lo ya puesto se deshace al cerrar sin
        confirmar. Lo importado espera a que se registre su entrada (su destino lleva su uid).
        Volver a llamarla no hace nada más."""
        self._check_open()
        for entry in self._files():
            if entry.installed or entry.final is None or entry.backup is None:
                continue
            if entry.final.exists():
                try:
                    os.replace(entry.final, entry.backup)
                except OSError as error:
                    raise _disk_error(entry.final.name, error) from None
                entry.replaced = True
            try:
                os.replace(entry.temporary, entry.final)
            except OSError as error:
                failure = _disk_error(entry.final.name, error)
                for problem in _restore(entry) if entry.replaced else []:
                    failure.add_note(problem)
                raise failure from None
            entry.installed = True

    def _register_input(self, conn: sqlite3.Connection) -> None:
        """En la transacción ``conn``: la entrada sustituida, ``supersede``; la entrada,
        ``register_input``; y lo importado, con su ubicación (D22), comprobada y reclamada."""
        if self._declared is None:
            if self.handle.op_type in IMPORTS:
                raise ValueError(f"la importación «{self.handle.op_type}» registra su entrada: "
                                 "declárela antes (declare_input)")
            return
        if self._record is not None:
            return
        declared = self._declared
        previous_uid = None if declared.previous is None else declared.previous.uid
        if previous_uid is not None:
            supersede(conn, self.project, previous_uid, operation_uid=self.handle.uid,
                      reason=declared.reason)
        record = register_input(conn, self.project, declared.spec,
                                operation_uid=self.handle.uid, previous_uid=previous_uid,
                                reason=declared.reason)
        self._record = record
        for output in self._outputs:
            if output.spec is not None:
                continue
            if isinstance(output, _File):
                self._place_file(conn, output, record)
            else:
                self._place_table(conn, output, record)

    def _place_file(self, conn: sqlite3.Connection, entry: _File, record: InputRecord) -> None:
        spec = dataset_spec(entry.family, entry.name, input_uid=record.uid,
                            content=entry.content, crs_epsg=entry.crs_epsg)
        final = Path(self.project.root, *spec.locator.split("/"))
        check_path_length(final, obj=final.name)
        self._check_place(conn, spec)
        self.handle.claim_paths(final)
        entry.spec, entry.final = spec, final
        entry.backup = backup_path(self.project, final)

    def _place_table(self, conn: sqlite3.Connection, table: _Table,
                     record: InputRecord) -> None:
        spec = dataset_spec(table.family, table.name, input_uid=record.uid,
                            crs_epsg=table.crs.epsg)
        layout = table.layout
        identifier = f"{layout.label}: {table.name} ({spec.locator})"
        if conn.execute("SELECT 1 FROM gpkg_contents WHERE identifier = ?",
                        (identifier,)).fetchone() is not None:
            raise _taken(spec)
        self._check_place(conn, spec)
        description = f"{layout.label}: lo importado de la entrada «{record.name}» por Geoblender"
        if layout.has_z:
            description += f"; {_z_description(table.vertical)}"
        table.spec, table.identifier, table.description = spec, identifier, description

    def write(self, conn: sqlite3.Connection) -> tuple[DatasetSpec, ...]:
        """Lo que se hace en la transacción de escritura ``conn`` que confirma la operación
        (la de :meth:`commit` o la de ``ingest_job``): registra la entrada de una importación
        (y marca sustituida la que sustituye), pone los ficheros en su sitio si aún no lo
        están (:meth:`install`), escribe las tablas (una que ya es del dato, con sus filas
        nuevas) y devuelve las salidas para ``OperationHandle.complete``."""
        if not isinstance(conn, sqlite3.Connection) or not conn.in_transaction:
            raise ValueError("los resultados se escriben en una transacción de escritura del "
                             "proyecto (Project.write_transaction)")
        self._register_input(conn)
        self.install()
        for output in self._outputs:
            if isinstance(output, _Table):
                self._write_table(conn, output)
        return self.specs

    def _write_table(self, conn: sqlite3.Connection, table: _Table) -> None:
        spec, layout = table.spec, table.layout
        assert spec is not None and table.identifier is not None
        owned, others = _owned(conn, spec)
        exists = _table_exists(conn, spec.locator)
        if others or (exists and not owned):
            raise _taken(spec)
        if exists:
            conn.execute(f'DELETE FROM "{spec.locator}"')
        else:
            _ensure_srs(conn, table.crs)
            create_feature_table(conn, spec.locator, layout.geometry_type, table.crs.epsg,
                                 layout.has_z, layout.columns, table.identifier,
                                 table.description or "")
        names = [_GEOMETRY_COLUMN, *(column.name for column in layout.columns)]
        conn.executemany(
            f'INSERT INTO "{spec.locator}" ({", ".join(names)}) '
            f'VALUES ({", ".join("?" for _ in names)})',
            table.rows,
        )
        conn.execute("UPDATE gpkg_contents SET min_x = ?, min_y = ?, max_x = ?, max_y = ? "
                     "WHERE table_name = ?",
                     (*(table.extent or (None, None, None, None)), spec.locator))

    def commit(
        self,
        *,
        software: Any = None,
        interpreter: Any = None,
        message: str | None = None,
        executor: Any = None,
        job_uid: str | None = None,
    ) -> tuple[DatasetRecord, ...]:
        """Confirma la operación: los ficheros en su sitio (:meth:`install`) y, en una
        transacción, la entrada de una importación, las tablas y ``OperationHandle.complete``
        con las salidas y ``software``, ``interpreter``, ``message``, ``executor`` y
        ``job_uid`` (RF-008-18); después borra lo anterior apartado. Devuelve las salidas
        registradas, en su orden. Si algo falla, se deshace todo lo de esta operación y queda
        «fallida» o «cancelada» con su motivo (RF-008-19), y el error sigue."""
        try:
            self.install()
            with self.project.write_transaction() as conn:
                specs = self.write(conn)
                records = self.handle.complete(
                    conn, outputs=specs, software=software, interpreter=interpreter,
                    message=message, executor=executor, job_uid=job_uid,
                )
        except BaseException as error:
            self.close(error)
            raise
        self._committed = True
        self.close()
        return records

    def originals(
        self,
        verified_copies: Sequence[str | os.PathLike[str]],
        *,
        budget_s: float = STEP_BUDGET_S,
        same_volume: Callable[[Path, Path], bool] | None = None,
    ) -> Iterator[ProjectProgress]:
        """Los pasos que guardan el original de la entrada que registró esta importación
        (RF-008-53; ``core.inputs.store_originals_steps``) desde ``verified_copies``, la copia
        verificada de cada fichero que hizo su trabajo (``JobDir.copy_input``), nunca la
        fuente (RF-008-14): el de un texto de puntos se guarda en ``originals/<entrada>/`` con
        su huella; de un ráster o de una capa, no (el último paso lo dice). ``RuntimeError``
        si la importación no se confirmó."""
        if not self._committed or self._record is None:
            raise RuntimeError(f"la operación «{self.handle.op_type}» ({self.handle.uid}) no "
                               "registró ninguna entrada: el original se guarda tras confirmar "
                               "su importación")
        return store_originals_steps(self.project, self._record.uid, verified_copies,
                                     budget_s=budget_s, same_volume=same_volume)

    # --- Cerrar ----------------------------------------------------------------------------

    def close(self, error: BaseException | None = None) -> None:
        """Termina: si la operación quedó «hecha», borra lo anterior apartado; si no, deshace
        lo puesto en su sitio y borra los temporales. Con ``error`` (el que paró el bloque) y la
        operación aún «en curso», la deja «cancelada» o «fallida» con su motivo; si no se puede
        registrar, se dice en una nota del error. Volver a llamarla no hace nada."""
        if self._closed:
            return
        self._closed = True
        problems: list[str] = []
        files = self._files()
        # Incorporada con ingest_job, la confirmó su transacción: se mira en el proyecto.
        if self._committed is None and (self._record is not None
                                        or any(entry.installed for entry in files)):
            try:
                self._committed = self._status() == OperationStatus.DONE
            except (GeoblenderError, OSError, sqlite3.Error) as exc:
                problems.append(f"no se pudo saber si la operación se confirmó ({exc}); sus "
                                "ficheros se dejan como están")
        if self._committed:
            for entry in files:
                if entry.backup is not None:
                    _discard(entry.backup)
        else:
            self._record = None
            if not problems:
                for entry in reversed(files):
                    problems.extend(_undo(entry))
        if error is not None and not self._committed:
            problems.extend(self._abandon(error))
        if error is not None:
            for problem in problems:
                error.add_note(problem)

    def _status(self) -> str | None:
        with self.project.read() as conn:
            row = conn.execute("SELECT status FROM gb_operation WHERE uid = ?",
                               (self.handle.uid,)).fetchone()
        return None if row is None else str(row[0])

    def _abandon(self, error: BaseException) -> list[str]:
        """La operación, si sigue «en curso», «cancelada» o «fallida» con su motivo."""
        cancelled = isinstance(error, CANCELLATIONS)
        what = "cancelación" if cancelled else "fallo"
        try:
            if self._status() != OperationStatus.RUNNING:
                return []
            if cancelled:
                self.handle.cancel(cancel_reason(error))
            else:
                self.handle.fail(failure_reason(error))
        except (GeoblenderError, OSError, sqlite3.Error) as exc:
            return [f"La operación «{self.handle.op_type}» ({self.handle.uid}) sigue «en "
                    f"curso» en el proyecto: no se pudo registrar su {what} ({exc})."]
        return []


def _found_uid(found: Classification) -> str | None:
    """El uid de la entrada que encontró la clasificación (``None`` si es nueva)."""
    return found.input.uid if isinstance(found, Reuse | Substitute) else None


def _copy(source: Path, target: Path, name: str, progress: Progress | None,
          cancelled: Cancelled | None) -> str:
    """Copia ``source`` en ``target`` por trozos con su sha256 (``fsync`` al final); si falla
    o se cancela, borra ``target``."""
    digest = hashlib.sha256()
    try:
        size = source.stat().st_size
        total = max(1, -(-size // COPY_CHUNK_BYTES))
        with source.open("rb") as reader, target.open("wb") as writer:
            for index in range(total):
                if cancelled is not None and cancelled():
                    raise JobCancelled(f"Cancelado al copiar «{name}» en el trozo {index + 1} "
                                       f"de {total}")
                chunk = reader.read(COPY_CHUNK_BYTES)
                digest.update(chunk)
                writer.write(chunk)
                if progress is not None:
                    progress((index + 1) / total,
                             f"Copiando «{name}»: trozo {index + 1} de {total}")
            rest = reader.read()
            digest.update(rest)
            writer.write(rest)
            writer.flush()
            os.fsync(writer.fileno())
    except BaseException as error:
        _discard(target)
        if isinstance(error, OSError):
            raise write_failed(name, error) from None
        raise
    return digest.hexdigest()


def _discard(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _restore(entry: _File) -> list[str]:
    """Devuelve a su sitio el fichero anterior apartado."""
    assert entry.final is not None and entry.backup is not None
    try:
        os.replace(entry.backup, entry.final)
    except OSError as exc:
        return [f"No se pudo devolver a su sitio «{entry.final.name}» ({exc}): el anterior "
                f"está en «{entry.backup.name}» y se apartará a orphans/ al volver a abrir el "
                "proyecto."]
    entry.replaced = False
    return []


def _undo(entry: _File) -> list[str]:
    """Deshace lo de un fichero sin confirmar: el anterior vuelve (o lo nuevo se borra) y el
    temporal se borra."""
    problems: list[str] = []
    if entry.installed and entry.final is not None:
        if entry.replaced:
            problems.extend(_restore(entry))
        else:
            try:
                entry.final.unlink(missing_ok=True)
            except OSError as exc:
                problems.append(f"No se pudo borrar «{entry.final.name}» ({exc}), escrito por "
                                "una operación que no se confirmó: se apartará a orphans/ al "
                                "volver a abrir el proyecto.")
        entry.installed = False
    _discard(entry.temporary)
    return problems


# --- Lectura de lo guardado --------------------------------------------------------------------


def list_gis_datasets(
    project: StoreProject,
    kinds: Iterable[str] | None = None,
    *,
    families: Iterable[str] | None = None,
) -> list[DatasetRecord]:
    """Los datos vivos de la topografía registrados en ``gb_dataset`` (vigentes, que faltan,
    bloqueados o dañados), por nombre; solo los de los tipos ``kinds`` (``"raster"``,
    ``"mesh"``, ``"vector"``) o de las familias ``families`` (``"dtm"``, ``"tin"``…), si se
    dan. ``ValueError`` con una familia que no es de la 006."""
    chosen_kinds = None if kinds is None else frozenset(kinds)
    prefixes = None if families is None else tuple(
        _family(code, tuple(FAMILIES_BY_CODE)).prefix for code in families)
    live = tuple(str(status) for status in LIVE_STATUSES)
    with project.read() as conn:
        rows = conn.execute(
            f"SELECT {', '.join(RECORD_COLUMNS)} FROM gb_dataset WHERE module = ? AND status "
            f"IN ({', '.join('?' for _ in live)}) ORDER BY name",
            (MODULE, *live),
        ).fetchall()
    found = [DatasetRecord.from_row(row) for row in rows]
    return [record for record in found
            if (chosen_kinds is None or record.kind in chosen_kinds)
            and (prefixes is None or record.name.startswith(prefixes))]


def _resolve(project: StoreProject, ref: DatasetRecord | str,
             allowed: Sequence[str]) -> DatasetRecord:
    if isinstance(ref, DatasetRecord):
        record: DatasetRecord | None = ref
    elif isinstance(ref, str):
        with project.read() as conn:
            record = dataset_registry.get(conn, ref)
        if record is not None and record.module != MODULE:
            record = None
    else:
        raise TypeError(f"un dato se indica por su nombre, su uid o su registro, no {ref!r}")
    if record is None:
        raise GisError("gis.dataset_unknown", obj=_OBJ, field=_FIELD_DATASET, value=ref)
    prefixes = tuple(FAMILIES_BY_CODE[code].prefix for code in allowed)
    if not record.name.startswith(prefixes):
        raise ValueError(f"«{record.name}» no es un dato de {', '.join(allowed)}")
    return record


def _file_of(project: StoreProject, record: DatasetRecord) -> Path:
    path = Path(project.root, *record.locator.split("/"))
    if not path.is_file():
        raise GisError("gis.dataset_file_missing", obj=f"{_OBJ} «{record.name}»",
                       field=_FIELD_LOCATION, value=record.locator, file=path.name,
                       name=record.name)
    return path


def load_raster(
    project: StoreProject,
    ref: DatasetRecord | str,
    *,
    catalog: CrsCatalog | None = None,
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> Raster:
    """La rejilla guardada del dato ``ref`` (su registro, su uid o su nombre: ``gis_dtm_`` o
    ``gis_src_``), con las mismas celdas que se escribieron, el CRS que declara el fichero y su
    referencia vertical (la del proyecto si el fichero no la declara: una referencia local).
    Sin el límite de celdas de la importación. ``GisError`` ``gis.dataset_unknown`` si no hay
    un dato de ``gis`` así y ``gis.dataset_file_missing`` si falta su fichero; ``ValueError``
    si es de otra familia."""
    record = _resolve(project, ref, GRID_FAMILIES)
    path = _file_of(project, record)
    source = read_geotiff(path, max_cells=sys.maxsize, catalog=catalog, progress=progress,
                          cancelled=cancelled)
    crs, vertical = project_references(project, catalog=catalog)
    return Raster(source.grid, source.values, source.declared_crs or crs,
                  source.declared_vertical or vertical)


def load_tin(project: StoreProject, ref: DatasetRecord | str) -> Tin:
    """El TIN guardado del dato ``ref`` (``gis_tin_``) con su ``meta``. Los mismos errores que
    :func:`load_raster`; un fichero que no es el de un TIN, ``gis.tin_file_invalid``."""
    record = _resolve(project, ref, (TIN,))
    return read_tin_file(_file_of(project, record))

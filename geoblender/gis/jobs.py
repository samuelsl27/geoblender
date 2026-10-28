# SPDX-License-Identifier: GPL-3.0-or-later
"""Los trabajos de la topografía (spec 006, T26; RF-006-28, RF-006-26; RF-008-09, RF-008-20;
plan 006 §5.3.4 y §5.6.4; ADR-0010; plan 004 §5.3.1).

Lo que puede pasar de 1 s va a los trabajos de la 004 (RF-006-28: progreso en la barra de
estado y cancelación). Este módulo declara sus diez tipos (:data:`WORKER_INFOS`, cada uno con
su estimador de duración y su función ``run``) y ``bl/ops/gis.py`` los registra con
``jobs.catalog.register_worker``: ``jobs/`` no importa ``gis`` (ARQ-07). Cada
``workers/<tipo>.py`` envuelve la misma función (registra antes los lectores de ``gis``), así
que el hilo de Blender y el proceso aparte hacen lo mismo. Todos en el entorno ``blender``
(sin motor de cálculo); automáticos (en el hilo si se estiman en ≤ 5 s, RF-004-03) salvo
``gis_triangulate``, siempre en proceso aparte.

**La petición nunca lleva una ruta** (ARQ-11): una fuente externa llega por la línea de
órdenes (``JobRunner.submit(paths=…)``, ``--path source_main=…``; el ``.prj`` de un ASC,
``source_prj``) y el trabajo la copia a ``in/`` con ``JobDir.copy_input`` (huella antes,
durante y después, con su avance cada MiB: T33); lo del proyecto (una rejilla, un TIN,
puntos) lo copia ``bl`` a ``in/`` antes de lanzarlo (``request.inputs``). Los parámetros van
resueltos (los del proyecto, ``handle.params``; los de control, su valor) y la operación, en
``operation_uid``. Ningún paso sin avance pasa de medio segundo con 11,2 M celdas (RF-006-28,
T33): la copia, su huella y el hash de la rejilla escrita avisan por trozos.

**Resultados** en ``out/`` con su huella (``WorkerContext.add_output``, con el papel de
:class:`JobOutput`) y un **resumen** JSON con el ``ContentDigest`` de la fuente
(importaciones: el que da ``core_content_hash`` con las mismas declaraciones,
``gis.store.source_declarations``), las huellas de cada fichero de la fuente (sha256, tamaño y
fecha) y, en ``outputs``, el ``ContentDigest`` de cada fichero que será un dato del proyecto
(una rejilla, con ``gis.geotiff@1``; un TIN, con ``core.npz_mesh@1``; lo importado en una
tabla, con ``core.gpkg_layer@1`` sobre las filas que escribirá la orden en un GeoPackage en
memoria, :func:`_table_digests`, T50: así el hilo de Blender no vuelve a leer 300.000 puntos al
incorporarlos, RNF-006-09; las demás tablas lo calcula el registro al escribirlas, T42). Los
informes completos van en ``report.json`` (el resumen solo
lleva recuentos: cabe en el canal). Cancelar a mitad, o un fallo, deja ``out/`` vacía: nada a
medias ni entero (RF-006-28); un ``GisError`` (o cualquier error para el usuario) es un
``JobFailed`` con su código, su ``msgid``, sus valores y su texto en español (RF-004-12), y una
petición que no vale, ``request_invalid``.

Los tipos, con sus parámetros (las entradas de ``in/``, las rutas de ``--path``) y sus
resultados en ``out/``:

- ``gis_read_raster``: ``reader`` (``gis.geotiff@1``, ``gis.asc@1`` o ``gis.xyz_grid@1``),
  ``name``, ``settings`` (de lectura), ``crs`` y ``vertical`` (declarados; ``None``: los del
  fichero), ``prj_crs`` (el CRS que la orden reconoció en el ``.prj`` de un ASC con el
  servicio de CRS; sin él, la nota de que no se reconoció), ``max_cells``, ``size`` y
  ``origin`` (opcional: el GeoOrigin del proyecto, si la fuente está en su CRS horizontal);
  ``source_main`` [y ``source_prj``] → ``source.tif`` y ``samples.npy`` (T54: las
  posiciones con que la orden compara sus cotas con la rejilla del proyecto,
  ``gis.dtm.vertical_samples`` de lo escrito, RF-006-06; así el hilo de Blender no vuelve a
  leer la rejilla importada, RNF-006-09; :func:`write_samples`). Sus notas y sus fallos
  nombran el fichero del usuario, no su copia en ``in/`` (T52). Su resumen dice dónde caen
  las celdas con dato (T51; spec §8): su extensión (``data_extent``, :func:`window_json`) y, con
  ``origin``, el aviso de RF-002-26 de sus centros (``precision``, :func:`precision_json`;
  ``gis.placement``).
- ``gis_resample``: ``name``, ``source_crs``, ``source_vertical``, ``target_crs``,
  ``target_vertical``, ``target`` (la rejilla), ``method`` (``auto``, ``area_mean``,
  ``bilinear`` o ``mode``), ``min_valid_fraction``, ``supersample`` y ``size``; ``source``
  (``.tif``) → ``grid.tif`` y ``report.json``.
- ``gis_import_points``: ``reader`` (``gis.points_text@1``), ``name``, ``settings``,
  ``crs``, ``vertical`` y ``size``; ``source_main`` → ``points.npz``, ``lines.npz`` y
  ``report.json``; en el resumen, el hash de cada tabla que serán (T50).
- ``gis_tin_prepare``: ``name``, ``tol_xy``, ``tol_z``, ``duplicate_policy`` y ``count``;
  ``points`` y ``lines`` (``.npz``) → ``prepared.npz`` o, con conflictos,
  ``conflicts.json``.
- ``gis_triangulate``: ``name``, ``origin`` y ``count``; ``prepared`` → ``faces.npy``.
- ``gis_tin_finish``: ``name``, ``origin``, ``triangulator``, ``max_edge_m``, ``crs``,
  ``vertical`` y ``count``; ``prepared``, ``faces`` [y ``regions``]; la operación de la
  petición (``operation_uid``) → ``tin.npz`` y ``report.json``.

Los puntos y lo preparado de un TIN pueden llegar también como arrays sueltos
(``points_<array>``, ``prepared_<array>``: :func:`point_inputs` y :func:`tin_inputs`), que
``bl`` escribe en ``in/`` sin copiarlos ni releerlos (``JobDir.write_array``; spec 006, T35:
la copia verificada de los 300.000 puntos de RNF-006-03 eran décimas de segundo del hilo de
Blender, RNF-006-09). Los ficheros de paso van sin comprimir y sus textos, en UTF-8.
- ``gis_contours``: ``name``, ``crs``, ``vertical``, ``interval_m``, ``base_m``,
  ``index_every_m``, ``index_offset_m``, ``simplify_m``, ``min_length_m`` y ``count``;
  ``source`` (``.tif`` o ``.npz``) → ``contours.npz``.
- ``gis_validate``: ``name``, ``crs``, ``vertical``, ``window``, ``z_range`` y ``count``;
  ``source`` → ``report.json``.
- ``gis_export``: ``format`` (``geotiff``, por defecto, o ``gpkg``), ``name``, ``crs``,
  ``vertical`` y ``count``; con ``geotiff``, ``source`` (``.tif``) → ``export.tif``, el GeoTIFF
  entregable; con ``gpkg`` (T31), ``layers`` (``.npz`` de :func:`write_export_layers`: las
  tablas del proyecto tal como están guardadas y, de cada TIN, el nombre de su entrada) y
  esos TIN (``tin_<n>``, ``.npz``) → ``export.gpkg`` (``gis.vector.write_layers``). Los dos,
  con el hash de contenido del fichero escrito (``gis.geotiff@1``, ``core.document@1``).
- ``gis_view_arrays``: ``name``, ``crs``, ``vertical``, ``lod_steps`` y ``count``;
  ``source`` → ``mesh.npz``.

Los que añade la T29 (RF-006-12, RF-006-16, RF-006-17):

- ``gis_import_vector``: ``reader`` (``gis.gpkg_layer@1``), ``name``, ``settings`` (``layer``,
  ``role`` y, en curvas, ``elevation_field``), ``crs`` (``None``: el de la capa),
  ``vertical``, ``size`` y, en puntos, ``tol_xy`` y ``tol_z``; ``source_main`` (copiado a
  ``in/`` con su ``-wal`` o su diario y leído sobre una copia consolidada,
  ``gis.vector.copy_source``) → según el papel, ``points.npz``, ``lines.npz``,
  ``contours.npz``, ``polygons.npz`` o, una capa de dominios (spec 011, D-32),
  ``domains.npz`` (:data:`LAYER_OUTPUTS`, :func:`write_domains`), y ``report.json``. Una capa
  de entidades (spec 012, D-27; papel ``features``) deja ``features.npz``
  (:func:`write_features`) con las coordenadas de la capa; con ``target_crs`` (el del
  proyecto) distinto del suyo, el resumen lo dice (``reprojects``) y no lleva el hash de su
  tabla: ``bl`` la transforma con la 006 al incorporarla (RF-006-05, como las curvas de un TIN)
  y la hashea su registro.
- ``gis_import_points`` admite además ``tol_xy`` y ``tol_z``: su informe dice los puntos
  duplicados (RF-006-12).
- ``gis_tin_contours``: ``name``, ``origin``, ``crs``, ``vertical``, ``densify_m``,
  ``max_passes``, ``max_flat_pct``, ``tol_xy``, ``tol_z``, ``duplicate_policy`` y ``count``;
  ``lines`` (las curvas) [, ``points`` (los puntos acotados) y ``regions`` (el contorno)]; la
  operación de la petición → ``tin.npz`` (``gis.tin_from_contours`` con ``PureTriangulator``:
  la corrección de triángulos planos triangula varias veces seguidas) y ``report.json``, o
  ``conflicts.json``.
- ``gis_convert_surface``: ``direction`` (``grid_to_tin`` o ``tin_to_grid``), ``name``,
  ``crs``, ``vertical``, ``target`` (la rejilla del proyecto, de un TIN a rejilla) y
  ``count``; ``source`` (``.tif`` o ``.npz``) → ``tin.npz`` (con la operación de la petición)
  o ``grid.tif``.

Referencias en JSON: un CRS, ``{"epsg": n}``; una referencia vertical, ``{"epsg": n}``,
``{"local": nota}`` o ``{"ellipsoidal": 4937}`` (los de ``gis.store.declared_crs`` y
``declared_vertical``); una rejilla, :func:`grid_json`; el GeoOrigin, :func:`origin_json`.
Ficheros intermedios en npz sin *pickle* (:func:`write_points`, :func:`write_lines`,
:func:`write_tin_input`, :func:`write_regions`, :func:`write_contours`, :func:`write_mesh`,
con su lectura), para que ``bl`` los lea al incorporarlos.

Una **reproyección** (otro CRS u otra referencia vertical, :func:`reprojects`) no tiene
estimación: va a proceso aparte (D11: una de hasta 60 s en un hilo no se podría parar), con
``--site`` a las ruedas de la extensión para pyproj (:func:`needs_site`); el servicio de CRS lo
da ``adapters.registry`` dentro del trabajo, con su versión comprobada (RF-006-31).

Python puro y numpy (ADR-0004).
"""

from __future__ import annotations

import dataclasses
import functools
import hashlib
import json
import math
import numbers
import os
import shutil
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

import numpy as np

from ..core.content.builtin import DOCUMENT
from ..core.content.encoder import NORMALIZER, ContentDigest
from ..core.content.readers import MAIN_ROLE, ContentReader, read_steps
from ..core.errors import GeoblenderError
from ..core.georef import (
    CrsRef,
    GeoOrigin,
    PrecisionReport,
    VerticalRef,
    Window,
    load_catalog,
    world_to_local,
)
from ..core.gpkg.base import ColumnDef
from ..core.gpkg.header import side_file
from ..core.gpkg.wkb import Geometry
from ..jobs.catalog import WorkerInfo
from ..jobs.messages import JobError
from ..jobs.paths import JobDir
from ..jobs.protocol import JobRequest, JsonValue
from ..jobs.worker_api import JobCancelled, JobFailed
from . import content as gis_content
from .asc import read_asc
from .cdt import PureTriangulator
from .contours import (
    ContourLine,
    contours_from_features,
    contours_from_raster,
    contours_from_tin,
)
from .crs import ELLIPSOIDAL_ETRS89, Declaration, needs_transform, transformation_for
from .crs import require_crs_service, transform_summary
from .geotiff import GeoTiffIO
from .geotiff.reader import read_geotiff
from .grid import Grid
from .mesh import MeshArrays, lod_rasters, surface_mesh_from_raster, surface_mesh_from_tin
from .placement import cells_precision, data_extent
from .points import (
    Breakline,
    ColumnMapping,
    DuplicatePolicy,
    PointSet,
    breaklines_from_features,
    duplicate_tolerances,
    find_duplicates,
    points_from_features,
    points_from_rows,
    polygons_from_features,
)
from .ports import Cancelled, Progress
from .raster import Raster
from .reports import Conflict, ConflictError, ConflictKind
from .resample import (
    ResampleMethod,
    choose_method,
    reproject_to_grid,
    resample_classes_to_grid,
    resample_to_grid,
)
from .styles import LayerStyle
from .tin import (
    Tin,
    TinInput,
    finish_tin,
    load_tin,
    meta_vertical,
    prepare_tin,
    raster_to_tin,
    save_tin,
    tin_to_raster,
)
from .tin_contours import tin_from_contours
from .validate import validate_raster, validate_tin
from .vector import (
    DomainSet,
    FeatureLayer,
    FieldColumn,
    StoredLayer,
    copy_source,
    domains_from_features,
    features_from_layer,
    read_layer,
    tin_layer,
    write_layers,
)
from .xyz_grid import read_xyz_grid

__all__ = [
    "CANCEL_GRACE_S",
    "WORKER_INFOS",
    "WORKER_INFOS_BY_NAME",
    "WORKER_NAMES",
    "JobOutput",
    "TinExport",
    "crs_json",
    "crs_of",
    "digest_json",
    "digest_of",
    "grid_json",
    "grid_of",
    "imported_rows",
    "needs_site",
    "origin_json",
    "origin_of",
    "path_name",
    "plain",
    "point_inputs",
    "read_boundary",
    "read_conflicts",
    "read_contours",
    "read_domains",
    "read_features",
    "read_lines",
    "read_mesh",
    "read_points",
    "read_export_layers",
    "read_polygons",
    "read_regions",
    "read_samples",
    "read_tin_input",
    "reprojects",
    "tin_inputs",
    "vertical_json",
    "vertical_of",
    "write_contours",
    "write_domains",
    "write_features",
    "write_export_layers",
    "write_lines",
    "write_mesh",
    "write_points",
    "write_polygons",
    "write_regions",
    "write_samples",
    "write_tin_input",
]

OWNER = "gis"
"""El módulo dueño de sus trabajos (``JobRequest.owner``)."""
CANCEL_GRACE_S = 1.0
"""Plazo de gracia de sus peticiones (el mínimo de la 004): cancelar para en ≤ 2 s también si
el trabajo está en un tramo sin puntos de cancelación (RF-006-28, RF-004-09)."""

READ_RASTER = "gis_read_raster"
RESAMPLE = "gis_resample"
IMPORT_POINTS = "gis_import_points"
TIN_PREPARE = "gis_tin_prepare"
TRIANGULATE = "gis_triangulate"
TIN_FINISH = "gis_tin_finish"
CONTOURS = "gis_contours"
VALIDATE = "gis_validate"
EXPORT = "gis_export"
VIEW_ARRAYS = "gis_view_arrays"
IMPORT_VECTOR = "gis_import_vector"
TIN_CONTOURS = "gis_tin_contours"
CONVERT_SURFACE = "gis_convert_surface"
WORKER_NAMES: tuple[str, ...] = (READ_RASTER, RESAMPLE, IMPORT_POINTS, TIN_PREPARE,
                                 TRIANGULATE, TIN_FINISH, CONTOURS, VALIDATE, EXPORT,
                                 VIEW_ARRAYS, IMPORT_VECTOR, TIN_CONTOURS, CONVERT_SURFACE)
"""Los tipos de trabajo de la 006 (y sus módulos de ``workers/``), en el orden del plan y,
después, los de la T29."""
GRID_TO_TIN = "grid_to_tin"
TIN_TO_GRID = "tin_to_grid"
DIRECTIONS: tuple[str, ...] = (GRID_TO_TIN, TIN_TO_GRID)
"""Lo que hace ``gis_convert_surface``: una rejilla en TIN o un TIN en rejilla."""

PATH_PREFIX = "source_"
"""Las rutas de la fuente en la línea de órdenes: ``source_<papel>`` (``source_main``)."""
PRJ_ROLE = gis_content.PRJ_ROLE
"""El papel del ``.prj`` de un ASC (``source_prj``)."""

INPUT_SOURCE = "source"
"""``in/source.tif`` (una rejilla del proyecto) o ``in/source.npz`` (un TIN)."""
INPUT_LAYERS = "layers"
"""``in/layers.npz``: las capas de una exportación a GeoPackage (:func:`write_export_layers`)."""
TIN_INPUT_PREFIX = "tin_"
"""Las entradas de los TIN de una exportación a GeoPackage: ``in/tin_<n>.npz``."""
GEOTIFF_FORMAT = "geotiff"
GPKG_FORMAT = "gpkg"
EXPORT_FORMATS: tuple[str, ...] = (GEOTIFF_FORMAT, GPKG_FORMAT)
"""Lo que escribe ``gis_export``: el GeoTIFF entregable o el GeoPackage con las capas."""
INPUT_POINTS = "points"
INPUT_LINES = "lines"
INPUT_PREPARED = "prepared"
INPUT_FACES = "faces"
INPUT_REGIONS = "regions"


@dataclass(frozen=True, slots=True)
class JobOutput:
    """Un resultado de un trabajo de la 006: su fichero en ``out/`` y su papel
    (``OutputRef.role``, con el que ``bl`` lo encuentra al incorporarlo)."""

    file: str
    role: str

    @property
    def relative(self) -> str:
        """``out/<fichero>``: su ruta en la carpeta del trabajo."""
        return f"out/{self.file}"


OUT_SOURCE_GRID = JobOutput("source.tif", "source_grid")
OUT_PROJECT_GRID = JobOutput("grid.tif", "project_grid")
OUT_POINTS = JobOutput("points.npz", "points")
OUT_LINES = JobOutput("lines.npz", "breaklines")
OUT_REPORT = JobOutput("report.json", "report")
OUT_PREPARED = JobOutput("prepared.npz", "prepared")
OUT_CONFLICTS = JobOutput("conflicts.json", "conflicts")
OUT_FACES = JobOutput("faces.npy", "faces")
OUT_TIN = JobOutput("tin.npz", "tin")
OUT_CONTOURS = JobOutput("contours.npz", "contours")
OUT_EXPORT = JobOutput("export.tif", "export")
OUT_EXPORT_GPKG = JobOutput("export.gpkg", "export")
OUT_MESH = JobOutput("mesh.npz", "mesh")
OUT_POLYGONS = JobOutput("polygons.npz", "boundary")
OUT_DOMAINS = JobOutput("domains.npz", "domains")
OUT_FEATURES = JobOutput("features.npz", "features")
OUT_SAMPLES = JobOutput("samples.npy", "samples")
LAYER_OUTPUTS: Mapping[str, JobOutput] = MappingProxyType({
    "points": OUT_POINTS,
    "breaklines": OUT_LINES,
    "contours": OUT_CONTOURS,
    "boundary": OUT_POLYGONS,
    "domains": OUT_DOMAINS,
    "features": OUT_FEATURES,
})
"""El resultado de ``gis_import_vector`` según el papel de la capa (los de
``gis.provenance.LAYER_ROLES``; ``domains``, spec 011, D-32)."""

COPYING_TEXT = "Copiando la fuente…"
READING_TEXT = "Leyendo la fuente…"
HASHING_TEXT = "Calculando el hash de contenido de la fuente…"
WRITING_TEXT = "Escribiendo el resultado…"
EXPORT_HASH_TEXT = "Calculando el hash de contenido del entregable…"
RESULT_HASH_TEXT = "Calculando el hash de contenido del resultado…"
TABLE_HASH_TEXT = "Calculando el hash de contenido de lo importado…"
DONE_TEXT = "Terminado"
COPY_SHARE = 0.75
"""La parte del avance de copiar un fichero de la fuente que es la copia verificada (lee la
fuente tres veces); el resto, la huella de la copia (una lectura)."""

# Estimaciones [I] (plan §5.3.4: «celdas × 0,6 µs (DEFLATE)…»; medidas de T05 a T23).
READ_PASSES = 3
"""Una importación lee la fuente para su hash, la lee para importarla y escribe la rejilla:
unas tres veces lo que estima su lector de contenido."""
CELL_S = 0.6e-6
"""Leer o escribir una celda de una rejilla del proyecto (DEFLATE + predictor 3)."""
CONTOUR_CELL_S = 1.2e-6
"""Curvas de una celda (2,81 M celdas en unos 3,4 s, T21) o de un vértice de un TIN."""
MESH_CELL_S = 1.5e-6
"""Malla de vista y niveles de detalle por celda (2,81 M celdas → malla en 2,4 s, T22)."""
VALIDATE_CELL_S = 0.2e-6
"""Validar una celda (2,81 M celdas en 0,02–0,22 s, T14) además de leerla."""
TIN_POINT_S = 5e-6
"""Preparar o acabar un TIN por punto (300.000 puntos y 200 roturas en 1,0 s, T16)."""
PURE_POINT_S = 20e-6
"""``PureTriangulator`` por punto (20.000 puntos en 0,34 s; mallas regulares, ×4; T17)."""
CONTOUR_PASSES = 5
"""Triangulaciones de un TIN desde curvas como mucho: las curvas solas, la primera y una por
pasada de corrección (``gis.tin.flat_max_passes``, 3)."""

_UNLIMITED = sys.maxsize
"""Sin límite de celdas al leer lo que ya es del proyecto (lo comprobó su importación)."""
SQLITE_SIDES: tuple[str, ...] = ("-wal", "-journal")
"""Lo que se copia junto a un GeoPackage: su ``-wal`` o su diario (el ``-shm`` no hace
falta), como el trabajo de hash de la 008."""
LAYER_DIR = "capa"
"""La carpeta del trabajo donde se consolida la copia de un GeoPackage para leerla (se borra
al terminar)."""
_ELLIPSOIDAL_EPSG = 4937
_HASH_BLOCK = 1 << 20
_SURFACE_SUFFIXES = {".tif": "grid", ".tiff": "grid", ".npz": "tin"}


class _Context(Protocol):
    """Lo que usan las funciones de los trabajos del ``WorkerContext`` de la 004."""

    @property
    def request(self) -> JobRequest: ...

    @property
    def job_dir(self) -> JobDir: ...

    @property
    def paths(self) -> Mapping[str, Path]: ...

    def input_path(self, name: str) -> Path: ...

    def output_path(self, filename: str | os.PathLike[str]) -> Path: ...

    def add_output(self, path: str | os.PathLike[str], role: str) -> Any: ...

    def progress(self, frac: float, msg: str = "") -> None: ...

    def check_cancelled(self) -> None: ...


# --- Nombres, referencias y JSON ----------------------------------------------------------


def path_name(role: str) -> str:
    """El nombre en la línea de órdenes (``--path``) del fichero de papel ``role`` de la
    fuente: ``source_main``, ``source_prj``."""
    return f"{PATH_PREFIX}{role}"


def crs_json(crs: CrsRef | None) -> dict[str, Any] | None:
    """Un CRS horizontal en la petición: ``{"epsg": n}`` (``None``: sin declarar)."""
    if crs is None:
        return None
    if not isinstance(crs, CrsRef):
        raise TypeError(f"un CRS horizontal es un CrsRef del catálogo, no {crs!r}")
    return {"epsg": crs.epsg}


def vertical_json(vertical: VerticalRef | None) -> dict[str, Any] | None:
    """Una referencia vertical en la petición: ``{"epsg": n}``, ``{"local": nota}`` o, la
    altura elipsoidal ETRS89, ``{"ellipsoidal": 4937}`` (``None``: sin declarar)."""
    if vertical is None:
        return None
    if not isinstance(vertical, VerticalRef):
        raise TypeError(f"una referencia vertical es un VerticalRef, no {vertical!r}")
    if vertical.kind == "epsg":
        return {"epsg": vertical.epsg}
    if vertical.kind == "local":
        return {"local": vertical.note}
    if vertical == ELLIPSOIDAL_ETRS89:
        return {"ellipsoidal": _ELLIPSOIDAL_EPSG}
    return {"ellipsoidal": vertical.name}


def crs_of(value: object) -> CrsRef | None:
    """El CRS horizontal del catálogo de :func:`crs_json`. ``ValueError`` si no lo es."""
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {"epsg"}:
        raise ValueError(f"un CRS horizontal es {{\"epsg\": n}}, no {value!r}")
    try:
        return load_catalog().horizontal(value["epsg"])
    except GeoblenderError as error:
        raise ValueError(str(error)) from None


def vertical_of(value: object) -> VerticalRef | None:
    """La referencia vertical de :func:`vertical_json`. ``ValueError`` si no lo es."""
    if value is None:
        return None
    if not isinstance(value, Mapping) or len(value) != 1:
        raise ValueError(f"una referencia vertical es {{\"epsg\": n}}, {{\"local\": nota}} o "
                         f"{{\"ellipsoidal\": {_ELLIPSOIDAL_EPSG}}}, no {value!r}")
    try:
        if "epsg" in value:
            return load_catalog().vertical(value["epsg"])
        if "local" in value:
            return load_catalog().local_vertical(value["local"])
    except GeoblenderError as error:
        raise ValueError(str(error)) from None
    if value.get("ellipsoidal") == _ELLIPSOIDAL_EPSG:
        return ELLIPSOIDAL_ETRS89
    raise ValueError(f"referencia vertical desconocida: {value!r}")


def grid_json(grid: Grid) -> dict[str, Any]:
    """Una rejilla en la petición o en el resumen: oeste, norte, pasos, columnas y filas."""
    return {"west": grid.west, "north": grid.north, "dx": grid.dx, "dy": grid.dy,
            "ncols": grid.ncols, "nrows": grid.nrows}


def grid_of(value: object) -> Grid:
    """La rejilla de :func:`grid_json`. ``ValueError`` o ``TypeError`` si no lo es."""
    keys = ("west", "north", "dx", "dy", "ncols", "nrows")
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise ValueError(f"una rejilla es {{{', '.join(keys)}}}, no {value!r}")
    return Grid(*(value[key] for key in keys))


def origin_json(origin: GeoOrigin) -> dict[str, int]:
    """El GeoOrigin en la petición: ``{"x0", "y0", "z0"}`` (metros enteros)."""
    return {"x0": origin.x0, "y0": origin.y0, "z0": origin.z0}


def origin_of(value: object) -> GeoOrigin:
    """El GeoOrigin de :func:`origin_json`. ``ValueError`` o ``TypeError`` si no lo es."""
    if not isinstance(value, Mapping) or set(value) != {"x0", "y0", "z0"}:
        raise ValueError(f"el GeoOrigin es {{x0, y0, z0}}, no {value!r}")
    return GeoOrigin(value["x0"], value["y0"], value["z0"])


def window_json(window: Window) -> dict[str, float]:
    """Una extensión (``core.georef.Window``) en el resumen: ``{"xmin", "ymin", "xmax",
    "ymax"}`` (m)."""
    return {"xmin": window.xmin, "ymin": window.ymin, "xmax": window.xmax,
            "ymax": window.ymax}


def window_of(value: object) -> Window:
    """La extensión de :func:`window_json`. ``ValueError`` o ``TypeError`` si no lo es."""
    keys = {"xmin", "ymin", "xmax", "ymax"}
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ValueError(f"una extensión es {{xmin, ymin, xmax, ymax}}, no {value!r}")
    return Window(**dict(value))


def precision_json(report: PrecisionReport) -> dict[str, Any]:
    """El aviso de RF-002-26 (``core.georef.PrecisionReport``) en el resumen."""
    return plain(report)


def precision_of(value: object) -> PrecisionReport:
    """El ``PrecisionReport`` de :func:`precision_json`. ``ValueError`` o ``TypeError`` si no
    lo es."""
    names = [item.name for item in dataclasses.fields(PrecisionReport)]
    if not isinstance(value, Mapping) or set(value) != set(names):
        raise ValueError(f"un aviso de precisión es {{{', '.join(names)}}}, no {value!r}")
    return PrecisionReport(**{**value, "corners_outside": tuple(value["corners_outside"])})


def digest_json(digest: ContentDigest) -> dict[str, str]:
    """Un ``ContentDigest`` en el resumen (como el del trabajo ``core_content_hash``)."""
    return {"data_sha256": digest.data_sha256, "content_sha256": digest.content_sha256,
            "normalizer": digest.normalizer, "reader": digest.reader}


def digest_of(value: Mapping[str, Any]) -> ContentDigest:
    """El ``ContentDigest`` de :func:`digest_json`."""
    return ContentDigest(value["data_sha256"], value["content_sha256"], value["normalizer"],
                         value["reader"])


def plain(value: object) -> Any:
    """``value`` (un informe del dominio: ``dataclass``, tuplas, enumeraciones, números de
    numpy) en JSON: diccionarios, listas, textos, números finitos (NaN o ±∞, como texto),
    booleanos y ``None``."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {item.name: plain(getattr(value, item.name))
                for item in dataclasses.fields(value)}
    if isinstance(value, Mapping):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [plain(item) for item in value]
    if isinstance(value, np.ndarray):
        return plain(value.tolist())
    if isinstance(value, np.generic):
        return plain(value.item())
    if isinstance(value, Enum):
        return plain(value.value)
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if value is None or isinstance(value, str | int | bool):
        return value
    return str(value)


def reprojects(params: Mapping[str, Any]) -> bool:
    """Si el remuestreo de ``params`` cambia de CRS o de referencia vertical (una
    reproyección con pyproj, RF-006-05); sin los dos CRS no se sabe: verdadero."""
    pairs = (("source_crs", "target_crs"), ("source_vertical", "target_vertical"))
    if any(key not in params for pair in pairs for key in pair):
        return True
    return any(params[first] != params[second] for first, second in pairs)


def needs_site(worker: str, params: Mapping[str, Any]) -> bool:
    """Si el trabajo ``worker`` con ``params`` necesita las ruedas de la extensión (pyproj)
    en su intérprete: ``submit(..., site_override=<carpeta de las ruedas>)`` (plan §5.3.4,
    D11). Solo una reproyección."""
    return worker == RESAMPLE and reprojects(params)


# --- Ficheros intermedios (npz sin pickle) -------------------------------------------------


def _save_npz(path: Path, **arrays: np.ndarray) -> None:
    """Los ficheros de paso de un trabajo, sin comprimir: están en la caché local y viven lo
    que la cadena (spec 006, T35: comprimir los 289.900 puntos de un TIN costaba 0,5 s sin
    avance; sin comprimir, centésimas)."""
    with open(path, "wb") as stream:
        np.savez(stream, **arrays)


def _load_npz(path: Path, keys: Sequence[str]) -> dict[str, np.ndarray]:
    """Los arrays ``keys`` del npz ``path`` (leído sin *pickle*, ARQ-16); ``ValueError`` si
    no es un npz con ellos."""
    try:
        with np.load(path, allow_pickle=False) as data:
            missing = [key for key in keys if key not in data.files]
            if missing:
                raise ValueError(f"al npz «{Path(path).name}» le faltan {missing}")
            return {key: data[key] for key in data.files}
    except (OSError, EOFError) as error:
        raise ValueError(f"«{Path(path).name}» no es un npz legible ({error})") from None


def _texts(values: Sequence[str]) -> np.ndarray:
    """Los textos ``values`` en UTF-8 (``bytes`` de numpy, sin *pickle*): de un byte por letra
    en vez de cuatro (spec 006, T35: los 289.900 identificadores de un levantamiento pasan de
    7 MB a menos de 2). Si son ASCII, de una vez."""
    if not len(values):
        return np.zeros(0, dtype="S1")
    try:
        return np.array(tuple(values), dtype=bytes)
    except UnicodeEncodeError:
        return np.array([str(value).encode("utf-8") for value in values], dtype=bytes)


def _strings(array: np.ndarray) -> tuple[str, ...]:
    """Los textos de :func:`_texts` (o de un array de ``str`` de antes de T35)."""
    if array.dtype.kind == "S":
        return tuple(value.decode("utf-8") for value in array.tolist())
    return tuple(str(value) for value in array.tolist())


def _offsets(sizes: Sequence[int]) -> np.ndarray:
    return np.concatenate(([0], np.cumsum(np.asarray(sizes, dtype=np.int64)))).astype(np.int64)


def _xyz_rows(arrays: Sequence[np.ndarray], columns: int = 3) -> np.ndarray:
    if not arrays:
        return np.zeros((0, columns), dtype=np.float64)
    return np.ascontiguousarray(np.concatenate(arrays), dtype=np.float64)


_POINT_KEYS = ("xyz", "point_ids", "codes", "source_rows")


def _point_arrays(points: PointSet) -> dict[str, np.ndarray]:
    return {"xyz": points.xyz, "point_ids": _texts(points.point_ids),
            "codes": _texts(points.codes),
            "source_rows": np.asarray(points.source_rows, dtype=np.int64)}


def _points_from(data: Mapping[str, np.ndarray]) -> PointSet:
    return PointSet(np.ascontiguousarray(data["xyz"], dtype=np.float64).reshape(-1, 3),
                    _strings(data["point_ids"]), _strings(data["codes"]),
                    tuple(int(row) for row in data["source_rows"].tolist()))


def write_points(path: Path | str, points: PointSet) -> None:
    """``points`` en el npz ``path`` (``xyz`` ABSOLUTOS float64, identificadores, códigos y
    filas de origen)."""
    _save_npz(Path(path), **_point_arrays(points))


def read_points(path: Path | str) -> PointSet:
    """El ``PointSet`` de :func:`write_points` (``xyz`` bit a bit)."""
    return _points_from(_load_npz(Path(path), _POINT_KEYS))


def _loose(name: str, arrays: Mapping[str, np.ndarray]) -> dict[str, np.ndarray]:
    return {f"{name}_{key}": value for key, value in arrays.items()}


def point_inputs(points: PointSet) -> dict[str, np.ndarray]:
    """Los puntos de un TIN como entradas sueltas de ``gis_tin_prepare`` (``points_<array>``,
    los arrays de :func:`write_points`), que ``bl`` escribe en ``in/`` sin copiar ni releer
    (``JobDir.write_array``, con ``core_provenance.launch_job(arrays=…)``; spec 006, T35: la
    copia verificada de 300.000 puntos eran 0,2 s del hilo de Blender, RNF-006-09)."""
    return _loose(INPUT_POINTS, _point_arrays(points))


def _input_arrays(ctx: _Context, request: _Request, name: str,
                  keys: Sequence[str]) -> dict[str, np.ndarray] | None:
    """Los arrays ``keys`` de la entrada ``name``: los del npz ``in/<name>.npz`` o, sueltos
    (:func:`point_inputs`, :func:`tin_inputs`), los de ``in/<name>_<array>.npy``; ``None``
    si no llega ni uno ni otros."""
    entries = ctx.request.inputs
    if name in entries:
        return _load_npz(ctx.input_path(name), keys)
    loose = [f"{name}_{key}" for key in keys]
    if not any(entry in entries for entry in loose):
        return None
    missing = [entry for entry in loose if entry not in entries]
    if missing:
        raise request.invalid(f"a la entrada «{name}» le faltan {missing}")
    return {key: np.load(ctx.input_path(entry), allow_pickle=False)
            for key, entry in zip(keys, loose, strict=True)}


def write_lines(path: Path | str, lines: Sequence[Breakline]) -> None:
    """Las líneas de rotura ``lines`` en el npz ``path``: vértices seguidos (``xyz``),
    ``offsets`` (n + 1), identificador, código, dura o blanda y filas de origen."""
    lines = list(lines)
    rows = [np.asarray(line.source_rows, dtype=np.int64) for line in lines]
    _save_npz(Path(path), xyz=_xyz_rows([line.xyz for line in lines]),
              offsets=_offsets([len(line.xyz) for line in lines]),
              line_ids=_texts([line.line_id for line in lines]),
              codes=_texts([line.code for line in lines]),
              hard=np.array([line.hard for line in lines], dtype=bool),
              rows=np.concatenate(rows) if rows else np.zeros(0, np.int64),
              row_offsets=_offsets([len(item) for item in rows]))


def read_lines(path: Path | str) -> list[Breakline]:
    """Las líneas de rotura de :func:`write_lines` (vértices bit a bit)."""
    data = _load_npz(Path(path), ("xyz", "offsets", "line_ids", "codes", "hard", "rows",
                                  "row_offsets"))
    xyz = np.ascontiguousarray(data["xyz"], dtype=np.float64).reshape(-1, 3)
    offsets, row_offsets = data["offsets"], data["row_offsets"]
    codes = _strings(data["codes"])
    lines: list[Breakline] = []
    for index, line_id in enumerate(_strings(data["line_ids"])):
        start, stop = int(offsets[index]), int(offsets[index + 1])
        rows = data["rows"][int(row_offsets[index]):int(row_offsets[index + 1])]
        lines.append(Breakline(line_id, np.ascontiguousarray(xyz[start:stop]),
                               hard=bool(data["hard"][index]), code=codes[index],
                               source_rows=tuple(int(row) for row in rows)))
    return lines


_TIN_COUNTS = ("input_vertices", "merged", "crossings", "splits", "input_points",
               "duplicates_merged")


_TIN_INPUT_KEYS = ("xyz", "edges", "vertex_source", "counts")


def _tin_input_arrays(source: TinInput) -> dict[str, np.ndarray]:
    prepared = source.prepared
    counts = (prepared.input_vertices, prepared.merged, prepared.crossings, prepared.splits,
              source.input_points, source.duplicates_merged)
    return {"xyz": prepared.xyz, "edges": prepared.edges,
            "vertex_source": prepared.vertex_source,
            "counts": np.asarray(counts, dtype=np.int64)}


def write_tin_input(path: Path | str, source: TinInput) -> None:
    """Lo que se triangula (``gis.tin.TinInput``) en el npz ``path``."""
    _save_npz(Path(path), **_tin_input_arrays(source))


def tin_inputs(source: TinInput) -> dict[str, np.ndarray]:
    """Lo que se triangula como entradas sueltas (``prepared_<array>``, los arrays de
    :func:`write_tin_input`) de ``gis_tin_finish`` o ``gis_triangulate``, como
    :func:`point_inputs`."""
    return _loose(INPUT_PREPARED, _tin_input_arrays(source))


def read_tin_input(path: Path | str) -> TinInput:
    """El ``TinInput`` de :func:`write_tin_input` (los mismos arrays, bit a bit)."""
    return _tin_input_from(_load_npz(Path(path), _TIN_INPUT_KEYS))


def _tin_input_from(data: Mapping[str, np.ndarray]) -> TinInput:
    from .breaklines import PreparedInput

    counts = dict(zip(_TIN_COUNTS, (int(value) for value in data["counts"]), strict=True))
    prepared = PreparedInput(
        np.ascontiguousarray(data["xyz"], dtype=np.float64).reshape(-1, 3),
        np.ascontiguousarray(data["edges"], dtype=np.int32).reshape(-1, 2),
        np.ascontiguousarray(data["vertex_source"], dtype=np.uint8),
        counts["input_vertices"], counts["merged"], counts["crossings"], counts["splits"])
    return TinInput(prepared, counts["input_points"], counts["duplicates_merged"])


def write_regions(path: Path | str, boundary: Sequence[np.ndarray] | None,
                  holes: Sequence[Sequence[np.ndarray]] = ()) -> None:
    """El contorno (una región: su lista de anillos ABSOLUTOS, o ``None``) y los huecos (una
    lista de regiones) de un TIN en el npz ``path``; de cada anillo, su X e Y."""
    regions = ([] if boundary is None else [list(boundary)]) + [list(hole) for hole in holes]
    rings = [np.ascontiguousarray(np.asarray(ring, dtype=np.float64)[:, :2])
             for region in regions for ring in region]
    _save_npz(Path(path), xy=_xyz_rows(rings, 2), ring_offsets=_offsets([len(r) for r in rings]),
              region_offsets=_offsets([len(region) for region in regions]),
              holes=np.array([False] * (boundary is not None) + [True] * len(holes), bool))


def read_regions(path: Path | str) -> tuple[list[np.ndarray] | None, list[list[np.ndarray]]]:
    """El contorno y los huecos de :func:`write_regions`."""
    data = _load_npz(Path(path), ("xy", "ring_offsets", "region_offsets", "holes"))
    xy = np.ascontiguousarray(data["xy"], dtype=np.float64).reshape(-1, 2)
    rings, regions = data["ring_offsets"], data["region_offsets"]
    boundary: list[np.ndarray] | None = None
    holes: list[list[np.ndarray]] = []
    for index, is_hole in enumerate(data["holes"]):
        found = [np.ascontiguousarray(xy[int(rings[r]):int(rings[r + 1])])
                 for r in range(int(regions[index]), int(regions[index + 1]))]
        if is_hole:
            holes.append(found)
        else:
            boundary = found
    return boundary, holes


def write_samples(path: Path | str, xyz: np.ndarray) -> None:
    """Las posiciones con que la orden compara un MDT importado con la rejilla del proyecto
    (``gis.dtm.vertical_samples``: ``(n, 3)``, X, Y y Z ABSOLUTAS en float64) en el ``.npy``
    ``path``, sin *pickle* (T54). ``ValueError`` si no son ``(n, 3)``."""
    found = np.ascontiguousarray(xyz, dtype=np.float64)
    if found.ndim != 2 or found.shape[1] != 3:
        raise ValueError(f"las posiciones son (n, 3), no {found.shape}")
    with open(path, "wb") as stream:
        np.save(stream, found, allow_pickle=False)


def read_samples(path: Path | str) -> np.ndarray:
    """Las posiciones de :func:`write_samples` (``(n, 3)`` en float64); ``ValueError`` si el
    fichero no las tiene."""
    with open(path, "rb") as stream:
        found = np.load(stream, allow_pickle=False)
    if found.dtype != np.float64 or found.ndim != 2 or found.shape[1] != 3:
        raise ValueError(f"«{Path(path).name}» no tiene posiciones (n, 3) en float64: "
                         f"{found.dtype} {found.shape}")
    return found


def write_polygons(path: Path | str,
                   features: Sequence[Sequence[Sequence[np.ndarray]]]) -> None:
    """Los contornos de una capa en el npz ``path``: de cada entidad, sus polígonos y, de cada
    uno, sus anillos (X e Y ABSOLUTOS), con sus ``offsets``."""
    polygons = [polygon for feature in features for polygon in feature]
    rings = [np.ascontiguousarray(np.asarray(ring, dtype=np.float64)[:, :2])
             for polygon in polygons for ring in polygon]
    _save_npz(Path(path), xy=_xyz_rows(rings, 2), ring_offsets=_offsets([len(r) for r in rings]),
              polygon_offsets=_offsets([len(polygon) for polygon in polygons]),
              feature_offsets=_offsets([len(feature) for feature in features]))


def read_polygons(path: Path | str) -> list[list[list[np.ndarray]]]:
    """Los contornos de :func:`write_polygons` (anillos bit a bit)."""
    data = _load_npz(Path(path), ("xy", "ring_offsets", "polygon_offsets", "feature_offsets"))
    xy = np.ascontiguousarray(data["xy"], dtype=np.float64).reshape(-1, 2)
    rings, polygons, features = (data["ring_offsets"], data["polygon_offsets"],
                                 data["feature_offsets"])
    found: list[list[list[np.ndarray]]] = []
    for feature in range(len(features) - 1):
        found.append([
            [np.ascontiguousarray(xy[int(rings[r]):int(rings[r + 1])])
             for r in range(int(polygons[p]), int(polygons[p + 1]))]
            for p in range(int(features[feature]), int(features[feature + 1]))])
    return found


def read_boundary(path: Path | str, epsg: int) -> list[Geometry]:
    """Los contornos de :func:`write_polygons` como los guarda una importación de una capa
    (``gis.store.ResultWriter.boundary``): una ``Geometry`` ``MULTIPOLYGON`` sin Z en ``epsg``
    por entidad. La orden los guarda así y el trabajo calcula con ellos el hash de su tabla
    (T50)."""
    return [Geometry("MULTIPOLYGON", epsg, False, polygons, None)
            for polygons in read_polygons(path)]


def write_domains(path: Path | str, domains: DomainSet) -> None:
    """Los dominios de una capa (``gis.vector.DomainSet``, spec 011, D-32) en el npz ``path``:
    los anillos como en :func:`write_polygons`, el número de cada entidad y, en JSON, sus
    columnas (campo, columna y tipo) y sus valores por columna."""
    rings = [ring for feature in domains.polygons for polygon in feature for ring in polygon]
    polygons = [polygon for feature in domains.polygons for polygon in feature]
    _save_npz(Path(path), xy=_xyz_rows(rings, 2), ring_offsets=_offsets([len(r) for r in rings]),
              polygon_offsets=_offsets([len(polygon) for polygon in polygons]),
              feature_offsets=_offsets([len(feature) for feature in domains.polygons]),
              fids=np.asarray(domains.fids, dtype=np.int64),
              columns=_text_array([[c.field, c.column, c.sql_type] for c in domains.columns]),
              values=_text_array({name: list(found) for name, found in domains.values.items()}))


def read_domains(path: Path | str) -> DomainSet:
    """Los dominios de :func:`write_domains` (anillos bit a bit, los mismos valores)."""
    data = _load_npz(Path(path), ("xy", "ring_offsets", "polygon_offsets", "feature_offsets",
                                  "fids", "columns", "values"))
    xy = np.ascontiguousarray(data["xy"], dtype=np.float64).reshape(-1, 2)
    rings, polygons, features = (data["ring_offsets"], data["polygon_offsets"],
                                 data["feature_offsets"])
    found = tuple(
        tuple(tuple(np.ascontiguousarray(xy[int(rings[r]):int(rings[r + 1])])
                    for r in range(int(polygons[p]), int(polygons[p + 1])))
              for p in range(int(features[feature]), int(features[feature + 1])))
        for feature in range(len(features) - 1))
    columns = tuple(FieldColumn(*map(str, item)) for item in _json_of(data["columns"]))
    return DomainSet(tuple(int(fid) for fid in data["fids"].tolist()), found, columns,
                     _json_of(data["values"]))


def write_features(path: Path | str, layer: FeatureLayer) -> None:
    """Las entidades de una capa (``gis.vector.FeatureLayer``, spec 012, D-27) en el npz
    ``path``: las X e Y de cada anillo, camino o punto, seguidas, con sus ``offsets`` por
    array, por parte y por entidad, su geometría, el número de cada entidad y, en JSON, sus
    columnas (campo, columna y tipo) y sus valores por columna."""
    arrays = [array for feature in layer.parts for part in feature for array in part]
    parts = [part for feature in layer.parts for part in feature]
    _save_npz(Path(path), xy=_xyz_rows(arrays, 2),
              array_offsets=_offsets([len(array) for array in arrays]),
              part_offsets=_offsets([len(part) for part in parts]),
              feature_offsets=_offsets([len(feature) for feature in layer.parts]),
              kind=np.array(layer.kind), fids=np.asarray(layer.fids, dtype=np.int64),
              columns=_text_array([[c.field, c.column, c.sql_type] for c in layer.columns]),
              values=_text_array({name: list(found) for name, found in layer.values.items()}))


def read_features(path: Path | str) -> FeatureLayer:
    """Las entidades de :func:`write_features` (coordenadas bit a bit, los mismos valores)."""
    data = _load_npz(Path(path), ("xy", "array_offsets", "part_offsets", "feature_offsets",
                                  "kind", "fids", "columns", "values"))
    xy = np.ascontiguousarray(data["xy"], dtype=np.float64).reshape(-1, 2)
    arrays, parts, features = (data["array_offsets"], data["part_offsets"],
                               data["feature_offsets"])
    found = tuple(
        tuple(tuple(np.ascontiguousarray(xy[int(arrays[a]):int(arrays[a + 1])])
                    for a in range(int(parts[p]), int(parts[p + 1])))
              for p in range(int(features[feature]), int(features[feature + 1])))
        for feature in range(len(features) - 1))
    columns = tuple(FieldColumn(*map(str, item)) for item in _json_of(data["columns"]))
    return FeatureLayer(str(data["kind"].item()), tuple(int(f) for f in data["fids"].tolist()),
                        found, columns, _json_of(data["values"]))


def imported_rows(family: str, path: Path | str, epsg: int) -> list[tuple[Any, ...]]:
    """Las filas de la tabla de ``family`` (``gis.provenance``: puntos, líneas de rotura,
    curvas, contornos o dominios) con lo importado que dejó un trabajo en ``path``
    (``points.npz``, ``lines.npz``, ``contours.npz``, ``polygons.npz`` o ``domains.npz``) y las
    coordenadas en ``epsg``: las que escribe la orden al incorporarlo (``gis.store.point_rows``
    y las demás). Con ellas calcula el trabajo el hash de la tabla (T50; RNF-006-09)."""
    from .provenance import BOUNDARY, BREAKLINES, CONTOUR_LINES, DOMAINS, POINTS
    from .store import boundary_rows, breakline_rows, contour_rows, domain_rows, point_rows

    if family == DOMAINS:
        return domain_rows(read_domains(path), epsg)
    if family == POINTS:
        return point_rows(read_points(path), epsg)
    if family == BREAKLINES:
        return breakline_rows(read_lines(path), epsg)
    if family == CONTOUR_LINES:
        return contour_rows(read_contours(path), epsg)
    if family == BOUNDARY:
        return boundary_rows(read_boundary(path, epsg), (), epsg)
    raise ValueError(f"{family!r} no es lo importado en una tabla (puntos, líneas de rotura, "
                     "curvas, contornos o dominios)")


def write_contours(path: Path | str, lines: Sequence[ContourLine]) -> None:
    """Las curvas de nivel ``lines`` en el npz ``path`` (vértices seguidos y ``offsets``,
    cota, maestra y cerrada)."""
    lines = list(lines)
    _save_npz(Path(path), xyz=_xyz_rows([line.xyz for line in lines]),
              offsets=_offsets([len(line.xyz) for line in lines]),
              elevation=np.array([line.elevation for line in lines], dtype=np.float64),
              is_index=np.array([line.is_index for line in lines], dtype=bool),
              closed=np.array([line.closed for line in lines], dtype=bool))


def read_contours(path: Path | str) -> list[ContourLine]:
    """Las curvas de :func:`write_contours` (vértices bit a bit)."""
    data = _load_npz(Path(path), ("xyz", "offsets", "elevation", "is_index", "closed"))
    xyz = np.ascontiguousarray(data["xyz"], dtype=np.float64).reshape(-1, 3)
    offsets = data["offsets"]
    return [ContourLine(np.ascontiguousarray(xyz[int(offsets[i]):int(offsets[i + 1])]),
                        float(data["elevation"][i]), bool(data["is_index"][i]),
                        bool(data["closed"][i]))
            for i in range(len(data["elevation"]))]


def write_mesh(path: Path | str, meshes: Mapping[float | None, MeshArrays]) -> None:
    """Las mallas de vista en el npz ``path``: la de la superficie (clave ``None``) y la de
    cada nivel de detalle por su paso (m)."""
    steps = sorted(step for step in meshes if step is not None)
    arrays: dict[str, np.ndarray] = {"lod_steps": np.asarray(steps, dtype=np.float64)}
    for index, step in enumerate([None, *steps]):
        prefix = "" if step is None else f"lod{index}_"
        arrays[f"{prefix}vertices"] = meshes[step].vertices
        arrays[f"{prefix}faces"] = meshes[step].faces
    _save_npz(Path(path), **arrays)


def read_mesh(path: Path | str) -> dict[float | None, MeshArrays]:
    """Las mallas de :func:`write_mesh`, por paso (``None``: la de la superficie)."""
    data = _load_npz(Path(path), ("lod_steps", "vertices", "faces"))
    found: dict[float | None, MeshArrays] = {}
    for index, step in enumerate([None, *(float(s) for s in data["lod_steps"])]):
        prefix = "" if step is None else f"lod{index}_"
        found[step] = MeshArrays(np.ascontiguousarray(data[f"{prefix}vertices"]),
                                 np.ascontiguousarray(data[f"{prefix}faces"]))
    return found


@dataclass(frozen=True, slots=True)
class TinExport:
    """Un TIN que el trabajo ``gis_export`` exporta como triángulos (``gis.vector.tin_layer``):
    el nombre de su capa, la entrada de la petición con su fichero (``tin_<n>``), su
    identificador y su descripción."""

    name: str
    input: str
    identifier: str = ""
    description: str = ""


_TABLE_LAYER = "table"
_TIN_LAYER = "tin"


def _text_array(value: Any) -> np.ndarray:
    return np.array(json.dumps(value, ensure_ascii=False))


def _json_of(value: np.ndarray) -> Any:
    return json.loads(str(value.item()))


def write_export_layers(path: Path | str, layers: Sequence[StoredLayer | TinExport]) -> None:
    """Las capas de una exportación a GeoPackage en el npz ``path`` (sin comprimir: las
    geometrías codificadas no se comprimen apenas y así ``bl`` lo escribe enseguida): de cada
    tabla (``gis.vector.StoredLayer``), su forma, sus geometrías tal como están guardadas
    (seguidas, con sus ``offsets``), sus valores en JSON (los números, con todos sus
    decimales) y su estilo de QGIS (``gis.styles.LayerStyle``, T55); de cada TIN
    (:class:`TinExport`), su capa y su entrada."""
    arrays: dict[str, np.ndarray] = {"count": np.array([len(layers)], dtype=np.int64)}
    for index, layer in enumerate(layers):
        if isinstance(layer, TinExport):
            arrays[f"meta{index}"] = _text_array({
                "kind": _TIN_LAYER, "name": layer.name, "input": layer.input,
                "identifier": layer.identifier, "description": layer.description})
            continue
        if not isinstance(layer, StoredLayer):
            raise TypeError(f"una capa exportada es un StoredLayer o un TinExport, no {layer!r}")
        arrays[f"meta{index}"] = _text_array({
            "kind": _TABLE_LAYER, "name": layer.name, "geometry_type": layer.geometry_type,
            "has_z": layer.has_z, "identifier": layer.identifier,
            "description": layer.description,
            "style": None if layer.style is None else {
                "name": layer.style.name, "qml": layer.style.qml,
                "description": layer.style.description},
            "columns": [[column.name, column.sql_type, column.not_null, column.default]
                        for column in layer.columns]})
        blobs = [bytes(blob) for blob in layer.blobs]
        arrays[f"blobs{index}"] = np.frombuffer(b"".join(blobs), dtype=np.uint8)
        arrays[f"offsets{index}"] = _offsets([len(blob) for blob in blobs])
        arrays[f"values{index}"] = _text_array({column.name: list(layer.values[column.name])
                                                for column in layer.columns})
    with open(Path(path), "wb") as stream:
        np.savez(stream, **arrays)


def read_export_layers(path: Path | str) -> list[StoredLayer | TinExport]:
    """Las capas de :func:`write_export_layers` (las geometrías, con los mismos bytes)."""
    data = _load_npz(Path(path), ("count",))
    found: list[StoredLayer | TinExport] = []
    for index in range(int(data["count"][0])):
        meta = _json_of(data[f"meta{index}"])
        if meta["kind"] == _TIN_LAYER:
            found.append(TinExport(meta["name"], meta["input"], meta["identifier"],
                                   meta["description"]))
            continue
        raw = data[f"blobs{index}"].tobytes()
        offsets = data[f"offsets{index}"]
        blobs = tuple(raw[int(offsets[i]):int(offsets[i + 1])] for i in range(len(offsets) - 1))
        columns = tuple(ColumnDef(name, sql_type, bool(not_null), default)
                        for name, sql_type, not_null, default in meta["columns"])
        style = meta.get("style")
        found.append(StoredLayer(meta["name"], meta["geometry_type"], bool(meta["has_z"]),
                                 columns, blobs, _json_of(data[f"values{index}"]),
                                 meta["identifier"], meta["description"],
                                 None if style is None else LayerStyle(**style)))
    return found


def _write_conflicts(path: Path, error: ConflictError) -> None:
    values = {key: value for key, value in error.values.items() if key not in ("value", "tin")}
    data = {
        "code": error.code,
        "tin": error.tin,
        "text": error.text,
        "values": values,
        "conflicts": [{"kind": str(item.kind), "ids": list(item.ids), "x": item.x,
                       "y": item.y, "z": list(item.z), "text": text}
                      for item, text in zip(error.conflicts, error.texts(), strict=True)],
    }
    path.write_text(json.dumps(plain(data), ensure_ascii=False, indent=1, allow_nan=False),
                    encoding="utf-8")


def read_conflicts(path: Path | str) -> ConflictError:
    """El ``ConflictError`` del dominio que dejó ``gis_tin_prepare`` en ``conflicts.json``
    (cada conflicto con sus identificadores, su posición y sus cotas), para presentarlo
    (RF-006-14)."""
    data = json.loads(Path(path).read_text("utf-8"))
    conflicts = [Conflict(ConflictKind(item["kind"]), tuple(item["ids"]), float(item["x"]),
                          float(item["y"]), tuple(float(z) for z in item["z"]))
                 for item in data["conflicts"]]
    return ConflictError(data["code"], conflicts, tin=data["tin"], **data["values"])


# --- Lo común de los trabajos --------------------------------------------------------------


def _job_name(request: JobRequest) -> str:
    for candidate in (request.label, request.worker, request.job_uid):
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return OWNER


class _Request:
    """Los parámetros de la petición de un trabajo, comprobados: lo que no vale es
    ``JobError`` ``request_invalid`` (nombra el trabajo y el parámetro)."""

    def __init__(self, ctx: _Context) -> None:
        self.values: Mapping[str, Any] = ctx.request.params
        self.job = _job_name(ctx.request)

    def invalid(self, detail: str) -> JobError:
        return JobError("request_invalid", job=self.job, detail=detail)

    def text(self, key: str, default: str | None = None) -> str:
        value = self.values.get(key, default)
        if not isinstance(value, str):
            raise self.invalid(f"«{key}» no es un texto ({value!r})")
        return value

    def number(self, key: str, default: float | None = None) -> float | None:
        value = self.values.get(key, default)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, numbers.Real):
            raise self.invalid(f"«{key}» no es un número ({value!r})")
        return float(value)

    def integer(self, key: str) -> int | None:
        value = self.values.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
            raise self.invalid(f"«{key}» no es un entero ({value!r})")
        return value

    def mapping(self, key: str, default: Mapping[str, Any] | None = None) -> dict[str, Any]:
        value = self.values.get(key, default)
        if not isinstance(value, Mapping):
            raise self.invalid(f"«{key}» no es un objeto JSON ({value!r})")
        return dict(value)

    def parsed(self, key: str, parse: Callable[[Any], Any], *, required: bool = True) -> Any:
        value = self.values.get(key)
        if value is None and required:
            raise self.invalid(f"falta «{key}»")
        try:
            return parse(value)
        except (ValueError, TypeError) as error:
            raise self.invalid(f"«{key}» no vale: {error}") from None

    def crs(self, key: str, *, required: bool = True) -> CrsRef | None:
        return self.parsed(key, crs_of, required=required)

    def vertical(self, key: str, *, required: bool = True) -> VerticalRef | None:
        return self.parsed(key, vertical_of, required=required)

    def name(self) -> str:
        return self.text("name", "")


def _cancelled(ctx: _Context) -> Cancelled:
    """``cancelled()`` del dominio: si se pidió parar el trabajo (sin lanzar)."""

    def probe() -> bool:
        try:
            ctx.check_cancelled()
        except JobCancelled:
            return True
        return False

    return probe


def _span(ctx: _Context, low: float, high: float) -> Progress:
    """``progress(fracción, texto)`` del dominio en el tramo [``low``, ``high``] del
    avance del trabajo (lanza ``JobCancelled`` si se pidió parar)."""

    def progress(fraction: float, text: str = "") -> None:
        ctx.progress(low + (high - low) * min(max(float(fraction), 0.0), 1.0), text)

    return progress


def _clear_outputs(ctx: _Context) -> None:
    """Deja ``out/`` vacía (cancelación o fallo: ningún resultado, RF-006-28)."""
    folder = ctx.job_dir.outputs_dir
    if not folder.is_dir():
        return
    for child in folder.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)


def _json_values(values: Mapping[str, Any]) -> dict[str, JsonValue]:
    return {str(key): plain(value) for key, value in values.items()}


def _failed(error: GeoblenderError) -> JobFailed:
    """El fallo explicado (RF-004-12) de un error para el usuario del dominio."""
    text = str(error)
    values = getattr(error, "values", None)
    return JobFailed(error.code, msgid=getattr(error, "msgid", None) or text, text=text,
                     values=_json_values(values if isinstance(values, Mapping)
                                         else error.context))


def _job(run: Callable[[_Context], dict[str, Any]]) -> Callable[[_Context], dict[str, Any]]:
    """La función de un trabajo: si se cancela o falla, ``out/`` queda vacía; un error del
    dominio para el usuario es ``JobFailed``."""

    @functools.wraps(run)
    def guarded(ctx: _Context) -> dict[str, Any]:
        try:
            return run(ctx)
        except BaseException as error:
            _clear_outputs(ctx)
            if isinstance(error, GeoblenderError) and not isinstance(error, JobError):
                raise _failed(error) from None
            raise

    return guarded


def _finish(ctx: _Context, outputs: Sequence[JobOutput]) -> None:
    """El último punto de cancelación (con todo escrito) y la declaración de los
    resultados con su huella."""
    ctx.progress(1.0, DONE_TEXT)
    for output in outputs:
        ctx.add_output(ctx.output_path(output.file), output.role)


def _sha256(path: Path, progress: Callable[[float], None] | None = None) -> str:
    """La huella sha256 de ``path`` por bloques de 1 MiB, con ``progress(fracción)`` tras
    cada uno."""
    digest = hashlib.sha256()
    size = max(1, path.stat().st_size) if progress is not None else 1
    read = 0
    with open(path, "rb") as stream:
        while block := stream.read(_HASH_BLOCK):
            digest.update(block)
            if progress is not None:
                read += len(block)
                progress(min(1.0, read / size))
    return digest.hexdigest()


def _dataset_digest_raster(ctx: _Context, raster: Raster, low: float,
                           high: float) -> ContentDigest:
    """El ``ContentDigest`` de la rejilla ``raster`` como dato del proyecto, con su avance en
    el tramo [``low``, ``high``] y la cancelación entre bandas (11,2 M celdas son medio
    segundo de hash; RF-006-28, T33)."""
    from ..core.datasets.model import DATASET_DECLARATIONS  # un dato se hashea sin declaraciones

    return gis_content.raster_digest(raster, DATASET_DECLARATIONS,
                                     progress=_span(ctx, low, high), cancelled=_cancelled(ctx))


def _table_digests(ctx: _Context, crs: CrsRef, tables: Sequence[tuple[JobOutput, str]],
                   low: float, high: float) -> dict[str, dict[str, str]]:
    """El ``ContentDigest`` de cada tabla que será lo importado (T50; RNF-006-09): de cada
    resultado ``(JobOutput, familia)``, las filas que escribirá la orden
    (:func:`imported_rows`, desde el fichero escrito) con su hash de ``core.gpkg_layer@1``
    (``gis.store.table_digest``), por su papel, con el avance repartido en [``low``,
    ``high``] por el tamaño de cada fichero y la cancelación entre trozos. Así el hilo de
    Blender no vuelve a leer una tabla de 300.000 puntos al incorporarla."""
    from .provenance import DOMAINS, FEATURES
    from .store import domain_rows, feature_rows, table_digest  # importa la procedencia

    paths = [ctx.output_path(output.file) for output, _family in tables]
    sizes = [max(1, _size(path)) for path in paths]
    total = sum(sizes)
    found: dict[str, dict[str, str]] = {}
    start = low
    for (output, family), path, size in zip(tables, paths, sizes, strict=True):
        end = start + (high - low) * size / total
        ctx.progress(start, TABLE_HASH_TEXT)
        columns = geometry_type = None
        if family == DOMAINS:  # con las columnas de su capa (spec 011, D-32)
            domains = read_domains(path)
            rows, columns = domain_rows(domains, crs.epsg), domains.column_defs
        elif family == FEATURES:  # con sus columnas y su geometría (spec 012, D-27)
            layer = read_features(path)
            rows, columns = feature_rows(layer, crs.epsg), layer.column_defs
            geometry_type = layer.geometry_type
        else:
            rows = imported_rows(family, path, crs.epsg)
        digest = table_digest(family, rows, crs, columns=columns, geometry_type=geometry_type,
                              progress=_span(ctx, start, end), cancelled=_cancelled(ctx))
        found[output.role] = digest_json(digest)
        start = end
    return found


def _copy_sources(ctx: _Context, request: _Request, roles: Sequence[str], *,
                  sqlite: bool = False, low: float = 0.0,
                  high: float = 0.0) -> tuple[dict[str, Path], dict[str, dict[str, Any]]]:
    """Las copias verificadas en ``in/`` de los ficheros de la fuente que llegan por
    ``--path`` (``source_<papel>``; todas con el nombre ``source_main`` y su extensión: el
    ``.prj`` queda junto a su ASC) y sus huellas (sha256, tamaño y fecha). Con ``sqlite`` (un
    GeoPackage), también el ``-wal`` o el diario de la principal, junto a su copia
    (``in/source_main.gpkg-wal``; plan §5.6.4, D9), sin que cambie mientras se copian. El
    avance de cada copia y de su huella (cada MiB; los ficheros, por su tamaño) va en el
    tramo [``low``, ``high``] con :data:`COPYING_TEXT`, y cada aviso es un punto de
    cancelación (RF-006-28, T33: una fuente grande o en red tarda)."""
    files: dict[str, Path] = {}
    prints: dict[str, dict[str, Any]] = {}
    found = {role: Path(path) for role in roles
             if (path := ctx.paths.get(path_name(role))) is not None}
    sizes = {role: _size(path) for role, path in found.items()}
    total = max(1, sum(sizes.values()))
    done = 0
    for role in roles:
        source = found.get(role)
        if source is None:
            if role == MAIN_ROLE:
                raise request.invalid(f"falta la ruta «{path_name(role)}» de la fuente (--path)")
            continue
        ctx.check_cancelled()
        start = low + (high - low) * done / total
        done += sizes[role]
        span = _span(ctx, start, low + (high - low) * done / total)
        before = _stamp(Path(source))
        relative = ctx.job_dir.copy_input(Path(source), path_name(MAIN_ROLE), job=request.job,
                                          progress=_part(span, 0.0, COPY_SHARE, COPYING_TEXT))
        copy = ctx.job_dir.path / relative
        if sqlite and role == MAIN_ROLE:
            for suffix in SQLITE_SIDES:
                side = side_file(Path(source), suffix)
                if side.is_file():
                    ctx.check_cancelled()
                    ctx.job_dir.copy_input(side, path_name(MAIN_ROLE), job=request.job)
        if before is None or _stamp(Path(source)) != before:
            raise JobError("source_changed", job=request.job, path=source)
        files[role] = copy
        sha256 = _sha256(copy, _part(span, COPY_SHARE, 1.0, COPYING_TEXT))
        prints[role] = {"sha256": sha256, "size": before[0], "mtime_ns": before[1]}
    return files, prints


def _part(span: Progress, low: float, high: float, text: str) -> Callable[[float], None]:
    """``progress(fracción)`` de una parte [``low``, ``high``] del tramo ``span``, con
    ``text``."""

    def progress(fraction: float) -> None:
        span(low + (high - low) * min(max(float(fraction), 0.0), 1.0), text)

    return progress


def _stamp(path: Path) -> tuple[int, int] | None:
    try:
        info = path.stat()
    except OSError:
        return None
    return info.st_size, info.st_mtime_ns


def _size(path: Path) -> int:
    """El tamaño de ``path`` para repartir el avance (0 si no se puede leer: lo dirá la
    copia)."""
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _source_digest(ctx: _Context, reader: ContentReader, kind: str, files: Mapping[str, Path],
                   declarations: Mapping[str, Any], settings: Mapping[str, Any],
                   low: float, high: float, text: str = HASHING_TEXT) -> ContentDigest:
    """El ``ContentDigest`` de la fuente con su lector de contenido (el mismo que da
    ``core_content_hash``), con avance y cancelación entre trozos (``text``, lo que dice el
    avance)."""
    request = reader.request(kind, declarations, files, settings, normalizer=NORMALIZER)
    steps = read_steps(reader, request)
    try:
        ctx.check_cancelled()
        for done in steps:
            ctx.progress(low + (high - low) * done, text)
    except (ValueError, TypeError) as error:  # ajustes de lectura que el lector no admite
        raise JobError("request_invalid", job=_job_name(ctx.request), detail=str(error)) from None
    finally:
        steps.close()
    return request.hasher.digest()


def _source_summary(reader: ContentReader, digest: ContentDigest,
                    prints: Mapping[str, Any], declarations: Mapping[str, Any],
                    settings: Mapping[str, Any]) -> dict[str, Any]:
    return {"reader": reader.id, "digest": digest_json(digest), "files": dict(prints),
            "declarations": dict(declarations), "settings": plain(settings)}


def _reader(request: _Request, allowed: Sequence[ContentReader]) -> ContentReader:
    reader_id = request.text("reader", "")
    for reader in allowed:
        if reader.id == reader_id:
            return reader
    raise request.invalid(f"el lector «{reader_id}» no es uno de "
                          f"{', '.join(reader.id for reader in allowed)}")


def _settings(request: _Request, reader: ContentReader) -> dict[str, Any]:
    settings = request.mapping("settings", {})
    allowed = gis_content.READER_SETTINGS[reader.id]
    unknown = sorted(key for key in settings if key not in allowed)
    if unknown:
        raise request.invalid(f"ajustes que no son de lectura de «{reader.id}»: {unknown}")
    return settings


def _column_mapping(request: _Request, settings: Mapping[str, Any]) -> ColumnMapping:
    """La correspondencia de columnas de un texto de puntos (``settings["columns"]``: papel →
    índice desde 0 o ``None``), con los ajustes de lectura que no pueden faltar."""
    missing = [key for key in gis_content.POINTS_REQUIRED if key not in settings]
    if missing:
        raise request.invalid(f"faltan ajustes de lectura del texto de puntos: {missing}")
    if settings.get("line_kind", "hard") not in gis_content.LINE_KINDS:
        raise request.invalid(f"tipo de línea {settings['line_kind']!r} no admitido: "
                              f"{list(gis_content.LINE_KINDS)}")
    columns = settings["columns"]
    if not isinstance(columns, Mapping) or not set(columns) <= set(gis_content.MAPPING_ROLES):
        raise request.invalid(f"«columns» es {{papel: índice}} con los papeles "
                              f"{list(gis_content.MAPPING_ROLES)}, no {columns!r}")
    try:
        return ColumnMapping(**{role: columns.get(role) for role in gis_content.MAPPING_ROLES})
    except (ValueError, TypeError) as error:
        raise request.invalid(str(error)) from None


def _declarations(request: _Request, reader: ContentReader, crs: CrsRef | None,
                  vertical: VerticalRef | None, settings: Mapping[str, Any]) -> dict[str, Any]:
    from .store import source_declarations  # importa la procedencia: solo al usarlo

    try:
        return source_declarations(reader.id, crs, vertical, settings)
    except (ValueError, TypeError) as error:
        raise request.invalid(str(error)) from None


def _surface(ctx: _Context, request: _Request, *, low: float = 0.0,
             high: float = 0.0) -> Raster | Tin:
    """La superficie del proyecto copiada a ``in/source``: una rejilla (``.tif``, con el CRS
    y la referencia vertical de la petición) o un TIN (``.npz``)."""
    path = ctx.input_path(INPUT_SOURCE)
    kind = _SURFACE_SUFFIXES.get(path.suffix.lower())
    if kind is None:
        raise request.invalid(f"la superficie «{path.name}» no es una rejilla (.tif) ni un "
                              "TIN (.npz)")
    if kind == "tin":
        ctx.check_cancelled()
        return load_tin(path)
    return _project_raster(ctx, request, path, "crs", "vertical", low, high)


def _project_raster(ctx: _Context, request: _Request, path: Path, crs_key: str,
                    vertical_key: str, low: float, high: float) -> Raster:
    crs = request.crs(crs_key)
    vertical = request.vertical(vertical_key)
    source = read_geotiff(path, max_cells=_UNLIMITED, progress=_span(ctx, low, high),
                          cancelled=_cancelled(ctx))
    if source.declared_crs is not None and source.declared_crs.epsg != crs.epsg:
        raise request.invalid(f"la rejilla «{path.name}» está en EPSG:"
                              f"{source.declared_crs.epsg}, no en el «{crs_key}» de la "
                              f"petición (EPSG:{crs.epsg})")
    return Raster(source.grid, source.values, crs, vertical)


def _write_report(ctx: _Context, report: object) -> None:
    ctx.output_path(OUT_REPORT.file).write_text(
        json.dumps(plain(report), ensure_ascii=False, indent=1, allow_nan=False),
        encoding="utf-8")


def _count_estimate(rate_s: float) -> Callable[[Mapping[str, Any]], float | None]:
    """La estimación ``count`` × ``rate_s`` (``count``: celdas o puntos de la petición);
    ``None`` sin ``count``."""

    def estimate(params: Mapping[str, Any]) -> float | None:
        count = params.get("count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            return None
        return count * rate_s

    return estimate


def _size_estimate(params: Mapping[str, Any], reader: ContentReader | None) -> float | None:
    size = params.get("size")
    if reader is None or reader.estimate_s is None:
        return None
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        return None
    seconds = reader.estimate_s(size)
    return None if seconds is None else READ_PASSES * float(seconds)


_IMPORT_READERS: Mapping[str, ContentReader] = MappingProxyType(
    {reader.id: reader for reader in (gis_content.GEOTIFF, gis_content.ASC,
                                      gis_content.XYZ_GRID)})


def _read_estimate(params: Mapping[str, Any]) -> float | None:
    reader = params.get("reader")
    return _size_estimate(params, _IMPORT_READERS.get(reader) if isinstance(reader, str) else None)


def _points_estimate(params: Mapping[str, Any]) -> float | None:
    if params.get("reader") != gis_content.POINTS_TEXT.id:
        return None
    return _size_estimate(params, gis_content.POINTS_TEXT)


def _vector_estimate(params: Mapping[str, Any]) -> float | None:
    if params.get("reader") != gis_content.GPKG_LAYER.id:
        return None
    return _size_estimate(params, gis_content.GPKG_LAYER)


def _resample_estimate(params: Mapping[str, Any]) -> float | None:
    """Sin estimación (proceso aparte) si reproyecta (D11); si no, leer la fuente de
    ``size`` bytes y calcular y escribir la rejilla destino."""
    if reprojects(params):
        return None
    try:
        target = grid_of(params.get("target"))
    except (ValueError, TypeError):
        return None
    size = params.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        return None
    return size / gis_content.GEOTIFF_BYTES_PER_S + target.ncols * target.nrows * 2 * CELL_S


# --- Los trabajos ----------------------------------------------------------------------------


@_job
def run_read_raster(ctx: _Context) -> dict[str, Any]:
    """``gis_read_raster``: una fuente GeoTIFF, ASC o XYZ en malla a ``out/source.tif``
    (perfil ``project``, en su rejilla de origen y con su CRS y su referencia vertical
    declarados), con el hash de la fuente y de la rejilla (RF-006-08, RF-006-26)."""
    request = _Request(ctx)
    reader = _reader(request, tuple(_IMPORT_READERS.values()))
    settings = _settings(request, reader)
    name = request.name()
    declared_crs = request.crs("crs", required=False)
    declared_vertical = request.vertical("vertical", required=False)
    max_cells = request.integer("max_cells")
    override = settings.get("nodata_override")
    if override is not None and (isinstance(override, bool)
                                 or not isinstance(override, numbers.Real)
                                 or not math.isfinite(override)):
        raise request.invalid(f"el sin dato forzado es un número finito o nada, no {override!r}")
    prj_crs = request.crs("prj_crs", required=False)
    origin = request.parsed("origin", lambda value: None if value is None else origin_of(value),
                            required=False)
    ctx.progress(0.0, COPYING_TEXT)
    roles = (MAIN_ROLE, PRJ_ROLE) if reader is gis_content.ASC else (MAIN_ROLE,)
    files, prints = _copy_sources(ctx, request, roles, low=0.0, high=0.1)
    main = files[MAIN_ROLE]
    # Se lee la copia de in/, pero las notas y los fallos nombran el fichero del usuario (T52).
    shown = Path(ctx.paths[path_name(MAIN_ROLE)]).name
    progress, cancelled = _span(ctx, 0.1, 0.4), _cancelled(ctx)
    if reader is gis_content.GEOTIFF:
        source = read_geotiff(main, name=shown, max_cells=max_cells, progress=progress,
                              cancelled=cancelled)
    elif reader is gis_content.ASC:
        source = read_asc(main, name=shown, max_cells=max_cells, prj_crs=prj_crs,
                          progress=progress, cancelled=cancelled)
    else:
        try:
            source = read_xyz_grid(main, separator=settings.get("separator"),
                                   decimal=settings.get("decimal", "."), name=shown,
                                   max_cells=max_cells, progress=progress, cancelled=cancelled)
        except ValueError as error:
            raise request.invalid(str(error)) from None
    crs, vertical = Declaration(name or shown,
                                declared_crs or source.declared_crs,
                                declared_vertical or source.declared_vertical).require()
    values = source.values
    if override is not None:
        values = np.where(values == float(override), np.nan, values)
    raster = Raster(source.grid, values, crs, vertical)
    declarations = _declarations(request, reader, crs, vertical, settings)
    digest = _source_digest(ctx, reader, "raster", files, declarations, settings, 0.4, 0.6)
    ctx.progress(0.6, WRITING_TEXT)
    GeoTiffIO().write(raster, ctx.output_path(OUT_SOURCE_GRID.file), profile="project",
                      progress=_span(ctx, 0.6, 0.9), cancelled=cancelled)
    written = _dataset_digest_raster(ctx, raster, 0.9, 0.99)
    # Las posiciones de la comparación con la rejilla del proyecto (T54; RF-006-06): las de lo
    # escrito, bit a bit; la orden no vuelve a leer la rejilla en el hilo de Blender.
    from .dtm import vertical_samples  # gis.dtm importa este módulo: solo al usarlo

    write_samples(ctx.output_path(OUT_SAMPLES.file), vertical_samples(raster))
    valid = np.isfinite(values)
    extent = data_extent(source.grid, valid)
    summary = {
        "source": _source_summary(reader, digest, prints, declarations, settings),
        "crs": crs_json(crs),
        "vertical": vertical_json(vertical),
        "grid": grid_json(source.grid),
        "encoding": source.encoding,
        "source_dtype": source.source_dtype,
        "nodata_value": plain(source.nodata_value),
        "pixel_is_point": bool(source.pixel_is_point),
        "notes": list(source.notes),
        "valid_cells": int(np.count_nonzero(valid)),
        # Dónde caen sus celdas con dato (T51; spec §8, RF-002-26): la orden lo dice.
        "data_extent": None if extent is None else window_json(extent),
        "outputs": {
            OUT_SOURCE_GRID.role: {"file": OUT_SOURCE_GRID.relative,
                                   "digest": digest_json(written)},
            OUT_SAMPLES.role: {"file": OUT_SAMPLES.relative},
        },
    }
    if origin is not None:
        summary["precision"] = precision_json(cells_precision(source.grid, valid, origin))
    _finish(ctx, (OUT_SOURCE_GRID, OUT_SAMPLES))
    return summary


@_job
def run_resample(ctx: _Context) -> dict[str, Any]:
    """``gis_resample``: la rejilla ``in/source.tif`` a la rejilla ``target`` del proyecto
    (media por área, bilineal o moda; RF-006-11, RF-006-30) o, con otro CRS u otra referencia
    vertical, reproyectada con el servicio de CRS (RF-006-05; en proceso aparte con
    ``--site``): ``grid.tif`` e informe."""
    request = _Request(ctx)
    name = request.name() or "MDT"
    target = request.parsed("target", grid_of)
    target_crs = request.crs("target_crs")
    target_vertical = request.vertical("target_vertical")
    method_text = request.text("method", "auto")
    fraction = request.number("min_valid_fraction")
    supersample = request.integer("supersample")
    if method_text not in ("auto", *(method.value for method in ResampleMethod)):
        raise request.invalid(f"método de remuestreo desconocido «{method_text}»")
    ctx.progress(0.0, READING_TEXT)
    source = _project_raster(ctx, request, ctx.input_path(INPUT_SOURCE), "source_crs",
                             "source_vertical", 0.0, 0.2)
    progress, cancelled = _span(ctx, 0.2, 0.85), _cancelled(ctx)
    method = (choose_method(source.grid, target) if method_text == "auto"
              else ResampleMethod(method_text))
    transform = None
    if needs_transform(source.crs, source.vertical, target_crs, target_vertical):
        if method is ResampleMethod.MODE:
            raise request.invalid("la moda de clases no se reproyecta")
        service = require_crs_service()
        transform = transformation_for(Declaration(name, source.crs, source.vertical),
                                       target_crs, target_vertical, service=service)
        inverse = service.transformer(target_crs, target_vertical, source.crs,
                                      source.vertical)
        grid, report = reproject_to_grid(
            source, target, transform=transform, inverse=inverse, target_crs=target_crs,
            target_vertical=target_vertical, method=method, min_valid_fraction=fraction,
            supersample=supersample, name=name, progress=progress, cancelled=cancelled)
    elif method is ResampleMethod.MODE:
        grid, report = resample_classes_to_grid(source, target, min_valid_fraction=fraction,
                                                name=name, progress=progress,
                                                cancelled=cancelled)
    else:
        grid, report = resample_to_grid(source, target, method=method,
                                        min_valid_fraction=fraction, progress=progress,
                                        cancelled=cancelled)
    ctx.progress(0.85, WRITING_TEXT)
    GeoTiffIO().write(grid, ctx.output_path(OUT_PROJECT_GRID.file), profile="project",
                      progress=_span(ctx, 0.85, 0.96), cancelled=cancelled)
    written = _dataset_digest_raster(ctx, grid, 0.96, 0.99)
    _write_report(ctx, report)
    summary = {
        "method": str(report.method),
        "cells": report.cells,
        "valid_cells": report.valid_cells,
        "grid": grid_json(target),
        "reprojected": transform is not None,
        "transform": None if transform is None else {
            **plain(transform.info), "summary": transform_summary(transform.info)},
        "outputs": {
            OUT_PROJECT_GRID.role: {"file": OUT_PROJECT_GRID.relative,
                                    "digest": digest_json(written)},
            OUT_REPORT.role: {"file": OUT_REPORT.relative}},
    }
    _finish(ctx, (OUT_PROJECT_GRID, OUT_REPORT))
    return summary


@_job
def run_import_points(ctx: _Context) -> dict[str, Any]:
    """``gis_import_points``: un texto de puntos (CSV, TXT o XYZ disperso) a ``points.npz`` y
    ``lines.npz`` (coordenadas ABSOLUTAS de la fuente, en float64) con su informe, el hash
    de la fuente (RF-006-12, RF-006-26) y el de las tablas que serán lo importado (T50:
    :func:`_table_digests`; RNF-006-09). Lee con el lector de tablas de ``interop`` que le da
    su envoltorio (``gis.content.use_table_reader``)."""
    from .provenance import BREAKLINES, POINTS  # importa la procedencia: solo al usarlo

    request = _Request(ctx)
    reader = _reader(request, (gis_content.POINTS_TEXT,))
    settings = _settings(request, reader)
    name = request.name()
    crs, vertical = Declaration(name or "puntos", request.crs("crs", required=False),
                                request.vertical("vertical", required=False)).require()
    declarations = _declarations(request, reader, crs, vertical, settings)
    tables = gis_content.table_reader()
    if tables is None:
        raise RuntimeError("el trabajo de puntos no tiene lector de tablas de texto: se lo da "
                           "su envoltorio (gis.content.use_table_reader)")
    mapping = _column_mapping(request, settings)
    ctx.progress(0.0, COPYING_TEXT)
    files, prints = _copy_sources(ctx, request, (MAIN_ROLE,), low=0.0, high=0.05)
    digest = _source_digest(ctx, reader, "table", files, declarations, settings, 0.05, 0.3)
    ctx.progress(0.3, READING_TEXT)
    table = tables(files[MAIN_ROLE], encoding=settings["encoding"],
                   separator=settings["separator"], header_row=settings.get("header_row", 0))
    ctx.progress(0.45, READING_TEXT)
    points, lines, report = points_from_rows(
        table.columns, table.rows, mapping, settings["decimal"], source=name,
        row_numbers=table.lines, hard=settings.get("line_kind", "hard") == "hard")
    report = dataclasses.replace(report, duplicates=_duplicates(request, points))
    ctx.progress(0.55, WRITING_TEXT)
    write_points(ctx.output_path(OUT_POINTS.file), points)
    write_lines(ctx.output_path(OUT_LINES.file), lines)
    _write_report(ctx, report)
    imported = [(OUT_POINTS, POINTS)] if len(points) else []
    imported += [(OUT_LINES, BREAKLINES)] if lines else []
    digests = _table_digests(ctx, crs, imported, 0.6, 0.99)
    summary = {
        "source": _source_summary(reader, digest, prints, declarations, settings),
        "crs": crs_json(crs),
        "vertical": vertical_json(vertical),
        "read": report.read,
        "points": len(points),
        "lines": len(lines),
        "rejected": len(report.rejected),
        "duplicates": report.duplicates,
        "outputs": {output.role: {"file": output.relative,
                                  **({"digest": digests[output.role]}
                                     if output.role in digests else {})}
                    for output in (OUT_POINTS, OUT_LINES, OUT_REPORT)},
    }
    _finish(ctx, (OUT_POINTS, OUT_LINES, OUT_REPORT))
    return summary


@_job
def run_tin_prepare(ctx: _Context) -> dict[str, Any]:
    """``gis_tin_prepare``: duplicados y restricciones (``gis.tin.prepare_tin``; RF-006-13,
    RF-006-14) de ``in/points.npz`` (o sus arrays sueltos, :func:`point_inputs`) e
    ``in/lines.npz``: ``prepared.npz`` o, con conflictos, ``conflicts.json`` (sin TIN)."""
    request = _Request(ctx)
    name = request.name()
    tol_xy, tol_z = request.number("tol_xy"), request.number("tol_z")
    try:
        policy = DuplicatePolicy(request.text("duplicate_policy", DuplicatePolicy.ASK.value))
    except ValueError as error:
        raise request.invalid(str(error)) from None
    entries = ctx.request.inputs
    found = _input_arrays(ctx, request, INPUT_POINTS, _POINT_KEYS)
    if found is None and INPUT_LINES not in entries:
        raise request.invalid("no hay puntos ni líneas de rotura que triangular")
    points = (_points_from(found) if found is not None
              else PointSet(np.zeros((0, 3)), (), (), ()))
    lines = read_lines(ctx.input_path(INPUT_LINES)) if INPUT_LINES in entries else []
    try:
        source = prepare_tin(points, lines, tol_xy=tol_xy, tol_z=tol_z,
                             duplicate_policy=policy, name=name,
                             progress=_span(ctx, 0.05, 0.9), cancelled=_cancelled(ctx))
    except ConflictError as error:
        _write_conflicts(ctx.output_path(OUT_CONFLICTS.file), error)
        summary = {"conflicts": len(error.conflicts), "code": error.code, "text": error.text,
                   "outputs": {OUT_CONFLICTS.role: {"file": OUT_CONFLICTS.relative}}}
        _finish(ctx, (OUT_CONFLICTS,))
        return summary
    ctx.progress(0.9, WRITING_TEXT)
    write_tin_input(ctx.output_path(OUT_PREPARED.file), source)
    prepared = source.prepared
    summary = {
        "conflicts": 0,
        "vertices": len(prepared.xyz),
        "constraint_edges": len(prepared.edges),
        "input_points": source.input_points,
        "duplicates_merged": source.duplicates_merged + prepared.merged,
        "crossings": prepared.crossings,
        "splits": prepared.splits,
        "outputs": {OUT_PREPARED.role: {"file": OUT_PREPARED.relative}},
    }
    _finish(ctx, (OUT_PREPARED,))
    return summary


@_job
def run_triangulate(ctx: _Context) -> dict[str, Any]:
    """``gis_triangulate``: los triángulos de ``in/prepared.npz`` con ``PureTriangulator``
    en coordenadas locales respecto al GeoOrigin (RF-006-13; por encima del límite de la CDT
    de Blender en el hilo, ``gis.tin.blender_cdt_max_s``), con avance y cancelación:
    ``faces.npy``."""
    request = _Request(ctx)
    origin = request.parsed("origin", origin_of)
    source = _prepared_input(ctx, request)
    xy = world_to_local(source.prepared.xyz[:, :2], origin)
    triangulator = PureTriangulator(progress=_span(ctx, 0.0, 0.95), cancelled=_cancelled(ctx))
    faces = np.ascontiguousarray(triangulator.triangulate(xy, source.prepared.edges),
                                 dtype=np.int32)
    ctx.progress(0.95, WRITING_TEXT)
    with open(ctx.output_path(OUT_FACES.file), "wb") as stream:
        np.save(stream, faces, allow_pickle=False)
    summary = {"triangulator": triangulator.name, "triangles": len(faces),
               "outputs": {OUT_FACES.role: {"file": OUT_FACES.relative}}}
    _finish(ctx, (OUT_FACES,))
    return summary


def _prepared_input(ctx: _Context, request: _Request) -> TinInput:
    """Lo que se triangula: ``in/prepared.npz`` o sus arrays sueltos (:func:`tin_inputs`)."""
    found = _input_arrays(ctx, request, INPUT_PREPARED, _TIN_INPUT_KEYS)
    if found is None:
        raise request.invalid("falta lo que se triangula («prepared»)")
    return _tin_input_from(found)


@_job
def run_tin_finish(ctx: _Context) -> dict[str, Any]:
    """``gis_tin_finish``: el TIN de ``in/prepared.npz`` (o sus arrays sueltos) con los
    triángulos de ``in/faces.npy`` (``gis.tin.finish_tin``: orientación, contorno y huecos de
    ``in/regions.npz``, lado máximo y estadísticas; RF-006-13, RF-006-15) en ``tin.npz``, con
    el ``meta`` del proyecto y de la operación de la petición y su hash (``core.npz_mesh@1``),
    e informe."""
    request = _Request(ctx)
    operation_uid = ctx.request.operation_uid
    if not isinstance(operation_uid, str) or not operation_uid:
        raise request.invalid("el TIN necesita la operación que lo crea (operation_uid)")
    name = request.name()
    origin = request.parsed("origin", origin_of)
    triangulator = request.text("triangulator", "")
    if not triangulator:
        raise request.invalid("falta el triangulador que dio los triángulos («triangulator»)")
    max_edge = request.number("max_edge_m")
    crs, vertical = request.crs("crs"), request.vertical("vertical")
    source = _prepared_input(ctx, request)
    with open(ctx.input_path(INPUT_FACES), "rb") as stream:
        faces = np.load(stream, allow_pickle=False)
    boundary, holes = (read_regions(ctx.input_path(INPUT_REGIONS))
                       if INPUT_REGIONS in ctx.request.inputs else (None, []))
    ctx.progress(0.1, "Filtros y estadísticas del TIN…")
    tin, report = finish_tin(source, faces, triangulator=triangulator, origin=origin,
                             boundary=boundary, holes=holes, max_edge_m=max_edge, name=name,
                             progress=_span(ctx, 0.1, 0.5), cancelled=_cancelled(ctx))
    ctx.progress(0.5, WRITING_TEXT)
    meta = {"crs_epsg": crs.epsg, "vertical": meta_vertical(vertical),
            "operation_uid": operation_uid}
    save_tin(tin, ctx.output_path(OUT_TIN.file), meta, progress=_span(ctx, 0.5, 0.85))
    _write_report(ctx, report)
    ctx.progress(0.85, RESULT_HASH_TEXT)
    from ..core.datasets.model import DATASET_DECLARATIONS

    summary = {
        "triangulator": triangulator,
        "vertices": len(tin.vertices),
        "triangles": len(tin.faces),
        "outputs": {
            OUT_TIN.role: {"file": OUT_TIN.relative, "digest": digest_json(
                gis_content.tin_digest(tin, meta, DATASET_DECLARATIONS))},
            OUT_REPORT.role: {"file": OUT_REPORT.relative}},
    }
    _finish(ctx, (OUT_TIN, OUT_REPORT))
    return summary


@_job
def run_contours(ctx: _Context) -> dict[str, Any]:
    """``gis_contours``: las curvas de nivel de la rejilla o del TIN de ``in/source``
    (RF-006-18) en ``contours.npz``."""
    request = _Request(ctx)
    name = request.name()
    options = {key: request.number(key) for key in ("interval_m", "index_every_m",
                                                    "index_offset_m", "simplify_m",
                                                    "min_length_m")}
    base = request.number("base_m", 0.0)
    surface = _surface(ctx, request, low=0.0, high=0.2)
    compute: Callable[..., list[ContourLine]] = (
        contours_from_tin if isinstance(surface, Tin) else contours_from_raster)
    lines = compute(surface, base_m=base, name=name, progress=_span(ctx, 0.2, 0.9),
                    cancelled=_cancelled(ctx), **options)
    ctx.progress(0.9, WRITING_TEXT)
    write_contours(ctx.output_path(OUT_CONTOURS.file), lines)
    summary = {"contours": len(lines),
               "index": sum(1 for line in lines if line.is_index),
               "vertices": sum(len(line.xyz) for line in lines),
               "outputs": {OUT_CONTOURS.role: {"file": OUT_CONTOURS.relative}}}
    _finish(ctx, (OUT_CONTOURS,))
    return summary


@_job
def run_validate(ctx: _Context) -> dict[str, Any]:
    """``gis_validate``: el informe de la superficie de ``in/source`` (RF-006-23) en
    ``report.json``."""
    request = _Request(ctx)
    window = request.parsed("window", lambda value: Window(**dict(value)))
    z_range = request.values.get("z_range")
    if z_range is not None and (not isinstance(z_range, list | tuple) or len(z_range) != 2):
        raise request.invalid(f"«z_range» es [mínima, máxima], no {z_range!r}")
    surface = _surface(ctx, request, low=0.0, high=0.5)
    ctx.progress(0.5, "Validando la superficie…")
    check = validate_tin if isinstance(surface, Tin) else validate_raster
    report = check(surface, window=window,  # type: ignore[arg-type]
                   z_range=None if z_range is None else tuple(z_range))
    _write_report(ctx, report)
    summary = {"surface": "tin" if isinstance(surface, Tin) else "grid",
               "outputs": {OUT_REPORT.role: {"file": OUT_REPORT.relative}}}
    _finish(ctx, (OUT_REPORT,))
    return summary


@_job
def run_export(ctx: _Context) -> dict[str, Any]:
    """``gis_export``: con ``format = "geotiff"`` (por defecto), la rejilla de
    ``in/source.tif`` como GeoTIFF entregable (Float32, −9999; RF-006-24) en ``export.tif``;
    con ``"gpkg"`` (T31), las capas de ``in/layers.npz`` (y sus TIN) en un GeoPackage con Z y
    el CRS de la petición (``gis.vector.write_layers``; RF-006-25) en ``export.gpkg``. Con el
    hash de contenido de lo escrito (``gis.geotiff@1``, ``core.document@1``) para
    registrarlo como dato ``exports`` si va a ``exports/`` del proyecto."""
    from ..core.datasets.model import DATASET_DECLARATIONS

    request = _Request(ctx)
    chosen = request.text("format", GEOTIFF_FORMAT)
    if chosen not in EXPORT_FORMATS:
        raise request.invalid(f"«format» es uno de {list(EXPORT_FORMATS)}, no {chosen!r}")
    if chosen == GPKG_FORMAT:
        return _export_gpkg(ctx, request)
    surface = _surface(ctx, request, low=0.0, high=0.4)
    if isinstance(surface, Tin):
        raise request.invalid("solo una rejilla se exporta a GeoTIFF")
    ctx.progress(0.4, WRITING_TEXT)
    path = ctx.output_path(OUT_EXPORT.file)
    GeoTiffIO().write(surface, path, profile="deliverable", progress=_span(ctx, 0.4, 0.9),
                      cancelled=_cancelled(ctx))
    digest = _source_digest(ctx, gis_content.GEOTIFF, "raster", {MAIN_ROLE: path},
                            DATASET_DECLARATIONS, {}, 0.9, 0.98, EXPORT_HASH_TEXT)
    summary = {"grid": grid_json(surface.grid),
               "valid_cells": int(np.count_nonzero(np.isfinite(surface.values))),
               "outputs": {OUT_EXPORT.role: {"file": OUT_EXPORT.relative,
                                             "digest": digest_json(digest)}}}
    _finish(ctx, (OUT_EXPORT,))
    return summary


def _export_gpkg(ctx: _Context, request: _Request) -> dict[str, Any]:
    """Las capas de ``in/layers.npz`` a ``out/export.gpkg`` (véase :func:`run_export`)."""
    crs, vertical = request.crs("crs"), request.vertical("vertical")
    ctx.progress(0.0, READING_TEXT)
    try:
        exported = read_export_layers(ctx.input_path(INPUT_LAYERS))
    except (ValueError, KeyError, TypeError) as error:
        raise request.invalid(f"«{INPUT_LAYERS}» no es la lista de capas de una exportación: "
                              f"{error}") from None
    layers = []
    for item in exported:
        ctx.check_cancelled()
        if isinstance(item, TinExport):
            if not item.input.startswith(TIN_INPUT_PREFIX):
                raise request.invalid(f"la entrada del TIN «{item.name}» es «{item.input}», no "
                                      f"«{TIN_INPUT_PREFIX}<n>»")
            tin = load_tin(ctx.input_path(item.input))
            layers.append(tin_layer(tin, item.name, identifier=item.identifier,
                                    description=item.description))
        else:
            try:
                layers.append(item.decoded(crs.epsg))
            except ValueError as error:
                raise request.invalid(str(error)) from None
    ctx.progress(0.2, WRITING_TEXT)
    path = ctx.output_path(OUT_EXPORT_GPKG.file)
    write_layers(path, layers, crs, vertical, progress=_span(ctx, 0.2, 0.95),
                 cancelled=_cancelled(ctx))
    digest = _source_digest(ctx, DOCUMENT, "document", {MAIN_ROLE: path}, {}, {}, 0.95, 0.98,
                            EXPORT_HASH_TEXT)
    summary = {"layers": [[layer.name, len(layer.geometries)] for layer in layers],
               "outputs": {OUT_EXPORT_GPKG.role: {"file": OUT_EXPORT_GPKG.relative,
                                                  "digest": digest_json(digest)}}}
    _finish(ctx, (OUT_EXPORT_GPKG,))
    return summary


@_job
def run_view_arrays(ctx: _Context) -> dict[str, Any]:
    """``gis_view_arrays``: la malla de vista de la superficie de ``in/source`` (ABSOLUTA,
    float64; la vista resta el GeoOrigin) y, de una rejilla, las de sus niveles de detalle
    (``lod_steps`` o ``gis.view.lod_steps_m``; RF-006-21, RF-006-22) en ``mesh.npz``."""
    request = _Request(ctx)
    steps = request.values.get("lod_steps")
    if steps is not None and not isinstance(steps, list | tuple):
        raise request.invalid(f"«lod_steps» es una lista de pasos (m), no {steps!r}")
    surface = _surface(ctx, request, low=0.0, high=0.2)
    cancelled = _cancelled(ctx)
    meshes: dict[float | None, MeshArrays] = {}
    if isinstance(surface, Tin):
        meshes[None] = surface_mesh_from_tin(surface)
    else:
        name = request.name()
        meshes[None] = surface_mesh_from_raster(surface, name=name,
                                                progress=_span(ctx, 0.2, 0.6),
                                                cancelled=cancelled)
        levels = lod_rasters(surface, None if steps is None else list(steps),
                             progress=_span(ctx, 0.6, 0.75), cancelled=cancelled)
        for step, level in levels.items():
            meshes[float(step)] = surface_mesh_from_raster(level, name=name,
                                                           cancelled=cancelled)
    ctx.progress(0.9, WRITING_TEXT)
    write_mesh(ctx.output_path(OUT_MESH.file), meshes)
    summary = {"levels": sorted(step for step in meshes if step is not None),
               "vertices": len(meshes[None].vertices),
               "faces": len(meshes[None].faces),
               "outputs": {OUT_MESH.role: {"file": OUT_MESH.relative}}}
    _finish(ctx, (OUT_MESH,))
    return summary


def _duplicates(request: _Request, points: PointSet) -> int:
    """Los puntos que coinciden en planta con otro anterior (``gis.points.find_duplicates``
    con ``tol_xy`` y ``tol_z`` de la petición o, sin ellas, las de ``gis/params.py``): el
    ``TopoReport.duplicates`` de una importación (RF-006-12)."""
    try:
        tol_xy, tol_z = duplicate_tolerances(request.number("tol_xy"), request.number("tol_z"))
    except GeoblenderError as error:
        raise request.invalid(str(error)) from None
    if not len(points):
        return 0
    labels = [pid or f"#{row}" for pid, row in zip(points.point_ids, points.source_rows,
                                                   strict=True)]
    return find_duplicates(points.xyz, tol_xy=tol_xy, tol_z=tol_z, ids=labels).duplicates


def _layer_settings(request: _Request, settings: Mapping[str, Any]) -> tuple[str, str,
                                                                             str | None]:
    """La capa, su papel (uno de :data:`LAYER_OUTPUTS`) y el campo de cota (solo en curvas)
    de una importación de una capa; si no valen, ``request_invalid``."""
    layer, role = settings.get("layer"), settings.get("role")
    field = settings.get("elevation_field")
    if not isinstance(layer, str) or not layer:
        raise request.invalid(f"falta la capa que se importa («layer»), no {layer!r}")
    if role not in LAYER_OUTPUTS:
        raise request.invalid(f"el papel de una capa es uno de {list(LAYER_OUTPUTS)}, no "
                              f"{role!r}")
    if field is not None and (not isinstance(field, str) or role != "contours"):
        raise request.invalid(f"el campo de cota ({field!r}) es de una capa de curvas de nivel")
    return layer, str(role), field


@_job
def run_import_vector(ctx: _Context) -> dict[str, Any]:
    """``gis_import_vector``: una capa de un GeoPackage (``gis.gpkg_layer@1``) con el papel
    que declara la persona (RF-006-12): el GeoPackage, copiado a ``in/`` con su ``-wal`` o su
    diario y leído sobre una copia consolidada (nunca el de la persona, RF-006-10), da los
    puntos, las líneas de rotura (duras), las curvas de nivel (con su cota), el contorno o los
    dominios (con sus atributos; spec 011, D-32) o las entidades (con sus atributos; spec 012,
    D-27) con las coordenadas de la capa bit a bit, el
    informe (entidades leídas, rechazadas con su
    número y motivo y, en puntos, duplicados), el hash de la fuente (RF-006-26) y el de la
    tabla que será lo importado (T50: :func:`_table_digests`; RNF-006-09). Su CRS, el de la
    petición o el de la capa; el datum, el de la petición (RF-006-04)."""
    from .provenance import layer_family  # importa la procedencia: solo al usarlo

    request = _Request(ctx)
    reader = _reader(request, (gis_content.GPKG_LAYER,))
    settings = _settings(request, reader)
    layer, role, field = _layer_settings(request, settings)
    name = request.name() or layer
    declared_crs = request.crs("crs", required=False)
    declared_vertical = request.vertical("vertical", required=False)
    ctx.progress(0.0, COPYING_TEXT)
    files, prints = _copy_sources(ctx, request, (MAIN_ROLE,), sqlite=True, low=0.0, high=0.1)
    ctx.progress(0.1, READING_TEXT)
    work = ctx.job_dir.path / LAYER_DIR
    try:
        features = read_layer(copy_source(files[MAIN_ROLE], work), layer)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    crs, vertical = Declaration(name, declared_crs or features.layer.declared_crs,
                                declared_vertical).require()
    declarations = _declarations(request, reader, crs, vertical, settings)
    digest = _source_digest(ctx, reader, "vector", files, declarations, settings, 0.3, 0.7)
    ctx.progress(0.7, READING_TEXT)
    output = LAYER_OUTPUTS[role]
    path = ctx.output_path(output.file)
    extra: dict[str, Any] = {}
    if role == "points":
        points, report = points_from_features(features)
        report = dataclasses.replace(report, duplicates=_duplicates(request, points))
        write_points(path, points)
        count = len(points)
        extra["duplicates"] = report.duplicates
    elif role == "breaklines":
        lines, report = breaklines_from_features(features, hard=True)
        write_lines(path, lines)
        count = len(lines)
    elif role == "contours":
        try:
            contours, report = contours_from_features(features, elevation_field=field)
        except ValueError as error:
            raise request.invalid(str(error)) from None
        write_contours(path, contours)
        count = len(contours)
    elif role == "domains":  # spec 011, T18 (D-32)
        domains, report = domains_from_features(features)
        write_domains(path, domains)
        count = len(domains)
    elif role == "features":  # spec 012, T07 (D-27)
        entities, report = features_from_layer(features)
        write_features(path, entities)
        count = len(entities)
        target_crs = request.crs("target_crs")
        extra["reprojects"] = target_crs is not None and target_crs.epsg != crs.epsg
    else:
        polygons, report = polygons_from_features(features)
        write_polygons(path, polygons)
        count = len(polygons)
    _write_report(ctx, report)
    hashed = count and not extra.get("reprojects")  # transformada, la hashea su registro
    digests = _table_digests(ctx, crs, [(output, layer_family(role))] if hashed else [],
                             0.75, 0.99)
    summary = {
        "source": _source_summary(reader, digest, prints, declarations, settings),
        "crs": crs_json(crs),
        "vertical": vertical_json(vertical),
        "layer": layer,
        "role": role,
        "read": report.read,
        "count": count,
        "rejected": len(report.rejected),
        **extra,
        "outputs": {item.role: {"file": item.relative,
                                **({"digest": digests[item.role]}
                                   if item.role in digests else {})}
                    for item in (output, OUT_REPORT)},
    }
    _finish(ctx, (output, OUT_REPORT))
    return summary


def _tin_meta(request: _Request, ctx: _Context, crs: CrsRef,
              vertical: VerticalRef) -> dict[str, Any]:
    """El ``meta`` de un TIN de ``meshes/`` (el EPSG, la referencia vertical y la operación
    de la petición, que tiene que llegar)."""
    operation_uid = ctx.request.operation_uid
    if not isinstance(operation_uid, str) or not operation_uid:
        raise request.invalid("el TIN necesita la operación que lo crea (operation_uid)")
    return {"crs_epsg": crs.epsg, "vertical": meta_vertical(vertical),
            "operation_uid": operation_uid}


def _tin_summary(tin: Tin, meta: Mapping[str, Any], **values: Any) -> dict[str, Any]:
    from ..core.datasets.model import DATASET_DECLARATIONS

    return {
        **values,
        "vertices": len(tin.vertices),
        "triangles": len(tin.faces),
        "outputs": {
            OUT_TIN.role: {"file": OUT_TIN.relative, "digest": digest_json(
                gis_content.tin_digest(tin, meta, DATASET_DECLARATIONS))}},
    }


@_job
def run_tin_contours(ctx: _Context) -> dict[str, Any]:
    """``gis_tin_contours``: el TIN de las curvas de nivel de ``in/lines.npz`` con los puntos
    acotados de ``in/points.npz`` y el contorno de ``in/regions.npz`` (si llegan) y la
    corrección de triángulos planos (``gis.tin_from_contours``, RF-006-16) con
    ``PureTriangulator`` (RF-006-13), en ``tin.npz`` con el ``meta`` de la operación de la
    petición y su hash, e informe; con conflictos (RF-006-14), solo ``conflicts.json``."""
    request = _Request(ctx)
    name = request.name()
    origin = request.parsed("origin", origin_of)
    crs, vertical = request.crs("crs"), request.vertical("vertical")
    meta = _tin_meta(request, ctx, crs, vertical)
    try:
        policy = DuplicatePolicy(request.text("duplicate_policy", DuplicatePolicy.ASK.value))
    except ValueError as error:
        raise request.invalid(str(error)) from None
    options = {"densify_m": request.number("densify_m"),
               "max_passes": request.integer("max_passes"),
               "max_flat_pct": request.number("max_flat_pct"),
               "tol_xy": request.number("tol_xy"), "tol_z": request.number("tol_z")}
    entries = ctx.request.inputs
    if INPUT_LINES not in entries:
        raise request.invalid("no hay curvas de nivel que triangular («lines»)")
    lines = read_lines(ctx.input_path(INPUT_LINES))
    spots = read_points(ctx.input_path(INPUT_POINTS)) if INPUT_POINTS in entries else None
    boundary = (read_regions(ctx.input_path(INPUT_REGIONS))[0]
                if INPUT_REGIONS in entries else None)
    triangulator = PureTriangulator(cancelled=_cancelled(ctx))
    try:
        tin, report = tin_from_contours(lines, spot_heights=spots, triangulator=triangulator,
                                        origin=origin, boundary=boundary,
                                        duplicate_policy=policy, name=name,
                                        progress=_span(ctx, 0.0, 0.9),
                                        cancelled=_cancelled(ctx), **options)
    except ConflictError as error:
        _write_conflicts(ctx.output_path(OUT_CONFLICTS.file), error)
        summary = {"conflicts": len(error.conflicts), "code": error.code, "text": error.text,
                   "outputs": {OUT_CONFLICTS.role: {"file": OUT_CONFLICTS.relative}}}
        _finish(ctx, (OUT_CONFLICTS,))
        return summary
    ctx.progress(0.9, WRITING_TEXT)
    save_tin(tin, ctx.output_path(OUT_TIN.file), meta)
    _write_report(ctx, report)
    summary = _tin_summary(tin, meta, conflicts=0, triangulator=triangulator.name)
    summary["outputs"][OUT_REPORT.role] = {"file": OUT_REPORT.relative}
    _finish(ctx, (OUT_TIN, OUT_REPORT))
    return summary


@_job
def run_convert_surface(ctx: _Context) -> dict[str, Any]:
    """``gis_convert_surface`` (RF-006-17): ``grid_to_tin``, la rejilla del proyecto de
    ``in/source.tif`` en un TIN de los centros de sus celdas con dato
    (``gis.tin.raster_to_tin``) en ``tin.npz``, con el ``meta`` de la operación de la petición;
    ``tin_to_grid``, el TIN de ``in/source.npz`` interpolado en los centros de la rejilla
    ``target`` (``gis.tin.tin_to_raster``; fuera del TIN, sin dato) en ``grid.tif``. Cada uno
    con el hash de su lector (RF-006-26)."""
    request = _Request(ctx)
    direction = request.text("direction", "")
    if direction not in DIRECTIONS:
        raise request.invalid(f"«direction» es una de {list(DIRECTIONS)}, no {direction!r}")
    name = request.name()
    crs, vertical = request.crs("crs"), request.vertical("vertical")
    cancelled = _cancelled(ctx)
    ctx.progress(0.0, READING_TEXT)
    surface = _surface(ctx, request, low=0.0, high=0.3)
    if direction == GRID_TO_TIN:
        if isinstance(surface, Tin):
            raise request.invalid("de rejilla a TIN, la fuente es una rejilla (.tif)")
        meta = _tin_meta(request, ctx, crs, vertical)
        tin = raster_to_tin(surface, name=name, progress=_span(ctx, 0.3, 0.85),
                            cancelled=cancelled)
        ctx.progress(0.85, WRITING_TEXT)
        save_tin(tin, ctx.output_path(OUT_TIN.file), meta)
        summary = _tin_summary(tin, meta, direction=direction, triangulator=tin.triangulator)
        _finish(ctx, (OUT_TIN,))
        return summary
    if not isinstance(surface, Tin):
        raise request.invalid("de TIN a rejilla, la fuente es un TIN (.npz)")
    target = request.parsed("target", grid_of)
    grid = tin_to_raster(surface, target, crs=crs, vertical=vertical,
                         progress=_span(ctx, 0.3, 0.85), cancelled=cancelled)
    ctx.progress(0.85, WRITING_TEXT)
    GeoTiffIO().write(grid, ctx.output_path(OUT_PROJECT_GRID.file), profile="project",
                      progress=_span(ctx, 0.85, 0.96), cancelled=cancelled)
    written = _dataset_digest_raster(ctx, grid, 0.96, 0.99)
    summary = {"direction": direction, "grid": grid_json(target), "cells": int(grid.values.size),
               "valid_cells": int(np.count_nonzero(np.isfinite(grid.values))),
               "outputs": {OUT_PROJECT_GRID.role: {
                   "file": OUT_PROJECT_GRID.relative,
                   "digest": digest_json(written)}}}
    _finish(ctx, (OUT_PROJECT_GRID,))
    return summary


# --- Los tipos de trabajo ------------------------------------------------------------------

_LABELS: Mapping[str, str] = MappingProxyType({
    READ_RASTER: "Read a raster DTM",
    RESAMPLE: "Resample a DTM",
    IMPORT_POINTS: "Read points and breaklines",
    TIN_PREPARE: "Prepare a TIN",
    TRIANGULATE: "Triangulate a TIN",
    TIN_FINISH: "Finish a TIN",
    CONTOURS: "Compute contour lines",
    VALIDATE: "Validate a surface",
    EXPORT: "Write a deliverable",
    VIEW_ARRAYS: "View meshes of a surface",
    IMPORT_VECTOR: "Read a vector layer",
    TIN_CONTOURS: "TIN from contour lines",
    CONVERT_SURFACE: "Convert a surface",
})
"""El nombre visible (``msgid``) de cada tipo; su español, en ``core/i18n/messages.toml``."""

WORKER_INFOS: tuple[WorkerInfo, ...] = (
    WorkerInfo(READ_RASTER, _LABELS[READ_RASTER], estimate_s=_read_estimate,
               run=run_read_raster),
    WorkerInfo(RESAMPLE, _LABELS[RESAMPLE], estimate_s=_resample_estimate, run=run_resample),
    WorkerInfo(IMPORT_POINTS, _LABELS[IMPORT_POINTS], estimate_s=_points_estimate,
               run=run_import_points),
    WorkerInfo(TIN_PREPARE, _LABELS[TIN_PREPARE], estimate_s=_count_estimate(TIN_POINT_S),
               run=run_tin_prepare),
    WorkerInfo(TRIANGULATE, _LABELS[TRIANGULATE], policy="subprocess",
               estimate_s=_count_estimate(PURE_POINT_S), run=run_triangulate),
    WorkerInfo(TIN_FINISH, _LABELS[TIN_FINISH], estimate_s=_count_estimate(TIN_POINT_S),
               run=run_tin_finish),
    WorkerInfo(CONTOURS, _LABELS[CONTOURS], estimate_s=_count_estimate(CELL_S + CONTOUR_CELL_S),
               run=run_contours),
    WorkerInfo(VALIDATE, _LABELS[VALIDATE], estimate_s=_count_estimate(CELL_S + VALIDATE_CELL_S),
               run=run_validate),
    WorkerInfo(EXPORT, _LABELS[EXPORT], estimate_s=_count_estimate(2 * CELL_S), run=run_export),
    WorkerInfo(VIEW_ARRAYS, _LABELS[VIEW_ARRAYS], estimate_s=_count_estimate(CELL_S + MESH_CELL_S),
               run=run_view_arrays),
    WorkerInfo(IMPORT_VECTOR, _LABELS[IMPORT_VECTOR], estimate_s=_vector_estimate,
               run=run_import_vector),
    WorkerInfo(TIN_CONTOURS, _LABELS[TIN_CONTOURS],
               estimate_s=_count_estimate(CONTOUR_PASSES * PURE_POINT_S + TIN_POINT_S),
               run=run_tin_contours),
    WorkerInfo(CONVERT_SURFACE, _LABELS[CONVERT_SURFACE],
               estimate_s=_count_estimate(CELL_S + MESH_CELL_S), run=run_convert_surface),
)
"""Los tipos de trabajo de la 006 (plan §5.3.4), para ``jobs.catalog.register_worker`` desde
``bl/ops/gis.py``: entorno ``blender``; automáticos salvo ``gis_triangulate`` (proceso
aparte); estimación por ``size`` (bytes de la fuente) o ``count`` (celdas o puntos)."""

WORKER_INFOS_BY_NAME: Mapping[str, WorkerInfo] = MappingProxyType(
    {info.name: info for info in WORKER_INFOS})
"""Los tipos de trabajo de la 006 por nombre (solo lectura)."""

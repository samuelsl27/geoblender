# SPDX-License-Identifier: GPL-3.0-or-later
"""La topografía en Blender (código ``gis``, spec 006; plan 006 §5.1, §5.3.4, §5.3.5, §5.5 y
§5.6; ADR-0025 §2).

Registra lo que la topografía declara a las specs 004 y 008:

- sus **definiciones de parámetros** (``gis.params.DEFINITIONS``) en ``core.params``, para el
  panel de parámetros y para que cada operación resuelva los del proyecto (RF-008-01,
  RF-008-06; plan §5.6.1; T26);
- sus **lectores de contenido** (``gis.content``) en ``core.content``, con el lector de tablas de
  texto de ``interop`` (``gis`` no puede importarlo, ARQ-07; RF-006-26, RF-008-09; T40): así la
  lista estática del trabajo ``core_content_hash`` (``workers/core_content_hash.py``) coincide con
  lo que registra Blender;
- sus **tipos de trabajo** (``gis.jobs.WORKER_INFOS``) en ``jobs.catalog`` con
  ``register_worker`` (RF-006-28; plan §5.3.4; T26): ``jobs/`` no importa ``gis``;
- (T28) el ``OperationDef`` de ``gis.import_dtm`` (sin recálculo: se reimporta) y el de
  ``gis.resample`` con su **recálculo** (:func:`recompute_resample`, RF-008-26), y los
  ``ImporterDef`` de ``gis.geotiff``, ``gis.asc`` y ``gis.xyz_grid`` con su **reimportación**
  (:func:`reimport_dtm`, RF-008-11; plan §5.6.3 y §5.6.8);
- (T29) los de ``gis.import_points`` y ``gis.import_vector`` (sin recálculo) y los de los TIN
  y las conversiones con el suyo, y los ``ImporterDef`` de ``gis.points_text`` y
  ``gis.gpkg_layer``; al quitarlo todo, también el temporizador de las triangulaciones;
- (T30) el de ``gis.contours`` con su recálculo, y (T31) los de ``gis.export_raster`` y
  ``gis.export_gpkg`` (no se repiten solas: sin recálculo).
- (spec 012, T21; RF-012-16) el de ``gis.compile_constraints`` (:data:`MASKS_OPERATION_DEF`, de la
  versión, con su recálculo :func:`recompute_compile` y la reproducción de ``gis.masks.store``) y
  sus diez cifras: «Recalcular lo obsoleto» empieza la compilación nueva con
  ``gis.masks.store.recompute_run`` y deja sus pasos en la cola de las máscaras
  (:data:`MASKS_RUNS`, :func:`queue_mask_steps`, su temporizador :func:`masks_tick`, que en
  ``blender -b`` no corre: las pruebas lo llaman a mano), con su avance en la barra de estado;
  unos pasos que fallan dejan la operación «fallida», los avisos de la compilación van al
  registro de Blender y desregistrar cierra lo que espera como Esc (lo que no empezó, «cancelado»).
  Sus órdenes (T23; RF-012-04, RF-012-06, RF-012-11, RF-012-20, RF-012-28): «Compilar las
  máscaras» (``geoblender.gis_compile_constraints``, :class:`GEOBLENDER_OT_gis_compile_constraints`:
  la puerta de la 008, los pasos de ``gis.masks.store.begin_compile_steps`` y ``compile_run`` en
  un modal con su avance y Esc, y el informe de ganado y perdido y de la búsqueda pendiente) y
  «Exportar las máscaras…» (``geoblender.gis_export_constraint_masks``: la rejilla de clases a
  GeoTIFF con su leyenda; no es una operación).

(T44) Las declaraciones de procedencia son constantes del módulo, construidas una vez:
:data:`OPERATION_DEFS` (los once tipos de ``gis.provenance.OPERATION_TYPES``, cada repetible con
su función de :data:`RECOMPUTE`, y cada uno con los ajustes de su orden que enseña su
procedencia, :data:`SETTING_DEFS`, T58) e :data:`IMPORTER_DEFS` (un importador por lector de
importación, con su función de :data:`REIMPORT`); registrar dos veces pone los mismos objetos.

:func:`register` pone lo que falta y apunta cómo quitarlo; :func:`unregister` quita solo eso, en
orden inverso: lo que otro registró antes con la misma clave, o puso después en su lugar, es
suyo y se queda (también una definición de parámetro de ``gis``). Los dos son simétricos e
idempotentes: registrar y desregistrar deja los registros de ``core`` como estaban (ADR-0025
§2).

**Las órdenes de un MDT** (T28; HU-006-1), operadores de la procedencia de la 008
(``ProvenanceAwareOperator``: la puerta ``ensure_ready``, ``begin_operation``, su trabajo de la
004 y ``ingest_job_result``; plan §5.6.4). Solo escriben en el proyecto (``{'REGISTER'}``):

- ``geoblender.gis_import_dtm`` (Topografía ▸ Importar ▸ MDT ráster…): un GeoTIFF, un ASC o un
  XYZ en malla a ``gis_src_<nombre>`` en su rejilla de origen, con su entrada (nombre lógico,
  fecha de entrega y quién entrega, opcionales; RF-006-08, RF-006-26). Antes de empezar,
  ``gis.dtm.plan_import`` comprueba el formato y la cabecera (RF-006-09) y exige el CRS
  horizontal y el datum vertical (el datum, «Sin declarar» hasta que la persona lo elige si el
  fichero no lo declara; RF-006-04); si difieren de los del proyecto, la transformación de
  precisión conocida o el rechazo nombrando los dos CRS (RF-006-05), que el informe dice. Su
  trabajo ``gis_read_raster`` lee la fuente por ``--path`` y, al terminar, la importación se
  clasifica (``classify_import``: reutilizar, sustituir o nueva; RF-008-54) y se compara con el
  MDT del proyecto (RF-006-06). (T54; RNF-006-09) Se incorpora **por pasos** desde el
  temporizador de las incorporaciones (:func:`incorporation_tick`, con su avance en la barra de
  estado): la comparación, con las posiciones que dejó su trabajo (``samples.npy``: el hilo de
  Blender no vuelve a leer la rejilla importada); la copia de su rejilla al proyecto con su
  huella, un trozo por paso, y la transacción corta del final (con el MDT de RNF-006-01, pasos
  de menos de 0,2 s en vez de una llamada de casi un segundo). Una sustitución sin motivo o un
  aviso de alturas elipsoidales **esperan la decisión de la persona** (:func:`waiting_imports`):
  la misma orden con ``pending`` (el uid de la operación), ``decision`` y, en una sustitución,
  ``reason`` la sigue (por pasos) o la cancela; mientras, el trabajo está «pendiente de
  incorporar». Con el fichero ya elegido y ``dialog`` (lo abre así «Importar un fichero…» de
  ``bl.ops.io``, T32), su diálogo. Se importa entero y su informe avisa (T51; spec §8) si sus
  celdas con dato salen de la ventana de trabajo (``gis.placement``; la rejilla del proyecto
  solo la cubre a ella) o si alguno de sus centros pasa de 8 km del GeoOrigin
  (``core.georef.precision_report``, RF-002-26).
- ``geoblender.gis_resample_to_grid`` (Topografía ▸ Superficies ▸ Rejilla de proyecto desde un
  MDT…): el MDT importado a ``gis_dtm_<nombre>`` en la rejilla del proyecto (la ventana de
  trabajo con el paso del proyecto, ``gis.grid.project_grid``), con el método en el informe
  (RF-006-11). La fracción mínima sale en el diálogo con el valor del proyecto, su insignia de
  tipo y «sin confirmar» si lo está (:func:`fraction_field`): sin cambiarla, se consume y se
  anota (RF-008-05); tecleada otra, es un ajuste de la orden y no cambia el parámetro (D18). Con otro CRS u otra
  referencia vertical, su trabajo reproyecta en proceso aparte con las ruedas de la extensión
  (``site_override``, :func:`wheels_site`; D11).

**Puntos, capas y TIN** (T29; HU-006-2, HU-006-5; RF-006-12 a RF-006-17, RF-006-27):

- ``geoblender.gis_import_points`` (Importar ▸ Puntos y líneas de rotura…): un CSV, TXT o XYZ
  disperso con su asistente (codificación, separador, decimal, cabecera y el papel de cada
  columna, ``GEOBLENDER_PG_gis_column``; sin él, adivinado por la cabecera) a ``gis_pts_`` y
  ``gis_brk_`` con su entrada y su original (trabajo ``gis_import_points``); el informe dice las
  filas leídas, las rechazadas (número y motivo) y los duplicados. (T50; RNF-006-09) El hash de
  las tablas de lo importado lo calcula su trabajo (con su avance y su cancelación) y, al
  terminar, la importación se incorpora **por pasos** desde un temporizador
  (:func:`incorporation_tick`, :func:`pending_incorporations`): leer lo que dejó el trabajo,
  codificar sus filas, la transacción corta del final y el original por trozos, cada paso de
  unas décimas de segundo como mucho y con su avance en la barra de estado («Incorporando «…» al
  proyecto… n %»); con 300.000 puntos, en vez de una llamada de 5 s.
- ``geoblender.gis_import_vector`` (Importar ▸ Capas vectoriales…): una capa de un GeoPackage
  (listada sobre una copia en ``cache/import/``) con su papel (puntos, roturas, curvas con su
  campo de cota o contorno; trabajo ``gis_import_vector``, que copia la fuente con su ``-wal``).
  Lo mismo que los de un MDT: la entrega, ``classify_import`` (reutilizar: cancelada con el
  aviso; sustituir sin motivo: cancelada pidiéndolo) y su reimportación
  (:func:`reimport_survey`).
- ``geoblender.gis_create_tin_from_points`` y ``…_from_contours``: una operación con una cadena
  de trabajos; desde puntos, ``gis_tin_prepare`` → la CDT de Blender en el hilo principal
  desde un temporizador (:func:`triangulation_tick`; avisada antes en la barra de estado si se
  estima en más de 1 s) solo si su estimación no pasa de ``gis.tin.blender_cdt_max_s`` (de
  control, D17), y si pasa, ``gis_triangulate`` → ``gis_tin_finish``, que se incorpora con el
  triangulador en ``software``; desde curvas, ``gis_tin_contours`` (``PureTriangulator``: la
  corrección de triángulos planos triangula varias veces). Lo que consumen se lee del proyecto
  y, si está en otro CRS, se transforma con una de precisión conocida (RF-006-05). Los
  conflictos sin resolver quedan en los avisos con su posición y sus cotas y la operación,
  fallida o cancelada con su motivo, sin TIN (RF-006-14). Con su recálculo
  (:func:`recompute_tin`).
- ``geoblender.gis_convert_dtm_tin`` (MDT ⇄ TIN…): ``gis.grid_to_tin`` o ``gis.tin_to_grid``
  con ``gis_convert_surface`` (RF-006-17), con su recálculo (:func:`recompute_convert`).

**Exportar** (T31; HU-006-6; RF-006-24, RF-006-25; plan §5.6.6, D21):
``geoblender.gis_export_raster`` (Exportar ▸ Superficie o rejilla a GeoTIFF…: el MDT importado o
la rejilla del proyecto, el GeoTIFF float32 con −9999 de T07) y ``geoblender.gis_export_gpkg``
(Capas a GeoPackage…: puntos, líneas de rotura, TIN como triángulos, curvas y contornos, con
``GEOBLENDER_PG_gis_export_item``), operaciones ``gis.export_raster`` y ``gis.export_gpkg`` que
consumen lo exportado (papel ``exported``) con su trabajo ``gis_export``. Antes de empezar y
otra vez antes de escribir, la guarda de las escrituras de la 008 (``check_write_target`` con
``read_only_dirs()``: la fuente de una entrada, su carpeta y las de solo lectura, RF-008-15);
ni otra carpeta del proyecto que ``exports/`` ni otra extensión. Un destino que ya existe no se
sustituye sin confirmarlo (desde la interfaz, una confirmación; desde un guion, ``overwrite``);
abierto por otro programa, la operación falla con el anterior intacto. Dentro de ``exports/``
el entregable es el dato ``exports`` ``gis_exp_<ruta>`` con su hash; fuera, ninguno, y los
ajustes llevan el nombre del fichero, nunca su ruta.

Sin proyecto, ``poll`` dice el paso previo («Primero abra un proyecto (Proyecto ▸ … ▸ Abrir
proyecto…)», con su ruta en la barra); sin la procedencia o en solo lectura (también dentro de
una carpeta de solo lectura), su motivo (:func:`unavailable_reason`). El servicio de CRS de las
órdenes es el del registro de adaptadores (:data:`crs_resolver`, que las pruebas cambian). El
informe de cada orden queda como mensaje de su operación y en los avisos de la sesión.
"""

from __future__ import annotations

import datetime as dt
import functools
import json
import logging
import math
import re
import shutil
import sqlite3
import sys
import unicodedata
import uuid
from collections.abc import Callable, Generator, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import bpy
import numpy as np
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, StringProperty

from ...core import i18n
from ...core import params as core_params
from ...core.catalog.search import path_text
from ...core.content import readers as content_readers
from ...core.content.readers import MAIN_ROLE
from ...core.datasets import registry as dataset_registry
from ...core.errors import GeoblenderError
from ...core.georef import load_catalog, world_to_local
from ...core.i18n import format_number, tr
from ...core.inputs import get as get_input
from ...core.inputs import locate_source, reader_roles, resolve_source
from ...core.inputs.model import SourcePrint
from ...core.inputs.registry import Reuse, Substitute
from ...core.numbers import parse_decimal
from ...core.provenance import contract
from ...core.provenance.messages import ProvenanceError
from ...core.project.model import Progress
from ...core.provenance.operations import Use, begin_operation, failure_reason, ingest_job
from ...core.provenance.undo import UndoKind
from ...core.units import DIMENSIONLESS
from ...gis import content, jobs, provenance, store, vector
from ...gis import params as gis_params
from ...gis.crs import (
    ELLIPSOIDAL_ETRS89,
    VERTICAL_FIELD,
    Declaration,
    crs_library,
    needs_transform,
    reference_label,
    require_crs_service,
    transform_summary,
    transformation_for,
)
from ...gis.dtm import (
    CONTROL_KEYS,
    MAX_CELLS_KEY,
    DtmSource,
    control_values,
    dtm_reader,
    identify_prj,
    job_params,
    job_paths,
    parse_crs,
    plan_import,
    read_settings,
    scene_origin,
)
from ...gis.contours import (
    INDEX_EVERY_KEY,
    INDEX_OFFSET_KEY,
    INTERVAL_KEY,
    MIN_LENGTH_KEY,
    SIMPLIFY_KEY,
    ContourLine,
)
from ...gis.grid import Grid, project_grid
from ...gis.masks import provenance as masks_provenance
from ...gis.masks import store as masks_store
from ...gis.messages import GisError
from ...gis.placement import extent_in, outside_window
from ...gis.points import DUP_XY_KEY, DUP_Z_KEY, Breakline, PointSet
from ...gis.ports import TriangulationError
from ...gis.reports import SurfaceReport
from ...gis.tin_contours import DENSIFY_KEY, MAX_FLAT_KEY, PASSES_KEY
from ...gis.validate import SURFACE_GRID, Z_RANGE_KEY
from ...gis.vertical import BAND_KEY, check_vertical_offset
from ...interop.csv_tables import preview_table, read_table
from ...jobs import catalog as job_catalog
from ...jobs.ingest import job_outcome
from ...jobs.protocol import new_request
from ..props.core import OBJECT_PROPERTY, GEOBLENDER_PG_core_view_dataset
from ..props.gis import (
    COLUMN_ROLES,
    NOT_IMPORTED,
    GEOBLENDER_PG_gis_column,
    GEOBLENDER_PG_gis_export_item,
)
from ..scene import project_session, undo_watch
from ..scene import versions as scene_versions
from ..scene import triangulator as cdt_blender
from ..ui import constraint_panels
from ..ui.commands import catalog as command_catalog
from ..ui.commands import command_idname
from ..ui.provenance import badge
from ..ui.views import no_work_window_message
from . import core_provenance, incorporation
from .core import _StepsModal
from . import jobs as jobs_ops
from .core_provenance import ProvenanceAwareOperator, error_text, write_unavailable

if TYPE_CHECKING:
    from ...core.datasets.model import DatasetRecord
    from ...core.georef import CrsRef, VerticalRef
    from ...core.provenance.contract import ReimportRequest
    from ...core.provenance.operations import OperationHandle
    from ...core.provenance.recompute import RecomputeRequest
    from ...gis.ports import CrsService, Transform
    from ...gis.vertical import VerticalCheck
    from ...jobs.runner import JobResult

LOGGER = logging.getLogger("geoblender.bl.ops")
TRANSLATION_CONTEXT = "Geoblender"
MODULE = "gis"
"""El módulo de las definiciones de parámetros de la topografía."""

IMPORT_DTM = "geoblender.gis_import_dtm"
RESAMPLE_TO_GRID = "geoblender.gis_resample_to_grid"
OPEN_PROJECT = "geoblender.core_open_project"
DIALOG_WIDTH = 520
QUESTION_CHARS = 80
FRACTION_KEY = "gis.resample.min_valid_fraction"
SUPERSAMPLE_KEY = "gis.reproject.supersample"
DTM_IMPORTERS: tuple[str, ...] = ("gis.geotiff", "gis.asc", "gis.xyz_grid")
"""Los lectores (sin versión) cuya reimportación registra esta orden (plan §5.6.8)."""
_SUCCEEDED = "succeeded"  # el final de un trabajo que terminó bien (jobs.records)
_DTM_SOURCE_READERS = {reader.id: reader for reader in (content.GEOTIFF, content.ASC,
                                                         content.XYZ_GRID)}

crs_resolver: Callable[[], CrsService] | None = None
"""El servicio de CRS de las órdenes (``None``: el del registro de adaptadores, pyproj con su
versión comprobada); las pruebas ponen uno de prueba."""

UNDECLARED = "UNDECLARED"
PROJECT_VERTICAL = "PROJECT"
ELLIPSOIDAL = "ELLIPSOIDAL"
VERTICAL_ITEMS = [
    (UNDECLARED, "Undeclared", "The file's if it declares one; if not, declare it"),
    (PROJECT_VERTICAL, "The project's", ""),
    (ELLIPSOIDAL, "ETRS89 ellipsoidal height", "GNSS or drone without geoid"),
]
VERTICAL_ITEMS += [(f"EPSG:{ref.epsg}", f"EPSG:{ref.epsg} · {ref.name}", ref.name)
                   for ref in load_catalog().verticals() if ref.epsg is not None]
SEPARATOR_ITEMS = [
    ("AUTO", "Automatic", "Detected in the first data line"),
    ("SPACE", "Space", ""),
    ("TAB", "Tab", ""),
    ("COMMA", "Comma", ""),
    ("SEMICOLON", "Semicolon", ""),
]
SEPARATORS: Mapping[str, str | None] = {"AUTO": None, "SPACE": " ", "TAB": "\t", "COMMA": ",",
                                        "SEMICOLON": ";"}
DECIMAL_ITEMS = [("POINT", "Point", ""), ("COMMA", "Comma", "")]
DECIMALS: Mapping[str, str] = {"POINT": ".", "COMMA": ","}
METHOD_ITEMS = [
    ("AUTO", "Automatic", "Area-weighted mean if the DTM cells are not larger than the "
                          "project's; bilinear if they are"),
    ("AREA_MEAN", "Area-weighted mean", ""),
    ("BILINEAR", "Bilinear interpolation", ""),
]
METHODS: Mapping[str, str] = {"AUTO": "auto", "AREA_MEAN": "area_mean", "BILINEAR": "bilinear"}
DECISION_ITEMS = [
    ("CONTINUE", "Continue the import", ""),
    ("CANCEL", "Cancel the import", ""),
]
_SUBSTITUTE = "substitute"  # lo que espera una importación: el motivo de una sustitución…
_CONFIRM = "confirm"  # …o la confirmación del aviso de alturas elipsoidales
_ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")

_UNDO: list[Callable[[], None]] = []


# --- Registro --------------------------------------------------------------------------------


def register() -> None:
    """Registra las definiciones de parámetros, el lector de tablas, los lectores de contenido,
    los tipos de trabajo y las declaraciones de procedencia (:data:`OPERATION_DEFS`,
    :data:`IMPORTER_DEFS`) de ``gis`` que aún no están; idempotente."""
    missing = tuple(defn for defn in gis_params.DEFINITIONS
                    if defn.key not in core_params.DEFINITIONS)
    if missing:
        core_params.register_definitions(missing)
        _UNDO.append(functools.partial(_unregister_definitions, missing))
    if content.table_reader() is None:
        content.use_table_reader(read_table)
        _UNDO.append(_forget_table_reader)
    for reader in content.CONTENT_READERS:
        if reader.id not in content_readers.READERS:
            content_readers.register_reader(reader)
            _UNDO.append(_unregister_if(content_readers.READERS, reader.id, reader,
                                        content_readers.unregister_reader))
    for info in jobs.WORKER_INFOS:
        if info.name not in job_catalog.WORKERS:
            job_catalog.register_worker(info)
            _UNDO.append(_unregister_if(job_catalog.WORKERS, info.name, info,
                                        job_catalog.unregister_worker))
    for definition in (*OPERATION_DEFS, MASKS_OPERATION_DEF):
        if definition.op_type not in contract.OPERATIONS:
            contract.register_operation(definition)
            _UNDO.append(_unregister_if(contract.OPERATIONS, definition.op_type, definition,
                                        contract.unregister_operation))
    for figure in masks_provenance.FIGURES:
        if figure.key not in contract.FIGURES:
            contract.register_figure(figure)
            _UNDO.append(_unregister_if(contract.FIGURES, figure.key, figure,
                                        contract.unregister_figure))
    for importer in IMPORTER_DEFS:
        if importer.reader_id not in contract.IMPORTERS:
            contract.register_importer(importer)
            _UNDO.append(_unregister_if(contract.IMPORTERS, importer.reader_id, importer,
                                        contract.unregister_importer))


def unregister() -> None:
    """Quita lo que puso :func:`register`, en orden inverso (lo que otro cambió después es
    suyo), y olvida las importaciones que esperaban una decisión; idempotente."""
    _WAITING.clear()
    _TRIANGULATIONS.clear()
    MASKS_RUNS.drop()
    if bpy.app.timers.is_registered(triangulation_tick):
        bpy.app.timers.unregister(triangulation_tick)
    _drop_incorporations()
    while _UNDO:
        _UNDO.pop()()


def _unregister_if(view: Any, key: str, item: object,
                   remove: Callable[[str], object]) -> Callable[[], None]:
    def undo() -> None:
        if view.get(key) is item:  # si otro lo cambió, es suyo
            remove(key)

    return undo


def _unregister_definitions(ours: tuple[core_params.ParamDef, ...]) -> None:
    """Quita las definiciones que puso :func:`register` (``ours``) y deja las demás de
    ``gis``: las que otro registró antes con su clave o puso después en su lugar son suyas.
    ``core.params`` solo las quita por módulo: se quitan todas y se vuelven a poner las de
    otro, los mismos objetos."""
    mine = {id(defn) for defn in ours}
    others = [defn for defn in core_params.DEFINITIONS.values()
              if defn.module == MODULE and id(defn) not in mine]
    core_params.unregister_definitions(MODULE)
    if others:
        core_params.register_definitions(others)


def _forget_table_reader() -> None:
    if content.table_reader() is read_table:
        content.use_table_reader(None)


# --- Ayudas -----------------------------------------------------------------------------------


def wheels_site() -> Path | None:
    """La carpeta donde Blender instala las ruedas de las extensiones
    (``<extensiones>/.local/lib/pythonX.Y/site-packages``: pyproj), el ``--site`` de una
    reproyección en proceso aparte (D11; plan 004 §5.3.3), si existe; si no, ``None``."""
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    folder = bpy.utils.user_resource("EXTENSIONS", path=f".local/lib/{version}/site-packages")
    found = Path(folder) if folder else None
    return found if found is not None and found.is_dir() else None


def open_reason() -> str | None:
    """Sin proyecto abierto, el paso previo de una orden de la topografía («Primero abra un
    proyecto (Proyecto ▸ … ▸ Abrir proyecto…)»); con él, ``None``. Basta para las que no
    escriben en el proyecto (validar una superficie, T30)."""
    if project_session.current() is None:
        path = path_text(command_catalog(), OPEN_PROJECT, i18n.language())
        return tr("First {step} ({path})", step=tr("open a project"), path=path)
    return None


def unavailable_reason() -> str | None:
    """Por qué no se puede lanzar ahora una orden de un MDT (su ``poll``), en el idioma de
    Geoblender: sin proyecto, el paso previo (:func:`open_reason`); sin la procedencia o en
    solo lectura, su motivo (``core_provenance.write_unavailable``); si se puede, ``None``."""
    return open_reason() or write_unavailable()


def _poll(cls: type) -> bool:
    reason = unavailable_reason()
    if reason is not None:
        cls.poll_message_set(reason)  # type: ignore[attr-defined]
        return False
    return True


def _say(text: str) -> None:
    """Lo que dice una orden al terminar su trabajo: en los avisos de la sesión (el panel del
    proyecto y el registro técnico)."""
    project_session.notify(text)


def _decimal(value: float) -> str:
    """Un número con los decimales que necesita (hasta 6), en el formato del idioma."""
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    decimals = len(text.partition(".")[2])
    return format_number(float(value), decimals)


def _wrapped(text: str) -> list[str]:
    """``text`` en líneas de :data:`QUESTION_CHARS` caracteres como mucho, para un diálogo."""
    lines: list[str] = []
    for paragraph in text.splitlines():
        line = ""
        for word in paragraph.split():
            if line and len(line) + 1 + len(word) > QUESTION_CHARS:
                lines.append(line)
                line = word
            else:
                line = f"{line} {word}" if line else word
        lines.append(line)
    return lines


class _DateText(ValueError):
    """Una fecha de entrega tecleada que no es un día."""


def _delivery_day(typed: str) -> dt.date | None:
    """La fecha de entrega tecleada: un día DD/MM/AAAA (o, desde un guion, AAAA-MM-DD); vacía,
    sin fecha. :class:`_DateText` si no es un día."""
    shown = typed.strip()
    if not shown:
        return None
    try:
        return dt.datetime.strptime(shown, "%d/%m/%Y").date()
    except ValueError:
        pass
    if _ISO_DAY.fullmatch(shown):
        try:
            return dt.date.fromisoformat(shown)
        except ValueError:
            pass
    raise _DateText(shown)


def _transform(project: Any, source: DtmSource) -> Transform | None:
    """La transformación de lo que declara ``source`` al CRS y la referencia vertical del
    proyecto, o ``None`` si son los mismos; ``GisError`` sin una de precisión conocida
    (RF-006-05) o sin servicio de CRS (RF-006-31)."""
    crs, vertical = store.project_references(project)
    return transformation_for(Declaration(source.name, source.crs, source.vertical), crs,
                              vertical, resolver=crs_resolver)


def _identify(wkt: str) -> CrsRef | None:
    """El CRS del catálogo que declara el ``.prj`` de un ASC, si el servicio de CRS lo
    reconoce; sin servicio, ninguno (se pide declararlo, RF-006-04)."""
    try:
        return require_crs_service(crs_resolver).identify_wkt(wkt)
    except GisError:
        LOGGER.info("Sin servicio de CRS: el .prj no se reconoce", exc_info=True)
        return None


def _vertical_choice(choice: str, project: Any) -> VerticalRef | None:
    """La referencia vertical elegida en el diálogo (``None``: «Sin declarar»)."""
    if choice == UNDECLARED:
        return None
    if choice == PROJECT_VERTICAL:
        return store.project_references(project)[1]
    if choice == ELLIPSOIDAL:
        return ELLIPSOIDAL_ETRS89
    return load_catalog().vertical(int(choice.removeprefix("EPSG:")))


def _file_of(project: Any, record: DatasetRecord) -> Path:
    """El fichero del dato ``record`` en el proyecto; ``gis.dataset_file_missing`` si falta."""
    path = Path(project.root, *record.locator.split("/"))
    if not path.is_file():
        raise GisError("gis.dataset_file_missing", obj=f"Dato de topografía «{record.name}»",
                       field="ubicación", value=record.locator, file=path.name,
                       name=record.name)
    return path


def _failure(handle: OperationHandle, result: JobResult, error: BaseException) -> str:
    """Deja fallida con su motivo la operación ``handle`` cuyo trabajo terminó bien y no se
    pudo incorporar (si sigue «en curso»), da su trabajo por incorporado y devuelve el
    motivo."""
    text = error_text(error)
    LOGGER.warning("La operación «%s» (%s) no se incorporó", handle.op_type, handle.uid,
                   exc_info=error)
    try:
        handle.fail(text)
    except (GeoblenderError, TypeError, ValueError):
        pass  # ya terminó (la dejó así la escritura) o el proyecto no se puede escribir
    core_provenance.release_job(result.job_uid)
    return text


# --- Importar un MDT -------------------------------------------------------------------------


@dataclass(eq=False)
class _Import:
    """Una importación de un MDT en marcha: su operación, lo que se importa, la transformación
    al proyecto, los parámetros de control, la entrega, la entrada a la que sustituye y el
    motivo, el final de su trabajo, la comparación con el MDT del proyecto y lo que espera."""

    handle: OperationHandle
    source: DtmSource
    transform: Transform | None
    control: Mapping[str, Any]
    received_at: Any = None
    received_from: str | None = None
    previous_uid: str | None = None
    reason: str | None = None
    result: JobResult | None = None
    check: VerticalCheck | None = None
    checked: bool = False
    confirmed: bool = False
    kind: str | None = None
    question: str = ""
    failure: str = ""


_WAITING: dict[str, _Import] = {}


def waiting_imports() -> dict[str, str]:
    """Las importaciones que esperan la decisión de la persona: el uid de su operación y la
    pregunta."""
    return {uid: plan.question for uid, plan in _WAITING.items()}


def _import_settings(source: DtmSource, control: Mapping[str, Any]) -> dict[str, Any]:
    """Los ajustes de la operación de una importación: el nombre lógico, el fichero (sin su
    ruta), el lector, los ajustes de lectura, los CRS declarados y los parámetros de control
    con su valor (D17)."""
    return {"name": source.name, "file": source.main.name, "reader": source.reader.id,
            "read": dict(source.settings), "crs": jobs.crs_json(source.crs),
            "vertical": jobs.vertical_json(source.vertical), "control": dict(control)}


def _start_import(plan: _Import, launch: Callable[..., Any]) -> Any:
    """Lanza el trabajo ``gis_read_raster`` de ``plan`` con ``launch`` (``launch_job`` de la
    procedencia o el del operador); al terminar, :func:`_import_finished`."""
    source = plan.source
    project = plan.handle.project
    origin = scene_origin(source, store.project_references(project)[0], project.origin)
    return launch(plan.handle, jobs.READ_RASTER,
                  label=tr("Import of the DTM «{name}»", name=source.name),
                  params=job_params(source, max_cells=plan.control[MAX_CELLS_KEY],
                                    origin=origin),
                  paths=job_paths(source), on_finish=functools.partial(_import_finished, plan),
                  grace_s=jobs.CANCEL_GRACE_S)


def _import_finished(plan: _Import, result: JobResult) -> None:
    """El final del trabajo de una importación: si terminó bien, su incorporación por pasos
    desde el temporizador (:func:`_import_steps`, :func:`incorporation_tick`; T54,
    RNF-006-09); si no, la procedencia la deja cancelada o fallida con el motivo de la 004."""
    if result.state != _SUCCEEDED:
        return
    plan.result = result
    _incorporate(plan.handle.uid, plan.source.name, _import_steps(plan))


def _input_spec(plan: _Import, summary: Mapping[str, Any]) -> Any:
    """La entrada de la importación con lo que trae el resumen de su trabajo: el
    ``ContentDigest`` de la fuente y las huellas de sus ficheros (RF-008-07)."""
    project = plan.handle.project
    source = plan.source
    found = summary["source"]
    roles = list(source.files)
    anchors = [locate_source(source.files[role], project, project.userdata,
                             role="main" if role == MAIN_ROLE else "sidecar")
               for role in roles]
    prints = [SourcePrint(found["files"][role]["sha256"], size=found["files"][role]["size"],
                          mtime_ns=found["files"][role]["mtime_ns"]) for role in roles]
    return store.source_input(found["reader"], source.name, files=anchors, file_prints=prints,
                              digest=jobs.digest_of(found["digest"]), crs=source.crs,
                              vertical=source.vertical, settings=dict(source.settings),
                              received_at=plan.received_at, received_from=plan.received_from)


COPY_SHARE = (0.2, 0.9)
"""El tramo del avance de la incorporación de un MDT que es la copia de su rejilla al proyecto
(T54): antes, lo que dejó el trabajo, su clasificación y la comparación de cotas; después, la
transacción corta del final."""


def _import_steps(plan: _Import) -> Generator[float, None, str]:
    """Los pasos que incorporan la importación de ``plan`` (su trabajo ya terminó bien), con su
    avance (0–1) tras cada uno; cada paso, unas décimas de segundo del hilo de Blender como
    mucho (T54; RNF-006-09, RF-006-28; como los de los puntos, :func:`_survey_steps`): lo que
    dejó el trabajo y su clasificación; la comparación de cotas con la rejilla del proyecto
    (:func:`_vertical_check_steps`, con las posiciones que dejó el trabajo: el hilo de Blender
    no vuelve a leer la rejilla importada); la entrada declarada; la copia de la rejilla al
    proyecto con su huella, un trozo por paso (``ResultWriter.copy_file_steps``), y la
    transacción corta del final (``ingest_job_result``). Devuelve (``StopIteration.value``)
    cómo quedó: ``"reused"`` (la misma entrada con los mismos ajustes: cancelada con el aviso,
    RF-008-54), ``"waiting"`` (una sustitución sin motivo o el aviso de alturas elipsoidales:
    espera la decisión de la persona, RF-008-11, RF-006-06; la orden con ``pending`` la sigue
    con otros pasos), ``"done"`` (incorporada) o ``"failed"`` (fallida con su motivo, sin
    nada escrito). Cerrar los pasos antes de la transacción (al desregistrar) borra lo copiado
    y no escribe nada: la operación sigue «en curso» y queda «interrumpida» al abrir el
    proyecto."""
    result = plan.result
    assert result is not None
    project = plan.handle.project
    language = i18n.language()
    out: store.ResultWriter | None = None
    try:
        outcome = job_outcome(result, result.job_dir)
        spec = _input_spec(plan, outcome.summary)
        if plan.previous_uid is None:
            found = store.classify_source(project, spec)
            if isinstance(found, Reuse):
                with store.ResultWriter(project, plan.handle) as reused:
                    reused.declare_input(spec)  # la deja cancelada con el aviso
                core_provenance.release_job(result.job_uid)
                _say(found.render(language))
                return "reused"
            if isinstance(found, Substitute):
                if not plan.reason:
                    return _ask(plan, _SUBSTITUTE, tr(
                        "«{name}» has the same data as the input «{existing}» with other "
                        "settings ({differences}): write why it replaces it",
                        name=plan.source.name, existing=found.input.name,
                        differences=found.describe(language)))
                plan.previous_uid = found.input.uid
        yield 0.05
        if not plan.checked:
            plan.check = yield from _vertical_check_steps(plan, outcome)
            plan.checked = True
        if plan.check is not None and plan.check.warn and not plan.confirmed:
            return _ask(plan, _CONFIRM, plan.check.message(language) or "")
        report = _import_report(plan, outcome.summary)
        out = store.ResultWriter(project, plan.handle)
        out.declare_input(spec, previous_uid=plan.previous_uid, reason=plan.reason)
        low, high = COPY_SHARE
        yield low
        role = jobs.OUT_SOURCE_GRID.role
        copying = out.copy_file_steps(
            provenance.SOURCE_GRID, plan.source.name, outcome.file(role),
            content=jobs.digest_of(outcome.summary["outputs"][role]["digest"]),
            sha256=outcome.output(role).sha256)
        try:
            for done in copying:
                yield low + (high - low) * done
        finally:
            copying.close()  # a mitad, borra su temporal antes de deshacer lo demás
        core_provenance.ingest_job_result(plan.handle, result, out.write, message=report)
        out.close()
    except GeneratorExit:
        if out is not None:
            out.close()  # sin escribir nada: borra lo copiado; la operación sigue «en curso»
        raise
    except Exception as error:  # noqa: BLE001 - la operación queda fallida con el motivo
        if out is not None:
            out.close(error)
        plan.failure = tr("«{name}» has not been imported: {reason}", name=plan.source.name,
                          reason=_failure(plan.handle, result, error))
        _say(plan.failure)
        return "failed"
    _say(report)
    return "done"


def _ask(plan: _Import, kind: str, question: str) -> str:
    """Deja la importación esperando la decisión de la persona (``kind``: el motivo de una
    sustitución o la confirmación de un aviso), lo dice y abre su diálogo."""
    plan.kind, plan.question = kind, question
    _WAITING[plan.handle.uid] = plan
    _say(question)
    _open_decision(plan.handle.uid)
    return "waiting"


def _open_decision(uid: str) -> None:
    """Abre el diálogo de la importación ``uid`` que espera (la orden con ``pending``): sin
    ventana o sin interfaz, solo queda el aviso y la persona la sigue desde la orden."""
    manager = getattr(bpy.context, "window_manager", None)
    windows = list(getattr(manager, "windows", ()) or ())
    if not windows:
        return
    try:
        with bpy.context.temp_override(window=windows[0]):
            bpy.ops.geoblender.gis_import_dtm("INVOKE_DEFAULT", pending=uid)
    except (RuntimeError, TypeError, AttributeError):
        LOGGER.warning("No se pudo abrir el diálogo de la importación %s", uid, exc_info=True)


def _vertical_check_steps(plan: _Import,
                          outcome: Any) -> Generator[float, None, VerticalCheck | None]:
    """La comparación de las cotas importadas con la primera rejilla del proyecto vigente que
    tiene posiciones comunes (RF-006-06, A16), en el CRS y la referencia del proyecto (con la
    transformación de la importación) y con la banda del proyecto; sin rejilla del proyecto,
    ``None``. Las posiciones (``gis.dtm.vertical_samples``) las dejó el trabajo en
    ``samples.npy`` (T54; RNF-006-09: el hilo de Blender no vuelve a leer la rejilla
    importada); cada rejilla del proyecto se lee en su paso."""
    project = plan.handle.project
    references = [record for record in store.list_gis_datasets(
        project, families=(provenance.PROJECT_GRID,)) if str(record.status) == "current"]
    if not references:
        return None
    xyz = jobs.read_samples(outcome.file(jobs.OUT_SAMPLES.role))
    if plan.transform is not None:
        xyz = plan.transform.apply(xyz)
    for record in references:
        yield 0.1
        try:
            reference = store.load_raster(project, record)
        except GeoblenderError:  # su fichero falta o no se lee: se compara con otra
            LOGGER.info("Sin la rejilla «%s» para comparar las cotas", record.name,
                        exc_info=True)
            continue
        check = check_vertical_offset(xyz, reference, band_m=plan.control.get(BAND_KEY),
                                      name=record.name)
        if check.median_m is not None:
            return check
    return None


def _import_report(plan: _Import, summary: Mapping[str, Any]) -> str:
    """El informe de una importación: la rejilla de origen, la transformación al proyecto (si
    hay), la comparación con el MDT del proyecto (si se hizo) y las notas de la fuente."""
    grid = jobs.grid_of(summary["grid"])
    language = i18n.language()
    lines = [tr("Raster DTM «{name}» imported as {dataset}: {cols} × {rows} cells of {dx} × "
                "{dy} m, {valid} with data; {encoding}", name=plan.source.name,
                dataset=provenance.dataset_name(provenance.SOURCE_GRID, plan.source.name),
                cols=grid.ncols, rows=grid.nrows, dx=_decimal(grid.dx), dy=_decimal(grid.dy),
                valid=format_number(int(summary["valid_cells"]), 0),
                encoding=summary["encoding"])]
    if plan.transform is not None:
        crs, vertical = store.project_references(plan.handle.project)
        lines.append(tr("To bring it to the project grid it will be transformed from {source} "
                        "to {target}: {transform}",
                        source=reference_label(plan.source.crs, plan.source.vertical),
                        target=reference_label(crs, vertical),
                        transform=transform_summary(plan.transform.info)))
    check = plan.check
    if check is not None and check.median_m is not None:
        if check.warn:
            lines.append(tr("Confirmed by the user: {warning}",
                            warning=check.message(language) or ""))
        else:
            lines.append(tr("Median difference with the DTM «{dtm}»: {median} m at {samples} "
                            "positions", dtm=check.reference,
                            median=format_number(check.median_m, 1),
                            samples=format_number(check.samples, 0)))
    lines.extend(_placement_notes(plan, summary))
    lines.extend(str(note) for note in summary.get("notes", ()))
    return "\n".join(lines)


def _placement_notes(plan: _Import, summary: Mapping[str, Any]) -> list[str]:
    """Los avisos de dónde caen las celdas con dato del MDT importado (T51; spec §8, «MDT que
    sale de la ventana de trabajo o a más de 8 km del GeoOrigin»): si su extensión (en el CRS
    del proyecto, transformada si hace falta) sale de la ventana de trabajo, que se importa
    entero y la rejilla del proyecto solo cubre la ventana (RF-006-08, RF-006-11); y si algún
    centro pasa de 8 000 m del GeoOrigin, el aviso de ``core.georef.precision_report``
    (RF-002-26) que trae el resumen de su trabajo."""
    notes: list[str] = []
    name = plan.source.name
    window = plan.handle.project.window
    found = summary.get("data_extent")
    extent = None if found is None else extent_in(jobs.window_of(found), plan.transform)
    if window is not None and extent is not None and outside_window(extent, window):
        xmin, ymin, xmax, ymax = (_coordinate(value) for value in (
            extent.xmin, extent.ymin, extent.xmax, extent.ymax))
        wxmin, wymin, wxmax, wymax = (_coordinate(value) for value in (
            window.xmin, window.ymin, window.xmax, window.ymax))
        if plan.transform is None:
            notes.append(tr("The DTM «{name}» goes beyond the working window (X {wxmin} to "
                            "{wxmax}, Y {wymin} to {wymax}): its cells with data go from X "
                            "{xmin} to {xmax} and from Y {ymin} to {ymax}. It is imported "
                            "whole; the project grid only covers the window", name=name,
                            wxmin=wxmin, wxmax=wxmax, wymin=wymin, wymax=wymax, xmin=xmin,
                            xmax=xmax, ymin=ymin, ymax=ymax))
        else:
            notes.append(tr("The DTM «{name}» goes beyond the working window (X {wxmin} to "
                            "{wxmax}, Y {wymin} to {wymax}): its cells with data, transformed "
                            "to the project CRS, go from X {xmin} to {xmax} and from Y {ymin} "
                            "to {ymax}. It is imported whole; the project grid only covers the "
                            "window", name=name, wxmin=wxmin, wxmax=wxmax, wymin=wymin,
                            wymax=wymax, xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax))
    precision = summary.get("precision")
    report = None if precision is None else jobs.precision_of(precision)
    if report is not None and not report.within_limit:
        notes.append(tr("DTM «{name}», centres of the cells with data: {warning}", name=name,
                        warning=report.message))
    return notes


def _coordinate(value: float) -> str:
    """Una coordenada absoluta (m) para un aviso, con dos decimales (``format_xyz``)."""
    return format_number(value, 2)


class GEOBLENDER_OT_gis_import_dtm(ProvenanceAwareOperator, bpy.types.Operator):
    """Import a raster DTM (GeoTIFF, ASC, XYZ) onto the exact project grid"""

    bl_idname = IMPORT_DTM
    bl_label = "Raster DTM…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.IMPORT_DTM

    filepath: StringProperty(  # type: ignore[valid-type]
        name="File", subtype="FILE_PATH", options={"SKIP_SAVE"},
    )
    filter_glob: StringProperty(  # type: ignore[valid-type]
        default="*.tif;*.tiff;*.asc;*.xyz", options={"HIDDEN"},
    )
    name: StringProperty(  # type: ignore[valid-type]
        name="Name", description="Logical name of the input", options={"SKIP_SAVE"},
    )
    crs: StringProperty(  # type: ignore[valid-type]
        name="Horizontal CRS",
        description="EPSG code of the source's horizontal CRS, such as EPSG:25830 (empty: the "
                    "one the file declares)",
        options={"SKIP_SAVE"},
    )
    vertical: EnumProperty(  # type: ignore[valid-type]
        name="Vertical CRS", items=VERTICAL_ITEMS, default=UNDECLARED, options={"SKIP_SAVE"},
    )
    nodata_override: StringProperty(  # type: ignore[valid-type]
        name="No data",
        description="Value of the source that means no data (empty: the one the file declares)",
        options={"SKIP_SAVE"},
    )
    separator: EnumProperty(  # type: ignore[valid-type]
        name="Separator", items=SEPARATOR_ITEMS, default="AUTO", options={"SKIP_SAVE"},
    )
    decimal: EnumProperty(  # type: ignore[valid-type]
        name="Decimal mark", items=DECIMAL_ITEMS, default="POINT", options={"SKIP_SAVE"},
    )
    received_at: StringProperty(  # type: ignore[valid-type]
        name="Delivery date", description="Delivery day, DD/MM/YYYY (empty: no date)",
        options={"SKIP_SAVE"},
    )
    received_from: StringProperty(  # type: ignore[valid-type]
        name="Delivered by", description="Who delivered the input (empty: nobody recorded)",
        options={"SKIP_SAVE"},
    )
    reason: StringProperty(  # type: ignore[valid-type]
        name="Reason",
        description="Why the input replaces the one imported with the same data and other "
                    "settings",
        options={"SKIP_SAVE"},
    )
    pending: StringProperty(options={"HIDDEN", "SKIP_SAVE"})  # type: ignore[valid-type]
    decision: EnumProperty(  # type: ignore[valid-type]
        name="Decision", items=DECISION_ITEMS, default="CONTINUE", options={"SKIP_SAVE"},
    )
    # Con el fichero ya elegido (Importar un fichero…, o soltado en la vista; T32), el diálogo
    # de la importación en lugar de importar sin más.
    dialog: BoolProperty(options={"HIDDEN", "SKIP_SAVE"})  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context: Any) -> bool:
        return _poll(cls)

    def invoke(self, context: Any, event: Any) -> set[str]:
        self.provenance_dialog = True
        if self.pending:
            if self.pending not in _WAITING:
                return self.execute(context)
            self.decision = "CONTINUE"
            return context.window_manager.invoke_props_dialog(
                self, width=DIALOG_WIDTH, translate=False, title=tr("Import of a raster DTM"))
        if self.filepath and self.dialog:
            return context.window_manager.invoke_props_dialog(
                self, width=DIALOG_WIDTH, translate=False, title=tr("Import of a raster DTM"))
        if self.filepath:
            return self.execute(context)
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, context: Any) -> None:
        layout = self.layout
        plan = _WAITING.get(self.pending) if self.pending else None
        if plan is not None:
            for line in _wrapped(plan.question):
                layout.label(text=line, translate=False)
            if plan.kind == _SUBSTITUTE:
                layout.prop(self, "reason", text=tr("Reason"), translate=False)
            layout.prop(self, "decision", expand=True)
            return
        layout.use_property_split = True
        layout.prop(self, "name", text=tr("Name"), translate=False)
        layout.prop(self, "crs", text=tr("Horizontal CRS"), translate=False)
        layout.prop(self, "vertical", text=tr("Vertical CRS"), translate=False)
        layout.prop(self, "nodata_override", text=tr("No data"), translate=False)
        if Path(self.filepath).suffix.lower() == ".xyz":
            layout.prop(self, "separator", text=tr("Separator"), translate=False)
            layout.prop(self, "decimal", text=tr("Decimal mark"), translate=False)
        layout.prop(self, "received_at", text=tr("Delivery date"), translate=False)
        layout.prop(self, "received_from", text=tr("Delivered by"), translate=False)

    def execute(self, context: Any) -> set[str]:
        blocked = unavailable_reason()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        if self.pending:
            return self._decide()
        project = core_provenance.SESSION.project
        path = Path(bpy.path.abspath(self.filepath)) if self.filepath else None
        if path is None or not path.is_file():
            self.report({"ERROR"}, tr("The file «{file}» does not exist: choose the DTM to "
                                      "import", file="" if path is None else path.name))
            return {"CANCELLED"}
        try:
            reader = dtm_reader(path)
            settings = read_settings(reader, nodata_override=self.nodata_override,
                                     separator=SEPARATORS[self.separator],
                                     decimal=DECIMALS[self.decimal])
            source = plan_import(path, name=self.name, crs=parse_crs(self.crs),
                                 vertical=_vertical_choice(self.vertical, project),
                                 settings=settings, identify=_identify)
            transform = _transform(project, source)
            received_at = _delivery_day(self.received_at)
            control = control_values(project, CONTROL_KEYS)
        except _DateText as exc:
            self.report({"ERROR"}, tr("Delivery date «{value}»: write it as DD/MM/YYYY",
                                      value=str(exc)))
            return {"CANCELLED"}
        except (GeoblenderError, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        handle = self.begin(context, settings=_import_settings(source, control),
                            executor="job_thread")
        if handle is None:
            return {"CANCELLED"}
        plan = _Import(handle, source, transform, control, received_at=received_at,
                       received_from=self.received_from.strip() or None,
                       reason=self.reason.strip() or None)
        if _start_import(plan, self.launch_job) is None:
            return {"CANCELLED"}
        self.report({"INFO"}, tr("Importing «{name}» in the background…", name=source.name))
        return {"FINISHED"}

    def _decide(self) -> set[str]:
        """Sigue o cancela la importación ``pending`` que espera la decisión de la persona; lo
        que no se hace lo informa la orden (no se repite en el registro de Blender, T57)."""
        with core_provenance.caller_reports():
            return self._decided()

    def _decided(self) -> set[str]:
        plan = _WAITING.get(self.pending)
        if plan is None:
            self.report({"ERROR"}, tr("No DTM import is waiting for a decision"))
            return {"CANCELLED"}
        if not self.properties.is_property_set("decision"):
            self.report({"WARNING"}, tr("Choose whether to continue the import or cancel it: "
                                        "nothing changed"))
            return {"CANCELLED"}
        name = plan.source.name
        if self.decision == "CANCEL":
            _WAITING.pop(self.pending, None)
            assert plan.result is not None
            try:
                plan.handle.cancel(f"La persona canceló la importación: {plan.question}")
            except GeoblenderError as exc:
                self.report({"ERROR"}, error_text(exc))
                return {"CANCELLED"}
            core_provenance.release_job(plan.result.job_uid)
            self.report({"INFO"}, tr("Import of «{name}» cancelled: nothing has been written",
                                     name=name))
            return {"FINISHED"}
        if plan.kind == _SUBSTITUTE:
            reason = self.reason.strip()
            if not reason:
                self.report({"ERROR"}, tr("Write why «{name}» replaces the input with the same "
                                          "data", name=name))
                return {"CANCELLED"}
            plan.reason = reason
        else:
            plan.confirmed = True
        _WAITING.pop(self.pending, None)
        # Sigue por pasos desde el temporizador (T54): lo que no se haga lo dicen la barra de
        # estado y el registro de Blender (T57).
        _incorporate(plan.handle.uid, name, _import_steps(plan))
        return {"FINISHED"}


def reimport_dtm(request: ReimportRequest) -> OperationHandle:
    """La reimportación de una entrada de un MDT (``ImporterDef`` de ``gis.geotiff``,
    ``gis.asc`` y ``gis.xyz_grid``; RF-008-11, plan §5.6.8): vuelve a importar su fuente con
    sus ajustes registrados (o los que pide ``request.settings``) y sus CRS declarados, como
    una entrada nueva que la sustituye con el motivo, en su trabajo; devuelve la operación,
    aún «en curso». Sin escribir nada: ``core.input_unknown``, ``core.reimport_source_missing``
    (no se encuentra su fuente), la transformación sin precisión conocida (RF-006-05) y
    ``ValueError`` con un ajuste que no es de lectura de su lector."""
    project = request.project
    with project.read() as conn:
        record = get_input(conn, request.input_uid)
    if record is None:
        raise ProvenanceError("core.input_unknown", input=request.input_uid,
                              project=project.name)
    reader = _DTM_SOURCE_READERS.get(record.reader)
    if reader is None:
        raise ValueError(f"la entrada «{record.name}» no es la de un MDT ({record.reader})")
    files: dict[str, Path] = {}
    for role, item in zip(reader_roles(record.files), record.files, strict=True):
        path = resolve_source(item, project, project.userdata)
        if path is None or not path.is_file():
            raise ProvenanceError("core.reimport_source_missing", name=record.name,
                                  file=item.path)
        files[role] = path
    settings = dict(record.settings)
    given = dict(request.settings or {})
    unknown = sorted(key for key in given if key not in content.READER_SETTINGS[reader.id])
    if unknown:
        raise ValueError(f"ajustes que no son de lectura de «{reader.id}»: {unknown}")
    settings.update(given)
    # El .prj de un ASC, reconocido otra vez: el informe no dice que no se reconoció (T52).
    prj_crs = identify_prj(files[MAIN_ROLE], _identify) if reader is content.ASC else None
    source = DtmSource(record.name, reader, files, jobs.crs_of(dict(record.crs_h)),
                       jobs.vertical_of(dict(record.crs_v)), settings, prj_crs=prj_crs)
    transform = _transform(project, source)
    control = control_values(project, CONTROL_KEYS)
    handle = begin_operation(project, provenance.IMPORT_DTM,
                             settings=_import_settings(source, control), executor="job_thread",
                             supersedes=record.operation_uid)
    plan = _Import(handle, source, transform, control, received_at=request.received_at,
                   received_from=request.received_from, previous_uid=record.uid,
                   reason=request.reason)
    _start_import(plan, core_provenance.launch_job)
    return handle


# --- La rejilla del proyecto desde un MDT --------------------------------------------------


@dataclass(eq=False)
class _Resample:
    """Un remuestreo en marcha: su operación, el MDT y sus referencias, la rejilla del
    proyecto, el método, la fracción mínima y el submuestreo que usa, y el nombre."""

    handle: OperationHandle
    name: str
    source: DatasetRecord
    crs: CrsRef
    vertical: VerticalRef
    target: Grid
    method: str
    fraction: float
    supersample: int | None
    reprojects: bool


def _resolved(handle: OperationHandle) -> dict[str, Any]:
    """Los parámetros del proyecto que resolvió la operación al empezar, por clave."""
    return {param.key: param.value for param in handle.params}


def project_value(project: Any, key: str) -> tuple[Any, str, bool]:
    """El valor del parámetro de resultado ``key`` en el proyecto, su tipo y si está «sin
    confirmar»; si aún no lo tiene, el de su definición, que se registrará «sin confirmar» al
    empezar la orden (RF-008-04)."""
    record = core_params.ParameterStore(project).get(key)
    if record is None:
        defn = core_params.DEFINITIONS[key]
        return defn.default, str(defn.kind), True
    return record.value, str(record.kind), record.unconfirmed


def param_field(project: Any, key: str) -> tuple[str, str]:
    """El campo del diálogo de una orden con el parámetro de resultado ``key`` (D18; plan
    §5.6.1): su valor en el proyecto, como se teclea, y su insignia de tipo con «sin confirmar»
    si lo está."""
    value, kind, unconfirmed = project_value(project, key)
    note = badge(kind)
    if unconfirmed:
        note = f"{note} {tr('unconfirmed')}"
    return _decimal(value), note


def fraction_field(project: Any) -> tuple[str, str]:
    """El campo de la fracción mínima del diálogo de la rejilla del proyecto
    (:func:`param_field`)."""
    return param_field(project, FRACTION_KEY)


def _source_record(project: Any, ref: str) -> DatasetRecord:
    """El MDT importado ``ref`` (nombre o uid de un ``gis_src_``); ``gis.dataset_unknown`` si
    no lo hay."""
    shown = ref.strip()
    with project.read() as conn:
        record = dataset_registry.get(conn, shown) if shown else None
    prefix = provenance.FAMILIES_BY_CODE[provenance.SOURCE_GRID].prefix
    if record is None or record.module != MODULE or not record.name.startswith(prefix):
        raise GisError("gis.dataset_unknown", obj="Dato de topografía", field="dato",
                       value=ref)
    return record


def _resample_plan(handle: OperationHandle, record: DatasetRecord,
                   settings: Mapping[str, Any]) -> _Resample:
    """El remuestreo de ``record`` de la operación ``handle`` con sus ajustes ``settings``:
    la fracción tecleada o, si no, la del proyecto que resolvió al empezar."""
    project = handle.project
    crs, vertical = store.dataset_references(project, record)
    project_crs, project_vertical = store.project_references(project)
    resolved = _resolved(handle)
    fraction = settings.get("min_valid_fraction", resolved.get(FRACTION_KEY))
    supersample = resolved.get(SUPERSAMPLE_KEY)
    return _Resample(handle, str(settings["name"]), record, crs, vertical,
                     jobs.grid_of(settings["grid"]), str(settings["method"]), float(fraction),
                     None if supersample is None else int(supersample),
                     needs_transform(crs, vertical, project_crs, project_vertical))


def _start_resample(plan: _Resample, launch: Callable[..., Any]) -> Any:
    """Lanza el trabajo ``gis_resample`` de ``plan`` con ``launch``, con la rejilla del MDT
    copiada a ``in/`` y, si reproyecta, las ruedas de la extensión; al terminar,
    :func:`_resample_finished`."""
    project = plan.handle.project
    path = _file_of(project, plan.source)
    project_crs, project_vertical = store.project_references(project)
    params = {"name": plan.name, "source_crs": jobs.crs_json(plan.crs),
              "source_vertical": jobs.vertical_json(plan.vertical),
              "target_crs": jobs.crs_json(project_crs),
              "target_vertical": jobs.vertical_json(project_vertical),
              "target": jobs.grid_json(plan.target), "method": plan.method,
              "min_valid_fraction": plan.fraction, "supersample": plan.supersample,
              "size": path.stat().st_size}
    site = wheels_site() if jobs.needs_site(jobs.RESAMPLE, params) else None
    return launch(plan.handle, jobs.RESAMPLE, label=tr("Project grid «{name}»", name=plan.name),
                  params=params, inputs={jobs.INPUT_SOURCE: path}, site_override=site,
                  on_finish=functools.partial(_resample_finished, plan),
                  grace_s=jobs.CANCEL_GRACE_S)


def _resample_finished(plan: _Resample, result: JobResult) -> None:
    """El final del trabajo de un remuestreo: si terminó bien, su rejilla pasa a
    ``gis_dtm_<nombre>`` con el informe (si no, la procedencia deja la operación cancelada o
    fallida con el motivo de la 004)."""
    if result.state != _SUCCEEDED:
        return
    project = plan.handle.project
    try:
        outcome = job_outcome(result, result.job_dir)
        summary = outcome.summary
        report = _resample_report(plan, summary)
        role = jobs.OUT_PROJECT_GRID.role
        with store.ResultWriter(project, plan.handle) as out:
            out.copy_file(provenance.PROJECT_GRID, plan.name, outcome.file(role),
                          content=jobs.digest_of(summary["outputs"][role]["digest"]),
                          sha256=outcome.output(role).sha256)
            library, version = crs_library()
            core_provenance.ingest_job_result(plan.handle, result, out.write,
                                              software={library: version}, message=report)
    except Exception as error:  # noqa: BLE001 - la operación queda fallida con el motivo
        reason = _failure(plan.handle, result, error)
        _say(tr("The project grid «{name}» has not been computed: {reason}", name=plan.name,
                reason=reason))
        return
    _say(report)


def _method_text(method: str) -> str:
    """El nombre del método de un remuestreo para el informe (RF-006-11)."""
    if method == "area_mean":
        return tr("area-weighted mean")
    if method == "bilinear":
        return tr("bilinear interpolation")
    if method == "mode":
        return tr("majority of classes")
    return method


def _resample_report(plan: _Resample, summary: Mapping[str, Any]) -> str:
    """El informe de un remuestreo: la rejilla, el método, las celdas con dato, la fracción
    mínima y, si reproyectó, la transformación con su precisión (RF-006-05, RF-006-11)."""
    lines = [tr("Project grid {dataset} from «{source}»: {method}, {valid} of {cells} cells "
                "with data, minimum covered fraction {fraction}",
                dataset=provenance.dataset_name(provenance.PROJECT_GRID, plan.name),
                source=plan.source.name, method=_method_text(str(summary["method"])),
                valid=format_number(int(summary["valid_cells"]), 0),
                cells=format_number(int(summary["cells"]), 0),
                fraction=_decimal(plan.fraction))]
    transform = summary.get("transform")
    if transform:
        lines.append(tr("Transformation: {transform}", transform=transform["summary"]))
    return "\n".join(lines)


def recompute_resample(request: RecomputeRequest) -> OperationHandle:
    """El recálculo de ``gis.resample`` (RF-008-26; plan §5.6.8): la misma orden con el MDT
    vigente, los parámetros de hoy y los mismos ajustes, en su trabajo; devuelve la operación
    nueva, que sustituye a la antigua, aún «en curso»."""
    project = request.project
    (use,) = [use for use in request.inputs if use.role == "source"]
    with project.read() as conn:
        record = dataset_registry.get(conn, use.item)
    if record is None:
        raise GisError("gis.dataset_unknown", obj="Dato de topografía", field="dato",
                       value=use.item)
    crs, vertical = store.dataset_references(project, record)
    reprojects = needs_transform(crs, vertical, *store.project_references(project))
    handle = request.begin(executor="job_process" if reprojects else "job_thread")
    _start_resample(_resample_plan(handle, record, request.settings),
                    core_provenance.launch_job)
    return handle


class GEOBLENDER_OT_gis_resample_to_grid(ProvenanceAwareOperator, bpy.types.Operator):
    """Resample a DTM to the exact-step project grid"""

    bl_idname = RESAMPLE_TO_GRID
    bl_label = "Project grid from a DTM…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.RESAMPLE

    source: StringProperty(  # type: ignore[valid-type]
        name="DTM", description="Name or uid of the imported DTM", options={"SKIP_SAVE"},
    )
    method: EnumProperty(  # type: ignore[valid-type]
        name="Method", items=METHOD_ITEMS, default="AUTO", options={"SKIP_SAVE"},
    )
    min_valid_fraction: StringProperty(  # type: ignore[valid-type]
        name="Minimum covered fraction",
        description="Fraction of each cell that must be covered by data, from 0 to 1 (empty or "
                    "unchanged: the project's parameter)",
        options={"SKIP_SAVE"},
    )
    name: StringProperty(  # type: ignore[valid-type]
        name="Name", description="Name of the project grid (empty: the DTM's)",
        options={"SKIP_SAVE"},
    )
    items: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_view_dataset, options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context: Any) -> bool:
        return _poll(cls)

    def provenance_inputs(self, context: Any) -> tuple[Use, ...]:
        record = getattr(self, "_record", None)
        return () if record is None else (Use(record.uid, "source"),)

    def invoke(self, context: Any, event: Any) -> set[str]:
        self.provenance_dialog = True
        if self.source:
            return self.execute(context)
        project = core_provenance.SESSION.project
        try:
            records = store.list_gis_datasets(project, families=(provenance.SOURCE_GRID,))
        except GeoblenderError as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        if not records:
            path = path_text(command_catalog(), IMPORT_DTM, i18n.language())
            self.report({"ERROR"}, tr("First {step} ({path})", step=tr("import a DTM"),
                                      path=path))
            return {"CANCELLED"}
        self.items.clear()
        for record in records:
            item = self.items.add()
            item.name = record.name
            item.uid = record.uid
            item.label = record.name
        self.source = records[-1].name
        self.min_valid_fraction, self._fraction_note = fraction_field(project)
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False, title=tr("Resampling to the project grid"))

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.prop_search(self, "source", self, "items", text=tr("DTM"), translate=False)
        layout.prop(self, "method", text=tr("Method"), translate=False)
        row = layout.row()
        row.prop(self, "min_valid_fraction", text=tr("Minimum covered fraction"),
                 translate=False)
        row.label(text=getattr(self, "_fraction_note", ""), translate=False)
        layout.prop(self, "name", text=tr("Name"), translate=False)

    def execute(self, context: Any) -> set[str]:
        blocked = unavailable_reason()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        project = core_provenance.SESSION.project
        try:
            record = _source_record(project, self.source)
            if project.window is None:
                self.report({"ERROR"}, no_work_window_message())
                return {"CANCELLED"}
            target = project_grid(project.window, project.grid_step_m)
            crs, vertical = store.dataset_references(project, record)
            reprojects = needs_transform(crs, vertical, *store.project_references(project))
            name = self.name.strip() or record.name.removeprefix(
                provenance.FAMILIES_BY_CODE[provenance.SOURCE_GRID].prefix)
            provenance.dataset_slug(name)  # un nombre sin letras ni cifras no vale
            settings: dict[str, Any] = {"name": name, "method": METHODS[self.method],
                                        "grid": jobs.grid_json(target)}
            params: list[str] = []
            typed = None
            if self.min_valid_fraction.strip():
                typed = gis_params.param(FRACTION_KEY).check(parse_decimal(
                    self.min_valid_fraction, obj=tr("Minimum covered fraction"),
                    field=FRACTION_KEY))
            if typed is None or typed == project_value(project, FRACTION_KEY)[0]:
                params.append(FRACTION_KEY)  # la del proyecto: se consume (RF-008-05)
            else:
                settings["min_valid_fraction"] = typed  # tecleada: un ajuste (D18)
            if reprojects:
                params.append(SUPERSAMPLE_KEY)
        except (GeoblenderError, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        self._record = record
        handle = self.begin(context, settings=settings, params=params,
                            executor="job_process" if reprojects else "job_thread")
        if handle is None:
            return {"CANCELLED"}
        try:
            plan = _resample_plan(handle, record, settings)
            job = _start_resample(plan, self.launch_job)
        except (GeoblenderError, OSError, ValueError) as exc:
            try:
                handle.fail(error_text(exc))
            except GeoblenderError:
                pass
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        if job is None:
            return {"CANCELLED"}
        self.report({"INFO"}, tr("Computing the project grid «{name}» in the background…",
                                 name=name))
        return {"FINISHED"}


# --- Puntos, líneas de rotura y capas (T29) -----------------------------------------------


IMPORT_POINTS = "geoblender.gis_import_points"
IMPORT_VECTOR = "geoblender.gis_import_vector"
TIN_FROM_POINTS = "geoblender.gis_create_tin_from_points"
TIN_FROM_CONTOURS = "geoblender.gis_create_tin_from_contours"
CONVERT_DTM_TIN = "geoblender.gis_convert_dtm_tin"
SURVEY_IMPORTERS: tuple[str, ...] = ("gis.points_text", "gis.gpkg_layer")
"""Los lectores (sin versión) del texto de puntos y de las capas: su reimportación (T29)."""
DUP_KEYS: tuple[str, ...] = (DUP_XY_KEY, DUP_Z_KEY)
"""Las tolerancias de duplicados: de resultado en un TIN; de control en una importación,
donde solo cuentan los duplicados del informe (D17)."""
REJECTIONS_SHOWN = 50
"""Filas o entidades rechazadas que se citan en el informe de una importación."""
CONFLICTS_SHOWN = 50
"""Conflictos de un TIN que se citan en los avisos y en el motivo de su operación."""
ENCODING_ITEMS = [
    ("UTF8", "UTF-8", ""),
    ("CP1252", "Windows-1252", ""),
    ("ISO8859_1", "ISO-8859-1 (Latin-1)", ""),
    ("CP850", "DOS (CP850)", ""),
]
ENCODINGS: Mapping[str, str] = {"UTF8": "utf-8", "CP1252": "cp1252", "ISO8859_1": "iso8859-1",
                                "CP850": "cp850"}
POINT_SEPARATOR_ITEMS = [
    ("SEMICOLON", "Semicolon", ""),
    ("COMMA", "Comma", ""),
    ("TAB", "Tab", ""),
    ("SPACE", "Space", "One or more blanks"),
]
POINT_SEPARATORS: Mapping[str, str] = {"SEMICOLON": ";", "COMMA": ",", "TAB": "\t",
                                       "SPACE": " "}
LINE_KIND_ITEMS = [
    ("HARD", "Hard", "The breaklines are edges of the TIN"),
    ("SOFT", "Soft", "The breaklines only add their points"),
]
LINE_KINDS: Mapping[str, str] = {"HARD": "hard", "SOFT": "soft"}
LAYER_ROLE_ITEMS = [
    ("POINTS", "Points", ""),
    ("BREAKLINES", "Breaklines", ""),
    ("CONTOURS", "Contour lines", ""),
    ("BOUNDARY", "Boundary", "Boundary and holes of a TIN"),
    ("DOMAINS", "Domains",
     "Polygons that divide a cubication (phases, zones or sectors), with their fields"),
    ("FEATURES", "Features",
     "Points, lines or polygons with their fields (constraints, infrastructures, client "
     "marks), in the project CRS"),
]
LAYER_ROLES: Mapping[str, str] = {"POINTS": "points", "BREAKLINES": "breaklines",
                                  "CONTOURS": "contours", "BOUNDARY": "boundary",
                                  "DOMAINS": "domains", "FEATURES": "features"}
_GUESSES: Mapping[str, tuple[str, ...]] = {
    "point_id": ("p", "punto", "id", "point", "pt", "num", "numero", "nombre", "name"),
    "x": ("x", "este", "easting", "e", "coordx"),
    "y": ("y", "norte", "northing", "n", "coordy"),
    "z": ("z", "cota", "elevation", "altura", "h", "coordz"),
    "code": ("codigo", "code", "cod"),
    "line": ("linea", "line", "rotura", "breakline"),
}
"""Los nombres de cabecera con que se adivina el papel de cada columna (sin tildes ni
mayúsculas)."""


def _plain_header(text: str) -> str:
    """Un nombre de cabecera sin tildes, en minúsculas y solo con letras y cifras."""
    plain = "".join(char for char in unicodedata.normalize("NFKD", text)
                    if not unicodedata.combining(char)).lower()
    return "".join(char for char in plain if char.isalnum())


def guess_columns(header: Sequence[str]) -> dict[str, int]:
    """El papel de cada columna adivinado por su nombre en la cabecera (P, X, Y, Z, Código,
    Línea…): papel → índice desde 0, solo los que se reconocen (el primero de cada uno)."""
    found: dict[str, int] = {}
    for index, text in enumerate(header):
        key = _plain_header(str(text))
        for role, names in _GUESSES.items():
            if role not in found and key in names:
                found[role] = index
                break
    return found


def _mapping_of(columns: Any) -> dict[str, int]:
    """La correspondencia de las filas del asistente (``GEOBLENDER_PG_gis_column``): papel →
    índice; ``ValueError`` si dos filas tienen el mismo papel."""
    found: dict[str, int] = {}
    for item in columns:
        if item.role == NOT_IMPORTED:
            continue
        role = COLUMN_ROLES[item.role]
        if role in found:
            raise ValueError(tr("Two columns have the role «{role}»: choose one",
                                role=item.role))
        found[role] = int(item.index)
    return found


@dataclass(eq=False)
class _Survey:
    """Una importación de puntos o de una capa en marcha: su operación, la fuente, su lector,
    sus ajustes de lectura, los CRS declarados (en una capa, el horizontal puede llegar de
    ella), los parámetros de control, la entrega, la entrada a la que sustituye y el
    motivo."""

    handle: OperationHandle
    name: str
    path: Path
    reader: str
    settings: dict[str, Any]
    crs: CrsRef | None
    vertical: VerticalRef
    control: Mapping[str, Any]
    received_at: Any = None
    received_from: str | None = None
    previous_uid: str | None = None
    reason: str | None = None
    failure: str = ""


def _survey_settings(plan: _Survey) -> dict[str, Any]:
    """Los ajustes de la operación de una importación de puntos o de una capa: el nombre
    lógico, el fichero (sin su ruta), el lector, los ajustes de lectura, los CRS declarados y
    los parámetros de control con su valor (D17)."""
    return {"name": plan.name, "file": plan.path.name, "reader": plan.reader,
            "read": dict(plan.settings), "crs": jobs.crs_json(plan.crs),
            "vertical": jobs.vertical_json(plan.vertical), "control": dict(plan.control)}


def _start_survey(plan: _Survey, launch: Callable[..., Any]) -> Any:
    """Lanza el trabajo de la importación de ``plan`` (``gis_import_points`` o
    ``gis_import_vector``) con ``launch``; al terminar, :func:`_survey_finished`."""
    points = plan.reader == content.POINTS_TEXT.id
    params = {"reader": plan.reader, "name": plan.name, "settings": plan.settings,
              "crs": jobs.crs_json(plan.crs), "vertical": jobs.vertical_json(plan.vertical),
              "size": plan.path.stat().st_size, "tol_xy": plan.control.get(DUP_XY_KEY),
              "tol_z": plan.control.get(DUP_Z_KEY)}
    if plan.settings.get("role") == "features":  # al CRS del proyecto (spec 012, D-27)
        params["target_crs"] = jobs.crs_json(store.project_references(plan.handle.project)[0])
    label = (tr("Import of the points «{name}»", name=plan.name) if points
             else tr("Import of the layer «{name}»", name=plan.name))
    return launch(plan.handle, jobs.IMPORT_POINTS if points else jobs.IMPORT_VECTOR,
                  label=label, params=params, paths={jobs.path_name(MAIN_ROLE): plan.path},
                  on_finish=functools.partial(_survey_finished, plan),
                  grace_s=jobs.CANCEL_GRACE_S)


def _survey_finished(plan: _Survey, result: JobResult) -> None:
    """El final del trabajo de una importación de puntos o de una capa: si terminó bien, su
    incorporación por pasos desde el temporizador (:func:`_survey_steps`,
    :func:`incorporation_tick`; T50, RNF-006-09); si no, la procedencia la deja cancelada o
    fallida."""
    if result.state == _SUCCEEDED:
        _incorporate(plan.handle.uid, plan.name, _survey_steps(plan, result))


# --- Incorporar por pasos (T50) ----------------------------------------------------------------


INCORPORATION_TICK_S = 0.0
"""Lo que espera el temporizador de las incorporaciones entre dos pasos: nada (Blender redibuja
la interfaz y la barra de estado entre dos llamadas)."""


@dataclass(eq=False)
class _Incorporation:
    """Una incorporación por pasos en marcha (T50): su operación, el nombre que enseña la barra
    de estado, sus pasos (un generador que da su avance, 0–1, tras cada uno) y lo hecho."""

    uid: str
    name: str
    steps: Iterator[float]
    done: float = 0.0


_INCORPORATIONS: list[_Incorporation] = []
"""Las incorporaciones que esperan su turno en el temporizador, por orden de llegada."""


def pending_incorporations() -> list[str]:
    """Las operaciones cuya incorporación por pasos espera el temporizador (T50)."""
    return [item.uid for item in _INCORPORATIONS]


def _incorporate(uid: str, name: str, steps: Iterator[float]) -> None:
    """Pone en cola la incorporación ``steps`` de la operación ``uid`` y registra su
    temporizador (:func:`incorporation_tick`) si no lo estaba."""
    _INCORPORATIONS.append(_Incorporation(uid, name, steps))
    if not bpy.app.timers.is_registered(incorporation_tick):
        bpy.app.timers.register(incorporation_tick, first_interval=INCORPORATION_TICK_S,
                                persistent=True)


def incorporation_tick() -> float | None:
    """El temporizador de las incorporaciones por pasos (T50; RF-006-28, RNF-006-09): un paso
    de la primera de la cola por llamada (cada uno, unas décimas de segundo como mucho: leer lo
    que dejó el trabajo, codificar sus filas, la transacción corta del final, cada trozo del
    original o, en un MDT, T54, cada trozo de su rejilla) y su avance en la barra de estado; lo
    largo (el hash de las tablas, las posiciones de la comparación de cotas) lo hizo ya su
    trabajo, con su avance y su cancelación. Devuelve cuándo volver (``None``: no queda
    ninguna)."""
    if not _INCORPORATIONS:
        return None
    current = _INCORPORATIONS[0]
    try:
        current.done = float(next(current.steps))
    except StopIteration:
        _INCORPORATIONS.pop(0)
    except Exception:  # noqa: BLE001 - los pasos tratan sus errores: esto es del programa
        LOGGER.exception("La incorporación de «%s» (%s) se ha parado", current.name,
                         current.uid)
        _INCORPORATIONS.pop(0)
    if not _INCORPORATIONS:
        _status(None)
        return None
    shown = _INCORPORATIONS[0]
    _status(tr("Adding «{name}» to the project… {percent} %", name=shown.name,
               percent=int(100 * min(max(shown.done, 0.0), 1.0))))
    return INCORPORATION_TICK_S


def _drop_incorporations() -> None:
    """Olvida las incorporaciones en cola (al desregistrar): cada una se cierra sin escribir
    nada más en el proyecto (su operación sigue «en curso», como las que olvida la 008)."""
    shown = bool(_INCORPORATIONS)
    while _INCORPORATIONS:
        _INCORPORATIONS.pop(0).steps.close()  # type: ignore[attr-defined]
    if bpy.app.timers.is_registered(incorporation_tick):
        bpy.app.timers.unregister(incorporation_tick)
    if shown:
        _status(None)


def _survey_spec(plan: _Survey, summary: Mapping[str, Any]) -> Any:
    """La entrada de la importación con lo que trae el resumen de su trabajo (RF-008-07)."""
    project = plan.handle.project
    found = summary["source"]
    main = found["files"][MAIN_ROLE]
    anchor = locate_source(plan.path, project, project.userdata, role="main")
    prints = [SourcePrint(main["sha256"], size=main["size"], mtime_ns=main["mtime_ns"])]
    return store.source_input(found["reader"], plan.name, files=[anchor], file_prints=prints,
                              digest=jobs.digest_of(found["digest"]),
                              crs=jobs.crs_of(summary["crs"]),
                              vertical=jobs.vertical_of(summary["vertical"]),
                              settings=dict(plan.settings), received_at=plan.received_at,
                              received_from=plan.received_from)


def _survey_steps(plan: _Survey, result: JobResult) -> Generator[float, None, str]:
    """Los pasos que incorporan la importación de ``plan`` (su trabajo terminó bien), con su
    avance (0–1) tras cada uno; cada paso, unas décimas de segundo del hilo de Blender como
    mucho (T50; RNF-006-09): lo que dejó el trabajo y su clasificación (``"reused"``: la misma
    entrada, cancelada con el aviso, RF-008-54; ``"cancelled"``: los mismos datos con otros
    ajustes y sin motivo, se repite con él, RF-008-11); la entrada declarada; lo importado,
    leído y codificado (:func:`_survey_tables`, con el hash de cada tabla que calculó su
    trabajo); la transacción corta del final (``ingest_job``, I-7 de la 008); el original del
    texto de puntos desde la copia verificada del trabajo, por trozos (RF-008-53), y el
    trabajo, dado por incorporado. Devuelve (``StopIteration.value``) cómo quedó: ``"done"``,
    ``"reused"``, ``"cancelled"`` o ``"failed"``. Un error la deja fallida con su motivo y
    nada escrito; cerrar los pasos antes de la transacción (al desregistrar) no escribe nada
    (la operación sigue «en curso» y queda «interrumpida» al abrir el proyecto)."""
    project = plan.handle.project
    language = i18n.language()
    out: store.ResultWriter | None = None
    try:
        outcome = job_outcome(result, result.job_dir)
        summary = outcome.summary
        spec = _survey_spec(plan, summary)
        if plan.previous_uid is None:
            found = store.classify_source(project, spec)
            if isinstance(found, Reuse):
                with store.ResultWriter(project, plan.handle) as reused:
                    reused.declare_input(spec)  # la deja cancelada con el aviso
                core_provenance.release_job(result.job_uid)
                _say(found.render(language))
                return "reused"
            if isinstance(found, Substitute):
                if not plan.reason:
                    text = tr("«{name}» has the same data as the input «{existing}» with other "
                              "settings ({differences}): import it again with the reason why "
                              "it replaces it", name=plan.name, existing=found.input.name,
                              differences=found.describe(language))
                    plan.handle.cancel(text)
                    core_provenance.release_job(result.job_uid)
                    _say(text)
                    return "cancelled"
                plan.previous_uid = found.input.uid
        report = _survey_report(plan, summary, outcome)
        yield 0.1
        out = store.ResultWriter(project, plan.handle)
        out.declare_input(spec, previous_uid=plan.previous_uid, reason=plan.reason)
        yield 0.2
        yield from _survey_tables(out, plan, outcome, summary)
        ingest_job(project, plan.handle, outcome, out.write, message=report)
        out.close()
    except GeneratorExit:
        if out is not None:
            out.close()  # sin escribir nada: la operación sigue «en curso»
        raise
    except Exception as error:  # noqa: BLE001 - la operación queda fallida con el motivo
        if out is not None:
            out.close(error)
        plan.failure = tr("«{name}» has not been imported: {reason}", name=plan.name,
                          reason=_failure(plan.handle, result, error))
        _say(plan.failure)
        return "failed"
    yield 0.8
    try:  # lo importado ya está en el proyecto: falta el original y dar el trabajo por hecho
        if plan.reader == content.POINTS_TEXT.id:
            yield from _original_steps(out, result.job_dir.inputs_dir / (
                jobs.path_name(MAIN_ROLE) + plan.path.suffix))
    finally:
        core_provenance.release_job(result.job_uid)
    _say(report)
    return "done"


def _original_steps(out: store.ResultWriter, verified: Path) -> Iterator[float]:
    """El original del texto de puntos desde la copia verificada (RF-008-53), por los trozos
    de ``store_originals_steps`` (cada uno, un paso); si no se puede guardar, la importación
    sigue hecha y se avisa."""
    try:
        for step in out.originals([verified]):
            yield 0.8 + 0.19 * (step.done / step.total if step.total else 1.0)
    except Exception as error:  # noqa: BLE001 - lo importado ya está confirmado
        LOGGER.warning("No se guardó el original de «%s»", verified.name, exc_info=True)
        _say(tr("The original of the input could not be kept: {reason}",
                reason=error_text(error)))


def _table_contents(summary: Mapping[str, Any]) -> dict[str, Any]:
    """El hash de cada tabla de lo importado que calculó el trabajo (T50), por su papel."""
    found: dict[str, Any] = {}
    for role, output in dict(summary.get("outputs") or {}).items():
        if isinstance(output, Mapping) and output.get("digest") is not None:
            found[str(role)] = jobs.digest_of(output["digest"])
    return found


def _survey_tables(out: store.ResultWriter, plan: _Survey, outcome: Any,
                   summary: Mapping[str, Any]) -> Iterator[float]:
    """Prepara lo importado del resultado del trabajo, en pasos: puntos y líneas de un texto;
    de una capa, según su papel; cada tabla con el hash que calculó el trabajo (T50: el hilo
    de Blender no la vuelve a leer). Sin nada que importar, ``gis.survey_empty``."""
    contents = _table_contents(summary)
    if plan.reader == content.POINTS_TEXT.id:
        points = jobs.read_points(outcome.file(jobs.OUT_POINTS.role))
        yield 0.3
        lines = jobs.read_lines(outcome.file(jobs.OUT_LINES.role))
        if len(points):
            out.points(plan.name, points, content=contents.get(jobs.OUT_POINTS.role))
        yield 0.5
        if lines:
            out.breaklines(plan.name, lines, content=contents.get(jobs.OUT_LINES.role))
        count = len(points) + len(lines)
    else:
        role = str(summary["role"])
        output = jobs.LAYER_OUTPUTS[role].role
        path = outcome.file(output)
        count = int(summary["count"])
        if count and role == "points":
            out.points(plan.name, jobs.read_points(path), content=contents.get(output))
        elif count and role == "breaklines":
            out.breaklines(plan.name, jobs.read_lines(path), content=contents.get(output))
        elif count and role == "contours":
            out.contours(plan.name, jobs.read_contours(path), content=contents.get(output))
        elif count and role == "domains":  # spec 011, T18 (D-32)
            out.domains(plan.name, jobs.read_domains(path), content=contents.get(output))
        elif count and role == "features":  # spec 012, T07 (D-27)
            layer = jobs.read_features(path)
            transform = _features_transform(plan, summary)
            if transform is not None:
                layer = vector.transform_features(layer, transform)
            out.features(plan.name, layer, content=contents.get(output))
        elif count:
            out.boundary(plan.name, jobs.read_boundary(path, jobs.crs_of(summary["crs"]).epsg),
                         content=contents.get(output))
    if not count:
        raise GisError("gis.survey_empty", obj=f"«{plan.path.name}»", field="filas",
                       value=0, name=plan.name, file=plan.path.name,
                       rejected=int(summary.get("rejected", 0)))
    yield 0.6


def _features_transform(plan: _Survey, summary: Mapping[str, Any]) -> Transform | None:
    """La transformación de la 006 de las entidades de una capa (spec 012, D-27) de su CRS al
    del proyecto, en planta (la referencia vertical del proyecto a los dos lados: la cota no
    cuenta), o ``None`` si es el mismo; ``GisError`` sin una de precisión conocida (RF-006-05)
    o sin servicio de CRS (RF-006-31)."""
    crs, vertical = store.project_references(plan.handle.project)
    return transformation_for(Declaration(plan.name, jobs.crs_of(summary["crs"]), vertical),
                              crs, vertical, resolver=crs_resolver)


def _rejections(outcome: Any) -> list[str]:
    """Las filas o entidades rechazadas del informe del trabajo (número y motivo), como mucho
    :data:`REJECTIONS_SHOWN`."""
    report = json.loads(outcome.file(jobs.OUT_REPORT.role).read_text("utf-8"))
    rejected = list(report.get("rejected", ()))
    lines = [str(item["reason"]) for item in rejected[:REJECTIONS_SHOWN]]
    if len(rejected) > REJECTIONS_SHOWN:
        lines.append(tr("… and {count} more rejected", count=format_number(
            len(rejected) - REJECTIONS_SHOWN, 0)))
    lines.extend(str(item) for item in report.get("warnings", ()))
    return lines


def _survey_report(plan: _Survey, summary: Mapping[str, Any], outcome: Any) -> str:
    """El informe de una importación de puntos o de una capa (RF-006-12): lo leído, lo
    importado, lo rechazado (con número y motivo) y los duplicados."""
    if plan.reader == content.POINTS_TEXT.id:
        names = [name for family, count in ((provenance.POINTS, summary["points"]),
                                            (provenance.BREAKLINES, summary["lines"]))
                 if count for name in [provenance.dataset_name(family, plan.name)]]
        head = tr("Points «{name}» imported as {datasets}: rows read {read}, points {points}, "
                  "breaklines {lines}, rejected {rejected}, duplicates {duplicates}",
                  name=plan.name, datasets=tr(" and ").join(names) if names else "—",
                  read=format_number(int(summary["read"]), 0),
                  points=format_number(int(summary["points"]), 0),
                  lines=format_number(int(summary["lines"]), 0),
                  rejected=format_number(int(summary["rejected"]), 0),
                  duplicates=format_number(int(summary.get("duplicates", 0)), 0))
    else:
        role = str(summary["role"])
        family = provenance.layer_family(role)
        what = {"points": tr("points"), "breaklines": tr("breaklines"),
                "contours": tr("contour lines"), "boundary": tr("boundaries"),
                "domains": tr("domains"), "features": tr("features")}[role]
        head = tr("Layer «{layer}» of «{file}» imported as {dataset}: {count} {what} of {read} "
                  "features read, {rejected} rejected", layer=summary["layer"],
                  file=plan.path.name, dataset=provenance.dataset_name(family, plan.name),
                  count=format_number(int(summary["count"]), 0), what=what,
                  read=format_number(int(summary["read"]), 0),
                  rejected=format_number(int(summary["rejected"]), 0))
        if role == "points":
            head += "; " + tr("duplicates {duplicates}", duplicates=format_number(
                int(summary.get("duplicates", 0)), 0))
        transform = _features_transform(plan, summary) if role == "features" else None
        if transform is not None:  # spec 012, D-27
            crs, vertical = store.project_references(plan.handle.project)
            head += "\n" + tr("«{name}» transformed from {source} to {target}: {transform}",
                              name=plan.name,
                              source=reference_label(jobs.crs_of(summary["crs"]), vertical),
                              target=reference_label(crs, vertical),
                              transform=transform_summary(transform.info))
    return "\n".join([head, *_rejections(outcome)])


def _declared_vertical(choice: str, project: Any, source: str) -> VerticalRef:
    """El datum vertical elegido para la fuente ``source``; «Sin declarar»,
    ``gis.vertical_undeclared`` (RF-006-04: un texto o una capa no lo declaran)."""
    found = _vertical_choice(choice, project)
    if found is None:
        raise GisError("gis.vertical_undeclared", obj=source, field=VERTICAL_FIELD,
                       source=source)
    return found


def reimport_survey(request: ReimportRequest) -> OperationHandle:
    """La reimportación de una entrada de puntos (``gis.points_text``) o de una capa
    (``gis.gpkg_layer``) (RF-008-11; plan §5.6.8): vuelve a importar su fuente con sus ajustes
    registrados (o los que pide ``request.settings``) y sus CRS declarados, como una entrada
    nueva que la sustituye con el motivo, en su trabajo; devuelve la operación, aún «en
    curso». Sin escribir nada: ``core.input_unknown``, ``core.reimport_source_missing`` y
    ``ValueError`` con un ajuste que no es de lectura de su lector."""
    project = request.project
    with project.read() as conn:
        record = get_input(conn, request.input_uid)
    if record is None:
        raise ProvenanceError("core.input_unknown", input=request.input_uid,
                              project=project.name)
    if record.reader not in (content.POINTS_TEXT.id, content.GPKG_LAYER.id):
        raise ValueError(f"la entrada «{record.name}» no es de puntos ni de una capa "
                         f"({record.reader})")
    path = resolve_source(record.files[0], project, project.userdata)
    if path is None or not path.is_file():
        raise ProvenanceError("core.reimport_source_missing", name=record.name,
                              file=record.files[0].path)
    settings = dict(record.settings)
    given = dict(request.settings or {})
    unknown = sorted(key for key in given if key not in content.READER_SETTINGS[record.reader])
    if unknown:
        raise ValueError(f"ajustes que no son de lectura de «{record.reader}»: {unknown}")
    settings.update(given)
    points = record.reader == content.POINTS_TEXT.id
    plan = _Survey(None, record.name, path, record.reader, settings,  # type: ignore[arg-type]
                   jobs.crs_of(dict(record.crs_h)), jobs.vertical_of(dict(record.crs_v)),
                   control_values(project, DUP_KEYS), received_at=request.received_at,
                   received_from=request.received_from, previous_uid=record.uid,
                   reason=request.reason)
    plan.handle = begin_operation(
        project, provenance.IMPORT_POINTS if points else provenance.IMPORT_VECTOR,
        settings=_survey_settings(plan), executor="job_thread",
        supersedes=record.operation_uid)
    _start_survey(plan, core_provenance.launch_job)
    return plan.handle


class _SurveyMixin:
    """Lo común de las dos importaciones de la T29: la puerta, la entrega y el lanzamiento."""

    def _start(self, context: Any, plan_values: dict[str, Any]) -> set[str]:
        project = core_provenance.SESSION.project
        try:
            received_at = _delivery_day(self.received_at)  # type: ignore[attr-defined]
            control = control_values(project, DUP_KEYS)
        except _DateText as exc:
            text = tr("Delivery date «{value}»: write it as DD/MM/YYYY", value=str(exc))
            self.report({"ERROR"}, text)  # type: ignore[attr-defined]
            return {"CANCELLED"}
        except (GeoblenderError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))  # type: ignore[attr-defined]
            return {"CANCELLED"}
        delivered = self.received_from.strip() or None  # type: ignore[attr-defined]
        reason = self.reason.strip() or None  # type: ignore[attr-defined]
        plan = _Survey(None, control=control, received_at=received_at,  # type: ignore[arg-type]
                       received_from=delivered, reason=reason, **plan_values)
        handle = self.begin(context, settings=_survey_settings(plan), executor="job_thread")
        if handle is None:
            return {"CANCELLED"}
        plan.handle = handle
        if _start_survey(plan, self.launch_job) is None:
            return {"CANCELLED"}
        text = tr("Importing «{name}» in the background…", name=plan.name)
        self.report({"INFO"}, text)  # type: ignore[attr-defined]
        return {"FINISHED"}


def _open_wizard(idname: str, values: Mapping[str, Any]) -> None:
    """Abre el asistente de la orden ``idname`` con ``values`` (tras elegir el fichero); sin
    ventana, nada (lo dice el error de quien lo pide)."""
    manager = getattr(bpy.context, "window_manager", None)
    windows = list(getattr(manager, "windows", ()) or ())
    if not windows:
        return
    group, name = idname.split(".")

    def call() -> None:
        try:
            with bpy.context.temp_override(window=windows[0]):
                getattr(getattr(bpy.ops, group), name)("INVOKE_DEFAULT", wizard=True,
                                                       **values)
        except (RuntimeError, TypeError, AttributeError):
            LOGGER.warning("No se pudo abrir el asistente de %s", idname, exc_info=True)

    bpy.app.timers.register(call, first_interval=0.0)


class GEOBLENDER_OT_gis_import_points(_SurveyMixin, ProvenanceAwareOperator,
                                      bpy.types.Operator):
    """Survey points and breaklines (CSV, TXT, XYZ)"""

    bl_idname = IMPORT_POINTS
    bl_label = "Points and breaklines…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.IMPORT_POINTS

    filepath: StringProperty(  # type: ignore[valid-type]
        name="File", subtype="FILE_PATH", options={"SKIP_SAVE"},
    )
    filter_glob: StringProperty(  # type: ignore[valid-type]
        default="*.csv;*.txt;*.xyz", options={"HIDDEN"},
    )
    name: StringProperty(  # type: ignore[valid-type]
        name="Name", description="Logical name of the input", options={"SKIP_SAVE"},
    )
    encoding: EnumProperty(  # type: ignore[valid-type]
        name="Encoding", items=ENCODING_ITEMS, default="UTF8", options={"SKIP_SAVE"},
    )
    separator: EnumProperty(  # type: ignore[valid-type]
        name="Separator", items=POINT_SEPARATOR_ITEMS, default="SEMICOLON",
        options={"SKIP_SAVE"},
    )
    decimal: EnumProperty(  # type: ignore[valid-type]
        name="Decimal mark", items=DECIMAL_ITEMS, default="POINT", options={"SKIP_SAVE"},
    )
    header: BoolProperty(  # type: ignore[valid-type]
        name="Header", description="The file has a header row with the column names",
        default=True, options={"SKIP_SAVE"},
    )
    header_row: IntProperty(  # type: ignore[valid-type]
        name="Lines before the header", default=0, min=0, options={"SKIP_SAVE"},
    )
    columns: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_gis_column, options={"SKIP_SAVE"},
    )
    line_kind: EnumProperty(  # type: ignore[valid-type]
        name="Breaklines", items=LINE_KIND_ITEMS, default="HARD", options={"SKIP_SAVE"},
    )
    crs: StringProperty(  # type: ignore[valid-type]
        name="Horizontal CRS",
        description="EPSG code of the points' horizontal CRS, such as EPSG:25830",
        options={"SKIP_SAVE"},
    )
    vertical: EnumProperty(  # type: ignore[valid-type]
        name="Vertical CRS", items=VERTICAL_ITEMS, default=UNDECLARED, options={"SKIP_SAVE"},
    )
    received_at: StringProperty(  # type: ignore[valid-type]
        name="Delivery date", description="Delivery day, DD/MM/YYYY (empty: no date)",
        options={"SKIP_SAVE"},
    )
    received_from: StringProperty(  # type: ignore[valid-type]
        name="Delivered by", description="Who delivered the input (empty: nobody recorded)",
        options={"SKIP_SAVE"},
    )
    reason: StringProperty(  # type: ignore[valid-type]
        name="Reason",
        description="Why the input replaces the one imported with the same data and other "
                    "settings",
        options={"SKIP_SAVE"},
    )
    wizard: BoolProperty(options={"HIDDEN", "SKIP_SAVE"})  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context: Any) -> bool:
        return _poll(cls)

    def _read_options(self) -> tuple[str, str, int | None]:
        return (ENCODINGS[self.encoding], POINT_SEPARATORS[self.separator],
                self.header_row if self.header else None)

    def _fill_columns(self, path: Path) -> list[list[str]]:
        """Las columnas del asistente desde la vista previa del fichero (el papel adivinado
        por la cabecera) y sus primeras filas."""
        encoding, separator, header_row = self._read_options()
        table = preview_table(path, encoding=encoding, separator=separator,
                              header_row=header_row)
        count = max([len(table.columns), *(len(row) for row in table.rows)], default=0)
        guessed = {index: role for role, index in guess_columns(table.columns).items()}
        reverse = {role: key for key, role in COLUMN_ROLES.items()}
        self.columns.clear()
        for index in range(count):
            item = self.columns.add()
            item.index = index
            item.name = table.columns[index] if index < len(table.columns) else ""
            item.role = reverse[guessed[index]] if index in guessed else NOT_IMPORTED
        self._preview = [list(row) for row in table.rows]
        return self._preview

    def invoke(self, context: Any, event: Any) -> set[str]:
        self.provenance_dialog = True
        if self.filepath:
            try:
                self._fill_columns(Path(bpy.path.abspath(self.filepath)))
            except (GeoblenderError, OSError, ValueError) as exc:
                self.report({"ERROR"}, error_text(exc))
                return {"CANCELLED"}
            self.wizard = True
            return context.window_manager.invoke_props_dialog(
                self, width=DIALOG_WIDTH, translate=False,
                title=tr("Import of points and breaklines"))
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "name", text=tr("Name"), translate=False)
        for prop, text in (("encoding", tr("Encoding")), ("separator", tr("Separator")),
                           ("decimal", tr("Decimal mark")), ("header", tr("Header")),
                           ("header_row", tr("Lines before the header")),
                           ("line_kind", tr("Breaklines")), ("crs", tr("Horizontal CRS")),
                           ("vertical", tr("Vertical CRS")),
                           ("received_at", tr("Delivery date")),
                           ("received_from", tr("Delivered by"))):
            layout.prop(self, prop, text=text, translate=False)
        if self.wizard:
            layout.prop(self, "reason", text=tr("Reason"), translate=False)
            box = layout.box()
            box.label(text=tr("Columns (preview of the first rows)"), translate=False)
            preview = getattr(self, "_preview", [])
            for item in self.columns:
                sample = " · ".join(row[item.index].strip() for row in preview[:3]
                                    if item.index < len(row))
                shown = f"{item.index + 1}. {item.name}"
                row = box.row()
                row.label(text=shown, translate=False)
                row.label(text=sample, translate=False)
                row.prop(item, "role", text="")

    def execute(self, context: Any) -> set[str]:
        blocked = unavailable_reason()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        project = core_provenance.SESSION.project
        path = Path(bpy.path.abspath(self.filepath)) if self.filepath else None
        if path is None or not path.is_file():
            self.report({"ERROR"}, tr("The file «{file}» does not exist: choose the file to "
                                      "import", file="" if path is None else path.name))
            return {"CANCELLED"}
        if self.provenance_dialog and not self.wizard:
            _open_wizard(IMPORT_POINTS, {
                "filepath": str(path), "name": self.name, "encoding": self.encoding,
                "separator": self.separator, "decimal": self.decimal, "header": self.header,
                "header_row": self.header_row, "line_kind": self.line_kind, "crs": self.crs,
                "vertical": self.vertical, "received_at": self.received_at,
                "received_from": self.received_from})
            return {"CANCELLED"}
        try:
            encoding, separator, header_row = self._read_options()
            mapping = _mapping_of(self.columns)
            if not mapping:
                table = preview_table(path, encoding=encoding, separator=separator,
                                      header_row=header_row)
                mapping = guess_columns(table.columns)
            missing = [axis for axis in ("x", "y", "z") if axis not in mapping]
            if missing:
                raise ValueError(tr("Choose the columns X, Y and Z of «{file}» in the wizard",
                                    file=path.name))
            source = self.name.strip() or path.name
            crs, vertical = Declaration(source, parse_crs(self.crs),
                                        _vertical_choice(self.vertical, project)).require()
            _transform(project, DtmSource(self.name or path.name, content.POINTS_TEXT,
                                          {MAIN_ROLE: path}, crs, vertical, {}))
            settings = {"encoding": encoding, "separator": separator,
                        "decimal": DECIMALS[self.decimal], "header_row": header_row,
                        "columns": {role: mapping.get(role) for role in content.MAPPING_ROLES},
                        "line_kind": LINE_KINDS[self.line_kind]}
        except (GeoblenderError, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        name = self.name.strip() or path.stem
        return self._start(context, {"name": name, "path": path,
                                     "reader": content.POINTS_TEXT.id, "settings": settings,
                                     "crs": crs, "vertical": vertical})


class GEOBLENDER_OT_gis_import_vector(_SurveyMixin, ProvenanceAwareOperator,
                                      bpy.types.Operator):
    """Vector layers of a GeoPackage"""

    bl_idname = IMPORT_VECTOR
    bl_label = "Vector layers…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.IMPORT_VECTOR

    filepath: StringProperty(  # type: ignore[valid-type]
        name="File", subtype="FILE_PATH", options={"SKIP_SAVE"},
    )
    filter_glob: StringProperty(  # type: ignore[valid-type]
        default="*.gpkg", options={"HIDDEN"},
    )
    layer: StringProperty(  # type: ignore[valid-type]
        name="Layer", description="Layer of the GeoPackage to import", options={"SKIP_SAVE"},
    )
    layers: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_view_dataset, options={"SKIP_SAVE"},
    )
    role: EnumProperty(  # type: ignore[valid-type]
        name="Role", items=LAYER_ROLE_ITEMS, default="POINTS", options={"SKIP_SAVE"},
    )
    elevation_field: StringProperty(  # type: ignore[valid-type]
        name="Elevation field",
        description="Field with the elevation of each contour line (empty: the Z of its "
                    "vertices)",
        options={"SKIP_SAVE"},
    )
    crs: StringProperty(  # type: ignore[valid-type]
        name="Horizontal CRS",
        description="EPSG code of the layer's horizontal CRS, such as EPSG:25830 (empty: the "
                    "one the layer declares)",
        options={"SKIP_SAVE"},
    )
    vertical: EnumProperty(  # type: ignore[valid-type]
        name="Vertical CRS", items=VERTICAL_ITEMS, default=UNDECLARED, options={"SKIP_SAVE"},
    )
    name: StringProperty(  # type: ignore[valid-type]
        name="Name", description="Logical name of the input", options={"SKIP_SAVE"},
    )
    received_at: StringProperty(  # type: ignore[valid-type]
        name="Delivery date", description="Delivery day, DD/MM/YYYY (empty: no date)",
        options={"SKIP_SAVE"},
    )
    received_from: StringProperty(  # type: ignore[valid-type]
        name="Delivered by", description="Who delivered the input (empty: nobody recorded)",
        options={"SKIP_SAVE"},
    )
    reason: StringProperty(  # type: ignore[valid-type]
        name="Reason",
        description="Why the input replaces the one imported with the same data and other "
                    "settings",
        options={"SKIP_SAVE"},
    )
    wizard: BoolProperty(options={"HIDDEN", "SKIP_SAVE"})  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context: Any) -> bool:
        return _poll(cls)

    def _list_layers(self, path: Path) -> None:
        """Las capas del GeoPackage, leídas de una copia en ``cache/import/`` (nunca del
        fichero de la persona, RF-006-10), en las filas del diálogo."""
        project = core_provenance.SESSION.project
        folder = vector.import_dir(project.cache_dir(), f"capas-{uuid.uuid4().hex[:8]}")
        try:
            found = vector.list_layers(vector.copy_source(path, folder))
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        self.layers.clear()
        for info in found:
            item = self.layers.add()
            item.name = info.name
            item.uid = info.name
            item.label = (f"{info.name} · {info.geometry_type} · {info.srs}"
                          + ("" if info.importable else f" · {info.problem}"))
        if found and not self.layer:
            self.layer = next((info.name for info in found if info.importable), found[0].name)

    def invoke(self, context: Any, event: Any) -> set[str]:
        self.provenance_dialog = True
        if self.filepath:
            try:
                self._list_layers(Path(bpy.path.abspath(self.filepath)))
            except (GeoblenderError, OSError, ValueError) as exc:
                self.report({"ERROR"}, error_text(exc))
                return {"CANCELLED"}
            self.wizard = True
            return context.window_manager.invoke_props_dialog(
                self, width=DIALOG_WIDTH, translate=False, title=tr("Import of a vector layer"))
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.use_property_split = True
        if self.wizard:
            layout.prop_search(self, "layer", self, "layers", text=tr("Layer"),
                               translate=False)
        layout.prop(self, "role", text=tr("Role"), translate=False)
        if self.role == "CONTOURS":
            layout.prop(self, "elevation_field", text=tr("Elevation field"), translate=False)
        for prop, text in (("name", tr("Name")), ("crs", tr("Horizontal CRS")),
                           ("vertical", tr("Vertical CRS")),
                           ("received_at", tr("Delivery date")),
                           ("received_from", tr("Delivered by"))):
            layout.prop(self, prop, text=text, translate=False)
        if self.wizard:
            layout.prop(self, "reason", text=tr("Reason"), translate=False)

    def execute(self, context: Any) -> set[str]:
        blocked = unavailable_reason()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        project = core_provenance.SESSION.project
        path = Path(bpy.path.abspath(self.filepath)) if self.filepath else None
        if path is None or not path.is_file():
            self.report({"ERROR"}, tr("The file «{file}» does not exist: choose the file to "
                                      "import", file="" if path is None else path.name))
            return {"CANCELLED"}
        if self.provenance_dialog and not self.wizard:
            _open_wizard(IMPORT_VECTOR, {
                "filepath": str(path), "layer": self.layer, "role": self.role,
                "elevation_field": self.elevation_field, "crs": self.crs,
                "vertical": self.vertical, "name": self.name,
                "received_at": self.received_at, "received_from": self.received_from})
            return {"CANCELLED"}
        try:
            layer = self.layer.strip()
            if not layer:
                raise ValueError(tr("Choose the layer of «{file}» to import", file=path.name))
            vertical = _declared_vertical(self.vertical, project, self.name.strip() or layer)
            crs = parse_crs(self.crs)
            role = LAYER_ROLES[self.role]
            settings: dict[str, Any] = {"layer": layer, "role": role}
            field = self.elevation_field.strip()
            if role == "contours" and field:
                settings["elevation_field"] = field
            if crs is not None:
                _transform(project, DtmSource(layer, content.GPKG_LAYER, {MAIN_ROLE: path},
                                              crs, vertical, {}))
        except (GeoblenderError, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        name = self.name.strip() or layer
        return self._start(context, {"name": name, "path": path,
                                     "reader": content.GPKG_LAYER.id, "settings": settings,
                                     "crs": crs, "vertical": vertical})


# --- TIN y conversiones (T29) ----------------------------------------------------------------


ANNOUNCE_S = 1.0
"""Una triangulación en el hilo estimada en más (s) se avisa antes en la barra de estado y
corre en el paso siguiente del temporizador (RNF-006-09, D-12)."""
TRIANGULATION_TICK_S = 0.05
"""Lo que espera el temporizador entre el aviso y la triangulación (la barra se redibuja)."""
WORK_DIR = "gis"
"""La carpeta de la caché del proyecto con los ficheros de una cadena de un TIN mientras dura
(``cache/gis/tin-<operación8>/``, en disco local también con el proyecto en red)."""
POLICY_ITEMS = [
    ("ASK", "Ask", "List the conflicts and do not create the TIN"),
    ("MEAN", "Mean", "The mean elevation of the coincident points"),
    ("MIN", "Minimum", "The point with the lowest elevation"),
    ("MAX", "Maximum", "The point with the highest elevation"),
    ("FIRST", "First", "The first point of the file"),
    ("CANCEL", "Cancel", "Do not create the TIN if there are conflicts"),
]
POLICIES: Mapping[str, str] = {key: key.lower() for key, *_ in POLICY_ITEMS}
DIRECTION_ITEMS = [
    ("DTM_TO_TIN", "DTM → TIN", "Triangulate the centres of the cells with data"),
    ("TIN_TO_DTM", "TIN → DTM", "Interpolate the TIN at the centres of the project grid"),
]
_TIN_POINTS = "points"
_TIN_CONTOURS = "contours"


@dataclass(eq=False)
class _Tin:
    """Una cadena de un TIN o una conversión en marcha (una sola operación aunque lance varios
    trabajos; se incorpora el último): su operación, su tipo (``points``, ``contours``,
    ``grid_to_tin`` o ``tin_to_grid``), el nombre del resultado, sus ajustes, su carpeta de
    trabajo y lo que se va sabiendo (vértices, dónde se triangula, el triangulador y las
    notas del informe)."""

    handle: OperationHandle
    kind: str
    name: str
    settings: Mapping[str, Any]
    work: Path | None = None
    regions: bool = False
    vertices: int = 0
    choice: Any = None
    announced: bool = False
    triangulator: str = ""
    notes: list[str] = field(default_factory=list)


_TRIANGULATIONS: list[_Tin] = []
"""Las triangulaciones con la CDT de Blender que esperan su turno en el temporizador."""


def pending_triangulations() -> list[str]:
    """Las operaciones cuya triangulación con la CDT de Blender espera el temporizador."""
    return [plan.handle.uid for plan in _TRIANGULATIONS]


def _status(text: str | None) -> None:
    """El aviso en la barra de estado de cada ventana (``None`` lo quita)."""
    manager = getattr(bpy.context, "window_manager", None)
    for window in list(getattr(manager, "windows", ()) or ()):
        workspace = getattr(window, "workspace", None)
        if workspace is None:
            continue
        try:
            workspace.status_text_set(text)
        except (RuntimeError, TypeError):
            LOGGER.debug("Sin barra de estado en una ventana", exc_info=True)


def _work_dir(handle: OperationHandle) -> Path:
    """La carpeta de trabajo de la cadena de ``handle`` (en la caché del proyecto)."""
    folder = Path(handle.project.cache_dir(), WORK_DIR, f"tin-{handle.uid.partition('-')[0]}")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _discard_work(plan: _Tin) -> None:
    if plan.work is not None:
        shutil.rmtree(plan.work, ignore_errors=True)


def _abort(plan: _Tin, error: BaseException, result: JobResult | None = None) -> None:
    """Deja fallida con su motivo la operación de ``plan`` (si sigue en curso), da por
    incorporado su trabajo ``result`` (si lo hay), borra su carpeta de trabajo y lo dice."""
    if result is not None:
        reason = _failure(plan.handle, result, error)
    else:
        reason = error_text(error)
        LOGGER.warning("La operación «%s» (%s) no terminó", plan.handle.op_type,
                       plan.handle.uid, exc_info=error)
        try:
            plan.handle.fail(reason)
        except (GeoblenderError, TypeError, ValueError):
            pass
    _discard_work(plan)
    _say(tr("TIN «{name}» has not been created: {reason}", name=plan.name, reason=reason))


def _record(project: Any, ref: str, families: Sequence[str]) -> DatasetRecord:
    """El dato vivo ``ref`` (nombre o uid) de una de ``families`` de ``gis``;
    ``gis.dataset_unknown`` si no lo hay."""
    shown = ref.strip()
    with project.read() as conn:
        record = dataset_registry.get(conn, shown) if shown else None
    prefixes = tuple(provenance.FAMILIES_BY_CODE[code].prefix for code in families)
    if record is None or record.module != MODULE or not record.name.startswith(prefixes):
        raise GisError("gis.dataset_unknown", obj="Dato de topografía", field="dato",
                       value=ref)
    return record


def _require_project_references(project: Any, record: DatasetRecord) -> None:
    """Una superficie que se convierte, se contornea o se valida, en el CRS y la referencia
    vertical del proyecto (lo calculado sale en ellos y la ventana de trabajo es suya); si no,
    ``gis.surface_references_mismatch`` nombrando los dos."""
    found = store.dataset_references(project, record)
    expected = store.project_references(project)
    if found != expected:
        raise GisError("gis.surface_references_mismatch", obj=f"«{record.name}»",
                       field="CRS", value=reference_label(*found), name=record.name,
                       expected=reference_label(*expected))


def _to_project(project: Any, record: DatasetRecord, arrays: list[np.ndarray],
                notes: list[str]) -> list[np.ndarray]:
    """Las coordenadas ``arrays`` del dato ``record`` (``(n, 2)`` o ``(n, 3)``) en el CRS y la
    referencia vertical del proyecto: las mismas si ya lo están; si no, transformadas con una
    de precisión conocida (RF-006-05; si no la hay, ``GisError`` nombrando los dos CRS), con
    la transformación en ``notes`` (para el informe)."""
    crs, vertical = store.dataset_references(project, record)
    target_crs, target_vertical = store.project_references(project)
    if not needs_transform(crs, vertical, target_crs, target_vertical):
        return arrays
    transform = transformation_for(Declaration(record.name, crs, vertical), target_crs,
                                   target_vertical, resolver=crs_resolver)
    assert transform is not None
    notes.append(tr("«{name}» transformed from {source} to {target}: {transform}",
                    name=record.name, source=reference_label(crs, vertical),
                    target=reference_label(target_crs, target_vertical),
                    transform=transform_summary(transform.info)))
    found: list[np.ndarray] = []
    for array in arrays:
        xyz = (array if array.shape[1] == 3
               else np.column_stack([array, np.zeros(len(array), dtype=np.float64)]))
        moved = np.ascontiguousarray(transform.apply(xyz), dtype=np.float64)
        found.append(moved if array.shape[1] == 3 else np.ascontiguousarray(moved[:, :2]))
    return found


def _points_of(project: Any, record: DatasetRecord, notes: list[str]) -> PointSet:
    points = store.load_points(project, record)
    (xyz,) = _to_project(project, record, [points.xyz], notes)
    return PointSet(xyz, points.point_ids, points.codes, points.source_rows)


def _lines_of(project: Any, record: DatasetRecord, notes: list[str]) -> list[Breakline]:
    lines = store.load_lines(project, record)
    moved = _to_project(project, record, [line.xyz for line in lines], notes)
    return [Breakline(line.line_id, xyz, hard=line.hard, code=line.code)
            for line, xyz in zip(lines, moved, strict=True)]


def _regions_of(project: Any, record: DatasetRecord, notes: list[str],
                ) -> tuple[list[np.ndarray], list[list[np.ndarray]]]:
    """Los anillos del contorno (todos los de sus polígonos: dentro, por paridad) y los de
    cada hueco del dato ``record``, en las referencias del proyecto."""
    polygons, holes = store.load_regions(project, record)
    rings = [ring for polygon in polygons for ring in polygon]
    hole_rings = [[ring for polygon in hole for ring in polygon] for hole in holes]
    flat = _to_project(project, record, [*rings, *(r for hole in hole_rings for r in hole)],
                       notes)
    boundary, position = flat[:len(rings)], len(rings)
    found: list[list[np.ndarray]] = []
    for hole in hole_rings:
        found.append(flat[position:position + len(hole)])
        position += len(hole)
    return boundary, found


def _tin_settings(name: str, uses: Mapping[str, DatasetRecord],
                  extra: Mapping[str, Any]) -> dict[str, Any]:
    """Los ajustes de la operación de un TIN: su nombre, lo que consume (por papel, el nombre
    del dato) y los de la orden (``extra``)."""
    return {"name": name, "sources": {role: record.name for role, record in uses.items()},
            **dict(extra)}


def _start_tin(plan: _Tin, launch: Callable[..., Any],
               uses: Mapping[str, DatasetRecord]) -> Any:
    """Lee lo que consume el TIN de ``plan`` (puntos, líneas o curvas y contorno; en las
    referencias del proyecto), lo deja en su carpeta de trabajo y lanza con ``launch`` su
    primer trabajo: ``gis_tin_prepare`` (desde puntos) o ``gis_tin_contours`` (desde
    curvas)."""
    project = plan.handle.project
    plan.work = _work_dir(plan.handle)
    inputs: dict[str, Path] = {}
    arrays: dict[str, np.ndarray] = {}
    count = 0
    if _TIN_POINTS in uses or "spot_heights" in uses:
        record = uses.get(_TIN_POINTS) or uses["spot_heights"]
        points = _points_of(project, record, plan.notes)
        if plan.kind == _TIN_POINTS:  # en in/ del trabajo, sin copia (T35, RNF-006-09)
            arrays.update(jobs.point_inputs(points))
        else:
            jobs.write_points(plan.work / "points.npz", points)
            inputs[jobs.INPUT_POINTS] = plan.work / "points.npz"
        count += len(points)
    line_role = "breaklines" if plan.kind == _TIN_POINTS else _TIN_CONTOURS
    if line_role in uses:
        lines = _lines_of(project, uses[line_role], plan.notes)
        jobs.write_lines(plan.work / "lines.npz", lines)
        inputs[jobs.INPUT_LINES] = plan.work / "lines.npz"
        count += sum(len(line.xyz) for line in lines)
    if "boundary" in uses:
        boundary, holes = _regions_of(project, uses["boundary"], plan.notes)
        if plan.kind == _TIN_CONTOURS:  # el TIN desde curvas no tiene huecos: por paridad
            boundary, holes = boundary + [ring for hole in holes for ring in hole], []
        jobs.write_regions(plan.work / "regions.npz", boundary or None, holes)
        plan.regions = True
    resolved = _resolved(plan.handle)
    settings = plan.settings
    if plan.kind == _TIN_POINTS:
        params = {"name": plan.name, "tol_xy": resolved[DUP_XY_KEY],
                  "tol_z": resolved[DUP_Z_KEY], "duplicate_policy": settings["duplicate_policy"],
                  "count": count}
        return launch(plan.handle, jobs.TIN_PREPARE, label=tr("TIN «{name}»", name=plan.name),
                      params=params, inputs=inputs, arrays=arrays,
                      on_finish=functools.partial(_tin_prepared, plan),
                      grace_s=jobs.CANCEL_GRACE_S)
    if plan.regions:
        inputs[jobs.INPUT_REGIONS] = plan.work / "regions.npz"
    crs, vertical = store.project_references(project)
    params = {"name": plan.name, "origin": jobs.origin_json(project.origin),
              "crs": jobs.crs_json(crs), "vertical": jobs.vertical_json(vertical),
              "densify_m": settings.get("densify_m", resolved.get(DENSIFY_KEY)),
              "max_passes": resolved[PASSES_KEY], "max_flat_pct": resolved[MAX_FLAT_KEY],
              "tol_xy": resolved[DUP_XY_KEY], "tol_z": resolved[DUP_Z_KEY],
              "duplicate_policy": settings["duplicate_policy"], "count": count}
    return launch(plan.handle, jobs.TIN_CONTOURS, label=tr("TIN «{name}»", name=plan.name),
                  params=params, inputs=inputs, on_finish=functools.partial(_tin_finished, plan),
                  grace_s=jobs.CANCEL_GRACE_S)


def _conflicts(plan: _Tin, result: JobResult, outcome: Any) -> None:
    """Un TIN con conflictos sin resolver (RF-006-14): cada uno en los avisos, con sus
    identificadores, su posición y sus dos cotas; la operación queda cancelada (si se eligió
    cancelar) o fallida con el motivo y la lista; ningún dato."""
    error = jobs.read_conflicts(outcome.file(jobs.OUT_CONFLICTS.role))
    texts = error.texts(i18n.language())
    shown = texts[:CONFLICTS_SHOWN]
    if len(texts) > CONFLICTS_SHOWN:
        shown.append(tr("… and {count} more conflicts", count=format_number(
            len(texts) - CONFLICTS_SHOWN, 0)))
    reason = "\n".join([error.text, *shown])
    for text in (error.text, *shown):
        _say(text)
    try:
        if error.code == "gis.duplicates_cancelled":
            plan.handle.cancel(reason)
        else:
            plan.handle.fail(reason)
    finally:
        core_provenance.release_job(result.job_uid)
        _discard_work(plan)


def _tin_prepared(plan: _Tin, result: JobResult) -> None:
    """El final de ``gis_tin_prepare``: con conflictos, :func:`_conflicts`; si no, lo
    preparado pasa a la carpeta de trabajo y se triangula con la CDT de Blender desde el
    temporizador si la estimación no pasa del umbral del proyecto
    (``gis.tin.blender_cdt_max_s``) o, si pasa, en el trabajo ``gis_triangulate``."""
    if result.state != _SUCCEEDED:
        _discard_work(plan)
        return
    try:
        outcome = job_outcome(result, result.job_dir)
        summary = outcome.summary
        if summary.get("conflicts"):
            _conflicts(plan, result, outcome)
            return
        assert plan.work is not None
        shutil.copyfile(outcome.file(jobs.OUT_PREPARED.role), plan.work / "prepared.npz")
        plan.vertices = int(summary["vertices"])
        core_provenance.release_job(result.job_uid)
        limit = plan.settings["control"][cdt_blender.MAX_SECONDS_KEY]
        plan.choice = cdt_blender.choose_triangulation(plan.vertices, limit_s=limit)
        if plan.choice.in_process:
            _TRIANGULATIONS.append(plan)
            if not bpy.app.timers.is_registered(triangulation_tick):
                bpy.app.timers.register(triangulation_tick, first_interval=0.0,
                                        persistent=True)
        else:
            _launch_triangulate(plan)
    except Exception as error:  # noqa: BLE001 - la operación queda fallida con el motivo
        _abort(plan, error, result)


def triangulation_tick() -> float | None:
    """El temporizador de las triangulaciones con la CDT de Blender (plan §5.3.4, A10, D-12):
    una por paso; si se estima en más de :data:`ANNOUNCE_S`, primero el aviso en la barra de
    estado y en los avisos («Triangulando n puntos (unos t s)…») y la triangulación en el
    paso siguiente. Devuelve cuándo volver (``None``: no queda ninguna)."""
    if not _TRIANGULATIONS:
        return None
    plan = _TRIANGULATIONS[0]
    if plan.choice.estimate_s > ANNOUNCE_S and not plan.announced:
        plan.announced = True
        text = tr("Triangulating {count} points (about {seconds} s)…",
                  count=format_number(plan.vertices, 0),
                  seconds=_decimal(round(plan.choice.estimate_s, 1)))
        _status(text)
        _say(text)
        return TRIANGULATION_TICK_S
    _TRIANGULATIONS.pop(0)
    try:
        _triangulate_here(plan)
    finally:
        if plan.announced:
            _status(None)
    return TRIANGULATION_TICK_S if _TRIANGULATIONS else None


def _triangulate_here(plan: _Tin) -> None:
    """La CDT de Blender en el hilo principal con lo preparado (coordenadas locales respecto
    al GeoOrigin) y, después, ``gis_tin_finish`` con lo preparado y los triángulos escritos en
    su ``in/`` sin copia (T35). Si no cumple su contrato (``gis.triangulation_contract``), se
    repite con ``PureTriangulator`` en ``gis_triangulate``."""
    try:
        if core_provenance.SESSION.project is not plan.handle.project:
            raise GisError("gis.tin_project_closed", obj=f"TIN «{plan.name}»",
                           field="proyecto", value=plan.handle.project.name, tin=plan.name)
        assert plan.work is not None
        source = jobs.read_tin_input(plan.work / "prepared.npz")
        xy = world_to_local(source.prepared.xyz[:, :2], plan.handle.project.origin)
        try:
            faces = cdt_blender.BlenderTriangulator().triangulate(xy, source.prepared.edges)
        except TriangulationError as error:
            plan.notes.append(tr("The Blender triangulation did not fulfil its contract "
                                 "({reason}): repeated with the pure triangulator",
                                 reason=error_text(error)))
            _launch_triangulate(plan)
            return
        plan.triangulator = cdt_blender.NAME
        _launch_finish(plan, faces, source)
    except Exception as error:  # noqa: BLE001 - la operación queda fallida con el motivo
        _abort(plan, error)


def _launch_triangulate(plan: _Tin) -> None:
    """``gis_triangulate`` (``PureTriangulator`` en proceso aparte, con avance y
    cancelación) con lo preparado."""
    assert plan.work is not None
    core_provenance.launch_job(
        plan.handle, jobs.TRIANGULATE, label=tr("TIN «{name}»", name=plan.name),
        params={"name": plan.name, "origin": jobs.origin_json(plan.handle.project.origin),
                "count": plan.vertices},
        inputs={jobs.INPUT_PREPARED: plan.work / "prepared.npz"},
        on_finish=functools.partial(_tin_triangulated, plan), grace_s=jobs.CANCEL_GRACE_S)


def _tin_triangulated(plan: _Tin, result: JobResult) -> None:
    """El final de ``gis_triangulate``: sus triángulos a la carpeta de trabajo y
    ``gis_tin_finish``."""
    if result.state != _SUCCEEDED:
        _discard_work(plan)
        return
    try:
        outcome = job_outcome(result, result.job_dir)
        with open(outcome.file(jobs.OUT_FACES.role), "rb") as stream:
            faces = np.load(stream, allow_pickle=False)
        plan.triangulator = str(outcome.summary["triangulator"])
        core_provenance.release_job(result.job_uid)
        _launch_finish(plan, faces)
    except Exception as error:  # noqa: BLE001 - la operación queda fallida con el motivo
        _abort(plan, error, result)


def _launch_finish(plan: _Tin, faces: np.ndarray, source: Any = None) -> None:
    """``gis_tin_finish``: orientación, contorno, huecos, lado máximo y estadísticas, con lo
    preparado (``source``; si no, el de la carpeta de trabajo) y los triángulos ``faces``
    escritos en su ``in/`` sin copia (``arrays``, T35)."""
    assert plan.work is not None
    project = plan.handle.project
    crs, vertical = store.project_references(project)
    if source is None:
        source = jobs.read_tin_input(plan.work / "prepared.npz")
    arrays = {**jobs.tin_inputs(source),
              jobs.INPUT_FACES: np.ascontiguousarray(faces, dtype=np.int32)}
    inputs = {jobs.INPUT_REGIONS: plan.work / "regions.npz"} if plan.regions else {}
    core_provenance.launch_job(
        plan.handle, jobs.TIN_FINISH, label=tr("TIN «{name}»", name=plan.name),
        params={"name": plan.name, "origin": jobs.origin_json(project.origin),
                "triangulator": plan.triangulator,
                "max_edge_m": plan.settings.get("max_edge_m"), "crs": jobs.crs_json(crs),
                "vertical": jobs.vertical_json(vertical), "count": plan.vertices},
        inputs=inputs, arrays=arrays, on_finish=functools.partial(_tin_finished, plan),
        grace_s=jobs.CANCEL_GRACE_S)


def _tin_report(plan: _Tin, outcome: Any) -> str:
    """El informe de un TIN (RF-006-13 a RF-006-16): vértices, triángulos, aristas
    obligatorias, triángulos planos (antes y después, en uno desde curvas), puntos añadidos,
    lado máximo, degenerados, lo quitado por el contorno y el lado máximo, el triangulador y
    las transformaciones."""
    report = json.loads(outcome.file(jobs.OUT_REPORT.role).read_text("utf-8"))
    lines = [tr("TIN «{name}» ({dataset}): {vertices} vertices, {triangles} triangles, "
                "{constraints} constraint edges; flat triangles {flat} %, longest side {side} "
                "m, degenerate {degenerate}; triangulator {triangulator}",
                name=plan.name, dataset=provenance.dataset_name(provenance.TIN, plan.name),
                vertices=format_number(int(report["vertices"]), 0),
                triangles=format_number(int(report["triangles"]), 0),
                constraints=format_number(int(report["constraint_edges"]), 0),
                flat=format_number(float(report["flat_pct"]), 2),
                side=format_number(float(report["max_edge_m"]), 3),
                degenerate=format_number(int(report["degenerate"]), 0),
                triangulator=report["triangulator"])]
    if report.get("duplicates_merged"):
        lines.append(tr("Duplicate points merged: {count}", count=format_number(
            int(report["duplicates_merged"]), 0)))
    if report.get("removed_outside") or report.get("removed_long_edges"):
        lines.append(tr("Triangles removed by the boundary and the holes: {outside}; by the "
                        "longest side: {long}",
                        outside=format_number(int(report.get("removed_outside", 0)), 0),
                        long=format_number(int(report.get("removed_long_edges", 0)), 0)))
    before = report.get("flat_pct_before")
    if plan.kind == _TIN_CONTOURS:
        lines.append(tr("Flat triangles before the correction: {before} %; after: {after} %; "
                        "points added: {added}",
                        before="—" if before is None else format_number(float(before), 2),
                        after=format_number(float(report["flat_pct"]), 2),
                        added=format_number(int(report.get("points_added", 0)), 0)))
    lines.extend([*plan.notes, *(str(note) for note in report.get("notes", ()))])
    return "\n".join(lines)


def _tin_finished(plan: _Tin, result: JobResult) -> None:
    """El final del último trabajo de la cadena (``gis_tin_finish`` o ``gis_tin_contours``):
    con conflictos, :func:`_conflicts`; si no, el TIN pasa a ``gis_tin_<nombre>`` con su hash
    y el triangulador usado en ``software`` (RF-006-26), y se incorpora la operación."""
    if result.state != _SUCCEEDED:
        _discard_work(plan)
        return
    try:
        outcome = job_outcome(result, result.job_dir)
        summary = outcome.summary
        if summary.get("conflicts"):
            _conflicts(plan, result, outcome)
            return
        plan.triangulator = plan.triangulator or str(summary["triangulator"])
        report = _tin_report(plan, outcome)
        role = jobs.OUT_TIN.role
        with store.ResultWriter(plan.handle.project, plan.handle) as out:
            out.copy_file(provenance.TIN, plan.name, outcome.file(role),
                          content=jobs.digest_of(summary["outputs"][role]["digest"]),
                          sha256=outcome.output(role).sha256)
            core_provenance.ingest_job_result(
                plan.handle, result, out.write,
                software={provenance.TRIANGULATOR: plan.triangulator}, message=report)
    except Exception as error:  # noqa: BLE001 - la operación queda fallida con el motivo
        _abort(plan, error, result)
        return
    _discard_work(plan)
    _say(report)


def _tin_inputs(operator: Any, roles: Sequence[tuple[str, str, Sequence[str]]],
                project: Any) -> dict[str, DatasetRecord]:
    """Los datos que consume un TIN, por papel, de las propiedades del operador (``roles``:
    papel, propiedad y familias); los vacíos no cuentan."""
    found: dict[str, DatasetRecord] = {}
    for role, prop, families in roles:
        ref = str(getattr(operator, prop)).strip()
        if ref:
            found[role] = _record(project, ref, families)
    return found


def _default_name(records: Sequence[DatasetRecord]) -> str:
    """El nombre por defecto de un resultado: el del primer dato que consume, sin su
    familia."""
    for record in records:
        for family in provenance.FAMILIES:
            if record.name.startswith(family.prefix):
                return record.name.removeprefix(family.prefix)
    return ""


def _max_edge(text: str, name: str) -> float | None:
    """El lado máximo tecleado (m, coma o punto) o ``None``; ``gis.tin_max_edge_invalid``
    si no es un número positivo."""
    if not text.strip():
        return None
    value = parse_decimal(text, obj=tr("Longest side"), field="max_edge")
    if not (math.isfinite(value) and value > 0.0):
        raise GisError("gis.tin_max_edge_invalid", obj=f"TIN «{name}»", field="lado máximo",
                       value=value, tin=name)
    return float(value)


def _fill_items(operator: Any, families: Sequence[str],
                project: Any = None) -> list[DatasetRecord]:
    """Las filas del diálogo de una orden: los datos de ``families`` de ``project`` (por
    defecto, el de la sesión de la procedencia)."""
    records = store.list_gis_datasets(project or core_provenance.SESSION.project,
                                      families=families)
    operator.items.clear()
    for record in records:
        item = operator.items.add()
        item.name = record.name
        item.uid = record.uid
        item.label = record.name
    return records


def _first(records: Sequence[DatasetRecord], family: str) -> str:
    prefix = provenance.FAMILIES_BY_CODE[family].prefix
    return next((record.name for record in reversed(records)
                 if record.name.startswith(prefix)), "")


def _begin_tin(operator: Any, context: Any, kind: str, uses: Mapping[str, DatasetRecord],
               settings: dict[str, Any], params: list[str]) -> _Tin | None:
    """La puerta y la operación «en curso» de un TIN (la de ``operator``) con lo que consume,
    sus ajustes y los parámetros de resultado que lee."""
    operator._uses = tuple(Use(record.uid, role) for role, record in uses.items())
    handle = operator.begin(context, settings=settings, params=params, executor="job_thread")
    if handle is None:
        return None
    return _Tin(handle, kind, str(settings["name"]), settings)


def _launch_first(operator: Any, plan: _Tin, uses: Mapping[str, DatasetRecord]) -> set[str]:
    try:
        job = _start_tin(plan, operator.launch_job, uses)
    except (GeoblenderError, OSError, ValueError) as exc:
        _abort(plan, exc)
        operator.report({"ERROR"}, error_text(exc))
        return {"CANCELLED"}
    if job is None:
        _discard_work(plan)
        return {"CANCELLED"}
    operator.report({"INFO"}, tr("Creating the TIN «{name}» in the background…",
                                 name=plan.name))
    return {"FINISHED"}


class _TinMixin:
    """Lo común de las órdenes de un TIN: lo que consumen (``_uses``) y su diálogo."""

    def provenance_inputs(self, context: Any) -> tuple[Use, ...]:
        return tuple(getattr(self, "_uses", ()))

    @classmethod
    def poll(cls, context: Any) -> bool:
        return _poll(cls)


class GEOBLENDER_OT_gis_create_tin_from_points(_TinMixin, ProvenanceAwareOperator,
                                               bpy.types.Operator):
    """Triangulated surface from points and breaklines. In RecMin, T3"""

    bl_idname = TIN_FROM_POINTS
    bl_label = "TIN from points and breaklines…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.TIN_FROM_POINTS

    points: StringProperty(  # type: ignore[valid-type]
        name="Points", description="Name or uid of the imported points", options={"SKIP_SAVE"},
    )
    breaklines: StringProperty(  # type: ignore[valid-type]
        name="Breaklines", description="Name or uid of the imported breaklines (optional)",
        options={"SKIP_SAVE"},
    )
    boundary: StringProperty(  # type: ignore[valid-type]
        name="Boundary", description="Name or uid of the imported boundary (optional)",
        options={"SKIP_SAVE"},
    )
    max_edge: StringProperty(  # type: ignore[valid-type]
        name="Longest side",
        description="Triangles with a longer side in plan are removed, m (empty: none)",
        options={"SKIP_SAVE"},
    )
    duplicate_policy: EnumProperty(  # type: ignore[valid-type]
        name="Coincident points", items=POLICY_ITEMS, default="ASK", options={"SKIP_SAVE"},
    )
    name: StringProperty(  # type: ignore[valid-type]
        name="Name", description="Name of the TIN (empty: the points')", options={"SKIP_SAVE"},
    )
    items: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_view_dataset, options={"SKIP_SAVE"},
    )

    def invoke(self, context: Any, event: Any) -> set[str]:
        self.provenance_dialog = True
        if self.points or self.breaklines:
            return self.execute(context)
        try:
            records = _fill_items(self, (provenance.POINTS, provenance.BREAKLINES,
                                         provenance.BOUNDARY))
        except GeoblenderError as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        if not any(record.name.startswith(("gis_pts_", "gis_brk_")) for record in records):
            path = path_text(command_catalog(), IMPORT_POINTS, i18n.language())
            self.report({"ERROR"}, tr("First {step} ({path})", step=tr("import points"),
                                      path=path))
            return {"CANCELLED"}
        self.points = _first(records, provenance.POINTS)
        self.breaklines = _first(records, provenance.BREAKLINES)
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False,
            title=tr("TIN from points and breaklines"))

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.use_property_split = True
        for prop, text in (("points", tr("Points")), ("breaklines", tr("Breaklines")),
                           ("boundary", tr("Boundary"))):
            layout.prop_search(self, prop, self, "items", text=text, translate=False)
        layout.prop(self, "max_edge", text=tr("Longest side"), translate=False)
        layout.prop(self, "duplicate_policy", text=tr("Coincident points"), translate=False)
        layout.prop(self, "name", text=tr("Name"), translate=False)

    def execute(self, context: Any) -> set[str]:
        blocked = unavailable_reason()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        project = core_provenance.SESSION.project
        try:
            uses = _tin_inputs(self, (
                (_TIN_POINTS, "points", (provenance.POINTS,)),
                ("breaklines", "breaklines", (provenance.BREAKLINES,)),
                ("boundary", "boundary", (provenance.BOUNDARY,))), project)
            if _TIN_POINTS not in uses and "breaklines" not in uses:
                raise ValueError(tr("Choose the points or the breaklines of the TIN"))
            name = self.name.strip() or _default_name(list(uses.values()))
            provenance.dataset_slug(name)
            settings = _tin_settings(name, uses, {
                "max_edge_m": _max_edge(self.max_edge, name),
                "duplicate_policy": POLICIES[self.duplicate_policy],
                "control": control_values(project, (cdt_blender.MAX_SECONDS_KEY,))})
        except (GeoblenderError, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        plan = _begin_tin(self, context, _TIN_POINTS, uses, settings, list(DUP_KEYS))
        if plan is None:
            return {"CANCELLED"}
        return _launch_first(self, plan, uses)


def densify_field(project: Any) -> tuple[str, str]:
    """El campo de la densificación del diálogo del TIN desde curvas (:func:`param_field`)."""
    return param_field(project, DENSIFY_KEY)


class GEOBLENDER_OT_gis_create_tin_from_contours(_TinMixin, ProvenanceAwareOperator,
                                                 bpy.types.Operator):
    """Triangulated surface from contour lines. In RecMin, from SUP to T3"""

    bl_idname = TIN_FROM_CONTOURS
    bl_label = "TIN from contour lines…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.TIN_FROM_CONTOURS

    contours: StringProperty(  # type: ignore[valid-type]
        name="Contour lines", description="Name or uid of the contour lines",
        options={"SKIP_SAVE"},
    )
    spot_heights: StringProperty(  # type: ignore[valid-type]
        name="Spot heights", description="Name or uid of the imported points (optional)",
        options={"SKIP_SAVE"},
    )
    boundary: StringProperty(  # type: ignore[valid-type]
        name="Boundary", description="Name or uid of the imported boundary (optional)",
        options={"SKIP_SAVE"},
    )
    densify: StringProperty(  # type: ignore[valid-type]
        name="Densification",
        description="Longest segment of a contour line, m (empty or unchanged: the project's "
                    "parameter)",
        options={"SKIP_SAVE"},
    )
    duplicate_policy: EnumProperty(  # type: ignore[valid-type]
        name="Coincident points", items=POLICY_ITEMS, default="ASK", options={"SKIP_SAVE"},
    )
    name: StringProperty(  # type: ignore[valid-type]
        name="Name", description="Name of the TIN (empty: the contour lines')",
        options={"SKIP_SAVE"},
    )
    items: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_view_dataset, options={"SKIP_SAVE"},
    )

    def invoke(self, context: Any, event: Any) -> set[str]:
        self.provenance_dialog = True
        if self.contours:
            return self.execute(context)
        try:
            records = _fill_items(self, (provenance.CONTOUR_LINES, provenance.POINTS,
                                         provenance.BOUNDARY))
        except GeoblenderError as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        self.contours = _first(records, provenance.CONTOUR_LINES)
        if not self.contours:
            path = path_text(command_catalog(), IMPORT_VECTOR, i18n.language())
            self.report({"ERROR"}, tr("First {step} ({path})", step=tr("import contour lines"),
                                      path=path))
            return {"CANCELLED"}
        self.densify, self._densify_note = densify_field(core_provenance.SESSION.project)
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False, title=tr("TIN from contour lines"))

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.use_property_split = True
        for prop, text in (("contours", tr("Contour lines")),
                           ("spot_heights", tr("Spot heights")),
                           ("boundary", tr("Boundary"))):
            layout.prop_search(self, prop, self, "items", text=text, translate=False)
        row = layout.row()
        row.prop(self, "densify", text=tr("Densification"), translate=False)
        row.label(text=getattr(self, "_densify_note", ""), translate=False)
        layout.prop(self, "duplicate_policy", text=tr("Coincident points"), translate=False)
        layout.prop(self, "name", text=tr("Name"), translate=False)

    def execute(self, context: Any) -> set[str]:
        blocked = unavailable_reason()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        project = core_provenance.SESSION.project
        try:
            uses = _tin_inputs(self, (
                (_TIN_CONTOURS, "contours", (provenance.CONTOUR_LINES,)),
                ("spot_heights", "spot_heights", (provenance.POINTS,)),
                ("boundary", "boundary", (provenance.BOUNDARY,))), project)
            if _TIN_CONTOURS not in uses:
                raise ValueError(tr("Choose the contour lines of the TIN"))
            name = self.name.strip() or _default_name([uses[_TIN_CONTOURS]])
            provenance.dataset_slug(name)
            extra: dict[str, Any] = {"duplicate_policy": POLICIES[self.duplicate_policy]}
            params = [*DUP_KEYS, PASSES_KEY, MAX_FLAT_KEY]
            typed = None
            if self.densify.strip():
                typed = gis_params.param(DENSIFY_KEY).check(parse_decimal(
                    self.densify, obj=tr("Densification"), field=DENSIFY_KEY))
            if typed is None or typed == project_value(project, DENSIFY_KEY)[0]:
                params.append(DENSIFY_KEY)  # la del proyecto: se consume (RF-008-05)
            else:
                extra["densify_m"] = typed  # tecleada: un ajuste (D18)
            settings = _tin_settings(name, uses, extra)
        except (GeoblenderError, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        plan = _begin_tin(self, context, _TIN_CONTOURS, uses, settings, params)
        if plan is None:
            return {"CANCELLED"}
        return _launch_first(self, plan, uses)


def recompute_tin(request: RecomputeRequest) -> OperationHandle:
    """El recálculo de ``gis.tin_from_points`` y ``gis.tin_from_contours`` (RF-008-26; plan
    §5.6.8): la misma cadena con los datos vigentes, los parámetros de hoy y los mismos
    ajustes; devuelve la operación nueva, aún «en curso», que sustituye a la antigua."""
    project = request.project
    uses: dict[str, DatasetRecord] = {}
    for use in request.inputs:
        with project.read() as conn:
            record = dataset_registry.get(conn, use.item)
        if record is None:
            raise GisError("gis.dataset_unknown", obj="Dato de topografía", field="dato",
                           value=use.item)
        uses[use.role] = record
    kind = _TIN_POINTS if request.op_type == provenance.TIN_FROM_POINTS else _TIN_CONTOURS
    arguments = request.arguments()
    if kind == _TIN_POINTS:  # los parámetros de control se vuelven a leer del proyecto (D17)
        arguments["settings"] = {**arguments["settings"], "control": control_values(
            project, (cdt_blender.MAX_SECONDS_KEY,))}
    handle = begin_operation(project, request.op_type, executor="job_thread", **arguments)
    plan = _Tin(handle, kind, str(request.settings["name"]), dict(arguments["settings"]))
    try:
        _start_tin(plan, core_provenance.launch_job, uses)
    except (GeoblenderError, OSError, ValueError) as exc:
        _abort(plan, exc)
    return handle


# --- MDT ⇄ TIN ---------------------------------------------------------------------------


def _start_convert(plan: _Tin, launch: Callable[..., Any], record: DatasetRecord) -> Any:
    """Lanza ``gis_convert_surface`` para la conversión de ``plan`` con el fichero de
    ``record`` copiado a ``in/``."""
    project = plan.handle.project
    path = _file_of(project, record)
    crs, vertical = store.project_references(project)
    params: dict[str, Any] = {"name": plan.name, "crs": jobs.crs_json(crs),
                              "vertical": jobs.vertical_json(vertical)}
    if plan.kind == jobs.GRID_TO_TIN:
        params.update(direction=jobs.GRID_TO_TIN, count=path.stat().st_size // 4)
    else:
        target = jobs.grid_of(plan.settings["grid"])
        params.update(direction=jobs.TIN_TO_GRID, target=jobs.grid_json(target),
                      count=target.ncols * target.nrows)
    label = (tr("TIN «{name}»", name=plan.name) if plan.kind == jobs.GRID_TO_TIN
             else tr("Project grid «{name}»", name=plan.name))
    return launch(plan.handle, jobs.CONVERT_SURFACE, label=label, params=params,
                  inputs={jobs.INPUT_SOURCE: path},
                  on_finish=functools.partial(_converted, plan, record),
                  grace_s=jobs.CANCEL_GRACE_S)


def _converted(plan: _Tin, record: DatasetRecord, result: JobResult) -> None:
    """El final de ``gis_convert_surface``: el TIN a ``gis_tin_<nombre>`` o la rejilla a
    ``gis_dtm_<nombre>``, con su hash, y la operación incorporada (RF-006-17)."""
    if result.state != _SUCCEEDED:
        return
    try:
        outcome = job_outcome(result, result.job_dir)
        summary = outcome.summary
        if plan.kind == jobs.GRID_TO_TIN:
            role, family = jobs.OUT_TIN.role, provenance.TIN
            report = tr("TIN «{name}» ({dataset}) from the DTM «{source}»: {vertices} vertices "
                        "and {triangles} triangles at the centres of the cells with data",
                        name=plan.name, dataset=provenance.dataset_name(family, plan.name),
                        source=record.name,
                        vertices=format_number(int(summary["vertices"]), 0),
                        triangles=format_number(int(summary["triangles"]), 0))
        else:
            role, family = jobs.OUT_PROJECT_GRID.role, provenance.PROJECT_GRID
            report = tr("Project grid {dataset} from the TIN «{source}»: {valid} of {cells} "
                        "cells with data (linear interpolation in each triangle)",
                        dataset=provenance.dataset_name(family, plan.name), source=record.name,
                        valid=format_number(int(summary["valid_cells"]), 0),
                        cells=format_number(int(summary["cells"]), 0))
        with store.ResultWriter(plan.handle.project, plan.handle) as out:
            out.copy_file(family, plan.name, outcome.file(role),
                          content=jobs.digest_of(summary["outputs"][role]["digest"]),
                          sha256=outcome.output(role).sha256)
            core_provenance.ingest_job_result(plan.handle, result, out.write, message=report)
    except Exception as error:  # noqa: BLE001 - la operación queda fallida con el motivo
        reason = _failure(plan.handle, result, error)
        _say(tr("«{name}» has not been converted: {reason}", name=plan.name, reason=reason))
        return
    _say(report)


def recompute_convert(request: RecomputeRequest) -> OperationHandle:
    """El recálculo de ``gis.grid_to_tin`` y ``gis.tin_to_grid`` (RF-008-26): la misma
    conversión con el dato vigente y los mismos ajustes; devuelve la operación nueva, aún
    «en curso»."""
    project = request.project
    (use,) = [use for use in request.inputs if use.role == "source"]
    with project.read() as conn:
        record = dataset_registry.get(conn, use.item)
    if record is None:
        raise GisError("gis.dataset_unknown", obj="Dato de topografía", field="dato",
                       value=use.item)
    kind = jobs.GRID_TO_TIN if request.op_type == provenance.GRID_TO_TIN else jobs.TIN_TO_GRID
    handle = request.begin(executor="job_thread")
    _start_convert(_Tin(handle, kind, str(request.settings["name"]), dict(request.settings)),
                   core_provenance.launch_job, record)
    return handle


class GEOBLENDER_OT_gis_convert_dtm_tin(ProvenanceAwareOperator, bpy.types.Operator):
    """Convert a grid DTM into a TIN or back"""

    bl_idname = CONVERT_DTM_TIN
    bl_label = "DTM ⇄ TIN…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.GRID_TO_TIN

    direction: EnumProperty(  # type: ignore[valid-type]
        name="Direction", items=DIRECTION_ITEMS, default="DTM_TO_TIN", options={"SKIP_SAVE"},
    )
    source: StringProperty(  # type: ignore[valid-type]
        name="Surface", description="Name or uid of the DTM or the TIN", options={"SKIP_SAVE"},
    )
    name: StringProperty(  # type: ignore[valid-type]
        name="Name", description="Name of the result (empty: the source's)",
        options={"SKIP_SAVE"},
    )
    items: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_view_dataset, options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context: Any) -> bool:
        return _poll(cls)

    def provenance_inputs(self, context: Any) -> tuple[Use, ...]:
        record = getattr(self, "_record", None)
        return () if record is None else (Use(record.uid, "source"),)

    def _families(self) -> tuple[str, ...]:
        return ((provenance.SOURCE_GRID, provenance.PROJECT_GRID)
                if self.direction == "DTM_TO_TIN" else (provenance.TIN,))

    def invoke(self, context: Any, event: Any) -> set[str]:
        self.provenance_dialog = True
        if self.source:
            return self.execute(context)
        try:
            records = _fill_items(self, (provenance.SOURCE_GRID, provenance.PROJECT_GRID,
                                         provenance.TIN))
        except GeoblenderError as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        if not records:
            path = path_text(command_catalog(), IMPORT_DTM, i18n.language())
            self.report({"ERROR"}, tr("First {step} ({path})", step=tr("import a DTM"),
                                      path=path))
            return {"CANCELLED"}
        self.source = records[-1].name
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False, title=tr("DTM ⇄ TIN conversion"))

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "direction", text=tr("Direction"), translate=False)
        layout.prop_search(self, "source", self, "items", text=tr("Surface"), translate=False)
        layout.prop(self, "name", text=tr("Name"), translate=False)

    def execute(self, context: Any) -> set[str]:
        blocked = unavailable_reason()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        project = core_provenance.SESSION.project
        to_tin = self.direction == "DTM_TO_TIN"
        try:
            record = _record(project, self.source, self._families())
            _require_project_references(project, record)
            name = self.name.strip() or _default_name([record])
            provenance.dataset_slug(name)
            settings: dict[str, Any] = {"name": name}
            if not to_tin:
                if project.window is None:
                    self.report({"ERROR"}, no_work_window_message())
                    return {"CANCELLED"}
                settings["grid"] = jobs.grid_json(project_grid(project.window,
                                                               project.grid_step_m))
        except (GeoblenderError, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        self._record = record
        self.provenance_op_type = provenance.GRID_TO_TIN if to_tin else provenance.TIN_TO_GRID
        handle = self.begin(context, settings=settings, executor="job_thread")
        if handle is None:
            return {"CANCELLED"}
        plan = _Tin(handle, jobs.GRID_TO_TIN if to_tin else jobs.TIN_TO_GRID, name, settings)
        try:
            job = _start_convert(plan, self.launch_job, record)
        except (GeoblenderError, OSError, ValueError) as exc:
            _abort(plan, exc)
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        if job is None:
            return {"CANCELLED"}
        self.report({"INFO"}, tr("Converting «{name}» in the background…", name=record.name))
        return {"FINISHED"}


# --- Curvas de nivel y validación de una superficie (T30) ----------------------------------


CREATE_CONTOURS = "geoblender.gis_create_contours"
VALIDATE_SURFACE = "geoblender.gis_validate_surface"
SURFACE_FAMILIES: tuple[str, ...] = (provenance.SOURCE_GRID, provenance.PROJECT_GRID,
                                     provenance.TIN)
"""Las superficies de la topografía: el MDT importado, la rejilla del proyecto y el TIN."""
SURFACE_KINDS: tuple[str, ...] = ("DTM", "TIN")
"""El tipo (``Object.geoblender.kind``) de un objeto de la vista que muestra una superficie."""
CONTOUR_FIELDS: tuple[tuple[str, str, str, str], ...] = (
    ("interval", INTERVAL_KEY, "interval_m", "Interval"),
    ("index_every", INDEX_EVERY_KEY, "index_every_m", "Index contours every"),
    ("index_offset", INDEX_OFFSET_KEY, "index_offset_m", "Index offset"),
    ("simplify", SIMPLIFY_KEY, "simplify_m", "Simplification"),
    ("min_length", MIN_LENGTH_KEY, "min_length_m", "Minimum length"),
)
"""Los campos del diálogo de las curvas con un parámetro de resultado del proyecto (D18): la
propiedad, la clave, su nombre en los ajustes de la operación y en el trabajo, y su etiqueta
(``msgid``)."""
BASE_SETTING = "base_m"
"""La cota base de las curvas en los ajustes y en el trabajo (un ajuste, D18; 0 por
defecto)."""
HOLES_SHOWN = 20
"""Huecos interiores cuya área cita el informe de una validación (el resto, cuántos más)."""


def contour_fields(project: Any) -> dict[str, tuple[str, str]]:
    """Los campos del diálogo de las curvas (D18; plan §5.6.1), por propiedad: el valor en el
    proyecto de cada uno de los cinco ``gis.contours.*``, como se teclea, y su insignia con
    «sin confirmar» si lo está (:func:`param_field`)."""
    return {prop: param_field(project, key) for prop, key, _setting, _label in CONTOUR_FIELDS}


def _active_surface(context: Any) -> str:
    """El uid del dato que muestra el objeto activo de la vista si es una superficie (un MDT o
    un TIN de la topografía); si no, vacío."""
    obj = getattr(context, "active_object", None)
    marks = getattr(obj, OBJECT_PROPERTY, None) if obj is not None else None
    if marks is None or marks.kind not in SURFACE_KINDS:
        return ""
    return str(marks.dataset_uid)


def _surface(project: Any, ref: str, context: Any) -> DatasetRecord:
    """La superficie ``ref`` (nombre o uid) o, sin él, la activa en la vista, en las
    referencias del proyecto; ``ValueError`` si no hay ninguna."""
    shown = ref.strip() or _active_surface(context)
    if not shown:
        raise ValueError(tr("Choose the surface: select it in the view or give its name"))
    record = _record(project, shown, SURFACE_FAMILIES)
    _require_project_references(project, record)
    return record


def _surface_items(operator: Any, context: Any, project: Any) -> set[str] | None:
    """Las filas del diálogo de una orden sobre una superficie y la superficie propuesta (la
    activa en la vista o la última); sin ninguna, lo dice y devuelve ``{'CANCELLED'}``."""
    try:
        records = _fill_items(operator, SURFACE_FAMILIES, project)
    except GeoblenderError as exc:
        operator.report({"ERROR"}, error_text(exc))
        return {"CANCELLED"}
    if not records:
        path = path_text(command_catalog(), IMPORT_DTM, i18n.language())
        operator.report({"ERROR"}, tr("First {step} ({path})", step=tr("import a DTM"),
                                      path=path))
        return {"CANCELLED"}
    if not operator.source:
        active = _active_surface(context)
        chosen = next((record for record in records if record.uid == active), records[-1])
        operator.source = chosen.name
    return None


@dataclass(eq=False)
class _Contours:
    """Unas curvas de nivel en marcha: su operación, su nombre, la superficie y los valores
    con que se calculan (la cota base y los cinco ``gis.contours.*``, en m)."""

    handle: OperationHandle
    name: str
    source: DatasetRecord
    values: Mapping[str, float]


def _contours_plan(handle: OperationHandle, record: DatasetRecord,
                   settings: Mapping[str, Any]) -> _Contours:
    """Las curvas de ``record`` de la operación ``handle`` con sus ajustes ``settings``: cada
    valor tecleado o, si no, el del proyecto que resolvió al empezar."""
    resolved = _resolved(handle)
    values = {BASE_SETTING: float(settings.get(BASE_SETTING, 0.0))}
    for _prop, key, setting, _label in CONTOUR_FIELDS:
        value = settings.get(setting, resolved.get(key))
        if value is None:
            raise ValueError(f"las curvas «{settings['name']}» no tienen valor para «{key}»: "
                             "ni tecleado ni del proyecto")
        values[setting] = float(value)
    return _Contours(handle, str(settings["name"]), record, values)


def _start_contours(plan: _Contours, launch: Callable[..., Any]) -> Any:
    """Lanza el trabajo ``gis_contours`` de ``plan`` con ``launch``, con la superficie copiada
    a ``in/``; al terminar, :func:`_contours_finished`."""
    project = plan.handle.project
    path = _file_of(project, plan.source)
    crs, vertical = store.project_references(project)
    params: dict[str, Any] = {"name": plan.name, "crs": jobs.crs_json(crs),
                              "vertical": jobs.vertical_json(vertical), **plan.values,
                              "count": path.stat().st_size // 4}
    return launch(plan.handle, jobs.CONTOURS, label=tr("Contour lines «{name}»", name=plan.name),
                  params=params, inputs={jobs.INPUT_SOURCE: path},
                  on_finish=functools.partial(_contours_finished, plan),
                  grace_s=jobs.CANCEL_GRACE_S)


def _contours_finished(plan: _Contours, result: JobResult) -> None:
    """El final de ``gis_contours``: las curvas a ``gis_cnt_<nombre>`` (su cota, si son
    maestras, si son cerradas y su longitud en planta; su hash, el del registro) y la operación
    incorporada con el informe (RF-006-18, RF-006-26); si el trabajo no terminó bien, la
    procedencia la deja cancelada o fallida con el motivo de la 004."""
    if result.state != _SUCCEEDED:
        return
    try:
        outcome = job_outcome(result, result.job_dir)
        lines = jobs.read_contours(outcome.file(jobs.OUT_CONTOURS.role))
        report = _contours_report(plan, lines)
        with store.ResultWriter(plan.handle.project, plan.handle) as out:
            out.contours(plan.name, lines)
            core_provenance.ingest_job_result(plan.handle, result, out.write, message=report)
    except Exception as error:  # noqa: BLE001 - la operación queda fallida con el motivo
        reason = _failure(plan.handle, result, error)
        _say(tr("The contour lines «{name}» have not been computed: {reason}", name=plan.name,
                reason=reason))
        return
    _say(report)


def _contours_report(plan: _Contours, lines: Sequence[ContourLine]) -> str:
    """El informe de unas curvas: cuántas (maestras y cerradas), sus vértices y su longitud
    en planta, y los valores con que se calcularon."""
    values = plan.values
    report = [tr("Contour lines {dataset} of «{source}»: {count} lines ({index} index, {closed} "
                 "closed), {vertices} vertices, {length} m in plan; interval {interval} m, "
                 "base elevation {base} m, index every {index_every} m",
                 dataset=provenance.dataset_name(provenance.CONTOUR_LINES, plan.name),
                 source=plan.source.name, count=format_number(len(lines), 0),
                 index=format_number(sum(1 for line in lines if line.is_index), 0),
                 closed=format_number(sum(1 for line in lines if line.closed), 0),
                 vertices=format_number(sum(len(line.xyz) for line in lines), 0),
                 length=format_number(sum(line.length_m for line in lines), 1),
                 interval=_decimal(values["interval_m"]), base=_decimal(values[BASE_SETTING]),
                 index_every=_decimal(values["index_every_m"]))]
    if values["index_offset_m"] or values["simplify_m"] or values["min_length_m"]:
        report.append(tr("Index offset {offset} m, simplification {simplify} m, minimum length "
                         "{min_length} m", offset=_decimal(values["index_offset_m"]),
                         simplify=_decimal(values["simplify_m"]),
                         min_length=_decimal(values["min_length_m"])))
    return "\n".join(report)


def recompute_contours(request: RecomputeRequest) -> OperationHandle:
    """El recálculo de ``gis.contours`` (RF-008-26; plan §5.6.8): las curvas de la superficie
    vigente con los parámetros de hoy y los mismos ajustes, en su trabajo; devuelve la
    operación nueva, que sustituye a la antigua, aún «en curso»."""
    project = request.project
    (use,) = [use for use in request.inputs if use.role == "source"]
    with project.read() as conn:
        record = dataset_registry.get(conn, use.item)
    if record is None:
        raise GisError("gis.dataset_unknown", obj="Dato de topografía", field="dato",
                       value=use.item)
    handle = request.begin(executor="job_thread")
    _start_contours(_contours_plan(handle, record, request.settings),
                    core_provenance.launch_job)
    return handle


class GEOBLENDER_OT_gis_create_contours(ProvenanceAwareOperator, bpy.types.Operator):
    """Contour lines of a surface at the chosen interval"""

    bl_idname = CREATE_CONTOURS
    bl_label = "Contour lines…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.CONTOURS

    source: StringProperty(  # type: ignore[valid-type]
        name="Surface",
        description="Name or uid of the DTM or the TIN (empty: the active surface in the view)",
        options={"SKIP_SAVE"},
    )
    interval: StringProperty(  # type: ignore[valid-type]
        name="Interval",
        description="Height between contour lines, m (empty or unchanged: the project's "
                    "parameter)",
        options={"SKIP_SAVE"},
    )
    base: StringProperty(  # type: ignore[valid-type]
        name="Base elevation", description="Elevation from which the levels are counted, m "
                                           "(empty: 0)",
        options={"SKIP_SAVE"},
    )
    index_every: StringProperty(  # type: ignore[valid-type]
        name="Index contours every",
        description="Height between index contours, m (empty or unchanged: the project's "
                    "parameter)",
        options={"SKIP_SAVE"},
    )
    index_offset: StringProperty(  # type: ignore[valid-type]
        name="Index offset",
        description="Offset of the index contours, m (empty or unchanged: the project's "
                    "parameter)",
        options={"SKIP_SAVE"},
    )
    simplify: StringProperty(  # type: ignore[valid-type]
        name="Simplification",
        description="Douglas–Peucker tolerance, m; 0 does not simplify (empty or unchanged: "
                    "the project's parameter)",
        options={"SKIP_SAVE"},
    )
    min_length: StringProperty(  # type: ignore[valid-type]
        name="Minimum length",
        description="Shorter contour lines are dropped, m (empty or unchanged: the project's "
                    "parameter)",
        options={"SKIP_SAVE"},
    )
    name: StringProperty(  # type: ignore[valid-type]
        name="Name", description="Name of the contour lines (empty: the surface's)",
        options={"SKIP_SAVE"},
    )
    items: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_view_dataset, options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context: Any) -> bool:
        return _poll(cls)

    def provenance_inputs(self, context: Any) -> tuple[Use, ...]:
        record = getattr(self, "_record", None)
        return () if record is None else (Use(record.uid, "source"),)

    def invoke(self, context: Any, event: Any) -> set[str]:
        self.provenance_dialog = True
        project = core_provenance.SESSION.project
        stop = _surface_items(self, context, project)
        if stop is not None:
            return stop
        fields = contour_fields(project)
        for prop, (shown, _note) in fields.items():
            if not getattr(self, prop):
                setattr(self, prop, shown)
        self._notes = {prop: note for prop, (_shown, note) in fields.items()}
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False, title=tr("Contour lines of a surface"))

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.prop_search(self, "source", self, "items", text=tr("Surface"), translate=False)
        notes = getattr(self, "_notes", {})
        language = i18n.language()
        for prop, _key, _setting, label in CONTOUR_FIELDS:
            row = layout.row()
            row.prop(self, prop, text=i18n.translate(language, label), translate=False)
            note = notes.get(prop, "")
            row.label(text=note, translate=False)
        layout.prop(self, "base", text=tr("Base elevation"), translate=False)
        layout.prop(self, "name", text=tr("Name"), translate=False)

    def execute(self, context: Any) -> set[str]:
        blocked = unavailable_reason()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        project = core_provenance.SESSION.project
        language = i18n.language()
        try:
            record = _surface(project, self.source, context)
            name = self.name.strip() or _default_name([record])
            provenance.dataset_slug(name)  # un nombre sin letras ni cifras no vale
            base = (parse_decimal(self.base, obj=tr("Base elevation"), field=BASE_SETTING)
                    if self.base.strip() else 0.0)
            settings: dict[str, Any] = {"name": name, "source": record.name,
                                        BASE_SETTING: base}
            params: list[str] = []
            for prop, key, setting, label in CONTOUR_FIELDS:
                text = str(getattr(self, prop)).strip()
                typed = None
                if text:
                    typed = gis_params.param(key).check(parse_decimal(
                        text, obj=i18n.translate(language, label), field=key))
                if typed is None or typed == project_value(project, key)[0]:
                    params.append(key)  # la del proyecto: se consume (RF-008-05)
                else:
                    settings[setting] = typed  # tecleada: un ajuste (D18)
        except (GeoblenderError, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        self._record = record
        handle = self.begin(context, settings=settings, params=params, executor="job_thread")
        if handle is None:
            return {"CANCELLED"}
        try:
            job = _start_contours(_contours_plan(handle, record, settings), self.launch_job)
        except (GeoblenderError, OSError, ValueError) as exc:
            try:
                handle.fail(error_text(exc))
            except GeoblenderError:
                pass
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        if job is None:
            return {"CANCELLED"}
        self.report({"INFO"}, tr("Computing the contour lines «{name}» in the background…",
                                 name=name))
        return {"FINISHED"}


@dataclass(eq=False)
class _Validation:
    """Una validación en marcha: el proyecto, la superficie y el rango plausible aplicado."""

    project: Any
    record: DatasetRecord
    z_range: tuple[float, float]


def validation_range(project: Any) -> tuple[float, float]:
    """El rango plausible de las cotas (``gis.validate.z_range_m``, de control, D17): el del
    proyecto si lo tiene y, si no, el de su definición, sin registrarlo (validar no escribe en
    el proyecto)."""
    low, high = project_value(project, Z_RANGE_KEY)[0]
    return float(low), float(high)


def _start_validation(plan: _Validation) -> Any:
    """Lanza el trabajo ``gis_validate`` de ``plan`` sin operación (validar no es una
    operación: spec §11) con la superficie copiada a ``in/``; al terminar,
    :func:`_validated`. Sin lanzador de trabajos, :class:`RuntimeError`."""
    runner = jobs_ops.MONITOR.runner
    if runner is None or runner.closed:
        raise RuntimeError("no hay lanzador de trabajos: Geoblender aún no ha preparado la "
                           "carpeta de los trabajos")
    project = plan.project
    path = _file_of(project, plan.record)
    crs, vertical = store.project_references(project)
    window = project.window
    params = {"name": plan.record.name, "crs": jobs.crs_json(crs),
              "vertical": jobs.vertical_json(vertical),
              "window": {"xmin": window.xmin, "ymin": window.ymin, "xmax": window.xmax,
                         "ymax": window.ymax},
              "z_range": list(plan.z_range), "count": path.stat().st_size // 4}
    request = new_request(jobs.VALIDATE, label=tr("Validation of «{name}»",
                                                  name=plan.record.name),
                          owner=MODULE, params=params, project_uid=project.uid,
                          grace_s=jobs.CANCEL_GRACE_S)
    # La misma copia a in/ que los trabajos de una operación (launch_job de la 008).
    folder = core_provenance._prepare_inputs(runner, request, {jobs.INPUT_SOURCE: path})
    return jobs_ops.MONITOR.submit(folder, on_finish=functools.partial(_validated, plan))


def _validated(plan: _Validation, result: JobResult) -> None:
    """El final de ``gis_validate``: el informe en los avisos de la sesión (el panel del
    proyecto y el registro técnico) y el trabajo dado por incorporado; nada en el
    proyecto."""
    name = plan.record.name
    try:
        if result.state == "cancelled":
            _say(tr("The validation of «{name}» was cancelled", name=name))
        elif result.state != _SUCCEEDED:
            _say(tr("«{name}» has not been validated: {reason}", name=name,
                    reason=result.error_text or result.state))
        else:
            outcome = job_outcome(result, result.job_dir)
            data = json.loads(outcome.file(jobs.OUT_REPORT.role).read_text("utf-8"))
            _say(validation_text(name, _surface_report(data)))
    except Exception as error:  # noqa: BLE001 - se dice; el proyecto no cambia
        LOGGER.warning("La validación de «%s» no se pudo leer", name, exc_info=error)
        _say(tr("«{name}» has not been validated: {reason}", name=name,
                reason=error_text(error)))
    finally:
        core_provenance.release_job(result.job_uid)


def _surface_report(data: Mapping[str, Any]) -> SurfaceReport:
    """El ``SurfaceReport`` del ``report.json`` de ``gis_validate``."""
    values = dict(data)
    values["hole_areas_m2"] = tuple(float(area) for area in values["hole_areas_m2"])
    values["z_range_m"] = tuple(float(z) for z in values["z_range_m"])
    return SurfaceReport(**values)


def validation_text(name: str, report: SurfaceReport) -> str:
    """El informe de la validación de la superficie ``name`` (RF-006-23), con su valor y su
    unidad: el área y el porcentaje sin dato, el área de cada hueco interior, lo que queda
    fuera de la ventana de trabajo, las cotas fuera del rango plausible (posible sin dato no
    declarado) y, en un TIN, los triángulos planos, el lado máximo y los degenerados."""
    grid = report.surface_type == SURFACE_GRID
    area, nodata = format_number(report.area_m2, 2), format_number(report.nodata_area_m2, 2)
    pct = format_number(report.nodata_pct, 2)
    lines = [tr("Validation of the grid «{name}»: area {area} m², without data {nodata} m² "
                "({pct} %)", name=name, area=area, nodata=nodata, pct=pct) if grid else
             tr("Validation of the TIN «{name}»: area {area} m², without data {nodata} m² "
                "({pct} %)", name=name, area=area, nodata=nodata, pct=pct)]
    holes = report.hole_areas_m2
    if not holes:
        lines.append(tr("Interior holes: none"))
    else:
        areas = "; ".join(f"{format_number(hole, 2)} m²" for hole in holes[:HOLES_SHOWN])
        if len(holes) > HOLES_SHOWN:
            more = tr("… and {count} more", count=format_number(len(holes) - HOLES_SHOWN, 0))
            areas = f"{areas}; {more}"
        lines.append(tr("Interior holes: {count} ({areas})",
                        count=format_number(len(holes), 0), areas=areas))
    outside = format_number(report.cells_outside_window, 0)
    lines.append(tr("Cells with data outside the work window: {count}", count=outside) if grid
                 else tr("Triangles with a vertex outside the work window: {count}",
                         count=outside))
    low, high = (_decimal(z) for z in report.z_range_m)
    count = format_number(report.out_of_range, 0)
    lines.append(tr("Cells with the elevation outside the plausible range from {low} to {high} "
                    "m: {count}", low=low, high=high, count=count) if grid else
                 tr("Vertices with the elevation outside the plausible range from {low} to "
                    "{high} m: {count}", low=low, high=high, count=count))
    if report.out_of_range:
        lines.append(tr("Elevations outside the plausible range may be an undeclared no-data "
                        "value"))
    if not grid:
        lines.append(tr("Flat triangles: {flat} %; longest side: {side} m; degenerate "
                        "triangles: {degenerate}",
                        flat=format_number(report.flat_pct or 0.0, 2),
                        side=format_number(report.max_edge_m or 0.0, 3),
                        degenerate=format_number(report.degenerate or 0, 0)))
    return "\n".join(lines)


class GEOBLENDER_OT_gis_validate_surface(bpy.types.Operator):
    """Holes, nodata and mesh checks of the surface"""

    bl_idname = VALIDATE_SURFACE
    bl_label = "Validate the surface"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    source: StringProperty(  # type: ignore[valid-type]
        name="Surface",
        description="Name or uid of the DTM or the TIN (empty: the active surface in the view)",
        options={"SKIP_SAVE"},
    )
    items: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_view_dataset, options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context: Any) -> bool:
        reason = open_reason()
        if reason is not None:
            cls.poll_message_set(reason)
            return False
        return True

    def invoke(self, context: Any, event: Any) -> set[str]:
        if self.source or _active_surface(context):
            return self.execute(context)
        stop = _surface_items(self, context, project_session.current())
        if stop is not None:
            return stop
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, translate=False, title=tr("Validation of a surface"))

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.prop_search(self, "source", self, "items", text=tr("Surface"), translate=False)

    def execute(self, context: Any) -> set[str]:
        blocked = open_reason()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        project = project_session.current()
        try:
            record = _surface(project, self.source, context)
            if project.window is None:
                self.report({"ERROR"}, no_work_window_message())
                return {"CANCELLED"}
            _start_validation(_Validation(project, record, validation_range(project)))
        except RuntimeError:
            self.report({"ERROR"}, tr("Geoblender has not prepared the jobs folder yet"))
            return {"CANCELLED"}
        except (GeoblenderError, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, tr("Validating «{name}» in the background…", name=record.name))
        return {"FINISHED"}


# --- Exportar (T31) ---------------------------------------------------------------------------


EXPORT_RASTER = "geoblender.gis_export_raster"
EXPORT_GPKG = "geoblender.gis_export_gpkg"
EXPORT_OPERATIONS: tuple[str, ...] = (provenance.EXPORT_RASTER, provenance.EXPORT_GPKG)
"""Los tipos de operación de las dos exportaciones (no se repiten solas: sin recálculo)."""
GRID_FAMILIES: tuple[str, ...] = (provenance.SOURCE_GRID, provenance.PROJECT_GRID)
"""Lo que se exporta a GeoTIFF: el MDT importado y la rejilla del proyecto (un TIN, antes a
rejilla con MDT ⇄ TIN)."""
LAYER_FAMILIES: tuple[str, ...] = (provenance.POINTS, provenance.BREAKLINES, provenance.TIN,
                                   provenance.CONTOUR_LINES, provenance.BOUNDARY)
"""Lo que se exporta a GeoPackage (RF-006-25), en el orden de su lista."""
RASTER_SUFFIXES: tuple[str, ...] = (".tif", ".tiff")
GPKG_SUFFIXES: tuple[str, ...] = (".gpkg",)
EXPORTED_ROLE = "exported"
"""El papel de lo que consume una exportación (``gis.provenance``)."""
TIN_LABEL = "TIN"
TIN_DESCRIPTION = "TIN de Geoblender: un triángulo por entidad"


@dataclass(eq=False)
class _Export:
    """Una exportación en marcha: su operación, el destino, lo que exporta y si la persona
    confirmó sustituir un destino que ya existía."""

    handle: OperationHandle
    target: Path
    sources: tuple[DatasetRecord, ...]
    overwrite: bool


def _export_target(project: Any, filepath: str, suffixes: Sequence[str], label: str) -> Path:
    """El destino de una exportación (la ruta del diálogo): con una de ``suffixes``
    (``gis.export_extension_invalid``) y fuera del proyecto o en su ``exports/``
    (``gis.export_inside_project``: nunca sobre lo que gestiona el proyecto)."""
    shown = filepath.strip()
    if not shown:
        raise ValueError(tr("Choose the file to export to"))
    path = Path(bpy.path.abspath(shown))
    if path.suffix.lower() not in suffixes:
        raise GisError("gis.export_extension_invalid", obj=path.name, field="extensión",
                       value=path.suffix or "—", file=path.name, format=label,
                       expected="/".join(suffixes))
    if (provenance.inside_project(project.root, path)
            and provenance.export_locator(project.root, path) is None):
        raise GisError("gis.export_inside_project", obj=path.name, field="destino",
                       value=path.name, file=path.name, project=project.name)
    return path


def _require_export_references(project: Any, record: DatasetRecord) -> None:
    """Lo que se exporta, en el CRS y la referencia vertical del proyecto (RF-006-24,
    RF-006-25: los entregables van en ellos); si no, ``gis.export_references_mismatch``
    nombrando los dos."""
    found = store.dataset_references(project, record)
    expected = store.project_references(project)
    if found != expected:
        raise GisError("gis.export_references_mismatch", obj=f"«{record.name}»", field="CRS",
                       value=reference_label(*found), name=record.name,
                       expected=reference_label(*expected))


def _default_target(project: Any, name: str, suffix: str) -> str:
    """El destino que propone el diálogo: ``exports/<nombre><extensión>`` del proyecto."""
    return str(Path(project.root, provenance.EXPORTS_FOLDER, f"{name}{suffix}"))


def _open_confirm(idname: str, values: Mapping[str, Any]) -> None:
    """Pide confirmar que se sustituye el destino que ya existe: la misma orden con
    ``confirm`` (su confirmación) en cuanto acaba esta; sin ventana, nada (lo dice el aviso)."""
    manager = getattr(bpy.context, "window_manager", None)
    windows = list(getattr(manager, "windows", ()) or ())
    if not windows:
        return
    group, name = idname.split(".")

    def call() -> None:
        try:
            with bpy.context.temp_override(window=windows[0]):
                getattr(getattr(bpy.ops, group), name)("INVOKE_DEFAULT", confirm=True, **values)
        except (RuntimeError, TypeError, AttributeError):
            LOGGER.warning("No se pudo pedir confirmación en %s", idname, exc_info=True)

    bpy.app.timers.register(call, first_interval=0.0)


def _existing(operator: Any, target: Path, values: Mapping[str, Any]) -> set[str] | None:
    """Si ``target`` ya existe y la persona no confirmó sustituirlo (spec §8: nunca sin
    confirmación): desde la interfaz, lo dice y pide confirmarlo; desde un guion, lo rechaza
    (``gis.export_target_exists``; con ``overwrite``, se sustituye). Devuelve
    ``{'CANCELLED'}``; si no hay nada que confirmar, ``None``."""
    if operator.overwrite or not target.exists():
        return None
    error = GisError("gis.export_target_exists", obj=target.name, field="destino",
                     value=target.name, file=target.name)
    if operator.provenance_dialog:
        operator.report({"WARNING"}, error_text(error))
        # En un operador vivo, ``bl_idname`` es «GEOBLENDER_OT_…» (011, T40): la orden.
        _open_confirm(command_idname(operator.bl_idname),
                      {"filepath": str(target), **values})
    else:
        operator.report({"ERROR"}, error_text(error))
    return {"CANCELLED"}


def _confirm(operator: Any, context: Any, event: Any) -> set[str]:
    """La confirmación de sustituir el destino (la orden con ``confirm``): si se acepta, la
    orden sigue con ``overwrite``."""
    operator.overwrite = True
    name = Path(operator.filepath).name
    return context.window_manager.invoke_confirm(
        operator, event, title=tr("Replace the file"),
        message=tr("«{file}» already exists: replace it?", file=name),
        confirm_text=tr("Replace"), translate=False)


def _start_export(operator: Any, context: Any, target: Path,
                  records: Sequence[DatasetRecord], settings: dict[str, Any],
                  start: Callable[[_Export, Callable[..., Any]], Any]) -> set[str]:
    """La puerta, la operación «en curso» que consume ``records`` y su trabajo (``start``);
    lo que no se puede, lo dice."""
    project = core_provenance.SESSION.project
    settings["file"] = target.name  # solo el nombre: ninguna ruta en el proyecto (D21)
    settings["in_exports"] = provenance.export_locator(project.root, target) is not None
    operator._records = tuple(records)
    handle = operator.begin(context, settings=settings, executor="job_thread")
    if handle is None:
        return {"CANCELLED"}
    plan = _Export(handle, target, tuple(records), bool(operator.overwrite))
    try:
        job = start(plan, operator.launch_job)
    except (GeoblenderError, OSError, ValueError) as exc:
        try:
            handle.fail(error_text(exc))
        except GeoblenderError:
            pass
        operator.report({"ERROR"}, error_text(exc))
        return {"CANCELLED"}
    if job is None:
        return {"CANCELLED"}
    operator.report({"INFO"}, tr("Exporting «{file}» in the background…", file=target.name))
    return {"FINISHED"}


def _start_raster(plan: _Export, launch: Callable[..., Any]) -> Any:
    """Lanza el trabajo ``gis_export`` (GeoTIFF) de ``plan`` con la rejilla copiada a
    ``in/``; al terminar, :func:`_exported`."""
    project = plan.handle.project
    (record,) = plan.sources
    path = _file_of(project, record)
    crs, vertical = store.project_references(project)
    params = {"format": jobs.GEOTIFF_FORMAT, "name": record.name, "crs": jobs.crs_json(crs),
              "vertical": jobs.vertical_json(vertical), "count": path.stat().st_size // 4}
    return launch(plan.handle, jobs.EXPORT, label=tr("Export of «{file}»", file=plan.target.name),
                  params=params, inputs={jobs.INPUT_SOURCE: path},
                  on_finish=functools.partial(_exported, plan), grace_s=jobs.CANCEL_GRACE_S)


def _start_gpkg(plan: _Export, launch: Callable[..., Any]) -> Any:
    """Lanza el trabajo ``gis_export`` (GeoPackage) de ``plan``: las tablas tal como están
    guardadas (``store.export_layer``, sin descodificarlas) en ``in/layers.npz`` y cada TIN,
    su fichero (``in/tin_<n>.npz``); al terminar, :func:`_exported`."""
    project = plan.handle.project
    tin_prefix = provenance.FAMILIES_BY_CODE[provenance.TIN].prefix
    layers: list[Any] = []
    inputs: dict[str, Path] = {}
    size = 0
    for record in plan.sources:
        if record.name.startswith(tin_prefix):
            path = _file_of(project, record)
            name = f"{jobs.TIN_INPUT_PREFIX}{len(inputs)}"
            inputs[name] = path
            layers.append(jobs.TinExport(record.name, name, f"{TIN_LABEL}: {record.name}",
                                         TIN_DESCRIPTION))
            size += path.stat().st_size
        else:
            layer = store.export_layer(project, record)
            layers.append(layer)
            size += sum(len(blob) for blob in layer.blobs)
    work = Path(project.cache_dir(), WORK_DIR, f"export-{plan.handle.uid.partition('-')[0]}")
    work.mkdir(parents=True, exist_ok=True)
    try:
        listed = work / f"{jobs.INPUT_LAYERS}.npz"
        jobs.write_export_layers(listed, layers)
        inputs[jobs.INPUT_LAYERS] = listed
        crs, vertical = store.project_references(project)
        params = {"format": jobs.GPKG_FORMAT, "name": plan.target.stem,
                  "crs": jobs.crs_json(crs), "vertical": jobs.vertical_json(vertical),
                  "count": size // 24}
        return launch(plan.handle, jobs.EXPORT,
                      label=tr("Export of «{file}»", file=plan.target.name), params=params,
                      inputs=inputs, on_finish=functools.partial(_exported, plan),
                      grace_s=jobs.CANCEL_GRACE_S)
    finally:
        shutil.rmtree(work, ignore_errors=True)  # el trabajo tiene su copia en in/


def _exported(plan: _Export, result: JobResult) -> None:
    """El final de ``gis_export``: el entregable a su destino (con la guarda de las escrituras
    otra vez, RF-008-15) y la operación incorporada con el informe; dentro de ``exports/``,
    como dato ``exports`` con el hash del trabajo (plan §5.6.6). Si no se puede (el destino
    abierto por otro programa: ``gis.raster_target_locked``), la operación queda fallida con
    el motivo y el destino anterior intacto; si el trabajo no terminó bien, la procedencia la
    deja cancelada o fallida con el motivo de la 004."""
    if result.state != _SUCCEEDED:
        return
    project = plan.handle.project
    name = plan.target.name
    role = jobs.OUT_EXPORT.role
    try:
        outcome = job_outcome(result, result.job_dir)
        core_provenance.check_write_target(plan.target)
        if not plan.overwrite and plan.target.exists():
            raise GisError("gis.export_target_exists", obj=name, field="destino", value=name,
                           file=name)
        crs, _vertical = store.project_references(project)
        with store.ResultWriter(project, plan.handle) as out:
            spec = out.export(outcome.file(role), plan.target,
                              content=jobs.digest_of(outcome.summary["outputs"][role]["digest"]),
                              sha256=outcome.output(role).sha256, crs_epsg=crs.epsg)
            report = _export_report(plan, outcome.summary, spec)
            core_provenance.ingest_job_result(plan.handle, result, out.write, message=report)
    except Exception as error:  # noqa: BLE001 - la operación queda fallida con el motivo
        reason = _failure(plan.handle, result, error)
        _say(tr("«{file}» has not been exported: {reason}", file=name, reason=reason))
        return
    _say(report)


def _export_report(plan: _Export, summary: Mapping[str, Any], spec: Any) -> str:
    """El informe de una exportación: qué se escribió, con el CRS y la referencia vertical
    del proyecto, y si es un dato del proyecto (dentro de ``exports/``) o no."""
    references = reference_label(*store.project_references(plan.handle.project))
    name = plan.target.name
    if "grid" in summary:
        grid = jobs.grid_of(summary["grid"])
        lines = [tr("GeoTIFF «{file}» exported from «{source}»: {cols} × {rows} cells of {dx} × "
                    "{dy} m, {valid} with data, in float32 with no data −9999; {references}",
                    file=name, source=plan.sources[0].name, cols=grid.ncols, rows=grid.nrows,
                    dx=_decimal(grid.dx), dy=_decimal(grid.dy),
                    valid=format_number(int(summary["valid_cells"]), 0),
                    references=references)]
    else:
        layers = "; ".join(f"{layer} ({format_number(int(count), 0)})"
                           for layer, count in summary["layers"])
        lines = [tr("GeoPackage «{file}» exported with {count} layers: {layers}; {references}",
                    file=name, count=len(summary["layers"]), layers=layers,
                    references=references)]
    if spec is not None:
        lines.append(tr("In the project as the deliverable {dataset}", dataset=spec.name))
    else:
        lines.append(tr("Written outside the project: it is not a dataset of the project"))
    return "\n".join(lines)


def _selected_datasets(context: Any) -> set[str]:
    """Los uid de los datos que muestran los objetos seleccionados en la vista."""
    found: set[str] = set()
    for obj in getattr(context, "selected_objects", None) or ():
        marks = getattr(obj, OBJECT_PROPERTY, None)
        if marks is not None and marks.dataset_uid:
            found.add(str(marks.dataset_uid))
    return found


class GEOBLENDER_OT_gis_export_raster(ProvenanceAwareOperator, bpy.types.Operator):
    """Write a surface or a grid as GeoTIFF"""

    bl_idname = EXPORT_RASTER
    bl_label = "Surface or grid to GeoTIFF…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.EXPORT_RASTER

    filepath: StringProperty(  # type: ignore[valid-type]
        name="File", subtype="FILE_PATH", options={"SKIP_SAVE"},
    )
    filter_glob: StringProperty(  # type: ignore[valid-type]
        default="*.tif;*.tiff", options={"HIDDEN"},
    )
    check_existing: BoolProperty(  # type: ignore[valid-type]
        default=True, options={"HIDDEN", "SKIP_SAVE"},
    )
    source: StringProperty(  # type: ignore[valid-type]
        name="Grid",
        description="Name or uid of the DTM or the project grid (empty: the active surface in "
                    "the view)",
        options={"SKIP_SAVE"},
    )
    overwrite: BoolProperty(  # type: ignore[valid-type]
        name="Replace", description="Replace the file if it already exists",
        options={"SKIP_SAVE"},
    )
    confirm: BoolProperty(options={"HIDDEN", "SKIP_SAVE"})  # type: ignore[valid-type]
    items: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_view_dataset, options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context: Any) -> bool:
        return _poll(cls)

    def provenance_inputs(self, context: Any) -> tuple[Use, ...]:
        return tuple(Use(record.uid, EXPORTED_ROLE) for record in getattr(self, "_records", ()))

    def invoke(self, context: Any, event: Any) -> set[str]:
        self.provenance_dialog = True
        if self.confirm:
            return _confirm(self, context, event)
        project = core_provenance.SESSION.project
        try:
            records = _fill_items(self, GRID_FAMILIES, project)
        except GeoblenderError as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        if not records:
            path = path_text(command_catalog(), IMPORT_DTM, i18n.language())
            self.report({"ERROR"}, tr("First {step} ({path})", step=tr("import a DTM"),
                                      path=path))
            return {"CANCELLED"}
        if not self.source:
            active = _active_surface(context)
            chosen = next((record for record in records if record.uid == active), records[-1])
            self.source = chosen.name
        if not self.filepath:
            self.filepath = _default_target(project, self.source, RASTER_SUFFIXES[0])
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.prop_search(self, "source", self, "items", text=tr("Grid"), translate=False)
        layout.prop(self, "overwrite", text=tr("Replace"), translate=False)

    def execute(self, context: Any) -> set[str]:
        blocked = unavailable_reason()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        project = core_provenance.SESSION.project
        try:
            target = _export_target(project, self.filepath, RASTER_SUFFIXES, "GeoTIFF")
            shown = self.source.strip() or _active_surface(context)
            if not shown:
                raise ValueError(tr("Choose the surface: select it in the view or give its name"))
            record = _record(project, shown, GRID_FAMILIES)
            _require_export_references(project, record)
        except (GeoblenderError, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        if not self.check_write_target(target):
            return {"CANCELLED"}
        stop = _existing(self, target, {"source": record.name})
        if stop is not None:
            return stop
        return _start_export(self, context, target, (record,), {"source": record.name},
                             _start_raster)


class GEOBLENDER_OT_gis_export_gpkg(ProvenanceAwareOperator, bpy.types.Operator):
    """Write layers to a GeoPackage"""

    bl_idname = EXPORT_GPKG
    bl_label = "Layers to GeoPackage…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.EXPORT_GPKG

    filepath: StringProperty(  # type: ignore[valid-type]
        name="File", subtype="FILE_PATH", options={"SKIP_SAVE"},
    )
    filter_glob: StringProperty(  # type: ignore[valid-type]
        default="*.gpkg", options={"HIDDEN"},
    )
    check_existing: BoolProperty(  # type: ignore[valid-type]
        default=True, options={"HIDDEN", "SKIP_SAVE"},
    )
    overwrite: BoolProperty(  # type: ignore[valid-type]
        name="Replace", description="Replace the file if it already exists",
        options={"SKIP_SAVE"},
    )
    confirm: BoolProperty(options={"HIDDEN", "SKIP_SAVE"})  # type: ignore[valid-type]
    items: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_gis_export_item, options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context: Any) -> bool:
        return _poll(cls)

    def provenance_inputs(self, context: Any) -> tuple[Use, ...]:
        return tuple(Use(record.uid, EXPORTED_ROLE) for record in getattr(self, "_records", ()))

    def invoke(self, context: Any, event: Any) -> set[str]:
        self.provenance_dialog = True
        if self.confirm:
            return _confirm(self, context, event)
        project = core_provenance.SESSION.project
        try:
            records = store.list_gis_datasets(project, families=LAYER_FAMILIES)
        except GeoblenderError as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        if not records:
            path = path_text(command_catalog(), IMPORT_POINTS, i18n.language())
            self.report({"ERROR"}, tr("First {step} ({path})", step=tr("import or compute a "
                                                                         "layer"), path=path))
            return {"CANCELLED"}
        order = {provenance.FAMILIES_BY_CODE[code].prefix: index
                 for index, code in enumerate(LAYER_FAMILIES)}
        chosen = _selected_datasets(context)
        self.items.clear()
        for record in sorted(records, key=lambda found: (
                next(index for prefix, index in order.items()
                     if found.name.startswith(prefix)), found.name)):
            item = self.items.add()
            item.name = record.name
            item.selected = record.uid in chosen
        if not self.filepath:
            self.filepath = _default_target(project, "capas", GPKG_SUFFIXES[0])
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.label(text=tr("Layers"), translate=False)
        column = layout.column(align=True)
        for item in self.items:
            column.prop(item, "selected", text=item.name, translate=False)
        layout.prop(self, "overwrite", text=tr("Replace"), translate=False)

    def execute(self, context: Any) -> set[str]:
        blocked = unavailable_reason()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        project = core_provenance.SESSION.project
        names = [str(item.name) for item in self.items if item.selected]
        if not names:
            self.report({"ERROR"}, tr("Choose at least one layer to export"))
            return {"CANCELLED"}
        try:
            target = _export_target(project, self.filepath, GPKG_SUFFIXES, "GeoPackage")
            records = [_record(project, name, LAYER_FAMILIES) for name in names]
            for record in records:
                _require_export_references(project, record)
        except (GeoblenderError, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        if not self.check_write_target(target):
            return {"CANCELLED"}
        rows = [{"name": str(item.name), "selected": bool(item.selected)} for item in self.items]
        stop = _existing(self, target, {"items": rows})
        if stop is not None:
            return stop
        return _start_export(self, context, target, records,
                             {"layers": [record.name for record in records]}, _start_gpkg)


# --- Declaraciones de la procedencia (T44; ADR-0025 §2; plan §5.6.3 y §5.6.8) ---------------

RECOMPUTE: Mapping[str, Callable[[RecomputeRequest], OperationHandle]] = MappingProxyType({
    provenance.RESAMPLE: recompute_resample,
    provenance.TIN_FROM_POINTS: recompute_tin,
    provenance.TIN_FROM_CONTOURS: recompute_tin,
    provenance.GRID_TO_TIN: recompute_convert,
    provenance.TIN_TO_GRID: recompute_convert,
    provenance.CONTOURS: recompute_contours,
})
"""La función de recálculo de cada tipo de operación de la 006 que se repite solo
(RF-008-26): vuelve a lanzar la misma cadena con las entradas vigentes, los parámetros de hoy y
los mismos ajustes."""
REIMPORT: Mapping[str, Callable[[ReimportRequest], OperationHandle]] = MappingProxyType({
    **{reader_id: reimport_dtm for reader_id in DTM_IMPORTERS},
    **{reader_id: reimport_survey for reader_id in SURVEY_IMPORTERS},
})
"""La función de reimportación de cada lector de importación de la 006, sin versión
(RF-008-11)."""


def _choices(items: Sequence[tuple[str, ...]],
             stored: Mapping[str, Any]) -> tuple[tuple[Any, str], ...]:
    """Una elección de un diálogo como la guarda su operación: cada valor guardado
    (``stored``, por el identificador de su ``EnumProperty``) con el ``msgid`` del nombre con
    que se elige (``items``)."""
    names = {item[0]: item[1] for item in items}
    return tuple((value, names[identifier]) for identifier, value in stored.items())


_DECIMAL_SETTING = contract.SettingDef("read.decimal", "Decimal mark",
                                       choices=_choices(DECIMAL_ITEMS, DECIMALS))
_POLICY_SETTING = contract.SettingDef("duplicate_policy", "Coincident points",
                                      choices=_choices(POLICY_ITEMS, POLICIES))
SETTING_DEFS: Mapping[str, tuple[contract.SettingDef, ...]] = MappingProxyType({
    provenance.IMPORT_DTM: (
        contract.SettingDef("read.nodata_override", "No data", unit=DIMENSIONLESS),
        contract.SettingDef("read.separator", "Separator",
                            choices=_choices(SEPARATOR_ITEMS, SEPARATORS)),
        _DECIMAL_SETTING,
    ),
    provenance.IMPORT_POINTS: (
        contract.SettingDef("read.encoding", "Encoding",
                            choices=_choices(ENCODING_ITEMS, ENCODINGS)),
        contract.SettingDef("read.separator", "Separator",
                            choices=_choices(POINT_SEPARATOR_ITEMS, POINT_SEPARATORS)),
        _DECIMAL_SETTING,
        contract.SettingDef("read.header_row", "Lines before the header", unit=DIMENSIONLESS),
        contract.SettingDef("read.line_kind", "Breaklines",
                            choices=_choices(LINE_KIND_ITEMS, LINE_KINDS)),
    ),
    provenance.IMPORT_VECTOR: (
        contract.SettingDef("read.role", "Role", choices=_choices(LAYER_ROLE_ITEMS, LAYER_ROLES)),
    ),
    provenance.RESAMPLE: (
        contract.SettingDef("method", "Method", choices=_choices(METHOD_ITEMS, METHODS)),
        contract.SettingDef("min_valid_fraction", "Minimum covered fraction",
                            unit=gis_params.param(FRACTION_KEY).unit),
    ),
    provenance.TIN_FROM_POINTS: (
        contract.SettingDef("max_edge_m", "Longest side", unit="m"),
        _POLICY_SETTING,
    ),
    provenance.TIN_FROM_CONTOURS: (
        contract.SettingDef("densify_m", "Densification",
                            unit=gis_params.param(DENSIFY_KEY).unit),
        _POLICY_SETTING,
    ),
    provenance.CONTOURS: (
        *(contract.SettingDef(setting, label, unit=gis_params.param(key).unit)
          for _prop, key, setting, label in CONTOUR_FIELDS),
        contract.SettingDef(BASE_SETTING, "Base elevation", unit="m"),
    ),
})
"""Los ajustes de la orden de cada tipo de la 006 que enseña su procedencia (RF-008-29;
T58; el panel «Grafo de operaciones y procedencia»), con el nombre del campo de su diálogo y
la unidad de su parámetro del proyecto (D18: un valor tecleado distinto del del proyecto es un
ajuste) o los nombres de sus elecciones. Ni el nombre del resultado, ni lo que consume, ni el
fichero o la capa (D21: ninguna ruta), ni los CRS (los dice la entrada), ni los parámetros de
control (D17); las conversiones MDT ⇄ TIN y las exportaciones no tienen ninguno que enseñar."""
OPERATION_DEFS: tuple[contract.OperationDef, ...] = provenance.operation_defs(
    RECOMPUTE, settings=SETTING_DEFS)
"""Los ``OperationDef`` de los once tipos de la 006, en el orden de
``gis.provenance.OPERATION_TYPES``, cada uno que se repite solo con su recálculo (contrato de
ADR-0025; ``operation_defs`` rechaza que falte o sobre una función) y con los ajustes de
:data:`SETTING_DEFS`."""
IMPORTER_DEFS: tuple[contract.ImporterDef, ...] = tuple(
    provenance.importer_def(reader_id, REIMPORT[reader_id])
    for reader_id in provenance.IMPORT_READERS)
"""Los ``ImporterDef`` de los lectores de importación de la 006 (``KeyError`` al cargar el
módulo si a uno le falta su reimportación)."""


# --- Las máscaras de las restricciones (spec 012, T21; RF-012-16; plan 012 §5.3.3, D-19) --------

MASKS_RUNS = incorporation.StepQueue()
"""Los pasos de las compilaciones de las restricciones que recalcula «Recalcular lo obsoleto»,
por orden de llegada (la cola es suya, aparte de las de la topografía, los sondeos y la
cubicación)."""
masks_tick: Callable[[], float | None] = MASKS_RUNS.timer
"""El temporizador de la cola de las máscaras: un paso de la primera por llamada (el mismo
objeto siempre: Blender reconoce un temporizador por su función)."""


def pending_mask_runs() -> list[str]:
    """Las compilaciones cuyos pasos esperan en la cola de las máscaras, en orden."""
    return MASKS_RUNS.pending()


def _report_mask_notices(result: object) -> None:
    """Los avisos de una compilación (``StoredMasks``: el perímetro tomado del límite legal, una
    zona fuera de la rejilla…), al registro de Blender en el idioma de Geoblender."""
    found = getattr(result, "result", None)
    for notice in getattr(found, "notices", None) or ():
        jobs_ops.report_later("WARNING", notice.text(i18n.language()))


def _mask_name(handle: Any) -> str:
    """Lo que enseña la barra de estado de una compilación: el nombre de su tipo de operación en
    el idioma de Geoblender o, si no está registrado, el tipo."""
    definition = contract.OPERATIONS.get(handle.op_type)
    return (i18n.translate(i18n.language(), definition.label_msgid)
            if definition is not None else str(handle.op_type))


def queue_mask_steps(handle: OperationHandle, steps: Iterator[Progress]) -> None:
    """Pone en la cola de las máscaras los pasos ``steps`` (``Progress``) de la compilación
    ``handle``, «en curso», y registra su temporizador si no lo estaba."""
    name = _mask_name(handle)
    MASKS_RUNS.add(handle.uid, name,
                   incorporation.RecomputeSteps(handle, name, steps,
                                                report=_report_mask_notices),
                   status=incorporation.RECOMPUTING)


def recompute_compile(request: RecomputeRequest) -> OperationHandle:
    """El recálculo de ``gis.compile_constraints`` (RF-008-26; RF-012-16; D-19): la compilación
    nueva (``gis.masks.store.recompute_run``, con las restricciones y los parámetros de hoy),
    «en curso», con sus pasos en la cola de las máscaras."""
    handle, steps = masks_store.recompute_run(request)
    queue_mask_steps(handle, steps)
    return handle


MASKS_OPERATION_DEF: contract.OperationDef = masks_provenance.operation_def(
    recompute_compile, masks_store.REPRODUCE[masks_provenance.COMPILE])
"""El ``OperationDef`` de ``gis.compile_constraints``: de la versión, repetible, con
:func:`recompute_compile`, la reproducción de ``gis.masks.store`` y la tolerancia de sus
cifras (10⁻⁹, D-37)."""


# --- Compilar las máscaras y exportarlas (spec 012, T23; RF-012-04, RF-012-06, RF-012-11,
# RF-012-15, RF-012-16, RF-012-20, RF-012-28; plan 012 §5.3.4, §5.5, D-31) -------------------------

COMPILE_CONSTRAINTS = masks_provenance.COMMAND
EXPORT_MASKS = "geoblender.gis_export_constraint_masks"
PREPARE_PHASE = "prepare"
"""La fase de los pasos de antes de empezar la operación (leer y comprobar las restricciones)."""
EXPORT_TICKS = 1000
_HIDDEN = {"HIDDEN", "SKIP_SAVE"}  # las pone quien la lanza (la ventana)


def _compile_steps(owner: Any, project: Any, version_uid: str) -> Iterator[Progress]:
    """Los pasos de la orden «Compilar las máscaras» de la versión ``version_uid``: los de antes
    de empezar la operación (``gis.masks.store.begin_compile_steps``: la lectura y la
    comprobación de cada restricción y de cada polígono, ninguno de más de 0,05 s en frío:
    RNF-012-06) como ``Progress`` sin avance, la operación «en curso» (queda en ``owner.handle``)
    y los de ``compile_run``, el último con lo guardado. Cerrarlos antes de la operación no
    deja nada; cerrarlos después, la deja «cancelada» (``compile_run`` lo hace al cerrarse) y no
    deja nada en el proyecto."""
    begin = masks_store.begin_compile_steps(project, version=version_uid)
    handle = None
    try:
        while handle is None:
            try:
                next(begin)
            except StopIteration as stop:
                handle = stop.value
                break
            yield Progress(PREPARE_PHASE, 0, 1, tr("Compiling the constraints…"))
    finally:
        begin.close()
    owner.handle = handle
    try:
        run = masks_store.compile_run(project, handle)
    except BaseException as error:  # noqa: BLE001 - la operación empezada queda fallida
        incorporation.end_operation(handle.fail, failure_reason(error))
        raise
    yield from run


def _drained(operator: Any, steps: Iterator[Progress]) -> Any:
    """Los pasos ``steps`` de una orden de una vez (desde un guion): el resultado del último o,
    si fallan, ``None`` (ya dicho con el ``_report`` de ``operator``; sus pasos no dejan nada a
    medias)."""
    found = None
    try:
        for step in steps:
            if step.result is not None:
                found = step.result
    except GeoblenderError as exc:
        operator._report({"ERROR"}, error_text(exc))
        return None
    except (sqlite3.Error, OSError, ValueError) as exc:
        LOGGER.error("«%s» se ha parado", operator.bl_idname, exc_info=exc)
        operator._report({"ERROR"}, error_text(exc))
        return None
    if found is None:  # pragma: no cover - los pasos acaban siempre con su resultado
        operator._report({"ERROR"}, tr("The operation did not finish with its result"))
    return found


class GEOBLENDER_OT_gis_compile_constraints(ProvenanceAwareOperator, _StepsModal,
                                            bpy.types.Operator):
    """Compile the constraints into the masks the design operators read"""

    bl_idname = COMPILE_CONSTRAINTS
    bl_label = "Compile the masks"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = masks_provenance.COMPILE
    STEP_BUDGET_S = 0.05  # cada evento del temporizador (RNF-012-06: ninguna llamada de > 0,2 s)

    in_steps: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]

    handle: Any = None
    """La operación que empezó (``None`` hasta que empieza)."""

    def invoke(self, context: Any, event: Any) -> set[str]:
        """Desde la interfaz, por pasos con el avance y Esc (sin versión activa, la ventana que
        pide una, RF-009-05)."""
        self.in_steps = getattr(context, "window", None) is not None
        return super().invoke(context, event)

    def execute(self, context: Any) -> set[str]:
        """Compila las restricciones de la versión activa (RF-012-11): la puerta de la 008 con
        las capas como entradas, y los pasos de ``gis.compile_constraints``. Desde la interfaz,
        por pasos con el avance y Esc; desde un guion, de una vez. Si no se puede (versión no
        editable, restricciones incompletas o no válidas, sin límite legal), lo dice y no
        registra nada."""
        blocked = write_unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        refusal = self._version_refusal()
        if refusal is not None:
            self.report({"ERROR"}, refusal)
            return {"CANCELLED"}
        project = core_provenance.SESSION.project
        version_uid = scene_versions.active_version() or ""
        try:
            inputs = masks_provenance.compile_inputs(masks_store.available_tables(project))
        except (GeoblenderError, sqlite3.Error, OSError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        ready = core_provenance.ensure_ready(
            self.provenance_op_type, inputs, report=self.report,
            dialog=self.provenance_dialog, version=version_uid)
        if ready is None:
            return {"CANCELLED"}
        self.handle = None
        self._project = project
        steps = _compile_steps(self, project, version_uid)
        if self.in_steps and getattr(context, "window", None) is not None:
            self._start(context, steps)
            return {"RUNNING_MODAL"}
        self.report_log: list[str] = []
        stored = _drained(self, steps)
        if stored is None:
            return {"CANCELLED"}
        self._finished(stored)
        return {"FINISHED"}

    def _finished(self, stored: Any) -> None:
        """Lo que dice la orden al terminar (RF-012-05, 06, 10, 11, 14): el informe de
        ``constraint_panels.compile_lines`` en la ventana y en el informe de Blender. La lista de
        la ventana no se vuelve a leer: compilar no cambia las restricciones ni su estado, y leerla
        con 500 restricciones tarda más de los 0,2 s de una llamada (RNF-012-06)."""
        project, handle = self._project, self.handle
        undo_watch.record(UndoKind.OPERATION, masks_provenance.COMPILE)
        names: tuple[str, ...] = ()
        try:
            with project.read() as conn:
                names = tuple(masks_store.current_pending(conn, project, handle.version_uid)[1])
        except (GeoblenderError, sqlite3.Error, OSError):
            LOGGER.warning("No se pudo leer la búsqueda de intocables pendiente", exc_info=True)
        shown = scene_versions.active()
        revision = shown.revision if shown is not None and shown.uid == handle.version_uid \
            else ""
        lines = constraint_panels.compile_lines(stored, revision, names)
        constraint_panels.show_report(lines)
        for line in lines:
            self._report({"WARNING" if line.alert else "INFO"}, line.text)

    # --- En pasos (_StepsModal) ---------------------------------------------------------------

    def _status_text(self, step: Progress) -> str:
        percent = max(0, min(100, int(100 * step.done / step.total))) if step.total else 0
        return tr("Compiling the constraints… {percent} % · Esc: cancel", percent=percent)

    def _cancelled_text(self) -> str:
        return tr("Compilation cancelled: nothing has been left half-done")

    def _error_text(self, exc: GeoblenderError) -> str:
        return error_text(exc)

    def _result(self, context: Any, step: Progress) -> set[str] | None:
        if step.result is None:
            if project_session.current() is not getattr(self, "_project", None):
                return self._fail(context, tr(
                    "The project was closed while the masks were being compiled: nothing has "
                    "been left half-done"))
            return None
        self._done(context)
        self._finished(step.result)
        return {"FINISHED"}

    def modal(self, context: Any, event: Any) -> set[str]:
        try:
            return super().modal(context, event)
        except Exception as exc:  # noqa: BLE001 - los pasos cerrados no dejan nada a medias
            LOGGER.error("«%s» se ha parado", self.bl_idname, exc_info=exc)
            return self._fail(context, error_text(exc))


def _export_progress(steps: Iterator[float], name: str) -> Iterator[Progress]:
    """Los pasos de ``gis.masks.export.export_classes_steps`` (su avance, 0–1) como ``Progress``
    (fase ``export``, en milésimas); el último lleva el fichero escrito. Cerrarlos cierra los de
    la exportación, que no dejan nada a medias."""
    try:
        while True:
            try:
                done = next(steps)
            except StopIteration as stop:
                yield Progress("export", EXPORT_TICKS, EXPORT_TICKS, name, result=stop.value)
                return
            yield Progress("export", int(EXPORT_TICKS * min(max(float(done), 0.0), 1.0)),
                           EXPORT_TICKS, name)
    finally:
        close = getattr(steps, "close", None)
        if callable(close):
            close()


class GEOBLENDER_OT_gis_export_constraint_masks(_StepsModal, bpy.types.Operator):
    """Write the class grid of the masks of the active version as a deliverable GeoTIFF with its
    legend (it is not an operation: also from a superseded version and, outside the project, in
    read-only)"""

    bl_idname = EXPORT_MASKS
    bl_label = "Export the masks…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "INTERNAL"}
    STEP_BUDGET_S = 0.05

    filepath: StringProperty(  # type: ignore[valid-type]
        name="File", subtype="FILE_PATH", options={"SKIP_SAVE"})
    filter_glob: StringProperty(  # type: ignore[valid-type]
        default="*.tif;*.tiff", options={"HIDDEN"})
    check_existing: BoolProperty(  # type: ignore[valid-type]
        default=True, options=_HIDDEN)
    overwrite: BoolProperty(  # type: ignore[valid-type]
        name="Replace", description="Replace the file if it already exists",
        options={"SKIP_SAVE"})
    in_steps: BoolProperty(default=False, options=_HIDDEN)  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context: Any) -> bool:
        """Con un proyecto abierto (no es una operación: en solo lectura, fuera de él)."""
        reason = core_provenance.SESSION.unavailable()
        if reason is not None:
            cls.poll_message_set(reason)  # type: ignore[attr-defined]
            return False
        return True

    def invoke(self, context: Any, event: Any) -> set[str]:
        """El diálogo de fichero, con el destino que propone (``exports/<versión>_mascaras.tif``
        del proyecto)."""
        self.in_steps = getattr(context, "window", None) is not None
        shown = scene_versions.active()
        if shown is None:
            self.report({"ERROR"}, tr("Choose the active version first: Project ▸ Versions ▸ "
                                      "Active version"))
            return {"CANCELLED"}
        if not self.filepath:
            stem = store.provenance.dataset_slug(f"{shown.code}_masks") \
                if hasattr(store, "provenance") else f"{shown.code}_masks"
            self.filepath = str(Path(core_provenance.SESSION.project.root,
                                     provenance.EXPORTS_FOLDER, f"{stem}.tif"))
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context: Any) -> set[str]:
        """Escribe el GeoTIFF de clases de la versión activa y su leyenda
        (``gis.masks.export``): desde la interfaz, por pasos con el avance y Esc; desde un guion,
        de una vez. Se niega, sin escribir nada, con las máscaras obsoletas o sin compilar, sobre
        un fichero que ya existe (salvo ``overwrite``) y dentro del proyecto fuera de sus
        entregables."""
        from ...gis.masks import export  # al usarlo: habilitar no lo carga

        blocked = core_provenance.SESSION.unavailable()
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        shown = scene_versions.active()
        if shown is None:
            self.report({"ERROR"}, tr("Choose the active version first: Project ▸ Versions ▸ "
                                      "Active version"))
            return {"CANCELLED"}
        typed = self.filepath.strip()
        if not typed:
            self.report({"ERROR"}, tr("Choose the file to export to"))
            return {"CANCELLED"}
        target = Path(bpy.path.abspath(typed))
        project = core_provenance.SESSION.project
        try:
            steps = export.export_classes_steps(
                project, shown.uid, target, read_only=core_provenance.read_only_dirs(),
                overwrite=bool(self.overwrite))
        except (GeoblenderError, sqlite3.Error, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        self._file, self._version = target.name, shown.code
        progress = _export_progress(steps, target.name)
        if self.in_steps and getattr(context, "window", None) is not None:
            self._start(context, progress)
            return {"RUNNING_MODAL"}
        self.report_log: list[str] = []
        stored = _drained(self, progress)
        if stored is None:
            return {"CANCELLED"}
        return self._exported()

    def _exported(self) -> set[str]:
        line = constraint_panels.Line(tr("Masks of {version} exported to «{file}»",
                                         version=getattr(self, "_version", ""),
                                         file=getattr(self, "_file", "")))
        constraint_panels.show_report([line])
        self._report({"INFO"}, line.text)
        return {"FINISHED"}

    # --- En pasos (_StepsModal) ---------------------------------------------------------------

    def _status_text(self, step: Progress) -> str:
        percent = max(0, min(100, int(100 * step.done / step.total))) if step.total else 0
        return tr("Exporting «{file}»… {percent} % · Esc: cancel",
                  file=getattr(self, "_file", ""), percent=percent)

    def _cancelled_text(self) -> str:
        return tr("Export cancelled: nothing has been written")

    def _error_text(self, exc: GeoblenderError) -> str:
        return error_text(exc)

    def _result(self, context: Any, step: Progress) -> set[str] | None:
        if step.result is None:
            return None
        self._done(context)
        return self._exported()

    def modal(self, context: Any, event: Any) -> set[str]:
        try:
            return super().modal(context, event)
        except OSError as exc:  # los pasos cerrados no dejan nada a medias
            LOGGER.error("La exportación de «%s» se ha parado", getattr(self, "_file", ""),
                         exc_info=exc)
            return self._fail(context, error_text(exc))


classes: tuple[type, ...] = (GEOBLENDER_OT_gis_import_dtm, GEOBLENDER_OT_gis_resample_to_grid,
                             GEOBLENDER_OT_gis_import_points, GEOBLENDER_OT_gis_import_vector,
                             GEOBLENDER_OT_gis_create_tin_from_points,
                             GEOBLENDER_OT_gis_create_tin_from_contours,
                             GEOBLENDER_OT_gis_convert_dtm_tin, GEOBLENDER_OT_gis_create_contours,
                             GEOBLENDER_OT_gis_validate_surface, GEOBLENDER_OT_gis_export_raster,
                             GEOBLENDER_OT_gis_export_gpkg,
                             GEOBLENDER_OT_gis_compile_constraints,
                             GEOBLENDER_OT_gis_export_constraint_masks)
"""Los operadores de ``gis`` (T28: las órdenes de un MDT; T29: puntos, capas, TIN y MDT ⇄
TIN; T30: curvas de nivel y validar una superficie; T31: exportar a GeoTIFF y a
GeoPackage)."""

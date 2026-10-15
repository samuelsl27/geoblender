# SPDX-License-Identifier: GPL-3.0-or-later
"""Los sondeos en Blender (código ``dh``, spec 005; plan 005 §5.1, §5.3.1, §5.5 y §5.6; ADR-0025
§2).

Registra lo que los sondeos declaran a las specs 004 y 008 (T24, como la 006/T44):

- sus **definiciones de parámetros** (``drillholes.params.DEFINITIONS``: los umbrales de la
  validación, el paso de las trazas y la regla bajo el límite de detección) en
  ``core.params`` (RF-005-16, RF-005-26; plan §5.6.3);
- (T39) sus **lectores de contenido** (``interop.dh_content``: ``io.dh_csv@1``,
  ``io.dh_xlsx@1`` e ``io.recmin_mdb@1``) en ``core.content`` (RF-005-12, RF-008-09): así la
  lista estática del trabajo ``core_content_hash`` coincide con lo que registra Blender. Leen
  las tablas con ``interop`` mismo y una base de RecMin con el extractor de
  ``adapters.registry.mdb_extractor()``, que resuelven ellos: no hay que darles nada;
- sus **tipos de trabajo** (``drillholes.jobs.WORKER_INFOS``) en ``jobs.catalog`` con
  ``register_worker`` (plan §5.6.7): ``jobs/`` no importa ``drillholes``;
- sus **declaraciones de procedencia**, constantes del módulo construidas una vez:
  :data:`OPERATION_DEFS` (los seis tipos de ``drillholes.provenance.OPERATION_TYPES``, cada
  repetible con su función de :data:`RECOMPUTE` y las importaciones y la desviación con los
  ajustes de su orden que enseña su procedencia, :data:`SETTING_DEFS`) e
  :data:`IMPORTER_DEFS` (un importador por lector de importación, con su función de
  :data:`REIMPORT`); registrar dos veces pone los mismos objetos.

:func:`register` pone lo que falta y apunta cómo quitarlo; :func:`unregister` quita solo eso, en
orden inverso: lo que otro registró antes con la misma clave, o puso después en su lugar, es
suyo y se queda (también una definición de parámetro de ``dh``). Los dos son simétricos e
idempotentes: registrar y desregistrar deja los registros de ``core`` como estaban. El cargador
de la vista de las trazas lo registra ``bl/scene/dh_view.py``.

**Las órdenes de la 005** (:data:`COMMANDS`; plan §5.3.1 con lo que cambia §5.6) son clases
reales con su ``bl_idname`` definitivo, sus propiedades y su etiqueta del catálogo de la 003
(contrato 1): ninguna es ya provisional. Las de la procedencia (importar, validar, exportar el
informe, calcular las trazas y la referencia del azimut) son operadores de la 008
(``ProvenanceAwareOperator``); las otras dos (la regla bajo el límite, que abre
``core_set_parameter``, y la representación, que abre su panel), operadores sin más. Las que
solo escriben en el proyecto llevan ``{'REGISTER'}``; calcular las trazas, que rehace la vista,
también ``UNDO``. Mientras su orden no llega (:data:`UNDELIVERED`), una no está disponible y
dice dónde estará («Disponible en 005 · Sondeos», :func:`unavailable_reason`), como un
provisional, y los recálculos (T42) lo dicen con ``dh.not_delivered`` sin hacer nada. La
entrada 005 del catálogo entrega sus órdenes tarea a tarea (``entries.toml``).

**Importar tablas de sondeos** (T25; HU-005-1; RF-005-05 a RF-005-07, RF-005-09 a RF-005-12;
plan §5.6.4 y §5.6.5): ``geoblender.dh_import_drillholes`` (Sondeos ▸ Importar ▸ «Sondeos
(CSV, XLSX…)»). Tras elegir los ficheros, el **asistente**: las declaraciones de la orden (el
CRS y el datum vertical de las bocas, la referencia del azimut y la declinación, el convenio de
la inclinación, la unidad de cada elemento, los valores sin dato, la entrega…), y cada fichero
(cada hoja de un XLSX) como una tabla con su papel y el campo de cada columna propuestos
(``interop.drillholes_tabular.suggest_role`` y ``suggest_mapping``; ``bl.props.dh``) y sus
primeras filas tal como se van a interpretar; si falta una declaración, lo dice y no se importa
nada (RF-005-07). Desde un guion, ``mapping_json`` da el papel (y, si se quiere, la
correspondencia y la hoja) de cada fichero. **Una entrada por fichero** (D-15): cada una, una
operación ``dh.import_tabular`` «en curso» y su lectura (``dh_import_tabular``, en proceso
aparte). Leídas todas, cada entrada se clasifica (``classify_import``; RF-008-54): la misma
entrada con los mismos ajustes se reutiliza (cancelada con el aviso); los mismos datos con
otros ajustes, una sustitución que necesita el motivo. Si hay códigos nuevos (RF-005-10),
sondeos que el proyecto ya tiene (RF-005-11) o una sustitución sin motivo, la orden espera la
decisión de la persona en «Importación pendiente» (``GEOBLENDER_PT_dh_pending``,
:func:`waiting_imports`): la misma orden con ``stage`` ``'APPLY'`` (dar de alta los códigos,
conservar o sustituir cada sondeo, el motivo) o ``'DISCARD'`` y ``pending`` (el uid de la
orden). Aplicada, cada entrada con su ``dh_import_apply`` y, todas, **por pasos** en una
transacción (``drillholes.store.SourceWriter``, RF-005-04): su entrada, lo importado con el
hash que dio su trabajo, su informe en ``dh_import_log`` (RF-005-12) y su original desde la
copia verificada del trabajo; después, la **base** (``dh.build_base``,
:func:`start_build_base`, desde lo importado vigente, ``drillholes.store.live_sources``) y su
**validación** (``dh.validate``, :func:`start_validate`, con el MDT del proyecto más reciente
si hay alguno, D-19), cuyas incidencias pasan a la lista de la pestaña «Sondeos». Cancelar o
fallar antes de un ``COMMIT`` no deja nada de esa operación.

**Importar una base de RecMin** (T26; HU-005-2; RF-005-07, RF-005-11 a RF-005-15; plan §5.3.1,
§5.6.4 y §5.6.5): ``geoblender.dh_import_recmin_mdb`` (Sondeos ▸ Importar ▸ «Base de sondeos
RecMin»; también un ``.mdb`` en «Importar un fichero…»). Tras elegir la base, su diálogo: su
formato (por su cabecera, sin motor), las declaraciones (el CRS y el datum de las bocas, la
referencia del azimut y la declinación, las unidades de los elementos que no son de ley, los
valores sin dato, «−x = <x», el tipo de la densidad), la entrega y, si otro programa la tiene
abierta (su ``.ldb`` o ``.laccdb`` junto a ella), el aviso y su confirmación: sin ella, ni sin
el CRS, el datum o la referencia del azimut, no empieza nada (RF-005-15, RF-005-07). Lo demás,
como las tablas: la base entera es **una** entrada (D-15) con su operación ``dh.import_recmin``
y su lectura (``dh_import_recmin``, en proceso aparte: copia la base y la extrae con el motor de
Access del equipo; sin motor, la operación falla con el formato y qué instalar, RF-005-14); una
versión de esquema que no es 11 ni 12 espera en «Importación pendiente» la confirmación de que
se lea igualmente (la misma orden con ``stage``: se lee otra vez con ``accept_schema``); su
informe en ``dh_import_log`` tiene una línea por tabla de RecMin, con los registros de los
sondeos que se conservan fuera y los de los que se sustituyen contados (RF-005-12).

**Validar y exportar el informe** (T27; HU-005-3; RF-005-16 a RF-005-19; plan §5.3.1, §5.6.6 y
§5.6.9; D-19): ``geoblender.dh_validate`` valida la base con la rejilla del proyecto
(``gis_dtm_*``) que se elige en su diálogo (por defecto, la vigente más reciente,
:func:`project_surfaces`; sin ninguna, DH-W05 no se evalúa y el informe lo dice): la operación
``dh.validate`` con la puerta de la 008 y su trabajo, por la cola de incorporación
(:func:`start_validate`). La lista de la pestaña «Sondeos» enseña el informe guardado de la
última validación del proyecto abierto (``drillholes.store.stored_validation``: las incidencias
y lo que no se evaluó, :func:`load_issues`), al validar y al cambiar de proyecto.
``geoblender.dh_export_validation_report`` lo exporta en proceso como la operación
``dh.export_validation``, que consume ``dh_validation_issue``: el destino, un CSV fuera del
proyecto o en su ``exports/`` (:func:`report_target`), pasa la guarda de las escrituras de la
008 (``check_write_target``, RF-008-15); uno que ya existe no se sustituye sin confirmarlo
(desde la interfaz, una confirmación; desde un guion, ``overwrite``); el CSV es el de T11
(``drillholes.store.export_report``) y, en ``exports/``, un dato del proyecto.

**Las trazas, la referencia del azimut y la regla bajo el límite de detección** (T28; HU-005-4;
RF-005-20, RF-005-22, RF-005-26; plan §5.3.1, §5.6.3, §5.6.6 y §5.6.10; D-22):
``geoblender.dh_desurvey`` calcula las trazas de la base (la operación ``dh.desurvey``,
repetible, con el método y los sondeos en sus ajustes, la tolerancia de profundidad y el paso de
las trazas de ``core.params``, y su trabajo ``dh_desurvey`` por la cola de incorporación,
:func:`start_desurvey`): de todos los sondeos o solo de los de traza obsoleta, que conserva las
demás si la desviación anterior usó el mismo método y los mismos parámetros
(``drillholes.store.kept_traces``); rehace la vista (``UNDO``; T29: escritas las trazas, su
vista se carga sola por la misma cola, :func:`start_view`, con el cargador de
``bl.scene.dh_view``). ``geoblender.
dh_set_azimuth_reference`` es «Actualizar» una entrada de bocas, desviaciones o una base de
RecMin con la referencia del azimut y la declinación nuevas y su motivo (``reimport_input``,
:func:`_reimport`: una sustitución de la entrada que, aplicada, reconstruye la base y deja
obsoletas, por la huella de la desviación, las trazas de sus sondeos); la reimportación de los
tres lectores (:data:`REIMPORT`) es la misma, con los ajustes registrados. ``geoblender.
dh_set_detection_limit_policy`` registra la regla bajo el límite con su valor por defecto si el
proyecto no la tiene (también la primera importación, :func:`ensure_detection_limit_rule`) y
abre ``geoblender.core_set_parameter`` con su clave: cambiarla queda en su historial y no
cambia ningún valor guardado.

**La cola de incorporación** de los sondeos (:data:`INCORPORATIONS`, su temporizador
:func:`incorporation_tick` y :func:`pending_incorporations`; RNF-005-06, plan §5.6.7) es suya,
aparte de la de la topografía: lo que deja un trabajo entra en el proyecto por pasos;
desregistrar la cierra sin escribir nada más.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import functools
import json
import logging
import math
import re
import sqlite3
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
from ...core.datasets import registry as dataset_registry
from ...core.errors import GeoblenderError, ValidationError
from ...core.georef import load_catalog
from ...core.i18n import format_number, tr, translate
from ...core.inputs import get as get_input
from ...core.inputs import list_inputs, locate_source, resolve_source
from ...core.inputs.model import InputRecord, SourcePrint
from ...core.inputs.registry import Reuse, Substitute, classify_import, reuse_input
from ...core.params.model import ParamKind
from ...core.provenance import contract
from ...core.provenance.messages import ProvenanceError
from ...core.provenance.operations import Use, begin_operation
from ...core.provenance.undo import UndoKind
from ...drillholes import jobs, provenance, store
from ...drillholes import params as dh_params
from ...drillholes.arrays import catalogs_json, rows_arrays, tables_arrays
from ...drillholes.desurvey import Method
from ...drillholes.model import (
    LITHOLOGY_LOG_SET,
    TABLES,
    AzimuthRef,
    Catalogs,
    DetectionFlag,
    InclinationConvention,
    Rejection,
    SourceDeclaration,
    ValueRules,
    name_key,
    parse_declination,
)
from ...drillholes.schema import BASE_TABLES, LAYOUTS
from ...gis import jobs as gis_jobs
from ...gis import provenance as gis_provenance
from ...gis import store as gis_store
from ...gis.crs import ELLIPSOIDAL_ETRS89, crs_library
from ...gis.dtm import parse_crs
from ...interop import csv_tables, dh_content, xlsx_tables
from ...interop import drillholes_tabular as tabular
from ...interop import ports as mdb_ports
from ...interop.base import DeclarationError, Needs, missing_declarations, spanish_list
from ...interop.recmin.schema import SOURCE_LABEL as RECMIN_LABEL
from ...jobs import catalog as job_catalog
from ...jobs.ingest import job_outcome
from ..props.core import GEOBLENDER_PG_core_view_dataset
from ..props.dh import (
    IMPORT_PROPERTY,
    NOT_EVALUATED,
    NOT_IMPORTED,
    ROLE_ITEMS,
    ROLES,
    VALIDATION_PROPERTY,
    GEOBLENDER_PG_dh_table,
    fill_tables,
    suggest_fields,
    table_mapping,
)
from ..scene import project_session, undo_watch, views
from ..scene.dh_view import NOT_DELIVERED
from ..ui.commands import UNDELIVERED_FLAG, unavailable_note
from ..ui.commands import catalog as command_catalog
from . import core_provenance
from .core_provenance import (
    ProvenanceAwareOperator,
    ensure_ready,
    error_text,
    write_unavailable,
)
from .incorporation import StepQueue

if TYPE_CHECKING:
    from ...core.georef import VerticalRef
    from ...core.provenance.contract import ReimportRequest
    from ...core.provenance.operations import OperationHandle
    from ...core.provenance.recompute import RecomputeRequest
    from ...interop.csv_tables import Table
    from ...jobs.runner import JobResult

LOGGER = logging.getLogger("geoblender.bl.ops")
TRANSLATION_CONTEXT = "Geoblender"
MODULE = provenance.MODULE
"""El módulo de las definiciones de parámetros de los sondeos (``dh``)."""
OPEN_PROJECT = "geoblender.core_open_project"

IMPORT_DRILLHOLES = "geoblender.dh_import_drillholes"
IMPORT_RECMIN = "geoblender.dh_import_recmin_mdb"
SET_DETECTION_LIMIT = "geoblender.dh_set_detection_limit_policy"
VALIDATE = "geoblender.dh_validate"
EXPORT_REPORT = "geoblender.dh_export_validation_report"
DESURVEY = "geoblender.dh_desurvey"
SET_AZIMUTH = "geoblender.dh_set_azimuth_reference"
SHOW_DISPLAY = "geoblender.dh_show_display"
COMMANDS: tuple[str, ...] = (IMPORT_DRILLHOLES, IMPORT_RECMIN, SET_DETECTION_LIMIT, VALIDATE,
                             EXPORT_REPORT, DESURVEY, SET_AZIMUTH, SHOW_DISPLAY)
"""Las órdenes de la 005 (entrada ``005`` del catálogo), en el orden del menú Sondeos."""
UNDELIVERED: frozenset[str] = frozenset(COMMANDS) - {
    IMPORT_DRILLHOLES, IMPORT_RECMIN, VALIDATE, EXPORT_REPORT, DESURVEY, SET_AZIMUTH,
    SET_DETECTION_LIMIT}
"""Las órdenes cuya ejecución aún no ha llegado (plan 005, fase 3): no están disponibles y
dicen dónde estarán. La tarea que entrega una la quita de aquí (T25: importar tablas; T26, una
base de RecMin; T27, validar y exportar el informe de validación; T28, calcular las trazas, la
referencia del azimut y la regla bajo el límite de detección)."""
_PROJECT_ONLY: frozenset[str] = frozenset({SHOW_DISPLAY})
"""Las que no escriben en el proyecto: les basta tenerlo abierto."""

# --- Elecciones de los diálogos -----------------------------------------------------------------

UNDECLARED = "UNDECLARED"
PROJECT_VERTICAL = "PROJECT"
ELLIPSOIDAL = "ELLIPSOIDAL"
VERTICAL_ITEMS = [
    (UNDECLARED, "Undeclared", "Declare it: without it nothing is imported"),
    (PROJECT_VERTICAL, "The project's", ""),
    (ELLIPSOIDAL, "ETRS89 ellipsoidal height", "Collars measured with GNSS, without geoid"),
]
VERTICAL_ITEMS += [(f"EPSG:{ref.epsg}", f"EPSG:{ref.epsg} · {ref.name}", ref.name)
                   for ref in load_catalog().verticals() if ref.epsg is not None]
NOT_DECLARED = "NONE"
AZIMUTH_ITEMS = [
    (NOT_DECLARED, "Undeclared", "Declare it if there are surveys or a collar orientation"),
    ("GRID", "Grid north", ""),
    ("TRUE", "True north", "Geographic north"),
    ("MAGNETIC", "Magnetic north", "With its magnetic declination"),
]
AZIMUTH_REFS: Mapping[str, str | None] = MappingProxyType({
    NOT_DECLARED: None, "GRID": str(AzimuthRef.GRID), "TRUE": str(AzimuthRef.TRUE),
    "MAGNETIC": str(AzimuthRef.MAGNETIC)})
INCLINATION_ITEMS = [
    (NOT_DECLARED, "Undeclared", "Declare it if there are surveys or a collar orientation"),
    ("NEGATIVE_DOWN", "Negative downwards", "From the horizontal: −90 is vertical downwards"),
    ("POSITIVE_DOWN", "Positive downwards", "From the horizontal: 90 is vertical downwards"),
    ("FROM_VERTICAL", "From the vertical", "0 is vertical downwards"),
]
INCLINATIONS: Mapping[str, str | None] = MappingProxyType({
    NOT_DECLARED: None, "NEGATIVE_DOWN": str(InclinationConvention.NEGATIVE_DOWN),
    "POSITIVE_DOWN": str(InclinationConvention.POSITIVE_DOWN),
    "FROM_VERTICAL": str(InclinationConvention.FROM_VERTICAL)})
SEPARATOR_ITEMS = [
    ("SEMICOLON", "Semicolon", ""),
    ("COMMA", "Comma", ""),
    ("TAB", "Tab", ""),
]
SEPARATORS: Mapping[str, str] = MappingProxyType({"SEMICOLON": ";", "COMMA": ",", "TAB": "\t"})
DECIMAL_ITEMS = [("COMMA", "Comma", ""), ("POINT", "Point", "")]
DECIMALS: Mapping[str, str] = MappingProxyType({"COMMA": ",", "POINT": "."})
ENCODING_ITEMS = [
    ("UTF8", "UTF-8", ""),
    ("CP1252", "Windows-1252", ""),
    ("ISO8859_1", "ISO-8859-1 (Latin-1)", ""),
    ("CP850", "DOS (CP850)", ""),
]
ENCODINGS: Mapping[str, str] = MappingProxyType({"UTF8": "utf-8", "CP1252": "cp1252",
                                                 "ISO8859_1": "iso8859-1", "CP850": "cp850"})
DENSITY_ITEMS = [
    ("MEDIDO", "Measured", "The densities of the catalog were measured"),
    ("ADOPTADO", "Adopted", "The densities of the catalog are adopted values"),
    ("HIPOTESIS", "Hypothesis", "The densities of the catalog are a hypothesis"),
]
DENSITY_KINDS: Mapping[str, str] = MappingProxyType({
    "MEDIDO": str(ParamKind.MEDIDO), "ADOPTADO": str(ParamKind.ADOPTADO),
    "HIPOTESIS": str(ParamKind.HIPOTESIS)})
METHOD_ITEMS = [
    ("MINIMUM_CURVATURE", "Minimum curvature", ""),
    ("TANGENT", "Tangent", ""),
    ("BALANCED_TANGENT", "Balanced tangent", ""),
]
METHODS: Mapping[str, str] = MappingProxyType({
    "MINIMUM_CURVATURE": str(Method.MINIMUM_CURVATURE), "TANGENT": str(Method.TANGENT),
    "BALANCED_TANGENT": str(Method.BALANCED_TANGENT)})
SCOPE_ITEMS = [
    ("ALL", "All the drillholes", ""),
    ("STALE", "Only the stale ones", "The drillholes whose trace is stale"),
]
SCOPES: Mapping[str, str] = MappingProxyType({"ALL": "all", "STALE": "stale"})
STAGE_NEW = "NEW"
STAGE_APPLY = "APPLY"
STAGE_DISCARD = "DISCARD"
STAGE_ITEMS = [
    (STAGE_NEW, "New import", ""),
    (STAGE_APPLY, "Apply", ""),
    (STAGE_DISCARD, "Discard", ""),
]
_FIELD = {"SKIP_SAVE"}
_HIDDEN = {"HIDDEN", "SKIP_SAVE"}

_UNDO: list[Callable[[], None]] = []


# --- Registro --------------------------------------------------------------------------------


def register() -> None:
    """Registra las definiciones de parámetros, los lectores de contenido, los tipos de trabajo
    y las declaraciones de procedencia (:data:`OPERATION_DEFS`, :data:`IMPORTER_DEFS`) de los
    sondeos que aún no están y (T27) apunta en la sesión :func:`on_project_changed` (la lista
    de incidencias del proyecto abierto); idempotente."""
    missing = tuple(defn for defn in dh_params.DEFINITIONS
                    if defn.key not in core_params.DEFINITIONS)
    if missing:
        core_params.register_definitions(missing)
        _UNDO.append(functools.partial(_unregister_definitions, missing))
    for reader in dh_content.CONTENT_READERS:
        if reader.id not in content_readers.READERS:
            content_readers.register_reader(reader)
            _UNDO.append(_unregister_if(content_readers.READERS, reader.id, reader,
                                        content_readers.unregister_reader))
    for info in jobs.WORKER_INFOS:
        if info.name not in job_catalog.WORKERS:
            job_catalog.register_worker(info)
            _UNDO.append(_unregister_if(job_catalog.WORKERS, info.name, info,
                                        job_catalog.unregister_worker))
    for definition in OPERATION_DEFS:
        if definition.op_type not in contract.OPERATIONS:
            contract.register_operation(definition)
            _UNDO.append(_unregister_if(contract.OPERATIONS, definition.op_type, definition,
                                        contract.unregister_operation))
    for importer in IMPORTER_DEFS:
        if importer.reader_id not in contract.IMPORTERS:
            contract.register_importer(importer)
            _UNDO.append(_unregister_if(contract.IMPORTERS, importer.reader_id, importer,
                                        contract.unregister_importer))
    if on_project_changed not in project_session.listeners():
        project_session.add_listener(on_project_changed)
        _UNDO.append(functools.partial(project_session.remove_listener, on_project_changed))


def unregister() -> None:
    """Cierra las incorporaciones en cola (sin escribir nada más), olvida las importaciones
    que esperaban (su operación sigue «en curso» y queda «interrumpida» al abrir el proyecto) y
    quita lo que puso :func:`register`, en orden inverso (lo que otro cambió después es suyo);
    idempotente."""
    INCORPORATIONS.drop()
    _WAITING.clear()
    _ORDERS.clear()
    _PREVIEWS.clear()
    while _UNDO:
        _UNDO.pop()()


def _unregister_if(view: Any, key: str, item: object,
                   remove: Callable[[str], object]) -> Callable[[], None]:
    def undo() -> None:
        if view.get(key) is item:  # si otro lo cambió, es suyo
            remove(key)

    return undo


def _unregister_definitions(ours: tuple[core_params.ParamDef, ...]) -> None:
    """Quita las definiciones que puso :func:`register` (``ours``) y deja las demás de ``dh``:
    las que otro registró antes con su clave o puso después en su lugar son suyas.
    ``core.params`` solo las quita por módulo: se quitan todas y se vuelven a poner las de
    otro, los mismos objetos."""
    mine = {id(defn) for defn in ours}
    others = [defn for defn in core_params.DEFINITIONS.values()
              if defn.module == MODULE and id(defn) not in mine]
    core_params.unregister_definitions(MODULE)
    if others:
        core_params.register_definitions(others)


# --- Incorporar por pasos (RNF-005-06; plan §5.6.7) ---------------------------------------------

INCORPORATIONS = StepQueue()
"""Las incorporaciones de los sondeos que esperan su turno (la cola es suya, aparte de la de la
topografía)."""
incorporation_tick: Callable[[], float | None] = INCORPORATIONS.timer
"""El temporizador de las incorporaciones de los sondeos: un paso de la primera de la cola por
llamada (en ``blender -b`` no corren los temporizadores: las pruebas lo llaman a mano)."""


def pending_incorporations() -> list[str]:
    """Las operaciones cuya incorporación por pasos espera el temporizador."""
    return INCORPORATIONS.pending()


# --- Disponibilidad -----------------------------------------------------------------------------


def open_reason() -> str | None:
    """Sin proyecto abierto, el paso previo de una orden de los sondeos («Primero abra un
    proyecto (Proyecto ▸ … ▸ Abrir proyecto…)»); con él, ``None``."""
    if project_session.current() is None:
        path = path_text(command_catalog(), OPEN_PROJECT, i18n.language())
        return tr("First {step} ({path})", step=tr("open a project"), path=path)
    return None


def unavailable_reason(idname: str) -> str | None:
    """Por qué no se puede lanzar ahora la orden ``idname`` de los sondeos (su ``poll``), en
    el idioma de Geoblender: si aún no ha llegado (:data:`UNDELIVERED`), dónde estará
    («Disponible en 005 · Sondeos», como un provisional); sin proyecto, el paso previo
    (:func:`open_reason`); una que escribe en el proyecto, sin la procedencia o en solo
    lectura, su motivo (``core_provenance.write_unavailable``). Si se puede, ``None``."""
    if idname in UNDELIVERED:
        found = command_catalog().commands.get(idname)
        return unavailable_note(found) if found is not None else idname
    reason = open_reason()
    if reason is None and idname not in _PROJECT_ONLY:
        reason = write_unavailable()
    return reason


class _DrillholesCommand:
    """Lo común de las órdenes de los sondeos (sin base de Blender: NOM-01): su ``poll`` con
    :func:`unavailable_reason` y, mientras su orden no llega, un ``execute`` que lo dice sin
    tocar nada (``poll`` ya no deja llegar a él)."""

    @classmethod
    def poll(cls, context: Any) -> bool:
        reason = unavailable_reason(cls.bl_idname)  # type: ignore[attr-defined]
        if reason is not None:
            cls.poll_message_set(reason)  # type: ignore[attr-defined]
            return False
        return True

    def execute(self, context: Any) -> set[str]:
        reason = unavailable_reason(self.bl_idname)  # type: ignore[attr-defined]
        self.report({"INFO"}, reason or "")  # type: ignore[attr-defined]
        return {"CANCELLED"}


# --- Ayudas -------------------------------------------------------------------------------------


def _text(msgid: str) -> str:
    """El texto de un ``msgid`` de una constante del módulo en el idioma de Geoblender."""
    return translate(i18n.language(), msgid)


def _say(text: str) -> None:
    """Lo que dice una orden al terminar su trabajo: en los avisos de la sesión (el panel del
    proyecto y el registro técnico)."""
    project_session.notify(text)


def _redraw() -> None:
    """Redibuja las vistas 3D (la pestaña «Sondeos» cambió)."""
    manager = getattr(bpy.context, "window_manager", None)
    for window in list(getattr(manager, "windows", ()) or ()):
        screen = getattr(window, "screen", None)
        for area in getattr(screen, "areas", ()) or ():
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _number(value: Any) -> str:
    """Un número leído para enseñarlo: con los decimales que tiene (hasta 6), en el formato
    del idioma; sin valor, «—»."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    if isinstance(value, bool) or not isinstance(value, int | float | np.integer | np.floating):
        return str(value)
    if isinstance(value, int | np.integer):
        return format_number(int(value), 0)
    text = np.format_float_positional(float(value), unique=True, trim="-")
    decimals = min(len(text.partition(".")[2]), 6)
    return format_number(float(value), decimals)


def _delivery_day(typed: str) -> dt.date | None:
    """La fecha de entrega tecleada: un día DD/MM/AAAA (o, desde un guion, AAAA-MM-DD); vacía,
    sin fecha. ``ValueError`` con el aviso si no es un día."""
    shown = typed.strip()
    if not shown:
        return None
    try:
        return dt.datetime.strptime(shown, "%d/%m/%Y").date()
    except ValueError:
        pass
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", shown):
        try:
            return dt.date.fromisoformat(shown)
        except ValueError:
            pass
    raise ValueError(tr("Delivery date «{value}»: write it as DD/MM/YYYY", value=shown))


def vertical_choice(choice: str, project: Any) -> VerticalRef | None:
    """El datum vertical de las cotas elegido en el diálogo (``None``: «Sin declarar»)."""
    if choice == UNDECLARED:
        return None
    if choice == PROJECT_VERTICAL:
        return gis_store.project_references(project)[1]
    if choice == ELLIPSOIDAL:
        return ELLIPSOIDAL_ETRS89
    return load_catalog().vertical(int(choice.removeprefix("EPSG:")))


def parse_units(text: str) -> dict[str, str]:
    """La unidad de cada elemento tecleada («Au=g/t; Cu=%», también con «:»); vacía, ninguna.
    ``ValueError`` con el aviso si una parte no es «código=unidad»."""
    found: dict[str, str] = {}
    for part in re.split(r"[;\n]", text):
        shown = part.strip()
        if not shown:
            continue
        code, sep, unit = shown.partition("=")
        if not sep:
            code, sep, unit = shown.partition(":")
        if not sep or not code.strip() or not unit.strip():
            raise ValueError(tr("Unit «{text}»: write each element with its unit, such as "
                                "Au=g/t, separated by «;»", text=shown))
        found[code.strip()] = unit.strip()
    return found


def parse_sentinels(text: str) -> frozenset[str]:
    """Los valores sin dato tecleados («−99;−999;ND»)."""
    return frozenset(part.strip() for part in text.split(";") if part.strip())


# --- Las tablas de una importación (T25; RF-005-05) ---------------------------------------------

READERS: Mapping[str, str] = MappingProxyType({".csv": provenance.DH_CSV,
                                               ".txt": provenance.DH_CSV,
                                               ".xlsx": provenance.DH_XLSX})
"""El lector de una tabla de sondeos por la extensión de su fichero."""
PREVIEW_LINES = csv_tables.PREVIEW_ROWS
"""Las filas de una tabla que enseña el asistente tal como se van a interpretar (RF-005-05)."""
SAMPLE_ROWS = 3
"""Los valores de ejemplo de cada columna en el asistente."""
DIALOG_WIDTH = 720
RECMIN_DIALOG_WIDTH = 600
"""El ancho del diálogo de una base de RecMin (sin tablas que enseñar: solo lo declarado)."""
_PREVIEWS_KEPT = 64
_ROLE_MSGIDS: Mapping[str, str] = MappingProxyType(
    {ROLES[identifier]: name for identifier, name, _description in ROLE_ITEMS})
_KIND_MSGIDS: Mapping[str, str] = MappingProxyType({
    "lithology": "lithologies", "element": "elements", "sector": "sectors",
    "group": "groups", "zone": "zones"})
_CATALOG_ROLES = frozenset({str(tabular.TableRole.LITHOLOGY_CATALOG),
                            str(tabular.TableRole.ELEMENT_CATALOG)})


@dataclass(frozen=True)
class ReadOptions:
    """Cómo se leen las tablas de una orden: la codificación y el separador de un CSV, las
    filas antes de la cabecera, el separador decimal y el formato de las fechas."""

    encoding: str
    separator: str
    header_row: int
    decimal: str
    date_format: str | None

    def reading(self, reader: str, sheet: str | None) -> dict[str, Any]:
        """Los ajustes de lectura de una entrada (``drillholes.provenance.READING_SETTINGS``:
        de un CSV, su codificación, su separador y su cabecera; de una hoja, su nombre y su
        cabecera; de una base de RecMin, ninguno)."""
        if reader == provenance.RECMIN_MDB:
            return {}
        if reader == provenance.DH_XLSX:
            return {"sheet": sheet or "", "header_row": self.header_row}
        return {"encoding": self.encoding, "separator": self.separator,
                "header_row": self.header_row}

    def job_settings(self, reader: str, sheet: str | None) -> dict[str, Any]:
        """Los ajustes de la lectura de su trabajo: los de :meth:`reading`, el decimal y el
        formato de las fechas (una base de RecMin, solo el decimal)."""
        if reader == provenance.RECMIN_MDB:
            return {"decimal": self.decimal}
        return {**self.reading(reader, sheet), "decimal": self.decimal,
                "date_format": self.date_format}


@dataclass(frozen=True)
class TableChoice:
    """Una tabla de una importación (D-15: una entrada): su fichero, su lector, su papel
    (``""`` si no se sabe; una base de RecMin no tiene), su correspondencia de columnas
    (campo → columna), su hoja (de un XLSX), el nombre lógico de su entrada y sus columnas."""

    path: Path
    reader: str
    role: str
    mapping: Mapping[str, str]
    sheet: str | None = None
    name: str = ""
    columns: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        """Cómo se nombra: su fichero y, si es de un XLSX, su hoja."""
        return f"{self.path.name} · {self.sheet}" if self.sheet else self.path.name


def entry_name(path: Path, sheet: str | None = None) -> str:
    """El nombre lógico de la entrada de un fichero (sin la extensión) o de una hoja de un
    XLSX («libro · hoja»)."""
    return f"{path.stem} · {sheet}" if sheet else path.stem


def reader_of(path: Path) -> str:
    """El lector de una tabla de sondeos por su extensión; ``ValueError`` con el aviso si no es
    un CSV, un TXT ni un XLSX."""
    found = READERS.get(Path(path).suffix.lower())
    if found is None:
        raise ValueError(tr("«{file}» is not a CSV, TXT or XLSX file: choose the drillhole "
                            "tables to import", file=Path(path).name))
    return found


_PREVIEWS: dict[tuple[Any, ...], Table] = {}
"""Las primeras filas de las tablas que enseña el asistente, por fichero (su tamaño y su
fecha), hoja y ajustes de lectura."""


def preview(choice: TableChoice, options: ReadOptions) -> Table:
    """Las primeras filas de la tabla de ``choice`` leídas con ``options``
    (``interop.csv_tables.preview_table`` o ``interop.xlsx_tables.preview_sheet``), con su
    cabecera; los errores de lectura, los suyos."""
    path = Path(choice.path)
    info = path.stat()
    key = (str(path), info.st_size, info.st_mtime_ns, choice.reader, choice.sheet, options)
    found = _PREVIEWS.get(key)
    if found is None:
        if choice.reader == provenance.DH_XLSX:
            found = xlsx_tables.preview_sheet(path, choice.sheet or "",
                                              header_row=options.header_row,
                                              decimal_mark=options.decimal,
                                              date_format=options.date_format)
        else:
            found = csv_tables.preview_table(path, encoding=options.encoding,
                                             separator=options.separator,
                                             header_row=options.header_row)
        if len(_PREVIEWS) >= _PREVIEWS_KEPT:
            _PREVIEWS.clear()
        _PREVIEWS[key] = found
    return found


def suggested_tables(paths: Sequence[Path], options: ReadOptions, *,
                     sheet: str | None = None) -> list[TableChoice]:
    """Las tablas de los ficheros ``paths`` con su papel y su correspondencia propuestos
    (``interop.drillholes_tabular.suggest_role`` por el nombre del fichero o de la hoja, y
    ``suggest_mapping``; RF-005-05): una por CSV o TXT y, de un XLSX, una por hoja de datos (o
    solo ``sheet``). Un papel que no se sabe queda ``""``."""
    found: list[TableChoice] = []
    for given in paths:
        path = Path(given)
        reader = reader_of(path)
        if reader == provenance.DH_XLSX:
            sheets: list[str | None] = [sheet] if sheet else list(xlsx_tables.list_sheets(path))
        else:
            sheets = [None]
        for chosen in sheets:
            probe = TableChoice(path, reader, "", {}, chosen, entry_name(path, chosen))
            table = preview(probe, options)
            role = tabular.suggest_role(chosen or path.name, table.columns)
            mapping = {} if role is None else tabular.suggest_mapping(role, table.columns)
            found.append(dataclasses.replace(probe, role="" if role is None else str(role),
                                             mapping=mapping, columns=tuple(table.columns)))
    return found


def json_tables(text: str, directory: Path | None, options: ReadOptions) -> list[TableChoice]:
    """Las tablas de ``mapping_json`` (para guiones y pruebas): una lista de objetos con su
    fichero (``file``, relativo a ``directory``), su papel (``role``, uno de
    ``drillholes.provenance.TABLE_ROLES``) y, si se quiere, su correspondencia (``mapping``;
    si no, la propuesta), su hoja (``sheet``, obligatoria en un XLSX) y el nombre de su entrada
    (``name``). ``ValueError`` con el aviso si no lo es."""
    try:
        data = json.loads(text)
    except ValueError:
        raise ValueError(tr("The column mapping (mapping_json) is not JSON")) from None
    items = data if isinstance(data, list) else [data]
    found: list[TableChoice] = []
    for item in items:
        if (not isinstance(item, Mapping) or not isinstance(item.get("file"), str)
                or not isinstance(item.get("role"), str)):
            raise ValueError(tr("Each table of the column mapping (mapping_json) says its file "
                                "and its role: {item}",
                                item=json.dumps(item, ensure_ascii=False)))
        path = Path(item["file"])
        if not path.is_absolute():
            path = (directory or Path.cwd()) / path
        reader = reader_of(path)
        role = item["role"].strip().lower()
        if role not in ROLES.values():
            raise ValueError(tr("«{role}» is not the role of a drillhole table: it is one of "
                                "{roles}", role=item["role"], roles=", ".join(ROLES.values())))
        sheet = item.get("sheet") or None
        if reader == provenance.DH_XLSX and not sheet:
            raise ValueError(tr("Say the sheet of «{file}» in the column mapping",
                                file=path.name))
        probe = TableChoice(path, reader, role, {}, sheet,
                            str(item.get("name") or entry_name(path, sheet)))
        table = preview(probe, options)
        mapping = item.get("mapping") or tabular.suggest_mapping(role, table.columns)
        found.append(dataclasses.replace(probe, mapping=dict(mapping),
                                         columns=tuple(table.columns)))
    return found


def check_declarations(choices: Sequence[TableChoice], declaration: SourceDeclaration,
                       options: ReadOptions) -> None:
    """RF-005-07: lo que las tablas necesitan que se declare (``interop.drillholes_tabular.
    needs`` de sus primeras filas) y no está en ``declaration``:
    ``interop.base.DeclarationError``, que lo nombra todo; una correspondencia que no vale,
    su ``MappingError``."""
    needs = Needs()
    for choice in choices:
        needs = needs | tabular.needs(choice.role, preview(choice, options), choice.mapping)
    missing = missing_declarations(declaration, needs)
    if missing:
        raise DeclarationError(tabular.SOURCE_LABEL, missing)


_FLAG_SIGNS: Mapping[str, str] = MappingProxyType({
    str(DetectionFlag.BELOW_DL): "<", str(DetectionFlag.ABOVE_UL): ">"})
"""Cómo se enseña la marca de un valor de un análisis («<0,01», «>100»)."""


def _shown_value(values: Any, row: int) -> str:
    """Un valor leído de una columna para la vista previa."""
    value = values[row]
    if isinstance(value, str):
        return value
    if value is None:
        return "—"
    return _number(value.item() if hasattr(value, "item") else value)


def _records(rows: Any, role: str) -> list[str]:
    """Los registros de una tabla leída (``RoleRows``) en texto, como los ve el asistente:
    los números con el separador decimal del idioma; un valor bajo el límite de detección,
    con su «<»."""
    if role == "lithology_catalog":
        return [" · ".join((code.code, code.color, _number(code.density)))
                for code in rows.catalogs.lithology]
    if role == "element_catalog":
        return [" · ".join((element.code, element.unit))
                for element in rows.catalogs.elements]
    part, names = {
        "collar": (rows.collars, ("name", "x", "y", "z", "depth")),
        "survey": (rows.surveys, ("hole_name", "depth", "azimuth", "inclination")),
        "lithology": (rows.lithology, ("hole_name", "from_m", "to_m", "code")),
    }.get(role, (rows.assays, ("hole_name", "from_m", "to_m", "element", "value", "unit")))
    flags = None
    if part is rows.assays:
        codes = type(part).code_values("detection_flag")
        flags = [str(codes[code]) if code >= 0 else "" for code in part.detection_flag.tolist()]
    lines = []
    for row in range(len(part)):
        shown = []
        for name in names:
            text = _shown_value(getattr(part, name), row)
            if name == "value" and flags is not None:
                text = _FLAG_SIGNS.get(flags[row], "") + text
            shown.append(text)
        lines.append(" · ".join(shown))
    return lines


def preview_lines(choice: TableChoice, options: ReadOptions,
                  declaration: SourceDeclaration) -> list[str]:
    """Las primeras filas de la tabla de ``choice`` tal como se van a interpretar (RF-005-05):
    sus registros leídos con la correspondencia y la declaración (números con el separador
    decimal del idioma) y sus rechazos; si falta una declaración o la correspondencia no vale,
    qué pasa."""
    try:
        rows = tabular.read_role(choice.role, preview(choice, options), choice.mapping,
                                 declaration)
    except DeclarationError as exc:
        return [tr("Missing declarations: {missing}", missing=spanish_list(exc.missing))]
    except (GeoblenderError, ValueError) as exc:
        return [error_text(exc)]
    lines = _records(rows, choice.role)[:PREVIEW_LINES]
    lines += [tr("Row {row}, {field}: {reason}", row=item.row, field=item.field,
                 reason=item.reason) for item in rows.rejected]
    return lines


def _table_choice(table: Any) -> TableChoice:
    """La tabla del asistente ``table`` (``GEOBLENDER_PG_dh_table``) como :class:`TableChoice`
    (``ValueError`` si dos columnas dan el mismo campo)."""
    path = Path(table.path)
    sheet = table.sheet or None
    return TableChoice(path, reader_of(path), ROLES.get(table.role, ""), table_mapping(table),
                       sheet, table.entry or entry_name(path, sheet),
                       tuple(column.name for column in table.columns))


# --- La importación en marcha (T25; plan §5.6.5) ------------------------------------------------

_SUCCEEDED = "succeeded"  # el final de un trabajo que terminó bien (jobs.records)
DISCARDED = "La persona descartó la importación de los sondeos"
"""El motivo (en español, como los demás motivos guardados) de una importación descartada."""
OTHER_FAILED = "Otra tabla de la misma importación no se leyó o no se aplicó: {name}"
"""El motivo de las demás importaciones de una orden cuando una falla (RF-005-04)."""
NOT_STARTED = "Otra tabla de la misma importación no pudo empezar: {name}"
"""El motivo de las importaciones de una orden ya empezadas cuando otra no puede empezar."""
DUPLICATES_WARNING = "Sondeos repetidos en la fuente (DH-E01; no pasan a la base): {holes}"
"""El aviso de ``dh_import_log`` de unas bocas repetidas en la fuente."""
REJECTIONS_SHOWN = 50
"""Los registros rechazados que se citan en el informe de una entrada."""
NAMES_SHOWN = 20
"""Los sondeos que ya están en el proyecto que se citan en el aviso de una importación que
espera (el panel los lista todos)."""
_MAIN_TABLES: Mapping[str, str] = MappingProxyType({
    "collar": "collars", "survey": "surveys", "lithology": "lithology",
    "assay_wide": "assays", "assay_long": "assays"})
"""La tabla de lo leído que cuenta los registros de cada papel (los catálogos, sus filas)."""


@dataclass(eq=False)
class _Entry:
    """Una entrada de una orden de importación (un fichero o una hoja): su tabla, su
    operación, su lectura y su resultado, su entrada (``InputSpec``), cómo se clasificó y su
    aplicación."""

    choice: TableChoice
    handle: OperationHandle
    started: bool = False
    read: JobResult | None = None
    outcome: Any = None
    spec: Any = None
    reused: bool = False
    previous_uid: str | None = None
    substitute: str = ""
    applying: bool = False
    applied: JobResult | None = None


@dataclass(eq=False)
class _Order:
    """Una orden de importación de sondeos en marcha (de tablas o de una base de RecMin): sus
    entradas, lo declarado, cómo se leen, los catálogos y los sondeos del proyecto al empezar,
    la entrega, el motivo de una sustitución, la orden que la aplica o la descarta, lo que hay
    que decidir (también lo que hay que confirmar antes de leer, RF-005-15) y lo decidido. La
    reimportación de una entrada (``reimport``, T28; RF-008-11) sustituye sin preguntar los
    sondeos que ya traía (``replaced``)."""

    entries: list[_Entry]
    declaration: SourceDeclaration
    options: ReadOptions
    catalogs: Catalogs
    project_holes: tuple[str, ...]
    received_at: Any = None
    received_from: str | None = None
    reason: str | None = None
    command: str = IMPORT_DRILLHOLES
    accept_schema: bool = False
    failure: str = ""
    failure_text: str = ""
    confirm: str = ""
    codes: dict[str, list[Any]] = field(default_factory=dict)
    holes: list[str] = field(default_factory=list)
    keep: tuple[str, ...] = ()
    register: bool = False
    reimport: bool = False
    replaced: tuple[str, ...] = ()

    @property
    def uid(self) -> str:
        """El uid de la orden: el de su primera operación."""
        return self.entries[0].handle.uid

    @property
    def live(self) -> list[_Entry]:
        """Las entradas que siguen en la orden (lanzadas y no reutilizadas)."""
        return [entry for entry in self.entries if entry.started and not entry.reused]


_ORDERS: dict[str, _Order] = {}
"""Las órdenes de importación en marcha, por su uid."""
_WAITING: list[str] = []
"""Las que esperan la decisión de la persona, por orden de llegada (el panel enseña la
primera)."""


def waiting_imports() -> dict[str, str]:
    """Las importaciones de sondeos que esperan la decisión de la persona («Importación
    pendiente»): el uid de su orden (el de su primera operación) y lo que hay que decidir."""
    return {uid: _decision_text(_ORDERS[uid]) for uid in _WAITING if uid in _ORDERS}


def _code_key(kind: str, item: Any) -> Any:
    if kind == "lithology":
        return name_key(item[0]), name_key(item[1])
    if kind == "element":
        return name_key(item[0])
    return name_key(item)


def _code_text(kind: str, item: Any) -> str:
    """Cómo se enseña un código nuevo: el suyo; el de una litología de otro esquema de logueo
    que la litología (las tablas adicionales de RecMin), con su esquema («SIL · recmin_…»)."""
    if kind == "lithology":
        if name_key(item[0]) != LITHOLOGY_LOG_SET:
            return f"{item[1]} · {item[0]}"
        return str(item[1])
    if kind == "element":
        return str(item[0])
    return str(item)


def _codes_text(codes: Mapping[str, Sequence[Any]]) -> str:
    """Los códigos nuevos por catálogo: «SUE, ARC (litologías); Au, Cu (elementos)»."""
    return "; ".join(f"{', '.join(_code_text(kind, item) for item in items)} "
                     f"({_text(_KIND_MSGIDS[kind])})" for kind, items in codes.items() if items)


def _decision_text(order: _Order) -> str:
    """Lo que hay que decidir de ``order``: lo que hay que confirmar antes de leer, los códigos
    nuevos, los sondeos que ya están en el proyecto y las sustituciones sin motivo."""
    parts: list[str] = [order.confirm] if order.confirm else []
    if order.codes:
        parts.append(tr("New codes: {codes}", codes=_codes_text(order.codes)))
    if order.holes:
        shown = ", ".join(order.holes[:NAMES_SHOWN])
        if len(order.holes) > NAMES_SHOWN:
            shown = tr("{names} and {count} more", names=shown,
                       count=format_number(len(order.holes) - NAMES_SHOWN, 0))
        parts.append(tr("Drillholes already in the project: {holes}", holes=shown))
    parts.extend(entry.substitute for entry in order.live if entry.substitute)
    return "\n".join(parts)


def _end(handle: OperationHandle, reason: str, *, failed: bool = False) -> None:
    """Deja cancelada (o fallida) con su motivo la operación ``handle`` si sigue «en curso»."""
    try:
        if failed:
            handle.fail(reason)
        else:
            handle.cancel(reason)
    except (GeoblenderError, TypeError, ValueError):
        pass  # ya terminó, o el proyecto no se puede escribir


def _release(result: JobResult | None) -> None:
    """Da por incorporado el trabajo de ``result`` si aún está pendiente."""
    if result is not None and result.job_uid in core_provenance.pending_ingests():
        core_provenance.release_job(result.job_uid)


def _abandon(order: _Order, reason: str, *, failed: bool = False,
             said: str | None = None) -> None:
    """La orden ``order`` no se escribe (RF-005-04): cada importación que sigue «en curso»
    queda cancelada (o fallida) con ``reason`` (las que no se leyeron o no se aplicaron, con
    el motivo de la 004), sus trabajos se dan por incorporados y la orden se olvida. El aviso
    dice ``said`` (por defecto, ``reason``)."""
    for entry in order.entries:
        ended = any(result is not None and result.state != _SUCCEEDED
                    for result in (entry.read, entry.applied))
        if entry.started and not entry.reused and not ended:
            _end(entry.handle, reason, failed=failed)
        elif not entry.started:
            _end(entry.handle, reason)
        for result in (entry.read, entry.applied):
            if result is not None and result.state == _SUCCEEDED:
                _release(result)
    _ORDERS.pop(order.uid, None)
    if order.uid in _WAITING:
        _WAITING.remove(order.uid)
        _show_pending()
    _say(tr("The import of the drillholes has not been written: {reason}",
            reason=said or reason))


def _show_pending() -> None:
    """La primera importación que espera la decisión, en «Importación pendiente»
    (``WindowManager.geoblender_dh_import``), con la orden que la aplica o la descarta; sin
    ninguna, vacía."""
    manager = getattr(bpy.context, "window_manager", None)
    pending = getattr(manager, IMPORT_PROPERTY, None)
    if pending is None:
        return
    order = next((_ORDERS[uid] for uid in _WAITING if uid in _ORDERS), None)
    pending.holes.clear()
    pending.operation_uid = "" if order is None else order.uid
    pending.command = "" if order is None else order.command
    pending.confirm = "" if order is None else order.confirm
    pending.new_codes = "" if order is None else _codes_text(order.codes)
    pending.register_codes = True
    pending.question = "" if order is None else "\n".join(
        entry.substitute for entry in order.live if entry.substitute)
    pending.reason = "" if order is None else order.reason or ""
    for name in ([] if order is None else order.holes):
        item = pending.holes.add()
        item.name = name
        item.keep = False
    _redraw()


def _is_recmin(choice: TableChoice) -> bool:
    """Si la entrada es una base de RecMin (sin papel ni correspondencia)."""
    return choice.reader == provenance.RECMIN_MDB


def _input_spec(order: _Order, entry: _Entry) -> Any:
    """La entrada de una tabla (o de una base de RecMin) con lo que trae el resumen de su
    lectura: su ``ContentDigest``, la huella de su fichero y su ancla (RF-008-07)."""
    project = entry.handle.project
    found = entry.outcome.summary["source"]
    main = found["files"]["main"]
    anchor = locate_source(entry.choice.path, project, project.userdata, role="main")
    prints = [SourcePrint(main["sha256"], size=main["size"], mtime_ns=main["mtime_ns"])]
    recmin = _is_recmin(entry.choice)
    return provenance.input_spec(
        entry.choice.reader, entry.choice.name, files=[anchor], file_prints=prints,
        digest=gis_jobs.digest_of(found["digest"]), declaration=order.declaration,
        role=None if recmin else entry.choice.role,
        mapping=None if recmin else dict(entry.choice.mapping),
        settings=order.options.reading(entry.choice.reader, entry.choice.sheet),
        received_at=order.received_at, received_from=order.received_from)


def _operation_settings(choice: TableChoice, declaration: SourceDeclaration,
                        options: ReadOptions) -> dict[str, Any]:
    """Los ajustes de la operación de una entrada: su nombre, su fichero (sin su ruta), su
    lector, su papel y su correspondencia (una base de RecMin no tiene), los de lectura y lo
    declarado (las claves de :data:`SETTING_DEFS`; los valores sin dato, su texto «−99;ND»)."""
    conventions = declaration.conventions()
    conventions["sentinels"] = ";".join(conventions["sentinels"])
    if _is_recmin(choice):
        return {"name": choice.name, "file": choice.path.name, "reader": choice.reader,
                "decimal": options.decimal, **conventions}
    return {"name": choice.name, "file": choice.path.name, "reader": choice.reader,
            "role": choice.role, "mapping": dict(choice.mapping),
            **options.reading(choice.reader, choice.sheet), "decimal": options.decimal,
            "date_format": options.date_format, **conventions}


def _read_job(order: _Order, entry: _Entry) -> dict[str, Any]:
    """Lo que lanza la lectura de una entrada (``launch_job``): su trabajo
    (``dh_import_tabular`` o ``dh_import_recmin``, con lo declarado, los ajustes de lectura,
    los CRS del proyecto, sus sondeos y sus catálogos), su fichero por ``paths`` y, al
    terminar, :func:`_read_finished`."""
    choice = entry.choice
    crs, vertical = gis_store.project_references(entry.handle.project)
    params: dict[str, Any] = {
        "name": choice.name, "declaration": jobs.declaration_json(order.declaration),
        "settings": order.options.job_settings(choice.reader, choice.sheet),
        "crs": gis_jobs.crs_json(crs), "vertical": gis_jobs.vertical_json(vertical),
        "project_holes": list(order.project_holes), "catalogs": catalogs_json(order.catalogs),
        "size": choice.path.stat().st_size}
    if _is_recmin(choice):
        worker = jobs.IMPORT_RECMIN
        params["accept_schema"] = order.accept_schema
    else:
        worker = jobs.IMPORT_TABULAR
        params.update(reader=choice.reader, role=choice.role, mapping=dict(choice.mapping))
    return {"worker": worker, "label": tr("Reading «{name}»", name=choice.label),
            "params": params, "paths": {gis_jobs.path_name("main"): choice.path},
            "on_finish": functools.partial(_read_finished, order, entry),
            "grace_s": jobs.CANCEL_GRACE_S}


def start_order(operator: Any, context: Any, project: Any, choices: Sequence[TableChoice],
                declaration: SourceDeclaration, options: ReadOptions, *,
                received_at: Any = None, received_from: str | None = None,
                reason: str | None = None, accept_schema: bool = False,
                command: str = IMPORT_DRILLHOLES) -> set[str]:
    """Empieza la importación de ``choices`` con la orden ``operator`` (una operación de su
    tipo por tabla, o por la base de RecMin, con la puerta de la 008, y su lectura; la de una
    base de RecMin de esquema desconocido, ya confirmada si ``accept_schema``); devuelve el
    final de la orden. ``command``: el ``bl_idname`` de la orden, la que aplica o descarta lo
    que espere la decisión de la persona. Si una no puede empezar, las demás quedan
    canceladas."""
    with project.read() as conn:
        catalogs = store.read_catalogs(conn)
        holes = store.existing_holes(conn)
    order = _Order([], declaration, options, catalogs, holes, received_at, received_from,
                   reason, command=command, accept_schema=accept_schema)
    for choice in choices:
        handle = operator.begin(context, settings=_operation_settings(choice, declaration,
                                                                      options),
                                executor="job_process")
        if handle is None:  # ya dicho por qué
            for entry in order.entries:
                _end(entry.handle, NOT_STARTED.format(name=choice.label))
            return {"CANCELLED"}
        order.entries.append(_Entry(choice, handle))
    _ORDERS[order.uid] = order
    for entry in order.entries:
        choice = entry.choice
        launch = _read_job(order, entry)
        job = operator.launch_job(entry.handle, launch.pop("worker"), **launch)
        if job is None:  # la operación queda fallida con el motivo (ya dicho)
            order.failure = choice.label
            break
        entry.started = True
    if order.failure:
        for entry in order.entries:
            if not entry.started:
                _end(entry.handle, OTHER_FAILED.format(name=order.failure))
        if not any(entry.started for entry in order.entries):
            _ORDERS.pop(order.uid, None)
        return {"CANCELLED"}
    return {"FINISHED"}


def _read_finished(order: _Order, entry: _Entry, result: JobResult) -> None:
    """El final de la lectura de una entrada: cuando terminan todas las de la orden, se sigue
    (:func:`_after_reading`)."""
    entry.read = result
    if result.state != _SUCCEEDED and not order.failure:
        order.failure = entry.choice.label
        order.failure_text = result.error_text or ""
    if all(item.read is not None for item in order.entries if item.started):
        try:
            _after_reading(order)
        except Exception as error:  # noqa: BLE001 - la orden no sigue: nada escrito
            LOGGER.exception("La importación de sondeos %s se ha parado", order.uid)
            _abandon(order, error_text(error), failed=True)


def _confirmation(entry: _Entry) -> str:
    """Lo que hay que confirmar antes de leer una base de RecMin (RF-005-15: una versión de
    esquema que no es 11 ni 12), si su lectura terminó sin leerla; si no, ``""``."""
    found = entry.outcome.summary.get("needs_confirmation") if entry.outcome else None
    if not found:
        return ""
    return tr("{warning}. Confirm it to read «{name}» anyway", warning=str(found["text"]),
              name=entry.choice.label)


def _after_reading(order: _Order) -> None:
    """Leídas todas las entradas: si una falló, la orden no sigue (RF-005-04); si una base de
    RecMin necesita una confirmación antes de leerla (RF-005-15), la orden la espera; si no,
    cada una se clasifica (RF-008-54: reutilizada, cancelada con el aviso; los mismos datos con
    otros ajustes, una sustitución) y, si hay algo que decidir (códigos nuevos, sondeos que ya
    están o una sustitución sin motivo), la orden espera; si no, se aplica."""
    if order.failure:
        said = None
        if order.failure_text:
            said = tr("«{name}» has not been read: {reason}", name=order.failure,
                      reason=order.failure_text)
        _abandon(order, OTHER_FAILED.format(name=order.failure), said=said)
        return
    project = order.entries[0].handle.project
    language = i18n.language()
    for entry in order.live:
        entry.outcome = job_outcome(entry.read, entry.read.job_dir)
    order.confirm = "\n".join(text for text in map(_confirmation, order.live) if text)
    if order.confirm:
        _WAITING.append(order.uid)
        _show_pending()
        _say(tr("The import of the drillholes waits for your decision in Drillholes ▸ "
                "Pending import:\n{decision}", decision=_decision_text(order)))
        return
    for entry in order.live:
        entry.spec = _input_spec(order, entry)
    with project.read() as conn:  # una reimportación ya sabe a qué entrada sustituye
        classified = [(entry, classify_import(conn, entry.spec)) for entry in order.live
                      if entry.previous_uid is None]
    for entry, found in classified:
        if isinstance(found, Reuse):
            reuse_input(project, entry.handle, found)  # cancelada con el aviso
            entry.reused = True
            _release(entry.read)
            _say(found.render(language))
        elif isinstance(found, Substitute):
            entry.previous_uid = found.input.uid
            entry.substitute = tr("«{name}» has the same data as the input «{existing}» with "
                                  "other settings ({differences}): write why it replaces it",
                                  name=entry.choice.name, existing=found.input.name,
                                  differences=found.describe(language))
    if not order.live:
        _ORDERS.pop(order.uid, None)
        return
    order.codes, order.holes = _decisions(order)
    if order.reimport:  # los sondeos que ya traía la entrada se sustituyen sin preguntar
        known = {name_key(name) for name in order.replaced}
        order.replaced = tuple(name for name in order.holes if name_key(name) in known)
        order.holes = [name for name in order.holes if name_key(name) not in known]
    unexplained = any(entry.substitute for entry in order.live) and not order.reason
    if order.codes or order.holes or unexplained:
        _WAITING.append(order.uid)
        _show_pending()
        _say(tr("The import of the drillholes waits for your decision in Drillholes ▸ "
                "Pending import:\n{decision}", decision=_decision_text(order)))
        return
    _apply(order)


def _decisions(order: _Order) -> tuple[dict[str, list[Any]], list[str]]:
    """Lo que hay que decidir de ``order``: los códigos nuevos de sus entradas (cómo se darían
    de alta, sin repetir; RF-005-10) y los sondeos que el proyecto ya tiene (RF-005-11)."""
    codes: dict[str, list[Any]] = {}
    seen: dict[str, set[Any]] = {}
    holes: dict[str, str] = {}
    for entry in order.live:
        summary = entry.outcome.summary
        for kind, items in dict(summary.get("register_codes") or {}).items():
            for item in items:
                key = _code_key(kind, item)
                if key not in seen.setdefault(kind, set()):
                    seen[kind].add(key)
                    codes.setdefault(kind, []).append(item)
        for name in summary.get("existing_holes") or ():
            holes.setdefault(name_key(name), name)
    return codes, list(holes.values())


def _register_for(order: _Order, entry: _Entry) -> dict[str, list[Any]]:
    """Los códigos nuevos que da de alta la entrada ``entry``: los suyos, salvo los que trae
    un catálogo de la misma orden (con su color y su unidad: RF-005-10)."""
    found = dict(entry.outcome.summary.get("register_codes") or {})
    if entry.choice.role in _CATALOG_ROLES:
        return found
    provided: dict[str, set[Any]] = {}
    for other in order.live:
        if other.choice.role in _CATALOG_ROLES:
            for kind, items in dict(other.outcome.summary.get("register_codes") or {}).items():
                provided.setdefault(kind, set()).update(_code_key(kind, item) for item in items)
    chosen = {kind: [item for item in items
                     if _code_key(kind, item) not in provided.get(kind, set())]
              for kind, items in found.items()}
    return {kind: items for kind, items in chosen.items() if items}


def _imported(summary: Mapping[str, Any]) -> int:
    """Los registros importados de la lectura de una entrada: los de su tabla o, de una base
    de RecMin, los de todas (sus recuentos van por tabla de RecMin)."""
    counts = dict(summary.get("counts") or {})
    if "imported" in counts:
        return int(counts["imported"])
    return sum(int(dict(found).get("imported", 0)) for found in counts.values())


def _apply(order: _Order) -> None:
    """Aplica las entradas de ``order`` con lo decidido (``dh_import_apply``: los sondeos que
    se conservan fuera, los que se sustituyen contados, los códigos nuevos dados de alta)."""
    project = order.entries[0].handle.project
    crs, _vertical = gis_store.project_references(project)
    keep = {name_key(name) for name in order.keep}
    replace = [name for name in order.holes if name_key(name) not in keep]
    replace += order.replaced
    taken = [code.color for code in order.catalogs.lithology]
    for entry in order.live:
        params = {"name": entry.choice.name, "crs": gis_jobs.crs_json(crs),
                  "keep_holes": list(order.keep), "replace_holes": replace,
                  "register_codes": _register_for(order, entry) if order.register else {},
                  "taken_colors": taken, "count": _imported(entry.outcome.summary) + 1}
        try:
            core_provenance.launch_job(
                entry.handle, jobs.IMPORT_APPLY,
                label=tr("Import of «{name}»", name=entry.choice.label), params=params,
                inputs={jobs.INPUT_SOURCE: entry.outcome.file(jobs.OUT_SOURCE.role)},
                on_finish=functools.partial(_apply_finished, order, entry),
                grace_s=jobs.CANCEL_GRACE_S)
        except Exception as error:  # noqa: BLE001 - la operación queda fallida con el motivo
            LOGGER.warning("No se pudo aplicar «%s»", entry.choice.label, exc_info=True)
            order.failure = order.failure or entry.choice.label
            if not any(item.applying for item in order.live):
                _abandon(order, error_text(error))
            return
        entry.applying = True


def _apply_finished(order: _Order, entry: _Entry, result: JobResult) -> None:
    """El final de la aplicación de una entrada: cuando terminan todas, la incorporación por
    pasos (:func:`_import_steps`) o, si una falló, nada (RF-005-04)."""
    entry.applied = result
    if result.state != _SUCCEEDED and not order.failure:
        order.failure = entry.choice.label
    if not all(item.applied is not None for item in order.live if item.applying):
        return
    if order.failure:
        _abandon(order, OTHER_FAILED.format(name=order.failure))
        return
    INCORPORATIONS.add(order.uid, tr("Drillhole import"), _import_steps(order))


def _read_report(entry: _Entry) -> dict[str, Any]:
    """El informe de la lectura de una entrada (``report.json``)."""
    path = entry.outcome.file(jobs.OUT_REPORT.role)
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _counts(entry: _Entry, report: Mapping[str, Any],
            applied: Mapping[str, Any]) -> tuple[int, int, int, int]:
    """Leídos, importados, rechazados y sustituidos de la tabla de una entrada (RF-005-12)."""
    counts = dict(report.get("counts") or {})
    main = _MAIN_TABLES.get(entry.choice.role)
    removed = int(dict(applied.get("removed") or {}).get(main, 0)) if main else 0
    replaced = int(dict(applied.get("replaced") or {}).get(main, 0)) if main else 0
    return (int(counts.get("read", 0)), max(int(counts.get("imported", 0)) - removed, 0),
            int(counts.get("rejected", 0)), replaced)


def _recmin_counts(order: _Order,
                   report: Mapping[str, Any]) -> list[tuple[str, int, int, int, int]]:
    """Por tabla de una base de RecMin: leídos, importados, rechazados y sustituidos
    (RF-005-12). Los registros de los sondeos que ya estaban y se conservan no se importan, y
    los de los que se sustituyen se cuentan (``hole_rows`` de su lectura: los de cada sondeo
    que ya estaba, por tabla)."""
    keep = {name_key(name) for name in order.keep}
    replace = {name_key(name) for name in (*order.holes, *order.replaced)} - keep
    rows = dict(report.get("hole_rows") or {})
    found = []
    for table, counts in dict(report.get("counts") or {}).items():
        per_hole = dict(rows.get(table) or {})
        kept = sum(int(n) for hole, n in per_hole.items() if name_key(hole) in keep)
        replaced = sum(int(n) for hole, n in per_hole.items() if name_key(hole) in replace)
        found.append((str(table), int(counts.get("read", 0)),
                      max(int(counts.get("imported", 0)) - kept, 0),
                      int(counts.get("rejected", 0)), replaced))
    return found


def _log_lines(order: _Order, entry: _Entry, report: Mapping[str, Any],
               applied: Mapping[str, Any]) -> list[store.LogLine]:
    """El informe de una entrada en ``dh_import_log`` (RF-005-12): sus recuentos (de una base
    de RecMin, por cada una de sus tablas), cada registro rechazado con su motivo y los
    avisos."""
    if _is_recmin(entry.choice):  # sus avisos ya dicen los sondeos repetidos (DH-E01)
        lines = [store.LogLine.summary(*counts) for counts in _recmin_counts(order, report)]
        lines += [store.LogLine.rejection(Rejection(*item))
                  for item in report.get("rejected", ())]
        lines += [store.LogLine.warning(RECMIN_LABEL, str(text))
                  for text in report.get("warnings", ())]
        return lines
    role = entry.choice.role
    read, imported, rejected, replaced = _counts(entry, report, applied)
    lines = [store.LogLine.summary(role, read, imported, rejected, replaced)]
    lines += [store.LogLine.rejection(Rejection(*item)) for item in report.get("rejected", ())]
    lines += [store.LogLine.warning(role, str(text)) for text in report.get("warnings", ())]
    lines += [store.LogLine.warning(role, DUPLICATES_WARNING.format(holes=", ".join(group)))
              for group in report.get("duplicate_holes", ())]
    return lines


def _recmin_report(order: _Order, entry: _Entry, report: Mapping[str, Any]) -> str:
    """El informe de una base de RecMin (su mensaje y el aviso de la sesión; RF-005-12): su
    fichero, su versión de esquema, los recuentos de cada tabla, su hash de contenido, los
    rechazos (los primeros, con su tabla) y los avisos."""
    version = report.get("schema_version")
    tables = "; ".join(
        tr("{table}: {read} read, {imported} imported, {rejected} rejected, {replaced} "
           "replaced", table=table, read=format_number(read, 0),
           imported=format_number(imported, 0), rejected=format_number(rejected, 0),
           replaced=format_number(replaced, 0))
        for table, read, imported, rejected, replaced in _recmin_counts(order, report))
    lines = [tr("RecMin drillhole database «{file}» (schema {version}) imported as «{name}»: "
                "{tables}; content hash {digest}", file=entry.choice.label,
                version="—" if version is None else str(version), name=entry.choice.name,
                tables=tables, digest=entry.spec.digest.content_sha256[:12])]
    items = list(report.get("rejected", ()))
    lines += [tr("{table}, row {row}, {field}: {reason}", table=item[0], row=item[1],
                 field=item[2], reason=item[4]) for item in items[:REJECTIONS_SHOWN]]
    if len(items) > REJECTIONS_SHOWN:
        lines.append(tr("… and {count} more rejected",
                        count=format_number(len(items) - REJECTIONS_SHOWN, 0)))
    lines += [str(text) for text in report.get("warnings", ())]
    return "\n".join(lines)


def _entry_report(order: _Order, entry: _Entry, report: Mapping[str, Any],
                  applied: Mapping[str, Any]) -> str:
    """El informe de una entrada (su mensaje y el aviso de la sesión; RF-005-12): su tabla y
    su papel, sus recuentos, el hash de contenido de su fichero, los rechazos (los primeros) y
    los avisos; el de una base de RecMin, :func:`_recmin_report`."""
    if _is_recmin(entry.choice):
        return _recmin_report(order, entry, report)
    read, imported, rejected, replaced = _counts(entry, report, applied)
    lines = [tr("Drillhole table «{file}» ({role}) imported as «{name}»: {read} rows read, "
                "{imported} records imported, {rejected} rejected, {replaced} replaced; "
                "content hash {digest}", file=entry.choice.label,
                role=_text(_ROLE_MSGIDS[entry.choice.role]), name=entry.choice.name,
                read=format_number(read, 0), imported=format_number(imported, 0),
                rejected=format_number(rejected, 0), replaced=format_number(replaced, 0),
                digest=entry.spec.digest.content_sha256[:12])]
    items = list(report.get("rejected", ()))
    lines += [tr("Row {row}, {field}: {reason}", row=item[1], field=item[2], reason=item[4])
              for item in items[:REJECTIONS_SHOWN]]
    if len(items) > REJECTIONS_SHOWN:
        lines.append(tr("… and {count} more rejected",
                        count=format_number(len(items) - REJECTIONS_SHOWN, 0)))
    lines += [str(text) for text in report.get("warnings", ())]
    return "\n".join(lines)


def _import_steps(order: _Order) -> Generator[float, None, str]:
    """Los pasos que escriben la orden ``order`` aplicada (RF-005-04, RF-005-12; plan §5.6.5),
    con su avance (0–1): lo importado de cada entrada (las filas y el hash que dio su
    aplicación, su informe) en una transacción por pasos (``drillholes.store.SourceWriter``);
    confirmada, el original de cada fichero desde la copia verificada de su lectura
    (RF-008-53), sus trabajos dados por incorporados y, después, la base y su validación
    (:func:`start_build_base`). Devuelve cómo quedó: ``"done"`` o ``"failed"`` (cada
    importación fallida con su motivo y nada escrito). Cerrar los pasos antes del ``COMMIT``
    (al desregistrar) no escribe nada: sus operaciones siguen «en curso»."""
    project = order.entries[0].handle.project
    writer = store.SourceWriter(project)
    written: list[tuple[_Entry, Any, str]] = []
    try:
        for entry in order.live:
            assert entry.applied is not None and entry.read is not None
            applied = job_outcome(entry.applied, entry.applied.job_dir)
            tables: dict[str, Any] = {}
            contents: dict[str, Any] = {}
            for name, output in dict(applied.summary["outputs"]).items():
                role = name.removeprefix("dh_src_")
                tables[role] = jobs.read_table_output(applied.file(name), name)
                contents[role] = gis_jobs.digest_of(output["digest"])
            report = _read_report(entry)
            message = _entry_report(order, entry, report, applied.summary)
            item = writer.add(
                entry.handle, entry.spec, tables, name=entry.choice.name, contents=contents,
                log=_log_lines(order, entry, report, applied.summary),
                previous_uid=entry.previous_uid,
                reason=order.reason if entry.previous_uid else None, message=message,
                interpreter=entry.outcome.interpreter, executor=entry.outcome.executor,
                job_uid=entry.read.job_uid)
            written.append((entry, item, message))
            yield 0.05
        library, version = crs_library()
        for done in writer.steps(software={library: version}):
            yield 0.05 + 0.75 * done
    except GeneratorExit:
        raise
    except Exception as error:  # noqa: BLE001 - las importaciones quedan fallidas, sin nada
        LOGGER.warning("La importación de sondeos %s no se escribió", order.uid, exc_info=True)
        _abandon(order, error_text(error), failed=True)
        return "failed"
    try:  # la regla bajo el límite de detección, con la primera importación (RF-005-26)
        ensure_detection_limit_rule(project)
    except (GeoblenderError, sqlite3.Error, OSError, ValueError):
        LOGGER.warning("No se registró la regla bajo el límite de detección", exc_info=True)
    for number, (entry, item, _message) in enumerate(written):
        assert entry.read is not None
        verified = entry.read.job_dir.inputs_dir / (gis_jobs.path_name("main")
                                                    + entry.choice.path.suffix)
        try:
            for step in writer.originals(item, [verified]):
                share = step.done / step.total if step.total else 1.0
                yield 0.8 + 0.19 * (number + share) / len(written)
        except Exception as error:  # noqa: BLE001 - lo importado ya está confirmado
            LOGGER.warning("No se guardó el original de «%s»", entry.choice.label,
                           exc_info=True)
            _say(tr("The original of the input could not be kept: {reason}",
                    reason=error_text(error)))
    for entry in order.live:
        _release(entry.read)
        _release(entry.applied)
    _ORDERS.pop(order.uid, None)
    for _entry, _item, message in written:
        _say(message)
    start_build_base(project)
    return "done"


# --- La base y su validación (T25; plan §5.6.1, §5.6.5 y §5.6.6) ---------------------------------

BASE_LABEL = "Drillhole database"
VALIDATION_LABEL = "Validation of the drillhole database"


def _loose_set(name: str, tables: Mapping[str, Any], catalogs: Catalogs
               ) -> Iterator[dict[str, np.ndarray]]:
    """Los arrays (``drillholes.arrays.tables_arrays``) de unas tablas y unos catálogos para
    ``launch_job(arrays=…)``, una tabla por paso y cada una empaquetada en una sola entrada
    (``drillholes.jobs.packed_arrays``: un fichero por tabla en ``in/``, no uno por columna;
    T28)."""
    for table in TABLES:
        yield jobs.packed_arrays(name, table, tables_arrays({table: tables[table]}))
    yield jobs.packed_arrays(name, "catalogs", tables_arrays({}, catalogs))


def start_build_base(project: Any, *, validate: bool = True) -> None:
    """Pone en la cola de incorporación de los sondeos la base desde lo importado vigente
    (``dh.build_base``; plan §5.6.1) y, hecha, su validación (:func:`start_validate`)."""
    INCORPORATIONS.add(provenance.BUILD_BASE, _text(BASE_LABEL),
                       _build_base_steps(project, validate))


def _build_base_steps(project: Any, validate: bool) -> Generator[float, None, str]:
    """Los pasos que lanzan ``dh.build_base``: la operación «en curso» con lo que consume
    (cada ``dh_src_*`` vigente, papel ``source``, y ``dh_import_log``, ``imports``), lo
    importado leído por pasos (``drillholes.store.source_entry_steps``) a arrays sueltos y su
    trabajo ``dh_build_base`` (con las ruedas de la extensión si transforma)."""
    try:
        with project.read() as conn:
            sources = store.live_sources(conn)
            has_log = dataset_registry.get(conn, store.IMPORT_LOG) is not None
        if not sources:
            return "empty"
        uses = [Use(dataset.name, "source") for source in sources
                for dataset in source.datasets.values()]
        if has_log:
            uses.append(Use(store.IMPORT_LOG, "imports"))
        handle = begin_operation(project, provenance.BUILD_BASE, settings={}, inputs=uses,
                                 executor="job_thread")
    except Exception as error:  # noqa: BLE001 - lo dice y no empieza nada
        LOGGER.warning("No se pudo empezar la base de los sondeos", exc_info=True)
        _say(tr("The drillhole database has not been built: {reason}",
                reason=error_text(error)))
        return "failed"
    try:
        entries: list[dict[str, Any]] = []
        loose: dict[str, np.ndarray] = {}
        rows = 0
        with project.read() as conn:
            for number, source in enumerate(sources, start=1):
                entry = yield from store.source_entry_steps(conn, source)
                name = f"e{number}"
                for arrays in _loose_set(name, {table: getattr(entry, table)
                                                for table in TABLES}, entry.catalogs):
                    loose.update(arrays)
                    yield 0.5 * number / len(sources)
                rows += sum(len(getattr(entry, table)) for table in TABLES)
                entries.append({"input": name, "uid": entry.input_uid, "label": entry.label,
                                "declaration": jobs.declaration_json(entry.declaration)})
        crs, vertical = gis_store.project_references(project)
        params = {"crs": gis_jobs.crs_json(crs), "vertical": gis_jobs.vertical_json(vertical),
                  "project_uid": project.uid, "entries": entries, "count": rows + 1}
        from .gis import wheels_site

        site = wheels_site() if jobs.needs_site(jobs.BUILD_BASE, params) else None
        core_provenance.launch_job(handle, jobs.BUILD_BASE, label=_text(BASE_LABEL), params=params,
                                   arrays=loose, site_override=site,
                                   on_finish=functools.partial(_base_finished, handle,
                                                               validate),
                                   grace_s=jobs.CANCEL_GRACE_S)
    except GeneratorExit:
        raise
    except Exception as error:  # noqa: BLE001 - la operación queda fallida con el motivo
        LOGGER.warning("No se pudo lanzar la base de los sondeos", exc_info=True)
        _end(handle, error_text(error), failed=True)
        _say(tr("The drillhole database has not been built: {reason}",
                reason=error_text(error)))
        return "failed"
    return "launched"


def _base_finished(handle: OperationHandle, validate: bool, result: JobResult) -> None:
    """El final del trabajo de la base: si terminó bien, su escritura por pasos (si no, la
    procedencia la deja cancelada o fallida con el motivo de la 004)."""
    if result.state == _SUCCEEDED:
        INCORPORATIONS.add(handle.uid, _text(BASE_LABEL), _base_steps(handle, result, validate))


def _base_report(summary: Mapping[str, Any]) -> str:
    """El informe de la base: sus sondeos, las transformaciones y las notas (lo que no
    pasa)."""
    lines = [tr("Drillhole database: {holes} drillholes",
                holes=format_number(int(summary.get("holes", 0)), 0))]
    lines += [tr("Transformation: {transform}", transform=item["summary"])
              for item in summary.get("transforms", ())]
    lines += [str(note["message"]) for note in summary.get("notes", ())]
    return "\n".join(lines)


def _base_steps(handle: OperationHandle, result: JobResult,
                validate: bool) -> Generator[float, None, str]:
    """Los pasos que escriben la base (``drillholes.store.BaseWriter``: las once tablas con el
    hash que dio su trabajo, en una transacción) y, hecha, lanzan su validación."""
    project = handle.project
    try:
        outcome = job_outcome(result, result.job_dir)
        summary = outcome.summary
        writer = store.BaseWriter(project, handle)
        for name in BASE_TABLES:
            writer.table(name, jobs.read_table_output(outcome.file(name), name),
                         content=gis_jobs.digest_of(summary["outputs"][name]["digest"]))
        report = _base_report(summary)
        yield 0.05
        library, version = crs_library()
        for done in writer.steps(software={library: version}, message=report,
                                 interpreter=outcome.interpreter, executor=outcome.executor,
                                 job_uid=result.job_uid):
            yield 0.05 + 0.95 * done
    except GeneratorExit:
        raise
    except Exception as error:  # noqa: BLE001 - la operación queda fallida con el motivo
        LOGGER.warning("La base de los sondeos no se escribió", exc_info=True)
        _end(handle, error_text(error), failed=True)
        _release(result)
        _say(tr("The drillhole database has not been built: {reason}",
                reason=error_text(error)))
        return "failed"
    _release(result)
    _say(report)
    if validate:
        start_validate(project)
    return "done"


def project_surfaces(project: Any) -> list[Any]:
    """Las rejillas del proyecto vigentes (``gis_dtm_*``; D-19) con que se pueden comparar
    las cotas de las bocas (DH-W05), de la más antigua a la más reciente (por su último cambio
    y su creación)."""
    records = [record for record in gis_store.list_gis_datasets(
        project, families=(gis_provenance.PROJECT_GRID,)) if str(record.status) == "current"]
    return sorted(records, key=lambda record: (record.modified_at, record.created_at))


def project_surface(project: Any) -> Any:
    """El MDT del proyecto con que se comparan las cotas de las bocas por defecto (DH-W05;
    D-19): la rejilla del proyecto vigente más reciente (``gis_dtm_*``); sin ninguna,
    ``None``."""
    surfaces = project_surfaces(project)
    return surfaces[-1] if surfaces else None


def chosen_surface(project: Any, typed: str) -> Any:
    """La rejilla del proyecto que se elige al validar (D-19): la de nombre o uid ``typed``
    entre las vigentes (:func:`project_surfaces`); vacío, la más reciente (sin ninguna,
    ``None``: DH-W05 no se evalúa). ``ValidationError`` ``dh.surface_unknown`` si no es
    ninguna de ellas, nombrándolas."""
    surfaces = project_surfaces(project)
    shown = typed.strip()
    if not shown:
        return surfaces[-1] if surfaces else None
    for record in surfaces:
        if shown in (record.name, record.uid):
            return record
    names = ", ".join(f"«{record.name}»" for record in surfaces)
    reason = (f"no es una rejilla del proyecto vigente: elija una de {names}" if surfaces else
              "el proyecto no tiene ninguna rejilla vigente (Rejilla de proyecto desde un "
              "MDT…): valide sin superficie")
    raise ValidationError("dh.surface_unknown", reason, obj=_text(VALIDATION_LABEL),
                          field="superficie", value=shown)


def validation_uses(surface: Any) -> list[Use]:
    """Lo que consume ``dh.validate`` (plan §5.6.4): las once tablas de la base y, si se
    eligió, la rejilla del proyecto ``surface`` (papel ``terrain``)."""
    uses = [Use(table, provenance.OUTPUT_ROLES[table]) for table in BASE_TABLES]
    if surface is not None:
        uses.append(Use(surface.name, "terrain"))
    return uses


def validation_settings(surface: Any) -> dict[str, Any]:
    """Los ajustes de ``dh.validate``: el nombre de la rejilla del proyecto elegida, o
    ``None`` sin ninguna (D-19: el informe guardado dice entonces que DH-W05 no se
    evaluó)."""
    return {"surface": None if surface is None else surface.name}


MOST_RECENT_SURFACE: Any = object()
"""La superficie por defecto de :func:`start_validate`: la rejilla vigente más reciente."""


def start_validate(project: Any, *, surface: Any = MOST_RECENT_SURFACE,
                   handle: OperationHandle | None = None) -> None:
    """Pone en la cola de incorporación de los sondeos la validación de la base
    (``dh.validate``; RF-005-16) con la rejilla del proyecto ``surface`` (``None``, sin
    ninguna; por defecto, la vigente más reciente) y, si ya la empezó su orden con la puerta de
    la 008, su operación ``handle``."""
    INCORPORATIONS.add(provenance.VALIDATE if handle is None else handle.uid,
                       _text(VALIDATION_LABEL), _validate_steps(project, surface, handle))


def _validate_steps(project: Any, surface: Any,
                    handle: OperationHandle | None) -> Generator[float, None, str]:
    """Los pasos que lanzan ``dh.validate``: la operación «en curso» con lo que consume (las
    once tablas de la base y, si lo hay, el MDT, papel ``terrain``) y sus parámetros (si no
    la empezó ya su orden), la base leída por pasos (``drillholes.store.read_steps``) a arrays
    sueltos y su trabajo ``dh_validate`` (el MDT, copiado a ``in/``)."""
    if handle is None:
        try:
            if surface is MOST_RECENT_SURFACE:
                surface = project_surface(project)
            handle = begin_operation(
                project, provenance.VALIDATE, settings=validation_settings(surface),
                inputs=validation_uses(surface), params=list(dh_params.VALIDATION_KEYS),
                executor="job_thread")
        except Exception as error:  # noqa: BLE001 - lo dice y no empieza nada
            LOGGER.warning("No se pudo empezar la validación de los sondeos", exc_info=True)
            _say(tr("The drillhole database has not been validated: {reason}",
                    reason=error_text(error)))
            return "failed"
    try:
        inputs: dict[str, Path] = {}
        if surface is not None:
            inputs[jobs.INPUT_DEM] = Path(project.root, *surface.locator.split("/"))
        with project.read() as conn:
            dset = yield from store.read_steps(conn)
        loose: dict[str, np.ndarray] = {}
        for arrays in _loose_set(jobs.INPUT_BASE, {table: getattr(dset, table)
                                                   for table in TABLES}, dset.catalogs):
            loose.update(arrays)
            yield 0.6
        resolved = {param.key: param.value for param in handle.params}
        thresholds = {key.rpartition(".")[2]: resolved[key]
                      for key in dh_params.VALIDATION_KEYS}
        window = project.window
        rows = sum(len(getattr(dset, table)) for table in TABLES)
        params = {"crs": gis_jobs.crs_json(dset.crs),
                  "vertical": gis_jobs.vertical_json(dset.vertical),
                  "thresholds": thresholds,
                  "work_window": None if window is None else gis_jobs.window_json(window),
                  "count": rows + 1}
        core_provenance.launch_job(handle, jobs.VALIDATE, label=_text(VALIDATION_LABEL),
                                   params=params, arrays=loose, inputs=inputs or None,
                                   on_finish=functools.partial(_validate_finished, handle),
                                   grace_s=jobs.CANCEL_GRACE_S)
    except GeneratorExit:
        raise
    except Exception as error:  # noqa: BLE001 - la operación queda fallida con el motivo
        LOGGER.warning("No se pudo lanzar la validación de los sondeos", exc_info=True)
        _end(handle, error_text(error), failed=True)
        _say(tr("The drillhole database has not been validated: {reason}",
                reason=error_text(error)))
        return "failed"
    return "launched"


def _validate_finished(handle: OperationHandle, result: JobResult) -> None:
    """El final del trabajo de la validación: si terminó bien, su escritura por pasos."""
    if result.state == _SUCCEEDED:
        INCORPORATIONS.add(handle.uid, _text(VALIDATION_LABEL),
                           _validated_steps(handle, result))


def _validation_report(summary: Mapping[str, Any], notes: Sequence[Mapping[str, Any]]) -> str:
    """El informe de una validación (RF-005-16): las incidencias por nivel, los sondeos
    excluidos y lo que no se evaluó."""
    lines = [tr("Validation of the drillhole database: {issues} issues ({errors} errors and "
                "{warnings} warnings); {excluded} drillholes excluded",
                issues=format_number(int(summary.get("issues", 0)), 0),
                errors=format_number(int(summary.get("errors", 0)), 0),
                warnings=format_number(int(summary.get("warnings", 0)), 0),
                excluded=format_number(int(summary.get("excluded_holes", 0)), 0))]
    lines += [f"{note['hole_name']}: {note['message']}" if note.get("hole_name")
              else str(note["message"]) for note in notes]
    return "\n".join(lines)


def _depth_text(start: Any, end: Any) -> str:
    """El tramo o la profundidad de una incidencia («12,5–13,0»; sin ninguno, «»)."""
    shown = [_number(value) for value in (start, end)
             if value is not None and not (isinstance(value, float) and math.isnan(value))]
    return "–".join(shown)


def show_issues(stored: store.StoredValidation | None) -> None:
    """El informe guardado de la última validación (``drillholes.store.stored_validation``:
    cada fila de ``dh_validation_issue`` y, después, lo que no se evaluó, con el nivel «Sin
    evaluar») en la lista de la pestaña «Sondeos» (``WindowManager.geoblender_dh_validation``;
    RF-005-16); sin informe, vacía."""
    manager = getattr(bpy.context, "window_manager", None)
    validation = getattr(manager, VALIDATION_PROPERTY, None)
    if validation is None:
        return
    validation.issues.clear()
    for values in () if stored is None else stored.records:
        item = validation.issues.add()
        item.code = str(values["code"])
        item.level = str(values["level"]).upper()
        item.hole = str(values["hole_name"] or "")
        item.table = str(values["table_name"] or "")
        item.depth = _depth_text(values["depth_from"], values["depth_to"])
        item.field = str(values["field"] or "")
        item.value = str(values["value"] or "")
        item.message = str(values["message"])
    language = i18n.language()
    for note in () if stored is None else stored.notes:
        item = validation.issues.add()
        item.code = note.code
        item.level = NOT_EVALUATED
        item.hole = note.hole_name or ""
        item.message = note.message(language)
    validation.issue_index = 0
    _redraw()


def load_issues(project: Any) -> None:
    """La lista de la pestaña «Sondeos» con el informe guardado de la última validación de
    ``project`` (:func:`show_issues`); sin proyecto, sin validación o si no se puede leer
    (queda en el registro técnico), vacía."""
    stored = None
    if project is not None and not getattr(project, "closed", False) \
            and not getattr(project, "header_only", False):
        try:
            with project.read() as conn:
                stored = store.stored_validation(conn)
        except (GeoblenderError, sqlite3.Error, OSError, ValueError):
            LOGGER.info("No se pudo leer la última validación de los sondeos", exc_info=True)
    show_issues(stored)


def on_project_changed(project: Any) -> None:
    """Al cambiar el proyecto de la sesión (``bl.scene.project_session.add_listener``): la
    lista de incidencias es la de la última validación del nuevo (sin ninguno, vacía)."""
    try:
        load_issues(project)
    except Exception:  # noqa: BLE001 - la sesión sigue: la lista no es imprescindible
        LOGGER.exception("No se pudo poner la lista de la validación de los sondeos")


def _validated_steps(handle: OperationHandle, result: JobResult) -> Generator[float, None, str]:
    """Los pasos que escriben ``dh_validation_issue`` con el hash que dio su trabajo y llevan
    el informe guardado a la lista de la pestaña (:func:`load_issues`)."""
    project = handle.project
    try:
        outcome = job_outcome(result, result.job_dir)
        summary = outcome.summary
        name = "dh_validation_issue"
        rows = jobs.read_table_output(outcome.file(name), name)
        notes = json.loads(outcome.file(jobs.OUT_REPORT.role).read_text(encoding="utf-8"))
        report = _validation_report(summary, list(notes.get("notes", ())))
        writer = store.BaseWriter(project, handle)
        writer.table(name, rows, content=gis_jobs.digest_of(summary["outputs"][name]["digest"]))
        yield 0.05
        for done in writer.steps(message=report, interpreter=outcome.interpreter,
                                 executor=outcome.executor, job_uid=result.job_uid):
            yield 0.05 + 0.9 * done
    except GeneratorExit:
        raise
    except Exception as error:  # noqa: BLE001 - la operación queda fallida con el motivo
        LOGGER.warning("La validación de los sondeos no se escribió", exc_info=True)
        _end(handle, error_text(error), failed=True)
        _release(result)
        _say(tr("The drillhole database has not been validated: {reason}",
                reason=error_text(error)))
        return "failed"
    _release(result)
    yield 0.95
    load_issues(project)
    _say(report)
    return "done"


# --- Las trazas (T28; RF-005-20, RF-005-22; plan §5.3.1, §5.6.4 y §5.6.6) -----------------------

TRACES_LABEL = "Drillhole traces"
TRACE_TABLE = "dh_trace"
STALE_SCOPE = SCOPES["STALE"]
"""El ámbito de «solo las obsoletas» en los ajustes de ``dh.desurvey``."""


def desurvey_uses() -> list[Use]:
    """Lo que consume ``dh.desurvey`` (plan §5.6.4): las bocas y las desviaciones de la base
    (no el informe de validación: sus exclusiones de alcance S las calcula ella misma)."""
    return [Use(table, provenance.OUTPUT_ROLES[table]) for table in ("dh_collar", "dh_survey")]


def desurvey_settings(method: str, scope: str) -> dict[str, Any]:
    """Los ajustes de ``dh.desurvey`` (los de :data:`SETTING_DEFS`): el método
    (``drillholes.desurvey.Method``) y los sondeos (``all`` o ``stale``)."""
    return {"method": method, "scope": scope}


def start_desurvey(project: Any, handle: OperationHandle, *, method: str, scope: str) -> None:
    """Pone en la cola de incorporación de los sondeos el cálculo de las trazas de la
    operación ``handle`` (``dh.desurvey``, ya empezada por su orden): por ``method``, de todos
    los sondeos (``scope="all"``) o solo de los de traza obsoleta (``"stale"``)."""
    INCORPORATIONS.add(handle.uid, _text(TRACES_LABEL),
                       _desurvey_steps(project, handle, method, scope))


def _desurvey_steps(project: Any, handle: OperationHandle, method: str,
                    scope: str) -> Generator[float, None, str]:
    """Los pasos que lanzan ``dh.desurvey``: las bocas y las desviaciones de la base leídas
    por pasos (``drillholes.store.read_steps``) a arrays sueltos, la huella de la desviación
    de cada boca y, con «solo las obsoletas», las trazas que se conservan
    (``drillholes.store.kept_traces``: las demás, si la última desviación usó el mismo método
    y los mismos parámetros) y las bocas que se calculan; y su trabajo ``dh_desurvey`` con los
    parámetros que resolvió la operación."""
    try:
        resolved = {param.key: param for param in handle.params}
        with project.read() as conn:
            dset = yield from store.read_steps(conn, parts=("dh_survey",))
            hashes = store.survey_hashes(conn)
            kept = [] if scope != STALE_SCOPE else store.kept_traces(
                conn, method=method,
                params={key: param.value_sha256 for key, param in resolved.items()})
        yield 0.3
        loose: dict[str, np.ndarray] = {}
        for arrays in _loose_set(jobs.INPUT_BASE, {table: getattr(dset, table)
                                                   for table in TABLES}, dset.catalogs):
            loose.update(arrays)
            yield 0.6
        loose[jobs.INPUT_HASHES] = np.array(hashes, dtype="S64")
        params = {"crs": gis_jobs.crs_json(dset.crs),
                  "vertical": gis_jobs.vertical_json(dset.vertical), "method": method,
                  "depth_tolerance_m": resolved[dh_params.DEPTH_TOLERANCE].value,
                  "trace_step_m": resolved[dh_params.TRACE_STEP].value,
                  "count": len(dset.collars) + 1}
        if scope == STALE_SCOPE:
            done = {row[1] - 1 for row in kept}
            params["holes"] = [hole for hole in range(len(dset.collars)) if hole not in done]
            if kept:
                loose.update(jobs.packed_arrays(jobs.INPUT_KEPT, "rows",
                                                rows_arrays(LAYOUTS[TRACE_TABLE], kept)))
        yield 0.9
        core_provenance.launch_job(handle, jobs.DESURVEY, label=_text(TRACES_LABEL),
                                   params=params, arrays=loose,
                                   on_finish=functools.partial(_desurvey_finished, handle),
                                   grace_s=jobs.CANCEL_GRACE_S)
    except GeneratorExit:
        raise
    except Exception as error:  # noqa: BLE001 - la operación queda fallida con el motivo
        LOGGER.warning("No se pudo lanzar el cálculo de las trazas", exc_info=True)
        _end(handle, error_text(error), failed=True)
        _say(tr("The drillhole traces have not been computed: {reason}",
                reason=error_text(error)))
        return "failed"
    return "launched"


def _desurvey_finished(handle: OperationHandle, result: JobResult) -> None:
    """El final del trabajo de las trazas: si terminó bien, su escritura por pasos."""
    if result.state == _SUCCEEDED:
        INCORPORATIONS.add(handle.uid, _text(TRACES_LABEL), _traced_steps(handle, result))


def _traces_report(summary: Mapping[str, Any]) -> str:
    """El informe de un cálculo de las trazas (RF-005-20): el método, las calculadas y las
    conservadas, los sondeos sin traza (errores de alcance S, RF-005-17) y dónde se prolongó
    la orientación de la estación más próxima."""
    method = next((name for identifier, name, _description in METHOD_ITEMS
                   if METHODS[identifier] == summary.get("method")), str(summary.get("method")))
    lines = [tr("Drillhole traces by {method}: {computed} computed and {kept} kept",
                method=_text(method).lower(),
                computed=format_number(int(summary.get("computed", 0)), 0),
                kept=format_number(int(summary.get("kept", 0)), 0))]
    excluded = list(summary.get("excluded", ()))
    if excluded:
        lines.append(tr("Without trace (errors of scope S): {holes}",
                        holes=", ".join(map(str, excluded))))
    extended = [f"{item['name']} ({item['code']}, "
                f"{_depth_text(item['depth_from'], item['depth_to'])} m)"
                for item in summary.get("warnings", ())]
    if extended:
        lines.append(tr("Orientation extended where there are no stations: {items}",
                        items="; ".join(extended)))
    return "\n".join(lines)


def _traced_steps(handle: OperationHandle, result: JobResult) -> Generator[float, None, str]:
    """Los pasos que escriben ``dh_trace`` con el hash que dio su trabajo
    (``drillholes.store.BaseWriter``, en una transacción)."""
    project = handle.project
    try:
        outcome = job_outcome(result, result.job_dir)
        summary = outcome.summary
        rows = jobs.read_table_output(outcome.file(TRACE_TABLE), TRACE_TABLE)
        report = _traces_report(summary)
        writer = store.BaseWriter(project, handle)
        writer.table(TRACE_TABLE, rows,
                     content=gis_jobs.digest_of(summary["outputs"][TRACE_TABLE]["digest"]))
        yield 0.05
        for done in writer.steps(message=report, interpreter=outcome.interpreter,
                                 executor=outcome.executor, job_uid=result.job_uid):
            yield 0.05 + 0.95 * done
    except GeneratorExit:
        raise
    except Exception as error:  # noqa: BLE001 - la operación queda fallida con el motivo
        LOGGER.warning("Las trazas de los sondeos no se escribieron", exc_info=True)
        _end(handle, error_text(error), failed=True)
        _release(result)
        _say(tr("The drillhole traces have not been computed: {reason}",
                reason=error_text(error)))
        return "failed"
    _release(result)
    _say(report)
    start_view(project)
    return "done"


# --- La vista de las trazas (T29; RF-005-23, RF-005-24; plan §5.6.8) -----------------------------

VIEW_LABEL = "View arrays of the drillholes"
VIEW_QUEUE = "dh.view"
"""La «operación» de la carga de la vista en la cola de incorporación (no es una operación de
la procedencia: la vista no escribe en el proyecto)."""
VIEW_STATUS = "Loading «{name}» into the view… {percent} %"


def start_view(project: Any) -> None:
    """Pone en la cola de incorporación de los sondeos la carga de sus trazas en la vista
    (plan §5.6.8: calculadas las trazas, la vista se recarga sola; RF-005-23): los pasos de
    ``bl.scene.views.load_steps`` con el cargador de ``bl.scene.dh_view``, detrás de la
    escritura de ``dh_trace``."""
    INCORPORATIONS.add(VIEW_QUEUE, _text(VIEW_LABEL), _view_steps(project), status=VIEW_STATUS)


def _view_steps(project: Any) -> Generator[float, None, str]:
    """Los pasos que cargan ``dh_trace`` en la escena (``bl.scene.views.load_steps``: lo
    cargado de antes, sustituido en el último) y lo que dice la carga, en los avisos de la
    sesión."""
    outcome: views.LoadOutcome | None = None
    try:
        for step in views.load_steps(bpy.context, project, [TRACE_TABLE]):
            if isinstance(step.result, views.LoadOutcome):
                outcome = step.result
            yield step.done / step.total if step.total else 1.0
    except GeneratorExit:
        raise
    except Exception as error:  # noqa: BLE001 - la vista no se carga: se dice
        LOGGER.warning("Las trazas de los sondeos no se cargaron en la vista", exc_info=True)
        _say(tr("The drillhole traces have not been loaded into the view: {reason}",
                reason=error_text(error)))
        return "failed"
    for text in () if outcome is None else (*outcome.notes, *outcome.errors):
        _say(text)
    return "done"


# --- La referencia del azimut: reimportar una entrada (T28; RF-005-22, RF-008-11; plan §5.6.10)

AZIMUTH_LABEL = "Azimuth reference of an import"


def azimuth_inputs(project: Any) -> list[InputRecord]:
    """Las entradas vigentes de los sondeos con azimuts (D-22): las de unas bocas, unas
    desviaciones o una base de RecMin (la referencia del azimut es contenido de la entrada),
    en el orden en que se registraron."""
    with project.read() as conn:
        records = list_inputs(conn)
    found = [record for record in records if record.active
             and record.reader in provenance.READER_IDS
             and "azimuth_ref" in record.content_settings_keys]
    return sorted(found, key=lambda record: record.registered_at)


def azimuth_input(project: Any, typed: str) -> InputRecord:
    """La entrada con azimuts (:func:`azimuth_inputs`) de uid o nombre ``typed``;
    ``ValidationError`` ``dh.input_without_azimuth`` si no es ninguna de ellas, nombrándolas."""
    shown = typed.strip()
    records = azimuth_inputs(project)
    for record in records:
        if shown and shown in (record.uid, record.name):
            return record
    names = ", ".join(f"«{record.name}»" for record in records)
    reason = (f"no es una importación vigente de bocas, desviaciones o una base de RecMin: "
              f"elija una de {names}" if records else
              "el proyecto no tiene ninguna importación vigente de bocas, desviaciones o una "
              "base de RecMin (Sondeos ▸ Importar)")
    raise ValidationError("dh.input_without_azimuth", reason, obj=_text(AZIMUTH_LABEL),
                          field="importación", value=shown)


def _reimport(request: ReimportRequest) -> OperationHandle:
    """«Actualizar» una entrada de los sondeos (RF-008-11; plan §5.6.4 y §5.6.10): su fuente
    (la del registro, resuelta desde su ancla) leída otra vez con sus ajustes registrados (y
    los que pide ``request.settings``, de los que tiene) en una operación nueva de su tipo que
    sustituye a la de la entrada (``supersedes``), como una orden de importación de una
    entrada que la sustituye con el motivo (no se clasifica: ya se sabe a cuál sustituye); los
    sondeos que ya traía la entrada se sustituyen sin preguntar y lo demás, como al importar
    (los códigos nuevos y los sondeos que vienen de otra entrada esperan la decisión).
    Aplicada, la base se reconstruye (y su validación). Devuelve la operación, aún «en curso».
    Sin escribir nada: ``core.input_unknown``, ``core.reimport_source_missing`` (no se
    encuentra su fuente), una base de RecMin abierta en otro programa (``ValueError``) y
    ``ValueError`` con un ajuste que la entrada no tiene."""
    project = request.project
    with project.read() as conn:
        record = get_input(conn, request.input_uid)
        source = None if record is None else next(
            (item for item in store.live_sources(conn) if item.record.uid == record.uid), None)
        replaced = () if source is None else store.source_holes(conn, source)
        catalogs = store.read_catalogs(conn)
        existing = store.existing_holes(conn)
    if record is None:
        raise ProvenanceError("core.input_unknown", input=request.input_uid,
                              project=project.name)
    if record.reader not in provenance.READER_IDS or len(record.files) != 1:
        raise ValueError(f"la entrada «{record.name}» no es la de una importación de sondeos "
                         f"({record.reader})")
    (main,) = record.files
    path = resolve_source(main, project, project.userdata)
    if path is None or not path.is_file():
        raise ProvenanceError("core.reimport_source_missing", name=record.name, file=main.path)
    settings = dict(record.settings)
    given = dict(request.settings or {})
    unknown = sorted(str(key) for key in given if key not in settings)
    if unknown:
        raise ValueError(f"la entrada «{record.name}» no tiene los ajustes {unknown}")
    settings.update(given)
    declaration = provenance.input_declaration(record.reader, record.crs_h, record.crs_v,
                                               settings)
    if record.reader == provenance.RECMIN_MDB:
        lock = mdb_ports.lock_file(path)
        if lock is not None:  # RF-005-15: sin la confirmación del diálogo, no se lee
            raise ValueError(tr("«{file}» is open in another program (it has «{lock}»): "
                                "close it and update the input again", file=path.name,
                                lock=lock.name))
        choice = TableChoice(path, record.reader, "", {}, None, record.name)
        options = ReadOptions("utf-8", ";", 0, str(settings["decimal"]), None)
        op_type, command = provenance.IMPORT_RECMIN, IMPORT_RECMIN
    else:
        sheet = record.layer if record.reader == provenance.DH_XLSX else None
        choice = TableChoice(path, record.reader, str(settings["role"]),
                             dict(settings["mapping"]), sheet, record.name)
        options = ReadOptions(str(settings.get("encoding", "utf-8")),
                              str(settings.get("separator", ";")),
                              int(settings.get("header_row", 0)), str(settings["decimal"]),
                              settings.get("date_format"))
        op_type, command = provenance.IMPORT_TABULAR, IMPORT_DRILLHOLES
    handle = begin_operation(project, op_type,
                             settings=_operation_settings(choice, declaration, options),
                             executor="job_process", supersedes=record.operation_uid)
    order = _Order([_Entry(choice, handle, previous_uid=record.uid)], declaration, options,
                   catalogs, existing, request.received_at, request.received_from,
                   request.reason, command=command, reimport=True, replaced=replaced)
    _ORDERS[order.uid] = order
    (entry,) = order.entries
    try:
        launch = _read_job(order, entry)
        core_provenance.launch_job(handle, launch.pop("worker"), **launch)
    except BaseException:  # la operación ya quedó fallida con el motivo
        _ORDERS.pop(order.uid, None)
        raise
    entry.started = True
    return handle


# --- La regla bajo el límite de detección (T28; RF-005-26; plan §5.6.3 y §5.6.10, D-22) ---------

RULE_ITEMS = [
    ("METHOD", "Rule", "How the values below the detection limit are replaced in later "
                       "calculations: a factor of the limit, the limit, zero or absent"),
    ("FACTOR", "Factor of the limit", "Fraction of the detection limit with the rule «factor»"),
]
RULE_KEYS: Mapping[str, str] = MappingProxyType({"METHOD": dh_params.BELOW_DL_METHOD,
                                                 "FACTOR": dh_params.BELOW_DL_FACTOR})
"""La clave de ``core.params`` de cada parte de la regla (D-17)."""
RULE_LABEL = "Values below the detection limit"


def ensure_detection_limit_rule(project: Any) -> tuple[str, ...]:
    """Registra en ``project`` la regla bajo el límite de detección (``dh.below_dl.*``) con su
    valor por defecto «sin confirmar» si aún no la tiene (RF-005-26, RF-008-04; plan §5.6.3),
    en una transacción; devuelve las claves que registró (ninguna si ya estaban). No la anota
    ninguna operación: ningún cálculo de la 005 la consume."""
    parameters = core_params.ParameterStore(project)
    with project.read() as conn:
        missing = tuple(key for key in dh_params.BELOW_DL_KEYS
                        if parameters.get(key, conn=conn) is None)
    if missing:
        with project.write_transaction() as conn:
            for key in missing:
                parameters.ensure_default(
                    conn, key, geoblender_version=project.session.geoblender_version)
    return missing


# --- Las órdenes (plan §5.3.1 y §5.6) -----------------------------------------------------------

_DECLARATION_PROPS: tuple[tuple[str, str], ...] = (
    ("crs", "Horizontal CRS"), ("vertical", "Vertical CRS"),
    ("azimuth_ref", "Azimuth reference"), ("declination_deg", "Magnetic declination"),
    ("inclination_convention", "Inclination"), ("all_vertical", "All vertical"),
    ("units", "Units of the elements"), ("sentinels", "No-data values"),
    ("negative_is_below_dl", "Negative means below the detection limit"),
    ("density_kind", "Density"),
)
_READING_PROPS: tuple[tuple[str, str], ...] = (
    ("encoding", "Encoding"), ("separator", "Separator"), ("decimal_mark", "Decimal mark"),
    ("header_row", "Lines before the header"), ("date_format", "Date format"),
)
_DELIVERY_PROPS: tuple[tuple[str, str], ...] = (
    ("received_at", "Delivery date"), ("received_from", "Delivered by"), ("reason", "Reason"),
)
_KEPT_PROPS: tuple[str, ...] = tuple(
    name for name, _text in (*_DECLARATION_PROPS, *_READING_PROPS, *_DELIVERY_PROPS)) + (
    "sheet",)
"""Lo que el asistente recibe de la orden que lo abre (tras elegir los ficheros)."""
_RECMIN_DECLARATION_PROPS: tuple[tuple[str, str], ...] = (
    ("crs", "Horizontal CRS"), ("vertical", "Vertical CRS"),
    ("azimuth_ref", "Azimuth reference"), ("declination_deg", "Magnetic declination"),
    ("units", "Units of the elements"), ("sentinels", "No-data values"),
    ("negative_is_below_dl", "Negative means below the detection limit"),
    ("density_kind", "Density"),
)
_RECMIN_READING_PROPS: tuple[tuple[str, str], ...] = (
    ("decimal_mark", "Decimal mark"), ("accept_schema", "Read an unknown schema"),
)
LOCKED_LABEL = "Read it although it is open"
_RECMIN_KEPT_PROPS: tuple[str, ...] = tuple(
    name for name, _text in (*_RECMIN_DECLARATION_PROPS, *_RECMIN_READING_PROPS,
                             *_DELIVERY_PROPS)) + ("accept_locked",)
"""Lo que el diálogo de una base de RecMin recibe de la orden que lo abre (tras elegirla)."""
RECMIN_NEEDS = Needs(crs=True, vertical=True, azimuth=True)
"""Lo que se declara siempre al importar una base de RecMin (RF-005-07): el CRS y el datum de
sus bocas y la referencia de sus azimuts (con la declinación, si es magnético). La unidad de un
elemento cuya unidad en la base no es de ley la pide su lectura, que ve la base."""
SHOWN_MSGIDS: tuple[str, ...] = (
    BASE_LABEL, VALIDATION_LABEL, LOCKED_LABEL, *_KIND_MSGIDS.values(), *_ROLE_MSGIDS.values(),
    *(text for _prop, text in (*_DECLARATION_PROPS, *_READING_PROPS, *_DELIVERY_PROPS,
                               *_RECMIN_READING_PROPS)),
    TRACES_LABEL, AZIMUTH_LABEL, RULE_LABEL, *(name for _id, name, _text in RULE_ITEMS),
    *(name for _id, name, _text in METHOD_ITEMS))
"""Los ``msgid`` de las constantes del módulo que se enseñan sin un ``tr`` literal (la prueba
de la importación comprueba que tienen su español)."""


def _reading_changed(self: Any, context: Any) -> None:
    """Con otra codificación, otro separador u otras filas antes de la cabecera, las columnas
    de cada tabla del asistente se leen otra vez y sus campos se proponen de nuevo."""
    if not getattr(self, "wizard", False):
        return
    options = _options_of(self)
    for table in self.tables:
        try:
            choice = _table_choice(table)
            header = list(preview(choice, options).columns)
        except (GeoblenderError, OSError, ValueError):
            LOGGER.info("No se pudo leer otra vez «%s»", table.name, exc_info=True)
            continue
        if [column.name for column in table.columns] == header:
            continue
        table.columns.clear()
        for index, name in enumerate(header):
            column = table.columns.add()
            column.name = name
            column.index = index
        suggest_fields(table)


def _options_of(operator: Any) -> ReadOptions:
    """Los ajustes de lectura de la orden ``operator``."""
    return ReadOptions(ENCODINGS[operator.encoding], SEPARATORS[operator.separator],
                       int(operator.header_row), DECIMALS[operator.decimal_mark],
                       operator.date_format.strip() or None)


def _open_wizard(values: Mapping[str, Any], idname: str = IMPORT_DRILLHOLES) -> None:
    """Abre el asistente (o el diálogo) de la importación ``idname`` con ``values`` (tras
    elegir los ficheros: en un temporizador, después del navegador de ficheros); sin ventana,
    nada."""
    manager = getattr(bpy.context, "window_manager", None)
    windows = list(getattr(manager, "windows", ()) or ())
    if not windows:
        return
    name = idname.partition(".")[2]

    def call() -> None:
        try:
            with bpy.context.temp_override(window=windows[0]):
                getattr(bpy.ops.geoblender, name)("INVOKE_DEFAULT", wizard=True, **values)
        except (RuntimeError, TypeError, AttributeError):
            LOGGER.warning("No se pudo abrir el asistente de la importación de sondeos",
                           exc_info=True)

    bpy.app.timers.register(call, first_interval=0.0)


def _reread(order: _Order) -> None:
    """Lee otra vez, con la confirmación (``accept_schema``), las bases de RecMin de ``order``
    que la pedían (RF-005-15): su lectura anterior, dada por incorporada; la nueva, en la
    misma operación. Si una no se puede lanzar, la orden no se escribe."""
    asking = [entry for entry in order.live if _confirmation(entry)]
    order.confirm = ""
    order.accept_schema = True
    for entry in asking:
        _release(entry.read)
        entry.read = None
        entry.outcome = None
    for entry in asking:
        try:
            launch = _read_job(order, entry)
            core_provenance.launch_job(entry.handle, launch.pop("worker"), **launch)
        except Exception as error:  # noqa: BLE001 - la operación ya quedó fallida o se deja
            LOGGER.warning("No se pudo leer otra vez «%s»", entry.choice.label, exc_info=True)
            _abandon(order, error_text(error), failed=True)
            return


def decide_pending(operator: Any, context: Any) -> set[str]:
    """Aplica o descarta la importación ``operator.pending`` que espera la decisión de la
    persona (``operator.stage``; RF-005-10, RF-005-11, RF-005-15): lo decidido, el de
    «Importación pendiente» si la enseña. Si lo que espera es la confirmación de leer una base
    de RecMin de esquema desconocido, «Aplicar» la lee otra vez con ella."""
    uid = operator.pending
    order = _ORDERS.get(uid) if uid in _WAITING else None
    if order is None:
        operator.report({"ERROR"}, tr("No drillhole import is waiting for a decision"))
        return {"CANCELLED"}
    if operator.stage == STAGE_DISCARD:
        _abandon(order, DISCARDED)
        operator.report({"INFO"}, tr("Import of the drillholes discarded: nothing has been "
                                     "written"))
        return {"FINISHED"}
    if order.confirm:
        _WAITING.remove(uid)
        _show_pending()
        _reread(order)
        operator.report({"INFO"}, tr("Reading the RecMin drillhole database again…"))
        return {"FINISHED"}
    shown = getattr(context.window_manager, IMPORT_PROPERTY, None)
    if shown is not None and shown.operation_uid != uid:
        shown = None
    register = True if shown is None else bool(shown.register_codes)
    if order.codes and not register:
        operator.report({"ERROR"}, tr("Without registering the new codes nothing is "
                                      "imported: register them or discard the import"))
        return {"CANCELLED"}
    reason = (operator.reason.strip() or (shown.reason.strip() if shown is not None else "")
              or (order.reason or ""))
    if any(entry.substitute for entry in order.live) and not reason:
        operator.report({"ERROR"}, tr("Write why the inputs replace those with the same data "
                                      "and other settings"))
        return {"CANCELLED"}
    order.reason = reason or None
    order.keep = tuple(hole.name for hole in shown.holes if hole.keep) if shown else ()
    order.register = bool(order.codes)
    _WAITING.remove(uid)
    _show_pending()
    _apply(order)
    operator.report({"INFO"}, tr("Applying the import of the drillholes…"))
    return {"FINISHED"}


class GEOBLENDER_OT_dh_import_drillholes(_DrillholesCommand, ProvenanceAwareOperator,
                                         bpy.types.Operator):
    """Collars, surveys, lithology and assays from CSV or XLSX"""

    bl_idname = IMPORT_DRILLHOLES
    bl_label = "Drillholes…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.IMPORT_TABULAR

    files: CollectionProperty(  # type: ignore[valid-type]
        type=bpy.types.OperatorFileListElement, options=_HIDDEN,
    )
    directory: StringProperty(subtype="DIR_PATH", options=_HIDDEN)  # type: ignore[valid-type]
    # Un fichero ya elegido (Importar un fichero…, soltado en la vista): el asistente con él.
    filepath: StringProperty(subtype="FILE_PATH", options=_HIDDEN)  # type: ignore[valid-type]
    filter_glob: StringProperty(  # type: ignore[valid-type]
        default="*.csv;*.txt;*.xlsx", options={"HIDDEN"},
    )
    mapping_json: StringProperty(  # type: ignore[valid-type]
        name="Column mapping",
        description="Role and columns of each file, in JSON (for scripts and tests)",
        options=_FIELD,
    )
    crs: StringProperty(  # type: ignore[valid-type]
        name="Horizontal CRS",
        description="EPSG code of the horizontal CRS of the collars, such as EPSG:25830 "
                    "(empty: undeclared, and nothing is imported)",
        options=_FIELD,
    )
    vertical: EnumProperty(  # type: ignore[valid-type]
        name="Vertical CRS", items=VERTICAL_ITEMS, default=UNDECLARED, options=_FIELD,
    )
    azimuth_ref: EnumProperty(  # type: ignore[valid-type]
        name="Azimuth reference", items=AZIMUTH_ITEMS, default=NOT_DECLARED, options=_FIELD,
    )
    declination_deg: StringProperty(  # type: ignore[valid-type]
        name="Magnetic declination",
        description="Magnetic declination in degrees, positive to the east, as written (only "
                    "with magnetic azimuths)",
        options=_FIELD,
    )
    inclination_convention: EnumProperty(  # type: ignore[valid-type]
        name="Inclination", items=INCLINATION_ITEMS, default=NOT_DECLARED, options=_FIELD,
    )
    all_vertical: BoolProperty(  # type: ignore[valid-type]
        name="All vertical", description="The drillholes without surveys are vertical",
        options=_FIELD,
    )
    units: StringProperty(  # type: ignore[valid-type]
        name="Units of the elements",
        description="Unit of each element of the assays that does not come in the file, "
                    "such as Au=g/t; Cu=% (g/t, ppm, ppb or %)",
        options=_FIELD,
    )
    decimal_mark: EnumProperty(  # type: ignore[valid-type]
        name="Decimal mark", items=DECIMAL_ITEMS, default="COMMA", options=_FIELD,
    )
    separator: EnumProperty(  # type: ignore[valid-type]
        name="Separator", items=SEPARATOR_ITEMS, default="SEMICOLON", options=_FIELD,
        update=_reading_changed,
    )
    encoding: EnumProperty(  # type: ignore[valid-type]
        name="Encoding", items=ENCODING_ITEMS, default="UTF8", options=_FIELD,
        update=_reading_changed,
    )
    header_row: IntProperty(  # type: ignore[valid-type]
        name="Lines before the header", default=0, min=0, options=_FIELD,
        update=_reading_changed,
    )
    date_format: StringProperty(  # type: ignore[valid-type]
        name="Date format",
        description="Format of the dates of the source, such as %d/%m/%Y (empty: ISO, "
                    "YYYY-MM-DD)",
        options=_FIELD,
    )
    sheet: StringProperty(  # type: ignore[valid-type]
        name="Sheet", description="Sheet of an XLSX workbook (empty: every sheet)",
        options=_FIELD,
    )
    sentinels: StringProperty(  # type: ignore[valid-type]
        name="No-data values",
        description="Values of the source that mean no data, separated by «;», such as "
                    "−99;−999;ND",
        options=_FIELD,
    )
    negative_is_below_dl: BoolProperty(  # type: ignore[valid-type]
        name="Negative means below the detection limit",
        description="A negative value −x of an assay means «<x»", options=_FIELD,
    )
    density_kind: EnumProperty(  # type: ignore[valid-type]
        name="Density", items=DENSITY_ITEMS, default="ADOPTADO", options=_FIELD,
    )
    received_at: StringProperty(  # type: ignore[valid-type]
        name="Delivery date", description="Delivery day, DD/MM/YYYY (empty: no date)",
        options=_FIELD,
    )
    received_from: StringProperty(  # type: ignore[valid-type]
        name="Delivered by", description="Who delivered the input (empty: nobody recorded)",
        options=_FIELD,
    )
    reason: StringProperty(  # type: ignore[valid-type]
        name="Reason",
        description="Why the input replaces the one imported with the same data and other "
                    "settings",
        options=_FIELD,
    )
    # El asistente (tras elegir los ficheros) y lo que decide la persona en «Importación
    # pendiente» (la misma orden con ``stage`` y ``pending``).
    wizard: BoolProperty(options=_HIDDEN)  # type: ignore[valid-type]
    tables: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_dh_table, options=_HIDDEN,
    )
    stage: EnumProperty(  # type: ignore[valid-type]
        items=STAGE_ITEMS, default=STAGE_NEW, options=_HIDDEN,
    )
    pending: StringProperty(options=_HIDDEN)  # type: ignore[valid-type]

    def _paths(self) -> list[Path]:
        """Los ficheros elegidos."""
        folder = Path(bpy.path.abspath(self.directory)) if self.directory else None
        found = [(folder / item.name) if folder is not None
                 else Path(bpy.path.abspath(item.name)) for item in self.files if item.name]
        if self.filepath and not found:
            found.append(Path(bpy.path.abspath(self.filepath)))
        return found

    def _choices(self, options: ReadOptions) -> list[TableChoice]:
        """Las tablas de la orden: las del asistente, las de ``mapping_json`` o, sin ninguno,
        las propuestas de los ficheros elegidos (``ValueError`` si de un CSV no se sabe el
        papel; las hojas de un XLSX sin papel no se importan)."""
        if self.wizard and len(self.tables):
            return [_table_choice(table) for table in self.tables
                    if table.role != NOT_IMPORTED]
        if self.mapping_json.strip():
            folder = Path(bpy.path.abspath(self.directory)) if self.directory else None
            return json_tables(self.mapping_json, folder, options)
        found = suggested_tables(self._paths(), options, sheet=self.sheet.strip() or None)
        unknown = [choice.label for choice in found
                   if not choice.role and choice.reader == provenance.DH_CSV]
        if unknown:
            raise ValueError(tr("Choose the role of {tables} in the import wizard",
                                tables=", ".join(f"«{name}»" for name in unknown)))
        return [choice for choice in found if choice.role]

    def _declaration(self, project: Any, options: ReadOptions) -> SourceDeclaration:
        """Lo declarado en la orden (``GisError`` con un CRS que no es del catálogo,
        ``ValidationError`` con una declinación que no vale y ``ValueError`` con unas
        unidades que no lo son)."""
        typed = self.declination_deg.strip()
        return SourceDeclaration(
            crs=parse_crs(self.crs), vertical=vertical_choice(self.vertical, project),
            azimuth_ref=AZIMUTH_REFS[self.azimuth_ref],
            declination_deg=parse_declination(typed) if typed else None,
            inclination_convention=INCLINATIONS[self.inclination_convention],
            units=parse_units(self.units),
            value_rules=ValueRules(decimal_mark=options.decimal,
                                   sentinels=parse_sentinels(self.sentinels),
                                   negative_is_below_dl=self.negative_is_below_dl),
            all_vertical=self.all_vertical, density_kind=DENSITY_KINDS[self.density_kind],
            date_format=options.date_format)

    def invoke(self, context: Any, event: Any) -> set[str]:
        self.provenance_dialog = True
        if self.stage != STAGE_NEW or self.mapping_json.strip():
            return self.execute(context)
        if self.wizard or len(self.files) or self.filepath:
            try:
                fill_tables(self.tables, suggested_tables(self._paths(), _options_of(self),
                                                          sheet=self.sheet.strip() or None))
            except (GeoblenderError, OSError, ValueError) as exc:
                self.report({"ERROR"}, error_text(exc))
                return {"CANCELLED"}
            self.wizard = True
            return context.window_manager.invoke_props_dialog(
                self, width=DIALOG_WIDTH, translate=False, title=tr("Import of drillholes"))
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, context: Any) -> None:
        layout = self.layout
        project = core_provenance.SESSION.project
        options = _options_of(self)
        split = layout.split(factor=0.5)
        for column, props in ((split.column(), _DECLARATION_PROPS),
                              (split.column(), (*_READING_PROPS, *_DELIVERY_PROPS))):
            column.use_property_split = True
            for prop, text in props:
                column.prop(self, prop, text=_text(text), translate=False)
        try:
            declaration = self._declaration(project, options)
            choices = [_table_choice(table) for table in self.tables
                       if table.role != NOT_IMPORTED]
            check_declarations(choices, declaration, options)
        except DeclarationError as exc:
            layout.label(text=tr("Missing declarations: {missing}",
                                 missing=spanish_list(exc.missing)),
                         icon="ERROR", translate=False)
            declaration = None
        except (GeoblenderError, OSError, ValueError) as exc:
            layout.label(text=error_text(exc), icon="ERROR", translate=False)
            declaration = None
        for table in self.tables:
            self._draw_table(layout.box(), table, options, declaration)

    def _draw_table(self, box: Any, table: Any, options: ReadOptions,
                    declaration: SourceDeclaration | None) -> None:
        """Una tabla del asistente: su papel, el campo de cada columna con unos valores de
        ejemplo y sus primeras filas tal como se van a interpretar (RF-005-05)."""
        row = box.row()
        row.label(text=table.name, icon="FILE", translate=False)
        row.prop(table, "role", text="")
        if table.role == NOT_IMPORTED:
            return
        try:
            choice = _table_choice(table)
            rows = preview(choice, options).rows
        except (GeoblenderError, OSError, ValueError) as exc:
            box.label(text=error_text(exc), icon="ERROR", translate=False)
            return
        grid = box.grid_flow(columns=3, even_columns=False, align=True)
        for column in table.columns:
            sample = " · ".join(values[column.index].strip() for values in rows[:SAMPLE_ROWS]
                                if column.index < len(values))
            grid.label(text=column.name, translate=False)
            grid.label(text=sample, translate=False)
            grid.prop(column, "field", text="")
        if declaration is None:
            return
        lines = box.column(align=True)
        lines.label(text=tr("As it will be read (first rows)"), translate=False)
        for line in preview_lines(choice, options, declaration):
            lines.label(text=line, translate=False)

    def execute(self, context: Any) -> set[str]:
        blocked = unavailable_reason(IMPORT_DRILLHOLES)
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        if self.stage != STAGE_NEW:
            with core_provenance.caller_reports():
                return decide_pending(self, context)
        project = core_provenance.SESSION.project
        options = _options_of(self)
        if self.provenance_dialog and not self.wizard and not self.mapping_json.strip():
            if not self._paths():  # tras elegir los ficheros: el asistente
                self.report({"ERROR"}, tr("Choose the drillhole tables to import"))
                return {"CANCELLED"}
            values: dict[str, Any] = {name: getattr(self, name) for name in _KEPT_PROPS}
            _open_wizard({**values, "directory": self.directory, "filepath": self.filepath,
                          "files": [{"name": item.name} for item in self.files if item.name]})
            return {"CANCELLED"}
        try:
            choices = self._choices(options)
        except (GeoblenderError, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        if not choices:
            self.report({"ERROR"}, tr("Choose the drillhole tables to import"))
            return {"CANCELLED"}
        try:
            declaration = self._declaration(project, options)
            check_declarations(choices, declaration, options)
            received_at = _delivery_day(self.received_at)
        except (GeoblenderError, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        result = start_order(self, context, project, choices, declaration, options,
                             received_at=received_at,
                             received_from=self.received_from.strip() or None,
                             reason=self.reason.strip() or None)
        if result == {"FINISHED"}:
            self.report({"INFO"}, tr("Importing {count} drillhole tables in the background…",
                                     count=format_number(len(choices), 0)))
        return result


def _locked_text(path: Path, lock: Path) -> str:
    """El aviso de una base que otro programa tiene abierta (RF-005-15)."""
    return tr("«{file}» is open in another program (it has «{lock}»): close it, or confirm "
              "that it is read anyway", file=path.name, lock=lock.name)


def check_recmin(declaration: SourceDeclaration) -> None:
    """RF-005-07: lo que se declara siempre al importar una base de RecMin
    (:data:`RECMIN_NEEDS`) y no está en ``declaration``: ``interop.base.DeclarationError``,
    que lo nombra todo."""
    missing = missing_declarations(declaration, RECMIN_NEEDS)
    if missing:
        raise DeclarationError(RECMIN_LABEL, missing)


class GEOBLENDER_OT_dh_import_recmin_mdb(_DrillholesCommand, ProvenanceAwareOperator,
                                         bpy.types.Operator):
    """RecMin drillhole database (MDB), read-only"""

    bl_idname = IMPORT_RECMIN
    bl_label = "RecMin drillhole database…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.IMPORT_RECMIN

    filepath: StringProperty(  # type: ignore[valid-type]
        name="File", subtype="FILE_PATH", options=_FIELD,
    )
    filter_glob: StringProperty(  # type: ignore[valid-type]
        default="*.mdb;*.accdb", options={"HIDDEN"},
    )
    crs: StringProperty(  # type: ignore[valid-type]
        name="Horizontal CRS",
        description="EPSG code of the horizontal CRS of the collars, such as EPSG:25830 "
                    "(empty: undeclared, and nothing is imported)",
        options=_FIELD,
    )
    vertical: EnumProperty(  # type: ignore[valid-type]
        name="Vertical CRS", items=VERTICAL_ITEMS, default=UNDECLARED, options=_FIELD,
    )
    azimuth_ref: EnumProperty(  # type: ignore[valid-type]
        name="Azimuth reference", items=AZIMUTH_ITEMS, default=NOT_DECLARED, options=_FIELD,
    )
    declination_deg: StringProperty(  # type: ignore[valid-type]
        name="Magnetic declination",
        description="Magnetic declination in degrees, positive to the east, as written (only "
                    "with magnetic azimuths)",
        options=_FIELD,
    )
    decimal_mark: EnumProperty(  # type: ignore[valid-type]
        name="Decimal mark", items=DECIMAL_ITEMS, default="COMMA", options=_FIELD,
    )
    units: StringProperty(  # type: ignore[valid-type]
        name="Units of the elements",
        description="Unit of each element whose unit in the database is not g/t, ppm, ppb or "
                    "%, such as Au=g/t; Cu=%",
        options=_FIELD,
    )
    sentinels: StringProperty(  # type: ignore[valid-type]
        name="No-data values",
        description="Values of the source that mean no data, separated by «;», such as "
                    "−99;−999;ND",
        options=_FIELD,
    )
    negative_is_below_dl: BoolProperty(  # type: ignore[valid-type]
        name="Negative means below the detection limit",
        description="A negative value −x of an assay means «<x»", options=_FIELD,
    )
    density_kind: EnumProperty(  # type: ignore[valid-type]
        name="Density", items=DENSITY_ITEMS, default="ADOPTADO", options=_FIELD,
    )
    accept_locked: BoolProperty(  # type: ignore[valid-type]
        name=LOCKED_LABEL,
        description="Read the database although another program has it open (it has its lock "
                    "file)",
        options=_FIELD,
    )
    accept_schema: BoolProperty(  # type: ignore[valid-type]
        name="Read an unknown schema",
        description="Read a database whose schema version is not 11 or 12", options=_FIELD,
    )
    received_at: StringProperty(  # type: ignore[valid-type]
        name="Delivery date", description="Delivery day, DD/MM/YYYY (empty: no date)",
        options=_FIELD,
    )
    received_from: StringProperty(  # type: ignore[valid-type]
        name="Delivered by", description="Who delivered the input (empty: nobody recorded)",
        options=_FIELD,
    )
    reason: StringProperty(  # type: ignore[valid-type]
        name="Reason",
        description="Why the input replaces the one imported with the same data and other "
                    "settings",
        options=_FIELD,
    )
    # El diálogo (tras elegir la base) y lo que decide la persona en «Importación pendiente»
    # (la misma orden con ``stage`` y ``pending``).
    wizard: BoolProperty(options=_HIDDEN)  # type: ignore[valid-type]
    stage: EnumProperty(  # type: ignore[valid-type]
        items=STAGE_ITEMS, default=STAGE_NEW, options=_HIDDEN,
    )
    pending: StringProperty(options=_HIDDEN)  # type: ignore[valid-type]

    def _path(self) -> Path | None:
        """La base elegida (``None`` si no hay ninguna)."""
        return Path(bpy.path.abspath(self.filepath)) if self.filepath.strip() else None

    def _options(self) -> ReadOptions:
        """Cómo se lee la base: solo su separador decimal (el de los números escritos como
        texto); lo demás no se usa."""
        return ReadOptions(ENCODINGS["UTF8"], SEPARATORS["SEMICOLON"], 0,
                           DECIMALS[self.decimal_mark], None)

    def _declaration(self, project: Any, options: ReadOptions) -> SourceDeclaration:
        """Lo declarado en la orden, con la inclinación de RecMin (negativa hacia abajo, que no
        se declara: ``interop.recmin``); los errores, como en las tablas."""
        typed = self.declination_deg.strip()
        return SourceDeclaration(
            crs=parse_crs(self.crs), vertical=vertical_choice(self.vertical, project),
            azimuth_ref=AZIMUTH_REFS[self.azimuth_ref],
            declination_deg=parse_declination(typed) if typed else None,
            inclination_convention=InclinationConvention.NEGATIVE_DOWN,
            units=parse_units(self.units),
            value_rules=ValueRules(decimal_mark=options.decimal,
                                   sentinels=parse_sentinels(self.sentinels),
                                   negative_is_below_dl=self.negative_is_below_dl),
            density_kind=DENSITY_KINDS[self.density_kind])

    def invoke(self, context: Any, event: Any) -> set[str]:
        self.provenance_dialog = True
        if self.stage != STAGE_NEW:
            return self.execute(context)
        if self.wizard or self.filepath.strip():
            self.wizard = True
            return context.window_manager.invoke_props_dialog(
                self, width=RECMIN_DIALOG_WIDTH, translate=False,
                title=tr("Import of a RecMin drillhole database"))
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, context: Any) -> None:
        """La base (su formato y, si otro programa la tiene abierta, el aviso y su
        confirmación: RF-005-15), las declaraciones y la entrega y, si falta alguna
        declaración, cuál (RF-005-07)."""
        layout = self.layout
        path = self._path()
        box = layout.box()
        if path is None:
            box.label(text=tr("Choose the RecMin drillhole database to import"), icon="ERROR",
                      translate=False)
        else:
            try:
                found, _version = mdb_ports.read_format(path)
                shown = " · ".join((path.name, found.label))  # el formato, del dominio
                box.label(text=shown, icon="FILE", translate=False)
            except (GeoblenderError, OSError) as exc:
                box.label(text=error_text(exc), icon="ERROR", translate=False)
            lock = mdb_ports.lock_file(path)
            if lock is not None:
                box.label(text=_locked_text(path, lock), icon="ERROR", translate=False)
                box.prop(self, "accept_locked", text=_text(LOCKED_LABEL), translate=False)
        split = layout.split(factor=0.5)
        for column, props in ((split.column(), _RECMIN_DECLARATION_PROPS),
                              (split.column(), (*_RECMIN_READING_PROPS, *_DELIVERY_PROPS))):
            column.use_property_split = True
            for prop, text in props:
                column.prop(self, prop, text=_text(text), translate=False)
        try:
            check_recmin(self._declaration(core_provenance.SESSION.project, self._options()))
        except DeclarationError as exc:
            layout.label(text=tr("Missing declarations: {missing}",
                                 missing=spanish_list(exc.missing)),
                         icon="ERROR", translate=False)
        except (GeoblenderError, ValueError) as exc:
            layout.label(text=error_text(exc), icon="ERROR", translate=False)

    def execute(self, context: Any) -> set[str]:
        blocked = unavailable_reason(IMPORT_RECMIN)
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        if self.stage != STAGE_NEW:
            with core_provenance.caller_reports():
                return decide_pending(self, context)
        path = self._path()
        if path is None or not path.is_file():
            self.report({"ERROR"}, tr("Choose the RecMin drillhole database to import"))
            return {"CANCELLED"}
        if self.provenance_dialog and not self.wizard:  # tras elegirla: su diálogo
            values = {name: getattr(self, name) for name in _RECMIN_KEPT_PROPS}
            _open_wizard({**values, "filepath": self.filepath}, IMPORT_RECMIN)
            return {"CANCELLED"}
        project = core_provenance.SESSION.project
        options = self._options()
        try:
            mdb_ports.read_format(path)  # una base de Access (sin motor: su cabecera)
            lock = mdb_ports.lock_file(path)
            if lock is not None and not self.accept_locked:  # RF-005-15
                raise ValueError(_locked_text(path, lock))
            declaration = self._declaration(project, options)
            check_recmin(declaration)
            received_at = _delivery_day(self.received_at)
        except (GeoblenderError, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        choice = TableChoice(path, provenance.RECMIN_MDB, "", {}, None, entry_name(path))
        result = start_order(self, context, project, [choice], declaration, options,
                             received_at=received_at,
                             received_from=self.received_from.strip() or None,
                             reason=self.reason.strip() or None,
                             accept_schema=self.accept_schema, command=IMPORT_RECMIN)
        if result == {"FINISHED"}:
            self.report({"INFO"}, tr("Importing the RecMin drillhole database «{file}» in the "
                                     "background…", file=path.name))
        return result


class GEOBLENDER_OT_dh_set_detection_limit_policy(_DrillholesCommand, bpy.types.Operator):
    """How the values below the detection limit are treated"""

    bl_idname = SET_DETECTION_LIMIT
    bl_label = "Values below the detection limit…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}

    parameter: EnumProperty(  # type: ignore[valid-type]
        name="Part of the rule", items=RULE_ITEMS, default="METHOD", options=_FIELD,
    )

    def invoke(self, context: Any, event: Any) -> set[str]:
        return context.window_manager.invoke_props_dialog(
            self, translate=False, title=_text(RULE_LABEL))

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.prop(self, "parameter", text=tr("Change"), translate=False)
        layout.label(text=tr("It is changed with its reason in the project parameters; the "
                             "values stored do not change"), icon="INFO", translate=False)

    def execute(self, context: Any) -> set[str]:
        """La regla bajo el límite de detección (RF-005-26; plan §5.6.10, D-22): la registra
        con su valor por defecto si el proyecto aún no la tiene y abre el diálogo de
        ``geoblender.core_set_parameter`` con la clave de la parte elegida (desde un guion,
        sin ventana, se cambia con esa orden). No cambia ningún valor guardado."""
        blocked = unavailable_reason(SET_DETECTION_LIMIT)
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        project = core_provenance.SESSION.project
        try:
            ensure_detection_limit_rule(project)
        except (GeoblenderError, OSError, sqlite3.Error, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        key = RULE_KEYS[self.parameter]
        open_later(core_provenance.SET_PARAMETER, {"key": key})
        self.report({"INFO"}, tr("Change the parameter «{key}» with its reason: the values "
                                 "stored do not change", key=key))
        return {"FINISHED"}


class GEOBLENDER_OT_dh_validate(_DrillholesCommand, ProvenanceAwareOperator,
                                bpy.types.Operator):
    """Check the database, including the collar elevation against the DTM"""

    bl_idname = VALIDATE
    bl_label = "Validate the drillhole database"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.VALIDATE

    surface: StringProperty(  # type: ignore[valid-type]
        name="Surface",
        description="Terrain model to compare the collar elevations with (empty: the most "
                    "recent one; without any, that check is not evaluated)",
        options=_FIELD,
    )
    surfaces: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_view_dataset, options=_FIELD,
    )

    def provenance_inputs(self, context: Any) -> tuple[Use, ...]:
        return tuple(getattr(self, "_uses", ()))

    def invoke(self, context: Any, event: Any) -> set[str]:
        self.provenance_dialog = True
        project = core_provenance.SESSION.project
        try:
            records = project_surfaces(project) if project is not None else []
        except (GeoblenderError, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        if not records:  # nada que elegir: sin MDT (D-19)
            return self.execute(context)
        self.surfaces.clear()
        for record in records:
            item = self.surfaces.add()
            item.name = item.label = record.name
            item.uid = record.uid
        if not self.surface:
            self.surface = records[-1].name
        return context.window_manager.invoke_props_dialog(
            self, translate=False, title=_text(VALIDATION_LABEL))

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.prop_search(self, "surface", self, "surfaces", text=tr("Surface"),
                           translate=False)
        layout.label(text=tr("The collar elevations are compared with it (DH-W05)"),
                     icon="INFO", translate=False)

    def execute(self, context: Any) -> set[str]:
        blocked = unavailable_reason(VALIDATE)
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        project = core_provenance.SESSION.project
        try:
            with project.read() as conn:
                built = dataset_registry.get(conn, BASE_TABLES[0]) is not None
            if not built:
                raise ValueError(tr("First {step} ({path})", step=tr("import drillholes"),
                                    path=path_text(command_catalog(), IMPORT_DRILLHOLES,
                                                   i18n.language())))
            surface = chosen_surface(project, self.surface)
        except (GeoblenderError, OSError, ValueError) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        self._uses = tuple(validation_uses(surface))
        handle = self.begin(context, settings=validation_settings(surface),
                            params=list(dh_params.VALIDATION_KEYS), executor="job_thread")
        if handle is None:  # ya dicho por qué
            return {"CANCELLED"}
        start_validate(project, surface=surface, handle=handle)
        self.report({"INFO"}, tr("Validating the drillhole database in the background…"))
        return {"FINISHED"}


REPORT_SUFFIX = ".csv"
"""La extensión del informe de validación exportado (RF-005-19)."""
REPORT_NAME = "validacion_sondeos"
"""El nombre que propone el diálogo de la exportación, en ``exports/`` del proyecto."""
EXPORTED_ROLE = "exported"
"""El papel de lo que consume la exportación (``dh_validation_issue``)."""


def report_target(project: Any, filepath: str) -> Path:
    """El destino del informe de validación (la ruta del diálogo): un ``.csv`` fuera del
    proyecto o en su ``exports/`` (nunca sobre lo que gestiona el proyecto); si no,
    ``ValueError`` con el motivo. Sin escribir nada."""
    shown = filepath.strip()
    if not shown:
        raise ValueError(tr("Choose the file to export to"))
    path = Path(bpy.path.abspath(shown))
    if path.suffix.lower() != REPORT_SUFFIX:
        raise ValueError(tr("«{file}»: the validation report has the extension .csv, not "
                            "«{suffix}»; nothing has been written", file=path.name,
                            suffix=path.suffix or "—"))
    if (gis_provenance.inside_project(project.root, path)
            and gis_provenance.export_locator(project.root, path) is None):
        raise ValueError(tr("«{file}» is inside the project but not in its exports folder: "
                            "export to exports/ or outside the project; nothing has been "
                            "written", file=path.name))
    return path


def stored_report(project: Any) -> store.StoredValidation:
    """El informe guardado de la última validación de ``project`` (lo que se exporta); sin
    ninguna, ``ValueError`` con el paso previo."""
    with project.read() as conn:
        stored = store.stored_validation(conn)
    if stored is None:
        raise ValueError(tr("First {step} ({path})",
                            step=tr("validate the drillhole database"),
                            path=path_text(command_catalog(), VALIDATE, i18n.language())))
    return stored


def open_later(idname: str, values: Mapping[str, Any]) -> None:
    """Abre la orden ``idname`` (``geoblender.*``) desde la interfaz (``INVOKE_DEFAULT``)
    con ``values`` en cuanto acaba la que la llama (en un temporizador: su diálogo, encima);
    sin ventana (un guion, ``blender -b``), nada: lo dice el aviso de quien la llama."""
    manager = getattr(bpy.context, "window_manager", None)
    windows = list(getattr(manager, "windows", ()) or ())
    if not windows:
        return
    name = idname.partition(".")[2]

    def call() -> None:
        try:
            with bpy.context.temp_override(window=windows[0]):
                getattr(bpy.ops.geoblender, name)("INVOKE_DEFAULT", **values)
        except (RuntimeError, TypeError, AttributeError):
            LOGGER.warning("No se pudo abrir %s", idname, exc_info=True)

    bpy.app.timers.register(call, first_interval=0.0)


def _open_confirm(idname: str, values: Mapping[str, Any]) -> None:
    """Pide confirmar que se sustituye el destino que ya existe: la misma orden con
    ``confirm`` en cuanto acaba esta; sin ventana, nada (lo dice el aviso)."""
    open_later(idname, {"confirm": True, **values})


class GEOBLENDER_OT_dh_export_validation_report(_DrillholesCommand, ProvenanceAwareOperator,
                                                bpy.types.Operator):
    """Validation issues to CSV"""

    bl_idname = EXPORT_REPORT
    bl_label = "Export the validation report…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    provenance_op_type = provenance.EXPORT_VALIDATION

    filepath: StringProperty(  # type: ignore[valid-type]
        name="File", subtype="FILE_PATH", options=_FIELD,
    )
    filter_glob: StringProperty(default="*.csv", options={"HIDDEN"})  # type: ignore[valid-type]
    check_existing: BoolProperty(  # type: ignore[valid-type]
        default=True, options=_HIDDEN,
    )
    overwrite: BoolProperty(  # type: ignore[valid-type]
        name="Replace it", description="Replace the file if it already exists", options=_FIELD,
    )
    confirm: BoolProperty(options=_HIDDEN)  # type: ignore[valid-type]

    def provenance_inputs(self, context: Any) -> tuple[Use, ...]:
        return tuple(getattr(self, "_uses", ()))

    def invoke(self, context: Any, event: Any) -> set[str]:
        self.provenance_dialog = True
        if self.confirm:  # sustituir el destino que ya existe (spec §8: nunca sin confirmarlo)
            self.overwrite = True
            return context.window_manager.invoke_confirm(
                self, event, title=tr("Replace the file"),
                message=tr("«{file}» already exists: replace it?",
                           file=Path(self.filepath).name),
                confirm_text=tr("Replace"), translate=False)
        project = core_provenance.SESSION.project
        try:
            stored_report(project)
        except (GeoblenderError, OSError, ValueError, sqlite3.Error) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        if not self.filepath:
            self.filepath = str(Path(project.root, provenance.EXPORTS_FOLDER,
                                     REPORT_NAME + REPORT_SUFFIX))
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, context: Any) -> None:
        self.layout.prop(self, "overwrite", text=tr("Replace"), translate=False)

    def execute(self, context: Any) -> set[str]:
        blocked = unavailable_reason(EXPORT_REPORT)
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        project = core_provenance.SESSION.project
        try:
            target = report_target(project, self.filepath)
            stored = stored_report(project)
        except (GeoblenderError, OSError, ValueError, sqlite3.Error) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        if not self.check_write_target(target):  # RF-008-15: ya dicho, nombrando la carpeta
            return {"CANCELLED"}
        if target.exists() and not self.overwrite:
            text = tr("«{file}» already exists: confirm that it is replaced; nothing has been "
                      "written", file=target.name)
            if self.provenance_dialog:
                self.report({"WARNING"}, text)
                _open_confirm(EXPORT_REPORT, {"filepath": str(target)})
            else:
                self.report({"ERROR"}, text)
            return {"CANCELLED"}
        locator = gis_provenance.export_locator(project.root, target)
        self._uses = (Use(stored.dataset_uid, EXPORTED_ROLE),)
        # Solo el nombre del fichero: ninguna ruta en el proyecto (D21 de la 006).
        handle = self.begin(context, settings={"file": target.name,
                                               "in_exports": locator is not None})
        if handle is None:  # ya dicho por qué
            return {"CANCELLED"}
        lines = [tr("Validation report «{file}» exported: {issues} issues; not evaluated: "
                    "{notes}", file=target.name,
                    issues=format_number(len(stored.records), 0),
                    notes=format_number(len(stored.notes), 0))]
        if locator is not None:
            lines.append(tr("In the project as the deliverable {dataset}",
                            dataset=provenance.export_name(locator)))
        else:
            lines.append(tr("Written outside the project: it is not a dataset of the project"))
        text = "\n".join(lines)
        try:
            core_provenance.check_write_target(target)  # otra vez, justo antes de escribir
            store.export_report(project, handle, stored, target, locator=locator, message=text)
        except Exception as error:  # noqa: BLE001 - la operación queda fallida con el motivo
            LOGGER.warning("El informe de validación no se exportó", exc_info=True)
            reason = error_text(error)
            try:
                handle.fail(reason)
            except GeoblenderError:
                pass
            self.report({"ERROR"}, tr("«{file}» has not been exported: {reason}",
                                      file=target.name, reason=reason))
            return {"CANCELLED"}
        _say(text)
        self.report({"INFO"}, text.splitlines()[0])
        return {"FINISHED"}


class GEOBLENDER_OT_dh_desurvey(_DrillholesCommand, ProvenanceAwareOperator,
                                bpy.types.Operator):
    """Drillhole traces by minimum curvature, tangent or balanced tangent"""

    bl_idname = DESURVEY
    bl_label = "Compute traces…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER", "UNDO"}
    provenance_op_type = provenance.DESURVEY

    method: EnumProperty(  # type: ignore[valid-type]
        name="Method", items=METHOD_ITEMS, default="MINIMUM_CURVATURE", options=_FIELD,
    )
    scope: EnumProperty(  # type: ignore[valid-type]
        name="Drillholes", items=SCOPE_ITEMS, default="ALL", options=_FIELD,
    )

    def provenance_inputs(self, context: Any) -> tuple[Use, ...]:
        return tuple(desurvey_uses())

    def invoke(self, context: Any, event: Any) -> set[str]:
        self.provenance_dialog = True
        return context.window_manager.invoke_props_dialog(
            self, translate=False, title=_text(TRACES_LABEL))

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.prop(self, "method", text=tr("Method"), translate=False)
        layout.prop(self, "scope", text=tr("Drillholes"), translate=False)

    def execute(self, context: Any) -> set[str]:
        """Las trazas de la base (RF-005-20; plan §5.6.6): la operación ``dh.desurvey`` con la
        puerta de la 008, su método y sus sondeos en los ajustes y sus parámetros
        (``drillholes.params.DESURVEY_KEYS``), y su trabajo por la cola de incorporación
        (:func:`start_desurvey`). Sin base, no empieza."""
        blocked = unavailable_reason(DESURVEY)
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        project = core_provenance.SESSION.project
        try:
            with project.read() as conn:
                built = dataset_registry.get(conn, BASE_TABLES[0]) is not None
            if not built:
                raise ValueError(tr("First {step} ({path})", step=tr("import drillholes"),
                                    path=path_text(command_catalog(), IMPORT_DRILLHOLES,
                                                   i18n.language())))
        except (GeoblenderError, OSError, ValueError, sqlite3.Error) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        method, scope = METHODS[self.method], SCOPES[self.scope]
        handle = self.begin(context, settings=desurvey_settings(method, scope),
                            params=list(dh_params.DESURVEY_KEYS), executor="job_thread")
        if handle is None:  # ya dicho por qué
            return {"CANCELLED"}
        start_desurvey(project, handle, method=method, scope=scope)
        self.report({"INFO"}, tr("Computing the drillhole traces in the background…"))
        return {"FINISHED"}


class GEOBLENDER_OT_dh_set_azimuth_reference(_DrillholesCommand, ProvenanceAwareOperator,
                                             bpy.types.Operator):
    """Grid or true north and magnetic declination of the surveys"""

    bl_idname = SET_AZIMUTH
    bl_label = "Azimuth reference and declination…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}
    # Reimporta la entrada elegida: su tipo (de tablas o de RecMin) se sabe al empezar.
    provenance_op_type = ""

    input_uid: StringProperty(  # type: ignore[valid-type]
        name="Input",
        description="Import whose azimuth reference or declination changes (its uid or its "
                    "name)",
        options=_FIELD,
    )
    azimuth_ref: EnumProperty(  # type: ignore[valid-type]
        name="Azimuth reference", items=AZIMUTH_ITEMS, default=NOT_DECLARED, options=_FIELD,
    )
    declination_deg: StringProperty(  # type: ignore[valid-type]
        name="Magnetic declination",
        description="Magnetic declination in degrees, positive to the east, as written (only "
                    "with magnetic azimuths)",
        options=_FIELD,
    )
    reason: StringProperty(  # type: ignore[valid-type]
        name="Reason",
        description="Why the azimuth reference or the declination changes (required)",
        options=_FIELD,
    )
    inputs: CollectionProperty(  # type: ignore[valid-type]
        type=GEOBLENDER_PG_core_view_dataset, options=_FIELD,
    )

    def invoke(self, context: Any, event: Any) -> set[str]:
        """El diálogo: las importaciones con azimuts para elegir (la más reciente, si no se
        dio ninguna) con su referencia y su declinación de ahora."""
        self.provenance_dialog = True
        project = core_provenance.SESSION.project
        try:
            records = azimuth_inputs(project)
            if not records:
                azimuth_input(project, self.input_uid)  # lo que falta, dicho
        except (GeoblenderError, OSError, ValueError, sqlite3.Error) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        self.inputs.clear()
        for record in records:
            item = self.inputs.add()
            item.name = item.label = record.name
            item.uid = record.uid
        chosen = next((record for record in records
                       if self.input_uid in (record.uid, record.name)), records[-1])
        self.input_uid = chosen.name
        current = chosen.settings.get("azimuth_ref")
        self.azimuth_ref = next((identifier for identifier, value in AZIMUTH_REFS.items()
                                 if value == current), NOT_DECLARED)
        declination = chosen.settings.get("declination_deg")
        self.declination_deg = "" if declination is None else _number(float(declination))
        return context.window_manager.invoke_props_dialog(
            self, translate=False, title=_text(AZIMUTH_LABEL))

    def draw(self, context: Any) -> None:
        layout = self.layout
        layout.prop_search(self, "input_uid", self, "inputs", text=tr("Input"),
                           translate=False)
        layout.prop(self, "azimuth_ref", text=tr("Azimuth reference"), translate=False)
        row = layout.row()
        row.enabled = self.azimuth_ref == "MAGNETIC"
        row.prop(self, "declination_deg", text=tr("Magnetic declination"), translate=False)
        layout.prop(self, "reason", text=tr("Reason"), translate=False)
        layout.label(text=tr("The input is replaced: the traces of its drillholes become "
                             "stale"), icon="INFO", translate=False)

    def _changes(self, record: InputRecord) -> dict[str, Any]:
        """Lo que cambia de la entrada ``record`` (sus ajustes ``azimuth_ref`` y
        ``declination_deg``, como los guarda su declaración); ``ValueError`` con el aviso si
        falta la referencia, la declinación de un norte magnético o el motivo, sobra la
        declinación o no cambia nada."""
        name = record.name
        reference = AZIMUTH_REFS[self.azimuth_ref]
        if reference is None:
            raise ValueError(tr("Declare the azimuth reference of «{name}»: grid, true or "
                                "magnetic north", name=name))
        typed = self.declination_deg.strip()
        declination = None
        if reference == str(AzimuthRef.MAGNETIC):
            if not typed:
                raise ValueError(tr("With the magnetic north, write the magnetic declination "
                                    "of «{name}» in degrees, positive to the east", name=name))
            declination = parse_declination(typed)
        elif typed:
            raise ValueError(tr("The magnetic declination of «{name}» is only declared with "
                                "the magnetic north", name=name))
        if not self.reason.strip():
            raise ValueError(tr("Write why the azimuth reference of «{name}» changes: the "
                                "input is replaced", name=name))
        changes = {"azimuth_ref": reference, "declination_deg": declination}
        if all(record.settings.get(key) == value for key, value in changes.items()):
            raise ValueError(tr("«{name}» already has that azimuth reference and "
                                "declination: nothing changes", name=name))
        return changes

    def execute(self, context: Any) -> set[str]:
        """«Actualizar» la entrada elegida con la referencia del azimut y la declinación
        nuevas y su motivo (D-22; plan §5.6.10): ``reimport_input``, una sustitución de la
        entrada (RF-008-54) que, aplicada, reconstruye la base y deja obsoletas, por la huella
        de la desviación, las trazas de sus sondeos (RF-005-22). Lo que no vale no cambia
        nada."""
        blocked = unavailable_reason(SET_AZIMUTH)
        if blocked is not None:
            self.report({"ERROR"}, blocked)
            return {"CANCELLED"}
        project = core_provenance.SESSION.project
        try:
            record = azimuth_input(project, self.input_uid)
            changes = self._changes(record)
        except (GeoblenderError, OSError, ValueError, sqlite3.Error) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        op_type = (provenance.IMPORT_RECMIN if record.reader == provenance.RECMIN_MDB
                   else provenance.IMPORT_TABULAR)
        if ensure_ready(op_type, report=self.report, dialog=self.provenance_dialog) is None:
            return {"CANCELLED"}  # ya dicho por qué
        from ...core.provenance.importer import reimport_input  # al usarlo

        try:
            reimport_input(project, record.uid, self.reason.strip(), settings=changes)
        except (GeoblenderError, OSError, ValueError, sqlite3.Error) as exc:
            self.report({"ERROR"}, error_text(exc))
            return {"CANCELLED"}
        undo_watch.record(UndoKind.INPUT, record.name)  # Ctrl+Z no la deshace
        self.report({"INFO"}, tr("Updating «{name}» with the new azimuth reference in the "
                                 "background: the traces of its drillholes become stale",
                                 name=record.name))
        return {"FINISHED"}


class GEOBLENDER_OT_dh_show_display(_DrillholesCommand, bpy.types.Operator):
    """Trace, lithology, grade bars and labels of the drillholes"""

    bl_idname = SHOW_DISPLAY
    bl_label = "Display…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}


# --- Recálculo y reimportación (plan §5.6.10) --------------------------------------------------


def _not_delivered(what: str, value: str) -> GeoblenderError:
    """Lo que dice una función de la procedencia de los sondeos que aún no ha llegado (los
    recálculos, T42): ``dh.not_delivered``, sin hacer nada."""
    found = command_catalog().commands.get(SHOW_DISPLAY)
    note = unavailable_note(found) if found is not None else ""
    return GeoblenderError(NOT_DELIVERED, f"aún no está disponible ({note})", obj="Sondeos",
                           field=what, value=value)


def recompute_build_base(request: RecomputeRequest) -> OperationHandle:
    """El recálculo de ``dh.build_base`` (RF-008-26): la base con todo lo importado vigente.
    Aún no está disponible: ``dh.not_delivered``."""
    raise _not_delivered("recálculo", provenance.BUILD_BASE)


def recompute_validate(request: RecomputeRequest) -> OperationHandle:
    """El recálculo de ``dh.validate`` con los parámetros de hoy. Aún no está disponible:
    ``dh.not_delivered``."""
    raise _not_delivered("recálculo", provenance.VALIDATE)


def recompute_desurvey(request: RecomputeRequest) -> OperationHandle:
    """El recálculo de ``dh.desurvey`` con los mismos ajustes y los parámetros de hoy. Aún no
    está disponible: ``dh.not_delivered``."""
    raise _not_delivered("recálculo", provenance.DESURVEY)


def reimport_tabular(request: ReimportRequest) -> OperationHandle:
    """La reimportación de una entrada de una tabla de sondeos (CSV o XLSX) con sus ajustes
    registrados o los que pide ``request.settings`` (RF-008-11; T28: la referencia del
    azimut, D-22): véase :func:`_reimport`."""
    return _reimport(request)


def reimport_recmin(request: ReimportRequest) -> OperationHandle:
    """La reimportación de una base de RecMin con sus ajustes registrados o los que pide
    ``request.settings`` (RF-008-11; T28): véase :func:`_reimport`."""
    return _reimport(request)


# --- Declaraciones de la procedencia (ADR-0025 §2; plan §5.6.4 y §5.6.10) ----------------------

RECOMPUTE: Mapping[str, Callable[[RecomputeRequest], OperationHandle]] = MappingProxyType({
    provenance.BUILD_BASE: recompute_build_base,
    provenance.VALIDATE: recompute_validate,
    provenance.DESURVEY: recompute_desurvey,
})
"""La función de recálculo de cada tipo de operación de la 005 que se repite solo
(RF-008-26)."""
REIMPORT: Mapping[str, Callable[[ReimportRequest], OperationHandle]] = MappingProxyType({
    provenance.DH_CSV.partition("@")[0]: reimport_tabular,
    provenance.DH_XLSX.partition("@")[0]: reimport_tabular,
    provenance.RECMIN_MDB.partition("@")[0]: reimport_recmin,
})
"""La función de reimportación de cada lector de importación de la 005, sin versión
(RF-008-11)."""


def _choices(items: Sequence[tuple[str, ...]],
             stored: Mapping[str, Any]) -> tuple[tuple[Any, str], ...]:
    """Una elección de un diálogo como la guarda su operación: cada valor guardado
    (``stored``, por el identificador de su ``EnumProperty``) con el ``msgid`` del nombre con
    que se elige (``items``)."""
    names = {item[0]: item[1] for item in items}
    return tuple((value, names[identifier]) for identifier, value in stored.items())


_YES_NO = ((True, "Yes"), (False, "No"))
_SENTINELS = contract.SettingDef("sentinels", "No-data values", choices=(("", "None"),))
_BELOW_DL = contract.SettingDef("negative_is_below_dl", "Negative means below the detection "
                                "limit", choices=_YES_NO)
_DENSITY = contract.SettingDef("density_kind", "Density",
                               choices=_choices(DENSITY_ITEMS, DENSITY_KINDS))
_AZIMUTH = contract.SettingDef("azimuth_ref", "Azimuth reference",
                               choices=_choices(AZIMUTH_ITEMS, AZIMUTH_REFS))
_DECLINATION = contract.SettingDef("declination_deg", "Magnetic declination", unit="deg")
_DECIMAL = contract.SettingDef("decimal", "Decimal mark",
                               choices=_choices(DECIMAL_ITEMS, DECIMALS))
SETTING_DEFS: Mapping[str, tuple[contract.SettingDef, ...]] = MappingProxyType({
    provenance.IMPORT_TABULAR: (
        contract.SettingDef("role", "Role", choices=_choices(ROLE_ITEMS, ROLES)),
        contract.SettingDef("separator", "Separator",
                            choices=_choices(SEPARATOR_ITEMS, SEPARATORS)),
        _DECIMAL,
        contract.SettingDef("encoding", "Encoding", choices=_choices(ENCODING_ITEMS, ENCODINGS)),
        _SENTINELS,
        _BELOW_DL,
        contract.SettingDef("all_vertical", "All vertical", choices=_YES_NO),
        _DENSITY,
        _AZIMUTH,
        _DECLINATION,
        contract.SettingDef("inclination_convention", "Inclination",
                            choices=_choices(INCLINATION_ITEMS, INCLINATIONS)),
    ),
    provenance.IMPORT_RECMIN: (_DECIMAL, _SENTINELS, _BELOW_DL, _DENSITY, _AZIMUTH,
                               _DECLINATION),
    provenance.DESURVEY: (
        contract.SettingDef("method", "Method", choices=_choices(METHOD_ITEMS, METHODS)),
        contract.SettingDef("scope", "Drillholes", choices=_choices(SCOPE_ITEMS, SCOPES)),
    ),
})
"""Los ajustes de la orden de cada tipo de la 005 que enseña su procedencia (RF-008-29; plan
§5.6.4): en una importación, el papel de la tabla, el separador, el decimal, la codificación,
los valores sin dato (su texto, «−99;ND»: uno vacío es «Ninguno»), «−x = <x», «todos
verticales», el tipo de la densidad, la referencia del azimut, la declinación (en grados) y el
convenio de inclinación (en RecMin, los que tiene); en la desviación, el método y los sondeos.
Son claves de primer nivel de ``gb_operation.settings``, con los valores que guarda la
declaración (``drillholes.model.SourceDeclaration.conventions``). Ni rutas, ni nombres, ni los
CRS (los dice la entrada), ni la hoja de un XLSX (es la capa de su entrada); la base, la
validación y la exportación no tienen ninguno que enseñar."""
OPERATION_DEFS: tuple[contract.OperationDef, ...] = provenance.operation_defs(
    RECOMPUTE, settings=SETTING_DEFS)
"""Los ``OperationDef`` de los seis tipos de la 005, en el orden de
``drillholes.provenance.OPERATION_TYPES``, cada uno que se repite solo con su recálculo y con
los ajustes de :data:`SETTING_DEFS`."""
IMPORTER_DEFS: tuple[contract.ImporterDef, ...] = tuple(
    provenance.importer_def(reader_id, REIMPORT[reader_id])
    for reader_id in provenance.IMPORT_READERS)
"""Los ``ImporterDef`` de los lectores de importación de la 005 (``KeyError`` al cargar el
módulo si a uno le falta su reimportación)."""


classes: tuple[type, ...] = (
    GEOBLENDER_OT_dh_import_drillholes, GEOBLENDER_OT_dh_import_recmin_mdb,
    GEOBLENDER_OT_dh_set_detection_limit_policy, GEOBLENDER_OT_dh_validate,
    GEOBLENDER_OT_dh_export_validation_report, GEOBLENDER_OT_dh_desurvey,
    GEOBLENDER_OT_dh_set_azimuth_reference, GEOBLENDER_OT_dh_show_display,
)
"""Las órdenes de la 005, en el orden de :data:`COMMANDS`."""


def _mark_undelivered() -> None:
    """Las órdenes que aún no han llegado no están disponibles en el catálogo (su entrada sí:
    ``bl.ui.commands.is_undelivered``; T25), como un provisional."""
    for cls in classes:
        setattr(cls, UNDELIVERED_FLAG, cls.bl_idname in UNDELIVERED)


_mark_undelivered()

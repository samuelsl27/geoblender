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
provisional, y su recálculo y su reimportación lo dicen con ``dh.not_delivered`` sin hacer
nada. La entrada 005 del catálogo no está entregada todavía (``entries.toml``).

**La cola de incorporación** de los sondeos (:data:`INCORPORATIONS`, su temporizador
:func:`incorporation_tick` y :func:`pending_incorporations`; RNF-005-06, plan §5.6.7) es suya,
aparte de la de la topografía: lo que deja un trabajo entra en el proyecto por pasos;
desregistrar la cierra sin escribir nada más.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Mapping, Sequence
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, StringProperty

from ...core import i18n
from ...core import params as core_params
from ...core.catalog.search import path_text
from ...core.content import readers as content_readers
from ...core.errors import GeoblenderError
from ...core.georef import load_catalog
from ...core.i18n import tr
from ...core.params.model import ParamKind
from ...core.provenance import contract
from ...drillholes import jobs, provenance
from ...drillholes import params as dh_params
from ...drillholes.desurvey import Method
from ...drillholes.model import AzimuthRef, InclinationConvention
from ...interop import dh_content
from ...jobs import catalog as job_catalog
from ..scene import project_session
from ..scene.dh_view import NOT_DELIVERED
from ..ui.commands import catalog as command_catalog
from ..ui.commands import unavailable_note
from .core_provenance import ProvenanceAwareOperator, write_unavailable
from .incorporation import StepQueue

if TYPE_CHECKING:
    from ...core.provenance.contract import ReimportRequest
    from ...core.provenance.operations import OperationHandle
    from ...core.provenance.recompute import RecomputeRequest

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
UNDELIVERED: frozenset[str] = frozenset(COMMANDS)
"""Las órdenes cuya ejecución aún no ha llegado (plan 005, fase 3): no están disponibles y
dicen dónde estarán. La tarea que entrega una la quita de aquí."""
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
ROLE_ITEMS = [
    ("COLLAR", "Collars", ""),
    ("SURVEY", "Surveys", ""),
    ("LITHOLOGY", "Lithology", ""),
    ("ASSAY_WIDE", "Assays in columns", "One column per element"),
    ("ASSAY_LONG", "Assays in rows", "Element, value and unit in each row"),
    ("LITHOLOGY_CATALOG", "Lithology catalog", ""),
    ("ELEMENT_CATALOG", "Element catalog", ""),
]
ROLES: Mapping[str, str] = MappingProxyType(
    {identifier: identifier.lower() for identifier, *_rest in ROLE_ITEMS})
"""El papel de una tabla (``interop.drillholes_tabular.TableRole``, los de
``drillholes.provenance.TABLE_ROLES``)."""
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
_FIELD = {"SKIP_SAVE"}
_HIDDEN = {"HIDDEN", "SKIP_SAVE"}

_UNDO: list[Callable[[], None]] = []


# --- Registro --------------------------------------------------------------------------------


def register() -> None:
    """Registra las definiciones de parámetros, los lectores de contenido, los tipos de trabajo
    y las declaraciones de procedencia (:data:`OPERATION_DEFS`, :data:`IMPORTER_DEFS`) de los
    sondeos que aún no están; idempotente."""
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


def unregister() -> None:
    """Cierra las incorporaciones en cola (sin escribir nada más) y quita lo que puso
    :func:`register`, en orden inverso (lo que otro cambió después es suyo); idempotente."""
    INCORPORATIONS.drop()
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


# --- Las órdenes (plan §5.3.1 y §5.6) -----------------------------------------------------------


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
    decimal_mark: EnumProperty(  # type: ignore[valid-type]
        name="Decimal mark", items=DECIMAL_ITEMS, default="COMMA", options=_FIELD,
    )
    separator: EnumProperty(  # type: ignore[valid-type]
        name="Separator", items=SEPARATOR_ITEMS, default="SEMICOLON", options=_FIELD,
    )
    encoding: EnumProperty(  # type: ignore[valid-type]
        name="Encoding", items=ENCODING_ITEMS, default="UTF8", options=_FIELD,
    )
    header_row: IntProperty(  # type: ignore[valid-type]
        name="Lines before the header", default=0, min=0, options=_FIELD,
    )
    date_format: StringProperty(  # type: ignore[valid-type]
        name="Date format",
        description="Format of the dates of the source, such as %d/%m/%Y (empty: ISO, "
                    "YYYY-MM-DD)",
        options=_FIELD,
    )
    sheet: StringProperty(  # type: ignore[valid-type]
        name="Sheet", description="Sheet of an XLSX workbook (empty: the first one)",
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
        name="Read it although it is open",
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


class GEOBLENDER_OT_dh_set_detection_limit_policy(_DrillholesCommand, bpy.types.Operator):
    """How the values below the detection limit are treated"""

    bl_idname = SET_DETECTION_LIMIT
    bl_label = "Values below the detection limit…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}


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
    overwrite: BoolProperty(  # type: ignore[valid-type]
        name="Replace it", description="Replace the file if it already exists", options=_FIELD,
    )


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


class GEOBLENDER_OT_dh_show_display(_DrillholesCommand, bpy.types.Operator):
    """Trace, lithology, grade bars and labels of the drillholes"""

    bl_idname = SHOW_DISPLAY
    bl_label = "Display…"
    bl_translation_context = TRANSLATION_CONTEXT
    bl_options = {"REGISTER"}


# --- Recálculo y reimportación (plan §5.6.10) --------------------------------------------------


def _not_delivered(what: str, value: str) -> GeoblenderError:
    """Lo que dice una función de la procedencia de los sondeos cuya orden aún no ha llegado:
    ``dh.not_delivered``, sin hacer nada."""
    found = command_catalog().commands.get(IMPORT_DRILLHOLES)
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
    registrados (RF-008-11). Aún no está disponible: ``dh.not_delivered``."""
    raise _not_delivered("reimportación", provenance.IMPORT_TABULAR)


def reimport_recmin(request: ReimportRequest) -> OperationHandle:
    """La reimportación de una base de RecMin con sus ajustes registrados (RF-008-11). Aún no
    está disponible: ``dh.not_delivered``."""
    raise _not_delivered("reimportación", provenance.IMPORT_RECMIN)


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

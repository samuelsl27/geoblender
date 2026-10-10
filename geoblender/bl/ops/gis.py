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
  (:func:`reimport_dtm`, RF-008-11; plan §5.6.3 y §5.6.8).

:func:`register` pone lo que falta y apunta cómo quitarlo; :func:`unregister` lo quita en orden
inverso (lo que otro cambió después es suyo). Los dos son simétricos e idempotentes.

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
  MDT del proyecto (RF-006-06). Una sustitución sin motivo o un aviso de alturas elipsoidales
  **esperan la decisión de la persona** (:func:`waiting_imports`): la misma orden con
  ``pending`` (el uid de la operación), ``decision`` y, en una sustitución, ``reason`` la sigue
  o la cancela; mientras, el trabajo está «pendiente de incorporar».
- ``geoblender.gis_resample_to_grid`` (Topografía ▸ Superficies ▸ Rejilla de proyecto desde un
  MDT…): el MDT importado a ``gis_dtm_<nombre>`` en la rejilla del proyecto (la ventana de
  trabajo con el paso del proyecto, ``gis.grid.project_grid``), con el método en el informe
  (RF-006-11). La fracción mínima sale en el diálogo con el valor del proyecto, su insignia de
  tipo y «sin confirmar» si lo está (:func:`fraction_field`): sin cambiarla, se consume y se
  anota (RF-008-05); tecleada otra, es un ajuste de la orden y no cambia el parámetro (D18). Con otro CRS u otra
  referencia vertical, su trabajo reproyecta en proceso aparte con las ruedas de la extensión
  (``site_override``, :func:`wheels_site`; D11).

Sin proyecto, ``poll`` dice el paso previo («Primero abra un proyecto (Proyecto ▸ … ▸ Abrir
proyecto…)», con su ruta en la barra); sin la procedencia o en solo lectura (también dentro de
una carpeta de solo lectura), su motivo (:func:`unavailable_reason`). El servicio de CRS de las
órdenes es el del registro de adaptadores (:data:`crs_resolver`, que las pruebas cambian). El
informe de cada orden queda como mensaje de su operación y en los avisos de la sesión.
"""

from __future__ import annotations

import datetime as dt
import functools
import logging
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import bpy
from bpy.props import CollectionProperty, EnumProperty, StringProperty

from ...core import i18n
from ...core import params as core_params
from ...core.catalog.search import path_text
from ...core.content import readers as content_readers
from ...core.content.readers import MAIN_ROLE
from ...core.datasets import registry as dataset_registry
from ...core.errors import GeoblenderError
from ...core.georef import load_catalog
from ...core.i18n import format_number, tr
from ...core.inputs import get as get_input
from ...core.inputs import locate_source, reader_roles, resolve_source
from ...core.inputs.model import SourcePrint
from ...core.inputs.registry import Reuse, Substitute
from ...core.numbers import parse_decimal
from ...core.provenance import contract
from ...core.provenance.messages import ProvenanceError
from ...core.provenance.operations import Use, begin_operation
from ...gis import content, jobs, provenance, store
from ...gis import params as gis_params
from ...gis.crs import (
    ELLIPSOIDAL_ETRS89,
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
    job_params,
    job_paths,
    parse_crs,
    plan_import,
    read_settings,
    vertical_samples,
)
from ...gis.geotiff.reader import read_geotiff
from ...gis.grid import Grid, project_grid
from ...gis.messages import GisError
from ...gis.raster import Raster
from ...gis.vertical import BAND_KEY, check_vertical_offset
from ...interop.csv_tables import read_table
from ...jobs import catalog as job_catalog
from ...jobs.ingest import job_outcome
from ..props.core import GEOBLENDER_PG_core_view_dataset
from ..scene import project_session
from ..ui.commands import catalog as command_catalog
from ..ui.provenance import badge
from ..ui.views import no_work_window_message
from . import core_provenance
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
    los tipos de trabajo y las declaraciones de procedencia de las órdenes de ``gis`` que aún no
    están; idempotente."""
    missing = [defn for defn in gis_params.DEFINITIONS
               if defn.key not in core_params.DEFINITIONS]
    if missing:
        core_params.register_definitions(missing)
        _UNDO.append(_unregister_definitions)
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
    definitions = provenance.operation_defs({provenance.RESAMPLE: recompute_resample},
                                            op_types=(provenance.IMPORT_DTM, provenance.RESAMPLE))
    for definition in definitions:
        if definition.op_type not in contract.OPERATIONS:
            contract.register_operation(definition)
            _UNDO.append(_unregister_if(contract.OPERATIONS, definition.op_type, definition,
                                        contract.unregister_operation))
    for reader_id in DTM_IMPORTERS:
        if reader_id not in contract.IMPORTERS:
            importer = provenance.importer_def(reader_id, reimport_dtm)
            contract.register_importer(importer)
            _UNDO.append(_unregister_if(contract.IMPORTERS, reader_id, importer,
                                        contract.unregister_importer))


def unregister() -> None:
    """Quita lo que puso :func:`register`, en orden inverso (lo que otro cambió después es
    suyo), y olvida las importaciones que esperaban una decisión; idempotente."""
    _WAITING.clear()
    while _UNDO:
        _UNDO.pop()()


def _unregister_if(view: Any, key: str, item: object,
                   remove: Callable[[str], object]) -> Callable[[], None]:
    def undo() -> None:
        if view.get(key) is item:  # si otro lo cambió, es suyo
            remove(key)

    return undo


def _unregister_definitions() -> None:
    core_params.unregister_definitions(MODULE)


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


def unavailable_reason() -> str | None:
    """Por qué no se puede lanzar ahora una orden de un MDT (su ``poll``), en el idioma de
    Geoblender: sin proyecto, el paso previo («Primero abra un proyecto (Proyecto ▸ … ▸ Abrir
    proyecto…)»); sin la procedencia o en solo lectura, su motivo
    (``core_provenance.write_unavailable``); si se puede, ``None``."""
    if project_session.current() is None:
        path = path_text(command_catalog(), OPEN_PROJECT, i18n.language())
        return tr("First {step} ({path})", step=tr("open a project"), path=path)
    return write_unavailable()


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
    return launch(plan.handle, jobs.READ_RASTER,
                  label=tr("Import of the DTM «{name}»", name=source.name),
                  params=job_params(source, max_cells=plan.control[MAX_CELLS_KEY]),
                  paths=job_paths(source), on_finish=functools.partial(_import_finished, plan),
                  grace_s=jobs.CANCEL_GRACE_S)


def _import_finished(plan: _Import, result: JobResult) -> None:
    """El final del trabajo de una importación: si terminó bien, :func:`_settle_import` (si
    no, la procedencia la deja cancelada o fallida con el motivo de la 004)."""
    if result.state != _SUCCEEDED:
        return
    plan.result = result
    _settle_import(plan)


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


def _settle_import(plan: _Import) -> str:
    """Sigue la importación de ``plan`` (su trabajo ya terminó bien) y dice cómo quedó:
    ``"reused"`` (la misma entrada con los mismos ajustes: cancelada con el aviso,
    RF-008-54), ``"waiting"`` (una sustitución sin motivo o el aviso de alturas elipsoidales:
    espera la decisión de la persona, RF-008-11, RF-006-06), ``"done"`` (incorporada) o
    ``"failed"`` (fallida con su motivo)."""
    result = plan.result
    assert result is not None
    project = plan.handle.project
    language = i18n.language()
    try:
        outcome = job_outcome(result, result.job_dir)
        spec = _input_spec(plan, outcome.summary)
        if plan.previous_uid is None:
            found = store.classify_source(project, spec)
            if isinstance(found, Reuse):
                with store.ResultWriter(project, plan.handle) as out:
                    out.declare_input(spec)  # la deja cancelada con el aviso
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
        if not plan.checked:
            plan.check = _vertical_check(plan, outcome)
            plan.checked = True
        if plan.check is not None and plan.check.warn and not plan.confirmed:
            return _ask(plan, _CONFIRM, plan.check.message(language) or "")
        report = _import_report(plan, outcome.summary)
        role = jobs.OUT_SOURCE_GRID.role
        with store.ResultWriter(project, plan.handle) as out:
            out.declare_input(spec, previous_uid=plan.previous_uid, reason=plan.reason)
            out.copy_file(provenance.SOURCE_GRID, plan.source.name, outcome.file(role),
                          content=jobs.digest_of(outcome.summary["outputs"][role]["digest"]),
                          sha256=outcome.output(role).sha256)
            core_provenance.ingest_job_result(plan.handle, result, out.write, message=report)
    except Exception as error:  # noqa: BLE001 - la operación queda fallida con el motivo
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


def _vertical_check(plan: _Import, outcome: Any) -> VerticalCheck | None:
    """La comparación de las cotas importadas con la primera rejilla del proyecto vigente que
    tiene posiciones comunes (RF-006-06, A16), en el CRS y la referencia del proyecto (con la
    transformación de la importación) y con la banda del proyecto; sin rejilla del proyecto,
    ``None``."""
    project = plan.handle.project
    references = [record for record in store.list_gis_datasets(
        project, families=(provenance.PROJECT_GRID,)) if str(record.status) == "current"]
    if not references:
        return None
    found = read_geotiff(outcome.file(jobs.OUT_SOURCE_GRID.role), max_cells=sys.maxsize)
    xyz = vertical_samples(Raster(found.grid, found.values, plan.source.crs,
                                  plan.source.vertical))
    if plan.transform is not None:
        xyz = plan.transform.apply(xyz)
    for record in references:
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
    lines.extend(str(note) for note in summary.get("notes", ()))
    return "\n".join(lines)


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
        """Sigue o cancela la importación ``pending`` que espera la decisión de la persona."""
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
        if _settle_import(plan) == "failed":
            self.report({"ERROR"}, plan.failure)
            return {"CANCELLED"}
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
    source = DtmSource(record.name, reader, files, jobs.crs_of(dict(record.crs_h)),
                       jobs.vertical_of(dict(record.crs_v)), settings)
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


def fraction_field(project: Any) -> tuple[str, str]:
    """El campo de la fracción mínima del diálogo de la rejilla del proyecto (D18; plan
    §5.6.1): su valor en el proyecto, como se teclea, y su insignia de tipo con «sin confirmar»
    si lo está."""
    value, kind, unconfirmed = project_value(project, FRACTION_KEY)
    note = badge(kind)
    if unconfirmed:
        note = f"{note} {tr('unconfirmed')}"
    return _decimal(value), note


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


classes: tuple[type, ...] = (GEOBLENDER_OT_gis_import_dtm, GEOBLENDER_OT_gis_resample_to_grid)
"""Los operadores de ``gis`` (T28: las órdenes de un MDT)."""

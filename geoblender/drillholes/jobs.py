# SPDX-License-Identifier: GPL-3.0-or-later
"""Los trabajos de los sondeos (spec 005, T23; RF-005-04, RF-005-05 a RF-005-10, RF-005-13 a
RF-005-16, RF-005-20; plan 005 §5.3.3, §5.6.5 a §5.6.7; ADR-0010; plan 004 §5.3.1).

Lo que puede pasar de 1 s va a los trabajos de la 004 (RNF-005-06: avance en la barra de estado
y cancelación). Este módulo declara los siete tipos de la 005 (:data:`WORKER_INFOS`, con su
estimación y su función ``run``) y ``bl/ops/dh.py`` los registra con
``jobs.catalog.register_worker``: ``jobs/`` no importa ``drillholes`` (ARQ-07). Cada
``workers/<tipo>.py`` envuelve la misma función (registra antes los lectores de contenido), así
que el hilo de Blender y el proceso aparte hacen lo mismo. Todos en el entorno ``blender`` (sin
motor de cálculo):

- ``dh_import_tabular`` y ``dh_import_recmin`` leen una fuente (un CSV o una hoja de un XLSX;
  una base de RecMin) y van **siempre en proceso aparte** (plan §5.6.7; la base de RecMin, con
  su ``powershell.exe`` hijo dentro del *Job Object* del trabajo, que lo termina si el trabajo
  se cancela o muere). Leer formatos ajenos es de ``interop`` (``drillholes`` no lo importa,
  ARQ-07): sus funciones están en ``interop.dh_jobs`` y aquí, solo su tipo (sin ``run``: nunca
  van en el hilo);
- ``dh_import_apply``, ``dh_build_base``, ``dh_validate``, ``dh_desurvey`` y
  ``dh_view_arrays``, automáticos (en el hilo si se estiman en ≤ 5 s, RF-004-03), con su
  función aquí.

**La petición nunca lleva una ruta** (ARQ-11): la fuente de una importación llega por la línea
de órdenes (``--path source_main=…``) y el trabajo la copia a ``in/`` con
``JobDir.copy_input`` (huella antes, durante y después; si cambia, ``source_changed``); lo del
proyecto lo escribe ``bl`` en ``in/`` antes de lanzarlo, leído por pasos (``launch_job(arrays=
…)`` sueltos, :func:`loose_arrays`, o ``inputs=`` con un npz). **Ningún trabajo abre
``project.gpkg``** ni escribe fuera de su carpeta. Los parámetros van resueltos (los del
proyecto, ``handle.params``).

**Resultados** en ``out/`` con su huella (``WorkerContext.add_output``, con el papel de
:class:`~..gis.jobs.JobOutput`) y un resumen JSON. Cada tabla que será un dato del proyecto va
con sus filas (las de ``schema.insert_rows``, en un npz de ``drillholes.arrays.rows_arrays``;
``bl`` las escribe con ``drillholes.arrays.TableRows``) y su ``ContentDigest`` de
``schema.table_digest``, el que calcula el registro de la 008 al escribirla: así el hilo de
Blender no vuelve a leer la tabla al incorporarla (plan §5.6.5 y §5.6.7). Cancelar a mitad, o
un fallo, deja ``out/`` vacía; un error del dominio para el usuario es un ``JobFailed`` con su
código y su texto en español (RF-004-12), y una petición que no vale, ``request_invalid``.

Los tipos, con sus parámetros, sus entradas (``in/``) y sus resultados (``out/``):

- ``dh_import_tabular`` (``interop.dh_jobs.run_import_tabular``): ``reader`` (``io.dh_csv@1`` o
  ``io.dh_xlsx@1``), ``name``, ``role`` (el papel de la tabla), ``mapping`` (campo → columna),
  ``declaration`` (:func:`declaration_json`), ``settings`` (los de lectura, el decimal y el
  formato de fecha), ``crs`` y ``vertical`` (los del proyecto), ``project_holes`` (los sondeos
  de la base, RF-005-11), ``catalogs`` (los del proyecto, ``drillholes.arrays.catalogs_json``)
  y ``size``; ``source_main`` → ``source.npz`` (lo leído, en lo declarado: las columnas del
  modelo, ``drillholes.arrays.tables_arrays``) y ``report.json`` (recuentos, rechazos, códigos
  nuevos, cómo se darían de alta, ``register_codes``, y sondeos que ya están), con el
  ``ContentDigest`` de la fuente (el de ``core_content_hash``) y la huella de su fichero;
- ``dh_import_recmin`` (``interop.dh_jobs.run_import_recmin``): ``declaration``, ``settings``
  (el decimal, si se da), ``accept_schema``, ``crs``, ``vertical``, ``project_holes``,
  ``catalogs`` y ``size``; ``source_main`` → ``source.npz``, ``report.json`` (con los
  recuentos por tabla de RecMin y, de cada sondeo que ya está, sus registros por tabla,
  ``hole_rows``) y lo que extrae el motor en ``mdb/`` (el crudo). Una versión de esquema que
  no es 11 ni 12 sin
  ``accept_schema``: termina sin resultados con ``needs_confirmation`` en el resumen
  (RF-005-15), y se vuelve a lanzar con la confirmación;
- ``dh_import_apply``: ``name``, ``crs``, ``keep_holes`` (los sondeos que conservan los
  registros del proyecto: no se importan, RF-005-11), ``replace_holes`` (los que sustituyen a
  los del proyecto: se cuentan, RF-005-12), ``register_codes`` (los códigos nuevos que se dan
  de alta, RF-005-10; las litologías, con un color determinista distinto de
  ``taken_colors``); ``source`` (el ``source.npz`` de la lectura) → ``dh_src_<rol>.npz`` por
  papel con sus filas y su hash;
- ``dh_build_base``: ``crs``, ``vertical``, ``project_uid``, ``entries`` (cada entrada vigente
  en el orden en que se registró: ``input``, el nombre de sus arrays en ``in/``; ``uid``;
  ``label``; ``declaration``) y ``previous`` (``{sondeo: survey_sha256}`` de la base anterior)
  → las once tablas de la base (``<tabla>.npz``) con su hash, los sondeos cuya huella cambia,
  las transformaciones y las notas. Con otro CRS, otro datum o un azimut magnético o
  geográfico necesita pyproj (:func:`needs_site`);
- ``dh_validate``: ``crs``, ``vertical``, ``thresholds`` (los cinco umbrales,
  ``ValidationParams``), ``work_window`` y, con MDT, ``dem_crs`` y ``dem_vertical`` (por
  defecto, los de la base: un ``gis_dtm_*`` del proyecto); ``base`` (la base), ``dem`` (el
  MDT, un ``.tif``) y ``stored_xyz`` → ``dh_validation_issue.npz`` con su hash y
  ``report.json`` (las notas y la diferencia de cada boca con el MDT);
- ``dh_desurvey``: ``crs``, ``vertical``, ``method``, ``depth_tolerance_m``,
  ``trace_step_m`` y, opcional (T28, «solo las obsoletas»), ``holes`` (las posiciones de las
  bocas que se calculan); ``base``, ``survey_sha256`` (la huella de cada boca) y, con
  ``holes``, ``kept`` (las trazas de las demás, que pasan tal cual) → ``dh_trace.npz`` con su
  hash (los sondeos con errores de alcance S, sin traza: RF-005-17);
- ``dh_view_arrays``: ``crs``, ``vertical``, ``method``, ``depth_tolerance_m``,
  ``max_step_m``, ``log_set``, ``element`` (con ``legend`` o, sin ella, ``unit`` y la leyenda
  por defecto; ``offset_m`` y ``width_m``), ``labels_at_end``, ``excluded`` y, opcional (T29),
  ``holes`` (las posiciones de las bocas que se dibujan: las que tienen traza en el
  proyecto); ``base`` → ``view.npz`` (:func:`write_view`).

La base (``base``), lo leído (``source``) y lo importado de cada entrada son los arrays de
``drillholes.arrays`` (:func:`loose_arrays` para ``launch_job(arrays=…)``, o un npz por
``inputs=``); el CRS y el datum, ``gis.jobs.crs_json`` y ``vertical_json``; una declaración,
:func:`declaration_json`; los catálogos del proyecto, ``drillholes.arrays.catalogs_json``.

Python puro y numpy (ADR-0004).
"""

from __future__ import annotations

import colorsys
import functools
import hashlib
import io
import json
import math
import numbers
import os
import shutil
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

import numpy as np

from ..core.content.encoder import NORMALIZER, ContentDigest
from ..core.content.readers import ContentReader, read_steps
from ..core.errors import GeoblenderError
from ..core.georef import CrsRef, VerticalRef
from ..gis.jobs import (
    JobOutput,
    crs_json,
    crs_of,
    digest_json,
    path_name,
    plain,
    vertical_json,
    vertical_of,
    window_of,
)
from ..jobs.catalog import WorkerInfo
from ..jobs.messages import JobError
from ..jobs.paths import JobDir
from ..jobs.protocol import JobRequest
from ..jobs.worker_api import JobCancelled, JobFailed
from .arrays import (
    TableRows,
    catalogs_of,
    dataclass_arrays,
    dataclass_of,
    entry_of,
    load_npz,
    rows_arrays,
    save_npz,
    set_of,
    tables_of,
)
from .model import (
    TABLES,
    AzimuthRef,
    Catalogs,
    CatalogEntry,
    DrillholeSet,
    Element,
    LithologyCode,
    SourceDeclaration,
    ValueRules,
    name_key,
)
from .schema import BASE_TABLES, LAYOUTS, source_layout, table_digest

__all__ = [
    "BUILD_BASE",
    "CANCEL_GRACE_S",
    "DESURVEY",
    "IMPORT_APPLY",
    "IMPORT_RECMIN",
    "IMPORT_TABULAR",
    "INPUT_BASE",
    "INPUT_DEM",
    "INPUT_HASHES",
    "INPUT_KEPT",
    "INPUT_SOURCE",
    "INPUT_STORED",
    "MDB_FOLDER",
    "OUT_RAW_ROLE",
    "OUT_REPORT",
    "OUT_SOURCE",
    "OUT_VIEW",
    "PACKED_TAG",
    "VALIDATE",
    "VIEW_ARRAYS",
    "WORKER_INFOS",
    "WORKER_INFOS_BY_NAME",
    "WORKER_NAMES",
    "JobParams",
    "ViewArrays",
    "cancelled_probe",
    "copy_source",
    "declaration_json",
    "declaration_of",
    "finish",
    "input_arrays",
    "issue_rows",
    "job_function",
    "loose_arrays",
    "needs_site",
    "new_colors",
    "packed_arrays",
    "read_table_output",
    "read_view",
    "run_build_base",
    "run_desurvey",
    "run_import_apply",
    "run_validate",
    "run_view_arrays",
    "source_digest",
    "span",
    "table_output",
    "trace_rows",
    "write_json",
    "write_view",
]

OWNER = "dh"
"""El módulo dueño de sus trabajos (``JobRequest.owner``)."""
CANCEL_GRACE_S = 1.0
"""Plazo de gracia de sus peticiones (el mínimo de la 004): cancelar para en ≤ 2 s también si
el trabajo está en un tramo sin puntos de cancelación (RF-004-09)."""

IMPORT_TABULAR = "dh_import_tabular"
IMPORT_RECMIN = "dh_import_recmin"
IMPORT_APPLY = "dh_import_apply"
BUILD_BASE = "dh_build_base"
VALIDATE = "dh_validate"
DESURVEY = "dh_desurvey"
VIEW_ARRAYS = "dh_view_arrays"
WORKER_NAMES: tuple[str, ...] = (IMPORT_TABULAR, IMPORT_RECMIN, IMPORT_APPLY, BUILD_BASE,
                                 VALIDATE, DESURVEY, VIEW_ARRAYS)
"""Los tipos de trabajo de la 005 (y sus módulos de ``workers/``), en el orden del plan
§5.6.7."""

OUT_SOURCE = JobOutput("source.npz", "source")
"""Lo leído de una fuente (las columnas del modelo en lo declarado y sus catálogos)."""
OUT_REPORT = JobOutput("report.json", "report")
OUT_VIEW = JobOutput("view.npz", "view")
MDB_FOLDER = "mdb"
"""La carpeta de ``out/`` donde deja el extractor de una base de RecMin el crudo."""
OUT_RAW_ROLE = "raw"
"""El papel de lo que extrae el motor de una base de RecMin (``out/mdb/…``)."""

INPUT_SOURCE = "source"
"""``dh_import_apply``: lo leído (``in/source.npz`` o sus arrays ``source_<clave>``)."""
INPUT_BASE = "base"
"""La base del proyecto (``in/base.npz`` o sus arrays ``base_<clave>``)."""
INPUT_DEM = "dem"
"""``dh_validate``: el MDT elegido (``in/dem.tif``)."""
INPUT_STORED = "stored_xyz"
"""``dh_validate``: la posición de cada boca en la capa (``(bocas, 3)`` en float64)."""
INPUT_HASHES = "survey_sha256"
"""``dh_desurvey``: la huella de la desviación de cada boca (``S64``, una por boca)."""
INPUT_KEPT = "kept"
"""``dh_desurvey`` (T28): las trazas que se conservan, filas de ``dh_trace``
(``drillholes.arrays.rows_arrays``), de las bocas que no están en ``holes``."""

COPYING_TEXT = "Copiando la fuente…"
READING_TEXT = "Leyendo la fuente…"
HASHING_TEXT = "Calculando el hash de contenido de la fuente…"
WRITING_TEXT = "Escribiendo el resultado…"
DONE_TEXT = "Terminado"
COPY_SHARE = 0.75
"""La parte del avance de copiar la fuente que es la copia verificada (lee la fuente tres
veces); el resto, la huella de la copia (una lectura)."""
ROWS_SHARE = 0.15
"""La parte del avance de una tabla que es guardar sus filas (los análisis de V-ref: 1,5 s);
el resto, su hash (unos 8 s)."""

# Estimaciones [I] (spec 005, T38 y T41: con V-ref, 572 000 filas; T31 las medirá).
APPLY_ROW_S = 15e-6
"""Filas de lo importado y su hash, por fila (V-ref: 0,2 s y 7,9 s)."""
BUILD_ROW_S = 20e-6
"""La base, sus filas y su hash, por fila de lo importado (V-ref: 1,0 + 0,22 + 8,7 s)."""
VALIDATE_ROW_S = 2e-6
"""Validar y hashear las incidencias, por fila de la base (V-ref: 0,34 s con MDT)."""
DESURVEY_HOLE_S = 1e-3
"""Trazas, polilíneas y su hash, por sondeo (2 000 sondeos: unas décimas)."""
VIEW_ROW_S = 2e-6
"""Curvas, barras y etiquetas, por fila de la base (V-ref: 0,3 + 0,2 s)."""

_HASH_BLOCK = 1 << 20
_GOLDEN = 0.618033988749895
_COLOR_SATURATION = 0.55
_COLOR_VALUE = 0.85
_MAX_COLOR_STEPS = 100_000


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


# --- La declaración en la petición -------------------------------------------------------------


def declaration_json(declaration: SourceDeclaration) -> dict[str, Any]:
    """La declaración de una fuente en la petición (JSON): su CRS y su datum (los de
    ``gis.jobs.crs_json`` y ``vertical_json``), sus convenciones (``conventions()``), el
    separador decimal y el formato de fecha. :func:`declaration_of` la devuelve igual."""
    if not isinstance(declaration, SourceDeclaration):
        raise TypeError(f"la declaración es un SourceDeclaration, no {declaration!r}")
    return {"crs": crs_json(declaration.crs), "vertical": vertical_json(declaration.vertical),
            **declaration.conventions(), "decimal": declaration.value_rules.decimal_mark,
            "date_format": declaration.date_format}


def declaration_of(value: object) -> SourceDeclaration:
    """La declaración de :func:`declaration_json`; ``ValueError`` o ``TypeError`` si no lo
    es."""
    keys = {"crs", "vertical", "all_vertical", "azimuth_ref", "declination_deg",
            "density_kind", "inclination_convention", "negative_is_below_dl", "sentinels",
            "units", "decimal", "date_format"}
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ValueError(f"una declaración es {{{', '.join(sorted(keys))}}}, no {value!r}")
    return SourceDeclaration(
        crs=crs_of(value["crs"]), vertical=vertical_of(value["vertical"]),
        azimuth_ref=value["azimuth_ref"], declination_deg=value["declination_deg"],
        inclination_convention=value["inclination_convention"], units=dict(value["units"]),
        value_rules=ValueRules(decimal_mark=value["decimal"],
                               sentinels=frozenset(value["sentinels"]),
                               negative_is_below_dl=value["negative_is_below_dl"]),
        all_vertical=value["all_vertical"], density_kind=value["density_kind"],
        date_format=value["date_format"])


# --- Lo común de los trabajos ------------------------------------------------------------------


def _job_name(request: JobRequest) -> str:
    for candidate in (request.label, request.worker, request.job_uid):
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return OWNER


class JobParams:
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

    def optional_text(self, key: str) -> str | None:
        value = self.values.get(key)
        return None if value is None else self.text(key)

    def number(self, key: str, default: float | None = None) -> float:
        value = self.values.get(key, default)
        if isinstance(value, bool) or not isinstance(value, numbers.Real) or not math.isfinite(
                value):
            raise self.invalid(f"«{key}» no es un número finito ({value!r})")
        return float(value)

    def boolean(self, key: str, default: bool = False) -> bool:
        value = self.values.get(key, default)
        if not isinstance(value, bool):
            raise self.invalid(f"«{key}» es verdadero o falso, no {value!r}")
        return value

    def mapping(self, key: str, default: Mapping[str, Any] | None = None) -> dict[str, Any]:
        value = self.values.get(key, default)
        if not isinstance(value, Mapping):
            raise self.invalid(f"«{key}» no es un objeto JSON ({value!r})")
        return dict(value)

    def texts(self, key: str) -> list[str]:
        value = self.values.get(key, [])
        if not isinstance(value, list | tuple) or not all(isinstance(v, str) for v in value):
            raise self.invalid(f"«{key}» es una lista de textos, no {value!r}")
        return list(value)

    def parsed(self, key: str, parse: Callable[[Any], Any], *, required: bool = True) -> Any:
        value = self.values.get(key)
        if value is None and required:
            raise self.invalid(f"falta «{key}»")
        try:
            return parse(value)
        except (ValueError, TypeError, KeyError) as error:
            raise self.invalid(f"«{key}» no vale: {error}") from None

    def crs(self, key: str = "crs") -> CrsRef:
        return self.parsed(key, crs_of)

    def vertical(self, key: str = "vertical") -> VerticalRef:
        return self.parsed(key, vertical_of)

    def declaration(self, key: str = "declaration") -> SourceDeclaration:
        return self.parsed(key, declaration_of)

    def catalogs(self, key: str = "catalogs") -> Catalogs:
        found = self.values.get(key)
        return Catalogs() if found is None else self.parsed(key, catalogs_of)


def cancelled_probe(ctx: _Context) -> Callable[[], bool]:
    """``cancelled()`` del dominio: si se pidió parar el trabajo (sin lanzar)."""

    def probe() -> bool:
        try:
            ctx.check_cancelled()
        except JobCancelled:
            return True
        return False

    return probe


def span(ctx: _Context, low: float, high: float,
         text: str = "") -> Callable[..., None]:
    """``progress(fracción, texto)`` en el tramo [``low``, ``high``] del avance del trabajo
    (lanza ``JobCancelled`` si se pidió parar)."""

    def progress(fraction: float, shown: str = "") -> None:
        ctx.progress(low + (high - low) * min(max(float(fraction), 0.0), 1.0), shown or text)

    return progress


def _clear_outputs(ctx: _Context) -> None:
    """Deja ``out/`` vacía (cancelación o fallo: ningún resultado)."""
    folder = ctx.job_dir.outputs_dir
    if not folder.is_dir():
        return
    for child in folder.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)


def _failed(error: GeoblenderError) -> JobFailed:
    """El fallo explicado (RF-004-12) de un error para el usuario del dominio."""
    text = str(error)
    values = getattr(error, "values", None)
    found = values if isinstance(values, Mapping) else error.context
    return JobFailed(error.code, msgid=getattr(error, "msgid", None) or text, text=text,
                     values={str(key): plain(value) for key, value in found.items()})


def job_function(run: Callable[[Any], dict[str, Any]]) -> Callable[[Any], dict[str, Any]]:
    """La función de un trabajo: si se cancela o falla, ``out/`` queda vacía; un error del
    dominio para el usuario es ``JobFailed``."""

    @functools.wraps(run)
    def guarded(ctx: Any) -> dict[str, Any]:
        try:
            return run(ctx)
        except BaseException as error:
            _clear_outputs(ctx)
            if isinstance(error, GeoblenderError) and not isinstance(error, JobError):
                raise _failed(error) from None
            raise

    return guarded


def finish(ctx: _Context, outputs: Sequence[JobOutput]) -> None:
    """El último punto de cancelación (con todo escrito) y la declaración de los resultados
    con su huella."""
    ctx.progress(1.0, DONE_TEXT)
    for output in outputs:
        ctx.add_output(ctx.output_path(output.file), output.role)


def write_json(ctx: _Context, output: JobOutput, value: object) -> None:
    """``value`` en JSON (sin NaN: los de ``gis.jobs.plain``) en ``out/<fichero>``."""
    ctx.output_path(output.file).write_text(
        json.dumps(plain(value), ensure_ascii=False, indent=1, allow_nan=False),
        encoding="utf-8")


def _stamp(path: Path) -> tuple[int, int] | None:
    try:
        info = path.stat()
    except OSError:
        return None
    return info.st_size, info.st_mtime_ns


def _sha256(path: Path, progress: Callable[[float], None]) -> str:
    digest = hashlib.sha256()
    size = max(1, path.stat().st_size)
    read = 0
    with open(path, "rb") as stream:
        while block := stream.read(_HASH_BLOCK):
            digest.update(block)
            read += len(block)
            progress(min(1.0, read / size))
    return digest.hexdigest()


def copy_source(ctx: _Context, request: JobParams, *, low: float,
                high: float) -> tuple[Path, dict[str, Any]]:
    """La copia verificada en ``in/`` del fichero de la fuente que llega por ``--path``
    (``source_main``; ``JobDir.copy_input``: el motor de Access deja su bloqueo junto a ella,
    nunca junto a la fuente) y su huella (sha256, tamaño y fecha), con el avance en
    [``low``, ``high``]. Si la fuente cambia mientras se copia, ``source_changed``; sin la
    ruta, ``request_invalid``."""
    name = path_name("main")
    source = ctx.paths.get(name)
    if source is None:
        raise request.invalid(f"falta la ruta «{name}» de la fuente (--path)")
    source = Path(source)
    progress = span(ctx, low, high, COPYING_TEXT)
    ctx.check_cancelled()
    before = _stamp(source)
    relative = ctx.job_dir.copy_input(source, name, job=request.job,
                                      progress=lambda f: progress(COPY_SHARE * f))
    if before is None or _stamp(source) != before:
        raise JobError("source_changed", job=request.job, path=source)
    copy = ctx.job_dir.path / relative
    sha256 = _sha256(copy, lambda f: progress(COPY_SHARE + (1.0 - COPY_SHARE) * f))
    return copy, {"sha256": sha256, "size": before[0], "mtime_ns": before[1]}


def source_digest(ctx: _Context, reader: ContentReader, kind: str, files: Mapping[str, Path],
                  declarations: Mapping[str, Any], settings: Mapping[str, Any], low: float,
                  high: float) -> ContentDigest:
    """El ``ContentDigest`` de la fuente con su lector de contenido (el mismo que da
    ``core_content_hash``), con avance y cancelación entre trozos; unos ajustes que el lector
    no admite son ``request_invalid``."""
    try:
        request = reader.request(kind, declarations, files, settings, normalizer=NORMALIZER)
    except (ValueError, TypeError) as error:
        raise JobError("request_invalid", job=_job_name(ctx.request), detail=str(error)) from None
    steps = read_steps(reader, request)
    try:
        ctx.check_cancelled()
        for done in steps:
            ctx.progress(low + (high - low) * done, HASHING_TEXT)
    except (ValueError, TypeError) as error:
        raise JobError("request_invalid", job=_job_name(ctx.request), detail=str(error)) from None
    finally:
        steps.close()
    return request.hasher.digest()


def loose_arrays(name: str, arrays: Mapping[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Los arrays de una entrada ``name`` como entradas sueltas de ``launch_job(arrays=…)``
    (``<name>_<clave>``), que :func:`input_arrays` vuelve a juntar."""
    return {f"{name}_{key}": value for key, value in arrays.items()}


PACKED_TAG = "npz-"
"""Lo que distingue una parte empaquetada de una entrada (:func:`packed_arrays`) de sus
arrays sueltos (cuyas claves empiezan por el nombre de una tabla)."""


def packed_arrays(name: str, part: str,
                  arrays: Mapping[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Los arrays ``arrays`` de la parte ``part`` (una tabla, los catálogos…) de la entrada
    ``name`` como **una** entrada suelta de ``launch_job(arrays=…)``
    (``<name>_npz-<part>``): un npz sin comprimir en un array de bytes (``uint8``), que
    :func:`input_arrays` abre y junta con las demás partes (T28: un fichero por tabla en
    ``in/`` en vez de uno por columna; cada uno, la 004 lo escribe y lo sincroniza aparte).
    Sin arrays, ninguna; ``ValueError`` con un array de objetos de Python (sin *pickle*)."""
    if not arrays:
        return {}
    for key, array in arrays.items():
        if not isinstance(array, np.ndarray) or array.dtype.hasobject:
            raise ValueError(f"«{key}» no es un array de numpy sin objetos de Python")
    buffer = io.BytesIO()
    np.savez(buffer, **arrays)
    return {f"{name}_{PACKED_TAG}{part}": np.frombuffer(buffer.getbuffer(), dtype=np.uint8)}


def _unpacked(path: Path) -> dict[str, np.ndarray]:
    """Los arrays de una parte empaquetada (:func:`packed_arrays`), sin *pickle*."""
    with open(path, "rb") as stream:
        raw = np.load(stream, allow_pickle=False)
    with np.load(io.BytesIO(raw.tobytes()), allow_pickle=False) as data:
        return {key: data[key] for key in data.files}


def input_arrays(ctx: _Context, name: str) -> dict[str, np.ndarray] | None:
    """Los arrays de la entrada ``name``: los del npz ``in/<name>.npz`` o, sueltos
    (:func:`loose_arrays`), los de ``in/<name>_<clave>.npy`` y los de sus partes empaquetadas
    (:func:`packed_arrays`, ``in/<name>_npz-<parte>.npy``); ``None`` si no llega."""
    entries = ctx.request.inputs
    if name in entries:
        return load_npz(ctx.input_path(name))
    head = f"{name}_"
    found: dict[str, np.ndarray] = {}
    for entry in entries:
        if entry.startswith(head + PACKED_TAG):
            found.update(_unpacked(ctx.input_path(entry)))
        elif entry.startswith(head):
            with open(ctx.input_path(entry), "rb") as stream:
                found[entry[len(head):]] = np.load(stream, allow_pickle=False)
    return found or None


def _required_arrays(ctx: _Context, request: JobParams, name: str) -> dict[str, np.ndarray]:
    found = input_arrays(ctx, name)
    if found is None:
        raise request.invalid(f"falta la entrada «{name}»")
    return found


def _base(ctx: _Context, request: JobParams, crs: CrsRef, vertical: VerticalRef,
          low: float, high: float) -> DrillholeSet:
    """La base del proyecto de ``in/`` (``base``) en el CRS y el datum de la petición, con
    su avance en [``low``, ``high``]."""
    arrays = _required_arrays(ctx, request, INPUT_BASE)
    try:
        return set_of(arrays, crs=crs, vertical=vertical,
                      progress=span(ctx, low, high, READING_TEXT))
    except (ValueError, TypeError) as error:
        raise request.invalid(f"la base de los sondeos de «{INPUT_BASE}» no vale: "
                              f"{error}") from None


def table_output(table: str) -> JobOutput:
    """El resultado con las filas de la tabla ``table`` (de la base, de lo calculado o de lo
    importado, ``dh_src_<rol>``): ``<table>.npz`` con el papel ``table``."""
    return JobOutput(f"{table}.npz", table)


def read_table_output(path: Path | str, table: str) -> TableRows:
    """Las filas de un resultado de :func:`table_output` (``drillholes.arrays.TableRows``)."""
    layout = LAYOUTS[table] if table in LAYOUTS else source_layout(
        table.removeprefix("dh_src_"))
    return TableRows(layout, load_npz(path))


def _tables(ctx: _Context, crs: CrsRef, tables: Sequence[tuple[str, Any, Sequence[Any]]],
            low: float, high: float) -> dict[str, dict[str, Any]]:
    """Escribe las filas de cada tabla ``(nombre, layout, filas)`` en su resultado y calcula
    su ``ContentDigest`` (``schema.table_digest``, el del registro de la 008), con el avance
    en [``low``, ``high``] repartido por filas; devuelve lo de cada una para el resumen."""
    total = sum(len(rows) + 1 for _, _, rows in tables) or 1
    done = 0
    found: dict[str, dict[str, Any]] = {}
    cancelled = cancelled_probe(ctx)
    for name, layout, rows in tables:
        start = low + (high - low) * done / total
        done += len(rows) + 1
        end = low + (high - low) * done / total
        middle = start + (end - start) * ROWS_SHARE
        ctx.progress(start, WRITING_TEXT)
        output = table_output(name)
        save_npz(ctx.output_path(output.file),
                 rows_arrays(layout, rows, progress=span(ctx, start, middle, WRITING_TEXT)))
        digest = table_digest(layout, rows, crs, progress=span(ctx, middle, end),
                              cancelled=cancelled)
        found[name] = {"file": output.relative, "digest": digest_json(digest),
                       "rows": len(rows)}
    return found


def _count_estimate(rate_s: float) -> Callable[[Mapping[str, Any]], float | None]:
    """La estimación ``count`` × ``rate_s`` (``count``: filas o sondeos de la petición);
    ``None`` sin ``count``."""

    def estimate(params: Mapping[str, Any]) -> float | None:
        count = params.get("count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            return None
        return count * rate_s

    return estimate


def needs_site(worker: str, params: Mapping[str, Any]) -> bool:
    """Si el trabajo ``worker`` con ``params`` necesita las ruedas de la extensión (pyproj)
    en su intérprete: ``launch_job(..., site_override=<carpeta de las ruedas>)`` (plan
    §5.6.7). Solo ``dh_build_base`` cuando una entrada declara otro CRS u otro datum que el
    proyecto (se transforman sus bocas) o un azimut magnético o geográfico (la convergencia);
    sin las entradas o sin el CRS del proyecto, verdadero."""
    if worker != BUILD_BASE:
        return False
    entries = params.get("entries")
    if not isinstance(entries, list | tuple) or "crs" not in params or "vertical" not in params:
        return True
    for entry in entries:
        declaration = entry.get("declaration") if isinstance(entry, Mapping) else None
        if not isinstance(declaration, Mapping):
            return True
        crs, vertical = declaration.get("crs"), declaration.get("vertical")
        if crs is not None and crs != params["crs"]:
            return True
        if vertical is not None and vertical != params["vertical"]:
            return True
        if declaration.get("azimuth_ref") in (AzimuthRef.MAGNETIC, AzimuthRef.TRUE):
            return True
    return False


# --- dh_import_apply ---------------------------------------------------------------------------


def new_colors(count: int, taken: Sequence[str]) -> list[str]:
    """``count`` colores «#RRGGBB» para litologías nuevas (RF-005-10), deterministas y
    distintos de ``taken`` (sin mayúsculas) y entre sí: tonos repartidos por la proporción
    áurea con saturación y brillo fijos (ninguno es gris)."""
    used = {color.upper() for color in taken}
    found: list[str] = []
    step = 0
    while len(found) < count:
        if step > _MAX_COLOR_STEPS:
            raise ValueError(f"no quedan {count} colores distintos de los {len(used)} usados")
        red, green, blue = colorsys.hsv_to_rgb((step * _GOLDEN) % 1.0, _COLOR_SATURATION,
                                               _COLOR_VALUE)
        step += 1
        color = "#{:02X}{:02X}{:02X}".format(*(round(c * 255) for c in (red, green, blue)))
        if color not in used:
            used.add(color)
            found.append(color)
    return found


def _kept(columns: Any, keep: frozenset[str], field: str) -> tuple[Any, int]:
    """Las filas de ``columns`` cuyo sondeo (``field``) no está en ``keep`` (sin mayúsculas)
    y cuántas se quitan."""
    if not keep or not len(columns):
        return columns, 0
    names = getattr(columns, field).tolist()
    stay = np.array([name is None or name_key(name) not in keep for name in names],
                    dtype=np.bool_)
    return columns.take(np.flatnonzero(stay)), int((~stay).sum())


def _counted(columns: Any, holes: frozenset[str], field: str) -> int:
    """Cuántas filas de ``columns`` son de un sondeo (``field``) de ``holes`` (sin
    mayúsculas)."""
    if not holes or not len(columns):
        return 0
    return sum(1 for name in getattr(columns, field).tolist()
               if name is not None and name_key(name) in holes)


def _registered(catalogs: Catalogs, codes: Mapping[str, Any], taken: Sequence[str],
                request: JobParams) -> tuple[Catalogs, dict[str, list[Any]]]:
    """Los catálogos de la entrada con los códigos nuevos que se dan de alta (los que no
    tiene ya, sin mayúsculas): litologías con su esquema y un color nuevo, elementos con su
    unidad, sectores, grupos y zonas."""
    allowed = {"lithology", "element", "sector", "group", "zone"}
    unknown = sorted(set(codes) - allowed)
    if unknown:
        raise request.invalid(f"«register_codes» tiene catálogos desconocidos: {unknown}")
    lithology = list(catalogs.lithology)
    known = {(name_key(c.log_set), name_key(c.code)) for c in lithology}
    added: dict[str, list[Any]] = {}
    pairs = [tuple(pair) for pair in codes.get("lithology", [])]
    wanted = [(log_set, code) for log_set, code in pairs
              if (name_key(log_set), name_key(code)) not in known]
    colors = new_colors(len(wanted), [*taken, *(c.color for c in lithology)])
    for (log_set, code), color in zip(wanted, colors, strict=True):
        lithology.append(LithologyCode(code, log_set=log_set, color=color))
        known.add((name_key(log_set), name_key(code)))
        added.setdefault("lithology", []).append([log_set, code, color])
    elements = list(catalogs.elements)
    seen = {name_key(e.code) for e in elements}
    for code, unit in (tuple(pair) for pair in codes.get("element", [])):
        if name_key(code) not in seen:
            elements.append(Element(code, unit))
            seen.add(name_key(code))
            added.setdefault("element", []).append([code, unit])
    groups: dict[str, list[CatalogEntry]] = {}
    for kind, attribute in (("sector", "sectors"), ("group", "groups"), ("zone", "zones")):
        entries = list(getattr(catalogs, attribute))
        seen = {name_key(e.code) for e in entries}
        for code in codes.get(kind, []):
            if name_key(code) not in seen:
                entries.append(CatalogEntry(code))
                seen.add(name_key(code))
                added.setdefault(kind, []).append(code)
        groups[attribute] = entries
    return Catalogs(lithology=tuple(lithology), elements=tuple(elements), **groups), added


@job_function
def run_import_apply(ctx: _Context) -> dict[str, Any]:
    """``dh_import_apply``: lo leído de una entrada (``in/source``) con las decisiones de la
    persona (RF-005-10, RF-005-11): los sondeos que conservan sus registros del proyecto
    (``keep_holes``) fuera de todas sus tablas y los códigos nuevos dados de alta en sus
    catálogos (``register_codes``; las litologías con un color determinista distinto de los
    del proyecto, ``taken_colors``). Deja las filas de cada ``dh_src_<rol>`` (las de
    ``drillholes.store.source_tables``) con su hash (``schema.table_digest``), las que
    escribe ``SourceWriter``. El resumen dice, por tabla, las filas quitadas (``removed``) y
    las de los sondeos que ya están en el proyecto y se sustituyen (``replace_holes``:
    ``replaced``, el informe de RF-005-12)."""
    from .store import source_tables  # importa la procedencia: solo al usarlo

    request = JobParams(ctx)
    crs = request.crs()
    keep = frozenset(name_key(name) for name in request.texts("keep_holes"))
    replace = frozenset(name_key(name) for name in request.texts("replace_holes")) - keep
    codes = request.mapping("register_codes", {})
    taken = request.texts("taken_colors")
    ctx.progress(0.0, READING_TEXT)
    arrays = _required_arrays(ctx, request, INPUT_SOURCE)
    try:
        tables, catalogs = tables_of(arrays, progress=span(ctx, 0.0, 0.2, READING_TEXT))
    except (ValueError, TypeError) as error:
        raise request.invalid(f"lo leído de «{INPUT_SOURCE}» no vale: {error}") from None
    removed: dict[str, int] = {}
    replaced: dict[str, int] = {}
    for name in TABLES:
        field = "name" if name == "collars" else "hole_name"
        tables[name], removed[name] = _kept(tables[name], keep, field)
        replaced[name] = _counted(tables[name], replace, field)
    try:
        catalogs, added = _registered(catalogs, codes, taken, request)
    except (ValueError, TypeError) as error:
        raise request.invalid(f"«register_codes» no vale: {error}") from None
    ctx.progress(0.2, WRITING_TEXT)
    rows = source_tables(collars=tables["collars"], surveys=tables["surveys"],
                         lithology=tables["lithology"], assays=tables["assays"],
                         zones=tables["zones"], structures=tables["structures"],
                         catalogs=catalogs)
    found = _tables(ctx, crs, [(f"dh_src_{role}", source_layout(role), table_rows)
                               for role, table_rows in rows.items()], 0.3, 0.99)
    summary = {"name": request.text("name", ""), "removed": removed, "replaced": replaced,
               "registered": added, "outputs": found}
    finish(ctx, [table_output(name) for name in found])
    return summary


# --- dh_build_base -----------------------------------------------------------------------------


def _entries(ctx: _Context, request: JobParams, low: float, high: float) -> list[Any]:
    """Lo importado vigente de la petición (``entries``, en el orden en que se registró), con
    su avance en [``low``, ``high``]."""
    listed = request.values.get("entries")
    if not isinstance(listed, list | tuple):
        raise request.invalid(f"«entries» es la lista de lo importado, no {listed!r}")
    found = []
    for number, item in enumerate(listed, start=1):
        if not isinstance(item, Mapping) or not {"input", "uid", "declaration"} <= set(item):
            raise request.invalid(f"la entrada {number} de «entries» es {{input, uid, label, "
                                  f"declaration}}, no {item!r}")
        arrays = _required_arrays(ctx, request, str(item["input"]))
        share = high - low
        progress = span(ctx, low + share * (number - 1) / len(listed),
                        low + share * number / len(listed), READING_TEXT)
        try:
            found.append(entry_of(arrays, input_uid=item["uid"],
                                  declaration=declaration_of(item["declaration"]),
                                  label=item.get("label"), progress=progress))
        except (ValueError, TypeError) as error:
            raise request.invalid(f"la entrada {number} de «entries» no vale: {error}") from None
        ctx.check_cancelled()
    return found


@job_function
def run_build_base(ctx: _Context) -> dict[str, Any]:
    """``dh_build_base``: la base de los sondeos (``build_base.build_base``; RF-005-08,
    RF-005-11, RF-005-27 a RF-005-29) desde lo importado vigente, en el CRS y el datum del
    proyecto: las once tablas con sus filas y su hash, los sondeos cuya huella de la
    desviación cambia respecto a ``previous`` (RF-005-22, el ``detail`` de ``dh_collar``), las
    transformaciones con su precisión y las notas. El servicio de CRS (pyproj) lo da
    ``adapters.registry`` dentro del trabajo, solo si hace falta (:func:`needs_site`)."""
    from .build_base import build_base, changed_holes

    request = JobParams(ctx)
    crs, vertical = request.crs(), request.vertical()
    project_uid = request.text("project_uid")
    previous = request.values.get("previous")
    if previous is not None and not isinstance(previous, Mapping):
        raise request.invalid(f"«previous» es {{sondeo: survey_sha256}}, no {previous!r}")
    ctx.progress(0.0, READING_TEXT)
    entries = _entries(ctx, request, 0.0, 0.1)
    ctx.progress(0.1, "Construyendo la base de los sondeos…")
    try:
        base = build_base(entries, None, crs, vertical, project_uid=project_uid)
    except ValueError as error:
        raise request.invalid(str(error)) from None
    ctx.progress(0.3, WRITING_TEXT)
    found = _tables(ctx, crs, [(name, LAYOUTS[name], base.rows(name)) for name in BASE_TABLES],
                    0.3, 0.99)
    summary = {
        "holes": len(base.dset.collars),
        "changed": list(changed_holes(previous or {}, base)),
        "transforms": [{**plain(item), "info": plain(item.info)} for item in base.transforms],
        "notes": [{**plain(note), "message": note.message} for note in base.notes],
        "outputs": found,
    }
    finish(ctx, [table_output(name) for name in BASE_TABLES])
    return summary


# --- dh_validate ---------------------------------------------------------------------------------


def _value_text(value: object) -> str | None:
    """El valor de una incidencia en ``dh_validation_issue.value`` (texto): el texto tal cual,
    «sí»/«no», el número por su decimal más corto con «.» o ``None``."""
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "sí" if value else "no"
    if isinstance(value, float):
        return np.format_float_positional(value + 0.0, unique=True, trim="-")
    return str(value)


def issue_rows(report: Any) -> list[tuple[Any, ...]]:
    """Las filas de ``dh_validation_issue`` de un informe de ``drillholes.validate`` (las de
    ``schema.insert_rows``): el sondeo por su id (``fid`` = posición + 1) y su nombre, el
    código, el nivel, el alcance, la tabla, la fila (su ``fid``), el esquema, el elemento, el
    código del catálogo, el tramo, el campo, el valor en texto y el mensaje en español."""
    rows = []
    for issue in report.issues:
        scope = issue.scope
        rows.append((
            issue.hole + 1 if issue.hole >= 0 else None, issue.hole_name, issue.code,
            str(issue.level), None if scope is None else str(scope), issue.table,
            None if issue.row_ref is None else issue.row_ref + 1, issue.log_set,
            issue.element, issue.catalog_code, issue.depth_from, issue.depth_to, issue.field,
            _value_text(issue.value), issue.message("es")))
    return rows


@job_function
def run_validate(ctx: _Context) -> dict[str, Any]:
    """``dh_validate``: las incidencias de la base (``drillholes.validate``; RF-005-16 a
    RF-005-18) con los umbrales de la petición, la ventana de trabajo y, si llega, el MDT
    (``in/dem.tif``, bilineal con ``gis.raster.sample``) y la posición de cada boca en la capa
    (DH-W15): ``dh_validation_issue.npz`` con su hash y ``report.json`` (las notas, sin evaluar,
    y la diferencia de cada boca con el MDT)."""
    from ..gis.geotiff.reader import read_geotiff
    from ..gis.raster import Raster
    from .surface import raster_sampler
    from .validate import Level, ValidationParams, validate

    request = JobParams(ctx)
    crs, vertical = request.crs(), request.vertical()
    thresholds = request.parsed("thresholds", lambda value: ValidationParams(**dict(value)))
    window = request.parsed("work_window", lambda value: None if value is None
                            else window_of(value), required=False)
    ctx.progress(0.0, READING_TEXT)
    dset = _base(ctx, request, crs, vertical, 0.0, 0.1)
    surface = None
    if INPUT_DEM in ctx.request.inputs:  # un MDT del proyecto: por defecto, en su CRS y datum
        dem_crs = request.crs("dem_crs") if "dem_crs" in request.values else crs
        dem_vertical = (request.vertical("dem_vertical") if "dem_vertical" in request.values
                        else vertical)
        source = read_geotiff(ctx.input_path(INPUT_DEM), max_cells=sys.maxsize,
                              progress=span(ctx, 0.1, 0.3), cancelled=cancelled_probe(ctx))
        surface = raster_sampler(Raster(source.grid, source.values, dem_crs, dem_vertical))
    stored = None
    if INPUT_STORED in ctx.request.inputs:
        with open(ctx.input_path(INPUT_STORED), "rb") as stream:
            stored = np.load(stream, allow_pickle=False)
    ctx.progress(0.3, "Validando los sondeos…")
    try:
        report = validate(dset, thresholds, surface=surface, work_window=window,
                          stored_geom_xyz=stored)
    except (ValueError, TypeError) as error:
        raise request.invalid(str(error)) from None
    rows = issue_rows(report)
    found = _tables(ctx, crs, [("dh_validation_issue", LAYOUTS["dh_validation_issue"], rows)],
                    0.5, 0.95)
    write_json(ctx, OUT_REPORT, {
        "notes": [{"code": note.code, "hole": note.hole, "hole_name": note.hole_name,
                   "message": note.message("es")} for note in report.notes],
        "collar_dem_dz": None if report.collar_dem_dz is None else report.collar_dem_dz,
    })
    levels = [str(issue.level) for issue in report.issues]
    summary = {
        "issues": len(rows),
        "errors": levels.count(str(Level.ERROR)),
        "warnings": levels.count(str(Level.WARNING)),
        "excluded_holes": int(report.excluded().holes.sum()),
        "notes": len(report.notes),
        "outputs": {**found, OUT_REPORT.role: {"file": OUT_REPORT.relative}},
    }
    finish(ctx, [table_output("dh_validation_issue"), OUT_REPORT])
    return summary


# --- dh_desurvey ---------------------------------------------------------------------------------


def trace_rows(dset: DrillholeSet, traces: Any, step_m: float, hashes: Sequence[str],
               srs: int) -> list[tuple[Any, ...]]:
    """Las filas de ``dh_trace`` (las de ``schema.insert_rows``) de los sondeos con traza: la
    polilínea densificada cada ``step_m`` m como ``LINESTRING`` con Z en ``srs``, el sondeo
    por su id (``fid`` = posición + 1), el método, la longitud (la profundidad del último
    nodo), el fondo y la huella de la desviación de su boca (``hashes``)."""
    from ..core.gpkg.wkb import encode_geometry
    from .desurvey import polylines

    if len(hashes) != len(dset.collars):
        raise ValueError(f"hay {len(hashes)} huellas de la desviación y {len(dset.collars)} "
                         "bocas")
    offsets, xyz = polylines(traces, None, step_m)
    rows = []
    for hole in np.flatnonzero(traces.computed).tolist():
        last = int(traces.hole_start[hole + 1]) - 1
        end = traces.xyz[last]
        rows.append((encode_geometry("LINESTRING", xyz[offsets[hole]:offsets[hole + 1]], srs,
                                     True),
                     hole + 1, str(traces.method), float(traces.md[last]), float(end[0]),
                     float(end[1]), float(end[2]), hashes[hole]))
    return rows


def _chosen_holes(request: JobParams, count: int) -> np.ndarray:
    """``holes`` de ``dh_desurvey`` (T28) y de ``dh_view_arrays`` (T29): la máscara de las
    bocas cuyas trazas se calculan o se dibujan (sus posiciones en la base, sin repetir); sin
    ``holes``, todas."""
    chosen = np.zeros(count, dtype=np.bool_)
    holes = request.values.get("holes")
    if holes is None:
        chosen[:] = True
        return chosen
    if not isinstance(holes, list) or any(
            isinstance(hole, bool) or not isinstance(hole, int) or not 0 <= hole < count
            for hole in holes) or len(set(holes)) != len(holes):
        raise request.invalid(f"«holes» son posiciones distintas de las {count} bocas de la "
                              f"base, no {holes!r}")
    chosen[holes] = True
    return chosen


def _kept_rows(ctx: _Context, request: JobParams, chosen: np.ndarray) -> list[tuple[Any, ...]]:
    """Las trazas que llegan hechas (``kept``, filas de ``dh_trace``; T28), de sondeos de la
    base que no se calculan."""
    arrays = input_arrays(ctx, INPUT_KEPT)
    if arrays is None:
        return []
    try:
        rows = list(TableRows(LAYOUTS["dh_trace"], arrays))
    except (ValueError, TypeError) as error:
        raise request.invalid(f"las trazas de «{INPUT_KEPT}» no valen: {error}") from None
    for row in rows:
        hole = row[1] - 1
        if not 0 <= hole < len(chosen) or chosen[hole]:
            raise request.invalid(f"la traza conservada del sondeo {row[1]} no es de una boca "
                                  "de la base que no se calcula")
    return rows


@job_function
def run_desurvey(ctx: _Context) -> dict[str, Any]:
    """``dh_desurvey``: las trazas de la base (RF-005-20) por el método de la petición, sin
    los sondeos con errores de alcance S (``validate.hole_exclusions``; RF-005-17), en
    ``dh_trace.npz`` con su hash: cada una con la huella de la desviación de su boca
    (``in/survey_sha256``), la que usa ``drillholes.store.stale_holes`` (RF-005-22). Con
    ``holes`` (T28, «solo las obsoletas»), solo las de esas bocas; las de las demás llegan
    hechas en ``kept`` y pasan tal cual: la tabla entera, por su sondeo."""
    from .desurvey import Method, desurvey
    from .validate import hole_exclusions

    request = JobParams(ctx)
    crs, vertical = request.crs(), request.vertical()
    method = request.text("method", str(Method.MINIMUM_CURVATURE))
    if method not in tuple(str(item) for item in Method):
        raise request.invalid(f"método de cálculo desconocido «{method}»")
    tolerance = request.number("depth_tolerance_m")
    step = request.number("trace_step_m")
    ctx.progress(0.0, READING_TEXT)
    dset = _base(ctx, request, crs, vertical, 0.0, 0.2)
    if INPUT_HASHES not in ctx.request.inputs:
        raise request.invalid(f"falta la entrada «{INPUT_HASHES}»")
    with open(ctx.input_path(INPUT_HASHES), "rb") as stream:
        raw = np.load(stream, allow_pickle=False)
    hashes = [value.decode("ascii") for value in raw.tolist()] if raw.dtype.kind == "S" else []
    if len(hashes) != len(dset.collars):
        raise request.invalid(f"«{INPUT_HASHES}» tiene {len(hashes)} huellas y la base "
                              f"{len(dset.collars)} bocas")
    chosen = _chosen_holes(request, len(dset.collars))
    kept = _kept_rows(ctx, request, chosen)
    ctx.progress(0.2, "Calculando las trazas…")
    excluded = hole_exclusions(dset, depth_tolerance_m=tolerance)
    # Todas las calculables, como sin «holes»: la suma acumulada de los desplazamientos es
    # de todos los sondeos (desurvey), y así cada traza calculada tiene los mismos bits.
    traces = desurvey(dset, method, holes=~excluded)
    ctx.progress(0.4, WRITING_TEXT)
    try:
        computed = [row for row in trace_rows(dset, traces, step, hashes, crs.epsg)
                    if chosen[row[1] - 1]]
    except ValueError as error:
        raise request.invalid(str(error)) from None
    rows = sorted([*computed, *kept], key=lambda row: row[1])
    found = _tables(ctx, crs, [("dh_trace", LAYOUTS["dh_trace"], rows)], 0.5, 0.99)
    names = dset.collars.name.tolist()
    summary = {
        "method": method,
        "traces": len(rows),
        "computed": len(computed),
        "kept": len(kept),
        "excluded": [names[hole] for hole in np.flatnonzero(chosen & excluded).tolist()],
        "warnings": [plain(warning) for warning in traces.warnings if chosen[warning.hole]],
        "outputs": found,
    }
    finish(ctx, [table_output("dh_trace")])
    return summary


# --- dh_view_arrays ------------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class ViewArrays:
    """Lo que dibuja la vista de los sondeos (RF-005-23 a RF-005-25): las curvas de la
    litología de un esquema y su leyenda, las barras de un elemento y su leyenda (y las
    filas que no se dibujan por su unidad) y las etiquetas, todo ABSOLUTO en float64 (la
    vista resta el GeoOrigin)."""

    curves: Any | None
    lithology_legend: tuple[Any, ...]
    bars: Any | None
    grade_legend: Any | None
    labels: tuple[Any, ...]


def write_view(path: Path | str, view: ViewArrays) -> None:
    """``view`` en el npz ``path``: las curvas y las barras por sus arrays
    (``drillholes.arrays.dataclass_arrays``) y las leyendas y las etiquetas en JSON (los
    números, con todos sus decimales)."""
    arrays: dict[str, np.ndarray] = {}
    if view.curves is not None:
        arrays.update(dataclass_arrays("curves", view.curves))
    if view.bars is not None:
        arrays.update(dataclass_arrays("bars", view.bars))
    meta = {
        "lithology_legend": [plain(entry) for entry in view.lithology_legend],
        "grade_legend": None if view.grade_legend is None else plain(view.grade_legend),
        "labels": [plain(label) for label in view.labels],
    }
    arrays["meta"] = np.frombuffer(json.dumps(meta, ensure_ascii=False, allow_nan=False)
                                   .encode("utf-8"), dtype=np.uint8).copy()
    save_npz(path, arrays)


def read_view(path: Path | str) -> ViewArrays:
    """La vista de :func:`write_view` (los arrays, bit a bit)."""
    from .view_data import BarArrays, CurveArrays, GradeLegend, Label, LegendEntry

    arrays = load_npz(path)
    meta = json.loads(arrays["meta"].tobytes().decode("utf-8"))
    grade = meta["grade_legend"]
    return ViewArrays(
        curves=(dataclass_of(arrays, "curves", CurveArrays)
                if "curves_curve_sizes" in arrays else None),
        lithology_legend=tuple(LegendEntry(**entry) for entry in meta["lithology_legend"]),
        bars=dataclass_of(arrays, "bars", BarArrays) if "bars_faces" in arrays else None,
        grade_legend=None if grade is None else GradeLegend(
            grade["unit"], tuple(grade["breaks"]), tuple(grade["colors"]),
            grade["below_dl_color"]),
        labels=tuple(Label(item["hole"], item["text"], tuple(item["xyz"]), item["bottom"])
                     for item in meta["labels"]),
    )


def _exclusions(request: JobParams, holes: np.ndarray) -> Any:
    """Lo que no se dibuja: los sondeos con errores de alcance S y lo de alcance T y R que da
    la petición (``excluded``: ``tables`` [[sondeo, tabla, esquema o elemento]] y ``records``
    [[tabla, fila]], los de la última validación)."""
    from .validate import Exclusions

    given = request.mapping("excluded", {})
    try:
        tables = frozenset((int(hole), str(table), None if key is None else str(key))
                           for hole, table, key in given.get("tables", []))
        records = frozenset((str(table), int(row)) for table, row in given.get("records", []))
    except (ValueError, TypeError) as error:
        raise request.invalid(f"«excluded» no vale: {error}") from None
    return Exclusions(holes, tables, records)


@job_function
def run_view_arrays(ctx: _Context) -> dict[str, Any]:
    """``dh_view_arrays``: los arrays de la vista de la base (``drillholes.view_data``;
    RF-005-23 a RF-005-25) con las trazas del método de la petición (sin los sondeos con
    errores de alcance S): las curvas de la litología del esquema ``log_set`` y su leyenda,
    las barras del elemento ``element`` con la leyenda ``legend`` (o la de
    ``default_grade_legend``) y las etiquetas, en ``view.npz``. Con ``holes`` (T29: las
    posiciones de las bocas con traza en el proyecto, «cada sondeo calculado»), solo se
    dibujan esas; las trazas son las de todas las calculables, como en ``dh_desurvey``."""
    from .desurvey import Method, desurvey
    from .validate import hole_exclusions
    from .view_data import (
        GradeLegend,
        default_grade_legend,
        grade_bars,
        grade_values,
        labels,
        lithology_curves,
        lithology_legend,
    )

    request = JobParams(ctx)
    crs, vertical = request.crs(), request.vertical()
    method = request.text("method", str(Method.MINIMUM_CURVATURE))
    if method not in tuple(str(item) for item in Method):
        raise request.invalid(f"método de cálculo desconocido «{method}»")
    tolerance = request.number("depth_tolerance_m")
    step = request.number("max_step_m")
    log_set = request.optional_text("log_set")
    element = request.optional_text("element")
    ctx.progress(0.0, READING_TEXT)
    dset = _base(ctx, request, crs, vertical, 0.0, 0.2)
    chosen = _chosen_holes(request, len(dset.collars))
    holes = hole_exclusions(dset, depth_tolerance_m=tolerance)
    excluded = _exclusions(request, holes | ~chosen)
    traces = desurvey(dset, method, holes=~holes)
    ctx.progress(0.3, "Calculando la vista…")
    curves, legend = None, ()
    if log_set is not None:
        curves = lithology_curves(dset, traces, log_set, step, excluded=excluded)
        legend = lithology_legend(dset, log_set)
    ctx.check_cancelled()
    bars, grade = None, None
    if element is not None:
        given = request.values.get("legend")
        if given is None:
            unit = request.text("unit")
            grade = default_grade_legend(grade_values(dset, element, unit, excluded=excluded),
                                         unit)
        else:
            grade = request.parsed("legend", lambda value: GradeLegend(
                value["unit"], tuple(value["breaks"]), tuple(value["colors"]),
                value.get("below_dl_color", "#C8C8C8")))
        bars = grade_bars(dset, traces, element, grade, request.number("offset_m"),
                          request.number("width_m"), max_step_m=step, excluded=excluded)
    ctx.progress(0.8, WRITING_TEXT)
    found = labels(dset, traces, request.boolean("labels_at_end"))
    view = ViewArrays(curves, tuple(legend), bars, grade, tuple(found))
    write_view(ctx.output_path(OUT_VIEW.file), view)
    summary = {
        "curves": 0 if curves is None else len(curves.curve_sizes),
        "faces": 0 if bars is None else len(bars.faces),
        "labels": len(found),
        "outputs": {OUT_VIEW.role: {"file": OUT_VIEW.relative}},
    }
    finish(ctx, (OUT_VIEW,))
    return summary


# --- Los tipos de trabajo ------------------------------------------------------------------

_LABELS: Mapping[str, str] = MappingProxyType({
    IMPORT_TABULAR: "Read a drillhole table",
    IMPORT_RECMIN: "Read a RecMin database",
    IMPORT_APPLY: "Prepare a drillhole import",
    BUILD_BASE: "Build the drillhole database",
    VALIDATE: "Validate the drillholes",
    DESURVEY: "Compute the drillhole traces",
    VIEW_ARRAYS: "View arrays of the drillholes",
})
"""El nombre visible (``msgid``) de cada tipo; su español, en ``core/i18n/messages.toml``."""

WORKER_INFOS: tuple[WorkerInfo, ...] = (
    WorkerInfo(IMPORT_TABULAR, _LABELS[IMPORT_TABULAR], policy="subprocess"),
    WorkerInfo(IMPORT_RECMIN, _LABELS[IMPORT_RECMIN], policy="subprocess"),
    WorkerInfo(IMPORT_APPLY, _LABELS[IMPORT_APPLY], estimate_s=_count_estimate(APPLY_ROW_S),
               run=run_import_apply),
    WorkerInfo(BUILD_BASE, _LABELS[BUILD_BASE], estimate_s=_count_estimate(BUILD_ROW_S),
               run=run_build_base),
    WorkerInfo(VALIDATE, _LABELS[VALIDATE], estimate_s=_count_estimate(VALIDATE_ROW_S),
               run=run_validate),
    WorkerInfo(DESURVEY, _LABELS[DESURVEY], estimate_s=_count_estimate(DESURVEY_HOLE_S),
               run=run_desurvey),
    WorkerInfo(VIEW_ARRAYS, _LABELS[VIEW_ARRAYS], estimate_s=_count_estimate(VIEW_ROW_S),
               run=run_view_arrays),
)
"""Los tipos de trabajo de la 005 (plan §5.6.7), para ``jobs.catalog.register_worker`` desde
``bl/ops/dh.py``: entorno ``blender``; las dos lecturas, siempre en proceso aparte (su función,
en ``interop.dh_jobs``); los demás, automáticos, con su estimación por ``count`` (filas o
sondeos de la petición)."""

WORKER_INFOS_BY_NAME: Mapping[str, WorkerInfo] = MappingProxyType(
    {info.name: info for info in WORKER_INFOS})
"""Los tipos de trabajo de la 005 por nombre (solo lectura)."""

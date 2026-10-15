# SPDX-License-Identifier: GPL-3.0-or-later
"""Los trabajos que leen una fuente de sondeos (spec 005, T23; RF-005-03 a RF-005-10,
RF-005-12 a RF-005-15; plan 005 §5.3.3, §5.6.5 y §5.6.7; ADR-0018).

``dh_import_tabular`` y ``dh_import_recmin`` leen formatos ajenos (un CSV o una hoja de un
XLSX; una base de RecMin), que es cosa de ``interop``: ``drillholes`` no lo importa (ARQ-07).
Sus tipos de trabajo están en ``drillholes.jobs`` (``WORKER_INFOS``, siempre en proceso
aparte) y sus funciones aquí, con lo común de los trabajos de la 005 (la copia verificada de
la fuente, el hash de contenido con su lector, la limpieza de ``out/`` si se cancela o falla y
los fallos explicados). Sus envoltorios son ``workers/dh_import_tabular.py`` y
``workers/dh_import_recmin.py``. Véase ``drillholes.jobs`` para sus parámetros y sus
resultados.

Cada lectura deja lo leído **en lo declarado** (el CRS, el datum y los convenios de la fuente,
sin transformar: lo transforma ``dh_build_base``) con las columnas del modelo de
``drillholes.model`` (``drillholes.arrays.tables_arrays``, sin *pickle*), su informe
(RF-005-12: recuentos, rechazos con su motivo, avisos), los códigos que no están en los
catálogos del proyecto (RF-005-10) y los sondeos que ya están en la base (RF-005-11; T46: por
tabla, los que ya tienen registros en la que trae la fuente, ``existing_tables``), y el
``ContentDigest`` de la fuente con su lector de ``interop.dh_content`` (el mismo que da
``core_content_hash``). La fuente no se toca: se lee su copia de ``in/`` (RF-005-03).

Python puro y numpy (ADR-0004).
"""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..core.content.encoder import NORMALIZER
from ..core.georef import CrsRef, VerticalRef
from ..drillholes.arrays import save_npz, tables_arrays
from ..drillholes.jobs import (
    DONE_TEXT,
    MDB_FOLDER,
    OUT_RAW_ROLE,
    OUT_REPORT,
    OUT_SOURCE,
    READING_TEXT,
    WRITING_TEXT,
    JobParams,
    cancelled_probe,
    copy_source,
    finish,
    job_function,
    source_digest,
    span,
    write_json,
)
from ..drillholes.model import DrillholeSet, SourceDeclaration
from ..gis.jobs import digest_json, plain
from ..jobs.worker_api import JobCancelled
from . import dh_content

__all__ = ["run_import_recmin", "run_import_tabular"]

TABULAR_READERS = (dh_content.DH_CSV, dh_content.DH_XLSX)
"""Los lectores de ``dh_import_tabular``."""
NEEDS_CONFIRMATION = "dh.recmin_schema_unknown"
"""El código de lo que hay que confirmar antes de importar una base de RecMin (RF-005-15)."""


def _container(decl: SourceDeclaration, request: JobParams, **tables: Any) -> DrillholeSet:
    """Lo leído en un ``DrillholeSet`` para listar sus códigos nuevos y sus sondeos que ya
    están: en el CRS y el datum declarados o, en una tabla sin coordenadas, los del proyecto
    de la petición (no se calcula nada con ellos)."""
    crs: CrsRef = decl.crs or request.crs()
    vertical: VerticalRef = decl.vertical or request.vertical()
    return DrillholeSet(crs=crs, vertical=vertical, **tables)


def _source_summary(reader_id: str, digest: Any, prints: Mapping[str, Any],
                    declarations: Mapping[str, Any], settings: Mapping[str, Any]
                    ) -> dict[str, Any]:
    return {"reader": reader_id, "digest": digest_json(digest), "files": {"main": dict(prints)},
            "declarations": dict(declarations), "settings": plain(settings)}


def _existing(request: JobParams, found: DrillholeSet) -> dict[str, list[str]]:
    """Por tabla de lo leído (``found``), sus sondeos que ya tienen registros en esa tabla del
    proyecto (``project_holes`` de la petición; RF-005-11, T46): los que se preguntan."""
    from .base import existing_tables

    try:
        return {table: list(names) for table, names in
                existing_tables(found, request.holes("project_holes")).items()}
    except (ValueError, TypeError) as error:
        raise request.invalid(str(error)) from None


def _declarations(request: JobParams, reader_id: str, decl: SourceDeclaration,
                  **entry: Any) -> dict[str, Any]:
    from ..drillholes.provenance import source_declarations

    try:
        return source_declarations(reader_id, decl, **entry)
    except (ValueError, TypeError) as error:
        raise request.invalid(str(error)) from None


@job_function
def run_import_tabular(ctx: Any) -> dict[str, Any]:
    """``dh_import_tabular``: una tabla de sondeos de un papel en un CSV o una hoja de un XLSX
    (RF-005-05, RF-005-06, RF-005-09): la copia verificada de la fuente, su
    ``ContentDigest`` (``io.dh_csv@1`` o ``io.dh_xlsx@1``) y lo leído con la correspondencia
    de columnas y la declaración de la petición (``interop.drillholes_tabular.read_role``,
    la lectura del importador) en ``source.npz``, con su informe en ``report.json``. Sin las
    declaraciones que hacen falta, ``dh.declaration_missing`` (RF-005-07)."""
    from ..drillholes.provenance import TABLE_ROLES, input_kind
    from .base import holes_of, new_codes, registrations
    from .csv_tables import read_table
    from .drillholes_tabular import read_role
    from .xlsx_tables import read_sheet

    request = JobParams(ctx)
    readers = {reader.id: reader for reader in TABULAR_READERS}
    reader = readers.get(request.text("reader", ""))
    if reader is None:
        raise request.invalid(f"el lector es uno de {list(readers)}, no "
                              f"{request.values.get('reader')!r}")
    role = request.text("role", "")
    if role not in TABLE_ROLES:
        raise request.invalid(f"el papel de la tabla es uno de {list(TABLE_ROLES)}, no "
                              f"{role!r}")
    mapping = request.mapping("mapping")
    if not all(isinstance(key, str) and isinstance(value, str)
               for key, value in mapping.items()):
        raise request.invalid(f"«mapping» es {{campo: columna}}, no {mapping!r}")
    decl = request.declaration()
    settings = request.mapping("settings", {})
    request.holes("project_holes")  # que valga antes de copiar nada
    catalogs = request.catalogs()
    declarations = _declarations(request, reader.id, decl, role=role, mapping=mapping)
    kind = input_kind(reader.id, role)
    ctx.progress(0.0)
    copy, prints = copy_source(ctx, request, low=0.0, high=0.1)
    digest = source_digest(ctx, reader, kind, {"main": copy}, declarations, settings, 0.1, 0.6)
    ctx.progress(0.6, READING_TEXT)
    try:
        if reader is dh_content.DH_CSV:
            table = read_table(copy, encoding=settings["encoding"],
                               separator=settings["separator"],
                               header_row=settings["header_row"])
        else:
            table = read_sheet(copy, settings["sheet"], header_row=settings["header_row"],
                               decimal_mark=settings["decimal"],
                               date_format=settings.get("date_format"))
    except KeyError as error:
        raise request.invalid(f"falta el ajuste de lectura {error}") from None
    ctx.check_cancelled()
    rows = read_role(role, table, mapping, decl)
    ctx.progress(0.8, WRITING_TEXT)
    parts = {"collars": rows.collars, "surveys": rows.surveys, "lithology": rows.lithology,
             "assays": rows.assays}
    found = _container(decl, request, **parts, catalogs=rows.catalogs)
    save_npz(ctx.output_path(OUT_SOURCE.file), tables_arrays(parts, rows.catalogs))
    existing = _existing(request, found)
    report = {
        "role": role,
        "counts": rows.counts.as_dict(),
        "rejected": [list(item) for item in rows.rejected],
        "duplicate_holes": [list(group) for group in rows.duplicate_holes],
        "warnings": [],
        "new_codes": {kind: list(codes) for kind, codes in new_codes(found, catalogs).items()},
        "register_codes": registrations(found, catalogs),
        "existing_holes": list(holes_of(existing)),
        "existing_tables": existing,
    }
    write_json(ctx, OUT_REPORT, report)
    summary = {
        "source": _source_summary(reader.id, digest, prints, declarations, settings),
        "role": role,
        "counts": report["counts"],
        "rejected": len(rows.rejected),
        "new_codes": report["new_codes"],
        "register_codes": report["register_codes"],
        "existing_holes": report["existing_holes"],
        "existing_tables": existing,
        "outputs": {OUT_SOURCE.role: {"file": OUT_SOURCE.relative},
                    OUT_REPORT.role: {"file": OUT_REPORT.relative}},
    }
    finish(ctx, (OUT_SOURCE, OUT_REPORT))
    return summary


def _extract(ctx: Any, copy: Path, out_dir: Path, low: float, high: float) -> list[Any]:
    """Las tablas de la copia de la base con el extractor de ``interop.dh_content`` (el de
    ``adapters.registry`` o el que se le dio), con su avance en [``low``, ``high``] y la
    cancelación del trabajo: el extractor para su ``powershell.exe`` hijo en ≤ 2 s."""
    from .ports import MdbCancelled

    progress = span(ctx, low, high)
    try:
        return list(dh_content.mdb_extractor().extract(copy, out_dir, progress,
                                                       cancelled_probe(ctx)))
    except MdbCancelled:
        raise JobCancelled("Lectura de la base de RecMin cancelada") from None


@job_function
def run_import_recmin(ctx: Any) -> dict[str, Any]:
    """``dh_import_recmin``: una base de RecMin (RF-005-13 a RF-005-15): la copia verificada
    de la base en ``in/`` (el motor de Access deja su bloqueo junto a ella, no junto a la
    fuente), sus tablas con el extractor (el crudo, en ``out/mdb``; sin motor,
    ``io.mdb_engine_missing``), su versión de esquema (otra que 11 o 12 sin
    ``accept_schema``: ``needs_confirmation`` y ningún resultado), su ``ContentDigest`` (el de
    ``io.recmin_mdb@1`` sobre las mismas tablas, sin extraerla otra vez) y lo leído
    (``interop.recmin.drillholes.read_drillholes``) en ``source.npz``, con su informe (que
    dice además, por tabla de RecMin, los registros de cada sondeo que ya está en el proyecto,
    ``hole_rows``: los que quita conservarlo, RF-005-12; y, T46, los de las tablas en las que
    ya tenía registros en el proyecto, ``existing_rows``: los que sustituye importarlo)."""
    from ..drillholes.provenance import RECMIN_MDB
    from .base import holes_of, registrations
    from .recmin.drillholes import hole_rows, read_drillholes
    from .recmin.schema import schema_version, version_warning

    request = JobParams(ctx)
    decl = request.declaration()
    settings = request.mapping("settings", {})
    accept = request.boolean("accept_schema")
    request.holes("project_holes")  # que valga antes de copiar nada
    catalogs = request.catalogs()
    declarations = _declarations(request, RECMIN_MDB, decl)
    reader = dh_content.RECMIN_MDB
    ctx.progress(0.0)
    copy, prints = copy_source(ctx, request, low=0.0, high=0.05)
    out_dir = ctx.job_dir.outputs_dir / MDB_FOLDER
    tables = _extract(ctx, copy, out_dir, 0.05, 0.6)
    version = schema_version(tables)
    warning = version_warning(version)
    if warning is not None and not accept:  # RF-005-15: nada sin la confirmación
        shutil.rmtree(out_dir, ignore_errors=True)
        ctx.progress(1.0, DONE_TEXT)
        return {"needs_confirmation": {"code": NEEDS_CONFIRMATION, "version": version,
                                       "text": warning},
                "source": {"reader": reader.id, "files": {"main": dict(prints)}},
                "outputs": {}}
    hashed = reader.request("drillholes", declarations, {"main": copy}, settings,
                            normalizer=NORMALIZER)
    progress = span(ctx, 0.6, 0.8, "Calculando el hash de contenido de la base…")
    try:
        for done in dh_content.hash_recmin_tables(hashed, tables):
            progress(done)
    except (ValueError, TypeError) as error:  # ajustes o convenciones que no admite
        raise request.invalid(str(error)) from None
    digest = hashed.hasher.digest()
    ctx.progress(0.8, READING_TEXT)
    dset, report = read_drillholes(tables, decl, catalogs, accept_schema=accept)
    ctx.progress(0.9, WRITING_TEXT)
    save_npz(ctx.output_path(OUT_SOURCE.file),
             tables_arrays({name: getattr(dset, name) for name in
                            ("collars", "surveys", "lithology", "assays", "zones",
                             "structures")}, dset.catalogs))
    tables_with = _existing(request, dset)
    existing = list(holes_of(tables_with))
    found = {
        "schema_version": version,
        "counts": {table: counts.as_dict() for table, counts in report.per_table.items()},
        "rejected": [list(item) for item in report.rejected],
        "duplicate_holes": [list(group) for group in report.duplicate_holes],
        "warnings": list(report.warnings),
        "new_codes": {kind: list(codes) for kind, codes in report.unknown_codes.items()},
        "register_codes": registrations(dset, catalogs),
        "existing_holes": existing,
        "existing_tables": tables_with,
        "hole_rows": hole_rows(dset, existing, report.per_table),
        "existing_rows": hole_rows(dset, tables_with, report.per_table),
    }
    write_json(ctx, OUT_REPORT, found)
    raw = sorted(path for path in out_dir.rglob("*") if path.is_file()) if out_dir.exists() \
        else []
    summary = {
        "source": _source_summary(reader.id, digest, prints, declarations, settings),
        "schema_version": version,
        "counts": found["counts"],
        "rejected": len(report.rejected),
        "warnings": found["warnings"],
        "new_codes": found["new_codes"],
        "register_codes": found["register_codes"],
        "existing_holes": found["existing_holes"],
        "existing_tables": tables_with,
        "outputs": {OUT_SOURCE.role: {"file": OUT_SOURCE.relative},
                    OUT_REPORT.role: {"file": OUT_REPORT.relative},
                    OUT_RAW_ROLE: {"files": [path.relative_to(ctx.job_dir.path).as_posix()
                                             for path in raw]}},
    }
    finish(ctx, (OUT_SOURCE, OUT_REPORT))
    for path in raw:
        ctx.add_output(path, OUT_RAW_ROLE)
    return summary

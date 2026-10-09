# SPDX-License-Identifier: GPL-3.0-or-later
"""Las bocas de sondeos de un CSV importadas como entrada, para las regresiones de la 008 (spec
008, T41; CE-008-09; RF-008-11, RF-008-52, RF-008-53; plan 008 §7 y §7.1).

La demostración de la procedencia (``tests.support.provenance_demo``) importa el límite de un
GeoPackage con ``core.import_layer``. Este módulo importa los collares sintéticos de
``tests/data/core/provenance/`` (``collares_v1.csv`` a ``collares_v3.csv``) como lo hará un
módulo con los suyos (la 005 con los de RecMin), con su código ``demo``:

- el lector de contenido ``demo.collars_csv@1`` (:data:`COLLARS_CSV`): la tabla del CSV
  («;» de separador y coma decimal, cabecera con los nombres de las columnas, ``sondeo`` como
  texto y las demás como números), con sus filas en su orden;
- la importación ``demo.import_collars`` (no repetible, :func:`import_collars`): registra el CSV
  como entrada de sondeos (``drillholes``) con su CRS declarado (EPSG:25830 y la altura
  ortométrica EPSG:5782; nunca se suponen: los declara quien importa), copia sus filas a una
  tabla propia del proyecto (lo importado, el dato ``demo_collares``, inmutable: cada
  actualización escribe otra tabla, ``demo_collares_2``…) y guarda su original con su huella
  (RF-008-53) desde una copia verificada fuera de la fuente, como la de un trabajo de la 004;
- su importador (``ImporterDef`` del lector, :func:`reimport_collars`): «Actualizar»
  (``core.provenance.importer.reimport_input``) vuelve a importar el CSV desde su fuente como
  una entrada nueva que sustituye a la anterior, con el motivo;
- ``demo.collar_elevation`` (repetible, :func:`mean_elevation`): la cota media de las bocas de
  lo importado vigente → la cifra ``demo.collar_elevation`` (m, CALCULADO); la columna de la
  cota es ``cota`` o, desde ``collares_v3.csv``, ``z``.

Se registra, con sus etiquetas en español, con :func:`registered` mientras la demostración está
registrada (es la que da el código ``demo``). Solo fuera de Blender (usa
``tests.support.package``). La fuente solo se lee (RF-008-14). Datos solo sintéticos: nada de
clientes.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered as contract_registered
from tests.support.provenance_readers import registered as readers_registered

readers = import_geoblender("core.content.readers")
builtin = import_geoblender("core.content.builtin")
contract = import_geoblender("core.provenance.contract")
operations = import_geoblender("core.provenance.operations")
figures = import_geoblender("core.provenance.figures")
inputs = import_geoblender("core.inputs")
input_registry = import_geoblender("core.inputs.registry")
originals = import_geoblender("core.inputs.originals")
model = import_geoblender("core.datasets.model")
gpkg_base = import_geoblender("core.gpkg.base")
hashing = import_geoblender("core.hashing")
numbers = import_geoblender("core.numbers")
i18n = import_geoblender("core.i18n")

IMPORT_COLLARS = "demo.import_collars"
COLLAR_ELEVATION = "demo.collar_elevation"
"""El tipo de operación de la cota media y la clave de su cifra."""
INPUT_NAME = "collares"
"""El nombre lógico de la entrada (el del CSV sin extensión)."""
SOURCE_NAME = "collares.csv"
"""El nombre del CSV en la carpeta del cliente."""
DATASET = "demo_collares"
"""El nombre estable de lo importado (su tabla cambia en cada actualización)."""
IMPORTED_ROLE = "imported"
COLLARS_ROLE = "collars"
"""El papel de lo importado en su importación y en la cota media."""
KIND = "drillholes"
ETRS89: Mapping[str, Any] = {"epsg": 25830}
REDNAP: Mapping[str, Any] = {"epsg": 5782}
"""Los CRS que declara quien importa los collares (horizontal y vertical)."""
SETTINGS: Mapping[str, str] = {"separator": ";", "decimal": ","}
"""Los ajustes de lectura del CSV (ninguno es contenido)."""
TEXT_COLUMNS: tuple[str, ...] = ("sondeo",)
"""Las columnas de texto del CSV; las demás son números."""
ELEVATION_COLUMNS: tuple[str, ...] = ("cota", "z")
"""Los nombres de la columna de la cota que se aceptan, en orden."""
CSV_BYTES_PER_S = 50_000_000
"""Lo que lee el lector por segundo, a la baja (su estimación)."""


def parse_csv(data: bytes, settings: Mapping[str, Any] = SETTINGS) -> tuple[
        tuple[str, ...], list[tuple[Any, ...]]]:
    """La cabecera y las filas de un CSV de collares (UTF-8, una fila por línea), con los
    números ya interpretados («412,53» → 412.53). :class:`ValueError` si una fila no tiene las
    columnas de la cabecera."""
    separator = str(settings["separator"])
    lines = data.decode("utf-8").splitlines()
    if not lines:
        raise ValueError("el CSV de collares está vacío")
    header = tuple(name.strip() for name in lines[0].split(separator))
    rows: list[tuple[Any, ...]] = []
    for number, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        cells = line.split(separator)
        if len(cells) != len(header):
            raise ValueError(f"la línea {number} del CSV tiene {len(cells)} columnas, no "
                             f"{len(header)}")
        rows.append(tuple(
            cell.strip() if name in TEXT_COLUMNS else numbers.parse_decimal(
                cell, obj=f"CSV de collares, línea {number}", field=name)
            for name, cell in zip(header, cells, strict=True)))
    return header, rows


def _column_types(header: Sequence[str]) -> list[tuple[str, str]]:
    return [(name, "text" if name in TEXT_COLUMNS else "float") for name in header]


def read_collars_csv(request: Any) -> Iterator[float]:
    """El generador del lector: la tabla entera del CSV en un paso."""
    header, rows = parse_csv(Path(request.files["main"]).read_bytes(), request.settings)
    request.hasher.rows(_column_types(header), True, rows)
    yield 1.0


COLLARS_CSV = readers.ContentReader(
    "demo.collars_csv", 1, (KIND,), False, False,
    lambda size: size / CSV_BYTES_PER_S, read_collars_csv,
)
"""El lector de contenido de los CSV de collares."""


@dataclass(frozen=True)
class CollarsImport:
    """Una importación de los collares: su operación, la entrada registrada, lo importado y
    lo que dijo el guardado de su original."""

    operation_uid: str
    input: Any
    dataset: Any
    original: Any

    @property
    def uid(self) -> str:
        """El uid de la operación de importación."""
        return self.operation_uid


def _table_name(conn: Any) -> str:
    """La tabla libre para lo importado: ``demo_collares``, ``demo_collares_2``…"""
    number = 1
    while True:
        name = DATASET if number == 1 else f"{DATASET}_{number}"
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (name,)).fetchone() is None:
            return name
        number += 1


def _verified_copy(path: Path, sha256: str, folder: Path) -> Path:
    """Una copia de ``path`` en ``folder`` con la huella ``sha256`` (como la de un trabajo de
    la 004): si la fuente cambió mientras tanto, :class:`ValueError`."""
    copy = folder / path.name
    shutil.copyfile(path, copy)
    if hashing.sha256_file(copy) != sha256:
        raise ValueError(f"«{path.name}» cambió mientras se importaba: no se registra")
    return copy


def import_collars(project: Any, source: str | os.PathLike[str], *, name: str = INPUT_NAME,
                   previous_uid: str | None = None, reason: str | None = None) -> CollarsImport:
    """Importa el CSV de collares ``source`` como la entrada ``name`` (con ``previous_uid`` y
    ``reason``, la que sustituye y por qué): su operación ``demo.import_collars``, la entrada,
    lo importado y su original guardado (véase el módulo)."""
    path = Path(source)
    found = path.stat()
    sha256 = hashing.sha256_file(path)
    with tempfile.TemporaryDirectory(prefix="gb-col-") as work:
        copy = _verified_copy(path, sha256, Path(work))
        declarations = inputs.input_declarations(ETRS89, REDNAP, {})
        request = COLLARS_CSV.request(KIND, declarations, {"main": copy}, dict(SETTINGS))
        spec = inputs.InputSpec(
            name, KIND, "demo", COLLARS_CSV.id,
            files=[input_registry.locate_source(path, project, project.userdata)],
            file_prints=[inputs.SourcePrint(sha256, size=found.st_size,
                                            mtime_ns=found.st_mtime_ns)],
            digest=readers.read_content(COLLARS_CSV, request),
            crs_h=dict(ETRS89), crs_v=dict(REDNAP), settings=dict(SETTINGS))
        header, rows = parse_csv(copy.read_bytes())
        supersedes = None
        if previous_uid is not None:
            with project.read() as conn:
                supersedes = input_registry.get(conn, previous_uid).operation_uid
        with operations.operation(project, IMPORT_COLLARS, settings=dict(SETTINGS),
                                  supersedes=supersedes) as handle, \
                project.write_transaction() as conn:
            if previous_uid is not None:
                input_registry.supersede(conn, project, previous_uid, operation_uid=handle.uid,
                                         reason=reason)
            record = input_registry.register_input(conn, project, spec,
                                                   operation_uid=handle.uid,
                                                   previous_uid=previous_uid, reason=reason)
            table = _table_name(conn)
            gpkg_base.create_attribute_table(
                conn, table,
                [gpkg_base.ColumnDef(column, "TEXT" if column in TEXT_COLUMNS else "DOUBLE")
                 for column in header],
                f"Collares importados ({table})", "Tabla sintética de las pruebas de la 008")
            names = ", ".join(f'"{column}"' for column in header)
            marks = ", ".join("?" for _ in header)
            conn.executemany(f'INSERT INTO "{table}" ({names}) VALUES ({marks})', rows)
            (dataset,) = handle.complete(conn, outputs=[model.DatasetSpec(
                DATASET, "demo", "table", "gpkg", table, reader=builtin.GPKG_LAYER.id,
                role=IMPORTED_ROLE, input_uid=record.uid, immutable=True)])
        stored = list(originals.store_originals_steps(project, record.uid, [copy],
                                                      tabular=True))[-1].result
    return CollarsImport(handle.uid, record, dataset, stored)


def reimport_collars(request: Any) -> CollarsImport:
    """El importador del lector: vuelve a importar la entrada de ``request`` desde su fuente,
    con su nombre, como una entrada nueva que la sustituye con el motivo de ``request``."""
    project = request.project
    with project.read() as conn:
        record = input_registry.get(conn, request.input_uid)
    (main,) = record.files
    path = input_registry.resolve_source(main, project, project.userdata)
    if path is None or not path.is_file():
        raise FileNotFoundError(f"no se encuentra la fuente de «{record.name}»")
    return import_collars(project, path, name=record.name, previous_uid=record.uid,
                          reason=request.reason)


def _elevation(handle: Any) -> None:
    """El cuerpo de ``demo.collar_elevation``: la cota media de las bocas que consume."""
    with handle.project.write_transaction() as conn:
        (item,) = [item for item in handle.inputs if item.role == COLLARS_ROLE]
        table = conn.execute("SELECT locator FROM gb_dataset WHERE uid = ?",
                             (item.uid,)).fetchone()[0]
        columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]
        column = next(name for name in ELEVATION_COLUMNS if name in columns)
        values = [value for (value,) in conn.execute(f'SELECT "{column}" FROM "{table}"')]
        mean = sum(values) / len(values)
        handle.complete(conn, figures=[figures.FigureSpec(COLLAR_ELEVATION, mean, "m")])


def _recompute(request: Any) -> Any:
    with request.operation() as handle:
        _elevation(handle)
    return handle


def mean_elevation(project: Any) -> Any:
    """``demo.collar_elevation`` con lo importado vigente de los collares; su operación."""
    with operations.operation(project, COLLAR_ELEVATION, settings={},
                              inputs=[operations.Use(DATASET, COLLARS_ROLE)]) as handle:
        _elevation(handle)
    return handle


LABELS_ES: Mapping[str, str] = {
    "Demo import collars": "Importar los collares (demostración)",
    "Demo mean collar elevation": "Cota media de los collares (demostración)",
}
"""Las etiquetas de las operaciones y de la cifra (``msgid`` en inglés → español)."""


def declarations() -> tuple[Any, ...]:
    """Lo que se registra: las dos operaciones, la cifra y el importador (se crean con la
    demostración registrada: el código ``demo`` solo vale entonces)."""
    return (
        contract.OperationDef(IMPORT_COLLARS, "1.0", "demo", "Demo import collars", False),
        contract.OperationDef(COLLAR_ELEVATION, "1.0", "demo", "Demo mean collar elevation",
                              True, recompute=_recompute),
        contract.FigureDef(COLLAR_ELEVATION, "m", "Demo mean collar elevation"),
        contract.ImporterDef(COLLARS_CSV.reader_id, reimport_collars),
    )


@contextmanager
def _labels() -> Iterator[None]:
    installed = i18n._STATE.installed  # sin API para quitar: se deja como estaba
    previous = {msgid: installed.get(msgid) for msgid in LABELS_ES}
    i18n.install(LABELS_ES)
    try:
        yield
    finally:
        for msgid, text in previous.items():
            if text is None:
                installed.pop(msgid, None)
            else:
                installed[msgid] = text


@contextmanager
def registered() -> Iterator[None]:
    """Registra el lector, :func:`declarations` y sus etiquetas (con la demostración ya
    registrada) y lo deja todo como estaba al salir."""
    with readers_registered(COLLARS_CSV), contract_registered(*declarations()), _labels():
        yield

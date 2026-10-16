# SPDX-License-Identifier: GPL-3.0-or-later
"""El volumen de referencia D-13 de la spec 008 en un proyecto sintético de esquema 2, las fuentes
grandes de RNF-008-05 y el arnés de RNF-008-11 por lector (T42; plan 008 §7, §7.3 y S-4).

**D-13** (spec 008, §7 «Volumen esperado»): 100 entradas, 300 parámetros con 10 revisiones,
20 000 datos y 10 000 operaciones. :func:`build_d13` lo escribe en un proyecto real
(``create_project``, su sesión y un reloj fijo posterior a las fechas de las filas) por filas,
en una sola transacción, sin pasar por el registro de operaciones (que tardaría minutos), pero
coherente con él: nada está obsoleto, ningún dato ni entrada ha cambiado y la caché
``gb_stale`` está vacía, como en un proyecto al día.

- Operaciones: ``chains`` cadenas iguales (100 de 100 por defecto; 1 de 10 000 para la
  procedencia de RNF-008-03), de los 20 tipos repetibles ``res.t00``…``res.t19`` (1.0). Cada
  una escribe dos datos y consume el primero de la anterior de su cadena; la cabeza de cada
  cadena registró y consume su entrada. La última de cada cadena da la cifra
  :data:`FIGURE_KEY` con el ámbito ``{"chain": n}``.
- Datos: uno de cada :data:`FILE_EVERY` es un fichero de ``rasters/fNN/`` (4 000 en 40
  carpetas); el resto, filas de 160 tablas comunes del proyecto (100 datos por tabla, cada uno
  con su selector), seguidas por sus disparadores de ``last_change``.
- Entradas: 100 documentos fuera del proyecto (en ``sources``, que puede estar en la red), con
  su ancla de ``locate_source``; la mitad con su original guardado en ``originals/``.
- Parámetros: ``res.p000``…``res.p299`` (registrados con :func:`registered`), cada uno con 10
  revisiones en su historial. Las cabezas leen :data:`COMMON_KEY` (cambiarlo deja obsoleto
  todo el grafo) y el de su cadena; las demás, uno de ``res.p101``…``res.p299``.

Para las fuentes grandes: :func:`write_mdt` (rejilla ``.npy`` por bandas), :func:`write_layer`
(capa de polígonos de un GeoPackage) y :func:`write_assays` (tabla de ensayos), con sus
declaraciones y ajustes. :class:`BigHashHarness` es el arnés de RNF-008-11 que reutilizan la 006
(su GeoTIFF) y la 005 (su base de RecMin) con su lector: una clase de pruebas lo hereda y da
``reader`` y ``make_source``. Solo fuera de Blender (el Python de Blender de
``tools/check.py --rendimiento``).
"""

from __future__ import annotations

import datetime as dt
import os
import shutil
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from tests.support.core_fixtures import FakeClock, make_session, make_settings
from tests.support.package import import_geoblender
from tests.unit.core.provenance.test_schema import (
    dataset_change_row,
    dataset_row,
    figure_row,
    file_row,
    history_row,
    input_row,
    io_row,
    op_param_row,
    operation_row,
    parameter_row,
)

create = import_geoblender("core.project.create")
userdata_mod = import_geoblender("core.userdata")
gpkg = import_geoblender("core.gpkg")
base = import_geoblender("core.gpkg.base")
georef = import_geoblender("core.georef")
hashing = import_geoblender("core.hashing")
readers = import_geoblender("core.content.readers")
builtin = import_geoblender("core.content.builtin")
tracking = import_geoblender("core.datasets.tracking")
datasets = import_geoblender("core.datasets")
dataset_model = import_geoblender("core.datasets.model")
inputs = import_geoblender("core.inputs")
params = import_geoblender("core.params")
store_mod = import_geoblender("core.params.store")
contract = import_geoblender("core.provenance.contract")
figures_mod = import_geoblender("core.provenance.figures")
checks = import_geoblender("core.provenance.checks")
encoder = import_geoblender("core.content.encoder")
job_paths = import_geoblender("jobs.paths")
content_hash = import_geoblender("jobs.content_hash")
worker_api = import_geoblender("jobs.worker_api")

# --- D-13 ------------------------------------------------------------------------------------

INPUTS = 100
PARAMETERS = 300
REVISIONS = 10
OPERATIONS = 10_000
DATASETS = 20_000
CHAINS = 100
OUTPUTS = DATASETS // OPERATIONS  # datos que escribe cada operación
FILE_EVERY = 5  # uno de cada 5 datos es un fichero de rasters/: 4 000
FILES_PER_FOLDER = 100  # 40 carpetas rasters/fNN/
ROWS_PER_TABLE = 100  # datos (filas con su selector) por tabla común: 160 tablas
ORIGINAL_EVERY = 2  # la mitad de las entradas tiene su original guardado
OP_TYPES = 20
MODULE = "res"
COMMON_KEY = "res.p000"
FIRST_INNER_PARAMETER = 101  # las operaciones de dentro de las cadenas leen res.p101…res.p299
FIGURE_KEY = "res.d13_total"
FILE_READER = "test.d13_bytes@1"  # nunca se lee: los ficheros no cambian
SESSION = make_session()  # la sesión de las filas (test_schema.SESSION_UID)
CLOCK_START = dt.datetime(2026, 10, 9, 10, 0, tzinfo=dt.UTC)  # después de test_schema.NOW
SHA = hashing.sha256_bytes(b"contenido de D-13")


def parameter_key(index: int) -> str:
    """La clave del parámetro ``index`` (0…299): ``res.p042``."""
    return f"{MODULE}.p{index:03d}"


def op_type(index: int) -> str:
    """El tipo de la operación ``index``: uno de ``res.t00``…``res.t19``."""
    return f"{MODULE}.t{index % OP_TYPES:02d}"


def _uid(kind: int, number: int) -> str:
    return f"00000000-0000-4000-{0x8000 + kind:04x}-{number:012x}"


def _never_recomputed(request: Any) -> Any:  # pragma: no cover - el volumen no se recalcula
    raise AssertionError("el volumen de D-13 no se recalcula")


DEFINITIONS: tuple[Any, ...] = tuple(
    params.ParamDef(parameter_key(index), "float", "m", 1.0 + index, 0.0, 1e6,
                    ("RF-008-60",), f"Parámetro {index} de D-13")
    for index in range(PARAMETERS)
)
OPERATION_DEFS: tuple[Any, ...] = tuple(
    contract.OperationDef(op_type(index), "1.0", MODULE, f"D-13 step {index:02d}", True,
                          recompute=_never_recomputed)
    for index in range(OP_TYPES)
)
FIGURE_DEF = contract.FigureDef(FIGURE_KEY, "t", "D-13 total")

_DEPTH = [0]


@contextmanager
def registered() -> Iterator[None]:
    """Registra lo que el volumen necesita (las 300 definiciones, los 20 tipos, la cifra, las
    operaciones y los lectores de ``core`` que falten) y lo quita al salir. Se puede anidar: lo
    registra la primera entrada y lo quita la última."""
    if _DEPTH[0]:
        _DEPTH[0] += 1
        try:
            yield
        finally:
            _DEPTH[0] -= 1
        return
    with ExitStack() as stack:
        params.register_definitions(DEFINITIONS)
        stack.callback(params.unregister_definitions, MODULE)
        for defn in OPERATION_DEFS:
            contract.register_operation(defn)
            stack.callback(contract.unregister_operation, defn.op_type)
        contract.register_figure(FIGURE_DEF)
        stack.callback(contract.unregister_figure, FIGURE_KEY)
        for operation in contract.CORE_OPERATIONS:
            if operation.op_type not in contract.OPERATIONS:
                contract.register_operation(operation)
                stack.callback(contract.unregister_operation, operation.op_type)
        for reader in builtin.CONTENT_READERS:
            if reader.id not in readers.READERS:
                readers.register_reader(reader)
                stack.callback(readers.unregister_reader, reader.id)
        _DEPTH[0] = 1
        try:
            yield
        finally:
            _DEPTH[0] = 0


@dataclass
class D13Project:
    """Un proyecto abierto en escritura con el volumen de D-13 (o solo sus entradas), y lo que
    hace falta para medirlo. :meth:`close` lo cierra y borra sus datos de usuario temporales
    (la carpeta del proyecto es de quien lo construyó)."""

    project: Any
    userdata: Any
    sources: tuple[Path, ...]
    files: tuple[Path, ...]
    operations: tuple[str, ...]
    datasets: tuple[str, ...]
    inputs: tuple[str, ...]
    figures: tuple[str, ...]
    chains: int
    cleanup: ExitStack = field(repr=False)

    @property
    def root(self) -> Path:
        return Path(self.project.root)

    def leaf(self, chain: int) -> str:
        """El nombre del segundo dato de la última operación de la cadena ``chain``, que nadie
        consume."""
        length = len(self.operations) // self.chains
        last = chain * length + length - 1
        return self.datasets[OUTPUTS * last + 1]

    def close(self) -> None:
        try:
            if not self.project.closed:
                self.project.close()
        finally:
            self.cleanup.close()


def _insert(conn: Any, table: str, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        return
    columns = list(rows[0])
    conn.executemany(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES "
        f"({', '.join('?' for _ in columns)})",
        [tuple(row[column] for column in columns) for row in rows],
    )


def _json(value: Any) -> str:
    return hashing.canonical_json(value).decode("utf-8")


def _start(parent: Path, sources: Path, clock: Any | None) -> tuple[Any, Any, ExitStack]:
    """Crea el proyecto en ``parent`` (con sus datos de usuario en un temporal local) y la
    carpeta de las fuentes."""
    parent.mkdir(parents=True, exist_ok=True)
    sources.mkdir(parents=True, exist_ok=True)
    cleanup = ExitStack()
    try:
        local = Path(cleanup.enter_context(tempfile.TemporaryDirectory(
            prefix="gb-008-u-", ignore_cleanup_errors=True)))
        userdata = userdata_mod.UserData(local)
        project = create.create_project(parent, make_settings(), SESSION, userdata,
                                        FakeClock(CLOCK_START) if clock is None else clock).project
    except BaseException:
        cleanup.close()
        raise
    return project, userdata, cleanup


def _write_sources(sources: Path) -> list[Path]:
    found = []
    for index in range(INPUTS):
        path = sources / f"fuente_{index:03d}.csv"
        lines = [f"sondeo;x;y;z;fuente {index}"]
        lines += [f"S-{index:03d}-{row:02d};715{row:03d},5;4378{row:03d},25;6{row:02d},5"
                  for row in range(4 + index % 5)]
        path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
        found.append(path)
    return found


def _operation(index: int) -> dict[str, Any]:
    settings = _json({"paso": index})
    return operation_row(
        uid=_uid(1, index), op_type=op_type(index), module=MODULE, repeatable=1,
        settings=settings, settings_sha256=hashing.sha256_bytes(settings.encode("utf-8")),
    )


def _inputs(conn: Any, project: Any, userdata: Any, sources: Sequence[Path],
            registrars: Sequence[str]) -> list[str]:
    """Las filas de las 100 entradas (y sus originales, en disco) registradas por las
    operaciones ``registrars`` (la entrada n, por la n-ésima módulo su número)."""
    root = Path(project.root)
    not_applicable = _json({"not_applicable": True})
    settings = _json({"content_keys": [], "values": {}})
    rows, files, uids = [], [], []
    for index, path in enumerate(sources):
        uid = _uid(3, index)
        uids.append(uid)
        stored = index % ORIGINAL_EVERY == 0
        name = f"Entrada_{index:03d}"
        rows.append(input_row(
            uid=uid, name=name, kind="document", module=MODULE, reader="core.document@1",
            layer=None, crs_h=not_applicable, crs_v=not_applicable, settings=settings,
            settings_sha256=hashing.sha256_bytes(settings.encode("utf-8")),
            bytes_sha256=hashing.sha256_bytes(f"bytes {name}".encode()),
            data_sha256=hashing.sha256_bytes(f"datos {name}".encode()),
            content_sha256=hashing.sha256_bytes(f"contenido {name}".encode()),
            operation_uid=registrars[index % len(registrars)],
            original="stored" if stored else "not_applicable",
        ))
        source = inputs.locate_source(path, project, userdata)
        found = path.stat()
        values: dict[str, Any] = dict(
            input_uid=uid, ord=0, role="main", anchor=str(source.anchor), path=source.path,
            ref_uid=source.ref_uid, size=found.st_size, mtime_ns=found.st_mtime_ns,
            sha256=hashing.sha256_file(path),
        )
        if stored:
            original = root / "originals" / uid / path.name
            original.parent.mkdir(parents=True)
            shutil.copyfile(path, original)
            kept = original.stat()
            values.update(original_path=f"originals/{uid}/{path.name}",
                          original_sha256=values["sha256"], original_size=kept.st_size,
                          original_mtime_ns=kept.st_mtime_ns)
        files.append(file_row(**values))
    _insert(conn, "gb_input", rows)
    _insert(conn, "gb_input_file", files)
    return uids


def _parameters(conn: Any) -> dict[str, dict[str, Any]]:
    """Los 300 parámetros con sus 10 revisiones; por clave, lo que anota quien los lee."""
    rows, history, read = [], [], {}
    for index, defn in enumerate(DEFINITIONS):
        uid = _uid(4, index)
        value = 1.0 + index
        value_sha = store_mod.value_sha256(value, "m")
        rows.append(parameter_row(
            uid=uid, key=defn.key, module=MODULE, value=store_mod.value_json(value), unit="m",
            kind="ADOPTADO", rev=REVISIONS, def_sha256=store_mod.definition_sha256(defn),
            value_sha256=value_sha,
        ))
        for rev in range(1, REVISIONS + 1):
            earlier = value - 0.01 * (REVISIONS - rev)
            history.append(history_row(
                parameter_uid=uid, rev=rev, action="default" if rev == 1 else "change",
                value=store_mod.value_json(earlier), unit="m",
                value_sha256=store_mod.value_sha256(earlier, "m"),
                changed_at=f"2026-10-08T09:{rev:02d}:00.000Z",
            ))
        read[defn.key] = dict(parameter_uid=uid, key=defn.key, rev=REVISIONS,
                              value=store_mod.value_json(value), unit="m", kind="ADOPTADO",
                              unconfirmed=0, value_sha256=value_sha)
    _insert(conn, "gb_parameter", rows)
    _insert(conn, "gb_parameter_history", history)
    return read


def _write_files(root: Path, names: Sequence[str]) -> list[Path]:
    """Los ficheros de los datos ``names``, de 100 en 100 en ``rasters/fNN/``."""
    paths = []
    for number, name in enumerate(names):
        folder = root / "rasters" / f"f{number // FILES_PER_FOLDER:02d}"
        if number % FILES_PER_FOLDER == 0:
            folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{name}.bin"
        path.write_bytes(b"r" * (1 + number % 97))
        paths.append(path)
    return paths


def build_d13(parent: Path, sources: Path, *, chains: int = CHAINS,
              clock: Any | None = None) -> D13Project:
    """Crea en ``parent`` el proyecto con el volumen de D-13 (véase el módulo) en ``chains``
    cadenas, con las 100 fuentes de sus entradas en ``sources``. Necesita :func:`registered`."""
    if chains < 1 or OPERATIONS % chains:
        raise ValueError(f"{OPERATIONS} operaciones no se reparten en {chains} cadenas")
    length = OPERATIONS // chains
    project, userdata, cleanup = _start(parent, sources, clock)
    try:
        root = Path(project.root)
        source_paths = _write_sources(sources)
        operations = [_uid(1, index) for index in range(OPERATIONS)]
        names = [f"{MODULE}_d{index:05d}" for index in range(DATASETS)]
        file_paths = _write_files(root, names[::FILE_EVERY])
        file_count = len(file_paths)
        heads = [operations[chain * length] for chain in range(chains)]
        with project.write_transaction() as conn:
            _insert(conn, "gb_operation", [_operation(index) for index in range(OPERATIONS)])
            input_uids = _inputs(conn, project, userdata, source_paths, heads)
            read = _parameters(conn)
            tables = [f"{MODULE}_tabla{number:03d}"
                      for number in range((DATASETS - file_count) // ROWS_PER_TABLE)]
            for table in tables:
                base.create_attribute_table(conn, table, [base.ColumnDef("codigo", "TEXT")],
                                            table)
                tracking.track_table(conn, table)
                conn.executemany(f'INSERT INTO "{table}" (codigo) VALUES (?)',
                                 [(f"V{row}",) for row in range(ROWS_PER_TABLE)])
            states = tracking.table_states(conn, tables)
            data, changes, io = [], [], []
            files = iter(file_paths)
            table_row = 0
            for index, name in enumerate(names):
                producer = operations[index // OUTPUTS]
                common = dict(uid=_uid(2, index), name=name, module=MODULE, selector="",
                              content_sha256=SHA, crs_epsg=None, operation_uid=producer,
                              input_uid=None, immutable=0)
                if index % FILE_EVERY == 0:
                    path = next(files)
                    found = path.stat()
                    data.append(dataset_row(
                        **common, kind="raster", store="rasters",
                        locator=path.relative_to(root).as_posix(), reader=FILE_READER,
                        tracked_size=found.st_size, tracked_mtime_ns=found.st_mtime_ns,
                        tracked_last_change=None, tracked_schema_sha256=None,
                    ))
                else:
                    table = tables[table_row // ROWS_PER_TABLE]
                    state = states[table]
                    selector = {"column": "codigo", "equals": f"V{table_row % ROWS_PER_TABLE}"}
                    data.append(dataset_row(
                        **{**common, "selector": _json(selector)}, kind="table", store="gpkg",
                        locator=table, reader="core.gpkg_layer@1",
                        tracked_last_change=state.last_change,
                        tracked_schema_sha256=state.schema_sha256,
                    ))
                    table_row += 1
                changes.append(dataset_change_row(dataset_uid=common["uid"], to_sha256=SHA,
                                                  operation_uid=producer))
                io.append(io_row(operation_uid=producer, item_uid=common["uid"],
                                 content_sha256=SHA, role=f"r{index % OUTPUTS}"))
            uses, figure_rows = [], []
            for index, operation in enumerate(operations):
                chain, step = divmod(index, length)
                if step == 0:
                    consumed = input_uids[chain] if chain < len(input_uids) else input_uids[0]
                    io.append(io_row(
                        operation_uid=operation, direction="in", item_kind="input",
                        item_uid=consumed, role="source",
                        content_sha256=hashing.sha256_bytes(
                            f"contenido Entrada_{input_uids.index(consumed):03d}".encode()),
                    ))
                    keys = [COMMON_KEY, parameter_key(1 + chain % (FIRST_INNER_PARAMETER - 1))]
                else:
                    io.append(io_row(operation_uid=operation, direction="in",
                                     item_uid=_uid(2, OUTPUTS * (index - 1)),
                                     content_sha256=SHA, role="source"))
                    span = PARAMETERS - FIRST_INNER_PARAMETER
                    keys = [parameter_key(FIRST_INNER_PARAMETER + index % span)]
                uses.extend(op_param_row(operation_uid=operation, scope="project",
                                         **read[key]) for key in keys)
                if step == length - 1:
                    scope = {"chain": chain}
                    figure_rows.append(figure_row(
                        uid=_uid(5, chain), key=FIGURE_KEY, label="D-13 total",
                        value=1000.0 + chain, unit="t", kind="CALCULADO",
                        operation_uid=operation, scope=figures_mod.scope_json(scope),
                        scope_key=figures_mod.scope_key(scope),
                    ))
            _insert(conn, "gb_dataset", data)
            _insert(conn, "gb_dataset_change", changes)
            _insert(conn, "gb_operation_io", io)
            _insert(conn, "gb_operation_param", uses)
            _insert(conn, "gb_figure", figure_rows)
    except BaseException:
        project.close()
        cleanup.close()
        raise
    return D13Project(project, userdata, tuple(source_paths), tuple(file_paths),
                      tuple(operations), tuple(names), tuple(input_uids),
                      tuple(row["uid"] for row in figure_rows), chains, cleanup)


def build_inputs(parent: Path, sources: Path, *, clock: Any | None = None) -> D13Project:
    """Crea en ``parent`` un proyecto con solo las 100 entradas de D-13 (registradas por una
    importación), con sus fuentes en ``sources``: para medir su comprobación con las fuentes
    en la red. Necesita :func:`registered`."""
    project, userdata, cleanup = _start(parent, sources, clock)
    try:
        source_paths = _write_sources(sources)
        importer = _uid(1, 0)
        with project.write_transaction() as conn:
            _insert(conn, "gb_operation", [_operation(0)])
            input_uids = _inputs(conn, project, userdata, source_paths, [importer])
    except BaseException:
        project.close()
        cleanup.close()
        raise
    return D13Project(project, userdata, tuple(source_paths), (), (importer,), (),
                      tuple(input_uids), (), 1, cleanup)


def write_output_tables(project: Any, prefix: str, count: int,
                        rows: int = 10) -> list[Any]:
    """Escribe ``count`` tablas ``<prefix>_<n>`` de ``rows`` filas en el proyecto (en su
    transacción) y devuelve sus ``DatasetSpec`` con el contenido ya calculado (como las salidas
    de un trabajo, que llegan con su hash)."""
    names = [f"{prefix}_{number}" for number in range(count)]
    with project.write_transaction() as conn:
        for name in names:
            base.create_attribute_table(conn, name, [base.ColumnDef("valor", "DOUBLE")], name)
            conn.executemany(f'INSERT INTO "{name}" (valor) VALUES (?)',
                             [(0.5 * row,) for row in range(rows)])
    specs = []
    with project.read() as conn:
        for number, name in enumerate(names):
            request = builtin.GPKG_LAYER.request(
                "table", dataset_model.DATASET_DECLARATIONS, {"main": project.database_path},
                {"layer": name})
            for _ in builtin.layer_steps(conn, request):
                pass
            specs.append(datasets.DatasetSpec(
                name, MODULE, "table", "gpkg", name, reader=builtin.GPKG_LAYER.id,
                role=f"salida{number}", content=request.hasher.digest(),
            ))
    return specs


# --- Fuentes grandes (RNF-008-05 y 11) -------------------------------------------------------

GRID_DECLARATIONS: Mapping[str, Any] = {
    "conventions": {}, "crs_h": {"epsg": 25830}, "crs_v": {"epsg": 5782},
}
LAYER_DECLARATIONS: Mapping[str, Any] = GRID_DECLARATIONS
TABLE_DECLARATIONS: Mapping[str, Any] = {
    "conventions": {}, "crs_h": {"not_applicable": True}, "crs_v": {"not_applicable": True},
}
LAYER_NAME = "parcelas"
ASSAYS_NAME = "ensayos"
LAYER_VERTICES = 20
LAYER_BATCH = 50_000  # polígonos por lote al escribir una capa
BAND_CELLS = 4_000_000  # celdas por banda al escribir una rejilla grande


def grid_settings() -> dict[str, Any]:
    """Los ajustes de lectura de ``test.npy_grid@1`` de las rejillas de :func:`write_mdt`."""
    return {"x0": 715000.0, "y0": 4378000.0, "dx": 2.0, "dy": 2.0, "cell": "area",
            "nodata": -9999.0, "crs": {"epsg": 25830}}


def write_mdt(path: Path, shape: tuple[int, int]) -> Path:
    """Escribe en ``path`` un MDT sintético ``.npy`` de ``shape`` celdas float32 (una ladera
    con ondulaciones), por bandas: nunca tiene la rejilla entera en memoria."""
    rows, columns = shape
    grid = np.lib.format.open_memmap(path, mode="w+", dtype=np.float32, shape=shape)
    try:
        band = max(1, BAND_CELLS // columns)
        across = (0.05 * np.arange(columns, dtype=np.float64)
                  + 3.0 * np.sin(np.arange(columns) / 37.0))
        for start in range(0, rows, band):
            stop = min(rows, start + band)
            down = 800.0 - 0.03 * np.arange(start, stop, dtype=np.float64)
            grid[start:stop] = (down[:, None] + across[None, :]).astype(np.float32)
        grid.flush()
    finally:
        del grid
    return path


def _parcel_blobs(first: int, count: int, circle: np.ndarray) -> list[bytes]:
    """Los blobs GeoPackage de los polígonos ``first``…``first + count − 1`` de
    :func:`write_layer` (cabecera con su envolvente XY y WKB ISO *little-endian*), escritos
    de una vez con numpy: los mismos bytes que ``gpkg.encode_geometry``, que lo comprueba con
    el primero (T67: 2 M polígonos en segundos, no en un minuto)."""
    index = np.arange(first, first + count)
    centres = np.column_stack([715_000.0 + (index % 300) * 10.0,
                               4_378_000.0 + (index // 300) * 10.0])
    rings = circle[None, :, :] + centres[:, None, :]
    rings = np.concatenate([rings, rings[:, :1]], axis=1)  # cerrado
    reference = gpkg.encode_geometry("POLYGON", [rings[0]], 25830, False)
    points = rings.shape[1]
    wkb_at = len(reference) - 16 * points - 13  # cabecera y envolvente | WKB (13 B) | puntos
    envelope = np.stack([rings[:, :, 0].min(axis=1), rings[:, :, 0].max(axis=1),
                         rings[:, :, 1].min(axis=1), rings[:, :, 1].max(axis=1)], axis=1)
    blobs = np.empty((count, len(reference)), dtype=np.uint8)
    blobs[:, :8] = np.frombuffer(reference[:8], dtype=np.uint8)
    blobs[:, 8:wkb_at] = envelope.astype("<f8").view(np.uint8)
    blobs[:, wkb_at:wkb_at + 13] = np.frombuffer(reference[wkb_at:wkb_at + 13], dtype=np.uint8)
    blobs[:, wkb_at + 13:] = rings.astype("<f8").reshape(count, -1).view(np.uint8)
    found = [row.tobytes() for row in blobs]
    if found[0] != reference:
        raise AssertionError("los blobs de write_layer no son los de gpkg.encode_geometry")
    return found


def write_layer(path: Path, count: int) -> Path:
    """Escribe en ``path`` un GeoPackage con la capa :data:`LAYER_NAME` de ``count`` polígonos
    de :data:`LAYER_VERTICES` vértices (EPSG:25830) con un código y una ley, por lotes de
    :data:`LAYER_BATCH`."""
    crs = georef.load_catalog().horizontal(25830)
    angles = np.linspace(0.0, 2.0 * np.pi, LAYER_VERTICES + 1)[:-1]
    circle = np.column_stack([4.0 * np.cos(angles), 4.0 * np.sin(angles)])
    with gpkg.GpkgConnection.open_write(path, create=True) as db, db.transaction() as conn:
        base.create_base(conn, crs)
        base.create_feature_table(
            conn, LAYER_NAME, "POLYGON", 25830, False,
            [base.ColumnDef("codigo", "TEXT"), base.ColumnDef("ley", "DOUBLE")], "Parcelas")

        def features() -> Iterator[tuple[bytes, str, float]]:
            for first in range(0, count, LAYER_BATCH):
                blobs = _parcel_blobs(first, min(LAYER_BATCH, count - first), circle)
                for index, blob in enumerate(blobs, start=first):
                    yield blob, f"P-{index:06d}", 0.01 * index

        conn.executemany(f"INSERT INTO {LAYER_NAME} (geom, codigo, ley) VALUES (?, ?, ?)",
                         features())
    return path


def write_assays(path: Path, count: int) -> Path:
    """Escribe en ``path`` un GeoPackage con la tabla de ensayos :data:`ASSAYS_NAME` de
    ``count`` filas: sondeo, desde, hasta, ley de cobre y litología."""
    crs = georef.load_catalog().horizontal(25830)
    rocks = ("granito", "pizarra", "cuarcita", "esquisto")
    with gpkg.GpkgConnection.open_write(path, create=True) as db, db.transaction() as conn:
        base.create_base(conn, crs)
        base.create_attribute_table(
            conn, ASSAYS_NAME,
            [base.ColumnDef("sondeo", "TEXT"), base.ColumnDef("desde", "DOUBLE"),
             base.ColumnDef("hasta", "DOUBLE"), base.ColumnDef("ley_cu", "DOUBLE"),
             base.ColumnDef("litologia", "TEXT")], "Ensayos")
        conn.executemany(
            f"INSERT INTO {ASSAYS_NAME} (sondeo, desde, hasta, ley_cu, litologia) "
            "VALUES (?, ?, ?, ?, ?)",
            ((f"S-{index // 250:04d}", 1.5 * (index % 250), 1.5 * (index % 250) + 1.5,
              0.001 * (index % 997), rocks[index % 4]) for index in range(count)),
        )
    return path


def _comma(value: float, digits: int) -> str:
    """Un número con coma decimal (salida en español)."""
    return f"{value:.{digits}f}".replace(".", ",")


class ProgressClock:
    """Mide el hueco más largo sin aviso de progreso de una lectura (desde que se crea hasta
    el primer aviso, entre dos y desde el último hasta :meth:`finish`)."""

    def __init__(self) -> None:
        self.started = time.perf_counter()
        self.last = self.started
        self.gap = 0.0
        self.ticks = 0

    def tick(self, _fraction: float) -> None:
        now = time.perf_counter()
        self.gap = max(self.gap, now - self.last)
        self.last = now
        self.ticks += 1

    def finish(self) -> tuple[float, float]:
        """El tiempo total y el hueco más largo."""
        now = time.perf_counter()
        self.gap = max(self.gap, now - self.last)
        return now - self.started, self.gap


# --- Arnés de RNF-008-11 ---------------------------------------------------------------------

BIG_HASH_BUDGET_S = 45.0  # RNF-008-11: un MDT de 100 M celdas en disco local
BIG_MDT_SHAPE = (10_000, 10_000)
BIG_LAYER_BUDGET_S = 60.0  # RNF-008-11: un GeoPackage de 1 GB en Z: (en local, también)
BIG_LAYER_FEATURES = 2_000_000  # T67: 2 M polígonos de 20 vértices (unos 0,9 GB)
PROGRESS_GAP_S = 1.0  # RNF-008-11: progreso cada ≤ 1 s
CANCEL_BUDGET_S = 2.0  # RNF-008-11: cancelación efectiva en ≤ 2 s
JOBS_FOLDER = "trabajos"  # la raíz de las carpetas de trabajo del arnés


class _WatchedEvent(threading.Event):
    """El aviso de parar del trabajo del arnés, que apunta cuándo lo mira el trabajo
    (``WorkerContext.check_cancelled``, tras cada trozo): el mayor intervalo entre dos miradas
    es lo más que tardaría en parar si se cancelase en cualquier momento (T67)."""

    def __init__(self) -> None:
        super().__init__()
        self.looks: list[float] = []

    def is_set(self) -> bool:
        self.looks.append(time.perf_counter())
        return super().is_set()


@dataclass(frozen=True)
class BigSource:
    """Una fuente grande para el arnés: sus ficheros por papel (``"main"`` siempre), el tipo
    de dato, lo declarado al importar, los ajustes de lectura y cómo se nombra en la medida."""

    files: Mapping[str, Path]
    kind: str
    declarations: Mapping[str, Any]
    settings: Mapping[str, Any]
    label: str


class _HarnessSink:
    """Los eventos del trabajo de hash en el arnés (su ``EventSink``): cada aviso de progreso,
    de la copia verificada (si el lector la pide; spec 005, T43) o de la lectura, va a
    ``progress`` y, si después ``cancelled()`` lo pide, se activa el aviso de parar del
    trabajo (``cancel``); apunta lo que tardó la copia verificada (de empezar a su primer
    aviso de lectura; 0 si no hubo copia), cuándo llegó ese aviso y la última fracción."""

    def __init__(self, progress: Callable[[float], object] | None,
                 cancelled: Callable[[], bool] | None, cancel: threading.Event) -> None:
        self.started = time.perf_counter()
        self.progress = progress
        self.cancelled = cancelled
        self.cancel = cancel
        self.copying = False
        self.copy_s = 0.0
        self.reading_at: float | None = None
        self.fraction = 0.0

    def send(self, event: Any) -> None:
        if event.type != "progress":
            return
        if event.msg == content_hash.COPYING_TEXT:
            self.copying = True
        elif self.reading_at is None:
            self.reading_at = time.perf_counter()
            if self.copying:
                self.copy_s = self.reading_at - self.started
        self.fraction = event.frac
        if self.progress is not None:
            self.progress(event.frac)
        if self.cancelled is not None and self.cancelled():
            self.cancel.set()


class BigHashHarness:
    """El arnés de RNF-008-11 por lector (S-4): el hash de contenido de una fuente grande por
    el camino común del trabajo de hash ``core_content_hash`` (``jobs.content_hash.run``, la
    función que ejecuta el trabajo en el hilo y en proceso aparte, con las rutas de la fuente
    por ``paths``, su copia verificada de ``JobDir.copy_input`` si el lector la pide y el
    progreso y la cancelación de su ``WorkerContext``), con su presupuesto, un aviso de
    progreso cada ≤ 1 s y la cancelación en ≤ 2 s: mirada cada ≤ 2 s mientras copia y lee (lo
    más que tardaría en parar si se cancelase en cualquier momento; T67 y, con la copia, spec
    005 T43), al empezar y a mitad.

    Se usa como mezcla de una clase de pruebas (``class X(BigHashHarness, unittest.TestCase)``)
    que da el lector (``reader``, que el arnés registra si no lo está), su presupuesto
    (``budget_s``) y la fuente (``make_source``, que la escribe una vez para la clase en una
    carpeta temporal); ``report`` imprime la línea de la medida. La 006 lo hereda con su GeoTIFF
    de 100 M celdas y la 005 con su base de RecMin de 100 MB."""

    reader: ClassVar[Any] = None
    budget_s: ClassVar[float] = BIG_HASH_BUDGET_S
    progress_gap_s: ClassVar[float] = PROGRESS_GAP_S
    cancel_budget_s: ClassVar[float] = CANCEL_BUDGET_S
    requirement: ClassVar[str] = "RNF-008-11"
    source: ClassVar[BigSource]
    big_folder: ClassVar[Path]
    _big_stack: ClassVar[ExitStack]
    sink: _HarnessSink  # los eventos del último trabajo (hash_source)
    cancel_event: _WatchedEvent  # su aviso de parar, con las miradas del trabajo

    @classmethod
    def make_source(cls, folder: Path) -> BigSource:
        """La fuente grande, escrita en ``folder`` (ya existe)."""
        raise NotImplementedError("la clase de pruebas da la fuente de su lector")

    @classmethod
    def report(cls, text: str) -> None:
        """Imprime la línea de la medida (``tools/check.py`` la recoge)."""
        print(text, file=sys.stderr, flush=True)

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()  # type: ignore[misc]
        if cls.reader is None:
            raise TypeError(f"{cls.__name__}: el arnés necesita el lector («reader»)")
        cls._big_stack = ExitStack()
        try:
            cls.big_folder = Path(cls._big_stack.enter_context(tempfile.TemporaryDirectory(
                prefix="gb-008-big-", ignore_cleanup_errors=True)))
            folder = cls.big_folder / "fuente"
            folder.mkdir()
            cls.source = cls.make_source(folder)
            if cls.reader.id not in readers.READERS:
                readers.register_reader(cls.reader)
                cls._big_stack.callback(readers.unregister_reader, cls.reader.id)
        except BaseException:
            cls._big_stack.close()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        cls._big_stack.close()
        super().tearDownClass()  # type: ignore[misc]

    def hash_source(self, *, progress: Any = None, cancelled: Any = None) -> tuple[Any, float]:
        """El hash de la fuente por el camino común (``jobs.content_hash.run`` en una carpeta
        de trabajo nueva, con las rutas de la fuente por ``paths``) y lo que tardó su copia
        verificada (0 si el lector no la pide). ``progress(fracción)`` recibe los avisos de
        progreso del trabajo; si después ``cancelled()`` es verdadero, el trabajo para en el
        trozo siguiente (``JobCancelled``)."""
        size = sum(os.path.getsize(path) for path in self.source.files.values())
        request = checks.HashRequest(self.requirement, self.source.label, self.reader.id,
                                     self.source.kind, self.source.declarations,
                                     self.source.settings, self.source.files,
                                     encoder.NORMALIZER, size)
        job = content_hash.new_job(request)
        folder = job_paths.job_dir(self.big_folder / JOBS_FOLDER, job.job_uid).create()
        self.cancel_event = cancel = _WatchedEvent()
        self.sink = _HarnessSink(progress, cancelled, cancel)
        ctx = worker_api.WorkerContext(job, folder, self.sink, cancel_event=cancel,
                                       paths=content_hash.job_paths(request))
        summary = content_hash.run(ctx)
        digest = encoder.ContentDigest(summary["data_sha256"], summary["content_sha256"],
                                       summary["normalizer"], summary["reader"])
        return digest, self.sink.copy_s

    def _size(self) -> str:
        total = sum(os.path.getsize(path) for path in self.source.files.values())
        return f"{total / 1e6:.0f} MB"

    def _looks_gap(self, end: float) -> float:
        """El mayor intervalo sin mirar la cancelación desde que empieza el trabajo (también
        mientras copia la fuente, si su lector lo pide: cada aviso de la copia la mira; spec
        005, T43) hasta ``end``."""
        start = self.sink.started
        moments = [start, *(look for look in self.cancel_event.looks if look >= start), end]
        return max(later - earlier for earlier, later in zip(moments, moments[1:]))

    def test_big_hash(self) -> None:
        """RNF-008-11: el hash de contenido en segundo plano de la fuente grande del lector
        tarda lo que su presupuesto (un MDT de 100 M celdas, ≤ 45 s en disco local), con un
        aviso de progreso cada ≤ 1 s y, mientras copia y lee, la cancelación mirada cada
        ≤ 2 s."""
        clock = ProgressClock()
        digest, copy_s = self.hash_source(progress=clock.tick)
        total, gap = clock.finish()
        looks = self._looks_gap(clock.started + total)
        test: Any = self
        test.assertEqual(digest.reader, self.reader.id)
        copied = f" (copia verificada {_comma(copy_s, 2)} s)" if copy_s else ""
        self.report(
            f"{self.requirement}: hash de contenido de {self.source.label} ({self._size()}) "
            f"con {self.reader.id}: {_comma(total, 2)} s{copied}, {clock.ticks} avisos de "
            f"progreso, el mayor hueco {_comma(gap, 3)} s, la cancelación mirada cada "
            f"≤ {_comma(looks, 3)} s (presupuestos {_comma(self.budget_s, 0)} s, "
            f"{_comma(self.progress_gap_s, 0)} s y {_comma(self.cancel_budget_s, 0)} s)"
        )
        test.assertLessEqual(total, self.budget_s)
        test.assertLessEqual(gap, self.progress_gap_s)
        test.assertLessEqual(looks, self.cancel_budget_s)

    def _cancelled_when(self, wanted: Callable[[float], bool], moment: str) -> None:
        """Cancela en el primer aviso de lectura cuya fracción cumple ``wanted`` y comprueba
        que el trabajo para (``JobCancelled``) en ≤ 2 s."""
        asked: list[float] = []

        def progress(fraction: float) -> None:
            if wanted(fraction) and not asked:
                asked.append(time.perf_counter())

        test: Any = self
        with test.assertRaises(worker_api.JobCancelled):
            self.hash_source(progress=progress, cancelled=lambda: bool(asked))
        took = time.perf_counter() - asked[0]
        self.report(
            f"{self.requirement}: cancelar {moment} el hash de contenido de "
            f"{self.source.label} con {self.reader.id}: parado en {_comma(took, 3)} s al "
            f"{100 * self.sink.fraction:.0f} % (presupuesto "
            f"{_comma(self.cancel_budget_s, 0)} s)"
        )
        test.assertLessEqual(took, self.cancel_budget_s)

    def test_big_hash_cancelled_at_start(self) -> None:
        """RNF-008-11 (T67): cancelar al empezar a leer (el primer aviso con avance: con un
        GeoPackage, mientras cuenta sus filas) el hash de contenido de la fuente grande del
        lector lo para en ≤ 2 s (``JobCancelled`` del trabajo)."""
        self._cancelled_when(lambda fraction: fraction > 0.0, "al empezar")

    def test_big_hash_cancelled_at_half(self) -> None:
        """RNF-008-11: cancelar a mitad el hash de contenido de la fuente grande del lector
        lo para en ≤ 2 s, entre dos trozos (``JobCancelled`` del trabajo)."""
        self._cancelled_when(lambda fraction: fraction >= 0.5, "a mitad")

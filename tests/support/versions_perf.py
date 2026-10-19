# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo común de las pruebas de rendimiento de las versiones (spec 009, T28; plan 009 §2.2 y
§7.3; ``tests/rendimiento/core/test_versions_perf.py``). Datos solo sintéticos, en carpetas que
borra quien las crea.

- **Llevar unos pasos como su orden** (:func:`drive`): cada ``next()`` es una llamada del
  temporizador del modal; la primera llamada es la que los crea (la orden hace el plan en
  ``execute``). Da el total, cada llamada, el mayor hueco entre dos avances, lo que suma cada
  fase y, con ``cancel_at``, lo que tarda cerrar los pasos (Esc) con el avance en esa fracción.
  Con ``waits`` (``tests.support.netwaits.NetworkWaits``, el proyecto en la red), también las
  esperas de la red de cada llamada y lo propio, sin ellas (RNF-009-05, T29).
- **El GB de RNF-009-02** (y los 5 GB de RNF-009-05, la T29: :data:`FIVE_GIGABYTES` con el
  proyecto en la carpeta de la red y los datos de usuario en disco local, ``userdata``):
  :func:`big_project` crea el proyecto de la demostración de versiones
  (``tests.support.versions_fixtures.build``) y escribe en V01, con el tipo de prueba
  :data:`BIG_OP`, ``rasters`` rejillas de ``side`` × ``side`` celdas Float64 de 1 m (GeoTIFF del
  perfil ``project`` de la 006: DEFLATE y predictor 3) con el terreno de ``gis_perf`` (la
  superficie de RNF-006-01 con su ruido de 5 cm, a mm) y cada una con otra cota, una malla npz
  de ``vertices`` vértices y el doble de caras y una tabla de ``rows`` filas.
- **El proyecto de D-13 con versiones** (RNF-009-01; :func:`build_d13_versions`): el volumen de
  la 008 (``tests.support.provenance_fixtures``) con :data:`VERSIONS` versiones, cada una con
  :data:`VERSION_OPERATIONS` operaciones del tipo de prueba :data:`STEP_OP` (cada una consume
  el final de una cadena de D-13 y escribe una tabla de su versión), su r1 congelada por SQL
  (``versions_fixtures.freeze_rows``) y su r2 abierta; la primera, VIGENTE.
  :meth:`D13Versions.declare` declara VIGENTE otra y mide la transacción y la cabecera.
- **Las 200 revisiones** (RNF-009-03 y 04; :func:`build_revisions`): el proyecto de la
  demostración de versiones con 20 versiones y 10 revisiones congeladas de verdad en cada una
  (``demo.pit`` con otra cota y ``demo.pit_stockpiles``, y ``freeze_steps``), cerrado;
  :func:`open_revisions` lo abre (en su carpeta o en una copia) y :func:`open_check` mide el paso
  «instantáneas» de la comprobación de apertura.
- **El crecimiento** (RNF-009-06; :func:`growth_project`): un proyecto con una versión por
  número de elementos, hecha de operaciones del tipo de prueba :data:`GROWTH_OP` (cada una lee un
  parámetro de D-13, escribe dos tablas y da una cifra: cuatro elementos y los parámetros, como
  mucho :data:`provenance_fixtures.PARAMETERS`) y su r1 congelada de verdad;
  :func:`freeze_unchanged` congela la siguiente sin cambiar nada y mide lo que crece.

Solo fuera de Blender (el Python de Blender de ``tools/check.py --rendimiento``).
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from tests.support import gis_perf
from tests.support import provenance_fixtures as d13
from tests.support import versions_demo as vdemo
from tests.support import versions_fixtures as fixtures
from tests.support.core_fixtures import FakeClock, make_settings
from tests.support.package import import_geoblender
from tests.support.provenance_demo import DEMO_CODE

builtin = import_geoblender("core.content.builtin")
base = import_geoblender("core.gpkg.base")
datasets = import_geoblender("core.datasets")
dataset_model = import_geoblender("core.datasets.model")
contract = import_geoblender("core.provenance.contract")
operations = import_geoblender("core.provenance.operations")
figures_mod = import_geoblender("core.provenance.figures")
checks = import_geoblender("core.provenance.checks")
create = import_geoblender("core.project.create")
open_mod = import_geoblender("core.project.open")
userdata_mod = import_geoblender("core.userdata")
timeutil = import_geoblender("core.timeutil")
freeze = import_geoblender("core.versions.freeze")
vcheck = import_geoblender("core.versions.check")
vmodel = import_geoblender("core.versions.model")
vread = import_geoblender("core.versions.read")
vstore = import_geoblender("core.versions.store")
gis = import_geoblender("gis")
gis_content = import_geoblender("gis.content")
gis_store = import_geoblender("gis.store")
writer = import_geoblender("gis.geotiff.writer")

INTERPRETER = f"Python {platform.python_version()}, numpy {np.__version__}"
number = gis_perf.number
count = gis_perf.count


def report(text: str) -> None:
    """Imprime una línea de cifra con el intérprete (``tools/check.py`` las recoge)."""
    print(f"{text} [{INTERPRETER}]", file=sys.stderr, flush=True)


def free_space(path: Path) -> str:
    """El espacio libre del disco de ``path`` («12,3 GB libres en C:»; trampa §6). De una
    carpeta de la red (una ruta UNC) no se dice el servidor: «en la red»."""
    path = Path(path)
    drive = path.drive
    where = "la red" if not drive or drive.startswith("\\\\") else drive
    return f"{number(shutil.disk_usage(path).free / 1e9, 1)} GB libres en {where}"


def folder_size(root: Path) -> int:
    """Lo que ocupa la carpeta del proyecto ``root`` sin su caché (RNF-009-06)."""
    total = 0
    for folder, dirs, names in os.walk(root):
        if Path(folder) == Path(root) and "cache" in dirs:
            dirs.remove("cache")
        total += sum(os.stat(os.path.join(folder, name)).st_size for name in names)
    return total


def listing(root: Path, *, hashes: bool = True,
            skip_dirs: Sequence[str] = ()) -> dict[str, object]:
    """Cada fichero y carpeta del proyecto ``root`` sin la base, su diario ni la cabecera: con
    su huella (``versions_fixtures.files``) o, sin ``hashes``, solo con su tamaño y su fecha
    (en la red, sin leer cada fichero)."""
    if hashes:
        return fixtures.files(root, skip_dirs=skip_dirs)
    found: dict[str, object] = {}
    root = Path(root)
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if rel in fixtures.WRITTEN or rel.split("/")[0] in skip_dirs:
            continue
        if path.is_dir():
            found[rel] = "carpeta"
        else:
            stat = path.stat()
            found[rel] = (stat.st_size, stat.st_mtime_ns)
    return found


def cache_leftovers(project: Any) -> list[str]:
    """Lo que dejó una congelación en la caché del proyecto (su GeoPackage a medias)."""
    cache = Path(project.cache_dir())
    if not cache.exists():
        return []
    return sorted(path.name for path in cache.rglob("*") if vmodel.FREEZING_MARK in path.name)


# --- Llevar los pasos como su orden -------------------------------------------------------------


@dataclass
class Driven:
    """Lo que tardaron unos pasos llevados como su orden (véase :func:`drive`)."""

    total_s: float
    calls: list[float]
    gap_s: float
    phases: dict[str, float]
    result: Any = None
    cancelled_s: float | None = None
    cancelled_at: float | None = None
    called: list[str] = field(default_factory=list)  # la fase de cada llamada
    # Con ``waits``: las esperas de la red de cada llamada y las de cerrar los pasos (Esc).
    waits: list[dict[str, float]] = field(default_factory=list)
    cancel_waits: dict[str, float] = field(default_factory=dict)

    @property
    def longest_s(self) -> float:
        """La llamada más larga (también la que crea los pasos)."""
        return max(self.calls)

    @property
    def longest_phase(self) -> str:
        """La fase de la llamada más larga."""
        return self.called[self.calls.index(self.longest_s)] if self.called else ""

    @property
    def steps(self) -> int:
        return len(self.calls)

    @property
    def own(self) -> list[float]:
        """Lo que hace Geoblender en cada llamada: su duración sin sus esperas de la red (sin
        ``waits``, toda)."""
        if not self.waits:
            return list(self.calls)
        return [call - sum(waits.values()) for call, waits in zip(self.calls, self.waits,
                                                                  strict=True)]

    @property
    def worst_own(self) -> int:
        """La llamada con más trabajo propio (su índice)."""
        own = self.own
        return own.index(max(own))

    @property
    def cancel_own_s(self) -> float:
        """Lo propio de cerrar los pasos (Esc), sin sus esperas de la red; 0 sin cerrarlos."""
        if self.cancelled_s is None:
            return 0.0
        return self.cancelled_s - sum(self.cancel_waits.values())


START_PHASE = "plan"
"""La fase de la primera llamada, la que crea los pasos (el plan de la congelación)."""


def drive(start: Callable[[], Iterator[Any]], *, cancel_at: float | None = None,
          waits: Any = None) -> Driven:
    """Llama a ``start()`` y recorre los pasos que da como el temporizador de su orden: mide cada
    llamada, el hueco entre dos avances (desde que se pulsa) y lo de cada fase. Con
    ``cancel_at``, los cierra (Esc) en cuanto el avance (``done / total``) llega a esa fracción
    y mide lo que tarda cerrarlos. Con ``waits`` (una ``netwaits.NetworkWaits`` activa), también
    las esperas de la red de cada llamada (``Driven.waits``) y de cerrarlos."""
    calls: list[float] = []
    called: list[str] = []
    waited: list[dict[str, float]] = []
    phases: dict[str, float] = {}
    result: Any = None

    def begin() -> None:
        if waits is not None:
            waits.begin()

    def took() -> None:
        if waits is not None:
            waited.append(waits.take())

    begin()
    began = time.perf_counter()
    steps = start()
    last = time.perf_counter()
    took()
    calls.append(last - began)
    called.append(START_PHASE)
    phases[START_PHASE] = last - began
    gap = last - began
    while True:
        begin()
        before = time.perf_counter()
        try:
            step = next(steps)
        except StopIteration:
            calls.append(time.perf_counter() - before)
            took()
            called.append(called[-1])
            break
        now = time.perf_counter()
        took()
        calls.append(now - before)
        called.append(step.phase)
        phases[step.phase] = phases.get(step.phase, 0.0) + now - before
        gap = max(gap, now - last)
        last = now
        if step.result is not None:
            result = step.result
        fraction = step.done / step.total if step.total else 0.0
        if cancel_at is not None and step.result is None and fraction >= cancel_at:
            begin()
            closing = time.perf_counter()
            steps.close()
            closed = time.perf_counter() - closing
            closed_waits = waits.take() if waits is not None else {}
            return Driven(now - began, calls, gap, phases, None, closed, fraction, called,
                          waited, closed_waits)
    return Driven(time.perf_counter() - began, calls, gap, phases, result, called=called,
                  waits=waited)


# --- RNF-009-02 (y la T29): datos grandes en una versión ----------------------------------------

BIG_OP = f"{DEMO_CODE}.big_data"
"""El tipo de prueba que escribe los datos grandes en una versión (no se repite)."""
BIG_STEP_M = 1.0
NOISE_SEED = gis_perf.SEED + 9


@dataclass(frozen=True)
class BigData:
    """Lo que escribe :func:`produce_big`: ``rasters`` rejillas de ``side`` × ``side`` celdas,
    una malla de ``vertices`` vértices (y el doble de caras) y una tabla de ``rows`` filas;
    ``nominal_bytes``, lo que deberían ocupar."""

    rasters: int = 10
    side: int = 4096
    vertices: int = 1_500_000
    rows: int = 250_000
    nominal_bytes: int = 1_000_000_000

    @property
    def min_bytes(self) -> int:
        """Lo que copia como poco una congelación de estos datos (el 95 % del nominal)."""
        return int(0.95 * self.nominal_bytes)

    @property
    def label(self) -> str:
        return (f"{self.rasters} rejillas de {count(self.side)} × {count(self.side)} celdas "
                f"Float64, una malla de {count(self.vertices)} vértices y una tabla de "
                f"{count(self.rows)} filas")


GIGABYTE = BigData()
"""El GB de §2.2 del plan (RNF-009-02)."""
FIVE_GIGABYTES = BigData(rasters=55, nominal_bytes=5_000_000_000)
"""Los 5 GB de RNF-009-05 (T29): las rejillas de :data:`GIGABYTE` (unos 90 MB cada una) hasta
pasar de 5 GB, con la misma malla y la misma tabla."""

_TERRAIN: dict[int, np.ndarray] = {}


def terrain(side: int) -> np.ndarray:
    """Las cotas (m, float64, de norte a sur) de una rejilla de ``side`` × ``side`` celdas de
    1 m con el terreno de ``gis_perf`` (su superficie y su ruido de 5 cm), redondeadas a mm."""
    if side not in _TERRAIN:
        _TERRAIN.clear()
        grid = gis.Grid(gis_perf.WEST, gis_perf.SOUTH + side * BIG_STEP_M, BIG_STEP_M,
                        BIG_STEP_M, side, side)
        x, y = grid.centers()
        values = gis_perf.surface(x, y)
        del x, y
        values += np.random.default_rng(NOISE_SEED).normal(0.0, gis_perf.NOISE_M, values.shape)
        _TERRAIN[side] = np.round(values, 3)
    return _TERRAIN[side]


@contextmanager
def big_data_type() -> Iterator[None]:
    """Registra :data:`BIG_OP` (con la demostración de versiones ya registrada) y lo quita."""
    contract.register_operation(contract.OperationDef(
        BIG_OP, "1.0", DEMO_CODE, "Demo big data", False, scope="version"))
    try:
        yield
    finally:
        contract.unregister_operation(BIG_OP)


def _big_body(handle: Any, data: BigData, offset: float) -> None:
    project = handle.project
    crs, vertical = gis_store.project_references(project)
    with project.read() as conn:
        code = vread.version(conn, handle.version_uid).code
    outputs = []
    side = data.side
    grid = gis.Grid(gis_perf.WEST, gis_perf.SOUTH + side * BIG_STEP_M, BIG_STEP_M, BIG_STEP_M,
                    side, side)
    for index in range(data.rasters):
        locator = vmodel.version_locator(f"rasters/demo_big_mdt_{index:02d}.tif", code)
        final = Path(project.root, *locator.split("/"))
        temporary = writer.temporary_path(final)
        handle.claim_paths(final, temporary)
        final.parent.mkdir(parents=True, exist_ok=True)
        raster = gis.Raster(grid, terrain(side) + (offset + index), crs, vertical)
        writer.write_geotiff(raster, final, profile="project", temporary=temporary)
        outputs.append(dataset_model.DatasetSpec(
            f"demo_big_mdt_{index:02d}", DEMO_CODE, "raster", "rasters", locator,
            reader=gis_content.GEOTIFF.id, role=f"mdt_{index:02d}", crs_epsg=crs.epsg))
    rng = np.random.default_rng(gis_perf.SEED + int(offset))
    vertices = np.column_stack([gis_perf.WEST + rng.random(data.vertices) * side,
                                gis_perf.SOUTH + rng.random(data.vertices) * side,
                                850.0 + offset + rng.random(data.vertices) * 50.0])
    faces = rng.integers(0, data.vertices, size=(2 * data.vertices, 3), dtype=np.int32)
    meta = json.dumps({"schema": 1, "kind": "surface", "crs_epsg": crs.epsg, "closed": False})
    locator = vmodel.version_locator("meshes/demo_big_tin.npz", code)
    final = Path(project.root, *locator.split("/"))
    temporary = final.with_name(final.name + ".tmp")
    handle.claim_paths(final, temporary)
    final.parent.mkdir(parents=True, exist_ok=True)
    with temporary.open("wb") as stream:
        np.savez_compressed(stream, vertices=vertices, faces=faces, meta=np.array(meta))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, final)
    outputs.append(dataset_model.DatasetSpec("demo_big_tin", DEMO_CODE, "mesh", "meshes",
                                             locator, reader=builtin.NPZ_MESH.id, role="tin",
                                             crs_epsg=crs.epsg))
    table = vmodel.version_locator("demo_big_cubicacion", code)
    with project.write_transaction() as conn:
        if conn.execute("SELECT 1 FROM gpkg_contents WHERE table_name = ?",
                        (table,)).fetchone() is not None:
            conn.execute(f'DELETE FROM "{table}"')  # otra vez: las filas nuevas
        else:
            base.create_attribute_table(
                conn, table,
                [base.ColumnDef("fase", "TEXT"), base.ColumnDef("banco", "INTEGER"),
                 base.ColumnDef("unidad", "TEXT"), base.ColumnDef("volumen_m3", "DOUBLE"),
                 base.ColumnDef("toneladas", "DOUBLE")],
                f"Cubicación {code}", "Tabla sintética de rendimiento (spec 009)")
        conn.executemany(
            f'INSERT INTO "{table}" (fase, banco, unidad, volumen_m3, toneladas) '
            "VALUES (?, ?, ?, ?, ?)",
            ((f"F{row % 7}", 100 + row % 40, f"U{row % 5}", 1000.0 + offset + 0.25 * (row % 9973),
              2.1 * (1000.0 + 0.25 * (row % 9973))) for row in range(data.rows)))
        outputs.append(dataset_model.DatasetSpec(
            "demo_big_cubicacion", DEMO_CODE, "table", "gpkg", table,
            reader=builtin.GPKG_LAYER.id, role="cubicacion"))
        handle.complete(conn, outputs=outputs)


def produce_big(project: Any, version: str, data: BigData = GIGABYTE, *,
                offset: float = 0.0) -> Any:
    """Escribe ``data`` en ``version`` (uid o código) con :data:`BIG_OP`, cada rejilla con su
    cota más ``offset``; su ``OperationHandle``."""
    with operations.operation(project, BIG_OP, settings={"offset": offset}, inputs=[],
                              params=[], version=version) as handle:
        _big_body(handle, data, offset)
    return handle


@dataclass
class BigProject:
    """El proyecto de :func:`big_project`, abierto en escritura, con los datos en V01."""

    project: Any
    folder: Path
    clock: FakeClock
    version_uid: str
    data: BigData
    produce_s: float

    @property
    def root(self) -> Path:
        return Path(self.project.root)


@contextmanager
def big_project(folder: Path, data: BigData = GIGABYTE, *,
                userdata: Path | None = None) -> Iterator[BigProject]:
    """El proyecto de la demostración de versiones en ``folder`` con ``data`` en V01 (véase el
    módulo), abierto en escritura con la demostración y :data:`BIG_OP` registradas; al salir lo
    cierra (la carpeta es de quien la dio). ``userdata``: la carpeta de los datos de usuario
    (con el proyecto en la red, la de su caché), si no es la de ``folder``."""
    clock = FakeClock()
    with vdemo.VersionsDemo().registered() as demo, big_data_type():
        built = fixtures.build(Path(folder), demo, clock=clock, userdata=userdata)
        try:
            clock.advance(minutes=1)
            started = time.perf_counter()
            produce_big(built.project, built.v1.code, data)
            produced = time.perf_counter() - started
            clock.advance(minutes=1)
            yield BigProject(built.project, Path(folder), clock, built.v1.uid, data, produced)
        finally:
            built.project.close()


# --- RNF-009-01: el proyecto de D-13 con versiones ----------------------------------------------

STEP_OP = f"{d13.MODULE}.version_step"
"""El tipo de versión de prueba de D-13: consume un dato del proyecto y escribe una tabla."""
GROWTH_OP = f"{d13.MODULE}.growth_step"
"""El tipo de versión de prueba del crecimiento: lee un parámetro, escribe dos tablas y da una
cifra."""
VERSIONS = 6
VERSION_OPERATIONS = 10
TABLE_ROWS = 5


@contextmanager
def versions_registered() -> Iterator[None]:
    """Lo de D-13 (``provenance_fixtures.registered``) y los tipos :data:`STEP_OP` y
    :data:`GROWTH_OP`; lo quita al salir."""
    with d13.registered(), ExitStack() as stack:
        for op_type, label in ((STEP_OP, "Version step"), (GROWTH_OP, "Growth step")):
            contract.register_operation(contract.OperationDef(
                op_type, "1.0", d13.MODULE, label, False, scope="version"))
            stack.callback(contract.unregister_operation, op_type)
        yield


def write_tables(project: Any, names: Sequence[str], seed: float,
                 rows: int = TABLE_ROWS) -> list[Any]:
    """Escribe las tablas ``names`` (cada una, otro contenido a partir de ``seed``) en su
    transacción y devuelve sus ``DatasetSpec`` con el hash de contenido ya calculado (como
    ``provenance_fixtures.write_output_tables``)."""
    with project.write_transaction() as conn:
        for index, name in enumerate(names):
            base.create_attribute_table(conn, name, [base.ColumnDef("valor", "DOUBLE")], name)
            conn.executemany(f'INSERT INTO "{name}" (valor) VALUES (?)',
                             [(seed + 1000.0 * index + 0.5 * row,) for row in range(rows)])
    specs = []
    with project.read() as conn:
        for index, name in enumerate(names):
            request = builtin.GPKG_LAYER.request(
                "table", dataset_model.DATASET_DECLARATIONS, {"main": project.database_path},
                {"layer": name})
            for _ in builtin.layer_steps(conn, request):
                pass
            specs.append(datasets.DatasetSpec(
                name, d13.MODULE, "table", "gpkg", name, reader=builtin.GPKG_LAYER.id,
                role=f"salida{index}", content=request.hasher.digest()))
    return specs


@dataclass
class Declared:
    """Una versión declarada VIGENTE: la transacción y la cabecera, la transacción sola, el
    ``StatusChange`` y las revisiones cerradas."""

    total_s: float
    write_s: float
    change: Any
    closed: tuple[str, ...]


@dataclass
class D13Versions:
    """El proyecto de :func:`build_d13_versions`, abierto en escritura."""

    built: Any
    codes: list[str]
    version_operations: int
    clock: FakeClock

    @property
    def project(self) -> Any:
        return self.built.project

    @property
    def root(self) -> Path:
        return self.built.root

    def declare(self, code: str) -> Declared:
        """Declara VIGENTE la versión ``code`` un minuto después, como su orden: la transacción
        (``set_status``) y la cabecera."""
        self.clock.advance(minutes=1)
        project = self.project
        started = time.perf_counter()
        with project.write_transaction() as conn:
            change = vstore.set_status(conn, project, code, "VIGENTE")
        written = time.perf_counter() - started
        project.refresh_header()
        total = time.perf_counter() - started
        return Declared(total, written, change, tuple(rev.uid for rev in change.closed))

    def close(self) -> None:
        self.built.close()


def _version_step(built: Any, code: str, chain: int, step: int) -> None:
    project = built.project
    span = d13.PARAMETERS - d13.FIRST_INNER_PARAMETER
    handle = operations.begin_operation(
        project, STEP_OP, settings={"paso": step},
        inputs=[operations.Use(built.leaf(chain), "source")],
        params=[d13.parameter_key(d13.FIRST_INNER_PARAMETER + chain % span)],
        executor="blender", version=code)
    outputs = write_tables(project, [vmodel.version_locator(f"{d13.MODULE}_paso{step:02d}", code)],
                           seed=1000.0 * chain)
    with project.write_transaction() as conn:
        handle.complete(conn, outputs=outputs, software={})


def build_d13_versions(parent: Path, sources: Path, *, versions: int = VERSIONS,
                       operations_per_version: int = VERSION_OPERATIONS) -> D13Versions:
    """El proyecto de D-13 en ``parent`` (sus fuentes en ``sources``) con ``versions`` versiones
    (véase el módulo); la primera, VIGENTE. Necesita :func:`versions_registered`."""
    clock = FakeClock(d13.CLOCK_START)
    built = d13.build_d13(Path(parent), Path(sources), clock=clock)
    try:
        project = built.project
        codes: list[str] = []
        for number_ in range(versions):
            clock.advance(minutes=1)
            version = fixtures.create_version(project, feature=f"alternativa{number_ + 1}",
                                              title=f"Alternativa {number_ + 1}")
            codes.append(version.code)
            for step in range(operations_per_version):
                clock.advance(seconds=1)
                chain = (number_ * operations_per_version + step) % built.chains
                _version_step(built, version.code, chain, step)
            clock.advance(minutes=1)
            now = timeutil.format_utc(clock.now())
            with project.write_transaction() as conn:
                fixtures.freeze_rows(conn, version, now=now, reason="Segunda revisión")
        made = D13Versions(built, codes, operations_per_version, clock)
        made.declare(codes[0])
    except BaseException:
        built.close()
        raise
    return made


# --- RNF-009-03 y 04: 200 revisiones congeladas -------------------------------------------------


@dataclass
class RevisionsProject:
    """El proyecto de :func:`build_revisions`, cerrado: su carpeta (``proyectos/``,
    ``fuentes/`` y ``u/``), el nombre de la del proyecto, el reloj, cuántas revisiones congeladas
    tiene y, de una de ellas, sus ficheros propios, sus datos en otra instantánea y lo que ocupa
    su manifiesto."""

    folder: Path
    name: str
    clock: FakeClock
    versions: int
    per_version: int
    revisions: int
    own_files: int
    other_files: int
    manifest_bytes: int
    build_s: float


def _drain_freeze(project: Any, code: str, reason: str) -> Any:
    outcome = None
    for step in freeze.freeze_steps(project, code, reason=reason):
        if step.result is not None:
            outcome = step.result
    if outcome is None or outcome.frozen is None:
        raise RuntimeError(f"no se congeló la revisión abierta de {code}")
    return outcome


def build_revisions(folder: Path, *, versions: int = 20, per_version: int = 10
                    ) -> RevisionsProject:
    """En ``folder``, el proyecto de la demostración de versiones con ``versions`` versiones de
    ``per_version`` revisiones congeladas de verdad (véase el módulo); lo deja cerrado."""
    folder = Path(folder)
    clock = FakeClock()
    started = time.perf_counter()
    with vdemo.VersionsDemo().registered() as demo:
        built = fixtures.build(folder, demo, clock=clock)
        project = built.project
        try:
            for number_ in range(3, versions + 1):
                clock.advance(minutes=1)
                fixtures.create_version(project, feature=f"alternativa{number_}",
                                        title=f"Alternativa {number_}")
            for number_ in range(1, versions + 1):
                code = f"V{number_:02d}"
                for revision in range(1, per_version + 1):
                    clock.advance(minutes=1)
                    demo.pit(project, code, top_z=500.0 + number_ + revision / 100.0)
                    clock.advance(minutes=1)
                    demo.pit_stockpiles(project, code)
                    clock.advance(minutes=1)
                    _drain_freeze(project, code, f"Revisión {revision + 1}")
        finally:
            project.close()
    root = Path(project.root)
    sample = f"V{max(1, versions // 2):02d}.r{max(1, per_version // 2)}"
    manifest = root / "snapshots" / sample / vmodel.SNAPSHOT_MANIFEST
    body = vmodel.expand_manifest(json.loads(manifest.read_text(encoding="utf-8")))
    others = sum(1 for item in body["datasets"] if item.get("location") == "other")
    return RevisionsProject(folder, root.name, clock, versions, per_version,
                            versions * per_version, len(body["files"]), others,
                            manifest.stat().st_size, time.perf_counter() - started)


@contextmanager
def open_revisions(made: RevisionsProject, folder: Path) -> Iterator[Any]:
    """El proyecto de ``made`` en ``folder`` (el suyo o una copia de ``proyectos/`` y
    ``fuentes/``), abierto en escritura un minuto después con la demostración registrada y sus
    datos de usuario; al salir lo cierra."""
    made.clock.advance(minutes=1)
    with vdemo.VersionsDemo().registered():
        project = open_mod.open_project(
            Path(folder) / "proyectos" / made.name, fixtures.SESSION,
            userdata_mod.UserData(made.folder / "u"), clock=made.clock,
            pid_alive=fixtures.PIDS).project
        try:
            yield project
        finally:
            project.close()


@dataclass
class CheckRun:
    """Una comprobación de apertura: su total, lo que sumó el paso «instantáneas» y su llamada
    más larga, cuántas revisiones comprueba la rápida y las alteradas o que cambian."""

    total_s: float
    phase_s: float
    longest_s: float
    revisions: int
    altered: tuple[str, ...] = field(default_factory=tuple)


def open_check(project: Any) -> CheckRun:
    """La comprobación de apertura entera de ``project`` (``open_check_steps``, en escritura)
    llevada por pasos; después, sin medir, cuántas revisiones comprueba la rápida."""
    phase: list[float] = []
    outcome = None
    started = time.perf_counter()
    steps = checks.open_check_steps(project, write=True)
    while True:
        before = time.perf_counter()
        try:
            step = next(steps)
        except StopIteration:
            break
        spent = time.perf_counter() - before
        if step.phase == vcheck.PHASE:
            phase.append(spent)
        if step.result is not None:
            outcome = step.result
    total = time.perf_counter() - started
    found = _findings(vcheck.quick_steps(project))
    altered = tuple(finding.label for finding in getattr(outcome, "snapshots", ()))
    altered += tuple(finding.label for finding in found if finding.altered)
    return CheckRun(total, sum(phase), max(phase, default=0.0), len(found), altered)


def _findings(steps: Any) -> tuple[Any, ...]:
    while True:
        try:
            next(steps)
        except StopIteration as stop:
            return tuple(stop.value)


# --- RNF-009-06: el crecimiento -----------------------------------------------------------------


def growth_operations(elements: int) -> int:
    """Las operaciones de :data:`GROWTH_OP` que hacen una revisión de ``elements`` elementos:
    cuatro por operación (ella, sus dos tablas y su cifra) más los parámetros que leen (uno
    cada una, como mucho los :data:`provenance_fixtures.PARAMETERS` de D-13).
    :class:`ValueError` si no sale un número entero."""
    if elements % 5 == 0 and elements // 5 <= d13.PARAMETERS:
        return elements // 5
    rest = elements - d13.PARAMETERS
    if rest > 4 * d13.PARAMETERS and rest % 4 == 0:
        return rest // 4
    raise ValueError(f"{elements} elementos no salen de operaciones de cuatro elementos y "
                     f"un parámetro cada una")


def _growth_step(project: Any, code: str, index: int, seed: float) -> None:
    handle = operations.begin_operation(
        project, GROWTH_OP, settings={"paso": index},
        params=[d13.parameter_key(index % d13.PARAMETERS)], executor="blender", version=code)
    names = [vmodel.version_locator(f"{d13.MODULE}_g{index:04d}_{part}", code)
             for part in range(2)]
    outputs = write_tables(project, names, seed)
    figure = figures_mod.FigureSpec(d13.FIGURE_KEY, seed, "t", scope={"paso": index})
    with project.write_transaction() as conn:
        handle.complete(conn, outputs=outputs, figures=[figure], software={})


@dataclass
class GrowthProject:
    """El proyecto de :func:`growth_project`, abierto en escritura: sus versiones (una por
    número de elementos) con su r1 congelada y su r2 abierta."""

    project: Any
    clock: FakeClock
    codes: list[str]
    elements: list[int]
    build_s: float

    @property
    def root(self) -> Path:
        return Path(self.project.root)


@contextmanager
def growth_project(folder: Path, elements: Sequence[int]) -> Iterator[GrowthProject]:
    """En ``folder``, un proyecto nuevo con una versión por cada número de ``elements``, hecha
    de :func:`growth_operations` operaciones de :data:`GROWTH_OP` (véase el módulo) y con su r1
    congelada; al salir lo cierra (la carpeta es de quien la dio)."""
    folder = Path(folder)
    clock = FakeClock()
    started = time.perf_counter()
    with versions_registered():
        parent = folder / "proyectos"
        parent.mkdir()
        project = create.create_project(parent, make_settings(), fixtures.SESSION,
                                        userdata_mod.UserData(folder / "u"),
                                        clock=clock).project
        try:
            codes: list[str] = []
            for number_, wanted in enumerate(elements, start=1):
                clock.advance(minutes=1)
                version = fixtures.create_version(project, feature=f"crecimiento{number_}",
                                                  title=f"Crecimiento {number_}")
                codes.append(version.code)
                for index in range(growth_operations(wanted)):
                    clock.advance(seconds=1)
                    _growth_step(project, version.code, index, 1e6 * number_ + 10.0 * index)
                clock.advance(minutes=1)
                plan = freeze.freeze_plan(project, version.code)
                for _ in freeze.freeze_steps(project, version.code, reason="Sin cambios",
                                             accepted=freeze.Acceptance.of(plan)):
                    pass
            yield GrowthProject(project, clock, codes, list(elements),
                                time.perf_counter() - started)
        finally:
            project.close()


@dataclass
class Grown:
    """Lo que creció el proyecto al congelar una revisión sin cambios (RNF-009-06)."""

    label: str
    elements: int
    kinds: str
    copied_bytes: int
    grown_bytes: int
    database_bytes: int
    manifest_bytes: int


_KIND_NAMES = {"operation": "operaciones", "dataset": "datos", "figure": "cifras",
               "parameter": "parámetros", "input": "entradas"}


def freeze_unchanged(made: GrowthProject, code: str) -> Grown:
    """Congela sin cambiar nada la revisión abierta de ``code`` y mide lo que crece la carpeta
    del proyecto sin su caché, su base y el manifiesto de la instantánea."""
    project = made.project
    root = made.root
    made.clock.advance(minutes=1)
    plan = freeze.freeze_plan(project, code)
    database = Path(project.database_path)
    before = folder_size(root)
    database_before = database.stat().st_size
    outcome = None
    for step in freeze.freeze_steps(project, code, reason="Sin cambios",
                                    accepted=freeze.Acceptance.of(plan)):
        if step.result is not None:
            outcome = step.result
    if outcome is None or outcome.frozen is None:
        raise RuntimeError(f"no se congeló la revisión abierta de {code}")
    grown = folder_size(root) - before
    manifest = root / outcome.frozen.snapshot_dir / vmodel.SNAPSHOT_MANIFEST
    with project.read() as conn:
        kinds = Counter(str(kind) for (kind,) in conn.execute(
            "SELECT item_kind FROM gb_revision_item WHERE revision_uid = ?",
            (outcome.frozen.uid,)))
    text = ", ".join(f"{count(kinds[kind])} {_KIND_NAMES.get(kind, kind)}"
                     for kind in sorted(kinds, key=lambda kind: -kinds[kind]))
    return Grown(outcome.label, sum(kinds.values()), text, outcome.copied_bytes, grown,
                 database.stat().st_size - database_before, manifest.stat().st_size)

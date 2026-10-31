# SPDX-License-Identifier: GPL-3.0-or-later
"""Los datos de escala de la 012 (``plan.md`` §2.2; spec 012, T35; RNF-012-01 a RNF-012-06).

Se generan aquí y no se versionan (semilla :data:`SEED`, ningún dato de cliente): la rejilla de
:data:`COLS` × :data:`ROWS` celdas de 1 m (2,81 M) y, en un proyecto sintético, las
:data:`COUNT` restricciones de §2.2 con unos 100.000 vértices:

- el límite legal y el perímetro, de 2.000 vértices cada uno (estrellas de radio casi constante);
- 30 puntos, 30 líneas de 200 vértices y 40 polígonos de 500 con un resguardo de 5 a 50 m, de los
  tipos que lo piden (intocable, exclusión, resguardo, «preferible no afectar» y «sin relleno»);
- 398 polígonos de 176 vértices sin resguardo (los otros cinco tipos).

:func:`scale_project` los deja escritos en un proyecto en disco local, con V01 y V02, los
parámetros dados de alta y lo que registrará ``bl`` (las pruebas de compilar y de verificar lo
miden de ``begin`` a las cifras). Para verificar (T36): :func:`write_surfaces` escribe en él la
superficie de partida y tres finales, de las dos formas de §2.2 (:data:`WINDOW`, que cambian en
toda la ventana, y :data:`LOCAL`, que cambian en unos abultamientos) y :func:`verify_registered`
registra lo que hará ``bl`` para verificar. Para buscar intocables (T37): :func:`write_search`
escribe en él las :data:`SEARCH_LAYERS` capas «entidades» de :data:`SEARCH_ENTITIES` entidades y
declara un sector de 400 vértices que ocupa un cuarto de la ventana, dentro de
:func:`search_registered`. Python de Blender (su numpy 2.3.4) y biblioteca estándar.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as fx
from tests.support import constraints_project as cp
from tests.support.core_fixtures import FakeClock, make_session, make_settings, project_tmp
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.res_fixtures import write_grids

cmodel = import_geoblender("core.constraints.model")
cparams = import_geoblender("core.constraints.params")
cstore = import_geoblender("core.constraints.store")
userdata_mod = import_geoblender("core.userdata")
versions_store = import_geoblender("core.versions.store")
create = import_geoblender("core.project.create")
gis = import_geoblender("gis")
params_mod = import_geoblender("core.params")
cstore_v = import_geoblender("reserves.compliance_store")
surfaces_mod = import_geoblender("reserves.surfaces")

T = cmodel.ConstraintType
G = cmodel.GeometryKind

WEST, SOUTH = 699_000.0, 4_399_000.0
COLS, ROWS = 1654, 1699
STEP_M = 1.0
EAST, NORTH = WEST + COLS * STEP_M, SOUTH + ROWS * STEP_M
SEED = 20_261_031
COUNT = 500
PERSON = "Samuel (IMGA)"
SESSION = make_session()


def window() -> tuple[float, float, float, float]:
    """La ventana del proyecto de escala: (oeste, sur, este, norte)."""
    return (WEST, SOUTH, EAST, NORTH)


def grid() -> Any:
    """La rejilla de 1 m del proyecto de escala."""
    return gis.Grid(WEST, NORTH, STEP_M, STEP_M, COLS, ROWS)


# --- Las restricciones --------------------------------------------------------------------------


def star(rng: np.random.Generator, cx: float, cy: float, radius: float, n: int,
         jitter: float = 0.3) -> np.ndarray:
    """Un anillo cerrado y antihorario de ``n`` vértices (simple: radio positivo a ángulos
    crecientes)."""
    step = 2.0 * math.pi / n
    angles = np.arange(n) * step + (rng.random(n) - 0.5) * 0.6 * step
    radii = radius * (1.0 + jitter * (rng.random(n) - 0.5) * 2.0)
    ring = np.column_stack([cx + radii * np.cos(angles), cy + radii * np.sin(angles)])
    return np.vstack([ring, ring[:1]])


def path(rng: np.random.Generator, x: float, y: float, n: int, length: float) -> np.ndarray:
    """Una línea de ``n`` vértices que empieza en (``x``, ``y``) y gira poco (``length`` m)."""
    heading = rng.uniform(0, 2 * math.pi)
    steps = length / (n - 1)
    turns = np.cumsum((rng.random(n - 1) - 0.5) * 0.4) + heading
    xy = np.column_stack([np.cumsum(np.cos(turns)) * steps, np.cumsum(np.sin(turns)) * steps])
    return np.vstack([[x, y], np.array([x, y]) + xy])


@dataclass(frozen=True, slots=True)
class ScaleConstraints:
    """Las restricciones de §2.2 (``rows``, nuevas, ``fid`` 0), los valores de sus parámetros
    de proyecto (clave → valor) y sus vértices."""

    rows: tuple[Any, ...]
    values: dict[str, Any]
    vertices: int


def build_constraints(rng: np.random.Generator | None = None) -> ScaleConstraints:
    """Las 500 restricciones de §2.2 con ``rng`` (por defecto, la semilla :data:`SEED`): el
    límite legal (10 m hacia dentro) y el perímetro, 30 puntos, 30 líneas y 40 polígonos con
    resguardo de 5 a 50 m y 398 polígonos sin él."""
    rng = np.random.default_rng(SEED) if rng is None else rng
    rows: list[Any] = []
    values: dict[str, Any] = {}
    taken: set[str] = set()
    vertices = 0
    cx, cy = (WEST + EAST) / 2.0, (SOUTH + NORTH) / 2.0

    def add(name: str, ctype: Any, kind: Any, part: np.ndarray, buffer_out: float | None,
            buffer_in: float | None = None, weight: float | None = None) -> None:
        nonlocal vertices
        code = cmodel.constraint_code(name, taken)
        taken.add(code)
        rows.append(cmodel.Constraint(
            uid=f"{len(rows):032x}", code=code, name=name, ctype=ctype, kind=kind,
            parts=((part,),), priority=0, reason="Restricción sintética de rendimiento",
            decided_by=PERSON, decided_on=date(2026, 10, 31), decision_uid=None,
            intention_uid=None, source_input=None, source_fid=None,
            layer=cstore.layer_of(kind), fid=0))
        vertices += len(part)
        values[cparams.active_key(code)] = True
        if buffer_out is not None:
            values[cparams.buffer_out_key(code)] = float(buffer_out)
        if buffer_in is not None:
            values[cparams.buffer_in_key(code)] = float(buffer_in)
        if weight is not None and ctype is T.AVOID:
            values[cparams.weight_key(code)] = float(weight)

    add("Concesión", T.LEGAL_LIMIT, G.POLYGON, star(rng, cx, cy, 760.0, 2000, 0.06), None, 10.0)
    add("Perímetro", T.ACTION_PERIMETER, G.POLYGON,
        star(rng, cx + 40, cy - 30, 640.0, 2000, 0.08), None)
    buffered = (T.UNTOUCHABLE, T.EXCLUSION, T.SETBACK, T.AVOID, T.NO_FILL)
    plain = (T.NO_CUT, T.NO_FILL, T.FILL_ONLY, T.RESTORATION_ONLY, T.REQUIRES_ACCESS)

    def at() -> tuple[float, float]:
        return (float(rng.uniform(WEST + 120, EAST - 120)),
                float(rng.uniform(SOUTH + 120, NORTH - 120)))

    for index in range(30):
        x, y = at()
        add(f"Punto {index:02d}", buffered[index % 5], G.POINT, np.array([[x, y]]),
            float(rng.uniform(5, 50)), weight=2.0)
    for index in range(30):
        x, y = at()
        add(f"Línea {index:02d}", buffered[index % 5], G.LINE, path(rng, x, y, 200, 300.0),
            float(rng.uniform(5, 50)), weight=2.0)
    for index in range(40):
        x, y = at()
        add(f"Zona {index:02d}", buffered[index % 5], G.POLYGON,
            star(rng, x, y, float(rng.uniform(30, 120)), 500), float(rng.uniform(5, 50)),
            weight=2.0)
    for index in range(398):
        x, y = at()
        add(f"Recinto {index:03d}", plain[index % 5], G.POLYGON,
            star(rng, x, y, float(rng.uniform(10, 60)), 176), 0.0)
    return ScaleConstraints(tuple(rows), values, vertices)


# --- El proyecto --------------------------------------------------------------------------------


@dataclass(slots=True)
class ScaleProject:
    """Un proyecto de escala abierto: el proyecto, su reloj, V01 y V02 (``versions``), el
    SRS de sus capas y las restricciones que se le escribieron."""

    project: Any
    clock: FakeClock
    versions: tuple[Any, Any]
    srs_id: int
    constraints: ScaleConstraints

    @property
    def v1(self) -> Any:
        """V01 («Máscaras»)."""
        return self.versions[0]

    @property
    def v2(self) -> Any:
        """V02 («Alternativa»)."""
        return self.versions[1]


@contextmanager
def scale_project(constraints: ScaleConstraints | None = None) -> Iterator[ScaleProject]:
    """Un proyecto nuevo en una carpeta temporal de disco local, con V01 y V02, las
    restricciones de §2.2 escritas (``constraints``; por defecto :func:`build_constraints`) y sus
    parámetros dados de alta en el proyecto, con lo que registrará ``bl`` para compilar. Al salir
    lo cierra y borra la carpeta."""
    made = build_constraints() if constraints is None else constraints
    with ExitStack() as stack:
        stack.enter_context(cp.constraints_registered())
        folder = stack.enter_context(project_tmp("gb-escala-"))
        clock = FakeClock()
        (folder / "proyectos").mkdir()
        settings = make_settings(window=window(), grid_step_m=STEP_M)
        project = create.create_project(folder / "proyectos", settings, SESSION,
                                        userdata_mod.UserData(folder / "u"), clock=clock).project
        stack.callback(project.close)
        versions = []
        for feature, title in (("mascaras", "Máscaras"), ("alternativa", "Alternativa")):
            clock.advance(minutes=1)
            with project.write_transaction() as conn:
                version, _revision = versions_store.create_version(
                    conn, project, feature=feature, title=title, reason="Escala de la 012")
            project.refresh_header()
            versions.append(version)
        clock.advance(minutes=1)
        cp.edit_constraints(project, made.rows)
        cp.declare(project, clock, made.values)
        clock.advance(minutes=1)
        yield ScaleProject(project, clock, (versions[0], versions[1]),
                           int(project.record.crs_epsg), made)


# --- Las superficies de verificar ----------------------------------------------------------------

WINDOW = "window"
"""Las finales que cambian en toda la ventana (ondas de 3 m): pocos grupos grandes por recinto."""
LOCAL = "local"
"""Las finales que cambian solo en 8 abultamientos de ±3 m: muchos grupos pequeños."""
FINALS = 3
"""Las superficies finales de cada forma."""


def _plane() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x = np.arange(COLS)[None, :].astype(np.float64)
    y = np.arange(ROWS)[:, None].astype(np.float64)
    return x, y, 650.0 + 0.02 * x + 0.01 * y


def surface(rng: np.random.Generator, kind: int) -> Any:
    """La partida (``kind`` 0, el plano inclinado) y las finales (1 a 3) de la forma
    :data:`WINDOW`: el plano con una onda de 3 m en toda la ventana y 5 mm de ruido."""
    x, y, base = _plane()
    if kind:
        base = base + 3.0 * np.sin(x / (150.0 + 40 * kind)) * np.cos(y / (170.0 + 30 * kind))
        base = base + (rng.random((ROWS, COLS)) - 0.5) * 0.01
    return gis.Raster(grid(), base, fx.CRS, fx.VERTICAL)


def local_surface(rng: np.random.Generator) -> Any:
    """Una superficie de la forma :data:`LOCAL`: el plano con 8 abultamientos de ±3 m (σ de 25
    m) y 5 mm de ruido en toda la ventana (la partida y cada final, con otro azar)."""
    x, y, base = _plane()
    for _ in range(8):
        cx, cy = rng.uniform(150, COLS - 150), rng.uniform(150, ROWS - 150)
        amplitude = rng.choice([-3.0, 3.0])
        base = base + amplitude * np.exp(-((x - cx) ** 2 + (y - cy) ** 2) / (2 * 25.0**2))
    base = base + (rng.random((ROWS, COLS)) - 0.5) * 0.01
    return gis.Raster(grid(), base, fx.CRS, fx.VERTICAL)


@dataclass(frozen=True, slots=True)
class ScaleSurfaces:
    """Las superficies de una forma (:data:`WINDOW` o :data:`LOCAL`) escritas en el proyecto:
    la partida y las :data:`FINALS` finales, como ``SurfaceRef``."""

    shape: str
    start: Any
    finals: tuple[Any, ...]


def write_surfaces(data: ScaleProject, shape: str) -> ScaleSurfaces:
    """Escribe en ``data.project`` la partida y las tres finales de la forma ``shape`` como
    rejillas del proyecto (``gis_dtm_partida_<forma>``, ``gis_dtm_final_<forma>_<k>``)."""
    if shape not in (WINDOW, LOCAL):
        raise ValueError(f"la forma de las finales es «{WINDOW}» o «{LOCAL}», no {shape!r}")
    seed = SEED + (0 if shape == WINDOW else 100)
    if shape == WINDOW:
        rng = np.random.default_rng(seed)
        rasters = [surface(rng, kind) for kind in range(FINALS + 1)]
    else:
        rasters = [local_surface(np.random.default_rng(seed + kind)) for kind in range(FINALS + 1)]
    names = [f"partida_{shape}", *(f"final_{shape}_{k}" for k in range(1, FINALS + 1))]
    data.clock.advance(minutes=1)
    write_grids(data.project, list(zip(names, rasters, strict=True)),
                message=f"Superficies de escala ({shape})")
    ref = surfaces_mod.SurfaceRef
    return ScaleSurfaces(
        shape, ref(dataset=f"gis_dtm_{names[0]}", label="Partida"),
        tuple(ref(dataset=f"gis_dtm_{name}", label=f"Final {k}")
              for k, name in enumerate(names[1:], start=1)))


def _no_recompute(request: Any) -> Any:
    raise AssertionError("las pruebas de escala no recalculan con la función de bl")


# --- Las capas de buscar intocables --------------------------------------------------------------

SEARCH_LAYERS = 10
"""Las capas «entidades» de la búsqueda (las que admite una búsqueda, de §2.2)."""
SEARCH_ENTITIES = 10_000
"""Las entidades de cada capa: 3 de puntos, 4 de líneas de 10 vértices y 3 de polígonos de 8."""
SEARCH_SECTOR_VERTICES = 400
SEARCH_DISTANCE_M = 25.0
"""La distancia de búsqueda de §2.2 (el valor por defecto del parámetro)."""
LAYERS_TYPE = "gis.test_layers"
"""La operación de prueba de ``gis`` que escribe las capas (hace lo que la importación de la 006
con el papel «entidades»)."""
SECTORS_LAYER = "gis_fea_sectores_escala"
SECTOR_CODE = "sector_1"


def _search_layer(rng: np.random.Generator, index: int, count: int) -> Any:
    """La capa ``index`` de la búsqueda: puntos (0 a 2), líneas de 10 vértices cada 6 m (3 a 6) o
    polígonos de 8 vértices y 12 m de radio (7 a 9), con un campo de texto «nombre»."""
    vector = import_geoblender("gis.vector")
    px = rng.uniform(WEST, EAST, count)
    py = rng.uniform(SOUTH, NORTH, count)
    if index < 3:
        kind = "point"
        parts = tuple(((np.array([[px[i], py[i]]]),),) for i in range(count))
    elif index < 7:
        kind = "line"
        angles = rng.uniform(0, 2 * math.pi, count)
        parts = tuple(((np.column_stack([px[i] + np.arange(10) * 6.0 * math.cos(angles[i]),
                                         py[i] + np.arange(10) * 6.0 * math.sin(angles[i])]),),)
                      for i in range(count))
    else:
        kind = "polygon"
        parts = tuple(((star(rng, px[i], py[i], 12.0, 8),),) for i in range(count))
    return vector.FeatureLayer(
        kind, tuple(range(1, count + 1)), parts, (vector.FieldColumn("nombre", "nombre", "TEXT"),),
        {"nombre": tuple(f"Entidad {i}" for i in range(count))})


def build_search_layers(rng: np.random.Generator | None = None, *,
                        count: int = SEARCH_ENTITIES) -> tuple[dict[str, Any], np.ndarray]:
    """Las :data:`SEARCH_LAYERS` capas de ``count`` entidades (``{nombre del dato: capa}``) y el
    sector de :data:`SEARCH_SECTOR_VERTICES` vértices (un anillo absoluto: un cuarto de la
    ventana, centrado al 30 %) con ``rng`` (por defecto, la semilla :data:`SEED` + 1)."""
    rng = np.random.default_rng(SEED + 1) if rng is None else rng
    layers = {f"gis_fea_capa_{index}": _search_layer(rng, index, count)
              for index in range(SEARCH_LAYERS)}
    sector = star(rng, WEST + COLS * 0.30, SOUTH + ROWS * 0.30, 400.0, SEARCH_SECTOR_VERTICES, 0.1)
    return layers, sector


@dataclass(frozen=True, slots=True)
class ScaleSearch:
    """Las capas de la búsqueda escritas en el proyecto: sus nombres (datos ``gis_fea_``), el
    sector declarado (``sector_code``, su anillo absoluto) y las entidades de cada capa."""

    layers: tuple[str, ...]
    sector_code: str
    sector: np.ndarray
    entities: int


@contextmanager
def search_registered() -> Iterator[None]:
    """Registra lo que hará ``bl`` para buscar intocables: las operaciones de ``core`` de las
    restricciones (declarar sectores y cerrar la búsqueda), la de prueba de las capas
    (:data:`LAYERS_TYPE`) y la distancia de búsqueda. Al salir, lo quita."""
    contract = import_geoblender("core.provenance.contract")
    cprov = import_geoblender("core.constraints.provenance")
    layers = contract.OperationDef(LAYERS_TYPE, "1.0", "gis", "Layers of the tests", False)
    core_ops = [item for item in contract.CORE_OPERATIONS
                if item.op_type not in contract.OPERATIONS]
    with ExitStack() as stack:
        stack.enter_context(registered(layers, *cprov.OPERATIONS, *core_ops))
        if cparams.SEARCH_DISTANCE.key not in params_mod.DEFINITIONS:
            kept = [item for item in params_mod.DEFINITIONS.values() if item.module == "core"]
            params_mod.register_definitions(cparams.DEFINITIONS)

            def restore() -> None:
                params_mod.unregister_definitions("core")
                params_mod.register_definitions(kept)

            stack.callback(restore)
        yield


def write_feature_layer(data: ScaleProject, name: str, layer: Any) -> None:
    """:data:`LAYERS_TYPE`: escribe la capa ``layer`` como el dato ``name`` (``gis_fea_``) del
    proyecto y lo registra (la tabla, su fila de ``gpkg_contents`` y sus columnas de geometría)."""
    datasets = import_geoblender("core.datasets")
    builtin = import_geoblender("core.content.builtin")
    operations = import_geoblender("core.provenance.operations")
    gstore = import_geoblender("gis.store")
    srs = data.srs_id
    data.clock.advance(minutes=1)
    handle = operations.begin_operation(data.project, LAYERS_TYPE, settings={"name": name},
                                        executor="blender")
    rows = gstore.feature_rows(layer, srs)
    columns = [column.column for column in layer.columns]
    with data.project.write_transaction() as conn:
        extra = "".join(f', "{column}" TEXT' for column in columns)
        conn.execute(f'CREATE TABLE "{name}" (fid INTEGER PRIMARY KEY NOT NULL, '
                     f'geom {layer.geometry_type}{extra})')
        conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, description, "
                     "srs_id) VALUES (?, 'features', ?, '', ?)", (name, name, srs))
        conn.execute("INSERT INTO gpkg_geometry_columns (table_name, column_name, "
                     "geometry_type_name, srs_id, z, m) VALUES (?, 'geom', ?, ?, 0, 0)",
                     (name, layer.geometry_type, srs))
        marks = ", ".join("?" for _ in range(len(columns) + 2))
        names = "".join(f', "{column}"' for column in columns)
        conn.executemany(f'INSERT INTO "{name}" (fid, geom{names}) VALUES ({marks})', rows)
        handle.complete(conn, outputs=(datasets.DatasetSpec(
            name, "gis", "vector", datasets.Store.GPKG, name, reader=builtin.GPKG_LAYER.id,
            role="features", crs_epsg=srs, input_uid=None, immutable=False),),
            message="Capa de prueba")


def write_search(data: ScaleProject, *, count: int = SEARCH_ENTITIES) -> ScaleSearch:
    """Escribe en ``data.project`` las capas de la búsqueda (:func:`build_search_layers`) y la
    capa del sector, y declara el sector (``sector_1``, en V01). Dentro de
    :func:`search_registered`."""
    vector = import_geoblender("gis.vector")
    sectors = import_geoblender("gis.masks.sectors")
    layers, sector = build_search_layers(count=count)
    for name, layer in layers.items():
        write_feature_layer(data, name, layer)
    write_feature_layer(data, SECTORS_LAYER, vector.FeatureLayer(
        "polygon", (1,), (((sector,),),), (vector.FieldColumn("sector", "sector", "TEXT"),),
        {"sector": ("Sector 1",)}))
    data.clock.advance(minutes=1)
    declared = sectors.declare_sectors(data.project, SECTORS_LAYER, "sector",
                                       version=data.v1.uid)
    if tuple(item.code for item in declared.sectors) != (SECTOR_CODE,):
        raise AssertionError(f"el sector declarado no es «{SECTOR_CODE}»: {declared.sectors!r}")
    return ScaleSearch(tuple(layers), SECTOR_CODE, sector, count)


@contextmanager
def verify_registered() -> Iterator[None]:
    """Registra lo que hará ``bl`` para verificar: ``res.verify_constraints`` (con su función
    de reproducir), sus cifras y su espesor mínimo. Al salir, lo quita."""
    with ExitStack() as stack:
        stack.enter_context(registered(
            cstore_v.operation_def(_no_recompute, cstore_v.REPRODUCE[cstore_v.VERIFY]),
            *cstore_v.FIGURES))
        if cstore_v.MIN_THICKNESS not in params_mod.DEFINITIONS:
            kept = [item for item in params_mod.DEFINITIONS.values() if item.module == "res"]
            params_mod.register_definitions(cstore_v.DEFINITIONS)

            def restore() -> None:
                params_mod.unregister_definitions("res")
                params_mod.register_definitions(kept)

            stack.callback(restore)
        yield

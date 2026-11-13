# SPDX-License-Identifier: GPL-3.0-or-later
"""La cantera sintética de la cantera con dos superficies (spec 014, T01; plan 014 §7.1; hito H2;
E1 a E7; CE-014-01 a CE-014-08).

Todo es sintético (ningún dato de cliente), en coordenadas **absolutas** float64 (EPSG:25830 +
EPSG:5782) desde la esquina :data:`BASE` de ``tests.support.constraints_fixtures``, sobre las ayudas
de ``tests.support.design_fixtures`` (013) y ``tests.support.constraints_project`` (012). Las
coordenadas «locales» son metros desde :data:`BASE` (``x`` al este, ``y`` al norte); en las
rejillas, la fila 0 es el norte. Cada función que da un array da uno **nuevo**.

- **La rejilla** (:data:`GRID`): 400 × 400 celdas de 1 m, de (0, 0) a (400, 400) locales; y la
  gruesa (:func:`grid_of` con :data:`COARSE_STEP_M`), 200 × 200 celdas de 2 m con la misma
  extensión, para las historias de las operaciones (T35; plan 014 §7.4).
- **El terreno de partida** (:func:`terrain`): una ladera que sube al norte y al este,
  ``180 + 0,25·y + 0,0625·x`` (m, exacta en binario en los centros de celda), con un **escarpe
  previo de 3 m** al norte de ``y = 300`` (:data:`SCARP_Y`, :data:`SCARP_M`; CE-014-06).
- **Las restricciones de la 012** (:func:`constraints`): «Concesión» (límite legal de (40, 40) a
  (360, 360), 102.400 m², con 5 m hacia dentro), «Perímetro» (de (20, 60) a (360, 340), 95.200
  m²: su franja fuera del límite, de (20, 60) a (40, 340), 5.600 m²), «Torre» (intocable puntual
  en la esquina de celda (300, 120) con **8 m** de resguardo: 224 celdas, :data:`TOWER_ZONE_CELLS`)
  y «Sin corte» (un rectángulo de (60, 280) a (100, 320) sin resguardo: 1.600 celdas). Dos sectores
  de búsqueda (:data:`SECTORS_LOCAL`) que cubren el perímetro, con sus búsquedas **cerradas**.
- **Las capas del proyecto** (§5.2.1 del plan; :data:`LAYERS`): dos fondos (:data:`FLOORS`: 125 m
  en 80 × 80 m y 175 m en 80 × 60 m), una zona a conservar, un corredor de **200 m de eje** (una
  polilínea de 120 + 80 m) y **20 m** de ancho con su rasante (125 m al 8 %), una zona de
  restauración por relleno y una lámina de agua a 270 m.
- **Los perfiles** (:data:`PROFILES`): ``EXPL_10_60_6`` (la explotación) y ``REST_5_35_6`` (la
  final), los de la 013 con ancla 125 m.
- **El proyecto de la cantera** (:func:`project_template`, :class:`QuarryProjectCase`): V01 y V02,
  la ventana de :data:`GRID` con paso 1 m, las restricciones, los sectores con sus búsquedas
  cerradas, el terreno como rejilla del proyecto (:data:`START_DATASET`), las capas y las máscaras
  de V01 compiladas (V02 sin compilar). Se crea **una vez por proceso** y paso de rejilla (en
  ≤ 2 s de CPU, :data:`BUILD_BUDGET_S`) y cada clase trabaja en su copia.

Las áreas y celdas de la docstring de cada constante están hechas a mano; las comprueba
``tests/unit/design/test_quarry_fixtures.py``.
"""

from __future__ import annotations

import atexit
import shutil
import tempfile
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import constraints_project as cp
from tests.support import design_fixtures as dfx
from tests.support.core_fixtures import FakeClock, FakePids, make_settings, project_tmp
from tests.support.package import import_geoblender

gis = import_geoblender("gis")
cmodel = import_geoblender("core.constraints.model")
cparams = import_geoblender("core.constraints.params")

CRS = cfx.CRS
"""El CRS de la cantera (ETRS89 / UTM 30N)."""
VERTICAL = cfx.VERTICAL
"""La referencia vertical de las superficies (Alicante)."""
BASE: tuple[float, float] = cfx.BASE
"""La esquina suroeste de la cantera (m, absoluta)."""

STEP_M = 1.0
"""El paso de la rejilla de la cantera (m)."""
SIZE = 400
"""Celdas por lado de la rejilla."""
GRID = gis.Grid(BASE[0], BASE[1] + SIZE * STEP_M, STEP_M, STEP_M, SIZE, SIZE)
"""La rejilla de la cantera: 400 × 400 celdas de 1 m de (0, 0) a (400, 400) locales."""
COARSE_STEP_M = 2.0
"""El paso de la rejilla gruesa (m): 200 × 200 celdas de 2 m con la extensión de :data:`GRID`
(T35; plan 014 §7.4, las pruebas unitarias en rejillas de ≤ 200 × 200), para las historias de las
operaciones que no comprueban ninguna cifra hecha a mano con celdas de 1 m."""


def grid_of(step_m: float = STEP_M) -> Any:
    """La rejilla de la cantera con celdas de ``step_m`` m y la extensión de :data:`GRID` (de (0, 0)
    a (400, 400) locales): con :data:`STEP_M`, :data:`GRID` misma; con :data:`COARSE_STEP_M`, la
    gruesa. ``ValueError`` si el paso no divide los 400 m del lado."""
    if step_m == STEP_M:
        return GRID
    side_m = SIZE * STEP_M
    cells = round(side_m / step_m)
    if cells < 1 or cells * step_m != side_m:
        raise ValueError(f"El paso de {step_m} m no divide el lado de {side_m} m de la cantera")
    return gis.Grid(BASE[0], BASE[1] + side_m, step_m, step_m, cells, cells)


# --- El terreno ------------------------------------------------------------------------------

TERRAIN_Z0 = 180.0
"""La cota del terreno en la esquina (0, 0) local, sin el escarpe (m)."""
TERRAIN_NORTH = 0.25
"""La pendiente de la ladera hacia el norte (m/m, exacta en binario)."""
TERRAIN_EAST = 0.0625
"""La pendiente de la ladera hacia el este (m/m, exacta en binario)."""
SCARP_Y = 300.0
"""La línea del escarpe previo (``y`` local): las celdas con el centro al norte, 3 m más altas."""
SCARP_M = 3.0
"""La altura del escarpe previo (m; CE-014-06)."""
TERRAIN_MIN_M = 180.15625
"""La cota mínima del terreno, a mano: el centro (0,5, 0,5), 180 + 0,125 + 0,03125."""
TERRAIN_MAX_M = 307.84375
"""La cota máxima, a mano: el centro (399,5, 399,5), 180 + 99,875 + 24,96875 + 3."""


def local_centers(grid: Any = GRID) -> tuple[np.ndarray, np.ndarray]:
    """Las coordenadas LOCALES (m desde :data:`BASE`) de los centros de celda de ``grid`` (por
    defecto :data:`GRID`; una de :func:`grid_of`), de forma ``grid.shape`` (fila 0 al norte)."""
    columns = (np.arange(grid.ncols) + 0.5) * grid.dx
    rows = SIZE * STEP_M - (np.arange(grid.nrows) + 0.5) * grid.dy
    return np.meshgrid(columns, rows)


def in_box(box: tuple[float, float, float, float], grid: Any = GRID) -> np.ndarray:
    """Las celdas de ``grid`` (por defecto :data:`GRID`) con el centro dentro de la caja local
    ``(izquierda, abajo, derecha, arriba)``."""
    x, y = local_centers(grid)
    left, bottom, right, top = box
    return (x > left) & (x < right) & (y > bottom) & (y < top)


def terrain(grid: Any = GRID) -> np.ndarray:
    """El terreno de partida en los centros de ``grid`` (por defecto :data:`GRID`; m, float64,
    exacto en binario): ``180 + 0,25·y + 0,0625·x`` más :data:`SCARP_M` al norte de
    :data:`SCARP_Y`."""
    x, y = local_centers(grid)
    return TERRAIN_Z0 + TERRAIN_NORTH * y + TERRAIN_EAST * x + np.where(y > SCARP_Y, SCARP_M, 0.0)


def start_raster(grid: Any = GRID) -> Any:
    """El terreno de partida como ``gis.Raster`` de ``grid`` (por defecto :data:`GRID`)."""
    return gis.Raster(grid, terrain(grid), CRS, VERTICAL)


# --- Las restricciones de la 012 -------------------------------------------------------------

LEGAL_LOCAL = (40.0, 40.0, 360.0, 360.0)
"""El límite legal «Concesión» (local: izquierda, abajo, derecha, arriba): 320 × 320 m."""
LEGAL_INWARD_M = 5.0
"""El resguardo hacia dentro del límite legal (m; valor de prueba)."""
PERIMETER_LOCAL = (20.0, 60.0, 360.0, 340.0)
"""El perímetro de actuación (local): 340 × 280 m, con 20 m fuera del límite al oeste."""
TOWER_LOCAL = (300.0, 120.0)
"""La torre (local): una esquina de celda dentro del recinto."""
TOWER_OUTWARD_M = 8.0
"""El resguardo de la torre como intocable (m; valor de prueba, D-5 de la 012)."""
NO_CUT_LOCAL = (60.0, 280.0, 100.0, 320.0)
"""La zona «sin corte» (local), sin resguardo: 40 × 40 m."""
SECTORS_LOCAL: Mapping[str, tuple[float, float, float, float]] = {
    "Sector oeste": (20.0, 60.0, 190.0, 340.0),
    "Sector este": (190.0, 60.0, 360.0, 340.0),
}
"""Los dos sectores de búsqueda (local), sin solapes, que cubren el perímetro."""

LEGAL_AREA_M2 = 102_400.0
"""El área del límite legal: 320 · 320."""
PERIMETER_AREA_M2 = 95_200.0
"""El área del perímetro: 340 · 280."""
INTERSECTION_M2 = 89_600.0
"""Perímetro ∩ límite: de (40, 60) a (360, 340), 320 · 280."""
STRIP_M2 = 5_600.0
"""La franja de solo relleno (perímetro ∖ límite): de (20, 60) a (40, 340), 20 · 280."""
INWARD_BAND_M2 = 2_800.0
"""El resguardo hacia dentro del límite dentro del perímetro: las bandas de 5 m del oeste
(x de 40 a 45) y del este (x de 355 a 360), 2 · 5 · 280 (las del sur y el norte quedan fuera del
perímetro)."""
TOWER_ZONE_CELLS = 224
"""Las celdas de 1 m de la zona de la torre con 8 m: las que tocan el disco abierto de 8 m de un
punto en una esquina, por cuadrante ``i² + j² < 64`` (8, 8, 8, 8, 7, 7, 6 y 4 por columna: 56)."""
NO_CUT_CELLS = 1_600
"""Las celdas de la zona «sin corte»: 40 · 40."""
DOMAIN_CELLS = int(INTERSECTION_M2) - TOWER_ZONE_CELLS
"""El dominio por defecto: perímetro ∩ límite − la torre (89.376 celdas)."""
CUT_ALLOWED_CELLS = int(INTERSECTION_M2 - INWARD_BAND_M2) - TOWER_ZONE_CELLS - NO_CUT_CELLS
"""El corte admitido (el recinto de A1): el dominio − el resguardo hacia dentro − «sin corte»
(84.976 celdas)."""

CONSTRAINT_CODES = ("concesion", "perimetro", "sin_corte", "torre")
"""Los códigos de las cuatro restricciones, por orden alfabético."""


def _rectangle(box: tuple[float, float, float, float]) -> np.ndarray:
    return cfx.rectangle(*box)


def _constraint(code: str, name: str, ctype: Any, kind: Any, parts: Any, *,
                priority: int = 0) -> Any:
    store = import_geoblender("core.constraints.store")
    return cmodel.Constraint(
        uid=f"{code:0<32}"[:32], code=code, name=name, ctype=ctype, kind=kind, parts=parts,
        priority=priority, reason="Restricción sintética de la cantera",
        decided_by="Samuel (IMGA)", decided_on=date(2026, 11, 12), decision_uid=None,
        intention_uid=None, source_input=None, source_fid=None,
        layer=store.layer_of(kind), fid=0)


def constraints() -> tuple[Any, ...]:
    """Las cuatro restricciones de la cantera (véase el módulo), con ``fid`` 0 (nuevas)."""
    kinds, types = cmodel.GeometryKind, cmodel.ConstraintType
    return (
        _constraint("concesion", "Concesión", types.LEGAL_LIMIT, kinds.POLYGON,
                    ((_rectangle(LEGAL_LOCAL),),)),
        _constraint("perimetro", "Perímetro", types.ACTION_PERIMETER, kinds.POLYGON,
                    ((_rectangle(PERIMETER_LOCAL),),)),
        _constraint("torre", "Torre", types.UNTOUCHABLE, kinds.POINT,
                    ((cfx.absolute([TOWER_LOCAL]),),), priority=10),
        _constraint("sin_corte", "Sin corte", types.NO_CUT, kinds.POLYGON,
                    ((_rectangle(NO_CUT_LOCAL),),)),
    )


def constraint_values() -> dict[str, Any]:
    """Los parámetros del proyecto de las restricciones (clave → valor): activas, el resguardo
    hacia dentro del límite, el de la torre y el de «sin corte» (0 m)."""
    found: dict[str, Any] = {cparams.active_key(item.code): True for item in constraints()}
    found[cparams.buffer_in_key("concesion")] = LEGAL_INWARD_M
    found[cparams.buffer_out_key("torre")] = TOWER_OUTWARD_M
    found[cparams.buffer_out_key("sin_corte")] = 0.0
    return found


def sectors() -> tuple[Any, ...]:
    """Los dos sectores de búsqueda (:data:`SECTORS_LOCAL`): ``sector_1`` al oeste y ``sector_2``
    al este."""
    return tuple(cmodel.Sector(f"qsector{index}{'0' * 25}", f"sector_{index}", name,
                               (_rectangle(box),))
                 for index, (name, box) in enumerate(SECTORS_LOCAL.items(), start=1))


# --- Las capas del proyecto (plan 014 §5.2.1) -------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class Floor:
    """Un fondo: su nombre, su caja local y su cota (m)."""

    name: str
    box: tuple[float, float, float, float]
    level_m: float

    @property
    def area_m2(self) -> float:
        """Su área (m²), a mano."""
        left, bottom, right, top = self.box
        return (right - left) * (top - bottom)


FLOORS: tuple[Floor, ...] = (
    Floor("Fondo 125", (120.0, 120.0, 200.0, 200.0), 125.0),
    Floor("Plataforma 175", (220.0, 200.0, 300.0, 260.0), 175.0),
)
"""Los dos fondos de E1: el de 125 m (80 × 80 m, 6.400 m²) y la plataforma de 175 m (80 × 60 m,
4.800 m²), sin solapes, dentro del corte admitido y por debajo del terreno."""
CONSERVE_LOCAL = (60.0, 180.0, 100.0, 240.0)
"""La zona a conservar (local; E2): 40 × 60 m, 2.400 m², dentro del corte admitido."""
CORRIDOR_AXIS_LOCAL = ((200.0, 160.0), (320.0, 160.0), (320.0, 80.0))
"""El eje del corredor (local; E1, CE-014-03): sale del borde este del fondo de 125 m, 120 m al
este y 80 m al sur: **200 m**."""
CORRIDOR_LENGTH_M = 200.0
"""La longitud del eje del corredor (m)."""
CORRIDOR_WIDTH_M = 20.0
"""El ancho del corredor (m)."""
CORRIDOR_START_M = 125.0
"""La cota inicial de la rasante del corredor (m): la del fondo del que sale."""
CORRIDOR_GRADIENT_PCT = 8.0
"""La pendiente de la rasante (%): 125 + 200 · 0,08 = 141 m al final."""
FILL_ZONE_LOCAL = (60.0, 80.0, 110.0, 140.0)
"""La zona de restauración por relleno (local; D-11): 50 × 60 m, 3.000 m²."""
WATER_LOCAL = (130.0, 300.0, 170.0, 330.0)
"""La lámina de agua (local; E5, RF-014-24): 40 × 30 m, 1.200 m², al norte del escarpe."""
WATER_LEVEL_M = 270.0
"""La cota de la lámina de agua (m)."""

FLOORS_LAYER = "gis_fea_fondos"
"""La capa de los fondos (polígonos con el campo ``cota``)."""
CONSERVE_LAYER = "gis_fea_conservar"
"""La capa de las zonas a conservar (polígonos)."""
CORRIDORS_LAYER = "gis_fea_corredores"
"""La capa de los corredores (líneas con ``ancho``, ``cota_inicial`` y ``pendiente``)."""
FILL_LAYER = "gis_fea_relleno"
"""La capa de las zonas de restauración por relleno (polígonos)."""
WATER_LAYER = "gis_fea_laminas"
"""La capa de las láminas de agua (polígonos con ``cota``)."""


@dataclass(frozen=True, slots=True, eq=False)
class LayerData:
    """Una capa de entidades de la cantera: su nombre en el proyecto, su geometría (``polygon`` o
    ``line``), sus entidades (por entidad, sus partes y, de cada una, sus anillos o su camino,
    ABSOLUTOS), el nombre de cada una y sus campos numéricos (campo → valor por entidad)."""

    name: str
    kind: str
    entities: tuple[tuple[tuple[np.ndarray, ...], ...], ...]
    names: tuple[str, ...]
    fields: Mapping[str, tuple[float, ...]]


def layers() -> tuple[LayerData, ...]:
    """Las cinco capas de la cantera (arrays nuevos), en el orden en que se escriben."""
    def polygon(box: tuple[float, float, float, float]) -> tuple[tuple[np.ndarray, ...], ...]:
        return ((_rectangle(box),),)

    return (
        LayerData(FLOORS_LAYER, "polygon", tuple(polygon(item.box) for item in FLOORS),
                  tuple(item.name for item in FLOORS),
                  {"cota": tuple(item.level_m for item in FLOORS)}),
        LayerData(CONSERVE_LAYER, "polygon", (polygon(CONSERVE_LOCAL),), ("Ladera a conservar",),
                  {}),
        LayerData(CORRIDORS_LAYER, "line", (((cfx.absolute(CORRIDOR_AXIS_LOCAL),),),),
                  ("Corredor de salida",),
                  {"ancho": (CORRIDOR_WIDTH_M,), "cota_inicial": (CORRIDOR_START_M,),
                   "pendiente": (CORRIDOR_GRADIENT_PCT,)}),
        LayerData(FILL_LAYER, "polygon", (polygon(FILL_ZONE_LOCAL),), ("Relleno de restauración",),
                  {}),
        LayerData(WATER_LAYER, "polygon", (polygon(WATER_LOCAL),), ("Balsa",),
                  {"cota": (WATER_LEVEL_M,)}),
    )


LAYERS = tuple(item.name for item in layers())
"""Los nombres de las cinco capas."""

# --- Los perfiles ----------------------------------------------------------------------------

EXPLOITATION_PROFILE = dfx.EXPL_10_60_6
"""El perfil de la explotación: ``EXPL_10_60_6`` (ancla 125 m)."""
FINAL_PROFILE = dfx.REST_5_35_6
"""El perfil de la final: ``REST_5_35_6`` (ancla 125 m)."""
PROFILES: Mapping[str, dfx.ProfileData] = {item.name: item for item in
                                           (EXPLOITATION_PROFILE, FINAL_PROFILE)}
"""Los dos perfiles de la cantera, por nombre."""

# --- El proyecto de la cantera ----------------------------------------------------------------

START_LABEL = "terreno"
"""El nombre del terreno de partida al escribirlo (``write_grids``)."""
START_DATASET = f"gis_dtm_{START_LABEL}"
"""El dato del terreno de partida en el proyecto."""
BUILD_BUDGET_S = 2.0
"""La plantilla se construye en ≤ 2 s de CPU (tarea T01)."""
_VERSIONS = (("cantera", "Cantera"), ("alternativa", "Alternativa"))
_TEMPLATES: dict[float, dict[str, Any]] = {}


def window() -> tuple[float, float, float, float]:
    """La ventana del proyecto: la extensión de :data:`GRID`."""
    extent = GRID.extent
    return (extent.xmin, extent.ymin, extent.xmax, extent.ymax)


def _close_searches(project: Any, clock: FakeClock) -> None:
    """Cierra la búsqueda de intocables de cada sector (como ``design_fixtures``)."""
    cstore = import_geoblender("core.constraints.store")
    operations = import_geoblender("core.provenance.operations")
    for index, sector in enumerate(sectors(), start=1):
        clock.advance(minutes=1)
        handle = operations.begin_operation(project, cp.EDIT_TYPE, settings={"count": 0},
                                            executor="blender")
        record = cmodel.SearchRecord(f"qsearch{index}{'0' * 25}", handle.uid, sector.code,
                                     cstore.sector_sha256(sector), cfx.SEARCH_DISTANCE_M,
                                     "Samuel (IMGA)", "2026-11-12T10:00:00Z")
        with project.write_transaction() as conn:
            cstore.append_search(conn, record, ())
            handle.complete(conn, outputs=cstore.dataset_specs(crs_epsg=project.record.crs_epsg),
                            message="Búsqueda de prueba de la cantera")


def write_feature_layer(project: Any, clock: FakeClock, layer: LayerData) -> None:
    """Escribe ``layer`` como capa de entidades del proyecto (``gis_fea_…``), como la importación
    de la 006 y ``DesignProjectCase.write_layer``: el campo ``nombre`` y sus campos numéricos
    (``DOUBLE``), un minuto después."""
    from tests.support.provenance_contract import registered

    contract = import_geoblender("core.provenance.contract")
    operations = import_geoblender("core.provenance.operations")
    datasets = import_geoblender("core.datasets")
    builtin = import_geoblender("core.content.builtin")
    gstore = import_geoblender("gis.store")
    vector = import_geoblender("gis.vector")
    srs = int(project.record.crs_epsg)
    columns = (vector.FieldColumn("nombre", "nombre", "TEXT"),
               *(vector.FieldColumn(field, field, "DOUBLE") for field in layer.fields))
    values = {"nombre": layer.names, **{field: tuple(found) for field, found in
                                        layer.fields.items()}}
    fids = tuple(range(1, len(layer.entities) + 1))
    found = vector.FeatureLayer(layer.kind, fids, layer.entities, columns, values)
    rows = gstore.feature_rows(found, srs)
    names = ", ".join(f'"{column.column}" {column.sql_type}' for column in columns)
    marks = ", ".join("?" for _ in range(len(columns) + 2))
    writer = contract.OperationDef(dfx.LAYERS_TYPE, "1.0", "gis", "Layers of the tests", False)
    with registered(writer):
        clock.advance(minutes=1)
        handle = operations.begin_operation(project, dfx.LAYERS_TYPE,
                                            settings={"name": layer.name}, executor="blender")
        with project.write_transaction() as conn:
            conn.execute(f'CREATE TABLE "{layer.name}" (fid INTEGER PRIMARY KEY NOT NULL, '
                         f"geom {found.geometry_type}, {names})")
            conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, "
                         "description, srs_id) VALUES (?, 'features', ?, '', ?)",
                         (layer.name, layer.name, srs))
            conn.execute("INSERT INTO gpkg_geometry_columns (table_name, column_name, "
                         "geometry_type_name, srs_id, z, m) VALUES (?, 'geom', ?, ?, 0, 0)",
                         (layer.name, found.geometry_type, srs))
            conn.executemany(f'INSERT INTO "{layer.name}" VALUES ({marks})', rows)
            handle.complete(conn, outputs=(datasets.DatasetSpec(
                layer.name, "gis", "vector", datasets.Store.GPKG, layer.name,
                reader=builtin.GPKG_LAYER.id, role="features", crs_epsg=srs, input_uid=None,
                immutable=False),), message="Capa de prueba de la cantera")


def _build(folder: Path, step_m: float) -> dict[str, Any]:
    """Crea el proyecto de :func:`project_template` con celdas de ``step_m`` m en
    ``folder/proyectos`` y lo cierra."""
    from tests.support.res_fixtures import write_grids

    create = import_geoblender("core.project.create")
    userdata = import_geoblender("core.userdata")
    versions_store = import_geoblender("core.versions.store")
    access = import_geoblender("gis.masks.access")
    started = time.process_time()
    (folder / "proyectos").mkdir()
    clock = FakeClock()
    settings = make_settings(window=window(), grid_step_m=step_m)
    project = create.create_project(folder / "proyectos", settings, cp.SESSION,
                                    userdata.UserData(folder / "u"), clock=clock).project
    try:
        versions = []
        for feature, title in _VERSIONS:
            clock.advance(minutes=1)
            with project.write_transaction() as conn:
                version, _revision = versions_store.create_version(
                    conn, project, feature=feature, title=title, reason="Prueba de la 014")
            project.refresh_header()
            versions.append(version)
        clock.advance(minutes=1)
        cp.edit_constraints(project, constraints(), sector_rows=sectors())
        cp.declare(project, clock, constraint_values())
        _close_searches(project, clock)
        clock.advance(minutes=1)
        write_grids(project, [(START_LABEL, start_raster(grid_of(step_m)))],
                    message="Terreno de partida de la cantera")
        for layer in layers():
            write_feature_layer(project, clock, layer)
        clock.advance(minutes=1)
        for _step in access.ensure_masks_steps(project, versions[0].uid):
            pass
        clock.advance(minutes=1)
        return {"folder": folder, "name": Path(project.root).name, "now": clock.now(),
                "versions": tuple(version.uid for version in versions),
                "build_s": time.process_time() - started}
    finally:
        project.close()


def project_template(step_m: float = STEP_M) -> Mapping[str, Any]:
    """El proyecto de la cantera (véase el módulo) con la rejilla de ``step_m`` m (por defecto la
    de 1 m, :data:`GRID`; con :data:`COARSE_STEP_M`, la gruesa de :func:`grid_of`), creado y
    cerrado la primera vez que se pide en el proceso con ese paso, en una carpeta temporal que se
    borra al salir: ``folder``, ``name`` de la carpeta del proyecto, ``now`` del reloj al terminar,
    los uid de ``versions`` (V01 y V02) y ``build_s``, la CPU que gastó construirlo (s). No se
    modifica."""
    found = _TEMPLATES.get(step_m)
    if found is None:
        grid_of(step_m)  # el paso, antes de crear nada
        folder = Path(tempfile.mkdtemp(prefix="gb-qt-"))
        atexit.register(shutil.rmtree, folder, ignore_errors=True)
        with cp.constraints_registered():
            found = _TEMPLATES[step_m] = _build(folder, step_m)
    return found


@contextmanager
def open_quarry_project(prefix: str = "gb-qp-", step_m: float = STEP_M
                        ) -> Iterator[tuple[Any, FakeClock]]:
    """Una copia propia del proyecto de la cantera con la rejilla de ``step_m`` m
    (:func:`project_template`) abierta en escritura: ``(project, clock)``. Al salir se cierra y
    se borra. Hace falta ``constraints_project.constraints_registered()`` activo (lo está en una
    :class:`QuarryProjectCase`)."""
    open_mod = import_geoblender("core.project.open")
    userdata = import_geoblender("core.userdata")
    made = project_template(step_m)
    with project_tmp(prefix) as folder:
        shutil.copytree(made["folder"] / "proyectos", folder / "proyectos")
        clock = FakeClock(made["now"])
        project = open_mod.open_project(
            folder / "proyectos" / made["name"], cp.SESSION, userdata.UserData(folder / "u"),
            clock=clock, pid_alive=FakePids({cp.SESSION.pid})).project
        try:
            yield project, clock
        finally:
            project.close()


class QuarryProjectCase(cp.ConstraintsProjectCase):
    """Una copia **por clase** del proyecto de la cantera, abierta en escritura (``cls.project``,
    en ``cls.root``), con lo de ``constraints_registered``, su reloj (``cls.clock``), V01 y V02
    (``cls.v1``, ``cls.v2``) y su rejilla (``cls.grid``: la de :data:`STEP_M` por defecto; una
    clase con ``STEP_M = COARSE_STEP_M`` trabaja en la gruesa, T35); además de ``query``,
    ``record`` y ``stored_constraints``:

    - :meth:`masks`: el ``MaskSet`` de una versión (por defecto V01, al día);
    - :meth:`read_layer`: una capa de entidades del proyecto (``gis.store.read_features``);
    - :meth:`stale_causes` y :meth:`recompute_plan` (T50): por qué está obsoleta una operación y
      el plan de «Recalcular lo obsoleto» (de la 008), con nombres legibles."""

    STEP_M: ClassVar[float] = STEP_M
    project: ClassVar[Any]
    grid: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        versions_read = import_geoblender("core.versions.read")
        cls.grid = grid_of(cls.STEP_M)
        made = project_template(cls.STEP_M)
        cls.enterClassContext(cp.constraints_registered())
        cls.project, cls.clock = cls.enterClassContext(
            open_quarry_project("gb-qc-", cls.STEP_M))
        cls.root = Path(cls.project.root)
        with cls.project.read() as conn:
            cls.v1, cls.v2 = (versions_read.version(conn, uid) for uid in made["versions"])

    def masks(self, version: Any = None) -> Any:
        """Las máscaras de ``version`` (por defecto V01) ya compiladas; ``MaskError`` si no
        están al día."""
        access = import_geoblender("gis.masks.access")
        target = self.v1 if version is None else version
        return access.load_masks(self.project, target.uid)

    def read_layer(self, name: str) -> Any:
        """La capa de entidades ``name`` del proyecto (``FeatureLayer``)."""
        gstore = import_geoblender("gis.store")
        with self.project.read() as conn:
            return gstore.read_features(conn, name)

    def stale_causes(self, operation_uid: str) -> set[tuple[str, str]]:
        """Las causas por las que la operación ``operation_uid`` está obsoleta (la caché
        ``gb_stale`` de la 008), cada una con su clase (``parameter_changed``,
        ``dataset_changed``…) y lo que cambió por su nombre: la clave del parámetro, el nombre
        del dato o, si no es ninguno de los dos, su uid. Vacío si está al día."""
        found: set[tuple[str, str]] = set()
        with self.project.read() as conn:
            for cause, subject in conn.execute(
                    "SELECT cause_kind, subject_uid FROM gb_stale WHERE item_kind = 'operation' "
                    "AND item_uid = ?", (operation_uid,)).fetchall():
                named = conn.execute("SELECT key FROM gb_parameter WHERE uid = ? UNION ALL "
                                     "SELECT name FROM gb_dataset WHERE uid = ?",
                                     (subject, subject)).fetchone()
                found.add((cause, subject if named is None else named[0]))
        return found

    def recompute_plan(self) -> list[tuple[str, ...]]:
        """El plan de «Recalcular lo obsoleto» del proyecto (``plan_recompute`` de la 008): el tipo
        de las operaciones de cada unidad, unidad a unidad, en el orden en que se repiten."""
        graph = import_geoblender("core.provenance.graph")
        recompute = import_geoblender("core.provenance.recompute")
        with self.project.read() as conn:
            units = recompute.plan_recompute(graph.load_graph(conn)).units
            return [tuple(conn.execute("SELECT op_type FROM gb_operation WHERE uid = ?",
                                       (uid,)).fetchone()[0] for uid in unit.operations)
                    for unit in units]


def same_entities(found: Sequence[Any], expected: Sequence[Any]) -> bool:
    """Si las partes de dos listas de entidades son iguales bit a bit."""
    return len(found) == len(expected) and all(
        cp.same_parts(a, b) for a, b in zip(found, expected, strict=True))

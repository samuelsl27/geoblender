# SPDX-License-Identifier: GPL-3.0-or-later
"""Los datos de rendimiento de las envolventes y el escalonado (spec 013, T30; plan 013 §2.2 y §7.3;
``tests/rendimiento/des/test_design_perf.py``). Solo sintéticos: se generan al pedirlos, no se
versionan y los borra quien los escribe; ningún dato de cliente.

- **La rejilla** (spec 013 §5): :data:`COLS` × :data:`ROWS` celdas de :data:`STEP_M` m (2,81 M), la
  de las restricciones de la 012 (``constraints_data``), con :func:`terrain` (un terreno ondulado de
  145 a 215 m con colinas, un ondulado de metros y ruido de 5 cm).
- **Las semillas** (plan §2.2): :func:`ring_seeds` (un anillo de radio :data:`RING_RADIUS_M`; con
  :data:`RING_HALF_WIDTH_M`, unas 5.300 celdas, y con :data:`THICK_HALF_WIDTH_M`, unas 9.800, bajo
  el tope de 10.000 de RNF-013-01) y :func:`disc_seeds` (un disco rugoso de unas 159.900 celdas,
  con un ondulado de ±2 m y ruido de 0,3 m sobre el terreno: la zona maciza de RNF-013-01). Cada
  una es una rejilla de cotas con NaN donde no hay semilla.
- **Los sectores** (:data:`SECTORS` franjas): :func:`strip_labels` (las etiquetas de la rejilla),
  :func:`sector_rules` (una regla de pendiente por sector: el talud general de uno de los
  :data:`PROFILES` o, en :data:`IMPOSED`, el impuesto de 10,6° y 18°) y :func:`base_rule`.
- **El proyecto de escala** (:func:`scale_project`): un proyecto nuevo en ``%TEMP%`` con la ventana
  de la rejilla, V01 y V02, el límite legal y el perímetro, los 20 sectores (franjas del
  perímetro) con su búsqueda de intocables cerrada, la superficie de partida (:data:`START`) y las
  semillas en anillo (:data:`RING_GRID`) como rejillas del proyecto, las máscaras de V01 al día,
  los diez perfiles de banco y los dos taludes impuestos, y lo que registrará ``bl`` para que
  ``design`` calcule. Las peticiones de las órdenes (:func:`ring_request`, :func:`surface_request`,
  :func:`sectors_request`, :func:`design_request`) son las de este proyecto.

Python de Blender (su numpy 2.3.4) y biblioteca estándar.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np

from tests.support import constraints_data as cdata
from tests.support import constraints_fixtures as cfx
from tests.support import constraints_project as cp
from tests.support.core_fixtures import FakeClock, make_session, make_settings, project_tmp
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.res_fixtures import write_grids

gis = import_geoblender("gis")
cmodel = import_geoblender("core.constraints.model")
cparams = import_geoblender("core.constraints.params")
cstore = import_geoblender("core.constraints.store")
core_params = import_geoblender("core.params")
create = import_geoblender("core.project.create")
operations = import_geoblender("core.provenance.operations")
userdata_mod = import_geoblender("core.userdata")
versions_store = import_geoblender("core.versions.store")
access = import_geoblender("gis.masks.access")
design_model = import_geoblender("design.model")
design_params = import_geoblender("design.params")
design_provenance = import_geoblender("design.provenance")
envelopes = import_geoblender("design.envelopes")
res_provenance = import_geoblender("reserves.provenance")

__all__ = [
    "CELLS", "COLS", "CONTOUR_MAX_SEEDS", "GENERAL_DEG", "IMPOSED", "PROFILES",
    "RING_GRID", "RING_HALF_WIDTH_M", "RING_RADIUS_M", "ROWS", "SECTORS", "SOLID_MAX_SEEDS",
    "START", "THICK_HALF_WIDTH_M", "DesignScale", "PerfProfile", "base_rule", "design_request",
    "disc_seeds", "grid", "ring_request", "ring_seeds", "scale_project", "sector_rules",
    "sectors_request", "strip_labels", "surface_request", "terrain",
]

COLS, ROWS = cdata.COLS, cdata.ROWS
STEP_M = cdata.STEP_M
CELLS = COLS * ROWS
SEED = 20_261_104
GENERAL_DEG = 35.0
"""La pendiente de las envolventes de pendiente constante (``k = tan 35°``, plan §2.2)."""
CONTOUR_MAX_SEEDS = 10_000
SOLID_MAX_SEEDS = 160_000
RING_RADIUS_M = 600.0
RING_HALF_WIDTH_M = 0.7
"""El anillo de §2.2: unas 5.300 celdas."""
THICK_HALF_WIDTH_M = 1.3
"""El anillo más grueso: unas 9.800 celdas, bajo el tope de RNF-013-01."""
DISC_RADIUS_M = 225.6
SECTORS = 20
PERSON = "Samuel (IMGA)"
START = "gis_dtm_partida"
"""El dato de la superficie de partida del proyecto de escala."""
RING_GRID = "gis_dtm_anillo"
"""El dato con las semillas en anillo (cotas del terreno en el anillo, sin dato fuera)."""
_START_LABEL = "partida"
_RING_LABEL = "anillo"
MARGIN_M = 10.0
"""Lo que el perímetro queda dentro de la ventana (y el límite legal, la mitad)."""
BY_HAND = {"source": "Valores sintéticos de rendimiento", "source_kind": "person",
           "decided_by": PERSON}


def grid() -> Any:
    """La rejilla de 1.654 × 1.699 celdas de 1 m."""
    return gis.Grid(cdata.WEST, cdata.NORTH, STEP_M, STEP_M, COLS, ROWS)


# --- El terreno y las semillas -------------------------------------------------------------------

_CACHE: dict[str, np.ndarray] = {}


def _east() -> np.ndarray:
    """Las coordenadas locales (m desde el oeste) de los centros de cada columna, (1, COLS)."""
    return (np.arange(COLS, dtype=np.float64) + 0.5)[None, :] * STEP_M


def _north() -> np.ndarray:
    """Las coordenadas locales (m desde el sur) de los centros de cada fila (la 0 al norte),
    (ROWS, 1)."""
    return (np.arange(ROWS, dtype=np.float64)[::-1] + 0.5)[:, None] * STEP_M


def terrain() -> np.ndarray:
    """El terreno (m, float64, fila 0 al norte): de 145 a 215 m, con colinas de cientos de
    metros, un ondulado de metros y ruido de 5 cm. Es el mismo array en cada llamada: no se
    modifica."""
    if "terrain" not in _CACHE:
        east, north = _east(), _north()
        values = (180.0 + 30.0 * np.sin(east / 150.0) * np.cos(north / 120.0)
                  + 5.0 * np.sin(east / 7.3) * np.sin(north / 5.1))
        values += np.random.default_rng(SEED).normal(0.0, 0.05, values.shape)
        _CACHE["terrain"] = values
    return _CACHE["terrain"]


def _distance_from_center() -> np.ndarray:
    """La distancia (m) de cada centro de celda al centro de la rejilla."""
    return np.hypot(_east() - COLS * STEP_M / 2.0, _north() - ROWS * STEP_M / 2.0)


def ring_seeds(half_width_m: float) -> np.ndarray:
    """Las semillas de un anillo de radio :data:`RING_RADIUS_M` y ``half_width_m`` de semiancho,
    con la cota del terreno (NaN fuera): array nuevo."""
    seeds = np.full((ROWS, COLS), np.nan)
    ring = np.abs(_distance_from_center() - RING_RADIUS_M) <= half_width_m
    seeds[ring] = terrain()[ring]
    return seeds


def disc_seeds() -> np.ndarray:
    """La zona maciza: las celdas de un disco de :data:`DISC_RADIUS_M` con el terreno más un
    ondulado de ±2 m y ruido de 0,3 m (rugosa, el peor caso de la búsqueda exacta; NaN fuera):
    array nuevo."""
    seeds = np.full((ROWS, COLS), np.nan)
    disc = _distance_from_center() <= DISC_RADIUS_M
    rough = (2.0 * np.sin(_east() / 3.1) * np.sin(_north() / 2.3)
             + np.random.default_rng(SEED + 1).normal(0.0, 0.3, (ROWS, COLS)))
    seeds[disc] = (terrain() + rough)[disc]
    return seeds


# --- Los perfiles y los sectores -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PerfProfile:
    """Un perfil de banco de §2.2: su ``code`` y la altura, la cara, la berma y el ancla (m y °)."""

    code: str
    height_m: float
    face_deg: float
    berm_m: float
    anchor_m: float = 125.0

    @property
    def general_tan(self) -> float:
        """El talud general ``h / (h/tan α + B)``."""
        return self.height_m / (self.height_m / math.tan(math.radians(self.face_deg))
                                + self.berm_m)


PROFILES = tuple(PerfProfile(f"perf_{h}_{face}_{berm}", float(h), float(face), float(berm))
                 for h, face, berm in ((10, 60, 6), (10, 70, 8), (10, 55, 8), (10, 65, 6),
                                       (10, 50, 8), (5, 35, 6), (5, 45, 6), (5, 40, 8),
                                       (5, 60, 6), (5, 50, 8)))
"""Los diez perfiles (h 5 o 10 m; cara de 35° a 70°; berma de 6 u 8 m; ancla de 125 m)."""
IMPOSED: dict[int, float] = {5: 10.6, 13: 18.0}
"""El talud general impuesto (°) de los sectores 5 y 13 (plan §2.2)."""


def sector_code(index: int) -> str:
    """El código del sector ``index`` (1 a :data:`SECTORS`)."""
    return f"sector_{index:02d}"


def _profile_of(index: int) -> PerfProfile:
    return PROFILES[(index - 1) % len(PROFILES)]


def strip_labels() -> np.ndarray:
    """Las etiquetas (int16) de :data:`SECTORS` franjas verticales de igual ancho que cubren toda
    la rejilla: el sector ``k`` es la etiqueta ``k``."""
    columns = (np.arange(COLS) * SECTORS // COLS + 1).astype(np.int16)
    return np.broadcast_to(columns, (ROWS, COLS)).copy()


def sector_rules() -> list[Any]:
    """La regla de pendiente de cada sector: su talud impuesto (:data:`IMPOSED`) o el talud
    general del perfil que se le asigna."""
    rules = []
    for index in range(1, SECTORS + 1):
        if index in IMPOSED:
            rules.append(envelopes.SlopeRule.from_degrees(IMPOSED[index]))
        else:
            rules.append(envelopes.SlopeRule(_profile_of(index).general_tan))
    return rules


def base_rule() -> Any:
    """La regla del perfil base (el primero)."""
    return envelopes.SlopeRule(PROFILES[0].general_tan)


# --- El proyecto de escala ------------------------------------------------------------------------


@dataclass(slots=True)
class DesignScale:
    """El proyecto de escala abierto: el proyecto, su reloj y V01 y V02."""

    project: Any
    clock: FakeClock
    v1: Any
    v2: Any


def _ring(left: float, bottom: float, right: float, top: float) -> np.ndarray:
    """El anillo absoluto, cerrado y antihorario, de un rectángulo de coordenadas absolutas."""
    return np.array([(left, bottom), (right, bottom), (right, top), (left, top), (left, bottom)],
                    dtype=np.float64)


def _constraint(index: int, code: str, name: str, ctype: Any, ring: np.ndarray) -> Any:
    kind = cmodel.GeometryKind.POLYGON
    return cmodel.Constraint(
        uid=f"{index:032x}", code=code, name=name, ctype=ctype, kind=kind, parts=((ring,),),
        priority=0, reason="Restricción sintética de rendimiento", decided_by=PERSON,
        decided_on=date(2026, 11, 4), decision_uid=None, intention_uid=None, source_input=None,
        source_fid=None, layer=cstore.layer_of(kind), fid=0)


def _constraints() -> tuple[tuple[Any, ...], dict[str, Any]]:
    """El límite legal (5 m hacia dentro de la ventana, 2 m más hacia dentro) y el perímetro de
    actuación (:data:`MARGIN_M`), con sus parámetros de proyecto."""
    west, south, east, north = cdata.window()
    legal = _constraint(1, "concesion", "Concesión", cmodel.ConstraintType.LEGAL_LIMIT,
                        _ring(west + MARGIN_M / 2, south + MARGIN_M / 2, east - MARGIN_M / 2,
                              north - MARGIN_M / 2))
    perimeter = _constraint(2, "perimetro", "Perímetro", cmodel.ConstraintType.ACTION_PERIMETER,
                            _ring(west + MARGIN_M, south + MARGIN_M, east - MARGIN_M,
                                  north - MARGIN_M))
    values = {cparams.active_key("concesion"): True, cparams.active_key("perimetro"): True,
              cparams.buffer_in_key("concesion"): 2.0}
    return (legal, perimeter), values


def _sectors() -> tuple[Any, ...]:
    """Las :data:`SECTORS` franjas verticales del perímetro."""
    west, south, east, north = cdata.window()
    left, right = west + MARGIN_M, east - MARGIN_M
    width = (right - left) / SECTORS
    found = []
    for index in range(1, SECTORS + 1):
        lo = left + (index - 1) * width
        hi = right if index == SECTORS else left + index * width
        found.append(cmodel.Sector(f"sector{index:02d}".ljust(32, "0"), sector_code(index),
                                   f"Sector {index:02d}",
                                   (_ring(lo, south + MARGIN_M, hi, north - MARGIN_M),)))
    return tuple(found)


def _close_searches(project: Any, clock: FakeClock, sectors: tuple[Any, ...]) -> None:
    """Cierra la búsqueda de intocables de cada sector (con su huella), como hará la orden de la
    012: ningún sector queda con la búsqueda pendiente."""
    for index, sector in enumerate(sectors, start=1):
        clock.advance(minutes=1)
        handle = operations.begin_operation(project, cp.EDIT_TYPE, settings={"count": 0},
                                            executor="blender")
        record = cmodel.SearchRecord(f"search{index:02d}".ljust(32, "0"), handle.uid, sector.code,
                                     cstore.sector_sha256(sector), cfx.SEARCH_DISTANCE_M, PERSON,
                                     "2026-11-04T10:00:00Z")
        with project.write_transaction() as conn:
            cstore.append_search(conn, record, ())
            handle.complete(conn, outputs=cstore.dataset_specs(crs_epsg=project.record.crs_epsg),
                            message="Búsqueda de rendimiento")


def _recompute(request: Any) -> Any:
    raise AssertionError("las pruebas de rendimiento no recalculan con la función de bl")


def _reproduce(request: Any) -> Iterator[Any]:
    raise AssertionError("las pruebas de rendimiento no reproducen")


def _declare_design(project: Any, clock: FakeClock, v1: Any) -> None:
    """Los diez perfiles de banco (en el proyecto) y los taludes impuestos de los sectores
    :data:`IMPOSED` (en V01)."""
    store = core_params.ParameterStore(project)
    clock.advance(minutes=1)
    with project.write_transaction() as conn:
        for profile in PROFILES:
            values = {"height_m": profile.height_m, "face_deg": profile.face_deg,
                      "berm_m": profile.berm_m, "anchor_m": profile.anchor_m, "mesh_factor": 1.0}
            for param, value in values.items():
                kind = "ADOPTADO" if param == "mesh_factor" else "HIPÓTESIS"
                store.create(conn, design_params.bench_key(profile.code, param), value, kind=kind,
                             reason="Perfil sintético de rendimiento", **BY_HAND)
        for index, degrees in IMPOSED.items():
            store.create(conn, design_params.sector_slope_key(sector_code(index)), degrees,
                         kind="HIPÓTESIS", reason="Talud impuesto sintético de rendimiento",
                         version=v1.code, **BY_HAND)


@contextmanager
def scale_project() -> Iterator[DesignScale]:
    """El proyecto de escala (véase el módulo), con lo que registrará ``bl`` para que ``design``
    calcule y registre. Al salir lo cierra, quita lo registrado y borra la carpeta."""
    rows, values = _constraints()
    sectors = _sectors()
    with ExitStack() as stack:
        stack.enter_context(cp.constraints_registered())
        core_params.register_definitions(design_params.DEFINITIONS)
        stack.callback(core_params.unregister_definitions, "des")
        core_params.register_families(design_params.FAMILIES)
        stack.callback(core_params.unregister_families, "des")
        core_params.register_definitions(res_provenance.VERIFY_DEFINITIONS)
        stack.callback(core_params.unregister_definitions, "res")
        stack.enter_context(registered(
            *design_provenance.operation_defs(
                {t: _recompute for t in design_provenance.REPRODUCIBLE},
                {t: _reproduce for t in design_provenance.REPRODUCIBLE}),
            *design_provenance.FIGURES))
        folder = stack.enter_context(project_tmp("gb-diseno-"))
        clock = FakeClock()
        (folder / "proyectos").mkdir()
        settings = make_settings(window=cdata.window(), grid_step_m=STEP_M)
        project = create.create_project(folder / "proyectos", settings, make_session(),
                                        userdata_mod.UserData(folder / "u"), clock=clock).project
        stack.callback(project.close)
        versions = []
        for feature, title in (("diseno", "Diseño"), ("alternativa", "Alternativa")):
            clock.advance(minutes=1)
            with project.write_transaction() as conn:
                version, _revision = versions_store.create_version(
                    conn, project, feature=feature, title=title, reason="Escala de la 013")
            project.refresh_header()
            versions.append(version)
        clock.advance(minutes=1)
        cp.edit_constraints(project, rows, sector_rows=sectors)
        cp.declare(project, clock, values)
        _close_searches(project, clock, sectors)
        clock.advance(minutes=1)
        found = grid()
        write_grids(project, [
            (_START_LABEL, gis.Raster(found, terrain().copy(), cfx.CRS, cfx.VERTICAL)),
            (_RING_LABEL, gis.Raster(found, ring_seeds(RING_HALF_WIDTH_M), cfx.CRS, cfx.VERTICAL))],
            message="Superficies de escala del diseño")
        _declare_design(project, clock, versions[0])
        clock.advance(minutes=1)
        for _step in access.ensure_masks_steps(project, versions[0].uid):
            pass
        clock.advance(minutes=1)
        yield DesignScale(project, clock, versions[0], versions[1])


# --- Las peticiones de las órdenes ---------------------------------------------------------------


def _envelope(name: str, seeds: Any, **changes: Any) -> Any:
    base: dict[str, Any] = {
        "direction": "down", "seeds": seeds, "slope_mode": "constant",
        "slope_deg": GENERAL_DEG, "metric": "chamfer5", "mesh_factor": 1.0, "reach_m": None,
        "domain": design_model.WorkDomain()}
    return design_model.EnvelopeRequest(name=name, **{**base, **changes})


def ring_request(data: DesignScale, name: str) -> Any:
    """Una envolvente de 35° desde las semillas en anillo (``chamfer`` constante)."""
    del data
    return _envelope(name, design_model.SeedSource("grid", grid=RING_GRID))


def surface_request(data: DesignScale, name: str) -> Any:
    """Una envolvente de 35° desde toda la superficie de partida como semillas: la preparación
    con más semillas posible (las celdas del dominio de trabajo)."""
    del data
    return _envelope(name, design_model.SeedSource("surface", surface=START,
                                                   zone=design_model.Zone("domain")))


def _assigned() -> dict[str, str]:
    return {sector_code(index): _profile_of(index).code for index in range(1, SECTORS + 1)}


def sectors_request(data: DesignScale, name: str) -> Any:
    """La envolvente del cálculo completo: descendente desde las semillas en anillo con la
    pendiente de cada sector (diez perfiles y los dos taludes impuestos)."""
    del data
    return _envelope(name, design_model.SeedSource("grid", grid=RING_GRID), slope_mode="sectors",
                     slope_deg=None, base_profile=PROFILES[0].code, sector_profiles=_assigned())


def design_request(data: DesignScale, name: str, envelope: str) -> Any:
    """El escalonado en corte de ``envelope`` con el perfil de cada sector."""
    del data
    return design_model.DesignRequest(name=name, envelope=envelope, sense="cut",
                                      base_profile=PROFILES[0].code, sector_profiles=_assigned(),
                                      anchor_grid=None)

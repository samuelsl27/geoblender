# SPDX-License-Identifier: GPL-3.0-or-later
"""Los datos de rendimiento de las envolventes y el escalonado (spec 013, T30; plan 013 §2.2 y §7.3;
``tests/rendimiento/des/test_design_perf.py``). Solo sintéticos: se generan al pedirlos, no se
versionan y los borra quien los escribe; ningún dato de cliente.

- **La rejilla, las semillas, los perfiles y los sectores** (plan §2.2): son datos puros y están en
  ``tests/support/design_data.py`` (los usa también ``perf_design.py`` dentro de Blender, T31); aquí
  se reexportan: :func:`terrain`, :func:`ring_seeds`, :func:`disc_seeds`, :func:`strip_labels`,
  :data:`PROFILES`, :data:`IMPOSED`…
- **Los taludes de los sectores**: :func:`sector_rules` (una regla de pendiente por sector: el talud
  general de uno de los :data:`PROFILES` o, en :data:`IMPOSED`, el impuesto de 10,6° y 18°) y
  :func:`base_rule`.
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

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from tests.support import constraints_data as cdata
from tests.support import constraints_fixtures as cfx
from tests.support import constraints_project as cp
from tests.support.core_fixtures import FakeClock, make_session, make_settings, project_tmp
from tests.support.design_data import (
    CELLS, COLS, CONTOUR_MAX_SEEDS, DISC_RADIUS_M, GENERAL_DEG, IMPOSED, MARGIN_M, PERSON, PROFILES,
    RING_HALF_WIDTH_M, RING_RADIUS_M, ROWS, SECTORS, SEED, SOLID_MAX_SEEDS, STEP_M,
    THICK_HALF_WIDTH_M, PerfProfile, assigned, disc_seeds, profile_of, ring_seeds, sector_boxes,
    sector_code, strip_labels, terrain)
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
    "CELLS", "COLS", "CONTOUR_MAX_SEEDS", "DISC_RADIUS_M", "GENERAL_DEG", "IMPOSED", "MARGIN_M",
    "PERSON", "PROFILES", "RING_GRID", "RING_HALF_WIDTH_M", "RING_RADIUS_M", "ROWS", "SECTORS",
    "SEED", "SOLID_MAX_SEEDS", "START", "STEP_M", "THICK_HALF_WIDTH_M", "DesignScale",
    "PerfProfile", "base_rule", "design_request", "disc_seeds", "grid", "ring_request",
    "ring_seeds", "scale_project", "sector_rules", "sectors_request", "strip_labels",
    "surface_request", "terrain",
]

START = "gis_dtm_partida"
"""El dato de la superficie de partida del proyecto de escala."""
RING_GRID = "gis_dtm_anillo"
"""El dato con las semillas en anillo (cotas del terreno en el anillo, sin dato fuera)."""
_START_LABEL = "partida"
_RING_LABEL = "anillo"
BY_HAND = {"source": "Valores sintéticos de rendimiento", "source_kind": "person",
           "decided_by": PERSON}


def grid() -> Any:
    """La rejilla de 1.654 × 1.699 celdas de 1 m."""
    return gis.Grid(cdata.WEST, cdata.NORTH, STEP_M, STEP_M, COLS, ROWS)


# --- Los taludes de los sectores --------------------------------------------------------------


def sector_rules() -> list[Any]:
    """La regla de pendiente de cada sector: su talud impuesto (:data:`IMPOSED`) o el talud
    general del perfil que se le asigna."""
    rules = []
    for index in range(1, SECTORS + 1):
        if index in IMPOSED:
            rules.append(envelopes.SlopeRule.from_degrees(IMPOSED[index]))
        else:
            rules.append(envelopes.SlopeRule(profile_of(index).general_tan))
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
    return tuple(
        cmodel.Sector(f"sector{index:02d}".ljust(32, "0"), code, name,
                      (_ring(left, bottom, right, top),))
        for index, code, name, left, bottom, right, top in sector_boxes())


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
def scale_project(*, folder: Path | None = None, userdata: Path | None = None
                  ) -> Iterator[DesignScale]:
    """El proyecto de escala (véase el módulo), con lo que registrará ``bl`` para que ``design``
    calcule y registre. Al salir lo cierra y quita lo registrado; la carpeta (por defecto, una temporal
    propia en ``%TEMP%``, que se borra) la pone quien llama con ``folder`` (spec 015, T33: la de la red,
    que borra él) y los datos de usuario, en ``userdata`` (por defecto, dentro de ella)."""
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
        if folder is None:
            folder = stack.enter_context(project_tmp("gb-diseno-"))
        clock = FakeClock()
        (folder / "proyectos").mkdir()
        settings = make_settings(window=cdata.window(), grid_step_m=STEP_M)
        user = userdata_mod.UserData(userdata or folder / "u")
        project = create.create_project(folder / "proyectos", settings, make_session(), user,
                                        clock=clock).project
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


def sectors_request(data: DesignScale, name: str) -> Any:
    """La envolvente del cálculo completo: descendente desde las semillas en anillo con la
    pendiente de cada sector (diez perfiles y los dos taludes impuestos)."""
    del data
    return _envelope(name, design_model.SeedSource("grid", grid=RING_GRID), slope_mode="sectors",
                     slope_deg=None, base_profile=PROFILES[0].code, sector_profiles=assigned())


def design_request(data: DesignScale, name: str, envelope: str) -> Any:
    """El escalonado en corte de ``envelope`` con el perfil de cada sector."""
    del data
    return design_model.DesignRequest(name=name, envelope=envelope, sense="cut",
                                      base_profile=PROFILES[0].code, sector_profiles=assigned(),
                                      anchor_grid=None)

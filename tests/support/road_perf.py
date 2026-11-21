# SPDX-License-Identifier: GPL-3.0-or-later
"""Los datos de rendimiento de las pistas y rampas (spec 017, T34; plan 017 §7.1 y §7.3; RNF-017-01 a 08 y 10;
``tests/rendimiento/des/test_roads_perf.py``): los de §2.2 del plan 013 (``design_perf``: la rejilla de 1.654 × 1.699 celdas de 1 m
—2,81 M—, con su terreno y las máscaras de V01 al día) con lo que añaden la 014, la 015, la 016 y la 017. Solo sintéticos: se generan al
pedirlos, no se versionan y los borra quien los escribe; ningún dato de cliente. Los terrenos, los ejes y las cajas de berma a escala son
los de ``road_data`` (T01); aquí se añaden los casos de la ruta de §7.3 (el llano, el barranco, la franja de 60 m y la ladera del 38 %
a 22,5°), el eje de 2 km **compacto** (cuya ventana de grabado cabe en 2 M celdas) y el proyecto.

- **Los casos de la ruta** (:class:`RouteCase`, :func:`route_cases`; plan §7.3): la ruta de 1,5 km con la malla de 4 m, el paso de cota de
  0,28 m, 14 m de altura y 16 rumbos, sobre el terreno que se pida y con la holgura del pasillo que se pida; :func:`run_route` la corre
  por pasos (la red 2D desde los dos extremos, el pasillo y la búsqueda) y da lo que tardó cada parte, el resultado y las llamadas.
- **El eje compacto** (:func:`compact_axis_2km`): 2.035 m con 61 curvas que giran 70° (la ventana de grabado de la caja de §7.3 es de
  1,6 M celdas, no de 2,42 M como la del eje en diagonal de ``road_data.scale_axis_2km``: la cláusula «una caja de ≤ 2 M celdas» de
  RNF-017-04).
- **El grabado** (:func:`engrave_case`): el trabajo, la sección y la rasante de un eje (la de ``milestone_road_engrave.ScaleTest``: un plano
  que sube al noreste y una rasante que sube y baja 2,5 m cada 300 m sobre el terreno del eje).
- **La accesibilidad** (:func:`access_job`): 250 tramos de berma, 5 plataformas y 20 zonas «requiere acceso» sobre 2,81 M celdas
  (``milestone_road_access_berms.ScaleTest``) con una franja intocable que parte la rejilla.
- **El proyecto de escala** (:func:`scale_project`): el de la 015 (``entity_perf.scale_project``) con lo que registra ``bl`` para la 017
  (las familias de parámetros, los cuatro tipos de operación con las funciones **reales** de recalcular y las cifras), el perfil de pista
  de referencia (solo de las pruebas), los terrenos y las capas de escala escritos en él.
- **Llevar las órdenes** (:func:`calculate`, :func:`cycle`): «Calcular» y «Crear» una pista o la accesibilidad como la orden, con lo que
  tardó cada parte, las llamadas del hilo (cada ``next`` de los pasos, en pared y en CPU del proceso) y lo que dejó en disco.

Python de Blender (su numpy 2.3.4) y biblioteca estándar.
"""

from __future__ import annotations

import dataclasses
import math
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from tests.support import design_perf as dperf
from tests.support import entity_perf as ep
from tests.support import road_data as rd
from tests.support import road_scale
from tests.support import stockpile_data as sdata
from tests.support import stockpile_perf as sp
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.res_fixtures import write_grids

core_params = import_geoblender("core.params")
design_params = import_geoblender("design.params")
design_store = import_geoblender("design.store")
entity_store = import_geoblender("design.entity_store")
gis = import_geoblender("gis")
provenance = import_geoblender("design.provenance")
res_provenance = import_geoblender("reserves.provenance")
road_access = import_geoblender("design.road_access")
road_axis = import_geoblender("design.road_axis")
road_engrave = import_geoblender("design.road_engrave")
road_model = import_geoblender("design.road_model")
road_net = import_geoblender("design.road_net")
road_profiles = import_geoblender("design.road_profiles")
road_route = import_geoblender("design.road_route")
road_section = import_geoblender("design.road_section")
road_store = import_geoblender("design.road_store")
steps = import_geoblender("design.steps")

__all__ = [
    "AXES", "ENTRIES", "POINTS", "PROFILE_CODE", "RAVINE", "AccessCase", "Calls", "EngraveCase", "RouteCase", "RouteRun",
    "Calculated", "access_case", "access_request", "axis_request", "calculate", "compact_axis_2km", "cycle", "drain", "engrave_case", "flat_terrain",
    "hillside_case", "ravine_case", "road_request", "route_case", "route_cases", "route_peak_bytes", "run_route", "scale_project", "strip_case", "timed_steps",
]

Calls = sp.Calls
"""Las llamadas del hilo de Blender de unos pasos: cuántas, la más larga en pared y en CPU del proceso."""
USER = sp.USER
PROFILE_CODE = "pista_principal"
"""El código del perfil de pista de referencia del proyecto de escala (``road_data.PROFILE``, solo de las pruebas)."""
RAVINE = "gis_dtm_barranco"
"""El terreno del barranco de 14 m a medio camino de la ruta de 1,5 km, como rejilla del proyecto de escala."""
HILLSIDE = "gis_dtm_ladera"
"""La ladera del 38 % con la curva de nivel a 22,5°, como rejilla del proyecto de escala."""
POINTS = "gis_fea_pistas_escala_puntos"
"""Las capas de puntos de las pistas de escala: el origen y el destino de la ruta del barranco y de la de la ladera."""
AXES = "gis_fea_pistas_escala_ejes"
"""La capa de ejes de las pistas de escala: el eje de 2 km en diagonal (``Eje de 2 km``), el compacto (``Eje compacto``) y 20 de 1,5 km
(``Eje 01`` a ``Eje 20``), uno por pista de la revisión de RNF-017-10."""
ENTRIES = "gis_fea_pistas_escala_entradas"
"""La capa de puntos de entrada de la accesibilidad de escala."""
CHAIN_ROADS = rd.SCALE_ROADS
"""Las pistas de la revisión de RNF-017-10 (``road_data.SCALE_ROADS``: 20)."""
RAVINE_ORIGIN, RAVINE_DESTINATION = "Origen del barranco", "Destino del barranco"
HILL_ORIGIN, HILL_DESTINATION = "Origen de la ladera", "Destino de la ladera"
WALK_SLOPE_PCT, WALK_WIDTH_M, MIN_BERM_AREA_M2 = 12.0, 10.0, 300.0
"""La pendiente transitable, el ancho mínimo (HIPÓTESIS de la prueba: ninguno es valor por defecto) y el área mínima de berma de la referencia
de IMGA (300 m²), como en ``milestone_road_access_berms``."""
WALL_X0_M, WALL_X1_M = 700.0, 712.0
"""La franja intocable que parte la rejilla de la accesibilidad (x local, m)."""


# --- Los casos de la ruta (plan §7.3) -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RouteCase:
    """Un caso de la ruta de 1,5 km sobre la rejilla de escala: el terreno, lo que no se pisa (``None``: nada), el origen y el destino
    (absolutos), la holgura del pasillo y el presupuesto de estados."""

    name: str
    surface: np.ndarray
    mask: np.ndarray | None
    origin: tuple[float, float]
    destination: tuple[float, float]
    margin_m: float
    budget: int = rd.ROUTE.search_budget

    def job(self) -> Any:
        """El ``RoadJob`` del caso en el modo «trazar», con los parámetros de la referencia (``road_data.ROUTE``) y la holgura de este caso."""
        route = dataclasses.replace(rd.ROUTE, margin_m=self.margin_m, search_budget=self.budget)
        return rd.route_job(rd.scale_grid(), self.surface, self.origin, self.destination, route=route, untouchable=self.mask)


def _absolute(point: tuple[float, float]) -> tuple[float, float]:
    found = rd.absolute([point], rd.scale_grid())[0]
    return float(found[0]), float(found[1])


def flat_terrain(grid: Any | None = None) -> np.ndarray:
    """El terreno **llano** del plan §7.3: una pendiente del 4 % hacia el este con ondas de ±8 m de 1 km de longitud (la mayor pendiente,
    del 5,0 %): la ruta cabe en un rumbo y la búsqueda apenas se ensancha."""
    found = rd.scale_grid() if grid is None else grid
    x, _y = rd.local_centers(found)
    return 100.0 + 0.04 * x + 8.0 * np.sin(2.0 * np.pi * x / 1_000.0)


def _route_ends(origin: tuple[float, float], destination: tuple[float, float]) -> dict[str, Any]:
    return {"origin": _absolute(origin), "destination": _absolute(destination)}


def flat_case(margin_m: float = 60.0, budget: int = rd.ROUTE.search_budget) -> RouteCase:
    """El llano con la holgura de 60 m (21.978 nodos y 35,5 M estados posibles en el plan; 390 expandidos)."""
    spec = rd.scale_ravine_spec()
    return RouteCase(f"llano, holgura de {margin_m:g} m", flat_terrain(), None, margin_m=margin_m, budget=budget,
                     **_route_ends(spec.origin, spec.destination))


def ravine_case(margin_m: float, budget: int = rd.ROUTE.search_budget) -> RouteCase:
    """El barranco de 14 m a medio camino de la ruta de 1.500 m (el de ``road_data.scale_ravine_terrain``) con la holgura ``margin_m``
    (2 y 4 m: 1.120 y 1.860 nodos; 60 m: 21.978 nodos y 7,5 M estados, que el presupuesto de 5 M detiene)."""
    spec = rd.scale_ravine_spec()
    return RouteCase(f"barranco, holgura de {margin_m:g} m", rd.scale_ravine_terrain(), None, margin_m=margin_m, budget=budget,
                     **_route_ends(spec.origin, spec.destination))


def strip_case(width_m: float = 60.0) -> RouteCase:
    """El barranco con **una franja de ``width_m`` m de ancho** (lo demás, intocable) a lo largo de la ruta: la franja de 60 m del plan §7.3 y de
    RNF-017-02 (5.640 nodos en el plan; aquí, ≈ 5.400), con la holgura de 60 m (el pasillo es la franja entera)."""
    grid = rd.scale_grid()
    spec = rd.scale_ravine_spec()
    _x, y = rd.local_centers(grid)
    centre = spec.origin[1]
    mask = ~((y > centre - width_m / 2.0) & (y < centre + width_m / 2.0))
    return RouteCase(f"barranco con una franja de {width_m:g} m", rd.scale_ravine_terrain(), mask, margin_m=60.0,
                     **_route_ends(spec.origin, spec.destination))


def hillside_case(margin_m: float, budget: int = rd.ROUTE.search_budget) -> RouteCase:
    """La ladera del 38 % con la curva de nivel a 22,5° (``road_data.hillside_terrain``) y una ruta de 1.500 m **a lo largo de la curva de nivel**
    (los 16 rumbos solo la siguen a trozos: el caso difícil del plan §7.3: de 9.239 nodos con 2 m de holgura a ≈ 31.000 con 60 m)."""
    angle = math.radians(rd.HILL_CONTOUR_DEG)
    origin = (100.0, 200.0 + math.tan(angle) * (100.0 - 200.0))
    destination = (origin[0] + 1_500.0 * math.cos(angle), origin[1] + 1_500.0 * math.sin(angle))
    return RouteCase(f"ladera del 38 %, holgura de {margin_m:g} m", rd.hillside_terrain(rd.scale_grid()), None, margin_m=margin_m, budget=budget,
                     **_route_ends(origin, destination))


_CASES: dict[str, Callable[[], RouteCase]] = {
    "flat": lambda: flat_case(60.0), "ravine_2": lambda: ravine_case(2.0), "ravine_4": lambda: ravine_case(4.0), "strip": lambda: strip_case(60.0),
    "ravine_60": lambda: ravine_case(60.0), "hill_2": lambda: hillside_case(2.0), "hill_8": lambda: hillside_case(8.0), "hill_60": lambda: hillside_case(60.0)}


def route_case(key: str) -> RouteCase:
    """El caso de la ruta de RNF-017-02 ``key`` (``KeyError`` si no es uno de :func:`route_cases`): el terreno se construye al pedirlo (≈ 0,05 s y 22 MB)."""
    return _CASES[key]()


def route_cases() -> dict[str, RouteCase]:
    """Los casos de la ruta de RNF-017-02 por su clave: el llano, el barranco con 2, 4 y 60 m de holgura, la franja de 60 m y la ladera con 2, 8 y 60 m."""
    return {key: make() for key, make in _CASES.items()}


_PEAK_SCRIPT = """
import ctypes, gc, sys
from ctypes import wintypes

class Counters(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

def peak():
    kernel, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    found = Counters()
    found.cb = ctypes.sizeof(Counters)
    assert psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(found), found.cb)
    return found.PeakWorkingSetSize

from tests.support import road_perf as rp
case = rp.route_case(sys.argv[1])
gc.collect()
before = peak()
run = rp.run_route(case)
print(before, peak(), run.route.expanded, run.route.seen, run.route.ok)
"""


def route_peak_bytes(key: str) -> tuple[int, int, Any]:
    """El pico de memoria **adicional** del proceso (``PeakWorkingSetSize`` de Windows, que cuenta lo de numpy y lo del intérprete) de la ruta ``key``, medido en un **proceso nuevo**
    (el pico de un proceso no baja: cada caso, el suyo): lo que sube desde que está el terreno construido hasta el final de la ruta. Da ``(bytes añadidos, bytes de partida, la ruta
    como (expandidos, vistos, ok))``. Es la medida del plan §7.3 («pico del proceso») y vale **donde ``tracemalloc`` no se puede usar**: sus 7 M de entradas de diccionario lo hacen 48
    veces más lento (``docs/trampas.md``)."""
    import os
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[2]
    done = subprocess.run([sys.executable, "-B", "-s", "-X", "utf8", "-c", _PEAK_SCRIPT, key], cwd=root, env={**os.environ, "PYTHONPATH": os.pathsep.join(
        [str(root), os.environ.get("PYTHONPATH", "")])}, capture_output=True, text=True, check=False, timeout=1_800)
    if done.returncode != 0:
        raise RuntimeError(f"la medida del pico de memoria de «{key}» falló: {done.stderr[-2000:]}")
    before, after, expanded, seen, ok = done.stdout.split()[-5:]
    return int(after) - int(before), int(before), (int(expanded), int(seen), ok == "True")


@dataclass(frozen=True, slots=True)
class RouteRun:
    """Una ruta corrida entera por pasos: la red 2D desde los dos extremos, el pasillo y la búsqueda. Los tiempos son de pared (s); ``cpu_s``,
    del proceso; ``calls`` son las llamadas de los pasos de la red 2D y de la búsqueda."""

    corridor: Any
    route: Any
    mesh_s: float
    network_s: float
    search_s: float
    cpu_s: float
    calls: Calls

    @property
    def total_s(self) -> float:
        return self.mesh_s + self.network_s + self.search_s


def timed_steps(work: Iterator[Any]) -> tuple[Any, float, Calls]:
    """Lleva unos pasos hasta el final: el último resultado que dieron, lo que tardó (pared, s) y sus :class:`Calls`."""
    began = time.perf_counter()
    result, calls = sp.drain(work)
    return result, time.perf_counter() - began, calls


def _merge(first: Calls, second: Calls) -> Calls:
    return Calls(first.count + second.count, max(first.longest_s, second.longest_s), max(first.longest_cpu_s, second.longest_cpu_s))


def run_route(case: RouteCase) -> RouteRun:
    """La ruta de ``case`` como la prepara «Calcular»: la malla, la red 2D desde el destino y desde el origen, el pasillo (la holgura del caso) y
    la búsqueda A\\* por pasos de 0,05 s. Da lo que tardó cada parte y las llamadas (la red 2D y la búsqueda)."""
    job = case.job()
    cpu = time.process_time()
    began = time.perf_counter()
    mesh = road_net.route_mesh(job.grid, job.start, job.route.mesh_m, job.untouchable, avoid_weight=job.avoid_weight)
    meshed = time.perf_counter()
    pd = job.profile.max_gradient_pct / 100.0
    height = job.route.max_cut_fill_m
    target = road_route.route_target(job, mesh)
    net_dest, _wall, calls = timed_steps(road_net.network_steps(mesh, target, pd, height, budget_s=0.05))
    net_origin, _wall, again = timed_steps(road_net.network_steps(mesh, mesh.node_of(*job.geometry.origin), pd, height, budget_s=0.05))
    calls = _merge(calls, again)
    corridor = road_net.corridor(net_origin, net_dest, job.route.margin_m)
    networked = time.perf_counter()
    found, _wall, search = timed_steps(road_route.route_steps(job, corridor, budget_s=0.05))
    done = time.perf_counter()
    return RouteRun(corridor, found, meshed - began, networked - meshed, done - networked, time.process_time() - cpu, _merge(calls, search))


# --- El eje de 5 km y el compacto de 2 km -----------------------------------------------------------------------------


def compact_axis_2km() -> np.ndarray:
    """El eje de 61 curvas **compacto** (``road_scale.compact_axis_2km``: 2.035 m de poligonal y 1.817 m con las curvas; sus curvas giran 70°): su ventana de grabado (con el
    alcance de 60 m) es de **1,73 M celdas**, dentro de la caja de ≤ 2 M celdas de RNF-017-04 (el eje de ``road_data.scale_axis_2km``, de ±10°, da 2,42 M)."""
    return road_scale.compact_axis_2km()


@dataclass(frozen=True, slots=True)
class EngraveCase:
    """Lo que pide grabar un eje: el trabajo (``RoadJob`` en «sobre un eje»), la sección en la ventana de trabajo, la rasante por celda y el
    eje; ``cells`` es el tamaño de la ventana."""

    job: Any
    section: Any
    levels: Any
    axis: Any

    @property
    def cells(self) -> int:
        rows, cols = self.section.window
        return (rows.stop - rows.start) * (cols.stop - cols.start)


PROJECT = {design_params.TOLERANCE_FACE: 1.0, design_params.VERIFY_MIN_THICKNESS: 0.05, design_params.EDGE_MAX_STEP: 1.0,
           design_params.EDGE_MIN_SHARE: 99.0}
"""Los parámetros del proyecto que lee el borde (los valores de ``milestone_road_engrave``, no de un proyecto)."""
WAVE_M, WAVE_PERIOD_M = 2.5, 300.0
"""La rasante sube y baja 2,5 m sobre el terreno del eje cada 300 m (desmonte y terraplén a tramos)."""


def engrave_case(line: np.ndarray, profile: rd.ProfileData = rd.PROFILE) -> EngraveCase:
    """El grabado de ``line`` (absoluta, ``(k, 2)``) sobre un plano que sube al noreste (8,5 % en la diagonal) con una rasante que sube y baja
    sobre el terreno del eje (:data:`WAVE_M` cada :data:`WAVE_PERIOD_M` m): lo mismo que ``milestone_road_engrave.ScaleTest``."""
    grid = rd.scale_grid()
    x, y = rd.local_centers(grid)
    terrain = np.asarray(150.0 + 0.06 * (x + y), dtype=np.float64)
    axis = road_axis.axis_of(line, profile.curve_radius_m, profile.min_radius_m, profile.station_step_m)
    road_profile = rd.road_profile(profile)
    window = road_engrave.engrave_window(axis, road_profile, grid)
    section = road_section.section_cells(axis, profile.carriageway_m, profile.shoulder_m, profile.berm_m, terrain, grid, window)
    on_axis = road_section.sample_terrain(terrain, grid, axis.points[:, 0], axis.points[:, 1])
    wave = WAVE_M * np.sin(2.0 * np.pi * axis.stations / WAVE_PERIOD_M)
    job = rd.axis_job(grid, terrain, line, profile=profile)
    return EngraveCase(job, section, section.levels(axis.stations, on_axis + wave), axis)


# --- La accesibilidad (RNF-017-05) --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AccessCase:
    """La accesibilidad de §7.3: la rejilla, el terreno, la franja intocable, las bermas (una rejilla de cotas), las plataformas y las zonas."""

    grid: Any
    terrain: np.ndarray
    wall: np.ndarray
    levels: np.ndarray
    platforms: tuple[Any, ...]
    zones: tuple[Any, ...]

    def job(self, *, final: bool = False) -> Any:
        """El ``AccessJob``: una entrada al oeste de la franja, los umbrales de la referencia y, con ``final``, la superficie final de una cantera."""
        return rd.access_job(self.grid, self.terrain, [(10.5, 10.5)], untouchable=self.wall,
                             access=rd.AccessData(WALK_SLOPE_PCT, WALK_WIDTH_M, MIN_BERM_AREA_M2),
                             final=self.terrain + 0.5 if final else None, berms=[road_model.BermGrid("bancos", self.levels)],
                             platforms=self.platforms, zones=self.zones)


def access_case() -> AccessCase:
    """Los 250 tramos de berma de 640 m², las 5 plataformas y las 20 zonas «requiere acceso» de ``road_data`` sobre 2,81 M celdas, con una franja
    intocable de 12 m que parte la rejilla (la entrada al oeste: 110 tramos y 3 plataformas comunicados y la mitad de las zonas, no)."""
    grid = rd.scale_grid()
    x, y = rd.local_centers(grid)
    terrain = 150.0 + 4.0 * np.sin(x / 150.0) + 3.0 * np.cos(y / 120.0)
    wall = rd.in_box((WALL_X0_M, 0.0, WALL_X1_M, float(grid.nrows)), grid)
    levels = np.full(grid.shape, np.nan)
    for index, box in enumerate(rd.scale_berm_boxes()):
        levels[rd.in_box(box, grid)] = 100.0 + index

    def cells(box: tuple[float, float, float, float]) -> np.ndarray:
        return np.flatnonzero(rd.in_box(box, grid).ravel())

    platforms = tuple(road_model.AccessCells(f"PLT-{n:03d}", f"P{n}", cells(box)) for n, box in enumerate(rd.scale_platform_boxes(), start=1))
    zones = tuple(road_model.AccessCells(f"z{n}", f"Z{n}", cells(box)) for n, box in enumerate(rd.scale_zone_boxes(), start=1))
    return AccessCase(grid, terrain, wall, levels, platforms, zones)


# --- El proyecto de escala --------------------------------------------------------------------------------------------


def _never(request: Any) -> Any:
    raise AssertionError("las pruebas de rendimiento de las pistas no reproducen")


def _recompute(request: Any) -> Any:
    """Lo que registra ``bl`` como función de recálculo de los tipos de la 017: lleva sus pasos hasta el final."""
    handle, work = design_store.recompute_run(request)
    ep.finish(work)
    return handle


def _axes_layer() -> Any:
    """La capa de ejes de las pistas de escala: el de 2 km en diagonal, el compacto y los 20 de la revisión de RNF-017-10 (``road_scale.chain_axes``: 1,5 km de ondas)."""
    entities = [((road_scale.axis_2km(),),), ((road_scale.compact_axis_2km(),),), *(((line,),) for line in road_scale.chain_axes())]
    names = ("Eje de 2 km", "Eje compacto", *(f"Eje {number:02d}" for number in range(1, CHAIN_ROADS + 1)))
    return sdata.FieldsLayer(AXES, "line", tuple(entities), names, {})


def _points_layer() -> Any:
    """Los puntos de origen y de destino de la ruta del barranco y de la ladera (absolutos)."""
    ravine = rd.scale_ravine_spec()
    hill = hillside_case(2.0)
    points = [_absolute(ravine.origin), _absolute(ravine.destination), hill.origin, hill.destination]
    names = (RAVINE_ORIGIN, RAVINE_DESTINATION, HILL_ORIGIN, HILL_DESTINATION)
    return sdata.FieldsLayer(POINTS, "point", tuple(((np.array([point]),),) for point in points), names, {})


def _entries_layer() -> Any:
    """La entrada de la accesibilidad de escala (local (10,5; 10,5)): al oeste de la franja intocable."""
    point = _absolute((10.5, 10.5))
    return sdata.FieldsLayer(ENTRIES, "point", (((np.array([point]),),),), ("Entrada",), {})


def _write(data: dperf.DesignScale) -> None:
    """Escribe en el proyecto de escala los terrenos del barranco y de la ladera, las capas y el perfil de pista de referencia."""
    grid = dperf.grid()
    write_grids(data.project, [
        ("barranco", gis.Raster(grid, rd.scale_ravine_terrain(), sdata.CRS, sdata.VERTICAL)),
        ("ladera", gis.Raster(grid, rd.hillside_terrain(grid), sdata.CRS, sdata.VERTICAL))], message="Terrenos de escala de las pistas")
    for layer in (_axes_layer(), _points_layer(), _entries_layer()):
        sdata.write_layer(data.project, data.clock, layer)
    declared = road_profiles.ProfileDeclaration("ITC 07.1.03 de la prueba", USER, "Perfil de la prueba de rendimiento")
    values = {param: getattr(rd.PROFILE, "class_name" if param.value == "class" else param.value) for param in design_params.RoadProfileParam}
    data.clock.advance(minutes=1)
    road_profiles.edit_road_profiles(data.project, (road_profiles.ProfileEdit(name=PROFILE_CODE.upper(), values=values),), declared)
    data.clock.advance(minutes=1)


@contextmanager
def scale_project(*, folder: Path | None = None, userdata: Path | None = None) -> Iterator[dperf.DesignScale]:
    """El proyecto de escala de la 015 (``entity_perf.scale_project``: 2,81 M celdas de 1 m, V01 y V02, las máscaras de V01 al día, los diez
    perfiles de banco) con lo que registra ``bl`` para la 017 (las familias de parámetros de la pista, de la accesibilidad y del perfil, los
    cuatro tipos de operación con las funciones **reales** de recalcular, la edición de los perfiles y las cifras) y los datos de la escala
    (:func:`_write`). ``folder`` y ``userdata``: dónde se crea (el de la red); al salir lo quita todo."""
    with ExitStack() as stack:
        data = stack.enter_context(ep.scale_project(folder=folder, userdata=userdata))
        core_params.register_families(design_params.ROAD_PROFILE_FAMILIES)
        core_params.register_families(design_params.ROAD_FAMILIES)
        core_params.register_families(design_params.ACCESS_FAMILIES)
        stack.callback(core_params.unregister_families, "des")
        recompute = dict.fromkeys(provenance.ROAD_VERSION_TYPES, _recompute)
        reproduce = dict.fromkeys(provenance.ROAD_REPRODUCIBLE, _never)
        stack.enter_context(registered(*provenance.road_operation_defs(recompute, reproduce), *provenance.ROAD_PROFILE_OPERATIONS,
                                       *provenance.ROAD_FIGURES, *provenance.ACCESS_FIGURES))
        _write(data)
        yield data


# --- Las peticiones ------------------------------------------------------------------------------------------------------


def axis_request(name: str, feature: str, *, start: str = dperf.START, profile: str = PROFILE_CODE, **changes: Any) -> Any:
    """La pista «sobre un eje» de la línea ``feature`` de :data:`AXES` sobre ``start``."""
    return road_model.RoadRequest(name, road_model.LayerFields(AXES, "nombre"), "on_axis", profile, start, feature=feature, **changes)


def road_request(name: str, origin: str, destination: str, surface: str, *, margin_m: float = 2.0, profile: str = PROFILE_CODE,
                 **changes: Any) -> Any:
    """La pista «trazar» de ``origin`` a ``destination`` (puntos de :data:`POINTS`) sobre ``surface``, con los parámetros de la ruta de la
    referencia (``road_data.ROUTE``: malla de 4 m, paso de cota de 0,28 m…) y la holgura ``margin_m``."""
    route = {name_: getattr(rd.ROUTE, name_) for name_ in rd.RouteData.__slots__}
    route["margin_m"] = margin_m
    return road_model.RoadRequest(name, road_model.LayerFields(POINTS, "nombre"), "trace", profile, surface, origin=origin,
                                  destination=destination, **{**route, **changes})


def access_request(name: str, surface: str = dperf.START, **changes: Any) -> Any:
    """La accesibilidad de la capa :data:`ENTRIES` sobre ``surface`` con los umbrales de la referencia (:data:`WALK_SLOPE_PCT`…)."""
    return road_model.AccessRequest(name, road_model.LayerFields(ENTRIES, "nombre"), surface, walk_slope_pct=WALK_SLOPE_PCT,
                                    walk_width_m=WALK_WIDTH_M, min_berm_area_m2=MIN_BERM_AREA_M2, **changes)


# --- Llevar las órdenes --------------------------------------------------------------------------------------------------


def drain(work: Iterator[Any]) -> tuple[Any, Calls, dict[str, float]]:
    """Lleva unos pasos hasta el final: el último resultado que dieron, sus :class:`Calls` (cada ``next``, en pared y en CPU del proceso) y lo que tardó cada fase
    (``Progress.phase``, s de pared: el tiempo de cada llamada se carga a la fase del paso que devuelve)."""
    result, count, longest, longest_cpu = None, 0, 0.0, 0.0
    phases: dict[str, float] = {}
    iterator = iter(work)
    while True:
        wall, cpu = time.perf_counter(), time.process_time()
        try:
            step = next(iterator)
        except StopIteration:
            break
        spent = time.perf_counter() - wall
        longest = max(longest, spent)
        longest_cpu = max(longest_cpu, time.process_time() - cpu)
        count += 1
        phases[step.phase] = phases.get(step.phase, 0.0) + spent
        if step.result is not None:
            result = step.result
    return result, Calls(count, longest, longest_cpu), phases


@dataclass(frozen=True, slots=True)
class Calculated(sp.Calculated):
    """Lo de :class:`stockpile_perf.Calculated` con lo que tardó cada fase de «Calcular» (``phases``: la fase de los pasos por su nombre → s de pared)."""

    phases: Mapping[str, float] = field(default_factory=dict)


def calculate(data: dperf.DesignScale, run: Any, request: Any, *, confirm: dict[str, Any] | None = None, chain: bool = False,
              **options: Any) -> Calculated:
    """«Calcular» (``run``: ``steps.road_run`` o ``steps.access_run``, con el presupuesto de la interfaz, 0,05 s) y «Crear» ``request`` en V01
    como lo hace la orden: lo que tardó cada parte, las llamadas de «Calcular», lo que tardó cada fase y lo que dejó en disco. ``confirm``: las confirmaciones de la pista
    (``Calculation.confirm_road``). Con ``chain``, además lo que la orden encadena (``entity_store.after_entity_change``), medido aparte y **sin contar** en
    ``disk_bytes``."""
    before_db = ep.database_bytes(data.project)
    before_files = sp.rasters_bytes(data.project)
    began = time.perf_counter()
    calculation, calls, phases = drain(run(data.project, request, version=options.pop("version", None) or data.v1.uid, budget_s=0.05, **options))
    calculated = time.perf_counter()
    with calculation:
        if confirm:
            calculation.confirm_road(**confirm)
        stored = calculation.create(decided_by=USER)
    created = time.perf_counter()
    after = sp.rasters_bytes(data.project)
    new = sum(size for name, size in after.items() if before_files.get(name) != size)
    db = ep.database_bytes(data.project) - before_db
    chain_s = 0.0
    if chain:
        began_chain = time.perf_counter()
        ep.finish(entity_store.after_entity_change(data.project, data.v1.uid))
        chain_s = time.perf_counter() - began_chain
    return Calculated(calculated - began, created - calculated, db, new, calls, calculation, stored, chain_s, phases)


def cycle(data: dperf.DesignScale, run: Any, request: Any, *, chain: bool = True, **options: Any) -> Calculated:
    """:func:`calculate` y, si la pista parte de una superficie (de cada superficie parte una sola), **descartarla** con lo que la orden
    encadena, para repetir la medida con otro nombre: lo que pasa de descartar no cuenta. La accesibilidad no se descarta (no es una entidad
    ni tiene «Descartar»): se repite con otro nombre."""
    data.clock.advance(minutes=1)
    made = calculate(data, run, request, chain=chain, **options)
    data.clock.advance(minutes=1)
    if isinstance(request, road_model.RoadRequest):
        ep.finish(entity_store.discard_entity_steps(data.project, data.v1.uid, made.calculation.entity.code, reason="Medición de rendimiento"))
    return made

# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendimiento de las pistas y rampas y de su accesibilidad (spec 017, T34; RNF-017-01 a RNF-017-08 y RNF-017-10; plan 017 §7.1 y §7.3,
``tests/rendimiento/des``), con la forma de ``test_stockpiles_perf.py`` de la 016: los guiones de medida de ``plan.md`` §7.3 (que vivían en el
*scratchpad* de la sesión del plan y no estaban versionados) convertidos en pruebas.

Se ejecuta con ``tools/check.py --rendimiento``, nunca en el «verde»: el Python de Blender (su numpy 2.3.4), en el PC de referencia de la spec 001
§5 y en disco local (``%TEMP%``). Cada cifra se imprime en una línea ``RNF-017-nn: …`` con el equipo y el intérprete y se compara con su
presupuesto, **sin relajarlo**. **Mediana de 5** las medidas de hasta unos 3 s; **de 3** las de hasta unos 20 s (la franja de 60 m, el grabado de
2 km) y **una sola corrida** las de la ladera del 38 % y del barranco con 60 m de holgura (de 26 a 70 s cada una; el plan §7.3 también las midió
con una o dos corridas): una prueba que tarda más de un minuto no se repite cinco veces, y la cifra que cuenta es su máximo, no su media.

**Datos** (``tests/support/road_perf.py`` y ``road_data.py``, T01, que no versionan ninguno): la rejilla de 1.654 × 1.699 celdas de 1 m (2,81 M) del
plan 013 con sus terrenos (el llano, el barranco de 14 m, la ladera del 38 % a 22,5°), la ruta de 1,5 km con la malla de 4 m, el paso de cota de
0,28 m, 14 m de altura y 16 rumbos, los ejes de 2 km (en diagonal y compacto) y de 5 km, y la accesibilidad con 250 tramos de berma, 5 plataformas y
20 zonas «requiere acceso». El proyecto de escala (:func:`~tests.support.road_perf.scale_project`) es el de la 015 con las familias, los tipos de
operación, el perfil de pista de referencia (**solo de las pruebas**, D-2) y los terrenos y las capas de escala.

- RNF-017-01 (:class:`NetworkTest`): la red 2D de las dos corridas (el origen y el destino) sobre los 175.950 nodos de la malla de 4 m, ≤ 10 s (en
  ``Z:``, ≤ 20 s, con el proyecto :class:`NetworkRoadProjectTest`; previsto 0,7 s).
- RNF-017-02 (:class:`RouteTest`): la ruta 3D de ≈ 1,5 km, ≤ 90 s (en ``Z:``, ≤ 180 s) y ≤ 1,3 GB **para cualquier pasillo** (la búsqueda se detiene
  a su presupuesto de 5 M estados expandidos) y ≤ 30 s con una franja de 60 m de ancho.
- RNF-017-03 (:class:`AxisTest`): el eje con curvas y la rasante de 5 km con estaciones cada 1 m, ≤ 2 s (previsto 1,6 ms).
- RNF-017-04 (:class:`EngraveTest`): grabar 2 km con su borde, la métrica exacta y una caja de ≤ 2 M celdas, ≤ 15 s (en ``Z:``, ≤ 30 s), y ≤ 2 s con el
  *chamfer*. **Dos ejes**: el **compacto** (ventana de 1,73 M celdas: la caja de la spec) y el de la fixture ``road_data.scale_axis_2km``, **en
  diagonal** (2,42 M celdas: más que la caja de la spec; se compara con su presupuesto por celda de la ventana, como el hito, y se anota si pasa de 15 s).
- RNF-017-05 (:class:`AccessTest`): la accesibilidad de 2,81 M celdas con 250 tramos de berma, 5 plataformas y 20 zonas, ≤ 5 s (en ``Z:``, ≤ 10 s; previsto 0,17 s).
- RNF-017-06 (cada prueba de arriba): cada llamada del hilo de Blender de «Calcular» (cada ``next`` de los pasos del dominio con el presupuesto de la interfaz,
  0,05 s), en CPU del proceso, ≤ 0,2 s. Las órdenes reales, dentro de Blender (``perf_roads.py``).
- RNF-017-07 (las ``test_z_memory`` de cada clase): el pico de memoria adicional (``tracemalloc``, con la de numpy) ≤ 1,5 GB (la ruta, ≤ 1,3 GB: RNF-017-02), en una
  pasada aparte (multiplica el tiempo por ≈ 1,6).
- RNF-017-10 (:class:`DiskTest`): lo que guarda en el proyecto una pista (su superficie entera de 2,81 M celdas, comprimida, y sus tablas) ≤ 25 MiB y una revisión con
  20 pistas en cadena ≤ 0,5 GiB. **MiB y GiB son de 2^20 y 2^30 bytes.**

La vista previa con 20 pistas (RNF-017-08), cada llamada de las órdenes reales (RNF-017-06) y Esc a mitad de cada cálculo, dentro de Blender
(``perf_roads.py``); habilitar Geoblender (RNF-001-03), ``perf_registration.py``; la verificación de la 012 (RNF-012-02), ``tests/rendimiento/res/``.
"""

from __future__ import annotations

import gc
import statistics
import time
import unittest
from collections.abc import Callable
from contextlib import ExitStack
from typing import Any, ClassVar

import numpy as np

from tests.support import design_perf as dperf
from tests.support import entity_perf as ep
from tests.support import gis_perf, network
from tests.support import road_data as rd
from tests.support import road_perf as rp
from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender
from tests.support.resources import requires

road_axis = import_geoblender("design.road_axis")
road_access = import_geoblender("design.road_access")
entity_store = import_geoblender("design.entity_store")
road_engrave = import_geoblender("design.road_engrave")
road_gradient = import_geoblender("design.road_gradient")
road_model = import_geoblender("design.road_model")
road_net = import_geoblender("design.road_net")
steps = import_geoblender("design.steps")

NETWORK_BUDGET_S = 10.0  # RNF-017-01, en disco local
NETWORK_NETWORK_BUDGET_S = 20.0  # RNF-017-01 en Z:
ROUTE_BUDGET_S = 90.0  # RNF-017-02, en disco local, con cualquier pasillo
ROUTE_NETWORK_BUDGET_S = 180.0  # RNF-017-02 en Z:
STRIP_BUDGET_S = 30.0  # RNF-017-02, con una franja de 60 m de ancho
ROUTE_MEMORY_BYTES = int(1.3 * 1024**3)  # RNF-017-02: 1,3 GB para cualquier pasillo
AXIS_BUDGET_S = 2.0  # RNF-017-03
ENGRAVE_BUDGET_S = 15.0  # RNF-017-04, métrica exacta, caja de ≤ 2 M celdas, en disco local
ENGRAVE_NETWORK_BUDGET_S = 30.0  # RNF-017-04 en Z:
ENGRAVE_BOX_CELLS = 2_000_000  # la caja a que se refiere RNF-017-04
CREATE_BUDGET_S = 2.0  # «Crear» una pista con la ventana de más de 2 M celdas: escribe la rejilla entera (el plan midió ≈ 0,7 s de lectura y escritura); en Z:, el doble como los demás
CHAMFER_BUDGET_S = 2.0  # RNF-017-04, con el chamfer
ACCESS_BUDGET_S = 5.0  # RNF-017-05, en disco local
ACCESS_NETWORK_BUDGET_S = 10.0  # RNF-017-05 en Z:
CALL_BUDGET_S = 0.2  # RNF-017-06: cada llamada del hilo de Blender, en CPU
MEMORY_BUDGET_BYTES = int(1.5 * 1024**3)  # RNF-017-07: 1,5 GB
MIB = 1024**2
ENTITY_BUDGET_BYTES = 25 * MIB  # RNF-017-10: una pista, su superficie entera y sus tablas
REVISION_BUDGET_BYTES = int(0.5 * 1024**3)  # RNF-017-10: una revisión con 20 pistas
RUNS = 5  # mediana de 5 (la spec 017 §5), en las medidas de hasta unos 3 s
HEAVY_RUNS = 3  # mediana de 3 en las de hasta unos 20 s
NETWORK_RUNS = 3  # en Z: cada ejecución escribe superficies de 17 MiB: mediana de 3
CHAIN = rp.CHAIN_ROADS  # las pistas de la revisión de RNF-017-10
MACHINE = gis_perf.MACHINE
number = gis_perf.number
count = gis_perf.count
seconds_of = gis_perf.median_line


def mib(value: float) -> str:
    """Bytes en MiB de 2^20 (con coma decimal)."""
    return number(value / MIB, 2)


def gib(value: float) -> str:
    """Bytes en GiB de 2^30 (con coma decimal)."""
    return number(value / 1024**3, 3)


def ms(value: float) -> str:
    """Segundos en milisegundos enteros."""
    return number(value * 1000, 0)


def calls_line(found: list[rp.Calls]) -> str:
    """Las llamadas de ``found``: cuántas en la última corrida y la más larga de todas, en pared y en CPU (ayuda: no es una prueba)."""
    return (f"llamadas del hilo (presupuesto de {number(0.05, 2)} s): {found[-1].count} en la última, la más larga de todas "
            f"{ms(max(item.longest_s for item in found))} ms de pared y {ms(max(item.longest_cpu_s for item in found))} ms de CPU (presupuesto "
            f"{ms(CALL_BUDGET_S)} ms de CPU)")


class RoadsCase(unittest.TestCase):
    """Lo que tienen en común las clases de dominio: repetir una medida y comprobar el presupuesto de cada llamada."""

    def check_calls(self, found: list[rp.Calls], what: str) -> None:
        """Lo que pide el presupuesto de cada llamada del hilo: **el máximo** de la llamada más larga de cada corrida (no la media) no pasa de 0,2 s de CPU del proceso."""
        self.assertLessEqual(max(item.longest_cpu_s for item in found), CALL_BUDGET_S, f"{what}: una llamada del hilo pasa de 0,2 s de CPU")


# --- RNF-017-01: la red 2D ----------------------------------------------------------------------------------------------


class NetworkTest(RoadsCase):
    """RNF-017-01, RNF-017-06 y RNF-017-07 con la malla de 4 m de la rejilla de 2,81 M celdas (175.950 nodos, 16 rumbos): la red 2D desde el origen y desde
    el destino, en el terreno **libre** (el talud del 4 %) y en el **difícil** (la ladera del 38 % con un muro con hueco y 2 m de altura)."""

    PD, HEIGHT = 0.10, 14.0

    @classmethod
    def setUpClass(cls) -> None:
        cls.grid = rd.scale_grid()
        spec = rd.scale_ravine_spec()
        cls.ends = tuple(tuple(float(v) for v in rd.absolute([point], cls.grid)[0]) for point in (spec.origin, spec.destination))
        x, _y = rd.local_centers(cls.grid)
        wall = np.zeros(cls.grid.shape, dtype=bool)
        middle = cls.grid.ncols // 2
        wall[:, middle:middle + 12] = True
        wall[cls.grid.nrows - 80:cls.grid.nrows - 56, middle:middle + 12] = False
        cls.cases = {"el talud libre del 4 % (14 m de altura)": (100.0 + 0.04 * x, None, cls.HEIGHT),
                     "la ladera del 38 % con un muro con hueco (2 m de altura)": (100.0 + 0.38 * x, wall, 2.0)}

    def two_runs(self, key: str) -> tuple[float, float, rp.Calls, int, int]:
        """Las dos corridas de la red (el origen y el destino) del caso ``key``: el tiempo de la malla (s), el de las dos redes (s), las llamadas, los nodos alcanzados desde
        el origen y los de la malla."""
        surface, mask, height = self.cases[key]
        began = time.perf_counter()
        mesh = road_net.route_mesh(self.grid, surface, 4.0, mask)
        meshed = time.perf_counter()
        nets, calls = [], []
        for point in self.ends:
            found, _wall, called = rp.timed_steps(road_net.network_steps(mesh, mesh.node_of(*point), self.PD, height, budget_s=0.05))
            nets.append(found)
            calls.append(called)
        done = time.perf_counter()
        return meshed - began, done - meshed, rp.Calls(sum(item.count for item in calls), max(item.longest_s for item in calls),
                                                       max(item.longest_cpu_s for item in calls)), nets[0].reached, mesh.size

    def test_a_two_runs_of_the_2d_network(self) -> None:
        """RNF-017-01, RNF-017-06: las dos corridas de la red 2D (origen y destino) sobre los 175.950 nodos de la malla de 4 m, del talud libre del 4 % y de la
        ladera del 38 % con un muro con hueco, en ≤ 10 s (mediana de 5), con cada llamada ≤ 0,2 s de CPU."""
        for key in self.cases:
            made = [self.two_runs(key) for _ in range(RUNS)]
            networks = [item[1] for item in made]
            gis_perf.report(
                f"RNF-017-01: la red 2D de la malla de 4 m ({count(made[-1][4])} nodos, 16 rumbos) en {key}, las dos corridas "
                f"(origen y destino; {MACHINE}): {seconds_of(networks)}; la malla, {number(statistics.median(item[0] for item in made), 3)} s de mediana; "
                f"{count(made[-1][3])} nodos alcanzados; {calls_line([item[2] for item in made])}; presupuesto {number(NETWORK_BUDGET_S, 0)} s")
            self.assertGreater(made[-1][3], 10_000, f"{key}: casi nada alcanzable: no mide nada")
            self.assertLessEqual(statistics.median(networks), NETWORK_BUDGET_S, key)
            self.check_calls([item[2] for item in made], key)

    def test_z_memory(self) -> None:
        """RNF-017-07: el pico de memoria adicional (``tracemalloc``, con la de numpy) de la malla y las dos corridas de la red 2D del caso difícil ≤ 1,5 GB."""
        key = next(reversed(self.cases))
        peak = gis_perf.peak_bytes(lambda: self.two_runs(key))
        gis_perf.report(f"RNF-017-07: pico de memoria adicional (tracemalloc, con la de numpy) de la malla y la red 2D (las dos corridas) en {key} "
                        f"({MACHINE}): {number(peak / MIB, 0)} MiB; presupuesto {number(MEMORY_BUDGET_BYTES / MIB, 0)} MiB")
        self.assertLessEqual(peak, MEMORY_BUDGET_BYTES)


# --- RNF-017-02: la ruta 3D ---------------------------------------------------------------------------------------------


class RouteTest(RoadsCase):
    """RNF-017-02, RNF-017-06 y RNF-017-07 con la ruta de ≈ 1,5 km sobre la rejilla de 2,81 M celdas (la malla de 4 m, el paso de cota de 0,28 m, 14 m de
    altura, λ = 2 1/m y 16 rumbos): lo que tarda cada pasillo de §7.3 y lo que gasta el peor, con el presupuesto de 5 M estados expandidos."""

    cases: ClassVar[dict[str, rp.RouteCase]] = {}

    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = rp.route_cases()

    def line(self, key: str, found: list[rp.RouteRun], budget_s: float) -> str:
        """La línea de cifra de las corridas ``found`` del caso ``key``."""
        last = found[-1]
        route = last.route
        cause = "ruta hallada" if route.ok else f"sin ruta ({route.cause})"
        return (f"la ruta 3D de 1,5 km, {self.cases[key].name} ({count(last.corridor.nodes)} nodos de pasillo; {MACHINE}): "
                f"{seconds_of([item.total_s for item in found])} (la red 2D, {number(statistics.median(item.network_s for item in found), 2)} s; la "
                f"búsqueda, {number(statistics.median(item.search_s for item in found), 2)} s); {count(route.expanded)} estados expandidos y "
                f"{count(route.seen)} vistos; {cause}; {calls_line([item.calls for item in found])}; presupuesto {number(budget_s, 0)} s")

    def check(self, key: str, runs: int, budget_s: float) -> list[rp.RouteRun]:
        """Corre el caso ``key`` ``runs`` veces y comprueba que la mediana del total no pasa de ``budget_s`` y cada llamada ≤ 0,2 s de CPU."""
        found = []
        for _ in range(runs):
            gc.collect()
            found.append(rp.run_route(self.cases[key]))
        gis_perf.report(f"RNF-017-02: {self.line(key, found, budget_s)}")
        gis_perf.report(f"RNF-017-06: {self.cases[key].name}, {calls_line([item.calls for item in found])}")
        self.assertLessEqual(statistics.median(item.total_s for item in found), budget_s, key)
        self.check_calls([item.calls for item in found], key)
        return found

    def test_a_flat(self) -> None:
        """RNF-017-02: el llano con 60 m de holgura (21.978 nodos y 35,5 M estados posibles: la ruta cabe en un rumbo y se expanden unos cientos) en ≤ 90 s (mediana de
        5; el plan midió 0,12 s)."""
        found = self.check("flat", RUNS, ROUTE_BUDGET_S)
        self.assertTrue(found[-1].route.ok)
        self.assertLess(found[-1].route.expanded, 10_000, "el llano no es llano: no mide lo que el plan")

    def test_b_ravine_with_narrow_margins(self) -> None:
        """RNF-017-02: el barranco de 14 m con 2 y 4 m de holgura (los pasillos de 1.120 y 1.860 nodos del plan: 0,61 s y 2,10 s) en ≤ 90 s (mediana de 5)."""
        for key in ("ravine_2", "ravine_4"):
            found = self.check(key, RUNS, ROUTE_BUDGET_S)
            self.assertTrue(found[-1].route.ok, key)

    def test_c_strip_of_60_m(self) -> None:
        """RNF-017-02: el barranco con **una franja de 60 m de ancho** a lo largo de la ruta (lo demás, intocable: ≈ 5.400 nodos; 5.640 en el plan) en ≤ 30 s (mediana de 3;
        el plan midió 18,5 s con 1,8 M estados expandidos)."""
        found = self.check("strip", HEAVY_RUNS, STRIP_BUDGET_S)
        self.assertTrue(found[-1].route.ok)
        self.assertLess(found[-1].corridor.nodes, 7_000, "la franja no es de 60 m")
        self.assertGreater(found[-1].route.expanded, 1_000_000, "el barranco no se nota: no mide el caso difícil de la franja")

    def test_d_hillside_with_2_m_of_margin(self) -> None:
        """RNF-017-02: la ladera del 38 % a 22,5° con 2 m de holgura (9.239 nodos; el plan midió 36,4 s con 2,6 M estados) en ≤ 90 s. **Una corrida.**"""
        found = self.check("hill_2", 1, ROUTE_BUDGET_S)
        self.assertTrue(found[-1].route.ok)

    def test_e_hillside_with_8_m_of_margin(self) -> None:
        """RNF-017-02: la ladera del 38 % con 8 m de holgura (12.304 nodos en el plan; 41,6 s con 3,3 M estados) en ≤ 90 s. **Una corrida.**"""
        found = self.check("hill_8", 1, ROUTE_BUDGET_S)
        self.assertTrue(found[-1].route.ok)

    def test_f_hillside_with_60_m_of_margin(self) -> None:
        """RNF-017-02: la ladera del 38 % con 60 m de holgura (31.856 nodos y 51,5 M estados posibles; 69 a 71 s con 5,1 M expandidos y 1,21 GB en el plan: el
        caso más caro de los que acaban) en ≤ 90 s. **Una corrida.**"""
        found = self.check("hill_60", 1, ROUTE_BUDGET_S)
        self.assertTrue(found[-1].route.ok)

    def test_g_ravine_with_60_m_of_margin_stops_at_the_budget(self) -> None:
        """RNF-017-02: el barranco con 60 m de holgura (21.978 nodos; la búsqueda entera expandiría 7,5 M estados y tardaría 96 s) **se detiene a su presupuesto de 5 M
        estados expandidos** (≈ 65 s en el plan) con la causa del presupuesto —**no** «no hay ruta»: RF-017-12— en ≤ 90 s. **Una corrida.**"""
        found = self.check("ravine_60", 1, ROUTE_BUDGET_S)
        route = found[-1].route
        self.assertFalse(route.ok)
        self.assertEqual(route.cause, road_model.NoRouteCause.BUDGET)
        self.assertEqual((route.expanded, route.budget), (rd.ROUTE.search_budget, rd.ROUTE.search_budget))

    def test_y_traced_memory_of_a_short_route(self) -> None:
        """RNF-017-07: el pico de memoria adicional (``tracemalloc``, con la de numpy) de la ruta del barranco con 2 m de holgura (88.702 estados expandidos) ≤ 1,5 GB, con lo que cuesta por
        estado visto (sirve para proyectar los pasillos grandes: ``tracemalloc`` los hace 48 veces más lentos, así que el pico de esos se mide con el del proceso, en ``test_z_memory``)."""
        case = self.cases["ravine_2"]
        found: list[Any] = []
        peak = gis_perf.peak_bytes(lambda: found.append(rp.run_route(case)))
        seen = found[0].route.seen
        gis_perf.report(f"RNF-017-07: pico de memoria adicional (tracemalloc, con la de numpy) de la ruta de 1,5 km, {case.name} ({count(seen)} estados vistos; {MACHINE}): "
                        f"{number(peak / MIB, 0)} MiB, {number(peak / seen, 0)} bytes por estado visto con lo fijo de la malla y las dos redes 2D; presupuesto "
                        f"{number(MEMORY_BUDGET_BYTES / MIB, 0)} MiB")
        self.assertLessEqual(peak, MEMORY_BUDGET_BYTES)

    def test_z_memory(self) -> None:
        """RNF-017-02, RNF-017-07: el pico de memoria adicional del proceso (``PeakWorkingSetSize``, con la de numpy: el «pico del proceso» del plan §7.3; **un proceso nuevo por caso**) de los
        pasillos que más gastan —la ladera con 60 m de holgura (1,21 GB en el plan con 7,5 M estados vistos) y el barranco con 60 m, detenido a su presupuesto de 5 M estados— ≤ 1,3 GB (la
        spec lo pide «para cualquier pasillo»)."""
        peaks = {key: rp.route_peak_bytes(key) for key in ("hill_60", "ravine_60")}
        gis_perf.report("RNF-017-02: pico de memoria adicional del proceso (PeakWorkingSetSize, con la de numpy; un proceso nuevo por caso) de la ruta de 1,5 km, " + "; ".join(
            f"{self.cases[key].name} {number(extra / MIB, 0)} MiB con {count(found[1])} estados vistos y {count(found[0])} expandidos ({number(extra / found[1], 0)} bytes por estado visto; "
            f"{'ruta hallada' if found[2] else 'detenida por su presupuesto'}; partida de {number(base / MIB, 0)} MiB)" for key, (extra, base, found) in peaks.items())
            + f" ({MACHINE}); presupuesto {number(ROUTE_MEMORY_BYTES / MIB, 0)} MiB (RNF-017-07: {number(MEMORY_BUDGET_BYTES / MIB, 0)} MiB)")
        for key, (extra, _base, _found) in peaks.items():
            self.assertLessEqual(extra, ROUTE_MEMORY_BYTES, self.cases[key].name)


# --- RNF-017-03: el eje y la rasante ------------------------------------------------------------------------------------


class AxisTest(RoadsCase):
    """RNF-017-03 con el eje de 5.013 m con 163 vértices (161 curvas de R = 20 m) y las estaciones cada 1 m (5.014): formar el eje, muestrear y la rasante
    acotada, con pd = 10 %."""

    PROFILE = rd.PROFILE

    def axis_and_gradient(self) -> tuple[Any, np.ndarray]:
        """El eje con curvas del polígono de 5 km, el terreno sobre él (una onda: sube y baja 6 m cada 700 m sobre una pendiente del 1 %) y su rasante acotada."""
        line = rd.scale_axis_5km()
        axis = road_axis.axis_of(line, self.PROFILE.curve_radius_m, self.PROFILE.min_radius_m, self.PROFILE.station_step_m)
        terrain = 150.0 + 0.01 * axis.stations + 6.0 * np.sin(2.0 * np.pi * axis.stations / 700.0)
        rise = road_gradient.gradient_line(axis.stations, terrain, self.PROFILE.max_gradient_pct / 100.0, float(terrain[0]), float(terrain[-1]))
        road_gradient.mean_gradient(axis.stations, rise)
        return axis, rise

    def test_a_axis_and_gradient_of_5_km(self) -> None:
        """RNF-017-03: formar el eje de 5 km con 163 vértices (161 curvas), muestrearlo cada 1 m y calcular su rasante acotada y su pendiente media ≤ 2 s (mediana de 5; el
        plan midió 1,6 ms)."""
        times = []
        for _ in range(RUNS):
            began = time.perf_counter()
            axis, rise = self.axis_and_gradient()
            times.append(time.perf_counter() - began)
        gis_perf.report(
            f"RNF-017-03: el eje con curvas y la rasante acotada de una pista de {count(round(axis.length_m))} m con {axis.curve_count} curvas y "
            f"{count(len(axis.stations))} estaciones cada 1 m (A4 y A5; {MACHINE}): {seconds_of(times)}; presupuesto {number(AXIS_BUDGET_S, 0)} s")
        self.assertEqual((axis.curve_count, len(rise)), (161, len(axis.stations)))
        self.assertAlmostEqual(axis.length_m, 5_013.0, delta=60.0)
        self.assertLessEqual(statistics.median(times), AXIS_BUDGET_S)


# --- RNF-017-04: grabar -------------------------------------------------------------------------------------------------


class EngraveTest(RoadsCase):
    """RNF-017-04, RNF-017-06 y RNF-017-07 con el eje de 2.035 m con 61 curvas sobre la rejilla de 2,81 M celdas (la sección de 11,5 m, desmonte a 60° y terraplén a
    35°, alcance de 60 m): el **compacto** (ventana de 1,73 M celdas) y el **diagonal** de la fixture (2,42 M)."""

    compact: ClassVar[rp.EngraveCase]
    diagonal: ClassVar[rp.EngraveCase]

    @classmethod
    def setUpClass(cls) -> None:
        cls.compact = rp.engrave_case(rp.compact_axis_2km())
        cls.diagonal = rp.engrave_case(rd.scale_axis_2km())

    @staticmethod
    def engrave(case: rp.EngraveCase) -> tuple[Any, float, rp.Calls]:
        """El grabado por pasos de 0,05 s: el ``Engraved``, lo que tardó (pared, s) y las llamadas."""
        return rp.timed_steps(road_engrave.engrave_steps(case.job, case.section, case.levels, rp.PROJECT, budget_s=0.05))

    def check(self, case: rp.EngraveCase, what: str, runs: int, budget_s: float, *, rnf_box: bool) -> tuple[list[float], Any]:
        """Graba ``case`` ``runs`` veces; da los tiempos y el último resultado. ``rnf_box``: la caja es de ≤ 2 M celdas y el presupuesto es el del RNF."""
        found = []
        for _ in range(runs):
            gc.collect()
            found.append(self.engrave(case))
        times = [item[1] for item in found]
        engraved = found[-1][0]
        gis_perf.report(
            f"RNF-017-04: grabar {what} (eje de {count(round(case.axis.length_m))} m con {case.axis.curve_count} curvas, ventana de {count(case.cells)} celdas de "
            f"{count(dperf.CELLS)}; sección de {count(case.section.cell_count)} celdas; corte {count(round(engraved.cut_m3))} m³ y relleno "
            f"{count(round(engraved.fill_m3))} m³; {MACHINE}): {seconds_of(times)}; {calls_line([item[2] for item in found])}; presupuesto "
            f"{number(budget_s, 1)} s{'' if rnf_box else ' (el de la spec, 15 s, por cada 2 M celdas de la ventana)'}")
        gis_perf.report(f"RNF-017-06: grabar {what}, {calls_line([item[2] for item in found])}")
        self.assertGreater(case.section.cell_count, 20_000, "la sección es casi nada: no mide el borde")
        self.assertGreater(engraved.edge_cut_m3, 0.0)
        self.assertGreater(engraved.edge_fill_m3, 0.0)
        self.assertLessEqual(statistics.median(times), budget_s, what)
        self.check_calls([item[2] for item in found], what)
        return times, engraved

    def test_a_compact_axis_with_the_exact_metric(self) -> None:
        """RNF-017-04, RNF-017-06: grabar los 2 km con 61 curvas del eje compacto (ventana de ≤ 2 M celdas: la de la spec) con la métrica exacta en ≤ 15 s (mediana de 3;
        el plan midió 8,31 s con 1,58 M celdas)."""
        self.assertLessEqual(self.compact.cells, ENGRAVE_BOX_CELLS, "la caja del eje compacto pasa de 2 M celdas")
        self.check(self.compact, "2 km con la métrica exacta (la caja de la spec)", HEAVY_RUNS, ENGRAVE_BUDGET_S, rnf_box=True)

    def test_b_diagonal_axis_with_the_exact_metric(self) -> None:
        """RNF-017-04, RNF-017-06: el eje en diagonal de la fixture (``road_data.scale_axis_2km``, ventana de **2,42 M celdas**: más que la caja de la spec) con la métrica
        exacta en ≤ 15 s **por cada 2 M celdas de la ventana** (≤ 18,1 s; mediana de 3). Si pasa de 15 s se anota con un aviso: la cifra o la ventana por tramos del plan §7.3
        es una decisión de Samuel, no de esta prueba."""
        cells = self.diagonal.cells
        self.assertGreater(cells, ENGRAVE_BOX_CELLS)
        limit = ENGRAVE_BUDGET_S * cells / ENGRAVE_BOX_CELLS
        times, _ = self.check(self.diagonal, "2 km en diagonal con la métrica exacta (2,42 M celdas)", HEAVY_RUNS, limit, rnf_box=False)
        if statistics.median(times) > ENGRAVE_BUDGET_S:
            gis_perf.report(f"Aviso RNF-017-04: con una ventana de {count(cells)} celdas (más de 2 M) la mediana, {number(statistics.median(times), 2)} s, pasa de "
                            f"{number(ENGRAVE_BUDGET_S, 0)} s: la spec lo pide hasta 2 M celdas (≈ {number(ENGRAVE_BUDGET_S * ENGRAVE_BOX_CELLS / cells, 1)} s por 2 M)")

    def test_c_chamfer(self) -> None:
        """RNF-017-04, RNF-017-06: los mismos 2 km (los dos ejes) con el *chamfer* 5×5 del perfil en ≤ 2 s (mediana de 5; el plan midió 0,43 s), con cada llamada ≤ 0,2 s."""
        profile = rd.profile_with(metric="chamfer5")
        for what, line in (("el eje compacto", rp.compact_axis_2km()), ("el eje en diagonal", rd.scale_axis_2km())):
            case = rp.engrave_case(line, profile)
            found = [self.engrave(case) for _ in range(RUNS)]
            times = [item[1] for item in found]
            gis_perf.report(
                f"RNF-017-04: grabar 2 km con el chamfer 5×5 en {what} (ventana de {count(case.cells)} celdas; {MACHINE}): {seconds_of(times)}; "
                f"{calls_line([item[2] for item in found])}; presupuesto {number(CHAMFER_BUDGET_S, 0)} s")
            self.assertEqual(found[-1][0].metric.value, "chamfer5")
            self.assertLessEqual(statistics.median(times), CHAMFER_BUDGET_S, what)
            self.check_calls([item[2] for item in found], what)

    def test_z_memory(self) -> None:
        """RNF-017-07: el pico de memoria adicional (``tracemalloc``, con la de numpy) de grabar los 2 km con la métrica exacta —el eje compacto y el diagonal, con las
        envolventes de la caja entera— ≤ 1,5 GB (el plan lo estimó en ≈ 0,3 GB sin medirlo)."""
        peaks = {what: gis_perf.peak_bytes(lambda case=case: self.engrave(case))
                 for what, case in (("el eje compacto", self.compact), ("el eje en diagonal", self.diagonal))}
        gis_perf.report(f"RNF-017-07: pico de memoria adicional (tracemalloc, con la de numpy) de grabar 2 km con la métrica exacta ({MACHINE}): "
                        + "; ".join(f"{what} {number(peak / MIB, 0)} MiB" for what, peak in peaks.items())
                        + f"; presupuesto {number(MEMORY_BUDGET_BYTES / MIB, 0)} MiB")
        for what, peak in peaks.items():
            self.assertLessEqual(peak, MEMORY_BUDGET_BYTES, what)


# --- RNF-017-05: la accesibilidad ---------------------------------------------------------------------------------------


class AccessTest(RoadsCase):
    """RNF-017-05, RNF-017-06 y RNF-017-07 con la accesibilidad de 2,81 M celdas con 250 tramos de berma de 640 m², 5 plataformas y 20 zonas «requiere acceso», con una
    franja intocable que parte la rejilla (la entrada al oeste): sin y con la superficie final de una cantera de dos superficies."""

    case: ClassVar[rp.AccessCase]

    @classmethod
    def setUpClass(cls) -> None:
        cls.case = rp.access_case()

    @staticmethod
    def access(job: Any) -> tuple[Any, float, rp.Calls]:
        return rp.timed_steps(road_access.access_steps(job, budget_s=0.05))

    def test_a_access(self) -> None:
        """RNF-017-05, RNF-017-06: A10 y A11 (lo alcanzable, las bermas, las plataformas y las zonas, también la distancia exacta de las que no se comunican) ≤ 5 s con
        una superficie y con dos (mediana de 5; el plan midió 0,17 s y 0,34 s), con cada llamada ≤ 0,2 s."""
        for final in (False, True):
            job = self.case.job(final=final)
            found = [self.access(job) for _ in range(RUNS)]
            outcome = found[-1][0]
            times = [item[1] for item in found]
            gis_perf.report(
                f"RNF-017-05: la accesibilidad de {count(dperf.CELLS)} celdas con {len(outcome.berms)} tramos de berma, {len(outcome.platforms)} plataformas y "
                f"{len(outcome.zones)} zonas, {'con la superficie final' if final else 'con una superficie'} ({MACHINE}): {seconds_of(times)}; "
                f"{sum(item.connected for item in outcome.berms)} tramos, {sum(item.connected for item in outcome.platforms)} plataformas y "
                f"{sum(item.connected for item in outcome.zones)} zonas comunicados; {calls_line([item[2] for item in found])}; presupuesto "
                f"{number(ACCESS_BUDGET_S, 0)} s")
            self.assertEqual((len(outcome.berms), len(outcome.platforms), len(outcome.zones)), (250, 5, 20))
            self.assertEqual(sum(item.connected for item in outcome.berms), 110, "la franja ya no parte las bermas como el plan")
            self.assertLessEqual(statistics.median(times), ACCESS_BUDGET_S, f"final={final}")
            self.check_calls([item[2] for item in found], f"la accesibilidad, final={final}")

    def test_z_memory(self) -> None:
        """RNF-017-07: el pico de memoria adicional (``tracemalloc``, con la de numpy) de la accesibilidad con las bermas, las plataformas y las zonas, con las dos
        superficies, ≤ 1,5 GB."""
        job = self.case.job(final=True)
        peak = gis_perf.peak_bytes(lambda: self.access(job))
        gis_perf.report(f"RNF-017-07: pico de memoria adicional (tracemalloc, con la de numpy) de la accesibilidad de {count(dperf.CELLS)} celdas con 250 tramos de "
                        f"berma, 5 plataformas y 20 zonas ({MACHINE}): {number(peak / MIB, 0)} MiB; presupuesto {number(MEMORY_BUDGET_BYTES / MIB, 0)} MiB")
        self.assertLessEqual(peak, MEMORY_BUDGET_BYTES)


# --- Con el proyecto: «Calcular» a «Crear» ------------------------------------------------------------------------------


class NetworkRoadProject:
    """El proyecto de escala en una subcarpeta temporal de la carpeta de pruebas de la red (``Z:``), borrada al terminar, con los datos de usuario en disco local
    (``tests.support.network``: con ``GEOBLENDER_NET_TEST_DIR``, a mano; sin ella, se omite; nunca la de los expedientes de clientes)."""

    WHERE = "con el proyecto en la carpeta de pruebas de la red"

    @classmethod
    def make_project(cls) -> Any:
        stack = ExitStack()
        cls.addClassCleanup(stack.close)  # type: ignore[attr-defined]
        remote = stack.enter_context(network.net_tmp("gb-017-t34-"))
        local = stack.enter_context(project_tmp("gb-017-u-"))
        return stack.enter_context(rp.scale_project(folder=remote, userdata=local / "u"))


class ScaleCase(unittest.TestCase):
    """Un proyecto de escala por clase (disco local), con lo que miden todas: repetir ``cycle`` con un nombre nuevo."""

    BUDGET_S = ROUTE_BUDGET_S
    RUNS = HEAVY_RUNS
    WHERE = "proyecto en disco local"
    data: ClassVar[Any]

    @classmethod
    def make_project(cls) -> Any:
        return cls.enterClassContext(rp.scale_project())

    @classmethod
    def setUpClass(cls) -> None:
        cls.data = cls.make_project()

    def repeat(self, make: Callable[[], rp.Calculated], *, warm: bool = False, once: bool = False) -> list[rp.Calculated]:
        """:data:`RUNS` ejecuciones seguidas de ``make`` (con la basura recogida antes de cada una; una sola con ``once``), después de una que calienta la caché de lectura y no
        cuenta (con ``warm``)."""
        if warm:
            make()
        found = []
        for _ in range(1 if once else self.RUNS):
            gc.collect()
            found.append(make())
        return found

    def road(self, request: Any) -> rp.Calculated:
        return rp.cycle(self.data, steps.road_run, request)

    def check_calls(self, found: list[rp.Calculated], what: str) -> None:
        worst = max(found, key=lambda item: item.calls.longest_cpu_s)
        gis_perf.report(f"RNF-017-06: {what}, llamadas de «Calcular» (presupuesto de {number(0.05, 2)} s): {worst.calls.count} en la peor, la más larga de todas "
                        f"{ms(max(item.calls.longest_s for item in found))} ms de pared y {ms(worst.calls.longest_cpu_s)} ms de CPU (presupuesto {ms(CALL_BUDGET_S)} ms de CPU; {self.WHERE})")
        self.assertLessEqual(worst.calls.longest_cpu_s, CALL_BUDGET_S, f"{what}: una llamada del hilo pasa de 0,2 s de CPU")


class RoadProjectTest(ScaleCase):
    """RNF-017-01, 02, 04, 05 y 06 con el proyecto de escala: «Calcular» y «Crear» (leer la superficie y las capas del proyecto, las máscaras, calcular y escribir en una
    transacción), cada ejecución con un nombre nuevo y descartada al terminar (de cada superficie parte una sola). Lo que tarda cada fase de «Calcular» (``prepare``: leer el
    proyecto; ``road_net``: la red 2D; ``road_route``: la ruta 3D; ``road_section`` y ``road_engrave``: la sección y el grabado) sale de los pasos."""

    NETWORK_BUDGET_S = NETWORK_BUDGET_S
    BUDGET_ENGRAVE_S = ENGRAVE_BUDGET_S
    BUDGET_ACCESS_S = ACCESS_BUDGET_S
    BUDGET_CREATE_S = CREATE_BUDGET_S

    def trace(self, origin: str, destination: str, surface: str, margin_m: float) -> rp.Calculated:
        return self.road(rp.road_request(ep.fresh_name("Pista"), origin, destination, surface, margin_m=margin_m))

    def axis(self, feature: str) -> rp.Calculated:
        return self.road(rp.axis_request(ep.fresh_name("Pista sobre un eje"), feature))

    @staticmethod
    def phase(made: rp.Calculated, *names: str) -> float:
        """Lo que tardaron las fases ``names`` de «Calcular» de ``made`` (s)."""
        return sum(made.phases.get(name, 0.0) for name in names)

    def test_a_trace_over_the_ravine(self) -> None:
        """RNF-017-01, RNF-017-02, RNF-017-06: «trazar» la ruta de 1,5 km sobre el barranco (2 m de holgura: leer el proyecto, la red 2D y la ruta, el eje, la rasante, la sección y el
        grabado), de «Calcular» a «Crear»: leer y la red 2D de las dos corridas ≤ 10 s (≤ 20 s en ``Z:``) y, con la ruta, ≤ 90 s (≤ 180 s en ``Z:``)."""
        found = self.repeat(lambda: self.trace(rp.RAVINE_ORIGIN, rp.RAVINE_DESTINATION, rp.RAVINE, 2.0))
        nets = [self.phase(item, "prepare", "road_net") for item in found]
        routes = [self.phase(item, "prepare", "road_net", "road_route") for item in found]
        gis_perf.report(
            f"RNF-017-01: la red 2D de la malla de 4 m del barranco, con el proyecto (leer la superficie y las capas, las dos corridas; {self.WHERE}; {MACHINE}): {seconds_of(nets)}; "
            f"presupuesto {number(self.NETWORK_BUDGET_S, 0)} s")
        gis_perf.report(
            f"RNF-017-02: «trazar» la ruta de 1,5 km sobre el barranco con 2 m de holgura sobre {count(dperf.CELLS)} celdas de 1 m: leer, la red 2D y la ruta {seconds_of(routes)} "
            f"y, de «Calcular» (con el eje, la rasante, la sección y el grabado) a «Crear» (la superficie y las tablas; {self.WHERE}), "
            f"{seconds_of([item.total_s for item in found])}; «Calcular» {number(statistics.median(item.calculate_s for item in found), 2)} s y «Crear» "
            f"{number(statistics.median(item.create_s for item in found), 2)} s de mediana; presupuesto {number(self.BUDGET_S, 0)} s")
        self.assertGreater(self.phase(found[-1], "road_route"), 0.0, "la pista no hizo la ruta: no mide nada")
        self.assertLessEqual(statistics.median(nets), self.NETWORK_BUDGET_S)
        self.assertLessEqual(statistics.median(routes), self.BUDGET_S)
        self.check_calls(found, "«trazar» sobre el barranco")

    def test_b_trace_over_the_hillside(self) -> None:
        """RNF-017-02, RNF-017-06: «trazar» la ruta de 1,5 km sobre la ladera del 38 % con 8 m de holgura (12.000 nodos de pasillo: el caso caro de §7.3), de «Calcular» a
        «Crear»: leer, la red 2D y la ruta ≤ 90 s (≤ 180 s en ``Z:``). **Una ejecución.**"""
        found = self.repeat(lambda: self.trace(rp.HILL_ORIGIN, rp.HILL_DESTINATION, rp.HILLSIDE, 8.0), once=True)
        route_s = self.phase(found[0], "prepare", "road_net", "road_route")
        gis_perf.report(
            f"RNF-017-02: «trazar» la ruta de 1,5 km sobre la ladera del 38 % con 8 m de holgura sobre {count(dperf.CELLS)} celdas de 1 m ({self.WHERE}; {MACHINE}, una sola "
            f"ejecución): leer, la red 2D y la ruta {number(route_s, 2)} s y, de «Calcular» a «Crear», {number(found[0].total_s, 2)} s («Calcular» "
            f"{number(found[0].calculate_s, 2)} s y «Crear» {number(found[0].create_s, 2)} s); presupuesto {number(self.BUDGET_S, 0)} s")
        self.assertLessEqual(route_s, self.BUDGET_S)
        self.check_calls(found, "«trazar» sobre la ladera")

    def test_c_axis_of_2_km(self) -> None:
        """RNF-017-04, RNF-017-06: grabar un eje de 2 km con 61 curvas «sobre un eje» (los dos: el compacto, de ≤ 2 M celdas de ventana, y el diagonal, de 2,42 M) sobre el terreno
        de escala: la sección y el grabado más «Crear» (la superficie entera de 2,81 M celdas y las tablas) ≤ 15 s para el compacto (≤ 30 s en ``Z:``; el diagonal, ≤ 15 s por cada 2 M
        celdas de ventana: 18,1 s, ≤ 36,3 s en ``Z:``)."""
        for feature, scaled in (("Eje compacto", 1.0), ("Eje de 2 km", 2.42 / 2.0)):
            found = self.repeat(lambda feature=feature: self.axis(feature))
            engraved = [self.phase(item, "road_section", "road_engrave") + item.create_s for item in found]
            limit = self.BUDGET_ENGRAVE_S * scaled
            gis_perf.report(
                f"RNF-017-04: grabar el «{feature}» de 2 km sobre {count(dperf.CELLS)} celdas de 1 m, la sección y el grabado de «Calcular» más «Crear» (la superficie entera y las "
                f"tablas; {self.WHERE}; {MACHINE}): {seconds_of(engraved)}; de «Calcular» a «Crear», {seconds_of([item.total_s for item in found])}; «Crear» "
                f"{number(statistics.median(item.create_s for item in found), 2)} s de mediana; presupuesto {number(limit, 1)} s"
                f"{'' if scaled == 1.0 else ' (el de la spec por cada 2 M celdas de la ventana, con la escritura de «Crear» fija)'}")
            if scaled == 1.0:
                self.assertLessEqual(statistics.median(engraved), limit, feature)
            else:  # la ventana pasa de 2 M celdas: lo que depende de ella (la sección y el grabado) va a su presupuesto por celda y «Crear», que escribe la rejilla entera, aparte
                window = [self.phase(item, "road_section", "road_engrave") for item in found]
                self.assertLessEqual(statistics.median(window), limit, feature)
                self.assertLessEqual(statistics.median(item.create_s for item in found), self.BUDGET_CREATE_S, feature)
                if statistics.median(engraved) > self.BUDGET_ENGRAVE_S:
                    gis_perf.report(f"Aviso RNF-017-04: con una ventana de más de 2 M celdas la mediana, {number(statistics.median(engraved), 2)} s con «Crear», pasa de "
                                    f"{number(self.BUDGET_ENGRAVE_S, 0)} s: la spec lo pide hasta 2 M celdas (la cifra o la ventana por tramos del plan §7.3: decisión de Samuel)")
            self.check_calls(found, f"grabar el «{feature}»")

    def test_d_access(self) -> None:
        """RNF-017-05, RNF-017-06: la accesibilidad de la superficie de escala (2,81 M celdas, con la entrada de la capa del proyecto y los umbrales de la referencia: **sin**
        las bermas, plataformas y zonas, que ``AccessTest`` mide con su CPU) de «Calcular» a «Crear» (las rejillas y las tablas), ≤ 5 s (≤ 10 s en ``Z:``)."""
        found = self.repeat(lambda: rp.cycle(self.data, steps.access_run, rp.access_request(ep.fresh_name("Accesibilidad"))), warm=True)
        gis_perf.report(
            f"RNF-017-05: la accesibilidad de la superficie de escala ({count(dperf.CELLS)} celdas de 1 m; con la capa de entradas del proyecto, sin bermas, plataformas ni zonas), de "
            f"«Calcular» a «Crear» ({self.WHERE}; {MACHINE}): {seconds_of([item.total_s for item in found])}; «Calcular» "
            f"{number(statistics.median(item.calculate_s for item in found), 2)} s y «Crear» {number(statistics.median(item.create_s for item in found), 2)} s de mediana; "
            f"presupuesto {number(self.BUDGET_ACCESS_S, 0)} s")
        self.assertLessEqual(statistics.median(item.total_s for item in found), self.BUDGET_ACCESS_S)
        self.check_calls(found, "la accesibilidad")


# --- RNF-017-10: lo que guarda ------------------------------------------------------------------------------------------


class DiskTest(ScaleCase):
    """RNF-017-10 y RNF-017-07 con el proyecto de escala: lo que deja en disco una pista (su superficie en la rejilla entera comprimida, más lo que crece la base del
    proyecto con sus tablas, operaciones, parámetros y cifras) y una revisión con 20 en cadena; y el pico de memoria de «Calcular» a «Crear»."""

    def once(self, request: Any, **options: Any) -> rp.Calculated:
        """Calcula y crea ``request`` una vez (**sin** descartar: lo que mide es lo que queda), con lo que encadena la orden."""
        self.data.clock.advance(minutes=1)
        made = rp.calculate(self.data, steps.road_run, request, **options)
        self.data.clock.advance(minutes=1)
        return made

    def test_a_one_road(self) -> None:
        """RNF-017-10: una pista de 2 km (el eje en diagonal) ≤ 25 MiB (su superficie entera, comprimida, más sus tablas, su operación y sus cifras)."""
        made = self.once(rp.axis_request("Pista de 2 km", "Eje de 2 km"))
        ep.finish(entity_store.discard_entity_steps(self.data.project, self.data.v1.uid, made.calculation.entity.code, reason="Medición de rendimiento"))
        gis_perf.report(
            f"RNF-017-10: lo que guarda en el proyecto una pista de 2 km (superficie entera de {count(dperf.CELLS)} celdas de 1 m {mib(made.raster_bytes)} MiB y tablas "
            f"{mib(made.db_bytes)} MiB; {MACHINE}): {mib(made.disk_bytes)} MiB; presupuesto {mib(ENTITY_BUDGET_BYTES)} MiB")
        self.assertLessEqual(made.disk_bytes, ENTITY_BUDGET_BYTES, f"una pista: {mib(made.disk_bytes)} MiB frente a {mib(ENTITY_BUDGET_BYTES)} MiB")

    def test_b_twenty_roads(self) -> None:
        """RNF-017-10: una revisión con 20 pistas en cadena (cada una de la superficie de la anterior, con lo que encadena la orden: la capa de entidades y la de ejes) ≤ 0,5 GiB,
        cada una ≤ 25 MiB."""
        start, sizes, codes = dperf.START, [], []
        for index in range(1, CHAIN + 1):
            made = self.once(rp.axis_request(f"Pista {index:02d}", f"Eje {index:02d}", start=start), chain=True)
            codes.append(made.calculation.entity.code)
            start = f"entity:{codes[-1]}"
            sizes.append(made.disk_bytes)
        for code in reversed(codes):  # de cada superficie parte una sola: se descartan (la última primero) para que las pruebas siguientes puedan partir de ella
            self.data.clock.advance(minutes=1)
            ep.finish(entity_store.discard_entity_steps(self.data.project, self.data.v1.uid, code, reason="Medición de rendimiento"))
        total = sum(sizes)
        gis_perf.report(
            f"RNF-017-10: lo que guardan {len(sizes)} pistas en cadena (superficie entera de {count(dperf.CELLS)} celdas de 1 m comprimida más sus tablas; {MACHINE}): la mayor "
            f"{mib(max(sizes))} MiB, la mediana {mib(statistics.median(sizes))} MiB, presupuesto {mib(ENTITY_BUDGET_BYTES)} MiB cada una; la revisión con las {len(sizes)}: "
            f"{gib(total)} GiB ({mib(total)} MiB), presupuesto {number(REVISION_BUDGET_BYTES / 1024**3, 2)} GiB")
        self.assertEqual(len(sizes), CHAIN)
        self.assertLessEqual(total, REVISION_BUDGET_BYTES, f"la revisión con 20: {gib(total)} GiB frente a 0,5 GiB")
        self.assertLessEqual(max(sizes), ENTITY_BUDGET_BYTES, f"la mayor: {mib(max(sizes))} MiB frente a {mib(ENTITY_BUDGET_BYTES)} MiB")

    def test_z_memory(self) -> None:
        """RNF-017-07: el pico de memoria adicional (``tracemalloc``, con la de numpy) de «Calcular» a «Crear» una pista de 2 km (el eje en diagonal) y la accesibilidad, con el proyecto
        de escala ≤ 1,5 GB."""
        cases: dict[str, Callable[[], rp.Calculated]] = {
            "la pista de 2 km": lambda: rp.cycle(self.data, steps.road_run, rp.axis_request(ep.fresh_name("Pista"), "Eje de 2 km")),
            "la accesibilidad": lambda: rp.cycle(self.data, steps.access_run, rp.access_request(ep.fresh_name("Accesibilidad")))}
        peaks = {}
        for what, make in cases.items():
            make()  # sin caché de lectura
            peaks[what] = gis_perf.peak_bytes(make)
        gis_perf.report(f"RNF-017-07: pico de memoria adicional (tracemalloc, con la de numpy) sobre {count(dperf.CELLS)} celdas de 1 m, de «Calcular» a «Crear» ({MACHINE}): "
                        + "; ".join(f"{what} {number(peak / MIB, 0)} MiB" for what, peak in peaks.items()) + f"; presupuesto {number(MEMORY_BUDGET_BYTES / MIB, 0)} MiB")
        for what, peak in peaks.items():
            self.assertLessEqual(peak, MEMORY_BUDGET_BYTES, what)


# --- En la red ------------------------------------------------------------------------------------------------------------
#
# **Ojo**: en el PC de referencia la variable GEOBLENDER_NET_TEST_DIR está definida en el usuario y este módulo, lanzado tal cual, también corre estas clases
# (``docs/trampas.md`` §7); para medir solo en local, sin ella: ``Remove-Item Env:GEOBLENDER_NET_TEST_DIR`` (PowerShell) o ``env -u GEOBLENDER_NET_TEST_DIR …``
# (Git Bash).


@requires(network.NET, network.NET_HINT)
class NetworkRoadProjectTest(NetworkRoadProject, RoadProjectTest):
    """RNF-017-01, 02, 04 y 05 en ``Z:``: la ruta sobre el barranco y la ladera, el eje de 2 km y la accesibilidad con el proyecto en la red (mediana de
    :data:`NETWORK_RUNS`; cada ejecución escribe en la red una superficie de 17 MiB), con los presupuestos de ``Z:``: la ruta, ≤ 180 s; el grabado, ≤ 30 s (el diagonal, ≤ 36 s); la
    accesibilidad, ≤ 10 s. Las esperas de la red de cada llamada (RNF-017-06) las mide ``perf_roads.py`` aparte."""

    NETWORK_BUDGET_S = NETWORK_NETWORK_BUDGET_S
    BUDGET_S = ROUTE_NETWORK_BUDGET_S
    BUDGET_ENGRAVE_S = ENGRAVE_NETWORK_BUDGET_S
    BUDGET_ACCESS_S = ACCESS_NETWORK_BUDGET_S
    BUDGET_CREATE_S = 2.0 * CREATE_BUDGET_S
    RUNS = NETWORK_RUNS


if __name__ == "__main__":
    unittest.main()

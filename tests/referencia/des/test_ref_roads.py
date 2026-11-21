# SPDX-License-Identifier: GPL-3.0-or-later
"""Hito H1 de las pistas y rampas: la cadena entera en el dominio, sin Blender y sin proyecto (spec 017, T14; HU-017-1, HU-017-4; RF-017-02, 04, 06, 09 a 18, 20 a 23; CE-017-01 a 04 y
CE-017-06; E1, E3 y E4; plan 017 §7.1, §7.2 y §7.5): la **ruta** 3D (T06 a T08), el **eje con curvas** (T10), la **rasante** acotada (T11), la **sección** (T12) y el **grabado** con su borde
(T13), **compuestos a mano** (sin ``road_store``, que no existe aún) y contrastados con el cálculo a mano **en las mismas celdas**.

Lo que hace falta para que la accesibilidad, el proyecto, la cadena y las dependencias puedan montarse encima: que las piezas encajen entre sí y den, juntas, lo que da cada una por separado
(un fallo posterior sería indistinguible de uno de las piezas). La composición es la de la orden de pista de la T19 a la T21, escrita aquí con las firmas reales (:func:`compose`):

    ruta (``route_steps``) → eje (``axis_of``, con el origen y el destino exactos) → terreno en las estaciones (``sample_terrain``) → rasante (``gradient_line``)
    → ventana (``engrave_window``) → sección (``section_cells``) → cota por celda (``Section.levels``) → grabado (``engrave``) → las veintitrés cifras de RF-017-23.

**Ningún valor esperado sale de llamar al código bajo prueba**: el eje se mide con las fórmulas cerradas de tangente y arco desde sus vértices (:func:`axis_by_hand`); la rasante, con la fuerza
bruta O(n²) de ``road_data.oracle_gradient_line``; la sección, con ``road_data.oracle_section`` (el tramo más próximo uno a uno) o las fórmulas de ``straight_section_by_hand``; el grabado, con
``road_data.hand_engrave`` (un bucle por celda y la envolvente de todas las semillas por fuerza bruta). Tolerancias de D-22 y de la spec: ≤ 10⁻⁹ m en las longitudes y las cotas y ≤ 10⁻⁹ relativo
en los volúmenes. Todo es sintético y de la cantera de la 014 (400 × 400 m, de 1 m y de 2 m); el escenario E1 es propio (ver :func:`e1_surface`).

- **CE-017-01 · rampa recta y sección** (RF-017-10, 11, 15, 20, 21, 23): sobre el plano del 4 % cuyo sentido de máxima pendiente es un eje de la rejilla, con pd = 8 %, la pista «trazar» de 200 m mide
  200,000 m, su rasante es el terreno (movimiento 0 m), su pendiente media y su máxima son del 4,000 % y su desnivel, de 8,000 m; con la pendiente transversal del 20 %, la calzada da el corte y el
  relleno del cálculo a mano en las mismas celdas; y en un plano sin restricciones y con un rumbo cualquiera el eje no pasa de la distancia recta en más de un 2,8 %. Con un corte que no se admite, con
  un intocable al que llega la calzada y con una altura máxima menor que la pendiente transversal (RF-017-06, 21 y 22), la calzada que no queda en su rasante da su grupo, su causa y la confirmación.
- **CE-017-02 · curvas** (RF-017-13 y 14): el eje de dos tramos perpendiculares con R = 20 m (tangente 20 m, arco 31,416 m, a ≤ 10⁻⁹ m del arco analítico), con tramos de 15 m y Rmín = 12 m el
  radio baja a 15 m con el aviso, con Rmín = 16 m se rechaza nombrando el vértice, los tramos y el radio que cabría, y la línea dibujada («sobre un eje») no cambia (hash antes y después).
- **CE-017-03 · rasante** (RF-017-15 a 18): el escalón da una rampa del 5 % entre −60 y +60 m y 180 m·m (con un error O(w) por el muestreo y la bilineal), el oráculo en las mismas estaciones, el
  rechazo «necesaria 200 m, el eje mide 100 m», el aviso de la media con pm = 2 % y el «eje 3D» irregular con sus avisos y **la línea sin cambiar**.
- **CE-017-04 · regresión de B2 y sin ruta** (RF-017-11, 12): la ladera del 38 % da una ruta que existe, de la cota del terreno y que no pasa de pd, y la franja de un nodo no tiene ruta y no crea nada.
- **CE-017-06 · la sección** (RF-017-20): la huella de 200 m ± 1 celda a lo largo del eje, la calzada y el caballón a ≤ 10⁻⁹ m del cálculo a mano, el caballón a la derecha con cotas iguales y el arcén
  en el lado de mayor cota.
- **E1 · la pista a la plataforma del fondo** (RF-017-02, 09 a 23): el origen en el borde, 15 m sobre el fondo de 175 m, a unos 200 m de la plataforma por un corredor del 8 % con una esquina: la
  ruta, el eje con curvas, la rasante, la sección y el grabado compuestos y contrastados, con las veintitrés cifras (en pequeño aquí, con la malla de la ruta de 8 m; con la de 4 m, la fuerza bruta de
  las pistas de 200 m y la misma pista bit a bit, en ``tests/unit/design/milestone_roads_h1.py``, que ejecuta el paso «hito» de ``check.py --completo``).
- **La rampa a una cota** (E4, sin la accesibilidad; RF-017-02, 10): el destino por cota sobre la cantera con bancos: la ruta termina en la zona, el eje acaba en el nodo de llegada y la rasante, en
  la cota pedida.
- **La misma entrada, la misma pista bit a bit** (RF-015-02, RF-017-10) y **las entradas no se modifican** (principio 7).
"""

from __future__ import annotations

import dataclasses
import functools
import hashlib
import math
import unittest
from typing import Any

import numpy as np

from tests.support import quarry_fixtures as qfx
from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.unit.design.test_road_no_route import strip_case

gis = import_geoblender("gis")
messages = import_geoblender("design.messages")
params = import_geoblender("design.params")
provenance = import_geoblender("design.provenance")
road_axis = import_geoblender("design.road_axis")
road_engrave = import_geoblender("design.road_engrave")
road_gradient = import_geoblender("design.road_gradient")
road_model = import_geoblender("design.road_model")
road_route = import_geoblender("design.road_route")
road_section = import_geoblender("design.road_section")

TOL = 1e-9
"""Metros y relativo: lo que la spec pide frente al cálculo a mano en las mismas celdas (RF-017-13, 15, 20, 21 y 23)."""
PROJECT = {params.TOLERANCE_FACE: 1.0, params.VERIFY_MIN_THICKNESS: 0.05, params.EDGE_MAX_STEP: 1.0, params.EDGE_MIN_SHARE: 99.0}
"""Los parámetros del proyecto que lee el borde (valores de la prueba, no de un proyecto)."""
ENTITY = "Pista de prueba"
SHORT = rd.profile_with(reach_m=12.5)
"""El perfil de referencia con un alcance de 12,5 m: las cuentas por fuerza bruta del borde cuestan lo que la ventana (``hand_engrave`` es O(semillas × celdas))."""
PD8 = rd.profile_with(max_gradient_pct=8.0, reach_m=12.5)
"""El de CE-017-01: pd = 8 %."""


# --- La composición a mano (sin road_store) -------------------------------------------------------------------------------


def last_result(steps: Any) -> Any:
    """El resultado del último paso."""
    found = None
    for step in steps:
        if step.result is not None:
            found = step.result
    return found


def digest(*arrays: Any) -> str:
    """El hash de los bytes de unos arrays (para «antes y después»)."""
    found = hashlib.sha256()
    for array in arrays:
        found.update(np.ascontiguousarray(array).tobytes())
    return found.hexdigest()


@dataclasses.dataclass(frozen=True, slots=True, eq=False)
class Road:
    """Una pista calculada de punta a punta: el trabajo, la ``route`` (``None`` fuera de «trazar») y la ``arrival`` (el destino por cota), el eje, la superficie de partida **en sus estaciones**
    (``terrain``), la rasante ``z`` por estación, la ventana, la sección, la cota de cada celda y lo grabado."""

    job: Any
    route: Any
    arrival: Any
    axis: Any
    terrain: np.ndarray
    z: np.ndarray
    window: tuple[slice, slice]
    section: Any
    levels: np.ndarray
    found: Any

    @property
    def carriageway_m(self) -> float:
        """La calzada ``f·A`` (a mano, no ``derived``)."""
        return self.job.profile.lane_factor * self.job.profile.vehicle_width_m

    def slopes(self) -> np.ndarray:
        """La pendiente (tanto por uno, en valor absoluto) de cada tramo entre estaciones."""
        return np.abs(np.diff(self.z)) / np.diff(self.axis.stations)

    def figures(self) -> dict[str, float | None]:
        """Las veintitrés cifras de RF-017-23 (``provenance.ROAD_FIGURES``): las del eje y la rasante, aquí; las del grabado, ``Engraved.figure_values()``. El desnivel es ``z_fin − z_inicio``."""
        profile, axis, z = self.job.profile, self.axis, self.z
        slopes = self.slopes()
        top = int(np.argmax(slopes))
        mean = float(np.abs(np.diff(z)).sum() / (axis.stations[-1] - axis.stations[0]))
        return {
            "des.road_length_m": axis.length_m, "des.road_z_start_m": float(z[0]), "des.road_z_end_m": float(z[-1]), "des.road_drop_m": float(z[-1] - z[0]),
            "des.road_gradient_mean_pct": mean * 100.0, "des.road_gradient_max_pct": float(slopes[top]) * 100.0, "des.road_gradient_max_station_m": float(axis.stations[top]),
            "des.road_radius_min_m": axis.min_radius_m, "des.road_curves": int(axis.curve_count), "des.road_width_m": self.carriageway_m,
            "des.road_section_m": self.carriageway_m + profile.shoulder_m + profile.berm_m, **({} if self.found is None else self.found.figure_values())}


def line_z(axis: Any, line: np.ndarray) -> np.ndarray:
    """La Z de la línea 3D en las estaciones del eje: la de su vértice según la abscisa proporcional a lo largo de la poligonal (exacta con una línea recta, donde el eje y la línea miden lo mismo; con
    esquinas, una aproximación: el contrato con R-35 lo fija la T23)."""
    chord = np.concatenate(([0.0], np.cumsum(np.hypot(*np.diff(line[:, :2], axis=0).T))))
    return np.interp(axis.stations / axis.length_m * chord[-1], chord, line[:, 2])


def compose(job: Any, project: Any = PROJECT, *, engrave: bool = True) -> Road:
    """La pista de ``job`` de punta a punta, como la compondrán T19 a T21 con las firmas reales: la ruta 3D (solo «trazar»: si no hay, el rechazo del diagnóstico, **sin crear nada**), el eje con
    curvas (con el origen y el destino exactos; la línea de «sobre un eje» y de «eje 3D» no se modifica), la superficie de partida en las estaciones, la rasante (en «eje 3D» es la Z de la
    línea), la ventana, la sección, la cota de cada celda y el grabado. ``RadiusBelowMinimum`` (el radio que cabría es menor que Rmín) y ``DropTooSteep`` (el desnivel pasa de pd por la longitud) se
    dejan pasar: son el rechazo de RF-017-14 y de RF-017-16."""
    profile, grid, geometry = job.profile, job.grid, job.geometry
    route = arrival = None
    if job.mode is road_model.RoadMode.TRACE:
        mesh, corridor = rd.route_corridor(job)
        route = last_result(road_route.route_steps(job, corridor))
        if not route.ok:
            raise road_route.no_route(job, corridor.net_origin, corridor.net_dest, route).error(job)
        destination = geometry.destination
        if isinstance(destination, road_model.LevelDestination):
            arrival = road_route.arrival_of(job, route)
            destination = (arrival.x, arrival.y)
        axis = road_axis.axis_of(route.centers, profile.curve_radius_m, profile.min_radius_m, profile.station_step_m, simplify_m=job.route.simplify_m,
                                 origin=geometry.origin, destination=destination)
    elif job.mode is road_model.RoadMode.ON_AXIS:
        axis = road_axis.axis_of(geometry.line, profile.curve_radius_m, profile.min_radius_m, profile.station_step_m)
    else:
        axis = road_axis.axis_of(geometry.line, profile.curve_radius_m, profile.min_radius_m, profile.station_step_m, reject_below_minimum=False)
    on_axis = road_section.sample_terrain(job.start, grid, axis.points[:, 0], axis.points[:, 1])
    if job.mode is road_model.RoadMode.AXIS_3D:
        z = line_z(axis, geometry.line)
    else:
        z_start = float(on_axis[0]) if job.start_level_m is None else job.start_level_m
        if job.end_level_m is not None:
            z_end = job.end_level_m
        elif isinstance(geometry.destination, road_model.LevelDestination):
            z_end = geometry.destination.level_m
        else:
            z_end = float(on_axis[-1])
        z = road_gradient.gradient_line(axis.stations, on_axis, profile.max_gradient_pct / 100.0, z_start, z_end)
    if not engrave:
        return Road(job, route, arrival, axis, on_axis, z, (slice(0, 0), slice(0, 0)), None, np.empty((0, 0)), None)
    window = road_engrave.engrave_window(axis, profile, grid)
    section = road_section.section_cells(axis, profile.lane_factor * profile.vehicle_width_m, profile.shoulder_m, profile.berm_m, job.start, grid, window)
    levels = section.levels(axis.stations, z)
    return Road(job, route, arrival, axis, on_axis, z, window, section, levels, road_engrave.engrave(job, section, levels, project))


def axis_3d_job(grid: Any, surface: np.ndarray, line: np.ndarray, *, profile: rd.ProfileData = SHORT) -> Any:
    """Un ``RoadJob`` en el modo «eje 3D» (la línea ``(k, 3)`` absoluta con su Z), con el corte y el relleno admitidos en todas partes."""
    shape = grid.shape
    request = road_model.RoadRequest(ENTITY, road_model.LayerFields("gis_brk_pistas_eje3d", "nombre"), "axis_3d", "pista_principal", "gis_dtm_prueba")
    return road_model.RoadJob(request=request, code="RDW-001", profile=rd.road_profile(profile), grid=grid, start=np.asarray(surface, dtype=np.float64),
                              cut_allowed=np.ones(shape, dtype=bool), fill_allowed=np.ones(shape, dtype=bool), untouchable=np.zeros(shape, dtype=bool),
                              geometry=road_model.RoadGeometry(line=np.asarray(line, dtype=np.float64)))


# --- El cálculo a mano que contrasta cada pieza ----------------------------------------------------------------------------


def axis_by_hand(axis: Any, radius_m: float) -> tuple[float, list[float]]:
    """La longitud del eje y el radio de cada curva (en el orden del eje) con las fórmulas cerradas y la regla de RF-017-14 (una pasada), desde **sus vértices** (la poligonal simplificada): la
    tangente de diseño de cada vértice con cambio de dirección es ``R·tan(|Δ|/2)`` (``Δ`` el cambio de azimut normalizado a (−π, π]); si la suma de las de los dos extremos de un tramo pasa de su
    longitud, el radio de cada una baja a ``R·mín(tramo/necesario)`` de sus dos tramos; la longitud es ``Σ tramos − Σ 2·T + Σ r·|Δ|``."""
    vertices = axis.vertices
    legs = [math.hypot(*(vertices[k + 1] - vertices[k])) for k in range(len(vertices) - 1)]
    azimuths = [math.atan2(vertices[k + 1][0] - vertices[k][0], vertices[k + 1][1] - vertices[k][1]) for k in range(len(vertices) - 1)]
    deflections = {k + 1: (azimuths[k + 1] - azimuths[k] + math.pi) % (2.0 * math.pi) - math.pi for k in range(len(azimuths) - 1)}
    deflections = {vertex: delta for vertex, delta in deflections.items() if abs(delta) > 1e-9}
    design = {vertex: radius_m * math.tan(abs(delta) / 2.0) for vertex, delta in deflections.items()}
    factor = dict.fromkeys(design, 1.0)
    for leg, length in enumerate(legs):
        needed = design.get(leg, 0.0) + design.get(leg + 1, 0.0)
        if needed > length * (1.0 + 1e-12):
            for vertex in (leg, leg + 1):
                if vertex in factor:
                    factor[vertex] = min(factor[vertex], length / needed)
    radii = {vertex: radius_m * factor[vertex] for vertex in design}
    tangents = {vertex: radii[vertex] * math.tan(abs(deflections[vertex]) / 2.0) for vertex in design}
    total = math.fsum(legs) - 2.0 * math.fsum(tangents.values()) + math.fsum(radii[vertex] * abs(deflections[vertex]) for vertex in design)
    return total, [radii[vertex] for vertex in sorted(radii)]


def bilinear(terrain: np.ndarray, grid: Any) -> Any:
    """La interpolación bilineal de ``terrain`` en coordenadas **locales** (la que usa el oráculo de la sección para el lado del arcén), escrita aparte de ``road_section.sample_terrain``; con las cuatro
    cotas iguales da **exactamente** esa cota (``a + t·(b − a)``: un empate es un empate)."""

    def z_of(x: Any, y: Any) -> np.ndarray:
        col = np.asarray(x, dtype=np.float64) / grid.dx - 0.5
        row = (grid.nrows * grid.dy - np.asarray(y, dtype=np.float64)) / grid.dy - 0.5
        c0 = np.clip(np.floor(col).astype(int), 0, grid.ncols - 2)
        r0 = np.clip(np.floor(row).astype(int), 0, grid.nrows - 2)
        tx, ty = col - c0, row - r0
        top = terrain[r0, c0] + tx * (terrain[r0, c0 + 1] - terrain[r0, c0])
        bottom = terrain[r0 + 1, c0] + tx * (terrain[r0 + 1, c0 + 1] - terrain[r0 + 1, c0])
        return top + ty * (bottom - top)

    return z_of


def section_by_hand(road: Road) -> Any:
    """La sección de la pista por fuerza bruta (``road_data.oracle_section``: el tramo más próximo del eje denso uno a uno) en las celdas de su ventana."""
    axis, job = road.axis, road.job
    dense = rd.stations_by_hand(axis.length_m, 1.0)
    path, _azimuth = axis.sample(dense)
    profile = job.profile
    return rd.oracle_section(job.grid, road.window, path, dense, bilinear(job.start, job.grid), road.carriageway_m, profile.shoulder_m, profile.berm_m)


def check_axis(test: unittest.TestCase, road: Road) -> None:
    """RF-017-13 y 14: la longitud, las curvas y sus radios (los de R, o los que caben) son los de las fórmulas cerradas desde los vértices del eje, ≤ 10⁻⁹ m; hay un aviso por curva cuyo radio baja de
    R; el origen y el destino, exactos."""
    axis, job = road.axis, road.job
    length, radii = axis_by_hand(axis, job.profile.curve_radius_m)
    test.assertAlmostEqual(axis.length_m, length, delta=TOL)
    test.assertEqual(axis.curve_count, len(radii))
    np.testing.assert_allclose([curve.radius_m for curve in axis.curves], radii, rtol=0.0, atol=TOL)
    test.assertTrue(all(radius >= job.profile.min_radius_m - TOL for radius in radii))
    if radii:
        test.assertAlmostEqual(axis.min_radius_m, min(radii), delta=TOL)
    else:
        test.assertIsNone(axis.min_radius_m)
    test.assertEqual(len(axis.notices(ENTITY)), sum(1 for radius in radii if radius < job.profile.curve_radius_m - TOL))
    geometry = job.geometry
    if job.mode is road_model.RoadMode.TRACE:
        destination = (road.arrival.x, road.arrival.y) if road.arrival is not None else geometry.destination
        test.assertEqual((tuple(axis.points[0]), tuple(axis.points[-1])), (geometry.origin, destination))
    else:
        test.assertEqual((tuple(axis.points[0]), tuple(axis.points[-1])), (tuple(geometry.line[0, :2]), tuple(geometry.line[-1, :2])))
    test.assertAlmostEqual(float(axis.stations[-1]), axis.length_m, delta=TOL)


def requested_levels(road: Road) -> tuple[float, float]:
    """Las cotas de inicio y de fin de la pista (D-13), a mano: las pedidas (``start_level_m``, ``end_level_m`` o la cota de un destino por cota) o, si no, las de la superficie de partida en los extremos del eje."""
    job = road.job
    start = float(road.terrain[0]) if job.start_level_m is None else job.start_level_m
    if job.end_level_m is not None:
        return start, job.end_level_m
    destination = job.geometry.destination
    return start, destination.level_m if isinstance(destination, road_model.LevelDestination) else float(road.terrain[-1])


def check_gradient(test: unittest.TestCase, road: Road) -> None:
    """RF-017-15: la superficie de partida en las estaciones es la bilineal de la rejilla (escrita aparte) y la rasante, la del oráculo O(n²) (la mayor minorante y la menor mayorante pd-Lipschitz,
    su media, la banda de los extremos) a ≤ 10⁻⁹ m, con los extremos en las cotas pedidas, ninguna pendiente por encima de pd (a 10⁻⁹) y la media Σ|Δcota|/S de las cotas."""
    pd = road.job.profile.max_gradient_pct / 100.0
    s = road.axis.stations
    z_start, z_end = requested_levels(road)
    local = road.axis.points - np.asarray(rd.origin_of(road.job.grid))
    np.testing.assert_allclose(road.terrain, bilinear(road.job.start, road.job.grid)(local[:, 0], local[:, 1]), rtol=0.0, atol=TOL)
    np.testing.assert_allclose(road.z, rd.oracle_gradient_line(s, road.terrain, pd, z_start, z_end), rtol=0.0, atol=TOL)
    test.assertEqual((float(road.z[0]), float(road.z[-1])), (z_start, z_end))
    test.assertLessEqual(float(road.slopes().max()), pd + TOL)
    mean = math.fsum(np.abs(np.diff(road.z)).tolist()) / (float(s[-1]) - float(s[0]))
    test.assertAlmostEqual(road_gradient.mean_gradient(s, road.z), mean, delta=TOL)


def check_section(test: unittest.TestCase, road: Road) -> Any:
    """RF-017-20: la sección es la de la fuerza bruta en las mismas celdas (clase, lado, abscisa de arco y distancia lateral con signo, ≤ 10⁻⁹ m); devuelve el cálculo a mano."""
    hand = section_by_hand(road)
    section = road.section
    np.testing.assert_array_equal(section.kind, hand.kind)
    np.testing.assert_array_equal(section.side, hand.side)
    np.testing.assert_allclose(section.sigma, hand.sigma, rtol=0.0, atol=TOL, equal_nan=True)
    np.testing.assert_allclose(section.lateral, hand.lateral, rtol=0.0, atol=TOL, equal_nan=True)
    return hand


def check_engrave(test: unittest.TestCase, road: Road, hand: Any) -> None:
    """RF-017-21 y 23: el grabado es el del cálculo a mano en las mismas celdas —un bucle por celda de la sección y la fuerza bruta del borde—: la superficie y la de solo la sección (≤ 10⁻⁹ m),
    las celdas en la rasante, lo que mueve el borde y lo que no, y el corte, el relleno, las alturas máximas y la pared (≤ 10⁻⁹ relativo)."""
    job, found, profile = road.job, road.found, road.job.profile
    window = road.window
    levels = np.where(hand.cells, np.interp(np.nan_to_num(hand.sigma), road.axis.stations, road.z), np.nan)
    free = ~job.untouchable
    by_hand = rd.hand_engrave(job.grid, window, job.start, levels, hand.cells, hand.kind, (job.cut_allowed & free)[window], (job.fill_allowed & free)[window],
                              cut_deg=profile.cut_angle_deg, fill_deg=profile.fill_angle_deg, reach_m=profile.reach_m, mesh_factor=profile.mesh_factor,
                              max_height_m=None if job.route is None else job.route.max_cut_fill_m)
    np.testing.assert_allclose(found.applied, by_hand.applied, rtol=0.0, atol=TOL)
    np.testing.assert_allclose(found.surface, by_hand.surface, rtol=0.0, atol=TOL)
    np.testing.assert_array_equal(found.at_level, by_hand.at_level)
    np.testing.assert_array_equal(found.changed, by_hand.changed)
    np.testing.assert_array_equal(found.held, by_hand.held)
    for name, expected in (("section_cut_m3", by_hand.section_cut_m3), ("section_fill_m3", by_hand.section_fill_m3), ("edge_cut_m3", by_hand.edge_cut_m3),
                           ("edge_fill_m3", by_hand.edge_fill_m3), ("cut_height_max_m", by_hand.cut_height_max_m), ("fill_height_max_m", by_hand.fill_height_max_m),
                           ("wall_max_m", by_hand.wall_max_m)):
        np.testing.assert_allclose(getattr(found, name), expected, rtol=TOL, atol=TOL, err_msg=name)
    for cause, cells in by_hand.off.items():
        test.assertEqual(sum(group.cells for group in found.off_level if group.cause.value == cause), int(cells.sum()), cause)


def check_invariants(test: unittest.TestCase, road: Road) -> None:
    """RF-017-21 y 23, CE-017-09: la superficie de partida es **igual fuera de lo que mueve** (bit a bit), el corte y el relleno del grabado son los de restar las dos superficies celda a celda
    por el área de la celda (lo que dará la cubicación de la 011), y las veintitrés cifras caben en ``provenance.road_figures`` sin cambiar un valor."""
    job, found = road.job, road.found
    start = job.start[road.window]
    moved = found.footprint | found.changed
    np.testing.assert_array_equal(found.surface[~moved], start[~moved])
    drop = start - found.surface
    np.testing.assert_allclose(found.cut_m3, np.maximum(drop, 0.0).sum() * job.grid.cell_area, rtol=TOL, atol=TOL)
    np.testing.assert_allclose(found.fill_m3, np.maximum(-drop, 0.0).sum() * job.grid.cell_area, rtol=TOL, atol=TOL)
    values = road.figures()
    registered = provenance.road_figures(job.request.name, job.code, values)
    test.assertEqual(len(values), len(provenance.ROAD_FIGURES))
    test.assertEqual({item.key: item.value for item in registered}, {key: (None if value is None else float(value)) for key, value in values.items() if value is not None})


def verify(test: unittest.TestCase, road: Road, *, brute: bool = True) -> Any:
    """Todo lo anterior sobre una pista calculada: el eje, la rasante (salvo en «eje 3D», donde es la Z de la línea), la sección, el grabado y los invariantes."""
    check_axis(test, road)
    if road.job.mode is not road_model.RoadMode.AXIS_3D:
        check_gradient(test, road)
    hand = check_section(test, road)
    if brute:
        check_engrave(test, road, hand)
    check_invariants(test, road)
    return hand


def fingerprint(road: Road) -> tuple[Any, ...]:
    """Todo lo que identifica una pista, comparable bit a bit: la ruta, el eje, la rasante, la sección y lo grabado."""
    found = road.found
    route = () if road.route is None else (road.route.nodes, road.route.headings, road.route.levels_m.tobytes(), road.route.cost_units, road.route.expanded)
    return (route, road.axis.vertices.tobytes(), road.axis.points.tobytes(), road.axis.length_m, road.z.tobytes(), road.section.kind.tobytes(), road.section.sigma.tobytes(),
            road.levels.tobytes(), found.surface.tobytes(), found.applied.tobytes(), found.changed.tobytes(), found.cut_m3, found.fill_m3, found.edge_cut_m3,
            found.edge_fill_m3, tuple(sorted(road.figures().items())))


# --- CE-017-01: la rampa recta y su sección --------------------------------------------------------------------------------


@functools.lru_cache(maxsize=None)
def ramp(cross_pct: float, shoulder_m: float = 0.0) -> Road:
    """La pista «trazar» de 200 m de CE-017-01 (de (100, 200) a (300, 200) locales; pd = 8 %) sobre el plano del 4 % con ``cross_pct`` % de pendiente transversal, con la sección de 11,5 m (arcén
    ``shoulder_m``): una vez por caso (de solo lectura)."""
    grid = rd.GRID
    origin, destination = (tuple(float(v) for v in rd.absolute([point], grid)[0]) for point in (rd.RAMP_ORIGIN, rd.RAMP_DESTINATION))
    job = rd.route_job(grid, rd.ramp_terrain(grid, cross_pct=cross_pct), origin, destination, route=rd.ROUTE, profile=dataclasses.replace(PD8, shoulder_m=shoulder_m))
    return compose(job)


@functools.lru_cache(maxsize=None)
def restricted_ramp(kind: str) -> Road:
    """La rampa de 200 m con el 20 % transversal y una restricción (RF-017-06, RF-017-22): ``"mask"``, un corte que no se admite en una caja de la calzada del norte (de x = 180 a 220 m, de y = 200 a
    205,25 m); ``"untouchable"``, un intocable al norte del eje (de y = 203 a 208 m: la ruta, al sur, no lo pisa, pero la calzada llega a él); o ``"height"``, una altura máxima de desmonte y terraplén de
    0,5 m (menor que lo que pide la pendiente transversal en los bordes de la calzada: 0,2 · d)."""
    grid = rd.GRID
    origin, destination = (tuple(float(v) for v in rd.absolute([point], grid)[0]) for point in (rd.RAMP_ORIGIN, rd.RAMP_DESTINATION))
    route = rd.route_with(max_cut_fill_m=0.5) if kind == "height" else rd.ROUTE
    untouchable = rd.in_box(UNTOUCHABLE_BOX, grid) if kind == "untouchable" else None
    job = rd.route_job(grid, rd.ramp_terrain(grid, cross_pct=rd.RAMP_CROSS_PCT), origin, destination, route=route, profile=PD8, untouchable=untouchable)
    if kind == "mask":
        job = dataclasses.replace(job, cut_allowed=~rd.in_box(MASK_BOX, grid))
    return compose(job)


UNTOUCHABLE_BOX = (180.0, 203.0, 220.0, 208.0)
"""El intocable (local): de x = 180 a 220 m y de y = 203 a 208 m, al norte del eje (y = 200 m): toca las dos filas de la calzada a 3,5 y 4,5 m del eje (80 celdas)."""
MASK_BOX = (180.0, 200.0, 220.0, 205.25)
"""La caja donde no se admite el corte (local): 40 columnas por las 5 filas de la calzada del norte (y de 200,5 a 204,5 m), 200 celdas."""


def plane(cross_pct: float) -> Any:
    """El plano de la rampa del 4 % con ``cross_pct`` % transversal, cerrado, en locales."""
    return lambda x, y: rd.RAMP_Z0_M + rd.RAMP_SLOPE_PCT / 100.0 * x + cross_pct / 100.0 * (y - rd.RAMP_AXIS_Y_M)


class RampTest(unittest.TestCase):
    """CE-017-01: «sobre un plano de pendiente 4 % cuyo sentido de máxima pendiente es el de un rumbo de la ruta, sin restricciones y con pd = 8 %, una pista «trazar» de 200 m entre dos puntos mide
    200,000 m, su rasante es el terreno (movimiento 0 m), su pendiente media y su máxima son del 4,000 % a ≤ 10⁻⁹ y su desnivel, de 8,000 m; con una pendiente transversal del 20 %, la sección da el
    corte y el relleno de su calzada iguales al cálculo a mano en las mismas celdas a ≤ 10⁻⁹ relativo»."""

    def test_the_200_m_ramp_goes_through_the_whole_chain_and_its_gradient_is_the_terrain(self) -> None:
        """RF-017-09 a 11, 13, 15, 23, CE-017-01, HU-017-1: la ruta (cincuenta pasos al este) y el eje (recto, de 200,000 m, sin curvas) salen de la cadena; el terreno en el eje es el plano, la
        rasante es el terreno (**movimiento 0 m**), la pendiente media y la máxima son del **4,000 %** (≤ 10⁻⁹), el desnivel es de **8,000 m** (de 104 a 112 m) y no hay nada que mover: la superficie
        no cambia (≤ 10⁻⁹ m), el corte, el relleno y el borde son 0."""
        road = ramp(0.0)
        verify(self, road, brute=False)
        self.assertTrue(road.route.ok)
        self.assertEqual((len(road.route.nodes), road.route.turns), (51, 0))
        axis = road.axis
        self.assertAlmostEqual(axis.length_m, rd.RAMP_LENGTH_M, delta=TOL)
        self.assertEqual((axis.curve_count, axis.min_radius_m), (0, None))
        local = axis.points - np.asarray(rd.BASE)
        np.testing.assert_allclose(road.terrain, rd.RAMP_Z0_M + 0.04 * local[:, 0], rtol=0.0, atol=TOL)
        np.testing.assert_allclose(road.z, road.terrain, rtol=0.0, atol=TOL)  # el movimiento de la rasante: 0 m
        figures = road.figures()
        self.assertAlmostEqual(figures["des.road_gradient_mean_pct"], rd.RAMP_SLOPE_PCT, delta=TOL)
        self.assertAlmostEqual(figures["des.road_gradient_max_pct"], rd.RAMP_SLOPE_PCT, delta=TOL)
        self.assertAlmostEqual(figures["des.road_drop_m"], rd.RAMP_DROP_M, delta=TOL)
        self.assertEqual((figures["des.road_z_start_m"], figures["des.road_length_m"]), (road.z[0], axis.length_m))
        self.assertEqual((figures["des.road_width_m"], figures["des.road_section_m"]), (10.5, 11.5))
        found = road.found
        self.assertLessEqual(float(np.abs(found.surface - rd.ramp_terrain(rd.GRID)[road.window]).max()), TOL)
        self.assertLessEqual(found.cut_m3 + found.fill_m3, TOL)
        self.assertEqual((found.off_level, found.needs_confirmation), ((), False))

    def test_the_section_with_a_20_percent_cross_slope_gives_the_carriageway_cut_and_fill_by_hand(self) -> None:
        """RF-017-20, 21, 23, CE-017-01, CE-017-06: sobre el plano del 4 % con el 20 % transversal, la calzada de 10,5 m de la rampa de 200 m da, **desde la cadena entera**, 500 m³ de corte (al norte,
        el lado alto: sin arcén) y los mismos de relleno al sur (más 220 m³ de la fila del caballón: 720 m³ de relleno de la sección) y las celdas del cálculo a mano (``ramp_calzada_by_hand`` y
        ``straight_section_by_hand``) a ≤ 10⁻⁹ relativo; la sección y el grabado son los de la fuerza bruta."""
        road = ramp(rd.RAMP_CROSS_PCT)
        verify(self, road, brute=False)
        by_hand = rd.ramp_calzada_by_hand(1.0)
        hand = rd.straight_section_by_hand(rd.GRID, plane(rd.RAMP_CROSS_PCT), road.carriageway_m, 0.0, 1.0)
        window = road.window
        np.testing.assert_array_equal(road.section.kind, hand.kind[window])
        np.testing.assert_allclose(road.section.lateral, hand.lateral[window], rtol=0.0, atol=TOL, equal_nan=True)
        found = road.found
        np.testing.assert_allclose(found.section_cut_m3, by_hand.cut_m3, rtol=TOL)
        np.testing.assert_allclose(found.section_fill_m3, by_hand.fill_m3 + 200 * 0.2 * 5.5, rtol=TOL)
        self.assertAlmostEqual(found.section_cut_m3, 500.0, delta=TOL)
        self.assertAlmostEqual(found.section_fill_m3, 720.0, delta=TOL)
        self.assertEqual((found.off_level, found.needs_confirmation), ((), False))
        self.assertGreater(found.edge_cut_m3 + found.edge_fill_m3, 0.0)

    def test_a_cut_that_the_masks_do_not_allow_leaves_a_group_of_the_carriageway_and_asks_for_confirmation(self) -> None:
        """RF-017-06, RF-017-21, RF-017-22, CE-017-01: con un corte que no se admite en una caja de 40 × 5 filas de la calzada del norte, la calzada **no queda en su rasante** en esas 200 celdas: un grupo
        (4-conexo) de la causa de la máscara, de 200 m², con la diferencia máxima de 0,2 · 4,5 = **0,9 m** y su lugar (el centro de la caja), el corte de la sección baja los 100 m³ que no se cortan (400 m³: 500 −
        40 columnas · Σ 0,2·(k + ½) = 2,5 m) y se pide la confirmación; el aviso nombra el área, la diferencia y el lugar, y la restricción que lo impide."""
        road = restricted_ramp("mask")
        found = road.found
        self.assertTrue(found.needs_confirmation)
        self.assertEqual(len(found.off_level), 1)
        group = found.off_level[0]
        self.assertEqual((group.cause, group.cells, group.area_m2), (road_engrave.EngraveCause.CUT_DENIED, 200, 200.0))
        self.assertAlmostEqual(group.max_m, 0.9, delta=TOL)
        centre = np.asarray((group.x, group.y)) - np.asarray(rd.BASE)
        np.testing.assert_allclose(centre, (200.0, 202.5), rtol=0.0, atol=TOL)
        self.assertAlmostEqual(found.section_cut_m3, 500.0 - 40 * 2.5, delta=TOL)
        self.assertAlmostEqual(found.section_fill_m3, 720.0, delta=TOL)
        notice = road_engrave.carriageway_notice(group, ENTITY, blocker="Zona sin corte")
        self.assertEqual(notice.code, "des.road_carriageway_masks")
        self.assertEqual((notice.values["area"], notice.values["difference"], notice.values["blocker"]), (200.0, 0.9, "Zona sin corte"))
        self.assertIn("Zona sin corte", notice.text())
        check_axis(self, road)
        check_invariants(self, road)

    def test_an_untouchable_next_to_the_road_is_not_moved_and_leaves_a_group_of_the_carriageway(self) -> None:
        """RF-017-06, RF-017-21, RF-017-22, CE-017-01: un intocable que la ruta no pisa (al norte del eje, de y = 203 a 208 m) pero al que llega la calzada (las filas a 3,5 y 4,5 m del eje) **no se mueve**
        ni se corta ni se rellena: esas 80 celdas quedan en el terreno (un grupo de la causa del corte, de 80 m², con 0,9 m de diferencia máxima) y el corte de la sección baja
        40 · (0,7 + 0,9) = 64 m³ (436 m³); la ruta no tiene ningún nodo en él y se pide la confirmación."""
        road = restricted_ramp("untouchable")
        found = road.found
        self.assertTrue(found.needs_confirmation)
        self.assertEqual([(group.cause, group.cells, group.area_m2) for group in found.off_level], [(road_engrave.EngraveCause.CUT_DENIED, 80, 80.0)])
        self.assertAlmostEqual(found.off_level[0].max_m, 0.9, delta=TOL)
        self.assertAlmostEqual(found.section_cut_m3, 500.0 - 40 * (0.7 + 0.9), delta=TOL)
        untouchable = road.job.untouchable
        mesh = road.route.mesh
        self.assertGreater(int(np.count_nonzero(~mesh.walkable)), 0)  # el intocable cierra nodos de la malla...
        self.assertTrue(all(bool(mesh.walkable[node]) for node in road.route.nodes))  # ...y la ruta no pisa ninguno
        start = road.job.start[road.window]
        np.testing.assert_array_equal(found.surface[untouchable[road.window]], start[untouchable[road.window]])  # ni el borde lo mueve
        check_axis(self, road)
        check_invariants(self, road)

    def test_a_height_limit_below_the_cross_slope_leaves_two_groups_with_the_height_cause(self) -> None:
        """RF-017-21, RF-017-22, CE-017-01: con una altura máxima de desmonte y terraplén de 0,5 m en la rampa del 20 % transversal, las filas de la calzada a 3,5 y 4,5 m del eje (0,7 y 0,9 m) **no se
        mueven** (la de 2,5 m, a 0,5 m justos, sí): dos grupos de la causa de la altura (el norte, que pediría cortar, y el sur, que pediría rellenar) de 400 celdas y 0,9 m de diferencia máxima, con el
        aviso de la altura; se pide la confirmación."""
        road = restricted_ramp("height")
        found = road.found
        self.assertTrue(found.needs_confirmation)
        self.assertEqual([(group.cause, group.cells, group.area_m2) for group in found.off_level], [(road_engrave.EngraveCause.MAX_HEIGHT, 400, 400.0)] * 2)
        self.assertEqual([round(group.max_m, 9) for group in found.off_level], [0.9, 0.9])
        self.assertEqual(sorted(round(group.y - rd.BASE[1]) for group in found.off_level), [196, 204])  # el sur (y de 195,5 a 196,5) y el norte (de 203,5 a 204,5)
        notice = road_engrave.carriageway_notice(found.off_level[0], ENTITY, height_m=0.5)
        self.assertEqual(notice.code, "des.road_carriageway_height")
        self.assertEqual((notice.values["area"], notice.values["height"]), (400.0, 0.5))
        check_axis(self, road)
        check_invariants(self, road)

    def test_the_axis_never_passes_the_straight_line_by_more_than_2_8_percent_in_any_direction(self) -> None:
        """RF-017-10, 11, 13, CE-017-01, D-22: en un plano del 4 % sin restricciones, con pd = 8 % y desde el centro a 14 destinos en los cuatro cuadrantes (los rumbos peores, a 13,28° del más
        próximo), el **eje** que sale de la cadena (la ruta simplificada, con curvas y con el origen y el destino exactos) no pasa de la distancia recta en más de un 2,8 % ni baja de ella."""
        grid = gis.Grid(west=rd.BASE[0], north=rd.BASE[1] + 160.0, dx=1.0, dy=1.0, ncols=160, nrows=160)
        terrain = rd.ramp_terrain(grid)
        mesh_m = rd.ROUTE.mesh_m

        def center(node: tuple[int, int]) -> tuple[float, float]:
            return (grid.west + (node[1] + 0.5) * mesh_m, grid.north - (node[0] + 0.5) * mesh_m)

        displacements = ((18, 0), (17, 4), (18, 4), (13, 3), (16, 16), (7, 14), (4, 17), (0, 18), (-17, 4), (-18, -11), (15, -7), (5, -17), (11, 2), (19, 5))
        worst = 0.0
        for dx, dy in displacements:
            origin, destination = (20, 20), (20 - dy, 20 + dx)
            job = rd.route_job(grid, terrain, center(origin), center(destination), route=rd.route_with(turn_m=4.0), profile=PD8)
            road = compose(job, engrave=False)
            straight = math.hypot(*(np.asarray(center(destination)) - np.asarray(center(origin))))
            ratio = road.axis.length_m / straight
            with self.subTest(displacement=(dx, dy)):
                self.assertGreaterEqual(ratio, 1.0 - TOL)
                self.assertLessEqual((ratio - 1.0) * 100.0, rd.DETOUR_BOUND_PCT)
                check_axis(self, road)
            worst = max(worst, ratio - 1.0)
        self.assertGreater(worst * 100.0, 1.0)  # el abanico llega a los rumbos peores: la cota no es vacía


# --- CE-017-02: el eje con curvas ------------------------------------------------------------------------------------------


def corner_job(points: Any, *, profile: rd.ProfileData = SHORT) -> Any:
    """Una pista «sobre un eje» sobre la línea ``points`` (locales) y el plano del 4 % (``rampa``)."""
    grid = rd.GRID
    return rd.axis_job(grid, rd.ramp_terrain(grid), rd.absolute(points, grid), profile=profile)


class CurveTest(unittest.TestCase):
    """CE-017-02: «dos tramos rectos perpendiculares con R = 20 m dan una tangente de 20 m, un arco de 31,416 m (π·R/2) y el eje a ≤ 10⁻⁹ m del arco analítico, con radio mínimo real de 20 m; con tramos
    de 15 m y Rmín = 12 m el radio se reduce a 15 m (el mayor que cabe) con el aviso del vértice; con Rmín = 16 m, el rechazo nombra el vértice, los tramos y el radio que cabría (15 m); con la línea
    dibujada («sobre un eje») da lo mismo y la línea no cambia»."""

    def test_two_perpendicular_legs_of_40_m_give_a_tangent_of_20_m_an_arc_of_31_416_m_and_the_analytic_circle(self) -> None:
        """RF-017-13, CE-017-02: la esquina de dos tramos de 40 m con R = 20 m, por la cadena entera: una curva de tangente 20 m y arco π·R/2 = 31,416 m (71,4159 m de eje), a ≤ 10⁻⁹ m de la
        circunferencia analítica (el centro, a 20 m de los dos tramos), con radio mínimo real de 20 m y la rasante, la sección y el grabado de la fuerza bruta en las mismas celdas."""
        road = compose(corner_job(rd.CORNER_LONG))
        by_hand = rd.corner_by_hand(40.0, 20.0)
        verify(self, road)
        axis = road.axis
        self.assertAlmostEqual(axis.length_m, by_hand.length_m, delta=TOL)
        self.assertEqual((axis.curve_count, axis.min_radius_m), (1, 20.0))
        curve = axis.curves[0]
        self.assertAlmostEqual(curve.tangent_m, by_hand.tangent_m, delta=TOL)
        self.assertAlmostEqual(curve.length_m, by_hand.arc_m, delta=TOL)
        self.assertAlmostEqual(by_hand.arc_m, math.pi * 20.0 / 2.0, delta=TOL)
        centre = np.asarray(rd.absolute([(80.0, 80.0)])[0])  # el vértice (100, 60) gira a la izquierda: el centro, a 20 m de cada tramo
        on_arc = (axis.stations >= 20.0) & (axis.stations <= 20.0 + by_hand.arc_m)
        distance = np.hypot(*(axis.points[on_arc] - centre).T)
        self.assertGreater(int(on_arc.sum()), 30)
        self.assertLessEqual(float(np.abs(distance - 20.0).max()), TOL)
        self.assertEqual(road.found.off_level, ())

    def test_legs_of_15_m_reduce_the_radius_to_15_m_with_the_notice_and_the_chain_goes_on(self) -> None:
        """RF-017-14, CE-017-02: con tramos de 15 m y Rmín = 12 m el radio baja al mayor que cabe, 15 m (tangente = tramo entero: el eje es solo el arco, π·15/2 = 23,562 m), con **un** aviso
        del vértice, el radio pedido, el que cabe y su lugar; la rasante, la sección y el grabado siguen sobre ese eje (a mano)."""
        road = compose(corner_job(rd.CORNER_SHORT))
        by_hand = rd.corner_by_hand(15.0, 20.0)
        self.assertAlmostEqual(road.axis.length_m, by_hand.length_m, delta=TOL)
        self.assertAlmostEqual(by_hand.length_m, math.pi * 15.0 / 2.0, delta=TOL)
        self.assertEqual(road.axis.curve_count, 1)
        self.assertAlmostEqual(road.axis.min_radius_m, by_hand.fitted_radius_m, delta=TOL)
        notices = road.axis.notices(ENTITY)
        self.assertEqual([item.code for item in notices], ["des.road_radius_reduced"])
        self.assertEqual((notices[0].values["vertex"], notices[0].values["radius"]), (2, 20.0))  # el vértice 2 de la línea de tres puntos
        self.assertAlmostEqual(notices[0].values["fitted"], 15.0, delta=TOL)
        self.assertIn("15", notices[0].text())
        check_axis(self, road)
        check_gradient(self, road)
        hand = check_section(self, road)
        check_engrave(self, road, hand)
        check_invariants(self, road)

    def test_with_a_minimum_radius_of_16_m_the_corner_of_15_m_is_rejected_naming_the_vertex_the_legs_and_the_radius(self) -> None:
        """RF-017-14, CE-017-02: con Rmín = 16 m el radio que cabe (15 m) no llega: el rechazo nombra el vértice, los dos tramos (15 m) y el radio que cabría (15 m), y **no se baja de Rmín** (no
        sale ninguna pista)."""
        job = corner_job(rd.CORNER_SHORT, profile=rd.profile_with(reach_m=12.5, min_radius_m=16.0))
        with self.assertRaises(road_axis.RadiusBelowMinimum) as caught:
            compose(job)
        error = caught.exception.error(layer="gis_fea_pistas_ejes", entity=ENTITY, profile=job.profile)
        self.assertIsInstance(error, messages.DesignError)
        self.assertEqual(error.code, "des.road_radius_below_min")
        self.assertEqual((error.values["vertex"], error.values["length_before"], error.values["length_after"], error.values["minimum"]), (2, 15.0, 15.0, 16.0))
        self.assertAlmostEqual(error.values["fitted"], 15.0, delta=1e-6)
        for expected in ("15", "16"):
            self.assertIn(expected, error.text)

    def test_the_drawn_line_is_not_changed_and_the_same_input_gives_the_same_road_bit_by_bit(self) -> None:
        """RF-017-02, RF-017-13, RF-015-02, CE-017-02, principio 7: la línea dibujada («sobre un eje») **no cambia** (hash antes y después, y de solo lectura), el trabajo y la superficie de partida
        tampoco, y la misma entrada con los mismos parámetros da la misma pista **bit a bit** (la ruta, el eje, la rasante, la sección y lo grabado)."""
        first_job = corner_job(rd.CORNER_LONG)
        before = digest(first_job.geometry.line, first_job.start, first_job.cut_allowed, first_job.fill_allowed, first_job.untouchable)
        first = compose(first_job)
        self.assertEqual(digest(first_job.geometry.line, first_job.start, first_job.cut_allowed, first_job.fill_allowed, first_job.untouchable), before)
        self.assertFalse(first_job.geometry.line.flags.writeable)
        second = compose(corner_job(rd.CORNER_LONG))
        self.assertEqual(fingerprint(first), fingerprint(second))
        np.testing.assert_array_equal(first_job.geometry.line, rd.absolute(rd.CORNER_LONG))

    def test_the_chain_of_a_route_is_the_chain_of_the_drawn_line_when_the_nodes_are_its_vertices(self) -> None:
        """RF-017-13, CE-017-02 («con la línea dibujada da lo mismo»): el eje que sale de unos nodos de ruta (con el origen y el destino exactos) y el de la línea con esos mismos vértices son el
        mismo: longitud, curvas, puntos y azimut, bit a bit."""
        line = rd.absolute(rd.CORNER_LONG)
        profile = SHORT
        from_line = road_axis.axis_of(line, profile.curve_radius_m, profile.min_radius_m, profile.station_step_m)
        from_route = road_axis.axis_of(line, profile.curve_radius_m, profile.min_radius_m, profile.station_step_m, simplify_m=4.0, origin=tuple(line[0]), destination=tuple(line[-1]))
        self.assertEqual((from_route.length_m, from_route.curve_count), (from_line.length_m, from_line.curve_count))
        np.testing.assert_array_equal(from_route.points, from_line.points)
        np.testing.assert_array_equal(from_route.azimuth, from_line.azimuth)


# --- CE-017-03: la rasante -------------------------------------------------------------------------------------------------


def step_job(line: Any, *, profile: rd.ProfileData = SHORT, **levels: float) -> Any:
    """Una pista «sobre un eje» sobre el terreno en escalón, con las cotas de inicio y de fin que se den."""
    grid = rd.GRID
    job = rd.axis_job(grid, rd.step_terrain(grid), rd.absolute(line, grid), profile=profile)
    return dataclasses.replace(job, **levels)


class StepTest(unittest.TestCase):
    """CE-017-03: «un perfil del terreno en escalón (0 m hasta la abscisa 0 y 6 m después, en un eje de 200 m centrado en el escalón) con pd = 10 % da una rampa del 5 % (pd/2) entre las abscisas −60 m y
    +60 m, con la diferencia con el terreno sumando 180 m·m; con los extremos a 0 y a 20 m en un eje de 100 m, el rechazo dice «necesaria 200 m, el eje mide 100 m»; con pm = 2 %, la media (3 %) da el
    aviso; con un «eje 3D» de Z irregular, el aviso por tramo y la línea sin cambiar. Los 5 % y los 180 m·m son los del perfil continuo: con estaciones cada w m, un oráculo en esas mismas estaciones y
    la cifra continua con un error O(w)»."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.road = compose(step_job(rd.STEP_AXIS))

    def test_the_gradient_is_the_oracle_in_the_same_stations_and_the_continuous_ramp_within_o_w(self) -> None:
        """RF-017-15, CE-017-03: la rasante del escalón (muestreado en una rejilla de 1 m: la bilineal alisa el salto en 1 m) es la del oráculo O(n²) **en esas mismas estaciones** (≤ 10⁻⁹ m); con
        pd = 10 % sube del 0 al 6 m en una rampa del 5 % entre −60 y +60 m y su diferencia con el terreno suma 180 m·m: la cifra continua, con un error O(w) = O(1 m)."""
        road = self.road
        verify(self, road, brute=False)
        s = road.axis.stations - 100.0  # la abscisa desde el escalón
        slope = (road.z[np.searchsorted(s, 59.0)] - road.z[np.searchsorted(s, -59.0)]) / 118.0 * 100.0
        self.assertAlmostEqual(float(slope), rd.STEP_RAMP_PCT, delta=0.1)
        diff = float(np.trapezoid(np.abs(road.z - road.terrain), s))
        self.assertAlmostEqual(diff, rd.STEP_DIFF_MM, delta=10.0 * road.axis.step_m)  # O(w): el discreto resta ≈ 3·w y el alisado de la bilineal, ≈ 6·w
        analytic = rd.step_grade_by_hand(s, 10.0)
        self.assertLessEqual(float(np.abs(road.z - analytic).max()), 0.1)  # pd·w: lo que el alisado del muestreo mueve la rampa
        flat = np.abs(s) > rd.STEP_RAMP_TO_M + 1.0
        np.testing.assert_allclose(road.z[flat], np.where(s[flat] < 0.0, rd.STEP_LOW_M, rd.STEP_HIGH_M), rtol=0.0, atol=TOL)  # donde el terreno no pasa de pd: el terreno

    def test_the_mean_gradient_is_3_percent_and_with_pm_2_percent_it_warns_with_the_steepest_stretches(self) -> None:
        """RF-017-17, CE-017-03: la media de la rampa del escalón (Σ|Δcota|/S = 6 m sobre 200 m) es del **3,000 %** (≤ 10⁻⁹), por debajo de pm = 10 %; con pm = 2 % da el aviso
        (``des.road_mean_gradient``) con la media, el límite y los tramos de mayor pendiente con su abscisa y su lugar (la confirmación y el motivo los registra la T21)."""
        road = self.road
        self.assertAlmostEqual(road_gradient.mean_gradient(road.axis.stations, road.z) * 100.0, rd.STEP_MEAN_PCT, delta=TOL)
        self.assertIsNone(road_gradient.mean_gradient_notice(road.axis, road.z, road.job.profile, ENTITY))
        strict = rd.road_profile(rd.profile_with(reach_m=12.5, max_mean_gradient_pct=2.0))
        notice = road_gradient.mean_gradient_notice(road.axis, road.z, strict, ENTITY)
        self.assertEqual(notice.code, "des.road_mean_gradient")
        self.assertAlmostEqual(notice.values["mean"], rd.STEP_MEAN_PCT, delta=TOL * 100.0)
        self.assertEqual((notice.values["limit"], len(notice.values["stretches"])), (2.0, road_gradient.LISTED_STRETCHES))
        text = notice.text()
        for expected in ("3,00", "2,00"):
            self.assertIn(expected, text)

    def test_the_short_axis_with_the_ends_at_0_and_20_m_is_rejected_saying_200_m_needed_and_100_m_of_axis(self) -> None:
        """RF-017-16, CE-017-03: con los extremos a 0 y a 20 m en un eje de 100 m y pd = 10 %, la pista se rechaza (``DropTooSteep``) con la longitud del eje (100 m), la necesaria (**200 m**) y el
        desnivel (20 m), sin cambiar las cotas ni la pendiente por su cuenta (no sale ninguna pista)."""
        job = step_job(rd.SHORT_AXIS, start_level_m=rd.SHORT_Z_START_M, end_level_m=rd.SHORT_Z_END_M)
        with self.assertRaises(road_gradient.DropTooSteep) as caught:
            compose(job)
        drop = caught.exception
        self.assertEqual((drop.length_m, drop.drop_m, drop.needed_m), (100.0, 20.0, rd.SHORT_NEEDED_M))
        error = drop.error(layer="gis_fea_pistas_ejes", entity=ENTITY, profile=job.profile)
        self.assertEqual(error.code, "des.road_drop_too_steep")
        for expected in ("200", "100", "20"):
            self.assertIn(expected, error.text)
        self.assertEqual((job.start_level_m, job.end_level_m), (rd.SHORT_Z_START_M, rd.SHORT_Z_END_M))

    def test_the_irregular_3d_axis_warns_per_stretch_and_the_line_is_not_changed(self) -> None:
        """RF-017-18, CE-017-03: la línea 3D de Z irregular (11 vértices: 15 % en el cuarto tramo y 12 % en el séptimo de 20 m, los de 10 % exactos no pasan) da, por la cadena, **un aviso por tramo
        entre estaciones** que pasa de pd (2 × 20 estaciones), el de la media (7,2 % frente a pm = 5 %) con sus tramos, ninguno del radio (recta), **la línea sin cambiar** (hash antes y después) y
        se graba con la Z como rasante (las cotas de las celdas, las de la línea en su abscisa; el grabado contra la fuerza bruta, en ``milestone_roads_h1``)."""
        grid = rd.GRID
        line = rd.axis_3d_irregular()
        job = axis_3d_job(grid, rd.ramp_terrain(grid), line, profile=rd.profile_with(reach_m=12.5, max_mean_gradient_pct=5.0))
        before = digest(job.geometry.line)
        road = compose(job)
        self.assertEqual(digest(job.geometry.line), before)
        np.testing.assert_array_equal(job.geometry.line, rd.axis_3d_irregular())
        verify(self, road, brute=False)
        np.testing.assert_allclose(road.z, 104.0 + np.interp(road.axis.stations, 20.0 * np.arange(11), np.concatenate(([0.0], np.cumsum(rd.AXIS_3D_INCREMENTS_M)))), rtol=0.0, atol=TOL)
        notices = road_gradient.check_axis_3d(road.axis, road.z, job.profile, ENTITY)
        codes = [item.code for item in notices]
        self.assertEqual(codes, ["des.road_axis3d_gradient"] * 40 + ["des.road_mean_gradient"])
        self.assertEqual(sorted({round(item.values["gradient"], 6) for item in notices[:40]}), [12.0, 15.0])
        self.assertAlmostEqual(notices[-1].values["mean"], rd.AXIS_3D_MEAN_PCT, delta=TOL * 100.0)
        self.assertEqual(road.axis.below_minimum, ())

    def test_a_3d_corner_below_the_minimum_radius_warns_with_the_radius_and_is_not_rejected(self) -> None:
        """RF-017-18, RF-017-14, CE-017-03: una línea 3D con una esquina de tramos de 15 m y Rmín = 16 m **no se rechaza** (es una entrada: el radio es un aviso): el eje la lleva con el radio que cabe
        (15 m), ``des.road_axis3d_radius`` con la abscisa y el lugar, y no se repite como «el radio baja»; la línea no cambia."""
        grid = rd.GRID
        planar = rd.absolute(rd.CORNER_SHORT, grid)
        line = np.column_stack([planar, 140.0 + 0.04 * np.array([0.0, 15.0, 30.0])])
        job = axis_3d_job(grid, rd.ramp_terrain(grid), line, profile=rd.profile_with(reach_m=12.5, min_radius_m=16.0))
        before = digest(job.geometry.line)
        road = compose(job, engrave=False)
        self.assertEqual(digest(job.geometry.line), before)
        notices = road_gradient.check_axis_3d(road.axis, road.z, job.profile, ENTITY)
        self.assertEqual([item.code for item in notices], ["des.road_axis3d_radius"])
        self.assertAlmostEqual(notices[0].values["radius"], 15.0, delta=TOL)
        self.assertEqual(notices[0].values["minimum"], 16.0)
        self.assertEqual(road.axis.notices(ENTITY), ())


# --- CE-017-04: la ladera del 38 % y sin ruta ------------------------------------------------------------------------------


class HillsideTest(unittest.TestCase):
    """CE-017-04: «en un plano del 38 % con la curva de nivel a 22,5° de un eje de la rejilla y pd = 10 %, la menor pendiente de paso que ofrecen los 16 rumbos es del 2,7 % y la ruta existe y no pasa de
    pd; con un perímetro que solo deja pasar una franja de un nodo para un desnivel de 30 m, no hay ruta y no se registra nada»."""

    def test_the_route_exists_and_the_axis_gradient_never_passes_2_7_percent_nor_pd(self) -> None:
        """RF-017-11, CE-017-04, B2: la pista «trazar» de la ladera del 38 % (de (100, 100) a (180, 140), 89,443 m en el rumbo (2, 1)) **existe** con los parámetros de la referencia (14 m de altura): la
        ruta son diez pasos del rumbo (2, 1), el eje (con el origen y el destino exactos) es recto y mide 10·√80 = 89,443 m, el terreno en su eje tiene el **2,694 %** (0,38·sen 4,065°, a
        ≤ 10⁻⁹) y la rasante lo sigue (movimiento 0 m): su pendiente máxima es esa, no pasa de pd = 10 %."""
        grid = rd.GRID
        origin, destination = (tuple(float(v) for v in rd.absolute([point], grid)[0]) for point in (rd.HILL_ORIGIN, rd.HILL_DESTINATION))
        job = rd.route_job(grid, rd.hillside_terrain(grid), origin, destination, route=rd.ROUTE, profile=rd.profile_with(max_gradient_pct=10.0, reach_m=12.5))
        road = compose(job, engrave=False)
        check_axis(self, road)
        check_gradient(self, road)
        self.assertTrue(road.route.ok)
        self.assertEqual(len(road.route.nodes), rd.HILL_STEPS + 1)
        self.assertEqual((road.axis.curve_count, road.axis.min_radius_m), (0, None))
        self.assertAlmostEqual(road.axis.length_m, rd.HILL_STEPS * math.sqrt(80.0), delta=TOL * 89.45)
        gradient = 0.38 * math.sin(math.atan(0.5) - math.radians(rd.HILL_CONTOUR_DEG)) * 100.0
        np.testing.assert_allclose(road.z, road.terrain, rtol=0.0, atol=TOL)
        figures = road.figures()
        self.assertAlmostEqual(figures["des.road_gradient_max_pct"], gradient, delta=1e-7)
        self.assertAlmostEqual(figures["des.road_gradient_mean_pct"], gradient, delta=1e-7)
        self.assertLess(figures["des.road_gradient_max_pct"], 10.0)
        self.assertEqual(round(gradient, 1), 2.7)

    def test_the_same_traced_road_is_the_same_bit_by_bit_and_its_inputs_do_not_change(self) -> None:
        """RF-015-02, RF-017-10, principio 7, CE-017-04: la misma pista «trazar» (la ruta, el eje, la rasante, la sección, lo grabado y las veintitrés cifras) con las mismas entradas es la misma **bit
        a bit**, y ni la superficie de partida ni las máscaras cambian."""
        def job() -> Any:
            grid = rd.GRID
            origin, destination = (tuple(float(v) for v in rd.absolute([point], grid)[0]) for point in (rd.HILL_ORIGIN, rd.HILL_DESTINATION))
            return rd.route_job(grid, rd.hillside_terrain(grid), origin, destination, route=rd.ROUTE, profile=rd.profile_with(max_gradient_pct=10.0, reach_m=12.5))

        first_job = job()
        before = digest(first_job.start, first_job.cut_allowed, first_job.fill_allowed, first_job.untouchable)
        first = compose(first_job)
        self.assertEqual(digest(first_job.start, first_job.cut_allowed, first_job.fill_allowed, first_job.untouchable), before)
        self.assertEqual(fingerprint(first), fingerprint(compose(job())))
        check_invariants(self, first)

    def test_the_strip_without_a_route_creates_nothing_and_changes_nothing(self) -> None:
        """RF-017-12, CE-017-04: en la franja de un nodo (100 m, 30 m de desnivel y pd = 10 %: hacen falta 300 m) la cadena **se detiene en la ruta**: el rechazo
        (``des.road_no_route_corridor``) da la cota mayor alcanzada (110 m), la pendiente mínima necesaria (30 %) y el tramo limitante, **sin crear nada** (ni eje, ni rasante, ni sección) y sin
        cambiar lo que lee; con el intocable que cierra el único paso, el rechazo de la red 2D (``des.road_no_route_network``)."""
        for closed, code in ((False, "des.road_no_route_corridor"), (True, "des.road_no_route_network")):
            job, mesh, corridor = strip_case(closed=closed)
            before = digest(job.start, job.untouchable, mesh.z, corridor.net_origin.dist, corridor.net_dest.dist)
            with self.subTest(closed=closed), self.assertRaises(messages.DesignError) as caught:
                compose(job)
            self.assertEqual(caught.exception.code, code)
            for expected in ("30 %", "no se relaja ningún límite", "no se crea nada"):
                self.assertIn(expected, caught.exception.text)
            self.assertEqual(digest(job.start, job.untouchable, mesh.z, corridor.net_origin.dist, corridor.net_dest.dist), before)
        job, _mesh, _corridor = strip_case()
        with self.assertRaises(messages.DesignError) as caught:
            compose(job)
        self.assertIn("110", caught.exception.text)


# --- CE-017-06: la sección -------------------------------------------------------------------------------------------------


class SectionTest(unittest.TestCase):
    """CE-017-06: «una pista de eje recto de 200 m con la sección de 11,5 m tiene una huella de 200 m ± 1 celda a lo largo del eje (no 211,5 m) y la calzada, el arcén y el caballón del perfil a ≤ 10⁻⁹ m; con
    cotas iguales a ambos lados, el caballón a la derecha en el sentido de la marcha; con una pendiente transversal, el arcén en el lado de mayor cota»."""

    def test_the_footprint_of_the_200_m_road_is_200_m_and_its_cells_are_the_hand_calculation(self) -> None:
        """RF-017-20, CE-017-06 (error 20): la huella de la pista «trazar» de 200 m con la sección de 11,5 m (por la cadena: la ruta, el eje y la ventana de trabajo del grabado) mide **200 m ± 1
        celda** a lo largo del eje —no los 211,5 m de un *buffer*— y su calzada (2.000 celdas) y su caballón (200) son, a ≤ 10⁻⁹ m, los de las fórmulas cerradas en las mismas celdas."""
        road = ramp(0.0)
        section = road.section
        self.assertLessEqual(abs(section.length_m - rd.RAMP_LENGTH_M), rd.GRID.dx)
        self.assertGreater(abs(section.length_m - 211.5), 10.0)
        hand = rd.ramp_calzada_by_hand(1.0)
        self.assertEqual(section.count_of(road_section.SectionClass.CARRIAGEWAY), 2 * hand.rows_per_side * hand.columns)
        self.assertEqual(section.count_of(road_section.SectionClass.SHOULDER), 0)
        self.assertEqual(section.count_of(road_section.SectionClass.BERM), hand.columns)
        closed = rd.straight_section_by_hand(rd.GRID, plane(0.0), road.carriageway_m, 0.0, 1.0)
        window = road.window
        np.testing.assert_array_equal(section.kind, closed.kind[window])
        np.testing.assert_array_equal(section.side, closed.side[window])
        np.testing.assert_allclose(section.sigma, closed.sigma[window], rtol=0.0, atol=TOL, equal_nan=True)
        np.testing.assert_allclose(section.lateral, closed.lateral[window], rtol=0.0, atol=TOL, equal_nan=True)

    def test_with_equal_heights_the_berm_is_on_the_right_and_with_a_cross_slope_the_shoulder_on_the_higher_side(self) -> None:
        """RF-017-20, CE-017-06, D-12: con cotas iguales a ambos lados el caballón va a la derecha en el sentido de la marcha (al sur, hacia el este) y, con el arcén de 1,5 m, este a la izquierda; con el 20 %
        de pendiente transversal (al norte), el arcén va al **lado de mayor cota** (el norte, a la izquierda): por la cadena y a ≤ 10⁻⁹ m de las fórmulas cerradas."""
        for cross, shoulder_side in ((0.0, road_section.LEFT), (rd.RAMP_CROSS_PCT, road_section.LEFT)):
            road = ramp(cross, 1.5)
            section = road.section
            closed = rd.straight_section_by_hand(rd.GRID, plane(cross), road.carriageway_m, 1.5, 1.0)
            with self.subTest(cross_pct=cross):
                shoulder = section.kind == road_section.SectionClass.SHOULDER
                berm = section.kind == road_section.SectionClass.BERM
                self.assertTrue(bool((section.side[shoulder] == shoulder_side).all()))
                self.assertTrue(bool((section.side[berm] == road_section.RIGHT).all()))
                self.assertEqual((int(shoulder.sum()), int(berm.sum())), (400, 200))
                np.testing.assert_array_equal(section.kind, closed.kind[road.window])
                np.testing.assert_allclose(section.lateral, closed.lateral[road.window], rtol=0.0, atol=TOL, equal_nan=True)


# --- E1: la pista a la plataforma del fondo --------------------------------------------------------------------------------

E1_GROUND_M = 190.0
"""El terreno llano que rodea la cantera de E1 (m): el borde, a 15 m sobre el fondo."""
E1_FLOOR = qfx.FLOORS[1]
"""«Plataforma 175» de la cantera de la 014: el fondo de 175 m, de (220, 200) a (300, 260) locales (80 × 60 m)."""
E1_TRENCH: tuple[tuple[float, float], ...] = ((220.0, 230.0), (100.0, 230.0), (100.0, 140.0))
"""El eje del corredor de acceso (local; como el de la 014, una polilínea con una esquina): sale del borde oeste del fondo, 120 m al oeste y 90 m al sur: **210 m**."""
E1_TRENCH_PCT = 8.0
E1_TRENCH_HALF_M = 10.0
"""Su rasante (125 + … en la 014; aquí 175 m + 8 % de la abscisa) y su semiancho (20 m de ancho, como el de la 014)."""
E1_ORIGIN: tuple[float, float] = (102.0, 146.0)
E1_DESTINATION: tuple[float, float] = (262.0, 230.0)
"""El origen, en el borde (el terreno llano: 190 m), y el destino, el centro de la plataforma (175 m)."""
E1_DROP_M = E1_GROUND_M - E1_FLOOR.level_m
"""El desnivel de E1 (15 m): con pd = 10 %, hacen falta ≥ 150 m de pista (``rd.needed_length_m``)."""


def e1_surface(grid: Any) -> np.ndarray:
    """La cantera de E1 en los centros de ``grid`` (m, float64): terreno llano a 190 m, el fondo de 175 m de ``qfx.FLOORS[1]`` con paredes de 45° (``175 + distancia a la caja``, tope 190 m) y el
    corredor de 20 m de ancho que baja del borde al fondo con su rasante del 8 % (``175 + 0,08·abscisa``, desde el borde oeste del fondo), como el de la 014.

    **El escenario es propio, no la superficie de explotación de la 014**: esa pide un proyecto (máscaras, sectores, capas) y la tarea es «sin proyecto»; y el terreno de la 014 queda 70 m sobre
    ese fondo (una pista de unos 700 m). Aquí es un terreno de 190 m y un fondo de 175 m con el fondo, la plataforma y el corredor de la 014 (anotado en la *Verificación* de la T14)."""
    x, y = rd.local_centers(grid)
    left, bottom, right, top = E1_FLOOR.box
    walls = np.minimum(E1_GROUND_M, E1_FLOOR.level_m + np.hypot(np.maximum(np.maximum(left - x, x - right), 0.0), np.maximum(np.maximum(bottom - y, y - top), 0.0)))
    points = np.array(E1_TRENCH)
    legs = np.diff(points, axis=0)
    length = np.hypot(legs[:, 0], legs[:, 1])
    chord = np.concatenate(([0.0], np.cumsum(length)))
    nearest = np.full(x.shape, np.inf)
    abscissa = np.zeros(x.shape)
    for leg in range(len(length)):
        ux, uy = legs[leg] / length[leg]
        ox, oy = x - points[leg, 0], y - points[leg, 1]
        along = np.clip(ox * ux + oy * uy, 0.0, length[leg])
        distance2 = (ox - along * ux) ** 2 + (oy - along * uy) ** 2
        closer = distance2 < nearest
        nearest[closer] = distance2[closer]
        abscissa[closer] = chord[leg] + along[closer]
    trench = E1_FLOOR.level_m + E1_TRENCH_PCT / 100.0 * abscissa
    return np.where(nearest <= E1_TRENCH_HALF_M ** 2, np.minimum(walls, trench), walls)


def e1_job(step_m: float, mesh_m: float, simplify_m: float, profile: rd.ProfileData, margin_m: float = 60.0) -> Any:
    """La pista «trazar» de E1 (de ``E1_ORIGIN`` a ``E1_DESTINATION``) en una rejilla de ``step_m`` m, con la malla de la ruta de ``mesh_m`` m (HIPÓTESIS de la prueba: la holgura de 60 m de RNF-017-02 y
    la simplificación de un nodo) y el perfil ``profile``."""
    grid = rd.grid_of(step_m)
    origin, destination = (tuple(float(v) for v in rd.absolute([point], grid)[0]) for point in (E1_ORIGIN, E1_DESTINATION))
    return rd.route_job(grid, e1_surface(grid), origin, destination, route=rd.route_with(mesh_m=mesh_m, margin_m=margin_m, simplify_m=simplify_m), profile=profile)


class E1Test(unittest.TestCase):
    """E1 (``spec.md`` §2 y §10.1), en pequeño: «una pista «trazar» desde la entrada de la cantera, en el borde (a unos 200 m), hasta la plataforma del fondo, a 175 m: ruta, curvas, rasante, sección y
    grabado, con su resumen (longitud, pendientes, radio mínimo, corte y relleno)»."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.job = e1_job(2.0, 8.0, 8.0, SHORT)
        cls.road = compose(cls.job)

    def test_the_whole_chain_of_the_road_to_the_platform_is_the_hand_calculation(self) -> None:
        """RF-017-09 a 18, 20 a 23, E1: la ruta (malla de 8 m en la rejilla de 2 m) baja del borde por el corredor del 8 % hasta la plataforma; el eje (con sus curvas de R = 20 m), la rasante
        (de 190 a 175 m, **pendiente media = desnivel/longitud** porque baja siempre), la sección y el grabado (con la métrica exacta y el alcance de 12,5 m) son los del cálculo a mano en las mismas
        celdas (≤ 10⁻⁹): el eje desde sus vértices con las fórmulas cerradas, la rasante con el oráculo O(n²), la sección con la fuerza bruta y el grabado con un bucle por celda y la envolvente de todas
        las semillas; la superficie de partida es igual fuera de lo que mueve y la pista cabe en las veintitrés cifras de RF-017-23."""
        road = self.road
        hand = verify(self, road)
        self.assertTrue(road.route.ok)
        self.assertEqual((road.route.nodes[0], road.route.nodes[-1]), (road.route.mesh.node_of(*self.job.geometry.origin), road.route.mesh.node_of(*self.job.geometry.destination)))
        self.assertGreaterEqual(road.axis.curve_count, 1)
        self.assertEqual(road.axis.min_radius_m, 20.0)
        self.assertGreater(road.axis.deviation_m, 0.0)
        self.assertGreater(int(hand.cells.sum()), 500)
        self.assertEqual(road.found.off_level, ())
        self.assertFalse(road.found.needs_confirmation)

    def test_the_figures_of_the_road_are_the_hand_figures(self) -> None:
        """RF-017-23, E1: las cifras: la cota de inicio es la del borde (**190,000 m**) y la de fin, la de la plataforma (**175,000 m**), el desnivel (−15,000 m) pide ≥ 150 m (``H/pd``) y el eje mide más
        que eso y que la distancia recta; la pendiente máxima no pasa de pd (10 %) y la media es el desnivel entre la longitud (la rasante no sube ni un tramo: Σ|Δcota| = 15 m, ≤ 10⁻⁹); el radio
        mínimo es el de diseño (20 m) y las anchuras, las del perfil (10,5 m y 11,5 m); el corte y el relleno de la sección y del borde, positivos, y el neto, su diferencia."""
        road = self.road
        figures = road.figures()
        self.assertEqual((figures["des.road_z_start_m"], figures["des.road_z_end_m"]), (E1_GROUND_M, E1_FLOOR.level_m))
        self.assertAlmostEqual(figures["des.road_drop_m"], -E1_DROP_M, delta=TOL)
        needed = rd.needed_length_m(E1_DROP_M, 10.0)
        straight = math.hypot(E1_DESTINATION[0] - E1_ORIGIN[0], E1_DESTINATION[1] - E1_ORIGIN[1])
        self.assertAlmostEqual(needed, 150.0, delta=TOL)
        self.assertGreater(figures["des.road_length_m"], max(needed, straight))
        self.assertLessEqual(figures["des.road_gradient_max_pct"], 10.0 + 1e-7)
        self.assertAlmostEqual(figures["des.road_gradient_mean_pct"], E1_DROP_M / figures["des.road_length_m"] * 100.0, delta=1e-7)
        self.assertEqual((figures["des.road_radius_min_m"], figures["des.road_width_m"], figures["des.road_section_m"]), (20.0, 10.5, 11.5))
        for key in ("des.road_cut_m3", "des.road_fill_m3", "des.road_edge_cut_m3", "des.road_edge_fill_m3"):
            self.assertGreater(figures[key], 0.0, key)
        self.assertAlmostEqual(figures["des.road_net_m3"], road.found.cut_m3 - road.found.fill_m3, delta=1e-6)
        self.assertEqual(len(figures), 23)

# --- La rampa a una cota (E4, sin la accesibilidad) -------------------------------------------------------------------------

LEVEL_ZONE_BOX = (10.0, 78.0, 50.0, 94.0)
"""La zona de la rampa (local): un rectángulo de 40 × 16 m en la berma de 125 m de la cantera con bancos."""
LEVEL_ORIGIN = (10.0, 20.0)
"""El origen (local): el terreno llano de 140 m, la entrada de la cantera con bancos (``rd.BANK_ENTRY``)."""
LEVEL_M = 125.0
LEVEL_TOLERANCE_M = 0.5
"""La cota que se pide en la zona y la tolerancia de llegada (HIPÓTESIS de la prueba)."""


def level_job() -> Any:
    """La pista «trazar» **a una cota** (la rampa, D-4) sobre la cantera con bancos de E4 (rejilla de 2 m): del terreno de entrada (140 m) a la zona de la berma de 125 m, con pd = 20 % (ITC: los accesos a
    tajos, hasta el 20 %), la holgura de 12 m (HIPÓTESIS de la prueba) y el resto del perfil de referencia."""
    grid = rd.grid_of(2.0)
    left, bottom, right, top = LEVEL_ZONE_BOX
    ring = rd.absolute([(left, bottom), (right, bottom), (right, top), (left, top)], grid)
    destination = road_model.LevelDestination(LEVEL_M, LEVEL_TOLERANCE_M, ((ring,),))
    origin = tuple(float(v) for v in rd.absolute([LEVEL_ORIGIN], grid)[0])
    job = rd.route_job(grid, rd.bank_surface(grid), origin, destination, route=rd.route_with(margin_m=12.0), profile=rd.profile_with(max_gradient_pct=20.0, reach_m=12.5))
    return dataclasses.replace(job, request=dataclasses.replace(job.request, dest_zone="gis_fea_pistas_zonas"))


class LevelRampTest(unittest.TestCase):
    """E4 (sin la accesibilidad; RF-017-02, RF-017-10): «la rampa a una cota por los bancos»."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.road = compose(level_job())

    def test_the_ramp_ends_in_the_zone_at_the_requested_level_and_the_chain_is_the_hand_calculation(self) -> None:
        """RF-017-02, RF-017-10, RF-017-15, 20, 21, D-4, E4: la ruta termina en el primer nodo de la zona cuya cota de partida difiere de la pedida en menos de la tolerancia, el destino alcanzado (lugar
        y cota) cae **dentro de la zona**, el eje acaba exacto en ese nodo, la rasante acaba **en la cota pedida (125,000 m)** tras bajar 15 m desde el terreno de entrada (140 m), no pasa de pd = 20 %
        ni de pd·longitud (los 15 m piden ≥ 75 m de eje), y la sección y el grabado son los de la fuerza bruta en las mismas celdas."""
        road = self.road
        verify(self, road)
        arrival = road.arrival
        self.assertIsNotNone(arrival)
        left, bottom, right, top = LEVEL_ZONE_BOX
        local = np.asarray((arrival.x, arrival.y)) - np.asarray(rd.BASE)
        self.assertTrue(left < local[0] < right and bottom < local[1] < top)
        self.assertLess(abs(arrival.terrain_m - LEVEL_M), LEVEL_TOLERANCE_M)
        self.assertEqual((arrival.requested_m, arrival.within_tolerance), (LEVEL_M, True))
        self.assertEqual(road.route.nodes[-1], arrival.node)
        figures = road.figures()
        self.assertEqual((figures["des.road_z_start_m"], figures["des.road_z_end_m"]), (140.0, LEVEL_M))
        self.assertAlmostEqual(figures["des.road_drop_m"], -15.0, delta=TOL)
        self.assertGreaterEqual(figures["des.road_length_m"], rd.needed_length_m(15.0, 20.0) - TOL)
        self.assertLessEqual(figures["des.road_gradient_max_pct"], 20.0 + 1e-7)
        self.assertGreaterEqual(figures["des.road_gradient_mean_pct"], 15.0 / figures["des.road_length_m"] * 100.0 - 1e-7)

if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: GPL-3.0-or-later
"""La ruta 3D de mínimo coste de una pista (spec 017, T07; HU-017-1; RF-017-10, 11 y 06; RF-015-02; RNF-017-02, 06 y 07; plan 017 §5.4 A2,
§5.7 P-3, P-7 y P-13, §6, §7.3, §8 y §9; D-23).

Lo que da, todo en el dominio (Python y numpy, sin Blender), con las coordenadas absolutas en float64 (regla 4 de AGENTS.md):

- **La búsqueda** (:func:`route_steps` → :class:`Route`; RF-017-10): un **A\\*** sobre los estados ``(nodo, nivel, rumbo)`` de la malla de
  la ruta (:mod:`design.road_net`) dentro del pasillo (:func:`~design.road_net.corridor`). El **nivel** ``m ∈ [−M, M]`` (``M = ⌊H/Δz⌋``,
  con ``H`` la altura máxima de desmonte y terraplén y ``Δz`` el paso de cota) es **relativo al terreno de su nodo**: la cota es
  ``z(n) + m·Δz``, de modo que ``|cota − terreno| ≤ H`` es el rango. De ``(n, m, h)`` se pasa a ``(n + paso(h'), m + j, h')`` con ``h'`` en
  ``{h − 1, h, h + 1}`` módulo 16 («a lo sumo al contiguo») y ``j`` entero con ``|Δterreno + j·Δz| ≤ pd·L(h')`` (con 10⁻⁹ m de margen):
  las tablas ``j`` mínimo y máximo por rumbo y nodo se calculan una vez con numpy. El paso es admisible además por el filtro de la red 2D
  (:func:`~design.road_net.step_masks`: ningún extremo ni nodo intermedio prohibido o sin dato —RF-017-06— y ``|Δterreno| ≤ pd·L + 2H``) y
  no sale del pasillo. Arranca en el origen con el nivel de la cota de inicio y **los 16 rumbos a coste 0** (el rumbo de partida es libre);
  acaba al **extraer** el destino (un nodo o un conjunto de nodos: el destino por cota, T08) con el nivel de la cota de fin.
- **El coste del paso** (P-7): ``L(h')·(1 + λ·Δz·(|m| + |m'|)/2)·w + giro·[h' ≠ h]``, con ``λ`` el peso del movimiento de tierras (1/m: el
  desvío se mide en la **media de los dos extremos**), ``w`` el peso (≥ 1) de las zonas «preferible no afectar» de RF-017-06 (la media de
  los dos nodos; 1 sin zonas) y ``giro`` la penalización (m) por rumbo cambiado. **Cada paso cuesta al menos su longitud**, así que la
  distancia de la red 2D al destino es una **cota admisible y consistente** (``h(n) = d_d(n)``) y el A\\* es exacto.
- **Determinismo y desempates** (D-23, RF-015-02): con las mismas entradas, la misma ruta **bit a bit**. El coste es **entero**
  (:data:`COST_SCALE` unidades por metro: nanómetros; cada paso se redondea una vez) para que los empates sean **exactos**, también entre
  rutas que suman los mismos pasos en otro orden (con ``float`` la última cifra los rompería). Las etiquetas se comparan por ``(coste,
  giros)`` y, a igualdad, por el rumbo y el desvío del paso que las llegó (el menor primero); la cola ordena por ``(f, giros, rumbo,
  estado)``: gana la ruta de **menos giros** y, a igual número, la del **primer rumbo en sentido horario desde el norte** al llegar. Cada
  estado visto es **un solo entero** (el coste, los giros y de dónde viene empaquetados: la ruta se reconstruye sin otro diccionario) y cada
  entrada de la cola, otro: ≈ 135–140 bytes por estado visto medidos (965 MiB de pico del proceso con 5,98 M estados vistos en el barranco con
  60 m de holgura y 1.163 MiB con 7,44 M en la ladera del 38 %, con 167 MiB de base: los peores casos del plan §7.3 con el presupuesto de
  5 M; el plan estimaba 150 bytes sin guardar de dónde viene cada estado).
- **El presupuesto** (P-3, ADOPTADO «sin confirmar», :data:`~design.road_model.DEFAULT_SEARCH_BUDGET`): la búsqueda se **detiene** a
  ``search_budget`` estados expandidos y lo dice (:class:`Route` con ``ok`` falso, los estados expandidos y la causa
  :attr:`~design.road_model.NoRouteCause.BUDGET`): **no** es «no hay ruta». Agotar el pasillo sin llegar es
  :attr:`~design.road_model.NoRouteCause.CORRIDOR` y una red 2D que no alcanza el origen, :attr:`~design.road_model.NoRouteCause.NETWORK`;
  la explicación con cifras («por qué no hay ruta», con la cota alcanzada y el tramo limitante) es de T08.
- **Por pasos** (RNF-017-06, P-13, plan §9): **un bucle de Python por estado expandido** —la excepción al principio 9 que pide y aprueba
  el plan §9 (S-2), con el presupuesto y los pasos como condición; el A\\* **no usa numpy por iteración**—, que cede el hilo cada
  :data:`~design.road_net.NODES_PER_UNIT` (≈ 2.000) expansiones (≈ 25–30 ms: no se mira ``perf_counter`` por estado, cuesta más que el
  estado) y ``pace_progress`` agrupa en pasos de ``budget_s`` como mucho. Cerrar el generador a mitad no deja nada: solo guarda listas locales.

**Ninguna cifra de volumen ni de longitud de la pista sale de aquí** (RF-017-09): el coste es una cifra de búsqueda; las de la pista
salen de su eje y de la rejilla del proyecto. La ruta son nodos de la malla (el eje, T10, los simplifica y los redondea con curvas y
usa el punto exacto del origen y del destino).

**Perezoso** (RNF-001-03): ni ``design.model`` ni nada del arranque lo importan; lo pide quien traza una pista.
"""

from __future__ import annotations

import heapq
import math
from array import array
from collections.abc import Generator, Iterator
from dataclasses import dataclass

import numpy as np

from ..core.project.model import Progress
from .road_model import LevelDestination, NoRouteCause, RoadJob, RoadMode
from .road_net import (
    HEADINGS,
    NODES_PER_UNIT,
    STEP_BUDGET_S,
    STEP_UNITS,
    Corridor,
    RouteMesh,
    _finite,
    _readonly,
    _shifted,
    step_masks,
)
from .seeds import pace_progress

__all__ = [
    "COST_SCALE",
    "Route",
    "route_steps",
]

COST_SCALE = 1_000_000_000
"""Las unidades de coste por metro: el coste del paso es un entero en nanómetros (cada paso se redondea una vez: ≤ 0,5 nm de error por
paso, 10⁻¹⁰ relativo en una ruta de 100 pasos), para que los empates de D-23 sean exactos."""

_TURN_BITS = 24
"""Los bits de los giros en el coste empaquetado (hasta 16 millones de giros en una ruta)."""
_SLOPE_TOLERANCE_M = 1e-9
"""El margen (m) con que se compara ``|Δcota| ≤ pd·L``: el mismo que el de ``road_net.step_masks``."""
_LEVEL_TOLERANCE = 1e-9
"""El margen (en niveles) con que ``H/Δz`` da el número de niveles ``M``: ``14/0,28`` es 49,999… o 50,000… según el último bit."""
_HEURISTIC_SHRINK = 1e-8
"""La parte (relativa; mayor si la malla es menor de 1 m) en que se reduce la cota admisible al pasarla a enteros: el redondeo de
un paso (±0,5 unidades) y del suelo de la cota cabe en ella, de modo que la cota entera sigue siendo **consistente** y ningún estado
expandido vuelve a mejorar (la ruta se reconstruye por lo que cada estado guarda de dónde vino)."""
_SHARDS = 16
"""En cuántos diccionarios se reparten las etiquetas de los estados vistos. Un solo diccionario de 6 M entradas **se redimensiona de una
vez** (130 a 230 ms en una sola inserción) y, **al acabar, liberar** sus 12 M de enteros y los 5 M de la cola cuesta 250 a 300 ms **en una
sola llamada**: más que los 0,2 s de RNF-017-06 (medido en el peor caso del plan §7.3). Repartidas, cada redimensionado y cada liberación
son de una parte y se hacen en pasos aparte (la llamada más larga medida pasa de 250–320 a 90–110 ms); también baja el pico de memoria (965 frente a
1.094 MiB). Cuesta ≈ 20 % de tiempo. Una potencia
de 2: el reparto es ``(nodo · niveles + nivel) & (_SHARDS − 1)``."""
_SHARD_MASK = _SHARDS - 1
_RELEASE_CHUNK = 500_000
"""Las entradas de la cola que se liberan por unidad al acabar (≈ 15 ms)."""
_PHASE = "road_route"
_RUNNING = "Buscando la ruta 3D de la pista…"
_FINISHED = "Ruta 3D de la pista lista"


@dataclass(frozen=True, slots=True, eq=False)
class Route:
    """El resultado de la búsqueda (A2; RF-017-10, RF-017-12): ``ok`` (si hay ruta) y, si no, su ``cause``
    (:class:`~design.road_model.NoRouteCause`: ``NETWORK``, ``CORRIDOR`` o ``BUDGET``; ``None`` si hay ruta). Con ruta, los ``nodes`` ``(i, j)``
    de la malla del origen al destino (el origen incluido), el ``headings`` con que se llega a cada uno (el índice de
    :data:`~design.road_net.HEADINGS`; el del primero es el de partida, que es libre), las ``levels_m`` (cota de cada nodo, m: el terreno
    de la malla más el nivel por el paso de cota, float64), sus ``centers`` (absolutos, float64 ``(k, 2)``: los de la malla) y el coste de
    la búsqueda (``cost_units`` en :data:`COST_SCALE` unidades por metro, un entero; ``cost`` en esas unidades dividido por :data:`COST_SCALE`)
    y los ``turns`` (rumbos cambiados). Sin ruta, todo eso está vacío (``cost`` y ``cost_units``, ``None``). Siempre: los estados
    ``expanded`` y ``seen`` (los que llegaron a tener coste), el ``budget`` de estados expandidos con que se buscó y la ``mesh``. Los arrays son
    de solo lectura.

    **El coste es una cifra de búsqueda, no una longitud** (RF-017-09): ninguna cifra de volumen ni de longitud de la pista sale de aquí."""

    ok: bool
    cause: NoRouteCause | None
    nodes: tuple[tuple[int, int], ...]
    headings: tuple[int, ...]
    levels_m: np.ndarray
    centers: np.ndarray
    cost: float | None
    cost_units: int | None
    turns: int
    expanded: int
    seen: int
    budget: int
    mesh: RouteMesh


def _levels_toward(wanted: float | None, terrain: float, step_m: float) -> int:
    """El nivel (múltiplo del paso de cota sobre el terreno del nodo) más próximo a la cota ``wanted``; ``None`` es el terreno."""
    if wanted is None:
        return 0
    return math.floor((wanted - terrain) / step_m + 0.5)


def _check(job: object, corridor: object) -> tuple[RoadJob, Corridor]:
    """Las entradas de :func:`route_steps` (errores del programa): el trabajo de una pista en el modo «trazar» y el pasillo de la misma
    malla, la misma pendiente de diseño y la misma altura máxima que la ruta (con otras la red 2D no es cota de esta búsqueda)."""
    if not isinstance(job, RoadJob):
        raise TypeError(f"el trabajo de una pista es RoadJob, no {job!r}")
    if not isinstance(corridor, Corridor):
        raise TypeError(f"el pasillo es Corridor, no {corridor!r}")
    if job.route is None or job.mode is not RoadMode.TRACE:
        raise ValueError(f"la ruta 3D es del modo «trazar» y lleva los parámetros de la ruta (RF-017-10), no el modo «{job.mode.value}»")
    mesh, params = corridor.mesh, job.route
    if mesh.grid != job.grid:
        raise ValueError("la malla del pasillo no es la de la rejilla del trabajo")
    if not math.isclose(mesh.mesh_m, params.mesh_m, rel_tol=1e-9, abs_tol=0.0):
        raise ValueError(f"la malla del pasillo ({mesh.mesh_m:g} m) no es la de la ruta ({params.mesh_m:g} m)")
    pd = job.profile.max_gradient_pct / 100.0
    for net in (corridor.net_origin, corridor.net_dest):
        if not (math.isclose(net.pd, pd, rel_tol=1e-12, abs_tol=0.0)
                and math.isclose(net.hmax, params.max_cut_fill_m, rel_tol=1e-12, abs_tol=0.0)):
            raise ValueError(f"la red 2D se calculó con pd = {net.pd:g} y H = {net.hmax:g} m y la ruta pide pd = {pd:g} y "
                             f"H = {params.max_cut_fill_m:g} m: no es cota admisible de esta búsqueda")
    return job, corridor


def route_steps(job: RoadJob, corridor: Corridor, *, budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """Los pasos de la ruta 3D de ``job`` dentro de ``corridor`` (A2; RF-017-10, RF-017-11, RF-017-06, D-23; RNF-017-02 y 06): el A\\* de este
    módulo, por pasos de ``budget_s`` como mucho (``STEP_BUDGET_S``, 0,05 s) con su progreso; el último ``Progress`` lleva la :class:`Route`
    (``pipeline.forward`` la extrae). ``corridor`` es el de :func:`~design.road_net.corridor`: de las dos redes 2D con la ``pd`` del perfil
    (en tanto por uno) y la altura máxima de la ruta; su origen (``net_origin.sources``) es el de la búsqueda y su destino
    (``net_dest.sources``, un nodo o un conjunto), el de la llegada. El origen arranca en el nivel de ``job.start_level_m`` y el destino
    acaba en el de ``job.end_level_m`` (o el de la cota pedida de un :class:`~design.road_model.LevelDestination`; ``None``: la del
    terreno): el nivel más próximo; una cota fuera de la altura máxima no da estado y la ruta sale sin estados expandidos (``CORRIDOR``).
    Las entradas se comprueban **al llamar** (``ValueError`` o ``TypeError``). Cerrar el generador a mitad no deja nada: no escribe en
    ninguna parte."""
    job, corridor = _check(job, corridor)
    budget = _finite(budget_s, "el presupuesto de un paso (s)", strict=True)
    work = _search_units(job, corridor)
    return pace_progress(work, budget, phase=_PHASE, running=_RUNNING, finished=_FINISHED)


def _search_units(job: RoadJob, corridor: Corridor) -> Generator[None, None, Route]:
    """Las unidades de :func:`route_steps`: el A\\*, que cede el hilo cada :data:`~design.road_net.NODES_PER_UNIT` expansiones."""
    params = job.route
    assert params is not None
    mesh = corridor.mesh
    rows, cols = mesh.shape
    pd = job.profile.max_gradient_pct / 100.0
    step_m, height, budget = params.level_step_m, params.max_cut_fill_m, params.search_budget
    top = math.floor(height / step_m + _LEVEL_TOLERANCE)  # M: los niveles son −M..M
    span = 2 * top
    slots = 2 * top + 1  # los niveles de un nodo
    empty_levels, empty_centers = _readonly(np.empty(0)), _readonly(np.empty((0, 2)))

    def failed(cause: NoRouteCause, expanded: int = 0, seen: int = 0) -> Route:
        return Route(False, cause, (), (), empty_levels, empty_centers, None, None, 0, expanded, seen, budget, mesh)

    if not corridor.reachable:
        return failed(NoRouteCause.NETWORK)
    terrain = mesh.z.ravel()
    starts = []
    for node in corridor.net_origin.sources.tolist():
        level = _levels_toward(job.start_level_m, float(terrain[node]), step_m)
        if -top <= level <= top:
            starts.append((node, level))
    goal: dict[int, int] = {}
    destination = job.geometry.destination
    wanted = destination.level_m if isinstance(destination, LevelDestination) else job.end_level_m
    for node in corridor.net_dest.sources.tolist():
        level = _levels_toward(wanted, float(terrain[node]), step_m)
        if -top <= level <= top:
            goal[node] = level
    if not starts or not goal:  # una cota fuera de la altura máxima: no hay estado donde arrancar o acabar
        return failed(NoRouteCause.CORRIDOR)
    yield

    # --- Lo que se calcula una vez, con numpy: pasos permitidos, tablas de saltos de nivel, costes y cota admisible ----------------
    jump_bits = (2 * span).bit_length()
    pcode_bits = jump_bits + 5  # (rumbo anterior + 1, salto de nivel): 0 es «no viene de ningún sitio»
    shift = _TURN_BITS + pcode_bits  # el coste empaquetado: ((coste << giros) | giros) << pcode_bits | pcode
    masks = step_masks(mesh, pd, height)
    inside, ground = corridor.mask, mesh.z
    table: list[tuple[bytes, array, array, int, list[int], list[float]]] = []
    for heading, (dx, dy) in enumerate(HEADINGS):
        length = mesh.mesh_m * STEP_UNITS[heading]
        allowed = masks[heading] & inside & _shifted(inside, -dy, dx, False)
        drop = _shifted(ground, -dy, dx, np.nan) - ground
        with np.errstate(invalid="ignore"):
            lowest = np.ceil((-pd * length - _SLOPE_TOLERANCE_M - drop) / step_m)
            highest = np.floor((pd * length + _SLOPE_TOLERANCE_M - drop) / step_m)
        lowest = np.where(allowed, np.clip(lowest, -span, span), 1.0).astype(np.int32)
        highest = np.where(allowed, np.clip(highest, -span, span), 0.0).astype(np.int32)
        floats = [COST_SCALE * length * (1.0 + params.lambda_per_m * step_m * both * 0.5) for both in range(span + 1)]
        table.append((np.ascontiguousarray(allowed, dtype=np.uint8).tobytes(), array("i", lowest.tobytes()),
                      array("i", highest.tobytes()), -dy * cols + dx, [int(value + 0.5) << shift for value in floats], floats))
    yield
    shrink = _HEURISTIC_SHRINK * max(1.0, 1.0 / mesh.mesh_m)
    remaining = corridor.net_dest.dist
    ahead = np.where(inside & np.isfinite(remaining), np.floor(np.where(np.isfinite(remaining), remaining, 0.0)
                                                              * (COST_SCALE * (1.0 - shrink))), 0.0).astype(np.int64)
    ahead_shifted = [value << _TURN_BITS for value in ahead.ravel().tolist()]
    weights = None if mesh.weight is None else mesh.weight.ravel().tolist()
    turn_step = (int(params.turn_m * COST_SCALE + 0.5) << shift) + (1 << pcode_bits)
    state_bits = (rows * cols * slots * 16).bit_length()
    state_mask = (1 << state_bits) - 1
    key_shift = state_bits + 4
    yield

    # --- El A* ------------------------------------------------------------------------------------------------------------------
    shards: tuple[dict[int, int], ...] = tuple({} for _ in range(_SHARDS))  # las etiquetas, repartidas por (nodo, nivel)
    heap: list[int] = []
    for node, level in starts:
        first = (node * slots + level + top) << 4
        for heading in range(16):
            state = first | heading
            shards[(state >> 4) & _SHARD_MASK][state] = 0
            heap.append((((ahead_shifted[node] << 4) | heading) << state_bits) | state)
    heapq.heapify(heap)
    pop, push, goal_get = heapq.heappop, heapq.heappush, goal.get
    expanded, unit, found, cause = 0, NODES_PER_UNIT, -1, None
    while heap:
        key = pop(heap)
        state = key & state_mask
        tail = state >> 4
        node, slot = divmod(tail, slots)
        packed = (key >> key_shift) - ahead_shifted[node]  # (coste << giros) | giros
        if shards[tail & _SHARD_MASK][state] >> pcode_bits != packed:
            continue  # una entrada vieja: el estado se mejoró después
        level = slot - top
        if goal_get(node) == level:
            found = state
            break
        if expanded >= budget:
            cause = NoRouteCause.BUDGET
            break
        expanded += 1
        heading = state & 15
        base = packed << pcode_bits
        from_code = ((heading + 1) << jump_bits) + span
        level_abs = level if level >= 0 else -level
        for other in ((heading - 1) & 15, heading, (heading + 1) & 15):
            allow, lows, highs, offset, costs, floats = table[other]
            if not allow[node]:
                continue
            low = lows[node]
            if low < -top - level:
                low = -top - level
            high = highs[node]
            if high > top - level:
                high = top - level
            if low > high:
                continue
            target = node + offset
            labeled = base if other == heading else base + turn_step
            tail_0 = target * slots + top  # el estado del nivel 0 del destino, sin el rumbo
            first = (tail_0 << 4) | other
            beyond = ahead_shifted[target]
            mean = None if weights is None else (weights[node] + weights[target]) * 0.5
            for jump in range(low, high + 1):
                new_level = level + jump
                both = level_abs + (new_level if new_level >= 0 else -new_level)
                new = labeled + from_code + jump + (costs[both] if mean is None else int(floats[both] * mean + 0.5) << shift)
                state_2 = first + (new_level << 4)
                bucket = shards[(tail_0 + new_level) & _SHARD_MASK]
                old = bucket.get(state_2)
                if old is None:
                    bucket[state_2] = new
                    push(heap, (((((new >> pcode_bits) + beyond) << 4) | other) << state_bits) | state_2)
                elif new < old:
                    bucket[state_2] = new
                    if (new >> pcode_bits) != (old >> pcode_bits):
                        push(heap, (((((new >> pcode_bits) + beyond) << 4) | other) << state_bits) | state_2)
        unit -= 1
        if not unit:
            unit = NODES_PER_UNIT
            yield
    seen = sum(map(len, shards))
    result = None if found >= 0 else failed(cause or NoRouteCause.CORRIDOR, expanded, seen)
    if result is None:
        result = _route_found(found, shards, table, (top, slots, span, jump_bits, pcode_bits), terrain, step_m, mesh, expanded, seen,
                              budget)
    # --- Liberar lo que se vio, **por partes** (cada una, en su unidad: liberarlo todo de una vez cuesta 250 ms) ---------------------
    for bucket in shards:
        bucket.clear()
        yield
    while heap:
        del heap[-_RELEASE_CHUNK:]
        yield
    return result


def _route_found(found: int, shards: tuple[dict[int, int], ...], table: list[tuple[bytes, array, array, int, list[int], list[float]]],
                 layout: tuple[int, int, int, int, int], terrain: np.ndarray, step_m: float, mesh: RouteMesh, expanded: int, seen: int,
                 budget: int) -> Route:
    """La ruta que acaba en el estado ``found``: de cada estado, de dónde vino (el rumbo anterior y el salto de nivel que lleva empaquetados).
    ``layout`` es ``(M, niveles por nodo, 2·M, bits del salto, bits de lo que lleva de dónde vino)``."""
    top, slots, span, jump_bits, pcode_bits = layout
    cols = mesh.shape[1]
    jump_mask = (1 << jump_bits) - 1
    pcode_mask = (1 << pcode_bits) - 1
    shift = _TURN_BITS + pcode_bits
    turn_mask = (1 << _TURN_BITS) - 1
    chain: list[tuple[int, int, int]] = []
    state = found
    while True:
        node, slot = divmod(state >> 4, slots)
        heading = state & 15
        chain.append((node, slot - top, heading))
        code = shards[(state >> 4) & _SHARD_MASK][state] & pcode_mask
        if not code:
            break
        previous = node - table[heading][3]
        state = (((previous * slots) + slot - ((code & jump_mask) - span)) << 4) | ((code >> jump_bits) - 1)
    chain.reverse()
    ids = np.array([item[0] for item in chain], dtype=np.int64)
    in_rows, in_cols = np.divmod(ids, cols)
    levels_m = terrain[ids] + np.array([item[1] for item in chain], dtype=np.int64) * step_m
    side, grid = mesh.mesh_m, mesh.grid
    centers = np.column_stack((grid.west + (in_cols + 0.5) * side, grid.north - (in_rows + 0.5) * side))
    final = shards[(found >> 4) & _SHARD_MASK][found]
    units = final >> shift
    return Route(True, None, tuple(zip(in_rows.tolist(), in_cols.tolist(), strict=True)),
                 tuple(item[2] for item in chain), _readonly(levels_m), _readonly(centers), units / COST_SCALE, units,
                 (final >> pcode_bits) & turn_mask, expanded, seen, budget, mesh)

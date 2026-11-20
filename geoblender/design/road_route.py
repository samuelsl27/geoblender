# SPDX-License-Identifier: GPL-3.0-or-later
"""La ruta 3D de mínimo coste de una pista, sin ruta y el destino por cota (spec 017, T07 y T08; HU-017-1; RF-017-10, 11, 06, 12, 02 y 04;
RF-015-02; RNF-017-02, 06 y 07; plan 017 §5.4 A2 y A3, §5.7 P-3, P-7 y P-13, §5.8 H-1, §6, §7.3, §8 y §9; D-4, D-23).

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
  :attr:`~design.road_model.NoRouteCause.CORRIDOR` y una red 2D que no alcanza el origen, :attr:`~design.road_model.NoRouteCause.NETWORK`.
- **Sin ruta** (:func:`no_route` → :class:`NoRoute`; A3, RF-017-12, T08): **por qué** no hay ruta, sin registrar nada ni relajar un límite
  (B2). En la red 2D que no llega al origen y en el pasillo agotado: la cota a que llega la ruta **desde el origen** (la mayor si el destino
  está más alto; la menor si más bajo) y **desde el destino** (la otra), la **pendiente mínima necesaria** (el desnivel entre los extremos
  dividido por la longitud de la ruta más corta de la red 2D, %; **sin ruta en la red 2D no hay una más corta: se usa la distancia en línea
  recta entre los nodos**, que es la de cualquier ruta como mínimo) y el **tramo limitante** (:class:`LimitingStretch`): el nodo de lo
  alcanzado más próximo al otro extremo y la causa, leída de su primer paso inadmisible en la dirección del otro extremo (:func:`step_reason`:
  una zona que las máscaras prohíben, el borde de la rejilla, celdas sin dato, la altura máxima de desmonte y terraplén o, con altura 0, la
  pendiente). Con el pasillo agotado las cifras del origen salen de **los estados vistos** (``Route.high_m`` y ``low_m``). Si la búsqueda
  **agotó su presupuesto**, una tercera causa distinta (``des.road_budget``): los estados explorados y que reducir la holgura o subir el
  presupuesto puede dar una ruta; no se dice que no la haya.
- **El destino por cota** (la rampa, D-4; :func:`route_target` y :func:`arrival_of`): el conjunto de nodos de la zona (el centro del nodo dentro
  del polígono) que se pisan y cuya cota de partida difiere de la pedida en **menos de la tolerancia de llegada del destino** (``dest_tol_m``,
  ``LevelDestination.tolerance_m``); una cota que ningún nodo de la zona alcanza se rechaza (RF-017-04). ``arrival_tol_m`` (``RouteParams``)
  es otra: la de **la cota a que llega la ruta** frente a la pedida (el nivel de llegada es el más próximo: a menos de medio paso de cota), que
  :func:`arrival_of` compara con ella y **dice, sin corregir**.
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
from ..gis.grid import Grid
from .messages import DesignError
from .params import RoadParam, entity_key
from .road_model import LevelDestination, LimitCause, NoRouteCause, RoadJob, RoadMode
from .road_net import (
    _INTERMEDIATES,
    _STEP_TOLERANCE_M,
    HEADINGS,
    NODES_PER_UNIT,
    STEP_BUDGET_S,
    STEP_UNITS,
    Corridor,
    Network,
    RouteMesh,
    _finite,
    _readonly,
    _shifted,
    step_masks,
)
from .seeds import pace_progress
from .zones import polygons_cells

__all__ = [
    "COST_SCALE",
    "Arrival",
    "LimitingStretch",
    "NoRoute",
    "Route",
    "arrival_of",
    "no_route",
    "node_reason",
    "route_steps",
    "route_target",
    "step_reason",
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

    Con el **pasillo agotado** (``cause`` ``CORRIDOR`` y se buscó), ``high_m`` y ``low_m`` (T08, A3): por nodo de la malla, la cota mayor y
    la menor (m, float64) de **los estados vistos** (``NaN`` donde no llegó ninguno; la forma de la malla; de solo lectura). Con ruta, con la
    red 2D que no alcanza el origen o con el presupuesto agotado son ``None``: no se calculan (el presupuesto no las necesita y pagaría una
    pasada sobre millones de estados).

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
    high_m: np.ndarray | None = None
    low_m: np.ndarray | None = None


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
    _check_networks(job, corridor.net_origin, corridor.net_dest, "pasillo")
    return job, corridor


def _check_networks(job: object, net_origin: object, net_dest: object, what: str = "red 2D") -> tuple[RoadJob, Network, Network]:
    """Las entradas de :func:`no_route` y de :func:`_check` (errores del programa): el trabajo de una pista en el modo «trazar» y las dos redes 2D
    de su malla, con la pendiente de diseño y la altura máxima de su ruta (con otras no son lo que explica el diagnóstico ni cota de la
    búsqueda). ``what`` es lo que se nombra en el error de la malla."""
    if not isinstance(job, RoadJob):
        raise TypeError(f"el trabajo de una pista es RoadJob, no {job!r}")
    if not isinstance(net_origin, Network) or not isinstance(net_dest, Network):
        raise TypeError("las redes 2D de una pista son dos Network: la del origen y la del destino")
    if job.route is None or job.mode is not RoadMode.TRACE:
        raise ValueError(f"la ruta 3D es del modo «trazar» y lleva los parámetros de la ruta (RF-017-10), no el modo «{job.mode.value}»")
    if net_origin.mesh is not net_dest.mesh:
        raise ValueError("las redes 2D del origen y del destino son de la misma malla")
    mesh, params = net_origin.mesh, job.route
    if mesh.grid != job.grid:
        raise ValueError(f"la malla del {what} no es la de la rejilla del trabajo")
    if not math.isclose(mesh.mesh_m, params.mesh_m, rel_tol=1e-9, abs_tol=0.0):
        raise ValueError(f"la malla del {what} ({mesh.mesh_m:g} m) no es la de la ruta ({params.mesh_m:g} m)")
    pd = job.profile.max_gradient_pct / 100.0
    for net in (net_origin, net_dest):
        if not (math.isclose(net.pd, pd, rel_tol=1e-12, abs_tol=0.0)
                and math.isclose(net.hmax, params.max_cut_fill_m, rel_tol=1e-12, abs_tol=0.0)):
            raise ValueError(f"la red 2D se calculó con pd = {net.pd:g} y H = {net.hmax:g} m y la ruta pide pd = {pd:g} y "
                             f"H = {params.max_cut_fill_m:g} m: no es cota admisible de esta búsqueda")
    return job, net_origin, net_dest


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

    def failed(cause: NoRouteCause, expanded: int = 0, seen: int = 0, high_m: np.ndarray | None = None,
               low_m: np.ndarray | None = None) -> Route:
        return Route(False, cause, (), (), empty_levels, empty_centers, None, None, 0, expanded, seen, budget, mesh, high_m, low_m)

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
    high_m = low_m = None
    if found < 0 and cause is None:
        # El pasillo agotado (A3): la cota mayor y la menor de los estados vistos por nodo, **antes de liberarlos**; una unidad por diccionario
        # (una pasada de numpy sobre sus claves, ≈ 25 ms cada una con ≈ 400.000 estados: dentro de los 0,2 s de RNF-017-06).
        high = np.full(rows * cols, -1, dtype=np.int64)
        low = np.full(rows * cols, slots, dtype=np.int64)
        for bucket in shards:
            node_ids, level_slots = np.divmod(np.fromiter(bucket, dtype=np.int64, count=len(bucket)) >> 4, slots)
            np.maximum.at(high, node_ids, level_slots)
            np.minimum.at(low, node_ids, level_slots)
            yield
        visited = high >= 0
        high_m = _readonly(np.where(visited, terrain + (high - top) * step_m, np.nan).reshape(mesh.shape))
        low_m = _readonly(np.where(visited, terrain + (low - top) * step_m, np.nan).reshape(mesh.shape))
    result = None if found >= 0 else failed(cause or NoRouteCause.CORRIDOR, expanded, seen, high_m, low_m)
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


# --- El destino por cota (la rampa, D-4) -------------------------------------------------------------------------------------------


def _check_target(job: object, mesh: object) -> tuple[RoadJob, RouteMesh]:
    if not isinstance(job, RoadJob):
        raise TypeError(f"el trabajo de una pista es RoadJob, no {job!r}")
    if not isinstance(mesh, RouteMesh):
        raise TypeError(f"la malla es RouteMesh, no {mesh!r}")
    if job.route is None or job.mode is not RoadMode.TRACE or job.geometry.destination is None:
        raise ValueError(f"el destino de la ruta es del modo «trazar» (RF-017-02), no del modo «{job.mode.value}»")
    return job, mesh


def route_target(job: RoadJob, mesh: RouteMesh) -> tuple[int, int] | np.ndarray:
    """El destino de la red 2D y de la ruta de ``job`` en ``mesh`` (A1, A2, D-4; RF-017-02 y RF-017-10), lo que se pasa a
    :func:`~design.road_net.network_steps`: el nodo ``(i, j)`` que contiene el punto de destino o, con un **destino por cota**
    (:class:`~design.road_model.LevelDestination`: la rampa), la **máscara de los nodos** de la zona (el centro del nodo dentro del polígono,
    como las celdas de una zona en la 013: D-16) que se pisan y **cuya cota de partida** (la media de su bloque: P-6) **difiere de la pedida en
    menos de la tolerancia de llegada del destino** (``dest_tol_m``). La ruta termina en el primero de ellos que alcanza (:func:`route_steps`) y
    :func:`arrival_of` da cuál.

    Una cota que ningún nodo de la zona alcanza (la pedida queda fuera de las cotas del terreno de la zona, con la tolerancia) es un rechazo de
    la persona, ``des.road_dest_level_out_of_zone`` (RF-017-04), con las cotas del terreno dentro de la zona: no se elige otra por ella. Una zona
    sin ningún nodo que se pise (fuera de la rejilla, sin dato o en un intocable) es un error del programa (``ValueError``): la preparación de la
    pista (T19) la rechaza antes con la capa, la pista y el campo, y el catálogo de mensajes no tiene un código para ella."""
    job, mesh = _check_target(job, mesh)
    destination = job.geometry.destination
    if not isinstance(destination, LevelDestination):
        return mesh.node_of(*destination)  # type: ignore[misc]
    rows, cols = mesh.shape
    nodes = Grid(west=mesh.grid.west, north=mesh.grid.north, dx=mesh.mesh_m, dy=mesh.mesh_m, ncols=cols, nrows=rows)
    candidates = polygons_cells(destination.zone, nodes) & mesh.walkable
    if not bool(candidates.any()):
        raise ValueError("la zona del destino por cota no contiene ningún nodo de la malla que se pise (fuera de la rejilla, sin dato o en "
                         "una zona prohibida): la preparación de la pista la rechaza antes (RF-017-04)")
    with np.errstate(invalid="ignore"):
        close = candidates & (np.abs(mesh.z - destination.level_m) < destination.tolerance_m)
    if not bool(close.any()):
        request = job.request
        raise DesignError("des.road_dest_level_out_of_zone", obj=f"Pista «{request.name}» de la capa «{request.layer}»",
                          field=entity_key(job.code, RoadParam.DEST_LEVEL.value), value=destination.level_m, layer=request.layer,
                          entity=request.name, zone=request.dest_zone, low=round(float(mesh.z[candidates].min()), 3),
                          high=round(float(mesh.z[candidates].max()), 3))
    return close


@dataclass(frozen=True, slots=True)
class Arrival:
    """El destino alcanzado de una ruta (RF-017-02, RF-017-10, D-4): el ``node`` ``(i, j)`` en que termina, su lugar (``x`` e ``y``: el centro
    del nodo, absoluto, float64), la cota (``level_m``, m) a que llega la ruta y la de partida del nodo (``terrain_m``), la cota pedida
    (``requested_m``: la del destino por cota o la cota de fin; ``None`` si no se pidió ninguna), su diferencia con la de llegada
    (``difference_m``) y si cabe en la tolerancia de llegada de la ruta (``within_tolerance``: ``|diferencia| ≤ arrival_tol_m``; ``None`` sin
    cota pedida). **Se dice y no se corrige**: la ruta llega al nivel más próximo a la cota pedida (a menos de medio paso de cota) y la
    tolerancia no cambia la búsqueda."""

    node: tuple[int, int]
    x: float
    y: float
    level_m: float
    terrain_m: float
    requested_m: float | None
    difference_m: float | None
    within_tolerance: bool | None


def arrival_of(job: RoadJob, route: Route) -> Arrival:
    """El destino alcanzado por ``route`` (RF-017-02, D-4): su último nodo, su lugar y la cota a que llega con su diferencia con la pedida
    (:class:`Arrival`). ``ValueError`` si la ruta no existe (``route.ok`` falso); ``TypeError`` si no son de su tipo."""
    if not isinstance(job, RoadJob):
        raise TypeError(f"el trabajo de una pista es RoadJob, no {job!r}")
    if not isinstance(route, Route):
        raise TypeError(f"la ruta es Route, no {route!r}")
    if not route.ok or job.route is None:
        raise ValueError("una ruta que no existe no llega a ningún destino: se explica con no_route (RF-017-12)")
    node = route.nodes[-1]
    destination = job.geometry.destination
    requested = destination.level_m if isinstance(destination, LevelDestination) else job.end_level_m
    level = float(route.levels_m[-1])
    x, y = route.mesh.center_of(*node)
    difference = None if requested is None else level - requested
    within = None if difference is None else abs(difference) <= job.route.arrival_tol_m + _SLOPE_TOLERANCE_M
    return Arrival(node, x, y, level, float(route.mesh.z[node]), requested, difference, within)


# --- Sin ruta (A3; RF-017-12) ------------------------------------------------------------------------------------------------------

_BASIS_NETWORK = "network"
_BASIS_STRAIGHT = "straight"
_ERROR_FIELD = {NoRouteCause.NETWORK: RoadParam.MAX_CUT_FILL, NoRouteCause.CORRIDOR: RoadParam.MARGIN}
"""El parámetro que nombra el rechazo de cada causa (el campo del error): la altura máxima, con la que la red 2D admite más pasos, y la
holgura, con la que el pasillo contiene más rutas; la del presupuesto agotado, ``search_budget``."""


def node_reason(mesh: RouteMesh, i: int, j: int) -> LimitCause | None:
    """Por qué el nodo ``(i, j)`` de ``mesh`` no se pisa (A1, RF-017-12), o ``None`` si se pisa: **el borde de la rejilla** si el nodo no es
    de la malla o su bloque sale de la rejilla del proyecto (los bloques del sur y del este de una rejilla que no es múltiplo del paso), **celdas
    sin dato** si su cota no existe y **una zona que las máscaras prohíben** si es intocable o exclusión (en ese orden)."""
    rows, cols = mesh.shape
    if not (0 <= i < rows and 0 <= j < cols):
        return LimitCause.GRID_EDGE
    grid, factor = mesh.grid, mesh.k
    if (i + 1) * factor > grid.nrows or (j + 1) * factor > grid.ncols:
        return LimitCause.GRID_EDGE
    if not math.isfinite(float(mesh.z[i, j])):
        return LimitCause.NO_DATA
    if bool(mesh.forbidden[i, j]):
        return LimitCause.MASK
    return None


def step_reason(mesh: RouteMesh, i: int, j: int, heading: int, pd: float, hmax: float) -> LimitCause | None:
    """Por qué el paso del rumbo ``heading`` desde el nodo ``(i, j)`` (que se pisa) no es admisible en la red 2D (A1, RF-017-12), o ``None`` si
    lo es: la causa del primer nodo que no se pisa —el del extremo y, en los pasos «de caballo», los dos que la recta atraviesa: :func:`node_reason`—
    o, si todos se pisan, que el desnivel pase de ``pd·L + 2H`` (con ``pd`` en tanto por uno y ``hmax`` en m): **la altura máxima de desmonte
    y terraplén** si hay (el terreno no se puede seguir dentro de ella) o **la pendiente** si es 0 (la pista que sigue el terreno)."""
    dx, dy = HEADINGS[heading]
    for offset_x, offset_y in ((dx, dy), *_INTERMEDIATES[heading]):
        reason = node_reason(mesh, i - offset_y, j + offset_x)
        if reason is not None:
            return reason
    length = mesh.mesh_m * STEP_UNITS[heading]
    if abs(float(mesh.z[i - dy, j + dx]) - float(mesh.z[i, j])) > pd * length + 2.0 * hmax + _STEP_TOLERANCE_M:
        return LimitCause.HEIGHT if hmax > 0.0 else LimitCause.SLOPE
    return None


def _level_reason(mesh: RouteMesh, i: int, j: int, heading: int, high: float, low: float, pd: float, hmax: float) -> LimitCause | None:
    """Por qué desde un nodo al que la búsqueda llegó con cotas entre ``low`` y ``high`` no se sigue el paso del rumbo ``heading`` (a un nodo que
    se pisa): porque con la pendiente de diseño no se alcanza el nivel que el terreno del nodo siguiente deja (``z ± H``). Es la altura máxima si
    la hay y la pendiente si no; ``None`` si el paso cabe."""
    dx, dy = HEADINGS[heading]
    ahead = float(mesh.z[i - dy, j + dx])
    reach = pd * mesh.mesh_m * STEP_UNITS[heading] + _STEP_TOLERANCE_M
    if high + reach < ahead - hmax or low - reach > ahead + hmax:
        return LimitCause.HEIGHT if hmax > 0.0 else LimitCause.SLOPE
    return None


def _toward(i: int, j: int, target: tuple[int, int]) -> tuple[int, ...]:
    """Los 16 rumbos desde el nodo ``(i, j)`` del más próximo al más lejano de la dirección de ``target`` (el coseno del ángulo, y a igualdad
    el primero en sentido horario desde el norte: D-23)."""
    east, north = target[1] - j, i - target[0]
    norm = math.hypot(east, north)
    if norm == 0.0:
        return tuple(range(len(HEADINGS)))
    return tuple(sorted(range(len(HEADINGS)), key=lambda h: (-(HEADINGS[h][0] * east + HEADINGS[h][1] * north) / (STEP_UNITS[h] * norm), h)))


@dataclass(frozen=True, slots=True)
class LimitingStretch:
    """El tramo limitante de un «sin ruta» (RF-017-12): la ``cause`` (:class:`~design.road_model.LimitCause`), el ``node`` ``(i, j)`` de la malla
    de la frontera de lo alcanzable más próximo al otro extremo y su lugar (``x`` e ``y``: el centro del nodo, absoluto, float64) y el
    ``heading`` (el índice de :data:`~design.road_net.HEADINGS`) del primer paso inadmisible de que se lee la causa (``None`` si es el
    propio nodo —el origen o el destino que no se pisan— o la pendiente con que no se llega al nivel pedido)."""

    cause: LimitCause
    node: tuple[int, int]
    x: float
    y: float
    heading: int | None


@dataclass(frozen=True, slots=True)
class NoRoute:
    """Por qué no hay ruta (A3, RF-017-12): la ``cause`` (:class:`~design.road_model.NoRouteCause`; su valor es el código del rechazo) y la
    holgura del pasillo (``margin_m``). Con la red 2D que no llega al origen (``NETWORK``) y con el pasillo sin ruta 3D (``CORRIDOR``): las cotas
    pedidas del origen y del destino (``z_origin_m`` y ``z_destination_m``; las del terreno de su nodo si no se pidió ninguna: D-13) y si el
    destino está más alto (``rising``); **la cota a que llega la ruta desde el origen** (``reached_from_origin_m``: la mayor si ``rising``, la menor
    si no) **y desde el destino** (la otra); **la pendiente mínima necesaria** (``min_gradient_pct``, %: el desnivel entre los extremos
    dividido por ``length_m``, que es la longitud de la ruta más corta de la red 2D —``length_basis`` ``"network"``— o, si la red no une los
    extremos y no hay una más corta, la distancia en línea recta entre los nodos —``"straight"``—) y el **tramo limitante** (``limit``; ``None``
    si no se buscó o no hay a quien atribuirlo). Con el presupuesto agotado (``BUDGET``: **no** es «no hay ruta»), solo ``budget``, ``expanded``
    y ``seen`` (los estados explorados) y ``margin_m``: no se sabe si la hay.

    **No registra nada ni relaja ningún límite** (B2): es un resultado. :meth:`error` lo convierte en el rechazo del catálogo."""

    cause: NoRouteCause
    margin_m: float
    z_origin_m: float | None = None
    z_destination_m: float | None = None
    rising: bool | None = None
    reached_from_origin_m: float | None = None
    reached_from_destination_m: float | None = None
    length_m: float | None = None
    length_basis: str | None = None
    min_gradient_pct: float | None = None
    limit: LimitingStretch | None = None
    budget: int | None = None
    expanded: int | None = None
    seen: int | None = None

    def error(self, job: RoadJob) -> DesignError:
        """El rechazo de la persona (``des.road_no_route_network``, ``des.road_no_route_corridor`` o ``des.road_budget``: RF-017-12) con la
        capa, la pista, el campo y el valor: el de **la altura máxima de desmonte y terraplén** en la red 2D, **la holgura** en el pasillo y
        **el presupuesto** en la búsqueda agotada, las cifras y, detrás, la nota del tramo limitante con su lugar. Los textos, en español y en
        inglés, son los de :mod:`design.messages`."""
        if not isinstance(job, RoadJob) or job.route is None:
            raise TypeError(f"el trabajo de una pista en el modo «trazar» es RoadJob, no {job!r}")
        request = job.request
        obj = f"Pista «{request.name}» de la capa «{request.layer}»"
        shared = {"layer": request.layer, "entity": request.name}
        if self.cause is NoRouteCause.BUDGET:
            return DesignError(self.cause.value, obj=obj, field=entity_key(job.code, RoadParam.SEARCH_BUDGET.value), value=self.budget,
                               budget=self.budget, expanded=self.expanded, margin=_shown(self.margin_m), **shared)
        param = _ERROR_FIELD[self.cause]
        value = job.route.max_cut_fill_m if param is RoadParam.MAX_CUT_FILL else self.margin_m
        notes: list[tuple[str, dict[str, object]]] = []
        if self.limit is not None:
            note: dict[str, object] = {"x": _shown(self.limit.x), "y": _shown(self.limit.y)}
            if self.limit.cause is LimitCause.SLOPE:
                note["gradient"] = job.profile.max_gradient_pct
            elif self.limit.cause is LimitCause.HEIGHT:
                note["height"] = job.route.max_cut_fill_m
            notes.append((self.limit.cause.value, note))
        return DesignError(self.cause.value, obj=obj, field=entity_key(job.code, param.value), value=value,
                           z_origin=_shown(self.reached_from_origin_m), z_destination=_shown(self.reached_from_destination_m),
                           gradient=_shown(self.min_gradient_pct), notes=notes, **shared)


def _shown(value: float | None) -> float | None:
    """Una cifra del rechazo como la lee una persona: a milésimas (las de un lugar o una cota son de m)."""
    return None if value is None else round(float(value), 3)


def _reach_bound(net: Network, level: float | None, up: bool, mesh: RouteMesh, pd: float, hmax: float) -> float | None:
    """La cota a que llega la ruta desde los nodos de partida de ``net`` con ``level`` (m), **según la red 2D**: ``up`` (la mayor) o la menor.
    Con ``d`` la longitud mínima de la red a cada nodo alcanzado, no se sube (o baja) más de ``pd·d`` —cualquier ruta 3D es, como mínimo, la de
    la red— ni se pasa de ``z ± H`` del nodo; y un nodo al que no se llega a ``z ∓ H`` (el desmonte o el relleno pasaría de la altura máxima) no
    cuenta. Es una cota del alcance: la búsqueda 3D de un pasillo agotado da la exacta (``Route.high_m`` y ``low_m``). Sin nodos de partida
    que se pisen, o sin cota, la propia."""
    if level is None or not net.sources.size:
        return level
    distance, ground = net.dist, mesh.z
    with np.errstate(invalid="ignore"):
        if up:
            climb = level + pd * distance
            feasible = np.isfinite(distance) & (climb >= ground - hmax - _STEP_TOLERANCE_M)
            return float(np.minimum(climb, ground + hmax)[feasible].max()) if bool(feasible.any()) else level
        drop = level - pd * distance
        feasible = np.isfinite(distance) & (drop <= ground + hmax + _STEP_TOLERANCE_M)
        return float(np.maximum(drop, ground - hmax)[feasible].min()) if bool(feasible.any()) else level


def _node_limit(mesh: RouteMesh, node: tuple[int, int]) -> LimitingStretch | None:
    """El tramo limitante cuando es el propio nodo (el origen o el destino) el que no se pisa: su causa (:func:`node_reason`) y su lugar."""
    reason = node_reason(mesh, *node)
    if reason is None:
        return None
    x, y = mesh.center_of(*node)
    return LimitingStretch(reason, node, x, y, None)


def _frontier_limit(mesh: RouteMesh, reached: np.ndarray, pivot: tuple[int, int], targets: np.ndarray, pd: float, hmax: float,
                    route: Route | None) -> LimitingStretch | None:
    """El tramo limitante de lo alcanzado (``reached``: una máscara de la malla): **el nodo de lo alcanzado más próximo al otro extremo**
    (``pivot``: el nodo del destino más próximo al origen; a igual distancia, el primero por fila y columna) y la causa del **primer paso
    inadmisible** de ese nodo **en la dirección del otro extremo** (:func:`_toward`): :func:`step_reason` en la red 2D y, con la búsqueda 3D de
    un pasillo agotado (``route``), también el paso que no se sigue por **el nivel** (:func:`_level_reason`) hacia un nodo que no se vio. Si la
    búsqueda llegó a un nodo del destino pero no a su cota, el tramo es ese nodo y su causa la pendiente (con la que no se llega al nivel
    pedido); si ningún paso lo explica, también la pendiente (lo que se alcanza en el pasillo no da para el desnivel)."""
    cols = mesh.shape[1]
    flat = np.flatnonzero(reached.ravel())
    if not flat.size:
        return None
    if route is not None:
        arrived = flat[np.isin(flat, targets)]
        if arrived.size:
            i, j = divmod(int(arrived[0]), cols)
            x, y = mesh.center_of(i, j)
            return LimitingStretch(LimitCause.SLOPE, (i, j), x, y, None)
    rows_of, cols_of = np.divmod(flat, cols)
    near = int(flat[int(np.argmin((rows_of - pivot[0]) ** 2 + (cols_of - pivot[1]) ** 2))])
    i, j = divmod(near, cols)
    x, y = mesh.center_of(i, j)
    for heading in _toward(i, j, pivot):
        reason = step_reason(mesh, i, j, heading, pd, hmax)
        if reason is None:  # un paso admisible entra en lo alcanzado, o solo lo limita el nivel
            dx, dy = HEADINGS[heading]
            if route is None or reached[i - dy, j + dx]:
                continue
            reason = _level_reason(mesh, i, j, heading, float(route.high_m[i, j]), float(route.low_m[i, j]), pd, hmax)  # type: ignore[index]
        if reason is not None:
            return LimitingStretch(reason, (i, j), x, y, heading)
    return LimitingStretch(LimitCause.SLOPE, (i, j), x, y, None)


def no_route(job: RoadJob, net_origin: Network, net_dest: Network, route: Route | None = None) -> NoRoute:
    """Por qué no hay ruta (A3, RF-017-12; plan §5.3.1): el diagnóstico de ``job`` con las redes 2D desde su origen (``net_origin``) y desde su
    destino (``net_dest``: un nodo o, con un destino por cota, el conjunto de :func:`route_target`), y la ``route`` de :func:`route_steps` si se
    buscó (con ella se distingue el presupuesto agotado y se leen las cotas de los estados vistos). Da una :class:`NoRoute`; **no registra
    nada ni relaja un límite** (B2: solo lee).

    - **El presupuesto agotado** (``route.cause`` ``BUDGET``): solo los estados explorados, el presupuesto y la holgura. No se sabe si hay ruta.
    - **La red 2D no une el origen con el destino** (``NETWORK``): la cota a que llega la ruta desde el origen y desde el destino, la pendiente
      mínima con la distancia en línea recta entre los nodos y el tramo limitante de lo alcanzado desde el origen; si es el propio origen o
      destino el que no se pisa (el borde de la rejilla, celdas sin dato o una zona prohibida), ese nodo.
    - **El pasillo no contiene ninguna ruta 3D** (``CORRIDOR``): lo mismo, con la longitud de la ruta más corta de la red 2D y, con la
      ``route``, las cotas y el tramo sobre los estados vistos.

    Las cotas son las pedidas (``start_level_m``, ``end_level_m`` o la del destino por cota; si no, la del terreno de su nodo). ``ValueError`` si la
    ruta existe (``route.ok``) o las entradas no son de un mismo trabajo (otra malla, otra pendiente o altura); ``TypeError`` si no son de su tipo."""
    job, net_origin, net_dest = _check_networks(job, net_origin, net_dest)
    if route is not None:
        if not isinstance(route, Route):
            raise TypeError(f"la ruta es Route, no {route!r}")
        if route.ok:
            raise ValueError("hay ruta: no hay nada que explicar (RF-017-12)")
        if route.mesh is not net_origin.mesh:
            raise ValueError("la ruta es de otra malla que las redes 2D")
    params = job.route
    assert params is not None
    mesh = net_origin.mesh
    if route is not None and route.cause is NoRouteCause.BUDGET:
        return NoRoute(NoRouteCause.BUDGET, params.margin_m, budget=route.budget, expanded=route.expanded, seen=route.seen)
    cols = mesh.shape[1]
    pd, hmax = job.profile.max_gradient_pct / 100.0, params.max_cut_fill_m
    origin = mesh.node_of(*job.geometry.origin)  # type: ignore[misc]
    destination = job.geometry.destination
    targets = net_dest.sources
    if not targets.size:
        if isinstance(destination, LevelDestination):
            raise ValueError("el destino por cota no tiene ningún nodo: la preparación lo rechaza antes (RF-017-04)")
        node = mesh.node_of(*destination)  # type: ignore[misc]
        targets = np.array([node[0] * cols + node[1]], dtype=np.int64)
    target_rows, target_cols = np.divmod(targets, cols)
    squares = (target_rows - origin[0]) ** 2 + (target_cols - origin[1]) ** 2
    pick = int(np.argmin(squares))
    pivot = (int(target_rows[pick]), int(target_cols[pick]))  # el nodo del destino más próximo al origen
    straight = mesh.mesh_m * math.sqrt(float(squares[pick]))

    def terrain_at(node: tuple[int, int]) -> float | None:
        found = float(mesh.z[node])
        return found if math.isfinite(found) else None

    z_origin = job.start_level_m if job.start_level_m is not None else terrain_at(origin)
    wanted = destination.level_m if isinstance(destination, LevelDestination) else job.end_level_m
    z_destination = wanted if wanted is not None else terrain_at(pivot)
    rising = None if z_origin is None or z_destination is None else z_destination >= z_origin
    shortest = float(net_dest.dist[origin])
    reachable = math.isfinite(shortest)
    length, basis = (shortest, _BASIS_NETWORK) if reachable else (straight, _BASIS_STRAIGHT)
    gradient = None
    if z_origin is not None and z_destination is not None and length > 0.0:
        gradient = abs(z_destination - z_origin) / length * 100.0
    reached_origin, reached_destination = z_origin, z_destination
    if rising is not None:
        if route is not None and route.high_m is not None and route.low_m is not None:
            reached_origin = float(np.nanmax(route.high_m)) if rising else float(np.nanmin(route.low_m))
        else:
            reached_origin = _reach_bound(net_origin, z_origin, rising, mesh, pd, hmax)
        reached_destination = _reach_bound(net_dest, z_destination, not rising, mesh, pd, hmax)
    if not net_origin.sources.size:
        limit = _node_limit(mesh, origin)
    elif not net_dest.sources.size:
        limit = _node_limit(mesh, pivot)
    elif not reachable:
        limit = _frontier_limit(mesh, np.isfinite(net_origin.dist), pivot, targets, pd, hmax, None)
    elif route is not None and route.high_m is not None:
        limit = _frontier_limit(mesh, np.isfinite(route.high_m), pivot, targets, pd, hmax, route)
    else:
        limit = None
    return NoRoute(NoRouteCause.CORRIDOR if reachable else NoRouteCause.NETWORK, params.margin_m, z_origin, z_destination, rising,
                   reached_origin, reached_destination, length, basis, gradient, limit)

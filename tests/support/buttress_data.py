# SPDX-License-Identifier: GPL-3.0-or-later
"""Los casos del contrafuerte para las pruebas del dominio (spec 016, T26; plan 016 §5.4 A10; RF-016-17, RF-016-18;
CE-016-10): el perfil, la petición, las escenas y el trabajo de ``design.buttress``, **sin proyecto** y sin datos de
cliente.

- :func:`profile` (un ``BenchProfile`` de los perfiles de la spec 013 o uno propio), :func:`request` y :func:`job_of`: lo
  que lee el cálculo (la rejilla, la partida, la zona de coronación, el relleno admitido y los valores resueltos).
- :class:`Scene` y sus constructores: un **llano** de cota constante con una zona rectangular (:func:`plane_scene`), una
  **franja** de lado a lado (:func:`strip_scene`: el problema de una sola dimensión, que se resuelve en cerrado), un
  **relieve** con celdas sin dato (:func:`relief_scene`) y **el llano de CE-016-10** de la T01
  (:func:`flat_window_scene`: 115 m con una zona de 40 × 30 m).
- :func:`hand_of`: el contrafuerte de una escena calculado por el oráculo independiente
  (:func:`tests.support.design_oracles.hand_buttress`).
- :func:`strip_closed_form`: la franja **en fórmula cerrada** (RF-013-23 en aritmética racional y el recorte final en una
  dimensión), sin el oráculo ni el código.

Todo es float64; cada función que da un array da uno **nuevo**.
"""

from __future__ import annotations

import dataclasses
import math
from fractions import Fraction
from typing import Any

import numpy as np

from tests.support import design_fixtures as dfx
from tests.support import design_oracles as oracles
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender

model = import_geoblender("design.model")

CODE = "BTR-001"
"""El código del contrafuerte de las pruebas (``des.buttress.btr_001.*``)."""
NAME = "Contrafuerte de prueba"
LAYER = "Zonas de coronación"
FEATURE = "1"
CHAMFER_SCALE = oracles.CHAMFER_SCALE
"""La escala del *chamfer* 5×5 (ADR-0014): un paso de eje cuesta ``paso · 0,98644``."""

SMALL = dfx.ProfileData("SMALL_10_45_10", "small_10_45_10", 10.0, 45.0, 10.0, 100.0)
"""Un perfil de pruebas: bancos de 10 m con la cara a 45° y bermas de 10 m, ancla a 100 m; el avance es de 20 m y el talud
general de ``atan(0,5)`` (con celdas de 2 m, una cota baja 1 m por celda)."""


def profile(source: Any = dfx.EXPL_10_60_6, **changes: Any) -> Any:
    """El ``BenchProfile`` de un perfil de ``tests.support.design_fixtures`` (``source``), con ``changes`` sobre sus campos
    (``height_m``, ``face_deg``, ``berm_m``, ``anchor_m``, ``mesh_factor``)."""
    found = dataclasses.replace(source, **changes) if changes else source
    return model.BenchProfile(found.code, found.name, found.height_m, found.face_deg, found.berm_m, found.anchor_m,
                              found.mesh_factor)


def request(*, name: str = NAME, layer: str = LAYER, profile_code: str = "expl_10_60_6") -> Any:
    """La petición de un contrafuerte (solo la leen los mensajes: nombre y capa)."""
    return model.ButtressRequest(name=name, fields=model.ButtressFields(layer=layer), feature=FEATURE, start="terreno",
                                 profile=profile_code)


@dataclasses.dataclass(slots=True)
class Scene:
    """Lo que se lee de un contrafuerte: la ``grid``, la partida ``start`` (m; NaN, sin dato), la ``zone`` de coronación y
    el relleno admitido ``allowed`` (booleanas) y el perfil (``BenchProfile``)."""

    grid: Any
    start: np.ndarray
    zone: np.ndarray
    allowed: np.ndarray
    profile: Any


def _grid(rows: int, cols: int, step: float) -> Any:
    return dfx.grid_from(rows, cols, step)


def plane_scene(rows: int = 44, cols: int = 44, step: float = 2.0, level: float = 101.5,
                box: tuple[int, int, int, int] = (18, 26, 18, 26), source: Any = SMALL) -> Scene:
    """Un llano de ``rows`` × ``cols`` celdas de ``step`` m a ``level`` m con la zona de coronación en las filas
    ``box[0]:box[1]`` y las columnas ``box[2]:box[3]``, todo admitido."""
    zone = np.zeros((rows, cols), dtype=bool)
    zone[box[0]:box[1], box[2]:box[3]] = True
    return Scene(_grid(rows, cols, step), np.full((rows, cols), float(level)), zone, np.ones((rows, cols), dtype=bool),
                 profile(source))


def strip_scene(rows: int = 60, cols: int = 6, step: float = 2.0, level: float = 102.0, first: int = 28,
                last: int = 31, source: Any = SMALL) -> Scene:
    """Un llano con la zona de coronación de **lado a lado** (todas las columnas, de la fila ``first`` a la ``last``,
    incluida): cada columna es igual a las demás y el problema es de una sola dimensión."""
    zone = np.zeros((rows, cols), dtype=bool)
    zone[first:last + 1, :] = True
    return Scene(_grid(rows, cols, step), np.full((rows, cols), float(level)), zone, np.ones((rows, cols), dtype=bool),
                 profile(source))


def relief_scene(seed: int = 1, rows: int = 40, cols: int = 44, step: float = 2.0) -> Scene:
    """Un terreno con relieve (de 96 a 108 m, suave), una zona de coronación en L con un hueco, celdas sin dato (dentro de
    la zona y fuera), una celda de la zona a 118 m (por encima de la coronación de 115 m con que se prueba: no siembra),
    una cresta de 111 m fuera de ella y celdas sin relleno admitido (un bloque dentro y la franja del este)."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:rows, 0:cols].astype(np.float64)
    start = 102.0 + 3.0 * np.sin(x / 6.0) + 2.0 * np.cos(y / 5.0) + rng.uniform(-0.4, 0.4, (rows, cols))
    zone = np.zeros((rows, cols), dtype=bool)
    zone[14:20, 12:30] = True
    zone[14:30, 12:17] = True
    zone[16:18, 20:22] = False
    start[15, 14] = np.nan
    start[28, 40] = np.nan
    start[18, 25] = 118.0  # una celda de la zona por encima de la coronación de 115 m: no siembra
    start[30:33, 30:36] = 111.0  # una cresta fuera de la zona
    allowed = np.ones((rows, cols), dtype=bool)
    allowed[24:30, 22:30] = False
    allowed[:, 36:] = False
    return Scene(_grid(rows, cols, step), start, zone, allowed, profile(dfx.EXPL_10_60_6, mesh_factor=0.93))


def flat_window_scene(step: float = 2.0, tilt_deg: float = 0.0) -> Scene:
    """El llano de CE-016-10 de la T01 (``stockpile_data.flat_window``): 115 m en una ventana de 120 m con la zona de coronación
    de 40 × 30 m (:data:`~tests.support.stockpile_data.BUTTRESS_ZONE_LOCAL`) y el perfil ``EXPL_10_60_6``."""
    case = sdata.flat_window(tilt_deg, step)
    zone = sdata.in_box(sdata.BUTTRESS_ZONE_LOCAL, case.grid)
    return Scene(case.grid, np.array(case.terrain, dtype=np.float64), zone, np.ones(case.terrain.shape, dtype=bool),
                 profile(dfx.EXPL_10_60_6))


def values_of(crown: float | None, *, reach: float | None = None, metric: str | None = None,
              extra: dict[str, object] | None = None) -> dict[str, object]:
    """Los valores resueltos del contrafuerte (por último segmento de su clave): la cota de coronación (``None``: sin valor),
    el alcance y la métrica solo si se piden."""
    found: dict[str, object] = {"crown_m": crown}
    if reach is not None:
        found["reach_m"] = reach
    if metric is not None:
        found["metric"] = metric
    found.update(extra or {})
    return found


def job_of(scene: Scene, crown: float | None, *, reach: float | None = None, metric: str | None = None,
           region: tuple[slice, slice] | None = None, lowest_m: float | None = None, name: str = NAME,
           layer: str = LAYER, **extra: object) -> Any:
    """El trabajo de contrafuerte de ``scene`` con la cota de coronación ``crown``; ``region`` lee solo esa ventana (con
    ``lowest_m``, la cota más baja de la partida de la rejilla entera)."""
    buttress = import_geoblender("design.buttress")
    start, zone, allowed = scene.start, scene.zone, scene.allowed
    if region is not None:
        start, zone, allowed = start[region], zone[region], allowed[region]
    return buttress.ButtressJob(request(name=name, layer=layer, profile_code=scene.profile.code), CODE, scene.grid,
                                scene.profile, start, zone, allowed,
                                values_of(crown, reach=reach, metric=metric, extra=dict(extra)), region=region,
                                lowest_m=lowest_m)


def tan_face(found: Any) -> float:
    """``tan α`` de la cara de un perfil."""
    return math.tan(math.radians(found.face_deg))


def hand_of(scene: Scene, crown: float, *, metric: str = "exact", reach: float | None = None) -> Any:
    """El contrafuerte de ``scene`` calculado por el oráculo independiente (``design_oracles.hand_buttress``)."""
    found = scene.profile
    return oracles.hand_buttress(scene.start, scene.zone, scene.allowed, crown=crown, height=found.height_m,
                                 tan_face=tan_face(found), berm=found.berm_m, anchor=found.anchor_m,
                                 mesh=found.mesh_factor, step=scene.grid.dx, metric=metric, reach=reach)


# --- La franja, en fórmula cerrada -------------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class Strip:
    """La franja por fila, en fórmula cerrada: la ``distance`` (m) de cada fila a la zona, la ``envelope`` descendente, el
    escalonado en relleno ``stairs`` (RF-013-23), su recorte ``stepped`` y la ``surface``; y las cifras por **columna** (m²,
    m³ y m): el ``volume``, el ``area`` y la ``height_max``, que se multiplican por las columnas."""

    distance: tuple[float, ...]
    envelope: tuple[float, ...]
    stairs: tuple[float, ...]
    stepped: tuple[float, ...]
    surface: tuple[float, ...]
    volume: float
    area: float
    height_max: float


def strip_closed_form(rows: int, first: int, last: int, *, level: float, crown: float, found: Any, step: float,
                      metric: str = "exact") -> Strip:
    """La franja de ``rows`` filas con la zona de coronación en las filas ``first`` a ``last`` sobre un llano de ``level`` m,
    **en fórmula cerrada** y sin más código que el de esta función.

    Por la simetría de las columnas, la distancia de una fila a la semilla más próxima es la de **su columna**: ``k·paso``
    con ``k`` las filas que la separan de la zona (con el *chamfer*, ``k·paso·0,98644``) y la envolvente descendente,
    ``E_k = coronación − tan·malla·distancia``, con la tangente del talud general ``h/(h/tan α + B)``. El escalonado en
    relleno es el de RF-013-23, ``z₀ + n·h + máx((f·a − B)·tan α, 0)``, con ``u = (E − z₀)/h``, ``n = ⌊u⌋`` y ``f = u − n``
    **exactos** (racionales). Su recorte es la envolvente ascendente de una dimensión,
    ``mín_j [escalonado_j + tan α·malla·0,98644·paso·|k − j|]``, acotada por ``E`` (un paso de eje cuesta lo mismo que
    una fila: ningún paso de caballo de la máscara 5×5 cuesta menos que las filas que cruza), y la superficie, ``máx(llano,
    recorte)``."""
    height, berm, anchor, mesh = found.height_m, found.berm_m, found.anchor_m, found.mesh_factor
    tan = tan_face(found)
    advance = height / tan + berm
    general = mesh * height / advance
    scale = CHAMFER_SCALE if metric == "chamfer5" else 1.0
    distance = tuple(0.0 if first <= r <= last else scale * step * (first - r if r < first else r - last)
                     for r in range(rows))
    envelope = tuple(crown - general * d for d in distance)
    stairs: list[float] = []
    for value in envelope:
        index = (Fraction(value) - Fraction(anchor)) / Fraction(height)
        number = math.floor(index)
        fraction = float(index - number)
        stairs.append(anchor + number * height + max((fraction * advance - berm) * tan, 0.0))
    cost = tan * mesh * CHAMFER_SCALE * step
    stepped = tuple(min(min(stairs[j] + cost * abs(r - j) for j in range(rows)), envelope[r]) for r in range(rows))
    surface = tuple(max(level, value) for value in stepped)
    rises = [value - level for value in surface if value > level]
    return Strip(distance, envelope, tuple(stairs), stepped, surface, math.fsum(rises) * step * step,
                 len(rises) * step * step, max(rises, default=0.0))

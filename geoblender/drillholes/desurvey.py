# SPDX-License-Identifier: GPL-3.0-or-later
"""Trazas de los sondeos: posición de cada estación por mínima curvatura, tangente o tangente
equilibrada (spec 005, T06; RF-005-20; plan 005 §5.4 y D7).

**Convenios** (los internos, spec §7): azimut A de cuadrícula, en sentido horario, en
[0, 360); inclinación θ desde la horizontal, negativa hacia abajo. La dirección unitaria de una
estación (:func:`direction`), con I = 90° + θ, es t = (sin I·sin A, sin I·cos A, −cos I) en
(E, N, Z arriba): la vertical hacia abajo es exactamente (0, 0, −1).

**Estaciones de cada sondeo** (:func:`desurvey`): ordenadas por profundidad (MD), con la
orientación de la más próxima prolongada hasta la boca si la primera está por debajo
(DH-W02) y hasta el fondo si la última está por encima (DH-W03). La traza va de la boca
(MD = 0, la X, Y, Z de la boca, exacta) al fondo, o hasta la última estación si está algo más
abajo (la validación admite su tolerancia, DH-E07). La orientación en boca y la vertical
declarada (``StationSource.COLLAR`` y ``DECLARED_VERTICAL``, una estación en la boca) definen
un sondeo recto hasta el fondo: su prolongación no se avisa; la de una estación medida, sí
(:class:`TraceWarning`, con el tramo prolongado).

**Métodos** (:class:`Method`), por par de estaciones consecutivas, con ΔMD su distancia:

- mínima curvatura (por defecto): β = 2·atan2(|t₂ − t₁|, |t₂ + t₁|) (:func:`dogleg`, estable
  cerca de 0), RF = (2/β)·tan(β/2) (:func:`ratio_factor`; 1 + β²/12 si β < 10⁻⁶ rad) y
  Δ = ΔMD/2·(t₁ + t₂)·RF. Exacta en arcos de circunferencia (Sawaryn y Thorogood, 2005, «A
  compendium of directional calculations based on the minimum curvature method», SPE
  Drilling & Completion 20(1));
- tangente: Δ = ΔMD·t₁;
- tangente equilibrada: Δ = ΔMD/2·(t₁ + t₂).

Las posiciones son la boca más la suma acumulada de los Δ de su sondeo. Todo es vectorial:
una ordenación, un ``cumsum`` sobre todos los sondeos y la resta de la suma en la boca de cada
uno; ningún bucle por sondeo ni por estación. Las coordenadas son absolutas y en float64
(ADR-0005); el error de la suma de todos los sondeos es del orden de un ulp de la suma por
estación (≈ 10⁻⁹ m con V-ref).

**Sondeos que no se pueden calcular.** Las trazas se calculan solo para sondeos sin errores
de alcance S (spec §4.4.1): boca sin X, Y o Z (DH-E02), sin profundidad total (DH-E03), sin
estaciones (DH-E05), estaciones repetidas (DH-E06), a profundidad negativa (DH-E07) o con
ángulos fuera de rango (DH-E08). Quien calcula los quita antes con la validación (la parte
de alcance S, ``drillholes.validate``) y pasa los demás en ``holes``; si llega uno, no se
calcula a medias: ``ValueError`` con su nombre y su código. Las estaciones sin boca
(DH-E04) no entran en ninguna traza.

Nada modifica el conjunto de sondeos. Las posiciones de una profundidad cualquiera
(``md_to_xyz``) y las polilíneas densificadas (``polylines``) son de la tarea T07, sobre las
:class:`Traces` de aquí. Python puro y numpy (ADR-0004).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from .model import DrillholeSet, StationSource, SurveyColumns

__all__ = [
    "RF_SERIES_LIMIT_RAD",
    "WARN_BOTTOM",
    "WARN_TOP",
    "Method",
    "TraceWarning",
    "Traces",
    "desurvey",
    "direction",
    "dogleg",
    "ratio_factor",
]

RF_SERIES_LIMIT_RAD = 1e-6  # por debajo, RF = 1 + β²/12 (plan §5.4)
WARN_TOP = "DH-W02"  # primera estación por debajo de la boca
WARN_BOTTOM = "DH-W03"  # última estación por encima del fondo

_MEASURED = SurveyColumns.code_values("source").index(StationSource.MEASURED)
_FULL_TURN_DEG = 360.0
_RIGHT_ANGLE_DEG = 90.0
_NAMES_SHOWN = 10  # sondeos que nombra un error, por código

# Los errores de alcance S que impiden calcular una traza (spec §4.4.1).
_UNTRACEABLE = {
    "DH-E02": "X, Y o Z de la boca ausente o no finita",
    "DH-E03": "profundidad total ausente, no finita o ≤ 0 m",
    "DH-E05": "sin estaciones, ni orientación en boca, ni vertical declarada",
    "DH-E06": "dos estaciones a la misma profundidad",
    "DH-E07": "estación a profundidad negativa o no finita",
    "DH-E08": "azimut fuera de [0, 360) o inclinación fuera de [−90, 90]",
}


class Method(StrEnum):
    """El método de cálculo de las trazas (``dh_trace.method``; RF-005-20)."""

    MINIMUM_CURVATURE = "minimum_curvature"
    TANGENT = "tangent"
    BALANCED_TANGENT = "balanced_tangent"


@dataclass(frozen=True, slots=True)
class TraceWarning:
    """Una prolongación de la orientación de una estación medida: hasta la boca
    (:data:`WARN_TOP`, DH-W02) o hasta el fondo (:data:`WARN_BOTTOM`, DH-W03), en el sondeo
    ``hole`` (su posición entre las bocas) llamado ``name``, de ``depth_from`` a ``depth_to``
    (m)."""

    code: str
    hole: int
    name: str
    depth_from: float
    depth_to: float


def _array(value: object, what: str, dtype: type, ndim: int) -> np.ndarray:
    if not isinstance(value, np.ndarray) or value.dtype != dtype or value.ndim != ndim:
        raise TypeError(f"{what} es un array {np.dtype(dtype)} de {ndim} dimensiones, no "
                        f"{value!r}")
    return value


@dataclass(frozen=True, eq=False)
class Traces:
    """Las trazas de un conjunto de sondeos (RF-005-20): un nodo por estación (con las
    prolongadas hasta la boca y el fondo), ordenados por sondeo y profundidad.

    - ``hole_start`` (int64, una más que bocas): los nodos del sondeo k son
      ``hole_start[k]:hole_start[k + 1]``; vacío si no se ha calculado.
    - ``md`` (float64): la profundidad de cada nodo (m), desde 0 en la boca.
    - ``xyz`` (float64, (n, 3)): su posición absoluta (E, N, Z) en el CRS y la referencia
      vertical del conjunto de sondeos.
    - ``tangent`` (float64, (n, 3)): su dirección unitaria (:func:`direction`).
    - ``method``: el método usado; ``warnings``: las prolongaciones avisadas.
    """

    hole_start: np.ndarray
    md: np.ndarray
    xyz: np.ndarray
    tangent: np.ndarray
    method: Method
    warnings: tuple[TraceWarning, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "method", Method(self.method))
        start = _array(self.hole_start, "hole_start", np.int64, 1)
        md = _array(self.md, "md", np.float64, 1)
        for name in ("xyz", "tangent"):
            if _array(getattr(self, name), name, np.float64, 2).shape != (md.size, 3):
                raise ValueError(f"{name} tiene una fila (E, N, Z) por nodo: ({md.size}, 3), "
                                 f"no {getattr(self, name).shape}")
        if start.size == 0 or start[0] != 0 or start[-1] != md.size or (np.diff(start) < 0).any():
            raise ValueError(f"hole_start va de 0 a {md.size} sin bajar, no {start.tolist()}")
        found = tuple(self.warnings)
        if not all(isinstance(item, TraceWarning) for item in found):
            raise TypeError(f"los avisos de unas trazas son TraceWarning, no {found!r}")
        object.__setattr__(self, "warnings", found)

    @property
    def computed(self) -> np.ndarray:
        """Una máscara con los sondeos que tienen traza."""
        return np.diff(self.hole_start) > 0

    @property
    def node_hole(self) -> np.ndarray:
        """El sondeo (posición entre las bocas, int64) de cada nodo."""
        counts = np.diff(self.hole_start)
        return np.repeat(np.arange(counts.size, dtype=np.int64), counts)


def direction(azimuth: np.ndarray, inclination: np.ndarray) -> np.ndarray:
    """La dirección unitaria (n, 3) en (E, N, Z arriba) de unos azimutes de cuadrícula y unas
    inclinaciones internas (grados): t = (sin I·sin A, sin I·cos A, −cos I), I = 90° + θ."""
    i = np.radians(_RIGHT_ANGLE_DEG + np.asarray(inclination, dtype=np.float64))
    a = np.radians(np.asarray(azimuth, dtype=np.float64))
    sin_i = np.sin(i)
    return np.column_stack((sin_i * np.sin(a), sin_i * np.cos(a), -np.cos(i)))


def dogleg(t1: np.ndarray, t2: np.ndarray) -> np.ndarray:
    """El ángulo (rad) entre las direcciones unitarias de cada fila de ``t1`` y ``t2``:
    β = 2·atan2(|t₂ − t₁|, |t₂ + t₁|), exacto también cuando es diminuto (el arco coseno del
    producto escalar da 0 por debajo de unos 10⁻⁸ rad)."""
    t1 = np.asarray(t1, dtype=np.float64)
    t2 = np.asarray(t2, dtype=np.float64)
    return 2.0 * np.arctan2(np.linalg.norm(t2 - t1, axis=-1), np.linalg.norm(t2 + t1, axis=-1))


def ratio_factor(beta: np.ndarray) -> np.ndarray:
    """El factor de razón de la mínima curvatura, RF = (2/β)·tan(β/2), con β en radianes;
    1 + β²/12 (su serie, sin división) por debajo de :data:`RF_SERIES_LIMIT_RAD`."""
    beta = np.asarray(beta, dtype=np.float64)
    result = 1.0 + beta * beta / 12.0
    big = beta >= RF_SERIES_LIMIT_RAD
    half = beta[big] / 2.0
    result[big] = np.tan(half) / half
    return result


def _steps(method: Method, length: np.ndarray, t1: np.ndarray, t2: np.ndarray) -> np.ndarray:
    """El desplazamiento (m, 3) de cada par de estaciones por ``method``."""
    if method is Method.TANGENT:
        return length[:, None] * t1
    pair = t1 + t2
    half = 0.5 * length
    if method is Method.MINIMUM_CURVATURE:
        half = half * ratio_factor(dogleg(t1, t2))
    return half[:, None] * pair


def _wanted(holes: np.ndarray | None, count: int) -> np.ndarray:
    """La máscara de los sondeos pedidos: todos, unas posiciones distintas o una máscara."""
    if holes is None:
        return np.ones(count, dtype=np.bool_)
    index = np.asarray(holes)
    if index.ndim != 1:
        raise ValueError(f"los sondeos que se calculan son un array de una dimensión, no de "
                         f"{index.ndim}")
    if index.dtype == np.bool_:
        if index.shape != (count,):
            raise ValueError(f"una máscara de sondeos tiene {count} valores, no {index.size}")
        return index.copy()
    if not np.issubdtype(index.dtype, np.integer):
        raise TypeError(f"los sondeos que se calculan son posiciones enteras o una máscara, "
                        f"no {index.dtype}")
    if index.size and (index.min() < 0 or index.max() >= count):
        raise IndexError(f"posiciones de sondeo fuera de [0, {count})")
    if np.unique(index).size != index.size:
        raise ValueError("cada sondeo se pide una sola vez")
    mask = np.zeros(count, dtype=np.bool_)
    mask[index] = True
    return mask


def _refuse(dset: DrillholeSet, problems: dict[str, np.ndarray]) -> None:
    """``ValueError`` con los sondeos de cada código de ``problems`` (posiciones de boca)."""
    found = []
    for code, holes in problems.items():
        unique = np.unique(holes)
        if not unique.size:
            continue
        names = [str(name) for name in dset.collars.name[unique[:_NAMES_SHOWN]].tolist()]
        more = unique.size - len(names)
        listed = ", ".join(names) + (f" y {more} más" if more else "")
        found.append(f"{code} ({_UNTRACEABLE[code]}): {listed}")
    if found:
        raise ValueError("no se calculan las trazas de sondeos con errores de alcance S (la "
                         "validación los excluye): " + "; ".join(found))


def _check(dset: DrillholeSet, chosen: np.ndarray, hole: np.ndarray, md: np.ndarray,
           azimuth: np.ndarray, inclination: np.ndarray, stations: np.ndarray) -> None:
    """Los sondeos ``chosen`` y sus estaciones (ordenadas por sondeo y profundidad) se pueden
    calcular; si no, :func:`_refuse`."""
    collars = dset.collars
    xyz = np.column_stack((collars.x[chosen], collars.y[chosen], collars.z[chosen]))
    depth = collars.depth[chosen]
    same = np.flatnonzero((hole[1:] == hole[:-1]) & (md[1:] == md[:-1]))
    angles = (np.isfinite(azimuth) & (azimuth >= 0.0) & (azimuth < _FULL_TURN_DEG)
              & np.isfinite(inclination) & (np.abs(inclination) <= _RIGHT_ANGLE_DEG))
    _refuse(dset, {
        "DH-E02": chosen[~np.isfinite(xyz).all(axis=1)],
        "DH-E03": chosen[~(np.isfinite(depth) & (depth > 0.0))],
        "DH-E05": chosen[stations[chosen] == 0],
        "DH-E06": hole[same],
        "DH-E07": hole[~(np.isfinite(md) & (md >= 0.0))],
        "DH-E08": hole[~angles],
    })


def _warnings(dset: DrillholeSet, code: str, hole: np.ndarray, start: np.ndarray,
              end: np.ndarray) -> list[TraceWarning]:
    names = dset.collars.name[hole].tolist()
    return [TraceWarning(code, k, str(name), a, b) for k, name, a, b
            in zip(hole.tolist(), names, start.tolist(), end.tolist(), strict=True)]


def desurvey(dset: DrillholeSet, method: Method | str = Method.MINIMUM_CURVATURE,
             holes: np.ndarray | None = None) -> Traces:
    """Las trazas de los sondeos ``holes`` de ``dset`` (posiciones distintas entre las bocas
    o una máscara; ``None``, todos) por ``method`` (RF-005-20; véase el módulo).

    Cada sondeo pedido debe poder calcularse (sin errores de alcance S): si no,
    ``ValueError`` con su nombre y su código. ``IndexError`` con una posición fuera de rango;
    ``ValueError`` con una repetida, una máscara de otra longitud o un método desconocido."""
    if not isinstance(dset, DrillholeSet):
        raise TypeError(f"las trazas se calculan sobre un DrillholeSet, no {dset!r}")
    method = Method(method)
    collars, surveys = dset.collars, dset.surveys
    count = len(collars)
    wanted = _wanted(holes, count)
    chosen = np.flatnonzero(wanted)

    # Las estaciones de los sondeos pedidos, por sondeo y profundidad.
    linked = np.flatnonzero(surveys.hole >= 0)
    rows = linked[wanted[surveys.hole[linked]]]
    order = rows[np.lexsort((surveys.depth[rows], surveys.hole[rows]))]
    hole = surveys.hole[order]
    md = surveys.depth[order]
    azimuth = surveys.azimuth[order]
    inclination = surveys.inclination[order]
    measured = surveys.source[order] == _MEASURED
    stations = np.bincount(hole, minlength=count)
    _check(dset, chosen, hole, md, azimuth, inclination, stations)
    tangent = direction(azimuth, inclination)

    # La prolongación de la primera estación hasta la boca y de la última hasta el fondo.
    after = np.cumsum(stations)
    first = (after - stations)[chosen]
    last = after[chosen] - 1
    depth = collars.depth[chosen]
    top = md[first] > 0.0
    bottom = md[last] < depth
    node_hole = np.concatenate((hole, chosen[top], chosen[bottom]))
    node_md = np.concatenate((md, np.zeros(int(top.sum())), depth[bottom]))
    node_t = np.concatenate((tangent, tangent[first[top]], tangent[last[bottom]]))
    order = np.lexsort((node_md, node_hole))
    node_hole, node_md, node_t = node_hole[order], node_md[order], node_t[order]

    # Desplazamiento de cada par de nodos del mismo sondeo y suma acumulada desde la boca.
    nodes = node_md.size
    pairs = np.flatnonzero(node_hole[1:] == node_hole[:-1])
    delta = np.zeros((max(nodes - 1, 0), 3))
    delta[pairs] = _steps(method, node_md[pairs + 1] - node_md[pairs], node_t[pairs],
                          node_t[pairs + 1])
    total = np.zeros((nodes, 3))
    np.cumsum(delta, axis=0, out=total[1:])
    hole_start = np.zeros(count + 1, dtype=np.int64)
    np.cumsum(np.bincount(node_hole, minlength=count), out=hole_start[1:])
    origin = np.column_stack((collars.x, collars.y, collars.z))
    xyz = origin[node_hole] + (total - total[hole_start[node_hole]])

    top_warned = top & measured[first]
    bottom_warned = bottom & measured[last]
    found = (_warnings(dset, WARN_TOP, chosen[top_warned], np.zeros(int(top_warned.sum())),
                       md[first[top_warned]])
             + _warnings(dset, WARN_BOTTOM, chosen[bottom_warned], md[last[bottom_warned]],
                         depth[bottom_warned]))
    found.sort(key=lambda item: (item.hole, item.code))
    return Traces(hole_start=hole_start, md=node_md, xyz=xyz, tangent=node_t, method=method,
                  warnings=tuple(found))

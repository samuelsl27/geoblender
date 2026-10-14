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

**Posición de cualquier profundidad** (:func:`md_to_xyz`; RF-005-21; tarea T07): sobre la
misma curva que la traza, desde el nodo anterior (p₁, t₁, a la profundidad MD₁) y el
siguiente (t₂, a ΔMD), con s = MD − MD₁ y f = s/ΔMD:

- mínima curvatura: el arco de circunferencia entre los dos nodos,
  p = p₁ + s/2·(t₁ + t(f))·RF(f·β), con t(f) = slerp(t₁, t₂, f) (exacto en un arco; la
  interpolación lineal normalizada por debajo de :data:`RF_SERIES_LIMIT_RAD`);
- tangente: p₁ + s·t₁;
- tangente equilibrada: t₁ hasta ΔMD/2 y t₂ después.

En un nodo (s = 0) da exactamente su punto de la traza. Por debajo del último nodo (un tramo
que llega algo más abajo que el fondo, dentro de la tolerancia de la validación, DH-E09) se
prolonga la orientación del fondo, como manda RF-005-20 hasta el fondo. Por encima de la
boca, en un sondeo sin traza o con una profundidad no finita, no hay posición: error.

**Polilíneas densificadas** (:func:`polylines`, :func:`polyline_md`): por sondeo con traza,
sus nodos (boca, estaciones y fondo) y las profundidades pedidas (los límites de los tramos),
con puntos intermedios en partes iguales de cada intervalo para que ninguno pase de
``max_step_m`` (``dh.desurvey.trace_step_m``, plan §5.2.3); sus puntos son los de
:func:`md_to_xyz`. Son la geometría de ``dh_trace`` y de la vista; la posición exacta de una
profundidad no se lee de ellas, se calcula con :func:`md_to_xyz` (plan D7).

Nada modifica el conjunto de sondeos ni las trazas. Python puro y numpy (ADR-0004).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
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
    "md_to_xyz",
    "polyline_md",
    "polylines",
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


def _depths(value: object, what: str) -> np.ndarray:
    """Unas profundidades (m) en float64: float64 o enteras (exactas); otra precisión de
    coma flotante se rechaza, como en el modelo (RF-005-02)."""
    found = np.asarray(value)
    if found.dtype.kind == "f" and found.dtype != np.float64:
        raise TypeError(f"{what} van en float64, no en {found.dtype}")
    if found.dtype.kind not in "fiu":
        raise TypeError(f"{what} son números, no {found.dtype}")
    return found.astype(np.float64, copy=False)


def _without_trace(traces: Traces, holes: np.ndarray) -> None:
    """``ValueError`` si alguno de ``holes`` (posiciones ya en rango) no tiene traza."""
    missing = np.unique(holes[~traces.computed[holes]])
    if missing.size:
        listed = ", ".join(str(k) for k in missing[:_NAMES_SHOWN].tolist())
        more = missing.size - min(missing.size, _NAMES_SHOWN)
        raise ValueError(f"sondeos sin traza (posiciones {listed}"
                         f"{f' y {more} más' if more else ''}): no se calculó, o la "
                         "validación los excluye")


def _check_depths(traces: Traces, holes: np.ndarray, md: np.ndarray, what: str) -> None:
    """``ValueError`` si alguna de ``md`` no es finita o está por encima de la boca (del
    primer nodo de su sondeo)."""
    if not np.isfinite(md).all():
        raise ValueError(f"{what} no finitas: {md[~np.isfinite(md)][:_NAMES_SHOWN].tolist()}")
    above = md < traces.md[traces.hole_start[holes]]
    if above.any():
        raise ValueError(f"{what} por encima de la boca: {md[above][:_NAMES_SHOWN].tolist()}")


def _slerp(t1: np.ndarray, t2: np.ndarray, f: np.ndarray, beta: np.ndarray) -> np.ndarray:
    """La dirección unitaria a la fracción ``f`` del arco de ``t1`` a ``t2`` (ángulo
    ``beta``): sin((1 − f)β)/sin β·t₁ + sin(fβ)/sin β·t₂; por debajo de
    :data:`RF_SERIES_LIMIT_RAD`, la interpolación lineal normalizada (sin división por
    sin β ≈ 0; su error angular es del orden de β³)."""
    found = t1 + f[:, None] * (t2 - t1)
    big = beta >= RF_SERIES_LIMIT_RAD
    if big.any():
        b, fb = beta[big], f[big]
        sin_b = np.sin(b)
        found[big] = ((np.sin((1.0 - fb) * b) / sin_b)[:, None] * t1[big]
                      + (np.sin(fb * b) / sin_b)[:, None] * t2[big])
    small = ~big
    found[small] /= np.linalg.norm(found[small], axis=1)[:, None]
    return found


def _position(traces: Traces, node: np.ndarray, s: np.ndarray) -> np.ndarray:
    """La posición absoluta (n, 3) a ``s`` m (≥ 0) por debajo de cada nodo ``node``, por el
    método de las trazas (véase el módulo)."""
    tangent = traces.tangent
    delta = s[:, None] * tangent[node]  # tangente, y por debajo del último nodo
    last = traces.hole_start[1:][traces.node_hole[node]] - 1
    inner = np.flatnonzero(node != last)
    if inner.size and traces.method is not Method.TANGENT:
        j = node[inner]
        t1, t2 = tangent[j], tangent[j + 1]
        part = s[inner]
        length = traces.md[j + 1] - traces.md[j]
        if traces.method is Method.BALANCED_TANGENT:
            first = np.minimum(part, 0.5 * length)
            delta[inner] = first[:, None] * t1 + (part - first)[:, None] * t2
        else:
            beta = dogleg(t1, t2)
            f = part / length
            along = 0.5 * part * ratio_factor(f * beta)
            delta[inner] = along[:, None] * (t1 + _slerp(t1, t2, f, beta))
    return traces.xyz[node] + delta


def _locate(traces: Traces, hole: np.ndarray, md: np.ndarray) -> np.ndarray:
    """El último nodo del sondeo ``hole`` a profundidad ≤ ``md``, para cada consulta (ya
    comprobadas: con traza y no por encima de la boca). Nodos y consultas se ordenan juntos
    por (sondeo, profundidad, nodo antes que consulta): exacto, sin la clave
    sondeo·L + profundidad, que redondea."""
    nodes = traces.md.size
    query = np.zeros(nodes + md.size, dtype=np.bool_)
    query[nodes:] = True
    order = np.lexsort((query, np.concatenate((traces.md, md)),
                        np.concatenate((traces.node_hole, hole))))
    upto = np.cumsum(~query[order])  # nodos hasta cada posición del orden, incluida
    rank = np.empty_like(order)
    rank[order] = np.arange(order.size)
    return upto[rank[nodes:]] - 1


def _positions(traces: object, hole: object) -> np.ndarray:
    """Unas posiciones de sondeo (int64) de ``traces`` en rango y con traza."""
    if not isinstance(traces, Traces):
        raise TypeError(f"las posiciones se calculan sobre unas Traces, no {traces!r}")
    found = np.asarray(hole)
    if found.dtype.kind not in "iu":
        raise TypeError(f"los sondeos son posiciones enteras entre las bocas, no {found.dtype}")
    found = found.astype(np.int64, copy=False)
    count = traces.hole_start.size - 1
    if found.size and (found.min() < 0 or found.max() >= count):
        raise IndexError(f"posiciones de sondeo fuera de [0, {count})")
    _without_trace(traces, found.ravel())
    return found


def md_to_xyz(traces: Traces, hole: np.ndarray | int, md: np.ndarray | float) -> np.ndarray:
    """La posición absoluta (E, N, Z; float64, (n, 3)) de la profundidad ``md`` (m) de cada
    sondeo ``hole`` (su posición entre las bocas), sobre la misma curva que su traza
    (RF-005-21; véase el módulo). ``hole`` y ``md`` se combinan como en numpy (un sondeo y
    muchas profundidades, por ejemplo) y dan un array de una dimensión.

    ``TypeError`` si ``hole`` no es entero o ``md`` no es float64 ni entero; ``IndexError``
    con un sondeo fuera de rango; ``ValueError`` con uno sin traza, una profundidad no finita
    o por encima de la boca, o más de una dimensión."""
    holes = _positions(traces, hole)
    depth = _depths(md, "las profundidades")
    holes, depth = np.broadcast_arrays(holes, depth)
    if holes.ndim > 1:
        raise ValueError(f"las profundidades que se sitúan van en una dimensión, no en "
                         f"{holes.ndim}")
    holes, depth = holes.ravel(), depth.ravel()
    _check_depths(traces, holes, depth, "profundidades")
    node = _locate(traces, holes, depth)
    return _position(traces, node, depth - traces.md[node])


def _step(max_step_m: object) -> float:
    step = float(max_step_m)  # TypeError si no es un número
    if not (math.isfinite(step) and step > 0.0):
        raise ValueError(f"el paso de la polilínea es un número de metros positivo y finito, "
                         f"no {max_step_m!r}")
    return step


def _extra(traces: Traces, extra_md: Mapping[int, object] | None
           ) -> tuple[np.ndarray, np.ndarray]:
    """Los sondeos (int64) y las profundidades (float64) de ``extra_md``, comprobados."""
    if extra_md is None:
        return np.zeros(0, dtype=np.int64), np.zeros(0)
    if not isinstance(extra_md, Mapping):
        raise TypeError(f"las profundidades pedidas van por sondeo en un Mapping, no "
                        f"{extra_md!r}")
    count = traces.hole_start.size - 1
    holes, depths = [], []
    for key, values in extra_md.items():
        if isinstance(key, bool | np.bool_) or not isinstance(key, int | np.integer):
            raise TypeError(f"las profundidades pedidas van por posición entera de sondeo, "
                            f"no por {key!r}")
        if not 0 <= key < count:
            raise IndexError(f"posición de sondeo {key} fuera de [0, {count})")
        depth = _depths(values, f"las profundidades pedidas del sondeo {key}")
        if depth.ndim != 1:
            raise ValueError(f"las profundidades pedidas del sondeo {key} van en una "
                             f"dimensión, no en {depth.ndim}")
        holes.append(np.full(depth.size, int(key), dtype=np.int64))
        depths.append(depth)
    if not holes:
        return np.zeros(0, dtype=np.int64), np.zeros(0)
    hole, depth = np.concatenate(holes), np.concatenate(depths)
    _without_trace(traces, hole)
    _check_depths(traces, hole, depth, "profundidades pedidas")
    return hole, depth


def _polyline(traces: object, extra_md: Mapping[int, object] | None, max_step_m: object
              ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Los desplazamientos por boca, el último nodo anterior de cada vértice y su
    profundidad (véase :func:`polyline_md`)."""
    if not isinstance(traces, Traces):
        raise TypeError(f"las polilíneas se calculan sobre unas Traces, no {traces!r}")
    step = _step(max_step_m)
    extra_hole, extra_depth = _extra(traces, extra_md)

    # Nodos y profundidades pedidas, por sondeo y profundidad, sin repetir (el nodo primero).
    nodes = traces.md.size
    is_extra = np.zeros(nodes + extra_depth.size, dtype=np.bool_)
    is_extra[nodes:] = True
    hole = np.concatenate((traces.node_hole, extra_hole))
    md = np.concatenate((traces.md, extra_depth))
    order = np.lexsort((is_extra, md, hole))
    hole, md, is_extra = hole[order], md[order], is_extra[order]
    keep = np.ones(md.size, dtype=np.bool_)
    keep[1:] = (hole[1:] != hole[:-1]) | (md[1:] != md[:-1])
    hole, md, is_extra = hole[keep], md[keep], is_extra[keep]
    # El primer punto de cada sondeo es su nodo de la boca: lo anterior de cada punto,
    # el último nodo hasta él.
    node_of = np.cumsum(~is_extra) - 1

    # Partes iguales de ≤ step en cada intervalo hasta el punto siguiente del sondeo.
    gap = np.zeros(md.size)
    same = hole[1:] == hole[:-1]
    gap[:-1][same] = (md[1:] - md[:-1])[same]
    pieces = np.maximum(np.ceil(gap / step), 1.0)
    pieces += gap / pieces > step  # por si el cociente redondeó hacia abajo
    pieces = pieces.astype(np.int64)
    rep = np.repeat(np.arange(md.size), pieces)
    k = np.arange(rep.size) - np.repeat(np.cumsum(pieces) - pieces, pieces)
    vertex_md = md[rep] + gap[rep] * k / pieces[rep]
    count = traces.hole_start.size - 1
    offsets = np.zeros(count + 1, dtype=np.int64)
    np.cumsum(np.bincount(hole[rep], minlength=count), out=offsets[1:])
    return offsets, node_of[rep], vertex_md


def polyline_md(traces: Traces, extra_md: Mapping[int, np.ndarray] | None,
                max_step_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Las profundidades de los vértices de la polilínea de cada sondeo con traza (véase el
    módulo): ``offsets`` (int64, una más que bocas; los vértices del sondeo k son
    ``offsets[k]:offsets[k + 1]``, ninguno sin traza) y ``md`` (float64, crecientes en cada
    sondeo). Tienen los nodos de la traza y las profundidades ``extra_md`` (por posición de
    sondeo; una por debajo del fondo prolonga la polilínea) y, entre cada dos, puntos en
    partes iguales de a lo sumo ``max_step_m`` (m; salvo el redondeo de float64).

    ``TypeError`` con una clave que no es una posición entera o profundidades que no son
    float64 ni enteras; ``IndexError`` con una posición fuera de rango; ``ValueError`` con un
    paso que no es positivo y finito, profundidades de un sondeo sin traza, no finitas, por
    encima de la boca o en más de una dimensión."""
    offsets, _, md = _polyline(traces, extra_md, max_step_m)
    return offsets, md


def polylines(traces: Traces, extra_md: Mapping[int, np.ndarray] | None,
              max_step_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Las polilíneas densificadas de los sondeos con traza (RF-005-21; ``dh_trace`` y la
    vista): ``offsets`` como en :func:`polyline_md` y ``xyz`` (float64, (n, 3), absolutas),
    la posición de :func:`md_to_xyz` de cada vértice (exactamente la de la traza en sus
    nodos). Mismos errores que :func:`polyline_md`."""
    offsets, node, md = _polyline(traces, extra_md, max_step_m)
    return offsets, _position(traces, node, md - traces.md[node])

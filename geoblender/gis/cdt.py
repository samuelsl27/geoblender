# SPDX-License-Identifier: GPL-3.0-or-later
"""Triangulador propio: Delaunay restringida sin Blender (spec 006; plan 006 §5.3.1 y §5.4 A9;
ADR-0021; RF-006-13).

:class:`PureTriangulator` implementa el puerto ``gis.ports.Triangulator`` en Python y numpy:
lo usan las pruebas sin Blender, el trabajo ``gis_triangulate`` (por encima del umbral de la
CDT de Blender) y la alternativa de cualquier fallo. Mismo contrato que la CDT de Blender:

- entrada: ``xy_local`` float64 (n, 2), relativas al GeoOrigin, y ``edges`` int (k, 2), las
  aristas obligatorias, sin cruces (las prepara ``gis.breaklines``);
- salida: int32 (m, 3), índices de la entrada (nunca un vértice nuevo), triángulos
  antihorarios vistos desde arriba que cubren la envolvente convexa, con cada arista
  obligatoria como arista y la propiedad de Delaunay restringida: ningún vértice dentro del
  círculo circunscrito de un triángulo salvo que lo tape una arista obligatoria.

Algoritmo (A9):

1. **Bowyer–Watson incremental** dentro de un supertriángulo a 10³ × la extensión, con orden
   **BRIO** (Amenta, Choi y Rote, 2003: rondas al azar de tamaño doble, con semilla fija, y
   cada ronda en el orden de la curva de Hilbert) y búsqueda por **caminata** desde el último
   triángulo creado.
2. **Predicados** ``orient2d`` e ``incircle`` con el filtro de error estático de Shewchuk
   (1997) y, cuando el filtro no decide, evaluación **exacta** con ``fractions.Fraction`` (un
   float64 es un racional diádico): el signo es siempre el exacto, también en mallas
   regulares, puntos cocirculares o casi alineados.
3. **Restricciones** por volteo de aristas (Sloan, 1993): las aristas que cruzan la
   obligatoria se voltean hasta que aparece, y después se restaura la propiedad de Delaunay
   volteando las nuevas, nunca una obligatoria.
4. **Borde**: la envolvente convexa (cadena monótona, con los puntos alineados del borde) se
   compara con la triangulación; la arista del borde que falte (el supertriángulo es finito) se
   añade como restricción. Se quitan los triángulos del supertriángulo.
5. Se comprueba el contrato (:func:`check_contract`) y se devuelven los triángulos en orden
   canónico (cada uno desde su menor índice, ordenados): con datos no degenerados la
   triangulación es única y no depende del orden de la entrada.

Lo que no tiene triangulación (menos de 3 puntos, todos alineados, puntos repetidos,
coordenadas no finitas, una arista obligatoria que pasa por un vértice o dos que se cruzan)
da :class:`TriangulatorError` ``gis.triangulation_input``; una salida que no cumpla el
contrato, ``gis.triangulation_contract``. Una forma o un tipo de array que el contrato no
admite es un error del programa (``ValueError`` o ``TypeError``).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction

import numpy as np

from ..jobs.worker_api import JobCancelled
from .messages import GisError, format_value
from .ports import Cancelled, Progress, TriangulationError

__all__ = [
    "ALGORITHM_VERSION",
    "HULL_FILTER_MIN",
    "NAME",
    "PROGRESS_STEP",
    "SUPER_SCALE",
    "CheckedInput",
    "PureTriangulator",
    "TriangulatorError",
    "check_contract",
    "check_input",
    "check_output",
    "incircle",
    "orient2d",
]

ALGORITHM_VERSION = 1
"""Versión del algoritmo (cambia si cambia la triangulación que sale de unos datos)."""

NAME = f"pure@{ALGORITHM_VERSION}"
"""Nombre del triangulador en la procedencia (RF-006-26)."""

SUPER_SCALE = 1000.0
"""Lado del supertriángulo frente a la extensión de los puntos (A9: 10³)."""

PROGRESS_STEP = 4096
"""Puntos o aristas entre dos avisos de avance y consultas de cancelación."""

SEED = 20061017
"""Semilla del orden BRIO: la misma entrada da siempre la misma salida."""

HULL_FILTER_MIN = 64
"""Desde cuántos puntos se quitan, antes de calcular la envolvente convexa, los que están
claramente dentro (:func:`_hull_candidates`)."""

_EPSILON = 2.0**-53
_CCW_BOUND = (3.0 + 16.0 * _EPSILON) * _EPSILON
_ICC_BOUND = (10.0 + 96.0 * _EPSILON) * _EPSILON
_NEXT = (1, 2, 0)
_PREV = (2, 0, 1)


class TriangulatorError(TriangulationError, GisError):
    """El error de un triangulador (``gis.ports.TriangulationError``) con el código, el
    ``msgid``, los valores y el texto del catálogo, como un ``GisError``:
    ``gis.triangulation_input`` (datos sin triangulación) o ``gis.triangulation_contract``
    (salida que no cumple el contrato). Valores: ``name`` (el triangulador) y ``detail``."""


def _input_error(detail: str, *, field: str, value: object,
                 name: str = NAME) -> TriangulatorError:
    return TriangulatorError("gis.triangulation_input", obj="Triangulación", field=field,
                             value=value, name=name, detail=detail)


def _contract_error(name: str, detail: str, *, field: str, value: object) -> TriangulatorError:
    return TriangulatorError("gis.triangulation_contract", obj="Triangulación", field=field,
                             value=value, name=name, detail=detail)


# Predicados ------------------------------------------------------------------------------


def _sign(value: Fraction) -> int:
    return (value > 0) - (value < 0)


def _orient_exact(ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> int:
    fcx, fcy = Fraction(cx), Fraction(cy)
    acx, acy = Fraction(ax) - fcx, Fraction(ay) - fcy
    bcx, bcy = Fraction(bx) - fcx, Fraction(by) - fcy
    return _sign(acx * bcy - acy * bcx)


def orient2d(ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> int:
    """Signo exacto del giro de a, b, c: +1 antihorario (c a la izquierda de a→b), −1
    horario y 0 alineados. Filtro de Shewchuk y, si no decide, ``Fraction``."""
    detleft = (ax - cx) * (by - cy)
    detright = (ay - cy) * (bx - cx)
    det = detleft - detright
    bound = _CCW_BOUND * (abs(detleft) + abs(detright))
    if det > bound:
        return 1
    if -det > bound:
        return -1
    return _orient_exact(ax, ay, bx, by, cx, cy)


def _incircle_exact(ax: float, ay: float, bx: float, by: float, cx: float, cy: float,
                    dx: float, dy: float) -> int:
    fdx, fdy = Fraction(dx), Fraction(dy)
    adx, ady = Fraction(ax) - fdx, Fraction(ay) - fdy
    bdx, bdy = Fraction(bx) - fdx, Fraction(by) - fdy
    cdx, cdy = Fraction(cx) - fdx, Fraction(cy) - fdy
    alift = adx * adx + ady * ady
    blift = bdx * bdx + bdy * bdy
    clift = cdx * cdx + cdy * cdy
    return _sign(alift * (bdx * cdy - cdx * bdy) + blift * (cdx * ady - adx * cdy)
                 + clift * (adx * bdy - bdx * ady))


def incircle(ax: float, ay: float, bx: float, by: float, cx: float, cy: float,
             dx: float, dy: float) -> int:
    """Signo exacto de ``incircle``: con a, b, c antihorarios, +1 si d está estrictamente
    dentro de su círculo circunscrito, −1 si está fuera y 0 si está en él."""
    adx, ady = ax - dx, ay - dy
    bdx, bdy = bx - dx, by - dy
    cdx, cdy = cx - dx, cy - dy
    bdxcdy, cdxbdy = bdx * cdy, cdx * bdy
    cdxady, adxcdy = cdx * ady, adx * cdy
    adxbdy, bdxady = adx * bdy, bdx * ady
    alift = adx * adx + ady * ady
    blift = bdx * bdx + bdy * bdy
    clift = cdx * cdx + cdy * cdy
    det = alift * (bdxcdy - cdxbdy) + blift * (cdxady - adxcdy) + clift * (adxbdy - bdxady)
    permanent = ((abs(bdxcdy) + abs(cdxbdy)) * alift + (abs(cdxady) + abs(adxcdy)) * blift
                 + (abs(adxbdy) + abs(bdxady)) * clift)
    bound = _ICC_BOUND * permanent
    if det > bound:
        return 1
    if -det > bound:
        return -1
    return _incircle_exact(ax, ay, bx, by, cx, cy, dx, dy)


# Entradas --------------------------------------------------------------------------------


def _points(xy_local: object) -> np.ndarray:
    xy = np.asarray(xy_local)
    if xy.ndim != 2 or xy.shape[1] != 2:
        raise ValueError(f"los puntos de una triangulación son un array (n, 2), no {xy.shape}")
    if xy.dtype.kind != "f":
        raise TypeError(f"los puntos de una triangulación son float64, no {xy.dtype}")
    return np.ascontiguousarray(xy, dtype=np.float64)


def _constraints(edges: object, n: int) -> list[tuple[int, int]]:
    """Las aristas obligatorias como parejas (a, b), en su orden de entrada (una repetida, en
    el mismo sentido o al revés, no hace nada la segunda vez)."""
    array = np.asarray(edges)
    if array.size == 0:
        return []
    if array.ndim != 2 or array.shape[1] != 2:
        raise ValueError(f"las aristas obligatorias son un array (k, 2), no {array.shape}")
    if array.dtype.kind not in "iu":
        raise TypeError(f"las aristas obligatorias son índices enteros, no {array.dtype}")
    if int(array.min()) < 0 or int(array.max()) >= n:
        raise ValueError(f"una arista obligatoria usa un índice fuera de 0…{n - 1}")
    out: list[tuple[int, int]] = []
    for a, b in array.tolist():
        if a == b:
            raise ValueError(f"la arista obligatoria {a}–{b} une un vértice consigo mismo")
        out.append((a, b))
    return out


def _point_text(xy: np.ndarray, index: int) -> str:
    return f"({format_value(float(xy[index, 0]))}; {format_value(float(xy[index, 1]))})"


def _check_points(xy: np.ndarray, name: str = NAME) -> np.ndarray:
    """Comprueba que hay 3 puntos o más, finitos y distintos; devuelve el orden
    lexicográfico (x, y). Los errores llevan el nombre del triangulador ``name``."""
    n = len(xy)
    if n < 3:
        raise _input_error(f"hacen falta al menos 3 puntos y hay {n}", field="puntos", value=n,
                           name=name)
    bad = np.flatnonzero(~np.isfinite(xy).all(axis=1))
    if len(bad):
        index = int(bad[0])
        raise _input_error(f"el vértice {index} no tiene coordenadas finitas", field="vértice",
                           value=index, name=name)
    order = np.lexsort((xy[:, 1], xy[:, 0]))
    ordered = xy[order]
    same = np.flatnonzero((ordered[1:] == ordered[:-1]).all(axis=1))
    if len(same):
        first, second = sorted((int(order[same[0]]), int(order[same[0] + 1])))
        raise _input_error(f"los vértices {first} y {second} coinciden en "
                           f"{_point_text(xy, first)}", field="vértice", value=second,
                           name=name)
    return order


def _all_collinear(xy: np.ndarray, first: int, last: int) -> bool:
    """Todos los puntos en la recta de ``first`` a ``last`` (signo exacto)."""
    ax, ay = xy[first]
    bx, by = xy[last]
    detleft = (ax - xy[:, 0]) * (by - xy[:, 1])
    detright = (ay - xy[:, 1]) * (bx - xy[:, 0])
    det = detleft - detright
    if np.any(np.abs(det) > _CCW_BOUND * (np.abs(detleft) + np.abs(detright))):
        return False
    a, b = float(ax), float(ay)
    c, d = float(bx), float(by)
    return all(orient2d(a, b, c, d, px, py) == 0 for px, py in xy.tolist())


def _convex_hull(x: list[float], y: list[float], order: np.ndarray) -> list[int]:
    """Índices de la envolvente convexa en sentido antihorario desde el menor (x, y), con
    los puntos alineados del borde (cadena monótona de Andrew con signos exactos). No se
    llama con todos los puntos alineados."""

    def chain(indices: list[int]) -> list[int]:
        out: list[int] = []
        for p in indices:
            px, py = x[p], y[p]
            while len(out) >= 2:
                a, b = out[-2], out[-1]
                if orient2d(x[a], y[a], x[b], y[b], px, py) >= 0:
                    break
                out.pop()
            out.append(p)
        return out

    ordered = order.tolist()
    lower = chain(ordered)
    upper = chain(ordered[::-1])
    return lower[:-1] + upper[:-1]


def _hull_candidates(xy: np.ndarray, order: np.ndarray) -> np.ndarray:
    """``order`` (el orden lexicográfico de ``xy``) sin los puntos que están, con signo
    seguro, estrictamente a la izquierda de todos los lados del polígono de los extremos en
    8 direcciones (X, Y y las dos diagonales, en sentido antihorario; Akl y Toussaint, 1978).
    Un punto así está en el interior de la envolvente convexa de los vértices del polígono
    (si estuviera fuera o en su borde, los vectores del punto a los vértices cabrían en un
    semiplano y no podrían girar siempre a la izquierda y volver), y por tanto en el de la
    envolvente de todos: ni es vértice ni está alineado en un lado. Vale con cualquier punto
    de la entrada como extremo (aunque el redondeo de x ± y elija uno que no lo es) y con
    extremos repetidos; un punto dudoso se queda. Con todos los puntos, la cadena monótona
    recorre en Python cada uno (unos 1,2 µs por punto); aquí quedan los que rozan el borde."""
    if len(order) < HULL_FILTER_MIN:
        return order
    x, y = xy[:, 0], xy[:, 1]
    corners = [int(np.argmin(x)), int(np.argmin(x + y)), int(np.argmin(y)),
               int(np.argmax(x - y)), int(np.argmax(x)), int(np.argmax(x + y)),
               int(np.argmax(y)), int(np.argmin(x - y))]
    inside = np.ones(len(xy), dtype=bool)
    for a, b in zip(corners, corners[1:] + corners[:1], strict=True):
        if a == b:  # dos extremos en el mismo punto: ese lado no existe
            continue
        ax, ay = xy[a]
        bx, by = xy[b]
        left = (ax - x) * (by - y)
        right = (ay - y) * (bx - x)
        inside &= left - right > _CCW_BOUND * (np.abs(left) + np.abs(right))
    return order[~inside[order]]


def _hull(xy: np.ndarray, order: np.ndarray) -> list[int]:
    """La envolvente convexa de ``xy`` (como :func:`_convex_hull`, con los puntos alineados
    del borde) calculada solo con los candidatos de :func:`_hull_candidates`."""
    candidates = _hull_candidates(xy, order)
    local = _convex_hull(xy[candidates, 0].tolist(), xy[candidates, 1].tolist(),
                         np.arange(len(candidates)))
    return candidates[local].tolist()


def _hilbert_keys(xy: np.ndarray, bits: int = 16) -> np.ndarray:
    """Posición de cada punto en la curva de Hilbert de una retícula de 2^bits de lado."""
    low = xy.min(axis=0)
    span = float((xy.max(axis=0) - low).max()) or 1.0
    side = 1 << bits
    q = np.minimum(((xy - low) / span * (side - 1)).astype(np.int64), side - 1)
    x, y = q[:, 0].copy(), q[:, 1].copy()
    keys = np.zeros(len(xy), dtype=np.int64)
    s = side >> 1
    while s > 0:
        rx = (x & s) > 0
        ry = (y & s) > 0
        keys += s * s * ((3 * rx.astype(np.int64)) ^ ry.astype(np.int64))
        turn = ~ry
        mirror = turn & rx
        x[mirror] = side - 1 - x[mirror]
        y[mirror] = side - 1 - y[mirror]
        x[turn], y[turn] = y[turn], x[turn].copy()
        s >>= 1
    return keys


def _insertion_order(xy: np.ndarray) -> list[int]:
    """Orden BRIO: rondas al azar de 1, 2, 4… puntos (semilla fija) y, dentro de cada
    ronda, el orden de la curva de Hilbert."""
    n = len(xy)
    rank = np.empty(n, dtype=np.int64)
    rank[np.random.default_rng(SEED).permutation(n)] = np.arange(n)
    rounds = np.frexp((rank + 1).astype(np.float64))[1]
    return np.lexsort((_hilbert_keys(xy), rounds)).tolist()


# Triangulación ---------------------------------------------------------------------------


class _Twin(Exception):
    """El vértice que se inserta coincide con ``args[0]``."""


class _OnSegment(Exception):
    """Una arista obligatoria pasa por el vértice ``args[0]``."""


class _Crossing(Exception):
    """Una arista obligatoria cruza la obligatoria ``args``."""


class _Mesh:
    """Triangulación en listas planas: ``tri[3t + i]`` es el vértice i del triángulo t (en
    sentido antihorario) y ``adj[3t + i]``, el triángulo al otro lado de la arista opuesta a
    ese vértice (−1 en el borde del supertriángulo). ``vt[v]`` es un triángulo de v y
    ``fixed``, las aristas obligatorias (clave ``min · K + max``)."""

    __slots__ = ("adj", "fixed", "key", "tri", "vt", "x", "y")

    def __init__(self, x: list[float], y: list[float]) -> None:
        self.x = x
        self.y = y
        self.key = len(x)
        self.tri: list[int] = []
        self.adj: list[int] = []
        self.vt = [-1] * len(x)
        self.fixed: set[int] = set()

    def edge_key(self, u: int, v: int) -> int:
        return u * self.key + v if u < v else v * self.key + u

    # Bowyer–Watson -------------------------------------------------------------------

    def start(self, a: int, b: int, c: int) -> None:
        self.tri.extend((a, b, c))
        self.adj.extend((-1, -1, -1))
        self.vt[a] = self.vt[b] = self.vt[c] = 0

    def locate(self, px: float, py: float, t: int) -> int:
        """Un triángulo que contiene (px, py) (dentro o en su borde): caminata por
        visibilidad desde t, empezando cada paso por una arista distinta."""
        x, y, tri, adj = self.x, self.y, self.tri, self.adj
        previous = -1
        limit = len(tri) + 64
        for step in range(limit):
            b = 3 * t
            for j in (step % 3, (step + 1) % 3, (step + 2) % 3):
                nb = adj[b + j]
                if nb == previous or nb < 0:
                    continue
                u = tri[b + _NEXT[j]]
                v = tri[b + _PREV[j]]
                if orient2d(x[u], y[u], x[v], y[v], px, py) < 0:
                    previous = t
                    t = nb
                    break
            else:
                return t
        return self._locate_brute(px, py)

    def _locate_brute(self, px: float, py: float) -> int:
        x, y, tri = self.x, self.y, self.tri
        for t in range(len(tri) // 3):
            a, b, c = tri[3 * t:3 * t + 3]
            if (orient2d(x[a], y[a], x[b], y[b], px, py) >= 0
                    and orient2d(x[b], y[b], x[c], y[c], px, py) >= 0
                    and orient2d(x[c], y[c], x[a], y[a], px, py) >= 0):
                return t
        raise AssertionError("ningún triángulo contiene el punto")  # pragma: no cover

    def insert(self, p: int, start: int) -> int:
        """Inserta el vértice p (Bowyer–Watson): quita los triángulos cuyo círculo lo
        contiene estrictamente y une p con el borde de la cavidad. Devuelve un triángulo
        nuevo (donde empezar a buscar el siguiente) o lanza ``_Twin(v)`` si p coincide
        con el vértice v."""
        x, y, tri, adj, vt = self.x, self.y, self.tri, self.adj, self.vt
        px, py = x[p], y[p]
        t = self.locate(px, py, start)
        b = 3 * t
        for v in tri[b:b + 3]:
            if x[v] == px and y[v] == py:
                raise _Twin(v)
        cavity = [t]
        inside = {t}
        outside: set[int] = set()
        boundary: list[tuple[int, int, int, int]] = []
        stack = [t]
        while stack:
            c = stack.pop()
            cb = 3 * c
            for j in (0, 1, 2):
                nb = adj[cb + j]
                if nb in inside:
                    continue
                if nb >= 0 and nb not in outside:
                    nbb = 3 * nb
                    a0, a1, a2 = tri[nbb], tri[nbb + 1], tri[nbb + 2]
                    if incircle(x[a0], y[a0], x[a1], y[a1], x[a2], y[a2], px, py) > 0:
                        inside.add(nb)
                        cavity.append(nb)
                        stack.append(nb)
                        continue
                    outside.add(nb)
                slot = -1
                if nb >= 0:
                    nbb = 3 * nb
                    slot = 0 if adj[nbb] == c else (1 if adj[nbb + 1] == c else 2)
                boundary.append((tri[cb + _NEXT[j]], tri[cb + _PREV[j]], nb, slot))
        new = len(tri) // 3
        slots = cavity + [new, new + 1]
        tri.extend((0, 0, 0, 0, 0, 0))
        adj.extend((-1, -1, -1, -1, -1, -1))
        starting: dict[int, int] = {}
        for (u, v, nb, slot), s in zip(boundary, slots, strict=True):
            sb = 3 * s
            tri[sb] = u
            tri[sb + 1] = v
            tri[sb + 2] = p
            adj[sb + 2] = nb
            if nb >= 0:
                adj[3 * nb + slot] = s
            starting[u] = s
            vt[u] = s
        for s in slots:
            sb = 3 * s
            following = starting[tri[sb + 1]]
            adj[sb] = following
            adj[3 * following + 1] = s
        vt[p] = slots[0]
        return slots[-1]

    # Volteos y restricciones (Sloan) ---------------------------------------------------

    def find_edge(self, u: int, v: int) -> tuple[int, int] | None:
        """(t, j): el triángulo t con la arista u→v y j, el índice de su vértice opuesto;
        ``None`` si u y v no son vecinos. Recorre los triángulos alrededor de u."""
        tri, adj = self.tri, self.adj
        first = t = self.vt[u]
        backwards = False
        while True:
            b = 3 * t
            i = 0 if tri[b] == u else (1 if tri[b + 1] == u else 2)
            if tri[b + _NEXT[i]] == v:
                return t, _PREV[i]
            t = adj[b + (_PREV[i] if backwards else _NEXT[i])]
            if t == first:
                return None
            if t < 0:
                if backwards:
                    return None
                backwards = True
                t = first

    def flip(self, t: int, j: int) -> tuple[int, int]:
        """Voltea la arista opuesta al vértice j de t = (a, b, c), compartida con
        t2 = (d, c, b): quedan t = (a, b, d) y t2 = (d, c, a). Devuelve la arista nueva
        (a, d)."""
        tri, adj, vt = self.tri, self.adj, self.vt
        b0 = 3 * t
        j1, j2 = _NEXT[j], _PREV[j]
        a, b, c = tri[b0 + j], tri[b0 + j1], tri[b0 + j2]
        t2 = adj[b0 + j]
        b2 = 3 * t2
        k = 0 if tri[b2] != b and tri[b2] != c else (1 if tri[b2 + 1] != b and tri[b2 + 1] != c
                                                      else 2)
        d = tri[b2 + k]
        n_ab, n_ca = adj[b0 + j2], adj[b0 + j1]
        n_bd, n_dc = adj[b2 + _NEXT[k]], adj[b2 + _PREV[k]]
        tri[b0], tri[b0 + 1], tri[b0 + 2] = a, b, d
        adj[b0], adj[b0 + 1], adj[b0 + 2] = n_bd, t2, n_ab
        tri[b2], tri[b2 + 1], tri[b2 + 2] = d, c, a
        adj[b2], adj[b2 + 1], adj[b2 + 2] = n_ca, t, n_dc
        if n_bd >= 0:
            nb = 3 * n_bd
            adj[nb + (0 if adj[nb] == t2 else (1 if adj[nb + 1] == t2 else 2))] = t
        if n_ca >= 0:
            nb = 3 * n_ca
            adj[nb + (0 if adj[nb] == t else (1 if adj[nb + 1] == t else 2))] = t2
        vt[a] = vt[b] = vt[d] = t
        vt[c] = t2
        return a, d

    def _quad(self, u: int, w: int) -> tuple[int, int, int, int]:
        """(t, j, a, d) de la arista u–w: t = (a, u, w) con a en j, y d, el vértice
        opuesto del otro triángulo."""
        found = self.find_edge(u, w)
        if found is None:  # pragma: no cover - las aristas de las listas existen
            raise AssertionError(f"la arista {u}–{w} no existe")
        t, j = found
        tri = self.tri
        a = tri[3 * t + j]
        t2 = self.adj[3 * t + j]
        b2 = 3 * t2
        d = next(v for v in tri[b2:b2 + 3] if v != u and v != w)
        return t, j, a, d

    def _same_way(self, a: int, b: int, v: int) -> bool:
        """v, alineado con a y b, está del lado de b desde a."""
        x, y = self.x, self.y
        return ((x[v] > x[a]) == (x[b] > x[a]) and (x[v] < x[a]) == (x[b] < x[a])
                and (y[v] > y[a]) == (y[b] > y[a]) and (y[v] < y[a]) == (y[b] < y[a]))

    def crossings(self, a: int, b: int) -> list[tuple[int, int]]:
        """Las aristas (u, w) que cruza el segmento a–b, de a hacia b (u a su derecha y w
        a su izquierda). ``_OnSegment(v)`` si a–b pasa por el vértice v y ``_Crossing(u, w)``
        si cruza la arista obligatoria u–w."""
        x, y, tri, adj = self.x, self.y, self.tri, self.adj
        ax, ay, bx, by = x[a], y[a], x[b], y[b]
        first = t = self.vt[a]
        while True:
            base = 3 * t
            i = 0 if tri[base] == a else (1 if tri[base + 1] == a else 2)
            u, w = tri[base + _NEXT[i]], tri[base + _PREV[i]]
            side_u = orient2d(ax, ay, bx, by, x[u], y[u])
            if side_u == 0 and self._same_way(a, b, u):
                raise _OnSegment(u)
            if side_u < 0 < orient2d(ax, ay, bx, by, x[w], y[w]):
                break
            t = adj[base + _NEXT[i]]
            if t == first or t < 0:  # pragma: no cover - a es interior al supertriángulo
                raise AssertionError(f"el segmento {a}–{b} no sale de {a}")
        out: list[tuple[int, int]] = []
        while True:
            if self.edge_key(u, w) in self.fixed:
                raise _Crossing(u, w)
            out.append((u, w))
            base = 3 * t
            k = next(m for m in (0, 1, 2) if tri[base + m] != u and tri[base + m] != w)
            t = adj[base + k]
            base = 3 * t
            d = next(v for v in tri[base:base + 3] if v != u and v != w)
            if d == b:
                return out
            side = orient2d(ax, ay, bx, by, x[d], y[d])
            if side == 0:
                raise _OnSegment(d)
            if side < 0:
                u = d
            else:
                w = d

    def insert_constraint(self, a: int, b: int) -> None:
        """Hace de a–b una arista obligatoria (Sloan, 1993): volteos de las aristas que la
        cruzan y restauración de Delaunay de las aristas nuevas."""
        key = self.edge_key(a, b)
        if key in self.fixed:
            return
        if self.find_edge(a, b) is None and self.find_edge(b, a) is None:
            self._force(a, b)
        self.fixed.add(key)

    def _force(self, a: int, b: int) -> None:
        x, y = self.x, self.y
        ax, ay, bx, by = x[a], y[a], x[b], y[b]
        queue = deque(self.crossings(a, b))
        created: list[tuple[int, int]] = []
        limit = 50 * len(queue) ** 2 + 1000
        spins = 0
        while queue:
            spins += 1
            if spins > limit:  # pragma: no cover - Sloan termina con signos exactos
                raise AssertionError(f"los volteos para la arista {a}–{b} no terminan")
            u, w = queue.popleft()
            t, j, p, d = self._quad(u, w)
            if (orient2d(x[p], y[p], x[u], y[u], x[d], y[d]) <= 0
                    or orient2d(x[d], y[d], x[w], y[w], x[p], y[p]) <= 0):
                queue.append((u, w))  # cuadrilátero no convexo: más tarde
                continue
            self.flip(t, j)
            if (p not in (a, b) and d not in (a, b)
                    and orient2d(ax, ay, bx, by, x[p], y[p])
                    * orient2d(ax, ay, bx, by, x[d], y[d]) < 0):
                queue.append((p, d))
            else:
                created.append((p, d))
        self._restore(created, self.edge_key(a, b))

    def _restore(self, created: list[tuple[int, int]], skip: int) -> None:
        """Voltea las aristas nuevas que no son de Delaunay hasta que no quede ninguna."""
        x, y, fixed = self.x, self.y, self.fixed
        changed = True
        while changed:
            changed = False
            for position, (u, w) in enumerate(created):
                key = self.edge_key(u, w)
                if key == skip or key in fixed:
                    continue
                t, j, p, d = self._quad(u, w)
                if incircle(x[p], y[p], x[u], y[u], x[w], y[w], x[d], y[d]) > 0:
                    created[position] = self.flip(t, j)
                    changed = True

    def triangles(self, n: int) -> np.ndarray:
        """Los triángulos sin vértices del supertriángulo, cada uno desde su menor índice y
        en orden lexicográfico."""
        tri = np.array(self.tri, dtype=np.int64).reshape(-1, 3)
        tri = tri[(tri < n).all(axis=1)]
        first = tri.argmin(axis=1)
        rows = np.arange(len(tri))[:, None]
        tri = tri[rows, (first[:, None] + np.arange(3)) % 3]
        tri = tri[np.lexsort((tri[:, 2], tri[:, 1], tri[:, 0]))]
        return np.ascontiguousarray(tri, dtype=np.int32)


# Contrato --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CheckedInput:
    """La entrada comprobada de una triangulación (:func:`check_input`): ``xy`` float64
    (n, 2) contiguo (el mismo array si ya lo era: no se modifica), ``constraints`` (las
    aristas obligatorias como parejas, en su orden de entrada), ``hull`` (la envolvente
    convexa: índices antihorarios desde el menor (x, y), con los puntos alineados del borde)
    y ``name`` (el triangulador, para los mensajes)."""

    xy: np.ndarray
    constraints: tuple[tuple[int, int], ...]
    hull: tuple[int, ...]
    name: str


def _check(xy: np.ndarray, constraints: Sequence[tuple[int, int]], triangles: object,
           hull: Sequence[int], name: str) -> None:
    n = len(xy)
    hull = list(hull)
    tri = np.asarray(triangles)
    if tri.dtype != np.int32 or tri.ndim != 2 or (tri.size and tri.shape[1] != 3):
        raise _contract_error(name, f"los triángulos son {tri.dtype} {tri.shape}, no int32 "
                              "(m, 3)", field="triángulos", value=str(tri.shape))
    tri = tri.reshape(-1, 3).astype(np.int64)
    outside = np.flatnonzero(((tri < 0) | (tri >= n)).any(axis=1))
    if len(outside):
        row = int(outside[0])
        vertex = int(tri[row][(tri[row] < 0) | (tri[row] >= n)][0])
        raise _contract_error(name, f"el triángulo {row} usa el vértice {vertex}, que no es "
                              "de la entrada", field="vértice", value=vertex)
    unused = np.flatnonzero(np.bincount(tri.ravel(), minlength=n) == 0)
    if len(unused):
        vertex = int(unused[0])
        raise _contract_error(name, f"el vértice {vertex} no está en ningún triángulo",
                              field="vértice", value=vertex)
    p = xy[tri]
    left = (p[:, 0, 0] - p[:, 2, 0]) * (p[:, 1, 1] - p[:, 2, 1])
    right = (p[:, 0, 1] - p[:, 2, 1]) * (p[:, 1, 0] - p[:, 2, 0])
    doubtful = np.flatnonzero(left - right <= _CCW_BOUND * (np.abs(left) + np.abs(right)))
    for row in doubtful.tolist():
        a, b, c = tri[row].tolist()
        if orient2d(xy[a, 0], xy[a, 1], xy[b, 0], xy[b, 1], xy[c, 0], xy[c, 1]) <= 0:
            raise _contract_error(name, f"el triángulo {row} ({a}, {b}, {c}) no es "
                                  "antihorario", field="triángulo", value=row)
    # Cada arista dirigida, como el doble de la clave de su arista sin sentido más su sentido
    # (1 si va del índice mayor al menor): al ordenar, las dos mitades de una arista interior
    # quedan juntas. Una sola ordenación en lugar de np.unique y np.isin (unas 3 veces menos
    # con 600.000 triángulos: el contrato se comprueba tras la CDT de Blender, en el hilo
    # principal).
    directed = np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]])
    low = np.minimum(directed[:, 0], directed[:, 1])
    high = np.maximum(directed[:, 0], directed[:, 1])
    ordered = np.sort((low * n + high) * 2 + (directed[:, 0] > directed[:, 1]))
    repeated = np.flatnonzero(ordered[1:] == ordered[:-1])
    if len(repeated):
        key, backwards = divmod(int(ordered[repeated[0]]), 2)
        u, v = divmod(key, n)
        u, v = (v, u) if backwards else (u, v)
        raise _contract_error(name, f"la arista {u}–{v} está repetida: hay triángulos "
                              "solapados", field="arista", value=f"{u}–{v}")
    undirected = ordered >> 1
    paired = undirected[1:] == undirected[:-1]
    alone = np.ones(len(ordered), dtype=bool)
    alone[1:] &= ~paired
    alone[:-1] &= ~paired
    lone = ordered[alone]
    lone_low, lone_high = np.divmod(lone >> 1, n)
    border = np.where(lone & 1, lone_high * n + lone_low, lone_low * n + lone_high)
    expected = np.array([a * n + b for a, b in zip(hull, hull[1:] + hull[:1], strict=True)],
                        dtype=np.int64)
    area = float(np.sum(left - right)) / 2.0
    hx = xy[hull, 0] - xy[hull[0], 0]  # relativas a un vértice: sin cancelación
    hy = xy[hull, 1] - xy[hull[0], 1]
    hull_area = 0.5 * float(np.sum(hx * np.roll(hy, -1) - np.roll(hx, -1) * hy))
    if (len(border) != len(expected) or not np.array_equal(np.sort(border), np.sort(expected))
            or len(tri) != 2 * n - len(hull) - 2 or abs(area - hull_area) > 1e-9 * hull_area):
        raise _contract_error(name, f"los {len(tri)} triángulos no cubren la envolvente "
                              f"convexa de los {n} puntos", field="triángulos", value=len(tri))
    if constraints:
        pairs = np.array(constraints, dtype=np.int64)
        wanted = pairs.min(axis=1) * n + pairs.max(axis=1)
        at = np.minimum(np.searchsorted(undirected, wanted), len(undirected) - 1)
        missing = np.flatnonzero(undirected[at] != wanted)
        if len(missing):
            a, b = constraints[int(missing[0])]
            raise _contract_error(name, f"falta la arista obligatoria {a}–{b}",
                                  field="arista", value=f"{a}–{b}")


def check_input(xy_local: np.ndarray, edges: np.ndarray, *, name: str) -> CheckedInput:
    """La primera mitad del contrato de ``ports.Triangulator``: comprueba la entrada antes
    de triangular. ``xy_local`` float (n, 2) y ``edges`` enteros (k, 2) con índices válidos
    (si no, ``ValueError`` o ``TypeError``); al menos 3 puntos, finitos, distintos y no todos
    alineados (si no, ``TriangulatorError`` ``gis.triangulation_input`` con ``name``).
    Devuelve los puntos en float64, las aristas obligatorias y la envolvente convexa, para
    :func:`check_output`. Un triangulador que no puede recibir datos sin triangulación (la
    CDT de Blender) la llama antes."""
    xy = _points(xy_local)
    constraints = tuple(_constraints(edges, len(xy)))
    order = _check_points(xy, name)
    if _all_collinear(xy, int(order[0]), int(order[-1])):
        raise _input_error(f"los {len(xy)} puntos están alineados", field="puntos",
                           value=len(xy), name=name)
    return CheckedInput(xy, constraints, tuple(_hull(xy, order)), name)


def check_output(checked: CheckedInput, triangles: np.ndarray) -> None:
    """La segunda mitad del contrato: ``triangles`` es int32 (m, 3), solo con vértices de
    la entrada y todos usados, antihorarios (signo exacto), sin aristas repetidas, con el
    borde igual a la envolvente convexa (con sus puntos alineados), su área, m = 2n − h − 2
    y cada arista obligatoria presente. Si no, ``TriangulatorError``
    ``gis.triangulation_contract`` con el nombre de ``checked``. No comprueba la propiedad
    de Delaunay."""
    _check(checked.xy, checked.constraints, triangles, checked.hull, checked.name)


def check_contract(xy_local: np.ndarray, edges: np.ndarray, triangles: np.ndarray, *,
                   name: str) -> None:
    """El contrato de ``ports.Triangulator`` entero (:func:`check_input` y
    :func:`check_output`) para ``triangles``, con ``name`` en los mensajes."""
    check_output(check_input(xy_local, edges, name=name), triangles)


# Puerto ----------------------------------------------------------------------------------


class PureTriangulator:
    """Triangulación de Delaunay restringida en Python y numpy (``gis.ports.Triangulator``;
    ADR-0021). ``progress`` y ``cancelled`` (opcionales) son el avance y la cancelación del
    trabajo ``gis_triangulate`` (RF-006-28): se avisa y se consulta cada
    :data:`PROGRESS_STEP` puntos o aristas, y al cancelar se lanza ``JobCancelled``."""

    name: str = NAME

    def __init__(self, *, progress: Progress | None = None,
                 cancelled: Cancelled | None = None) -> None:
        self.progress = progress
        self.cancelled = cancelled

    def _tick(self, done: int, total: int, what: str) -> None:
        if self.cancelled is not None and self.cancelled():
            raise JobCancelled(f"Cancelado al triangular: {what}")
        if self.progress is not None:
            self.progress(done / total, f"Triangulando: {what}")

    def triangulate(self, xy_local: np.ndarray, edges: np.ndarray) -> np.ndarray:
        """Triángulos (int32 (m, 3), antihorarios, índices de ``xy_local``) de la
        triangulación de Delaunay restringida de ``xy_local`` (float64 (n, 2), relativas al
        GeoOrigin) con las aristas obligatorias ``edges`` (int (k, 2)). Ver el módulo."""
        checked = check_input(xy_local, edges, name=self.name)
        xy, constraints, hull = checked.xy, checked.constraints, list(checked.hull)
        n = len(xy)
        x, y = xy[:, 0].tolist(), xy[:, 1].tolist()
        low, high = xy.min(axis=0), xy.max(axis=0)
        cx, cy = (low + high) / 2.0
        reach = SUPER_SCALE * float((high - low).max())
        mesh = _Mesh(x + [cx - 3.0 * reach, cx + 3.0 * reach, cx],
                     y + [cy - reach, cy - reach, cy + 2.0 * reach])
        mesh.start(n, n + 1, n + 2)
        total = n + len(constraints)
        step = max(1, PROGRESS_STEP)
        last = 0
        for done, p in enumerate(_insertion_order(xy), start=1):
            try:
                last = mesh.insert(p, last)
            except _Twin as twin:  # pragma: no cover - _check_points ya lo descarta
                raise _input_error(f"los vértices {twin.args[0]} y {p} coinciden",
                                   field="vértice", value=p) from None
            if done % step == 0:
                self._tick(done, total, f"punto {done} de {n}")
        for done, (a, b) in enumerate(constraints, start=n + 1):
            self._insert(mesh, a, b)
            if done % step == 0:
                self._tick(done, total, f"arista obligatoria {done - n} de {len(constraints)}")
        for a, b in zip(hull, hull[1:] + hull[:1], strict=True):
            if mesh.find_edge(a, b) is None:
                self._insert(mesh, a, b)
        triangles = mesh.triangles(n)
        check_output(checked, triangles)
        self._tick(total, total, "terminado")
        return triangles

    @staticmethod
    def _insert(mesh: _Mesh, a: int, b: int) -> None:
        try:
            mesh.insert_constraint(a, b)
        except _OnSegment as problem:
            raise _input_error(f"la arista obligatoria {a}–{b} pasa por el vértice "
                               f"{problem.args[0]}", field="arista", value=f"{a}–{b}") from None
        except _Crossing as problem:
            u, w = sorted(problem.args)
            raise _input_error(f"las aristas obligatorias {a}–{b} y {u}–{w} se cruzan",
                               field="arista", value=f"{a}–{b}") from None

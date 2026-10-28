# SPDX-License-Identifier: GPL-3.0-or-later
"""Polígonos de una capa: validarlos, recortarlos por el ámbito y repartir cada celda entre ellos
(spec 011; RF-011-01, RF-011-07, RF-011-08; plan 011 A6 y D-21).

Una cubicación se reparte por **dominios** (los polígonos de una capa y el campo que los nombra:
fase, zona o sector) y, si se declara, solo dentro de un **ámbito** (otro polígono). Antes de
cubicar, la capa se comprueba (RF-011-08) y cada dominio que cruza el borde del ámbito se
sustituye por su **recorte exacto** (D-21); con esas aristas, la fracción exacta de cada celda
(``reserves.coverage``, A5) reparte la celda entre los dominios y la fila «Fuera de los
dominios».

La geometría (validación, solapes y recorte por clasificación de aristas, A6) está en
``gis.polygons`` desde la spec 012 (plan 012 §5.6, D-18 y T2), con errores neutros; aquí quedan
la API de la cubicación sobre ella, sin cambiar un bit de sus resultados:

- :class:`Polygon`: un polígono de la capa (``fid``, el valor de su campo y sus anillos
  ABSOLUTOS; el primero, el exterior); :func:`domain_polygons`, los de las entidades de una capa
  de dominios del proyecto (``gis.store.DomainFeature``), uno por parte (T32).
- :func:`problems` y :func:`validate`: cada polígono **simple**, **con área**, con sus huecos
  dentro del exterior y fuera de los demás huecos, y con el campo lleno; ningún par **solapado**
  (más de 1 mm²). La lista dice el ``fid``, el valor del campo, el problema y, en un solape, su
  área en m² (:class:`Problem`); :func:`validate` la lanza como ``res.domains_invalid``
  (:class:`DomainsError`), y :func:`problem_steps` la busca por pasos (uno por polígono y por
  par que recortar: los de una cubicación, A10).
- :func:`scope_problems`, :func:`scope_problem_steps` y :func:`validate_scope`: lo mismo para
  un **ámbito** (RF-011-01; T37), sin el campo (no lo tiene), con los códigos ``res.scope_*``
  y el error ``res.scope_invalid`` (:class:`ScopeError`): dos partes que se solapan contarían
  dos veces el solape, y una que se corta a sí misma daría pesos con signo.
- :func:`overlaps`: los pares que se solapan, con el área del solape.
- :func:`clip_to_scope`: las aristas orientadas de ``polígono ∩ ámbito``.
- :func:`domain_edges` y :func:`scope_edges`: las aristas de cada dominio (los polígonos con el
  mismo valor, juntos; recortados por el ámbito si lo hay) y las del ámbito, relativas a la
  esquina suroeste de la rejilla, listas para :func:`weights`.
- :func:`weights`: las entradas (celda, dominio, peso) de una banda de filas, con la fila «Fuera
  de los dominios» = fracción del ámbito − Σ fracciones de los dominios (1 − Σ sin ámbito): las
  filas suman la del ámbito por construcción (RF-011-07).

Python puro con numpy (nivel 9). Las entradas del usuario solo se leen.
"""

from __future__ import annotations

import math
from collections.abc import Generator, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from ..core.i18n import format_number
from ..gis import polygons as geometry
from ..gis.polygons import AREA_TOLERANCE_M2, TOLERANCE_M, Overlap
from .coverage import FRACTION_EPSILON, band_coverage, polygon_edges
from .messages import ResError, render

if TYPE_CHECKING:
    from ..gis.grid import Grid
    from ..gis.store import DomainFeature

__all__ = [
    "AREA_TOLERANCE_M2",
    "TOLERANCE_M",
    "DomainEdges",
    "DomainsError",
    "Overlap",
    "Polygon",
    "Problem",
    "ScopeError",
    "Weights",
    "clip_to_scope",
    "domain_edges",
    "domain_polygons",
    "overlaps",
    "problem_steps",
    "problems",
    "scope_edges",
    "scope_problem_steps",
    "scope_problems",
    "validate",
    "validate_scope",
    "weights",
]


# Datos ----------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class Polygon:
    """Un polígono de una capa (dominios o ámbito): ``fid``, el valor del campo que lo nombra
    (``value``; vacío, ``""``) y sus anillos ABSOLUTOS en float64 (``rings``: arrays ``(k, 2)``,
    cerrados o no; el primero, el exterior, y los demás, sus huecos, en cualquier sentido)."""

    fid: int
    value: str
    rings: tuple[np.ndarray, ...]


@dataclass(frozen=True, slots=True)
class Problem:
    """Un problema de un polígono de la capa (RF-011-08): su código de nota (``res.domain_*``),
    ``fid`` y valor del campo, y en un solape, el otro polígono y el área (m²)."""

    code: str
    fid: int
    value: str
    other_fid: int | None = None
    other_value: str | None = None
    area_m2: float | None = None

    def text(self, attribute: str, language: str = "es") -> str:
        """El problema como un elemento de la lista de ``res.domains_invalid``, con el nombre
        del campo (``attribute``), en ``language`` (el área, en el formato de la interfaz)."""
        area = None if self.area_m2 is None else _area_text(self.area_m2)
        return render(self.code, language=language, fid=self.fid, domain=self.value,
                      attribute=attribute, other_fid=self.other_fid,
                      other_domain=self.other_value, area=area)


class DomainsError(ResError):
    """``res.domains_invalid``: la capa de dominios no sirve; ``problems`` es la lista
    (:class:`Problem`) y el valor del error, cuántos problemas hay."""

    def __init__(self, found: Sequence[Problem], *, field: str, layer: str) -> None:
        found = tuple(found)
        super().__init__("res.domains_invalid", obj=f"Capa de dominios «{layer}»", field=field,
                         value=len(found), layer=layer, attribute=field,
                         problems="; ".join(problem.text(field) for problem in found))
        self.problems = found


class ScopeError(ResError):
    """``res.scope_invalid``: el ámbito no sirve (RF-011-01; T37); ``problems`` es la lista
    (:class:`Problem`, códigos ``res.scope_*``) y el valor del error, cuántos problemas hay."""

    def __init__(self, found: Sequence[Problem], *, layer: str) -> None:
        found = tuple(found)
        super().__init__("res.scope_invalid", obj=f"Capa del ámbito «{layer}»", field="ámbito",
                         value=len(found), layer=layer,
                         problems="; ".join(problem.text("") for problem in found))
        self.problems = found


@dataclass(frozen=True, slots=True, eq=False)
class DomainEdges:
    """Un dominio (el valor del campo) y las aristas orientadas de sus polígonos, recortados por
    el ámbito si lo hay, ``(n, 2, 2)`` en metros relativos a la esquina suroeste de la rejilla."""

    value: str
    edges: np.ndarray


@dataclass(frozen=True, slots=True, eq=False)
class Weights:
    """El reparto de las celdas de una banda de filas ``[start, stop)`` (la fila 0 es la del
    norte).

    - ``scope``: ``(stop − start, ncols)``, la fracción de cada celda dentro del ámbito; ``None``
      sin ámbito (cada celda cuenta entera).
    - Las entradas (celda, dominio, peso): ``rows`` y ``cols`` (int64, de la rejilla),
      ``domain`` (int64: la posición del dominio, o ``count`` para «Fuera de los dominios») y
      ``weight`` (float64). En cada celda suman su fracción del ámbito (1 sin él) salvo el
      redondeo. Sin dominios (``count == 0``) no hay entradas."""

    start: int
    stop: int
    scope: np.ndarray | None
    rows: np.ndarray
    cols: np.ndarray
    domain: np.ndarray
    weight: np.ndarray
    count: int

    @property
    def outside(self) -> int:
        """El índice de la fila «Fuera de los dominios» en ``domain``."""
        return self.count


def domain_polygons(features: Sequence[DomainFeature], field: str) -> tuple[Polygon, ...]:
    """Los polígonos de la capa de dominios ``features`` (sus entidades,
    ``gis.store.DomainFeature``: número, atributos por columna y polígonos) para repartir por su
    columna ``field``
    (RF-011-07; plan D-32): uno por parte de cada entidad, en su orden, con el número de la
    entidad y el valor de su campo como texto (un número, sus cifras; sin valor, ``""``, que
    rechaza :func:`validate`: RF-011-08) y sus anillos tal como llegan (no se copian).
    ``ValueError`` si alguna entidad no tiene la columna ``field``."""
    found: list[Polygon] = []
    for feature in features:
        if field not in feature.attributes:
            raise ValueError(f"la entidad {feature.fid} de la capa de dominios no tiene el campo "
                             f"«{field}»: tiene {', '.join(map(str, feature.attributes))}")
        value = feature.attributes[field]
        text = "" if value is None else str(value)
        found.extend(Polygon(int(feature.fid), text, tuple(part)) for part in feature.polygons)
    return tuple(found)


# Validación y solapes (RF-011-08) --------------------------------------------------------------


def problems(polygons: Sequence[Polygon]) -> tuple[Problem, ...]:
    """Los problemas de la capa (RF-011-08), en el orden de sus polígonos y después los
    solapes: el campo vacío, «se corta a sí mismo», «no tiene área», un hueco fuera de su
    contorno o dentro de otro, y cada par que se solapa en más de 1 mm², con su área. Los
    solapes se buscan entre los polígonos de geometría válida."""
    return geometry.drain(problem_steps(polygons))


def problem_steps(polygons: Sequence[Polygon]) -> Generator[None, None, tuple[Problem, ...]]:
    """:func:`problems` por pasos (plan 011 A10; RNF-011-04): un paso por polígono y otro por
    cada par de polígonos cuyas cajas se tocan (recortar un par es lo más lento: unos 11 ms con
    miles de vértices); lo mismo que :func:`problems` en ``StopIteration.value``."""
    return (yield from _problem_steps(polygons, domains=True))


def scope_problems(polygons: Sequence[Polygon]) -> tuple[Problem, ...]:
    """Los problemas de un ámbito (RF-011-01, con la regla de RF-011-08; T37): los de
    :func:`problems` salvo el campo vacío (un ámbito no tiene campo), con los códigos
    ``res.scope_*``. Dos partes que se solapan contarían dos veces el solape, y una que se corta
    a sí misma daría pesos con signo."""
    return geometry.drain(scope_problem_steps(polygons))


def scope_problem_steps(polygons: Sequence[Polygon]
                        ) -> Generator[None, None, tuple[Problem, ...]]:
    """:func:`scope_problems` por pasos, como :func:`problem_steps`."""
    return (yield from _problem_steps(polygons, domains=False))


def _problem_steps(polygons: Sequence[Polygon], *, domains: bool
                   ) -> Generator[None, None, tuple[Problem, ...]]:
    """Los problemas neutros de ``gis.polygons`` con los códigos y los datos de la capa: por
    cada polígono, el campo vacío (de los dominios) y el de su geometría; después, los
    solapes."""
    prefix = "res.domain_" if domains else "res.scope_"
    found = yield from geometry.problem_steps([polygon.rings for polygon in polygons])
    shape = {item.index: item.problem for item in found if item.problem != "overlap"}
    listed: list[Problem] = []
    for index, polygon in enumerate(polygons):
        value = _value(polygon)
        if domains and not value.strip():
            listed.append(Problem("res.domain_value_empty", polygon.fid, value))
        if index in shape:
            listed.append(Problem(prefix + shape[index], polygon.fid, value))
    for item in found:
        if item.problem == "overlap" and item.other is not None:
            first, second = polygons[item.index], polygons[item.other]
            listed.append(Problem(prefix + "overlap", first.fid, _value(first), second.fid,
                                  _value(second), item.area_m2))
    return tuple(listed)


def validate(polygons: Sequence[Polygon], *, field: str, layer: str) -> None:
    """Comprueba la capa de dominios ``layer`` para repartir por su campo ``field``
    (RF-011-08): con algún problema (:func:`problems`), :class:`DomainsError`
    (``res.domains_invalid``, con la lista) y no se cubica con ella."""
    found = problems(polygons)
    if found:
        raise DomainsError(found, field=field, layer=layer)


def validate_scope(polygons: Sequence[Polygon], *, layer: str) -> None:
    """Comprueba el ámbito de la capa ``layer`` (:func:`scope_problems`): con algún problema,
    :class:`ScopeError` (``res.scope_invalid``, con la lista) y no se cubica con él."""
    found = scope_problems(polygons)
    if found:
        raise ScopeError(found, layer=layer)


def overlaps(polygons: Sequence[Polygon]) -> tuple[Overlap, ...]:
    """Los pares de ``polygons`` (válidos: simples y con área) que se solapan en más de
    :data:`AREA_TOLERANCE_M2`, con el área del solape (m²), por posiciones. Dos que comparten un
    lado (también en parte, o a ≤ 1 mm) o que solo se tocan no se solapan."""
    return geometry.overlaps([polygon.rings for polygon in polygons])


# Recorte (A6) ---------------------------------------------------------------------------------


def clip_to_scope(polygon: Polygon, scope: Polygon, *, origin: Sequence[float]) -> np.ndarray:
    """Las aristas orientadas ``(n, 2, 2)`` del borde de ``polygon ∩ scope`` (el exterior
    antihorario y los huecos horarios), en metros relativos a ``origin`` (``(x, y)`` absolutos;
    para la fracción de celda, la esquina suroeste de la rejilla, ``(grid.west,
    grid.extent.ymin)``). Un polígono entero dentro del ámbito da sus aristas; entero fuera,
    ninguna. Los dos, válidos (:func:`validate`)."""
    return geometry.clip(polygon.rings, scope.rings, origin=origin)


def domain_edges(polygons: Sequence[Polygon], grid: Grid, *,
                 scope: Polygon | Sequence[Polygon] | None = None) -> tuple[DomainEdges, ...]:
    """Las aristas de cada dominio (los polígonos con el mismo valor, juntos; en el orden en que
    aparece cada valor), relativas a la esquina suroeste de ``grid``: con un ámbito (uno o varios
    polígonos que no se solapan), su recorte por él (:func:`clip_to_scope`); sin él, las del
    polígono (``coverage.polygon_edges``)."""
    corner = _corner(grid)
    parts = _parts(scope)
    groups: dict[str, list[np.ndarray]] = {}
    for polygon in polygons:
        if parts is None:
            edges = polygon_edges(polygon.rings, grid)
        else:
            edges = _concatenate([clip_to_scope(polygon, part, origin=corner) for part in parts])
        groups.setdefault(_value(polygon), []).append(edges)
    return tuple(DomainEdges(value, _concatenate(items)) for value, items in groups.items())


def scope_edges(scope: Polygon | Sequence[Polygon], grid: Grid) -> np.ndarray:
    """Las aristas orientadas del ámbito (uno o varios polígonos que no se solapan), relativas a
    la esquina suroeste de ``grid``, con la misma copia de trabajo que usa el recorte."""
    corner = _corner(grid)
    return _concatenate([geometry.local_edges(part.rings, corner)
                         for part in _parts(scope) or ()])


# Pesos de una banda (A5, RF-011-07) ----------------------------------------------------------


def weights(domains: Sequence[np.ndarray], scope: np.ndarray | None, grid: Grid,
            rows: slice) -> Weights:
    """Las entradas (celda, dominio, peso) de la banda de filas ``rows`` de ``grid`` (sin paso):
    ``domains``, las aristas de cada dominio (:func:`domain_edges`); ``scope``, las del ámbito
    (:func:`scope_edges`) o ``None``. Cada celda recibe la fracción exacta de su área dentro de
    cada dominio y, en «Fuera de los dominios» (``domain == count``), la del ámbito (1 sin él)
    menos la suma de las de los dominios; con |peso| ≤ ``coverage.FRACTION_EPSILON``, no se
    da. Por bandas sale bit a bit lo mismo que de una vez."""
    start, stop, step = rows.indices(grid.nrows)
    if step != 1:
        raise ValueError(f"Una banda son filas seguidas, no con paso {step}")
    stop = max(stop, start)
    band = slice(start, stop)
    shape = (stop - start, grid.ncols)
    fraction = None
    if scope is not None:
        fraction = np.zeros(shape)
        cells = band_coverage(scope, grid, band)
        fraction[cells.rows - start, cells.cols] = cells.fraction
    parts: list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = []
    if len(domains):
        covered = np.zeros(shape)
        for number, edges in enumerate(domains):
            cells = band_coverage(edges, grid, band)
            covered[cells.rows - start, cells.cols] += cells.fraction
            parts.append((cells.rows, cells.cols,
                          np.full(cells.rows.size, number, dtype=np.int64), cells.fraction))
        outside = (1.0 if fraction is None else fraction) - covered
        found_rows, found_cols = np.nonzero(np.abs(outside) > FRACTION_EPSILON)
        parts.append(((found_rows + start).astype(np.int64), found_cols.astype(np.int64),
                      np.full(found_rows.size, len(domains), dtype=np.int64),
                      np.ascontiguousarray(outside[found_rows, found_cols])))
    columns = [np.concatenate([part[k] for part in parts]) if parts else
               np.zeros(0, dtype=np.float64 if k == 3 else np.int64) for k in range(4)]
    return Weights(start, stop, fraction, columns[0], columns[1], columns[2], columns[3],
                   len(domains))


# Ayudas -----------------------------------------------------------------------------------------


def _value(polygon: Polygon) -> str:
    return "" if polygon.value is None else str(polygon.value)


def _area_text(area: float) -> str:
    """El área (m²) como texto: con dos decimales, o con los que hagan falta (hasta seis) para
    que se vea un área menor que 0,01 m²."""
    decimals = 2
    if 0.0 < abs(area) < 0.01:
        decimals = min(6, 1 - math.floor(math.log10(abs(area))))
    return format_number(area, decimals)


def _corner(grid: Grid) -> np.ndarray:
    return np.array([grid.west, grid.extent.ymin], dtype=np.float64)


def _parts(scope: Polygon | Sequence[Polygon] | None) -> tuple[Polygon, ...] | None:
    if scope is None:
        return None
    if isinstance(scope, Polygon):
        return (scope,)
    return tuple(scope)


def _concatenate(edges: list[np.ndarray]) -> np.ndarray:
    if not edges:
        return np.zeros((0, 2, 2), dtype=np.float64)
    return np.ascontiguousarray(np.concatenate(edges))

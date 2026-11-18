# SPDX-License-Identifier: GPL-3.0-or-later
"""Casos de referencia de la detección de acopios (spec 016, T10, hito H1; HU-016-1; RF-016-01, RF-016-02,
RF-016-03, RF-016-06, RF-016-07, RF-016-08, RF-016-09; CE-016-01 y CE-016-02; E1 en el dominio; D-3, D-11, D-16,
D-17, D-18, D-20).

Verifica **de forma independiente** lo que hicieron T05 a T09 (``design.morphology`` y ``design.stockpiles``:
A1 a A5): cada cifra esperada sale de una cuenta cerrada del enunciado o de un cálculo a mano (bucles de Python,
aritmética racional y las implementaciones de ``tests.support.design_oracles``) y **ningún** valor esperado se
calcula llamando al código bajo prueba. Todo es sintético y en el dominio (sin Blender ni proyecto) con celdas de
1 m: con 2 m el par de E1 es pequeño para la celda (``docs/trampas.md`` §2). Las entradas son los valores por
defecto del programa (``design.params``, D-3; ``res.anthropic_presence_m``, D-17), que la primera prueba compara
con los que escribe la spec.

Tolerancias de D-11: **≤ 10⁻⁹** (m o relativo) frente al cálculo a mano **en las mismas celdas y con el mismo
plano**; **plano ≤ 10⁻⁶ m** con atípicos en la corona (CE-016-02: el cono); y **≤ 1 %** del volumen analítico con
celdas de 1 m, descontado el anillo de menos del umbral de huella (lo que domina la diferencia).

- **El cálculo a mano** (:func:`grow_by_hand`): A2 y A3 enteros —la marca ampliada, y en cada vuelta la corona, sus
  celdas llanas, el plano en racionales exactos (``design_oracles.hand_plane``) y la huella por una búsqueda en
  anchura (``hand_footprint``)—. Es el ``hand_grow`` de ``test_stockpile_footprint`` con las distancias por fuerza
  bruta sobre **el borde** de cada máscara (la celda más próxima a una de fuera siempre es del borde) y sobre una
  ventana, para que cueste ≈ 0,1 s y no ≈ 13 s; ``OracleTest`` lo compara con el original y con la fuerza bruta, y
  ``milestone_ref_stockpiles`` (paso «hito») con las huellas reales de los casos.
- **CE-016-02** (:class:`ConeTest`): el tronco de cono sobre un plano de 3° con ocho celdas atípicas en la corona
  (más allá del residuo máximo): el plano a ≤ 10⁻⁶ m del sintético en toda la ventana, la huella = las celdas del
  cono a más de 0,3 m, el volumen = la suma de sus alturas (a ≤ 10⁻⁹) y el analítico por encima del umbral (≤ 1 %);
  y sobre uno de 8° con la inclinación máxima de 4°: el aviso con las dos inclinaciones, la nota, el azimut
  conservado, el plano en el cuantil de apoyo y el volumen sobre él, a ≤ 10⁻⁹ del cálculo a mano.
- **CE-016-01** (:class:`SurveyTest`): el levantamiento de 5 acopios marcados y 20 montículos sin marca (400 × 400
  celdas): una sola operación da los 5 acopios y **solo los 8** candidatos que pasan los filtros (clasificados a
  mano: la apertura de ⌀ 31 m por fuerza bruta con enteros y las zonas por una búsqueda en anchura), cada acopio y
  cada candidato con su plano, su huella y su volumen a ≤ 10⁻⁹ del cálculo a mano y a ≤ 1 % del analítico por anillos;
  **ninguna salida** da los 12 que no. «Cambiar un umbral deja obsoleta la operación entera» pide proyecto: es de la
  T14.
- **RF-016-03** (:class:`OwnBaseTest`): una marca con la superficie de un levantamiento anterior como base (la
  terraza de 0,5 m queda bajo la base): sin plano, corona ni ajuste, la base idéntica, el espesor = la altura del
  montón y el volumen = la suma de anillos, exacto.
- **E1** (:class:`SurveyTest`, :class:`PairTest`): los dos acopios que se tocan (436 celdas comunes, repartidas por
  la recta de contacto de las marcas: x = 110 m en el levantamiento y x = 60 m en la ventana del par; el aviso con
  las dos marcas y el área), los candidatos y el terreno sin acopios.
"""

from __future__ import annotations

import functools
import math
import random
import unittest
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

import numpy as np

from tests.support import design_oracles as oracles
from tests.support import quarry_fixtures as qfx
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.unit.design.test_morphology import brute
from tests.unit.design.test_stockpile_footprint import SPIKES, hand_grow, small_scene

gis = import_geoblender("gis")
stockpiles = import_geoblender("design.stockpiles")
design_params = import_geoblender("design.params")
reserve_params = import_geoblender("reserves.params")

AT_EDGE = "des.stockpile_footprint_at_edge"
SEVERAL = "des.stockpile_several_zones"
FEW_FLAT = "des.stockpile_crown_few_flat"
TILT = "des.stockpile_tilt_limited"
NOT_CONVERGED = "des.stockpile_not_converged"
SHARED = "des.stockpile_shared_cells"

EXACT = 1e-9
"""D-11: m o relativo, frente al cálculo a mano en las mismas celdas."""
PLANE_TOL_M = 1e-6
"""D-11: el plano recuperado con atípicos en la corona, frente al sintético (CE-016-02)."""
ANALYTIC = 0.01
"""D-11: el volumen frente al analítico por encima del umbral, con celdas de 1 m."""

# Los valores de D-3 tal como los escribe la spec (ADOPTADO «sin confirmar»; la inclinación máxima y el cuantil de
# apoyo, HIPÓTESIS) y la apertura de P-6.
SPEC_D3: dict[str, float | int] = {
    "margin_m": 10.0, "crown_inner_m": 1.0, "crown_outer_m": 3.0, "crown_slope_deg": 12.0,
    "crown_flat_min_m2": 10.0, "max_residual_m": 1.0, "fit_rounds": 4, "turns": 6, "tilt_max_deg": 4.0,
    "support_quantile": 0.6}
SPEC_CANDIDATES: dict[str, float] = {
    "open_diameter_m": 31.0, "min_height_m": 2.0, "min_area_m2": 150.0, "max_area_m2": 20_000.0}
SPEC_THRESHOLD_M = 0.30
"""El umbral único de presencia de antrópicas de la 011 (D-17)."""

_STOCKPILE = design_params.entity_params("stockpile")
D3 = {name: _STOCKPILE.template(name).default for name in SPEC_D3}
"""Los valores por defecto del programa de la detección: la entrada de todos los casos."""
CANDIDATE_D3 = {name: _STOCKPILE.template(name).default for name in SPEC_CANDIDATES}
THRESHOLD_M = float(reserve_params.default(reserve_params.ANTHROPIC_PRESENCE))


def footprint_params() -> Any:
    """Los umbrales de A2 y A3 con los valores por defecto del programa y el umbral de la 011."""
    plane = stockpiles.PlaneParams(
        crown_inner_m=D3["crown_inner_m"], crown_outer_m=D3["crown_outer_m"], crown_slope_deg=D3["crown_slope_deg"],
        crown_flat_min_m2=D3["crown_flat_min_m2"], max_residual_m=D3["max_residual_m"],
        fit_rounds=D3["fit_rounds"], tilt_max_deg=D3["tilt_max_deg"], support_quantile=D3["support_quantile"])
    return stockpiles.FootprintParams(plane=plane, margin_m=D3["margin_m"], turns=D3["turns"],
                                      threshold_m=THRESHOLD_M)


def candidate_params() -> Any:
    """Los umbrales de A4 con los valores por defecto del programa."""
    return stockpiles.CandidateParams(footprint=footprint_params(), **CANDIDATE_D3)


# --- Lo que se sabe de los datos, a mano ----------------------------------------------------------------------------


def box_mask(grid: Any, box: tuple[float, float, float, float]) -> np.ndarray:
    """Las celdas de ``grid`` con el centro **dentro** de la caja local ``(izquierda, abajo, derecha, arriba)`` (m
    desde la esquina suroeste de los casos), contadas a mano: el centro de la columna ``c`` está en ``(c + ½)·dx`` y
    el de la fila ``r`` (la 0 es el norte) en ``(filas − r − ½)·dy``."""
    if grid.west != sdata.BASE[0] or grid.north - grid.nrows * grid.dy != sdata.BASE[1]:
        raise ValueError("la rejilla no parte de la esquina suroeste de los casos")
    left, bottom, right, top = box
    columns = [c for c in range(grid.ncols) if left < (c + 0.5) * grid.dx < right]
    rows = [r for r in range(grid.nrows) if bottom < (grid.nrows - r - 0.5) * grid.dy < top]
    found = np.zeros(grid.shape, dtype=bool)
    found[np.ix_(rows, columns)] = True
    return found


def hand_height(mound: Any, x: float, y: float) -> float:
    """La altura (m) sobre el plano de un tronco de pirámide o de cono en ``(x, y)`` locales: baja desde ``height`` en
    la cima hasta 0 en el pie con la pendiente ``height / (pie − cima)``; la distancia es la de Chebyshev (pirámide)
    o la euclídea (cono)."""
    dx, dy = abs(x - mound.cx), abs(y - mound.cy)
    distance = max(dx, dy) if mound.shape == "pyramid" else math.hypot(dx, dy)
    if distance >= mound.foot:
        return 0.0
    return min(mound.height, mound.height / (mound.foot - mound.top) * (mound.foot - distance))


def hand_heights(grid: Any, mounds: Iterable[Any]) -> np.ndarray:
    """La altura de ``mounds`` (donde dos se solapan, la mayor) en los centros de ``grid``, celda a celda y solo en la
    caja del pie de cada uno."""
    found = np.zeros(grid.shape)
    for mound in mounds:
        left, bottom, right, top = mound.foot_box
        for r in range(max(grid.nrows - math.ceil(top / grid.dy), 0), min(grid.nrows - math.floor(bottom / grid.dy),
                                                                           grid.nrows)):
            for c in range(max(math.floor(left / grid.dx), 0), min(math.ceil(right / grid.dx), grid.ncols)):
                x, y = (c + 0.5) * grid.dx, (grid.nrows - r - 0.5) * grid.dy
                found[r, c] = max(found[r, c], hand_height(mound, x, y))
    return found


def hand_plane_values(grid: Any, tilt_deg: float, pivot: tuple[float, float], z_pivot: float) -> np.ndarray:
    """El plano de ``tilt_deg`` ° con su máxima pendiente al azimut de la cantera (desde el norte, en sentido horario)
    por ``z_pivot`` en ``pivot`` (locales), en los centros de ``grid``."""
    tangent = math.tan(math.radians(tilt_deg))
    east, north = tangent * math.sin(math.radians(sdata.AZIMUTH_DEG)), tangent * math.cos(
        math.radians(sdata.AZIMUTH_DEG))
    x = (np.arange(grid.ncols) + 0.5) * grid.dx
    y = grid.nrows * grid.dy - (np.arange(grid.nrows) + 0.5) * grid.dy
    return z_pivot + east * (x[None, :] - pivot[0]) + north * (y[:, None] - pivot[1])


def pyramid_rings(foot: float, top: float, height: float, threshold: float) -> tuple[int, Fraction]:
    """Las celdas y el volumen (m³, exacto) sobre el plano de un tronco de pirámide de semilado ``foot`` en el pie y
    ``top`` en la cima, de altura ``height``, con celdas de 1 m y el centro en una esquina de celda, que pasan de
    ``threshold``. **Por anillos**: el anillo ``n`` (de 1 a ``foot``, desde el centro) tiene ``(2n)² − (2n − 2)² =
    8n − 4`` celdas a la distancia de Chebyshev ``n − ½``, donde la altura es ``mín(height, pendiente·(foot − n +
    ½))``. Racionales: sin redondeos."""
    slope = Fraction(height) / (Fraction(foot) - Fraction(top))
    cells, volume = 0, Fraction(0)
    for ring in range(1, int(foot) + 1):
        level = min(Fraction(height), slope * (Fraction(foot) - ring + Fraction(1, 2)))
        if level > Fraction(threshold):
            cells += 8 * ring - 4
            volume += (8 * ring - 4) * level
    return cells, volume


def cone_above_threshold(foot: float, top: float, height: float, threshold: float) -> float:
    """El volumen analítico (m³) del tronco de cono por encima del umbral de huella: el sólido ``h(d) = mín(height,
    s·(foot − d))`` con ``s = height / (foot − top)`` **menos el anillo** donde ``h ≤ threshold`` (de ``d₀ = foot −
    threshold / s`` al pie): ``π·top²·height + 2π·s·[foot·d²/2 − d³/3]`` entre ``top`` y ``d₀``."""
    slope = height / (foot - top)
    d0 = foot - threshold / slope

    def antiderivative(d: float) -> float:
        return foot * d * d / 2.0 - d ** 3 / 3.0

    return math.pi * top * top * height + 2.0 * math.pi * slope * (antiderivative(d0) - antiderivative(top))


def centre_of(grid: Any, cells: Iterable[tuple[int, int]]) -> tuple[float, float]:
    """El centro (la media de los centros de celda, ``fsum``) de las celdas ``(fila, columna)`` de ``grid``."""
    x, y = grid.centers()
    found = list(cells)
    return (math.fsum(float(x[r, c]) for r, c in found) / len(found),
            math.fsum(float(y[r, c]) for r, c in found) / len(found))


# --- El cálculo a mano de A2 y A3 -----------------------------------------------------------------------------------


def near(mask: np.ndarray, cell: float, radius_m: float) -> np.ndarray:
    """Las celdas a no más de ``radius_m`` m de alguna de ``mask`` (centro con centro, con los 10⁻⁹ m de tolerancia de
    ``oracles.hand_dilate`` y ``hand_crown``), por fuerza bruta **sobre el borde de la máscara**: la celda de la
    máscara más próxima a una de fuera siempre tiene una vecina (de 4) fuera. Si no, el vecino de ``Q`` hacia ``P``
    (a lo largo del mayor de ``|a|`` y ``|b|``, que es ≥ 1 celda > ½) está más cerca de ``P`` que ``Q`` y es de la
    máscara, y ``Q`` no era la más próxima. Las de dentro están a distancia 0."""
    mask = np.asarray(mask, dtype=bool)
    found = mask.copy()
    if not mask.any():
        return found
    padded = np.pad(mask, 1, constant_values=False)
    edge = mask & ~(padded[:-2, 1:-1] & padded[2:, 1:-1] & padded[1:-1, :-2] & padded[1:-1, 2:])
    rows, cols = np.nonzero(edge)
    reach = math.floor(radius_m / cell + 1e-9)
    top, bottom = max(int(rows.min()) - reach, 0), min(int(rows.max()) + reach + 1, mask.shape[0])
    left, right = max(int(cols.min()) - reach, 0), min(int(cols.max()) + reach + 1, mask.shape[1])
    y, x = np.mgrid[top:bottom, left:right]
    nearest = np.full(y.shape, np.inf)
    for i, j in zip(rows.tolist(), cols.tolist(), strict=True):
        nearest = np.minimum(nearest, np.hypot((y - i) * cell, (x - j) * cell))
    found[top:bottom, left:right] |= nearest <= radius_m + 1e-9
    return found


@dataclass(frozen=True, slots=True, eq=False)
class Grown:
    """Lo que dan A2 y A3 a mano sobre la ventana de una marca: la ``window`` (filas y columnas de la rejilla
    entera), su ``grid``, el terreno ``z``, la ``mark``, la marca ampliada (``enlarged``) y el resultado del oráculo
    de la huella (``found``); la huella (``mask``), la ``base`` (el plano o la superficie de base) y su ``plane``
    (``None`` con base propia), el ``volume`` (m³), las vueltas (``turns``), si convergió y si la corona no tenía
    celdas llanas bastantes."""

    window: tuple[slice, slice]
    grid: Any
    z: np.ndarray
    mark: np.ndarray
    enlarged: np.ndarray
    found: Any
    mask: np.ndarray
    base: np.ndarray
    plane: Any
    volume: float
    turns: int
    converged: bool
    few_flat: bool

    def full(self, grid: Any, mask: np.ndarray | None = None) -> np.ndarray:
        """``mask`` (de la ventana; por defecto la huella) como máscara de la rejilla entera ``grid``."""
        found = np.zeros(grid.shape, dtype=bool)
        found[self.window] = self.mask if mask is None else mask
        return found


def _window_of(mark: np.ndarray, grid: Any, margin_m: float) -> tuple[slice, slice]:
    """La ventana de la marca: su caja ampliada por el margen, la corona exterior y dos celdas, recortada."""
    rows, cols = np.nonzero(mark)
    reach = math.ceil((margin_m + D3["crown_outer_m"]) / grid.dx) + 2
    return (slice(max(int(rows.min()) - reach, 0), min(int(rows.max()) + reach + 1, grid.nrows)),
            slice(max(int(cols.min()) - reach, 0), min(int(cols.max()) + reach + 1, grid.ncols)))


def _cells(grid: Any, z: np.ndarray, mask: np.ndarray) -> list[tuple[float, float, float]]:
    """``(x, y, z)`` de las celdas de ``mask`` en el orden de lectura (la fila 0, al norte), para el oráculo."""
    x, y = grid.centers()
    return [(float(x[r, c]), float(y[r, c]), float(z[r, c])) for r, c in np.argwhere(mask)]


def grow_by_hand(z: np.ndarray, grid: Any, mark: np.ndarray, *, margin_m: float,
                 params: dict[str, float | int] = D3, threshold_m: float = THRESHOLD_M) -> Grown:
    """A2 y A3 enteros **a mano** sobre la ventana de ``mark`` (máscara de ``grid``): la marca ampliada por
    ``margin_m`` y, en cada vuelta, la corona (a ≤ ``crown_outer_m`` de la huella y a más de ``crown_inner_m``), las
    celdas de la corona de pendiente < ``crown_slope_deg`` (toda la corona si suman menos del área llana mínima), el
    plano en racionales exactos con el descarte de atípicas y el límite de inclinación (``oracles.hand_plane``) y la
    huella sobre él (``oracles.hand_footprint``), hasta que no cambie o se acaben las vueltas. Una marca que no da
    ninguna zona hace fallar la prueba."""
    window = _window_of(mark, grid, margin_m)
    rows, cols = window
    wgrid = gis.Grid(grid.west + cols.start * grid.dx, grid.north - rows.start * grid.dy, grid.dx, grid.dy,
                     cols.stop - cols.start, rows.stop - rows.start)
    zw, mw = z[window], mark[window]
    cell = grid.dx
    enlarged = near(mw, cell, margin_m)
    slope = oracles.hand_cell_slope_deg(zw.tolist(), cell, cell)
    x, y = wgrid.centers()
    current, few_flat, converged = mw.copy(), False, False
    for turn in range(1, int(params["turns"]) + 1):
        crown = near(current, cell, params["crown_outer_m"]) & ~near(current, cell, params["crown_inner_m"])
        flat = crown & (slope < params["crown_slope_deg"])
        few_flat = float(flat.sum()) * cell * cell < params["crown_flat_min_m2"]
        plane = oracles.hand_plane(_cells(wgrid, zw, crown if few_flat else flat), rounds=int(params["fit_rounds"]),
                                   max_residual_m=params["max_residual_m"], tilt_max_deg=params["tilt_max_deg"],
                                   quantile=params["support_quantile"])
        base = np.asarray(plane.at(x, y), dtype=np.float64)
        found = oracles.hand_footprint(zw.tolist(), base.tolist(), mw.tolist(), enlarged.tolist(), threshold_m)
        assert found is not None, "el oráculo no encontró ninguna zona que toque la marca"
        if np.array_equal(found.mask, current):
            converged = True
            break
        current = found.mask
    volume = oracles.hand_volume(zw.tolist(), base.tolist(), found.mask.tolist(), cell * cell, threshold_m)
    return Grown(window, wgrid, zw, mw, enlarged, found, found.mask, base, plane, volume, turn, converged, few_flat)


def cut_by_hand(z: np.ndarray, base: np.ndarray, grid: Any, mark: np.ndarray, *, margin_m: float,
                threshold_m: float = THRESHOLD_M) -> Grown:
    """La huella y el volumen sobre una **superficie de base propia** (RF-016-03), a mano: una sola vuelta, sin corona,
    ajuste ni límite de inclinación."""
    window = _window_of(mark, grid, margin_m)
    zw, mw, bw = z[window], mark[window], base[window]
    rows, cols = window
    wgrid = gis.Grid(grid.west + cols.start * grid.dx, grid.north - rows.start * grid.dy, grid.dx, grid.dy,
                     cols.stop - cols.start, rows.stop - rows.start)
    enlarged = near(mw, grid.dx, margin_m)
    found = oracles.hand_footprint(zw.tolist(), bw.tolist(), mw.tolist(), enlarged.tolist(), threshold_m)
    assert found is not None, "el oráculo no encontró ninguna zona que toque la marca"
    volume = oracles.hand_volume(zw.tolist(), bw.tolist(), found.mask.tolist(), grid.cell_area, threshold_m)
    return Grown(window, wgrid, zw, mw, enlarged, found, found.mask, bw, None, volume, 1, True, False)


def hand_notes(grown: Grown) -> list[tuple[str, tuple[float, float] | None]]:
    """Los avisos y notas de un acopio que ve el oráculo, en el orden documentado (el borde de la marca ampliada, las
    zonas, la corona, la inclinación y que no se estabiliza), cada uno con su lugar si el aviso lo trae: la primera
    celda que llega al borde, el centro de la mayor de las demás zonas, el centro de la huella."""
    found = []
    if grown.found.first_edge is not None:
        found.append((AT_EDGE, centre_of(grown.grid, [grown.found.first_edge])))
    if grown.found.zones > 1:
        found.append((SEVERAL, centre_of(grown.grid, grown.found.other)))
    if grown.few_flat:
        found.append((FEW_FLAT, None))
    if grown.plane is not None and grown.plane.limited:
        found.append((TILT, centre_of(grown.grid, map(tuple, np.argwhere(grown.mask).tolist()))))
    if not grown.converged:
        found.append((NOT_CONVERGED, None))
    return found


def share_by_hand(grid: Any, grown: Sequence[Grown], *, names: Sequence[str]) -> tuple[list[np.ndarray], np.ndarray]:
    """El reparto de las celdas comunes de las huellas de ``grown`` (A3, RF-016-06) con ``oracles.hand_share`` sobre la
    caja que reúne sus ventanas: las huellas repartidas, como máscaras de la rejilla entera, y las celdas comunes
    **antes** de repartir (la unión de los cruces de cada par)."""
    top = min(g.window[0].start for g in grown)
    bottom = max(g.window[0].stop for g in grown)
    left = min(g.window[1].start for g in grown)
    right = max(g.window[1].stop for g in grown)
    box = (slice(top, bottom), slice(left, right))
    masks = [g.full(grid)[box] for g in grown]
    marks = [g.full(grid, g.mark)[box] for g in grown]
    shared = oracles.hand_share([m.tolist() for m in masks], [m.tolist() for m in marks])
    common = np.zeros(grid.shape, dtype=bool)
    twice = np.sum(masks, axis=0) > 1
    common[box] = twice
    out = []
    for found in shared:
        full = np.zeros(grid.shape, dtype=bool)
        full[box] = found
        out.append(full)
    assert len(out) == len(names)
    return out, common


def assert_notes(case: unittest.TestCase, notes: Sequence[Any], expected: Sequence[tuple[str, Any]], *,
                 label: str = "") -> None:
    """Los códigos de ``notes`` (``Notice`` o ``SiteMessage``) son los de ``expected`` en su orden y, donde el aviso
    trae lugar (``x`` e ``y``) y el oráculo lo sabe, es el mismo a ≤ 10⁻⁶ m."""
    case.assertEqual([note.code for note in notes], [code for code, _ in expected], label)
    for note, (code, place) in zip(notes, expected, strict=True):
        if place is not None and "x" in note.values:
            case.assertAlmostEqual(note.values["x"], place[0], delta=1e-6, msg=f"{label} {code}: x")
            case.assertAlmostEqual(note.values["y"], place[1], delta=1e-6, msg=f"{label} {code}: y")


def assert_plane_and_volume(case: unittest.TestCase, grown: Grown, *, plane: Any, volume: float, turns: int,
                            converged: bool, label: str = "") -> None:
    """El plano (a ≤ 10⁻⁹ m en toda la ventana y la misma inclinación ajustada, con o sin límite), el volumen (a ≤ 10⁻⁹
    relativo), las vueltas y la convergencia del código son los del cálculo a mano."""
    if plane is None:
        case.assertIsNone(grown.plane, label)
    else:
        case.assertIsNotNone(grown.plane, label)
        case.assertLessEqual(float(np.abs(plane.values(grown.grid) - grown.base).max()), EXACT, label)
        case.assertAlmostEqual(plane.fitted_tilt_deg, grown.plane.fitted_tilt_deg, delta=EXACT, msg=label)
        case.assertEqual(plane.limited, grown.plane.limited, label)
        case.assertAlmostEqual(plane.azimuth_deg, math.degrees(math.atan2(grown.plane.east_slope,
                                                                          grown.plane.north_slope)) % 360.0,
                               delta=EXACT, msg=label)
    case.assertAlmostEqual(volume / grown.volume - 1.0, 0.0, delta=EXACT, msg=label)
    case.assertEqual((turns, converged), (grown.turns, grown.converged), label)


# --- Los oráculos antes de usarlos de árbitro -----------------------------------------------------------------------


class OracleTest(unittest.TestCase):
    """El cálculo a mano de arriba da lo que se sabe, y lo mismo que los oráculos de fuerza bruta de ``design_oracles``
    y de ``test_stockpile_footprint``, antes de que arbitre nada."""

    def test_the_spec_values_are_the_defaults_of_the_program(self) -> None:
        """D-3, D-17, P-6: las entradas de los casos (los valores por defecto del programa) son los que escribe la spec."""
        self.assertEqual(D3, SPEC_D3)
        self.assertEqual(CANDIDATE_D3, SPEC_CANDIDATES)
        self.assertEqual(THRESHOLD_M, SPEC_THRESHOLD_M)

    def test_the_rings_of_a_pyramid_are_counted_by_hand(self) -> None:
        """La pirámide de referencia (pie 20 m, cima 12 m, 4 m de alto): 1.600 celdas y 4.184 m³ en total; sobre el
        umbral de huella, 1.444 celdas y 4.145 m³ (el anillo de 0,25 m de altura no cuenta). Con el pie de 2 m, la cima
        de 0 y 2 m de alto (pendiente 1) los anillos 1 y 2 a 1,5 y 0,5 m: 4 celdas a 1,5 m y 12 a 0,5 m."""
        self.assertEqual(pyramid_rings(20, 12, 4.0, 0.0), (1600, Fraction(4184)))
        self.assertEqual(pyramid_rings(20, 12, 4.0, 0.3), (1444, Fraction(4145)))
        self.assertEqual(pyramid_rings(2, 0, 2.0, 0.0), (16, Fraction(4 * 3, 2) + 12 * Fraction(1, 2)))
        self.assertEqual(pyramid_rings(2, 0, 2.0, 1.0), (4, Fraction(6)))

    def test_the_analytic_cone_is_the_known_one(self) -> None:
        """Sin umbral, el tronco de cono de CE-016-02 mide π·5/3·(20² + 20·10 + 10²) = 3.665,19 m³; con el de huella, el
        anillo de 19,4 a 20 m (≈ 11 m³) menos."""
        self.assertAlmostEqual(cone_above_threshold(20.0, 10.0, 5.0, 0.0), math.pi * 5.0 / 3.0 * 700.0, delta=1e-9)
        ring = math.pi * 5.0 / 3.0 * 700.0 - cone_above_threshold(20.0, 10.0, 5.0, 0.3)
        self.assertTrue(10.0 < ring < 12.0, ring)

    def test_the_quantile_support_is_the_one_counted_by_hand(self) -> None:
        """Cinco filas de cinco celdas en un plano de 0,2 m/m al este (11,3°, más que el límite de 4°): la inclinación se
        limita a 4° y la cota de apoyo es el cuantil 0,6 de ``z − b'·x'`` (25 valores: la posición 14,4 está entre el
        15.º y el 16.º, que son las columnas 2 y 3): ``10,4 + 0,4·(0,2 − tan 4°)``."""
        cells = [(float(x), float(y), 10.0 + 0.2 * x) for y in range(5) for x in range(5)]
        found = oracles.hand_plane(cells, rounds=4, max_residual_m=1.0, tilt_max_deg=4.0, quantile=0.6)
        self.assertTrue(found.limited)
        self.assertAlmostEqual(found.fitted_tilt_deg, math.degrees(math.atan(0.2)), delta=1e-12)
        tangent = math.tan(math.radians(4.0))
        self.assertAlmostEqual(found.east_slope, tangent, delta=1e-12)
        self.assertAlmostEqual(found.north_slope, 0.0, delta=1e-12)
        self.assertAlmostEqual(found.pivot_z, 10.4 + 0.4 * (0.2 - tangent), delta=1e-12)

    def test_near_is_the_brute_force_one(self) -> None:
        """``near`` (la fuerza bruta sobre el borde) da lo que ``oracles.hand_dilate`` (cada celda contra cada celda de la
        máscara) y lo que ``oracles.hand_crown``, en máscaras al azar con huecos, islas y celdas en el borde de la
        rejilla, con celdas de 1 y de 0,5 m y radios de 1, 3 y 10 m."""
        rng = random.Random(20_261_118)
        for _ in range(8):
            mask = np.zeros((22, 26), dtype=bool)
            for _ in range(rng.randrange(1, 6)):
                top, left = rng.randrange(22), rng.randrange(26)
                mask[top:top + rng.randrange(1, 9), left:left + rng.randrange(1, 9)] = True
            mask &= np.array([[rng.random() < 0.85 for _ in range(26)] for _ in range(22)])
            if not mask.any():
                mask[3, 4] = True
            for cell in (1.0, 0.5):
                for radius in (1.0, 3.0, 10.0):
                    with self.subTest(cell=cell, radius=radius):
                        np.testing.assert_array_equal(near(mask, cell, radius),
                                                      oracles.hand_dilate(mask.tolist(), cell, radius))
                inner, outer = 1.0, 3.0
                np.testing.assert_array_equal(near(mask, cell, outer) & ~near(mask, cell, inner),
                                              oracles.hand_crown(mask.tolist(), cell, inner, outer))

    def test_grow_by_hand_is_the_brute_hand_grow(self) -> None:
        """A2 y A3 a mano (con las distancias sobre el borde y la ventana) dan lo que el ``hand_grow`` de
        ``test_stockpile_footprint`` (con las distancias por fuerza bruta sobre la ventana entera): el mismo plano en cada
        celda, la misma huella, el mismo volumen, las mismas vueltas y las mismas notas, en un cono, una pirámide con
        atípicas, un cono a 8° (plano limitado) y un cono con un cráter."""
        scenes = {"cono": small_scene("cone"), "pirámide con atípicas": small_scene("pyramid", blocks=SPIKES),
                  "cono a 8°": small_scene("cone", 8.0),
                  "cono con cráter": small_scene("cone", flatten=((13.0, 13.0, 17.0, 17.0),))}
        for what, scene in scenes.items():
            with self.subTest(what):
                brute = hand_grow(scene.terrain, scene.grid, scene.mark, margin_m=3.0)
                mine = grow_by_hand(scene.terrain, scene.grid, scene.mark, margin_m=3.0)
                self.assertEqual(mine.window[0].stop - mine.window[0].start, scene.grid.nrows)  # cabe la ventana
                np.testing.assert_array_equal(mine.mask, brute.found.mask)
                np.testing.assert_allclose(mine.base, brute.base, rtol=0.0, atol=1e-12)
                self.assertAlmostEqual(mine.volume / brute.volume - 1.0, 0.0, delta=1e-12)
                self.assertEqual((mine.turns, mine.converged, mine.few_flat),
                                 (brute.turns, brute.converged, brute.few_flat))
                self.assertEqual(mine.plane.limited, brute.plane.limited)


# --- CE-016-02: el acopio de referencia ------------------------------------------------------------------------------


def detect_one(grid: Any, z: np.ndarray, mark: np.ndarray, key: str = "Cono") -> Any:
    """La detección de una sola marca (``mark``, máscara de ``grid``) sobre ``z`` con los valores por defecto."""
    marks = (stockpiles.StockpileMark(key=key, cells=np.flatnonzero(mark)),)
    job = stockpiles.StockpileJob(name="Detección de prueba", code="STK-001", grid=grid, surface=z, marks=marks,
                                  params=footprint_params())
    return stockpiles.detect_stockpiles(job)


@functools.cache
def cone_runs() -> dict[float, tuple[Any, Any, Any, Grown, np.ndarray]]:
    """Los dos casos de CE-016-02 (el cono sobre 3° y sobre 8°): ``(caso, resultado, acopio, cálculo a mano, marca)``,
    una vez por proceso."""
    found = {}
    for tilt in (3.0, 8.0):
        case = sdata.mound_case("cone", tilt)
        mark = box_mask(case.grid, case.mark_box)
        outcome = detect_one(case.grid, case.terrain, mark)
        found[tilt] = (case, outcome, outcome.stockpiles[0],
                       grow_by_hand(case.terrain, case.grid, mark, margin_m=D3["margin_m"]), mark)
    return found


class ConeTest(unittest.TestCase):
    """CE-016-02: el tronco de cono de la cantera (pie de 20 m de radio, cima de 10 m, 5 m de alto: pendiente 0,5) en la
    ventana de 120 × 120 celdas de 1 m, con la marca (el pie más 4 m de semilado) y ocho celdas atípicas de 2 a 4 m en
    la corona (más que el residuo máximo de 1 m), sobre un plano de 3° y sobre uno de 8° (con la inclinación máxima
    de 4°)."""

    FOOT, TOP, HEIGHT = 20.0, 10.0, 5.0

    @classmethod
    def setUpClass(cls) -> None:
        cls.found = cone_runs()

    def cone_heights(self, grid: Any) -> np.ndarray:
        """La altura del cono a mano (los números del enunciado, no los de la cantera)."""
        cone = sdata.Mound("cono", "cone", 60.0, 60.0, self.FOOT, self.TOP, self.HEIGHT)
        return hand_heights(grid, [cone])

    def test_the_case_is_the_one_in_the_statement(self) -> None:
        """La cantera es lo que dice CE-016-02: el cono de 20 / 10 / 5 m (su volumen analítico, 3.665,19 m³), el plano
        de 3° (y el de 8°) con su máxima pendiente al azimut de 30° por 115 m en el centro, y ocho celdas atípicas de 2 a
        4 m (cuatro en la corona de la marca y cuatro en la de la huella) con suma +8 m."""
        for tilt, (case, _outcome, _item, _grown, _mark) in self.found.items():
            with self.subTest(tilt=tilt):
                self.assertEqual((sdata.CONE.foot, sdata.CONE.top, sdata.CONE.height), (self.FOOT, self.TOP, self.HEIGHT))
                np.testing.assert_allclose(case.height, self.cone_heights(case.grid), rtol=0.0, atol=1e-12)
                np.testing.assert_allclose(
                    case.base, hand_plane_values(case.grid, tilt, sdata.WINDOW_PIVOT, sdata.WINDOW_Z_M),
                    rtol=0.0, atol=1e-12)
                offsets = case.offsets[case.outliers]
                self.assertEqual(int(case.outliers.sum()), 8)
                self.assertTrue((np.abs(offsets) >= 2.0).all() and (np.abs(offsets) <= 4.0).all())
                self.assertEqual(float(offsets.sum()), 8.0)
                np.testing.assert_allclose(case.terrain, case.base + case.height + case.offsets, rtol=0.0, atol=1e-12)
        self.assertAlmostEqual(cone_above_threshold(self.FOOT, self.TOP, self.HEIGHT, 0.0), 3665.19, delta=0.005)

    def test_3_degrees_the_footprint_is_the_cone_above_the_threshold(self) -> None:
        """RF-016-02, D-17, D-18: la huella son exactamente las celdas del cono a más de 0,3 m de altura (a < 19,4 m del
        centro: 1.176 celdas contadas a mano); las ocho atípicas, ninguna dentro."""
        case, _outcome, item, _grown, _mark = self.found[3.0]
        height = self.cone_heights(case.grid)
        expected = np.flatnonzero(height > THRESHOLD_M)
        self.assertEqual(item.cells.tolist(), expected.tolist())
        self.assertEqual(int(expected.size), 1176)
        self.assertEqual(item.area_m2, 1176.0)
        self.assertFalse(np.isin(item.cells, np.flatnonzero(case.outliers)).any())

    def test_3_degrees_the_plane_is_the_synthetic_one_to_a_micrometre(self) -> None:
        """CE-016-02: el plano de base recuperado a ≤ 10⁻⁶ m del sintético en toda la ventana (y en toda la huella), con
        las ocho atípicas en la corona más allá del residuo máximo; 3° de inclinación y el azimut de 30°."""
        case, _outcome, item, _grown, _mark = self.found[3.0]
        synthetic = hand_plane_values(case.grid, 3.0, sdata.WINDOW_PIVOT, sdata.WINDOW_Z_M)
        self.assertLessEqual(float(np.abs(item.plane.values(case.grid) - synthetic).max()), PLANE_TOL_M)
        rows, cols = np.divmod(item.cells, case.grid.ncols)
        self.assertLessEqual(float(np.abs(item.base - synthetic[rows, cols]).max()), PLANE_TOL_M)
        self.assertAlmostEqual(item.plane.tilt_deg, 3.0, delta=PLANE_TOL_M)
        self.assertAlmostEqual(item.plane_azimuth_deg, sdata.AZIMUTH_DEG, delta=1e-4)
        self.assertFalse(item.plane.limited)

    def test_3_degrees_the_outliers_are_what_the_discard_removes(self) -> None:
        """El control de CE-016-02: sin el descarte de las celdas más allá del residuo máximo (cero vueltas del ajuste) el
        plano de mínimos cuadrados, a mano, se aparta del sintético más de un milímetro: las ocho atípicas pesan, y el
        micrómetro de arriba es obra del descarte."""
        case, _outcome, _item, _grown, mark = self.found[3.0]
        plain = grow_by_hand(case.terrain, case.grid, mark, margin_m=D3["margin_m"], params={**D3, "fit_rounds": 0})
        synthetic = hand_plane_values(case.grid, 3.0, sdata.WINDOW_PIVOT, sdata.WINDOW_Z_M)[plain.window]
        self.assertGreater(float(np.abs(plain.base - synthetic).max()), 1e-3)

    def test_3_degrees_the_volume_is_the_hand_sum_and_the_analytic_one(self) -> None:
        """CE-016-02, RF-016-02: el volumen es la suma de las alturas del cono en la huella (``fsum``: la cuenta a mano
        sobre las mismas celdas con el plano sintético) a ≤ 10⁻⁹ relativo, el cálculo a mano de A2 y A3 enteros a ≤ 10⁻⁹
        y el analítico por encima del umbral de huella (el anillo de menos del umbral, descontado) a ≤ 1 % (D-11)."""
        case, _outcome, item, grown, _mark = self.found[3.0]
        height = self.cone_heights(case.grid)
        by_hand = math.fsum(height[height > THRESHOLD_M].tolist())
        self.assertAlmostEqual(item.volume_m3 / by_hand - 1.0, 0.0, delta=EXACT)
        assert_plane_and_volume(self, grown, plane=item.plane, volume=item.volume_m3, turns=item.turns,
                                converged=item.converged)
        analytic = cone_above_threshold(self.FOOT, self.TOP, self.HEIGHT, THRESHOLD_M)
        self.assertLessEqual(abs(item.volume_m3 / analytic - 1.0), ANALYTIC)
        self.assertAlmostEqual(item.thickness_max_m, self.HEIGHT, delta=1e-9)

    def test_3_degrees_the_notes_are_the_hand_ones(self) -> None:
        """RF-016-05: las dos atípicas positivas que caen dentro de la marca (de 2,5 y 4 m) son otras dos zonas que la
        tocan: la nota de «más de una zona» con 3 zonas y el lugar de la mayor de las demás (la de 2,5 m, la primera al
        recorrer la rejilla fila a fila); ni inclinación limitada ni corona llana escasa. CE-016-02 no pide «sin
        notas»: las pide RF-016-05."""
        case, outcome, item, grown, _mark = self.found[3.0]
        self.assertEqual(grown.found.zones, 3)
        self.assertEqual([code for code, _ in hand_notes(grown)], [SEVERAL])
        assert_notes(self, item.notes, hand_notes(grown))
        self.assertEqual(item.notes[0].values["zones"], 3)
        place = (sdata.BASE[0] + 60.0 + 21.5, sdata.BASE[1] + 60.0 + 5.5)  # la atípica de +2,5 m, relativa al centro
        self.assertAlmostEqual(item.notes[0].values["x"], place[0], delta=1e-6)
        self.assertAlmostEqual(item.notes[0].values["y"], place[1], delta=1e-6)
        self.assertEqual([notice.code for notice in outcome.notices], [SEVERAL])

    def test_8_degrees_the_plane_is_limited_with_its_warning_and_note(self) -> None:
        """RF-016-07, CE-016-02: sobre el plano de 8° la inclinación máxima de 4° deja el plano en 4° (≤ 10⁻⁹ °), conserva
        el azimut de la máxima pendiente del ajuste (el del cálculo a mano, ≤ 10⁻⁹ °, y a menos de 0,05° del de 30° del
        sintético), avisa con la inclinación ajustada (la del cálculo a mano, ≤ 10⁻⁹ °, y ≈ 8°) y la limitada, con el cuantil
        de apoyo, y lo anota en el acopio con su lugar (el centro de la huella) y en el resumen."""
        case, outcome, item, grown, _mark = self.found[8.0]
        self.assertTrue(grown.plane.limited)
        self.assertAlmostEqual(item.plane.tilt_deg, 4.0, delta=EXACT)
        azimuth = math.degrees(math.atan2(grown.plane.east_slope, grown.plane.north_slope)) % 360.0
        self.assertAlmostEqual(item.plane_azimuth_deg, azimuth, delta=EXACT)
        self.assertAlmostEqual(item.plane_azimuth_deg, sdata.AZIMUTH_DEG, delta=0.05)
        (note,) = [note for note in item.notes if note.code == TILT]
        self.assertAlmostEqual(note.values["fitted"], grown.plane.fitted_tilt_deg, delta=EXACT)
        self.assertAlmostEqual(note.values["fitted"], 8.0, delta=0.05)  # las atípicas mueven el ajuste ≈ 0,01°
        self.assertEqual((note.values["limit"], note.values["quantile"], note.values["mark"]), (4.0, 0.6, "Cono"))
        place = centre_of(grown.grid, map(tuple, np.argwhere(grown.mask).tolist()))
        self.assertAlmostEqual(note.values["x"], place[0], delta=1e-6)
        self.assertAlmostEqual(note.values["y"], place[1], delta=1e-6)
        self.assertIn(TILT, [notice.code for notice in outcome.notices])
        self.assertAlmostEqual(item.plane_slope_percent, 100.0 * math.tan(math.radians(4.0)), delta=1e-9)
        figure = [f for f in outcome.figures if f.key == "des.stk_plane_tilt_deg"]
        self.assertEqual(len(figure), 1)
        self.assertAlmostEqual(figure[0].value, 4.0, delta=EXACT)

    def test_8_degrees_the_support_and_the_volume_are_the_hand_ones(self) -> None:
        """RF-016-07, CE-016-02: el plano limitado (apoyado en el cuantil 0,6 de los residuos de la corona de la huella
        final), la huella, el volumen sobre él, las vueltas y los avisos igual al cálculo a mano de A2 y A3 enteros
        a ≤ 10⁻⁹: el plano a ≤ 10⁻⁹ m en toda la ventana y el volumen a ≤ 10⁻⁹ relativo."""
        case, _outcome, item, grown, mark = self.found[8.0]
        assert_plane_and_volume(self, grown, plane=item.plane, volume=item.volume_m3, turns=item.turns,
                                converged=item.converged)
        self.assertEqual(item.cells.tolist(), np.flatnonzero(grown.full(case.grid)).tolist())
        assert_notes(self, item.notes, hand_notes(grown))
        self.assertEqual([code for code, _ in hand_notes(grown)], [SEVERAL, TILT])
        self.assertEqual(grown.found.zones, 4)
        analytic = cone_above_threshold(self.FOOT, self.TOP, self.HEIGHT, THRESHOLD_M)
        self.assertLess(item.volume_m3, analytic)  # sobre el plano limitado, el cono ya no es el de 3°

    def test_the_thickness_ground_and_surface_are_the_hand_layers(self) -> None:
        """RF-016-01, RF-016-09: en cada celda de la huella, el espesor es ``máx(z − base, 0)`` (nunca negativo), el terreno
        sin acopios ``mín(z, base)`` y la superficie ``z``, como las da ``oracles.hand_layers`` (un bucle por celda), y el
        volumen es la suma de ese espesor por el área donde pasa del umbral."""
        for tilt, (case, _outcome, item, grown, _mark) in self.found.items():
            with self.subTest(tilt=tilt):
                hand = oracles.hand_layers(grown.z.tolist(), grown.base.tolist(), grown.mask.tolist(), 1.0,
                                           THRESHOLD_M)
                rows, cols = np.divmod(item.cells, case.grid.ncols)
                r0, c0 = grown.window[0].start, grown.window[1].start
                for name in ("base", "thickness", "ground", "surface"):
                    expected = np.array([getattr(hand, name)[int(r) - r0, int(c) - c0] for r, c in zip(rows, cols,
                                                                                                     strict=True)])
                    np.testing.assert_allclose(getattr(item, name), expected, rtol=0.0, atol=EXACT, err_msg=name)
                self.assertGreaterEqual(float(item.thickness.min()), 0.0)
                self.assertAlmostEqual(item.thickness_max_m, hand.thickness_max, delta=EXACT)
                self.assertAlmostEqual(item.volume_m3 / hand.volume - 1.0, 0.0, delta=EXACT)
                above = item.thickness > THRESHOLD_M
                self.assertAlmostEqual(math.fsum(item.thickness[above].tolist()) / item.volume_m3 - 1.0, 0.0,
                                       delta=EXACT)

    def test_a_crater_is_a_hole_the_footprint_fills_and_the_volume_leaves_out(self) -> None:
        """D-18, RF-016-01, RF-016-02: con un cráter de 4 × 4 celdas en la cima del cono de 3° (el terreno a la altura del
        plano, 5 m por debajo de lo que era), la huella sigue siendo las 1.176 celdas del cono (el hueco se rellena: su
        área cuenta, 1.176 m²) y el volumen es la suma de las alturas del cono **sin** las 16 celdas del cráter, que no
        pasan del umbral (es 80 m³ menos: 16 × 5 m), a ≤ 10⁻⁹; en esas celdas el espesor es 0 (nunca negativo), igual
        al cálculo a mano de A2 y A3 enteros."""
        case, _outcome, plain, _grown, mark = self.found[3.0]
        z = case.terrain.copy()
        crater = box_mask(case.grid, (58.0, 58.0, 62.0, 62.0))
        z[crater] = case.base[crater]
        height = self.cone_heights(case.grid)
        self.assertEqual(int(crater.sum()), 16)
        self.assertTrue((height[crater] == self.HEIGHT).all())
        item = detect_one(case.grid, z, mark).stockpiles[0]
        self.assertEqual(item.cells.tolist(), np.flatnonzero(height > THRESHOLD_M).tolist())
        self.assertEqual(item.area_m2, 1176.0)
        by_hand = math.fsum(height[(height > THRESHOLD_M) & ~crater].tolist())
        self.assertAlmostEqual(item.volume_m3 / by_hand - 1.0, 0.0, delta=EXACT)
        self.assertAlmostEqual(plain.volume_m3 - item.volume_m3, 16 * self.HEIGHT, delta=1e-6)
        inside = np.isin(item.cells, np.flatnonzero(crater))
        self.assertEqual(int(inside.sum()), 16)
        self.assertTrue((item.thickness[inside] >= 0.0).all() and (item.thickness[inside] <= PLANE_TOL_M).all())
        hand = grow_by_hand(z, case.grid, mark, margin_m=D3["margin_m"])
        assert_plane_and_volume(self, hand, plane=item.plane, volume=item.volume_m3, turns=item.turns,
                                converged=item.converged)
        np.testing.assert_array_equal(hand.full(case.grid), np.isin(np.arange(z.size), item.cells).reshape(z.shape))


# --- CE-016-01 y E1: el levantamiento -------------------------------------------------------------------------------


def assert_layers(case: unittest.TestCase, grid: Any, grown: Grown, item: Any, mask: np.ndarray, *, label: str = ""
                  ) -> None:
    """Lo que dan A5 y A3 para ``item`` es lo de ``oracles.hand_layers`` (un bucle de Python por celda) sobre su misma
    huella (``mask``, de la ventana de ``grown``) y la base del cálculo a mano: la base, el espesor ``máx(z − base, 0)``
    (nunca negativo), el terreno sin acopios ``mín(z, base)`` y la superficie ``z`` a ≤ 10⁻⁹ m, y el volumen, el área
    y el espesor máximo (RF-016-01, RF-016-09)."""
    hand = oracles.hand_layers(grown.z.tolist(), grown.base.tolist(), mask.tolist(), grid.cell_area, THRESHOLD_M)
    rows, cols = np.divmod(item.cells, grid.ncols)
    r0, c0 = grown.window[0].start, grown.window[1].start
    for name in ("base", "thickness", "ground", "surface"):
        expected = np.array([getattr(hand, name)[int(r) - r0, int(c) - c0] for r, c in zip(rows, cols, strict=True)])
        np.testing.assert_allclose(getattr(item, name), expected, rtol=0.0, atol=EXACT, err_msg=f"{label} {name}")
    case.assertGreaterEqual(float(item.thickness.min()), 0.0, label)
    case.assertAlmostEqual(item.volume_m3 / hand.volume - 1.0, 0.0, delta=EXACT, msg=label)
    case.assertAlmostEqual(item.thickness_max_m, hand.thickness_max, delta=EXACT, msg=label)
    case.assertEqual(item.area_m2, item.cells.size * grid.cell_area, label)
    # la suma del espesor por el área, donde pasa del umbral de huella, es el volumen (la presencia de la 011)
    above = item.thickness > THRESHOLD_M
    case.assertAlmostEqual(math.fsum(item.thickness[above].tolist()) * grid.cell_area / item.volume_m3 - 1.0, 0.0,
                           delta=EXACT, msg=label)


def closed_form_footprint(truth: np.ndarray, grown: Grown) -> np.ndarray:
    """La huella de una marca sola **sin ajustar nada**, de las alturas sintéticas ``truth`` (el montón sobre el plano
    exacto): la zona conexa mayor que toca la marca de las celdas de la marca ampliada a más de 0,3 m, en la ventana
    de ``grown``."""
    above = (truth[grown.window] > THRESHOLD_M) & grown.enlarged
    touching = [zone for zone in oracles.hand_zones(above.tolist()) if any(grown.mark[r, c] for r, c in zone)]
    chosen = max(touching, key=len)
    found = np.zeros(above.shape, dtype=bool)
    for r, c in chosen:
        found[r, c] = True
    return found


def assert_pair(case: unittest.TestCase, grid: Any, mounds: Sequence[Any], outcome: Any, grown: Sequence[Grown],
                names: Sequence[str], boundary: float) -> None:
    """E1, RF-016-06, D-16: dos acopios cuyas marcas se tocan en ``x = boundary`` (local) y cuyas huellas se solapan.

    A mano: cada huella sola es la del montón que cubre su marca ampliada (una cuenta cerrada de las alturas, sin
    ajuste); las celdas comunes son las de las dos; el reparto (``oracles.hand_share``) da cada una a la marca que la
    contiene o a la más próxima, que por simetría es la del lado de la recta de contacto; cada acopio lleva el plano de
    su marca sola. El código da las mismas huellas repartidas (disjuntas, con la misma unión), el volumen de cada una
    a ≤ 10⁻⁹ del cálculo a mano sobre las celdas que le quedan, el aviso con las dos marcas, el área y el centro de lo
    repartido en cada acopio y una sola vez en el resumen."""
    truth = hand_heights(grid, mounds)
    first, second = (next(item for item in outcome.stockpiles if item.key == name) for name in names)
    for found in grown:
        np.testing.assert_array_equal(found.mask, closed_form_footprint(truth, found))  # A2 y A3 = la cuenta cerrada
    shares, common = share_by_hand(grid, grown, names=names)
    count = int(common.sum())
    case.assertEqual(count, 436)
    owner = np.zeros(grid.shape, dtype=int)
    for k, mask in enumerate(shares):
        owner[mask] = k + 1
    local_x = (np.arange(grid.ncols) + 0.5) * grid.dx
    for r, c in np.argwhere(common):
        case.assertEqual(int(owner[r, c]), 1 if local_x[c] < boundary else 2, f"celda ({r}, {c})")
    np.testing.assert_array_equal(shares[0] | shares[1], grown[0].full(grid) | grown[1].full(grid))  # sin perder nada
    case.assertFalse((shares[0] & shares[1]).any())
    for item, grown_k, mask in zip((first, second), grown, shares, strict=True):
        case.assertEqual(item.cells.tolist(), np.flatnonzero(mask).tolist(), item.key)
        inside = mask[grown_k.window]
        hand = oracles.hand_volume(grown_k.z.tolist(), grown_k.base.tolist(), inside.tolist(), grid.cell_area,
                                   THRESHOLD_M)
        case.assertAlmostEqual(item.volume_m3 / hand - 1.0, 0.0, delta=EXACT, msg=item.key)
        assert_layers(case, grid, grown_k, item, inside, label=item.key)
        # cada acopio lleva el plano de su marca sola (no el del otro), a ≤ 10⁻⁹ m en toda su ventana
        case.assertLessEqual(float(np.abs(item.plane.values(grown_k.grid) - grown_k.base).max()), EXACT, item.key)
        case.assertEqual((item.turns, item.converged), (grown_k.turns, grown_k.converged), item.key)
        assert_notes(case, item.notes, [*hand_notes(grown_k), (SHARED, None)], label=item.key)
    # el aviso: las dos marcas, el área repartida y el centro de las celdas comunes (calculado a mano)
    centre = centre_of(grid, map(tuple, np.argwhere(common).tolist()))
    (pair,) = outcome.shared
    case.assertEqual((pair.mark, pair.other, pair.cells, pair.area_m2), (names[0], names[1], count,
                                                                         count * grid.cell_area))
    case.assertAlmostEqual(pair.x, centre[0], delta=1e-6)
    case.assertAlmostEqual(pair.y, centre[1], delta=1e-6)
    for item in (first, second):
        (note,) = [note for note in item.notes if note.code == SHARED]
        case.assertEqual((note.values["mark"], note.values["other"], note.values["area"]),
                         (names[0], names[1], count * grid.cell_area))
        case.assertAlmostEqual(note.values["x"], centre[0], delta=1e-6)
        case.assertAlmostEqual(note.values["y"], centre[1], delta=1e-6)
    case.assertEqual(Counter(notice.code for notice in outcome.notices)[SHARED], 1)  # el resumen lo cuenta una vez
    # D-11: la suma de los dos, frente a las alturas del cálculo a mano de la unión (la mayor de las dos donde se solapan)
    total = math.fsum(truth[truth > THRESHOLD_M].tolist())
    case.assertLessEqual(abs((first.volume_m3 + second.volume_m3) / total - 1.0), ANALYTIC)


@dataclass(frozen=True, slots=True, eq=False)
class SurveyRun:
    """El levantamiento de CE-016-01: los datos (``grid``, ``z``, ``previous``, ``perimeter``), el resultado de la
    detección (``outcome``) y lo que sale a mano de ella: ``grown`` (A2 y A3 de cada marca, con su base propia si la tiene,
    y de la zona de cada candidato), ``zones`` (la zona de cada montículo sin marca que pasa los filtros, de sus alturas),
    ``classes`` (qué le pasa a cada uno de los 20), ``truth`` (las alturas de los 25) y ``mounds`` (por nombre)."""

    grid: Any
    z: np.ndarray
    previous: np.ndarray
    perimeter: np.ndarray
    outcome: Any
    grown: dict[str, Grown]
    zones: dict[str, np.ndarray]
    classes: dict[str, str]
    truth: np.ndarray
    mounds: dict[str, Any]

    def named_candidates(self) -> list[tuple[str, Any]]:
        """Cada candidato con el nombre del montículo que pasa los filtros en cuyo centro está su huella."""
        found = []
        for candidate in self.outcome.candidates.items:
            x, y = candidate.centre
            (name,) = [name for name in self.zones
                       if abs(x - sdata.BASE[0] - self.mounds[name].cx) < 1e-6
                       and abs(y - sdata.BASE[1] - self.mounds[name].cy) < 1e-6]
            found.append((name, candidate))
        return found


def hand_zone_index(grid: Any, z: np.ndarray, perimeter: np.ndarray) -> dict[tuple[int, int], tuple[tuple[int, int], ...]]:
    """A4 a mano: las zonas conexas (4-conexión, por una búsqueda en anchura: ``oracles.hand_zones``) de las celdas del
    perímetro con ``z − apertura(z) > altura mínima``, con la apertura de ⌀ 31 m **por fuerza bruta con enteros**
    (``test_morphology.brute``: el mínimo y el máximo de cada celda contra cada desplazamiento del disco, sin
    ``design.morphology``). La apertura no es el plano: sobre una ladera de 3° el disco plano levanta la apertura bajo
    un montón hasta ≈ 0,8 m, así que la zona de un montículo es algo menor que sus celdas a más de la altura mínima.
    Da, por cada celda de una zona, la zona (sus celdas ``(fila, columna)``)."""
    twice = round(CANDIDATE_D3["open_diameter_m"] / grid.dx)
    opened = brute(brute(z, twice, erode=True), twice, erode=False)
    above = perimeter & (z - opened > CANDIDATE_D3["min_height_m"])
    return {cell: zone for zone in oracles.hand_zones(above.tolist()) for cell in zone}


def classify(grid: Any, mound: Any, index: dict[tuple[int, int], tuple[tuple[int, int], ...]],
             perimeter: np.ndarray) -> tuple[str, np.ndarray]:
    """Qué le pasa a un montículo sin marca con los umbrales de D-3, a mano: tiene zona si alguna de las cuatro celdas de
    su cima está en una de ``index`` y entonces es ``small`` o ``large`` por su área (``min_area_m2`` y ``max_area_m2``,
    ambas incluidas) y ``pass`` si pasa los filtros; si no, ``out`` si sobresale más que la altura mínima solo fuera del
    perímetro y ``low`` si no llega a ella. Devuelve también su zona (máscara de la rejilla entera)."""
    zone: tuple[tuple[int, int], ...] | None = None
    for row in (grid.nrows - int(mound.cy) - 1, grid.nrows - int(mound.cy)):
        for col in (int(mound.cx) - 1, int(mound.cx)):
            zone = zone or index.get((row, col))
    found = np.zeros(grid.shape, dtype=bool)
    if zone is None:
        high = hand_heights(grid, [mound]) > CANDIDATE_D3["min_height_m"]
        return ("out" if (high & ~perimeter).any() else "low"), found
    for r, c in zone:
        found[r, c] = True
    area = float(len(zone)) * grid.cell_area
    if area < CANDIDATE_D3["min_area_m2"]:
        return "small", found
    if area > CANDIDATE_D3["max_area_m2"]:
        return "large", found
    return "pass", found


@functools.cache
def survey_run() -> SurveyRun:
    """La detección del levantamiento (5 marcas con dos materiales y una base propia, y los candidatos) y todo lo que
    sale a mano de ella, una vez por proceso."""
    grid = qfx.GRID
    z, previous = sdata.survey(grid), sdata.previous_survey(grid)
    perimeter = box_mask(grid, qfx.PERIMETER_LOCAL)
    masks = {mark.name: box_mask(grid, mark.box) for mark in sdata.MARKS}
    marks = tuple(stockpiles.StockpileMark(key=mark.name, cells=np.flatnonzero(masks[mark.name]),
                                           margin_m=mark.margin_m, material=mark.material, base=mark.base)
                  for mark in sdata.MARKS)
    job = stockpiles.StockpileJob(name="Detección de prueba", code="STK-001", grid=grid, surface=z, marks=marks,
                                  params=footprint_params(), bases={sdata.PREVIOUS_LABEL: previous},
                                  candidates=candidate_params(), perimeter=perimeter)
    outcome = stockpiles.detect_stockpiles(job)
    grown: dict[str, Grown] = {}
    for mark in sdata.MARKS:
        margin = D3["margin_m"] if mark.margin_m is None else mark.margin_m
        if mark.base is None:
            grown[mark.name] = grow_by_hand(z, grid, masks[mark.name], margin_m=margin)
        else:
            grown[mark.name] = cut_by_hand(z, previous, grid, masks[mark.name], margin_m=margin)
    mounds = {mound.name: mound for mound in sdata.SURVEY_MOUNDS}
    marked = {mark.name for mark in sdata.MARKS}
    classes: dict[str, str] = {}
    zones: dict[str, np.ndarray] = {}
    index = hand_zone_index(grid, z, perimeter)
    for name, mound in mounds.items():
        if name in marked:
            continue
        classes[name], zone = classify(grid, mound, index, perimeter)
        if classes[name] == "pass":
            zones[name] = zone
            grown[name] = grow_by_hand(z, grid, zone, margin_m=D3["margin_m"])
    return SurveyRun(grid, z, previous, perimeter, outcome, grown, zones, classes,
                     hand_heights(grid, sdata.SURVEY_MOUNDS), mounds)


class SurveyTest(unittest.TestCase):
    """CE-016-01 y E1 en el dominio: el levantamiento de 5 acopios marcados (dos materiales, una base propia, el Acopio 1
    y el 2 que se tocan) y 20 montículos sin marca (8 que pasan los filtros, 4 pequeños, 4 bajos y 4 fuera del
    perímetro) en la rejilla de 400 × 400 celdas de 1 m, **de una sola operación**."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.run_ = survey_run()

    def test_the_case_is_the_one_in_the_statement(self) -> None:
        """La cantera es el levantamiento del enunciado: el plano de 3° por 110 m en el centro con la terraza de 0,5 m
        (30 × 40 celdas) bajo el pie del Acopio 5, y los 25 montículos sobre él (donde dos se solapan, el mayor); los
        20 sin marca se reparten, **a mano por su geometría**, en 8 que pasan los filtros, 4 pequeños, 4 bajos y 4
        fuera del perímetro, y son los grupos que dice la cantera."""
        run = self.run_
        plane = hand_plane_values(run.grid, sdata.SURVEY_TILT_DEG, sdata.SURVEY_PIVOT, sdata.SURVEY_Z_M)
        terrace = box_mask(run.grid, sdata.TERRACE_BOX)
        self.assertEqual(int(terrace.sum()), 30 * 40)
        np.testing.assert_allclose(run.previous, plane + np.where(terrace, sdata.TERRACE_M, 0.0), rtol=0.0, atol=1e-12)
        np.testing.assert_allclose(run.z, run.previous + run.truth, rtol=0.0, atol=1e-12)
        self.assertEqual(Counter(run.classes.values()), Counter({"pass": 8, "small": 4, "low": 4, "out": 4}))
        labels = {"pass": "pass", "small": "small", "low": "low", "outside": "out"}
        for group, names in sdata.SURVEY_GROUPS.items():
            if group != "marked":
                self.assertEqual({run.classes[name] for name in names}, {labels[group]}, group)

    def test_one_operation_gives_the_five_stockpiles_and_only_the_eight_candidates(self) -> None:
        """CE-016-01, RF-016-02, RF-016-08: una sola operación da los 5 acopios (en el orden de las marcas, dos
        materiales, ninguno rechazado) y lista solo los 8 candidatos que pasan los filtros: cada uno es uno de los
        montículos que pasan (el centro de su huella es el del montículo), uno por montículo; no se lista ninguno de los
        4 pequeños, de los 4 bajos ni de los 4 de fuera del perímetro, ni ninguno de los marcados."""
        run = self.run_
        outcome = run.outcome
        self.assertEqual([item.key for item in outcome.stockpiles], [mark.name for mark in sdata.MARKS])
        self.assertEqual(outcome.rejected, ())
        self.assertEqual(outcome.materials, ("mineral", "estéril"))
        found = outcome.candidates
        self.assertEqual(len(found.items), 8)
        self.assertEqual((found.too_small, found.too_large, found.rejected), (4, 0, 0))  # lo descartado se cuenta
        self.assertEqual(found.filtered, 4)
        passing = sorted(name for name, label in run.classes.items() if label == "pass")
        self.assertEqual(sorted(name for name, _candidate in run.named_candidates()), passing)

    def test_no_output_gives_the_twelve_that_do_not_pass(self) -> None:
        """CE-016-01, error 64, RF-016-08: ni un acopio, ni un candidato (su zona o su huella), ni un aviso, ni una
        pareja repartida contiene el centro de los 12 montículos que no pasan (4 pequeños, 4 bajos, 4 de fuera), y el
        resultado no tiene ningún campo con una lista de lo descartado, solo contadores."""
        run, outcome = self.run_, self.run_.outcome
        taken = np.zeros(run.grid.shape, dtype=bool)
        for item in outcome.stockpiles:
            taken.ravel()[item.cells] = True
        for candidate in outcome.candidates.items:
            taken.ravel()[candidate.cells] = True
            taken[candidate.window] |= candidate.zone
        twelve = [name for name, label in run.classes.items() if label != "pass"]
        self.assertEqual(len(twelve), 12)
        places = [(notice.values["x"], notice.values["y"]) for notice in outcome.notices if "x" in notice.values]
        places += [(pair.x, pair.y) for pair in outcome.shared]
        for name in twelve:
            mound = run.mounds[name]
            with self.subTest(name):
                row, col = run.grid.nrows - int(mound.cy) - 1, int(mound.cx) - 1  # las cuatro celdas de la cima
                self.assertFalse(taken[row:row + 2, col:col + 2].any())
                left, bottom, right, top = mound.foot_box
                for x, y in places:
                    self.assertFalse(left <= x - sdata.BASE[0] <= right and bottom <= y - sdata.BASE[1] <= top)
        # T13: ``states`` es el estado de cada candidato que **pasó** los filtros (su clave y su decisión), nunca una lista de
        # lo que el filtro descarta.
        self.assertEqual(set(outcome.__dataclass_fields__), {"name", "code", "grid", "stockpiles", "rejected", "shared",
                                                             "candidates", "figures", "notices", "states"})
        self.assertEqual(outcome.states, (), "sin decisiones, el resultado de A2 a A5 no da estados")
        self.assertEqual(set(outcome.candidates.__dataclass_fields__),
                         {"grid", "items", "zones", "on_marks", "too_small", "too_large", "rejected"})

    def test_each_candidate_zone_is_the_hand_zone(self) -> None:
        """RF-016-08: la zona de cada candidato (las celdas del perímetro a más de la altura mínima sobre la apertura de
        31 m) es la zona conexa del montículo que sale de la apertura por fuerza bruta con enteros y una búsqueda en anchura
        (``hand_zone_index``), celda a celda."""
        run = self.run_
        for name, candidate in run.named_candidates():
            full = np.zeros(run.grid.shape, dtype=bool)
            full[candidate.window] = candidate.zone
            with self.subTest(name):
                np.testing.assert_array_equal(full, run.zones[name])

    def test_each_candidate_is_the_hand_one_to_a_nanometre(self) -> None:
        """CE-016-01, RF-016-08, D-11: de cada candidato, el plano (a ≤ 10⁻⁹ m en toda su ventana), la huella, el volumen
        (a ≤ 10⁻⁹ relativo), las vueltas y los avisos son los del cálculo a mano de A2 y A3 enteros sobre su zona."""
        run = self.run_
        for name, candidate in run.named_candidates():
            grown = run.grown[name]
            with self.subTest(name):
                self.assertEqual(candidate.window, grown.window)
                np.testing.assert_array_equal(candidate.footprint.mask, grown.mask)
                self.assertEqual(candidate.cells.tolist(), np.flatnonzero(grown.full(run.grid)).tolist())
                assert_plane_and_volume(self, grown, plane=candidate.footprint.plane,
                                        volume=candidate.footprint.volume_m3, turns=candidate.footprint.turns,
                                        converged=candidate.footprint.converged, label=name)
                self.assertEqual(candidate.footprint.area_m2, float(grown.mask.sum()))
                assert_notes(self, candidate.footprint.notes, hand_notes(grown), label=name)

    def test_each_candidate_volume_is_the_analytic_one_to_one_percent(self) -> None:
        """D-11: el volumen de cada candidato frente al analítico por encima del umbral (la suma exacta por anillos de su
        pirámide, 576, 676 o 784 celdas) a ≤ 1 %, con el plano a unos milímetros del sintético (T06: cuatro celdas de
        las esquinas de la propia pirámide caen en su corona); la huella, exactamente las celdas de los anillos."""
        run = self.run_
        synthetic = hand_plane_values(run.grid, sdata.SURVEY_TILT_DEG, sdata.SURVEY_PIVOT, sdata.SURVEY_Z_M)
        for name, candidate in run.named_candidates():
            mound = run.mounds[name]
            cells, volume = pyramid_rings(mound.foot, mound.top, mound.height, THRESHOLD_M)
            with self.subTest(name):
                self.assertEqual(int(candidate.footprint.mask.sum()), cells)
                self.assertLessEqual(abs(candidate.footprint.volume_m3 / float(volume) - 1.0), ANALYTIC)
                plane = candidate.footprint.plane.values(candidate.grid)
                self.assertLessEqual(float(np.abs(plane - synthetic[candidate.window]).max()), 0.01)

    def test_the_isolated_marked_stockpiles_are_the_hand_ones(self) -> None:
        """CE-016-01, RF-016-02, D-11: el Acopio 3 (pirámide de 5 m, con su margen de 6 m) y el 4 (cono): la huella son
        las celdas del montículo a más de 0,3 m (676 y 732), sin avisos; el plano, la huella y el volumen son los del
        cálculo a mano a ≤ 10⁻⁹ y el volumen es el analítico a ≤ 1 % (en el cono, el plano es el sintético a 10⁻⁹ m y el
        volumen, la suma de sus alturas)."""
        run = self.run_
        for name, cells in (("Acopio 3", 676), ("Acopio 4", 732)):
            item = next(item for item in run.outcome.stockpiles if item.key == name)
            grown = run.grown[name]
            height = hand_heights(run.grid, [run.mounds[name]])
            with self.subTest(name):
                self.assertEqual(item.cells.tolist(), np.flatnonzero(height > THRESHOLD_M).tolist())
                self.assertEqual(item.cells.size, cells)
                self.assertEqual(item.notes, ())
                assert_plane_and_volume(self, grown, plane=item.plane, volume=item.volume_m3, turns=item.turns,
                                        converged=item.converged, label=name)
                assert_notes(self, item.notes, hand_notes(grown), label=name)
                assert_layers(self, run.grid, grown, item, grown.mask, label=name)
        pyramid = run.mounds["Acopio 3"]
        _cells, volume = pyramid_rings(pyramid.foot, pyramid.top, pyramid.height, THRESHOLD_M)
        item3 = next(item for item in run.outcome.stockpiles if item.key == "Acopio 3")
        self.assertLessEqual(abs(item3.volume_m3 / float(volume) - 1.0), ANALYTIC)
        item4 = next(item for item in run.outcome.stockpiles if item.key == "Acopio 4")
        cone = hand_heights(run.grid, [run.mounds["Acopio 4"]])
        synthetic = hand_plane_values(run.grid, sdata.SURVEY_TILT_DEG, sdata.SURVEY_PIVOT, sdata.SURVEY_Z_M)
        rows, cols = np.divmod(item4.cells, run.grid.ncols)
        self.assertLessEqual(float(np.abs(item4.base - synthetic[rows, cols]).max()), EXACT)
        self.assertAlmostEqual(item4.volume_m3 / math.fsum(cone[cone > THRESHOLD_M].tolist()) - 1.0, 0.0, delta=EXACT)

    def test_the_two_that_touch_share_their_cells_with_a_warning(self) -> None:
        """E1, RF-016-06, D-16: el Acopio 1 y el 2 (sus marcas se tocan en x = 110 m y sus pies se solapan) son dos
        acopios de huellas disjuntas con la misma unión que las de cada marca sola: las 436 celdas comunes, repartidas por
        la recta de contacto, el aviso con las dos marcas y los 436 m² en cada acopio y una vez en el resumen, y el
        volumen de cada uno sobre lo que le queda a ≤ 10⁻⁹ del cálculo a mano."""
        run = self.run_
        pair = ("Acopio 1", "Acopio 2")
        self.assertEqual(len(run.outcome.shared), 1)  # y ninguna otra pareja: nada más se toca
        assert_pair(self, run.grid, [run.mounds[name] for name in pair], run.outcome, [run.grown[name] for name in pair],
                    pair, boundary=sdata.MARKS[0].box[2])

    def test_the_ground_without_stockpiles_is_the_terrain_under_them(self) -> None:
        """E1, RF-016-01, RF-016-09: el terreno sin acopios (``mín(z, base)`` en las huellas, la superficie fuera de ellas)
        es el terreno que había bajo los montones: el levantamiento anterior, a ≤ 2 cm en las huellas sobre un plano
        ajustado (a unos milímetros en la realidad), y exactamente (10⁻⁹ m) bajo el cono, cuyo plano es el sintético, y
        bajo el Acopio 5, cuya base es el levantamiento anterior; y fuera de las huellas, el propio levantamiento."""
        run, outcome = self.run_, self.run_.outcome
        ground = outcome.ground_grid()
        composed = np.where(np.isfinite(ground), ground, run.z)
        inside = np.isfinite(ground)
        self.assertEqual(int(inside.sum()), sum(item.cells.size for item in outcome.stockpiles))
        self.assertLessEqual(float(np.abs(composed - run.previous)[inside].max()), 0.02)
        np.testing.assert_array_equal(composed[~inside], run.z[~inside])
        for name in ("Acopio 4", "Acopio 5"):
            item = next(item for item in outcome.stockpiles if item.key == name)
            rows, cols = np.divmod(item.cells, run.grid.ncols)
            np.testing.assert_allclose(composed[rows, cols], run.previous[rows, cols], rtol=0.0, atol=EXACT,
                                       err_msg=name)

    def test_every_layer_is_the_hand_layer(self) -> None:
        """RF-016-01, RF-016-09: en cada acopio, la base, el espesor ``máx(z − base, 0)``, el terreno sin acopios y la
        superficie son los de ``oracles.hand_layers`` sobre su huella y la base del cálculo a mano; el espesor nunca es
        negativo y su suma por el área, donde pasa del umbral, es el volumen."""
        run = self.run_
        pair = ("Acopio 1", "Acopio 2")
        shares, _common = share_by_hand(run.grid, [run.grown[name] for name in pair], names=pair)
        for item in run.outcome.stockpiles:
            grown = run.grown[item.key]
            mask = shares[pair.index(item.key)][grown.window] if item.key in pair else grown.mask
            with self.subTest(item.key):
                assert_layers(self, run.grid, grown, item, mask, label=item.key)

    def test_each_material_has_its_own_base_and_thickness(self) -> None:
        """RF-016-09, D-19: «mineral» (Acopio 1, 2 y 5) y «estéril» (3 y 4), cada material con su base y su espesor, solo
        en sus huellas (NaN fuera) y con el espesor de cada acopio en las suyas."""
        run, outcome = self.run_, self.run_.outcome
        by_material: dict[str, list[Any]] = {"mineral": [], "estéril": []}
        for mark in sdata.MARKS:
            by_material[mark.material].append(next(item for item in outcome.stockpiles if item.key == mark.name))
        self.assertEqual({k: [i.key for i in v] for k, v in by_material.items()},
                         {"mineral": ["Acopio 1", "Acopio 2", "Acopio 5"], "estéril": ["Acopio 3", "Acopio 4"]})
        for material, items in by_material.items():
            union = np.zeros(run.grid.shape, dtype=bool)
            for item in items:
                union.ravel()[item.cells] = True
            base, thickness = outcome.base_grid(material), outcome.thickness_grid(material)
            np.testing.assert_array_equal(np.isfinite(base), union, material)
            np.testing.assert_array_equal(np.isfinite(thickness), union, material)
            for item in items:
                np.testing.assert_array_equal(thickness.ravel()[item.cells], item.thickness)
                np.testing.assert_array_equal(base.ravel()[item.cells], item.base)

    def test_the_figures_are_the_hand_ones(self) -> None:
        """RF-016-02, RF-016-08, CE-016-01: ``des.stk_count`` 5 y ``des.stk_candidates`` 8, y por acopio (con su ámbito:
        el acopio y su material) el volumen del cálculo a mano a ≤ 10⁻⁹ relativo."""
        run, outcome = self.run_, self.run_.outcome
        values = {(f.key, f.scope.get("stockpile")): f.value for f in outcome.figures}
        self.assertEqual((values["des.stk_count", None], values["des.stk_candidates", None]), (5.0, 8.0))
        pair = ("Acopio 1", "Acopio 2")
        shares, _common = share_by_hand(run.grid, [run.grown[name] for name in pair], names=pair)
        for item in outcome.stockpiles:
            grown = run.grown[item.key]
            mask = shares[pair.index(item.key)][grown.window] if item.key in pair else grown.mask
            hand = oracles.hand_volume(grown.z.tolist(), grown.base.tolist(), mask.tolist(), run.grid.cell_area,
                                       THRESHOLD_M)
            self.assertAlmostEqual(values["des.stk_volume_m3", item.key] / hand - 1.0, 0.0, delta=EXACT, msg=item.key)


class PairTest(unittest.TestCase):
    """E1 en el dominio: el Acopio 1 y el 2 (troncos de pirámide de pie 12 m, cima 4 m y 4 m de alto, a 20 m uno de otro)
    **solos** en una ventana de 120 × 120 celdas de 1 m sobre un plano de 3°, con el reparto de sus celdas comunes y su
    aviso. Con celdas de 2 m el par es pequeño para la celda (``docs/trampas.md`` §2): E1 va con 1 m."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.case = sdata.touching_pair()
        grid = cls.case.grid
        cls.names = tuple(mark.name for mark in cls.case.marks)
        cls.masks = [box_mask(grid, mark.box) for mark in cls.case.marks]
        cls.marks = tuple(stockpiles.StockpileMark(key=mark.name, cells=np.flatnonzero(mask), material=mark.material)
                          for mark, mask in zip(cls.case.marks, cls.masks, strict=True))
        cls.outcome = cls.detect(cls.marks)
        cls.grown = [grow_by_hand(cls.case.terrain, grid, mask, margin_m=D3["margin_m"]) for mask in cls.masks]
        cls.truth = hand_heights(grid, cls.case.mounds)

    @classmethod
    def detect(cls, marks: Sequence[Any]) -> Any:
        job = stockpiles.StockpileJob(name="Detección de prueba", code="STK-001", grid=cls.case.grid,
                                      surface=cls.case.terrain, marks=tuple(marks), params=footprint_params())
        return stockpiles.detect_stockpiles(job)

    def test_the_case_is_the_one_in_the_statement(self) -> None:
        """La cantera: dos pirámides de 12 / 4 / 4 m en (50, 60) y (70, 60) locales sobre el plano de 3° por 115 m en
        el centro (donde se solapan, la mayor), con sus marcas de 20 × 20 m que se tocan en x = 60 m."""
        case = self.case
        self.assertEqual([(m.cx, m.cy, m.foot, m.top, m.height) for m in case.mounds],
                         [(50.0, 60.0, 12.0, 4.0, 4.0), (70.0, 60.0, 12.0, 4.0, 4.0)])
        np.testing.assert_allclose(case.height, self.truth, rtol=0.0, atol=1e-12)
        np.testing.assert_allclose(case.base, hand_plane_values(case.grid, 3.0, sdata.WINDOW_PIVOT, sdata.WINDOW_Z_M),
                                   rtol=0.0, atol=1e-12)
        self.assertEqual([mark.box for mark in case.marks], [(40.0, 50.0, 60.0, 70.0), (60.0, 50.0, 80.0, 70.0)])

    def test_the_cells_are_shared_by_the_rule_with_its_warning_and_volumes_by_hand(self) -> None:
        """E1, RF-016-06, D-16, RF-016-02: la huella de cada marca sola es la cuenta cerrada del montón sobre su marca
        ampliada; las 436 celdas comunes se reparten por x = 60 m (a la marca que las contiene o, fuera de las dos, a la
        más próxima); el aviso con las dos marcas, 436 m² y el centro (60, 60); el volumen de cada uno sobre lo que le
        queda a ≤ 10⁻⁹ del cálculo a mano y la suma a ≤ 1 % de las alturas de la unión."""
        assert_pair(self, self.case.grid, self.case.mounds, self.outcome, self.grown, self.names, boundary=60.0)
        (pair,) = self.outcome.shared
        self.assertAlmostEqual(pair.x, sdata.BASE[0] + 60.0, delta=1e-6)
        self.assertAlmostEqual(pair.y, sdata.BASE[1] + 60.0, delta=1e-6)
        self.assertEqual(pair.area_m2, 436.0)

    def test_the_sum_of_the_volumes_is_the_one_of_the_union(self) -> None:
        """RF-016-06: nada se cuenta dos veces ni se pierde: la suma de los dos volúmenes (≈ 2.143 m³) es la de las alturas
        de las celdas de la unión a más de 0,3 m (2.145 m³ a mano) a 0,2 % (los planos están a un par de centímetros)."""
        total = math.fsum(self.truth[self.truth > THRESHOLD_M].tolist())
        self.assertEqual(total, 2145.0)
        both = sum(item.volume_m3 for item in self.outcome.stockpiles)
        self.assertLessEqual(abs(both / total - 1.0), 2e-3)

    def test_the_order_of_the_marks_in_the_job_does_not_change_the_result(self) -> None:
        """Con las marcas en el otro orden salen los mismos acopios con las mismas celdas y el mismo volumen (lo que sale
        es el orden del trabajo): el reparto no depende del orden."""
        swapped = self.detect(self.marks[::-1])
        self.assertEqual([item.key for item in swapped.stockpiles], list(self.names[::-1]))
        for item in swapped.stockpiles:
            before = next(found for found in self.outcome.stockpiles if found.key == item.key)
            self.assertEqual(item.cells.tolist(), before.cells.tolist())
            self.assertAlmostEqual(item.volume_m3 / before.volume_m3 - 1.0, 0.0, delta=EXACT)


# --- RF-016-03: la base propia --------------------------------------------------------------------------------------


class OwnBaseTest(unittest.TestCase):
    """RF-016-03, D-20: el Acopio 5 (pirámide de 5 m) sobre la superficie del levantamiento anterior, que lleva una
    terraza de 0,5 m bajo su pie, como base: sin plano, corona, ajuste ni límite de inclinación."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.run_ = survey_run()
        cls.item = next(item for item in cls.run_.outcome.stockpiles if item.key == "Acopio 5")
        cls.mound = cls.run_.mounds["Acopio 5"]
        cls.height = hand_heights(cls.run_.grid, [cls.mound])

    def test_the_stockpile_notes_the_surface_its_base_comes_from_and_has_no_plane(self) -> None:
        """RF-016-03: anota de qué superficie sale su base y no tiene plano (ni su cota, pendiente o azimut), una sola vuelta
        que ya converge y ninguna nota de corona, ajuste o inclinación; es del material de su marca."""
        item = self.item
        self.assertEqual(item.base_surface, sdata.PREVIOUS_LABEL)
        self.assertIsNone(item.plane)
        self.assertEqual((item.plane_level_m, item.plane_slope_percent, item.plane_azimuth_deg, item.plane_tilt_deg),
                         (None, None, None, None))
        self.assertEqual((item.turns, item.converged), (1, True))
        self.assertEqual(item.notes, ())
        self.assertEqual(item.material, "mineral")
        self.assertEqual([f.key for f in self.run_.outcome.figures if f.scope.get("stockpile") == "Acopio 5"],
                         ["des.stk_area_m2", "des.stk_volume_m3", "des.stk_thickness_max_m"])  # sin inclinación

    def test_the_base_is_the_previous_survey_and_the_thickness_is_the_height_of_the_pile(self) -> None:
        """RF-016-01, RF-016-03: la base de cada celda de la huella es el levantamiento anterior bit a bit (con su terraza) y
        el espesor es la altura de la pirámide sobre él (``z − base``, a ≤ 10⁻⁹): la terraza no es del acopio. El terreno
        sin acopios es la propia base."""
        run, item = self.run_, self.item
        rows, cols = np.divmod(item.cells, run.grid.ncols)
        self.assertEqual(item.base.tobytes(), run.previous[rows, cols].tobytes())
        np.testing.assert_allclose(item.thickness, self.height[rows, cols], rtol=0.0, atol=EXACT)
        np.testing.assert_array_equal(item.ground, run.previous[rows, cols])
        terrace = box_mask(run.grid, sdata.TERRACE_BOX)[rows, cols]
        # las celdas de la terraza (x > 240 m) que quedan bajo la huella (x de 226 a 254 m, y de 206 a 234 m): 14 × 28
        self.assertEqual(int(terrace.sum()), 14 * 28)
        self.assertTrue((item.thickness[terrace] > THRESHOLD_M).all())

    def test_the_footprint_and_the_volume_are_the_pyramid_by_rings_exactly(self) -> None:
        """RF-016-02, RF-016-03, D-11: la huella son las celdas de la pirámide a más de 0,3 m (784, contadas por anillos) y
        el volumen es la suma exacta por anillos (racionales) a ≤ 10⁻⁹ relativo, igual al cálculo a mano de A3 sobre la base
        propia (``cut_by_hand``)."""
        run, item, mound = self.run_, self.item, self.mound
        cells, volume = pyramid_rings(mound.foot, mound.top, mound.height, THRESHOLD_M)
        self.assertEqual((item.cells.size, cells), (784, 784))
        self.assertEqual(item.cells.tolist(), np.flatnonzero(self.height > THRESHOLD_M).tolist())
        self.assertAlmostEqual(item.volume_m3 / float(volume) - 1.0, 0.0, delta=EXACT)
        grown = run.grown["Acopio 5"]
        self.assertEqual(item.cells.tolist(), np.flatnonzero(grown.full(run.grid)).tolist())
        self.assertAlmostEqual(item.volume_m3 / grown.volume - 1.0, 0.0, delta=EXACT)
        assert_layers(self, run.grid, grown, item, grown.mask)

    def test_the_terrace_would_count_if_the_base_were_the_plane(self) -> None:
        """El control de RF-016-03: con el plano de la corona en lugar del levantamiento anterior, la terraza de 0,5 m (más
        que el umbral de 0,3 m sobre el plano) entra en la huella de la marca, que tiene más celdas que con la base propia
        (el ajuste del plano absorbe parte de la terraza, que está en un solo lado de la corona): el resultado con la base
        propia es, de verdad, otro."""
        run, item = self.run_, self.item
        plain = grow_by_hand(run.z, run.grid, box_mask(run.grid, sdata.MARKS[4].box), margin_m=D3["margin_m"])
        self.assertGreater(int(plain.mask.sum()), item.cells.size)
        self.assertNotAlmostEqual(plain.volume, item.volume_m3, delta=1.0)

# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo alcanzable, las cotas y lo comunicado de la accesibilidad (spec 017, T15 y T16; HU-017-3; RF-017-24, RF-017-25 y RF-017-04; RNF-017-05 y RNF-017-06; plan 017 §5.4 A10 y
A11, D-17 y T15-a). Dominio puro: sin proyecto y sin ``bpy``. **A10** (T15: lo alcanzable y las cotas) y **A11** (T16: las bermas, las plataformas y las zonas «requiere acceso»
comunicadas y la cota mínima sobre la superficie final de una cantera).

Lo que entrega, con las coordenadas absolutas en float64 (regla 4 de AGENTS.md) y todo lo que vuelve de solo lectura:

- :func:`access` (y :func:`access_steps`, por pasos; :func:`access_units`, las unidades para componerlas con otras): el :class:`~.road_model.AccessOutcome` de un
  :class:`~.road_model.AccessJob` —lo **alcanzable** (una rejilla booleana), las cotas mínima y máxima alcanzables (m) y el área alcanzable (m²)— y, de A11, la **comunicación** de
  cada tramo de berma, plataforma y zona «requiere acceso» y la cota mínima alcanzable sobre la superficie final de una cantera con dos superficies. No cambia ninguna superficie ni
  restricción (RF-017-25): lo que lee son vistas de solo lectura.
- :func:`local_slope_pct`: la **pendiente local** (%) de cada celda, la mayor tangente a sus ocho vecinas con dato (:func:`design.report.max_tangents`, que la plataforma y la pista
  ya usan, por bandas de filas con sus vecinas); sin dato, o sin ninguna vecina con dato, no tiene pendiente (``nan``).
- :func:`reach_units` y :class:`Reach`: la misma cuenta sobre **una superficie** que se da (la del trabajo, o, en una cantera con dos superficies, su superficie final: T16) con las
  entradas ya resueltas por :func:`entry_cells`.

**Qué es alcanzable** (A10, RF-017-24, D-17): una celda es **transitable** si tiene dato, su pendiente local es ``≤`` la pendiente máxima transitable y no está en ``untouchable``
(lo que las máscaras prohíben atravesar: los intocables y las exclusiones de la 012, las mismas que impiden pisar a la ruta, RF-017-06; **las demás clases de la 012 se atraviesan**:
decisión de la sesión principal T15-a, que arma la preparación en la máscara del trabajo). El **ancho mínimo** transitable es una **apertura** con un disco exacto de radio
``ancho / 2`` (:func:`design.morphology.opening_steps`: lo que un disco de ese diámetro puede tocar por dentro: un paso más estrecho desaparece). **Lo alcanzable** son las
componentes 4-conexas (:func:`design.grids.label_components_steps`) de lo transitable abierto que contienen un punto de entrada.

**A11** (RF-017-25, D-17; sobre lo alcanzable de la superficie del trabajo, la de explotación): un **tramo de berma** es una componente 4-conexa de las celdas con cota de la rejilla de
bermas de la 013 (:class:`~.road_model.BermGrid`) con al menos ``min_berm_area_m2`` (los menores **no se listan**), con su cota real (la media de las de sus celdas), su área, su lugar
(el centroide de sus celdas) y si está **comunicado** (alguna de sus celdas es alcanzable); una **plataforma** está comunicada si alguna celda alcanzable cae en su huella y a la **menor
cota** de esas celdas; una zona **«requiere acceso»**, si alguna de sus celdas es alcanzable y, si no, con su lugar (su celda más próxima a lo alcanzable), la distancia (m) y la diferencia
de cota (la de la celda alcanzable más próxima menos la de la celda de la zona). En una cantera con dos superficies (``job.final``), la cota mínima alcanzable sobre la final, con los mismos
parámetros y la misma máscara de lo intocable.

**Interpretaciones** (la spec y el plan no las dicen; revisables, anotadas en la verificación de T15 y de T16): (1) una celda con dato y **sin ninguna vecina con dato** no tiene pendiente y no
es transitable; (2) la comparación con la pendiente máxima tiene la tolerancia relativa de :data:`SLOPE_TOLERANCE` (10⁻¹²: el ruido de la última cifra de dividir cotas; una rampa
justa del 7 % de 0,07 m por metro sale 7,000000000000001 %), muy por debajo de 10⁻⁹ %; (3) un punto de entrada en una celda **no transitable** (en una pendiente, en lo intocable o en
un paso más estrecho que el ancho mínimo) no alcanza nada y **no se rechaza**: RF-017-04 solo rechaza la capa sin puntos o con uno **sin dato** (una celda sin cota o fuera de la
rejilla) y se hace **antes de calcular**; (4) las celdas son cuadradas (la rejilla del proyecto lo es) porque el disco de la apertura lo es; (5) (T16) el lugar de un tramo de berma es el
centroide de sus celdas y el de una zona sin comunicar, su celda más próxima a lo alcanzable (a igual distancia, la de menor índice); la cota real de un tramo, la media de las de sus
celdas; la diferencia de cota de una zona tiene signo (positiva si lo alcanzable más próximo está más alto que la zona); una entrada sin dato en la superficie final no se rechaza (no
alcanza nada: la cota mínima sobre la final es ``None``).

Los pasos (:func:`access_steps`) ceden el hilo cada ≈ 0,05 s (``pace_progress``; RNF-017-06): la pendiente y las cotas van por bandas de filas, y la apertura y las componentes son
las de ``morphology`` y ``grids``, por unidades. Cerrar el generador a mitad no deja nada: no escribe nada y no modifica sus entradas (principio 7). **Perezoso** (RNF-001-03): ni
``design.model`` ni nada del arranque lo importan.
"""

from __future__ import annotations

import math
from collections.abc import Generator, Iterator
from contextlib import closing
from dataclasses import dataclass

import numpy as np

from ..core.project.model import Progress
from ..gis.grid import Grid
from ..gis.masks.compile import STEP_BUDGET_S
from .grids import label_components_steps, nearest_value_steps
from .messages import DesignError
from .morphology import opening_steps
from .params import AccessParam, entity_key
from .report import REPORT_CELLS_PER_UNIT, max_tangents, padded_rows
from .road_model import AccessJob, AccessOutcome, BermGrid, BermReach, PlatformReach, ZoneReach
from .seeds import pace_progress

__all__ = [
    "SLOPE_TOLERANCE",
    "Reach",
    "access",
    "access_steps",
    "access_units",
    "entry_cells",
    "local_slope_pct",
    "reach_units",
]

SLOPE_TOLERANCE = 1e-12
"""La tolerancia relativa con que se compara la pendiente local con la máxima transitable: el ruido de la última cifra de dividir dos cotas (0,07 m en 1 m, ``· 100``, da
7,000000000000001), que no admite una rampa con 10⁻⁹ % de más (relativamente, ≈ 10⁻¹⁰)."""
_PHASE = "road_access"


@dataclass(frozen=True, slots=True, eq=False)
class Reach:
    """Lo alcanzable sobre una superficie (A10): ``reachable`` (booleana de la forma de la rejilla, de solo lectura), las cotas mínima y máxima de sus celdas (``z_min_m`` y
    ``z_max_m``, m, de la superficie; ``None`` si no se alcanza ninguna) y su área (``area_m2``, m²)."""

    reachable: np.ndarray
    z_min_m: float | None
    z_max_m: float | None
    area_m2: float


# --- La pendiente local ----------------------------------------------------------------------------------------------------------


def _surface(surface: object, grid: Grid, what: str = "la superficie") -> np.ndarray:
    """``surface`` como array float64 de la forma de ``grid`` (``ValueError``, un error del programa, si no lo es)."""
    found = np.asarray(surface, dtype=np.float64)
    if found.shape != grid.shape:
        raise ValueError(f"{what} es de la forma de la rejilla {grid.shape}, no {found.shape}")
    return found


def _band_rows(grid: Grid, band_rows: int | None) -> int:
    """Las filas de cada banda: las dadas o las que caben en ``REPORT_CELLS_PER_UNIT`` celdas (≈ 6 ms con la pendiente de la plataforma)."""
    if band_rows is None:
        return max(1, REPORT_CELLS_PER_UNIT // max(grid.ncols, 1))
    if isinstance(band_rows, bool) or not isinstance(band_rows, int | np.integer) or band_rows < 1:
        raise ValueError(f"las filas de cada banda son un entero ≥ 1, no {band_rows!r}")
    return int(band_rows)


def _band_tangents(surface: np.ndarray, grid: Grid, first: int, last: int) -> np.ndarray:
    """La mayor tangente a las ocho vecinas de las celdas de las filas ``first:last`` de ``surface`` (``nan`` sin ninguna con dato): la banda con la fila de arriba y la de abajo
    (si las hay), así que da lo mismo que toda la rejilla de una vez."""
    low, high = max(first - 1, 0), min(last + 1, grid.nrows)
    start = 1 + first - low
    return max_tangents(padded_rows(surface, low, high), grid.dx, grid.dy)[start:start + (last - first), 1:grid.ncols + 1]


def local_slope_pct(surface: np.ndarray, grid: Grid, *, band_rows: int | None = None) -> np.ndarray:
    """La pendiente local (%) de cada celda de ``surface`` (m, de la forma de ``grid``; ``nan``, sin dato): la mayor tangente a sus ocho vecinas con dato (la diagonal, a la
    distancia de sus centros), por bandas de ``band_rows`` filas (``None``: las de unas 200.000 celdas; el resultado es el mismo bit a bit con cualquier número). Una celda sin
    dato, o sin ninguna vecina con dato, da ``nan``. Un array nuevo; ``surface`` no se modifica. ``ValueError`` si no es de la forma de la rejilla o ``band_rows`` no es un entero ≥ 1."""
    found = _surface(surface, grid)
    per = _band_rows(grid, band_rows)
    slope = np.empty(grid.shape, dtype=np.float64)
    for first in range(0, grid.nrows, per):
        last = min(grid.nrows, first + per)
        slope[first:last] = _band_tangents(found, grid, first, last) * 100.0
    return slope


def _walkable_units(job: AccessJob, surface: np.ndarray) -> Generator[None, None, np.ndarray]:
    """Las unidades (una banda de filas cada una) de las celdas transitables de ``surface``: con pendiente local ``≤`` la máxima transitable (con la tolerancia de
    :data:`SLOPE_TOLERANCE`; ``nan`` no lo es: sin dato o sin vecinas con dato) y no intocables."""
    grid = job.grid
    limit = job.walk_slope_pct / 100.0 * (1.0 + SLOPE_TOLERANCE)
    walkable = np.empty(grid.shape, dtype=np.bool_)
    per = _band_rows(grid, None)
    for first in range(0, grid.nrows, per):
        last = min(grid.nrows, first + per)
        tangents = _band_tangents(surface, grid, first, last)
        with np.errstate(invalid="ignore"):
            walkable[first:last] = (tangents <= limit) & ~job.untouchable[first:last]
        yield None
    return walkable


# --- Los puntos de entrada --------------------------------------------------------------------------------------------------------


def entry_cells(job: AccessJob) -> tuple[np.ndarray, np.ndarray]:
    """Las celdas de los puntos de entrada de ``job``: sus filas y sus columnas (``intp``, en el orden de las entradas), con la celda de un punto en el borde de dos a la del este
    y a la del sur (como la malla de la pista). **RF-017-04:** ninguna entrada se rechaza con ``des.access_no_entry`` y una **sin dato** en la superficie del trabajo (una celda sin
    cota, o un punto fuera de la rejilla) con ``des.access_entry_no_data`` (la primera de la lista), nombrando la capa, la accesibilidad, el punto, la superficie y su lugar (x e y
    absolutas, al cm), sin elegir ningún valor por la persona (``DesignError``)."""
    grid, request = job.grid, job.request
    shared = {"layer": request.layer, "entity": request.name}
    where = f"Accesibilidad «{request.name}» de la capa «{request.layer}»"
    field = entity_key(job.code, AccessParam.ENTRIES_LAYER)
    if not job.entries:
        raise DesignError("des.access_no_entry", obj=where, field=field, value=request.layer, **shared)
    rows: list[int] = []
    cols: list[int] = []
    for entry in job.entries:
        column = math.floor((entry.x - grid.west) / grid.dx)
        row = math.floor((grid.north - entry.y) / grid.dy)
        if not (0 <= row < grid.nrows and 0 <= column < grid.ncols) or not math.isfinite(float(job.surface[row, column])):
            raise DesignError("des.access_entry_no_data", obj=where, field=field, value=entry.name, surface=request.surface, x=round(entry.x, 2), y=round(entry.y, 2), **shared)
        rows.append(row)
        cols.append(column)
    return np.asarray(rows, dtype=np.intp), np.asarray(cols, dtype=np.intp)


# --- Lo alcanzable ----------------------------------------------------------------------------------------------------------------


def _square(grid: Grid) -> None:
    """``ValueError`` (un error del programa) si las celdas de ``grid`` no son cuadradas: el disco del ancho mínimo lo es y la rejilla del proyecto también."""
    if grid.dx != grid.dy:
        raise ValueError(f"la accesibilidad pide celdas cuadradas (el disco del ancho mínimo lo es), no {grid.dx} × {grid.dy} m")


def _drain[T](steps: Iterator[Progress]) -> Generator[None, None, T]:
    """Las unidades de un cálculo por pasos (``steps``: cada ``Progress`` es una unidad) y, al terminar, su resultado; cerrar el generador cierra ``steps``. Es lo que deja
    componer la apertura y las componentes (``morphology``, ``grids``) con ``yield from`` dentro de las unidades de la accesibilidad."""
    with closing(steps):  # type: ignore[type-var]
        for step in steps:
            if step.result is not None:
                return step.result  # type: ignore[no-any-return]
            yield None
    raise RuntimeError("los pasos terminaron sin dar resultado")


def reach_units(job: AccessJob, surface: np.ndarray, entries: tuple[np.ndarray, np.ndarray], *, budget_s: float = STEP_BUDGET_S) -> Generator[None, None, Reach]:
    """Las unidades (cada ``yield``, una; el :class:`Reach` es el valor de ``StopIteration``) de **A10** sobre ``surface`` (m, de la forma de la rejilla de ``job``; la del
    trabajo o, en una cantera con dos superficies, su final) con los umbrales, lo intocable y la rejilla de ``job`` y las celdas de entrada ``entries`` (:func:`entry_cells`:
    filas y columnas): las celdas transitables, su apertura con el disco del ancho mínimo, las componentes 4-conexas y las que tienen una entrada (lo alcanzable), con sus cotas
    mínima y máxima y su área. Una entrada fuera de lo transitable abierto no alcanza nada. ``ValueError`` si ``surface`` no es de la forma de la rejilla o las celdas no son
    cuadradas (la rejilla del proyecto lo es)."""
    grid = job.grid
    found = _surface(surface, grid)
    _square(grid)
    rows, cols = entries
    return _reach_units(job, found, rows, cols, budget_s)


def _reach_units(job: AccessJob, surface: np.ndarray, rows: np.ndarray, cols: np.ndarray, budget_s: float) -> Generator[None, None, Reach]:
    grid = job.grid
    walkable = yield from _walkable_units(job, surface)
    opened: np.ndarray = yield from _drain(opening_steps(walkable, job.walk_width_m / 2.0, grid.dx, budget_s=budget_s))
    labels = yield from _drain(label_components_steps(opened, budget_s=budget_s))
    tags = labels.grid[rows, cols]
    wanted = np.unique(tags[tags > 0])
    yield None
    reachable = np.zeros(grid.shape, dtype=np.bool_)
    low: float | None = None
    high: float | None = None
    cells = 0
    if wanted.size:
        keep = np.zeros(labels.count + 1, dtype=np.bool_)
        keep[wanted] = True
        per = _band_rows(grid, None)
        for first in range(0, grid.nrows, per):
            last = min(grid.nrows, first + per)
            band = keep[labels.grid[first:last]]
            reachable[first:last] = band
            inside = surface[first:last][band]
            if inside.size:
                lowest, highest = float(inside.min()), float(inside.max())
                low = lowest if low is None else min(low, lowest)
                high = highest if high is None else max(high, highest)
                cells += int(inside.size)
            yield None
    reachable.flags.writeable = False
    return Reach(reachable, low, high, cells * grid.cell_area)


# --- La accesibilidad -------------------------------------------------------------------------------------------------------------


def access_units(job: AccessJob, *, budget_s: float = STEP_BUDGET_S) -> Generator[None, None, AccessOutcome]:
    """Las unidades de :func:`access_steps` (cada ``yield``, una; el :class:`~.road_model.AccessOutcome` es el valor de ``StopIteration``): para componerlas con otras unidades del
    cálculo de la accesibilidad con ``yield from``. Los rechazos de RF-017-04 (:func:`entry_cells`) y los de forma, **al llamar**, antes de la primera unidad."""
    if not isinstance(job, AccessJob):
        raise TypeError(f"el trabajo de una accesibilidad es AccessJob, no {job!r}")
    _square(job.grid)
    entries = entry_cells(job)
    return _units(job, entries, budget_s)


def _units(job: AccessJob, entries: tuple[np.ndarray, np.ndarray], budget_s: float) -> Generator[None, None, AccessOutcome]:
    reach = yield from reach_units(job, job.surface, entries, budget_s=budget_s)
    z_min_final: float | None = None
    if job.final is not None:  # una cantera con dos superficies (error 23): la misma cuenta sobre la final, con los mismos umbrales y lo mismo intocable
        final = yield from reach_units(job, job.final, entries, budget_s=budget_s)
        z_min_final = final.z_min_m
    berms = yield from _berm_units(job, reach.reachable, budget_s)
    platforms = _platform_reach(job, reach.reachable)
    yield None
    zones = yield from _zone_units(job, reach.reachable, budget_s)
    return AccessOutcome(name=job.request.name, code=job.code, reachable=reach.reachable, z_min_m=reach.z_min_m, z_max_m=reach.z_max_m, area_m2=reach.area_m2,
                         z_min_final_m=z_min_final, berms=berms, platforms=platforms, zones=zones)


# --- Bermas, plataformas y zonas comunicadas (A11) ---------------------------------------------------------------------------------

_STRETCHES_PER_UNIT = 1_000
"""Los tramos de berma que se construyen en cada unidad de trabajo (≈ 10 µs cada uno con su validación: con los 24.586 del plan, varios pasos de ≤ 0,05 s)."""


def _berm_units(job: AccessJob, reachable: np.ndarray, budget_s: float) -> Generator[None, None, tuple[BermReach, ...]]:
    """Los tramos de berma (A11, RF-017-25) de cada dato de bermas del trabajo, en su orden y numerados de seguido, con ``reachable`` (lo alcanzable sobre la superficie del trabajo)."""
    found: list[BermReach] = []
    for berm in job.berms:
        stretches = yield from _stretch_units(job, berm, reachable, len(found) + 1, budget_s)
        found.extend(stretches)
    return tuple(found)


def _stretch_units(job: AccessJob, berm: BermGrid, reachable: np.ndarray, first_number: int, budget_s: float) -> Generator[None, None, list[BermReach]]:
    """Los tramos de ``berm`` (A11): cada **componente 4-conexa** de sus celdas con cota (``label_components_steps``) de al menos ``min_berm_area_m2`` m² (los menores **no se
    listan**), numerados desde ``first_number`` en el orden de su primera celda recorriendo la rejilla desde el norte, con su **cota real** (la media de las de sus celdas: la de la
    berma si es plana), su área (m²), su lugar (el centroide de sus celdas, absoluto) y si queda **comunicado** (alguna de sus celdas es alcanzable: ``np.bincount`` con pesos por
    etiqueta, una pasada por bandas de filas)."""
    grid = job.grid
    with_level = np.isfinite(berm.levels)
    yield None
    if not with_level.any():
        return []
    labels = yield from _drain(label_components_steps(with_level, budget_s=budget_s))
    total = labels.count + 1
    level_sum, row_sum, col_sum, reached = (np.zeros(total) for _ in range(4))
    per = _band_rows(grid, None)
    for first in range(0, grid.nrows, per):
        last = min(grid.nrows, first + per)
        band = labels.grid[first:last]
        rows, cols = np.nonzero(band)
        if rows.size:
            tags = band[rows, cols]
            level_sum += np.bincount(tags, weights=berm.levels[first:last][rows, cols], minlength=total)
            row_sum += np.bincount(tags, weights=rows + first, minlength=total)
            col_sum += np.bincount(tags, weights=cols, minlength=total)
            reached += np.bincount(tags, weights=reachable[first:last][rows, cols], minlength=total)
        yield None
    cells = labels.sizes
    listed = np.flatnonzero(cells * grid.cell_area >= job.min_berm_area_m2)
    count = cells[listed].astype(np.float64)
    tags = listed + 1
    levels = level_sum[tags] / count
    x = grid.west + (col_sum[tags] / count + 0.5) * grid.dx
    y = grid.north - (row_sum[tags] / count + 0.5) * grid.dy
    connected = reached[tags] > 0.0
    stretches: list[BermReach] = []
    for start in range(0, listed.size, _STRETCHES_PER_UNIT):
        for k in range(start, min(listed.size, start + _STRETCHES_PER_UNIT)):
            stretches.append(BermReach(first_number + k, float(levels[k]), float(count[k]) * grid.cell_area, bool(connected[k]), float(x[k]), float(y[k]), berm.name))
        yield None
    return stretches


def _platform_reach(job: AccessJob, reachable: np.ndarray) -> tuple[PlatformReach, ...]:
    """Las plataformas (A11, RF-017-25): cada una queda **comunicada** si alguna celda alcanzable cae en su huella y, entonces, a la **menor cota** de la superficie del trabajo entre
    las celdas alcanzables de su huella (no la menor de la huella); si no, ``None``."""
    flat_reach, flat_surface = reachable.ravel(), job.surface.ravel()
    found: list[PlatformReach] = []
    for platform in job.platforms:
        hit = flat_reach[platform.cells]
        found.append(PlatformReach(platform.code, True, float(flat_surface[platform.cells][hit].min())) if hit.any() else PlatformReach(platform.code, False))
    return tuple(found)


def _zone_units(job: AccessJob, reachable: np.ndarray, budget_s: float) -> Generator[None, None, tuple[ZoneReach, ...]]:
    """Las zonas «requiere acceso» (A11, RF-017-25): cada una queda **comunicada** si alguna de sus celdas es alcanzable; las que no (y tienen celdas), con su **lugar** (su celda más
    próxima a lo alcanzable —a igual distancia, la de menor índice—, o su primera celda si no se alcanza nada), la **distancia** (m, entre centros, exacta:
    :func:`design.grids.nearest_value_steps`, solo si hay alguna zona sin comunicar) y la **diferencia de cota** (m: la cota de la celda alcanzable más próxima —a igual distancia, la
    menor— menos la de la celda de la zona, con signo). Una zona sin celdas no queda comunicada y no lleva lugar."""
    grid = job.grid
    flat_reach = reachable.ravel()
    missing = [bool(zone.cells.size) and not bool(flat_reach[zone.cells].any()) for zone in job.zones]
    nearest = None
    if any(missing) and bool(flat_reach.any()):
        nearest = yield from _drain(nearest_value_steps(reachable, job.surface, grid.dx, budget_s=budget_s))
    found: list[ZoneReach] = []
    for zone, lost in zip(job.zones, missing, strict=True):
        if not zone.cells.size:
            found.append(ZoneReach(zone.code, False))
        elif not lost:
            found.append(ZoneReach(zone.code, True))
        elif nearest is None:  # no se alcanza nada: sin nada desde donde medir
            row, col = divmod(int(zone.cells.min()), grid.ncols)
            found.append(ZoneReach(zone.code, False, grid.west + (col + 0.5) * grid.dx, grid.north - (row + 0.5) * grid.dy))
        else:
            rows, cols = np.divmod(zone.cells, grid.ncols)
            squared = nearest.cells2[rows, cols]
            closest = int(squared.min())
            row, col = divmod(int(zone.cells[squared == closest].min()), grid.ncols)
            here, there = float(job.surface[row, col]), float(nearest.value[row, col])
            difference = there - here if math.isfinite(here) and math.isfinite(there) else None
            found.append(ZoneReach(zone.code, False, grid.west + (col + 0.5) * grid.dx, grid.north - (row + 0.5) * grid.dy, math.sqrt(closest) * grid.dx, difference))
        yield None
    return tuple(found)


def access_steps(job: AccessJob, *, budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """**A10 y A11** (RF-017-24, RF-017-25, RF-017-04; plan 017 §5.4; RNF-017-05 y RNF-017-06): lo alcanzable desde los puntos de entrada de ``job`` por celdas transitables, con sus
    cotas mínima y máxima y su área, la comunicación de sus bermas, plataformas y zonas «requiere acceso» y, con una cantera de dos superficies, la cota mínima sobre la final, por pasos
    de ``budget_s`` como mucho (``STEP_BUDGET_S``, 0,05 s): el último ``Progress`` (fase ``road_access``) lleva el :class:`~.road_model.AccessOutcome`. Ninguna cifra ni aviso todavía:
    los compone la operación (T17).

    Rechazos al llamar: la capa sin ningún punto de entrada y la entrada sin dato (``DesignError``: RF-017-04) y, como errores del programa (``ValueError``), una rejilla de celdas
    que no son cuadradas. Ninguna entrada se modifica y no se escribe nada; cerrar el generador a mitad no deja nada."""
    work = access_units(job, budget_s=budget_s)
    return pace_progress(work, budget_s, phase=_PHASE, running="Calculando lo alcanzable…", finished="Accesibilidad calculada")


def access(job: AccessJob) -> AccessOutcome:
    """**A10**: :func:`access_steps` hasta el final, sin pasos: el :class:`~.road_model.AccessOutcome` de ``job``. Los mismos rechazos."""
    work = access_units(job)
    while True:
        try:
            next(work)
        except StopIteration as done:
            result: AccessOutcome = done.value
            return result

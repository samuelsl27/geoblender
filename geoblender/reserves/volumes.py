# SPDX-License-Identifier: GPL-3.0-or-later
"""Los pasos de una cubicación (spec 011; RF-011-01, RF-011-05, RF-011-07, RF-011-09,
RF-011-10, RF-011-12, RF-011-22, RF-011-25; RNF-011-04; plan 011 §5.3.1, A10, A14, D-16, D-25,
D-26, D-34).

:func:`volume_steps` cubica una :class:`VolumeRequest` **por pasos** sobre fuentes de ficheros
(``reserves.surfaces.SurfaceSource`` por papel: las rejillas del proyecto, las congeladas de una
instantánea o cotas constantes; plan T3): la misma función sirve a la orden, al recálculo y a
reproducir, que no recibe el proyecto. Cada paso es un ``core.project.model.Progress`` y no pasa
de ``budget_s`` (el trabajo de cada paso se planea para la mitad, :data:`WORK_FRACTION`); el último
lleva el :class:`VolumeResult`. Fases (A10):

1. ``check``: las superficies (A1: ``check_pair``, también las bases y los espesores de la
   columna, estos sin el datum vertical) y la columna de materiales (``validate``);
2. ``domains``: validar el ámbito (``polygons.scope_problem_steps``: un paso por polígono y
   por par; ``res.scope_invalid``, RF-011-01, T37) y los dominios (``polygons.problem_steps``: un
   paso por polígono y por par que recortar; ``res.domains_invalid``) y recortarlos por el
   ámbito, un polígono por paso;
3. ``bands``: por cada banda de filas, leer la banda de cada superficie (un paso por superficie,
   todas al paso: ninguna se remuestrea), sus pesos de ámbito y dominios (A5), el núcleo (A2, A3,
   A7; troceado por unidades: los totales y después una unidad por paso) y, si se pide la rejilla
   de diferencias, sus valores ``final − partida`` (sin dato donde falta una de las dos) y su
   hash de contenido **por bandas**, sin volver a leerla (``gis.geotiff@1``, ADR-0024);
4. ``grid``: la rejilla, por teselas en su temporal (``gis.geotiff.writer.write_steps``, perfil
   ``project``, sin ponerla en su sitio: lo hace quien confirma, ``reserves.store``);
5. el resultado: las tablas en formato largo (``reserves.table``, D-27), las cifras de los totales
   y de los subtotales de **un** reparto (D-26), los avisos y el factor combinado
   (``reserves.scale``, D-34).

**Un solo cálculo** (RF-011-10): todos los repartos salen de los mismos acumuladores de la misma
pasada. **Nada a medias** (RF-011-25): cerrar los pasos antes del final (Esc) o un fallo borran
el temporal de la rejilla y no devuelven nada; tras el último paso, el temporal es de quien
recibe el resultado. Sin ninguna celda común con dato (dentro del ámbito), ``res.no_common_cells``;
la misma superficie de partida y final, ceros y el aviso ``res.same_surface``.

:func:`tonnage_outputs` es el cálculo de ``res.tonnage`` (D-16): de la tabla de volúmenes
(``table.unit_volumes``, sin releer las superficies) a las toneladas, su tabla, sus cifras y sus
avisos; :func:`tonnage_work`, lo mismo por unidades de trabajo (T33: con la tabla de RNF-011-02,
de 28 712 filas, son 0,14 s de una vez). :func:`paced` agrupa unidades de trabajo en pasos de un
presupuesto (como los de :func:`volume_steps`).

**Cifras** (``FigureSpec`` CALCULADO, nunca NaN ni infinitas; ámbito ``{"cubication": nombre}``
más ``domain`` —el valor del dominio, o ``outside`` = :data:`OUTSIDE_SCOPE` para «Fuera de los
dominios»—, ``bench`` —la cota del pie de la rodaja—, ``unit`` y ``component``): los totales y,
cada uno por separado, los de cada dominio, cada rodaja y cada unidad; los cruces (dominio ×
rodaja × unidad) y lo que queda fuera de una lista de cotas, solo en la tabla.

Python puro con numpy (nivel 9). Las entradas solo se leen.
"""

from __future__ import annotations

import math
import numbers
import os
import time
from collections.abc import Generator, Iterator, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ..core.content.encoder import NORMALIZER, ContentDigest, ContentHasher
from ..core.datasets.model import DATASET_DECLARATIONS
from ..core.project.model import Progress
from ..core.provenance.figures import FigureSpec, ScopeValue
from ..core.provenance.graph import drain
from ..gis.content import GEOTIFF, raster_header
from ..gis.geotiff import writer
from ..gis.grid import Grid
from ..gis.raster import Raster
from . import scale
from .kernel import ALL, Accumulators, BandValues, KernelResult, NegativeThickness, band_step
from .materials import MaterialColumn, negative_thickness
from .messages import ResError, render
from .polygons import (
    DomainsError,
    Polygon,
    ScopeError,
    domain_edges,
    problem_steps,
    scope_edges,
    scope_problem_steps,
    weights,
)
from .slices import Slices
from .surfaces import BAND_ROWS, SurfaceRef, SurfaceSource, band_reader, check_pair
from .table import (
    ALL_DOMAINS,
    OUTSIDE_DOMAINS,
    QUANTITIES,
    Row,
    number_text,
    row,
    tonnage_parts,
    unit_volumes,
)
from .tonnage import TonnageResult, tonnage

__all__ = [
    "FINAL",
    "OUTSIDE_SCOPE",
    "PHASES",
    "START",
    "STEP_BUDGET_S",
    "WORK_FRACTION",
    "DifferenceGrid",
    "DomainLayer",
    "Notice",
    "TonnageOutputs",
    "VolumeRequest",
    "VolumeResult",
    "base_role",
    "paced",
    "step_budget",
    "thickness_role",
    "tonnage_outputs",
    "tonnage_work",
    "volume_steps",
]

START = "start"
"""El papel de la superficie de partida (y su clave en las fuentes)."""
FINAL = "final"
"""El papel de la superficie final."""
PHASES = ("check", "domains", "bands", "grid", "result")
"""Las fases de los pasos, en su orden (A10)."""
STEP_BUDGET_S = 0.05
"""El presupuesto de un paso por defecto (s; RNF-011-04: ≤ 0,2 s por llamada)."""
WORK_FRACTION = 0.5
"""La parte del presupuesto que se planea llenar de trabajo (el resto, para lo imprevisto)."""
OUTSIDE_SCOPE = "Fuera de los dominios"
"""El valor del ámbito ``outside`` de las cifras de «Fuera de los dominios» (en la tabla, el
dominio ``''``: un ámbito de cifra no puede quedar vacío)."""

_OBJ = "Superficies de la cubicación"
_FIELD = "superficie"
_TOTALS = ("cut_m3", "fill_m3", "net_m3", "area_m2", "nodata_area_m2", "still_area_m2")
_UNIT_AREAS = (("absent_area_m2", "unit_absent_m2"),
               ("absent_nodata_area_m2", "unit_nodata_m2"),
               ("crossed_area_m2", "unit_crossed_m2"))
_TEXTS = {
    "check": "comprobando las superficies…",
    "domains": "comprobando y recortando los dominios…",
    "bands": "leyendo y sumando las superficies…",
    "grid": "escribiendo la rejilla de diferencias…",
    "result": "preparando las tablas y las cifras…",
}
_NO_SCALE = "res.note_no_scale_factor"


def base_role(code: str) -> str:
    """El papel de la base de la unidad ``code`` (D-39)."""
    return f"base_{code}"


def thickness_role(code: str) -> str:
    """El papel de la rejilla de espesores de la unidad ``code`` (D-39)."""
    return f"thickness_{code}"


# --- Petición y resultado ------------------------------------------------------------------


def _non_negative(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real) or not math.isfinite(
            float(value)) or float(value) < 0.0:
        raise ValueError(f"{what} es un número finito ≥ 0, no {value!r}")
    return float(value)


@dataclass(frozen=True, slots=True, eq=False)
class DomainLayer:
    """La capa de dominios de un reparto (RF-011-07): su nombre (``layer``), el campo que nombra
    cada dominio (``field``) y sus polígonos (al menos uno)."""

    layer: str
    field: str
    polygons: tuple[Polygon, ...]

    def __post_init__(self) -> None:
        polygons = tuple(self.polygons)
        if not polygons or not all(isinstance(item, Polygon) for item in polygons):
            raise ValueError(f"la capa de dominios «{self.layer}» es una lista no vacía de "
                             "reserves.polygons.Polygon")
        object.__setattr__(self, "polygons", polygons)


@dataclass(frozen=True, slots=True, eq=False)
class VolumeRequest:
    """Una cubicación (plan §5.3.1): su nombre (único en la versión), las superficies de
    partida y final (``SurfaceRef``: lo que registra su operación; lo que se lee son las fuentes
    de :func:`volume_steps`), el ámbito (uno o varios polígonos que no se solapan; ``None``, toda
    la rejilla), los dominios, las rodajas, la columna de materiales (``None``: sin repartir por
    unidades), el espesor mínimo y el umbral de presencia de lo antrópico (m, los parámetros del
    proyecto), si se escribe la rejilla de diferencias (D-25) y el factor de escala de la
    proyección en :func:`reserves.scale.center` (``None``: no disponible, D-34) y el nombre de la
    capa del ámbito (``scope_layer``: solo para nombrarla si no sirve, ``res.scope_invalid``;
    no es un ajuste). Una petición mal formada es un error del programa (:class:`TypeError` o
    :class:`ValueError`)."""

    name: str
    start: SurfaceRef
    final: SurfaceRef
    scope: tuple[Polygon, ...] | None = None
    domains: DomainLayer | None = None
    slices: Slices | None = None
    column: MaterialColumn | None = None
    min_thickness_m: float = 0.0
    presence_m: float = 0.0
    difference_grid: bool = False
    point_scale: float | None = None
    scope_layer: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError(f"una cubicación tiene nombre, no {self.name!r}")
        for name in ("start", "final"):
            if not isinstance(getattr(self, name), SurfaceRef):
                raise TypeError(f"la superficie {name} es una SurfaceRef")
        if self.scope is not None:
            scope = tuple(self.scope)
            if not scope or not all(isinstance(item, Polygon) for item in scope):
                raise ValueError("el ámbito es una lista no vacía de reserves.polygons.Polygon")
            object.__setattr__(self, "scope", scope)
        for name, kind in (("domains", DomainLayer), ("slices", Slices),
                           ("column", MaterialColumn)):
            value = getattr(self, name)
            if value is not None and not isinstance(value, kind):
                raise TypeError(f"{name} es un {kind.__name__} o None, no {value!r}")
        object.__setattr__(self, "min_thickness_m",
                           _non_negative(self.min_thickness_m, "el espesor mínimo"))
        object.__setattr__(self, "presence_m",
                           _non_negative(self.presence_m, "el umbral de presencia"))
        if not isinstance(self.difference_grid, bool):
            raise TypeError("difference_grid es verdadero o falso")
        if not isinstance(self.scope_layer, str):
            raise TypeError(f"scope_layer es el nombre de una capa, no {self.scope_layer!r}")
        if self.point_scale is not None:
            scale.combined_factor(self.point_scale, 0.0)
            object.__setattr__(self, "point_scale", float(self.point_scale))

    def roles(self) -> tuple[str, ...]:
        """Los papeles de las superficies que se leen: partida, final y, con la columna, la base
        y el espesor de cada unidad que los tiene."""
        found = [START, FINAL]
        for unit in () if self.column is None else self.column.units:
            if unit.base is not None:
                found.append(base_role(unit.code))
            if unit.thickness is not None:
                found.append(thickness_role(unit.code))
        return tuple(found)


@dataclass(frozen=True, slots=True)
class Notice:
    """Un aviso para el usuario: su código de ``reserves.messages`` y sus valores."""

    code: str
    values: Mapping[str, object] = field(default_factory=dict)

    def text(self, language: str = "es") -> str:
        """El aviso en ``language``."""
        return render(self.code, language=language, **self.values)


@dataclass(frozen=True, slots=True, eq=False)
class DifferenceGrid:
    """La rejilla de diferencias escrita entera en su temporal (``path``; la pone en su sitio
    quien confirma) y su hash de contenido, el que da su lector ``gis.geotiff@1``."""

    path: Path
    digest: ContentDigest


@dataclass(frozen=True, slots=True, eq=False)
class VolumeResult:
    """El resultado de :func:`volume_steps`: el del núcleo (m³ y m²; su fila ``1 + i`` es el
    dominio ``domains[i]``), las filas de la tabla ``res_vol_``, las cifras, los avisos, la cota
    media de lo cubicado (m), el factor combinado (``None``: no disponible) y la rejilla de
    diferencias (``None`` si no se pidió)."""

    name: str
    kernel: KernelResult
    domains: tuple[str, ...]
    rows: tuple[Row, ...]
    figures: tuple[FigureSpec, ...]
    warnings: tuple[Notice, ...]
    mean_elevation_m: float
    factor: scale.CombinedFactor | None
    difference: DifferenceGrid | None

    @property
    def cut_m3(self) -> float:
        """El desmonte total (m³)."""
        return float(self.kernel.cut_m3[ALL])

    @property
    def fill_m3(self) -> float:
        """El terraplén total (m³)."""
        return float(self.kernel.fill_m3[ALL])

    @property
    def net_m3(self) -> float:
        """El neto, desmonte − terraplén (m³)."""
        return float(self.kernel.net_m3[ALL])


@dataclass(frozen=True, slots=True, eq=False)
class TonnageOutputs:
    """El cálculo de ``res.tonnage`` (:func:`tonnage_outputs`): el de ``reserves.tonnage``,
    las filas de la tabla ``res_ton_``, las cifras y los avisos (lo que falta)."""

    result: TonnageResult
    rows: tuple[Row, ...]
    figures: tuple[FigureSpec, ...]
    warnings: tuple[Notice, ...]


# --- Los pasos -----------------------------------------------------------------------------


class _Pacer:
    """Mide un paso: termina cuando lo hecho más lo más lento del paso pasaría de su parte del
    presupuesto (siempre al menos una unidad de trabajo)."""

    def __init__(self, budget_s: float) -> None:
        self.target = budget_s * WORK_FRACTION
        self.restart()

    def restart(self) -> None:
        self.start = self.last = time.perf_counter()
        self.slowest = 0.0

    def lap(self) -> bool:
        now = time.perf_counter()
        self.slowest = max(self.slowest, now - self.last)
        self.last = now
        return now - self.start + self.slowest > self.target


def step_budget(value: object) -> float:
    """El presupuesto de un paso ``value`` (s) como ``float``: ``TypeError`` si no es un
    número, ``ValueError`` si no es positivo."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"el presupuesto de un paso es un número de segundos, no {value!r}")
    if not value > 0:
        raise ValueError(f"el presupuesto de un paso es positivo, no {value!r}")
    return float(value)


def paced[T, R](work: Generator[T, None, R],
                budget_s: float = STEP_BUDGET_S) -> Generator[T, None, R]:
    """Agrupa las unidades de trabajo de ``work`` (cada ``next`` hace una y da lo que quiera;
    lo que devuelve es su resultado) en pasos de ``budget_s`` como mucho (se planea la mitad,
    :data:`WORK_FRACTION`; un paso hace siempre al menos una): da lo último que dio ``work`` en
    cada paso y devuelve lo que devuelve ``work``. Cerrarlo cierra ``work``. El presupuesto se
    comprueba al llamar (:func:`step_budget`)."""
    return _grouped(work, step_budget(budget_s))


def _grouped[T, R](work: Generator[T, None, R], budget_s: float) -> Generator[T, None, R]:
    pacer = _Pacer(budget_s)
    with closing(work):  # cerrar los pasos (Esc) cierra el trabajo
        while True:
            pacer.restart()
            try:
                item = next(work)
                while not pacer.lap():
                    item = next(work)
            except StopIteration as stop:
                return stop.value
            yield item


def volume_steps(request: VolumeRequest, sources: Mapping[str, SurfaceSource], *,
                 budget_s: float = STEP_BUDGET_S, difference_path: Path | str | None = None,
                 difference_temporary: Path | str | None = None,
                 band_rows: int = BAND_ROWS) -> Iterator[Progress]:
    """Los pasos de la cubicación ``request`` sobre ``sources`` (papel → ``SurfaceSource``:
    :data:`START`, :data:`FINAL` y, con la columna, :func:`base_role` y :func:`thickness_role` de
    cada unidad que los tiene), de ``budget_s`` como mucho, por bandas de ``band_rows`` filas
    (véase el módulo). Con la rejilla de diferencias, ``difference_path`` es su destino (no se
    toca) y ``difference_temporary``, el temporal donde queda escrita (por defecto, el de
    ``gis.geotiff.writer``). El último ``Progress`` lleva el :class:`VolumeResult`.

    Al llamar, sin calcular nada, una petición, unas fuentes (una que falta) o unos ajustes mal
    formados son :class:`TypeError` o :class:`ValueError`; al avanzar, los rechazos para el
    usuario (``ResError``: ``res.surfaces_mismatch``, ``res.surfaces_no_grid``,
    ``res.materials_invalid``, ``res.domains_invalid``, ``res.thickness_negative``,
    ``res.no_common_cells``) y los del disco al escribir la rejilla (``GisError``)."""
    if not isinstance(request, VolumeRequest):
        raise TypeError(f"se cubica una VolumeRequest, no {type(request).__name__}")
    found: dict[str, SurfaceSource] = {}
    for role in request.roles():
        source = sources.get(role)
        if source is None:
            raise ValueError(f"falta la superficie «{role}» de la cubicación «{request.name}»")
        if not isinstance(source, SurfaceSource):
            raise TypeError(f"la superficie «{role}» es una SurfaceSource, no {source!r}")
        found[role] = source
    if isinstance(band_rows, bool) or not isinstance(band_rows, int) or band_rows < 1:
        raise ValueError(f"una banda tiene al menos una fila, no {band_rows!r}")
    if request.difference_grid and difference_path is None:
        raise ValueError("la rejilla de diferencias necesita su destino (difference_path)")
    run = _Run(request, found, band_rows,
               None if difference_path is None else Path(difference_path),
               None if difference_temporary is None else Path(difference_temporary),
               writer.TILE_SIZE)
    return _paced(run, step_budget(budget_s))


def _paced(run: _Run, budget_s: float) -> Iterator[Progress]:
    """Agrupa las unidades de trabajo de ``run`` en pasos de ``budget_s`` como mucho."""
    steps = paced(run.work(), budget_s)
    with closing(steps):  # cerrar los pasos (Esc) cierra el trabajo: lectores y temporal
        while True:
            try:
                phase = next(steps)
            except StopIteration as stop:
                result: VolumeResult = stop.value
                break
            yield run.progress(phase)
    yield Progress("result", run.total, run.total, _summary(result), result=result)


def _summary(result: VolumeResult) -> str:
    return (f"«{result.name}»: desmonte {number_text(result.cut_m3, 'm3')} m³, terraplén "
            f"{number_text(result.fill_m3, 'm3')} m³, neto "
            f"{number_text(result.net_m3, 'm3')} m³")


def _discard(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


@dataclass(eq=False)
class _Run:
    """Una cubicación en curso: lo pedido, sus fuentes y lo hecho de su total de unidades."""

    request: VolumeRequest
    sources: Mapping[str, SurfaceSource]
    band_rows: int
    difference_path: Path | None
    difference_temporary: Path | None
    tile: int
    done: int = 0
    total: int = 1

    def progress(self, phase: str) -> Progress:
        return Progress(phase, min(self.done, self.total), self.total,
                        f"Cubicando «{self.request.name}»: {_TEXTS[phase]}")

    def _plan(self, grid: Grid, chunks: int) -> None:
        """El total de unidades de trabajo (para el avance)."""
        request = self.request
        bands = -(-grid.nrows // self.band_rows)
        weighted = request.domains is not None or request.scope is not None
        per_band = len(self.sources) + int(weighted) + chunks + 1
        domains = 0 if request.domains is None else len(request.domains.polygons)
        domains += int(request.scope is not None)
        tiles = 0
        if request.difference_grid:
            tiles = -(-grid.nrows // self.tile) * -(-grid.ncols // self.tile) + 1
        self.total = 1 + domains + bands * per_band + tiles + 1

    def _check(self) -> tuple[SurfaceSource, list[Notice]]:
        """A1: las superficies y la columna; la de referencia (con rejilla) y los avisos."""
        request = self.request
        start, final = self.sources[START], self.sources[FINAL]
        check_pair(start, final)
        reference = start if start.grid is not None else final
        if request.column is not None:
            request.column.validate()
            for unit in request.column.units:
                if unit.base is not None:
                    check_pair(reference, self.sources[base_role(unit.code)])
                if unit.thickness is not None:
                    check_pair(reference, self.sources[thickness_role(unit.code)],
                               vertical=False)
        warnings = []
        if _same(request, start, final):
            warnings.append(Notice("res.same_surface", {"surface": start.name}))
        return reference, warnings

    def work(self) -> Generator[str, None, VolumeResult]:
        """Las unidades de trabajo, cada una seguida de su fase (A10); devuelve el resultado."""
        request = self.request
        reference, warnings = self._check()
        grid = reference.grid
        assert grid is not None
        units = () if request.column is None else request.column.units
        chunks: list[slice | None] = [None] if not units else [
            slice(0, 0), *(slice(position, position + 1) for position in range(len(units)))]
        self._plan(grid, len(chunks))
        self.done += 1
        yield "check"

        yield from self._scope_check()
        names, edges = yield from self._domains(grid)
        scope = None
        if request.scope is not None:
            scope = scope_edges(request.scope, grid)
            self.done += 1
            yield "domains"

        accumulators = Accumulators(grid, slices=request.slices, domains=len(edges),
                                    min_thickness_m=request.min_thickness_m, units=len(units),
                                    presence_m=request.presence_m)
        difference = hasher = None
        if request.difference_grid:
            difference = Raster(grid, np.full(grid.shape, np.nan), reference.header.crs,
                                reference.header.vertical)
            hasher = ContentHasher("raster", declarations=DATASET_DECLARATIONS,
                                   reader=GEOTIFF.id, normalizer=NORMALIZER)
        elevation = yield from self._bands(grid, accumulators, edges, scope, chunks, difference,
                                           hasher)
        result = accumulators.result()
        if not result.area_m2[ALL] > 0.0:
            start, final = self.sources[START], self.sources[FINAL]
            raise ResError("res.no_common_cells", obj=_OBJ, field=_FIELD, value=final.name,
                           start=start.name, final=final.name)
        mean_elevation = elevation[0] / elevation[1]

        written: Path | None = None
        if difference is not None:
            assert self.difference_path is not None and hasher is not None
            steps = writer.write_steps(difference, self.difference_path, profile="project",
                                       temporary=self.difference_temporary, replace=False)
            with closing(steps):  # cerrar o fallar a mitad borra el temporal
                while True:
                    try:
                        next(steps)
                    except StopIteration as stop:
                        written = Path(stop.value)
                        break
                    self.done += 1
                    yield "grid"
        try:
            if written is not None:
                self.done += 1
                yield "grid"  # el IFD, fsync y la rejilla entera en su temporal
            grid_out = None if written is None or hasher is None else DifferenceGrid(
                written, hasher.digest())
            return _volume_result(request, result, names, warnings, mean_elevation, grid_out)
        except BaseException:
            if written is not None:
                _discard(written)  # nada a medias (RF-011-25)
            raise

    def _scope_check(self) -> Generator[str, None, None]:
        """Valida el ámbito antes de recortar nada con él (RF-011-01; T37): un paso por polígono
        y por par, como los dominios; con algún problema, ``res.scope_invalid`` con la lista."""
        scope = self.request.scope
        if scope is None:
            return
        steps = scope_problem_steps(scope)
        while True:
            try:
                next(steps)
            except StopIteration as stop:
                found = stop.value
                break
            yield "domains"
        if found:
            raise ScopeError(found, layer=self.request.scope_layer or "—")

    def _domains(self, grid: Grid) -> Generator[str, None, tuple[tuple[str, ...],
                                                                  list[np.ndarray]]]:
        """Valida los dominios (un paso por polígono y por par) y los recorta por el ámbito (un
        paso por polígono): sus valores y sus aristas, en el orden en que aparece cada uno."""
        layer = self.request.domains
        if layer is None:
            return (), []
        steps = problem_steps(layer.polygons)
        while True:
            try:
                next(steps)
            except StopIteration as stop:
                found = stop.value
                break
            yield "domains"
        if found:
            raise DomainsError(found, field=layer.field, layer=layer.layer)
        grouped: dict[str, list[np.ndarray]] = {}
        for polygon in layer.polygons:
            (item,) = domain_edges((polygon,), grid, scope=self.request.scope)
            grouped.setdefault(item.value, []).append(item.edges)
            self.done += 1
            yield "domains"
        return tuple(grouped), [np.ascontiguousarray(np.concatenate(parts))
                                for parts in grouped.values()]

    def _bands(self, grid: Grid, accumulators: Accumulators, edges: list[np.ndarray],
               scope: np.ndarray | None, chunks: list[slice | None],
               difference: Raster | None, hasher: ContentHasher | None
               ) -> Generator[str, None, tuple[float, float]]:
        """La pasada por bandas (A2, A3, A7): las superficies al paso, los pesos, el núcleo por
        trozos y la rejilla de diferencias con su hash. Devuelve las sumas de la cota media (Σ
        w·cota, Σ w) de las celdas con dato en las dos superficies."""
        request = self.request
        roles = list(self.sources)
        readers = [band_reader(self.sources[role], grid, rows=self.band_rows) for role in roles]
        feed = None if difference is None or hasher is None else hasher.begin_grid(
            raster_header(difference))
        elevation = [0.0, 0.0]
        weighted = bool(edges) or scope is not None
        try:
            for top in range(0, grid.nrows, self.band_rows):
                rows = slice(top, min(top + self.band_rows, grid.nrows))
                bands: dict[str, np.ndarray | float] = {}
                for role, reader in zip(roles, readers, strict=True):
                    first, bands[role] = next(reader)
                    assert first == top
                    self.done += 1
                    yield "bands"
                band_weights = None
                if weighted:
                    band_weights = weights(edges, scope, grid, rows)
                    self.done += 1
                    yield "bands"
                values = self._band_values(top, bands)
                for chunk in chunks:
                    try:
                        band_step(accumulators, values, band_weights, units=chunk)
                    except NegativeThickness as exc:
                        assert request.column is not None
                        raise negative_thickness(request.column.units[exc.unit],
                                                 exc.value) from exc
                    self.done += 1
                    yield "bands"
                shape = (rows.stop - rows.start, grid.ncols)
                start = np.broadcast_to(np.asarray(bands[START], dtype=np.float64), shape)
                final = np.broadcast_to(np.asarray(bands[FINAL], dtype=np.float64), shape)
                valid = np.isfinite(start) & np.isfinite(final)
                fraction = None if band_weights is None else band_weights.scope
                middle = (start[valid] + final[valid]) / 2.0
                if fraction is None:
                    elevation[0] += float(np.sum(middle))
                    elevation[1] += float(np.count_nonzero(valid))
                else:
                    elevation[0] += float(np.sum(fraction[valid] * middle))
                    elevation[1] += float(np.sum(fraction[valid]))
                if difference is not None and feed is not None:
                    with np.errstate(invalid="ignore"):
                        band = np.where(valid, final - start, np.nan)
                    difference.values[rows] = band
                    feed.update(band)
                self.done += 1
                yield "bands"
            if feed is not None:
                feed.finish()
        finally:
            for reader in readers:
                reader.close()
        return elevation[0], elevation[1]

    def _band_values(self, top: int, bands: Mapping[str, np.ndarray | float]) -> BandValues:
        """Las cotas de la banda para el núcleo: las dos superficies y, con la columna, la base
        y el espesor de cada unidad (la base de la última y el espesor de las demás, ``None``)."""
        column = self.request.column
        if column is None:
            return BandValues(top, bands[START], bands[FINAL])
        bases = tuple(None if unit.base is None else bands[base_role(unit.code)]
                      for unit in column.units)
        thicknesses = tuple(None if unit.thickness is None else bands[thickness_role(unit.code)]
                            for unit in column.units)
        return BandValues(top, bands[START], bands[FINAL], bases=bases, thicknesses=thicknesses)


def _same(request: VolumeRequest, start: SurfaceSource, final: SurfaceSource) -> bool:
    """La misma superficie de partida y final (la misma referencia o el mismo fichero)."""
    if request.start == request.final:
        return True
    if start.path is None or final.path is None:
        return False
    try:
        return os.path.samefile(start.path, final.path)
    except OSError:
        return False


# --- El resultado: tablas y cifras (D-26, D-27) ---------------------------------------------


def _figure(key: str, value: object, unit: str, scope: Mapping[str, ScopeValue]) -> FigureSpec:
    """Una cifra CALCULADO; un valor que no es finito es un error del programa (RF-011-22)."""
    number = float(value)  # type: ignore[arg-type]
    if not math.isfinite(number):
        raise ValueError(f"la cifra «{key}» ({dict(scope)}) no es un número finito: {number!r}")
    return FigureSpec(key, number, unit, scope=dict(scope))


def _quantity_figure(quantity: str, value: object, scope: Mapping[str, ScopeValue]
                     ) -> FigureSpec:
    found = QUANTITIES[quantity]
    assert found.figure is not None
    return _figure(found.figure, value, found.unit, scope)


def _domain_scopes(name: str, names: Sequence[str]) -> list[tuple[str, dict[str, ScopeValue]]]:
    """Las filas del núcleo como (dominio de la tabla, ámbito de sus cifras), en su orden."""
    base: dict[str, ScopeValue] = {"cubication": name}
    found = [(ALL_DOMAINS, base)]
    if names:
        found += [(value, {**base, "domain": value}) for value in names]
        found.append((OUTSIDE_DOMAINS, {**base, "outside": OUTSIDE_SCOPE}))
    return found


def _volume_result(request: VolumeRequest, kernel: KernelResult, names: tuple[str, ...],
                   warnings: list[Notice], mean_elevation: float,
                   difference: DifferenceGrid | None) -> VolumeResult:
    """Las tablas, las cifras y el factor combinado de la cubicación (A10, fase 5)."""
    factor = None
    if request.point_scale is not None:
        factor = scale.combined_factor(request.point_scale, mean_elevation)
    rows: list[Row] = []
    figures: list[FigureSpec] = []
    levels = kernel.bounds
    benches = [] if levels is None else [(float(levels[i]), float(levels[i + 1]))
                                         for i in range(levels.size - 1)]
    listed = request.slices is not None and request.slices.levels is not None
    edges = [] if not listed or levels is None else [
        ((None, float(levels[0])), "below"), ((float(levels[-1]), None), "above")]
    units = () if request.column is None else request.column.units
    for position, (domain, scope) in enumerate(_domain_scopes(request.name, names)):
        for quantity in _TOTALS:
            value = float(getattr(kernel, quantity)[position])
            rows.append(row(quantity, value, domain=domain))
            figures.append(_quantity_figure(quantity, value, scope))
        for side in ("cut", "fill"):
            if kernel.bounds is None:
                break
            parts = getattr(kernel, f"slice_{side}_m3")[position]
            for index, bench in enumerate(benches):
                rows.append(row(f"{side}_m3", float(parts[index]), domain=domain, bench=bench))
                if position == ALL:
                    figures.append(_quantity_figure(f"{side}_m3", parts[index],
                                                    {**scope, "bench": bench[0]}))
            for bench, where in edges:
                rows.append(row(f"{side}_m3", float(getattr(kernel, f"{where}_{side}_m3")[
                    position]), domain=domain, bench=bench))
        for number, unit in enumerate(units):
            volume = float(kernel.unit_volume_m3[position, number])
            rows.append(row("volume_m3", volume, domain=domain, unit=unit.code))
            if position == ALL:
                figures.append(_quantity_figure("volume_m3", volume,
                                                {**scope, "unit": unit.code}))
            for quantity, name in _UNIT_AREAS:
                rows.append(row(quantity, float(getattr(kernel, name)[position, number]),
                                domain=domain, unit=unit.code))
            if kernel.unit_slice_m3 is not None:
                parts = kernel.unit_slice_m3[position, number]
                for index, bench in enumerate(benches):
                    rows.append(row("volume_m3", float(parts[index]), domain=domain,
                                    bench=bench, unit=unit.code))
                for bench, where in edges:
                    rows.append(row("volume_m3", float(getattr(kernel, f"unit_{where}_m3")[
                        position, number]), domain=domain, bench=bench, unit=unit.code))
    rows.append(row("mean_elevation_m", mean_elevation))
    no_factor = () if factor is not None else (_NO_SCALE,)
    rows.append(row("grid_scale_factor", None if factor is None else factor.combined,
                    notes=no_factor))
    rows.append(row("ground_effect_pct", None if factor is None else factor.effect_pct,
                    notes=no_factor))
    if factor is not None:
        base = {"cubication": request.name}
        figures.append(_quantity_figure("grid_scale_factor", factor.combined, base))
        figures.append(_quantity_figure("ground_effect_pct", factor.effect_pct, base))
    return VolumeResult(request.name, kernel, names, tuple(rows), tuple(figures),
                        tuple(warnings), mean_elevation, factor, difference)


# --- res.tonnage (D-16) -----------------------------------------------------------------------


def _group_scope(name: str, domain: str, bench: Any) -> dict[str, ScopeValue] | None:
    """El ámbito de las cifras de los totales de ``domain`` y ``bench`` (un reparto cada vez);
    ``None`` en un cruce o fuera de una lista de cotas (solo en la tabla)."""
    base: dict[str, ScopeValue] = {"cubication": name}
    if bench is None:
        if domain == ALL_DOMAINS:
            return base
        if domain == OUTSIDE_DOMAINS:
            return {**base, "outside": OUTSIDE_SCOPE}
        return {**base, "domain": domain}
    if domain != ALL_DOMAINS or bench[0] is None or bench[1] is None:
        return None
    return {**base, "bench": float(bench[0])}


def _tonnage_figures(result: TonnageResult, name: str) -> tuple[FigureSpec, ...]:
    """Las cifras de las toneladas de la cubicación ``name``: cada unidad y componente en
    total; los totales, lo útil y lo estéril y las relaciones en total, por dominio y por
    rodaja; la intrínseca de cada compuesta."""
    figures: list[FigureSpec] = []
    base: dict[str, ScopeValue] = {"cubication": name}
    for item in result.rows:
        if item.domain != ALL_DOMAINS or item.bench is not None:
            continue
        scope = {**base, "unit": item.unit}
        if item.component is not None:
            scope["component"] = item.component
            figures.append(_quantity_figure("volume_m3", item.volume_m3, scope))
        for quantity, value in (("swell_m3", item.swell_m3), ("mass_t", item.mass_t)):
            if value is not None:
                figures.append(_quantity_figure(quantity, value, scope))
    for group in result.groups:
        scope = _group_scope(name, group.domain, group.bench)
        if scope is None:
            continue
        for quantity, value in (
                ("total_t", group.total_t), ("useful_m3", group.useful_m3),
                ("waste_m3", group.waste_m3), ("useful_t", group.useful_t),
                ("waste_t", group.waste_t), ("waste_ratio_m3", group.ratio_m3.value),
                ("waste_ratio_t", group.ratio_t.value)):
            if value is not None:
                figures.append(_quantity_figure(quantity, value, scope))
    for intrinsic in result.intrinsic:
        scope = {**base, "unit": intrinsic.unit}
        for quantity, ratio in (("intrinsic_ratio_m3", intrinsic.ratio_m3),
                                ("intrinsic_ratio_t", intrinsic.ratio_t)):
            if ratio.value is not None:
                figures.append(_quantity_figure(quantity, ratio.value, scope))
    return tuple(figures)


def tonnage_work(rows: Sequence[Row], column: MaterialColumn, params: Mapping[str, Any], *,
                 name: str) -> Generator[float, None, TonnageOutputs]:
    """:func:`tonnage_outputs` por unidades de trabajo (RNF-011-04; T33), para llevarlas por
    pasos con :func:`paced`: pesar (``reserves.tonnage.tonnage``), cada parte de la tabla
    ``res_ton_`` (``table.tonnage_parts``) y, al terminar, las cifras y los avisos. Cada unidad
    da la parte hecha (0–1); devuelve lo mismo que :func:`tonnage_outputs`, bit a bit. Los
    rechazos de pesar (la columna, los parámetros), en la primera."""
    result = tonnage(unit_volumes(rows), column, params)
    units = len(result.rows) + len(result.groups) + len(result.intrinsic) + 2
    yield 1 / units
    found: list[Row] = []
    for done, part in enumerate(tonnage_parts(result), start=2):
        found.extend(part)
        yield done / units
    warnings = tuple(Notice("res.density_missing", {"unit": item.shown, "value": item.key})
                     for item in result.missing)
    return TonnageOutputs(result, tuple(found), _tonnage_figures(result, name), warnings)


def tonnage_outputs(rows: Sequence[Row], column: MaterialColumn,
                    params: Mapping[str, Any], *, name: str) -> TonnageOutputs:
    """El cálculo de ``res.tonnage`` de la cubicación ``name`` (D-16; A8, A9): los m³ de cada
    unidad de su tabla de volúmenes ``rows`` (sin releer las superficies), con la columna
    ``column`` y sus parámetros ``params`` (clave → número, ``ResolvedParam`` o ``None``; véase
    ``reserves.tonnage.tonnage``): la tabla ``res_ton_``, las cifras (cada unidad y componente
    en total; los totales, lo útil y lo estéril y las relaciones en total, por dominio y por
    rodaja; la intrínseca de cada compuesta) y el aviso de cada parámetro que falta. De una
    vez; por pasos, :func:`tonnage_work`."""
    return drain(tonnage_work(rows, column, params, name=name))

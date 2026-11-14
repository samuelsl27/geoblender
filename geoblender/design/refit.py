# SPDX-License-Identifier: GPL-3.0-or-later
"""El diseño frente a un límite nuevo (spec 014; HU-014-7; RF-014-26 a RF-014-28; plan 014 A13,
§5.3.1; el error 46 del análisis).

**La comprobación** (T31; RF-014-26): cuando se recompilan las máscaras de una versión, cada
superficie de esta spec que tiene (las dos de una cantera, una transición, un diseño «solo
relleno», un ajuste) se compara con el límite vigente: :func:`outside_volume` da el volumen y el
área de lo que mueve fuera de él (:class:`RefitCheck`) y su aviso ``des.refit_outside``, que lleva a
«Ajustar el diseño a un límite nuevo…». Quien lee las superficies del proyecto es
``design.store.limit_checks``.

- **Lo que mueve** una superficie ``S`` frente a su partida ``z``: las celdas con dato en las dos y
  ``|S − z|`` mayor que el espesor mínimo de la 012 (``design.report.moved_cells``, la máscara del
  informe de la 013).
- **Fuera del límite** (:func:`limit_cells`): un corte (``S < z``) fuera del perímetro de actuación
  ∩ el límite legal sin su resguardo hacia dentro, o un relleno (``S > z``) fuera del perímetro de
  actuación (la franja de solo relleno, perímetro ∖ límite legal, es del límite). Las zonas de las
  demás restricciones (intocables, sin corte…) no son del límite: las verifica la 012 por recinto.
- **Volumen** ``Σ |S − z| · área de celda`` de esas celdas (el desmonte y el terraplén con todo su
  espesor, como ``design.report``) y **área**, sus celdas por el área de celda.

**El ajuste** (T32; RF-014-27, RF-014-28; A13, P-3): :func:`refit_steps` ajusta una superficie
de diseño ``S`` a las máscaras nuevas, frente a su partida ``z``:

- **Si el límite nuevo no deja nada de ella fuera** (la comprobación, :func:`outside_volume`), no
  hacía falta: ``S`` tal cual, 0 m³ y el aviso ``des.refit_not_needed`` (spec §8).
- **Fuera** de ``D`` (el límite para cortar de :func:`limit_cells`), el terreno intacto: ``S' = z``;
  un relleno dentro del perímetro de actuación (la franja de solo relleno, el resguardo) es del
  límite y sigue.
- **Dentro**, las semillas son ``z`` en el anillo exterior de una celda de ``D`` (Chebyshev, con
  dato de terreno), su envolvente descendente de la 013 va con la **cara del perfil** de la
  superficie por su factor de malla (``tan α · malla``, la de cada celda según su sector:
  :func:`face_slope`), y ``S' = máx(S, mín(z, ENV↓))``: la superficie sube hasta ella sin superar
  el terreno (un relleno no cambia). Es la ``mín(z, máx(S, ENV↓))`` de A13 donde ``S ≤ z``.
- El **volumen de ajuste** es ``Σ |S' − S| · área de celda`` (:class:`Refit`); las celdas sin dato
  en ``S`` o en ``z`` no se tocan.

El ángulo no se pide (P-3): es la cara del perfil de la operación que creó la superficie
(:class:`ProfileFace`, :func:`profile_faces`); una petición por guion que trae otro se rechaza con
``des.refit_angle`` nombrando la superficie y los dos ángulos (:func:`check_angle`; RF-014-28, el
error 46: con 35° en el muro de explotación salían 39.000 m³ falsos). Lo de las superficies de un
ajuste (:class:`RefitOutcome`, :func:`refit_outcome`) lleva su cifra ``des.refit_m3`` por
superficie (:func:`refit_figures`), los avisos de las que no hacía falta, los del orden de las dos
superficies de una cantera, los de los diseños obsoletos de los que sale y el mensaje.

**El orden de las dos superficies de una cantera** (T53; RF-014-14 frente a RF-014-27, hallazgo
F-15): con la final más tendida que la explotación, junto al límite nuevo la final ajustada sube más
que la explotación ajustada. Si un ajuste lleva las dos superficies de una misma cantera,
``design.store.refit_compute_steps`` les aplica después la regla de orden de esa cantera
(``design.quarry.order_surfaces``, con su ajuste «order») y ``check_order`` antes de ofrecer
«Crear»: la rejilla de cada :class:`Refit` es entonces la atada, y su volumen y sus celdas siguen
siendo los de su cara (CE-014-08); la nota :data:`ORDER_CODE` dice las celdas que cambió la regla
más de 1 mm (T60), y no sale si no cambió ninguna (T61).
Con una sola de las dos, no se ata, y el aviso :data:`ORDER_SIDE_CODE` dice si queda del lado
equivocado de la otra.

**El ajuste frente a lo obsoleto del diseño del que sale** (T54; RF-014-27, RF-014-31, hallazgo
F-16; la propuesta por defecto (b) que aceptó Samuel): un límite nuevo deja obsoleto el diseño del
que sale cada superficie (la cantera, el escalonado de la 013 o «solo relleno»: leen las máscaras),
así que el ajuste nace obsoleto con sus causas, y «Recalcular lo obsoleto» vuelve a calcular ese
diseño con el límite vigente y después rehace el ajuste sobre él, que sustituye al que se creó. El
ajuste no resuelve lo obsoleto de su diseño de origen (eso sería de la 008); lo dice: el aviso
:data:`SOURCE_STALE_CODE`, uno por diseño obsoleto con las superficies del ajuste que salen de él
(lo lee ``design.store.prepare_refit_units``, de la caché de lo obsoleto de la 008).

Python puro con numpy; no lee el proyecto ni modifica ninguna entrada.
"""

from __future__ import annotations

import math
from collections.abc import Generator, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..core.project.model import Progress
from ..core.provenance.figures import FigureSpec
from ..gis.masks.access import MaskSet
from ..gis.masks.combine import ClassBit
from ..gis.masks.compile import STEP_BUDGET_S
from ..gis.messages import format_value
from . import provenance
from .edges import seed_envelope_steps
from .envelopes import CELLS_PER_UNIT, SlopeField, SlopeRule, sector_slope
from .grids import dilate_square
from .messages import DesignError
from .model import Direction, Metric
from .params import BenchParam, bench_key, check_bench_value
from .preview import Notice
from .report import _thickness, moved_cells
from .seeds import pace_progress

__all__ = [
    "ANGLE_CODE",
    "ANGLE_TOLERANCE_DEG",
    "NOT_NEEDED_CODE",
    "ORDER_CODE",
    "ORDER_SIDE_CODE",
    "OUTSIDE_CODE",
    "REFIT_NAME",
    "REFIT_PHASE",
    "SOURCE_STALE_CODE",
    "ProfileFace",
    "Refit",
    "RefitCheck",
    "RefitOutcome",
    "check_angle",
    "face_slope",
    "limit_cells",
    "outside_volume",
    "profile_faces",
    "refit_figures",
    "refit_outcome",
    "refit_steps",
]

OUTSIDE_CODE = "des.refit_outside"
"""El aviso de una superficie que queda fuera del límite vigente (RF-014-26)."""


@dataclass(frozen=True, slots=True)
class RefitCheck:
    """Una superficie de diseño frente al límite vigente de su versión (RF-014-26): el nombre de su
    dato (``surface``), el código de la versión (``version``), las celdas que mueve fuera del límite
    (``cells``), su área (``area_m2``, m²), su volumen (``volume_m3``, m³) y el espesor mínimo con
    que se midió lo que mueve (``min_thickness_m``, m)."""

    surface: str
    version: str
    cells: int
    area_m2: float
    volume_m3: float
    min_thickness_m: float

    @property
    def outside(self) -> bool:
        """Si mueve alguna celda fuera del límite."""
        return self.cells > 0

    @property
    def notice(self) -> Notice | None:
        """El aviso ``des.refit_outside`` con la superficie, el volumen, el área y la versión;
        ``None`` si no deja nada fuera."""
        if not self.outside:
            return None
        return Notice(OUTSIDE_CODE, {"surface": self.surface, "volume": self.volume_m3,
                                     "area": self.area_m2, "version": self.version})


def _bit(masks: MaskSet, bit: ClassBit) -> np.ndarray:
    return (masks.classes & np.uint16(int(bit))) != 0


def limit_cells(masks: MaskSet) -> tuple[np.ndarray, np.ndarray]:
    """Las celdas de la rejilla de ``masks`` **dentro del límite** (máscaras nuevas): para cortar,
    el perímetro de actuación ∩ el límite legal sin su resguardo hacia dentro; para rellenar, el
    perímetro de actuación (con la franja de solo relleno y el resguardo). Las demás restricciones
    no cuentan (véase el módulo)."""
    perimeter = _bit(masks, ClassBit.PERIMETER)
    cut = perimeter & _bit(masks, ClassBit.LEGAL) & ~_bit(masks, ClassBit.INNER_BAND)
    return cut, perimeter


def _grid(values: np.ndarray, name: str, masks: MaskSet) -> np.ndarray:
    found = np.asarray(values, dtype=np.float64)
    if found.shape != masks.grid.shape:
        raise ValueError(f"{name} es una rejilla de la forma {masks.grid.shape} (la de las "
                         f"máscaras), no de forma {found.shape}")
    return found


def outside_volume(surface: np.ndarray, start: np.ndarray, masks: MaskSet,
                   min_thickness_m: float, *, name: str, version: str = "") -> RefitCheck:
    """**A13**, la comprobación (RF-014-26): lo que la superficie ``surface`` (float64, de la forma
    de la rejilla de ``masks``) mueve frente a su partida ``start`` —más que ``min_thickness_m`` (m),
    con dato en las dos— **fuera del límite** de ``masks`` (:func:`limit_cells`: un corte fuera del
    límite para cortar o un relleno fuera del perímetro), con su volumen y su área. ``name`` es el
    nombre del dato de la superficie y ``version`` el código de su versión (sin él, la de
    ``masks``). Ninguna entrada se modifica.

    ``ValueError`` (error del programa) si una rejilla no es de la forma de la de ``masks`` o el
    espesor no es un número finito ≥ 0."""
    design = _grid(surface, "la superficie", masks)
    terrain = _grid(start, "la superficie de partida", masks)
    moved = moved_cells(terrain, design, min_thickness_m)
    cut_inside, fill_inside = limit_cells(masks)
    with np.errstate(invalid="ignore"):
        outside = moved & (((design < terrain) & ~cut_inside) | ((design > terrain) & ~fill_inside))
    cells = int(np.count_nonzero(outside))
    cell_area = masks.grid.cell_area
    volume = float(np.abs(design[outside] - terrain[outside]).sum()) * cell_area
    return RefitCheck(name, version or masks.version_uid, cells, cells * cell_area, volume,
                      float(min_thickness_m))


# --- El ajuste (T32; RF-014-27, RF-014-28; A13, P-3) ----------------------------------------------

REFIT_NAME = "ajuste a un límite nuevo"
"""El nombre de la envolvente del ajuste en los mensajes de la 013 (RF-013-15)."""
REFIT_PHASE = "refit"
"""La fase de los pasos del ajuste."""
NOT_NEEDED_CODE = "des.refit_not_needed"
"""El aviso de una superficie que el límite nuevo no corta: su ajuste no hacía falta."""
ANGLE_CODE = "des.refit_angle"
"""El rechazo de un ángulo que no es la cara del perfil de la superficie (RF-014-28)."""
ANGLE_TOLERANCE_DEG = 1e-9
"""Lo que puede diferir de la cara del perfil un ángulo pedido por guion (°): el mismo número
escrito de otra forma (60 y 60,0), no otro ángulo."""
ORDER_CODE = "des.refit_order"
"""La nota de la regla de orden de una cantera aplicada a sus dos superficies ajustadas (T53;
RF-014-14): la cantera, la superficie que cambió y sus celdas, las que cambió más de 1 mm (T60);
sin ninguna, no hay nota (T61)."""
ORDER_SIDE_CODE = "des.refit_order_side"
"""El aviso de una superficie de una cantera ajustada sin la otra que deja la final por encima de
la explotación (T53; RF-014-14): la superficie, la cantera, la otra, las celdas y cuánto."""
SOURCE_STALE_CODE = "des.refit_source_stale"
"""El aviso de un diseño obsoleto del que sale lo que se ajusta (T54; RF-014-31, hallazgo F-16):
recalcularlo con el límite vigente rehace el ajuste, que sustituye al que se cree ahora; el nombre
del diseño (``design``) y las superficies del ajuste que salen de él (``surfaces``)."""
_FIGURE = "des.refit_m3"


@dataclass(frozen=True, slots=True)
class ProfileFace:
    """La cara de un perfil de banco que lee el ajuste (RF-014-27; P-3): su ``code``, su ``name``
    (con el que lo nombran los mensajes), la inclinación de la cara ``face_deg`` *α* (°, de 0 a 90
    excluidos) y el ``mesh_factor`` (—, de 0 excluido a 1). Un valor sin valor o fuera de rango es
    ``DesignError`` ``des.profile_value_missing`` o ``_range`` nombrando el perfil, el campo y el
    valor (RF-013-19)."""

    code: str
    name: str
    face_deg: float
    mesh_factor: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "face_deg", check_bench_value(
            self.name, self.code, BenchParam.FACE, self.face_deg))
        object.__setattr__(self, "mesh_factor", check_bench_value(
            self.name, self.code, BenchParam.MESH_FACTOR, self.mesh_factor))

    @property
    def rule(self) -> SlopeRule:
        """La pendiente con que baja la envolvente del ajuste: ``tan α`` con el factor de malla
        (la efectiva es su producto, RF-013-11)."""
        return SlopeRule(math.tan(math.radians(self.face_deg)), self.mesh_factor)


def profile_faces(values: Mapping[str, object], codes: Iterable[str],
                  names: Mapping[str, str] | None = None) -> dict[str, ProfileFace]:
    """La :class:`ProfileFace` de cada perfil de ``codes`` con la cara y el factor de malla de
    ``values`` (clave ``des.bench.{p}.…`` → valor: los que anotó la operación o los que se
    resuelven hoy) y su nombre de ``names`` (código → nombre; sin él, el código). Un valor que
    falta o está fuera de rango se rechaza como en :class:`ProfileFace`."""
    shown = {} if names is None else names
    found: dict[str, ProfileFace] = {}
    for code in dict.fromkeys(codes):
        face: Any = values.get(bench_key(code, BenchParam.FACE))
        mesh: Any = values.get(bench_key(code, BenchParam.MESH_FACTOR))
        found[code] = ProfileFace(code, shown.get(code, code), face, mesh)
    return found


def face_slope(labels: np.ndarray, base: ProfileFace, sectors: Sequence[ProfileFace]
               ) -> SlopeField:
    """La pendiente del ajuste en cada celda (RF-014-27; ADR-0029): ``tan α · malla`` del perfil
    del sector de la celda —la etiqueta ``k`` (1 a n, como ``design.seeds.sector_layout``) es
    ``sectors[k − 1]`` (el perfil de ese sector o, si no tiene uno propio, el base)— y la del perfil
    ``base`` en las celdas sin sector (etiqueta 0). Con un solo perfil, una constante (la que
    admite también la euclídea exacta). ``ValueError`` (error del programa) si una celda tiene una
    etiqueta sin perfil."""
    rules = [face.rule for face in sectors]
    codes = np.asarray(labels)
    if codes.ndim != 2 or codes.dtype.kind not in "iu":
        raise ValueError("las etiquetas de sector son una rejilla de enteros de 2 dimensiones")
    if all(rule == base.rule for rule in rules):
        if codes.size and int(codes.max()) > len(rules):
            raise ValueError(f"hay etiquetas de sector hasta {int(codes.max())} y solo "
                             f"{len(rules)} perfiles")
        return SlopeField(base.rule.effective)
    return sector_slope(codes, rules, base.rule)


def check_angle(surface: str, faces: Iterable[ProfileFace], angle_deg: float | None) -> None:
    """**RF-014-28** (error 46; P-3): un ajuste se hace con la cara del perfil de la superficie,
    no con otro ángulo. Sin ``angle_deg`` (lo normal: no se pide), nada; con uno, cada perfil de
    ``faces`` (los que usa la superficie ``surface``: el base y los de sus sectores) tiene que
    tener esa cara (a :data:`ANGLE_TOLERANCE_DEG`); si no, ``DesignError`` ``des.refit_angle``
    nombrando la superficie, el primer perfil que no la tiene, su cara y el ángulo pedido."""
    if angle_deg is None:
        return
    value = float(angle_deg)
    for face in faces:
        if not math.isfinite(value) or abs(value - face.face_deg) > ANGLE_TOLERANCE_DEG:
            raise DesignError(ANGLE_CODE, obj=f"Superficie «{surface}»", field="ángulo",
                              value=value, surface=surface, profile=face.name,
                              face=face.face_deg)


@dataclass(frozen=True, slots=True, eq=False)
class Refit:
    """El ajuste de una superficie a un límite nuevo (A13; RF-014-27): ``surface``, el nombre de su
    dato; ``grid``, la superficie ajustada ``S'`` (m, float64, nueva); ``check``, lo que dejaba
    fuera del límite nuevo antes (:class:`RefitCheck`, la comprobación de la T31); el volumen de
    ajuste ``volume_m3`` (``Σ |S' − S| · área de celda``), las ``cells`` que cambian y, de ellas,
    las que vuelven al terreno fuera del límite (``outside_cells``), y ``cell_area_m2``. Si el
    ajuste ata después las dos superficies de una cantera (T53, véase el módulo), ``grid`` es la
    atada y el volumen y las celdas siguen siendo los de su cara."""

    surface: str
    grid: np.ndarray
    check: RefitCheck
    volume_m3: float
    cells: int
    outside_cells: int
    cell_area_m2: float

    @property
    def needed(self) -> bool:
        """Si el límite nuevo dejaba algo de la superficie fuera (si no, no se toca)."""
        return self.check.outside

    @property
    def area_m2(self) -> float:
        """El área de las celdas que cambian (m²)."""
        return self.cells * self.cell_area_m2

    @property
    def notice(self) -> Notice | None:
        """El aviso ``des.refit_not_needed`` si el límite nuevo no corta la superficie (spec §8:
        «ajuste de 0 m³ y aviso de que no hacía falta»); ``None`` si hacía falta."""
        if self.needed:
            return None
        return Notice(NOT_NEEDED_CODE, {"surface": self.surface})


def _refit_units(design: np.ndarray, start: np.ndarray, masks: MaskSet, slope: SlopeField,
                 thickness: float, metric: Metric, name: str, version: str
                 ) -> Generator[None, None, Refit]:
    """Las unidades de :func:`refit_steps`: la comprobación, la envolvente desde el anillo y la
    superficie ajustada con lo que cambia, por bandas de filas."""
    geometry = masks.grid
    check = outside_volume(design, start, masks, thickness, name=name, version=version)
    yield None
    if not check.outside:
        return Refit(name, design.copy(), check, 0.0, 0, 0, geometry.cell_area)
    cut_inside, fill_inside = limit_cells(masks)
    with np.errstate(invalid="ignore"):
        ring = dilate_square(cut_inside, 1) & ~cut_inside & np.isfinite(start)
    seed = np.where(ring, start, np.nan)
    yield None
    lower = yield from seed_envelope_steps(seed, geometry, slope, metric, Direction.DOWN,
                                           f"{name} ({REFIT_NAME})")
    found = design.copy()
    step = max(1, CELLS_PER_UNIT // max(geometry.ncols, 1))
    sums: list[float] = []
    cells = outside = 0
    for first in range(0, geometry.nrows, step):
        rows = slice(first, first + step)
        before, ground = design[rows], start[rows]
        valid = np.isfinite(before) & np.isfinite(ground)
        inside = cut_inside[rows]
        with np.errstate(invalid="ignore"):
            raised = np.maximum(before, np.minimum(ground, lower[rows]))
            kept = fill_inside[rows] & (before > ground)  # un relleno dentro del perímetro
            after = np.where(inside, raised, np.where(kept, before, ground))
            changed = valid & (after != before)
        found[rows] = np.where(changed, after, before)
        sums.append(float(np.abs(after[changed] - before[changed]).sum()))
        cells += int(np.count_nonzero(changed))
        outside += int(np.count_nonzero(changed & ~inside))
        yield None
    return Refit(name, found, check, math.fsum(sums) * geometry.cell_area, cells, outside,
                 geometry.cell_area)


def refit_steps(surface: np.ndarray, start: np.ndarray, masks: MaskSet, slope: SlopeField,
                min_thickness_m: float, *, name: str, metric: Metric | str = Metric.CHAMFER5,
                version: str = "", budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """**A13**, el ajuste (RF-014-27): la superficie de diseño ``surface`` (``S``, m, float64, de la
    forma de la rejilla de ``masks``) ajustada al límite de las máscaras nuevas ``masks`` sobre su
    partida ``start`` (``z``, m), con la pendiente ``slope`` (``tan α · malla`` de la cara de su
    perfil en cada celda, :func:`face_slope`) y la ``metric`` de la 013 (*chamfer* 5×5 por
    defecto, ADR-0014), por pasos de ``budget_s`` como mucho: el último ``Progress`` (fase
    :data:`REFIT_PHASE`) lleva el :class:`Refit` (véase el módulo). ``min_thickness_m`` (m) es el
    espesor mínimo de la 012 con que se mira si el límite nuevo deja algo fuera; ``name``, el
    nombre del dato de la superficie (en el resultado, el aviso y los mensajes de la envolvente,
    «<superficie> (ajuste a un límite nuevo)»); ``version``, el código de la versión del aviso.

    ``ValueError`` (error del programa) al llamar si una rejilla no es de la forma de las
    máscaras, el espesor no es finito y ≥ 0, la pendiente no casa o la métrica no es de la 013;
    al avanzar, los rechazos de la envolvente de la 013 (RF-013-15). Ninguna entrada se modifica y
    no se escribe nada; cerrar el generador a mitad no deja nada."""
    design = _grid(surface, "la superficie", masks)
    terrain = _grid(start, "la superficie de partida", masks)
    thickness = _thickness(min_thickness_m)
    if not isinstance(slope, SlopeField):
        raise TypeError(f"la pendiente es un SlopeField, no {slope!r}")
    if not slope.uniform and np.shape(slope.tan) != masks.grid.shape:
        raise ValueError(f"la pendiente {np.shape(slope.tan)} no es de la forma de la rejilla "
                         f"{masks.grid.shape}")
    way = Metric(metric)
    if way is Metric.EXACT and not slope.uniform:
        raise ValueError("la euclídea exacta solo admite una pendiente constante (RF-013-16)")
    work = _refit_units(design, terrain, masks, slope, thickness, way, name, version)
    return pace_progress(work, budget_s, phase=REFIT_PHASE,
                         running=f"Ajustando «{name}» al límite nuevo…",
                         finished=f"«{name}» ajustada al límite nuevo")


@dataclass(frozen=True, slots=True, eq=False)
class RefitOutcome:
    """Lo que calcula ``des.refit`` (RF-014-27, RF-014-29): el ``name`` del ajuste, el
    :class:`Refit` de cada superficie (``refits``, en el orden de la petición), sus cifras
    CALCULADO (``figures``, :func:`refit_figures`), el ``message`` de la operación, las notas y los
    avisos del orden de las dos superficies de una cantera (``order_notices``, :data:`ORDER_CODE` y
    :data:`ORDER_SIDE_CODE`; T53), los de los diseños obsoletos de los que sale
    (``stale_notices``, :data:`SOURCE_STALE_CODE`; T54) y los del salto creado de cada superficie
    ajustada (``created_notices``: ``des.edge_surface_step`` y sus tramos, T56; RF-014-20,
    RF-014-21)."""

    name: str
    refits: tuple[Refit, ...]
    figures: tuple[FigureSpec, ...]
    message: str
    order_notices: tuple[Notice, ...] = ()
    stale_notices: tuple[Notice, ...] = ()
    created_notices: tuple[Notice, ...] = ()

    @property
    def volume_m3(self) -> float:
        """El volumen de ajuste de todas las superficies (m³)."""
        return math.fsum(item.volume_m3 for item in self.refits)

    @property
    def notices(self) -> tuple[Notice, ...]:
        """Los avisos ``des.refit_not_needed`` de las superficies que el límite nuevo no corta y
        los del salto creado de cada superficie ajustada (T56), lo de cada superficie; detrás, los
        del orden de las dos superficies de una cantera (T53) y, al final, los de los diseños
        obsoletos de los que sale (T54)."""
        return (*(item.notice for item in self.refits if item.notice is not None),
                *self.created_notices, *self.order_notices, *self.stale_notices)

    def refit(self, surface: str) -> Refit:
        """El ajuste de la superficie ``surface`` (el nombre de su dato); ``KeyError`` si no es de
        este ajuste."""
        for item in self.refits:
            if item.surface == surface:
                return item
        raise KeyError(surface)


def refit_figures(name: str, refits: Sequence[Refit]) -> tuple[FigureSpec, ...]:
    """La cifra CALCULADO ``des.refit_m3`` (m³; RF-014-27; plan 014 §5.2.3) de cada superficie del
    ajuste ``name``, con el ámbito de ``provenance.refit_figure_scope`` (el nombre del ajuste y el
    de la superficie): su volumen de ajuste, 0 si no hacía falta."""
    return tuple(FigureSpec(_FIGURE, float(item.volume_m3), "m3",
                            scope=provenance.refit_figure_scope(name, item.surface))
                 for item in refits)


def _order_text(notice: Notice) -> str:
    """Lo que dice el mensaje de la operación de una nota o un aviso del orden (T53)."""
    values = notice.values
    if notice.code == ORDER_CODE:
        return (f"regla de orden de la cantera «{values['quarry']}»: {values['cells']} celdas de "
                f"«{values['surface']}»")
    return (f"«{values['surface']}» deja la final de la cantera «{values['quarry']}» por encima "
            f"de la explotación en {values['cells']} celdas")


def refit_outcome(name: str, refits: Sequence[Refit], order_notices: Iterable[Notice] = (),
                  stale_notices: Iterable[Notice] = (), *,
                  created_notices: Iterable[Notice] = ()) -> RefitOutcome:
    """El :class:`RefitOutcome` del ajuste ``name`` con sus ``refits``, las notas y avisos del
    orden de las dos superficies de una cantera (``order_notices``, T53), los avisos de los
    diseños obsoletos de los que sale (``stale_notices``, T54) y los del salto creado de cada
    superficie ajustada (``created_notices``, T56): las cifras y el mensaje (cada superficie con
    su volumen de ajuste y sus celdas, o «no hacía falta», y lo del orden; el salto creado no
    cambia el mensaje)."""
    found = tuple(refits)
    orders = tuple(order_notices)
    parts = [f"«{item.surface}» {format_value(round(item.volume_m3, 1))} m³ en {item.cells} "
             "celdas" if item.needed else f"«{item.surface}» 0 m³ (no hacía falta)"
             for item in found]
    parts += [_order_text(notice) for notice in orders]
    message = f"Ajuste «{name}» al límite nuevo calculado: {'; '.join(parts)}"
    return RefitOutcome(name, found, refit_figures(name, found), message, orders,
                        tuple(stale_notices), tuple(created_notices))

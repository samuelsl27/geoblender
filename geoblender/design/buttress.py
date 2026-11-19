# SPDX-License-Identifier: GPL-3.0-or-later
"""El contrafuerte: la semilla en la coronación, el escalonado en relleno y la composición sin corte (spec 016, T26; HU-016-3;
RF-016-01, RF-016-17, RF-016-18; RNF-016-02, RNF-016-03; plan 016 §5.4 A0 y A10, §5.7 P-8, §5.8 H-6 y H-10; D-7, D-21, D-24;
CE-016-10). Dominio puro: sin proyecto y sin ``bpy``.

Un contrafuerte es **el escalonado en relleno de la 013 desde una semilla en la coronación** (P-8): reutiliza, sin tocarlas, las
piezas ya probadas de la 013 y la 014 (la envolvente descendente de :func:`~.edges.seed_envelope_steps`, el escalonado de
:func:`~.benching.bench_fill`, el recorte final de :func:`~.benching.final_trim_steps` y la composición de :func:`~.compose.compose`)
y **no corta nada**. Lo que entrega:

- :class:`ButtressJob` (el homólogo de ``removal.RemovalJob`` y ``thickness.BodyJob``): todo lo que el cálculo necesita **ya
  leído** y nada del proyecto —la petición, el código de la entidad (``BTR-001``), la rejilla, el perfil de banco de la 013
  (:class:`~.model.BenchProfile`), la superficie de partida, la zona de coronación, el relleno admitido de las máscaras de la 012
  y los valores resueltos (la cota de coronación, el alcance, la métrica)— para probarlo sin proyecto y reproducirlo
  (``reproduce.py``).
- :func:`buttress_steps` y :func:`compute_buttress` (A10): el :class:`ButtressOutcome` con la superficie nueva, el espesor, la
  huella entera, lo escalonado sin máscara y las cifras ``des.btr_volume_m3``, ``des.btr_area_m2`` y ``des.btr_height_max_m``.
- :func:`check_crown_anchor`, :func:`nearest_anchor` y :func:`below_support_error` (RF-016-18, D-21): los dos rechazos de la cota de
  coronación, que no registran nada ni eligen una cota por la persona.
- :func:`buttress_window` y :func:`buttress_reach_m` (A0): la ventana de trabajo de la zona ampliada por lo que alcanza su
  envolvente, que es lo que basta leer de la partida y de las máscaras.

**A10, paso a paso** (``buttress_steps``):

1. **La semilla** es la cota de coronación ``crown_m`` en las celdas de la zona de coronación con dato y con la partida por debajo
   de ella; las demás celdas de la zona **no siembran** (RF-016-17). Si ninguna siembra, no hay contrafuerte
   (``des.buttress_crown_below_support``, RF-016-18: la coronación a la cota de la partida o por debajo en toda la zona).
2. **La envolvente descendente** de la semilla (:func:`~.edges.seed_envelope_steps`) con la tangente del talud general del
   perfil, ``h / (h/tan α + B)``, por su factor de malla, y la métrica del contrafuerte (la euclídea exacta, por defecto, o el
   *chamfer* 5×5 de la 013); con ``reach_m`` fijado, solo hasta esa distancia de la zona (RF-013-14).
3. **El escalonado en relleno** (:func:`~.benching.bench_fill`, RF-013-23: berma primero, anclado a ``z₀ + n·h``) y **el recorte
   final** (:func:`~.benching.final_trim_steps`, RF-013-27) con la cara del perfil por su factor de malla, como en la 013.
4. **La composición** ``máx(partida, recorte)`` en el relleno admitido de la 012 (:func:`~.compose.compose` con
   :attr:`~.model.BenchSense.FILL`): **también en las zonas de solo restauración**, que la 012 admite como relleno (D-24, H-10,
   RF-012-13), sin recortar el pie a la zona dibujada (error 19) y **sin cortar ninguna celda**; donde no sube, la partida bit a
   bit. Lo que el escalonado sin máscara tiene de más que lo compuesto es el pie cortado de RF-016-19 (T28, que lee
   :attr:`ButtressOutcome.stepped`).
5. **El espesor** (RF-016-01) es la superficie menos la partida (la base del contrafuerte es su apoyo: la superficie de partida):
   ``derive`` comprueba en todas las celdas que no es negativo y que la base no queda por encima del techo. No se guarda: el plan
   no tiene un dato de espesor del contrafuerte (solo ``des_psf_``, ``des_epr_`` y ``des_prp_``).

**La cota de coronación** (D-21, RF-016-18). Es la **cota de ancla** del perfil, ``z₀ + n·h``: un escalonado en relleno queda por
debajo de su envolvente y a menos de ``h`` de ella (RF-013-23), así que fuera del ancla no llega a la coronación. Una cota que no
dista del ancla más próxima ≤ 10⁻⁹ m se rechaza **al pedir los pasos** nombrando la capa, el contrafuerte, la cota, el perfil y la
cota del ancla más próxima (a igual distancia, la menor); ninguna cota se elige por la persona.

**El apoyo.** El contrafuerte se apoya en la superficie de partida del cálculo (``start``): la semilla, la composición y el
espesor se miden sobre ella. Que la persona declare otra superficie de apoyo (la de explotación de una cantera de la 014: D-7) es de
la preparación (T27): decide qué superficie entra como ``start`` y registra la dependencia ``supported_on``; no cambia este cálculo.

**Leer solo la ventana** (A0): como ``RemovalJob``, el trabajo puede llevar la partida, la zona y el relleno admitido de una ventana
de la rejilla (``region``): la de :func:`buttress_window` con el alcance de :func:`buttress_reach_m`. A diferencia de una retirada,
**la envolvente de un contrafuerte llega hasta donde la partida la corta**, así que la ventana ha de cubrir lo que alcanza hasta la
cota **más baja de la partida de la rejilla entera** (``lowest_m``; con ``reach_m`` fijado basta él): el trabajo comprueba que la ventana
lo cubre y, si no, es un error del programa (:class:`ValueError`), nunca un contrafuerte recortado en silencio. Las coordenadas
absolutas se pasan a locales respecto a la esquina de la rejilla solo dentro del cálculo (principio 6, ADR-0005) y ninguna entrada
se modifica.
"""

from __future__ import annotations

import math
from collections.abc import Generator, Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

from ..core.project.model import Progress
from ..core.provenance.figures import FigureSpec
from ..gis.grid import Grid
from ..gis.masks.compile import STEP_BUDGET_S
from .benching import bench_fill, final_trim_steps
from .compose import compose
from .edges import seed_envelope_steps
from .envelopes import CELLS_PER_UNIT, CHAMFER_SCALE, TOLERANCE_M, SlopeField, reach_steps
from .messages import DesignError
from .model import BenchProfile, BenchSense, BodySense, ButtressRequest, Direction, Metric
from .params import ButtressParam, check_entity_param, entity_key, entity_params, entity_params_of
from .pipeline import forward
from .platform import Window, _shaped_array, _whole, _window_of, work_window
from .preview import Notice
from .provenance import buttress_figures
from .seeds import pace_progress
from .stockpiles import window_grid
from .thickness import derive

__all__ = [
    "ButtressJob",
    "ButtressOutcome",
    "below_support_error",
    "buttress_reach_m",
    "buttress_steps",
    "buttress_window",
    "check_crown_anchor",
    "compute_buttress",
    "nearest_anchor",
    "trim_margin_m",
]

_PHASE = "buttress"
_OFF_ANCHOR = "des.buttress_crown_off_anchor"
_BELOW_SUPPORT = "des.buttress_crown_below_support"
_OBJ = "Contrafuerte «{}»"


# --- Los rechazos de la cota de coronación (RF-016-18, D-21) -----------------------------------------------------------------


def nearest_anchor(profile: BenchProfile, level_m: float) -> float:
    """La cota de ancla ``z₀ + n·h`` del perfil más próxima a ``level_m`` (m): ``n`` es el entero más próximo a ``(nivel − z₀)/h``;
    a igual distancia, la menor (RF-016-18, D-21)."""
    steps = (float(level_m) - profile.anchor_m) / profile.height_m
    return profile.anchor_m + math.ceil(steps - 0.5) * profile.height_m


def check_crown_anchor(request: ButtressRequest, code: str, profile: BenchProfile, crown_m: float) -> None:
    """**RF-016-18, D-21**: la cota de coronación ``crown_m`` ha de ser **del ancla** del perfil (``z₀ + n·h``, a ≤ 10⁻⁹ m: el
    redondeo de la suma). Si no, ``des.buttress_crown_off_anchor`` (:class:`~.messages.DesignError`), nombrando la capa, el
    contrafuerte, la cota, el perfil y la **cota del ancla más próxima** (:func:`nearest_anchor`); no se registra nada ni se elige
    una cota por la persona. Antes de leer nada: no depende de ninguna superficie."""
    anchor = nearest_anchor(profile, crown_m)
    if abs(float(crown_m) - anchor) > TOLERANCE_M:
        raise DesignError(_OFF_ANCHOR, obj=_OBJ.format(request.name), field=entity_key(code, ButtressParam.CROWN),
                          value=crown_m, layer=request.layer, entity=request.name, profile=profile.name, anchor=anchor)


def below_support_error(request: ButtressRequest, code: str, crown_m: float) -> DesignError:
    """**RF-016-18**: ``des.buttress_crown_below_support``, el rechazo de un contrafuerte cuya cota de coronación queda a la de la
    partida o por debajo en toda la zona de coronación (o la zona no tiene dato): no hay contrafuerte. Nombra la capa, el
    contrafuerte y la cota. No se registra nada."""
    return DesignError(_BELOW_SUPPORT, obj=_OBJ.format(request.name), field=entity_key(code, ButtressParam.CROWN),
                       value=crown_m, layer=request.layer, entity=request.name)


# --- Lo leído ---------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class ButtressJob:
    """Lo que necesita calcular un contrafuerte, ya leído y sin proyecto (plan 016 §5.3.1): la ``request`` (su nombre y la capa de
    las zonas, para nombrarlos en un rechazo), el ``code`` de la entidad (``BTR-001``), la rejilla ``grid`` (del proyecto, de
    celdas cuadradas), el ``profile`` de banco de la 013 (:class:`~.model.BenchProfile`: ``h``, ``α``, ``B``, ``z₀`` y el factor de
    malla), la superficie de partida ``start`` (m, float64; ``NaN``, sin dato), la ``zone`` de coronación (máscara booleana de las
    celdas con el centro dentro del polígono), el relleno admitido ``fill_allowed`` (booleana; el de las máscaras de la 012,
    :func:`~.compose.admitted` con :attr:`~.model.BenchSense.FILL`, que incluye las zonas de solo restauración: D-24) y los valores
    resueltos (``values``: por último segmento de su clave, los de :class:`~.params.ButtressParam`: ``crown_m`` —sin valor por
    defecto: D-21—, ``reach_m`` —opcional—, ``metric`` y ``profile``, que si está es el código del ``profile``).

    ``start``, ``zone`` y ``fill_allowed`` son de la **rejilla entera** o, con ``region``, de **esa ventana** de la rejilla (A0: la de
    :func:`buttress_window`). Con una ventana hace falta además ``lowest_m``, la cota más baja de la partida de la **rejilla entera**
    (m), para saber hasta dónde llega la envolvente (sin ``reach_m``). ``ValueError`` (errores del programa) si el código no es el de
    un contrafuerte, una clave de ``values`` no es de un contrafuerte, el perfil no es el de ``values``, un array no es de su forma,
    las celdas no son cuadradas o ``lowest_m`` no es finito; ``TypeError`` si la petición o el perfil no son lo que son."""

    request: ButtressRequest
    code: str
    grid: Grid
    profile: BenchProfile
    start: np.ndarray
    zone: np.ndarray
    fill_allowed: np.ndarray
    values: Mapping[str, object]
    region: Window | None = None
    lowest_m: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.request, ButtressRequest):
            raise TypeError(f"la petición de un contrafuerte es una ButtressRequest, no {type(self.request).__name__}")
        kind = entity_params_of(self.code).kind
        if kind != "buttress":
            raise ValueError(f"el código {self.code!r} no es el de un contrafuerte (es de {kind})")
        if not isinstance(self.grid, Grid):
            raise TypeError(f"la rejilla es una Grid, no {type(self.grid).__name__}")
        if self.grid.dx != self.grid.dy:
            raise ValueError(f"la rejilla de un contrafuerte es la del proyecto, de celdas cuadradas, no {self.grid.dx} × {self.grid.dy}")
        if not isinstance(self.profile, BenchProfile):
            raise TypeError(f"el perfil de un contrafuerte es un BenchProfile, no {type(self.profile).__name__}")
        if self.region is not None:
            object.__setattr__(self, "region", _window_of(self.region, self.grid))
        window = self.window
        shape = (window[0].stop - window[0].start, window[1].stop - window[1].start)
        where = "de la rejilla" if self.region is None else "de su ventana"
        for name, dtype, what in (("start", np.float64, "la partida"), ("zone", np.bool_, "la zona de coronación"),
                                  ("fill_allowed", np.bool_, "el relleno admitido")):
            object.__setattr__(self, name, _shaped_array(getattr(self, name), shape, dtype, what, where))
        known = {param.value for param in ButtressParam}
        unknown = sorted(set(self.values) - known)
        if unknown:
            raise ValueError(f"los valores de un contrafuerte son de {', '.join(sorted(known))}, no «{unknown[0]}»")
        chosen = self.values.get(ButtressParam.PROFILE.value)
        if chosen is not None and chosen != self.profile.code:
            raise ValueError(f"el valor «profile» del contrafuerte es {chosen!r} y su perfil, {self.profile.code!r}")
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))
        if self.lowest_m is not None:
            lowest = float(self.lowest_m)
            if not math.isfinite(lowest):
                raise ValueError(f"la cota más baja de la partida es un número finito, no {self.lowest_m!r}")
            object.__setattr__(self, "lowest_m", lowest)

    @property
    def window(self) -> Window:
        """La ventana de la rejilla que cubren los arrays: ``region`` o, sin ella, la rejilla entera."""
        return _whole(self.grid) if self.region is None else self.region


@dataclass(frozen=True, slots=True)
class _Settings:
    """Lo que lee A10 de los valores del contrafuerte, ya comprobado."""

    crown_m: float
    reach_m: float | None
    metric: Metric
    tan: float


def _settings(job: ButtressJob) -> _Settings:
    """La cota de coronación (obligatoria: D-21; del ancla del perfil: RF-016-18), el alcance (opcional) y la métrica (la euclídea
    exacta, si no se da) de ``job``, comprobados (``des.entity_param_missing``, ``_range`` o ``_choice``, nombrando la capa, la
    entidad, la clave y el valor: RF-015-08; ``des.buttress_crown_off_anchor``), y la tangente efectiva de la envolvente: la del
    talud general del perfil por su factor de malla."""
    name, code, found, layer = job.request.name, job.code, job.values, job.request.layer
    crown = check_entity_param(name, code, ButtressParam.CROWN, found.get(ButtressParam.CROWN.value), layer=layer)
    reach = check_entity_param(name, code, ButtressParam.REACH, found.get(ButtressParam.REACH.value), layer=layer)
    metric = found.get(ButtressParam.METRIC.value)
    if metric is None:
        metric = entity_params("buttress").template(ButtressParam.METRIC.value).default
    metric = check_entity_param(name, code, ButtressParam.METRIC, str(metric), layer=layer)
    assert isinstance(crown, float) and isinstance(metric, str) and (reach is None or isinstance(reach, float))
    check_crown_anchor(job.request, code, job.profile, crown)
    return _Settings(crown, reach, Metric(metric), job.profile.general_tan * job.profile.mesh_factor)


# --- La ventana de trabajo (A0) ----------------------------------------------------------------------------------------------


def trim_margin_m(profile: BenchProfile, metric: Metric | str = Metric.EXACT) -> float:
    """**A0**: cuánto más allá de lo que alcanza la envolvente (m) puede una celda cambiar el **recorte final** de una celda de
    dentro. El recorte (RF-013-27) es ``mín_j [escalonado_j + tan α · malla · d_chamfer(c, j)]``: una celda ``j`` solo lo baja si
    el escalonado cae entre ``c`` y ``j`` más de lo que cuesta el camino. Como el escalonado queda a menos de ``h`` de la
    envolvente (RF-013-23) y esta baja ``talud general · malla`` por metro (por ``1/0,98644`` más con el *chamfer*, ADR-0014), una
    ``j`` a más de ``h / (0,98644 · tan α · malla − (talud general · malla) · (1 | 1/0,98644))`` de ``c`` no lo baja. Con la
    cara a menos que el talud general (sin berma) ese número no es positivo y el recorte no tiene alcance: ``math.inf``."""
    ratio = 1.0 if Metric(metric) is Metric.EXACT else 1.0 / CHAMFER_SCALE
    gap = (CHAMFER_SCALE * math.tan(math.radians(profile.face_deg)) - ratio * profile.general_tan) * profile.mesh_factor
    return profile.height_m / gap if gap > 0.0 else math.inf


def buttress_reach_m(profile: BenchProfile, crown_m: float, lowest_m: float | None, reach_m: float | None = None,
                     metric: Metric | str = Metric.EXACT) -> float:
    """**A0**: hasta qué distancia (m) de la zona de coronación hay que leer para calcular el contrafuerte y que el resultado no
    dependa de lo que queda fuera. La envolvente baja ``talud general · factor de malla`` por metro desde ``crown_m`` y deja de
    pasar de la partida a ``(crown_m − lowest_m) / (talud general · malla)`` de la zona (``lowest_m``: la cota más baja de la
    partida de la **rejilla entera**; 0 si no baja de la coronación), y desde ahí el recorte final aún puede notar lo que hay a
    :func:`trim_margin_m` más. Con ``reach_m`` fijado (RF-013-14) nada pasa de él (más allá no hay escalonado): el menor de los
    dos, y sin ``lowest_m``, ``reach_m`` (``ValueError`` si no hay ninguno de los dos). Puede ser ``math.inf``: la rejilla
    entera."""
    if lowest_m is None:
        if reach_m is None:
            raise ValueError("el alcance de un contrafuerte sin alcance fijado necesita la cota más baja de la partida (lowest_m)")
        return float(reach_m)
    tangent = profile.general_tan * profile.mesh_factor
    bound = max(float(crown_m) - float(lowest_m), 0.0) / tangent + trim_margin_m(profile, metric)
    return bound if reach_m is None else min(bound, float(reach_m))


def buttress_window(zone: np.ndarray, grid: Grid, reach_m: float, metric: Metric | str = Metric.EXACT) -> Window | None:
    """**A0** (plan 016 §5.4): la ventana de trabajo de un contrafuerte: la caja de las celdas de ``zone`` (máscara de la rejilla
    entera) ampliada por el alcance ``reach_m`` (:func:`buttress_reach_m`) y dos celdas, recortada a la rejilla
    (:func:`~.platform.work_window`: ``⌈alcance / paso⌉ + 2`` celdas por cada lado y, con el *chamfer*, ``⌈alcance / (0,98644 ·
    paso)⌉ + 2``; con un alcance infinito, la rejilla entera). Es lo que basta leer de la partida y de las máscaras. ``None`` si
    la zona no tiene ninguna celda; ``ValueError`` si la máscara no es de la forma de la rejilla."""
    found = np.asarray(zone, dtype=np.bool_)
    if found.shape != grid.shape:
        raise ValueError(f"la zona es una máscara de la rejilla {grid.shape}, no de forma {found.shape}")
    rows = np.flatnonzero(found.any(axis=1))
    if rows.size == 0:
        return None
    if math.isinf(reach_m):
        return _whole(grid)
    cols = np.flatnonzero(found.any(axis=0))
    return work_window(slice(int(rows[0]), int(rows[-1]) + 1), slice(int(cols[0]), int(cols[-1]) + 1), reach_m, grid, metric)


def _check_window(job: ButtressJob, settings: _Settings) -> None:
    """Con una ventana (``region``), que cubre la de :func:`buttress_window` con el alcance de :func:`buttress_reach_m`: si no, un
    error del programa (``ValueError``), nunca un contrafuerte recortado en silencio."""
    region = job.region
    if region is None:
        return
    reach = buttress_reach_m(job.profile, settings.crown_m, job.lowest_m, settings.reach_m, settings.metric)
    rows = np.flatnonzero(job.zone.any(axis=1))
    if rows.size == 0:
        return  # sin zona en la ventana: lo dirá la semilla (des.buttress_crown_below_support)
    cols = np.flatnonzero(job.zone.any(axis=0))
    needed = (_whole(job.grid) if math.isinf(reach) else
              work_window(slice(region[0].start + int(rows[0]), region[0].start + int(rows[-1]) + 1),
                          slice(region[1].start + int(cols[0]), region[1].start + int(cols[-1]) + 1), reach, job.grid,
                          settings.metric))
    if not (region[0].start <= needed[0].start and needed[0].stop <= region[0].stop
            and region[1].start <= needed[1].start and needed[1].stop <= region[1].stop):
        raise ValueError(f"la ventana {region!r} no cubre lo que alcanza la envolvente del contrafuerte ({needed!r}): léase la de "
                         "buttress_window con el alcance de buttress_reach_m")


# --- Lo que da --------------------------------------------------------------------------------------------------------------


def _decimal(value: float, places: int = 2) -> str:
    """``value`` con coma decimal y sin ceros de más (para el mensaje de la operación)."""
    return f"{value:.{places}f}".rstrip("0").rstrip(".").replace(".", ",")


@dataclass(frozen=True, slots=True, eq=False)
class ButtressOutcome:
    """El contrafuerte (A10; RF-016-01, RF-016-17), en su ventana de trabajo (``window``: filas y columnas de la rejilla; todas las
    rejillas de abajo son de su forma): la ``zone`` de coronación, las ``seeds`` (la zona con dato y con la partida por debajo de la
    coronación), ``stepped`` (el escalonado en relleno recortado **sin máscara**, m; ``NaN`` más allá del alcance: lo que el
    contrafuerte llegaría a ser donde las máscaras lo admitieran todo), la ``surface`` de diseño (``máx(partida, stepped)`` donde
    se admite el relleno y la partida, bit a bit, en las demás: sin cortar ninguna celda), el ``thickness`` (m, ≥ 0: la superficie
    menos la partida; ``NaN`` donde la partida no tiene dato; RF-016-01) y la ``footprint`` (la huella **entera**: las celdas donde
    la superficie sube, dentro y fuera de la zona dibujada).

    Las cifras: ``volume_m3`` (la suma del espesor por el área de la celda), ``area_m2`` (la de la huella) y ``height_max_m`` (lo más
    que sube una celda) con su lugar (``height_max_x``, ``height_max_y``: el centro de la primera celda de arriba abajo y de oeste a
    este que la tiene; ``None`` sin huella); ``cutoff_m2`` y ``cutoff_m3`` (el pie cortado por el borde de lo admitido: ``None``
    mientras no se mida, T28). ``crown_m``, ``reach_m``, ``metric`` y ``profile`` (el código del perfil) son los del contrafuerte,
    ``seed_cells`` las celdas de semilla, ``cell_area_m2`` el área de una celda y ``notices`` los avisos."""

    name: str
    code: str
    profile: str
    window: Window
    zone: np.ndarray
    seeds: np.ndarray
    stepped: np.ndarray
    surface: np.ndarray
    thickness: np.ndarray
    footprint: np.ndarray
    crown_m: float
    reach_m: float | None
    metric: Metric
    volume_m3: float
    area_m2: float
    height_max_m: float
    height_max_x: float | None
    height_max_y: float | None
    seed_cells: int
    cell_area_m2: float
    cutoff_m2: float | None = None
    cutoff_m3: float | None = None
    notices: tuple[Notice, ...] = ()

    @property
    def figures(self) -> tuple[FigureSpec, ...]:
        """Las cifras CALCULADO de la operación (:func:`~.provenance.buttress_figures`, con el ámbito de la entidad y en el orden de
        ``BUTTRESS_FIGURES``): ``des.btr_volume_m3``, ``_area_m2`` y ``_height_max_m`` y, si se midió el pie cortado (T28),
        ``_cutoff_m2`` y ``_cutoff_m3``."""
        return buttress_figures(self.name, self.code, {
            "des.btr_volume_m3": self.volume_m3, "des.btr_area_m2": self.area_m2, "des.btr_height_max_m": self.height_max_m,
            "des.btr_cutoff_m2": self.cutoff_m2, "des.btr_cutoff_m3": self.cutoff_m3})

    @property
    def message(self) -> str:
        """El mensaje de la operación (como el de una retirada): lo que dice el resumen de lo calculado, con el volumen (al metro
        cúbico), el área (al metro cuadrado) y la altura máxima."""
        return (f"Contrafuerte «{self.name}»: {round(self.volume_m3)} m³ sobre {round(self.area_m2)} m² y "
                f"{_decimal(self.height_max_m)} m de altura máxima")

    def compose(self, start: np.ndarray) -> np.ndarray:
        """La superficie entera que deja el contrafuerte: una rejilla **nueva** igual a ``start`` (la superficie de partida, de la
        rejilla entera) con la ventana de trabajo sustituida por :attr:`surface`. ``ValueError`` si ``start`` no es una rejilla
        que contenga la ventana."""
        whole = np.array(start, dtype=np.float64, copy=True)
        rows, cols = self.window
        if whole.ndim != 2 or rows.stop > whole.shape[0] or cols.stop > whole.shape[1]:
            raise ValueError(f"la superficie de partida {whole.shape} no contiene la ventana del contrafuerte ({rows}, {cols})")
        whole[self.window] = self.surface
        return whole


# --- A10 --------------------------------------------------------------------------------------------------------------------


def _seed_units(job: ButtressJob, settings: _Settings) -> Generator[None, None, np.ndarray]:
    """Las unidades de sembrar: la cota de coronación en las celdas de la zona con dato y con la partida por debajo de ella
    (``NaN`` en las demás). ``des.buttress_crown_below_support`` si ninguna siembra."""
    yield None
    with np.errstate(invalid="ignore"):
        below = np.isfinite(job.start) & (job.start < settings.crown_m)
    seeds = job.zone & below
    if not seeds.any():
        raise below_support_error(job.request, job.code, settings.crown_m)
    yield None
    return np.where(seeds, settings.crown_m, np.nan)


def _outcome_units(job: ButtressJob, settings: _Settings, seed: np.ndarray, stepped: np.ndarray
                   ) -> Generator[None, None, ButtressOutcome]:
    """Las unidades de componer la superficie (``máx(partida, recorte)`` en el relleno admitido), medir el espesor con la regla de
    RF-016-01 y sumar las cifras por bandas de filas."""
    start, grid = job.start, job.grid
    yield None
    surface = compose(start, stepped, job.fill_allowed, BenchSense.FILL)
    yield None
    with np.errstate(invalid="ignore"):
        rise = surface - start
        body = rise > 0.0  # NaN no es mayor que nada: la celda sin dato no cuenta
    derive(start, rise, BodySense.ON_BASE)  # RF-016-01: espesor ≥ 0 y base ≤ techo en todas las celdas
    yield None
    rows, cols = job.window
    height, width = start.shape
    step = max(1, CELLS_PER_UNIT // max(width, 1))
    parts: list[float] = []
    for first in range(0, height, step):
        band = slice(first, first + step)
        parts.append(float(rise[band][body[band]].sum()))
        yield None
    area = grid.cell_area
    count = int(np.count_nonzero(body))
    x = y = None
    biggest = 0.0
    if count:
        index = int(np.argmax(np.where(body, rise, -np.inf)))
        row, col = divmod(index, width)
        biggest = float(rise[row, col])
        x = grid.west + (cols.start + col + 0.5) * grid.dx
        y = grid.north - (rows.start + row + 0.5) * grid.dy
    return ButtressOutcome(job.request.name, job.code, job.profile.code, job.window, job.zone.copy(), np.isfinite(seed), stepped,
                           surface, rise, body, settings.crown_m, settings.reach_m, settings.metric, math.fsum(parts) * area,
                           count * area, biggest, x, y, int(np.count_nonzero(np.isfinite(seed))), area)


def _buttress_progress(job: ButtressJob, settings: _Settings, budget_s: float) -> Generator[Progress, None, None]:
    """Los pasos de :func:`buttress_steps`: sembrar, la envolvente (con el alcance, si se fija), el escalonado, el recorte final y la
    composición con sus cifras; cada pieza de la 013 con su propio ritmo (``budget_s``)."""
    profile = job.profile
    label = f"{job.request.name} (contrafuerte)"
    sub = window_grid(job.grid, job.window)
    seed: np.ndarray = yield from forward(pace_progress(
        _seed_units(job, settings), budget_s, phase="seeds", running="Sembrando la coronación del contrafuerte…",
        finished="Coronación sembrada"))
    envelope: np.ndarray = yield from forward(pace_progress(
        seed_envelope_steps(seed, sub, SlopeField(settings.tan), settings.metric, Direction.DOWN, label), budget_s,
        phase="envelope", running="Calculando la envolvente del contrafuerte…", finished="Envolvente del contrafuerte calculada"))
    if settings.reach_m is not None:
        distance: np.ndarray = yield from forward(reach_steps(seed, sub, settings.reach_m, settings.metric, name=label,
                                                              budget_s=budget_s))
        envelope[np.isnan(distance)] = np.nan
        del distance
    yield Progress("stairs", 0, 1, "Escalonando el contrafuerte…")
    tan_face = math.tan(math.radians(profile.face_deg))
    stairs = bench_fill(envelope, profile.height_m, tan_face, profile.berm_m, profile.anchor_m)
    trim = yield from forward(final_trim_steps(stairs, envelope, sub, tan_face, profile.mesh_factor, BenchSense.FILL,
                                               name=label, budget_s=budget_s))
    del stairs, envelope
    outcome: ButtressOutcome = yield from forward(pace_progress(
        _outcome_units(job, settings, seed, trim.grid), budget_s, phase="figures", running="Midiendo el contrafuerte…",
        finished="Contrafuerte medido"))
    yield Progress(_PHASE, 1, 1, outcome.message, result=outcome)


def buttress_steps(job: ButtressJob, *, budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """**A10** (RF-016-01, RF-016-17, RF-016-18; plan 016 §5.4): el contrafuerte de ``job`` por pasos de ``budget_s`` como mucho por
    pieza (RNF-016-03: ≤ 0,2 s cada llamada): el último ``Progress`` (fase ``buttress``) lleva el :class:`ButtressOutcome`.

    La semilla es ``crown_m`` en las celdas de la zona de coronación con la partida por debajo; con la envolvente descendente de la
    semilla (el talud general del perfil por su factor de malla, la métrica y el alcance del contrafuerte), el escalonado en
    relleno de RF-013-23 y su recorte final, la superficie es ``máx(partida, recorte)`` en el relleno admitido (también en las
    zonas de solo restauración) y la partida bit a bit en las demás: nada baja y el pie no se recorta a la zona dibujada. Da el
    volumen, el área y la altura máxima (RF-016-17) y el espesor, que cumple RF-016-01.

    Rechazos **al llamar**, nombrando la capa, el contrafuerte, la clave del campo y el valor (RF-015-08): sin cota de coronación
    (``des.entity_param_missing``: D-21, no se elige una por la persona), no finita, un alcance que no es mayor que 0
    (``des.entity_param_range``), una métrica que no es de la lista (``des.entity_param_choice``) o una cota de coronación que no es
    del ancla del perfil, con la cota del ancla más próxima (``des.buttress_crown_off_anchor``, RF-016-18). **Al avanzar**, una
    coronación a la cota de la partida o por debajo en toda la zona: no hay contrafuerte (``des.buttress_crown_below_support``,
    RF-016-18). ``ValueError`` (error del programa) si una ventana no cubre lo que alcanza la envolvente. Ninguna entrada se
    modifica y no se escribe nada; cerrar el generador a mitad no deja nada."""
    settings = _settings(job)
    _check_window(job, settings)
    return _buttress_progress(job, settings, budget_s)


def compute_buttress(job: ButtressJob) -> ButtressOutcome:
    """**A10**: :func:`buttress_steps` hasta el final, sin repartir el trabajo en pasos: el :class:`ButtressOutcome` de ``job``.
    Los mismos rechazos."""
    last: Progress | None = None
    for last in buttress_steps(job, budget_s=math.inf):
        pass
    found = None if last is None else last.result
    assert isinstance(found, ButtressOutcome)
    return found

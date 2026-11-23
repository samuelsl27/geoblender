# SPDX-License-Identifier: GPL-3.0-or-later
"""Los datos de la corta por bancos (spec 018, T05; HU-018-1; RF-018-01, 02, 04; plan 018 §5.1, §5.2.2 y §5.3.1).

Lo que entrega, todo inmutable (``frozen``, ``slots``) y sin ninguna cifra minera por defecto (lo que no se pide es ``None``: el
valor por defecto del parámetro o, si no lo tiene, el rechazo de RF-015-08, que es de la preparación):

- **La corta.** :class:`PitMode` (``up`` y ``down``: RF-018-02), :class:`PitRequest` (lo que pide el diálogo, con la capa y su
  campo, :class:`~design.road_model.LayerFields`), :class:`PitParams` (los valores de desfase y de parada **ya resueltos**),
  :class:`PitJob` (todo lo leído y **nada del proyecto**, para calcular sin proyecto y reproducir: la rejilla, la superficie de
  partida, las máscaras como arrays, los polígonos de origen :class:`PitSource`, los sectores :class:`PitSector`, el perfil base, la
  roseta, las rampas, los bancos fijados :class:`FixedBench` y los parámetros) y :class:`PitOutcome` (el resultado: las polilíneas
  :class:`Polyline`, los ejes de rampa :class:`RampPath`, la línea de cielo, las cifras por banco :class:`BenchFigures`, los
  hallazgos :class:`Finding` y el criterio que paró :class:`StopCriterion`).
- **La roseta y la rampa.** :class:`RoseRange` y :data:`RampDef` son los de :mod:`design.pit_rose` y :mod:`design.pit_ramp_def`
  (T04): se reexportan aquí para que quien calcula los pida de un solo sitio.
- **Los códigos de error** de lo que el cálculo no puede dar: :class:`PitCode`. Su valor **es** el código de
  :mod:`design.messages`; el texto, en español y en inglés, y la gravedad son de ahí.

**Lo define esta tarea y las demás no lo editan** (plan 018 §6, para poder paralelizar): si una tarea posterior necesita un campo,
lo avisa a la sesión principal. La validación al construir es de tipos y de forma (``TypeError`` si un valor no es de su tipo,
``ValueError`` si no es de su forma o rango): los rechazos de la persona, con su capa, su corta, su campo y su valor, son de la
preparación (T21). **Perezoso** (RNF-001-03): ni ``design.model`` ni habilitar Geoblender lo importan. Python puro (nivel 8).
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np

from ..core.provenance.figures import FigureSpec
from ..gis.grid import Grid
from ..gis.messages import format_value
from .model import BenchProfile, _name_or_none, _real_or_none, _text
from .params import PIT_RANGES, PitParam, ValueRange, entity_params_of
from .pit_ramp_def import PitRampDef
from .pit_rose import RoseRange
from .preview import Notice
from .road_model import (
    LayerFields,
    Parts,
    Point,
    Window,
    _flag,
    _label,
    _parts,
    _readonly,
    _real,
    _tuple_of,
    _window,
)
from .road_profiles import RoadProfile
from .supported_requests import _int_or_none, _named

__all__ = [
    "FINDING_UNITS",
    "MAX_BENCHES",
    "MAX_VERTICES",
    "BenchFigures",
    "Corner",
    "FixedBench",
    "Finding",
    "FindingKind",
    "LayerFields",
    "PitCode",
    "PitJob",
    "PitMode",
    "PitOutcome",
    "PitParams",
    "PitRequest",
    "PitSector",
    "PitSource",
    "Polyline",
    "PolylineKind",
    "RampDef",
    "RampPath",
    "RampStart",
    "RoseRange",
    "StopCriterion",
]

RampDef = PitRampDef
"""La definición de rampa de la corta (RF-018-15): la de :mod:`design.pit_ramp_def` (T04), con su nombre del plan."""

MAX_BENCHES: int = 200
"""El tope de bancos de una polilínea (RF-018-04): **un límite de validez, no una cifra minera**. Lo rechaza el cálculo con
``des.pit_too_many_benches``."""
MAX_VERTICES: int = 50_000
"""El tope de vértices de una polilínea (RF-018-04): otro límite de validez, no una cifra minera."""

_PARAM_REALS = ("top_level_m", "bottom_level_m", "min_floor_width_m", "arc_tol_m", "simplify_m", "close_radius_m", "az_window_m")
"""Los parámetros decimales de la corta que se piden (``PitRequest``) y se resuelven (``PitParams``)."""


# --- Los enumerados y los códigos de error ------------------------------------------------------------------------------


class PitMode(StrEnum):
    """El modo de una corta (RF-018-02): ``UP`` (ascendente: de uno o más fondos, cada uno a su cota, los bancos suben hacia
    fuera hasta salir al terreno) y ``DOWN`` (descendente: de uno o más límites, cuya cresta sigue al terreno o está a una cota,
    los bancos bajan hacia dentro hasta un criterio de parada). Es el texto del parámetro ``mode`` (``PitParam.MODE``)."""

    UP = "up"
    DOWN = "down"


class Corner(StrEnum):
    """La esquina del desfase (RF-018-10, D-14): ``ROUND`` (arcos circunscritos) o ``MITER`` (inglete). El texto del parámetro ``corner``."""

    ROUND = "round"
    MITER = "miter"


class PolylineKind(StrEnum):
    """El tipo de una polilínea de diseño (RF-018-11, RF-018-12; ``des_pbl_``): el ``FOOT`` (pie) o la ``CREST`` (cresta) de un banco."""

    FOOT = "foot"
    CREST = "crest"


class StopCriterion(StrEnum):
    """Lo que paró una corta (RF-018-11, RF-018-13): ``SURFACE`` (la ascendente sale a superficie), ``TOP_LEVEL`` (la ascendente llega
    a la cota de coronación), ``FLOOR_WIDTH`` (el ancho mínimo de fondo), ``BOTTOM_LEVEL`` (la cota de fondo) o ``MAX_BENCHES`` (el
    número máximo de bancos)."""

    SURFACE = "surface"
    TOP_LEVEL = "top_level"
    FLOOR_WIDTH = "floor_width"
    BOTTOM_LEVEL = "bottom_level"
    MAX_BENCHES = "max_benches"


class FindingKind(StrEnum):
    """El tipo de un hallazgo (RF-018-26): la inclinación real de un tramo de cara (``FACE_SLOPE``), la berma real menor que B
    (``BERM_WIDTH``), el ancho de fondo o de una plataforma menor que el mínimo (``FLOOR_WIDTH``), el tramo de cresta fuera del
    perímetro de actuación (``OUTSIDE_PERIMETER``) o sobre un intocable (``ON_UNTOUCHABLE``), el área que no se excava por una
    restricción (``UNEXCAVATED``), un incumplimiento de la rampa (``RAMP``) o un banco sin perfil (``NO_PROFILE``: no es un «cumple»)."""

    FACE_SLOPE = "face_slope"
    BERM_WIDTH = "berm_width"
    FLOOR_WIDTH = "floor_width"
    OUTSIDE_PERIMETER = "outside_perimeter"
    ON_UNTOUCHABLE = "on_untouchable"
    UNEXCAVATED = "unexcavated"
    RAMP = "ramp"
    NO_PROFILE = "no_profile"


FINDING_UNITS: Mapping[FindingKind, str] = {
    FindingKind.FACE_SLOPE: "°",
    FindingKind.BERM_WIDTH: "m",
    FindingKind.FLOOR_WIDTH: "m",
    FindingKind.OUTSIDE_PERIMETER: "m",
    FindingKind.ON_UNTOUCHABLE: "m",
    FindingKind.UNEXCAVATED: "m²",
    FindingKind.RAMP: "",
    FindingKind.NO_PROFILE: "",
}
"""La unidad del valor y del límite de cada tipo de hallazgo (RF-018-26: «con su unidad»); la de la rampa depende del incumplimiento
y va en el hallazgo (``Finding.unit``)."""


class PitCode(StrEnum):
    """Los códigos de lo que el cálculo o la preparación de una corta no puede dar (RF-018-04, 06, 10, 13, 14, 15, 19, 20, 23, 24):
    ``PROFILES_DIFFER`` (perfiles de distinta altura o ancla), ``NOTHING_TO_EXCAVATE`` (el fondo no queda por debajo del terreno),
    ``TOO_MANY_BENCHES`` (más de :data:`MAX_BENCHES` bancos o :data:`MAX_VERTICES` vértices), ``NOT_REACHING_SURFACE`` (no sale a
    superficie), ``FLOOR_TOO_SMALL`` (el fondo, menor que el mínimo: el aviso con que para una descendente), ``EMPTY`` (una descendente
    queda vacía antes de su primer banco, RF-018-14), ``TOO_MANY_PARTS`` (el interior de un banco se parte en más de 50 partes),
    ``FIXED_LEVEL`` y ``FIXED_CROSS`` (bancos fijados),
    ``RAMP_MEAN_OVER`` (la pendiente media de la rampa pasa de la máxima), ``RAMP_RADIUS_BELOW_MIN`` (el radio que cabe es menor
    que el mínimo), ``NO_RAMP_FIT`` (la rampa no cabe), ``NO_SEARCH`` (un sector sin la búsqueda de intocables vigente), ``HOLES``
    (el desfase tiene huecos) y ``OFFSET_UNRELIABLE`` (el desfase no se pudo verificar). Su valor es el código de
    :mod:`design.messages`."""

    PROFILES_DIFFER = "des.pit_profiles_differ"
    NOTHING_TO_EXCAVATE = "des.pit_nothing_to_excavate"
    TOO_MANY_BENCHES = "des.pit_too_many_benches"
    NOT_REACHING_SURFACE = "des.pit_not_reaching_surface"
    FLOOR_TOO_SMALL = "des.pit_floor_too_small"
    EMPTY = "des.pit_empty"
    TOO_MANY_PARTS = "des.pit_too_many_parts"
    FIXED_LEVEL = "des.pit_fixed_level"
    FIXED_CROSS = "des.pit_fixed_cross"
    RAMP_MEAN_OVER = "des.pit_ramp_mean_over"
    RAMP_RADIUS_BELOW_MIN = "des.pit_ramp_radius_below_min"
    NO_RAMP_FIT = "des.pit_no_ramp_fit"
    NO_SEARCH = "des.pit_no_search"
    HOLES = "des.pit_holes"
    OFFSET_UNRELIABLE = "des.pit_offset_unreliable"


# --- Ayudantes de validación ---------------------------------------------------------------------------------------------


def _int(value: object, what: str) -> int:
    """``value`` como ``int``; :class:`TypeError` si no es un entero (un decimal, un texto o un booleano no lo son)."""
    if isinstance(value, bool) or not isinstance(value, numbers.Integral):
        raise TypeError(f"{what} es un número entero, no {value!r}")
    return int(value)


def _ranged(value: object, key: str, what: str) -> float:
    """``value`` como ``float`` finito dentro del rango ``PIT_RANGES[key]`` (la fuente única, :mod:`design.params`)."""
    number = _real(value, f"«{key}» de {what}")
    span: ValueRange = PIT_RANGES[key]
    if not span.contains(number):
        raise ValueError(f"«{key}» de {what} = {number!r} está fuera de su rango {span.text()}")
    return number


def _n_berm(value: object, what: str) -> int:
    """El número de bancos por berma: entero dentro de su rango (≥ 1; RF-018-08)."""
    number = _int(value, f"«n_berm» de {what}")
    if not PIT_RANGES[PitParam.N_BERM.value].contains(number):
        raise ValueError(f"«n_berm» de {what} = {number!r} está fuera de su rango {PIT_RANGES[PitParam.N_BERM.value].text()}")
    return number


def _lines3(value: object, what: str, minimum: int) -> np.ndarray:
    """``value`` como un array float64 ``(k, 3)`` de solo lectura (con su Z), de al menos ``minimum`` vértices y todo finito."""
    array = np.asarray(value, dtype=np.float64)
    if array.ndim != 2 or array.shape[1] != 3 or array.shape[0] < minimum:
        raise ValueError(f"{what} es un array (k, 3) con al menos {minimum} vértices, no de forma {array.shape}")
    if not np.isfinite(array).all():
        raise ValueError(f"{what} tiene coordenadas no finitas")
    view = array.view()
    view.flags.writeable = False
    return view


def _ring2(value: object, what: str) -> np.ndarray:
    """``value`` como un anillo float64 ``(k, 2)`` de solo lectura: al menos tres vértices, todo finito, sin vértice repetido seguido
    (RF-018-04: «un vértice repetido» se rechaza, y la preparación lo dice con su capa; aquí es un error del programa)."""
    array = np.asarray(value, dtype=np.float64)
    if array.ndim != 2 or array.shape[1] != 2 or array.shape[0] < 3:
        raise ValueError(f"{what} es un anillo (k, 2) con al menos tres vértices, no de forma {array.shape}")
    if not np.isfinite(array).all():
        raise ValueError(f"{what} tiene coordenadas no finitas")
    view = array.view()
    view.flags.writeable = False
    return view


def _pairs(value: object, what: str, check: Any) -> tuple[tuple[str, Any], ...]:
    """Los pares ``(sector, valor)`` de ``value`` (un mapa o pares), por sector ordenado, con cada valor pasado por ``check``."""
    items = dict(value).items() if value else ()  # type: ignore[call-overload]
    found = []
    for sector, item in items:
        found.append((_text(sector, f"el sector de {what}"), check(item, what)))
    return tuple(sorted(found, key=lambda pair: pair[0]))


def _code_text(value: object, what: str) -> str:
    return _label(value, what)


# --- La corta: lo que se pide ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PitRequest:
    """Lo que pide el usuario de «Nueva corta…» (RF-018-01, RF-018-02; plan 018 §5.2.2 y §5.3.3; el homólogo de ``RoadRequest``): su
    ``name`` (único en la versión), la capa de origen con su campo del nombre (``fields``: los fondos o los límites), el ``mode``
    (RF-018-02), la superficie de la que parte (``start``: el nombre de su dato; por defecto, la última de la cadena y, si no, el
    terreno: RF-018-03) y el campo de cota de la capa (``level_field``: ``cota_m``: cada fondo a su cota; en el descendente, la cota
    de la cresta).

    Lo demás es opcional y, si no se pide, es ``None``: el valor por defecto del parámetro (solo ``n_berm`` y ``corner`` lo tienen)
    o, si no lo tiene, el rechazo de RF-015-08 de la preparación. ``support`` es la superficie de apoyo; ``fixed`` y ``noramp``, las
    capas de bancos fijados y de zonas sin rampa (con ``fixed_field`` por el campo del banco o de la cota); ``profile``, ``rose``
    y ``n_berm``, el perfil base, la roseta y los bancos por berma, y ``sector_profiles``, ``sector_roses`` y ``sector_n_berm``,
    los de cada sector (``(sector, valor)``, ordenados por sector: RF-018-06 a 09); ``ramps``, los códigos de rampa; los criterios de
    parada (``top_level_m``, ``bottom_level_m``, ``max_benches``, ``min_floor_width_m``: sin valor por defecto, D-8) y los del
    desfase (``corner``, ``arc_tol_m``, ``simplify_m``, ``close_radius_m``, ``az_window_m``: HIPÓTESIS sin valor, D-14, D-15, P-5).

    **No tiene** ``protect`` ni ``guard_m`` (la corta no declara restricción alguna: D-9, RF-018-01) ni lo declarado después
    (``supports``) ni el descarte: no son del diálogo de crearla. Lo leído no es parte de la petición: lo recoge el cálculo
    (:class:`PitJob`)."""

    name: str
    fields: LayerFields
    mode: PitMode | str
    start: str
    level_field: str | None = None
    support: str | None = None
    fixed: LayerFields | None = None
    fixed_field: str | None = None
    noramp: LayerFields | None = None
    profile: str | None = None
    rose: str | None = None
    n_berm: int | None = None
    sector_profiles: Mapping[str, str] | tuple[tuple[str, str], ...] = ()
    sector_roses: Mapping[str, str] | tuple[tuple[str, str], ...] = ()
    sector_n_berm: Mapping[str, int] | tuple[tuple[str, int], ...] = ()
    ramps: tuple[str, ...] = ()
    top_level_m: float | None = None
    bottom_level_m: float | None = None
    max_benches: int | None = None
    min_floor_width_m: float | None = None
    corner: Corner | str | None = None
    arc_tol_m: float | None = None
    simplify_m: float | None = None
    close_radius_m: float | None = None
    az_window_m: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _named(self.name, "el nombre de una corta", "Corta"))
        if not isinstance(self.fields, LayerFields):
            raise TypeError(f"la capa de una corta es LayerFields, no {self.fields!r}")
        object.__setattr__(self, "mode", PitMode(self.mode))
        object.__setattr__(self, "start", _text(self.start, "«start» de una corta"))
        for attr in ("level_field", "support", "profile", "rose", "fixed_field"):
            object.__setattr__(self, attr, _name_or_none(getattr(self, attr), f"«{attr}» de una corta"))
        for attr in ("fixed", "noramp"):
            found = getattr(self, attr)
            if found is not None and not isinstance(found, LayerFields):
                raise TypeError(f"la capa «{attr}» de una corta es LayerFields, no {found!r}")
        object.__setattr__(self, "n_berm", None if self.n_berm is None else _n_berm(self.n_berm, "una corta"))
        object.__setattr__(self, "sector_profiles", _pairs(self.sector_profiles, "los perfiles por sector de una corta", _code_text))
        object.__setattr__(self, "sector_roses", _pairs(self.sector_roses, "las rosetas por sector de una corta", _code_text))
        object.__setattr__(self, "sector_n_berm", _pairs(self.sector_n_berm, "los bancos por berma por sector de una corta", _n_berm))
        if isinstance(self.ramps, str):
            raise TypeError(f"las rampas de una corta son una lista de códigos, no {self.ramps!r}")
        object.__setattr__(self, "ramps", tuple(_label(code, "el código de una rampa") for code in self.ramps))
        for attr in ("top_level_m", "bottom_level_m", "min_floor_width_m", "arc_tol_m", "simplify_m", "close_radius_m", "az_window_m"):
            object.__setattr__(self, attr, _real_or_none(getattr(self, attr), f"«{attr}» de una corta"))
        object.__setattr__(self, "max_benches", _int_or_none(self.max_benches, "«max_benches» de una corta"))
        if self.corner is not None:
            object.__setattr__(self, "corner", Corner(self.corner))

    @property
    def layer(self) -> str:
        """La capa de origen de la corta."""
        return self.fields.layer


@dataclass(frozen=True, slots=True)
class PitParams:
    """Los valores de desfase y de parada de una corta, **ya resueltos** (RF-018-10, 11, 13, 14; plan 018 §5.2.2): ``arc_tol_m`` y
    ``simplify_m`` (m; HIPÓTESIS, D-14: **se piden**, sin valor por defecto), ``corner`` (``round`` por defecto: ADOPTADO «sin
    confirmar»), ``n_berm`` (1 por defecto) y los opcionales —``top_level_m``, ``bottom_level_m``, ``max_benches``,
    ``min_floor_width_m``, ``close_radius_m`` (0 o ``None``: sin cierre) y ``az_window_m`` (``None`` donde no hay roseta)—. Cada uno
    ha de estar en su rango (:data:`~design.params.PIT_RANGES`, la fuente única: ``ValueError`` si no; ``TypeError`` si no es un
    número real, o un entero ``n_berm`` y ``max_benches``)."""

    arc_tol_m: float
    simplify_m: float
    corner: Corner | str = Corner.ROUND
    n_berm: int = 1
    top_level_m: float | None = None
    bottom_level_m: float | None = None
    max_benches: int | None = None
    min_floor_width_m: float | None = None
    close_radius_m: float | None = None
    az_window_m: float | None = None

    def __post_init__(self) -> None:
        what = "los parámetros de la corta"
        for attr in ("arc_tol_m", "simplify_m"):
            object.__setattr__(self, attr, _ranged(getattr(self, attr), attr, what))
        for attr in ("top_level_m", "bottom_level_m", "min_floor_width_m", "close_radius_m", "az_window_m"):
            found = getattr(self, attr)
            if found is not None:
                object.__setattr__(self, attr, _ranged(found, attr, what))
        object.__setattr__(self, "corner", Corner(self.corner))
        object.__setattr__(self, "n_berm", _n_berm(self.n_berm, what))
        if self.max_benches is not None:
            number = _int(self.max_benches, f"«max_benches» de {what}")
            if not PIT_RANGES[PitParam.MAX_BENCHES.value].contains(number):
                raise ValueError(f"«max_benches» de {what} = {number!r} está fuera de su rango "
                                 f"{PIT_RANGES[PitParam.MAX_BENCHES.value].text()}")
            object.__setattr__(self, "max_benches", number)
        if (self.top_level_m is not None and self.bottom_level_m is not None
                and not self.bottom_level_m < self.top_level_m):
            raise ValueError(f"la cota de fondo {self.bottom_level_m!r} de {what} no está por debajo de la de coronación {self.top_level_m!r}")

    @classmethod
    def from_values(cls, values: Mapping[str, object]) -> PitParams:
        """Los parámetros de ``values``: los valores resueltos de la corta por su último segmento (``PitParam``; los demás —la capa, el
        modo…— no son suyos y se ignoran). Sin ``corner`` ni ``n_berm`` toman su valor por defecto. :class:`ValueError` si falta
        ``arc_tol_m`` o ``simplify_m``: es un error del programa, porque la preparación ya lo rechazó (RF-015-08) sin elegir uno
        por la persona."""
        missing = [attr for attr in ("arc_tol_m", "simplify_m") if values.get(attr) is None]
        if missing:
            raise ValueError(f"faltan parámetros de la corta ({', '.join(missing)}): la preparación los rechaza antes "
                             "(RF-015-08) y no se elige ninguno por la persona")
        found: dict[str, Any] = {attr: values.get(attr) for attr in (*_PARAM_REALS, "max_benches")}
        corner, n_berm = values.get("corner"), values.get("n_berm")
        if corner is not None:
            found["corner"] = corner
        if n_berm is not None:
            found["n_berm"] = n_berm
        return cls(**found)


# --- La corta: lo que se lee --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class PitSource:
    """Un polígono de origen de la corta, ya leído de su capa (RF-018-01, RF-018-02; absolutas, float64): su ``name``, su ``ring`` (un
    anillo ``(k, 2)`` sin repetir el primer vértice, de solo lectura; **sin huecos**: P-13) y su cota ``level_m`` (m: el fondo de la
    ascendente, que la lleva siempre, o la cota de la cresta de la descendente, opcional)."""

    name: str
    ring: np.ndarray
    level_m: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _label(self.name, "el nombre de un polígono de la corta"))
        object.__setattr__(self, "ring", _ring2(self.ring, f"el polígono «{self.name}» de la corta"))
        if self.level_m is not None:
            object.__setattr__(self, "level_m", _real(self.level_m, f"la cota del polígono «{self.name}»"))


@dataclass(frozen=True, slots=True, eq=False)
class PitSector:
    """Un sector de diseño que la corta toca, con lo que le corresponde (ADR-0029; RF-018-06 a 09): su ``code`` (``""``: el
    perímetro), su ``name``, sus ``parts`` (los anillos de cada parte, absolutos, de solo lectura) y su perfil de banco, su roseta y
    sus bancos por berma si los tiene propios (``None``: los de la corta)."""

    code: str
    name: str
    parts: Parts
    profile: BenchProfile | None = None
    rose: tuple[RoseRange, ...] | None = None
    n_berm: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _text(self.code, "el código de un sector de la corta"))
        object.__setattr__(self, "name", _text(self.name, "el nombre de un sector de la corta"))
        object.__setattr__(self, "parts", _parts(self.parts, f"el sector «{self.code}» de la corta"))
        if self.profile is not None and not isinstance(self.profile, BenchProfile):
            raise TypeError(f"el perfil de un sector es BenchProfile, no {self.profile!r}")
        if self.rose is not None:
            object.__setattr__(self, "rose", _tuple_of(self.rose, RoseRange, "la roseta de un sector"))
        if self.n_berm is not None:
            object.__setattr__(self, "n_berm", _n_berm(self.n_berm, f"el sector «{self.code}»"))


@dataclass(frozen=True, slots=True, eq=False)
class FixedBench:
    """Un banco fijado por el usuario (RF-018-23, RF-018-24; absolutas, float64): su ``name``, sus ``vertices`` ``(k, 3)`` con la Z
    (de solo lectura; una línea o un polígono ``closed``) y su ``bench`` (el número) o su ``level_m`` (la cota): al menos uno. La
    línea del usuario **no se modifica**: es el pie o la cresta de ese banco tal cual."""

    name: str
    vertices: np.ndarray
    bench: int | None = None
    level_m: float | None = None
    closed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _label(self.name, "el nombre de un banco fijado"))
        object.__setattr__(self, "closed", _flag(self.closed, "«closed» de un banco fijado"))
        object.__setattr__(self, "vertices",
                           _lines3(self.vertices, f"el banco fijado «{self.name}»", 3 if self.closed else 2))
        if self.bench is not None:
            object.__setattr__(self, "bench", _int(self.bench, "«bench» de un banco fijado"))
        if self.level_m is not None:
            object.__setattr__(self, "level_m", _real(self.level_m, f"la cota del banco fijado «{self.name}»"))
        if self.bench is None and self.level_m is None:
            raise ValueError(f"el banco fijado «{self.name}» lleva su banco o su cota (RF-018-23)")


@dataclass(frozen=True, slots=True, eq=False)
class RampStart:
    """El punto de inicio de una rampa de la corta ya resuelto (RF-018-15; T21b): el ``ramp`` (su código) y **o** el ``point`` ``(x, y)`` absoluto de una
    capa de puntos (``layer`` y ``name``: de dónde salió) **o** el ``bench`` sobre cuya polilínea parte (``fondo`` es el banco 0; la rampa lo sitúa
    cuando tiene la polilínea: T21c). Uno solo de los dos."""

    ramp: str
    point: tuple[float, float] | None = None
    bench: int | None = None
    layer: str = ""
    name: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "ramp", _label(self.ramp, "el código de una rampa"))
        if (self.point is None) == (self.bench is None):
            raise ValueError(f"el inicio de la rampa «{self.ramp}» es un punto o un banco, no los dos ni ninguno")
        if self.point is not None:
            x, y = self.point
            object.__setattr__(self, "point", (_real(x, "la x del inicio de una rampa"), _real(y, "la y del inicio de una rampa")))
        if self.bench is not None:
            object.__setattr__(self, "bench", _int(self.bench, "el banco del inicio de una rampa"))
        object.__setattr__(self, "layer", _text(self.layer, "la capa del inicio de una rampa"))
        object.__setattr__(self, "name", _text(self.name, "el nombre del inicio de una rampa"))


@dataclass(frozen=True, slots=True, eq=False)
class PitJob:
    """Lo que necesita calcular una corta, ya leído y **sin nada del proyecto** (plan 018 §5.3.1; lo que ``RoadJob`` a la 017): la
    ``request`` (su nombre y su capa), el ``code`` de la entidad (``PIT-001``), la rejilla (``grid``), la superficie de partida
    ``start`` (m, float64; ``NaN``, sin dato), las máscaras de la versión como arrays booleanos de la rejilla entera (``cut_allowed``,
    ``fill_allowed`` y ``untouchable``: RF-018-05), los polígonos de origen (``sources``, uno al menos), el perfil base
    (``profile``: ``None`` si todo sector lleva el suyo), los sectores (``sectors``), la roseta base (``rose``), las rampas
    (``ramps``, con los perfiles de pista que usan: ``road_profiles``), los bancos fijados (``fixed``), las zonas sin rampa
    (``noramp``: partes de polígonos), el perímetro de actuación (``perimeter``) y el límite legal (``legal``: partes de polígonos o
    ``None``; los pide la línea de cielo, RF-018-29) y los parámetros (``params``: :class:`PitParams`). ``ramp_starts``: el inicio de cada rampa
    ya resuelto (T21b: el punto de su capa o el banco).

    **No lleva** ruta de fichero, conexión, proyecto ni versión: se calcula sin proyecto y se reproduce con el mismo resultado.
    Los arrays son de la **rejilla entera** y vistas de solo lectura. :class:`TypeError` o :class:`ValueError` (errores del programa:
    la preparación rechazó antes, con su capa, su corta, su campo y su valor) si un tipo no es el suyo, el código no es el de una
    corta, un array no es de la forma de la rejilla, no hay perfil para algún sector, los perfiles son de distinta altura o ancla
    (RF-018-06), un nombre o un código se repite, una rampa cita un perfil de pista que falta o falta la cota de un fondo en el
    modo ascendente (RF-018-02)."""

    request: PitRequest
    code: str
    grid: Grid
    start: np.ndarray
    cut_allowed: np.ndarray
    fill_allowed: np.ndarray
    untouchable: np.ndarray
    sources: tuple[PitSource, ...]
    params: PitParams
    profile: BenchProfile | None = None
    sectors: tuple[PitSector, ...] = ()
    rose: tuple[RoseRange, ...] | None = None
    ramps: tuple[RampDef, ...] = ()
    road_profiles: tuple[RoadProfile, ...] = ()
    fixed: tuple[FixedBench, ...] = ()
    noramp: Parts | None = None
    perimeter: Parts | None = None
    legal: Parts | None = None
    ramp_starts: tuple[RampStart, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.request, PitRequest):
            raise TypeError(f"la petición de una corta es PitRequest, no {self.request!r}")
        if entity_params_of(self.code).kind != "pit":  # type: ignore[arg-type]
            raise ValueError(f"el código {self.code!r} no es el de una corta")
        if not isinstance(self.grid, Grid):
            raise TypeError(f"la rejilla de una corta es Grid, no {self.grid!r}")
        if not isinstance(self.params, PitParams):
            raise TypeError(f"los parámetros de una corta son PitParams, no {self.params!r}")
        shape = self.grid.shape
        object.__setattr__(self, "start", _readonly(self.start, shape, np.float64, "la superficie de partida"))
        for attr in ("cut_allowed", "fill_allowed", "untouchable"):
            object.__setattr__(self, attr, _readonly(getattr(self, attr), shape, np.bool_, f"la máscara «{attr}»"))
        object.__setattr__(self, "sources", _tuple_of(self.sources, PitSource, "los polígonos de una corta"))
        if not self.sources:
            raise ValueError("una corta parte de uno o más polígonos de origen (RF-018-02)")
        if self.request.mode is PitMode.UP and any(item.level_m is None for item in self.sources):
            raise ValueError("cada fondo de una corta ascendente lleva su cota (RF-018-02)")
        _unique([item.name for item in self.sources], "el nombre de un polígono de la corta")
        if self.profile is not None and not isinstance(self.profile, BenchProfile):
            raise TypeError(f"el perfil base de una corta es BenchProfile, no {self.profile!r}")
        object.__setattr__(self, "sectors", _tuple_of(self.sectors, PitSector, "los sectores de una corta"))
        _unique([item.code for item in self.sectors], "el código de un sector de la corta")
        if self.rose is not None:
            object.__setattr__(self, "rose", _tuple_of(self.rose, RoseRange, "la roseta de una corta"))
        object.__setattr__(self, "ramps", _tuple_of(self.ramps, PitRampDef, "las rampas de una corta"))
        _unique([item.code for item in self.ramps], "el código de una rampa de la corta")
        object.__setattr__(self, "road_profiles", _tuple_of(self.road_profiles, RoadProfile, "los perfiles de pista de una corta"))
        known = {item.code for item in self.road_profiles}
        for ramp in self.ramps:
            if ramp.road_profile not in known:
                raise ValueError(f"la rampa «{ramp.code}» cita el perfil de pista «{ramp.road_profile}», que la corta no lleva")
        object.__setattr__(self, "ramp_starts", _tuple_of(self.ramp_starts, RampStart, "los inicios de las rampas de una corta"))
        codes = {item.code for item in self.ramps}
        for item in self.ramp_starts:
            if item.ramp not in codes:
                raise ValueError(f"el inicio de la rampa «{item.ramp}» es de una rampa que la corta no lleva")
        object.__setattr__(self, "fixed", _tuple_of(self.fixed, FixedBench, "los bancos fijados de una corta"))
        for attr in ("noramp", "perimeter", "legal"):
            found = getattr(self, attr)
            if found is not None:
                object.__setattr__(self, attr, _parts(found, f"«{attr}» de una corta"))
        self._check_profiles()

    def _check_profiles(self) -> None:
        profiles = self.bench_profiles
        if not profiles:
            raise ValueError("una corta lleva un perfil de banco, el base o el de cada sector (RF-018-06)")
        if self.profile is None and any(item.profile is None for item in self.sectors):
            raise ValueError("sin perfil base, cada sector de la corta lleva el suyo (RF-018-06)")
        first = profiles[0]
        for other in profiles[1:]:
            if other.height_m != first.height_m or other.anchor_m != first.anchor_m:
                raise ValueError(f"los perfiles «{first.code}» y «{other.code}» tienen distinta altura o ancla (RF-018-06, "
                                 f"{PitCode.PROFILES_DIFFER.value})")

    @property
    def mode(self) -> PitMode:
        """El modo de la corta."""
        return self.request.mode  # type: ignore[return-value]

    @property
    def bench_profiles(self) -> tuple[BenchProfile, ...]:
        """Los perfiles de banco distintos de la corta, el base primero y luego los de los sectores, en su orden."""
        found: list[BenchProfile] = [] if self.profile is None else [self.profile]
        for sector in self.sectors:
            if sector.profile is not None and sector.profile not in found:
                found.append(sector.profile)
        return tuple(found)

    @property
    def height_m(self) -> float:
        """La altura de banco ``h`` (m): la de todos los perfiles (RF-018-06)."""
        return self.bench_profiles[0].height_m

    @property
    def anchor_m(self) -> float:
        """La cota de ancla ``z₀`` (m): la de todos los perfiles (RF-018-06)."""
        return self.bench_profiles[0].anchor_m


def _unique(items: Iterable[str], what: str) -> None:
    seen: set[str] = set()
    for item in items:
        if item in seen:
            raise ValueError(f"{what} se repite: {item!r}")
        seen.add(item)


# --- La corta: el resultado -----------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class Polyline:
    """Una polilínea de diseño de una corta (RF-018-11, RF-018-12, RF-018-25; ``des_pbl_``): su ``kind`` (pie o cresta), su ``bench``
    (el número del banco), su ``zone`` (``""`` si no es de una zona de rampa), su ``sector`` (``""``: el perímetro) y sus
    ``vertices`` ``(k, 3)`` con la Z (absolutas, float64, de solo lectura; ``closed``: un anillo sin repetir el primer vértice).
    ``part`` numera las partes de un mismo banco en que se divide el interior (D-7); ``fixed`` dice que es una línea del
    usuario, tal cual (RF-018-23). El **orden** de las polilíneas en su lista y el de los vértices son los registrados (RF-018-25)."""

    kind: PolylineKind | str
    bench: int
    vertices: np.ndarray
    zone: str = ""
    sector: str = ""
    closed: bool = True
    part: int = 0
    fixed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", PolylineKind(self.kind))
        object.__setattr__(self, "bench", _int(self.bench, "el banco de una polilínea"))
        object.__setattr__(self, "part", _int(self.part, "la parte de una polilínea"))
        if self.part < 0:
            raise ValueError(f"la parte de una polilínea es un número de 0 o más, no {self.part!r}")
        object.__setattr__(self, "zone", _text(self.zone, "la zona de una polilínea"))
        object.__setattr__(self, "sector", _text(self.sector, "el sector de una polilínea"))
        object.__setattr__(self, "closed", _flag(self.closed, "«closed» de una polilínea"))
        object.__setattr__(self, "fixed", _flag(self.fixed, "«fixed» de una polilínea"))
        object.__setattr__(self, "vertices", _lines3(self.vertices, "una polilínea", 3 if self.closed else 2))

    @property
    def z_m(self) -> float:
        """La cota de la polilínea (m): la Z de su primer vértice (una polilínea de banco es plana)."""
        return float(self.vertices[0, 2])

    @property
    def length_m(self) -> float:
        """La longitud en planta (m), con el cierre si es un anillo."""
        xy = self.vertices[:, :2]
        if self.closed:
            xy = np.vstack([xy, xy[:1]])
        return float(np.hypot(*np.diff(xy, axis=0).T).sum())


@dataclass(frozen=True, slots=True, eq=False)
class RampPath:
    """El eje y la banda de una rampa (RF-018-16, RF-018-17; ``des_prl_``): el ``code`` de su definición, el ``bench`` en que
    empieza (el de arriba) y su ``axis`` ``(k, 3)`` con la Z (por estaciones, absolutas, de solo lectura), con el semiancho de la banda
    en cada estación (``half_width_m``, m, ``(k,)``)."""

    code: str
    bench: int
    axis: np.ndarray
    half_width_m: np.ndarray

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _label(self.code, "el código de una rampa"))
        object.__setattr__(self, "bench", _int(self.bench, "el banco de una rampa"))
        axis = _lines3(self.axis, "el eje de una rampa", 2)
        object.__setattr__(self, "axis", axis)
        object.__setattr__(self, "half_width_m", _readonly(self.half_width_m, (axis.shape[0],), np.float64, "el semiancho de la banda"))
        if not bool((self.half_width_m >= 0.0).all()):
            raise ValueError("el semiancho de la banda de una rampa no es negativo")

    @property
    def length_m(self) -> float:
        """La longitud del eje en planta (m)."""
        return float(np.hypot(*np.diff(self.axis[:, :2], axis=0).T).sum())

    @property
    def gradient_mean_pct(self) -> float:
        """La pendiente media del eje (%): el desnivel entre sus extremos sobre su longitud en planta; 0 si no hay longitud."""
        length = self.length_m
        return 0.0 if length <= 0.0 else abs(float(self.axis[-1, 2] - self.axis[0, 2])) / length * 100.0

    @property
    def gradient_max_pct(self) -> float:
        """La mayor pendiente de un tramo del eje (%)."""
        run = np.hypot(*np.diff(self.axis[:, :2], axis=0).T)
        rise = np.abs(np.diff(self.axis[:, 2]))
        moving = run > 0.0
        return float((rise[moving] / run[moving]).max() * 100.0) if bool(moving.any()) else 0.0


@dataclass(frozen=True, slots=True)
class BenchFigures:
    """Las cifras de un banco (RF-018-29, RF-018-31; ``des_pbk_``): su ``bench``, la cota de su pie (``z_foot_m``) y de su cresta
    (``z_crest_m``), las longitudes de pie y de cresta (``len_foot_m``, ``len_crest_m``, m), el área de la berma y del fondo
    (``area_berm_m2``, ``area_floor_m2``, m²; ``None`` donde no tiene) y el volumen que se corta en él (``cut_m3``, m³). Todo
    CALCULADO por el cálculo; aquí solo tipos y números finitos."""

    bench: int
    z_foot_m: float
    z_crest_m: float
    len_foot_m: float
    len_crest_m: float
    cut_m3: float
    area_berm_m2: float | None = None
    area_floor_m2: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "bench", _int(self.bench, "el banco de unas cifras"))
        for attr in ("z_foot_m", "z_crest_m", "len_foot_m", "len_crest_m", "cut_m3"):
            object.__setattr__(self, attr, _real(getattr(self, attr), f"«{attr}» de las cifras de un banco"))
        for attr in ("area_berm_m2", "area_floor_m2"):
            found = _real_or_none(getattr(self, attr), f"«{attr}» de las cifras de un banco")
            if found is not None and not math.isfinite(found):
                raise ValueError(f"«{attr}» de las cifras de un banco no es finito")
            object.__setattr__(self, attr, found)


@dataclass(frozen=True, slots=True)
class Finding:
    """Un hallazgo de la corta (RF-018-26; ``des_pfn_``): su ``kind``, el ``bench`` (``None`` si no es de uno), el ``value`` y el
    ``limit`` que no cumple (con su ``unit``: la de :data:`FINDING_UNITS` si no se da) y su lugar (``place``: ``(x, y)`` absoluto) y
    un ``detail`` de texto libre (la rampa que no cabe, el sector…). Un banco sin perfil es un hallazgo, no un «cumple»."""

    kind: FindingKind | str
    value: float | None
    limit: float | None
    place: Point
    bench: int | None = None
    unit: str | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        kind = FindingKind(self.kind)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "value", _real_or_none(self.value, "el valor de un hallazgo"))
        object.__setattr__(self, "limit", _real_or_none(self.limit, "el límite de un hallazgo"))
        x, y = self.place
        object.__setattr__(self, "place", (_real(x, "la x del lugar de un hallazgo"), _real(y, "la y del lugar de un hallazgo")))
        if self.bench is not None:
            object.__setattr__(self, "bench", _int(self.bench, "el banco de un hallazgo"))
        object.__setattr__(self, "unit", FINDING_UNITS[kind] if self.unit is None else _text(self.unit, "la unidad de un hallazgo"))
        object.__setattr__(self, "detail", _text(self.detail, "el detalle de un hallazgo"))


@dataclass(frozen=True, slots=True, eq=False)
class PitOutcome:
    """El cálculo de una corta (RF-018-01, RF-018-26, RF-018-29, RF-018-31; plan 018 §5.3.1): su ``name``, el ``code`` de la entidad,
    el ``mode``, la ventana de trabajo de la rejilla (``window``), la superficie resultante (``surface``, m, float64) y la huella
    (``footprint``: booleana, el área con movimiento) en esa ventana, las ``figures`` de RF-018-31 (CALCULADO, con su unidad y su
    ámbito: ``provenance.pit_figures``) y los ``notices`` en orden estable. Los arrays son de la forma de la ventana y de solo lectura.

    Lo demás es del cálculo (opcional, vacío si no hay): las ``polylines`` de diseño en su orden registrado (RF-018-25), los ``ramps``
    (ejes y bandas), la línea de cielo (``skyline``: líneas ``(k, 3)`` con la Z del terreno), las cifras de cada banco
    (``benches``), los ``findings`` (RF-018-26), el criterio que paró (``stop``) y los nombres de los otros diseños de la versión
    cuya superficie difiere de la de partida en la huella (``other_designs``: la T21 los registra como entradas)."""

    name: str
    code: str
    mode: PitMode | str
    window: Window
    surface: np.ndarray
    footprint: np.ndarray
    figures: tuple[FigureSpec, ...] = ()
    notices: tuple[Notice, ...] = ()
    polylines: tuple[Polyline, ...] = ()
    ramps: tuple[RampPath, ...] = ()
    skyline: tuple[np.ndarray, ...] = ()
    benches: tuple[BenchFigures, ...] = ()
    findings: tuple[Finding, ...] = ()
    stop: StopCriterion | str | None = None
    other_designs: tuple[str, ...] = ()
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _label(self.name, "el nombre de una corta"))
        if entity_params_of(self.code).kind != "pit":  # type: ignore[arg-type]
            raise ValueError(f"el código {self.code!r} no es el de una corta")
        object.__setattr__(self, "mode", PitMode(self.mode))
        window = _window(self.window)
        object.__setattr__(self, "window", window)
        shape = (window[0].stop - window[0].start, window[1].stop - window[1].start)
        object.__setattr__(self, "surface", _readonly(self.surface, shape, np.float64, "la superficie resultante"))
        object.__setattr__(self, "footprint", _readonly(self.footprint, shape, np.bool_, "la huella de la corta"))
        object.__setattr__(self, "figures", _tuple_of(self.figures, FigureSpec, "las cifras de una corta"))
        object.__setattr__(self, "notices", _tuple_of(self.notices, Notice, "los avisos de una corta"))
        object.__setattr__(self, "polylines", _tuple_of(self.polylines, Polyline, "las polilíneas de una corta"))
        object.__setattr__(self, "ramps", _tuple_of(self.ramps, RampPath, "las rampas de una corta"))
        object.__setattr__(self, "skyline", tuple(_lines3(line, "una línea de cielo", 2) for line in self.skyline))
        object.__setattr__(self, "benches", _tuple_of(self.benches, BenchFigures, "las cifras por banco de una corta"))
        object.__setattr__(self, "findings", _tuple_of(self.findings, Finding, "los hallazgos de una corta"))
        if self.stop is not None:
            object.__setattr__(self, "stop", StopCriterion(self.stop))
        names = tuple(_label(name, "el nombre de otro diseño") for name in self.other_designs)
        object.__setattr__(self, "other_designs", names)

    @property
    def message(self) -> str:
        """El mensaje de la operación: la corta, su código, los bancos y el volumen que corta, en español. Es lo que recibe
        ``DesignWriter.commit`` al crearla (``Calculation.message``)."""
        found = {figure.key: figure.value for figure in self.figures}
        head = f"Corta «{self.name}» ({self.code}) calculada"
        if "des.pit_benches" not in found:
            return head
        text = f"{head}: {format_value(int(found['des.pit_benches'] or 0))} bancos"
        if found.get("des.pit_cut_m3") is not None:
            text += f" y {format_value(round(float(found['des.pit_cut_m3'] or 0.0), 2))} m³ de desmonte"
        return text

    def compose(self, start: np.ndarray) -> np.ndarray:
        """La superficie entera que deja la corta: una rejilla **nueva** igual a ``start`` con la ventana de trabajo sustituida por
        :attr:`surface`. ``ValueError`` si ``start`` no es una rejilla que contenga la ventana."""
        whole = np.array(start, dtype=np.float64, copy=True)
        rows, cols = self.window
        if whole.ndim != 2 or rows.stop > whole.shape[0] or cols.stop > whole.shape[1]:
            raise ValueError(f"la superficie de partida {whole.shape} no contiene la ventana de la corta ({rows}, {cols})")
        whole[rows, cols] = self.surface
        return whole

# SPDX-License-Identifier: GPL-3.0-or-later
"""El modelo de las envolventes y el escalonado (spec 013; plan 013 §5.1 y §5.3.1; RF-013-01,
RF-013-11, RF-013-13, RF-013-18 a RF-013-21).

Opciones y peticiones del dominio, todas inmutables (``frozen``) y comparables por valor, sin
ninguna cifra minera por defecto (D-7). Python puro; las comprobaciones de fondo de cada petición
(pendiente fuera de rango, exacta con sectores, semillas o dominio vacíos, rejilla distinta…) son
de las funciones que calculan, que las hacen antes de registrar nada (RF-013-16).

- Opciones: :class:`Direction` (``DOWN``: ``E↓(p) = máx_q [s(q) − d(p,q)·t]``, la menor que no queda
  por debajo de las semillas; ``UP``: ``E↑(p) = mín_q [s(q) + d(p,q)·t]``, la mayor que no queda por
  encima), :class:`Metric` (solo el *chamfer* 5×5 y la euclídea exacta: nunca el 3×3, ADR-0014),
  :class:`SlopeMode` (una constante o el talud general de cada sector, D-6) y :class:`BenchSense`
  (corte o relleno).
- Las semillas (RF-013-01): :class:`SeedSource` con su origen (:class:`SeedKind`) y su zona
  (:class:`Zone`, de :class:`ZoneKind`); y el acotado del dominio de trabajo (RF-013-02):
  :class:`WorkDomain`.
- Las peticiones: :class:`EnvelopeRequest` y :class:`DesignRequest`.
- El perfil de banco (RF-013-18 a RF-013-20): :class:`BenchProfile`, con su avance
  ``a = h/tan α + B`` y su talud general ``atan(h/a)`` derivados (no son parámetros) y la marca
  «no resuelto por la rejilla»; :func:`check_profiles`.
- :data:`PERIMETER_SEGMENT`: el código del perímetro de actuación como sector único (ADR-0029).

Y los de la cantera con dos superficies (spec 014, T02; plan 014 §5.1 y §5.3.1; RF-014-11 a
RF-014-18): :class:`Surface`, :class:`Order` («final primero» por defecto, D-4),
:class:`AnchorMode` (fija, en rejilla o «al fondo de cada muro»), :class:`CellClass` (sin
diferencia, desdoblado o relleno, con su código del GeoTIFF), :class:`ToFinalMode` (P-2), las
capas con sus campos (:class:`LayerField`, :class:`CorridorFields`), lo de cada superficie
(:class:`QuarrySide`) y la petición (:class:`QuarryRequest`); la de «Solo relleno…» (T30,
:class:`FillOnlyRequest`) y la de «Ajustar el diseño a un límite nuevo…» (T32,
:class:`RefitRequest`).

Y los de las entidades de diseño de la 015 (T02; plan 015 §5.1 y §5.3.1): el modo de una plataforma
(:class:`PlatformMode`, «en corte» por defecto, D-5), su eje (:class:`Axis`: vértices absolutos en
``float64`` con la abscisa 0 en el primero), la capa con sus campos (:class:`PlatformFields`) y la
petición (:class:`PlatformRequest`, el homólogo de :class:`QuarryRequest`). El registro de una
entidad y su código son de :mod:`design.entities`.
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

from .messages import DesignError, render
from .params import BenchParam, check_bench_value, is_code

if TYPE_CHECKING:
    from ..gis.grid import Grid

__all__ = [
    "DECLARED_PREFIX",
    "PERIMETER_SEGMENT",
    "AnchorMode",
    "Axis",
    "BenchProfile",
    "BenchSense",
    "CellClass",
    "CorridorFields",
    "DesignRequest",
    "Direction",
    "EnvelopeRequest",
    "FillOnlyRequest",
    "LayerField",
    "Metric",
    "Named",
    "Order",
    "PlatformFields",
    "PlatformMode",
    "PlatformRequest",
    "QuarryRequest",
    "QuarrySide",
    "RefitRequest",
    "SeedKind",
    "SeedSource",
    "SlopeMode",
    "Surface",
    "ToFinalMode",
    "WorkDomain",
    "Zone",
    "ZoneKind",
    "check_profiles",
]

PERIMETER_SEGMENT = "perimeter__"
"""El código del perímetro de actuación como sector único, en la clave de un parámetro por sector
(``des.sector.perimeter__.max_general_slope_deg``; ADR-0029, D-23)."""
DECLARED_PREFIX = "DEC-"
"""El principio del código de una restricción que declara una entidad (``DEC-PLT-001``; RF-015-10,
plan 015 §5.4 A8): el resto es el código de la entidad. La tabla de las declaradas es de la T16
(``core.constraints.declared``, que tiene el mismo prefijo); el resumen de «Calcular» (T12) lo usa para
decir qué entidad impide mover unas celdas."""


class Direction(StrEnum):
    """La dirección de una envolvente (RF-013-11): ``DOWN`` baja al alejarse de las semillas
    (``E↓ = máx_q [s − d·t]``) y ``UP`` sube (``E↑ = mín_q [s + d·t]``)."""

    DOWN = "down"
    UP = "up"


class Metric(StrEnum):
    """La métrica de la distancia (RF-013-12; ADR-0014): el *chamfer* 5×5 o la euclídea exacta.
    Nunca el *chamfer* 3×3."""

    CHAMFER5 = "chamfer5"
    EXACT = "exact"


class SlopeMode(StrEnum):
    """De dónde sale la pendiente de una envolvente (RF-013-13, D-6): una constante o el talud
    general de cada sector (el máximo impuesto o, si no lo tiene, el del perfil asignado)."""

    CONSTANT = "constant"
    SECTORS = "sectors"


class BenchSense(StrEnum):
    """El sentido del escalonado (RF-013-22, RF-013-23): en corte, cara primero; en relleno,
    berma primero."""

    CUT = "cut"
    FILL = "fill"


class ZoneKind(StrEnum):
    """Qué es la zona de unas semillas o de un acotado (RF-013-01): el dominio por defecto de
    las máscaras, la zona de una restricción, un sector o una capa de polígonos del proyecto."""

    DOMAIN = "domain"
    CONSTRAINT = "constraint"
    SECTOR = "sector"
    LAYER = "layer"


class SeedKind(StrEnum):
    """De dónde salen las semillas (RF-013-01): las celdas de una superficie dentro de una zona,
    una cota fija en las celdas de una zona o una rejilla de cotas de la versión."""

    SURFACE = "surface"
    FIXED = "fixed"
    GRID = "grid"


@dataclass(frozen=True, slots=True)
class Zone:
    """Una zona de celdas por su centro (D-16): ``kind`` y, salvo el dominio por defecto, el
    ``name`` (el código de la restricción o del sector, o el nombre de la capa)."""

    kind: ZoneKind | str
    name: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", ZoneKind(self.kind))


@dataclass(frozen=True, slots=True)
class SeedSource:
    """Las semillas de un cálculo (RF-013-01). Con ``SURFACE``: ``surface`` (su nombre, del
    proyecto o de la versión activa) y ``zone``; con ``FIXED``: ``elevation_m`` (m) en las celdas
    de ``zone``; con ``GRID``: ``grid``, el nombre de una rejilla de cotas de la versión."""

    kind: SeedKind | str
    surface: str | None = None
    zone: Zone | None = None
    elevation_m: float | None = None
    grid: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", SeedKind(self.kind))
        if self.elevation_m is not None:
            object.__setattr__(self, "elevation_m", float(self.elevation_m))


@dataclass(frozen=True, slots=True)
class WorkDomain:
    """Cómo se acota el dominio de trabajo (RF-013-02): el entero de las máscaras de la versión
    (sin ``sectors`` ni ``layer``), unos ``sectors`` (sus códigos) o una ``layer`` de polígonos
    del proyecto. Nunca se amplía: solo se acota."""

    sectors: tuple[str, ...] = ()
    layer: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.sectors, str | bytes):
            raise TypeError(f"los sectores son una lista de códigos, no {self.sectors!r}")
        object.__setattr__(self, "sectors", tuple(self.sectors))

    @property
    def bounded(self) -> bool:
        """Si el dominio se acota a unos sectores o a una capa."""
        return bool(self.sectors) or self.layer is not None


@dataclass(frozen=True, slots=True)
class EnvelopeRequest:
    """Lo que pide el usuario de una envolvente (RF-013-11 a RF-013-14, RF-013-17): su ``name``
    (único en la versión), la ``direction``, las ``seeds``, la ``metric`` (*chamfer* 5×5 por
    defecto), la pendiente (``slope_mode`` y, si es constante, ``slope_deg`` en ° desde la
    horizontal), el ``mesh_factor`` (— entre 0 excluido y 1; 1 por defecto), el alcance ``reach_m``
    (m; ninguno por defecto) y el acotado del dominio (``domain``). Con la pendiente por sectores,
    el talud general de cada sector es el máximo que impone o, si no lo tiene, el del perfil que se
    le asigna (RF-013-13, RF-013-21): ``base_profile`` es el código del perfil de las celdas sin
    sector y ``sector_profiles`` el de cada sector (código del sector → código del perfil; sale como
    pares ordenados por sector), que se guardan con los ajustes para recalcular y reproducir. Ni la
    métrica ni el alcance son parámetros del proyecto: son decisiones de esta operación."""

    name: str
    direction: Direction | str
    seeds: SeedSource
    slope_mode: SlopeMode | str = SlopeMode.CONSTANT
    slope_deg: float | None = None
    metric: Metric | str = Metric.CHAMFER5
    mesh_factor: float = 1.0
    reach_m: float | None = None
    domain: WorkDomain = field(default_factory=WorkDomain)
    base_profile: str | None = None
    sector_profiles: Mapping[str, str] | Iterable[tuple[str, str]] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "direction", Direction(self.direction))
        object.__setattr__(self, "slope_mode", SlopeMode(self.slope_mode))
        object.__setattr__(self, "metric", Metric(self.metric))
        object.__setattr__(self, "mesh_factor", float(self.mesh_factor))
        for name in ("slope_deg", "reach_m"):
            if getattr(self, name) is not None:
                object.__setattr__(self, name, float(getattr(self, name)))
        pairs: Any = self.sector_profiles
        object.__setattr__(self, "sector_profiles", tuple(sorted(dict(pairs).items())))


@dataclass(frozen=True, slots=True)
class DesignRequest:
    """Lo que pide el usuario de un escalonado (RF-013-21 a RF-013-24): su ``name`` (único en la
    versión), la ``envelope`` de la versión que se escalona, el ``sense`` (corte o relleno), el
    código del perfil base (``base_profile``), el de cada sector (``sector_profiles``: código del
    sector → código del perfil; sale como pares ordenados por sector) y la rejilla de anclas
    (``anchor_grid``; ninguna: el ancla del perfil)."""

    name: str
    envelope: str
    sense: BenchSense | str
    base_profile: str
    sector_profiles: Mapping[str, str] | Iterable[tuple[str, str]] = ()
    anchor_grid: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "sense", BenchSense(self.sense))
        pairs: Any = self.sector_profiles
        object.__setattr__(self, "sector_profiles", tuple(sorted(dict(pairs).items())))


@dataclass(frozen=True, slots=True)
class BenchProfile:
    """Un perfil de banco (RF-013-18): ``code`` inmutable (``[a-z][a-z0-9_]*``, ASCII; D-17),
    ``name`` libre y único (``EXPL_10_60_6``), la altura de banco ``height_m`` *h* (m), la
    inclinación máxima de la cara ``face_deg`` *α* (°, de 0 a 90 excluidos), la berma mínima
    ``berm_m`` *B* (m), la cota de ancla ``anchor_m`` *z₀* (m) y el ``mesh_factor`` (—, de 0
    excluido a 1; 1 por defecto). Sin ningún valor por defecto salvo el factor de malla (D-7).

    Un perfil no se crea con un valor fuera de su rango (:data:`~design.params.RANGES`), sin
    valor o sin nombre (``DesignError`` nombrando el perfil, el campo y el valor; RF-013-19):
    nada se calcula con él. El avance, el talud general y la marca «no resuelto por la rejilla»
    son **derivados**, no parámetros (RF-013-20)."""

    code: str
    name: str
    height_m: float
    face_deg: float
    berm_m: float
    anchor_m: float
    mesh_factor: float = 1.0

    def __post_init__(self) -> None:
        if not isinstance(self.code, str):
            raise TypeError(f"el código de un perfil es un texto, no {self.code!r}")
        if not is_code(self.code):
            raise ValueError(f"el código {self.code!r} no es [a-z][a-z0-9_]* (D-17)")
        if not isinstance(self.name, str):
            raise TypeError(f"el nombre de un perfil es un texto, no {self.name!r}")
        name = self.name.strip()
        if not name:
            raise DesignError("des.profile_name_missing", obj=f"Perfil de banco «{self.code}»",
                              field="name", value=self.name, profile=self.code)
        object.__setattr__(self, "name", name)
        for param in BenchParam:
            object.__setattr__(self, param.value, check_bench_value(
                name, self.code, param, getattr(self, param.value)))

    @property
    def face_footprint_m(self) -> float:
        """La huella horizontal de la cara, ``h / tan α`` (m)."""
        return self.height_m / math.tan(math.radians(self.face_deg))

    @property
    def avance_m(self) -> float:
        """El avance ``a = h/tan α + B`` (m): lo que avanza el perfil en planta por banco
        (RF-013-20)."""
        return self.face_footprint_m + self.berm_m

    @property
    def general_tan(self) -> float:
        """La tangente del talud general, ``h / a`` (exacta, no la de un ángulo redondeado)."""
        return self.height_m / self.avance_m

    @property
    def general_deg(self) -> float:
        """El talud general ``atan(h / a)`` (°; RF-013-20)."""
        return math.degrees(math.atan(self.general_tan))

    def unresolved_values(self, grid: Grid) -> dict[str, object] | None:
        """``None`` si la rejilla del proyecto ``grid`` resuelve el perfil; si no, los valores de
        la marca «no resuelto por la rejilla» (``des.profile_unresolved``: ``profile``, ``face``,
        ``berm`` y ``step``, en metros y a dos decimales) cuando la huella horizontal de la cara o
        la berma (la berma de 0 m no tiene huella que resolver) es menor que el paso de la
        rejilla, el mayor de ``dx`` y ``dy`` (RF-013-20; ADR-0014)."""
        step = max(float(grid.dx), float(grid.dy))
        face = self.face_footprint_m
        if face >= step and (self.berm_m == 0.0 or self.berm_m >= step):
            return None
        return {"profile": self.name, "face": round(face, 2), "berm": round(self.berm_m, 2),
                "step": round(step, 2)}

    def unresolved_by(self, grid: Grid, *, language: str = "es") -> str | None:
        """``None`` si la rejilla del proyecto ``grid`` resuelve el perfil; si no, el texto de la
        marca «no resuelto por la rejilla» (``des.profile_unresolved``, en ``language``) con los
        valores de :meth:`unresolved_values`."""
        values = self.unresolved_values(grid)
        if values is None:
            return None
        return render("des.profile_unresolved", language=language, **values)


# --- Cantera con dos superficies (spec 014, T02; plan 014 §5.1 y §5.3.1) -------------------------


class Surface(StrEnum):
    """Las dos superficies de una cantera (RF-014-12): la final y la de explotación."""

    FINAL = "final"
    EXPLOITATION = "exploitation"


class Order(StrEnum):
    """El orden del diseño (RF-014-13; D-4): «final primero» calcula antes la final y sube la
    explotación donde queda por debajo (``explotación = máx(explotación, final)``); «explotación
    primero» calcula antes la explotación y baja la final donde queda por encima
    (``final = mín(final, explotación)``)."""

    FINAL_FIRST = "final_first"
    EXPLOITATION_FIRST = "exploitation_first"


class AnchorMode(StrEnum):
    """El ancla de un escalonado: la cota de ancla de su perfil (``FIXED``), una rejilla de cotas
    de la versión (``GRID``; D-18 de la 013) o «al fondo de cada muro» (``NEAREST_FLOOR``: la
    cota del fondo más próximo en planta, empate a la más baja; RF-014-11)."""

    FIXED = "fixed"
    GRID = "grid"
    NEAREST_FLOOR = "nearest_floor"


class CellClass(StrEnum):
    """La clase de una celda de las dos superficies (RF-014-15; plan 014 §5.2.3, P-1): sin
    diferencia (≤ el espesor mínimo de la 012), desdoblado o relleno; :attr:`code` es su código
    en el GeoTIFF de la clasificación (0, 1 y 2)."""

    NONE = "none"
    UNSPLIT = "unsplit"
    FILL = "fill"

    @property
    def code(self) -> int:
        """El código de la clase en la rejilla de la clasificación: 0, 1 o 2."""
        return list(CellClass).index(self)

    @classmethod
    def from_code(cls, code: int) -> CellClass:
        """La clase del código ``code``; :class:`ValueError` si no es 0, 1 ni 2."""
        for item in cls:
            if item.code == code:
                return item
        raise ValueError(f"el código de clase {code!r} no es 0, 1 ni 2 (plan 014 §5.2.3)")


class ToFinalMode(StrEnum):
    """Dónde se aplica «explotación hasta la final» (RF-014-18; P-2): en ninguna zona, en todas
    las zonas avisadas (RF-014-17) o en las zonas de una capa de polígonos."""

    NONE = "none"
    WARNED = "warned"
    LAYER = "layer"


@dataclass(frozen=True, slots=True)
class LayerField:
    """Una capa de polígonos del proyecto y el campo numérico que se lee de ella (plan 014
    §5.2.1): la cota de los fondos (RF-014-05) o de las láminas de agua (RF-014-24)."""

    layer: str
    field: str


@dataclass(frozen=True, slots=True)
class CorridorFields:
    """La capa de líneas de los corredores y sus campos (RF-014-09; plan 014 §5.2.1): el ancho
    (``width_field``, m) y o bien una cota fija (``level_field``, m) o bien una rasante
    (``start_level_field``, m, y ``gradient_field``, la pendiente de la rasante en %, positiva
    cuando sube en el sentido del eje; en inglés, «gradient»: glosario §14, T60). Las dos cosas,
    ninguna o media rasante son un error del programa."""

    layer: str
    width_field: str
    level_field: str | None = None
    start_level_field: str | None = None
    gradient_field: str | None = None

    def __post_init__(self) -> None:
        rasante = (self.start_level_field, self.gradient_field)
        if (None in rasante) != (rasante == (None, None)):
            raise ValueError("una rasante lleva la cota inicial y la pendiente (RF-014-09)")
        if (self.level_field is None) == (rasante == (None, None)):
            raise ValueError("un corredor tiene una cota fija o una rasante, no las dos ni "
                             "ninguna (RF-014-09)")

    @property
    def has_gradient(self) -> bool:
        """Si el corredor va con rasante (cota inicial y pendiente) y no con cota fija."""
        return self.level_field is None


@dataclass(frozen=True, slots=True)
class QuarrySide:
    """Lo de una superficie de la cantera (RF-014-12): el perfil base (``base_profile``) y el de
    cada sector (``sector_profiles``: código del sector → código del perfil; sale como pares
    ordenados por sector), las semillas (``seeds``; ninguna: «coronación y zonas a sostener»,
    RF-014-02; o unas de la 013), el ancla (``anchor``; con ``GRID``, la rejilla ``anchor_grid``
    y solo con él) y la métrica de su envolvente (*chamfer* 5×5 por defecto, ADR-0014)."""

    base_profile: str
    sector_profiles: Mapping[str, str] | Iterable[tuple[str, str]] = ()
    seeds: SeedSource | None = None
    anchor: AnchorMode | str = AnchorMode.FIXED
    anchor_grid: str | None = None
    metric: Metric | str = Metric.CHAMFER5

    def __post_init__(self) -> None:
        object.__setattr__(self, "anchor", AnchorMode(self.anchor))
        object.__setattr__(self, "metric", Metric(self.metric))
        pairs: Any = self.sector_profiles
        object.__setattr__(self, "sector_profiles", tuple(sorted(dict(pairs).items())))
        if (self.anchor is AnchorMode.GRID) != (self.anchor_grid is not None):
            raise ValueError("la rejilla de anclas va con el ancla en rejilla y solo con ella "
                             "(D-18 de la 013)")

    @property
    def crown_seeds(self) -> bool:
        """Si las semillas son «coronación y zonas a sostener» (RF-014-02)."""
        return self.seeds is None


@dataclass(frozen=True, slots=True)
class QuarryRequest:
    """Lo que pide el usuario de «Cantera con dos superficies…» (RF-014-12): su ``name`` (único
    en la versión), la superficie de partida (``start``), los dos lados (``final`` y
    ``exploitation``, :class:`QuarrySide`), el ``order`` («final primero» por defecto, D-4) y las
    capas de plan 014 §5.2.1 que use: los fondos (``floors``), las zonas a conservar
    (``conserve``: restricciones de la 012 o capas, :class:`Zone`), los corredores
    (``corridors``), las zonas de restauración por relleno (``fill_zones``, una capa; D-11) y las
    láminas de agua (``water``); y «explotación hasta la final» (``to_final``; con ``LAYER``, la
    capa ``to_final_layer`` y solo con él; P-2)."""

    name: str
    start: str
    final: QuarrySide
    exploitation: QuarrySide
    order: Order | str = Order.FINAL_FIRST
    floors: LayerField | None = None
    conserve: tuple[Zone, ...] | Iterable[Zone] = ()
    corridors: CorridorFields | None = None
    fill_zones: str | None = None
    water: LayerField | None = None
    to_final: ToFinalMode | str = ToFinalMode.NONE
    to_final_layer: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "order", Order(self.order))
        object.__setattr__(self, "to_final", ToFinalMode(self.to_final))
        if isinstance(self.conserve, str | bytes):
            raise TypeError(f"las zonas a conservar son una lista de zonas, no {self.conserve!r}")
        object.__setattr__(self, "conserve", tuple(self.conserve))
        if (self.to_final is ToFinalMode.LAYER) != (self.to_final_layer is not None):
            raise ValueError("la capa de «explotación hasta la final» va con el modo «capa» y "
                             "solo con él (P-2)")

    def side(self, surface: Surface | str) -> QuarrySide:
        """El lado de la superficie ``surface``."""
        if Surface(surface) is Surface.FINAL:
            return self.final
        return self.exploitation


@dataclass(frozen=True, slots=True)
class FillOnlyRequest:
    """Lo que pide el usuario de «Solo relleno…» (spec 014, T30; RF-014-22 a RF-014-24; plan 014
    §5.3.3): como el escalonado **en relleno** de la 013 —su ``name`` (único en la versión), la
    ``envelope`` de la versión que se escalona, la superficie de partida (``start``, el nombre de
    su dato), el código del perfil base (``base_profile``), el de cada sector
    (``sector_profiles``: código del sector → código del perfil; sale como pares ordenados por
    sector) y la rejilla de anclas (``anchor_grid``; ninguna: el ancla del perfil)— más la capa de
    las láminas de agua con su campo de cota (``water``; ninguna: sin láminas, D-10)."""

    name: str
    envelope: str
    start: str
    base_profile: str
    sector_profiles: Mapping[str, str] | Iterable[tuple[str, str]] = ()
    anchor_grid: str | None = None
    water: LayerField | None = None

    def __post_init__(self) -> None:
        pairs: Any = self.sector_profiles
        object.__setattr__(self, "sector_profiles", tuple(sorted(dict(pairs).items())))

    @property
    def design(self) -> DesignRequest:
        """El escalonado de la 013 que hace (RF-014-22): el de la misma envolvente, en relleno,
        con su perfil base, el de cada sector y su ancla."""
        return DesignRequest(self.name, self.envelope, BenchSense.FILL, self.base_profile,
                             self.sector_profiles, self.anchor_grid)


@dataclass(frozen=True, slots=True)
class RefitRequest:
    """Lo que pide el usuario de «Ajustar el diseño a un límite nuevo…» (spec 014, T32; RF-014-27,
    RF-014-28; plan 014 A13, P-3): su ``name`` (único en la versión), las superficies de diseño de
    la versión que se ajustan (``surfaces``: los nombres de sus datos, en su orden y sin repetir;
    al menos una) y la superficie de partida (``start``, el nombre de su dato). El ángulo de cada
    superficie **no se pide**: es la cara del perfil de la operación que la creó (P-3); solo una
    petición por guion puede traer uno (``angles``: superficie → °, sale como pares ordenados por
    superficie), que se comprueba contra esa cara (RF-014-28) y no se guarda."""

    name: str
    surfaces: tuple[str, ...] | Iterable[str]
    start: str
    angles: Mapping[str, float] | Iterable[tuple[str, float]] = ()

    def __post_init__(self) -> None:
        if isinstance(self.surfaces, str | bytes):
            raise TypeError(f"las superficies que se ajustan son una lista de nombres, no "
                            f"{self.surfaces!r}")
        found = tuple(self.surfaces)
        if not found or not all(isinstance(item, str) and item.strip() for item in found):
            raise ValueError(f"un ajuste ajusta al menos una superficie, por el nombre de su "
                             f"dato, no {found!r}")
        if len(set(found)) != len(found):
            raise ValueError(f"una superficie se ajusta una vez, no {found!r}")
        object.__setattr__(self, "surfaces", found)
        pairs: Any = self.angles
        angles = tuple(sorted(dict(pairs).items()))
        strangers = [surface for surface, _angle in angles if surface not in found]
        if strangers:
            raise ValueError(f"se pide un ángulo para {strangers!r}, que no se ajusta")
        object.__setattr__(self, "angles", angles)


class Named(Protocol):
    """Lo que la comprobación de nombres lee de un perfil: su ``code`` y su ``name`` (un
    :class:`BenchProfile` o una fila de ``design.profiles``)."""

    @property
    def code(self) -> str: ...

    @property
    def name(self) -> str: ...


def check_profiles(profiles: Iterable[Named]) -> None:
    """Comprueba el conjunto de perfiles de un proyecto: ``DesignError``
    ``des.profile_name_repeated`` si un perfil repite el nombre de otro (sin distinguir
    mayúsculas: el código sale del nombre; RF-013-19), nombrando los dos; :class:`ValueError` si
    dos tienen el mismo código (el sistema lo fija al crear el perfil y es único: un error del
    programa)."""
    codes: dict[str, str] = {}
    names: dict[str, str] = {}
    for profile in profiles:
        if profile.code in codes:
            raise ValueError(f"el código {profile.code!r} está en dos perfiles (D-17)")
        codes[profile.code] = profile.name
        key = profile.name.casefold()
        if key in names:
            raise DesignError("des.profile_name_repeated",
                              obj=f"Perfil de banco «{profile.code}»", field="name",
                              value=profile.name, profile=profile.code, other=names[key])
        names[key] = profile.code


# --- Entidades de diseño: la plataforma (spec 015, T02; plan 015 §5.1, §5.2.1 y §5.3.1) ----------


class PlatformMode(StrEnum):
    """El modo de una plataforma (RF-015-20, RF-015-21; D-5): ``CUT`` («en corte», el de por
    defecto) baja a la rasante donde el corte se admite y no sube ninguna celda (la plataforma es
    el fondo de su corredor, no una cota mínima); ``CUT_FILL`` («en corte y relleno») además sube a
    la rasante donde el relleno se admite."""

    CUT = "cut"
    CUT_FILL = "cut_fill"


def _text(value: object, what: str) -> str:
    """``value`` sin los espacios de los extremos; :class:`TypeError` si no es un texto."""
    if not isinstance(value, str):
        raise TypeError(f"{what} es un texto, no {value!r}")
    return value.strip()


def _name_or_none(value: object, what: str) -> str | None:
    """``value`` como texto sin los espacios de los extremos (``None`` si es ``None`` o está en
    blanco); :class:`TypeError` si no es un texto."""
    if value is None:
        return None
    return _text(value, what) or None


def _real_or_none(value: object, what: str) -> float | None:
    """``value`` como ``float`` (``None`` si es ``None``); :class:`TypeError` si no es un número
    real (un texto o un booleano no lo son)."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"{what} es un número real, no {value!r}")
    return float(value)


@dataclass(frozen=True, slots=True)
class PlatformFields:
    """La capa de una plataforma y los campos que se leen de ella (plan 015 §5.2.1; D-15: los de
    un corredor de la 014): su ``layer`` y, de cada geometría, la cota inicial de la rasante
    (``start_level_field``, m) y su pendiente (``gradient_field``, %, positiva si sube en el sentido
    del eje). Una capa de líneas lleva además el ancho (``width_field``, m); una de polígonos, si
    quiere elegir su eje, el campo que lo enlaza (``axis_field``: el ``fid`` de una línea) y la capa
    de líneas de ese eje (``axis_layer``), los dos o ninguno (sin ellos, el eje principal del
    polígono, con aviso). Una línea con ancho y un polígono con eje enlazado no se dan juntos."""

    layer: str
    start_level_field: str
    gradient_field: str
    width_field: str | None = None
    axis_field: str | None = None
    axis_layer: str | None = None

    def __post_init__(self) -> None:
        for name in ("layer", "start_level_field", "gradient_field"):
            value = _text(getattr(self, name), f"«{name}» de los campos de una plataforma")
            if not value:
                raise ValueError(f"«{name}» de los campos de una plataforma no puede estar en "
                                 "blanco (plan 015 §5.2.1)")
            object.__setattr__(self, name, value)
        for name in ("width_field", "axis_field", "axis_layer"):
            object.__setattr__(self, name, _name_or_none(
                getattr(self, name), f"«{name}» de los campos de una plataforma"))
        if (self.axis_field is None) != (self.axis_layer is None):
            raise ValueError("el enlace de un polígono con su eje lleva el campo y la capa de "
                             "líneas, los dos o ninguno (plan 015 §5.2.1)")
        if self.width_field is not None and self.axis_field is not None:
            raise ValueError("una plataforma es una línea con su ancho o un polígono con su eje "
                             "enlazado, no las dos cosas (RF-015-19)")


@dataclass(frozen=True, slots=True)
class Axis:
    """El eje de una plataforma (RF-015-19): la polilínea de sus ``vertices`` absolutos
    ``(x, y)`` en ``float64`` (pares de ``float`` de Python: lo exacto, sin ``float32``; ADR-0005),
    en el sentido de digitalización: la abscisa 0 está en el primer vértice. ``principal``, si es
    el eje principal de un polígono sin eje enlazado (con el aviso ``des.platform_axis_principal``).

    El modelo no rechaza un eje sin longitud ni cerrado (lo hace la geometría con su capa y su
    entidad, RF-015-08): lo representa. Lo que no puede ser un eje (menos de dos vértices, un
    vértice que no son dos números finitos) es un error del programa: :class:`ValueError`."""

    vertices: tuple[tuple[float, float], ...]
    principal: bool = False

    def __post_init__(self) -> None:
        points: list[tuple[float, float]] = []
        try:
            for vertex in self.vertices:
                x, y = vertex
                point = (float(x), float(y))
                if not (math.isfinite(point[0]) and math.isfinite(point[1])):
                    raise ValueError("no es un número finito")
                points.append(point)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"un eje es una lista de vértices (x, y) finitos: {exc}") from None
        if len(points) < 2:
            raise ValueError(f"un eje tiene al menos dos vértices, no {len(points)}")
        object.__setattr__(self, "vertices", tuple(points))

    @property
    def start(self) -> tuple[float, float]:
        """El primer vértice: la abscisa 0."""
        return self.vertices[0]

    @property
    def end(self) -> tuple[float, float]:
        """El último vértice."""
        return self.vertices[-1]

    @property
    def length_m(self) -> float:
        """La longitud medida sobre el eje (m): la suma de sus tramos."""
        return math.fsum(math.hypot(b[0] - a[0], b[1] - a[1])
                         for a, b in zip(self.vertices, self.vertices[1:], strict=False))

    @property
    def closed(self) -> bool:
        """Si el eje es un anillo: acaba donde empieza, con tres vértices al menos."""
        return len(self.vertices) >= 3 and self.vertices[0] == self.vertices[-1]


@dataclass(frozen=True, slots=True)
class PlatformRequest:
    """Lo que pide el usuario de «Plataforma…» (RF-015-01, RF-015-19 a RF-015-23; plan 015 §5.3.1
    y §5.3.3; el homólogo de :class:`QuarryRequest`): su ``name`` (único en la versión), la capa y
    sus campos (``fields``), la geometría de la capa (``feature``: su nombre o su ``fid``, como
    texto; ``prepare_platform`` la resuelve, T11), la superficie de partida (``start``, el nombre de
    su dato) y, si la hay, la de apoyo (``support``), el ``mode`` y los valores del borde
    (``edge_angle_deg``, ``mesh_factor``, ``reach_m`` y la ``metric``), la tolerancia de
    contrapendiente (``counter_tol_m``), la pendiente máxima (``max_slope_pct``) y lo que declara
    (``protect``, ``guard_m`` y su ``reason``).

    Lo que no se pide es ``None``: el valor por defecto del parámetro (D-5, D-7, D-8 y D-22: la
    petición no lleva ninguna cifra minera a mano) o, si no lo tiene, el rechazo de RF-015-08. Las
    cotas, la pendiente y el ancho no se piden: salen de los campos de la capa y se copian a los
    parámetros de la entidad al crearla (P-3). Lo leído (rejilla, partida, máscaras y geometría)
    no es parte de la petición: lo recoge el cálculo.

    **Lo que corrige el diálogo** (spec 015, T15; plan §5.2.1): el diálogo de «Plataforma…» propone la
    cota inicial, la pendiente y el ancho que lee de los campos de la capa y deja corregirlos; los
    valores corregidos (``start_level_m``, ``gradient_pct`` y ``width_m``; ``None`` los que no se
    corrigen) mandan sobre los de la capa y se copian a los parámetros de la entidad con el origen del
    diálogo; un valor igual al de la capa conserva su origen. El ancho, solo de una capa de líneas
    (``ValueError``: es un error del programa pedirlo de un polígono)."""

    name: str
    fields: PlatformFields
    feature: str
    start: str
    support: str | None = None
    mode: PlatformMode | str | None = None
    edge_angle_deg: float | None = None
    reach_m: float | None = None
    mesh_factor: float | None = None
    counter_tol_m: float | None = None
    metric: Metric | str | None = None
    max_slope_pct: float | None = None
    protect: bool = False
    guard_m: float | None = None
    reason: str | None = None
    start_level_m: float | None = None
    gradient_pct: float | None = None
    width_m: float | None = None

    def __post_init__(self) -> None:
        name = _text(self.name, "el nombre de una plataforma")
        if not name:
            raise DesignError("des.entity_name_missing", obj="Plataforma", field="name",
                              value=self.name)
        object.__setattr__(self, "name", name)
        if not isinstance(self.fields, PlatformFields):
            raise TypeError(f"los campos de una plataforma son PlatformFields, no "
                            f"{self.fields!r}")
        for attr in ("feature", "start"):
            object.__setattr__(self, attr, _text(getattr(self, attr), f"«{attr}» de una "
                                                                     "plataforma"))
        for attr in ("support", "reason"):
            object.__setattr__(self, attr, _name_or_none(getattr(self, attr), f"«{attr}» de una "
                                                                              "plataforma"))
        if self.mode is not None:
            object.__setattr__(self, "mode", PlatformMode(self.mode))
        if self.metric is not None:
            object.__setattr__(self, "metric", Metric(self.metric))
        for attr in ("edge_angle_deg", "reach_m", "mesh_factor", "counter_tol_m",
                     "max_slope_pct", "guard_m", "start_level_m", "gradient_pct", "width_m"):
            object.__setattr__(self, attr, _real_or_none(getattr(self, attr),
                                                         f"«{attr}» de una plataforma"))
        if not isinstance(self.protect, bool):
            raise TypeError(f"«protect» de una plataforma es un sí/no, no {self.protect!r}")
        if self.width_m is not None and self.fields.width_field is None:
            raise ValueError("una plataforma de polígono no lleva ancho (RF-015-19): su capa "
                             f"«{self.fields.layer}» no tiene campo de ancho, y se pidió un ancho de "
                             f"{self.width_m} m")

    @property
    def layer(self) -> str:
        """La capa de la geometría de la plataforma."""
        return self.fields.layer

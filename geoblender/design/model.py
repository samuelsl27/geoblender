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
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from .messages import DesignError, render
from .params import BenchParam, check_bench_value, is_code

if TYPE_CHECKING:
    from ..gis.grid import Grid

__all__ = [
    "PERIMETER_SEGMENT",
    "BenchProfile",
    "BenchSense",
    "DesignRequest",
    "Direction",
    "EnvelopeRequest",
    "Metric",
    "SeedKind",
    "SeedSource",
    "SlopeMode",
    "WorkDomain",
    "Zone",
    "ZoneKind",
    "check_profiles",
]

PERIMETER_SEGMENT = "perimeter__"
"""El código del perímetro de actuación como sector único, en la clave de un parámetro por sector
(``des.sector.perimeter__.max_general_slope_deg``; ADR-0029, D-23)."""


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


def check_profiles(profiles: Iterable[BenchProfile]) -> None:
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

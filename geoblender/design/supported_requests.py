# SPDX-License-Identifier: GPL-3.0-or-later
"""Las peticiones de los cuatro tipos de la 016 (spec 016, T03 y T51; plan 016 §5.1, §5.2.1, §5.2.2 y
§5.3.1): la detección de acopios (:class:`StockpileRequest`, con la capa de marcas y sus campos,
:class:`StockpileFields`), la retirada (:class:`RemovalRequest`), el contrafuerte
(:class:`ButtressRequest`, con su capa de zonas, :class:`ButtressFields`) y el cuerpo apoyado
(:class:`BodyRequest`; su sentido, :class:`~geoblender.design.model.BodySense`, y de dónde sale su espesor,
:class:`~geoblender.design.model.ThicknessSource`, son de :mod:`design.model`). Sin ninguna cifra minera por
defecto (lo que no se pide es ``None``).

Viven aquí y no en :mod:`design.model` para que **habilitar no las cree** (RNF-001-03): cada
``@dataclass(frozen=True, slots=True)`` cuesta ≈ 0,5–1 ms al importar el módulo y las seis eran 4,2 ms
de los 25 ms con los que la 016 subió el habilitado de Geoblender. ``design.model`` las ofrece con su
nombre de siempre al pedirlas (``model.StockpileRequest``, ``from .model import StockpileRequest``,
``__getattr__`` de PEP 562, como :mod:`gis.masks`): son el mismo objeto. Los ayudantes de conversión son los
de :mod:`design.model` (``_text``, ``_name_or_none``, ``_real_or_none``); los cuatro que solo usan estas
peticiones se movieron con ellas.
"""

from __future__ import annotations

import numbers
from dataclasses import dataclass

from .messages import DesignError
from .model import BodySense, Metric, ThicknessSource, _name_or_none, _real_or_none, _text

__all__ = [
    "BodyRequest",
    "ButtressFields",
    "ButtressRequest",
    "RemovalRequest",
    "StockpileFields",
    "StockpileRequest",
]


def _int_or_none(value: object, what: str) -> int | None:
    """``value`` como ``int`` (``None`` si es ``None``); :class:`TypeError` si no es un entero (un decimal, un texto
    o un booleano no lo son)."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, numbers.Integral):
        raise TypeError(f"{what} es un número entero, no {value!r}")
    return int(value)


def _flag_or_none(value: object, what: str) -> bool | None:
    """``value`` si es un sí/no (``None`` si es ``None``); :class:`TypeError` si no lo es."""
    if value is not None and not isinstance(value, bool):
        raise TypeError(f"{what} es un sí/no, no {value!r}")
    return value


def _named(value: object, what: str, label: str) -> str:
    """El nombre ``value`` de una entidad de la 016 sin los espacios de los extremos; ``DesignError``
    ``des.entity_name_missing`` si está en blanco; :class:`TypeError` si no es un texto."""
    name = _text(value, what)
    if not name:
        raise DesignError("des.entity_name_missing", obj=label, field="name", value=value)
    return name


def _layer(value: object, what: str) -> str:
    """El nombre de la capa ``value`` de ``what`` sin los espacios de los extremos; :class:`ValueError` si está en
    blanco (plan 016 §5.2.1) y :class:`TypeError` si no es un texto."""
    layer = _text(value, f"la capa de {what}")
    if not layer:
        raise ValueError(f"la capa de {what} no puede estar en blanco (plan 016 §5.2.1)")
    return layer


@dataclass(frozen=True, slots=True)
class StockpileFields:
    """La capa de marcas de una detección de acopios y los campos que se leen de ella (plan 016 §5.2.1; RF-016-02,
    RF-016-03): su ``layer`` (polígonos orientativos, uno por acopio) y, si los tiene, el campo con el nombre de la
    marca (``name_field``: su clave; sin él se usa el ``fid``), el de su margen (``margin_field``, m), el de su
    material (``material_field``) y el de su superficie de base (``base_field``: el nombre de una superficie del
    proyecto). Los nombres de campo se eligen en el diálogo, como en la 014 y la 015; solo la capa es obligatoria."""

    layer: str
    name_field: str | None = None
    margin_field: str | None = None
    material_field: str | None = None
    base_field: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "layer", _layer(self.layer, "las marcas de los acopios"))
        for name in ("name_field", "margin_field", "material_field", "base_field"):
            object.__setattr__(self, name, _name_or_none(getattr(self, name),
                                                         f"«{name}» de los campos de las marcas"))


@dataclass(frozen=True, slots=True)
class StockpileRequest:
    """Lo que pide el usuario de «Acopio (detectar, retirar)…» al **detectar** (RF-016-02, RF-016-08; plan 016 §5.2.2
    y §5.3.3; el homólogo de :class:`PlatformRequest`): su ``name`` (único en su ámbito), la capa de marcas y sus
    campos (``fields``), la superficie sobre la que se detecta (``surface``, el nombre de su dato), si se buscan
    también los candidatos sin marca (``candidates``) y los umbrales de D-3: el margen, la separación interior y exterior
    de la corona, su pendiente y su área llana mínima, el residuo máximo, las vueltas del ajuste y de plano y huella, la
    inclinación máxima y el cuantil de apoyo (HIPÓTESIS), y, de los candidatos, el diámetro de la apertura, la altura
    mínima y las áreas mínima y máxima; las ``decisions`` sobre los candidatos y lo que declara (``protect``,
    ``guard_m`` y ``reason``).

    Lo que no se pide es ``None``: el valor por defecto del parámetro (D-3: la petición no lleva ninguna cifra minera)
    o, si no lo tiene, el rechazo de RF-015-08. Lo leído (la rejilla, las marcas, el perímetro) no es parte de la
    petición: lo recoge el cálculo. El umbral de la huella y el espesor mínimo no son de la petición: se leen por su
    clave de la 011 y de la 012."""

    name: str
    fields: StockpileFields
    surface: str
    candidates: bool | None = None
    margin_m: float | None = None
    crown_inner_m: float | None = None
    crown_outer_m: float | None = None
    crown_slope_deg: float | None = None
    crown_flat_min_m2: float | None = None
    max_residual_m: float | None = None
    fit_rounds: int | None = None
    turns: int | None = None
    tilt_max_deg: float | None = None
    support_quantile: float | None = None
    open_diameter_m: float | None = None
    min_height_m: float | None = None
    min_area_m2: float | None = None
    max_area_m2: float | None = None
    decisions: str | None = None
    protect: bool | None = None
    guard_m: float | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _named(self.name, "el nombre de una detección de acopios",
                                                "Detección de acopios"))
        if not isinstance(self.fields, StockpileFields):
            raise TypeError(f"los campos de las marcas son StockpileFields, no {self.fields!r}")
        object.__setattr__(self, "surface", _text(self.surface, "«surface» de una detección de acopios"))
        for attr in ("decisions", "reason"):
            object.__setattr__(self, attr, _name_or_none(getattr(self, attr),
                                                         f"«{attr}» de una detección de acopios"))
        for attr in ("margin_m", "crown_inner_m", "crown_outer_m", "crown_slope_deg", "crown_flat_min_m2",
                     "max_residual_m", "tilt_max_deg", "support_quantile", "open_diameter_m", "min_height_m",
                     "min_area_m2", "max_area_m2", "guard_m"):
            object.__setattr__(self, attr, _real_or_none(getattr(self, attr),
                                                         f"«{attr}» de una detección de acopios"))
        for attr in ("fit_rounds", "turns"):
            object.__setattr__(self, attr, _int_or_none(getattr(self, attr),
                                                        f"«{attr}» de una detección de acopios"))
        for attr in ("candidates", "protect"):
            object.__setattr__(self, attr, _flag_or_none(getattr(self, attr),
                                                         f"«{attr}» de una detección de acopios"))

    @property
    def layer(self) -> str:
        """La capa de las marcas."""
        return self.fields.layer


@dataclass(frozen=True, slots=True)
class RemovalRequest:
    """Lo que pide el usuario de «Acopio (detectar, retirar)…» al **retirar** un acopio (RF-016-11 a RF-016-16; plan
    016 §5.2.2): su ``name`` (único en la versión), el acopio que se retira (``stockpile``: su detección y su clave,
    ``STK-001#m07``), la superficie de la que parte (``start``) y, si la hay, la de apoyo (``support``), el ángulo de
    transición (``transition_deg``, sin valor por defecto: D-2), el factor de malla, la métrica, el motivo de la pared
    que deja (``wall_reason``, RF-016-15) y lo que declara. «Como plataforma» (RF-016-16) es una plataforma de la 015
    con la huella como geometría, no una opción de esta petición. Lo que no se pide es ``None``."""

    name: str
    stockpile: str
    start: str
    support: str | None = None
    transition_deg: float | None = None
    mesh_factor: float | None = None
    metric: Metric | str | None = None
    wall_reason: str | None = None
    protect: bool | None = None
    guard_m: float | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _named(self.name, "el nombre de una retirada", "Retirada de acopio"))
        for attr in ("stockpile", "start"):
            object.__setattr__(self, attr, _text(getattr(self, attr), f"«{attr}» de una retirada"))
        for attr in ("support", "wall_reason", "reason"):
            object.__setattr__(self, attr, _name_or_none(getattr(self, attr), f"«{attr}» de una retirada"))
        if self.metric is not None:
            object.__setattr__(self, "metric", Metric(self.metric))
        for attr in ("transition_deg", "mesh_factor", "guard_m"):
            object.__setattr__(self, attr, _real_or_none(getattr(self, attr), f"«{attr}» de una retirada"))
        object.__setattr__(self, "protect", _flag_or_none(self.protect, "«protect» de una retirada"))


@dataclass(frozen=True, slots=True)
class ButtressFields:
    """La capa de las zonas de coronación de un contrafuerte y el campo que se lee de ella (plan 016 §5.2.1;
    RF-016-17): su ``layer`` (polígonos) y, si la capa la da, el campo de la cota de coronación (``crown_field``, m:
    el valor que se copia al parámetro, que lo copia **la persona**, ADR-0025 §5)."""

    layer: str
    crown_field: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "layer", _layer(self.layer, "las zonas de coronación"))
        object.__setattr__(self, "crown_field", _name_or_none(self.crown_field,
                                                              "«crown_field» de los campos de las zonas"))


@dataclass(frozen=True, slots=True)
class ButtressRequest:
    """Lo que pide el usuario de «Contrafuerte…» (RF-016-17 a RF-016-19; plan 016 §5.2.2; D-7): su ``name``, la capa de
    las zonas de coronación (``fields``) y la geometría de la capa (``feature``), la superficie de la que parte
    (``start``) y, si no es esa, la de apoyo (``support``; también la de explotación de una cantera de la 014), el
    código del perfil de banco de la 013 (``profile``), la cota de coronación (``crown_m``, sin valor por defecto: del
    ancla de su perfil, D-21), el alcance opcional (``reach_m``), la métrica y lo que declara (``protect``: ``None`` es
    el valor por defecto del parámetro, verdadero para el contrafuerte, D-1). Lo que no se pide es ``None``."""

    name: str
    fields: ButtressFields
    feature: str
    start: str
    profile: str
    support: str | None = None
    crown_m: float | None = None
    reach_m: float | None = None
    metric: Metric | str | None = None
    protect: bool | None = None
    guard_m: float | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _named(self.name, "el nombre de un contrafuerte", "Contrafuerte"))
        if not isinstance(self.fields, ButtressFields):
            raise TypeError(f"los campos de las zonas son ButtressFields, no {self.fields!r}")
        for attr in ("feature", "start", "profile"):
            object.__setattr__(self, attr, _text(getattr(self, attr), f"«{attr}» de un contrafuerte"))
        for attr in ("support", "reason"):
            object.__setattr__(self, attr, _name_or_none(getattr(self, attr), f"«{attr}» de un contrafuerte"))
        if self.metric is not None:
            object.__setattr__(self, "metric", Metric(self.metric))
        for attr in ("crown_m", "reach_m", "guard_m"):
            object.__setattr__(self, attr, _real_or_none(getattr(self, attr), f"«{attr}» de un contrafuerte"))
        object.__setattr__(self, "protect", _flag_or_none(self.protect, "«protect» de un contrafuerte"))

    @property
    def layer(self) -> str:
        """La capa de las zonas de coronación."""
        return self.fields.layer


@dataclass(frozen=True, slots=True)
class BodyRequest:
    """Lo que pide el usuario de «Cuerpo apoyado…» (RF-016-20 a RF-016-22; plan 016 §5.2.2; D-8, D-9): su ``name``, la
    huella (la capa ``layer`` y la geometría ``feature``), los datos de espesor (la capa ``data_layer``, el campo
    ``data_field`` y de dónde se leen, ``data_from``), la superficie conocida (``surface``) y su sentido (``sense``:
    «sobre una base» o «bajo un techo»), la partida (``start``, solo «sobre una base»: «bajo un techo» no cambia la
    superficie y no parte de ninguna), la distancia máxima a los datos (``max_distance_m``, sin valor por defecto: D-9),
    el «cero en el borde» (``zero_at_edge``) y lo que declara. Lo que no se pide es ``None``."""

    name: str
    layer: str
    feature: str
    data_layer: str
    data_field: str
    data_from: ThicknessSource | str
    surface: str
    sense: BodySense | str
    start: str | None = None
    max_distance_m: float | None = None
    zero_at_edge: bool | None = None
    support: str | None = None
    protect: bool | None = None
    guard_m: float | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _named(self.name, "el nombre de un cuerpo apoyado", "Cuerpo apoyado"))
        for attr in ("layer", "feature", "data_layer", "data_field", "surface"):
            object.__setattr__(self, attr, _text(getattr(self, attr), f"«{attr}» de un cuerpo apoyado"))
        object.__setattr__(self, "data_from", ThicknessSource(self.data_from))
        object.__setattr__(self, "sense", BodySense(self.sense))
        for attr in ("start", "support", "reason"):
            object.__setattr__(self, attr, _name_or_none(getattr(self, attr), f"«{attr}» de un cuerpo apoyado"))
        if self.sense is BodySense.UNDER_ROOF and self.start is not None:
            raise ValueError("un cuerpo «bajo un techo» no cambia la superficie y no parte de ninguna (RF-016-20): "
                             f"no lleva partida, y se pidió {self.start!r}")
        for attr in ("max_distance_m", "guard_m"):
            object.__setattr__(self, attr, _real_or_none(getattr(self, attr), f"«{attr}» de un cuerpo apoyado"))
        for attr in ("zero_at_edge", "protect"):
            object.__setattr__(self, attr, _flag_or_none(getattr(self, attr), f"«{attr}» de un cuerpo apoyado"))

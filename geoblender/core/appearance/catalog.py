# SPDX-License-Identifier: GPL-3.0-or-later
"""El catálogo del aspecto: qué se edita de cada tipo de elemento y su predefinido (spec 019, T02;
RF-019-07, RF-019-09; plan 019 §5.2 y A1; D-5 y D-11; ADR-0033).

- :data:`KINDS`: por cada ``kind`` de ``GEOBLENDER_PG_core_object`` (``bl.props.core.OBJECT_KINDS``, menos
  ``NONE``), las propiedades que se ofrecen (:func:`allowed`: **un tipo sin una propiedad no la lista**, UI-13) y
  su predefinido (:func:`defaults_for`). El aplicador de Blender (T07) y el panel (T10) leen de aquí «según el
  tipo»; no hay ``if`` por tipo fuera de este catálogo.
- **El predefinido es el valor actual** de lo que ya pinta cada cargador, para que lo que hoy se ve no cambie
  (``entity_views.COLORS``, ``constraint_views.INTENTION_STYLE``, ``core.constraints.styles.COLORS``,
  ``des_views.CLASS_LEGEND``, ``res_views``, los tubos de sondeos): :data:`INVENTORY` lo reúne y una prueba lo
  compara con cada cargador (``bl`` no se importa fuera de Blender: se lee con el árbol sintáctico). Un tipo cuyo
  cargador no le da color propio (Blender lo pinta con el del objeto) toma uno de la **paleta de Okabe e Ito**
  (:data:`PALETTE`, legible con daltonismo); eso no cambia lo que se ve hasta que alguien lo aplica.
- Los colores de los cargadores son RGBA de 0 a 1 o ``r, g, b`` de 0 a 255; aquí van en ``#RRGGBB`` (el valor
  canónico, :mod:`.model`) con el mismo redondeo (``int(c * 255 + 0.5)``).

Dominio puro: ni ``bpy`` ni nada de ``bl``; no importa otros paquetes de dominio (las constantes que reúne
se copian y una prueba las compara).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import GeoblenderError
from ..i18n import tr
from .model import Appearance

__all__ = ["CLASS_LEGEND_COLORS", "CONSTRAINT_SUBKINDS", "DRILLHOLE_NO_DATA_COLOR", "DRILLHOLE_RAMP",
           "ENTITY_SUBKINDS", "INVENTORY", "KINDS", "LoaderPaint", "PALETTE", "PROPERTIES", "allowed",
           "defaults_for", "legend_driven"]

PROPERTIES: tuple[str, ...] = ("label", "color", "transparency", "visible", "line_width", "point_size", "labels", "wire")
"""Las propiedades de aspecto que existen (D-5), en el orden en que se ofrecen: rótulo, color, transparencia y
visibilidad, y según el tipo, grosor de línea, tamaño de punto, etiquetas y malla visible."""

PALETTE: tuple[str, ...] = ("#E69F00", "#56B4E9", "#009E73", "#F0E442", "#0072B2", "#D55E00", "#CC79A7", "#999999")
"""La paleta de Okabe e Ito (D-11): naranja, azul cielo, verde azulado, amarillo, azul, bermellón y púrpura
rojizo; el octavo es un gris (el negro de la original no se ve sobre el tema oscuro)."""

ENTITY_SUBKINDS: dict[str, str] = {
    "platform": "#1AA68C", "stockpile": "#D98C1A", "removal": "#CC4D40", "buttress": "#8066CC",
    "body": "#4D8CD9", "road": "#E6D126", "pit": "#9E6B47", "other": "#999999",
}
"""El color de cada tipo de entidad de diseño (``entity_views.COLORS`` y ``OTHER_COLOR``)."""
CONSTRAINT_SUBKINDS: dict[str, str] = {
    "legal_limit": "#143C96", "action_perimeter": "#1E963C", "untouchable": "#C81414", "exclusion": "#8C1464",
    "no_cut": "#E68214", "fill_only": "#2878DC", "restoration_only": "#7850AA", "setback": "#C8B428",
    "no_fill": "#6EA028", "avoid": "#F5AF3C", "requires_access": "#3CA0AA", "untyped": "#828282",
}
"""El color de cada tipo de restricción (``core.constraints.styles.COLORS``) y el de lo sin tipo (``ELSE_COLOR``)."""
CLASS_LEGEND_COLORS: dict[str, tuple[str, ...]] = {
    "des_views.CLASS_LEGEND": ("#808080", "#E64D05", "#0D8C1A"),
    "res_views._GRAY": ("#808080",),
}
"""Los colores por clase de las rejillas (leyendas: el color lo dice la leyenda, D-8)."""
DRILLHOLE_NO_DATA_COLOR = "#808080"
"""El color de un hueco o de un código sin color en los sondeos (``drillholes.model.DEFAULT_COLOR``)."""
DRILLHOLE_RAMP: tuple[str, ...] = ("#2C7BB6", "#3FA34D", "#F2D43D", "#F28C28", "#D7263D")
"""La rampa por defecto de las leyes (``drillholes.view_data.DEFAULT_RAMP``)."""

_STANDARD = {"label": None, "color": None, "transparency": "0", "visible": "1", "line_width": "1", "point_size": "3",
             "labels": "0", "wire": "0"}
"""El predefinido de lo que no depende del tipo (``label`` no tiene: es el nombre del dato)."""


@dataclass(frozen=True)
class KindSpec:
    """Lo que el catálogo sabe de un tipo: sus propiedades, su color y lo que lo cambia de lo estándar."""

    props: tuple[str, ...]
    color: str | None
    legend_driven: bool = False
    line_width: str | None = None


KINDS: dict[str, KindSpec] = {
    "PROJECT_ANCHOR": KindSpec(("label", "visible"), None),
    "DTM": KindSpec(("label", "color", "transparency", "visible", "wire"), "#56B4E9"),
    "TIN": KindSpec(("label", "color", "transparency", "visible", "wire"), "#0072B2"),
    "POINTS": KindSpec(("label", "color", "visible", "point_size", "labels"), "#D55E00"),
    "BREAKLINES": KindSpec(("label", "color", "visible", "line_width"), "#CC79A7"),
    "CONTOURS": KindSpec(("label", "color", "visible", "line_width"), "#E69F00"),
    "BOUNDARY": KindSpec(("label", "color", "visible", "line_width"), "#F0E442"),
    "DRILLHOLES": KindSpec(("label", "color", "transparency", "visible", "point_size", "labels"),
                           DRILLHOLE_NO_DATA_COLOR, legend_driven=True),
    "VOLUME_DIFFERENCE": KindSpec(("label", "transparency", "visible", "wire"), None, legend_driven=True),
    "COMPLIANCE_GRID": KindSpec(("label", "transparency", "visible", "wire"), None, legend_driven=True),
    "CLIENT_INTENTION": KindSpec(("label", "color", "visible", "line_width"), "#B340E6"),
    "CONSTRAINT": KindSpec(("label", "color", "visible", "line_width"), CONSTRAINT_SUBKINDS["untyped"], line_width="2.5"),
    "DESIGN": KindSpec(("label", "color", "transparency", "visible", "wire"), "#009E73"),
    "DESIGN_ENTITY": KindSpec(("label", "color", "transparency", "visible", "wire"), ENTITY_SUBKINDS["other"]),
}
"""Las propiedades y el predefinido de cada tipo (``kind``) de elemento."""

_SUBKINDS: dict[str, dict[str, str]] = {"DESIGN_ENTITY": ENTITY_SUBKINDS, "CONSTRAINT": CONSTRAINT_SUBKINDS}


@dataclass(frozen=True)
class LoaderPaint:
    """Lo que pinta un cargador: su constante, el tipo de elemento al que da el color y qué es."""

    loader: str
    kind: str
    what: str


INVENTORY: tuple[LoaderPaint, ...] = (
    LoaderPaint("entity_views.COLORS", "DESIGN_ENTITY", "color del objeto de cada tipo de entidad de diseño (ENTITY_SUBKINDS)"),
    LoaderPaint("constraint_views.INTENTION_STYLE", "CLIENT_INTENTION", "color, alambre y delante de lo demás de las intenciones"),
    LoaderPaint("constraints.styles.COLORS", "CONSTRAINT", "color por tipo de restricción (CONSTRAINT_SUBKINDS); grosor 2,5 px de la superposición"),
    LoaderPaint("des_views.CLASS_LEGEND", "DESIGN", "color por clase de cada cara de la clasificación de cantera (una leyenda)"),
    LoaderPaint("res_views._GRAY", "VOLUME_DIFFERENCE", "gris base y rampas por clase de la rejilla de diferencias (una leyenda)"),
    LoaderPaint("res_views._GRAY", "COMPLIANCE_GRID", "la rejilla de incumplimientos usa el color por clase de la de diferencias"),
    LoaderPaint("drillholes.model.DEFAULT_COLOR", "DRILLHOLES", "color de lo sin código o sin dato de los tubos y las barras"),
    LoaderPaint("drillholes.view_data.DEFAULT_RAMP", "DRILLHOLES", "rampa por defecto de las leyes (una leyenda por campo)"),
    LoaderPaint("(Blender)", "PROJECT_ANCHOR", "sin color propio: lo dibuja Blender"),
    LoaderPaint("(Blender)", "DTM", "sin color propio: lo dibuja Blender con el color del objeto"),
    LoaderPaint("(Blender)", "TIN", "sin color propio: lo dibuja Blender con el color del objeto"),
    LoaderPaint("(Blender)", "POINTS", "sin color propio: lo dibuja Blender con el color del objeto"),
    LoaderPaint("(Blender)", "BREAKLINES", "sin color propio: alambre de 1 px con el color del objeto"),
    LoaderPaint("(Blender)", "CONTOURS", "sin color propio: alambre de 1 px con el color del objeto"),
    LoaderPaint("(Blender)", "BOUNDARY", "sin color propio: alambre de 1 px con el color del objeto"),
    LoaderPaint("(Blender)", "DESIGN", "sin color propio la envolvente ni la superficie de diseño: color del objeto"),
)
"""Lo que pinta cada cargador, por tipo de elemento (el inventario de T02; lo usan T07 y T10)."""


def _spec(kind: str) -> KindSpec:
    try:
        return KINDS[kind]
    except KeyError:
        raise GeoblenderError(
            "core.appearance_unknown_kind", tr("it is not a type of element of the project"),
            obj=tr("Appearance of {kind}", kind=kind), field=tr("Type"), value=kind,
        ) from None


def allowed(kind: str) -> tuple[str, ...]:
    """Las propiedades de aspecto que ofrece el tipo ``kind``, en el orden de :data:`PROPERTIES`; solo las que
    ese tipo tiene (UI-13). ``GeoblenderError`` con un tipo que no es de un elemento del proyecto."""
    return _spec(kind).props


def legend_driven(kind: str) -> bool:
    """Si el color del tipo lo manda una leyenda (por clase o por campo) en vez de ser uno solo (D-8): el
    panel dice «coloreado por <leyenda>» y no lo deja editar donde ella manda."""
    return _spec(kind).legend_driven


def defaults_for(kind: str, subkind: str | None = None) -> Appearance:
    """El predefinido del tipo ``kind`` (D-11): una propiedad por cada una de :func:`allowed` salvo el rótulo
    (el predefinido de este es el nombre del dato). ``subkind`` afina el color de las entidades de diseño
    (``platform``, ``road``…) y de las restricciones (``legal_limit``…); sin él, el de «otra entidad» o
    el de lo sin tipo."""
    spec = _spec(kind)
    color = spec.color
    if subkind is not None:
        colors = _SUBKINDS.get(kind)
        if colors is None or subkind not in colors:
            raise GeoblenderError(
                "core.appearance_unknown_kind", tr("it is not a type of element of the project"),
                obj=tr("Appearance of {kind}", kind=kind), field=tr("Type"), value=subkind,
            )
        color = colors[subkind]
    values: list[tuple[str, str]] = []
    for prop in spec.props:
        if prop == "label":
            continue
        if prop == "color":
            assert color is not None, kind
            value = color
        elif prop == "line_width" and spec.line_width is not None:
            value = spec.line_width
        else:
            value = _STANDARD[prop]  # type: ignore[assignment]
        values.append((prop, value))
    return Appearance(kind, tuple(values))

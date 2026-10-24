# SPDX-License-Identifier: GPL-3.0-or-later
"""Mensajes de la cubicación (spec 011; plan 011 §5.1, §5.4 y §5.5; constitución,
principio 10).

Cada rechazo, aviso o nota que ``reserves`` puede mostrar tiene un **código** estable en
inglés con el prefijo ``res.`` (``"res.surfaces_mismatch"``), un ``msgid`` en inglés (también
su versión inglesa) y su texto en español, con marcadores de ``str.format`` con nombre en
inglés, los mismos en los dos. El texto nombra el objeto (la superficie, la capa, el
polígono, la unidad) y el valor, y dice qué hacer; el marcador ``{value}`` es siempre el valor
que se rechaza o se avisa (el ``value`` de :class:`ResError`).

- :class:`Message`: un mensaje del catálogo, con su gravedad (:data:`SEVERITIES`):
  ``"error"`` se lanza como :class:`ResError`; ``"warning"`` se informa (la cubicación sigue);
  ``"note"`` es un texto corto que acompaña a una fila de la tabla («sin densidad») o a un
  elemento de una lista (un polígono de ``res.domains_invalid``). :data:`CATALOG`, todos;
  :data:`MESSAGES`, por código.
- :data:`CATALOG_ES`: ``msgid`` → español, para ``core.i18n.install`` al registrar.
- :func:`render`: el texto de un código con sus valores, en español o en inglés.
- :class:`ResError`: el error para el usuario, con código, ``msgid``, valores (JSON), objeto,
  campo y valor (un ``GeoblenderError``).

Las cotas, las áreas y los volúmenes de un mensaje llegan ya escritos como texto
(``core.i18n.format_number``: coma decimal y espacio fino de miles); los demás números, como
números, y :func:`render` los escribe en el formato del idioma (:func:`gis.messages.format_value`).
Un detalle que compone quien lanza el error (la diferencia entre dos rejillas de
``gis.grid``), en español, como en la 006. Las tareas siguientes de la 011 añaden aquí los
códigos que necesiten.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from ..core.errors import GeoblenderError
from ..core.i18n import LANGUAGES
from ..gis.messages import MISSING_VALUE, JsonScalar, format_value, json_value

__all__ = [
    "CATALOG",
    "CATALOG_ES",
    "MESSAGES",
    "SEVERITIES",
    "Message",
    "ResError",
    "lookup",
    "render",
]

SEVERITIES = ("error", "warning", "note")
"""Las gravedades de un mensaje: se lanza, se informa o acompaña a una fila o a una lista."""

_MATERIALS_EN = "Volumetrics ▸ Materials and densities…"
_MATERIALS_ES = "Cubicación ▸ Materiales y densidades…"


@dataclass(frozen=True, slots=True)
class Message:
    """Un mensaje del catálogo: código ``res.*``, ``msgid`` en inglés, texto en español y
    gravedad (una de :data:`SEVERITIES`)."""

    code: str
    msgid: str
    es: str
    severity: str = "error"


CATALOG: tuple[Message, ...] = (
    # Las superficies y su compatibilidad (A1; RF-011-02, RF-011-03) ------------------------
    Message(
        "res.surfaces_mismatch",
        "«{surface}» and «{other}» cannot be measured against each other: {detail}. Bring the "
        "surface to the project grid (Topography ▸ Project grid from a DTM…).",
        "No se pueden cubicar «{surface}» y «{other}»: {detail}. Lleve la superficie a la "
        "rejilla del proyecto (Topografía ▸ Rejilla de proyecto desde un MDT…).",
    ),
    Message(
        "res.surface_other_version",
        "«{surface}» belongs to version {version}, which is neither the active version "
        "({active}) nor the one it starts from: choose a surface of the project, of the "
        "active version or frozen in the revision it starts from.",
        "«{surface}» es de la versión {version}, que no es la activa ({active}) ni aquella de "
        "la que parte: elija una superficie del proyecto, de la versión activa o congelada en "
        "la revisión de la que parte.",
    ),
    Message(
        "res.surface_is_tin",
        "«{surface}» is a TIN: bring it to the grid first (Topography ▸ DTM ⇄ TIN…); a "
        "volumetric computation does not resample any surface.",
        "«{surface}» es un TIN: llévelo antes a la rejilla (Topografía ▸ MDT ⇄ TIN…); una "
        "cubicación no remuestrea ninguna superficie.",
    ),
    Message(
        "res.surfaces_no_grid",
        "«{surface}» and «{other}» are both constant elevations: at least one of the two "
        "surfaces has to be a grid of the project, whose cells are measured.",
        "«{surface}» y «{other}» son las dos cotas constantes: al menos una de las dos "
        "superficies ha de ser una rejilla del proyecto, cuyas celdas se cubican.",
    ),
    # Una banda: totales (A2; RF-011-01, §8 de la spec) -------------------------------------
    Message(
        "res.same_surface",
        "«{surface}» is both the starting and the final surface: every volume is zero.",
        "«{surface}» es a la vez la superficie de partida y la final: todos los volúmenes son "
        "cero.",
        "warning",
    ),
    Message(
        "res.no_common_cells",
        "No common cells with data: «{start}» and «{final}» have no cell with data in both "
        "(inside the scope, if there is one); nothing has been computed.",
        "Sin celdas comunes con dato: «{start}» y «{final}» no tienen ninguna celda con dato "
        "en las dos (dentro del ámbito, si lo hay); no se ha cubicado nada.",
    ),
    # Bancos (A4; RF-011-09, RF-008-03) ------------------------------------------------------
    Message(
        "res.bench_height_range",
        "Bench height: {value} m is outside its range {range}.",
        "Altura de banco: {value} m está fuera de su rango {range}.",
    ),
    Message(
        "res.bench_levels_not_increasing",
        "List of bench elevations: {value} comes after {previous} and is not greater; write "
        "the elevations in increasing order, without repeats.",
        "Lista de cotas de los bancos: {value} va después de {previous} y no es mayor; "
        "escriba las cotas en orden creciente, sin repetir.",
    ),
    Message(
        "res.bench_value_not_number",
        "{label}: «{value}» is not a number of metres; write it with digits and a decimal "
        "comma or point.",
        "{label}: «{value}» no es un número de metros; escríbalo con cifras y coma o punto "
        "decimal.",
    ),
    Message(
        "res.bench_value_missing",
        "{label}: the value is missing; write the bench height and the anchor elevation (m), "
        "or a list of elevations.",
        "{label}: falta el valor; escriba la altura de banco y la cota de anclaje (m), o una "
        "lista de cotas.",
    ),
    Message(
        "res.bench_levels_too_few",
        "List of bench elevations: «{value}» has fewer than two elevations; write at least "
        "two, separated by «;».",
        "Lista de cotas de los bancos: «{value}» tiene menos de dos cotas; escriba al menos "
        "dos, separadas por «;».",
    ),
    Message(
        "res.bench_both_ways",
        "Benches: write either the bench height and the anchor elevation or a list of "
        "elevations, not both.",
        "Bancos: escriba la altura de banco y la cota de anclaje o una lista de cotas, no las "
        "dos cosas.",
    ),
    # Dominios (A6; RF-011-07, RF-011-08) ----------------------------------------------------
    Message(
        "res.domains_invalid",
        "Domain layer «{layer}» cannot be used to split by «{attribute}»: {problems}. Correct "
        "it and import it again; nothing has been computed.",
        "La capa de dominios «{layer}» no sirve para repartir por «{attribute}»: {problems}. "
        "Corríjala y vuelva a importarla; no se ha cubicado nada.",
    ),
    Message(
        "res.scope_references_mismatch",
        "The scope layer «{layer}» is in {value}, not in the CRS of the project ({expected}): "
        "import it in the CRS of the project; nothing has been computed.",
        "La capa del ámbito «{layer}» está en {value}, no en el CRS del proyecto ({expected}): "
        "impórtela en el CRS del proyecto; no se ha cubicado nada.",
    ),
    Message(
        "res.domains_references_mismatch",
        "The domain layer «{layer}» is in {value}, not in the CRS of the project ({expected}): "
        "import it in the CRS of the project; nothing has been computed.",
        "La capa de dominios «{layer}» está en {value}, no en el CRS del proyecto "
        "({expected}): impórtela en el CRS del proyecto; no se ha cubicado nada.",
    ),
    Message(
        "res.domain_self_intersecting",
        "polygon {fid} («{domain}») intersects itself",
        "el polígono {fid} («{domain}») se corta a sí mismo",
        "note",
    ),
    Message(
        "res.domain_no_area",
        "polygon {fid} («{domain}») has no area",
        "el polígono {fid} («{domain}») no tiene área",
        "note",
    ),
    Message(
        "res.domain_hole_outside",
        "polygon {fid} («{domain}») has a hole outside its outer ring or inside another hole",
        "el polígono {fid} («{domain}») tiene un hueco fuera de su contorno o dentro de otro "
        "hueco",
        "note",
    ),
    Message(
        "res.domain_value_empty",
        "polygon {fid} has an empty «{attribute}»",
        "el polígono {fid} tiene vacío el campo «{attribute}»",
        "note",
    ),
    Message(
        "res.domain_overlap",
        "polygons {fid} («{domain}») and {other_fid} («{other_domain}») overlap over {area} m²",
        "los polígonos {fid} («{domain}») y {other_fid} («{other_domain}») se solapan en "
        "{area} m²",
        "note",
    ),
    # La columna de materiales (RF-011-11; D-18, D-23, D-24) ----------------------------------
    Message(
        "res.materials_invalid",
        "The material column is not valid: {problems}. Correct it in "
        f"{_MATERIALS_EN}.",
        f"La columna de materiales no es válida: {{problems}}. Corríjala en {_MATERIALS_ES}.",
    ),
    Message("res.materials_empty", "the column has no unit",
            "la columna no tiene ninguna unidad", "note"),
    Message("res.unit_name_empty", "«{unit}» has no name", "«{unit}» no tiene nombre", "note"),
    Message(
        "res.unit_code_invalid",
        "«{unit}» has the code «{code}», which is not valid (lower-case letters without "
        "accents, digits and «_», starting with a letter)",
        "«{unit}» tiene el código «{code}», que no vale (minúsculas sin tilde, cifras y «_», "
        "empezando por una letra)",
        "note",
    ),
    Message(
        "res.unit_code_repeated",
        "«{unit}» repeats the code «{code}» of another element of the column",
        "«{unit}» repite el código «{code}» de otro elemento de la columna",
        "note",
    ),
    Message(
        "res.unit_base_missing",
        "«{unit}» has no base surface: only the last unit has none",
        "«{unit}» no tiene superficie de base: solo la última unidad va sin base",
        "note",
    ),
    Message(
        "res.unit_last_with_base",
        "«{unit}» is the last unit and has no base: it reaches down to the final surface",
        "«{unit}» es la última unidad y va sin base: llega hasta la superficie final",
        "note",
    ),
    Message(
        "res.unit_last_anthropic",
        "«{unit}» is anthropic and cannot be the last unit, which has no base",
        "«{unit}» es antrópica y no puede ser la última unidad, que va sin base",
        "note",
    ),
    Message(
        "res.unit_thickness_missing",
        "«{unit}» is anthropic and has no thickness grid",
        "«{unit}» es antrópica y no tiene rejilla de espesores",
        "note",
    ),
    Message(
        "res.unit_components_missing",
        "«{unit}» is compound and has no components",
        "«{unit}» es compuesta y no tiene componentes",
        "note",
    ),
    Message(
        "res.unit_role_missing",
        "«{unit}» is neither useful nor waste: choose its role",
        "«{unit}» no es útil ni estéril: elija su papel",
        "note",
    ),
    # Unidades de la columna de materiales (A7; RF-011-12 a RF-011-14) -----------------------
    Message(
        "res.thickness_negative",
        "Thickness grid «{surface}» of unit «{unit}» has negative thicknesses (the smallest, "
        "{value} m): a thickness is 0 m or more; correct it and compute again.",
        "La rejilla de espesores «{surface}» de la unidad «{unit}» tiene espesores negativos "
        "(el menor, {value} m): un espesor es de 0 m o más; corríjala y vuelva a cubicar.",
    ),
    Message(
        "res.materials_missing",
        "The project has no material column to split the cut by units: define the materials "
        f"first ({_MATERIALS_EN}).",
        "El proyecto no tiene columna de materiales para repartir el desmonte por unidades: "
        f"defina antes los materiales ({_MATERIALS_ES}).",
    ),
    # Toneladas y relaciones (A8, A9; RF-011-15 a RF-011-18) --------------------------------
    Message(
        "res.percent_sum",
        "The percentages of the components of «{unit}» add up to {value} %, not 100 % (to two "
        f"decimals): correct them in {_MATERIALS_EN}; nothing has been computed.",
        "Los porcentajes de los componentes de «{unit}» suman {value} %, no 100 % (con dos "
        f"decimales): corríjalos en {_MATERIALS_ES}; no se ha calculado nada.",
    ),
    Message(
        "res.density_missing",
        "«{unit}» has volume and lacks parameter «{value}»: it has no tonnes and the "
        f"computation has no total tonnes (declare it in {_MATERIALS_EN}).",
        "«{unit}» tiene volumen y le falta el parámetro «{value}»: sale sin toneladas y la "
        f"cubicación, sin total de toneladas (declárelo en {_MATERIALS_ES}).",
        "warning",
    ),
    Message("res.note_no_density", "no density", "sin densidad", "note"),
    Message("res.note_no_swell", "no K", "sin K", "note"),
    Message("res.note_no_useful", "no useful material", "sin material útil", "note"),
    # Momentos de extracción (A13; RF-011-19) -------------------------------------------------
    Message(
        "res.stages_mismatch",
        "{quantity}: the sum of the stages ({sum} m³) differs from the direct computation "
        "«{direct}» ({direct_volume} m³) by {difference} m³ ({value} %), more than the "
        "tolerance of {tolerance} %; no figure has been adjusted.",
        "{quantity}: la suma de los momentos ({sum} m³) difiere de la cubicación directa "
        "«{direct}» ({direct_volume} m³) en {difference} m³ ({value} %), más que la tolerancia "
        "de {tolerance} %; no se ha ajustado ninguna cifra.",
        "warning",
    ),
    Message(
        "res.stages_materials_differ",
        "«{name}» does not use the same material column as «{direct}»: their units are not "
        "comparable.",
        "«{name}» no usa la misma columna de materiales que «{direct}»: sus unidades no son "
        "comparables.",
        "warning",
    ),
    Message("res.note_stages_no_direct", "no volume in the direct computation",
            "sin volumen en la cubicación directa", "note"),
    Message("res.note_stages_over_tolerance", "above the tolerance", "más que la tolerancia",
            "note"),
    # Factor combinado (A14; D-4 de la spec, D-34) ------------------------------------------
    Message(
        "res.note_no_scale_factor",
        "Combined factor: not available",
        "Factor combinado: no disponible",
        "note",
    ),
    # Exportar (D-29; RF-011-24, RF-011-05) --------------------------------------------------
    Message(
        "res.cubication_unknown",
        "There is no cubication «{value}» in {version}: compute it first (Volumetrics ▸ "
        "Volume between two surfaces…); nothing has been written.",
        "No hay ninguna cubicación «{value}» en {version}: cubíquela antes (Cubicación ▸ "
        "Cubicar entre dos superficies…); no se ha escrito nada.",
    ),
    Message(
        "res.difference_unknown",
        "There is no difference grid «{value}» in {version}; nothing has been written.",
        "No hay ninguna rejilla de diferencias «{value}» en {version}; no se ha escrito nada.",
    ),
    Message(
        "res.export_read_only_project",
        "The project «{project}» is open read-only: export «{value}» outside the project; "
        "nothing has been written.",
        "El proyecto «{project}» está abierto en solo lectura: exporte «{value}» fuera del "
        "proyecto; no se ha escrito nada.",
    ),
)

MESSAGES: Mapping[str, Message] = MappingProxyType({m.code: m for m in CATALOG})
"""El catálogo por código (solo lectura)."""

CATALOG_ES: Mapping[str, str] = MappingProxyType({m.msgid: m.es for m in CATALOG})
"""``msgid`` → texto en español, para ``core.i18n.install`` (solo lectura)."""


def _check_catalog() -> None:
    """Un catálogo incoherente es un error del programa: códigos o ``msgid`` repetidos, un
    código que no es ``res.*`` o una gravedad desconocida."""
    if len(MESSAGES) != len(CATALOG) or len(CATALOG_ES) != len(CATALOG):
        raise ValueError("códigos o msgid repetidos en el catálogo de la cubicación")
    for message in CATALOG:
        if not message.code.startswith("res.") or message.severity not in SEVERITIES:
            raise ValueError(f"mensaje de la cubicación mal declarado: «{message.code}»")


_check_catalog()


def lookup(code: str) -> Message:
    """El mensaje de ``code``; :class:`ValueError` si no está en el catálogo (un error del
    programa: todo mensaje de ``res`` tiene aquí su texto en español)."""
    message = MESSAGES.get(code)
    if message is None:
        raise ValueError(
            f"el código de mensaje «{code}» no está en el catálogo de la cubicación "
            "(reserves/messages.py)"
        )
    return message


def render(code: str, /, *, language: str = "es", **values: object) -> str:
    """El texto de ``code`` con ``values`` en sus marcadores, en ``language`` (``"es"`` o
    ``"en"``, el ``msgid``). El marcador sin valor queda «?»; los valores que sobran se
    ignoran. Los decimales salen con coma en español y con punto en inglés."""
    if language not in LANGUAGES:
        raise ValueError(f"el idioma «{language}» no es de Geoblender: {', '.join(LANGUAGES)}")
    message = lookup(code)
    template = message.es if language == "es" else message.msgid
    shown = _Shown({name: format_value(value, language) for name, value in values.items()})
    return template.format_map(shown)


class ResError(GeoblenderError):
    """Error de la cubicación para el usuario: ``code`` del catálogo, ``msgid``, ``values``
    (JSON, para el registro y para mostrarlo en otro idioma con :func:`render`), el objeto,
    el campo y el valor (``GeoblenderError``) y ``text`` en español, que es también
    ``str(error)`` y ``message``. El valor es también el marcador ``{value}`` del texto. Un
    código de aviso o de nota no es un error: :class:`ValueError`."""

    def __init__(
        self,
        code: str,
        /,
        *,
        obj: str,
        field: str,
        value: object = None,
        **values: object,
    ) -> None:
        message = lookup(code)
        if message.severity != "error":
            raise ValueError(f"«{code}» es un {message.severity}, no un error: no se lanza")
        shown = {"value": value, **values}
        self.msgid = message.msgid
        self.values: dict[str, JsonScalar] = {k: json_value(v) for k, v in shown.items()}
        self.text = render(code, **shown)
        super().__init__(code, self.text, obj=obj, field=field, value=value,
                         context=self.values)
        self.args = (self.text,)


class _Shown(dict[str, str]):
    """Valores ya presentados; el que falta se ve como «?» (nunca el marcador ``{…}``)."""

    def __missing__(self, key: str) -> str:
        return MISSING_VALUE

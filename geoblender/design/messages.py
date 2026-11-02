# SPDX-License-Identifier: GPL-3.0-or-later
"""Mensajes del diseño (spec 013; plan 013 §5.1, §5.3.1 y §5.5; constitución, principio 10).

Cada rechazo, aviso o nota que ``design`` puede mostrar tiene un **código** estable en inglés con
el prefijo ``des.`` (``"des.profile_value_range"``), un ``msgid`` en inglés (también su versión
inglesa) y su texto en español, con marcadores de ``str.format`` con nombre en inglés, los mismos
en los dos. El texto nombra el objeto (el perfil, el sector), el campo (la clave del parámetro) y
el valor, y dice qué hacer; el marcador ``{value}`` es siempre el valor que se rechaza (el
``value`` de :class:`DesignError`) y ``{field}``, su campo.

- :class:`Message`: un mensaje del catálogo, con su gravedad (:data:`SEVERITIES`): ``"error"`` se
  lanza como :class:`DesignError`; ``"warning"`` se informa (el cálculo sigue); ``"note"`` es un
  texto corto que acompaña a una fila de una tabla o a un elemento de una lista. :data:`CATALOG`,
  todos; :data:`MESSAGES`, por código.
- :data:`CATALOG_ES`: ``msgid`` → español, para ``core.i18n.install`` al registrar.
- :func:`render`: el texto de un código con sus valores, en español o en inglés.
- :class:`DesignError`: el error para el usuario, con código, ``msgid``, valores (JSON), objeto,
  campo y valor (un ``GeoblenderError``).

Las cifras de un mensaje llegan ya redondeadas como números (:func:`render` los escribe en el
formato del idioma: coma decimal en español, punto en inglés). Cada tarea de la spec añade aquí los
códigos que necesite (semillas, sectores, envolventes…): los de los perfiles de banco
(RF-013-19, RF-013-20), el del talud impuesto por sector (RF-013-08), los de las superficies y las
zonas de un cálculo (RF-013-01, RF-013-16) y los de las semillas, el dominio de trabajo y lo que
dice la vista previa (RF-013-01 a RF-013-03). Un campo que es un texto de una lista cerrada que la
persona ve (el papel de una superficie, el tipo de geometría de una capa) llega ya en el idioma
de quien lo llama: ``render`` no lo traduce.
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
    "DesignError",
    "Message",
    "lookup",
    "render",
]

SEVERITIES = ("error", "warning", "note")
"""Las gravedades de un mensaje: se lanza, se informa o acompaña a una fila o a una lista."""


@dataclass(frozen=True, slots=True)
class Message:
    """Un mensaje del catálogo: código ``des.*``, ``msgid`` en inglés, texto en español y
    gravedad (una de :data:`SEVERITIES`)."""

    code: str
    msgid: str
    es: str
    severity: str = "error"


CATALOG: tuple[Message, ...] = (
    # Perfiles de banco (RF-013-18, RF-013-19, RF-013-20; D-7, D-17) ---------------------------
    Message(
        "des.profile_name_missing",
        "Bench profile «{profile}» has no name; give it one, for example EXPL_10_60_6.",
        "El perfil de banco «{profile}» no tiene nombre; póngale uno, por ejemplo EXPL_10_60_6.",
    ),
    Message(
        "des.profile_name_repeated",
        "Bench profile «{profile}» has the name «{value}», which profile «{other}» already "
        "has; give each profile its own name.",
        "El perfil de banco «{profile}» se llama «{value}», como el perfil «{other}»; dé a cada "
        "perfil su propio nombre.",
    ),
    Message(
        "des.profile_value_missing",
        "Bench profile «{profile}»: «{field}» has no value and has no default; declare it in "
        "Design ▸ Parameters ▸ Bench profiles… before calculating.",
        "Perfil de banco «{profile}»: «{field}» no tiene valor ni lleva ninguno por defecto; "
        "declárelo en Diseño ▸ Parámetros ▸ Perfiles de banco… antes de calcular.",
    ),
    Message(
        "des.profile_value_range",
        "Bench profile «{profile}»: «{field}» = {value} is outside its range {range}; nothing "
        "is calculated with this profile.",
        "Perfil de banco «{profile}»: «{field}» = {value} está fuera de su rango {range}; no se "
        "calcula nada con este perfil.",
    ),
    Message(
        "des.profile_unresolved",
        "Bench profile «{profile}» is not resolved by the grid: in plan its face takes "
        "{face} m and its berm {berm} m, and the grid step is {step} m; a face or a berm "
        "narrower than a cell cannot be drawn.",
        "El perfil de banco «{profile}» no está resuelto por la rejilla: en planta su cara ocupa "
        "{face} m y su berma {berm} m, y el paso de la rejilla es {step} m; una cara o una berma "
        "más estrecha que una celda no se puede dibujar.",
        "warning",
    ),
    # Talud general máximo impuesto por un sector (RF-013-08; ADR-0029) ------------------------
    Message(
        "des.sector_slope_range",
        "Sector «{sector}»: the maximum general slope «{field}» = {value} is outside its range "
        "{range}.",
        "Sector «{sector}»: el talud general máximo «{field}» = {value} está fuera de su rango "
        "{range}.",
    ),
    # Superficies y zonas de un cálculo (RF-013-01, RF-013-16; T03) ----------------------------
    Message(
        "des.surface_mismatch",
        "«{surface}» ({role}) is not on the project grid: {detail} (project against surface; "
        "«{field}» of the surface = {value}). Bring it to the project grid with Topography ▸ "
        "Surfaces ▸ Project grid from a DTM… before calculating; nothing is calculated or "
        "recorded.",
        "«{surface}» ({role}) no está en la rejilla del proyecto: {detail} (proyecto frente a "
        "superficie; «{field}» de la superficie = {value}). Llévela a la rejilla del proyecto "
        "con Topografía ▸ Superficies ▸ Rejilla de proyecto desde un MDT… antes de calcular; no "
        "se calcula ni se registra nada.",
    ),
    Message(
        "des.surface_is_tin",
        "«{surface}» is a TIN: bring it to a grid first with Topography ▸ Surfaces ▸ "
        "DTM ⇄ TIN…; an envelope does not resample any surface.",
        "«{surface}» es un TIN: llévelo antes a una rejilla con Topografía ▸ Superficies ▸ "
        "MDT ⇄ TIN…; una envolvente no remuestrea ninguna superficie.",
    ),
    Message(
        "des.surface_other_version",
        "«{surface}» belongs to version {version}, not to the active version ({active}): "
        "choose a surface of the project or of the active version.",
        "«{surface}» es de la versión {version}, no de la activa ({active}): elija una "
        "superficie del proyecto o de la versión activa.",
    ),
    Message(
        "des.zone_unknown",
        "Zone «{zone}» is not among the zones of the compiled masks: choose a constraint that "
        "has a zone in Design ▸ Legal limits and constraints ▸ Constraints… or compile the "
        "masks again.",
        "La zona «{zone}» no está entre las de las máscaras compiladas: elija una restricción "
        "que tenga zona en Diseño ▸ Límites y restricciones ▸ Restricciones… o compile de "
        "nuevo las máscaras.",
    ),
    Message(
        "des.layer_not_polygons",
        "Layer «{layer}» holds {value}, not polygons: the cells of a zone come from a polygon "
        "layer of the project.",
        "La capa «{layer}» tiene {value}, no polígonos: las celdas de una zona salen de una "
        "capa de polígonos del proyecto.",
    ),
    # Semillas y dominio de trabajo (RF-013-01, RF-013-02; T04) --------------------------------
    Message(
        "des.seed_missing",
        "The {kind} seeds need «{field}»: choose it in Design ▸ Quarry ▸ Envelopes and "
        "benching… before calculating.",
        "Las semillas de tipo «{kind}» necesitan «{field}»: elíjalo en Diseño ▸ Cantera ▸ "
        "Envolventes y escalonado… antes de calcular.",
    ),
    Message(
        "des.seed_elevation",
        "The fixed elevation of the seeds «{field}» = {value} is not a finite number of metres; "
        "give a real elevation.",
        "La cota fija de las semillas «{field}» = {value} no es un número finito de metros; "
        "dé una cota real.",
    ),
    Message(
        "des.sector_unknown",
        "Sector «{value}» is not one of the search sectors of the project; choose one of "
        "{known} or declare the sectors again in Design ▸ Parameters ▸ Design sectors….",
        "El sector «{value}» no es uno de los sectores de búsqueda del proyecto; elija uno de "
        "{known} o declare de nuevo los sectores en Diseño ▸ Parámetros ▸ Sectores de diseño….",
    ),
    # Lo que dice la vista previa (RF-013-03; T04): notas y avisos, nunca se lanzan ------------
    Message(
        "des.preview_seeds",
        "Seeds: {cells} cells ({area} m²), elevations {low} to {high} m; work domain: "
        "{hectares} ha; {outside} seed cells outside the work domain.",
        "Semillas: {cells} celdas ({area} m²), cotas {low} a {high} m; dominio: {hectares} ha; "
        "{outside} celdas de semilla fuera del dominio.",
        "note",
    ),
    Message(
        "des.preview_seeds_none",
        "Seeds: none, no cell has a finite elevation; work domain: {hectares} ha. Nothing can be "
        "calculated without seeds.",
        "Semillas: ninguna, ninguna celda tiene una cota finita; dominio: {hectares} ha. No se "
        "puede calcular sin semillas.",
        "warning",
    ),
    Message(
        "des.preview_domain",
        "Work domain: {cells} cells ({area} m²), {coverage} % of it with a seed.",
        "Dominio de trabajo: {cells} celdas ({area} m²), {coverage} % con semilla.",
        "note",
    ),
    Message(
        "des.preview_domain_empty",
        "The work domain is empty: the default domain of the masks, the fill-only strip and the "
        "chosen sectors or layer have no cell in common. Nothing can be calculated.",
        "El dominio de trabajo está vacío: el dominio por defecto de las máscaras, la franja de "
        "solo relleno y los sectores o la capa elegidos no tienen ninguna celda en común. No se "
        "puede calcular nada.",
        "warning",
    ),
    Message(
        "des.seeds_outside_domain",
        "{cells} seed cells ({area} m²) are outside the work domain: the envelope uses them but "
        "nothing is delivered there. Check the seed zone before calculating.",
        "{cells} celdas de semilla ({area} m²) están fuera del dominio de trabajo: la envolvente "
        "las usa, pero allí no se entrega nada. Revise la zona de las semillas antes de calcular.",
        "warning",
    ),
    Message(
        "des.seeds_without_data",
        "{cells} cells ({area} m²) of the seed zone have no finite elevation in «{surface}» and "
        "are not seeds.",
        "{cells} celdas ({area} m²) de la zona de las semillas no tienen una cota finita en "
        "«{surface}» y no son semillas.",
        "warning",
    ),
    Message(
        "des.preview_sectors",
        "Sectors the work domain touches: {sectors}.",
        "Sectores que toca el dominio de trabajo: {sectors}.",
        "note",
    ),
    Message(
        "des.preview_sector_pending",
        "Sector «{sector}»: untouchables search pending; nothing is calculated while the work "
        "domain touches it. Search in Design ▸ Legal limits and constraints ▸ Search "
        "untouchable elements by sector….",
        "Sector «{sector}»: búsqueda de intocables pendiente; no se calcula nada mientras el "
        "dominio de trabajo lo toque. Búsqueda en Diseño ▸ Límites y restricciones ▸ Buscar "
        "elementos intocables por sector….",
        "warning",
    ),
    Message(
        "des.preview_unassigned",
        "{cells} cells of the work domain ({area} m²) belong to no sector; they use the base "
        "profile.",
        "{cells} celdas del dominio de trabajo ({area} m²) no son de ningún sector; usan el "
        "perfil base.",
        "note",
    ),
    Message(
        "des.preview_masks_current",
        "Masks of {version}: up to date.",
        "Máscaras de {version}: al día.",
        "note",
    ),
    Message(
        "des.preview_masks_missing",
        "The masks of {version} have not been compiled, so the work domain cannot be shown; "
        "they are compiled before calculating (Design ▸ Legal limits and constraints ▸ "
        "Constraints…).",
        "Las máscaras de {version} no se han compilado, así que no se puede mostrar el dominio "
        "de trabajo; se compilan antes de calcular (Diseño ▸ Límites y restricciones ▸ "
        "Restricciones…).",
        "warning",
    ),
    Message(
        "des.preview_masks_stale",
        "The masks of {version} are stale: a constraint, a sector, a search or a parameter "
        "changed after compiling them, so the work domain cannot be shown; they are compiled "
        "again before calculating.",
        "Las máscaras de {version} están obsoletas: cambió una restricción, un sector, una "
        "búsqueda o un parámetro después de compilarlas, así que no se puede mostrar el dominio "
        "de trabajo; se compilan de nuevo antes de calcular.",
        "warning",
    ),
)

MESSAGES: Mapping[str, Message] = MappingProxyType({m.code: m for m in CATALOG})
"""Los mensajes por código (solo lectura)."""

CATALOG_ES: Mapping[str, str] = MappingProxyType({m.msgid: m.es for m in CATALOG})
"""``msgid`` → texto en español, para ``core.i18n.install`` (solo lectura)."""


def _check_catalog() -> None:
    """Un catálogo incoherente es un error del programa: códigos o ``msgid`` repetidos, un
    código que no es ``des.*`` o una gravedad desconocida."""
    if len(MESSAGES) != len(CATALOG) or len(CATALOG_ES) != len(CATALOG):
        raise ValueError("códigos o msgid repetidos en el catálogo del diseño")
    for message in CATALOG:
        if not message.code.startswith("des.") or message.severity not in SEVERITIES:
            raise ValueError(f"mensaje del diseño mal declarado: «{message.code}»")


_check_catalog()


def lookup(code: str) -> Message:
    """El mensaje de ``code``; :class:`ValueError` si no está en el catálogo (un error del
    programa: todo mensaje de ``design`` tiene aquí su texto en español)."""
    message = MESSAGES.get(code)
    if message is None:
        raise ValueError(
            f"el código de mensaje «{code}» no está en el catálogo del diseño "
            "(design/messages.py)"
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


class DesignError(GeoblenderError):
    """Error del diseño para el usuario: ``code`` del catálogo, ``msgid``, ``values`` (JSON, para
    el registro y para mostrarlo en otro idioma con :func:`render`), el objeto, el campo y el valor
    (``GeoblenderError``) y ``text`` en español, que es también ``str(error)`` y ``message``. El
    valor es el marcador ``{value}`` del texto y el campo, ``{field}``. Un código de aviso o de
    nota no es un error: :class:`ValueError`."""

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
        shown = {"field": field, "value": value, **values}
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

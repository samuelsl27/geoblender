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
  campo y valor (un ``GeoblenderError``) y, si las lleva, las notas que lo acompañan (T47).

Las cifras de un mensaje llegan ya redondeadas como números (:func:`render` los escribe en el
formato del idioma: coma decimal en español, punto en inglés). Cada tarea de la spec añade aquí los
códigos que necesite (semillas, sectores, envolventes…): los de los perfiles de banco
(RF-013-19, RF-013-20), el del talud impuesto por sector (RF-013-08), los de las superficies y las
zonas de un cálculo (RF-013-01, RF-013-16) y los de las semillas, el dominio de trabajo y lo que
dice la vista previa (RF-013-01 a RF-013-03) y los del rechazo y la marca de un sector con la
búsqueda de intocables pendiente (RF-013-05, RF-013-06), los de la comprobación de cada
envolvente (RF-013-15), los que la rechazan antes de calcular (RF-013-14, RF-013-16), el aviso de
la regularización entre sectores que baja la envolvente (RF-013-26, RF-013-30) y los de exportar
una rejilla a GeoTIFF (RF-013-34). Los de la 014 (plan 014 §5.1, T02) van al final, por
familias: ``des.quarry_*`` (sus parámetros, el recinto, las semillas, las capas, las dos
superficies y «explotación hasta la final»), ``des.floor_*``, ``des.conserve_*``,
``des.corridor_*``, ``des.edge_*``, ``des.fill_only_*`` y ``des.refit_*``. Los de las entidades de
diseño de la 015 (T02, plan 015 §5.1) van detrás de los de la 014: ``des.entity_*`` (el marco
común: nombre, parámetros, partida, falta de dato, lo que no se mueve) y ``des.platform_*`` (la
plataforma: su geometría, su rasante, su contrapendiente y lo que deja fuera de ella). Los de la 016
(plan 016 §5.1, T02) empiezan por ``des.chainless_start`` (nadie parte de la superficie de una entidad de un
tipo sin cadena; va aparte de ``des.entity_*``, que es la familia cerrada de la 015) y siguen, por familias y detrás
de los de la 015 (T03; RF-016-04 a 07, 12 a 15, 18 a 22), ``des.stockpile_*`` (la detección de acopios: el acopio que se
rechaza o se avisa, con su marca y su lugar), ``des.removal_*`` (la retirada, su pared y lo que se le apoya),
``des.buttress_*`` y ``des.body_*``, con el motivo de la restricción que declara cada tipo y la causa de «apoyo
retirado». Un campo
que es un texto de una lista cerrada que la persona ve (el papel de una superficie, el tipo de
geometría de una capa) llega ya en el idioma de quien lo llama: ``render`` no lo traduce; por
eso, lo que cambia con el idioma va en otro código (las partes que vacían el recinto, notas detrás
de ``des.quarry_area_empty``) y un mensaje que cuenta algo lleva su singular (``Message.count``,
T51: «en 1 zona», no «en 1 zonas»).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from ..core.errors import GeoblenderError
from ..core.i18n import LANGUAGES, placeholders
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
    gravedad (una de :data:`SEVERITIES`).

    Un mensaje que cuenta algo («en {zones} zonas») puede llevar su texto **en singular** (spec
    014, T51): ``count`` es el marcador del número y ``one_msgid`` y ``one_es``, el texto en
    inglés y en español cuando ese número es 1 («en 1 zona»), con los mismos marcadores que el
    plural; :func:`render` elige uno u otro."""

    code: str
    msgid: str
    es: str
    severity: str = "error"
    count: str = ""
    one_msgid: str = ""
    one_es: str = ""

    def templates(self, value: object = None) -> tuple[str, str]:
        """El ``msgid`` y el español que corresponden al número ``value`` de su marcador
        ``count``: los del singular si el mensaje lo tiene y ``value`` es 1; si no, los de
        siempre."""
        if self.count and value == 1 and not isinstance(value, bool):
            return self.one_msgid, self.one_es
        return self.msgid, self.es


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
    # Sectores con la búsqueda de intocables pendiente (RF-013-05, RF-013-06; T05) -------------
    Message(
        "des.sector_pending",
        "The work domain touches sectors with no current search for untouchables: {value}. "
        "Nothing is calculated or recorded until they are searched; search in Design ▸ Legal "
        "limits and constraints ▸ Find untouchable elements by sector….",
        "El dominio de trabajo toca sectores sin búsqueda de intocables vigente: {value}. No se "
        "calcula ni se registra nada hasta que se busquen; búsqueda en Diseño ▸ Límites y "
        "restricciones ▸ Buscar elementos intocables por sector….",
    ),
    Message(
        "des.sector_pending_mark",
        "Untouchables search pending in {sector}.",
        "Búsqueda de intocables pendiente en {sector}.",
        "warning",
    ),
    # La comprobación de cada envolvente (RF-013-15; T06): fallos del programa, nada se entrega -
    Message(
        "des.envelope_not_fixed_point",
        "Envelope «{envelope}» is not a fixed point: using it as a seed would still change the "
        "cell in row {row}, column {col} (x = {x} m, y = {y} m) by {value} m, more than "
        "{tolerance} m. Nothing is delivered or recorded; this is a fault of the program, so "
        "report it with the log.",
        "La envolvente «{envelope}» no es un punto fijo: usarla como semilla aún cambiaría la "
        "celda de la fila {row}, columna {col} (x = {x} m, y = {y} m) en {value} m, más de "
        "{tolerance} m. No se entrega ni se registra nada; es un fallo del programa, así que "
        "avíselo con el registro.",
    ),
    Message(
        "des.envelope_seed_above",
        "Envelope «{envelope}»: the seed cell in row {row}, column {col} (x = {x} m, y = {y} m) "
        "ends {value} m above the elevation of its seed, {seed} m, and an ascending envelope "
        "must not pass its seeds. Nothing is delivered or recorded; this is a fault of the "
        "program, so report it with the log.",
        "Envolvente «{envelope}»: la celda de semilla de la fila {row}, columna {col} "
        "(x = {x} m, y = {y} m) queda {value} m por encima de la cota de su semilla, {seed} m, y "
        "una envolvente ascendente no puede pasar de sus semillas. No se entrega ni se registra "
        "nada; es un fallo del programa, así que avíselo con el registro.",
    ),
    Message(
        "des.envelope_seed_below",
        "Envelope «{envelope}»: the seed cell in row {row}, column {col} (x = {x} m, y = {y} m) "
        "ends {value} m below the elevation of its seed, {seed} m, and a descending envelope "
        "must not fall under its seeds. Nothing is delivered or recorded; this is a fault of the "
        "program, so report it with the log.",
        "Envolvente «{envelope}»: la celda de semilla de la fila {row}, columna {col} "
        "(x = {x} m, y = {y} m) queda {value} m por debajo de la cota de su semilla, {seed} m, y "
        "una envolvente descendente no puede bajar de sus semillas. No se entrega ni se registra "
        "nada; es un fallo del programa, así que avíselo con el registro.",
    ),
    # Lo que se rechaza antes de calcular una envolvente (RF-013-14, RF-013-16; T07) ------------
    Message(
        "des.slope_range",
        "Envelope «{envelope}»: the slope «{field}» = {value} is not a number of degrees from 0 "
        "(included) to 90 (excluded); fix it in Design ▸ Quarry ▸ Envelopes and benching… before "
        "calculating; nothing is calculated or recorded.",
        "Envolvente «{envelope}»: la pendiente «{field}» = {value} no es un número de grados de 0 "
        "(incluido) a 90 (excluido); corríjala en Diseño ▸ Cantera ▸ Envolventes y escalonado… "
        "antes de calcular; no se calcula ni se registra nada.",
    ),
    Message(
        "des.mesh_factor_range",
        "Envelope «{envelope}»: the mesh factor «{field}» = {value} must be a number greater "
        "than 0 and at most 1; fix it in Design ▸ Quarry ▸ Envelopes and benching… before "
        "calculating; nothing is calculated or recorded.",
        "Envolvente «{envelope}»: el factor de malla «{field}» = {value} debe ser un número mayor "
        "que 0 y como mucho 1; corríjalo en Diseño ▸ Cantera ▸ Envolventes y escalonado… antes "
        "de calcular; no se calcula ni se registra nada.",
    ),
    Message(
        "des.reach_range",
        "Envelope «{envelope}»: the reach «{field}» = {value} m must be a number of metres "
        "greater than 0 (leave it empty for no reach); fix it in Design ▸ Quarry ▸ Envelopes and "
        "benching… before calculating; nothing is calculated or recorded.",
        "Envolvente «{envelope}»: el alcance «{field}» = {value} m debe ser un número de metros "
        "mayor que 0 (déjelo vacío para no limitarlo); corríjalo en Diseño ▸ Cantera ▸ "
        "Envolventes y escalonado… antes de calcular; no se calcula ni se registra nada.",
    ),
    Message(
        "des.exact_needs_constant_slope",
        "Envelope «{envelope}»: the exact Euclidean metric only accepts a constant slope, not "
        "the slope by sectors («{field}» = {value}); choose the 5×5 chamfer metric or a "
        "constant slope in Design ▸ Quarry ▸ Envelopes and benching… before calculating; "
        "nothing is calculated or recorded.",
        "Envolvente «{envelope}»: la euclídea exacta solo admite una pendiente constante, no la "
        "de los sectores («{field}» = {value}); elija la métrica chamfer 5×5 o una pendiente "
        "constante en Diseño ▸ Cantera ▸ Envolventes y escalonado… antes de calcular; no se "
        "calcula ni se registra nada.",
    ),
    Message(
        "des.seeds_empty",
        "Envelope «{envelope}»: the seeds have no cell with a finite elevation («{field}» = "
        "{value} cells; {nodata} cells of their zone have none), so there is nothing to start "
        "from; choose another surface or zone for the seeds in Design ▸ Quarry ▸ Envelopes and "
        "benching… before calculating; nothing is calculated or recorded.",
        "Envolvente «{envelope}»: las semillas no tienen ninguna celda con cota finita "
        "(«{field}» = {value} celdas; {nodata} celdas de su zona no la tienen), así que no hay "
        "de dónde partir; elija otra superficie o zona de semillas en Diseño ▸ Cantera ▸ "
        "Envolventes y escalonado… antes de calcular; no se calcula ni se registra nada.",
    ),
    Message(
        "des.domain_empty",
        "Envelope «{envelope}»: the work domain is empty («{field}» = {value} cells): the "
        "default domain of the masks, the fill-only strip and the chosen sectors or layer have "
        "no cell in common, so nothing would be delivered; choose another bound («Bound to») "
        "in Design ▸ Quarry ▸ Envelopes and benching… or review the limits in Design ▸ Legal "
        "limits and constraints ▸ Constraints… before calculating; nothing is calculated or "
        "recorded.",
        "Envolvente «{envelope}»: el dominio de trabajo está vacío («{field}» = {value} "
        "celdas): el dominio por defecto de las máscaras, la franja de solo relleno y los "
        "sectores o la capa elegidos no tienen ninguna celda en común, así que no se entregaría "
        "nada; elija otro acotado («Acotar a») en Diseño ▸ Cantera ▸ Envolventes y escalonado… "
        "o revise los límites en Diseño ▸ Límites y restricciones ▸ Restricciones… antes de "
        "calcular; no se calcula ni se registra nada.",
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
        "domain touches it. Search in Design ▸ Legal limits and constraints ▸ Find "
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
    # El informe de un diseño (RF-013-30; T12): avisos y notas, nunca se lanzan ----------------
    Message(
        "des.no_movement",
        "The design does not move any cell by more than the minimum thickness of {thickness} m: "
        "it is the start surface. Check that the seeds are on the side of the surface that the "
        "calculation can reach (below it to cut, above it to fill) and that the work domain has "
        "cells where moving earth is admitted.",
        "El diseño no mueve ninguna celda más del espesor mínimo de {thickness} m: es la "
        "superficie de partida. Compruebe que las semillas están del lado de la superficie al "
        "que llega el cálculo (por debajo para cortar, por encima para rellenar) y que el "
        "dominio de trabajo tiene celdas donde se admite mover tierra.",
        "warning",
    ),
    Message(
        "des.edge_movement",
        "{cells} cells ({area} m²) with movement are on the edge of the grid, so the result is cut "
        "off by it and would go on beyond. Widen the project grid or review the seeds and the "
        "slope before creating the design.",
        "{cells} celdas ({area} m²) con movimiento están en el borde de la rejilla, así que el "
        "resultado queda cortado por ella y seguiría más allá. Amplíe la rejilla del proyecto o "
        "revise las semillas y la pendiente antes de crear el diseño.",
        "warning",
    ),
    Message(
        "des.slope_over_face",
        "{cells} cells with movement are steeper than the face of their profile plus the face "
        "tolerance; the worst is {max}° against a limit of {limit}° (face + {tolerance}°), at "
        "x = {x} m, y = {y} m. Check the profile, the mesh factor and the walls against the "
        "forbidden areas (the edge step).",
        "{cells} celdas con movimiento pasan de la cara de su perfil más la tolerancia de cara; "
        "la peor, {max}° frente a un límite de {limit}° (cara + {tolerance}°), en x = {x} m, "
        "y = {y} m. Revise el perfil, el factor de malla y las paredes contra lo prohibido (el "
        "salto en el borde).",
        "warning",
    ),
    Message(
        "des.regularization_lowered",
        "The regularization between sectors with different general slopes lowered the envelope "
        "by more than the tolerance in {cells} cells (by up to {drop} m; sectors: {sectors}), "
        "because there the envelope is steeper than {slope}°, the steepest general slope of the "
        "sectors involved. The stepped design follows the lowered envelope: in cut it can end up "
        "below the recorded envelope in those cells, and in fill it fills less than it. "
        "Calculate the envelope with «Slope of each sector» or raise the maximum general slope "
        "imposed on the sector.",
        "La regularización entre sectores con taludes generales distintos bajó la envolvente más "
        "que la tolerancia en {cells} celdas (hasta {drop} m; sectores: {sectors}), porque allí "
        "la envolvente es más empinada que {slope}°, el talud general más empinado de los "
        "sectores implicados. El escalonado sigue a la envolvente bajada: en corte puede quedar "
        "por debajo de la envolvente registrada en esas celdas y en relleno rellena menos que "
        "ella. Calcule la envolvente con «Talud de cada sector» o suba el talud general máximo "
        "impuesto del sector.",
        "warning",
    ),
    Message(
        "des.magnitude_cut",
        "The cut ({current} m³) is {ratio} times the {previous} m³ of «{operation}» in the "
        "frozen revision {revision}, above the warning threshold of {threshold} times. Check the "
        "seeds, the slope and the work domain.",
        "El desmonte ({current} m³) es {ratio} veces los {previous} m³ de «{operation}» en la "
        "revisión congelada {revision}, por encima del umbral de aviso de {threshold} veces. "
        "Revise las semillas, la pendiente y el dominio de trabajo.",
        "warning",
    ),
    Message(
        "des.magnitude_fill",
        "The fill ({current} m³) is {ratio} times the {previous} m³ of «{operation}» in the "
        "frozen revision {revision}, above the warning threshold of {threshold} times. Check the "
        "seeds, the slope and the work domain.",
        "El terraplén ({current} m³) es {ratio} veces los {previous} m³ de «{operation}» en la "
        "revisión congelada {revision}, por encima del umbral de aviso de {threshold} veces. "
        "Revise las semillas, la pendiente y el dominio de trabajo.",
        "warning",
    ),
    Message(
        "des.magnitude_no_reference",
        "No frozen revision of the version has an operation like «{operation}» (same type and "
        "name), so the cut and the fill are not compared with an earlier one.",
        "Ninguna revisión congelada de la versión tiene una operación como «{operation}» (mismo "
        "tipo y nombre), así que el desmonte y el terraplén no se comparan con uno anterior.",
        "note",
    ),
    # Registrar el resultado al confirmar (RF-013-04, RF-013-17, RF-013-31; T14) ---------------
    Message(
        "des.operation_name_repeated",
        "«{value}» is already the name of an operation of the design in {version}: its data "
        "«{dataset}» is alive. Choose another name, or recalculate that operation; nothing is "
        "calculated or recorded.",
        "«{value}» ya es el nombre de una operación del diseño en {version}: su dato "
        "«{dataset}» está vigente. Elija otro nombre, o recalcule esa operación; no se calcula "
        "ni se registra nada.",
    ),
    Message(
        "des.operation_name_repeated_project",
        "«{value}» is already the name of an operation of the design in the project: its data "
        "«{dataset}» is alive. Choose another name, or recalculate that operation; nothing is "
        "calculated or recorded.",
        "«{value}» ya es el nombre de una operación del diseño en el proyecto: su dato "
        "«{dataset}» está vigente. Elija otro nombre, o recalcule esa operación; no se calcula "
        "ni se registra nada.",
    ),
    Message(
        "des.input_changed",
        "«{value}» changed after the calculation started, so the result no longer matches it. "
        "Calculate again; nothing is recorded.",
        "«{value}» cambió después de empezar el cálculo, así que el resultado ya no le "
        "corresponde. Calcule de nuevo; no se registra nada.",
    ),
    # Recalcular y reproducir con lo que dicen los ajustes (RF-013-17, RF-013-21; T15) ---------
    Message(
        "des.profile_unassigned",
        "Sector {value} has no profile and imposes no slope, and the envelope uses the slope of "
        "each sector: assign it a profile (or a base profile) in Design ▸ Envelopes and "
        "benching…; nothing is calculated or recorded.",
        "El sector {value} no tiene perfil ni impone ningún talud, y la envolvente usa el talud de "
        "cada sector: asígnele un perfil (o un perfil base) en Diseño ▸ Envolventes y "
        "escalonado…; no se calcula ni se registra nada.",
    ),
    Message(
        "des.anchor_nodata",
        "The grid of anchors «{value}» has no elevation in {cells} cells of the stepped surface; "
        "every cell of the work domain needs an anchor. Use a grid that covers it, or the anchor "
        "of the profile; nothing is calculated or recorded.",
        "La rejilla de anclas «{value}» no tiene cota en {cells} celdas de la superficie que se "
        "escalona; cada celda del dominio de trabajo necesita un ancla. Use una rejilla que lo "
        "cubra, o el ancla del perfil; no se calcula ni se registra nada.",
    ),
    # Exportar a GeoTIFF (RF-013-34; T19) --------------------------------------------------------
    Message(
        "des.export_unknown",
        "Version {version} has no grid «{value}» of the design to export ({dataset}): choose an "
        "envelope, a design surface or a berm grid calculated in that version; nothing has been "
        "written.",
        "La versión {version} no tiene la rejilla «{value}» del diseño para exportar "
        "({dataset}): elija una envolvente, una superficie de diseño o una rejilla de bermas "
        "calculada en esa versión; no se ha escrito nada.",
    ),
    Message(
        "des.export_not_grid",
        "«{value}» is not a live grid of the design (an envelope, a design surface or a berm "
        "grid of a version): choose one in the view; nothing has been written.",
        "«{value}» no es una rejilla viva del diseño (una envolvente, una superficie de diseño "
        "o una rejilla de bermas de una versión): elíjala en la vista; no se ha escrito nada.",
    ),
    Message(
        "des.export_read_only_project",
        "The project «{project}» is open read-only: export «{value}» outside the project; "
        "nothing has been written.",
        "El proyecto «{project}» está abierto en solo lectura: exporte «{value}» fuera del "
        "proyecto; no se ha escrito nada.",
    ),
    # Cantera con dos superficies (spec 014, T02; plan 014 §5.1) ===============================
    # Sus parámetros (plan 014 §5.2.2; D-9) ----------------------------------------------------
    Message(
        "des.quarry_param_missing",
        "«{field}» has no value and has no default; declare it with its origin in Project ▸ "
        "Project parameters… before calculating.",
        "«{field}» no tiene valor ni lleva ninguno por defecto; declárelo con su origen en "
        "Proyecto ▸ Parámetros del proyecto… antes de calcular.",
    ),
    Message(
        "des.quarry_param_range",
        "«{field}» = {value} is outside its range {range}; change it in Project ▸ Project "
        "parameters… before calculating.",
        "«{field}» = {value} está fuera de su rango {range}; cámbielo en Proyecto ▸ Parámetros "
        "del proyecto… antes de calcular.",
    ),
    # Recinto, semillas y capas (RF-014-01 a RF-014-03; spec §7; plan §5.2.1) ------------------
    Message(
        "des.quarry_area_empty",
        "The excavation area of version {version} is empty: no cell is both admitted to cut by "
        "its masks and has terrain data. Review the limit and the constraints; nothing is "
        "calculated or recorded. What empties it:",
        "El recinto excavable de la versión {version} está vacío: ninguna celda tiene a la vez "
        "corte admitido por sus máscaras y dato de terreno. Revise el límite y las "
        "restricciones; no se calcula ni se registra nada. Lo que lo vacía:",
    ),
    # Lo que vacía el recinto, una nota por parte detrás del error (RF-014-01; T51) ----------
    Message(
        "des.quarry_area_outside_limit",
        "Action perimeter outside the legal limit: {area} m².",
        "Perímetro de actuación fuera del límite legal: {area} m².",
        "note",
    ),
    Message(
        "des.quarry_area_untouchable",
        "Untouchables and exclusions: {area} m².",
        "Intocables y exclusiones: {area} m².",
        "note",
    ),
    Message(
        "des.quarry_area_inner_band",
        "Buffer inside the limit: {area} m².",
        "Resguardo hacia dentro del límite: {area} m².",
        "note",
    ),
    Message(
        "des.quarry_area_no_cut",
        "Zones with no cut, fill only or restoration only: {area} m².",
        "Zonas sin corte, solo relleno o solo restauración: {area} m².",
        "note",
    ),
    Message(
        "des.quarry_area_no_terrain",
        "Cells without terrain data: {area} m².",
        "Celdas sin dato de terreno: {area} m².",
        "note",
    ),
    Message(
        "des.quarry_area_no_perimeter",
        "The action perimeter has no cell in the grid.",
        "El perímetro de actuación no tiene ninguna celda en la rejilla.",
        "note",
    ),
    Message(
        "des.quarry_seeds_outside",
        "{cells} seed cells ({area} m²) in {groups} groups fall outside the crown and the zones "
        "to hold: seeding there raises the floors. Confirm to calculate with them, or choose "
        "the seeds «Crown and zones to hold».",
        "{cells} celdas de semillas ({area} m²) en {groups} grupos caen fuera de la coronación y "
        "de las zonas a sostener: sembrar allí sube los fondos. Confirme para calcular con "
        "ellas, o elija las semillas «Coronación y zonas a sostener».",
        "warning",
        count="groups",
        one_msgid="{cells} seed cells ({area} m²) in {groups} group fall outside the crown and the "
        "zones to hold: seeding there raises the floors. Confirm to calculate with them, or "
        "choose the seeds «Crown and zones to hold».",
        one_es="{cells} celdas de semillas ({area} m²) en {groups} grupo caen fuera de la "
        "coronación y de las zonas a sostener: sembrar allí sube los fondos. Confirme para "
        "calcular con ellas, o elija las semillas «Coronación y zonas a sostener».",
    ),
    Message(
        "des.quarry_seed_group",
        "Group {group}: {cells} cells, {area} m², centre at x = {x} m, y = {y} m.",
        "Grupo {group}: {cells} celdas, {area} m², centro en x = {x} m, y = {y} m.",
        "note",
        count="cells",
        one_msgid="Group {group}: {cells} cell, {area} m², centre at x = {x} m, y = {y} m.",
        one_es="Grupo {group}: {cells} celda, {area} m², centro en x = {x} m, y = {y} m.",
    ),
    Message(
        "des.quarry_layer_field",
        "Layer «{layer}» has no numeric field «{value}»: choose one of its fields ({fields}); "
        "nothing is calculated.",
        "La capa «{layer}» no tiene el campo numérico «{value}»: elija uno de sus campos "
        "({fields}); no se calcula nada.",
    ),
    # Lo que dice la vista previa de la cantera (RF-014-04; T12): notas, nunca se lanzan --------
    Message(
        "des.quarry_preview_area",
        "Excavation area: {cells} cells ({area} m², {hectares} ha).",
        "Recinto excavable: {cells} celdas ({area} m², {hectares} ha).",
        "note",
        count="cells",
        one_msgid="Excavation area: {cells} cell ({area} m², {hectares} ha).",
        one_es="Recinto excavable: {cells} celda ({area} m², {hectares} ha).",
    ),
    Message(
        "des.quarry_preview_crown",
        "Crown: ring of {ring} cells outside the excavation area, {cells} cells ({area} m²).",
        "Coronación: anillo de {ring} celdas fuera del recinto, {cells} celdas ({area} m²).",
        "note",
        count="ring",
        one_msgid="Crown: ring of {ring} cell outside the excavation area, {cells} cells "
        "({area} m²).",
        one_es="Coronación: anillo de {ring} celda fuera del recinto, {cells} celdas ({area} m²).",
    ),
    Message(
        "des.quarry_preview_hold",
        "Zones to hold (untouchable and no cut): {cells} cells ({area} m²).",
        "Zonas a sostener (intocables y sin corte): {cells} celdas ({area} m²).",
        "note",
        count="cells",
        one_msgid="Zones to hold (untouchable and no cut): {cells} cell ({area} m²).",
        one_es="Zonas a sostener (intocables y sin corte): {cells} celda ({area} m²).",
    ),
    Message(
        "des.quarry_preview_floors",
        "Floors of «{layer}» («{field}»): {polygons} polygons, {cells} cells ({area} m²), "
        "elevations {low} to {high} m.",
        "Fondos de «{layer}» («{field}»): {polygons} polígonos, {cells} celdas ({area} m²), "
        "cotas {low} a {high} m.",
        "note",
        count="polygons",
        one_msgid="Floors of «{layer}» («{field}»): {polygons} polygon, {cells} cells ({area} m²), "
        "elevations {low} to {high} m.",
        one_es="Fondos de «{layer}» («{field}»): {polygons} polígono, {cells} celdas ({area} m²), "
        "cotas {low} a {high} m.",
    ),
    Message(
        "des.quarry_preview_ceilings",
        "Zones to conserve, which seed the conservation ceilings ({zones}): {cells} cells "
        "({area} m²).",
        "Zonas a conservar, que siembran los techos de conservación ({zones}): {cells} celdas "
        "({area} m²).",
        "note",
        count="cells",
        one_msgid="Zones to conserve, which seed the conservation ceilings ({zones}): {cells} cell "
        "({area} m²).",
        one_es="Zonas a conservar, que siembran los techos de conservación ({zones}): {cells} "
        "celda ({area} m²).",
    ),
    Message(
        "des.quarry_preview_corridors",
        "Corridors of «{layer}»: {corridors} lines, {cells} cells ({area} m²), {length} m of "
        "axis.",
        "Corredores de «{layer}»: {corridors} líneas, {cells} celdas ({area} m²), {length} m de "
        "eje.",
        "note",
        count="corridors",
        one_msgid="Corridors of «{layer}»: {corridors} line, {cells} cells ({area} m²), {length} m "
        "of axis.",
        one_es="Corredores de «{layer}»: {corridors} línea, {cells} celdas ({area} m²), {length} m "
        "de eje.",
    ),
    # La métrica de cada superficie (RF-014-12; T45): solo el chamfer 5×5 ---------------------
    Message(
        "des.quarry_final_exact",
        "Quarry «{quarry}»: the final surface asks for the exact Euclidean metric («{field}» = "
        "{value}), which only accepts a constant slope, and each surface of a quarry follows "
        "the slope of its sectors: use the 5×5 chamfer; nothing is calculated or recorded.",
        "Cantera «{quarry}»: la superficie final pide la euclídea exacta («{field}» = {value}), "
        "que solo admite una pendiente constante, y cada superficie de una cantera va con la "
        "pendiente de sus sectores: use el chamfer 5×5; no se calcula ni se registra nada.",
    ),
    Message(
        "des.quarry_exploitation_exact",
        "Quarry «{quarry}»: the exploitation surface asks for the exact Euclidean metric "
        "(«{field}» = {value}), which only accepts a constant slope, and each surface of a "
        "quarry follows the slope of its sectors: use the 5×5 chamfer; nothing is calculated or "
        "recorded.",
        "Cantera «{quarry}»: la superficie de explotación pide la euclídea exacta («{field}» = "
        "{value}), que solo admite una pendiente constante, y cada superficie de una cantera va "
        "con la pendiente de sus sectores: use el chamfer 5×5; no se calcula ni se registra "
        "nada.",
    ),
    # Las dos superficies y «explotación hasta la final» (RF-014-14, RF-014-17) ----------------
    Message(
        "des.quarry_order_broken",
        "Program error: at x = {x} m, y = {y} m the final surface ({final} m), the exploitation "
        "surface ({exploitation} m) and the terrain ({terrain} m) do not keep final ≤ "
        "exploitation ≤ terrain within 1 mm; nothing is created. Report it with the project.",
        "Error del programa: en x = {x} m, y = {y} m la superficie final ({final} m), la de "
        "explotación ({exploitation} m) y el terreno ({terrain} m) no cumplen final ≤ "
        "explotación ≤ terreno a 1 mm; no se crea nada. Comuníquelo con el proyecto.",
    ),
    # Una superficie de la cantera que no mueve nada (RF-014-12, RF-014-18; T61, el H3): se mide
    # sobre la superficie que se crea (con la regla de orden y «explotación hasta la final»), no
    # sobre el escalonado de un lado, y nombra la superficie (``des.no_movement`` es de la 013).
    Message(
        "des.quarry_final_no_movement",
        "The final surface of «{quarry}» does not move any cell by more than the minimum "
        "thickness of {thickness} m: it is the start surface. Check that its seeds are below "
        "the start surface and that the excavation boundary has cells where cutting is admitted.",
        "La superficie final de «{quarry}» no mueve ninguna celda más del espesor mínimo de "
        "{thickness} m: es la superficie de partida. Compruebe que sus semillas quedan por debajo "
        "de la superficie de partida y que el recinto excavable tiene celdas donde se admite "
        "cortar.",
        "warning",
    ),
    Message(
        "des.quarry_exploitation_no_movement",
        "The exploitation surface of «{quarry}» does not move any cell by more than the minimum "
        "thickness of {thickness} m: it is the start surface. Check that its seeds are below "
        "the start surface and that the excavation boundary has cells where cutting is admitted.",
        "La superficie de explotación de «{quarry}» no mueve ninguna celda más del espesor mínimo "
        "de {thickness} m: es la superficie de partida. Compruebe que sus semillas quedan por "
        "debajo de la superficie de partida y que el recinto excavable tiene celdas donde se "
        "admite cortar.",
        "warning",
    ),
    Message(
        "des.quarry_unsplit_zones",
        "The exploitation does not reach the final surface in {zones} zones: {area} ha and "
        "{volume} m³ of doubled surface over {threshold} m on unexploited terrain, in zones of "
        "more than {min_area} ha. Use «Exploitation down to the final» to lower it there with "
        "anchored benches.",
        "La explotación no llega a la final en {zones} zonas: {area} ha y {volume} m³ de "
        "desdoblado de más de {threshold} m sobre terreno sin explotar, en zonas de más de "
        "{min_area} ha. Use «Explotación hasta la final» para bajarla allí con bancos anclados.",
        "warning",
        count="zones",
        one_msgid="The exploitation does not reach the final surface in {zones} zone: {area} ha "
        "and {volume} m³ of doubled surface over {threshold} m on unexploited terrain, in a zone "
        "of more than {min_area} ha. Use «Exploitation down to the final» to lower it there with "
        "anchored benches.",
        one_es="La explotación no llega a la final en {zones} zona: {area} ha y {volume} m³ de "
        "desdoblado de más de {threshold} m sobre terreno sin explotar, en una zona de más de "
        "{min_area} ha. Use «Explotación hasta la final» para bajarla allí con bancos anclados.",
    ),
    Message(
        "des.quarry_unsplit_zone",
        "Zone {zone}: {area} ha, {volume} m³, centre at x = {x} m, y = {y} m.",
        "Zona {zone}: {area} ha, {volume} m³, centro en x = {x} m, y = {y} m.",
        "note",
    ),
    # Lo que queda tras «explotación hasta la final» en las zonas tratadas (T57, hallazgo F-19):
    # la cota de ancla inmediatamente por encima de la final deja menos de un banco y el aviso no
    # vuelve a ofrecer el modo (RF-014-17, RF-014-18).
    Message(
        "des.quarry_unsplit_remaining",
        "After «Exploitation down to the final», the exploitation still does not reach the final "
        "surface in {zones} zones within the treated ones: {area} ha and {volume} m³ of doubled "
        "surface over {threshold} m on unexploited terrain, in zones of more than {min_area} ha. "
        "It is less than one bench height: the mode does not go below the anchor level "
        "immediately above the final, and there that level leaves the terrain unexploited.",
        "Tras «Explotación hasta la final», la explotación sigue sin llegar a la final en {zones} "
        "zonas dentro de las tratadas: {area} ha y {volume} m³ de desdoblado de más de "
        "{threshold} m sobre terreno sin explotar, en zonas de más de {min_area} ha. Es menos de "
        "una altura de banco: el modo no baja de la cota de ancla inmediatamente por encima de la "
        "final, y allí esa cota deja el terreno sin explotar.",
        "warning",
        count="zones",
        one_msgid="After «Exploitation down to the final», the exploitation still does not reach "
        "the final surface in {zones} zone within the treated ones: {area} ha and {volume} m³ of "
        "doubled surface over {threshold} m on unexploited terrain, in a zone of more than "
        "{min_area} ha. It is less than one bench height: the mode does not go below the anchor "
        "level immediately above the final, and there that level leaves the terrain unexploited.",
        one_es="Tras «Explotación hasta la final», la explotación sigue sin llegar a la final en "
        "{zones} zona dentro de las tratadas: {area} ha y {volume} m³ de desdoblado de más de "
        "{threshold} m sobre terreno sin explotar, en una zona de más de {min_area} ha. Es menos "
        "de una altura de banco: el modo no baja de la cota de ancla inmediatamente por encima de "
        "la final, y allí esa cota deja el terreno sin explotar.",
    ),
    Message(
        "des.quarry_to_final",
        "«Exploitation down to the final» in {zones} zones ({area} ha): {volume} m³ pass from "
        "the doubled surface to the exploitation, with benches anchored at its levels.",
        "«Explotación hasta la final» en {zones} zonas ({area} ha): {volume} m³ pasan del "
        "desdoblado a la explotación, con bancos anclados a sus cotas.",
        "note",
        count="zones",
        one_msgid="«Exploitation down to the final» in {zones} zone ({area} ha): {volume} m³ pass "
        "from the doubled surface to the exploitation, with benches anchored at its levels.",
        one_es="«Explotación hasta la final» en {zones} zona ({area} ha): {volume} m³ pasan del "
        "desdoblado a la explotación, con bancos anclados a sus cotas.",
    ),
    # Fondos (RF-014-05, RF-014-06) -------------------------------------------------------------
    Message(
        "des.floor_overlap",
        "Layer «{layer}»: floor polygons {value} and {other} overlap in {cells} cells; correct "
        "the layer in QGIS (no level is chosen for them) and calculate again.",
        "Capa «{layer}»: los polígonos de fondo {value} y {other} se solapan en {cells} celdas; "
        "corrija la capa en QGIS (no se elige ninguna cota por ellos) y calcule de nuevo.",
        count="cells",
        one_msgid="Layer «{layer}»: floor polygons {value} and {other} overlap in {cells} cell; "
        "correct the layer in QGIS (no level is chosen for them) and calculate again.",
        one_es="Capa «{layer}»: los polígonos de fondo {value} y {other} se solapan en {cells} "
        "celda; corrija la capa en QGIS (no se elige ninguna cota por ellos) y calcule de nuevo.",
    ),
    Message(
        "des.floor_level",
        "Layer «{layer}», polygon {polygon}: «{field}» = {value} is missing or outside the "
        "terrain elevations ± 1 000 m ({low} to {high} m); correct it in QGIS (no level is "
        "chosen for it); nothing is calculated.",
        "Capa «{layer}», polígono {polygon}: «{field}» = {value} falta o está fuera de las cotas "
        "del terreno ± 1.000 m (de {low} a {high} m); corríjalo en QGIS (no se elige ninguna "
        "cota por él); no se calcula nada.",
    ),
    Message(
        "des.floor_above_terrain",
        "{area} m² of the floors are above the terrain: there is no cut there (the surface "
        "never goes above the terrain).",
        "{area} m² de los fondos quedan por encima del terreno: allí no hay corte (la "
        "superficie nunca supera el terreno).",
        "warning",
    ),
    # Zonas a conservar (RF-014-07, RF-014-08) --------------------------------------------------
    Message(
        "des.conserve_moved",
        "The design moves {volume} m³ inside the zones to conserve, in {parts} parts: it is an "
        "error of the design; it is not created.",
        "El diseño mueve {volume} m³ dentro de las zonas a conservar, en {parts} partes: es un "
        "error del diseño; no se crea.",
        count="parts",
        one_msgid="The design moves {volume} m³ inside the zones to conserve, in {parts} part: it "
        "is an error of the design; it is not created.",
        one_es="El diseño mueve {volume} m³ dentro de las zonas a conservar, en {parts} parte: es "
        "un error del diseño; no se crea.",
    ),
    Message(
        "des.conserve_part",
        "«{zone}»: {volume} m³, centre at x = {x} m, y = {y} m.",
        "«{zone}»: {volume} m³, centro en x = {x} m, y = {y} m.",
        "note",
    ),
    Message(
        "des.conserve_nodata",
        "Zone to conserve «{zone}» has no terrain data in {area} m²: those cells do not seed its "
        "conservation ceiling.",
        "La zona a conservar «{zone}» no tiene dato de terreno en {area} m²: esas celdas no "
        "siembran su techo de conservación.",
        "warning",
    ),
    # Corredores (RF-014-09, RF-014-10) ---------------------------------------------------------
    Message(
        "des.corridor_not_lines",
        "Layer «{layer}» holds {value}, not lines: the axis of a corridor is a line layer of "
        "the project.",
        "La capa «{layer}» tiene {value}, no líneas: el eje de un corredor es una capa de líneas "
        "del proyecto.",
    ),
    Message(
        "des.corridor_width",
        "Layer «{layer}», corridor {corridor}: the width «{field}» = {value} m must be greater "
        "than 0; correct it in QGIS; nothing is calculated.",
        "Capa «{layer}», corredor {corridor}: el ancho «{field}» = {value} m tiene que ser mayor "
        "que 0; corríjalo en QGIS; no se calcula nada.",
    ),
    Message(
        "des.corridor_length_zero",
        "Layer «{layer}», corridor {corridor}: its axis has a length of {value} m; draw an axis "
        "with length in QGIS; nothing is calculated.",
        "Capa «{layer}», corredor {corridor}: su eje mide {value} m; dibuje un eje con longitud "
        "en QGIS; no se calcula nada.",
    ),
    Message(
        "des.corridor_level_missing",
        "Layer «{layer}», corridor {corridor}: «{field}» = {value} has no valid value; give it "
        "a level, or a start level and a gradient, in QGIS (none is assumed); nothing is "
        "calculated.",
        "Capa «{layer}», corredor {corridor}: «{field}» = {value} no tiene un valor válido; "
        "dele una cota, o una cota inicial y una pendiente, en QGIS (no se supone ninguna); no "
        "se calcula nada.",
    ),
    Message(
        "des.corridor_level",
        "Layer «{layer}», corridor {corridor}: «{field}» = {value} m is outside the terrain "
        "elevations ± 1 000 m ({low} to {high} m); correct it in QGIS (no level is chosen for "
        "it); nothing is calculated.",
        "Capa «{layer}», corredor {corridor}: «{field}» = {value} m está fuera de las cotas del "
        "terreno ± 1.000 m (de {low} a {high} m); corríjalo en QGIS (no se elige ninguna cota "
        "por él); no se calcula nada.",
    ),
    Message(
        "des.corridor_too_long",
        "Corridor {corridor} measures {length} m, more than its axis ({axis} m) plus its width "
        "({width} m): check its ends.",
        "El corredor {corridor} mide {length} m, más que su eje ({axis} m) más su ancho "
        "({width} m): revise sus extremos.",
        "warning",
    ),
    # Transición del borde y salto creado (RF-014-19 a RF-014-21) -------------------------------
    Message(
        "des.edge_created_step",
        "{share} % of the {pairs} pairs of the edge have a created step greater than "
        "{threshold} m (at least {admitted} % should be within it); the largest, {maximum} m, at "
        "x = {x} m, y = {y} m, in {stretches} stretches. Use «Transitions with the untouched "
        "terrain…».",
        "El {share} % de las {pairs} parejas del borde tiene un salto creado mayor que "
        "{threshold} m (al menos el {admitted} % debería quedar por debajo); el mayor, "
        "{maximum} m, en x = {x} m, y = {y} m, en {stretches} tramos. Use «Transiciones con el "
        "terreno no afectado…».",
        "warning",
        count="stretches",
        one_msgid="{share} % of the {pairs} pairs of the edge have a created step greater than "
        "{threshold} m (at least {admitted} % should be within it); the largest, {maximum} m, at "
        "x = {x} m, y = {y} m, in {stretches} stretch. Use «Transitions with the untouched "
        "terrain…».",
        one_es="El {share} % de las {pairs} parejas del borde tiene un salto creado mayor que "
        "{threshold} m (al menos el {admitted} % debería quedar por debajo); el mayor, "
        "{maximum} m, en x = {x} m, y = {y} m, en {stretches} tramo. Use «Transiciones con el "
        "terreno no afectado…».",
    ),
    Message(
        "des.edge_surface_step",
        "«{surface}»: {share} % of the {pairs} pairs of its edge have a created step greater than "
        "{threshold} m (at least {admitted} % should be within it); the largest, {maximum} m, at "
        "x = {x} m, y = {y} m, in {stretches} stretches. Use «Transitions with the untouched "
        "terrain…».",
        "«{surface}»: el {share} % de las {pairs} parejas de su borde tiene un salto creado mayor "
        "que {threshold} m (al menos el {admitted} % debería quedar por debajo); el mayor, "
        "{maximum} m, en x = {x} m, y = {y} m, en {stretches} tramos. Use «Transiciones con el "
        "terreno no afectado…».",
        "warning",
        count="stretches",
        one_msgid="«{surface}»: {share} % of the {pairs} pairs of its edge have a created step "
        "greater than {threshold} m (at least {admitted} % should be within it); the largest, "
        "{maximum} m, at x = {x} m, y = {y} m, in {stretches} stretch. Use «Transitions with the "
        "untouched terrain…».",
        one_es="«{surface}»: el {share} % de las {pairs} parejas de su borde tiene un salto creado "
        "mayor que {threshold} m (al menos el {admitted} % debería quedar por debajo); el mayor, "
        "{maximum} m, en x = {x} m, y = {y} m, en {stretches} tramo. Use «Transiciones con el "
        "terreno no afectado…».",
    ),
    Message(
        "des.edge_stretch",
        "Stretch {stretch}: {pairs} pairs, up to {maximum} m, centre at x = {x} m, y = {y} m.",
        "Tramo {stretch}: {pairs} parejas, hasta {maximum} m, centro en x = {x} m, y = {y} m.",
        "note",
        count="pairs",
        one_msgid="Stretch {stretch}: {pairs} pair, up to {maximum} m, centre at x = {x} m, "
        "y = {y} m.",
        one_es="Tramo {stretch}: {pairs} pareja, hasta {maximum} m, centro en x = {x} m, "
        "y = {y} m.",
    ),
    # Los tramos que el resumen no enseña (T61, el H3: con 204 tramos, «Crear» quedaba fuera de la
    # ventana); los guarda el informe del diseño. Un ajuste, sin informe, los enseña todos.
    Message(
        "des.edge_more_stretches",
        "… and {stretches} more stretches (in the report).",
        "… y {stretches} tramos más (en el informe).",
        "note",
        count="stretches",
        one_msgid="… and {stretches} more stretch (in the report).",
        one_es="… y {stretches} tramo más (en el informe).",
    ),
    Message(
        "des.edge_not_design_surface",
        "«{value}» is not a design surface of the active version: choose a surface of the "
        "design (the exploitation or the final surface of a quarry, a stepped design, a "
        "fill-only design, a transition or a refitted surface); nothing is calculated.",
        "«{value}» no es una superficie de diseño de la versión activa: elija una superficie del "
        "diseño (la de explotación o la final de una cantera, un escalonado, un diseño «solo "
        "relleno», una transición o una superficie ajustada); no se calcula nada.",
    ),
    # Solo relleno (RF-014-22 a RF-014-25) ------------------------------------------------------
    Message(
        "des.fill_only_cuts",
        "The fill-only design would cut {value} m³ (it must cut less than 1 m³): review the "
        "envelope, its profile and its domain; nothing is created.",
        "El diseño «solo relleno» cortaría {value} m³ (tiene que cortar menos de 1 m³): revise "
        "la envolvente, su perfil y su dominio; no se crea nada.",
    ),
    Message(
        "des.fill_only_untouchable",
        "The fill-only design moves {value} m³ in the untouchable «{constraint}»: review the "
        "envelope, its profile and its domain; nothing is created.",
        "El diseño «solo relleno» mueve {value} m³ en el intocable «{constraint}»: revise la "
        "envolvente, su perfil y su dominio; no se crea nada.",
    ),
    Message(
        "des.fill_only_water_level",
        "Layer «{layer}», water sheet {polygon}: «{field}» = {value} is not a valid level; "
        "correct it in QGIS (none is assumed); nothing is calculated.",
        "Capa «{layer}», lámina de agua {polygon}: «{field}» = {value} no es una cota válida; "
        "corríjala en QGIS (no se supone ninguna); no se calcula nada.",
    ),
    Message(
        "des.fill_only_water_overlap",
        "Layer «{layer}»: water sheets {value} and {other} overlap in {cells} cells; correct the "
        "layer in QGIS (no level is chosen for them); nothing is calculated.",
        "Capa «{layer}»: las láminas de agua {value} y {other} se solapan en {cells} celdas; "
        "corrija la capa en QGIS (no se elige ninguna cota por ellas); no se calcula nada.",
        count="cells",
        one_msgid="Layer «{layer}»: water sheets {value} and {other} overlap in {cells} cell; "
        "correct the layer in QGIS (no level is chosen for them); nothing is calculated.",
        one_es="Capa «{layer}»: las láminas de agua {value} y {other} se solapan en {cells} celda; "
        "corrija la capa en QGIS (no se elige ninguna cota por ellas); no se calcula nada.",
    ),
    # La lámina solo es la partida del relleno admitido (RF-014-23, RF-014-24; T55) ---------------
    Message(
        "des.fill_only_water_outside",
        "Layer «{layer}», water sheet {polygon}: {cells} cells ({area} m²) fall outside the "
        "admitted fill or in an untouchable; it is not filled there and the surface stays on the "
        "recorded terrain.",
        "Capa «{layer}», lámina de agua {polygon}: {cells} celdas ({area} m²) caen fuera del "
        "relleno admitido o en un intocable; allí no se rellena y la superficie queda en el "
        "terreno registrado.",
        "warning",
        count="cells",
        one_msgid="Layer «{layer}», water sheet {polygon}: {cells} cell ({area} m²) falls outside "
                  "the admitted fill or in an untouchable; it is not filled there and the surface "
                  "stays on the recorded terrain.",
        one_es="Capa «{layer}», lámina de agua {polygon}: {cells} celda ({area} m²) cae fuera del "
               "relleno admitido o en un intocable; allí no se rellena y la superficie queda en el "
               "terreno registrado.",
    ),
    # Ajuste a un límite nuevo (RF-014-26 a RF-014-28) ------------------------------------------
    Message(
        "des.refit_outside",
        "«{surface}» leaves {volume} m³ in {area} m² outside the current limit of version "
        "{version}: use Design ▸ Quarry ▸ Refit the design to a new limit…",
        "«{surface}» deja {volume} m³ en {area} m² fuera del límite vigente de la versión "
        "{version}: use Diseño ▸ Cantera ▸ Ajustar el diseño a un límite nuevo…",
        "warning",
    ),
    Message(
        "des.refit_not_needed",
        "The new limit does not cut «{surface}»: its refit is 0 m³ and was not needed.",
        "El límite nuevo no corta «{surface}»: su ajuste es de 0 m³ y no hacía falta.",
        "warning",
    ),
    Message(
        "des.refit_angle",
        "«{surface}» is refitted with the face of its own profile «{profile}» ({face}°), not "
        "with {value}°: a refit with another angle gives false volumes; nothing is calculated.",
        "«{surface}» se ajusta con la cara de su propio perfil «{profile}» ({face}°), no con "
        "{value}°: un ajuste con otro ángulo da volúmenes falsos; no se calcula nada.",
    ),
    Message(
        "des.refit_face_missing",
        "«{surface}» cannot be refitted: the operation that made its design did not record "
        "«{field}» of its profile «{profile}», and a refit uses the face the surface was designed "
        "with; calculate that design again; nothing is calculated.",
        "«{surface}» no se puede ajustar: la operación que hizo su diseño no anotó «{field}» de "
        "su perfil «{profile}», y un ajuste usa la cara con que se diseñó la superficie; vuelva a "
        "calcular ese diseño; no se calcula nada.",
    ),
    # El orden de las dos superficies después del ajuste (RF-014-14, RF-014-27; T53) ----------
    Message(
        "des.refit_order",
        "Order rule of quarry «{quarry}» with its two refitted surfaces: «{surface}» changes in "
        "{cells} cells so that final ≤ exploitation ≤ terrain; the refit volume of each one is "
        "still that of the face of its profile.",
        "Regla de orden de la cantera «{quarry}» con sus dos superficies ajustadas: «{surface}» "
        "cambia en {cells} celdas para que final ≤ explotación ≤ terreno; el volumen de ajuste de "
        "cada una sigue siendo el de la cara de su perfil.",
        "note",
        count="cells",
        one_msgid="Order rule of quarry «{quarry}» with its two refitted surfaces: «{surface}» "
                  "changes in {cells} cell so that final ≤ exploitation ≤ terrain; the refit "
                  "volume of each one is still that of the face of its profile.",
        one_es="Regla de orden de la cantera «{quarry}» con sus dos superficies ajustadas: "
               "«{surface}» cambia en {cells} celda para que final ≤ explotación ≤ terreno; el "
               "volumen de ajuste de cada una sigue siendo el de la cara de su perfil.",
    ),
    Message(
        "des.refit_order_side",
        "After refitting «{surface}», the final surface of quarry «{quarry}» is above its "
        "exploitation surface in {cells} cells, up to {above} m (against «{other}», not "
        "refitted): they do not keep final ≤ exploitation ≤ terrain; refit both at once so that "
        "the order rule of the quarry ties them.",
        "Tras ajustar «{surface}», la superficie final de la cantera «{quarry}» queda por encima "
        "de la de explotación en {cells} celdas, hasta {above} m (frente a «{other}», sin "
        "ajustar): no cumplen final ≤ explotación ≤ terreno; ajuste las dos a la vez para que "
        "las ate la regla de orden de la cantera.",
        "warning",
        count="cells",
        one_msgid="After refitting «{surface}», the final surface of quarry «{quarry}» is above "
                  "its exploitation surface in {cells} cell, up to {above} m (against «{other}», "
                  "not refitted): they do not keep final ≤ exploitation ≤ terrain; refit both at "
                  "once so that the order rule of the quarry ties them.",
        one_es="Tras ajustar «{surface}», la superficie final de la cantera «{quarry}» queda por "
               "encima de la de explotación en {cells} celda, hasta {above} m (frente a "
               "«{other}», sin ajustar): no cumplen final ≤ explotación ≤ terreno; ajuste las dos "
               "a la vez para que las ate la regla de orden de la cantera.",
    ),
    # El ajuste frente a lo obsoleto del diseño del que sale (RF-014-27, RF-014-31; T54) --------
    Message(
        "des.refit_source_stale",
        "The design «{design}» is stale: Project ▸ Recompute the stale results computes it again "
        "with the current limit and then redoes this refit of {surfaces} on it, which replaces "
        "the one created now.",
        "El diseño «{design}» está obsoleto: Proyecto ▸ Recalcular lo obsoleto lo vuelve a "
        "calcular con el límite vigente y después rehace sobre él este ajuste de {surfaces}, que "
        "sustituye al que se cree ahora.",
        "warning",
    ),
    # Entidades de diseño: el marco común (spec 015, T02; RF-015-01, RF-015-04, RF-015-08,
    # RF-015-09, RF-015-13, RF-015-14) ---------------------------------------------------------
    Message(
        "des.entity_name_missing",
        "The entity has no name; give it one, for example P1.",
        "La entidad no tiene nombre; póngale uno, por ejemplo P1.",
    ),
    Message(
        "des.entity_name_repeated",
        "The name «{value}» is already used by entity «{other}» in {version}; give each entity "
        "its own name.",
        "El nombre «{value}» ya lo tiene la entidad «{other}» en {version}; dé a cada entidad su "
        "propio nombre.",
    ),
    Message(
        "des.entity_param_missing",
        "Layer «{layer}», entity «{entity}»: «{field}» has no value and has no default; give it a "
        "value in the entity dialog before calculating (no value is chosen for it).",
        "Capa «{layer}», entidad «{entity}»: «{field}» no tiene valor ni lleva ninguno por "
        "defecto; dele un valor en el diálogo de la entidad antes de calcular (no se elige "
        "ninguno por ella).",
    ),
    Message(
        "des.entity_param_range",
        "Layer «{layer}», entity «{entity}»: «{field}» = {value} is outside its range {range}; "
        "correct it in the entity dialog; nothing is calculated.",
        "Capa «{layer}», entidad «{entity}»: «{field}» = {value} está fuera de su rango {range}; "
        "corríjalo en el diálogo de la entidad; no se calcula nada.",
    ),
    Message(
        "des.entity_param_choice",
        "Layer «{layer}», entity «{entity}»: «{field}» = {value} is not one of its options "
        "({choices}); choose one of them; nothing is calculated.",
        "Capa «{layer}», entidad «{entity}»: «{field}» = {value} no es una de sus opciones "
        "({choices}); elija una de ellas; no se calcula nada.",
    ),
    Message(
        "des.entity_field_value",
        "Layer «{layer}», entity «{entity}»: «{field}» = {value} has no valid value; give it one "
        "in QGIS (none is assumed); nothing is calculated.",
        "Capa «{layer}», entidad «{entity}»: «{field}» = {value} no tiene un valor válido; dele "
        "uno en QGIS (no se supone ninguno); no se calcula nada.",
    ),
    Message(
        "des.entity_feature_unknown",
        "Layer «{layer}» has no feature «{value}»: choose the name or the fid of one of its "
        "features; nothing is calculated.",
        "La capa «{layer}» no tiene ninguna geometría «{value}»: elija el nombre o el fid de una "
        "de las suyas; no se calcula nada.",
    ),
    Message(
        "des.entity_feature_ambiguous",
        "Layer «{layer}» has several features called «{value}» (fid {fids}); choose the one you "
        "mean by its fid; nothing is calculated.",
        "La capa «{layer}» tiene varias geometrías llamadas «{value}» (fid {fids}); elija la que "
        "quiere por su fid; no se calcula nada.",
    ),
    Message(
        "des.entity_start_taken",
        "Entity «{entity}» cannot start from «{value}»: entity «{other}» already does and only "
        "one entity starts from each surface; insert the new one before or after «{other}», or "
        "choose another surface (another alternative goes in another version); nothing is "
        "calculated.",
        "La entidad «{entity}» no puede partir de «{value}»: ya parte la entidad «{other}» y de "
        "cada superficie parte una sola entidad; inserte la nueva antes o después de «{other}», "
        "o elija otra superficie (otra alternativa va en otra versión); no se calcula nada.",
    ),
    Message(
        "des.entity_start_unknown",
        "Entity «{entity}»: «{field}» = {value} is not the surface of a calculated entity of "
        "{version} (it does not exist, it has not been calculated yet or it was discarded); "
        "choose the terrain, a design surface or the surface of another entity; nothing is "
        "calculated.",
        "Entidad «{entity}»: «{field}» = {value} no es la superficie de una entidad calculada de "
        "{version} (no existe, aún no se ha calculado o se descartó); elija el terreno, una "
        "superficie de diseño o la superficie de otra entidad; no se calcula nada.",
    ),
    Message(
        "des.entity_supports_unknown",
        "Entity «{entity}»: «{field}» = {value} declares that it rests on {target}, which is not a "
        "calculated entity of {version} on which it can rest ({reason}); correct the declared "
        "dependencies; nothing is calculated.",
        "Entidad «{entity}»: «{field}» = {value} declara que se apoya en {target}, que no es una "
        "entidad calculada de {version} en la que pueda apoyarse ({reason}); corrija las "
        "dependencias declaradas; no se calcula nada.",
    ),
    Message(
        "des.entity_chain_cycle",
        "The chain of entities {chain} loops back on itself: an entity cannot start, directly or "
        "through others, from its own surface; change the start surface of one of them; nothing "
        "is calculated.",
        "La cadena de entidades {chain} se cierra sobre sí misma: una entidad no puede partir, "
        "directa ni indirectamente, de su propia superficie; cambie la superficie de partida de "
        "una de ellas; no se calcula nada.",
    ),
    Message(
        "des.chainless_start",
        "Entity «{entity}» cannot start from «{value}»: «{other}» does not leave a surface to "
        "start from (it only keeps its own data) and no entity can start from it; choose the "
        "terrain, a design surface or the surface of an entity that changes the surface; nothing "
        "is calculated.",
        "La entidad «{entity}» no puede partir de «{value}»: «{other}» no deja una superficie de "
        "la que partir (solo guarda sus propios datos) y ninguna entidad puede partir de ella; "
        "elija el terreno, una superficie de diseño o la superficie de una entidad que cambie la "
        "superficie; no se calcula nada.",
    ),
    Message(
        "des.entity_insert_reason",
        "Entity {inserted} is inserted before {entity}: {entity} now starts from the surface "
        "that {inserted} leaves.",
        "Se inserta la entidad {inserted} antes de {entity}: {entity} pasa a partir de la "
        "superficie que deja {inserted}.",
        "note",
    ),
    Message(
        "des.entity_nodata",
        "Entity «{entity}»: {area} m² of its footprint have no data in the surface «{surface}» "
        "({role}), the first cell at x = {x} m, y = {y} m; complete the surface or move the "
        "geometry; nothing is calculated or recorded.",
        "Entidad «{entity}»: {area} m² de su huella no tienen dato en la superficie «{surface}» "
        "({role}), la primera celda en x = {x} m, y = {y} m; complete la superficie o mueva la "
        "geometría; no se calcula ni se registra nada.",
    ),
    Message(
        "des.entity_held",
        "Entity «{entity}»: {area} m² of its footprint or its edge do not move because of the "
        "constraint «Platform {other} (declared)» (around x = {x} m, y = {y} m); they stay as in "
        "the start surface.",
        "Entidad «{entity}»: {area} m² de su huella o de su borde no se mueven por la "
        "restricción «Plataforma {other} (declarada)» (en torno a x = {x} m, y = {y} m); quedan "
        "como en la superficie de partida.",
        "warning",
    ),
    Message(
        "des.entity_held_constraint",
        "Entity «{entity}»: {area} m² of its footprint or its edge do not move because of the "
        "constraint «{constraint}» (around x = {x} m, y = {y} m); they stay as in the start "
        "surface.",
        "Entidad «{entity}»: {area} m² de su huella o de su borde no se mueven por la "
        "restricción «{constraint}» (en torno a x = {x} m, y = {y} m); quedan como en la "
        "superficie de partida.",
        "warning",
    ),
    Message(
        "des.entity_held_masks",
        "Entity «{entity}»: {area} m² of its footprint or its edge do not move because the masks "
        "of the version do not allow it (limits or the band of a limit; around x = {x} m, "
        "y = {y} m); they stay as in the start surface.",
        "Entidad «{entity}»: {area} m² de su huella o de su borde no se mueven porque las "
        "máscaras de la versión no lo admiten (límites o la banda de un límite; en torno a "
        "x = {x} m, y = {y} m); quedan como en la superficie de partida.",
        "warning",
    ),
    Message(
        "des.entity_edge_outside",
        "Entity «{entity}»: its edge reaches the border of the grid or cells without data "
        "outside its footprint, in {cells} cells ({area} m²), the first at x = {x} m, y = {y} m; "
        "the surface can be cut short there.",
        "Entidad «{entity}»: su borde llega al borde de la rejilla o a celdas sin dato fuera de "
        "su huella, en {cells} celdas ({area} m²), la primera en x = {x} m, y = {y} m; allí la "
        "superficie puede quedar cortada.",
        "warning",
        count="cells",
        one_msgid="Entity «{entity}»: its edge reaches the border of the grid or cells without "
        "data outside its footprint, in {cells} cell ({area} m²), at x = {x} m, y = {y} m; the "
        "surface can be cut short there.",
        one_es="Entidad «{entity}»: su borde llega al borde de la rejilla o a celdas sin dato "
        "fuera de su huella, en {cells} celda ({area} m²), en x = {x} m, y = {y} m; allí la "
        "superficie puede quedar cortada.",
    ),
    Message(
        "des.entity_quarry_order",
        "Entity «{entity}» changes «{surface}», a surface of quarry «{quarry}», and the result "
        "does not keep final ≤ exploitation ≤ terrain against «{other}»: {cells} cells "
        "({area} m²), up to {above} m, the first at x = {x} m, y = {y} m; it can be created "
        "anyway.",
        "La entidad «{entity}» cambia «{surface}», una superficie de la cantera «{quarry}», y el "
        "resultado no cumple final ≤ explotación ≤ terreno frente a «{other}»: {cells} celdas "
        "({area} m²), hasta {above} m, la primera en x = {x} m, y = {y} m; se puede crear "
        "igualmente.",
        "warning",
        count="cells",
        one_msgid="Entity «{entity}» changes «{surface}», a surface of quarry «{quarry}», and "
        "the result does not keep final ≤ exploitation ≤ terrain against «{other}»: {cells} "
        "cell ({area} m²), {above} m, at x = {x} m, y = {y} m; it can be created anyway.",
        one_es="La entidad «{entity}» cambia «{surface}», una superficie de la cantera "
        "«{quarry}», y el resultado no cumple final ≤ explotación ≤ terreno frente a «{other}»: "
        "{cells} celda ({area} m²), {above} m, en x = {x} m, y = {y} m; se puede crear "
        "igualmente.",
    ),
    # La plataforma: el motivo que declara, su geometría y su rasante (RF-015-08, RF-015-10,
    # RF-015-12, RF-015-19, RF-015-23, RF-015-24) -----------------------------------------------
    Message(
        "des.platform_declared_reason",
        "declared by platform {name}",
        "declarada por la plataforma {name}",
        "note",
    ),
    Message(
        "des.platform_layer_kind",
        "Layer «{layer}» holds {value}, not lines or polygons: a platform comes from a line (its "
        "axis, with its width) or from a polygon of a layer of the project.",
        "La capa «{layer}» tiene {value}, no líneas ni polígonos: una plataforma sale de una "
        "línea (su eje, con su ancho) o de un polígono de una capa del proyecto.",
    ),
    Message(
        "des.platform_self_intersects",
        "Layer «{layer}», platform «{entity}»: its geometry crosses itself at x = {x} m, "
        "y = {y} m; correct it in QGIS; nothing is calculated.",
        "Capa «{layer}», plataforma «{entity}»: su geometría se corta a sí misma en x = {x} m, "
        "y = {y} m; corríjala en QGIS; no se calcula nada.",
    ),
    Message(
        "des.platform_axis_length_zero",
        "Layer «{layer}», platform «{entity}»: its axis has a length of {value} m; draw an axis "
        "with length in QGIS; nothing is calculated.",
        "Capa «{layer}», plataforma «{entity}»: su eje mide {value} m; dibuje un eje con "
        "longitud en QGIS; no se calcula nada.",
    ),
    Message(
        "des.platform_axis_closed",
        "Layer «{layer}», platform «{entity}»: its axis is closed (it ends where it starts), so "
        "it has no sense and no abscissa 0; draw it open in QGIS; nothing is calculated.",
        "Capa «{layer}», plataforma «{entity}»: su eje es cerrado (acaba donde empieza), así que "
        "no tiene sentido ni abscisa 0; dibújelo abierto en QGIS; no se calcula nada.",
    ),
    Message(
        "des.platform_axis_parts",
        "Layer «{layer}», platform «{entity}»: its axis has {value} parts; a platform axis is a "
        "single line (the abscissa 0 is at its start: the first vertex of a line or, in a polygon "
        "with a linked line, where the line enters the polygon); join them into one line in QGIS; "
        "nothing is calculated.",
        "Capa «{layer}», plataforma «{entity}»: su eje tiene {value} partes; el eje de una "
        "plataforma es una sola línea (la abscisa 0 está en su inicio: el primer vértice de una "
        "línea o, en un polígono con línea enlazada, donde la línea entra en él); únalas en una "
        "línea en QGIS; no se calcula nada.",
    ),
    Message(
        "des.platform_area_zero",
        "Layer «{layer}», platform «{entity}»: its polygon has an area of {value} m²; draw a "
        "polygon with area in QGIS; nothing is calculated.",
        "Capa «{layer}», plataforma «{entity}»: su polígono tiene {value} m² de área; dibuje un "
        "polígono con área en QGIS; no se calcula nada.",
    ),
    Message(
        "des.platform_no_cells",
        "Layer «{layer}», platform «{entity}»: its footprint has no cell in the project grid (a "
        "cell is part of it if its centre is inside); check its position and its width; "
        "nothing is calculated.",
        "Capa «{layer}», plataforma «{entity}»: su huella no tiene ninguna celda en la rejilla "
        "del proyecto (una celda es suya si su centro queda dentro); revise su posición y su "
        "ancho; no se calcula nada.",
    ),
    Message(
        "des.platform_axis_not_crossing",
        "Layer «{layer}», platform «{entity}»: the axis «{value}» does not cross its polygon "
        "from side to side; draw an axis that enters and leaves the polygon, or remove the link "
        "to use the principal axis; nothing is calculated.",
        "Capa «{layer}», plataforma «{entity}»: el eje «{value}» no cruza su polígono de lado a "
        "lado; dibuje un eje que entre y salga del polígono, o quite el enlace para usar el eje "
        "principal; no se calcula nada.",
    ),
    Message(
        "des.platform_axis_principal",
        "Platform «{entity}» has no linked axis: its principal axis is used, from x = {x} m, "
        "y = {y} m (abscissa 0) towards x = {x_end} m, y = {y_end} m; link an axis in its layer "
        "to choose the sense.",
        "La plataforma «{entity}» no tiene eje enlazado: se usa su eje principal, desde "
        "x = {x} m, y = {y} m (abscisa 0) hacia x = {x_end} m, y = {y_end} m; enlace un eje en "
        "su capa para elegir el sentido.",
        "warning",
    ),
    Message(
        "des.platform_footprint_clipped",
        "Platform «{entity}»: the project grid cuts its footprint: {area} m² of it ({cells} cells) "
        "fall outside the grid, the first at x = {x} m, y = {y} m; only the part inside is "
        "calculated; enlarge the working window of the project or move the platform.",
        "Plataforma «{entity}»: la rejilla del proyecto recorta su huella: {area} m² de ella "
        "({cells} celdas) quedan fuera de la rejilla, la primera en x = {x} m, y = {y} m; solo se "
        "calcula la parte de dentro; amplíe la ventana de trabajo del proyecto o mueva la "
        "plataforma.",
        "warning",
        count="cells",
        one_msgid="Platform «{entity}»: the project grid cuts its footprint: {area} m² of it "
        "({cells} cell) fall outside the grid, at x = {x} m, y = {y} m; only the part inside is "
        "calculated; enlarge the working window of the project or move the platform.",
        one_es="Plataforma «{entity}»: la rejilla del proyecto recorta su huella: {area} m² de ella "
        "({cells} celda) quedan fuera de la rejilla, en x = {x} m, y = {y} m; solo se calcula la "
        "parte de dentro; amplíe la ventana de trabajo del proyecto o mueva la plataforma.",
    ),
    Message(
        "des.platform_level_range",
        "Layer «{layer}», platform «{entity}»: «{field}» = {value} m is outside the terrain "
        "elevations ± 1 000 m ({low} to {high} m); correct it (no level is chosen for it); "
        "nothing is calculated.",
        "Capa «{layer}», plataforma «{entity}»: «{field}» = {value} m está fuera de las cotas "
        "del terreno ± 1.000 m (de {low} a {high} m); corríjalo (no se elige ninguna cota por "
        "ella); no se calcula nada.",
    ),
    Message(
        "des.platform_max_slope",
        "Layer «{layer}», platform «{entity}»: its gradient «{field}» = {value} % exceeds its "
        "maximum gradient of {maximum} %; a gradient like that is a ramp, not a platform: draw "
        "it with the haul roads or raise the maximum; nothing is calculated.",
        "Capa «{layer}», plataforma «{entity}»: su pendiente «{field}» = {value} % supera su "
        "pendiente máxima de {maximum} %; una pendiente así es una rampa, no una plataforma: "
        "dibújela con las pistas o suba el máximo; no se calcula nada.",
    ),
    Message(
        "des.platform_protect_cut_fill",
        "Layer «{layer}», platform «{entity}»: in the «cut and fill» mode it fills its own "
        "footprint, so it cannot protect it with «no fill»; choose the «cut» mode or do not "
        "protect it; nothing is calculated.",
        "Capa «{layer}», plataforma «{entity}»: en el modo «en corte y relleno» rellena su propia "
        "huella, así que no puede protegerla con «sin relleno»; elija el modo «en corte» o no la "
        "proteja; no se calcula nada.",
    ),
    Message(
        "des.platform_counter_slope",
        "Platform «{entity}»: its longitudinal profile rises {amount} m against the sense in "
        "which its level falls, at chainage {chainage} m (x = {x} m, y = {y} m), more than its "
        "tolerance of {tolerance} m; confirm to create it with this counter-gradient.",
        "Plataforma «{entity}»: su perfil longitudinal sube {amount} m en contra del sentido en "
        "que baja su rasante, en la abscisa {chainage} m (x = {x} m, y = {y} m), más que su "
        "tolerancia de {tolerance} m; confirme para crearla con esta contrapendiente.",
        "warning",
    ),
    Message(
        "des.platform_counter_flat",
        "Platform «{entity}»: with a gradient of 0 %, its longitudinal profile varies {amount} m "
        "(from {low} m to {high} m), more than its tolerance of {tolerance} m; the highest point "
        "is at chainage {chainage} m (x = {x} m, y = {y} m); confirm to create it anyway.",
        "Plataforma «{entity}»: con una pendiente del 0 %, su perfil longitudinal varía {amount} m "
        "(de {low} m a {high} m), más que su tolerancia de {tolerance} m; el punto más alto está "
        "en la abscisa {chainage} m (x = {x} m, y = {y} m); confirme para crearla igualmente.",
        "warning",
    ),
    Message(
        "des.platform_counter_unconfirmed",
        "Platform «{entity}» is not created: its longitudinal profile rises {amount} m against the "
        "sense in which its level falls (tolerance {tolerance} m) and it is not created without "
        "your express confirmation; confirm the counter-gradient, or correct the level, the "
        "gradient or the masks; nothing is created.",
        "La plataforma «{entity}» no se crea: su perfil longitudinal sube {amount} m en contra del "
        "sentido en que baja su rasante (tolerancia {tolerance} m) y no se crea sin su "
        "confirmación expresa; confirme la contrapendiente, o corrija la cota, la pendiente o las "
        "máscaras; no se crea nada.",
    ),
    Message(
        "des.platform_below",
        "Platform «{entity}»: {area} m² of its footprint stay below its level, up to {maximum} "
        "m, in {groups} groups, because in the «cut» mode it does not fill.",
        "Plataforma «{entity}»: {area} m² de su huella quedan por debajo de su rasante, hasta "
        "{maximum} m, en {groups} grupos, porque en el modo «en corte» no rellena.",
        "warning",
        count="groups",
        one_msgid="Platform «{entity}»: {area} m² of its footprint stay below its level, up to "
        "{maximum} m, in {groups} group, because in the «cut» mode it does not fill.",
        one_es="Plataforma «{entity}»: {area} m² de su huella quedan por debajo de su rasante, "
        "hasta {maximum} m, en {groups} grupo, porque en el modo «en corte» no rellena.",
    ),
    Message(
        "des.platform_below_group",
        "Group {group}: {cells} cells, {area} m², up to {maximum} m below its level, centre at "
        "x = {x} m, y = {y} m.",
        "Grupo {group}: {cells} celdas, {area} m², hasta {maximum} m por debajo de su rasante, "
        "centro en x = {x} m, y = {y} m.",
        "note",
        count="cells",
        one_msgid="Group {group}: {cells} cell, {area} m², up to {maximum} m below its level, "
        "centre at x = {x} m, y = {y} m.",
        one_es="Grupo {group}: {cells} celda, {area} m², hasta {maximum} m por debajo de su "
        "rasante, centro en x = {x} m, y = {y} m.",
    ),
    Message(
        "des.platform_below_masks",
        "Platform «{entity}»: {area} m² of its footprint stay below its level, up to {maximum} "
        "m, in {groups} groups, because the masks do not allow filling there.",
        "Plataforma «{entity}»: {area} m² de su huella quedan por debajo de su rasante, hasta "
        "{maximum} m, en {groups} grupos, porque las máscaras no admiten allí el relleno.",
        "warning",
        count="groups",
        one_msgid="Platform «{entity}»: {area} m² of its footprint stay below its level, up to "
        "{maximum} m, in {groups} group, because the masks do not allow filling there.",
        one_es="Plataforma «{entity}»: {area} m² de su huella quedan por debajo de su rasante, "
        "hasta {maximum} m, en {groups} grupo, porque las máscaras no admiten allí el relleno.",
    ),
    Message(
        "des.platform_above",
        "Platform «{entity}»: {area} m² of its footprint stay above its level, up to {maximum} "
        "m, in {groups} groups, because the masks do not allow cutting there.",
        "Plataforma «{entity}»: {area} m² de su huella quedan por encima de su rasante, hasta "
        "{maximum} m, en {groups} grupos, porque las máscaras no admiten allí el corte.",
        "warning",
        count="groups",
        one_msgid="Platform «{entity}»: {area} m² of its footprint stay above its level, up to "
        "{maximum} m, in {groups} group, because the masks do not allow cutting there.",
        one_es="Plataforma «{entity}»: {area} m² de su huella quedan por encima de su rasante, "
        "hasta {maximum} m, en {groups} grupo, porque las máscaras no admiten allí el corte.",
    ),
    Message(
        "des.platform_above_group",
        "Group {group}: {cells} cells, {area} m², up to {maximum} m above its level, centre at "
        "x = {x} m, y = {y} m.",
        "Grupo {group}: {cells} celdas, {area} m², hasta {maximum} m por encima de su rasante, "
        "centro en x = {x} m, y = {y} m.",
        "note",
        count="cells",
        one_msgid="Group {group}: {cells} cell, {area} m², up to {maximum} m above its level, "
        "centre at x = {x} m, y = {y} m.",
        one_es="Grupo {group}: {cells} celda, {area} m², hasta {maximum} m por encima de su "
        "rasante, centro en x = {x} m, y = {y} m.",
    ),
    Message(
        "des.platform_no_cut",
        "Platform «{entity}» does not cut: no cell of its footprint ({area} m²) goes down to its "
        "level.",
        "La plataforma «{entity}» no corta: ninguna celda de su huella ({area} m²) baja hasta su "
        "rasante.",
        "warning",
    ),
    # El borde de la plataforma: la pared que queda más empinada que su ángulo (RF-015-22,
    # RF-015-13; T08). La que sale del salto creado, de la magnitud y de lo que llega al borde de la
    # rejilla usa ``des.edge_surface_step``, ``des.magnitude_*`` y ``des.entity_edge_outside``.
    Message(
        "des.platform_edge_steep",
        "Platform «{entity}»: {cells} cells of its edge are steeper than its edge angle "
        "({angle}°) plus the face tolerance ({tolerance}°); the worst is {max}° against a limit "
        "of {limit}°, at x = {x} m, y = {y} m: {at_reach} at the reach limit ({reach} m), "
        "{at_masks} next to what the masks do not let move and {other} because of the platform "
        "itself. Widen the reach or check the slope; a wall like that is only "
        "admitted at those limits.",
        "Plataforma «{entity}»: {cells} celdas de su borde quedan más empinadas que su ángulo de "
        "borde ({angle}°) más la tolerancia de cara ({tolerance}°); la peor, {max}° frente a un "
        "límite de {limit}°, en x = {x} m, y = {y} m: {at_reach} en el límite del alcance "
        "({reach} m), {at_masks} junto a lo que las máscaras no dejan mover y {other} por la "
        "propia plataforma. Amplíe el alcance o revise la ladera; una pared así "
        "solo se admite en esos límites.",
        "warning",
        count="cells",
        one_msgid="Platform «{entity}»: {cells} cell of its edge is steeper than its edge angle "
        "({angle}°) plus the face tolerance ({tolerance}°); it is {max}° against a limit of "
        "{limit}°, at x = {x} m, y = {y} m: {at_reach} at the reach limit ({reach} m), "
        "{at_masks} next to what the masks do not let move and {other} because of the platform "
        "itself. Widen the reach or check the slope; a wall like that is only "
        "admitted at those limits.",
        one_es="Plataforma «{entity}»: {cells} celda de su borde queda más empinada que su ángulo "
        "de borde ({angle}°) más la tolerancia de cara ({tolerance}°); es de {max}° frente a un "
        "límite de {limit}°, en x = {x} m, y = {y} m: {at_reach} en el límite del alcance "
        "({reach} m), {at_masks} junto a lo que las máscaras no dejan mover y {other} por la "
        "propia plataforma. Amplíe el alcance o revise la ladera; una pared así "
        "solo se admite en esos límites.",
    ),
    # El resumen de «Calcular» (RF-015-03, RF-015-13; T12): los grupos que no caben y lo que quedará
    # obsoleto al crear la entidad.
    Message(
        "des.platform_more_groups",
        "… and {groups} more groups (in the report)",
        "… y {groups} grupos más (en el informe)",
        "note",
        count="groups",
        one_msgid="… and {groups} more group (in the report)",
        one_es="… y {groups} grupo más (en el informe)",
    ),
    Message(
        "des.entity_obsolete_masks",
        "Creating the platform «{entity}», which protects its footprint, will make the masks of "
        "{version} stale: they are compiled again with the constraint it declares.",
        "Al crear la plataforma «{entity}», que protege su huella, quedarán obsoletas las "
        "máscaras de {version}: se compilan de nuevo con la restricción que declara.",
        "note",
    ),
    # El nombre de una operación de la versión que no lo lleva en sus ajustes (la capa de entidades, la declaración): lo que
    # las notas de lo que queda obsoleto enseñan en vez del identificador del tipo («des.entity_layer», spec 015, T51, H3-1).
    Message(
        "des.entity_layer_name",
        "the entity layer of {version}",
        "la capa de entidades de {version}",
        "note",
    ),
    Message(
        "des.entity_declaration_name",
        "the declared restrictions of {version}",
        "las restricciones declaradas de {version}",
        "note",
    ),
    Message(
        "des.entity_obsolete_consumers",
        "With them, {operations} operations that used the masks will be stale: {items}; Project ▸ "
        "Recompute the stale results computes them again.",
        "Con ellas quedarán obsoletas {operations} operaciones que usaron las máscaras: {items}; "
        "Proyecto ▸ Recalcular lo obsoleto las vuelve a calcular.",
        "note",
        count="operations",
        one_msgid="With them, {operations} operation that used the masks will be stale: {items}; "
        "Project ▸ Recompute the stale results computes it again.",
        one_es="Con ellas quedará obsoleta {operations} operación que usó las máscaras: {items}; "
        "Proyecto ▸ Recalcular lo obsoleto la vuelve a calcular.",
    ),
    Message(
        "des.entity_obsolete_successor",
        "Inserting the platform «{entity}» will make {entities} entities of the chain stale, the "
        "one that starts from its surface and the ones after it: {items}.",
        "Al insertar la plataforma «{entity}», quedarán obsoletas {entities} entidades de la "
        "cadena, la que parte de su superficie y las que le siguen: {items}.",
        "note",
        count="entities",
        one_msgid="Inserting the platform «{entity}» will make {entities} entity of the chain "
        "stale, the one that starts from its surface: {items}.",
        one_es="Al insertar la plataforma «{entity}», quedará obsoleta {entities} entidad de la "
        "cadena, la que parte de su superficie: {items}.",
    ),
    Message(
        "des.entity_obsolete_dependents",
        "Replacing the operation that made the platform «{entity}» will make {operations} "
        "operations that depended on it stale: {items}.",
        "Al sustituir la operación que hizo la plataforma «{entity}», quedarán obsoletas "
        "{operations} operaciones que dependían de ella: {items}.",
        "note",
        count="operations",
        one_msgid="Replacing the operation that made the platform «{entity}» will make "
        "{operations} operation that depended on it stale: {items}.",
        one_es="Al sustituir la operación que hizo la plataforma «{entity}», quedará obsoleta "
        "{operations} operación que dependía de ella: {items}.",
    ),
    # La lista de dependencias de una entidad (RF-015-15, RF-015-17; T24): una línea por fila, con el nombre, el
    # tipo (el de la operación) y los m³ apoyados o, si solo parte de su superficie, «superficie de partida».
    Message(
        "des.entity_dependent_volume",
        "{name} ({kind}): {volume} m³ supported",
        "{name} ({kind}): {volume} m³ apoyados",
        "note",
    ),
    Message(
        "des.entity_dependent_start",
        "{name} ({kind}): start surface",
        "{name} ({kind}): superficie de partida",
        "note",
    ),
    # Descartar una entidad, «apoyo retirado» y soltar el apoyo (RF-015-17, RF-009-12; D-12; A7, P-6; T25).
    Message(
        "des.entity_discard_reason",
        "Entity «{entity}»: write the reason to discard it; it is recorded with the decision; nothing "
        "is discarded.",
        "Entidad «{entity}»: escriba el motivo para descartarla; queda registrado con la decisión; no "
        "se descarta nada.",
    ),
    Message(
        "des.entity_already_discarded",
        "Entity «{entity}» is already discarded in {version}: it is a record, not to be used; nothing "
        "is done.",
        "La entidad «{entity}» ya está descartada en {version}: es un registro, no se usa; no se hace "
        "nada.",
    ),
    Message(
        "des.entity_release_reason",
        "«{entity}»: write the reason to give it as good without the support it has lost; it is "
        "recorded with the decision; nothing is done.",
        "«{entity}»: escriba el motivo para darla por buena sin el apoyo que ha perdido; queda "
        "registrado con la decisión; no se hace nada.",
    ),
    Message(
        "des.entity_release_unknown",
        "«{entity}» does not have its support on «{target}» removed in {version}: only what rests on "
        "an entity that was discarded can be given as good without that support; nothing is done.",
        "«{entity}» no tiene retirado su apoyo en «{target}» en {version}: solo se da por bueno sin "
        "su apoyo lo que se apoyaba en una entidad que se descartó; no se hace nada.",
    ),
    Message(
        "des.entity_release_nothing",
        "«{entity}» has no support removed in {version}: nothing rests on a discarded entity; nothing "
        "is done.",
        "«{entity}» no tiene ningún apoyo retirado en {version}: nada se apoya en una entidad "
        "descartada; no se hace nada.",
    ),
    Message(
        "des.entity_release_start",
        "«{entity}» starts from the surface of «{target}», which was discarded: without it there is "
        "nothing to repeat it on, so it cannot be given as good; remake it on another surface (change "
        "its start surface) or discard it; nothing is done.",
        "«{entity}» parte de la superficie de «{target}», que se descartó: sin ella no hay sobre qué "
        "repetirla, así que no se puede dar por buena; rehágala sobre otra superficie (cambie su "
        "superficie de partida) o descártela; no se hace nada.",
    ),
    Message(
        "des.entity_release_support_param",
        "«{entity}» has the surface of «{target}», which was discarded, as its support surface: it "
        "cannot be given as good with it; change its support surface or discard it; nothing is done.",
        "«{entity}» tiene la superficie de «{target}», que se descartó, como superficie de apoyo: no "
        "se puede dar por buena con ella; cambie su superficie de apoyo o descártela; no se hace nada.",
    ),
    Message(
        "des.entity_release_others",
        "«{entity}» has also lost its support on {others}: all the supports it has lost are given as "
        "good together, because it cannot keep one that was discarded; do not name the entity; nothing "
        "is done.",
        "«{entity}» ha perdido también su apoyo en {others}: se dan por buenos todos los apoyos "
        "perdidos a la vez, porque no puede conservar uno que se descartó; no indique la entidad; no "
        "se hace nada.",
    ),
    Message(
        "des.support_removed",
        "Support removed: {what}",
        "Apoyo retirado: {what}",
        "note",
    ),
    Message(
        "des.support_removed_platform",
        "the entity «{name}» was discarded",
        "se descartó «{name}»",
        "note",
    ),
    Message(
        "des.support_removed_dataset",
        "«{name}» was discarded",
        "se descartó «{name}»",
        "note",
    ),
    Message(
        "des.event_entity_discarded",
        "Entity «{name}» ({code}) discarded in {version}: {reason}",
        "Entidad «{name}» ({code}) descartada en {version}: {reason}",
        "note",
    ),
    Message(
        "des.event_support_released",
        "«{name}» given as good in {version} without its support on {entities}: {reason}",
        "«{name}» dada por buena en {version} sin su apoyo en {entities}: {reason}",
        "note",
    ),
    # Tras la orden de una entidad (RF-015-10, RF-012-06; T19): la declaración, las máscaras de nuevo, lo
    # ganado y perdido por restricción, lo que quedó obsoleto y lo que no se pudo hacer.
    Message(
        "des.entity_chain_declared",
        "The constraints declared by the entities of {version} are up to date: {count} in all.",
        "Las restricciones que declaran las entidades de {version} están al día: {count} en total.",
        "note",
    ),
    Message(
        "des.entity_chain_masks",
        "The masks of {version} have been compiled again with the constraints the entities declare.",
        "Las máscaras de {version} se han compilado de nuevo con las restricciones que declaran las "
        "entidades.",
        "note",
    ),
    Message(
        "des.entity_chain_change",
        "{name} (declared constraint): polygon +{gained} m² −{lost} m², zone +{zone_gained} m² "
        "−{zone_lost} m²",
        "{name} (restricción declarada): polígono +{gained} m² −{lost} m², zona +{zone_gained} m² "
        "−{zone_lost} m²",
        "note",
    ),
    Message(
        "des.entity_chain_obsolete",
        "With the new masks, {operations} operations that used the old ones are now stale: {items}; "
        "Project ▸ Recompute the stale results computes them again.",
        "Con las máscaras nuevas han quedado obsoletas {operations} operaciones que usaron las "
        "anteriores: {items}; Proyecto ▸ Recalcular lo obsoleto las vuelve a calcular.",
        "note",
        count="operations",
        one_msgid="With the new masks, {operations} operation that used the old ones is now stale: "
        "{items}; Project ▸ Recompute the stale results computes it again.",
        one_es="Con las máscaras nuevas ha quedado obsoleta {operations} operación que usó las "
        "anteriores: {items}; Proyecto ▸ Recalcular lo obsoleto la vuelve a calcular.",
    ),
    Message(
        "des.entity_chain_declare_failed",
        "The constraints declared by the entities of {version} could not be updated: {reason} The "
        "entity is created; they are updated the next time an entity is created or changed.",
        "No se pudieron poner al día las restricciones que declaran las entidades de {version}: "
        "{reason} La entidad está creada; se ponen al día la próxima vez que se cree o cambie una "
        "entidad.",
        "warning",
    ),
    Message(
        "des.entity_chain_masks_failed",
        "The masks of {version} could not be compiled again with the declared constraints: {reason} "
        "They stay stale and are compiled again before the next operation that uses them.",
        "No se pudieron compilar de nuevo las máscaras de {version} con las restricciones "
        "declaradas: {reason} Siguen obsoletas y se compilan de nuevo antes de la próxima "
        "operación que las use.",
        "warning",
    ),
    Message(
        "des.entity_chain_layer_failed",
        "The layer of the entities of {version} could not be updated: {reason} The entity is created; the "
        "layer keeps what it had and is stale if an entity it shows changed (Project ▸ Recompute the stale "
        "results brings it up to date); it is updated the next time an entity is created, changed or "
        "discarded.",
        "No se pudo poner al día la capa de entidades de {version}: {reason} La entidad está creada; la capa "
        "conserva lo que tenía y queda obsoleta si cambió una entidad que enseña (Proyecto ▸ Recalcular lo "
        "obsoleto la pone al día); se pone al día la próxima vez que se cree, cambie o descarte una entidad.",
        "warning",
    ),
    # La tabla de la entidad editada fuera de Geoblender (RF-015-11, RF-008-56, RF-008-57; B-2; T43): la huella de la que
    # sale su zona declarada y su fila de la capa.
    Message(
        "des.entity_footprint_blocked",
        "The table «{table}» of entity «{entity}» (the footprint its declared zone comes from) was edited outside "
        "Geoblender and is not edited by hand: accept the edit with a reason or recompute the entity so it writes the "
        "table again; its constraints are not declared and the masks of {version} are not compiled meanwhile.",
        "La tabla «{table}» de la entidad «{entity}» (la huella de la que sale su zona declarada) se editó fuera de "
        "Geoblender y no se edita a mano: acepte la edición con un motivo o recalcule la entidad para que vuelva a "
        "escribirla; mientras tanto no se declaran sus restricciones ni se compilan las máscaras de {version}.",
    ),
    Message(
        "des.entity_footprint_unusable",
        "The table «{table}» of entity «{entity}» (the footprint its declared zone comes from) is missing, damaged or "
        "is no longer an entity table (its row was deleted outside Geoblender): recompute the entity so it writes the "
        "table again; its constraints are not declared and the masks of {version} are not compiled meanwhile.",
        "La tabla «{table}» de la entidad «{entity}» (la huella de la que sale su zona declarada) falta, está dañada o "
        "ya no es la tabla de una entidad (se borró su fila fuera de Geoblender): recalcule la entidad para que vuelva "
        "a escribirla; mientras tanto no se declaran sus restricciones ni se compilan las máscaras de {version}.",
    ),
    # Traer las entidades de otra versión (RF-015-18, RF-009-01; D-18; T26): lo que se rechaza y lo que se avisa.
    Message(
        "des.entity_bring_same",
        "«{version}» is the version the entities are brought to: choose another version as the source; "
        "nothing is brought.",
        "«{version}» es la versión a la que se traen las entidades: elija otra de origen; no se trae "
        "nada.",
    ),
    Message(
        "des.entity_bring_unknown",
        "{source} has no entity «{entity}»; nothing is brought.",
        "{source} no tiene ninguna entidad «{entity}»; no se trae nada.",
    ),
    Message(
        "des.entity_bring_discarded",
        "The entity «{entity}» is discarded in {source}: it is a record, not to be used, so it is not "
        "brought; nothing is brought.",
        "La entidad «{entity}» está descartada en {source}: es un registro, no se usa, así que no se "
        "trae; no se trae nada.",
    ),
    Message(
        "des.entity_bring_nothing",
        "{source} has no entity to bring (the discarded ones are not brought); nothing is done.",
        "{source} no tiene ninguna entidad que traer (las descartadas no se traen); no se hace nada.",
        "note",
    ),
    Message(
        "des.entity_bring_done",
        "{count} entities brought from {source} to {version}, without their results: they are left "
        "as «not calculated» and their dependencies are detected again when they are calculated.",
        "{count} entidades traídas de {source} a {version}, sin sus resultados: quedan «sin "
        "calcular» y sus dependencias se detectan de nuevo al calcularlas.",
        "note",
        count="count",
        one_msgid="{count} entity brought from {source} to {version}, without its results: it is left "
        "as «not calculated» and its dependencies are detected again when it is calculated.",
        one_es="{count} entidad traída de {source} a {version}, sin sus resultados: queda «sin "
        "calcular» y sus dependencias se detectan de nuevo al calcularla.",
    ),
    Message(
        "des.entity_bring_recoded",
        "«{name}» was {old} in {source}; here it is {code}, because {old} is already taken in "
        "{version} (the references between the entities brought follow the new code).",
        "«{name}» era {old} en {source}; aquí es {code}, porque {old} ya está ocupado en {version} "
        "(las referencias entre las entidades traídas siguen el código nuevo).",
        "note",
    ),
    Message(
        "des.entity_bring_renamed",
        "«{old}» is called «{name}» here, because {version} already has an entity or a result with "
        "that name.",
        "«{old}» se llama aquí «{name}», porque {version} ya tiene una entidad o un resultado con "
        "ese nombre.",
        "warning",
    ),
    Message(
        "des.entity_bring_start_lost",
        "«{name}»: its start surface «{surface}» is a result of {source} and does not exist in "
        "{version}; the entity is left without a start surface and cannot be calculated until you "
        "choose one.",
        "«{name}»: su superficie de partida «{surface}» es un resultado de {source} y no existe en "
        "{version}; la entidad queda sin superficie de partida y no se puede calcular hasta que "
        "elija una.",
        "warning",
    ),
    Message(
        "des.entity_bring_support_lost",
        "«{name}»: its support surface «{surface}» is a result of {source} and does not exist in "
        "{version}; the entity is left without a support surface.",
        "«{name}»: su superficie de apoyo «{surface}» es un resultado de {source} y no existe en "
        "{version}; la entidad queda sin superficie de apoyo.",
        "warning",
    ),
    Message(
        "des.entity_bring_start_taken",
        "«{name}»: the surface «{surface}» is already the start of «{other}» in {version}, and each "
        "surface is the start of one entity at most; the entity is left without a start surface and "
        "cannot be calculated until you choose another.",
        "«{name}»: la superficie «{surface}» ya es la de partida de «{other}» en {version}, y de cada "
        "superficie parte una entidad como mucho; la entidad queda sin superficie de partida y no "
        "se puede calcular hasta que elija otra.",
        "warning",
    ),
    Message(
        "des.entity_bring_supports_lost",
        "«{name}»: it was declared to rest on {entities}, which are not brought; that dependency is "
        "not copied (declare it again if it still holds).",
        "«{name}»: se declaró apoyada en {entities}, que no se traen; esa dependencia no se copia "
        "(declárela de nuevo si sigue valiendo).",
        "warning",
    ),
    # Calcular una entidad traída o heredada «sin calcular» (RF-015-18, CE-015-01; hallazgo C-12; T41): lo que se rechaza.
    Message(
        "des.entity_calculate_done",
        "Entity «{entity}» ({code}) already has a result in {version}: «Calculate…» is for the entities "
        "brought or inherited without one; «Recompute the stale results» redoes a stale one; nothing is "
        "calculated.",
        "La entidad «{entity}» ({code}) ya tiene resultado en {version}: «Calcular…» es para las que se "
        "traen o se heredan sin él; «Recalcular lo obsoleto» rehace la que está obsoleta; no se calcula "
        "nada.",
    ),
    Message(
        "des.entity_calculate_missing",
        "Entity «{entity}» ({code}) cannot be calculated in {version}: «{field}» has no value (for "
        "example, when it was brought and the surface it started from was not in {version}, or another "
        "entity already started from it); discard it with «Discard…» and create the platform again "
        "with «Platform…», under another name (the name of a discarded entity stays taken); nothing is "
        "calculated.",
        "La entidad «{entity}» ({code}) no se puede calcular en {version}: «{field}» no tiene valor "
        "(por ejemplo, si al traerla la superficie de la que partía no estaba en {version} o ya partía "
        "de ella otra entidad); descártela con «Descartar…» y cree de nuevo la plataforma con "
        "«Plataforma…», con otro nombre (el de una descartada sigue ocupado); no se calcula nada.",
    ),
    # La vista previa de una entidad de diseño (T29; RF-015-26): lo que dice antes de calcular ---
    Message(
        "des.preview_entity",
        "Preview of «{entity}» ({code}) in {version}: footprint of {cells} cells ({area} m²), "
        "axis of {length} m, level from {start_level} m at the start of the axis (abscissa 0) to "
        "{end_level} m at its end, gradient {gradient} %.",
        "Vista previa de «{entity}» ({code}) en {version}: huella de {cells} celdas ({area} m²), "
        "eje de {length} m, rasante de {start_level} m al inicio del eje (abscisa 0) a "
        "{end_level} m al final, pendiente del {gradient} %.",
        "note",
    ),
    Message(
        "des.preview_entity_declares",
        "It will declare its footprint as a protected zone with a guard of {guard} m: {area} m² "
        "with the guard.",
        "Declarará su huella como una zona protegida con un resguardo de {guard} m: {area} m² con "
        "el resguardo.",
        "note",
    ),
    Message(
        "des.preview_entity_declares_none",
        "It does not protect its footprint: it declares no constraint.",
        "No protege su huella: no declara ninguna restricción.",
        "note",
    ),
    Message(
        "des.preview_entity_supported",
        "{count} designs rest on it or start from it: {items}.",
        "Se apoyan en ella o parten de ella {count} diseños: {items}.",
        "note",
        count="count",
        one_msgid="{count} design rests on it or starts from it: {items}.",
        one_es="Se apoya en ella o parte de ella {count} diseño: {items}.",
    ),
    Message(
        "des.preview_entity_supported_none",
        "Nothing rests on it and nothing starts from it.",
        "Nada se apoya en ella ni parte de ella.",
        "note",
    ),
    Message(
        "des.preview_entity_masks_missing",
        "The masks of {version} have not been compiled, so the preview of «{entity}» cannot be "
        "drawn; they are compiled before calculating (Design ▸ Legal limits and constraints ▸ "
        "Constraints…).",
        "Las máscaras de {version} no se han compilado, así que no se puede dibujar la vista "
        "previa de «{entity}»; se compilan antes de calcular (Diseño ▸ Límites y restricciones ▸ "
        "Restricciones…).",
        "warning",
    ),
    Message(
        "des.preview_entity_masks_stale",
        "The masks of {version} are stale: a constraint, a sector, a search or a parameter changed "
        "after compiling them, so the preview of «{entity}» cannot be drawn; they are compiled "
        "again before calculating.",
        "Las máscaras de {version} están obsoletas: cambió una restricción, un sector, una "
        "búsqueda o un parámetro después de compilarlas, así que no se puede dibujar la vista "
        "previa de «{entity}»; se compilan de nuevo antes de calcular.",
        "warning",
    ),
    Message(
        "des.preview_entity_uncalculated",
        "«{entity}» ({code}) has no result yet, so there is nothing to preview it from; calculate "
        "it first (menu Entity ▾ ▸ Calculate…).",
        "«{entity}» ({code}) aún no tiene resultado, así que no hay de dónde sacar su vista "
        "previa; calcúlela antes (menú Entidad ▾ ▸ Calcular…).",
        "warning",
    ),
    # Los cuatro tipos de entidad de la 016 (T03; plan 016 §5.1 y §5.5; RF-016-04 a 07, 12 a 15, 18 a 22). La detección de
    # acopios: el acopio que se rechaza (se informa en el resumen y no se registra) nombra su marca, el caso y su lugar.
    Message(
        "des.stockpile_no_cells",
        "Stockpile «{mark}» is not registered: no cell of its mark rises more than {threshold} m above its base "
        "(mark centred at x = {x} m, y = {y} m); check the mark and the surface it is detected on.",
        "El acopio «{mark}» no se registra: ninguna celda de su marca queda a más de {threshold} m sobre su base "
        "(marca centrada en x = {x} m, y = {y} m); revise la marca y la superficie sobre la que se detecta.",
        "warning",
    ),
    Message(
        "des.stockpile_no_terrain",
        "Stockpile «{mark}» is not registered: the surface has no data in its footprint (cells without data: "
        "{cells}; the first one at x = {x} m, y = {y} m); stockpiles are only detected on terrain that exists.",
        "El acopio «{mark}» no se registra: la superficie no tiene dato en su huella (celdas sin dato: {cells}; la "
        "primera en x = {x} m, y = {y} m); los acopios solo se detectan sobre terreno que existe.",
        "warning",
    ),
    Message(
        "des.stockpile_no_terrain_crown",
        "Stockpile «{mark}» is not registered: the surface has no data in its crown, the ring around its footprint "
        "where its base plane is fitted (cells without data: {cells}; the first one at x = {x} m, y = {y} m).",
        "El acopio «{mark}» no se registra: la superficie no tiene dato en su corona, el anillo alrededor de su "
        "huella donde se ajusta su plano de base (celdas sin dato: {cells}; la primera en x = {x} m, y = {y} m).",
        "warning",
    ),
    Message(
        "des.stockpile_no_crown_cells",
        "Stockpile «{mark}» is not registered: its crown, the ring from {inner} m to {outer} m around its "
        "footprint, has no cell to fit its base plane on (mark centred at x = {x} m, y = {y} m); widen the crown or "
        "give the mark a base surface.",
        "El acopio «{mark}» no se registra: su corona, el anillo de {inner} m a {outer} m alrededor de su huella, no "
        "tiene ninguna celda en la que ajustar su plano de base (marca centrada en x = {x} m, y = {y} m); amplíe la "
        "corona o dé a la marca una superficie de base.",
        "warning",
    ),
    Message(
        "des.stockpile_marks_overlap",
        "Marks «{mark}» and «{other}» overlap by {area} m² (around x = {x} m, y = {y} m): each stockpile has its "
        "own mark; redraw them so that they do not overlap; nothing is detected.",
        "Las marcas «{mark}» y «{other}» se solapan en {area} m² (en torno a x = {x} m, y = {y} m): cada acopio tiene "
        "su propia marca; dibújelas de modo que no se solapen; no se detecta nada.",
    ),
    # Lo que rechaza **antes de calcular** la preparación de la detección (T11; RF-016-02, RF-016-04, RF-015-08): la capa
    # de marcas, sus campos, sus polígonos y el nombre de la detección. Un acopio que se rechaza al calcularlo no está aquí.
    Message(
        "des.stockpile_layer_field",
        "Layer «{layer}» has no field «{value}» that can be read as «{field}» (text for the name, the material and "
        "the base; a number for the margin); the fields of the layer are: {fields}; choose another one in the dialog; "
        "nothing is calculated.",
        "La capa «{layer}» no tiene ningún campo «{value}» que se pueda leer como «{field}» (de texto para el nombre, "
        "el material y la base; un número para el margen); sus campos son: {fields}; elija otro en el diálogo; no se "
        "calcula nada.",
    ),
    Message(
        "des.stockpile_mark_repeated",
        "Layer «{layer}» has several marks called «{value}» (fid {fids}); the name of a mark is the key of its "
        "stockpile and each one needs its own; rename them in QGIS; nothing is calculated.",
        "La capa «{layer}» tiene varias marcas llamadas «{value}» (fid {fids}); el nombre de una marca es la clave de "
        "su acopio y cada una necesita el suyo; cámbieles el nombre en QGIS; no se calcula nada.",
    ),
    Message(
        "des.stockpile_mark_geometry",
        "Layer «{layer}», mark «{entity}»: its polygon is not valid ({value}: self_intersecting, it crosses itself; "
        "no_area, it has no area; hole_outside, a hole is outside its outline or inside another hole; overlap, two "
        "of its parts overlap); correct it in QGIS; nothing is calculated.",
        "Capa «{layer}», marca «{entity}»: su polígono no es válido ({value}: self_intersecting, se corta a sí "
        "mismo; no_area, no tiene área; hole_outside, un hueco queda fuera de su contorno o dentro de otro hueco; "
        "overlap, dos de sus partes se solapan); corríjalo en QGIS; no se calcula nada.",
    ),
    Message(
        "des.stockpile_mark_no_cells",
        "Layer «{layer}», mark «{entity}»: its polygon has no cell in the project grid (a cell is part of it if its "
        "centre is inside); check its position and its size; nothing is calculated.",
        "Capa «{layer}», marca «{entity}»: su polígono no tiene ninguna celda en la rejilla del proyecto (una celda "
        "es suya si su centro queda dentro); revise su posición y su tamaño; no se calcula nada.",
    ),
    Message(
        "des.stockpile_no_marks",
        "Layer «{layer}» has no marks and the candidates were not asked for, so there is nothing to detect; draw the "
        "marks in QGIS or ask for the candidates; nothing is calculated.",
        "La capa «{layer}» no tiene ninguna marca y no se pidieron los candidatos, así que no hay nada que detectar; "
        "dibuje las marcas en QGIS o pida los candidatos; no se calcula nada.",
    ),
    Message(
        "des.stockpile_name_repeated_project",
        "The name «{value}» is already used by entity «{other}» in the project; give each detection of the project "
        "its own name; nothing is calculated.",
        "El nombre «{value}» ya lo tiene la entidad «{other}» en el proyecto; dé a cada detección del proyecto su "
        "propio nombre; no se calcula nada.",
    ),
    Message(
        "des.stockpile_footprint_at_edge",
        "Stockpile «{mark}»: its footprint reaches the edge of its mark enlarged by the margin (at x = {x} m, "
        "y = {y} m), so the stockpile may be larger than its mark; the stockpile carries this note.",
        "Acopio «{mark}»: su huella llega al borde de su marca ampliada por el margen (en x = {x} m, y = {y} m), de "
        "modo que el acopio puede ser mayor que su marca; el acopio lleva esta nota.",
        "warning",
    ),
    Message(
        "des.stockpile_several_zones",
        "Stockpile «{mark}»: its mark touches more than one connected zone above its base (zones: {zones}; around "
        "x = {x} m, y = {y} m); the largest one is taken as the stockpile and the stockpile carries this note.",
        "Acopio «{mark}»: su marca toca más de una zona conexa por encima de su base (zonas: {zones}; en torno a "
        "x = {x} m, y = {y} m); se toma la mayor como acopio y el acopio lleva esta nota.",
        "warning",
    ),
    Message(
        "des.stockpile_crown_few_flat",
        "Stockpile «{mark}»: only {area} m² of its crown are flatter than {slope}°, less than the {minimum} m² "
        "needed, so the whole crown is used to fit its base plane (around x = {x} m, y = {y} m); the stockpile "
        "carries this note.",
        "Acopio «{mark}»: solo {area} m² de su corona son más llanos que {slope}°, menos de los {minimum} m² que "
        "hacen falta, así que se usa toda la corona para ajustar su plano de base (en torno a x = {x} m, "
        "y = {y} m); el acopio lleva esta nota.",
        "warning",
    ),
    Message(
        "des.stockpile_not_converged",
        "Stockpile «{mark}»: its base plane and its footprint did not settle in {turns} rounds (around x = {x} m, "
        "y = {y} m); the last ones are kept and the stockpile carries this note.",
        "Acopio «{mark}»: su plano de base y su huella no se estabilizaron en {turns} vueltas (en torno a "
        "x = {x} m, y = {y} m); se quedan los últimos y el acopio lleva esta nota.",
        "warning",
    ),
    Message(
        "des.stockpile_shared_cells",
        "Stockpiles «{mark}» and «{other}» share {area} m² of footprint (around x = {x} m, y = {y} m): each shared "
        "cell is given to the mark that contains it or, if both or neither contain it, to the nearest one.",
        "Los acopios «{mark}» y «{other}» comparten {area} m² de huella (en torno a x = {x} m, y = {y} m): cada "
        "celda común se da a la marca que la contiene o, si la contienen las dos o ninguna, a la más próxima.",
        "warning",
    ),
    Message(
        "des.stockpile_tilt_limited",
        "The base plane of stockpile «{mark}» is tilted {fitted}°, more than the maximum of {limit}° (a "
        "hypothesis): it is limited to {limit}°, keeping the azimuth of its steepest slope and resting its level on "
        "the {quantile} quantile of the residuals of its crown (around x = {x} m, y = {y} m); the stockpile carries "
        "this note.",
        "El plano de base del acopio «{mark}» está inclinado {fitted}°, más que el máximo de {limit}° (una "
        "hipótesis): se limita a {limit}°, conservando el azimut de su máxima pendiente y apoyando su nivel en el "
        "cuantil {quantile} de los residuos de su corona (en torno a x = {x} m, y = {y} m); el acopio lleva esta "
        "nota.",
        "warning",
    ),
    # El resumen de «Calcular» la detección (T12; RF-016-04 a 08, RF-015-03): la cabecera, un renglón por acopio y por
    # candidato, los candidatos y lo que quedará obsoleto al repetir la detección. Notas: lo que avisan son los de arriba.
    Message(
        "des.stockpile_summary",
        "Stockpile detection «{entity}» ({code}): {stockpiles} stockpiles with {area} m² of footprint and {volume} "
        "m³ in total.",
        "Detección de acopios «{entity}» ({code}): {stockpiles} acopios con {area} m² de huella y {volume} m³ en "
        "total.",
        "note",
        count="stockpiles",
        one_msgid="Stockpile detection «{entity}» ({code}): {stockpiles} stockpile with {area} m² of footprint and "
        "{volume} m³ in total.",
        one_es="Detección de acopios «{entity}» ({code}): {stockpiles} acopio con {area} m² de huella y {volume} m³ "
        "en total.",
    ),
    Message(
        "des.stockpile_item",
        "Stockpile «{mark}» (material {material}): footprint {area} m², volume {volume} m³, maximum thickness "
        "{thickness} m; base plane at {level} m at its centre, sloping {slope} % towards {azimuth}° (around x = {x} "
        "m, y = {y} m).",
        "Acopio «{mark}» (material {material}): huella de {area} m², volumen de {volume} m³, espesor máximo de "
        "{thickness} m; plano de base a {level} m en su centro, con una pendiente del {slope} % hacia el azimut "
        "{azimuth}° (en torno a x = {x} m, y = {y} m).",
        "note",
    ),
    Message(
        "des.stockpile_item_own_base",
        "Stockpile «{mark}» (material {material}): footprint {area} m², volume {volume} m³, maximum thickness "
        "{thickness} m; its base is the surface «{base}» (around x = {x} m, y = {y} m).",
        "Acopio «{mark}» (material {material}): huella de {area} m², volumen de {volume} m³, espesor máximo de "
        "{thickness} m; su base es la superficie «{base}» (en torno a x = {x} m, y = {y} m).",
        "note",
    ),
    Message(
        "des.stockpile_candidates",
        "{candidates} candidates without a mark found among {zones} zones that stand out: {on_marks} over a mark, "
        "{out_of_range} out of the area range and {rejected} that could not be formed; none is a stockpile until you "
        "convert it, or discard it with a reason, in the list of candidates.",
        "{candidates} candidatos sin marca entre {zones} zonas que sobresalen: {on_marks} sobre una marca, "
        "{out_of_range} fuera del rango de área y {rejected} que no se pudieron formar; ninguno es un acopio hasta "
        "que lo convierta, o lo descarte con un motivo, en la lista de candidatos.",
        "note",
        count="candidates",
        one_msgid="{candidates} candidate without a mark found among {zones} zones that stand out: {on_marks} over a "
        "mark, {out_of_range} out of the area range and {rejected} that could not be formed; it is not a stockpile "
        "until you convert it, or discard it with a reason, in the list of candidates.",
        one_es="{candidates} candidato sin marca entre {zones} zonas que sobresalen: {on_marks} sobre una marca, "
        "{out_of_range} fuera del rango de área y {rejected} que no se pudieron formar; no es un acopio hasta que lo "
        "convierta, o lo descarte con un motivo, en la lista de candidatos.",
    ),
    Message(
        "des.stockpile_candidate_item",
        "Candidate {candidate}: footprint {area} m², volume {volume} m³, base plane at {level} m at its centre, "
        "sloping {slope} % towards {azimuth}° (around x = {x} m, y = {y} m).",
        "Candidato {candidate}: huella de {area} m², volumen de {volume} m³, plano de base a {level} m en su centro, "
        "con una pendiente del {slope} % hacia el azimut {azimuth}° (en torno a x = {x} m, y = {y} m).",
        "note",
    ),
    Message(
        "des.stockpile_more_candidates",
        "… and {candidates} more candidates (in the list of candidates)",
        "… y {candidates} candidatos más (en la lista de candidatos)",
        "note",
        count="candidates",
        one_msgid="… and {candidates} more candidate (in the list of candidates)",
        one_es="… y {candidates} candidato más (en la lista de candidatos)",
    ),
    Message(
        "des.stockpile_obsolete_dependents",
        "Repeating the stockpile detection «{entity}» will make {operations} operations that depended on it stale: "
        "{items}.",
        "Al repetir la detección de acopios «{entity}», quedarán obsoletas {operations} operaciones que dependían "
        "de ella: {items}.",
        "note",
        count="operations",
        one_msgid="Repeating the stockpile detection «{entity}» will make {operations} operation that depended on "
        "it stale: {items}.",
        one_es="Al repetir la detección de acopios «{entity}», quedará obsoleta {operations} operación que dependía "
        "de ella: {items}.",
    ),
    Message(
        "des.stockpile_declared_reason",
        "declared by stockpile detection {name}",
        "declarada por la detección de acopios {name}",
        "note",
    ),
    Message(
        "des.stockpile_support_removed",
        "the stockpile detection «{name}» was discarded",
        "se descartó la detección de acopios «{name}»",
        "note",
    ),
    # La retirada de un acopio (RF-016-12 a 15).
    Message(
        "des.removal_detection_stale",
        "Stockpile «{stockpile}» cannot be removed: its detection «{detection}» is stale ({cause}); recompute the "
        "detection first; nothing is created.",
        "El acopio «{stockpile}» no se puede retirar: su detección «{detection}» está obsoleta ({cause}); "
        "recalcule antes la detección; no se crea nada.",
    ),
    Message(
        "des.removal_nothing",
        "Stockpile «{stockpile}» is no longer on the start surface: 0 m³ are removed.",
        "El acopio «{stockpile}» ya no está en la superficie de partida: se retiran 0 m³.",
        "warning",
    ),
    Message(
        "des.removal_resting",
        "{volume} m³ of material rest on stockpile «{stockpile}», placed by {items}; the stockpile is not removed "
        "without your express confirmation.",
        "Sobre el acopio «{stockpile}» se apoyan {volume} m³ de material, que puso {items}; el acopio no se retira "
        "sin su confirmación expresa.",
        "warning",
    ),
    Message(
        "des.removal_resting_unconfirmed",
        "Stockpile «{stockpile}» is not removed: {volume} m³ rest on it and the removal is not created without your "
        "express confirmation; confirm it, or decide what to do with what rests on it; nothing is created.",
        "El acopio «{stockpile}» no se retira: se apoyan en él {volume} m³ y la retirada no se crea sin su "
        "confirmación expresa; confírmela, o decida qué hacer con lo que se apoya en él; no se crea nada.",
    ),
    Message(
        "des.removal_wall",
        "Removing stockpile «{stockpile}» leaves a wall of {height} m at {angle}°, steeper than the transition angle "
        "plus the face tolerance ({limit}°), where the masks do not allow the removal (at x = {x} m, y = {y} m; "
        "created step of that edge: {step} m); it is not created without your express confirmation.",
        "Retirar el acopio «{stockpile}» deja una pared de {height} m a {angle}°, más empinada que el ángulo de "
        "transición más la tolerancia de cara ({limit}°), donde las máscaras no admiten la retirada (en "
        "x = {x} m, y = {y} m; salto creado de ese borde: {step} m); no se crea sin su confirmación expresa.",
        "warning",
    ),
    Message(
        "des.removal_wall_unconfirmed",
        "The removal of stockpile «{stockpile}» is not created: it leaves a wall of {height} m at {angle}° and it is "
        "not created without your express confirmation; confirm the wall, or change the transition or the masks; "
        "nothing is created.",
        "La retirada del acopio «{stockpile}» no se crea: deja una pared de {height} m a {angle}° y no se crea sin "
        "su confirmación expresa; confirme la pared, o cambie la transición o las máscaras; no se crea nada.",
    ),
    Message(
        "des.removal_wall_reason",
        "The wall that removing stockpile «{stockpile}» leaves, {height} m at {angle}°, is steeper than {min_angle}° "
        "and {min_height} m high or more: it needs a reason that stays recorded; nothing is created.",
        "La pared que deja retirar el acopio «{stockpile}», de {height} m a {angle}°, es más empinada que "
        "{min_angle}° y de {min_height} m o más: pide un motivo que queda registrado; no se crea nada.",
    ),
    Message(
        "des.removal_declared_reason",
        "declared by removal {name}",
        "declarada por la retirada {name}",
        "note",
    ),
    Message(
        "des.removal_support_removed",
        "the removal «{name}» was discarded",
        "se descartó la retirada «{name}»",
        "note",
    ),
    # El contrafuerte (RF-016-18 y 19).
    Message(
        "des.buttress_crown_off_anchor",
        "Layer «{layer}», buttress «{entity}»: the crown level {value} m is not on the anchor of profile "
        "«{profile}» (z₀ + n·h); the nearest anchor level is {anchor} m; no level is chosen for you; nothing is "
        "created.",
        "Capa «{layer}», contrafuerte «{entity}»: la cota de coronación {value} m no es del ancla del perfil "
        "«{profile}» (z₀ + n·h); la cota del ancla más próxima es {anchor} m; no se elige ninguna cota por usted; no "
        "se crea nada.",
    ),
    Message(
        "des.buttress_crown_below_support",
        "Layer «{layer}», buttress «{entity}»: the crown level {value} m is below its support in the whole crown "
        "zone, so there is no buttress; nothing is created.",
        "Capa «{layer}», contrafuerte «{entity}»: la cota de coronación {value} m queda por debajo de su apoyo en "
        "toda la zona de coronación, así que no hay contrafuerte; no se crea nada.",
    ),
    Message(
        "des.buttress_foot_cut",
        "Buttress «{entity}»: its foot is cut by the edge of the admitted fill: {area} m² and {volume} m³ are "
        "missing, with a created step of {step} m at x = {x} m, y = {y} m; it can still be created.",
        "Contrafuerte «{entity}»: su pie queda cortado por el borde del relleno admitido: faltan {area} m² y "
        "{volume} m³, con un salto creado de {step} m en x = {x} m, y = {y} m; se puede crear igualmente.",
        "warning",
    ),
    Message(
        "des.buttress_declared_reason",
        "declared by buttress {name}",
        "declarada por el contrafuerte {name}",
        "note",
    ),
    Message(
        "des.buttress_support_removed",
        "the buttress «{name}» was discarded",
        "se descartó el contrafuerte «{name}»",
        "note",
    ),
    # El cuerpo apoyado (RF-016-20 a 22).
    Message(
        "des.body_data_outside",
        "Supported body «{entity}»: some thickness data fall outside its footprint and are ignored (data: "
        "{ignored}).",
        "Cuerpo apoyado «{entity}»: hay datos de espesor fuera de su huella y se ignoran (datos: {ignored}).",
        "warning",
    ),
    Message(
        "des.body_far",
        "Supported body «{entity}»: {area} m² ({volume} m³) are farther than {distance} m from the thickness data "
        "(around x = {x} m, y = {y} m); it can still be created.",
        "Cuerpo apoyado «{entity}»: {area} m² ({volume} m³) quedan a más de {distance} m de los datos de espesor "
        "(en torno a x = {x} m, y = {y} m); se puede crear igualmente.",
        "warning",
    ),
    Message(
        "des.body_no_data",
        "Supported body «{entity}»: no thickness datum of layer «{layer}» falls inside its footprint "
        "«{footprint}»; nothing is created.",
        "Cuerpo apoyado «{entity}»: ningún dato de espesor de la capa «{layer}» cae en su huella «{footprint}»; no "
        "se crea nada.",
    ),
    Message(
        "des.body_all_far",
        "Supported body «{entity}»: no cell of its footprint «{footprint}» is within {distance} m of the thickness "
        "data; nothing is created.",
        "Cuerpo apoyado «{entity}»: ninguna celda de su huella «{footprint}» queda a menos de {distance} m de los "
        "datos de espesor; no se crea nada.",
    ),
    Message(
        "des.body_declared_reason",
        "declared by supported body {name}",
        "declarada por el cuerpo apoyado {name}",
        "note",
    ),
    Message(
        "des.body_support_removed",
        "the supported body «{name}» was discarded",
        "se descartó el cuerpo apoyado «{name}»",
        "note",
    ),
)

MESSAGES: Mapping[str, Message] = MappingProxyType({m.code: m for m in CATALOG})
"""Los mensajes por código (solo lectura)."""

CATALOG_ES: Mapping[str, str] = MappingProxyType(
    {msgid: es for m in CATALOG
     for msgid, es in ((m.msgid, m.es), (m.one_msgid, m.one_es)) if msgid})
"""``msgid`` → texto en español, para ``core.i18n.install`` (solo lectura): el de cada mensaje y,
si lo tiene, el de su singular."""


_RENDER_ARGUMENTS = frozenset({"language", "number"})
"""Los argumentos de :func:`render` que no son marcadores: ningún mensaje los usa como tales."""


def _check_catalog() -> None:
    """Un catálogo incoherente es un error del programa: códigos o ``msgid`` repetidos, un
    código que no es ``des.*``, una gravedad desconocida o un singular a medias (sin alguno de
    sus dos textos, con un marcador ``count`` que el plural no tiene o con otros marcadores que
    el plural) o un marcador con el nombre de un argumento de :func:`render` (``language``,
    ``number``)."""
    singular = sum(1 for m in CATALOG if m.one_msgid)
    if len(MESSAGES) != len(CATALOG) or len(CATALOG_ES) != len(CATALOG) + singular:
        raise ValueError("códigos o msgid repetidos en el catálogo del diseño")
    for message in CATALOG:
        if not message.code.startswith("des.") or message.severity not in SEVERITIES:
            raise ValueError(f"mensaje del diseño mal declarado: «{message.code}»")
        if _RENDER_ARGUMENTS & placeholders(message.es):
            raise ValueError(f"el mensaje «{message.code}» tiene un marcador con el nombre de un "
                             f"argumento de render: {', '.join(sorted(_RENDER_ARGUMENTS))}")
        if not (message.count or message.one_msgid or message.one_es):
            continue
        marks = placeholders(message.es)
        if (message.count not in marks or not message.one_msgid or not message.one_es
                or placeholders(message.one_msgid) != marks
                or placeholders(message.one_es) != marks):
            raise ValueError(f"el singular del mensaje «{message.code}» está mal declarado")


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


def render(code: str, /, *, language: str = "es", number: object = None,
           **values: object) -> str:
    """El texto de ``code`` con ``values`` en sus marcadores, en ``language`` (``"es"`` o
    ``"en"``, el ``msgid``); en singular si el mensaje lo tiene y el valor de su marcador
    ``count`` es 1 (:meth:`Message.templates`). El marcador sin valor queda «?»; los valores que
    sobran se ignoran. Los decimales salen con coma en español y con punto en inglés.

    ``number`` (spec 014, T60): el número **sin escribir** que elige el singular cuando los
    ``values`` llegan ya escritos para una persona (``preview.Notice.text``, con su espacio fino
    de miles: «1» como texto no es el número 1); sin él, el valor del marcador ``count``."""
    if language not in LANGUAGES:
        raise ValueError(f"el idioma «{language}» no es de Geoblender: {', '.join(LANGUAGES)}")
    message = lookup(code)
    if number is None and message.count:
        number = values.get(message.count)
    msgid, es = message.templates(number)
    template = es if language == "es" else msgid
    shown = _Shown({name: format_value(value, language) for name, value in values.items()})
    return template.format_map(shown)


class DesignError(GeoblenderError):
    """Error del diseño para el usuario: ``code`` del catálogo, ``msgid``, ``values`` (JSON, para
    el registro y para mostrarlo en otro idioma con :func:`render`), el objeto, el campo y el valor
    (``GeoblenderError``) y ``text`` en español, que es también ``str(error)`` y ``message``. El
    valor es el marcador ``{value}`` del texto y el campo, ``{field}``. Un código de aviso o de
    nota no es un error: :class:`ValueError`.

    ``notes`` (spec 014, T47): las notas que acompañan al error, cada una el código de una nota
    del catálogo y sus valores (JSON, como ``values``), que van detrás de su texto, una frase cada
    una (las partes de lo movido en las zonas a conservar, RF-014-08); :meth:`text_in` da el texto
    entero en un idioma. Una nota que no es una nota: :class:`ValueError`."""

    def __init__(
        self,
        code: str,
        /,
        *,
        obj: str,
        field: str,
        value: object = None,
        notes: Sequence[tuple[str, Mapping[str, object]]] = (),
        **values: object,
    ) -> None:
        message = lookup(code)
        if message.severity != "error":
            raise ValueError(f"«{code}» es un {message.severity}, no un error: no se lanza")
        for note, _values in notes:
            found = lookup(note)
            if found.severity != "note":
                raise ValueError(f"«{note}» es un {found.severity}, no una nota: no acompaña a "
                                 "un error")
        shown = {"field": field, "value": value, **values}
        self.msgid = message.msgid
        self.values: dict[str, JsonScalar] = {k: json_value(v) for k, v in shown.items()}
        self.notes: tuple[tuple[str, dict[str, JsonScalar]], ...] = tuple(
            (note, {k: json_value(v) for k, v in note_values.items()})
            for note, note_values in notes)
        self.text = " ".join((render(code, **shown),
                              *(render(note, **note_values) for note, note_values in notes)))
        super().__init__(code, self.text, obj=obj, field=field, value=value,
                         context=self.values)
        self.args = (self.text,)

    def text_in(self, language: str = "es") -> str:
        """El texto del error en ``language`` (``"es"`` o ``"en"``) con sus notas detrás, de sus
        valores en JSON (:func:`render`)."""
        return " ".join((render(self.code, language=language, **self.values),
                         *(render(note, language=language, **values)
                           for note, values in self.notes)))


class _Shown(dict[str, str]):
    """Valores ya presentados; el que falta se ve como «?» (nunca el marcador ``{…}``)."""

    def __missing__(self, key: str) -> str:
        return MISSING_VALUE

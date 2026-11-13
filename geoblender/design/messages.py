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
``des.corridor_*``, ``des.edge_*``, ``des.fill_only_*`` y ``des.refit_*``. Un campo
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
        "terrain».",
        "El {share} % de las {pairs} parejas del borde tiene un salto creado mayor que "
        "{threshold} m (al menos el {admitted} % debería quedar por debajo); el mayor, "
        "{maximum} m, en x = {x} m, y = {y} m, en {stretches} tramos. Use «Transiciones con el "
        "terreno no afectado».",
        "warning",
        count="stretches",
        one_msgid="{share} % of the {pairs} pairs of the edge have a created step greater than "
        "{threshold} m (at least {admitted} % should be within it); the largest, {maximum} m, at "
        "x = {x} m, y = {y} m, in {stretches} stretch. Use «Transitions with the untouched "
        "terrain».",
        one_es="El {share} % de las {pairs} parejas del borde tiene un salto creado mayor que "
        "{threshold} m (al menos el {admitted} % debería quedar por debajo); el mayor, "
        "{maximum} m, en x = {x} m, y = {y} m, en {stretches} tramo. Use «Transiciones con el "
        "terreno no afectado».",
    ),
    Message(
        "des.edge_surface_step",
        "«{surface}»: {share} % of the {pairs} pairs of its edge have a created step greater than "
        "{threshold} m (at least {admitted} % should be within it); the largest, {maximum} m, at "
        "x = {x} m, y = {y} m, in {stretches} stretches. Use «Transitions with the untouched "
        "terrain».",
        "«{surface}»: el {share} % de las {pairs} parejas de su borde tiene un salto creado mayor "
        "que {threshold} m (al menos el {admitted} % debería quedar por debajo); el mayor, "
        "{maximum} m, en x = {x} m, y = {y} m, en {stretches} tramos. Use «Transiciones con el "
        "terreno no afectado».",
        "warning",
        count="stretches",
        one_msgid="«{surface}»: {share} % of the {pairs} pairs of its edge have a created step "
        "greater than {threshold} m (at least {admitted} % should be within it); the largest, "
        "{maximum} m, at x = {x} m, y = {y} m, in {stretches} stretch. Use «Transitions with the "
        "untouched terrain».",
        one_es="«{surface}»: el {share} % de las {pairs} parejas de su borde tiene un salto creado "
        "mayor que {threshold} m (al menos el {admitted} % debería quedar por debajo); el mayor, "
        "{maximum} m, en x = {x} m, y = {y} m, en {stretches} tramo. Use «Transiciones con el "
        "terreno no afectado».",
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
        "{version}: use Design ▸ Quarry ▸ Refit the design to a new limit….",
        "«{surface}» deja {volume} m³ en {area} m² fuera del límite vigente de la versión "
        "{version}: use Diseño ▸ Cantera ▸ Ajustar el diseño a un límite nuevo….",
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

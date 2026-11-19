# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que dice la vista previa de semillas, dominios y restricciones (spec 013; RF-013-03, UI-06;
plan 013 §5.1, §5.5 y D-29), sin escribir nada en el proyecto.

:func:`summarize_steps` prepara, por pasos y solo leyendo, el :class:`PreviewSummary` de un cálculo
en preparación: las máscaras de la versión activa (si están al día; **no las compila**, que escribe:
si faltan o están obsoletas lo dice), las semillas y el dominio de trabajo con sus magnitudes
(celdas y área de las semillas y del dominio, porcentaje del dominio con semilla, cotas mínima y
máxima, semillas fuera del dominio, celdas de la zona sin cota), los sectores que el dominio toca
con el estado de su búsqueda de intocables y el estado de las máscaras. Lleva también lo que dibuja
la vista (las máscaras con sus zonas, el conjunto de semillas con su dominio): la vista 3D de
``bl`` no vuelve a leer el proyecto.

Con un diseño de la cantera con dos superficies (spec 014, T12; RF-014-04; plan 014 §5.1 y §5.5),
:func:`quarry_summarize_steps` prepara además, también por pasos y solo leyendo, el
:class:`QuarryPreview`: el recinto excavable, la coronación, las zonas a sostener, los fondos, las
zonas a conservar que siembran los techos de conservación y los corredores (``design.quarry``),
con sus rejillas para la vista y sus notas. El techo mismo (una envolvente ascendente) no se
calcula aquí, como la vista previa de la 013 no calcula envolventes: se calcula al «Calcular».

Con una entidad de diseño (spec 015, T12; RF-015-03, RF-015-13; plan 015 §5.3.2), el resumen de
«Calcular» (:class:`PlatformSummary`) junta las cifras, los avisos y **lo que quedará obsoleto al
crearla** (:class:`Obsolete`, :func:`obsolete_notices`), y :func:`held_notices` dice qué restricción
impide mover unas celdas: la que declara otra entidad (código ``dec__…``), con esa entidad, o una
restricción normal, con su nombre. Sin proyecto: las funciones de este módulo reciben lo que ya se
leyó (``design.entity_store`` lo lee).

Con una **detección de acopios** (spec 016, T12; RF-016-04 a 08, RF-015-03; plan 016 §5.3.2), el resumen de «Calcular» es el
:class:`StockpileSummary`: cada acopio (:class:`StockpileLine`: plano, huella, volumen, espesor máximo y notas), las marcas
**rechazadas** con su caso y su lugar (:class:`RejectedLine`; no se registran), los candidatos (:class:`CandidateLine` y
:class:`CandidateCounts`, nunca una zona sin filtrar) y lo que quedará obsoleto al repetirla (:func:`stockpile_obsolete_notices`,
con el mismo :class:`Obsolete` de la 015). Lo arma ``design.stockpile_store.stockpile_summary`` (este módulo no importa
``design.stockpiles``). Los avisos de los acopios dicen la inclinación, el límite y el umbral a la centésima
(:data:`_CODE_DECIMALS`: por mensaje, sin cambiar los de la 013, la 014 y la 015).

Y **antes de calcular** (spec 015, T29; RF-015-26; plan 015 §5.5), :func:`entity_preview_steps` prepara, por
pasos y solo leyendo, el :class:`EntityPreview` de la plataforma que se está preparando (o de una que ya
está en la versión): su huella, su eje con su sentido (la abscisa 0 en el primer vértice), la cota de la
rasante en sus extremos, lo que se le apoya (las huellas de lo que se apoya en ella, con su nombre y su
volumen) y la zona que declarará si protege, con su resguardo. Un rechazo de la preparación (RF-015-08,
RF-015-09: los mismos mensajes que «Calcular») no es un error: es el aviso de la vista previa en lugar
del dibujo.

Lo que dice son avisos y notas con código (:class:`Notice`, de ``design.messages``): el texto en
cada idioma sale de :meth:`Notice.text` y de :meth:`PreviewSummary.lines`, con la coma decimal y el
espacio fino de miles del español o el punto y la coma del inglés.
"""

from __future__ import annotations

from collections.abc import Generator, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from typing import TYPE_CHECKING, Any

import numpy as np

from ..core.constraints.model import ConstraintType
from ..core.errors import GeoblenderError
from ..core.i18n import THIN_SPACE
from ..core.project.model import Progress
from ..core.provenance.figures import FigureSpec
from ..core.versions import read as versions_read
from ..gis.masks import access
from ..gis.masks.access import MaskSet, MaskState
from ..gis.masks.compile import STEP_BUDGET_S
from ..gis.store import StoreProject, load_features
from ..gis.vector import FeatureLayer
from .messages import DesignError, lookup, render
from .model import DECLARED_PREFIX, QuarryRequest, SeedKind, Zone, ZoneKind
from .seeds import DomainSet, SeedPlan, SeedSet, pace_progress, seed_units
from .surfaces import project_frame, read_surface
from .zones import constraint_cells, layer_cells

if TYPE_CHECKING:  # design.quarry importa design.report, que importa Notice de aquí
    from ..gis.grid import Grid
    from .quarry import ConserveZone, CorridorMap, FloorMap

__all__ = [
    "BodySummary",
    "CandidateCounts",
    "CandidateLine",
    "EntityEnd",
    "EntityPreview",
    "Named",
    "Notice",
    "Obsolete",
    "ObsoleteKind",
    "PlatformSummary",
    "PreviewSummary",
    "QuarryPreview",
    "RejectedLine",
    "RemovalSummary",
    "RestingItem",
    "RestingLine",
    "SectorStatus",
    "StockpileLine",
    "StockpileSummary",
    "entity_preview_steps",
    "held_notices",
    "obsolete_names",
    "obsolete_notices",
    "quarry_summarize_steps",
    "seed_notices",
    "stockpile_obsolete_notices",
    "summarize_steps",
]

_HECTARE_M2 = 10_000.0
_DECIMALS = {"hectares": 1, "coverage": 1, "low": 1, "high": 1, "thickness": 3, "face": 2,
             "berm": 2, "step": 2, "drop": 3, "above": 3, "amount": 3, "start_level": 2,
             "end_level": 2, "gradient": 2}
"""Los decimales de los números que no son enteros (el área, entera o con uno). ``amount``: la
contrapendiente de una plataforma (spec 015, T09), que ronda la tolerancia de 0,1 m: con un decimal
«0,12 m» se leería «0,1 m», que no pasa de ella. ``start_level``, ``end_level`` y ``gradient``: la rasante
de la vista previa de una entidad (T29), al centímetro y a la centésima de por ciento."""


_CODE_DECIMALS: Mapping[str, Mapping[str, int]] = MappingProxyType({
    "des.stockpile_no_cells": MappingProxyType({"threshold": 2}),
    "des.stockpile_tilt_limited": MappingProxyType({"fitted": 2, "limit": 2, "quantile": 2}),
    "des.stockpile_item": MappingProxyType({"level": 2, "slope": 2}),
    "des.stockpile_candidate_item": MappingProxyType({"level": 2, "slope": 2}),
    "des.body_sections_large": MappingProxyType({"limit": 0}),
})
"""Los decimales de los números de **un mensaje concreto** (spec 016, T12), que mandan sobre :data:`_DECIMALS`: los avisos de
los acopios dicen una inclinación de 4,04° frente a un límite de 4° (``fitted``, ``limit``) y un umbral de huella de 0,25 m
(``threshold``) a la centésima; con el decimal de siempre se leerían «4,0° … 4,0°» y «0,2 m». Van **por código** y no por el
nombre del valor porque ``limit`` y ``threshold`` también son valores de los avisos de la 013, la 014 y la 015, que
conservan su decimal."""


def _number(value: float, decimals: int, language: str) -> str:
    """Un número en el formato de ``language`` (sin depender del idioma activo): en español, coma
    decimal y espacio fino de miles; en inglés, punto y comas."""
    text = f"{float(value):,.{decimals}f}"
    if language == "en":
        return text
    return text.translate(str.maketrans({",": THIN_SPACE, ".": ","}))


@dataclass(frozen=True, slots=True)
class Named:
    """El nombre de algo que no lo trae él mismo (spec 015, T51, H3-1: la capa de entidades o la declaración entre lo que
    queda obsoleto, que se nombraban por el identificador de su tipo): el ``code`` del mensaje del catálogo que lo dice,
    con sus ``values``. Va entre los elementos de una lista de un aviso y se escribe, entre « », al mostrarlo, en el idioma
    pedido."""

    code: str
    values: Mapping[str, object] = field(default_factory=dict)

    def text(self, language: str = "es") -> str:
        return f"«{render(self.code, language=language, **_shown(self.values, language))}»"


def _shown(values: Mapping[str, object], language: str, places: Mapping[str, int] | None = None
           ) -> dict[str, str]:
    """Los valores de un aviso ya escritos para una persona (``places``: los decimales propios de su mensaje, que mandan
    sobre los de siempre; :data:`_CODE_DECIMALS`)."""
    found: dict[str, str] = {}
    for name, value in values.items():
        if isinstance(value, bool):
            found[name] = str(value)
        elif isinstance(value, int):
            found[name] = _number(value, 0, language)
        elif isinstance(value, float):
            if places is not None and name in places:
                decimals = places[name]
            else:
                decimals = (0 if value.is_integer() else 1) if name == "area" else _DECIMALS.get(
                    name, 1)
            found[name] = _number(value, decimals, language)
        elif isinstance(value, tuple | list):
            found[name] = ", ".join(item.text(language) if isinstance(item, Named) else str(item)
                                    for item in value)
        else:
            found[name] = str(value)
    return found


@dataclass(frozen=True, slots=True)
class Notice:
    """Un aviso o una nota de la vista previa: el ``code`` de ``design.messages`` y sus ``values``
    (sin escribir: los números llegan como números y se escriben al mostrarlos)."""

    code: str
    values: Mapping[str, object] = field(default_factory=dict)

    @property
    def severity(self) -> str:
        """``"note"`` o ``"warning"`` (los errores se lanzan, no se avisan)."""
        return lookup(self.code).severity

    def text(self, language: str = "es") -> str:
        """El texto del aviso en ``language`` (``"es"`` o ``"en"``): sus números, escritos para
        una persona, y, si el mensaje cuenta algo, el singular elegido con el número **sin
        escribir** (spec 014, T60: «en 1 zona», no «en 1 zonas»)."""
        message = lookup(self.code)
        number = self.values.get(message.count) if message.count else None
        return render(self.code, language=language, number=number,
                      **_shown(self.values, language, _CODE_DECIMALS.get(self.code)))


@dataclass(frozen=True, slots=True)
class SectorStatus:
    """Un sector de búsqueda con el estado que enseña la vista previa: si el dominio de trabajo lo
    toca (``touched``, D-15) y si su búsqueda de intocables está pendiente (``pending``)."""

    code: str
    name: str
    touched: bool
    pending: bool


@dataclass(frozen=True, slots=True, eq=False)
class PreviewSummary:
    """La vista previa de un cálculo (RF-013-03): la ``version`` (su código), el estado de sus
    máscaras (``masks_state``) y, solo si están al día, las máscaras (``masks``), las semillas
    con su dominio (``seeds``), los ``sectors`` con su estado y los ``notices`` en el orden en que
    se enseñan; sin máscaras al día no hay semillas ni dominio ni sectores, y se dice."""

    version: str
    masks_state: MaskState
    masks: MaskSet | None
    seeds: SeedSet | None
    sectors: tuple[SectorStatus, ...]
    notices: tuple[Notice, ...]

    @property
    def domain(self) -> DomainSet | None:
        """El dominio de trabajo, si lo hay."""
        return None if self.seeds is None else self.seeds.domain

    @property
    def coverage_pct(self) -> float | None:
        """El porcentaje del dominio de trabajo que tiene semilla (0 a 100), o ``None`` si no hay
        dominio o está vacío."""
        if self.seeds is None or self.seeds.domain.cells == 0:
            return None
        inside = self.seeds.cells - self.seeds.outside_domain
        return 100.0 * inside / self.seeds.domain.cells

    def lines(self, language: str = "es") -> tuple[str, ...]:
        """Todo lo que dice la vista previa, línea a línea, en ``language``."""
        return tuple(notice.text(language) for notice in self.notices)

    def warnings(self, language: str = "es") -> tuple[str, ...]:
        """Solo los avisos, en ``language``."""
        return tuple(notice.text(language) for notice in self.notices
                     if notice.severity == "warning")


def seed_notices(plan: SeedPlan, seeds: SeedSet) -> tuple[Notice, ...]:
    """Los avisos de unas semillas ya formadas de ``plan``: las que caen fuera del dominio de trabajo
    (se conservan, la envolvente las usa) y las celdas de la zona sin cota. Los comparten la vista
    previa y el cálculo (``design.steps``)."""
    found = []
    if seeds.outside_domain:
        found.append(Notice("des.seeds_outside_domain", {
            "cells": seeds.outside_domain, "area": seeds.outside_area_m2}))
    if seeds.nodata_cells:
        source = plan.seeds
        name = source.surface if SeedKind(source.kind) is SeedKind.SURFACE else source.grid
        found.append(Notice("des.seeds_without_data", {
            "cells": seeds.nodata_cells, "area": seeds.nodata_cells * seeds.geometry.cell_area,
            "surface": name or "—"}))
    return tuple(found)


def _notices(version: str, state: MaskState, plan: SeedPlan, masks: MaskSet | None,
             seeds: SeedSet | None) -> tuple[Notice, ...]:
    """Lo que dice el resumen, en orden: semillas, dominio, avisos de las semillas y de los
    sectores."""
    if state is not MaskState.CURRENT or masks is None or seeds is None:
        code = ("des.preview_masks_missing" if state is MaskState.MISSING
                else "des.preview_masks_stale")
        return (Notice(code, {"version": version}),)
    domain = seeds.domain
    hectares = domain.area_m2 / _HECTARE_M2
    found = []
    if seeds.cells:
        assert seeds.min_m is not None and seeds.max_m is not None
        found.append(Notice("des.preview_seeds", {
            "cells": seeds.cells, "area": seeds.area_m2, "low": seeds.min_m,
            "high": seeds.max_m, "hectares": hectares, "outside": seeds.outside_domain}))
    else:
        found.append(Notice("des.preview_seeds_none", {"hectares": hectares}))
    inside = seeds.cells - seeds.outside_domain
    if domain.cells:
        found.append(Notice("des.preview_domain", {
            "cells": domain.cells, "area": domain.area_m2,
            "coverage": 100.0 * inside / domain.cells}))
    else:
        found.append(Notice("des.preview_domain_empty"))
    found.append(Notice("des.preview_masks_current", {"version": version}))
    found.extend(seed_notices(plan, seeds))
    if domain.touched:
        found.append(Notice("des.preview_sectors",
                            {"sectors": tuple(sector.name for sector in domain.touched)}))
        found.extend(Notice("des.preview_sector_pending", {"sector": sector.name})
                     for sector in domain.touched if sector.code in masks.pending_sectors)
    if domain.sectors and domain.unassigned_cells:
        found.append(Notice("des.preview_unassigned", {
            "cells": domain.unassigned_cells, "area": domain.unassigned_area_m2}))
    return tuple(found)


def _statuses(masks: MaskSet, domain: DomainSet) -> tuple[SectorStatus, ...]:
    return tuple(SectorStatus(sector.code, sector.name, sector in domain.touched,
                              sector.code in masks.pending_sectors)
                 for sector in domain.sectors)


def _summary_units(project: StoreProject, plan: SeedPlan, version_uid: str
                   ) -> Generator[None, None, PreviewSummary]:
    state, _pending = access.mask_state(project, version_uid)
    with project.read() as conn:
        version = versions_read.version(conn, version_uid)
    assert version is not None  # mask_state ya lo comprobó
    yield
    masks: MaskSet | None = None
    seeds: SeedSet | None = None
    if state is MaskState.CURRENT:
        masks = yield from access.load_masks_steps(project, version.uid)
        seeds = yield from seed_units(project, plan, masks)
    notices = _notices(version.code, state, plan, masks, seeds)
    sectors = () if masks is None or seeds is None else _statuses(masks, seeds.domain)
    yield
    return PreviewSummary(version.code, state, masks, seeds, sectors, notices)


def summarize_steps(project: StoreProject, plan: SeedPlan, version_uid: str, *,
                    budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """El :class:`PreviewSummary` de ``plan`` (``plan.seeds`` y ``plan.domain``) para la versión
    activa ``version_uid`` (uid o código), por pasos de ``budget_s`` como mucho: el último
    ``Progress`` lleva el resumen. Solo lee: no compila las máscaras que falten ni escribe nada en
    el proyecto (RF-013-03). Rechaza (al avanzar) lo que rechazan las semillas y el dominio
    (``build_seeds_steps``); unas máscaras que no están al día no son un error: se dicen en el
    resumen."""
    return pace_progress(_summary_units(project, plan, version_uid), budget_s, phase="preview",
                         running="Preparando la vista previa…", finished="Vista previa lista",
                         total=10)


# --- La cantera con dos superficies (spec 014, T12; RF-014-04) ---------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class QuarryPreview:
    """La vista previa de un diseño de la cantera con dos superficies (RF-014-04): la ``version``
    (su código), el estado de sus máscaras (``masks_state``) y, solo si están al día, las máscaras
    (``masks``), la superficie de partida (``start``, m, float64), el recinto excavable (``area``,
    A1), la coronación (``crown``, el anillo exterior de A2), las zonas a sostener (``hold``,
    intocables y sin corte), los fondos (``floors``, A4, si se piden), las zonas a conservar que
    siembran los techos (``conserve``, A5) y los corredores (``corridors``, A6, si se piden),
    todas en la rejilla de las máscaras; y los ``notices`` en el orden en que se enseñan. Sin
    máscaras al día no hay nada de eso, y se dice."""

    version: str
    masks_state: MaskState
    masks: MaskSet | None
    start: np.ndarray | None
    area: np.ndarray | None
    crown: np.ndarray | None
    hold: np.ndarray | None
    floors: FloorMap | None
    conserve: tuple[ConserveZone, ...]
    corridors: CorridorMap | None
    notices: tuple[Notice, ...]

    def lines(self, language: str = "es") -> tuple[str, ...]:
        """Todo lo que dice la vista previa, línea a línea, en ``language``."""
        return tuple(notice.text(language) for notice in self.notices)

    def warnings(self, language: str = "es") -> tuple[str, ...]:
        """Solo los avisos, en ``language``."""
        return tuple(notice.text(language) for notice in self.notices
                     if notice.severity == "warning")


def _features(project: StoreProject, name: str) -> FeatureLayer:
    """La capa de entidades ``name`` del proyecto (solo lee); ``ValueError`` si no es una capa de
    entidades (``gis_fea_``)."""
    layer = load_features(project, name)
    if not isinstance(layer, FeatureLayer):
        raise ValueError(f"«{name}» no es una capa de entidades del proyecto (gis_fea_)")
    return layer


def _conserve_mask(project: StoreProject, masks: MaskSet, zone: Zone) -> np.ndarray:
    """Las celdas de una zona a conservar: una restricción de la 012 o una capa de polígonos."""
    kind = ZoneKind(zone.kind)
    if kind not in (ZoneKind.CONSTRAINT, ZoneKind.LAYER) or not zone.name:
        raise ValueError(f"una zona a conservar es una restricción o una capa con su nombre, no "
                         f"{zone!r}")
    if kind is ZoneKind.CONSTRAINT:
        return constraint_cells(masks, zone.name)
    return layer_cells(project, zone.name, masks.grid)


def _cells(mask: np.ndarray, cell_area: float) -> dict[str, object]:
    cells = int(np.count_nonzero(mask))
    return {"cells": cells, "area": cells * cell_area}


def _quarry_notices(ring_cells: int, area: np.ndarray, crown: np.ndarray, hold: np.ndarray,
                    floors: FloorMap | None, conserve: tuple[ConserveZone, ...],
                    corridors: CorridorMap | None, cell_area: float) -> list[Notice]:
    """Las notas de las piezas de la cantera, en el orden en que se enseñan."""
    cells = int(np.count_nonzero(area))
    found = [
        Notice("des.quarry_preview_area", {"cells": cells, "area": cells * cell_area,
                                           "hectares": cells * cell_area / _HECTARE_M2}),
        Notice("des.quarry_preview_crown", {"ring": ring_cells, **_cells(crown, cell_area)}),
        Notice("des.quarry_preview_hold", _cells(hold, cell_area)),
    ]
    if floors is not None:
        levels = floors.levels or (float("nan"),)
        found.append(Notice("des.quarry_preview_floors", {
            "layer": floors.layer, "field": floors.field, "polygons": len(floors.fids),
            "cells": sum(floors.cells), "area": floors.area_m2, "low": min(levels),
            "high": max(levels)}))
    if conserve:
        union = np.zeros(area.shape, dtype=bool)
        for zone in conserve:
            union |= zone.mask
        found.append(Notice("des.quarry_preview_ceilings", {
            "zones": tuple(zone.name for zone in conserve), **_cells(union, cell_area)}))
    if corridors is not None:
        found.append(Notice("des.quarry_preview_corridors", {
            "layer": corridors.floors.layer, "corridors": len(corridors.floors.fids),
            "cells": sum(corridors.floors.cells), "area": corridors.floors.area_m2,
            "length": float(sum(corridors.axes_m))}))
    return found


def _quarry_warnings(start: np.ndarray, floors: FloorMap | None,
                     conserve: tuple[ConserveZone, ...], corridors: CorridorMap | None,
                     cell_area: float) -> list[Notice]:
    """Los avisos que el cálculo dará de las capas, para verlos antes: los fondos y los
    corredores, que son fondos (RF-014-09; T42), por encima del terreno (RF-014-05: un solo aviso
    con el área de los dos, cada celda una vez), las zonas a conservar sin dato de terreno
    (RF-014-07) y los corredores más largos que su eje más su ancho (RF-014-10)."""
    from .quarry import floors_above_terrain  # al usarlo: quarry → report → preview

    found = []
    maps = [item for item in (floors, None if corridors is None else corridors.floors)
            if item is not None]
    if maps:
        above = floors_above_terrain(maps[0], start, *maps[1:])
        if above.cells:
            found.append(Notice("des.floor_above_terrain", {"area": above.area_m2}))
    blank = ~np.isfinite(start)
    for zone in conserve:
        nodata = int(np.count_nonzero(zone.mask & blank))
        if nodata:
            found.append(Notice("des.conserve_nodata", {"zone": zone.name,
                                                        "area": nodata * cell_area}))
    if corridors is not None:
        for fid, axis, length, width in zip(corridors.floors.fids, corridors.axes_m,
                                            corridors.lengths_m, corridors.widths_m,
                                            strict=True):
            if length > axis + width:
                found.append(Notice("des.corridor_too_long", {
                    "corridor": fid, "length": length, "axis": axis, "width": width}))
    return found


def _quarry_units(project: StoreProject, request: QuarryRequest, version_uid: str,
                  ring_cells: int) -> Generator[None, None, QuarryPreview]:
    from . import quarry  # al usarlo: quarry → report → preview (Notice)

    state, _pending = access.mask_state(project, version_uid)
    with project.read() as conn:
        version = versions_read.version(conn, version_uid)
    assert version is not None  # mask_state ya lo comprobó
    yield
    if state is not MaskState.CURRENT:
        code = ("des.preview_masks_missing" if state is MaskState.MISSING
                else "des.preview_masks_stale")
        return QuarryPreview(version.code, state, None, None, None, None, None, None, (), None,
                             (Notice(code, {"version": version.code}),))
    masks: MaskSet = yield from access.load_masks_steps(project, version.uid)
    start = read_surface(project, request.start, version_uid=version.uid,
                         expect=project_frame(project), role="superficie de partida").values
    yield
    geometry = masks.grid
    area = quarry.excavation_area(masks, start, version=version.code)
    crown = quarry.crown_ring(area, start, ring_cells)
    hold = quarry.hold_zones(masks)
    yield
    floors = None
    if request.floors is not None:
        floors = quarry.floor_map(_features(project, request.floors.layer), request.floors, start,
                                  geometry)
        yield
    conserve = []
    for zone in request.conserve:
        assert zone.name is not None  # _conserve_mask lo comprueba
        conserve.append(quarry.ConserveZone(zone.name, _conserve_mask(project, masks, zone)))
        yield
    corridors = None
    if request.corridors is not None:
        corridors = quarry.corridor_cells(_features(project, request.corridors.layer),
                                          request.corridors, geometry, start=start)
        yield
    cell_area = geometry.cell_area
    zones = tuple(conserve)
    notices = [Notice("des.preview_masks_current", {"version": version.code}),
               *_quarry_notices(ring_cells, area, crown, hold, floors, zones, corridors,
                                cell_area),
               *_quarry_warnings(start, floors, zones, corridors, cell_area)]
    return QuarryPreview(version.code, state, masks, start, area, crown, hold, floors, zones,
                         corridors, tuple(notices))


def quarry_summarize_steps(project: StoreProject, request: QuarryRequest, version_uid: str, *,
                           ring_cells: int, budget_s: float = STEP_BUDGET_S
                           ) -> Iterator[Progress]:
    """El :class:`QuarryPreview` de ``request`` (su superficie de partida, sus fondos, sus zonas a
    conservar y sus corredores) para la versión activa ``version_uid`` (uid o código), por pasos
    de ``budget_s`` como mucho: el último ``Progress`` lleva el resumen (RF-014-04). ``ring_cells``
    es el ancho del anillo de coronación (``des.quarry.crown_ring_cells``, el valor que resuelve
    quien llama, como lo leerá la operación). Solo lee: no compila las máscaras que falten ni
    escribe nada en el proyecto. Rechaza (al avanzar) lo que rechazan el recinto vacío
    (``des.quarry_area_empty``), el anillo fuera de rango, los fondos (``floor_map``) y los
    corredores (``corridor_cells``); unas máscaras que no están al día no son un error: se dicen
    en el resumen."""
    return pace_progress(_quarry_units(project, request, version_uid, ring_cells), budget_s,
                         phase="preview", running="Preparando la vista previa…",
                         finished="Vista previa lista", total=10)


# --- El resumen de una entidad de diseño (spec 015, T12; RF-015-03, RF-015-13) -----------------


class ObsoleteKind(StrEnum):
    """Por qué algo quedará obsoleto al crear una entidad (RF-015-03, RF-015-16): ``MASKS`` (las máscaras
    de la versión, porque la entidad que protege declara una restricción y se compilan de nuevo),
    ``CONSUMER`` (lo que usó esas máscaras, y lo que depende de ello), ``SUCCESSOR`` (la entidad que
    parte de la superficie donde se inserta la nueva y las que le siguen, RF-015-05) y ``DEPENDENT``
    (lo que dependía de la operación que sustituye la nueva)."""

    MASKS = "masks"
    CONSUMER = "consumer"
    SUCCESSOR = "successor"
    DEPENDENT = "dependent"


@dataclass(frozen=True, slots=True)
class Obsolete:
    """Algo que quedará obsoleto al crear la entidad: su ``kind``, su ``name`` (el de la operación o la
    entidad; el código de la versión en las máscaras), el tipo de su operación (``op_type``, vacío
    en una entidad sin calcular), su ``uid`` (de la operación; ``""`` si no la tiene) y, si la operación no
    trae su nombre en sus ajustes y ``name`` es el de su tipo, el ``label`` (spec 015, T51; H3-1): el código del
    mensaje de ``design.messages`` que la nombra para una persona («la capa de entidades de V01»)."""

    kind: ObsoleteKind
    name: str
    op_type: str = ""
    uid: str = ""
    label: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", ObsoleteKind(self.kind))


SUMMARY_ITEMS = 10
"""Los nombres de lo que quedará obsoleto que enseña cada nota del resumen; el resto, un «…» (la
lista entera va en :attr:`PlatformSummary.obsolete`). No es una cifra minera: es lo que cabe en la
ventana."""


@dataclass(frozen=True, slots=True)
class PlatformSummary:
    """El resumen de «Calcular» una plataforma (RF-015-03): su ``name`` y su ``code`` (``PLT-001``), la
    ``version`` (su código), las ``figures`` que se registrarán (CALCULADO, con su unidad y el ámbito
    de la entidad), los ``notices`` en el orden en que se enseñan (los avisos y notas del cálculo, lo
    que no se mueve por una restricción y, al final, lo que quedará obsoleto) y ``obsolete``, lo que
    quedará obsoleto al crearla, con su lista entera."""

    name: str
    code: str
    version: str
    figures: tuple[FigureSpec, ...]
    notices: tuple[Notice, ...]
    obsolete: tuple[Obsolete, ...] = ()

    def lines(self, language: str = "es") -> tuple[str, ...]:
        """Todo lo que dice el resumen, línea a línea, en ``language``."""
        return tuple(notice.text(language) for notice in self.notices)

    def warnings(self, language: str = "es") -> tuple[str, ...]:
        """Solo los avisos, en ``language``."""
        return tuple(notice.text(language) for notice in self.notices
                     if notice.severity == "warning")


def obsolete_names(items: Iterable[Obsolete], version: str) -> tuple[str | Named, ...]:
    """Los nombres de ``items`` entre «», los :data:`SUMMARY_ITEMS` primeros y, si hay más, un «…»: el de una operación
    sin nombre propio (``label``), como :class:`Named` de ``version`` (se escribe en el idioma de quien lo lee), y los
    demás, tal cual (spec 015, T51, H3-1: no el identificador de su tipo)."""
    names: list[str | Named] = [Named(item.label, {"version": version}) if item.label else f"«{item.name}»"
                                for item in items]
    return tuple(names[:SUMMARY_ITEMS]) + (("…",) if len(names) > SUMMARY_ITEMS else ())


def obsolete_notices(entity: str, version: str, items: Iterable[Obsolete]) -> tuple[Notice, ...]:
    """Las notas de lo que quedará obsoleto al crear la entidad ``entity`` en la versión ``version``
    (RF-015-03), por orden: las máscaras (si ``items`` las lleva), lo que las usó, las entidades de la
    cadena que siguen a la que se inserta y lo que dependía de la operación sustituida; cada una con
    su cuenta (con singular) y los nombres. Ninguna si no hay nada."""
    by_kind: dict[ObsoleteKind, list[Obsolete]] = {kind: [] for kind in ObsoleteKind}
    for item in items:
        by_kind[item.kind].append(item)
    found: list[Notice] = []
    if by_kind[ObsoleteKind.MASKS]:
        found.append(Notice("des.entity_obsolete_masks", {"entity": entity, "version": version}))
    for kind, code, count in ((ObsoleteKind.CONSUMER, "des.entity_obsolete_consumers", "operations"),
                              (ObsoleteKind.SUCCESSOR, "des.entity_obsolete_successor", "entities"),
                              (ObsoleteKind.DEPENDENT, "des.entity_obsolete_dependents",
                               "operations")):
        if by_kind[kind]:
            found.append(Notice(code, {"entity": entity, count: len(by_kind[kind]),
                                       "items": obsolete_names(by_kind[kind], version)}))
    return tuple(found)


# --- El resumen de una detección de acopios (spec 016, T12; RF-016-04 a 08, RF-015-03) ----------


@dataclass(frozen=True, slots=True)
class StockpileLine:
    """Un acopio **registrado** en el resumen de «Calcular» la detección (RF-016-04, RF-016-02): su clave y su ``name`` (los de
    su marca), su ``material`` (``None``: sin material), la ``base_surface`` de la que sale su base si es propia (RF-016-03; si no,
    ``None`` y la base es su plano), el área de su huella (``area_m2``), su volumen (``volume_m3``), su espesor máximo
    (``thickness_max_m``), el plano en su centro (``plane_level_m``: la cota, ``plane_slope_percent``, ``plane_azimuth_deg`` y
    ``plane_tilt_deg``; ninguno si la base es propia), el lugar de su centro (``x``, ``y``: absolutas, m: el de «ir a») y sus
    ``notes`` (los avisos y notas de RF-016-05, 06 y 07, con su marca y su lugar)."""

    key: str
    name: str
    material: str | None
    base_surface: str | None
    area_m2: float
    volume_m3: float
    thickness_max_m: float
    plane_level_m: float | None
    plane_slope_percent: float | None
    plane_azimuth_deg: float | None
    plane_tilt_deg: float | None
    x: float
    y: float
    notes: tuple[Notice, ...] = ()


@dataclass(frozen=True, slots=True)
class RejectedLine:
    """Una marca que no da acopio y **no se registra** (RF-016-04): su clave y su ``name`` y el aviso con el caso y el lugar
    (``notice``: un ``des.stockpile_*`` con la marca, ``x`` e ``y``)."""

    key: str
    name: str
    notice: Notice


@dataclass(frozen=True, slots=True)
class CandidateLine:
    """Un candidato sin marca del resumen (RF-016-08): su ``number`` (desde 1, en el orden de lectura de su zona), el área de su
    huella (``area_m2``), su volumen (``volume_m3``), su plano en el centro (``plane_level_m``, ``plane_slope_percent`` y
    ``plane_azimuth_deg``) y el lugar de su centro (``x``, ``y``: absolutas, m)."""

    number: int
    area_m2: float
    volume_m3: float
    plane_level_m: float
    plane_slope_percent: float
    plane_azimuth_deg: float
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class CandidateCounts:
    """Lo que la búsqueda de candidatos descartó **sin listarlo nunca** (RF-016-08, error 64): las ``zones`` que salieron de la
    apertura antes de filtrar, las que tienen marca (``on_marks``), las que no llegan al área mínima (``too_small``) o pasan de la
    máxima (``too_large``) y las que pasan los filtros pero no se pudieron formar (``rejected``)."""

    zones: int
    on_marks: int
    too_small: int
    too_large: int
    rejected: int

    @property
    def filtered(self) -> int:
        """Las zonas que descartó el filtro del área."""
        return self.too_small + self.too_large


@dataclass(frozen=True, slots=True)
class StockpileSummary:
    """El resumen de «Calcular» una detección de acopios (RF-015-03, RF-016-04 a 08): su ``name`` y su ``code`` (``STK-001``), la
    ``version`` (su código; ``None`` si es **del proyecto**) y el ``scope`` (``project`` o ``version``), las ``figures`` que se
    registrarán (CALCULADO, con su ámbito), los acopios (``stockpiles``), las marcas que no dan acopio (``rejected``) y, si se
    pidieron, los candidatos (``candidates``, con la lista entera, y ``counts``; ambos ``None`` si no se pidieron), los
    ``notices`` en el orden en que se enseñan (la cabecera, las marcas rechazadas, cada acopio con sus avisos y notas, los
    candidatos y, al final, lo que quedará obsoleto) y ``obsolete``, lo que quedará obsoleto al crearla, con su lista entera."""

    name: str
    code: str
    version: str | None
    scope: str
    figures: tuple[FigureSpec, ...]
    stockpiles: tuple[StockpileLine, ...]
    rejected: tuple[RejectedLine, ...]
    candidates: tuple[CandidateLine, ...] | None
    counts: CandidateCounts | None
    notices: tuple[Notice, ...]
    obsolete: tuple[Obsolete, ...] = ()

    def lines(self, language: str = "es") -> tuple[str, ...]:
        """Todo lo que dice el resumen, línea a línea, en ``language``."""
        return tuple(notice.text(language) for notice in self.notices)

    def warnings(self, language: str = "es") -> tuple[str, ...]:
        """Solo los avisos, en ``language``."""
        return tuple(notice.text(language) for notice in self.notices if notice.severity == "warning")


def stockpile_obsolete_notices(entity: str, version: str, items: Iterable[Obsolete]) -> tuple[Notice, ...]:
    """La nota de lo que quedará obsoleto al **repetir** la detección ``entity`` (RF-015-03, RF-016-10, RF-015-16): las
    operaciones que dependían de lo que escribió la anterior (``ObsoleteKind.DEPENDENT``), con su cuenta (con singular) y los
    nombres de las :data:`SUMMARY_ITEMS` primeras. Ninguna si no hay nada. Como :func:`obsolete_notices` para una plataforma,
    con el texto de una detección: una detección no protege ni se inserta en ninguna cadena, así que solo tiene esta clase."""
    found = [item for item in items if item.kind is ObsoleteKind.DEPENDENT]
    if not found:
        return ()
    return (Notice("des.stockpile_obsolete_dependents", {"entity": entity, "operations": len(found),
                                                         "items": obsolete_names(found, version)}),)


# --- El resumen de la retirada de un acopio (spec 016, T20; RF-016-11 a 15, RF-015-03) ----------


@dataclass(frozen=True, slots=True)
class RestingLine:
    """Una fila de la lista **única** de lo que se apoya en el acopio que se retira (RF-016-14, RF-015-17): el ``name`` de quien lo
    puso (la entidad o el diseño de la versión o, de otra versión o del proyecto, el de la superficie), su ``kind`` (el tipo, en
    español: ``None`` si es una superficie), los ``volume_m3`` que puso sobre el acopio y las ``cells`` de su huella donde lo puso."""

    name: str
    kind: str | None
    volume_m3: float
    cells: int


@dataclass(frozen=True, slots=True)
class RemovalSummary:
    """El resumen de «Calcular» la retirada de un acopio (RF-015-03, RF-016-13 a 15): su ``name`` y su ``code`` (``RMV-001``), la
    ``version`` (su código), el acopio (``stockpile``: su referencia, ``STK-001#Acopio 1``, y ``stockpile_name``), las ``figures``
    que se registrarán, **la lista de lo que se le apoya** (``resting``, antes de calcular, sin escribir nada), la pared
    (``wall_height_m`` y ``wall_angle_deg`` del tramo más alto; ``None`` sin pared), si pide confirmar lo apoyado
    (``needs_resting_confirmation``), la pared (``needs_wall_confirmation``) y un motivo (``needs_wall_reason``: CA-9), los
    ``notices`` en el orden en que se enseñan (lo apoyado, los avisos de la retirada y, al final, lo que quedará obsoleto) y
    ``obsolete``, lo que quedará obsoleto al crearla (si sustituye a otra)."""

    name: str
    code: str
    version: str
    stockpile: str
    stockpile_name: str
    figures: tuple[FigureSpec, ...]
    resting: tuple[RestingLine, ...]
    wall_height_m: float | None
    wall_angle_deg: float | None
    needs_resting_confirmation: bool
    needs_wall_confirmation: bool
    needs_wall_reason: bool
    notices: tuple[Notice, ...]
    obsolete: tuple[Obsolete, ...] = ()

    def lines(self, language: str = "es") -> tuple[str, ...]:
        """Todo lo que dice el resumen, línea a línea, en ``language``."""
        return tuple(notice.text(language) for notice in self.notices)

    def warnings(self, language: str = "es") -> tuple[str, ...]:
        """Solo los avisos, en ``language``."""
        return tuple(notice.text(language) for notice in self.notices if notice.severity == "warning")


# --- El resumen del cuerpo apoyado (spec 016, T25; RF-016-20 a 22, RF-015-03) ---------------------------------


@dataclass(frozen=True, slots=True)
class BodySummary:
    """El resumen de «Calcular» un cuerpo apoyado (RF-015-03, RF-016-20 a 22): su ``name`` y su ``code`` (``BDY-001``), la ``version``
    (su código), su ``sense`` (``on_base`` o ``under_roof``), la capa de los datos (``data_layer``), las ``figures`` que se
    registrarán (el volumen, el espesor máximo, lo lejano y lo ignorado), el volumen (``volume_m3``), el espesor máximo
    (``thickness_max_m``) y su lugar (``thickness_max_x``, ``thickness_max_y``), el área (``far_m2``) y el volumen (``far_m3``) de lo
    lejano de los datos con su lugar (``far_x``, ``far_y``; ``None`` sin lo lejano), los ``notices`` en el orden en que se enseñan (los
    avisos del cálculo —lo ignorado, lo lejano, lo que no tiene superficie conocida, lo triangulado— y, al final, lo que quedará
    obsoleto) y ``obsolete``, lo que quedará obsoleto al crearlo (si sustituye a otro)."""

    name: str
    code: str
    version: str
    sense: str
    data_layer: str
    figures: tuple[FigureSpec, ...]
    volume_m3: float
    thickness_max_m: float
    thickness_max_x: float
    thickness_max_y: float
    far_m2: float
    far_m3: float
    far_x: float | None
    far_y: float | None
    notices: tuple[Notice, ...]
    obsolete: tuple[Obsolete, ...] = ()

    def lines(self, language: str = "es") -> tuple[str, ...]:
        """Todo lo que dice el resumen, línea a línea, en ``language``."""
        return tuple(notice.text(language) for notice in self.notices)

    def warnings(self, language: str = "es") -> tuple[str, ...]:
        """Solo los avisos, en ``language``."""
        return tuple(notice.text(language) for notice in self.notices if notice.severity == "warning")


_INNER = ":inner"
"""El sufijo de la zona de la banda hacia dentro de un límite legal (``MaskSet.zone``)."""


def _rule(masks: MaskSet, code: str) -> tuple[bool, bool] | None:
    """Si la zona ``code`` de ``masks`` impide cortar y rellenar (``None`` si no impide nada o no se
    sabe su tipo: un límite, «preferible no afectar»…). La banda hacia dentro de un límite legal
    (``<código>:inner``) impide cortar; un intocable o una exclusión, las dos cosas."""
    if code.endswith(_INNER):
        return True, False
    value = masks.ctypes.get(code)
    try:
        kind = ConstraintType(value)
    except ValueError:
        return None
    cut = kind.forbids_cut or kind.removes_from_domain
    fill = kind.forbids_fill or kind.removes_from_domain
    return (cut, fill) if cut or fill else None


def _place(grid: Grid, origin: tuple[int, int], mask: np.ndarray) -> tuple[float, float]:
    """El centro absoluto (m, float64) de la primera celda de ``mask`` de norte a sur y de oeste a
    este, al cm; ``origin`` es la fila y la columna de la rejilla donde empieza ``mask``."""
    rows, cols = np.nonzero(mask)
    x = grid.west + (int(cols[0]) + origin[1] + 0.5) * grid.dx
    y = grid.north - (int(rows[0]) + origin[0] + 0.5) * grid.dy
    return round(float(x), 2), round(float(y), 2)


def held_notices(entity: str, masks: MaskSet, window: tuple[slice, slice], *, cut: np.ndarray,
                 fill: np.ndarray, edge: np.ndarray, names: Mapping[str, str],
                 declared: Mapping[str, str]) -> tuple[Notice, ...]:
    """**Lo que la entidad ``entity`` no mueve por una restricción** (RF-015-13), con su área (m²) y su
    lugar: ``cut`` y ``fill`` son las celdas de su huella que las máscaras no dejan cortar y rellenar,
    ``edge`` las de su borde que no dejan mover (todas de la forma de la ventana ``window`` de la
    rejilla de ``masks``). Cada zona de las máscaras que impide lo que se le pide a esas celdas (un
    intocable o una exclusión, «sin corte», «solo relleno», «solo restauración», la banda de resguardo,
    «sin relleno» y la banda hacia dentro de un límite legal) da un aviso con sus celdas: si su
    código empieza por ``dec__`` (la declara una entidad, RF-015-10), ``des.entity_held`` con esa
    entidad (``declared``: código de la restricción → nombre de la entidad; sin ella, el código de la
    entidad, ``PLT-001`` de ``dec__plt_001``) y el texto la nombra como «Ver restricciones y límites»
    («Plataforma P1 (declarada)», nunca por su código interno: T45, E-8; el tipo de la entidad, «Plataforma», va en el
    texto del mensaje: la 016 añade el suyo); si no, ``des.entity_held_constraint`` con su nombre (``names``: código →
    nombre) y su código. Lo que ninguna zona explica (fuera del límite…) sale en ``des.entity_held_masks``. Una
    celda en dos zonas cuenta en las dos. Sin celdas, ninguno."""
    held = cut | fill | edge
    if not held.any():
        return ()
    grid = masks.grid
    shape = held.shape
    origin = (window[0].start, window[1].start)
    rows, cols = np.nonzero(held)
    top, bottom = int(rows.min()) + origin[0], int(rows.max()) + origin[0]  # la caja de lo que no se mueve
    left, right = int(cols.min()) + origin[1], int(cols.max()) + 1 + origin[1]
    explained = np.zeros(shape, dtype=bool)
    found: list[Notice] = []
    for code in sorted(masks.zones):
        rule = _rule(masks, code)
        if rule is None:
            continue
        runs = masks.zones[code].between_rows(top, bottom)
        if not len(runs):
            continue
        low, high = max(top, int(runs.row.min())), min(bottom, int(runs.row.max()))
        west = max(left, int(runs.col0.min()))
        east = min(right, int(runs.col1.max()))
        if east <= west:
            continue
        box = (slice(low - origin[0], high + 1 - origin[0]), slice(west - origin[1], east - origin[1]))
        asked = edge[box].copy()  # solo la caja común a la zona y a lo que no se mueve
        if rule[0]:
            asked |= cut[box]
        if rule[1]:
            asked |= fill[box]
        hit = runs.mask((high - low + 1, east - west), (low, west)) & asked
        if not hit.any():
            continue
        explained[box] |= hit
        base = code[:-len(_INNER)] if code.endswith(_INNER) else code
        area = int(np.count_nonzero(hit)) * grid.cell_area
        x, y = _place(grid, (low, west), hit)
        if base.startswith(DECLARED_PREFIX):
            other = declared.get(base, base[len(DECLARED_PREFIX):].upper().replace("_", "-"))
            found.append(Notice("des.entity_held", {
                "entity": entity, "area": area, "constraint": base, "other": other,
                "x": x, "y": y}))
            continue
        name = names.get(base, "")
        shown = f"{name} ({base})" if name and name != base else base
        found.append(Notice("des.entity_held_constraint", {
            "entity": entity, "area": area, "constraint": shown, "x": x, "y": y}))
    loose = held & ~explained
    if loose.any():
        x, y = _place(grid, origin, loose)
        found.append(Notice("des.entity_held_masks", {
            "entity": entity, "area": int(np.count_nonzero(loose)) * grid.cell_area, "x": x,
            "y": y}))
    return tuple(found)


# --- La vista previa de una entidad de diseño (spec 015, T29; RF-015-26) ------------------------

_ENTITY_PHASE = "preview_entity"
_ITEMS_LISTED = SUMMARY_ITEMS
"""Los nombres de lo que se apoya que enseña la nota del resumen; el resto, un «…» (la lista entera va en
:attr:`EntityPreview.resting`)."""


@dataclass(frozen=True, slots=True)
class EntityEnd:
    """Un extremo del eje de una entidad con la cota de su rasante: ``which`` (``"start"``: el primer vértice,
    la **abscisa 0** que decide el signo de la pendiente; ``"end"``: el último), sus coordenadas absolutas
    ``x`` e ``y`` (m, float64) y ``level_m``, la cota de la rasante ahí (m)."""

    which: str
    x: float
    y: float
    level_m: float


@dataclass(frozen=True, slots=True, eq=False)
class RestingItem:
    """Algo que se apoya en la entidad o parte de su superficie (``design.entities.Dependent``): su ``name``, su
    código si es una entidad (``entity``), el tipo de su operación (``op_type``), su estado (``state``, el valor
    de ``design.entities.EntityState``), lo que se le apoya en m³ (``volume_m3``; ``None`` si solo parte de la
    superficie) y, si es una entidad viva, los anillos de su huella (``rings``: ``(k, 2)`` absolutos, float64;
    vacío si es un diseño, que no tiene huella propia)."""

    name: str
    entity: str | None
    op_type: str
    state: str
    volume_m3: float | None
    rings: tuple[np.ndarray, ...] = ()


@dataclass(frozen=True, slots=True, eq=False)
class EntityPreview:
    """Lo que enseña la vista previa de una entidad **antes de calcularla** (RF-015-26): su ``name``, su ``code``
    (``PLT-001``; el que tendría), la ``version`` (su código) y el estado de las máscaras (``masks``), la
    superficie de partida (``start_surface``, el nombre de su dato: sobre la que se dibuja), la huella
    (``outline``: los anillos de su contorno, con sus huecos, ``(k, 2)`` absolutos float64), el eje (``axis``: sus
    vértices ``(x, y)`` absolutos, en el sentido de digitalización, con la abscisa 0 en el primero), la cota de la
    rasante en sus extremos (``ends``), la huella en celdas y m², el lado de las celdas de la rejilla (``cell_m``, m: lo
    que mide una celda en el dibujo), la longitud del eje (m) y su pendiente (%), lo
    que se le apoya (``resting``: **solo** si la entidad ya está en la versión; una nueva no tiene nada apoyado),
    si protege (``protects``) y, entonces, el resguardo (``guard_m``), el contorno de la zona con su resguardo
    (``zone``: los anillos de las celdas a ≤ resguardo de la huella, ajustado a la rejilla), las celdas y el área
    de esa zona, y el tipo de restricción que declara (``declares``).

    Con **máscaras que no están al día**, **sin resultado** (una entidad sin calcular) o con el **rechazo** de la
    preparación (``refusal``: lo que rechazaría «Calcular», RF-015-08 y RF-015-09), no hay dibujo: solo el aviso
    (``notices`` y ``refusal``). :meth:`lines` es todo lo que dice, línea a línea."""

    name: str
    code: str
    version: str
    masks: MaskState
    start_surface: str = ""
    outline: tuple[np.ndarray, ...] = ()
    axis: tuple[tuple[float, float], ...] = ()
    principal: bool = False
    ends: tuple[EntityEnd, ...] = ()
    cells: int = 0
    area_m2: float = 0.0
    cell_m: float = 0.0
    length_m: float = 0.0
    gradient_pct: float = 0.0
    resting: tuple[RestingItem, ...] = ()
    protects: bool = False
    guard_m: float | None = None
    zone: tuple[np.ndarray, ...] = ()
    zone_cells: int = 0
    zone_area_m2: float = 0.0
    declares: ConstraintType | None = None
    notices: tuple[Notice, ...] = ()
    refusal: GeoblenderError | None = None

    @property
    def drawable(self) -> bool:
        """Si hay algo que dibujar (la huella): sin máscaras al día, sin resultado o rechazada, no."""
        return bool(self.outline)

    def lines(self, language: str = "es") -> tuple[tuple[str, bool], ...]:
        """Todo lo que dice la vista previa en ``language``, línea a línea con si va en alerta: el rechazo de
        «Calcular», con los mismos mensajes (en alerta), y los avisos y notas en su orden."""
        found: list[tuple[str, bool]] = []
        if self.refusal is not None:
            text = (self.refusal.text_in(language) if isinstance(self.refusal, DesignError)
                    else self.refusal.message)
            found.append((text, True))
        found.extend((notice.text(language), notice.severity == "warning") for notice in self.notices)
        return tuple(found)


def _rings(zone: Any) -> tuple[np.ndarray, ...]:
    """Los anillos de una ``design.entities.DeclaredZone`` (el exterior y sus huecos, de cada parte)."""
    return tuple(ring for part in zone.parts for ring in part)


def _listed_names(items: Iterable[RestingItem]) -> tuple[str, ...]:
    """Los nombres de ``items`` entre «», los :data:`_ITEMS_LISTED` primeros y, si hay más, un «…»."""
    names = [f"«{item.name}»" for item in items]
    return tuple(names[:_ITEMS_LISTED]) + (("…",) if len(names) > _ITEMS_LISTED else ())


def _guard_units(footprint: Any, grid: Grid, guard_m: float
                 ) -> Generator[None, None, tuple[tuple[np.ndarray, ...], int]]:
    """El contorno de la zona de la huella con su resguardo ``guard_m`` (m) y sus celdas: las de la ventana de
    ``footprint`` (``design.platform.Footprint``) y las que quedan a ≤ resguardo de ella con la distancia
    euclídea entre centros de celda (``design.envelopes.reach_steps``): lo que la compilación de la 012
    admitirá, a una celda como mucho. Con resguardo 0, la propia huella."""
    from . import entities, platform  # al usarlo: platform importa Notice de aquí
    from .envelopes import reach_steps
    from .model import Metric

    cells = np.asarray(footprint.cells, dtype=bool)
    top, left = footprint.window[0].start, footprint.window[1].start
    if guard_m <= 0.0:
        zone = entities.declared_zone(cells, grid, 0.0, offset=(top, left))
        yield
        return _rings(zone), zone.cells
    rows, cols = np.flatnonzero(cells.any(axis=1)), np.flatnonzero(cells.any(axis=0))
    box = (slice(top + int(rows[0]), top + int(rows[-1]) + 1),
           slice(left + int(cols[0]), left + int(cols[-1]) + 1))
    window = platform.work_window(box[0], box[1], guard_m, grid, Metric.EXACT)
    around = platform._window_grid(grid, window)  # noqa: SLF001 - la ventana de la rejilla del proyecto
    seed = np.full(around.shape, np.nan, dtype=np.float64)
    inside_box = cells[int(rows[0]):int(rows[-1]) + 1, int(cols[0]):int(cols[-1]) + 1]
    first, second = box[0].start - window[0].start, box[1].start - window[1].start
    block = seed[first:first + inside_box.shape[0], second:second + inside_box.shape[1]]
    block[inside_box] = 0.0
    distance = yield from platform._drain(  # noqa: SLF001 - las unidades de un cálculo por pasos
        reach_steps(seed, around, guard_m, Metric.EXACT, name="resguardo"))
    inside = np.isfinite(distance)
    zone = entities.declared_zone(inside, grid, 0.0, offset=(window[0].start, window[1].start))
    yield
    return _rings(zone), zone.cells


def _resting_units(project: StoreProject, version_uid: str, code: str, grid: Grid
                   ) -> Generator[None, None, tuple[RestingItem, ...]]:
    """Lo que se apoya en la entidad ``code`` o parte de su superficie (``design.entities.dependents``, una sola
    lista) con, de las entidades vivas, su huella (``design.entity_store.read_entity_footprint``). Solo lee."""
    from . import entities, entity_store  # al usarlo: entity_store importa Notice de aquí

    rows = entities.dependents(project, version_uid, code)
    yield
    if not rows:
        return ()
    listed = entities.registry(project, version_uid)
    yield
    found: list[RestingItem] = []
    with project.read() as conn:
        surfaces = entity_store.entity_surfaces(conn, listed)
        for row in rows:
            rings: tuple[np.ndarray, ...] = ()
            where = surfaces.get(row.entity) if row.entity is not None else None
            if where is not None:
                shape = entity_store.read_entity_footprint(conn, where.locator)
                rings = _rings(entities.declared_zone_of_runs(shape.runs, grid, 0.0))
            found.append(RestingItem(row.name, row.entity, row.op_type, str(row.state.value),
                                     row.volume_m3, rings))
            yield
    return tuple(found)


def _entity_request(project: StoreProject, version: Any, code: str) -> Any:
    """La petición de la entidad ``code`` que ya está en la versión ``version``: su operación vigente (los campos de
    su capa) con los **parámetros vigentes** de la entidad (``entity_store.platform_parameters``, RF-015-01), como
    la que recalcularía «Recalcular lo obsoleto»; ``None`` si no tiene operación (sin calcular)."""
    import json

    from . import entities, entity_store, provenance  # al usarlo: importan Notice de aquí

    entry = entities.registry(project, version.uid).get(code)
    if entry is None:
        raise ValueError(f"la entidad «{code}» no es de la versión {version.code}")
    if entry.operation_uid is None:
        return None
    with project.read() as conn:
        row = conn.execute("SELECT settings FROM gb_operation WHERE uid = ?",
                           (entry.operation_uid,)).fetchone()
    settings = json.loads(str(row[0])) if row is not None and row[0] else {}
    return provenance.platform_request(
        settings, entity_store.platform_parameters(project, version, entry.record.code))


def _entity_units(project: StoreProject, request: Any, code: str | None, version_uid: str,
                  insert_before: str | None = None) -> Generator[None, None, EntityPreview]:
    """Las unidades de :func:`entity_preview_steps` (``insert_before``: la entidad que pasaría a partir de la nueva, si se
    previsualiza una inserción: RF-015-05)."""
    from . import entities, entity_store  # al usarlo: importan Notice de aquí
    from .entities import EntityKind

    state, _pending = access.mask_state(project, version_uid)
    with project.read() as conn:
        version = versions_read.version(conn, version_uid)
    assert version is not None  # mask_state ya lo comprobó
    yield
    existing = None
    name = getattr(request, "name", "") or ""
    if code is not None:
        existing = entities.registry(project, version.uid).get(code)
        if existing is None:
            raise ValueError(f"la entidad «{code}» no es de la versión {version.code}")
        name = existing.record.name
    named = "" if existing is None else existing.record.code
    if state is not MaskState.CURRENT:
        found = ("des.preview_entity_masks_missing" if state is MaskState.MISSING
                 else "des.preview_entity_masks_stale")
        return EntityPreview(name, named, version.code, state, notices=(
            Notice(found, {"version": version.code, "entity": name}),))
    if existing is not None:
        request = _entity_request(project, version, existing.record.code)
        if request is None:
            return EntityPreview(name, named, version.code, state, notices=(
                Notice("des.preview_entity_uncalculated", {"entity": name, "code": named}),))
    yield
    masks: MaskSet = yield from access.load_masks_steps(project, version.uid)
    try:
        prepared = yield from entity_store.prepare_platform_units(
            project, request, version, masks, code=None if existing is None else named,
            supersedes=None if existing is None else existing.operation_uid,  # como lo recalcularía la orden
            insert_before=insert_before)
    except (DesignError, GeoblenderError) as refused:  # lo que rechazaría «Calcular»: es el aviso
        return EntityPreview(name, named, version.code, state, refusal=refused)
    grid = prepared.job.grid
    foot = prepared.footprint
    shape = entities.declared_zone(foot.cells, grid, 0.0,
                                   offset=(foot.window[0].start, foot.window[1].start))
    yield
    axis = foot.axis
    start, end = axis.vertices[0], axis.vertices[-1]
    ends = (EntityEnd("start", start[0], start[1], float(foot.start_level_m)),
            EntityEnd("end", end[0], end[1], float(foot.end_level_m)))
    protects = bool(prepared.values.get("protect"))
    guard = prepared.values.get("guard_m") if protects else None
    zone: tuple[np.ndarray, ...] = ()
    zone_cells = 0
    declares: ConstraintType | None = None
    notices = [Notice("des.preview_entity", {
        "entity": name, "code": prepared.code, "version": version.code, "cells": foot.cell_count,
        "area": float(foot.area_m2), "length": float(axis.length_m),
        "start_level": float(foot.start_level_m), "end_level": float(foot.end_level_m),
        "gradient": float(foot.gradient_pct)}), *foot.notices]
    if protects and guard is not None:
        zone, zone_cells = yield from _guard_units(foot, grid, float(guard))
        declares = ConstraintType.NO_FILL  # lo que declara una plataforma que protege (D-4)
        notices.append(Notice("des.preview_entity_declares", {
            "guard": float(guard), "area": zone_cells * float(grid.cell_area)}))
    else:
        notices.append(Notice("des.preview_entity_declares_none"))
    resting: tuple[RestingItem, ...] = ()
    if existing is not None:
        resting = yield from _resting_units(project, version.uid, named, grid)
        if resting:
            notices.append(Notice("des.preview_entity_supported", {
                "count": len(resting), "items": _listed_names(resting)}))
        else:
            notices.append(Notice("des.preview_entity_supported_none"))
    return EntityPreview(
        name, prepared.code, version.code, state, prepared.start_surface, _rings(shape),
        tuple(axis.vertices), bool(axis.principal), ends, foot.cell_count, float(foot.area_m2),
        float(max(grid.dx, grid.dy)), float(axis.length_m), float(foot.gradient_pct), resting, protects,
        None if guard is None else float(guard), zone, zone_cells,
        zone_cells * float(grid.cell_area), declares, tuple(notices))


def entity_preview_steps(project: StoreProject, request: Any, version_uid: str, *,
                         code: str | None = None, insert_before: str | None = None,
                         budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """El :class:`EntityPreview` de una plataforma **antes de calcularla** (RF-015-26) para la versión
    ``version_uid`` (uid o código), por pasos de ``budget_s`` como mucho: el último ``Progress`` lleva el
    resumen. Dos maneras de pedirla: ``request`` (``design.model.PlatformRequest``, la que se prepara en el
    diálogo de «Plataforma…»; una entidad nueva, con el código que tendría) o ``code`` (el código o el nombre de
    una entidad que ya está en la versión, con sus parámetros vigentes: lo que recalcularía; ``request`` es
    entonces ``None``). Es la **preparación entera** de la orden (``entity_store.prepare_platform_units``), sin
    calcular la plataforma ni escribir nada: ni los parámetros, ni la operación, ni los datos, ni **las
    máscaras**, que no compila (si faltan o están obsoletas, lo dice en lugar de dibujar). Un rechazo de la
    preparación (RF-015-08, RF-015-09: la geometría, los campos, los parámetros, la partida, la falta de dato…)
    no es un error: es ``EntityPreview.refusal``, con el mismo mensaje que «Calcular». Otros errores (una
    versión que no existe, una entidad que no es de la versión: ``ValueError``) sí se lanzan al avanzar. ``insert_before``
    (T31; RF-015-05): la entidad que pasaría a partir de la nueva si ``request`` se inserta antes de ella (la misma
    preparación que «Calcular»: la partida ocupada por ella no se rechaza); solo con ``request``."""
    if (request is None) == (code is None):
        raise ValueError("la vista previa de una entidad es de una petición (la que se prepara) o de una "
                         "entidad de la versión (su código), no de las dos ni de ninguna")
    if insert_before is not None and request is None:
        raise ValueError("«insert_before» solo vale con la plataforma que se prepara (su petición), no con una entidad "
                         "que ya está en la versión")
    return pace_progress(_entity_units(project, request, code, version_uid, insert_before), budget_s,
                         phase=_ENTITY_PHASE, running="Preparando la vista previa de la entidad…",
                         finished="Vista previa de la entidad lista", total=10)

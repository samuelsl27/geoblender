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
impide mover unas celdas: la que declara otra entidad (código ``DEC-…``), con esa entidad, o una
restricción normal, con su nombre. Sin proyecto: las funciones de este módulo reciben lo que ya se
leyó (``design.entity_store`` lo lee).

Lo que dice son avisos y notas con código (:class:`Notice`, de ``design.messages``): el texto en
cada idioma sale de :meth:`Notice.text` y de :meth:`PreviewSummary.lines`, con la coma decimal y el
espacio fino de miles del español o el punto y la coma del inglés.
"""

from __future__ import annotations

from collections.abc import Generator, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from typing import TYPE_CHECKING

import numpy as np

from ..core.constraints.model import ConstraintType
from ..core.i18n import THIN_SPACE
from ..core.project.model import Progress
from ..core.provenance.figures import FigureSpec
from ..core.versions import read as versions_read
from ..gis.masks import access
from ..gis.masks.access import MaskSet, MaskState
from ..gis.masks.compile import STEP_BUDGET_S
from ..gis.store import StoreProject, load_features
from ..gis.vector import FeatureLayer
from .messages import lookup, render
from .model import DECLARED_PREFIX, QuarryRequest, SeedKind, Zone, ZoneKind
from .seeds import DomainSet, SeedPlan, SeedSet, pace_progress, seed_units
from .surfaces import project_frame, read_surface
from .zones import constraint_cells, layer_cells

if TYPE_CHECKING:  # design.quarry importa design.report, que importa Notice de aquí
    from ..gis.grid import Grid
    from .quarry import ConserveZone, CorridorMap, FloorMap

__all__ = [
    "Notice",
    "Obsolete",
    "ObsoleteKind",
    "PlatformSummary",
    "PreviewSummary",
    "QuarryPreview",
    "SectorStatus",
    "held_notices",
    "obsolete_notices",
    "quarry_summarize_steps",
    "seed_notices",
    "summarize_steps",
]

_HECTARE_M2 = 10_000.0
_DECIMALS = {"hectares": 1, "coverage": 1, "low": 1, "high": 1, "thickness": 3, "face": 2,
             "berm": 2, "step": 2, "drop": 3, "above": 3, "amount": 3}
"""Los decimales de los números que no son enteros (el área, entera o con uno). ``amount``: la
contrapendiente de una plataforma (spec 015, T09), que ronda la tolerancia de 0,1 m: con un decimal
«0,12 m» se leería «0,1 m», que no pasa de ella."""


def _number(value: float, decimals: int, language: str) -> str:
    """Un número en el formato de ``language`` (sin depender del idioma activo): en español, coma
    decimal y espacio fino de miles; en inglés, punto y comas."""
    text = f"{float(value):,.{decimals}f}"
    if language == "en":
        return text
    return text.translate(str.maketrans({",": THIN_SPACE, ".": ","}))


def _shown(values: Mapping[str, object], language: str) -> dict[str, str]:
    """Los valores de un aviso ya escritos para una persona."""
    found: dict[str, str] = {}
    for name, value in values.items():
        if isinstance(value, bool):
            found[name] = str(value)
        elif isinstance(value, int):
            found[name] = _number(value, 0, language)
        elif isinstance(value, float):
            decimals = (0 if value.is_integer() else 1) if name == "area" else _DECIMALS.get(
                name, 1)
            found[name] = _number(value, decimals, language)
        elif isinstance(value, tuple | list):
            found[name] = ", ".join(str(item) for item in value)
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
                      **_shown(self.values, language))


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
    en una entidad sin calcular) y su ``uid`` (de la operación; ``""`` si no la tiene)."""

    kind: ObsoleteKind
    name: str
    op_type: str = ""
    uid: str = ""

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


def _listed(items: Iterable[Obsolete]) -> tuple[str, ...]:
    """Los nombres de ``items`` entre «», los :data:`SUMMARY_ITEMS` primeros y, si hay más, un «…»."""
    names = [f"«{item.name}»" for item in items]
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
                                       "items": _listed(by_kind[kind])}))
    return tuple(found)


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
    código empieza por ``DEC-`` (la declara una entidad, RF-015-10), ``des.entity_held`` con esa
    entidad (``declared``: código de la restricción → nombre de la entidad; sin ella, el código de la
    entidad); si no, ``des.entity_held_constraint`` con su nombre (``names``: código → nombre) y su
    código. Lo que ninguna zona explica (fuera del límite…) sale en ``des.entity_held_masks``. Una
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
            other = declared.get(base, base[len(DECLARED_PREFIX):])
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

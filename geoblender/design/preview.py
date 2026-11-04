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

Lo que dice son avisos y notas con código (:class:`Notice`, de ``design.messages``): el texto en
cada idioma sale de :meth:`Notice.text` y de :meth:`PreviewSummary.lines`, con la coma decimal y el
espacio fino de miles del español o el punto y la coma del inglés.
"""

from __future__ import annotations

from collections.abc import Generator, Iterator, Mapping
from dataclasses import dataclass, field

from ..core.i18n import THIN_SPACE
from ..core.project.model import Progress
from ..core.versions import read as versions_read
from ..gis.masks import access
from ..gis.masks.access import MaskSet, MaskState
from ..gis.masks.compile import STEP_BUDGET_S
from ..gis.store import StoreProject
from .messages import lookup, render
from .model import SeedKind
from .seeds import DomainSet, SeedPlan, SeedSet, pace_progress, seed_units

__all__ = [
    "Notice",
    "PreviewSummary",
    "SectorStatus",
    "seed_notices",
    "summarize_steps",
]

_HECTARE_M2 = 10_000.0
_DECIMALS = {"hectares": 1, "coverage": 1, "low": 1, "high": 1, "thickness": 3, "face": 2,
             "berm": 2, "step": 2, "drop": 3}
"""Los decimales de los números que no son enteros (el área, entera o con uno)."""


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
        """El texto del aviso en ``language`` (``"es"`` o ``"en"``)."""
        return render(self.code, language=language, **_shown(self.values, language))


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

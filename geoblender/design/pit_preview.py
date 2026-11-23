# SPDX-License-Identifier: GPL-3.0-or-later
"""Los datos de la vista previa de una corta (spec 018, T29; HU-018-1, HU-018-4; RF-018-32, RF-015-26, RNF-018-08; plan 018 §5.5; el patrón de la vista previa de la pista, 017).

``design.preview.pit_preview_steps`` prepara, por pasos y **solo leyendo**, el :class:`~.preview.PitPreview` que dibuja ``bl.draw.pit``:

- **Antes de calcular**: la preparación entera de «Calcular» (:func:`~.pit_store.prepare_pit_units`; un rechazo suyo es ``PitPreview.refusal``) y de ella los polígonos de fondo o de límite, los sectores,
  **una flecha por rango de la roseta** (:func:`rose_arrows`), el punto de inicio de las rampas, las zonas sin rampa y los bancos fijados (:func:`job_parts`). Las máscaras de la versión han de estar al
  día (no se compilan al previsualizar: escribiría).
- **Tras calcular** (``PitAsk.outcome``) o de **una corta de la versión** (``PitAsk.code``: sus datos vigentes ``des_pbl_``, ``des_psk_``, ``des_prl_`` y ``des_pfn_``): las polilíneas, la línea de cielo,
  el eje de cada rampa y los hallazgos con su lugar (:func:`outcome_parts`).

Las funciones puras (:func:`rose_arrows`, :func:`job_parts`, :func:`outcome_parts`) no usan proyecto. Este módulo es **perezoso** (``design.preview`` lo importa al usarlo). Python puro (nivel 8).
"""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Generator
from typing import Any

import numpy as np

from ..core.errors import GeoblenderError
from ..core.versions import read as versions_read
from ..core.versions.model import Version
from ..gis.masks import access
from ..gis.store import StoreProject
from . import entities, entity_store, pit_layer, pit_store
from .entities import EntityKind
from .params import PitParam
from .pit_model import Finding, PitJob, PitOutcome
from .preview import Notice, PitArrow, PitAsk, PitLine, PitPreview, PitRampLine, PitShape, PitStart
from .surfaces import project_frame

__all__ = ["ARROW_FRACTION", "job_parts", "outcome_parts", "preview_pit_units", "rose_arrows"]

ARROW_FRACTION = 0.30
"""El largo de una flecha de la roseta: esta fracción del lado menor de la caja del polígono en que sale (de dibujo, no un dato minero)."""


def _area_and_centroid(ring: np.ndarray) -> tuple[float, float, float]:
    points = np.asarray(ring, dtype=np.float64)
    x, y = points[:, 0], points[:, 1]
    x2, y2 = np.roll(x, -1), np.roll(y, -1)
    cross = x * y2 - x2 * y
    area = 0.5 * float(cross.sum())
    if abs(area) < 1e-9:
        return 0.0, float(x.mean()), float(y.mean())
    return abs(area), float(((x + x2) * cross).sum() / (6.0 * area)), float(((y + y2) * cross).sum() / (6.0 * area))


def _anchor(rings: list[np.ndarray]) -> tuple[float, float, float]:
    """El centroide del anillo más grande de ``rings`` y el lado menor de su caja (m)."""
    big = max(rings, key=lambda ring: _area_and_centroid(ring)[0])
    _area, cx, cy = _area_and_centroid(big)
    side = float(min(np.ptp(big[:, 0]), np.ptp(big[:, 1])))
    return cx, cy, side


def _arrows(ranges: Any, rings: list[np.ndarray], sector: str) -> list[PitArrow]:
    if not rings or not ranges:
        return []
    cx, cy, side = _anchor(rings)
    length = max(ARROW_FRACTION * side, 1.0)
    return [PitArrow(cx, cy, (item.from_deg + item.to_deg) / 2.0, length, item.from_deg, item.to_deg, item.face_deg, item.berm_m, sector) for item in ranges]


def rose_arrows(job: PitJob) -> tuple[PitArrow, ...]:
    """Una flecha por rango de la roseta de la corta (anclada en el centro de su polígono mayor) y por rango de la roseta propia de cada sector (anclada en su parte mayor). El azimut es el del medio del
    rango, hacia donde baja la cara. Sin roseta, ninguna: la cara es la del perfil y no tiene dirección."""
    found = _arrows(job.rose, [np.asarray(source.ring, dtype=np.float64) for source in job.sources], "")
    for sector in job.sectors:
        if sector.rose is not None:
            rings = [np.asarray(ring, dtype=np.float64) for part in sector.parts for ring in part]
            found.extend(_arrows(sector.rose, rings, sector.name))
    return tuple(found)


def job_parts(job: PitJob) -> dict[str, Any]:
    """Lo que dibuja la vista previa antes de calcular, de lo leído por la preparación: ``sources``, ``sectors``, ``arrows``, ``starts``, ``noramp`` y ``fixed``."""
    sources = tuple(PitShape(item.name, (np.asarray(item.ring, dtype=np.float64),), item.level_m) for item in job.sources)
    sectors = tuple(PitShape(item.name, tuple(np.asarray(ring, dtype=np.float64) for part in item.parts for ring in part)) for item in job.sectors)
    noramp = tuple(np.asarray(ring, dtype=np.float64) for part in (job.noramp or ()) for ring in part)
    fixed = tuple(PitLine("fixed", item.bench, np.asarray(item.vertices, dtype=np.float64), item.closed) for item in job.fixed)
    starts = tuple(PitStart(item.ramp, float(item.point[0]), float(item.point[1]), item.name) for item in job.ramp_starts if item.point is not None)
    return {"sources": sources, "sectors": sectors, "arrows": rose_arrows(job), "starts": starts, "noramp": noramp, "fixed": fixed}


def outcome_parts(outcome: PitOutcome) -> dict[str, Any]:
    """Lo que dibuja la vista previa tras calcular, de lo que dejó «Calcular»: ``polylines``, ``skyline``, ``ramps``, ``findings``, ``bench_numbers``, ``stop`` y ``cut_m3``."""
    polylines = tuple(PitLine(str(item.kind.value), item.bench, item.vertices, item.closed) for item in outcome.polylines)
    skyline = tuple(PitLine("sky", None, line, False) for line in outcome.skyline)
    ramps = tuple(PitRampLine(item.code, item.bench, item.axis, item.length_m, item.gradient_mean_pct, item.gradient_max_pct) for item in outcome.ramps)
    figures = {figure.key: figure.value for figure in outcome.figures}
    cut = figures.get("des.pit_cut_m3")
    return {"polylines": polylines, "skyline": skyline, "ramps": ramps, "findings": tuple(outcome.findings), "bench_numbers": tuple(sorted({item.bench for item in outcome.polylines})),
            "stop": None if outcome.stop is None else str(outcome.stop.value), "cut_m3": None if cut is None else float(cut)}


def _masks_notice(state: access.MaskState, version: Version, name: str) -> Notice | None:
    if state is access.MaskState.CURRENT:
        return None
    code = "des.preview_entity_masks_missing" if state is access.MaskState.MISSING else "des.preview_entity_masks_stale"
    return Notice(code, {"version": version.code, "entity": name})


def preview_pit_units(project: StoreProject, ask: PitAsk, version_uid: str) -> Generator[None, None, PitPreview]:
    """Las unidades (cada ``yield``, una) de :func:`~.preview.pit_preview_steps`: el :class:`~.preview.PitPreview` de ``ask`` en la versión ``version_uid``. **Solo lee**.

    - **La corta que se prepara** (``ask.request``): con las máscaras al día (si no, el aviso en lugar del dibujo), la preparación de «Calcular» (o ``ask.prepared``: no se repite; su rechazo es
      ``refusal``) y, sin ``ask.outcome``, lo de antes de calcular; con él, lo de tras calcular.
    - **Una corta de la versión** (``ask.code``): sus datos vigentes. ``ValueError`` si no es una corta de la versión."""
    state, _pending = access.mask_state(project, version_uid)
    with project.read() as conn:
        version = versions_read.version(conn, version_uid)
    assert version is not None  # mask_state ya lo comprobó
    yield
    if ask.code is not None:
        return (yield from _stored(project, version, ask, state))
    asked = ask.request
    prepared = ask.prepared
    if prepared is None:
        issue = _masks_notice(state, version, asked.name)
        if issue is not None:
            return PitPreview(asked.name, "", version.code, state, by=ask.by, notices=(issue,))
        masks = yield from access.load_masks_steps(project, version.uid)
        try:
            prepared = yield from pit_store.prepare_pit_units(project, asked, version, masks)
        except GeoblenderError as refused:  # lo que rechazaría «Calcular»: es el aviso
            return PitPreview(asked.name, "", version.code, state, by=ask.by, refusal=refused)
        yield
    return _prepared(prepared, ask, state)


def _prepared(prepared: pit_store.PreparedPit, ask: PitAsk, state: access.MaskState) -> PitPreview:
    job = prepared.job
    head: dict[str, Any] = {"entity": job.request.name, "code": prepared.code, "version": prepared.version.code}
    fields: dict[str, Any] = {"mode": job.mode.value, "start_surface": prepared.start_surface, "profile": "" if job.profile is None else job.profile.name,
                              "cell_m": float(max(job.grid.dx, job.grid.dy)), "by": ask.by}
    notices: list[Notice] = []
    if ask.outcome is not None:
        found = outcome_parts(ask.outcome)
        notices.append(Notice("des.preview_pit_calculated", {**head, "benches": len(found["bench_numbers"]), "cut": found["cut_m3"] or 0.0, "ramps": len(found["ramps"]),
                                                              "findings": len(found["findings"]), "by": ask.by}))
        notices.extend(prepared.notices)
        notices.extend(ask.outcome.notices)
        return PitPreview(head["entity"], prepared.code, prepared.version.code, state, calculated=True, notices=tuple(notices), **fields, **found)
    parts = job_parts(job)
    notices.append(Notice("des.preview_pit_before", {**head, "surface": prepared.start_surface, "sources": len(parts["sources"]), "arrows": len(parts["arrows"]),
                                                      "starts": len(parts["starts"]), "noramp": len(parts["noramp"]), "fixed": len(parts["fixed"])}))
    notices.extend(prepared.notices)
    return PitPreview(head["entity"], prepared.code, prepared.version.code, state, notices=tuple(notices), **fields, **parts)


def _stored_findings(project: StoreProject, code: str, version: Version) -> tuple[Finding, ...]:
    from . import export  # al usarlo: es un módulo pesado

    found = export.stored_pit_findings(project, code, version=version.uid)
    with project.read() as conn:
        rows = conn.execute(export._PIT_FINDING_SQL.format(table=found.record.locator)).fetchall()
    return tuple(Finding(str(kind), value, limit, (float(x), float(y)), None if bench is None else int(bench), None if unit is None else str(unit), "" if detail is None else str(detail))
                 for kind, bench, value, limit, unit, x, y, detail in rows)


def _stored(project: StoreProject, version: Version, ask: PitAsk, state: access.MaskState) -> Generator[None, None, PitPreview]:
    """La vista previa de la corta ``ask.code`` de la versión: sus datos vigentes (polilíneas, línea de cielo, ejes de las rampas y hallazgos)."""
    code = str(ask.code)
    registry = entities.registry(project, version.uid)
    entry = registry.get(code)
    if entry is None or entry.record.kind != EntityKind.PIT:
        raise ValueError(f"«{code}» no es una corta de la versión {version.code}")
    name = entry.record.name
    if entry.operation_uid is None:
        return PitPreview(name, code, version.code, state, by=ask.by, notices=(Notice("des.preview_entity_uncalculated", {"entity": name, "code": code}),))
    values = pit_store.pit_parameters(project, version, code)  # el modo y la partida que tiene hoy la corta en la versión
    mode, start = str(values.get(PitParam.MODE.value) or ""), str(values.get(PitParam.START.value) or "")
    try:  # la superficie de partida como la resuelve «Calcular»; si no se resuelve (ya tiene resultado), se dibuja sobre lo que dice su parámetro
        surface = pit_store._start_dataset(registry, version, name, code, start, PitParam.START)
    except GeoblenderError:
        surface = start
    yield
    with entity_store._consistent(project) as conn:
        heads = [head for head in pit_layer.pit_heads(project, conn, version) if head.code == code]
        source = pit_layer._source(conn, heads[0], version) if heads else None
    if source is None:
        return PitPreview(name, code, version.code, state, by=ask.by, notices=(Notice("des.preview_entity_uncalculated", {"entity": name, "code": code}),))
    yield
    try:
        findings = _stored_findings(project, code, version)
    except (GeoblenderError, sqlite3.Error):
        findings = ()
    polylines = tuple(PitLine(str(line.values[1]), int(line.values[0]), line.points, bool(line.closed)) for line in source.polylines)
    skyline = tuple(PitLine("sky", None, line.points, False) for line in source.skyline)
    ramps = []
    for ramp, bench, points in source.ramps:
        run = np.hypot(*np.diff(points[:, :2], axis=0).T)
        rise = np.abs(np.diff(points[:, 2]))
        length = float(run.sum())
        moving = run > 0.0
        ramps.append(PitRampLine(ramp, bench, points, length, 0.0 if length <= 0.0 else abs(float(points[-1, 2] - points[0, 2])) / length * 100.0,
                                 float((rise[moving] / run[moving]).max() * 100.0) if bool(moving.any()) else 0.0))
    benches = tuple(sorted({line.bench for line in polylines if line.bench is not None}))
    note = Notice("des.preview_pit_stored", {"entity": name, "code": code, "version": version.code, "benches": len(benches), "ramps": len(ramps), "findings": len(findings)})
    grid = project_frame(project).grid
    return PitPreview(name, code, version.code, state, mode=mode, start_surface=surface, cell_m=float(max(grid.dx, grid.dy)), by=ask.by, calculated=True, polylines=polylines,
                      skyline=skyline, ramps=tuple(ramps), findings=findings, bench_numbers=benches, notices=(note,))


_ = math  # noqa: F841 - reservado: el módulo es de números

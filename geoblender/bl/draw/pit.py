# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que dibuja la vista previa de una corta por bancos en la Vista 3D (spec 018, T29; HU-018-1, HU-018-4; RF-018-32, RF-015-26; RNF-018-08; plan 018 §5.5; comprobación manual M3).

Es la parte de ``bl.draw.entity`` que arma los lotes de una corta (``EntityPlan(pit=design.preview.PitAsk)``); el dibujo, los manejadores, el temporizador y el quitarla al cancelar o al conmutar son los
de ``entity`` (RF-015-26). Aquí **no se calcula nada de minería**: lo dice ``design.preview.pit_preview_steps`` (que solo lee) y este módulo lo dibuja, sin ``gpu`` (los lotes se prueban sin ella).

- **Antes de calcular**, sin escribir nada: los polígonos de fondo o de límite (:data:`SOURCE`), los sectores (:data:`SECTOR`), las zonas sin rampa (:data:`NORAMP`), los bancos fijados a su cota
  (:data:`FIXED`), **una flecha por rango de la roseta** hacia donde baja la cara (:data:`ARROW`, con su rango, α y B) y el punto de inicio de las rampas (:data:`START`).
- **Tras calcular** (o de una corta de la versión): las polilíneas **a su cota**, coloreadas **por banco** (:func:`bench_key`; la paleta :data:`BENCH_COLORS` da la vuelta) o **por tipo**
  (:data:`FOOT`, :data:`CREST`), la línea de cielo (:data:`SKY`), el eje de cada rampa con la flecha de su sentido (:data:`RAMP`, :data:`RAMP_ARROW`) y cada hallazgo en su lugar (:data:`FINDING`).

Los colores y los trazos son de dibujo, no un dato minero. Con 60 bancos de 2 polilíneas de 2.000 vértices se arma en ≤ 1 s y cada redibujo es el de ``entity`` (RNF-018-08).
"""

from __future__ import annotations

from collections.abc import Generator, Sequence
from typing import Any

import numpy as np

from ...core.georef import world_to_local
from ...core.i18n import format_number, tr
from ...design import preview as design_preview
from . import constraints, design as design_draw, entity
from .constraints import Batch, Label
from .dh_overlay import LegendRow

__all__ = [
    "ARROW", "ARROW_COLOR", "BENCH_COLORS", "CREST", "FINDING", "FIXED", "FOOT", "NORAMP", "RAMP", "RAMP_ARROW", "SECTOR", "SKY", "SOURCE", "START", "bench_key", "build_pit",
    "line_segments",
]

SOURCE = "pit_source"
SECTOR = "pit_sector"
NORAMP = "pit_noramp"
FIXED = "pit_fixed"
ARROW = "pit_arrow"
START = "pit_start"
FOOT = "pit_foot"
CREST = "pit_crest"
SKY = "pit_sky"
RAMP = "pit_ramp"
RAMP_ARROW = "pit_ramp_arrow"
FINDING = "pit_finding"
"""Las claves (con el papel ``constraints.OUTLINE``) de los lotes de la vista previa de una corta."""

BENCH_COLORS: tuple[constraints.Color, ...] = (
    (0.35, 0.75, 1.00, 1.0), (1.00, 0.60, 0.20, 1.0), (0.55, 0.90, 0.35, 1.0), (0.90, 0.45, 0.95, 1.0), (1.00, 0.90, 0.25, 1.0), (0.30, 0.90, 0.80, 1.0))
"""La paleta de los bancos: el banco ``n`` lleva el color ``n`` módulo su largo (de dibujo)."""

SOURCE_COLOR: constraints.Color = (0.10, 0.80, 0.70, 1.0)
SECTOR_COLOR: constraints.Color = (0.60, 0.60, 0.95, 1.0)
NORAMP_COLOR: constraints.Color = (0.95, 0.30, 0.30, 1.0)
FIXED_COLOR: constraints.Color = (1.00, 0.85, 0.15, 1.0)
ARROW_COLOR: constraints.Color = (1.0, 1.0, 1.0, 1.0)
START_COLOR: constraints.Color = (0.20, 0.95, 0.45, 1.0)
FOOT_COLOR: constraints.Color = (0.35, 0.75, 1.00, 1.0)
CREST_COLOR: constraints.Color = (1.00, 0.60, 0.20, 1.0)
SKY_COLOR: constraints.Color = (0.85, 0.45, 0.95, 1.0)
RAMP_COLOR: constraints.Color = (0.95, 0.95, 0.30, 1.0)
FINDING_COLOR: constraints.Color = (0.95, 0.20, 0.20, 1.0)
LINE_PX = 2.0
OUTLINE_PX = 2.0
ARROW_PX = 2.5
POINT_PX = 3.0
ARROW_RANK = 0
FINDING_RANK = 1
RAMP_RANK = 1
START_RANK = 2
"""El rango de los nombres (el que se salta si cae sobre otro: ``design.label_layout``): primero el inicio de las rampas, luego los hallazgos y las rampas y, al final, las flechas."""


def bench_key(bench: int) -> str:
    """La clave del lote del banco ``bench``: su color es el ``bench`` módulo el largo de :data:`BENCH_COLORS`."""
    return f"pit_bench_{int(bench) % len(BENCH_COLORS)}"


def _bench_color(key: str) -> constraints.Color:
    return BENCH_COLORS[int(key.rsplit("_", 1)[1])]


def line_segments(lines: Sequence[tuple[np.ndarray, bool]]) -> np.ndarray:
    """Los tramos ``(m, 2, 3)`` absolutos (float64) de unas líneas con su Z (``(vértices (k, 3), cerrada)``): el cierre de un anillo une el último vértice con el primero."""
    pieces = []
    for points, closed in lines:
        found = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        if len(found) < 2:
            continue
        nxt = np.roll(found, -1, axis=0) if closed else found[1:]
        pieces.append(np.stack([found if closed else found[:-1], nxt], axis=1))
    return np.concatenate(pieces) if pieces else np.empty((0, 2, 3), dtype=np.float64)


def _solid(parts: Sequence[np.ndarray], key: str, color: constraints.Color, width_px: float, origin: Any) -> Batch | None:
    """El lote ``key`` de los tramos 3D ``parts`` (``(m, 2, 3)`` absolutos) **a su propia cota** (no se ajusta al terreno), locales (float64 hasta el último paso, ADR-0005); ``None`` sin ninguno."""
    drawn = [piece for piece in parts if len(piece)]
    if not drawn:
        return None
    flat = np.concatenate(drawn).reshape(-1, 3)
    return Batch(key, constraints.OUTLINE, color, width_px, world_to_local(flat, origin).astype(np.float32))


def _g(value: float) -> str:
    """Un número al decimal, sin él si es entero, con el formato del idioma activo."""
    return format_number(value, 0 if float(value).is_integer() else 1)


def _ramp_finding_text(detail: str) -> str:
    """El nombre de un hallazgo de rampa: ``detail`` es «rampa: código del aviso» y se dice qué pasó, nunca la clave interna (T40c; H3-2)."""
    ramp, _sep, code = str(detail).partition(": ")
    if code == "des.pit_ramp_gradient":
        what = tr("gradient over the maximum")
    elif code == "des.pit_ramp_mean_gradient":
        what = tr("mean gradient over the maximum")
    elif code == "des.pit_ramp_radius_reduced":
        what = tr("curve radius reduced")
    elif code == "des.pit_ramp_radius_below_min":
        what = tr("curve radius below the minimum")
    elif code == "des.pit_ramp_prolonged":
        what = tr("stretch beyond the side of the pit line")
    else:
        what = tr("requirement not met")
    return tr("Ramp «{ramp}»: {what}", ramp=ramp, what=what)


def _finding_text(found: Any) -> str:
    """El nombre de un hallazgo junto a su lugar: lo que es, su valor y su límite, y su banco."""
    kind = str(getattr(found.kind, "value", found.kind))
    value = "–" if found.value is None else format_number(found.value, 1)
    limit = "–" if found.limit is None else format_number(found.limit, 1)
    unit = found.unit or ""
    if kind == "face_slope":
        text = tr("Real face slope out of the limit: {value} {unit} (limit {limit} {unit})", value=value, limit=limit, unit=unit)
    elif kind == "berm_width":
        text = tr("Real berm narrower than asked: {value} {unit} (limit {limit} {unit})", value=value, limit=limit, unit=unit)
    elif kind == "floor_width":
        text = tr("Floor narrower than the minimum: {value} {unit} (limit {limit} {unit})", value=value, limit=limit, unit=unit)
    elif kind == "outside_perimeter":
        text = tr("Crest outside the perimeter of action: {value} {unit}", value=value, unit=unit)
    elif kind == "on_untouchable":
        text = tr("Crest over an untouchable area: {value} {unit}", value=value, unit=unit)
    elif kind == "unexcavated":
        text = tr("Area not excavated because of a restriction: {value} {unit}", value=value, unit=unit)
    elif kind == "ramp":
        text = _ramp_finding_text(found.detail)
    else:
        text = tr("Bench without a profile")
    return text if found.bench is None else tr("{text} · bench {bench}", text=text, bench=found.bench)


def _arrow_text(item: Any) -> str:
    text = tr("Face towards {azimuth}° · α {face}° · B {berm} m ({start}° to {end}°)", azimuth=_g(item.azimuth_deg), face=_g(item.face_deg), berm=_g(item.berm_m), start=_g(item.from_deg),
              end=_g(item.to_deg))
    return tr("«{sector}»: {text}", sector=item.sector, text=text) if item.sector else text


def _legend(request: Any, found: Any, ground: Any, drawn: set[str]) -> tuple[LegendRow, ...]:
    version = request.version_code or tr("No version")
    rows = [LegendRow(tr("Preview of «{name}» ({code}) · {version}", name=found.name, code=found.code, version=version) if found.code
                      else tr("Preview of «{name}» · {version}", name=found.name, version=version))]
    hexed = entity._hex
    if SOURCE in drawn:
        rows.append(LegendRow(tr("Polygons the pit starts from (floors or limits)"), hexed(SOURCE_COLOR)))
    if SECTOR in drawn:
        rows.append(LegendRow(tr("Design sectors"), hexed(SECTOR_COLOR)))
    if ARROW in drawn:
        rows.append(LegendRow(tr("Face direction of each range of the rose: towards where it descends"), hexed(ARROW_COLOR)))
    if START in drawn:
        rows.append(LegendRow(tr("Start of the ramps"), hexed(START_COLOR)))
    if NORAMP in drawn:
        rows.append(LegendRow(tr("Zones without a ramp"), hexed(NORAMP_COLOR)))
    if FIXED in drawn:
        rows.append(LegendRow(tr("Fixed benches (lines of the user)"), hexed(FIXED_COLOR)))
    if FOOT in drawn:
        rows.append(LegendRow(tr("Foot of a bench"), hexed(FOOT_COLOR)))
    if CREST in drawn:
        rows.append(LegendRow(tr("Crest of a bench"), hexed(CREST_COLOR)))
    colored = sorted(key for key in drawn if key.startswith("pit_bench_"))
    if colored:
        rows.append(LegendRow(tr("Benches ({count}): one colour each; the colours repeat", count=len(found.bench_numbers)), hexed(_bench_color(colored[0]))))
    if SKY in drawn:
        rows.append(LegendRow(tr("Skyline"), hexed(SKY_COLOR)))
    if RAMP in drawn:
        rows.append(LegendRow(tr("Axis of each ramp: the arrow shows its sense"), hexed(RAMP_COLOR)))
    if FINDING in drawn:
        rows.append(LegendRow(tr("Findings ({count})", count=len(found.findings)), hexed(FINDING_COLOR)))
    if found.drawable:
        rows.extend(constraints.surface_rows(ground))
    return tuple(rows)


def build_pit(request: Any, budget_s: float) -> Generator[None, None, tuple[design_draw.Built, Any]]:
    """Los pasos que construyen lo que dibuja la vista previa de una corta (véase el módulo): la preparación (``design.preview.pit_preview_steps``: solo lee), la superficie de partida sobre la que se
    dibuja y los lotes —**antes de calcular**, los polígonos, los sectores, las zonas sin rampa, los bancos fijados, las flechas de la roseta y el inicio de las rampas; **tras calcular**, las polilíneas
    a su cota por banco o por tipo, la línea de cielo, el eje de cada rampa con su flecha y los hallazgos—, los nombres, la leyenda y el resumen. Lo que rechazaría «Calcular» (o las máscaras sin
    compilar) sale en el resumen, en lugar del dibujo; sin versión activa, solo lo dice. Cada paso dura como mucho ``budget_s`` s; cerrarlo a mitad no deja nada."""
    project, version_uid, shown = request.project, request.version_uid, request.language
    origin = project.origin
    found = None
    if version_uid:
        steps = design_preview.pit_preview_steps(project, request.plan.pit, version_uid, budget_s=budget_s)
        found = yield from entity._run_preview(steps)
    if found is None:
        return entity._without_version(request)
    ground = None
    batches: list[Batch] = []
    labels: list[Label] = []
    drawn: set[str] = set()
    if found.drawable:
        ground = yield from constraints.ground_steps(project, found.start_surface, version_uid, budget_s=budget_s)
        arm = max(constraints.POINT_ARM_M, entity.POINT_ARM_CELLS * found.cell_m)
        arrow_axes = [np.array([(item.x, item.y), (item.x + item.length_m * np.sin(np.radians(item.azimuth_deg)), item.y + item.length_m * np.cos(np.radians(item.azimuth_deg)))])
                      for item in found.arrows]
        arrows = [np.concatenate([entity._axis_segments(axis), entity.arrow_segments(axis, max(0.25 * item.length_m, 0.5))]) for axis, item in zip(arrow_axes, found.arrows, strict=True)]
        crosses = entity.cross_segments([(item.x, item.y) for item in found.starts], arm)
        findings = entity.cross_segments([found_item.place for found_item in found.findings], arm)
        ramp_arrows = [_with_z(entity.arrow_segments(item.axis[:, :2], max(0.1 * item.length_m, 1.0)), float(item.axis[-1, 2])) for item in found.ramps if len(item.axis) > 1]
        two_d: dict[str, tuple[constraints.Color, float, list[np.ndarray]]] = {
            SOURCE: (SOURCE_COLOR, OUTLINE_PX, [design_draw.ring_segments(item.rings) for item in found.sources]),
            SECTOR: (SECTOR_COLOR, OUTLINE_PX, [design_draw.ring_segments(item.rings) for item in found.sectors]),
            NORAMP: (NORAMP_COLOR, OUTLINE_PX, [design_draw.ring_segments(found.noramp)]),
            ARROW: (ARROW_COLOR, ARROW_PX, arrows),
            START: (START_COLOR, POINT_PX, [crosses]),
            FINDING: (FINDING_COLOR, POINT_PX, [findings])}
        solid: dict[str, tuple[constraints.Color, float, list[np.ndarray]]] = {FIXED: (FIXED_COLOR, LINE_PX, [line_segments([(item.vertices, item.closed) for item in found.fixed])])}
        by_key: dict[str, list[tuple[np.ndarray, bool]]] = {}
        for item in found.polylines:
            key = bench_key(item.bench) if found.by == "bench" else (FOOT if item.kind == "foot" else CREST)
            by_key.setdefault(key, []).append((item.vertices, item.closed))
        keys = sorted(key for key in by_key if key.startswith("pit_bench_")) if found.by == "bench" else [key for key in (FOOT, CREST) if key in by_key]
        for key in keys:
            solid[key] = (_bench_color(key) if found.by == "bench" else (FOOT_COLOR if key == FOOT else CREST_COLOR), LINE_PX, [line_segments(by_key[key])])
        solid[SKY] = (SKY_COLOR, LINE_PX, [line_segments([(item.vertices, item.closed) for item in found.skyline])])
        solid[RAMP] = (RAMP_COLOR, LINE_PX, [line_segments([(item.axis, False) for item in found.ramps])])
        solid[RAMP_ARROW] = (RAMP_COLOR, ARROW_PX, ramp_arrows)
        order = [SOURCE, SECTOR, NORAMP, FIXED, *keys, FOOT, CREST, SKY, RAMP, RAMP_ARROW, ARROW, START, FINDING]
        for key in dict.fromkeys(order):
            if key in two_d:
                color, width, parts = two_d[key]
                batch = yield from entity._drape(parts, key, color, width, ground, origin, budget_s)
            elif key in solid:
                color, width, parts = solid[key]
                batch = _solid(parts, key, color, width, origin)
                yield
            else:
                continue
            if batch is not None:
                batches.append(batch)
                drawn.add(key)
        named: list[tuple[str, tuple[float, float], constraints.Color, int]] = []
        for item in found.arrows:
            tip = (item.x + item.length_m * float(np.sin(np.radians(item.azimuth_deg))), item.y + item.length_m * float(np.cos(np.radians(item.azimuth_deg))))
            named.append((_arrow_text(item), tip, ARROW_COLOR, ARROW_RANK))
        for start in found.starts:
            text = tr("Start of «{ramp}»: {name}", ramp=start.ramp, name=start.name) if start.name else tr("Start of «{ramp}»", ramp=start.ramp)
            named.append((text, (start.x, start.y), START_COLOR, START_RANK))
        for item in design_preview.finding_labels(found.findings):
            named.append((_finding_text(item), item.place, FINDING_COLOR, FINDING_RANK))
        for ramp in found.ramps:
            middle = ramp.axis[len(ramp.axis) // 2]
            named.append((tr("Ramp «{code}»: {length} m · {gradient} % mean", code=ramp.code, length=format_number(ramp.length_m, 1), gradient=format_number(ramp.gradient_mean_pct, 1)),
                          (float(middle[0]), float(middle[1])), RAMP_COLOR, RAMP_RANK))
        if named:
            places = np.array([place for _text, place, _color, _rank in named], dtype=np.float64).reshape(-1, 2)
            spots = yield from constraints.drape_points_steps(places, ground, origin, budget_s=budget_s)
            labels.extend(Label(text, (float(x), float(y), float(z)), color, rank) for (text, _place, color, rank), (x, y, z) in zip(named, spots.tolist(), strict=True))
    lines = constraints.Built(version_uid, request.version_code, found.masks.value, "" if ground is None else ground.name, tuple(batches), tuple(labels), _legend(request, found, ground, drawn),
                              request.stamp)
    return design_draw.Built(lines, None, (), found.lines(shown)), found


def _with_z(segments: np.ndarray, z: float) -> np.ndarray:
    """Los tramos ``(k, 2, 2)`` absolutos a la cota ``z``: ``(k, 2, 3)``."""
    return np.concatenate([segments, np.full((len(segments), 2, 1), float(z))], axis=2)

# SPDX-License-Identifier: GPL-3.0-or-later
"""Compilar las restricciones (spec 012; RF-012-04, RF-012-05, RF-012-06, RF-012-11 a
RF-012-16; plan 012 §5.3.1, A2–A5, A11, D-24, D-36).

:func:`compile_steps` hace, por pasos de ``budget_s`` como mucho (RNF-012-06), lo que pide una
:class:`CompileRequest`: comprobar y preparar las zonas y los límites
(``gis.masks.combine.prepare_steps``: RF-012-04, RF-012-15), combinarlas (A3), el informe de los
límites (A4, ``gis.masks.overlay``), **lo ganado y lo perdido** de cada restricción que cambió
frente a la compilación anterior (A5, :class:`Change`), las cifras y, si se pide, la rejilla de
clases (D-25) escrita por teselas en su temporal con su hash por bandas
(:class:`ClassesGrid`). El último ``Progress`` lleva el :class:`CompileResult`, con las filas de
sus tablas (zonas, informe, partes de la franja y restricciones compiladas). Cerrar los pasos
antes borra el temporal de la rejilla (RF-012-28).

**Lo de antes** (A5, D-36; :class:`PreviousMasks`): de cada restricción que cambió desde la
compilación anterior vigente de la versión (otra geometría, otro tipo, otro resguardo,
activada o desactivada; :func:`changed_codes` con la huella de :func:`fingerprint`), su polígono y
su zona de entonces (``None``: no estaba). Viaja en los ajustes de la operación
(:meth:`PreviousMasks.settings`, JSON exacto), para que reproducirla dé lo mismo sin el proyecto
(decisión de la T10: el contenido anterior de las capas no se guarda en ninguna otra parte).
Polígono ganado ``área(A ∖ A')`` y perdido ``área(A' ∖ A)`` con ``gis.polygons.overlay``
(líneas y puntos: 0); zona ganada y perdida, celdas × área de celda.

Python puro con numpy (nivel 2).
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Generator, Iterator, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np

from ...core.constraints.model import (
    Constraint,
    ConstraintParam,
    ConstraintType,
    GeometryKind,
    SearchRecord,
    Sector,
)
from ...core.constraints.params import param_key
from ...core.content.encoder import NORMALIZER, ContentDigest, ContentHasher
from ...core.datasets.model import DATASET_DECLARATIONS
from ...core.georef import CrsRef, VerticalRef
from ...core.params.store import ResolvedParam
from ...core.project.model import Progress
from ...core.provenance.figures import FigureSpec
from ..content import DIGEST_BLOCK_CELLS, GEOTIFF, raster_header
from ..geotiff import writer
from ..grid import Grid
from ..polygons import overlay
from ..raster import Raster
from .combine import Masks, Notice, Prepared, combine, prepare_steps
from .overlay import M2_PER_HA, LimitsReport, report_of
from .zones import ROWS_PER_STEP, SEGMENTS_PER_STEP, Runs

__all__ = [
    "STEP_BUDGET_S",
    "Change",
    "ClassesGrid",
    "CompileRequest",
    "CompileResult",
    "PreviousMasks",
    "PreviousShape",
    "changed_codes",
    "compile_steps",
    "fingerprint",
    "fingerprint_kind",
    "geometry_sha256",
    "resolved_values",
]

STEP_BUDGET_S = 0.05
"""Lo que dura un paso como mucho (s; RNF-012-06)."""
_WORK_FRACTION = 0.5
"""La parte del presupuesto que se planea (la otra mitad, para lo más lento del paso)."""
_PHASE = "compile"
_TEXT = "Compilando las restricciones…"


# --- Datos -------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class PreviousShape:
    """Una restricción tal como la compiló la compilación anterior: su tipo, su geometría, sus
    partes (anillos ABSOLUTOS) y su zona (tramos de fila)."""

    ctype: ConstraintType
    kind: GeometryKind
    parts: tuple[tuple[np.ndarray, ...], ...]
    runs: Runs


@dataclass(frozen=True, slots=True, eq=False)
class PreviousMasks:
    """Lo de la compilación anterior que pide A5: su operación y, por código de cada
    restricción que cambió desde entonces, cómo era (``None``: no estaba compilada)."""

    operation_uid: str
    changed: Mapping[str, PreviousShape | None]

    def settings(self) -> dict[str, Any]:
        """Lo de antes como ajustes JSON de la operación (exacto: floats de Python)."""
        found: dict[str, Any] = {}
        for code, shape in self.changed.items():
            found[code] = None if shape is None else {
                "ctype": shape.ctype.value, "kind": shape.kind.value,
                "parts": [[ring.tolist() for ring in part] for part in shape.parts],
                "runs": np.column_stack((shape.runs.row, shape.runs.col0,
                                         shape.runs.col1)).tolist(),
            }
        return {"operation": self.operation_uid, "changed": found}

    @classmethod
    def from_settings(cls, value: object) -> PreviousMasks | None:
        """Lo contrario de :meth:`settings` (``None`` sin compilación anterior)."""
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise ValueError(f"lo de la compilación anterior es un objeto, no {value!r}")
        changed: dict[str, PreviousShape | None] = {}
        for code, item in dict(value.get("changed") or {}).items():
            if item is None:
                changed[str(code)] = None
                continue
            runs = np.asarray(item["runs"], dtype=np.int64).reshape(-1, 3)
            changed[str(code)] = PreviousShape(
                ConstraintType(item["ctype"]), GeometryKind(item["kind"]),
                tuple(tuple(np.asarray(ring, dtype=np.float64).reshape(-1, 2) for ring in part)
                      for part in item["parts"]),
                Runs(runs[:, 0], runs[:, 1], runs[:, 2]))
        return cls(str(value.get("operation") or ""), MappingProxyType(changed))


@dataclass(frozen=True, slots=True, eq=False)
class CompileRequest:
    """Lo que se compila: las restricciones, los valores de sus parámetros resueltos en la
    versión (clave → valor o ``ResolvedParam``), los sectores y las búsquedas, la rejilla del
    proyecto y lo de la compilación anterior (A5)."""

    constraints: tuple[Constraint, ...]
    resolved: Mapping[str, object]
    sectors: tuple[Sector, ...] = ()
    searches: tuple[SearchRecord, ...] = ()
    grid: Grid | None = None
    previous: PreviousMasks | None = None


@dataclass(frozen=True, slots=True)
class Change:
    """Lo ganado y lo perdido de una restricción que cambió (RF-012-06; m²)."""

    code: str
    name: str
    ctype: ConstraintType | None
    polygon_gained_m2: float
    polygon_lost_m2: float
    zone_gained_m2: float
    zone_lost_m2: float


@dataclass(frozen=True, slots=True)
class ClassesGrid:
    """La rejilla de clases escrita entera en su temporal, con su hash (``gis.geotiff@1``)."""

    path: Path
    digest: ContentDigest


@dataclass(frozen=True, slots=True, eq=False)
class CompileResult:
    """Lo compilado: la rejilla, lo preparado, las máscaras, el informe de los límites, los
    cambios (A5), la rejilla de clases escrita (o ``None``), las cifras y los avisos."""

    grid: Grid
    prepared: Prepared
    masks: Masks
    report: LimitsReport
    changes: tuple[Change, ...]
    classes: ClassesGrid | None
    figures: tuple[FigureSpec, ...]
    notices: tuple[Notice, ...]
    buffers: Mapping[str, float] = field(default_factory=dict)
    fingerprints: Mapping[str, str] = field(default_factory=dict)

    def zone_rows(self) -> list[tuple[str, int, int, int]]:
        """Las filas de ``gis_mskz_``: (zona, fila, col0, col1) de cada zona en su orden y la
        banda hacia dentro del límite legal (``<código>:inner``)."""
        found: list[tuple[str, int, int, int]] = []

        def add(name: str, runs: Runs) -> None:
            found.extend(zip([name] * len(runs), runs.row.tolist(), runs.col0.tolist(),
                             runs.col1.tolist(), strict=True))

        for code, zone in self.prepared.zones.items():
            add(code, zone.runs)
        for code in self.prepared.limits.legal_codes:
            add(f"{code}:inner", self.prepared.limits.legal.band)
        return found

    def report_rows(self) -> list[tuple[str, str, float | None, str | None, str | None]]:
        """Las filas de ``gis_mskr_`` (formato largo: restricción, cantidad, valor, unidad y
        nota)."""
        report, masks = self.report, self.masks
        rows: list[tuple[str, str, float | None, str | None, str | None]] = [
            ("", name, value, "m2", None) for name, value in (
                ("legal_area", report.legal_m2), ("perimeter_area", report.perimeter_m2),
                ("limits_intersection", report.intersection_m2),
                ("fill_strip_area", report.strip_m2),
                ("default_domain", masks.default_domain.area(self.grid)),
                ("cut_allowed", masks.cut_allowed.area(self.grid)),
                ("fill_allowed", masks.fill_allowed.area(self.grid)),
                ("no_movement", masks.no_movement_m2))]
        for code, zone in self.prepared.zones.items():
            rows.append((code, "zone_area", zone.runs.area(self.grid), "m2", zone.ctype.value))
            rows.append((code, "zone_outside_grid", zone.outside_m2, "m2", None))
            rows.append((code, "buffer", self.buffers.get(code, 0.0), "m", None))
            rows.append((code, "fingerprint", None, None, self.fingerprints.get(code)))
            if zone.weight is not None:
                rows.append((code, "weight", zone.weight, "-", None))
        for conflict in masks.conflicts:
            rows.append(("", "conflict", conflict.area_m2, "m2", ",".join(conflict.causes)))
        for change in self.changes:
            rows.extend((change.code, quantity, value, "m2", None) for quantity, value in (
                ("polygon_gained", change.polygon_gained_m2),
                ("polygon_lost", change.polygon_lost_m2),
                ("zone_gained", change.zone_gained_m2), ("zone_lost", change.zone_lost_m2)))
        for notice in self.notices:
            code = notice.value("code")
            rows.append(("" if code is None else str(code), "notice", None, None,
                         notice.text("es")))
        return rows

    def part_rows(self) -> list[tuple[float, float, float, float]]:
        """Las partes de la franja: (x, y absolutos, área m², área ha)."""
        return [(part.centroid[0], part.centroid[1], part.area_m2, part.area_m2 / M2_PER_HA)
                for part in self.report.strip_parts]


# --- Huellas y lo que cambió (A5) --------------------------------------------------------------


def _value(found: object) -> object:
    return found.value if isinstance(found, ResolvedParam) else found


def resolved_values(resolved: Mapping[str, object]) -> dict[str, object]:
    """Clave → valor de unos parámetros resueltos (``ResolvedParam`` o valores)."""
    return {key: _value(value) for key, value in resolved.items()}


def geometry_sha256(item: Constraint) -> str:
    """La huella de la geometría de una restricción (su tipo de geometría y sus coordenadas
    float64, parte a parte y anillo a anillo)."""
    digest = hashlib.sha256(item.kind.value.encode("ascii"))
    for part in item.parts:
        digest.update(b"P%d" % len(part))
        for ring in part:
            values = np.ascontiguousarray(ring, dtype="<f8")
            digest.update(b"R%d" % values.shape[0])
            digest.update(values.tobytes())
    return digest.hexdigest()


def buffer_of(item: Constraint, resolved: Mapping[str, object]) -> float:
    """El resguardo que da su zona: hacia dentro del límite legal; 0 en el perímetro; hacia
    fuera en las demás."""
    if item.ctype is ConstraintType.ACTION_PERIMETER or item.ctype is None:
        return 0.0
    param = (ConstraintParam.BUFFER_IN if item.ctype is ConstraintType.LEGAL_LIMIT
             else ConstraintParam.BUFFER_OUT)
    value = _value(resolved.get(param_key(item.code, param)))
    return 0.0 if value is None else float(value)  # type: ignore[arg-type]


def is_active(item: Constraint, resolved: Mapping[str, object]) -> bool:
    """Si la restricción está activa en la versión (su «activa» resuelta, verdadera)."""
    return _value(resolved.get(param_key(item.code, ConstraintParam.ACTIVE))) is True


def fingerprint(item: Constraint, resolved: Mapping[str, object]) -> str:
    """La huella de lo que da la zona de una restricción activa: geometría, tipo, resguardo y
    coordenadas."""
    ctype = "" if item.ctype is None else item.ctype.value
    return f"{item.kind.value}|{ctype}|{buffer_of(item, resolved)!r}|{geometry_sha256(item)}"


def fingerprint_kind(value: str) -> GeometryKind:
    """La geometría de una huella de :func:`fingerprint`."""
    return GeometryKind(value.partition("|")[0])


def changed_codes(now: Mapping[str, str], before: Mapping[str, str]) -> tuple[str, ...]:
    """Los códigos cuya huella cambió, en orden: los que están ahora y antes no, los que
    estaban y ya no (desactivados o quitados) y los que tienen otra huella."""
    return tuple(sorted(code for code in set(now) | set(before)
                        if now.get(code) != before.get(code)))


def _polygons(parts: Sequence[Sequence[np.ndarray]], kind: GeometryKind) -> list[Any]:
    return list(parts) if kind is GeometryKind.POLYGON else []


def _area(a: list[Any], b: list[Any], origin: Sequence[float]) -> float:
    if not a:
        return 0.0
    area = overlay(a, b, "difference", origin=origin).area_m2
    return area if area > 0.0 else 0.0


def _changes(request: CompileRequest, prepared: Prepared, grid: Grid
             ) -> Generator[None, None, tuple[Change, ...]]:
    previous = request.previous
    if previous is None:
        return ()
    by_code = {item.code: item for item in request.constraints}
    origin = (grid.west, grid.extent.ymin)
    found: list[Change] = []
    for code, before in previous.changed.items():
        zone = prepared.zones.get(code)
        item = by_code.get(code)
        now_parts = (_polygons(item.parts, item.kind) if zone is not None and item is not None
                     else [])
        now_runs = zone.runs if zone is not None else Runs.empty()
        old_parts = [] if before is None else _polygons(before.parts, before.kind)
        old_runs = Runs.empty() if before is None else before.runs
        name = zone.name if zone is not None else (item.shown_name() if item else code)
        ctype = zone.ctype if zone is not None else (
            item.ctype if item is not None else (None if before is None else before.ctype))
        found.append(Change(code, name, ctype, _area(now_parts, old_parts, origin),
                            _area(old_parts, now_parts, origin),
                            now_runs.difference(old_runs).area(grid),
                            old_runs.difference(now_runs).area(grid)))
        yield None
    return tuple(found)


# --- Cifras ------------------------------------------------------------------------------------


def _figures(result_grid: Grid, prepared: Prepared, masks: Masks,
             report: LimitsReport) -> tuple[FigureSpec, ...]:
    found = [FigureSpec(key, value, "m2") for key, value in (
        ("gis.legal_area_m2", report.legal_m2), ("gis.perimeter_area_m2", report.perimeter_m2),
        ("gis.limits_intersection_m2", report.intersection_m2),
        ("gis.fill_strip_area_m2", report.strip_m2),
        ("gis.default_domain_m2", masks.default_domain.area(result_grid)),
        ("gis.cut_allowed_m2", masks.cut_allowed.area(result_grid)),
        ("gis.fill_allowed_m2", masks.fill_allowed.area(result_grid)),
        ("gis.no_movement_m2", masks.no_movement_m2))]
    for code, zone in prepared.zones.items():
        found.append(FigureSpec("gis.zone_area_m2", zone.runs.area(result_grid), "m2",
                                scope={"constraint": code}))
        if zone.outside_m2 > 0.0:
            found.append(FigureSpec("gis.zone_outside_grid_m2", zone.outside_m2, "m2",
                                    scope={"constraint": code}))
    return tuple(found)


# --- Los pasos ---------------------------------------------------------------------------------


class _Pacer:
    def __init__(self, budget_s: float) -> None:
        self.target = budget_s * _WORK_FRACTION
        self.restart()

    def restart(self) -> None:
        self.start = self.last = time.perf_counter()
        self.slowest = 0.0

    def lap(self) -> bool:
        now = time.perf_counter()
        self.slowest = max(self.slowest, now - self.last)
        self.last = now
        return now - self.start + self.slowest > self.target


def _classes_steps(raster: Raster, path: Path, temporary: Path | None
                   ) -> Generator[None, None, ClassesGrid]:
    """La rejilla de clases en su temporal (una tesela por unidad) y su hash por bandas."""
    hasher = ContentHasher("raster", declarations=DATASET_DECLARATIONS, reader=GEOTIFF.id,
                           normalizer=NORMALIZER)
    feed = hasher.begin_grid(raster_header(raster))
    rows, columns = raster.grid.shape
    band = max(1, DIGEST_BLOCK_CELLS // max(1, columns))
    for start in range(0, rows, band):
        feed.update(raster.values[start:start + band])
        yield None
    feed.finish()
    steps = writer.write_steps(raster, path, profile="project", temporary=temporary,
                               replace=False)
    with closing(steps):  # cerrar o fallar a mitad borra el temporal
        while True:
            try:
                next(steps)
            except StopIteration as stop:
                written = Path(stop.value)
                break
            yield None
    return ClassesGrid(written, hasher.digest())


def _work(request: CompileRequest, segments_per_step: int, rows_per_step: int,
          classes_path: Path | None, classes_temporary: Path | None,
          references: tuple[CrsRef, VerticalRef] | None
          ) -> Generator[None, None, CompileResult]:
    grid = request.grid
    prepared = yield from prepare_steps(request.constraints, request.resolved, grid,
                                        segments_per_step=segments_per_step,
                                        rows_per_step=rows_per_step)
    assert grid is not None
    masks = combine(prepared.zones, prepared.limits, grid)
    yield None
    report = report_of(prepared, grid)
    yield None
    changes = yield from _changes(request, prepared, grid)
    notices = (*prepared.notices, *(n for n in report.notices()
                                    if n.code == "core.constraint_strip_part"))
    buffers = {item.code: buffer_of(item, request.resolved) for item in request.constraints
               if item.code in prepared.zones}
    fingerprints = {item.code: fingerprint(item, request.resolved)
                    for item in request.constraints if item.code in prepared.zones}
    classes = None
    if classes_path is not None:
        if references is None:
            raise ValueError("la rejilla de clases necesita el CRS y la referencia vertical")
        raster = Raster(grid, masks.classes.astype(np.float64), *references)
        classes = yield from _classes_steps(raster, Path(classes_path),
                                            None if classes_temporary is None
                                            else Path(classes_temporary))
    try:
        return CompileResult(grid, prepared, masks, report, changes, classes,
                             _figures(grid, prepared, masks, report), tuple(notices),
                             MappingProxyType(buffers), MappingProxyType(fingerprints))
    except BaseException:
        if classes is not None:
            classes.path.unlink(missing_ok=True)
        raise


def compile_steps(request: CompileRequest, *, budget_s: float = STEP_BUDGET_S,
                  classes_path: Path | str | None = None,
                  classes_temporary: Path | str | None = None,
                  references: tuple[CrsRef, VerticalRef] | None = None,
                  segments_per_step: int = SEGMENTS_PER_STEP,
                  rows_per_step: int = ROWS_PER_STEP) -> Iterator[Progress]:
    """Los pasos de compilar ``request`` (véase el módulo), de ``budget_s`` como mucho. Con
    ``classes_path`` (su destino, que no se toca), la rejilla de clases queda escrita en
    ``classes_temporary`` (por defecto, el de ``gis.geotiff.writer``) con el CRS y la referencia
    vertical de ``references``. El último ``Progress`` lleva el :class:`CompileResult`. Los
    rechazos para el usuario (``ConstraintError``, ``IncompleteConstraints``), al avanzar."""
    if not isinstance(request, CompileRequest):
        raise TypeError(f"se compila una CompileRequest, no {type(request).__name__}")
    if isinstance(budget_s, bool) or not isinstance(budget_s, int | float) or budget_s <= 0:
        raise ValueError(f"el presupuesto de un paso es un número positivo, no {budget_s!r}")
    work = _work(request, segments_per_step, rows_per_step,
                 None if classes_path is None else Path(classes_path),
                 None if classes_temporary is None else Path(classes_temporary), references)
    return _paced(work, float(budget_s), len(request.constraints))


def _paced(work: Generator[None, None, CompileResult], budget_s: float,
           count: int) -> Iterator[Progress]:
    pacer = _Pacer(budget_s)
    done, total = 0, max(8, 4 * count + 8)
    with closing(work):  # cerrar los pasos (Esc) cierra el trabajo
        while True:
            pacer.restart()
            try:
                next(work)
                done += 1
                while not pacer.lap():
                    next(work)
                    done += 1
            except StopIteration as stop:
                result: CompileResult = stop.value
                break
            total = max(total, done + 1)
            yield Progress(_PHASE, done, total, _TEXT)
    yield Progress(_PHASE, total, total, _summary(result), result=result)


def _summary(result: CompileResult) -> str:
    report = result.report
    return (f"Máscaras compiladas: {len(result.prepared.zones)} restricciones; límite legal "
            f"{report.legal_ha:.2f} ha, perímetro {report.perimeter_ha:.2f} ha, franja "
            f"{report.strip_ha:.2f} ha")


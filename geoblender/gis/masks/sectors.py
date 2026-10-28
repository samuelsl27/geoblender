# SPDX-License-Identifier: GPL-3.0-or-later
"""Los sectores de búsqueda y la búsqueda de intocables en el proyecto (spec 012, T13;
HU-012-3; RF-012-07, RF-012-08, RF-012-09; plan 012 A6, A12, D-3, D-26, D-27).

La geometría que ``core`` no puede hacer (nivel 0) y que pide registrar sus operaciones
(``core.constraints.provenance``):

- :func:`declare_sectors`: los sectores de una capa de polígonos del proyecto («entidades»,
  ``gis_fea_``, o «dominios», ``gis_dom_``; D-27) y el campo que nombra cada uno. La capa se
  comprueba como RF-011-08 (:func:`sector_list`): cada polígono simple, con área, con sus huecos
  bien puestos y con el nombre lleno, y ningún par solapado (más de 1 mm²); si no, se rechaza
  con la lista (:class:`SectorsError`: entidad, nombre, problema y, en un solape, su área) sin
  registrar nada. Las entidades con el mismo nombre forman un sector; su código sale del nombre
  (``s_`` delante si no empieza por una letra). Informa del área del perímetro que no cubre
  ningún sector (:func:`uncovered_m2`, m², con ``gis.polygons.overlay``). Sin capa, ningún
  sector: el perímetro de actuación es el único (D-26).
- :func:`search_steps`: busca en un sector (por su código; ``""``, el perímetro) las entidades
  de hasta diez capas «entidades» a ≤ la distancia de búsqueda (el parámetro
  ``core.constraints.search_distance_m`` del proyecto; ``gis.search``, A6), por pasos; el último
  ``Progress`` lleva lo buscado (:class:`Searched`, con la huella del sector y el hash de cada
  capa).
- :func:`close_search`: con una decisión por entidad hallada (:class:`Decision`: convertida en
  la restricción que se creó, o descartada, siempre con su motivo), registra la búsqueda
  (``core.find_untouchables``). Se niega si queda alguna sin decidir o si el sector o una capa
  cambió después de buscar.

El estado de cada sector (vigente o pendiente, A12) lo da ``gis.masks.access.sector_states``.
Las entradas del usuario solo se leen. Python puro con numpy (nivel 2).
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ...core.constraints import provenance as cprov
from ...core.constraints import store as cstore
from ...core.constraints.messages import ConstraintError, render
from ...core.constraints.model import HitDecision, SearchHit, SearchRecord, Sector
from ...core.constraints.model import constraint_code
from ...core.constraints.params import SEARCH_DISTANCE
from ...core.datasets import registry as dataset_registry
from ...core.i18n import format_number
from ...core.params import ParamError
from ...core.params.store import ParameterStore
from ...core.project.model import Progress
from .. import polygons as geometry
from .. import search as finder
from .. import store as gstore
from ..provenance import DOMAINS, FAMILIES_BY_CODE, FEATURES
from ..store import StoreProject
from ..vector import FeatureLayer
from .store import _resolved, perimeter_of, search_sectors

__all__ = [
    "SECTOR_PREFIX",
    "Decision",
    "DeclaredSectors",
    "Searched",
    "SectorProblem",
    "SectorsError",
    "close_search",
    "declare_sectors",
    "search_steps",
    "sector_list",
    "uncovered_m2",
]

SECTOR_PREFIX = "s"
"""Lo que va delante del código de un sector cuyo nombre no empieza por una letra."""
_KINDS_ES = {"point": "puntos", "line": "líneas"}


# --- Datos -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SectorProblem:
    """Un problema de la capa de sectores (RF-012-07 con la regla de RF-011-08): ``problem``
    (``name_empty``, ``self_intersecting``, ``no_area``, ``hole_outside`` u ``overlap``), la
    entidad (``fid``) y su nombre y, en un solape, la otra y el área (m²)."""

    problem: str
    fid: int
    name: str
    other_fid: int | None = None
    other_name: str | None = None
    area_m2: float | None = None

    def text(self, attribute: str, language: str = "es") -> str:
        """El problema como un elemento de la lista de ``core.constraint_sectors_invalid``."""
        area = None if self.area_m2 is None else format_number(self.area_m2, 2)
        return render(f"core.constraint_sector_{self.problem}", language=language,
                      fid=self.fid, sector=self.name, attribute=attribute,
                      other_fid=self.other_fid, other_sector=self.other_name, area=area)


class SectorsError(ConstraintError):
    """``core.constraint_sectors_invalid``: la capa de sectores no sirve; ``problems`` es la
    lista (:class:`SectorProblem`) y el valor del error, cuántos problemas hay."""

    def __init__(self, found: Sequence[SectorProblem], *, layer: str, attribute: str) -> None:
        found = tuple(found)
        super().__init__("core.constraint_sectors_invalid", field=attribute, value=len(found),
                         layer=layer,
                         problems="; ".join(problem.text(attribute) for problem in found))
        self.problems = found


@dataclass(frozen=True, slots=True)
class DeclaredSectors:
    """Lo que dejó :func:`declare_sectors`: su operación, los sectores guardados y el área del
    perímetro que no cubre ninguno (m²; ``None`` sin capa o sin perímetro)."""

    operation_uid: str
    sectors: tuple[Sector, ...]
    uncovered_m2: float | None


@dataclass(frozen=True, slots=True)
class Searched:
    """Una búsqueda hecha y aún sin cerrar: el sector (código, nombre, huella y dato del que
    sale), las capas consultadas con el hash de su contenido al buscar, la distancia (m) y lo
    hallado (``gis.search.Found``, con ``layer`` = el nombre del dato)."""

    sector_code: str
    sector_name: str
    sector_sha256: str
    sector_dataset: str
    layers: tuple[str, ...]
    layer_sha256: tuple[str, ...]
    distance_m: float
    found: tuple[finder.Found, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class Decision:
    """Lo que se decide de una entidad hallada (RF-012-08): ``converted`` en la restricción
    ``constraint_code`` o ``discarded``, con su motivo."""

    layer: str
    fid: int
    decision: HitDecision
    reason: str
    constraint_code: str | None = None


@dataclass(frozen=True, slots=True)
class _Polygon:
    fid: int
    name: str
    rings: tuple[np.ndarray, ...]


# --- La capa de sectores ---------------------------------------------------------------------


def _family(name: str) -> str | None:
    for code in (FEATURES, DOMAINS):
        if name.startswith(FAMILIES_BY_CODE[code].prefix):
            return code
    return None


def _polygons(project: StoreProject, source: str, attribute: str) -> list[_Polygon]:
    """Los polígonos de la capa ``source`` (uno por parte de cada entidad) con el valor de su
    campo ``attribute`` (la columna o su título) como texto."""
    family = _family(source)
    if family is None:
        raise ValueError(f"los sectores salen de una capa «entidades» o «dominios» del "
                         f"proyecto, no de «{source}»")
    if family == FEATURES:
        layer = gstore.load_features(project, source)
        assert isinstance(layer, FeatureLayer)
        if layer.kind != "polygon":
            raise ConstraintError("core.constraint_sectors_not_polygons", field="capa",
                                  value=_KINDS_ES.get(layer.kind, layer.kind), layer=source)
        fields = [(column.column, column.field) for column in layer.columns]
        entities = [(fid, {name: layer.values[name][index] for name, _ in fields}, parts)
                    for index, (fid, parts) in enumerate(zip(layer.fids, layer.parts,
                                                             strict=True))]
    else:
        fields = list(gstore.domain_fields(project, source))
        entities = [(item.fid, item.attributes, item.polygons)
                    for item in gstore.load_domains(project, source)]
    column = next((name for name, title in fields if attribute in (name, title)), None)
    if column is None:
        raise ConstraintError("core.constraint_sectors_field_unknown", field="campo",
                              value=attribute, layer=source,
                              fields=", ".join(f"«{title}»" for _, title in fields) or "—")
    found = []
    for fid, attributes, parts in entities:
        value = attributes.get(column)
        name = "" if value is None else str(value)
        found.extend(_Polygon(int(fid), name, tuple(part)) for part in parts)
    return found


def sector_list(polygons: Sequence[tuple[int, str, Sequence[np.ndarray]]], *, layer: str,
                attribute: str) -> tuple[Sector, ...]:
    """Los sectores de unos polígonos (``(fid, nombre, anillos ABS)``, uno por parte):
    comprobados como RF-011-08 (:class:`SectorsError` con la lista si algo falla) y agrupados
    por nombre (sin los espacios de los extremos), en el orden en que aparece cada nombre; cada
    uno con un uid nuevo y su código (``core.constraints.model.constraint_code`` con
    :data:`SECTOR_PREFIX`)."""
    items = [_Polygon(int(fid), str(name), tuple(rings)) for fid, name, rings in polygons]
    found = geometry.problems([item.rings for item in items])
    shape = {problem.index: problem.problem for problem in found if problem.problem != "overlap"}
    listed: list[SectorProblem] = []
    for index, item in enumerate(items):
        if not item.name.strip():
            listed.append(SectorProblem("name_empty", item.fid, item.name))
        if index in shape:
            listed.append(SectorProblem(shape[index], item.fid, item.name))
    for problem in found:
        if problem.problem == "overlap" and problem.other is not None:
            first, second = items[problem.index], items[problem.other]
            listed.append(SectorProblem("overlap", first.fid, first.name, second.fid,
                                        second.name, problem.area_m2))
    if listed:
        raise SectorsError(listed, layer=layer, attribute=attribute)
    grouped: dict[str, list[np.ndarray]] = {}
    for item in items:
        grouped.setdefault(item.name.strip(), []).extend(item.rings)
    taken: set[str] = set()
    sectors = []
    for name, rings in grouped.items():
        code = constraint_code(name, taken, prefix=SECTOR_PREFIX)
        taken.add(code)
        sectors.append(Sector(uuid.uuid4().hex, code, name, tuple(rings)))
    return tuple(sectors)


def uncovered_m2(perimeter: Sequence[Sequence[np.ndarray]],
                 sectors: Sequence[Sequence[np.ndarray]]) -> float:
    """El área (m²) del perímetro (sus polígonos: los anillos de cada uno) que no cubre
    ninguno de los polígonos de los sectores (D-3): la diferencia exacta de
    ``gis.polygons.overlay``."""
    rings = [np.asarray(ring, dtype=np.float64) for polygon in perimeter for ring in polygon]
    if not rings:
        return 0.0
    origin = np.floor(np.min(np.vstack([ring[:, :2] for ring in rings]), axis=0))
    region = geometry.overlay(list(perimeter), list(sectors), "difference", origin=origin)
    return float(region.area_m2)


def declare_sectors(project: StoreProject, source: str | None, attribute: str | None, *,
                    version: str | None = None) -> DeclaredSectors:
    """Declara los sectores de búsqueda (RF-012-07): los de la capa ``source`` (el nombre de un
    dato ``gis_fea_`` de polígonos o ``gis_dom_``) por su campo ``attribute``, o ninguno (sin
    capa: el perímetro como único sector, D-26), con ``core.declare_sectors``. El área sin
    sector se mide con el perímetro activo en ``version`` (uid o código) o, sin ella, en el
    proyecto. Los rechazos (:class:`SectorsError`, ``ConstraintError``) salen antes de registrar
    nada."""
    srs = int(project.record.crs_epsg)
    if source is None:
        uid = cprov.declare_sectors(project, (), source=None, field=None, uncovered_m2=None,
                                    srs_id=srs)
        return DeclaredSectors(uid, (), None)
    if not isinstance(attribute, str) or not attribute.strip():
        raise ValueError("los sectores de una capa se nombran por un campo: falta cuál")
    polygons = _polygons(project, source, attribute)
    sectors = sector_list([(item.fid, item.name, item.rings) for item in polygons],
                          layer=source, attribute=attribute)
    with project.read() as conn:
        constraints = cstore.read_constraints(conn)
        resolved = _resolved(conn, project, constraints, version)
    perimeter = [part for item in perimeter_of(constraints, resolved) for part in item.parts]
    uncovered = (uncovered_m2(perimeter, [item.rings for item in polygons]) if perimeter
                 else None)
    uid = cprov.declare_sectors(project, sectors, source=source, field=attribute,
                                uncovered_m2=uncovered, srs_id=srs)
    return DeclaredSectors(uid, sectors, uncovered)


# --- La búsqueda -----------------------------------------------------------------------------


def _distance(project: StoreProject) -> float:
    """La distancia de búsqueda del proyecto (m): el parámetro o, si aún no está, su valor por
    defecto (lo registra la operación al cerrar, RF-008-04)."""
    with project.read() as conn:
        try:
            value = ParameterStore(project).resolve(conn, SEARCH_DISTANCE.key).value
        except ParamError:
            value = SEARCH_DISTANCE.default
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"la distancia de búsqueda no tiene valor: {value!r}")
    return float(value)


def _sector(project: StoreProject, code: str, version: str | None) -> tuple[Sector, str]:
    with project.read() as conn:
        for sector, dataset in search_sectors(conn, project, version):
            if sector.code == code:
                return sector, dataset
    raise ConstraintError("core.constraint_sector_unknown", field="sector", value=code)


def _hashes(project: StoreProject, names: Sequence[str]) -> tuple[str, ...]:
    with project.read() as conn:
        found = []
        for name in names:
            record = dataset_registry.get(conn, name)
            found.append("" if record is None else str(record.content_sha256))
    return tuple(found)


def search_steps(project: StoreProject, sector_code: str, layers: Sequence[str], *,
                 version: str | None = None, budget_s: float = finder.STEP_BUDGET_S
                 ) -> Iterator[Progress]:
    """Los pasos de buscar intocables (RF-012-08) en el sector ``sector_code`` (``""``: el
    perímetro, activo en ``version`` o en el proyecto) en las capas ``layers`` (nombres de datos
    ``gis_fea_``, de 1 a 10) a ≤ la distancia de búsqueda del proyecto. El último ``Progress``
    lleva :class:`Searched`. Los rechazos (sector desconocido, capas de más o de menos, una capa
    que no es de entidades) salen al llamar, antes del primer paso."""
    layers = tuple(layers)
    if not 1 <= len(layers) <= cprov.MAX_LAYERS:
        raise ConstraintError("core.constraint_search_layers", field="capas",
                              value=len(layers), max=cprov.MAX_LAYERS)
    if len(set(layers)) != len(layers):
        raise ValueError(f"una búsqueda no consulta dos veces la misma capa: {layers!r}")
    sector, dataset = _sector(project, sector_code, version)
    loaded: dict[str, FeatureLayer] = {}
    for name in layers:
        if _family(name) != FEATURES:
            raise ValueError(f"una búsqueda consulta capas «entidades» (gis_fea_), no «{name}»")
        layer = gstore.load_features(project, name)
        assert isinstance(layer, FeatureLayer)
        loaded[name] = layer
    distance = _distance(project)
    steps = finder.search_steps(sector.rings, loaded, distance, budget_s=budget_s)
    searched = Searched(sector.code, sector.name, cstore.sector_sha256(sector), dataset, layers,
                        _hashes(project, layers), distance)
    return _steps(steps, searched)


def _steps(steps: Iterator[Progress], searched: Searched) -> Iterator[Progress]:
    for progress in steps:
        if progress.result is None:
            yield progress
            continue
        found = tuple(progress.result)  # type: ignore[call-overload]
        yield Progress(progress.phase, progress.done, progress.total, progress.message,
                       Searched(searched.sector_code, searched.sector_name,
                                searched.sector_sha256, searched.sector_dataset,
                                searched.layers, searched.layer_sha256, searched.distance_m,
                                found))


def _shown(found: finder.Found) -> str:
    label = next((str(value) for value in found.attributes.values()
                  if isinstance(value, str) and value.strip()), None)
    where = f"{found.layer}, entidad {found.fid}, {format_number(found.distance_m, 1)} m"
    return f"«{label}» ({where})" if label else f"({where})"


def close_search(project: StoreProject, searched: Searched, decisions: Sequence[Decision], *,
                 closed_by: str, version: str | None = None) -> SearchRecord:
    """Cierra la búsqueda ``searched`` con una decisión por entidad hallada (RF-012-09) y la
    registra (``core.find_untouchables``) como de ``closed_by``. ``ConstraintError``
    ``core.constraint_search_undecided`` si alguna no tiene decisión y
    ``core.constraint_search_outdated`` si el sector (otra huella) o una capa (otro hash)
    cambió después de buscar; ``ValueError`` si una decisión no es de nada hallado o se
    repite. Nada se registra si se rechaza."""
    chosen: dict[tuple[str, int], Decision] = {}
    for decision in decisions:
        key = (decision.layer, int(decision.fid))
        if key in chosen:
            raise ValueError(f"dos decisiones para la entidad {key[1]} de «{key[0]}»")
        chosen[key] = decision
    found_keys = {(item.layer, item.fid) for item in searched.found}
    extra = sorted(set(chosen) - found_keys)
    if extra:
        raise ValueError(f"decisiones de entidades que no se hallaron: {extra!r}")
    missing = [item for item in searched.found if (item.layer, item.fid) not in chosen]
    if missing:
        raise ConstraintError("core.constraint_search_undecided", field="decisión",
                              value=len(missing), items="; ".join(map(_shown, missing)))
    where = (f"el sector «{searched.sector_name}»" if searched.sector_code
             else searched.sector_name)
    sector, _ = _sector(project, searched.sector_code, version)
    if cstore.sector_sha256(sector) != searched.sector_sha256:
        raise ConstraintError("core.constraint_search_outdated", field="sector",
                              value=f"La geometría de {where}", sector=where)
    for name, before, now in zip(searched.layers, searched.layer_sha256,
                                 _hashes(project, searched.layers), strict=True):
        if before != now:
            raise ConstraintError("core.constraint_search_outdated", field="capas",
                                  value=f"La capa «{name}»", sector=where)
    hits = []
    for item in searched.found:
        decision = chosen[(item.layer, item.fid)]
        hits.append(SearchHit("", str(item.layer), int(item.fid), float(item.distance_m),
                               dict(_plain(item.attributes)), decision.decision,
                               decision.reason, decision.constraint_code))
    return cprov.close_search(
        project, sector_code=searched.sector_code, sector_sha256=searched.sector_sha256,
        sector_dataset=searched.sector_dataset, layers=searched.layers,
        distance_m=searched.distance_m, hits=hits, closed_by=closed_by,
        srs_id=int(project.record.crs_epsg))


def _plain(attributes: Mapping[str, Any]) -> dict[str, Any]:
    """Los atributos en JSON: lo que no es texto, número o nulo, como texto; un real no finito,
    nulo."""
    found: dict[str, Any] = {}
    for name, value in attributes.items():
        if isinstance(value, float) and not math.isfinite(value):
            value = None
        elif value is not None and not isinstance(value, str | int | float):
            value = str(value)
        found[str(name)] = value
    return found

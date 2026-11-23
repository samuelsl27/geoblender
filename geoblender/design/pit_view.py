# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que leen de una corta calculada las órdenes «Línea de cielo…» y «Superficie y sólido…» (spec 018, T33; HU-018-4; RF-018-29, RF-018-30, RF-018-33; plan 018 §5.3.3).

Solo **lee** del proyecto (nada se escribe aquí): de la corta ``ref`` (su código o su nombre) de una versión,

- :func:`skyline_report`: las **cifras registradas** de su línea de cielo (``des.pit_sky_*``, con su unidad, su tipo y su procedencia, RF-008-30), **el lugar** de la distancia mínima al límite legal y al
  perímetro de actuación (no lo guarda ninguna cifra: se mide sobre la línea guardada, ``des_psk_``, con :func:`~.pit_sky.limit_distances` y los polígonos compilados de la versión de hoy) y si la capa
  de la línea de cielo (``des_sky_<vNN>``) está atrasada (:func:`~.pit_layer.pit_layer_pending`);
- :func:`pit_datasets`: los datos de la corta con que se hacen sus vistas y sus entregables: sus polilíneas (el TIN), sus bancos (el sólido), su superficie (el GeoTIFF) y sus hallazgos (el CSV).

Python puro (nivel 8); perezoso (lo importan las órdenes al usarlo, RNF-001-03).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..core.datasets import registry as dataset_registry
from ..core.provenance import figures as prov_figures
from ..core.versions import read as versions_read
from ..core.versions.model import Version
from ..gis.store import StoreProject
from . import entities, entity_store, pit_layer, pit_sky, pit_store, provenance
from .messages import DesignError

__all__ = ["PitDatasets", "SKY_FIGURE_PREFIX", "SkylineReport", "pit_datasets", "skyline_report"]

SKY_FIGURE_PREFIX = "des.pit_sky_"
"""El comienzo de la clave de las cifras de la línea de cielo (RF-018-29)."""


def _pit(project: StoreProject, conn: sqlite3.Connection, version_uid: str, ref: str) -> tuple[Version, pit_layer.PitHead]:
    """La versión y la corta **calculada** ``ref`` (código o nombre) de ``version_uid``: ``des.pit_view_unknown`` si la versión no tiene esa corta calculada. ``TypeError`` si ``ref`` no es un texto."""
    if not isinstance(ref, str) or not ref.strip():
        raise TypeError(f"una corta se indica por su código o su nombre, no {ref!r}")
    version = versions_read.version(conn, version_uid)
    if version is None:
        raise ValueError(f"la versión {version_uid!r} no existe")
    entry = entities.registry(project, version.uid, conn=conn).get(ref.strip())
    if entry is None or entry.record.kind != entities.EntityKind.PIT or entry.operation_uid is None:
        raise DesignError("des.pit_view_unknown", obj=ref.strip(), field="corta", value=ref.strip(), name=ref.strip(), version=version.code)
    heads = [head for head in pit_layer.pit_heads(project, conn, version) if head.code == entry.record.code]
    if not heads:  # una corta con estado que las capas no enseñan: no tiene línea de cielo que mostrar
        raise DesignError("des.pit_view_unknown", obj=ref.strip(), field="corta", value=ref.strip(), name=ref.strip(), version=version.code)
    return version, heads[0]


@dataclass(frozen=True, slots=True, eq=False)
class SkylineReport:
    """La línea de cielo de la corta ``code`` (``name``) de la versión ``version_code``, tal como está en el proyecto (:func:`skyline_report`): sus cifras registradas (``figures``, de la operación
    vigente de la corta; ``des.pit_sky_*``), el lugar de la distancia mínima al límite legal (``legal``) y al perímetro (``perimeter``; ``None`` sin límite o sin línea; el lugar se **mide** sobre la
    línea guardada y los polígonos de hoy) y si su capa está atrasada (``layer_pending``)."""

    code: str
    name: str
    version_code: str
    state: entities.EntityState
    figures: tuple[prov_figures.FigureRecord, ...]
    legal: pit_sky.SkyDistance | None
    perimeter: pit_sky.SkyDistance | None
    layer_pending: bool


def skyline_report(project: StoreProject, version_uid: str, ref: str) -> SkylineReport:
    """Lo que dice el proyecto de la línea de cielo de la corta ``ref`` en la versión ``version_uid`` (véase el módulo). ``DesignError`` ``des.pit_view_unknown`` si no es una corta calculada de la versión
    y los de :func:`~.pit_layer.pit_sources` si su dato está bloqueado o dañado. Solo lee, con una instantánea."""
    with entity_store._consistent(project) as conn:  # noqa: SLF001 - la misma lectura consistente que las capas
        version, head = _pit(project, conn, version_uid, ref)
        found = tuple(prov_figures.FigureRecord.from_row(row) for row in conn.execute(
            f"SELECT {prov_figures.RECORD_COLUMNS} FROM gb_figure AS f WHERE f.operation_uid = ? AND f.key LIKE ? ORDER BY f.fid", (head.operation_uid, f"{SKY_FIGURE_PREFIX}%")))
        source = pit_layer.pit_source(conn, head, version)
        pending = pit_layer.pit_layer_pending(project, conn, version.uid)
    legal = perimeter = None
    if source.skyline:
        parts = tuple(pit_sky.SkyPart(row.points, False) for row in source.skyline)
        perimeter_limit, legal_limit = pit_store.ProjectReader(project, version).limits()
        legal, perimeter = pit_sky.limit_distances(parts, legal=legal_limit, perimeter=perimeter_limit)
    return SkylineReport(head.code, head.name, version.code, head.state, found, legal, perimeter, pending)


@dataclass(frozen=True, slots=True)
class PitDatasets:
    """Los datos de la corta ``code`` (``name``) de la versión ``version_uid`` (``version_code``) con que se hacen sus vistas y sus entregables (:func:`pit_datasets`): el uid de sus polilíneas (el TIN) y de sus
    bancos (el sólido), y el nombre de su superficie (``des_psf_``) y de sus hallazgos (``des_pfn_``) para exportarlos."""

    code: str
    name: str
    version_uid: str
    version_code: str
    polylines_uid: str
    benches_uid: str
    surface: str
    findings: str


def pit_datasets(project: StoreProject, version_uid: str, ref: str) -> PitDatasets:
    """Los datos de la corta ``ref`` (código o nombre) calculada en ``version_uid`` (véase :class:`PitDatasets`): los de la operación **vigente** de la corta, por su nombre de cuando se calculó (que puede ser
    otro que el de hoy). ``DesignError`` ``des.pit_view_unknown`` si no es una corta calculada de la versión; los de las capas si un dato está bloqueado o dañado. Solo lee."""
    with entity_store._consistent(project) as conn:  # noqa: SLF001 - la misma lectura consistente que las capas
        version, head = _pit(project, conn, version_uid, ref)
        poly_table, poly_name = pit_layer.pit_data(conn, head, version, provenance.PIT_POLYLINES_ROLE, "polilíneas")
        bench_table, bench_name = pit_layer.pit_data(conn, head, version, provenance.PIT_BENCHES_ROLE, "bancos")
        del poly_table, bench_table
        polylines = dataset_registry.get(conn, poly_name, version_uid=version.uid)
        benches = dataset_registry.get(conn, bench_name, version_uid=version.uid)
    if polylines is None or benches is None:
        raise DesignError("des.pit_view_unknown", obj=ref.strip(), field="corta", value=ref.strip(), name=ref.strip(), version=version.code)
    calc = poly_name.removeprefix(provenance.dataset_name(provenance.PIT_POLYLINES_TABLE, "x")[:-1])
    return PitDatasets(head.code, head.name, version.uid, version.code, str(polylines.uid), str(benches.uid),
                       provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, calc), provenance.dataset_name(provenance.PIT_FINDINGS_TABLE, calc))


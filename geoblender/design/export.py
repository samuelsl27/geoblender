# SPDX-License-Identifier: GPL-3.0-or-later
"""Exportar una rejilla del diseño a GeoTIFF (spec 013, T19; HU-013-6; RF-013-34; RF-006-24;
RF-008-15; plan 013 §5.1 y §5.3.3; ADR-0014; D-29 de la 011).

Exportar **no es una operación** (D-29 de la 011): el entregable se escribe desde lo registrado,
también con el proyecto en solo lectura (si el destino está fuera de él) y desde una versión que ya
no es editable; nada se registra. Se exporta cualquiera de las rejillas de una versión
(:data:`GRIDS`): de la 013, la envolvente (``des_env_``), la superficie de diseño (``des_srf_``) o la
rejilla de cotas de berma (``des_brm_``); de la 014 (T33; RF-014-32; :data:`QUARRY_GRIDS`), las dos
superficies de una cantera (``des_exp_``, ``des_fin_``) y sus envolventes (``des_xen_``,
``des_fen_``), la transición (``des_trn_``), la superficie ajustada a un límite nuevo
(``des_adj_``), la clasificación de una cantera (``des_cls_``) y el recinto excavable
(``des_rcn_``); de la 015 (T30; RF-015-27; :data:`ENTITY_GRIDS`), la superficie que deja una entidad
(``des_psf_``), como las de la 013; las tablas no son rejillas y no se exportan aquí. :func:`stored_grid` (T28)
dice cuál es y de qué versión el dato que elige quien exporta (su uid o su nombre): solo una rejilla
**viva** del diseño (``des.export_not_grid``); de una entidad, también por su tabla (``des_epr_``, la que
enseña la vista), que da su superficie.

**Las rejillas de códigos** (spec 014, T33; RF-014-32; plan 014 P-1): la clasificación y el recinto
no son cotas sino un **código por celda** (:data:`LEGENDS`: 0 sin diferencia, 1 desdoblado y 2
relleno de restauración, los de ``design.model.CellClass``; 1 dentro del recinto excavable), que el
entregable Float32 lleva exacto. Sus metadatos dicen ``UNIDAD`` ``código`` (:data:`CODE_UNIT`) y,
en vez de una unidad física, **su leyenda**: un ``CODIGO_<n>`` por clase con su nombre en español,
el mismo de la vista y de la barra N (T51).

**El GeoTIFF** (:func:`export_grid_steps`, :func:`export_grid`; RF-006-24): la rejilla registrada
(``rasters/des_*_<vNN>.tif``, Float64 con NaN) como GeoTIFF del perfil ``deliverable`` de la 006
(``gis.geotiff.writer.write_steps``): Float32, **sin dato −9999 declarado** (``GDAL_NODATA``; toda
celda sin dato, NaN o infinita, lo lleva), el CRS y la referencia vertical del proyecto, cada cota
igual a la registrada redondeada al float32 más próximo (las cotas son metros: ni escala ni
desplazamiento) y compresión sin pérdida; una cota que en float32 fuese el −9999 o no cupiese se
rechaza antes de escribir (``gis.export_nodata_collision``, ``gis.export_value_out_of_range``). Con
sus metadatos (:func:`metadata_items`, ``GDAL_METADATA``): ``UNIDAD`` (``m``; ``código`` en una
rejilla de códigos, con su leyenda), ``TIPO`` (qué es, en español), ``DATO`` (el dato del proyecto
del que sale) y ``VERSION``.

**El destino** (:func:`check_target`, antes de escribir nada): con su extensión
(``gis.export_extension_invalid``); dentro del proyecto, solo en ``exports/``
(``gis.export_inside_project``) y nunca con el proyecto en solo lectura
(``des.export_read_only_project``); la guarda de las escrituras de la 008
(``core.inputs.check_write_target``: ni sobre una entrada, ni en la carpeta de su fuente, ni en una
carpeta de solo lectura; RF-008-15); y sobre un fichero que ya existe, solo con ``overwrite``
(``gis.export_target_exists``: quien exporta pregunta). Se escribe en un temporal
(``<destino>.tmp``, en la misma carpeta) con ``fsync`` y ``os.replace``: si otro programa tiene
abierto el destino (QGIS), ``gis.raster_target_locked`` y el anterior intacto; un fallo del disco,
``gis.raster_write_failed``; en los dos, sin temporal.

**Por pasos** (RNF-013-07): el primero lee la rejilla registrada (una unidad) y cada uno de los
siguientes escribe una tesela; el último pone el fichero en su sitio. Cerrar los pasos antes (Esc)
no deja nada. Python puro (nivel 8).
"""

from __future__ import annotations

import sqlite3
import sys
from collections.abc import Generator, Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

from ..core.datasets import registry as dataset_registry
from ..core.datasets.model import DatasetRecord
from ..core.inputs.guard import GuardProject, check_write_target
from ..core.paths import ReadOnlyDirs, check_path_length
from ..core.versions import read as versions_read
from ..core.versions.model import Version, VersionError
from ..gis.geotiff.reader import read_geotiff
from ..gis.geotiff.writer import DELIVERABLE_NODATA, temporary_path, write_steps
from ..gis.messages import GisError
from ..gis.provenance import export_locator, inside_project
from ..gis.raster import Raster
from ..gis.store import StoreProject, project_references
from . import provenance as declared
from .messages import DesignError
from .model import CellClass
from .quarry import CLASS_NAMES

__all__ = [
    "CODE_UNIT",
    "ENTITY_GRIDS",
    "GRIDS",
    "LEGENDS",
    "LEGEND_KEY",
    "NODATA",
    "QUARRY_GRIDS",
    "SUFFIXES",
    "UNIT",
    "ExportProject",
    "StoredGrid",
    "check_target",
    "export_grid",
    "export_grid_steps",
    "metadata_items",
    "stored_grid",
]

QUARRY_GRIDS: tuple[str, ...] = (
    declared.EXPLOITATION_GRID, declared.FINAL_GRID, declared.EXPLOITATION_ENVELOPE_GRID,
    declared.FINAL_ENVELOPE_GRID, declared.TRANSITION_GRID, declared.REFIT_GRID,
    declared.CLASSIFICATION_GRID, declared.EXCAVATION_AREA_GRID)
"""Las rejillas de la 014 que se pueden exportar (T33; RF-014-32): las cotas de las superficies y
de las envolventes y las dos rejillas de códigos (:data:`LEGENDS`)."""
ENTITY_GRIDS: tuple[str, ...] = (declared.ENTITY_SURFACE_GRID,)
"""Las rejillas de la 015 que se pueden exportar (T30; RF-015-27): la superficie que deja una entidad, de cotas
como las de la 013."""
GRIDS: tuple[str, ...] = (declared.ENVELOPE_GRID, declared.DESIGN_GRID, declared.BERMS_GRID,
                          *QUARRY_GRIDS, *ENTITY_GRIDS)
"""Las familias de datos de ``des`` que son una rejilla (de cotas o de códigos) y se pueden
exportar: las tres de la 013, las de :data:`QUARRY_GRIDS` y las de :data:`ENTITY_GRIDS`."""
LEGENDS: Mapping[str, tuple[tuple[int, str], ...]] = MappingProxyType({
    declared.CLASSIFICATION_GRID: tuple((item.code, CLASS_NAMES[item]) for item in CellClass),
    declared.EXCAVATION_AREA_GRID: ((1, "recinto excavable"),),
})
"""Las rejillas de **códigos** (spec 014, T33; RF-014-32; P-1) con su leyenda: por código, el
nombre de su clase en español, el de la vista y la barra N (T51; la clasificación, los de
``CellClass`` con ``quarry.CLASS_NAMES``: 0 sin diferencia, 1 desdoblado, 2 relleno de
restauración; el recinto, 1 «recinto excavable», como en spec 014 §6). Las demás rejillas son
cotas en metros."""
SUFFIXES: tuple[str, ...] = (".tif", ".tiff")
"""Las extensiones del GeoTIFF entregable."""
NODATA = DELIVERABLE_NODATA
"""El sin dato del entregable (−9999; RF-006-24)."""
UNIT = "m"
"""La unidad de la cota, declarada en los metadatos."""
CODE_UNIT = "código"
"""Lo que declaran los metadatos de una rejilla de :data:`LEGENDS` en vez de una unidad: su valor
es el código de una clase de su leyenda."""
LEGEND_KEY = "CODIGO_{code}"
"""La clave de los metadatos con el nombre de la clase de cada código."""

_FIELD_TARGET = "destino"
_FIELD_EXTENSION = "extensión"
_FIELD_GRID = "rejilla"


class ExportProject(StoreProject, GuardProject, Protocol):
    """Lo que la exportación usa del proyecto (``core.project.Project``): lo de la guarda de las
    escrituras y de ``gis.store`` (su raíz, su nombre, si se puede escribir, su fila de
    ``gb_project`` con el CRS y la referencia vertical) y una lectura."""


# --- Lo que se exporta -------------------------------------------------------------------------


def _family(family: object) -> declared.DatasetFamily:
    if not isinstance(family, str) or family not in GRIDS:
        raise ValueError(f"{family!r} no es una rejilla del diseño que se exporte: es una de "
                         f"{', '.join(GRIDS)}")
    return declared.FAMILIES_BY_CODE[family]


def _name(name: object) -> str:
    if not isinstance(name, str) or not name.strip():
        raise TypeError(f"una rejilla del diseño se indica por el nombre de su operación, "
                        f"no {name!r}")
    return name


def metadata_items(family: str, name: str, version_code: str) -> dict[str, str]:
    """Los metadatos de texto del GeoTIFF (``GDAL_METADATA``) de la rejilla ``family`` de la
    operación ``name`` en la versión ``version_code``: ``UNIDAD`` (:data:`UNIT`), ``TIPO`` (qué
    es, en español: «Envolvente», «Superficie de diseño», «Cota real de las bermas», «Superficie
    final»…), ``DATO`` (su nombre en el proyecto, en ASCII) y ``VERSION``. Una rejilla de códigos
    (:data:`LEGENDS`: la clasificación o el recinto de la 014; RF-014-32) declara ``UNIDAD``
    :data:`CODE_UNIT` y, detrás, su leyenda: ``CODIGO_<n>`` con el nombre de la clase de cada
    código. Sin «&» (GDAL 3.13 lo lee mal): el nombre de la operación no va tal cual, sino en el
    del dato. ``ValueError`` si la familia no es una rejilla del diseño o la versión es un texto
    vacío."""
    found = _family(family)
    if not isinstance(version_code, str) or not version_code.strip():
        raise ValueError(f"la versión de los metadatos es un texto no vacío, no {version_code!r}")
    legend = LEGENDS.get(family, ())
    items = {"UNIDAD": CODE_UNIT if legend else UNIT, "TIPO": found.label,
             "DATO": declared.dataset_name(family, name), "VERSION": version_code}
    items.update((LEGEND_KEY.format(code=code), label) for code, label in legend)
    return items


def _version(project: ExportProject, version: object) -> Version:
    if not isinstance(version, str) or not version:
        raise TypeError(f"la versión se indica por su uid o su código, no {version!r}")
    with project.read() as conn:
        found = versions_read.version(conn, version)
    if found is None:
        raise VersionError("core.version_unknown", field="versión", value=version,
                           version=version)
    return found


def _registered_file(project: ExportProject, family: str, name: str, found: Version) -> Path:
    """El fichero registrado de la rejilla ``family`` de ``name`` en la versión ``found``."""
    dataset = declared.dataset_name(family, name)
    with project.read() as conn:
        record = dataset_registry.get(conn, dataset, version_uid=found.uid)
    if record is None or record.name != dataset:
        raise DesignError("des.export_unknown", obj=name, field=_FIELD_GRID, value=name,
                          version=found.code, dataset=dataset)
    path = Path(project.root).joinpath(*record.locator.split("/"))
    if not path.is_file():
        raise GisError("gis.dataset_file_missing", obj=record.name, field="fichero",
                       value=path.name, file=path.name, name=record.name)
    return path


@dataclass(frozen=True, slots=True)
class StoredGrid:
    """Una rejilla viva del diseño que se puede exportar (:func:`stored_grid`): su dato, su
    familia (una de :data:`GRIDS`), el nombre de su operación tal como está en el nombre de su dato
    (``hoyo`` de ``des_env_hoyo``; vale tal cual para :func:`export_grid_steps`) y su versión (su
    uid y su código)."""

    record: DatasetRecord
    family: str
    name: str
    version_uid: str
    version_code: str


def _grid_family(record: DatasetRecord | None) -> str | None:
    """La familia de rejilla exportable de ``record`` por el comienzo de su nombre, o ``None``."""
    if record is None or record.module != declared.MODULE:
        return None
    return next((family for family in GRIDS
                 if record.name.startswith(declared.FAMILIES_BY_CODE[family].prefix)), None)


def _surface_of_entity(conn: sqlite3.Connection, record: DatasetRecord | None) -> DatasetRecord | None:
    """La superficie (``des_psf_<nombre>``) de la entidad cuya tabla (``des_epr_<nombre>``) es ``record``, en la
    versión de la tabla; ``None`` si ``record`` no es la tabla de una entidad o su versión no tiene la superficie."""
    table = declared.FAMILIES_BY_CODE[declared.ENTITY_TABLE]
    if record is None or record.module != declared.MODULE or not record.name.startswith(table.prefix):
        return None
    owner = versions_read.dataset_versions(conn, [record.uid]).get(record.uid, "")
    if not owner:
        return None
    surface = declared.FAMILIES_BY_CODE[declared.ENTITY_SURFACE_GRID].prefix + record.name[len(table.prefix):]
    return dataset_registry.get(conn, surface, version_uid=owner)


def stored_grid(project: ExportProject, ref: str, *, version: str = "") -> StoredGrid:
    """La rejilla del diseño ``ref`` —el uid de su dato o su nombre en la versión ``version`` (su
    uid)— con lo que pide :func:`export_grid_steps`: su familia, el nombre de su operación y su
    versión. ``DesignError`` ``des.export_not_grid`` si no es una rejilla **viva** del diseño
    de una versión, de :data:`GRIDS`: una envolvente, una superficie de diseño o una rejilla de
    cotas de berma de la 013; una superficie, una envolvente, la clasificación o el recinto de la
    014; la superficie de una entidad de la 015: una tabla, un dato de otro módulo, uno que no existe, uno
    sustituido o descartado, o uno por su nombre sin la versión que lo tiene. **La tabla de una entidad**
    (``des_epr_<nombre>``: la que enseña la vista, T30) da la **superficie** de esa entidad
    (``des_psf_<nombre>``) de su versión. ``TypeError`` si ``ref`` o ``version`` no son textos (o
    ``ref``, vacío). No escribe nada."""
    if not isinstance(ref, str) or not ref:
        raise TypeError(f"una rejilla del diseño se indica por el uid o el nombre de su dato, "
                        f"no {ref!r}")
    if not isinstance(version, str):
        raise TypeError(f"la versión se indica por su uid ('' sin ninguna), no {version!r}")
    with project.read() as conn:
        record = dataset_registry.get(conn, ref, version_uid=version)
        record = _surface_of_entity(conn, record) or record
        family = _grid_family(record)
        owner = ("" if record is None
                 else versions_read.dataset_versions(conn, [record.uid]).get(record.uid, ""))
        found = versions_read.version(conn, owner) if owner else None
    if record is None or not record.live or family is None or found is None:
        raise DesignError("des.export_not_grid", obj=ref, field=_FIELD_GRID, value=ref)
    return StoredGrid(record, family, record.name[len(declared.FAMILIES_BY_CODE[family].prefix):],
                      owner, found.code)


# --- El destino --------------------------------------------------------------------------------


def check_target(path: str | Path, *, project: ExportProject, read_only: ReadOnlyDirs,
                 overwrite: bool) -> Path:
    """El destino ``path`` del GeoTIFF, comprobado sin escribir nada (véase el módulo):
    ``GisError`` ``gis.export_extension_invalid``, ``gis.export_inside_project`` o
    ``gis.export_target_exists``; ``DesignError`` ``des.export_read_only_project``;
    ``ProvenanceError`` ``core.write_target_*`` (RF-008-15); ``core.path_too_long``."""
    if not isinstance(overwrite, bool):
        raise TypeError(f"«overwrite» es verdadero o falso, no {overwrite!r}")
    target = Path(path)
    name = target.name
    if target.suffix.lower() not in SUFFIXES:
        raise GisError("gis.export_extension_invalid", obj=name, field=_FIELD_EXTENSION,
                       value=target.suffix or "—", file=name, format="GeoTIFF",
                       expected="/".join(SUFFIXES))
    root = Path(project.root)
    if inside_project(root, target):
        if not project.writable:
            raise DesignError("des.export_read_only_project", obj=name, field=_FIELD_TARGET,
                              value=name, project=project.name)
        if export_locator(root, target) is None:
            raise GisError("gis.export_inside_project", obj=name, field=_FIELD_TARGET,
                           value=name, file=name, project=project.name)
    check_write_target(target, project=project, read_only=read_only)
    check_path_length(temporary_path(target), obj=name)
    if not overwrite and target.exists():
        raise GisError("gis.export_target_exists", obj=name, field=_FIELD_TARGET, value=name,
                       file=name)
    return target


# --- Exportar ----------------------------------------------------------------------------------


def export_grid_steps(project: ExportProject, family: str, name: str, path: str | Path, *,
                      version: str, read_only: ReadOnlyDirs,
                      overwrite: bool = False) -> Generator[float, None, Path]:
    """La rejilla ``family`` (una de :data:`GRIDS`) de la operación ``name`` en la versión
    ``version`` (uid o código) como GeoTIFF entregable en ``path``, por pasos (véase el módulo): al
    llamar, sin escribir nada, la versión (``VersionError`` ``core.version_unknown``), que la
    rejilla esté registrada en ella (``DesignError`` ``des.export_unknown``) y el destino
    (:func:`check_target`); el primer paso la lee y cada uno de los siguientes escribe una tesela
    (``gis.geotiff.writer.write_steps``: su avance, de 0 a 1); el último la pone en su sitio y
    devuelve ``path`` (``StopIteration.value``). Cerrar los pasos antes no deja nada. ``ValueError``
    si ``family`` no es una rejilla del diseño; ``TypeError`` si ``name``, ``version`` u
    ``overwrite`` no son del tipo que toca."""
    _family(family)
    shown = _name(name)
    found = _version(project, version)
    source = _registered_file(project, family, shown, found)
    target = check_target(path, project=project, read_only=read_only, overwrite=overwrite)
    metadata = metadata_items(family, shown, found.code)
    return _export_steps(project, source, target, metadata)


def _export_steps(project: ExportProject, source: Path, target: Path,
                  metadata: dict[str, str]) -> Generator[float, None, Path]:
    registered = read_geotiff(source, max_cells=sys.maxsize)
    crs, vertical = project_references(project)
    raster = Raster(registered.grid, registered.values, registered.declared_crs or crs,
                    registered.declared_vertical or vertical)
    yield 0.0
    return (yield from write_steps(raster, target, profile="deliverable", metadata=metadata))


def export_grid(project: ExportProject, family: str, name: str, path: str | Path, *,
                version: str, read_only: ReadOnlyDirs, overwrite: bool = False) -> Path:
    """:func:`export_grid_steps` de una vez: devuelve ``path``."""
    steps = export_grid_steps(project, family, name, path, version=version, read_only=read_only,
                              overwrite=overwrite)
    with closing(steps):
        while True:
            try:
                next(steps)
            except StopIteration as stop:
                return stop.value  # type: ignore[no-any-return]

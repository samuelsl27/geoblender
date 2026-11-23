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
(``des_psf_``), como las de la 013; de la 016 (T34; RF-016-24, RF-016-09; :data:`SUPPORTED_GRIDS`), **la base de los
acopios** de un material (``des_stb_``), **su espesor** (``des_stt_``), **el terreno sin acopios** (``des_stg_``) y **el
espesor de un cuerpo apoyado** (``des_bdt_``); de la 017 (T27; RF-017-27; :data:`ROAD_GRIDS`), **lo alcanzable** de una accesibilidad (``des_acc_``: un
**código** por celda, 1 alcanzable y 0 no, con su leyenda) —la superficie de una pista es ``des_psf_``, de las de la 015—; las tablas no son rejillas y no se exportan aquí (salvo **la rasante de una pista a
CSV**, :func:`export_road_csv`). :func:`stored_grid` (T28)
dice cuál es y de qué versión el dato que elige quien exporta (su uid o su nombre): solo una rejilla
**viva** del diseño (``des.export_not_grid``); de una entidad, también por su tabla (``des_epr_``, la que
enseña la vista), que da su superficie.

**Lo que se compone al exportar** (spec 016, T34; RF-016-24, RF-016-09; plan 016 §5.7 P-5): el terreno sin acopios
(``des_stg_``) se guarda **solo en las huellas** (el menor de la superficie detectada y de la base de cada acopio) y el
entregable es el **terreno entero**: lo guardado en las huellas y, fuera, la superficie de la que parte la detección (su
entrada ``surface``). Y el **espesor** de una entidad apoyada: el que guardan la detección (``des_stt_``, por material) y
el cuerpo (``des_bdt_``) se exporta tal cual; el de **una retirada y un contrafuerte**, que no lo guardan (su cuerpo es la
diferencia de dos superficies), se **resta al exportar** (``part=`` :data:`THICKNESS`): el de la retirada, la superficie
de partida menos la que deja (lo retirado), y el del contrafuerte, la que deja menos la de partida (lo que sube), en m y
nunca negativo; sin dato donde falta alguna de las dos. Una detección **del proyecto** (D-15) exporta sus rejillas sin
versión (su dato es del proyecto).

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
no deja nada.

**La rasante de una pista a CSV** (spec 017, T27; RF-017-27; decisión T27-a de la sesión principal; :func:`export_road_csv`, :func:`road_csv_bytes`): su eje por estaciones (``des_rdx_``: abscisa, x, y, cota del
terreno, cota de la rasante y pendiente, **en m y en %**), con la convención del CSV de la cubicación (``reserves.export``): UTF-8 con BOM, «;» de separador, filas acabadas en CRLF y los números con **coma
decimal**, sin separador de miles ni exponente, el decimal más corto que vuelve al mismo float64; la primera celda no es «ID». Como exportar a GeoTIFF **no es una operación** (D-29 de la 011): se escribe desde lo
registrado, con el proyecto en solo lectura si el destino está fuera de él y desde una versión que ya no es editable, y **no modifica nada del proyecto**; mismo destino (:func:`check_target`, con la extensión de
un CSV), mismo temporal con ``fsync`` y ``os.replace``.

**Qué se exporta de una pista o una accesibilidad** (spec 017, T33; RF-017-27, RF-017-29; :func:`stored_road_export`): de **una pista**, su superficie (``des_psf_``, GeoTIFF) o su rasante (``des_rdx_``, CSV); de
**una accesibilidad**, lo que alcanza (``des_acc_``, GeoTIFF de códigos con su leyenda). Se elige por el código o el nombre de la entidad de la versión. Python puro (nivel 8).
"""

from __future__ import annotations

import csv
import io
import os
import sqlite3
import sys
from collections.abc import Callable, Generator, Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

import numpy as np

from ..core.datasets import registry as dataset_registry
from ..core.datasets.model import DatasetRecord
from ..core.inputs.guard import GuardProject, check_write_target
from ..core.paths import ReadOnlyDirs, check_path_length
from ..core.versions import read as versions_read
from ..core.versions.model import Version, VersionError
from ..gis.geotiff.reader import read_geotiff
from ..gis.geotiff.writer import DELIVERABLE_NODATA, target_locked, temporary_path, write_failed, write_steps
from ..gis.messages import GisError
from ..gis.provenance import export_locator, inside_project
from ..gis.raster import Raster
from ..gis.store import StoreProject, project_references
from . import entities
from . import provenance as declared
from .messages import DesignError
from .model import CellClass
from .quarry import CLASS_NAMES

__all__ = [
    "CODE_UNIT",
    "CSV_COLUMNS",
    "CSV_SUFFIXES",
    "ENTITY_GRIDS",
    "GRIDS",
    "LEGENDS",
    "LEGEND_KEY",
    "NODATA",
    "PART_THICKNESS",
    "PROJECT_VERSION",
    "QUARRY_GRIDS",
    "PIT_FINDING_CSV_COLUMNS",
    "ROAD_EXPORTS",
    "ROAD_GRIDS",
    "SUFFIXES",
    "SUPPORTED_GRIDS",
    "UNIT",
    "ExportProject",
    "StoredGrid",
    "StoredPitFindings",
    "StoredRoad",
    "check_target",
    "compose_ground",
    "export_grid",
    "export_grid_steps",
    "export_pit_findings_csv",
    "export_road_csv",
    "metadata_items",
    "road_csv_bytes",
    "stored_grid",
    "stored_pit_findings",
    "stored_road",
    "stored_road_export",
    "thickness_between",
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
SUPPORTED_GRIDS: tuple[str, ...] = (declared.STOCKPILE_BASE_GRID, declared.STOCKPILE_THICKNESS_GRID,
                                    declared.STOCKPILE_GROUND_GRID, declared.BODY_THICKNESS_GRID)
"""Las rejillas de la 016 que se pueden exportar (T34; RF-016-24): la base (``des_stb_``) y el espesor (``des_stt_``) de los
acopios de un material, el terreno sin acopios (``des_stg_``: se exporta **compuesto entero**, :func:`compose_ground`) y el
espesor de un cuerpo apoyado (``des_bdt_``). Son datos **dispersos** (sin dato fuera de las huellas) salvo el terreno. Una
detección del proyecto (D-15) las tiene sin versión."""
ROAD_GRIDS: tuple[str, ...] = (declared.ACCESS_GRID,)
"""Las rejillas de la 017 que se pueden exportar (T27; RF-017-27): **lo alcanzable** de una accesibilidad (``des_acc_``), una rejilla de **códigos** (1 alcanzable y 0 no; :data:`LEGENDS`). La superficie
que deja una pista es ``des_psf_``: una de :data:`ENTITY_GRIDS`."""
GRIDS: tuple[str, ...] = (declared.ENVELOPE_GRID, declared.DESIGN_GRID, declared.BERMS_GRID,
                          *QUARRY_GRIDS, *ENTITY_GRIDS, *SUPPORTED_GRIDS, *ROAD_GRIDS)
"""Las familias de datos de ``des`` que son una rejilla (de cotas o de códigos) y se pueden
exportar: las tres de la 013, las de :data:`QUARRY_GRIDS`, las de :data:`ENTITY_GRIDS`, las de :data:`SUPPORTED_GRIDS` y las de :data:`ROAD_GRIDS`."""
PART_THICKNESS = "thickness"
"""La parte ``thickness`` de una entidad apoyada (``stored_grid(…, part=PART_THICKNESS)``, ``export_grid_steps(…, part=…)``):
su espesor, en vez de su superficie. El de un cuerpo es el dato que guarda (``des_bdt_``); el de una retirada y el de un
contrafuerte, la resta de sus dos superficies (:func:`thickness_between`)."""
PROJECT_VERSION = "proyecto"
"""Lo que dice el metadato ``VERSION`` de una rejilla del proyecto (sin versión: la detección de acopios del proyecto)."""
LEGENDS: Mapping[str, tuple[tuple[int, str], ...]] = MappingProxyType({
    declared.CLASSIFICATION_GRID: tuple((item.code, CLASS_NAMES[item]) for item in CellClass),
    declared.EXCAVATION_AREA_GRID: ((1, "recinto excavable"),),
    declared.ACCESS_GRID: ((0, "no alcanzable"), (1, "alcanzable")),
})
"""Las rejillas de **códigos** (spec 014, T33; RF-014-32; P-1) con su leyenda: por código, el
nombre de su clase en español, el de la vista y la barra N (T51; la clasificación, los de
``CellClass`` con ``quarry.CLASS_NAMES``: 0 sin diferencia, 1 desdoblado, 2 relleno de
restauración; el recinto, 1 «recinto excavable», como en spec 014 §6; de la 017, T27, lo alcanzable de una accesibilidad: 0 «no alcanzable» y 1
«alcanzable», como ``des_acc_``). Las demás rejillas son cotas en metros."""
PARTS: tuple[str, ...] = ("", PART_THICKNESS)
"""Lo que se puede pedir de una entidad al exportarla: su rejilla (``""``) o su espesor (:data:`PART_THICKNESS`)."""
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

_BODY, _REMOVAL, _BUTTRESS = "body", "removal", "buttress"
"""Los tipos de entidad (``EntityKind``) de los que se exporta el espesor (su valor, como lo guarda ``des_epr_``)."""
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


_COMPOSED_LABELS: Mapping[str, str] = MappingProxyType({
    declared.STOCKPILE_GROUND_GRID: "Terreno sin acopios (compuesto con la superficie de la que parte la detección)"})
"""El ``TIPO`` de lo que se exporta **compuesto** (:func:`compose_ground`): no es lo guardado (solo las huellas)."""
_THICKNESS_LABEL = "Espesor de la entidad (diferencia de sus dos superficies)"


def metadata_items(family: str, name: str, version_code: str, part: str = "") -> dict[str, str]:
    """Los metadatos de texto del GeoTIFF (``GDAL_METADATA``) de la rejilla ``family`` de la
    operación ``name`` en la versión ``version_code``: ``UNIDAD`` (:data:`UNIT`), ``TIPO`` (qué
    es, en español: «Envolvente», «Superficie de diseño», «Cota real de las bermas», «Superficie
    final»…), ``DATO`` (su nombre en el proyecto, en ASCII) y ``VERSION``. Una rejilla de códigos
    (:data:`LEGENDS`: la clasificación o el recinto de la 014; RF-014-32) declara ``UNIDAD``
    :data:`CODE_UNIT` y, detrás, su leyenda: ``CODIGO_<n>`` con el nombre de la clase de cada
    código. Sin «&» (GDAL 3.13 lo lee mal): el nombre de la operación no va tal cual, sino en el
    del dato. De la 016 (T34): el terreno sin acopios dice que va **compuesto** y el espesor que se resta de dos
    superficies (``part`` :data:`PART_THICKNESS`), qué es. ``ValueError`` si la familia no es una rejilla del diseño, la
    parte no es una de :data:`PARTS` o la versión es un texto vacío."""
    found = _family(family)
    if part not in PARTS:
        raise ValueError(f"la parte de una rejilla es una de {PARTS}, no {part!r}")
    if not isinstance(version_code, str) or not version_code.strip():
        raise ValueError(f"la versión de los metadatos es un texto no vacío, no {version_code!r}")
    legend = LEGENDS.get(family, ())
    label = _THICKNESS_LABEL if part == PART_THICKNESS else _COMPOSED_LABELS.get(family, found.label)
    items = {"UNIDAD": CODE_UNIT if legend else UNIT, "TIPO": label,
             "DATO": declared.dataset_name(family, name), "VERSION": version_code}
    items.update((LEGEND_KEY.format(code=code), label) for code, label in legend)
    return items


def _version(project: ExportProject, version: object) -> Version | None:
    """La versión ``version`` (uid o código) o, **vacía**, ``None``: el proyecto (la rejilla de una detección sobre una
    superficie del proyecto, D-15; solo la admite ``export_grid_steps`` con una familia de :data:`SUPPORTED_GRIDS`)."""
    if not isinstance(version, str):
        raise TypeError(f"la versión se indica por su uid o su código, no {version!r}")
    if not version:
        return None
    with project.read() as conn:
        found = versions_read.version(conn, version)
    if found is None:
        raise VersionError("core.version_unknown", field="versión", value=version,
                           version=version)
    return found


def _registered_file(project: ExportProject, family: str, name: str, found: Version | None) -> Path:
    """El fichero registrado de la rejilla ``family`` de ``name`` en la versión ``found`` (o, sin ella, en el proyecto)."""
    dataset = declared.dataset_name(family, name)
    with project.read() as conn:
        record = dataset_registry.get(conn, dataset, version_uid="" if found is None else found.uid)
    if record is None or record.name != dataset:
        raise DesignError("des.export_unknown", obj=name, field=_FIELD_GRID, value=name,
                          version=PROJECT_VERSION if found is None else found.code, dataset=dataset)
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
    uid y su código). De la 016 (T34), ``part``: ``""`` (su rejilla) o :data:`PART_THICKNESS` (el espesor de una retirada o
    un contrafuerte, que se resta de sus dos superficies; el de un cuerpo es su propio dato). Una rejilla del proyecto (la
    de una detección de acopios sobre una superficie del proyecto) tiene ``version_uid`` y ``version_code`` vacíos."""

    record: DatasetRecord
    family: str
    name: str
    version_uid: str
    version_code: str
    part: str = ""


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


def _thickness_of(conn: sqlite3.Connection, record: DatasetRecord | None) -> DatasetRecord | None:
    """El dato del que sale el **espesor** de la entidad de ``record`` (T34): su tabla (``des_epr_<nombre>``, la que enseña la vista),
    su superficie (``des_psf_<nombre>``) o su espesor guardado (``des_bdt_<nombre>``). De un cuerpo, el espesor guardado
    (``des_bdt_``); de una retirada o un contrafuerte, su superficie (``des_psf_``), de la que se resta la de partida al exportar;
    ``None`` si ``record`` no es de ninguna de esas entidades (una plataforma no tiene espesor) o su versión no tiene el dato."""
    if record is None or record.module != declared.MODULE:
        return None
    owner = versions_read.dataset_versions(conn, [record.uid]).get(record.uid, "")
    if not owner:
        return None
    families = {code: declared.FAMILIES_BY_CODE[code].prefix
                for code in (declared.ENTITY_TABLE, declared.ENTITY_SURFACE_GRID, declared.BODY_THICKNESS_GRID)}
    suffix = next((record.name[len(prefix):] for prefix in families.values() if record.name.startswith(prefix)), None)
    if suffix is None:
        return None
    if record.name.startswith(families[declared.BODY_THICKNESS_GRID]):
        return record
    table = dataset_registry.get(conn, families[declared.ENTITY_TABLE] + suffix, version_uid=owner)
    found = None if table is None else conn.execute(f'SELECT kind FROM "{table.locator}"').fetchone()
    kind = None if found is None else str(found[0])
    if kind == _BODY:
        return dataset_registry.get(conn, families[declared.BODY_THICKNESS_GRID] + suffix, version_uid=owner)
    if kind in (_REMOVAL, _BUTTRESS):
        return dataset_registry.get(conn, families[declared.ENTITY_SURFACE_GRID] + suffix, version_uid=owner)
    return None


def stored_grid(project: ExportProject, ref: str, *, version: str = "", part: str = "") -> StoredGrid:
    """La rejilla del diseño ``ref`` —el uid de su dato o su nombre en la versión ``version`` (su
    uid)— con lo que pide :func:`export_grid_steps`: su familia, el nombre de su operación y su
    versión. ``DesignError`` ``des.export_not_grid`` si no es una rejilla **viva** del diseño
    de una versión, de :data:`GRIDS`: una envolvente, una superficie de diseño o una rejilla de
    cotas de berma de la 013; una superficie, una envolvente, la clasificación o el recinto de la
    014; la superficie de una entidad de la 015: una tabla, un dato de otro módulo, uno que no existe, uno
    sustituido o descartado, o uno por su nombre sin la versión que lo tiene. **La tabla de una entidad**
    (``des_epr_<nombre>``: la que enseña la vista, T30) da la **superficie** de esa entidad
    (``des_psf_<nombre>``) de su versión. De la 016 (T34): también la base, el espesor y el terreno sin acopios de una
    detección (:data:`SUPPORTED_GRIDS`, por el nombre o el uid de su dato) y, **con** ``part`` :data:`PART_THICKNESS`,
    **el espesor** de la entidad cuya tabla se da: el de un cuerpo (``des_bdt_``) o, de una retirada o un contrafuerte, su
    superficie (``des_psf_``) con ``part`` en el resultado (el espesor se resta al exportar); una plataforma no tiene
    (``des.export_not_grid``). Una rejilla de una detección **del proyecto** (D-15) no es de ninguna versión: sin versión
    en el resultado. ``TypeError`` si ``ref`` o ``version`` no son textos (o ``ref``, vacío); ``ValueError`` si ``part`` no es
    una de :data:`PARTS`. No escribe nada."""
    if not isinstance(ref, str) or not ref:
        raise TypeError(f"una rejilla del diseño se indica por el uid o el nombre de su dato, "
                        f"no {ref!r}")
    if not isinstance(version, str):
        raise TypeError(f"la versión se indica por su uid ('' sin ninguna), no {version!r}")
    if part not in PARTS:
        raise ValueError(f"la parte de una rejilla es una de {PARTS}, no {part!r}")
    with project.read() as conn:
        record = dataset_registry.get(conn, ref, version_uid=version)
        if part == PART_THICKNESS:
            record = _thickness_of(conn, record)
            if record is not None and record.name.startswith(declared.FAMILIES_BY_CODE[declared.BODY_THICKNESS_GRID].prefix):
                part = ""  # el espesor de un cuerpo es un dato guardado: se exporta tal cual
        else:
            record = _surface_of_entity(conn, record) or record
        family = _grid_family(record)
        owner = ("" if record is None
                 else versions_read.dataset_versions(conn, [record.uid]).get(record.uid, ""))
        found = versions_read.version(conn, owner) if owner else None
    of_project = family in SUPPORTED_GRIDS and not owner  # el de una detección del proyecto (D-15)
    if record is None or not record.live or family is None or (found is None and not of_project):
        raise DesignError("des.export_not_grid", obj=ref, field=_FIELD_GRID, value=ref)
    return StoredGrid(record, family, record.name[len(declared.FAMILIES_BY_CODE[family].prefix):],
                      owner, "" if found is None else found.code, part)


# --- El destino --------------------------------------------------------------------------------


def check_target(path: str | Path, *, project: ExportProject, read_only: ReadOnlyDirs,
                 overwrite: bool, suffixes: tuple[str, ...] = SUFFIXES, label: str = "GeoTIFF") -> Path:
    """El destino ``path`` del GeoTIFF (o, con ``suffixes`` y ``label``, de otro entregable: el CSV de la rasante, :data:`CSV_SUFFIXES`; T27), comprobado sin escribir nada (véase el módulo):
    ``GisError`` ``gis.export_extension_invalid``, ``gis.export_inside_project`` o
    ``gis.export_target_exists``; ``DesignError`` ``des.export_read_only_project``;
    ``ProvenanceError`` ``core.write_target_*`` (RF-008-15); ``core.path_too_long``."""
    if not isinstance(overwrite, bool):
        raise TypeError(f"«overwrite» es verdadero o falso, no {overwrite!r}")
    target = Path(path)
    name = target.name
    if target.suffix.lower() not in suffixes:
        raise GisError("gis.export_extension_invalid", obj=name, field=_FIELD_EXTENSION,
                       value=target.suffix or "—", file=name, format=label,
                       expected="/".join(suffixes))
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


_WRITER_INPUT = (
    "SELECT d.name, d.locator, d.status FROM gb_operation_io AS w "
    "JOIN gb_operation AS o ON o.uid = w.operation_uid AND o.status = 'done' AND o.superseded_by IS NULL "
    "JOIN gb_operation_io AS io ON io.operation_uid = w.operation_uid AND io.direction = 'in' AND io.item_kind = 'dataset' "
    "AND io.role = ? JOIN gb_dataset AS d ON d.uid = io.item_uid "
    "WHERE w.item_uid = ? AND w.direction = 'out' AND w.item_kind = 'dataset' ORDER BY io.fid")
"""La superficie de la que parte la operación **vigente** que escribió el dato (su entrada con el papel ``surface``; un dato
recalculado es salida de cada operación que lo escribió)."""


def _start_surface(project: ExportProject, record: DatasetRecord, name: str, version_code: str) -> Path:
    """El fichero de la superficie de la que parte la operación que escribió ``record`` (su entrada ``surface``: la de
    partida de una retirada o un contrafuerte, la sobre la que se detectó una detección): lo que se compone o se resta al
    exportar (T34). ``DesignError`` ``des.export_unknown`` si la operación no tiene una sola, ``gis.dataset_file_missing`` si
    falta su fichero."""
    with project.read() as conn:
        found = conn.execute(_WRITER_INPUT, (declared.SURFACE_ROLE, record.uid)).fetchall()
    if len(found) != 1:
        raise DesignError("des.export_unknown", obj=name, field=_FIELD_GRID, value=name, version=version_code,
                          dataset=f"la superficie de la que parte «{record.name}»")
    ((surface, locator, _status),) = found
    path = Path(project.root).joinpath(*str(locator).split("/"))
    if not path.is_file():
        raise GisError("gis.dataset_file_missing", obj=str(surface), field="fichero", value=path.name, file=path.name,
                       name=str(surface))
    return path


def compose_ground(ground: np.ndarray, surface: np.ndarray) -> np.ndarray:
    """El **terreno sin acopios entero** (spec 016, T34; RF-016-09, RF-016-24; plan 016 §5.7 P-5): ``ground`` (``des_stg_``)
    solo tiene dato en las huellas —el menor de la superficie detectada y de la base de cada acopio— y ``surface`` es la
    superficie de la que parte la detección; el resultado es ``ground`` donde lo hay y ``surface`` en el resto, en las
    mismas celdas (nuevo; ``ValueError`` si no tienen la misma forma). Lo que no tiene dato en ninguno de los dos, sin dato."""
    if ground.shape != surface.shape:
        raise ValueError(f"el terreno de las huellas y la superficie de la que parte la detección tienen la misma rejilla: "
                         f"{ground.shape} frente a {surface.shape}")
    return np.where(np.isfinite(ground), ground, surface)


def thickness_between(top: np.ndarray, bottom: np.ndarray) -> np.ndarray:
    """El **espesor** entre dos superficies (spec 016, T34; RF-016-01, RF-016-24): ``top − bottom`` en cada celda en que las
    dos tienen dato, **nunca negativo** (una celda en que la de arriba queda por debajo es un espesor 0, no uno negativo: el
    error 26) y sin dato donde falta alguna. ``ValueError`` si no tienen la misma forma."""
    if top.shape != bottom.shape:
        raise ValueError(f"las dos superficies del espesor tienen la misma rejilla: {top.shape} frente a {bottom.shape}")
    with np.errstate(invalid="ignore"):
        return np.where(np.isfinite(top) & np.isfinite(bottom), np.maximum(top - bottom, 0.0), np.nan)


def _recipe(project: ExportProject, family: str, name: str, found: Version | None, source: Path, part: str
            ) -> Callable[[np.ndarray], np.ndarray] | None:
    """Lo que se hace a lo registrado antes de exportarlo, si algo: el terreno sin acopios se **compone** con la superficie
    de la que parte la detección y el espesor de una retirada o un contrafuerte se **resta** de las dos superficies de su
    entidad. ``None``: se exporta tal cual."""
    code = PROJECT_VERSION if found is None else found.code
    uid = "" if found is None else found.uid
    if family == declared.STOCKPILE_GROUND_GRID:
        with project.read() as conn:
            record = dataset_registry.get(conn, declared.dataset_name(family, name), version_uid=uid)
        assert record is not None
        other = read_geotiff(_start_surface(project, record, name, code), max_cells=sys.maxsize).values
        return lambda ground: compose_ground(ground, other)
    if part == PART_THICKNESS and family == declared.ENTITY_SURFACE_GRID:
        table = declared.dataset_name(declared.ENTITY_TABLE, name)
        with project.read() as conn:
            record = dataset_registry.get(conn, declared.dataset_name(family, name), version_uid=uid)
            owner = dataset_registry.get(conn, table, version_uid=uid)
            kind = None if owner is None else conn.execute(f'SELECT kind FROM "{owner.locator}"').fetchone()
        assert record is not None
        start = read_geotiff(_start_surface(project, record, name, code), max_cells=sys.maxsize).values
        if kind is not None and str(kind[0]) == _REMOVAL:  # lo retirado: la de partida menos la que deja
            return lambda top: thickness_between(start, top)
        return lambda top: thickness_between(top, start)  # lo que sube un contrafuerte
    return None


def export_grid_steps(project: ExportProject, family: str, name: str, path: str | Path, *,
                      version: str, read_only: ReadOnlyDirs,
                      overwrite: bool = False, part: str = "") -> Generator[float, None, Path]:
    """La rejilla ``family`` (una de :data:`GRIDS`) de la operación ``name`` en la versión
    ``version`` (uid o código) como GeoTIFF entregable en ``path``, por pasos (véase el módulo): al
    llamar, sin escribir nada, la versión (``VersionError`` ``core.version_unknown``), que la
    rejilla esté registrada en ella (``DesignError`` ``des.export_unknown``) y el destino
    (:func:`check_target`); el primer paso la lee y cada uno de los siguientes escribe una tesela
    (``gis.geotiff.writer.write_steps``: su avance, de 0 a 1); el último la pone en su sitio y
    devuelve ``path`` (``StopIteration.value``). Cerrar los pasos antes no deja nada. ``ValueError``
    si ``family`` no es una rejilla del diseño; ``TypeError`` si ``name``, ``version`` u
    ``overwrite`` no son del tipo que toca. De la 016 (T34): ``version`` **vacía** es el proyecto (solo con una familia de
    :data:`SUPPORTED_GRIDS`: la de una detección sobre una superficie del proyecto); el terreno sin acopios se exporta
    **compuesto** con la superficie de la que parte la detección (:func:`compose_ground`) y, con ``part``
    :data:`PART_THICKNESS` y la superficie de una retirada o un contrafuerte, su **espesor** (:func:`thickness_between`;
    ``name`` es el de la entidad). Faltar la superficie de la que parte (``des.export_unknown``, ``gis.dataset_file_missing``)
    se rechaza al llamar, sin escribir nada."""
    _family(family)
    if part not in PARTS:
        raise ValueError(f"la parte de una rejilla es una de {PARTS}, no {part!r}")
    shown = _name(name)
    found = _version(project, version)
    if found is None and family not in SUPPORTED_GRIDS:
        raise ValueError(f"solo las rejillas de una detección de acopios son del proyecto, no «{family}»")
    source = _registered_file(project, family, shown, found)
    recipe = _recipe(project, family, shown, found, source, part)
    target = check_target(path, project=project, read_only=read_only, overwrite=overwrite)
    metadata = metadata_items(family, shown, PROJECT_VERSION if found is None else found.code,
                              part if recipe is not None and part else "")
    return _export_steps(project, source, target, metadata, recipe)


def _export_steps(project: ExportProject, source: Path, target: Path, metadata: dict[str, str],
                  recipe: Callable[[np.ndarray], np.ndarray] | None = None) -> Generator[float, None, Path]:
    registered = read_geotiff(source, max_cells=sys.maxsize)
    crs, vertical = project_references(project)
    values = registered.values if recipe is None else recipe(registered.values)
    raster = Raster(registered.grid, values, registered.declared_crs or crs,
                    registered.declared_vertical or vertical)
    yield 0.0
    return (yield from write_steps(raster, target, profile="deliverable", metadata=metadata))


def export_grid(project: ExportProject, family: str, name: str, path: str | Path, *,
                version: str, read_only: ReadOnlyDirs, overwrite: bool = False, part: str = "") -> Path:
    """:func:`export_grid_steps` de una vez: devuelve ``path``."""
    steps = export_grid_steps(project, family, name, path, version=version, read_only=read_only,
                              overwrite=overwrite, part=part)
    with closing(steps):
        while True:
            try:
                next(steps)
            except StopIteration as stop:
                return stop.value  # type: ignore[no-any-return]


# --- La rasante de una pista a CSV (spec 017, T27; RF-017-27; decisión T27-a) -------------------


CSV_SUFFIXES: tuple[str, ...] = (".csv",)
"""La extensión del CSV de la rasante."""
CSV_COLUMNS: tuple[str, ...] = ("Abscisa (m)", "X (m)", "Y (m)", "Cota del terreno (m)", "Cota de la rasante (m)", "Pendiente (%)")
"""Los títulos del CSV de la rasante, con su unidad, en su orden (RF-017-27: abscisa, x, y, cota del terreno, cota de la rasante y pendiente, en m y en %). La primera celda no es «ID»: Excel tomaría el
fichero por SYLK."""
_CSV_ENCODING = "utf-8-sig"
_CSV_SEPARATOR = ";"
_CSV_LINE_END = "\r\n"
_CSV_DECIMAL = ","
_ROAD_AXIS_COLUMNS = "station_m, x, y, terrain_m, level_m, gradient_pct"
_FIELD_ROAD = "pista"


def _csv_number(value: float) -> str:
    """Un número con coma decimal: el decimal más corto que vuelve al mismo float64, sin exponente ni separador de miles; −0, «0» (como el CSV de la cubicación)."""
    text = np.format_float_positional(value, unique=True, trim="-")
    return ("0" if text == "-0" else text).replace(".", _CSV_DECIMAL)


def road_csv_bytes(stations: object) -> bytes:
    """El CSV de la rasante de ``stations`` —una tabla ``(n, 6)`` con una fila por estación: abscisa, x, y, cota del terreno, cota de la rasante y pendiente— tal como lo escribe
    :func:`export_road_csv`: BOM de UTF-8, «;» y CRLF, con los títulos de :data:`CSV_COLUMNS` y cada número con coma decimal y **sin pérdida** (el decimal más corto que vuelve al mismo float64).
    ``ValueError`` (un error del programa) si no son al menos una estación de seis columnas finitas."""
    table = np.asarray(stations, dtype=np.float64)
    if table.ndim != 2 or table.shape[1] != len(CSV_COLUMNS) or table.shape[0] < 1 or not bool(np.isfinite(table).all()):
        raise ValueError(f"la rasante de una pista son estaciones con {len(CSV_COLUMNS)} columnas finitas ({', '.join(CSV_COLUMNS)}), no una tabla {table.shape}")
    stream = io.StringIO(newline="")
    writer_ = csv.writer(stream, delimiter=_CSV_SEPARATOR, lineterminator=_CSV_LINE_END)
    writer_.writerow(CSV_COLUMNS)
    writer_.writerows([_csv_number(float(value)) for value in row] for row in table)
    return stream.getvalue().encode(_CSV_ENCODING)


@dataclass(frozen=True, slots=True)
class StoredRoad:
    """El eje por estaciones de una pista calculada que se puede exportar (:func:`stored_road`): su dato (``des_rdx_<nombre>``), el nombre de su operación tal como está en el nombre de su dato (``pista_a_p1``)
    y su versión (su uid y su código)."""

    record: DatasetRecord
    name: str
    version_uid: str
    version_code: str


def stored_road(project: ExportProject, name: str, *, version: str) -> StoredRoad:
    """El eje por estaciones de la pista ``name`` (su nombre de operación) en la versión ``version`` (uid o código): ``des_rdx_<nombre>`` **vivo y vigente** de esa versión. ``VersionError``
    ``core.version_unknown`` si no existe; ``DesignError`` ``des.export_road_unknown`` si la versión no tiene esa pista calculada (o su dato está bloqueado, sustituido o descartado). No escribe nada.
    ``TypeError`` si ``name`` o ``version`` no son textos."""
    shown = _name(name)
    found = _version(project, version)
    if found is None:
        raise ValueError("la rasante de una pista es de una versión: la versión no puede ser vacía")
    dataset = declared.dataset_name(declared.ROAD_AXIS_TABLE, shown)
    with project.read() as conn:
        record = dataset_registry.get(conn, dataset, version_uid=found.uid)
    if record is None or not record.live or record.status.value != "current":
        raise DesignError("des.export_road_unknown", obj=shown, field=_FIELD_ROAD, value=shown, version=found.code, dataset=dataset)
    return StoredRoad(record, record.name[len(declared.FAMILIES_BY_CODE[declared.ROAD_AXIS_TABLE].prefix):], found.uid, found.code)


ROAD_EXPORTS: tuple[str, ...] = ("surface", "gradient", "reach")
"""Lo que se exporta de una pista o una accesibilidad (:func:`stored_road_export`; T33; RF-017-27): la **superficie** de una pista (GeoTIFF), su **rasante** (CSV, :func:`export_road_csv`) y lo que **alcanza**
una accesibilidad (GeoTIFF de códigos)."""


def stored_road_export(project: ExportProject, what: str, ref: str, *, version: str) -> StoredGrid | StoredRoad:
    """Lo que se exporta de la pista o de la accesibilidad ``ref`` (su código o su nombre) de la versión ``version`` (uid o código; spec 017, T33; RF-017-27): con ``what`` ``"surface"``, la **superficie** de la pista
    (``des_psf_``, un :class:`StoredGrid`); con ``"gradient"``, **su rasante** (``des_rdx_``, un :class:`StoredRoad`: :func:`export_road_csv`) y con ``"reach"``, **lo que alcanza una accesibilidad**
    (``des_acc_``, un :class:`StoredGrid` de la familia de lo alcanzable): por el código o el nombre de la accesibilidad o, de no serlo, el de su dato (``ref`` el uid o el nombre de ``des_acc_``, como lo da el objeto
    de la vista). ``DesignError`` ``des.export_road_unknown`` si la versión no tiene esa pista **calculada** y viva (``surface`` y ``gradient``) y ``des.export_not_grid`` si ``ref`` no es lo alcanzable de una accesibilidad
    viva (``reach``); ``VersionError`` ``core.version_unknown``; ``ValueError`` si ``what`` no es de :data:`ROAD_EXPORTS` o la versión es vacía; ``TypeError`` si ``ref`` o ``version`` no son textos. **No escribe nada.**"""
    if what not in ROAD_EXPORTS:
        raise ValueError(f"lo que se exporta de una pista es una de {ROAD_EXPORTS}, no {what!r}")
    if not isinstance(ref, str) or not ref.strip():
        raise TypeError(f"una pista o una accesibilidad se indica por su código o su nombre, no {ref!r}")
    found = _version(project, version)
    if found is None:
        raise ValueError("lo que se exporta de una pista es de una versión: la versión no puede ser vacía")
    entry = entities.registry(project, found.uid).get(ref.strip())
    if what == "reach":
        if entry is not None and entry.record.kind == entities.EntityKind.ACCESS:
            grid = stored_grid(project, declared.dataset_name(declared.ACCESS_GRID, entry.record.name), version=found.uid)
        else:
            grid = stored_grid(project, ref.strip(), version=found.uid)
        if grid.family != declared.ACCESS_GRID:
            raise DesignError("des.export_not_grid", obj=ref, field=_FIELD_GRID, value=ref)
        return grid
    if entry is None or entry.record.kind != entities.EntityKind.ROAD or entry.operation_uid is None:
        raise DesignError("des.export_road_unknown", obj=ref, field=_FIELD_ROAD, value=ref, version=found.code,
                          dataset=declared.dataset_name(declared.ROAD_AXIS_TABLE, entry.record.name if entry is not None else ref))
    if what == "surface":
        return stored_grid(project, declared.dataset_name(declared.ENTITY_SURFACE_GRID, entry.record.name), version=found.uid)
    return stored_road(project, entry.record.name, version=found.uid)


def _discard(temporary: Path) -> None:
    try:
        temporary.unlink(missing_ok=True)
    except OSError:
        pass


def _write_bytes(data: bytes, target: Path) -> None:
    """``data`` en ``target`` por su temporal, ``fsync`` y ``os.replace``: con el destino abierto por otro programa, ``gis.raster_target_locked`` y el anterior intacto; un fallo del disco,
    ``gis.raster_write_failed``; en los dos, sin temporal."""
    name = target.name
    temporary = temporary_path(target)
    try:
        with temporary.open("wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException as error:
        _discard(temporary)
        if isinstance(error, OSError):
            raise write_failed(name, error) from None
        raise
    try:
        os.replace(temporary, target)
    except OSError as error:
        _discard(temporary)
        if isinstance(error, PermissionError):  # Windows: otro programa lo tiene abierto
            raise target_locked(name) from None
        raise write_failed(name, error) from None


def export_road_csv(project: ExportProject, name: str, path: str | Path, *, version: str, read_only: ReadOnlyDirs, overwrite: bool = False) -> Path:
    """La rasante de la pista ``name`` de la versión ``version`` (uid o código) a CSV en ``path`` (RF-017-27; T27-a; véase el módulo): una fila por estación de su eje por estaciones (``des_rdx_``), con la
    abscisa, la x y la y, la cota del terreno, la cota de la rasante y la pendiente del tramo que empieza en ella, **en m y en %**. Al llamar, antes de escribir nada, la versión (``VersionError``), que la
    pista esté calculada en ella (:func:`stored_road`, ``DesignError`` ``des.export_road_unknown``) y el destino (:func:`check_target` con la extensión de un CSV); **no modifica nada del proyecto** (no es una
    operación). Devuelve ``path``. ``gis.dataset_file_missing`` no aplica (es una tabla); una tabla dañada o vacía (sus filas se borraron fuera de Geoblender) es ``des.export_road_unknown``."""
    found = stored_road(project, name, version=version)
    target = check_target(path, project=project, read_only=read_only, overwrite=overwrite, suffixes=CSV_SUFFIXES, label="CSV")
    try:
        with project.read() as conn:
            rows = conn.execute(f'SELECT {_ROAD_AXIS_COLUMNS} FROM "{found.record.locator}" ORDER BY station_m').fetchall()
        data = road_csv_bytes(np.asarray(rows, dtype=np.float64).reshape(-1, len(CSV_COLUMNS)))
    except (sqlite3.Error, ValueError):
        raise DesignError("des.export_road_unknown", obj=name, field=_FIELD_ROAD, value=name, version=found.version_code, dataset=found.record.name) from None
    _write_bytes(data, target)
    return target


# --- Los hallazgos de una corta a CSV (spec 018, T27; RF-018-33, RF-018-26) -------------------------

PIT_FINDING_CSV_COLUMNS: tuple[str, ...] = ("Tipo", "Banco", "Valor", "Límite", "Unidad", "X (m)", "Y (m)", "Detalle")
"""Los títulos de las columnas del CSV de los hallazgos de una corta (``des_pfn_``): el tipo, el banco (vacío si no es de uno), el valor y el límite que no cumple, su unidad, el lugar absoluto y el detalle."""
_PIT_FINDING_SQL = "SELECT kind, bench, value, limit_value, unit, x, y, detail FROM \"{table}\" ORDER BY fid"
_FIELD_PIT = "corta"


@dataclass(frozen=True, slots=True)
class StoredPitFindings:
    """Los hallazgos de una corta calculada que se pueden exportar (:func:`stored_pit_findings`): su dato (``des_pfn_<nombre>``), la familia (``pfn``), el nombre de su operación tal como está en el nombre de su
    dato y su versión (su uid y su código)."""

    record: DatasetRecord
    family: str
    name: str
    version_uid: str
    version_code: str


def stored_pit_findings(project: ExportProject, ref: str, *, version: str) -> StoredPitFindings:
    """Los hallazgos de la corta ``ref`` (su código o su nombre) en la versión ``version`` (uid o código): ``des_pfn_<nombre>`` **vivo y vigente** de esa versión (RF-018-33). ``VersionError``
    ``core.version_unknown`` si la versión no existe; ``DesignError`` ``des.export_pit_unknown`` si la versión no tiene esa corta calculada (o su dato está bloqueado, sustituido o descartado).
    ``TypeError`` si ``ref`` o ``version`` no son textos. No escribe nada."""
    if not isinstance(ref, str) or not ref.strip():
        raise TypeError(f"una corta se indica por su código o su nombre, no {ref!r}")
    found = _version(project, version)
    if found is None:
        raise ValueError("los hallazgos de una corta son de una versión: la versión no puede ser vacía")
    entry = entities.registry(project, found.uid).get(ref.strip())
    shown = entry.record.name if entry is not None and entry.record.kind == entities.EntityKind.PIT and entry.operation_uid is not None else ref.strip()
    dataset = declared.dataset_name(declared.PIT_FINDINGS_TABLE, shown)
    with project.read() as conn:
        record = dataset_registry.get(conn, dataset, version_uid=found.uid)
    if record is None or not record.live or record.status.value != "current":
        raise DesignError("des.export_pit_unknown", obj=ref, field=_FIELD_PIT, value=ref, version=found.code, dataset=dataset)
    return StoredPitFindings(record, declared.PIT_FINDINGS_TABLE, record.name[len(declared.FAMILIES_BY_CODE[declared.PIT_FINDINGS_TABLE].prefix):], found.uid, found.code)


def _csv_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return _csv_number(value)
    return str(value)


def export_pit_findings_csv(project: ExportProject, ref: str, path: str | Path, *, version: str, read_only: ReadOnlyDirs, overwrite: bool = False) -> Path:
    """Los hallazgos de la corta ``ref`` de la versión ``version`` (uid o código) a CSV en ``path`` (RF-018-33, RF-018-26; véase el módulo): una fila por hallazgo, en el orden del cálculo, con el tipo, el
    banco, el valor y el límite, la unidad, el lugar y el detalle; BOM de UTF-8, «;», CRLF y coma decimal **sin pérdida** (como la rasante de una pista, :func:`road_csv_bytes`). Al llamar, antes de escribir
    nada, la versión (``VersionError``), que la corta esté calculada en ella (:func:`stored_pit_findings`, ``DesignError`` ``des.export_pit_unknown``) y el destino (:func:`check_target` con la extensión de
    un CSV); **no modifica nada del proyecto** (no es una operación). Una corta sin hallazgos da el CSV con solo los títulos. Devuelve ``path``."""
    found = stored_pit_findings(project, ref, version=version)
    target = check_target(path, project=project, read_only=read_only, overwrite=overwrite, suffixes=CSV_SUFFIXES, label="CSV")
    try:
        with project.read() as conn:
            rows = conn.execute(_PIT_FINDING_SQL.format(table=found.record.locator)).fetchall()
    except sqlite3.Error:
        raise DesignError("des.export_pit_unknown", obj=ref, field=_FIELD_PIT, value=ref, version=found.version_code, dataset=found.record.name) from None
    stream = io.StringIO(newline="")
    writer_ = csv.writer(stream, delimiter=_CSV_SEPARATOR, lineterminator=_CSV_LINE_END)
    writer_.writerow(PIT_FINDING_CSV_COLUMNS)
    writer_.writerows([_csv_cell(value) for value in row] for row in rows)
    _write_bytes(stream.getvalue().encode(_CSV_ENCODING), target)
    return target

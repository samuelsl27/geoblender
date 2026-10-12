# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que preparan sin Blender las órdenes de un MDT (spec 006, T28; RF-006-04, RF-006-05,
RF-006-06, RF-006-08, RF-006-09, RF-006-26; plan 006 §5.3.5, §5.6.1 y §5.6.4).

Las órdenes ``geoblender.gis_import_dtm`` y ``geoblender.gis_resample_to_grid`` (``bl/ops/
gis.py``) no calculan: validan lo que se teclea, preparan el trabajo de la 004 y presentan el
resultado. Lo que deciden y se puede probar sin Blender está aquí:

- **El lector** de una fuente, por su extensión (:data:`DTM_READERS`: GeoTIFF ``.tif`` y
  ``.tiff``, ESRI ASCII Grid ``.asc``, XYZ en malla ``.xyz``; :func:`dtm_reader`). Otra es
  ``gis.dtm_format_unsupported`` (RF-006-09).
- **Lo que se importa** (:func:`plan_import` → :class:`DtmSource`): sus ficheros (el ``.prj``
  de un ASC, compañero), sus ajustes de lectura (:func:`read_settings`: el sin dato forzado,
  tecleado con coma o punto; el separador y el decimal de un XYZ) y su CRS horizontal y su
  datum vertical, los tecleados o, si no, los que declara el fichero: las claves de un GeoTIFF,
  leídas de su cabecera (que se comprueba entera **antes de empezar**: un GeoTIFF en JPEG, con
  varias bandas o girado se rechaza sin leer ninguna celda, RF-006-09), o el ``.prj`` de un
  ASC si el servicio de CRS lo reconoce (``identify``, :func:`identify_prj`; también con el
  CRS tecleado, que manda: el trabajo recibe lo reconocido, ``DtmSource.prj_crs``, y su
  informe no dice que no se reconoció, T52). Sin uno de los dos, ``gis.crs_undeclared`` o
  ``gis.vertical_undeclared``: nunca se suponen los del proyecto (RF-006-04). Un CRS
  tecleado se escribe con su código EPSG (:func:`parse_crs`).
- **El trabajo** ``gis_read_raster`` de la importación (:func:`job_params`, sin ninguna
  ruta, ARQ-11; :func:`job_paths`, las rutas de la fuente por papel, que van por la línea de
  órdenes); con el GeoOrigin del proyecto si la fuente está en su CRS horizontal
  (:func:`scene_origin`), para decir cuántos centros de sus celdas con dato pasan de 8 km
  (RF-002-26; T51).
- **Los parámetros de control** de una orden (D17: los que deciden si se rechaza o se avisa
  sin cambiar ninguna salida, como ``gis.import.max_cells`` y
  ``gis.vertical.ellipsoidal_band_m``): :func:`control_values` los lee del proyecto (la
  primera vez, con su valor por defecto «sin confirmar», RF-008-04) para dejarlos en los
  ajustes de la operación, sin anotarlos como consumidos.
- **Las posiciones** con que se compara un MDT que se importa con uno del proyecto (RF-006-06,
  A16): :func:`vertical_samples`, centros de celdas con dato repartidos por toda la rejilla.

Python puro y numpy (ADR-0004).
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

import numpy as np

from ..core.content.readers import MAIN_ROLE, ContentReader
from ..core.errors import ValidationError
from ..core.georef import CrsCatalog, CrsRef, GeoOrigin, VerticalRef, load_catalog
from ..core.numbers import parse_decimal
from ..core.params.store import ParameterStore
from .asc import read_header as read_asc_header
from .asc import read_prj
from .content import ASC, GEOTIFF, PRJ_ROLE, READER_SETTINGS, XYZ_GRID
from .crs import Declaration
from .geotiff.reader import read_header as read_geotiff_header
from .jobs import crs_json, origin_json, path_name, vertical_json
from .messages import GisError
from .raster import Raster
from .vertical import BAND_KEY, MAX_SAMPLES
from .xyz_grid import check_options

__all__ = [
    "CONTROL_KEYS",
    "DTM_READERS",
    "MAX_CELLS_KEY",
    "MAX_SAMPLES",
    "DtmSource",
    "control_values",
    "dtm_reader",
    "identify_prj",
    "job_params",
    "job_paths",
    "parse_crs",
    "plan_import",
    "read_settings",
    "scene_origin",
    "vertical_samples",
]

DTM_READERS: Mapping[str, ContentReader] = MappingProxyType({
    ".tif": GEOTIFF,
    ".tiff": GEOTIFF,
    ".asc": ASC,
    ".xyz": XYZ_GRID,
})
"""El lector de contenido de un MDT por la extensión de su fichero (en minúsculas)."""
MAX_CELLS_KEY = "gis.import.max_cells"
"""El límite de celdas de una importación (parámetro de control, D17)."""
CONTROL_KEYS: tuple[str, ...] = (MAX_CELLS_KEY, BAND_KEY)
"""Los parámetros de control de una importación de un MDT: el límite de celdas y la banda
del aviso de alturas elipsoidales (D17)."""

_EPSG = re.compile(r"(?:epsg\s*:\s*)?(\d+)", re.IGNORECASE)
_NODATA_OBJ = "Sin dato forzado"
_NODATA_FIELD = "nodata_override"
_XYZ_OBJ = "XYZ en malla"


class _ParameterProject(Protocol):
    """Lo que usa :func:`control_values` de un proyecto (``core.project.Project``)."""

    @property
    def session(self) -> Any: ...

    def read(self) -> Any: ...

    def write_transaction(self) -> Any: ...


@dataclass(frozen=True, slots=True)
class DtmSource:
    """Lo que se importa de un MDT: el nombre lógico de su entrada (``name``), su lector, sus
    ficheros por papel (``main`` y, en un ASC, ``prj``), su CRS horizontal y su datum vertical
    declarados, sus ajustes de lectura (los de ``gis.content.READER_SETTINGS`` de su lector)
    y, en un ASC, el CRS que el servicio de CRS reconoció en su ``.prj`` (``prj_crs``;
    ``None`` sin ``.prj``, sin servicio o sin reconocerlo)."""

    name: str
    reader: ContentReader
    files: Mapping[str, Path]
    crs: CrsRef
    vertical: VerticalRef
    settings: Mapping[str, Any]
    prj_crs: CrsRef | None = None

    @property
    def main(self) -> Path:
        """El fichero principal de la fuente."""
        return self.files[MAIN_ROLE]


def dtm_reader(path: Path | str) -> ContentReader:
    """El lector de contenido del MDT ``path`` por su extensión (:data:`DTM_READERS`, sin
    distinguir mayúsculas); otra es ``GisError`` ``gis.dtm_format_unsupported`` con el fichero
    y la extensión (RF-006-09)."""
    found = Path(path)
    reader = DTM_READERS.get(found.suffix.lower())
    if reader is None:
        raise GisError("gis.dtm_format_unsupported", obj=found.name, field="extensión",
                       value=found.suffix, file=found.name)
    return reader


def parse_crs(text: str, *, catalog: CrsCatalog | None = None) -> CrsRef | None:
    """El CRS horizontal tecleado (``EPSG:25830``, ``epsg: 25830`` o ``25830``) del catálogo;
    vacío, ``None`` (el que declare el fichero). ``GisError`` ``gis.crs_text_invalid`` si no
    es un código EPSG del catálogo (RF-006-04)."""
    shown = str(text).strip()
    if not shown:
        return None
    found = _EPSG.fullmatch(shown)
    if found is not None:
        chosen = load_catalog() if catalog is None else catalog
        for crs in chosen.horizontals():
            if crs.epsg == int(found.group(1)):
                return crs
    raise GisError("gis.crs_text_invalid", obj="CRS horizontal", field="crs", value=text)


def read_settings(
    reader: ContentReader,
    *,
    nodata_override: str = "",
    separator: str | None = None,
    decimal: str = ".",
) -> dict[str, Any]:
    """Los ajustes de lectura de una fuente de ``reader`` (RF-006-08): el sin dato forzado
    ``nodata_override``, tecleado con coma o punto decimal (vacío: el que declara el fichero;
    si no es un número, el ``ValidationError`` de ``core.numbers.parse_decimal``) y, en un XYZ
    en malla, su ``separator`` (``None``: se detecta al leer) y su ``decimal``
    (``ValidationError`` si no se admiten, también la coma como los dos)."""
    settings: dict[str, Any] = {}
    if reader is XYZ_GRID:
        try:
            check_options(separator, decimal)
        except ValueError as error:
            raise ValidationError("gis.xyz_options_invalid", str(error), obj=_XYZ_OBJ,
                                  field="separador", value=separator) from None
        if separator is not None:
            settings["separator"] = separator
        settings["decimal"] = decimal
    if str(nodata_override).strip():
        settings["nodata_override"] = parse_decimal(nodata_override, obj=_NODATA_OBJ,
                                                    field=_NODATA_FIELD)
    return settings


def _source_files(path: Path, reader: ContentReader) -> dict[str, Path]:
    """Los ficheros de la fuente por papel: el principal y, en un ASC, su ``.prj`` si está."""
    files = {MAIN_ROLE: path}
    if reader is ASC:
        for suffix in (".prj", ".PRJ"):
            candidate = path.with_suffix(suffix)
            if candidate.is_file():
                files[PRJ_ROLE] = candidate
                break
    return files


def identify_prj(path: Path | str,
                 identify: Callable[[str], CrsRef | None] | None) -> CrsRef | None:
    """El CRS del catálogo que declara el ``.prj`` del ASC ``path`` si ``identify`` (el
    ``identify_wkt`` del servicio de CRS) lo reconoce; ``None`` sin ``.prj`` (o vacío), sin
    ``identify`` o sin reconocerlo (RF-006-04: se pide declararlo)."""
    if identify is None:
        return None
    wkt = read_prj(path)
    return identify(wkt) if wkt else None


def _declared(path: Path, reader: ContentReader, *,
              identify: Callable[[str], CrsRef | None] | None,
              catalog: CrsCatalog | None) -> tuple[CrsRef | None, VerticalRef | None]:
    """Lo que declara el fichero (comprobada su cabecera antes de empezar, RF-006-09): las
    claves de un GeoTIFF; el ``.prj`` de un ASC, si ``identify`` lo reconoce (también con el
    CRS tecleado: el trabajo debe saber si se reconoció); un XYZ, nada."""
    if reader is GEOTIFF:
        with open(path, "rb") as stream:
            header = read_geotiff_header(stream, path.stat().st_size, path.name,
                                         catalog=catalog)
        return header.crs, header.vertical
    if reader is ASC:
        with open(path, "rb") as stream:
            read_asc_header(stream, path.name)
        return identify_prj(path, identify), None
    return None, None


def plan_import(
    path: Path | str,
    *,
    name: str,
    crs: CrsRef | None = None,
    vertical: VerticalRef | None = None,
    settings: Mapping[str, Any] | None = None,
    identify: Callable[[str], CrsRef | None] | None = None,
    catalog: CrsCatalog | None = None,
) -> DtmSource:
    """Lo que se importa del MDT ``path`` con el nombre lógico ``name`` (vacío: el del
    fichero sin extensión): su lector (:func:`dtm_reader`), sus ficheros, sus ajustes de
    lectura ``settings`` (:func:`read_settings`) y su CRS horizontal y su datum vertical, los
    tecleados (``crs``, ``vertical``) o los que declara el fichero; ``identify`` (el
    ``identify_wkt`` del servicio de CRS) reconoce el ``.prj`` de un ASC (``prj_crs``).

    Sin leer ninguna celda: ``GisError`` de la cabecera de un GeoTIFF o de un ASC que no se
    admite (RF-006-09) y ``gis.crs_undeclared`` o ``gis.vertical_undeclared`` si falta uno de
    los dos (RF-006-04; nunca los del proyecto). ``OSError`` si el fichero no se puede leer;
    ``ValueError`` con un ajuste que no es de lectura de su lector."""
    found = Path(path)
    reader = dtm_reader(found)
    shown = str(name).strip() or found.stem
    chosen = dict(settings or {})
    unknown = sorted(key for key in chosen if key not in READER_SETTINGS[reader.id])
    if unknown:
        raise ValueError(f"ajustes que no son de lectura de «{reader.id}»: {unknown}")
    declared_crs, declared_vertical = _declared(found, reader, identify=identify,
                                                catalog=catalog)
    chosen_crs, chosen_vertical = Declaration(shown, crs or declared_crs,
                                              vertical or declared_vertical).require()
    return DtmSource(shown, reader, MappingProxyType(_source_files(found, reader)), chosen_crs,
                     chosen_vertical, MappingProxyType(chosen),
                     prj_crs=declared_crs if reader is ASC else None)


def job_params(source: DtmSource, *, max_cells: int,
               origin: GeoOrigin | None = None) -> dict[str, Any]:
    """Los parámetros del trabajo ``gis_read_raster`` de la importación de ``source``
    (``gis.jobs``): su lector, su nombre, sus ajustes de lectura, sus CRS declarados, en un
    ASC con su ``.prj`` reconocido, ese CRS (``prj_crs``: el trabajo no tiene el servicio de
    CRS), el límite de celdas (``max_cells``, el del proyecto), el tamaño del fichero
    principal (su estimación) y, con ``origin`` (el GeoOrigin del proyecto, si la fuente está
    en su CRS horizontal), ese origen: el trabajo dice cuántos centros de sus celdas con dato
    pasan de 8 km (RF-002-26; T51). Ninguna ruta (ARQ-11): van aparte, :func:`job_paths`."""
    params = {"reader": source.reader.id, "name": source.name,
              "settings": dict(source.settings), "crs": crs_json(source.crs),
              "vertical": vertical_json(source.vertical)}
    if source.prj_crs is not None:
        params["prj_crs"] = crs_json(source.prj_crs)
    if origin is not None:
        params["origin"] = origin_json(origin)
    return {**params, "max_cells": int(max_cells), "size": source.main.stat().st_size}


def scene_origin(source: DtmSource, crs: CrsRef, origin: GeoOrigin) -> GeoOrigin | None:
    """El GeoOrigin ``origin`` del proyecto (de CRS horizontal ``crs``) para el trabajo de la
    importación de ``source`` si la fuente está en ese CRS (sus centros son los que llegarían
    a la escena, RF-002-26); en otro, ``None``: la vista no la muestra sin transformarla y su
    rejilla del proyecto solo cubre la ventana (T51)."""
    return origin if source.crs.epsg == crs.epsg else None


def job_paths(source: DtmSource) -> dict[str, Path]:
    """Las rutas de la fuente de ``source`` para la línea de órdenes del trabajo
    (``--path source_<papel>``)."""
    return {path_name(role): path for role, path in source.files.items()}


def control_values(project: _ParameterProject, keys: Iterable[str]) -> dict[str, Any]:
    """El valor en el proyecto de los parámetros de control ``keys`` (D17): los que aún no
    tiene se registran antes con su valor por defecto «sin confirmar» (RF-008-04), en una
    transacción; no se anotan como consumidos por ninguna operación. Una lista sale como
    lista (JSON de los ajustes de una operación)."""
    chosen = tuple(keys)
    store = ParameterStore(project)
    with project.read() as conn:
        missing = [key for key in chosen if store.get(key, conn=conn) is None]
    if missing:
        with project.write_transaction() as conn:
            for key in missing:
                store.ensure_default(conn, key,
                                     geoblender_version=project.session.geoblender_version)
    with project.read() as conn:
        values = {key: store.resolve(conn, key).value for key in chosen}
    return {key: list(value) if isinstance(value, tuple) else value
            for key, value in values.items()}


def vertical_samples(raster: Raster, *, limit: int = MAX_SAMPLES) -> np.ndarray:
    """Las posiciones con que se compara ``raster`` con un MDT del proyecto (RF-006-06, A16):
    ``(n, 3)`` en float64, ABSOLUTAS en su CRS y su referencia vertical, con los centros de
    sus celdas con dato (los de ``Grid.centers``, bit a bit) y su cota. Todas si caben en
    ``limit``; si no, las de una malla de una de cada ``k`` filas y columnas, la menor ``k``
    con la que caben, repartidas por toda la rejilla."""
    if limit < 1:
        raise ValueError(f"el número de posiciones es al menos 1, no {limit}")
    values = raster.values
    valid = np.isfinite(values)
    step = max(1, math.isqrt(int(np.count_nonzero(valid)) // limit))
    while int(np.count_nonzero(valid[::step, ::step])) > limit:
        step += 1
    grid = raster.grid
    rows = np.arange(0, grid.nrows, step, dtype=np.float64)
    cols = np.arange(0, grid.ncols, step, dtype=np.float64)
    x = grid.west + (cols + 0.5) * grid.dx
    y = grid.north - (rows + 0.5) * grid.dy
    xx, yy = np.meshgrid(x, y)
    chosen = valid[::step, ::step]
    return np.column_stack([xx[chosen], yy[chosen], values[::step, ::step][chosen]])

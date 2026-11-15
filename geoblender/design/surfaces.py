# SPDX-License-Identifier: GPL-3.0-or-later
"""Las superficies de un cálculo (spec 013; RF-013-01, RF-013-16; plan 013 §5.1 y §5.3.1).

Una envolvente o un escalonado parte de una superficie (o de una rejilla de cotas) del proyecto o
de la versión activa. Se lee **tal como está en su fichero** (ninguna se remuestrea ni se
interpola: RF-013-01, como RF-011-02) y se compara con la rejilla del proyecto antes de calcular
nada (RF-013-16):

- :class:`ProjectFrame` y :func:`project_frame`: la rejilla del proyecto (la de su ventana y su
  paso, ``gis.grid.project_grid``) con su CRS y su datum vertical; la referencia con la que se
  compara. Cualquier cosa con ``grid``, ``crs`` y ``vertical`` (:class:`Frame`; también un
  ``gis.Raster``) sirve de superficie o de referencia.
- :func:`check_grid`: la primera diferencia de rejilla, CRS o datum vertical
  (``gis.grid.geometry_mismatch``, la de la cubicación de la 011) se rechaza con
  ``des.surface_mismatch`` nombrando la superficie, el campo y su valor, y la orden de la 006 que
  lo resuelve («Rejilla de proyecto desde un MDT…», RF-006-11).
- :func:`find_surface`: el dato de la superficie por su nombre: el de la versión activa o, si no
  lo tiene, el del proyecto; el de otra versión es ``des.surface_other_version`` y un TIN,
  ``des.surface_is_tin`` con la orden que lo lleva a rejilla («MDT ⇄ TIN…», RF-006-17).
- :func:`read_surface`: lee la superficie (:class:`~geoblender.gis.raster.Raster`, float64, NaN =
  sin dato). Con ``expect`` compara antes **la cabecera** del fichero con esa referencia y rechaza
  sin leer una sola celda.
- :func:`read_surface_window` y :func:`read_surface_steps` (spec 015, T37; RNF-015-03): lo mismo
  **solo en una ventana** de la rejilla (:class:`SurfaceWindow`: decodifica solo las teselas que la
  tocan) y **por pasos** (la rejilla entera, por bandas de filas, una unidad cada una): una plataforma
  prepara su cálculo con la ventana que va a tocar y lee la rejilla entera, que solo hace falta para
  escribir su superficie, dentro del cálculo y sin pasarse del hilo de Blender. Las mismas celdas, bit a
  bit, que ``read_surface(...).values``, con la misma comparación de la cabecera.

Nada se escribe en el proyecto. Python puro (nivel 8).
"""

from __future__ import annotations

import sqlite3
import sys
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from ..core.datasets import registry as dataset_registry
from ..core.datasets.model import LIVE_STATUSES, DatasetRecord
from ..core.georef import CrsCatalog, CrsRef, VerticalRef
from ..core.versions import read as versions_read
from ..gis.geotiff.reader import GeoTiffHeader, read_geotiff, read_header, read_rows, read_window
from ..gis.grid import Grid, geometry_mismatch, project_grid
from ..gis.messages import GisError
from ..gis.ports import Cancelled, Progress
from ..gis.provenance import FAMILIES_BY_CODE, TIN
from ..gis.provenance import MODULE as GIS_MODULE
from ..gis.raster import Raster
from ..gis.store import GRID_FAMILIES, StoreProject, load_raster, project_references
from .messages import DesignError

__all__ = [
    "Frame",
    "ProjectFrame",
    "SurfaceWindow",
    "check_grid",
    "find_surface",
    "project_frame",
    "read_surface",
    "read_surface_steps",
    "read_surface_window",
]

_OBJ = "Superficie"
_FIELD = "superficie"
_NO_VERSION = "—"
_RASTER = "raster"
_GRID_PREFIXES = tuple(FAMILIES_BY_CODE[code].prefix for code in GRID_FAMILIES)
_OWNER = (  # el índice de nombres vivos por versión; las versiones son pocas
    "SELECT v.code FROM gb_dataset AS d JOIN gb_version AS v ON v.uid = d.version_uid "
    "WHERE d.name = ? AND d.version_uid <> '' AND d.status IN ({marks}) "
    "ORDER BY CAST(substr(v.code, 2) AS INTEGER), v.code LIMIT 1"
)


class Frame(Protocol):
    """Lo que se compara de una superficie sin leer sus celdas: su rejilla, su CRS y su datum
    vertical. Lo cumplen :class:`ProjectFrame` y ``gis.raster.Raster``."""

    @property
    def grid(self) -> Grid: ...

    @property
    def crs(self) -> CrsRef: ...

    @property
    def vertical(self) -> VerticalRef: ...


@dataclass(frozen=True, slots=True)
class ProjectFrame:
    """Una rejilla con su CRS y su datum vertical, sin celdas: la del proyecto
    (:func:`project_frame`) o la que declara la cabecera de un fichero."""

    grid: Grid
    crs: CrsRef
    vertical: VerticalRef


def project_frame(project: StoreProject, *, catalog: CrsCatalog | None = None) -> ProjectFrame:
    """La rejilla del proyecto —la de su ventana de trabajo y su paso (RF-006-01)— con su CRS y su
    referencia vertical (``gis.store.project_references``): contra ella se comparan las
    superficies y las semillas (RF-013-16). ``ValueError`` con un proyecto abierto solo con su
    cabecera."""
    crs, vertical = project_references(project, catalog=catalog)
    record = project.record
    assert record is not None  # project_references ya lo comprobó
    return ProjectFrame(project_grid(record.window, float(record.grid_step_m)), crs, vertical)


def check_grid(surface: Frame, reference: Frame, *, role: str, name: str) -> None:
    """RF-013-16: ``surface`` (``name``, su nombre) ha de estar en la misma rejilla (bit a bit:
    oeste, norte, pasos, columnas y filas), el mismo CRS y el mismo datum vertical que
    ``reference`` (la del proyecto o la de las máscaras). Si no, ``DesignError``
    ``des.surface_mismatch`` con el objeto («name» y su ``role``, ya en el idioma de quien lo
    llama: «superficie de partida», «semillas»), el campo (``west``, ``north``, ``dx``, ``dy``,
    ``ncols``, ``nrows``, ``crs`` o ``vertical``), el valor de la superficie y la orden de la 006
    que lo resuelve. Solo se informa de la **primera** diferencia (la de
    ``gis.grid.geometry_mismatch``); no lee celdas ni modifica nada."""
    found = geometry_mismatch(reference.grid, surface.grid, reference.crs, surface.crs,
                              reference.vertical, surface.vertical)
    if found is None:
        return
    field, value, detail = found
    raise DesignError("des.surface_mismatch", obj=f"«{name}» ({role})", field=field,
                      value=value, surface=name, role=role, detail=detail)


# --- Encontrar la superficie -------------------------------------------------------------------


def _code(conn: sqlite3.Connection, version_uid: str) -> str:
    found = versions_read.version(conn, version_uid) if version_uid else None
    return _NO_VERSION if found is None else found.code


def _other_version(conn: sqlite3.Connection, name: str, owner: str,
                   version_uid: str) -> DesignError:
    return DesignError("des.surface_other_version", obj=_OBJ, field=_FIELD, value=name,
                       surface=name, version=owner, active=_code(conn, version_uid))


def find_surface(project: StoreProject, name: str, *, version_uid: str = "") -> DatasetRecord:
    """El dato de la superficie ``name`` (su nombre o su uid) para la versión activa
    ``version_uid`` (``''``: sin versión, solo lo del proyecto): el de la versión o, si no tiene
    uno así, el del proyecto. Uno de otra versión es ``des.surface_other_version`` (con la versión
    que lo tiene y la activa); uno que no hay, ``gis.dataset_unknown`` (``GisError``); un TIN,
    ``des.surface_is_tin`` con la orden que lo lleva a rejilla; algo que no es una rejilla, un
    error del programa (``ValueError``: las listas de las órdenes no lo ofrecen). Solo lee."""
    with project.read() as conn:
        record = dataset_registry.get(conn, name, version_uid=version_uid)
        if record is None and version_uid:
            record = dataset_registry.get(conn, name)
        if record is not None and not record.live:
            record = None
        has_versions = versions_read.has_versions(conn)
        if record is None:
            marks = ", ".join("?" for _ in LIVE_STATUSES)
            row = (conn.execute(_OWNER.format(marks=marks),
                                (name, *(str(status) for status in LIVE_STATUSES))).fetchone()
                   if has_versions else None)
            if row is not None:
                raise _other_version(conn, name, str(row[0]), version_uid)
            raise GisError("gis.dataset_unknown", obj=_OBJ, field=_FIELD, value=name)
        if has_versions:
            owner = versions_read.dataset_versions(conn, [record.uid]).get(record.uid, "")
            if owner and owner != version_uid:
                raise _other_version(conn, record.name, _code(conn, owner), version_uid)
    if record.module == GIS_MODULE and record.name.startswith(FAMILIES_BY_CODE[TIN].prefix):
        raise DesignError("des.surface_is_tin", obj=_OBJ, field=_FIELD, value=record.name,
                          surface=record.name)
    if record.kind != _RASTER:
        raise ValueError(f"«{record.name}» ({record.kind}) no es una rejilla: no es una "
                         "superficie")
    return record


# --- Leerla ------------------------------------------------------------------------------------


def _path(project: StoreProject, record: DatasetRecord) -> Path:
    path = Path(project.root, *record.locator.split("/"))
    if not path.is_file():
        raise GisError("gis.dataset_file_missing", obj=f"{_OBJ} «{record.name}»",
                       field="ubicación", value=record.locator, file=path.name, name=record.name)
    return path


def _header(project: StoreProject, path: Path, catalog: CrsCatalog | None) -> ProjectFrame:
    """Lo que declara la cabecera del fichero (la rejilla y, si no los declara, el CRS y el datum
    del proyecto), sin leer celdas."""
    crs, vertical = project_references(project, catalog=catalog)
    with path.open("rb") as stream:
        header = read_header(stream, path.stat().st_size, path.name, catalog=catalog)
    return ProjectFrame(header.grid, header.crs or crs, header.vertical or vertical)


def read_surface(
    project: StoreProject,
    name: str,
    *,
    version_uid: str = "",
    expect: Frame | None = None,
    role: str = "superficie",
    catalog: CrsCatalog | None = None,
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> Raster:
    """La superficie ``name`` del proyecto o de la versión activa ``version_uid`` tal como está
    en su fichero (RF-013-01): cada celda en float64, NaN donde no hay dato, en su rejilla, con su
    CRS y su datum vertical (los del proyecto si el fichero no los declara). Con ``expect`` (la
    rejilla del proyecto, :func:`project_frame`), compara antes **la cabecera** del fichero con
    ella y la rechaza sin leer una sola celda (:func:`check_grid`, con ``role`` en el mensaje:
    RF-013-16). Los errores de :func:`find_surface`; ``gis.dataset_file_missing`` si falta el
    fichero. Solo lee: no se modifica ni se remuestrea nada."""
    record = find_surface(project, name, version_uid=version_uid)
    path = _path(project, record)
    if expect is not None:
        check_grid(_header(project, path, catalog), expect, role=role, name=record.name)
    if record.module == GIS_MODULE and record.name.startswith(_GRID_PREFIXES):
        return load_raster(project, record, catalog=catalog, progress=progress,
                           cancelled=cancelled)
    source = read_geotiff(path, max_cells=sys.maxsize, catalog=catalog, progress=progress,
                          cancelled=cancelled)
    crs, vertical = project_references(project, catalog=catalog)
    return Raster(source.grid, source.values, source.declared_crs or crs,
                  source.declared_vertical or vertical)


# --- Leerla por ventana y por pasos (spec 015, T37) ---------------------------------------------

_READ_ROWS = 256
"""Las filas de la rejilla que se leen en cada unidad de :func:`read_surface_steps` (se redondea a un múltiplo del
alto de bloque del fichero: cada tesela se decodifica una sola vez)."""


@dataclass(frozen=True, slots=True, eq=False)
class SurfaceWindow:
    """Las celdas de una **ventana** de una superficie (:func:`read_surface_window`): el ``name`` de su dato, la
    ventana (``window``: filas y columnas de la rejilla del proyecto) y sus ``values`` (float64, NaN = sin dato, de
    la forma de la ventana)."""

    name: str
    window: tuple[slice, slice]
    values: np.ndarray


def _opened(project: StoreProject, name: str, version_uid: str, expect: Frame | None, role: str,
            catalog: CrsCatalog | None) -> tuple[DatasetRecord, Path, GeoTiffHeader, CrsRef, VerticalRef]:
    """Lo que tienen en común las lecturas por ventana y por pasos con :func:`read_surface`: el dato de la
    superficie, su fichero y su cabecera, comparada (con ``expect``) con la rejilla del proyecto **antes de leer una
    celda** (RF-013-16), y el CRS y el datum vertical con que se lee (los que declara el fichero o, si no, los del
    proyecto)."""
    record = find_surface(project, name, version_uid=version_uid)
    path = _path(project, record)
    crs, vertical = project_references(project, catalog=catalog)
    with path.open("rb") as stream:
        header = read_header(stream, path.stat().st_size, path.name, catalog=catalog)
    crs, vertical = header.crs or crs, header.vertical or vertical
    if expect is not None:
        check_grid(ProjectFrame(header.grid, crs, vertical), expect, role=role, name=record.name)
    return record, path, header, crs, vertical


def read_surface_window(
    project: StoreProject,
    name: str,
    window: tuple[slice, slice],
    *,
    version_uid: str = "",
    expect: Frame | None = None,
    role: str = "superficie",
    catalog: CrsCatalog | None = None,
) -> SurfaceWindow:
    """Las celdas de la ventana ``window`` (filas y columnas de la rejilla, ``slice`` de enteros sin paso) de la
    superficie ``name`` del proyecto o de la versión activa ``version_uid``: las mismas, bit a bit, que
    ``read_surface(...).values[window]``, decodificando **solo** las teselas que la tocan. Los mismos rechazos que
    :func:`read_surface` y con ``expect`` la misma comparación previa de la cabecera (sin leer una celda). Una
    ventana vacía o que se sale de la rejilla es un error del programa (``ValueError``). No comprueba que la
    superficie tenga algún dato (``gis.raster_empty``): lo sabe quien la lee entera."""
    record, path, header, _crs, _vertical = _opened(project, name, version_uid, expect, role, catalog)
    rows, cols = window
    for part in (rows, cols):
        if part.step not in (None, 1) or not isinstance(part.start, int) or not isinstance(part.stop, int):
            raise ValueError(f"la ventana {window!r} se indica con filas y columnas enteras, sin paso")
    with path.open("rb") as stream:
        values = read_window(stream, header, (rows.start, rows.stop), (cols.start, cols.stop))
    return SurfaceWindow(record.name, (slice(rows.start, rows.stop), slice(cols.start, cols.stop)), values)


def read_surface_steps(
    project: StoreProject,
    name: str,
    *,
    version_uid: str = "",
    expect: Frame | None = None,
    role: str = "superficie",
    catalog: CrsCatalog | None = None,
) -> Generator[None, None, Raster]:
    """:func:`read_surface` por pasos: una unidad (un ``yield``) por cada banda de filas de la rejilla, sin sostener
    el fichero abierto entre unidades; devuelve la misma :class:`~geoblender.gis.raster.Raster`, bit a bit. Los
    mismos rechazos (``expect`` compara la cabecera antes de leer una celda, y una superficie sin ningún dato es
    ``gis.raster_empty``). Cerrarlo a mitad no deja nada (solo lee)."""
    record, path, header, crs, vertical = _opened(project, name, version_uid, expect, role, catalog)
    values = np.empty((header.height, header.width), np.float64)
    band = header.layout.block_h * max(1, _READ_ROWS // header.layout.block_h)
    for top in range(0, header.height, band):
        stop = min(top + band, header.height)
        with path.open("rb") as stream:
            values[top:stop] = read_rows(stream, header, top, stop)
        yield None
    if np.isnan(values).all():
        raise GisError("gis.raster_empty", obj=path.name, field="valores", file=path.name)
    return Raster(header.grid, values, crs, vertical)

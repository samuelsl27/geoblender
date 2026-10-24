# SPDX-License-Identifier: GPL-3.0-or-later
"""Las superficies de una cubicación (spec 011; RF-011-02, RF-011-03, RF-011-06; plan 011
§5.3.1, A1, A2, D-24, D-31).

- :class:`SurfaceRef`: a qué superficie se refiere una cubicación o una unidad de la columna de
  materiales, sin leerla: un dato (``dataset``, por su nombre: estable al recalcularlo), un dato
  congelado en la revisión de la que parte la versión activa (``frozen``) o una cota constante
  (``elevation``, m, float64). ``label`` es el nombre que ve una persona (no cuenta al
  comparar).
- :class:`SurfaceHeader`: lo que se compara de una superficie **sin leer sus celdas** (A1): su
  nombre, su rejilla (``None`` en una cota constante), su CRS y su referencia vertical (las que
  declara el GeoTIFF o, si no las declara, las del proyecto, como ``gis.store.load_raster``).
- :class:`SurfaceSource`: lo que se lee (plan T3): la ruta de un GeoTIFF con su cabecera, o una
  cota constante. :func:`grid_source` y :func:`constant_source` la crean sin el proyecto (así
  la misma lectura sirve a la orden, al recálculo y a reproducir); :func:`surface_source`, desde
  una :class:`SurfaceRef` en un proyecto: una rejilla del proyecto o de la versión activa por su
  nombre, una congelada en la revisión de la que parte (la copia de su instantánea,
  ``core.versions.read.frozen_location``) o una cota constante (RF-011-02); un TIN
  (``res.surface_is_tin``) o un dato de otra versión (``res.surface_other_version``) se
  rechazan (RF-011-03).
- :func:`check_pair`: RF-011-03 por cabeceras (``gis.grid.geometry_mismatch``): la misma
  rejilla bit a bit, el mismo CRS y el mismo datum vertical (este, no para una rejilla de
  espesores, R7), o ``res.surfaces_mismatch`` con las dos superficies, la diferencia y la orden
  de la 006 que la resuelve. Una cota constante casa con cualquier rejilla.
- :func:`band_reader` y :func:`lockstep_bands`: las celdas **tal como están en el fichero**
  (ninguna superficie se remuestrea ni se interpola, RF-011-02), por bandas de filas, de una o
  de varias superficies al paso (las mismas filas de todas en cada banda, aunque sus teselas
  sean distintas); una cota constante da su cota (un número, como lo admite
  ``reserves.kernel``).
- :func:`propose_order` (RF-011-06, D-31): de partida, la de mayor cota media en las celdas
  comunes de una fila de teselas de cada cuatro.
- :func:`surface_choices` (RF-011-02; T21): las superficies que ofrece la orden de una
  cubicación (:class:`SurfaceChoice`): las rejillas vivas del proyecto y de la versión activa y
  las de versión congeladas en la revisión de la que parte.

Python puro (nivel 9).
"""

from __future__ import annotations

import math
import os
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

import numpy as np

from ..core.datasets import registry as dataset_registry
from ..core.datasets.model import LIVE_STATUSES, DatasetRecord
from ..core.georef import CrsCatalog, CrsRef, VerticalRef
from ..core.versions import read as versions_read
from ..core.versions.model import RevisionState, VersionError
from ..gis.geotiff.reader import GeoTiffHeader, read_header, read_rows
from ..gis.grid import Grid, geometry_mismatch
from ..gis.messages import GisError
from ..gis.provenance import FAMILIES_BY_CODE, TIN
from ..gis.provenance import MODULE as GIS_MODULE
from ..gis.store import StoreProject, project_references
from .messages import ResError

__all__ = [
    "BAND_ROWS",
    "SAMPLE_EVERY",
    "SurfaceChoice",
    "SurfaceHeader",
    "SurfaceRef",
    "SurfaceSource",
    "band_reader",
    "check_pair",
    "constant_source",
    "grid_source",
    "lockstep_bands",
    "propose_order",
    "surface_choices",
    "surface_source",
]

BAND_ROWS = 256
"""Las filas de una banda (las de una fila de teselas del perfil ``project`` de la 006)."""
SAMPLE_EVERY = 4
"""La propuesta de orden lee una fila de teselas de cada tantas (D-31)."""

_OBJ = "Superficies de la cubicación"
_FIELD = "superficie"
_NO_VERSION = "—"
_RASTER = "raster"
_FROZEN_DATASET = (  # por el índice único de (revision_uid, item_kind, item_uid)
    "SELECT d.uid, d.version_uid FROM gb_revision_item AS i JOIN gb_dataset AS d "
    "ON d.uid = i.item_uid WHERE i.revision_uid = ? AND i.item_kind = 'dataset' "
    "AND i.content_sha256 IS NOT NULL AND (d.uid = ? OR d.name = ?) "
    "ORDER BY d.uid = ? DESC, d.version_uid = '' LIMIT 1"
)
_OWNER = (  # el índice de nombres vivos por versión; las versiones son pocas
    "SELECT v.code FROM gb_dataset AS d JOIN gb_version AS v ON v.uid = d.version_uid "
    "WHERE d.name = ? AND d.version_uid <> '' AND d.status IN ({marks}) "
    "ORDER BY CAST(substr(v.code, 2) AS INTEGER), v.code LIMIT 1"
)
_OWN_MODULE = "res"  # las rejillas de diferencias de la cubicación no son superficies
_LIVE_GRIDS = (
    "SELECT uid, name, version_uid FROM gb_dataset WHERE kind = 'raster' AND module <> ? "
    "AND status IN ({marks}) AND version_uid IN ('', ?) ORDER BY name, version_uid = ''"
)
_FROZEN_GRIDS = (  # las de versión: lo del proyecto se usa vivo
    "SELECT d.uid, d.name FROM gb_revision_item AS i JOIN gb_dataset AS d "
    "ON d.uid = i.item_uid WHERE i.revision_uid = ? AND i.item_kind = 'dataset' "
    "AND i.content_sha256 IS NOT NULL AND d.version_uid <> '' AND d.kind = 'raster' "
    "AND d.module <> ? ORDER BY d.name, d.uid"
)


@dataclass(frozen=True, slots=True)
class SurfaceRef:
    """Una superficie, sin leerla: exactamente una de ``dataset`` (el nombre de un dato),
    ``frozen`` (un dato congelado en la revisión de la que parte la versión activa, RF-011-02)
    o ``elevation`` (una cota constante, m, número finito). ``label``, su nombre para una
    persona (no cuenta al comparar dos). Una referencia incoherente es un error del programa
    (:class:`ValueError`)."""

    dataset: str | None = None
    frozen: str | None = None
    elevation: float | None = None
    label: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        given = [name for name in ("dataset", "frozen", "elevation")
                 if getattr(self, name) is not None]
        if len(given) != 1:
            raise ValueError("una superficie es un dato, un dato congelado o una cota "
                             f"constante (una sola), no {given or 'ninguna'}")
        for name in ("dataset", "frozen"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"el {name} de una superficie es un nombre, no {value!r}")
        elevation = self.elevation
        if elevation is not None:
            object.__setattr__(self, "elevation", _elevation(elevation))
        if not isinstance(self.label, str):
            raise ValueError(f"el nombre de una superficie es un texto, no {self.label!r}")

    @property
    def shown(self) -> str:
        """El nombre para una persona: ``label`` o, sin él, el dato o la cota (m)."""
        if self.label:
            return self.label
        if self.elevation is not None:
            return f"{self.elevation!r} m"
        return self.dataset if self.dataset is not None else str(self.frozen)


def _elevation(value: object) -> float:
    """Una cota constante como float (float64): un número finito."""
    if isinstance(value, bool) or not isinstance(value, int | float | np.integer | np.floating):
        raise ValueError(f"una cota constante es un número, no {value!r}")
    if not math.isfinite(value):
        raise ValueError(f"una cota constante es un número finito, no {value!r}")
    return float(value)


@dataclass(frozen=True, slots=True)
class SurfaceHeader:
    """Lo que se compara de una superficie sin leer sus celdas (A1): ``name`` (para una
    persona), ``grid`` (``None`` en una cota constante, que casa con cualquiera), ``crs`` y
    ``vertical``."""

    name: str
    grid: Grid | None
    crs: CrsRef
    vertical: VerticalRef


@dataclass(frozen=True, slots=True)
class SurfaceSource:
    """Lo que se lee de una superficie (plan 011 T3): un GeoTIFF (``path``) con su
    :class:`SurfaceHeader`, o una cota constante (``elevation``, m)."""

    header: SurfaceHeader
    path: Path | None = None
    elevation: float | None = None

    def __post_init__(self) -> None:
        if (self.path is None) == (self.elevation is None):
            raise ValueError("una superficie se lee de un GeoTIFF o es una cota constante "
                             "(una de las dos)")
        if (self.header.grid is None) != (self.path is None):
            raise ValueError("un GeoTIFF tiene rejilla y una cota constante, no")

    @property
    def name(self) -> str:
        """Su nombre para una persona."""
        return self.header.name

    @property
    def grid(self) -> Grid | None:
        """Su rejilla (``None`` en una cota constante)."""
        return self.header.grid


# --- Crear las fuentes ----------------------------------------------------------------------


def _read_header(stream: BinaryIO, path: Path, catalog: CrsCatalog | None) -> GeoTiffHeader:
    return read_header(stream, os.fstat(stream.fileno()).st_size, path.name, catalog=catalog)


def grid_source(path: Path | str, *, name: str, crs: CrsRef, vertical: VerticalRef,
                catalog: CrsCatalog | None = None) -> SurfaceSource:
    """La superficie del GeoTIFF ``path`` (del proyecto o de una instantánea) con la cabecera
    que declara (``gis.geotiff.reader.read_header``: comprobada, sin leer sus celdas): su
    rejilla y su CRS y su referencia vertical o, si no los declara, ``crs`` y ``vertical``
    (los del proyecto). ``name``, su nombre para una persona. ``GisError`` si el fichero no se
    admite; ``OSError`` si no se puede abrir."""
    path = Path(path)
    with path.open("rb") as stream:
        header = _read_header(stream, path, catalog)
    return SurfaceSource(
        SurfaceHeader(name, header.grid, header.crs or crs, header.vertical or vertical),
        path=path)


def constant_source(elevation: float, *, name: str, crs: CrsRef,
                    vertical: VerticalRef) -> SurfaceSource:
    """Una cota constante (m) en el CRS y el datum del proyecto (``crs``, ``vertical``): casa
    con cualquier rejilla (A1)."""
    return SurfaceSource(SurfaceHeader(name, None, crs, vertical),
                         elevation=_elevation(elevation))


def _is_tin(record: DatasetRecord) -> bool:
    return record.module == GIS_MODULE and record.name.startswith(FAMILIES_BY_CODE[TIN].prefix)


def _check_grid(record: DatasetRecord, ref: SurfaceRef) -> None:
    """Un TIN se rechaza con la orden que lo lleva a rejilla (RF-011-02, RF-006-17); lo que no
    es una rejilla (``raster``) no es una superficie (las listas de las órdenes no lo
    ofrecen)."""
    if _is_tin(record):
        raise ResError("res.surface_is_tin", obj=_OBJ, field=_FIELD, value=record.name,
                       surface=ref.shown)
    if record.kind != _RASTER:
        raise ValueError(f"«{record.name}» ({record.kind}) no es una rejilla: no es una "
                         "superficie")


def _code(conn: sqlite3.Connection, version_uid: str) -> str:
    found = versions_read.version(conn, version_uid) if version_uid else None
    return _NO_VERSION if found is None else found.code


def _other_version(conn: sqlite3.Connection, ref: SurfaceRef, name: str, owner: str,
                   version_uid: str) -> ResError:
    return ResError("res.surface_other_version", obj=_OBJ, field=_FIELD, value=name,
                    surface=ref.shown, version=owner, active=_code(conn, version_uid))


def _dataset(conn: sqlite3.Connection, ref: SurfaceRef, version_uid: str) -> DatasetRecord:
    """El dato vivo de ``ref.dataset`` (uid o nombre) de la versión activa o del proyecto; de
    otra versión, ``res.surface_other_version`` (RF-011-03)."""
    name = str(ref.dataset)
    record = dataset_registry.get(conn, name, version_uid=version_uid)
    if record is None and version_uid:
        record = dataset_registry.get(conn, name)
    if record is not None and not record.live:
        record = None
    if record is None:
        marks = ", ".join("?" for _ in LIVE_STATUSES)
        row = (conn.execute(_OWNER.format(marks=marks),
                            (name, *(str(status) for status in LIVE_STATUSES))).fetchone()
               if versions_read.has_versions(conn) else None)
        if row is not None:
            raise _other_version(conn, ref, name, str(row[0]), version_uid)
        raise GisError("gis.dataset_unknown", obj=_OBJ, field=_FIELD, value=name)
    if versions_read.has_versions(conn):
        owner = versions_read.dataset_versions(conn, [record.uid]).get(record.uid, "")
        if owner and owner != version_uid:
            raise _other_version(conn, ref, record.name, _code(conn, owner), version_uid)
    _check_grid(record, ref)
    return record


def _frozen(conn: sqlite3.Connection, ref: SurfaceRef,
            version_uid: str) -> tuple[DatasetRecord, str]:
    """El dato ``ref.frozen`` (uid o nombre) congelado en la revisión de la que parte la
    versión activa y dónde está su copia (RF-011-02, RF-009-01, D-27 de la 009): solo de esa
    revisión, congelada y no alterada, y de una versión (lo del proyecto se usa vivo)."""
    name = str(ref.frozen)
    version = versions_read.version(conn, version_uid) if version_uid else None
    values: dict[str, object] = {"field": _FIELD, "value": name, "dataset": ref.shown}
    if version is not None:
        values["version"] = version.code
    parent = (None if version is None or version.parent_revision_uid is None
              else versions_read.revision(conn, version.parent_revision_uid))
    if parent is None or parent.state is not RevisionState.FROZEN:
        raise VersionError("core.version_frozen_missing", revision=_NO_VERSION, **values)
    label = parent.label(_code(conn, parent.version_uid))
    if parent.altered:
        raise VersionError("core.version_frozen_altered", revision=label, **values)
    row = conn.execute(_FROZEN_DATASET, (parent.uid, name, name, name)).fetchone()
    if row is None:
        raise VersionError("core.version_frozen_missing", revision=label, **values)
    uid, owner = str(row[0]), str(row[1])
    if not owner:
        raise VersionError("core.version_frozen_project", revision=label, **values)
    location = versions_read.frozen_location(conn, parent.uid, uid)
    record = dataset_registry.get(conn, uid)
    if location is None or record is None:
        raise VersionError("core.version_frozen_missing", revision=label, **values)
    _check_grid(record, ref)
    return record, location.locator if location.path is None else location.path


def surface_source(project: StoreProject, ref: SurfaceRef, *, version_uid: str = "",
                   catalog: CrsCatalog | None = None) -> SurfaceSource:
    """La superficie ``ref`` del proyecto con la versión activa ``version_uid`` (``''``: sin
    versión, solo lo del proyecto) (RF-011-02, RF-011-03; plan 011 A1):

    - una cota constante, en el CRS y el datum del proyecto;
    - un dato por su nombre (o su uid): una rejilla de la versión activa o, si no la tiene, del
      proyecto (un MDT en su rejilla de origen o la rejilla del proyecto); uno de otra versión,
      ``res.surface_other_version`` con el dato y su versión; un TIN, ``res.surface_is_tin``
      con la orden que lo lleva a rejilla; uno que no hay, ``gis.dataset_unknown``;
    - un dato congelado: el de la revisión de la que parte la versión activa, leído de la copia
      de su instantánea (``core.versions.read.frozen_location``); si no está, ni la revisión
      ni el dato, ``VersionError`` de la 009 (``core.version_frozen_*``).

    La cabecera, la del fichero (``grid_source``, con las referencias del proyecto si no las
    declara); si falta el fichero, ``gis.dataset_file_missing``. No lee celdas."""
    if not isinstance(ref, SurfaceRef):
        raise TypeError(f"una superficie se indica con una SurfaceRef, no {ref!r}")
    crs, vertical = project_references(project, catalog=catalog)
    if ref.elevation is not None:
        return constant_source(ref.elevation, name=ref.shown, crs=crs, vertical=vertical)
    with project.read() as conn:
        if ref.frozen is not None:
            record, relative = _frozen(conn, ref, version_uid)
        else:
            record = _dataset(conn, ref, version_uid)
            relative = record.locator
    path = Path(project.root, *relative.split("/"))
    if not path.is_file():
        raise GisError("gis.dataset_file_missing", obj=f"{_OBJ}: «{ref.shown}»",
                       field="ubicación", value=relative, file=path.name, name=record.name)
    return grid_source(path, name=ref.shown, crs=crs, vertical=vertical, catalog=catalog)


@dataclass(frozen=True, slots=True)
class SurfaceChoice:
    """Una superficie que ofrece la orden de una cubicación (RF-011-02): su referencia
    (``ref``: el dato por su nombre, o lo congelado), el uid y el nombre de su dato, la versión
    del dato vivo (``version_uid``: ``''`` del proyecto) y, de lo congelado, la revisión
    (``revision``, «V01.r1», y su uid)."""

    ref: SurfaceRef
    uid: str
    name: str
    version_uid: str = ""
    revision: str | None = None
    revision_uid: str | None = None


def surface_choices(project: StoreProject, *, version_uid: str = "") -> tuple[SurfaceChoice, ...]:
    """Las superficies que puede cubicar la orden con la versión activa ``version_uid`` (``''``:
    sin versión) (RF-011-02; T21), por nombre: las rejillas vivas del proyecto y las de la
    versión activa (de un nombre en las dos, la de la versión, la que lee
    :func:`surface_source`) y, si la versión parte de una revisión congelada que no está
    alterada, las rejillas de versión congeladas en ella (lo del proyecto se usa vivo). Ni un
    TIN, ni una rejilla de diferencias, ni lo de otra versión. Solo lee."""
    marks = ", ".join("?" for _ in LIVE_STATUSES)
    found: dict[str, SurfaceChoice] = {}
    frozen: list[SurfaceChoice] = []
    with project.read() as conn:
        rows = conn.execute(_LIVE_GRIDS.format(marks=marks),
                            (_OWN_MODULE, *(str(status) for status in LIVE_STATUSES),
                             version_uid)).fetchall()
        for uid, name, owner in rows:
            found.setdefault(str(name), SurfaceChoice(SurfaceRef(dataset=str(name)), str(uid),
                                                      str(name), str(owner or "")))
        version = versions_read.version(conn, version_uid) if version_uid else None
        parent = (None if version is None or version.parent_revision_uid is None
                  else versions_read.revision(conn, version.parent_revision_uid))
        if parent is not None and parent.state is RevisionState.FROZEN and not parent.altered:
            label = parent.label(_code(conn, parent.version_uid))
            names: set[str] = set()
            for uid, name in conn.execute(_FROZEN_GRIDS, (parent.uid, _OWN_MODULE)):
                if str(name) not in names:
                    names.add(str(name))
                    frozen.append(SurfaceChoice(SurfaceRef(frozen=str(name)), str(uid),
                                                str(name), revision=label,
                                                revision_uid=parent.uid))
    return (*found.values(), *frozen)


# --- Comprobar ------------------------------------------------------------------------------


def _header(surface: SurfaceHeader | SurfaceSource) -> SurfaceHeader:
    if isinstance(surface, SurfaceSource):
        return surface.header
    if isinstance(surface, SurfaceHeader):
        return surface
    raise TypeError(f"se esperaba una superficie, no {type(surface).__name__}")


def check_pair(start: SurfaceHeader | SurfaceSource, final: SurfaceHeader | SurfaceSource, *,
               vertical: bool = True) -> None:
    """RF-011-03 por cabeceras, sin leer celdas (A1): las dos superficies en la misma rejilla
    (bit a bit: oeste, norte, pasos, columnas y filas), el mismo CRS y, con ``vertical``, el
    mismo datum vertical (sin él, para una rejilla de espesores, R7). Una cota constante casa
    con cualquier rejilla (y se compara su CRS y su datum, los del proyecto); dos cotas
    constantes no tienen celdas que cubicar (``res.surfaces_no_grid``). Si no, ``ResError``
    ``res.surfaces_mismatch`` con las dos, la diferencia («paso en X 1 frente a 0,5»; campo y
    valor de ``final``) y la orden de la 006 que lleva una superficie a la rejilla del
    proyecto."""
    first, second = _header(start), _header(final)
    if first.grid is None and second.grid is None:
        raise ResError("res.surfaces_no_grid", obj=_OBJ, field=_FIELD, value=second.name,
                       surface=first.name, other=second.name)
    grid_a = first.grid if first.grid is not None else second.grid
    grid_b = second.grid if second.grid is not None else first.grid
    assert grid_a is not None and grid_b is not None
    found = geometry_mismatch(grid_a, grid_b, first.crs, second.crs,
                              first.vertical if vertical else None,
                              second.vertical if vertical else None)
    if found is not None:
        name, value, detail = found
        raise ResError("res.surfaces_mismatch", obj=_OBJ, field=name, value=value,
                       surface=first.name, other=second.name, detail=detail)


# --- Leer -----------------------------------------------------------------------------------


def _rows(rows: object) -> int:
    if isinstance(rows, bool) or not isinstance(rows, int) or rows < 1:
        raise ValueError(f"una banda tiene al menos una fila, no {rows!r}")
    return rows


@contextmanager
def _opened(source: SurfaceSource, grid: Grid) -> Iterator[tuple[BinaryIO, GeoTiffHeader]]:
    """El fichero de ``source`` abierto y su cabecera, leída de nuevo (por si se rehízo):
    la rejilla ha de ser ``grid`` (lo comprueba antes :func:`check_pair`)."""
    if source.path is None or source.grid is None or not source.grid.same_geometry(grid):
        raise ValueError(f"«{source.name}» no está en la rejilla que se lee: compruébelo antes "
                         "con check_pair")
    with source.path.open("rb") as stream:
        header = _read_header(stream, source.path, None)
        if not header.grid.same_geometry(grid):
            raise ValueError(f"«{source.name}» ({source.path.name}) cambió de rejilla "
                             "mientras se leía")
        yield stream, header


def band_reader(source: SurfaceSource, grid: Grid, *,
                rows: int = BAND_ROWS) -> Iterator[tuple[int, np.ndarray | float]]:
    """Las celdas de ``source`` en la rejilla ``grid`` por bandas de ``rows`` filas, de norte a
    sur: ``(primera fila, banda)``, la banda en float64 con NaN sin dato, **tal como está en el
    fichero** (ninguna superficie se remuestrea ni se interpola, RF-011-02) y leyendo solo los
    bloques que la tocan; una cota constante da su cota (un número) en cada banda. La rejilla
    de un GeoTIFF ha de ser ``grid`` (``ValueError`` si no). Cerrar el generador cierra el
    fichero."""
    height = _rows(rows)
    if not isinstance(grid, Grid):
        raise TypeError(f"se esperaba una Grid, no {type(grid).__name__}")
    if source.elevation is not None:
        for top in range(0, grid.nrows, height):
            yield top, source.elevation
        return
    with _opened(source, grid) as (stream, header):
        for top in range(0, grid.nrows, height):
            yield top, read_rows(stream, header, top, min(top + height, grid.nrows))


def lockstep_bands(sources: Sequence[SurfaceSource], grid: Grid, *, rows: int = BAND_ROWS
                   ) -> Iterator[tuple[int, tuple[np.ndarray | float, ...]]]:
    """Las bandas de varias superficies **al paso** (RF-011-02; A2): en cada una, la misma
    primera fila y las mismas filas de todas (``band_reader`` de cada una), en el orden de
    ``sources``. Cerrar el generador cierra los ficheros."""
    readers = [band_reader(source, grid, rows=rows) for source in sources]
    try:
        for bands in zip(*readers, strict=True):
            tops = {top for top, _band in bands}
            assert len(tops) == 1
            yield bands[0][0], tuple(band for _top, band in bands)
    finally:
        for reader in readers:
            reader.close()


# --- Proponer el orden (RF-011-06, D-31) ----------------------------------------------------


def _sampled(source: SurfaceSource, grid: Grid, ranges: Sequence[tuple[int, int]]
             ) -> Iterator[np.ndarray | float]:
    """Las filas de cada intervalo de ``ranges`` de ``source`` (una cota constante, su cota)."""
    if source.elevation is not None:
        for _range in ranges:
            yield source.elevation
        return
    with _opened(source, grid) as (stream, header):
        for top, stop in ranges:
            yield read_rows(stream, header, top, stop)


def _means(a: SurfaceSource, b: SurfaceSource, grid: Grid,
           ranges: Sequence[tuple[int, int]]) -> tuple[float, float] | None:
    """Las cotas medias de ``a`` y ``b`` en sus celdas comunes de las filas ``ranges``;
    ``None`` si no tienen ninguna."""
    sum_a = sum_b = 0.0
    count = 0
    for band_a, band_b in zip(_sampled(a, grid, ranges), _sampled(b, grid, ranges),
                              strict=True):
        values_a, values_b = np.broadcast_arrays(np.asarray(band_a, np.float64),
                                                 np.asarray(band_b, np.float64))
        common = np.isfinite(values_a) & np.isfinite(values_b)
        count += int(np.count_nonzero(common))
        sum_a += float(np.sum(values_a[common]))
        sum_b += float(np.sum(values_b[common]))
    return None if count == 0 else (sum_a / count, sum_b / count)


def _tile_rows(source: SurfaceSource, grid: Grid) -> int:
    """Las filas de una fila de bloques (teselas o tiras) del GeoTIFF de ``source``."""
    with _opened(source, grid) as (_stream, header):
        return header.layout.block_h


def propose_order(a: SurfaceSource, b: SurfaceSource) -> tuple[SurfaceSource, SurfaceSource]:
    """El orden que se propone para cubicar ``a`` y ``b`` (RF-011-06, D-31): de partida, la de
    mayor cota media en sus celdas comunes (las que tienen dato en las dos; con huecos, solo
    esas) de una fila de teselas de cada :data:`SAMPLE_EVERY` (la 0, la 4…); si en ellas no
    hay ninguna común, en todas. Igualadas, sin celdas comunes o en rejillas distintas (eso lo
    rechaza la cubicación, :func:`check_pair`), ``(a, b)`` tal como vienen. Dos cotas
    constantes, por su cota. Lee solo las filas de la muestra."""
    if a.elevation is not None and b.elevation is not None:
        return (b, a) if b.elevation > a.elevation else (a, b)
    grid = a.grid if a.grid is not None else b.grid
    assert grid is not None
    if (a.grid is not None and b.grid is not None) and not a.grid.same_geometry(b.grid):
        return a, b
    block = _tile_rows(a if a.grid is not None else b, grid)
    tiles = range(-(-grid.nrows // block))
    sampled = [k for k in tiles if k % SAMPLE_EVERY == 0]
    means = _means(a, b, grid, [(k * block, min((k + 1) * block, grid.nrows))
                                for k in sampled])
    if means is None:
        rest = [k for k in tiles if k % SAMPLE_EVERY != 0]
        means = _means(a, b, grid, [(k * block, min((k + 1) * block, grid.nrows))
                                    for k in rest]) if rest else None
    if means is None:
        return a, b
    return (b, a) if means[1] > means[0] else (a, b)

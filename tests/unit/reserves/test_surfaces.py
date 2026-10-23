# SPDX-License-Identifier: GPL-3.0-or-later
"""Las superficies de una cubicación (spec 011, T11; HU-011-1; RF-011-02, RF-011-03, RF-011-06;
plan 011 §5.3.1, A1, D-31; contrato ``frozen_location`` del plan 009 §5.3.1).

- **RF-011-02**: una superficie es una rejilla del proyecto, una de la versión activa, una
  congelada en la revisión de la que parte la versión activa (``core.versions.read
  .frozen_location``: la copia de su instantánea) o una cota constante; un TIN se rechaza con la
  orden que lo lleva a rejilla (``res.surface_is_tin``). **Ninguna se remuestrea**: lo que se lee
  por bandas son las celdas del fichero, bit a bit, y la lectura de varias superficies va al
  paso (las mismas filas de todas en cada banda, con teselas distintas).
- **RF-011-03**: dos superficies en otra rejilla (esquina, paso, tamaño), otro CRS u otro datum
  vertical se rechazan **sin leer celdas** (``check_pair``, ``res.surfaces_mismatch``) nombrando
  las dos, la diferencia y la orden de la 006 que la resuelve; un dato de otra versión que no es
  la activa ni su revisión de partida, con el dato y su versión (``res.surface_other_version``).
  Una cota constante casa con cualquiera (en el CRS y el datum del proyecto).
- **RF-011-06** (D-31): ``propose_order`` pone de partida la de mayor cota media en sus celdas
  comunes (también con huecos) leyendo una fila de teselas de cada cuatro.

Datos sintéticos: GeoTIFF del perfil ``project`` de la 006 de 48 × 80 celdas de 2 m con teselas
de 16 (la tesela de 256 de la 006, más pequeña para que las pruebas sean rápidas) y un proyecto
mínimo: la base con las tablas reales de los datos, las versiones y lo congelado (sin sus
disparadores), sus ficheros en ``rasters/`` y en ``snapshots/``.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import unittest
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import numpy as np

from tests.support import res_fixtures as fx
from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender

surfaces = import_geoblender("reserves.surfaces")
res_messages = import_geoblender("reserves.messages")
gis = import_geoblender("gis")
writer = import_geoblender("gis.geotiff.writer")
gis_messages = import_geoblender("gis.messages")
versions_read = import_geoblender("core.versions.read")
versions_model = import_geoblender("core.versions.model")
versions_schema = import_geoblender("core.versions.schema")
provenance_schema = import_geoblender("core.provenance.schema")

Grid = gis.Grid
SurfaceRef = surfaces.SurfaceRef
ResError = res_messages.ResError

TILE = 16
"""Teselas de las pruebas (las de la 006 son de 256: aquí, 3 × 5 teselas por rejilla)."""
GRID = Grid(west=735_000.0, north=4_434_160.0, dx=2.0, dy=2.0, ncols=48, nrows=80)
OTHER_CRS = next(crs for crs in fx.CATALOG.horizontals() if crs.epsg != fx.CRS.epsg)
OTHER_VERTICAL = next(v for v in fx.CATALOG.verticals() if v.epsg != fx.VERTICAL.epsg)
FIX_COMMAND = "Topografía ▸ Rejilla de proyecto desde un MDT…"
TIN_COMMAND = "Topografía ▸ MDT ⇄ TIN…"
NOW = "2026-10-23T10:00:00.000Z"
READER = "gis.geotiff@1"
NORMALIZER = "gis.raster@1"


def _plane(level: float, *, slope: float = 0.01) -> np.ndarray:
    """Un plano inclinado en float64 con la forma de :data:`GRID`, sin dos celdas iguales."""
    rows, cols = np.indices(GRID.shape, dtype=np.float64)
    return level + slope * cols + 3.0 * slope * rows + np.sqrt(2.0) * 1e-3 * rows * cols


def _write(path: Path, values: np.ndarray, *, grid: Grid = GRID, crs: Any = fx.CRS,
           vertical: Any = fx.VERTICAL, tile: int = TILE) -> Path:
    """Escribe ``values`` como GeoTIFF del perfil ``project`` con teselas de ``tile``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with mock.patch.object(writer, "TILE_SIZE", tile):
        writer.write_geotiff(gis.Raster(grid, values, crs, vertical), path, profile="project")
    return path


def _bits(values: np.ndarray) -> bytes:
    """Los bytes de un array float64 (también los de cada NaN): «bit a bit»."""
    return np.ascontiguousarray(values, dtype=np.float64).tobytes()


def _stacked(bands: list[tuple[int, Any]]) -> np.ndarray:
    return np.concatenate([band for _top, band in bands], axis=0)


class _Folder(unittest.TestCase):
    """Una carpeta temporal por clase."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.folder = cls.enterClassContext(project_tmp("gb-011-t11-"))

    def source(self, name: str, values: np.ndarray, **kw: Any) -> Any:
        path = _write(self.folder / f"{name}.tif", values, **kw)
        return surfaces.grid_source(path, name=name, crs=fx.CRS, vertical=fx.VERTICAL)


class CheckPairTest(_Folder):
    """RF-011-03, RF-011-02: la comprobación por cabeceras, sin leer celdas."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.october = _write(cls.folder / "octubre.tif", _plane(610.0))
        cls.september = _write(cls.folder / "septiembre.tif", _plane(600.0), tile=32)
        half = replace(GRID, dx=1.0, dy=1.0, ncols=96, nrows=160)
        cls.fine = _write(cls.folder / "fino.tif", np.full(half.shape, 605.0), grid=half)

    def header(self, path: Path, name: str) -> Any:
        return surfaces.grid_source(path, name=name, crs=fx.CRS, vertical=fx.VERTICAL).header

    def rejected(self, start: Any, final: Any, **kw: Any) -> Any:
        with self.assertRaises(ResError) as caught:
            surfaces.check_pair(start, final, **kw)
        return caught.exception

    def test_same_grid_passes(self) -> None:
        """RF-011-03: dos rejillas iguales bit a bit (con teselas distintas) pasan; la
        cabecera es la del fichero (rejilla, CRS y datum declarados)."""
        start = self.header(self.october, "MDT octubre")
        final = self.header(self.september, "MDT septiembre")
        self.assertTrue(start.grid.same_geometry(GRID))
        self.assertEqual((start.crs, start.vertical), (fx.CRS, fx.VERTICAL))
        self.assertIsNone(surfaces.check_pair(start, final))
        self.assertIsNone(surfaces.check_pair(final, start))

    def test_differences_are_named(self) -> None:
        """RF-011-03: otra esquina, otro paso, otro tamaño, otro CRS u otro datum vertical: el
        rechazo nombra las dos superficies, la diferencia y la orden de la 006."""
        start = self.header(self.october, "MDT octubre")
        cases = {
            "west": (replace(start, grid=replace(GRID, west=GRID.west + 2.0)), "oeste"),
            "north": (replace(start, grid=replace(GRID, north=GRID.north - 2.0)), "norte"),
            "dx": (self.header(self.fine, "MDT septiembre"), "paso en X 2 frente a 1"),
            "ncols": (replace(start, grid=replace(GRID, ncols=47)), "columnas 48 frente a 47"),
            "nrows": (replace(start, grid=replace(GRID, nrows=81)), "filas 80 frente a 81"),
            "crs": (replace(start, crs=OTHER_CRS),
                    f"CRS EPSG:{fx.CRS.epsg} frente a EPSG:{OTHER_CRS.epsg}"),
            "vertical": (replace(start, vertical=OTHER_VERTICAL),
                         f"referencia vertical EPSG:{fx.VERTICAL.epsg} frente a "
                         f"EPSG:{OTHER_VERTICAL.epsg}"),
        }
        for field, (other, detail) in cases.items():
            final = replace(other, name="MDT septiembre")
            with self.subTest(field=field):
                error = self.rejected(start, final)
                self.assertEqual(error.code, "res.surfaces_mismatch")
                self.assertEqual(error.field, field)
                for part in ("«MDT octubre»", "«MDT septiembre»", detail, FIX_COMMAND):
                    self.assertIn(part, error.text)

    def test_thickness_without_vertical(self) -> None:
        """Plan 011 A1, R7: para una rejilla de espesores no se compara el datum vertical
        (``vertical=False``), sí la rejilla y el CRS."""
        start = self.header(self.october, "MDT octubre")
        thickness = replace(start, name="Espesor del escombro", vertical=OTHER_VERTICAL)
        self.assertIsNone(surfaces.check_pair(start, thickness, vertical=False))
        moved = replace(thickness, grid=replace(GRID, west=GRID.west - 2.0))
        self.assertEqual(self.rejected(start, moved, vertical=False).field, "west")
        self.assertEqual(self.rejected(start, replace(thickness, crs=OTHER_CRS),
                                       vertical=False).field, "crs")

    def test_constant_matches_any_grid(self) -> None:
        """RF-011-02: una cota constante casa con cualquier rejilla (en el CRS y el datum del
        proyecto); dos cotas constantes no tienen celdas que cubicar."""
        constant = surfaces.constant_source(612.5, name="Cota 612,5", crs=fx.CRS,
                                            vertical=fx.VERTICAL)
        self.assertIsNone(constant.header.grid)
        self.assertEqual(constant.elevation, 612.5)
        for path in (self.october, self.fine):
            grid = self.header(path, "MDT")
            with self.subTest(grid=path.name):
                self.assertIsNone(surfaces.check_pair(constant, grid))
                self.assertIsNone(surfaces.check_pair(grid, constant))
        elsewhere = replace(self.header(self.october, "MDT octubre"), crs=OTHER_CRS)
        self.assertEqual(self.rejected(elsewhere, constant).field, "crs")
        error = self.rejected(constant, replace(constant.header, name="Cota 600"))
        self.assertEqual(error.code, "res.surfaces_no_grid")
        self.assertIn("«Cota 612,5»", error.text)
        self.assertIn("«Cota 600»", error.text)


class BandsTest(_Folder):
    """RF-011-02: lo que se lee son las celdas del fichero, bit a bit, por bandas al paso."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.start_values = _plane(610.0)
        cls.start_values[20:37, 5:30] = np.nan  # un hueco que cruza teselas
        cls.final_values = _plane(590.0, slope=0.02)
        cls.start_path = _write(cls.folder / "partida.tif", cls.start_values)
        cls.final_path = _write(cls.folder / "final.tif", cls.final_values, tile=32)

    def sources(self) -> tuple[Any, Any]:
        return (surfaces.grid_source(self.start_path, name="Partida", crs=fx.CRS,
                                     vertical=fx.VERTICAL),
                surfaces.grid_source(self.final_path, name="Final", crs=fx.CRS,
                                     vertical=fx.VERTICAL))

    def test_bands_are_the_file_cells(self) -> None:
        """RF-011-02: las bandas, juntas, son las celdas del fichero bit a bit (NaN en el
        hueco), con bandas que no coinciden con las teselas; nada se remuestrea."""
        start, _final = self.sources()
        for rows in (16, 24, 80, 200):
            with self.subTest(rows=rows):
                bands = list(surfaces.band_reader(start, GRID, rows=rows))
                tops = [top for top, _band in bands]
                self.assertEqual(tops, list(range(0, GRID.nrows, rows)))
                self.assertEqual(_bits(_stacked(bands)), _bits(self.start_values))
                self.assertTrue(all(band.dtype == np.float64 for _top, band in bands))

    def test_several_surfaces_in_step(self) -> None:
        """RF-011-02: varias superficies (teselas de 16 y de 32 y una cota constante) se
        leen al paso: las mismas filas en cada banda; la constante, su cota."""
        start, final = self.sources()
        constant = surfaces.constant_source(600.0, name="Cota 600", crs=fx.CRS,
                                            vertical=fx.VERTICAL)
        steps = list(surfaces.lockstep_bands((start, constant, final), GRID, rows=24))
        self.assertEqual([top for top, _bands in steps], [0, 24, 48, 72])
        for top, (first, level, last) in steps:
            height = min(24, GRID.nrows - top)
            self.assertEqual(first.shape, (height, GRID.ncols))
            self.assertEqual(last.shape, (height, GRID.ncols))
            self.assertEqual(level, 600.0)
        self.assertEqual(_bits(np.concatenate([b[0] for _t, b in steps])),
                         _bits(self.start_values))
        self.assertEqual(_bits(np.concatenate([b[2] for _t, b in steps])),
                         _bits(self.final_values))

    def test_other_grid_or_closed_reader(self) -> None:
        """Leer una superficie en otra rejilla es un error del programa (se comprueba antes);
        cerrar la lectura a mitad deja el fichero libre."""
        start, _final = self.sources()
        with self.assertRaises(ValueError):
            next(surfaces.band_reader(start, replace(GRID, ncols=47)))
        reader = surfaces.band_reader(start, GRID, rows=16)
        next(reader)
        reader.close()
        moved = self.folder / "partida-movida.tif"
        os.replace(self.start_path, moved)  # en Windows, un fichero abierto no se mueve
        os.replace(moved, self.start_path)


class ProposeOrderTest(_Folder):
    """RF-011-06 (D-31): la propuesta de orden de dos superficies."""

    def test_higher_mean_is_the_start(self) -> None:
        """RF-011-06: de partida, la de mayor cota media; igualadas, como vienen."""
        low = self.source("baja", _plane(600.0))
        high = self.source("alta", _plane(600.5))
        self.assertEqual(surfaces.propose_order(low, high), (high, low))
        self.assertEqual(surfaces.propose_order(high, low), (high, low))
        same = self.source("igual", _plane(600.0))
        self.assertEqual(surfaces.propose_order(same, low), (same, low))
        self.assertEqual(surfaces.propose_order(low, same), (low, same))

    def test_common_cells_with_holes(self) -> None:
        """RF-011-06: la media es la de las celdas comunes: con huecos, la que está más alta
        donde las dos tienen dato, aunque la otra tenga más cota media en las suyas."""
        flat = _plane(600.0, slope=0.0)
        flat[:, :24] = np.nan
        other = np.where(np.arange(GRID.ncols) < 24, 640.0, 590.0) + np.zeros(GRID.shape)
        start = self.source("con-hueco", flat)
        final = self.source("sin-hueco", other)
        self.assertGreater(np.nanmean(other), np.nanmean(flat))
        self.assertEqual(surfaces.propose_order(final, start), (start, final))

    def test_one_tile_row_of_four(self) -> None:
        """D-31: se lee una fila de teselas de cada cuatro (aquí la 0 y la 4 de las cinco):
        lo que cambia en las otras no cuenta; sin celdas comunes en ellas, se leen todas."""
        level = np.full(GRID.shape, 600.0)
        read = np.full(GRID.shape, 590.0)
        read[TILE:4 * TILE] = 700.0  # las filas de teselas 1, 2 y 3: no se leen
        first = self.source("plana", level)
        second = self.source("alta-sin-leer", read)
        self.assertGreater(read.mean(), level.mean())
        self.assertEqual(surfaces.propose_order(second, first), (first, second))
        holes = np.full(GRID.shape, 620.0)
        holes[:TILE] = np.nan
        holes[4 * TILE:] = np.nan
        third = self.source("huecos-en-las-leidas", holes)
        self.assertEqual(surfaces.propose_order(first, third), (third, first))

    def test_constants_and_other_grids(self) -> None:
        """RF-011-06: una cota constante se compara con la media de la otra; dos constantes,
        por su cota; en rejillas distintas no se propone nada (lo rechaza la cubicación)."""
        grid = self.source("rejilla", _plane(600.0, slope=0.0))
        above = surfaces.constant_source(650.0, name="Cota 650", crs=fx.CRS,
                                         vertical=fx.VERTICAL)
        below = surfaces.constant_source(550.0, name="Cota 550", crs=fx.CRS,
                                         vertical=fx.VERTICAL)
        self.assertEqual(surfaces.propose_order(grid, above), (above, grid))
        self.assertEqual(surfaces.propose_order(below, grid), (grid, below))
        self.assertEqual(surfaces.propose_order(below, above), (above, below))
        other = self.source("otra", np.full((40, 48), 700.0), grid=replace(GRID, nrows=40))
        self.assertEqual(surfaces.propose_order(grid, other), (grid, other))


# --- Superficies del proyecto ---------------------------------------------------------------


class _Project:
    """Lo que lee ``surface_source`` de un proyecto (``gis.store.StoreProject``): su carpeta,
    su fila de ``gb_project`` (CRS y referencia vertical) y una conexión de lectura."""

    name = "Cubicación de prueba"

    def __init__(self, root: Path) -> None:
        self.root = root
        self.record = SimpleNamespace(crs_epsg=fx.CRS.epsg, vcrs_epsg=fx.VERTICAL.epsg,
                                      vcrs_note=None)

    @contextlib.contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.root / "project.gpkg")
        try:
            yield conn
        finally:
            conn.close()


def _schema(conn: sqlite3.Connection) -> None:
    """Las tablas reales de los datos, las versiones y lo congelado, sin disparadores."""
    conn.execute(provenance_schema.TABLES["gb_dataset"])
    for column, definition in provenance_schema.SCHEMA_3_COLUMNS["gb_dataset"].items():
        conn.execute(f"ALTER TABLE gb_dataset ADD COLUMN {column} {definition}")
    for table in ("gb_version", "gb_revision", "gb_revision_item"):
        conn.execute(versions_schema.TABLES[table])


def _version(conn: sqlite3.Connection, code: str, parent: str | None = None,
             parent_revision: str | None = None) -> str:
    conn.execute(
        "INSERT INTO gb_version (uid, code, feature, title, parent_uid, parent_revision_uid, "
        "reason_created, created_at, created_by, status_changed_at, status_changed_by, "
        "modified_at) VALUES (?, ?, 'prueba', ?, ?, ?, 'Prueba', ?, 'prueba', ?, 'prueba', ?)",
        (f"v-{code}", code, code, parent, parent_revision, NOW, NOW, NOW))
    return f"v-{code}"


def _revision(conn: sqlite3.Connection, version: str, number: int, *,
              frozen: bool = False) -> str:
    uid = f"{version}-r{number}"
    if frozen:
        conn.execute(
            "INSERT INTO gb_revision (uid, version_uid, number, state, reason, created_at, "
            "created_by, closed_at, closed_by, snapshot_dir, snapshot_sha256) VALUES "
            "(?, ?, ?, 'frozen', 'Prueba', ?, 'prueba', ?, 'prueba', ?, ?)",
            (uid, version, number, NOW, NOW, f"snapshots/{uid}", "0" * 64))
    else:
        conn.execute(
            "INSERT INTO gb_revision (uid, version_uid, number, reason, created_at, "
            "created_by) VALUES (?, ?, ?, 'Prueba', ?, 'prueba')",
            (uid, version, number, NOW))
    return uid


def _dataset(conn: sqlite3.Connection, name: str, locator: str, *, version: str = "",
             kind: str = "raster", store: str = "rasters", content: str = "") -> str:
    uid = f"d-{name}-{version or 'proyecto'}"
    conn.execute(
        "INSERT INTO gb_dataset (uid, name, module, kind, store, locator, reader, normalizer, "
        "content_sha256, operation_uid, created_at, modified_at, version_uid) VALUES "
        "(?, ?, 'gis', ?, ?, ?, ?, ?, ?, 'op', ?, ?, ?)",
        (uid, name, kind, store, locator, READER, NORMALIZER, content or f"h-{uid}", NOW, NOW,
         version))
    return uid


def _item(conn: sqlite3.Connection, revision: str, dataset: str, part: str, *,
          path: str | None = None, copied: bool = False) -> None:
    (content,) = conn.execute("SELECT content_sha256 FROM gb_dataset WHERE uid = ?",
                              (dataset,)).fetchone()
    conn.execute(
        "INSERT INTO gb_revision_item (revision_uid, item_kind, item_uid, part, "
        "content_sha256, copied, snapshot_path) VALUES (?, 'dataset', ?, ?, ?, ?, ?)",
        (revision, dataset, part, content, int(copied), path))


class ProjectSourceTest(unittest.TestCase):
    """RF-011-02, RF-011-03: las superficies de un proyecto con versiones.

    V01 (r1 congelada, r2 abierta), V02 sin padre y V03, que parte de V01.r1. Del proyecto:
    ``gis_dtm_octubre`` (rejilla del proyecto), ``gis_src_septiembre`` (lo importado) y
    ``gis_tin_puntos`` (un TIN). ``gis_dtm_final`` en V01 (congelado en V01.r1 con su copia en
    la instantánea, otras cotas que el vivo) y en V02 (el mismo nombre, otro fichero)."""

    @classmethod
    def setUpClass(cls) -> None:
        root = cls.enterClassContext(project_tmp("gb-011-t11p-"))
        cls.values = {name: _plane(level) for name, level in (
            ("octubre", 610.0), ("septiembre", 600.0), ("final_v01", 580.0),
            ("final_v02", 570.0), ("final_v01_r1", 585.0))}
        files = {
            "octubre": "rasters/gis_dtm_octubre.tif",
            "septiembre": "rasters/gis_src_septiembre.tif",
            "final_v01": "rasters/gis_dtm_final_v01.tif",
            "final_v02": "rasters/gis_dtm_final_v02.tif",
            "final_v01_r1": "snapshots/V01.r1/rasters/gis_dtm_final_v01.tif",
        }
        for name, locator in files.items():
            _write(Path(root, *locator.split("/")), cls.values[name], tile=32)
        conn = sqlite3.connect(root / "project.gpkg")
        try:
            with conn:
                _schema(conn)
                v1 = _version(conn, "V01")
                cls.v1_r1 = _revision(conn, v1, 1, frozen=True)
                _revision(conn, v1, 2)
                v2 = _version(conn, "V02")
                _revision(conn, v2, 1)
                v3 = _version(conn, "V03", parent=v1, parent_revision=cls.v1_r1)
                _revision(conn, v3, 1)
                cls.october = _dataset(conn, "gis_dtm_octubre", files["octubre"])
                cls.september = _dataset(conn, "gis_src_septiembre", files["septiembre"])
                _dataset(conn, "gis_tin_puntos", "meshes/gis_tin_puntos.npz", kind="mesh",
                         store="meshes")
                cls.final_v1 = _dataset(conn, "gis_dtm_final", files["final_v01"], version=v1)
                _dataset(conn, "gis_dtm_final", files["final_v02"], version=v2)
                _item(conn, cls.v1_r1, cls.final_v1, "produced",
                      path=files["final_v01_r1"], copied=True)
                _item(conn, cls.v1_r1, cls.september, "immutable")
                cls.v2_r1 = _revision(conn, v2, 2, frozen=True)
                _item(conn, cls.v2_r1, cls.final_v1, "inherited")
        finally:
            conn.close()
        cls.project = _Project(root)
        cls.versions = {"V01": v1, "V02": v2, "V03": v3}
        cls.files = files

    def source(self, ref: Any, version: str = "") -> Any:
        return surfaces.surface_source(self.project, ref,
                                       version_uid=self.versions.get(version, ""))

    def cells(self, source: Any) -> np.ndarray:
        return _stacked(list(surfaces.band_reader(source, source.header.grid)))

    def test_project_and_active_version(self) -> None:
        """RF-011-02: una rejilla del proyecto (la del proyecto o la de origen de un MDT) y
        una de la versión activa, por su nombre, con su fichero y las cotas tal cual."""
        cases = (
            ("gis_dtm_octubre", "V01", "octubre"),
            ("gis_src_septiembre", "V02", "septiembre"),
            ("gis_dtm_final", "V01", "final_v01"),
            ("gis_dtm_final", "V02", "final_v02"),
            ("gis_dtm_octubre", "", "octubre"),
        )
        for name, version, expected in cases:
            with self.subTest(name=name, version=version):
                found = self.source(SurfaceRef(dataset=name, label="MDT"), version)
                self.assertEqual(found.path, Path(self.project.root,
                                                  *self.files[expected].split("/")))
                self.assertEqual((found.header.name, found.header.crs, found.header.vertical),
                                 ("MDT", fx.CRS, fx.VERTICAL))
                self.assertEqual(_bits(self.cells(found)), _bits(self.values[expected]))

    def test_frozen_in_parent_revision(self) -> None:
        """RF-011-02: un dato congelado en la revisión de la que parte la versión activa se
        lee de la copia de su instantánea (``frozen_location``), no del dato vivo."""
        found = self.source(SurfaceRef(frozen="gis_dtm_final", label="Final V01.r1"), "V03")
        self.assertEqual(found.path, Path(self.project.root,
                                          *self.files["final_v01_r1"].split("/")))
        self.assertEqual(_bits(self.cells(found)), _bits(self.values["final_v01_r1"]))

    def test_frozen_location(self) -> None:
        """Plan 009 §5.3.1: dónde está un dato congelado en una revisión: la copia de su
        instantánea; lo inmutable del proyecto, sin copia (su ubicación en el proyecto); lo
        heredado sin ruta, la copia de otra congelada con el mismo contenido; ``None`` si la
        revisión no lo congeló."""
        with self.project.read() as conn:
            copy = versions_read.frozen_location(conn, self.v1_r1, self.final_v1)
            immutable = versions_read.frozen_location(conn, self.v1_r1, self.september)
            inherited = versions_read.frozen_location(conn, self.v2_r1, self.final_v1)
            missing = versions_read.frozen_location(conn, self.v1_r1, self.october)
        self.assertIsInstance(copy, versions_model.FrozenLocation)
        self.assertEqual((copy.path, copy.layer, copy.reader, copy.normalizer,
                          copy.content_sha256),
                         (self.files["final_v01_r1"], None, READER, NORMALIZER,
                          f"h-{self.final_v1}"))
        self.assertEqual((immutable.path, immutable.locator),
                         (None, self.files["septiembre"]))
        self.assertEqual(inherited.path, self.files["final_v01_r1"])
        self.assertIsNone(missing)

    def test_other_version_is_rejected(self) -> None:
        """RF-011-03: un dato de otra versión que no es la activa ni su revisión de partida
        se rechaza con el dato y su versión."""
        for version, active, owner in (("V03", "V03", "V01"), ("", "—", "V01")):
            with self.subTest(active=active):
                with self.assertRaises(ResError) as caught:
                    self.source(SurfaceRef(dataset="gis_dtm_final", label="MDT final"),
                                version)
                error = caught.exception
                self.assertEqual(error.code, "res.surface_other_version")
                for part in ("«MDT final»", f"versión {owner}", f"({active})"):
                    self.assertIn(part, error.text)

    def test_frozen_rejections(self) -> None:
        """RF-011-02, RF-009-01: solo lo congelado en la revisión de la que parte (no lo del
        proyecto, que se usa vivo); sin padre o sin ese dato, ``core.version_frozen_missing``;
        con la revisión alterada, ``core.version_frozen_altered``."""
        cases = (
            ("gis_dtm_final", "V02", "core.version_frozen_missing"),
            ("gis_dtm_nada", "V03", "core.version_frozen_missing"),
            ("gis_src_septiembre", "V03", "core.version_frozen_project"),
        )
        for name, version, code in cases:
            with self.subTest(name=name, version=version):
                with self.assertRaises(versions_model.VersionError) as caught:
                    self.source(SurfaceRef(frozen=name), version)
                self.assertEqual(caught.exception.code, code)
        with contextlib.closing(sqlite3.connect(self.project.root / "project.gpkg")) as conn:
            with conn:
                conn.execute("UPDATE gb_revision SET altered_at = ? WHERE uid = ?",
                             (NOW, self.v1_r1))
            try:
                with self.assertRaises(versions_model.VersionError) as caught:
                    self.source(SurfaceRef(frozen="gis_dtm_final"), "V03")
                self.assertEqual(caught.exception.code, "core.version_frozen_altered")
            finally:
                with conn:
                    conn.execute("UPDATE gb_revision SET altered_at = NULL WHERE uid = ?",
                                 (self.v1_r1,))

    def test_tin_unknown_and_constant(self) -> None:
        """RF-011-02: un TIN, con la orden que lo lleva a rejilla; un dato que no hay, el de la
        006; una cota constante, en el CRS y el datum del proyecto."""
        with self.assertRaises(ResError) as caught:
            self.source(SurfaceRef(dataset="gis_tin_puntos", label="TIN de puntos"), "V01")
        self.assertEqual(caught.exception.code, "res.surface_is_tin")
        self.assertIn("«TIN de puntos»", caught.exception.text)
        self.assertIn(TIN_COMMAND, caught.exception.text)
        with self.assertRaises(gis_messages.GisError) as unknown:
            self.source(SurfaceRef(dataset="gis_dtm_nada"), "V01")
        self.assertEqual(unknown.exception.code, "gis.dataset_unknown")
        constant = self.source(SurfaceRef(elevation=600.0, label="Cota 600"), "V01")
        self.assertEqual((constant.elevation, constant.path, constant.header.grid),
                         (600.0, None, None))
        self.assertEqual((constant.header.crs, constant.header.vertical),
                         (fx.CRS, fx.VERTICAL))


if __name__ == "__main__":
    unittest.main()

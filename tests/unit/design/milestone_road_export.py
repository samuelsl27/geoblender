# SPDX-License-Identifier: GPL-3.0-or-later
"""Exportar la pista con el proyecto (spec 017, T27; HU-017-1 y HU-017-4; RF-017-27, RF-013-34, RF-006-24 y RF-008-15; D-29 de la 011; decisión T27-a), como prueba de **hito**: ``check.py --completo`` la
ejecuta; el «verde» tiene las suyas, sin proyecto, en ``test_road_export.py``.

Sobre la copia del proyecto de las pistas (rejilla de 2 m, 200 × 200 celdas) con la «Pista de la rampa» (la rampa del 4 % de CE-017-01) y una accesibilidad de la cantera con bancos de V01:

- **El GeoTIFF** (:class:`RoadGeoTiffTest`): la superficie de la pista (``des_psf_``) y lo alcanzable de la accesibilidad (``des_acc_``) se leen de nuevo con la rejilla, el CRS y la referencia vertical del
  proyecto, cada valor igual al registrado redondeado a float32 (0 m de diferencia) y, de lo alcanzable, los códigos 0 y 1 con su leyenda en los metadatos.
- **El CSV de la rasante** (:class:`RoadCsvProjectTest`): una fila por estación del eje (``des_rdx_``) con la abscisa, la x y la y, las dos cotas y la pendiente **a ≤ 10⁻⁹** de lo registrado y de lo que dan
  las cotas (la pendiente del tramo, en %), con la convención del CSV de la cubicación; **no se escribe nada en el proyecto** y los rechazos tampoco escriben.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.versions_fixtures import change_counter, files
from tests.unit.design import test_access_operation as tao
from tests.unit.design.milestone_road_recompute import RecomputeCase, recompute_function
from tests.unit.design.test_road_prepare import BY, request

core_params = import_geoblender("core.params")
design_params = import_geoblender("design.params")
design_reproduce = import_geoblender("design.reproduce")
export = import_geoblender("design.export")
geokeys = import_geoblender("gis.geotiff.geokeys")
gis_messages = import_geoblender("gis.messages")
messages = import_geoblender("design.messages")
paths = import_geoblender("core.paths")
provenance = import_geoblender("design.provenance")
reader = import_geoblender("gis.geotiff.reader")
steps = import_geoblender("design.steps")
tiff = import_geoblender("gis.geotiff.tiff")

NO_READ_ONLY = paths.ReadOnlyDirs.from_sources(None, [])
ROAD = "Pista de la rampa"
ACCESS = "Accesibilidad"
NODATA = -9999.0


class ExportCase(RecomputeCase):
    """Lo de ``RecomputeCase`` con la pista y la accesibilidad de la cantera con bancos de V01 creadas."""

    out: ClassVar[Path]
    road: ClassVar[Any]

    @classmethod
    def entity_definitions(cls) -> tuple[Any, ...]:
        return (*super().entity_definitions(), provenance.operation_def(provenance.ROAD_ACCESS, recompute_function, design_reproduce.reproduce_road_access))

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_families(design_params.ACCESS_FAMILIES)
        cls.enterClassContext(registered(*provenance.ACCESS_FIGURES))
        cls.road = cls.made(request(ROAD))[1]
        cls.clock.advance(minutes=1)
        tao.run(steps.access_run(cls.project, tao.request(ACCESS), version=cls.v1.uid, masks=cls.masks_v1)).create(decided_by=BY)
        cls.clock.advance(minutes=1)
        cls.out = Path(cls.root).parent / f"{Path(cls.root).name}-exportado"
        cls.out.mkdir(exist_ok=True)
        cls.addClassCleanup(shutil.rmtree, cls.out, ignore_errors=True)

    def snapshot(self) -> dict[str, Any]:
        """Lo que podría escribir exportar: el contador de cambios, las operaciones, los datos, los eventos y los ficheros del proyecto."""
        return {"counter": change_counter(self.root), "operations": self.query("SELECT uid, status FROM gb_operation ORDER BY rowid"),
                "datasets": self.query("SELECT uid, status, content_sha256 FROM gb_dataset ORDER BY rowid"), "files": files(self.root, skip=(), skip_dirs=("cache",))}

    def registered_grid(self, family: str, name: str) -> Any:
        found = export.stored_grid(self.project, provenance.dataset_name(family, name), version=self.v1.uid)
        return reader.read_geotiff(Path(self.root).joinpath(*found.record.locator.split("/")), max_cells=sys.maxsize)


class RoadGeoTiffTest(ExportCase):
    """RF-017-27, RF-013-34, RF-006-24: el GeoTIFF de la superficie de la pista y de lo alcanzable."""

    def test_a_the_road_surface_and_the_reachable_grid_read_back_equal_to_the_registered_ones_in_the_crs_of_the_project(self) -> None:
        """RF-017-27, RF-013-34: la superficie de la pista (``des_psf_``) y lo alcanzable (``des_acc_``) se exportan georreferenciadas **en el CRS y la referencia vertical del proyecto**, con la misma rejilla,
        el «sin dato» −9999 declarado y cada valor igual al registrado pasado a float32 (0 m de diferencia); lo alcanzable solo tiene los códigos 0 y 1."""
        for family, name in ((provenance.ENTITY_SURFACE_GRID, ROAD), (provenance.ACCESS_GRID, ACCESS)):
            with self.subTest(family=family):
                stored = self.registered_grid(family, name)
                target = self.out / f"{family}.tif"
                found_path = export.export_grid(self.project, family, name, target, version=self.v1.uid, read_only=NO_READ_ONLY, overwrite=True)
                found = reader.read_geotiff(found_path, max_cells=sys.maxsize)
                self.assertEqual(found.grid, stored.grid)
                self.assertEqual((found.declared_crs.epsg, found.declared_vertical.epsg), (rd.CRS.epsg, self.project.record.vcrs_epsg))
                self.assertEqual((found.source_dtype, found.nodata_value), ("float32", NODATA))
                finite = np.isfinite(stored.values)
                np.testing.assert_array_equal(found.values, np.where(finite, stored.values.astype(np.float32).astype(np.float64), np.nan))
                if family == provenance.ACCESS_GRID:
                    self.assertEqual(sorted(np.unique(found.values[np.isfinite(found.values)]).tolist()), [0.0, 1.0])

    def test_b_the_metadata_of_the_reachable_grid_carry_its_legend_and_nothing_is_written_in_the_project(self) -> None:
        """RF-017-27, RF-013-34, D-29 de la 011: los metadatos de lo alcanzable dicen la unidad «código», qué es, el dato, la versión y la leyenda (0 «no alcanzable», 1 «alcanzable»); exportar **no es una
        operación**: no escribe nada en el proyecto y no deja ningún temporal."""
        before = self.snapshot()
        target = self.out / "alcanzable.tif"
        export.export_grid(self.project, provenance.ACCESS_GRID, ACCESS, target, version=self.v1.uid, read_only=NO_READ_ONLY, overwrite=True)
        with target.open("rb") as stream:
            ifd = tiff.read_first_ifd(stream, target.stat().st_size)
        items = geokeys.parse_gdal_items(ifd.text(tiff.GDAL_METADATA) or "")
        self.assertEqual(items, export.metadata_items(provenance.ACCESS_GRID, ACCESS, self.v1.code))
        self.assertEqual((items["UNIDAD"], items["CODIGO_0"], items["CODIGO_1"]), ("código", "no alcanzable", "alcanzable"))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(sorted(path.name for path in self.out.glob("*.tmp")), [])


class RoadCsvProjectTest(ExportCase):
    """RF-017-27, T27-a: la rasante de la pista a CSV."""

    def axis(self) -> np.ndarray:
        """El eje por estaciones registrado de la pista (``des_rdx_``): ``(n, 6)`` en el orden del CSV."""
        locator = provenance.dataset_locator(provenance.ROAD_AXIS_TABLE, ROAD, "V01")
        return np.asarray(self.query(f'SELECT station_m, x, y, terrain_m, level_m, gradient_pct FROM "{locator}" ORDER BY station_m'), dtype=np.float64)

    @staticmethod
    def read_csv(path: Path) -> tuple[bytes, list[list[str]]]:
        data = path.read_bytes()
        return data, [line.split(";") for line in data.decode("utf-8-sig").split("\r\n") if line]

    def test_a_the_csv_has_one_row_per_station_with_the_registered_values_within_1e_9_and_the_slope_in_percent(self) -> None:
        """RF-017-27, T27-a: el CSV tiene los títulos con su unidad y **una fila por estación** del eje (abscisa, x, y, cota del terreno, cota de la rasante y pendiente) con lo registrado **a ≤ 10⁻⁹**
        (con coma decimal: el mismo float64) y la pendiente de cada tramo, **en %**, la que dan sus dos cotas; UTF-8 con BOM, «;» y CRLF."""
        target = self.out / "rasante.csv"
        found = export.export_road_csv(self.project, ROAD, target, version=self.v1.uid, read_only=NO_READ_ONLY, overwrite=True)
        data, rows = self.read_csv(found)
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(rows[0], list(export.CSV_COLUMNS))
        values = np.array([[float(cell.replace(",", ".")) for cell in row] for row in rows[1:]])
        wanted = self.axis()
        self.assertEqual(values.shape, wanted.shape)
        self.assertLessEqual(float(np.abs(values - wanted).max()), 1e-9)
        slope = np.diff(values[:, 4]) / np.diff(values[:, 0]) * 100.0
        self.assertLessEqual(float(np.abs(slope - values[:-1, 5]).max()), 1e-9)
        self.assertAlmostEqual(float(values[-1, 0]), float(self.query("SELECT value FROM gb_figure WHERE key = 'des.road_length_m' ORDER BY fid DESC")[0][0]), delta=1e-9)

    def test_b_exporting_writes_nothing_in_the_project_and_the_same_again_gives_the_same_bytes(self) -> None:
        """RF-017-27, D-29 de la 011: exportar **no modifica nada del proyecto** (ni la base —su contador de cambios—, ni las operaciones, los datos o los ficheros) y no deja temporal; con ``overwrite`` se
        sustituye con los mismos bytes."""
        target = self.out / "otra_rasante.csv"
        before = self.snapshot()
        export.export_road_csv(self.project, ROAD, target, version=self.v1.uid, read_only=NO_READ_ONLY)
        first = target.read_bytes()
        self.assertEqual(self.snapshot(), before)
        export.export_road_csv(self.project, ROAD, target, version=self.v1.code, read_only=NO_READ_ONLY, overwrite=True)
        self.assertEqual(target.read_bytes(), first)
        self.assertEqual(sorted(path.name for path in self.out.glob("*.tmp")), [])

    def test_c_the_refusals_write_nothing(self) -> None:
        """RF-017-27, RF-008-15: una pista que no está calculada en la versión (``des.export_road_unknown``), el destino que existe sin ``overwrite``, una extensión que no es un CSV y un destino dentro
        del proyecto fuera de ``exports/`` se rechazan **sin escribir nada**."""
        target = self.out / "ya_existe.csv"
        target.write_bytes(b"lo que hubiera")
        before = self.snapshot()
        cases = (
            (lambda: export.export_road_csv(self.project, "Pista que no existe", self.out / "x.csv", version=self.v1.uid, read_only=NO_READ_ONLY), messages.DesignError, "des.export_road_unknown"),
            (lambda: export.export_road_csv(self.project, ROAD, target, version=self.v1.uid, read_only=NO_READ_ONLY), gis_messages.GisError, "gis.export_target_exists"),
            (lambda: export.export_road_csv(self.project, ROAD, self.out / "rasante.tif", version=self.v1.uid, read_only=NO_READ_ONLY), gis_messages.GisError, "gis.export_extension_invalid"),
            (lambda: export.export_road_csv(self.project, ROAD, Path(self.root) / "rasante.csv", version=self.v1.uid, read_only=NO_READ_ONLY), gis_messages.GisError, "gis.export_inside_project"),
        )
        for work, kind, code in cases:
            with self.subTest(code), self.assertRaises(kind) as caught:
                work()
            self.assertEqual(caught.exception.code, code)
            for text in (caught.exception.text, caught.exception.text_in("en") if hasattr(caught.exception, "text_in") else ""):
                self.assertNotIn("{", text)
        self.assertEqual(target.read_bytes(), b"lo que hubiera")
        self.assertEqual(self.snapshot(), before)
        with self.assertRaises(Exception) as unknown:
            export.export_road_csv(self.project, ROAD, self.out / "y.csv", version="V99", read_only=NO_READ_ONLY)
        self.assertEqual(unknown.exception.code, "core.version_unknown")


if __name__ == "__main__":
    import unittest

    unittest.main()

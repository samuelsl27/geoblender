# SPDX-License-Identifier: GPL-3.0-or-later
"""Datos sintéticos de la spec 006 en ``tests/data/gis/`` (T01; plan 006 §7.1).

Los leen las pruebas de RF-006-08, RF-006-09 y RF-006-24 (GeoTIFF, ASC y XYZ), RF-006-10
(entradas intactas) y RF-006-12 a RF-006-14 (puntos, roturas y capas). Lo que se comprueba
aquí es que son los mismos ficheros que generaron las órdenes de GDAL del ``README.md``:

- cada fichero de datos está en la tabla del ``README.md`` con su sha256, y ese sha256
  coincide; la tabla no nombra ficheros que no existen;
- cada GeoTIFF y el GeoPackage aparecen en una orden de GDAL del ``README.md``, que
  también da la fórmula de la superficie;
- el GeoPackage está en el diario clásico (bytes 18 y 19 de la cabecera de SQLite a 1,
  nunca 2, que es WAL) y no hay ``-wal``, ``-shm``, ``-journal`` ni ``.aux.xml``.

Lo que no se versiona (el CSV en Latin-1, el GeoPackage con WAL pendiente y los datos
grandes de rendimiento) lo generan las pruebas que lo usan en la carpeta temporal.
"""

import hashlib
import re
import unittest
from pathlib import Path

from tests.support.repo import ROOT

DATA = ROOT / "tests" / "data" / "gis"
README = DATA / "README.md"
# Lo que no es un dato: la descripción, el generador y el paquete que permite ejecutarlo
# con «-m» (TST-01).
NOT_DATA = frozenset({"README.md", "make_gis_data.py", "__init__.py"})
# Una fila de la tabla de ficheros: | `ruta` | … | `sha256` |
ROW = re.compile(r"^\| `(?P<path>[^`]+)` \|.*\| `(?P<sha>[0-9a-f]{64})` \|\s*$")
# Una orden de GDAL del README: & "$GDAL\gdal_translate.exe" … o & "$GDAL\ogr2ogr.exe" …
COMMAND = re.compile(r'^& "\$GDAL\\(?P<tool>gdal_translate|ogr2ogr)\.exe" (?P<args>.*)$')
FORMULA = "800 + 0,5·x − 0,25·y + 3·sin(x/7)"
SQLITE_MAGIC = b"SQLite format 3\x00"
SIDECARS = ("-wal", "-shm", "-journal", ".aux.xml")


def _readme_text() -> str:
    return README.read_text(encoding="utf-8")


def _listed() -> dict[str, str]:
    """Las filas de la tabla de ficheros del README: ruta relativa → sha256."""
    rows: dict[str, str] = {}
    for line in _readme_text().splitlines():
        match = ROW.match(line)
        if match:
            rows[match["path"]] = match["sha"]
    return rows


def _data_files() -> list[str]:
    """Los ficheros de datos de ``tests/data/gis/`` (rutas relativas con «/»)."""
    return sorted(
        path.relative_to(DATA).as_posix()
        for path in DATA.rglob("*")
        if path.is_file() and path.name not in NOT_DATA and "__pycache__" not in path.parts
    )


def _commands() -> list[tuple[str, str]]:
    """Las órdenes de GDAL del README: (programa, argumentos)."""
    found: list[tuple[str, str]] = []
    for line in _readme_text().splitlines():
        match = COMMAND.match(line.strip())
        if match:
            found.append((match["tool"], match["args"]))
    return found


class GisDataTestCase(unittest.TestCase):
    """Los datos de ``tests/data/gis/`` y su ``README.md``."""

    def test_every_file_listed_with_matching_sha256(self) -> None:
        """RF-006-08, RF-006-09, RF-006-12 (datos de T01): cada fichero de datos está en la
        tabla del README y su sha256 coincide con el de la tabla."""
        listed = _listed()
        files = _data_files()
        self.assertTrue(files, f"no hay datos en {DATA}")
        self.assertEqual(sorted(listed), files, "la tabla del README y la carpeta difieren")
        for rel in files:
            with self.subTest(fichero=rel):
                digest = hashlib.sha256((DATA / rel).read_bytes()).hexdigest()
                self.assertEqual(digest, listed[rel])

    def test_plan_data_present(self) -> None:
        """RF-006-08, RF-006-09, RF-006-12 (datos de T01): están las cinco carpetas de
        ``plan.md`` §7.1 y los casos que nombran sus tareas (T05, T06, T08, T09, T15)."""
        files = set(_data_files())
        for rel in (
            "geotiff/f32_strip.tif",
            "geotiff/f64_strip.tif",
            "geotiff/i16_strip.tif",
            "geotiff/i16_strip_lzw_p2.tif",
            "geotiff/f32_strip_packbits.tif",
            "geotiff/f32_strip_deflate_p3_05m.tif",
            "geotiff/f32_tile.tif",
            "geotiff/f32_tile_sparse.tif",
            "geotiff/f32_bigtiff.tif",
            "geotiff/f32_pixelispoint.tif",
            "geotiff/f32_epsg23030.tif",
            "geotiff/u8_jpeg.tif",
            "geotiff/f32_rotated.tif",
            "asc/corner.asc",
            "asc/corner.prj",
            "asc/center.asc",
            "asc/dxdy.asc",
            "xyz/grid.xyz",
            "xyz/grid_hole.xyz",
            "xyz/irregular.xyz",
            "points/taludes.csv",
            "points/errores.csv",
            "gpkg/capas.gpkg",
        ):
            with self.subTest(fichero=rel):
                self.assertIn(rel, files)

    def test_readme_gives_formula_and_gdal_commands(self) -> None:
        """RF-006-08 (datos de T01): el README da la fórmula de la superficie y cada
        GeoTIFF y GeoPackage sale de una orden de GDAL (``gdal_translate``, ``ogr2ogr``)."""
        self.assertIn(FORMULA, _readme_text())
        commands = _commands()
        self.assertTrue(commands, "el README no tiene órdenes de GDAL")
        made = " ".join(args for _tool, args in commands)
        for rel in _data_files():
            if rel.endswith((".tif", ".gpkg")):
                with self.subTest(fichero=rel):
                    self.assertIn(rel.replace("/", "\\"), made)

    def test_geopackage_in_rollback_journal(self) -> None:
        """RF-006-10 (datos de T01): ningún GeoPackage versionado está en WAL (bytes 18 y
        19 de la cabecera de SQLite = 1) ni tiene ficheros de diario al lado."""
        gpkgs = sorted(DATA.rglob("*.gpkg"))
        self.assertTrue(gpkgs, "no hay GeoPackage en los datos")
        for path in gpkgs:
            with self.subTest(fichero=path.name):
                header = path.read_bytes()[:100]
                self.assertEqual(header[:16], SQLITE_MAGIC)
                self.assertEqual((header[18], header[19]), (1, 1))

    def test_no_sidecar_files(self) -> None:
        """RF-006-10 (datos de T01): GDAL no dejó ``.aux.xml`` ni ficheros de diario."""
        for path in DATA.rglob("*"):
            with self.subTest(fichero=path.name):
                self.assertFalse(path.name.endswith(SIDECARS), path.name)


if __name__ == "__main__":
    unittest.main()

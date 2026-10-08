# SPDX-License-Identifier: GPL-3.0-or-later
"""Lector de ESRI ASCII Grid (spec 006, T08; plan 006 §5.3.2, §5.3.6 y §5.4 A5).

- **RF-006-08** (importar un MDT con cada cota igual a la de la fuente): los ASC de
  ``tests/data/gis/asc/`` (T01) se leen con la rejilla que declaran —``xllcorner`` es el
  borde; ``xllcenter``, el centro de la celda inferior izquierda (esquina = centro − medio
  paso, como GDAL); ``cellsize`` o ``dx`` y ``dy`` (celdas no cuadradas, con área
  \\|dx·dy\\|, RF-006-02)— y cada cota es, bit a bit, el float64 de su texto; el
  ``NODATA_value`` declarado, NaN. Las variantes de la cabecera (mayúsculas, CRLF, BOM,
  tabuladores, líneas en blanco, valores repartidos en cualquier número de líneas) dan lo
  mismo, y el resultado no depende del tamaño de los trozos que se leen.
- **RF-006-04** (no suponer el CRS): con ``.prj``, su WKT se identifica con el puerto
  ``CrsService.identify_wkt`` (pyproj, T11); sin ``.prj``, sin servicio o sin
  identificar, ``declared_crs = None`` (con una nota si hay ``.prj``); la referencia
  vertical nunca la declara un ASC (``None``).
- **RF-006-09** (rechazar con fichero, característica, valor y qué hacer, sin importar
  nada): cabecera incompleta o incoherente, un valor que no es un número (con su fila y su
  columna), menos o más valores que ``ncols · nrows``, más celdas que
  ``gis.import.max_cells`` y ningún dato.
- **RF-006-10** (no tocar la entrada): leer no cambia el listado de la carpeta ni la fecha
  de ningún fichero.

Avance y cancelación por trozos (RF-006-28). Con ``GEOBLENDER_QGIS_DIR``, el GDAL de QGIS
da la misma georreferencia y los mismos bits (si no, omisión ``[ENTORNO] qgis``).
"""

import json
import math
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from tests.support import qgis
from tests.support.package import import_geoblender
from tests.support.repo import ROOT
from tests.support.resources import requires

gis = import_geoblender("gis")
asc = import_geoblender("gis.asc")
messages = import_geoblender("gis.messages")
params = import_geoblender("gis.params")
georef = import_geoblender("core.georef")
worker_api = import_geoblender("jobs.worker_api")

ASC = ROOT / "tests" / "data" / "gis" / "asc"
CATALOG = georef.load_catalog()
WEST, NORTH_1M, NORTH_05M = 700000.0, 4400048.0, 4400024.0
NROWS, NCOLS = 48, 64
HOLE = (slice(20, 23), slice(30, 34))  # filas 20–22 y columnas 30–33 desde el NO
REF_E, REF_N = 700000.0, 4400000.0


def _tokens_of(path: Path, header_lines: int) -> np.ndarray:
    """Las cotas de un ASC leídas aquí, sin el lector: cada texto con ``float`` (el
    float64 más próximo), en filas de norte a sur, con −9999 como NaN."""
    lines = path.read_text(encoding="ascii").splitlines()[header_lines:]
    values = np.array([float(token) for line in lines for token in line.split()])
    values[values == -9999.0] = np.nan
    return values.reshape(NROWS, NCOLS)


def _same(test: unittest.TestCase, got: np.ndarray, expected: np.ndarray) -> None:
    """Iguales bit a bit, con NaN en las mismas celdas."""
    test.assertEqual(got.dtype, np.float64)
    test.assertEqual(got.shape, expected.shape)
    nan = np.isnan(expected)
    test.assertTrue(np.array_equal(np.isnan(got), nan))
    test.assertTrue(np.array_equal(got[~nan].view(np.uint64), expected[~nan].view(np.uint64)))


def _grid_tuple(grid: object) -> tuple:
    return (grid.west, grid.north, grid.dx, grid.dy, grid.ncols, grid.nrows)


class _FakeCrsService:
    """``CrsService`` falso: solo ``identify_wkt``, que apunta lo que recibe."""

    def __init__(self, result: object) -> None:
        self.result = result
        self.seen: list[str] = []

    def identify_wkt(self, wkt: str) -> object:
        self.seen.append(wkt)
        return self.result


_CACHE: dict[str, object] = {}


def _read(name: str) -> object:
    """Un ASC de T01 leído una vez, sin servicio de CRS."""
    if name not in _CACHE:
        _CACHE[name] = asc.read_asc(ASC / name)
    return _CACHE[name]


# --- Los ficheros de T01 -----------------------------------------------------------------


class ReadDataFilesTest(unittest.TestCase):
    """RF-006-08, RF-006-04 y RF-006-10 con los ASC de ``tests/data/gis/asc/``."""

    def test_corner_grid_and_exact_values(self) -> None:
        """RF-006-08: ``xllcorner``/``yllcorner`` y ``cellsize`` 1 → oeste 700 000, norte
        4 400 048 (= 4 400 000 + 48 · 1), 64 × 48; cada cota, el float64 de su texto
        (bit a bit), a ≤ 0,0005 m de la fórmula del README; el hueco (−9999), NaN."""
        source = _read("corner.asc")
        self.assertEqual(_grid_tuple(source.grid), (WEST, NORTH_1M, 1.0, 1.0, NCOLS, NROWS))
        self.assertEqual(source.grid.cell_area, 1.0)
        _same(self, source.values, _tokens_of(ASC / "corner.asc", 6))
        self.assertEqual(source.nodata_value, -9999.0)
        self.assertEqual(source.source_dtype, "float64")
        self.assertFalse(source.pixel_is_point)
        nan = np.isnan(source.values)
        self.assertTrue(nan[HOLE].all())
        self.assertEqual(int(nan.sum()), 12)
        x = (WEST - REF_E) + np.arange(NCOLS) + 0.5
        y = (NORTH_1M - REF_N) - np.arange(NROWS) - 0.5
        sines = np.array([math.sin(value / 7.0) for value in x.tolist()])
        z = 800.0 + 0.5 * x[None, :] - 0.25 * y[:, None] + 3.0 * sines[None, :]
        self.assertLessEqual(float(np.max(np.abs(source.values[~nan] - z[~nan]))),
                             0.0005 + 1e-9)

    def test_center_is_the_same_grid(self) -> None:
        """RF-006-08: ``xllcenter``/``yllcenter`` (700 000,5; 4 400 000,5) → esquina =
        centro − medio paso: la misma rejilla y las mismas cotas que ``corner.asc``; la
        fuente referencia centros (``pixel_is_point``), sin aviso (spec §8)."""
        center, corner = _read("center.asc"), _read("corner.asc")
        self.assertTrue(center.grid.same_geometry(corner.grid))
        _same(self, center.values, corner.values)
        self.assertTrue(center.pixel_is_point)
        self.assertEqual(center.notes, ())

    def test_dx_dy_non_square_cells(self) -> None:
        """RF-006-08, RF-006-02: ``dx`` 1 y ``dy`` 0,5 → norte 4 400 024 (= 4 400 000 +
        48 · 0,5) y celdas de 1 × 0,5 con área 0,5 m²; cotas bit a bit."""
        source = _read("dxdy.asc")
        self.assertEqual(_grid_tuple(source.grid), (WEST, NORTH_05M, 1.0, 0.5, NCOLS, NROWS))
        self.assertEqual(source.grid.cell_area, 0.5)
        _same(self, source.values, _tokens_of(ASC / "dxdy.asc", 7))

    def test_prj_identified_by_the_crs_service(self) -> None:
        """RF-006-04: con ``corner.prj``, ``identify_wkt`` recibe su WKT tal cual y lo que
        devuelve (EPSG:25830) es el CRS declarado; sin nota. La referencia vertical no la
        declara un ASC."""
        service = _FakeCrsService(CATALOG.horizontal(25830))
        source = asc.read_asc(ASC / "corner.asc", crs_service=service)
        self.assertEqual(service.seen, [(ASC / "corner.prj").read_text(encoding="ascii")])
        self.assertEqual(source.declared_crs, CATALOG.horizontal(25830))
        self.assertIsNone(source.declared_vertical)
        self.assertEqual(source.notes, ())

    def test_prj_not_identified(self) -> None:
        """RF-006-04: con ``.prj`` pero sin servicio de CRS, o si el servicio no lo
        identifica (``None``), ``declared_crs = None`` y una nota que pide declararlo."""
        note = messages.render("gis.prj_unidentified", file="corner.asc", prj="corner.prj")
        self.assertIn("corner.prj", note)
        unknown = _FakeCrsService(None)
        for source in (_read("corner.asc"),
                       asc.read_asc(ASC / "corner.asc", crs_service=unknown)):
            self.assertIsNone(source.declared_crs)
            self.assertIsNone(source.declared_vertical)
            self.assertEqual(source.notes, (note,))
        self.assertEqual(len(unknown.seen), 1)

    def test_without_prj_nothing_is_declared(self) -> None:
        """RF-006-04: sin ``.prj``, ``declared_crs = None`` sin nota, y el servicio de
        CRS no se usa: nunca se supone un CRS."""
        service = _FakeCrsService(CATALOG.horizontal(25830))
        for name in ("center.asc", "dxdy.asc"):
            with self.subTest(name=name):
                source = asc.read_asc(ASC / name, crs_service=service)
                self.assertIsNone(source.declared_crs)
                self.assertIsNone(source.declared_vertical)
                self.assertEqual(source.notes, ())
        self.assertEqual(service.seen, [])

    def test_encoding_describes_the_file(self) -> None:
        """El informe dice cómo está escrito el fichero."""
        corner = _read("corner.asc").encoding
        for text in ("ESRI ASCII Grid", "ASCII", "xllcorner", "cellsize"):
            self.assertIn(text, corner)
        self.assertIn("xllcenter", _read("center.asc").encoding)
        self.assertIn("dx", _read("dxdy.asc").encoding)

    def test_input_untouched(self) -> None:
        """RF-006-10: leer los tres ASC (con y sin servicio de CRS) no cambia el listado de
        la carpeta ni la fecha de modificación de ningún fichero."""

        def snapshot() -> dict[str, int]:
            return {entry.name: entry.stat().st_mtime_ns for entry in os.scandir(ASC)}

        before = snapshot()
        service = _FakeCrsService(CATALOG.horizontal(25830))
        for name in ("corner.asc", "center.asc", "dxdy.asc"):
            asc.read_asc(ASC / name)
            asc.read_asc(ASC / name, crs_service=service)
        self.assertEqual(snapshot(), before)

    def test_progress_and_cancel(self) -> None:
        """RF-006-28: con trozos de 4 KiB, avance tras cada trozo, creciente hasta 1; si
        se cancela en el 3.º, para con ``JobCancelled`` y no devuelve nada."""
        seen: list[float] = []
        with mock.patch.object(asc, "CHUNK_BYTES", 4096):
            asc.read_asc(ASC / "corner.asc", progress=lambda frac, text: seen.append(frac))
            self.assertGreaterEqual(len(seen), 5)
            self.assertEqual(seen, sorted(seen))
            self.assertEqual(seen[-1], 1.0)
            calls = []

            def cancelled() -> bool:
                calls.append(1)
                return len(calls) > 2

            with self.assertRaises(worker_api.JobCancelled) as caught:
                asc.read_asc(ASC / "corner.asc", cancelled=cancelled)
        self.assertIn(f"3 de {len(seen)}", str(caught.exception))

    def test_chunk_size_does_not_change_the_result(self) -> None:
        """RF-006-08: con trozos de 7, 61 y 4096 bytes (cortando números por la mitad)
        las cotas son las mismas, bit a bit."""
        expected = _read("corner.asc").values
        for size in (7, 61, 4096):
            with self.subTest(trozo=size), mock.patch.object(asc, "CHUNK_BYTES", size):
                _same(self, asc.read_asc(ASC / "corner.asc").values, expected)

    def test_cell_limit(self) -> None:
        """RF-006-09: 64 × 48 = 3072 celdas > 3071 se rechaza con el número de celdas y
        el límite; con 3072, se lee. Sin ``max_cells``, el límite es
        ``gis.import.max_cells``, leído al leer."""
        with self.assertRaises(gis.GisError) as caught:
            asc.read_asc(ASC / "corner.asc", max_cells=3071)
        error = caught.exception
        self.assertEqual((error.code, error.value, error.obj), ("gis.raster_too_large", 3072,
                                                                "corner.asc"))
        self.assertEqual((error.values["file"], error.values["limit"]), ("corner.asc", 3071))
        self.assertEqual(asc.read_asc(ASC / "corner.asc", max_cells=3072).grid.ncols, NCOLS)
        real = params.default

        def small(key: str) -> object:
            return 3000 if key == "gis.import.max_cells" else real(key)

        with mock.patch.object(params, "default", side_effect=small):
            with self.assertRaises(gis.GisError) as caught:
                asc.read_asc(ASC / "corner.asc")
        self.assertEqual(caught.exception.values["limit"], 3000)


# --- Ficheros escritos en la prueba ------------------------------------------------------

BASE_HEADER = (
    "ncols 3",
    "nrows 2",
    "xllcorner 700000",
    "yllcorner 4400000",
    "cellsize 2",
    "NODATA_value -9999",
)
BASE_BODY = "801.5 802.25 -9999\n803 804.125 805\n"
BASE_VALUES = np.array([[801.5, 802.25, np.nan], [803.0, 804.125, 805.0]])
# Centro con decimales en los que el orden de las operaciones cambia el norte.
ODD_HEADER = ("ncols 3", "nrows 2", "xllcenter 700000.123", "yllcenter 10.4", "dx 0.3",
              "dy 1.44", "NODATA_value -9999")


class ReadBuiltFilesTest(unittest.TestCase):
    """RF-006-04, RF-006-08 y RF-006-09 con ASC pequeños escritos aquí."""

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="gb-asc-"))
        self.addCleanup(shutil.rmtree, self.folder, True)

    def _write(self, header: tuple[str, ...] = BASE_HEADER, body: str = BASE_BODY, *,
               name: str = "m.asc", newline: str = "\n", prefix: bytes = b"") -> Path:
        path = self.folder / name
        text = newline.join(header) + newline + body.replace("\n", newline)
        path.write_bytes(prefix + text.encode("ascii"))
        return path

    def _rejected(self, path: Path, code: str) -> object:
        with self.assertRaises(gis.GisError) as caught:
            asc.read_asc(path)
        error = caught.exception
        self.assertEqual(error.code, code)
        self.assertEqual(error.obj, path.name)
        self.assertEqual(error.values["file"], path.name)
        self.assertIn(f"«{path.name}»", str(error))
        return error

    def test_base_file(self) -> None:
        """RF-006-08: 3 × 2 celdas de 2 m: oeste 700 000, norte 4 400 004; −9999, NaN."""
        source = asc.read_asc(self._write())
        self.assertEqual(_grid_tuple(source.grid), (WEST, 4400004.0, 2.0, 2.0, 3, 2))
        _same(self, source.values, BASE_VALUES)
        self.assertEqual(source.nodata_value, -9999.0)
        self.assertIsNone(source.declared_crs)

    def test_header_and_layout_variants(self) -> None:
        """RF-006-08: claves en mayúsculas o mezcladas, CRLF, BOM UTF-8, tabuladores, líneas
        en blanco y los valores en una línea o uno por línea dan lo mismo."""
        upper = tuple(line.upper() if i % 2 else line.title() for i, line in
                      enumerate(BASE_HEADER))
        tabs = tuple(line.replace(" ", "\t") for line in BASE_HEADER)
        blank = (*BASE_HEADER[:3], "", "  ", *BASE_HEADER[3:])
        variants = {
            "mayusculas": self._write(upper, name="a.asc"),
            "crlf": self._write(newline="\r\n", name="b.asc"),
            "bom": self._write(prefix=b"\xef\xbb\xbf", name="c.asc"),
            "tabuladores": self._write(tabs, BASE_BODY.replace(" ", "\t"), name="d.asc"),
            "en_blanco": self._write(blank, name="e.asc"),
            "una_linea": self._write(body=BASE_BODY.replace("\n", " "), name="f.asc"),
            "uno_por_linea": self._write(body=BASE_BODY.replace(" ", "\n"), name="g.asc"),
        }
        for label, path in variants.items():
            with self.subTest(variante=label):
                source = asc.read_asc(path)
                self.assertEqual(_grid_tuple(source.grid), (WEST, 4400004.0, 2.0, 2.0, 3, 2))
                _same(self, source.values, BASE_VALUES)
        self.assertIn("BOM", asc.read_asc(variants["bom"]).encoding)

    def test_values_are_the_float64_of_their_text(self) -> None:
        """RF-006-08: 17 cifras, exponentes, signo y punto sin cifras: cada cota es
        ``float(texto)`` bit a bit, sin redondeo adicional."""
        texts = ["812.34567890123456", "-1.5e2", "+7.", ".25", "4.4000004560000001e6",
                 "1234.000000000000227"]
        header = ("ncols 3", "nrows 2", "xllcorner 0", "yllcorner 0", "cellsize 1")
        source = asc.read_asc(self._write(header, " ".join(texts) + "\n"))
        expected = np.array([float(text) for text in texts]).reshape(2, 3)
        _same(self, source.values, expected)

    def test_nodata_variants(self) -> None:
        """RF-006-08: sin ``NODATA_value``, −9999 es una cota (``nodata_value = None``);
        ``-9999.0`` en el cuerpo es el sin dato ``-9999``; ``nan`` declarado o en el cuerpo,
        NaN."""
        without = asc.read_asc(self._write(BASE_HEADER[:5], name="a.asc"))
        self.assertIsNone(without.nodata_value)
        self.assertEqual(without.values[0, 2], -9999.0)
        decimal = asc.read_asc(self._write(body=BASE_BODY.replace("-9999", "-9999.000"),
                                           name="b.asc"))
        _same(self, decimal.values, BASE_VALUES)
        nan_header = (*BASE_HEADER[:5], "NODATA_value nan")
        declared_nan = asc.read_asc(self._write(nan_header, BASE_BODY.replace("-9999", "nan"),
                                                name="c.asc"))
        self.assertTrue(math.isnan(declared_nan.nodata_value))
        _same(self, declared_nan.values, BASE_VALUES)

    def test_center_with_decimals_follows_gdal(self) -> None:
        """RF-006-08: con ``xllcenter`` 700 000,123, ``yllcenter`` 10,4, ``dx`` 0,3 y
        ``dy`` 1,44, oeste = x − 0,5·dx y norte = (y − 0,5·dy) + nrows·dy, en ese orden
        (el de GDAL): 12,559999999999999, y no 12,56 como daría (y + nrows·dy) − 0,5·dy;
        área |dx·dy|."""
        source = asc.read_asc(self._write(ODD_HEADER))
        north = (10.4 - 0.5 * 1.44) + 2 * 1.44
        self.assertEqual(north, 12.559999999999999)
        self.assertNotEqual(north, (10.4 + 2 * 1.44) - 0.5 * 1.44)
        self.assertEqual(_grid_tuple(source.grid),
                         (700000.123 - 0.5 * 0.3, north, 0.3, 1.44, 3, 2))
        self.assertEqual(source.grid.cell_area, abs(0.3 * 1.44))
        self.assertTrue(source.pixel_is_point)

    def test_header_rejected(self) -> None:
        """RF-006-09: cabecera incompleta o incoherente → ``gis.asc_header_invalid`` con
        la clave (campo), el texto hallado (valor) y el motivo, sin leer nada."""
        base = list(BASE_HEADER)

        def without(key: str) -> tuple[str, ...]:
            return tuple(line for line in base if not line.lower().startswith(key))

        def replaced(key: str, line: str) -> tuple[str, ...]:
            return tuple(line if old.lower().startswith(key) else old for old in base)

        cases = {
            "sin_ncols": (without("ncols"), "ncols", None, "falta «ncols»"),
            "ncols_decimal": (replaced("ncols", "ncols 3.5"), "ncols", "3.5",
                              "no es un número entero positivo"),
            "nrows_cero": (replaced("nrows", "nrows 0"), "nrows", "0",
                           "no es un número entero positivo"),
            "sin_xll": (without("xllcorner"), "xllcorner", None,
                        "falta «xllcorner» o «xllcenter»"),
            "sin_yll": (without("yllcorner"), "yllcorner", None,
                        "falta «yllcorner» o «yllcenter»"),
            "xll_texto": (replaced("xllcorner", "xllcorner abc"), "xllcorner", "abc",
                          "no es un número finito"),
            "yll_infinito": (replaced("yllcorner", "yllcorner inf"), "yllcorner", "inf",
                             "no es un número finito"),
            "paso_cero": (replaced("cellsize", "cellsize 0"), "cellsize", "0",
                          "no es un paso positivo"),
            "paso_negativo": (replaced("cellsize", "cellsize -2"), "cellsize", "-2",
                              "no es un paso positivo"),
            "sin_paso": (without("cellsize"), "cellsize", None,
                         "falta «cellsize» o «dx» y «dy»"),
            "solo_dx": ((*without("cellsize"), "dx 2"), "dy", None, "falta «dy»"),
            "paso_doble": ((*base, "dx 2", "dy 2"), "cellsize", "2",
                           "«cellsize» y «dx» o «dy» a la vez"),
            "esquina_y_centro": (replaced("yllcorner", "yllcenter 4400001"), "yllcenter",
                                 "4400001", "mezcla esquina y centro"),
            "x_doble": ((*base[:3], "xllcenter 700001", *base[3:]), "xllcenter", "700001",
                        "«xllcorner» y «xllcenter» a la vez"),
            "repetida": ((*base, "NCOLS 3"), "ncols", "3", "«ncols» está dos veces"),
            "desconocida": ((*base, "byteorder lsbfirst"), "byteorder", "lsbfirst",
                            "no es una clave de ESRI ASCII Grid"),
            "dos_valores": (replaced("ncols", "ncols 3 4"), "ncols", "3 4",
                            "una clave y un valor"),
            "nodata_texto": (replaced("nodata_value", "NODATA_value none"), "NODATA_value",
                             "none", "no es un número"),
        }
        for label, (header, field, value, detail) in cases.items():
            with self.subTest(caso=label):
                error = self._rejected(self._write(header, name=f"{label}.asc"),
                                       "gis.asc_header_invalid")
                self.assertEqual(error.field, field)
                self.assertEqual(error.value, value)
                self.assertIn(detail, str(error))

    def test_long_header_values(self) -> None:
        """RF-006-08, RF-006-09: un valor de cabecera de más de 40 caracteres se lee
        entero; si no es válido, el mensaje lo muestra cortado con «…»."""
        long_x = "700000." + "0" * 60 + "1"
        header = tuple(f"xllcorner {long_x}" if line.startswith("xllcorner") else line
                       for line in BASE_HEADER)
        self.assertEqual(asc.read_asc(self._write(header, name="largo.asc")).grid.west,
                         float(long_x))
        bad = tuple(f"xllcorner {long_x}x" if line.startswith("xllcorner") else line
                    for line in BASE_HEADER)
        error = self._rejected(self._write(bad, name="malo.asc"), "gis.asc_header_invalid")
        self.assertEqual(len(error.value), 40)
        self.assertTrue(error.value.endswith("…"))
        self.assertNotIn(long_x, str(error))

    def test_not_an_ascii_grid(self) -> None:
        """RF-006-09: un fichero vacío (falta «ncols») o binario (un GeoTIFF con otra
        extensión) se rechaza como cabecera no válida."""
        empty = self.folder / "vacio.asc"
        empty.write_bytes(b"")
        self.assertEqual(self._rejected(empty, "gis.asc_header_invalid").field, "ncols")
        binary = self.folder / "binario.asc"
        tif = ROOT / "tests" / "data" / "gis" / "geotiff" / "f32_strip.tif"
        binary.write_bytes(tif.read_bytes())
        error = self._rejected(binary, "gis.asc_header_invalid")
        self.assertIn("no es texto ASCII", str(error))

    def test_value_count_rejected(self) -> None:
        """RF-006-09: 5 o 7 valores con ``ncols · nrows`` = 6 → ``gis.asc_value_count`` con
        los hallados y los esperados; un cuerpo vacío, 0."""
        cases = {"menos": ("801.5 802.25 -9999\n803 804.125\n", 5),
                 "mas": (BASE_BODY + "806\n", 7),
                 "vacio": ("", 0)}
        for label, (body, found) in cases.items():
            with self.subTest(caso=label):
                error = self._rejected(self._write(body=body, name=f"{label}.asc"),
                                       "gis.asc_value_count")
                self.assertEqual(error.value, found)
                self.assertEqual(error.values["expected"], 6)
                self.assertIn(f"tiene {found} valores", str(error))

    def test_value_not_a_number_rejected(self) -> None:
        """RF-006-09: un valor que no es un número (coma decimal, dos puntos, dos números
        pegados) → ``gis.asc_value_invalid`` con su texto, su fila y su columna desde la
        esquina noroeste, también si cae en el corte entre dos trozos."""
        cases = {
            "coma": ("801,5 802.25 -9999\n803 804.125 805\n", "801,5", 1, 1),
            "dos_puntos": ("801.5 802.25 -9999\n803 1.5.3 805\n", "1.5.3", 2, 2),
            "pegados": ("801.5 802.25 -9999\n803 804.125 805-1\n", "805-1", 2, 3),
        }
        for label, (body, value, row, column) in cases.items():
            for size in (5, 1 << 20):
                with self.subTest(caso=label, trozo=size), \
                        mock.patch.object(asc, "CHUNK_BYTES", size):
                    error = self._rejected(self._write(body=body, name=f"{label}.asc"),
                                           "gis.asc_value_invalid")
                    self.assertEqual(error.value, value)
                    self.assertEqual((error.values["row"], error.values["column"]),
                                     (row, column))
                    self.assertIn(f"«{value}»", str(error))

    def test_all_nodata_rejected(self) -> None:
        """RF-006-09: sin ninguna celda con dato → ``gis.raster_empty``."""
        body = "-9999 -9999 -9999\n-9999 -9999 -9999\n"
        self._rejected(self._write(body=body), "gis.raster_empty")


# --- GDAL de QGIS (opcional) -------------------------------------------------------------


# Con el Python de QGIS: la georreferencia (``repr`` exacto en JSON; ``gdalinfo -json``
# escribe 16 cifras y no distingue 12,559999999999999 de 12,56), *Area*/*Point*, el nombre
# del CRS y las cotas en Float64 (en hexadecimal).
_GDAL_CODE = """
import json, sys
from osgeo import gdal
gdal.UseExceptions()
gdal.SetConfigOption("AAIGRID_DATATYPE", "Float64")
found = {}
for path in sys.argv[1:]:
    ds = gdal.Open(path)
    srs = ds.GetSpatialRef()
    found[path] = {
        "transform": list(ds.GetGeoTransform()),
        "size": [ds.RasterXSize, ds.RasterYSize],
        "point": ds.GetMetadataItem("AREA_OR_POINT"),
        "crs": None if srs is None else srs.GetName(),
        "values": ds.GetRasterBand(1).ReadRaster(buf_type=gdal.GDT_Float64).hex(),
    }
    ds = None
print(json.dumps(found))
"""


@requires(qgis.QGIS, qgis.QGIS_HINT)
class GdalReadsTheSameTest(unittest.TestCase):
    """RF-006-08: el GDAL de QGIS lee los ASC con la misma georreferencia y los mismos
    valores (con ``AAIGRID_DATATYPE=Float64``)."""

    NAMES = ("corner.asc", "center.asc", "dxdy.asc", "odd.asc")

    @classmethod
    def setUpClass(cls) -> None:
        folder = Path(tempfile.mkdtemp(prefix="gb-ascg-"))
        cls.addClassCleanup(shutil.rmtree, folder, True)
        for name in ("corner.asc", "corner.prj", "center.asc", "dxdy.asc"):
            shutil.copyfile(ASC / name, folder / name)
        (folder / "odd.asc").write_text("\n".join(ODD_HEADER) + "\n" + BASE_BODY,
                                        encoding="ascii")
        cls.folder = folder
        cls.result = qgis.run_python("-c", _GDAL_CODE, *(str(folder / n) for n in cls.NAMES))

    def _found(self) -> dict[str, dict]:
        self.assertEqual(self.result.returncode, 0, qgis.output_of(self.result))
        found = json.loads(self.result.stdout)
        return {Path(path).name: info for path, info in found.items()}

    def test_same_georeference(self) -> None:
        """La georreferencia de GDAL es, bit a bit, la rejilla leída (también
        norte = 12,559999999999999 en ``odd.asc``); *Point* con ``xllcenter``; para GDAL,
        el ``.prj`` (WKT de ESRI, sin código) es ETRS89 / UTM 30N: lo que el servicio de
        CRS (T11) identificará como EPSG:25830."""
        found = self._found()
        self.assertEqual(set(found), set(self.NAMES))
        for name, info in found.items():
            with self.subTest(name=name):
                grid = asc.read_asc(self.folder / name).grid
                self.assertEqual(info["transform"],
                                 [grid.west, grid.dx, 0.0, grid.north, 0.0, -grid.dy])
                self.assertEqual(info["size"], [grid.ncols, grid.nrows])
                self.assertEqual(info["point"] == "Point", name in ("center.asc", "odd.asc"))
        self.assertEqual(found["odd.asc"]["transform"][3], 12.559999999999999)
        self.assertEqual(found["corner.asc"]["crs"], "ETRS89 / UTM zone 30N")
        self.assertIsNone(found["dxdy.asc"]["crs"])

    def test_same_values(self) -> None:
        """Las cotas de GDAL en Float64 son las nuestras bit a bit (−9999 donde hay NaN)."""
        for name, info in self._found().items():
            with self.subTest(name=name):
                source = asc.read_asc(self.folder / name)
                got = np.frombuffer(bytes.fromhex(info["values"]), "<f8")
                ours = np.where(np.isnan(source.values), -9999.0, source.values).ravel()
                self.assertTrue(np.array_equal(got.view(np.uint64), ours.view(np.uint64)))


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: GPL-3.0-or-later
"""Lector de XYZ en malla regular (spec 006, T09; plan 006 §5.3.2, §5.3.6 y §5.4 A5).

- **RF-006-08** (importar un MDT con cada cota igual a la de la fuente): los XYZ en malla
  de ``tests/data/gis/xyz/`` (T01) dan la rejilla cuyos centros son los puntos (oeste =
  primera X − medio paso, norte = última Y + medio paso), con cada cota, bit a bit, el
  float64 de su texto y las celdas sin punto (el hueco) como NaN; la misma superficie que
  ``corner.asc``. El separador (espacios, tabulador, coma o «;», detectado o elegido), la
  coma decimal, la cabecera opcional, CRLF, BOM, las líneas en blanco y el orden de los
  puntos no cambian el resultado, ni el tamaño de los trozos que se leen. Un paso con ruido
  de hasta 1 mm (coordenadas escritas con 3 decimales de un paso de 1/3 m; diferencias de
  0,999 y 1,001 m) se acepta.
- **RF-006-09** (rechazar con fichero, característica, valor y qué hacer, sin importar
  nada): una malla irregular, con puntos repetidos, sobre dos mallas, con un punto a más de
  1 mm de la malla o de una sola fila o columna → ``gis.xyz_not_grid`` con la sugerencia de
  importarlo como puntos; una línea sin tres valores, un valor que no es un número o una X
  o una Y no finita → ``gis.xyz_line_invalid`` con la línea; más celdas que
  ``gis.import.max_cells`` y ningún dato.
- **RF-006-10** (no tocar la entrada): leer no cambia el listado de la carpeta ni la fecha
  de ningún fichero.

Avance y cancelación por trozos (RF-006-28).

- **RF-006-27** (T32, «Importar un fichero»): las primeras líneas de un ``.xyz`` dicen si es
  una malla (MDT) o puntos dispersos, con su separador, su decimal y su cabecera.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from tests.support.package import import_geoblender
from tests.support.repo import ROOT

gis = import_geoblender("gis")
xyz_grid = import_geoblender("gis.xyz_grid")
asc = import_geoblender("gis.asc")
params = import_geoblender("gis.params")
i18n = import_geoblender("core.i18n")
worker_api = import_geoblender("jobs.worker_api")

XYZ = ROOT / "tests" / "data" / "gis" / "xyz"
ASC = ROOT / "tests" / "data" / "gis" / "asc"
# grid.xyz: ventana de 20 × 15 celdas de 1 m en la esquina suroeste de base_1m (README).
GRID = (700000.0, 4400015.0, 1.0, 1.0, 20, 15)
HOLE = (slice(8, 10), slice(8, 11))  # filas 5–6 y columnas 8–10 desde el SO
NOT_GRID_HINT = "Impórtelo como puntos"


def _grid_tuple(grid: object) -> tuple:
    return (grid.west, grid.north, grid.dx, grid.dy, grid.ncols, grid.nrows)


def _same(test: unittest.TestCase, got: np.ndarray, expected: np.ndarray) -> None:
    """Iguales bit a bit, con NaN en las mismas celdas."""
    test.assertEqual(got.dtype, np.float64)
    test.assertEqual(got.shape, expected.shape)
    nan = np.isnan(expected)
    test.assertTrue(np.array_equal(np.isnan(got), nan))
    test.assertTrue(np.array_equal(got[~nan].view(np.uint64), expected[~nan].view(np.uint64)))


def _texts_of(path: Path, *, sep: str | None = None, comma: bool = False,
              header: bool = False) -> np.ndarray:
    """Las cotas de un XYZ de 1 m de T01 leídas aquí, sin el lector: cada texto con
    ``float``, en la celda de su centro (filas de norte a sur); las que faltan, NaN."""
    lines = path.read_text(encoding="utf-8").splitlines()[1 if header else 0:]
    values = np.full((15, 20), np.nan)
    for line in lines:
        x, y, z = (float(t.replace(",", ".") if comma else t) for t in line.split(sep))
        values[int(4400014.5 - y), int(x - 700000.5)] = z
    return values


_CACHE: dict[str, object] = {}


def _read(name: str, **options: object) -> object:
    """Un XYZ de T01 leído una vez."""
    if name not in _CACHE:
        _CACHE[name] = xyz_grid.read_xyz_grid(XYZ / name, **options)
    return _CACHE[name]


# --- Los ficheros de T01 -----------------------------------------------------------------


class ReadDataFilesTest(unittest.TestCase):
    """RF-006-08, RF-006-09 y RF-006-10 con los XYZ de ``tests/data/gis/xyz/``."""

    def test_grid_exact_values(self) -> None:
        """RF-006-08: ``grid.xyz`` (espacio, punto decimal, de norte a sur) → oeste
        700 000 (= 700 000,5 − 0,5), norte 4 400 015 (= 4 400 014,5 + 0,5), 20 × 15 celdas
        de 1 m; cada cota, el float64 de su texto, bit a bit, y la misma que la celda de
        ``corner.asc`` (filas 33–47, columnas 0–19). Referencia centros; no declara CRS,
        referencia vertical ni sin dato."""
        source = _read("grid.xyz")
        self.assertEqual(_grid_tuple(source.grid), GRID)
        self.assertEqual(source.grid.cell_area, 1.0)
        _same(self, source.values, _texts_of(XYZ / "grid.xyz"))
        _same(self, source.values, asc.read_asc(ASC / "corner.asc").values[33:48, 0:20])
        self.assertFalse(np.isnan(source.values).any())
        self.assertEqual(source.source_dtype, "float64")
        self.assertTrue(source.pixel_is_point)
        self.assertIsNone(source.nodata_value)
        self.assertIsNone(source.declared_crs)
        self.assertIsNone(source.declared_vertical)
        self.assertEqual(source.notes, ())

    def test_hole_semicolon_comma_and_header(self) -> None:
        """RF-006-08: ``grid_hole.xyz`` (cabecera ``X;Y;Z``, «;», coma decimal, de sur a
        norte, sin 6 puntos) → la misma rejilla y las mismas cotas que ``grid.xyz``, con
        las 6 celdas del hueco (filas 5–6 y columnas 8–10 desde el suroeste) como NaN;
        igual con el separador detectado que elegido."""
        expected = _read("grid.xyz").values.copy()
        expected[HOLE] = np.nan
        detected = _read("grid_hole.xyz", decimal=",")
        chosen = xyz_grid.read_xyz_grid(XYZ / "grid_hole.xyz", separator=";", decimal=",")
        for source in (detected, chosen):
            self.assertEqual(_grid_tuple(source.grid), GRID)
            _same(self, source.values, expected)
            _same(self, source.values, _texts_of(XYZ / "grid_hole.xyz", sep=";",
                                                 comma=True, header=True))
        self.assertEqual(int(np.isnan(detected.values).sum()), 6)
        for text in ("XYZ", "punto y coma (detectado)", "coma decimal", "con cabecera",
                     "294 puntos", "20 × 15"):
            self.assertIn(text, detected.encoding)
        self.assertNotIn("detectado", chosen.encoding)

    def test_irregular_rejected(self) -> None:
        """RF-006-09: ``irregular.xyz`` (150 puntos dispersos, tabulador) no es una malla:
        ``gis.xyz_not_grid`` con el fichero, el punto que se sale de la malla y la
        sugerencia de importarlo como puntos."""
        with self.assertRaises(gis.GisError) as caught:
            xyz_grid.read_xyz_grid(XYZ / "irregular.xyz")
        error = caught.exception
        self.assertEqual((error.code, error.obj), ("gis.xyz_not_grid", "irregular.xyz"))
        self.assertEqual(error.values["file"], "irregular.xyz")
        self.assertIn("«irregular.xyz»", str(error))
        self.assertIn(NOT_GRID_HINT, str(error))
        self.assertIn("de la línea", str(error))

    def test_input_untouched(self) -> None:
        """RF-006-10: leer los tres XYZ (también el que se rechaza) no cambia el listado de
        la carpeta ni la fecha de modificación de ningún fichero."""

        def snapshot() -> dict[str, int]:
            return {entry.name: entry.stat().st_mtime_ns for entry in os.scandir(XYZ)}

        before = snapshot()
        xyz_grid.read_xyz_grid(XYZ / "grid.xyz")
        xyz_grid.read_xyz_grid(XYZ / "grid_hole.xyz", decimal=",")
        with self.assertRaises(gis.GisError):
            xyz_grid.read_xyz_grid(XYZ / "irregular.xyz")
        self.assertEqual(snapshot(), before)

    def test_progress_and_cancel(self) -> None:
        """RF-006-28: con trozos de 1 KiB, avance tras cada trozo, creciente hasta 1; si se
        cancela en el 3.º, para con ``JobCancelled`` y no devuelve nada."""
        seen: list[float] = []
        with mock.patch.object(xyz_grid, "CHUNK_BYTES", 1024):
            xyz_grid.read_xyz_grid(XYZ / "grid.xyz",
                                   progress=lambda frac, text: seen.append(frac))
            self.assertGreaterEqual(len(seen), 5)
            self.assertEqual(seen, sorted(seen))
            self.assertEqual(seen[-1], 1.0)
            calls = []

            def cancelled() -> bool:
                calls.append(1)
                return len(calls) > 2

            with self.assertRaises(worker_api.JobCancelled) as caught:
                xyz_grid.read_xyz_grid(XYZ / "grid.xyz", cancelled=cancelled)
        self.assertIn(f"3 de {len(seen)}", str(caught.exception))

    def test_chunk_size_does_not_change_the_result(self) -> None:
        """RF-006-08: con trozos de 7, 61 y 4096 bytes (cortando líneas por la mitad) las
        cotas y la rejilla son las mismas, bit a bit."""
        expected = _read("grid_hole.xyz", decimal=",")
        for size in (7, 61, 4096):
            with self.subTest(trozo=size), mock.patch.object(xyz_grid, "CHUNK_BYTES", size):
                source = xyz_grid.read_xyz_grid(XYZ / "grid_hole.xyz", decimal=",")
                self.assertEqual(_grid_tuple(source.grid), GRID)
                _same(self, source.values, expected.values)

    def test_cell_limit(self) -> None:
        """RF-006-09: 20 × 15 = 300 celdas > 299 se rechaza con el número de celdas y el
        límite (también con 294 puntos y un hueco); con 300, se lee. Sin ``max_cells``,
        el límite es ``gis.import.max_cells``, leído al leer."""
        for name, options in (("grid.xyz", {}), ("grid_hole.xyz", {"decimal": ","})):
            with self.subTest(name=name):
                with self.assertRaises(gis.GisError) as caught:
                    xyz_grid.read_xyz_grid(XYZ / name, max_cells=299, **options)
                error = caught.exception
                self.assertEqual((error.code, error.value, error.obj),
                                 ("gis.raster_too_large", 300, name))
                self.assertEqual(error.values["limit"], 299)
        self.assertEqual(xyz_grid.read_xyz_grid(XYZ / "grid.xyz", max_cells=300).grid.ncols,
                         20)
        real = params.default

        def small(key: str) -> object:
            return 100 if key == "gis.import.max_cells" else real(key)

        with mock.patch.object(params, "default", side_effect=small):
            with self.assertRaises(gis.GisError) as caught:
                xyz_grid.read_xyz_grid(XYZ / "grid.xyz")
        self.assertEqual(caught.exception.code, "gis.raster_too_large")
        self.assertEqual(caught.exception.values["limit"], 100)


# --- Ficheros escritos en la prueba ------------------------------------------------------

# 3 × 2 celdas de 2 m con centros en X 700 001, 700 003, 700 005 e Y 4 400 003 (norte) y
# 4 400 001; falta el punto (700 005; 4 400 003): oeste 700 000, norte 4 400 004.
BASE_POINTS = (
    ("700001", "4400003", "801.5"),
    ("700003", "4400003", "802.25"),
    ("700001", "4400001", "803"),
    ("700003", "4400001", "804.125"),
    ("700005", "4400001", "805"),
)
BASE_GRID = (700000.0, 4400004.0, 2.0, 2.0, 3, 2)
BASE_VALUES = np.array([[801.5, 802.25, np.nan], [803.0, 804.125, 805.0]])


def _lines(points: tuple[tuple[str, str, str], ...] = BASE_POINTS, sep: str = " ",
           comma: bool = False) -> list[str]:
    return [sep.join(t.replace(".", ",") if comma else t for t in point) for point in points]


class ReadBuiltFilesTest(unittest.TestCase):
    """RF-006-08 y RF-006-09 con XYZ pequeños escritos aquí."""

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="gb-xyz-"))
        self.addCleanup(shutil.rmtree, self.folder, True)

    def _write(self, lines: list[str] | None = None, *, name: str = "m.xyz",
               newline: str = "\n", prefix: bytes = b"", end: str = "\n",
               data: bytes | None = None) -> Path:
        path = self.folder / name
        if data is None:
            data = prefix + (newline.join(_lines() if lines is None else lines)
                             + end).encode("latin-1")
        path.write_bytes(data)
        return path

    def _rejected(self, path: Path, code: str, **options: object) -> object:
        with self.assertRaises(gis.GisError) as caught:
            xyz_grid.read_xyz_grid(path, **options)
        error = caught.exception
        self.assertEqual(error.code, code)
        self.assertEqual(error.obj, path.name)
        self.assertEqual(error.values["file"], path.name)
        self.assertIn(f"«{path.name}»", str(error))
        if code == "gis.xyz_not_grid":
            self.assertIn(NOT_GRID_HINT, str(error))
        return error

    def test_separators_decimal_and_layout(self) -> None:
        """RF-006-08: espacios (varios y al principio), tabulador, coma, «;», coma decimal
        con espacio, tabulador o «;», CRLF, BOM, cabecera (también en Latin-1), líneas en
        blanco, otro orden y sin fin de línea al final: la misma rejilla y las mismas cotas,
        con el separador detectado o elegido."""
        reverse = tuple(reversed(BASE_POINTS))
        variants = {
            "espacios": (self._write(["  " + line for line in _lines(sep="   ")],
                                     name="a.xyz"), " ", "."),
            "tabulador": (self._write(_lines(sep="\t"), name="b.xyz"), "\t", "."),
            "coma": (self._write(_lines(sep=","), name="c.xyz"), ",", "."),
            "punto_y_coma": (self._write(_lines(sep=";"), name="d.xyz"), ";", "."),
            "punto_y_coma_decimal": (self._write(_lines(sep=";", comma=True),
                                                 name="e.xyz"), ";", ","),
            "espacio_decimal": (self._write(_lines(comma=True), name="f.xyz"), " ", ","),
            "tabulador_decimal": (self._write(_lines(sep="\t", comma=True), name="g.xyz"),
                                  "\t", ","),
            "crlf": (self._write(newline="\r\n", end="\r\n", name="h.xyz"), " ", "."),
            "bom": (self._write(prefix=b"\xef\xbb\xbf", name="i.xyz"), " ", "."),
            "cabecera": (self._write(["X;Y;Z", *_lines(sep=";")], name="j.xyz"), ";", "."),
            "cabecera_latin1": (self._write(["Este Norte Elevación", *_lines()],
                                            name="k.xyz"), " ", "."),
            "en_blanco": (self._write(["", *_lines()[:2], "  ", *_lines()[2:], ""],
                                      name="l.xyz"), " ", "."),
            "desordenado": (self._write(_lines(reverse), name="m.xyz"), " ", "."),
            "sin_fin_de_linea": (self._write(end="", name="n.xyz"), " ", "."),
        }
        for label, (path, separator, decimal) in variants.items():
            for chosen in (None, separator):
                with self.subTest(variante=label, separador=chosen):
                    source = xyz_grid.read_xyz_grid(path, separator=chosen, decimal=decimal)
                    self.assertEqual(_grid_tuple(source.grid), BASE_GRID)
                    _same(self, source.values, BASE_VALUES)
        self.assertIn("BOM", xyz_grid.read_xyz_grid(variants["bom"][0]).encoding)
        self.assertIn("tabulador (detectado)",
                      xyz_grid.read_xyz_grid(variants["tabulador"][0]).encoding)
        self.assertIn("sin cabecera", xyz_grid.read_xyz_grid(variants["coma"][0]).encoding)

    def test_values_are_the_float64_of_their_text(self) -> None:
        """RF-006-08: 17 cifras, exponentes, signo y punto sin cifras: cada cota es
        ``float(texto)`` bit a bit, sin redondeo adicional; ``nan`` es sin dato."""
        texts = ["812.34567890123456", "-1.5e2", "+7.", ".25", "1234.000000000000227"]
        points = tuple((x, y, z) for (x, y, _), z in zip(BASE_POINTS, texts, strict=True))
        source = xyz_grid.read_xyz_grid(self._write(_lines(points)))
        expected = np.array([[float(texts[0]), float(texts[1]), np.nan],
                             [float(texts[2]), float(texts[3]), float(texts[4])]])
        _same(self, source.values, expected)
        with_nan = (*BASE_POINTS, ("700005", "4400003", "nan"))
        _same(self, xyz_grid.read_xyz_grid(self._write(_lines(with_nan), name="n.xyz")).values,
              BASE_VALUES)

    def test_decimal_steps_are_exact(self) -> None:
        """RF-006-08, RF-006-02: centros con decimales que el binario no representa
        (X 700 000,3 + i, paso 1 m; Y 4 400 000,05 + 0,1·j) dan los pasos 1 y 0,1 m
        exactos (los de su texto) y celdas no cuadradas de área |dx·dy|."""
        points = tuple((f"{700000.3 + i:.1f}", f"{4400000.05 + 0.1 * j:.2f}", "800")
                       for i in range(7) for j in range(9))
        grid = xyz_grid.read_xyz_grid(self._write(_lines(points))).grid
        self.assertEqual((grid.dx, grid.dy, grid.ncols, grid.nrows), (1.0, 0.1, 7, 9))
        self.assertEqual(grid.west, 700000.3 - 0.5)
        self.assertEqual(grid.north, 4400000.85 + 0.05)
        self.assertEqual(grid.cell_area, abs(1.0 * 0.1))

    def test_step_with_noise_up_to_a_millimetre(self) -> None:
        """RF-006-08: un paso de 1/3 m escrito con 3 decimales (diferencias de 0,333 y
        0,334 m) y X que alternan 0,999 y 1,001 m de diferencia (|Δ − paso| = 1 mm) se
        aceptan: cada punto en su celda y ninguna sin dato."""
        third = tuple((f"{700000 + (i + 0.5) / 3:.3f}", f"{4400000 + (j + 0.5) / 3:.3f}",
                       f"{800 + i + 100 * j}") for i in range(30) for j in range(5))
        source = xyz_grid.read_xyz_grid(self._write(_lines(third), name="tercio.xyz"))
        grid = source.grid
        self.assertEqual((grid.ncols, grid.nrows), (30, 5))
        self.assertLess(abs(grid.dx - 1 / 3), 1e-4)
        self.assertLess(abs(grid.dy - 1 / 3), 1e-4)
        expected = 800.0 + np.arange(30)[None, :] + 100.0 * np.arange(4, -1, -1)[:, None]
        _same(self, source.values, expected)
        alternate = tuple((f"{700000.5 + i + 0.001 * (i % 2):.3f}", f"{4400000.5 + j:.3f}",
                           f"{800 + i + 100 * j}") for i in range(11) for j in range(3))
        source = xyz_grid.read_xyz_grid(self._write(_lines(alternate), name="alterno.xyz"))
        self.assertEqual(_grid_tuple(source.grid), (700000.0, 4400003.0, 1.0, 1.0, 11, 3))
        expected = 800.0 + np.arange(11)[None, :] + 100.0 * np.arange(2, -1, -1)[:, None]
        _same(self, source.values, expected)
        # La X de una misma columna cambia ±0,4 mm de una fila a otra.
        jitter = tuple((f"{700000.5 + i + 0.0004 * ((i + j) % 3 - 1):.4f}",
                        f"{4400000.5 + j}", f"{800 + i + 100 * j}")
                       for i in range(6) for j in range(4))
        source = xyz_grid.read_xyz_grid(self._write(_lines(jitter), name="vaiven.xyz"))
        grid = source.grid
        self.assertEqual((grid.dx, grid.dy, grid.ncols, grid.nrows), (1.0, 1.0, 6, 4))
        self.assertLess(abs(grid.west - 700000.0), 1e-6)
        expected = 800.0 + np.arange(6)[None, :] + 100.0 * np.arange(3, -1, -1)[:, None]
        _same(self, source.values, expected)

    def test_point_off_the_grid_rejected(self) -> None:
        """RF-006-09: una X a 1,5 mm de su centro (la línea 9) no es una malla: el mensaje
        da la X (en décimas de milímetro), la línea y la distancia, y pide importarlo como
        puntos."""
        points = [(f"{700000.5 + i}", f"{4400000.5 + j}", "800") for i in range(5)
                  for j in range(3)]
        points[8] = ("700002.5015", points[8][1], "800")
        error = self._rejected(self._write(_lines(tuple(points))), "gis.xyz_not_grid")
        self.assertEqual((error.field, error.value), ("X", 700002.5015))
        for text in (i18n.format_number(700002.5015, 4), "línea 9",
                     f"{i18n.format_number(1.5, 2)} mm", "se admite 1 mm"):
            self.assertIn(text, str(error))

    def test_repeated_points_rejected(self) -> None:
        """RF-006-09: un punto repetido (también con otra cota o a 0,4 mm) cae en la celda
        de otro: ``gis.xyz_not_grid`` con las dos líneas (contando la cabecera)."""
        cases = {
            "igual": ("700003", "4400001", "804.125"),
            "otra_cota": ("700003", "4400001", "790"),
            "a_0,4_mm": ("700003.0004", "4400001", "804.125"),
        }
        for label, point in cases.items():
            with self.subTest(caso=label):
                lines = ["X Y Z", *_lines((*BASE_POINTS, point))]
                error = self._rejected(self._write(lines, name=f"{label}.xyz"),
                                       "gis.xyz_not_grid")
                self.assertEqual((error.field, error.value), ("puntos", 7))
                self.assertIn("líneas 5 y 7", str(error))
                self.assertIn(f"centro X {i18n.format_number(700003.0, 4)} e Y "
                              f"{i18n.format_number(4400001.0, 4)}", str(error))
                self.assertIn("repetidos", str(error))

    def test_two_grids_rejected(self) -> None:
        """RF-006-09: dos mallas de 1 m, una desplazada 0,3 m en X y en Y, no son una."""
        points = [(f"{700000.5 + i + shift}", f"{4400000.5 + j + shift}", "800")
                  for shift in (0.0, 0.3) for i in range(4) for j in range(3)]
        self._rejected(self._write(_lines(tuple(points))), "gis.xyz_not_grid")

    def test_single_row_or_column_rejected(self) -> None:
        """RF-006-09: con una sola fila o una sola columna no se sabe el paso."""
        row = tuple((f"{700000.5 + i}", "4400000.5", "800") for i in range(4))
        column = tuple(("700000.5", f"{4400000.5 + j}", "800") for j in range(4))
        for label, points, axis in (("fila", row, "Y"), ("columna", column, "X")):
            with self.subTest(caso=label):
                error = self._rejected(self._write(_lines(points), name=f"{label}.xyz"),
                                       "gis.xyz_not_grid")
                self.assertEqual(error.field, axis)
                self.assertIn(f"misma {axis}", str(error))

    def test_line_invalid(self) -> None:
        """RF-006-09: una línea sin tres valores, un valor que no es un número o una X o
        una Y no finita → ``gis.xyz_line_invalid`` con la línea (contando la cabecera y las
        líneas en blanco), el campo y el valor; con coma en un número y punto decimal,
        sugiere la coma decimal."""
        base = _lines()
        cases = {
            "dos_valores": ([*base[:2], "700001 4400001", *base[3:]], {}, 3, "línea", 2,
                            "tiene 2 valores"),
            "cuatro_valores": ([*base[:4], "700005 4400001 805 7"], {}, 5, "línea", 4,
                               "tiene 4 valores"),
            "coma_decimal": (_lines(comma=True), {}, 1, "línea", 4, "coma decimal"),
            "z_texto": (["X Y Z", "", *base[:3], "700003 4400001 abc", base[4]], {}, 6, "Z",
                        "abc", "«abc» no es un número"),
            "coma_en_z": ([*_lines(sep=";")[:1], "700003;4400003;802,25",
                           *_lines(sep=";")[2:]], {}, 2, "Z", "802,25", "coma decimal"),
            "x_nan": ([*base[:4], "nan 4400001 805"], {}, 5, "X", "nan",
                      "no es un número finito"),
            "y_infinita": ([*base[:4], "700005 -inf 805"], {}, 5, "Y", "-inf",
                           "no es un número finito"),
        }
        for label, (lines, options, line, field, value, detail) in cases.items():
            with self.subTest(caso=label):
                error = self._rejected(self._write(lines, name=f"{label}.xyz"),
                                       "gis.xyz_line_invalid", **options)
                self.assertEqual((error.values["line"], error.field, error.value),
                                 (line, field, value))
                self.assertIn(detail, str(error))
                self.assertIn(f"línea {line}:", str(error))

    def test_line_numbers_across_chunks(self) -> None:
        """RF-006-09: la línea del error es la misma con trozos de 13 bytes, de 61 y de
        uno solo: la 25.ª de 30, con 2 valores."""
        lines = [f"{700000.5 + i} {4400000.5 + j} 800" for i in range(6) for j in range(5)]
        lines[24] = "700004.5 4400004.5"
        path = self._write(lines)
        for size in (13, 61, 1 << 20):
            with self.subTest(trozo=size), mock.patch.object(xyz_grid, "CHUNK_BYTES", size):
                error = self._rejected(path, "gis.xyz_line_invalid")
                self.assertEqual(error.values["line"], 25)

    def test_not_a_text_file(self) -> None:
        """RF-006-09: un fichero binario (un GeoTIFF con otra extensión) se rechaza: no es
        texto."""
        tif = ROOT / "tests" / "data" / "gis" / "geotiff" / "f32_strip.tif"
        error = self._rejected(self._write(data=tif.read_bytes(), name="binario.xyz"),
                               "gis.xyz_line_invalid")
        self.assertIn("no es texto", str(error))

    def test_without_data_rejected(self) -> None:
        """RF-006-09: un fichero vacío, solo con la cabecera o con todas las cotas ``nan``
        no tiene ninguna celda con dato: ``gis.raster_empty``."""
        all_nan = tuple((x, y, "nan") for x, y, _ in BASE_POINTS)
        for label, path in (("vacio", self._write(data=b"", name="vacio.xyz")),
                            ("cabecera", self._write(["X Y Z", ""], name="cabecera.xyz")),
                            ("nan", self._write(_lines(all_nan), name="nan.xyz"))):
            with self.subTest(caso=label):
                self._rejected(path, "gis.raster_empty")

    def test_invalid_arguments(self) -> None:
        """Un separador o un decimal que no son de la lista, o la coma como separador y
        como decimal a la vez, son un error del programa (``ValueError``)."""
        path = self._write()
        for options in ({"separator": "|"}, {"decimal": ";"},
                        {"separator": ",", "decimal": ","}):
            with self.subTest(**options), self.assertRaises(ValueError):
                xyz_grid.read_xyz_grid(path, **options)


# --- Las primeras líneas: ¿malla o puntos? (T32) -------------------------------------------


class SampleTest(unittest.TestCase):
    """RF-006-27 (T32): «Importar un fichero» abre con un ``.xyz`` en malla el importador de
    MDT y con uno disperso el de puntos; lo decide :func:`sample_xyz` con las primeras líneas
    del fichero, sin cambiarlo (RF-006-10)."""

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="gb-xyz-"))
        self.addCleanup(shutil.rmtree, self.folder, True)

    def test_grid_and_scattered_files(self) -> None:
        """RF-006-27: ``grid.xyz`` es una malla (espacio, punto decimal, sin cabecera);
        ``grid_hole.xyz`` también (cabecera ``X;Y;Z``, «;» y coma decimal: la coma se prueba
        cuando el punto no da números); ``irregular.xyz`` son puntos dispersos (tabulador).
        Leerlos no cambia la carpeta (RF-006-10)."""
        before = {entry.name: entry.stat().st_mtime_ns for entry in os.scandir(XYZ)}
        cases = (("grid.xyz", (True, " ", ".", False)),
                 ("grid_hole.xyz", (True, ";", ",", True)),
                 ("irregular.xyz", (False, "\t", ".", False)))
        for name, expected in cases:
            with self.subTest(fichero=name):
                sample = xyz_grid.sample_xyz(XYZ / name)
                self.assertIsInstance(sample, xyz_grid.XyzSample)
                self.assertEqual((sample.grid, sample.separator, sample.decimal,
                                  sample.header), expected)
        self.assertEqual({entry.name: entry.stat().st_mtime_ns for entry in os.scandir(XYZ)},
                         before)

    def test_only_whole_lines_of_the_first_bytes(self) -> None:
        """RF-006-27: solo se leen los primeros ``max_bytes`` y, de ellos, las líneas enteras:
        las tres primeras filas de ``grid.xyz`` y media línea de la cuarta siguen siendo una
        malla; si no llegan a dos filas, no se puede decir que lo sean (puntos)."""
        data = (XYZ / "grid.xyz").read_bytes()
        rows = data.split(b"\n")
        three = len(b"\n".join(rows[:60])) + 1  # 3 filas de 20 puntos, con su fin de línea
        sample = xyz_grid.sample_xyz(XYZ / "grid.xyz", max_bytes=three + 12)
        self.assertTrue(sample.grid)
        one = len(b"\n".join(rows[:20])) + 1
        self.assertFalse(xyz_grid.sample_xyz(XYZ / "grid.xyz", max_bytes=one + 12).grid)

    def test_not_xyz_points(self) -> None:
        """RF-006-27: un texto que no son puntos X Y Z con punto ni con coma decimal (cuatro
        columnas, palabras, un binario, nada) no es un XYZ: ``None`` (se abre el importador de
        puntos, que tiene su asistente)."""
        tif = ROOT / "tests" / "data" / "gis" / "geotiff" / "f32_strip.tif"
        cases = {"cuatro.xyz": b"P1 700000 4400000 800\nP2 700001 4400000 801\n",
                 "palabras.xyz": b"uno dos tres\ncuatro cinco seis\n",
                 "binario.xyz": tif.read_bytes(), "vacio.xyz": b""}
        for name, data in cases.items():
            with self.subTest(fichero=name):
                path = self.folder / name
                path.write_bytes(data)
                self.assertIsNone(xyz_grid.sample_xyz(path))


if __name__ == "__main__":
    unittest.main()

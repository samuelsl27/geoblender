# SPDX-License-Identifier: GPL-3.0-or-later
"""Contenido de los datos de texto de ``tests/data/gis/`` frente a su ``README.md`` (T01).

Lo que el README promete de los ASC, los XYZ y los CSV de puntos, leído con la biblioteca
estándar (los rásteres binarios los leen las pruebas del lector, T05 y T06):

- los ASC y los XYZ son la superficie z = 800 + 0,5·x − 0,25·y + 3·sin(x/7), con x e y
  desde (700 000; 4 400 000) en el centro de cada celda o en cada punto, con 3 decimales
  (|Δz| ≤ 0,0005 m), y los ASC tienen −9999 en el hueco y solo en él;
- ``taludes.csv`` tiene 44 filas: 20 puntos TN y cuatro roturas de 6 vértices;
  ``errores.csv``, 16 filas de datos.
"""

import math
import unittest
from pathlib import Path

from tests.support.repo import ROOT

DATA = ROOT / "tests" / "data" / "gis"
REF_E, REF_N = 700000.0, 4400000.0
TOLERANCE_M = 0.0005 + 1e-9  # 3 decimales
NODATA = -9999.0
HOLE = {(row, col) for row in range(20, 23) for col in range(30, 34)}


def surface(x: float, y: float) -> float:
    """La superficie del README, en el mismo orden."""
    return 800.0 + 0.5 * x - 0.25 * y + 3.0 * math.sin(x / 7.0)


def _number(text: str) -> float:
    return float(text.replace(",", "."))


def _read_asc(path: Path) -> tuple[dict[str, float], list[list[float]]]:
    """Cabecera (claves en minúsculas) y filas de un ESRI ASCII Grid, de norte a sur."""
    lines = path.read_text(encoding="utf-8").splitlines()
    header: dict[str, float] = {}
    while lines and lines[0].split()[0][0].isalpha():
        key, value = lines.pop(0).split()
        header[key.lower()] = float(value)
    return header, [[float(v) for v in line.split()] for line in lines if line.strip()]


class SurfaceTextTestCase(unittest.TestCase):
    """Los ASC y los XYZ son la superficie del README."""

    def test_asc_follow_surface(self) -> None:
        """RF-006-08, RF-006-09 (datos de T01): ``corner.asc`` (esquina), ``center.asc``
        (centro) y ``dxdy.asc`` (1 × 0,5 m) dan la cota de la superficie en el centro de
        cada celda con 3 decimales, y −9999 en el hueco y solo en él."""
        for name in ("corner.asc", "center.asc", "dxdy.asc"):
            with self.subTest(fichero=name):
                header, rows = _read_asc(DATA / "asc" / name)
                nrows, ncols = int(header["nrows"]), int(header["ncols"])
                self.assertEqual((len(rows), {len(r) for r in rows}), (nrows, {ncols}))
                dx = header.get("cellsize", header.get("dx"))
                dy = header.get("cellsize", header.get("dy"))
                if "xllcenter" in header:
                    west = header["xllcenter"] - dx / 2
                    south = header["yllcenter"] - dy / 2
                else:
                    west, south = header["xllcorner"], header["yllcorner"]
                self.assertEqual(header["nodata_value"], NODATA)
                worst = 0.0
                for row, values in enumerate(rows):
                    y = south + (nrows - row - 0.5) * dy - REF_N
                    for col, value in enumerate(values):
                        if (row, col) in HOLE:
                            self.assertEqual(value, NODATA, (row, col))
                            continue
                        x = west + (col + 0.5) * dx - REF_E
                        worst = max(worst, abs(value - surface(x, y)))
                self.assertLessEqual(worst, TOLERANCE_M)

    def test_xyz_follow_surface(self) -> None:
        """RF-006-08, RF-006-09 (datos de T01): ``grid.xyz`` (300 celdas), ``grid_hole.xyz``
        (cabecera, «;» y coma decimal; 294 celdas: 6 de hueco) e ``irregular.xyz`` (150
        puntos con tabulador) dan la cota de la superficie en cada punto con 3
        decimales."""
        cases = (("grid.xyz", None, False, 300), ("grid_hole.xyz", ";", True, 294),
                 ("irregular.xyz", "\t", False, 150))
        for name, separator, header, count in cases:
            with self.subTest(fichero=name):
                lines = (DATA / "xyz" / name).read_text(encoding="utf-8").splitlines()
                if header:
                    self.assertEqual(lines.pop(0), "X;Y;Z")
                points = [[_number(v) for v in line.split(separator)] for line in lines]
                self.assertEqual(len(points), count)
                worst = max(abs(z - surface(e - REF_E, n - REF_N)) for e, n, z in points)
                self.assertLessEqual(worst, TOLERANCE_M)


class PointsTextTestCase(unittest.TestCase):
    """Los CSV de puntos tienen lo que dice el README."""

    def test_taludes_structure(self) -> None:
        """RF-006-12, RF-006-13 (datos de T01): ``taludes.csv`` tiene 44 filas con
        ``P;X;Y;Z;Código;Línea``: 20 puntos TN sin línea y las roturas C1, P1, C2 y P2
        con 6 vértices cada una, todas con X, Y y Z numéricas."""
        lines = (DATA / "points" / "taludes.csv").read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "P;X;Y;Z;Código;Línea")
        rows = [line.split(";") for line in lines[1:]]
        self.assertEqual(len(rows), 44)
        by_line: dict[str, int] = {}
        for row in rows:
            self.assertEqual(len(row), 6, row)
            for value in row[1:4]:
                _number(value)
            by_line[row[5]] = by_line.get(row[5], 0) + 1
        self.assertEqual(by_line, {"": 20, "C1": 6, "P1": 6, "C2": 6, "P2": 6})

    def test_errores_rows(self) -> None:
        """RF-006-12, RF-006-14 (datos de T01): ``errores.csv`` tiene la cabecera y las 16
        filas de datos de la tabla de casos del README."""
        lines = (DATA / "points" / "errores.csv").read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "P;X;Y;Z;Código;Línea")
        self.assertEqual([line.split(";")[0] for line in lines[1:]],
                         [str(p) for p in range(1, 17)])


if __name__ == "__main__":
    unittest.main()

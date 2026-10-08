# SPDX-License-Identifier: GPL-3.0-or-later
"""Genera los datos sintéticos de la spec 006 en ``tests/data/gis/`` (T01; plan 006 §7.1).

Lo ejecuta una persona (no las pruebas), desde la raíz del repositorio, con el Python de
Blender y ``GEOBLENDER_QGIS_DIR`` apuntando a QGIS 4.2::

    & $PY -B -s -X utf8 -m tests.data.gis.make_gis_data

1. Calcula las «bases» (cotas de la superficie del ``README.md`` en float64 con
   ``math.sin``) y las escribe en una carpeta temporal como binario crudo con su VRT.
2. Lanza ``gdal_translate`` y ``ogr2ogr`` del GDAL de QGIS (:data:`COMMANDS`) con el entorno
   de su ``bin\\o4w_env.bat``, solo en ese proceso (``tests.support.qgis.gdal_env``: sin
   las variables ``PROJ_*`` ni ``GDAL_*`` del puesto y con ``GDAL_PAM_ENABLED=NO``).
3. Escribe los textos que GDAL no sabe escribir (ASC con ``xllcenter``, XYZ con «;» y
   coma decimal o disperso, CSV de puntos) en UTF-8 y LF.
4. Comprueba que los textos son UTF-8 sin ``\\r``, que el GeoPackage está en el diario
   clásico y que no hay ficheros auxiliares, y rehace en el ``README.md`` las secciones
   entre marcas (órdenes y tabla de ficheros con su sha256).

Con ``--out <carpeta>`` escribe los datos allí y no toca el ``README.md`` (sirve para
comprobar que dos ejecuciones dan los mismos bytes). Los datos que no se versionan (el CSV
en Latin-1, el GeoPackage con WAL pendiente y los grandes de rendimiento) los generan las
pruebas que los usan en la carpeta temporal.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import random
import re
import shutil
import struct
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from tests.support import qgis

HERE = Path(__file__).resolve().parent
README = HERE / "README.md"

# La superficie: z = 800 + 0,5·x − 0,25·y + 3·sin(x/7), con x = E − REF_E e y = N − REF_N
# (E y N, del centro de la celda).
REF_E = 700000.0
REF_N = 4400000.0
NX, NY = 64, 48
NODATA = -9999.0
# El hueco sin dato de todas las bases (filas y columnas desde la esquina noroeste).
HOLE_ROWS = range(20, 23)
HOLE_COLS = range(30, 34)
SPARSE_TILE = 16
# Fecha fija de las tablas del GeoPackage (gpkg_contents.last_change): sin ella, cada
# ejecución daría otro sha256.
GPKG_DATE = "2026-10-08T00:00:00.000Z"

SRS = ("-a_srs", "EPSG:25830")
NODATA_ARGS = ("-a_nodata", "-9999")


def surface(x: float, y: float) -> float:
    """La cota de la superficie en (x, y), en metros, en float64 y en este orden."""
    return 800.0 + 0.5 * x - 0.25 * y + 3.0 * math.sin(x / 7.0)


@dataclass(frozen=True)
class Base:
    """Una base: 64 × 48 celdas de la superficie, en binario crudo con su VRT."""

    name: str
    west: float
    north: float
    dx: float
    dy: float
    data_type: str = "Float64"  # o "Int16" (cotas redondeadas al metro)
    empty_tiles: tuple[tuple[int, int], ...] = ()  # (fila, columna) de teselas de 16 × 16

    def is_nodata(self, row: int, col: int) -> bool:
        if row in HOLE_ROWS and col in HOLE_COLS:
            return True
        return (row // SPARSE_TILE, col // SPARSE_TILE) in self.empty_tiles

    def values(self) -> list[float]:
        """Las cotas por filas desde el norte, con ``NODATA`` en el hueco."""
        out: list[float] = []
        for row in range(NY):
            y = (self.north - REF_N) - (row + 0.5) * self.dy
            for col in range(NX):
                x = (self.west - REF_E) + (col + 0.5) * self.dx
                out.append(NODATA if self.is_nodata(row, col) else surface(x, y))
        return out

    def write(self, folder: Path) -> None:
        """Escribe ``<name>.raw`` (little-endian) y ``<name>.vrt`` en ``folder``."""
        values = self.values()
        if self.data_type == "Int16":
            raw = struct.pack(f"<{len(values)}h", *(round(v) for v in values))
            size = 2
        else:
            raw = struct.pack(f"<{len(values)}d", *values)
            size = 8
        (folder / f"{self.name}.raw").write_bytes(raw)
        vrt = (
            f'<VRTDataset rasterXSize="{NX}" rasterYSize="{NY}">\n'
            f"  <GeoTransform>{self.west!r}, {self.dx!r}, 0.0, {self.north!r}, 0.0, "
            f"{-self.dy!r}</GeoTransform>\n"
            f'  <VRTRasterBand dataType="{self.data_type}" band="1" '
            'subClass="VRTRawRasterBand">\n'
            f'    <SourceFilename relativeToVRT="1">{self.name}.raw</SourceFilename>\n'
            f"    <ImageOffset>0</ImageOffset>\n"
            f"    <PixelOffset>{size}</PixelOffset>\n"
            f"    <LineOffset>{size * NX}</LineOffset>\n"
            f"    <ByteOrder>LSB</ByteOrder>\n"
            f"  </VRTRasterBand>\n"
            f"</VRTDataset>\n"
        )
        (folder / f"{self.name}.vrt").write_text(vrt, encoding="utf-8", newline="\n")


BASES: tuple[Base, ...] = (
    Base("base_1m", 700000.0, 4400048.0, 1.0, 1.0),
    Base("base_1m_i16", 700000.0, 4400048.0, 1.0, 1.0, data_type="Int16"),
    Base("base_05m", 700000.0, 4400024.0, 0.5, 0.5),
    Base("base_1m_sparse", 700000.0, 4400048.0, 1.0, 1.0, empty_tiles=((0, 3), (2, 0))),
    Base("base_dxdy", 700000.0, 4400024.0, 1.0, 0.5),
)


@dataclass(frozen=True)
class Work:
    """Un fichero de la carpeta temporal (una base o un CSV de origen)."""

    name: str


@dataclass(frozen=True)
class Out:
    """El fichero de datos que escribe la orden, relativo a la carpeta de datos."""

    rel: str


@dataclass(frozen=True)
class Command:
    """Una orden de GDAL, el fichero que produce y qué contiene."""

    tool: str
    args: tuple[str | Work | Out, ...]
    output: str
    description: str
    extra_outputs: tuple[tuple[str, str], ...] = ()  # (fichero, contenido) que también deja


def _translate(output: str, base: str, description: str, *options: str) -> Command:
    return Command(
        "gdal_translate", ("-q", *options, Work(f"{base}.vrt"), Out(output)), output, description
    )


def _f32(*options: str) -> tuple[str, ...]:
    return (*SRS, *NODATA_ARGS, "-ot", "Float32", *options)


def _ogr(layer: str, geometry: str, *, first: bool) -> Command:
    """Una capa de ``gpkg/capas.gpkg`` desde ``<layer>.csv`` (WKT en la columna ``wkt``).

    La primera crea el fichero y lleva índice espacial (como los GeoPackage de QGIS); las
    demás, sin él, para que el fichero pese menos."""
    mode = ("-f", "GPKG") if first else ("-update", "-lco", "SPATIAL_INDEX=NO")
    args = (
        *mode,
        "--config", "OGR_CURRENT_DATE", GPKG_DATE,
        *SRS,
        "-oo", "SEPARATOR=SEMICOLON",
        "-oo", "GEOM_POSSIBLE_NAMES=wkt",
        "-oo", "KEEP_GEOM_COLUMNS=NO",
        "-oo", "AUTODETECT_TYPE=YES",
        "-nln", layer,
        "-nlt", geometry,
        Out("gpkg/capas.gpkg"),
        Work(f"{layer}.csv"),
    )
    return Command("ogr2ogr", args, "gpkg/capas.gpkg", GPKG_DESCRIPTION)


GPKG_DESCRIPTION = (
    "GeoPackage (diario clásico, sin WAL) en EPSG:25830 con cinco capas: `puntos_z` "
    "(Point Z, con índice espacial: los 20 puntos TN de `taludes.csv`, con su número en "
    "`p` y `codigo`), `roturas_z` (LineString Z: sus cuatro roturas, con `linea` y "
    "`codigo`), `contorno` (MultiPolygon 2D: un polígono con un hueco y otro aparte), "
    "`puntos_2d` (Point 2D) y `curvas_zm` (LineString ZM de 806 y 816 m en `cota`; M = "
    "distancia desde el oeste, que se descarta)"
)


COMMANDS: tuple[Command, ...] = (
    _translate(
        "geotiff/f64_strip.tif", "base_1m", "Float64, sin compresión, tiras de 16 filas",
        *SRS, *NODATA_ARGS, "-ot", "Float64",
    ),
    _translate(
        "geotiff/f32_strip.tif", "base_1m", "Float32, sin compresión, tiras de 32 filas",
        *_f32(),
    ),
    _translate(
        "geotiff/i16_strip.tif", "base_1m_i16", "Int16 (cota redondeada al metro), sin "
        "compresión", *SRS, *NODATA_ARGS, "-ot", "Int16",
    ),
    _translate(
        "geotiff/i16_strip_lzw_p2.tif", "base_1m_i16", "Int16, LZW + predictor 2, tiras "
        "de 16 filas (los mismos valores que `i16_strip.tif`, que tiene una sola tira)",
        *SRS, *NODATA_ARGS, "-ot", "Int16", "-co", "COMPRESS=LZW", "-co", "PREDICTOR=2",
        "-co", "BLOCKYSIZE=16",
    ),
    _translate(
        "geotiff/f32_strip_packbits.tif", "base_1m", "Float32, PackBits (los mismos "
        "valores que `f32_strip.tif`)", *_f32("-co", "COMPRESS=PACKBITS"),
    ),
    _translate(
        "geotiff/f32_strip_deflate_p3_05m.tif", "base_05m", "Float32, DEFLATE + predictor "
        "3, paso de 0,5 m (el de la comprobación M1)",
        *_f32("-co", "COMPRESS=DEFLATE", "-co", "PREDICTOR=3"),
    ),
    _translate(
        "geotiff/f64_strip_deflate_p3.tif", "base_1m", "Float64, DEFLATE + predictor 3",
        *SRS, *NODATA_ARGS, "-ot", "Float64", "-co", "COMPRESS=DEFLATE", "-co", "PREDICTOR=3",
    ),
    _translate(
        "geotiff/f32_tile.tif", "base_1m", "Float32, sin compresión, teselas de 32 × 32 "
        "(la fila inferior, incompleta)",
        *_f32("-co", "TILED=YES", "-co", "BLOCKXSIZE=32", "-co", "BLOCKYSIZE=32"),
    ),
    _translate(
        "geotiff/f32_tile_lzw_p3.tif", "base_1m", "Float32, LZW + predictor 3, teselas de "
        "16 × 16", *_f32(
            "-co", "TILED=YES", "-co", "BLOCKXSIZE=16", "-co", "BLOCKYSIZE=16",
            "-co", "COMPRESS=LZW", "-co", "PREDICTOR=3",
        ),
    ),
    _translate(
        "geotiff/f32_tile_sparse.tif", "base_1m_sparse", "Float32, DEFLATE, teselas de "
        "16 × 16; las teselas (fila, columna) (0, 3) y (2, 0) no están en el fichero "
        "(desplazamiento y tamaño 0): sin dato", *_f32(
            "-co", "TILED=YES", "-co", "BLOCKXSIZE=16", "-co", "BLOCKYSIZE=16",
            "-co", "COMPRESS=DEFLATE", "-co", "SPARSE_OK=TRUE",
        ),
    ),
    _translate(
        "geotiff/f32_bigtiff.tif", "base_1m", "Float32, BigTIFF, sin compresión",
        *_f32("-co", "BIGTIFF=YES"),
    ),
    _translate(
        "geotiff/f32_mm.tif", "base_1m", "Float32, big-endian («MM»), sin compresión",
        *_f32("-co", "ENDIANNESS=BIG"),
    ),
    _translate(
        "geotiff/f32_pixelispoint.tif", "base_1m", "Float32, *PixelIsPoint*: el punto de "
        "enlace es el centro de la celda (700 000,5; 4 400 047,5), medio paso dentro",
        *_f32("-mo", "AREA_OR_POINT=Point"),
    ),
    _translate(
        "geotiff/f32_epsg23030.tif", "base_1m", "Float32, declarado en EPSG:23030 (ED50 / "
        "UTM 30N) con las mismas coordenadas", "-a_srs", "EPSG:23030", *NODATA_ARGS,
        "-ot", "Float32",
    ),
    _translate(
        "geotiff/f32_nocrs.tif", "base_1m", "Float32, sin claves de CRS",
        *NODATA_ARGS, "-ot", "Float32",
    ),
    _translate(
        "geotiff/u8_jpeg.tif", "base_1m", "Byte, JPEG (compresión 7): se rechaza", *SRS,
        "-ot", "Byte", "-scale", "780", "840", "0", "240", "-co", "COMPRESS=JPEG",
    ),
    _translate(
        "geotiff/f32_rotated.tif", "base_1m", "Float32, georreferencia girada "
        "(`ModelTransformation`): se rechaza",
        *_f32("-a_gt", "700000", "0.8", "0.6", "4400048", "0.6", "-0.8"),
    ),
    _translate(
        "geotiff/f32_2bands.tif", "base_1m", "Float32, dos bandas iguales: se rechaza",
        *_f32("-b", "1", "-b", "1"),
    ),
    _translate(
        "geotiff/f32_scale_offset.tif", "base_1m", "Float32, escala 0,1 y offset 100 en "
        "`GDAL_METADATA`: se rechaza", *_f32("-a_scale", "0.1", "-a_offset", "100"),
    ),
    Command(
        "gdal_translate",
        (
            "-q", *SRS, *NODATA_ARGS, "-of", "AAIGrid", "-co", "DECIMAL_PRECISION=3",
            Work("base_1m.vrt"), Out("asc/corner.asc"),
        ),
        "asc/corner.asc",
        "ESRI ASCII Grid con `xllcorner`/`yllcorner`, `cellsize` 1 y `NODATA_value` "
        "−9999; cotas con 3 decimales",
        extra_outputs=(("asc/corner.prj", "WKT (ESRI) de EPSG:25830 que escribe GDAL"),),
    ),
    Command(
        "gdal_translate",
        (
            "-q", *NODATA_ARGS, "-of", "AAIGrid", "-co", "DECIMAL_PRECISION=3",
            Work("base_dxdy.vrt"), Out("asc/dxdy.asc"),
        ),
        "asc/dxdy.asc",
        "ESRI ASCII Grid con `dx` 1 y `dy` 0,5 (celdas no cuadradas), sin `.prj`",
    ),
    Command(
        "gdal_translate",
        (
            "-q", "-of", "XYZ", "-co", "DECIMAL_PRECISION=3", "-srcwin", "0", "33", "20",
            "15", Work("base_1m.vrt"), Out("xyz/grid.xyz"),
        ),
        "xyz/grid.xyz",
        "XYZ en malla de 20 × 15 (la esquina suroeste de `base_1m`, sin hueco): espacio, "
        "punto decimal, sin cabecera, de norte a sur",
    ),
    _ogr("puntos_z", "POINTZ", first=True),
    _ogr("roturas_z", "LINESTRINGZ", first=False),
    _ogr("contorno", "MULTIPOLYGON", first=False),
    _ogr("puntos_2d", "POINT", first=False),
    _ogr("curvas_zm", "LINESTRINGZM", first=False),
)

# --- Puntos y roturas de «dos taludes» (desplazamientos desde (REF_E, REF_N) y cota) ---

TN_TOP = (
    (0.0, 40.0, 821.50), (20.0, 40.0, 821.80), (40.0, 40.0, 822.00), (60.0, 40.0, 822.20),
    (3.0, 34.0, 820.60), (15.2, 35.1, 820.90), (27.9, 34.4, 821.10), (40.3, 35.6, 821.30),
    (52.7, 34.2, 821.40), (60.0, 34.5, 821.00),
)
BERM = ((6.1, 20.1, 812.05), (30.2, 20.3, 812.12), (54.0, 20.0, 812.22))
TN_FLOOR = (
    (9.6, 5.2, 803.70), (29.8, 4.6, 803.80), (50.3, 5.5, 803.90), (0.0, 0.0, 803.50),
    (20.0, 0.0, 803.60), (40.0, 0.0, 803.70), (60.0, 0.0, 803.80),
)
# Roturas duras: cabeza y pie de cada talud (identificador, código, vértices).
BREAKLINES = (
    ("C1", "CABEZA", (
        (0.0, 30.0, 820.00), (12.5, 30.4, 820.10), (24.0, 30.9, 820.25),
        (36.5, 30.6, 820.30), (48.0, 30.2, 820.35), (60.0, 30.0, 820.40),
    )),
    ("P1", "PIE", (
        (0.0, 22.0, 812.00), (12.0, 22.3, 812.05), (24.5, 22.8, 812.15),
        (36.0, 22.5, 812.20), (48.5, 22.1, 812.25), (60.0, 22.0, 812.30),
    )),
    ("C2", "CABEZA", (
        (0.0, 18.0, 811.90), (12.5, 18.2, 811.95), (24.0, 18.6, 812.00),
        (36.5, 18.4, 812.05), (48.0, 18.1, 812.10), (60.0, 18.0, 812.15),
    )),
    ("P2", "PIE", (
        (0.0, 10.0, 803.90), (12.0, 10.3, 803.95), (24.5, 10.6, 804.00),
        (36.0, 10.4, 804.05), (48.5, 10.2, 804.10), (60.0, 10.0, 804.15),
    )),
)
CSV_HEADER = "P;X;Y;Z;Código;Línea"
# errores.csv, tal cual: cada fila con su caso en el README.
ERRORS_CSV = (
    CSV_HEADER,
    "1;700000,000;4400000,000;800,000;TN;",
    "2;700010,000;4400000,000;801,000;TN;",
    "3;700020,000;4400000,000;;TN;",
    "4;7OO030,000;4400000,000;803,000;TN;",
    "5;700040,000;4400000,000",
    "6;700000,000;4400010,000;810,000;TN;",
    "7;700000,0004;4400010,0003;810,004;TN;",
    "8;700010,000;4400010,000;811,000;TN;",
    "9;700010,0005;4400009,9996;811,250;TN;",
    "10;700020,000;4400010,000;812,000;PIE;L1",
    "11;700030,000;4400010,000;812,500;PIE;L1",
    "12;700040,000;4400010,000;813,000;PIE;L1",
    "13;700050,000;4400020,000;815,000;CABEZA;L2",
    "14;700020,000;4400020,000;814,000;CABEZA;L3",
    "15;700030,000;4400020,000;;CABEZA;L3",
    "16;700040,000;4400020,000;815,000;CABEZA;L3",
)

# Ventana de los XYZ: columnas 0–19 y filas 33–47 de base_1m (20 × 15 celdas de 1 m).
XYZ_COLS, XYZ_ROWS = 20, 15
XYZ_HOLE_COLS = range(8, 11)  # el hueco de grid_hole.xyz (columnas y filas desde el sur)
XYZ_HOLE_ROWS = range(5, 7)
IRREGULAR_POINTS = 150
IRREGULAR_SEED = 20261008

GENERATED_TEXTS: dict[str, str] = {
    "asc/center.asc": "`corner.asc` con `xllcenter`/`yllcenter` (esquina + medio paso), sin "
    "`.prj`: el lector no tiene CRS declarado",
    "xyz/grid_hole.xyz": "La malla de `grid.xyz` con cabecera `X;Y;Z`, «;», coma decimal, de "
    "sur a norte y sin las 6 celdas de columnas 8–10 y filas 5–6 (desde el suroeste): hueco "
    "sin dato",
    "xyz/irregular.xyz": f"{IRREGULAR_POINTS} puntos dispersos (no forman malla) en la "
    "ventana de `grid.xyz`, tabulador y punto decimal, sin cabecera",
    "points/taludes.csv": "Levantamiento de dos taludes: 20 puntos TN y cuatro roturas duras "
    "(cabeza C1 y pie P1 del superior, cabeza C2 y pie P2 del inferior, 6 vértices cada "
    "una); «;», coma decimal, columnas `P;X;Y;Z;Código;Línea`",
    "points/errores.csv": "Filas erróneas, duplicados y líneas inválidas (tabla de casos "
    "abajo)",
}


def _fmt(value: float, decimals: int = 3, comma: bool = False) -> str:
    text = f"{value:.{decimals}f}"
    return text.replace(".", ",") if comma else text


def _abs(offset: tuple[float, float, float]) -> tuple[float, float, float]:
    return REF_E + offset[0], REF_N + offset[1], offset[2]


def taludes_rows() -> list[tuple[int, tuple[float, float, float], str, str]]:
    """Las filas de ``taludes.csv`` (P, desplazamiento y cota, código, línea): TN de
    arriba, C1, P1, berma, C2, P2 y TN del fondo."""
    rows: list[tuple[tuple[float, float, float], str, str]] = []
    rows += [(p, "TN", "") for p in TN_TOP]
    for line_id, code, vertices in BREAKLINES[:2]:
        rows += [(v, code, line_id) for v in vertices]
    rows += [(p, "TN", "") for p in BERM]
    for line_id, code, vertices in BREAKLINES[2:]:
        rows += [(v, code, line_id) for v in vertices]
    rows += [(p, "TN", "") for p in TN_FLOOR]
    return [(number, *row) for number, row in enumerate(rows, start=1)]


def taludes_csv() -> str:
    lines = [CSV_HEADER]
    for number, offset, code, line_id in taludes_rows():
        e, n, z = _abs(offset)
        coords = (_fmt(v, comma=True) for v in (e, n, z))
        lines.append(";".join((str(number), *coords, code, line_id)))
    return "\n".join(lines) + "\n"


def _wkt_xyz(points: Sequence[tuple[float, float, float]]) -> str:
    return ",".join(
        f"{_fmt(e)} {_fmt(n)} {_fmt(z)}" for e, n, z in (_abs(p) for p in points)
    )


def ogr_sources() -> dict[str, str]:
    """Los CSV con geometría WKT que lee ``ogr2ogr`` (carpeta temporal, no se versionan)."""
    points = ["wkt;p;codigo"]
    for number, offset, code, line_id in taludes_rows():
        if not line_id:
            points.append(f"POINT Z ({_wkt_xyz((offset,))});{number};{code}")
    lines = ["wkt;linea;codigo"]
    for line_id, code, vertices in BREAKLINES:
        lines.append(f"LINESTRING Z ({_wkt_xyz(vertices)});{line_id};{code}")
    outer = "700000 4400000,700060 4400000,700060 4400040,700000 4400040,700000 4400000"
    hole = "700025 4400002,700025 4400007,700035 4400007,700035 4400002,700025 4400002"
    island = "700065 4400000,700075 4400000,700075 4400010,700065 4400010,700065 4400000"
    boundary = ["wkt;nombre", f"MULTIPOLYGON ((({outer}),({hole})),(({island})));contorno"]
    flat = [
        "wkt;nombre",
        "POINT (700005.000 4400005.000);A",
        "POINT (700055.000 4400005.000);B",
        "POINT (700030.000 4400038.000);C",
    ]
    contours = ["wkt;cota"]
    for z, north in ((806.0, (12.0, 12.5, 12.2)), (816.0, (26.0, 26.6, 26.1))):
        vertices = ",".join(
            f"{_fmt(REF_E + e)} {_fmt(REF_N + n)} {_fmt(z)} {_fmt(e)}"
            for e, n in zip((0.0, 30.0, 60.0), north, strict=True)
        )
        contours.append(f"LINESTRING ZM ({vertices});{_fmt(z)}")
    return {
        "puntos_z.csv": "\n".join(points) + "\n",
        "roturas_z.csv": "\n".join(lines) + "\n",
        "contorno.csv": "\n".join(boundary) + "\n",
        "puntos_2d.csv": "\n".join(flat) + "\n",
        "curvas_zm.csv": "\n".join(contours) + "\n",
    }


def center_asc(corner_text: str) -> str:
    """``corner.asc`` con ``xllcenter``/``yllcenter`` = esquina + medio ``cellsize``."""
    cellsize = float(re.search(r"^cellsize\s+(\S+)$", corner_text, re.M)[1])

    def shift(match: re.Match[str]) -> str:
        key = f"{match[1]}llcenter"
        return f"{key:<13}{float(match[2]) + cellsize / 2:.12f}"

    text, count = re.subn(r"^([xy])llcorner\s+(\S+)$", shift, corner_text, flags=re.M)
    if count != 2:
        raise RuntimeError("corner.asc no tiene xllcorner e yllcorner")
    return text


def _xyz_cells() -> list[tuple[int, int, float, float, float]]:
    """Las celdas de la ventana XYZ de sur a norte: (fila, columna, E, N, z)."""
    cells: list[tuple[int, int, float, float, float]] = []
    for row in range(XYZ_ROWS):
        y = row + 0.5
        for col in range(XYZ_COLS):
            x = col + 0.5
            cells.append((row, col, REF_E + x, REF_N + y, surface(x, y)))
    return cells


def grid_hole_xyz() -> str:
    lines = ["X;Y;Z"]
    for row, col, e, n, z in _xyz_cells():
        if row in XYZ_HOLE_ROWS and col in XYZ_HOLE_COLS:
            continue
        lines.append(";".join(_fmt(v, comma=True) for v in (e, n, z)))
    return "\n".join(lines) + "\n"


def irregular_xyz() -> str:
    rng = random.Random(IRREGULAR_SEED)
    lines: list[str] = []
    for _ in range(IRREGULAR_POINTS):
        x = float(_fmt(rng.uniform(0.0, float(XYZ_COLS))))
        y = float(_fmt(rng.uniform(0.0, float(XYZ_ROWS))))
        lines.append("\t".join((_fmt(REF_E + x), _fmt(REF_N + y), _fmt(surface(x, y)))))
    return "\n".join(lines) + "\n"


# --- Ejecución ---


def _display(arg: str | Work | Out) -> str:
    if isinstance(arg, Work):
        return arg.name
    if isinstance(arg, Out):
        return arg.rel.replace("/", "\\")
    return arg


def _resolve(arg: str | Work | Out, work: Path, out: Path) -> str:
    if isinstance(arg, Work):
        return str(work / arg.name)
    if isinstance(arg, Out):
        return str(out / arg.rel)
    return arg


def command_line(command: Command) -> str:
    """La orden como se escribe en el README (PowerShell)."""
    args = " ".join(_display(arg) for arg in command.args)
    return f'& "$GDAL\\{command.tool}.exe" {args}'


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def _outputs() -> list[str]:
    names: list[str] = []
    for command in COMMANDS:
        for rel in (command.output, *(rel for rel, _d in command.extra_outputs)):
            if rel not in names:
                names.append(rel)
    return [*names, *GENERATED_TEXTS]


def generate(out: Path) -> None:
    """Escribe todos los datos en ``out`` (borra antes los que va a escribir)."""
    for rel in _outputs():
        (out / rel).unlink(missing_ok=True)
    for sub in ("geotiff", "asc", "xyz", "points", "gpkg"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="gb006-"))
    try:
        for base in BASES:
            base.write(work)
        for name, text in ogr_sources().items():
            _write_text(work / name, text)
        for command in COMMANDS:
            args = [_resolve(arg, work, out) for arg in command.args]
            result = qgis.run_tool(command.tool, *args)
            if result.returncode != 0:
                raise RuntimeError(f"{command_line(command)}\n{qgis.output_of(result)}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    corner = (out / "asc/corner.asc").read_bytes().decode("utf-8")
    _write_text(out / "asc/center.asc", center_asc(corner))
    _write_text(out / "xyz/grid_hole.xyz", grid_hole_xyz())
    _write_text(out / "xyz/irregular.xyz", irregular_xyz())
    _write_text(out / "points/taludes.csv", taludes_csv())
    _write_text(out / "points/errores.csv", "\n".join(ERRORS_CSV) + "\n")
    check_outputs(out)


def check_outputs(out: Path) -> None:
    """Textos en UTF-8 sin ``\\r``, GeoPackage en el diario clásico y nada más al lado."""
    expected = set(_outputs())
    found = {
        p.relative_to(out).as_posix()
        for sub in ("geotiff", "asc", "xyz", "points", "gpkg")
        for p in (out / sub).rglob("*")
        if p.is_file()
    }
    if found != expected:
        raise RuntimeError(f"ficheros inesperados o que faltan: {sorted(found ^ expected)}")
    for rel in expected:
        data = (out / rel).read_bytes()
        if rel.endswith((".asc", ".prj", ".xyz", ".csv")):
            data.decode("utf-8")
            if b"\r" in data or data.startswith(b"\xef\xbb\xbf"):
                raise RuntimeError(f"{rel}: tiene «\\r» o BOM")
        if rel.endswith(".gpkg") and (data[18], data[19]) != (1, 1):
            raise RuntimeError(f"{rel}: no está en el diario clásico (WAL)")


def _descriptions() -> dict[str, str]:
    found: dict[str, str] = {}
    for command in COMMANDS:
        found[command.output] = command.description
        found.update(dict(command.extra_outputs))
    found.update(GENERATED_TEXTS)
    return found


def readme_sections(out: Path, version: str) -> dict[str, str]:
    """Las secciones generadas del README: órdenes y tabla de ficheros."""
    commands = "\n".join(command_line(command) for command in COMMANDS)
    orders = (
        f"Con {version} (`$GDAL` es `$env:GEOBLENDER_QGIS_DIR\\bin`; las bases y los CSV "
        "de origen, en la carpeta temporal):\n\n"
        "```powershell\n"
        '$GDAL = "$env:GEOBLENDER_QGIS_DIR\\bin"\n'
        f"{commands}\n"
        "```"
    )
    descriptions = _descriptions()
    rows = ["| Fichero | Contenido | sha256 |", "| --- | --- | --- |"]
    for rel in sorted(descriptions):
        digest = hashlib.sha256((out / rel).read_bytes()).hexdigest()
        rows.append(f"| `{rel}` | {descriptions[rel]} | `{digest}` |")
    return {"órdenes": orders, "ficheros": "\n".join(rows)}


def update_readme(sections: dict[str, str]) -> None:
    """Sustituye en el README lo que hay entre ``<!-- <nombre>: inicio -->`` y
    ``<!-- <nombre>: fin -->`` por su sección."""
    text = README.read_bytes().decode("utf-8")
    for name, body in sections.items():
        pattern = re.compile(
            rf"(<!-- {name}: inicio -->\n)(?:.*?\n)?(<!-- {name}: fin -->)", flags=re.S
        )
        text, count = pattern.subn(lambda m, b=body: f"{m[1]}{b}\n{m[2]}", text)
        if count != 1:
            raise RuntimeError(f"README.md: falta la sección «{name}» entre marcas")
    README.write_bytes(text.encode("utf-8"))


def gdal_version() -> str:
    result = qgis.run_tool("gdalinfo", "--version")
    if result.returncode != 0:
        raise RuntimeError(qgis.output_of(result))
    return result.stdout.strip().split(",")[0]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Genera los datos de tests/data/gis/.")
    parser.add_argument("--out", type=Path, help="carpeta de salida (no toca el README)")
    options = parser.parse_args(argv)
    if qgis.find_install() is None:
        print(f"No hay QGIS: {qgis.QGIS_HINT}.", file=sys.stderr)
        return 2
    out = (options.out or HERE).resolve()
    generate(out)
    sections = readme_sections(out, gdal_version())
    if options.out is None:
        update_readme(sections)
        print(f"Datos y README.md al día en {out}.")
    else:
        print(sections["ficheros"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

# SPDX-License-Identifier: GPL-3.0-or-later
"""Capas de un GeoPackage de otro programa, leídas sobre una copia (spec 006, T15; plan 006
§5.2.6, §5.3.2, §5.3.6 y A18; ``gis.vector`` y los papeles de ``gis.points``).

- **RF-006-10**: el GeoPackage del usuario se copia (con su ``-wal`` o su ``-journal``) a la
  carpeta de importación de la caché, ``<caché>/import/<operación>/``, y se lee la copia: su
  carpeta queda con los mismos ficheros, tamaños, fechas y sha256, también con un WAL
  pendiente de un escritor que terminó sin cerrar (generado aquí con ``os._exit``, como en la
  002), y la copia trae las entidades que solo estaban en el ``-wal``.
- **RF-006-12**: las capas Point Z, LineString Z, MultiPolygon 2D, Point 2D y LineString ZM de
  ``gpkg/capas.gpkg`` se listan con su tipo, Z, M, SRS y número de entidades, y se leen con
  cada coordenada igual bit a bit a la de su fuente (``taludes.csv`` y los WKT de
  ``make_gis_data``); la M se descarta con aviso. De un GeoPackage de otro programa: WKB
  ISO y EWKB, *big endian*, XYM; las geometrías vacías o nulas se omiten (con aviso) y las
  curvas, las colecciones y las de otro SRS se rechazan con su número de entidad y su
  motivo; una capa de curvas o en un CRS fuera del catálogo no se lee, y una sin SRS EPSG
  pide el CRS. Como líneas de rotura no se acepta una geometría sin cota; como puntos,
  tampoco.
"""

import hashlib
import re
import sqlite3
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

from tests.data.gis import make_gis_data
from tests.support.package import import_geoblender
from tests.support.repo import ROOT
from tests.support.trees import child_env, child_temp

gis = import_geoblender("gis")
vector = import_geoblender("gis.vector")
points = import_geoblender("gis.points")
core_gpkg = import_geoblender("core.gpkg")
gpkg_base = import_geoblender("core.gpkg.base")
georef = import_geoblender("core.georef")

DATA = ROOT / "tests" / "data" / "gis"
CAPAS = DATA / "gpkg" / "capas.gpkg"
TALUDES = DATA / "points" / "taludes.csv"
CATALOG = georef.load_catalog()
H25830 = CATALOG.horizontal(25830)
SRS = 25830
WAL_PRAGMA = "PRAGMA journal_mode=" + "WAL"
# Escritor que añade líneas a «roturas_z» en WAL y termina sin cerrar (un QGIS que se cae):
# deja el -wal sin consolidar y un -shm.
KILLED_WRITER = f"""
import os, sqlite3, sys
conn = sqlite3.connect(sys.argv[1], isolation_level=None)
conn.execute("{WAL_PRAGMA}")
for index, blob in enumerate(sys.argv[2:], start=1):
    conn.execute("BEGIN")
    conn.execute("INSERT INTO roturas_z (geom, linea, codigo) VALUES (?, ?, ?)",
                 (bytes.fromhex(blob), f"W{{index}}", "WAL"))
    conn.execute("COMMIT")
os._exit(0)
"""
WAL_LINES = [
    np.array([[700_001.001, 4_400_001.002, 801.003], [700_011.004, 4_400_002.005, 802.006]]),
    np.array([[700_021.25, 4_400_003.5, 803.75], [700_031.0, 4_400_004.0, 804.0],
              [700_041.123, 4_400_005.456, 805.789]]),
    np.array([[700_051.1, 4_400_006.2, 806.3], [700_059.9, 4_400_007.8, 807.7]]),
]


def _fingerprint(folder: Path) -> dict[str, tuple[int, int, str]]:
    """Cada fichero de ``folder``: tamaño, fecha (ns) y sha256."""
    return {
        path.name: (
            path.stat().st_size,
            path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in sorted(folder.iterdir())
    }


def _numbers(text: str) -> list[float]:
    return [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", text)]


def _wkt_parts(wkt: str, dims: int, keep: int) -> list[np.ndarray]:
    """Las listas de coordenadas más internas de un WKT, en orden, con ``keep`` de cada
    ``dims`` ordenadas (para quitar la M)."""
    parts = []
    for body in re.findall(r"\(([^()]+)\)", wkt):
        values = np.array(_numbers(body)).reshape(-1, dims)
        parts.append(np.ascontiguousarray(values[:, :keep]))
    return parts


def _sources() -> dict[str, list[str]]:
    """Los WKT de cada capa de ``capas.gpkg``, de su generador."""
    found: dict[str, list[str]] = {}
    for name, text in make_gis_data.ogr_sources().items():
        rows = text.splitlines()[1:]
        found[name.removesuffix(".csv")] = [row.split(";")[0] for row in rows]
    return found


def _csv_rows() -> tuple[list[tuple], dict[str, list[tuple]]]:
    """Puntos TN y vértices de cada rotura de ``taludes.csv`` (P, xyz, código)."""
    found: list[tuple] = []
    lines: dict[str, list[tuple]] = {}
    for line in TALUDES.read_text(encoding="utf-8").splitlines()[1:]:
        p, x, y, z, code, line_id = line.split(";")
        xyz = tuple(float(v.replace(",", ".")) for v in (x, y, z))
        (lines.setdefault(line_id, []) if line_id else found).append((p, xyz, code))
    return found, lines


def _killed_writer(path: Path, blobs: list[bytes]) -> None:
    with child_temp() as temp:
        subprocess.run(
            [sys.executable, "-B", "-s", "-c", KILLED_WRITER, str(path),
             *(blob.hex() for blob in blobs)],
            env=child_env(None, temp),
            check=True,
            timeout=60,
            capture_output=True,
        )


def _header(srs: int, *, flags: int = 1) -> bytes:
    """Cabecera ``GP`` *little endian* sin envolvente."""
    return b"GP" + bytes([0, flags]) + struct.pack("<i", srs)


def _wkb_points(order: str, code: int, values: np.ndarray) -> bytes:
    return struct.pack(f"{order}BI", 1 if order == "<" else 0, code) + struct.pack(
        f"{order}I", len(values)
    ) + values.astype(f"{order}f8").tobytes()


P_Z = np.array([700_100.123, 4_400_100.456, 850.789])
EWKB_LINE = np.array([[700_101.0, 4_400_101.5, 851.25], [700_102.75, 4_400_103.0, 852.5]])
BE_RING = np.array([[700_110.0, 4_400_110.0, 860.0], [700_120.0, 4_400_110.0, 861.0],
                    [700_120.0, 4_400_120.0, 862.0], [700_110.0, 4_400_110.0, 860.0]])
XYM = np.array([700_130.5, 4_400_130.25, 99.0])  # x, y, m
MULTI = np.array([[700_140.0, 4_400_140.0, 870.0], [700_141.0, 4_400_141.0, 871.0]])
PARTS_ZM = [
    np.array([[700_150.0, 4_400_150.0, 880.0, 0.0], [700_151.5, 4_400_150.5, 880.5, 1.6]]),
    np.array([[700_160.0, 4_400_160.0, 890.0, 0.0], [700_161.0, 4_400_162.0, 891.0, 2.2],
              [700_163.0, 4_400_162.5, 892.0, 4.3]]),
]
LINES_2D = [np.array([[700_170.0, 4_400_170.0], [700_171.0, 4_400_172.0]]),
            np.array([[700_180.0, 4_400_180.0], [700_181.0, 4_400_181.0]])]


def _mixed_blobs() -> list[bytes | None]:
    """Las 10 entidades de la capa «mixta» (GEOMETRY), en el orden de su fid."""
    empty = bytearray(core_gpkg.encode_geometry("POINT", P_Z[:2], SRS, False))
    empty[3] |= 0b0001_0000
    ring = BE_RING.astype(">f8").tobytes()
    big_polygon = (
        b"GP" + bytes([0, 0]) + struct.pack(">i", SRS)
        + struct.pack(">BI", 0, 1003) + struct.pack(">I", 1) + struct.pack(">I", 4) + ring
    )
    multipoint = core_gpkg.encode_geometry("MULTIPOINT", MULTI, SRS, True)
    return [
        core_gpkg.encode_geometry("POINT", P_Z, SRS, True),  # 1: Point Z
        bytes(empty),  # 2: vacía → se omite
        None,  # 3: nula → se omite
        _header(SRS) + struct.pack("<BII", 1, 7, 0),  # 4: GeometryCollection → rechazo
        _header(SRS) + _wkb_points("<", 8, EWKB_LINE[:, :2]),  # 5: CircularString → rechazo
        _header(SRS) + _wkb_points("<", 0x8000_0002, EWKB_LINE),  # 6: EWKB LineString Z
        big_polygon,  # 7: Polygon Z big endian
        _header(SRS) + struct.pack("<BI", 1, 2001) + XYM.tobytes(),  # 8: Point M (ISO)
        core_gpkg.encode_geometry("POINT", P_Z, 4326, True),  # 9: otro SRS → rechazo
        multipoint,  # 10: MultiPoint Z
    ]


def _multiline_zm() -> bytes:
    parts = b"".join(_wkb_points("<", 3002, part) for part in PARTS_ZM)
    return _header(SRS) + struct.pack("<BII", 1, 3005, len(PARTS_ZM)) + parts


def _foreign_gpkg(path: Path) -> None:
    """Un GeoPackage «de otro programa» con capas y geometrías que Geoblender no escribe."""
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        gpkg_base.create_base(conn, H25830)

        def layer(name: str, kind: str, srs: int, z: int, m: int, blobs: list) -> None:
            conn.execute(
                f'CREATE TABLE "{name}" (fid INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, '
                f"geom {kind}, nombre TEXT)"
            )
            conn.execute(
                "INSERT INTO gpkg_contents (table_name, data_type, identifier, srs_id) "
                "VALUES (?, 'features', ?, ?)",
                (name, name, srs),
            )
            conn.execute(
                "INSERT INTO gpkg_geometry_columns VALUES (?, 'geom', ?, ?, ?, ?)",
                (name, kind, srs, z, m),
            )
            conn.executemany(
                f'INSERT INTO "{name}" (geom, nombre) VALUES (?, ?)',
                [(blob, f"{name}-{index}") for index, blob in enumerate(blobs, start=1)],
            )

        layer("mixta", "GEOMETRY", SRS, 2, 2, _mixed_blobs())
        layer("multilineas", "MULTILINESTRING", SRS, 1, 1, [_multiline_zm()])
        layer("lineas_2d", "LINESTRING", SRS, 0, 0,
              [core_gpkg.encode_geometry("LINESTRING", line, SRS, False) for line in LINES_2D])
        layer("arcos", "CIRCULARSTRING", SRS, 0, 0, [])
        layer("sin_srs", "POINT", -1, 1, 0, [core_gpkg.encode_geometry("POINT", P_Z, -1, True)])
        layer("geograficas", "POINT", 4326, 0, 0,
              [core_gpkg.encode_geometry("POINT", np.array([-3.7, 40.4]), 4326, False)])
    finally:
        conn.close()


class _CopyTest(unittest.TestCase):
    """Una carpeta temporal con la caché del proyecto (``cache``) por prueba."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="geoblender-006-t15-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.cache = self.tmp / "cache"


class CopySourceTest(_CopyTest):
    """RF-006-10: se lee una copia en la caché; la fuente y su carpeta, intactas."""

    def test_import_dir(self) -> None:
        """La carpeta de importación es ``<caché>/import/<operación>/`` (plan §5.2.6); el
        identificador de la operación es un nombre, nunca una ruta."""
        self.assertEqual(vector.import_dir(self.cache, "op-2026_1"),
                         self.cache / "import" / "op-2026_1")
        for bad in ("", "..", "a/b", "a\\b", "c:x", " op"):
            with self.subTest(uid=bad), self.assertRaises(ValueError):
                vector.import_dir(self.cache, bad)

    def test_copy_of_the_versioned_gpkg(self) -> None:
        """RF-006-10: la copia queda en la carpeta de importación, en diario clásico y sin
        ``-wal``, ``-shm`` ni ``-journal``; la carpeta de la fuente, igual (nombres,
        tamaños, fechas y sha256)."""
        before = _fingerprint(CAPAS.parent)
        target = vector.import_dir(self.cache, "op1")
        copy = vector.copy_source(CAPAS, target)
        self.assertEqual(copy, target / "capas.gpkg")
        self.assertEqual(sorted(p.name for p in target.iterdir()), ["capas.gpkg"])
        self.assertEqual(core_gpkg.read_header(copy).journal, "classic")
        self.assertEqual(copy.read_bytes(), CAPAS.read_bytes())
        self.assertEqual(_fingerprint(CAPAS.parent), before)

    def test_wal_pending_is_read_complete(self) -> None:
        """RF-006-10, RF-006-12: con 3 líneas confirmadas que solo están en el ``-wal`` (y
        su ``-shm``), la copia tiene las 7 líneas, con las nuevas bit a bit, y la carpeta
        de la fuente sigue con los mismos ficheros, fechas y sha256."""
        source_dir = self.tmp / "usuario"
        source_dir.mkdir()
        source = source_dir / "capas.gpkg"
        source.write_bytes(CAPAS.read_bytes())
        blobs = [core_gpkg.encode_geometry("LINESTRING", line, SRS, True) for line in WAL_LINES]
        _killed_writer(source, blobs)
        self.assertEqual(sorted(p.name for p in source_dir.iterdir()),
                         ["capas.gpkg", "capas.gpkg-shm", "capas.gpkg-wal"])
        before = _fingerprint(source_dir)
        target = vector.import_dir(self.cache, "op-wal")
        copy = vector.copy_source(source, target)
        self.assertEqual(sorted(p.name for p in target.iterdir()), ["capas.gpkg"])
        layers = {info.name: info for info in vector.list_layers(copy)}
        self.assertEqual(layers["roturas_z"].features, 7)
        features = vector.read_layer(copy, "roturas_z")
        self.assertEqual(features.fids, (1, 2, 3, 4, 5, 6, 7))
        self.assertEqual(features.attributes["linea"][4:], ("W1", "W2", "W3"))
        for geometry, line in zip(features.geometries[4:], WAL_LINES, strict=True):
            self.assertEqual(geometry.coords.tobytes(), line.tobytes())
        self.assertEqual(_fingerprint(source_dir), before)
        self.assertEqual(core_gpkg.read_header(source).journal, "wal")

    def test_refuses_to_copy_onto_itself(self) -> None:
        """RF-006-10: una fuente que ya está en la carpeta de destino no se «copia» sobre sí
        misma (la borraría): ``ValueError`` y la fuente intacta."""
        target = vector.import_dir(self.cache, "op1")
        target.mkdir(parents=True)
        source = target / "capas.gpkg"
        source.write_bytes(CAPAS.read_bytes())
        with self.assertRaises(ValueError):
            vector.copy_source(source, target)
        self.assertEqual(source.read_bytes(), CAPAS.read_bytes())

    def test_not_a_gpkg(self) -> None:
        """Una fuente que no existe o que no es SQLite: ``gis.gpkg_unreadable`` con el
        fichero y el motivo, sin copiar nada."""
        text = self.tmp / "capas.gpkg"
        text.write_text("no soy un GeoPackage", encoding="utf-8")
        target = vector.import_dir(self.cache, "op1")
        for source, reason in ((text, "no es una base de datos SQLite"),
                               (self.tmp / "falta.gpkg", "no existe")):
            with self.subTest(fuente=source.name):
                with self.assertRaises(gis.GisError) as caught:
                    vector.copy_source(source, target)
                self.assertEqual(caught.exception.code, "gis.gpkg_unreadable")
                self.assertIn(f"«{source.name}»", str(caught.exception))
                self.assertIn(reason, str(caught.exception))
        self.assertFalse(target.exists())
        self.assertEqual(text.read_text(encoding="utf-8"), "no soy un GeoPackage")


class VersionedLayersTest(unittest.TestCase):
    """RF-006-12: las cinco capas de ``gpkg/capas.gpkg`` (creadas con ``ogr2ogr``)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="geoblender-006-t15-")
        cls.copy = vector.copy_source(CAPAS, Path(cls._tmp.name) / "import" / "op")
        cls.sources = _sources()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_list_layers(self) -> None:
        """RF-006-12: nombre, tipo, Z, M, SRS (EPSG:25830, del catálogo), entidades y
        campos de cada capa, por orden alfabético; todas se pueden importar."""
        layers = vector.list_layers(self.copy)
        self.assertEqual(
            [(i.name, i.geometry_type, i.z, i.m, i.features) for i in layers],
            [
                ("contorno", "MULTIPOLYGON", 0, 0, 1),
                ("curvas_zm", "LINESTRING", 1, 1, 2),
                ("puntos_2d", "POINT", 0, 0, 3),
                ("puntos_z", "POINT", 1, 0, 20),
                ("roturas_z", "LINESTRING", 1, 0, 4),
            ],
        )
        for info in layers:
            with self.subTest(capa=info.name):
                self.assertIsInstance(info, vector.LayerInfo)
                self.assertEqual((info.srs_id, info.srs), (SRS, "EPSG:25830"))
                self.assertEqual(info.declared_crs, H25830)
                self.assertIsNone(info.problem)
                self.assertTrue(info.importable)
                self.assertEqual(info.notes, ())
                self.assertEqual(info.geometry_column, "geom")
        fields = {info.name: info.fields for info in layers}
        self.assertEqual(fields["puntos_z"], (("p", "MEDIUMINT"), ("codigo", "TEXT")))
        self.assertEqual(fields["curvas_zm"], (("cota", "REAL"),))

    def test_points_z_bit_exact(self) -> None:
        """RF-006-12: Point Z: los 20 puntos TN de ``taludes.csv``, bit a bit, con sus
        atributos y sin avisos."""
        features = vector.read_layer(self.copy, "puntos_z")
        self.assertIsInstance(features, vector.FeatureSet)
        expected, _lines = _csv_rows()
        self.assertEqual(len(features), 20)
        self.assertEqual(features.fids, tuple(range(1, 21)))
        for geometry, (_p, xyz, _code) in zip(features.geometries, expected, strict=True):
            self.assertEqual((geometry.geometry_type, geometry.has_z, geometry.had_m),
                             ("POINT", True, False))
            self.assertEqual(geometry.coords.tobytes(), np.array(xyz).tobytes())
        self.assertEqual(features.attributes["p"], tuple(int(p) for p, _x, _c in expected))
        self.assertEqual(set(features.attributes["codigo"]), {"TN"})
        report = features.report
        self.assertEqual((report.read, report.rejected, report.warnings), (20, (), ()))
        self.assertEqual(report.source, "capas.gpkg ▸ puntos_z")

    def test_linestrings_z_bit_exact(self) -> None:
        """RF-006-12: LineString Z: las cuatro roturas de ``taludes.csv``, bit a bit."""
        features = vector.read_layer(self.copy, "roturas_z")
        _points, lines = _csv_rows()
        self.assertEqual(features.attributes["linea"], ("C1", "P1", "C2", "P2"))
        for geometry, line_id in zip(features.geometries, features.attributes["linea"],
                                     strict=True):
            want = np.array([xyz for _p, xyz, _c in lines[line_id]])
            self.assertEqual(geometry.geometry_type, "LINESTRING")
            self.assertEqual(geometry.coords.tobytes(), want.tobytes())

    def test_multipolygon_2d_bit_exact(self) -> None:
        """RF-006-12: MultiPolygon 2D: un polígono con un hueco y otro aparte, bit a bit."""
        features = vector.read_layer(self.copy, "contorno")
        (geometry,) = features.geometries
        outer, hole, island = _wkt_parts(self.sources["contorno"][0], 2, 2)
        self.assertEqual((geometry.geometry_type, geometry.has_z), ("MULTIPOLYGON", False))
        self.assertEqual(len(geometry.coords), 2)
        self.assertEqual([r.tobytes() for r in geometry.coords[0]],
                         [outer.tobytes(), hole.tobytes()])
        self.assertEqual([r.tobytes() for r in geometry.coords[1]], [island.tobytes()])
        self.assertEqual(features.attributes["nombre"], ("contorno",))

    def test_points_2d_bit_exact(self) -> None:
        """RF-006-12: Point 2D, bit a bit."""
        features = vector.read_layer(self.copy, "puntos_2d")
        want = [_wkt_parts(wkt, 2, 2)[0][0] for wkt in self.sources["puntos_2d"]]
        self.assertEqual([g.has_z for g in features.geometries], [False] * 3)
        self.assertEqual([g.coords.tobytes() for g in features.geometries],
                         [w.tobytes() for w in want])

    def test_zm_drops_m_with_warning(self) -> None:
        """RF-006-12: LineString ZM: X, Y y Z bit a bit, la M descartada, y el aviso."""
        features = vector.read_layer(self.copy, "curvas_zm")
        want = [_wkt_parts(wkt, 4, 3)[0] for wkt in self.sources["curvas_zm"]]
        for geometry, line in zip(features.geometries, want, strict=True):
            self.assertEqual((geometry.has_z, geometry.had_m), (True, True))
            self.assertEqual(geometry.coords.shape, (3, 3))
            self.assertEqual(geometry.coords.tobytes(), line.tobytes())
        self.assertEqual(features.attributes["cota"], (806.0, 816.0))
        self.assertEqual(features.report.warnings,
                         ("Capa «curvas_zm»: se han descartado sus valores M.",))

    def test_unknown_layer(self) -> None:
        """Una capa que no está: ``gis.layer_not_found`` con el fichero y la capa."""
        with self.assertRaises(gis.GisError) as caught:
            vector.read_layer(self.copy, "no_existe")
        self.assertEqual(caught.exception.code, "gis.layer_not_found")
        self.assertIn("no_existe", str(caught.exception))
        self.assertIn("capas.gpkg", str(caught.exception))


class ForeignLayersTest(unittest.TestCase):
    """RF-006-12: un GeoPackage «de otro programa»."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="geoblender-006-t15-")
        source = Path(cls._tmp.name) / "otro.gpkg"
        _foreign_gpkg(source)
        cls.copy = vector.copy_source(source, Path(cls._tmp.name) / "import" / "op")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_mixed_geometries(self) -> None:
        """RF-006-12: de 10 entidades, se leen 5 (Point Z, EWKB LineString Z, Polygon Z
        *big endian*, Point M sin la M y MultiPoint Z), bit a bit; 2 vacías o nulas se
        omiten con aviso; la colección, la curva y la de otro SRS se rechazan con su
        número de entidad y su motivo; la M, descartada con aviso."""
        features = vector.read_layer(self.copy, "mixta")
        self.assertEqual(features.fids, (1, 6, 7, 8, 10))
        kinds = [(g.geometry_type, g.has_z, g.had_m) for g in features.geometries]
        self.assertEqual(kinds, [("POINT", True, False), ("LINESTRING", True, False),
                                 ("POLYGON", True, False), ("POINT", False, True),
                                 ("MULTIPOINT", True, False)])
        coords = [g.coords for g in features.geometries]
        self.assertEqual(coords[0].tobytes(), P_Z.tobytes())
        self.assertEqual(coords[1].tobytes(), EWKB_LINE.tobytes())
        self.assertEqual(coords[2][0].tobytes(), BE_RING.tobytes())
        self.assertEqual(coords[3].tobytes(), XYM[:2].tobytes())
        self.assertEqual(coords[4].tobytes(), MULTI.tobytes())
        self.assertEqual(features.attributes["nombre"],
                         ("mixta-1", "mixta-6", "mixta-7", "mixta-8", "mixta-10"))
        report = features.report
        self.assertEqual(report.read, 10)
        self.assertEqual([(r.row, r.code) for r in report.rejected],
                         [(4, "gis.feature_geometry_invalid"),
                          (5, "gis.feature_geometry_invalid"),
                          (9, "gis.feature_srs_mismatch")])
        self.assertIn("entidad 4", report.rejected[0].reason)
        self.assertIn("7", report.rejected[0].reason)
        self.assertIn("4326", report.rejected[2].reason)
        self.assertEqual(
            report.warnings,
            ("Capa «mixta»: se han descartado sus valores M.",
             "Capa «mixta» de «otro.gpkg»: se han omitido 2 entidades sin geometría (vacías "
             "o nulas)."),
        )

    def test_layer_problems(self) -> None:
        """RF-006-12: una capa de curvas o en un CRS fuera del catálogo no se puede
        importar (``problem`` y, al leerla, ``GisError``); una sin SRS EPSG, sí, pero sin
        CRS declarado y con la nota de que hay que declararlo (RF-006-04)."""
        layers = {info.name: info for info in vector.list_layers(self.copy)}
        self.assertEqual(sorted(layers), ["arcos", "geograficas", "lineas_2d", "mixta",
                                          "multilineas", "sin_srs"])
        self.assertIn("CIRCULARSTRING", layers["arcos"].problem)
        self.assertFalse(layers["arcos"].importable)
        self.assertIn("EPSG:4326", layers["geograficas"].problem)
        self.assertIsNone(layers["sin_srs"].declared_crs)
        self.assertIsNone(layers["sin_srs"].problem)
        self.assertEqual(len(layers["sin_srs"].notes), 1)
        self.assertIn("declare su CRS", layers["sin_srs"].notes[0])
        self.assertEqual(layers["mixta"].geometry_type, "GEOMETRY")
        for name, code in (("arcos", "gis.layer_geometry_unsupported"),
                           ("geograficas", "gis.layer_crs_unsupported")):
            with self.subTest(capa=name):
                with self.assertRaises(gis.GisError) as caught:
                    vector.read_layer(self.copy, name)
                self.assertEqual(caught.exception.code, code)
        features = vector.read_layer(self.copy, "sin_srs")
        self.assertEqual(features.geometries[0].coords.tobytes(), P_Z.tobytes())


class RolesTest(unittest.TestCase):
    """RF-006-12: el papel que declara el usuario para una capa (puntos o líneas de
    rotura); nunca una rotura o un punto sin cota."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="geoblender-006-t15-")
        tmp = Path(cls._tmp.name)
        cls.capas = vector.copy_source(CAPAS, tmp / "import" / "a")
        source = tmp / "otro.gpkg"
        _foreign_gpkg(source)
        cls.otro = vector.copy_source(source, tmp / "import" / "b")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_points_layer_same_as_csv(self) -> None:
        """RF-006-12: los puntos de ``puntos_z`` son, bit a bit, los TN de
        ``taludes.csv``, con su P, su código y su número de entidad."""
        features = vector.read_layer(self.capas, "puntos_z")
        point_set, report = points.points_from_features(
            features, id_field="p", code_field="codigo"
        )
        expected, _lines = _csv_rows()
        self.assertEqual(point_set.xyz.tobytes(),
                         np.array([xyz for _p, xyz, _c in expected]).tobytes())
        self.assertEqual(point_set.point_ids, tuple(p for p, _x, _c in expected))
        self.assertEqual(set(point_set.codes), {"TN"})
        self.assertEqual(point_set.source_rows, features.fids)
        self.assertEqual((report.read, report.points, report.rejected), (20, 20, ()))

    def test_breaklines_layer_same_as_csv(self) -> None:
        """RF-006-12: las roturas de ``roturas_z`` son, bit a bit, las de ``taludes.csv``,
        duras o blandas como se declare."""
        features = vector.read_layer(self.capas, "roturas_z")
        breaklines, report = points.breaklines_from_features(
            features, hard=False, id_field="linea", code_field="codigo"
        )
        _points, lines = _csv_rows()
        self.assertEqual([b.line_id for b in breaklines], ["C1", "P1", "C2", "P2"])
        for breakline in breaklines:
            want = np.array([xyz for _p, xyz, _c in lines[breakline.line_id]])
            self.assertEqual(breakline.xyz.tobytes(), want.tobytes())
            self.assertFalse(breakline.hard)
        self.assertEqual([b.code for b in breaklines], ["CABEZA", "PIE", "CABEZA", "PIE"])
        self.assertEqual(breaklines[1].source_rows, (2,) * 6)
        self.assertEqual((report.read, report.lines, report.rejected), (4, 4, ()))

    def test_no_breakline_or_point_without_elevation(self) -> None:
        """RF-006-12: una línea 2D no se acepta como rotura, ni un punto 2D como punto;
        cada entidad, rechazada con su número y su motivo."""
        breaklines, report = points.breaklines_from_features(
            vector.read_layer(self.otro, "lineas_2d")
        )
        self.assertEqual(breaklines, [])
        self.assertEqual([(r.row, r.code) for r in report.rejected],
                         [(1, "gis.feature_without_z"), (2, "gis.feature_without_z")])
        self.assertIn("línea de rotura", report.rejected[0].reason)
        point_set, report = points.points_from_features(
            vector.read_layer(self.capas, "puntos_2d")
        )
        self.assertEqual(len(point_set), 0)
        self.assertEqual([r.code for r in report.rejected], ["gis.feature_without_z"] * 3)
        self.assertIn("punto", report.rejected[0].reason)

    def test_parts_and_wrong_types(self) -> None:
        """RF-006-12: cada parte de un MultiLineString es una línea («M.1», «M.2», sin la
        M); un MultiPoint da sus puntos; una geometría de otro tipo se rechaza con su
        número y el aviso y los rechazos de la lectura se conservan."""
        features = vector.read_layer(self.otro, "multilineas")
        breaklines, report = points.breaklines_from_features(features, id_field="nombre")
        self.assertEqual([b.line_id for b in breaklines],
                         ["multilineas-1.1", "multilineas-1.2"])
        for breakline, part in zip(breaklines, PARTS_ZM, strict=True):
            self.assertEqual(breakline.xyz.tobytes(),
                             np.ascontiguousarray(part[:, :3]).tobytes())
        self.assertIn("Capa «multilineas»: se han descartado sus valores M.", report.warnings)
        point_set, report = points.points_from_features(vector.read_layer(self.otro, "mixta"))
        self.assertEqual(point_set.xyz.tobytes(), np.vstack([P_Z, MULTI]).tobytes())
        self.assertEqual(point_set.source_rows, (1, 10, 10))
        self.assertEqual(point_set.point_ids, ("1", "10", "10"))
        self.assertEqual([(r.row, r.code) for r in report.rejected],
                         [(4, "gis.feature_geometry_invalid"),
                          (5, "gis.feature_geometry_invalid"),
                          (6, "gis.feature_role_mismatch"),
                          (7, "gis.feature_role_mismatch"),
                          (8, "gis.feature_without_z"),
                          (9, "gis.feature_srs_mismatch")])
        self.assertEqual(report.points, 3)
        self.assertEqual(len(report.warnings), 2)
        _lines, report = points.breaklines_from_features(vector.read_layer(self.capas,
                                                                           "contorno"))
        self.assertEqual([r.code for r in report.rejected], ["gis.feature_role_mismatch"])
        self.assertIn("MULTIPOLYGON", report.rejected[0].reason)

    def test_reexported(self) -> None:
        for module, names in ((vector, ("LayerInfo", "FeatureSet", "list_layers",
                                        "read_layer")),
                              (points, ("points_from_features", "breaklines_from_features"))):
            for name in names:
                with self.subTest(name=name):
                    self.assertIn(name, gis.__all__)
                    self.assertIs(getattr(gis, name), getattr(module, name))


if __name__ == "__main__":
    unittest.main()

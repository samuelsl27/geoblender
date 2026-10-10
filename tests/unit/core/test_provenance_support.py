# SPDX-License-Identifier: GPL-3.0-or-later
"""Datos sintéticos y comprobaciones de procedencia para las pruebas (spec 008, T01;
plan 008 §7.1).

La tarea no cubre ningún RF por sí misma: prepara los datos con que se prueban las entradas
y el hash de contenido (RF-008-07 a RF-008-13) y la ayuda que comprueba RF-008-14 (ningún
fichero creado, modificado, renombrado ni borrado en la carpeta de una fuente, tampoco
auxiliares). Comprueba que el generador es determinista y coincide con el ``README.md`` y
con lo versionado, las áreas de los límites, la variante en WAL y que
``assert_source_untouched`` falla cuando debe y solo entonces.
"""

import csv
import hashlib
import inspect
import io
import os
import re
import shutil
import sqlite3
import unittest
from pathlib import Path

import numpy as np

from tests.support import provenance_checks, provenance_data
from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender
from tests.support.provenance_checks import assert_source_untouched
from tests.support.provenance_data import (
    BOUNDARY_V1,
    BOUNDARY_V1_QGIS,
    BOUNDARY_V2,
    COLLARS_V1,
    COLLARS_V2,
    COLLARS_V3,
    DATA_DIR,
    FILES,
    REPORT,
    generate,
    make_wal_variant,
)
from tests.support.trees import age_folders

gpkg = import_geoblender("core.gpkg")

_README_ROW = re.compile(r"^\| `([^`]+)` \| (\d+) \| `([0-9a-f]{64})` \|$")
# Lo que no puede aparecer en las ayudas: una unidad con barra, una UNC, carpetas
# absolutas de Linux o macOS, y datos de un expediente real (el origen de Silvestre).
_ABSOLUTE = re.compile(r"[A-Za-z]:[\\/]|\\\\|(?<![\w.])/(?:mnt|home|Users|tmp|var)/")
_CLIENT_DATA = ("silvestre", "736200", "736 200", "4435300", "4 435 300")
HA = 10_000.0  # m² por hectárea


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _readme_table() -> dict[str, tuple[int, str]]:
    """Las filas «| `fichero` | bytes | `sha256` |» del ``README.md`` de los datos."""
    rows: dict[str, tuple[int, str]] = {}
    for line in (DATA_DIR / "README.md").read_text(encoding="utf-8").splitlines():
        match = _README_ROW.match(line.strip())
        if match:
            rows[match.group(1)] = (int(match.group(2)), match.group(3))
    return rows


def _ring_area(ring: np.ndarray) -> float:
    """Área (m²) de un anillo cerrado, con las coordenadas relativas a su primer vértice
    (en float64: nada de restar en grande)."""
    rel = ring[:, :2] - ring[0, :2]
    x, y = rel[:, 0], rel[:, 1]
    return 0.5 * abs(float(np.dot(x[:-1], y[1:]) - np.dot(x[1:], y[:-1])))


def _polygon_area(rings: list[np.ndarray]) -> float:
    return _ring_area(rings[0]) - sum(_ring_area(ring) for ring in rings[1:])


def _features(path: Path) -> list[tuple[int, bytes, str, str]]:
    """``(fid, geom, codigo, tipo)`` de la capa de límites, en orden físico."""
    with gpkg.GpkgConnection.open_read(path) as db:
        rows = db.connection.execute(
            f'SELECT fid, geom, codigo, tipo FROM "{provenance_data.LAYER}" ORDER BY rowid'
        ).fetchall()
    return [(int(fid), bytes(geom), str(code), str(kind)) for fid, geom, code, kind in rows]


def _area_ha(path: Path) -> float:
    total = 0.0
    for _fid, blob, _code, _kind in _features(path):
        geometry = gpkg.decode_geometry(blob)
        if geometry.geometry_type == "POLYGON":
            total += _polygon_area(geometry.coords)
        else:  # MULTIPOLYGON
            total += sum(_polygon_area(part) for part in geometry.coords)
    return total / HA


def _contents(path: Path) -> tuple[str, int, int]:
    """``last_change``, el SRS de la capa y su código EPSG en ``gpkg_spatial_ref_sys``."""
    with gpkg.GpkgConnection.open_read(path) as db:
        conn = db.connection
        (last_change,) = conn.execute(
            "SELECT last_change FROM gpkg_contents WHERE table_name = ?",
            (provenance_data.LAYER,),
        ).fetchone()
        (srs_id,) = conn.execute(
            "SELECT srs_id FROM gpkg_geometry_columns WHERE table_name = ?",
            (provenance_data.LAYER,),
        ).fetchone()
        (epsg,) = conn.execute(
            "SELECT organization_coordsys_id FROM gpkg_spatial_ref_sys "
            "WHERE srs_id = ? AND organization = 'EPSG'",
            (srs_id,),
        ).fetchone()
    return str(last_change), int(srs_id), int(epsg)


def _csv_rows(name: str) -> list[list[str]]:
    text = (DATA_DIR / name).read_bytes().decode("utf-8")
    return list(csv.reader(io.StringIO(text, newline=""), delimiter=";"))


class GeneratorTest(unittest.TestCase):
    def test_generator_is_deterministic_and_matches_readme(self) -> None:
        """Spec 008, T01 (datos de RF-008-07 a 13): dos ejecuciones del generador dan
        los mismos bytes, con el tamaño y el sha256 del ``README.md``, y lo versionado en
        ``tests/data/core/provenance/`` es exactamente eso."""
        table = _readme_table()
        self.assertEqual(sorted(table), sorted(FILES))
        with project_tmp("gb-008-a-") as first, project_tmp("gb-008-b-") as second:
            digests_a = generate(first)
            digests_b = generate(second)
            self.assertEqual(sorted(p.name for p in first.iterdir()), sorted(FILES))
            for name in FILES:
                with self.subTest(fichero=name):
                    data_a = (first / name).read_bytes()
                    self.assertEqual(data_a, (second / name).read_bytes())
                    self.assertEqual(digests_a[name], digests_b[name])
                    self.assertEqual(
                        (len(data_a), hashlib.sha256(data_a).hexdigest()),
                        table[name],
                        f"«{name}» no coincide con el README (SQLite "
                        f"{sqlite3.sqlite_version}): si cambió SQLite o el catálogo de "
                        "CRS, regenere los datos y el README (véase el README)",
                    )
        for name in FILES:
            with self.subTest(versionado=name):
                path = DATA_DIR / name
                self.assertEqual((path.stat().st_size, _sha256(path)), table[name])

    def test_support_has_no_absolute_paths_or_client_data(self) -> None:
        """Spec 008, T01: las ayudas y el README no llevan rutas absolutas ni datos de un
        expediente real (constitución, principio 7)."""
        texts = {
            "provenance_data": inspect.getsource(provenance_data),
            "provenance_checks": inspect.getsource(provenance_checks),
            "README.md": (DATA_DIR / "README.md").read_text(encoding="utf-8"),
        }
        for name, text in texts.items():
            with self.subTest(fichero=name):
                self.assertIsNone(_ABSOLUTE.search(text))
                for needle in _CLIENT_DATA:
                    self.assertNotIn(needle, text.lower())


class BoundaryDataTest(unittest.TestCase):
    def test_areas(self) -> None:
        """Spec 008, T01 (RF-008-08): las tres parcelas de ``Limites_v1`` suman
        12,000 0 ha y las de ``Limites_v2`` (un vértice movido), 13,430 0 ha (±10⁻⁹);
        ``Limites_v1_qgis``, lo mismo que v1. Todas en EPSG:25830."""
        expected = {BOUNDARY_V1: 12.0, BOUNDARY_V1_QGIS: 12.0, BOUNDARY_V2: 13.43}
        for name, area in expected.items():
            with self.subTest(fichero=name):
                self.assertAlmostEqual(_area_ha(DATA_DIR / name), area, delta=1e-9)
                self.assertEqual(len(_features(DATA_DIR / name)), 3)
                _last, srs_id, epsg = _contents(DATA_DIR / name)
                self.assertEqual((srs_id, epsg), (25830, 25830))

    def test_qgis_rewrite_same_content_other_file(self) -> None:
        """Spec 008, T01 (RF-008-08): ``Limites_v1_qgis`` tiene las mismas entidades que
        v1 (geometría y atributos) en otro orden y con otros ``fid``, otro
        ``last_change``, sin páginas libres (``VACUUM``) y otra huella del fichero; v2
        cambia la geometría de una sola parcela."""
        paths = [DATA_DIR / name for name in (BOUNDARY_V1, BOUNDARY_V1_QGIS, BOUNDARY_V2)]
        v1, qgis, v2 = (_features(path) for path in paths)
        last_v1, last_qgis, last_v2 = (_contents(path)[0] for path in paths)
        self.assertEqual(sorted(f[1:] for f in v1), sorted(f[1:] for f in qgis))
        self.assertNotEqual([f[2] for f in v1], [f[2] for f in qgis])
        self.assertTrue(set(f[0] for f in v1).isdisjoint(f[0] for f in qgis))
        self.assertEqual(len({last_v1, last_qgis, last_v2}), 3)
        self.assertNotEqual(_sha256(paths[0]), _sha256(paths[1]))
        with gpkg.GpkgConnection.open_read(paths[1]) as db:
            freelist = db.connection.execute("PRAGMA freelist_count").fetchone()[0]
        self.assertEqual(freelist, 0)
        changed = [a[2] for a, b in zip(v1, v2, strict=True) if a[1:] != b[1:]]
        self.assertEqual(changed, ["P-02"])
        self.assertEqual([f[2:] for f in v1], [f[2:] for f in v2])


class TableAndDocumentDataTest(unittest.TestCase):
    def test_collars(self) -> None:
        """Spec 008, T01 (RF-008-07, 08): 15 sondeos en ``collares_v1.csv`` («;» y coma
        decimal); v2 cambia una sola cota y v3 renombra una sola columna de v2."""
        v1, v2, v3 = (_csv_rows(name) for name in (COLLARS_V1, COLLARS_V2, COLLARS_V3))
        self.assertEqual(len(v1), 16)
        self.assertEqual(len({row[0] for row in v1[1:]}), 15)
        self.assertEqual(v1[0], v2[0])
        cells = [
            (r, c)
            for r, (row1, row2) in enumerate(zip(v1, v2, strict=True))
            for c, (a, b) in enumerate(zip(row1, row2, strict=True))
            if a != b
        ]
        self.assertEqual(len(cells), 1)
        self.assertEqual(v1[0][cells[0][1]], "cota")
        renamed = [c for c, (a, b) in enumerate(zip(v2[0], v3[0], strict=True)) if a != b]
        self.assertEqual(len(renamed), 1)
        self.assertEqual(v2[1:], v3[1:])
        for row in v1[1:]:
            for value in row[1:]:
                self.assertRegex(value, r"^\d+,\d{2}$")

    def test_report(self) -> None:
        """Spec 008, T01 (RF-008-07): ``informe.pdf`` es un PDF mínimo (cabecera y fin
        de fichero) de menos de 1 KiB."""
        data = (DATA_DIR / REPORT).read_bytes()
        self.assertTrue(data.startswith(b"%PDF-1."))
        self.assertTrue(data.rstrip().endswith(b"%%EOF"))
        self.assertLess(len(data), 1024)


class WalVariantTest(unittest.TestCase):
    def test_wal_variant(self) -> None:
        """Spec 008, T01 (RF-008-09, 14): la variante en WAL de ``Limites_v1`` tiene la
        cabecera en WAL y un ``-wal`` no vacío con una edición pendiente, y el tamaño y la
        fecha del principal no cambian con la edición; el principal solo da 12 ha y con su
        ``-wal``, 13,43 ha. Prepararla no toca ``tests/data`` y leerla en una copia
        privada no toca su carpeta."""
        with project_tmp("gb-008-wal-") as tmp:
            folder = tmp / "fuente"
            folder.mkdir()
            with assert_source_untouched(DATA_DIR):
                variant = make_wal_variant(folder)
            header = gpkg.read_header(variant.path)
            self.assertEqual(header.journal, "wal")
            self.assertTrue(header.has_wal)
            self.assertEqual(variant.wal, Path(f"{variant.path}-wal"))
            self.assertGreater(variant.wal.stat().st_size, 0)
            stat = variant.path.stat()
            self.assertEqual(
                (stat.st_size, stat.st_mtime_ns), (variant.main_size, variant.main_mtime_ns)
            )
            main_only = tmp / "solo" / variant.path.name
            main_only.parent.mkdir()
            shutil.copyfile(variant.path, main_only)
            with assert_source_untouched(folder):
                pending = gpkg.private_copy(variant.path, tmp / "privada")
            before = gpkg.private_copy(main_only, tmp / "privada_solo")
            self.assertAlmostEqual(_area_ha(before), 12.0, delta=1e-9)
            self.assertAlmostEqual(_area_ha(pending), 13.43, delta=1e-9)


class SourceUntouchedTest(unittest.TestCase):
    def _source(self, tmp: Path) -> Path:
        folder = tmp / "fuente"
        folder.mkdir()
        for name in (BOUNDARY_V1, COLLARS_V1):
            shutil.copyfile(DATA_DIR / name, folder / name)
        age_folders(folder)
        return folder

    def test_reading_passes(self) -> None:
        """RF-008-14: leer la fuente (bytes y SQLite en solo lectura, en diario clásico)
        no deja rastro y la comprobación pasa."""
        with project_tmp("gb-008-src-") as tmp:
            folder = self._source(tmp)
            with assert_source_untouched(folder):
                (folder / COLLARS_V1).read_bytes()
                self.assertEqual(len(_features(folder / BOUNDARY_V1)), 3)

    def test_new_wal_fails(self) -> None:
        """RF-008-14: un ``-wal`` nuevo junto a la fuente hace fallar la comprobación, que
        lo nombra como auxiliar."""
        with project_tmp("gb-008-src-") as tmp:
            folder = self._source(tmp)
            with self.assertRaises(AssertionError) as caught:
                with assert_source_untouched(folder):
                    (folder / f"{BOUNDARY_V1}-wal").write_bytes(b"\0" * 32)
            self.assertIn(f"{BOUNDARY_V1}-wal", str(caught.exception))
            self.assertIn("auxiliar", str(caught.exception))

    def test_changed_byte_fails(self) -> None:
        """RF-008-14: cambiar un byte de la fuente falla aunque se restauren su tamaño y su
        fecha (lo ve el sha256)."""
        with project_tmp("gb-008-src-") as tmp:
            folder = self._source(tmp)
            path = folder / COLLARS_V1
            with self.assertRaises(AssertionError) as caught:
                with assert_source_untouched(folder):
                    stat = path.stat()
                    data = bytearray(path.read_bytes())
                    data[-2] = ord("9") if data[-2] != ord("9") else ord("8")
                    path.write_bytes(bytes(data))
                    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            self.assertIn(COLLARS_V1, str(caught.exception))
            self.assertIn("sha256", str(caught.exception))

    def test_rename_delete_and_transient_fail(self) -> None:
        """RF-008-14: renombrar, borrar o crear y borrar un auxiliar (``-journal``,
        ``.aux.xml``, ``.ldb``…) en la carpeta de la fuente hace fallar la comprobación."""
        actions = {
            "renombrar": (
                lambda f: (f / COLLARS_V1).rename(f / "collares.csv"),
                ("nuevo: collares.csv", f"borrado: {COLLARS_V1}"),
            ),
            "borrar": (lambda f: (f / COLLARS_V1).unlink(), (f"borrado: {COLLARS_V1}",)),
            "auxiliar efímero": (
                lambda f: (
                    (f / f"{BOUNDARY_V1}-journal").write_bytes(b"x"),
                    (f / f"{BOUNDARY_V1}-journal").unlink(),
                ),
                ("la fecha de la carpeta",),
            ),
        }
        for label, (action, expected) in actions.items():
            with self.subTest(accion=label), project_tmp("gb-008-src-") as tmp:
                folder = self._source(tmp)
                with self.assertRaises(AssertionError) as caught:
                    with assert_source_untouched(folder):
                        action(folder)
                for text in expected:
                    self.assertIn(text, str(caught.exception))


if __name__ == "__main__":
    unittest.main()

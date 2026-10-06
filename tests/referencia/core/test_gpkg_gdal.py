# SPDX-License-Identifier: GPL-3.0-or-later
"""El GeoPackage del proyecto leído con el GDAL de QGIS (spec 002, T35; RF-002-14; plan
002 §7, ``tests/referencia/core``; ADR-0006, «Cómo se verifica», QGIS).

Caso de referencia: un proyecto creado por ``core`` (ajustes sintéticos de
``tests.support.core_fixtures``) con dos capas escritas con ``core.gpkg`` (WKB propio,
sin GDAL): ``gis_bnd_referencia`` (``MULTIPOLYGON``: un polígono con un hueco y otro de
dos partes) y ``gis_pts_referencia`` (``POINT`` con Z), con coordenadas UTM con
milímetros que no son exactas en binario. La referencia externa es el GDAL de QGIS 4.2
(``GEOBLENDER_QGIS_DIR``, con su PROJ y sin el ``PROJ_LIB`` del puesto):

- ``validate_gpkg.py`` termina con 0 y sin escribir nada;
- ``ogrinfo -ro -al`` termina con 0 y no emite ninguna línea con «Warning» ni «ERROR», y
  lista las dos capas y las tablas internas;
- las coordenadas que lee ``osgeo.ogr`` son las escritas, bit a bit (tolerancia:
  ninguna), con EPSG:25830 y el tipo de geometría de cada capa;
- GDAL solo lee: los ficheros del proyecto (nombres, tamaños, sha256 y fechas) no
  cambian, y no aparece ninguno (``-wal``, ``-shm``, ``.aux.xml``).

Sin QGIS (sin la variable, o sin su GDAL) la clase se omite con «[ENTORNO] qgis», que
``tools/check.py`` cuenta como «VERDE CON OMISIONES»; la spec 002 no se cierra sin una
ejecución con QGIS anotada en su T35.
"""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from tests.support import qgis
from tests.support.core_fixtures import make_session, make_settings
from tests.support.package import import_geoblender
from tests.support.resources import requires

create = import_geoblender("core.project.create")
base = import_geoblender("core.gpkg.base")
gpkg = import_geoblender("core.gpkg")
userdata_mod = import_geoblender("core.userdata")

POLYGONS_LAYER = "gis_bnd_referencia"
POINTS_LAYER = "gis_pts_referencia"
LAYERS = (POLYGONS_LAYER, POINTS_LAYER)
INTERNAL_TABLES = ("gb_project", "gb_event", "gb_schema_migration")
EPSG = 25830

# Coordenadas absolutas (EPSG:25830) con milímetros, dentro de la ventana sintética.
POLYGONS: dict[str, list[list[list[list[float]]]]] = {
    "con hueco": [
        [
            [
                [699_600.125, 4_399_600.250],
                [700_400.375, 4_399_600.500],
                [700_400.625, 4_400_400.875],
                [699_600.001, 4_400_400.999],
                [699_600.125, 4_399_600.250],
            ],
            [
                [699_900.111, 4_399_900.222],
                [699_900.333, 4_400_100.444],
                [700_100.555, 4_400_100.666],
                [700_100.777, 4_399_900.888],
                [699_900.111, 4_399_900.222],
            ],
        ]
    ],
    "dos partes": [
        [
            [
                [699_510.001, 4_399_510.002],
                [699_590.003, 4_399_510.004],
                [699_590.005, 4_399_590.006],
                [699_510.001, 4_399_510.002],
            ]
        ],
        [
            [
                [700_410.123, 4_400_410.456],
                [700_490.789, 4_400_410.012],
                [700_490.345, 4_400_490.678],
                [700_410.123, 4_400_410.456],
            ]
        ],
    ],
}
POINTS: dict[str, list[float]] = {
    "estación 1": [700_123.456, 4_400_987.654, 850.123],
    "estación 2": [699_501.001, 4_399_501.999, -12.345],
    "estación 3": [700_499.999, 4_400_499.001, 1_234.567],
}

# Se ejecuta con el Python de QGIS (osgeo): vuelca a JSON, con la representación exacta
# de cada número, las capas pedidas (tipo, EPSG y coordenadas por el campo «nombre»).
READER = r"""
import json
import sys

from osgeo import gdal, ogr

gdal.UseExceptions()


def coords(geometry):
    if geometry.GetGeometryCount() > 0:
        return [coords(geometry.GetGeometryRef(i)) for i in range(geometry.GetGeometryCount())]
    dim = geometry.CoordinateDimension()
    return [list(geometry.GetPoint(i))[:dim] for i in range(geometry.GetPointCount())]


dataset = gdal.OpenEx(sys.argv[1], gdal.OF_VECTOR | gdal.OF_READONLY)
found = {"gdal": gdal.__version__, "layers": {}}
for name in sys.argv[2:]:
    layer = dataset.GetLayerByName(name)
    srs = layer.GetSpatialRef()
    features = {}
    for feature in layer:
        features[feature.GetField("nombre")] = coords(feature.GetGeometryRef())
    found["layers"][name] = {
        "geometry": ogr.GeometryTypeToName(layer.GetGeomType()),
        "epsg": None if srs is None else srs.GetAuthorityCode(None),
        "features": features,
    }
internal = dataset.ExecuteSQL("SELECT name FROM gb_project")
found["gb_project"] = internal.GetNextFeature().GetField(0)
dataset.ReleaseResultSet(internal)
print(json.dumps(found))
"""


def _snapshot(root: Path) -> dict[str, object]:
    """Cada fichero (tamaño, sha256 y fecha) y cada carpeta de ``root``, recursivo."""
    found: dict[str, object] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_dir():
            found[rel] = "carpeta"
        else:
            stat = path.stat()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            found[rel] = (stat.st_size, digest, stat.st_mtime_ns)
    return found


def _write_layers(project: object, srs_id: int) -> None:
    """Las dos capas de referencia, escritas con ``core.gpkg`` en una transacción."""
    name_column = base.ColumnDef("nombre", "TEXT", not_null=True)
    with project.write_transaction() as conn:  # type: ignore[attr-defined]
        base.create_feature_table(
            conn, POLYGONS_LAYER, "MULTIPOLYGON", srs_id, False, [name_column],
            identifier="Límites de referencia",
            description="Capa sintética de la prueba con GDAL (spec 002, T35)",
        )
        base.create_feature_table(
            conn, POINTS_LAYER, "POINT", srs_id, True, [name_column],
            identifier="Puntos de referencia",
            description="Capa sintética de la prueba con GDAL (spec 002, T35)",
        )
        for name, polygons in POLYGONS.items():
            parts = [
                [np.array(ring, dtype=np.float64) for ring in polygon] for polygon in polygons
            ]
            blob = gpkg.encode_geometry("MULTIPOLYGON", parts, srs_id, False)
            conn.execute(
                f"INSERT INTO {POLYGONS_LAYER} (geom, nombre) VALUES (?, ?)", (blob, name)
            )
        for name, point in POINTS.items():
            blob = gpkg.encode_geometry("POINT", np.array(point, dtype=np.float64), srs_id, True)
            conn.execute(
                f"INSERT INTO {POINTS_LAYER} (geom, nombre) VALUES (?, ?)", (blob, name)
            )


@requires(qgis.QGIS, qgis.QGIS_HINT)
class GdalReadsProjectTest(unittest.TestCase):
    """Un proyecto creado por ``core``, cerrado, y lo que dice el GDAL de QGIS de él."""

    @classmethod
    def setUpClass(cls) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="geoblender-gdal-", ignore_cleanup_errors=True)
        cls.addClassCleanup(tmp.cleanup)
        folder = Path(tmp.name)
        (folder / "proyectos").mkdir()
        created = create.create_project(
            folder / "proyectos",
            make_settings(name="Referencia GDAL"),
            make_session(),
            userdata_mod.UserData(folder / "datos_usuario"),
        )
        cls.srs_id = created.record.crs_epsg
        _write_layers(created.project, cls.srs_id)
        cls.close_warnings = created.project.close()
        cls.root = created.root
        cls.database = created.root / "project.gpkg"
        cls.before = _snapshot(created.root)
        cls.validate = qgis.run_python(qgis.validate_gpkg_script(), str(cls.database))
        cls.ogrinfo = qgis.run_tool("ogrinfo", "-ro", "-al", str(cls.database))
        cls.reader = qgis.run_python("-c", READER, str(cls.database), *LAYERS)
        cls.after = _snapshot(created.root)

    def test_validate_gpkg_exits_with_0(self) -> None:
        """RF-002-14: ``validate_gpkg.py`` del GDAL de QGIS da por bueno el GeoPackage
        del proyecto (código 0) sin escribir ningún aviso."""
        output = qgis.output_of(self.validate)
        self.assertEqual(self.close_warnings, ())
        self.assertEqual(self.validate.returncode, 0, output)
        self.assertEqual(output, "", output)

    def test_ogrinfo_lists_everything_without_warnings(self) -> None:
        """RF-002-14: ``ogrinfo -ro -al`` termina con 0, no emite ninguna línea con
        «Warning» ni «ERROR» y lista las dos capas y las tablas internas."""
        output = qgis.output_of(self.ogrinfo)
        self.assertEqual(self.ogrinfo.returncode, 0, output)
        noisy = [
            line for line in output.splitlines() if "warning" in line.lower() or "ERROR" in line
        ]
        self.assertEqual(noisy, [], output[:4000])
        for name in (*LAYERS, *INTERNAL_TABLES):
            with self.subTest(capa=name):
                self.assertIn(f"Layer name: {name}", output)

    def test_coordinates_read_by_gdal_are_bit_exact(self) -> None:
        """RF-002-14: GDAL lee cada capa con EPSG:25830 y su tipo (``Multi Polygon`` y
        ``3D Point``), y sus coordenadas son las escritas, bit a bit (sin tolerancia),
        también la Z; la tabla interna ``gb_project`` se lee."""
        output = qgis.output_of(self.reader)
        self.assertEqual(self.reader.returncode, 0, output)
        found = json.loads(self.reader.stdout)
        layers = found["layers"]
        self.assertEqual(layers[POLYGONS_LAYER]["geometry"], "Multi Polygon")
        self.assertEqual(layers[POINTS_LAYER]["geometry"], "3D Point")
        for name in LAYERS:
            with self.subTest(capa=name):
                self.assertEqual(layers[name]["epsg"], str(EPSG))
        self.assertEqual(layers[POLYGONS_LAYER]["features"], POLYGONS)
        self.assertEqual(
            layers[POINTS_LAYER]["features"], {name: [p] for name, p in POINTS.items()}
        )
        self.assertEqual(found["gb_project"], "Referencia GDAL")

    def test_gdal_only_reads_the_project(self) -> None:
        """RF-002-14, RF-002-16: tras ``validate_gpkg.py``, ``ogrinfo`` y la lectura,
        los ficheros del proyecto (nombres, tamaños, sha256 y fechas) son los mismos y no
        aparece ninguno nuevo (``-wal``, ``-shm``, ``.aux.xml``); la base sigue en diario
        clásico."""
        self.assertEqual(self.after, self.before)
        self.assertEqual(gpkg.read_header(self.database).journal, "classic")


if __name__ == "__main__":
    unittest.main()

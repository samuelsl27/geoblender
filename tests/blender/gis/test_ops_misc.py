# SPDX-License-Identifier: GPL-3.0-or-later
"""Transformar coordenadas e importar un fichero en Blender (spec 006, T32; HU-006-5; plan 006
§5.3.5 y §5.5).

Con el proyecto, las fuentes y el servicio de CRS de las órdenes de ``test_ops_dtm``
(``DtmOperatorsCase``), aquí uno de prueba con ED50 → ETRS89 (la traslación del vértice IGNE de
la red REGENTE, 0,2 m con la rejilla del IGN), el factor de escala y la convergencia.

- RF-006-07: ``geoblender.core_transform_coordinates`` (Proyecto ▸ Georreferencia ▸ Transformar
  coordenadas…) transforma coordenadas tecleadas con coma decimal (varios puntos, con y sin Z)
  entre dos CRS del catálogo y muestra el resultado con 1 mm, la transformación usada y su
  precisión, y el factor de escala y la convergencia de cuadrícula (grados, positiva al este del
  meridiano central) en el destino; no necesita proyecto ni escribe en él. Un número mal
  escrito o un punto sin X e Y se rechazan nombrando el punto; sin una transformación de
  precisión conocida, no se muestra ninguna coordenada.
- RF-006-31: con otra versión de pyproj, la orden no se abre y dice la hallada y la esperada.
- RF-006-27: ``geoblender.io_import_file`` (Importar ▸ Importar un fichero…, y al soltar un
  fichero en la Vista 3D con ``GEOBLENDER_FH_io_import_file``) abre el importador de su
  extensión: ``.tif``, ``.tiff`` y ``.asc``, el de MDT; ``.xyz`` en malla, el de MDT, y disperso,
  el de puntos; ``.csv`` y ``.txt``, el de puntos; ``.gpkg``, el de capas. Una extensión que no
  se admite se rechaza con la entrada del roadmap que la traerá, sin abrir nada. Sin proyecto,
  no está disponible; soltar un GeoTIFF en la vista importa el MDT.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.blender.gis.test_ops_dtm import DtmOperatorsCase, _module

TRANSFORM = "geoblender.core_transform_coordinates"
IMPORT_FILE = "geoblender.io_import_file"
IMPORT_DTM = "geoblender.gis_import_dtm"
IMPORT_POINTS = "geoblender.gis_import_points"
IMPORT_VECTOR = "geoblender.gis_import_vector"
EXTENSIONS = ".tif;.tiff;.asc;.xyz;.csv;.txt;.gpkg"
# La traslación de ED50 a ETRS89 en el vértice 55901 «IGNE» (reseña del IGN; la prueba con
# pyproj y la rejilla está en tests/unit/adapters/test_pyproj_crs.py) y su factor de escala.
IGNE_SHIFT = (439830.795 - 439940.19, 4477484.219 - 4477691.67, 0.0)
IGNE_SCALE = 0.999644563
THIN = " "  # el separador de miles en español (espacio fino sin ruptura)


class _Shift:
    """Una transformación de prueba: traslada las coordenadas."""

    def __init__(self, info: Any) -> None:
        self.info = info

    def apply(self, xyz: np.ndarray) -> np.ndarray:
        return np.asarray(xyz, dtype=np.float64) + np.array(IGNE_SHIFT)


class _Ed50Service:
    """El servicio de CRS de prueba: ED50 → ETRS89 (0,2 m o de precisión desconocida), el
    factor de escala del vértice y la convergencia (x − 500 000) / 130 000 grados; apunta lo
    que se le pide."""

    def __init__(self, ports: ModuleType, accuracy: float | None = 0.2) -> None:
        self.info = ports.TransformInfo(
            "Inverse of UTM zone 30N + ED50 to ETRS89 (12) + UTM zone 30N", accuracy,
            ("es_ign_SPED2ETV2.tif",))
        self.asked: list[tuple[Any, ...]] = []
        self.factors: list[tuple[str, int, np.ndarray]] = []

    def identify_wkt(self, wkt: str) -> None:
        return None

    def transformer(self, src: Any, src_v: Any, dst: Any, dst_v: Any) -> _Shift:
        self.asked.append((src.epsg, src_v.epsg, dst.epsg, dst_v.epsg))
        return _Shift(self.info)

    def scale_factor(self, crs: Any, xy: np.ndarray) -> np.ndarray:
        self.factors.append(("k", crs.epsg, np.array(xy)))
        return np.full(len(xy), IGNE_SCALE)

    def grid_convergence(self, crs: Any, xy: np.ndarray) -> np.ndarray:
        self.factors.append(("γ", crs.epsg, np.array(xy)))
        return (np.asarray(xy)[:, 0] - 500_000.0) / 130_000.0


class MiscOperatorsTest(DtmOperatorsCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.core_ops = _module("bl.ops.core")
        cls.io_ops = _module("bl.ops.io")
        cls.commands = _module("bl.ui.commands")

    def transform(self, text: str, **props: Any) -> list[str]:
        """Transforma ``text`` de ED50 / UTM 30N a ETRS89 / UTM 30N (Alicante en los dos) y
        devuelve las líneas del resultado."""
        values = {"source_crs": "23030", "source_vertical": "5782", "target_crs": "25830",
                  "target_vertical": "5782", **props}
        result = bpy.ops.geoblender.core_transform_coordinates("EXEC_DEFAULT", text=text,
                                                               **values)
        self.assertEqual(result, {"FINISHED"})
        return self.core_ops.last_transform()

    def refused(self, idname: str, **props: Any) -> str:
        """El mensaje con el que la orden ``idname`` se niega."""
        group, name = idname.split(".")
        with self.assertRaises(RuntimeError) as caught:
            getattr(getattr(bpy.ops, group), name)("EXEC_DEFAULT", **props)
        return str(caught.exception)

    # --- Las dos órdenes ----------------------------------------------------------------------

    def test_real_operators_and_the_file_handler(self) -> None:
        """RF-006-27, RF-006-07: las dos órdenes son las reales (no las provisionales de la 003)
        y están disponibles; el manejador de ficheros abre «Importar un fichero» con las
        extensiones de la 006 al soltar un fichero en una Vista 3D (en otro editor, no). Sin
        proyecto, importar no está disponible (dice el paso previo) y transformar, sí."""
        for idname in (TRANSFORM, IMPORT_FILE):
            with self.subTest(orden=idname):
                cls = self.commands.registered_class(idname)
                self.assertIsNotNone(cls)
                self.assertFalse(self.commands.is_provisional(cls))
                self.assertTrue(self.commands.is_available(idname))
        handler = self.io_ops.GEOBLENDER_FH_io_import_file
        self.assertTrue(handler.is_registered)
        self.assertEqual((handler.bl_import_operator, handler.bl_file_extensions),
                         (IMPORT_FILE, EXTENSIONS))
        for area, expected in (("VIEW_3D", True), ("PROPERTIES", False), (None, False)):
            with self.subTest(area=area):
                shown = None if area is None else SimpleNamespace(type=area)
                self.assertIs(handler.poll_drop(SimpleNamespace(area=shown)), expected)
        self.assertFalse(bpy.ops.geoblender.io_import_file.poll())
        self.assertTrue(self.io_ops.unavailable_reason().startswith("Primero abra un proyecto"))
        self.assertTrue(bpy.ops.geoblender.core_transform_coordinates.poll())
        self.open()
        self.assertTrue(bpy.ops.geoblender.io_import_file.poll())

    # --- Transformar coordenadas --------------------------------------------------------------

    def test_typed_coordinates_with_their_transformation_and_factors(self) -> None:
        """RF-006-07: dos puntos tecleados con coma decimal y separados por «;» (el primero con
        Z) pasan de ED50 a ETRS89: cada uno con 1 mm, la transformación usada con su precisión
        y su rejilla, y el factor de escala y la convergencia (grados, positiva al este del
        meridiano central) calculados en el destino con las coordenadas ya transformadas. La
        misma referencia en los dos lados da las mismas coordenadas, sin transformación."""
        self.fake = _Ed50Service(self.ports)
        lines = self.transform("439940,19 4477691,67 714,611; 440000 4478000\n")
        text = "\n".join(lines)
        self.assertEqual(self.fake.asked, [(23030, 5782, 25830, 5782)])
        moved = np.array([[439940.19, 4477691.67, 714.611], [440000.0, 4478000.0, 0.0]])
        moved += np.array(IGNE_SHIFT)
        for kind, epsg, xy in self.fake.factors:
            with self.subTest(factor=kind):
                self.assertEqual(epsg, 25830)
                np.testing.assert_array_equal(xy, moved[:, :2])
        self.assertIn("EPSG:23030 + EPSG:5782", lines[0])
        self.assertIn("EPSG:25830 + EPSG:5782", lines[0])
        self.assertIn("ED50 to ETRS89 (12)", text)
        self.assertIn("precisión 0,2 m; rejilla es_ign_SPED2ETV2.tif", text)
        first = next(line for line in lines if line.startswith("Punto 1:"))
        self.assertIn(f"X 439{THIN}940,190  Y 4{THIN}477{THIN}691,670  Z 714,611 → "
                      f"X 439{THIN}830,795  Y 4{THIN}477{THIN}484,219  Z 714,611 m", first)
        self.assertIn("factor de escala 0,999644563", first)
        self.assertIn("convergencia -0,462840°", first)  # (439 830,795 − 500 000) / 130 000
        second = next(line for line in lines if line.startswith("Punto 2:"))
        self.assertIn(f"X 440{THIN}000,000  Y 4{THIN}478{THIN}000,000 → "
                      f"X 439{THIN}890,605  Y 4{THIN}477{THIN}792,549 m", second)
        self.assertNotIn("Z ", second)
        self.assertIn("positiva al este del meridiano central", text)
        self.assertIsNone(self.ps.current())  # sin proyecto
        same = self.transform("500000 4427757 650", source_crs="25830")
        self.assertIn("Sin transformación", "\n".join(same))
        self.assertIn("X 500{THIN}000,000  Y 4{THIN}427{THIN}757,000  Z 650,000 → "
                      "X 500{THIN}000,000".replace("{THIN}", THIN), "\n".join(same))
        self.assertEqual(len(self.fake.asked), 1)

    def test_rejected_coordinates_and_transformations(self) -> None:
        """RF-006-07, RF-006-31: un número mal escrito nombra el punto y el eje; un punto sin X
        e Y, o nada tecleado, dice cómo escribirlos; sin una transformación de precisión
        conocida no se muestra ninguna coordenada (nombra los dos CRS); con otra versión de
        pyproj la orden no se abre y dice la hallada y la esperada. En un proyecto abierto,
        nada cambia en él."""
        self.open()
        before = self.counts()
        self.fake = _Ed50Service(self.ports)
        props = {"source_crs": "23030", "target_crs": "25830"}
        message = self.refused(TRANSFORM, text="439940,19 4477691,67; 440000 4478000,1,2",
                               **props)
        self.assertIn("Punto 2", message)
        self.assertIn("Y", message)
        self.assertIn("«4478000,1,2»", message)
        message = self.refused(TRANSFORM, text="439940,19", **props)
        self.assertIn("Punto 1 «439940,19»", message)
        self.assertIn("X Y o X Y Z", message)
        self.assertIn("X Y o X Y Z", self.refused(TRANSFORM, text="  ", **props))
        self.fake = _Ed50Service(self.ports, accuracy=None)
        message = self.refused(TRANSFORM, text="439940,19 4477691,67", **props)
        self.assertIn("No hay una transformación de precisión conocida de EPSG:23030", message)
        self.assertIn("las coordenadas no se han transformado", message)

        def other_pyproj() -> None:
            raise self.ports.CrsServiceUnavailable("gis.crs_service_version", found="3.7.1",
                                                   expected="3.8.0")

        with mock.patch.object(self.gis_ops, "crs_resolver", other_pyproj):
            # Con interfaz, la orden ni abre su diálogo (``invoke``); sin ella, ``blender -b``
            # ejecuta directamente, y lo primero que mira es el servicio.
            message = self.refused(TRANSFORM, text="439940,19 4477691,67", **props)
        self.assertIn("Las transformaciones de coordenadas están desactivadas", message)
        self.assertIn("pyproj 3.7.1", message)
        self.assertIn("necesita 3.8.0", message)
        self.assertEqual(self.counts(), before)

    # --- Importar un fichero ------------------------------------------------------------------

    def test_each_extension_opens_its_importer(self) -> None:
        """RF-006-27: cada extensión abre su importador con el fichero: GeoTIFF y ASC, el de MDT
        con su diálogo; ``.xyz`` en malla, el de MDT con su decimal, y disperso, el de puntos
        con su separador, su decimal y sin cabecera; CSV y TXT, el de puntos; GeoPackage, el de
        capas. Si la entrada que trae un formato ya estuviera entregada, se abriría su orden."""
        self.open()
        opened: list[tuple[str, dict[str, Any]]] = []
        self.enterContext(mock.patch.object(
            self.io_ops, "open_importer",
            lambda idname, values, context=None: opened.append((idname, dict(values)))))
        dialog = {"dialog": True}
        cases = (
            (self.source("geotiff/f64_strip.tif"), IMPORT_DTM, dialog),
            (self.source("geotiff/f64_strip.tif", "MDT_VUELO.TIFF"), IMPORT_DTM, dialog),
            (self.source("asc/corner.asc"), IMPORT_DTM, dialog),
            (self.source("xyz/grid.xyz"), IMPORT_DTM, {**dialog, "decimal": "POINT"}),
            (self.source("xyz/grid_hole.xyz"), IMPORT_DTM, {**dialog, "decimal": "COMMA"}),
            (self.source("xyz/irregular.xyz"), IMPORT_POINTS,
             {"separator": "TAB", "decimal": "POINT", "header": False}),
            (self.source("points/taludes.csv"), IMPORT_POINTS, {}),
            (self.source("points/taludes.csv", "estacion.txt"), IMPORT_POINTS, {}),
            (self.source("gpkg/capas.gpkg"), IMPORT_VECTOR, {}),
        )
        for path, idname, extra in cases:
            with self.subTest(fichero=path.name):
                opened.clear()
                result = bpy.ops.geoblender.io_import_file("EXEC_DEFAULT", filepath=str(path))
                self.assertEqual(result, {"FINISHED"})
                self.assertEqual(opened, [(idname, {"filepath": str(path), **extra})])
        dxf = self.sources / "plano.dxf"
        dxf.write_bytes(b"0\nEOF\n")
        opened.clear()
        with mock.patch.object(self.commands, "is_available",
                               lambda key: key == "geoblender.io_import_dxf"):
            bpy.ops.geoblender.io_import_file("EXEC_DEFAULT", filepath=str(dxf))
        self.assertEqual(opened, [("geoblender.io_import_dxf", {"filepath": str(dxf)})])

    def test_unsupported_extensions_name_their_roadmap_entry(self) -> None:
        """RF-006-27: un formato que trae otra entrada del roadmap se rechaza con ella
        («Disponible en R-65 · DXF»; dos entradas si el formato es de dos programas); un
        shapefile, con la conversión a GeoPackage en QGIS; una extensión desconocida, con las
        que se importan; un fichero que no existe, con su nombre. No se abre ningún
        importador ni cambia nada en el proyecto."""
        self.open()
        before = self.counts()
        opened: list[str] = []
        self.enterContext(mock.patch.object(self.io_ops, "open_importer",
                                            lambda idname, values, context=None:
                                            opened.append(idname)))
        cases = (
            ("plano.dxf", ("Geoblender aún no importa ficheros .dxf", "Disponible en R-65 · DXF")),
            ("plano.dwg", ("Disponible en R-66 · DWG mediante conversor externo",)),
            ("eje.landxml", ("Disponible en R-67 · LandXML",)),
            ("vuelo.laz", ("Disponible en R-72 · Nubes de puntos y mallas de levantamiento",)),
            ("malla.OBJ", ("Disponible en R-72",)),
            ("cantera.sup", ("Disponible en R-64 · RecMin", "Disponible en R-68 · Aplitop MDT")),
            ("sondeos.xlsx", ("Disponible en 005",)),
            ("parcelas.shp", ("los shapefiles no se importan", "GeoPackage en QGIS")),
            ("notas.docx", ("la extensión «.docx»",
                            "Importa .tif, .tiff, .asc, .xyz, .csv, .txt, .gpkg")),
            ("LEEME", ("la extensión «»",)),
        )
        for name, expected in cases:
            with self.subTest(fichero=name):
                path = self.sources / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"x")
                message = self.refused(IMPORT_FILE, filepath=str(path))
                self.assertIn(f"«{name}»", message)
                for text in expected:
                    self.assertIn(text, message)
        missing = self.refused(IMPORT_FILE, filepath=str(self.sources / "no_esta.tif"))
        self.assertIn("«no_esta.tif» no existe", missing)
        self.assertEqual(opened, [])
        self.assertEqual(self.counts(), before)

    def test_dropped_geotiff_imports_the_dtm(self) -> None:
        """RF-006-27, RF-006-08: soltar un GeoTIFF (con su CRS y su datum declarados) abre el
        importador de MDT (sin interfaz, ``blender -b`` ejecuta las dos órdenes sin diálogo): la
        importación empieza y, al terminar su trabajo, el MDT está en el proyecto con las celdas
        de la fuente."""
        self.open()
        raster = self.source_raster(self.source("geotiff/f64_strip.tif"))
        path = self.written(raster, "dron/vuelo.tif")
        before = set(self.session.pending_ingests())
        result = bpy.ops.geoblender.io_import_file("INVOKE_DEFAULT", filepath=str(path))
        self.assertEqual(result, {"FINISHED"})
        launched = [op for job, op in self.session.pending_ingests().items()
                    if job not in before]
        self.assertEqual(len(launched), 1)
        self.finish()
        self.assertEqual(self.operation(launched[0])[:2], ("gis.import_dtm", "done"))
        self.assertSameCells(self.stored("gis_src_vuelo"), raster)
        self.assertEqual(Path(path).read_bytes()[:4], b"II*\x00")  # la fuente, intacta

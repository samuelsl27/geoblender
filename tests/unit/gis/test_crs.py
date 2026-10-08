# SPDX-License-Identifier: GPL-3.0-or-later
"""Declaración de CRS y datum, reglas de comparación e informe de transformación (spec 006,
T11; plan 006 §5.1 ``gis/crs.py`` y §5.3.3).

Dominio puro: el servicio de CRS es un doble de prueba (``FakeService``), salvo en la
versión de pyproj simulada, que pasa por ``adapters.registry`` sin llegar a importar pyproj.

- **RF-006-04** (no suponer el CRS): una fuente sin CRS horizontal o sin datum vertical
  declarados se rechaza con ``gis.crs_undeclared`` o ``gis.vertical_undeclared`` (nunca se
  toman los del proyecto).
- **RF-006-05** (transformar con precisión conocida o rechazar): misma referencia, sin
  transformación y sin servicio; distinta, la del servicio, con su informe (descripción,
  precisión en m y rejillas); sin precisión conocida, ``gis.transform_unknown_accuracy``
  con los dos CRS; una referencia local solo se compara por identidad.
- **RF-006-07** (transformar coordenadas tecleadas): el resultado en float64, la
  transformación y su precisión, y el factor de escala y la convergencia en el destino.
- **RF-006-31** (versión de pyproj): con otra versión simulada, el servicio queda no
  disponible con la versión hallada y la esperada, y lo que no transforma sigue igual.
"""

import unittest
from unittest import mock

import numpy as np

from tests.support.package import import_geoblender

gis = import_geoblender("gis")
crs = import_geoblender("gis.crs")
ports = import_geoblender("gis.ports")
messages = import_geoblender("gis.messages")
georef = import_geoblender("core.georef")
pyproj_crs = import_geoblender("adapters.pyproj_crs")

CATALOG = georef.load_catalog()
H25830 = CATALOG.horizontal(25830)
H23030 = CATALOG.horizontal(23030)
H4083 = CATALOG.horizontal(4083)
V5782 = CATALOG.vertical(5782)
V9397 = CATALOG.vertical(9397)
LOCAL = CATALOG.local_vertical("NP-0 del plano 3")
SPED = ports.TransformInfo(
    "Inverse of UTM zone 30N + ED50 to ETRS89 (12) + UTM zone 30N", 0.2,
    ("es_ign_SPED2ETV2.tif",),
)


class FakeTransform:
    """Traslación fija; apunta lo que recibe."""

    def __init__(self, info: object, offset: tuple[float, float, float]) -> None:
        self.info = info
        self.offset = np.array(offset)
        self.seen: list[np.ndarray] = []

    def apply(self, xyz: np.ndarray) -> np.ndarray:
        self.seen.append(np.array(xyz, copy=True))
        return np.asarray(xyz, dtype=np.float64) + self.offset


class FakeService:
    """Un ``CrsService`` de prueba: da ``FakeTransform`` con ``info`` y apunta las
    llamadas; factor de escala 1,0004 y convergencia = (x − 500 000)/10⁵ grados."""

    def __init__(self, info: object = SPED, offset=(-109.5, -207.5, 0.0)) -> None:
        self.info = info
        self.offset = offset
        self.calls: list[tuple] = []
        self.factor_calls: list[tuple] = []
        self.transform: FakeTransform | None = None

    def identify_wkt(self, wkt: str):
        return None

    def transformer(self, src, src_v, dst, dst_v):
        self.calls.append((src, src_v, dst, dst_v))
        self.transform = FakeTransform(self.info, self.offset)
        return self.transform

    def scale_factor(self, crs_ref, xy):
        self.factor_calls.append(("k", crs_ref, np.array(xy, copy=True)))
        return np.full(len(xy), 1.0004)

    def grid_convergence(self, crs_ref, xy):
        self.factor_calls.append(("gamma", crs_ref, np.array(xy, copy=True)))
        return (np.asarray(xy)[:, 0] - 500000.0) / 1e5


def _no_service():
    raise AssertionError("no hace falta el servicio de CRS")


class DeclarationTest(unittest.TestCase):
    """RF-006-04: el CRS y el datum se declaran o se piden; nunca se suponen."""

    def test_undeclared_crs(self) -> None:
        """RF-006-04: sin CRS horizontal, ``gis.crs_undeclared`` con la fuente; sin datum
        vertical, ``gis.vertical_undeclared``; sin ninguno, primero el CRS."""
        cases = [
            (crs.Declaration("mdt.asc", None, V5782), "gis.crs_undeclared", "CRS horizontal"),
            (crs.Declaration("mdt.asc", H25830, None), "gis.vertical_undeclared",
             "datum vertical"),
            (crs.Declaration("mdt.asc", None, None), "gis.crs_undeclared", "CRS horizontal"),
        ]
        for declaration, code, field in cases:
            with self.subTest(code=code, crs=declaration.crs, vertical=declaration.vertical):
                with self.assertRaises(messages.GisError) as caught:
                    declaration.require()
                error = caught.exception
                self.assertEqual(error.code, code)
                self.assertEqual(error.obj, "mdt.asc")
                self.assertEqual(error.field, field)
                self.assertIn("«mdt.asc»", error.text)
                self.assertIn("no se supone el del proyecto", error.text)

    def test_declared(self) -> None:
        """RF-006-04: con los dos declarados, ``require`` los devuelve tal cual."""
        self.assertEqual(crs.Declaration("a.tif", H23030, LOCAL).require(), (H23030, LOCAL))
        self.assertEqual(
            crs.Declaration("b.csv", H25830, crs.ELLIPSOIDAL_ETRS89).require(),
            (H25830, crs.ELLIPSOIDAL_ETRS89),
        )

    def test_ellipsoidal_reference(self) -> None:
        """RF-006-04/05: la altura elipsoidal ETRS89 es una referencia vertical para
        declarar fuentes (no la de un proyecto) y se nombra en los informes."""
        reference = crs.ELLIPSOIDAL_ETRS89
        self.assertEqual(reference.kind, "ellipsoidal")
        self.assertIsNone(reference.epsg)
        self.assertEqual(crs.reference_label(H25830, V5782), "EPSG:25830 + EPSG:5782")
        self.assertEqual(
            crs.reference_label(H25830, reference), "EPSG:25830 + altura elipsoidal ETRS89"
        )
        self.assertEqual(
            crs.reference_label(H23030, LOCAL), "EPSG:23030 + Referencia local (NP-0 del plano 3)"
        )


class TransformationTest(unittest.TestCase):
    """RF-006-05: transformar con una transformación de precisión conocida o rechazar."""

    def test_same_reference_needs_no_service(self) -> None:
        """RF-006-05: con el CRS y el datum del proyecto, sin transformación ni servicio."""
        declaration = crs.Declaration("mdt.tif", H25830, V5782)
        self.assertFalse(crs.needs_transform(H25830, V5782, H25830, V5782))
        self.assertIsNone(
            crs.transformation_for(declaration, H25830, V5782, resolver=_no_service)
        )
        local = crs.Declaration("mdt.tif", H25830, LOCAL)
        self.assertIsNone(crs.transformation_for(local, H25830, LOCAL, resolver=_no_service))

    def test_known_accuracy(self) -> None:
        """RF-006-05: otro CRS o datum → la transformación del servicio, con los cuatro
        datos de la fuente y del proyecto, y su informe con la precisión y la rejilla."""
        service = FakeService()
        declaration = crs.Declaration("ed50.asc", H23030, V5782)
        self.assertTrue(crs.needs_transform(H23030, V5782, H25830, V5782))
        transform = crs.transformation_for(declaration, H25830, V5782, service=service)
        self.assertIs(transform, service.transform)
        self.assertEqual(service.calls, [(H23030, V5782, H25830, V5782)])
        self.assertEqual(
            crs.transform_summary(transform.info),
            "Inverse of UTM zone 30N + ED50 to ETRS89 (12) + UTM zone 30N; precisión 0,2 m; "
            "rejilla es_ign_SPED2ETV2.tif",
        )
        ellipsoidal = crs.Declaration("dron.csv", H25830, crs.ELLIPSOIDAL_ETRS89)
        self.assertTrue(crs.needs_transform(H25830, crs.ELLIPSOIDAL_ETRS89, H25830, V5782))
        crs.transformation_for(ellipsoidal, H25830, V5782, service=service)
        self.assertEqual(service.calls[-1], (H25830, crs.ELLIPSOIDAL_ETRS89, H25830, V5782))

    def test_summary_texts(self) -> None:
        """RF-006-05: el informe de una conversión exacta, de varias rejillas y de una
        transformación sin precisión conocida."""
        self.assertEqual(
            crs.transform_summary(ports.TransformInfo("UTM 30N a UTM 31N", 0.0)),
            "UTM 30N a UTM 31N; precisión 0 m",
        )
        self.assertEqual(
            crs.transform_summary(ports.TransformInfo("x", 0.25, ("a.tif", "b.tif"))),
            "x; precisión 0,25 m; rejillas a.tif, b.tif",
        )
        self.assertEqual(
            crs.transform_summary(ports.TransformInfo("ballpark", None)),
            "ballpark; precisión desconocida",
        )

    def test_unknown_accuracy_rejected(self) -> None:
        """RF-006-05: sin precisión conocida, ``gis.transform_unknown_accuracy`` nombrando
        los dos CRS (con su datum) y la fuente; no se devuelve la transformación."""
        service = FakeService(info=ports.TransformInfo("Ballpark geographic offset", None))
        declaration = crs.Declaration("canarias.tif", H4083, V9397)
        with self.assertRaises(messages.GisError) as caught:
            crs.transformation_for(declaration, H25830, V5782, service=service)
        error = caught.exception
        self.assertEqual(error.code, "gis.transform_unknown_accuracy")
        self.assertEqual(error.obj, "canarias.tif")
        self.assertEqual(error.values["source_crs"], "EPSG:4083 + EPSG:9397")
        self.assertEqual(error.values["target_crs"], "EPSG:25830 + EPSG:5782")
        self.assertIn("EPSG:4083 + EPSG:9397 a EPSG:25830 + EPSG:5782", error.text)
        self.assertIn("«canarias.tif» no se ha importado", error.text)
        self.assertEqual(len(service.calls), 1)

    def test_local_reference_only_by_identity(self) -> None:
        """RF-006-05: una referencia local solo se compara por identidad: si difiere del
        datum del proyecto no hay transformación posible y se rechaza sin preguntar al
        servicio; si es la misma, solo cambia la horizontal."""
        other = CATALOG.local_vertical("Cota de la boca del pozo 2")
        cases = [(LOCAL, V5782), (V5782, LOCAL), (LOCAL, other)]
        for source_v, target_v in cases:
            with self.subTest(source=source_v.name, target=target_v.name):
                declaration = crs.Declaration("plano.dxf", H25830, source_v)
                with self.assertRaises(messages.GisError) as caught:
                    crs.transformation_for(
                        declaration, H25830, target_v, resolver=_no_service
                    )
                self.assertEqual(caught.exception.code, "gis.transform_unknown_accuracy")
        service = FakeService()
        declaration = crs.Declaration("plano.dxf", H23030, LOCAL)
        crs.transformation_for(declaration, H25830, LOCAL, service=service)
        self.assertEqual(service.calls, [(H23030, LOCAL, H25830, LOCAL)])

    def test_undeclared_is_checked_first(self) -> None:
        """RF-006-04: sin declarar no se busca transformación."""
        with self.assertRaises(messages.GisError) as caught:
            crs.transformation_for(
                crs.Declaration("x.tif", None, V5782), H25830, V5782, resolver=_no_service
            )
        self.assertEqual(caught.exception.code, "gis.crs_undeclared")


class CoordinatesTest(unittest.TestCase):
    """RF-006-07: transformar coordenadas tecleadas entre dos CRS del catálogo."""

    def test_transform_coordinates(self) -> None:
        """RF-006-07: el resultado (float64), la transformación y su precisión, y el factor
        de escala y la convergencia en el destino (en las coordenadas ya transformadas y
        con el CRS de destino); la entrada no cambia."""
        service = FakeService()
        typed = np.array([(440000.0, 4474000.0, 100.0), (756209.148, 4432276.557, 0.5)])
        kept = typed.copy()
        result = crs.transform_coordinates(typed, H23030, V5782, H25830, V5782, service=service)
        np.testing.assert_array_equal(typed, kept)
        expected = typed + np.array([-109.5, -207.5, 0.0])
        np.testing.assert_array_equal(result.xyz, expected)
        self.assertEqual(result.xyz.dtype, np.float64)
        self.assertEqual(result.info, SPED)
        np.testing.assert_array_equal(result.scale_factor, [1.0004, 1.0004])
        np.testing.assert_array_equal(
            result.convergence_deg, (expected[:, 0] - 500000.0) / 1e5
        )
        for kind, crs_ref, xy in service.factor_calls:
            with self.subTest(kind=kind):
                self.assertEqual(crs_ref, H25830)
                np.testing.assert_array_equal(xy, expected[:, :2])

    def test_rejects_bad_shape(self) -> None:
        """RF-006-07: las coordenadas son (n, 3)."""
        with self.assertRaises(ValueError):
            crs.transform_coordinates(
                np.zeros((2, 2)), H23030, V5782, H25830, V5782, service=FakeService()
            )

    def test_same_reference_and_unknown_accuracy(self) -> None:
        """RF-006-07: con el mismo CRS y datum, las mismas coordenadas con sus factores;
        sin precisión conocida (o con una referencia local distinta), no se transforman
        (``gis.coordinates_unknown_accuracy`` con los dos CRS)."""
        typed = np.array([(500000.0, 4427757.0, 650.0)])
        same = crs.transform_coordinates(typed, H25830, V5782, H25830, V5782,
                                         service=FakeService())
        np.testing.assert_array_equal(same.xyz, typed)
        self.assertEqual(same.info.accuracy_m, 0.0)
        np.testing.assert_array_equal(same.convergence_deg, [0.0])
        unknown = FakeService(info=ports.TransformInfo("Ballpark", None))
        other = CATALOG.local_vertical("Cota de la boca del pozo 2")
        for service, target_v in ((unknown, V5782), (FakeService(), other)):
            with self.subTest(target=target_v.name):
                with self.assertRaises(messages.GisError) as caught:
                    crs.transform_coordinates(typed, H25830, LOCAL if target_v is other
                                              else V9397, H25830, target_v, service=service)
                self.assertEqual(caught.exception.code, "gis.coordinates_unknown_accuracy")
                self.assertIn("las coordenadas no se han transformado", caught.exception.text)


class ServiceStatusTest(unittest.TestCase):
    """RF-006-31: si pyproj no es la versión fijada, sin transformaciones y lo demás igual."""

    def test_other_pyproj_version(self) -> None:
        """RF-006-31: con otra versión de pyproj simulada, el servicio queda no
        disponible con el mensaje de la versión hallada y la esperada; lo que no
        transforma (misma referencia, volúmenes) sigue funcionando."""
        with mock.patch.object(pyproj_crs, "installed_version", return_value="3.7.1"):
            status = crs.crs_service_status()
            self.assertFalse(status.available)
            self.assertIsNone(status.service)
            error = status.error
            self.assertEqual(error.code, "gis.crs_service_version")
            self.assertEqual(error.values["found"], "3.7.1")
            self.assertEqual(error.values["expected"], pyproj_crs.PYPROJ_VERSION)
            self.assertIn("Blender cargó pyproj 3.7.1", error.text)
            self.assertIn(f"Geoblender necesita {pyproj_crs.PYPROJ_VERSION}", error.text)
            self.assertIn("El resto de Geoblender funciona con normalidad", error.text)
            with self.assertRaises(messages.GisError) as caught:
                crs.require_crs_service()
            self.assertEqual(caught.exception.code, "gis.crs_service_version")
            with self.assertRaises(messages.GisError) as caught:
                crs.transformation_for(
                    crs.Declaration("ed50.asc", H23030, V5782), H25830, V5782
                )
            self.assertEqual(caught.exception.code, "gis.crs_service_version")
            same = crs.Declaration("mdt.tif", H25830, V5782)
            self.assertIsNone(crs.transformation_for(same, H25830, V5782))
            grid = gis.Grid(west=700000.0, north=4400002.0, dx=1.0, dy=1.0, ncols=2, nrows=2)
            upper = gis.Raster(grid, np.full((2, 2), 10.0), H25830, V5782)
            lower = gis.Raster(grid, np.zeros((2, 2)), H25830, V5782)
            self.assertEqual(gis.volume_between(upper, lower).cut_m3, 40.0)

    def test_unavailable_reasons(self) -> None:
        """RF-006-31: cada motivo del adaptador llega como ``GisError`` con su texto."""
        reasons = [
            (ports.CrsServiceUnavailable("gis.crs_catalog_mismatch", crs="EPSG:25830"),
             "La definición de EPSG:25830"),
            (ports.CrsServiceUnavailable("gis.crs_service_broken",
                                         detail="no se pudo cargar pyproj (DLL)"),
             "desactivadas: no se pudo cargar pyproj (DLL)."),
        ]
        for exc, text in reasons:
            with self.subTest(code=exc.code):

                def resolver(exc=exc):
                    raise exc

                status = crs.crs_service_status(resolver)
                self.assertFalse(status.available)
                self.assertEqual(status.error.code, exc.code)
                self.assertIn(text, status.error.text)

    def test_available(self) -> None:
        """RF-006-05: con un servicio, el estado lo da sin error."""
        service = FakeService()
        status = crs.crs_service_status(lambda: service)
        self.assertTrue(status.available)
        self.assertIs(status.service, service)
        self.assertIsNone(status.error)
        self.assertIs(crs.require_crs_service(lambda: service), service)


if __name__ == "__main__":
    unittest.main()

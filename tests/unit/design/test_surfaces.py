# SPDX-License-Identifier: GPL-3.0-or-later
"""Las superficies de un cálculo (spec 013, T03; HU-013-1; RF-013-01, RF-013-16; plan 013 §5.3.1).

``design.surfaces`` lee una superficie del proyecto o de la versión activa tal como está en su
fichero (sin remuestrear ni interpolar, RF-013-01) y la compara con la rejilla del proyecto antes
de calcular: una rejilla, un CRS o un datum vertical distintos se rechazan (RF-013-16) nombrando el
objeto, el campo y el valor, y ofreciendo la orden de la 006 que lo resuelve (RF-006-11 para
llevarla a la rejilla del proyecto, RF-006-17 si es un TIN); no se registra nada.
"""

from __future__ import annotations

import hashlib
import unittest
from unittest import mock

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import design_fixtures as dfx
from tests.support.package import import_geoblender

surfaces = import_geoblender("design.surfaces")
messages = import_geoblender("design.messages")
gis_messages = import_geoblender("gis.messages")
gis = import_geoblender("gis")

COMMAND_ES = "Topografía ▸ Superficies ▸ Rejilla de proyecto desde un MDT…"
COMMAND_EN = "Topography ▸ Surfaces ▸ Project grid from a DTM…"
TIN_COMMAND_ES = "Topografía ▸ Superficies ▸ MDT ⇄ TIN…"
GRID = dfx.grid_from(40, 60, 2.0)


def surface_on(grid: object, *, crs: object = dfx.CRS, vertical: object = dfx.VERTICAL) -> object:
    """Una superficie de cotas crecientes en ``grid``."""
    values = 600.0 + np.arange(grid.nrows * grid.ncols, dtype=np.float64).reshape(  # type: ignore[attr-defined]
        grid.shape) * 0.125  # type: ignore[attr-defined]
    return gis.Raster(grid, values, crs, vertical)


def with_grid(**changes: float) -> object:
    """La rejilla de prueba con algún campo cambiado."""
    fields = {"west": GRID.west, "north": GRID.north, "dx": GRID.dx, "dy": GRID.dy,
              "ncols": GRID.ncols, "nrows": GRID.nrows, **changes}
    return gis.Grid(**fields)


# --- Comparar con la rejilla del proyecto ----------------------------------------------------


class CheckGridTest(unittest.TestCase):
    FRAME = surfaces.ProjectFrame(GRID, dfx.CRS, dfx.VERTICAL)

    def refused(self, surface: object, name: str = "gis_dtm_antigua") -> object:
        with self.assertRaises(messages.DesignError) as caught:
            surfaces.check_grid(surface, self.FRAME, role="superficie de partida", name=name)
        return caught.exception

    def test_the_same_grid_passes(self) -> None:
        """RF-013-16: una superficie en la rejilla, el CRS y el datum vertical del proyecto pasa
        (``None``), aunque sea otro objeto: se comparan por valor, bit a bit; también una cabecera
        sin celdas (``ProjectFrame``)."""
        same = gis.Grid(GRID.west, GRID.north, GRID.dx, GRID.dy, GRID.ncols, GRID.nrows)
        self.assertIsNone(surfaces.check_grid(surface_on(same), self.FRAME,
                                              role="superficie de partida", name="x"))
        self.assertIsNone(surfaces.check_grid(surfaces.ProjectFrame(same, dfx.CRS, dfx.VERTICAL),
                                              self.FRAME, role="semillas", name="x"))

    def test_each_difference_is_refused_with_object_field_and_value(self) -> None:
        """RF-013-16: una rejilla distinta (oeste, norte, paso en X o en Y, columnas, filas), otro
        CRS u otro datum vertical se rechazan con ``des.surface_mismatch``: el objeto (el nombre
        de la superficie y su papel), el campo, el valor de la superficie y la diferencia, y la
        orden de la 006 que lo resuelve (RF-006-11)."""
        local = cfx.CATALOG.local_vertical("NP-0 del plano 3")
        cases = [
            ("west", GRID.west + 1.0, surface_on(with_grid(west=GRID.west + 1.0))),
            ("north", GRID.north - 2.0, surface_on(with_grid(north=GRID.north - 2.0))),
            ("dx", 1.0, surface_on(with_grid(dx=1.0))),
            ("dy", 1.0, surface_on(with_grid(dy=1.0))),
            ("ncols", 59, surface_on(with_grid(ncols=59))),
            ("nrows", 41, surface_on(with_grid(nrows=41))),
            ("crs", 25829, surface_on(GRID, crs=cfx.CATALOG.horizontal(25829))),
            ("vertical", None, surface_on(GRID, vertical=local)),
        ]
        for field, value, surface in cases:
            with self.subTest(field=field):
                error = self.refused(surface)
                self.assertEqual(error.code, "des.surface_mismatch")
                self.assertEqual(error.field, field)
                if value is None:
                    self.assertIn("plano 3", str(error.value))
                else:
                    self.assertEqual(error.value, value)
                self.assertIn("gis_dtm_antigua", error.obj)
                self.assertIn("superficie de partida", error.obj)
                self.assertEqual(error.values["surface"], "gis_dtm_antigua")
                self.assertIn("gis_dtm_antigua", error.text)
                self.assertIn(f"«{field}»", error.text)
                self.assertIn(COMMAND_ES, error.text)
                self.assertNotIn("?", error.text)
                self.assertNotIn("{", error.text)

    def test_the_first_difference_is_the_one_reported(self) -> None:
        """Con varias diferencias se informa de la primera de la 006 (oeste antes que el paso,
        la rejilla antes que el CRS), para no abrumar: se corrige y se vuelve a comprobar."""
        many = surface_on(with_grid(west=GRID.west + 4.0, dx=1.0, ncols=10),
                          crs=cfx.CATALOG.horizontal(25829))
        self.assertEqual(self.refused(many).field, "west")
        grid_ok_crs_not = surface_on(GRID, crs=cfx.CATALOG.horizontal(25829))
        self.assertEqual(self.refused(grid_ok_crs_not).field, "crs")

    def test_the_message_is_in_both_languages_and_says_who_is_who(self) -> None:
        """Principio 10: el mismo código se ve en inglés con la orden en inglés, y el detalle dice
        cuál es la rejilla del proyecto y cuál la de la superficie (el proyecto va primero)."""
        error = self.refused(surface_on(with_grid(dx=1.0)))
        english = messages.render(error.code, language="en", **error.values)
        self.assertIn(COMMAND_EN, english)
        self.assertIn("gis_dtm_antigua", english)
        self.assertNotIn(COMMAND_ES, english)
        self.assertIn("proyecto frente a superficie", error.text)
        self.assertIn("paso en X 2 frente a 1", error.text)

    def test_the_surface_is_not_modified(self) -> None:
        """Regla 6: comprobar no cambia ni una cota (ni la bandera de solo lectura)."""
        surface = surface_on(with_grid(dx=1.0))
        surface.values.setflags(write=False)
        before = surface.values.copy()
        self.refused(surface)
        np.testing.assert_array_equal(surface.values, before)
        self.assertFalse(surface.values.flags.writeable)

    def test_a_raster_can_be_the_reference(self) -> None:
        """La referencia es cualquier cosa con rejilla, CRS y datum vertical, p. ej. otra
        superficie ya leída (las máscaras de una versión, otra superficie de la misma orden)."""
        reference = surface_on(GRID)
        self.assertIsNone(surfaces.check_grid(surface_on(GRID), reference, role="semillas",
                                              name="x"))
        with self.assertRaises(messages.DesignError):
            surfaces.check_grid(surface_on(with_grid(nrows=39)), reference, role="semillas",
                                name="x")


# --- Las superficies del proyecto ------------------------------------------------------------


class ProjectSurfacesTest(dfx.DesignProjectCase):
    """Sobre el proyecto del diseño: una superficie con relieve y huecos en la rejilla del
    proyecto, otra en una rejilla desplazada, un TIN y los datos de la versión V01."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        grid = cfx.SITE_GRID
        rows, cols = np.indices(grid.shape)
        relief = 600.0 + 0.5 * cols + 0.25 * rows + 0.0625 * (rows % 7)
        relief[10:14, 20:30] = np.nan
        cls.relief = relief
        shifted = gis.Grid(grid.west + 2.0, grid.north, grid.dx, grid.dy, grid.ncols, grid.nrows)
        helper = cls("test_project_frame_is_the_project_grid")  # las ayudas son de instancia
        helper.write_surfaces(("relieve", dfx.raster(grid, relief)),
                              ("desplazada", dfx.raster(shifted, relief)))
        cls.tin = helper.write_tin("pozos")

    def frame(self) -> object:
        return surfaces.project_frame(self.project)

    def sha(self, name: str) -> str:
        return hashlib.sha256((self.root / "rasters" / f"{name}.tif").read_bytes()).hexdigest()

    def test_project_frame_is_the_project_grid(self) -> None:
        """RF-013-16: la rejilla del proyecto es la de su ventana y su paso (160 × 160 de 2 m);
        la misma, bit a bit, que la de las máscaras compiladas de la versión; con el CRS y el datum
        vertical del proyecto."""
        frame = self.frame()
        self.assertTrue(frame.grid.same_geometry(cfx.SITE_GRID))
        self.assertTrue(frame.grid.same_geometry(self.masks().grid))
        self.assertEqual(frame.crs.epsg, 25830)
        self.assertEqual(frame.vertical, cfx.VERTICAL)

    def test_reads_a_project_surface_cell_by_cell(self) -> None:
        """RF-013-01: la superficie se lee tal como está —cada celda igual bit a bit, con sus
        huecos como NaN, en float64— en la rejilla, el CRS y el datum del proyecto, sin
        remuestrear ni interpolar, y su fichero no cambia (regla 6)."""
        before = self.sha("gis_dtm_relieve")
        found = surfaces.read_surface(self.project, "gis_dtm_relieve")
        self.assertEqual(found.values.dtype, np.float64)
        self.assertTrue(found.grid.same_geometry(cfx.SITE_GRID))
        np.testing.assert_array_equal(found.values, self.relief)
        self.assertEqual(int(np.isnan(found.values).sum()), 40)
        self.assertEqual(found.crs.epsg, 25830)
        self.assertEqual(found.vertical, cfx.VERTICAL)
        self.assertEqual(self.sha("gis_dtm_relieve"), before)

    def test_the_grid_is_checked_against_the_project_before_reading_cells(self) -> None:
        """RF-013-16: con la rejilla de referencia, la cabecera se compara antes de leer una sola
        celda: una superficie en otra rejilla se rechaza sin leerla (el rechazo es de la cabecera),
        y una en la del proyecto se lee."""
        frame = self.frame()
        ok = surfaces.read_surface(self.project, "gis_dtm_relieve", expect=frame,
                                   role="superficie de partida")
        np.testing.assert_array_equal(ok.values, self.relief)
        with mock.patch.object(surfaces, "load_raster",
                               side_effect=AssertionError("no se leen celdas")), \
                mock.patch.object(surfaces, "read_geotiff",
                                  side_effect=AssertionError("no se leen celdas")):
            with self.assertRaises(messages.DesignError) as caught:
                surfaces.read_surface(self.project, "gis_dtm_desplazada", expect=frame,
                                      role="superficie de partida")
        error = caught.exception
        self.assertEqual((error.code, error.field), ("des.surface_mismatch", "west"))
        self.assertEqual(error.value, cfx.SITE_GRID.west + 2.0)
        self.assertIn("gis_dtm_desplazada", error.text)
        self.assertIn("superficie de partida", error.text)
        self.assertIn(COMMAND_ES, error.text)

    def test_another_crs_or_vertical_datum_is_refused_from_the_header(self) -> None:
        """RF-013-16: el escritor del proyecto solo admite su CRS y su datum vertical, así que la
        diferencia viene de la referencia (p. ej. unas máscaras en otro sistema): la cabecera de la
        superficie del proyecto, comparada con una referencia de la misma rejilla pero con otro CRS
        (EPSG:25829) o con otro datum vertical (un plano local), se rechaza sin leer una sola celda,
        con ``des.surface_mismatch``: el objeto (la superficie y su papel), el campo (``crs`` o
        ``vertical``), el valor y la orden de la 006."""
        grid = self.frame().grid
        local = cfx.CATALOG.local_vertical("NP-0 del plano 3")
        references = (
            ("crs", surfaces.ProjectFrame(grid, cfx.CATALOG.horizontal(25829), dfx.VERTICAL)),
            ("vertical", surfaces.ProjectFrame(grid, dfx.CRS, local)),
        )
        for field, reference in references:
            with self.subTest(field=field):
                with mock.patch.object(surfaces, "load_raster",
                                       side_effect=AssertionError("no se leen celdas")), \
                        mock.patch.object(surfaces, "read_geotiff",
                                          side_effect=AssertionError("no se leen celdas")):
                    with self.assertRaises(messages.DesignError) as caught:
                        surfaces.read_surface(self.project, "gis_dtm_relieve", expect=reference,
                                              role="superficie de partida")
                error = caught.exception
                self.assertEqual((error.code, error.field), ("des.surface_mismatch", field))
                self.assertIn("gis_dtm_relieve", error.obj)
                self.assertIn("superficie de partida", error.obj)
                self.assertIn(f"«{field}»", error.text)
                self.assertIn(COMMAND_ES, error.text)
                self.assertNotIn("?", error.text)

    def test_a_dataset_of_the_active_version_and_the_project_one(self) -> None:
        """RF-013-01: con una versión activa se lee un dato de esa versión (la rejilla de clases de
        las máscaras de V01, por el nombre) o, si no lo hay en ella, el del proyecto; las cotas son
        las del fichero."""
        masks = self.masks()
        found = surfaces.read_surface(self.project, "gis_msk", version_uid=self.v1.uid)
        self.assertTrue(found.grid.same_geometry(masks.grid))
        np.testing.assert_array_equal(np.where(np.isfinite(found.values), found.values, 0.0),
                                      masks.classes.astype(np.float64))
        again = surfaces.read_surface(self.project, "gis_dtm_relieve", version_uid=self.v1.uid)
        np.testing.assert_array_equal(again.values, self.relief)

    def test_a_dataset_of_another_version_is_refused(self) -> None:
        """RF-013-01: una superficie de otra versión (o de una versión sin ser la activa) se
        rechaza con la versión que la tiene y la activa; sin versión activa, también."""
        for active, label in ((self.v2.uid, "V02"), ("", "—")):
            with self.subTest(active=label):
                with self.assertRaises(messages.DesignError) as caught:
                    surfaces.read_surface(self.project, "gis_msk", version_uid=active)
                error = caught.exception
                self.assertEqual(error.code, "des.surface_other_version")
                self.assertEqual(error.value, "gis_msk")
                self.assertEqual(error.values["version"], "V01")
                self.assertEqual(error.values["active"], label)
                self.assertIn("gis_msk", error.text)

    def test_unknown_surface_and_missing_file(self) -> None:
        """Una superficie que no hay es ``gis.dataset_unknown`` (nombrándola); si su fichero ya no
        está, ``gis.dataset_file_missing``."""
        with self.assertRaises(gis_messages.GisError) as unknown:
            surfaces.read_surface(self.project, "gis_dtm_no_hay")
        self.assertEqual(unknown.exception.code, "gis.dataset_unknown")
        self.assertEqual(unknown.exception.value, "gis_dtm_no_hay")
        self.write_surfaces(("efimera", dfx.raster(cfx.SITE_GRID, self.relief)))
        (self.root / "rasters" / "gis_dtm_efimera.tif").unlink()
        with self.assertRaises(gis_messages.GisError) as missing:
            surfaces.read_surface(self.project, "gis_dtm_efimera",
                                  expect=self.frame(), role="semillas")
        self.assertEqual(missing.exception.code, "gis.dataset_file_missing")

    def test_a_tin_is_refused_with_the_order_that_brings_it_to_a_grid(self) -> None:
        """RF-013-16 (RF-006-17): un TIN no es una superficie en rejilla y no se remuestrea: se
        rechaza con la orden «MDT ⇄ TIN…» que lo lleva a una."""
        with self.assertRaises(messages.DesignError) as caught:
            surfaces.read_surface(self.project, self.tin)
        error = caught.exception
        self.assertEqual(error.code, "des.surface_is_tin")
        self.assertEqual(error.value, self.tin)
        self.assertIn(TIN_COMMAND_ES, error.text)
        self.assertIn(self.tin, error.text)

    def test_a_refusal_registers_nothing(self) -> None:
        """RF-013-16 (como RF-011-03): rechazar una superficie —otra rejilla, un TIN, una de otra
        versión, una que no hay— no registra operación ni dato alguno y no toca los ficheros."""
        def state() -> tuple[object, ...]:
            return (self.query("SELECT COUNT(*) FROM gb_operation")[0][0],
                    self.query("SELECT COUNT(*) FROM gb_dataset")[0][0],
                    self.query("SELECT COUNT(*) FROM gb_operation_io")[0][0],
                    self.sha("gis_dtm_desplazada"), self.sha("gis_dtm_relieve"))

        before = state()
        frame = self.frame()
        refusals = (
            lambda: surfaces.read_surface(self.project, "gis_dtm_desplazada", expect=frame),
            lambda: surfaces.read_surface(
                self.project, "gis_dtm_relieve", expect=surfaces.ProjectFrame(
                    frame.grid, cfx.CATALOG.horizontal(25829), frame.vertical)),
            lambda: surfaces.read_surface(self.project, self.tin),
            lambda: surfaces.read_surface(self.project, "gis_msk", version_uid=self.v2.uid),
            lambda: surfaces.read_surface(self.project, "gis_dtm_no_hay"),
        )
        for refuse in refusals:
            with self.assertRaises((messages.DesignError, gis_messages.GisError)):
                refuse()
        self.assertEqual(state(), before)

    def test_something_that_is_not_a_grid_is_a_program_error(self) -> None:
        """Un dato que no es una rejilla (una capa) no es una superficie: las listas de las
        órdenes no lo ofrecen, así que pedirlo es un error del programa (``ValueError``)."""
        ring = cfx.rectangle(20.0, 20.0, 60.0, 60.0)
        self.write_layer("gis_fea_no_es_rejilla", [[[ring]]])
        with self.assertRaises(ValueError):
            surfaces.read_surface(self.project, "gis_fea_no_es_rejilla")


# --- Los mensajes de la tarea ----------------------------------------------------------------


class MessagesTest(unittest.TestCase):
    CODES = ("des.surface_mismatch", "des.surface_is_tin", "des.surface_other_version",
             "des.zone_unknown", "des.layer_not_polygons")

    def test_new_codes_are_errors_with_every_value_filled(self) -> None:
        """Principio 10: los cinco códigos de la tarea son errores del catálogo, con su texto en
        español y en inglés, y rellenos con sus valores no dejan ni «?» ni «{…}»."""
        values = {"surface": "gis_dtm_x", "role": "semillas", "detail": "paso en X 2 frente a 1",
                  "zone": "balsa", "layer": "gis_fea_x", "version": "V01", "active": "V02"}
        for code in self.CODES:
            with self.subTest(code=code):
                self.assertEqual(messages.MESSAGES[code].severity, "error")
                error = messages.DesignError(code, obj="Objeto", field="campo", value="v",
                                             **values)
                for language in ("es", "en"):
                    text = messages.render(code, language=language, **error.values)
                    self.assertNotIn("{", text)
                    self.assertNotIn("?", text)


if __name__ == "__main__":
    unittest.main()

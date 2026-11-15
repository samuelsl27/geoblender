# SPDX-License-Identifier: GPL-3.0-or-later
"""Pruebas de hito de «test_platform_prepare» (spec 015, T48; plan 015 §7.4): las clases que pesan,
movidas sin cambiar una aserción. El «verde» deja en ``test_platform_prepare`` las más ligeras de cada
requisito; las de aquí las ejecuta el paso «hito» de ``tools/check.py --completo`` (la publicación
lo pide siempre).
"""

from __future__ import annotations

from typing import Any, ClassVar

from tests.support import entity_fixtures as efx
from tests.support.package import import_geoblender
from tests.unit.design.test_platform_prepare import (
    BAD_LAYER,
    HOLE_DATASET,
    LOADING,
    POINTS_LAYER,
    PrepareCase,
    START,
    USER,
    WITH_AXIS,
    WORKSHOP,
    drive,
    entity_store,
    line_fields,
    model,
    polygon_request,
    request,
)


class ChainRefusalTest(PrepareCase):
    """RF-015-01, RF-015-04: el nombre es único en la versión y de cada superficie parte como mucho
    una entidad; con una plataforma ya en la versión (sus parámetros, sin calcular)."""

    existing: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.existing = drive(entity_store.prepare_platform_units(
            cls.project, request(), cls.v1, cls.masks_v1))
        cls.clock.advance(minutes=1)
        entity_store.set_entity_params(cls.project, cls.existing.rows, version=cls.v1.uid,
                                       decided_by=USER)
        cls.clock.advance(minutes=1)

    def test_the_name_is_unique_in_the_version(self) -> None:
        """RF-015-01: el nombre de una entidad que ya está (aunque no esté calculada) se rechaza
        con la entidad que lo tiene; el mismo nombre en otra capitalización o con otra puntuación
        que da el mismo dato también."""
        error = self.refused(request(LOADING, start=HOLE_DATASET), "des.entity_name_repeated")
        self.names(error, value=LOADING, other=LOADING, version=self.v1.code)
        error = self.refused(request("plataforma de carga", feature=LOADING, start=HOLE_DATASET),
                             "des.entity_name_repeated")
        self.assertEqual(error.values["other"], LOADING)

    def test_a_surface_that_another_entity_already_starts_from(self) -> None:
        """RF-015-04: de la superficie de la que ya parte «Plataforma de carga» no parte otra; el
        rechazo nombra la que ya parte y la superficie. Otra superficie está libre y la entidad
        nueva es la ``PLT-002``."""
        error = self.refused(request(WORKSHOP), "des.entity_start_taken")
        self.names(error, entity=WORKSHOP, other=LOADING, value=START)
        self.assertEqual(error.field, "des.platform.plt_002.start")
        free = self.units(request(WORKSHOP, start=HOLE_DATASET))
        self.assertEqual(free.code, "PLT-002")

    def test_the_same_entity_prepared_again_does_not_clash_with_itself(self) -> None:
        """RF-015-04: con su código (una entidad que ya está en la versión: recalcularla o calcular la
        que dejó «Traer las entidades de…»), el nombre y la partida son los suyos y no chocan."""
        again = self.units(request(), code="PLT-001")
        self.assertEqual(again.code, "PLT-001")

    def test_a_start_that_is_the_surface_of_an_entity_not_calculated(self) -> None:
        """RF-015-04: partir de la superficie de una entidad (``entity:<código>``) que no está
        calculada, no existe o se descartó no tiene superficie que leer: se rechaza con la clave de
        su campo y el valor."""
        for ref in ("entity:PLT-001", "entity:PLT-009"):
            with self.subTest(ref=ref):
                error = self.refused(request(WORKSHOP, start=ref), "des.entity_start_unknown")
                self.assertEqual(error.field, "des.platform.plt_002.start")
                self.names(error, entity=WORKSHOP, value=ref, version=self.v1.code)

    def test_a_chain_that_loops_back_is_refused(self) -> None:
        """RF-015-04: una entidad que parte de su propia superficie cierra un ciclo."""
        error = self.refused(request(start="entity:PLT-001"), "des.entity_chain_cycle",
                             code="PLT-001")
        self.assertIn(LOADING, error.text)


class FieldRefusalTest(PrepareCase):
    """RF-015-08: lo que falta o sale de rango, sin elegir ningún valor por la persona."""

    def test_a_layer_field_without_value_or_that_does_not_exist(self) -> None:
        """Un eje sin ancho o sin cota inicial en su capa, o un campo que la capa no tiene: la capa,
        la entidad y el campo (con el ``—`` del valor que falta)."""
        error = self.refused(request("Eje sin ancho"), "des.entity_field_value")
        self.names(error, layer=efx.AXES_LAYER, entity="Eje sin ancho")
        self.assertEqual((error.field, error.value), ("ancho", "—"))
        asked = request("Eje sin cota", fields=line_fields(BAD_LAYER))
        error = self.refused(asked, "des.entity_field_value")
        self.assertEqual(error.field, "cota_inicial")
        self.names(error, layer=BAD_LAYER, entity="Eje sin cota")
        error = self.refused(request(fields=line_fields(width_field="ancho_malo")),
                             "des.quarry_layer_field")
        self.assertEqual(error.values["value"], "ancho_malo")
        self.assertEqual(error.values["layer"], efx.AXES_LAYER)

    def test_a_parameter_without_value_and_without_default(self) -> None:
        """El ángulo de borde y el alcance no tienen valor por defecto (D-7, D-20): sin ellos, se
        rechaza con la capa, la entidad y la clave del campo, y no se elige ninguno; tampoco un
        resguardo que falta a quien protege (D-19)."""
        for changes, field in (({"edge_angle_deg": None}, "edge_angle_deg"),
                               ({"reach_m": None}, "reach_m"),
                               ({"protect": True}, "guard_m")):
            with self.subTest(changes=changes):
                error = self.refused(request(**changes), "des.entity_param_missing")
                self.assertEqual(error.field, f"des.platform.plt_001.{field}")
                self.names(error, layer=efx.AXES_LAYER, entity=LOADING)

    def test_a_value_out_of_range(self) -> None:
        """Un ancho negativo (de la capa), un alcance de cero o de más de 10.000 m, un ángulo de 90°,
        un factor de malla de 0, una tolerancia negativa y una pendiente máxima de 0 %: el campo y el
        valor, con la capa y la entidad."""
        cases = (
            (request("Eje con ancho negativo", fields=line_fields(BAD_LAYER)), "width_m", -5.0),
            (request(reach_m=0.0), "reach_m", 0.0),
            (request(reach_m=10000.5), "reach_m", 10000.5),
            (request(edge_angle_deg=90.0), "edge_angle_deg", 90.0),
            (request(mesh_factor=0.0), "mesh_factor", 0.0),
            (request(counter_tol_m=-0.5), "counter_tol_m", -0.5),
            (request(max_slope_pct=0.0), "max_slope_pct", 0.0))
        for asked, field, value in cases:
            with self.subTest(field=field, value=value):
                error = self.refused(asked, "des.entity_param_range")
                self.assertEqual(error.field, f"des.platform.plt_001.{field}")
                self.assertEqual(error.value, value)
                self.names(error, layer=asked.fields.layer, entity=asked.name)

    def test_a_level_outside_the_terrain_plus_or_minus_1000_m(self) -> None:
        """RF-015-08: una cota inicial de 5.000 m (el terreno va de 180,15625 a 307,84375 m)."""
        asked = request("Eje con cota imposible", fields=line_fields(BAD_LAYER))
        error = self.refused(asked, "des.platform_level_range")
        self.assertEqual((error.field, error.value), ("cota_inicial", 5000.0))
        self.names(error, layer=BAD_LAYER, entity="Eje con cota imposible")

    def test_a_gradient_over_the_maximum_is_a_ramp(self) -> None:
        """RF-015-08 (D-6): con una pendiente máxima fijada, la rasante que la pasa se rechaza (es
        una rampa); igual a ella, no."""
        error = self.refused(request(max_slope_pct=0.5), "des.platform_max_slope")
        self.assertEqual((error.field, error.value), ("pendiente", 1.0))
        self.names(error, layer=efx.AXES_LAYER, entity=LOADING, maximum=0.5)
        self.assertEqual(self.units(request(max_slope_pct=1.0)).job.values["max_slope_pct"], 1.0)
        down = request("Eje en bajada", fields=line_fields(BAD_LAYER), max_slope_pct=2.0)
        error = self.refused(down, "des.platform_max_slope")  # baja un 3 %: cuenta su valor absoluto
        self.assertEqual(error.value, -3.0)
        steeper = request("Eje en bajada", fields=line_fields(BAD_LAYER), max_slope_pct=3.0)
        self.assertEqual(self.units(steeper).job.values["gradient_pct"], -3.0)

    def test_protecting_in_cut_and_fill_is_refused(self) -> None:
        """RF-015-12: una plataforma «en corte y relleno» rellena su propia huella y no puede
        declararla «sin relleno»; «en corte», sí."""
        error = self.refused(request(mode="cut_fill", protect=True, guard_m=4.0),
                             "des.platform_protect_cut_fill")
        self.assertEqual(error.field, "des.platform.plt_001.mode")
        self.names(error, layer=efx.AXES_LAYER, entity=LOADING)
        prepared = self.units(request(mode="cut", protect=True, guard_m=4.0))
        self.assertEqual((prepared.job.values["protect"], prepared.job.values["guard_m"]),
                         (True, 4.0))

    def test_a_surface_that_does_not_exist(self) -> None:
        """RF-015-09: una superficie de partida que no existe es ``gis.dataset_unknown`` (nombra la
        superficie), sin escribir nada."""
        before = self.state()
        with self.assertRaises(import_geoblender("gis.messages").GisError) as caught:
            self.prepare(request(start="gis_dtm_no_existe"))
        self.assertEqual(caught.exception.code, "gis.dataset_unknown")
        self.assertEqual(self.state(), before)


class GeometryRefusalTest(PrepareCase):
    """RF-015-08: una geometría que no es válida se rechaza con la capa, la entidad y lo que le
    pasa (los defectos del margen este de la cantera, T01)."""

    def test_an_invalid_geometry(self) -> None:
        """Un eje que se corta, cerrado o de longitud cero, un polígono que se corta, sin área o sin
        celdas y un eje enlazado que no cruza su polígono: cada uno con su código, la capa y la
        entidad nombradas."""
        cases = (
            (request("Eje que se corta"), "des.platform_self_intersects", efx.AXES_LAYER),
            (request("Eje cerrado"), "des.platform_axis_closed", efx.AXES_LAYER),
            (request("Eje de longitud cero"), "des.platform_axis_length_zero", efx.AXES_LAYER),
            (polygon_request("Polígono que se corta", linked=False),
             "des.platform_self_intersects", efx.POLYGONS_LAYER),
            (polygon_request("Polígono sin área", linked=False), "des.platform_area_zero",
             efx.POLYGONS_LAYER),
            (polygon_request("Polígono sin celdas", linked=False), "des.platform_no_cells",
             efx.POLYGONS_LAYER),
            (polygon_request("Explanada con eje que no la cruza"),
             "des.platform_axis_not_crossing", efx.POLYGONS_LAYER))
        for asked, code, layer in cases:
            with self.subTest(entity=asked.name):
                error = self.refused(asked, code)
                self.names(error, layer=layer, entity=asked.name)

    def test_a_layer_that_is_not_lines_or_polygons(self) -> None:
        """RF-015-08, RF-015-19: una capa de puntos no es una capa de plataformas."""
        asked = request("Punto", fields=line_fields(POINTS_LAYER, width_field=None))
        error = self.refused(asked, "des.platform_layer_kind")
        self.assertEqual(error.values["layer"], POINTS_LAYER)
        self.assertIn("puntos", error.text)

    def test_a_feature_that_the_layer_does_not_have_or_has_twice(self) -> None:
        """RF-015-01, RF-015-08: una geometría que la capa no tiene (por nombre o por ``fid``) o con el
        nombre repetido (hay que elegirla por su ``fid``)."""
        for feature in ("No existe", "99"):
            with self.subTest(feature=feature):
                error = self.refused(request(feature=feature), "des.entity_feature_unknown")
                self.names(error, layer=efx.AXES_LAYER, value=feature)
        asked = request("Una duplicada", fields=line_fields(BAD_LAYER), feature="Duplicada")
        error = self.refused(asked, "des.entity_feature_ambiguous")
        self.names(error, layer=BAD_LAYER, value="Duplicada", fids="4, 5")
        chosen = self.units(request("Una duplicada", fields=line_fields(BAD_LAYER), feature="4"))
        self.assertEqual(chosen.fid, 4)

    def test_the_axis_of_a_polygon_is_a_line_of_its_axis_layer(self) -> None:
        """RF-015-19: la capa de ejes de un polígono es de líneas (``des.corridor_not_lines``) y la
        línea que enlaza su campo ``eje`` está en ella (``des.entity_feature_unknown``, con la capa
        de ejes y el número): el enlace de «Explanada con eje» con otra capa."""
        def with_axes(layer: str, name: str) -> Any:
            return request(name, fields=model.PlatformFields(
                layer=efx.POLYGONS_LAYER, start_level_field="cota_inicial",
                gradient_field="pendiente", axis_field=efx.LINK_FIELD, axis_layer=layer))

        error = self.refused(with_axes(POINTS_LAYER, WITH_AXIS), "des.corridor_not_lines")
        self.assertEqual(error.values["layer"], POINTS_LAYER)
        asked = with_axes(BAD_LAYER, "Explanada con eje que no la cruza")  # su eje es la línea 9
        error = self.refused(asked, "des.entity_feature_unknown")
        self.names(error, layer=BAD_LAYER, value=efx.axis_fid("Eje corto"))

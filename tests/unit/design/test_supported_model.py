# SPDX-License-Identifier: GPL-3.0-or-later
"""Las peticiones de los cuatro tipos de entidad de la 016 (spec 016, T03; HU-016-1 a 4; RF-016-02, 03, 11, 17, 20;
plan 016 §5.1 y §5.3.1): ``StockpileRequest`` (con los campos de su capa de marcas, ``StockpileFields``),
``RemovalRequest``, ``ButtressRequest`` (con ``ButtressFields``) y ``BodyRequest``, por analogía con ``PlatformRequest``:
inmutables, comparables por valor, sin ninguna cifra minera por defecto (lo que no se pide es ``None``: el valor por
defecto del parámetro o, si no lo tiene, el rechazo de RF-015-08), con los textos sin los espacios de los extremos y los
errores del programa como ``TypeError`` o ``ValueError``.
"""

from __future__ import annotations

import dataclasses
import unittest

from tests.support.package import import_geoblender

model = import_geoblender("design.model")
messages = import_geoblender("design.messages")

STOCKPILE_PARAMS = ("margin_m", "crown_inner_m", "crown_outer_m", "crown_slope_deg", "crown_flat_min_m2",
                    "max_residual_m", "fit_rounds", "turns", "tilt_max_deg", "support_quantile", "open_diameter_m",
                    "min_height_m", "min_area_m2", "max_area_m2")


def fields(**changes: object) -> object:
    values: dict[str, object] = {"layer": "gis_fea_marcas", "name_field": "nombre"}
    values.update(changes)
    return model.StockpileFields(**values)


def stockpile(**changes: object) -> object:
    values: dict[str, object] = {"name": "Patio", "fields": fields(), "surface": "gis_dtm_patio"}
    values.update(changes)
    return model.StockpileRequest(**values)


def body(**changes: object) -> object:
    values: dict[str, object] = {
        "name": "Escombro", "layer": "gis_fea_huellas", "feature": "Cuerpo 1", "data_layer": "gis_fea_espesores",
        "data_field": "espesor", "data_from": "field", "surface": "gis_dtm_patio", "sense": "on_base",
        "start": "gis_dtm_patio"}
    values.update(changes)
    return model.BodyRequest(**values)


class EnumsTest(unittest.TestCase):
    def test_the_sense_and_where_the_thickness_comes_from(self) -> None:
        """RF-016-20 (plan 016 §5.2.2; D-8): el sentido de un cuerpo es «sobre una base» (``on_base``) o «bajo un
        techo» (``under_roof``) y el espesor de una línea 3D sale de su Z o de su M (``data_from``: ``field``, ``z`` o
        ``m``), con su texto estable (el que se registra)."""
        self.assertEqual([item.value for item in model.BodySense], ["on_base", "under_roof"])
        self.assertEqual([item.value for item in model.ThicknessSource], ["field", "z", "m"])
        for wrong in ("above", "ON_BASE", ""):
            with self.subTest(sense=wrong), self.assertRaises(ValueError):
                model.BodySense(wrong)


class StockpileTest(unittest.TestCase):
    def test_the_fields_of_the_marks_layer(self) -> None:
        """RF-016-02, 03 (plan 016 §5.2.1): la capa de marcas y los campos que se leen de ella (el nombre, el margen,
        el material y la superficie de base), que se eligen en el diálogo; sin nombre se usa el ``fid``; solo la
        capa es obligatoria."""
        found = fields(margin_field=" margen ", material_field="material", base_field="base")
        self.assertEqual((found.layer, found.name_field, found.margin_field, found.material_field, found.base_field),
                         ("gis_fea_marcas", "nombre", "margen", "material", "base"))
        bare = model.StockpileFields(layer=" gis_fea_marcas ")
        self.assertEqual((bare.layer, bare.name_field, bare.margin_field, bare.material_field, bare.base_field),
                         ("gis_fea_marcas", None, None, None, None))
        self.assertEqual(model.StockpileFields(layer="a", name_field="  "), model.StockpileFields(layer="a"))
        for blank in ("", "  "):
            with self.subTest(layer=blank), self.assertRaises(ValueError):
                model.StockpileFields(layer=blank)
        with self.assertRaises(TypeError):
            model.StockpileFields(layer=7)  # type: ignore[arg-type]

    def test_a_request_asks_for_no_mining_figure(self) -> None:
        """Principio 2, RF-016-02 (D-3): una petición no lleva ninguna cifra minera por defecto: los 14 umbrales, los
        candidatos, las decisiones y lo que declara son ``None`` (el valor por defecto del parámetro o, sin él, el
        rechazo de RF-015-08); es inmutable y comparable por valor."""
        request = stockpile()
        for name in (*STOCKPILE_PARAMS, "candidates", "decisions", "guard_m", "reason", "protect"):
            with self.subTest(field=name):
                self.assertIsNone(getattr(request, name))
        self.assertEqual((request.name, request.surface, request.layer), ("Patio", "gis_dtm_patio", "gis_fea_marcas"))
        self.assertEqual(request, stockpile())
        self.assertEqual(len({request, stockpile()}), 1)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            request.name = "otro"  # type: ignore[misc]

    def test_values_are_normalized_and_checked(self) -> None:
        """RF-016-02: los textos sin los espacios de los extremos; un número entero llega como ``float`` salvo las
        vueltas, que son enteros; un nombre en blanco, ``des.entity_name_missing``; un valor de otro tipo, un error
        del programa."""
        request = stockpile(name="  Patio ", surface=" gis_dtm_patio ", margin_m=10, fit_rounds=4, turns=6,
                            candidates=True, protect=False, reason=" motivo ", decisions="c03: convertido")
        self.assertEqual((request.name, request.surface, request.reason), ("Patio", "gis_dtm_patio", "motivo"))
        self.assertEqual((request.margin_m, type(request.margin_m)), (10.0, float))
        self.assertEqual((request.fit_rounds, type(request.fit_rounds)), (4, int))
        with self.assertRaises(messages.DesignError) as caught:
            stockpile(name="  ")
        self.assertEqual((caught.exception.code, caught.exception.field), ("des.entity_name_missing", "name"))
        for changes in ({"margin_m": "10"}, {"margin_m": True}, {"fit_rounds": 4.5}, {"turns": "6"},
                        {"candidates": 1}, {"protect": "sí"}, {"fields": "marcas"}, {"surface": 7}):
            with self.subTest(changes=changes), self.assertRaises(TypeError):
                stockpile(**changes)


class RemovalTest(unittest.TestCase):
    def test_a_removal(self) -> None:
        """RF-016-11, 14 (plan 016 §5.2.2; D-2, D-22 de la 015): la retirada pide el acopio (``STK-001#m07``), la
        superficie de la que parte y, si la hay, la de apoyo, el ángulo de transición, el factor de malla y la
        métrica; el motivo de la pared, lo que declara; lo que no se pide es ``None`` (la transición no tiene valor
        por defecto, D-2)."""
        request = model.RemovalRequest(name=" Retirada del 7 ", stockpile=" STK-001#m07 ", start="gis_dtm_patio")
        self.assertEqual((request.name, request.stockpile, request.start), ("Retirada del 7", "STK-001#m07",
                                                                         "gis_dtm_patio"))
        for name in ("support", "transition_deg", "mesh_factor", "metric", "wall_reason", "guard_m", "reason",
                     "protect"):
            with self.subTest(field=name):
                self.assertIsNone(getattr(request, name))
        full = model.RemovalRequest(name="R", stockpile="STK-001#m07", start="s", transition_deg=35, mesh_factor=0.93,
                                    metric="chamfer5", wall_reason="la propiedad lo pide", protect=True, guard_m=5)
        self.assertEqual((full.transition_deg, full.mesh_factor, full.metric.value, full.guard_m),
                         (35.0, 0.93, "chamfer5", 5.0))
        with self.assertRaises(messages.DesignError):
            model.RemovalRequest(name=" ", stockpile="STK-001#m07", start="s")
        with self.assertRaises(ValueError):
            model.RemovalRequest(name="R", stockpile="STK-001#m07", start="s", metric="chamfer3")
        with self.assertRaises(TypeError):
            model.RemovalRequest(name="R", stockpile=7, start="s")  # type: ignore[arg-type]


class ButtressTest(unittest.TestCase):
    def test_a_buttress(self) -> None:
        """RF-016-17, 18 (plan 016 §5.2.1 y §5.2.2; D-7, D-21): el contrafuerte pide su zona de coronación (la capa,
        la geometría y, si la capa la da, el campo de la cota), la partida y el apoyo, el perfil de la 013, la cota de
        coronación (sin valor por defecto: del ancla de su perfil), el alcance y la métrica; protege por defecto
        (D-1) sin que la petición lo diga (``None``)."""
        request = model.ButtressRequest(
            name=" Contrafuerte N ", fields=model.ButtressFields(layer="gis_fea_zonas", crown_field=" cota "),
            feature=" Zona 1 ", start="gis_dtm_patio", profile="expl_10_60_6", crown_m=250, reach_m=40)
        self.assertEqual((request.name, request.layer, request.fields.crown_field, request.feature),
                         ("Contrafuerte N", "gis_fea_zonas", "cota", "Zona 1"))
        self.assertEqual((request.crown_m, request.reach_m, request.protect, request.support, request.metric),
                         (250.0, 40.0, None, None, None))
        self.assertEqual(model.ButtressFields(layer="a").crown_field, None)
        with self.assertRaises(ValueError):
            model.ButtressFields(layer=" ")
        with self.assertRaises(messages.DesignError):
            model.ButtressRequest(name=" ", fields=model.ButtressFields(layer="a"), feature="Z", start="s",
                                  profile="P")
        with self.assertRaises(TypeError):
            model.ButtressRequest(name="B", fields="gis_fea_zonas", feature="Z", start="s", profile="P")  # type: ignore[arg-type]


class BodyTest(unittest.TestCase):
    def test_a_body(self) -> None:
        """RF-016-20 (plan 016 §5.2.2; D-8, D-9): el cuerpo pide su huella (la capa y la geometría), los datos de
        espesor (la capa, el campo y de dónde se lee), la superficie conocida y su sentido y, solo «sobre una base»,
        la partida; la distancia máxima y el «cero en el borde», sin valor por defecto en la petición."""
        request = body(zero_at_edge=True, max_distance_m=30)
        self.assertEqual((request.name, request.layer, request.feature, request.data_layer, request.data_field),
                         ("Escombro", "gis_fea_huellas", "Cuerpo 1", "gis_fea_espesores", "espesor"))
        self.assertEqual((request.data_from.value, request.sense.value, request.surface, request.start),
                         ("field", "on_base", "gis_dtm_patio", "gis_dtm_patio"))
        self.assertEqual((request.max_distance_m, request.zero_at_edge, request.support, request.protect),
                         (30.0, True, None, None))
        under = body(sense="under_roof", start=None, data_from="z")
        self.assertEqual((under.sense, under.start, under.data_from.value),
                         (model.BodySense.UNDER_ROOF, None, "z"))
        self.assertIsNone(body().max_distance_m)

    def test_a_body_under_a_roof_starts_from_nothing(self) -> None:
        """RF-016-20 (P-3; plan 016 §5.2.3): «bajo un techo» no cambia la superficie, así que no parte de ninguna
        (``start`` solo «sobre una base»): pedir las dos cosas es un error del programa. Que «sobre una base» tenga su
        partida lo comprueba el parámetro (``check_entity_param``), no el modelo."""
        with self.assertRaises(ValueError):
            body(sense="under_roof", start="gis_dtm_patio")
        self.assertIsNone(body(sense="on_base", start=None).start)
        for changes in ({"sense": "above"}, {"data_from": "x"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                body(**changes)
        with self.assertRaises(messages.DesignError):
            body(name=" ")
        with self.assertRaises(TypeError):
            body(max_distance_m="30")


if __name__ == "__main__":
    unittest.main()

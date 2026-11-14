# SPDX-License-Identifier: GPL-3.0-or-later
"""El modelo, los parámetros y los mensajes de la cantera con dos superficies (spec 014, T02;
HU-014-1 a 7; RF-014-02, RF-014-13, RF-014-17, RF-014-21; plan 014 §5.1, §5.2.2 y §5.3.1).

- ``design.model``: la petición de las dos superficies (``QuarryRequest``, con un
  ``QuarrySide`` por superficie), el orden (``Order``: «final primero» por defecto, D-4), el
  ancla (``AnchorMode``: fija, en rejilla o «al fondo de cada muro», RF-014-11), la clase de una
  celda (``CellClass``: sin diferencia, desdoblado o relleno, con su código 0, 1 y 2 del GeoTIFF)
  y el modo «explotación hasta la final» (``ToFinalMode``, P-2).
- ``design.params``: los siete parámetros de §5.2.2, de versión, con su rango, su unidad y su
  valor por defecto ADOPTADO «sin confirmar» (D-5, D-6, D-7) o sin valor (D-9).
- ``design.messages``: los códigos de la 014 (``des.quarry_*``, ``des.floor_*``,
  ``des.corridor_*``, ``des.conserve_*``, ``des.edge_*``, ``des.fill_only_*``, ``des.refit_*``).
"""

from __future__ import annotations

import dataclasses
import math
import re
import unittest
from pathlib import Path

from tests.support.package import import_geoblender

model = import_geoblender("design.model")
params = import_geoblender("design.params")
messages = import_geoblender("design.messages")
core_params = import_geoblender("core.params")
units = import_geoblender("core.units")
i18n = import_geoblender("core.i18n")

ParamError = core_params.ParamError
SPANISH_LETTERS = frozenset("áéíóúüñÁÉÍÓÚÜÑ¿¡")

# Plan 014 §5.2.2, en su orden: clave → (tipo de valor, unidad, por defecto, mínimo, máximo,
# máximo excluido, RF).
QUARRY_PARAMS: dict[str, tuple[str, str, float | int | None, float, float, bool,
                               tuple[str, ...]]] = {
    "des.quarry.crown_ring_cells": ("int", "-", 3, 1, 50, False, ("RF-014-02",)),
    "des.quarry.unsplit_threshold_m": ("float", "m", 1.0, 0.0, 100.0, False, ("RF-014-17",)),
    "des.quarry.unsplit_min_area_ha": ("float", "ha", 0.2, 0.0, 1000.0, False, ("RF-014-17",)),
    "des.edge.max_created_step_m": ("float", "m", 1.0, 0.0, 100.0, False, ("RF-014-21",)),
    "des.edge.min_share": ("float", "%", 99.0, 0.0, 100.0, False, ("RF-014-21",)),
    "des.edge.transition_deg": ("float", "deg", None, 0.0, 90.0, True, ("RF-014-19",)),
    "des.conserve.slope_deg": ("float", "deg", None, 0.0, 90.0, True, ("RF-014-07",)),
}

# Los códigos de la 014 con su gravedad, por familia (plan §5.1).
QUARRY_CODES: dict[str, str] = {
    "des.quarry_param_missing": "error",       # D-9
    "des.quarry_param_range": "error",         # plan §5.2.2
    "des.quarry_area_empty": "error",          # RF-014-01
    "des.quarry_area_outside_limit": "note",   # RF-014-01 (T51: lo que lo vacía, por partes)
    "des.quarry_area_untouchable": "note",     # RF-014-01 (T51)
    "des.quarry_area_inner_band": "note",      # RF-014-01 (T51)
    "des.quarry_area_no_cut": "note",          # RF-014-01 (T51)
    "des.quarry_area_no_terrain": "note",      # RF-014-01 (T51)
    "des.quarry_area_no_perimeter": "note",    # RF-014-01 (T51)
    "des.quarry_seeds_outside": "warning",     # RF-014-03
    "des.quarry_seed_group": "note",           # RF-014-03
    "des.quarry_layer_field": "error",         # plan §5.2.1
    "des.quarry_order_broken": "error",        # RF-014-14
    "des.quarry_final_no_movement": "warning",  # RF-014-12 (T61: la que se crea, nombrada)
    "des.quarry_exploitation_no_movement": "warning",  # RF-014-12, RF-014-18 (T61)
    "des.quarry_unsplit_zones": "warning",     # RF-014-17
    "des.quarry_unsplit_zone": "note",         # RF-014-17
    "des.quarry_unsplit_remaining": "warning",  # RF-014-17, RF-014-18 (T57: lo que queda)
    "des.quarry_final_exact": "error",         # RF-014-12 (T45)
    "des.quarry_exploitation_exact": "error",  # RF-014-12 (T45)
    "des.floor_overlap": "error",              # RF-014-06
    "des.floor_level": "error",                # RF-014-06
    "des.floor_above_terrain": "warning",      # RF-014-05 (caso límite)
    "des.conserve_moved": "error",             # RF-014-08 (T47: no se crea)
    "des.conserve_part": "note",               # RF-014-08
    "des.conserve_nodata": "warning",          # RF-014-07 (caso límite)
    "des.corridor_not_lines": "error",         # RF-014-09
    "des.corridor_width": "error",             # RF-014-09
    "des.corridor_length_zero": "error",       # RF-014-09
    "des.corridor_level_missing": "error",     # RF-014-09
    "des.corridor_level": "error",             # RF-014-06, RF-014-09 (T51: «corredor N»)
    "des.corridor_too_long": "warning",        # RF-014-10
    "des.edge_created_step": "warning",        # RF-014-21
    "des.edge_surface_step": "warning",        # RF-014-20, RF-014-21 (T56: el de cada diseño)
    "des.edge_stretch": "note",                # RF-014-21
    "des.edge_more_stretches": "note",         # RF-014-21 (T61: los que no enseña el resumen)
    "des.edge_more_stretches_refit": "note",   # RF-014-21 (T61: un ajuste, sin informe)
    "des.edge_not_design_surface": "error",    # RF-014-19
    "des.fill_only_cuts": "error",             # RF-014-25
    "des.fill_only_untouchable": "error",      # RF-014-25
    "des.fill_only_water_level": "error",      # RF-014-24
    "des.fill_only_water_outside": "warning",  # RF-014-23, RF-014-24 (T55: lámina fuera)
    "des.refit_outside": "warning",            # RF-014-26
    "des.refit_not_needed": "warning",         # RF-014-27 (caso límite)
    "des.refit_angle": "error",                # RF-014-28
    "des.refit_face_missing": "error",         # RF-014-27 (T49: la cara anotada)
    "des.refit_order": "note",                 # RF-014-14 (T53: la regla tras el ajuste)
    "des.refit_order_side": "warning",         # RF-014-14 (T53: una sola de las dos)
    "des.refit_source_stale": "warning",       # RF-014-27, RF-014-31 (T54: recalcular lo sustituye)
}
FAMILIES = ("des.quarry_", "des.floor_", "des.corridor_", "des.conserve_", "des.edge_",
            "des.fill_only_", "des.refit_")


def side(**changes: object) -> object:
    values: dict[str, object] = {"base_profile": "rest_5_35_6"}
    values.update(changes)
    return model.QuarrySide(**values)


def request(**changes: object) -> object:
    values: dict[str, object] = {
        "name": "Cantera V01", "start": "gis_dtm_partida", "final": side(),
        "exploitation": side(base_profile="expl_10_60_6",
                             anchor=model.AnchorMode.NEAREST_FLOOR)}
    values.update(changes)
    return model.QuarryRequest(**values)


class OptionsTest(unittest.TestCase):
    def test_order_anchor_class_and_to_final(self) -> None:
        """RF-014-13, RF-014-11, RF-014-15, RF-014-18 (D-4, P-1, P-2): los dos órdenes, los tres
        modos de ancla (con «al fondo de cada muro»), las tres clases de una celda con su código
        del GeoTIFF (0 sin diferencia, 1 desdoblado, 2 relleno) y los tres modos de «explotación
        hasta la final», con su texto estable (el que se registra en la operación)."""
        self.assertEqual([item.value for item in model.Order],
                         ["final_first", "exploitation_first"])
        self.assertEqual([item.value for item in model.AnchorMode],
                         ["fixed", "grid", "nearest_floor"])
        self.assertEqual(model.AnchorMode("nearest_floor"), model.AnchorMode.NEAREST_FLOOR)
        self.assertEqual([item.value for item in model.CellClass], ["none", "unsplit", "fill"])
        self.assertEqual([item.code for item in model.CellClass], [0, 1, 2])
        self.assertEqual(model.CellClass.from_code(1), model.CellClass.UNSPLIT)
        with self.assertRaises(ValueError):
            model.CellClass.from_code(3)
        self.assertEqual([item.value for item in model.ToFinalMode], ["none", "warned", "layer"])
        self.assertEqual([item.value for item in model.Surface], ["final", "exploitation"])
        for wrong in ("final", "both", ""):
            with self.subTest(order=wrong), self.assertRaises(ValueError):
                model.Order(wrong)


class QuarrySideTest(unittest.TestCase):
    def test_defaults_and_seeds(self) -> None:
        """RF-014-02, RF-014-12: cada lado lleva su perfil base y los de sus sectores (ordenados
        por código), sus semillas (ninguna: «coronación y zonas a sostener»; o las de la 013), su
        ancla (la del perfil por defecto) y su métrica (*chamfer* 5×5 por defecto)."""
        plain = side(sector_profiles={"sector_2": "a", "sector_1": "b"})
        self.assertTrue(plain.crown_seeds)
        self.assertIsNone(plain.seeds)
        self.assertEqual(plain.sector_profiles, (("sector_1", "b"), ("sector_2", "a")))
        self.assertEqual((plain.anchor, plain.anchor_grid, plain.metric),
                         (model.AnchorMode.FIXED, None, model.Metric.CHAMFER5))
        own = model.SeedSource(model.SeedKind.SURFACE, surface="gis_dtm_partida",
                               zone=model.Zone(model.ZoneKind.DOMAIN))
        custom = side(seeds=own, metric="exact", anchor="grid", anchor_grid="des_anclas")
        self.assertFalse(custom.crown_seeds)
        self.assertEqual((custom.metric, custom.anchor, custom.anchor_grid),
                         (model.Metric.EXACT, model.AnchorMode.GRID, "des_anclas"))
        self.assertEqual(hash(custom), hash(dataclasses.replace(custom)))

    def test_anchor_grid_only_with_grid_anchor(self) -> None:
        """RF-014-11 (D-18 de la 013): la rejilla de anclas va con el ancla en rejilla y solo
        con ella; lo contrario es un error del programa."""
        with self.assertRaises(ValueError):
            side(anchor="grid")
        with self.assertRaises(ValueError):
            side(anchor="nearest_floor", anchor_grid="des_anclas")
        with self.assertRaises(ValueError):
            side(anchor="moving")


class QuarryRequestTest(unittest.TestCase):
    def test_defaults(self) -> None:
        """RF-014-12, RF-014-13 (D-4): una petición lleva su nombre, la superficie de partida y
        los dos lados; el orden por defecto es «final primero»; sin capas ni «explotación hasta
        la final» por defecto; es inmutable y comparable por valor."""
        made = request()
        self.assertEqual(made.order, model.Order.FINAL_FIRST)
        self.assertEqual(made.exploitation.anchor, model.AnchorMode.NEAREST_FLOOR)
        self.assertIsNone(made.floors)
        self.assertEqual(made.conserve, ())
        self.assertIsNone(made.corridors)
        self.assertIsNone(made.fill_zones)
        self.assertIsNone(made.water)
        self.assertEqual((made.to_final, made.to_final_layer), (model.ToFinalMode.NONE, None))
        self.assertEqual(made.side(model.Surface.FINAL), made.final)
        self.assertEqual(made.side("exploitation"), made.exploitation)
        self.assertEqual(hash(made), hash(dataclasses.replace(made)))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            made.name = "Otra"

    def test_layers_order_and_to_final(self) -> None:
        """RF-014-05, RF-014-07, RF-014-09, RF-014-15, RF-014-18, RF-014-24 (plan §5.2.1, P-2):
        las capas con sus campos (fondos con su cota, zonas a conservar como restricción o capa,
        corredores con cota fija o rasante, relleno y láminas), el orden «explotación primero» y
        «explotación hasta la final» en las zonas de una capa."""
        made = request(
            order="exploitation_first", floors=model.LayerField("gis_fea_fondos", "cota"),
            conserve=[model.Zone(model.ZoneKind.LAYER, "gis_fea_conservar")],
            corridors=model.CorridorFields("gis_fea_corredores", width_field="ancho",
                                           start_level_field="cota_inicial",
                                           gradient_field="pendiente"),
            fill_zones="gis_fea_relleno", water=model.LayerField("gis_fea_lamina", "cota"),
            to_final="layer", to_final_layer="gis_fea_hasta_final")
        self.assertEqual(made.order, model.Order.EXPLOITATION_FIRST)
        self.assertEqual(made.conserve, (model.Zone(model.ZoneKind.LAYER, "gis_fea_conservar"),))
        self.assertTrue(made.corridors.has_gradient)
        self.assertFalse(model.CorridorFields("c", width_field="ancho",
                                              level_field="cota").has_gradient)
        self.assertEqual(made.to_final, model.ToFinalMode.LAYER)
        with self.assertRaises(ValueError):
            request(to_final="layer")
        with self.assertRaises(ValueError):
            request(to_final="warned", to_final_layer="gis_fea_hasta_final")
        with self.assertRaises(TypeError):
            request(conserve="gis_fea_conservar")

    def test_corridor_level_or_gradient(self) -> None:
        """RF-014-09: un corredor tiene una cota fija **o** una rasante (cota inicial y
        pendiente), nunca las dos ni ninguna, ni media rasante (error del programa)."""
        for wrong in ({}, {"level_field": "cota", "start_level_field": "cota_inicial",
                           "gradient_field": "pendiente"},
                      {"start_level_field": "cota_inicial"}, {"gradient_field": "pendiente"}):
            with self.subTest(fields=wrong), self.assertRaises(ValueError):
                model.CorridorFields("c", width_field="ancho", **wrong)


class QuarryParamsTest(unittest.TestCase):
    def test_the_seven_parameters_of_the_plan(self) -> None:
        """RF-014-02, RF-014-07, RF-014-17, RF-014-19, RF-014-21 (plan §5.2.2; D-5 a D-7 y D-9):
        los siete, en su orden, de ``des``, de versión, con su tipo de valor, su unidad, su rango
        y sus RF; 3 celdas, 1,0 m, 0,2 ha, 1,0 m y 99 % ADOPTADO «sin confirmar» (origen
        ``algorithm``); la transición y la conservación, ADOPTADO **sin valor** (los declara una
        persona: origen ``person``)."""
        self.assertEqual([item.key for item in params.QUARRY_DEFINITIONS], list(QUARRY_PARAMS))
        self.assertEqual(
            (params.CROWN_RING, params.UNSPLIT_THRESHOLD, params.UNSPLIT_MIN_AREA,
             params.EDGE_MAX_STEP, params.EDGE_MIN_SHARE, params.EDGE_TRANSITION,
             params.CONSERVE_SLOPE), tuple(QUARRY_PARAMS))
        for key, (value_type, unit, default, low, high, _high_excluded,
                  rfs) in QUARRY_PARAMS.items():
            definition = params.QUARRY_PARAMS[key]
            with self.subTest(key=key):
                self.assertNotIn(key, params.PARAMS)
                self.assertEqual(definition.module, "des")
                self.assertEqual((definition.value_type, definition.unit), (value_type, unit))
                self.assertIn(unit, units.UNITS)
                self.assertEqual(definition.default, default)
                if default is not None:
                    self.assertIs(type(definition.default), int if value_type == "int" else float)
                self.assertEqual((definition.minimum, definition.maximum), (low, high))
                self.assertIs(definition.min_exclusive, value_type == "float")
                self.assertEqual(definition.scope, "version")
                self.assertEqual(definition.kind, "ADOPTADO")
                self.assertEqual(definition.source_kind,
                                 "person" if default is None else "algorithm")
                self.assertEqual(definition.allow_empty, default is None)
                self.assertEqual(definition.requirements, rfs)
                self.assertIn("Spec 014", definition.source)
                if default is None:
                    self.assertIsNone(definition.check(None))
                else:
                    self.assertEqual(definition.check(default), default)
                    with self.assertRaises(ParamError):
                        definition.check(None)
                with self.assertRaises(ParamError) as caught:
                    definition.check(high + 1)
                self.assertEqual(caught.exception.code, "core.param_out_of_range")
        self.assertIn("D-7", params.QUARRY_PARAMS[params.CROWN_RING].source)
        self.assertIn("D-5", params.QUARRY_PARAMS[params.UNSPLIT_MIN_AREA].source)
        self.assertIn("D-6", params.QUARRY_PARAMS[params.EDGE_MIN_SHARE].source)
        self.assertIn("D-9", params.QUARRY_PARAMS[params.CONSERVE_SLOPE].source)

    def test_ranges_exclude_ninety_degrees(self) -> None:
        """Plan §5.2.2: el rango de cada uno (``QUARRY_RANGES``, una sola fuente con su
        ``ParamDef``); la transición y la conservación son ángulos de 0 a 90 **ambos
        excluidos**."""
        self.assertEqual(list(params.QUARRY_RANGES), list(QUARRY_PARAMS))
        for key, (_t, unit, _d, low, high, high_excluded, _rfs) in QUARRY_PARAMS.items():
            span = params.QUARRY_RANGES[key]
            definition = params.QUARRY_PARAMS[key]
            with self.subTest(key=key):
                self.assertEqual((span.minimum, span.maximum, span.unit), (low, high, unit))
                self.assertEqual(span.min_exclusive, definition.min_exclusive)
                self.assertIs(span.max_exclusive, high_excluded)
        self.assertEqual(params.QUARRY_RANGES[params.EDGE_TRANSITION].text(), "(0; 90) °")
        self.assertEqual(params.QUARRY_RANGES[params.CROWN_RING].text(), "[1; 50]")
        self.assertEqual(params.QUARRY_RANGES[params.EDGE_MIN_SHARE].text(), "(0; 100] %")

    def test_check_names_the_parameter_and_the_value(self) -> None:
        """D-9, plan §5.2.2: ``check_quarry_param`` devuelve el valor comprobado (``int`` el
        anillo, ``float`` los demás); sin valor, ``des.quarry_param_missing`` (no hay valor por
        defecto que tomar); fuera de rango (también 90°, NaN o infinito),
        ``des.quarry_param_range`` con la clave y el rango; un booleano, un texto o un anillo
        con decimales son errores del programa."""
        self.assertEqual(params.check_quarry_param(params.CROWN_RING, 3), 3)
        self.assertIs(type(params.check_quarry_param(params.CROWN_RING, 3)), int)
        self.assertEqual(params.check_quarry_param(params.EDGE_TRANSITION, 35), 35.0)
        self.assertIs(type(params.check_quarry_param(params.EDGE_TRANSITION, 35)), float)
        with self.assertRaises(messages.DesignError) as caught:
            params.check_quarry_param(params.CONSERVE_SLOPE, None)
        self.assertEqual(caught.exception.code, "des.quarry_param_missing")
        self.assertEqual(caught.exception.field, params.CONSERVE_SLOPE)
        self.assertIn("Proyecto ▸ Parámetros del proyecto…", caught.exception.text)
        for key, wrong in ((params.EDGE_TRANSITION, 90), (params.CONSERVE_SLOPE, 0),
                           (params.EDGE_TRANSITION, math.nan), (params.EDGE_MIN_SHARE, 100.5),
                           (params.CROWN_RING, 0), (params.CROWN_RING, 51),
                           (params.UNSPLIT_MIN_AREA, math.inf)):
            with self.subTest(key=key, value=wrong):
                with self.assertRaises(messages.DesignError) as caught:
                    params.check_quarry_param(key, wrong)
                self.assertEqual(caught.exception.code, "des.quarry_param_range")
                self.assertEqual(caught.exception.field, key)
                self.assertIn(params.QUARRY_RANGES[key].text(), caught.exception.text)
        for key, wrong in ((params.EDGE_TRANSITION, "35"), (params.EDGE_TRANSITION, True),
                           (params.CROWN_RING, 3.5)):
            with self.subTest(key=key, value=wrong), self.assertRaises(TypeError):
                params.check_quarry_param(key, wrong)
        with self.assertRaises(ValueError):
            params.check_quarry_param("des.tolerance.face_deg", 1.0)

    def test_labels_with_their_spanish(self) -> None:
        """RF-008-06 (principio 10): cada uno lleva su etiqueta en inglés con su español en
        ``core/i18n/messages.toml``."""
        table = i18n.load_messages()
        for definition in params.QUARRY_DEFINITIONS:
            label = definition.label_msgid
            with self.subTest(key=definition.key):
                self.assertTrue(label and label.strip())
                self.assertEqual(set(label) & SPANISH_LETTERS, set())
                self.assertIn(label, table)
                self.assertNotEqual(table[label], label)


class QuarryMessagesTest(unittest.TestCase):
    def test_codes_of_the_spec(self) -> None:
        """Plan §5.1 (principio 10): los códigos de la 014, cada uno con su gravedad, de una de
        sus siete familias; los errores se lanzan con su texto sin marcadores y nombran el
        objeto, el campo y el valor."""
        for code, severity in QUARRY_CODES.items():
            with self.subTest(code=code):
                self.assertIn(code, messages.MESSAGES)
                self.assertEqual(messages.MESSAGES[code].severity, severity)
                self.assertTrue(code.startswith(FAMILIES), code)
        for code, severity in QUARRY_CODES.items():
            message = messages.MESSAGES[code]
            values = {name: "V" for name in i18n.placeholders(message.es)}
            with self.subTest(code=code):
                if severity == "error":
                    values.pop("field", None)
                    values.pop("value", None)
                    error = messages.DesignError(code, obj="Objeto", field="campo", value=7,
                                                 **values)
                    self.assertNotIn("{", error.text)
                    self.assertNotIn("?", error.text.replace("¿", ""))
                else:
                    with self.assertRaises(ValueError):
                        messages.DesignError(code, obj="Objeto", field="campo")
                    self.assertNotIn("{", messages.render(code, **values))

    def test_texts_with_the_numbers_that_matter(self) -> None:
        """RF-014-03, RF-014-06, RF-014-17, RF-014-21, RF-014-28: los avisos dicen celdas, m²,
        ha, m³ y las coordenadas absolutas del centro; el rechazo de un fondo nombra la capa, el
        polígono, el campo y el valor; el del ajuste, la superficie y los dos ángulos."""
        group = messages.render("des.quarry_seed_group", group=1, cells=12, area=12.0,
                                x="725 010,5", y="4 400 020,5")
        self.assertEqual(group, "Grupo 1: 12 celdas, 12 m², centro en x = 725 010,5 m, "
                                "y = 4 400 020,5 m.")
        level = messages.DesignError("des.floor_level", obj="Capa «gis_fea_fondos»",
                                     field="cota", value=None, layer="gis_fea_fondos",
                                     polygon=3, low=80.0, high=2300.0)
        self.assertIn("«gis_fea_fondos»", level.text)
        self.assertIn("polígono 3", level.text)
        self.assertIn("«cota»", level.text)
        zones = messages.render("des.quarry_unsplit_zones", zones=2, area=2.1, volume=38400,
                                threshold=1.0, min_area=0.2)
        self.assertIn("2 zonas: 2,1 ha y 38400 m³", zones)
        self.assertIn("«Explotación hasta la final»", zones)
        step = messages.render("des.edge_created_step", share=4.9, pairs=812, threshold=1.0,
                               admitted=99.0, maximum=4.7, x="1", y="2", stretches=3)
        self.assertIn("4,9 %", step)
        angle = messages.DesignError("des.refit_angle", obj="Superficie «des_exp_1_v01»",
                                     field="angle", value=35.0, surface="des_exp_1_v01",
                                     profile="EXPL_10_60_6", face=60.0)
        self.assertIn("35", angle.text)
        self.assertIn("60", angle.text)
        self.assertIn("«EXPL_10_60_6»", angle.text)



class QuarryTextsTest(unittest.TestCase):
    """Los textos de la cantera (spec 014, T51; hallazgo F-12 de la verificación única): lo que
    dicen, en los dos idiomas con los mismos marcadores."""

    def test_the_singular_of_zones(self) -> None:
        """RF-014-17, RF-014-18 (F-12 (b)): el aviso de desdoblado y «explotación hasta la final»
        con una sola zona dicen «en 1 zona», no «en 1 zonas» (y «in 1 zone»); con dos, como
        siempre."""
        values = {"area": 2.0, "volume": 200_000.0, "threshold": 1.0, "min_area": 0.2}
        one = messages.render("des.quarry_unsplit_zones", zones=1, **values)
        self.assertEqual(one, "La explotación no llega a la final en 1 zona: 2 ha y 200000 m³ de "
                              "desdoblado de más de 1 m sobre terreno sin explotar, en una zona de "
                              "más de 0,2 ha. Use «Explotación hasta la final» para bajarla allí "
                              "con bancos anclados.")
        self.assertIn("in 1 zone: 2 ha", messages.render("des.quarry_unsplit_zones",
                                                         language="en", zones=1, **values))
        self.assertIn("en 2 zonas: 2 ha", messages.render("des.quarry_unsplit_zones", zones=2,
                                                          **values))
        lowered = messages.render("des.quarry_to_final", zones=1, area=0.5, volume=9_000.0)
        self.assertEqual(lowered, "«Explotación hasta la final» en 1 zona (0,5 ha): 9000 m³ "
                                  "pasan del desdoblado a la explotación, con bancos anclados a "
                                  "sus cotas.")
        self.assertIn("in 1 zone (0.5 ha)", messages.render(
            "des.quarry_to_final", language="en", zones=1, area=0.5, volume=9_000.0))
        for language in ("es", "en"):
            for code in ("des.quarry_unsplit_zones", "des.quarry_unsplit_remaining",
                         "des.quarry_to_final", "des.conserve_moved"):
                with self.subTest(code=code, language=language):
                    text = messages.render(code, language=language, zones=1, parts=1)
                    self.assertNotRegex(text, r"\b1 (zonas|zones|partes|parts)\b")

    def test_the_parts_of_an_empty_area_in_both_languages(self) -> None:
        """RF-014-01 (F-12 (c)): lo que vacía el recinto va en una nota por parte, en el idioma
        de quien lo lee: en inglés, sin una palabra en español."""
        notes = ("des.quarry_area_outside_limit", "des.quarry_area_untouchable",
                 "des.quarry_area_inner_band", "des.quarry_area_no_cut",
                 "des.quarry_area_no_terrain")
        error = messages.DesignError(
            "des.quarry_area_empty", obj="Recinto de la versión V01", field="recinto", value=0,
            version="V01", notes=tuple((code, {"area": 1_234.5}) for code in notes))
        self.assertEqual(error.text, (
            "El recinto excavable de la versión V01 está vacío: ninguna celda tiene a la vez "
            "corte admitido por sus máscaras y dato de terreno. Revise el límite y las "
            "restricciones; no se calcula ni se registra nada. Lo que lo vacía: Perímetro de "
            "actuación fuera del límite legal: 1234,5 m². Intocables y exclusiones: 1234,5 m². "
            "Resguardo hacia dentro del límite: 1234,5 m². Zonas sin corte, solo relleno o solo "
            "restauración: 1234,5 m². Celdas sin dato de terreno: 1234,5 m²."))
        english = error.text_in("en")
        self.assertEqual(english, (
            "The excavation area of version V01 is empty: no cell is both admitted to cut by its "
            "masks and has terrain data. Review the limit and the constraints; nothing is "
            "calculated or recorded. What empties it: Action perimeter outside the legal limit: "
            "1234.5 m². Untouchables and exclusions: 1234.5 m². Buffer inside the limit: "
            "1234.5 m². Zones with no cut, fill only or restoration only: 1234.5 m². Cells "
            "without terrain data: 1234.5 m²."))
        self.assertEqual(set(english) & SPANISH_LETTERS, set())
        self.assertNotIn("{parts}", messages.MESSAGES["des.quarry_area_empty"].es)

    def test_fill_only_names_what_it_has(self) -> None:
        """RF-014-25 (F-12 (d)): «Solo relleno…» no tiene semillas: sus rechazos dicen que se
        revise la envolvente, su perfil y su dominio."""
        for code in ("des.fill_only_cuts", "des.fill_only_untouchable"):
            message = messages.MESSAGES[code]
            with self.subTest(code=code):
                self.assertIn("revise la envolvente, su perfil y su dominio", message.es)
                self.assertIn("review the envelope, its profile and its domain", message.msgid)
                self.assertNotIn("semillas", message.es)
                self.assertNotIn("seeds", message.msgid)

    def test_every_design_surface_is_named(self) -> None:
        """RF-014-19, RF-014-27 (F-12 (e)): lo que no es una superficie de diseño se rechaza
        nombrando todas las que valen: las dos de una cantera, un escalonado, un «solo relleno»,
        una transición y una ajustada."""
        text = messages.render("des.edge_not_design_surface", value="gis_dtm_ladera")
        self.assertIn("(la de explotación o la final de una cantera, un escalonado, un diseño "
                      "«solo relleno», una transición o una superficie ajustada)", text)
        english = messages.render("des.edge_not_design_surface", language="en", value="x")
        self.assertIn("(the exploitation or the final surface of a quarry, a stepped design, a "
                      "fill-only design, a transition or a refitted surface)", english)

    def test_no_text_that_nothing_raises(self) -> None:
        """Spec §7 (F-12 (f)): las capas de la cantera son datos ``gis_fea_`` del proyecto, en su
        CRS por construcción: no hay un rechazo por el CRS de una capa que nada puede lanzar."""
        self.assertNotIn("des.quarry_layer_crs", messages.MESSAGES)
        self.assertFalse([m.code for m in messages.CATALOG if "reproyéctela" in m.es])

    def test_a_corridor_out_of_the_range_is_named_a_corridor(self) -> None:
        """RF-014-06, RF-014-09 (T42, T51 (h)): la cota de un corredor fuera de las del terreno
        ± 1.000 m se rechaza nombrando el corredor, no un polígono, en los dos idiomas."""
        error = messages.DesignError("des.corridor_level", obj="Corredor 2 de la capa «c»",
                                     field="cota", value=5000.0, layer="c", corridor=2,
                                     low=-819.84375, high=1307.84375)
        self.assertEqual(error.text, "Capa «c», corredor 2: «cota» = 5000 m está fuera de las "
                                     "cotas del terreno ± 1.000 m (de -819,84375 a 1307,84375 "
                                     "m); corríjalo en QGIS (no se elige ninguna cota por él); "
                                     "no se calcula nada.")
        self.assertIn("Layer «c», corridor 2: «cota» = 5000 m is outside", error.text_in("en"))

    def test_a_surface_that_moves_nothing_is_named(self) -> None:
        """RF-014-12, RF-014-18 (T61; lo que vio el H3 en E4): la superficie de la cantera que no
        mueve ninguna celda más del espesor mínimo se nombra, en los dos idiomas (el aviso de la
        013, ``des.no_movement``, decía «El diseño…» sin decir cuál de las dos)."""
        for code, es, en in (
                ("des.quarry_final_no_movement", "La superficie final de «Corta» no mueve",
                 "The final surface of «Corta» does not move"),
                ("des.quarry_exploitation_no_movement",
                 "La superficie de explotación de «Corta» no mueve",
                 "The exploitation surface of «Corta» does not move")):
            with self.subTest(code=code):
                text = messages.render(code, quarry="Corta", thickness=0.02)
                self.assertTrue(text.startswith(es), text)
                self.assertIn("más del espesor mínimo de 0,02 m: es la superficie de partida.",
                              text)
                english = messages.render(code, language="en", quarry="Corta", thickness=0.02)
                self.assertTrue(english.startswith(en), english)
                self.assertEqual(set(english) & SPANISH_LETTERS, set())

    def test_the_stretches_the_summary_leaves_out(self) -> None:
        """RF-014-21 (T61; el H3: 204 tramos dejaban «Crear» fuera de la ventana): la nota de los
        tramos que el resumen no enseña dice cuántos y dónde están, con su singular, en los dos
        idiomas; la de un ajuste dice que no tiene informe."""
        cases = (("des.edge_more_stretches", 2, "… y 2 tramos más (en el informe).",
                  "… and 2 more stretches (in the report)."),
                 ("des.edge_more_stretches", 1, "… y 1 tramo más (en el informe).",
                  "… and 1 more stretch (in the report)."),
                 ("des.edge_more_stretches_refit", 194,
                  "… y 194 tramos más (un ajuste no guarda informe).",
                  "… and 194 more stretches (a refit keeps no report)."),
                 ("des.edge_more_stretches_refit", 1,
                  "… y 1 tramo más (un ajuste no guarda informe).",
                  "… and 1 more stretch (a refit keeps no report)."))
        for code, count, es, en in cases:
            with self.subTest(code=code, count=count):
                self.assertEqual(messages.render(code, stretches=count), es)
                self.assertEqual(messages.render(code, language="en", stretches=count), en)

    def test_no_text_ends_with_an_ellipsis_and_a_full_stop(self) -> None:
        """RF-014-26 (T61; lo que vio el H3 en la ficha): un texto de la 014 que acaba en el nombre
        de una orden con «…» no lleva además el punto («límite nuevo….»); el aviso del límite
        vigente acaba en «Ajustar el diseño a un límite nuevo…»."""
        for code in QUARRY_CODES:
            message = messages.MESSAGES[code]
            for text in (message.msgid, message.es, message.one_msgid, message.one_es):
                with self.subTest(code=code, text=text[:40]):
                    self.assertNotIn("….", text)
        outside = messages.MESSAGES["des.refit_outside"]
        self.assertTrue(outside.es.endswith("Diseño ▸ Cantera ▸ Ajustar el diseño a un límite "
                                            "nuevo…"), outside.es)
        self.assertTrue(outside.msgid.endswith("Design ▸ Quarry ▸ Refit the design to a new "
                                               "limit…"), outside.msgid)

    def test_the_created_step_names_the_transitions_as_in_their_menu(self) -> None:
        """RF-014-21 (T61, (g)): los avisos del salto creado mandan a «Transiciones con el terreno
        no afectado…», con el «…» de su menú (abre un diálogo), en los dos idiomas y en singular."""
        for code in ("des.edge_created_step", "des.edge_surface_step"):
            message = messages.MESSAGES[code]
            for text in (message.es, message.one_es):
                with self.subTest(code=code):
                    self.assertTrue(text.endswith("Use «Transiciones con el terreno no "
                                                  "afectado…»."), text)
            for text in (message.msgid, message.one_msgid):
                with self.subTest(code=code):
                    self.assertTrue(text.endswith("Use «Transitions with the untouched "
                                                  "terrain…»."), text)


GRADE = re.compile(r"(?<!up)(?<!down)grade", re.IGNORECASE)
"""«grade» como palabra o como parte de un identificador (no «upgrade» ni «downgrade»)."""
DESIGN_UI = ("bl/ops/des.py", "bl/ui/des_panels.py", "bl/draw/design.py", "bl/scene/des_views.py",
             "bl/props/des.py")
"""Los módulos de ``bl`` del diseño (sus órdenes, paneles, vista y propiedades)."""


class GlossaryTest(unittest.TestCase):
    def test_grade_is_only_the_grade_of_the_ore(self) -> None:
        """Glosario §14 (T60; la T59): «grade» es la **ley**; la pendiente de la rasante de un
        corredor (RF-014-09) es ``gradient`` (``CorridorFields.gradient_field``, la propiedad
        ``corridors_gradient_field`` de la cantera y «Gradient field», en español «Campo de
        pendiente de la rasante»). Ni el diseño (``design``, sus códigos y textos) ni sus módulos
        de ``bl`` dicen «grade»: no tienen leyes."""
        root = Path(model.__file__).resolve().parents[1]
        files = [*sorted((root / "design").rglob("*.py")), *(root / name for name in DESIGN_UI)]
        found = [f"{path.relative_to(root).as_posix()}:{number}: {line.strip()}"
                 for path in files if path.is_file()
                 for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
                 if GRADE.search(line)]
        self.assertGreater(len(files), 20)
        self.assertEqual(found, [])
        fields = {item.name for item in dataclasses.fields(model.CorridorFields)}
        self.assertIn("gradient_field", fields)
        self.assertTrue(model.CorridorFields("c", "ancho", start_level_field="cota_inicial",
                                             gradient_field="pendiente").has_gradient)


if __name__ == "__main__":
    unittest.main()

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
import unittest

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
    "des.quarry_seeds_outside": "warning",     # RF-014-03
    "des.quarry_seed_group": "note",           # RF-014-03
    "des.quarry_layer_crs": "error",           # spec §7
    "des.quarry_layer_field": "error",         # plan §5.2.1
    "des.quarry_order_broken": "error",        # RF-014-14
    "des.quarry_unsplit_zones": "warning",     # RF-014-17
    "des.quarry_unsplit_zone": "note",         # RF-014-17
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
    "des.corridor_too_long": "warning",        # RF-014-10
    "des.edge_created_step": "warning",        # RF-014-21
    "des.edge_stretch": "note",                # RF-014-21
    "des.edge_not_design_surface": "error",    # RF-014-19
    "des.fill_only_cuts": "error",             # RF-014-25
    "des.fill_only_untouchable": "error",      # RF-014-25
    "des.fill_only_water_level": "error",      # RF-014-24
    "des.refit_outside": "warning",            # RF-014-26
    "des.refit_not_needed": "warning",         # RF-014-27 (caso límite)
    "des.refit_angle": "error",                # RF-014-28
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
                                           grade_field="pendiente"),
            fill_zones="gis_fea_relleno", water=model.LayerField("gis_fea_lamina", "cota"),
            to_final="layer", to_final_layer="gis_fea_hasta_final")
        self.assertEqual(made.order, model.Order.EXPLOITATION_FIRST)
        self.assertEqual(made.conserve, (model.Zone(model.ZoneKind.LAYER, "gis_fea_conservar"),))
        self.assertTrue(made.corridors.graded)
        self.assertFalse(model.CorridorFields("c", width_field="ancho",
                                              level_field="cota").graded)
        self.assertEqual(made.to_final, model.ToFinalMode.LAYER)
        with self.assertRaises(ValueError):
            request(to_final="layer")
        with self.assertRaises(ValueError):
            request(to_final="warned", to_final_layer="gis_fea_hasta_final")
        with self.assertRaises(TypeError):
            request(conserve="gis_fea_conservar")

    def test_corridor_level_or_grade(self) -> None:
        """RF-014-09: un corredor tiene una cota fija **o** una rasante (cota inicial y
        pendiente), nunca las dos ni ninguna, ni media rasante (error del programa)."""
        for wrong in ({}, {"level_field": "cota", "start_level_field": "cota_inicial",
                           "grade_field": "pendiente"},
                      {"start_level_field": "cota_inicial"}, {"grade_field": "pendiente"}):
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


if __name__ == "__main__":
    unittest.main()

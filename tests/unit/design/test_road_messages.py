# SPDX-License-Identifier: GPL-3.0-or-later
"""Los mensajes de la pista y de la accesibilidad de la 017 (spec 017, T02, T13 y T17; RF-017-04 a 07, 12, 14, 16, 17, 18, 21, 22, 24 y 25;
plan 017 §5.1 y §5.5; principio 10).

Un código ``des.road_*`` o ``des.access_*`` por cada rechazo y aviso de la spec, con su ``msgid`` en inglés y su texto
en español, con los mismos marcadores con nombre en los dos; lo que dice la spec que nombran (la capa, la pista o el
perfil, el campo y el valor; la cota mínima alcanzable sobre la final y sobre la de explotación; los estados
explorados y que reducir la holgura o subir el presupuesto puede dar una ruta…) está en el texto. No empiezan por
ninguna de las familias cerradas de la 015 ni de la 016 (``des.entity_``, ``des.platform_``, ``des.support_``,
``des.event_``, ``des.stockpile_``, ``des.removal_``, ``des.buttress_`` ni ``des.body_``): sus pruebas fijan las suyas.
"""

from __future__ import annotations

import re
import unittest

from tests.support.package import import_geoblender
from tests.support.repo import EXTENSION_DIR

messages = import_geoblender("design.messages")
i18n = import_geoblender("core.i18n")

SPANISH_LETTERS = frozenset("áéíóúüñÁÉÍÓÚÜÑ¿¡")
CLOSED_FAMILIES = ("des.entity_", "des.platform_", "des.support_", "des.event_", "des.stockpile_", "des.removal_",
                   "des.buttress_", "des.body_")
POSITION = {"x", "y"}
GEOMETRY = {"layer", "entity", "field", "value"}
PROFILE = {"profile", "field"}

# Código → (gravedad, RF, marcadores que el texto tiene que llevar).
CODES: dict[str, tuple[str, str, set[str]]] = {
    # RF-017-04: lo que se rechaza de la geometría de la pista, con la capa, la pista, el campo y el valor.
    "des.road_origin_is_destination": ("error", "RF-017-04", GEOMETRY),
    "des.road_point_outside_grid": ("error", "RF-017-04", {*GEOMETRY, *POSITION}),
    "des.road_point_no_data": ("error", "RF-017-04", {*GEOMETRY, "surface", *POSITION}),
    "des.road_line_self_intersects": ("error", "RF-017-04", {*GEOMETRY, *POSITION}),
    "des.road_line_no_length": ("error", "RF-017-04", GEOMETRY),
    "des.road_line_multipart": ("error", "RF-017-04", {*GEOMETRY, "parts"}),
    "des.road_line_repeated_vertex": ("error", "RF-017-04", {*GEOMETRY, "vertex", *POSITION}),
    "des.road_line_no_z": ("error", "RF-017-04", GEOMETRY),
    # RF-017-04 y 07: el perfil de pista (inexistente, repetido, incompleto, fuera de rango, con un radio mínimo que no cabe).
    "des.road_profile_unknown": ("error", "RF-017-04", {*GEOMETRY, "profiles"}),
    "des.road_profile_name_missing": ("error", "RF-017-07", {"profile"}),
    "des.road_profile_name_repeated": ("error", "RF-017-04", {"profile", "value", "other"}),
    "des.road_profile_value_missing": ("error", "RF-017-04", PROFILE),
    "des.road_profile_value_range": ("error", "RF-017-07", {*PROFILE, "value", "range"}),
    "des.road_profile_radius_order": ("error", "RF-017-07", {*PROFILE, "value", "radius"}),
    "des.road_profile_radius_narrow": ("error", "RF-017-04", {*PROFILE, "value", "half_width"}),
    # RF-017-04: las cotas.
    "des.road_level_range": ("error", "RF-017-04", {*GEOMETRY, "low", "high", "limit"}),
    "des.road_dest_level_out_of_zone": ("error", "RF-017-04", {*GEOMETRY, "zone", "low", "high"}),
    # T19 (preparar la pista): la malla de la ruta, la zona del destino por cota, el destino en una entidad y el origen en el eje de otra pista.
    "des.road_layer_kind": ("error", "RF-017-04", {*GEOMETRY, "expected"}),
    "des.road_layer_field": ("error", "RF-017-04", {*GEOMETRY, "fields"}),
    "des.road_mesh_not_multiple": ("error", "RF-017-04", {*GEOMETRY, "step"}),
    "des.road_dest_zone_empty": ("error", "RF-017-04", GEOMETRY),
    "des.road_destination_not_in_entity": ("error", "RF-017-03", {*GEOMETRY, "target"}),
    "des.road_destination_ambiguous": ("error", "RF-017-04", {*GEOMETRY, "target", "points"}),
    "des.road_origin_abscissa": ("error", "RF-017-03", {*GEOMETRY, "target", "length"}),
    # RF-017-04 (y RF-017-24): la accesibilidad sin punto de entrada o con uno sin dato.
    "des.access_no_entry": ("error", "RF-017-04", {"layer", "entity"}),
    "des.access_entry_no_data": ("error", "RF-017-04", {"layer", "entity", "value", "surface", *POSITION}),
    # T17: la capa de entradas (que no es de puntos o sin su campo), las rejillas de bermas, lo que avisa y lo que resume al calcular (RF-017-24 y 25).
    "des.access_layer_not_points": ("error", "RF-017-04", GEOMETRY),
    "des.access_layer_field": ("error", "RF-017-04", {*GEOMETRY, "fields"}),
    "des.access_berm_unknown": ("error", "RF-017-25", {"entity", "field", "value", "version"}),
    "des.access_entry_not_walkable": ("warning", "RF-017-24", {"layer", "entity", "value", *POSITION}),
    "des.access_nothing_reached": ("warning", "RF-017-24", {"entity"}),
    "des.access_final_none": ("warning", "RF-017-24", {"entity"}),
    "des.access_summary": ("note", "RF-017-25", {"entity", "code", "berms", "berms_reached", "platforms", "platforms_reached", "zones", "zones_reached"}),
    "des.access_levels": ("note", "RF-017-24", {"entity", "z_min", "z_max", "area"}),
    "des.access_final": ("note", "RF-017-24", {"final", "z_final"}),
    "des.access_berm_missing": ("warning", "RF-017-25", {"stretch", "source", "level", "area", *POSITION}),
    "des.access_platform_missing": ("warning", "RF-017-25", {"code"}),
    "des.access_zone_missing": ("warning", "RF-017-25", {"code", "distance", "difference", *POSITION}),
    "des.access_zone_missing_unplaced": ("warning", "RF-017-25", {"code"}),
    "des.access_more": ("note", "RF-017-25", {"more"}),
    "des.access_obsolete_dependents": ("note", "RF-015-16", {"entity", "operations", "items"}),
    # RF-017-05: la partida es la final (a) y un relleno que la pista no tiene en cuenta (b).
    "des.road_start_is_final": ("warning", "RF-017-05", {"entity", "surface", "z_final", "z_pit"}),
    "des.road_other_design_differs": ("warning", "RF-017-05", {"entity", "other", "area", "difference", *POSITION}),
    # RF-017-06: la afección de «preferible no afectar».
    "des.road_avoid_affected": ("warning", "RF-017-06", {"entity", "area", "volume", "weighted"}),
    # RF-017-12: sin ruta, las tres causas (la red 2D, el pasillo y el presupuesto de estados) y el tramo limitante.
    "des.road_no_route_network": ("error", "RF-017-12", {"layer", "entity", "z_origin", "z_destination", "gradient"}),
    "des.road_no_route_corridor": ("error", "RF-017-12", {"layer", "entity", "z_origin", "z_destination", "gradient"}),
    "des.road_budget": ("error", "RF-017-12", {"layer", "entity", "budget", "expanded", "margin"}),
    "des.road_limit_slope": ("note", "RF-017-12", {"gradient", *POSITION}),
    "des.road_limit_mask": ("note", "RF-017-12", POSITION),
    "des.road_limit_height": ("note", "RF-017-12", {"height", *POSITION}),
    "des.road_limit_grid_edge": ("note", "RF-017-12", POSITION),
    "des.road_limit_no_data": ("note", "RF-017-12", POSITION),
    # RF-017-14: el radio reducido y el rechazo por debajo del radio mínimo.
    "des.road_radius_reduced": ("warning", "RF-017-14", {"entity", "vertex", "radius", "fitted", *POSITION}),
    "des.road_radius_below_min": ("error", "RF-017-14", {"layer", "entity", "vertex", "length_before", "length_after",
                                                         "fitted", "minimum", "profile", *POSITION}),
    # RF-017-16: el desnivel que no cabe en el eje.
    "des.road_drop_too_steep": ("error", "RF-017-16", {"layer", "entity", "length", "needed", "drop", "gradient"}),
    # RF-017-17: la pendiente media por encima de la del perfil.
    "des.road_mean_gradient": ("warning", "RF-017-17", {"entity", "mean", "limit", "stretches"}),
    # RF-017-17 (T11): cada tramo de la lista del aviso de la media (``preview.Named``): abscisa, lugar y pendiente.
    "des.road_stretch": ("note", "RF-017-17", {"station", "gradient", *POSITION}),
    # RF-017-18: el modo «eje 3D», por tramo.
    "des.road_axis3d_gradient": ("warning", "RF-017-18", {"entity", "station", "gradient", "limit", *POSITION}),
    "des.road_axis3d_radius": ("warning", "RF-017-18", {"entity", "station", "radius", "minimum", *POSITION}),
    # RF-017-22: la calzada que no queda en su rasante, por las tres causas.
    "des.road_carriageway_masks": ("warning", "RF-017-22", {"entity", "area", "difference", "blocker", *POSITION}),
    "des.road_carriageway_entity": ("warning", "RF-017-22", {"entity", "area", "difference", "blocker", *POSITION}),
    "des.road_carriageway_height": ("warning", "RF-017-22", {"entity", "area", "difference", "height", *POSITION}),
    # RF-017-21 (T13): la pared del borde de la pista, más empinada que su ángulo de desmonte o de terraplén más la tolerancia de cara.
    "des.road_edge_steep": ("warning", "RF-017-21", {"entity", "cells", "cut_angle", "fill_angle", "tolerance", "max", "at_reach", "reach", "at_masks",
                                                      "other", *POSITION}),
    # T20b: la huella que la rejilla recorta (RF-015-13), la holgura del pasillo en el resumen (H-10), las dos confirmaciones que faltan (RF-017-17 y 22) y el nombre de lo que impide mover la calzada
    # cuando ninguna zona lo explica (una nota que va entre los valores de otro aviso: ``preview.Named``).
    "des.road_footprint_clipped": ("warning", "RF-015-13", {"entity", "cells", "area", *POSITION}),
    "des.road_route_margin": ("note", "RF-017-10", {"entity", "mesh", "margin", "expanded", "budget"}),
    "des.road_mean_unconfirmed": ("error", "RF-017-17", {"entity", "mean", "limit"}),
    "des.road_mean_reason": ("error", "RF-017-17", {"entity", "mean", "limit"}),
    "des.road_carriageway_unconfirmed": ("error", "RF-017-22", {"entity", "area", "difference"}),
    "des.road_blocker_masks": ("note", "RF-017-22", set()),
    # «Apoyo retirado» de cada tipo (``EntityType.removed``; RF-015-17).
    "des.road_support_removed": ("note", "RF-015-17", {"name"}),
    "des.access_support_removed": ("note", "RF-015-17", {"name"}),
    # T22b: traer las entidades de otra versión con la pista: su origen (el eje de otra pista) o su destino (una entidad) que no se trae (RF-015-18, hallazgo C-4).
    "des.road_bring_origin_lost": ("warning", "RF-015-18", {"name", "target", "source", "version"}),
    "des.road_bring_destination_lost": ("warning", "RF-015-18", {"name", "target", "source", "version"}),
    # El motivo declarado de cada tipo (``EntityType.reason``, obligatorio en la clase y no usado: la T03 los puso).
    "des.road_declared_reason": ("note", "RF-015-10", {"name"}),
    "des.access_declared_reason": ("note", "RF-015-10", {"name"}),
}
"""Los códigos de la T02 (y los de la T13, la T17 y la T20b) con su gravedad, su RF y lo que su texto nombra."""
PREFIXES = ("des.road_", "des.access_")
PROFILE_CODES = frozenset(code for code in CODES if code.startswith("des.road_profile_")) - {"des.road_profile_unknown"}
"""Los rechazos del perfil mismo (no de la pista que lo nombra: ``des.road_profile_unknown`` es de la pista)."""


class RoadMessagesTest(unittest.TestCase):
    def test_the_codes_of_the_task(self) -> None:
        """RF-017-04 a 06, 12, 14, 16 a 18 y 22 (plan 017 §5.1): cada rechazo y aviso de la spec tiene su código de
        una de las dos familias nuevas (``des.road_*`` y ``des.access_*``), con su gravedad; los del catálogo son
        exactamente estos, y ninguno es de las familias cerradas de la 015 ni de la 016; ni un código ni un ``msgid``
        se repite."""
        for code, (severity, _rf, _marks) in CODES.items():
            with self.subTest(code=code):
                self.assertIn(code, messages.MESSAGES)
                self.assertEqual(messages.MESSAGES[code].severity, severity)
                self.assertTrue(code.startswith(PREFIXES), code)
                self.assertFalse(code.startswith(CLOSED_FAMILIES), code)
                self.assertRegex(code, r"^des\.[a-z][a-z0-9_]*$")
        found = [m.code for m in messages.CATALOG if m.code.startswith(PREFIXES)]
        self.assertEqual(sorted(found), sorted(CODES))
        self.assertEqual(len(found), len(CODES))
        self.assertEqual(len({m.msgid for m in messages.CATALOG}), len(messages.CATALOG))
        self.assertEqual(len({m.code for m in messages.CATALOG}), len(messages.CATALOG))

    def test_both_languages_with_the_same_placeholders(self) -> None:
        """Principio 10: cada código tiene su ``msgid`` en inglés (sin letras del español) y su texto en español,
        distintos, con los mismos marcadores con nombre; el texto nombra lo que dice la spec; ``CATALOG_ES`` los da
        para ``core.i18n.install``."""
        for code, (_severity, _rf, marks) in CODES.items():
            message = messages.MESSAGES[code]
            with self.subTest(code=code):
                self.assertEqual(set(message.msgid) & SPANISH_LETTERS, set())
                self.assertNotEqual(message.msgid, message.es)
                self.assertEqual(i18n.placeholders(message.msgid), i18n.placeholders(message.es))
                self.assertLessEqual(marks, set(i18n.placeholders(message.es)))
                self.assertEqual(messages.CATALOG_ES[message.msgid], message.es)

    def test_a_rejection_names_the_layer_the_road_the_field_and_the_value(self) -> None:
        """RF-017-04, RF-017-07 (como RF-015-08 y RF-013-19): cada rechazo de la geometría, de las cotas, del perfil que
        la pista nombra y de la accesibilidad nombra la capa, la pista, el campo y el valor, y dice que no se crea nada;
        cada rechazo del perfil mismo nombra el perfil y el campo (el del valor, también el valor), y el que no deja
        calcular con él lo dice; el texto, en español y en inglés, no deja ningún marcador sin llenar."""
        for code, (severity, rf, _marks) in CODES.items():
            if severity != "error" or rf not in ("RF-017-04", "RF-017-07"):
                continue
            message = messages.MESSAGES[code]
            found = set(i18n.placeholders(message.es))
            with self.subTest(code=code):
                if code in PROFILE_CODES:
                    self.assertLessEqual({"profile"}, found)
                    if code != "des.road_profile_name_repeated" and code != "des.road_profile_name_missing":
                        self.assertLessEqual({"profile", "field"}, found)
                    if code in ("des.road_profile_value_range", "des.road_profile_radius_order",
                                "des.road_profile_radius_narrow"):
                        self.assertLessEqual({"value"}, found)
                        self.assertIn("no se calcula nada con este perfil", message.es)
                        self.assertIn("nothing is calculated with this profile", message.msgid)
                else:
                    self.assertLessEqual({"layer", "entity"}, found)
                    self.assertIn("no se crea nada", message.es)
                    self.assertIn("nothing is created", message.msgid)
                    if code not in ("des.access_no_entry", "des.access_entry_no_data"):
                        self.assertLessEqual({"field", "value"}, found)

    def test_a_rejection_is_raised_as_a_design_error_and_a_warning_is_not(self) -> None:
        """RF-017-04, 12, 14, 16 (plan 017 §5.1): cada error se lanza como ``DesignError`` con su objeto, su campo y su
        valor, en español y en inglés, y su texto no deja ningún marcador sin llenar (ni un «?»); un aviso o una nota
        no se lanza (``ValueError``)."""
        values = {"layer": "gis_fea_pistas_ejes", "entity": "Pista 1", "surface": "gis_dtm_tajo", "x": 725010.5,
                  "y": 4400020.5, "parts": 2, "vertex": 3, "profiles": "PISTA_PRINCIPAL, ACCESO_TAJO",
                  "profile": "PISTA_PRINCIPAL", "other": "ACCESO_TAJO", "range": "(0; 90) °", "radius": 20.0,
                  "half_width": 5.75, "low": 100.0, "high": 140.0, "limit": 1000.0, "zone": "Cota 140",
                  "z_origin": 120.0, "z_destination": 128.5, "gradient": 12.5, "margin": 60.0, "budget": 5000000,
                  "expanded": 5000001, "length_before": 14.0, "length_after": 18.0, "fitted": 9.0, "minimum": 12.0,
                  "length": 200.0, "needed": 300.0, "drop": 30.0, "name": "Pista 1",
                  "fields": "nombre, cota", "version": "V01", "step": 2.0, "target": "PLT-001", "points": 2, "expected": "puntos",
                  "mean": 10.5, "area": 60.0, "difference": 0.4}
        for code, (severity, _rf, _marks) in CODES.items():
            with self.subTest(code=code):
                if severity == "error":
                    error = messages.DesignError(code, obj="Pista", field="des.road.rdw_001.mesh_m", value=1.5, **values)
                    for text in (error.text, error.text_in("en")):
                        self.assertNotIn("{", text)
                        self.assertNotIn("?", text)
                    self.assertEqual(error.code, code)
                else:
                    with self.assertRaises(ValueError):
                        messages.DesignError(code, obj="Pista", field="campo")

    def test_a_no_route_error_carries_its_limiting_stretch_as_a_note(self) -> None:
        """RF-017-12 (plan 017 §5.4 A3): «sin ruta» es un error con sus tres causas —la red 2D no llega al origen, el
        pasillo no tiene ninguna ruta 3D y la búsqueda agota su presupuesto (``des.road_budget``, que **no** es «no
        hay ruta»)— y el **tramo limitante** con su restricción (la pendiente, una zona que las máscaras prohíben, la
        altura máxima de desmonte y terraplén, el borde de la rejilla o celdas sin dato) y su lugar, como una nota
        que va detrás; ninguno registra nada ni relaja un límite."""
        values = {"layer": "gis_fea_pistas_puntos", "entity": "Pista 1", "z_origin": 120.0, "z_destination": 128.5,
                  "gradient": 30.0}
        limits = {"des.road_limit_slope": {"gradient": 10.0}, "des.road_limit_mask": {},
                  "des.road_limit_height": {"height": 14.0}, "des.road_limit_grid_edge": {},
                  "des.road_limit_no_data": {}}
        self.assertEqual(len(limits), 5)
        for cause in ("des.road_no_route_network", "des.road_no_route_corridor"):
            for note, extra in limits.items():
                with self.subTest(cause=cause, note=note):
                    error = messages.DesignError(cause, obj="Pista 1", field="des.road.rdw_001.mesh_m", value=4.0,
                                                 notes=[(note, {"x": 725010.5, "y": 4400020.5, **extra})], **values)
                    self.assertIn("x = 725010,5 m", error.text)
                    self.assertIn("725010.5", error.text_in("en"))
                    self.assertIn("no se crea nada", error.text)
                    self.assertIn("no se relaja ningún límite", error.text)
                    self.assertNotIn("?", error.text)
        text = messages.MESSAGES["des.road_no_route_network"].es
        for name in ("z_origin", "z_destination", "gradient"):
            self.assertIn("{" + name + "}", text)
        with self.assertRaises(ValueError):  # un error no es una nota: no acompaña a otro error
            messages.DesignError("des.road_no_route_network", obj="Pista 1", field="campo", value=1.0,
                                 notes=[("des.road_budget", {})], **values)

    def test_the_budget_says_what_to_do_and_is_not_no_route(self) -> None:
        """RF-017-12 (la tercera causa): cuando la búsqueda agota su presupuesto de estados, el texto dice los estados
        explorados, que **no significa** que no haya ruta y que reducir la holgura o subir el presupuesto puede dar
        una (``des.road_budget``), y no registra nada ni relaja un límite."""
        message = messages.MESSAGES["des.road_budget"]
        for text, words in ((message.es, ("holgura", "presupuesto", "no significa que no haya ruta", "explorados",
                                          "no se crea nada", "no se relaja")),
                            (message.msgid, ("slack", "budget", "does not mean there is no route", "explored",
                                             "nothing is created", "no limit is relaxed"))):
            for word in words:
                self.assertIn(word, text)
        text = messages.render("des.road_budget", layer="gis_fea_pistas_puntos", entity="Pista 1", budget=5000000,
                               expanded=5000012, margin=60.0)
        self.assertIn("5000000", text)
        self.assertIn("5000012", text)
        self.assertIn("«Pista 1»", text)

    def test_the_start_from_the_final_surface_says_both_levels(self) -> None:
        """RF-017-05 (a): sobre la superficie final restaurada de una cantera, la pista dice que no se llega al fondo,
        con la cota mínima alcanzable sobre ella y sobre la de explotación (136,5 m frente a 125 m en el error 23), y se
        puede crear igualmente (un aviso); y el relleno que la pista no tiene en cuenta (b), con el área, la diferencia
        máxima y el lugar."""
        text = messages.render("des.road_start_is_final", entity="Pista 1", surface="gis_dtm_tajo_final",
                               z_final=136.5, z_pit=125.0)
        for expected in ("«Pista 1»", "«gis_dtm_tajo_final»", "136,5", "125", "no se llega al fondo", "igualmente"):
            self.assertIn(expected, text)
        english = messages.render("des.road_start_is_final", language="en", entity="Pista 1",
                                  surface="gis_dtm_tajo_final", z_final=136.5, z_pit=125.0)
        self.assertIn("136.5", english)
        self.assertIn("bottom", english)
        other = messages.render("des.road_other_design_differs", entity="Pista 1", other="Relleno V09", area=640.0,
                                difference=2.5, x=725010.0, y=4400020.0)
        for expected in ("«Pista 1»", "«Relleno V09»", "640", "2,5", "x = 725010 m", "y = 4400020 m", "igualmente"):
            self.assertIn(expected, other)

    def test_the_steep_drop_names_the_axis_the_needed_length_and_the_drop(self) -> None:
        """RF-017-16: el rechazo por un desnivel que no cabe nombra la longitud del eje, la necesaria y el desnivel, y
        dice que no cambia las cotas ni la pendiente por su cuenta; RF-017-14: el rechazo por debajo de Rmín nombra
        el vértice, la longitud de los tramos y el radio que cabría, y qué hacer (mover el vértice, simplificar más o
        menos, otro perfil)."""
        text = messages.render("des.road_drop_too_steep", layer="gis_fea_pistas_puntos", entity="Pista 1",
                               length=200.0, needed=300.0, drop=30.0, gradient=10.0)
        for expected in ("200", "300", "30", "no se cambian las cotas ni la pendiente", "no se crea nada"):
            self.assertIn(expected, text)
        text = messages.render("des.road_radius_below_min", layer="gis_fea_pistas_ejes", entity="Pista 1", vertex=3,
                               length_before=14.0, length_after=18.0, fitted=9.0, minimum=12.0,
                               profile="PISTA_PRINCIPAL", x=1.0, y=2.0)
        for expected in ("vértice 3", "14 m", "18 m", "9 m", "12 m", "«PISTA_PRINCIPAL»", "mueva el vértice",
                         "simplifique más o menos", "otro perfil", "no se baja"):
            self.assertIn(expected, text)

    def test_the_confirmations_are_expressed(self) -> None:
        """RF-017-17, RF-017-22: la pendiente media por encima de la del perfil y la calzada que no queda en su
        rasante se avisan antes de crear y dicen que no se crea sin la confirmación expresa (y, la media, un motivo
        que queda registrado); la rasante lleva su contexto («perfil de cotas»), no sola."""
        mean = messages.MESSAGES["des.road_mean_gradient"]
        for word in ("confirmación expresa", "motivo", "registrados"):
            self.assertIn(word, mean.es)
        for code in ("des.road_carriageway_masks", "des.road_carriageway_entity", "des.road_carriageway_height"):
            with self.subTest(code=code):
                message = messages.MESSAGES[code]
                self.assertIn("confirmación expresa", message.es)
                self.assertIn("express confirmation", message.msgid)
                self.assertIn("perfil de cotas", message.es)
                self.assertIn("rasante", message.es)

    def test_the_axis_3d_line_without_z_says_where_the_z_comes_from(self) -> None:
        """RF-017-18, T23-a (decisión de la sesión principal, 20/11/2026): una línea sin Z en el modo «eje 3D» se
        rechaza diciendo que una capa de entidades (``gis_fea_``) solo guarda X e Y y que la Z viene de una capa de líneas
        3D (``gis_brk_``) o de la que deja «Proponer el trazado…»; la rasante lleva su contexto (el perfil de cotas)."""
        message = messages.MESSAGES["des.road_line_no_z"]
        for word in ("no tiene Z", "X e Y", "gis_fea_", "gis_brk_", "Proponer el trazado", "perfil de cotas"):
            self.assertIn(word, message.es)
        for word in ("has no Z", "X and Y", "gis_fea_", "gis_brk_", "Propose the route"):
            self.assertIn(word, message.msgid)

    def test_no_mining_figure_is_written_in_the_text(self) -> None:
        """Principio 2 (RF-017-04; plan 017 §5.9): los 1.000 m de la cota fuera del terreno y todo número del que dependa
        una decisión llegan como valores, no escritos en el texto: ningún mensaje de la 017 lleva una cifra, salvo el
        «3D» de «eje 3D» y de «ruta 3D» y el «2D» de la red."""
        digits = re.compile(r"[0-9]")
        for code in CODES:
            message = messages.MESSAGES[code]
            for text in (message.es, message.msgid):
                stripped = re.sub(r"\{[a-z_0-9]+\}", "", text).replace("3D", "").replace("2D", "")
                with self.subTest(code=code):
                    self.assertIsNone(digits.search(stripped), text)

    def test_the_spanish_of_the_messages_lives_in_the_design_catalog(self) -> None:
        """El español de un mensaje con código vive en ``design/messages.py``; ``core/i18n/messages.toml`` solo trae las
        etiquetas (de los parámetros, los tipos de operación y las cifras): ningún ``msgid`` de estos mensajes está
        repetido ahí (el mismo texto en dos sitios podría divergir)."""
        text = (EXTENSION_DIR / "core" / "i18n" / "messages.toml").read_text(encoding="utf-8")
        for code in CODES:
            message = messages.MESSAGES[code]
            with self.subTest(code=code):
                self.assertNotIn(f'["{message.msgid}"]', text)


if __name__ == "__main__":
    unittest.main()

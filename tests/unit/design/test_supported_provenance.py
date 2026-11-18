# SPDX-License-Identifier: GPL-3.0-or-later
"""La procedencia de los cuatro tipos de entidad de la 016 (spec 016, T03; HU-016-1 a 4; RF-016-02 a 22; plan 016
§2.1, §5.1 y §5.2.3; ADR-0025 y ADR-0031 §3; RNF-016-07): sus tipos de operación, las familias de datos de la detección
y del cuerpo bajo un techo con su nombre y su ubicación **en los dos ámbitos** (el del proyecto, sin código de versión),
los papeles con que las leen la 011, la 012 y R-18, las funciones de ajustes, entradas y parámetros de cada tipo, sus
cifras con su ámbito (también el del acopio y su material) y las **listas cerradas** de ``design`` (``RECOMPUTED`` y la
cadena de ``recompute_run``, ``OPERATION_TYPES_BY_NAME``, ``reproduce``), que esta tarea amplía **sin comportamiento**
todavía: ninguna operación de estos tipos existe hasta que las tareas siguientes las crean.
"""

from __future__ import annotations

import dataclasses
import math
import unittest
from typing import Any

from tests.support.package import import_geoblender

provenance = import_geoblender("design.provenance")
params = import_geoblender("design.params")
model = import_geoblender("design.model")
store = import_geoblender("design.store")
reproduce_mod = import_geoblender("design.reproduce")
contract = import_geoblender("core.provenance.contract")
operations = import_geoblender("core.provenance.operations")
recompute_mod = import_geoblender("core.provenance.recompute")
versions_reproduce = import_geoblender("core.versions.reproduce")
datasets = import_geoblender("core.datasets.model")
i18n = import_geoblender("core.i18n")
figures_mod = import_geoblender("core.provenance.figures")

SPANISH_LETTERS = frozenset("áéíóúüñÁÉÍÓÚÜÑ¿¡")
TYPES = {"stockpile": "des.stockpile_detect", "removal": "des.stockpile_removal", "buttress": "des.buttress",
         "body": "des.body"}
LABELS = {"des.stockpile_detect": "Stockpile detection", "des.stockpile_removal": "Stockpile removal",
          "des.buttress": "Buttress", "des.body": "Supported body"}
COMMANDS = {"des.stockpile_detect": "geoblender.des_detect_stockpiles",
            "des.stockpile_removal": "geoblender.des_remove_stockpile",
            "des.buttress": "geoblender.des_add_buttress", "des.body": "geoblender.des_create_body"}
OUTPUTS = {"des.stockpile_detect": ("stk", "stc", "stb", "stt", "stg", "stp", "prp"),
           "des.stockpile_removal": ("psf", "epr", "prp"), "des.buttress": ("psf", "epr", "prp"),
           "des.body": ("bdt", "bds", "psf", "epr", "prp")}
# Código → (tipo, almacén, lector, papel, extensión) de las ocho familias de datos nuevas (plan 016 §5.2.3).
FAMILIES = {
    "stk": ("table", "gpkg", "core.gpkg_layer@1", "stockpiles", ""),
    "stc": ("table", "gpkg", "core.gpkg_layer@1", "stockpile_candidates", ""),
    "stb": ("raster", "rasters", "gis.geotiff@1", "stockpile_base", ".tif"),
    "stt": ("raster", "rasters", "gis.geotiff@1", "stockpile_thickness", ".tif"),
    "stg": ("raster", "rasters", "gis.geotiff@1", "stockpile_ground", ".tif"),
    "stp": ("raster", "rasters", "gis.geotiff@1", "stockpile_surface", ".tif"),
    "bdt": ("raster", "rasters", "gis.geotiff@1", "body_thickness", ".tif"),
    "bds": ("raster", "rasters", "gis.geotiff@1", "body_base", ".tif"),
}
# Las cifras de plan §5.2.3 por tipo: clave → unidad.
FIGURES = {
    "des.stockpile_detect": {"des.stk_count": "-", "des.stk_candidates": "-", "des.stk_area_m2": "m2",
                             "des.stk_volume_m3": "m3", "des.stk_thickness_max_m": "m",
                             "des.stk_plane_tilt_deg": "deg"},
    "des.stockpile_removal": {"des.rmv_removed_m3": "m3", "des.rmv_resting_m3": "m3",
                              "des.rmv_transition_m3": "m3", "des.rmv_kept_m3": "m3",
                              "des.rmv_transition_m2": "m2", "des.rmv_wall_max_m": "m"},
    "des.buttress": {"des.btr_volume_m3": "m3", "des.btr_area_m2": "m2", "des.btr_height_max_m": "m",
                     "des.btr_cutoff_m2": "m2", "des.btr_cutoff_m3": "m3"},
    "des.body": {"des.bdy_volume_m3": "m3", "des.bdy_thickness_max_m": "m", "des.bdy_far_m2": "m2",
                 "des.bdy_far_m3": "m3", "des.bdy_ignored": "-"},
}


def recompute(request: Any) -> Any:  # pragma: no cover - solo para construir las definiciones
    return None


def reproduce(request: Any) -> Any:  # pragma: no cover
    return None


class OperationTypesTest(unittest.TestCase):
    def test_the_four_types(self) -> None:
        """RF-016-02, 11, 17, 20 (plan 016 §5.2.3; ADR-0025): cuatro tipos de operación de la versión, del módulo
        ``des``, versión 1.0, repetibles y reproducibles con 10⁻⁹ relativo, sin grupo acoplado, cada uno con su orden
        del catálogo (las definitivas de la T35: ``des_edit_stockpile`` y ``des_add_buttress`` no se renombran), sus
        familias de datos y sus cifras; van aparte de los de las tres specs anteriores, que siguen como estaban."""
        self.assertEqual((provenance.STOCKPILE_DETECT, provenance.STOCKPILE_REMOVAL, provenance.BUTTRESS,
                          provenance.BODY), tuple(TYPES.values()))
        self.assertEqual([t.op_type for t in provenance.SUPPORTED_OPERATION_TYPES], list(TYPES.values()))
        self.assertEqual(provenance.SUPPORTED_VERSION_TYPES, tuple(TYPES.values()))
        self.assertEqual(provenance.SUPPORTED_REPRODUCIBLE, tuple(TYPES.values()))
        self.assertEqual(provenance.OP_VERSION, "1.0")
        for declared in provenance.SUPPORTED_OPERATION_TYPES:
            op_type = declared.op_type
            with self.subTest(op_type=op_type):
                self.assertIs(provenance.OPERATION_TYPES_BY_NAME[op_type], declared)
                self.assertEqual(declared.label_msgid, LABELS[op_type])
                self.assertEqual(declared.outputs, OUTPUTS[op_type])
                self.assertEqual(declared.commands, (COMMANDS[op_type],))
                self.assertEqual(declared.settings, ())
                self.assertTrue(declared.reproducible)
                self.assertFalse(declared.drops_discarded)
                self.assertEqual([figure.key for figure in declared.figures
                                  if figure.key != provenance.SUPPORTED_M3], list(FIGURES[op_type]))
                built = provenance.operation_def(op_type, recompute, reproduce)
                self.assertIsInstance(built, contract.OperationDef)
                self.assertEqual((built.op_type, built.version, built.module, built.scope, built.repeatable,
                                  built.group, built.reproduce, built.recompute),
                                 (op_type, "1.0", "des", "version", True, None, reproduce, recompute))
                self.assertEqual(built.figure_tolerance, provenance.FIGURE_TOLERANCE)
        for older in (*provenance.OPERATION_TYPES, *provenance.QUARRY_OPERATION_TYPES,
                      *provenance.ENTITY_OPERATION_TYPES):
            self.assertIs(provenance.OPERATION_TYPES_BY_NAME[older.op_type], older)
        self.assertEqual(len(provenance.OPERATION_TYPES_BY_NAME), 2 + 5 + 3 + 4)

    def test_the_support_figure_is_also_left_by_what_fills_on_a_stockpile(self) -> None:
        """RF-016-14, RF-015-15 (ADR-0031 §4): la retirada y el contrafuerte —lo que rellena sobre una huella—
        dejan también ``des.supported_m3``; la detección y el cuerpo, no."""
        for op_type, expected in (("des.stockpile_removal", True), ("des.buttress", True),
                                  ("des.stockpile_detect", False), ("des.body", False)):
            declared = provenance.OPERATION_TYPES_BY_NAME[op_type]
            with self.subTest(op_type=op_type):
                self.assertEqual(provenance.SUPPORTED_M3 in {item.key for item in declared.figures}, expected)

    def test_the_functions_of_the_definitions_are_checked(self) -> None:
        """RF-008-26, RF-009-11: ``supported_operation_defs`` arma las cuatro definiciones, en su orden, con su
        función de recálculo y de reproducción; ``ValueError`` si sobra o falta alguna."""
        functions = {op_type: recompute for op_type in TYPES.values()}
        replays = {op_type: reproduce for op_type in TYPES.values()}
        built = provenance.supported_operation_defs(functions, replays)
        self.assertEqual([item.op_type for item in built], list(TYPES.values()))
        self.assertTrue(all(item.scope == "version" and item.repeatable for item in built))
        with self.assertRaises(ValueError):
            provenance.supported_operation_defs({"des.body": recompute}, replays)
        with self.assertRaises(ValueError):
            provenance.supported_operation_defs(functions, {**replays, "des.platform": reproduce})

    def test_names_and_labels_have_their_spanish(self) -> None:
        """Principio 10: el nombre de cada tipo y de cada cifra es un ``msgid`` en inglés (sin letras del español)
        con su traducción en ``core/i18n/messages.toml``."""
        msgids = {declared.label_msgid for declared in provenance.SUPPORTED_OPERATION_TYPES}
        msgids |= {figure.label_msgid for figure in provenance.SUPPORTED_FIGURES}
        for msgid in msgids:
            with self.subTest(msgid=msgid):
                self.assertEqual(set(msgid) & SPANISH_LETTERS, set())
        self.assertEqual(i18n.untranslated(sorted(msgids)), [])
        table = i18n.load_messages()
        self.assertTrue(all(table[msgid] != msgid for msgid in msgids))


class DataFamiliesTest(unittest.TestCase):
    def test_the_eight_families_and_their_roles(self) -> None:
        """RF-016-09, RF-016-20 (plan 016 §5.2.3; ADR-0031 §3; P-4, P-5): ``des_stk_`` (los acopios), ``des_stc_`` (los
        candidatos), ``des_stb_`` (la base de cada material), ``des_stt_`` (su espesor), ``des_stg_`` (el terreno sin
        acopios en las huellas), ``des_stp_`` (la superficie con que se detectó), ``des_bdt_`` (el espesor de un
        cuerpo) y ``des_bds_`` (su base bajo un techo): tablas y rejillas dispersas, cada una con **su papel**, que
        es por el que las leen la 011, la 012 y R-18 sin importar ``design``; ninguna lleva el papel de una
        superficie de diseño (no se congelan como tales)."""
        self.assertEqual([family.code for family in provenance.SUPPORTED_FAMILIES], list(FAMILIES))
        self.assertEqual((provenance.STOCKPILES_TABLE, provenance.STOCKPILE_CANDIDATES_TABLE,
                          provenance.STOCKPILE_BASE_GRID, provenance.STOCKPILE_THICKNESS_GRID,
                          provenance.STOCKPILE_GROUND_GRID, provenance.STOCKPILE_SURFACE_GRID,
                          provenance.BODY_THICKNESS_GRID, provenance.BODY_BASE_GRID), tuple(FAMILIES))
        for family in provenance.SUPPORTED_FAMILIES:
            kind, store_name, reader, role, extension = FAMILIES[family.code]
            with self.subTest(family=family.code):
                self.assertIs(provenance.FAMILIES_BY_CODE[family.code], family)
                self.assertEqual((family.kind, str(family.store), family.reader, family.role, family.extension),
                                 (kind, store_name, reader, role, extension))
                self.assertTrue(family.named)
                self.assertEqual(family.prefix, f"des_{family.code}_")
                self.assertTrue(family.label.strip())
        roles = [family.role for family in provenance.SUPPORTED_FAMILIES]
        self.assertEqual(len(set(roles)), 8)
        older = {family.role for family in (*provenance.FAMILIES, *provenance.QUARRY_FAMILIES,
                                            *provenance.ENTITY_FAMILIES)}
        self.assertEqual(set(roles) & older, set())
        self.assertNotIn(provenance.DESIGN_SURFACE_ROLE, roles)
        self.assertEqual(len(provenance.FAMILIES_BY_CODE), 5 + 10 + 5 + 8)  # 013, 014, 015 y 016

    def test_the_roles_of_what_the_operations_consume(self) -> None:
        """RF-016-02, 11, 17, 20 (plan 016 §5.2.3): los papeles con que se consumen la capa de marcas, el acopio
        que se retira (su tabla y su base) y los datos de espesor de un cuerpo; el de la zona de un contrafuerte y la
        huella de un cuerpo es el de la capa de entidades de la 015."""
        self.assertEqual((provenance.MARKS_LAYER_ROLE, provenance.REMOVED_STOCKPILE_ROLE,
                          provenance.BODY_DATA_ROLE), ("marks_layer", "removed_stockpile", "body_data"))
        self.assertEqual((provenance.STOCKPILES_ROLE, provenance.STOCKPILE_CANDIDATES_ROLE,
                          provenance.STOCKPILE_BASE_ROLE, provenance.STOCKPILE_THICKNESS_ROLE,
                          provenance.STOCKPILE_GROUND_ROLE, provenance.STOCKPILE_SURFACE_ROLE,
                          provenance.BODY_THICKNESS_ROLE, provenance.BODY_BASE_ROLE),
                         tuple(item[3] for item in FAMILIES.values()))
        self.assertEqual(provenance.ENTITY_LAYER_ROLE, "entity_layer")

    def test_names_and_locators_in_the_two_scopes(self) -> None:
        """RF-016-02 (D-15; ADR-0031 §2; RF-008-17, D-34 de la 009): el nombre ``des_<familia>_<nombre>`` es el mismo
        en los dos ámbitos y la ubicación lleva el código de la versión si la detección es de una versión
        (``rasters/des_stb_patio_cobre_v02.tif``) y **no lo lleva** si es del proyecto (``rasters/des_stb_patio_cobre.tif``
        y ``des_stk_patio``); la ``DatasetSpec`` es de ``des``, sin selector, con su papel y no editable en QGIS."""
        self.assertEqual(provenance.dataset_name("stb", "Patio cobre"), "des_stb_patio_cobre")
        self.assertEqual(provenance.dataset_name("bds", "Cuerpo Ñandú"), "des_bds_cuerpo_nandu")
        self.assertEqual(provenance.dataset_locator("stb", "Patio cobre", "V02"),
                         "rasters/des_stb_patio_cobre_v02.tif")
        self.assertEqual(provenance.dataset_locator("stb", "Patio cobre", None),
                         "rasters/des_stb_patio_cobre.tif")
        self.assertEqual(provenance.dataset_locator("stk", "Patio", "V02"), "des_stk_patio_v02")
        self.assertEqual(provenance.dataset_locator("stk", "Patio", None), "des_stk_patio")
        self.assertEqual(provenance.dataset_locator("stc", "Patio", None), "des_stc_patio")
        for code in FAMILIES:
            for version in ("V03", None):
                with self.subTest(family=code, version=version):
                    found = provenance.dataset_spec(code, "Patio", version, crs_epsg=25830)
                    kind, _store, reader, role, extension = FAMILIES[code]
                    self.assertEqual((found.name, found.module, found.kind, found.reader, found.role,
                                      found.crs_epsg),
                                     (f"des_{code}_patio", "des", kind, reader, role, 25830))
                    self.assertIsInstance(found, datasets.DatasetSpec)
                    expected = f"des_{code}_patio" if version is None else f"des_{code}_patio_v03"
                    self.assertEqual(found.locator,
                                     expected if not extension else f"rasters/{expected}{extension}")
        self.assertEqual(provenance.dataset_locator("env", "Hoyo", "V01"), "rasters/des_env_hoyo_v01.tif")  # sin cambios
        with self.assertRaises(ValueError):
            provenance.dataset_locator("stk", "Patio", "v2")  # el código de una versión es V01
        with self.assertRaises(ValueError):
            provenance.dataset_locator("zzz", "Patio", None)


def stockpile_request(**changes: Any) -> Any:
    values: dict[str, Any] = {
        "name": "Patio de acopios", "surface": "gis_dtm_patio", "candidates": True, "margin_m": 15.0,
        "fields": model.StockpileFields(layer="gis_fea_marcas", name_field="nombre", margin_field="margen",
                                        material_field="material", base_field="base")}
    values.update(changes)
    return model.StockpileRequest(**values)


class SettingsRequestsTest(unittest.TestCase):
    def test_the_stockpile_settings_and_request_round_trip(self) -> None:
        """RF-016-02, RF-015-02 (ADR-0025): los ajustes de ``des.stockpile_detect`` son JSON sin rutas: el nombre, su
        código ``STK-001`` y los campos de la capa de marcas; **nada más** (la capa, la superficie y los umbrales
        son **parámetros** de la entidad); con los valores de sus parámetros salen la misma petición."""
        request = stockpile_request()
        settings = provenance.stockpile_settings(request, "STK-001")
        self.assertEqual(settings, {"name": "Patio de acopios", "code": "STK-001",
                                    "fields": {"name_field": "nombre", "margin_field": "margen",
                                               "material_field": "material", "base_field": "base"}})
        self.assertEqual(provenance.supported_code(settings), "STK-001")
        values = {"layer": "gis_fea_marcas", "surface": "gis_dtm_patio", "candidates": True, "margin_m": 15.0}
        self.assertEqual(provenance.stockpile_request(settings, values), request)
        parameters = {"des.stockpile.stk_001.layer": "gis_fea_marcas", "des.stockpile.stk_001.margin_m": 15.0,
                      "des.stockpile.stk_001.surface": "gis_dtm_patio", "des.stockpile.stk_001.candidates": True,
                      "des.stockpile.stk_002.margin_m": 99.0, "des.platform.plt_001.width_m": 4.0,
                      "res.anthropic_presence_m": 0.3}
        self.assertEqual(provenance.supported_values("STK-001", parameters), values)
        with self.assertRaises(ValueError):
            provenance.supported_code({"name": "x"})
        with self.assertRaises(ValueError):
            provenance.stockpile_request(settings, {"layer": "a", "surface": "b", "width_m": 3.0})
        with self.assertRaises(ValueError):
            provenance.stockpile_request(settings, {"surface": "b"})  # sin capa
        with self.assertRaises(TypeError):
            provenance.stockpile_settings("petición", "STK-001")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            provenance.stockpile_settings(request, "stk_001")

    def test_the_other_settings_and_requests_round_trip(self) -> None:
        """RF-016-11, 17, 20: lo mismo para la retirada, el contrafuerte y el cuerpo: el nombre y el código (y, en el
        contrafuerte, el campo de la cota de su capa); el resto, parámetros."""
        removal = model.RemovalRequest(name="Retirada del 7", stockpile="STK-001#m07", start="gis_dtm_patio",
                                       transition_deg=35.0, metric="chamfer5")
        settings = provenance.removal_settings(removal, "RMV-001")
        self.assertEqual(settings, {"name": "Retirada del 7", "code": "RMV-001"})
        values = {"stockpile": "STK-001#m07", "start": "gis_dtm_patio", "transition_deg": 35.0,
                  "metric": "chamfer5"}
        self.assertEqual(provenance.removal_request(settings, values), removal)
        buttress = model.ButtressRequest(
            name="Contrafuerte N", fields=model.ButtressFields(layer="gis_fea_zonas", crown_field="cota"),
            feature="Zona 1", start="gis_dtm_patio", profile="expl_10_60_6", crown_m=250.0)
        settings = provenance.buttress_settings(buttress, "BTR-002")
        self.assertEqual(settings, {"name": "Contrafuerte N", "code": "BTR-002", "fields": {"crown_field": "cota"}})
        values = {"layer": "gis_fea_zonas", "feature": "Zona 1", "start": "gis_dtm_patio",
                  "profile": "expl_10_60_6", "crown_m": 250.0}
        self.assertEqual(provenance.buttress_request(settings, values), buttress)
        body = model.BodyRequest(name="Escombro", layer="gis_fea_huellas", feature="Cuerpo 1",
                                 data_layer="gis_fea_espesores", data_field="espesor", data_from="field",
                                 surface="gis_dtm_patio", sense="under_roof", max_distance_m=30.0)
        settings = provenance.body_settings(body, "BDY-003")
        self.assertEqual(settings, {"name": "Escombro", "code": "BDY-003"})
        values = {"layer": "gis_fea_huellas", "feature": "Cuerpo 1", "data_layer": "gis_fea_espesores",
                  "data_field": "espesor", "data_from": "field", "surface": "gis_dtm_patio",
                  "sense": "under_roof", "max_distance_m": 30.0}
        self.assertEqual(provenance.body_request(settings, values), body)
        for build, ok in ((provenance.removal_request, {"stockpile": "S", "start": "T"}),
                          (provenance.buttress_request, {"layer": "L", "feature": "F", "start": "T",
                                                         "profile": "P"})):
            with self.subTest(build=build.__name__), self.assertRaises(ValueError):
                build({"name": "x", "code": "RMV-001", "fields": {"crown_field": None}},
                      {**ok, "no_such": 1})


class InputsAndParametersTest(unittest.TestCase):
    def test_what_each_type_consumes(self) -> None:
        """RF-016-02, 08, 11, 14, 17, 20 (plan 016 §5.2.3; ADR-0031 §3): lo que consume cada tipo con su papel, sin
        repetir: la detección, la capa de marcas, la superficie, las máscaras de la versión y, en el proyecto, el
        perímetro; la retirada, la partida, el acopio retirado (su tabla y su base, ``removed_stockpile``), las
        máscaras y, **añadidas al crear**, lo que apoya (``supported_on``); el contrafuerte, su zona, la partida, las
        máscaras y lo que apoya; el cuerpo, su huella, sus datos de espesor (``body_data``), la superficie conocida,
        las máscaras y lo que apoya."""
        Use = operations.Use
        mask = Use("gis_msk_a", "mask")
        perimeter = Use("core_constraint_perimeter", "perimeter")
        self.assertEqual(
            provenance.stockpile_inputs(stockpile_request(), "gis_dtm_patio", (mask,), (perimeter,)),
            (Use("gis_fea_marcas", "marks_layer"), Use("gis_dtm_patio", "surface"), mask, perimeter))
        self.assertEqual(provenance.stockpile_inputs(stockpile_request(), "gis_dtm_patio"),
                         (Use("gis_fea_marcas", "marks_layer"), Use("gis_dtm_patio", "surface")))
        removal = model.RemovalRequest(name="R", stockpile="STK-001#m07", start="entity:PLT-001")
        self.assertEqual(
            provenance.removal_inputs(removal, "des_psf_p1", ("des_stk_patio", "des_stb_patio_cobre"), (mask,),
                                      ("des_stp_patio", "des_stp_patio")),
            (Use("des_psf_p1", "surface"), Use("des_stk_patio", "removed_stockpile"),
             Use("des_stb_patio_cobre", "removed_stockpile"), mask, Use("des_stp_patio", "supported_on")))
        buttress = model.ButtressRequest(
            name="B", fields=model.ButtressFields(layer="gis_fea_zonas"), feature="Z", start="gis_dtm_patio",
            profile="P")
        self.assertEqual(provenance.buttress_inputs(buttress, "gis_dtm_patio", (mask,), ("des_psf_p1",)),
                         (Use("gis_fea_zonas", "entity_layer"), Use("gis_dtm_patio", "surface"), mask,
                          Use("des_psf_p1", "supported_on")))
        body = model.BodyRequest(name="C", layer="gis_fea_huellas", feature="Cuerpo 1", data_layer="gis_fea_espesores",
                                 data_field="espesor", data_from="field", surface="gis_dtm_patio", sense="under_roof")
        self.assertEqual(provenance.body_inputs(body, "gis_dtm_patio", (mask,)),
                         (Use("gis_fea_huellas", "entity_layer"), Use("gis_fea_espesores", "body_data"),
                          Use("gis_dtm_patio", "surface"), mask))
        for build, args in ((provenance.stockpile_inputs, (stockpile_request(), "")),
                            (provenance.removal_inputs, (removal, "", ())),
                            (provenance.buttress_inputs, (buttress, " ")),
                            (provenance.body_inputs, (body, ""))):
            with self.subTest(build=build.__name__), self.assertRaises(ValueError):
                build(*args)

    def test_what_each_type_reads(self) -> None:
        """RF-016-02, 11, 17, 20 (plan 016 §5.2.2; D-17): los parámetros que lee cada tipo —los que cambian su
        resultado, no su nombre ni lo que declara— con **el umbral de la huella de la 011 y el espesor mínimo de la 012
        por su clave**; la retirada y el contrafuerte, además, los comunes de las entidades que miden un borde (la
        tolerancia de cara, el umbral de magnitud y el salto creado); el contrafuerte, los cinco valores de su
        perfil. Cambiar uno deja obsoleta la operación con su causa."""
        key = params.entity_key
        stock = provenance.stockpile_params("STK-001", stockpile_request())
        self.assertEqual(stock[:3], (key("STK-001", "layer"), key("STK-001", "surface"), key("STK-001", "candidates")))
        for last in ("margin_m", "crown_inner_m", "crown_outer_m", "crown_slope_deg", "crown_flat_min_m2",
                     "max_residual_m", "fit_rounds", "turns", "tilt_max_deg", "support_quantile", "open_diameter_m",
                     "min_height_m", "min_area_m2", "max_area_m2"):
            self.assertIn(key("STK-001", last), stock)
        self.assertEqual(stock[-1], params.ANTHROPIC_PRESENCE)
        for last in ("name", "protect", "guard_m", "reason", "discarded", "decisions"):
            self.assertNotIn(key("STK-001", last), stock)
        self.assertIn(key("STK-001", "decisions"),
                      provenance.stockpile_params("STK-001", stockpile_request(decisions="c03: convertido")))
        removal = model.RemovalRequest(name="R", stockpile="STK-001#m07", start="gis_dtm_patio")
        found = provenance.removal_params("RMV-001", removal)
        self.assertEqual(found, (key("RMV-001", "stockpile"), key("RMV-001", "start"),
                                 key("RMV-001", "transition_deg"), key("RMV-001", "mesh_factor"),
                                 key("RMV-001", "metric"), *provenance.PLATFORM_COMMON_PARAMS))
        self.assertIn(key("RMV-001", "support"),
                      provenance.removal_params("RMV-001", dataclasses.replace(removal, support="gis_dtm_otro")))
        self.assertIn(key("RMV-001", "supports"), provenance.removal_params("RMV-001", removal, supports=True))
        buttress = model.ButtressRequest(
            name="B", fields=model.ButtressFields(layer="gis_fea_zonas"), feature="Z", start="gis_dtm_patio",
            profile="expl_10_60_6", reach_m=40.0)
        found = provenance.buttress_params("BTR-001", buttress)
        self.assertEqual(found[:7], tuple(key("BTR-001", last) for last in (
            "layer", "feature", "start", "profile", "crown_m", "metric", "reach_m")))
        self.assertEqual(found[7:12], provenance.profile_params(["expl_10_60_6"]))
        self.assertTrue(all(item.startswith("des.bench.expl_10_60_6.") for item in found[7:12]))
        self.assertEqual(found[12:], provenance.PLATFORM_COMMON_PARAMS)
        self.assertNotIn(key("BTR-001", "reach_m"),
                         provenance.buttress_params("BTR-001", dataclasses.replace(buttress, reach_m=None)))
        body = model.BodyRequest(name="C", layer="gis_fea_huellas", feature="Cuerpo 1", data_layer="gis_fea_espesores",
                                 data_field="espesor", data_from="field", surface="gis_dtm_patio", sense="on_base",
                                 start="gis_dtm_patio")
        found = provenance.body_params("BDY-001", body)
        self.assertEqual(found, tuple(key("BDY-001", last) for last in (
            "layer", "feature", "data_layer", "data_field", "data_from", "surface", "sense", "start",
            "max_distance_m", "zero_at_edge")) + (params.VERIFY_MIN_THICKNESS,))
        under = dataclasses.replace(body, sense="under_roof", start=None)
        self.assertNotIn(key("BDY-001", "start"), provenance.body_params("BDY-001", under))
        for build, args in ((provenance.stockpile_params, ("PLT-001", stockpile_request())),
                            (provenance.removal_params, ("stk_001", removal)),
                            (provenance.buttress_params, ("BTR-1", buttress))):
            with self.subTest(build=build.__name__), self.assertRaises(ValueError):
                build(*args)


class FiguresTest(unittest.TestCase):
    def test_the_figures_of_each_type(self) -> None:
        """RF-016-02, 09, 13, 17, 19, 20, 21 (plan 016 §5.2.3; ADR-0025; RF-008-30): cada cifra con su clave y su
        unidad del catálogo, en el orden del plan; las de un acopio llevan el ámbito del acopio y su material; ninguna
        es negativa ni NaN."""
        self.assertEqual({figure.key: figure.unit for figure in provenance.STOCKPILE_FIGURES},
                         FIGURES["des.stockpile_detect"])
        self.assertEqual({figure.key: figure.unit for figure in provenance.REMOVAL_FIGURES},
                         FIGURES["des.stockpile_removal"])
        self.assertEqual({figure.key: figure.unit for figure in provenance.BUTTRESS_FIGURES},
                         FIGURES["des.buttress"])
        self.assertEqual({figure.key: figure.unit for figure in provenance.BODY_FIGURES}, FIGURES["des.body"])
        self.assertEqual(provenance.SUPPORTED_FIGURES, (*provenance.STOCKPILE_FIGURES, *provenance.REMOVAL_FIGURES,
                                                        *provenance.BUTTRESS_FIGURES, *provenance.BODY_FIGURES))
        self.assertEqual(len(provenance.SUPPORTED_FIGURES), 22)
        for figure in provenance.SUPPORTED_FIGURES:
            self.assertFalse(figure.allow_negative, figure.key)
            self.assertIsInstance(figure, contract.FigureDef)
        keys = [figure.key for figure in (*provenance.FIGURES, *provenance.QUARRY_FIGURES,
                                          *provenance.ENTITY_FIGURES, *provenance.SUPPORTED_FIGURES)]
        self.assertEqual(len(keys), len(set(keys)), "una cifra declarada dos veces")

    def test_the_scope_of_a_stockpile_figure(self) -> None:
        """RF-016-02, 14 (plan 016 §2.1, ADR-0031 §4; ``docs/trampas.md`` §6): el ámbito de una cifra de un acopio es
        el de las entidades (el nombre de la operación y el código de la detección) más **la clave del acopio**
        (``stockpile``) y, si lo tiene, **su material**; sin la clave, las de dos acopios se pisarían (la vigente de
        una clave es la última de cada ámbito)."""
        self.assertEqual(provenance.stockpile_figure_scope("Patio", "STK-001", "m07"),
                         {"name": "patio", "entity": "STK-001", "stockpile": "m07"})
        self.assertEqual(provenance.stockpile_figure_scope("Patio", "STK-001", "m07", "Cobre"),
                         {"name": "patio", "entity": "STK-001", "stockpile": "m07", "material": "Cobre"})
        self.assertEqual(provenance.entity_figure_scope("Patio", "STK-001"),
                         {"name": "patio", "entity": "STK-001"})
        self.assertEqual(provenance.STOCKPILE_SCOPE_KEY, "stockpile")
        self.assertEqual(provenance.MATERIAL_SCOPE_KEY, "material")
        for bad in ("", "  "):
            with self.subTest(key=bad), self.assertRaises(ValueError):
                provenance.stockpile_figure_scope("Patio", "STK-001", bad)
        with self.assertRaises(ValueError):
            provenance.stockpile_figure_scope("Patio", "stk_001", "m07")

    def test_the_figures_of_a_detection(self) -> None:
        """RF-016-02, 08 (CE-016-01): ``des.stk_count`` y ``des.stk_candidates`` (si se pidieron los candidatos) por
        detección y, por acopio y material, su área, su volumen, su espesor máximo y la inclinación de su plano (si
        tiene plano: con una base propia no), cada una con su ámbito."""
        found = provenance.stockpile_figures(
            "Patio", "STK-001", count=2, candidates=8,
            stockpiles=[provenance.StockpileFigures("m01", "Cobre", 4000.0, 20000.5, 6.5, 3.0),
                        provenance.StockpileFigures("m02", None, 289.0, 410.25, 3.0, None)])
        keys = [(item.key, tuple(item.scope.get(name) for name in ("stockpile", "material"))) for item in found]
        self.assertEqual(keys, [
            ("des.stk_count", (None, None)), ("des.stk_candidates", (None, None)),
            ("des.stk_area_m2", ("m01", "Cobre")), ("des.stk_volume_m3", ("m01", "Cobre")),
            ("des.stk_thickness_max_m", ("m01", "Cobre")), ("des.stk_plane_tilt_deg", ("m01", "Cobre")),
            ("des.stk_area_m2", ("m02", None)), ("des.stk_volume_m3", ("m02", None)),
            ("des.stk_thickness_max_m", ("m02", None))])
        self.assertEqual([item.value for item in found[:4]], [2.0, 8.0, 4000.0, 20000.5])
        self.assertTrue(all(isinstance(item, figures_mod.FigureSpec) for item in found))
        self.assertEqual(found[0].scope, {"name": "patio", "entity": "STK-001"})
        self.assertEqual(found[2].unit, "m2")
        without = provenance.stockpile_figures("Patio", "STK-001", count=0, candidates=None, stockpiles=[])
        self.assertEqual([item.key for item in without], ["des.stk_count"])
        for count, candidates in ((-1, None), (1.5, None), (1, -2), (True, None)):
            with self.subTest(count=count, candidates=candidates), self.assertRaises((ValueError, TypeError)):
                provenance.stockpile_figures("Patio", "STK-001", count=count, candidates=candidates, stockpiles=[])
        for bad in (-1.0, math.nan, math.inf):
            with self.subTest(volume=bad), self.assertRaises(ValueError):
                provenance.stockpile_figures("Patio", "STK-001", count=1, candidates=None,
                                             stockpiles=[provenance.StockpileFigures("m01", None, 1.0, bad, 1.0, 1.0)])

    def test_the_figures_of_a_removal_a_buttress_and_a_body(self) -> None:
        """RF-016-13, 17, 19, 21 (plan 016 §5.2.3): las cifras de cada tipo con el ámbito de la entidad, en el orden
        del plan, todas dadas (``None`` la que no existe, como la pared sin pared) y ninguna de más."""
        removal = {key: 1.5 for key in FIGURES["des.stockpile_removal"]}
        found = provenance.removal_figures("Retirada", "RMV-001", {**removal, "des.rmv_wall_max_m": None})
        self.assertEqual([item.key for item in found], list(FIGURES["des.stockpile_removal"])[:-1])
        self.assertEqual(found[0].scope, {"name": "retirada", "entity": "RMV-001"})
        self.assertEqual([item.unit for item in provenance.removal_figures("R", "RMV-001", removal)],
                         list(FIGURES["des.stockpile_removal"].values()))
        buttress = {key: 2.0 for key in FIGURES["des.buttress"]}
        self.assertEqual([item.key for item in provenance.buttress_figures("B", "BTR-001", buttress)],
                         list(FIGURES["des.buttress"]))
        body = {key: 3.0 for key in FIGURES["des.body"]}
        found = provenance.body_figures("C", "BDY-001", {**body, "des.bdy_ignored": 4})
        self.assertEqual([item.key for item in found], list(FIGURES["des.body"]))
        self.assertEqual(found[-1].value, 4.0)
        with self.assertRaises(ValueError):  # una de más
            provenance.removal_figures("R", "RMV-001", {**removal, "des.rmv_extra_m3": 1.0})
        with self.assertRaises(ValueError):  # una de menos
            provenance.buttress_figures("B", "BTR-001", {"des.btr_volume_m3": 1.0})
        with self.assertRaises(ValueError):  # negativa
            provenance.body_figures("C", "BDY-001", {**body, "des.bdy_far_m2": -1.0})
        with self.assertRaises(ValueError):  # un recuento que no es entero
            provenance.body_figures("C", "BDY-001", {**body, "des.bdy_ignored": 2.5})


class ClosedListsTest(unittest.TestCase):
    """Las listas cerradas por tipo de operación del lado del dominio (plan 016 §2.1): cada tipo nuevo está en
    todas, o la prueba lo nombra. Sin comportamiento todavía: lo que repite, lo que reproduce y lo que calcula lo
    ponen las tareas que crean cada operación (T14, T20, T25 y T27)."""

    def test_recomputed_lists_the_four_types(self) -> None:
        """RF-008-26, RF-016-02: ``RECOMPUTED`` (lo que repite «Recalcular lo obsoleto») lleva los cuatro tipos
        después de los de la 015, sin cambiar lo que ya llevaba."""
        for op_type in TYPES.values():
            self.assertIn(op_type, store.RECOMPUTED)
        self.assertEqual(store.RECOMPUTED[:len(store.RECOMPUTED) - 4][-3:],
                         (provenance.PLATFORM, provenance.DECLARE_CONSTRAINTS, provenance.ENTITY_LAYER))
        self.assertEqual(len(set(store.RECOMPUTED)), len(store.RECOMPUTED))

    def test_recompute_run_has_a_branch_for_each_type_and_none_falls_to_another_design(self) -> None:
        """RF-008-26: ``recompute_run`` repite cada tipo de ``RECOMPUTED`` por su rama y **ninguno cae en la última**
        (que repite un escalonado): un tipo sin cálculo todavía dice qué tarea lo hace (``NotImplementedError``), no
        repite otra operación."""
        for op_type in TYPES.values():
            request = recompute_mod.RecomputeRequest(object(), "uid", op_type, {}, (), ())
            with self.subTest(op_type=op_type), self.assertRaises(NotImplementedError) as caught:
                store.recompute_run(request)
            self.assertIn(op_type, str(caught.exception))
        other = recompute_mod.RecomputeRequest(object(), "uid", "des.no_such", {}, (), ())
        with self.assertRaises(ValueError):
            store.recompute_run(other)
        released = (provenance.ReleasedSupport("PLT-001", "motivo", "Samuel", "2026-11-18"),)
        detect = recompute_mod.RecomputeRequest(object(), "uid", provenance.STOCKPILE_DETECT, {}, (), ())
        with self.assertRaises(ValueError):  # la detección no deja una superficie que se apoye en una entidad
            store.recompute_run(detect, released=released)
        removal = recompute_mod.RecomputeRequest(object(), "uid", provenance.STOCKPILE_REMOVAL, {}, (), ())
        with self.assertRaises(NotImplementedError):  # la retirada sí: lo que suelta lo hará su tarea
            store.recompute_run(removal, released=released)

    def test_the_reproduce_functions_exist_for_each_type(self) -> None:
        """RF-009-11: ``design.reproduce`` tiene la función de reproducir de cada tipo (la de ``bl`` la importa al
        usarla); sin comportamiento todavía: ``NotImplementedError`` con el tipo; lo que no es una petición,
        ``TypeError``; una de otro tipo, ``ValueError`` (errores del programa)."""
        for op_type, name in (("des.stockpile_detect", "reproduce_stockpile_detect"),
                              ("des.stockpile_removal", "reproduce_stockpile_removal"),
                              ("des.buttress", "reproduce_buttress"), ("des.body", "reproduce_body")):
            function = getattr(reproduce_mod, name)
            request = versions_reproduce.ReproduceRequest(op_type, {}, (), {}, ".", None)
            with self.subTest(op_type=op_type):
                with self.assertRaises(NotImplementedError) as caught:
                    function(request)
                self.assertIn(op_type, str(caught.exception))
                with self.assertRaises(TypeError):
                    function("petición")
                with self.assertRaises(ValueError):
                    function(versions_reproduce.ReproduceRequest("des.quarry", {}, (), {}, ".", None))


if __name__ == "__main__":
    unittest.main()

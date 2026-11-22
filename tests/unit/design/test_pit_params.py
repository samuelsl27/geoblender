# SPDX-License-Identifier: GPL-3.0-or-later
"""Los parámetros, las operaciones, los papeles, las cifras y los mensajes de la corta por bancos (spec 018, T03; HU-018-1 y 3;
RF-018-01, 03, 06, 07, 10, 11, 13, 15; plan 018 §5.2.2 y §5.2.3; ADR-0027, ADR-0029 y ADR-0031).

La corta (``pit``, ``PIT-001``: con cadena, sin ``protect`` ni ``guard_m``) tiene su familia ``des.pit.{e}.<valor>``; el perfil, la
roseta y el número de bancos por berma, además **por sector** (``des.pit.{e}.profile.{s}``: ADR-0029); la roseta de taludes
(``des.rose.{r}.{i}.<valor>``) y la definición de rampa (``des.pitramp.{q}.<valor>``) son familias **por código** del dato del proyecto.
Sin valor por defecto de ninguna cifra minera (D-8, D-14, D-15, P-5, D-19): los únicos valores por defecto son ``n_berm`` (1), ``corner``
(``round``) y ``discarded`` (falso).
"""

from __future__ import annotations

import unittest

from tests.support.package import import_geoblender

params = import_geoblender("design.params")
provenance = import_geoblender("design.provenance")
messages = import_geoblender("design.messages")
entity_store = import_geoblender("design.entity_store")
core_params = import_geoblender("core.params")

DEFAULTS = {"n_berm": 1, "corner": "round", "discarded": False}
LAYER = "Fondos"


def check(param: str, value: object, **options: object) -> object:
    return params.check_entity_param("Corta", "PIT-001", param, value, layer=LAYER, **options)  # type: ignore[arg-type]


class PitValuesTest(unittest.TestCase):
    """RF-018-01, 03, 06, 07, 10, 11, 13, 15: los valores de la corta, sus rangos y lo que no tiene valor por defecto."""

    def test_the_values_are_the_ones_of_the_plan_in_order(self) -> None:
        """Plan 018 §5.2.2: los comunes, el origen, los perfiles, la roseta, las rampas, los criterios de parada y el desfase; sin
        ``protect`` ni ``guard_m`` (la corta no declara: D-9)."""
        self.assertEqual([item.value for item in params.PitParam], [
            "name", "mode", "layer", "fixed_layer", "noramp_layer", "start", "support", "supports", "profile", "rose",
            "n_berm", "ramps", "top_level_m", "bottom_level_m", "max_benches", "min_floor_width_m", "corner", "arc_tol_m",
            "simplify_m", "close_radius_m", "az_window_m", "discarded", "reason"])
        self.assertEqual(len(params.PIT_FAMILIES), 23)
        self.assertEqual(params.PIT_ENTITY.names, tuple(item.value for item in params.PitParam))
        for name in ("protect", "guard_m"):
            self.assertNotIn(name, params.PIT_ENTITY.names)

    def test_only_three_values_have_a_default(self) -> None:
        """RF-018-04, 08, 10, 11, 13 (D-8, D-14, D-15, P-5): sin valor por defecto de ``top_level_m``, ``bottom_level_m``,
        ``max_benches``, ``min_floor_width_m`` ni de las tolerancias; ``n_berm`` = 1 y ``corner`` = ``round`` (ADOPTADO «sin
        confirmar») y ``discarded`` falso."""
        found = {item.pattern.rsplit(".", 1)[1]: item.template for item in params.PIT_FAMILIES}
        self.assertEqual({name: t.default for name, t in found.items() if t.default is not None}, DEFAULTS)
        for name in ("top_level_m", "bottom_level_m", "max_benches", "min_floor_width_m", "arc_tol_m", "simplify_m",
                     "close_radius_m", "az_window_m"):
            self.assertIsNone(found[name].default, name)
        for name in ("arc_tol_m", "simplify_m", "close_radius_m", "az_window_m"):
            self.assertEqual(found[name].kind, "HIPÓTESIS", name)
        for name in ("n_berm", "corner"):
            self.assertEqual(found[name].kind, "ADOPTADO", name)
        self.assertEqual(params.PIT_ENTITY.template("corner").choices, ("round", "miter"))

    def test_the_levels_the_count_and_the_width_are_required_by_the_criteria_not_by_the_type(self) -> None:
        """RF-018-11, 13, 14: los criterios de parada y la cota de los extremos son opcionales (basta uno, lo comprueba el cálculo); la
        tolerancia de arco y la de simplificación, obligatorias; sin valor se rechaza nombrando la clave."""
        for name in ("top_level_m", "bottom_level_m", "max_benches", "min_floor_width_m", "close_radius_m", "az_window_m"):
            self.assertIn(name, params.PIT_ENTITY.optional, name)
        for name in ("name", "mode", "layer", "arc_tol_m", "simplify_m", "corner", "n_berm"):
            self.assertNotIn(name, params.PIT_ENTITY.optional, name)
        for name in ("arc_tol_m", "simplify_m"):
            with self.assertRaises(messages.DesignError) as caught:
                check(name, None)
            self.assertEqual(caught.exception.code, "des.entity_param_missing")
            self.assertEqual(caught.exception.field, f"des.pit.pit_001.{name}")
        self.assertIsNone(check("max_benches", None))

    def test_the_ranges(self) -> None:
        """RF-018-08, 10, 11, 13: ``n_berm`` y ``max_benches`` enteros ≥ 1; las tolerancias, la ventana y el ancho mínimo > 0; el
        cierre ≥ 0; las cotas sin tope; un decimal fuera de rango se rechaza con la clave y el valor."""
        self.assertEqual(check("n_berm", 2), 2)
        self.assertEqual(check("max_benches", 40), 40)
        self.assertEqual(check("min_floor_width_m", 25), 25.0)
        self.assertEqual(check("close_radius_m", 0), 0.0)
        self.assertEqual(check("top_level_m", -12.5), -12.5)
        self.assertEqual(check("bottom_level_m", 1234.5), 1234.5)
        for param, value in (("n_berm", 0), ("max_benches", 0), ("min_floor_width_m", 0), ("min_floor_width_m", -1.0),
                             ("arc_tol_m", 0.0), ("simplify_m", -0.05), ("az_window_m", 0.0), ("close_radius_m", -0.1),
                             ("arc_tol_m", float("nan")), ("top_level_m", float("inf"))):
            with self.subTest(param=param, value=value), self.assertRaises(messages.DesignError) as caught:
                check(param, value)
            self.assertEqual(caught.exception.code, "des.entity_param_range")
            self.assertEqual(caught.exception.field, f"des.pit.pit_001.{param}")
        for param, value in (("n_berm", 1.5), ("max_benches", 40.0), ("n_berm", True)):
            with self.subTest(param=param, value=value), self.assertRaises(TypeError):
                check(param, value)
        with self.assertRaises(messages.DesignError) as caught:
            check("corner", "bevel")
        self.assertEqual(caught.exception.code, "des.entity_param_choice")

    def test_the_sector_families_follow_adr_0029(self) -> None:
        """RF-018-06, 07, 08 (ADR-0029): el perfil, la roseta y el número de bancos por berma, por sector: ``des.pit.{e}.profile.{s}``
        con el código del sector; el perímetro como sector único es ``perimeter__``. Sin valor por defecto (sin sector, el de la
        corta)."""
        self.assertEqual([item.pattern for item in params.PIT_SECTOR_FAMILIES],
                         ["des.pit.{e}.profile.{s}", "des.pit.{e}.rose.{s}", "des.pit.{e}.n_berm.{s}"])
        key = params.pit_sector_key("PIT-001", "profile", "talud_norte")
        self.assertEqual(key, "des.pit.pit_001.profile.talud_norte")
        self.assertEqual(params.pit_sector_key("PIT-001", "n_berm", "perimeter__"), "des.pit.pit_001.n_berm.perimeter__")
        for family in params.PIT_SECTOR_FAMILIES:
            self.assertIsNone(family.template.default)
        self.assertEqual(params.PIT_SECTOR_FAMILIES[2].template.value_type, "int")
        self.assertEqual(params.PIT_SECTOR_FAMILIES[2].template.minimum, 1)
        for family in params.PIT_SECTOR_FAMILIES:
            self.assertIsNotNone(family.match(family.template.key.replace(".e.", ".pit_001.").replace(".s", ".norte")))
        for bad in (("PIT-001", "mode", "norte"), ("PLT-001", "profile", "norte"), ("PIT-001", "profile", "Norte"),
                    ("PIT-001", "profile", "")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                params.pit_sector_key(*bad)
        self.assertEqual(params.parse_entity_key(key), None)  # no es el valor de una entidad: la familia es de otra forma


class RoseTest(unittest.TestCase):
    """RF-018-07: la roseta de taludes, una familia por rango (``des.rose.{r}.{i}.<valor>``); la forma exacta de sus rangos, de T04."""

    def test_the_families_and_the_keys(self) -> None:
        self.assertEqual([item.pattern for item in params.ROSE_FAMILIES], [
            "des.rose.{r}.{i}.from_deg", "des.rose.{r}.{i}.to_deg", "des.rose.{r}.{i}.face_deg", "des.rose.{r}.{i}.berm_m"])
        for family in params.ROSE_FAMILIES:
            self.assertIsNone(family.template.default)
            self.assertEqual(family.template.scope, "version")
        self.assertEqual(params.rose_key("rosa_1", "r1", "face_deg"), "des.rose.rosa_1.r1.face_deg")
        for bad in (("Rosa", "r1", "face_deg"), ("rosa_1", "1", "face_deg"), ("rosa_1", "r1", "mode")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                params.rose_key(*bad)

    def test_the_ranges_and_the_missing_values(self) -> None:
        """RF-018-07: azimut en [0, 360]; la cara en (0, 90) sin extremos; la berma ≥ 0; un valor sin valor o fuera de rango se rechaza
        con el rango y el valor, nombrando la roseta."""
        for param, good in (("from_deg", 0), ("to_deg", 360), ("face_deg", 60), ("berm_m", 0)):
            self.assertEqual(params.check_rose_value("Roseta", "rosa_1", "r1", param, good), float(good))
        for param, value in (("from_deg", -1), ("to_deg", 360.5), ("face_deg", 0), ("face_deg", 90), ("berm_m", -0.1),
                             ("berm_m", float("nan"))):
            with self.subTest(param=param, value=value), self.assertRaises(messages.DesignError) as caught:
                params.check_rose_value("Roseta", "rosa_1", "r1", param, value)
            self.assertEqual(caught.exception.code, "des.pit_rose_value_range")
            self.assertEqual(caught.exception.field, f"des.rose.rosa_1.r1.{param}")
        with self.assertRaises(messages.DesignError) as caught:
            params.check_rose_value("Roseta", "rosa_1", "r2", "face_deg", None)
        self.assertEqual((caught.exception.code, caught.exception.field), ("des.pit_rose_value_missing", "des.rose.rosa_1.r2.face_deg"))
        with self.assertRaises(TypeError):
            params.check_rose_value("Roseta", "rosa_1", "r1", "face_deg", "60")


class RampDefinitionTest(unittest.TestCase):
    """RF-018-15: la definición de rampa, una familia por código (``des.pitramp.{q}.<valor>``), sin valor por defecto."""

    def test_the_families_and_the_keys(self) -> None:
        self.assertEqual([item.value for item in params.PitRampParam], [
            "type", "sense", "start", "gradient_pct", "road_profile", "transition_m", "turn_radius_m", "min_platform_m"])
        self.assertEqual(len(params.PITRAMP_FAMILIES), 8)
        for family in params.PITRAMP_FAMILIES:
            self.assertTrue(family.pattern.startswith("des.pitramp.{q}."))
            self.assertIsNone(family.template.default)
        found = {item.pattern.rsplit(".", 1)[1]: item.template for item in params.PITRAMP_FAMILIES}
        self.assertEqual(found["turn_radius_m"].kind, "HIPÓTESIS")
        self.assertEqual(found["min_platform_m"].kind, "HIPÓTESIS")
        self.assertEqual(found["gradient_pct"].kind, "ADOPTADO")
        self.assertEqual(found["type"].choices, ("spiral", "zigzag"))
        self.assertEqual(found["sense"].choices, ("cw", "ccw"))
        self.assertEqual(params.pitramp_key("rampa_1", "gradient_pct"), "des.pitramp.rampa_1.gradient_pct")
        for bad in (("Rampa", "type"), ("rampa_1", "mode")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                params.pitramp_key(*bad)

    def test_the_ranges_and_the_values_that_only_the_zigzag_needs(self) -> None:
        """RF-018-15: ``0 < g ≤ 100``; ``transition ≥ 0``; el radio de giro y la plataforma > 0 (solo el zig-zag los pide: con
        ``required=False`` pasan sin valor); el tipo y el sentido, de su lista cerrada."""
        check_ramp = params.check_pitramp_value
        self.assertEqual(check_ramp("Rampa", "rampa_1", "gradient_pct", 10), 10.0)
        self.assertEqual(check_ramp("Rampa", "rampa_1", "transition_m", 0), 0.0)
        self.assertEqual(check_ramp("Rampa", "rampa_1", "type", " zigzag "), "zigzag")
        self.assertIsNone(check_ramp("Rampa", "rampa_1", "turn_radius_m", None, required=False))
        for param, value in (("gradient_pct", 0), ("gradient_pct", 100.5), ("transition_m", -1), ("turn_radius_m", 0),
                             ("min_platform_m", -5), ("type", "helix"), ("sense", "left")):
            with self.subTest(param=param, value=value), self.assertRaises(messages.DesignError) as caught:
                check_ramp("Rampa", "rampa_1", param, value)
            self.assertEqual(caught.exception.code, "des.pit_ramp_value_range")
            self.assertEqual(caught.exception.field, f"des.pitramp.rampa_1.{param}")
        with self.assertRaises(messages.DesignError) as caught:
            check_ramp("Rampa", "rampa_1", "gradient_pct", None)
        self.assertEqual(caught.exception.code, "des.pit_ramp_value_missing")


class PitRegistrationTest(unittest.TestCase):
    """Las familias de la 018 se declaran junto a las demás de ``des`` y no chocan con ninguna."""

    def test_every_pattern_is_unique_and_declared_in_the_module_des(self) -> None:
        groups = (params.PIT_FAMILIES, params.PIT_SECTOR_FAMILIES, params.ROSE_FAMILIES, params.PITRAMP_FAMILIES)
        found = [family.pattern for group in groups for family in group]
        self.assertEqual(len(found), len(set(found)))
        self.assertEqual((len(found), [len(group) for group in groups]), (38, [23, 3, 4, 8]))
        for group in groups:
            for family in group:
                self.assertEqual(family.module, "des")
                self.assertTrue(family.template.label_msgid)
        other = {family.pattern for family in (*params.FAMILIES, *params.ENTITY_FAMILIES, *params.SUPPORTED_FAMILIES,
                                                *params.ROAD_FAMILIES, *params.ACCESS_FAMILIES, *params.ROAD_PROFILE_FAMILIES)}
        self.assertFalse(other & set(found))
        # Ninguna casa con la clave de otra: la clave concreta de una familia solo es de ella.
        sample = {"des.pit.pit_001.n_berm": "des.pit.{e}.n_berm", "des.pit.pit_001.n_berm.norte": "des.pit.{e}.n_berm.{s}",
                  "des.rose.rosa_1.r1.face_deg": "des.rose.{r}.{i}.face_deg", "des.pitramp.rampa_1.type": "des.pitramp.{q}.type"}
        for key, pattern in sample.items():
            matching = [family.pattern for group in groups for family in group if family.match(key) is not None]
            self.assertEqual(matching, [pattern], key)


class PitFiguresTest(unittest.TestCase):
    """RF-018-29, 31: las cifras CALCULADO de la corta (plan 018 §5.2.3), con ``gradient`` y no «grade» (glosario §14)."""

    def test_the_figures_and_their_units(self) -> None:
        keys = [figure.key for figure in provenance.PIT_FIGURES]
        self.assertEqual(keys, [
            "des.pit_benches", "des.pit_z_bottom_m", "des.pit_z_top_m", "des.pit_len_foot_m", "des.pit_len_crest_m",
            "des.pit_area_berm_m2", "des.pit_area_floor_m2", "des.pit_cut_m3", "des.pit_area_m2", "des.pit_sky_parts",
            "des.pit_sky_len_m", "des.pit_sky_area_m2", "des.pit_sky_z_min_m", "des.pit_sky_z_max_m",
            "des.pit_sky_dist_legal_m", "des.pit_sky_dist_perimeter_m", "des.pit_ramp_len_m", "des.pit_ramp_gradient_mean_pct",
            "des.pit_ramp_gradient_max_pct", "des.pit_ramp_band_m3", "des.pit_findings"])
        units = {figure.key: figure.unit for figure in provenance.PIT_FIGURES}
        self.assertEqual((units["des.pit_benches"], units["des.pit_cut_m3"], units["des.pit_area_floor_m2"],
                          units["des.pit_ramp_gradient_max_pct"], units["des.pit_sky_len_m"]), ("-", "m3", "m2", "%", "m"))
        negative = {figure.key for figure in provenance.PIT_FIGURES if figure.allow_negative}
        self.assertEqual(negative, {"des.pit_z_bottom_m", "des.pit_z_top_m", "des.pit_sky_z_min_m", "des.pit_sky_z_max_m"})
        for figure in provenance.PIT_FIGURES:
            self.assertNotIn("grade", figure.key.replace("gradient", ""))

    def test_the_builder_gives_the_scope_of_the_entity_and_rejects_what_is_not_a_figure(self) -> None:
        values: dict[str, float | None] = {figure.key: 1.0 for figure in provenance.PIT_FIGURES}
        values["des.pit_benches"] = 12
        values["des.pit_z_bottom_m"] = -5.0
        values["des.pit_sky_dist_legal_m"] = None  # sin límite legal no hay distancia
        made = provenance.pit_figures("Corta 1", "PIT-001", values)
        self.assertEqual(len(made), len(provenance.PIT_FIGURES) - 1)
        self.assertEqual(made[0].key, "des.pit_benches")
        self.assertEqual(made[0].scope, provenance.entity_figure_scope("Corta 1", "PIT-001"))
        self.assertEqual({item.key: item.value for item in made}["des.pit_z_bottom_m"], -5.0)
        with self.assertRaises(ValueError):
            provenance.pit_figures("Corta 1", "PIT-001", {**values, "des.pit_otra": 1.0})
        with self.assertRaises(ValueError):
            provenance.pit_figures("Corta 1", "PIT-001", {**values, "des.pit_cut_m3": -1.0})
        with self.assertRaises(ValueError):
            provenance.pit_figures("Corta 1", "PLT-001", values)
        short = dict(values)
        del short["des.pit_area_m2"]
        with self.assertRaises(ValueError):
            provenance.pit_figures("Corta 1", "PIT-001", short)

    def test_the_layer_has_its_main_figures(self) -> None:
        """RF-015-27: la capa de entidades da el área y el corte de la corta (``des.pit_area_m2`` y ``des.pit_cut_m3``)."""
        self.assertEqual(entity_store.LAYER_FIGURES["pit"], (("area_m2", "des.pit_area_m2"), ("cut_m3", "des.pit_cut_m3")))


class PitOperationsTest(unittest.TestCase):
    """RF-018-01, 03, 22, 29: los tipos de operación, los papeles y las familias de datos de la corta."""

    def test_the_operation_types(self) -> None:
        names = [declared.op_type for declared in provenance.PIT_OPERATION_TYPES]
        self.assertEqual(names, ["des.pit", "des.pit_expand", "des.pit_layer"])
        pit, expand, layer = provenance.PIT_OPERATION_TYPES
        self.assertEqual((provenance.PIT_EXPAND, provenance.PIT_LAYER), ("des.pit_expand", "des.pit_layer"))
        self.assertEqual(pit.outputs, (
            provenance.ENTITY_SURFACE_GRID, provenance.ENTITY_TABLE, provenance.PIT_POLYLINES_TABLE, provenance.PIT_SKYLINE_TABLE,
            provenance.PIT_RAMPS_TABLE, provenance.PIT_FINDINGS_TABLE, provenance.PIT_BENCHES_TABLE, provenance.ENTITY_REPORT_TABLE))
        self.assertEqual(pit.figures, (*provenance.PIT_FIGURES, *provenance.SUPPORT_FIGURES))
        self.assertEqual(expand.outputs, (provenance.PIT_EXPANDED_TABLE,))
        self.assertEqual({figure.key for figure in expand.figures}, {"des.pit_len_crest_m", "des.pit_len_foot_m"})
        self.assertEqual(layer.outputs, (provenance.PIT_LAYER_TABLE, provenance.PIT_SKY_LAYER_TABLE))
        self.assertEqual((pit.reproducible, expand.reproducible, layer.reproducible), (True, True, False))
        self.assertTrue(layer.drops_discarded)
        self.assertFalse(pit.drops_discarded or expand.drops_discarded)
        self.assertEqual(provenance.PIT_VERSION_TYPES, tuple(names))
        self.assertEqual(provenance.PIT_REPRODUCIBLE, ("des.pit", "des.pit_expand"))
        for declared in provenance.PIT_OPERATION_TYPES:
            self.assertIs(provenance.OPERATION_TYPES_BY_NAME[declared.op_type], declared)
            self.assertEqual(declared.scope, "version")
        self.assertEqual(provenance.ENTITY_OP_NAMES[-1], "des.pit")
        self.assertNotIn("des.pit_expand", provenance.ENTITY_OP_NAMES)  # no es una entidad: no tiene cadena ni código

    def test_the_project_operations_are_not_repeated(self) -> None:
        """RF-018-07, 15: la edición de las roseta y de las rampas es **de proyecto**, sin repetición."""
        found = {item.op_type: item for item in provenance.PIT_PROJECT_OPERATIONS}
        self.assertEqual(list(found), ["des.edit_pit_roses", "des.edit_pit_ramps"])
        self.assertEqual((provenance.EDIT_PIT_ROSES, provenance.EDIT_PIT_RAMPS), tuple(found))
        for item in found.values():
            self.assertEqual((item.scope, item.recompute, item.reproduce), ("project", None, None))

    def test_the_roles_and_the_data_families(self) -> None:
        roles = {family.code: family.role for family in provenance.PIT_DATA_FAMILIES}
        self.assertEqual(roles, {
            "pbl": "pit_polylines", "psk": "pit_skyline", "prl": "pit_ramps", "pfn": "pit_findings", "pbk": "pit_benches",
            "pxb": "pit_expanded", "pit": "pit_layer", "sky": "sky_layer"})
        self.assertEqual((provenance.PIT_POLYLINES_TABLE, provenance.PIT_SKYLINE_TABLE, provenance.PIT_RAMPS_TABLE,
                          provenance.PIT_FINDINGS_TABLE, provenance.PIT_BENCHES_TABLE, provenance.PIT_EXPANDED_TABLE,
                          provenance.PIT_LAYER_TABLE, provenance.PIT_SKY_LAYER_TABLE),
                         ("pbl", "psk", "prl", "pfn", "pbk", "pxb", "pit", "sky"))
        self.assertEqual((provenance.PIT_POLYLINES_ROLE, provenance.PIT_SKYLINE_ROLE, provenance.PIT_RAMPS_ROLE,
                          provenance.PIT_FINDINGS_ROLE, provenance.PIT_BENCHES_ROLE),
                         ("pit_polylines", "pit_skyline", "pit_ramps", "pit_findings", "pit_benches"))
        self.assertEqual([family.code for family in provenance.PIT_DATA_FAMILIES if family.qgis_editable], ["pxb"])
        self.assertEqual({family.code: family.named for family in provenance.PIT_DATA_FAMILIES if not family.named},
                         {"pit": False, "sky": False})
        for family in provenance.PIT_DATA_FAMILIES:
            self.assertIs(provenance.FAMILIES_BY_CODE[family.code], family)
        self.assertEqual(provenance.dataset_name("pbl", "Corta 1"), "des_pbl_corta_1")
        self.assertEqual(provenance.dataset_name("pit"), "des_pit")
        self.assertEqual(provenance.dataset_locator("pit", "", "V02"), "des_pit_v02")
        spec = provenance.dataset_spec("pxb", "Banco 5", "V01")
        self.assertEqual((spec.role, spec.qgis_editable), ("pit_expanded", True))

    def test_the_ramp_confirmation_is_recorded_with_who_and_when(self) -> None:
        """RF-018-19, RF-017-17: la pendiente media de una rampa por encima de pm solo se acepta con la confirmación y el motivo
        registrados; un recálculo la reutiliza si la media nueva no pasa de la confirmada más la tolerancia."""
        done = provenance.ramp_confirmation("rampa_1", 11.2, "Hay que cruzar el cauce", "Samuel", "2026-11-22T10:00:00Z")
        self.assertEqual((done.ramp, done.mean_pct, done.reason), ("rampa_1", 11.2, "Hay que cruzar el cauce"))
        self.assertTrue(done.covers(11.2, 0.0))
        self.assertTrue(done.covers(11.25, 0.05))
        self.assertFalse(done.covers(11.3, 0.05))
        self.assertEqual(provenance.ramp_confirmed({provenance.PIT_RAMP_CONFIRMED: [done.settings()]}), (done,))
        self.assertEqual(provenance.ramp_confirmed({}), ())
        for bad in (("rampa_1", 0.0, "motivo", "S", "t"), ("rampa_1", float("nan"), "motivo", "S", "t"),
                    ("rampa_1", 11.0, "  ", "S", "t"), ("rampa_1", 11.0, "motivo", "", "t"), ("Rampa", 11.0, "motivo", "S", "t")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                provenance.ramp_confirmation(*bad)
        with self.assertRaises(ValueError):
            provenance.ramp_confirmed({provenance.PIT_RAMP_CONFIRMED: [{"ramp": "rampa_1"}]})


class PitMessagesTest(unittest.TestCase):
    """RF-018-04, 06, 07, 14, 19, 20, 23, 24: los códigos ``des.pit_*``, en los dos idiomas y con los marcadores que dicen."""

    CODES = (
        "des.pit_holes", "des.pit_offset_unreliable", "des.pit_no_ramp_fit", "des.pit_rose_gap", "des.pit_rose_overlap",
        "des.pit_profiles_differ", "des.pit_nothing_to_excavate", "des.pit_too_many_benches", "des.pit_not_reaching_surface",
        "des.pit_floor_too_small", "des.pit_fixed_level", "des.pit_fixed_cross", "des.pit_ramp_mean_over",
        "des.pit_ramp_radius_below_min", "des.pit_no_search", "des.pit_rose_value_missing", "des.pit_rose_value_range",
        "des.pit_ramp_value_missing", "des.pit_ramp_value_range")

    def test_each_code_is_in_the_catalog_with_its_spanish(self) -> None:
        for code in self.CODES:
            with self.subTest(code=code):
                found = messages.lookup(code)
                self.assertEqual(found.code, code)
                self.assertTrue(found.msgid and found.es)
                self.assertNotEqual(found.msgid, found.es)
                self.assertIsNotNone(messages.render(code, language="en"))

    def test_the_rejections_name_the_field_and_the_value(self) -> None:
        text = messages.render("des.pit_ramp_value_range", profile="Rampa", field="des.pitramp.r1.gradient_pct", value=0, range="(0; 100] %")
        self.assertIn("des.pitramp.r1.gradient_pct", text)
        self.assertIn("(0; 100] %", text)
        for code in ("des.pit_rose_gap", "des.pit_rose_overlap"):
            self.assertIn("{from_deg}", messages.lookup(code).es)
        self.assertEqual(messages.lookup("des.pit_ramp_mean_over").severity, "error")
        self.assertEqual(messages.lookup("des.pit_offset_unreliable").severity, "warning")
        self.assertEqual(messages.lookup("des.pit_holes").severity, "warning")


if __name__ == "__main__":
    unittest.main()

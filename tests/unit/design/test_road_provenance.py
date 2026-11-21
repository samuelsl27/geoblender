# SPDX-License-Identifier: GPL-3.0-or-later
"""La procedencia de la pista y de la accesibilidad de la 017 (spec 017, T03; HU-017-1 a 4; RF-017-01, 02, 07, 23, 24, 27;
RNF-017-10; plan 017 §2.1, §5.1, §5.2.2, §5.2.3, §5.7 P-1, P-5 y P-8; ADR-0025, ADR-0027, ADR-0030 y ADR-0031): sus
tipos de operación (con el de la edición de los perfiles, de proyecto), las familias de datos con su nombre y su
ubicación, los papeles con que las lee la 012 sin importar ``design``, las funciones de entradas y parámetros, las
cifras con su ámbito, los dos tipos de entidad del registro (``road``, que encadena y sale en la capa de entidades con su
huella, y ``access``, sin cadena y sin huella) y las **listas cerradas** de ``design`` (``RECOMPUTED`` y la cadena de
``recompute_run``, ``OPERATION_TYPES_BY_NAME``, ``reproduce``, ``ENTITY_OP_NAMES``), que esta tarea amplía **sin
comportamiento** todavía: ninguna operación de estos tipos existe hasta que las tareas siguientes las crean.

Los ajustes y la petición de cada tipo (``road_settings``, ``road_request``…) dependen de ``RoadRequest`` y
``AccessRequest`` (T05) y de los campos de la capa del diálogo: los hacen la T17 (accesibilidad) y la T19 a T21 (pista)
junto a su preparación; ``des.road_propose`` es de la T27.
"""

from __future__ import annotations

import math
import unittest
from typing import Any

from tests.support import entity_fixtures as efx
from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.versions_fixtures import change_counter

provenance = import_geoblender("design.provenance")
params = import_geoblender("design.params")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
entity_layer = import_geoblender("design.entity_layer")
messages = import_geoblender("design.messages")
store = import_geoblender("design.store")
reproduce_mod = import_geoblender("design.reproduce")
contract = import_geoblender("core.provenance.contract")
operations = import_geoblender("core.provenance.operations")
recompute_mod = import_geoblender("core.provenance.recompute")
versions_reproduce = import_geoblender("core.versions.reproduce")
versions_model = import_geoblender("core.versions.model")
datasets = import_geoblender("core.datasets.model")
builtin = import_geoblender("core.content.builtin")
gpkg_base = import_geoblender("core.gpkg.base")
core_params = import_geoblender("core.params")
i18n = import_geoblender("core.i18n")
figures_mod = import_geoblender("core.provenance.figures")

SPANISH_LETTERS = frozenset("áéíóúüñÁÉÍÓÚÜÑ¿¡")
ROAD, ACCESS, PROPOSE = "des.road", "des.road_access", "des.road_propose"
TYPES = {"road": ROAD, "access": ACCESS, "propose": PROPOSE}
LABELS = {ROAD: "Haul road", ACCESS: "Accessibility of the haul roads", PROPOSE: "Proposal of the route of a haul road"}
COMMANDS = {ROAD: "geoblender.des_create_road", ACCESS: "geoblender.des_road_access",
            PROPOSE: "geoblender.des_propose_road"}
PROFILE_COMMAND = "geoblender.des_edit_road_profile"
OUTPUTS = {ROAD: ("psf", "epr", "rdx", "prp"), ACCESS: ("acc", "acb", "acp", "acz", "prp"), PROPOSE: ("rpl",)}
# Código → (tipo, almacén, lector, papel, extensión, editable en QGIS) de las seis familias de datos nuevas (plan 017 §5.2.3).
FAMILIES = {
    "rdx": ("table", "gpkg", "core.gpkg_layer@1", "road_axis", "", False),
    "rpl": ("vector", "gpkg", "core.gpkg_layer@1", "route_layer", "", True),
    "acc": ("raster", "rasters", "gis.geotiff@1", "road_access", ".tif", False),
    "acb": ("table", "gpkg", "core.gpkg_layer@1", "access_berms", "", False),
    "acp": ("table", "gpkg", "core.gpkg_layer@1", "access_platforms", "", False),
    "acz": ("table", "gpkg", "core.gpkg_layer@1", "access_zones", "", False),
}
# Las cifras del plan §5.2.3 por tipo: clave → (unidad, admite negativos). «grade» no aparece (glosario §14: es la ley).
ROAD_FIGURES = {
    "des.road_length_m": ("m", False), "des.road_z_start_m": ("m", True), "des.road_z_end_m": ("m", True),
    "des.road_drop_m": ("m", True), "des.road_gradient_mean_pct": ("%", False),
    "des.road_gradient_max_pct": ("%", False), "des.road_gradient_max_station_m": ("m", False),
    "des.road_radius_min_m": ("m", False), "des.road_curves": ("-", False), "des.road_width_m": ("m", False),
    "des.road_section_m": ("m", False), "des.road_area_m2": ("m2", False), "des.road_cut_m3": ("m3", False),
    "des.road_fill_m3": ("m3", False), "des.road_edge_cut_m3": ("m3", False), "des.road_edge_fill_m3": ("m3", False),
    "des.road_net_m3": ("m3", True), "des.road_wall_max_m": ("m", False), "des.road_cut_height_max_m": ("m", False),
    "des.road_fill_height_max_m": ("m", False), "des.road_avoid_m2": ("m2", False), "des.road_avoid_m3": ("m3", False),
    "des.road_avoid_weighted_m3": ("m3", False),
}
ACCESS_FIGURES = {
    "des.acc_z_min_m": ("m", True), "des.acc_z_max_m": ("m", True), "des.acc_area_m2": ("m2", False),
    "des.acc_z_min_final_m": ("m", True), "des.acc_berms_reached": ("-", False), "des.acc_berms_total": ("-", False),
    "des.acc_platforms_reached": ("-", False), "des.acc_zones_reached": ("-", False),
    "des.acc_zones_missing": ("-", False),
}
PROPOSE_FIGURES = ("des.road_length_m", "des.road_gradient_max_pct")
PROJECT_PARAMS = provenance.PLATFORM_COMMON_PARAMS


def recompute(request: Any) -> Any:  # pragma: no cover - solo para construir las definiciones
    return None


def reproduce(request: Any) -> Any:  # pragma: no cover
    return None


def all_figures(kind: dict[str, tuple[str, bool]]) -> dict[str, float | None]:
    """Un valor para cada cifra de ``kind``: 1,5, o 2 si es un recuento (unidad ``-``: un entero)."""
    return {key: 2 if unit == "-" else 1.5 for key, (unit, _negative) in kind.items()}


class OperationTypesTest(unittest.TestCase):
    def test_the_three_types(self) -> None:
        """RF-017-01, 24, 28 (plan 017 §5.2.3; ADR-0025): tres tipos de operación de la versión, del módulo ``des``,
        versión 1.0, repetibles y reproducibles con 10⁻⁹ relativo, sin grupo acoplado, cada uno con su orden del plan
        §5.3.3, sus familias de datos y sus cifras; van aparte de los de las cuatro specs anteriores, que siguen como
        estaban."""
        self.assertEqual((provenance.ROAD, provenance.ROAD_ACCESS, provenance.ROAD_PROPOSE), tuple(TYPES.values()))
        self.assertEqual([t.op_type for t in provenance.ROAD_OPERATION_TYPES], list(TYPES.values()))
        self.assertEqual(provenance.ROAD_VERSION_TYPES, tuple(TYPES.values()))
        self.assertEqual(provenance.ROAD_REPRODUCIBLE, tuple(TYPES.values()))
        self.assertEqual(provenance.OP_VERSION, "1.0")
        for declared in provenance.ROAD_OPERATION_TYPES:
            op_type = declared.op_type
            with self.subTest(op_type=op_type):
                self.assertIs(provenance.OPERATION_TYPES_BY_NAME[op_type], declared)
                self.assertEqual(declared.label_msgid, LABELS[op_type])
                self.assertEqual(declared.outputs, OUTPUTS[op_type])
                self.assertEqual(declared.commands, (COMMANDS[op_type],))
                self.assertEqual(declared.settings, ())
                self.assertTrue(declared.reproducible)
                self.assertFalse(declared.drops_discarded)
                self.assertEqual(declared.scope, "version")
                built = provenance.operation_def(op_type, recompute, reproduce)
                self.assertIsInstance(built, contract.OperationDef)
                self.assertEqual((built.op_type, built.version, built.module, built.scope, built.repeatable,
                                  built.group, built.reproduce, built.recompute),
                                 (op_type, "1.0", "des", "version", True, None, reproduce, recompute))
                self.assertEqual(built.figure_tolerance, provenance.FIGURE_TOLERANCE)
        for older in (*provenance.OPERATION_TYPES, *provenance.QUARRY_OPERATION_TYPES,
                      *provenance.ENTITY_OPERATION_TYPES, *provenance.SUPPORTED_OPERATION_TYPES):
            self.assertIs(provenance.OPERATION_TYPES_BY_NAME[older.op_type], older)
        self.assertEqual(len(provenance.OPERATION_TYPES_BY_NAME), 2 + 5 + 3 + 5 + 3)

    def test_the_figures_of_each_type_and_what_fills_on_a_road(self) -> None:
        """RF-017-23, 24, 28, RF-015-15 (ADR-0031 §4): las cifras de cada tipo son las de su tabla; la pista deja también
        ``des.supported_m3`` (lo que se le apoya: una pista es una entidad con superficie), la accesibilidad y la
        propuesta, no; la propuesta deja la longitud y la pendiente máxima de la pista (las mismas dos claves)."""
        by_type = {ROAD: (*ROAD_FIGURES, provenance.SUPPORTED_M3), ACCESS: tuple(ACCESS_FIGURES), PROPOSE: PROPOSE_FIGURES}
        for op_type, expected in by_type.items():
            with self.subTest(op_type=op_type):
                declared = provenance.OPERATION_TYPES_BY_NAME[op_type]
                self.assertEqual([item.key for item in declared.figures], list(expected))

    def test_the_edition_of_the_profiles_is_a_project_operation_without_repetition(self) -> None:
        """RF-017-07, RF-009-24 (plan 017 §5.2.3, P-2): ``des.edit_road_profiles`` es **de proyecto** y no se repite sola
        (queda «revisar a mano», como ``des.edit_bench_profiles``): sin ``recompute`` ni ``reproduce``, con su orden
        «Perfil de pista…»; lo declara ``provenance`` porque ``bl`` solo importa lo ligero y ``road_profiles`` es
        perezoso (T04 construye su mecánica sobre este nombre); no es un ``OperationType`` de los repetibles."""
        self.assertEqual(provenance.EDIT_ROAD_PROFILES, "des.edit_road_profiles")
        self.assertEqual(provenance.ROAD_PROFILE_COMMAND, PROFILE_COMMAND)
        (found,) = provenance.ROAD_PROFILE_OPERATIONS
        self.assertIsInstance(found, contract.OperationDef)
        self.assertEqual((found.op_type, found.version, found.module, found.scope, found.repeatable, found.group,
                          found.recompute, found.reproduce, found.commands, found.label_msgid),
                         ("des.edit_road_profiles", "1.0", "des", "project", False, None, None, None,
                          (PROFILE_COMMAND,), "Edition of the road profiles"))
        self.assertNotIn("des.edit_road_profiles", provenance.OPERATION_TYPES_BY_NAME)

    def test_the_functions_of_the_definitions_are_checked(self) -> None:
        """RF-008-26, RF-009-11: ``road_operation_defs`` arma las tres definiciones, en su orden, con su función de
        recálculo y de reproducción; ``ValueError`` si sobra o falta alguna."""
        functions = dict.fromkeys(TYPES.values(), recompute)
        replays = dict.fromkeys(TYPES.values(), reproduce)
        built = provenance.road_operation_defs(functions, replays)
        self.assertEqual([item.op_type for item in built], list(TYPES.values()))
        self.assertTrue(all(item.repeatable and item.scope == "version" for item in built))
        with self.assertRaises(ValueError):
            provenance.road_operation_defs({ROAD: recompute}, replays)
        with self.assertRaises(ValueError):
            provenance.road_operation_defs(functions, {**replays, "des.platform": reproduce})

    def test_names_and_labels_have_their_spanish(self) -> None:
        """Principio 10: el nombre de cada tipo (también el de la edición de los perfiles) y de cada cifra es un
        ``msgid`` en inglés (sin letras del español) con su traducción en ``core/i18n/messages.toml``."""
        msgids = {declared.label_msgid for declared in provenance.ROAD_OPERATION_TYPES}
        msgids |= {item.label_msgid for item in provenance.ROAD_PROFILE_OPERATIONS}
        msgids |= {figure.label_msgid for figure in (*provenance.ROAD_FIGURES, *provenance.ACCESS_FIGURES)}
        for msgid in msgids:
            with self.subTest(msgid=msgid):
                self.assertEqual(set(msgid) & SPANISH_LETTERS, set())
        self.assertEqual(i18n.untranslated(sorted(msgids)), [])
        table = i18n.load_messages()
        self.assertTrue(all(table[msgid] != msgid for msgid in msgids))
        self.assertEqual({msgid: table[msgid] for msgid in LABELS.values()},
                         {"Haul road": "Pista", "Accessibility of the haul roads": "Accesibilidad de las pistas",
                          "Proposal of the route of a haul road": "Propuesta de trazado de una pista"})


class DataFamiliesTest(unittest.TestCase):
    def test_the_six_families_and_their_roles(self) -> None:
        """RF-017-01, 24, 25, 28 (plan 017 §5.2.3; P-8; ADR-0031 §3): ``des_rdx_`` (el eje por estaciones), ``des_rpl_``
        (la capa propuesta, **editable**), ``des_acc_`` (lo alcanzable, una rejilla), ``des_acb_`` (bermas), ``des_acp_``
        (plataformas) y ``des_acz_`` (zonas «requiere acceso»), cada una con **su papel**, por el que las leen la 012 y
        R-44 sin importar ``design``; ninguna lleva el papel de una superficie de diseño; las de la pista que ya
        existían (``des_psf_``, ``des_epr_`` y ``des_prp_``) siguen con los suyos."""
        self.assertEqual([family.code for family in provenance.ROAD_DATA_FAMILIES], list(FAMILIES))
        self.assertEqual((provenance.ROAD_AXIS_TABLE, provenance.ROUTE_LAYER_TABLE, provenance.ACCESS_GRID,
                          provenance.ACCESS_BERMS_TABLE, provenance.ACCESS_PLATFORMS_TABLE,
                          provenance.ACCESS_ZONES_TABLE), tuple(FAMILIES))
        for family in provenance.ROAD_DATA_FAMILIES:
            kind, store_name, reader, role, extension, _editable = FAMILIES[family.code]
            with self.subTest(family=family.code):
                self.assertIs(provenance.FAMILIES_BY_CODE[family.code], family)
                self.assertEqual((family.kind, str(family.store), family.reader, family.role, family.extension),
                                 (kind, store_name, reader, role, extension))
                self.assertTrue(family.named)
                self.assertEqual(family.prefix, f"des_{family.code}_")
                self.assertTrue(family.label.strip())
        roles = [family.role for family in provenance.ROAD_DATA_FAMILIES]
        self.assertEqual(len(set(roles)), 6)
        older = {family.role for family in (*provenance.FAMILIES, *provenance.QUARRY_FAMILIES,
                                            *provenance.ENTITY_FAMILIES, *provenance.SUPPORTED_FAMILIES)}
        self.assertEqual(set(roles) & older, set())
        self.assertNotIn(provenance.DESIGN_SURFACE_ROLE, roles)
        self.assertEqual(len(provenance.FAMILIES_BY_CODE), 5 + 10 + 5 + 8 + 6)  # 013, 014, 015, 016 y 017

    def test_the_roles_of_what_the_operations_consume_and_leave(self) -> None:
        """RF-017-01, 24, 25, 28 (plan 017 §5.2.3): el papel del eje por estaciones de otra pista, de la capa propuesta, de
        lo alcanzable y de las zonas «requiere acceso» (``ROAD_ACCESS_ZONES_ROLE``, el que importará ``reserves``: nada de
        ``design.entities``); y los de lo que consume la accesibilidad (sus entradas, la superficie final de la cantera)."""
        self.assertEqual((provenance.ROAD_AXIS_ROLE, provenance.ROUTE_LAYER_ROLE, provenance.ROAD_ACCESS_ROLE,
                          provenance.ROAD_ACCESS_BERMS_ROLE, provenance.ROAD_ACCESS_PLATFORMS_ROLE,
                          provenance.ROAD_ACCESS_ZONES_ROLE),
                         tuple(item[3] for item in FAMILIES.values()))
        self.assertEqual((provenance.ACCESS_ENTRIES_ROLE, provenance.ACCESS_FINAL_ROLE),
                         ("access_entries", "surface_final"))
        self.assertEqual((provenance.ENTITY_SURFACE_ROLE, provenance.ENTITY_ROLE, provenance.ENTITY_LAYER_ROLE,
                          provenance.SUPPORTED_ON_ROLE), ("entity_surface", "entity", "entity_layer", "supported_on"))

    def test_names_and_locators_and_what_is_editable(self) -> None:
        """RF-017-24, 28, RF-008-17, RF-008-56 (D-34 de la 009; P-8): el nombre ``des_<familia>_<nombre>`` y la ubicación con
        el código de la versión (``rasters/des_acc_acceso_v02.tif``, ``des_rdx_pista_1_v02``); la ``DatasetSpec`` es de
        ``des``, sin selector, con su papel; **solo la capa propuesta es editable a mano en QGIS**: lo demás es salida no
        editable (se bloquea si se edita fuera)."""
        self.assertEqual(provenance.dataset_name("acc", "Acceso"), "des_acc_acceso")
        self.assertEqual(provenance.dataset_name("rdx", "Pista Ñandú 1"), "des_rdx_pista_nandu_1")
        self.assertEqual(provenance.dataset_locator("acc", "Acceso", "V02"), "rasters/des_acc_acceso_v02.tif")
        self.assertEqual(provenance.dataset_locator("rdx", "Pista 1", "V02"), "des_rdx_pista_1_v02")
        self.assertEqual(provenance.dataset_locator("rpl", "Pista 1", "V10"), "des_rpl_pista_1_v10")
        for code, (kind, _store, reader, role, extension, editable) in FAMILIES.items():
            with self.subTest(family=code):
                found = provenance.dataset_spec(code, "Pista 1", "V03", crs_epsg=25830)
                expected = f"des_{code}_pista_1_v03"
                self.assertEqual((found.name, found.module, found.kind, found.reader, found.role, found.crs_epsg),
                                 (f"des_{code}_pista_1", "des", kind, reader, role, 25830))
                self.assertEqual(found.locator, f"rasters/{expected}{extension}" if extension else expected)
                self.assertIsInstance(found, datasets.DatasetSpec)
                self.assertEqual(found.qgis_editable, editable)
        for older in ("env", "srf", "psf", "epr", "prp", "stk", "enl", "decl"):
            with self.subTest(older=older):  # lo de las specs anteriores no es editable (sin cambios)
                name = "" if older in ("enl", "decl") else "Pista 1"
                self.assertFalse(provenance.dataset_spec(older, name, "V01").qgis_editable)
        with self.assertRaises(ValueError):
            provenance.dataset_locator("acc", "Acceso", "v2")


class FiguresTest(unittest.TestCase):
    def test_the_figures_of_each_type(self) -> None:
        """RF-017-23, 24 (plan 017 §5.2.3; ADR-0025; RF-008-30): cada cifra con su clave y su unidad del catálogo, en el
        orden del plan; las cotas, el desnivel y el volumen neto admiten negativos y las demás no; ninguna lleva «grade»
        (glosario §14) y ninguna clave se declara dos veces entre las cinco specs."""
        self.assertEqual({figure.key: (figure.unit, figure.allow_negative) for figure in provenance.ROAD_FIGURES},
                         ROAD_FIGURES)
        self.assertEqual([figure.key for figure in provenance.ROAD_FIGURES], list(ROAD_FIGURES))
        self.assertEqual({figure.key: (figure.unit, figure.allow_negative) for figure in provenance.ACCESS_FIGURES},
                         ACCESS_FIGURES)
        self.assertEqual([figure.key for figure in provenance.ACCESS_FIGURES], list(ACCESS_FIGURES))
        self.assertEqual([figure.key for figure in provenance.PROPOSE_FIGURES], list(PROPOSE_FIGURES))
        for figure in provenance.PROPOSE_FIGURES:  # las dos claves son las de la pista: los mismos objetos
            self.assertIn(figure, provenance.ROAD_FIGURES)
        self.assertEqual((len(provenance.ROAD_FIGURES), len(provenance.ACCESS_FIGURES)), (23, 9))
        for figure in (*provenance.ROAD_FIGURES, *provenance.ACCESS_FIGURES):
            self.assertIsInstance(figure, contract.FigureDef)
            self.assertNotIn("grade", figure.key)
        keys = [figure.key for figure in (*provenance.FIGURES, *provenance.QUARRY_FIGURES, *provenance.ENTITY_FIGURES,
                                          *provenance.SUPPORTED_FIGURES, *provenance.ROAD_FIGURES,
                                          *provenance.ACCESS_FIGURES)]
        self.assertEqual(len(keys), len(set(keys)), "una cifra declarada dos veces")

    def test_the_figures_of_a_road(self) -> None:
        """RF-017-23 (plan 017 §5.2.3): las cifras CALCULADO de la pista ``name`` de código ``code``, con el ámbito de
        las entidades (el nombre de la operación y el código de la pista), en el orden de la tabla y con su unidad: ``values``
        da cada una por su clave (las veintitrés); ``None`` la que no existe (sin curvas no hay radio mínimo) no se
        registra; las cotas y el neto admiten negativos."""
        values = {**all_figures(ROAD_FIGURES), "des.road_z_end_m": -3.5, "des.road_net_m3": -120.25,
                  "des.road_curves": 4, "des.road_radius_min_m": None}
        found = provenance.road_figures("Pista 1", "RDW-001", values)
        self.assertEqual([item.key for item in found], [key for key in ROAD_FIGURES if key != "des.road_radius_min_m"])
        self.assertTrue(all(isinstance(item, figures_mod.FigureSpec) for item in found))
        self.assertEqual(found[0].scope, {"name": "pista_1", "entity": "RDW-001"})
        by_key = {item.key: item for item in found}
        self.assertEqual((by_key["des.road_z_end_m"].value, by_key["des.road_net_m3"].value,
                          by_key["des.road_curves"].value), (-3.5, -120.25, 4.0))
        self.assertEqual({key: by_key[key].unit for key in by_key}, {key: ROAD_FIGURES[key][0] for key in by_key})

    def test_the_figures_of_an_access_and_of_a_proposal(self) -> None:
        """RF-017-24, 25, 28: las de la accesibilidad con el ámbito de la entidad (``ACC-001``), con las cotas negativas
        admitidas y los recuentos enteros; las de la propuesta (``des.road_length_m`` y ``des.road_gradient_max_pct``) con
        el ámbito del nombre de la operación, que no es una entidad."""
        values = {**all_figures(ACCESS_FIGURES), "des.acc_z_min_m": -4.0, "des.acc_berms_reached": 3,
                  "des.acc_berms_total": 4, "des.acc_z_min_final_m": None}
        found = provenance.access_figures("Accesibilidad 1", "ACC-001", values)
        self.assertEqual([item.key for item in found], [key for key in ACCESS_FIGURES if key != "des.acc_z_min_final_m"])
        self.assertEqual(found[0].scope, {"name": "accesibilidad_1", "entity": "ACC-001"})
        self.assertEqual((found[0].value, found[3].value, found[4].value), (-4.0, 3.0, 4.0))
        proposal = provenance.propose_figures("Trazado de prueba", {"des.road_length_m": 812.5,
                                                                      "des.road_gradient_max_pct": 9.75})
        self.assertEqual([(item.key, item.value, item.unit) for item in proposal],
                         [("des.road_length_m", 812.5, "m"), ("des.road_gradient_max_pct", 9.75, "%")])
        self.assertEqual(proposal[0].scope, {"name": "trazado_de_prueba"})

    def test_a_figure_that_is_wrong_is_a_fault_of_the_program(self) -> None:
        """RF-017-23, RF-013-17: una que sobra o falta, una negativa donde no se admite, un recuento que no es entero o un
        valor que no es finito es un error del programa (``ValueError``; ``TypeError`` si no es un número); un código
        que no es el de una pista, también."""
        full = all_figures(ROAD_FIGURES)
        with self.assertRaises(ValueError):  # una de más
            provenance.road_figures("Pista 1", "RDW-001", {**full, "des.road_extra_m": 1.0})
        with self.assertRaises(ValueError):  # una de menos
            provenance.road_figures("Pista 1", "RDW-001", {"des.road_length_m": 1.0})
        for key, bad in (("des.road_length_m", -1.0), ("des.road_cut_m3", -0.5), ("des.road_curves", 2.5),
                         ("des.road_curves", -1), ("des.road_area_m2", math.nan), ("des.road_z_start_m", math.inf)):
            with self.subTest(key=key, value=bad), self.assertRaises(ValueError):
                provenance.road_figures("Pista 1", "RDW-001", {**full, key: bad})
        with self.assertRaises(TypeError):
            provenance.road_figures("Pista 1", "RDW-001", {**full, "des.road_length_m": "3"})  # type: ignore[dict-item]
        with self.assertRaises(ValueError):
            provenance.road_figures("Pista 1", "rdw_001", full)
        with self.assertRaises(ValueError):
            provenance.access_figures("Accesibilidad", "ACC-001", {**all_figures(ACCESS_FIGURES), "des.acc_berms_total": -1})


class InputsAndParametersTest(unittest.TestCase):
    def test_what_a_road_consumes(self) -> None:
        """RF-017-01, 03, 06 (plan 017 §5.2.3; RF-015-06, RF-015-15): lo que consume ``des.road``, en su orden y sin
        repetir: la capa de origen (``entity_layer``: su geometría y su hash; un cambio de geometría en QGIS deja la pista
        obsoleta, uno de un campo no), la superficie de partida ya resuelta (``surface``), las máscaras de la versión y,
        **añadidas al crear**, lo que pisa (``supported_on``: el origen en otra pista, el destino en una entidad y lo que
        ya había). El perfil no es una entrada: son parámetros. ``ValueError`` si faltan los nombres."""
        Use = operations.Use
        mask = Use("gis_msk_a", "mask")
        self.assertEqual(provenance.road_inputs("gis_fea_pistas_puntos", "des_psf_p1", (mask,), ("des_psf_p1", "des_psf_otra")),
                         (Use("gis_fea_pistas_puntos", "entity_layer"), Use("des_psf_p1", "surface"), mask,
                          Use("des_psf_p1", "supported_on"), Use("des_psf_otra", "supported_on")))
        self.assertEqual(provenance.road_inputs("gis_fea_pistas_ejes", "gis_dtm_tajo"),
                         (Use("gis_fea_pistas_ejes", "entity_layer"), Use("gis_dtm_tajo", "surface")))
        for args in (("", "gis_dtm_tajo"), ("gis_fea_pistas_ejes", " ")):
            with self.subTest(args=args), self.assertRaises(ValueError):
                provenance.road_inputs(*args)
        with self.assertRaises(TypeError):
            provenance.road_inputs("gis_fea_pistas_ejes", "gis_dtm_tajo", (), "des_psf_p1")

    def test_what_an_access_consumes(self) -> None:
        """RF-017-24, 25 (plan 017 §5.2.3; D-18): lo que consume ``des.road_access``, en su orden y sin repetir: la
        superficie (``surface``) y, en una cantera de la 014, la final (``surface_final``), la capa de entradas, las
        máscaras de la versión, las rejillas y las tablas de bermas de la 013 (``berms`` y ``berm_table``) y las huellas de
        las plataformas (``entity``). Si cambia una pista, una berma o una entrada, queda obsoleta."""
        Use = operations.Use
        mask = Use("gis_msk_a", "mask")
        self.assertEqual(
            provenance.access_inputs("des_psf_p1", "gis_fea_pistas_entradas", (mask,), final="des_fin_tajo",
                                     berms=("des_brm_a", "des_brm_a"), berm_tables=("des_bmt_a",),
                                     footprints=("des_epr_p1",)),
            (Use("des_psf_p1", "surface"), Use("des_fin_tajo", "surface_final"),
             Use("gis_fea_pistas_entradas", "access_entries"), mask, Use("des_brm_a", "berms"),
             Use("des_bmt_a", "berm_table"), Use("des_epr_p1", "entity")))
        self.assertEqual(provenance.access_inputs("gis_dtm_tajo", "gis_fea_pistas_entradas"),
                         (Use("gis_dtm_tajo", "surface"), Use("gis_fea_pistas_entradas", "access_entries")))
        with self.assertRaises(ValueError):
            provenance.access_inputs("", "gis_fea_pistas_entradas")

    def test_what_a_road_reads(self) -> None:
        """RF-017-01, 02, 07, 10 (plan 017 §5.2.2; P-14): los parámetros que lee ``des.road`` de la pista ``code`` según su
        modo —el modo, la capa, el perfil y la partida siempre; «trazar», además, el origen, el destino y los de la ruta
        (con el presupuesto de estados); «sobre un eje» y «eje 3D», la geometría de su capa—, **solo los opcionales que
        tienen valor** (el apoyo, la cota y la tolerancia de llegada y la zona del destino, las cotas de inicio y de fin),
        las dependencias declaradas si las tiene, los 14 valores del perfil que cambian su resultado (no su clase
        normativa) y los del proyecto de toda entidad que mide un borde. **Ni su nombre ni lo que declara** (no declara)."""
        key = params.entity_key
        trace = provenance.road_params("RDW-001", mode="trace", profile="pista_principal")
        route = ("mesh_m", "level_step_m", "max_cut_fill_m", "lambda_per_m", "turn_m", "margin_m", "simplify_m",
                 "arrival_tol_m", "search_budget")
        self.assertEqual(trace[:6], tuple(key("RDW-001", last) for last in ("mode", "layer", "profile", "start",
                                                                              "origin", "destination")))
        self.assertEqual(trace[6:15], tuple(key("RDW-001", last) for last in route))
        profile = trace[15:-len(PROJECT_PARAMS)]
        self.assertEqual(len(profile), 14)
        self.assertTrue(all(item.startswith("des.roadprofile.pista_principal.") for item in profile))
        self.assertNotIn("des.roadprofile.pista_principal.class", profile)
        self.assertEqual(trace[-len(PROJECT_PARAMS):], PROJECT_PARAMS)
        for last in ("name", "reason", "discarded", "feature", "supports", "support", "dest_level_m", "start_level_m"):
            self.assertNotIn(key("RDW-001", last), trace)
        for mode in ("on_axis", "axis_3d"):
            found = provenance.road_params("RDW-002", mode=mode, profile="acceso", valued=("start_level_m", "support"),
                                           supports=True)
            with self.subTest(mode=mode):
                self.assertEqual(found[:8], tuple(key("RDW-002", last) for last in (
                    "mode", "layer", "feature", "profile", "start", "support", "supports", "start_level_m")))
                self.assertFalse({key("RDW-002", last) for last in route} & set(found))
                self.assertNotIn(key("RDW-002", "origin"), found)
        zone = provenance.road_params("RDW-001", mode="trace", profile="p", valued=("dest_zone", "dest_level_m", "dest_tol_m",
                                                                                     "end_level_m"))
        for last in ("dest_level_m", "dest_tol_m", "dest_zone", "end_level_m"):
            self.assertIn(key("RDW-001", last), zone)
        self.assertEqual([item for item in zone if item.startswith("des.road.rdw_001.")][5:10],
                         [key("RDW-001", last) for last in ("destination", "dest_level_m", "dest_tol_m", "dest_zone",
                                                            "end_level_m")])
        for bad in (dict(mode="fly", profile="p"), dict(mode="trace", profile="Pista"),
                    dict(mode="trace", profile="p", valued=("name",)), dict(mode="trace", profile="p", valued=("mesh_m",))):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                provenance.road_params("RDW-001", **bad)
        with self.assertRaises(ValueError):
            provenance.road_params("ACC-001", mode="trace", profile="p")  # no es el código de una pista
        with self.assertRaises(ValueError):
            provenance.road_params("rdw_001", mode="trace", profile="p")

    def test_what_an_access_reads(self) -> None:
        """RF-017-24, 25 (plan 017 §5.2.2; D-17): los parámetros que lee ``des.road_access`` de la accesibilidad ``code``:
        la superficie, la capa de entradas y los tres umbrales (la pendiente y el ancho transitables y el área mínima de
        berma); los datos de bermas solo si tiene valor. No lee su nombre ni lo que decide (descartarla)."""
        key = params.entity_key
        found = provenance.access_params("ACC-001")
        self.assertEqual(found, tuple(key("ACC-001", last) for last in (
            "surface", "entries_layer", "walk_slope_pct", "walk_width_m", "min_berm_area_m2")))
        self.assertEqual(provenance.access_params("ACC-001", berms=True)[2], key("ACC-001", "berms"))
        for last in ("name", "discarded"):
            self.assertNotIn(key("ACC-001", last), found)
        with self.assertRaises(ValueError):
            provenance.access_params("RDW-001")
        with self.assertRaises(ValueError):
            provenance.access_params("acc_001")


class EntityTypesTest(unittest.TestCase):
    """RF-017-01, RF-015-01 a 04 (plan 017 §2.1, §5.1; ADR-0030; ADR-0031): la pista y la accesibilidad son dos tipos del
    programa del registro de las entidades."""

    def test_the_two_types_are_registered_as_program_types(self) -> None:
        """RF-017-01, RF-015-01: ``road`` (``RDW``, **con cadena**: tiene ``start``) y ``access`` (``ACC``, **sin cadena**:
        no lo tiene) son miembros de ``EntityKind`` y tipos registrados del programa, detrás de los cinco de las dos
        specs anteriores, con su familia de parámetros, el tipo de su operación y los mensajes de su motivo y de «apoyo
        retirado»."""
        self.assertEqual([item.kind for item in entities.registered_types()],
                         ["platform", "stockpile", "removal", "buttress", "body", "road", "access"])
        self.assertEqual([item.value for item in entities.EntityKind],
                         ["platform", "stockpile", "removal", "buttress", "body", "road", "access"])
        road, access = entities.entity_type("road"), entities.entity_type("access")
        self.assertIs(entities.EntityKind.ROAD, entities.EntityKind("road"))
        self.assertIs(entities.EntityKind.ACCESS, entities.EntityKind("access"))
        self.assertEqual((road.kind, road.prefix, road.key_prefix, road.op_type, road.chained, road.project_op_type),
                         ("road", "RDW", "des.road", provenance.ROAD, True, None))
        self.assertEqual((access.kind, access.prefix, access.key_prefix, access.op_type, access.chained,
                          access.project_op_type),
                         ("access", "ACC", "des.access", provenance.ROAD_ACCESS, False, None))
        self.assertIs(road.params, params.entity_params("road"))
        self.assertIs(access.params, params.entity_params("access"))
        self.assertEqual((road.reason, road.removed), ("des.road_declared_reason", "des.road_support_removed"))
        self.assertEqual((access.reason, access.removed), ("des.access_declared_reason", "des.access_support_removed"))
        self.assertEqual((entities.EntityKind.ROAD.prefix, entities.EntityKind.ACCESS.chained), ("RDW", False))

    def test_a_road_leaves_a_surface_and_a_footprint_and_an_access_leaves_neither(self) -> None:
        """RF-017-01, RF-015-12, RF-015-27 (plan 017 §5.1): la pista deja su superficie (``entity_surface``) y la tabla de
        su huella (``entity``: sale en la capa de entidades y se puede apoyar en ella); **la accesibilidad no deja ninguna
        superficie en la que apoyarse y no tiene huella** (``has_footprint`` falso por el papel de su tabla): la
        declaración y la capa de entidades la saltan; ninguno de los dos declara restricciones por defecto."""
        road, access = entities.entity_type("road"), entities.entity_type("access")
        self.assertEqual((road.surface_role, road.table_role, road.has_footprint, road.own_zone),
                         (provenance.ENTITY_SURFACE_ROLE, provenance.ENTITY_ROLE, True, False))
        self.assertEqual((access.surface_role, access.table_role, access.has_footprint),
                         (None, provenance.ROAD_ACCESS_ZONES_ROLE, False))
        for spec in (road, access):
            self.assertNotIn("protect", spec.params.names)
            self.assertNotIn("guard_m", spec.params.names)
        self.assertNotIn("start", access.params.names)
        self.assertIn("start", road.params.names)
        self.assertNotIn(provenance.ROAD, entity_store._DECLARES)  # noqa: SLF001 - la pista no declara (D-15)
        self.assertEqual(entity_store.LAYER_FIGURES["road"][0], ("area_m2", "des.road_area_m2"))
        self.assertEqual([column for column, _key in entity_store.LAYER_FIGURES["road"]],
                         ["area_m2", "cut_m3", "fill_m3", "edge_cut_m3", "edge_fill_m3"])
        self.assertNotIn("access", entity_store.LAYER_FIGURES)  # sin huella: no sale en la capa

    def test_the_code_is_correlative_per_scope_and_immutable(self) -> None:
        """RF-017-01, RF-015-01 (ADR-0030: un código inmutable por entidad): ``RDW-001`` y ``ACC-001``, correlativos por
        ámbito, cada tipo con su cuenta; el tipo de un código es su prefijo; el de otro tipo, uno mal escrito o un tipo sin
        registrar es un error del programa."""
        road, access = entities.EntityKind.ROAD, entities.EntityKind.ACCESS
        self.assertEqual(entities.next_code(road, ()), "RDW-001")
        self.assertEqual(entities.next_code(access, ()), "ACC-001")
        self.assertEqual(entities.next_code(road, ["RDW-001", "PLT-007", "ACC-004", "RDW-003"]), "RDW-004")
        self.assertEqual(entities.next_code(access, ["RDW-001", "ACC-001", "ACC-001", "ACC-003"]), "ACC-004")
        self.assertEqual(entities.next_code("road", ["RDW-009"]), "RDW-010")
        self.assertEqual(entities.next_code(entities.EntityKind.PLATFORM, ["RDW-001", "ACC-001"]), "PLT-001")
        self.assertEqual((entities.format_code(road, 7), entities.format_code(access, 12)), ("RDW-007", "ACC-012"))
        self.assertIs(entities.kind_of_code("RDW-001"), road)
        self.assertIs(entities.kind_of_code("ACC-020"), access)
        for wrong in ("RDW-1", "rdw-001", "ACC-00a", "RWD-001"):
            with self.subTest(code=wrong), self.assertRaises(ValueError):
                entities.kind_of_code(wrong)
        record = entities.EntityRecord("RDW-001", "Pista 1", road, "gis_dtm_tajo", None, entities.EntityState.UNCALCULATED)
        self.assertEqual((record.segment, record.start), ("rdw_001", "gis_dtm_tajo"))
        bare = entities.EntityRecord("ACC-001", "Accesibilidad 1", access, None, None, entities.EntityState.UNCALCULATED)
        self.assertEqual((bare.segment, bare.start), ("acc_001", None))
        with self.assertRaises(ValueError):  # un tipo sin cadena no tiene partida
            entities.EntityRecord("ACC-001", "Accesibilidad 1", access, "gis_dtm_tajo", None,
                                  entities.EntityState.UNCALCULATED)
        with self.assertRaises(ValueError):
            entities.EntityRecord("ACC-001", "Accesibilidad 1", road, None, None, entities.EntityState.UNCALCULATED)

    def test_the_chain_has_the_road_and_leaves_out_the_access(self) -> None:
        """RF-017-01, RF-015-04 (D-16: una red de pistas es una cadena; plan 017 §2.1): ``chain_tails`` deja fuera a la
        accesibilidad (sin cadena: no declara y su dato no se congela como superficie de diseño) y da la cola de una
        pista que parte de la plataforma; y **nadie parte de la superficie de una accesibilidad**: ``des.chainless_start``,
        con el campo, el valor y las dos entidades."""
        State = entities.EntityState  # noqa: N806
        road = entities.EntityRecord("RDW-001", "Pista 1", entities.EntityKind.ROAD, "gis_dtm_tajo", None, State.CURRENT)
        branch = entities.EntityRecord("RDW-002", "Ramal", entities.EntityKind.ROAD, entities.surface_ref("RDW-001"),
                                       None, State.CURRENT)
        access = entities.EntityRecord("ACC-001", "Accesibilidad 1", entities.EntityKind.ACCESS, None, None, State.CURRENT)
        platform = entities.EntityRecord("PLT-001", "P1", entities.EntityKind.PLATFORM, entities.surface_ref("RDW-002"),
                                         None, State.CURRENT)
        self.assertEqual([item.code for item in entities.chain_tails([access])], [])
        self.assertEqual([item.code for item in entities.chain_tails([road, access])], ["RDW-001"])
        self.assertEqual([item.code for item in entities.chain_tails([access, road, branch])], ["RDW-002"])
        self.assertEqual([item.code for item in entities.chain_tails([road, branch, platform, access])], ["PLT-001"])
        for start in (entities.surface_ref("ACC-001"),):
            wrong = entities.EntityRecord("RDW-003", "Pista 3", entities.EntityKind.ROAD, start, None, State.CURRENT)
            for check in (entities.chain_tails, entities.check_chain):
                with self.subTest(check=check.__name__), self.assertRaises(messages.DesignError) as caught:
                    check([road, access, wrong])
                self.assertEqual(caught.exception.code, "des.chainless_start")
                self.assertEqual(caught.exception.value, start)


class RoadRegistryProjectTest(efx.EntityProjectCase):
    """RF-017-01, RF-015-01, 02, 04, 08, 25 con proyecto (la cantera de la 014 en la rejilla gruesa, con operaciones
    **sintéticas** que hacen de lo que dejarán las operaciones reales): V01 con una pista (``RDW-001``, que parte del
    terreno y deja su superficie y su huella) y una accesibilidad (``ACC-001``, que deja lo alcanzable y las zonas, sin
    superficie), más una plataforma suelta (``PLT-001``, de la 015) para comparar."""

    STEP_M = qfx.COARSE_STEP_M
    GROUND = "gis_dtm_ladera"
    ops: dict[str, str] = {}

    @classmethod
    def declare(cls, code: str, values: dict[str, Any]) -> list[str]:
        """Da de alta en V01 los parámetros de la entidad ``code`` y devuelve sus claves."""
        store_ = core_params.ParameterStore(cls.project)
        cls.clock.advance(minutes=1)
        keys = []
        with cls.project.write_transaction() as conn:
            for param, value in values.items():
                key = params.entity_key(code, param)
                store_.create(conn, key, value, kind="ADOPTADO", source="Prueba del registro de la pista", source_kind="person",
                              decided_by="Samuel (IMGA)", reason="Prueba de la T03 de la 017", version=cls.v1.code)
                keys.append(key)
        return keys

    @classmethod
    def run_operation(cls, op_type: str, tag: str, keys: list[str], families: tuple[tuple[str, str], ...]) -> str:
        """La operación sintética de ``op_type`` que lee los parámetros ``keys`` y escribe una tabla de juguete por cada
        ``(familia, papel)`` de ``families`` (``des_<familia>_<tag>``)."""
        cls.clock.advance(minutes=1)
        handle = operations.begin_operation(cls.project, op_type, settings={"tag": tag}, inputs=[], params=keys,
                                            executor="blender", version=cls.v1.uid)
        specs = []
        with cls.project.write_transaction() as conn:
            for family, role in families:
                name = f"des_{family}_{tag}"
                locator = versions_model.version_locator(name, cls.v1.code)
                gpkg_base.create_attribute_table(conn, locator, [gpkg_base.ColumnDef("value", "DOUBLE")], name,
                                                 "Dato sintético de la prueba de la T03 (spec 017)")
                conn.execute(f'INSERT INTO "{locator}" (value) VALUES (?)', (1.0,))
                specs.append(datasets.DatasetSpec(name, "des", "table", datasets.Store.GPKG, locator,
                                                  reader=builtin.GPKG_LAYER.id, role=role))
            handle.complete(conn, outputs=specs)
        return str(handle.uid)

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_families((*params.ENTITY_FAMILIES, *params.ROAD_FAMILIES, *params.ACCESS_FAMILIES))
        cls.addClassCleanup(core_params.unregister_families, "des")

        def never(request: Any) -> Any:
            raise AssertionError("las pruebas del registro no recalculan")

        cls.enterClassContext(registered(*(provenance.operation_def(op_type, never)
                                           for op_type in (provenance.PLATFORM, provenance.ROAD, provenance.ROAD_ACCESS))))
        surface = (provenance.ENTITY_SURFACE_ROLE, provenance.ENTITY_ROLE)
        keys = {
            "RDW-001": cls.declare("RDW-001", {"name": "Pista 1", "mode": "on_axis", "layer": "gis_fea_pistas_ejes",
                                               "profile": "pista_principal", "start": cls.GROUND}),
            "ACC-001": cls.declare("ACC-001", {"name": "Accesibilidad 1", "surface": cls.GROUND,
                                               "entries_layer": "gis_fea_pistas_entradas"}),
            "PLT-001": cls.declare("PLT-001", {"name": "P1", "start": "des_srf_otra"}),
        }
        cls.ops = {
            "RDW-001": cls.run_operation(provenance.ROAD, "r1", keys["RDW-001"], (("psf", surface[0]), ("epr", surface[1]))),
            "ACC-001": cls.run_operation(provenance.ROAD_ACCESS, "a1", keys["ACC-001"],
                                         (("acc", provenance.ROAD_ACCESS_ROLE), ("acz", provenance.ROAD_ACCESS_ZONES_ROLE))),
            "PLT-001": cls.run_operation(provenance.PLATFORM, "p1", keys["PLT-001"], (("psf", surface[0]), ("epr", surface[1]))),
        }

    def registry(self) -> Any:
        return entities.registry(self.project, self.v1.uid)

    def test_the_registry_lists_the_road_and_the_access_with_their_kind(self) -> None:
        """RF-017-01, RF-015-01, RF-015-25: el registro de la versión lista la pista y la accesibilidad con su tipo (el de su
        código), su nombre, su partida (sin ella, la accesibilidad: no tiene), su estado deducido del grafo y su operación; la
        lista de las que se pueden apoyar (``entity_surfaces``) lleva la pista y la plataforma, **nunca la accesibilidad**
        (no deja superficie), cada una con los papeles de su tipo."""
        found = self.registry()
        self.assertEqual([item.code for item in found.records], ["PLT-001", "RDW-001", "ACC-001"])
        self.assertEqual([item.kind for item in found.records],
                         [entities.EntityKind.PLATFORM, entities.EntityKind.ROAD, entities.EntityKind.ACCESS])
        self.assertEqual([item.start for item in found.records], ["des_srf_otra", self.GROUND, None])
        self.assertEqual({item.state for item in found.records}, {entities.EntityState.CURRENT})
        self.assertEqual({entry.record.code: entry.operation_uid for entry in found}, self.ops)
        with self.project.read() as conn:
            surfaces = entity_store.entity_surfaces(conn, found)
            only_road = entity_store.entity_surfaces(conn, found, kinds=["road"])
            only_access = entity_store.entity_surfaces(conn, found, kinds=["access"])
        self.assertEqual(list(surfaces), ["PLT-001", "RDW-001"])
        self.assertEqual((surfaces["RDW-001"].surface, surfaces["RDW-001"].table, surfaces["RDW-001"].kind,
                          surfaces["RDW-001"].operation_uid),
                         ("des_psf_r1", "des_epr_r1", entities.EntityKind.ROAD, self.ops["RDW-001"]))
        self.assertEqual(list(only_road), ["RDW-001"])
        self.assertEqual(only_access, {})

    def test_the_freeze_asks_to_verify_the_road_and_not_the_access(self) -> None:
        """RF-017-01, RF-012-25, RF-015-04: congelar pide verificar la superficie de la última de cada cadena: la de la pista
        (y la de la plataforma) y **no** la de la accesibilidad, que no está en ninguna."""
        with self.project.read() as conn:
            found = entities.chain_tail_surfaces(conn, self.v1.uid)
            names = {str(uid): name for uid, name in conn.execute("SELECT uid, name FROM gb_dataset WHERE name LIKE 'des_psf_%'")}
        self.assertEqual(sorted(names[uid] for uid in found), ["des_psf_p1", "des_psf_r1"])

    def test_changing_a_value_of_a_road_or_an_access_does_not_break_the_rules_between_entities(self) -> None:
        """RF-017-01, RF-015-01, RF-015-04 (T39 y T47: «Cambiar parámetro…» de **cada tipo**; la pista sin ``protect``):
        cambiar el modo de la pista (``mode``, que la plataforma también tiene con otro sentido) o su nombre por uno libre
        se admite, sin escribir nada (hasta ahora era un ``KeyError``: la pista no tiene ``protect``); un nombre ya
        tomado, vacío, o la partida de la superficie de la accesibilidad se rechazan como en los demás tipos, con su
        entidad y el campo; y nadie parte de la superficie de una accesibilidad (``des.chainless_start``)."""
        def check(code: str, param: str, value: object) -> None:
            entity_store.check_parameter_change(self.project, params.entity_key(code, param), value, version=self.v1.uid)

        before = change_counter(self.root)
        for code, param, value in (("RDW-001", "mode", "axis_3d"), ("RDW-001", "name", "Pista nueva"),
                                   ("RDW-001", "start", "des_srf_libre"), ("RDW-001", "start", entities.surface_ref("PLT-001")),
                                   ("ACC-001", "name", "Accesibilidad nueva")):
            with self.subTest(code=code, param=param, value=value):
                check(code, param, value)
        for code, param, value, expected in (("RDW-001", "name", "P1", "des.entity_name_repeated"),
                                             ("ACC-001", "name", "Pista 1", "des.entity_name_repeated"),
                                             ("RDW-001", "name", "  ", "des.entity_param_missing"),
                                             ("RDW-001", "start", "entity:ACC-001", "des.chainless_start")):
            with self.subTest(code=code, param=param, value=value), self.assertRaises(messages.DesignError) as caught:
                check(code, param, value)
            self.assertEqual(caught.exception.code, expected)
        self.assertEqual(change_counter(self.root), before, "una comprobación no escribe")


class ClosedListsTest(unittest.TestCase):
    """Las listas cerradas por tipo de operación del lado del dominio (plan 017 §2.1): cada tipo nuevo está en todas, o la
    prueba lo nombra. Lo que repite, lo que reproduce y lo que calcula lo ponen las tareas que crean cada operación (**T17b la
    accesibilidad: hecha**; T21 y T22 la pista y T27 la propuesta: sin comportamiento todavía)."""

    def test_recomputed_lists_the_three_types_after_the_016(self) -> None:
        """RF-008-26, RF-017-01: ``RECOMPUTED`` (lo que repite «Recalcular lo obsoleto») lleva los tres tipos de la 017
        detrás de los de la 016, sin cambiar lo que ya llevaba ni repetir ninguno."""
        for op_type in TYPES.values():
            self.assertIn(op_type, store.RECOMPUTED)
        self.assertEqual(store.RECOMPUTED[-3:], tuple(TYPES.values()))
        self.assertEqual(store.RECOMPUTED[-3 - len(provenance.SUPPORTED_TYPES):-3], provenance.SUPPORTED_TYPES)
        self.assertEqual(len(set(store.RECOMPUTED)), len(store.RECOMPUTED))

    def test_recompute_run_has_a_branch_for_each_type_and_none_falls_to_another_design(self) -> None:
        """RF-008-26: ``recompute_run`` repite cada tipo de ``RECOMPUTED`` por su rama y **ninguno cae en la última** (que
        repite un escalonado): un tipo sin cálculo todavía (la pista y la propuesta) dice qué tarea lo hace
        (``NotImplementedError``), no repite otra operación; **la accesibilidad (T17b) tiene su rama real**: con unos ajustes que no
        son los suyos, un ``ValueError`` (nada de «aún no») y no la de ningún escalonado; la accesibilidad y la propuesta no dejan
        una superficie que se apoye en una entidad: soltar un apoyo es un error del programa (``ValueError``); la pista sí (T22)."""
        for op_type in (ROAD, PROPOSE):
            request = recompute_mod.RecomputeRequest(object(), "uid", op_type, {}, (), ())
            with self.subTest(op_type=op_type), self.assertRaises(NotImplementedError) as caught:
                store.recompute_run(request)
            self.assertIn(op_type, str(caught.exception))
            self.assertIn("017", str(caught.exception))
        request = recompute_mod.RecomputeRequest(object(), "uid", ACCESS, {}, (), ())
        with self.assertRaises(ValueError) as caught:
            store.recompute_run(request)
        self.assertNotIn("aún no", str(caught.exception))
        self.assertIn("code", str(caught.exception))
        released = (provenance.ReleasedSupport("PLT-001", "motivo", "Samuel", "2026-11-20"),)
        for op_type in (ACCESS, PROPOSE):
            request = recompute_mod.RecomputeRequest(object(), "uid", op_type, {}, (), ())
            with self.subTest(op_type=op_type, released=True), self.assertRaises(ValueError) as caught:
                store.recompute_run(request, released=released)
            self.assertNotIn("aún no", str(caught.exception))
        road = recompute_mod.RecomputeRequest(object(), "uid", ROAD, {}, (), ())
        with self.assertRaises(NotImplementedError):  # una pista sí deja superficie: puede dar por bueno un apoyo (T22)
            store.recompute_run(road, released=released)
        for op_type in (ACCESS, PROPOSE):
            self.assertIn(op_type, store._NO_REST_TYPES)  # noqa: SLF001 - no se apoyan en un acopio
        self.assertNotIn(ROAD, store._NO_REST_TYPES)  # noqa: SLF001
        other = recompute_mod.RecomputeRequest(object(), "uid", "des.no_such", {}, (), ())
        with self.assertRaises(ValueError):
            store.recompute_run(other)

    def test_the_reproduce_functions_exist_for_each_type(self) -> None:
        """RF-009-11: ``design.reproduce`` tiene la función de reproducir de cada tipo (la de ``bl`` la importa al usarla); la pista y la
        propuesta, sin comportamiento todavía: ``NotImplementedError`` con el tipo y la tarea que la hace (la accesibilidad es real
        desde la T17b: ``milestone_access_operation``); lo que no es una petición, ``TypeError``; una de otro tipo, ``ValueError``
        (errores del programa)."""
        for op_type, name in ((ROAD, "reproduce_road"), (ACCESS, "reproduce_road_access"),
                              (PROPOSE, "reproduce_road_propose")):
            function = getattr(reproduce_mod, name)
            request = versions_reproduce.ReproduceRequest(op_type, {}, (), {}, ".", None)
            with self.subTest(op_type=op_type):
                if op_type != ACCESS:
                    with self.assertRaises(NotImplementedError) as caught:
                        function(request)
                    self.assertIn(op_type, str(caught.exception))
                    self.assertIn("017", str(caught.exception))
                with self.assertRaises(TypeError):
                    function("petición")
                with self.assertRaises(ValueError):
                    function(versions_reproduce.ReproduceRequest("des.quarry", {}, (), {}, ".", None))
        self.assertNotIn("reproduce_road", reproduce_mod.REPRODUCE)  # las de la 013, sin cambios

    def test_the_entities_of_the_layer_and_the_parameter_prefixes_count_the_new_types(self) -> None:
        """RF-017-01, RF-015-27 (hallazgos D-1 y D-2 de la 016): lo que sigue a «Recalcular lo obsoleto» y a «Cambiar
        parámetro…» cuenta **a las dos entidades**: ``ENTITY_OP_NAMES`` lleva la pista y la accesibilidad (no la
        propuesta, que no es una entidad); la pista **no** declara restricciones (``DECLARING_OP_NAMES`` no la lleva)."""
        self.assertEqual(provenance.ENTITY_OP_NAMES[-2:], (ROAD, ACCESS))
        self.assertNotIn(PROPOSE, provenance.ENTITY_OP_NAMES)
        self.assertNotIn(ROAD, provenance.DECLARING_OP_NAMES)
        self.assertEqual(provenance.ENTITY_OP_NAMES[:5], (provenance.PLATFORM, provenance.STOCKPILE_DETECT,
                                                          provenance.STOCKPILE_REMOVAL, provenance.BUTTRESS,
                                                          provenance.BODY))

    def test_no_declared_reason_is_used_but_both_exist(self) -> None:
        """RF-015-10, RF-015-12, D-15 (``EntityType.reason`` es obligatorio): ni la pista ni la accesibilidad declaran, pero
        su motivo existe en el catálogo, en español y en inglés, con el nombre de la entidad, como el de los demás tipos."""
        for code, es in (("des.road_declared_reason", "declarada por la pista Pista 1"),
                         ("des.access_declared_reason", "declarada por la accesibilidad Pista 1")):
            with self.subTest(code=code):
                self.assertEqual(messages.MESSAGES[code].severity, "note")
                self.assertEqual(messages.render(code, name="Pista 1"), es)
                self.assertIn("Pista 1", messages.render(code, language="en", name="Pista 1"))
        self.assertEqual(entities.declared_reason("road", "Pista 1"), "declarada por la pista Pista 1")
        self.assertEqual(entities.declared_reason("access", "Pista 1"), "declarada por la accesibilidad Pista 1")


if __name__ == "__main__":
    unittest.main()

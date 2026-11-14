# SPDX-License-Identifier: GPL-3.0-or-later
"""Las declaraciones de procedencia de las entidades de diseño (spec 015, T04; HU-015-1;
RF-015-01, RF-015-02; plan 015 §5.2.3; ADR-0025 §2 y ADR-0030).

``design.provenance`` declara con tipos de ``core`` lo que la 015 registra en la procedencia de la
008 y de la 009, aparte de lo de la 013 y la 014 (sin registrar nada: lo registra ``bl/ops/des.py``):

- **tres tipos de operación de la versión**, ``des.platform``, ``des.declare_constraints`` y
  ``des.entity_layer`` (versión 1.0, repetibles y reproducibles con 10⁻⁹ relativo);
- las **cinco familias de datos** de la versión (``des_psf_``, ``des_epr_``, ``des_prp_``,
  ``des_decl_`` y ``des_enl_``): la superficie de una entidad lleva el papel ``entity_surface`` y
  **no** el de ``design_surface`` (la última de cada cadena la añade congelar, T32);
- sus **ajustes**, sus **entradas** (con los papeles ``entity_layer``, ``surface``, ``supported_on`` y
  ``entity``) y los **parámetros** que lee cada una (``des.platform.{e}.*``);
- sus **cifras** (``FigureDef``) con el ámbito ``entity`` (el código de la entidad), y las funciones
  que las arman.

Y, con un proyecto real (la cantera sintética de la 014 con las capas de plataformas), que la 008
acepta lo declarado y que el registro de las entidades de la T03 reconoce la operación con el tipo
y los papeles de esta tarea.
"""

from __future__ import annotations

import json
import math
import unittest
from collections.abc import Iterator
from typing import Any, ClassVar

from tests.support import entity_fixtures as efx
from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered, snapshot

provenance = import_geoblender("design.provenance")
model = import_geoblender("design.model")
design_params = import_geoblender("design.params")
entities = import_geoblender("design.entities")
contract = import_geoblender("core.provenance.contract")
operations = import_geoblender("core.provenance.operations")
figures_mod = import_geoblender("core.provenance.figures")
core_params = import_geoblender("core.params")
datasets = import_geoblender("core.datasets.model")
gpkg_base = import_geoblender("core.gpkg.base")
i18n = import_geoblender("core.i18n")
units = import_geoblender("core.units")
res_provenance = import_geoblender("reserves.provenance")

SPANISH_LETTERS = frozenset("áéíóúüñÁÉÍÓÚÜÑ¿¡")
CODE, NAME = "PLT-001", "Plataforma de carga"
OTHER_CODE, OTHER_NAME = "PLT-002", "Plataforma de taller"
GROUND = "gis_dtm_ladera"
ENTITY_TYPES = ("des.platform", "des.declare_constraints", "des.entity_layer")
PLATFORM_COMMAND = "geoblender.des_draw_platform"
THICKNESS = "res.verify.min_thickness_m"
COMMON_PARAMS = ("des.tolerance.face_deg", "des.warning.magnitude_ratio", THICKNESS,
                 "des.edge.max_created_step_m", "des.edge.min_share")
"""Lo que lee de los parámetros del proyecto toda plataforma: la tolerancia de cara y el umbral de
aviso de magnitud de la 013, el espesor mínimo de la 012 y el salto creado de la 014."""
FAMILIES = {  # código → (tipo, almacén, lector, papel, extensión, con nombre)
    "psf": ("raster", "rasters", "gis.geotiff@1", "entity_surface", ".tif", True),
    "epr": ("table", "gpkg", "core.gpkg_layer@1", "entity", "", True),
    "prp": ("table", "gpkg", "core.gpkg_layer@1", "entity_report", "", True),
    "decl": ("vector", "gpkg", "core.gpkg_layer@1", "constraints_declared", "", False),
    "enl": ("vector", "gpkg", "core.gpkg_layer@1", "entity_map", "", False)}
PLATFORM_FIGURES = {  # clave → (unidad, admite negativos)
    "des.plat_area_m2": ("m2", False), "des.plat_axis_m": ("m", False),
    "des.plat_footprint_m": ("m", False), "des.plat_start_level_m": ("m", True),
    "des.plat_end_level_m": ("m", True), "des.plat_cut_m3": ("m3", False),
    "des.plat_fill_m3": ("m3", False), "des.edge_cut_m3": ("m3", False),
    "des.edge_fill_m3": ("m3", False), "des.edge_wall_max_m": ("m", False),
    "des.plat_below_m2": ("m2", False), "des.plat_below_max_m": ("m", False)}
GOOD_VALUES = {
    "des.plat_area_m2": 8_000.0, "des.plat_axis_m": 200.0, "des.plat_footprint_m": 199.5,
    "des.plat_start_level_m": 230.0, "des.plat_end_level_m": -2.5, "des.plat_cut_m3": 38_400.0,
    "des.plat_fill_m3": 0.0, "des.edge_cut_m3": 1_250.5, "des.edge_fill_m3": 0.0,
    "des.edge_wall_max_m": 3.25, "des.plat_below_m2": 1_600.0, "des.plat_below_max_m": 5.0}


def recompute(request: Any) -> Any:  # nunca se llama: solo declara que se repite sola
    raise AssertionError("las pruebas de las declaraciones no recalculan")


def reproduce(request: Any) -> Iterator[Any]:  # idem
    raise AssertionError("las pruebas de las declaraciones no reproducen")


def entity_definitions() -> tuple[Any, ...]:
    """Los tres tipos con sus funciones y las cifras, como los registrará ``bl``."""
    return (*provenance.entity_operation_defs({t: recompute for t in ENTITY_TYPES},
                                              {t: reproduce for t in ENTITY_TYPES}),
            *provenance.ENTITY_FIGURES)


def line_fields(**changes: Any) -> Any:
    """Los campos de una plataforma de una capa de líneas (con ancho)."""
    base: dict[str, Any] = {"layer": "gis_fea_plataformas_ejes", "start_level_field": "cota_inicial",
                            "gradient_field": "pendiente", "width_field": "ancho"}
    return model.PlatformFields(**{**base, **changes})


def polygon_fields(**changes: Any) -> Any:
    """Los de una de polígonos con su eje enlazado en otra capa."""
    base: dict[str, Any] = {"layer": "gis_fea_plataformas_poligonos",
                            "start_level_field": "cota_inicial", "gradient_field": "pendiente",
                            "axis_field": "eje", "axis_layer": "gis_fea_plataformas_ejes"}
    return model.PlatformFields(**{**base, **changes})


def platform_request(**changes: Any) -> Any:
    """Una plataforma completa de una capa de líneas."""
    base: dict[str, Any] = {
        "name": NAME, "fields": line_fields(), "feature": "1", "start": GROUND, "mode": "cut",
        "edge_angle_deg": 35.0, "reach_m": 60.0, "mesh_factor": 1.0, "counter_tol_m": 0.1,
        "metric": "exact"}
    return model.PlatformRequest(**{**base, **changes})


def values_of(request: Any) -> dict[str, Any]:
    """Los valores que tendrían los parámetros de la plataforma ``request`` (por último segmento de
    la clave): lo que lee la operación al recalcular."""
    found: dict[str, Any] = {
        "layer": request.layer, "feature": request.feature, "start": request.start,
        "start_level_m": 230.0, "gradient_pct": 1.0, "mode": str(request.mode),
        "edge_angle_deg": request.edge_angle_deg, "reach_m": request.reach_m,
        "mesh_factor": request.mesh_factor, "counter_tol_m": request.counter_tol_m,
        "metric": str(request.metric), "protect": request.protect}
    if request.fields.width_field is not None:
        found["width_m"] = 40.0
    for name, value in (("support", request.support), ("max_slope_pct", request.max_slope_pct),
                        ("guard_m", request.guard_m), ("reason", request.reason)):
        if value is not None:
            found[name] = value
    return found


def keyed(code: str, values: dict[str, Any]) -> dict[str, Any]:
    """Los valores con su clave completa (``des.platform.plt_001.mode``)."""
    return {design_params.entity_key(code, name): value for name, value in values.items()}


class EntityDatasetsTest(unittest.TestCase):
    """Las familias de datos de la versión de las entidades (plan 015 §5.2.3)."""

    def test_the_five_families(self) -> None:
        """RF-015-01, RF-015-02: la superficie, GeoTIFF propio (``entity_surface``); la tabla de la
        entidad y su informe, ``core.gpkg_layer@1``; la tabla de las restricciones declaradas y la
        capa de entidades, capas de vector de la versión (una por versión, sin el nombre de una
        operación). Van aparte de las de la 013 y la 014 y no repiten su código."""
        self.assertEqual([family.code for family in provenance.ENTITY_FAMILIES], list(FAMILIES))
        self.assertEqual((provenance.ENTITY_SURFACE_GRID, provenance.ENTITY_TABLE,
                          provenance.ENTITY_REPORT_TABLE, provenance.DECLARED_TABLE,
                          provenance.ENTITY_MAP_TABLE), tuple(FAMILIES))
        before = {family.code for family in (*provenance.FAMILIES, *provenance.QUARRY_FAMILIES)}
        self.assertEqual(before & set(FAMILIES), set())
        for family in provenance.ENTITY_FAMILIES:
            kind, store, reader, role, extension, named = FAMILIES[family.code]
            with self.subTest(family=family.code):
                self.assertIs(provenance.FAMILIES_BY_CODE[family.code], family)
                self.assertEqual((family.kind, str(family.store), family.reader, family.role,
                                  family.extension, family.named),
                                 (kind, store, reader, role, extension, named))
                self.assertEqual(family.prefix, f"des_{family.code}_")
                self.assertTrue(family.label.strip())
        self.assertEqual(len(provenance.FAMILIES_BY_CODE), 20)
        self.assertEqual(dict(provenance.FAMILIES_BY_CODE),
                         {family.code: family for family in (
                             *provenance.FAMILIES, *provenance.QUARRY_FAMILIES,
                             *provenance.ENTITY_FAMILIES)})

    def test_the_surface_of_an_entity_is_not_a_design_surface(self) -> None:
        """RF-015-04, P-2 (plan 015 §2.1): las superficies intermedias de una cadena no pueden
        llevar el papel ``design_surface``: la última de cada cadena la añade congelar (T32). El
        papel de la de una entidad es ``entity_surface`` y no lo lleva ninguna familia de la 013 ni
        de la 014; cada familia de las entidades tiene el suyo."""
        self.assertEqual(provenance.ENTITY_SURFACE_ROLE, "entity_surface")
        self.assertEqual(provenance.DESIGN_SURFACE_ROLE, "design_surface")
        roles = [family.role for family in provenance.ENTITY_FAMILIES]
        self.assertEqual(len(set(roles)), 5)
        self.assertNotIn(provenance.DESIGN_SURFACE_ROLE, roles)
        older = {family.role for family in (*provenance.FAMILIES, *provenance.QUARRY_FAMILIES)}
        self.assertEqual(set(roles) & older, set())
        self.assertEqual(provenance.FAMILIES_BY_CODE["psf"].role, provenance.ENTITY_SURFACE_ROLE)
        self.assertEqual([family.code for family in provenance.FAMILIES_BY_CODE.values()
                          if family.role == provenance.DESIGN_SURFACE_ROLE],
                         ["srf", "exp", "fin", "trn", "adj"])

    def test_the_roles_of_what_the_operations_consume(self) -> None:
        """RF-015-02, RF-015-15 (plan 015 §5.2.3): los papeles con que se consumen la capa de las
        plataformas, la superficie de partida, las de las entidades en las que se apoya y los datos
        de las entidades vivas; el de lo que consume la compilación de la 012 es el de la tabla que
        escribe la declaración."""
        self.assertEqual((provenance.ENTITY_LAYER_ROLE, provenance.SURFACE_ROLE,
                          provenance.SUPPORTED_ON_ROLE, provenance.ENTITY_ROLE),
                         ("entity_layer", "surface", "supported_on", "entity"))
        self.assertEqual(provenance.ENTITY_AXIS_LAYER_ROLE, "entity_axis_layer")
        self.assertEqual(provenance.DECLARED_ROLE, "constraints_declared")
        self.assertEqual(provenance.FAMILIES_BY_CODE["decl"].role, provenance.DECLARED_ROLE)
        self.assertEqual(provenance.FAMILIES_BY_CODE["epr"].role, provenance.ENTITY_ROLE)

    def test_names_locators_and_specs(self) -> None:
        """RF-008-17, D-34 de la 009: la superficie y los datos de una entidad se llaman
        ``des_<familia>_<nombre>`` y llevan el código de la versión en su ubicación; su
        ``DatasetSpec`` es de ``des``, sin selector y no editable en QGIS (RF-008-56)."""
        self.assertEqual(provenance.dataset_name("psf", NAME), "des_psf_plataforma_de_carga")
        self.assertEqual(provenance.dataset_locator("psf", NAME, "V02"),
                         "rasters/des_psf_plataforma_de_carga_v02.tif")
        self.assertEqual(provenance.dataset_locator("epr", "Plataforma Ñandú", "V01"),
                         "des_epr_plataforma_nandu_v01")
        self.assertEqual(provenance.dataset_locator("prp", NAME, "V10"),
                         "des_prp_plataforma_de_carga_v10")
        for code, (kind, store, reader, role, _extension, named) in FAMILIES.items():
            spec = provenance.dataset_spec(code, NAME if named else "", "V02", crs_epsg=25830)
            with self.subTest(family=code):
                self.assertIsInstance(spec, datasets.DatasetSpec)
                self.assertEqual((spec.module, spec.kind, str(spec.store), spec.reader, spec.role),
                                 ("des", kind, store, reader, role))
                self.assertEqual(spec.name, provenance.dataset_name(code, NAME if named else ""))
                self.assertEqual(spec.locator,
                                 provenance.dataset_locator(code, NAME if named else "", "V02"))
                self.assertFalse(spec.qgis_editable)
                self.assertIsNone(spec.input_uid)
                self.assertFalse(spec.immutable)
                self.assertEqual(spec.crs_epsg, 25830)

    def test_the_declared_table_and_the_layer_are_one_per_version(self) -> None:
        """RF-015-10, RF-015-27 (plan 015 §5.2.3: ``des_decl_<vNN>`` y ``des_enl_<vNN>``): sin el
        nombre de una operación, como las máscaras de la 012 (``gis_mskz_<vNN>``): el nombre es
        ``des_decl`` y la ubicación lleva el código de la versión; darles un nombre es un error del
        programa, y una familia con nombre sin él, el rechazo de siempre."""
        self.assertEqual(provenance.dataset_name("decl"), "des_decl")
        self.assertEqual(provenance.dataset_name("enl"), "des_enl")
        self.assertEqual(provenance.dataset_locator("decl", "", "V03"), "des_decl_v03")
        self.assertEqual(provenance.dataset_locator("enl", "", "V03"), "des_enl_v03")
        self.assertNotEqual(provenance.dataset_locator("decl", "", "V03"),
                            provenance.dataset_locator("decl", "", "V04"))
        for family in ("decl", "enl"):
            with self.subTest(family=family):
                with self.assertRaises(ValueError):
                    provenance.dataset_name(family, NAME)
        for family in ("psf", "epr", "prp"):
            with self.subTest(family=family):
                with self.assertRaises(Exception) as caught:
                    provenance.dataset_name(family)
                self.assertEqual(getattr(caught.exception, "code", ""),
                                 "gis.dataset_name_invalid")
        with self.assertRaises(ValueError):
            provenance.dataset_name("xyz")

    def test_two_entities_of_a_version_do_not_share_their_data(self) -> None:
        """RF-015-01: dos entidades de una versión (nombre único) tienen datos con nombre y ubicación
        distintos en cada familia con nombre; la misma, el mismo (el mismo nombre da el mismo
        dato)."""
        for family in ("psf", "epr", "prp"):
            with self.subTest(family=family):
                first = provenance.dataset_spec(family, NAME, "V01")
                second = provenance.dataset_spec(family, OTHER_NAME, "V01")
                again = provenance.dataset_spec(family, "  PLATAFORMA de carga ", "V01")
                self.assertNotEqual((first.name, first.locator), (second.name, second.locator))
                self.assertEqual((first.name, first.locator), (again.name, again.locator))


class EntityOperationTypesTest(unittest.TestCase):
    """Los tres tipos de operación de las entidades (plan 015 §5.2.3; RF-015-02)."""

    def test_three_version_operations(self) -> None:
        """RF-015-02, RF-008-24, RF-009-05, RF-009-11 (plan 015 §5.2.3): del módulo ``des``, versión
        1.0, de la versión, repetibles y reproducibles con 10⁻⁹ relativo; sin grupo acoplado. Van
        aparte de los de la 013 y la 014, que siguen como estaban, y están en
        ``OPERATION_TYPES_BY_NAME``."""
        self.assertEqual((provenance.PLATFORM, provenance.DECLARE_CONSTRAINTS,
                          provenance.ENTITY_LAYER), ENTITY_TYPES)
        self.assertEqual([t.op_type for t in provenance.ENTITY_OPERATION_TYPES],
                         list(ENTITY_TYPES))
        self.assertEqual(provenance.ENTITY_VERSION_TYPES, ENTITY_TYPES)
        self.assertEqual(provenance.ENTITY_REPRODUCIBLE, ENTITY_TYPES)
        self.assertEqual(provenance.OP_VERSION, "1.0")
        self.assertEqual(provenance.VERSION_TYPES, ("des.envelope", "des.stepped_design"))
        self.assertEqual(provenance.REPRODUCIBLE, ("des.envelope", "des.stepped_design"))
        self.assertEqual(len(provenance.QUARRY_VERSION_TYPES), 5)
        self.assertEqual(dict(provenance.OPERATION_TYPES_BY_NAME),
                         {t.op_type: t for t in (*provenance.OPERATION_TYPES,
                                                 *provenance.QUARRY_OPERATION_TYPES,
                                                 *provenance.ENTITY_OPERATION_TYPES)})
        for declared in provenance.ENTITY_OPERATION_TYPES:
            op_type = declared.op_type
            with self.subTest(op_type=op_type):
                self.assertIs(provenance.OPERATION_TYPES_BY_NAME[op_type], declared)
                self.assertTrue(declared.reproducible)
                built = provenance.operation_def(op_type, recompute, reproduce)
                self.assertIsInstance(built, contract.OperationDef)
                self.assertEqual((built.op_type, built.version, built.module, built.scope,
                                  built.repeatable, built.group),
                                 (op_type, "1.0", "des", "version", True, None))
                self.assertIs(built.recompute, recompute)
                self.assertIs(built.reproduce, reproduce)
                self.assertEqual(built.figure_tolerance, contract.Tolerance(relative=1e-9))
                self.assertEqual(built.settings, declared.settings)
                self.assertEqual(built.commands, declared.commands)
                self.assertTrue(declared.label_msgid.strip())

    def test_entity_operation_defs_need_the_functions_of_every_type(self) -> None:
        """RF-008-26, RF-009-11: ``entity_operation_defs`` da los tres en su orden con el recálculo
        y la reproducción de cada uno (ni de más ni de menos)."""
        built = provenance.entity_operation_defs({t: recompute for t in ENTITY_TYPES},
                                                 {t: reproduce for t in ENTITY_TYPES})
        self.assertEqual([item.op_type for item in built], list(ENTITY_TYPES))
        every = {t: recompute for t in ENTITY_TYPES}
        same = {t: reproduce for t in ENTITY_TYPES}
        for bad_recompute, bad_reproduce in (
                ({t: recompute for t in ENTITY_TYPES[:2]}, same),
                (every, {t: reproduce for t in ENTITY_TYPES[1:]}),
                ({**every, "des.quarry": recompute}, same),
                (every, {**same, "des.envelope": reproduce})):
            with self.subTest(recompute=sorted(bad_recompute), reproduce=sorted(bad_reproduce)):
                with self.assertRaises(ValueError):
                    provenance.entity_operation_defs(bad_recompute, bad_reproduce)

    def test_what_each_operation_writes(self) -> None:
        """RF-015-01, RF-015-10, RF-015-27 (plan 015 §5.2.3): la plataforma, su superficie, su
        tabla y su informe; la declaración, la tabla de las restricciones declaradas; la capa de
        entidades, la capa para QGIS."""
        outputs = {t.op_type: t.outputs for t in provenance.ENTITY_OPERATION_TYPES}
        self.assertEqual(outputs, {"des.platform": ("psf", "epr", "prp"),
                                   "des.declare_constraints": ("decl",),
                                   "des.entity_layer": ("enl",)})
        for produced in outputs.values():
            for code in produced:
                self.assertIn(code, provenance.FAMILIES_BY_CODE)

    def test_the_declared_settings_are_names_only(self) -> None:
        """Plan 015 §5.2.2: la definición de una entidad son sus parámetros, no sus ajustes: los
        tres tipos solo guardan nombres y códigos en sus ajustes (la capa, los campos, la entidad),
        que no se declaran (no se enseñan)."""
        self.assertEqual(provenance.PLATFORM_SETTINGS, ())
        for declared in provenance.ENTITY_OPERATION_TYPES:
            with self.subTest(op_type=declared.op_type):
                self.assertEqual(declared.settings, ())

    def test_the_figures_of_each_type(self) -> None:
        """RF-015-24, RF-015-15, RF-015-10 (plan 015 §5.2.3): las doce cifras de la plataforma y las
        de lo apoyado en la plataforma; la declaración, su recuento; la capa de entidades, ninguna."""
        figures = {t.op_type: [f.key for f in t.figures] for t in provenance.ENTITY_OPERATION_TYPES}
        self.assertEqual(figures, {
            "des.platform": [*PLATFORM_FIGURES, "des.supported_m3"],
            "des.declare_constraints": ["des.declared_count"],
            "des.entity_layer": []})

    def test_labels_have_their_spanish(self) -> None:
        """RF-008-31 (principio 10): el nombre de cada tipo y de cada cifra de las entidades es un
        ``msgid`` en inglés con su español en ``core/i18n/messages.toml``."""
        table = i18n.load_messages()
        wanted = [declared.label_msgid for declared in provenance.ENTITY_OPERATION_TYPES]
        wanted += [figure.label_msgid for figure in provenance.ENTITY_FIGURES]
        self.assertEqual(len(wanted), len(set(wanted)), "cada nombre, el suyo")
        for msgid in wanted:
            with self.subTest(msgid=msgid):
                self.assertEqual(set(msgid) & SPANISH_LETTERS, set(), "msgid en inglés")
                self.assertEqual(i18n.placeholders(msgid), set())
                self.assertIn(msgid, table)
                self.assertNotEqual(table[msgid], msgid)

    def test_their_commands_are_in_the_catalog(self) -> None:
        """RF-008-61 (ADR-0025 §2): la orden de cada tipo está en el catálogo, de ``des``. Hasta
        que la T15 le dé su clave definitiva (``geoblender.des_create_platform``), es la de la
        entrada de R-36 que ya trae el catálogo («Plataforma»); la T31 entrega la entrada."""
        self.assertEqual(provenance.PLATFORM_COMMAND, PLATFORM_COMMAND)
        cat = import_geoblender("core.catalog").load()
        for declared in provenance.ENTITY_OPERATION_TYPES:
            with self.subTest(op_type=declared.op_type):
                self.assertEqual(declared.commands, (PLATFORM_COMMAND,))
                command = cat.commands[PLATFORM_COMMAND]
                self.assertEqual((command.entry, command.module), ("R-36", "des"))

    def test_registration_leaves_no_trace(self) -> None:
        """RF-008-17 (principio 8): lo de las entidades se registra sin chocar con otra cosa y se
        quita sin dejar nada."""
        before = snapshot()
        with registered(*entity_definitions()):
            for op_type in ENTITY_TYPES:
                self.assertIn(op_type, contract.OPERATIONS)
            for figure in provenance.ENTITY_FIGURES:
                self.assertIs(contract.FIGURES[figure.key], figure)
        self.assertEqual(snapshot(), before)


class EntitySettingsTest(unittest.TestCase):
    """Lo que guarda cada operación en sus ajustes y cómo se lee (``gb_operation.settings``)."""

    def test_the_platform_settings_round_trip(self) -> None:
        """RF-015-02, RF-015-19 (plan 015 §5.2.1): los ajustes de la plataforma (JSON sin rutas)
        llevan su nombre, su código y los campos de su capa; con los valores de sus parámetros se
        vuelve a pedir la misma plataforma: al recalcularla y al reproducirla. Con una capa de
        polígonos, también la capa y el campo de su eje."""
        for request in (platform_request(),
                        platform_request(fields=polygon_fields(), feature="Explanada con eje",
                                         support="des_srf_cantera", max_slope_pct=8.0,
                                         protect=True, guard_m=4.0, reason="Taller"),
                        platform_request(fields=model.PlatformFields(
                            "gis_fea_plataformas_poligonos", "cota", "pend"), mode="cut_fill",
                            metric="chamfer5", start="entity:PLT-003")):
            with self.subTest(layer=request.layer, mode=request.mode):
                settings = provenance.platform_settings(request, CODE)
                self.assertEqual(json.loads(json.dumps(settings)), settings)
                self.assertEqual(settings["name"], NAME)
                self.assertEqual(provenance.platform_code(settings), CODE)
                values = provenance.platform_values(CODE, keyed(CODE, values_of(request)))
                self.assertEqual(values, values_of(request))
                self.assertEqual(provenance.platform_request(settings, values), request)

    def test_the_settings_do_not_repeat_the_parameters(self) -> None:
        """Plan 015 §5.2.2 (ADR-0025 §5): la capa, la geometría y todo lo que es un parámetro de la
        entidad no se duplica en los ajustes (cambiar un parámetro cambiaría uno solo): los ajustes
        llevan el nombre, el código y los campos de la capa."""
        request = platform_request(fields=polygon_fields(), mode="cut_fill", max_slope_pct=8.0)
        settings = provenance.platform_settings(request, CODE)
        self.assertEqual(sorted(settings), ["code", "fields", "name"])
        self.assertEqual(sorted(settings["fields"]),
                         ["axis_field", "axis_layer", "gradient_field", "start_level_field",
                          "width_field"])
        self.assertEqual(settings["fields"]["axis_layer"], "gis_fea_plataformas_ejes")
        self.assertIsNone(settings["fields"]["width_field"])
        text = json.dumps(settings)
        for forbidden in ("cut_fill", "35.0", "gis_fea_plataformas_poligonos", GROUND):
            self.assertNotIn(forbidden, text)

    def test_the_parameter_wins_over_what_the_settings_do_not_say(self) -> None:
        """RF-015-08, RF-015-16: la capa y la geometría salen de los parámetros de la entidad: un
        parámetro cambiado (otra capa, otra geometría) es lo que repite la operación; sin ellos, o
        con un valor que no es de su tipo, es un error del programa nombrando el campo."""
        settings = provenance.platform_settings(platform_request(), CODE)
        values = values_of(platform_request())
        again = provenance.platform_request(settings, {**values, "layer": "gis_fea_otra",
                                                      "feature": "7"})
        self.assertEqual((again.layer, again.feature), ("gis_fea_otra", "7"))
        self.assertEqual(again.fields.width_field, "ancho")
        for key in ("layer", "feature", "start"):
            with self.subTest(missing=key):
                with self.assertRaises(ValueError) as caught:
                    provenance.platform_request(
                        settings, {k: v for k, v in values.items() if k != key})
                self.assertIn(key, str(caught.exception))
        with self.assertRaises(ValueError) as caught:
            provenance.platform_request(settings, {**values, "edge_angle_deg": "treinta"})
        self.assertIn("edge_angle_deg", str(caught.exception))
        with self.assertRaises(ValueError):
            provenance.platform_request(settings, {**values, "protect": "sí"})
        with self.assertRaises(ValueError):
            provenance.platform_request(settings, {**values, "no_es_un_valor": 1.0})
        for bad in ({}, {"name": NAME}, {"name": NAME, "code": CODE},
                    {"name": "", "code": CODE, "fields": settings["fields"]},
                    {**settings, "fields": {"start_level_field": "cota"}}, "no es un diccionario"):
            with self.subTest(settings=bad):
                with self.assertRaises(ValueError):
                    provenance.platform_request(bad, values)  # type: ignore[arg-type]
        for bad_code in ("P1", "plt-001", "", None):
            with self.subTest(code=bad_code):
                with self.assertRaises((ValueError, TypeError)):
                    provenance.platform_settings(platform_request(), bad_code)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            provenance.platform_code({"name": NAME})

    def test_the_values_of_one_entity_are_picked_by_its_code(self) -> None:
        """RF-015-01: de un conjunto de parámetros resueltos (clave completa → valor) se toman los
        de la entidad por su código, sin los de otra ni los del proyecto."""
        mixed = {**keyed(CODE, {"mode": "cut", "reach_m": 60.0}),
                 **keyed(OTHER_CODE, {"mode": "cut_fill"}), THICKNESS: 0.1}
        self.assertEqual(provenance.platform_values(CODE, mixed),
                         {"mode": "cut", "reach_m": 60.0})
        self.assertEqual(provenance.platform_values(OTHER_CODE, mixed), {"mode": "cut_fill"})
        self.assertEqual(provenance.platform_values("PLT-009", mixed), {})
        with self.assertRaises(ValueError):
            provenance.platform_values("P1", mixed)

    def test_the_entities_of_a_declaration_and_of_the_layer(self) -> None:
        """RF-015-10, RF-015-27: la declaración y la capa de entidades guardan en sus ajustes las
        entidades que recogen (código y nombre, por orden), y se leen de vuelta; dos con el mismo
        código, un código que no lo es o un nombre en blanco son un error del programa."""
        pairs = ((CODE, NAME), (OTHER_CODE, OTHER_NAME))
        for make in (provenance.declare_settings, provenance.entity_layer_settings):
            with self.subTest(make=make.__name__):
                settings = make(pairs)
                self.assertEqual(json.loads(json.dumps(settings)), settings)
                self.assertEqual(provenance.settings_entities(settings), pairs)
                self.assertEqual(provenance.settings_entities(make(())), ())
                for bad in (((CODE, NAME), (CODE, OTHER_NAME)), (("P1", NAME),),
                            ((CODE, "  "),), ((CODE, None),)):
                    with self.subTest(bad=bad):
                        with self.assertRaises((ValueError, TypeError)):
                            make(bad)  # type: ignore[arg-type]
        for bad_settings in ({}, {"entities": "PLT-001"}, {"entities": [{"code": CODE}]},
                             {"entities": [["PLT-001", NAME]]}, "no es un diccionario"):
            with self.subTest(settings=bad_settings):
                with self.assertRaises(ValueError):
                    provenance.settings_entities(bad_settings)  # type: ignore[arg-type]


class EntityInputsAndParamsTest(unittest.TestCase):
    """Lo que consume cada operación, con su papel, y los parámetros que lee."""

    def test_the_inputs_of_a_platform(self) -> None:
        """RF-015-02, RF-015-04, RF-015-06, RF-015-15 (plan 015 §5.2.3): la capa de las plataformas
        (``entity_layer``), la superficie de partida ya resuelta (``surface``), las máscaras de la
        versión con sus papeles y, al crear, las superficies de las entidades en las que se apoya
        (``supported_on``), sin repetir; con un polígono de eje enlazado, también la capa del eje."""
        masks = (operations.Use("gis_msk", "classes"), operations.Use("gis_mskz", "zones"))
        found = provenance.platform_inputs(platform_request(), GROUND, masks)
        self.assertEqual([(use.item, use.role) for use in found], [
            ("gis_fea_plataformas_ejes", "entity_layer"), (GROUND, "surface"),
            ("gis_msk", "classes"), ("gis_mskz", "zones")])
        supports = ("des_psf_taller", "des_psf_carga", "des_psf_taller")
        found = provenance.platform_inputs(platform_request(fields=polygon_fields()),
                                           "des_psf_previa", masks, supports)
        self.assertEqual([(use.item, use.role) for use in found], [
            ("gis_fea_plataformas_poligonos", "entity_layer"),
            ("gis_fea_plataformas_ejes", "entity_axis_layer"), ("des_psf_previa", "surface"),
            ("gis_msk", "classes"), ("gis_mskz", "zones"),
            ("des_psf_taller", "supported_on"), ("des_psf_carga", "supported_on")])
        for use in found:
            self.assertEqual(str(use.kind), "dataset")
            self.assertIsNone(use.frozen)

    def test_the_inputs_of_a_platform_need_their_names(self) -> None:
        """RF-015-09: sin el nombre de la superficie de partida (o con uno en blanco) o de una de
        las superficies de apoyo, es un error del programa (``ValueError``)."""
        for start in ("", "  ", None):
            with self.subTest(start=start):
                with self.assertRaises(ValueError):
                    provenance.platform_inputs(platform_request(), start)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            provenance.platform_inputs(platform_request(), GROUND, (), ("",))
        with self.assertRaises(TypeError):
            provenance.platform_inputs(platform_request(), GROUND, (), "des_psf_taller")

    def test_the_inputs_of_the_declaration_and_of_the_layer(self) -> None:
        """RF-015-10, RF-015-27 (plan 015 §5.2.3): los datos ``des_epr_`` de las entidades vivas
        (papel ``entity``), por el nombre de cada entidad y sin repetir; ninguna entrada de la capa
        del proyecto."""
        for make in (provenance.declare_inputs, provenance.entity_layer_inputs):
            with self.subTest(make=make.__name__):
                found = make([NAME, OTHER_NAME, NAME])
                self.assertEqual([(use.item, use.role) for use in found], [
                    ("des_epr_plataforma_de_carga", "entity"),
                    ("des_epr_plataforma_de_taller", "entity")])
                self.assertEqual(make([]), ())
                with self.assertRaises(Exception):
                    make([""])
                with self.assertRaises(TypeError):
                    make(NAME)  # type: ignore[arg-type]

    def test_the_parameters_a_platform_reads(self) -> None:
        """RF-015-02, RF-015-16, RF-015-23 (plan 015 §5.2.2): una plataforma de líneas lee los
        valores que cambian su resultado (la capa, la geometría, la partida, el ancho, la cota y la
        pendiente de la rasante, el modo y lo del borde y la contrapendiente) y, del proyecto, la
        tolerancia de cara y el umbral de aviso de la 013, el espesor mínimo de la 012 y el salto
        creado de la 014. No lee su nombre ni lo que declara (eso lo lee la declaración)."""
        found = provenance.platform_params(CODE, platform_request())
        own = [design_params.entity_key(CODE, name) for name in (
            "layer", "feature", "start", "width_m", "start_level_m", "gradient_pct", "mode",
            "edge_angle_deg", "reach_m", "mesh_factor", "counter_tol_m", "metric")]
        self.assertEqual(found, (*own, *COMMON_PARAMS))
        self.assertEqual(provenance.PLATFORM_COMMON_PARAMS, COMMON_PARAMS)
        self.assertEqual(len(set(found)), len(found))
        for name in ("name", "protect", "guard_m", "reason", "support", "supports",
                     "max_slope_pct"):
            self.assertNotIn(design_params.entity_key(CODE, name), found)

    def test_the_optional_parameters_are_read_only_when_they_have_a_value(self) -> None:
        """RF-015-08, RF-015-15 (``begin_operation``: un parámetro sin valor ni valor por defecto es
        un rechazo): una plataforma de polígonos no lee ancho; la pendiente máxima y la superficie
        de apoyo, solo si las lleva; y las dependencias declaradas (``supports``), solo si la
        entidad las tiene."""
        polygon = provenance.platform_params(CODE, platform_request(fields=polygon_fields()))
        self.assertNotIn(design_params.entity_key(CODE, "width_m"), polygon)
        full = provenance.platform_params(
            CODE, platform_request(support="des_srf_cantera", max_slope_pct=8.0), supports=True)
        for name in ("support", "max_slope_pct", "supports", "width_m"):
            self.assertIn(design_params.entity_key(CODE, name), full)
        order = [key.rsplit(".", 1)[1] for key in full[:-len(COMMON_PARAMS)]]
        self.assertEqual(order, ["layer", "feature", "start", "support", "width_m",
                                 "start_level_m", "gradient_pct", "max_slope_pct", "mode",
                                 "edge_angle_deg", "reach_m", "mesh_factor", "counter_tol_m",
                                 "metric", "supports"])
        other = provenance.platform_params(OTHER_CODE, platform_request())
        self.assertTrue(all(".plt_002." in key for key in other[:-len(COMMON_PARAMS)]))

    def test_every_parameter_a_platform_reads_is_declared(self) -> None:
        """ADR-0027, RF-015-01: cada clave de la entidad que lee es de una de las familias de
        ``ENTITY_FAMILIES`` y cada una del proyecto, de una definición de ``des`` o de ``res``."""
        found = provenance.platform_params(
            CODE, platform_request(support="des_srf_cantera", max_slope_pct=8.0), supports=True)
        patterns = {family.pattern for family in design_params.ENTITY_FAMILIES}
        project = {definition.key for definition in (*design_params.DEFINITIONS,
                                                     *design_params.QUARRY_DEFINITIONS,
                                                     *res_provenance.VERIFY_DEFINITIONS)}
        for key in found:
            with self.subTest(key=key):
                if key.startswith("des.platform."):
                    last = key.rsplit(".", 1)[1]
                    self.assertIn(f"des.platform.{{e}}.{last}", patterns)
                else:
                    self.assertIn(key, project)

    def test_the_parameters_the_declaration_reads(self) -> None:
        """RF-015-10, RF-015-12, RF-015-17 (plan 015 §5.2.3): por cada entidad, su nombre (el motivo
        generado lo lleva) y si protege; de las que protegen, su modo (la «en corte y relleno» que
        protege se rechaza) y su resguardo; y su motivo, solo de las que lo editaron."""
        key = design_params.entity_key
        found = provenance.declare_params([CODE, OTHER_CODE], protecting=[OTHER_CODE],
                                          reasoned=[OTHER_CODE])
        self.assertEqual(found, (key(CODE, "name"), key(CODE, "protect"), key(OTHER_CODE, "name"),
                                 key(OTHER_CODE, "protect"), key(OTHER_CODE, "mode"),
                                 key(OTHER_CODE, "guard_m"), key(OTHER_CODE, "reason")))
        self.assertEqual(provenance.declare_params([CODE]),
                         (key(CODE, "name"), key(CODE, "protect")))
        self.assertEqual(provenance.declare_params([]), ())
        with self.assertRaises(ValueError):
            provenance.declare_params([CODE], protecting=[OTHER_CODE])
        with self.assertRaises(ValueError):
            provenance.declare_params([CODE], reasoned=[OTHER_CODE])
        with self.assertRaises(ValueError):
            provenance.declare_params(["P1"])


class EntityFiguresTest(unittest.TestCase):
    """Las cifras de las entidades (plan 015 §5.2.3; RF-015-15, RF-015-24)."""

    def test_the_figures_of_the_platform(self) -> None:
        """RF-015-24 (plan 015 §5.2.3): las doce cifras, en su orden, cada una con su unidad del
        catálogo: el área, las longitudes del eje y de la huella, las cotas de la rasante en los
        extremos (que pueden ser negativas), el corte y el relleno de la huella y del borde, la
        altura máxima de la pared del borde y, de lo que no queda en la rasante, el área y la
        diferencia máxima. Ninguna dice «grade» (glosario §14)."""
        self.assertEqual([f.key for f in provenance.PLATFORM_FIGURES], list(PLATFORM_FIGURES))
        for figure in provenance.PLATFORM_FIGURES:
            unit, negative = PLATFORM_FIGURES[figure.key]
            with self.subTest(figure=figure.key):
                self.assertEqual((figure.unit, figure.allow_negative, figure.allow_zero),
                                 (unit, negative, True))
                self.assertIn(figure.unit, units.UNITS)
                self.assertNotIn("grade", figure.key)
                self.assertNotIn("grade", figure.label_msgid.lower().replace("upgrade", ""))
        self.assertEqual([(f.key, f.unit) for f in provenance.SUPPORT_FIGURES],
                         [("des.supported_m3", "m3")])
        self.assertEqual([(f.key, f.unit) for f in provenance.DECLARE_FIGURES],
                         [("des.declared_count", "-")])
        self.assertEqual(provenance.ENTITY_FIGURES,
                         (*provenance.PLATFORM_FIGURES, *provenance.SUPPORT_FIGURES,
                          *provenance.DECLARE_FIGURES))
        self.assertEqual(provenance.SUPPORTED_M3, "des.supported_m3")
        self.assertEqual(provenance.DECLARED_COUNT, "des.declared_count")
        every = {*(f.key for f in provenance.FIGURES), *(f.key for f in provenance.QUARRY_FIGURES)}
        self.assertEqual({f.key for f in provenance.ENTITY_FIGURES} & every, set())

    def test_the_figures_carry_the_code_of_the_entity_as_scope(self) -> None:
        """RF-015-24, RF-009-20 (plan 015 §5.2.3, ``figure_scope``: ``entity``): la cifra vigente de
        una clave es la última de cada ámbito: el de las entidades es el nombre de su operación (el
        que da el dato, único en la versión) y el código de la entidad, que no cambia al
        renombrarla. Otra entidad, otro ámbito."""
        scope = provenance.entity_figure_scope(NAME, CODE)
        self.assertEqual(scope, {"name": "plataforma_de_carga", "entity": CODE})
        self.assertEqual(provenance.ENTITY_SCOPE_KEY, "entity")
        self.assertEqual(provenance.entity_figure_scope("  PLATAFORMA de CARGA ", CODE), scope)
        keys = {figures_mod.scope_key(provenance.entity_figure_scope(name, code))
                for name, code in ((NAME, CODE), (OTHER_NAME, OTHER_CODE), (NAME, OTHER_CODE))}
        self.assertEqual(len(keys), 3)
        self.assertNotIn(figures_mod.scope_key(provenance.figure_scope(NAME)), keys)
        for bad in ("P1", "plt-001", "", None):
            with self.subTest(code=bad):
                with self.assertRaises((ValueError, TypeError)):
                    provenance.entity_figure_scope(NAME, bad)  # type: ignore[arg-type]
        with self.assertRaises(Exception) as caught:
            provenance.entity_figure_scope("¿¡!?", CODE)
        self.assertEqual(getattr(caught.exception, "code", ""), "gis.dataset_name_invalid")

    def test_the_platform_figures_are_built_in_order(self) -> None:
        """RF-015-24: ``platform_figures`` da las cifras CALCULADO de la entidad en el orden de
        ``PLATFORM_FIGURES``, con su unidad y su ámbito; una que no existe (``None``: sin celdas
        fuera de la rasante no hay diferencia máxima) no se registra, y las cotas admiten
        negativos."""
        found = provenance.platform_figures(NAME, CODE, GOOD_VALUES)
        self.assertEqual([(s.key, s.value, s.unit) for s in found],
                         [(key, GOOD_VALUES[key], unit) for key, (unit, _n) in
                          PLATFORM_FIGURES.items()])
        for spec in found:
            self.assertEqual((spec.kind, dict(spec.scope), spec.parameter_key),
                             ("CALCULADO", provenance.entity_figure_scope(NAME, CODE), None))
            self.assertIs(type(spec.value), float)
        quiet = {**GOOD_VALUES, "des.plat_below_m2": 0.0, "des.plat_below_max_m": None}
        found = provenance.platform_figures(NAME, CODE, quiet)
        self.assertNotIn("des.plat_below_max_m", [spec.key for spec in found])
        self.assertEqual(len(found), len(PLATFORM_FIGURES) - 1)

    def test_no_platform_figure_can_be_nan_infinite_or_missing(self) -> None:
        """RF-013-17, RF-015-24: un valor que no es finito, un tipo que no es un número, una cifra
        que no es de la plataforma o una de las doce sin dar (ni siquiera ``None``) es un error del
        programa, nombrando la cifra; ninguna se registra a medias."""
        for key in PLATFORM_FIGURES:
            for bad in (math.nan, math.inf, -math.inf):
                with self.subTest(key=key, value=bad):
                    with self.assertRaises(ValueError) as caught:
                        provenance.platform_figures(NAME, CODE, {**GOOD_VALUES, key: bad})
                    self.assertIn(key, str(caught.exception))
            with self.subTest(key=key, missing=True):
                with self.assertRaises(ValueError) as caught:
                    provenance.platform_figures(
                        NAME, CODE, {k: v for k, v in GOOD_VALUES.items() if k != key})
                self.assertIn(key, str(caught.exception))
        with self.assertRaises(TypeError):
            provenance.platform_figures(NAME, CODE, {**GOOD_VALUES, "des.plat_area_m2": "mucho"})
        with self.assertRaises(ValueError):
            provenance.platform_figures(NAME, CODE, {**GOOD_VALUES, "des.supported_m3": 1.0})
        with self.assertRaises(ValueError):
            provenance.platform_figures(NAME, CODE, {**GOOD_VALUES, "des.plat_area_m2": -1.0})

    def test_the_supported_volumes_are_one_figure_per_entity(self) -> None:
        """RF-015-15 (plan 015 §5.2.3: «una por entidad apoyada»; ADR-0030 §4): la cifra
        ``des.supported_m3`` de la operación que rellena lleva como ámbito su nombre y el código
        de **cada entidad en la que se apoya**, con el volumen apoyado (m³; cero, si lo declara el
        usuario); por orden de código. Sin entidades, ninguna."""
        found = provenance.supported_figures("Solo relleno V01", {OTHER_CODE: 0.0, CODE: 1_234.5})
        self.assertEqual([(s.key, s.value, s.unit, dict(s.scope)) for s in found], [
            ("des.supported_m3", 1_234.5, "m3", {"name": "solo_relleno_v01", "entity": CODE}),
            ("des.supported_m3", 0.0, "m3", {"name": "solo_relleno_v01", "entity": OTHER_CODE})])
        self.assertEqual(provenance.supported_figures("X", {}), ())
        for bad in (math.nan, math.inf, -1.0):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    provenance.supported_figures("X", {CODE: bad})
        with self.assertRaises((ValueError, TypeError)):
            provenance.supported_figures("X", {"P1": 1.0})

    def test_the_declaration_counts_what_it_declares(self) -> None:
        """RF-015-10: la cifra ``des.declared_count`` es el número de restricciones que declara la
        versión (un entero no negativo, cero si ninguna entidad protege), sin ámbito: una
        declaración por versión."""
        (spec,) = provenance.declare_figures(2)
        self.assertEqual((spec.key, spec.value, spec.unit, dict(spec.scope)),
                         ("des.declared_count", 2.0, "-", {}))
        self.assertEqual(provenance.declare_figures(0)[0].value, 0.0)
        for bad in (-1, 1.5, True, math.nan, "dos"):
            with self.subTest(count=bad):
                with self.assertRaises((ValueError, TypeError)):
                    provenance.declare_figures(bad)  # type: ignore[arg-type]


class EntityRegistrationTest(efx.EntityProjectCase):
    """Lo declarado, en un proyecto real: la 008 acepta los ajustes, las entradas, los parámetros y
    las cifras que arman estas funciones (V01 de la cantera sintética de la 014 con sus capas de
    plataformas y sus máscaras al día) y el registro de las entidades de la T03 reconoce la
    operación."""

    STEP_M = qfx.COARSE_STEP_M
    version: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_definitions((*design_params.DEFINITIONS,
                                          *design_params.QUARRY_DEFINITIONS))
        cls.addClassCleanup(core_params.unregister_definitions, "des")
        core_params.register_definitions(res_provenance.VERIFY_DEFINITIONS)
        cls.addClassCleanup(core_params.unregister_definitions, "res")
        core_params.register_families(design_params.ENTITY_FAMILIES)
        cls.addClassCleanup(core_params.unregister_families, "des")
        cls.enterClassContext(registered(*entity_definitions()))
        cls.version = cls.v1

    def declare(self, code: str, name: str, start: str, *, width: bool = True) -> None:
        """Da de alta en V01 los parámetros de la entidad ``code`` (los que lee la plataforma de una
        capa de líneas y si protege): lo que escribe la orden al crear, también los valores por
        defecto. Sin su fila de versión, ``begin_operation`` registraría el valor por defecto de un
        parámetro de una entidad **en el proyecto** (y la entidad llegaría a toda versión)."""
        values: dict[str, Any] = {
            "name": name, "layer": efx.AXES_LAYER, "feature": "1", "start": start,
            "start_level_m": 230.0, "gradient_pct": 1.0, "mode": "cut", "edge_angle_deg": 35.0,
            "reach_m": 60.0, "mesh_factor": 1.0, "counter_tol_m": 0.1, "metric": "exact",
            "protect": False}
        if width:
            values["width_m"] = 40.0
        store = core_params.ParameterStore(self.project)
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            for param, value in values.items():
                store.create(conn, design_params.entity_key(code, param), value,
                             kind="ADOPTADO", source="Prueba de las declaraciones",
                             source_kind="person", decided_by="Samuel (IMGA)",
                             reason="Prueba de la 015", version=self.version.code)

    def begin(self, op_type: str, **values: Any) -> Any:
        self.clock.advance(minutes=1)
        handle = operations.begin_operation(self.project, op_type, executor="blender",
                                            version=self.version.uid, **values)
        self.addCleanup(cancel_if_running, handle)
        return handle

    def named(self, uses: Any) -> list[tuple[str, str]]:
        """Lo que consume ``uses`` como lo da ``roles``: el nombre del dato (las máscaras dan su
        uid) y su papel."""
        found = []
        for use in uses:
            rows = self.query("SELECT name FROM gb_dataset WHERE uid = ? OR name = ? "
                              "ORDER BY fid DESC", use.item, use.item)
            found.append((str(rows[0][0]), use.role))
        return found

    def roles(self, handle: Any) -> list[tuple[str, str]]:
        return [(str(item), str(role)) for item, role in self.query(
            "SELECT d.name, io.role FROM gb_operation_io AS io "
            "JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'in' ORDER BY io.fid", handle.uid)]

    def write_tables(self, handle: Any, name: str, figures: Any = ()) -> list[Any]:
        """Escribe la tabla de la entidad y su informe como los datos reales de las familias
        ``epr`` y ``prp`` (con un valor sintético; la superficie, un GeoTIFF, no se escribe aquí) y
        completa la operación."""
        specs = []
        with self.project.write_transaction() as conn:
            for family in ("epr", "prp"):
                spec = provenance.dataset_spec(family, name, self.version.code)
                gpkg_base.create_attribute_table(
                    conn, spec.locator, [gpkg_base.ColumnDef("value", "DOUBLE")], spec.name,
                    "Dato sintético de la prueba de las declaraciones (spec 015)")
                conn.execute(f'INSERT INTO "{spec.locator}" (value) VALUES (1.5)')
                specs.append(spec)
            handle.complete(conn, outputs=specs, figures=figures)
        return specs

    def make(self, code: str, name: str, start: str, *, surface: str,
             supports: tuple[str, ...] = ()) -> tuple[Any, Any]:
        """La plataforma ``code`` de nombre ``name`` que parte de ``start`` (el valor de su parámetro
        ``start``; ``surface`` es el dato que consume como superficie de partida), empezada con lo
        que arman las funciones de la T04: su petición y su operación «en curso»."""
        self.declare(code, name, start)
        request = platform_request(name=name, fields=line_fields(layer=efx.AXES_LAYER),
                                   start=start)
        handle = self.begin(
            "des.platform", settings=provenance.platform_settings(request, code),
            inputs=provenance.platform_inputs(request, surface, self.masks().uses(), supports),
            params=provenance.platform_params(code, request))
        return request, handle

    def test_the_008_accepts_the_platform_as_declared(self) -> None:
        """RF-015-01, RF-015-02, RF-008-05 (plan 015 §5.2.3): ``begin_operation`` registra la
        plataforma con los ajustes de :func:`platform_settings`, las entradas de
        :func:`platform_inputs` con sus papeles (la capa, la partida y las máscaras) y los
        parámetros de :func:`platform_params` (los de la entidad, con el valor de la versión, y los
        del proyecto); lo registrado vuelve a pedir la misma plataforma; al completarla, con sus
        datos y sus cifras, el registro de las entidades la reconoce, al día, con su operación."""
        self.declare(CODE, NAME, qfx.START_DATASET)
        request = platform_request(name=NAME, fields=line_fields(layer=efx.AXES_LAYER),
                                   start=qfx.START_DATASET)
        masks = self.masks()
        settings = provenance.platform_settings(request, CODE)
        inputs = provenance.platform_inputs(request, qfx.START_DATASET, masks.uses())
        keys = provenance.platform_params(CODE, request)
        handle = self.begin("des.platform", settings=settings, inputs=inputs, params=keys)
        self.assertEqual(self.roles(handle), self.named(inputs))
        self.assertEqual(self.roles(handle)[:2], [(efx.AXES_LAYER, "entity_layer"),
                                                  (qfx.START_DATASET, "surface")])
        ((text,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", handle.uid)
        self.assertEqual(json.loads(text), settings)
        self.assertEqual([item.key for item in handle.params], list(keys))
        scopes = {item.key: item.scope for item in handle.params}
        for key in keys:
            self.assertEqual(scopes[key], "version" if key.startswith("des.platform.")
                             else "project", key)
        recorded = {item.key: json.loads(item.value_json) for item in handle.params}
        again = provenance.platform_request(
            json.loads(text), provenance.platform_values(CODE, recorded))
        self.assertEqual(again, request)

        specs = self.write_tables(handle, NAME, provenance.platform_figures(
            NAME, CODE, GOOD_VALUES))
        self.assertEqual([spec.role for spec in specs], ["entity", "entity_report"])
        found = self.query("SELECT key, unit, kind, scope FROM gb_figure WHERE operation_uid = ? "
                           "ORDER BY rowid", handle.uid)
        self.assertEqual([(key, unit, kind) for key, unit, kind, _scope in found],
                         [(key, unit, "CALCULADO") for key, (unit, _n) in
                          PLATFORM_FIGURES.items()])
        self.assertEqual({json.loads(scope)["entity"] for *_rest, scope in found}, {CODE})

        entry = entities.registry(self.project, self.version.uid).get(CODE)
        self.assertIsNotNone(entry)
        self.assertEqual((entry.record.name, entry.record.start, entry.operation_uid),
                         (NAME, qfx.START_DATASET, handle.uid))
        self.assertEqual(entry.record.state, entities.EntityState.CURRENT)

    def test_the_008_accepts_the_supports_and_the_chain(self) -> None:
        """RF-015-04, RF-015-15 (plan 015 §5.2.3): una segunda plataforma consume como ``surface`` el
        dato de la primera y, como ``supported_on``, los de las entidades en las que se apoya; los
        descarta la 008 como cualquier dato y el registro dice «apoyo retirado» (el contrato de la
        T03 con los papeles de esta tarea). La superficie de una entidad es un GeoTIFF: la prueba usa
        la tabla de la entidad, y lo que mira es el papel."""
        first, second = "Plataforma A", "Plataforma B"
        _request, previous = self.make("PLT-011", first, qfx.START_DATASET,
                                       surface=qfx.START_DATASET)
        (stand_in, _report) = self.write_tables(previous, first)
        masks = self.masks().uses()
        request, later = self.make("PLT-012", second, "entity:PLT-011", surface=stand_in.name,
                                   supports=(stand_in.name,))
        self.assertEqual(request.start, "entity:PLT-011")
        self.assertEqual(self.roles(later), [
            (efx.AXES_LAYER, "entity_layer"), (stand_in.name, "surface"),
            *self.named(masks), (stand_in.name, "supported_on")])
        self.write_tables(later, second)
        found = entities.registry(self.project, self.version.uid)
        self.assertEqual(found.get("PLT-012").record.state, entities.EntityState.CURRENT)
        self.assertEqual(found.get("PLT-012").record.start, "entity:PLT-011")
        dataset_registry = import_geoblender("core.datasets.registry")
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            uids = [dataset_registry.get(conn, provenance.dataset_name(family, first),
                                         version_uid=self.version.uid).uid
                    for family in ("epr", "prp")]
            for uid in uids:
                dataset_registry.set_status(conn, self.project, uid, "discarded")
        retired = entities.registry(self.project, self.version.uid)
        self.assertEqual(retired.get("PLT-012").record.state,
                         entities.EntityState.SUPPORT_REMOVED)
        self.assertEqual(retired.get("PLT-011").record.state, entities.EntityState.DISCARDED)

    def test_the_008_accepts_the_declaration_and_the_layer_of_entities(self) -> None:
        """RF-015-10, RF-015-27 (plan 015 §5.2.3): ``begin_operation`` registra la declaración y la
        capa de entidades con los datos ``des_epr_`` de las entidades vivas como entradas (papel
        ``entity``), los parámetros de las que protegen y sus ajustes, y la cifra
        ``des.declared_count`` se registra CALCULADO sin ámbito."""
        name = "Plataforma C"
        _request, handle = self.make("PLT-021", name, qfx.START_DATASET,
                                     surface=qfx.START_DATASET)
        self.write_tables(handle, name)
        pairs = (("PLT-021", name),)
        declare = self.begin(
            "des.declare_constraints", settings=provenance.declare_settings(pairs),
            inputs=provenance.declare_inputs([name]),
            params=provenance.declare_params(["PLT-021"]))
        self.assertEqual(self.roles(declare), [("des_epr_plataforma_c", "entity")])
        self.assertEqual([item.key for item in declare.params],
                         [design_params.entity_key("PLT-021", "name"),
                          design_params.entity_key("PLT-021", "protect")])
        self.assertEqual([item.value_json for item in declare.params][1], "false")
        layer = self.begin("des.entity_layer", settings=provenance.entity_layer_settings(pairs),
                           inputs=provenance.entity_layer_inputs([name]))
        self.assertEqual(self.roles(layer), [("des_epr_plataforma_c", "entity")])
        self.assertEqual(layer.params, ())
        ((text,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", declare.uid)
        self.assertEqual(provenance.settings_entities(json.loads(text)), pairs)
        for figures in (provenance.declare_figures(0), provenance.declare_figures(3)):
            found = []
            try:
                with self.project.write_transaction() as conn:
                    found = [figures_mod.record_figure(conn, declare, spec) for spec in figures]
                    raise _Rollback
            except _Rollback:
                pass
            self.assertEqual([(item.key, item.unit, str(item.kind)) for item in found],
                             [("des.declared_count", "-", "CALCULADO")])


class _Rollback(Exception):
    """Para deshacer lo que una prueba escribe en una transacción."""


def cancel_if_running(handle: Any) -> None:
    """Deja cancelada la operación de la prueba si sigue «en curso» (una completada no hace falta)."""
    try:
        handle.cancel("Prueba")
    except Exception as exc:  # noqa: BLE001 - solo se calla «ya no está en curso»
        if getattr(exc, "code", "") != "core.operation_not_running":
            raise


if __name__ == "__main__":
    unittest.main()

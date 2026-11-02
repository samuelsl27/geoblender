# SPDX-License-Identifier: GPL-3.0-or-later
"""Las declaraciones de procedencia de las envolventes y el escalonado (spec 013, T13; HU-013-3,
HU-013-6; RF-013-17, RF-013-31; plan 013 §5.2.3, D-26, D-28; ADR-0013, ADR-0025 §2; RF-008-17,
RF-008-24 a RF-008-30, RF-009-05, RF-009-11).

``design.provenance`` declara con tipos de ``core`` lo que ``des`` registra en la procedencia de
la 008 y de la 009, sin registrar nada (lo registra ``bl``, T21 y T24):

- **dos operaciones de versión**, ``des.envelope`` y ``des.stepped_design`` (D-26), repetibles y
  reproducibles con 10⁻⁹ relativo; la segunda consume la primera;
- los **datos de la versión** (``des_env_``, ``des_srf_``, ``des_brm_``, ``des_bmt_``,
  ``des_rpt_``), con el papel ``design_surface`` en la superficie de diseño (D-28);
- sus **ajustes** (``SettingDef``), con las funciones que los guardan y los leen, para que cada
  clave declarada sea la que se guarda;
- sus **entradas** y los **parámetros** que lee cada una (la envolvente no lee el ancla ni la
  berma de un perfil que no usa: cambiar un perfil no deja obsoleta la envolvente que no lo usó);
- sus **cifras** (``FigureDef``) y las funciones que las arman: una cifra que no existe (sin
  celdas con envolvente, sin movimiento) no se registra, y una NaN o infinita nunca (RF-013-17).
"""

from __future__ import annotations

import json
import math
import unittest
from collections.abc import Iterator, Mapping
from dataclasses import astuple
from typing import Any

from tests.support import design_fixtures as dfx
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered, snapshot

provenance = import_geoblender("design.provenance")
model = import_geoblender("design.model")
design_params = import_geoblender("design.params")
design_report = import_geoblender("design.report")
contract = import_geoblender("core.provenance.contract")
operations = import_geoblender("core.provenance.operations")
figures_mod = import_geoblender("core.provenance.figures")
lineage = import_geoblender("core.provenance.lineage")
core_params = import_geoblender("core.params")
datasets = import_geoblender("core.datasets")
paths = import_geoblender("core.paths")
i18n = import_geoblender("core.i18n")
units = import_geoblender("core.units")
masks_provenance = import_geoblender("gis.masks.provenance")
masks_store = import_geoblender("gis.masks.store")
res_provenance = import_geoblender("reserves.provenance")

SPANISH_LETTERS = frozenset("áéíóúüñÁÉÍÓÚÜÑ¿¡")
SURFACE = dfx.START_DATASET
FIVE = ("des_env_", "des_srf_", "des_brm_", "des_bmt_", "des_rpt_")
THICKNESS = "res.verify.min_thickness_m"
PROFILE = "expl_10_60_6"
OTHER = "rest_5_35_6"


def recompute(request: Any) -> Any:  # nunca se llama: solo declara que se repite sola
    raise AssertionError("las pruebas de las declaraciones no recalculan")


def reproduce(request: Any) -> Iterator[Any]:  # idem
    raise AssertionError("las pruebas de las declaraciones no reproducen")


def definitions() -> tuple[Any, ...]:
    """Los dos tipos con sus funciones y las cifras, como las registrará ``bl``."""
    return (*provenance.operation_defs(
        {t: recompute for t in provenance.REPRODUCIBLE},
        {t: reproduce for t in provenance.REPRODUCIBLE}), *provenance.FIGURES)


def envelope_request(**changes: Any) -> Any:
    """Una envolvente completa (semillas de una superficie en la zona de una restricción)."""
    base: dict[str, Any] = {
        "name": "Hueco inicial", "direction": "down",
        "seeds": model.SeedSource("surface", surface=SURFACE,
                                  zone=model.Zone("constraint", "limite_legal")),
        "slope_mode": "constant", "slope_deg": 35.0, "metric": "chamfer5", "mesh_factor": 1.0,
        "reach_m": None, "domain": model.WorkDomain()}
    return model.EnvelopeRequest(**{**base, **changes})


def design_request(**changes: Any) -> Any:
    base: dict[str, Any] = {
        "name": "Diseño V01", "envelope": "Hueco inicial", "sense": "cut",
        "base_profile": PROFILE, "sector_profiles": {"sector_2": OTHER, "sector_1": PROFILE},
        "anchor_grid": None}
    return model.DesignRequest(**{**base, **changes})


def every_envelope() -> Iterator[Any]:
    """Peticiones que recorren cada valor declarado de cada elección."""
    for direction in model.Direction:
        yield envelope_request(direction=direction)
    for metric in model.Metric:
        yield envelope_request(metric=metric)
    for mode in model.SlopeMode:
        yield envelope_request(slope_mode=mode, slope_deg=None if mode == "sectors" else 40.0)
    yield envelope_request(seeds=model.SeedSource("fixed", elevation_m=-12.5,
                                                  zone=model.Zone("domain")))
    yield envelope_request(seeds=model.SeedSource("grid", grid="gis_dtm_cotas"))
    for kind, name in (("domain", None), ("constraint", "limite_legal"), ("sector", "sector_1"),
                       ("layer", "gis_fea_zona")):
        yield envelope_request(seeds=model.SeedSource("surface", surface=SURFACE,
                                                      zone=model.Zone(kind, name)))
    yield envelope_request(seeds=model.SeedSource("surface", surface=SURFACE))
    yield envelope_request(domain=model.WorkDomain(sectors=("sector_2", "sector_1")))
    yield envelope_request(domain=model.WorkDomain(layer="gis_fea_recorte"))
    yield envelope_request(domain=model.WorkDomain(sectors=("sector_1",), layer="gis_fea_recorte"))
    yield envelope_request(reach_m=250.0, mesh_factor=0.93)


def every_design() -> Iterator[Any]:
    for sense in model.BenchSense:
        yield design_request(sense=sense)
    yield design_request(anchor_grid="gis_dtm_anclas")
    yield design_request(sector_profiles={})


def lookup(settings: Mapping[str, Any], key: str) -> tuple[bool, Any]:
    """Si los ajustes tienen la clave declarada (con «.» entra en uno anidado) y su valor."""
    found: Any = settings
    for part in key.split("."):
        if not isinstance(found, Mapping) or part not in found:
            return False, None
        found = found[part]
    return True, found


def report_of(**changes: Any) -> Any:
    """Un informe de diseño con movimiento (los valores de los ejemplos del plan)."""
    base: dict[str, Any] = {
        "cut_m3": 412_380.0, "fill_m3": 0.0, "cut_cells": 80_000, "fill_cells": 0,
        "moved_area_m2": 80_000.0, "nodata_cells": 0, "nodata_area_m2": 0.0,
        "min_thickness_m": 0.02, "slope_p90_deg": 33.1, "slope_p99_deg": 35.6,
        "slope_max_deg": 36.4, "slope_max_at": None, "edge_step_max_m": 0.0, "edge_cells": 0,
        "notices": ()}
    return design_report.DesignReport(**{**base, **changes})


class OperationTypesTest(unittest.TestCase):
    def test_two_version_operations_repeatable_and_reproducible(self) -> None:
        """RF-013-17, RF-013-31, D-26: ``des.envelope`` y ``des.stepped_design`` son de la
        versión (RF-009-05), del módulo ``des``, en la versión 1.0, se repiten solas y se
        reproducen con 10⁻⁹ relativo; las lanza la orden de calcular; la segunda no usa las
        mismas salidas que la primera."""
        self.assertEqual((provenance.ENVELOPE, provenance.STEPPED),
                         ("des.envelope", "des.stepped_design"))
        self.assertEqual([t.op_type for t in provenance.OPERATION_TYPES],
                         ["des.envelope", "des.stepped_design"])
        self.assertEqual(provenance.REPRODUCIBLE, ("des.envelope", "des.stepped_design"))
        self.assertEqual(provenance.VERSION_TYPES, ("des.envelope", "des.stepped_design"))
        self.assertEqual(dict(provenance.OPERATION_TYPES_BY_NAME),
                         {t.op_type: t for t in provenance.OPERATION_TYPES})
        self.assertEqual(provenance.MODULE, "des")
        self.assertEqual(provenance.OP_VERSION, "1.0")
        self.assertEqual(provenance.FIGURE_TOLERANCE, contract.Tolerance(relative=1e-9))
        for declared in provenance.OPERATION_TYPES:
            with self.subTest(op_type=declared.op_type):
                built = declared.definition(recompute, reproduce)
                self.assertIsInstance(built, contract.OperationDef)
                self.assertEqual((built.op_type, built.version, built.module, built.scope,
                                  built.repeatable, built.figure_tolerance),
                                 (declared.op_type, "1.0", "des", "version", True,
                                  contract.Tolerance(relative=1e-9)))
                self.assertEqual(built.commands, ("geoblender.des_compute_envelope",))
                self.assertIs(built.recompute, recompute)
                self.assertIs(built.reproduce, reproduce)
                self.assertEqual(built.settings, declared.settings)
                self.assertTrue(declared.settings)
        self.assertNotEqual(provenance.OPERATION_TYPES[0].outputs,
                            provenance.OPERATION_TYPES[1].outputs)

    def test_without_the_reproduce_function_there_is_no_tolerance(self) -> None:
        """RF-009-11: el tipo se declara sin la función de reproducir (solo recalcula) sin
        tolerancia de cifras (``OperationDef`` rechaza una tolerancia sin ella)."""
        bare = provenance.operation_def(provenance.ENVELOPE, recompute)
        self.assertIsNone(bare.reproduce)
        self.assertIsNone(bare.figure_tolerance)
        with self.assertRaises(ValueError):
            provenance.operation_def("des.nothing", recompute)
        with self.assertRaises(ValueError):
            provenance.operation_def(provenance.ENVELOPE)  # repetible sin recálculo

    def test_operation_defs_need_both_functions_of_every_type(self) -> None:
        """RF-008-26: ``operation_defs`` da los dos en su orden y exige la función de recálculo
        y la de reproducción de cada uno (ni de más ni de menos)."""
        built = provenance.operation_defs({t: recompute for t in provenance.REPRODUCIBLE},
                                          {t: reproduce for t in provenance.REPRODUCIBLE})
        self.assertEqual([item.op_type for item in built], list(provenance.REPRODUCIBLE))
        only = {provenance.ENVELOPE: recompute}
        for bad_recompute, bad_reproduce in (
                (only, {t: reproduce for t in provenance.REPRODUCIBLE}),
                ({t: recompute for t in provenance.REPRODUCIBLE}, only),
                ({**{t: recompute for t in provenance.REPRODUCIBLE}, "des.other": recompute},
                 {t: reproduce for t in provenance.REPRODUCIBLE})):
            with self.subTest(recompute=sorted(bad_recompute), reproduce=sorted(bad_reproduce)):
                with self.assertRaises(ValueError):
                    provenance.operation_defs(bad_recompute, bad_reproduce)

    def test_registration_leaves_no_trace(self) -> None:
        """RF-008-17 (principio 8): ``bl`` registra los dos tipos y las cifras y los quita al
        desactivar: los cuatro registros de ``core`` quedan como estaban; mientras tanto están."""
        before = snapshot()
        with registered(*definitions()):
            for op_type in provenance.REPRODUCIBLE:
                self.assertIn(op_type, contract.OPERATIONS)
            for figure in provenance.FIGURES:
                self.assertIs(contract.FIGURES[figure.key], figure)
        self.assertEqual(snapshot(), before)

    def test_labels_have_their_spanish(self) -> None:
        """RF-008-31 (principio 10): el nombre de cada operación, ajuste, elección y cifra es un
        ``msgid`` en inglés con su español en ``core/i18n/messages.toml`` (que no es el mismo
        texto); los nombres no se repiten con otro sentido."""
        table = i18n.load_messages()
        wanted: list[str] = []
        for declared in provenance.OPERATION_TYPES:
            wanted.append(declared.label_msgid)
            for setting in declared.settings:
                wanted.append(setting.label_msgid)
                wanted += [msgid for _value, msgid in setting.choices]
        wanted += [figure.label_msgid for figure in provenance.FIGURES]
        for msgid in wanted:
            with self.subTest(msgid=msgid):
                self.assertEqual(set(msgid) & SPANISH_LETTERS, set(), "msgid en inglés")
                self.assertEqual(i18n.placeholders(msgid), set())
                self.assertIn(msgid, table)
                if msgid != "None":
                    self.assertNotEqual(table[msgid], msgid)


class DatasetsTest(unittest.TestCase):
    def test_the_five_families_of_the_version(self) -> None:
        """RF-013-17, RF-013-31 (plan §5.2.3): ``des_env_``, ``des_srf_``, ``des_brm_``,
        ``des_bmt_`` y ``des_rpt_``: las tres rejillas son GeoTIFF propio (``rasters/``) y las
        dos tablas, ``core.gpkg_layer@1``; cada una con su papel; la superficie de diseño lleva
        ``design_surface`` (D-28)."""
        expected = {
            "env": ("raster", "rasters", "gis.geotiff@1", "envelope"),
            "srf": ("raster", "rasters", "gis.geotiff@1", "design_surface"),
            "brm": ("raster", "rasters", "gis.geotiff@1", "berms"),
            "bmt": ("table", "gpkg", "core.gpkg_layer@1", "berm_table"),
            "rpt": ("table", "gpkg", "core.gpkg_layer@1", "report")}
        self.assertEqual([family.code for family in provenance.FAMILIES], list(expected))
        self.assertEqual((provenance.ENVELOPE_GRID, provenance.DESIGN_GRID, provenance.BERMS_GRID,
                          provenance.BERM_TABLE, provenance.REPORT_TABLE), tuple(expected))
        self.assertEqual(dict(provenance.FAMILIES_BY_CODE),
                         {family.code: family for family in provenance.FAMILIES})
        self.assertEqual(provenance.DESIGN_SURFACE_ROLE, "design_surface")
        for family in provenance.FAMILIES:
            kind, store, reader, role = expected[family.code]
            with self.subTest(family=family.code):
                self.assertEqual((family.kind, str(family.store), family.reader, family.role),
                                 (kind, store, reader, role))
                self.assertEqual(family.prefix, f"des_{family.code}_")
        self.assertEqual(len({family.role for family in provenance.FAMILIES}), 5)

    def test_names_and_locators_carry_the_name_of_the_operation_and_the_version(self) -> None:
        """RF-013-17, D-34 de la 009: el nombre del dato es ``des_<familia>_<nombre>`` con el
        nombre de la operación en ASCII (``gis.provenance.dataset_slug``: el mismo nombre da el
        mismo dato) y su ubicación lleva el código de la versión: una ubicación no se
        reutiliza."""
        self.assertEqual(provenance.dataset_name("env", "Cantera Ñandú 1"), "des_env_cantera_nandu_1")
        self.assertEqual(provenance.dataset_locator("srf", "Cantera A", "V01"),
                         "rasters/des_srf_cantera_a_v01.tif")
        self.assertEqual(provenance.dataset_locator("brm", "Cantera A", "V12"),
                         "rasters/des_brm_cantera_a_v12.tif")
        self.assertEqual(provenance.dataset_locator("bmt", "Cantera A", "V01"),
                         "des_bmt_cantera_a_v01")
        self.assertEqual(provenance.dataset_locator("rpt", "Cantera A", "V01"),
                         "des_rpt_cantera_a_v01")
        self.assertEqual(provenance.dataset_name("env", "cantera_a"),
                         provenance.dataset_name("env", "Cantera A"))
        for bad in ("", "   ", "---"):
            with self.subTest(name=bad):
                with self.assertRaises(Exception) as caught:
                    provenance.dataset_name("env", bad)
                self.assertEqual(getattr(caught.exception, "code", ""), "gis.dataset_name_invalid")
        with self.assertRaises(ValueError):
            provenance.dataset_name("vol", "Cantera A")  # una familia de otro módulo
        with self.assertRaises(ValueError):
            provenance.dataset_locator("env", "Cantera A", "1")

    def test_the_dataset_specs_are_the_ones_the_008_accepts(self) -> None:
        """RF-008-17, RF-013-31: la ``DatasetSpec`` de cada familia es del módulo ``des``, no se
        edita en QGIS, no lleva selector y declara el CRS de una rejilla; la de la superficie de
        diseño lleva el papel ``design_surface``."""
        for family in provenance.FAMILIES:
            with self.subTest(family=family.code):
                spec = provenance.dataset_spec(family.code, "Cantera A", "V01",
                                               crs_epsg=25830 if family.kind == "raster" else None)
                self.assertIsInstance(spec, datasets.DatasetSpec)
                self.assertEqual((spec.module, spec.kind, spec.reader, spec.role, spec.selector),
                                 ("des", family.kind, family.reader, family.role, None))
                self.assertEqual(spec.name, provenance.dataset_name(family.code, "Cantera A"))
                self.assertEqual(spec.locator,
                                 provenance.dataset_locator(family.code, "Cantera A", "V01"))
                self.assertFalse(spec.qgis_editable)
                self.assertEqual(spec.crs_epsg, 25830 if family.kind == "raster" else None)
        self.assertEqual(provenance.dataset_spec("srf", "Cantera A", "V01").role, "design_surface")

    def test_what_each_operation_writes(self) -> None:
        """RF-013-17, RF-013-31 (plan §5.2.3): la envolvente escribe su rejilla; el escalonado,
        la superficie de diseño, las bermas, su tabla y el informe."""
        outputs = {t.op_type: t.outputs for t in provenance.OPERATION_TYPES}
        self.assertEqual(outputs, {"des.envelope": ("env",),
                                   "des.stepped_design": ("srf", "brm", "bmt", "rpt")})
        self.assertEqual(tuple(family.prefix for family in provenance.FAMILIES), FIVE)


class SettingsTest(unittest.TestCase):
    def test_every_declared_setting_is_the_one_that_is_saved(self) -> None:
        """RF-008-29 (plan 013 §5.2.3): cada clave de cada ``SettingDef`` está en los ajustes
        que guarda la operación, y cada valor que se guarda de una elección es uno de los
        declarados (y cada declarado se guarda en algún caso); un ajuste sin declarar o sin
        guardar no se enseña bien."""
        built = {
            "des.envelope": [provenance.envelope_settings(request, ("sector_2",))
                             for request in every_envelope()],
            "des.stepped_design": [provenance.design_settings(request, SURFACE, ("sector_2",))
                                   for request in every_design()]}
        for declared in provenance.OPERATION_TYPES:
            for setting in declared.settings:
                values = []
                for settings in built[declared.op_type]:
                    present, value = lookup(settings, setting.key)
                    if setting.key.startswith("seeds.zone.") and not present:
                        continue  # sin zona: toda la superficie
                    with self.subTest(op_type=declared.op_type, key=setting.key):
                        self.assertTrue(present, f"{setting.key} falta en {settings}")
                    values.append(value)
                with self.subTest(op_type=declared.op_type, key=setting.key, check="choices"):
                    if setting.unit is not None:
                        self.assertTrue(any(isinstance(v, int | float) for v in values))
                        continue
                    declared_values = [value for value, _msgid in setting.choices]
                    if setting.key == "base_profile":
                        continue  # el código de un perfil: lo que no es «ninguno» se enseña tal cual
                    stored = {v for v in values if v is not None or None in declared_values}
                    self.assertLessEqual(stored, set(declared_values))
                    self.assertEqual(stored, set(declared_values))

    def test_the_declared_settings_of_the_plan(self) -> None:
        """RF-013-11 a RF-013-14, RF-013-21 a RF-013-24 (plan §5.2.3): de la envolvente, la
        dirección, la métrica, el alcance, el modo y el valor de la pendiente, el origen de las
        semillas, el acotado; del escalonado, el sentido, el perfil y el ancla."""
        keys = {t.op_type: {item.key for item in t.settings} for t in provenance.OPERATION_TYPES}
        for key in ("direction", "metric", "reach_m", "slope_mode", "slope_deg", "mesh_factor",
                    "seeds.kind", "seeds.zone.kind", "seeds.elevation_m", "domain.bound"):
            self.assertIn(key, keys["des.envelope"])
        for key in ("sense", "base_profile", "anchor.source"):
            self.assertIn(key, keys["des.stepped_design"])
        by_key = {item.key: item for item in provenance.OPERATION_TYPES[0].settings}
        self.assertEqual(by_key["reach_m"].unit, "m")
        self.assertEqual(by_key["slope_deg"].unit, "deg")
        self.assertEqual(by_key["seeds.elevation_m"].unit, "m")
        self.assertEqual(by_key["mesh_factor"].unit, "-")

    def test_the_envelope_round_trips_through_its_settings(self) -> None:
        """RF-013-17, RF-008-26: lo que guardan los ajustes vuelve a pedir lo mismo (el
        recálculo y la reproducción repiten la envolvente con ellos): la petición que sale es
        igual a la de entrada, también a través de JSON; los sectores pendientes al calcular
        (RF-013-06) se guardan y se leen aparte."""
        count = 0
        for request in every_envelope():
            for pending in ((), ("sector_2", "sector_1")):
                with self.subTest(request=request, pending=pending):
                    settings = provenance.envelope_settings(request, pending)
                    again = json.loads(json.dumps(settings))
                    self.assertEqual(again, settings)
                    self.assertEqual(provenance.envelope_request(again), request)
                    self.assertEqual(provenance.settings_pending(again), pending)
                    self.assertEqual(paths.find_absolute_paths(settings), [])
                    count += 1
        self.assertGreater(count, 20)

    def test_the_design_round_trips_through_its_settings(self) -> None:
        """RF-013-31, RF-008-26: lo mismo para el escalonado, con la superficie de partida (que
        la petición no lleva) y los perfiles por sector en su orden."""
        for request in every_design():
            with self.subTest(request=request):
                settings = provenance.design_settings(request, SURFACE, ("sector_2",))
                again = json.loads(json.dumps(settings))
                self.assertEqual(again, settings)
                self.assertEqual(provenance.design_request(again), request)
                self.assertEqual(provenance.design_start(again), SURFACE)
                self.assertEqual(provenance.settings_pending(again), ("sector_2",))
                self.assertEqual(paths.find_absolute_paths(settings), [])
        settings = provenance.design_settings(design_request(), SURFACE)
        self.assertEqual(list(settings["sector_profiles"]), ["sector_1", "sector_2"])
        self.assertEqual(settings["envelope"], "Hueco inicial")

    def test_the_settings_do_not_change_what_they_were_given(self) -> None:
        """Regla 6 de AGENTS.md: las peticiones son inmutables y los ajustes que sacan son
        diccionarios nuevos; cambiarlos no cambia la petición, y la lista de pendientes que se
        da no se guarda por referencia."""
        request = envelope_request(domain=model.WorkDomain(sectors=("a", "b")))
        pending = ["sector_1"]
        first = provenance.envelope_settings(request, pending)
        second = provenance.envelope_settings(request, pending)
        self.assertIsNot(first, second)
        first["domain"]["sectors"].append("c")
        first["pending_sectors"].append("sector_9")
        self.assertEqual(pending, ["sector_1"])
        self.assertEqual(request.domain.sectors, ("a", "b"))
        self.assertEqual(provenance.envelope_settings(request, pending), second)

    def test_the_procedencia_shows_them_in_spanish(self) -> None:
        """RF-008-29 (spec 006, T58): la procedencia enseña los ajustes declarados con su
        nombre y su valor en español, con su unidad y el nombre de la elección (la métrica
        exacta, el alcance en m, el acotado a sectores)."""
        request = envelope_request(metric="exact", reach_m=250.0, slope_deg=33.5,
                                   domain=model.WorkDomain(sectors=("sector_1",)))
        with registered(*definitions()):
            text = lineage.settings_text(provenance.ENVELOPE,
                                         provenance.envelope_settings(request), language="es")
            english = lineage.settings_text(provenance.ENVELOPE,
                                            provenance.envelope_settings(request), language="en")
            stepped = lineage.settings_text(
                provenance.STEPPED, provenance.design_settings(design_request(), SURFACE),
                language="es")
        self.assertIsNotNone(text)
        for expected in ("Distancia euclídea exacta", "Alcance = 250 m", "Acotado a sectores",
                         "Envolvente descendente"):
            self.assertIn(expected, text)
        self.assertNotIn("sector_1", text)  # los nombres no se enseñan
        self.assertIn("Exact Euclidean distance", english)
        self.assertIn("Corte", stepped)
        self.assertIn(PROFILE, stepped)

    def test_malformed_settings_are_refused_in_spanish(self) -> None:
        """RF-008-26: unos ajustes que no son los de una envolvente o un escalonado no se
        repiten a ciegas: ``ValueError`` con el campo (sin nombre, una dirección desconocida,
        un origen que no es de semillas, sectores que no son una lista…)."""
        good = provenance.envelope_settings(envelope_request())
        design = provenance.design_settings(design_request(), SURFACE)

        def without(settings: dict[str, Any], key: str) -> dict[str, Any]:
            return {k: v for k, v in settings.items() if k != key}

        cases: list[tuple[str, Any, Any]] = [
            ("nombre", provenance.envelope_request, without(good, "name")),
            ("dirección", provenance.envelope_request, {**good, "direction": "sideways"}),
            ("métrica", provenance.envelope_request, {**good, "metric": "chamfer3"}),
            ("modo", provenance.envelope_request, {**good, "slope_mode": 7}),
            ("semillas", provenance.envelope_request, without(good, "seeds")),
            ("origen", provenance.envelope_request, {**good, "seeds": {**good["seeds"], "kind": "x"}}),
            ("dominio", provenance.envelope_request, {**good, "domain": {"sectors": "ab"}}),
            ("lista", provenance.envelope_request, [1, 2]),
            ("alcance", provenance.envelope_request, {**good, "reach_m": "lejos"}),
            ("sentido", provenance.design_request, {**design, "sense": "dig"}),
            ("perfil base", provenance.design_request, without(design, "base_profile")),
            ("perfiles", provenance.design_request, {**design, "sector_profiles": ["a"]}),
            ("superficie", provenance.design_start, without(design, "surface")),
            ("pendientes", provenance.settings_pending, {"pending_sectors": "sector_1"}),
        ]
        for what, function, settings in cases:
            with self.subTest(what=what):
                with self.assertRaises((ValueError, TypeError)) as caught:
                    function(settings)
                self.assertTrue(str(caught.exception))
        self.assertEqual(provenance.settings_pending({}), ())

    def test_seeds_without_a_dataset_are_refused_as_inputs(self) -> None:
        """RF-013-01: unas semillas incompletas (una superficie sin nombre, una rejilla de cotas
        sin nombre) no se registran como entrada: ``ValueError`` con lo que falta."""
        bad = [envelope_request(seeds=model.SeedSource("surface")),
               envelope_request(seeds=model.SeedSource("grid"))]
        for request in bad:
            with self.subTest(seeds=request.seeds):
                with self.assertRaises(ValueError):
                    provenance.envelope_inputs(request)


class InputsAndParametersTest(unittest.TestCase):
    MASKS = (operations.Use("uid_classes", "masks_classes"),
             operations.Use("uid_zones", "masks_zones"),
             operations.Use("uid_report", "masks_report"))

    def uses(self, found: Any) -> list[tuple[str, str]]:
        return [(use.item, use.role) for use in found]

    def test_the_envelope_consumes_its_seeds_masks_sectors_and_searches(self) -> None:
        """RF-013-17 (plan §5.2.3): la superficie de partida con el papel ``surface`` (si las
        semillas salen de ella), las máscaras de la versión tal como las da ``MaskSet.uses()``
        (con sus papeles), los sectores y las búsquedas (solo si están registrados)."""
        request = envelope_request()
        found = provenance.envelope_inputs(request, self.MASKS,
                                           {"core_sector", "core_untouchable_search", "x"})
        self.assertEqual(self.uses(found),
                         [(SURFACE, "surface"), ("uid_classes", "masks_classes"),
                          ("uid_zones", "masks_zones"), ("uid_report", "masks_report"),
                          ("core_sector", "sectors"), ("core_untouchable_search", "searches")])
        self.assertTrue(all(isinstance(use, operations.Use) for use in found))
        self.assertEqual((provenance.SURFACE_ROLE, provenance.SECTORS_ROLE,
                          provenance.SEARCHES_ROLE),
                         ("surface", masks_provenance.SECTORS_ROLE, masks_provenance.SEARCHES_ROLE))
        none = provenance.envelope_inputs(request, self.MASKS, set())
        self.assertEqual(self.uses(none), self.uses(found)[:4])

    def test_each_origin_of_the_seeds_is_an_input_only_when_it_is_a_dataset(self) -> None:
        """RF-013-01, RF-013-17: una rejilla de cotas es la entrada ``seeds_grid``; una cota
        fija no es ninguna; la capa de una zona y la capa que acota el dominio son entradas
        (si cambian, la envolvente queda obsoleta) con su papel, sin repetirse."""
        grid = provenance.envelope_inputs(
            envelope_request(seeds=model.SeedSource("grid", grid="gis_dtm_cotas")))
        self.assertEqual(self.uses(grid), [("gis_dtm_cotas", "seeds_grid")])
        fixed = provenance.envelope_inputs(
            envelope_request(seeds=model.SeedSource("fixed", elevation_m=410.0,
                                                    zone=model.Zone("domain"))))
        self.assertEqual(fixed, ())
        layered = provenance.envelope_inputs(envelope_request(
            seeds=model.SeedSource("surface", surface=SURFACE,
                                   zone=model.Zone("layer", "gis_fea_zona")),
            domain=model.WorkDomain(layer="gis_fea_recorte")))
        self.assertEqual(self.uses(layered), [(SURFACE, "surface"), ("gis_fea_zona", "zone_layer"),
                                              ("gis_fea_recorte", "domain_layer")])
        same = provenance.envelope_inputs(envelope_request(
            seeds=model.SeedSource("surface", surface=SURFACE,
                                   zone=model.Zone("layer", "gis_fea_zona")),
            domain=model.WorkDomain(layer="gis_fea_zona")))
        self.assertEqual(self.uses(same), [(SURFACE, "surface"), ("gis_fea_zona", "zone_layer"),
                                           ("gis_fea_zona", "domain_layer")])

    def test_the_design_consumes_the_envelope_the_start_surface_and_the_anchors(self) -> None:
        """RF-013-31 (D-26, plan §5.2.3): el escalonado consume la envolvente (su dato
        ``des_env_<nombre>``, con el papel ``envelope``), la superficie de partida, la rejilla
        de anclas si el ancla es una rejilla, las máscaras, los sectores y las búsquedas."""
        request = design_request(anchor_grid="gis_dtm_anclas")
        found = provenance.design_inputs(request, SURFACE, self.MASKS,
                                         {"core_sector", "core_untouchable_search"})
        self.assertEqual(self.uses(found), [
            ("des_env_hueco_inicial", "envelope"), (SURFACE, "surface"),
            ("gis_dtm_anclas", "anchors"), ("uid_classes", "masks_classes"),
            ("uid_zones", "masks_zones"), ("uid_report", "masks_report"),
            ("core_sector", "sectors"), ("core_untouchable_search", "searches")])
        self.assertEqual(provenance.ENVELOPE_ROLE, provenance.FAMILIES_BY_CODE["env"].role)
        plain = provenance.design_inputs(design_request(), SURFACE)
        self.assertEqual(self.uses(plain), [("des_env_hueco_inicial", "envelope"),
                                            (SURFACE, "surface")])
        with self.assertRaises(ValueError):
            provenance.design_inputs(design_request(), "  ")

    def test_what_is_repeated_is_given_once(self) -> None:
        """RF-008-05: la 008 no admite la misma entrada con el mismo papel dos veces ni el mismo
        parámetro dos veces: lo repetido (una máscara que ya entró, un talud nombrado dos veces)
        se da una sola vez, en el orden de la primera."""
        again = provenance.envelope_inputs(envelope_request(), (*self.MASKS, self.MASKS[0]), ())
        self.assertEqual(self.uses(again), [(SURFACE, "surface"), ("uid_classes", "masks_classes"),
                                            ("uid_zones", "masks_zones"),
                                            ("uid_report", "masks_report")])
        slope = "des.sector.sector_1.max_general_slope_deg"
        found = provenance.envelope_params(
            envelope_request(slope_mode="sectors", slope_deg=None), profiles=(PROFILE, PROFILE),
            sector_slopes=(slope, slope))
        self.assertEqual(len(set(found)), len(found))
        self.assertEqual(found.count(slope), 1)
        twice = provenance.design_params(design_request(), sector_slopes=(slope, slope))
        self.assertEqual(len(set(twice)), len(twice))

    def test_parameters_of_a_profile(self) -> None:
        """RF-013-18: las claves de los parámetros de un perfil son las de las familias de
        ``design.params`` (``des.bench.{p}.<valor>``), en el orden de los perfiles y de los
        valores, sin repetir."""
        found = provenance.profile_params((PROFILE, OTHER, PROFILE))
        self.assertEqual(found, tuple(
            design_params.bench_key(code, value)
            for code in (PROFILE, OTHER) for value in design_params.BenchParam))
        self.assertEqual(provenance.profile_params((PROFILE,), (design_params.BenchParam.FACE,)),
                         (f"des.bench.{PROFILE}.face_deg",))
        self.assertEqual(provenance.profile_params(()), ())
        with self.assertRaises(ValueError):
            provenance.profile_params(("Expl 10",))

    def test_a_constant_envelope_reads_only_the_thickness(self) -> None:
        """RF-013-17, RF-013-11: con pendiente constante, la envolvente no lee ningún perfil ni
        talud de sector; solo el espesor mínimo de la 012 con que cuenta su desmonte y su
        terraplén (si cambia, cambian sus cifras)."""
        self.assertEqual(provenance.envelope_params(envelope_request(),
                                                    profiles=(PROFILE,),
                                                    sector_slopes=("des.sector.s.x",)),
                         (THICKNESS,))
        self.assertEqual(design_params.VERIFY_MIN_THICKNESS, THICKNESS)

    def test_an_envelope_by_sectors_reads_the_general_slope_but_not_the_anchor(self) -> None:
        """RF-013-13, RF-013-21 (plan 013 §7, T15): por sectores lee, de cada perfil que usa, la
        altura, la cara, la berma y el factor de malla (su talud general), no el ancla: cambiar
        el ancla de un perfil deja obsoleta la superficie, no la envolvente; y los taludes
        impuestos de los sectores."""
        slopes = ("des.sector.sector_1.max_general_slope_deg",
                  "des.sector.sector_2.max_general_slope_deg")
        found = provenance.envelope_params(envelope_request(slope_mode="sectors", slope_deg=None),
                                           profiles=(PROFILE, OTHER), sector_slopes=slopes)
        self.assertEqual(found, (
            *(f"des.bench.{code}.{value}" for code in (PROFILE, OTHER)
              for value in ("height_m", "face_deg", "berm_m", "mesh_factor")),
            *slopes, THICKNESS))
        self.assertFalse([key for key in found if key.endswith(".anchor_m")])
        self.assertEqual(len(set(found)), len(found))

    def test_the_design_reads_the_five_values_of_each_profile_and_the_project_ones(self) -> None:
        """RF-013-17, RF-013-27, RF-013-30: el escalonado lee los cinco valores de cada perfil
        (con el ancla), los taludes de los sectores, la tolerancia de cara, el umbral de aviso
        de magnitud y el espesor mínimo."""
        slopes = ("des.sector.sector_1.max_general_slope_deg",)
        found = provenance.design_params(design_request(), sector_slopes=slopes)
        self.assertEqual(found, (
            *provenance.profile_params((PROFILE, OTHER)), *slopes,
            "des.tolerance.face_deg", "des.warning.magnitude_ratio", THICKNESS))
        only_base = provenance.design_params(design_request(sector_profiles={}))
        self.assertEqual(only_base, (*provenance.profile_params((PROFILE,)),
                                     "des.tolerance.face_deg", "des.warning.magnitude_ratio",
                                     THICKNESS))
        self.assertEqual((design_params.TOLERANCE_FACE, design_params.WARNING_RATIO),
                         ("des.tolerance.face_deg", "des.warning.magnitude_ratio"))


class FiguresTest(unittest.TestCase):
    def test_the_figures_of_the_plan(self) -> None:
        """RF-013-17, RF-013-30 (plan §5.2.3): las seis cifras de la envolvente y las nueve del
        escalonado, con sus claves, su unidad del catálogo y de qué admiten (las cotas de la
        envolvente, negativas); ninguna se repite."""
        expected = {
            "des.env_cells": "-", "des.env_area_m2": "m2", "des.env_min_m": "m",
            "des.env_max_m": "m", "des.env_cut_m3": "m3", "des.env_fill_m3": "m3",
            "des.cut_m3": "m3", "des.fill_m3": "m3", "des.moved_area_m2": "m2",
            "des.slope_p90_deg": "deg", "des.slope_p99_deg": "deg", "des.slope_max_deg": "deg",
            "des.edge_step_max_m": "m", "des.berm_count": "-", "des.nodata_area_m2": "m2"}
        self.assertEqual({figure.key: figure.unit for figure in provenance.FIGURES}, expected)
        self.assertEqual(len(provenance.FIGURES), len(expected))
        self.assertEqual([figure.key for figure in provenance.ENVELOPE_FIGURES], list(expected)[:6])
        self.assertEqual([figure.key for figure in provenance.DESIGN_FIGURES], list(expected)[6:])
        self.assertEqual({figure.key for figure in provenance.FIGURES if figure.allow_negative},
                         {"des.env_min_m", "des.env_max_m"})
        self.assertTrue(all(figure.allow_zero for figure in provenance.FIGURES))
        for figure in provenance.FIGURES:
            self.assertIn(figure.unit, units.UNITS)
            self.assertEqual(figure.module, "des")
        self.assertEqual((provenance.CUT_M3, provenance.FILL_M3), ("des.cut_m3", "des.fill_m3"))

    def test_the_envelope_figures(self) -> None:
        """RF-013-17: las celdas con envolvente, su área, sus cotas mínima y máxima y el
        desmonte y el terraplén frente a la superficie de partida, todas CALCULADO en su
        unidad; con la envolvente sobre el nivel del mar y bajo él."""
        found = provenance.envelope_figures(cells=8_540, area_m2=34_160.0, min_m=-12.5,
                                            max_m=231.5, cut_m3=412_380.25, fill_m3=0.0)
        self.assertEqual([(spec.key, spec.value, spec.unit) for spec in found], [
            ("des.env_cells", 8540.0, "-"), ("des.env_area_m2", 34_160.0, "m2"),
            ("des.env_min_m", -12.5, "m"), ("des.env_max_m", 231.5, "m"),
            ("des.env_cut_m3", 412_380.25, "m3"), ("des.env_fill_m3", 0.0, "m3")])
        for spec in found:
            self.assertEqual((spec.kind, dict(spec.scope), spec.parameter_key),
                             ("CALCULADO", {}, None))
            self.assertIs(type(spec.value), float)

    def test_an_envelope_without_cells_has_no_extremes(self) -> None:
        """RF-013-17: sin celdas con envolvente no hay cota mínima ni máxima; la cifra no
        existe (no se registra una NaN ni una infinita) y las demás valen cero."""
        found = provenance.envelope_figures(cells=0, area_m2=0.0, min_m=None, max_m=None,
                                            cut_m3=0.0, fill_m3=0.0)
        self.assertEqual([spec.key for spec in found],
                         ["des.env_cells", "des.env_area_m2", "des.env_cut_m3", "des.env_fill_m3"])
        self.assertEqual([spec.value for spec in found], [0.0, 0.0, 0.0, 0.0])

    def test_no_envelope_figure_can_be_nan_or_infinite(self) -> None:
        """RF-013-17: un valor que no es finito es un error del programa (``ValueError``
        nombrando la cifra), nunca una cifra registrada."""
        good = {"cells": 10, "area_m2": 40.0, "min_m": 1.0, "max_m": 2.0, "cut_m3": 3.0,
                "fill_m3": 4.0}
        for name in good:
            for bad in (math.nan, math.inf, -math.inf):
                with self.subTest(name=name, value=bad):
                    with self.assertRaises(ValueError) as caught:
                        provenance.envelope_figures(**{**good, name: bad})
                    self.assertIn("des.", str(caught.exception))
        with self.assertRaises(TypeError):
            provenance.envelope_figures(**{**good, "cells": "diez"})

    def test_the_design_figures(self) -> None:
        """RF-013-30, RF-013-31: el desmonte, el terraplén, el área con movimiento, el p90, el
        p99 y el máximo de la inclinación, el mayor salto en el borde de lo prohibido, las
        bermas y el área sin dato, con las cifras de un informe real (``DesignReport``)."""
        found = provenance.design_figures(report_of(nodata_area_m2=12.0, edge_step_max_m=0.4),
                                          berm_count=214)
        self.assertEqual([(spec.key, spec.value, spec.unit) for spec in found], [
            ("des.cut_m3", 412_380.0, "m3"), ("des.fill_m3", 0.0, "m3"),
            ("des.moved_area_m2", 80_000.0, "m2"), ("des.slope_p90_deg", 33.1, "deg"),
            ("des.slope_p99_deg", 35.6, "deg"), ("des.slope_max_deg", 36.4, "deg"),
            ("des.edge_step_max_m", 0.4, "m"), ("des.berm_count", 214.0, "-"),
            ("des.nodata_area_m2", 12.0, "m2")])
        self.assertEqual({spec.key for spec in found}, {f.key for f in provenance.DESIGN_FIGURES})

    def test_without_movement_there_are_no_slope_figures(self) -> None:
        """RF-013-17, RF-013-30: sin celdas con movimiento el informe no tiene inclinación
        (``None``): la cifra no existe; las demás son cero (no se inventa un cero para la
        inclinación) y no hay bermas."""
        quiet = report_of(cut_m3=0.0, cut_cells=0, moved_area_m2=0.0, slope_p90_deg=None,
                          slope_p99_deg=None, slope_max_deg=None)
        found = provenance.design_figures(quiet, berm_count=0)
        self.assertEqual([spec.key for spec in found], [
            "des.cut_m3", "des.fill_m3", "des.moved_area_m2", "des.edge_step_max_m",
            "des.berm_count", "des.nodata_area_m2"])
        self.assertEqual({spec.value for spec in found}, {0.0})

    def test_no_design_figure_can_be_nan_or_infinite(self) -> None:
        """RF-013-17: un informe con una cifra NaN o infinita no se registra
        (``ValueError``), nombrando la cifra; ni el número de bermas negativo."""
        for name in ("cut_m3", "fill_m3", "moved_area_m2", "slope_p90_deg", "slope_p99_deg",
                     "slope_max_deg", "edge_step_max_m", "nodata_area_m2"):
            for bad in (math.nan, math.inf, -math.inf):
                with self.subTest(name=name, value=bad):
                    with self.assertRaises(ValueError) as caught:
                        provenance.design_figures(report_of(**{name: bad}), berm_count=3)
                    self.assertIn("des.", str(caught.exception))
        for bad_count in (-1, 2.5, True, math.nan):
            with self.subTest(berm_count=bad_count):
                with self.assertRaises((ValueError, TypeError)):
                    provenance.design_figures(report_of(), berm_count=bad_count)

    def test_the_report_is_not_modified(self) -> None:
        """Regla 6 de AGENTS.md: armar las cifras no cambia el informe (inmutable) ni lo
        copia con otra cosa."""
        report = report_of()
        before = astuple(report)
        provenance.design_figures(report, berm_count=1)
        self.assertEqual(astuple(report), before)


class _Rollback(Exception):
    """Para deshacer lo que una prueba escribe en una transacción."""


class RegistrationTest(dfx.DesignProjectCase):
    """Lo declarado, en un proyecto real: la 008 acepta los ajustes, las entradas, los parámetros
    y las cifras que arman estas funciones (V01, con las máscaras al día)."""

    def setUp(self) -> None:
        super().setUp()
        core_params.register_definitions(design_params.DEFINITIONS)
        self.addCleanup(core_params.unregister_definitions, "des")
        core_params.register_definitions(res_provenance.VERIFY_DEFINITIONS)
        self.addCleanup(core_params.unregister_definitions, "res")
        stack = registered(*definitions())
        stack.__enter__()
        self.addCleanup(stack.__exit__, None, None, None)

    def begin(self, op_type: str, **values: Any) -> Any:
        self.clock.advance(minutes=1)
        handle = operations.begin_operation(self.project, op_type, executor="blender",
                                            version=self.v1.uid, **values)
        self.addCleanup(lambda: handle.cancel("Prueba"))
        return handle

    def test_the_008_accepts_the_envelope_as_declared(self) -> None:
        """RF-013-17, RF-008-05: ``begin_operation`` registra la envolvente con los ajustes de
        :func:`envelope_settings` (JSON sin rutas, tal cual), las entradas de
        :func:`envelope_inputs` con sus papeles (la superficie, las tres de las máscaras, los
        sectores y las búsquedas) y los parámetros de :func:`envelope_params` (el espesor mínimo
        de la 012, resuelto en el proyecto)."""
        request = envelope_request()
        masks = self.masks()
        available = masks_store.available_tables(self.project)
        settings = provenance.envelope_settings(request, masks.pending_sectors)
        inputs = provenance.envelope_inputs(request, masks.uses(), available)
        handle = self.begin(provenance.ENVELOPE, settings=settings, inputs=inputs,
                            params=provenance.envelope_params(request))
        roles = [role for (role,) in self.query(
            "SELECT role FROM gb_operation_io WHERE operation_uid = ? AND direction = 'in' "
            "ORDER BY fid", handle.uid)]
        self.assertEqual(sorted(roles), sorted(use.role for use in inputs))
        self.assertEqual(set(roles) & {"surface", "sectors", "searches"},
                         {"surface", "sectors", "searches"})
        self.assertEqual(len(roles), 1 + len(masks.uses()) + 2)
        ((text,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", handle.uid)
        self.assertEqual(json.loads(text), settings)
        self.assertEqual([(item.key, item.scope) for item in handle.params],
                         [(THICKNESS, "project")])
        self.assertEqual(json.loads(text)["pending_sectors"], list(masks.pending_sectors))

    def test_the_008_accepts_the_design_as_declared(self) -> None:
        """RF-013-31: lo mismo para el escalonado, con la superficie de partida en sus ajustes y
        los parámetros del proyecto (tolerancia de cara, umbral de aviso y espesor mínimo;
        ``params`` sin perfiles: los valores de un perfil sin declarar no se registran)."""
        request = design_request(base_profile=PROFILE, sector_profiles={})
        keys = provenance.design_params(request)
        project_keys = tuple(key for key in keys if not key.startswith("des.bench."))
        handle = self.begin(provenance.STEPPED,
                            settings=provenance.design_settings(request, SURFACE),
                            params=project_keys)
        self.assertEqual({item.key for item in handle.params}, set(project_keys))
        self.assertEqual(project_keys, ("des.tolerance.face_deg", "des.warning.magnitude_ratio",
                                        THICKNESS))
        ((text,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", handle.uid)
        self.assertEqual(provenance.design_request(json.loads(text)), request)
        self.assertEqual(provenance.design_start(json.loads(text)), SURFACE)

    def record(self, handle: Any, specs: Any) -> list[Any]:
        """Registra las cifras ``specs`` en una transacción que se deshace y las da."""
        found: list[Any] = []
        try:
            with self.project.write_transaction() as conn:
                for spec in specs:
                    found.append(figures_mod.record_figure(conn, handle, spec))
                raise _Rollback
        except _Rollback:
            pass
        self.assertEqual(self.query("SELECT COUNT(*) FROM gb_figure WHERE operation_uid = ?",
                                    handle.uid), [(0,)])
        return found

    def test_the_008_accepts_every_figure_that_is_built(self) -> None:
        """RF-013-17, RF-008-30: las cifras de una envolvente y las de un escalonado se
        registran con su unidad y su tipo CALCULADO (también con cotas negativas, cero y sin
        inclinación); ninguna es NaN ni infinita."""
        envelope = self.begin(provenance.ENVELOPE, settings=provenance.envelope_settings(
            envelope_request()), params=(THICKNESS,))
        stepped = self.begin(provenance.STEPPED, settings=provenance.design_settings(
            design_request(), SURFACE), params=(THICKNESS,))
        sets = [
            (envelope, provenance.envelope_figures(
                cells=8_540, area_m2=34_160.0, min_m=-12.5, max_m=231.5, cut_m3=3.5, fill_m3=0.0)),
            (envelope, provenance.envelope_figures(
                cells=0, area_m2=0.0, min_m=None, max_m=None, cut_m3=0.0, fill_m3=0.0)),
            (stepped, provenance.design_figures(report_of(), berm_count=214)),
            (stepped, provenance.design_figures(
                report_of(cut_m3=0.0, moved_area_m2=0.0, slope_p90_deg=None, slope_p99_deg=None,
                          slope_max_deg=None), berm_count=0))]
        for handle, specs in sets:
            with self.subTest(op_type=handle.op_type, keys=[spec.key for spec in specs]):
                records = self.record(handle, specs)
                self.assertEqual([(item.key, item.unit, str(item.kind)) for item in records],
                                 [(spec.key, spec.unit, "CALCULADO") for spec in specs])
                self.assertTrue(all(math.isfinite(item.value) for item in records))

    def test_the_008_refuses_what_the_functions_never_build(self) -> None:
        """RF-013-17: una cifra NaN o infinita, que estas funciones no arman nunca, es lo que la
        008 rechazaría (``core.figure_nan``, ``core.figure_infinite``): sin la inclinación no se
        escribe una NaN, no se escribe nada."""
        stepped = self.begin(provenance.STEPPED, settings=provenance.design_settings(
            design_request(), SURFACE), params=(THICKNESS,))
        for value, code in ((math.nan, "core.figure_nan"), (math.inf, "core.figure_infinite")):
            with self.subTest(value=value):
                spec = figures_mod.FigureSpec("des.slope_p90_deg", value, "deg")
                with self.assertRaises(Exception) as caught:
                    self.record(stepped, [spec])
                self.assertEqual(getattr(caught.exception, "code", ""), code)


if __name__ == "__main__":
    unittest.main()

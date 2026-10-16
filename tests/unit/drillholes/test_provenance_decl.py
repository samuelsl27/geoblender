# SPDX-License-Identifier: GPL-3.0-or-later
"""Declaraciones de procedencia de los sondeos (spec 005, T40; HU-005-1 a HU-005-5; RF-005-07,
RF-005-12, RF-005-20, RF-005-22; RF-008-07, RF-008-17, RF-008-25 a RF-008-27; ADR-0025 §2; plan
005 §5.6.2 y §5.6.4).

``drillholes.provenance`` declara con tipos de ``core`` lo que los sondeos registran en la
procedencia de la 008, sin registrar nada (lo registra ``bl/ops/dh.py``), como la 006/T41:

- los **seis tipos de operación** del plan §5.6.4, en la versión ``1.0``: las dos importaciones
  y la exportación no se repiten solas (quedan «revisar a mano», RF-008-27); ``dh.build_base``,
  ``dh.validate`` y ``dh.desurvey`` sí, con la función de recálculo que les da ``bl``
  (RF-008-26); ninguna está acoplada a otra (RF-008-25); sus órdenes son las del catálogo de la
  003 (entrada ``005``) y su biblioteca, ``pyproj``;
- el **lector de cada importación** (``io.dh_csv@1``, ``io.dh_xlsx@1`` e
  ``io.recmin_mdb@1``, que escribe la T39) y el ``ImporterDef`` de cada uno;
- los **datos** (una tabla, un dato: ``vector`` las bocas y las trazas, ``table`` las demás, con
  ``core.gpkg_layer@1``) y su ``DatasetSpec`` (RF-008-17): la base y lo calculado, con el nombre
  de su tabla; lo importado de cada entrada, ``dh_src_<rol>_<nombre>``, inmutable con su
  entrada, sin selector y en la tabla con el uid corto de la entrada;
- la **entrada** de cada fichero (``InputSpec``, D-15): bocas y RecMin, ``drillholes`` con su
  CRS y su datum declarados; las demás tablas, ``table`` sin CRS; las convenciones de su papel
  son contenido y el separador, el decimal, la codificación y la cabecera, ajustes de lectura;
- ninguna cifra (``FigureDef``): los informes de la 005 son diagnósticos.

Las pruebas del registro escriben en un proyecto real de esquema 2: unas bocas sin datum
vertical no se registran (``core.input_crs_missing``) y cada ``DatasetSpec`` lo acepta el
registro de la 008. Cada prueba deja los registros de ``core`` (operaciones, grupos, cifras,
importadores y lectores) como los encontró.
"""

from __future__ import annotations

import dataclasses
import json
import unittest
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from tests.support.core_fixtures import FakeClock, make_session, make_settings, project_tmp
from tests.support.dh_sets import H25830, V5782
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered, snapshot

provenance = import_geoblender("drillholes.provenance")
schema = import_geoblender("drillholes.schema")
model = import_geoblender("drillholes.model")
contract = import_geoblender("core.provenance.contract")
operations = import_geoblender("core.provenance.operations")
messages = import_geoblender("core.provenance.messages")
datasets = import_geoblender("core.datasets")
readers = import_geoblender("core.content.readers")
builtin = import_geoblender("core.content.builtin")
encoder = import_geoblender("core.content.encoder")
inputs = import_geoblender("core.inputs")
input_registry = import_geoblender("core.inputs.registry")
create = import_geoblender("core.project.create")
userdata_mod = import_geoblender("core.userdata")
hashing = import_geoblender("core.hashing")
georef = import_geoblender("core.georef")
errors = import_geoblender("core.errors")
catalog = import_geoblender("core.catalog")
i18n = import_geoblender("core.i18n")
gis_crs = import_geoblender("gis.crs")

SPANISH_LETTERS = frozenset("áéíóúüñÁÉÍÓÚÜÑ¿¡")
IMPORT_TABULAR = "dh.import_tabular"
IMPORT_RECMIN = "dh.import_recmin"
BUILD_BASE = "dh.build_base"
VALIDATE = "dh.validate"
DESURVEY = "dh.desurvey"
EXPORT = "dh.export_validation"
CSV, XLSX, RECMIN = "io.dh_csv@1", "io.dh_xlsx@1", "io.recmin_mdb@1"

BASE = ("dh_collar", "dh_survey", "dh_lithology", "dh_assay", "dh_zone_interval",
        "dh_structure", "dh_lithology_code", "dh_element", "dh_sector", "dh_group", "dh_zone")
BASE_ROLES = ("collar", "survey", "lithology", "assay", "zone_interval", "structure",
              "lithology_code", "element", "sector", "group", "zone")
TABULAR_SOURCES = ("dh_src_collar", "dh_src_survey", "dh_src_lithology", "dh_src_assay",
                   "dh_src_catalog")
ALL_SOURCES = (*TABULAR_SOURCES, "dh_src_zone_interval", "dh_src_structure")
IMPORT_COMMANDS = ("geoblender.dh_import_drillholes", "geoblender.dh_import_recmin_mdb")
AZIMUTH_COMMAND = "geoblender.dh_set_azimuth_reference"
VALIDATION_PARAMS = ("dh.validation.depth_tolerance_m", "dh.validation.gap_tolerance_m",
                     "dh.validation.min_interval_m", "dh.validation.dogleg_max_deg_30m",
                     "dh.validation.collar_dem_tolerance_m")
DESURVEY_PARAMS = ("dh.validation.depth_tolerance_m", "dh.desurvey.trace_step_m")

# Plan 005 §5.6.4, copiado: tipo → (repetible, órdenes, consume, produce, bibliotecas,
# parámetros). Las órdenes: la propia del tipo y, si no la tiene (dh.build_base), las que lo
# encadenan; la referencia del azimut reimporta (plan §5.6.10).
PLAN: dict[str, tuple[bool, tuple[str, ...], tuple[str, ...], tuple[str, ...],
                      tuple[str, ...], tuple[str, ...]]] = {
    IMPORT_TABULAR: (False, (IMPORT_COMMANDS[0], AZIMUTH_COMMAND), (),
                     (*TABULAR_SOURCES, "dh_import_log"), ("pyproj",), ()),
    IMPORT_RECMIN: (False, (IMPORT_COMMANDS[1], AZIMUTH_COMMAND), (),
                    (*ALL_SOURCES, "dh_import_log"), ("pyproj",), ()),
    BUILD_BASE: (True, (*IMPORT_COMMANDS, AZIMUTH_COMMAND), ("source", "imports"), BASE,
                 ("pyproj",), ()),
    VALIDATE: (True, ("geoblender.dh_validate",), (*BASE_ROLES, "terrain"),
               ("dh_validation_issue",), (), VALIDATION_PARAMS),
    DESURVEY: (True, ("geoblender.dh_desurvey",), ("collar", "survey"), ("dh_trace",), (),
               DESURVEY_PARAMS),
    EXPORT: (False, ("geoblender.dh_export_validation_report",), ("exported",), (), (), ()),
}
PLAN_COMMANDS = {"geoblender.dh_import_drillholes", "geoblender.dh_import_recmin_mdb",
                 "geoblender.dh_validate", "geoblender.dh_desurvey",
                 "geoblender.dh_set_azimuth_reference",
                 "geoblender.dh_export_validation_report"}
IMPORTS = (IMPORT_TABULAR, IMPORT_RECMIN)
READERS = {IMPORT_TABULAR: (CSV, XLSX), IMPORT_RECMIN: (RECMIN,)}
# El papel de salida de cada tabla (gb_operation_io.role): distinto en cada una.
OUTPUT_ROLES = {
    **dict(zip(BASE, BASE_ROLES, strict=True)),
    "dh_trace": "trace",
    "dh_validation_issue": "validation_issue",
    "dh_import_log": "import_log",
    **{name: "source_" + name.removeprefix("dh_src_") for name in ALL_SOURCES},
}
# Plan §5.6.2: lo que es contenido de cada papel de una tabla (además del papel y de la
# correspondencia de columnas) y de una base de RecMin.
ROLE_CONVENTIONS = {
    "collar": ("all_vertical", "azimuth_ref", "declination_deg", "inclination_convention"),
    "survey": ("all_vertical", "azimuth_ref", "declination_deg", "inclination_convention"),
    "lithology": (),
    "assay_wide": ("negative_is_below_dl", "sentinels", "units"),
    "assay_long": ("negative_is_below_dl", "sentinels", "units"),
    "lithology_catalog": ("density_kind",),
    "element_catalog": ("units",),
}
SOURCE_OF_ROLE = {"collar": "collar", "survey": "survey", "lithology": "lithology",
                  "assay_wide": "assay", "assay_long": "assay", "lithology_catalog": "catalog",
                  "element_catalog": "catalog"}
RECMIN_CONVENTIONS = ("azimuth_ref", "declination_deg", "density_kind", "negative_is_below_dl",
                      "sentinels", "units")
CSV_SETTINGS = {"encoding": "utf-8", "separator": ";", "header_row": 0}
XLSX_SETTINGS = {"sheet": "Bocas", "header_row": 0}
MAPPING = {"hole": "Sondeo", "x": "X", "y": "Y", "z": "Z", "depth": "Profundidad"}
INPUT_UID = "3f2b9c1d-8e7a-4b6c-9d0e-1a2b3c4d5e6f"
TAG = "3f2b9c1d"
NAME = "Campaña Norte 2026"
SLUG = "campana_norte_2026"
ETRS89 = {"epsg": 25830}
REDNAP = {"epsg": 5782}
NOT_APPLICABLE = {"not_applicable": True}
PYPROJ = {"pyproj": "3.7.2"}
CATALOG = georef.load_catalog()
ProvenanceError = messages.ProvenanceError


def _function(op_type: str) -> Any:
    """Una función de recálculo o de reimportación de prueba, distinta por tipo (nunca se
    llama aquí)."""

    def run(request: Any) -> Any:
        return (op_type, request)

    run.__name__ = f"run_{op_type.replace('.', '_')}"
    return run


def _recompute_all() -> dict[str, Any]:
    return {op_type: _function(op_type) for op_type, row in PLAN.items() if row[0]}


def _unread(request: Any) -> Any:
    raise AssertionError("las pruebas de las declaraciones no leen las fuentes")


# Los lectores de la T39, falsos: solo dan su identificador y sus tipos.
FAKE_READERS = (
    readers.ContentReader("io.dh_csv", 1, ("drillholes", "table"), False, False, None, _unread),
    readers.ContentReader("io.dh_xlsx", 1, ("drillholes", "table"), False, False, None,
                          _unread),
    readers.ContentReader("io.recmin_mdb", 1, ("drillholes",), True, False, None, _unread),
)


@contextmanager
def _readers_registered(*chosen: Any) -> Iterator[None]:
    """Registra los lectores ``chosen`` que aún no estén y los quita al salir."""
    done: list[str] = []
    try:
        for reader in chosen:
            if reader.id not in readers.READERS:
                readers.register_reader(reader)
                done.append(reader.id)
        yield
    finally:
        for reader_id in reversed(done):
            readers.unregister_reader(reader_id)


def _declaration(**changes: Any) -> Any:
    """La declaración de ``csv_basico`` (EPSG:25830 y EPSG:5782, azimut de cuadrícula, coma
    decimal), con ``changes``."""
    values: dict[str, Any] = dict(
        crs=H25830, vertical=V5782, azimuth_ref=model.AzimuthRef.GRID, declination_deg=None,
        inclination_convention=model.InclinationConvention.NEGATIVE_DOWN,
        units={"Au": "g/t", "Ag": "ppm", "Cu": "%"}, value_rules=model.ValueRules(","),
        all_vertical=True, date_format="%d/%m/%Y",
    )
    values.update(changes)
    return model.SourceDeclaration(**values)


def _digest(reader: str, kind: str, declarations: Mapping[str, Any], label: str = "datos"
            ) -> Any:
    """Los hashes que daría el lector ``reader`` de unos datos que simula ``label`` con
    ``declarations``."""
    data = hashing.sha256_bytes(label.encode("utf-8"))
    return encoder.ContentDigest(data, encoder.content_sha256(kind, declarations, data),
                                 encoder.NORMALIZER, reader)


def _arguments(reader: str, role: str | None, declaration: Any, **changes: Any
               ) -> dict[str, Any]:
    """Los argumentos de ``input_spec`` de un fichero (de mentira) con su ``digest``."""
    settings = {CSV: CSV_SETTINGS, XLSX: XLSX_SETTINGS, RECMIN: {}}[reader]
    tabular = reader != RECMIN
    extra = {"role": role, "mapping": MAPPING} if tabular else {}
    kind = provenance.input_kind(reader, role)
    values: dict[str, Any] = dict(
        files=[inputs.SourceFile("fuentes/bocas.csv", "main", "original")],
        file_prints=[inputs.SourcePrint("a" * 64, size=10, mtime_ns=1)],
        digest=_digest(reader, kind, provenance.source_declarations(reader, declaration,
                                                                    **extra)),
        declaration=declaration, settings=dict(settings), **extra,
    )
    values.update(changes)
    return values


class _RegistryCase(unittest.TestCase):
    """Comprueba al terminar cada prueba que los registros de ``core`` están como al
    empezarla."""

    def setUp(self) -> None:
        before = (snapshot(), dict(readers.READERS))
        self.addCleanup(lambda: self.assertEqual((snapshot(), dict(readers.READERS)), before,
                                                 "la prueba dejó algo registrado"))


class OperationTypesTest(_RegistryCase):
    def test_types_of_the_plan(self) -> None:
        """RF-005-12, RF-005-20, RF-005-22, RF-008-17, RF-008-25 (plan §5.6.4): los seis
        tipos de la tabla del plan, en su orden, en la versión ``1.0``, con lo que consumen
        (sus papeles y sus parámetros), lo que producen (sus tablas), sus órdenes, sus
        bibliotecas y los lectores de las importaciones."""
        self.assertEqual(provenance.OP_VERSION, "1.0")
        self.assertEqual(provenance.MODULE, "dh")
        found = {t.op_type: t for t in provenance.OPERATION_TYPES}
        self.assertEqual([t.op_type for t in provenance.OPERATION_TYPES], list(PLAN))
        self.assertEqual(dict(provenance.OPERATION_TYPES_BY_NAME), found)
        for op_type, (repeatable, commands, uses, outputs, libraries, params) in PLAN.items():
            with self.subTest(op_type=op_type):
                declared = found[op_type]
                self.assertEqual(declared.repeatable, repeatable)
                self.assertEqual(declared.commands, commands)
                self.assertEqual(declared.inputs, uses)
                self.assertEqual(declared.outputs, outputs)
                self.assertEqual(declared.libraries, libraries)
                self.assertEqual(declared.params, params)
                self.assertEqual(declared.readers, READERS.get(op_type, ()))
        self.assertEqual({c for t in provenance.OPERATION_TYPES for c in t.commands},
                         PLAN_COMMANDS)
        self.assertEqual(provenance.IMPORTS, IMPORTS)
        self.assertEqual(provenance.EXPORTS, (EXPORT,))
        self.assertEqual(provenance.REPEATABLE, (BUILD_BASE, VALIDATE, DESURVEY))
        self.assertEqual({name for t in provenance.OPERATION_TYPES for name in t.outputs},
                         set(schema.LAYOUTS))

    def test_definitions_registered_and_removed_without_trace(self) -> None:
        """RF-008-17, RF-008-26, RF-008-27 (ADR-0025 §2): con funciones de recálculo de prueba,
        cada ``OperationDef`` se crea (módulo ``dh``, versión ``1.0``, ámbito del proyecto, sin
        grupo), se registra en ``core.provenance`` y se quita sin dejar rastro; las repetibles
        llevan su función y las importaciones y la exportación, ninguna."""
        functions = _recompute_all()
        before = snapshot()
        definitions = provenance.operation_defs(functions)
        self.assertEqual([d.op_type for d in definitions], list(PLAN))
        with registered(*definitions):
            for definition in definitions:
                op_type = definition.op_type
                with self.subTest(op_type=op_type):
                    self.assertIsInstance(definition, contract.OperationDef)
                    self.assertIs(contract.operation_def(op_type), definition)
                    self.assertEqual((definition.version, definition.module), ("1.0", "dh"))
                    self.assertEqual(definition.version_tuple, (1, 0))
                    self.assertIsNone(definition.group)
                    self.assertEqual(definition.scope, "project")
                    declared = provenance.OPERATION_TYPES_BY_NAME[op_type]
                    self.assertEqual(definition.label_msgid, declared.label_msgid)
                    self.assertEqual(definition.commands, declared.commands)
                    self.assertEqual(definition.libraries, declared.libraries)
                    self.assertEqual(definition.settings, ())
                    # T42 (plan §5.6.10): solo la base reúne ella misma todo lo vigente; lo
                    # descartado sale de su recálculo en vez de impedirlo.
                    self.assertEqual(definition.drops_discarded, op_type == BUILD_BASE)
                    if PLAN[op_type][0]:
                        self.assertTrue(definition.repeatable)
                        self.assertIs(definition.recompute, functions[op_type])
                    else:
                        self.assertFalse(definition.repeatable)
                        self.assertIsNone(definition.recompute)
            self.assertFalse([name for name in contract.GROUPS if name.startswith("dh.")])
        self.assertEqual(snapshot(), before)
        for op_type in PLAN:
            with self.subTest(op_type=op_type, registered=False):
                with self.assertRaises(contract.ProvenanceError) as caught:
                    contract.operation_def(op_type)
                self.assertEqual(caught.exception.code, "core.operation_unregistered")

    def test_one_definition_or_a_subset(self) -> None:
        """RF-008-26 (plan §5.6.4): ``bl`` puede construir un tipo (``operation_def``) o unos
        pocos (``op_types``), como hará cada tarea de operadores, y cada uno se registra y se
        quita solo."""
        build = _function(BUILD_BASE)
        definition = provenance.operation_def(BUILD_BASE, build)
        self.assertIs(definition.recompute, build)
        imported = provenance.operation_def(IMPORT_TABULAR)
        self.assertIsNone(imported.recompute)
        subset = provenance.operation_defs({BUILD_BASE: build},
                                           op_types=(IMPORT_TABULAR, BUILD_BASE))
        self.assertEqual([d.op_type for d in subset], [IMPORT_TABULAR, BUILD_BASE])
        self.assertEqual(subset[1], definition)
        with registered(*subset):
            self.assertEqual(sorted(name for name in contract.OPERATIONS
                                    if name.startswith("dh.")),
                             [BUILD_BASE, IMPORT_TABULAR])

    def test_settings_shown_in_the_provenance(self) -> None:
        """RF-008-29 (plan §5.6.4, 006/T58): ``bl`` da a cada tipo los ajustes de su orden que
        enseña su procedencia (``settings``, por tipo) y ``operation_def(s)`` se los pone, a
        los demás ninguno; unos de un tipo que no se construye o que no es de la 005 son un
        error del programa."""
        shown = (contract.SettingDef("method", "Method", choices=(
            ("minimum_curvature", "Minimum curvature"),)),
            contract.SettingDef("declination_deg", "Declination", unit="deg"))
        definitions = provenance.operation_defs(_recompute_all(), settings={DESURVEY: shown})
        self.assertEqual({d.op_type: d.settings for d in definitions if d.settings},
                         {DESURVEY: shown})
        alone = provenance.operation_def(DESURVEY, _function(DESURVEY), settings=shown)
        self.assertEqual(alone.settings, shown)
        self.assertEqual(provenance.operation_def(IMPORT_RECMIN).settings, ())
        for op_type in (DESURVEY, "dh.unknown"):
            with self.subTest(op_type=op_type):
                with self.assertRaisesRegex(ValueError, op_type):
                    provenance.operation_defs({}, op_types=(IMPORT_TABULAR,),
                                              settings={op_type: shown})

    def test_function_where_it_belongs(self) -> None:
        """RF-008-26, RF-008-27: una repetible sin su función, una importación o la
        exportación con función, un tipo que no es de la 005 o una función para un tipo que no
        se construye son errores del programa (``ValueError``), antes de registrar nada."""
        functions = _recompute_all()
        missing = dict(functions)
        del missing[DESURVEY]
        with self.assertRaisesRegex(ValueError, DESURVEY):
            provenance.operation_defs(missing)
        with self.assertRaisesRegex(ValueError, VALIDATE):
            provenance.operation_def(VALIDATE)
        for op_type in (*IMPORTS, EXPORT):
            with self.subTest(op_type=op_type):
                with self.assertRaisesRegex(ValueError, op_type):
                    provenance.operation_def(op_type, _function(op_type))
                with self.assertRaisesRegex(ValueError, op_type):
                    provenance.operation_defs({**functions, op_type: _function(op_type)})
        for wrong in ("dh.unknown", "gis.resample", "dh.import_drillholes"):
            with self.subTest(op_type=wrong):
                with self.assertRaisesRegex(ValueError, wrong):
                    provenance.operation_def(wrong)
                with self.assertRaisesRegex(ValueError, wrong):
                    provenance.operation_defs({}, op_types=(wrong,))
        with self.assertRaisesRegex(ValueError, DESURVEY):
            provenance.operation_defs({DESURVEY: _function(DESURVEY)}, op_types=(VALIDATE,))
        with self.assertRaisesRegex(ValueError, IMPORT_RECMIN):
            provenance.operation_defs({}, op_types=(IMPORT_RECMIN, IMPORT_RECMIN))
        with self.assertRaises(TypeError):
            provenance.operation_def(BUILD_BASE, "no es una función")

    def test_commands_in_the_catalog_of_003(self) -> None:
        """RF-008-61 (plan §5.6.4): cada ``bl_idname`` que lanza un tipo de la 005 está en el
        catálogo de comandos de la 003 como operador de ``dh`` de la entrada ``005``."""
        cat = catalog.load()
        idnames = cat.operator_idnames()
        for declared in provenance.OPERATION_TYPES:
            self.assertTrue(declared.commands, declared.op_type)
            for command in declared.commands:
                with self.subTest(op_type=declared.op_type, command=command):
                    self.assertIn(command, idnames)
                    self.assertEqual(cat.commands[command].module, "dh")
                    self.assertEqual(cat.commands[command].entry, "005")

    def test_labels_with_their_spanish(self) -> None:
        """RF-005-12 (principio 10): cada tipo tiene su nombre visible (``msgid`` en inglés,
        sin marcadores) con su español en ``core/i18n/messages.toml``; seis nombres
        distintos."""
        table = i18n.load_messages()
        labels = [t.label_msgid for t in provenance.OPERATION_TYPES]
        self.assertEqual(len(set(labels)), len(PLAN))
        for declared in provenance.OPERATION_TYPES:
            label = declared.label_msgid
            with self.subTest(op_type=declared.op_type, label=label):
                self.assertEqual(set(label) & SPANISH_LETTERS, set(), "msgid en inglés")
                self.assertEqual(i18n.placeholders(label), set())
                self.assertIn(label, table)
                self.assertNotEqual(table[label], label)
                self.assertEqual(i18n.translate("es", label), table[label])

    def test_no_figures(self) -> None:
        """RF-005-12 (plan §5.6.4, spec §11): la 005 no declara ninguna cifra: ningún
        ``FigureDef`` en el módulo, y registrar sus tipos no registra ninguna."""
        declared = [name for name, value in vars(provenance).items()
                    if isinstance(value, contract.FigureDef)
                    or (isinstance(value, tuple)
                        and any(isinstance(item, contract.FigureDef) for item in value))]
        self.assertEqual(declared, [])
        self.assertFalse(hasattr(provenance, "figure_defs"))
        with registered(*provenance.operation_defs(_recompute_all())):
            self.assertEqual([key for key in contract.FIGURES if key.startswith("dh.")], [])


class ImportersTest(_RegistryCase):
    def test_reader_of_each_import(self) -> None:
        """RF-005-12, RF-008-11 (plan §5.6.2): los lectores de las importaciones, con su
        versión y sin ella, y el tipo de la entrada que da cada uno: unas bocas (de CSV o
        XLSX) y una base de RecMin, ``drillholes``; las demás tablas, ``table``."""
        self.assertEqual(provenance.IMPORT_READERS, ("io.dh_csv", "io.dh_xlsx", "io.recmin_mdb"))
        self.assertEqual(provenance.READER_IDS, (CSV, XLSX, RECMIN))
        self.assertEqual(provenance.TABLE_ROLES, tuple(ROLE_CONVENTIONS))
        for reader in (CSV, XLSX):
            for role in ROLE_CONVENTIONS:
                with self.subTest(reader=reader, role=role):
                    self.assertEqual(provenance.input_kind(reader, role),
                                     "drillholes" if role == "collar" else "table")
                    self.assertEqual(provenance.source_role(role), SOURCE_OF_ROLE[role])
        self.assertEqual(provenance.input_kind(RECMIN), "drillholes")
        for wrong in ((CSV, None), (CSV, "assay"), (RECMIN, "collar"), ("io.dh_csv", "collar"),
                      ("gis.points_text@1", "collar")):
            with self.subTest(wrong=wrong):
                with self.assertRaises(ValueError):
                    provenance.input_kind(*wrong)
        with self.assertRaises(ValueError):
            provenance.source_role("assay")

    def test_importers_registered_and_removed_without_trace(self) -> None:
        """RF-008-11 (plan §5.6.4): un ``ImporterDef`` por lector de importación, con la
        función de reimportación que le da ``bl``, se registra y se quita sin rastro; un
        lector que no es de una importación de la 005 es un error del programa."""
        before = snapshot()
        defs = [provenance.importer_def(reader_id, _function(reader_id))
                for reader_id in provenance.IMPORT_READERS]
        with registered(*defs):
            for definition in defs:
                with self.subTest(reader=definition.reader_id):
                    self.assertIsInstance(definition, contract.ImporterDef)
                    self.assertIs(contract.importer_def(definition.reader_id), definition)
                    self.assertEqual(definition.module, "io")
        self.assertEqual(snapshot(), before)
        for wrong in ("io.dh_csv@1", "gis.geotiff", "io.unknown"):
            with self.subTest(reader=wrong):
                with self.assertRaisesRegex(ValueError, wrong):
                    provenance.importer_def(wrong, _function(wrong))
        with self.assertRaises(TypeError):
            provenance.importer_def("io.dh_csv", None)


class DatasetSpecsTest(_RegistryCase):
    def test_output_roles(self) -> None:
        """RF-008-17 (plan §5.6.1 y §5.6.4): cada tabla de los sondeos tiene su papel de
        salida, distinto en cada una (por él se busca el sucesor de lo sustituido); lo
        importado de cada papel, el suyo."""
        self.assertEqual(dict(provenance.OUTPUT_ROLES), OUTPUT_ROLES)
        self.assertEqual(list(provenance.OUTPUT_ROLES), list(schema.LAYOUTS))
        roles = list(OUTPUT_ROLES.values())
        self.assertEqual(len(set(roles)), len(roles))

    def test_specs_pass_the_checks_of_core_datasets(self) -> None:
        """RF-008-17, RF-008-52 (plan §5.6.1, D17): cada ``DatasetSpec`` pasa las
        comprobaciones de ``core.datasets``: una tabla, un dato, en ``project.gpkg`` con
        ``core.gpkg_layer@1`` (que da su tipo: ``vector`` las bocas y las trazas, ``table``
        las demás); la base y lo calculado, con el nombre de su tabla y sin entrada; lo
        importado, ``dh_src_<rol>_<nombre>`` en la tabla con el uid corto de su entrada,
        inmutable con ella y sin selector; ninguno editable a mano en QGIS."""
        specs = [(table, provenance.dataset_spec(table))
                 for table in (*schema.BASE_TABLES, *schema.COMPUTED_TABLES)]
        specs += [(f"dh_src_{role}", provenance.source_spec(role, NAME, INPUT_UID))
                  for role in schema.SOURCE_ROLES]
        self.assertEqual([table for table, _spec in specs], list(schema.LAYOUTS))
        with _readers_registered(builtin.GPKG_LAYER):
            for table, spec in specs:
                imported = table.startswith("dh_src_")
                with self.subTest(table=table):
                    self.assertIsInstance(spec, datasets.DatasetSpec)
                    self.assertEqual((spec.module, str(spec.store)), ("dh", "gpkg"))
                    self.assertEqual(spec.kind, "vector" if table in ("dh_collar", "dh_trace")
                                     else "table")
                    self.assertEqual(spec.kind, schema.LAYOUTS[table].kind)
                    self.assertEqual(spec.reader, builtin.GPKG_LAYER.id)
                    self.assertEqual(spec.role, OUTPUT_ROLES[table])
                    self.assertIsNone(spec.selector)
                    self.assertEqual(spec.selector_json, "")
                    self.assertFalse(spec.qgis_editable)
                    self.assertTrue(spec.tracked)
                    self.assertIsNone(spec.content)
                    self.assertIs(spec.immutable, imported)
                    if imported:
                        self.assertEqual(spec.name, f"{table}_{SLUG}")
                        self.assertEqual(spec.locator, f"{table}_{SLUG}_{TAG}")
                        self.assertEqual(spec.name, schema.source_name(spec.role[7:], NAME))
                        self.assertEqual(spec.locator,
                                         schema.source_table(spec.role[7:], NAME, INPUT_UID))
                        self.assertEqual(spec.input_uid, INPUT_UID)
                        self.assertIs(schema.layout_of(spec.locator), schema.LAYOUTS[table])
                    else:
                        self.assertEqual((spec.name, spec.locator), (table, table))
                        self.assertIsNone(spec.input_uid)
                    self.assertIn(spec.kind, readers.reader(spec.reader).kinds)
                    self.assertEqual(dataclasses.replace(spec), spec)

    def test_spec_values_pass_through(self) -> None:
        """RF-005-22, RF-008-17: el hash que da el trabajo (con el lector del dato), el EPSG y
        el detalle (los sondeos cambiados) llegan a la ``DatasetSpec``; un hash de otro lector
        lo rechaza ``core.datasets``."""
        digest = encoder.ContentDigest("a" * 64, "b" * 64, encoder.NORMALIZER,
                                       builtin.GPKG_LAYER.id)
        spec = provenance.dataset_spec("dh_collar", content=digest, crs_epsg=25830,
                                       detail={"holes": ["S-01", "S-12"]})
        self.assertIs(spec.content, digest)
        self.assertEqual(spec.crs_epsg, 25830)
        self.assertEqual(spec.detail_json, '{"holes":["S-01","S-12"]}')
        imported = provenance.source_spec("collar", NAME, INPUT_UID, content=digest,
                                          crs_epsg=23030)
        self.assertEqual((imported.content, imported.crs_epsg), (digest, 23030))
        other = encoder.ContentDigest("a" * 64, "b" * 64, encoder.NORMALIZER, "gis.geotiff@1")
        with self.assertRaisesRegex(ValueError, "gis.geotiff@1"):
            provenance.dataset_spec("dh_trace", content=other)

    def test_wrong_names(self) -> None:
        """RF-008-52 (plan §5.6.1): ``dataset_spec`` es de la base y lo calculado, y
        ``source_spec`` de lo importado de una entrada; otra tabla, otro papel o un uid que no
        lo es son ``ValueError``; un nombre sin letras ni cifras, el error para el usuario
        ``dh.dataset_name_invalid``."""
        for wrong in ("dh_src_collar", "dh_unknown", "gis_dtm_topo", f"dh_src_collar_x_{TAG}"):
            with self.subTest(table=wrong):
                with self.assertRaisesRegex(ValueError, wrong):
                    provenance.dataset_spec(wrong)
        with self.assertRaisesRegex(ValueError, "assay_wide"):
            provenance.source_spec("assay_wide", NAME, INPUT_UID)
        with self.assertRaises(ValueError):
            provenance.source_spec("collar", NAME, "no es un uid")
        with self.assertRaises(errors.ValidationError) as caught:
            provenance.source_spec("collar", "¿?", INPUT_UID)
        self.assertEqual(caught.exception.code, "dh.dataset_name_invalid")


class InputSpecTest(unittest.TestCase):
    def test_one_input_per_file(self) -> None:
        """RF-005-07, RF-008-07 (plan §5.6.4, D-15): una entrada por fichero (por hoja de un
        XLSX; la base de RecMin, una), del módulo ``dh`` con su lector; unas bocas y una base de
        RecMin son ``drillholes`` con el CRS y el datum declarados; las demás tablas, ``table``
        sin CRS («no aplica»); la hoja de un XLSX es su capa."""
        declaration = _declaration()
        for reader in (CSV, XLSX):
            for role in ROLE_CONVENTIONS:
                with self.subTest(reader=reader, role=role):
                    spec = provenance.input_spec(reader, "bocas",
                                                 **_arguments(reader, role, declaration))
                    self.assertIsInstance(spec, inputs.InputSpec)
                    self.assertEqual((spec.module, spec.reader), ("dh", reader))
                    self.assertEqual(spec.layer, "Bocas" if reader == XLSX else None)
                    if role == "collar":
                        self.assertEqual(spec.kind, "drillholes")
                        self.assertEqual((dict(spec.crs_h), dict(spec.crs_v)), (ETRS89, REDNAP))
                    else:
                        self.assertEqual(spec.kind, "table")
                        self.assertEqual((dict(spec.crs_h), dict(spec.crs_v)),
                                         (NOT_APPLICABLE, NOT_APPLICABLE))
        spec = provenance.input_spec(RECMIN, "base", **_arguments(RECMIN, None, declaration))
        self.assertEqual((spec.kind, spec.module, spec.layer), ("drillholes", "dh", None))
        self.assertEqual((dict(spec.crs_h), dict(spec.crs_v)), (ETRS89, REDNAP))
        survey = _declaration(crs=None, vertical=None)
        spec = provenance.input_spec(CSV, "desviaciones",
                                     **_arguments(CSV, "survey", survey))
        self.assertEqual(dict(spec.crs_v), NOT_APPLICABLE)

    def test_conventions_are_content_and_reading_settings_are_not(self) -> None:
        """RF-005-07 (plan §5.6.2, ADR-0024 §3): de una tabla, su papel, su correspondencia de
        columnas y las convenciones de su papel son contenido (sus declaraciones); el
        separador, el decimal, la codificación, la cabecera y el formato de las fechas son
        ajustes de lectura: el mismo CSV con «;» y coma o con «,» y punto da las mismas
        declaraciones, y una convención de otro papel ni se guarda ni cambia nada."""
        declaration = _declaration(value_rules=model.ValueRules(",", frozenset({"ND", "-99"})))
        for role, conventions in ROLE_CONVENTIONS.items():
            with self.subTest(role=role):
                spec = provenance.input_spec(CSV, "fichero",
                                             **_arguments(CSV, role, declaration))
                self.assertEqual(spec.content_settings_keys,
                                 tuple(sorted(("mapping", "role", *conventions))))
                expected = {key: declaration.conventions()[key] for key in conventions}
                self.assertEqual(dict(spec.declarations["conventions"]),
                                 {"mapping": MAPPING, "role": role, **expected})
                self.assertEqual(dict(spec.settings), {
                    "role": role, "mapping": MAPPING, **CSV_SETTINGS, "decimal": ",",
                    "date_format": "%d/%m/%Y", **expected})
                point = _declaration(value_rules=model.ValueRules(".", frozenset({"ND", "-99"})),
                                     date_format="%Y-%m-%d")
                other = provenance.input_spec(
                    CSV, "fichero", **_arguments(CSV, role, point, settings={
                        **CSV_SETTINGS, "separator": ",", "encoding": "cp1252",
                        "header_row": 2}))
                self.assertEqual(other.declarations, spec.declarations)
                self.assertNotEqual(other.settings_sha256, spec.settings_sha256)
        recmin = provenance.input_spec(RECMIN, "base", **_arguments(RECMIN, None, declaration))
        self.assertEqual(recmin.content_settings_keys, RECMIN_CONVENTIONS)
        self.assertEqual(dict(recmin.settings), {
            "decimal": ",", **{key: declaration.conventions()[key]
                               for key in RECMIN_CONVENTIONS}})
        changes = {
            "azimuth_ref": dict(azimuth_ref=model.AzimuthRef.MAGNETIC, declination_deg=0.25),
            "inclination_convention": dict(
                inclination_convention=model.InclinationConvention.POSITIVE_DOWN),
            "all_vertical": dict(all_vertical=False),
            "units": dict(units={"Au": "ppb", "Ag": "ppm", "Cu": "%"}),
            "sentinels": dict(value_rules=model.ValueRules(",", frozenset({"-99"}))),
            "negative_is_below_dl": dict(
                value_rules=model.ValueRules(",", negative_is_below_dl=True)),
            "density_kind": dict(density_kind="MEDIDO"),
        }
        base = _declaration()
        for key, change in changes.items():
            changed = _declaration(**change)
            for role, conventions in ROLE_CONVENTIONS.items():
                with self.subTest(change=key, role=role):
                    before = provenance.source_declarations(CSV, base, role=role,
                                                            mapping=MAPPING)
                    after = provenance.source_declarations(CSV, changed, role=role,
                                                           mapping=MAPPING)
                    self.assertEqual(before != after, key in conventions)
            with self.subTest(change=key, role="recmin"):
                self.assertEqual(provenance.source_declarations(RECMIN, base)
                                 != provenance.source_declarations(RECMIN, changed),
                                 key in RECMIN_CONVENTIONS)
        other_mapping = {**MAPPING, "z": "Cota"}
        for role in ("lithology", "collar"):
            with self.subTest(mapping=role):
                self.assertNotEqual(
                    provenance.source_declarations(CSV, base, role=role, mapping=MAPPING),
                    provenance.source_declarations(CSV, base, role=role, mapping=other_mapping))
        self.assertNotEqual(
            provenance.source_declarations(CSV, base, role="lithology", mapping=MAPPING),
            provenance.source_declarations(CSV, base, role="survey", mapping=MAPPING))

    def test_declarations_of_the_job(self) -> None:
        """RF-005-12, RF-008-07 (ADR-0024 §3): ``source_declarations`` da las declaraciones
        con que el trabajo calcula el hash de la fuente, las mismas que comprueba la entrada:
        un hash calculado con otras (otro CRS, otro papel) no se acepta."""
        declaration = _declaration()
        for reader, role in ((CSV, "collar"), (XLSX, "assay_wide"), (RECMIN, None)):
            with self.subTest(reader=reader, role=role):
                extra = {"role": role, "mapping": MAPPING} if role else {}
                found = provenance.source_declarations(reader, declaration, **extra)
                spec = provenance.input_spec(reader, "fichero",
                                             **_arguments(reader, role, declaration))
                self.assertEqual(dict(spec.declarations), found)
                self.assertEqual(found, inputs.input_declarations(
                    dict(spec.crs_h), dict(spec.crs_v),
                    {key: spec.settings[key] for key in spec.content_settings_keys}))
        ed50 = provenance.source_declarations(CSV, _declaration(crs=CATALOG.horizontal(23030)),
                                              role="collar", mapping=MAPPING)
        with self.assertRaisesRegex(ValueError, "declaraciones"):
            provenance.input_spec(CSV, "bocas", **_arguments(
                CSV, "collar", declaration, digest=_digest(CSV, "drillholes", ed50)))
        survey = provenance.source_declarations(CSV, declaration, role="survey",
                                                mapping=MAPPING)
        with self.assertRaisesRegex(ValueError, "declaraciones"):
            provenance.input_spec(CSV, "bocas", **_arguments(
                CSV, "lithology", declaration, digest=_digest(CSV, "table", survey)))

    def test_vertical_references(self) -> None:
        """RF-005-07, RF-005-08 (D-12): el datum declarado de las cotas se registra como lo
        registra la 006: uno del catálogo, ``{"epsg": n}``; una referencia local, con su
        nota; la altura elipsoidal ETRS89, ``{"ellipsoidal": 4937}``; sin declarar, ``None``
        (lo rechaza el registro)."""
        cases = (
            (V5782, REDNAP),
            (CATALOG.local_vertical("NP-0 del plano 3"), {"local": "NP-0 del plano 3"}),
            (gis_crs.ELLIPSOIDAL_ETRS89, {"ellipsoidal": 4937}),
        )
        for vertical, expected in cases:
            with self.subTest(vertical=vertical.name):
                declaration = _declaration(vertical=vertical)
                spec = provenance.input_spec(CSV, "bocas",
                                             **_arguments(CSV, "collar", declaration))
                self.assertEqual(dict(spec.crs_v), expected)
                self.assertEqual(provenance.declared_vertical(vertical), expected)
        self.assertIsNone(provenance.declared_vertical(None))
        self.assertIsNone(provenance.declared_crs(None))
        self.assertEqual(provenance.declared_crs(H25830), ETRS89)
        spec = provenance.input_spec(CSV, "bocas", **_arguments(
            CSV, "collar", _declaration(crs=None, vertical=None)))
        self.assertEqual((spec.crs_h, spec.crs_v), (None, None))
        with self.assertRaises(TypeError):
            provenance.declared_vertical(5782)
        with self.assertRaises(TypeError):
            provenance.declared_crs(25830)

    def test_declaration_back_from_the_input(self) -> None:
        """RF-005-07, RF-005-08, RF-005-27 a RF-005-29 (spec 005, T25; plan §5.6.1 y §5.6.10):
        de lo que guarda una entrada (sus CRS y sus ajustes, también tras pasar por JSON, como
        en ``gb_input``) vuelve lo que declaró su fichero para ``dh.build_base``: los CRS de
        unas bocas o de RecMin (``None`` en las demás tablas), las convenciones de su papel, el
        decimal y el formato de las fechas; lo que su papel no declara queda sin declarar. Una
        base de RecMin, con la inclinación negativa hacia abajo; un datum local o una altura
        elipsoidal, los mismos."""
        declaration = _declaration(
            azimuth_ref=model.AzimuthRef.MAGNETIC, declination_deg=0.25,
            inclination_convention=model.InclinationConvention.POSITIVE_DOWN,
            value_rules=model.ValueRules(",", frozenset({"-99", "ND"}), True),
            density_kind="MEDIDO")
        nothing = {"azimuth_ref": None, "declination_deg": None,
                   "inclination_convention": None, "units": {}, "all_vertical": False,
                   "sentinels": [], "negative_is_below_dl": False, "density_kind": "ADOPTADO"}
        for reader in (CSV, XLSX, RECMIN):
            for role in (ROLE_CONVENTIONS if reader != RECMIN else (None,)):
                with self.subTest(reader=reader, role=role):
                    spec = provenance.input_spec(reader, "fichero",
                                                 **_arguments(reader, role, declaration))
                    stored = json.loads(json.dumps(dict(spec.settings)))
                    found = provenance.input_declaration(
                        reader, json.loads(json.dumps(dict(spec.crs_h))),
                        json.loads(json.dumps(dict(spec.crs_v))), stored)
                    self.assertIsInstance(found, model.SourceDeclaration)
                    kept = RECMIN_CONVENTIONS if role is None else ROLE_CONVENTIONS[role]
                    expected = {**nothing, **{key: declaration.conventions()[key]
                                              for key in kept}}
                    if reader == RECMIN:
                        expected["inclination_convention"] = "negative_down"
                    self.assertEqual(found.conventions(), expected)
                    located = role in (None, "collar")
                    self.assertEqual((found.crs, found.vertical),
                                     (H25830, V5782) if located else (None, None))
                    self.assertEqual(found.value_rules.decimal_mark, ",")
                    self.assertEqual(found.date_format,
                                     None if reader == RECMIN else "%d/%m/%Y")
        for vertical in (georef.load_catalog().local_vertical("NP-0 del plano 3"),
                         gis_crs.ELLIPSOIDAL_ETRS89):
            with self.subTest(vertical=vertical.name):
                spec = provenance.input_spec(CSV, "bocas", **_arguments(
                    CSV, "collar", _declaration(vertical=vertical)))
                found = provenance.input_declaration(CSV, dict(spec.crs_h), dict(spec.crs_v),
                                                     dict(spec.settings))
                self.assertEqual(found.vertical, vertical)
        settings = dict(provenance.input_spec(CSV, "bocas", **_arguments(
            CSV, "collar", _declaration())).settings)
        for crs_h, crs_v, changes, error in (
                ({"epsg": 25830}, {"epsg": 5782}, {"decimal": None}, ValueError),
                ({"wkt": "x"}, {"epsg": 5782}, {}, ValueError),
                ({"epsg": 25830}, {"geoid": 1}, {}, ValueError)):
            with self.subTest(crs_h=crs_h, crs_v=crs_v, changes=changes):
                with self.assertRaises(error):
                    provenance.input_declaration(CSV, crs_h, crs_v, {**settings, **changes})
        with self.assertRaises(ValueError):
            provenance.input_declaration("gis.points_text@1", None, None, settings)
        with self.assertRaises(TypeError):
            provenance.input_declaration(CSV, None, None, [("decimal", ",")])

    def test_wrong_arguments(self) -> None:
        """RF-008-07: un lector que no es de una importación de la 005, un papel o una
        correspondencia que faltan o sobran, un ajuste de lectura que falta o que no es de su
        lector o una declaración de otro tipo son errores del programa (el diálogo solo ofrece
        lo válido), antes de crear la entrada."""
        declaration = _declaration()
        good = _arguments(CSV, "collar", declaration)
        cases: list[tuple[type[Exception], str, dict[str, Any]]] = [
            (ValueError, "gis.points_text@1", {}),
            (ValueError, "role", {"role": None}),
            (ValueError, "assay", {"role": "assay"}),
            (ValueError, "mapping", {"mapping": {}}),
            (TypeError, "mapping", {"mapping": [("hole", "Sondeo")]}),
            (TypeError, "mapping", {"mapping": {"hole": 1}}),
            (ValueError, "header_row", {"settings": {"encoding": "utf-8", "separator": ";"}}),
            (ValueError, "sheet", {"settings": {**CSV_SETTINGS, "sheet": "Bocas"}}),
            (ValueError, "header_row", {"settings": {**CSV_SETTINGS, "header_row": -1}}),
            (TypeError, "header_row", {"settings": {**CSV_SETTINGS, "header_row": True}}),
            (ValueError, "separator", {"settings": {**CSV_SETTINGS, "separator": ""}}),
            (TypeError, "declaration", {"declaration": {"crs": 25830}}),
        ]
        for error, text, change in cases:
            with self.subTest(change=change):
                reader = "gis.points_text@1" if text == "gis.points_text@1" else CSV
                with self.assertRaisesRegex(error, text):
                    provenance.input_spec(reader, "bocas", **{**good, **change})
        recmin = _arguments(RECMIN, None, declaration)
        for change in ({"role": "collar"}, {"mapping": MAPPING},
                       {"settings": {"encoding": "utf-8"}}):
            with self.subTest(recmin=change):
                with self.assertRaises(ValueError):
                    provenance.input_spec(RECMIN, "base", **{**recmin, **change})
        with self.assertRaisesRegex(ValueError, "sheet"):
            provenance.input_spec(XLSX, "bocas", **_arguments(XLSX, "collar", declaration,
                                                              settings={"header_row": 0}))
        with self.assertRaises(ValueError):
            provenance.source_declarations(CSV, declaration, role="collar")
        with self.assertRaises(ValueError):
            provenance.source_declarations(RECMIN, declaration, role="collar")


class RegistryTest(unittest.TestCase):
    """Un proyecto real de esquema 2 con los tipos de la 005, el lector de tablas de ``core``
    y los de la T39 (falsos) registrados, y un CSV de bocas fuera del proyecto."""

    def setUp(self) -> None:
        before = (snapshot(), dict(readers.READERS))
        self.addCleanup(lambda: self.assertEqual((snapshot(), dict(readers.READERS)), before))
        self.enterContext(registered(*provenance.operation_defs(_recompute_all())))
        self.enterContext(_readers_registered(builtin.GPKG_LAYER, *FAKE_READERS))
        tmp = self.enterContext(project_tmp("gb-t40-"))
        (tmp / "proyectos").mkdir()
        self.sources = tmp / "fuentes"
        self.sources.mkdir()
        self.source = self.sources / "bocas.csv"
        self.source.write_bytes("Sondeo;X;Y;Z;Profundidad\r\nS-01;700000,5;4400000,25;"
                                "512,75;150\r\n".encode("utf-8"))
        self.userdata = userdata_mod.UserData(tmp / "u")
        self.project = create.create_project(tmp / "proyectos", make_settings(), make_session(),
                                             self.userdata, clock=FakeClock()).project
        self.addCleanup(self.project.close)

    def collars(self, declaration: Any) -> Any:
        """La entrada del CSV de bocas con ``declaration``."""
        stat = self.source.stat()
        values = _arguments(CSV, "collar", declaration)
        values.update(
            files=[input_registry.locate_source(self.source, self.project, self.userdata)],
            file_prints=[inputs.SourcePrint(hashing.sha256_file(self.source),
                                            size=stat.st_size, mtime_ns=stat.st_mtime_ns)])
        return provenance.input_spec(CSV, "bocas", **values)

    def tables(self) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return [conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                    for table in ("gb_input", "gb_input_file", "gb_dataset", "gb_operation_io",
                                  "gpkg_contents")]

    def roles(self, uid: str) -> dict[str, str]:
        """El papel con que la operación ``uid`` escribió cada dato, por su nombre."""
        with self.project.read() as conn:
            rows = conn.execute(
                "SELECT d.name, io.role FROM gb_operation_io io JOIN gb_dataset d "
                "ON d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'out'",
                (uid,)).fetchall()
        return dict(rows)

    def test_collars_without_datum_are_not_registered(self) -> None:
        """RF-005-07, RF-008-07 (D-12, constitución, principio 6): unas bocas sin datum
        vertical declarado (o sin CRS) no se clasifican ni se registran
        (``core.input_crs_missing``), sin escribir nada y con el proyecto en escritura; con
        los dos, sí."""
        before = self.tables()
        handle = operations.begin_operation(self.project, IMPORT_TABULAR, settings={},
                                            executor="blender")
        for axis, declaration in (("vertical", _declaration(vertical=None)),
                                  ("horizontal", _declaration(crs=None))):
            spec = self.collars(declaration)
            with self.subTest(axis=axis):
                with self.project.read() as conn, self.assertRaises(ProvenanceError) as caught:
                    input_registry.classify_import(conn, spec)
                self.assertEqual((caught.exception.code, caught.exception.values["axis"]),
                                 ("core.input_crs_missing", axis))
                with self.assertRaises(ProvenanceError) as caught:
                    with self.project.write_transaction() as conn:
                        input_registry.register_input(conn, self.project, spec,
                                                      operation_uid=handle.uid)
                self.assertEqual((caught.exception.code, caught.exception.values["axis"]),
                                 ("core.input_crs_missing", axis))
                self.assertIn("bocas", str(caught.exception))
                self.assertTrue(self.project.writable)
        self.assertEqual(self.tables()[0:2], before[0:2])
        with self.project.write_transaction() as conn:
            record = input_registry.register_input(conn, self.project,
                                                   self.collars(_declaration()),
                                                   operation_uid=handle.uid)
            handle.complete(conn, software=PYPROJ)
        self.assertEqual((record.kind, record.module, record.reader), ("drillholes", "dh", CSV))
        self.assertEqual((dict(record.crs_h), dict(record.crs_v)), (ETRS89, REDNAP))

    def test_specs_accepted_by_the_registry(self) -> None:
        """RF-005-12, RF-005-20, RF-005-22, RF-008-17, RF-008-52 (plan §5.6.1 y §5.6.4): el
        registro de la 008 acepta cada ``DatasetSpec`` de la 005 con la operación que la
        escribe: la importación registra su entrada y lo importado (inmutable, con su entrada)
        y su informe; ``dh.build_base``, las once tablas de la base; ``dh.validate``, las
        incidencias, y ``dh.desurvey``, las trazas; cada dato con su tipo, su lector y su
        papel."""
        written: dict[str, Any] = {}

        def run(op_type: str, tables: list[tuple[Any, str, Any]], *,
                spec: Any = None, software: Mapping[str, str] | None = None) -> str:
            handle = operations.begin_operation(self.project, op_type, settings={},
                                                executor="blender")
            with self.project.write_transaction() as conn:
                record = None
                if spec is not None:
                    record = input_registry.register_input(conn, self.project, spec,
                                                           operation_uid=handle.uid)
                outputs = []
                for layout, name, make in tables:
                    dataset = make(record)
                    schema.create_table(conn, layout, dataset.locator, 25830)
                    outputs.append(dataset)
                for found in handle.complete(conn, outputs=outputs, software=software):
                    written[found.name] = found
            return handle.uid

        source = schema.source_layout("collar")
        imported = run(IMPORT_TABULAR, [
            (source, "collar", lambda record: provenance.source_spec("collar", NAME,
                                                                     record.uid)),
            (schema.LAYOUTS["dh_import_log"], "log",
             lambda record: provenance.dataset_spec("dh_import_log")),
        ], spec=self.collars(_declaration()), software=PYPROJ)
        built = run(BUILD_BASE, [
            (schema.LAYOUTS[table], table,
             lambda record, table=table: provenance.dataset_spec(
                 table, crs_epsg=25830 if table == "dh_collar" else None,
                 detail={"holes": ["S-01"]} if table == "dh_collar" else None))
            for table in schema.BASE_TABLES
        ], software=PYPROJ)
        validated = run(VALIDATE, [(schema.LAYOUTS["dh_validation_issue"], "issues",
                                    lambda record: provenance.dataset_spec(
                                        "dh_validation_issue"))])
        traced = run(DESURVEY, [(schema.LAYOUTS["dh_trace"], "trace",
                                 lambda record: provenance.dataset_spec("dh_trace",
                                                                        crs_epsg=25830))])
        with self.project.read() as conn:
            (input_uid,) = conn.execute("SELECT uid FROM gb_input").fetchone()
        source_name = f"dh_src_collar_{SLUG}"
        self.assertEqual(self.roles(imported), {source_name: "source_collar",
                                                "dh_import_log": "import_log"})
        self.assertEqual(self.roles(built), dict(zip(BASE, BASE_ROLES, strict=True)))
        self.assertEqual(self.roles(validated), {"dh_validation_issue": "validation_issue"})
        self.assertEqual(self.roles(traced), {"dh_trace": "trace"})
        self.assertEqual(sorted(written), sorted([source_name, "dh_import_log", *BASE,
                                                  "dh_validation_issue", "dh_trace"]))
        found = written[source_name]
        self.assertEqual((found.kind, found.locator, found.input_uid, found.immutable),
                         ("table", f"{source_name}_{input_uid[:8]}", input_uid, True))
        for name, record in written.items():
            with self.subTest(dataset=name):
                self.assertEqual((record.module, str(record.store), record.reader),
                                 ("dh", "gpkg", builtin.GPKG_LAYER.id))
                self.assertEqual(record.kind, "vector" if name in ("dh_collar", "dh_trace")
                                 else "table")
                self.assertFalse(record.qgis_editable)
                self.assertEqual(record.crs_epsg,
                                 25830 if name in ("dh_collar", "dh_trace") else None)
                if name != source_name:
                    self.assertEqual((record.locator, record.input_uid, record.immutable),
                                     (name, None, False))
        with self.project.read() as conn:
            detail = conn.execute(
                "SELECT c.detail FROM gb_dataset_change c JOIN gb_dataset d ON d.uid = "
                "c.dataset_uid WHERE d.name = 'dh_collar'").fetchone()
        self.assertEqual(detail, ('{"holes":["S-01"]}',))


if __name__ == "__main__":
    unittest.main()

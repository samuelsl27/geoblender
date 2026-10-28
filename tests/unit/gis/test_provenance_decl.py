# SPDX-License-Identifier: GPL-3.0-or-later
"""Declaraciones de procedencia de la 006 (spec 006, T41; RF-006-26; RF-008-17, RF-008-25,
RF-008-26, RF-008-27; ADR-0025 §2; plan 006 §5.6.3, D8 y D22).

``gis.provenance`` declara con tipos de ``core`` lo que la topografía registra en la
procedencia de la 008, sin registrar nada (lo registra ``bl/ops/gis.py``):

- los **tipos de operación** del plan §5.6.3, todos en la versión ``1.0``: las importaciones y
  las exportaciones no se repiten solas (quedan «revisar a mano», RF-008-27) y las demás sí,
  con la función de recálculo que les da ``bl`` (RF-008-26); ninguna está acoplada a otra
  (RF-008-25: la cadena de trabajos de un TIN es una sola operación); sus órdenes son las del
  catálogo de la 003 y sus bibliotecas, ``pyproj`` y el triangulador;
- el **lector de cada importación** (los de ``gis.content``) y el ``ImporterDef`` de cada uno;
- los **nombres de los datos** (``gis_src_``, ``gis_dtm_``, ``gis_tin_``, ``gis_pts_``,
  ``gis_brk_``, ``gis_cnt_``, ``gis_bnd_`` y, de la spec 011 (D-32), ``gis_dom_``, los
  dominios de una capa importada + el nombre de la orden en minúsculas) y la
  ``DatasetSpec`` de cada uno (RF-008-17): tipo, almacén, ubicación (lo importado, con el uid
  corto de su entrada, D22), lector y, lo importado, inmutable con su entrada y sin selector
  (una tabla por dato, D8);
- ninguna cifra (``FigureDef``): los informes de la 006 son diagnósticos.

Cada prueba deja los registros de ``core`` (operaciones, grupos, cifras, importadores y
lectores) como los encontró.
"""

from __future__ import annotations

import dataclasses
import unittest
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered, snapshot

provenance = import_geoblender("gis.provenance")
gis_content = import_geoblender("gis.content")
messages = import_geoblender("gis.messages")
contract = import_geoblender("core.provenance.contract")
datasets = import_geoblender("core.datasets")
readers = import_geoblender("core.content.readers")
builtin = import_geoblender("core.content.builtin")
encoder = import_geoblender("core.content.encoder")
catalog = import_geoblender("core.catalog")
i18n = import_geoblender("core.i18n")

SPANISH_LETTERS = frozenset("áéíóúüñÁÉÍÓÚÜÑ¿¡")

# Plan 006 §5.6.3, copiado: tipo → (repetible, órdenes, consume, produce, bibliotecas); una
# capa importada da también los dominios de una cubicación («dom»: plan 011 D-32, T18).
PLAN: dict[str, tuple[bool, tuple[str, ...], tuple[str, ...], tuple[str, ...],
                      tuple[str, ...]]] = {
    "gis.import_dtm": (False, ("geoblender.gis_import_dtm",), (), ("src",), ()),
    "gis.import_points": (False, ("geoblender.gis_import_points",), (), ("pts", "brk"), ()),
    "gis.import_vector": (False, ("geoblender.gis_import_vector",), (),
                          ("pts", "brk", "cnt", "bnd", "dom", "fea"), ()),
    "gis.resample": (True, ("geoblender.gis_resample_to_grid",), ("source",), ("dtm",),
                     ("pyproj",)),
    "gis.tin_from_points": (True, ("geoblender.gis_create_tin_from_points",),
                            ("points", "breaklines", "boundary"), ("tin",), ("triangulator",)),
    "gis.tin_from_contours": (True, ("geoblender.gis_create_tin_from_contours",),
                              ("contours", "spot_heights", "boundary"), ("tin",),
                              ("triangulator",)),
    "gis.grid_to_tin": (True, ("geoblender.gis_convert_dtm_tin",), ("source",), ("tin",), ()),
    "gis.tin_to_grid": (True, ("geoblender.gis_convert_dtm_tin",), ("source",), ("dtm",), ()),
    "gis.contours": (True, ("geoblender.gis_create_contours",), ("source",), ("cnt",), ()),
    "gis.export_raster": (False, ("geoblender.gis_export_raster",), ("exported",), (), ()),
    "gis.export_gpkg": (False, ("geoblender.gis_export_gpkg",), ("exported",), (), ()),
}
IMPORTS = ("gis.import_dtm", "gis.import_points", "gis.import_vector")
EXPORTS = ("gis.export_raster", "gis.export_gpkg")
# Plan §5.6.2 y §5.6.3: los lectores de cada importación.
IMPORT_READERS = {
    "gis.import_dtm": ("gis.geotiff@1", "gis.asc@1", "gis.xyz_grid@1"),
    "gis.import_points": ("gis.points_text@1",),
    "gis.import_vector": ("gis.gpkg_layer@1",),
}
# Plan §5.2.1 a §5.2.4, §5.6.2 y §5.6.3: familia → (tipo, almacén, lector, importado,
# calculado, extensión).
FAMILIES = {
    "src": ("raster", "rasters", "gis.geotiff@1", True, False, ".tif"),
    "dtm": ("raster", "rasters", "gis.geotiff@1", False, True, ".tif"),
    "tin": ("mesh", "meshes", "core.npz_mesh@1", False, True, ".npz"),
    "pts": ("vector", "gpkg", "core.gpkg_layer@1", True, False, ""),
    "brk": ("vector", "gpkg", "core.gpkg_layer@1", True, False, ""),
    "cnt": ("vector", "gpkg", "core.gpkg_layer@1", True, True, ""),
    "bnd": ("vector", "gpkg", "core.gpkg_layer@1", True, False, ""),
    "dom": ("vector", "gpkg", "core.gpkg_layer@1", True, False, ""),  # plan 011 D-32
    "fea": ("vector", "gpkg", "core.gpkg_layer@1", True, False, ""),  # plan 012 D-27
}
INPUT_UID = "3f2b9c1d-8e7a-4b6c-9d0e-1a2b3c4d5e6f"
TAG = "3f2b9c1d"


def _function(op_type: str) -> Any:
    """Una función de recálculo o de reimportación de prueba, distinta por tipo (nunca se
    llama aquí)."""

    def run(request: Any) -> Any:
        return (op_type, request)

    run.__name__ = f"run_{op_type.replace('.', '_')}"
    return run


def _recompute_all() -> dict[str, Any]:
    return {op_type: _function(op_type) for op_type, row in PLAN.items() if row[0]}


@contextmanager
def _readers_registered() -> Iterator[None]:
    """Registra los lectores de ``core`` y de ``gis`` que aún no estén y los quita al salir."""
    done: list[str] = []
    try:
        for reader in (*builtin.CONTENT_READERS, *gis_content.CONTENT_READERS):
            if reader.id not in readers.READERS:
                readers.register_reader(reader)
                done.append(reader.id)
        yield
    finally:
        for reader_id in reversed(done):
            readers.unregister_reader(reader_id)


class _RegistryCase(unittest.TestCase):
    """Comprueba al terminar cada prueba que los registros de ``core`` están como al
    empezarla."""

    def setUp(self) -> None:
        before = (snapshot(), dict(readers.READERS))
        self.addCleanup(lambda: self.assertEqual((snapshot(), dict(readers.READERS)), before,
                                                 "la prueba dejó algo registrado"))


class OperationTypesTest(_RegistryCase):
    def test_types_of_the_plan(self) -> None:
        """RF-006-26, RF-008-17, RF-008-25 (plan §5.6.3): los once tipos de la tabla del plan,
        en su orden, en la versión ``1.0``, con lo que consumen (sus papeles), lo que producen
        (sus familias de datos), sus órdenes y sus bibliotecas."""
        self.assertEqual(provenance.OP_VERSION, "1.0")
        found = {t.op_type: t for t in provenance.OPERATION_TYPES}
        self.assertEqual([t.op_type for t in provenance.OPERATION_TYPES], list(PLAN))
        self.assertEqual(dict(provenance.OPERATION_TYPES_BY_NAME), found)
        for op_type, (repeatable, commands, inputs, outputs, libraries) in PLAN.items():
            with self.subTest(op_type=op_type):
                declared = found[op_type]
                self.assertEqual(declared.repeatable, repeatable)
                self.assertEqual(declared.commands, commands)
                self.assertEqual(declared.inputs, inputs)
                self.assertEqual(declared.outputs, outputs)
                self.assertEqual(declared.libraries, libraries)
                self.assertEqual(declared.readers, IMPORT_READERS.get(op_type, ()))
        self.assertEqual(provenance.IMPORTS, IMPORTS)
        self.assertEqual(provenance.EXPORTS, EXPORTS)
        self.assertEqual(provenance.REPEATABLE,
                         tuple(op_type for op_type, row in PLAN.items() if row[0]))

    def test_definitions_registered_and_removed_without_trace(self) -> None:
        """RF-008-17, RF-008-26, RF-008-27 (ADR-0025 §2): con funciones de recálculo de prueba,
        cada ``OperationDef`` se crea (módulo ``gis``, versión ``1.0``, ámbito del proyecto,
        sin grupo), se registra en ``core.provenance`` y se quita sin dejar rastro; las
        repetibles llevan su función y las importaciones y exportaciones, ninguna."""
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
                    self.assertEqual((definition.version, definition.module), ("1.0", "gis"))
                    self.assertEqual(definition.version_tuple, (1, 0))
                    self.assertIsNone(definition.group)
                    self.assertEqual(definition.scope, "project")
                    declared = provenance.OPERATION_TYPES_BY_NAME[op_type]
                    self.assertEqual(definition.label_msgid, declared.label_msgid)
                    self.assertEqual(definition.commands, declared.commands)
                    self.assertEqual(definition.libraries, declared.libraries)
                    if op_type in IMPORTS or op_type in EXPORTS:
                        self.assertFalse(definition.repeatable)
                        self.assertIsNone(definition.recompute)
                    else:
                        self.assertTrue(definition.repeatable)
                        self.assertIs(definition.recompute, functions[op_type])
            self.assertFalse([name for name in contract.GROUPS if name.startswith("gis.")])
        self.assertEqual(snapshot(), before)
        for op_type in PLAN:
            with self.subTest(op_type=op_type, registered=False):
                with self.assertRaises(contract.ProvenanceError) as caught:
                    contract.operation_def(op_type)
                self.assertEqual(caught.exception.code, "core.operation_unregistered")

    def test_one_definition_or_a_subset(self) -> None:
        """RF-008-26 (plan §5.6.3): ``bl`` puede construir un tipo (``operation_def``) o unos
        pocos (``op_types``), como hará cada tarea de operadores, y cada uno se registra y se
        quita solo."""
        resample = _function("gis.resample")
        definition = provenance.operation_def("gis.resample", resample)
        self.assertIs(definition.recompute, resample)
        imported = provenance.operation_def("gis.import_dtm")
        self.assertIsNone(imported.recompute)
        subset = provenance.operation_defs({"gis.resample": resample},
                                           op_types=("gis.import_dtm", "gis.resample"))
        self.assertEqual([d.op_type for d in subset], ["gis.import_dtm", "gis.resample"])
        self.assertEqual(subset[1], definition)
        with registered(*subset):
            self.assertEqual(sorted(name for name in contract.OPERATIONS
                                    if name.startswith("gis.")),
                             ["gis.import_dtm", "gis.resample"])

    def test_settings_shown_in_the_provenance(self) -> None:
        """RF-008-29 (T58): ``bl`` da a cada tipo los ajustes de su orden que enseña su
        procedencia (``settings``, por tipo) y ``operation_def(s)`` se los pone, a los demás
        ninguno; unos de un tipo que no se construye o que no es de la 006 son un error del
        programa."""
        shown = (contract.SettingDef("interval_m", "Interval", unit="m"),
                 contract.SettingDef("base_m", "Base elevation", unit="m"))
        definitions = provenance.operation_defs(_recompute_all(),
                                                settings={"gis.contours": shown})
        self.assertEqual({d.op_type: d.settings for d in definitions if d.settings},
                         {"gis.contours": shown})
        alone = provenance.operation_def("gis.contours", _function("gis.contours"),
                                         settings=shown)
        self.assertEqual(alone.settings, shown)
        self.assertEqual(provenance.operation_def("gis.import_dtm").settings, ())
        for op_type in ("gis.contours", "gis.unknown"):
            with self.subTest(op_type=op_type):
                with self.assertRaisesRegex(ValueError, op_type):
                    provenance.operation_defs({}, op_types=("gis.import_dtm",),
                                              settings={op_type: shown})

    def test_function_where_it_belongs(self) -> None:
        """RF-008-26, RF-008-27: una repetible sin su función, una importación o una
        exportación con función, un tipo que no es de la 006 o una función para un tipo que no
        se construye son errores del programa (``ValueError``), antes de registrar nada."""
        functions = _recompute_all()
        missing = dict(functions)
        del missing["gis.contours"]
        with self.assertRaisesRegex(ValueError, "gis.contours"):
            provenance.operation_defs(missing)
        with self.assertRaisesRegex(ValueError, "gis.resample"):
            provenance.operation_def("gis.resample")
        for op_type in (*IMPORTS, *EXPORTS):
            with self.subTest(op_type=op_type):
                with self.assertRaisesRegex(ValueError, op_type):
                    provenance.operation_def(op_type, _function(op_type))
                with self.assertRaisesRegex(ValueError, op_type):
                    provenance.operation_defs({**functions, op_type: _function(op_type)})
        for wrong in ("gis.unknown", "core.import_layer", "gis.validate_surface"):
            with self.subTest(op_type=wrong):
                with self.assertRaisesRegex(ValueError, wrong):
                    provenance.operation_def(wrong)
                with self.assertRaisesRegex(ValueError, wrong):
                    provenance.operation_defs({}, op_types=(wrong,))
        with self.assertRaisesRegex(ValueError, "gis.contours"):
            provenance.operation_defs({"gis.contours": _function("gis.contours")},
                                      op_types=("gis.resample",))
        with self.assertRaisesRegex(ValueError, "gis.import_dtm"):
            provenance.operation_defs({}, op_types=("gis.import_dtm", "gis.import_dtm"))
        with self.assertRaises(TypeError):
            provenance.operation_def("gis.resample", "no es una función")

    def test_commands_in_the_catalog_of_003(self) -> None:
        """RF-008-61 (plan §5.3.5 y §5.6.3): cada ``bl_idname`` que lanza un tipo de la 006
        está en el catálogo de comandos de la 003 como operador de ``gis`` de la entrada
        ``006``."""
        cat = catalog.load()
        idnames = cat.operator_idnames()
        for declared in provenance.OPERATION_TYPES:
            self.assertTrue(declared.commands, declared.op_type)
            for command in declared.commands:
                with self.subTest(op_type=declared.op_type, command=command):
                    self.assertIn(command, idnames)
                    self.assertEqual(cat.commands[command].module, "gis")
                    self.assertEqual(cat.commands[command].entry, "006")

    def test_labels_with_their_spanish(self) -> None:
        """RF-006-26 (principio 10): cada tipo tiene su nombre visible (``msgid`` en inglés,
        sin marcadores) con su español en ``core/i18n/messages.toml``; once nombres
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
        """RF-006-26 (plan §5.6.1, spec §11): la 006 no declara ninguna cifra: ningún
        ``FigureDef`` en el módulo, y registrar sus tipos no registra ninguna."""
        declared = [name for name, value in vars(provenance).items()
                    if isinstance(value, contract.FigureDef)
                    or (isinstance(value, tuple)
                        and any(isinstance(item, contract.FigureDef) for item in value))]
        self.assertEqual(declared, [])
        self.assertFalse(hasattr(provenance, "figure_defs"))
        with registered(*provenance.operation_defs(_recompute_all())):
            self.assertEqual([key for key in contract.FIGURES if key.startswith("gis.")], [])


class ImportersTest(_RegistryCase):
    def test_reader_of_each_import(self) -> None:
        """RF-006-26, RF-008-11 (plan §5.6.2, §5.6.3 y §5.6.8): el lector de cada importación
        es uno de ``gis.content``, todos los de ``gis.content`` son de una importación y cada
        uno da el tipo de su entrada (``raster``, ``table`` o ``vector``)."""
        by_id = {reader.id: reader for reader in gis_content.CONTENT_READERS}
        found = [reader_id for op_type in IMPORTS
                 for reader_id in provenance.OPERATION_TYPES_BY_NAME[op_type].readers]
        self.assertEqual(sorted(found), sorted(by_id))
        self.assertEqual(provenance.IMPORT_READERS,
                         tuple(by_id[reader_id].reader_id for reader_id in found))
        kinds = {"gis.geotiff@1": "raster", "gis.asc@1": "raster", "gis.xyz_grid@1": "raster",
                 "gis.points_text@1": "table", "gis.gpkg_layer@1": "vector"}
        for reader_id, kind in kinds.items():
            with self.subTest(reader=reader_id):
                self.assertEqual(provenance.input_kind(reader_id), kind)
                self.assertIn(kind, by_id[reader_id].kinds)
        for wrong in ("core.gpkg_layer@1", "gis.geotiff", "gis.unknown@1"):
            with self.subTest(reader=wrong):
                with self.assertRaisesRegex(ValueError, wrong):
                    provenance.input_kind(wrong)

    def test_importers_registered_and_removed_without_trace(self) -> None:
        """RF-008-11 (plan §5.6.8): un ``ImporterDef`` por lector de importación, con la
        función de reimportación que le da ``bl``, se registra y se quita sin rastro; un
        lector que no es de una importación de la 006 es un error del programa."""
        before = snapshot()
        defs = [provenance.importer_def(reader_id, _function(reader_id))
                for reader_id in provenance.IMPORT_READERS]
        with registered(*defs):
            for definition in defs:
                with self.subTest(reader=definition.reader_id):
                    self.assertIsInstance(definition, contract.ImporterDef)
                    self.assertIs(contract.importer_def(definition.reader_id), definition)
                    self.assertEqual(definition.module, "gis")
        self.assertEqual(snapshot(), before)
        for wrong in ("core.gpkg_layer", "gis.geotiff@1", "gis.unknown"):
            with self.subTest(reader=wrong):
                with self.assertRaisesRegex(ValueError, wrong):
                    provenance.importer_def(wrong, _function(wrong))
        with self.assertRaises(TypeError):
            provenance.importer_def("gis.geotiff", None)

    def test_layer_roles(self) -> None:
        """RF-006-12 (plan §5.6.3), RF-011-07 (plan 011 D-32): una capa importada da
        ``gis_pts_``, ``gis_brk_``, ``gis_cnt_``, ``gis_bnd_`` o ``gis_dom_`` (los dominios de
        una cubicación) según su papel; otro papel es ``ValueError``."""
        self.assertEqual(dict(provenance.LAYER_ROLES),
                         {"points": "pts", "breaklines": "brk", "contours": "cnt",
                          "boundary": "bnd", "domains": "dom", "features": "fea"})
        self.assertEqual(tuple(provenance.LAYER_ROLES.values()),
                         provenance.OPERATION_TYPES_BY_NAME["gis.import_vector"].outputs)
        for role, family in provenance.LAYER_ROLES.items():
            with self.subTest(role=role):
                self.assertEqual(provenance.layer_family(role), family)
        with self.assertRaisesRegex(ValueError, "surface"):
            provenance.layer_family("surface")


class DatasetNamesTest(unittest.TestCase):
    def test_slug(self) -> None:
        """RF-008-17 (plan §5.2.1): el nombre de la orden, en ASCII en minúsculas con «_» (sin
        tildes, «ñ» → «n», y lo demás que no es letra o cifra, un «_»), como mucho
        ``MAX_SLUG_CHARS`` caracteres; un nombre ya en esa forma no cambia."""
        cases = {
            "Topo 2026": "topo_2026",
            "topo_2026": "topo_2026",
            "  MDT Ñandú-vuelo (2025)  ": "mdt_nandu_vuelo_2025",
            "Límite__de   la cantera": "limite_de_la_cantera",
            "Curvas.1m": "curvas_1m",
        }
        for name, slug in cases.items():
            with self.subTest(name=name):
                self.assertEqual(provenance.dataset_slug(name), slug)
                self.assertEqual(provenance.dataset_slug(slug), slug)
        long_name = "Levantamiento " * 10
        slug = provenance.dataset_slug(long_name)
        self.assertLessEqual(len(slug), provenance.MAX_SLUG_CHARS)
        self.assertEqual(provenance.MAX_SLUG_CHARS, 40)
        self.assertFalse(slug.endswith("_"))
        self.assertTrue(long_name.lower().replace(" ", "_").startswith(slug))

    def test_name_without_letters_or_digits(self) -> None:
        """Principio 10: un nombre sin ninguna letra ni cifra no da nombre a un dato: error
        para el usuario ``gis.dataset_name_invalid`` con el valor, en español."""
        for name in ("", "   ", "---", "¿?"):
            with self.subTest(name=name):
                with self.assertRaises(messages.GisError) as caught:
                    provenance.dataset_slug(name)
                error = caught.exception
                self.assertEqual(error.code, "gis.dataset_name_invalid")
                self.assertEqual(error.value, name)
                self.assertIn(f"«{name}»", str(error))
        with self.assertRaises(TypeError):
            provenance.dataset_slug(None)

    def test_dataset_names(self) -> None:
        """RF-008-17 (plan §5.2.1 a §5.2.4): ``gis_<familia>_<nombre>``, el nombre estable del
        dato, igual para lo importado y para lo calculado."""
        for family in FAMILIES:
            with self.subTest(family=family):
                self.assertEqual(provenance.dataset_name(family, "Topo 2026"),
                                 f"gis_{family}_topo_2026")
        with self.assertRaisesRegex(ValueError, "xyz"):
            provenance.dataset_name("xyz", "Topo 2026")

    def test_input_tag(self) -> None:
        """D22: el uid corto de una entrada son las 8 primeras cifras hexadecimales de su uid
        (un UUID v4 en texto); otro texto es ``ValueError``."""
        self.assertEqual(provenance.input_tag(INPUT_UID), TAG)
        self.assertEqual(provenance.input_tag(INPUT_UID.upper()), TAG)
        fresh = str(uuid.uuid4())
        self.assertEqual(provenance.input_tag(fresh), fresh[:8])
        for wrong in ("", "abc", "zzzzzzzz-0000", "3f2b9c1d8e7a"):
            with self.subTest(uid=wrong):
                with self.assertRaises(ValueError):
                    provenance.input_tag(wrong)


class DatasetSpecsTest(_RegistryCase):
    def _specs(self) -> list[tuple[str, bool, Any]]:
        found = []
        for family, (_kind, _store, _reader, imported, computed, _ext) in FAMILIES.items():
            if imported:
                found.append((family, True,
                              provenance.dataset_spec(family, "Topo 2026", input_uid=INPUT_UID)))
            if computed:
                found.append((family, False, provenance.dataset_spec(family, "Topo 2026")))
        return found

    def test_families(self) -> None:
        """RF-008-17 (plan §5.2.4 y §5.6.3): las siete familias de datos (y los dominios de la
        011, D-32) con su tipo, su
        almacén, su lector, si son lo importado o lo calculado y su extensión; un papel de
        salida distinto por familia (el sucesor de lo sustituido se busca por su papel), y
        cada tipo de operación produce familias declaradas, compatibles con su origen."""
        self.assertEqual([f.code for f in provenance.FAMILIES], list(FAMILIES))
        roles = [f.role for f in provenance.FAMILIES]
        self.assertEqual(len(set(roles)), len(roles))
        for declared in provenance.FAMILIES:
            kind, store, reader, imported, computed, extension = FAMILIES[declared.code]
            with self.subTest(family=declared.code):
                self.assertEqual((declared.kind, str(declared.store), declared.reader),
                                 (kind, store, reader))
                self.assertEqual((declared.imported, declared.computed), (imported, computed))
                self.assertEqual(declared.extension, extension)
                self.assertEqual(declared.prefix, f"gis_{declared.code}_")
                self.assertRegex(declared.role, r"^[a-z][a-z0-9_]*$")
        for declared in provenance.OPERATION_TYPES:
            for family in declared.outputs:
                with self.subTest(op_type=declared.op_type, family=family):
                    found = provenance.FAMILIES_BY_CODE[family]
                    if declared.op_type in IMPORTS:
                        self.assertTrue(found.imported)
                    else:
                        self.assertTrue(found.computed)

    def test_specs_pass_the_checks_of_core_datasets(self) -> None:
        """RF-008-17, RF-008-52 (plan §5.6.3, D8 y D22): cada ``DatasetSpec`` pasa las
        comprobaciones de ``core.datasets`` (ubicación relativa dentro de su almacén y lector
        registrado, que da su tipo); lo importado es inmutable con su entrada, sin selector, y
        su ubicación lleva el uid corto de su entrada; lo calculado, no; ninguno es editable
        a mano en QGIS; las tablas se leen con ``core.gpkg_layer@1``, como exige el registro
        de la 008 (``core.dataset_reader_store``)."""
        expected = {
            ("src", True): "rasters/gis_src_topo_2026_3f2b9c1d.tif",
            ("dtm", False): "rasters/gis_dtm_topo_2026.tif",
            ("tin", False): "meshes/gis_tin_topo_2026.npz",
            ("pts", True): "gis_pts_topo_2026_3f2b9c1d",
            ("brk", True): "gis_brk_topo_2026_3f2b9c1d",
            ("cnt", True): "gis_cnt_topo_2026_3f2b9c1d",
            ("cnt", False): "gis_cnt_topo_2026",
            ("bnd", True): "gis_bnd_topo_2026_3f2b9c1d",
            ("dom", True): "gis_dom_topo_2026_3f2b9c1d",
            ("fea", True): "gis_fea_topo_2026_3f2b9c1d",
        }
        specs = self._specs()
        self.assertEqual([(family, imported) for family, imported, _spec in specs],
                         list(expected))
        with _readers_registered():
            for family, imported, spec in specs:
                kind, store, reader_id, *_ = FAMILIES[family]
                with self.subTest(family=family, imported=imported):
                    self.assertIsInstance(spec, datasets.DatasetSpec)
                    self.assertEqual(spec.name, f"gis_{family}_topo_2026")
                    self.assertEqual((spec.module, spec.kind, str(spec.store)),
                                     ("gis", kind, store))
                    self.assertEqual(spec.locator, expected[(family, imported)])
                    self.assertEqual(spec.locator, provenance.dataset_locator(
                        family, "Topo 2026", input_uid=INPUT_UID if imported else None))
                    self.assertEqual(spec.reader, reader_id)
                    self.assertEqual(spec.role, provenance.FAMILIES_BY_CODE[family].role)
                    self.assertIsNone(spec.selector)
                    self.assertEqual(spec.selector_json, "")
                    self.assertIs(spec.immutable, imported)
                    self.assertEqual(spec.input_uid, INPUT_UID if imported else None)
                    self.assertFalse(spec.qgis_editable)
                    self.assertTrue(spec.tracked)
                    self.assertIsNone(spec.content)
                    if spec.store in datasets.FILE_STORES:
                        self.assertTrue(spec.locator.startswith(f"{store}/"))
                        self.assertNotIn("\\", spec.locator)
                    else:
                        self.assertEqual(spec.reader, builtin.GPKG_LAYER.id)
                    content_reader = readers.reader(spec.reader)
                    self.assertIn(spec.kind, content_reader.kinds)
                    again = dataclasses.replace(spec)
                    self.assertEqual(again, spec)

    def test_spec_values_pass_through(self) -> None:
        """RF-008-17: el hash que da el trabajo (con el lector del dato), el EPSG y el detalle
        llegan a la ``DatasetSpec``; un hash de otro lector lo rechaza ``core.datasets``."""
        digest = encoder.ContentDigest("a" * 64, "b" * 64, encoder.NORMALIZER, "gis.geotiff@1")
        spec = provenance.dataset_spec("dtm", "Topo 2026", content=digest, crs_epsg=25830,
                                       detail={"cells": 12})
        self.assertIs(spec.content, digest)
        self.assertEqual(spec.crs_epsg, 25830)
        self.assertEqual(spec.detail_json, '{"cells":12}')
        with self.assertRaisesRegex(ValueError, "gis.geotiff@1"):
            provenance.dataset_spec("tin", "Topo 2026", content=digest)

    def test_origin_rules(self) -> None:
        """RF-008-52 (plan §5.6.3): lo importado (``src``, ``pts``, ``brk``, ``bnd``, ``dom``)
        necesita su entrada; lo calculado (``dtm``, ``tin``) no la tiene; ``cnt`` es de los dos
        (una capa importada o las curvas de una superficie); una familia que no es de la 006 es
        ``ValueError``."""
        for family in ("src", "pts", "brk", "bnd", "dom", "fea"):
            with self.subTest(family=family, input_uid=None):
                with self.assertRaisesRegex(ValueError, f"gis_{family}_"):
                    provenance.dataset_spec(family, "Topo 2026")
        for family in ("dtm", "tin"):
            with self.subTest(family=family, input_uid=INPUT_UID):
                with self.assertRaisesRegex(ValueError, f"gis_{family}_"):
                    provenance.dataset_spec(family, "Topo 2026", input_uid=INPUT_UID)
        with self.assertRaisesRegex(ValueError, "xyz"):
            provenance.dataset_spec("xyz", "Topo 2026")
        with self.assertRaises(ValueError):
            provenance.dataset_spec("pts", "Topo 2026", input_uid="no es un uid")


if __name__ == "__main__":
    unittest.main()

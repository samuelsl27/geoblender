# SPDX-License-Identifier: GPL-3.0-or-later
"""El escritor de proyecto y el ámbito de los parámetros (spec 016, T04; HU-016-1; RF-016-02, RF-016-09; D-15;
plan 016 §2.1, §5.2.3 «El ámbito», §5.7 P-2, §5.8 H-3, §8; ADR-0031 §2; RF-009-05, RF-009-12).

La detección de acopios es **del proyecto si la superficie es del proyecto y de la versión si es de una versión**
(D-15). ``OperationDef.scope`` es uno por tipo (contrato de ``core``, spec 009), así que la detección tiene **dos tipos
de operación con el mismo algoritmo, las mismas familias y el mismo escritor parametrizado por ámbito**
(decisión de la sesión principal, 18/11/2026): ``des.stockpile_detect`` (de versión) y
``des.stockpile_detect_project`` (de proyecto). Estas pruebas comprueban:

- **Sin proyecto** (:class:`DetectionTypesTest`): los dos tipos, el registro de entidades que asocia los dos al tipo
  ``stockpile`` y el aviso de nombre repetido en el proyecto, en los dos idiomas.
- **Con proyecto** (:class:`ScopedWriterTest`, la cantera de la 014 en la rejilla gruesa y un tipo de prueba, ``pile``,
  con sus dos operaciones, registrado solo desde aquí): **los mismos datos** (una rejilla dispersa, una tabla y una
  entidad) escritos en los dos ámbitos y lo único que cambia es **dónde se escriben** (la ruta sin y con el código de
  versión, el ámbito de la operación y de los parámetros); los códigos son correlativos **por ámbito**
  (``PIL-001`` en el proyecto y en cada versión); una operación de proyecto no consume un dato de versión
  (RF-009-05) y una de versión sí consume uno del proyecto; las filas «sin confirmar» que una operación de versión
  deja en el proyecto (trampa de ``begin_operation``, ``docs/trampas.md`` §6) no son entidades del proyecto ni
  impiden crear la suya.
"""

from __future__ import annotations

import unittest
from types import MappingProxyType
from typing import Any, ClassVar
from unittest import mock

import numpy as np

from tests.support import entity_fixtures as efx
from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered

core_params = import_geoblender("core.params")
datasets = import_geoblender("core.datasets.model")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
gis = import_geoblender("gis")
i18n = import_geoblender("core.i18n")
messages = import_geoblender("design.messages")
operations = import_geoblender("core.provenance.operations")
params = import_geoblender("design.params")
provenance = import_geoblender("design.provenance")
store = import_geoblender("design.store")
versions_model = import_geoblender("core.versions.model")
contract = import_geoblender("core.provenance.contract")

PILE = "pile"
PILE_OP, PILE_PROJECT_OP = "des.pile_detect", "des.pile_detect_project"
NAMES = ("name", "discarded", "size_m")
VALUE_TYPES = {"name": "text", "discarded": "bool", "size_m": "float"}
DEFAULTS = {"discarded": False}
OUTPUTS = (provenance.STOCKPILE_BASE_GRID, provenance.ENTITY_REPORT_TABLE)
"""Lo que escribe la operación de prueba: una rejilla dispersa (la base de un material) y una tabla (un informe)."""
BASE = provenance.STOCKPILE_BASE_GRID
REPORT = provenance.ENTITY_REPORT_TABLE
WHO = "Samuel (IMGA)"


def drive(steps: Any) -> Any:
    """Lleva unos pasos hasta el final y devuelve lo que devuelven (``StopIteration.value``)."""
    while True:
        try:
            next(steps)
        except StopIteration as stop:
            return stop.value


def pile_types() -> tuple[Any, Any]:
    """Los dos tipos de operación de prueba, de versión y de proyecto, con lo mismo salvo el ámbito."""
    return (provenance.OperationType(PILE_OP, "Pile of the tests", OUTPUTS, ()),
            provenance.OperationType(PILE_PROJECT_OP, "Pile of the tests of the project", OUTPUTS, (),
                                     scope="project"))


def pile_entity() -> Any:
    """El tipo de entidad de prueba: ``PIL-nnn``, sin cadena, con sus dos operaciones."""
    families = tuple(params.entity_family("des.pile", name, VALUE_TYPES[name], DEFAULTS.get(name), (),
                                          ("RF-016-02",), "Prueba de la T04 de la 016 (sin valor real)",
                                          f"{name} of the pile") for name in NAMES)
    return entities.EntityType(
        params.EntityParams(PILE, "PIL", NAMES, families), PILE_OP, "des.platform_declared_reason",
        "des.support_removed_platform", project_op_type=PILE_PROJECT_OP)


def never(request: Any) -> Any:
    raise AssertionError("las pruebas del escritor de proyecto no recalculan")


class DetectionTypesTest(unittest.TestCase):
    """RF-016-02, RF-016-09, D-15 (ADR-0031 §2; sin proyecto): la detección tiene dos tipos de operación, uno por
    ámbito, que solo se distinguen en eso, y el registro de entidades asocia los dos al tipo ``stockpile``."""

    def test_the_detection_has_one_operation_type_per_scope(self) -> None:
        """RF-016-02, D-15: ``des.stockpile_detect`` (de versión) y ``des.stockpile_detect_project`` (de proyecto) son
        **el mismo algoritmo**: las mismas salidas (las familias de datos de la detección, ``des_stk_``…), los mismos
        ajustes, las mismas cifras, la misma orden y la misma reproducibilidad; solo cambian su nombre, su ``msgid`` y su
        ámbito (``OperationDef.scope``); los trata igual ``OPERATION_TYPES_BY_NAME``."""
        self.assertEqual(provenance.STOCKPILE_DETECT_PROJECT, "des.stockpile_detect_project")
        by_version = provenance.OPERATION_TYPES_BY_NAME[provenance.STOCKPILE_DETECT]
        by_project = provenance.OPERATION_TYPES_BY_NAME[provenance.STOCKPILE_DETECT_PROJECT]
        self.assertIn(by_project, provenance.SUPPORTED_OPERATION_TYPES)
        self.assertEqual((by_version.scope, by_project.scope), ("version", "project"))
        for name in ("outputs", "settings", "figures", "commands", "reproducible", "drops_discarded"):
            with self.subTest(attribute=name):
                self.assertEqual(getattr(by_version, name), getattr(by_project, name))
        self.assertNotEqual(by_version.label_msgid, by_project.label_msgid)
        self.assertEqual(provenance.SUPPORTED_PROJECT_TYPES, (provenance.STOCKPILE_DETECT_PROJECT,))
        self.assertEqual(provenance.STOCKPILE_DETECT_TYPES,
                         (provenance.STOCKPILE_DETECT, provenance.STOCKPILE_DETECT_PROJECT))
        self.assertNotIn(provenance.STOCKPILE_DETECT_PROJECT, provenance.SUPPORTED_VERSION_TYPES)
        self.assertIn(provenance.STOCKPILE_DETECT_PROJECT, provenance.SUPPORTED_REPRODUCIBLE)
        self.assertEqual(provenance.SUPPORTED_TYPES, tuple(t.op_type for t in provenance.SUPPORTED_OPERATION_TYPES))
        built = {item.op_type: item for item in (provenance.operation_def(by_version.op_type, never, never),
                                                  provenance.operation_def(by_project.op_type, never, never))}
        self.assertEqual({op_type: (item.scope, item.repeatable, item.module, item.version)
                          for op_type, item in built.items()},
                         {provenance.STOCKPILE_DETECT: ("version", True, "des", "1.0"),
                          provenance.STOCKPILE_DETECT_PROJECT: ("project", True, "des", "1.0")})
        self.assertEqual(built[provenance.STOCKPILE_DETECT_PROJECT].figure_tolerance, provenance.FIGURE_TOLERANCE)

    def test_the_definitions_of_the_016_are_built_for_the_five_types(self) -> None:
        """RF-008-26, RF-009-11: ``supported_operation_defs`` arma las cinco definiciones, en su orden (las dos de la
        detección juntas), cada una con su función de recálculo y de reproducción; ``ValueError`` si sobra o falta
        alguna (la del tipo de proyecto también)."""
        functions = {op_type: never for op_type in provenance.SUPPORTED_TYPES}
        built = provenance.supported_operation_defs(functions, functions)
        self.assertEqual([item.op_type for item in built], list(provenance.SUPPORTED_TYPES))
        self.assertEqual([item.scope for item in built], ["version", "project", "version", "version", "version"])
        without = {key: value for key, value in functions.items() if key != provenance.STOCKPILE_DETECT_PROJECT}
        with self.assertRaises(ValueError):
            provenance.supported_operation_defs(without, functions)
        with self.assertRaises(ValueError):
            provenance.supported_operation_defs(functions, without)

    def test_the_stockpile_entity_type_has_both_operation_types(self) -> None:
        """RF-016-02, D-15 (H-3): el registro de entidades asocia los **dos** tipos de operación al tipo ``stockpile``
        (el de versión como ``op_type`` de siempre y el de proyecto como ``project_op_type``); ningún otro tipo de
        entidad tiene el de proyecto (la retirada, el contrafuerte y el cuerpo son siempre de versión)."""
        found = entities.entity_type("stockpile")
        self.assertEqual((found.op_type, found.project_op_type),
                         (provenance.STOCKPILE_DETECT, provenance.STOCKPILE_DETECT_PROJECT))
        self.assertEqual(found.op_types, (provenance.STOCKPILE_DETECT, provenance.STOCKPILE_DETECT_PROJECT))
        for other in entities.registered_types():
            if other.kind != "stockpile":
                with self.subTest(kind=other.kind):
                    self.assertIsNone(other.project_op_type)
                    self.assertEqual(other.op_types, (other.op_type,))

    def test_the_operation_labels_have_their_spanish(self) -> None:
        """Principio 10: el nombre del tipo de proyecto es un ``msgid`` en inglés con su traducción."""
        label = provenance.OPERATION_TYPES_BY_NAME[provenance.STOCKPILE_DETECT_PROJECT].label_msgid
        self.assertEqual(i18n.untranslated([label]), [])
        self.assertNotEqual(i18n.load_messages()[label], label)

    def test_a_repeated_name_in_the_project_has_its_own_message(self) -> None:
        """RF-013-17 (el nombre es único en su ámbito): el rechazo de un nombre repetido **en el proyecto** nombra al
        proyecto y no a una versión, en los dos idiomas, con los mismos marcadores."""
        message = messages.MESSAGES["des.operation_name_repeated_project"]
        self.assertEqual(message.severity, "error")
        self.assertEqual(i18n.placeholders(message.msgid), i18n.placeholders(message.es))
        error = messages.DesignError("des.operation_name_repeated_project", obj="Operación «Pila»",
                                     field="nombre", value="Pila", dataset="des_stb_pila")
        self.assertIn("proyecto", error.text)
        self.assertNotIn("{", error.text)
        self.assertIn("project", error.text_in("en"))


class ScopedWriterTest(efx.EntityProjectCase):
    """RF-016-02, RF-016-09, D-15, RF-009-05 con proyecto: V01 con ``PIL-001`` («Pila») y ``PIL-002`` («Pila V3»), el
    proyecto con **su** ``PIL-001`` («Pila», el mismo nombre y los mismos datos que la de V01) y V02 con su
    ``PIL-001`` («Pila V2»), que consume la rejilla de la del proyecto. La de V01 se crea **antes** que la del proyecto
    (sus parámetros dejan filas «sin confirmar» en el proyecto: la trampa); la del proyecto se repite después (un
    recálculo: ``begin`` y ``resume``)."""

    STEP_M = qfx.COARSE_STEP_M
    made: ClassVar[dict[str, Any]] = {}

    @classmethod
    def raster(cls) -> Any:
        """La rejilla de prueba: dispersa (solo 35 celdas con dato), float64, en la rejilla del proyecto."""
        values = np.full(cls.grid.shape, np.nan)
        values[10:15, 20:27] = 100.0 + np.arange(35).reshape(5, 7) / 8.0
        return gis.Raster(cls.grid, values, qfx.CRS, qfx.VERTICAL)

    @staticmethod
    def rows() -> list[tuple[Any, ...]]:
        """Las filas de la tabla de prueba (las columnas de ``des_prp_``: magnitud, valor, unidad y nota)."""
        return [("area_m2", 12.5, "m2", None), ("note", None, None, "dos")]

    @classmethod
    def parameter_rows(cls, code: str, name: str) -> list[Any]:
        """Todas las filas de la entidad ``code`` (el nombre, el valor por defecto y el tamaño)."""
        values: dict[str, Any] = {"name": name, "discarded": False, "size_m": 2.5}
        return [entity_store.EntityParamRow(
            params.entity_key(code, key), key, value, "Prueba de la T04", "person", "Prueba de la T04")
            for key, value in values.items()]

    @classmethod
    def create(cls, scope: str, name: str, *, code: str | None = None, reads: str | None = None,
               version: Any = None, supersedes: str | None = None) -> Any:
        """«Crea» la entidad ``name`` en el ``scope`` (``project`` o ``version``, en ``version``, V01 por defecto):
        las dos salidas del tipo, los parámetros en la misma transacción que la operación y la operación. Devuelve
        lo guardado (``Stored``)."""
        where = version or cls.v1
        op_type = PILE_PROJECT_OP if scope == "project" else PILE_OP
        owner = None if scope == "project" else where
        listed = (entities.project_registry(cls.project) if owner is None
                  else entities.registry(cls.project, owner.uid))
        chosen = code or entities.next_code(PILE, (entry.record.code for entry in listed))
        keys = tuple(params.entity_key(chosen, key) for key in NAMES)
        inputs = () if reads is None else (operations.Use(reads, provenance.SURFACE_ROLE),)
        start = store._start(cls.project, op_type, name, owner, None, {"name": name, "code": chosen},
                             inputs, keys, supersedes)
        cls.clock.advance(minutes=1)
        with store.design_writer(cls.project, op_type, name, version=None if owner is None else owner.uid,
                                 supersedes=supersedes) as writer:
            drive(writer.grid_steps(BASE, cls.raster()))
            drive(writer.table_steps(REPORT, cls.rows()))

            def parameters(conn: Any) -> None:
                entity_store.set_entity_params(cls.project, cls.parameter_rows(chosen, name),
                                               version=None if owner is None else owner.uid,
                                               decided_by=WHO, conn=conn)

            return writer.commit(start, message="Pila de prueba", before_begin=parameters)

    @classmethod
    def repeat_project(cls, name: str, previous: str, *, code: str = "PIL-001") -> Any:
        """El recálculo de la entidad ``code`` del proyecto: empieza la operación que sustituye a ``previous`` (``begin``)
        y la completa con el escritor reanudado (``resume``), como lo hará ``recompute_run`` (T14)."""
        keys = tuple(params.entity_key(code, key) for key in NAMES)
        start = store._start(cls.project, PILE_PROJECT_OP, name, None, None, {"name": name, "code": code}, (), keys,
                             previous)
        cls.clock.advance(minutes=1)
        handle = start.begin(cls.project)
        with store.ProjectDesignWriter.resume(cls.project, handle) as writer:
            drive(writer.grid_steps(BASE, cls.raster()))
            drive(writer.table_steps(REPORT, cls.rows()))
            return writer.commit(message="Pila de prueba, recalculada")

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.enterClassContext(mock.patch.object(provenance, "OPERATION_TYPES_BY_NAME", MappingProxyType(
            {**provenance.OPERATION_TYPES_BY_NAME, **{item.op_type: item for item in pile_types()}})))
        spec = pile_entity()
        entities.register_entity_type(spec)
        cls.addClassCleanup(entities.unregister_entity_type, PILE)
        core_params.register_families(spec.params.families)
        cls.addClassCleanup(core_params.unregister_families, "des")
        cls.enterClassContext(registered(*(item.definition(never) for item in pile_types())))
        cls.made = {}
        cls.made["v1"] = cls.create("version", "Pila")
        cls.made["v1b"] = cls.create("version", "Pila V3")
        cls.made["project"] = cls.create("project", "Pila")
        cls.made["again"] = cls.repeat_project("Pila", cls.made["project"].handle.uid)
        cls.made["v2"] = cls.create("version", "Pila V2", version=cls.v2, reads="des_stb_pila")

    # --- Lo que hay en el proyecto -------------------------------------------------------------------

    def datasets_of(self, stored: Any) -> list[tuple[Any, ...]]:
        """Los datos de una operación: nombre, tipo, almacén, ubicación, papel, hash y su ámbito (``version_uid``)."""
        with self.project.read() as conn:
            return conn.execute(
                "SELECT d.name, d.kind, d.store, d.locator, io.role, d.content_sha256, d.version_uid "
                "FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
                "WHERE io.operation_uid = ? AND io.direction = 'out' ORDER BY d.name", (stored.handle.uid,)).fetchall()

    def parameter_scopes(self, code: str) -> list[tuple[Any, ...]]:
        """Las filas de ``gb_parameter`` de la entidad ``code``: clave, ámbito, ``scope_uid``, valor y «sin confirmar»."""
        with self.project.read() as conn:
            return conn.execute(
                "SELECT key, scope, scope_uid, value, unconfirmed FROM gb_parameter WHERE key LIKE ? "
                "ORDER BY key, scope, scope_uid", (f"des.pile.{code.lower().replace('-', '_')}.%",)).fetchall()

    def des_state(self) -> dict[str, Any]:
        """Lo que ``des`` ha dejado: operaciones, datos, tablas, ficheros y filas de parámetros de la entidad."""
        names = sorted(path.name for path in (self.root / "rasters").iterdir())
        with self.project.read() as conn:
            return {
                "operations": conn.execute("SELECT op_type, status FROM gb_operation WHERE op_type LIKE 'des.pile%' "
                                           "ORDER BY fid").fetchall(),
                "datasets": conn.execute("SELECT name, version_uid FROM gb_dataset WHERE name LIKE 'des\\_%' "
                                         "ESCAPE '\\' ORDER BY name, version_uid").fetchall(),
                "tables": conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'des\\_%' ESCAPE '\\' "
                                       "ORDER BY name").fetchall(),
                "parameters": conn.execute("SELECT key, scope, scope_uid, value FROM gb_parameter "
                                           "WHERE key LIKE 'des.pile.%' ORDER BY key, scope, scope_uid").fetchall(),
                "files": names}

    # --- Los mismos datos en los dos ámbitos ----------------------------------------------------------

    def test_the_same_data_is_written_in_both_scopes_and_only_the_place_changes(self) -> None:
        """RF-016-02, RF-016-09, D-15 (P-2): la misma entidad de prueba (la rejilla dispersa, la tabla y los parámetros)
        creada en el proyecto y en V01 deja **los mismos datos** —el mismo nombre, tipo, papel, hash y bytes— y lo único
        que cambia es dónde se escriben: la ruta del proyecto no lleva código de versión (``rasters/des_stb_pila.tif``,
        la tabla ``des_prp_pila``) y la de V01 sí (``…_v01``); los datos del proyecto no son de ninguna versión
        (``version_uid`` vacío) y los de V01, de V01."""
        project_data = self.datasets_of(self.made["project"])
        version_data = self.datasets_of(self.made["v1"])
        self.assertEqual([row[0] for row in project_data], ["des_prp_pila", "des_stb_pila"])
        self.assertEqual([row[0] for row in version_data], [row[0] for row in project_data])
        for here, there in zip(project_data, version_data, strict=True):
            with self.subTest(dataset=here[0]):
                self.assertEqual(here[:3] + here[4:6], there[:3] + there[4:6])  # nombre, tipo, almacén, papel, hash
                self.assertEqual(there[3], versions_model.version_locator(here[3], self.v1.code))
                self.assertEqual((here[6], there[6]), ("", self.v1.uid))
        self.assertEqual([row[3] for row in project_data], ["des_prp_pila", "rasters/des_stb_pila.tif"])
        self.assertEqual([row[3] for row in version_data], ["des_prp_pila_v01", "rasters/des_stb_pila_v01.tif"])
        self.assertEqual((self.root / "rasters/des_stb_pila.tif").read_bytes(),
                         (self.root / "rasters/des_stb_pila_v01.tif").read_bytes())
        with self.project.read() as conn:
            tables = [conn.execute(f'SELECT quantity, value, unit_code, note FROM "{name}" ORDER BY quantity').fetchall()
                      for name in ("des_prp_pila", "des_prp_pila_v01")]
        self.assertEqual(tables[0], tables[1])
        self.assertEqual(tables[0], sorted(self.rows(), key=lambda row: row[0]))

    def test_the_operation_and_its_parameters_are_of_the_scope_that_wrote_them(self) -> None:
        """RF-016-02, D-15, RF-009-05: la operación de proyecto es de ámbito ``project`` y sin revisión, la de versión
        de ``version`` con la revisión abierta de V01; los parámetros que lee cada una son **todos** de su ámbito
        (ninguno resuelto desde el otro) y las filas de la entidad se escribieron **todas** en él: las tres, «con valor»,
        en el proyecto o en la versión (el ámbito de los parámetros es el de la operación). Con los mismos valores."""
        with self.project.read() as conn:
            found = {}
            for key in ("project", "v1"):
                uid = self.made[key].handle.uid
                scope, revision, status = conn.execute(
                    "SELECT scope, revision_uid, status FROM gb_operation WHERE uid = ?", (uid,)).fetchone()
                resolved = conn.execute(
                    "SELECT key, scope, value FROM gb_operation_param WHERE operation_uid = ? ORDER BY key",
                    (uid,)).fetchall()
                found[key] = (scope, bool(revision), status, resolved)
        self.assertEqual(found["project"][:3], ("project", False, "done"))
        self.assertEqual(found["v1"][:3], ("version", True, "done"))
        self.assertEqual({row[1] for row in found["project"][3]}, {"project"})
        self.assertEqual({row[1] for row in found["v1"][3]}, {"version"})
        self.assertEqual([(row[0], row[2]) for row in found["project"][3]], [(row[0], row[2]) for row in found["v1"][3]])
        self.assertEqual([row[0] for row in found["project"][3]],
                         [params.entity_key("PIL-001", key) for key in sorted(NAMES)])
        rows = self.parameter_scopes("PIL-001")
        by_scope = {scope: [row for row in rows if (row[1], row[2]) == scope]
                    for scope in (("project", ""), ("version", self.v1.uid), ("version", self.v2.uid))}
        self.assertEqual([row[0] for row in by_scope[("project", "")]],
                         [params.entity_key("PIL-001", key) for key in sorted(NAMES)])
        self.assertEqual([row[3] for row in by_scope[("project", "")]], [row[3] for row in by_scope[("version", self.v1.uid)]])
        self.assertEqual({row[4] for row in by_scope[("project", "")]}, {0})  # ninguna «sin confirmar»: son de una persona
        self.assertEqual(len(by_scope[("version", self.v2.uid)]), len(NAMES))

    def test_parameters_are_read_in_the_scope_of_the_entity(self) -> None:
        """RF-016-02, D-15: ``entity_parameters`` da los valores vigentes de una entidad **en su ámbito**: en el
        proyecto, los del proyecto; en una versión, los de la versión (los del proyecto si la versión no tiene fila: el
        orden versión → proyecto de ``begin_operation``). Las claves son las de la familia de su tipo."""
        want = {"name": "Pila", "discarded": False, "size_m": 2.5}
        self.assertEqual(entity_store.entity_parameters(self.project, "PIL-001"), want)
        self.assertEqual(entity_store.entity_parameters(self.project, "PIL-001", version=self.v1), want)
        self.assertEqual(entity_store.entity_parameters(self.project, "PIL-001", version=self.v2),
                         {**want, "name": "Pila V2"})
        self.assertEqual(entity_store.entity_parameters(self.project, "PIL-002", version=self.v1),
                         {**want, "name": "Pila V3"})

    # --- El registro y los códigos por ámbito --------------------------------------------------------

    def test_the_codes_are_correlative_per_scope(self) -> None:
        """RF-016-02, D-15 (H-3): el código ``PIL-nnn`` es correlativo **por ámbito**: el proyecto tiene su ``PIL-001``
        (``project_registry``), V01 tiene ``PIL-001`` y ``PIL-002`` y V02, su ``PIL-001``; la siguiente de cada ámbito
        cuenta solo las suyas (``PIL-002`` en el proyecto, ``PIL-003`` en V01 y ``PIL-002`` en V02). Cada entidad dice de
        qué ámbito es (``EntityRecord.scope``, ``EntityRegistry.scope``) y su tipo es el de su código."""
        project, v1, v2 = (entities.project_registry(self.project), entities.registry(self.project, self.v1.uid),
                           entities.registry(self.project, self.v2.uid))
        self.assertEqual([entry.record.code for entry in project], ["PIL-001"])
        self.assertEqual([entry.record.code for entry in v1], ["PIL-001", "PIL-002"])
        self.assertEqual([entry.record.code for entry in v2], ["PIL-001"])
        self.assertEqual([entry.record.name for entry in project], ["Pila"])
        self.assertEqual([entry.record.name for entry in v1], ["Pila", "Pila V3"])
        self.assertEqual([entry.record.name for entry in v2], ["Pila V2"])
        for listed, scope in ((project, "project"), (v1, "version"), (v2, "version")):
            self.assertEqual(listed.scope, scope)
            for entry in listed:
                self.assertEqual((entry.record.scope, entry.record.kind), (scope, entities.EntityKind(PILE)))
        self.assertEqual(project.version, "")
        self.assertEqual(v1.version, self.v1.code)
        self.assertEqual([entities.next_code(PILE, (entry.record.code for entry in listed)) for listed in (project, v1, v2)],
                         ["PIL-002", "PIL-003", "PIL-002"])
        self.assertIsNotNone(project.get("PIL-001"))
        self.assertIsNone(project.get("PIL-002"))

    def test_each_registry_has_its_own_operation_and_state(self) -> None:
        """RF-016-02, RF-015-25, D-15: la operación vigente y el estado (deducido del grafo) de cada entidad son los de
        **su** ámbito: la del proyecto, la operación de proyecto (la última, que sustituyó a la primera: un recálculo,
        ``begin`` y ``resume``), la de V01, la de versión; las dos al día."""
        project = entities.project_registry(self.project).get("PIL-001")
        v1 = entities.registry(self.project, self.v1.uid).get("PIL-001")
        self.assertEqual(project.operation_uid, self.made["again"].handle.uid)
        self.assertEqual(v1.operation_uid, self.made["v1"].handle.uid)
        self.assertNotEqual(project.operation_uid, v1.operation_uid)
        self.assertEqual((project.record.state, v1.record.state),
                         (entities.EntityState.CURRENT, entities.EntityState.CURRENT))

    def test_the_rows_without_confirming_that_a_version_leaves_in_the_project_are_no_entity(self) -> None:
        """RF-016-02, D-15 (la trampa de ``begin_operation``, ``docs/trampas.md`` §6): abrir la operación de versión de
        ``PIL-002`` («Pila V3») dejó en el **proyecto** una fila «sin confirmar» por clave que lee, sin que el proyecto
        tenga esa entidad: el registro del proyecto **no** las cuenta (no tienen nombre), no bloquean su siguiente
        código (``PIL-002``) y la entidad de V01 sigue siendo de V01."""
        ghosts = [row for row in self.parameter_scopes("PIL-002") if row[1] == "project"]
        self.assertEqual(len(ghosts), len(NAMES))
        self.assertEqual({row[4] for row in ghosts}, {1})
        self.assertNotIn("PIL-002", [entry.record.code for entry in entities.project_registry(self.project)])
        self.assertEqual(entities.next_code(
            PILE, (entry.record.code for entry in entities.project_registry(self.project))), "PIL-002")

    def test_creating_the_project_entity_after_the_version_one_turns_its_rows_into_the_entity(self) -> None:
        """RF-016-02, D-15: ``PIL-001`` de V01 se creó **antes** que la del proyecto, que ya tenía sus filas «sin
        confirmar» (``begin_operation``): escribir las de la entidad del proyecto no falla con ``core.param_exists`` —las
        convierte en las de una persona (con su origen, su decisor y su historial: la fila por defecto y el cambio)— y no
        se pisa ninguna entidad real: crear otra vez la misma sí lo rechaza."""
        store_ = core_params.ParameterStore(self.project)
        key = params.entity_key("PIL-001", "name")
        record = store_.get(key)
        self.assertEqual((record.value, record.unconfirmed, record.decided_by), ("Pila", False, WHO))
        self.assertEqual([entry.action for entry in store_.history(key)], ["default", "change"])
        before = self.des_state()
        with self.assertRaises(core_params.ParamError) as caught:
            with self.project.write_transaction() as conn:
                entity_store.set_entity_params(self.project, self.parameter_rows("PIL-001", "Otra"),
                                               version=None, decided_by=WHO, conn=conn)
        self.assertEqual(caught.exception.code, "core.param_exists")
        self.assertEqual(self.des_state(), before)

    # --- RF-009-05: lo que una operación de cada ámbito puede consumir -------------------------------

    def test_a_project_operation_cannot_consume_a_version_data(self) -> None:
        """RF-009-05, D-15: una operación **de proyecto** que consume un dato **de versión** (la rejilla de la «Pila V3»
        de V01) se rechaza (``core.version_data_in_project``) y no deja nada: ni operación, ni dato, ni parámetro, ni
        fichero, ni temporal."""
        before = self.des_state()
        with self.assertRaises(versions_model.VersionError) as caught:
            self.create("project", "Otra pila", reads="des_stb_pila_v3")
        self.assertEqual(caught.exception.code, "core.version_data_in_project")
        self.assertEqual(self.des_state(), before)

    def test_a_version_operation_can_consume_a_project_data(self) -> None:
        """RF-009-05, D-15: la inversa sí: una operación de versión consume un dato del proyecto (R-18 y la 011 leen
        la detección del proyecto desde una versión): la ``PIL-001`` de V02 consumió la rejilla del proyecto
        (``des_stb_pila``, de ámbito de proyecto, la de su última operación) y la anotó entre sus entradas."""
        with self.project.read() as conn:
            used = conn.execute(
                "SELECT d.name, d.version_uid, d.operation_uid FROM gb_operation_io AS io JOIN gb_dataset AS d "
                "ON d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'in'",
                (self.made["v2"].handle.uid,)).fetchall()
        self.assertEqual(used, [("des_stb_pila", "", self.made["again"].handle.uid)])

    # --- El escritor ------------------------------------------------------------------------------------

    def test_the_writer_is_of_the_scope_of_the_operation_type(self) -> None:
        """RF-016-02, D-15: ``design_writer`` da el escritor del ámbito del tipo (``ProjectDesignWriter`` para uno de
        proyecto, ``DesignWriter`` para uno de versión); el de proyecto **no usa la versión activa** (como
        ``begin_operation``) y no tiene versión ni código de versión; y cada escritor rechaza el tipo del otro ámbito
        (errores del programa, ``ValueError``)."""
        with store.design_writer(self.project, PILE_PROJECT_OP, "Nueva", version=self.v1.uid) as writer:
            self.assertIsInstance(writer, store.ProjectDesignWriter)
            self.assertIsInstance(writer, store.DesignWriter)
            self.assertEqual((writer.version_uid, writer.version_code), ("", None))
        with store.design_writer(self.project, PILE_OP, "Nueva", version=self.v1.uid) as writer:
            self.assertNotIsInstance(writer, store.ProjectDesignWriter)
            self.assertEqual((writer.version_uid, writer.version_code), (self.v1.uid, "V01"))
        with self.assertRaises(ValueError):
            store.ProjectDesignWriter(self.project, PILE_OP, "Nueva")
        with self.assertRaises(ValueError):
            store.DesignWriter(self.project, PILE_PROJECT_OP, "Nueva", version=self.v1.uid)
        with self.assertRaises(ValueError):
            store.design_writer(self.project, "des.no_such", "Nueva", version=None)

    def test_a_project_writer_does_not_write_the_layers_of_a_version(self) -> None:
        """RF-016-02, D-15: las capas de versión (las declaradas y la de entidades) no son salidas de la detección y el
        escritor de proyecto las rechaza como cualquier salida que su tipo no escribe (``ValueError``)."""
        with store.design_writer(self.project, PILE_PROJECT_OP, "Nueva", version=None) as writer:
            with self.assertRaises(ValueError):
                writer.declared_steps([])
            with self.assertRaises(ValueError):
                writer.entity_layer_steps([])

    def test_a_repeated_name_is_refused_in_the_scope_that_has_it(self) -> None:
        """RF-013-17, D-15: el nombre es único **en su ámbito**: «Pila» existe en el proyecto y en V01 (a la vez, sin
        pisarse), así que repetirlo se rechaza en cada uno —en el proyecto con su propio mensaje, que nombra al
        proyecto— y «Pila V3» (solo de V01) sí es libre en el proyecto."""
        with self.assertRaises(messages.DesignError) as caught:
            store.design_writer(self.project, PILE_PROJECT_OP, "Pila", version=None)
        self.assertEqual(caught.exception.code, "des.operation_name_repeated_project")
        self.assertIn("proyecto", caught.exception.text)
        with self.assertRaises(messages.DesignError) as caught:
            store.design_writer(self.project, PILE_OP, "Pila", version=self.v1.uid)
        self.assertEqual(caught.exception.code, "des.operation_name_repeated")
        with store.design_writer(self.project, PILE_PROJECT_OP, "Pila V3", version=None):
            pass

    def test_a_project_operation_is_repeated_with_its_own_writer(self) -> None:
        """RF-016-02, RF-008-26, D-15: el recálculo de una detección del proyecto —empezar la operación que sustituye a
        la anterior y completarla con el escritor reanudado (``resume``)— deja una sola operación vigente en el
        proyecto, con los mismos datos y el mismo nombre; la sustituida queda como historia."""
        first, again = self.made["project"].handle.uid, self.made["again"].handle.uid
        with self.project.read() as conn:
            rows = conn.execute("SELECT uid, scope, status, supersedes_uid, superseded_by FROM gb_operation "
                                "WHERE uid IN (?, ?) ORDER BY fid", (first, again)).fetchall()
        self.assertEqual(rows, [(first, "project", "done", None, again), (again, "project", "done", first, None)])
        self.assertEqual([row[0] for row in self.datasets_of(self.made["again"])], ["des_prp_pila", "des_stb_pila"])
        self.assertEqual([row[3] for row in self.datasets_of(self.made["again"])],
                         ["des_prp_pila", "rasters/des_stb_pila.tif"])  # los mismos datos, en el mismo sitio del proyecto


class DatasetsOfProject(unittest.TestCase):
    """El nombre y la ubicación de los datos de la detección valen en los dos ámbitos (RF-016-09, D-15)."""

    def test_the_locator_of_a_project_data_has_no_version_code(self) -> None:
        """RF-016-09, D-15: ``dataset_spec`` con ``None`` da el dato del proyecto (sin código de versión) y con el de
        una versión, el de siempre; **el mismo nombre, tipo, almacén y papel**."""
        for family in (provenance.STOCKPILE_BASE_GRID, provenance.STOCKPILES_TABLE):
            with self.subTest(family=family):
                here = provenance.dataset_spec(family, "Pila", None)
                there = provenance.dataset_spec(family, "Pila", "V01")
                self.assertEqual((here.name, here.kind, here.store, here.role), (there.name, there.kind, there.store, there.role))
                self.assertEqual(there.locator, versions_model.version_locator(here.locator, "V01"))
        self.assertEqual(datasets.Store.RASTERS, provenance.dataset_spec(provenance.STOCKPILE_BASE_GRID, "Pila", None).store)


if __name__ == "__main__":
    unittest.main()

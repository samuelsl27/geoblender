# SPDX-License-Identifier: GPL-3.0-or-later
"""El registro de las entidades de la 015 generalizado a más de un tipo (spec 016, T02; HU-016-1; RF-016-01,
RF-016-02; plan 016 §2.1, §5.1, §5.2.3 «Una entidad sin cadena», §5.7 P-1, P-3 y P-11, §5.8 H-2 y H-9, §8;
ADR-0031 §1 y «Negativas»; RF-015-01 a 04, 15 a 18, 25 y 27 sin cambios).

La T02 es un **refactor sin cambio de comportamiento**: lo que la 015 sabía de «la plataforma» (su prefijo de
código ``PLT``, su familia de parámetros ``des.platform.{e}.*``, el tipo de su operación, los papeles de su
superficie y su tabla, los mensajes que dice de ella) pasa a ser lo que el registro sabe **de cada tipo de
entidad**, y la 015 sigue siendo el único tipo registrado. Estas pruebas lo comprueban con **dos tipos de
prueba sin comportamiento**, registrados solo desde aquí (:func:`types_registered`) y quitados al salir:

- ``probe`` (``PRB``): como la plataforma, con partida, que **encadena** (lo que serán la retirada, el contrafuerte
  y el cuerpo «sobre una base»);
- ``island`` (``ISL``): **sin cadena**, sin ``start`` (lo que serán la detección de acopios y el cuerpo «bajo un
  techo»): ``chain_tails`` la deja fuera, no encadena y **nadie puede partir de su superficie**
  (``des.chainless_start``, el rechazo nuevo); deja su superficie y su tabla con sus propios papeles.

Sin proyecto: el registro por tipo, el código ``<PREFIJO>-nnn`` correlativo por ámbito e inmutable, los
parámetros de la familia de cada tipo (:func:`~geoblender.design.params.entity_key`), la cadena y el rechazo. Con
proyecto (la cantera de la 014, sobre operaciones sintéticas como las de ``test_entities_chain``): el registro de
una versión con los tres tipos, ``entity_surfaces`` por tipo, lo que congelar pide verificar y los rechazos al
crear y al cambiar la partida. Que reproducir una revisión congelada de la 015 da el mismo hash con los tipos de
prueba registrados es de ``milestone_entities_registry.py`` (el paso «hito»: pesa más de 1 s, P-13).
"""

from __future__ import annotations

import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, ClassVar

from tests.support import entity_fixtures as efx
from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.unit.design.test_entities_chain import synthetic_definition

entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")
params = import_geoblender("design.params")
provenance = import_geoblender("design.provenance")
core_params = import_geoblender("core.params")
contract = import_geoblender("core.provenance.contract")
operations = import_geoblender("core.provenance.operations")
datasets = import_geoblender("core.datasets.model")
builtin = import_geoblender("core.content.builtin")
gpkg_base = import_geoblender("core.gpkg.base")
versions_model = import_geoblender("core.versions.model")

PLATFORM = entities.EntityKind.PLATFORM
PROGRAM_KINDS = ["platform", "stockpile", "removal", "buttress", "body", "road", "access"]
"""Los tipos del programa, en su orden: la plataforma (015), los cuatro de la 016 (T03) y los dos de la 017 (T03)."""
State = entities.EntityState
PROBE, ISLAND = "probe", "island"
GROUND = "gis_dtm_ladera"
"""La superficie de partida de las cadenas de las pruebas: el terreno de la cantera."""
ISLAND_SURFACE_ROLE, ISLAND_TABLE_ROLE = "island_surface", "island_table"
"""Los papeles propios del tipo sin cadena: su superficie y su tabla no son las de una entidad que encadena."""
VALUE_TYPES = {"name": "text", "start": "text", "support": "text", "supports": "text", "reason": "text",
               "discarded": "bool", "protect": "bool", "guard_m": "float", "size_m": "float",
               "area_m2": "float"}
"""El tipo de valor de cada parámetro de los tipos de prueba; los únicos con valor por defecto, los dos sí/no."""
DEFAULTS = {"discarded": False, "protect": False}
COMMON = ("name", "start", "support", "supports", "discarded", "protect", "guard_m", "reason")
"""Los valores comunes a todos los tipos (plan 016 §5.2.2): los de la 015 bajo el prefijo de cada tipo (P-11)."""


def families_of(prefix: str, names: tuple[str, ...]) -> tuple[Any, ...]:
    """Las familias de parámetros ``<prefix>.{e}.<valor>`` de un tipo de prueba, de versión."""
    return tuple(params.entity_family(prefix, name, VALUE_TYPES[name], DEFAULTS.get(name), (), ("RF-016-02",),
                                      "Prueba de la T02 de la 016 (sin valor real)", f"{name} of the probe")
                 for name in names)


def probe_spec() -> Any:
    """``probe``: con partida (encadena) y con los papeles de la superficie y la tabla de toda entidad."""
    names = (*COMMON, "size_m")
    return entities.EntityType(
        params.EntityParams(PROBE, "PRB", names, families_of("des.probe", names)), "des.probe",
        "des.platform_declared_reason", "des.support_removed_platform", provenance.ENTITY_SURFACE_ROLE,
        provenance.ENTITY_ROLE)


def island_spec() -> Any:
    """``island``: sin ``start`` (sin cadena) y con papeles propios para su superficie y su tabla."""
    names = (*(name for name in COMMON if name != "start"), "area_m2")
    return entities.EntityType(
        params.EntityParams(ISLAND, "ISL", names, families_of("des.island", names)), "des.island",
        "des.platform_declared_reason", "des.support_removed_platform", ISLAND_SURFACE_ROLE, ISLAND_TABLE_ROLE)


@contextmanager
def types_registered(*, families: bool = False) -> Iterator[tuple[Any, Any]]:
    """Registra los dos tipos de prueba (``probe`` e ``island``) y los quita al salir, en orden inverso;
    ``families``: también sus familias de parámetros en ``core.params`` (y las de la plataforma, que ``bl``
    registra al activarse; se quitan todas las de ``des`` al salir)."""
    specs = (probe_spec(), island_spec())
    done: list[Any] = []
    try:
        for spec in specs:
            entities.register_entity_type(spec)
            done.append(spec)
        if families:
            core_params.register_families(
                (*params.ENTITY_FAMILIES, *(item for spec in specs for item in spec.params.families)))
        yield specs
    finally:
        if families:
            core_params.unregister_families("des")
        for spec in reversed(done):
            entities.unregister_entity_type(spec.kind)


def rec(code: str, name: str, kind: Any, start: str | None = None, *, state: Any = State.UNCALCULATED,
        support: str | None = None) -> Any:
    """Una entidad de ``kind`` (el tipo o su valor) con ``code`` y ``name`` que parte de ``start``."""
    return entities.EntityRecord(code, name, kind, start, support, state)


def codes(found: Any) -> list[str]:
    """Los códigos de las entidades de ``found``, en su orden."""
    return [item.code for item in found]


class TypeRegistryTest(unittest.TestCase):
    """RF-016-02, RF-015-01: el registro de los tipos de entidad: la plataforma y los cuatro de la 016 (T03) son
    los de verdad y un tipo de prueba existe solo mientras una prueba lo registra."""

    def test_the_types_of_the_program_are_registered_by_default(self) -> None:
        """RF-016-02, RF-015-01, RF-015-02, RF-015-25: lo que la 015 sabía de la plataforma es lo que el registro
        sabe de su tipo, sin cambiar un valor: su prefijo, su familia de parámetros, su operación, los papeles de
        su superficie y su tabla y los mensajes de su motivo y de «apoyo retirado»; y, detrás, los cuatro de la 016
        (T03), sin más tipo."""
        self.assertEqual([item.kind for item in entities.registered_types()], PROGRAM_KINDS)
        spec = entities.entity_type("platform")
        self.assertEqual((spec.kind, spec.prefix, spec.key_prefix, spec.op_type, spec.chained),
                         ("platform", "PLT", "des.platform", provenance.PLATFORM, True))
        self.assertEqual((spec.surface_role, spec.table_role),
                         (provenance.ENTITY_SURFACE_ROLE, provenance.ENTITY_ROLE))
        self.assertEqual((spec.reason, spec.removed),
                         ("des.platform_declared_reason", "des.support_removed_platform"))
        self.assertIs(entities.entity_type(PLATFORM), spec)
        self.assertIs(spec.params, params.entity_params("platform"))
        self.assertEqual(spec.params.names, tuple(item.value for item in params.PlatformParam))
        self.assertEqual([item.value for item in entities.EntityKind], PROGRAM_KINDS)
        self.assertEqual((PLATFORM.prefix, PLATFORM.chained), ("PLT", True))
        self.assertEqual(entities.declared_reason(PLATFORM, "P1"), "declarada por la plataforma P1")

    def test_a_type_exists_only_while_a_test_registers_it(self) -> None:
        """RF-016-02: un tipo registrado se lee como un ``EntityKind`` (igual a su valor, siempre el mismo objeto)
        y deja de existir al quitarlo; la enumeración de los tipos de verdad no cambia y lo registrado, tampoco
        (ni el de las entidades ni el de sus parámetros)."""
        before = (entities.registered_types(), params.registered_entity_params())
        for missing in (PROBE, ISLAND):
            with self.assertRaises(ValueError):
                entities.EntityKind(missing)
        with types_registered() as (probe, island):
            kind = entities.EntityKind(PROBE)
            self.assertEqual((kind.value, kind.prefix, kind.chained), ("probe", "PRB", True))
            self.assertEqual(kind, "probe")
            self.assertIs(entities.EntityKind("probe"), kind)
            self.assertIs(entities.EntityKind(kind), kind)
            self.assertFalse(entities.EntityKind(ISLAND).chained)
            self.assertEqual([item.kind for item in entities.registered_types()],
                             [*PROGRAM_KINDS, "probe", "island"])
            self.assertEqual([item.value for item in entities.EntityKind], PROGRAM_KINDS)
            self.assertIs(entities.entity_type(kind), probe)
            self.assertIs(entities.entity_type("island"), island)
        self.assertEqual((entities.registered_types(), params.registered_entity_params()), before)
        for missing in (PROBE, ISLAND):
            with self.subTest(kind=missing):
                with self.assertRaises(ValueError):
                    entities.EntityKind(missing)
                with self.assertRaises(ValueError):
                    entities.entity_type(missing)
                with self.assertRaises(ValueError):
                    params.entity_params(missing)

    def test_registering_twice_or_with_a_prefix_already_taken_is_a_program_error(self) -> None:
        """RF-016-02: un tipo o un prefijo de código se registran una vez (el prefijo es el tipo de un código);
        un rechazo no deja nada a medias."""
        with types_registered() as (probe, _island):
            before = (entities.registered_types(), params.registered_entity_params())
            with self.assertRaises(ValueError):
                entities.register_entity_type(probe)
            clash = entities.EntityType(
                params.EntityParams("other", "PRB", COMMON, families_of("des.other", COMMON)), "des.other",
                "des.platform_declared_reason", "des.support_removed_platform")
            with self.assertRaises(ValueError):
                entities.register_entity_type(clash)
            with self.assertRaises(ValueError):
                params.register_entity_params(clash.params)
            with self.assertRaises(TypeError):
                entities.register_entity_type("probe")  # type: ignore[arg-type]
            self.assertEqual((entities.registered_types(), params.registered_entity_params()), before)

    def test_the_platform_cannot_be_unregistered_nor_what_is_not_registered(self) -> None:
        """RF-016-02, RF-015-01: la plataforma y los cuatro tipos de la 016 son del programa, no de una prueba:
        quitarlos (o un tipo que no está) es un error del programa y lo registrado sigue igual."""
        before = (entities.registered_types(), params.registered_entity_params())
        for kind in (*PROGRAM_KINDS, PROBE):
            with self.subTest(kind=kind):
                with self.assertRaises(ValueError):
                    entities.unregister_entity_type(kind)
                with self.assertRaises(ValueError):
                    params.unregister_entity_params(kind)
        self.assertEqual((entities.registered_types(), params.registered_entity_params()), before)

    def test_the_type_of_a_code_is_its_prefix(self) -> None:
        """RF-016-02: de un código ``<PREFIJO>-nnn`` se saca su tipo; un prefijo que ningún tipo registrado
        tiene, o algo que no es un código, es un error del programa."""
        with types_registered():
            self.assertIs(entities.kind_of_code("PLT-001"), PLATFORM)
            self.assertIs(entities.kind_of_code("PRB-1234"), entities.EntityKind(PROBE))
            self.assertIs(entities.kind_of_code("ISL-020"), entities.EntityKind(ISLAND))
            for wrong in ("XYZ-001", "plt-001", "PRB-1", "", "PRB_001", "PRB-001 "):
                with self.subTest(code=wrong), self.assertRaises(ValueError):
                    entities.kind_of_code(wrong)
            with self.assertRaises(TypeError):
                entities.kind_of_code(5)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            entities.kind_of_code("PRB-001")

    def test_a_record_takes_its_kind_from_its_code_and_a_type_without_chain_has_no_start(self) -> None:
        """RF-016-02, RF-015-01, RF-015-04: el código de una entidad es de su tipo; el tipo se da por su valor o
        como ``EntityKind``; una entidad de un tipo sin cadena no tiene partida (lo que la hace «sin cadena»)."""
        with types_registered():
            probe = entities.EntityKind(PROBE)
            record = rec("PRB-001", "S1", PROBE, GROUND)
            self.assertIs(record.kind, probe)
            self.assertEqual((record.segment, record.start), ("prb_001", GROUND))
            self.assertEqual(record, rec("PRB-001", "S1", probe, GROUND))
            with self.assertRaises(ValueError):
                rec("PLT-001", "S1", PROBE)
            with self.assertRaises(ValueError):
                rec("PRB-001", "S1", PLATFORM)
            bare = rec("ISL-001", "Acopios", ISLAND)
            self.assertEqual((bare.start, bare.support, bare.segment), (None, None, "isl_001"))
            with self.assertRaises(ValueError):
                rec("ISL-001", "Acopios", ISLAND, GROUND)
        with self.assertRaises(ValueError):
            rec("PRB-001", "S1", PROBE)


class CodeTest(unittest.TestCase):
    """RF-016-02, RF-015-01: el código ``<PREFIJO>-nnn`` de cada tipo, correlativo por ámbito e inmutable."""

    def setUp(self) -> None:
        self.probe, self.island = (entities.EntityKind(item.kind) for item in self.enterContext(types_registered()))

    def test_each_type_counts_its_own_codes(self) -> None:
        """RF-016-02, RF-015-01 (ADR-0030: un código inmutable por entidad): cada tipo, su prefijo y su cuenta: el
        siguiente es el mayor número del tipo más uno; los de otro tipo no cuentan, y la plataforma cuenta como
        siempre."""
        self.assertEqual(entities.next_code(self.probe, ()), "PRB-001")
        self.assertEqual(entities.next_code(self.probe, ["PLT-005", "ISL-007", "PRB-002"]), "PRB-003")
        self.assertEqual(entities.next_code(self.island, ["ISL-001", "ISL-002", "PRB-009"]), "ISL-003")
        self.assertEqual(entities.next_code(PLATFORM, ["PRB-009", "ISL-003"]), "PLT-001")
        self.assertEqual(entities.next_code(PLATFORM, ["PRB-009", "PLT-003"]), "PLT-004")
        self.assertEqual(entities.next_code("probe", iter(["PRB-009"])), "PRB-010")
        self.assertEqual(entities.format_code(self.probe, 7), "PRB-007")
        self.assertEqual(entities.format_code(self.island, 1234), "ISL-1234")
        self.assertEqual(entities.next_code(self.probe, ["PRB-999"]), "PRB-1000")

    def test_the_code_is_correlative_and_never_reused_in_its_scope(self) -> None:
        """RF-016-02, D-15 (el código es correlativo **por ámbito**: ``STK-001`` en el proyecto y en cada
        versión): ``next_code`` cuenta los códigos que se le dan, los del ámbito (todos, también los de lo
        descartado, que sigue ahí); lo que falte por el camino se queda como hueco, y otro ámbito empieza de
        nuevo."""
        project_scope = ["ISL-001", "ISL-002"]
        version_scope = ["ISL-001"]
        self.assertEqual(entities.next_code(self.island, project_scope), "ISL-003")
        self.assertEqual(entities.next_code(self.island, version_scope), "ISL-002")
        self.assertEqual(entities.next_code(self.island, []), "ISL-001")
        self.assertEqual(entities.next_code(self.island, ["ISL-001", "ISL-003"]), "ISL-004")
        self.assertEqual(entities.next_code(self.island, ["ISL-003", "ISL-001", "ISL-001"]), "ISL-004")

    def test_a_code_that_is_not_one_is_a_fault_of_the_program(self) -> None:
        """RF-016-02, RF-015-01: ni ``next_code`` ni ``format_code`` inventan un código: uno mal escrito, un
        número que no es de una entidad o un tipo sin registrar es un error del programa."""
        for wrong in ("PRB-1", "prb-001", "PRB-00a", "PRB001", "", "PRB-001 "):
            with self.subTest(code=wrong), self.assertRaises(ValueError):
                entities.next_code(self.probe, [wrong])
        with self.assertRaises(TypeError):
            entities.next_code(self.probe, [1])  # type: ignore[list-item]
        for number in (0, -1):
            with self.subTest(number=number), self.assertRaises(ValueError):
                entities.format_code(self.probe, number)
        for number in (1.5, True, "1"):
            with self.subTest(number=number), self.assertRaises(TypeError):
                entities.format_code(self.probe, number)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            entities.next_code("sandbar", ())
        with self.assertRaises(ValueError):
            entities.format_code("sandbar", 1)


class ParamFamilyTest(unittest.TestCase):
    """RF-016-02, RF-015-01, P-11: los parámetros de cada tipo son su familia ``des.<tipo>.{e}.*``."""

    def test_the_platform_family_is_the_one_of_the_015(self) -> None:
        """RF-015-01, RF-016-02: los valores de la plataforma, su prefijo y sus 20 familias son los de la 015; el
        constructor de las familias de cualquier tipo da **exactamente** las de la plataforma con los datos de su
        plantilla; los comunes a todos los tipos (plan 016 §5.2.2) están entre ellos."""
        platform = params.entity_params("platform")
        self.assertEqual((platform.kind, platform.code_prefix, platform.key_prefix, platform.chained),
                         ("platform", "PLT", "des.platform", True))
        self.assertEqual(platform.families, params.ENTITY_FAMILIES)
        self.assertEqual(len(platform.names), 21)  # las 20 de la 015 y la 21.ª de la 016 (T21: «stockpile»)
        self.assertEqual(params.COMMON_ENTITY_PARAMS, COMMON)
        self.assertLessEqual(set(COMMON), set(platform.names))
        for name, template in params.PLATFORM_PARAMS.items():
            rebuilt = params.entity_family(
                params.PLATFORM_PREFIX, name, str(template.value_type), template.default, template.choices,
                template.requirements, template.source, str(template.label_msgid),
                span=params.ENTITY_RANGES.get(name))
            self.assertEqual(rebuilt, params.ENTITY_FAMILIES[platform.names.index(name)], name)

    def test_the_key_of_a_value_is_in_the_family_of_the_type_of_its_code(self) -> None:
        """RF-016-02, RF-015-01: la clave de un valor es ``des.<tipo>.<código>.<valor>`` con el tipo y el
        segmento que dice su código; los comunes valen para todos los tipos que los tienen."""
        with types_registered():
            cases = (("PLT-001", "width_m", "des.platform.plt_001.width_m"),
                     ("PLT-002", params.PlatformParam.GUARD, "des.platform.plt_002.guard_m"),
                     ("PRB-001", "size_m", "des.probe.prb_001.size_m"),
                     ("PRB-1234", "name", "des.probe.prb_1234.name"),
                     ("ISL-003", "area_m2", "des.island.isl_003.area_m2"))
            for code, param, expected in cases:
                with self.subTest(code=code, param=str(param)):
                    self.assertEqual(params.entity_key(code, param), expected)
            for name in COMMON:
                self.assertEqual(params.entity_key("PLT-001", name), f"des.platform.plt_001.{name}")
                self.assertEqual(params.entity_key("PRB-001", name), f"des.probe.prb_001.{name}")
                if name != "start":
                    self.assertEqual(params.entity_key("ISL-001", name), f"des.island.isl_001.{name}")

    def test_each_type_takes_only_its_own_values(self) -> None:
        """RF-016-02: un valor que no es de la familia del tipo de su código (los de la plataforma no son de
        otro tipo, ni al revés; ``island`` no tiene ``start``), un prefijo sin tipo o un tipo sin registrar son
        errores del programa."""
        with types_registered():
            for code, wrong in (("PRB-001", "width_m"), ("PLT-001", "size_m"), ("ISL-001", "start"),
                                ("PRB-001", "no_such_param"), ("ISL-001", "size_m"), ("PLT-001", "area_m2")):
                with self.subTest(code=code, param=wrong), self.assertRaises(ValueError):
                    params.entity_key(code, wrong)
            for code in ("XYZ-001", "plt-001", "PRB-1", "", "PLT_001"):
                with self.subTest(code=code), self.assertRaises(ValueError):
                    params.entity_key(code, "name")
        with self.assertRaises(ValueError):
            params.entity_key("PRB-001", "name")

    def test_a_key_is_read_back_into_its_code_its_type_and_its_value(self) -> None:
        """RF-016-02: la clave de un valor de una entidad vuelve a su código, su tipo y su valor; lo que no es de
        la forma ``des.<tipo>.<segmento>.<valor>`` de un tipo registrado, a ``None``."""
        with types_registered():
            parse = params.parse_entity_key
            self.assertEqual(parse("des.platform.plt_001.width_m"), ("PLT-001", "platform", "width_m"))
            self.assertEqual(parse("des.probe.prb_002.size_m"), ("PRB-002", "probe", "size_m"))
            self.assertEqual(parse("des.island.isl_010.name"), ("ISL-010", "island", "name"))
            for wrong in ("des.platform.plt_001", "des.platform.plt_001.size_m", "des.probe.plt_001.size_m",
                          "des.island.isl_001.start", "des.bench.p1.height_m", "des.platform.plt_001.width_m.x",
                          "des.platform.xyz_001.width_m", "", "res.unit.u1.density"):
                with self.subTest(key=wrong):
                    self.assertIsNone(parse(wrong))
            self.assertIsNone(parse(5))  # type: ignore[arg-type]
        self.assertIsNone(params.parse_entity_key("des.probe.prb_002.size_m"))

    def test_the_families_of_one_type_are_not_the_ones_of_another(self) -> None:
        """RF-016-02, P-11: ninguna familia de un tipo repite el patrón de otra; la definición de una clave es la
        de su tipo (``des.probe.{e}.name`` no es ``des.platform.{e}.name``), de versión y con el valor por
        defecto de su tipo, y un valor que un tipo no tiene no se declara."""
        with types_registered() as (probe, island):
            every = (*params.ENTITY_FAMILIES, *probe.params.families, *island.params.families)
            patterns = [family.pattern for family in every]
            self.assertEqual(len(patterns), len(set(patterns)))
            self.assertEqual([len(item.params.families) for item in (probe, island)], [9, 8])
            for code, name in (("PLT-001", "name"), ("PRB-001", "name"), ("ISL-001", "name"),
                               ("PRB-002", "size_m"), ("ISL-002", "area_m2"), ("PLT-003", "discarded")):
                key = params.entity_key(code, name)
                found = core_params.find_definition(key, {}, every)
                self.assertIsNotNone(found, key)
                self.assertEqual((found.key, found.scope), (key, "version"))
            self.assertIs(core_params.find_definition(params.entity_key("PRB-001", "discarded"), {}, every).default,
                          False)
            self.assertIsNone(core_params.find_definition("des.probe.prb_001.width_m", {}, every))
            self.assertIsNone(core_params.find_definition("des.island.isl_001.start", {}, every))


class ChainlessTest(unittest.TestCase):
    """RF-016-02, plan 016 §2.1 y H-9: un tipo sin cadena (sin ``start``) no encadena y nadie parte de su
    superficie; la regla implícita de ``chain_tails`` se fija aquí."""

    def setUp(self) -> None:
        self.enterContext(types_registered())

    def test_a_type_without_start_is_in_no_chain_and_not_a_tail(self) -> None:
        """RF-016-02, RF-015-04, H-9: la entidad de un tipo sin cadena **no** es la cola de ninguna (no hay
        superficie de diseño que congelar), en cualquier estado, sola o con otras; y no tiene sucesora ni
        predecesora."""
        platform = rec("PLT-001", "P1", PLATFORM, GROUND)
        for state in State:
            with self.subTest(state=str(state)):
                island = rec("ISL-001", "Acopios", ISLAND, state=state)
                self.assertEqual(entities.chain_tails([island]), ())
                self.assertEqual(codes(entities.chain_tails([platform, island])), ["PLT-001"])
                self.assertEqual(codes(entities.chain_tails([island, platform])), ["PLT-001"])
                self.assertEqual(codes(entities.chain_of([platform, island], "Acopios")), ["ISL-001"])
                self.assertIsNone(entities.successor_of([platform, island], "ISL-001"))
                self.assertIsNone(entities.predecessor_of([platform, island], "ISL-001"))
                self.assertIsNone(entities.check_chain([platform, island]))
                self.assertIsNone(entities.start_conflict([platform, island], None))

    def test_a_type_with_start_chains_like_the_platform_across_types(self) -> None:
        """RF-016-02, RF-015-04: ``probe`` tiene partida y encadena con la plataforma, una detrás de la otra, en
        cualquier sentido: la cola de la cadena es la última, sea de su tipo que sea."""
        records = [rec("PLT-001", "P1", PLATFORM, GROUND),
                   rec("PRB-001", "S1", PROBE, entities.surface_ref("PLT-001")),
                   rec("PLT-002", "P2", PLATFORM, entities.surface_ref("PRB-001")),
                   rec("PRB-002", "S2", PROBE, "des_srf_otra")]
        self.assertEqual(codes(entities.chain_tails(records)), ["PLT-002", "PRB-002"])
        self.assertEqual(codes(entities.chain_of(records, "P1")), ["PLT-001", "PRB-001", "PLT-002"])
        self.assertEqual(entities.predecessor_of(records, "P2").code, "PRB-001")
        self.assertEqual(entities.successor_of(records, "S1").code, "PLT-002")

    def test_nobody_starts_from_the_surface_of_a_type_without_chain(self) -> None:
        """RF-016-02, plan 016 §5.8 H-9 (rechazo nuevo): una entidad viva que parte de la superficie de una de un
        tipo sin cadena se rechaza con ``des.chainless_start`` —con su campo, el valor y las dos entidades—, sea
        cual sea el estado de la sin cadena y sea de su tipo que sea quien parte; una descartada es un registro y
        no se rechaza."""
        start = entities.surface_ref("ISL-001")
        for state in State:
            island = rec("ISL-001", "Acopios", ISLAND, state=state)
            for kind, code, field in ((PLATFORM, "PLT-001", "des.platform.plt_001.start"),
                                      (PROBE, "PRB-001", "des.probe.prb_001.start")):
                records = [island, rec(code, "P1", kind, start)]
                for check in (entities.chain_tails, entities.check_chain,
                              lambda items: entities.chain_of(items, "P1")):
                    with self.subTest(state=str(state), kind=str(kind)), self.assertRaises(
                            messages.DesignError) as caught:
                        check(records)
                    error = caught.exception
                    self.assertEqual((error.code, error.field, error.value), ("des.chainless_start", field, start))
                    self.assertEqual((error.values["entity"], error.values["other"]), ("P1", "Acopios"))
                    self.assertIn("«P1»", error.text)
                    self.assertIn("«Acopios»", error.text)
        island = rec("ISL-001", "Acopios", ISLAND, state=State.CURRENT)
        record = rec("PLT-001", "P1", PLATFORM, start, state=State.DISCARDED)
        self.assertIsNone(entities.check_chain([island, record]))
        self.assertEqual(entities.chain_tails([island, record]), ())

    def test_the_rejection_is_in_both_languages_with_the_same_markers(self) -> None:
        """RF-016-02, principio 10: ``des.chainless_start`` es un error con su texto en español y en inglés, con
        los mismos marcadores; nombra la entidad, la superficie y la que no deja superficie de la que partir."""
        message = messages.MESSAGES["des.chainless_start"]
        self.assertEqual(message.severity, "error")
        self.assertNotEqual(message.msgid, message.es)
        values = {"entity": "P1", "value": "entity:ISL-001", "other": "Acopios"}
        es = messages.render("des.chainless_start", **values)
        en = messages.render("des.chainless_start", language="en", **values)
        for text in (es, en):
            for shown in values.values():
                self.assertIn(shown, text)
        self.assertNotEqual(es, en)

    def test_nothing_is_inserted_next_to_a_type_without_chain(self) -> None:
        """RF-016-02, RF-015-05: «insertar antes o después de…» no se ofrece junto a una entidad sin cadena (no
        deja superficie de la que partir ni parte de ninguna): un error del programa, como junto a una
        descartada."""
        records = [rec("PLT-001", "P1", PLATFORM, GROUND), rec("ISL-001", "Acopios", ISLAND)]
        new = rec("PRB-001", "S1", PROBE, entities.surface_ref("ISL-001"))
        for before in (False, True):
            with self.subTest(before=before):
                with self.assertRaises(ValueError):
                    entities.insertion_start(records, "Acopios", before=before)
                with self.assertRaises(ValueError):
                    entities.insertion_point(records, "ISL-001", before=before)
        with self.assertRaises(ValueError):
            entities.insert_after(records, "Acopios", new)
        self.assertEqual(entities.insertion_start(records, "P1"), entities.surface_ref("PLT-001"))


# --- El registro de una versión con proyecto (la cantera de la 014 con operaciones sintéticas) ----------


def synthetic_definitions() -> tuple[Any, ...]:
    """Los tipos de operación de las pruebas: ``des.platform`` (el de la 015) y los de los dos tipos de prueba,
    de versión y sin recálculo."""

    def never(request: Any) -> Any:
        raise AssertionError("las pruebas del registro no recalculan")

    return (synthetic_definition(),
            *(contract.OperationDef(op_type, "1.0", "des", f"{op_type} of the tests", True, scope="version",
                                    recompute=never) for op_type in ("des.probe", "des.island")))


class RegistryProjectTest(efx.EntityProjectCase):
    """RF-016-02, RF-015-01, RF-015-02, RF-015-25 con proyecto: V01 con una plataforma (``PLT-001``), una de
    prueba que parte de su superficie (``PRB-001``, la cola de la cadena), otra suelta (``PLT-002``) y una sin
    cadena (``ISL-001``), todas con operación sintética salvo ``PLT-002``; V02, con dos de prueba que comparten
    **una** operación (la trampa de ``live = {operation_uid: code}``)."""

    STEP_M = qfx.COARSE_STEP_M
    STRAY = "des.island.prb_009.name"
    ops: ClassVar[dict[str, str]] = {}

    @classmethod
    def declare(cls, version: Any, code: str, values: dict[str, Any]) -> list[str]:
        """Da de alta en ``version`` los parámetros de la entidad ``code`` y devuelve sus claves."""
        store = core_params.ParameterStore(cls.project)
        cls.clock.advance(minutes=1)
        keys = []
        with cls.project.write_transaction() as conn:
            for param, value in values.items():
                if value is None:
                    continue
                key = params.entity_key(code, param)
                store.create(conn, key, value, kind="ADOPTADO", source="Prueba del registro por tipo",
                             source_kind="person", decided_by="Samuel (IMGA)", reason="Prueba de la T02",
                             version=version.code)
                keys.append(key)
        return keys

    @classmethod
    def run_operation(cls, version: Any, op_type: str, tag: str, keys: list[str], roles: tuple[str, str], *,
                      reads: str | None = None) -> str:
        """La operación sintética de ``op_type`` que lee los parámetros ``keys``, consume como ``surface`` el
        dato ``des_psf_<reads>`` y escribe ``des_psf_<tag>`` (papel ``roles[0]``) y ``des_epr_<tag>`` (``roles[1]``)."""
        cls.clock.advance(minutes=1)
        inputs = [operations.Use(f"des_psf_{reads}", "surface")] if reads else []
        handle = operations.begin_operation(
            cls.project, op_type, settings={"tag": tag}, inputs=inputs, params=keys, executor="blender",
            version=version.uid)
        specs = []
        with cls.project.write_transaction() as conn:
            for family, role in zip(("psf", "epr"), roles, strict=True):
                name = f"des_{family}_{tag}"
                locator = versions_model.version_locator(name, version.code)
                gpkg_base.create_attribute_table(conn, locator, [gpkg_base.ColumnDef("value", "DOUBLE")], name,
                                                 "Dato sintético de la prueba del registro por tipo (spec 016)")
                conn.execute(f'INSERT INTO "{locator}" (value) VALUES (?)', (1.0,))
                specs.append(datasets.DatasetSpec(name, "des", "table", datasets.Store.GPKG, locator,
                                                  reader=builtin.GPKG_LAYER.id, role=role))
            handle.complete(conn, outputs=specs)
        return str(handle.uid)

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.enterClassContext(types_registered(families=True))
        cls.enterClassContext(registered(*synthetic_definitions()))
        surface = (provenance.ENTITY_SURFACE_ROLE, provenance.ENTITY_ROLE)
        own = (ISLAND_SURFACE_ROLE, ISLAND_TABLE_ROLE)
        v1, v2 = cls.v1, cls.v2
        keys = {
            "PLT-001": cls.declare(v1, "PLT-001", {"name": "P1", "start": GROUND}),
            "PRB-001": cls.declare(v1, "PRB-001", {"name": "S1", "start": entities.surface_ref("PLT-001")}),
            "ISL-001": cls.declare(v1, "ISL-001", {"name": "Acopios", "area_m2": 12.5}),
            "PLT-002": cls.declare(v1, "PLT-002", {"name": "P2", "start": "des_srf_otra"}),
        }
        # Un parámetro de la familia de ``island`` con el código de otro tipo (``prb_009``): no es una entidad.
        cls.clock.advance(minutes=1)
        with cls.project.write_transaction() as conn:
            core_params.ParameterStore(cls.project).create(
                conn, cls.STRAY, "Ajena", kind="ADOPTADO", source="Prueba del registro por tipo",
                source_kind="person", decided_by="Samuel (IMGA)", reason="Prueba de la T02", version=v1.code)
        cls.ops = {
            "PLT-001": cls.run_operation(v1, provenance.PLATFORM, "p1", keys["PLT-001"], surface),
            "PRB-001": cls.run_operation(v1, "des.probe", "s1", keys["PRB-001"], surface, reads="p1"),
            "ISL-001": cls.run_operation(v1, "des.island", "isl1", keys["ISL-001"], own),
        }
        shared = [*cls.declare(v2, "PRB-001", {"name": "A", "start": "des_srf_a"}),
                  *cls.declare(v2, "PRB-002", {"name": "B", "start": "des_srf_b"})]
        cls.ops["shared"] = cls.run_operation(v2, "des.probe", "ab", shared, surface)

    def registry(self, version: Any = None) -> Any:
        return entities.registry(self.project, (version or self.v1).uid)

    def test_the_registry_lists_every_type_with_its_own_family(self) -> None:
        """RF-016-02, RF-015-01, RF-015-25: el registro de una versión recorre los tipos registrados, cada uno
        con su familia de parámetros: sus códigos por tipo (en el orden de registro de los tipos) y por número,
        el nombre, la partida (sin ella, la de un tipo sin cadena) y el estado deducido del grafo; el tipo de
        cada entidad, el de su código; lo de la versión de al lado no entra."""
        found = self.registry()
        self.assertEqual(codes(found.records), ["PLT-001", "PLT-002", "PRB-001", "ISL-001"])
        self.assertEqual([item.name for item in found.records], ["P1", "P2", "S1", "Acopios"])
        self.assertEqual([item.kind for item in found.records],
                         [PLATFORM, PLATFORM, entities.EntityKind(PROBE), entities.EntityKind(ISLAND)])
        self.assertTrue(all(item.record.kind is entities.kind_of_code(item.record.code) for item in found))
        self.assertEqual([item.start for item in found.records],
                         [GROUND, "des_srf_otra", entities.surface_ref("PLT-001"), None])
        self.assertEqual([item.state for item in found.records],
                         [State.CURRENT, State.UNCALCULATED, State.CURRENT, State.CURRENT])
        self.assertEqual({entry.record.code: entry.operation_uid for entry in found if entry.operation_uid},
                         {code: self.ops[code] for code in ("PLT-001", "PRB-001", "ISL-001")})
        self.assertEqual(entities.next_code(entities.EntityKind(PROBE), codes(found.records)), "PRB-002")
        self.assertEqual(entities.next_code(entities.EntityKind(ISLAND), codes(found.records)), "ISL-002")
        self.assertEqual(entities.next_code(PLATFORM, codes(found.records)), "PLT-003")
        self.assertEqual(codes(self.registry(self.v2).records), ["PRB-001", "PRB-002"])

    def test_a_value_of_the_wrong_family_does_not_make_an_entity(self) -> None:
        """RF-016-02, RF-015-01: una entidad es un código **con el prefijo de su tipo** y los parámetros de la
        familia de ese tipo: un parámetro de la familia de ``island`` con el código ``PRB-009`` (``STRAY``) no
        hace una entidad en ninguna de las dos familias, y el registro no mezcla los códigos de los tipos."""
        with self.project.read() as conn:
            (kept,) = conn.execute("SELECT COUNT(*) FROM gb_parameter WHERE key = ?", (self.STRAY,)).fetchone()
        self.assertEqual(kept, 1)
        self.assertNotIn("PRB-009", codes(self.registry().records))
        for item in self.registry().records:
            self.assertEqual(item.kind.prefix, item.code.partition("-")[0])

    def test_entity_surfaces_by_type(self) -> None:
        """RF-016-02, RF-015-15 (plan 016 §2.1: «un código por operación»): ``entity_surfaces`` da la superficie y
        la tabla de cada entidad viva y calculada **con los papeles de su tipo** (la de una sin cadena, los
        suyos), con su tipo y el uid de su operación; ``kinds`` deja solo los de unos tipos y ``skip`` quita
        códigos; una sin calcular no sale."""
        with self.project.read() as conn:
            everything = entity_store.entity_surfaces(conn, self.registry())
            only_island = entity_store.entity_surfaces(conn, self.registry(), kinds=[ISLAND])
            no_platform = entity_store.entity_surfaces(
                conn, self.registry(), kinds=(PROBE, entities.EntityKind(ISLAND)), skip=["PRB-001"])
            by_kind = entity_store.entity_surfaces(conn, self.registry(), kinds=[PLATFORM])
        self.assertEqual(list(everything), ["ISL-001", "PLT-001", "PRB-001"])  # por código: tipo y número
        for code, tag, kind in (("PLT-001", "p1", PLATFORM), ("PRB-001", "s1", PROBE), ("ISL-001", "isl1", ISLAND)):
            found = everything[code]
            self.assertEqual((found.code, found.surface, found.table), (code, f"des_psf_{tag}", f"des_epr_{tag}"))
            self.assertEqual(found.locator, versions_model.version_locator(f"des_epr_{tag}", self.v1.code))
            self.assertEqual((found.kind, found.operation_uid), (entities.EntityKind(kind), self.ops[code]))
        self.assertEqual(list(only_island), ["ISL-001"])
        self.assertEqual(only_island["ISL-001"], everything["ISL-001"])
        self.assertEqual(list(no_platform), ["ISL-001"])
        self.assertEqual(list(by_kind), ["PLT-001"])
        self.assertEqual(by_kind["PLT-001"], everything["PLT-001"])
        with self.assertRaises(ValueError):
            with self.project.read() as conn:
                entity_store.entity_surfaces(conn, self.registry(), kinds=["sandbar"])

    def test_two_entities_of_one_operation_do_not_overwrite_each_other(self) -> None:
        """RF-016-02, plan 016 §2.1 (trampa del registro con un código por operación): dos entidades que leyeron
        sus parámetros en **una misma** operación salen las dos de ``entity_surfaces`` (con el uid de su
        operación), no solo la última."""
        registry = self.registry(self.v2)
        self.assertEqual([entry.operation_uid for entry in registry], [self.ops["shared"]] * 2)
        with self.project.read() as conn:
            found = entity_store.entity_surfaces(conn, registry)
        self.assertEqual(list(found), ["PRB-001", "PRB-002"])
        self.assertEqual({item.surface for item in found.values()}, {"des_psf_ab"})
        self.assertEqual({item.operation_uid for item in found.values()}, {self.ops["shared"]})

    def test_the_freeze_asks_to_verify_the_tail_of_the_chains_only(self) -> None:
        """RF-016-02, RF-012-25, RF-015-04 (plan 016 §8: «prueba de congelar con una detección: no pide
        verificación»): de las entidades de la versión, congelar pide verificar la superficie de la última de
        cada cadena; la de un tipo sin cadena no es de ninguna."""
        with self.project.read() as conn:
            found = entities.chain_tail_surfaces(conn, self.v1.uid)
            wanted = {name: str(uid) for uid, name in conn.execute(
                "SELECT uid, name FROM gb_dataset WHERE name LIKE 'des_psf_%'") if name in ("des_psf_s1", "des_psf_isl1")}
        self.assertEqual(found, (wanted["des_psf_s1"],))
        self.assertNotIn(wanted["des_psf_isl1"], found)

    def test_nothing_starts_from_a_surface_of_a_type_without_chain_when_changing_the_start(self) -> None:
        """RF-016-02, RF-015-04 (T39, «Cambiar parámetro…»): cambiar la partida de ``PLT-002`` a la superficie de
        la entidad sin cadena se rechaza con ``des.chainless_start`` antes de escribir nada; a la de una que
        encadena, no."""
        key = params.entity_key("PLT-002", "start")
        with self.assertRaises(messages.DesignError) as caught:
            entity_store.check_parameter_change(self.project, key, "entity:ISL-001", version=self.v1.code)
        error = caught.exception
        self.assertEqual((error.code, error.field, error.value), ("des.chainless_start", key, "entity:ISL-001"))
        self.assertEqual((error.values["entity"], error.values["other"]), ("P2", "Acopios"))
        self.assertIsNone(entity_store.check_parameter_change(
            self.project, key, entities.surface_ref("PRB-001"), version=self.v1.code))

    def test_nothing_starts_from_a_surface_of_a_type_without_chain_when_creating(self) -> None:
        """RF-016-02, RF-015-04: crear una plataforma que parte de la superficie de la entidad sin cadena se
        rechaza con ``des.chainless_start``, **antes** de leer la capa ni nada, y sin escribir (la preparación es
        solo lectura); parte de la de una que encadena, sigue su camino."""
        asked = model.PlatformRequest(
            name="P9", fields=model.PlatformFields(layer="gis_fea_plataformas_ejes", width_field="ancho",
                                                   start_level_field="cota_inicial", gradient_field="pendiente"),
            feature="7", start="entity:ISL-001", edge_angle_deg=35.0, reach_m=50.0)
        with self.assertRaises(messages.DesignError) as caught:
            next(entity_store.prepare_platform_units(self.project, asked, self.v1, None))  # type: ignore[arg-type]
        self.assertEqual(caught.exception.code, "des.chainless_start")
        self.assertEqual(caught.exception.values["entity"], "P9")
        chained = model.PlatformRequest(name="P9", fields=asked.fields, feature="7",
                                        start=entities.surface_ref("PRB-001"), edge_angle_deg=35.0,
                                        reach_m=50.0)
        generator = entity_store.prepare_platform_units(self.project, chained, self.v1, None)  # type: ignore[arg-type]
        next(generator)  # el nombre, el código y la cadena están bien: lo siguiente es leer la capa
        generator.close()


if __name__ == "__main__":
    unittest.main()

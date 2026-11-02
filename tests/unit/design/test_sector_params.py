# SPDX-License-Identifier: GPL-3.0-or-later
"""El talud general máximo impuesto por sector (spec 013, T05; HU-013-2; RF-013-08, RF-013-09,
RF-013-10; plan 013 §5.2.2, D-4, D-23; ADR-0029; RF-008-01, RF-008-05, RF-009-24).

El talud que impone la propiedad en un sector es un parámetro por sector que guarda ``core.params``
como una **familia de versión** (ADR-0027) cuya clave lleva el **código** del sector
(``des.sector.{s}.max_general_slope_deg``; el perímetro de actuación como sector único, el
segmento reservado ``perimeter__``): sin esquema nuevo ni cambios en las specs 008 y 009.

- **Claves** (ADR-0029): el código es la clave, nunca el nombre ni el uid; ``perimeter__`` no lo
  puede generar el código de ningún sector real.
- **RF-013-09**: se resuelve para cada sector con el valor del sector en la versión activa o, si no
  lo tiene, con el del sector en el proyecto; un sector sin valor no impone ningún talud; la
  resolución anota el ámbito, el sector y la entrada del historial que usó, que es lo que anota
  ``begin_operation`` (RF-008-05), y el valor que está fuera de (0; 90) ° se rechaza al usarlo
  (``check_sector_slope``).
- **RF-013-08**: cambiarlo en un sector y una versión no lo cambia en los demás sectores ni en
  las demás versiones; y una versión puede levantar el talud que el proyecto impone.
- **RF-013-10**: redeclarar los sectores (nuevos uid, mismos códigos) conserva los valores con su
  historial; renombrar un sector deja su valor sin borrar y se lista como huérfano.
"""

from __future__ import annotations

import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, ClassVar

from tests.support import constraints_fixtures as cfx
from tests.support import constraints_project as cp
from tests.support import design_fixtures as dfx
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered

sectors_mod = import_geoblender("design.sectors")
design_params = import_geoblender("design.params")
model = import_geoblender("design.model")
messages = import_geoblender("design.messages")
core_params = import_geoblender("core.params")
cmodel = import_geoblender("core.constraints.model")
cprov = import_geoblender("core.constraints.provenance")
cstore = import_geoblender("core.constraints.store")
gsectors = import_geoblender("gis.masks.sectors")
contract = import_geoblender("core.provenance.contract")
operations = import_geoblender("core.provenance.operations")

PERIMETER_KEY = "des.sector.perimeter__.max_general_slope_deg"
BY_HAND = {"source": "Escritura de la finca (prueba)", "source_kind": "document",
           "decided_by": "Samuel (IMGA)"}
"""El origen y el decisor de los taludes de prueba (D-7: ninguno por defecto)."""
READ_TYPE = "des.test_read_slopes"
"""Una operación de versión de prueba que lee los taludes de los sectores."""

LAYER_A = "gis_fea_sectores_a"
LAYER_B = "gis_fea_sectores_b"
LAYER_C = "gis_fea_sectores_c"


def key_of(code: str) -> str:
    return f"des.sector.{code or 'perimeter__'}.max_general_slope_deg"


@contextmanager
def families_registered() -> Iterator[None]:
    """Registra las familias de ``design`` (lo hará ``bl``) y las quita al salir."""
    core_params.register_families(design_params.FAMILIES)
    try:
        yield
    finally:
        core_params.unregister_families("des")


def put(project: Any, clock: Any, code: str, value: float | None, *, version: Any = None,
        reason: str = "Talud impuesto por la propiedad") -> None:
    """Declara (o cambia) el talud de un sector en el proyecto o, con ``version``, en esa
    versión, con ``core.params`` y su historial."""
    store = core_params.ParameterStore(project)
    key = sectors_mod.slope_key(code)
    scope = None if version is None else version.code
    clock.advance(minutes=1)
    with project.write_transaction() as conn:
        if store.get(key, version=scope, conn=conn) is None:
            store.create(conn, key, value, kind="ADOPTADO", reason=reason, version=scope,
                         **BY_HAND)
        else:
            store.change(conn, key, value=value, reason=reason, version=scope)


def codes(found: Any) -> tuple[str, ...]:
    return tuple(item.code for item in found)


def slopes(found: Any) -> dict[str, float | None]:
    """Código → valor de los sectores que tienen alguna fila (``None``: fila sin valor)."""
    return {item.code: item.slope.value for item in found if item.slope is not None}


class SlopeKeyTest(unittest.TestCase):
    def test_the_key_of_a_sector_is_the_family_with_its_code(self) -> None:
        """RF-013-08, ADR-0029: la clave es la de la familia con el código del sector; es la de
        ``design.params`` y casa con el patrón de la familia."""
        key = sectors_mod.slope_key("sector_2")
        self.assertEqual(key, "des.sector.sector_2.max_general_slope_deg")
        self.assertEqual(key, design_params.sector_slope_key("sector_2"))
        family = next(item for item in design_params.FAMILIES
                      if item.pattern == "des.sector.{s}.max_general_slope_deg")
        self.assertEqual(family.match(key), ("sector_2",))

    def test_the_perimeter_uses_the_reserved_segment(self) -> None:
        """RF-013-07, ADR-0029 punto 2: el perímetro de actuación como sector único (código
        vacío en ``gis.masks.access``) usa el segmento reservado ``perimeter__``."""
        self.assertEqual(model.PERIMETER_SEGMENT, "perimeter__")
        self.assertEqual(sectors_mod.slope_key(""), PERIMETER_KEY)
        self.assertEqual(sectors_mod.slope_key(""),
                         design_params.sector_slope_key(model.PERIMETER_SEGMENT))

    def test_no_real_sector_can_have_the_reserved_segment(self) -> None:
        """ADR-0029 punto 2: ningún nombre da, con ``constraint_code``, un código con guiones
        bajos dobles o finales, así que ``perimeter__`` no choca con el de un sector real."""
        for name in ("perimeter__", "Perimeter__", "perimeter", "perimeter  ", "_perimeter__",
                     "perimeter___", "Perímetro__", "a__b"):
            with self.subTest(name=name):
                code = cmodel.constraint_code(name, (), prefix="s")
                self.assertNotEqual(code, model.PERIMETER_SEGMENT)
                self.assertNotIn("__", code)
                self.assertFalse(code.endswith("_"))

    def test_a_key_needs_a_code(self) -> None:
        """Un nombre, un código con mayúsculas o espacios, uno que empieza por un dígito o el
        mismo segmento reservado son un error del programa (``ValueError``): el segmento es
        siempre el código, nunca el nombre ni el uid (ADR-0029 punto 5)."""
        for bad in ("Sector 2", "S1", "1abc", "a-b", "perimeter__", None, 7):
            with self.subTest(code=bad):
                with self.assertRaises(ValueError):
                    sectors_mod.slope_key(bad)  # type: ignore[arg-type]


def seed_values(project: Any, clock: Any, v1: Any, v2: Any) -> None:
    """Los taludes de prueba: en el proyecto, el sector 1 a 12,0°; en V01, el sector 1 a 10,6° y el
    sector 2 a 18,0°; en V02, el sector 2 declarado sin valor (levantado)."""
    put(project, clock, "sector_1", 12.0)
    put(project, clock, "sector_1", 10.6, version=v1)
    put(project, clock, "sector_2", 18.0, version=v1)
    put(project, clock, "sector_2", None, version=v2)


class _SlopesCase(dfx.DesignProjectCase):
    """El proyecto del diseño con las familias de ``design`` registradas."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.enterClassContext(families_registered())

    def seed(self, project: Any = None, clock: Any = None) -> None:
        """``seed_values`` en ``project`` (por defecto, el de la clase)."""
        seed_values(self.project if project is None else project,
                    self.clock if clock is None else clock, self.v1, self.v2)


class _OwnCopies(unittest.TestCase):
    """Las pruebas que abren su propia copia del proyecto del diseño (``open_design_project``) con lo
    de la 012 y las familias de ``design`` registrados, sin una copia por clase que no usarían:
    solo hacen falta de V01 y V02 su uid y su código."""

    v1: ClassVar[Any]
    v2: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        first, second = dfx.project_template()["versions"]  # antes: la plantilla lo registra
        cls.enterClassContext(cp.constraints_registered())
        cls.enterClassContext(families_registered())
        cls.v1 = SimpleNamespace(uid=first, code="V01")
        cls.v2 = SimpleNamespace(uid=second, code="V02")

    def seed(self, project: Any, clock: Any) -> None:
        """``seed_values`` en la copia ``project``."""
        seed_values(project, clock, self.v1, self.v2)


class ResolveSlopesTest(_SlopesCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls("test_a_sector_takes_the_value_of_the_version_or_else_the_projects").seed()

    def test_a_sector_takes_the_value_of_the_version_or_else_the_projects(self) -> None:
        """RF-013-09, RF-013-08, ADR-0029: el talud de cada sector es el del sector en la versión
        activa o, si no lo tiene, el del sector en el proyecto. En V01, el sector 1 tiene el suyo
        (10,6°, de la versión) y el 2 también (18,0°); en V02, el 1 no tiene valor propio y usa el
        del proyecto (12,0°) y el 2 tiene su fila sin valor; sin versión, solo cuenta el
        proyecto."""
        cases = (
            (self.v1.uid, {"sector_1": ("version", 10.6), "sector_2": ("version", 18.0)}),
            (self.v2.uid, {"sector_1": ("project", 12.0), "sector_2": ("version", None)}),
            (self.v1.code, {"sector_1": ("version", 10.6), "sector_2": ("version", 18.0)}),
            (None, {"sector_1": ("project", 12.0)}),
        )
        for version, expected in cases:
            with self.subTest(version=version):
                found = sectors_mod.design_sectors(self.project, version)
                self.assertEqual(codes(found), ("sector_1", "sector_2"))
                self.assertEqual({item.code: (item.slope.param.scope, item.slope.value)
                                  for item in found if item.slope is not None}, expected)

    def test_a_sector_without_a_value_imposes_nothing(self) -> None:
        """RF-013-09, ADR-0029 punto 4: un sector sin fila en ningún ámbito (el 2 sin versión)
        no tiene talud ni se lee; uno con la fila sin valor (el 2 en V02) tampoco impone nada
        —y la fila se lee, así que se anota—; no hay un valor general de respaldo."""
        none = sectors_mod.design_sectors(self.project, None)
        self.assertIsNone(none[1].slope)
        self.assertEqual(sectors_mod.imposed_slopes(none), {"sector_1": 12.0})
        self.assertEqual(sectors_mod.slope_params(none), (key_of("sector_1"),))
        v2 = sectors_mod.design_sectors(self.project, self.v2.uid)
        self.assertIsNone(v2[1].slope.value)
        self.assertEqual(sectors_mod.imposed_slopes(v2), {"sector_1": 12.0})
        self.assertEqual(sectors_mod.slope_params(v2),
                         (key_of("sector_1"), key_of("sector_2")))

    def test_the_imposed_slope_of_each_sector_is_a_float_in_degrees(self) -> None:
        """RF-013-08, RF-013-09: ``imposed_slopes`` da código → grados (float64, comprobado con
        ``check_sector_slope``) de los sectores que imponen uno, y ``DesignSector.imposed_deg``,
        el de uno."""
        v1 = sectors_mod.design_sectors(self.project, self.v1.uid)
        imposed = sectors_mod.imposed_slopes(v1)
        self.assertEqual(imposed, {"sector_1": 10.6, "sector_2": 18.0})
        self.assertTrue(all(type(value) is float for value in imposed.values()))
        self.assertEqual([item.imposed_deg for item in v1], [10.6, 18.0])
        self.assertEqual([item.key for item in v1], [key_of("sector_1"), key_of("sector_2")])

    def test_the_resolution_notes_scope_sector_and_history_entry(self) -> None:
        """RF-013-09, RF-008-05: lo resuelto dice el sector, la clave, el ámbito (versión o
        proyecto, con su uid), la entrada del historial que se usó (su revisión) y el tipo, el
        origen y el decisor del valor, para mostrarlos (RF-013-07)."""
        store = core_params.ParameterStore(self.project)
        v1 = sectors_mod.design_sectors(self.project, self.v1.uid)
        v2 = sectors_mod.design_sectors(self.project, self.v2.uid)
        for found, version, code, scope, scope_uid in (
                (v1, self.v1, "sector_1", "version", self.v1.uid),
                (v2, self.v2, "sector_1", "project", ""),
                (v1, self.v1, "sector_2", "version", self.v1.uid)):
            with self.subTest(version=version.code, sector=code):
                slope = next(item for item in found if item.code == code).slope
                self.assertEqual((slope.sector, slope.key), (code, key_of(code)))
                self.assertEqual((slope.param.scope, slope.param.scope_uid), (scope, scope_uid))
                history = store.history(slope.key, version=scope_uid or None)
                self.assertEqual(slope.param.rev, history[-1].rev)
                self.assertEqual(slope.param.parameter_uid, history[-1].parameter_uid)
                self.assertEqual(slope.record.uid, slope.param.parameter_uid)
                self.assertEqual((slope.record.kind, slope.record.decided_by),
                                 ("ADOPTADO", "Samuel (IMGA)"))
                self.assertEqual(slope.record.source, BY_HAND["source"])
                self.assertIn(slope.record.source_kind, ("document",))
                self.assertFalse(slope.record.unconfirmed)

    def test_a_new_entry_of_the_history_is_the_one_used(self) -> None:
        """RF-009-24, RF-008-05: tras cambiar el valor, la resolución usa la entrada nueva del
        historial (revisión 2) y no la anterior; el cambio es de una copia."""
        with dfx.open_design_project("gb-sp-") as (project, clock):
            self.seed(project, clock)
            before = sectors_mod.design_sectors(project, self.v1.uid)[0].slope
            put(project, clock, "sector_1", 9.5, version=self.v1, reason="Nuevo informe")
            after = sectors_mod.design_sectors(project, self.v1.uid)[0].slope
        self.assertEqual((before.value, before.param.rev), (10.6, 1))
        self.assertEqual((after.value, after.param.rev), (9.5, 2))
        self.assertEqual(after.param.parameter_uid, before.param.parameter_uid)

    def test_a_value_outside_its_range_is_refused_when_used(self) -> None:
        """RF-013-08, RF-013-09: el talud es de 0 a 90° ambos excluidos, y el 90 no lo rechaza
        ``ParamDef`` (solo excluye el mínimo): al usarlo, ``imposed_slopes`` lo rechaza con
        ``des.sector_slope_range`` nombrando el sector, la clave del campo y el valor. Listar los
        sectores no falla (la ventana tiene que poder corregirlo)."""
        with dfx.open_design_project("gb-sp-") as (project, clock):
            put(project, clock, "sector_2", 90.0)
            found = sectors_mod.design_sectors(project, None)
            self.assertEqual(found[1].slope.value, 90.0)
            with self.assertRaises(messages.DesignError) as raised:
                sectors_mod.imposed_slopes(found)
            with self.assertRaises(messages.DesignError):
                found[1].imposed_deg  # noqa: B018
        error = raised.exception
        self.assertEqual(error.code, "des.sector_slope_range")
        self.assertIn("sector_2", error.text)
        self.assertIn(key_of("sector_2"), error.text)
        self.assertIn("90", error.text)

    def test_the_perimeter_as_the_only_sector_has_its_own_key(self) -> None:
        """RF-013-07, ADR-0029 punto 2: sin sectores declarados, el perímetro de actuación es el
        único y su talud es el de la clave ``perimeter__``, de su ámbito (versión o proyecto)."""
        with dfx.open_design_project("gb-sp-") as (project, clock):
            with project.write_transaction() as conn:
                conn.execute("DELETE FROM core_sector")
            put(project, clock, "", 14.0)
            put(project, clock, "", 8.5, version=self.v1)
            in_v2 = sectors_mod.design_sectors(project, self.v2.uid)
            in_v1 = sectors_mod.design_sectors(project, self.v1.uid)
        self.assertEqual(codes(in_v1), ("",))
        self.assertEqual((in_v1[0].key, in_v1[0].slope.param.scope, in_v1[0].imposed_deg),
                         (PERIMETER_KEY, "version", 8.5))
        self.assertEqual((in_v2[0].slope.param.scope, in_v2[0].imposed_deg), ("project", 14.0))
        self.assertEqual(sectors_mod.imposed_slopes(in_v1), {"": 8.5})


class AnnotationTest(_OwnCopies):
    """Lo que resuelve ``design`` es lo que anota una operación de versión al empezar."""

    def test_the_operation_notes_what_the_design_resolved(self) -> None:
        """RF-013-09, RF-008-05: ``slope_params`` son las claves que se pasan a
        ``begin_operation(params=…)``; la operación de versión anota, de cada una, la misma fila
        y la misma revisión del historial que resolvió ``design`` (en V01 la de la versión; en
        V02, el sector 1 con la del proyecto), y un sector sin valor ni fila no se anota (no se
        registra ningún parámetro por defecto vacío)."""
        op = contract.OperationDef(READ_TYPE, "1.0", "des", "Read the sector slopes", False,
                                   scope="version")
        with registered(op), dfx.open_design_project("gb-sp-") as (project, clock):
            self.seed(project, clock)
            for version, scope in ((self.v1, "version"), (self.v2, "project")):
                with self.subTest(version=version.code):
                    found = sectors_mod.design_sectors(project, version.uid)
                    params = sectors_mod.slope_params(found)
                    handle = operations.begin_operation(project, READ_TYPE, settings={},
                                                        params=params, executor="blender",
                                                        version=version.uid)
                    try:
                        noted = {item.key: item for item in handle.params}
                        self.assertEqual(set(noted), set(params))
                        for item in found:
                            self.assertEqual(noted[item.key], item.slope.param)
                        first = noted[key_of("sector_1")]
                        self.assertEqual((first.scope, first.rev), (scope, 1))
                        with project.read() as conn:
                            rows = conn.execute(
                                "SELECT key, scope, rev FROM gb_operation_param "
                                "WHERE operation_uid = ? ORDER BY key", (handle.uid,)).fetchall()
                        self.assertEqual(rows, [(item.key, item.slope.param.scope,
                                                 item.slope.param.rev) for item in found])
                    finally:
                        handle.cancel("Prueba")

    def test_a_sector_without_any_row_is_not_noted_and_no_empty_parameter_is_created(self) -> None:
        """RF-013-09, RF-008-04: sin ninguna fila (el sector 2 sin versión), ``slope_params`` no
        lo nombra y ``begin_operation`` no crea un parámetro vacío en el proyecto."""
        op = contract.OperationDef(READ_TYPE, "1.0", "des", "Read the sector slopes", False,
                                   scope="version")
        with registered(op), dfx.open_design_project("gb-sp-") as (project, clock):
            put(project, clock, "sector_1", 12.0)
            found = sectors_mod.design_sectors(project, self.v1.uid)
            self.assertEqual(sectors_mod.slope_params(found), (key_of("sector_1"),))
            handle = operations.begin_operation(
                project, READ_TYPE, settings={}, params=sectors_mod.slope_params(found),
                executor="blender", version=self.v1.uid)
            try:
                with project.read() as conn:
                    keys = [row[0] for row in conn.execute(
                        "SELECT key FROM gb_parameter WHERE key LIKE 'des.sector.%'")]
                self.assertEqual(keys, [key_of("sector_1")])
            finally:
                handle.cancel("Prueba")


class IndependenceTest(_OwnCopies):
    """RF-013-08: el valor es de un sector y de una versión."""

    def values(self, project: Any) -> dict[Any, Any]:
        """(versión, sector) → (valor, revisión) de lo que se resuelve en cada una."""
        return {(version, item.code): (item.slope.value, item.slope.param.rev, item.slope.param.scope)
                for version in (self.v1.uid, self.v2.uid, None)
                for item in sectors_mod.design_sectors(project, version) if item.slope is not None}

    def test_changing_one_sector_in_one_version_changes_no_other(self) -> None:
        """RF-013-08, D-4: cambiar el talud del sector 1 en V01 no cambia el del sector 2 en
        V01, ni el del sector 1 en V02 ni en el proyecto: solo cambia (V01, sector 1), que sube
        de revisión; las demás resoluciones, y su historial, son las de antes."""
        with dfx.open_design_project("gb-ip-") as (project, clock):
            self.seed(project, clock)
            store = core_params.ParameterStore(project)
            keys = [key_of("sector_1"), key_of("sector_2")]
            history = {(key, scope): store.history(key, version=scope)
                       for key in keys for scope in (None, self.v1.uid, self.v2.uid)}
            before = self.values(project)
            put(project, clock, "sector_1", 7.25, version=self.v1, reason="Otra sentencia")
            after = self.values(project)
            after_history = {(key, scope): store.history(key, version=scope)
                             for key in keys for scope in (None, self.v1.uid, self.v2.uid)}
        changed = {where for where in before if before[where] != after[where]}
        self.assertEqual(changed, {(self.v1.uid, "sector_1")})
        self.assertEqual(after[(self.v1.uid, "sector_1")], (7.25, 2, "version"))
        self.assertEqual(after[(self.v2.uid, "sector_1")], (12.0, 1, "project"))
        self.assertEqual(after[(None, "sector_1")], (12.0, 1, "project"))
        self.assertEqual({where: entries for where, entries in after_history.items()
                          if where != (key_of("sector_1"), self.v1.uid)},
                         {where: entries for where, entries in history.items()
                          if where != (key_of("sector_1"), self.v1.uid)})
        self.assertEqual(len(after_history[(key_of("sector_1"), self.v1.uid)]), 2)

    def test_a_version_can_lift_the_slope_the_project_imposes(self) -> None:
        """RF-013-08, RF-013-09, D-4 de la 012: la propiedad impone un talud en un sector en el
        proyecto (20,0°) y una versión lo levanta con su fila sin valor: en esa versión el sector
        no impone nada, y en las demás sigue imponiendo el del proyecto."""
        with dfx.open_design_project("gb-ip-") as (project, clock):
            put(project, clock, "sector_2", 20.0)
            put(project, clock, "sector_2", None, version=self.v2)
            in_v1 = sectors_mod.design_sectors(project, self.v1.uid)
            in_v2 = sectors_mod.design_sectors(project, self.v2.uid)
        self.assertEqual(sectors_mod.imposed_slopes(in_v1), {"sector_2": 20.0})
        self.assertEqual(sectors_mod.imposed_slopes(in_v2), {})
        self.assertEqual(in_v2[1].slope.param.scope, "version")


class RedeclareTest(dfx.DesignProjectCase):
    """RF-013-10: declarar de nuevo los sectores desde una capa (``core.declare_sectors``, que
    les da uid nuevos) y renombrar uno."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.enterClassContext(families_registered())
        declare = next(item for item in cprov.OPERATIONS if item.op_type == cprov.DECLARE_SECTORS)
        cls.enterClassContext(registered(declare))
        helper = cls("test_redeclaring_keeps_the_values_and_renaming_leaves_them_orphans")
        west, east = (20.0, 20.0, 90.0, 180.0), (110.0, 20.0, 180.0, 180.0)
        narrow_west, narrow_east = (20.0, 20.0, 70.0, 180.0), (130.0, 20.0, 180.0, 180.0)
        both = ("Entidad 1", "Entidad 2")
        helper.write_layer(LAYER_A, [[[cfx.rectangle(*west)]], [[cfx.rectangle(*east)]]],
                           names=both)
        helper.write_layer(LAYER_B, [[[cfx.rectangle(*narrow_west)]],
                                     [[cfx.rectangle(*narrow_east)]]], names=both)
        helper.write_layer(LAYER_C, [[[cfx.rectangle(*west)]], [[cfx.rectangle(*east)]]],
                           names=("Entidad 1", "Zona oeste"))

    def declare(self, layer: str | None) -> None:
        self.clock.advance(minutes=1)
        gsectors.declare_sectors(self.project, layer, None if layer is None else "nombre")

    def stored_uids(self) -> tuple[str, ...]:
        with self.project.read() as conn:
            return tuple(sector.uid for sector in cstore.read_sectors(conn))

    def histories(self) -> dict[tuple[str, str], Any]:
        """(clave, ámbito) → historial de todo lo que hay de los taludes, sin interpretar."""
        store = core_params.ParameterStore(self.project)
        with self.project.read() as conn:
            rows = conn.execute("SELECT key, scope_uid FROM gb_parameter WHERE key LIKE "
                                "'des.sector.%' ORDER BY key, scope_uid").fetchall()
        return {(key, scope): store.history(key, version=scope or None) for key, scope in rows}

    def test_redeclaring_keeps_the_values_and_renaming_leaves_them_orphans(self) -> None:
        """RF-013-10, ADR-0029 puntos 3 y 5, RF-013-08: (1) con dos sectores declarados y unos
        valores (el 1 en V01 y en el proyecto, el 2 en el proyecto), (2) declarar de nuevo desde
        otra capa con los mismos nombres cambia los uid pero no los códigos: los valores siguen
        donde estaban, con su historial entero, y no hay huérfanos; (3) renombrar el sector 2
        («Zona oeste») deja su valor sin borrar y lo lista como huérfano, y el sector nuevo no
        impone nada; (4) volver a llamarlo como antes lo recupera; (5) sin capa (el perímetro
        como único sector) los de los dos son huérfanos y el del perímetro vale; (6) con la capa
        otra vez, el del perímetro es el huérfano."""
        # (1)
        self.declare(LAYER_A)
        first_uids = self.stored_uids()
        found = sectors_mod.design_sectors(self.project, self.v1.uid)
        self.assertEqual(codes(found), ("entidad_1", "entidad_2"))
        self.assertEqual(slopes(found), {})
        self.assertEqual(sectors_mod.orphan_slopes(self.project, found), ())
        put(self.project, self.clock, "entidad_1", 12.0)
        put(self.project, self.clock, "entidad_1", 10.6, version=self.v1)
        put(self.project, self.clock, "entidad_2", 20.0)
        put(self.project, self.clock, "entidad_2", 17.0, reason="Segunda sentencia")
        before = self.histories()
        self.assertEqual(len(before), 3)
        self.assertEqual(len(before[(key_of("entidad_2"), "")]), 2)

        # (2) mismos nombres, otra geometría: nuevos uid, los mismos códigos
        self.declare(LAYER_B)
        self.assertEqual(len(set(self.stored_uids()) & set(first_uids)), 0)
        found = sectors_mod.design_sectors(self.project, self.v1.uid)
        self.assertEqual(codes(found), ("entidad_1", "entidad_2"))
        self.assertEqual(slopes(found), {"entidad_1": 10.6, "entidad_2": 17.0})
        self.assertEqual(sectors_mod.imposed_slopes(found), {"entidad_1": 10.6, "entidad_2": 17.0})
        in_v2 = sectors_mod.design_sectors(self.project, self.v2.uid)
        self.assertEqual(sectors_mod.imposed_slopes(in_v2), {"entidad_1": 12.0, "entidad_2": 17.0})
        self.assertEqual(self.histories(), before)  # el historial entero, sin tocar
        self.assertEqual(sectors_mod.orphan_slopes(self.project, found), ())

        # (3) renombrar el sector 2
        self.declare(LAYER_C)
        found = sectors_mod.design_sectors(self.project, self.v1.uid)
        self.assertEqual(codes(found), ("entidad_1", "zona_oeste"))
        self.assertEqual([item.name for item in found], ["Entidad 1", "Zona oeste"])
        self.assertIsNone(found[1].slope)
        self.assertEqual(sectors_mod.imposed_slopes(found), {"entidad_1": 10.6})
        (orphan,) = sectors_mod.orphan_slopes(self.project, found)
        self.assertEqual((orphan.segment, orphan.key, orphan.scope, orphan.version, orphan.value),
                         ("entidad_2", key_of("entidad_2"), "project", "", 17.0))
        self.assertEqual(orphan.record.decided_by, "Samuel (IMGA)")
        self.assertEqual(orphan.record.rev, 2)
        self.assertEqual(self.histories(), before)  # no se borra nada

        # (4) el nombre de antes recupera el valor
        self.declare(LAYER_A)
        found = sectors_mod.design_sectors(self.project, self.v1.uid)
        self.assertEqual(sectors_mod.imposed_slopes(found), {"entidad_1": 10.6, "entidad_2": 17.0})
        self.assertEqual(sectors_mod.orphan_slopes(self.project, found), ())

        # (5) sin capa: el perímetro como único sector; los de los dos sectores quedan huérfanos
        self.declare(None)
        found = sectors_mod.design_sectors(self.project, self.v1.uid)
        self.assertEqual(codes(found), ("",))
        self.assertIsNone(found[0].slope)
        orphans = sectors_mod.orphan_slopes(self.project, found)
        self.assertEqual([(item.segment, item.scope, item.version, item.value)
                          for item in orphans],
                         [("entidad_1", "project", "", 12.0), ("entidad_1", "version", "V01", 10.6),
                          ("entidad_2", "project", "", 17.0)])
        put(self.project, self.clock, "", 9.0)
        found = sectors_mod.design_sectors(self.project, self.v1.uid)
        self.assertEqual((found[0].key, found[0].imposed_deg), (PERIMETER_KEY, 9.0))
        self.assertEqual(len(sectors_mod.orphan_slopes(self.project, found)), 3)

        # (6) con la capa otra vez, el perímetro ya no es un sector: su valor es el huérfano
        self.declare(LAYER_A)
        found = sectors_mod.design_sectors(self.project, self.v1.uid)
        (orphan,) = sectors_mod.orphan_slopes(self.project, found)
        self.assertEqual((orphan.segment, orphan.key, orphan.value),
                         ("perimeter__", PERIMETER_KEY, 9.0))
        self.assertEqual(sectors_mod.imposed_slopes(found), {"entidad_1": 10.6, "entidad_2": 17.0})


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: GPL-3.0-or-later
"""La compilación de las máscaras con las restricciones declaradas por las entidades (spec 015, T18;
HU-015-1; RF-012-16, RF-012-29, RF-015-10, RF-012-12, RF-012-06, RF-012-14; plan 015 §5.1, §5.7 P-8;
ADR-0028 §2 y §4, ADR-0030 §3).

Sobre el proyecto de ``tests.support.constraints_project`` (160 × 160 celdas de 2 m, V01 y V02) con la
restricción que declara una entidad en V01 (``tests.support.entity_fixtures``: ``dec__plt_001``, «sin
relleno», una huella de 300 celdas y 4 m de resguardo). ``gis.compile_constraints`` la lleva a las
máscaras como una restricción más: la tabla de las declaradas de la versión es una **entrada** (papel
``constraints_declared``) y su resguardo y su «activa» son **columnas** de esa tabla que se inyectan bajo
las claves de siempre (P-8), sin parámetros del almacén.

- **RF-012-16, RF-015-10** (``DeclaredMasksTest``): las máscaras de V01 tienen la zona de la declarada
  (las celdas de la huella ampliadas en su resguardo, calculadas aquí con otra fórmula), el relleno
  admitido la excluye y el corte no cambia; la tabla es una entrada de la compilación y sus claves no
  están entre los parámetros; sus cifras y su informe llevan su código; V02 no la usa (RF-012-29).
- **RF-012-29** (listados): ``listed_constraints``, ``shown_constraints_steps`` y ``listed_constraint``
  llevan la declarada con su entidad como origen, solo en la versión que la tiene.
- **RF-012-14** (``DeclaredSumTest``): una declarada y una del proyecto sobre las mismas celdas se suman
  (una prohibición no la quita ninguna prioridad); el código declarado no choca con el de una del proyecto
  con un nombre parecido.
- **RF-012-19, RF-015-11** (``DeclaredListingBlockedTest``, T21): la declarada lleva su resguardo (columna de su
  tabla) en las listas; con su dato bloqueado por una edición fuera de Geoblender, su estado es ``blocked``; una
  tabla que ya no se puede leer no tumba las listas (no la enseñan) y compilar no la ignora.
- **RF-012-06, RF-015-10** (``DeclaredChangesTest``): repetir la declaración con las mismas filas no deja
  las máscaras obsoletas; cambiar el resguardo o el contorno las deja y la compilación da lo ganado y lo
  perdido de la declarada, por su código; quitarla devuelve las máscaras de antes.
- **RF-012-06** (``DeclaredNewTest``): una declarada que la compilación anterior no tenía da su polígono
  y su zona como ganados.
- **RF-012-16** (``DeclaredEmptyTest``, ``DeclaredInactiveTest``): con la tabla viva y vacía, o con la
  declarada desactivada, las máscaras son las de sin declaradas.
- **RF-012-15** (``DeclaredOutsideGridTest``): una zona que con su resguardo se sale de la rejilla se avisa.
- **Sin declaradas** (``NoDeclaredTest``): las entradas son exactamente las de la 012 y ``OP_VERSION`` no
  sube: lo compilado antes de la 015 sigue al día.

La T19 cierra **el hueco H-1** (``gis.masks.access``; plan 015 §5.8) y congela y reproduce lo declarado
(RF-012-06, RF-012-29, RF-015-10, RF-015-16):

- **RF-012-06, RF-012-29, RF-015-10** (``DeclaredHoleTest``, ``BeforeThe015Test``): un dato nuevo no deja
  obsoleto lo que ya se calculó (el grafo deduce solo de lo que la operación consumió), así que una
  declarada que aparece **después** de compilar dejaría las máscaras «al día» sin su prohibición (el error
  51): ``mask_state`` las da obsoletas, con su causa (``MaskCause.DECLARED_NEW`` y el mensaje
  ``core.constraint_masks_declared_new``), y quien las pide las recompila; lo que las usó queda obsoleto al
  recompilarlas. Una versión compilada antes de la 015 sigue al día mientras no haya una tabla de declaradas
  viva; una compilación que la consumió (aunque esté vacía) está al día mientras su hash no cambie.
- **RF-012-29** (``DeclaredOtherVersionTest``): la declarada de V01 no hace obsoletas las máscaras de V02, que
  no la ve ni la consume, y V01 recompila sola con ella.
- **RF-012-16, RF-012-29, RF-015-10** (``DeclaredReproduceTest``): congelar V01.r1 y reproducirla da las
  **mismas máscaras con la declarada**, bit a bit, aunque lo vivo ya sea otro.
"""

from __future__ import annotations

import dataclasses
import json
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as fx
from tests.support import constraints_project as cp
from tests.support import entity_fixtures as efx
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.versions_fixtures import change_counter, files

access = import_geoblender("gis.masks.access")
cmessages = import_geoblender("core.constraints.messages")
contract = import_geoblender("core.provenance.contract")
core_params = import_geoblender("core.params")
design_provenance = import_geoblender("design.provenance")
figures_mod = import_geoblender("core.provenance.figures")
freeze = import_geoblender("core.versions.freeze")
operations = import_geoblender("core.provenance.operations")
reproduce = import_geoblender("core.versions.reproduce")
combine = import_geoblender("gis.masks.combine")
provenance = import_geoblender("gis.masks.provenance")
masks_store = import_geoblender("gis.masks.store")
cparams = import_geoblender("core.constraints.params")
cmodel = import_geoblender("core.constraints.model")
cstore = import_geoblender("core.constraints.store")
declared = import_geoblender("core.constraints.declared")
entities = import_geoblender("design.entities")
polygons = import_geoblender("gis.polygons")

T = cmodel.ConstraintType
CODE = efx.DECLARED_CODE
GRID = fx.SITE_GRID
TOWER_KEY = cparams.buffer_out_key("torre")
OUTWARD = cparams.buffer_out_key(CODE)
ACTIVE = cparams.active_key(CODE)
BOX = efx.DECLARED_BOX_LOCAL
TABLE = "des_decl_v01"
GUARD = efx.DECLARED_GUARD_M
CELL_M2 = GRID.dx * GRID.dy
FOOTPRINT_CELLS = efx.DECLARED_CELLS
ZONE_CELLS = 24 * 19
"""Las celdas de la zona de la declarada de prueba: la caja de 40 × 30 m (20 × 15 celdas) con 4 m (2
celdas) por cada lado: 24 × 19 (las esquinas, a 2,83 m del contorno, entran)."""


def _last(steps: Iterator[Any]) -> Any:
    result = None
    for step in steps:
        if step.result is not None:
            result = step.result
    return result


def _box_cells(box: tuple[float, float, float, float]) -> np.ndarray:
    """Las celdas de ``GRID`` cuyo centro cae dentro de ``box`` (local: izquierda, abajo, derecha, arriba)."""
    x, y = fx.site_centers()
    left, bottom, right, top = box
    return (x > left) & (x < right) & (y > bottom) & (y < top)


def zone_cells(box: tuple[float, float, float, float], guard: float) -> np.ndarray:
    """La zona de una huella rectangular ``box`` con ``guard`` m de resguardo, **por distancias de celda
    a rectángulo** (otra fórmula que la de la 012): con 0, las celdas de la huella; con más, las celdas
    con alguna parte a menos de ``guard`` m de ella."""
    if guard <= 0.0:
        return _box_cells(box)
    left, bottom, right, top = box
    x0 = (GRID.west - fx.BASE[0]) + np.arange(GRID.ncols) * GRID.dx
    y1 = (GRID.north - fx.BASE[1]) - np.arange(GRID.nrows) * GRID.dy
    zero = np.zeros(GRID.ncols)
    gap_x = np.maximum.reduce([left - (x0 + GRID.dx), zero, x0 - right])
    gap_y = np.maximum.reduce([bottom - y1, np.zeros(GRID.nrows), (y1 - GRID.dy) - top])
    return np.hypot(gap_x[None, :], gap_y[:, None]) < guard


def declared_row(version_uid: str, *, entity: str = efx.DECLARED_ENTITY, name: str = "P1",
                 box: tuple[float, float, float, float] = BOX, guard: float = GUARD,
                 active: bool = True, ctype: Any = T.NO_FILL) -> Any:
    """Una restricción declarada de prueba de la versión ``version_uid``: la huella ``box`` (local)."""
    zone = entities.declared_zone(_box_cells(box), GRID, guard)
    return declared.DeclaredConstraint(
        uid=declared.declared_uid(version_uid, entity), code=declared.declared_code(entity),
        ctype=ctype, name=name, reason=entities.declared_reason(entities.EntityKind.PLATFORM, name),
        decided_by=efx.DECLARED_BY, decided_on=efx.DECLARED_ON, entity_code=entity,
        entity_name=name, parts=zone.parts, buffer_out_m=guard, active=active)


class _Compiled(efx.DeclaredConstraintsProjectCase):
    """Ayudas comunes: lo compilado, lo guardado y lo esperado sin declaradas."""

    def operation(self, version: Any = None) -> str:
        """El uid de la última compilación de ``version`` (por defecto V01)."""
        return str(self.query(
            "SELECT o.uid FROM gb_operation AS o JOIN gb_revision AS r ON r.uid = o.revision_uid "
            "WHERE o.op_type = ? AND r.version_uid = ? ORDER BY o.rowid DESC LIMIT 1",
            provenance.COMPILE, (version or self.v1).uid)[0][0])

    def inputs(self, uid: str) -> list[tuple[str, str]]:
        """``(nombre, papel)`` de lo que consumió la operación ``uid``, en su orden."""
        return [(str(name), str(role)) for name, role in self.query(
            "SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d "
            "ON d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'in' "
            "ORDER BY io.fid", uid)]

    def keys(self, uid: str) -> list[str]:
        """Las claves de los parámetros que usó la operación ``uid``."""
        return [str(row[0]) for row in self.query(
            "SELECT key FROM gb_operation_param WHERE operation_uid = ? ORDER BY fid", uid)]

    def report(self, uid: str, code: str) -> dict[str, tuple[Any, Any]]:
        """El informe de la compilación ``uid`` de la restricción ``code``: cantidad → (valor, nota)."""
        locator = self.query(
            "SELECT d.locator FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'out' AND d.name = ?",
            uid, provenance.dataset_name(provenance.REPORT))[0][0]
        with self.project.read() as conn:
            rows = masks_store.read_report(conn, locator)
        return {quantity: (value, note) for found, quantity, value, _unit, note in rows
                if found == code}

    def figure(self, uid: str, key: str, code: str) -> float | None:
        """La cifra ``key`` de la restricción ``code`` de la operación ``uid`` (``None`` si no la hay)."""
        found = self.query("SELECT value FROM gb_figure WHERE operation_uid = ? AND key = ? "
                           "AND scope = ?", uid, key, f'{{"constraint":"{code}"}}')
        return None if not found else float(found[0][0])

    def baseline(self, *, tower_m: float = cp.TOWER_V01_M,
                 extra: dict[str, Any] | None = None) -> Any:
        """Las máscaras de ``gis.masks.combine`` sobre las restricciones **del proyecto** solas (sin
        declaradas): lo que daba la 012; ``extra``, los parámetros de las que se añadieron."""
        resolved = dict(cp.project_values())
        resolved[TOWER_KEY] = tower_m
        resolved.update(extra or {})
        prepared = combine.prepare(self.stored_constraints(), resolved, GRID)
        return combine.combine(prepared.zones, prepared.limits, GRID)

    def content(self, name: str, version: Any = None) -> str:
        return str(self.record(name, version or self.v1).content_sha256)


class DeclaredMasksTest(_Compiled):
    """V01 con la declarada y V02 sin ella, compiladas (véase el módulo)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.masks_1 = cls.compile_version(cls.v1)
        cls.masks_2 = cls.compile_version(cls.v2)

    @classmethod
    def compile_version(cls, version: Any) -> Any:
        cls.clock.advance(minutes=1)
        return _last(access.ensure_masks_steps(cls.project, version.uid))

    def test_zone_of_the_declared_is_in_the_masks(self) -> None:
        """RF-012-16, RF-015-10, RF-012-12: las máscaras de V01 tienen la zona de la declarada
        (``dec__plt_001``): las celdas de la huella ampliadas en su resguardo, y el contorno de la
        huella con 0 m son exactamente sus 300 celdas (D-23)."""
        zone = self.masks_1.zone(CODE).mask(GRID.shape)
        self.assertEqual(int(zone.sum()), ZONE_CELLS)
        self.assertTrue((zone == zone_cells(BOX, GUARD)).all())
        self.assertEqual(int(_box_cells(BOX).sum()), FOOTPRINT_CELLS)
        self.assertEqual(self.masks_1.ctypes[CODE], "no_fill")
        self.assertIn(CODE, self.masks_1.zones)
        self.assertNotIn(CODE, self.masks_2.zones)

    def test_fill_allowed_excludes_the_zone_and_cut_is_not_touched(self) -> None:
        """RF-015-10, RF-012-14: el relleno admitido excluye la zona de la declarada (``fill_allowed``) y,
        fuera de ella, es el de sin declaradas; una prohibición de relleno no toca el corte admitido."""
        base = self.baseline()
        zone = zone_cells(BOX, GUARD)
        base_fill = base.fill_allowed.mask(GRID.shape)
        found = self.masks_1.fill_allowed()
        self.assertTrue((found == (base_fill & ~zone)).all())
        removed = int((base_fill & zone).sum())
        self.assertGreater(removed, FOOTPRINT_CELLS)  # la zona está dentro del dominio de relleno
        self.assertEqual(int(base_fill.sum()) - int(found.sum()), removed)
        self.assertFalse(found[zone].any())
        self.assertTrue((self.masks_1.cut_allowed() == base.cut_allowed.mask(GRID.shape)).all())
        domain = self.masks_1.default_domain()
        self.assertTrue((domain == base.default_domain.mask(GRID.shape)).all())

    def test_v02_is_not_touched_by_the_declared_of_v01(self) -> None:
        """RF-012-29, RF-012-16: V02, que no tiene la declarada, da las máscaras de sin declaradas (con el
        resguardo de la torre del proyecto, D-4) y no la usa: ni entrada ni zona."""
        base = self.baseline(tower_m=cp.TOWER_PROJECT_M)
        self.assertTrue((self.masks_2.fill_allowed() == base.fill_allowed.mask(GRID.shape)).all())
        self.assertTrue((self.masks_2.cut_allowed() == base.cut_allowed.mask(GRID.shape)).all())
        self.assertNotIn(CODE, self.masks_2.zones)
        self.assertNotIn(("des_decl", "constraints_declared"), self.inputs(self.operation(self.v2)))

    def test_the_table_is_an_input_and_its_columns_are_not_parameters(self) -> None:
        """RF-012-16, P-8: la tabla de las declaradas de V01 es una entrada (papel
        ``constraints_declared``, tras las tres capas), y el resguardo y la «activa» de la declarada, que
        son columnas, no están entre los parámetros de la operación (solo claves del almacén); los
        parámetros de las del proyecto son los de siempre."""
        uid = self.operation()
        inputs = self.inputs(uid)
        self.assertEqual(inputs.count(("des_decl", "constraints_declared")), 1)
        roles = [role for _name, role in inputs]
        self.assertEqual(roles[:4], ["constraints_polygon", "constraints_line", "constraints_point",
                                     "constraints_declared"])
        keys = self.keys(uid)
        self.assertTrue(keys)
        self.assertFalse([key for key in keys if "dec__" in key])
        self.assertIn(TOWER_KEY, keys)
        self.assertEqual(self.query("SELECT count(*) FROM gb_parameter WHERE key LIKE ?",
                                    "%dec__%")[0][0], 0)  # y ninguna se creó en el almacén
        self.assertEqual(provenance.compile_params(
            [item.as_constraint() for item in declared_rows(self)], {OUTWARD: 4.0, ACTIVE: True}), ())

    def test_figures_and_report_of_the_declared(self) -> None:
        """RF-012-16, RF-012-06: la zona de la declarada está en las cifras de la compilación y en su
        informe por su código: su área, su resguardo, el tipo y la huella."""
        uid = self.operation()
        self.assertEqual(self.figure(uid, "gis.zone_area_m2", CODE), ZONE_CELLS * CELL_M2)
        self.assertIsNone(self.figure(uid, "gis.zone_outside_grid_m2", CODE))
        found = self.report(uid, CODE)
        self.assertEqual(found["zone_area"], (ZONE_CELLS * CELL_M2, "no_fill"))
        self.assertEqual(found["zone_outside_grid"][0], 0.0)
        self.assertEqual(found["buffer"][0], GUARD)
        self.assertTrue(str(found["fingerprint"][1]).startswith("polygon|no_fill|4.0|"))

    def test_available_tables_have_the_declared_of_its_version(self) -> None:
        """RF-012-16: ``available_tables`` da el dato de las declaradas solo de la versión que lo tiene (y
        no sin versión): lo que consume ``compile_inputs``."""
        self.assertNotIn("des_decl", masks_store.available_tables(self.project))
        self.assertNotIn("des_decl", masks_store.available_tables(self.project, self.v2.uid))
        found = masks_store.available_tables(self.project, self.v1.uid)
        self.assertIn("des_decl", found)
        self.assertEqual(found - {"des_decl"}, masks_store.available_tables(self.project))
        uses = provenance.compile_inputs(found)
        self.assertEqual([use.role for use in uses][:4], [
            "constraints_polygon", "constraints_line", "constraints_point", "constraints_declared"])
        self.assertEqual(provenance.compile_inputs(found - {"des_decl"}),
                         provenance.compile_inputs(masks_store.available_tables(self.project)))

    def test_listings_carry_the_origin_of_the_declared(self) -> None:
        """RF-012-29, RF-012-19: las listas de la versión que la tiene llevan la declarada tras las del
        proyecto, con la entidad como origen y su estado; la de V02 y la del proyecto no la llevan."""
        listed = masks_store.listed_constraints(self.project, version=self.v1.uid)
        shown = polygons.drain(masks_store.shown_constraints_steps(self.project,
                                                                   version=self.v1.uid))
        found = [item for item in listed if item.declared]
        self.assertEqual([item.constraint.code for item in found], [CODE])
        entry = found[0]
        self.assertIs(listed[-1], entry)  # tras las cinco del proyecto
        self.assertEqual(len(listed), 6)
        self.assertEqual((entry.state, entry.problems), ("active", ()))
        self.assertEqual((entry.entity_code, entry.entity_name), (efx.DECLARED_ENTITY, "P1"))
        self.assertEqual(entry.constraint.ctype, T.NO_FILL)
        self.assertEqual(entry.constraint.priority, declared.DECLARED_PRIORITY)
        self.assertTrue(all(item.entity_code is None and not item.declared for item in listed[:5]))
        self.assertEqual([item.constraint.code for item in shown],
                         [item.constraint.code for item in listed])
        self.assertEqual((shown[-1].state, shown[-1].entity_name), ("active", "P1"))
        one = masks_store.listed_constraint(self.project, entry.constraint.uid, version=self.v1.uid)
        self.assertEqual((one.state, one.entity_code, one.constraint.code),
                         ("active", efx.DECLARED_ENTITY, CODE))
        for version in (self.v2.uid, None):
            self.assertEqual(len(masks_store.listed_constraints(self.project, version=version)), 5)
            self.assertIsNone(masks_store.listed_constraint(self.project, entry.constraint.uid,
                                                            version=version))

    def test_constraint_names_include_the_declared_of_the_version(self) -> None:
        """RF-012-29, RF-012-02: ``constraint_names`` con la versión incluye la declarada con el nombre de
        su entidad; sin versión (o con otra) da lo de siempre."""
        with self.project.read() as conn:
            plain = cstore.constraint_names(conn)
            first = cstore.constraint_names(conn, version_uid=self.v1.uid)
            other = cstore.constraint_names(conn, version_uid=self.v2.uid)
        self.assertNotIn(CODE, plain)
        self.assertEqual(other, plain)
        self.assertEqual(first[CODE], ("P1", T.NO_FILL))
        self.assertEqual({code: value for code, value in first.items() if code != CODE}, plain)


def declared_rows(case: Any) -> tuple[Any, ...]:
    """Las declaradas que hay en V01 de ``case``."""
    with case.project.read() as conn:
        return declared.read_in_version(conn, case.v1.uid)


class DeclaredSumTest(_Compiled):
    """Una restricción del proyecto «sin relleno» que se solapa con la zona de la declarada y otra «sin
    corte» con un nombre parecido (``dec_plt_001``)."""

    PROJECT_BOX = (150.0, 150.0, 190.0, 180.0)
    """Se solapa con la zona de la declarada (126 a 174 × 136 a 174) en 150 a 174 × 150 a 174."""
    PROJECT_NAME = "DEC PLT 001"
    CUT_BOX = (190.0, 120.0, 230.0, 140.0)

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.clock.advance(minutes=1)
        rows = (
            cp._constraint("reserva", "Reserva", T.NO_FILL, cp.G.POLYGON,
                           ((fx.rectangle(*cls.PROJECT_BOX),),)),
            cp._constraint(cmodel.constraint_code(cls.PROJECT_NAME, ()), cls.PROJECT_NAME,
                           T.NO_CUT, cp.G.POLYGON, ((fx.rectangle(*cls.CUT_BOX),),)),
        )
        cp.edit_constraints(cls.project, rows)
        cls.similar = rows[1].code
        cls.extra = {}
        for row in rows:
            cls.extra[cparams.active_key(row.code)] = True
            cls.extra[cparams.buffer_out_key(row.code)] = 0.0
        cp.declare(cls.project, cls.clock, cls.extra)
        cls.masks = _last(access.ensure_masks_steps(cls.project, cls.v1.uid))

    def test_a_declared_and_a_project_prohibition_add_up(self) -> None:
        """RF-012-14, RF-012-16: la declarada y la «sin relleno» del proyecto sobre las mismas celdas se
        suman: el relleno admitido no tiene las celdas de ninguna de las dos zonas (la prioridad no
        quita una prohibición), y el corte admitido solo pierde lo que prohíbe la de «sin corte»."""
        base = self.baseline(extra=self.extra)  # las del proyecto: la «sin relleno» nueva incluida
        declared_zone = zone_cells(BOX, GUARD)
        reserve = zone_cells(self.PROJECT_BOX, 0.0)
        overlap = declared_zone & reserve
        self.assertGreater(int(overlap.sum()), 0)
        self.assertEqual(self.masks.zone(CODE).mask(GRID.shape).sum(), declared_zone.sum())
        self.assertTrue((self.masks.zone("reserva").mask(GRID.shape) == reserve).all())
        fill = self.masks.fill_allowed()
        self.assertFalse(fill[declared_zone].any())
        self.assertFalse(fill[reserve].any())
        self.assertTrue((fill == (base.fill_allowed.mask(GRID.shape) & ~declared_zone)).all())
        self.assertTrue((self.masks.cut_allowed() == base.cut_allowed.mask(GRID.shape)).all())
        cut_zone = zone_cells(self.CUT_BOX, 0.0)
        self.assertFalse(self.masks.cut_allowed()[cut_zone].any())
        self.assertTrue(self.masks.cut_allowed()[declared_zone & ~cut_zone].any())

    def test_the_declared_code_does_not_clash_with_a_similar_project_code(self) -> None:
        """RF-012-29, RF-012-16: el código de la declarada (``dec__plt_001``) no choca con el de una
        restricción del proyecto con un nombre parecido (``dec_plt_001``): las dos compilan, cada una
        con su zona y su informe, y la comprobación no da ningún código repetido."""
        self.assertEqual(self.similar, "dec_plt_001")
        self.assertNotEqual(self.similar, CODE)
        self.assertTrue(declared.is_declared_code(CODE))
        self.assertFalse(declared.is_declared_code(self.similar))
        self.assertIn(CODE, self.masks.zones)
        self.assertIn(self.similar, self.masks.zones)
        self.assertEqual(self.masks.ctypes[self.similar], "no_cut")
        self.assertEqual(self.masks.ctypes[CODE], "no_fill")
        self.assertEqual(self.masks.zone(self.similar).mask(GRID.shape).sum(),
                         zone_cells(self.CUT_BOX, 0.0).sum())
        listed = masks_store.listed_constraints(self.project, version=self.v1.uid)
        codes = [item.constraint.code for item in listed]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual({code for code in codes if code.startswith("dec")}, {CODE, self.similar})
        self.assertTrue(all(item.state == "active" for item in listed))


class DeclaredChangesTest(_Compiled):
    """La historia de una declarada que cambia: recalcularla igual, otro resguardo, quitarla."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.masks_before = cls.compile_it()
        cls.first_op = cls.operation_of()

    @classmethod
    def compile_it(cls) -> Any:
        cls.clock.advance(minutes=1)
        return _last(access.ensure_masks_steps(cls.project, cls.v1.uid))

    @classmethod
    def operation_of(cls) -> str:
        with cls.project.read() as conn:
            return str(conn.execute(
                "SELECT o.uid FROM gb_operation AS o JOIN gb_revision AS r ON r.uid = o.revision_uid "
                "WHERE o.op_type = ? AND r.version_uid = ? ORDER BY o.rowid DESC LIMIT 1",
                (provenance.COMPILE, cls.v1.uid)).fetchone()[0])

    def redeclare(self, *rows: Any) -> None:
        """Repite la declaración de V01 con ``rows`` (sustituye a la vigente)."""
        current = self.query(
            "SELECT o.uid FROM gb_operation AS o JOIN gb_revision AS r ON r.uid = o.revision_uid "
            "WHERE o.op_type = 'des.declare_constraints' AND r.version_uid = ? "
            "AND o.superseded_by IS NULL ORDER BY o.rowid DESC LIMIT 1", self.v1.uid)[0][0]
        efx.declare_rows(self.project, self.clock, rows, version=self.v1, supersedes=str(current))

    def test_a_repeating_the_declaration_does_not_make_the_masks_obsolete(self) -> None:
        """RF-015-10, RF-012-06: repetir la declaración con las mismas filas deja la misma tabla (el mismo
        hash) y las máscaras al día: lo compilado no se vuelve obsoleto sin motivo."""
        table = declared.declared_table(self.v1.code)
        before = self.query("SELECT content_sha256 FROM gb_dataset WHERE name = 'des_decl' AND "
                            "status = 'current'")
        self.redeclare(declared_row(self.v1.uid))
        after = self.query("SELECT content_sha256 FROM gb_dataset WHERE name = 'des_decl' AND "
                           "status = 'current'")
        self.assertEqual(before, after)
        self.assertEqual(len(after), 1)
        self.assertEqual(self.record("des_decl", self.v1).locator, table)
        state, _pending = access.mask_state(self.project, self.v1.uid)
        self.assertIs(state, access.MaskState.CURRENT)
        self.assertEqual(self.operation_of(), self.first_op)  # y nadie la compiló de nuevo

    def test_b_changing_the_guard_makes_the_masks_obsolete_and_reports_the_change(self) -> None:
        """RF-012-06, RF-015-10: con otro resguardo la tabla cambia y las máscaras quedan obsoletas
        (la tabla es una entrada); al compilar de nuevo, la zona son las celdas de la huella (0 m) y el
        informe da lo perdido de la declarada, por su código: su polígono no cambió y la zona pierde las
        156 celdas del resguardo."""
        self.redeclare(declared_row(self.v1.uid, guard=0.0))
        state, _pending = access.mask_state(self.project, self.v1.uid)
        self.assertIs(state, access.MaskState.STALE)
        masks = self.compile_it()
        zone = masks.zone(CODE).mask(GRID.shape)
        self.assertTrue((zone == _box_cells(BOX)).all())  # RF-012-12: exactamente las celdas de la huella
        self.assertEqual(int(zone.sum()), FOOTPRINT_CELLS)
        report = self.report(self.operation_of(), CODE)
        lost = (ZONE_CELLS - FOOTPRINT_CELLS) * CELL_M2
        self.assertEqual((report["zone_lost"][0], report["zone_gained"][0]), (lost, 0.0))
        self.assertEqual((report["polygon_lost"][0], report["polygon_gained"][0]), (0.0, 0.0))
        self.assertEqual(report["buffer"][0], 0.0)
        base = self.baseline()
        self.assertTrue((masks.fill_allowed() == (base.fill_allowed.mask(GRID.shape)
                                                  & ~_box_cells(BOX))).all())

    def test_c_moving_the_contour_gives_gained_and_lost(self) -> None:
        """RF-012-06, RF-015-10: con otro contorno (la huella desplazada 20 m al oeste), la compilación da
        lo ganado y lo perdido del polígono y de la zona de la declarada por su código."""
        moved = (110.0, 140.0, 150.0, 170.0)
        self.redeclare(declared_row(self.v1.uid, box=moved, guard=0.0))
        masks = self.compile_it()
        report = self.report(self.operation_of(), CODE)
        shift = 10 * 15 * CELL_M2  # 10 columnas de 15 celdas
        self.assertEqual((report["polygon_gained"][0], report["polygon_lost"][0]), (shift, shift))
        self.assertEqual((report["zone_gained"][0], report["zone_lost"][0]), (shift, shift))
        self.assertTrue((masks.zone(CODE).mask(GRID.shape) == _box_cells(moved)).all())

    def test_d_removing_it_gives_back_the_masks_without_declared(self) -> None:
        """RF-012-06, RF-015-10: quitar la declarada (la tabla queda viva y vacía) deja obsoletas las
        máscaras, y compilar de nuevo da las de sin declaradas, con lo perdido de la declarada (su
        polígono y su zona enteros) en el informe de su código."""
        self.redeclare()
        state, _pending = access.mask_state(self.project, self.v1.uid)
        self.assertIs(state, access.MaskState.STALE)
        masks = self.compile_it()
        self.assertNotIn(CODE, masks.zones)
        base = self.baseline()
        self.assertTrue((masks.fill_allowed() == base.fill_allowed.mask(GRID.shape)).all())
        self.assertTrue((masks.cut_allowed() == base.cut_allowed.mask(GRID.shape)).all())
        uid = self.operation_of()
        self.assertIn(("des_decl", "constraints_declared"), self.inputs(uid))  # la tabla viva y vacía
        report = self.report(uid, CODE)
        whole = FOOTPRINT_CELLS * CELL_M2
        self.assertEqual((report["zone_lost"][0], report["zone_gained"][0]), (whole, 0.0))
        self.assertEqual((report["polygon_lost"][0], report["polygon_gained"][0]), (whole, 0.0))
        self.assertNotIn("zone_area", report)
        self.assertIsNone(self.figure(uid, "gis.zone_area_m2", CODE))


class DeclaredNewTest(cp.ConstraintsProjectCase):
    """V01 compilada **antes** de que ninguna entidad declarase nada, y una declarada que llega después."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.enterClassContext(efx.declared_registered())
        cls.clock.advance(minutes=1)
        cls.before = _last(access.ensure_masks_steps(cls.project, cls.v1.uid))
        efx.declare_rows(cls.project, cls.clock, [declared_row(cls.v1.uid, guard=0.0)],
                         version=cls.v1)
        cls.clock.advance(minutes=1)
        # Compilar a mano: que las máscaras queden obsoletas al llegar la primera declarada es el hueco H-1
        # (``DeclaredHoleTest``, T19); aquí se comprueba lo que da la compilación con ella.
        handle = masks_store.begin_compile(cls.project, version=cls.v1.uid)
        cls.stored = _last(masks_store.compile_run(cls.project, handle))
        cls.operation = str(handle.uid)

    def test_a_new_declared_gives_its_gain_against_the_previous_compilation(self) -> None:
        """RF-012-06, RF-015-10: compilar con una declarada que la compilación anterior no tenía da su
        polígono y su zona enteros como **ganados** (por su código) y las máscaras ya sin el relleno
        de su huella; lo demás no cambia."""
        locator = self.record(provenance.dataset_name(provenance.REPORT), self.v1).locator
        with self.project.read() as conn:
            rows = masks_store.read_report(conn, locator)
        report = {quantity: value for code, quantity, value, _unit, _note in rows if code == CODE}
        whole = FOOTPRINT_CELLS * CELL_M2
        self.assertEqual((report["zone_gained"], report["zone_lost"]), (whole, 0.0))
        self.assertEqual((report["polygon_gained"], report["polygon_lost"]), (whole, 0.0))
        masks = access.load_masks(self.project, self.v1.uid)
        self.assertTrue((masks.zone(CODE).mask(GRID.shape) == _box_cells(BOX)).all())
        was = self.before.fill_allowed()
        self.assertTrue((masks.fill_allowed() == (was & ~_box_cells(BOX))).all())
        self.assertTrue((masks.cut_allowed() == self.before.cut_allowed()).all())
        self.assertIn(CODE, self.stored.result.prepared.zones)


class DeclaredEmptyTest(cp.ConstraintsProjectCase):
    """V01 con la tabla de las declaradas viva y vacía (ninguna entidad protege)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.enterClassContext(efx.declared_registered())
        cls.operation = efx.declare_rows(cls.project, cls.clock, [], version=cls.v1)
        cls.clock.advance(minutes=1)
        cls.masks = _last(access.ensure_masks_steps(cls.project, cls.v1.uid))

    def test_compiling_with_an_empty_table_gives_the_masks_without_declared(self) -> None:
        """RF-012-16, RF-015-10: compilar con la tabla vacía da las máscaras de sin declaradas (las de
        ``gis.masks.combine`` sobre las del proyecto), con la tabla como entrada, sin ninguna zona
        declarada y sin ninguna declarada en las listas."""
        resolved = dict(cp.project_values())
        resolved[TOWER_KEY] = cp.TOWER_V01_M
        prepared = combine.prepare(self.stored_constraints(), resolved, GRID)
        base = combine.combine(prepared.zones, prepared.limits, GRID)
        self.assertTrue((self.masks.classes == base.classes).all())
        self.assertFalse([code for code in self.masks.zones if code.startswith("dec__")])
        self.assertTrue(set(prepared.zones) <= set(self.masks.zones))
        listed = masks_store.listed_constraints(self.project, version=self.v1.uid)
        self.assertEqual(len(listed), 5)
        self.assertFalse(any(item.declared for item in listed))
        self.assertIn("des_decl", masks_store.available_tables(self.project, self.v1.uid))


class DeclaredInactiveTest(_Compiled):
    """La declarada de V01 desactivada: la «activa» es una columna de la tabla."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.clock.advance(minutes=1)
        current = cls.declared_operation
        efx.declare_rows(cls.project, cls.clock, [declared_row(cls.v1.uid, active=False)],
                         version=cls.v1, supersedes=current)
        cls.clock.advance(minutes=1)
        cls.masks = _last(access.ensure_masks_steps(cls.project, cls.v1.uid))

    def test_an_inactive_declared_is_not_compiled(self) -> None:
        """RF-012-16, RF-012-02: una declarada con ``active`` falso (columna de la tabla, inyectada
        bajo la clave ``…active``) no tiene zona ni cambia el relleno admitido; en las listas sale
        «inactive» con su entidad."""
        base = self.baseline()
        self.assertNotIn(CODE, self.masks.zones)
        self.assertTrue((self.masks.fill_allowed() == base.fill_allowed.mask(GRID.shape)).all())
        (entry,) = [item for item in masks_store.listed_constraints(self.project,
                                                                     version=self.v1.uid)
                    if item.declared]
        self.assertEqual((entry.state, entry.entity_code), ("inactive", efx.DECLARED_ENTITY))
        self.assertEqual(self.keys(self.operation()).count(ACTIVE), 0)


class DeclaredOutsideGridTest(cp.ConstraintsProjectCase):
    """Una declarada pegada al borde este de la rejilla, con un resguardo que se sale de ella."""

    EDGE_BOX = (290.0, 100.0, 300.0, 110.0)
    """Su huella: 5 × 5 celdas contra el borde este (x = 300 local)."""
    EDGE_GUARD_M = 6.0

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.enterClassContext(efx.declared_registered())
        cls.row = declared_row(cls.v1.uid, box=cls.EDGE_BOX, guard=cls.EDGE_GUARD_M)
        efx.declare_rows(cls.project, cls.clock, [cls.row], version=cls.v1)
        cls.clock.advance(minutes=1)
        cls.masks = _last(access.ensure_masks_steps(cls.project, cls.v1.uid))

    def test_zone_outside_the_grid_is_reported(self) -> None:
        """RF-012-16, RF-012-15: la zona de la declarada que con su resguardo se sale de la rejilla se
        avisa con su código y el área fuera (tres columnas de 11 celdas: 132 m²), en la cifra
        ``gis.zone_outside_grid_m2`` y en el informe; la zona de dentro son las celdas de la rejilla."""
        uid = str(self.query(
            "SELECT o.uid FROM gb_operation AS o JOIN gb_revision AS r ON r.uid = o.revision_uid "
            "WHERE o.op_type = ? AND r.version_uid = ? ORDER BY o.rowid DESC LIMIT 1",
            provenance.COMPILE, self.v1.uid)[0][0])
        outside = 3 * 11 * CELL_M2
        figure = self.query("SELECT value FROM gb_figure WHERE operation_uid = ? AND key = ? AND "
                            "scope = ?", uid, "gis.zone_outside_grid_m2", f'{{"constraint":"{CODE}"}}')
        self.assertEqual([float(row[0]) for row in figure], [outside])
        locator = self.record(provenance.dataset_name(provenance.REPORT), self.v1).locator
        with self.project.read() as conn:
            rows = masks_store.read_report(conn, locator)
        notices = [note for code, quantity, _value, _unit, note in rows
                   if quantity == "notice" and code == CODE]
        self.assertEqual(len(notices), 1)  # en el informe de la restricción de su código
        self.assertIn("P1", notices[0])  # con el nombre de su entidad
        self.assertIn("132", notices[0])
        self.assertEqual([value for code, quantity, value, _unit, _note in rows
                          if quantity == "zone_outside_grid" and code == CODE], [outside])
        zone = self.masks.zone(CODE).mask(GRID.shape)
        self.assertEqual(int(zone.sum()), 8 * 11)  # las 11 columnas de la zona, menos las 3 de fuera
        self.assertTrue((zone == zone_cells(self.EDGE_BOX, self.EDGE_GUARD_M)).all())


class NoDeclaredTest(cp.ConstraintsProjectCase):
    """Un proyecto sin declaradas compila como antes."""

    def test_without_declared_the_inputs_are_those_of_the_012(self) -> None:
        """RF-012-16: sin tabla de declaradas viva, las entradas de la compilación son exactamente las de
        la 012 (las tres capas, los sectores y las búsquedas registrados), sus parámetros solo los de las
        restricciones del proyecto, ``OP_VERSION`` no sube y lo compilado queda al día."""
        self.assertEqual(provenance.OP_VERSION, "1.1")
        self.assertNotIn("des_decl", masks_store.available_tables(self.project, self.v1.uid))
        self.assertEqual(masks_store.available_tables(self.project, self.v1.uid),
                         masks_store.available_tables(self.project))
        self.clock.advance(minutes=1)
        _last(access.ensure_masks_steps(self.project, self.v1.uid))
        uid = self.query(
            "SELECT o.uid FROM gb_operation AS o JOIN gb_revision AS r ON r.uid = o.revision_uid "
            "WHERE o.op_type = ? AND r.version_uid = ? ORDER BY o.rowid DESC LIMIT 1",
            provenance.COMPILE, self.v1.uid)[0][0]
        roles = [role for (role,) in self.query(
            "SELECT role FROM gb_operation_io WHERE operation_uid = ? AND direction = 'in' "
            "ORDER BY fid", uid)]
        expected = [use.role for use in provenance.compile_inputs(
            masks_store.available_tables(self.project))]
        self.assertEqual(roles, expected)
        self.assertNotIn("constraints_declared", roles)
        self.assertEqual(roles[:3], ["constraints_polygon", "constraints_line", "constraints_point"])
        self.assertFalse([key for (key,) in self.query(
            "SELECT key FROM gb_operation_param WHERE operation_uid = ?", uid) if "dec__" in key])
        state, _pending = access.mask_state(self.project, self.v1.uid)
        self.assertIs(state, access.MaskState.CURRENT)
        self.assertEqual(len(masks_store.listed_constraints(self.project, version=self.v1.uid)), 5)


class DeclaredListingBlockedTest(efx.DeclaredConstraintsProjectCase):
    """Lo que **muestran** las listas, la barra N y la superposición de la declarada cuando su tabla se
    editó fuera de Geoblender (T21; RF-012-19, RF-015-11), por el orden de los nombres de las pruebas."""

    def _block(self, status: str) -> None:
        """Deja el dato de las declaradas de V01 en ``status`` (lo que hace la puerta de la 008 al ver la
        edición de QGIS)."""
        registry = import_geoblender("core.datasets.registry")
        with self.project.write_transaction() as conn:
            record = registry.get(conn, declared.DATASET_NAME, version_uid=self.v1.uid)
            registry.set_status(conn, self.project, record.uid, status)

    def _listings(self) -> tuple[Any, Any, Any]:
        listed = masks_store.listed_constraints(self.project, version=self.v1.uid)
        shown = polygons.drain(masks_store.shown_constraints_steps(self.project, version=self.v1.uid))
        one = masks_store.listed_constraint(self.project, declared_row(self.v1.uid).uid,
                                            version=self.v1.uid)
        return listed, shown, one

    def test_a_the_declared_carries_its_buffer_from_the_table(self) -> None:
        """RF-012-19, RF-012-02, P-8: la declarada lleva su resguardo hacia fuera, que es una columna de su
        tabla y da la entidad (no un parámetro del almacén); las del proyecto no llevan ninguno."""
        for found in self._listings()[:2]:
            self.assertEqual([item.buffer_out_m for item in found], [None] * 5 + [GUARD])
        self.assertEqual(self._listings()[2].buffer_out_m, GUARD)

    def test_b_a_blocked_table_lists_its_constraints_as_blocked(self) -> None:
        """RF-015-11, RF-012-19, RF-008-56: con el dato de las declaradas bloqueado por una edición fuera de
        Geoblender, su restricción está **bloqueada** en las tres listas (la de la ventana, la de la barra N y
        la de la superposición), con su entidad y su resguardo; las del proyecto no se bloquean y V02, que
        no la tiene, no la lista; «bloqueada» manda sobre «inactiva»."""
        self.assertIn("blocked", masks_store.STATES)
        self._block("blocked")
        for found in self._listings():
            entry = found[-1] if isinstance(found, tuple) else found
            self.assertEqual((entry.state, entry.entity_code, entry.entity_name, entry.buffer_out_m),
                             ("blocked", efx.DECLARED_ENTITY, "P1", GUARD))
        listed, shown, _one = self._listings()
        self.assertEqual([item.state for item in listed[:5]], ["active"] * 5)
        self.assertEqual([item.state for item in shown[:5]], ["active"] * 5)
        self.assertEqual(len(masks_store.listed_constraints(self.project, version=self.v2.uid)), 5)
        self._block("current")  # las pruebas siguientes parten de la tabla vigente

    def test_c_an_unreadable_table_is_not_shown_but_compiling_still_refuses_it(self) -> None:
        """RF-015-11 (T21): una fila de la tabla que ya no es una declarada (QGIS la dejó con un tipo que no
        existe) no tumba las listas ni los nombres: la declarada no se enseña y las del proyecto, como
        siempre; **compilar no la ignora**: el ``ValueError`` de la lectura sigue (con el dato bloqueado, la
        puerta lo corta antes con su mensaje: ``require_usable``)."""
        with self.project.write_transaction() as conn:
            conn.execute(f'UPDATE "{TABLE}" SET ctype = ?', ("no_existe",))
        listed, shown, one = self._listings()
        self.assertEqual(len(listed), 5)
        self.assertEqual(len(shown), 5)
        self.assertIsNone(one)
        self.assertFalse([item for item in listed if item.declared])
        with self.project.read() as conn:
            self.assertEqual(cstore.constraint_names(conn, version_uid=self.v1.uid),
                             cstore.constraint_names(conn))
        with self.assertRaises(ValueError):
            masks_store.gather(self.project, version=self.v1.uid)


# ---------------------------------------------------------------------------------------------
# El hueco H-1 (T19)
# ---------------------------------------------------------------------------------------------

CONSUMER = "des.test_consumer"
CAUSE_DATASET_CHANGED = "dataset_changed"



@contextmanager
def consumer_registered() -> Iterator[None]:
    """Un tipo de operación de ``des`` de prueba que consume las máscaras de su versión, como un diseño de la 013
    o de la 014 (``des.envelope``, ``des.quarry``…): lo que «las usó» y debe quedar obsoleto."""
    with registered(contract.OperationDef(CONSUMER, "1.0", "des", "Design that uses the masks (tests)",
                                          False, scope="version")):
        yield


class _HoleCase(cp.ConstraintsProjectCase):
    """Ayudas comunes de las pruebas del hueco: compilar por el contrato de los operadores, una operación que
    usó las máscaras, el estado de las de una versión y las causas de obsolescencia que deduce el grafo."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.enterClassContext(efx.declared_registered())
        cls.enterClassContext(consumer_registered())

    @classmethod
    def compile_version(cls, version: Any = None) -> Any:
        """Las máscaras de ``version`` (por defecto V01) por ``ensure_masks_steps``: compila si no están al día."""
        cls.clock.advance(minutes=1)
        return _last(access.ensure_masks_steps(cls.project, (version or cls.v1).uid))

    @classmethod
    def consume(cls, masks: Any, version: Any = None) -> str:
        """Una operación de prueba de ``des`` que usó ``masks`` (las de ``version``, por defecto V01); su uid."""
        cls.clock.advance(minutes=1)
        handle = operations.begin_operation(
            cls.project, CONSUMER, settings={"name": "Diseño de prueba"}, executor="blender",
            inputs=masks.uses(), version=(version or cls.v1).uid)
        with cls.project.write_transaction() as conn:
            handle.complete(conn, outputs=(), message="Diseño de prueba")
        return str(handle.uid)

    @classmethod
    def declare(cls, rows: Any, *, supersedes: str | None = None) -> str:
        """Escribe la tabla de las declaradas de V01 con ``rows`` (sustituye a la vigente si se da)."""
        return efx.declare_rows(cls.project, cls.clock, rows, version=cls.v1, supersedes=supersedes)

    def state(self, version: Any = None) -> Any:
        return access.mask_state(self.project, (version or self.v1).uid)[0]

    def cause(self, version: Any = None) -> Any:
        return access.mask_cause(self.project, (version or self.v1).uid)

    def graph_causes(self, uid: str) -> set[str]:
        """Las causas de obsolescencia que el **grafo** de la 008 da a la operación ``uid``."""
        return {str(kind) for (kind,) in self.query(
            "SELECT cause_kind FROM gb_stale WHERE item_kind = 'operation' AND item_uid = ?", uid)}

    @classmethod
    def compile_op(cls, version: Any = None) -> str:
        """El uid de la compilación vigente de ``version`` (por defecto V01)."""
        with cls.project.read() as conn:
            return str(conn.execute(
                "SELECT o.uid FROM gb_operation AS o JOIN gb_revision AS r ON r.uid = o.revision_uid "
                "WHERE o.op_type = ? AND r.version_uid = ? AND o.superseded_by IS NULL "
                "ORDER BY o.rowid DESC LIMIT 1", (provenance.COMPILE, (version or cls.v1).uid)).fetchone()[0])

    def inputs(self, uid: str) -> list[str]:
        """Los nombres de lo que consumió la operación ``uid``."""
        return [str(name) for (name,) in self.query(
            "SELECT d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'in' ORDER BY io.fid", uid)]


class DeclaredHoleTest(_HoleCase):
    """RF-012-06, RF-012-29, RF-015-10 (el error 51): V01 compilada **sin** declaradas, usada por un diseño de
    prueba, y una declarada que llega **después**, en el orden de las pruebas: (a) lo compilado, (b) la
    declarada que llega, (c) quien pide las máscaras las recompila."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.masks_before = cls.compile_version()
        cls.consumer = cls.consume(cls.masks_before)
        cls.compile_before = cls.compile_op()

    def test_a_compiled_without_declared_is_current(self) -> None:
        """RF-012-17: antes de que llegue ninguna declarada, las máscaras de V01 están al día, sin causa de
        obsolescencia, y se entregan."""
        self.assertIs(self.state(), access.MaskState.CURRENT)
        self.assertIsNone(self.cause())
        self.assertNotIn(CODE, access.load_masks(self.project, self.v1.uid).zones)
        self.assertEqual(self.graph_causes(self.consumer), set())

    def test_b_a_declared_that_arrives_after_compiling_makes_the_masks_stale_with_its_cause(self) -> None:
        """RF-012-06, RF-012-29, RF-015-10 (H-1): una declarada que llega **después** de compilar deja las
        máscaras de V01 **obsoletas** con su causa (``MaskCause.DECLARED_NEW``) aunque el grafo de la 008 no lo sepa
        (un dato nuevo no deja obsoleto lo que ya se calculó: ni la compilación ni lo que las usó tienen causa
        todavía); ``load_masks`` se niega nombrándola, en los dos idiomas, y dice qué hacer."""
        self.declare([declared_row(self.v1.uid)])
        self.assertEqual(self.graph_causes(self.compile_op()), set(), "el grafo no lo sabe: el hueco")
        self.assertEqual(self.graph_causes(self.consumer), set())
        self.assertIs(self.state(), access.MaskState.STALE)
        self.assertIs(self.cause(), access.MaskCause.DECLARED_NEW)
        with self.assertRaises(access.MaskError) as caught:
            access.load_masks(self.project, self.v1.uid)
        error = caught.exception
        self.assertEqual(error.code, "core.constraint_masks_declared_new")
        self.assertIn("V01", error.message)
        self.assertIn("declarada", error.message)
        self.assertIn("compílelas de nuevo", error.message)
        self.assertIn("(geoblender.gis_compile_constraints)", error.message)
        english = cmessages.render("core.constraint_masks_declared_new", language="en",
                                   version="V01", command=provenance.COMMAND)
        self.assertIn("declared", english)
        self.assertNotEqual(english, error.message)
        with self.assertRaises(access.MaskError) as asked:  # quien las pide por el contrato (ADR-0028 §4)
            access.require_current(self.project, self.v1.uid)
        self.assertEqual(asked.exception.code, "core.constraint_masks_declared_new")

    def test_c_asking_for_the_masks_compiles_them_with_the_declared_and_makes_their_users_stale(self) -> None:
        """RF-012-06, RF-012-17, RF-015-10: ``ensure_masks_steps`` (lo que piden los operadores) las recompila
        con la declarada, que ahora es una entrada: las máscaras vuelven a estar al día, con la zona y sin el
        relleno de la huella, y lo que usó las anteriores queda obsoleto con su causa (otro contenido de un dato
        que consumió); la compilación leyó la tabla y, al día, ya no tiene causa."""
        before = self.compile_op()
        masks = self.compile_version()
        self.assertIs(self.state(), access.MaskState.CURRENT)
        self.assertIsNone(self.cause())
        self.assertNotEqual(self.compile_op(), before)
        self.assertIn("des_decl", self.inputs(self.compile_op()))
        self.assertTrue((masks.zone(CODE).mask(GRID.shape) == zone_cells(BOX, GUARD)).all())
        self.assertFalse(masks.fill_allowed()[zone_cells(BOX, GUARD)].any())
        self.assertEqual(self.graph_causes(self.consumer), {CAUSE_DATASET_CHANGED})
        compiled = self.compile_op()
        again = _last(access.ensure_masks_steps(self.project, self.v1.uid))  # al día: nada que compilar
        self.assertEqual(self.compile_op(), compiled)
        self.assertEqual(again.operation_uid, masks.operation_uid)


class BeforeThe015Test(_HoleCase):
    """RF-012-16, RF-012-29, RF-015-10: lo compilado **antes de la 015** (sin ninguna tabla de declaradas) sigue
    válido hasta que aparece una viva; una compilación que la consumió, aunque esté vacía, está al día mientras
    su hash no cambie. En el orden de las pruebas."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.compile_version()
        cls.first_compile = cls.compile_op()

    def test_a_compiled_before_the_015_is_valid_without_a_live_declared_table(self) -> None:
        """RF-012-16: sin tabla de declaradas viva (ninguna operación de ``des`` la escribió) la compilación de
        la 012, con las entradas de siempre y ``OP_VERSION`` «1.1», está al día y se entrega."""
        self.assertEqual(provenance.OP_VERSION, "1.1")
        self.assertNotIn("des_decl", masks_store.available_tables(self.project, self.v1.uid))
        self.assertNotIn("des_decl", self.inputs(self.first_compile))
        self.assertIs(self.state(), access.MaskState.CURRENT)
        self.assertIsNone(self.cause())
        access.load_masks(self.project, self.v1.uid)

    def test_b_an_empty_declared_table_that_appears_makes_them_stale(self) -> None:
        """RF-012-29, RF-015-10: la tabla de las declaradas aparece (aunque **vacía**: ninguna entidad protege
        todavía): la compilación no la consumió, así que las máscaras están obsoletas con su causa; la compilación
        de antes no cambia (sigue siendo la vigente hasta recompilar)."""
        type(self).first_declaration = self.declare([])
        self.assertIs(self.state(), access.MaskState.STALE)
        self.assertIs(self.cause(), access.MaskCause.DECLARED_NEW)
        self.assertEqual(self.compile_op(), self.first_compile)

    def test_c_compiling_again_consumes_the_empty_table_and_leaves_them_current(self) -> None:
        """RF-012-16, RF-015-10: recompiladas, consumen la tabla vacía (entrada ``constraints_declared``) y
        están al día; son las máscaras de sin declaradas (ninguna zona declarada)."""
        masks = self.compile_version()
        self.assertIs(self.state(), access.MaskState.CURRENT)
        self.assertIn("des_decl", self.inputs(self.compile_op()))
        self.assertFalse([code for code in masks.zones if code.startswith("dec__")])

    def test_d_the_same_empty_table_written_again_does_not_make_them_stale(self) -> None:
        """RF-012-06, RF-015-10: repetir la declaración con las mismas filas (la vacía) deja el mismo hash: las
        máscaras, que la consumieron, siguen al día, sin recompilar."""
        before = self.compile_op()
        self.declare([], supersedes=self.first_declaration)
        self.assertIs(self.state(), access.MaskState.CURRENT)
        self.assertIsNone(self.cause())
        self.assertEqual(self.compile_op(), before)

    def test_e_a_row_that_changes_the_table_is_a_cause_of_the_graph_not_a_new_one(self) -> None:
        """RF-012-06: una fila que cambia la tabla que la compilación **sí** consumió la deja obsoleta por el
        grafo de la 008 (otro contenido de un dato que consumió), no por el hueco: ``mask_cause`` no da
        ``MaskCause.DECLARED_NEW`` y la compilación tiene su causa en ``gb_stale``."""
        self.declare([declared_row(self.v1.uid)], supersedes=self.query(
            "SELECT o.uid FROM gb_operation AS o JOIN gb_revision AS r ON r.uid = o.revision_uid "
            "WHERE o.op_type = 'des.declare_constraints' AND r.version_uid = ? AND o.superseded_by IS NULL",
            self.v1.uid)[0][0])
        self.assertIs(self.state(), access.MaskState.STALE)
        self.assertIsNone(self.cause())
        self.assertEqual(self.graph_causes(self.compile_op()), {CAUSE_DATASET_CHANGED})


class DeclaredOtherVersionTest(_HoleCase):
    """RF-012-29: la declarada de V01 es de V01. V01 y V02 compiladas, y una declarada que llega a V01."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.masks_1 = cls.compile_version(cls.v1)
        cls.masks_2 = cls.compile_version(cls.v2)
        cls.compile_2 = cls.compile_op(cls.v2)
        cls.declare([declared_row(cls.v1.uid)])

    def test_a_the_declared_of_v01_makes_only_the_masks_of_v01_stale(self) -> None:
        """RF-012-29, RF-015-10: V01 tiene una declarada nueva (obsoletas, con su causa); V02, que no la ve,
        sigue al día y se entrega: el hueco se mide **por versión**."""
        self.assertIs(self.state(self.v1), access.MaskState.STALE)
        self.assertIs(self.cause(self.v1), access.MaskCause.DECLARED_NEW)
        self.assertIs(self.state(self.v2), access.MaskState.CURRENT)
        self.assertIsNone(self.cause(self.v2))
        access.load_masks(self.project, self.v2.uid)
        with self.project.read() as conn:
            self.assertNotIn("des_decl", masks_store._available(conn, self.v2.uid))
            self.assertIn("des_decl", masks_store._available(conn, self.v1.uid))

    def test_b_v01_compiles_with_it_and_v02_neither_sees_it_nor_consumes_it(self) -> None:
        """RF-012-29, RF-012-16: V01 se recompila con la declarada; la compilación de V02 es la misma (no se
        recompila: ni la ve ni la consume), sin su zona y con las mismas máscaras bit a bit."""
        masks = self.compile_version(self.v1)
        self.assertIn(CODE, masks.zones)
        self.assertEqual(self.compile_op(self.v2), self.compile_2)
        self.assertNotIn("des_decl", self.inputs(self.compile_2))
        again = access.load_masks(self.project, self.v2.uid)
        self.assertNotIn(CODE, again.zones)
        self.assertTrue((again.classes == self.masks_2.classes).all())
        self.assertIs(self.state(self.v2), access.MaskState.CURRENT)


class OnlyThroughDeclaredTest(_HoleCase):
    """RF-012-17 (la excepción que Samuel aprobó el 15/11/2026, spec 012 0.4), RF-015-10, D-21; hallazgo B-3 de la
    verificación única (T38): ``access._only_through_declared`` entrega unas máscaras que el grafo da por obsoletas
    **solo si** la obsolescencia llega por la declaración (el ciclo entidad → declarada → máscaras → entidad) y la
    compilación **no tiene ninguna causa directa**. Las pruebas de antes solo mataban la mutación de los datos
    directos; aquí, **una por cada rama** (un dato, un parámetro, la fila propia de la versión de un parámetro, la
    versión del algoritmo).

    V01: una declarada viva y **consumida** por la compilación y una operación de declaración que leyó un parámetro
    que la compilación **no** lee (el resguardo de la declarada, ``OUTWARD``), de modo que cambiarlo deja obsoleta
    la declaración y, **por herencia**, la compilación, sin ninguna causa directa en ella: las máscaras se entregan
    (el caso base). Cada causa directa que se añade, por orden de las pruebas, las deja ``STALE`` y ``load_masks``
    se niega; recompiladas, vuelven a entregarse (la herencia sigue)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.compile_version()
        row = declared_row(cls.v1.uid)
        table = design_provenance.dataset_locator(design_provenance.DECLARED_TABLE, "", cls.v1.code)
        srs = cls.project.record.crs_epsg
        cls.clock.advance(minutes=1)
        handle = operations.begin_operation(  # la declaración lee un parámetro que la compilación no lee
            cls.project, design_provenance.DECLARE_CONSTRAINTS, executor="blender", version=cls.v1.uid,
            params=(OUTWARD,), settings=design_provenance.declare_settings([(row.entity_code, row.entity_name)]))
        with cls.project.write_transaction() as conn:
            declared.write_declared(conn, table, [row], srs_id=srs)
            handle.complete(conn, outputs=(design_provenance.dataset_spec(
                design_provenance.DECLARED_TABLE, "", cls.v1.code, crs_epsg=srs),),
                figures=design_provenance.declare_figures(1), message="Declarada de prueba")
        cls.masks = cls.compile_version()  # consume la tabla
        cls.clock.advance(minutes=1)
        with cls.project.write_transaction() as conn:  # y ahora cambia lo que leyó la declaración, no la compilación
            core_params.ParameterStore(cls.project).change(
                conn, OUTWARD, value=GUARD + 3.0, reason="Prueba de la excepción de RF-012-17", **cp.PARAMS_BY_HAND)

    def stale_and_refused(self) -> None:
        """El estado de las máscaras es ``STALE`` (sin la causa del hueco H-1: la da el grafo) y quien las pide se
        niega."""
        self.assertIs(self.state(), access.MaskState.STALE)
        self.assertIsNone(self.cause())
        with self.assertRaises(access.MaskError) as refused:
            access.load_masks(self.project, self.v1.uid)
        self.assertEqual(refused.exception.code, "core.constraint_masks_stale")

    def base_again(self) -> None:
        """Recompila (lo que hace quien las pide) y vuelve al caso base: al día **aunque el grafo las dé por
        obsoletas por herencia**."""
        self.compile_version()
        access.load_masks(self.project, self.v1.uid)  # al día: se entregan
        self.assertIs(self.state(), access.MaskState.CURRENT)
        self.assertTrue(self.graph_causes(self.compile_op()), "la herencia sigue: es lo que la excepción cubre")

    def test_a_the_base_case_only_inherited_staleness_is_delivered(self) -> None:
        """RF-012-17 (excepción), D-21: la compilación consumió la tabla viva, la declaración que la escribió está
        obsoleta (cambió el parámetro que leyó) y **por herencia** la compilación también: el grafo la da por
        obsoleta con una causa que **no es suya** (``parameter_changed`` de otro) y, sin ninguna causa directa, las
        máscaras se entregan."""
        self.assertEqual(self.graph_causes(self.compile_op()), {"parameter_changed"})
        self.assertIn("des_decl", self.inputs(self.compile_op()))
        self.assertIs(self.state(), access.MaskState.CURRENT)
        self.assertIsNone(self.cause())
        self.assertIn(CODE, access.load_masks(self.project, self.v1.uid).zones)

    def test_b_a_changed_data_it_consumed_is_a_direct_cause(self) -> None:
        """RF-012-17, D-21 (rama de los datos): una capa de restricciones del proyecto editada (el perímetro
        redibujado, como en ``test_compile``) cambia un dato que la compilación consumió: obsoletas."""
        (perimeter,) = [item for item in self.stored_constraints() if item.code == "perimetro"]
        redrawn = cp.constraints(perimeter=fx.REDRAWN_PERIMETER_LOCAL)[1]
        self.clock.advance(minutes=1)
        cp.edit_constraints(self.project, [type(redrawn)(**{
            **{name: getattr(redrawn, name) for name in redrawn.__dataclass_fields__},
            "uid": perimeter.uid, "fid": perimeter.fid})])
        self.stale_and_refused()
        self.base_again()

    def test_c_a_new_search_sector_is_a_direct_cause(self) -> None:
        """RF-012-17, D-21 (rama de los datos): un sector de búsqueda nuevo (``core_sector`` es entrada de la
        compilación) cambia lo que consumió: obsoletas."""
        self.clock.advance(minutes=1)
        cp.edit_constraints(self.project, [], sector_rows=[cmodel.Sector(
            "sector3" + "0" * 25, "sector_3", "Sector 3", (fx.rectangle(10.0, 10.0, 40.0, 40.0),))])
        self.stale_and_refused()
        self.base_again()

    def test_d_a_parameter_of_the_version_it_read_is_a_direct_cause(self) -> None:
        """RF-012-17, D-21 (rama de los parámetros): el resguardo de la torre, que la compilación leyó (propio de
        V01), cambia de valor: obsoletas."""
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            core_params.ParameterStore(self.project).change(
                conn, TOWER_KEY, value=cp.TOWER_V01_M + 2.0, reason="Prueba de la excepción de RF-012-17",
                version=self.v1.code)
        self.stale_and_refused()
        self.base_again()

    def test_e_an_own_row_of_the_version_for_a_parameter_it_read_from_the_project_is_a_direct_cause(self) -> None:
        """RF-012-17, D-21 (rama de la fila propia de la versión; A4 (4) de la 008): la cuneta, cuyo resguardo la
        compilación leyó **del proyecto**, gana una fila propia en V01: obsoletas, aunque el valor sea el mismo."""
        key = cparams.buffer_out_key("cuneta")
        before = self.query("SELECT value FROM gb_parameter WHERE key = ? AND scope = 'project'", key)
        self.assertEqual(self.query("SELECT count(*) FROM gb_parameter WHERE key = ? AND scope = 'version'", key),
                         [(0,)])
        cp.declare(self.project, self.clock, {key: cp.DITCH_OUTWARD_M}, version=self.v1)
        self.assertEqual(self.query("SELECT value FROM gb_parameter WHERE key = ? AND scope = 'project'", key),
                         before, "el valor del proyecto no cambia")
        self.stale_and_refused()
        self.base_again()

    def test_f_a_newer_version_of_the_algorithm_is_a_direct_cause(self) -> None:
        """RF-012-17, RF-008-24, D-21 (rama de la versión del algoritmo): con una versión de la compilación mayor
        que la que las compiló, obsoletas; recompiladas con ella, al día."""
        older = contract.OPERATIONS[provenance.COMPILE]
        newer = dataclasses.replace(older, version="9.9")
        contract.unregister_operation(provenance.COMPILE)
        contract.register_operation(newer)

        def restore() -> None:
            contract.unregister_operation(provenance.COMPILE)
            contract.register_operation(older)

        self.addCleanup(restore)
        self.stale_and_refused()
        self.base_again()


class DeclaredReproduceTest(cp.ConstraintsProjectCase):
    """RF-012-16, RF-012-29, RF-015-10, RF-009-11: V01 con una declarada, compilada con ella, congelada en V01.r1
    y reproducida desde lo congelado (la operación de prueba que escribió la tabla no se reproduce, sin
    entidades: es de ``des``, no de lo que se prueba aquí)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.enterClassContext(efx.declared_registered(reproducible=False))
        efx.declare_rows(cls.project, cls.clock, [declared_row(cls.v1.uid)], version=cls.v1)
        cls.clock.advance(minutes=1)
        cls.masks = _last(access.ensure_masks_steps(cls.project, cls.v1.uid))
        cls.compile_uid = str(cls.masks.operation_uid)
        cls.clock.advance(minutes=1)
        outcome = _last(freeze.freeze_steps(cls.project, cls.v1.uid, reason="Entrega de la prueba"))
        cls.r1 = str(outcome.frozen.uid)

    def reproduce(self) -> Any:
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        report = _last(reproduce.reproduce_steps(self.project, self.r1))
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root)),
                         before, "reproducir no escribe nada en el proyecto")
        return report

    def test_a_reproducing_v01_r1_gives_the_same_masks_with_the_declared(self) -> None:
        """RF-012-16, RF-012-29, RF-015-10: la compilación congelada **consumió** la tabla de las declaradas
        (papel ``constraints_declared``); reproducirla da las cinco salidas con el mismo hash que registró (la
        rejilla de clases, las zonas con la de la declarada, el informe, las partes y las formas) y las
        mismas cifras bit a bit, sin escribir nada en el proyecto."""
        self.assertIn(("des_decl", "constraints_declared"), [(str(name), str(role)) for name, role in self.query(
            "SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'in'", self.compile_uid)])
        self.assertIn(CODE, self.masks.zones)
        report = self.reproduce()
        mine = [check for check in report.outputs if check.op_type == provenance.COMPILE]
        self.assertEqual(sorted(check.role for check in mine),
                         sorted(family.role for family in provenance.FAMILIES))
        self.assertTrue(all(check.same for check in mine), [check for check in mine if not check.same])
        frozen = {(key, figures_mod.scope_json(json.loads(scope))): value for key, scope, value in self.query(
            "SELECT key, scope, value FROM gb_figure WHERE operation_uid = ?", self.compile_uid)}
        reproduced = {(check.key, figures_mod.scope_json(check.scope)): check.reproduced
                      for check in report.figures if check.operation_uid == self.compile_uid}
        self.assertEqual(reproduced, frozen)
        self.assertIn(("gis.zone_area_m2", figures_mod.scope_json({"constraint": CODE})), reproduced)
        self.assertEqual(report.not_reproducible, ())
        self.assertEqual(sorted(note.op_type for note in report.taken_frozen),
                         ["core.test_constraints", "des.declare_constraints"])  # lo que no se reproduce, congelado

    def test_b_changing_what_is_live_after_freezing_does_not_change_the_frozen_masks(self) -> None:
        """RF-009-19, RF-012-29: congelada V01.r1, una declarada de otro resguardo (y las máscaras recompiladas
        con ella) cambia lo vivo; reproducir V01.r1 da lo mismo que antes (la declarada congelada, no la de
        hoy) y V01 sigue al día."""
        current = str(self.query(
            "SELECT o.uid FROM gb_operation AS o JOIN gb_revision AS r ON r.uid = o.revision_uid "
            "WHERE o.op_type = 'des.declare_constraints' AND r.version_uid = ? AND o.superseded_by IS NULL",
            self.v1.uid)[0][0])
        efx.declare_rows(self.project, self.clock, [declared_row(self.v1.uid, guard=0.0)], version=self.v1,
                         supersedes=current)
        self.clock.advance(minutes=1)
        live = _last(access.ensure_masks_steps(self.project, self.v1.uid))
        self.assertEqual(int(live.zone(CODE).mask(GRID.shape).sum()), FOOTPRINT_CELLS)
        self.assertEqual(int(self.masks.zone(CODE).mask(GRID.shape).sum()), ZONE_CELLS)
        report = self.reproduce()
        mine = [check for check in report.outputs if check.op_type == provenance.COMPILE
                and check.operation_uid == self.compile_uid]
        self.assertEqual(len(mine), len(provenance.FAMILIES))
        self.assertTrue(all(check.same for check in mine))


if __name__ == "__main__":
    unittest.main()

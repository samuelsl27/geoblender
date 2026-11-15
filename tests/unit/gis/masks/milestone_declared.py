# SPDX-License-Identifier: GPL-3.0-or-later
"""Pruebas de hito de «test_declared» (spec 015, T48; plan 015 §7.4): las clases que pesan,
movidas sin cambiar una aserción. El «verde» deja en ``test_declared`` las más ligeras de cada
requisito; las de aquí las ejecuta el paso «hito» de ``tools/check.py --completo`` (la publicación
lo pide siempre).
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from tests.support import constraints_fixtures as fx
from tests.support import constraints_project as cp
from tests.support import entity_fixtures as efx
from tests.support.versions_fixtures import change_counter, files
from tests.unit.gis.masks.test_declared import (
    BOX,
    CAUSE_DATASET_CHANGED,
    CELL_M2,
    CODE,
    FOOTPRINT_CELLS,
    GRID,
    GUARD,
    OUTWARD,
    TOWER_KEY,
    ZONE_CELLS,
    _Compiled,
    _HoleCase,
    _box_cells,
    _last,
    access,
    cmodel,
    contract,
    core_params,
    cparams,
    declared,
    declared_row,
    design_provenance,
    figures_mod,
    freeze,
    masks_store,
    operations,
    provenance,
    reproduce,
)


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

# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que sigue a cada orden de entidades: declarar y recompilar las máscaras (spec 015, T19; HU-015-1;
RF-015-10, RF-015-16, RF-012-06, RF-012-29; plan 015 §5.3.2, §5.7 P-7 y §5.8 H-1; ADR-0030 §3 y §5; D-21;
CE-015-04).

``design.entity_store.after_entity_change(project, version)`` es lo que encadena la orden de una entidad tras
su commit (y, con la misma función, descartarla o retirarla: T25 y T26): **(a)** repite la declaración de las
restricciones de las entidades vivas y **(b)** si las máscaras ya no están al día las compila de nuevo y dice
qué quedó obsoleto, con lo ganado y perdido por restricción. Cada etapa es una operación y una transacción
propias (P-7). Sobre la cantera sintética de la 014 con las capas de plataformas (``tests.support.
entity_fixtures``), rejilla gruesa de 2 m, V01 con P1 (la «Plataforma de carga», que no protege) y P2 (la
«Plataforma de taller», de la superficie de P1, que protege 4 m), **con las funciones reales de recálculo** de
la plataforma, de la declaración y de la compilación de las máscaras (lo que registrará ``bl``):

- **La cadena** (:class:`ChainTest`, en el orden de las pruebas): (a) la primera vez declara una tabla vacía
  y compila las máscaras una vez (el hueco H-1: la compilación vigente no la había consumido), sin dejar nada
  obsoleto (las máscaras salen iguales); (b) repetirla sin cambios no recompila ni cambia nada; (c) crear P2
  protegiendo da su restricción, las máscaras con su zona (la huella ampliada 4 m, calculada aquí con otra
  fórmula) y el informe de lo ganado y perdido en m², y deja obsoletas las operaciones que usaron las
  anteriores, con su causa, **también la de P2** (el ciclo entidad → declarada → máscaras → entidad, D-21);
  (d) «Recalcular lo obsoleto» resuelve el ciclo: P1 y P2 se rehacen con las máscaras nuevas, su salida no
  cambia (RF-008-26) y no queda nada obsoleto; (e) cambiar el resguardo y (f) retirar la protección vuelven
  a declarar y recompilar, con lo perdido.
- **Los fallos** (:class:`FailureTest`): si falla la compilación de las máscaras, la entidad queda creada, la
  declaración hecha y las máscaras **obsoletas con su causa**, que se recompilan al pedirlas; si falla la
  declaración, no se escribe nada y se cuenta.
- **Esc y los pasos** (:class:`StepsTest`): el progreso es un porcentaje que no retrocede entre etapas; cerrar
  a mitad de una etapa no la deja a medias; sin versión editable no se hace nada (RF-009-21).
"""

from __future__ import annotations

import json
from typing import Any, ClassVar
from unittest import mock

import numpy as np

from tests.support.package import import_geoblender
from tests.support.versions_fixtures import freeze_rows
from tests.unit.design import test_declare_operation as decl
from tests.unit.design import test_platform_operation as ops
from tests.unit.design import test_platform_prepare as prep

access = import_geoblender("gis.masks.access")
compile_mod = import_geoblender("gis.masks.compile")
contract = import_geoblender("core.provenance.contract")
declared_mod = import_geoblender("core.constraints.declared")
design_messages = import_geoblender("design.messages")
entity_store = import_geoblender("design.entity_store")
masks_provenance = import_geoblender("gis.masks.provenance")
masks_store = import_geoblender("gis.masks.store")
preview = import_geoblender("design.preview")
provenance = import_geoblender("design.provenance")
recompute_mod = import_geoblender("core.provenance.recompute")
versions_model = import_geoblender("core.versions.model")

LOADING, WORKSHOP = prep.LOADING, prep.WORKSHOP
GUARD_M = 4.0
CELL_M2 = ops.CELL_M2
DECLARE, PLATFORM, COMPILE = provenance.DECLARE_CONSTRAINTS, provenance.PLATFORM, masks_provenance.COMPILE
CODE = declared_mod.declared_code("PLT-002")
EDITOR = decl.EDITOR
CAUSE_DATASET = "dataset_changed"


def dilate(mask: np.ndarray, cells: int) -> np.ndarray:
    """``mask`` ensanchada ``cells`` celdas por cada lado (un cuadrado de ``2·cells + 1``): la zona de una
    huella con un resguardo de ``cells`` celdas **menos un poco**, por la regla de la celda de la 012 (con 2 m de
    celda y 4 m de resguardo, dos celdas: la de tres queda a 4 m, que no es «menos de 4 m»)."""
    found = mask.copy()
    rows, cols = mask.shape
    for dy in range(-cells, cells + 1):
        for dx in range(-cells, cells + 1):
            shifted = np.zeros_like(mask)
            shifted[max(dy, 0):rows + min(dy, 0), max(dx, 0):cols + min(dx, 0)] = mask[
                max(-dy, 0):rows + min(-dy, 0), max(-dx, 0):cols + min(-dx, 0)]
            found |= shifted
    return found


class ChainCase(decl.DeclareCase):
    """``DeclareCase`` (con la compilación real registrada), las máscaras **al día** para calcular (las que dejó
    la anterior orden, no las de la clase) y los ayudantes de estas pruebas."""

    @classmethod
    def made(cls, asked: Any) -> Any:
        """«Calcula» (con las máscaras que den ``ensure_masks_steps``: compila si hace falta) y «crea» ``asked``."""
        cls.clock.advance(minutes=1)
        return cls.calculate_in(asked, masks=None).create()

    @classmethod
    def chain(cls, version: Any = None) -> Any:
        """Lo que sigue a la orden de una entidad, hasta el final: el ``EntityChain``."""
        cls.clock.advance(minutes=1)
        return ops.finish(entity_store.after_entity_change(cls.project, version or cls.v1))

    def compile_op(self) -> str:
        return str(self.query(
            "SELECT o.uid FROM gb_operation AS o JOIN gb_revision AS r ON r.uid = o.revision_uid "
            "WHERE o.op_type = ? AND r.version_uid = ? AND o.status = 'done' AND o.superseded_by IS NULL ORDER BY o.fid DESC "
            "LIMIT 1", COMPILE, self.v1.uid)[0][0])

    def inputs(self, uid: str) -> list[str]:
        return [str(name) for (name,) in self.query(
            "SELECT d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'in' ORDER BY io.fid", uid)]

    def state(self) -> Any:
        return access.mask_state(self.project, self.v1.uid)[0]

    def footprint(self, code: str) -> np.ndarray:
        """La huella de la entidad ``code`` en la rejilla entera, de su tabla ``des_epr_``."""
        return entity_store.runs_mask(self.entity_runs(code), self.grid.shape)

    def zone_area(self, code: str, guard_cells: int) -> tuple[float, float]:
        """El área (m²) de la huella de ``code`` y de su zona con ``guard_cells`` celdas de resguardo."""
        footprint = self.footprint(code)
        return float(footprint.sum()) * CELL_M2, float(dilate(footprint, guard_cells).sum()) * CELL_M2


# ---------------------------------------------------------------------------------------------
# La cadena
# ---------------------------------------------------------------------------------------------


class ChainTest(ChainCase):
    """RF-015-10, RF-015-16, RF-012-06, H-1, D-21: P1 creada sin declaradas y, en el orden de las pruebas,
    (a) la primera cadena, (b) la repetición, (c) P2 que protege, (d) «Recalcular lo obsoleto», (e) otro
    resguardo y (f) retirar la protección."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.first = cls.made(prep.request())
        cls.compile_before = str(cls.query_of(
            "SELECT o.uid FROM gb_operation AS o WHERE o.op_type = ? AND o.superseded_by IS NULL",
            COMPILE)[0][0])

    # --- (a) La primera vez ------------------------------------------------------------------------

    def test_a_the_first_chain_declares_an_empty_table_and_compiles_the_masks_once(self) -> None:
        """RF-015-10, H-1: sin ninguna entidad que proteja, la primera cadena declara una tabla **vacía** (la
        versión ya tiene su ``des_decl_v01``) y, como la compilación vigente no la había consumido, **compila
        las máscaras de nuevo** una vez: con la tabla como entrada y, como no hay ninguna declarada, **iguales**
        (ni lo ganado ni lo perdido) y sin dejar nada obsoleto: P1, que las usó, sigue al día."""
        self.assertIs(self.state(), access.MaskState.CURRENT)  # las de la 012, sin tabla
        chain = self.chain()
        self.assertIsInstance(chain, entity_store.EntityChain)
        self.assertEqual((chain.version, chain.declared, chain.declaration_changed, chain.masks_compiled),
                         ("V01", 0, True, True))
        self.assertIsNone(chain.failure)
        self.assertEqual((chain.changes, chain.obsolete), ((), ()))
        self.assertIs(chain.masks_state, access.MaskState.CURRENT)
        self.assertEqual([notice.code for notice in chain.notices()],
                         ["des.entity_chain_declared", "des.entity_chain_masks"])
        self.assertNotEqual(self.compile_op(), self.compile_before)
        self.assertIn("des_decl", self.inputs(self.compile_op()))
        self.assertIs(self.state(), access.MaskState.CURRENT)
        self.assertEqual(self.recompute_plan(), [], "unas máscaras iguales no dejan nada obsoleto")
        self.assertEqual(self.stale_causes(self.current("PLT-001")), set())

    def test_b_repeating_it_without_changes_compiles_nothing_and_changes_nothing(self) -> None:
        """RF-015-10, A8, RF-012-06: repetir la cadena sin cambiar nada vuelve a declarar (sustituye a la
        declaración vigente, el mismo contenido y el mismo hash) pero **no recompila**: la compilación vigente es
        la misma, las máscaras siguen al día y no se dice nada de ellas."""
        before, digest = self.compile_op(), self.record_of().content_sha256
        chain = self.chain()
        self.assertEqual((chain.declared, chain.declaration_changed, chain.masks_compiled),
                         (0, False, False))
        self.assertEqual((chain.changes, chain.obsolete, chain.failure), ((), (), None))
        self.assertEqual(chain.notices(), ())
        self.assertEqual(self.compile_op(), before)
        self.assertEqual(self.record_of().content_sha256, digest)
        self.assertIs(self.state(), access.MaskState.CURRENT)

    # --- (c) Una plataforma que protege ------------------------------------------------------------

    def test_c_a_platform_that_protects_gets_its_zone_in_the_masks_and_the_report(self) -> None:
        """RF-015-10, RF-012-06, RF-015-16, D-21: P2 (que protege con 4 m) se crea y la cadena declara su
        restricción y recompila las máscaras con su zona: la huella ampliada 2 celdas (calculada aquí con otra
        fórmula), sin el relleno de esa zona; el informe da por su código lo **ganado** (el polígono: la huella;
        la zona: la huella ampliada) y lo perdido (nada) en m²; y quedan obsoletas, con su causa (otro contenido
        de un dato que consumieron, las máscaras), las operaciones que usaron las anteriores: P1 y **la propia
        P2**, cuya restricción cambió lo que ella misma consumió."""
        stored = self.made(prep.request(WORKSHOP, start="entity:PLT-001", protect=True, guard_m=GUARD_M))
        self.assertEqual(self.stale_causes(str(stored.handle.uid)), set(), "al crearla, está al día")
        chain = self.chain()
        self.assertEqual((chain.declared, chain.declaration_changed, chain.masks_compiled), (1, True, True))
        self.assertIsNone(chain.failure)
        footprint_m2, zone_m2 = self.zone_area("PLT-002", 2)
        self.assertGreater(zone_m2, footprint_m2)
        (change,) = chain.changes
        self.assertEqual((change.code, change.name), (CODE, WORKSHOP))
        self.assertEqual(change.ctype, import_geoblender("core.constraints.model").ConstraintType.NO_FILL)
        for found, expected in ((change.polygon_gained_m2, footprint_m2), (change.zone_gained_m2, zone_m2)):
            self.assertAlmostEqual(found, expected, delta=1e-9 * expected)
        self.assertEqual((change.polygon_lost_m2, change.zone_lost_m2), (0.0, 0.0))
        masks = access.load_masks(self.project, self.v1.uid)
        zone = masks.zone(CODE).mask(self.grid.shape)
        self.assertTrue((zone == dilate(self.footprint("PLT-002"), 2)).all())
        self.assertEqual(masks.ctypes[CODE], "no_fill")
        self.assertFalse(masks.fill_allowed()[zone].any(), "ni se rellena su zona")
        self.assertEqual(self.entity_declared_code(), CODE)
        names = sorted(item.name for item in chain.obsolete)
        self.assertEqual(names, sorted([LOADING, WORKSHOP]))
        self.assertTrue(all(item.kind is preview.ObsoleteKind.CONSUMER and item.op_type == PLATFORM
                            for item in chain.obsolete))
        for code in ("PLT-001", "PLT-002"):
            causes = self.stale_causes(self.current(code))
            self.assertEqual({kind for kind, _name in causes}, {CAUSE_DATASET}, code)
            self.assertTrue({"gis_msk", "gis_mskz", "gis_mskr"} <= {name for _kind, name in causes}, causes)
        lines = [notice.text("es") for notice in chain.notices()]
        self.assertTrue(lines[0].startswith("Las restricciones que declaran las entidades de V01 están al día: 1"))
        self.assertIn("Las máscaras de V01 se han compilado de nuevo", lines[1])
        area = f"{round(footprint_m2):,}".replace(",", " ")  # el espacio fino de miles
        self.assertTrue(lines[2].startswith(f"{WORKSHOP} (restricción declarada): polígono +"), lines[2])
        self.assertIn("m² −0 m², zona +", lines[2])
        self.assertTrue(lines[3].startswith("Con las máscaras nuevas han quedado obsoletas 2 operaciones"),
                        lines[3])
        self.assertEqual(len(lines), 4)
        self.assertGreater(len(area), 0)

    def entity_declared_code(self) -> str:
        (found,) = self.declared()
        return str(found.code)

    # --- (d) El ciclo ------------------------------------------------------------------------------

    def test_d_recomputing_the_stale_resolves_the_cycle_and_leaves_nothing_stale(self) -> None:
        """RF-015-16, RF-008-26, D-21, CE-015-04: entidad → declarada → máscaras → entidad es un ciclo (P2
        consumió las máscaras que su propia restricción cambió, y el grafo da por obsoleto todo el ciclo): las
        máscaras, aun así, se entregan (**es lo que cierra ``mask_state``**: sus propias entradas no han
        cambiado, la declaración que consumieron es la de ahora) y «Recalcular lo obsoleto» rehace P1 y P2 con
        ellas (las de P2 incluyen su zona, que en el modo «en corte» no le impide cortar), **su salida no
        cambia** (el mismo hash de la superficie, la tabla y el informe) y por eso lo que dependía de ellas (la
        declaración y la compilación) pierde su marca sin recalcularse. Cada pasada rehace **una** unidad (lo
        recalculado que vuelve a quedar obsoleto espera, RF-008-27): con dos entidades encadenadas, dos
        pasadas; no queda nada obsoleto y las máscaras siguen siendo las de la declarada."""
        types = [self.query("SELECT op_type FROM gb_operation WHERE uid = ?", uid)[0][0]
                 for unit in self.plan_units() for uid in unit]
        self.assertIn(PLATFORM, types)
        self.assertEqual(self.recompute_plan()[0], (PLATFORM,), "empieza por una plataforma (el ciclo)")
        self.assertIs(self.state(), access.MaskState.CURRENT, "se entregan: sin ello nada las recalcularía")
        before = {code: self.hashes_of(self.current(code)) for code in ("PLT-001", "PLT-002")}
        declaration, masks_op, table = self.current_declaration(), self.compile_op(), self.declared_dump()
        rounds: list[tuple[str, ...]] = []
        for _ in range(4):
            self.clock.advance(minutes=1)
            done = ops.finish(recompute_mod.recompute_steps(self.project))
            statuses = [result.status for result in done.results]
            self.assertTrue(statuses and all(status is recompute_mod.UnitStatus.DONE for status in statuses),
                            done.results)
            rounds.append(tuple(op for result in done.results for op in (self.query(
                "SELECT op_type FROM gb_operation WHERE uid = ?", uid)[0][0] for uid in result.operations)))
            if not self.recompute_plan():
                break
        self.assertEqual(sorted(op for names in rounds for op in names), [PLATFORM, PLATFORM],
                         "solo se rehacen las dos entidades")
        self.assertLessEqual(len(rounds), 2)
        self.assertEqual(self.recompute_plan(), [])
        for code in ("PLT-001", "PLT-002"):
            self.assertEqual(self.stale_causes(self.current(code)), set(), code)
            self.assertEqual(self.hashes_of(self.current(code)), before[code], f"{code}: su salida no cambia")
        self.assertEqual(self.declared_dump(), table, "la declaración queda como estaba")
        self.assertEqual(self.current_declaration(), declaration, "y no se recalcula: perdió su marca")
        self.assertEqual(self.compile_op(), masks_op, "ni las máscaras")
        self.assertIs(self.state(), access.MaskState.CURRENT)
        self.assertIn(CODE, access.load_masks(self.project, self.v1.uid).zones)

    # --- (e) Otro resguardo ------------------------------------------------------------------------

    def test_e_changing_the_guard_declares_and_compiles_again_with_what_the_zone_gains(self) -> None:
        """RF-015-10, RF-012-06: el resguardo de P2 pasa de 4 a 6 m (otra persona): la cadena repite la
        declaración (otra tabla: otro hash), recompila las máscaras y da lo ganado por la zona (la corona de
        una celda más; el polígono no cambia: la huella es la misma) y lo perdido, nada."""
        digest = self.record_of().content_sha256
        self.change_as(decl.guard_key("PLT-002"), 6.0, EDITOR)
        chain = self.chain()
        self.assertEqual((chain.declared, chain.declaration_changed, chain.masks_compiled), (1, True, True))
        self.assertNotEqual(self.record_of().content_sha256, digest)
        (found,) = self.declared()
        self.assertEqual((found.buffer_out_m, found.decided_by), (6.0, EDITOR))
        (change,) = chain.changes
        _footprint_m2, old_zone = self.zone_area("PLT-002", 2)
        _footprint_m2, new_zone = self.zone_area("PLT-002", 3)
        self.assertGreater(new_zone, old_zone)
        self.assertAlmostEqual(change.zone_gained_m2, new_zone - old_zone, delta=1e-9 * new_zone)
        self.assertEqual((change.polygon_gained_m2, change.polygon_lost_m2, change.zone_lost_m2),
                         (0.0, 0.0, 0.0))
        zone = access.load_masks(self.project, self.v1.uid).zone(CODE).mask(self.grid.shape)
        self.assertTrue((zone == dilate(self.footprint("PLT-002"), 3)).all())

    # --- (f) Retirar la protección ------------------------------------------------------------------

    def test_f_retiring_the_protection_removes_the_restriction_and_reports_what_the_zone_loses(self) -> None:
        """RF-015-10, RF-012-06: P2 deja de proteger: la cadena deja la tabla **vacía** (existe, la compilación
        la consume), recompila las máscaras sin la zona y da lo perdido por su código: el polígono y la zona
        enteros; el relleno de su huella vuelve a estar admitido."""
        _footprint_m2, zone_m2 = self.zone_area("PLT-002", 3)
        footprint_m2 = float(self.footprint("PLT-002").sum()) * CELL_M2
        self.change_as(decl.protect_key("PLT-002"), False, EDITOR)
        chain = self.chain()
        self.assertEqual((chain.declared, chain.declaration_changed, chain.masks_compiled), (0, True, True))
        self.assertEqual(self.declared(), ())
        (change,) = chain.changes
        self.assertEqual((change.code, change.polygon_gained_m2, change.zone_gained_m2), (CODE, 0.0, 0.0))
        self.assertAlmostEqual(change.polygon_lost_m2, footprint_m2, delta=1e-9 * footprint_m2)
        self.assertAlmostEqual(change.zone_lost_m2, zone_m2, delta=1e-9 * zone_m2)
        masks = access.load_masks(self.project, self.v1.uid)
        self.assertNotIn(CODE, masks.zones)
        self.assertTrue(masks.fill_allowed()[self.footprint("PLT-002")].any())


# ---------------------------------------------------------------------------------------------
# Con una revisión congelada
# ---------------------------------------------------------------------------------------------


class FrozenChainTest(ChainCase):
    """RF-015-16, RF-009-19, RF-015-10 (T27): lo **vigente** de la versión sigue siéndolo aunque lo registrara una
    revisión que luego se congeló, y la 008 lo marca obsoleto en la revisión abierta; la cadena lo cuenta entre
    «lo que quedó obsoleto» (antes filtraba por la revisión abierta y no contaba lo congelado)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())
        cls.chain()
        cls.clock.advance(minutes=1)
        with cls.project.write_transaction() as conn:  # P1, ya hecha, pasa a la revisión congelada V01.r1
            freeze_rows(conn, cls.v1, now=cls.clock.now().isoformat(timespec="seconds"), reason="Siguiente")

    def test_a_what_is_live_in_the_frozen_revision_is_counted_with_what_became_obsolete(self) -> None:
        """RF-015-16, RF-009-19: P1 (en V01.r1, congelada, y vigente) usó las máscaras; P2 (que protege, creada en
        la revisión abierta) cambia las máscaras al declarar: la cadena da obsoletas **las dos**, P1 con la causa de
        las máscaras, y V01.r1 no cambia (sigue congelada, con los mismos elementos)."""
        revision = self.query("SELECT uid FROM gb_revision WHERE version_uid = ? AND state = 'frozen'",
                              self.v1.uid)[0][0]
        items = self.query("SELECT * FROM gb_revision_item WHERE revision_uid = ? ORDER BY fid", revision)
        self.made(prep.request(WORKSHOP, start="entity:PLT-001", protect=True, guard_m=GUARD_M))
        chain = self.chain()
        self.assertEqual((chain.declared, chain.masks_compiled), (1, True))
        self.assertEqual(sorted(item.name for item in chain.obsolete), sorted([LOADING, WORKSHOP]))
        self.assertEqual({kind for kind, _name in self.stale_causes(self.current("PLT-001"))}, {CAUSE_DATASET})
        self.assertEqual(self.query("SELECT state FROM gb_revision WHERE uid = ?", revision), [("frozen",)])
        self.assertEqual(self.query("SELECT * FROM gb_revision_item WHERE revision_uid = ? ORDER BY fid",
                                    revision), items, "lo congelado no cambia")


# ---------------------------------------------------------------------------------------------
# Los fallos
# ---------------------------------------------------------------------------------------------


class FailureTest(ChainCase):
    """RF-015-10, P-7: lo que pasa si una etapa falla. P1 creada (no protege) y, en el orden de las pruebas, (a)
    falla la compilación de las máscaras, (b) la cadena siguiente las compila de nuevo, (c) falla la
    declaración."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())

    def test_a_a_failing_compilation_leaves_the_masks_stale_with_their_cause(self) -> None:
        """RF-015-10, P-7, H-1: si la compilación de las máscaras falla (un fallo del disco), la declaración
        **ya está hecha** (su transacción), la entidad sigue creada y el fallo va en el resultado, con su
        etapa y su aviso; las máscaras quedan **obsoletas con su causa** (``DECLARED_NEW``: la tabla nueva no la
        consumió la compilación vigente) y no queda nada de la compilación a medias."""
        before = self.compile_op()
        with mock.patch.object(masks_store, "compile_steps", side_effect=OSError("disco lleno")):
            chain = self.chain()
        self.assertEqual((chain.declared, chain.declaration_changed, chain.masks_compiled), (0, True, False))
        self.assertIsNotNone(chain.failure)
        self.assertIs(chain.failure.stage, entity_store.ChainStage.MASKS)
        self.assertIsInstance(chain.failure.error, OSError)
        self.assertIs(chain.masks_state, access.MaskState.STALE)
        self.assertIs(access.mask_cause(self.project, self.v1.uid), access.MaskCause.DECLARED_NEW)
        self.assertEqual(self.compile_op(), before)
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE op_type = ? ORDER BY fid DESC LIMIT 1", COMPILE),
                         [("failed",)], "la compilación que falló queda como historia, fallida")
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation WHERE status = 'running'"), [(0,)])
        self.assertEqual(self.record_of().operation_uid, self.current_declaration())
        (warning,) = [notice for notice in chain.notices() if notice.severity == "warning"]
        self.assertEqual(warning.code, "des.entity_chain_masks_failed")
        self.assertIn("disco lleno", warning.text("es"))
        self.assertIn("Siguen obsoletas", warning.text("es"))
        with self.assertRaises(access.MaskError) as asked:
            access.load_masks(self.project, self.v1.uid)
        self.assertEqual(asked.exception.code, "core.constraint_masks_declared_new")

    def test_b_the_next_chain_or_whoever_asks_for_the_masks_compiles_them(self) -> None:
        """RF-015-10, RF-012-17: la cadena siguiente ve las máscaras obsoletas y las compila (aunque la
        declaración no cambie: el hueco no es de ella); quien las pide por el contrato de los operadores
        (``ensure_masks_steps``) también las habría compilado."""
        chain = self.chain()
        self.assertEqual((chain.declaration_changed, chain.masks_compiled), (False, True))
        self.assertIsNone(chain.failure)
        self.assertIs(self.state(), access.MaskState.CURRENT)
        self.assertIsNone(access.mask_cause(self.project, self.v1.uid))

    def test_c_a_refused_declaration_writes_nothing_and_is_told(self) -> None:
        """RF-015-10, RF-015-12, P-7: P1 pasa a proteger sin resguardo (D-19): la declaración se rechaza antes de
        escribir nada y el fallo va en el resultado (la etapa de declarar, el código de la falta de valor y su
        aviso); no se recompila nada: la tabla y las máscaras siguen como estaban."""
        before = (self.declared_dump(), self.compile_op(), self.current_declaration())
        self.addCleanup(self.change_as, decl.protect_key("PLT-001"), False, decl.USER)
        self.change_as(decl.protect_key("PLT-001"), True, decl.USER)
        chain = self.chain()
        self.assertIsNone(chain.declared)
        self.assertFalse(chain.declaration_changed or chain.masks_compiled)
        self.assertIs(chain.failure.stage, entity_store.ChainStage.DECLARE)
        self.assertIsInstance(chain.failure.error, design_messages.DesignError)
        self.assertEqual(chain.failure.error.code, "des.entity_param_missing")
        (warning,) = [notice for notice in chain.notices() if notice.severity == "warning"]
        self.assertEqual(warning.code, "des.entity_chain_declare_failed")
        self.assertIn(decl.guard_key("PLT-001"), warning.text("es"))
        self.assertEqual((self.declared_dump(), self.compile_op(), self.current_declaration()), before)


# ---------------------------------------------------------------------------------------------
# Esc y los pasos
# ---------------------------------------------------------------------------------------------


class StepsTest(ChainCase):
    """RF-015-29, P-7, RF-009-21: el progreso, Esc y los rechazos de la cadena. P1 (que no protege) y P2 (que sí)
    creadas."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())
        cls.made(prep.request(WORKSHOP, start="entity:PLT-001", protect=True, guard_m=GUARD_M))

    def test_a_the_progress_is_a_percentage_that_never_goes_back(self) -> None:
        """RF-015-29: la cadena da pasos (cada uno de una etapa) como un porcentaje de 0 a 100 que no retrocede,
        con la declaración en su primer tramo y las máscaras en el resto; el último lleva el resultado y es el
        100 %."""
        shown = list(entity_store.after_entity_change(self.project, self.v1, budget_s=1e-9))
        self.assertGreater(len(shown), 4, "un presupuesto mínimo da muchos pasos")
        self.assertTrue(all(step.phase == "entity_chain" for step in shown))
        self.assertTrue(all(step.total == 100 and 0 <= step.done <= 100 for step in shown))
        done = [step.done for step in shown]
        self.assertEqual(done, sorted(done))
        self.assertEqual((shown[0].done, shown[-1].done), (0, 100))
        self.assertTrue(all(step.result is None for step in shown[:-1]))
        self.assertIsInstance(shown[-1].result, entity_store.EntityChain)
        self.assertIs(shown[-1].result.masks_state, access.MaskState.CURRENT)

    def test_b_closing_in_the_middle_of_each_stage_leaves_nothing_half_done(self) -> None:
        """RF-015-29, P-7, RF-012-28: cerrar la cadena (Esc) en la declaración no escribe nada de ella; cerrarla
        en la compilación de las máscaras deja la declaración hecha y **ninguna compilación a medias** (la
        operación queda cancelada): las máscaras, obsoletas con su causa, y la cadena siguiente las compila."""
        self.change_as(decl.guard_key("PLT-002"), 5.0, EDITOR)  # la declaración cambiará: habrá que recompilar
        declaration, masks_op = self.current_declaration(), self.compile_op()
        written = self.written()
        work = entity_store.after_entity_change(self.project, self.v1, budget_s=1e-9)
        next(work)
        next(work)  # dentro de la declaración: la operación empezó, nada escrito todavía
        work.close()
        history = ("operations", "io")  # una operación cancelada queda como historia, con lo que iba a consumir
        self.assertEqual({key: value for key, value in self.written().items() if key not in history},
                         {key: value for key, value in written.items() if key not in history})
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE op_type = ? ORDER BY fid DESC LIMIT 1",
                                    DECLARE), [("cancelled",)])
        self.assertEqual((self.current_declaration(), self.compile_op()), (declaration, masks_op))

        work = entity_store.after_entity_change(self.project, self.v1, budget_s=1e-9)
        for step in work:
            if step.done > entity_store._CHAIN_DECLARE_SHARE:  # ya en la compilación
                break
        else:
            self.fail("la cadena no llegó a compilar las máscaras")
        work.close()
        self.assertNotEqual(self.current_declaration(), declaration, "la declaración ya estaba hecha")
        self.assertEqual(self.compile_op(), masks_op)
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation WHERE status = 'running'"), [(0,)])
        self.assertIs(self.state(), access.MaskState.STALE)
        chain = self.chain()
        self.assertEqual((chain.declaration_changed, chain.masks_compiled), (False, True))
        self.assertIs(self.state(), access.MaskState.CURRENT)

    def test_c_without_an_editable_version_nothing_is_done(self) -> None:
        """RF-009-21: sin versión (``core.version_required``), con una que no existe (``core.version_unknown``)
        o no editable (``core.version_not_editable``), la cadena se rechaza al avanzar y no escribe nada."""
        before = self.written()
        for version, code in ((None, "core.version_required"), ("V99", "core.version_unknown")):
            with self.subTest(version=version), self.assertRaises(versions_model.VersionError) as caught:
                ops.finish(entity_store.after_entity_change(self.project, version))
            self.assertEqual(caught.exception.code, code)
        with self.project.write_transaction() as conn:
            conn.execute("UPDATE gb_version SET status = 'VIGENTE' WHERE uid = ?", (self.v2.uid,))
            conn.execute("UPDATE gb_version SET status = 'SUPERADO', reason_closed = ? WHERE uid = ?",
                         ("Prueba de la T19", self.v2.uid))
        with self.assertRaises(versions_model.VersionError) as caught:
            ops.finish(entity_store.after_entity_change(self.project, self.v2))
        self.assertEqual(caught.exception.code, "core.version_not_editable")
        self.assertEqual(json.dumps(self.written(), default=str), json.dumps(before, default=str))


if __name__ == "__main__":
    import unittest

    unittest.main()

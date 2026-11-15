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
- **La primera declaración de una versión** (:class:`FirstDeclarationTest`, :class:`EveryEventTest`; T38, hallazgo
  E-1 de la verificación única; CE-015-04): una plataforma que **protege** recién creada en una versión sin
  ``des_decl_<vNN>`` y la cadena que se corta —con Esc en cualquier evento o con un fallo de la etapa de declarar—
  antes de escribir la primera tabla: **nunca** las máscaras al día sin la zona de la entidad (obsoletas con su
  causa, ``DECLARED_NEW``) y quien las pide declara y compila antes. Cada caso trabaja en una **copia** del
  proyecto tal como lo dejó la clase (``entity_fixtures.open_copy_of``).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, ClassVar
from unittest import mock

import numpy as np

from tests.support import entity_fixtures as efx
from tests.support import step_modals
from tests.support.package import import_geoblender
from tests.unit.design import test_declare_operation as decl
from tests.unit.design import test_platform_operation as ops
from tests.unit.design import test_platform_prepare as prep

access = import_geoblender("gis.masks.access")
compile_mod = import_geoblender("gis.masks.compile")
contract = import_geoblender("core.provenance.contract")
declared_mod = import_geoblender("core.constraints.declared")
design_messages = import_geoblender("design.messages")
entities = import_geoblender("design.entities")
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


# ---------------------------------------------------------------------------------------------
# Con una revisión congelada
# ---------------------------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------------------------
# La primera declaración de una versión (T38; hallazgo E-1)
# ---------------------------------------------------------------------------------------------

P1_CODE = declared_mod.declared_code("PLT-001")
"""El código de la restricción que declara la primera entidad."""
SAMPLED_EVENTS = 8
"""Los eventos de lo que sigue a «Crear» que, repartidos por toda la cadena, cierra :class:`EveryEventTest` además de
los cinco primeros."""


class FirstDeclarationCase(ChainCase):
    """Una versión **sin** ``des_decl_<vNN>`` con la plataforma P1 que **protege** (4 m) recién creada: lo que deja
    «Crear» tras su commit y **antes** de que la cadena escriba la primera declaración. La clase no toca su proyecto
    (es la instantánea): cada caso trabaja en una **copia** (:meth:`fresh`)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request(protect=True, guard_m=GUARD_M))

    @contextmanager
    def fresh(self) -> Iterator[Any]:
        """Una copia de la instantánea, abierta; al salir se borra."""
        with efx.open_copy_of(self.project, self.clock, self.STEP_M) as (project, _clock):
            yield project

    def declaration_exists(self, project: Any) -> bool:
        with project.read() as conn:
            return declared_mod.live_table(conn, self.v1.uid) is not None

    def close_after(self, project: Any, events: int, **patch: Any) -> int:
        """Lo que sigue a crear la plataforma, con un paso por evento, **cerrado** (Esc) tras ``events`` eventos:
        cuántos dio (menos que ``events`` si acabó antes)."""
        work = entity_store.after_entity_change(project, self.v1, budget_s=step_modals.ONE_STEP_S)
        given = 0
        try:
            for _ in range(events):
                next(work)
                given += 1
        except StopIteration:
            pass
        finally:
            work.close()
        return given

    def never_current_without_its_zone(self, project: Any) -> access.MaskState:
        """**El invariante de CE-015-04**: las máscaras de V01 no están al día sin la zona de la entidad viva que
        protege. Si lo están, la tienen (y el relleno de su huella no se admite); si no, ``load_masks`` se niega.
        Devuelve su estado."""
        state, _pending = access.mask_state(project, self.v1.uid)
        if state is access.MaskState.CURRENT:
            masks = access.load_masks(project, self.v1.uid)
            self.assertIn(P1_CODE, masks.zones, "máscaras al día sin la zona de la entidad que protege")
            self.assertFalse(masks.fill_allowed()[self.footprint("PLT-001")].any())
        else:
            self.assertIs(state, access.MaskState.STALE)
            with self.assertRaises(access.MaskError) as refused:
                access.load_masks(project, self.v1.uid)
            self.assertEqual(refused.exception.code, "core.constraint_masks_declared_new")
        return state

    def nothing_left_open(self, project: Any) -> None:
        with project.read() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM gb_operation WHERE status = 'running'").fetchone(),
                             (0,))
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchall(), [("ok",)])


if __name__ == "__main__":
    import unittest

    unittest.main()

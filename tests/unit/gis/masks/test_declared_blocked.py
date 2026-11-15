# SPDX-License-Identifier: GPL-3.0-or-later
"""Editar fuera de Geoblender la tabla de las restricciones declaradas por las entidades (spec 015, T20;
HU-015-1; RF-015-11, RF-012-29, RF-008-56, RF-012-03; plan 015 §2.1 y §5.8; ADR-0025 §4 y §5).

La tabla ``des_decl_<vNN>`` de una versión es de sus entidades: el módulo ``des`` la declara **no
editable a mano** (RF-012-29). Si se toca en QGIS (geometría, resguardo, «activa», motivo, filas), la
procedencia de la 008 la **bloquea** (``core.external_edit``, RF-008-56) y la compilación de las máscaras,
que la consume como entrada directa (papel ``constraints_declared``), **no se ejecuta** mientras tanto: ni
por la puerta de las operaciones (``gate.can_run``) ni cuando un operador pide las máscaras
(``gis.masks.access``), con un error claro de dominio y sin tocar nada. La persona acepta la edición con un
motivo (que queda registrado) o hace que **la entidad la vuelva a poner** (recalcular
``des.declare_constraints``, que reescribe la tabla entera desde las entidades); lo aceptado puede diferir de
lo que declaran las entidades y ``entity_store.declaration_diverges`` lo dice sin recalcular.

Sobre la cantera sintética de la 014 (``tests.support.entity_fixtures``, rejilla gruesa de 2 m) con P1 (la
«Plataforma de carga», que no protege) y P2 (la «Plataforma de taller», que protege con 4 m de resguardo),
declaradas y con las máscaras compiladas con la zona de P2 (``DeclaredBlockedTest``, por el orden de los
nombres de las pruebas). La edición de QGIS se simula con una conexión propia al GeoPackage del proyecto, con
los disparadores de seguimiento activos (los que ponen ``gpkg_contents.last_change``).

- **RF-015-11, RF-008-56** (a): editar la tabla la deja **bloqueada** (``core.external_edit`` con su evento); la
  puerta de la compilación se niega (``BlockKind.DATASET_BLOCKED``) y las ofertas son aceptar la edición y
  recalcular.
- **RF-015-11** (b): las máscaras no se entregan ni se compilan mientras tanto (``MaskCause.DECLARED_BLOCKED``;
  ``load_masks``, ``ensure_masks_steps``, ``compile_masks_steps``, ``begin_compile`` y «Recalcular lo
  obsoleto»): un ``ConstraintError`` que nombra las entidades, también con una fila que ya no se puede leer
  (nunca un ``ValueError`` crudo), y sin escribir nada.
- **RF-015-11, RF-008-56** (c, d): recalcular la declaración («la entidad la vuelve a poner») desbloquea con el
  mismo contenido de antes, sea cual sea la edición, y lo registrado queda como historia.
- **RF-015-11, RF-008-56** (e, f): aceptar la edición con un motivo la desbloquea (evento con su motivo, sin
  motivo se rechaza) y las máscaras se compilan con lo aceptado; el contenido vigente **difiere** del de las
  entidades (``declaration_diverges``) hasta que una entidad lo vuelve a poner.
- **RF-015-11, RF-015-10** (g, h): una entidad cuya protección se retiró, o que se descartó, ya no declara: el
  recálculo quita su restricción editada.
- **RF-015-11, RF-008-57** (i): una tabla eliminada en QGIS «falta»: tampoco se compila con ella (error de
  dominio) y recalcular la declaración la rehace.
- **RF-008-21, RF-008-56** (a, todo el fichero): una edición externa de un dato **de una versión** se registra
  como ``core.external_edit_version`` (de la versión del dato y de su revisión abierta: una operación de proyecto
  no puede usar un dato de una versión, D-14 de la 009; hasta la T20 la puerta fallaba con
  ``core.version_data_in_project`` y el dato no llegaba a bloquearse).
- **RF-012-03** (``ProjectLayerEditTest``): editar en QGIS una restricción **del proyecto** (las tres capas)
  sigue como antes: se registra y deja obsoletas las máscaras, sin bloquear nada.
"""

from __future__ import annotations

import sqlite3
import unittest
from typing import Any, ClassVar

from tests.support import entity_fixtures as efx
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.unit.design import test_declare_operation as decl
from tests.unit.design import test_platform_operation as ops
from tests.unit.design import test_platform_prepare as prep

access = import_geoblender("gis.masks.access")
cmessages = import_geoblender("core.constraints.messages")
contract = import_geoblender("core.provenance.contract")
cstore = import_geoblender("core.constraints.store")
datasets = import_geoblender("core.datasets.model")
declared = import_geoblender("core.constraints.declared")
entity_store = import_geoblender("design.entity_store")
events = import_geoblender("core.project.events")
external = import_geoblender("core.datasets.external")
gate = import_geoblender("core.provenance.gate")
masks_provenance = import_geoblender("gis.masks.provenance")
masks_store = import_geoblender("gis.masks.store")
messages = import_geoblender("core.provenance.messages")
provenance = import_geoblender("design.provenance")
recompute_mod = import_geoblender("core.provenance.recompute")
registry = import_geoblender("core.datasets.registry")
wkb = import_geoblender("core.gpkg.wkb")

Status = datasets.DatasetStatus
TABLE = decl.TABLE
NAME = "des_decl"
WORKSHOP = decl.WORKSHOP
CODE = declared.declared_code("PLT-002")
EXTRA_CODE = declared.declared_code("PLT-009")
USER = decl.USER


def core_operations_registered() -> Any:
    """Las operaciones de ``core`` que faltan (``core.external_edit``: lo que registra una edición de QGIS), que
    registra ``bl``; al salir, las quita."""
    return registered(*[item for item in contract.CORE_OPERATIONS if item.op_type not in contract.OPERATIONS])


EXTRA_ROW = (
    'INSERT INTO "{table}" (geom, uid, code, name, ctype, reason, decided_by, decided_on, entity_code, '
    "entity_name, buffer_out_m, active) SELECT geom, 'x' || uid, ?, name, ctype, reason, decided_by, "
    "decided_on, 'PLT-009', 'P9', buffer_out_m, active FROM \"{table}\"")
"""Lo que hace QGIS al añadir a mano la restricción de una entidad que no existe (una copia de la de P2)."""


def edited_text(language: str = "es") -> str:
    """El principio del aviso de una capa editada fuera de Geoblender que no se edita a mano."""
    return "se editó fuera de Geoblender" if language == "es" else "was edited outside Geoblender"


class DeclaredBlockedCase(decl.DeclareCase):
    """P1 y P2 creadas en V01, declaradas y con las máscaras al día, y los ayudantes de editar la tabla de las
    declaradas como QGIS y de lo que queda registrado (:class:`DeclaredBlockedTest` y, en
    ``test_declared_accepted``, la T40)."""

    initial: ClassVar[str]
    edits: ClassVar[int] = 0

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.enterClassContext(core_operations_registered())
        cls.made(prep.request())
        cls.clock.advance(minutes=1)
        cls.made(prep.request(WORKSHOP, start="entity:PLT-001", protect=True, guard_m=decl.GUARD_M))
        cls.entities_declared()
        cls.initial = str(cls.record_of().content_sha256)

    # --- Ayudas -------------------------------------------------------------------------------

    @classmethod
    def qgis(cls, sql: str, args: tuple[Any, ...] = ()) -> None:
        """QGIS cambia la tabla de las declaradas con su propia conexión (sin las funciones de Geoblender, con
        los disparadores de seguimiento de la tabla activos) y deja su ``last_change`` como lo pone al guardar."""
        cls.edits += 1
        conn = sqlite3.connect(cls.project.database_path, isolation_level=None)
        try:
            conn.execute(sql, args)
            conn.execute("UPDATE gpkg_contents SET last_change = ? WHERE table_name = ?",
                         (f"2031-01-01T00:00:{cls.edits:02d}.000Z", TABLE))
        finally:
            conn.close()

    def gate_result(self) -> Any:
        """La puerta de las operaciones para compilar las máscaras de V01, con lo que consumiría ahora."""
        inputs = masks_provenance.compile_inputs(masks_store.available_tables(self.project, self.v1.uid))
        return gate.can_run(self.project, masks_provenance.COMPILE, inputs, pending=gate.CheckState(),
                            version=self.v1.uid)

    def status(self) -> Any:
        return self.record_of().status

    def uid(self) -> str:
        """El uid del dato de las declaradas de V01 (un dato de una versión se indica por su uid: su nombre,
        sin la versión, es el de un dato del proyecto)."""
        return str(self.record_of().uid)

    def external_edits(self) -> list[tuple[Any, ...]]:
        return self.query("SELECT executor, status FROM gb_operation WHERE op_type = ? ORDER BY fid",
                          contract.EXTERNAL_EDIT_VERSION)

    def logged(self, kind: Any) -> list[Any]:
        with self.project.read() as conn:
            return events.read_events(conn, kind)

    def read_offers(self) -> tuple[Any, ...]:
        with self.project.read() as conn:
            return external.offers(conn, self.uid())

    def read_unusable(self) -> tuple[Any, ...]:
        with self.project.read() as conn:
            return external.unusable(conn)

    def snapshot(self) -> dict[str, Any]:
        """Todo lo que podría escribir una compilación o su rechazo: lo de ``written`` (operaciones, datos,
        parámetros, entradas y cifras), los eventos, la caché de la obsolescencia y la propia tabla."""
        return {**self.written(),
                "events": self.query_of("SELECT kind, entity_uid FROM gb_event ORDER BY fid"),
                "stale": self.query_of("SELECT item_uid, cause_kind FROM gb_stale ORDER BY 1, 2"),
                "table": self.declared_dump()}

    def assertBlocked(self) -> Any:
        """La puerta de la compilación se niega por **un** dato bloqueado, el de las declaradas; su motivo."""
        result = self.gate_result()
        self.assertIsInstance(result, gate.Blocked, result)
        (reason,) = result.reasons
        self.assertEqual((reason.kind, reason.item_kind, reason.name, reason.code),
                         (gate.BlockKind.DATASET_BLOCKED, "dataset", NAME, "core.dataset_blocked"))
        self.assertEqual(self.status(), Status.BLOCKED)
        return reason

    def put_back(self) -> Any:
        """«La entidad la vuelve a poner»: recalcular el dato (la oferta RECOMPUTE de la 008); su resultado."""
        self.clock.advance(minutes=1)
        outcome = ops.finish(recompute_mod.recompute_dataset_steps(self.project, self.uid()))
        self.assertEqual([result.status for result in outcome.results], [recompute_mod.UnitStatus.DONE],
                         [result.text() for result in outcome.results])
        return outcome

    def assertSameAsEntities(self, *, same_hash: bool = True) -> None:
        """La tabla vuelve a ser la de las entidades: vigente, sin divergir y, si ellas no cambiaron, con el mismo
        hash que al declarar; la puerta deja compilar."""
        self.assertEqual(self.status(), Status.CURRENT)
        if same_hash:
            self.assertEqual(self.record_of().content_sha256, self.initial)
        self.assertFalse(entity_store.declaration_diverges(self.project, self.v1))
        self.assertIsInstance(self.gate_result(), gate.Ready)


class ProjectLayerEditTest(efx.DeclaredConstraintsProjectCase):
    """RF-012-03: editar en QGIS una restricción **del proyecto** (las tres capas) sigue como antes: se registra
    como una edición externa y deja obsoletas las máscaras, pero no bloquea la capa ni la compilación; y no toca
    la tabla de las declaradas."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.enterClassContext(core_operations_registered())

    def qgis(self, sql: str, args: tuple[Any, ...], table: str) -> None:
        conn = sqlite3.connect(self.project.database_path, isolation_level=None)
        try:
            conn.execute(sql, args)
            conn.execute("UPDATE gpkg_contents SET last_change = ? WHERE table_name = ?",
                         ("2031-02-01T00:00:00.000Z", table))
        finally:
            conn.close()

    def test_editing_a_project_constraint_does_not_block_anything(self) -> None:
        polygons = cstore.layer_of("polygon")
        self.clock.advance(minutes=1)
        masks = ops.finish(access.ensure_masks_steps(self.project, self.v1.uid))
        self.assertIs(masks.state, access.MaskState.CURRENT)
        self.assertIn(efx.DECLARED_CODE, masks.zones)
        declared_before = self.record(NAME, self.v1)
        self.qgis(f"UPDATE {polygons} SET reason = ? WHERE code = 'perimetro'", ("Retocado en QGIS",),
                  polygons)
        inputs = masks_provenance.compile_inputs(masks_store.available_tables(self.project, self.v1.uid))
        result = gate.can_run(self.project, masks_provenance.COMPILE, inputs, pending=gate.CheckState(),
                              version=self.v1.uid)
        self.assertIsInstance(result, gate.Ready, result)
        self.assertEqual([notice.code for notice in result.notices], ["core.external_edit"])
        self.assertEqual(self.record(polygons).status, Status.CURRENT)
        self.assertEqual(self.query("SELECT executor FROM gb_operation WHERE op_type = 'core.external_edit'"),
                         [("external",)])
        after = self.record(NAME, self.v1)
        self.assertEqual((after.status, after.content_sha256),
                         (Status.CURRENT, declared_before.content_sha256))
        self.assertIs(access.mask_state(self.project, self.v1.uid)[0], access.MaskState.STALE)
        self.assertIsNone(access.mask_cause(self.project, self.v1.uid))
        self.clock.advance(minutes=1)
        again = ops.finish(access.ensure_masks_steps(self.project, self.v1.uid))
        self.assertIs(again.state, access.MaskState.CURRENT)
        self.assertIn(efx.DECLARED_CODE, again.zones)


if __name__ == "__main__":
    unittest.main()

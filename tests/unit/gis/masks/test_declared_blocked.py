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



class DeclaredBlockedTest(DeclaredBlockedCase):
    """Cada prueba parte de lo que dejó la anterior (por el orden de los nombres): (a) la edición bloquea y la
    puerta se niega, (b) las máscaras no se compilan, (c) recalcular desbloquea, (d) cada clase de edición, (e)
    aceptar con motivo, (f) la entidad lo vuelve a poner tras aceptar, (g) la protección retirada, (h) la entidad
    descartada, (i) la tabla eliminada y (j) V02."""

    # --- (a) La edición bloquea y la puerta se niega ----------------------------------------------

    def test_a_a_qgis_edit_blocks_the_table_and_the_gate_refuses_to_compile(self) -> None:
        """RF-015-11, RF-008-56, RF-012-29: sin tocar nada la puerta deja compilar y la tabla es una entrada
        directa de la compilación; el resguardo de la declarada, cambiado en QGIS, la deja **bloqueada** (una
        edición externa, hecha fuera, con su evento y sin deshacer nada) y la puerta se niega a compilar con
        ese dato y su aviso; se ofrece aceptar la edición y recalcularla (la declaración es repetible)."""
        self.assertIsInstance(self.gate_result(), gate.Ready)
        self.assertIn(NAME, masks_store.available_tables(self.project, self.v1.uid))
        self.assertEqual(self.external_edits(), [])
        self.qgis(f'UPDATE "{TABLE}" SET buffer_out_m = 6.0')
        reason = self.assertBlocked()
        self.assertIn(edited_text(), reason.text())
        self.assertIn(edited_text("en"), reason.text("en"))
        self.assertEqual(self.external_edits(), [("external", "done")])
        self.assertEqual(self.query("SELECT scope, revision_uid, op_version FROM gb_operation WHERE op_type = ?",
                                    contract.EXTERNAL_EDIT_VERSION), [("version", self.revision(), "1.0")],
                         "una operación de la versión del dato, en su revisión abierta")
        (event,) = self.logged(events.EventKind.EXTERNAL_EDIT)
        self.assertEqual((event.entity_uid, event.data["blocked"], event.data["editable"]),
                         (self.uid(), True, False))
        (found,) = [item.buffer_out_m for item in self.declared()]
        self.assertEqual(found, 6.0, "lo editado queda como lo dejó QGIS: nada se deshace")
        self.assertEqual(self.read_offers(), (external.Offer.ACCEPT, external.Offer.RECOMPUTE))
        (item,) = self.read_unusable()
        self.assertEqual((item.record.name, item.offers), (NAME, (external.Offer.ACCEPT,
                                                                  external.Offer.RECOMPUTE)))
        self.assertIsNone(item.input_uid, "no es lo importado de ninguna entrada: no se reimporta")

    # --- (b) Las máscaras no se compilan mientras tanto ---------------------------------------------

    def test_b_the_masks_are_not_compiled_nor_delivered_while_the_table_is_blocked(self) -> None:
        """RF-015-11, RF-008-56: con la tabla bloqueada las máscaras están obsoletas con su causa
        (``MaskCause.DECLARED_BLOCKED``) y quien las pide —cargarlas, ``ensure_masks_steps``,
        ``compile_masks_steps``, ``begin_compile`` o «Recalcular lo obsoleto»— recibe un error claro de
        dominio que nombra las entidades y dice qué hacer, en los dos idiomas, **sin escribir nada** (ni una
        operación, ni un dato, ni un evento) y sin llegar a leer una tabla que ya no es una declaración: con
        el tipo de una fila roto (lo que antes daba un ``ValueError`` crudo de ``read_declared``) igual."""
        self.assertBlocked()
        self.assertIs(access.mask_state(self.project, self.v1.uid)[0], access.MaskState.STALE)
        self.assertIs(access.mask_cause(self.project, self.v1.uid), access.MaskCause.DECLARED_BLOCKED)
        before = self.snapshot()
        for label, ask in (
                ("load_masks", lambda: access.load_masks(self.project, self.v1.uid)),
                ("require_current", lambda: access.require_current(self.project, self.v1.uid))):
            with self.subTest(ask=label), self.assertRaises(access.MaskError) as caught:
                ask()
            error = caught.exception
            self.assertEqual(error.code, "core.constraint_masks_declared_blocked")
            self.assertIn("V01", error.message)
            self.assertIn("fuera de Geoblender", error.message)
            self.assertIn("(geoblender.gis_compile_constraints)", error.message)
        english = cmessages.render("core.constraint_masks_declared_blocked", language="en", version="V01",
                                   command=masks_provenance.COMMAND)
        self.assertIn("outside Geoblender", english)
        self.assertNotEqual(english, error.message)
        for rows in ("legibles", "con un tipo roto"):
            if rows != "legibles":  # otra edición de QGIS que ya no deja leer la tabla como declarada
                self.qgis(f'UPDATE "{TABLE}" SET ctype = ?', ("no-es-un-tipo",))
            for label, ask in (
                    ("ensure_masks_steps", lambda: list(access.ensure_masks_steps(self.project, self.v1.uid))),
                    ("compile_masks_steps", lambda: list(access.compile_masks_steps(self.project, self.v1.uid))),
                    ("begin_compile", lambda: masks_store.begin_compile(self.project, version=self.v1.uid)),
                    ("gather", lambda: masks_store.gather(self.project, version=self.v1.uid))):
                with self.subTest(ask=label, rows=rows), self.assertRaises(cmessages.ConstraintError) as caught:
                    ask()
                error = caught.exception
                self.assertEqual(error.code, "core.constraint_declared_blocked")
                self.assertIn(f"«{WORKSHOP}»", error.text)
                self.assertIn("fuera de Geoblender", error.text)
                self.assertIn("acepte la edición con un motivo", error.text)
                self.assertIn("vuelvan a poner", error.text)
                self.assertIn(TABLE, error.text)
        self.assertIn("were edited outside Geoblender", cmessages.render(
            "core.constraint_declared_blocked", language="en", version="V01", names=f"«{WORKSHOP}»",
            table=TABLE))
        self.assertEqual({key: value for key, value in self.snapshot().items() if key != "table"},
                         {key: value for key, value in before.items() if key != "table"})
        # «Recalcular lo obsoleto» (008) tampoco las compila: espera a la edición externa sin resolver
        self.clock.advance(minutes=1)
        operations = self.query_of("SELECT count(*) FROM gb_operation")
        outcome = ops.finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual(outcome.results, ())
        self.assertIn(masks_provenance.COMPILE, [item.op_type for item in outcome.remaining.skipped])
        self.assertEqual(self.query_of("SELECT count(*) FROM gb_operation"), operations)
        self.assertEqual(self.status(), Status.BLOCKED)

    # --- (c) La entidad la vuelve a poner ---------------------------------------------------------

    def test_c_recomputing_the_declaration_puts_it_back_and_unblocks_it(self) -> None:
        """RF-015-11, RF-008-56, RF-015-10: aceptar sin motivo se rechaza sin escribir nada; recalcular el dato
        («la entidad la vuelve a poner»: ``des.declare_constraints``, que reescribe la tabla entera desde las
        entidades) la desbloquea con **el mismo contenido de antes** (el mismo hash), sin divergir; las
        ediciones externas quedan registradas como historia, la puerta deja compilar y las máscaras se
        entregan otra vez: lo editado y recalculado no cambió lo que consumieron."""
        uid = self.uid()
        edits = self.logged(events.EventKind.EXTERNAL_EDIT)
        before = self.snapshot()
        with self.assertRaises(messages.ProvenanceError) as caught, self.project.write_transaction() as conn:
            external.accept_edit(conn, self.project, uid, "   ")
        self.assertEqual(caught.exception.code, "core.accept_edit_reason_missing")
        self.assertEqual(self.snapshot(), before)
        previous = self.current_declaration()
        self.put_back()
        self.assertNotEqual(self.current_declaration(), previous)
        self.assertEqual(self.query("SELECT superseded_by FROM gb_operation WHERE uid = ?", previous),
                         [(self.current_declaration(),)])
        self.assertSameAsEntities()
        self.assertEqual(self.uid(), uid)
        self.assertEqual(self.logged(events.EventKind.EXTERNAL_EDIT), edits, "lo registrado queda como historia")
        self.assertTrue(edits)
        self.assertEqual(self.read_offers(), ())
        self.assertEqual(self.read_unusable(), ())
        self.assertIsNone(access.mask_cause(self.project, self.v1.uid))
        self.assertIs(access.mask_state(self.project, self.v1.uid)[0], access.MaskState.CURRENT)
        self.assertIn(CODE, access.load_masks(self.project, self.v1.uid).zones)

    # --- (d) Cada clase de edición ----------------------------------------------------------------

    def test_d_every_kind_of_edit_blocks_it_and_the_entity_puts_it_back(self) -> None:
        """RF-015-11, RF-008-56: la «activa», el motivo, la geometría (un contorno desplazado), borrar la fila y
        añadir la de una entidad que no existe, hechos en QGIS, dejan la tabla bloqueada y la puerta se niega;
        recalcular la declaración la deja cada vez como la dejan las entidades."""
        moved = [tuple(ring + (10.0, 0.0) for ring in part) for part in self.declared()[0].parts]
        shifted = wkb.encode_geometry("MULTIPOLYGON", [list(part) for part in moved],
                                      self.project.record.crs_epsg, False)
        edits = {
            "«activa»": (f'UPDATE "{TABLE}" SET active = 0', ()),
            "el motivo": (f'UPDATE "{TABLE}" SET reason = ?', ("Retocado en QGIS",)),
            "la geometría": (f'UPDATE "{TABLE}" SET geom = ?', (shifted,)),
            "borrar la fila": (f'DELETE FROM "{TABLE}"', ()),
            "añadir una fila": (EXTRA_ROW.format(table=TABLE), (EXTRA_CODE,)),
        }
        for label, (sql, args) in edits.items():
            with self.subTest(edit=label):
                self.qgis(sql, args)
                self.assertBlocked()
                self.assertIn(external.Offer.RECOMPUTE, self.read_offers())
                self.put_back()
                self.assertSameAsEntities()

    # --- (e) Aceptar con un motivo ----------------------------------------------------------------

    def test_e_accepting_the_edit_with_a_reason_unblocks_it_and_the_masks_use_what_was_accepted(self) -> None:
        """RF-015-11, RF-008-56: QGIS añade la restricción de una entidad que no existe: bloqueada, la puerta se
        niega; aceptar la edición con un motivo (sin rutas) la deja vigente con el evento del motivo y de quien
        la aceptó, ya sin ofertas, y la puerta deja compilar. Lo aceptado **difiere** de lo que declaran las
        entidades (``declaration_diverges``, también antes de aceptar), y las máscaras, obsoletas por el cambio
        del dato, se compilan con la fila aceptada."""
        self.assertFalse(entity_store.declaration_diverges(self.project, self.v1))
        self.qgis(EXTRA_ROW.format(table=TABLE), (EXTRA_CODE,))
        self.assertBlocked()
        self.assertTrue(entity_store.declaration_diverges(self.project, self.v1))
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            accepted = external.accept_edit(conn, self.project, self.uid(),
                                            "La propiedad pide proteger también la balsa (Q:\\a\\b.pdf)")
        self.assertEqual((accepted.status, accepted.name), (Status.CURRENT, NAME))
        (event,) = self.logged(events.EventKind.EDIT_ACCEPTED)
        self.assertEqual((event.entity_kind, event.entity_uid, event.data["reason"], event.data["accepted_by"]),
                         ("dataset", accepted.uid, "La propiedad pide proteger también la balsa (b.pdf)",
                          self.project.session.user_host))
        self.assertIn("La propiedad pide proteger también la balsa", event.message)
        self.assertEqual(self.read_offers(), ())
        self.assertIsInstance(self.gate_result(), gate.Ready)
        self.assertTrue(entity_store.declaration_diverges(self.project, self.v1),
                        "lo aceptado no es lo que declaran las entidades")
        self.assertIs(access.mask_state(self.project, self.v1.uid)[0], access.MaskState.STALE)
        self.assertIsNone(access.mask_cause(self.project, self.v1.uid))
        self.clock.advance(minutes=1)
        masks = ops.finish(access.ensure_masks_steps(self.project, self.v1.uid))
        self.assertIs(masks.state, access.MaskState.CURRENT)
        self.assertIn(EXTRA_CODE, masks.zones, "las máscaras llevan la restricción aceptada")
        self.assertIn(CODE, masks.zones)
        self.assertTrue(entity_store.declaration_diverges(self.project, self.v1))

    # --- (f) La entidad lo vuelve a poner tras aceptar ----------------------------------------------

    def test_f_the_entity_puts_back_what_was_accepted(self) -> None:
        """RF-015-11, RF-015-10: lo aceptado se queda hasta que una entidad lo vuelve a poner: declarar de
        nuevo (lo que encadena toda orden de entidades) sustituye a la declaración vigente y reescribe la tabla
        desde las entidades, que ya no diverge; las máscaras se compilan sin la fila que se aceptó."""
        self.assertTrue(entity_store.declaration_diverges(self.project, self.v1))
        previous = self.current_declaration()
        self.declare()
        self.assertEqual(self.query("SELECT superseded_by FROM gb_operation WHERE uid = ?", previous),
                         [(self.current_declaration(),)], "sustituye a la declaración, no a la edición externa")
        self.assertSameAsEntities()
        self.clock.advance(minutes=1)
        masks = ops.finish(access.ensure_masks_steps(self.project, self.v1.uid))
        self.assertNotIn(EXTRA_CODE, masks.zones)
        self.assertIn(CODE, masks.zones)
        self.assertFalse(entity_store.declaration_diverges(self.project, self.v1))

    # --- (g) La protección retirada ---------------------------------------------------------------

    def test_g_retiring_the_protection_removes_the_edited_restriction(self) -> None:
        """RF-015-11, RF-015-10: la restricción de P2, editada en QGIS (bloqueada), ya no existe cuando P2
        retira su protección: recalcular la declaración la quita (la tabla queda vacía, vigente y sin divergir)
        y al proteger otra vez vuelve."""
        self.qgis(f'UPDATE "{TABLE}" SET active = 0')
        self.assertBlocked()
        self.change_as(decl.protect_key("PLT-002"), False, USER)
        self.put_back()
        self.assertEqual(self.declared(), ())
        self.assertEqual(self.status(), Status.CURRENT)
        self.assertFalse(entity_store.declaration_diverges(self.project, self.v1))
        self.assertIsInstance(self.gate_result(), gate.Ready)
        self.change_as(decl.protect_key("PLT-002"), True, USER)
        self.declare()
        self.assertSameAsEntities(same_hash=False)  # su decisor y la fecha de su decisión son los del último cambio
        (found,) = self.declared()
        self.assertEqual((found.code, found.decided_by), (CODE, USER))

    # --- (h) La entidad descartada ----------------------------------------------------------------

    def test_h_discarding_the_entity_removes_the_edited_restriction(self) -> None:
        """RF-015-11, RF-015-25: P2 se descarta (nada se borra: sus datos quedan descartados) con su
        restricción editada en QGIS y bloqueada; recalcular la declaración —que reúne ella misma las entidades
        vivas: lo descartado sale de su petición— la quita; la tabla queda vacía, vigente y sin divergir."""
        self.qgis(f'UPDATE "{TABLE}" SET reason = ?', ("Retocado en QGIS",))
        self.assertBlocked()
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            for family in ("psf", "epr", "prp"):
                found = registry.get(conn, provenance.dataset_name(family, WORKSHOP), version_uid=self.v1.uid)
                registry.set_status(conn, self.project, found.uid, "discarded")
        self.assertEqual(self.status(), Status.BLOCKED)
        self.put_back()
        self.assertEqual(self.declared(), ())
        self.assertEqual(self.status(), Status.CURRENT)
        self.assertFalse(entity_store.declaration_diverges(self.project, self.v1))
        self.assertEqual(self.figures_of(self.current_declaration()), {("des.declared_count", decl.NO_SCOPE): 0.0})

    def test_i_a_table_dropped_in_qgis_is_missing_and_is_not_compiled_either(self) -> None:
        """RF-015-11, RF-008-57: QGIS elimina la capa de las declaradas: el dato «falta» (la puerta se niega
        con su aviso), las máscaras no se compilan sin leer nada (sin ella se perdería la prohibición en
        silencio: ``read_declared`` da ninguna de una tabla que no existe) y recalcular la declaración, que
        la rehace desde las entidades, la deja vigente."""
        conn = sqlite3.connect(self.project.database_path, isolation_level=None)
        try:
            conn.execute(f'DROP TABLE "{TABLE}"')
            for registered_table in ("gpkg_contents", "gpkg_geometry_columns"):
                conn.execute(f"DELETE FROM {registered_table} WHERE table_name = ?", (TABLE,))
        finally:
            conn.close()
        result = self.gate_result()
        self.assertIsInstance(result, gate.Blocked, result)
        (reason,) = result.reasons
        self.assertEqual((reason.kind, reason.name), (gate.BlockKind.DATASET_MISSING, NAME))
        self.assertEqual(self.status(), Status.MISSING)
        self.assertIs(access.mask_cause(self.project, self.v1.uid), access.MaskCause.DECLARED_BLOCKED)
        before = self.written()["operations"]
        with self.assertRaises(cmessages.ConstraintError) as caught:
            list(access.ensure_masks_steps(self.project, self.v1.uid))
        self.assertEqual(caught.exception.code, "core.constraint_declared_unusable")
        self.assertIn(TABLE, caught.exception.text)
        self.assertIn("falta o está dañada", caught.exception.text)
        self.assertEqual(self.written()["operations"], before)
        self.put_back()
        self.assertSameAsEntities(same_hash=False)
        self.assertEqual(self.declared(), ())

    def test_j_a_version_without_a_declaration_does_not_diverge(self) -> None:
        """RF-015-11, RF-012-29: V02 no tiene entidades ni tabla de declaradas: no hay nada que diverja."""
        self.assertIsNone(self.record_of(self.v2))
        self.assertFalse(entity_store.declaration_diverges(self.project, self.v2))
        self.assertFalse(entity_store.declaration_diverges(self.project, self.v2.uid))


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

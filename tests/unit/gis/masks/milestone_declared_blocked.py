# SPDX-License-Identifier: GPL-3.0-or-later
"""Pruebas de hito de «test_declared_blocked» (spec 015, T48; plan 015 §7.4): las clases que pesan,
movidas sin cambiar una aserción. El «verde» deja en ``test_declared_blocked`` las más ligeras de cada
requisito; las de aquí las ejecuta el paso «hito» de ``tools/check.py --completo`` (la publicación
lo pide siempre).
"""

from __future__ import annotations

import sqlite3

from tests.unit.design import test_declare_operation as decl
from tests.unit.design import test_platform_operation as ops
from tests.unit.gis.masks.test_declared_blocked import (
    CODE,
    DeclaredBlockedCase,
    EXTRA_CODE,
    EXTRA_ROW,
    NAME,
    Status,
    TABLE,
    USER,
    WORKSHOP,
    access,
    cmessages,
    contract,
    edited_text,
    entity_store,
    events,
    external,
    gate,
    masks_provenance,
    masks_store,
    messages,
    provenance,
    recompute_mod,
    registry,
    wkb,
)


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

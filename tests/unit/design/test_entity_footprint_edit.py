# SPDX-License-Identifier: GPL-3.0-or-later
"""Editar fuera de Geoblender la tabla de **la entidad** (``des_epr_``), de la que sale su zona declarada (spec 015,
T43; hallazgo B-2 de la verificación única; HU-015-1; RF-015-11, RF-015-10, RF-008-56, RF-008-57, RF-008-21).

La declaración de restricciones de una versión (``des.declare_constraints``) lee la huella de cada entidad viva que
protege de su tabla ``des_epr_`` (``entity_store.declared_sources``). Esa tabla es una **salida** de la entidad, no
editable a mano: si se toca en QGIS, la procedencia de la 008 la bloquea (``core.external_edit``, RF-008-56). Hasta la
T43 ``after_entity_change`` no miraba ese estado: reescribía ``des_decl`` con la huella editada y la zona pasaba de
1.653 a 133 celdas **sin ningún aviso**, y borrar la fila o cambiar el ``name`` daba mensajes crípticos. Ahora la
declaración —y la capa de entidades, que lee la misma tabla— **se niegan con un error que nombra la entidad** y dice
qué hacer (aceptar la edición con un motivo o recalcular la entidad), y las máscaras no se compilan mientras tanto
(el equivalente, para las entidades, de ``core.constraints.declared.require_usable``).

Sobre la cantera sintética de la 014 con las capas de plataformas (rejilla gruesa de 2 m): P1 (la «Plataforma de
carga», que no protege) y P2 (la «Plataforma de taller», que protege con 4 m), declaradas, con las máscaras al día y
nada obsoleto. Cada caso trabaja en una **copia** del proyecto tal como lo dejó la clase
(``entity_fixtures.open_copy_of``); la edición de QGIS se simula con una conexión propia al GeoPackage, con los
disparadores de seguimiento activos.

- **(a) Bloqueada** (RF-015-11, RF-008-56): una edición de la huella que la 008 detecta (la puerta de las operaciones
  o «Comprobar cambios en las entradas») deja el dato ``des_epr_`` **bloqueado**; ``declared_sources``,
  ``recompute_declaration`` y lo que sigue a las órdenes de entidades se niegan con ``des.entity_footprint_blocked``
  (la entidad, la tabla, qué hacer, en los dos idiomas); la declaración no cambia, las máscaras no se recompilan y
  la capa de entidades, que lee la misma tabla, tampoco se rehace.
- **(b) La salida** (RF-015-11): aceptar la edición con un motivo la devuelve a la declaración (con lo aceptado) y
  recalcular la entidad la vuelve a escribir y deja la declaración como estaba.
- **(c) Sin fila o dañada** (RF-008-57): una tabla a la que QGIS borró la fila, o que ya no existe, no se lee como
  una entidad: ``des.entity_footprint_unusable`` con la entidad (nunca un ``ValueError`` crudo ni «consume el dato
  que no está en el proyecto»).
- **(d) El nombre** (RF-008-21): cambiar el atributo ``name`` de la tabla, sin más, no cambia el dato del que la
  declaración se alimenta (el ``des_epr_`` de la entidad, por su nombre registrado): no se pierde ni se pide nada
  que no esté.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from tests.support import entity_fixtures as efx
from tests.support.package import import_geoblender
from tests.unit.design import test_after_entity_change as chain_test
from tests.unit.design import test_platform_operation as ops
from tests.unit.design import test_platform_prepare as prep
from tests.unit.gis.masks.test_declared_blocked import core_operations_registered

access = import_geoblender("gis.masks.access")
datasets = import_geoblender("core.datasets.model")
declared_mod = import_geoblender("core.constraints.declared")
design_messages = import_geoblender("design.messages")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
external = import_geoblender("core.datasets.external")
gate = import_geoblender("core.provenance.gate")
masks_provenance = import_geoblender("gis.masks.provenance")
masks_store = import_geoblender("gis.masks.store")
provenance = import_geoblender("design.provenance")
recompute_mod = import_geoblender("core.provenance.recompute")
registry = import_geoblender("core.datasets.registry")

DesignError = design_messages.DesignError
WORKSHOP = prep.WORKSHOP
CODE = "PLT-002"
GUARD_M = chain_test.GUARD_M
ZONE = declared_mod.declared_code(CODE)
WHY = "La huella la corrigió la persona en QGIS"


class FootprintEditCase(chain_test.ChainCase):
    """P1 y P2 (que protege) creadas en V01, declaradas, con las máscaras al día y nada obsoleto."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.enterClassContext(core_operations_registered())
        cls.made(prep.request())
        cls.made(prep.request(WORKSHOP, start="entity:PLT-001", protect=True, guard_m=GUARD_M))
        cls.chain()
        cls.settle()

    # --- Ayudas (sobre la copia ``project``) -------------------------------------------------------

    @contextmanager
    def fresh(self) -> Iterator[Any]:
        """Una copia de lo que dejó la clase, abierta; al salir se borra."""
        with efx.open_copy_of(self.project, self.clock, self.STEP_M) as (project, _clock):
            yield project

    def entity_table(self, project: Any, code: str = CODE) -> str:
        """El ``des_epr_`` vigente de la entidad ``code`` de V01."""
        entry = entities.registry(project, self.v1.uid).get(code)
        with project.read() as conn:
            return str(conn.execute(
                "SELECT d.locator FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
                "WHERE io.operation_uid = ? AND io.direction = 'out' AND io.role = 'entity'",
                (entry.operation_uid,)).fetchone()[0])

    @staticmethod
    def qgis(project: Any, table: str, sql: str, args: tuple[Any, ...] = (), *, second: int = 1) -> None:
        """QGIS cambia la tabla con su propia conexión y deja su ``last_change`` como lo pone al guardar."""
        conn = sqlite3.connect(project.database_path, isolation_level=None)
        try:
            conn.execute(sql, args)
            conn.execute("UPDATE gpkg_contents SET last_change = ? WHERE table_name = ?",
                         (f"2031-01-01T00:00:{second:02d}.000Z", table))
        finally:
            conn.close()

    def edit_footprint(self, project: Any, table: str) -> None:
        """La persona reduce en QGIS la huella de la entidad a sus tres primeros tramos."""
        with project.read() as conn:
            runs = json.loads(conn.execute(f'SELECT footprint FROM "{table}"').fetchone()[0])
        self.qgis(project, table, f'UPDATE "{table}" SET footprint = ?', (json.dumps(runs[:3]),))

    def detect(self, project: Any) -> Any:
        """La puerta de las operaciones para compilar las máscaras de V01: detecta la edición y bloquea el dato."""
        inputs = masks_provenance.compile_inputs(masks_store.available_tables(project, self.v1.uid))
        return gate.can_run(project, masks_provenance.COMPILE, inputs, pending=gate.CheckState(),
                            version=self.v1.uid)

    def status_of(self, project: Any, table: str) -> Any:
        with project.read() as conn:
            return conn.execute("SELECT status FROM gb_dataset WHERE locator = ? AND version_uid = ?",
                                (table, self.v1.uid)).fetchone()[0]

    def declaration_hash(self, project: Any) -> str:
        with project.read() as conn:
            return str(registry.get(conn, provenance.dataset_name(provenance.DECLARED_TABLE),
                                    version_uid=self.v1.uid).content_sha256)

    def zone_cells(self, project: Any) -> int:
        masks = access.load_masks(project, self.v1.uid)
        return int(masks.zone(ZONE).mask(masks.classes.shape).sum())

    def operations(self, project: Any, op_type: str) -> list[str]:
        with project.read() as conn:
            return [str(uid) for (uid,) in conn.execute(
                "SELECT uid FROM gb_operation WHERE op_type = ? ORDER BY fid", (op_type,))]

    def layer_operations(self, project: Any) -> list[str]:
        return self.operations(project, provenance.ENTITY_LAYER)

    def chain_of(self, project: Any) -> Any:
        self.clock.advance(minutes=1)
        return ops.finish(entity_store.after_entity_change(project, self.v1))

    def assertNamesEntity(self, error: Any, code: str) -> None:
        self.assertEqual(error.code, code)
        for language in ("es", "en"):
            text = error.text_in(language)
            self.assertIn(WORKSHOP, text)
            self.assertNotIn("Traceback", text)
            self.assertNotIn("?", text, "ningún marcador sin valor")


class FootprintEditTest(FootprintEditCase):
    """RF-015-11, RF-008-56, RF-008-57, B-2: la edición de la huella de P2 en QGIS, en cada caso sobre una copia."""

    def test_a_a_detected_edit_blocks_the_declaration_the_masks_and_the_layer_naming_the_entity(self) -> None:
        """RF-015-11, RF-008-56: la huella de P2 reducida en QGIS y detectada por la 008 deja el dato bloqueado;
        ``declared_sources`` y ``recompute_declaration`` se niegan con ``des.entity_footprint_blocked`` (la
        entidad, la tabla y qué hacer, en los dos idiomas); lo que sigue a una orden de entidades cuenta el fallo de
        la declaración (la etapa de declarar), **no recompila las máscaras** y no rehace la capa con la huella
        editada; la declaración y la zona de las máscaras no cambian (1.653 → 133 celdas hasta la T43)."""
        with self.fresh() as project:
            table = self.entity_table(project)
            hash_before, zone_before = self.declaration_hash(project), self.zone_cells(project)
            compiles, layers = (self.operations(project, masks_provenance.COMPILE),
                                self.layer_operations(project))
            self.edit_footprint(project, table)
            self.assertIsInstance(self.detect(project), gate.Ready)
            self.assertEqual(str(self.status_of(project, table)), "blocked")
            with self.assertRaises(DesignError) as caught:
                entity_store.declared_sources(project, self.v1)
            self.assertNamesEntity(caught.exception, "des.entity_footprint_blocked")
            self.assertIn(table, caught.exception.text)
            self.assertIn("motivo", caught.exception.text)
            self.assertIn("reason", caught.exception.text_in("en"))
            request = recompute_mod.RecomputeRequest(
                project, self.operations(project, provenance.DECLARE_CONSTRAINTS)[-1],
                provenance.DECLARE_CONSTRAINTS, {}, (), (), version=self.v1.uid)
            with self.assertRaises(DesignError) as again:
                entity_store.recompute_declaration(request)
            self.assertEqual(again.exception.code, "des.entity_footprint_blocked")
            chain = self.chain_of(project)
            self.assertIs(chain.failure.stage, entity_store.ChainStage.DECLARE)
            self.assertIn(WORKSHOP, chain.failure.reason)
            self.assertFalse(chain.masks_compiled)
            self.assertIsNone(chain.layer)
            self.assertIs(chain.layer_failure.stage, entity_store.ChainStage.LAYER)
            self.assertIn(WORKSHOP, chain.layer_failure.reason)
            self.assertEqual((self.declaration_hash(project), self.zone_cells(project)), (hash_before, zone_before))
            self.assertEqual(self.operations(project, masks_provenance.COMPILE), compiles)
            self.assertEqual(self.layer_operations(project), layers)
            self.assertEqual([notice.code for notice in chain.notices()],
                             ["des.entity_chain_declare_failed", "des.entity_chain_layer_failed"])

    def test_b_accepting_the_edit_or_recalculating_the_entity_lets_the_declaration_go_on(self) -> None:
        """RF-015-11, RF-008-56: las dos salidas que ofrece el error. **Aceptar la edición con un motivo**: el dato
        vuelve a estar vigente y la declaración usa lo aceptado (la zona sale de la huella editada); **recalcular
        la entidad** la vuelve a escribir y la declaración queda como estaba (el mismo hash)."""
        with self.fresh() as project:
            table = self.entity_table(project)
            hash_before = self.declaration_hash(project)
            self.edit_footprint(project, table)
            self.detect(project)
            with project.read() as conn:
                uid = str(registry.get(conn, provenance.dataset_name("epr", WORKSHOP),
                                       version_uid=self.v1.uid).uid)
            self.clock.advance(minutes=1)
            outcome = ops.finish(recompute_mod.recompute_dataset_steps(project, uid))
            self.assertEqual([result.status for result in outcome.results], [recompute_mod.UnitStatus.DONE],
                             [result.text() for result in outcome.results])
            chain = self.chain_of(project)
            self.assertIsNone(chain.failure)
            self.assertEqual(self.declaration_hash(project), hash_before, "la entidad volvió a poner su huella")

        with self.fresh() as project:
            table = self.entity_table(project)
            self.edit_footprint(project, table)
            self.detect(project)
            with project.read() as reading:
                record = registry.get(reading, provenance.dataset_name("epr", WORKSHOP), version_uid=self.v1.uid)
            with project.write_transaction() as conn:
                external.accept_edit(conn, project, str(record.uid), WHY)
            self.assertEqual(str(self.status_of(project, table)), "current")
            chain = self.chain_of(project)
            self.assertIsNone(chain.failure)
            self.assertEqual(chain.declared, 1)
            self.assertTrue(chain.declaration_changed, "la declaración usa la huella aceptada")

    def test_c_a_table_without_its_row_or_missing_is_unusable_and_names_the_entity(self) -> None:
        """RF-008-57, RF-015-11: QGIS borró la fila de la tabla (sin que la 008 lo haya registrado aún) o la tabla
        ya no existe: ``des.entity_footprint_unusable`` con la entidad en los dos idiomas, nunca «la tabla … tiene
        una fila, no 0» ni «consume el dato … que no está en el proyecto»; lo que sigue a una orden de entidades
        lo cuenta como el fallo de declarar y no escribe nada."""
        with self.fresh() as project:
            table = self.entity_table(project)
            self.qgis(project, table, f'DELETE FROM "{table}"')
            with self.assertRaises(DesignError) as caught:
                entity_store.declared_sources(project, self.v1)
            self.assertNamesEntity(caught.exception, "des.entity_footprint_unusable")
            written, compiles = self.declaration_hash(project), self.operations(project, masks_provenance.COMPILE)
            chain = self.chain_of(project)
            self.assertIs(chain.failure.stage, entity_store.ChainStage.DECLARE)
            self.assertIn(WORKSHOP, chain.failure.reason)
            self.assertEqual(self.declaration_hash(project), written)
            self.assertEqual(self.operations(project, masks_provenance.COMPILE), compiles)
        with self.fresh() as project:
            table = self.entity_table(project)
            conn = sqlite3.connect(project.database_path, isolation_level=None)
            try:
                conn.execute("PRAGMA writable_schema = ON")
                conn.execute("DELETE FROM gpkg_contents WHERE table_name = ?", (table,))
                conn.execute(f'DROP TABLE "{table}"')
            finally:
                conn.close()
            with self.assertRaises(DesignError) as caught:
                entity_store.declared_sources(project, self.v1)
            self.assertNamesEntity(caught.exception, "des.entity_footprint_unusable")
            self.detect(project)  # y cuando la 008 lo ve (falta), por su estado
            self.assertEqual(str(self.status_of(project, table)), "missing")
            with self.assertRaises(DesignError) as seen:
                entity_store.declared_sources(project, self.v1)
            self.assertNamesEntity(seen.exception, "des.entity_footprint_unusable")

    def test_c_a_dataset_the_008_has_as_missing_or_damaged_is_unusable_too(self) -> None:
        """RF-008-57: con el dato ``des_epr_`` de la entidad registrado como **falta** o **dañado** (lo que deja la 008
        tras detectarlo), aunque la tabla se pueda leer, la declaración se niega con la entidad y no la lee."""
        for status in ("missing", "damaged"):
            with self.subTest(status=status), self.fresh() as project:
                table = self.entity_table(project)
                with project.write_transaction() as conn:
                    conn.execute("UPDATE gb_dataset SET status = ? WHERE locator = ?", (status, table))
                with self.assertRaises(DesignError) as caught:
                    entity_store.declared_sources(project, self.v1)
                self.assertNamesEntity(caught.exception, "des.entity_footprint_unusable")

    def test_d_renaming_the_attribute_does_not_change_what_the_declaration_consumes(self) -> None:
        """RF-008-21, B-2: cambiar el atributo ``name`` de la tabla de P2 (sin que la 008 lo haya detectado) no
        cambia el dato del que se alimenta la declaración —el ``des_epr_`` de la entidad, el que tiene registrado—:
        antes pedía el dato «des_epr_otro_nombre» y fallaba con «no está en el proyecto»."""
        with self.fresh() as project:
            table = self.entity_table(project)
            def consumed() -> list[tuple[str, str]]:
                return [(source.code, provenance.dataset_name(provenance.ENTITY_TABLE, source.calc_name))
                        for source in entity_store.declared_sources(project, self.v1)]

            before = consumed()
            self.assertEqual(before[1], (CODE, "des_epr_plataforma_de_taller"))
            self.qgis(project, table, f'UPDATE "{table}" SET name = ?', ("Otro nombre",))
            self.assertEqual(consumed(), before)
            chain = self.chain_of(project)
            self.assertIsNone(chain.failure)
            self.assertFalse(chain.declaration_changed)

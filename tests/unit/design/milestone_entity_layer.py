# SPDX-License-Identifier: GPL-3.0-or-later
"""Pruebas de hito de «test_entity_layer» (spec 015, T48; plan 015 §7.4): las clases que pesan,
movidas sin cambiar una aserción. El «verde» deja en ``test_entity_layer`` las más ligeras de cada
requisito; las de aquí las ejecuta el paso «hito» de ``tools/check.py --completo`` (la publicación
lo pide siempre).
"""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

import numpy as np

from tests.support import entity_fixtures as efx
from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender
from tests.unit.design import test_after_entity_change as chain_test
from tests.unit.design import test_entity_supports as sup
from tests.unit.design import test_platform_operation as ops
from tests.unit.design import test_platform_prepare as prep
from tests.unit.design.test_entity_layer import (
    ARROW,
    BY,
    DRAG,
    EDITOR,
    EntityState,
    GRADIENT,
    GUARD,
    LAYER,
    LOADING,
    LayerCase,
    NODATA,
    NO_READ_ONLY,
    OVER,
    START,
    TABLE,
    WHY,
    WORKSHOP,
    access,
    core_params,
    cstyles,
    design_params,
    design_store,
    entities,
    entity_layer,
    entity_store,
    export,
    gis_provenance,
    provenance,
    reader,
    recompute_mod,
    returned,
    versions_model,
)


class LayerStateTest(LayerCase):
    """RF-015-27, RF-015-29, RF-008-26 (T43; hallazgo E-4 de la verificación única, que incluye el C-11): la capa de
    entidades escribe el **estado** de cada entidad (al día, obsoleta, con el apoyo retirado, descartada) tal como lo
    deduce el grafo **en el momento de escribirla**; sin más, lo contradecía en cuanto el grafo cambiaba por una vía
    que no la regeneraba: tras **cambiar** un parámetro (la entidad queda obsoleta y la capa dice «al día»), tras
    **recalcular sin cambiar la salida** (RF-008-26: la capa, que no depende de nada que cambió, seguía diciendo
    «obsoleta»), tras **soltar un apoyo** (la 008 no recalcula lo que depende de ella) y tras **cancelar la cadena** (la
    entidad nueva no estaba en la capa, ni la tabla si era la primera). Ahora la capa se pone al día por esas vías o
    queda **marcada**: ``entity_store.layer_pending`` dice si no es lo que dice el registro y ``layer_sync_steps`` y
    ``layers_sync_steps`` la regeneran solo si hace falta.

    P1 (la «Plataforma de carga», del terreno, que **protege** con 4 m: es el caso típico de recalcular sin cambiar la
    salida, D-21) y el taller (P2, de otro terreno, que **declara** apoyarse en P1: no parte de su superficie, así
    que se puede dar por bueno sin ella), en el orden de las pruebas: (a) cambiar, (b) recalcular sin cambiar la
    salida, (c) cancelar la cadena y (d) soltar el apoyo. El punto de partida (la declaración, las máscaras y
    «Recalcular lo obsoleto» hasta no dejar nada) ya es el caso (b): la capa dice «obsoleta» sobre entidades al día,
    y se pone al día como lo hace ``bl``."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request(protect=True, guard_m=chain_test.GUARD_M))
        cls.made(prep.request(WORKSHOP, start=prep.HOLE_DATASET))
        cls.clock.advance(minutes=1)
        with cls.project.write_transaction() as conn:
            core_params.ParameterStore(cls.project).create(
                conn, design_params.entity_key("PLT-002", "supports"), "PLT-001", kind="ADOPTADO",
                source="Prueba de la T43", source_kind="person", decided_by=BY, reason="Dependencia declarada",
                version=cls.v1.uid)
        cls.recompute_entity("PLT-002")
        cls.chain()
        cls.settle()
        cls.clock.advance(minutes=1)
        assert tuple(returned(entity_store.layers_sync_steps(cls.project))) == ("V01",)

    @classmethod
    def recompute_entity(cls, code: str) -> None:
        """Repite la operación vigente de la entidad ``code`` con sus parámetros de ahora."""
        entry = entities.registry(cls.project, cls.v1.uid).get(code)
        ((settings,),) = cls.query_of("SELECT settings FROM gb_operation WHERE uid = ?", entry.operation_uid)
        request = recompute_mod.RecomputeRequest(cls.project, str(entry.operation_uid), provenance.PLATFORM,
                                                 json.loads(settings), (), (), version=cls.v1.uid)
        cls.clock.advance(minutes=1)
        _handle, work = design_store.recompute_run(request)
        sup.finish(work)

    def registry_states(self) -> dict[str, str]:
        """Lo que dice el registro (el grafo) de cada entidad que sale en la capa."""
        return {entry.record.code: str(entry.record.state)
                for entry in entities.registry(self.project, self.v1.uid)
                if entry.operation_uid is not None and entry.record.state in entity_layer.LAYER_STATES}

    def layer_states(self) -> dict[str, str]:
        """Lo que dice la capa."""
        return {code: str(row.state) for code, row in self.layer_rows().items()}

    def pending(self) -> bool:
        with self.project.read() as conn:
            return entity_store.layer_pending(self.project, conn, self.v1.uid)

    def sync(self) -> bool:
        """«Poner al día la capa si hace falta» hasta el final: si la regeneró."""
        self.clock.advance(minutes=1)
        return bool(returned(entity_store.layer_sync_steps(self.project, self.v1)))

    def sync_all(self) -> tuple[str, ...]:
        """«Poner al día la capa de cada versión que la tenga atrasada»: los códigos de las que regeneró."""
        self.clock.advance(minutes=1)
        return tuple(returned(entity_store.layers_sync_steps(self.project)))

    def test_a_after_changing_a_parameter_the_layer_says_what_the_registry_says(self) -> None:
        """RF-015-27, RF-015-16 (E-4): el punto de partida —capa y registro dicen «al día», nada pendiente—; cambiar
        la pendiente de P1 deja obsoletas a P1 y a P2 (la cascada de la 008) y **la capa sigue diciendo «al día»**: está
        marcada (``layer_pending``). Ponerla al día la deja como el registro, solo escribe si hace falta (la segunda
        vez no hace nada) y «Recalcular lo obsoleto» —que rehace la capa porque cambió la salida— la deja al día."""
        self.assertEqual(self.registry_states(), {"PLT-001": "current", "PLT-002": "current"})
        self.assertEqual((self.layer_states(), self.pending()), (self.registry_states(), False))
        self.change(GRADIENT, 0.5)
        self.assertEqual(self.registry_states(), {"PLT-001": "stale", "PLT-002": "stale"})
        self.assertEqual(self.layer_states(), {"PLT-001": "current", "PLT-002": "current"})
        self.assertTrue(self.pending(), "la capa dice «al día» y el registro, «obsoleta»")
        layer = self.current_layer()
        self.assertTrue(self.sync())
        self.assertNotEqual(self.current_layer(), layer)
        self.assertEqual((self.layer_states(), self.pending()), ({"PLT-001": "stale", "PLT-002": "stale"}, False))
        again = self.current_layer()
        self.assertFalse(self.sync(), "al día: no se escribe nada")
        self.assertEqual(self.current_layer(), again)
        self.settle()
        self.assertEqual(self.registry_states(), {"PLT-001": "current", "PLT-002": "current"})
        self.assertEqual((self.layer_states(), self.pending()), (self.registry_states(), False))

    def test_b_after_recomputing_without_changing_the_output_the_layer_is_marked_and_brought_up_to_date(self) -> None:
        """RF-015-27, RF-008-26 (E-4, el caso típico de la entidad que protege): cambiar el resguardo de P1 la deja
        obsoleta y lo que sigue a la orden (la declaración, las máscaras y la capa) deja la capa diciendo «obsoleta»;
        «Recalcular lo obsoleto» rehace P1 con la **misma salida** (los mismos hash), así que la 008 no toca la capa
        (no depende de nada que cambió): el registro dice «al día» y la capa **seguía diciendo «obsoleta»**. Está
        marcada y ``layers_sync_steps`` —lo que hace ``bl`` tras «Recalcular lo obsoleto»— la pone al día."""
        first = self.hashes_of(self.current("PLT-001"))
        self.change(GUARD, 6.0)
        self.assertEqual(self.registry_states()["PLT-001"], "stale")
        self.assertEqual(self.chain().layer_failure, None)
        self.assertEqual(self.layer_states()["PLT-001"], "stale")
        layer = self.current_layer()
        done = self.settle()
        self.assertEqual(self.hashes_of(self.current("PLT-001")), first, "la salida de P1 no cambia")
        types = [self.query("SELECT op_type FROM gb_operation WHERE uid = ?", uid)[0][0]
                 for result in done for uid in result.operations]
        self.assertIn(provenance.PLATFORM, types)
        self.assertNotIn(LAYER, types, "la 008 no rehace la capa: no depende de nada que cambió")
        self.assertEqual(self.current_layer(), layer)
        self.assertEqual(self.registry_states(), {"PLT-001": "current", "PLT-002": "current"})
        self.assertEqual(self.layer_states()["PLT-001"], "stale", "lo que dice la capa, sin ponerla al día")
        self.assertTrue(self.pending(), "marcada: no dice lo que el registro")
        self.assertEqual(self.sync_all(), ("V01",))
        self.assertEqual((self.layer_states(), self.pending()), (self.registry_states(), False))
        self.assertEqual(self.sync_all(), (), "sin nada que poner al día no se escribe")

    def test_c_closing_the_chain_before_the_layer_leaves_it_marked_and_it_is_brought_up_to_date_later(self) -> None:
        """RF-015-27, RF-015-29 (E-4): una entidad nueva (P3, de la superficie de P2) se crea y lo que sigue se cierra
        (Esc) justo antes de la capa: la entidad está creada y **no sale en la capa**; la capa está marcada
        (``layer_pending``) y ``layers_sync_steps`` (lo que hace ``bl`` tras «Recalcular lo obsoleto») la pone al día
        con las tres entidades."""
        self.made_confirmed(sup.asked(sup.DRAG, start="entity:PLT-002"))
        self.clock.advance(minutes=1)
        work = entity_store.after_entity_change(self.project, self.v1)
        try:
            for step in work:
                if "capa de entidades" in step.message:
                    break  # justo antes de escribirla
        finally:
            work.close()
        self.assertEqual(list(self.layer_rows()), ["PLT-001", "PLT-002"], "la entidad nueva no está en la capa")
        self.assertTrue(self.pending())
        self.assertEqual(self.sync_all(), ("V01",))
        self.assertEqual(list(self.layer_rows()), ["PLT-001", "PLT-002", "PLT-003"])
        self.assertEqual((self.layer_states(), self.pending()), (self.registry_states(), False))

    def test_d_giving_the_support_as_good_brings_the_layer_up_to_date_in_the_same_steps(self) -> None:
        """RF-015-27, RF-015-17, RF-008-26 (E-4): descartar P1 deja al taller con el «apoyo retirado» (la cadena de
        «Descartar» lo escribe en la capa); **darlo por bueno** (``release_support``) repite la operación con la misma
        salida y la 008 no recalcula nada de lo que dependía de ella: el registro pasa a «al día» y la capa **seguía
        diciendo «apoyo retirado»**. Los pasos de ``release_support`` terminan poniendo la capa al día: nada que
        hacer después y nada marcado."""
        self.clock.advance(minutes=1)
        ops.finish(entity_store.discard_entity_steps(self.project, self.v1.uid, "PLT-001", reason=WHY,
                                                     decided_by=BY))
        self.assertEqual(self.registry_states()["PLT-002"], "support_removed")
        self.assertEqual((self.layer_states(), self.pending()), (self.registry_states(), False))
        # Si la capa no se puede escribir (el disco), darlo por bueno ya está hecho —la operación y su evento—, el último
        # paso llega y la capa queda marcada: en una copia, antes de hacerlo de verdad.
        with efx.open_copy_of(self.project, self.clock, self.STEP_M) as (project, _clock):
            handle, work = entity_store.release_support(project, self.v1.uid, "PLT-002", "PLT-001", reason=WHY,
                                                        decided_by=BY)
            with mock.patch.object(entity_store, "entity_layer_steps", side_effect=OSError("disco lleno")),                     self.assertLogs("geoblender.design.entity_store", "WARNING"):
                self.assertIsNotNone(sup.finish(work))
            with project.read() as conn:
                self.assertEqual(conn.execute("SELECT status FROM gb_operation WHERE uid = ?",
                                              (handle.uid,)).fetchall(), [("done",)])
                self.assertEqual(conn.execute("SELECT count(*) FROM gb_event WHERE kind = 'support_released'"
                                              ).fetchone(), (1,))
                self.assertTrue(entity_store.layer_pending(project, conn, self.v1.uid), "la capa sigue marcada")
        self.clock.advance(minutes=1)
        handle, work = entity_store.release_support(self.project, self.v1.uid, "PLT-002", "PLT-001", reason=WHY,
                                                    decided_by=BY)
        steps = list(work)
        self.assertEqual([step.result is not None for step in steps], [False] * (len(steps) - 1) + [True],
                         "solo el último paso lleva el resultado (los de la capa, no: el modal acabaría con ellos)")
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE uid = ?", handle.uid), [("done",)])
        self.assertEqual(self.registry_states()["PLT-002"], "current")
        self.assertEqual((self.layer_states(), self.pending()), (self.registry_states(), False))

    def test_e_a_row_with_another_name_or_a_missing_one_marks_the_layer(self) -> None:
        """RF-015-27 (E-4): ``layer_pending`` compara el nombre y el estado de cada fila con el registro y que no sobre
        ni falte ninguna: en una copia del proyecto, la fila de P2 con otro nombre, sin la de P1 o con una fila de más
        (de lo que no está calculado) marcan la capa; la capa tal cual está, no."""
        with efx.open_copy_of(self.project, self.clock, self.STEP_M) as (project, _clock):
            def pending() -> bool:
                with project.read() as conn:
                    return entity_store.layer_pending(project, conn, self.v1.uid)

            def edit(sql: str, *args: Any) -> None:
                with project.write_transaction() as conn:
                    conn.execute(sql, args)

            self.assertFalse(pending())
            edit(f'UPDATE "{TABLE}" SET name = ? WHERE code = ?', "Otro nombre", "PLT-002")
            self.assertTrue(pending(), "otro nombre")
        with efx.open_copy_of(self.project, self.clock, self.STEP_M) as (project, _clock):
            with project.write_transaction() as conn:
                conn.execute(f'DELETE FROM "{TABLE}" WHERE code = ?', ("PLT-001",))
            with project.read() as conn:
                self.assertTrue(entity_store.layer_pending(project, conn, self.v1.uid), "falta una fila")
        with efx.open_copy_of(self.project, self.clock, self.STEP_M) as (project, _clock):
            with project.write_transaction() as conn:
                conn.execute(f'UPDATE "{TABLE}" SET code = ? WHERE code = ?', ("PLT-009", "PLT-001"))
            with project.read() as conn:
                self.assertTrue(entity_store.layer_pending(project, conn, self.v1.uid), "una fila de lo que no está")


class LayerTest(LayerCase):
    """RF-015-27, P-7: V01 con P1 («Plataforma de carga», del terreno), P2 («Sobre la carga», de la superficie de
    P1, «en corte y relleno»: se apoya en ella) y P3 («Arrastra el terreno», de la superficie de P2), en el orden
    de las pruebas."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.p1 = cls.made(prep.request())

    # --- (a) Crear -----------------------------------------------------------------------------------

    def test_a_creating_an_entity_puts_it_in_the_layer_with_everything_counted_by_hand(self) -> None:
        """RF-015-27: tras crear P1 y lo que sigue, ``des_enl_v01`` tiene **una** fila, la de P1: su código, su
        nombre, el tipo ``platform``, el estado «al día», de qué parte, **sin apoyo**, su cadena
        («partida → Plataforma de carga»), las cinco cifras de la operación (área, corte y relleno de la huella,
        corte y relleno del borde, de ``gb_figure``) y el contorno de su huella con el área de sus celdas a mano
        (1.000 celdas de 2 m: 4.000 m²)."""
        self.assertEqual(self.layer_operations(), [])
        chain = self.chain()
        self.assertIsNone(chain.failure)
        self.assertEqual((chain.layer, chain.layer_changed, chain.layer_failure), (1, True, None))
        rows = self.layer_rows()
        self.assertEqual(list(rows), ["PLT-001"])
        row = rows["PLT-001"]
        self.assertEqual((row.name, str(row.kind), row.state, row.start, row.supports),
                         (LOADING, "platform", EntityState.CURRENT, START, ""))
        self.assertEqual(row.chain, f"{START}{ARROW}{LOADING}")
        for column, key in (("area_m2", "des.plat_area_m2"), ("cut_m3", "des.plat_cut_m3"),
                            ("fill_m3", "des.plat_fill_m3"), ("edge_cut_m3", "des.edge_cut_m3"),
                            ("edge_fill_m3", "des.edge_fill_m3")):
            self.assertEqual(getattr(row, column), self.figure("PLT-001", key), column)
        self.assertEqual(row.area_m2, 4_000.0)
        self.assertEqual((row.layer, row.fid), (TABLE, 1))
        self.check_polygon("PLT-001", row)
        self.assertEqual(sorted(code for code in self.layer_rows()), ["PLT-001"])

    def test_b_the_operation_records_its_inputs_no_parameters_and_a_data_not_editable_by_hand(self) -> None:
        """RF-015-27, RF-008-56, RF-009-05, P-7: la operación ``des.entity_layer`` de V01, hecha, consume el
        ``des_epr_`` (papel ``entity``) y el ``des_prp_`` (papel ``entity_report``, de donde salen las cifras) de
        las entidades **vivas**, no lee ningún parámetro, deja en sus ajustes las entidades que recoge y escribe
        el dato ``des_enl`` (una capa de polígonos de ``des``, vigente, **no editable a mano**); y como la
        declaración, es una operación y una transacción aparte (la entidad ya estaba creada)."""
        uid = self.current_layer()
        epr, prp = (provenance.dataset_name(family, LOADING) for family in ("epr", "prp"))
        self.assertEqual(self.query(
            "SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'in' ORDER BY io.fid", uid),
            [(epr, "entity"), (prp, "entity_report")])
        self.assertEqual(self.query("SELECT key FROM gb_operation_param WHERE operation_uid = ?", uid), [])
        ((settings, status, message),) = self.query("SELECT settings, status, message FROM gb_operation "
                                                    "WHERE uid = ?", uid)
        self.assertEqual(json.loads(settings), provenance.entity_layer_settings([("PLT-001", LOADING)]))
        self.assertEqual(status, "done")
        self.assertIn("1", message)
        self.assertEqual(self.query(
            "SELECT d.name, d.kind, d.module, d.status, d.locator FROM gb_operation_io AS io JOIN gb_dataset AS d "
            "ON d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'out'", uid),
            [("des_enl", "vector", "des", "current", TABLE)])
        record = self.layer_record()
        self.assertFalse(record.qgis_editable)
        self.assertEqual(str(record.status), "current")
        self.assertEqual(self.query("SELECT role FROM gb_operation_io WHERE operation_uid = ? AND direction = 'out'",
                                    uid), [("entity_map",)])
        self.assertEqual(self.query("SELECT count(*) FROM gb_figure WHERE operation_uid = ?", uid), [(0,)])
        # La declaración y la capa son operaciones distintas, cada una en su revisión abierta.
        self.assertNotEqual(uid, self.current_declaration())

    def test_b_the_style_row_is_written_in_the_same_transaction_with_every_field_read_only(self) -> None:
        """RF-015-27, RF-012-20, RF-009-05: la operación escribe la fila de estilo por defecto de ``des_enl_v01``
        en ``layer_styles`` (la de ``core.constraints.styles``, T22) con **todas** las columnas de la tabla de
        verdad marcadas de solo lectura; repetir la capa no la duplica."""
        rows = self.style_rows(TABLE)
        self.assertEqual([row[:4] for row in rows], [(TABLE, "geom", cstyles.ENTITY_STYLE_NAME, 1)])
        with self.project.read() as conn:
            columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{TABLE}")') if row[1] != "geom"]
        self.assertEqual(columns, ["fid", *entity_layer.COLUMN_NAMES])
        root = ET.fromstring(rows[0][4].split("\n", 1)[1])
        (editable,) = root.iter("editable")
        self.assertEqual({field.get("name"): field.get("editable") for field in editable.iter("field")},
                         dict.fromkeys(columns, "0"))
        self.assertEqual(rows[0][4], cstyles.style_for(TABLE, columns).qml)

    def test_b_repeating_the_chain_changes_nothing_but_the_operation(self) -> None:
        """RF-015-27, P-7: repetir lo que sigue a la orden (sin cambiar nada) da **otra operación** que sustituye
        a la anterior (queda como historia) con los mismos bytes de la capa y el mismo hash, no duplica el
        estilo ni deja nada obsoleto."""
        before, digest, dump = self.current_layer(), self.layer_record().content_sha256, self.layer_dump()
        chain = self.chain()
        self.assertEqual((chain.layer, chain.layer_changed, chain.layer_failure), (1, False, None))
        self.assertNotEqual(self.current_layer(), before)
        self.assertEqual(self.query("SELECT superseded_by FROM gb_operation WHERE uid = ?", before),
                         [(self.current_layer(),)])
        self.assertEqual((self.layer_record().content_sha256, self.layer_dump()), (digest, dump))
        self.assertEqual(len(self.style_rows(TABLE)), 1)
        self.assertEqual(self.recompute_plan(), [])

    # --- (c) Crear otra, que se apoya en la primera -----------------------------------------------------

    def test_c_a_second_entity_that_rests_on_the_first_adds_its_row_with_what_it_rests_on(self) -> None:
        """RF-015-27, RF-015-15, RF-015-04: crear P2 («en corte y relleno» sobre la superficie de P1) la pone en
        la capa con su apoyo —«… (Plataforma): 8 000 m³ apoyados», el de ``entities.dependencies_of``—, y la
        cadena de las dos es la misma: «partida → Plataforma de carga → Sobre la carga»; P1 sigue sin apoyo y
        ya lleva su cadena entera. Las dos están al día."""
        self.made_over()
        chain = self.chain()
        self.assertEqual((chain.layer, chain.layer_changed), (2, True))
        rows = self.layer_rows()
        self.assertEqual(list(rows), ["PLT-001", "PLT-002"])
        first, second = rows["PLT-001"], rows["PLT-002"]
        expected = f"{START}{ARROW}{LOADING}{ARROW}{OVER}"
        self.assertEqual((first.chain, second.chain), (expected, expected))
        self.assertEqual((first.state, second.state), (EntityState.CURRENT, EntityState.CURRENT))
        self.assertEqual(first.supports, "")
        depends = [item for item in entities.dependencies_of(self.project, self.v1.uid, "PLT-002")
                   if "supported_on" in item.roles]
        self.assertEqual([item.name for item in depends], [LOADING])
        self.assertEqual(second.supports, "; ".join(item.text("es") for item in depends))
        self.assertIn(LOADING, second.supports)
        self.assertIn("m³ apoyados", second.supports)
        self.assertEqual((second.start, second.name), (LOADING, OVER), "parte de la superficie de P1: su nombre")
        self.check_polygon("PLT-002", second)
        self.assertEqual(self.recompute_plan(), [])

    # --- (d) Cambiar y recalcular ---------------------------------------------------------------------

    def test_d_changing_a_parameter_leaves_the_layer_stale_and_recomputing_brings_its_figures_up_to_date(self) -> None:
        """RF-015-27, RF-015-16, RF-008-24, RF-008-26: cambiar la pendiente de P1 deja obsoletas P1 y P2 (la
        cascada de la 008) **y la capa**, que las consume, con su causa; «Recalcular lo obsoleto» las rehace en
        orden —las entidades y, tras ellas, la capa (``recompute_entity_layer``)—: no queda nada obsoleto y las
        cifras de P1 y de P2 en la capa son las nuevas (las de ``gb_figure``). Como la salida de P1 cambia
        (las cifras), la capa no se salta aunque sus ``des_epr_`` no cambien."""
        stale_before = self.layer_dump()
        layer = self.current_layer()
        self.change(GRADIENT, 0.5)
        self.assertTrue(self.stale_causes(layer), "la capa consume lo que quedó obsoleto")
        self.assertIn((LAYER,), self.recompute_plan())
        done = self.settle()
        types = [self.query("SELECT op_type FROM gb_operation WHERE uid = ?", uid)[0][0]
                 for result in done for uid in result.operations]
        self.assertEqual(types.count(LAYER), 1, types)
        self.assertEqual(self.recompute_plan(), [])
        self.assertNotEqual(self.current_layer(), layer)
        self.assertNotEqual(self.layer_dump(), stale_before)
        rows = self.layer_rows()
        for code in ("PLT-001", "PLT-002"):
            with self.subTest(code=code):
                row = rows[code]
                self.assertEqual((row.state, row.cut_m3, row.fill_m3),
                                 (EntityState.CURRENT, self.figure(code, "des.plat_cut_m3"),
                                  self.figure(code, "des.plat_fill_m3")))
                self.assertEqual(row.edge_cut_m3, self.figure(code, "des.edge_cut_m3"))
        self.assertEqual(self.stale_causes(self.current_layer()), set())

    # --- (e) «Apoyo retirado» y descartar --------------------------------------------------------------

    def test_e_discarding_leaves_the_row_discarded_and_what_started_from_it_with_the_support_removed(self) -> None:
        """RF-015-27, RF-015-17, D-12: con P3 («Arrastra el terreno», de la superficie de P2) creada, descartar
        P2 la deja en la capa como **descartada** (sigue en el proyecto, con su huella) y deja a P3 con el
        **«apoyo retirado»**; P1 sigue al día. La capa se pone al día **dentro de la propia orden** (la cadena de
        «Descartar»): su contorno y sus cifras siguen siendo los de la entidad."""
        self.made_confirmed(sup.asked(DRAG, start="entity:PLT-002"))
        self.chain()
        before = self.layer_rows()["PLT-002"]
        self.assertEqual(self.layer_rows()["PLT-003"].state, EntityState.CURRENT)
        self.clock.advance(minutes=1)
        done = ops.finish(entity_store.discard_entity_steps(self.project, self.v1.uid, "PLT-002",
                                                            reason="Prueba de la T30", decided_by=EDITOR))
        self.assertEqual((done.chain.layer, done.chain.layer_failure), (3, None))
        rows = self.layer_rows()
        self.assertEqual({code: row.state for code, row in rows.items()},
                         {"PLT-001": EntityState.CURRENT, "PLT-002": EntityState.DISCARDED,
                          "PLT-003": EntityState.SUPPORT_REMOVED})
        self.assertEqual((rows["PLT-002"].area_m2, rows["PLT-002"].cut_m3), (before.area_m2, before.cut_m3))
        self.assertEqual([part[0].tobytes() for part in rows["PLT-002"].parts],
                         [part[0].tobytes() for part in before.parts])
        self.assertEqual(rows["PLT-003"].chain.split(ARROW)[-1], DRAG, "la cadena de la que perdió su apoyo")
        self.assertEqual(self.layer_record().content_sha256, self.query(
            "SELECT content_sha256 FROM gb_dataset WHERE name = 'des_enl' AND status = 'current'")[0][0])
        # La descartada no es entrada de la capa (sus datos están descartados); las vivas, sí.
        inputs = {name for (name,) in self.query(
            "SELECT d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'in'", self.current_layer())}
        self.assertNotIn(provenance.dataset_name("epr", OVER), inputs)
        self.assertIn(provenance.dataset_name("epr", LOADING), inputs)
        self.assertIn(provenance.dataset_name("epr", DRAG), inputs)

    # --- (f) Las «sin calcular» no salen ----------------------------------------------------------------

    def test_f_the_entities_not_calculated_have_no_geometry_and_are_not_in_the_layer(self) -> None:
        """RF-015-27 (las sin calcular no tienen geometría), RF-015-18: traer las entidades de V01 a V02 las
        deja **sin calcular** (parámetros sin operación): la capa de V02 no tiene ninguna fila (existe, vacía), y
        la de V01 no cambia."""
        before = self.layer_dump()
        brought = entity_store.bring_entities(self.project, self.v1, self.v2)
        self.assertTrue(brought.entities)
        listed = entities.registry(self.project, self.v2.uid)
        self.assertTrue(all(entry.record.state is EntityState.UNCALCULATED for entry in listed))
        self.clock.advance(minutes=1)
        stored = ops.finish(entity_store.entity_layer_steps(self.project, self.v2))
        self.assertEqual(stored.records[0].locator, "des_enl_v02")
        self.assertEqual(self.layer_rows(self.v2), {})
        self.assertEqual(self.query_of('SELECT count(*) FROM "des_enl_v02"'), [(0,)])
        self.assertEqual(self.layer_dump(), before)

    def test_g_without_an_editable_version_nothing_is_done(self) -> None:
        """RF-009-21: la capa se rechaza sin versión (``core.version_required``) o con una que no existe
        (``core.version_unknown``) y no escribe nada."""
        before = self.written()
        for version, code in ((None, "core.version_required"), ("V99", "core.version_unknown")):
            with self.subTest(version=version), self.assertRaises(versions_model.VersionError) as caught:
                ops.finish(entity_store.entity_layer_steps(self.project, version))
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(json.dumps(self.written(), default=str), json.dumps(before, default=str))


class LayerFailureTest(LayerCase):
    """RF-015-27, P-7: lo que pasa si la capa no se puede regenerar. P1 creada con su capa."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())
        cls.chain()

    def test_a_a_failed_regeneration_leaves_the_layer_stale_with_its_cause_and_recompute_redoes_it(self) -> None:
        """RF-015-27, P-7 (ADR-0030 §5): P1 cambia (su pendiente) y se recalcula **sola** (como una orden de
        entidades que no encadenó): la capa, que la consumía, queda obsoleta con su causa (otro contenido de su
        informe). Lo que sigue a la orden **falla** al escribir la capa (el disco): el fallo va en el resultado
        con su etapa y su aviso, la declaración y las máscaras **sí** se hicieron, la capa sigue como estaba
        —vigente, obsoleta, **con su causa**— y no queda ninguna operación «en curso»; el fallo no es un estado
        escondido: «Recalcular lo obsoleto» la rehace, con las cifras de ahora."""
        old_layer, dump = self.current_layer(), self.layer_dump()
        self.change(GRADIENT, 0.5)
        self.clock.advance(minutes=1)
        p1 = self.current("PLT-001")
        ops.finish(recompute_mod.recompute_steps(self.project, scope=p1))
        self.assertNotEqual(self.current("PLT-001"), p1)
        causes = self.stale_causes(old_layer)
        self.assertTrue(causes, "la capa consume el informe que cambió")
        self.assertIn("dataset_changed", {kind for kind, _name in causes})
        self.assertIn(provenance.dataset_name("prp", LOADING), {name for _kind, name in causes})
        with mock.patch.object(entity_store, "entity_layer_rows_steps", side_effect=OSError("disco lleno")):
            chain = self.chain()
        self.assertIsNone(chain.failure, "la declaración y las máscaras no fallaron")
        self.assertEqual((chain.layer, chain.layer_changed), (None, False))
        self.assertIs(chain.layer_failure.stage, entity_store.ChainStage.LAYER)
        self.assertIsInstance(chain.layer_failure.error, OSError)
        (warning,) = [item for item in chain.notices() if item.severity == "warning"]
        self.assertEqual(warning.code, "des.entity_chain_layer_failed")
        self.assertIn("disco lleno", warning.text("es"))
        self.assertIn("Recalcular lo obsoleto", warning.text("es"))
        self.assertEqual(self.current_layer(), old_layer, "la capa que había sigue vigente")
        self.assertEqual(self.layer_dump(), dump, "sin cambiar nada de lo escrito")
        self.assertEqual(self.stale_causes(old_layer), causes, "y obsoleta, con su causa")
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE op_type = ? ORDER BY fid DESC LIMIT 1",
                                    LAYER), [("failed",)], "el intento queda como historia, fallido")
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation WHERE status = 'running'"), [(0,)])
        self.assertEqual(chain.declared, 0)
        self.assertIs(self.state(), access.MaskState.CURRENT, "la declaración y las máscaras siguen al día")
        self.assertIn((LAYER,), self.recompute_plan())
        self.settle()
        self.assertEqual(self.recompute_plan(), [])
        self.assertNotEqual(self.current_layer(), old_layer)
        row = self.layer_rows()["PLT-001"]
        self.assertEqual((row.state, row.cut_m3, row.fill_m3),
                         (EntityState.CURRENT, self.figure("PLT-001", "des.plat_cut_m3"),
                          self.figure("PLT-001", "des.plat_fill_m3")))

    def test_b_a_failure_after_creating_an_entity_is_told_and_the_next_order_repairs_it(self) -> None:
        """RF-015-27, P-7: crear P2 y fallar la capa (el disco) cuenta el fallo —la entidad está creada— y la capa
        sigue sin P2; la orden siguiente de entidades la pone al día (una entidad nueva no es una entrada de la
        capa de antes: el grafo no la ve obsoleta, y por eso el aviso lo dice)."""
        self.made_over()
        with mock.patch.object(entity_store, "entity_layer_rows_steps", side_effect=OSError("disco lleno")):
            chain = self.chain()
        self.assertIsNotNone(chain.layer_failure)
        self.assertEqual(list(self.layer_rows()), ["PLT-001"])
        self.assertIn("la próxima vez", [item for item in chain.notices() if item.severity == "warning"][0].text("es"))
        repaired = self.chain()
        self.assertEqual((repaired.layer, repaired.layer_failure), (2, None))
        self.assertEqual(list(self.layer_rows()), ["PLT-001", "PLT-002"])

    def test_c_a_refused_layer_leaves_nothing_half_done_when_it_is_closed_midway(self) -> None:
        """RF-015-29, RF-015-27, P-7: cerrar lo que sigue a la orden (Esc) a mitad de la capa no deja la capa a
        medias: la operación queda cancelada, la capa vigente es la de antes y no hay ninguna «en curso»."""
        dump, layer = self.layer_dump(), self.current_layer()
        work = entity_store.after_entity_change(self.project, self.v1, budget_s=1e-9)
        for step in work:
            if step.message.startswith("Capa de entidades"):  # la operación de la capa ya empezó
                break
        else:  # pragma: no cover - lo asegura el presupuesto mínimo
            self.fail("la cadena no llegó a la capa de entidades")
        work.close()
        self.assertEqual(self.layer_dump(), dump)
        self.assertEqual(self.current_layer(), layer)
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation WHERE status = 'running'"), [(0,)])
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE op_type = ? ORDER BY fid DESC LIMIT 1",
                                    LAYER), [("cancelled",)])


class FirstLayerTest(LayerCase):
    """RF-015-27, RF-015-29 (E-4): una versión sin capa de entidades (la tabla ni existe) con una entidad calculada
    —lo que deja «Crear» si lo que sigue se cierra antes de escribir la primera capa— está **marcada**, y
    ``layers_sync_steps`` la crea."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())

    def test_a_without_its_table_the_layer_is_marked_and_it_is_created(self) -> None:
        with self.project.read() as conn:
            self.assertFalse(entity_store.layer_pending(self.project, conn, self.v2.uid), "V02: sin entidades, nada")
            self.assertIsNone(conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (TABLE,)).fetchone())
            self.assertTrue(entity_store.layer_pending(self.project, conn, self.v1.uid))
        self.clock.advance(minutes=1)
        self.assertEqual(tuple(returned(entity_store.layers_sync_steps(self.project))), ("V01",))
        self.assertEqual({code: str(row.state) for code, row in self.layer_rows().items()}, {"PLT-001": "current"})
        with self.project.read() as conn:
            self.assertFalse(entity_store.layer_pending(self.project, conn, self.v1.uid))

    def test_b_a_layer_that_cannot_be_written_does_not_stop_the_others(self) -> None:
        """RF-015-27: ``layers_sync_steps`` deja marcada y anota la capa que no se puede poner al día (aquí, V01: el disco)
        y sigue con las demás (V02) sin lanzar nada; devuelve solo las que regeneró."""
        progress = import_geoblender("core.project.model").Progress

        def sync(_project: Any, version: Any, **_options: Any) -> Any:
            if version.code == "V01":
                raise OSError("disco lleno")
            yield progress("entity_layer", 1, 1, "V02")
            return True

        with mock.patch.object(entity_store, "layer_pending", return_value=True),                 mock.patch.object(entity_store, "layer_sync_steps", sync),                 self.assertLogs("geoblender.design.entity_store", "WARNING") as logged:
            self.assertEqual(tuple(returned(entity_store.layers_sync_steps(self.project))), ("V02",))
        self.assertTrue(any("V01" in line and "sigue marcada" in line for line in logged.output), logged.output)


class LayerExportTest(LayerCase):
    """RF-015-27 (como RF-013-34): la superficie de P1 de V01 exportada a GeoTIFF."""

    out: ClassVar[Path]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())
        cls.out = cls.enterClassContext(project_tmp("gb-ex-"))

    def stored(self) -> Any:
        """La superficie guardada de P1 en V01, tal cual (float64, NaN sin dato)."""
        record = self.record(provenance.dataset_name("psf", LOADING), self.v1)
        return reader.read_geotiff(self.root.joinpath(*record.locator.split("/")), max_cells=sys.maxsize)

    def export(self, name: str = "carga.tif", **options: Any) -> Path:
        options.setdefault("read_only", NO_READ_ONLY)
        options.setdefault("version", self.v1.uid)
        return export.export_grid(self.project, provenance.ENTITY_SURFACE_GRID, LOADING, self.out / name,
                                  **options)

    def counts(self) -> tuple[int, ...]:
        return tuple(self.query(f"SELECT count(*) FROM {table}")[0][0]
                     for table in ("gb_operation", "gb_dataset", "gb_event"))

    def test_a_the_surface_of_an_entity_is_an_exportable_grid_found_by_its_name_or_uid(self) -> None:
        """RF-015-27, RF-013-34: ``des_psf_`` es una rejilla exportable (``export.GRIDS``); ``stored_grid`` la
        encuentra por su nombre o por su uid —su familia, el nombre de su operación y su versión— y también desde la
        tabla de la entidad (``des_epr_``, la que enseña la vista); una tabla que no es de una entidad, un dato que
        no existe o descartado, no."""
        self.assertIn(provenance.ENTITY_SURFACE_GRID, export.GRIDS)
        dataset = provenance.dataset_name("psf", LOADING)
        record = self.record(dataset, self.v1)
        for ref in (dataset, record.uid, provenance.dataset_name("epr", LOADING)):
            with self.subTest(ref=ref):
                found = export.stored_grid(self.project, ref, version=self.v1.uid)
                self.assertEqual((found.family, found.name, found.version_code, found.record.uid),
                                 (provenance.ENTITY_SURFACE_GRID, gis_provenance.dataset_slug(LOADING), "V01",
                                  record.uid))
        for ref in (provenance.dataset_name("prp", LOADING), "des_psf_no_existe", "des_epr_no_existe"):
            with self.subTest(ref=ref), self.assertRaises(import_geoblender("design.messages").DesignError) as caught:
                export.stored_grid(self.project, ref, version=self.v1.uid)
            self.assertEqual(caught.exception.code, "des.export_not_grid")

    def test_b_the_geotiff_is_georeferenced_in_the_project_crs_with_the_elevations_of_the_stored_surface(self) -> None:
        """RF-015-27, RF-013-34, RF-006-24: el GeoTIFF se lee de nuevo con ``gis`` con la rejilla de la superficie
        guardada, el CRS del proyecto (EPSG:25830) y su referencia vertical, el «sin dato» −9999 declarado y cada
        cota **igual a la guardada pasada a float32** (0 m de diferencia, y a media unidad de float32 de la de
        float64: el entregable es Float32 como los de la 013); los metadatos dicen su unidad, qué es, el dato y la
        versión."""
        stored = self.stored()
        path = self.export()
        found = reader.read_geotiff(path, max_cells=sys.maxsize)
        self.assertEqual(found.grid, stored.grid)
        self.assertEqual((found.declared_crs.epsg, found.declared_vertical.epsg),
                         (self.project.record.crs_epsg, self.project.record.vcrs_epsg))
        self.assertEqual((found.source_dtype, found.nodata_value), ("float32", NODATA))
        finite = np.isfinite(stored.values)
        self.assertTrue(finite.any())
        expected = np.where(finite, stored.values.astype(np.float32).astype(np.float64), np.nan)
        np.testing.assert_array_equal(found.values, expected)
        self.assertFalse((found.values == NODATA).any())
        half_unit = np.spacing(np.abs(stored.values[finite]).astype(np.float32)) / 2
        self.assertTrue((np.abs(found.values[finite] - stored.values[finite]) <= half_unit).all())
        tiff = import_geoblender("gis.geotiff.tiff")
        geokeys = import_geoblender("gis.geotiff.geokeys")
        with path.open("rb") as stream:
            ifd = tiff.read_first_ifd(stream, path.stat().st_size)
        self.assertEqual(geokeys.parse_gdal_items(ifd.text(tiff.GDAL_METADATA) or ""), {
            "UNIDAD": "m", "TIPO": "Superficie de la entidad",
            "DATO": provenance.dataset_name("psf", LOADING), "VERSION": "V01"})

    def test_c_exporting_writes_nothing_in_the_project_and_never_overwrites_without_asking(self) -> None:
        """RF-015-27, RF-013-34, D-29 de la 011: exportar no es una operación (ni operaciones, ni datos ni eventos
        nuevos, y ningún temporal); sobre un fichero que ya existe se rechaza (``gis.export_target_exists``) y
        queda como estaba, y solo con ``overwrite`` se sustituye, con los mismos bytes."""
        before = self.counts()
        other = self.export("otra.tif")
        self.assertEqual(self.counts(), before)
        original = other.read_bytes()
        gis_messages = import_geoblender("gis.messages")
        with self.assertRaises(gis_messages.GisError) as caught:
            self.export("otra.tif")
        self.assertEqual(caught.exception.code, "gis.export_target_exists")
        self.assertEqual(other.read_bytes(), original)
        self.export("otra.tif", overwrite=True)
        self.assertEqual(other.read_bytes(), original)
        self.assertEqual(sorted(path.name for path in self.out.iterdir()), ["carga.tif", "otra.tif"])
        self.assertEqual(self.counts(), before)

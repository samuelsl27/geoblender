# SPDX-License-Identifier: GPL-3.0-or-later
"""«Expandir banco…» y la capa propuesta ``des_pxb_`` con el proyecto (spec 018, T28; HU-018-2; RF-018-22, RF-018-23, RF-018-26, RF-015-02, RF-009-11, RF-008-21 y RF-008-56; plan 018 §5.2.3 «des.pit_expand»,
§5.4 A7, §5.7 P-12), como prueba de **hito**: ``check.py --completo`` la ejecuta; el «verde» tiene las suyas, sin proyecto, en ``test_pit_expand.py``.

Sobre el proyecto de las cortas (rejilla de 2 m, 200 × 200 celdas) con la corta ascendente ``Corta del fondo`` creada en V01:

- **Desde una corta calculada** (:class:`ExpandFromPitTest`, **en orden**): «Calcular» un paso sobre el pie del banco 1 no escribe nada y da **la cresta del banco 1 de la corta** (el mismo desfase del bucle)
  con su comprobación; descartarlo no deja nada; **crearlo** deja la capa ``des_pxb_`` editable (``qgis_editable``), con la operación, sus entradas y las dos cifras, y **ninguna** superficie ni entidad; la
  capa vale como banco fijado; **editada en QGIS** no se bloquea y deja obsoleta la expansión que parte de ella; repetir la expansión no la sobrescribe.
- **Desde una capa del proyecto** (:class:`ExpandFromLayerTest`): una línea de rotura con Z (el pie del banco 2) da su cresta; sus rechazos (abierta, no plana, sin tipo) nombran la capa y la línea.
- **Repetir y reproducir** (:class:`ExpandRecomputeTest`): repetirla sin cambiar nada da la misma capa bit a bit; un valor del perfil la deja obsoleta con su causa; la revisión congelada se reproduce **sin
  proyecto** con el mismo hash y las mismas cifras.
"""

from __future__ import annotations

import sqlite3
from typing import Any, ClassVar

import numpy as np

from tests.support import pit_data as pd
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.versions_fixtures import change_counter, files
from tests.unit.design.milestone_pit_create import BY, NAME
from tests.unit.design.milestone_pit_prepare_checks import EXPL, FLAT, request
from tests.unit.design.milestone_pit_recompute import FACE, RecomputeCase, finish_steps, recompute_function
from tests.unit.gis.masks.test_declared_blocked import core_operations_registered

core_datasets = import_geoblender("core.datasets.registry")
design_reproduce = import_geoblender("design.reproduce")
entities = import_geoblender("design.entities")
external = import_geoblender("core.datasets.external")
freeze = import_geoblender("core.versions.freeze")
gwkb = import_geoblender("core.gpkg.wkb")
messages = import_geoblender("design.messages")
pit_expand = import_geoblender("design.pit_expand")
pit_layer = import_geoblender("design.pit_layer")
pit_lines = import_geoblender("design.pit_lines")
pit_store = import_geoblender("design.pit_store")
provenance = import_geoblender("design.provenance")
reproduce_mod = import_geoblender("core.versions.reproduce")
road_model = import_geoblender("design.road_model")
steps = import_geoblender("design.steps")

PBL = provenance.dataset_name(provenance.PIT_POLYLINES_TABLE, NAME)
EXPANDED = "Cresta 1 expandida"
DATASET = provenance.dataset_name(provenance.PIT_EXPANDED_TABLE, EXPANDED)
TABLE = provenance.dataset_locator(provenance.PIT_EXPANDED_TABLE, EXPANDED, "V01")
BREAKLINE = "gis_brk_corta_banco_2"
OP = provenance.PIT_EXPAND


def ask(name: str, source: str, mode: str = "up", *, field: str = "name", **changes: Any) -> Any:
    values: dict[str, Any] = {"profile": EXPL, "arc_tol_m": pd.HYPOTHESES.arc_m, "simplify_m": pd.HYPOTHESES.simplify_m}
    values.update(changes)
    return pit_expand.ExpandRequest(name, road_model.LayerFields(source, field), mode, FLAT, **values)


class ExpandCase(RecomputeCase):
    """Lo de ``RecomputeCase`` con ``des.pit_expand`` registrado con sus funciones **reales** y las ayudas para expandir y editar fuera de Geoblender."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.enterClassContext(registered(provenance.operation_def(OP, recompute_function, design_reproduce.reproduce_pit_expand)))
        cls.enterClassContext(core_operations_registered())  # la comprobación de los datos registra la edición externa
        cls.clock.advance(minutes=1)
        cls.pit = cls.uid(cls, cls.calculate(cls, request()).create(decided_by=BY))

    @classmethod
    def expand_calc(cls, asked: Any) -> Any:
        """«Calcula» ``asked`` en V01: la ``Calculation`` (el último paso la lleva; nada registrado)."""
        cls.clock.advance(minutes=1)
        found = None
        for step in steps.pit_expand_run(cls.project, asked, version=cls.v1.uid, masks=cls.masks_v1):
            found = step.result
        assert found is not None
        return found

    @classmethod
    def expand_create(cls, asked: Any) -> Any:
        return cls.expand_calc(asked).create()

    def pit_line(self, bench: int, kind: str) -> np.ndarray:
        with self.project.read() as conn:
            lines = pit_lines.read_pit_lines(conn, provenance.dataset_locator(provenance.PIT_POLYLINES_TABLE, NAME, "V01"), provenance.PIT_POLYLINES_TABLE, closed_column="closed")
        return next(line for line in lines if (line.values[0], line.values[1]) == (bench, kind)).points

    def layer_rows(self, table: str = TABLE) -> list[tuple[Any, ...]]:
        return self.query(f'SELECT fid, geom, name, bench, kind, part, z_m, length_m FROM "{table}" ORDER BY fid')

    def record(self, name: str = DATASET) -> Any:
        with self.project.read() as conn:
            return core_datasets.get(conn, name, version_uid=self.v1.uid)

    def current_op(self, name: str) -> str:
        dataset = provenance.dataset_name(provenance.PIT_EXPANDED_TABLE, name)
        return str(self.query("SELECT o.uid FROM gb_operation AS o JOIN gb_operation_io AS io ON io.operation_uid = o.uid JOIN gb_dataset AS d ON d.uid = io.item_uid "
                              "WHERE o.op_type = ? AND d.name = ? AND io.direction = 'out' AND o.status = 'done' AND o.superseded_by IS NULL", OP, dataset)[0][0])

    def edit_outside(self, table: str, sql: str, *params: Any, moment: str) -> None:
        """Una edición de ``table`` hecha **fuera de Geoblender** (QGIS) y la comprobación de los datos que la ve."""
        conn = sqlite3.connect(self.project.database_path, isolation_level=None)
        try:
            conn.execute(sql, params)
            conn.execute("UPDATE gpkg_contents SET last_change = ? WHERE table_name = ?", (moment, table))
        finally:
            conn.close()
        finish_steps(external.external_check_steps(self.project))

    def type_of(self, uid: str) -> str:
        return str(self.query("SELECT op_type FROM gb_operation WHERE uid = ?", uid)[0][0])

    def stale_causes_of(self, uid: str) -> list[tuple[Any, ...]]:
        return self.query("SELECT cause_kind, subject_uid FROM gb_stale WHERE item_kind = 'operation' AND item_uid = ?", uid)


class ExpandFromPitTest(ExpandCase):
    """RF-018-22, RF-018-23, P-12: un paso sobre el pie del banco 1 de la corta calculada. **En orden** (``test_a`` a ``test_g``)."""

    calculation: ClassVar[Any]
    stored: ClassVar[Any]
    second: ClassVar[Any]

    def test_a_calculating_writes_nothing_and_gives_the_crest_of_bench_1_of_the_pit_with_its_check(self) -> None:
        """RF-018-22, RF-018-26, RF-015-03: «Calcular» no escribe nada (ni la base, ni ficheros) y da el banco siguiente: la **cresta del banco 1 de la corta** (el mismo desfase del bucle, a la
        misma cota), con la comprobación de inclinación que cumple, y las dos cifras (la del pie, ninguna)."""
        before = self.snapshot()
        type(self).calculation = calc = self.expand_calc(ask(EXPANDED, PBL, bench=1, kind="foot"))
        self.assertEqual(self.snapshot(), before, "«Calcular» ha escrito algo")
        self.assertEqual((calc.op_type, calc.name, calc.version, calc.open), (OP, EXPANDED, "V01", True))
        outcome = calc.outcome
        crest = self.pit_line(1, "crest")
        (found,) = outcome.polylines
        self.assertEqual((str(found.kind), found.bench), ("crest", 1))
        self.assertAlmostEqual(found.z_m, float(crest[0, 2]), delta=1e-9)
        self.assertEqual(len(found.vertices), len(crest))
        for point in found.vertices[:, :2]:  # cada vértice está en la cresta de la corta
            self.assertLess(float(np.hypot(*(crest[:, :2] - point).T).min()), 1e-6)
        self.assertTrue(calc.summary.slope_ok)
        self.assertEqual([figure.key for figure in calc.figures], ["des.pit_len_crest_m"])

    def test_b_discarding_leaves_nothing(self) -> None:
        """RF-015-29: descartar el cálculo no escribe ni borra nada y lo deja cerrado."""
        before = self.snapshot()
        self.calculation.discard()
        self.assertFalse(self.calculation.open)
        self.assertEqual(self.snapshot(), before)
        self.assertIsNone(self.record())

    def test_c_creating_leaves_the_editable_layer_the_operation_and_the_figures_and_nothing_else(self) -> None:
        """RF-018-22, P-12, RF-008-21: «Crear» deja **una** operación ``des.pit_expand`` hecha con la capa ``des_pxb_`` (una línea con la Z de la cresta, **editable en QGIS**), la corta, el perfil, la partida y
        las máscaras como entradas y la cifra con el ámbito de la operación; **ninguna superficie, entidad ni parámetro de entidad**, y la corta de la que sale no cambia."""
        entities_before = [entry.record.code for entry in entities.registry(self.project, self.v1.uid)]
        parameters_before = self.query("SELECT key, scope_uid FROM gb_parameter ORDER BY rowid")
        pit_hashes = self.hashes(PBL, FLAT)
        type(self).stored = stored = self.expand_create(ask(EXPANDED, PBL, bench=1, kind="foot"))
        uid = str(stored.handle.uid)
        self.assertEqual(self.query("SELECT op_type, scope, status FROM gb_operation WHERE uid = ?", uid), [(OP, "version", "done")])
        self.assertEqual([(name, role) for name, _locator, role, *_ in self.outputs(uid)], [(DATASET, "pit_expanded")])
        self.assertEqual([locator for _name, locator, *_ in self.outputs(uid)], [TABLE])
        record = self.record()
        self.assertTrue(record.qgis_editable)
        self.assertEqual(record.status.value, "current")
        (row,) = self.layer_rows()
        crest = self.pit_line(1, "crest")
        line = np.asarray(gwkb.decode_geometry(bytes(row[1]), external=True).coords, dtype=np.float64).reshape(-1, 3)
        self.assertTrue(bool((line[0] == line[-1]).all()), "un anillo cerrado")
        self.assertAlmostEqual(float(line[0, 2]), float(crest[0, 2]), delta=1e-9)
        self.assertEqual((row[2], row[3], row[4], row[5]), (EXPANDED, 1, "crest", 0))
        inputs = self.inputs(uid)
        for expected in ((PBL, provenance.PIT_POLYLINES_ROLE), (FLAT, provenance.SURFACE_ROLE)):
            self.assertIn(expected, inputs)
        figures = self.figures_of(uid)
        self.assertEqual([key for key, _value, _scope in figures], ["des.pit_len_crest_m"])
        self.assertAlmostEqual(figures[0][1], float(row[7]), delta=1e-9)
        self.assertEqual(figures[0][2], provenance.figure_scope(EXPANDED))
        self.assertEqual([entry.record.code for entry in entities.registry(self.project, self.v1.uid)], entities_before)
        self.assertEqual(self.query("SELECT key, scope_uid FROM gb_parameter ORDER BY rowid"), parameters_before)
        self.assertEqual(self.hashes(PBL, FLAT), pit_hashes)

    def test_d_the_layer_is_usable_as_a_fixed_bench(self) -> None:
        """RF-018-23: la capa ``des_pxb_`` es una de las capas de líneas con Z que acepta una corta como bancos fijados: la línea se lee **tal cual** (sus vértices con la Z, el banco por su campo ``bench``)."""
        asked = request("Corta con el banco expandido fijado", fixed=road_model.LayerFields(DATASET, "name"), fixed_field="bench")
        (fixed,) = pit_store._fixed_benches(self.project, self.v1, asked, "PIT-002")
        crest = self.pit_line(1, "crest")
        self.assertEqual((fixed.name, fixed.bench), (EXPANDED, 1))
        self.assertAlmostEqual(float(fixed.vertices[0, 2]), float(crest[0, 2]), delta=1e-9)

    def test_e_a_further_step_from_the_layer_and_editing_it_in_qgis_leaves_it_stale_with_its_cause(self) -> None:
        """RF-008-21, RF-008-56, P-12: una segunda expansión parte de la capa ``des_pxb_`` (el siguiente pie, hacia arriba); **editar la capa en QGIS no la bloquea** (queda vigente con el contenido nuevo,
        sigue ``qgis_editable``) y **deja obsoleta** la expansión que parte de ella, con su causa."""
        type(self).second = second = self.expand_create(ask("Pie 2 expandido", DATASET, bench=1, kind="crest"))
        uid = str(second.handle.uid)
        self.assertIn((DATASET, provenance.ENTITY_LAYER_ROLE), self.inputs(uid))
        self.assertEqual(self.stale_causes_of(uid), [])
        before = self.record()
        ((_fid, blob, *_rest),) = self.layer_rows()
        points = np.asarray(gwkb.decode_geometry(bytes(blob), external=True).coords, dtype=np.float64).reshape(-1, 3)
        moved = gwkb.encode_geometry("LINESTRING", points + np.array([0.0, 3.0, 0.0]), int(self.query("SELECT srs_id FROM gpkg_geometry_columns WHERE table_name = ?", TABLE)[0][0]), True)
        self.edit_outside(TABLE, f'UPDATE "{TABLE}" SET geom = ? WHERE fid = 1', moved, moment="2031-01-01T00:00:01.000Z")
        after = self.record()
        self.assertEqual(after.status.value, "current")
        self.assertNotEqual(after.content_sha256, before.content_sha256)
        self.assertTrue(after.qgis_editable)
        self.assertTrue(self.stale_causes_of(uid), "la expansión que parte de la capa queda obsoleta")

    def test_f_repeating_the_expansion_does_not_overwrite_what_was_drawn_in_qgis(self) -> None:
        """P-12, principio 7: repetir la expansión cuya capa se editó en QGIS **no la sobrescribe**: ``des.pit_expand_layer_edited`` al llamar, **sin escribir nada**; lo dibujado queda como estaba."""
        current = self.current_op(EXPANDED)
        drawn = self.layer_rows()
        before = (change_counter(self.root), files(self.root, skip=(), skip_dirs=("cache",)), self.query("SELECT uid, status FROM gb_operation ORDER BY rowid"))
        self.clock.advance(minutes=1)
        request_ = self.request_for(current)
        with self.assertRaises(messages.DesignError) as caught:
            recompute_function(request_)
        self.assertEqual(caught.exception.code, "des.pit_expand_layer_edited")
        for text in (caught.exception.text, caught.exception.text_in("en")):
            self.assertNotIn("{", text)
        self.assertEqual((change_counter(self.root), files(self.root, skip=(), skip_dirs=("cache",)), self.query("SELECT uid, status FROM gb_operation ORDER BY rowid")), before)
        self.assertEqual(self.layer_rows(), drawn)

    def test_g_a_name_already_used_is_refused_and_a_closed_generator_leaves_nothing(self) -> None:
        """RF-015-29: el nombre de una expansión ya hecha se rechaza al avanzar (``des.operation_name_repeated``) y cerrar el generador a mitad no deja nada."""
        with self.assertRaises(messages.DesignError) as caught:
            self.expand_calc(ask(EXPANDED, PBL, bench=1, kind="foot"))
        self.assertEqual(caught.exception.code, "des.operation_name_repeated")
        before = self.snapshot()
        work = steps.pit_expand_run(self.project, ask("Cerrada a mitad", PBL, bench=1, kind="foot"), version=self.v1.uid, masks=self.masks_v1)
        next(work)
        work.close()
        self.assertEqual(self.snapshot(), before)


class ExpandFromLayerTest(ExpandCase):
    """RF-018-22, RF-018-24: un paso sobre una línea de rotura con Z (el pie del banco 2) y sus rechazos."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.foot = cls.pit_line(cls, 2, "foot")
        sdata.write_breaklines(cls.project, cls.clock, BREAKLINE, [np.vstack([cls.foot, cls.foot[:1]])])
        flat = cls.foot.copy()
        flat[0, 2] += 1.0
        sdata.write_breaklines(cls.project, cls.clock, "gis_brk_no_plana", [np.vstack([flat, flat[:1]])])
        sdata.write_breaklines(cls.project, cls.clock, "gis_brk_abierta", [cls.foot])
        cls.clock.advance(minutes=1)

    def refused(self, asked: Any) -> Any:
        with self.assertRaises(messages.DesignError) as caught:
            self.expand_calc(asked)
        self.assertEqual(caught.exception.code, "des.pit_expand_source")
        for text in (caught.exception.text, caught.exception.text_in("en")):
            self.assertNotIn("{", text)
        return caught.exception

    def test_a_the_foot_of_a_layer_gives_its_crest_and_the_layer_is_not_modified(self) -> None:
        """RF-018-22, principio 7: el pie de la línea de rotura da su cresta (la del banco 2 de la corta); la capa es una **entrada** (``entity_layer``) y su hash es el mismo antes y después."""
        before = self.hashes(BREAKLINE)
        stored = self.expand_create(ask("Cresta de la línea", BREAKLINE, field="line_id", feature="1", kind="foot", bench=2))
        crest = self.pit_line(2, "crest")
        (row,) = self.layer_rows(provenance.dataset_locator(provenance.PIT_EXPANDED_TABLE, "Cresta de la línea", "V01"))
        line = np.asarray(gwkb.decode_geometry(bytes(row[1]), external=True).coords, dtype=np.float64).reshape(-1, 3)
        self.assertAlmostEqual(float(line[0, 2]), float(crest[0, 2]), delta=1e-9)
        self.assertEqual((row[3], row[4]), (2, "crest"))
        self.assertIn((BREAKLINE, provenance.ENTITY_LAYER_ROLE), self.inputs(str(stored.handle.uid)))
        self.assertEqual(self.hashes(BREAKLINE), before)

    def test_b_the_refusals_name_the_layer_and_the_line(self) -> None:
        """RF-018-24: una línea abierta, una que no es plana, una sin tipo y una que no existe se rechazan con la capa, la línea y el motivo, sin escribir nada."""
        before = self.snapshot()
        for source, changes, reason in (("gis_brk_abierta", {"feature": "1", "kind": "foot"}, "abierta"), ("gis_brk_no_plana", {"feature": "1", "kind": "foot"}, "plana"),
                                        (BREAKLINE, {"feature": "1"}, "pie o una cresta"), (BREAKLINE, {"feature": "9", "kind": "foot"}, "ninguna línea")):
            with self.subTest(source=source, changes=changes):
                error = self.refused(ask("Rechazada", source, field="line_id", **changes))
                self.assertIn(source, error.text)
                self.assertIn(reason, error.text)
        self.assertEqual(self.snapshot(), before)


class ExpandRecomputeTest(ExpandCase):
    """RF-018-22, RF-015-02, RF-009-11: repetir y reproducir la expansión. **En orden** (``test_a`` a ``test_c``)."""

    stored: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.stored = cls.expand_create(ask(EXPANDED, PBL, bench=1, kind="foot"))

    def test_a_recomputing_without_changing_anything_gives_the_same_layer_and_figures_bit_for_bit(self) -> None:
        """RF-015-02: «Recalcular» sin haber cambiado nada es **una operación nueva que sustituye a la anterior**, **la misma capa bit a bit** (hash y filas) y las mismas cifras con su ámbito."""
        uid = str(self.stored.handle.uid)
        layer, figures, rows = self.outputs(uid), self.figures_of(uid), self.layer_rows()
        self.clock.advance(minutes=1)
        new = str(recompute_function(self.request_for(uid)).uid)
        self.assertNotEqual(new, uid)
        self.assertEqual(self.query("SELECT supersedes_uid FROM gb_operation WHERE uid = ?", new)[0][0], uid)
        self.assertEqual([tuple(row) for row in self.outputs(new)], [tuple(row) for row in layer])
        self.assertEqual(self.figures_of(new), figures)
        self.assertEqual(self.layer_rows(), rows)

    def test_b_a_changed_profile_value_makes_it_stale_and_recomputing_repeats_it(self) -> None:
        """RF-015-02, RF-008-26: cambiar un valor del perfil (el ángulo de cara) deja obsoleta la expansión **con su causa** y «Recalcular lo obsoleto» la repite con el nuevo: otra longitud de berma."""
        current = self.current_op(EXPANDED)
        before = self.layer_rows()
        self.change(FACE, 50.0)
        self.assertTrue(self.stale_causes_of(current), "la expansión queda obsoleta")
        self.clock.advance(minutes=1)
        done = [uid for uid in self.recompute_all() if self.type_of(uid) == OP]
        self.assertEqual(len(done), 1)
        self.assertEqual(self.stale_causes_of(done[0]), [])
        self.assertNotEqual(self.layer_rows()[0][1], before[0][1])

    def test_c_reproducing_the_frozen_revision_gives_the_same_hash_and_figures_without_writing(self) -> None:
        """RF-009-11: reproducir ``V01.r1`` —sin proyecto, desde la capa de partida, la partida, las máscaras y los valores congelados— da el **mismo hash** de la capa y **las mismas cifras**, sin escribir."""
        uid = self.current_op(EXPANDED)
        revision = str(finish_steps(freeze.freeze_steps(self.project, self.v1.uid, reason="Entrega de la prueba")).frozen.uid)
        self.clock.advance(minutes=1)
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        report = finish_steps(reproduce_mod.reproduce_steps(self.project, revision))
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root)), before, "reproducir no escribe en el proyecto")
        mine = [check for check in report.outputs if check.operation_uid == uid]
        self.assertEqual([check.role for check in mine], ["pit_expanded"])
        self.assertTrue(all(check.same for check in mine), mine)
        found = [check for check in report.figures if check.operation_uid == uid]
        self.assertEqual(len(found), 1)
        self.assertTrue(all(check.same for check in found), found)


if __name__ == "__main__":
    import unittest

    unittest.main()

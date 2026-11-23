# SPDX-License-Identifier: GPL-3.0-or-later
"""Las capas de cortas con el proyecto (spec 018, T27; HU-018-4; RF-018-33, RF-015-27, RF-008-26, RF-008-56 y RF-009-05; D-19; plan 018 §5.2.3 y §5.3.2), como prueba de **hito**: ``check.py --completo`` la
ejecuta; el «verde» tiene las suyas, sin proyecto, en ``test_pit_layer.py``.

Sobre el proyecto de las cortas (rejilla de 2 m, 200 × 200 celdas), con las funciones **reales** de recalcular de las entidades y de las capas de cortas (las que registra ``bl``):

- **Las capas reflejan las cortas** (:class:`PitLayerTest`, **en orden**): (a) tras lo que sigue a las órdenes (``after_entity_change``) hay una fila por polilínea de la corta calculada con **la Z de cada vértice
  igual a la de su ``des_pbl_``** (sus bytes), su tipo, banco, cota, zona, sector y longitud, y una por línea de cielo con la de su ``des_psk_``; (b) su operación (entradas, ajustes, **dos datos no editables a
  mano** y su estilo por tipo); (c) repetirla da **los mismos bytes con las mismas filas**; (d) una segunda corta y **descartar** la primera: sale **descartada** (atenuada) y deja de ser entrada; (e) cambiar
  el perfil deja obsoletas la corta y las capas, con su causa, y «Recalcular lo obsoleto» las rehace y las deja diciendo lo que el registro (RF-008-26).
- **Los fallos** (:class:`PitLayerFailureTest`): si la regeneración falla, **la corta está creada**, las capas conservan lo que tenían y el aviso lo dice.
- **La exportación** (:class:`PitExportTest`): la superficie de la corta a GeoTIFF (RF-013-34) y los hallazgos a CSV, sin escribir nada en el proyecto.
"""

from __future__ import annotations

import csv
import io
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

import numpy as np

from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.versions_fixtures import change_counter
from tests.unit.design.milestone_pit_cascade import CascadeCase
from tests.unit.design.milestone_pit_create import BY, NAME
from tests.unit.design.milestone_pit_prepare_checks import CODE, request
from tests.unit.design.milestone_pit_recompute import FACE, recompute_function
from tests.unit.gis.masks.test_declared_blocked import core_operations_registered

dataset_registry = import_geoblender("core.datasets.registry")
design_export = import_geoblender("design.export")
paths = import_geoblender("core.paths")
reader = import_geoblender("gis.geotiff.reader")
surfaces = import_geoblender("design.surfaces")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
messages = import_geoblender("design.messages")
pit_layer = import_geoblender("design.pit_layer")
pit_lines = import_geoblender("design.pit_lines")
provenance = import_geoblender("design.provenance")
recompute_mod = import_geoblender("core.provenance.recompute")
store = import_geoblender("design.store")

EntityState = entities.EntityState
NO_READ_ONLY = paths.ReadOnlyDirs.from_sources(None, [])
PIT_TABLE = "des_pit_v01"
SKY_TABLE = "des_sky_v01"
LAYER = provenance.PIT_LAYER
SECOND_PIT = "Segunda corta de la capa"
WHY = "La corta se hace por otro camino"


class LayerCase(CascadeCase):
    """Lo que miran todas las pruebas de las capas: sus filas, su operación, lo que dice el registro y lo que hace ``bl`` tras «Recalcular lo obsoleto»."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.enterClassContext(registered(provenance.operation_def(LAYER, recompute_function)))  # la función real de recalcular que registra ``bl``
        cls.enterClassContext(core_operations_registered())  # la comprobación de los datos registra la edición externa

    def layer_rows(self) -> dict[tuple[str, int], Any]:
        with self.project.read() as conn:
            return {(item.code, item.ordinal): item for item in pit_layer.read_pit_layer(conn, PIT_TABLE)}

    def sky_rows(self) -> list[Any]:
        with self.project.read() as conn:
            return list(pit_layer.read_sky_layer(conn, SKY_TABLE))

    def layer_dump(self) -> list[tuple[Any, ...]]:
        return self.query(f'SELECT * FROM "{PIT_TABLE}" ORDER BY fid') + self.query(f'SELECT * FROM "{SKY_TABLE}" ORDER BY fid')

    def layer_operations(self) -> list[tuple[Any, ...]]:
        return self.query("SELECT o.uid, o.status, o.superseded_by FROM gb_operation AS o JOIN gb_revision AS r ON r.uid = o.revision_uid WHERE r.version_uid = ? AND o.op_type = ? ORDER BY o.fid",
                          self.v1.uid, LAYER)

    def current_layer(self) -> str:
        found = [uid for uid, status, replaced in self.layer_operations() if status == "done" and replaced is None]
        assert len(found) == 1, found
        return str(found[0])

    def layer_record(self) -> Any:
        with self.project.read() as conn:
            return dataset_registry.get(conn, provenance.dataset_name(provenance.PIT_LAYER_TABLE), version_uid=self.v1.uid)

    def registry_states(self) -> dict[str, str]:
        return {entry.record.code: str(entry.record.state) for entry in entities.registry(self.project, self.v1.uid)
                if entry.record.kind == entities.EntityKind.PIT and entry.operation_uid is not None and entry.record.state in pit_layer.LAYER_STATES}

    def layer_states(self) -> dict[str, str]:
        return {code: str(row.state) for (code, _ordinal), row in self.layer_rows().items()}

    def pending(self) -> bool:
        with self.project.read() as conn:
            return bool(pit_layer.pit_layer_pending(self.project, conn, self.v1.uid))

    @classmethod
    def after_chain(cls) -> Any:
        cls.clock.advance(minutes=1)
        found = None
        for step in entity_store.after_entity_change(cls.project, cls.v1.uid):
            found = step.result if step.result is not None else found
        return found

    def after(self) -> Any:
        return self.after_chain()

    def sync_all(self) -> tuple[str, ...]:
        self.clock.advance(minutes=1)
        work = entity_store.layers_sync_steps(self.project)
        while True:
            try:
                next(work)
            except StopIteration as stop:
                return tuple(stop.value)  # type: ignore[no-any-return]

    def recompute_all_pits(self) -> None:
        """Repite solo las cortas obsoletas (la operación ``des.pit``), no las capas: lo que haría «Recalcular lo obsoleto» antes de que ``bl`` ponga al día las capas."""
        for uid, op_type in self.query("SELECT o.uid, o.op_type FROM gb_operation AS o JOIN gb_stale AS s ON s.item_uid = o.uid WHERE o.op_type = ? AND o.superseded_by IS NULL", provenance.PIT):
            handle, work = store.recompute_run(self.request_for(str(uid)))
            for _step in work:
                pass

    def polylines_of(self, name: str) -> tuple[Any, ...]:
        with self.project.read() as conn:
            return pit_lines.read_pit_lines(conn, provenance.dataset_locator(provenance.PIT_POLYLINES_TABLE, name, "V01"), provenance.PIT_POLYLINES_TABLE, closed_column="closed")

    def skyline_of(self, name: str) -> tuple[Any, ...]:
        with self.project.read() as conn:
            return pit_lines.read_pit_lines(conn, provenance.dataset_locator(provenance.PIT_SKYLINE_TABLE, name, "V01"), provenance.PIT_SKYLINE_TABLE)


class PitLayerTest(LayerCase):
    """RF-018-33, RF-015-27, RF-009-05, RF-008-56, D-19: las capas con una corta, una segunda y la primera descartada. **En orden** (``test_a`` a ``test_d``): cada una parte de lo que dejó la anterior."""

    chain_result: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.clock.advance(minutes=1)
        cls.uid(cls, cls.calculate(cls, request()).create(decided_by=BY))
        cls.chain_result = cls.after_chain()

    def test_a_there_is_a_row_per_polyline_with_the_level_in_the_z_of_every_vertex(self) -> None:
        """RF-018-33, RF-015-27: tras lo que sigue a las órdenes hay **una fila por polilínea de la corta calculada** con su tipo, banco, zona, sector, parte, cota y longitud, y **la Z de cada vértice
        es la de su ``des_pbl_``** (la x, la y y la cota, ni un bit de menos; el anillo, cerrado); una por línea de cielo con la de su ``des_psk_``; lo que dice la cadena: una corta, el contenido **cambió** y
        nada falló."""
        self.assertEqual((self.chain_result.pit_layer, self.chain_result.pit_layer_changed, self.chain_result.pit_layer_failure), (1, True, None))
        self.assertEqual([notice.code for notice in self.chain_result.notices() if notice.code.startswith("des.pitlayer")], [])
        source = self.polylines_of(NAME)
        rows = self.layer_rows()
        self.assertEqual(len(rows), len(source), "una fila por polilínea (esta corta no tiene rampas)")
        self.assertEqual({code for code, _ordinal in rows}, {CODE})
        for line in source:
            bench, kind, zone, sector, part, ordinal, closed, fixed, z_m, length_m = line.values
            row = rows[CODE, ordinal]
            self.assertEqual((row.name, str(row.state), row.layer, row.bench, row.kind, row.zone, row.sector, row.part, row.fixed, row.z_m, row.length_m),
                             (NAME, "current", PIT_TABLE, bench, kind, zone, sector, part, fixed, z_m, length_m))
            wanted = np.vstack([line.points, line.points[:1]]) if closed else line.points
            self.assertEqual(row.points.tobytes(), np.asarray(wanted, dtype=np.float64).tobytes(), "la Z de cada vértice es la cota guardada de la polilínea")
        self.assertEqual({row.kind for row in rows.values()}, {"foot", "crest"})
        sky = self.sky_rows()
        self.assertEqual([(row.code, row.part, str(row.state)) for row in sky], [(CODE, part, "current") for part in range(1, len(sky) + 1)])
        for row, line in zip(sky, self.skyline_of(NAME), strict=True):
            self.assertEqual((row.points.tobytes(), row.length_m), (np.asarray(line.points, dtype=np.float64).tobytes(), line.values[1]))
        self.assertEqual(set(self.layer_states().values()), {"current"})
        self.assertFalse(self.pending())

    def test_b_the_operation_records_its_inputs_two_data_not_editable_by_hand_and_the_style(self) -> None:
        """RF-018-33, RF-008-56, RF-009-05: la operación ``des.pit_layer`` es de la versión, está hecha, **no es reproducible**, anota como entradas las polilíneas, la línea de cielo y las rampas de la corta
        (con sus papeles) y las cortas que enseña en sus ajustes, y escribe **dos datos** (``des_pit`` y ``des_sky``) **no editables a mano** con su estilo por tipo."""
        uid = self.current_layer()
        self.assertEqual(self.query("SELECT op_type, scope, status FROM gb_operation WHERE uid = ?", uid), [(LAYER, "version", "done")])
        self.assertEqual(sorted(self.inputs(uid)), sorted([(provenance.dataset_name(family, NAME), role) for family, role in (
            (provenance.PIT_POLYLINES_TABLE, provenance.PIT_POLYLINES_ROLE), (provenance.PIT_SKYLINE_TABLE, provenance.PIT_SKYLINE_ROLE), (provenance.PIT_RAMPS_TABLE, provenance.PIT_RAMPS_ROLE))]))
        self.assertEqual(self.settings_of(uid), {"entities": [{"code": CODE, "name": NAME}]})
        self.assertEqual(self.outputs(uid), [(provenance.dataset_name(provenance.PIT_LAYER_TABLE), PIT_TABLE, provenance.PIT_LAYER_ROLE),
                                             (provenance.dataset_name(provenance.PIT_SKY_LAYER_TABLE), SKY_TABLE, provenance.PIT_SKY_LAYER_ROLE)])
        self.assertEqual(self.query("SELECT qgis_editable FROM gb_dataset WHERE name IN ('des_pit', 'des_sky') AND status = 'current' ORDER BY name"), [(0,), (0,)])
        styles = dict(self.query("SELECT f_table_name, styleName FROM layer_styles WHERE f_table_name IN (?, ?)", PIT_TABLE, SKY_TABLE))
        self.assertEqual(styles, {PIT_TABLE: "Polilíneas de cortas", SKY_TABLE: "Línea de cielo de cortas"})
        self.assertNotIn(LAYER, provenance.PIT_REPRODUCIBLE)

    def test_c_repeating_it_gives_the_same_bytes_and_replaces_the_previous_one(self) -> None:
        """RF-018-33, RF-009-05: repetirla con las mismas cortas da **los mismos bytes** y el mismo hash de contenido y **sustituye** a la anterior (una sola vigente)."""
        before_dump, before_hash, before_uid = self.layer_dump(), self.layer_record().content_sha256, self.current_layer()
        result = self.after()
        self.assertEqual((result.pit_layer, result.pit_layer_changed), (1, False))
        self.assertEqual(self.layer_dump(), before_dump)
        self.assertEqual(self.layer_record().content_sha256, before_hash)
        self.assertNotEqual(self.current_layer(), before_uid)
        self.assertEqual([status for _uid, status, replaced in self.layer_operations() if replaced is None], ["done"])

    def test_d_a_second_pit_is_shown_and_a_discarded_one_is_faded_and_stops_being_an_input(self) -> None:
        """RF-018-33, RF-015-27: una segunda corta añade sus filas (por código); **descartar** la primera deja sus filas con el estado «descartada» (atenuada en QGIS), **sale de las entradas** de la operación
        (sus datos están descartados) y sigue enseñando su geometría."""
        self.clock.advance(minutes=1)
        self.create_pit(SECOND_PIT, start="gis_dtm_corta_llano_c")
        result = self.after()
        self.assertEqual(result.pit_layer, 2)
        self.assertEqual(sorted({code for code, _ordinal in self.layer_rows()}), ["PIT-001", "PIT-002"])
        self.assertEqual({row.code for row in self.sky_rows()}, {"PIT-001", "PIT-002"})
        self.clock.advance(minutes=1)
        entity_store.discard_entity(self.project, self.v1.uid, CODE, reason=WHY, decided_by=BY)
        result = self.after()
        self.assertEqual(result.pit_layer, 2)
        states = self.registry_states()
        self.assertEqual(states["PIT-001"], "discarded")
        self.assertEqual(self.layer_states(), states, "las capas dicen lo que el registro (la segunda, obsoleta: otro diseño cambió)")
        self.assertEqual({row.code: str(row.state) for row in self.sky_rows()}, states)
        names = [name for name, _role in self.inputs(self.current_layer())]
        self.assertNotIn(provenance.dataset_name(provenance.PIT_POLYLINES_TABLE, NAME), names)
        self.assertIn(provenance.dataset_name(provenance.PIT_POLYLINES_TABLE, SECOND_PIT), names)
        self.assertEqual(self.settings_of(self.current_layer())["entities"], [{"code": "PIT-001", "name": NAME}, {"code": "PIT-002", "name": SECOND_PIT}])
        self.assertFalse(self.pending())


class PitLayerStateTest(LayerCase):
    """RF-018-33, RF-008-26: el estado de las capas es el del registro (hallazgo D-1 de la 016 con la corta): tras «Cambiar parámetro…» la capa puede quedar diciendo otro estado y se **marca**; lo que
    hace ``bl`` al terminar «Recalcular lo obsoleto» la pone al día."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.clock.advance(minutes=1)
        cls.uid(cls, cls.calculate(cls, request()).create(decided_by=BY))
        cls.after_chain()

    def test_a_a_stale_pit_marks_the_layer_and_syncing_brings_it_up_to_date(self) -> None:
        """RF-018-33: cambiar un parámetro de la corta la deja obsoleta por el grafo; la capa, que dice «al día», queda **marcada** (``pit_layer_pending``, ``marked_pits``); ``layers_sync_steps`` la regenera
        y la deja diciendo «obsoleta» como el registro y sin marca; sin cambios, no escribe ninguna operación."""
        self.assertEqual(self.sync_all(), (), "con las capas al día no se escribe nada")
        count = len(self.layer_operations())
        self.change(FACE, 52.0)
        self.assertEqual(self.registry_states(), {"PIT-001": "stale"})
        self.assertTrue(self.pending())
        with self.project.read() as conn:
            self.assertEqual(pit_layer.marked_pits(self.project, conn, self.v1.uid), ("PIT-001",))
        self.assertEqual(self.sync_all(), ("V01",))
        self.assertEqual(self.layer_states(), {"PIT-001": "stale"})
        self.assertFalse(self.pending())
        self.assertEqual(len(self.layer_operations()), count + 1)
        with self.project.read() as conn:
            self.assertEqual(pit_layer.marked_pits(self.project, conn, self.v1.uid), ())
        self.assertEqual(self.sync_all(), ())

    def test_b_the_layers_are_stale_with_their_cause_and_recomputing_brings_them_up_to_date(self) -> None:
        """RF-018-33, RF-008-26: tras el cambio del perfil, la corta y **las capas** quedan obsoletas con su causa (las capas consumen los datos de la corta); «Recalcular lo obsoleto» las rehace **en orden**
        (la corta y, después, las capas, que sustituyen a las anteriores) y las deja al día, diciendo lo que el registro y sin marca."""
        old_layer = self.current_layer()
        self.assertTrue(self.stale_causes(self.current("PIT-001")))
        self.assertTrue(self.stale_causes(old_layer), "las capas consumen los datos de la corta: quedan obsoletas con su causa")
        self.assertIn(provenance.PIT_LAYER, [item for unit in self.recompute_plan() for item in unit])
        self.clock.advance(minutes=1)
        self.recompute_all()
        self.assertEqual(self.recompute_plan(), [])
        self.assertEqual(self.registry_states(), {"PIT-001": "current"})
        self.assertEqual(self.layer_states(), {"PIT-001": "current"})
        self.assertFalse(self.pending())
        self.assertNotEqual(self.current_layer(), old_layer)
        self.assertEqual(self.stale_causes(self.current_layer()), set())
        self.assertEqual(self.sync_all(), ())


class PitLayerFailureTest(LayerCase):
    """RF-018-33, P-7: si la regeneración falla, la corta está creada y las capas conservan lo que tenían."""

    def test_a_a_failed_layer_is_told_the_pit_stays_created_and_the_next_order_repairs_it(self) -> None:
        """RF-018-33, P-7: si las capas no se pueden escribir (el disco), la corta **está creada**, lo que sigue lo cuenta (``pit_layer_failure`` y su aviso ``des.pitlayer_failed``, con el porqué), las
        capas quedan como estaban (aquí, sin ellas) y **marcadas**; la orden siguiente (``after_entity_change``) las repara."""
        self.clock.advance(minutes=1)
        self.uid(self.calculate(request()).create(decided_by=BY))
        with mock.patch.object(pit_layer, "pit_layer_steps", side_effect=OSError("disco lleno")):
            chain = self.after()
        self.assertIsNotNone(chain.pit_layer_failure)
        self.assertEqual(chain.pit_layer_failure.stage, entity_store.ChainStage.PIT_LAYER)
        notice = next(item for item in chain.notices() if item.code == "des.pitlayer_failed")
        self.assertIn("disco lleno", notice.values["reason"])
        self.assertIsNone(chain.pit_layer)
        self.assertIsNone(chain.layer_failure, "la capa de entidades es independiente")
        self.assertEqual(self.registry_states(), {"PIT-001": "current"}, "la corta está creada")
        self.assertIsNone(self.layer_record())
        self.assertTrue(self.pending())
        repaired = self.after()
        self.assertEqual((repaired.pit_layer, repaired.pit_layer_failure), (1, None))
        self.assertEqual((self.layer_states(), self.pending()), (self.registry_states(), False))

    def test_b_a_failed_regeneration_after_changing_the_pit_leaves_the_layers_stale_with_their_cause(self) -> None:
        """RF-018-33, RF-008-26: si la regeneración falla tras **cambiar** una corta que las capas enseñan, las capas **conservan lo que tenían** (los mismos bytes) y la 008 las da por **obsoletas con su
        causa** (consumen los datos de la corta que cambió: no se quedan diciendo «al día» sin avisar); la orden siguiente las repara."""
        self.assertEqual(self.registry_states(), {"PIT-001": "current"})
        before, layer = self.layer_dump(), self.current_layer()
        self.change(FACE, 51.0)
        self.clock.advance(minutes=1)
        self.recompute_all_pits()
        with mock.patch.object(pit_layer, "pit_layer_steps", side_effect=OSError("disco lleno")):
            chain = self.after()
        self.assertIsNotNone(chain.pit_layer_failure)
        self.assertEqual(self.current_layer(), layer, "las capas conservan lo que tenían")
        self.assertEqual(self.layer_dump(), before)
        self.assertTrue(self.stale_causes(layer), "las capas quedan obsoletas con su causa")
        self.assertTrue(self.pending() or self.stale_causes(layer))
        repaired = self.after()
        self.assertEqual((repaired.pit_layer, repaired.pit_layer_failure), (1, None))
        self.assertEqual(self.stale_causes(self.current_layer()), set())


class PitExportTest(LayerCase):
    """RF-018-33, RF-013-34: la superficie de la corta a GeoTIFF y sus hallazgos a CSV, sin escribir nada en el proyecto."""

    out: ClassVar[Path]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.clock.advance(minutes=1)
        cls.uid(cls, cls.calculate(cls, request()).create(decided_by=BY))
        cls.out = Path(cls.root).parent / f"{Path(cls.root).name}-exportado-corta"
        cls.out.mkdir(exist_ok=True)
        cls.addClassCleanup(shutil.rmtree, cls.out, ignore_errors=True)

    def test_a_the_surface_of_a_pit_is_exported_as_a_geotiff_equal_to_the_registered_one_without_touching_the_project(self) -> None:
        """RF-018-33, RF-013-34: la superficie de la corta (``des_psf_``), elegida por la tabla de su huella o por su dato, se exporta georreferenciada en el CRS del proyecto, con la misma rejilla y cada
        valor igual al registrado pasado a float32, sin modificar el proyecto."""
        for ref in (provenance.dataset_name(provenance.ENTITY_TABLE, NAME), provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, NAME)):
            with self.subTest(ref=ref):
                found = design_export.stored_grid(self.project, ref, version=self.v1.uid)
                self.assertEqual((found.family, found.version_code), (provenance.ENTITY_SURFACE_GRID, "V01"))
        counter = change_counter(self.root)
        target = self.out / "superficie_corta.tif"
        written = design_export.export_grid(self.project, found.family, found.name, target, version=self.v1.uid, read_only=NO_READ_ONLY, overwrite=True)
        grid = reader.read_geotiff(written, max_cells=sys.maxsize)
        surface = surfaces.read_surface_steps(self.project, provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, NAME), version_uid=self.v1.uid)
        while True:
            try:
                next(surface)
            except StopIteration as done:
                stored = done.value
                break
        self.assertEqual(grid.grid, stored.grid)
        self.assertEqual(grid.declared_crs.epsg, int(self.project.record.crs_epsg))
        finite = np.isfinite(stored.values)
        np.testing.assert_array_equal(grid.values, np.where(finite, stored.values.astype(np.float32).astype(np.float64), np.nan))
        self.assertEqual(change_counter(self.root), counter)

    def test_b_the_findings_are_exported_as_a_csv_with_the_columns_and_the_values_of_the_table(self) -> None:
        """RF-018-33, RF-018-26: los hallazgos (``des_pfn_``) se exportan a CSV (BOM de UTF-8, «;», CRLF y coma decimal) con una fila por hallazgo y los títulos de sus columnas, por el código o por el nombre
        de la corta, sin modificar el proyecto; una corta que no existe es ``des.export_pit_unknown`` y no escribe nada."""
        counter = change_counter(self.root)
        stored = self.table(NAME, provenance.PIT_FINDINGS_TABLE)
        for ref in (CODE, NAME):
            with self.subTest(ref=ref):
                target = self.out / f"hallazgos_{len(ref)}.csv"
                design_export.export_pit_findings_csv(self.project, ref, target, version=self.v1.uid, read_only=NO_READ_ONLY)
                data = target.read_bytes()
                self.assertTrue(data.startswith(b"\xef\xbb\xbf") and b"\r\n" in data)
                rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""), delimiter=";"))
                self.assertEqual(rows[0], list(design_export.PIT_FINDING_CSV_COLUMNS))
                self.assertEqual(len(rows) - 1, len(stored))
                for row, wanted in zip(rows[1:], stored, strict=True):
                    self.assertEqual((row[0], row[4], row[7]), (wanted["kind"], wanted["unit"], wanted["detail"]))
                    self.assertEqual(row[1], "" if wanted["bench"] is None else str(wanted["bench"]))
                    self.assertEqual(float(row[5].replace(",", ".")), wanted["x"])
        self.assertEqual(design_export.stored_pit_findings(self.project, CODE, version="V01").family, provenance.PIT_FINDINGS_TABLE)
        self.assertEqual(change_counter(self.root), counter)
        missing = self.out / "x.csv"
        with self.assertRaises(messages.DesignError) as caught:
            design_export.export_pit_findings_csv(self.project, "No existe", missing, version=self.v1.uid, read_only=NO_READ_ONLY)
        self.assertEqual(caught.exception.code, "des.export_pit_unknown")
        self.assertFalse(missing.exists())

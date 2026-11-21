# SPDX-License-Identifier: GPL-3.0-or-later
"""«Proponer el trazado» con el proyecto (spec 017, T27; HU-017-1 y HU-017-4; RF-017-28, RF-017-18, RF-017-02, RF-015-02, RF-009-11, RF-008-21 y RF-008-56; plan 017 §5.2.3 «des.road_propose», §5.7 P-8 y P-14;
D-19; decisión T27-a), como prueba de **hito**: ``check.py --completo`` la ejecuta; el «verde» tiene las suyas, sin proyecto, en ``test_road_propose.py``.

Sobre la copia del proyecto de las pistas (rejilla de 2 m, 200 × 200 celdas) con las máscaras de V01 y el perfil de referencia (**solo de las pruebas**):

- **Crear** (:class:`ProposeCreateTest`): la propuesta deja la capa ``des_rpl_<nombre>_<vNN>`` —una línea con la rasante en su Z—, las dos cifras y la operación con sus entradas y los parámetros del perfil, y
  **nada más**: ninguna superficie cambia (su hash antes y después), no hay entidad, ni parámetro de entidad, ni capa de ejes, y la capa de los puntos tampoco cambia.
- **La capa es del usuario** (:class:`ProposeEditableTest`, P-8, RF-008-21): editada fuera de Geoblender **no se bloquea** (queda vigente, con su contenido nuevo); **una pista «eje 3D» que la usa**, con su hash
  como entrada, **queda obsoleta si cambia su geometría** y se rehace con ella; y un cambio de **un campo** la deja obsoleta igual (el hash de ``core.gpkg_layer@1`` cuenta todas las columnas: el plan decía lo
  contrario y ya lo anotó la T14 de la 016, ``docs/trampas.md`` §6).
- **Recalcular** (:class:`ProposeRecomputeTest`, RF-015-02, RF-008-26): repetirla sin cambiar nada da la misma capa bit a bit y las mismas cifras; un valor del perfil la deja obsoleta con su causa y «Recalcular lo
  obsoleto» la repite; **y no sobrescribe lo que se dibujó en QGIS** (``des.route_layer_edited``, sin escribir nada).
- **Reproducir** (:class:`ProposeReproduceTest`, RF-009-11): una revisión congelada con la propuesta (y la de un destino por cota) se reproduce **sin proyecto** con el mismo hash y las mismas cifras.
"""

from __future__ import annotations

import sqlite3
from typing import Any, ClassVar

import numpy as np

from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.support.versions_fixtures import change_counter, files
from tests.unit.design.milestone_road_recompute import PROFILE_STEP, RecomputeCase, finish_steps, recompute_function
from tests.unit.design.test_road_prepare import RAMP, drive, request
from tests.unit.gis.masks.test_declared_blocked import core_operations_registered

core_datasets = import_geoblender("core.datasets.registry")
design_reproduce = import_geoblender("design.reproduce")
entities = import_geoblender("design.entities")
external = import_geoblender("core.datasets.external")
freeze = import_geoblender("core.versions.freeze")
gwkb = import_geoblender("core.gpkg.wkb")
messages = import_geoblender("design.messages")
provenance = import_geoblender("design.provenance")
recompute_mod = import_geoblender("core.provenance.recompute")
reproduce_mod = import_geoblender("core.versions.reproduce")
road_layer = import_geoblender("design.road_layer")
road_model = import_geoblender("design.road_model")
road_store = import_geoblender("design.road_store")
store = import_geoblender("design.store")

NAME = "Trazado A"
DATASET = "des_rpl_trazado_a"
TABLE = "des_rpl_trazado_a_v01"
ROAD_3D = "Pista sobre el trazado"
PROFILE_KEY_PREFIX = "des.roadprofile.pista_principal."


class ProposeCase(RecomputeCase):
    """Lo de ``RecomputeCase`` con el tipo ``des.road_propose`` registrado con sus funciones **reales** de recalcular y reproducir y las ayudas para proponer y editar fuera de Geoblender."""

    @classmethod
    def entity_definitions(cls) -> tuple[Any, ...]:
        return (*super().entity_definitions(), provenance.operation_def(provenance.ROAD_PROPOSE, recompute_function, design_reproduce.reproduce_road_propose))

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.enterClassContext(core_operations_registered())  # la comprobación de los datos registra la edición externa

    @classmethod
    def propose(cls, asked: Any) -> tuple[Any, Any, Any]:
        """«Propone» ``asked`` en V01 (un minuto después de lo anterior): lo preparado, lo calculado y lo guardado."""
        cls.clock.advance(minutes=1)
        prepared = road_store.prepare_propose(cls.project, asked, version=cls.v1.uid, masks=cls.masks_v1)
        outcome = drive(road_store.propose_compute_steps(prepared.job, surface=prepared.start_surface))
        with store.DesignWriter(cls.project, provenance.ROAD_PROPOSE, asked.name, version=cls.v1.uid) as writer:
            stored = road_store.create_propose(cls.project, writer, prepared, outcome)
        cls.clock.advance(minutes=1)
        return prepared, outcome, stored

    @classmethod
    def rows_of(cls, sql: str, *params: Any) -> list[tuple[Any, ...]]:
        """Las filas de la consulta ``sql`` (de lectura) del proyecto, para ``setUpClass``."""
        with cls.project.read() as conn:
            return [tuple(row) for row in conn.execute(sql, params).fetchall()]

    @classmethod
    def road_in_3d_axis(cls) -> Any:
        """Una pista «eje 3D» que toma como eje la línea con Z de la propuesta (``des_rpl_``), sobre la misma rampa."""
        asked = road_model.RoadRequest(ROAD_3D, road_model.LayerFields(DATASET, "name"), "axis_3d", "pista_principal", RAMP, feature=NAME)
        return cls.made(asked)[1]

    def record(self, name: str = DATASET) -> Any:
        with self.project.read() as conn:
            return core_datasets.get(conn, name, version_uid=self.v1.uid)

    def layer_rows(self) -> list[tuple[Any, ...]]:
        return self.query(f'SELECT fid, geom, name FROM "{TABLE}" ORDER BY fid')

    def edit_outside(self, sql: str, *params: Any, moment: str = "2031-01-01T00:00:01.000Z") -> None:
        """Una edición de ``TABLE`` hecha **fuera de Geoblender** (QGIS: su propia conexión y su ``last_change``) y la comprobación de los datos que la ve."""
        conn = sqlite3.connect(self.project.database_path, isolation_level=None)
        try:
            conn.execute(sql, params)
            conn.execute("UPDATE gpkg_contents SET last_change = ? WHERE table_name = ?", (moment, TABLE))
        finally:
            conn.close()
        finish_steps(external.external_check_steps(self.project))

    def move_line(self, moment: str) -> None:
        """Mueve la línea de la propuesta 3 m al norte (su geometría, **no** un campo) fuera de Geoblender."""
        ((_fid, blob, _name),) = self.layer_rows()
        points = np.asarray(gwkb.decode_geometry(bytes(blob), external=True).coords, dtype=np.float64).reshape(-1, 3)
        moved = gwkb.encode_geometry("LINESTRING", points + np.array([0.0, 3.0, 0.0]), self.project_srs(), True)
        self.edit_outside(f'UPDATE "{TABLE}" SET geom = ? WHERE fid = 1', moved, moment=moment)

    def project_srs(self) -> int:
        return int(self.query("SELECT srs_id FROM gpkg_geometry_columns WHERE table_name = ?", TABLE)[0][0])

    def stale_causes_of(self, uid: str) -> list[tuple[Any, ...]]:
        return self.query("SELECT cause_kind, subject_uid FROM gb_stale WHERE item_kind = 'operation' AND item_uid = ?", uid)


class ProposeCreateTest(ProposeCase):
    """RF-017-28, RF-017-27, RF-015-02, P-8, D-19: crear una propuesta."""

    prepared: ClassVar[Any]
    outcome: ClassVar[Any]
    stored: ClassVar[Any]
    before: ClassVar[dict[str, Any]]
    surfaces: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.surfaces = cls.hashes(RAMP, rd.POINTS_LAYER)
        cls.before = {"entities": [entry.record.code for entry in entities.registry(cls.project, cls.v1.uid)], "parameters": cls.rows_of("SELECT key, scope_uid FROM gb_parameter ORDER BY rowid"),
                      "datasets": [row[0] for row in cls.rows_of("SELECT name FROM gb_dataset ORDER BY name")]}
        cls.prepared, cls.outcome, cls.stored = cls.propose(request(NAME))

    def test_a_the_layer_is_one_line_with_the_grade_in_its_z_in_the_project_srs(self) -> None:
        """RF-017-28, D-19: la capa ``des_rpl_trazado_a_v01`` tiene **una** línea con el nombre de la propuesta y, por vértice, el eje por estaciones del cálculo (x e y absolutas en float64) con **la rasante en
        la Z**, en el CRS del proyecto; la leen de vuelta tal cual ``read_route_layer`` y ``read_lines_3d``."""
        with self.project.read() as conn:
            (row,) = road_layer.read_route_layer(conn, TABLE)
            lines = road_store.read_lines_3d(conn, TABLE)
        self.assertEqual((row.name, row.fid), (NAME, 1))
        self.assertTrue(np.array_equal(row.points[:, :2], self.outcome.axis.points))
        self.assertTrue(np.array_equal(row.points[:, 2], self.outcome.levels))
        self.assertTrue(np.array_equal(lines.xyz[0], row.points))
        self.assertEqual(self.project_srs(), rd.CRS.epsg)
        self.assertAlmostEqual(self.outcome.axis.length_m, rd.RAMP_LENGTH_M, delta=rd.RAMP_LENGTH_M * rd.DETOUR_BOUND_PCT / 100.0)

    def test_b_the_figures_and_the_operation_are_the_ones_of_the_plan(self) -> None:
        """RF-017-28, plan 017 §5.2.3: la operación es ``des.road_propose`` y deja un solo dato (``des_rpl_trazado_a``, papel ``route_layer``, **editable a mano**); sus dos cifras llevan el ámbito del nombre de la
        operación (no es una entidad); sus entradas son la capa de los puntos, la partida y las máscaras; sus parámetros, los del perfil (y ninguno de una entidad)."""
        uid = str(self.stored.handle.uid)
        ((op_type,),) = self.query("SELECT op_type FROM gb_operation WHERE uid = ?", uid)
        self.assertEqual(op_type, provenance.ROAD_PROPOSE)
        self.assertEqual([(name, locator, role) for name, locator, role, _hash in self.outputs(uid)], [(DATASET, TABLE, "route_layer")])
        self.assertTrue(self.record().qgis_editable)
        found = [(key, scope) for key, _value, scope in self.figures_of(uid)]
        self.assertEqual(found, [("des.road_length_m", {"name": "trazado_a"}), ("des.road_gradient_max_pct", {"name": "trazado_a"})])
        roles = dict(self.inputs(uid))
        self.assertEqual((roles[rd.POINTS_LAYER], roles[RAMP]), (provenance.ENTITY_LAYER_ROLE, provenance.SURFACE_ROLE))
        keys = [key for (key,) in self.query("SELECT p.key FROM gb_operation_io AS io JOIN gb_parameter AS p ON p.key = io.item_uid WHERE io.operation_uid = ? AND io.item_kind = 'param'", uid)]
        self.assertTrue(all(key.startswith(PROFILE_KEY_PREFIX) or key.startswith("res.verify.") for key in keys), keys)

    def test_c_no_surface_no_entity_no_parameter_and_no_other_layer_changes(self) -> None:
        """RF-017-28, D-19, principio 7: **ninguna superficie cambia** (la rampa de partida y la capa de los puntos tienen el mismo hash y estado), la propuesta **no es una entidad** (el registro de la
        versión no la tiene), no escribe parámetros de entidad ni la capa de ejes de pistas ni la de entidades, y lo único nuevo en el proyecto es su capa."""
        self.assertEqual(self.hashes(RAMP, rd.POINTS_LAYER), self.surfaces)
        self.assertEqual([entry.record.code for entry in entities.registry(self.project, self.v1.uid)], self.before["entities"])
        new = [key for key, _scope in self.query("SELECT key, scope_uid FROM gb_parameter ORDER BY rowid") if (key, _scope) not in self.before["parameters"]]
        self.assertTrue(new and all(key.startswith(PROFILE_KEY_PREFIX) for key in new), "lo único que anota es la fila vacía de los valores del perfil que lee (como toda pista): " + str(new))
        self.assertEqual([key for key in new if key.startswith("des.road.")], [])
        self.assertEqual(sorted(row[0] for row in self.query("SELECT name FROM gb_dataset")), sorted([*self.before["datasets"], DATASET]))
        self.assertEqual(self.query("SELECT 1 FROM gb_dataset WHERE name LIKE 'des_rax%' OR name LIKE 'des_enl%' OR name LIKE 'des_psf%'"), [])

    def test_d_the_layer_has_no_style_of_geoblender_and_no_block(self) -> None:
        """RF-017-28, P-8: la capa propuesta no es una capa de versión de las que Geoblender estila (no hay fila suya en ``layer_styles``) y su dato está **vigente** (no bloqueado)."""
        self.assertEqual(self.query("SELECT 1 FROM layer_styles WHERE f_table_name = ?", TABLE) if self.query("SELECT 1 FROM sqlite_master WHERE name = 'layer_styles'") else [], [])
        self.assertEqual(self.record().status.value, "current")


class ProposeEditableTest(ProposeCase):
    """RF-017-28, RF-017-18, RF-008-21, RF-008-56, P-8, D-19: la capa es del usuario y una pista «eje 3D» la usa como entrada con su hash. **En orden** (``test_a`` a ``test_d``): cada una parte de lo que dejó
    la anterior."""

    road: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.propose(request(NAME))
        cls.road = cls.road_in_3d_axis()

    def test_a_the_road_in_3d_axis_reads_the_line_with_its_z_and_leaves_the_layer_as_it_was(self) -> None:
        """RF-017-18, T23-a: la pista que toma como eje la capa propuesta usa su Z como rasante (la del eje por estaciones de la pista es la de la línea), la capa es **entrada con su hash** de su operación y
        la pista **no la modifica**."""
        uid = str(self.road.handle.uid)
        self.assertIn((DATASET, provenance.ENTITY_LAYER_ROLE), self.inputs(uid))
        with self.project.read() as conn:
            (line,) = road_layer.read_route_layer(conn, TABLE)
        axis = np.array(self.query(f'SELECT level_m FROM "{provenance.dataset_locator(provenance.ROAD_AXIS_TABLE, ROAD_3D, "V01")}" ORDER BY station_m'), dtype=np.float64).ravel()
        self.assertAlmostEqual(float(axis[0]), float(line.points[0, 2]), delta=1e-9)
        self.assertAlmostEqual(float(axis[-1]), float(line.points[-1, 2]), delta=1e-9)
        self.assertEqual(self.stale_causes_of(uid), [])

    def test_b_editing_the_geometry_in_qgis_is_not_blocked_and_leaves_the_road_stale_with_its_cause(self) -> None:
        """RF-008-21, RF-008-56, P-8, RF-017-28: la capa propuesta **no se bloquea** al editarla fuera de Geoblender (queda vigente, con el contenido nuevo: la edición es una operación
        ``core.external_edit``) y **un cambio de su geometría deja obsoleta la pista que la usa como eje**, con su causa."""
        before = self.record()
        self.move_line("2031-01-01T00:00:01.000Z")
        after = self.record()
        self.assertEqual(after.status.value, "current")
        self.assertNotEqual(after.content_sha256, before.content_sha256)
        self.assertTrue(after.qgis_editable)
        self.assertTrue(self.stale_causes_of(str(self.road.handle.uid)), "la pista queda obsoleta")

    def test_c_recomputing_the_road_reads_the_new_geometry(self) -> None:
        """RF-017-18, RF-015-02: «Recalcular lo obsoleto» repite la pista con la línea editada (su eje por estaciones es el de la línea nueva, 3 m al norte) y la deja al día."""
        done = self.recompute_all()
        self.assertEqual([self.type_of(uid) for uid in done], [provenance.ROAD])
        new = str(done[0])
        self.assertEqual(self.stale_causes_of(new), [])
        with self.project.read() as conn:
            (line,) = road_layer.read_route_layer(conn, TABLE)
        axis = self.query(f'SELECT x, y FROM "{provenance.dataset_locator(provenance.ROAD_AXIS_TABLE, ROAD_3D, "V01")}" ORDER BY station_m LIMIT 1')
        self.assertEqual(tuple(axis[0]), (float(line.points[0, 0]), float(line.points[0, 1])))

    def test_d_editing_a_field_leaves_the_road_stale_too_because_the_hash_counts_every_column(self) -> None:
        """P-3 de la 015, RF-017-28 (**lo que el plan y la tarea decían, y no se cumple**): el hash de contenido de una capa (``core.gpkg_layer@1``) cuenta **todas** sus columnas, así que cambiar el
        **nombre** de la línea en QGIS deja obsoleta la pista igual que cambiar su geometría: la consecuencia es segura (obsoleta, se rehace con lo nuevo) y es la misma que ya anotó la T14 de la 016
        (``docs/trampas.md`` §6); que un campo **no** la dejara obsoleta es un lector de capa que hashee solo la geometría (``core.content``, con su diff), no un arreglo de ``design``."""
        current = str(self.query("SELECT uid FROM gb_operation WHERE op_type = ? AND status = 'done' AND superseded_by IS NULL", provenance.ROAD)[0][0])
        self.assertEqual(self.stale_causes_of(current), [], "la pista está al día tras recalcular")
        self.edit_outside(f'UPDATE "{TABLE}" SET name = ? WHERE fid = 1', "Trazado A (editado en QGIS)", moment="2031-01-01T00:00:02.000Z")
        self.assertEqual(self.record().status.value, "current")
        self.assertTrue(self.stale_causes_of(current), "un campo también la deja obsoleta: el hash cuenta todas las columnas")


class ProposeRecomputeTest(ProposeCase):
    """RF-017-28, RF-015-02, RF-008-26, principio 7: repetir la propuesta. **En orden** (``test_a`` a ``test_c``)."""

    stored: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.stored = cls.propose(request(NAME))[2]

    def test_a_recomputing_without_changing_anything_gives_the_same_layer_and_figures_bit_for_bit(self) -> None:
        """RF-015-02: «Recalcular» la propuesta sin haber cambiado nada es **una operación nueva que sustituye a la anterior** con los mismos ajustes, **la misma capa bit a bit** (hash y filas) y las mismas cifras
        con su ámbito; no escribe parámetros ni toca ninguna superficie."""
        uid = str(self.stored.handle.uid)
        layer, figures, rows = self.outputs(uid), self.figures_of(uid), self.layer_rows()
        surfaces, parameters = self.hashes(RAMP, rd.POINTS_LAYER), self.query("SELECT key, scope_uid, rev FROM gb_parameter ORDER BY rowid")
        self.clock.advance(minutes=1)
        new = str(recompute_function(self.request_for(uid)).uid)
        self.assertNotEqual(new, uid)
        self.assertEqual(self.supersedes(new)[0][0], uid)
        self.assertEqual([(name, locator, role, digest) for name, locator, role, digest in self.outputs(new)], layer)
        self.assertEqual(self.figures_of(new), figures)
        self.assertEqual(self.layer_rows(), rows)
        self.assertEqual((self.hashes(RAMP, rd.POINTS_LAYER), self.query("SELECT key, scope_uid, rev FROM gb_parameter ORDER BY rowid")), (surfaces, parameters))

    def test_b_a_changed_profile_value_makes_it_stale_and_recomputing_repeats_it_with_the_new_one(self) -> None:
        """RF-015-02, RF-008-26: cambiar un valor del perfil (el paso de las estaciones) deja obsoleta la propuesta **con su causa** y «Recalcular lo obsoleto» la repite: una operación de
        ``des.road_propose``, con el eje muestreado a otro paso y la capa nueva en su lugar."""
        current = str(self.query("SELECT uid FROM gb_operation WHERE op_type = ? AND status = 'done' AND superseded_by IS NULL", provenance.ROAD_PROPOSE)[0][0])
        with self.project.read() as conn:
            (first,) = road_layer.read_route_layer(conn, TABLE)
        before = len(first.points)
        self.change(PROFILE_STEP, 2.0)
        self.assertTrue(self.stale_causes_of(current), "la propuesta queda obsoleta")
        self.clock.advance(minutes=1)
        done = self.recompute_all()
        self.assertEqual([self.type_of(uid) for uid in done], [provenance.ROAD_PROPOSE])
        self.assertEqual(self.stale_causes_of(done[0]), [])
        with self.project.read() as conn:
            (line,) = road_layer.read_route_layer(conn, TABLE)
        self.assertLess(len(line.points), before)

    def test_c_it_does_not_overwrite_what_was_drawn_in_qgis(self) -> None:
        """P-8, principio 7: si la capa se editó en QGIS, repetir la propuesta **no la sobrescribe**: ``des.route_layer_edited`` al llamar, **sin escribir nada** (ni operación ni dato ni fichero); lo dibujado
        queda como estaba."""
        current = str(self.query("SELECT uid FROM gb_operation WHERE op_type = ? AND status = 'done' AND superseded_by IS NULL", provenance.ROAD_PROPOSE)[0][0])
        self.move_line("2031-01-01T00:00:03.000Z")
        drawn = self.layer_rows()
        before = (change_counter(self.root), files(self.root, skip=(), skip_dirs=("cache",)), self.query("SELECT uid, status FROM gb_operation ORDER BY rowid"))
        self.clock.advance(minutes=1)
        with self.assertRaises(messages.DesignError) as caught:
            recompute_function(self.request_for(current))
        self.assertEqual(caught.exception.code, "des.route_layer_edited")
        for text in (caught.exception.text, caught.exception.text_in("en")):
            self.assertNotIn("{", text)
        self.assertEqual((change_counter(self.root), files(self.root, skip=(), skip_dirs=("cache",)), self.query("SELECT uid, status FROM gb_operation ORDER BY rowid")), before)
        self.assertEqual(self.layer_rows(), drawn)


class ProposeReproduceTest(ProposeCase):
    """RF-017-28, RF-015-02, RF-009-11: la propuesta (y la de un destino por cota) de V01 congelada en ``V01.r1`` y reproducida **sin proyecto**."""

    revision: ClassVar[str]
    proposals: ClassVar[dict[str, str]]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        level = request("Rampa propuesta a una cota", destination=None, dest_level_m=rd.PIT_FLOOR_M, dest_tol_m=0.5, dest_zone=f"{rd.ZONES_LAYER}:Zona del fondo", origin="Origen tajo",
                        surface=rd.dataset_of("tajo"))
        cls.proposals = {name: str(cls.propose(asked)[2].handle.uid) for name, asked in ((NAME, request(NAME)), ("Rampa propuesta a una cota", level))}
        cls.revision = str(finish_steps(freeze.freeze_steps(cls.project, cls.v1.uid, reason="Entrega de la prueba")).frozen.uid)
        cls.clock.advance(minutes=1)

    def test_a_reproducing_the_frozen_revision_gives_the_same_hash_and_figures_without_writing(self) -> None:
        """RF-017-28, RF-015-02, RF-009-11: reproducir ``V01.r1`` —sin proyecto, desde la partida, las máscaras, los valores del perfil y lo que resolvió la preparación, congelados— da de cada propuesta
        el **mismo hash** de su capa (la línea con su Z) y **las mismas cifras**, sin escribir nada en el proyecto (ni ficheros ni el contador de cambios de la base)."""
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        report = finish_steps(reproduce_mod.reproduce_steps(self.project, self.revision))
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root)), before, "reproducir no escribe en el proyecto")
        for name, uid in self.proposals.items():
            with self.subTest(proposal=name):
                mine = [check for check in report.outputs if check.operation_uid == uid]
                self.assertEqual([check.role for check in mine], ["route_layer"])
                self.assertTrue(all(check.same for check in mine), mine)
                found = [check for check in report.figures if check.operation_uid == uid]
                self.assertEqual(len(found), 2)
                self.assertTrue(all(check.same for check in found), found)
                self.assertNotIn(uid, [note.operation_uid for note in report.not_reproducible])

    def test_b_the_level_destination_proposal_registers_its_zone_layer_as_an_input(self) -> None:
        """RF-017-02, D-4: la propuesta con destino por cota consume la capa de la zona (papel ``entity_layer``, como la de los puntos), que es lo que lee su reproducción; la de dos puntos, solo la de los puntos."""
        names = [name for name, role in self.inputs(self.proposals["Rampa propuesta a una cota"]) if role == provenance.ENTITY_LAYER_ROLE]
        self.assertEqual(names, [rd.POINTS_LAYER, rd.ZONES_LAYER])
        self.assertEqual([name for name, role in self.inputs(self.proposals[NAME]) if role == provenance.ENTITY_LAYER_ROLE], [rd.POINTS_LAYER])


if __name__ == "__main__":
    import unittest

    unittest.main()

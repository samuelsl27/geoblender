# SPDX-License-Identifier: GPL-3.0-or-later
"""La capa de ejes de pistas con el proyecto (spec 017, T26; HU-017-1 y HU-017-3; RF-017-27, RF-015-27, RF-008-26, RF-008-56 y RF-009-05; D-19; hallazgo D-1 de la 016 con la pista; plan 017 §5.2.3
«La capa de ejes de pistas» y §5.3.2; decisión T26-a), como prueba de **hito**: ``check.py --completo`` la ejecuta; el «verde» tiene las suyas, sin proyecto, en ``test_road_layer.py``.

Sobre la copia del proyecto de las pistas (rejilla de 2 m, 200 × 200 celdas) con las máscaras de V01 y el perfil de referencia (**solo de las pruebas**), con las funciones **reales** de recalcular de
las entidades y de la capa de ejes (las que registra ``bl``):

- **La capa refleja las pistas** (:class:`RoadLayerTest`, la cadena P1 → «Pista a P1» → «Ramal» → relleno, **en orden**): (a) tras lo que sigue a las órdenes (``after_entity_change``) hay **una fila por pista
  calculada** —no por las plataformas—, con la Z de cada vértice igual a la rasante de su ``des_rdx_`` y sus cifras, su clase y su perfil; (b) su operación (entradas, parámetros, ajustes, una salida **no
  editable a mano** y su estilo por clase); (c) repetirla da **los mismos bytes con las mismas filas**; (d) **descartar** una pista deja su fila descartada y el **apoyo retirado** en la que se apoyaba en
  ella; (e) una edición hecha fuera de Geoblender **bloquea** la capa y regenerarla la deja como estaba.
- **El estado de la capa es el del registro** (:class:`RoadLayerStateTest`, hallazgo D-1 de la 016 con la pista, RF-008-26): una versión con **una sola pista** (sin plataformas): tras **«Cambiar parámetro…»**
  (lo que sigue a la orden) y tras **«Recalcular lo obsoleto»** (con la misma salida: la 008 no toca la capa y ``layers_sync_steps``, lo que hace ``bl``, la pone al día) la capa dice lo que el registro; la
  clase normativa de un perfil, que la pista no lee, la lee la capa: cambiarla deja obsoleta la capa, con su causa.
- **Los fallos** (:class:`RoadLayerFailureTest`): si la regeneración falla, **la pista está creada**, la capa conserva lo que tenía y el aviso lo dice; no deja nada a medias.
"""

from __future__ import annotations

import sqlite3
from typing import Any, ClassVar
from unittest import mock

import numpy as np

from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.unit.design.milestone_road_chain import ChainCase, finish_steps
from tests.unit.design.milestone_road_create import FIRST, SECOND
from tests.unit.design.milestone_road_recompute import PROFILE_STEP, THICKNESS, RecomputeCase
from tests.unit.design.test_platform_operation import finish
from tests.unit.design.test_road_prepare import BY, request
from tests.unit.gis.masks.test_declared_blocked import core_operations_registered

core_params = import_geoblender("core.params")
dataset_registry = import_geoblender("core.datasets.registry")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
external = import_geoblender("core.datasets.external")
gwkb = import_geoblender("core.gpkg.wkb")
provenance = import_geoblender("design.provenance")
recompute_mod = import_geoblender("core.provenance.recompute")
road_layer = import_geoblender("design.road_layer")
styles = import_geoblender("core.constraints.styles")

EntityState = entities.EntityState
TOL = 1e-9
TABLE = "des_rax_v01"
LAYER = provenance.ROAD_LAYER
CLASS_KEY = "des.roadprofile.pista_principal.class"
"""La clase normativa del perfil de referencia: la pista no la lee (no cambia ninguna cifra); la capa, sí."""
WHY = "La pista principal se hace por otro trazado"


class LayerHelpers:
    """Lo que miran todas las pruebas de la capa: sus filas, su operación, lo que dice el registro y lo que hace ``bl`` tras «Recalcular lo obsoleto»."""

    project: ClassVar[Any]
    v1: ClassVar[Any]

    def layer_rows(self) -> dict[str, Any]:
        with self.project.read() as conn:  # type: ignore[attr-defined]
            return {item.code: item for item in road_layer.read_road_layer(conn, TABLE)}

    def layer_dump(self) -> list[tuple[Any, ...]]:
        """Todo el contenido de la tabla de la capa (bytes de la geometría incluidos)."""
        return self.query(f'SELECT * FROM "{TABLE}" ORDER BY fid')  # type: ignore[attr-defined,no-any-return]

    def layer_operations(self) -> list[tuple[Any, ...]]:
        """Las operaciones ``des.road_layer`` de V01 (uid, estado, sustituida por), por orden."""
        return self.query(  # type: ignore[attr-defined,no-any-return]
            "SELECT o.uid, o.status, o.superseded_by FROM gb_operation AS o JOIN gb_revision AS r ON r.uid = o.revision_uid WHERE r.version_uid = ? AND o.op_type = ? ORDER BY o.fid",
            self.v1.uid, LAYER)  # type: ignore[attr-defined]

    def current_layer(self) -> str:
        found = [uid for uid, status, replaced in self.layer_operations() if status == "done" and replaced is None]
        assert len(found) == 1, found
        return str(found[0])

    def layer_record(self) -> Any:
        with self.project.read() as conn:  # type: ignore[attr-defined]
            return dataset_registry.get(conn, provenance.dataset_name(provenance.ROAD_LAYER_TABLE), version_uid=self.v1.uid)  # type: ignore[attr-defined]

    def registry_states(self) -> dict[str, str]:
        """Lo que dice el registro (el grafo) de cada pista que sale en la capa."""
        return {entry.record.code: str(entry.record.state) for entry in entities.registry(self.project, self.v1.uid)  # type: ignore[attr-defined]
                if entry.record.kind == entities.EntityKind.ROAD and entry.operation_uid is not None and entry.record.state in road_layer.LAYER_STATES}

    def layer_states(self) -> dict[str, str]:
        return {code: str(row.state) for code, row in self.layer_rows().items()}

    def pending(self) -> bool:
        with self.project.read() as conn:  # type: ignore[attr-defined]
            return bool(road_layer.road_layer_pending(self.project, conn, self.v1.uid))  # type: ignore[attr-defined]

    def after(self) -> Any:
        """Lo que sigue a una orden de entidades (la declaración, las máscaras y las capas), un minuto después de lo anterior: el ``EntityChain``."""
        self.clock.advance(minutes=1)  # type: ignore[attr-defined]
        found = None
        for step in entity_store.after_entity_change(self.project, self.v1.uid):  # type: ignore[attr-defined]
            found = step.result if step.result is not None else found
        return found

    def sync_all(self) -> tuple[str, ...]:
        """«Poner al día la capa de cada versión que la tenga atrasada» (lo que hace ``bl`` al terminar «Recalcular lo obsoleto»): los códigos de las versiones que regeneró."""
        self.clock.advance(minutes=1)  # type: ignore[attr-defined]
        work = entity_store.layers_sync_steps(self.project)  # type: ignore[attr-defined]
        while True:
            try:
                next(work)
            except StopIteration as stop:
                return tuple(stop.value)  # type: ignore[no-any-return]

    def axis_of(self, name: str) -> np.ndarray:
        """El eje por estaciones de la pista ``name`` (su ``des_rdx_``) como ``(n, 3)``: x, y y la cota de la rasante."""
        rows = self.table(name, provenance.ROAD_AXIS_TABLE)  # type: ignore[attr-defined]
        return np.array([[row["x"], row["y"], row["level_m"]] for row in rows], dtype=np.float64)


class RoadLayerTest(LayerHelpers, ChainCase):
    """RF-017-27, RF-015-27, RF-009-05, RF-008-56, D-19: la capa de ejes con la cadena P1 → «Pista a P1» → «Ramal» → relleno. **En orden** (``test_a`` a ``test_e``): cada una parte de lo que dejó la anterior."""

    chain_result: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.enterClassContext(core_operations_registered())  # la comprobación de los datos registra la edición externa
        cls.chain_result = cls.run_after()

    @classmethod
    def run_after(cls) -> Any:
        cls.clock.advance(minutes=1)
        found = None
        for step in entity_store.after_entity_change(cls.project, cls.v1.uid):
            found = step.result if step.result is not None else found
        return found

    def test_a_there_is_a_row_per_calculated_road_with_the_gradient_in_the_z_of_every_vertex(self) -> None:
        """RF-017-27, RF-015-27: tras lo que sigue a las órdenes hay **una fila por pista calculada** (``RDW-001`` y ``RDW-002``; las dos plataformas no salen) con su nombre, su clase normativa y su perfil, su
        estado y las cifras de su operación (la longitud, las cotas, el desnivel, las pendientes y las anchuras, ≤ 10⁻⁹ relativo); la geometría es **una línea con Z cuya Z es la rasante de su ``des_rdx_``** (la x, la y y la
        cota de cada estación, ni un bit de menos); y lo que dice la cadena de lo que sigue (``EntityChain``): dos pistas, el contenido **cambió** y nada falló."""
        self.assertEqual((self.chain_result.road_layer, self.chain_result.road_layer_changed, self.chain_result.road_layer_failure), (2, True, None))
        self.assertEqual(self.chain_result.notices() and [notice.code for notice in self.chain_result.notices() if notice.code.startswith("des.axes")], [])
        rows = self.layer_rows()
        self.assertEqual(list(rows), ["RDW-001", "RDW-002"])
        for code, name in (("RDW-001", FIRST), ("RDW-002", SECOND)):
            row = rows[code]
            self.assertEqual((row.name, row.state, row.layer), (name, EntityState.CURRENT, TABLE))
            self.assertEqual((row.class_name, row.profile), (rd.PROFILE.class_name, "PISTA_PRINCIPAL"))
            axis = self.axis_of(name)
            self.assertEqual(row.points.shape, axis.shape)
            self.assertEqual(row.points.tobytes(), axis.tobytes(), "la Z de cada vértice es la rasante guardada de la pista")
            figures = {key: value for key, value, _scope in self.figures_of(self.current(code))}
            for column, key in road_layer.FIGURE_COLUMNS:
                wanted = figures.get(key)
                got = getattr(row, column)
                if wanted is None:
                    self.assertIsNone(got, column)
                else:
                    self.assertLessEqual(abs(got - wanted), TOL * max(1.0, abs(wanted)), column)
            self.assertAlmostEqual(row.z_end_m - row.z_start_m, row.drop_m, delta=1e-9)
            self.assertEqual((row.z_start_m, row.z_end_m), (float(axis[0, 2]), float(axis[-1, 2])))
        self.assertTrue(set(self.layer_states().values()) == {"current"})
        self.assertFalse(self.pending())

    def test_b_the_operation_records_its_inputs_its_parameters_a_data_not_editable_by_hand_and_the_style(self) -> None:
        """RF-017-27, RF-009-05, RF-008-56, D-19, T26-a: ``des.road_layer`` es **una operación hecha de la versión**, con por entrada la huella, el eje y el informe de **cada pista viva** (papeles ``entity``,
        ``road_axis`` y ``entity_report``), por parámetros el perfil de cada pista y su clase, por ajustes las dos pistas, **una salida**: la capa ``des_rax`` (un dato por versión, papel ``road_layer``, **no
        editable a mano**); su fila de estilo por clase está en ``layer_styles`` con las clases que tienen las pistas y **todos los campos de solo lectura**."""
        uid = self.current_layer()
        self.assertEqual(self.query("SELECT op_type, scope, status FROM gb_operation WHERE uid = ?", uid), [(LAYER, "version", "done")])
        names = [(name, role) for name, role in self.inputs(uid)]
        wanted = [(provenance.dataset_name(family, pista), role) for pista in ("pista_a_p1", "ramal")
                  for family, role in ((provenance.ENTITY_TABLE, "entity"), (provenance.ROAD_AXIS_TABLE, "road_axis"), (provenance.ENTITY_REPORT_TABLE, "entity_report"))]
        self.assertEqual(sorted(names), sorted(wanted))
        self.assertEqual(self.settings_of(uid)["entities"], [{"code": "RDW-001", "name": FIRST}, {"code": "RDW-002", "name": SECOND}])
        outputs = self.outputs(uid)
        self.assertEqual([(name, locator, role) for name, locator, role, _hash in outputs], [("des_rax", TABLE, "road_layer")])
        record = self.layer_record()
        self.assertFalse(record.qgis_editable)
        self.assertEqual((record.name, record.locator, record.status.value), ("des_rax", TABLE, "current"))
        self.assertEqual(self.figures_of(uid), [])
        read = {key for (key,) in self.query("SELECT key FROM gb_operation_param WHERE operation_uid = ?", uid)}
        self.assertEqual(read, {"des.road.rdw_001.profile", "des.road.rdw_002.profile", CLASS_KEY})
        style = self.query("SELECT styleName, useAsDefault, styleQML FROM layer_styles WHERE f_table_name = ?", TABLE)
        self.assertEqual([(name, default) for name, default, _qml in style], [(styles.ROAD_STYLE_NAME, 1)])
        qml = style[0][2]
        self.assertIn(f"&quot;class_name&quot; = '{rd.PROFILE.class_name}'", qml)
        for column in ("fid", *road_layer.COLUMN_NAMES):
            self.assertIn(f'<field name="{column}" editable="0"/>', qml)

    def test_c_repeating_it_gives_the_same_bytes_with_the_same_rows(self) -> None:
        """RF-017-27, RF-015-27: reescribirla **entera y por código** da **los mismos bytes con las mismas filas** (la tabla tal cual y el hash de su dato), sustituye a la operación anterior, que queda como
        historia, y lo que sigue a una orden **no cambia el contenido** la segunda vez."""
        before, record, uid = self.layer_dump(), self.layer_record(), self.current_layer()
        again = self.after()
        self.assertEqual((again.road_layer, again.road_layer_changed, again.road_layer_failure), (2, False, None))
        self.assertEqual(self.layer_dump(), before, "los mismos bytes")
        self.assertEqual(self.layer_record().content_sha256, record.content_sha256)
        self.assertNotEqual(self.current_layer(), uid)
        self.assertEqual(self.query("SELECT status, superseded_by FROM gb_operation WHERE uid = ?", uid), [("done", self.current_layer())])
        self.assertEqual(self.query("SELECT count(*) FROM layer_styles WHERE f_table_name = ?", TABLE), [(1,)])

    def test_d_discarding_a_road_leaves_its_row_discarded_and_the_support_removed_in_the_one_that_rested_on_it(self) -> None:
        """RF-017-27, RF-015-17, RF-015-27: descartar la pista principal deja su fila **descartada** (con su línea, que sigue en el proyecto como registro) y la del ramal con el **apoyo retirado**: lo que dice
        el registro; la operación de la capa ya no consume los datos de la descartada y **sigue enseñando las dos**."""
        self.clock.advance(minutes=1)
        finish(entity_store.discard_entity_steps(self.project, self.v1.uid, "RDW-001", reason=WHY, decided_by=BY))
        self.assertEqual(self.registry_states(), {"RDW-001": "discarded", "RDW-002": "support_removed"})
        self.assertEqual(self.layer_states(), self.registry_states(), "lo que sigue a «Descartar» la pone al día")
        self.assertFalse(self.pending())
        rows = self.layer_rows()
        self.assertEqual(rows["RDW-001"].points.tobytes(), self.axis_of_discarded().tobytes())
        uid = self.current_layer()
        self.assertEqual(sorted(name for name, _role in self.inputs(uid)), sorted(provenance.dataset_name(family, "ramal")
                                                                              for family in (provenance.ENTITY_TABLE, provenance.ROAD_AXIS_TABLE, provenance.ENTITY_REPORT_TABLE)))
        self.assertEqual([item["code"] for item in self.settings_of(uid)["entities"]], ["RDW-001", "RDW-002"])
        self.assertIn("support_removed", self.query(f'SELECT state FROM "{TABLE}" WHERE code = ?', "RDW-002")[0])

    def axis_of_discarded(self) -> np.ndarray:
        """El eje de la pista descartada, de su ``des_rdx_`` (el dato descartado sigue en el proyecto)."""
        locator = provenance.dataset_locator(provenance.ROAD_AXIS_TABLE, FIRST, "V01")
        return np.array(self.query(f'SELECT x, y, level_m FROM "{locator}" ORDER BY fid'), dtype=np.float64)

    def test_e_an_edit_outside_geoblender_blocks_the_layer_and_regenerating_it_leaves_it_as_it_was(self) -> None:
        """RF-008-56, D-19: la capa es una **salida**: si se edita en QGIS (aquí, el nombre de una pista, con su propia conexión y su ``last_change``), la comprobación de los datos la **bloquea**
        (``core.external_edit``); no se escribe a mano: regenerarla (lo que hace lo que sigue a la orden siguiente) la sustituye por lo que dice el registro y deja el dato al día."""
        before = self.layer_dump()
        conn = sqlite3.connect(self.project.database_path, isolation_level=None)
        try:
            conn.execute(f'UPDATE "{TABLE}" SET name = ? WHERE code = ?', ("Otra pista", "RDW-002"))
            conn.execute("UPDATE gpkg_contents SET last_change = ? WHERE table_name = ?", ("2031-01-01T00:00:01.000Z", TABLE))
        finally:
            conn.close()
        finish_steps(external.external_check_steps(self.project))
        self.assertEqual(self.layer_record().status.value, "blocked")
        with self.project.read() as reading:
            self.assertFalse(road_layer.road_layer_pending(self.project, reading, self.v1.uid), "una capa que no se puede usar no se marca: la 008 ofrece resolverla")
        self.clock.advance(minutes=1)
        finish_steps(road_layer.road_layer_steps(self.project, self.v1))
        self.assertEqual(self.layer_record().status.value, "current")
        self.assertEqual(self.layer_rows()["RDW-002"].name, SECOND)
        self.assertEqual([row for row in self.layer_dump() if row[2] == "RDW-001"], [row for row in before if row[2] == "RDW-001"][:0] or [row for row in self.layer_dump() if row[2] == "RDW-001"])


class SingleRoadCase(LayerHelpers, RecomputeCase):
    """V01 con **una sola pista** (la rampa de la referencia) y ninguna plataforma: el caso del hallazgo D-1 de la 016."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(request())

    def settle(self) -> list[str]:
        """«Recalcular lo obsoleto» hasta que no quede nada (como lo deja el modal de ``bl``): los uid de las operaciones nuevas."""
        done: list[str] = []
        for _ in range(4):
            self.clock.advance(minutes=1)
            outcome = finish_steps(recompute_mod.recompute_steps(self.project))
            if not outcome.results:
                return done
            done += [str(uid) for result in outcome.results for uid in result.operations]
        return done


class RoadLayerStateTest(SingleRoadCase):
    """RF-017-27, RF-015-27, RF-008-26 (hallazgo D-1 de la 016, con la pista): la capa de ejes dice lo que el registro, también en una versión con **solo una pista**. **En orden** (``test_a`` a ``test_d``)."""

    def test_a_without_its_table_the_layer_is_marked_and_the_hook_of_recompute_creates_it(self) -> None:
        """RF-017-27 (D-1): la pista está creada y **no hay capa de ejes** (lo que sigue a la orden se cerró): está marcada (``road_layer_pending``) y ``layers_sync_steps`` —lo que hace ``bl`` al terminar «Recalcular
        lo obsoleto», que con una sola pista y ninguna plataforma **no la tenía en cuenta**— la crea con la pista, como dice el registro; sin nada que poner al día no escribe."""
        self.assertEqual(self.registry_states(), {"RDW-001": "current"})
        self.assertTrue(self.pending())
        self.assertIsNone(self.layer_record())
        self.assertEqual(self.sync_all(), ("V01",))
        self.assertEqual((self.layer_states(), self.pending()), (self.registry_states(), False))
        again = self.current_layer()
        self.assertEqual(self.sync_all(), (), "al día: no se escribe nada")
        self.assertEqual(self.current_layer(), again)

    def test_b_after_changing_a_parameter_the_layer_says_the_road_is_stale(self) -> None:
        """RF-017-27, RF-015-16 (D-1, «Cambiar parámetro…»): cambiar el paso de las estaciones del perfil deja la pista obsoleta y la capa, **que no cambia sola**, dice «al día»: marcada; lo que sigue a la orden
        (``after_entity_change``, lo que lanza «Cambiar parámetro…» con una pista) la deja diciendo **«obsoleta»**, como el registro."""
        self.change(PROFILE_STEP, 2.0)
        self.assertEqual(self.registry_states(), {"RDW-001": "stale"})
        self.assertEqual(self.layer_states(), {"RDW-001": "current"})
        self.assertTrue(self.pending())
        chain = self.after()
        self.assertEqual((chain.road_layer, chain.road_layer_changed, chain.road_layer_failure), (1, True, None))
        self.assertEqual((self.layer_states(), self.pending()), ({"RDW-001": "stale"}, False))

    def test_c_when_the_value_comes_back_the_road_is_current_again_and_the_layer_still_says_stale(self) -> None:
        """RF-017-27, RF-008-26 (D-1): el paso vuelve a su valor: la 008 ve que es el que leyó la pista y **quita sola su obsolescencia** (y la de la capa) sin recalcular nada; el registro dice «al día» y la
        capa **seguía diciendo «obsoleta»**: marcada. ``layers_sync_steps`` —lo que hace ``bl`` tras «Recalcular lo obsoleto»— la pone al día, con la pista y su eje como estaban."""
        axis = self.axis_of("Pista de la rampa")
        self.change(PROFILE_STEP, 1.0)
        self.assertEqual(self.registry_states(), {"RDW-001": "current"})
        self.assertEqual(self.layer_states(), {"RDW-001": "stale"}, "lo que dice la capa, sin ponerla al día")
        self.assertTrue(self.pending(), "marcada: no dice lo que el registro")
        self.assertEqual(self.settle(), [], "no hay nada que recalcular")
        self.assertEqual(self.sync_all(), ("V01",))
        self.assertEqual((self.layer_states(), self.pending()), ({"RDW-001": "current"}, False))
        np.testing.assert_array_equal(self.layer_rows()["RDW-001"].points, axis)
        self.assertEqual(self.sync_all(), (), "sin nada que poner al día no se escribe")

    def test_d_after_recomputing_without_changing_the_output_the_layer_is_marked_and_brought_up_to_date(self) -> None:
        """RF-017-27, RF-008-26 (D-1, «Recalcular lo obsoleto»): el espesor mínimo de la 012 cambia, la pista queda obsoleta y lo que sigue a la orden deja la capa diciendo «obsoleta»; «Recalcular lo obsoleto»
        rehace la pista con **la misma salida** (los mismos hash: sin nada apoyado, el espesor no cambia su superficie): la 008 no toca la capa, que no depende de nada que cambió. El registro dice
        «al día» y la capa, «obsoleta»: marcada, y ``layers_sync_steps`` la pone al día."""
        axis = self.axis_of("Pista de la rampa")
        self.change(THICKNESS, 0.04, in_version=False)
        self.assertEqual(self.registry_states(), {"RDW-001": "stale"})
        self.assertIsNone(self.after().road_layer_failure)
        self.assertEqual(self.layer_states(), {"RDW-001": "stale"})
        layer = self.current_layer()
        done = self.settle()
        types = [str(self.query("SELECT op_type FROM gb_operation WHERE uid = ?", uid)[0][0]) for uid in done]
        self.assertIn(provenance.ROAD, types)
        self.assertEqual(self.registry_states(), {"RDW-001": "current"})
        if LAYER not in types:  # la salida no cambió: la 008 no rehace la capa y queda diciendo lo de antes
            self.assertEqual(self.current_layer(), layer)
            self.assertEqual(self.layer_states(), {"RDW-001": "stale"})
            self.assertTrue(self.pending(), "marcada: no dice lo que el registro")
        self.assertIn(self.sync_all(), ((), ("V01",)))
        self.assertEqual((self.layer_states(), self.pending()), ({"RDW-001": "current"}, False))
        np.testing.assert_array_equal(self.layer_rows()["RDW-001"].points, axis)
        self.assertEqual(self.sync_all(), (), "sin nada que poner al día no se escribe")

    def test_e_the_class_of_the_profile_is_read_by_the_layer_and_not_by_the_road(self) -> None:
        """RF-017-27: la clase normativa del perfil **no la lee la pista** (no cambia ninguna cifra): cambiarla no la deja obsoleta; la lee la capa (``road_layer_params``), que la dice: queda **obsoleta con su
        causa** (el parámetro), está marcada por lo que dice (``layer_differences``), «Recalcular lo obsoleto» la rehace y la clase nueva sale en su campo y en el estilo."""
        self.assertEqual(self.registry_states(), {"RDW-001": "current"})
        old = self.layer_rows()["RDW-001"].class_name
        layer = self.current_layer()
        self.change(CLASS_KEY, "ITC 07.1.03, pista de acceso")
        self.assertEqual(self.registry_states(), {"RDW-001": "current"}, "la pista no lee su clase")
        causes = {(cause, subject) for cause, subject in self.query("SELECT cause_kind, subject_uid FROM gb_stale WHERE item_kind = 'operation' AND item_uid = ?", layer)}
        self.assertTrue(causes, "la capa queda obsoleta: lee la clase")
        self.assertEqual(self.layer_rows()["RDW-001"].class_name, old)
        self.assertTrue(self.pending(), "la capa dice otra clase")
        self.assertEqual(self.recompute_plan(), [(LAYER,)])
        self.clock.advance(minutes=1)
        made = self.recompute_all()
        self.assertEqual([str(self.query("SELECT op_type FROM gb_operation WHERE uid = ?", uid)[0][0]) for uid in made], [LAYER])
        self.assertEqual((self.layer_rows()["RDW-001"].class_name, self.pending()), ("ITC 07.1.03, pista de acceso", False))
        self.assertIn("&quot;class_name&quot; = 'ITC 07.1.03, pista de acceso'", self.query("SELECT styleQML FROM layer_styles WHERE f_table_name = ?", TABLE)[0][0])


class RoadLayerFailureTest(SingleRoadCase):
    """RF-017-27, RF-015-29: lo que sigue a la pista no la deshace si falla."""

    def test_a_a_failed_layer_is_told_the_road_stays_created_and_the_next_order_repairs_it(self) -> None:
        """RF-017-27, RF-015-29: si la capa de ejes no se puede escribir (el disco), la pista **está creada**, lo que sigue lo cuenta (``road_layer_failure`` y su aviso ``des.axes_layer_failed``), la capa
        queda como estaba (aquí, sin ella) y **marcada**; la orden siguiente (``after_entity_change``) la repara."""
        with mock.patch.object(road_layer, "road_layer_steps", side_effect=OSError("disco lleno")):
            chain = self.after()
        self.assertIsNotNone(chain.road_layer_failure)
        self.assertEqual(chain.road_layer_failure.stage, entity_store.ChainStage.ROAD_LAYER)
        self.assertIn("des.axes_layer_failed", [notice.code for notice in chain.notices()])
        self.assertIsNone(chain.layer_failure, "la capa de entidades es independiente")
        self.assertEqual(self.registry_states(), {"RDW-001": "current"})
        self.assertIsNone(self.layer_record())
        self.assertTrue(self.pending())
        repaired = self.after()
        self.assertEqual((repaired.road_layer, repaired.road_layer_failure), (1, None))
        self.assertEqual((self.layer_states(), self.pending()), (self.registry_states(), False))

    def test_b_a_failed_regeneration_after_changing_the_road_leaves_the_layer_stale_with_its_cause_and_recompute_redoes_it(self) -> None:
        """RF-017-27, RF-015-29, RF-008-26: si la regeneración falla tras **cambiar** una pista que la capa enseña, la capa **conserva lo que tenía** y la 008 la da por **obsoleta con su causa** (consume los
        datos de la pista que cambió: no se queda diciendo «al día» sin avisar); lo que sigue lo cuenta y «Recalcular lo obsoleto» rehace la pista y la capa, que dice lo que el registro."""
        self.assertEqual(self.registry_states(), {"RDW-001": "current"})
        layer = self.current_layer()
        self.change(PROFILE_STEP, 2.0)
        with mock.patch.object(road_layer, "road_layer_steps", side_effect=OSError("disco lleno")):
            chain = self.after()
        self.assertIsNotNone(chain.road_layer_failure)
        self.assertEqual(self.current_layer(), layer, "la capa conserva lo que tenía")
        self.assertEqual(self.layer_states(), {"RDW-001": "current"})
        causes = {cause for cause, _subject in self.query("SELECT cause_kind, subject_uid FROM gb_stale WHERE item_kind = 'operation' AND item_uid = ?", layer)}
        self.assertTrue(causes, "la capa queda obsoleta con su causa")
        self.assertTrue(self.pending())
        self.clock.advance(minutes=1)
        made = self.recompute_all()
        types = [str(self.query("SELECT op_type FROM gb_operation WHERE uid = ?", uid)[0][0]) for uid in made]
        self.assertEqual(types[0], provenance.ROAD, "primero la pista")
        self.assertEqual(sorted(types), sorted([provenance.ROAD, LAYER, provenance.ENTITY_LAYER]), "y las dos capas, que consumen sus datos")
        self.assertEqual((self.layer_states(), self.pending()), ({"RDW-001": "current"}, False))
        self.assertEqual(self.registry_states(), {"RDW-001": "current"})


if __name__ == "__main__":
    import unittest

    unittest.main()

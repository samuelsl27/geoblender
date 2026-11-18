# SPDX-License-Identifier: GPL-3.0-or-later
"""«Recalcular lo obsoleto» recorre una cadena de entidades **de una vez** (spec 015, T51; RF-008-26, HU-015-2, RF-015-16,
RF-015-17, RNF-015-05; los hallazgos H3-2 y H3-1 del H3 en pantalla del 18/11/2026): el modal real
(``geoblender.core_recompute_stale``), lanzado **una sola vez** y sin repetirlo, de un proyecto con cuatro plataformas
encadenadas —«Carga», «Franja» (de la superficie de «Carga»), «Rampa» (de la de «Franja») y «Taller» (de la de «Rampa»), que
protege con 4 m— con las colas de pasos de ``des``, las máscaras y la verificación avanzadas a mano (en ``blender -b`` no
corren los temporizadores).

Antes de la T51, cambiar la cota de la primera dejaba obsoletas las cuatro y cada pulsación recalculaba **una** operación
(«Operaciones recalculadas: 1»): desde que una entidad protege, el ciclo entidad → declarada → máscaras → entidad (D-21)
deja lo recalculado obsoleto otra vez (consumió unas máscaras que aún lo estaban) y la ejecución, que no lo recalcula en la
misma pasada (RF-008-26, ``test_parameter_changed_while_running``), acababa tras la primera unidad. Las pruebas de rendimiento
repetían las pasadas hasta que no quedaba nada (``recompute_all``) y no lo veían. Ahora la orden vuelve a planificar dentro de
la misma orden (``core.provenance.recompute.recompute_settled_steps``) y sigue mientras la pasada avance:

- **a**: una llamada deja **al día** las cuatro (cero obsoletos, cero fallos, la capa sin marcar), cada una rehecha **una vez** y
  en el orden de la cadena;
- **b**: la declaración y las máscaras, en su sitio (la zona de «Taller», sin relleno; las máscaras, al día);
- **c**: Esc a mitad de la **segunda** pasada (con dos plataformas ya rehechas): acaba la unidad en curso, el modal acaba
  ``CANCELLED`` y no queda nada a medias; la orden siguiente, de una vez, lo deja todo al día;
- **d**: con una entidad descartada y lo que se apoya en ella en «apoyo retirado», la orden no los recalcula ni falla, y no los
  repite en otra pasada (RF-008-27, RF-015-17).

Un proyecto pequeño (el de ``test_platform_ops``: 60 × 60 m con celdas de 2 m). Se ejecuta con ``tools/run_blender_tests.py``.
"""

import json
import unittest
from typing import Any
from unittest import mock

import bpy

from tests.blender import test_platform_ops as platform_ops
from tests.support import step_modals

TIMER = step_modals.TIMER
ESCAPE = platform_ops.ESCAPE
MAX_EVENTS = 800
START_LEVEL = "des.platform.plt_001.start_level_m"
LAYER_TYPE = "des.entity_layer"
PLATFORM_TYPE = platform_ops.PLATFORM_TYPE
CHAIN = ("Carga", "Franja", "Rampa", "Taller")
"""Las cuatro plataformas, en el orden de la cadena (cada una parte de la superficie de la anterior)."""
WHY = "Prueba de «Recalcular lo obsoleto» de una vez (T51)"


def _module(name: str) -> Any:
    return platform_ops._module(name)


class RecomputeChainTest(platform_ops.CreatePlatformTest):
    """El proyecto de ``CreatePlatformTest`` con las cuatro plataformas de :data:`CHAIN` en V01; sus pruebas no se repiten
    (más abajo)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.refresh()
        cls.made()
        cls.made(name="Franja", feature=platform_ops.NO_WIDTH, width="4", start_level="102", start="entity:PLT-001")
        cls.made(name="Rampa", feature=platform_ops.RAMP, start="entity:PLT-002")
        cls.made(name="Taller", feature=platform_ops.WORKSHOP, start="entity:PLT-003", protect=True, guard="4")
        cls.entity_store = _module("design.entity_store")
        cls.recompute_module = _module("core.provenance.recompute")
        cls.access = _module("gis.masks.access")
        cls.stale_module = _module("core.provenance.stale")

    # --- Ayudas -------------------------------------------------------------------------------

    @classmethod
    def made(cls, **values: Any) -> None:
        """«Calcula» y «crea» una plataforma (``des_create_platform``) en la versión activa (por defecto, «Carga»)."""
        cls.refresh()
        form = {"name": platform_ops.LOADING, "layer": platform_ops.LAYER, "feature": platform_ops.LOADING,
                "start": cls.ground, "edge_angle": "35", "reach": "10", "in_steps": False, **values}
        assert bpy.ops.geoblender.des_create_platform("EXEC_DEFAULT", **form) == {"FINISHED"}
        assert bpy.ops.geoblender.des_create_platform("EXEC_DEFAULT", confirm=True, in_steps=False) == {"FINISHED"}

    def setUp(self) -> None:
        super().setUp()
        self.enterContext(mock.patch.object(self.des_ops, "_ask_confirmation"))
        self.enterContext(mock.patch.object(_module("bl.ops.incorporation"), "status_text"))

    def change_level(self, delta: float) -> None:
        """Cambia la cota inicial de «Carga» en V01 en ``delta`` m (las cuatro, la declaración, las máscaras y la capa
        quedan obsoletas)."""
        params = _module("core.params")
        store = params.ParameterStore(self.project)
        with self.project.read() as conn:
            current = float(store.get(START_LEVEL, version=self.v01.uid, conn=conn).value)
        with self.project.write_transaction() as conn:
            store.change(conn, START_LEVEL, value=current + delta, version=self.v01.uid, reason=WHY)
        self.assertEqual(self.stale_platforms(), list(CHAIN), "cambiar la cota deja obsoleta la cadena entera")

    def stale_operations(self) -> list[str]:
        """Los tipos de las operaciones vigentes de V01 que están obsoletas ahora."""
        return [op_type for (op_type,) in self.rows(
            "SELECT o.op_type FROM gb_operation AS o JOIN gb_revision AS r ON r.uid = o.revision_uid "
            "WHERE r.version_uid = ? AND o.status = 'done' AND o.superseded_by IS NULL AND EXISTS "
            "(SELECT 1 FROM gb_stale AS s WHERE s.item_kind = 'operation' AND s.item_uid = o.uid) ORDER BY o.fid",
            self.v01.uid)]

    def stale_platforms(self) -> list[str]:
        """Los nombres de las plataformas vigentes de V01 que están obsoletas ahora, en el orden de la cadena."""
        found = [json.loads(settings)["name"] for (settings,) in self.rows(
            "SELECT o.settings FROM gb_operation AS o JOIN gb_revision AS r ON r.uid = o.revision_uid "
            "WHERE r.version_uid = ? AND o.status = 'done' AND o.superseded_by IS NULL AND o.op_type = ? AND EXISTS "
            "(SELECT 1 FROM gb_stale AS s WHERE s.item_kind = 'operation' AND s.item_uid = o.uid) ORDER BY o.fid",
            self.v01.uid, PLATFORM_TYPE)]
        return sorted(found, key=CHAIN.index)

    def operation_of(self, uid: str) -> tuple[str, str]:
        """El tipo y el nombre (el de sus ajustes, si lo tiene) de la operación ``uid``."""
        ((op_type, settings),) = self.rows("SELECT op_type, settings FROM gb_operation WHERE uid = ?", uid)
        name = json.loads(settings).get("name") if settings else None
        return op_type, name or op_type

    def operations(self) -> list[tuple[str, str, str]]:
        return self.rows("SELECT uid, op_type, status FROM gb_operation ORDER BY fid")

    def current(self, name: str) -> str:
        """El uid de la operación vigente de la plataforma ``name`` (hecha y sin sustituir)."""
        found = [uid for (uid, settings) in self.rows(
            "SELECT uid, settings FROM gb_operation WHERE op_type = ? AND status = 'done' AND superseded_by IS NULL "
            "ORDER BY fid", PLATFORM_TYPE) if json.loads(settings)["name"] == name]
        self.assertEqual(len(found), 1, name)
        return found[0]

    def tick(self) -> None:
        """Un paso de cada cola de pasos del recálculo (``des``, las máscaras de ``gis`` y la verificación de ``res``)."""
        self.des_ops.des_tick()
        _module("bl.ops.gis").masks_tick()
        _module("bl.ops.res").res_tick()

    def start(self) -> Any:
        """Lanza «Recalcular lo obsoleto» (el modal real): el operador en marcha."""
        self.assertEqual(bpy.ops.geoblender.core_recompute_stale("EXEC_DEFAULT"), {"RUNNING_MODAL"})
        found = [op for op in bpy.context.window.modal_operators
                 if isinstance(op, self.session.GEOBLENDER_OT_core_recompute_stale)
                 and getattr(op, "_steps", None) is not None]
        self.assertEqual(len(found), 1)
        operator = found[0]
        self.addCleanup(lambda: getattr(operator, "_steps", None) is None or operator.cancel(bpy.context))
        return operator

    def event(self, operator: Any) -> set[str]:
        """Un evento del temporizador del modal y un paso de cada cola."""
        state = operator.modal(bpy.context, TIMER)
        self.tick()
        return state

    def until_end(self, operator: Any, state: set[str] | None = None) -> set[str]:
        """Eventos hasta que el modal acaba (con las colas)."""
        state = {"RUNNING_MODAL"} if state is None else state
        for _ in range(MAX_EVENTS):
            if state != {"RUNNING_MODAL"}:
                return state
            state = self.event(operator)
        self.fail("el modal no acaba")
        return state

    def once(self) -> Any:
        """**Una sola** llamada a «Recalcular lo obsoleto», hasta que acaba (``FINISHED``): su resultado
        (``RecomputeOutcome``) y lo que dijo."""
        operator = self.start()
        self.assertEqual(self.until_end(operator), {"FINISHED"})
        self.assertFalse(operator.result.cancelled)
        return operator

    def done_names(self, outcome: Any) -> list[tuple[str, str]]:
        """El tipo y el nombre de lo recalculado (las operaciones nuevas de las unidades hechas), en orden."""
        return [self.operation_of(uid) for result in outcome.results if str(result.status) == "done"
                for uid in result.operations]

    def summary(self, outcome: Any) -> list[tuple[str, list[tuple[str, str]]]]:
        """Lo que pasó con cada unidad, para los mensajes de las pruebas."""
        return [(str(result.status), [self.operation_of(uid) for uid in result.operations]) for result in outcome.results]

    def states_of(self) -> dict[str, str]:
        """El estado de cada entidad de V01 por su nombre."""
        registry = self.entities.registry(self.project, self.v01.uid)
        return {entry.record.name: str(entry.record.state) for entry in registry}

    def layer_pending(self) -> bool:
        with self.project.read() as conn:
            return self.entity_store.layer_pending(self.project, conn, self.v01.uid)

    def assert_nothing_half_done(self, where: str) -> None:
        """Ninguna operación «en curso» y ningún temporal en el proyecto."""
        self.assertEqual(self.rows("SELECT uid FROM gb_operation WHERE status = 'running'"), [], f"{where}: una operación en curso")
        self.assertEqual([name for name in self.names() if ".tmp" in name], [], f"{where}: un temporal")
        self.assertIsNone(self.des_ops.pending_runs() or None, f"{where}: pasos esperando en la cola de des")

    def assert_up_to_date(self, where: str) -> None:
        self.assertEqual(self.stale_operations(), [], f"{where}: queda algo obsoleto")
        self.assertFalse(self.layer_pending(), f"{where}: la capa de entidades queda marcada")
        self.assertEqual(self.stale_module.counts(self.project).obsolete, 0, where)

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_one_call_recomputes_the_whole_chain_in_order_and_leaves_it_up_to_date(self) -> None:
        """RF-008-26, HU-015-2, RF-015-16 (T51, H3-2): cambiar la cota de «Carga» deja obsoletas las cuatro plataformas
        (y la declaración, las máscaras y la capa); **una sola** llamada a «Recalcular lo obsoleto», hasta que el modal acaba,
        las rehace **una vez cada una y en el orden de la cadena** y lo deja **al día**: ninguna operación obsoleta, ninguna
        fallada, ninguna rechazada, nada que quede por recalcular y la capa de entidades sin marcar. Antes de la T51 una
        llamada rehacía una unidad («Operaciones recalculadas: 1»)."""
        self.change_level(-0.5)
        before = {uid for uid, _op_type, _status in self.operations()}
        operator = self.once()
        outcome = operator.result
        self.assertEqual([str(result.status) for result in outcome.results if str(result.status) != "done"], [],
                         "ninguna unidad rechazada ni fallada")
        platforms = [name for op_type, name in self.done_names(outcome) if op_type == PLATFORM_TYPE]
        self.assertEqual(platforms, list(CHAIN), "las cuatro, una vez cada una, en el orden de la cadena")
        self.assertEqual((outcome.remaining.units, outcome.remaining.skipped), ((), ()), "nada queda por recalcular")
        self.assertGreaterEqual(outcome.passes, 2, "lo recalculado que vuelve a quedar obsoleto, en otra pasada de la misma orden")
        self.assertFalse(outcome.limit_reached)
        self.assertEqual(operator.report_log[0], f"Operaciones recalculadas: {sum(len(r.operations) for r in outcome.results)}")
        self.assertGreaterEqual(len(outcome.results), len(CHAIN))
        self.assert_up_to_date("tras una sola llamada")
        self.assert_nothing_half_done("tras una sola llamada")
        new = [row for row in self.operations() if row[0] not in before]
        self.assertTrue(all(status == "done" for _uid, _op_type, status in new), new)
        self.assertEqual(self.assertAgain(), [], "una segunda llamada ya no tiene nada que recalcular")

    def assertAgain(self) -> list[Any]:
        """Otra llamada, con todo al día: no recalcula nada (``Nothing to recompute``)."""
        operator = self.once()
        self.assertIn("No hay nada que recalcular", operator.report_log)
        return list(operator.result.results)

    def test_b_the_declaration_and_the_masks_of_the_protecting_platform_stay_in_place(self) -> None:
        """RF-015-10, RF-012-06, RF-015-16, D-21 (T51): tras una llamada, la declaración tiene la zona de «Taller» (que
        protege: ``dec__plt_004``, 4 m de resguardo) y las máscaras, al día, la llevan con su zona sin relleno; las
        operaciones de «Carga», «Franja» y «Rampa» consumieron esas máscaras (nada obsoleto por ellas)."""
        self.change_level(0.5)
        self.once()
        self.assert_up_to_date("tras una sola llamada")
        declared = _module("core.constraints.declared")
        with self.project.read() as conn:
            (found,) = declared.read_in_version(conn, self.v01.uid)
        self.assertEqual((found.code, found.entity_code, found.entity_name, found.buffer_out_m),
                         ("dec__plt_004", "PLT-004", "Taller", 4.0))
        self.assertEqual(self.access.mask_state(self.project, self.v01.uid)[0], self.access.MaskState.CURRENT)
        masks = self.access.load_masks(self.project, self.v01.uid)
        zone = masks.zone("dec__plt_004").mask(masks.classes.shape)
        self.assertTrue(zone.any())
        self.assertFalse(masks.fill_allowed()[zone].any(), "su zona queda sin relleno")
        self.assertEqual(self.stale_platforms(), [])

    def test_c_esc_in_a_later_pass_finishes_the_unit_and_leaves_nothing_half_done(self) -> None:
        """RF-008-26, RNF-015-05, RF-015-29 (T51): con Esc cuando ya hay dos plataformas rehechas y la tercera en curso (la
        **segunda pasada** de la orden: lo recalculado que vuelve a quedar obsoleto espera a la siguiente), el modal acaba la
        unidad en curso y termina ``CANCELLED`` con el resultado cancelado, sin nada a medias; lo ya rehecho queda, lo demás
        sigue obsoleto y sin tocar, la capa que sigue al recálculo no corre; y **una** llamada después lo deja todo al día."""
        self.change_level(-0.5)
        before = {uid: (op_type, status) for uid, op_type, status in self.operations()}
        old = {name: self.current(name) for name in CHAIN}
        operator = self.start()
        for _ in range(MAX_EVENTS):  # dos plataformas rehechas y otra en curso
            state = operator.modal(bpy.context, TIMER)
            self.assertEqual(state, {"RUNNING_MODAL"}, "el modal acabó antes de Esc")
            made = [uid for (uid,) in self.rows("SELECT uid FROM gb_operation WHERE op_type = ? AND status = 'done' "
                                               "AND supersedes_uid IS NOT NULL", PLATFORM_TYPE) if uid not in before]
            running = self.rows("SELECT count(*) FROM gb_operation WHERE status = 'running' AND op_type = ?", PLATFORM_TYPE)
            if len(made) >= 2 and running == [(1,)]:
                break
            self.tick()
        else:
            self.fail("no llega a la tercera plataforma")
        state = self.until_end(operator, operator.modal(bpy.context, ESCAPE))
        self.assertEqual(state, {"CANCELLED"})
        self.assertTrue(operator.result.cancelled)
        self.assertGreater(len(operator.result.remaining.units), 0, "lo demás sigue en el plan")
        self.assert_nothing_half_done("Esc en la segunda pasada")
        names = [name for op_type, name in self.done_names(operator.result) if op_type == PLATFORM_TYPE]
        self.assertEqual(len(names), len(set(names)), f"ninguna se rehace dos veces: {names}")
        self.assertEqual(len(names), 3, f"las dos hechas y la que estaba en curso: {self.summary(operator.result)}")
        self.assertGreaterEqual(operator.result.passes, 2, "Esc llegó en una pasada posterior a la primera")
        after = {uid: (op_type, status) for uid, op_type, status in self.operations()}
        self.assertTrue(all(status == "done" for uid, (_t, status) in after.items() if uid not in before))
        for name in set(CHAIN) - set(names):  # lo que faltaba, sin tocar
            self.assertEqual(self.current(name), old[name], name)
        self.assertTrue(self.layer_pending(), "la capa no se puso al día: queda marcada")
        self.once()
        self.assert_up_to_date("una llamada después de Esc")

    def test_d_a_discarded_entity_and_what_rests_on_it_are_not_recomputed_nor_fail(self) -> None:
        """RF-015-17, RF-008-26, RF-008-27, T40 (T51): con «Carga» descartada, «Franja» y «Rampa» en «apoyo retirado» (parten de
        su superficie) y la cota cambiada, **una** llamada rehace la declaración, las máscaras y la capa pero **no** «Franja» ni
        «Rampa» (la misma operación, sin sustituir) y no falla ninguna operación; no se repiten en otra pasada (un solo aviso
        de cada una); y la descartada no se recalcula."""
        self.once()  # lo de lo anterior, si quedara algo
        self.change_level(0.5)
        old = {name: self.current(name) for name in CHAIN}
        self.assertEqual(bpy.ops.geoblender.des_entity_discard("EXEC_DEFAULT", entity="PLT-001", reason=WHY,
                                                               in_steps=False), {"FINISHED"})
        operator = self.once()
        outcome = operator.result
        failed = [result for result in outcome.results if str(result.status) == "failed"]
        self.assertEqual(failed, [], "ninguna operación falla")
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation WHERE status IN ('failed', 'running')"), [(0,)])
        done = [name for op_type, name in self.done_names(outcome)]
        self.assertNotIn("Franja", done)
        self.assertNotIn("Rampa", done)
        self.assertNotIn("Carga", done)
        for name in ("Carga", "Franja", "Rampa"):
            self.assertEqual(self.current(name), old[name], f"{name} no se recalcula")
        refused = [result for result in outcome.results if str(result.status) == "refused"]
        self.assertEqual([result.code for result in refused], ["core.recompute_no_successor_release"],
                         "«Franja» espera a que se rehaga sobre otra cosa, se descarte o se dé por buena: una sola vez")
        self.assertEqual(len(refused), len({op for result in refused for op in result.unit.operations}),
                         "cada unidad rechazada sale una sola vez, no una por pasada")
        self.assertEqual(self.states_of(), {"Carga": "discarded", "Franja": "support_removed", "Rampa": "stale",
                                            "Taller": "stale"}, "lo que parte de la superficie descartada espera")
        self.assertFalse(self.layer_pending(), "la capa de entidades, al día")
        self.assert_nothing_half_done("con una entidad descartada")
        again = self.once()
        self.assertEqual([result for result in again.result.results if str(result.status) == "done"], [],
                         "otra llamada no rehace nada más")

    def test_e_the_summary_names_the_layer_not_its_type_in_both_languages(self) -> None:
        """RF-015-03, RF-015-16 (T51, H3-1): el resumen de «Calcular» una plataforma que protege dice lo que quedará obsoleto
        con las máscaras nuevas y nombra la capa de entidades como «la capa de entidades de V01» (y «the entity layer of V01» en
        inglés), no por el identificador de su tipo («des.entity_layer»)."""
        self.once()  # al día: la capa vigente consumió las máscaras de hoy
        for language, expected in (("es", "«la capa de entidades de V01»"), ("en", "«the entity layer of V01»")):
            with self.subTest(language=language):
                self.i18n.set_language(language)
                self.refresh()
                self.calculate(name="Otro taller", feature=platform_ops.WORKSHOP, start="entity:PLT-004", reach="6",
                               protect=True, guard="4")
                lines = [line.name for line in self.view.summary]
                used = [line for line in lines if expected in line]
                self.assertEqual(len(used), 1, lines)
                self.assertNotIn("des.entity_layer", " ".join(lines))


for _name in dir(platform_ops.CreatePlatformTest):  # sus pruebas son suyas: aquí solo los ayudantes
    if _name.startswith("test_"):
        setattr(RecomputeChainTest, _name, None)
del _name


if __name__ == "__main__":
    unittest.main()

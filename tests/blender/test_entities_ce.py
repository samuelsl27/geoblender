# SPDX-License-Identifier: GPL-3.0-or-later
"""Hito H2 de las entidades de diseño en Blender (spec 015, T27; HU-015-1, HU-015-2; CE-015-01, CE-015-04 y CE-015-05;
E3 de §2 y §10.1 sin pantalla; RF-015-10, RF-015-12, RF-015-13, RF-015-15 a RF-015-18; plan 015 §7.1 y §7.5): el marco
**de punta a punta con las órdenes reales** y las funciones de recálculo y de reproducción que registra ``bl`` (no las del
dominio de las pruebas unitarias), en ``blender -b`` y sin pantalla: «Plataforma…» (``geoblender.des_create_platform``),
«Descartar…», «Soltar el apoyo…» y «Traer las entidades de…» de la T25 y la T26, **«Recalcular lo obsoleto»**
(``geoblender.core_recompute_stale``, el modal con su plan) y, con las funciones del dominio que las órdenes llaman, congelar,
reproducir y la verificación por recinto de la 012. Lo exhaustivo (las cuentas a mano de cada cifra, el «solo relleno» de la 014,
la lista de «Ver restricciones y límites» con su entidad) está en ``tests/unit/design/test_entities_ce.py``; aquí, que **lo
mismo ocurre con lo que registra la extensión**.

El proyecto de ``test_platform_ops`` (ventana de 60 × 60 m con celdas de 2 m y la ladera ``100 + 0,25·y + 0,0625·x``), con
una capa de plataformas más: «Sobre Carga» (el eje y el ancho de «Carga», a 112 m). La huella de «Carga» (eje de 20 m, 8 m de
ancho: los centros de celda de x = 21… 39 e y = 27… 33) son **10 × 4 = 40 celdas de 4 m²**, a mano; «Carga» corta del todo
(rasante a 105 m, el terreno de su huella queda de 108 a 111 m) y «Sobre Carga», «en corte y relleno» a 112 m de la superficie de
«Carga», sube **7 m** sobre ella: 40 · 7 · 4 = **1.120 m³** a mano (con la pendiente de 0,5 % de «Carga», 1.112 m³: la columna de
abscisa σ rellena ``7 − 0,005·σ`` m en cuatro filas). Cada CE, en su versión (V01: CE-015-01; V03: CE-015-04; V04: CE-015-05),
con las pruebas en el orden de sus letras sobre el mismo estado.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import hashlib
import json
import unittest
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.blender import test_platform_ops as platform_ops
from tests.support import blender_ext
from tests.support.fake_layout import operator_self

DISCARD = "geoblender.des_entity_discard"
OVER = "Sobre Carga"
LOADING, WORKSHOP, RAMP = platform_ops.LOADING, platform_ops.WORKSHOP, platform_ops.RAMP
WHY = "La propiedad cambia el plan: la carga no se hace"
TIMER = SimpleNamespace(type="TIMER", value="NOTHING")
MAX_TICKS = 400
CELL_M2 = platform_ops.CELL_M2
FOOTPRINT_CELLS = 10 * 4
"""La huella de «Carga», a mano: los centros de x = 21… 39 (10) por los de y = 27… 33 (4)."""
FILL_M3 = FOOTPRINT_CELLS * (112.0 - 105.0) * CELL_M2
"""1.120 m³: «Sobre Carga» sube 7 m sobre la rasante de «Carga» en sus 40 celdas de 4 m²."""
SLOPE_PCT = 0.5
FILL_AFTER_M3 = 4 * sum(7.0 - SLOPE_PCT / 100.0 * sigma for sigma in range(1, 20, 2)) * CELL_M2
"""Con la pendiente de 0,5 % de «Carga»: la columna de abscisa σ (1, 3… 19 m desde el primer vértice del eje) rellena
``7 − 0,005·σ`` m en cuatro filas: 1.112 m³."""
HELD_M2 = FOOTPRINT_CELLS * CELL_M2
"""El área que «Sobre Carga» no rellena sobre «Carga» protegida: toda su huella, 160 m² a mano."""
GRADIENT = "des.platform.plt_001.gradient_pct"


def _module(name: str) -> Any:
    return platform_ops._module(name)


def _last(work: Iterator[Any]) -> Any:
    """El resultado del último ``Progress`` de unos pasos."""
    found = None
    for found in work:
        pass
    return found.result


def _close(found: float, expected: float, relative: float = 1e-9) -> bool:
    return abs(found - expected) <= relative * abs(expected)


class EntitiesCETest(platform_ops.CreatePlatformTest):
    """La extensión habilitada una vez y el proyecto de la cantera de plataformas con una capa más y tres terrenos."""

    ground2: str
    ground3: str
    v03: Any
    v04: Any

    @classmethod
    def setUpClass(cls) -> None:
        extra = (OVER, ((20.0, 30.0), (40.0, 30.0)), 8.0, 112.0, 0.0)
        with mock.patch.object(platform_ops, "FEATURES", (*platform_ops.FEATURES, extra)):
            super().setUpClass()
        cls.ground2 = cls.write_grid("Ladera 2", platform_ops.ground())
        cls.ground3 = cls.write_grid("Ladera 3", platform_ops.ground())
        store = _module("core.versions.store")
        with cls.project.write_transaction() as conn:
            cls.v03, _ = store.create_version(conn, cls.project, feature="protegida", title="Protegida",
                                              reason=platform_ops.REASON)
            cls.v04, _ = store.create_version(conn, cls.project, feature="congelada", title="Congelada",
                                              reason=platform_ops.REASON)
        cls.project.refresh_header()
        cls.refresh()

    # --- Ayudas -------------------------------------------------------------------------------

    def activate(self, version: Any) -> None:
        """La versión activa pasa a ser ``version`` (con sus máscaras al día)."""
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=version.uid), {"FINISHED"})
        self.assertEqual(bpy.ops.geoblender.gis_compile_constraints(), {"FINISHED"})
        self.refresh()

    def made(self, **values: Any) -> None:
        """«Calcula» y «crea» una plataforma (``des_create_platform``) en la versión activa."""
        self.refresh()
        self.calculate(**values)
        self.assertEqual(self.create(), {"FINISHED"})

    def calculate_entity(self, code: str) -> None:
        """«Calcular…» (``des_entity_calculate``) y «Crear» una entidad sin calcular de la versión activa, con las órdenes reales
        (T41): la primera lanza «Plataforma…» con el código de la entidad (el temporizador que lo hace no corre en ``blender
        -b``: se hace ya) y la segunda registra el cálculo abierto."""
        def launch(idname: str, _window: Any, **values: Any) -> None:
            self.assertEqual(idname, platform_ops.PLATFORM)
            self.assertEqual(bpy.ops.geoblender.des_create_platform("EXEC_DEFAULT", in_steps=False, **values), {"FINISHED"})

        with mock.patch.object(self.des_ops, "_invoke_later", side_effect=launch):
            self.assertEqual(bpy.ops.geoblender.des_entity_calculate("EXEC_DEFAULT", entity=code), {"FINISHED"})
        self.assertEqual(self.create(), {"FINISHED"})

    def states(self, version: Any) -> dict[str, str]:
        registry = self.entities.registry(self.project, version.uid)
        return {entry.record.code: str(entry.record.state) for entry in registry}

    def current(self, version: Any, code: str) -> str:
        return str(self.entities.registry(self.project, version.uid).get(code).operation_uid)

    def volumes(self, uid: str) -> dict[str, float]:
        return {json.loads(scope)["entity"]: value for key, scope, value in self.rows(
            "SELECT key, scope, value FROM gb_figure WHERE operation_uid = ?", uid) if key == "des.supported_m3"}

    def supported(self, version: Any, code: str) -> dict[str, float | None]:
        return {row.name: row.volume_m3 for row in self.entities.dependents(self.project, version.uid, code)}

    def hashes(self, uid: str) -> dict[str, str]:
        return dict(self.rows("SELECT d.name, io.content_sha256 FROM gb_operation_io AS io JOIN gb_dataset AS d ON "
                              "d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'out'", uid))

    def causes(self, uid: str) -> set[tuple[str, str]]:
        found = set()
        for cause, subject in self.rows("SELECT cause_kind, subject_uid FROM gb_stale WHERE item_kind = 'operation' "
                                        "AND item_uid = ?", uid):
            named = self.rows("SELECT key FROM gb_parameter WHERE uid = ? UNION ALL SELECT name FROM gb_dataset "
                              "WHERE uid = ?", subject, subject)
            found.add((cause, subject if not named else named[0][0]))
        return found

    def stale_in(self, version: Any) -> list[str]:
        """Los nombres de las operaciones vigentes de ``version`` que están obsoletas ahora."""
        found = []
        for op_type, settings in self.rows(
                "SELECT o.op_type, o.settings FROM gb_operation AS o JOIN gb_revision AS r ON r.uid = o.revision_uid "
                "WHERE r.version_uid = ? AND o.status = 'done' AND o.superseded_by IS NULL AND EXISTS "
                "(SELECT 1 FROM gb_stale AS s WHERE s.item_kind = 'operation' AND s.item_uid = o.uid) "
                "ORDER BY o.fid", version.uid):
            found.append(str(json.loads(settings).get("name", op_type)))
        return found

    def change(self, version: Any, key: str, value: object) -> None:
        """Cambia el parámetro de versión ``key`` de ``version`` (ADOPTADO, con su motivo)."""
        with self.project.write_transaction() as conn:
            _module("core.params").ParameterStore(self.project).change(
                conn, key, value=value, version=version.uid, reason="Prueba del hito H2")

    def declare_support(self, version: Any, code: str, text: str) -> None:
        """La persona declara que ``code`` se apoya en ``text`` (como lo hará el diálogo de la T31)."""
        with self.project.write_transaction() as conn:
            _module("core.params").ParameterStore(self.project).create(
                conn, f"des.platform.{code.lower().replace('-', '_')}.supports", text, kind="ADOPTADO",
                source="Criterio de la prueba", source_kind="person", decided_by=platform_ops.PERSON,
                reason="Dependencia declarada", version=version.uid)

    def recompute_unit(self, version: Any, code: str) -> None:
        """«Recalcular» la entidad ``code`` con sus parámetros de ahora (la función de recálculo que registró ``bl``)."""
        uid = self.current(version, code)
        ((settings,),) = self.rows("SELECT settings FROM gb_operation WHERE uid = ?", uid)
        request = _module("core.provenance.recompute").RecomputeRequest(
            self.project, uid, platform_ops.PLATFORM_TYPE, json.loads(settings), (), (), version=version.uid)
        function = _module("core.provenance.contract").operation_def(platform_ops.PLATFORM_TYPE).recompute
        function(request)
        for _ in range(MAX_TICKS):
            if not self.tick():
                return
        self.fail("las colas de los pasos no se vacían")

    def tick(self) -> bool:
        """Un paso de cada cola de pasos del recálculo (``des``, las máscaras de ``gis`` y la verificación de ``res``: sus
        temporizadores no corren en ``blender -b``, se avanzan a mano); si queda algo pendiente."""
        gis_ops, res_ops = _module("bl.ops.gis"), _module("bl.ops.res")
        pending = bool(self.des_ops.pending_runs() or gis_ops.pending_mask_runs() or res_ops.pending_runs())
        self.des_ops.des_tick()
        gis_ops.masks_tick()
        res_ops.res_tick()
        return pending

    def recompute(self, **props: Any) -> Any:
        """Lanza «Recalcular lo obsoleto» y lo lleva hasta el final: el modal (con la cola de ``des``, que en ``blender -b``
        se avanza a mano), sin pedir ninguna confirmación."""
        with mock.patch.object(self.des_ops, "_ask_confirmation") as ask, \
                mock.patch.object(_module("bl.ops.incorporation"), "status_text"):
            self.assertEqual(getattr(bpy.ops.geoblender, "core_recompute_stale")("EXEC_DEFAULT", **props),
                             {"RUNNING_MODAL"})
            found = [op for op in bpy.context.window.modal_operators
                     if isinstance(op, self.session.GEOBLENDER_OT_core_recompute_stale)
                     and getattr(op, "_steps", None) is not None]
            self.assertEqual(len(found), 1)
            operator = found[0]
            self.addCleanup(lambda: operator._steps is None or operator.cancel(bpy.context))
            for _ in range(MAX_TICKS):
                state = operator.modal(bpy.context, TIMER)
                self.tick()
                if state != {"RUNNING_MODAL"}:
                    ask.assert_not_called()
                    # Lo descartado no vuelve al plan (T40, hallazgos C-4 y E-3): antes la P1 descartada de V01 fallaba
                    # en cada «Recalcular lo obsoleto» del proyecto, también en las demás versiones (``test_j``).
                    self.assertEqual(self.names_of(operator, "failed"), [], "ninguna unidad falla")
                    return operator
        self.fail("el recálculo no termina")

    def names_of(self, operator: Any, status: str) -> list[str]:
        """Los nombres de las operaciones de las unidades de ``operator`` que acabaron en ``status``."""
        found = []
        for result in operator.result.results:
            if str(result.status) == status:
                for uid in result.unit.operations:
                    ((op_type, settings),) = self.rows("SELECT op_type, settings FROM gb_operation WHERE uid = ?", uid)
                    found.append(str(json.loads(settings).get("name", op_type)))
        return found

    def fake(self, idname: str, **values: Any) -> tuple[Any, Any, mock.Mock]:
        """El operador de mentira, el contexto con que se abre el diálogo (sin ventana) y el diálogo."""
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=platform_ops.window(),
                                  window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        fields: dict[str, Any] = {"entity": "", "target": "", "reason": "", "in_steps": False,
                                  "provenance_dialog": False, "report": lambda kind, text: None, **values}
        return operator_self(self.commands.registered_class(idname), **fields), context, dialog

    def hand_volume(self, version: Any, result: str, start: str, entity: str) -> float:
        """Lo que ``result`` apoya en ``entity`` desde ``start`` **por los ficheros** (RF-015-15): ``r − máx(s, e)`` sobre
        la huella de «Carga» (40 celdas, a mano) y el espesor mínimo de la 012 (0,02 m)."""
        read = lambda name: self.surfaces.read_surface(self.project, name, version_uid=version.uid).values  # noqa: E731
        x, y = platform_ops.centers()
        footprint = (x > 20.0) & (x < 40.0) & (y > 26.0) & (y < 34.0)
        self.assertEqual(int(footprint.sum()), FOOTPRINT_CELLS)
        thick = (read(result) - np.maximum(platform_ops.ground() if start == "ground" else read(start), read(entity)))[footprint]
        return float(thick[thick > 0.02].sum()) * CELL_M2

    # --- CE-015-01 (V01) ----------------------------------------------------------------------

    def test_a_the_platform_that_fills_on_another_rests_on_it_and_a_declared_dependency_is_registered_the_same(self) -> None:
        """CE-015-01, RF-015-15 (D-11, D-9; las órdenes reales): P2 «Sobre Carga» («en corte y relleno», de la superficie de P1
        «Carga») rellena 7 m sobre su huella y **se apoya en ella** con **1.120 m³ a mano**, a ≤ 10⁻⁹ relativo (y por los ficheros);
        P3 «Taller» (de otro terreno) **declara** apoyarse en P1 y se registra igual, con 0 m³; lo que se apoya en P1 es **una
        sola lista**. P4 «Rampa» también la declara (la descartará la salida 2)."""
        self.made()
        self.made(name=OVER, feature=OVER, start="entity:PLT-001", mode="CUT_FILL")
        self.made(name=WORKSHOP, feature=WORKSHOP, start=self.ground2, start_level="107,5", gradient="0", width="5",
                  reach="6")
        self.made(name=RAMP, feature=RAMP, start=self.ground3, start_level="100", gradient="0", width="4", reach="6")
        for code in ("PLT-003", "PLT-004"):
            self.declare_support(self.v01, code, "PLT-001")
            self.recompute_unit(self.v01, code)
        self.assertEqual(set(self.states(self.v01).values()), {"current"})
        listed = self.entities.dependents(self.project, self.v01.uid, "PLT-001")
        self.assertEqual([(row.name, row.roles) for row in listed],
                         [(OVER, ("supported_on", "surface")), (WORKSHOP, ("supported_on",)), (RAMP, ("supported_on",))])
        self.assertTrue(_close(listed[0].volume_m3, FILL_M3), listed[0].volume_m3)
        self.assertEqual([row.volume_m3 for row in listed[1:]], [0.0, 0.0])
        psf = lambda name: self.dprov.dataset_name("psf", name)  # noqa: E731
        by_files = self.hand_volume(self.v01, psf(OVER), psf(LOADING), psf(LOADING))
        self.assertTrue(_close(by_files, FILL_M3), by_files)
        self.assertEqual(self.volumes(self.current(self.v01, "PLT-002")), {"PLT-001": listed[0].volume_m3})
        for code in ("PLT-003", "PLT-004"):
            self.assertEqual(self.volumes(self.current(self.v01, code)), {"PLT-001": 0.0}, code)

    def test_b_changing_the_first_makes_the_rest_obsolete_with_the_cause_and_recompute_stale_redoes_it_in_order(self) -> None:
        """CE-015-01, RF-015-16, RF-008-26, E3 (cambiar una entidad y ver la cascada en «Recalcular lo obsoleto»): la
        pendiente de P1 pasa de 0 a 0,5 %: P1, P2, P3 y P4 quedan obsoletas **con la misma causa raíz**, el motivo dice qué
        entidad y qué cambió y «Recalcular lo obsoleto» (el modal real, con las funciones que registra ``bl``) las rehace **en
        orden de dependencia** (P1 antes que P2); no queda nada y P2 sigue apoyada en P1 con **1.112 m³ a mano**."""
        ui = _module("bl.ui.provenance")
        codes = ("PLT-001", "PLT-002", "PLT-003", "PLT-004")
        old = {code: self.current(self.v01, code) for code in codes}
        self.change(self.v01, GRADIENT, SLOPE_PCT)
        ui.refresh(force=True)
        for code, uid in old.items():
            self.assertEqual(self.causes(uid), {("parameter_changed", GRADIENT)}, code)
        self.assertEqual(set(self.states(self.v01).values()), {"stale"})
        self.assertEqual(self.entities.stale_reason(self.project, self.v01.uid, "PLT-002"),
                         f"Obsoleto: cambió Pendiente de la rasante de la plataforma · {LOADING}")
        operator = self.recompute()
        self.assertEqual(operator.result.cancelled, False)
        done = self.names_of(operator, "done")
        layer = "des.entity_layer"  # T30: la capa de entidades consume los datos de las cuatro y se rehace la última
        self.assertEqual(sorted(done), sorted([LOADING, OVER, WORKSHOP, RAMP, layer]))
        self.assertLess(done.index(LOADING), done.index(OVER), "orden de dependencia")
        self.assertEqual(done.index(layer), len(done) - 1, "la capa de entidades, tras las entidades que enseña")
        self.assertEqual(set(self.states(self.v01).values()), {"current"})
        self.assertEqual(self.stale_in(self.v01), [])
        listed = {row.name: row.volume_m3 for row in self.entities.dependents(self.project, self.v01.uid, "PLT-001")}
        self.assertTrue(_close(listed[OVER], FILL_AFTER_M3), (listed[OVER], FILL_AFTER_M3))
        self.assertAlmostEqual(FILL_AFTER_M3, 1112.0, places=9)

    def test_c_brought_to_another_version_they_are_not_calculated_and_the_dependency_is_detected_again(self) -> None:
        """CE-015-01, RF-015-18, RF-009-01, D-18, C-12: «Traer las entidades de V01» (la orden real) a V02 trae las definiciones
        de P1 y P2 **sin calcular** (ningún resultado en V02); calculadas allí **con la orden real, «Calcular…» del menú «Entidad
        ▾»** (T41; antes, por la API con su código: en la interfaz no se podían calcular) **la dependencia se detecta de nuevo**
        con lo mismo que en V01 (1.112 m³ a mano)."""
        self.activate(self.v02)
        self.addCleanup(self.activate, self.v01)
        self.assertEqual(bpy.ops.geoblender.des_entity_bring("EXEC_DEFAULT", source="V01", entities="PLT-001, PLT-002"),
                         {"FINISHED"})
        self.assertEqual(self.states(self.v02), {"PLT-001": "uncalculated", "PLT-002": "uncalculated"})
        self.assertEqual(self.rows("SELECT count(*) FROM gb_dataset WHERE version_uid = ? AND name LIKE 'des!_%' ESCAPE '!'",
                                   self.v02.uid), [(0,)])
        for code in ("PLT-001", "PLT-002"):  # por el orden de la cadena: P2 parte de la superficie de P1
            self.calculate_entity(code)
        self.assertEqual(self.states(self.v02), {"PLT-001": "current", "PLT-002": "current"})
        again = self.volumes(self.current(self.v02, "PLT-002"))
        self.assertTrue(_close(again["PLT-001"], FILL_AFTER_M3), again)
        self.assertEqual(again, self.volumes(self.current(self.v01, "PLT-002")))

    def test_d_discarding_the_first_lists_what_rests_on_it_before_and_leaves_it_as_support_removed(self) -> None:
        """CE-015-01, RF-015-17, RF-009-12, E3, error 59 (la orden real): el diálogo de «Descartar…» enseña **una sola lista**
        antes (P2 con sus 1.112 m³ a mano, P3 y P4 con 0); aceptar descarta P1 sin borrar nada y las tres quedan en **«apoyo
        retirado»** con la causa; «Recalcular lo obsoleto» **no las recalcula** (se rehúsan: se descartó y no tiene sucesor) y no
        se crea ninguna operación más que la declaración que sigue a descartar."""
        cls = self.commands.registered_class(DISCARD)
        fake, context, _dialog = self.fake(DISCARD, entity="PLT-001")
        self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
        lines = fake._plan.lines("es")
        self.assertEqual([line.split(":")[0] for line in lines],
                         [f"{OVER} (Plataforma)", f"{WORKSHOP} (Plataforma)", f"{RAMP} (Plataforma)"])
        self.assertRegex(lines[0], r": 1\s?112 m³ apoyados$")
        self.assertTrue(lines[1].endswith(": 0 m³ apoyados") and lines[2].endswith(": 0 m³ apoyados"), lines)
        operations = self.rows("SELECT uid, status FROM gb_operation ORDER BY fid")
        self.assertEqual(bpy.ops.geoblender.des_entity_discard("EXEC_DEFAULT", entity="PLT-001", reason=WHY,
                                                               in_steps=False), {"FINISHED"})
        self.assertEqual(self.states(self.v01), {"PLT-001": "discarded", "PLT-002": "support_removed",
                                                 "PLT-003": "support_removed", "PLT-004": "support_removed"})
        wanted = f"Apoyo retirado: se descartó la plataforma {LOADING}"
        for code in ("PLT-002", "PLT-003", "PLT-004"):
            self.assertEqual(self.entities.stale_reason(self.project, self.v01.uid, code), wanted)
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation"), [(len(operations) + 2,)],
                         "solo la declaración nueva y la capa de entidades nueva (lo que sigue a descartar)")
        before = self.rows("SELECT uid, status FROM gb_operation ORDER BY fid")
        operator = self.recompute()
        self.assertEqual(self.names_of(operator, "done"), [])
        refused = {str(result.code) for result in operator.result.results if str(result.status) == "refused"}
        self.assertEqual(refused, {"core.recompute_no_successor_release"})
        self.assertEqual(self.rows("SELECT uid, status FROM gb_operation ORDER BY fid"), before, "no se crea nada")
        self.assertEqual(self.states(self.v01)["PLT-002"], "support_removed")

    def test_e_the_three_exits_remake_discard_and_give_as_good_with_a_reason(self) -> None:
        """CE-015-01, RF-015-17, RF-008-26 (las tres salidas, con las órdenes reales): P3, que declaró apoyarse en P1, se da
        **por buena con un motivo** (``geoblender.des_entity_release_support``: se repite sin ese apoyo, su salida no cambia y
        queda el motivo y el decisor en sus ajustes y un evento); P2, que parte de la superficie de P1, se **rehace sobre otra
        superficie** (su partida pasa al terreno; ``platform_run(code=, supersedes=)``) y sale de «apoyo retirado»; y P4 «Rampa»,
        que también declaró apoyarse en P1, se **descarta** (queda como registro, con su evento). Nada se recalcula por su
        cuenta: lo que se decidió sale de «apoyo retirado»."""
        old = self.current(self.v01, "PLT-003")
        hashes = self.hashes(old)
        self.assertEqual(bpy.ops.geoblender.des_entity_release_support(
            "EXEC_DEFAULT", target="PLT-003", reason=WHY, in_steps=False), {"FINISHED"})
        new = self.current(self.v01, "PLT-003")
        self.assertNotEqual(new, old)
        self.assertEqual(self.hashes(new), hashes, "su salida no cambia")
        ((settings,),) = self.rows("SELECT settings FROM gb_operation WHERE uid = ?", new)
        (released,) = json.loads(settings)["supports_released"]
        self.assertEqual((released["entity"], released["reason"], released["by"]),
                         ("PLT-001", WHY, self.project.session.user_host))
        self.assertEqual(self.states(self.v01)["PLT-003"], "current")
        # P4: descartarla (antes de rehacer P2: lo que se rehace ya no se apoya en lo descartado)
        self.assertEqual(bpy.ops.geoblender.des_entity_discard("EXEC_DEFAULT", entity="PLT-004", reason=WHY,
                                                               in_steps=False), {"FINISHED"})
        self.assertEqual(self.states(self.v01)["PLT-004"], "discarded")
        # P2: rehacerla sobre otra superficie
        model = _module("design.model")
        asked = model.PlatformRequest(
            name=OVER, fields=model.PlatformFields(layer=platform_ops.LAYER, start_level_field="cota_inicial",
                                                   gradient_field="pendiente", width_field="ancho"),
            feature=OVER, start=self.ground, mode=model.PlatformMode.CUT_FILL, edge_angle_deg=35.0, reach_m=10.0)
        self.change(self.v01, "des.platform.plt_002.start", self.ground)
        steps = _module("design.steps")
        _last(steps.platform_run(self.project, asked, version=self.v01.uid, code="PLT-002",
                                 supersedes=self.current(self.v01, "PLT-002"))).create()
        self.assertEqual(self.states(self.v01), {"PLT-001": "discarded", "PLT-002": "current", "PLT-003": "current",
                                                 "PLT-004": "discarded"})
        self.assertNotIn(OVER, self.supported(self.v01, "PLT-001"))
        self.assertEqual([row.name for row in self.entities.retired_supports(self.project, self.v01.uid)], [])
        events = _module("core.project.events")
        with self.project.read() as conn:
            found = events.read_events(conn, events.EventKind.ENTITY_DISCARDED)
        self.assertEqual([item.data["entity"] for item in found], ["PLT-001", "PLT-004"])

    def test_f_a_version_that_starts_from_this_one_gets_the_discarded_one_discarded(self) -> None:
        """CE-015-01, RF-015-17, RF-009-01, D-12 (hallazgo (a) de la T26): una versión que parte de V01 recibe P1, descartada con
        datos, **descartada** (no «viva y sin calcular»), igual que P4, y las demás sin calcular."""
        store = _module("core.versions.store")
        with self.project.write_transaction() as conn:
            child, _ = store.create_version(conn, self.project, feature="hija", title="Hija", reason=platform_ops.REASON,
                                            parent="V01")
        self.project.refresh_header()
        mine = self.states(child)
        self.assertEqual((mine["PLT-001"], mine["PLT-004"]), ("discarded", "discarded"))
        self.assertEqual({code for code, state in mine.items() if state == "uncalculated"},
                         {"PLT-002", "PLT-003"})
        self.assertEqual(self.entities.registry(self.project, self.v01.uid).get("PLT-001").record.state.value, "discarded")

    # --- CE-015-04 (V03) ----------------------------------------------------------------------

    def test_g_a_cut_platform_that_protects_declares_its_restriction_and_what_overlaps_it_fills_zero(self) -> None:
        """CE-015-04, RF-015-10, RF-015-12, RF-015-13, E3 (error 51, las órdenes reales): en V03, P1 «Carga» («en corte», con 4 m
        de resguardo) declara «sin relleno» (``dec__plt_001``, con el nombre de la entidad, en «Ver restricciones y límites»)
        y las máscaras la llevan; P2 «Sobre Carga» («en corte y relleno», de la superficie de P1, con la misma huella) **rellena 0
        m³** en ella (su superficie es la de P1 en esas celdas) y el resumen dice el área que no rellena, **160 m² a mano**, con la
        restricción y la entidad que la declara; y **la verificación de la 012 da «cumple»** con 0 m³ en su recinto."""
        self.activate(self.v03)
        self.made(protect=True, guard="4")
        access = _module("gis.masks.access")
        masks = access.load_masks(self.project, self.v03.uid)
        zone = masks.zone("dec__plt_001").mask(masks.classes.shape)
        self.assertEqual(int(zone.sum()), (10 + 4) * (4 + 4), "la huella ensanchada dos celdas por cada lado, a mano")
        self.assertFalse(masks.fill_allowed()[zone].any())
        listed = [item for item in _module("gis.masks.store").listed_constraints(self.project, version=self.v03.uid)
                  if item.declared]
        self.assertEqual([(item.entity_code, item.entity_name, item.state, item.buffer_out_m) for item in listed],
                         [("PLT-001", LOADING, "active", 4.0)])
        self.refresh()
        held = self.calculate(name=OVER, feature=OVER, start="entity:PLT-001", mode="CUT_FILL")
        notice = next(item for item in held.summary.notices if item.code == "des.entity_held")
        self.assertEqual((notice.values["entity"], notice.values["constraint"], notice.values["other"], notice.values["area"]),
                         (OVER, "dec__plt_001", LOADING, HELD_M2))
        self.assertEqual(self.create(), {"FINISHED"})
        psf = lambda name: self.surfaces.read_surface(self.project, self.dprov.dataset_name("psf", name),  # noqa: E731
                                                       version_uid=self.v03.uid).values
        x, y = platform_ops.centers()
        footprint = (x > 20.0) & (x < 40.0) & (y > 26.0) & (y < 34.0)
        np.testing.assert_array_equal(psf(OVER)[footprint], psf(LOADING)[footprint])
        self.assertEqual(self.volumes(self.current(self.v03, "PLT-002")), {})
        cstore, surfaces = _module("reserves.compliance_store"), _module("reserves.surfaces")
        result = _last(cstore.verify_project_steps(
            self.project, version=self.v03.uid, name="Revisión de Carga", start=surfaces.SurfaceRef(
                dataset=self.ground, label="Partida"), finals=tuple(
                surfaces.SurfaceRef(dataset=self.dprov.dataset_name("psf", name), label=name) for name in (LOADING, OVER))
        )).result
        self.assertEqual(result.fails, (False, False))
        for check in result.finals:
            zone_total = check.zone("dec__plt_001")
            self.assertEqual((zone_total.counted_m3, str(zone_total.verdict)), (0.0, "complies"))
        # el ciclo de D-21 al crearla: P1, que consumió las máscaras de antes, queda obsoleta y «Recalcular lo obsoleto» la rehace
        operator = self.recompute()
        self.assertIn(LOADING, self.names_of(operator, "done"))
        self.assertEqual(set(self.states(self.v03).values()), {"current"})

    def test_h_changing_its_own_restriction_leaves_it_obsolete_and_recomputing_does_not_change_its_output(self) -> None:
        """CE-015-04, RF-008-26, D-21 (lo que da el código, con «Recalcular lo obsoleto» real): P1 pasa de 4 a 6 m de resguardo y
        queda obsoleta (por ese parámetro); las máscaras se siguen entregando; lo que sigue a cambiarlo declara y recompila; **una
        sola pasada** de «Recalcular lo obsoleto» rehace P1, P2 y la verificación, **sin recalcular la declaración ni las
        máscaras** (pierden su marca) y la salida de P1 **no cambia**."""
        access, ui = _module("gis.masks.access"), _module("bl.ui.provenance")
        key = "des.platform.plt_001.guard_m"
        first, second = self.current(self.v03, "PLT-001"), self.current(self.v03, "PLT-002")
        hashes = self.hashes(first)
        self.change(self.v03, key, 6.0)
        self.assertEqual(self.causes(first), {("parameter_changed", key)})
        self.assertIs(access.mask_state(self.project, self.v03.uid)[0], access.MaskState.CURRENT)
        chain = _last(_module("design.entity_store").after_entity_change(self.project, self.v03))
        self.assertEqual((chain.declared, chain.declaration_changed, chain.masks_compiled), (1, True, True))
        ui.refresh(force=True)
        declaration = self.rows("SELECT uid FROM gb_operation WHERE op_type = ? AND status = 'done' AND superseded_by "
                                "IS NULL AND settings LIKE '%PLT-001%'", platform_ops.DECLARE_TYPE)
        operator = self.recompute()
        done = self.names_of(operator, "done")
        self.assertIn(LOADING, done)
        self.assertEqual(done.count(LOADING), 1)
        self.assertNotIn(platform_ops.DECLARE_TYPE, done, "la declaración no se recalcula: pierde su marca")
        self.assertNotIn("gis.compile_constraints", done, "ni las máscaras")
        self.assertEqual(self.hashes(self.current(self.v03, "PLT-001")), hashes, "la salida de P1 no cambia")
        self.assertEqual(self.hashes(self.current(self.v03, "PLT-002")), self.hashes(second), "ni la de P2")
        self.assertEqual(self.states(self.v03), {"PLT-001": "current", "PLT-002": "current"})
        self.assertEqual(self.stale_in(self.v03), [])
        self.assertTrue(declaration)

    def test_i_a_cut_and_fill_platform_cannot_declare_its_own_prohibition_and_discarding_takes_the_restriction_out(self) -> None:
        """CE-015-04, RF-015-12, RF-015-10, RF-015-17, E3 (la orden real): «Plataforma…» «en corte y relleno» que protege se
        rechaza (``des.platform_protect_cut_fill``: la entidad y el modo) sin escribir nada; descartar P1 **quita su restricción de
        las máscaras** (su código sale; el relleno se admite otra vez en su zona), la lista de restricciones ya no la trae y
        P2, que parte de su superficie, queda en «apoyo retirado»."""
        self.refresh()
        before = self.state()
        with self.assertRaises(RuntimeError) as refused:
            bpy.ops.geoblender.des_create_platform("EXEC_DEFAULT", **self.form(
                name="No debe", feature=WORKSHOP, start="entity:PLT-002", mode="CUT_FILL", protect=True, guard="4"))
        self.assertIn("«en corte y relleno»", str(refused.exception))
        self.assertEqual(self.state(), before)
        access = _module("gis.masks.access")
        zone = access.load_masks(self.project, self.v03.uid).zone("dec__plt_001").mask(
            access.load_masks(self.project, self.v03.uid).classes.shape)
        self.assertEqual(bpy.ops.geoblender.des_entity_discard("EXEC_DEFAULT", entity="PLT-001", reason=WHY,
                                                               in_steps=False), {"FINISHED"})
        masks = access.load_masks(self.project, self.v03.uid)
        self.assertNotIn("dec__plt_001", masks.zones)
        self.assertTrue(masks.fill_allowed()[zone].all(), "el relleno se admite otra vez donde protegía")
        self.assertEqual([item for item in _module("gis.masks.store").listed_constraints(
            self.project, version=self.v03.uid) if item.declared], [])
        self.assertEqual(self.states(self.v03), {"PLT-001": "discarded", "PLT-002": "support_removed"})

    # --- CE-015-05 (V04) ----------------------------------------------------------------------

    def test_j_freezing_and_changing_the_slope_makes_it_obsolete_and_recomputed_it_changes_and_the_frozen_one_does_not(self) -> None:
        """CE-015-05, RF-015-16, RF-009-11, RF-009-19 (las órdenes reales): en V04, P1 «Carga» y P2 «Sobre Carga» (que se le
        apoya, 1.120 m³ a mano) se congelan en V04.r1; cambiar la pendiente de P1 en la revisión abierta deja obsoletas, con su
        causa, a las dos y «Recalcular lo obsoleto» las rehace **cambiadas** (1.112 m³ a mano); V04.r1 **no cambia** (su estado,
        sus elementos y los ficheros de su instantánea) y se reproduce bit a bit."""
        self.activate(self.v04)
        self.made()
        self.made(name=OVER, feature=OVER, start="entity:PLT-001", mode="CUT_FILL")
        self.assertTrue(_close(self.supported(self.v04, "PLT-001")[OVER], FILL_M3))
        freeze, reproduce = _module("core.versions.freeze"), _module("core.versions.reproduce")
        plan = freeze.freeze_plan(self.project, self.v04.uid)  # T32 (RF-015-04, RF-012-25): pide verificar la última
        self.assertEqual([entry.name for entry in plan.accept if entry.finding], ["des_psf_sobre_carga"],
                         "la última de la cadena (P2), no la intermedia (P1)")
        frozen = _last(freeze.freeze_steps(self.project, self.v04.uid, reason="Entrega de la prueba",
                                           accepted=freeze.Acceptance.of(plan)))  # aceptada sin verificar
        revision = str(frozen.frozen.uid)
        items = self.rows("SELECT * FROM gb_revision_item WHERE revision_uid = ? ORDER BY fid", revision)
        files = {str(path): str(sha) for path, sha in self.rows(
            "SELECT DISTINCT snapshot_path, file_sha256 FROM gb_revision_item WHERE revision_uid = ? AND "
            "snapshot_path IS NOT NULL AND copied = 1", revision)}
        self.assertTrue(items and files)
        old = {code: self.current(self.v04, code) for code in ("PLT-001", "PLT-002")}
        before = {code: self.hashes(uid) for code, uid in old.items()}
        self.change(self.v04, GRADIENT, SLOPE_PCT)
        for code, uid in old.items():
            self.assertEqual(self.causes(uid), {("parameter_changed", GRADIENT)}, code)
        self.assertEqual(self.states(self.v04), {"PLT-001": "stale", "PLT-002": "stale"})
        operator = self.recompute()
        self.assertEqual(sorted(self.names_of(operator, "done")), sorted([LOADING, OVER, "des.entity_layer"]))
        for code in old:
            self.assertNotEqual(self.hashes(self.current(self.v04, code)), before[code], f"{code}: cambió")
        self.assertTrue(_close(self.supported(self.v04, "PLT-001")[OVER], FILL_AFTER_M3))
        self.assertEqual(self.rows("SELECT state FROM gb_revision WHERE uid = ?", revision), [("frozen",)])
        self.assertEqual(self.rows("SELECT * FROM gb_revision_item WHERE revision_uid = ? ORDER BY fid", revision), items)
        for path, sha in files.items():
            self.assertEqual(hashlib.sha256((Path(self.project.root) / path).read_bytes()).hexdigest(), sha, path)
        self.assertEqual({code: self.hashes(uid) for code, uid in old.items()}, before)
        report = _last(reproduce.reproduce_steps(self.project, revision))
        self.assertTrue(report.outputs)
        self.assertTrue(all(check.same for check in report.outputs))
        self.assertTrue(all(check.same for check in report.figures))
        self.assertTrue(report.matches)
        self.assertFalse(report.not_reproducible)
        self.activate(self.v01)

    def test_z_disabling_geoblender_leaves_no_temporary(self) -> None:
        """Principio 8: tras todo lo anterior, desactivar Geoblender no deja ningún temporal."""
        blender_ext.release()
        self.assertFalse(any(".tmp" in name for name in self.names()))


for _name in dir(platform_ops.CreatePlatformTest):  # sus pruebas son suyas: aquí solo los ayudantes
    if _name.startswith("test_"):
        setattr(EntitiesCETest, _name, None)
del _name


if __name__ == "__main__":
    unittest.main()

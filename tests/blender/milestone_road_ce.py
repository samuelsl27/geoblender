# SPDX-License-Identifier: GPL-3.0-or-later
"""Hito H2 de las pistas y rampas en Blender (spec 017, T25; HU-017-1 a HU-017-3; E1 a E5 sin pantalla; CE-017-05 a CE-017-09 y el marco de la 015 con la pista; RF-017-01 a RF-017-03,
RF-017-05, RF-017-17, RF-017-24, RF-015-04, RF-015-15 a RF-015-18, RF-009-11; plan 017 §7.1 y §7.5): lo que ``tests/unit/design/milestone_road_ce.py`` hace con las funciones del dominio y los tipos
que registran las pruebas, **con lo que registra la extensión** —las funciones de recalcular y de reproducir de ``des.road`` y ``des.road_access`` que hay en ``bl/ops/des.py``, **«Recalcular lo
obsoleto»** (``geoblender.core_recompute_stale``, el modal con su plan), «Plataforma…», «Descartar…» y «Traer las entidades de…» (las órdenes de la 015)—, en ``blender -b`` y sin pantalla. **Las órdenes
de la pista y de la accesibilidad son de la fase G** (T29 y T30): aquí se recorren el dominio y la ``Calculation`` dentro de Blender (``design.steps.road_run`` y ``access_run``).

El proyecto es **el de las pistas de las pruebas sin Blender** (``tests.support.road_data``: la cantera de la 015 con los terrenos como rejillas y las capas, en la de 2 m), construido una vez por
proceso con la copia de ``geoblender`` de las pruebas sin Blender, copiado y **abierto por la extensión** (la otra copia, la de ``bl_ext``); con las capas y el terreno que le faltan para la 017 y el
perfil de referencia. Las cuentas a mano, las exhaustivas y los casos de referencia están en el hito sin Blender: aquí, que **lo mismo ocurre con lo que registra la extensión**. Las pruebas, **en el
orden de sus letras** sobre el mismo estado.

- **E1** (``test_a``): la plataforma ``P1`` (la orden real), la «Pista a P1», el «Ramal» (su origen es el eje de la anterior) y el relleno posterior sobre la calzada (la orden real).
- **E5, la cascada** (``test_b``): cambiar la cota de ``P1`` y «Recalcular lo obsoleto» (el modal real): las cuatro obsoletas con su causa, repetidas en orden, y la pista llega a la cota nueva.
- **E3** (``test_c``): «sobre un eje» al 10,5 % de media con pm = 10 %: el aviso, la confirmación y el motivo, que quedan en los ajustes.
- **E2 y CE-017-05** (``test_d``): el tajo de la 014 (una operación de prueba), el «solo relleno» posterior, la pista que parte de él **sin avisar de su cantera** (hallazgo H2-1), la pista sobre la
  final («no llega al fondo») y la accesibilidad (125 m sobre la explotación y 140 m sobre la final).
- **E4 y CE-017-07** (``test_e``): la accesibilidad de la cantera con bancos (cota mínima 115 m y máxima 140 m).
- **E5, traer** (``test_f``): traer la cadena a V02 con «Traer las entidades de…»: sin calcular.
- **Congelar y reproducir** (``test_g``): lo que hay en V01 congelado se reproduce **sin proyecto** con las funciones que registra la extensión: el mismo hash de cada dato de cada pista y de la accesibilidad.
- **E5, descartar** (``test_h``): descartar la pista principal (la orden real): el ramal y el relleno quedan en «apoyo retirado» y «Recalcular lo obsoleto» no los recalcula.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.blender import test_platform_ops as platform_ops
from tests.support import blender_ext
from tests.support import constraints_project as cproject
from tests.support import res_fixtures
from tests.support import road_data as rd
from tests.support import stockpile_data as sdata
from tests.support.core_fixtures import FakeClock
from tests.support.trees import remove_tree

TIMER = SimpleNamespace(type="TIMER", value="NOTHING")
MAX_TICKS = 400
PERSON = platform_ops.PERSON
PLATFORM, FILL, FIRST, SECOND = "P1", "Relleno sobre la calzada", "Pista a P1", "Ramal"
PLATFORM_LAYER = "gis_fea_pistas_a_p1"
A15, A15_NAME, A15_PROFILE = "gis_dtm_a15", "Pista A15", "ACCESO_A15"
REASON = "Opción A15 de la propiedad (N-15)"
NEW_M = 111.6
"""La cota nueva de ``P1`` (0,4 m más baja que la de la capa: más alta, la plataforma plana sube en contra de su rasante)."""
RAMP = rd.dataset_of("rampa")
PROBE = "des.probe_road_h2_blender"
PIT_FILL, PIT_ROAD, PIT_FINAL_ROAD = "Relleno del fondo", "Pista al fondo", "Pista de la final"
PIT_FILL_LAYER, PIT_POINTS, PIT_ENTRY = "gis_fea_h2_relleno", "gis_fea_h2_puntos", "gis_fea_h2_entrada"
ROUTE_FIELDS = ("mesh_m", "level_step_m", "max_cut_fill_m", "lambda_per_m", "turn_m", "margin_m", "simplify_m", "arrival_tol_m", "search_budget")
WHY = "La pista principal se hace por otro trazado"
CELL_M2 = 4.0


def _module(name: str) -> Any:
    return platform_ops._module(name)


def _last(work: Any) -> Any:
    """El resultado de los últimos pasos de ``work`` que lo llevaron."""
    found = None
    for step in work:
        found = step.result if step.result is not None else found
    return found


def _drive(work: Any) -> Any:
    """Lo que devuelve un generador de unidades de preparación."""
    while True:
        try:
            next(work)
        except StopIteration as stop:
            return stop.value


class RoadCETest(unittest.TestCase):
    """La extensión habilitada una vez y el proyecto de las pistas (rejilla de 2 m) abierto por ella."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        folder = Path(tempfile.mkdtemp(prefix="gb-h2r-"))
        cls.addClassCleanup(remove_tree, folder)
        for name, module in (("ps", "bl.scene.project_session"), ("session", "bl.ops.core_provenance"), ("commands", "bl.ui.commands"), ("des_ops", "bl.ops.des"),
                             ("core_ops", "bl.ops.core"), ("panels", "bl.ui.des_panels"), ("dprov", "design.provenance"), ("entities", "design.entities"),
                             ("surfaces", "design.surfaces"), ("i18n", "core.i18n")):
            setattr(cls, name, _module(module))
        # El proyecto: se construye (una vez por proceso) y se le escribe lo que falta con **la otra copia** del paquete, la de las pruebas sin Blender, y lo abre la extensión.
        made = rd.project_template(rd.COARSE_STEP_M)
        shutil.copytree(made["folder"] / "proyectos", folder / "proyectos")
        clock = FakeClock(made["now"])
        with cproject.constraints_registered():
            plain = rd._open(folder, made, clock)
            try:
                cls.extend_project(plain, clock)
            finally:
                plain.close()
        contract = _module("core.provenance.contract")
        for definition in (contract.OperationDef(cproject.EDIT_TYPE, "1.0", "core", "Constraints of the tests", False),
                           contract.OperationDef("gis.test_layers", "1.0", "gis", "Layers of the tests", False)):
            contract.register_operation(definition)
            cls.addClassCleanup(contract.unregister_operation, definition.op_type)
        opened = _module("core.project.open").open_project(folder / "proyectos" / made["name"], cls.ps.session(), cls.ps.userdata())
        cls.project = opened.project
        cls.addClassCleanup(cls.project.close)
        with cls.project.read() as conn:
            reading = _module("core.versions.read")
            cls.v01, cls.v02 = (reading.version(conn, uid) for uid in made["versions"])
        cls.ps.attach(cls.project)
        cls.addClassCleanup(cls.ps.close)
        for _ in range(2000):  # la comprobación de apertura (sin temporizadores en blender -b)
            if cls.session.check_tick() is None:
                break
        assert bpy.ops.geoblender.core_set_active_version(version_uid=cls.v01.uid) == {"FINISHED"}
        assert bpy.ops.geoblender.gis_compile_constraints() == {"FINISHED"}
        cls.masks = _module("gis.masks.access").load_masks(cls.project, cls.v01.uid)
        cls.write_profiles()
        cls.register_probe()
        cls.refresh()

    @classmethod
    def extend_project(cls, project: Any, clock: Any) -> None:
        """Lo que la 017 pide al proyecto de las pistas y no trae: la capa de puntos de la «Pista a P1», la del relleno del tajo, sus puntos y su entrada, y el terreno de la «opción A15»."""
        grid = rd.grid_of(rd.COARSE_STEP_M)
        points = (("Entrada", rd.RAMP_ORIGIN), ("En P1", (320.0, 200.0)), ("Fuera de P1", (200.0, 100.0)))
        sdata.write_layer(project, clock, sdata.FieldsLayer(PLATFORM_LAYER, "point", tuple(((rd.absolute([point], grid),),) for _name, point in points), tuple(name for name, _p in points), {}))
        box = rd.PIT_FILL_BOX
        sdata.write_layer(project, clock, sdata.FieldsLayer(PIT_FILL_LAYER, "line", (((rd.absolute([(box[0], 160.0), (box[2], 160.0)], grid),),),), (PIT_FILL,),
                                                           {"ancho": (box[3] - box[1],), "cota_inicial": (rd.PIT_FILL_LEVEL_M,), "pendiente": (0.0,)}))
        pit = (("Origen del tajo", rd.PIT_ORIGIN), ("En el relleno", (100.0, 160.0)))
        sdata.write_layer(project, clock, sdata.FieldsLayer(PIT_POINTS, "point", tuple(((rd.absolute([point], grid),),) for _name, point in pit), tuple(name for name, _p in pit), {}))
        sdata.write_layer(project, clock, sdata.FieldsLayer(PIT_ENTRY, "point", (((rd.absolute([rd.PIT_ENTRY], grid),),),), ("Entrada del tajo",), {}))
        x, _y = rd.local_centers(grid)
        res_fixtures.write_grids(project, [("a15", _module_free_raster(grid, rd.RAMP_Z0_M + 0.105 * x))], message="Terreno de la «opción A15» del hito H2")

    @classmethod
    def write_profiles(cls) -> None:
        """El perfil de referencia de IMGA (**solo de las pruebas**) y el de la «opción A15» (pd = 12 %) en V01."""
        profiles = _module("design.road_profiles")
        dparams = _module("design.params")
        declared = profiles.ProfileDeclaration("ITC 07.1.03 de la prueba", PERSON, "Perfiles del hito H2 de las pistas", version=cls.v01.code)
        for name, data in (("PISTA_PRINCIPAL", rd.PROFILE), (A15_PROFILE, rd.profile_with(max_gradient_pct=12.0))):
            values = {param: getattr(data, "class_name" if param.value == "class" else param.value) for param in dparams.RoadProfileParam}
            profiles.edit_road_profiles(cls.project, (profiles.ProfileEdit(name=name, values=values),), declared)

    @classmethod
    def register_probe(cls) -> None:
        """La operación de prueba que escribe las dos superficies del tajo de la 014 (solo desde esta prueba) y las escribe en V01."""
        contract, dprov, store = _module("core.provenance.contract"), cls.dprov, _module("design.store")
        found = dprov.OperationType(PROBE, "Surfaces of the pit of the H2 of the roads", (dprov.EXPLOITATION_GRID, dprov.FINAL_GRID), ())
        patched = mock.patch.object(dprov, "OPERATION_TYPES_BY_NAME", MappingProxyType({**dprov.OPERATION_TYPES_BY_NAME, PROBE: found}))
        patched.start()
        cls.addClassCleanup(patched.stop)
        contract.register_operation(found.definition(lambda request: None))
        cls.addClassCleanup(contract.unregister_operation, PROBE)
        grid = rd.grid_of(rd.COARSE_STEP_M)
        gis = _module("gis")
        begun = store._start(cls.project, PROBE, "Tajo", cls.v01, None, {"name": "Tajo"}, (), (), None)
        references = _module("gis.store").project_references(cls.project)
        with store.design_writer(cls.project, PROBE, "Tajo", version=cls.v01.uid) as writer:
            for family, values in ((dprov.EXPLOITATION_GRID, rd.pit_exploitation(grid)), (dprov.FINAL_GRID, rd.pit_final(grid))):
                _drive(writer.grid_steps(family, gis.Raster(_project_grid(cls.project), values, references[0], references[1])))
            writer.commit(begun, message="Superficies del tajo del hito H2 de las pistas")

    # --- Ayudas -------------------------------------------------------------------------------

    @classmethod
    def refresh(cls) -> None:
        """Las listas de los diálogos (superficies, capas y plataformas), leídas de nuevo (un guion no abre el diálogo que las lee)."""
        cls.panels.fill_profiles(cls.project)
        cls.panels.fill_sectors(cls.project)
        cls.panels.refresh_choices(cls.project)
        cls.panels.refresh_platform_choices(cls.project)

    def setUp(self) -> None:
        if not blender_ext.is_enabled():
            blender_ext.enable()
        self.addCleanup(self.i18n.set_language, self.i18n.language())
        self.i18n.set_language("es")

    def tearDown(self) -> None:
        self.des_ops.discard_calculation()  # lo que deja una prueba que falla no sigue

    def rows(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def states(self, version: Any = None) -> dict[str, str]:
        registry = self.entities.registry(self.project, (version or self.v01).uid)
        return {entry.record.code: str(entry.record.state) for entry in registry}

    def current(self, code: str, version: Any = None) -> str:
        return str(self.entities.registry(self.project, (version or self.v01).uid).get(code).operation_uid)

    def change(self, key: str, value: object, *, version: Any = None) -> None:
        """Cambia el parámetro de versión ``key`` (con su motivo y como lo da una persona)."""
        with self.project.write_transaction() as conn:
            _module("core.params").ParameterStore(self.project).change(conn, key, value=value, source="Prueba del hito H2", source_kind="person", decided_by=PERSON,
                                                                      reason="Prueba del hito H2", version=(version or self.v01).uid)

    def causes(self, uid: str) -> set[tuple[str, str]]:
        found = set()
        for cause, subject in self.rows("SELECT cause_kind, subject_uid FROM gb_stale WHERE item_kind = 'operation' AND item_uid = ?", uid):
            named = self.rows("SELECT key FROM gb_parameter WHERE uid = ? UNION ALL SELECT name FROM gb_dataset WHERE uid = ?", subject, subject)
            found.add((cause, subject if not named else named[0][0]))
        return found

    def tick(self) -> bool:
        """Un paso de cada cola de pasos del recálculo (``des``, las máscaras de ``gis`` y la verificación de ``res``: sus temporizadores no corren en ``blender -b``, se avanzan a mano)."""
        gis_ops, res_ops = _module("bl.ops.gis"), _module("bl.ops.res")
        pending = bool(self.des_ops.pending_runs() or gis_ops.pending_mask_runs() or res_ops.pending_runs())
        self.des_ops.des_tick()
        gis_ops.masks_tick()
        res_ops.res_tick()
        return pending

    def recompute(self) -> Any:
        """Lanza «Recalcular lo obsoleto» y lo lleva hasta el final (el modal con la cola de ``des`` avanzada a mano), sin confirmar nada: el operador, con su ``result`` y lo que dijo."""
        with mock.patch.object(self.des_ops, "_ask_confirmation") as ask, mock.patch.object(_module("bl.ops.incorporation"), "status_text"):
            self.assertEqual(bpy.ops.geoblender.core_recompute_stale("EXEC_DEFAULT"), {"RUNNING_MODAL"})
            found = [op for op in bpy.context.window.modal_operators
                     if isinstance(op, self.session.GEOBLENDER_OT_core_recompute_stale) and getattr(op, "_steps", None) is not None]
            self.assertEqual(len(found), 1)
            operator = found[0]
            self.addCleanup(lambda: operator._steps is None or operator.cancel(bpy.context))
            for _ in range(MAX_TICKS):
                state = operator.modal(bpy.context, TIMER)
                self.tick()
                if state != {"RUNNING_MODAL"}:
                    ask.assert_not_called()
                    return operator
        self.fail("el recálculo no termina")

    def made_names(self, operator: Any, status: str) -> list[str]:
        """Los nombres de las operaciones de las unidades de ``operator`` que acabaron en ``status``."""
        found = []
        for result in operator.result.results:
            if str(result.status) == status:
                for uid in result.unit.operations:
                    ((op_type, settings),) = self.rows("SELECT op_type, settings FROM gb_operation WHERE uid = ?", uid)
                    found.append(str(json.loads(settings).get("name", op_type)))
        return found

    def platform_made(self, **values: Any) -> None:
        """«Plataforma…» (la orden real, «Calcular» y «Crear») en la versión activa."""
        self.refresh()
        form = {"layer": rd.PLATFORMS_LAYER, "edge_angle": "35", "reach": "20", "in_steps": False, **values}
        self.assertEqual(bpy.ops.geoblender.des_create_platform("EXEC_DEFAULT", **form), {"FINISHED"})
        self.assertEqual(bpy.ops.geoblender.des_create_platform("EXEC_DEFAULT", confirm=True, in_steps=False), {"FINISHED"})

    def road_request(self, name: str, *, layer: str = rd.POINTS_LAYER, mode: str = "trace", profile: str = "pista_principal", surface: str = RAMP, **changes: Any) -> Any:
        """La petición de una pista (sin que la orden de la fase G exista): los parámetros de la ruta de la referencia de IMGA (solo de las pruebas) en «trazar»."""
        model = _module("design.road_model")
        base: dict[str, Any] = {field: getattr(rd.ROUTE, field) for field in ROUTE_FIELDS} if mode == "trace" else {"feature": "Eje de 200 m"}
        return model.RoadRequest(name, model.LayerFields(layer, "nombre"), mode, profile, surface, **{**base, **changes})

    def road_made(self, asked: Any, **confirmed: Any) -> tuple[Any, Any]:
        """«Calcula» y «crea» la pista ``asked`` en la versión activa: la ``Calculation`` y lo guardado."""
        calculation = _last(_module("design.steps").road_run(self.project, asked, version=self.v01.uid, masks=self.masks))
        self.assertIsNotNone(calculation)
        if confirmed:
            calculation.confirm_road(**confirmed)
        stored = calculation.create(decided_by=PERSON)
        self.refresh()
        return calculation, stored

    def axis_levels(self, name: str) -> tuple[np.ndarray, np.ndarray]:
        """Las abscisas y las cotas de la rasante de la pista ``name`` (su ``des_rdx_``), de la tabla guardada."""
        locator = self.dprov.dataset_locator(self.dprov.ROAD_AXIS_TABLE, name, self.v01.code)
        rows = self.rows(f'SELECT station_m, level_m FROM "{locator}" ORDER BY fid')
        return np.array([row[0] for row in rows]), np.array([row[1] for row in rows])

    def surface(self, name: str, version: Any = None) -> np.ndarray:
        return np.asarray(self.surfaces.read_surface(self.project, name, version_uid=(version or self.v01).uid).values)

    def psf(self, name: str) -> str:
        return self.dprov.dataset_name(self.dprov.ENTITY_SURFACE_GRID, name)

    # --- E1: la cadena P1 → pista → ramal → relleno ----------------------------------------------

    def test_a_e1_the_chain_of_the_platform_the_road_the_branch_and_the_fill_is_created_with_the_registered_extension(self) -> None:
        """E1, E5, RF-017-01 a RF-017-03, RF-015-04, RF-015-15 (la orden real de la plataforma y el dominio de la pista dentro de Blender): ``P1`` (``PLT-001``), la «Pista a P1» (``RDW-001``: el
        destino, el punto de la capa que cae en su huella), el «Ramal» (``RDW-002``: sale del eje de la anterior a 100 m) y el relleno posterior sobre la calzada (``PLT-002``) se crean; la pista
        mide 220 m al 4 % (el plano del 4 %, la rampa de la referencia), **se apoya en ``P1``** y lo que se apoya en la pista es **una sola lista** —el ramal y el relleno, con **su volumen a mano
        de los ficheros** (≤ 10⁻⁹ relativo)—; el estado de las cuatro es «al día»."""
        self.platform_made(name=PLATFORM, feature=PLATFORM, start=RAMP)
        asked = self.road_request(FIRST, layer=PLATFORM_LAYER, origin="Entrada", destination="entity:PLT-001", surface="entity:PLT-001")
        first, _stored = self.road_made(asked)
        self.assertEqual(first.entity.supports, ("PLT-001",))
        self.assertAlmostEqual(first.summary.length_m, 220.0, delta=3.0)
        self.assertLessEqual(first.summary.gradient_max_pct, rd.PROFILE.max_gradient_pct + 1e-9)
        self.assertAlmostEqual(first.summary.gradient_mean_pct, 4.0, delta=0.5)
        second, _stored = self.road_made(self.road_request(SECOND, origin="RDW-001@100", destination="Destino del ramal", surface="entity:RDW-001"))
        self.assertEqual(second.entity.supports, ("RDW-001",))
        self.platform_made(name=FILL, layer=rd.PLATFORMS_LAYER, feature=FILL, start="entity:RDW-002", mode="CUT_FILL", reach="20")
        self.assertEqual(self.states(), {"PLT-001": "current", "RDW-001": "current", "RDW-002": "current", "PLT-002": "current"})
        listed = {row.name: row for row in self.entities.dependents(self.project, self.v01.uid, "RDW-001")}
        self.assertEqual(sorted(listed), [SECOND, FILL])
        self.assertIn("supported_on", listed[SECOND].roles)
        self.assertIn("supported_on", listed[FILL].roles)
        found, begun, road = (self.surface(self.psf(name)) for name in (FILL, SECOND, FIRST))
        (footprint_row,) = self.rows(f'SELECT footprint FROM "{self.dprov.dataset_locator(self.dprov.ENTITY_TABLE, FIRST, self.v01.code)}"')
        footprint = np.asarray(self.entities_store().runs_mask(json.loads(footprint_row[0]), found.shape))
        with np.errstate(invalid="ignore"):
            thickness = found - np.maximum(begun, road)
            counted = footprint & (thickness > 0.02)
        by_hand = float(thickness[counted].sum()) * CELL_M2
        self.assertGreater(by_hand, 0.0)
        self.assertLessEqual(abs(listed[FILL].volume_m3 - by_hand), 1e-9 * by_hand)

    def entities_store(self) -> Any:
        return _module("design.entity_store")

    # --- E5: cambiar la plataforma de destino y recalcular lo obsoleto ---------------------------

    def test_b_e5_changing_the_target_platform_makes_the_four_stale_with_the_cause_and_the_modal_repeats_them_in_order(self) -> None:
        """E5, RF-015-16, RF-017-03, D-13 (T24b), CE-017-08 (el modal real con las funciones que registra ``bl``): la cota de ``P1`` pasa de 112 a 111,6 m: ella, la pista, el ramal y el relleno
        quedan **obsoletos con su causa** (el parámetro) y «Recalcular lo obsoleto» los rehace **en orden de dependencia** (``P1`` antes que la pista, la pista antes que el ramal y que el
        relleno) más lo que sigue (la capa de entidades); **la pista acaba a la cota nueva** (la cota de fin que derivó de ``P1`` la sigue) y nada queda obsoleto."""
        key = "des.platform.plt_001.start_level_m"
        before = {code: self.current(code) for code in ("PLT-001", "RDW-001", "RDW-002", "PLT-002")}
        self.change(key, NEW_M)
        self.assertEqual(set(self.states().values()), {"stale"})
        for code, uid in before.items():
            self.assertIn(("parameter_changed", key), self.causes(uid), code)
        operator = self.recompute()
        self.assertEqual(operator.result.cancelled, False)
        self.assertEqual(self.made_names(operator, "failed"), [], "ninguna unidad falla")
        done = self.made_names(operator, "done")
        self.assertEqual([name for name in done if name != "des.entity_layer"], [PLATFORM, FIRST, SECOND, FILL])
        self.assertEqual(set(self.states().values()), {"current"})
        _stations, levels = self.axis_levels(FIRST)
        self.assertAlmostEqual(float(levels[-1]), NEW_M, places=9)
        for code in ("PLT-001", "RDW-001", "RDW-002", "PLT-002"):
            self.assertEqual(self.causes(self.current(code)), set(), code)

    # --- E3: sobre un eje con la media por encima de pm --------------------------------------------

    def test_c_e3_the_axis_of_the_property_with_the_mean_over_pm_asks_for_the_confirmation_and_the_reason_stays(self) -> None:
        """E3, RF-017-17, D-6, N-15 (la «opción A15»): el eje de 200 m de la capa de la propiedad sobre un terreno del 10,5 % con pd = 12 % y pm = 10 %: el resumen da la media (10,5 %) y pide la
        confirmación; **sin ella «Crear» se rechaza sin escribir nada**; con el motivo se crea y el motivo queda en los ajustes con quién lo confirmó y cuándo (``confirmed_of``); **la capa de la
        propiedad no cambia**."""
        steps, store, messages = _module("design.steps"), _module("design.road_store"), _module("design.messages")
        layer_before = self.rows(f'SELECT * FROM "{rd.AXES_LAYER}" ORDER BY fid')
        asked = self.road_request(A15_NAME, mode="on_axis", layer=rd.AXES_LAYER, profile=A15_PROFILE.lower(), surface=A15)
        calculation = _last(steps.road_run(self.project, asked, version=self.v01.uid, masks=self.masks))
        self.assertAlmostEqual(calculation.summary.gradient_mean_pct, 10.5, delta=1e-6)
        self.assertTrue(calculation.needs_mean_confirmation)
        counter = self.rows("SELECT count(*) FROM gb_operation")
        with self.assertRaises(messages.DesignError) as caught:
            calculation.create(decided_by=PERSON)
        self.assertEqual(caught.exception.code, "des.road_mean_unconfirmed")
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation"), counter)
        calculation.confirm_road(mean=True, reason=REASON)
        stored = calculation.create(decided_by=PERSON)
        ((settings,),) = self.rows("SELECT settings FROM gb_operation WHERE uid = ?", str(stored.handle.uid))
        found = store.confirmed_of(json.loads(settings))
        self.assertEqual((found.decided_by, found.reason, found.mean_limit_pct), (PERSON, REASON, 10.0))
        self.assertAlmostEqual(found.mean_pct, 10.5, delta=1e-6)
        self.assertEqual(self.rows(f'SELECT * FROM "{rd.AXES_LAYER}" ORDER BY fid'), layer_before)
        self.refresh()

    # --- E2 y CE-017-05: el tajo, el relleno posterior y la accesibilidad ---------------------------

    def test_d_e2_the_road_after_the_fill_does_not_warn_of_its_quarry_and_on_the_final_it_does_not_reach_the_bottom(self) -> None:
        """E2, CE-017-05, RF-017-05, RF-017-24, errores 9 y 23 (hallazgo H2-1): sobre el tajo de la 014 (explotación hasta 125 m, final restaurada hasta 140 m) el «solo relleno» posterior (la orden
        real: «en corte y relleno» a 130 m) y la pista que parte de **la superficie que deja** **no avisan de la cantera de la que parten** (ni su explotación ni su final son «otro diseño»); la
        pista sobre **la final restaurada** avisa de que no llega al fondo (140 y 125 m); y la accesibilidad da **125 m sobre la explotación y 140 m sobre la final**."""
        steps = _module("design.steps")
        self.platform_made(name=PIT_FILL, layer=PIT_FILL_LAYER, feature=PIT_FILL, start="des_exp_tajo", mode="CUT_FILL")
        code = next(code for code, entry in self.states().items() if code.startswith("PLT") and self.entities.registry(self.project, self.v01.uid).get(code).record.name == PIT_FILL)
        asked = self.road_request(PIT_ROAD, layer=PIT_POINTS, origin="Origen del tajo", destination=f"entity:{code}", surface=f"entity:{code}")
        road, _stored = self.road_made(asked)
        self.assertEqual((road.summary.start_level_m, road.summary.end_level_m), (rd.PIT_GROUND_M, rd.PIT_FILL_LEVEL_M))
        self.assertFalse({"des_exp_tajo", "des_fin_tajo"} & set(road.outcome.other_designs), "la cantera de la que parte no es otro diseño")
        self.assertFalse({"des_exp_tajo", "des_fin_tajo"} & {notice.values["other"] for notice in road.summary.notices if notice.code == "des.road_other_design_differs"})
        on_final, _stored = self.road_made(self.road_request(PIT_FINAL_ROAD, layer=PIT_POINTS, origin="Origen del tajo", destination="En el relleno", surface="des_fin_tajo"))
        first = on_final.summary.notices[0]
        self.assertEqual((first.code, first.values["z_final"], first.values["z_pit"]), ("des.road_start_is_final", rd.PIT_Z_MIN_FINAL_M, rd.PIT_Z_MIN_EXPLOITATION_M))
        model = _module("design.road_model")
        figures = {}
        for surface in ("des_exp_tajo", "des_fin_tajo"):
            asked_access = model.AccessRequest(f"Accesibilidad sobre {surface}", model.LayerFields(PIT_ENTRY, "nombre"), surface, walk_slope_pct=rd.ACCESS.walk_slope_pct,
                                               walk_width_m=rd.ACCESS.walk_width_m, min_berm_area_m2=rd.ACCESS.min_berm_area_m2)
            made = _last(steps.access_run(self.project, asked_access, version=self.v01.uid, masks=self.masks))
            figures[surface] = {figure.key: figure.value for figure in made.figures}
            made.create(decided_by=PERSON)
        self.assertEqual((figures["des_exp_tajo"]["des.acc_z_min_m"], figures["des_exp_tajo"]["des.acc_z_min_final_m"]), (rd.PIT_Z_MIN_EXPLOITATION_M, rd.PIT_Z_MIN_FINAL_M))
        self.assertEqual(figures["des_fin_tajo"]["des.acc_z_min_m"], rd.PIT_Z_MIN_FINAL_M)
        self.refresh()

    # --- E4: la accesibilidad de la cantera con bancos ---------------------------------------------

    def test_e_e4_the_accessibility_of_the_bank_quarry_reaches_115_m_and_140_m(self) -> None:
        """E4, CE-017-07, RF-017-24: la accesibilidad de la cantera con bancos (``gis_dtm_banco``: la entrada a 140 m, las bermas a 135, 125, 115 y 105 m y las tres rampas grabadas), con las
        entradas de la referencia, da la cota mínima alcanzable de **115 m** y la máxima de **140 m** (la berma de 105 m no se comunica), a ≤ 10⁻⁹ del cálculo a mano de ``road_data``, y su
        informe se escribe con el tipo que registra la extensión."""
        model = _module("design.road_model")
        asked = model.AccessRequest("Accesibilidad de la cantera con bancos", model.LayerFields(rd.ENTRIES_LAYER, "nombre"), rd.dataset_of("banco"), walk_slope_pct=rd.ACCESS.walk_slope_pct,
                                    walk_width_m=rd.ACCESS.walk_width_m, min_berm_area_m2=rd.ACCESS.min_berm_area_m2)
        made = _last(_module("design.steps").access_run(self.project, asked, version=self.v01.uid, masks=self.masks))
        stored = made.create(decided_by=PERSON)
        figures = {key: value for key, value in self.rows("SELECT key, value FROM gb_figure WHERE operation_uid = ?", str(stored.handle.uid))}
        self.assertEqual((figures["des.acc_z_min_m"], figures["des.acc_z_max_m"]), (rd.BANK_Z_MIN_M, rd.BANK_Z_MAX_M))
        self.assertEqual(self.rows("SELECT op_type, status FROM gb_operation WHERE uid = ?", str(stored.handle.uid)), [("des.road_access", "done")])
        self.refresh()

    # --- E5: traer a otra versión ----------------------------------------------------------------

    def test_f_e5_bringing_the_chain_to_another_version_leaves_the_roads_uncalculated(self) -> None:
        """E5, RF-015-18, CE-017-08 (la orden real «Traer las entidades de…» con la pista): traer ``PLT-001``, la pista, el ramal y el relleno de V01 a V02 los deja **sin calcular** (ningún
        resultado en V02) con los parámetros de su tipo; V01 sigue como estaba."""
        v01_states = self.states()
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v02.uid), {"FINISHED"})
        self.addCleanup(bpy.ops.geoblender.core_set_active_version, version_uid=self.v01.uid)
        self.assertEqual(bpy.ops.geoblender.des_entity_bring("EXEC_DEFAULT", source="V01", entities="PLT-001, RDW-001, RDW-002, PLT-002"), {"FINISHED"})
        mine = self.states(self.v02)
        self.assertEqual({code: mine[code] for code in ("PLT-001", "RDW-001", "RDW-002", "PLT-002")}, dict.fromkeys(("PLT-001", "RDW-001", "RDW-002", "PLT-002"), "uncalculated"))
        self.assertEqual(self.rows("SELECT count(*) FROM gb_dataset WHERE version_uid = ? AND name LIKE 'des!_psf!_%' ESCAPE '!'", self.v02.uid), [(0,)])
        self.assertEqual(self.rows("SELECT count(*) FROM gb_parameter WHERE key LIKE 'des.road.rdw_001.%' AND scope = 'version' AND scope_uid = ?", self.v02.uid)[0][0] > 0, True)
        self.assertEqual(self.states(), v01_states)

    # --- Congelar y reproducir -----------------------------------------------------------------

    def test_g_frozen_the_roads_and_the_accessibility_are_reproduced_with_the_functions_the_extension_registers(self) -> None:
        """RF-009-11, RF-017-01 a RF-017-03, RF-017-24, RF-015-02: V01 congelada en ``V01.r1`` con las pistas de los tres modos (la cadena, «sobre un eje» y las del tajo) y las dos accesibilidades,
        se reproduce **sin proyecto** con las funciones de reproducir que registra la extensión (``reproduce_road`` y ``reproduce_road_access``): de cada dato, **el mismo hash**, y las mismas
        cifras, **sin escribir nada** en el proyecto."""
        freeze, reproduce = _module("core.versions.freeze"), _module("core.versions.reproduce")
        accepted = freeze.Acceptance.of(freeze.freeze_plan(self.project, self.v01.uid))  # lo no verificado queda anotado tal como está (RF-009-08)
        revision = _last(freeze.freeze_steps(self.project, self.v01.uid, reason="Entrega de la prueba del hito H2", accepted=accepted))
        self.assertIsNotNone(revision)
        before = self.rows("SELECT count(*) FROM gb_dataset"), self.rows("SELECT count(*) FROM gb_operation")
        report = _last(reproduce.reproduce_steps(self.project, str(revision.frozen.uid)))
        kinds = {uid: op_type for uid, op_type in self.rows("SELECT uid, op_type FROM gb_operation")}
        roads = {check.operation_uid for check in report.outputs if kinds.get(check.operation_uid) in ("des.road", "des.road_access")}
        self.assertEqual(sorted(kinds[uid] for uid in roads), ["des.road"] * 5 + ["des.road_access"] * 3, "las cinco pistas y las tres accesibilidades")
        mine = [check for check in report.outputs if check.operation_uid in roads]
        self.assertTrue(mine)
        self.assertTrue(all(check.same for check in mine), [check for check in mine if not check.same])
        figures = [check for check in report.figures if check.operation_uid in roads]
        self.assertTrue(figures and all(check.same for check in figures), [check for check in figures if not check.same])
        self.assertEqual([note for note in report.not_reproducible if note.operation_uid in roads], [])
        self.assertEqual((self.rows("SELECT count(*) FROM gb_dataset"), self.rows("SELECT count(*) FROM gb_operation")), before, "reproducir no escribe")

    # --- E5: descartar la pista principal ----------------------------------------------------------

    def test_h_e5_discarding_the_main_road_leaves_the_branch_and_the_fill_with_their_support_removed_and_recompute_does_not_remake_them(self) -> None:
        """E5, RF-015-17, D-24, CE-017-08 (la orden real «Descartar…» con la pista): antes de descartar la pista principal, **una sola lista** de lo que se le apoya (el ramal y el relleno); al
        descartarla (con su motivo) **quedan en «apoyo retirado»** con su causa, sin que se borre nada, y «Recalcular lo obsoleto» **no los recalcula**: no escribe ninguna operación ni dato
        de las pistas ni de las plataformas."""
        listed = self.entities.dependents(self.project, self.v01.uid, "RDW-001")
        self.assertEqual(sorted(row.name for row in listed), [SECOND, FILL])
        self.change("des.road.rdw_002.search_budget", 4_999_999)  # el ramal y lo que parte de él, obsoletos
        self.assertEqual(bpy.ops.geoblender.des_entity_discard("EXEC_DEFAULT", entity="RDW-001", reason=WHY, in_steps=False), {"FINISHED"})
        mine = self.states()
        self.assertEqual((mine["RDW-001"], mine["RDW-002"], mine["PLT-002"]), ("discarded", "support_removed", "support_removed"))
        why = self.entities.stale_reason(self.project, self.v01.uid, "RDW-002")
        self.assertTrue(why.startswith("Apoyo retirado: "), why)
        self.assertEqual(self.rows("SELECT count(*) FROM gb_dataset WHERE status = 'discarded'")[0][0] > 0, True)
        roads_before = self.rows("SELECT count(*) FROM gb_operation WHERE op_type IN ('des.road', 'des.platform')")
        operator = self.recompute()
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation WHERE op_type IN ('des.road', 'des.platform')"), roads_before)
        for name in (SECOND, FILL):
            self.assertNotIn(name, self.made_names(operator, "done"))
        self.assertEqual({code: state for code, state in self.states().items() if code in ("RDW-002", "PLT-002")}, {"RDW-002": "support_removed", "PLT-002": "support_removed"})


def _project_grid(project: Any) -> Any:
    """La rejilla del proyecto (la de su ventana y su paso)."""
    record = project.record
    return _module("gis.grid").project_grid(record.window, float(record.grid_step_m))


def _module_free_raster(grid: Any, values: np.ndarray) -> Any:
    """Un ``Raster`` de la copia de las pruebas sin Blender (``write_grids`` lo escribe con esa copia)."""
    from tests.support.package import import_geoblender

    return import_geoblender("gis").Raster(grid, values, rd.CRS, rd.VERTICAL)


if __name__ == "__main__":
    unittest.main()

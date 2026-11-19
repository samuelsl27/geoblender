# SPDX-License-Identifier: GPL-3.0-or-later
"""La orden del contrafuerte, su almacén: preparar, calcular, crear, declarar, recalcular y reproducir (spec 016, T27; HU-016-3; RF-016-17,
RF-016-18, RF-015-02, RF-015-03, RF-015-10, RF-015-12, RF-015-29, RF-009-11; plan 016 §5.2.3, §5.3.2, §5.4 A10, §5.7 P-8, §5.8 H-6). Es el
patrón de la retirada (T20) y del cuerpo (T25): ``design.supported_store`` hace, para el contrafuerte, lo mismo; el cálculo es el de la T26
(``design.buttress``, ya probado contra la fórmula cerrada y el oráculo independiente: aquí solo se comprueba que lo registrado es lo que
dio).

La cantera de 2 m con la zona de coronación «Contrafuerte del acopio 3» (22 × 22 m, 121 celdas, coronación a 115 m: el ancla de
``EXPL_10_60_6``, un banco por debajo de 125) sobre el levantamiento de V01 (:class:`ButtressOperationTest`, **en orden**: cada ``test_x``
parte de lo que dejó la anterior): «Calcular» no escribe nada; los rechazos (la cota fuera del ancla con la del ancla más próxima, sin
cota, sin resguardo, por debajo del apoyo…) no escriben; «Crear» es **una** transacción; **la restricción «sin corte» es de la zona de
coronación y no de toda la huella** (P-8, H-6; resguardo obligatorio: D-19); recalcular, reproducir y encadenar lo que sigue a crearlo.
"""

from __future__ import annotations

import json
import unittest
from typing import Any, ClassVar
from unittest import mock

import numpy as np

from tests.support import design_fixtures as dfx
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.support.versions_fixtures import change_counter, files
from tests.unit.design import test_removal_operation as rop
from tests.unit.design import test_stockpile_operation as ops
from tests.unit.design import test_stockpile_prepare as tp

core_params = import_geoblender("core.params")
design_params = import_geoblender("design.params")
design_reproduce = import_geoblender("design.reproduce")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
freeze = import_geoblender("core.versions.freeze")
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")
provenance = import_geoblender("design.provenance")
recompute_mod = import_geoblender("core.provenance.recompute")
reproduce_mod = import_geoblender("core.versions.reproduce")
steps = import_geoblender("design.steps")
store = import_geoblender("design.store")
supported_store = import_geoblender("design.supported_store")
constraints_model = import_geoblender("core.constraints.model")

GRID = rop.GRID
USER = rop.USER
SURVEY = rop.SURVEY
HILLSIDE = sdata.HILLSIDE_DATASET
PROFILE = dfx.EXPL_10_60_6.code
ZONE = "Contrafuerte del acopio 3"
BUTTRESS = "Contrafuerte sobre el acopio 3"
CROWN_M = 115.0
GUARD_M = 10.0
EXACT = 1e-9
BY_HAND = {"source": "Perfil de prueba", "source_kind": "person", "decided_by": "Samuel (IMGA)"}


def asked(name: str = BUTTRESS, *, feature: str = ZONE, crown: float | None = CROWN_M, profile: str = PROFILE, start: str = SURVEY,
          guard: float | None = GUARD_M, layer: str = sdata.CROWN_LAYER, **changes: Any) -> Any:
    """La petición de un contrafuerte con la zona de coronación ``feature`` de la capa de zonas, sobre el levantamiento de V01, con el
    perfil ``EXPL_10_60_6``, la cota de coronación ``crown`` y, porque protege por defecto (D-1), su resguardo."""
    return model.ButtressRequest(name=name, fields=model.ButtressFields(layer=layer, crown_field="cota"), feature=feature, start=start,
                                 profile=profile, crown_m=crown, guard_m=guard, **changes)


def buttress_definitions() -> tuple[Any, ...]:
    """El tipo del contrafuerte con sus funciones **reales** (recalcular y reproducir) y sus cifras, como los registra ``bl``."""
    found = provenance.OPERATION_TYPES_BY_NAME[provenance.BUTTRESS].definition(ops.recompute_function, design_reproduce.reproduce_buttress)
    return found, *provenance.BUTTRESS_FIGURES


def write_profile(case: Any) -> None:
    """Escribe en el proyecto de ``case`` (una clase de pruebas con su ``project`` y su reloj) las familias de parámetros de la 013 y los
    cinco valores del perfil ``EXPL_10_60_6`` (el de la 013: 10 m, 60°, 6 m y ancla de 125 m), con su origen, como lo deja el diálogo de los
    perfiles; las familias se quitan al acabar la clase."""
    core_params.register_families(design_params.FAMILIES)
    case.addClassCleanup(core_params.unregister_families, "des")
    case.clock.advance(minutes=1)
    parameters = core_params.ParameterStore(case.project)
    with case.project.write_transaction() as conn:
        for param, value in (("height_m", dfx.EXPL_10_60_6.height_m), ("face_deg", dfx.EXPL_10_60_6.face_deg),
                             ("berm_m", dfx.EXPL_10_60_6.berm_m), ("anchor_m", dfx.EXPL_10_60_6.anchor_m), ("mesh_factor", 1.0)):
            parameters.create(conn, design_params.bench_key(PROFILE, param), value,
                              kind="ADOPTADO" if param == "mesh_factor" else "HIPÓTESIS", reason="Perfil de la prueba", **BY_HAND)
    case.clock.advance(minutes=1)


class ButtressCase(rop.RemovalCase):
    """La cantera de los acopios (2 m, V01 con su levantamiento y sus capas) con los perfiles de banco de la 013 en el proyecto, el tipo del
    contrafuerte registrado con sus funciones reales (recalcular y reproducir) y las ayudas de lo registrado."""

    @classmethod
    def definitions(cls) -> tuple[Any, ...]:
        return (*super().definitions(), *buttress_definitions())

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        write_profile(cls)

    @classmethod
    def calculate(cls, request: Any, **options: Any) -> Any:
        options.setdefault("masks", cls.masks_v1)
        options.setdefault("version", cls.v1.uid)
        return ops.last(steps.buttress_run(cls.project, request, **options))

    @classmethod
    def make(cls, request: Any, **options: Any) -> tuple[Any, Any]:
        """«Calcula» y «crea» ``request`` (un minuto después de lo anterior): la ``Calculation`` y lo guardado."""
        cls.clock.advance(minutes=1)
        calculation = cls.calculate(request)
        stored = calculation.create(decided_by=USER, **options)
        cls.clock.advance(minutes=1)
        return calculation, stored

    def locator(self, family: str, name: str) -> str:
        return provenance.dataset_locator(family, name, "V01")

    def raster(self, family: str, name: str) -> np.ndarray:
        """La rejilla de la salida ``family`` del contrafuerte ``name`` tal como está en su fichero."""
        return self.grid_of(provenance.dataset_name(family, name))


class ButtressOperationTest(ButtressCase):
    """RF-016-17, RF-016-18, RF-015-01, RF-015-02, RF-015-03, RF-015-10, RF-015-12, RF-015-29, RF-009-11, **en orden**: el contrafuerte
    ``BTR-001`` sobre el levantamiento de V01, con la zona de coronación de 121 celdas."""

    first: ClassVar[Any]
    stored: ClassVar[Any]
    revision: ClassVar[str]

    def zone_cells(self) -> set[tuple[int, int]]:
        """A mano: las celdas con el centro dentro de la zona de coronación (un bucle, no el código)."""
        (zone,) = [item for item in sdata.CROWN_ZONES if item.name == ZONE]
        return {(int(index) // GRID.ncols, int(index) % GRID.ncols) for index in tp.hand_cells(zone.box)}

    # --- Calcular ------------------------------------------------------------------------------------------------------

    def test_a_calculating_writes_nothing_and_raises_the_surface_only_where_the_crown_reaches(self) -> None:
        """RF-015-03, RF-016-17: «Calcular» el contrafuerte **no escribe nada** (la base de datos, las operaciones, los datos, los parámetros ni
        las cifras: solo el temporal de la superficie, que descartar borra); la superficie es la de partida sin bajar una celda, con la
        zona de coronación a su cota (donde la partida queda por debajo) y la huella entera por encima de la zona; el volumen, el área y la
        altura máxima que dice el resumen son los de la superficie."""
        before = self.state()
        calculation = self.calculate(asked())
        self.assertEqual({k: v for k, v in self.state().items() if k != "files"}, {k: v for k, v in before.items() if k != "files"})
        self.assertEqual(len(self.temporaries()), 1, "solo el temporal de la superficie")
        outcome = calculation.outcome
        summary = calculation.summary
        start = self.grid_of(SURVEY)
        zone = self.zone_cells()
        surface = outcome.compose(start)
        self.assertTrue(np.all(surface >= start), "ninguna celda baja")
        rise = surface - start
        self.assertGreater(float(rise.sum()) * 4.0, 0.0)
        self.assertLessEqual(abs(summary.volume_m3 - float(rise[rise > 0.0].sum()) * 4.0) / summary.volume_m3, EXACT)
        self.assertEqual(summary.area_m2, float(np.count_nonzero(rise > 0.0)) * 4.0)
        self.assertEqual(summary.height_max_m, float(rise.max()))
        self.assertEqual((summary.code, summary.crown_m, summary.profile, summary.protect, summary.guard_m),
                         ("BTR-001", CROWN_M, PROFILE, True, GUARD_M))
        self.assertGreater(len(outcome.footprint.nonzero()[0]), len(zone), "el pie sale de la zona dibujada (error 19)")
        self.assertEqual(int(np.count_nonzero(outcome.zone)), len(zone))
        calculation.discard()
        self.assertEqual(self.temporaries(), [])
        self.assertEqual(self.state(), before)

    def test_a_closing_the_steps_halfway_leaves_nothing(self) -> None:
        """RF-015-29: cerrar los pasos (Esc) a mitad del cálculo, y justo antes del último paso, no deja nada: ni un temporal ni una fila."""
        before = self.state()
        for stop in (3, 9):
            generator = steps.buttress_run(self.project, asked(), version=self.v1.uid, masks=self.masks_v1, budget_s=0.0)
            for _ in range(stop):
                next(generator)
            generator.close()
            self.assertEqual(self.temporaries(), [], f"tras {stop} pasos")
            self.assertEqual(self.state(), before)

    # --- Rechazos ------------------------------------------------------------------------------------------------------

    def test_b_the_refusals_write_nothing_and_name_what_is_wrong(self) -> None:
        """RF-016-18, RF-015-08, D-19, D-21: cada rechazo sale **antes de calcular** y no escribe nada ni deja un temporal: la cota fuera del
        ancla, con la capa, el contrafuerte, la cota, el perfil y **la cota del ancla más próxima**; sin cota de coronación (no se elige una
        por la persona) o sin resguardo (protege por defecto y el resguardo no tiene valor por defecto); una coronación **por debajo del
        apoyo** en toda la zona; una capa que no es de polígonos, una zona que no existe y un perfil sin valores."""
        error = self.refused(asked(crown=118.0), "des.buttress_crown_off_anchor")
        self.assertEqual((error.values["layer"], error.values["entity"], error.values["profile"], error.values["anchor"]),
                         (sdata.CROWN_LAYER, BUTTRESS, PROFILE, 115.0))
        self.assertIn("115", error.text)
        error = self.refused(asked(crown=None), "des.entity_param_missing")
        self.assertEqual(error.values["field"], "des.buttress.btr_001.crown_m")
        error = self.refused(asked(guard=None), "des.entity_param_missing")
        self.assertEqual(error.values["field"], "des.buttress.btr_001.guard_m")
        self.refused(asked(guard=-1.0), "des.entity_param_range")
        error = self.refused(asked(crown=105.0), "des.buttress_crown_below_support")
        self.assertEqual((error.values["layer"], error.values["entity"]), (sdata.CROWN_LAYER, BUTTRESS))
        error = self.refused(asked(feature="No hay"), "des.entity_feature_unknown")
        self.assertEqual(error.values["layer"], sdata.CROWN_LAYER)
        self.refused(asked(layer=sdata.THICKNESS_POINTS_LAYER, feature="A1"), "des.layer_not_polygons")
        self.refused(asked(profile="expl_99_60_6"), "des.profile_value_missing")
        with self.assertRaises(ValueError):
            self.calculate(asked(metric="manhattan"))
        before = self.state()
        self.assertEqual(self.temporaries(), [])
        self.assertEqual(self.state(), before)
        calculation = self.calculate(asked(guard=None, protect=False))
        self.assertFalse(calculation.summary.protect, "sin proteger no hace falta el resguardo")
        calculation.discard()

    def test_b_a_support_surface_is_read_and_its_dependency_is_noted_without_changing_the_calculation(self) -> None:
        """RF-016-17, RF-015-15 (T26, decisión 1): el contrafuerte puede apoyarse en una superficie que no es su partida (también la de
        explotación de una cantera): se lee con la rejilla del proyecto y **se anota como ``supported_on``** (lo que apoya); el cálculo es
        el mismo, sobre la partida; una superficie de apoyo que no existe se rechaza antes de calcular."""
        plain = self.calculate(asked())
        with_support = self.calculate(asked(support=HILLSIDE))
        self.assertEqual(with_support.entity.support_surface, HILLSIDE)
        self.assertIn(("supported_on", HILLSIDE), [(str(use.role), use.item) for use in with_support.entity.start.inputs])
        np.testing.assert_array_equal(with_support.outcome.surface, plain.outcome.surface)
        plain.discard()
        with_support.discard()
        before = self.state()
        with self.assertRaises(Exception) as caught:  # noqa: B017 - un GisError, no un DesignError
            self.calculate(asked(support="No hay esa superficie"))
        self.assertEqual(getattr(caught.exception, "code", None), "gis.dataset_unknown")
        self.assertEqual((self.state(), self.temporaries()), (before, []))

    # --- Crear ---------------------------------------------------------------------------------------------------------

    def test_c_creating_fails_as_a_whole_if_a_table_cannot_be_written(self) -> None:
        """RF-015-02, RF-015-29: «Crear» es **una** transacción: un fallo al escribir la segunda tabla no deja nada —ni la operación, los
        datos, los parámetros de la entidad, las cifras o los ficheros, ni un temporal— y el cálculo queda descartado."""
        calculation = self.calculate(asked())
        before = self.state()
        written: list[str] = []
        real = store.DesignWriter._write_table

        def breaks(writer: Any, conn: Any, table: Any) -> None:
            written.append(table.family)
            if len(written) == 2:
                raise RuntimeError("falla la segunda tabla")
            real(writer, conn, table)

        with mock.patch.object(store.DesignWriter, "_write_table", breaks):
            with self.assertRaises(RuntimeError):
                calculation.create(decided_by=USER)
        self.assertEqual(self.state(), before, "no queda nada")
        self.assertEqual(self.temporaries(), [])
        self.assertFalse(calculation.open, "el cálculo queda descartado")

    def test_d_creating_registers_the_buttress_in_one_transaction_with_its_footprint_and_its_crown_zone(self) -> None:
        """RF-016-17, RF-015-01, RF-015-02, P-8, H-6: «Crear» registra **de una vez** los parámetros de la entidad (``des.buttress.btr_001.*``
        de V01, con su decisor y su origen y **protegiendo por defecto**: D-1), la operación ``des.buttress`` con sus entradas (la capa de
        zonas con el papel ``entity_layer``, la partida y las máscaras) y sus parámetros (también los del perfil), la superficie **entera**,
        la huella (``des_epr_``: **15 columnas**, la huella entera y **la zona de coronación**) y el informe, y las cifras ``des.btr_*`` con
        el ámbito de la entidad; las entradas no cambian de contenido."""
        survey_before = self.record(SURVEY, self.v1).content_sha256
        layer_before = self.record(sdata.CROWN_LAYER).content_sha256
        calculation, stored = self.make(asked())
        type(self).first, type(self).stored = calculation, stored
        uid = str(stored.handle.uid)
        self.assertEqual(self.query("SELECT op_type, scope, status, supersedes_uid FROM gb_operation WHERE uid = ?", uid),
                         [(provenance.BUTTRESS, "version", "done", None)])
        self.assertEqual(self.operation_of("BTR-001"), uid)
        rows = {key: (value, decided_by) for key, value, decided_by in self.query(
            "SELECT key, value, decided_by FROM gb_parameter WHERE key LIKE 'des.buttress.btr_001.%' AND scope = 'version'")}
        for param, value in (("name", BUTTRESS), ("layer", sdata.CROWN_LAYER), ("start", SURVEY), ("profile", PROFILE), ("crown_m", CROWN_M),
                             ("metric", "exact"), ("protect", True), ("guard_m", GUARD_M)):
            found = rows[f"des.buttress.btr_001.{param}"]
            self.assertEqual((json.loads(found[0]), found[1]), (value, USER), param)
        self.assertEqual(json.loads(rows["des.buttress.btr_001.feature"][0]), "1", "la zona, por su fid")
        self.assertNotIn("des.buttress.btr_001.reach_m", rows, "sin alcance")
        read = {name for (name,) in self.query("SELECT p.key FROM gb_operation_param AS p WHERE p.operation_uid = ?", uid)}
        self.assertLessEqual({f"des.buttress.btr_001.{name}" for name in ("crown_m", "profile", "metric", "start")}, read)
        self.assertLessEqual({design_params.bench_key(PROFILE, param) for param in ("height_m", "face_deg", "berm_m")}, read,
                             "los del perfil, también")
        self.assertEqual(self.inputs_of(uid)[:2], [("entity_layer", sdata.CROWN_LAYER), ("surface", SURVEY)])
        self.assertEqual(self.outputs_of(uid), [("entity_surface", provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, BUTTRESS)),
                                                ("entity", provenance.dataset_name(provenance.ENTITY_TABLE, BUTTRESS)),
                                                ("entity_report", provenance.dataset_name(provenance.ENTITY_REPORT_TABLE, BUTTRESS))])
        self.assertEqual(self.record(SURVEY, self.v1).content_sha256, survey_before, "la partida no cambia")
        self.assertEqual(self.record(sdata.CROWN_LAYER).content_sha256, layer_before, "la capa de zonas no cambia")
        outcome = calculation.outcome
        surface = self.raster(provenance.ENTITY_SURFACE_GRID, BUTTRESS)
        np.testing.assert_array_equal(surface, outcome.compose(self.grid_of(SURVEY)))
        figures = self.figures_by_key(uid)
        for key, value in (("des.btr_volume_m3", outcome.volume_m3), ("des.btr_area_m2", outcome.area_m2),
                           ("des.btr_height_max_m", outcome.height_max_m)):
            self.assertEqual(figures[key], value, key)
        rise = surface - self.grid_of(SURVEY)
        self.assertLessEqual(abs(figures["des.btr_volume_m3"] - float(rise[rise > 0.0].sum()) * 4.0) / figures["des.btr_volume_m3"], EXACT)
        columns = [name for (_cid, name, *_rest) in self.query(f'PRAGMA table_info("{self.locator(provenance.ENTITY_TABLE, BUTTRESS)}")')]
        self.assertEqual(columns, ["fid", *(column.name for column in store.BUTTRESS_ENTITY_COLUMNS)])
        self.assertEqual(len(store.BUTTRESS_ENTITY_COLUMNS), len(store.ENTITY_COLUMNS) + 1, "la de la plataforma, sin cambio")
        (table,) = self.query(f'SELECT code, name, kind, start_surface, support_surface, layer, source_fid, mode, cells, footprint, zone FROM '
                              f'"{self.locator(provenance.ENTITY_TABLE, BUTTRESS)}"')
        self.assertEqual(table[:9], ("BTR-001", BUTTRESS, "buttress", SURVEY, None, sdata.CROWN_LAYER, 1, "buttress", int(np.count_nonzero(rise > 0.0))))
        footprint = set(zip(*(axis.tolist() for axis in entities.runs_cells(tuple(tuple(run) for run in json.loads(table[9])))), strict=True))
        zone = set(zip(*(axis.tolist() for axis in entities.runs_cells(tuple(tuple(run) for run in json.loads(table[10])))), strict=True))
        self.assertEqual(zone, self.zone_cells(), "la zona de coronación es la dibujada: 121 celdas")
        self.assertEqual(footprint, set(zip(*(axis.tolist() for axis in np.nonzero(rise > 0.0)), strict=True)), "la huella, donde la superficie sube")
        self.assertTrue(zone <= footprint and len(footprint) > len(zone), "el pie sale de la zona dibujada")
        entry = entities.registry(self.project, self.v1.uid).get("BTR-001")
        assert entry is not None
        self.assertEqual((entry.record.kind, entry.record.name, entry.record.start, entry.record.state),
                         (entities.EntityKind.BUTTRESS, BUTTRESS, SURVEY, entities.EntityState.CURRENT))
        self.assertEqual(self.temporaries(), [])
        self.assertEqual(self.stale_causes(uid), set())

    # --- La restricción que declara ------------------------------------------------------------------------------------

    def test_e_it_declares_no_cut_over_its_crown_zone_and_not_over_the_whole_footprint(self) -> None:
        """RF-015-10, RF-015-12, D-1, P-8, H-6: la entidad viva declara «sin corte» (``no_cut``) con su resguardo de 10 m obligatorio, el
        motivo generado («declarada por el contrafuerte …») y su decisor; **el contorno que declara es el de su zona de coronación** (121
        celdas y su área) y no el de toda la huella, que sube también fuera de ella; la capa de entidades y lo que se le apoya siguen con la
        huella entera."""
        with self.project.read() as conn:
            (source,) = [item for item in entity_store.declared_sources(self.project, self.v1, conn=conn) if item.code == "BTR-001"]
        self.assertEqual((source.kind, source.protect, source.guard_m, source.reason, source.decided_by),
                         (entities.EntityKind.BUTTRESS, True, GUARD_M, None, USER))
        self.assertIsNotNone(source.zone)
        footprint = entities.runs_cells(source.runs)[0].size
        self.assertEqual(entities.runs_cells(source.zone)[0].size, len(self.zone_cells()))
        self.assertGreater(footprint, len(self.zone_cells()))
        work = entity_store.declared_rows_steps((source,), GRID, str(self.v1.uid))
        while True:
            try:
                next(work)
            except StopIteration as stop:
                rows = stop.value
                break
        (declared,) = rows
        self.assertIs(declared.ctype, constraints_model.ConstraintType.NO_CUT)
        self.assertEqual((declared.entity_code, declared.buffer_out_m, declared.decided_by), ("BTR-001", GUARD_M, USER))
        self.assertTrue(declared.reason.startswith("declarada por el contrafuerte"), declared.reason)
        zone = entities.declared_zone_of_runs(source.zone, GRID, 0.0)
        whole = entities.declared_zone_of_runs(source.runs, GRID, 0.0)
        self.assertEqual((zone.cells, zone.area_m2), (len(self.zone_cells()), len(self.zone_cells()) * 4.0))
        self.assertGreater(whole.cells, zone.cells)
        for found, wanted in zip(declared.parts, zone.parts, strict=True):
            for ring, expected in zip(found, wanted, strict=True):
                np.testing.assert_array_equal(ring, expected)
        # sin proteger no declara nada, y el tipo sin zona propia declara su huella (la de la 015, sin cambio)
        self.assertEqual(entities.declaration_runs("platform", ((1, 2, 3),), None), ((1, 2, 3),))
        with self.assertRaises(ValueError):
            entities.declaration_runs("buttress", ((1, 2, 3),), None)
        with self.assertRaises(ValueError):
            entities.declaration_runs("platform", ((1, 2, 3),), ((1, 2, 3),))

    # --- Recalcular y reproducir ---------------------------------------------------------------------------------------

    def test_f_recomputing_repeats_the_buttress_with_the_parameters_of_its_entity(self) -> None:
        """RF-015-02, RF-015-16: cambiar la cota de coronación de la entidad (``des.buttress.btr_001.crown_m``: 125 m, otro ancla) la deja
        obsoleta con su causa y **«Recalcular lo obsoleto»** la repite como una operación nueva que sustituye a la anterior, con la misma
        identidad (``BTR-001``) y **sin reescribir sus parámetros**: sube más (el volumen crece)."""
        old = str(self.stored.handle.uid)
        figures = self.figures_by_key(old)
        self.assertEqual(self.stale_causes(old), set())
        self.change(design_params.entity_key("BTR-001", "crown_m"), 125.0)
        self.assertNotEqual(self.stale_causes(old), set(), "obsoleta con su causa")
        self.assertEqual(entities.registry(self.project, self.v1.uid).get("BTR-001").record.state, entities.EntityState.STALE)
        rows = self.query("SELECT key, scope, value, rev FROM gb_parameter WHERE key LIKE 'des.buttress.btr_001.%' ORDER BY key, scope")
        self.clock.advance(minutes=1)
        outcome = ops.finish(recompute_mod.recompute_steps(self.project))
        self.assertTrue(all(result.status == recompute_mod.UnitStatus.DONE for result in outcome.results), outcome.results)
        new = self.operation_of("BTR-001")
        self.assertNotEqual(new, old)
        self.assertEqual(self.query("SELECT supersedes_uid, status FROM gb_operation WHERE uid = ?", new), [(old, "done")])
        after = self.query("SELECT key, scope, value, rev FROM gb_parameter WHERE key LIKE 'des.buttress.btr_001.%' ORDER BY key, scope")
        self.assertEqual([row[0] for row in after], [row[0] for row in rows], "sin parámetros nuevos")
        self.assertGreater(self.figures_by_key(new)["des.btr_volume_m3"], figures["des.btr_volume_m3"], "con 125 m, más alto")
        self.assertEqual(self.stale_causes(new), set())
        self.assertEqual(self.temporaries(), [])
        self.assertEqual(entities.registry(self.project, self.v1.uid).get("BTR-001").record.state, entities.EntityState.CURRENT)

    def test_g_reproducing_the_frozen_revision_gives_the_same_surface_tables_and_figures(self) -> None:
        """RF-009-11, RF-015-02: congelada ``V01.r1`` con el contrafuerte, reproducirla —**sin el proyecto**: desde lo congelado, la capa de
        zonas, la partida, las máscaras y los parámetros (también los del perfil)— da la misma superficie, la misma tabla de la entidad
        (**con su zona de coronación**) y el mismo informe (el hash de cada dato) y las mismas cifras; reproducir no escribe nada."""
        self.clock.advance(minutes=1)
        frozen = ops.finish(freeze.freeze_steps(self.project, self.v1.uid, reason="Entrega de la prueba"))
        type(self).revision = str(frozen.frozen.uid)
        self.clock.advance(minutes=1)
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        report = ops.finish(reproduce_mod.reproduce_steps(self.project, self.revision))
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root)), before, "reproducir no escribe")
        uid = self.operation_of("BTR-001")
        mine = [check for check in report.outputs if check.operation_uid == uid]
        self.assertEqual(len(mine), 3, f"la superficie, la huella con su zona y el informe: {report.not_reproducible} {report.outputs}")
        self.assertTrue(all(check.same for check in mine), [check for check in mine if not check.same])
        self.assertEqual(len([check for check in report.figures if check.operation_uid == uid]), 3, "las tres cifras")
        self.assertTrue(all(check.same for check in report.outputs), [check for check in report.outputs if not check.same])
        self.assertTrue(all(check.same for check in report.figures), [check for check in report.figures if not check.same])
        self.assertFalse(report.not_reproducible)
        self.assertTrue(report.matches)

    # --- Lo que sigue a crearlo ----------------------------------------------------------------------------------------

    def test_h_what_follows_declares_no_cut_in_the_version_and_compiles_the_masks_with_it(self) -> None:
        """RF-015-10, RF-012-06, D-1: lo que sigue a crearlo (``after_entity_change``) declara «sin corte» **de la zona de coronación** en la
        tabla de las restricciones declaradas de V01 (una, con el código y el nombre del contrafuerte), compila de nuevo las máscaras con
        ella y pone al día la capa de entidades (que lo enseña con su huella **entera**); nada de ello falla."""
        self.clock.advance(minutes=1)
        chain = ops.finish(entity_store.after_entity_change(self.project, self.v1.uid))
        self.assertIsNone(chain.failure, chain.failure)
        self.assertIsNone(chain.layer_failure, chain.layer_failure)
        self.assertEqual(chain.declared, 1)
        self.assertTrue(chain.declaration_changed and chain.masks_compiled)
        (row,) = self.query(f'SELECT code, name, ctype FROM "{provenance.dataset_locator(provenance.DECLARED_TABLE, "", "V01")}"')
        self.assertEqual(row[2], "no_cut")
        self.assertIn("BTR-001", row[0] + str(row[1]) + "BTR-001")
        with self.project.read() as conn:
            (found,) = [item for item in entity_store.layer_sources(self.project, self.v1, conn=conn) if item.code == "BTR-001"]
        self.assertGreater(entities.runs_cells(found.runs)[0].size, len(self.zone_cells()), "la capa enseña la huella entera")


if __name__ == "__main__":
    unittest.main()

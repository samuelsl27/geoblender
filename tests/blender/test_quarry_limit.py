# SPDX-License-Identifier: GPL-3.0-or-later
"""La cantera frente a un límite nuevo en Blender (spec 014, T31; HU-014-7; RF-014-26; plan 014
A13, §5.5; comprobación manual M6).

Al recompilar las máscaras de una versión («Compilar las máscaras»,
``geoblender.gis_compile_constraints``, o su recálculo en la cola de las máscaras desde «Recalcular
lo obsoleto»), cada superficie de diseño de la 014 de la versión que mueve algo fuera del límite
vigente sale en el resumen de la compilación (la ventana Restricciones… y el informe de Blender)
como aviso con su volumen y su área (``des.refit_outside``, que lleva a «Ajustar el diseño a un
límite nuevo…»); la barra N «Diseño» lo dice también, en alerta, en la ficha de la superficie.

Desde la T35 (RNF-014-02), **por pasos y con una caché**: la comprobación sigue a la compilación en
los pasos de su modal y de su recálculo en la cola, sin que ninguna llamada haga las dos cosas (Esc
durante ella deja la compilación guardada y no guarda nada de la comprobación), y llena la caché en
memoria de ``des_panels`` (``design.store.LimitCheckMemo``), de la que leen la ficha de la barra N y
el diálogo de «Ajustar el diseño a un límite nuevo…» sin leer ninguna rejilla; sin acierto, la ficha
no dice nada y comprueba por pasos en un temporizador (``des_panels.limit_tick``; en ``blender -b``
no corre: la prueba lo llama) que vuelve a leerla, y el diálogo comprueba por pasos en el modal de
su orden antes de abrirse.

Un proyecto pequeño por clase (ventana de 60 × 40 m con celdas de 2 m, V01, el límite legal de
(4, 4) a (56, 36) con 2 m hacia dentro, el perímetro de (2, 2) a (58, 38), un sector con la búsqueda
cerrada, la ladera ``100 + 0,25·y + 0,0625·x`` y el perfil ``REST_5_35_6``) con la cantera «Corta»
de V01 creada por el dominio. Las pruebas, en el orden de sus letras: con el límite de su diseño;
después, con el límite legal **30 m más corto por el este** (de x = 56 a x = 26).

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import contextlib
import dataclasses
import importlib
import tempfile
import unittest
import uuid
from datetime import date
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.core_fixtures import settings_values
from tests.support.fake_layout import operator_self
from tests.support.trees import remove_tree

REASON = "Prueba de la cantera frente a un límite nuevo"
PERSON = "Samuel (IMGA)"
SOURCE = "Plan de restauración"
WEST = 700_000.0
SOUTH = 4_400_000.0
WIDTH_M, HEIGHT_M = 60.0, 40.0
STEP_M = 2.0
LEGAL = (4.0, 4.0, 56.0, 36.0)
INWARD_M = 2.0
PERIMETER = (2.0, 2.0, 58.0, 38.0)
CUT_BACK_M = 30.0
NEW_LEGAL = (LEGAL[0], LEGAL[1], LEGAL[2] - CUT_BACK_M, LEGAL[3])
NO_LONGER_CUT_X = NEW_LEGAL[2] - INWARD_M
"""Al este de esta x (local) el corte deja de estar admitido con el límite nuevo: 26 − 2 m."""
SECTOR = ("Sector único", (0.0, 0.0, WIDTH_M, HEIGHT_M))
CLOSED_AT = "2026-11-13T10:00:00Z"
REST, REST_CODE = "REST_5_35_6", "rest_5_35_6"
QUARRY_NAME = "Corta"
THICKNESS_M = 0.02
"""El espesor mínimo de la 012 por defecto (el proyecto no declara otro)."""
TIMER = SimpleNamespace(type="TIMER", value="NOTHING")
ESCAPE = SimpleNamespace(type="ESC", value="PRESS")
OUTSIDE = "fuera del límite vigente"


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def ring(box: tuple[float, float, float, float]) -> np.ndarray:
    """El anillo absoluto, cerrado y antihorario, del rectángulo local ``box``."""
    left, bottom, right, top = box
    return np.array([(WEST + left, SOUTH + bottom), (WEST + right, SOUTH + bottom),
                     (WEST + right, SOUTH + top), (WEST + left, SOUTH + top),
                     (WEST + left, SOUTH + bottom)], dtype=np.float64)


def centres() -> tuple[np.ndarray, np.ndarray]:
    """Las coordenadas locales de los centros de celda (fila 0 al norte)."""
    columns = STEP_M * np.arange(int(WIDTH_M / STEP_M), dtype=np.float64) + STEP_M / 2
    rows = HEIGHT_M - (STEP_M * np.arange(int(HEIGHT_M / STEP_M), dtype=np.float64) + STEP_M / 2)
    return np.meshgrid(columns, rows)


def ground() -> np.ndarray:
    """La ladera ``100 + 0,25·y + 0,0625·x`` en los centros de celda."""
    x, y = centres()
    return 100.0 + 0.25 * y + 0.0625 * x


def window() -> bpy.types.Window:
    return bpy.context.window_manager.windows[0]


class _Rows(list):  # type: ignore[type-arg]
    """La colección de filas de la orden, de mentira (``add`` y ``clear``)."""

    def add(self) -> SimpleNamespace:
        row = SimpleNamespace(name="", label="", outside=False, selected=False)
        self.append(row)
        return row


def drained(steps: Any) -> Any:
    """El resultado del último de unos pasos (``Progress``) llevados hasta el final."""
    found = None
    for step in steps:
        if step.result is not None:
            found = step.result
    return found


class QuarryLimitTest(unittest.TestCase):
    """La extensión habilitada una vez y el proyecto de la cantera, para toda la clase."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        folder = Path(tempfile.mkdtemp(prefix="gb-t31-"))
        cls.addClassCleanup(remove_tree, folder)
        (folder / "proyectos").mkdir()
        cls.ps = _module("bl.scene.project_session")
        cls.session = _module("bl.ops.core_provenance")
        cls.panels = _module("bl.ui.des_panels")
        cls.constraint_panels = _module("bl.ui.constraint_panels")
        cls.gis_ops = _module("bl.ops.gis")
        cls.jobs_ops = _module("bl.ops.jobs")
        cls.queue = _module("bl.ops.incorporation")
        cls.cmodel = _module("core.constraints.model")
        cls.cstore = _module("core.constraints.store")
        cls.cprov = _module("core.constraints.provenance")
        cls.dprov = _module("design.provenance")
        cls.dstore = _module("design.store")
        cls.surfaces = _module("design.surfaces")
        cls.des_ops = _module("bl.ops.des")
        cls.commands = _module("bl.ui.commands")
        cls.i18n = _module("core.i18n")
        core_project = _module("core.project")
        settings = core_project.ProjectSettings(**settings_values(
            window=(WEST, SOUTH, WEST + WIDTH_M, SOUTH + HEIGHT_M), grid_step_m=STEP_M))
        cls.project = core_project.create_project(
            folder / "proyectos", settings, cls.ps.session(), cls.ps.userdata()).project
        cls.addClassCleanup(cls.project.close)
        with cls.project.write_transaction() as conn:
            cls.v01, _revision = _module("core.versions.store").create_version(
                conn, cls.project, feature="cantera", title="Cantera", reason=REASON)
        cls.project.refresh_header()
        cls.declare()
        cls.ground = cls.write_grid("Ladera", ground())
        cls.ps.attach(cls.project)
        cls.addClassCleanup(cls.ps.close)
        for _ in range(2000):  # la comprobación de apertura (sin temporizadores en blender -b)
            if cls.session.check_tick() is None:
                break
        assert bpy.ops.geoblender.core_set_active_version(version_uid=cls.v01.uid) == {"FINISHED"}
        assert bpy.ops.geoblender.gis_compile_constraints() == {"FINISHED"}  # las máscaras de V01
        assert bpy.ops.geoblender.des_save_bench_profile(
            name=REST, kind="ADOPTADO", source=SOURCE, decided_by=PERSON, reason=REASON,
            scope="PROJECT", height="5", face="35", berm="6", anchor="125") == {"FINISHED"}
        dmodel = _module("design.model")
        side = dmodel.QuarrySide(REST_CODE)
        found = None
        for found in _module("design.steps").quarry_run(
                cls.project, dmodel.QuarryRequest(QUARRY_NAME, cls.ground, side, side),
                version=cls.v01.uid):
            pass
        found.result.create()
        cls.final = cls.dprov.dataset_name("fin", QUARRY_NAME)
        cls.exploitation = cls.dprov.dataset_name("exp", QUARRY_NAME)

    @classmethod
    def declare(cls) -> None:
        """El límite legal (2 m hacia dentro), el perímetro de actuación y el sector de búsqueda,
        con su búsqueda cerrada, como los dejan las órdenes de la 012."""
        m, kinds, types = cls.cmodel, cls.cmodel.GeometryKind, cls.cmodel.ConstraintType

        def row(ctype: Any, name: str, box: tuple[float, float, float, float]) -> Any:
            return m.Constraint(
                uid=uuid.uuid4().hex, code="", name=name, ctype=ctype, kind=kinds.POLYGON,
                parts=((ring(box),),), priority=0, reason=f"{REASON}: {name}", decided_by=PERSON,
                decided_on=date(2026, 11, 13), decision_uid=None, intention_uid=None,
                source_input=None, source_fid=None, layer=cls.cstore.layer_of(kinds.POLYGON), fid=0)

        declaration = cls.cprov.ParamDeclaration(
            values={m.ConstraintParam.BUFFER_IN: INWARD_M, m.ConstraintParam.BUFFER_OUT: 0.0,
                    m.ConstraintParam.ACTIVE: True},
            source="Criterio de la prueba", decided_by=PERSON, reason=REASON)
        cls.cprov.edit_constraints(cls.project, [row(types.LEGAL_LIMIT, "Concesión", LEGAL),
                                                 row(types.ACTION_PERIMETER, "Perímetro",
                                                     PERIMETER)],
                                   params=declaration, srs_id=cls.project.record.crs_epsg)
        operations = _module("core.provenance.operations")
        sector = cls.cmodel.Sector(f"sector1{'0' * 26}", "sector_1", SECTOR[0], (ring(SECTOR[1]),))
        handle = operations.begin_operation(cls.project, "core.edit_constraints",
                                            settings={"count": 0}, executor="blender")
        with cls.project.write_transaction() as conn:
            cls.cstore.write_sectors(conn, (sector,), srs_id=cls.project.record.crs_epsg)
            handle.complete(conn, outputs=cls.cstore.dataset_specs(
                crs_epsg=cls.project.record.crs_epsg), message="Sector de prueba")
        handle = operations.begin_operation(cls.project, "core.edit_constraints",
                                            settings={"count": 0}, executor="blender")
        record = cls.cmodel.SearchRecord(uuid.uuid4().hex, handle.uid, "sector_1",
                                         cls.cstore.sector_sha256(sector), 25.0, PERSON,
                                         CLOSED_AT)
        with cls.project.write_transaction() as conn:
            cls.cstore.append_search(conn, record, ())
            handle.complete(conn, outputs=cls.cstore.dataset_specs(
                crs_epsg=cls.project.record.crs_epsg), message="Búsqueda de prueba")

    @classmethod
    def write_grid(cls, name: str, values: np.ndarray) -> str:
        """Una rejilla del proyecto de la ventana con ``values``; el nombre de su dato."""
        gis_store = _module("gis.store")
        record = cls.project.record
        grid = _module("gis.grid").project_grid(record.window, float(record.grid_step_m))
        crs, vertical = gis_store.project_references(cls.project)
        handle = _module("core.provenance.operations").begin_operation(
            cls.project, _module("gis.provenance").RESAMPLE, settings={"nombre": name},
            executor="blender")
        library, library_version = _module("gis.crs").crs_library()
        with gis_store.ResultWriter(cls.project, handle) as out:
            out.raster(name, _module("gis.raster").Raster(grid, values, crs, vertical))
            records = out.commit(software={library: library_version}, message=REASON)
        return str(records[0].name)

    def setUp(self) -> None:
        if not blender_ext.is_enabled():
            blender_ext.enable()
        self.addCleanup(self.i18n.set_language, self.i18n.language())
        self.i18n.set_language("es")

    # --- Ayudas -------------------------------------------------------------------------------

    def stored(self) -> tuple[Any, ...]:
        """Las restricciones guardadas en el proyecto."""
        with self.project.read() as conn:
            return self.cstore.read_constraints(conn)

    def uid_of(self, name: str) -> str:
        with self.project.read() as conn:
            (uid,) = [row[0] for row in conn.execute(
                "SELECT uid FROM gb_dataset WHERE name = ? AND status IN ('current', 'stale')",
                (name,))]
        return str(uid)

    def card(self, name: str) -> list[Any]:
        """Las líneas de la ficha de la barra N del dato vivo ``name``."""
        return list(self.panels.item_lines(self.project, self.uid_of(name)).lines)

    def no_grid_read(self) -> Any:
        """Un contexto en el que leer una rejilla del diseño es un error de la prueba (lo que sale
        de la caché no lee ninguna)."""
        stack = contextlib.ExitStack()
        for module in (self.dstore, self.surfaces):
            stack.enter_context(mock.patch.object(module, "read_surface",
                                                  side_effect=AssertionError("lee una rejilla")))
        return stack

    def running(self, cls: type) -> Any:
        """El modal de ``cls`` en marcha (el único con pasos)."""
        found = [op for op in window().modal_operators
                 if isinstance(op, cls) and getattr(op, "_steps", None) is not None]
        self.assertEqual(len(found), 1, f"{cls.__name__} no está en marcha")
        return found[0]

    def compile_in_steps(self) -> Any:
        """«Compilar las máscaras» como desde la interfaz, por pasos, con un paso por evento del
        temporizador de su modal (``STEP_BUDGET_S`` a 0); devuelve el modal en marcha."""
        cls = self.commands.registered_class("geoblender.gis_compile_constraints")
        self.enterContext(mock.patch.object(cls, "STEP_BUDGET_S", 0.0))
        with bpy.context.temp_override(window=window()):
            self.assertEqual(bpy.ops.geoblender.gis_compile_constraints(
                "EXEC_DEFAULT", in_steps=True), {"RUNNING_MODAL"})
        return self.running(cls)

    def compiled_uids(self) -> list[str]:
        """Las compilaciones de las máscaras hechas, en orden."""
        with self.project.read() as conn:
            return [row[0] for row in conn.execute(
                "SELECT uid FROM gb_operation WHERE op_type = 'gis.compile_constraints' AND "
                "status = 'done' ORDER BY fid")]

    def outside_by_hand(self, name: str) -> tuple[int, float]:
        """Las celdas y el volumen que la superficie ``name`` mueve al este de
        :data:`NO_LONGER_CUT_X` (más que el espesor mínimo frente a la ladera), a mano."""
        values = _module("design.surfaces").read_surface(self.project, name,
                                                         version_uid=self.v01.uid).values
        x, _y = centres()
        moved = np.isfinite(values) & (np.abs(values - ground()) > THICKNESS_M)
        outside = moved & (x > NO_LONGER_CUT_X)
        self.assertFalse((values[outside] > ground()[outside]).any())  # la cantera solo corta
        area = STEP_M * STEP_M
        return (int(np.count_nonzero(outside)),
                float(np.abs(values - ground())[outside].sum()) * area)

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_with_the_limit_of_its_design_nothing_is_said(self) -> None:
        """RF-014-26: con el límite con que se diseñó, ni el resumen de una compilación ni la ficha
        de la barra N de las dos superficies de la cantera dicen nada de él; las envolventes y la
        clasificación no se comprueban. La barra N mira los tipos de ``design.store``."""
        self.assertEqual(self.panels._LIMIT_CHECKED, frozenset(self.dstore.LIMIT_CHECKED_TYPES))
        self.assertEqual(drained(self.panels.limit_steps(self.project, self.v01.uid)), [])
        self.assertIn(self.panels.limit_steps, self.constraint_panels._COMPILE_CHECKS)
        for name in (self.exploitation, self.final):
            with self.subTest(superficie=name):
                self.assertFalse(any("fuera del límite vigente" in line.text
                                     for line in self.card(name)))

    def test_b_a_limit_cut_back_30_m_is_said_when_the_masks_are_compiled(self) -> None:
        """RF-014-26 (M6; error 46): con el límite legal 30 m más corto por el este, «Compilar las
        máscaras» termina con un aviso en alerta por cada superficie de la cantera, con el volumen y
        el área de lo que corta al este de x = 24 m (local), a mano, en la ventana Restricciones… y
        en el informe de Blender; la ficha de la barra N de cada una lo dice en alerta, tras su
        estado, en el idioma de Geoblender."""
        (legal,) = [item for item in self.stored() if item.name == "Concesión"]
        self.cprov.edit_constraints(self.project, [dataclasses.replace(
            legal, parts=((ring(NEW_LEGAL),),))], srs_id=self.project.record.crs_epsg)
        self.assertEqual(bpy.ops.geoblender.gis_compile_constraints(), {"FINISHED"})
        shown = [(line.text, line.alert) for line in self.constraint_panels.view().report_lines]
        warned = [(text, alert) for text, alert in shown if OUTSIDE in text]
        self.assertEqual(len(warned), 2, shown)
        for name in (self.exploitation, self.final):
            with self.subTest(superficie=name):
                cells, volume = self.outside_by_hand(name)
                self.assertGreater(cells, 0)
                (check,) = self.dstore.limit_checks(self.project, self.v01.uid, names=(name,))
                self.assertEqual((check.cells, check.area_m2), (cells, cells * STEP_M * STEP_M))
                self.assertAlmostEqual(check.volume_m3, volume, delta=1e-9 * volume)
                text = check.notice.text("es")
                self.assertIn((text, True), warned)
                self.assertTrue(text.startswith(f"«{name}» deja "), text)
                with self.no_grid_read():  # la ficha, de la caché que llenó la compilación (T35)
                    card = self.card(name)
                    self.assertEqual((card[1].text, card[1].alert), (text, True))
                    self.i18n.set_language("en")
                    self.assertEqual(self.card(name)[1].text, check.notice.text("en"))
                    self.i18n.set_language("es")

    def test_c_its_recalculation_says_it_too(self) -> None:
        """RF-014-26: una compilación recalculada en la cola de las máscaras («Recalcular lo
        obsoleto») lleva también al registro de Blender el aviso de cada superficie fuera del
        límite vigente de su versión."""
        progress = _module("core.project.model").Progress

        def steps() -> Any:
            yield progress("save", 1, 1, "…", SimpleNamespace(result=SimpleNamespace(notices=())))

        handle = SimpleNamespace(uid="op-t31", op_type="gis.compile_constraints", settings={},
                                 version_uid=self.v01.uid, fail=lambda reason: None,
                                 cancel=lambda reason: None)
        expected = [check.notice.text("es") for check in
                    self.dstore.limit_checks(self.project, self.v01.uid)]
        self.assertEqual(len(expected), 2)
        with mock.patch.object(self.queue, "status_text"):
            self.gis_ops.queue_mask_steps(handle, steps())
            while self.gis_ops.masks_tick() is not None:
                pass
        sent = self.jobs_ops.sent_reports()
        for text in expected:
            self.assertIn(("WARNING", text), sent)


    def test_d_in_steps_the_check_follows_the_saved_compilation(self) -> None:
        """RNF-014-02 (spec 014, T35; RF-014-26): «Compilar las máscaras» desde la interfaz da los
        pasos de la comprobación **tras** los suyos: ninguno de la comprobación antes de guardar la
        compilación ni en el mismo paso que la guarda (el de su transacción se da sin lo guardado),
        con su texto en la barra de estado; al terminar, el resumen con los dos avisos y la caché
        llena (la ficha, sin leer ninguna rejilla). Esc durante la comprobación: la compilación
        queda guardada y la orden termina con su resumen y la línea que dice que la comprobación se
        omitió, sin los avisos ni nada en la caché."""
        check = self.constraint_panels.CHECK_PHASE
        before = self.compiled_uids()
        modal = self.compile_in_steps()
        state = {"RUNNING_MODAL"}
        for _event in range(500):
            state = modal.modal(bpy.context, TIMER)
            if state != {"RUNNING_MODAL"}:
                break
        self.assertEqual(state, {"FINISHED"})
        phases = [entry[1] for entry in modal.progress_log]
        first = phases.index(check)
        self.assertGreater(first, 1)
        self.assertNotIn(check, phases[:first])
        self.assertTrue(all(phase == check for phase in phases[first:-1]), phases)
        self.assertEqual(phases[-1], phases[first - 1])  # el último, como el que guardó
        self.assertIsNotNone(modal.stored)
        self.assertEqual(len(self.compiled_uids()), len(before) + 1)
        progress = _module("core.project.model").Progress
        self.assertEqual(modal._status_text(progress(check, 1, 1, "")),
                         "Comprobando los datos de la versión contra las máscaras nuevas… · Esc: "
                         "omitir la comprobación")
        self.assertEqual(len([text for text in modal.report_log if OUTSIDE in text]), 2)
        with self.no_grid_read():
            self.assertEqual(len(self.panels._LIMITS.memo().lookup(self.project, self.v01.uid)),
                             2)
            self.assertIn(OUTSIDE, self.card(self.final)[1].text)

        modal = self.compile_in_steps()  # Esc en cuanto empieza la comprobación
        for _event in range(500):
            self.assertEqual(modal.modal(bpy.context, TIMER), {"RUNNING_MODAL"})
            if modal.progress_log[-1][1] == check:
                break
        self.assertEqual(modal.modal(bpy.context, ESCAPE), {"FINISHED"})
        self.assertEqual(modal.outcome, "FINISHED")
        self.assertEqual(len(self.compiled_uids()), len(before) + 2)
        self.assertIs(self.access().mask_state(self.project, self.v01.uid)[0],
                      self.access().MaskState.CURRENT)
        skipped = ("Comprobación de los datos de la versión contra las máscaras nuevas omitida: "
                   "las máscaras están compiladas y guardadas")
        self.assertIn(skipped, modal.report_log)
        self.assertFalse(any(OUTSIDE in text for text in modal.report_log))
        shown = [(line.text, line.alert) for line in self.constraint_panels.view().report_lines]
        self.assertIn((skipped, True), shown)
        self.assertIsNone(self.panels._LIMITS.memo().lookup(self.project, self.v01.uid))

    def access(self) -> ModuleType:
        return _module("gis.masks.access")

    def test_e_without_a_hit_the_card_checks_in_a_timer(self) -> None:
        """RNF-014-02 (spec 014, T35; RF-014-26): sin acierto en la caché, la ficha de la barra N no
        se bloquea: no dice nada del límite y lanza la comprobación por pasos en su temporizador
        (``des_panels.limit_tick``, una sola aunque se lea otra ficha de la versión), que llena la
        caché y vuelve a leer las fichas; después, la ficha lo dice sin leer ninguna rejilla.
        Cerrar el proyecto (o desactivar) vacía la caché."""
        panels = self.panels
        self.addCleanup(lambda: bpy.app.timers.is_registered(panels.limit_tick)
                        and bpy.app.timers.unregister(panels.limit_tick))
        panels.forget_limit_checks()
        with mock.patch.object(bpy.app.timers, "register") as register:
            self.assertFalse(any(OUTSIDE in line.text for line in self.card(self.final)))
            work = panels._LIMITS.work
            self.assertIsNotNone(work)
            self.assertFalse(any(OUTSIDE in line.text for line in self.card(self.exploitation)))
            self.assertIs(panels._LIMITS.work, work)  # la misma: ya estaba en marcha
        register.assert_called_once()
        self.assertIs(register.call_args.args[0], panels.limit_tick)
        self.assertTrue(register.call_args.kwargs["persistent"])
        with mock.patch.object(panels, "_reread_cards") as reread:
            ticks = 1
            while panels.limit_tick() is not None:
                ticks += 1
                self.assertLess(ticks, 500)
        reread.assert_called_once_with()
        self.assertIsNone(panels._LIMITS.work)
        self.assertIsNone(panels.limit_tick())
        with self.no_grid_read():
            self.assertIn(OUTSIDE, self.card(self.final)[1].text)
            self.assertIn(OUTSIDE, self.card(self.exploitation)[1].text)
        self.assertGreater(len(panels._LIMITS.memo()), 0)
        panels.on_project_changed(None)
        self.assertEqual(len(panels._LIMITS.memo()), 0)

    def test_f_without_a_hit_the_refit_dialog_checks_before_opening(self) -> None:
        """RNF-014-02 (spec 014, T35; RF-014-26, RF-014-27): sin acierto, «Ajustar el diseño a un
        límite nuevo…» desde la interfaz no abre su ventana: comprueba antes por pasos en su modal
        (con su texto en la barra de estado) y, al terminar, se vuelve a abrir con las filas ya
        marcadas (las dos superficies de la cantera, fuera del límite vigente) y la caché llena.
        Esc a mitad no abre nada ni guarda nada en la caché. Con acierto, abre su ventana sin leer
        ninguna rejilla. (En ``blender -b`` Blender no llama a ``invoke``: se llama a mano con un
        ``self`` y un contexto de mentira, y el modal se avanza como lo haría su temporizador.)"""
        cls = self.commands.registered_class("geoblender.des_refit_to_limit")
        core_ops = _module("bl.ops.core")
        progress = _module("core.project.model").Progress
        self.enterContext(mock.patch.object(cls, "STEP_BUDGET_S", 0.0))
        later = self.enterContext(mock.patch.object(self.des_ops, "_invoke_later"))
        expected = {check.surface: check for check in self.dstore.limit_checks(
            self.project, self.v01.uid, types=self.dstore.REFIT_SOURCES)}
        self.assertEqual(sorted(expected), sorted([self.exploitation, self.final]))

        def invoked() -> tuple[Any, Any]:
            manager = SimpleNamespace(**{name: mock.Mock() for name in (
                "event_timer_add", "event_timer_remove", "modal_handler_add", "progress_begin",
                "progress_update", "progress_end", "invoke_props_dialog")})
            context = SimpleNamespace(window=window(), window_manager=manager, workspace=None,
                                      selected_objects=())
            fake = operator_self(cls, name="", surfaces=_Rows(), start="", note="",
                                 confirm=False, in_steps=False, report=lambda kind, text: None,
                                 properties=SimpleNamespace(is_property_set=lambda name: False))
            return fake, context

        for escape in (True, False):
            with self.subTest(esc=escape):
                self.panels.forget_limit_checks()
                later.reset_mock()
                fake, context = invoked()
                self.assertEqual(cls.invoke(fake, context, None), {"RUNNING_MODAL"})
                context.window_manager.invoke_props_dialog.assert_not_called()
                context.window_manager.modal_handler_add.assert_called_once_with(fake)
                self.assertEqual(fake._status_text(progress("limit_check", 0, 0, "")),
                                 "Comprobando las superficies de diseño contra el límite "
                                 "vigente… · Esc: cancelar")
                self.assertIsNone(fake._result(context, progress(
                    "limit_check", 0, 0, "")))
                self.assertEqual(core_ops._StepsModal.modal(fake, context, TIMER),
                                 {"RUNNING_MODAL"})
                if escape:
                    self.assertEqual(core_ops._StepsModal.modal(fake, context, ESCAPE),
                                     {"CANCELLED"})
                    self.assertIn("Comprobación cancelada: no se ha abierto la ventana",
                                  fake.report_log)
                    later.assert_not_called()
                    self.assertEqual(len(self.panels._LIMITS.memo()), 0)
                    continue
                state = {"RUNNING_MODAL"}
                for _event in range(500):
                    state = core_ops._StepsModal.modal(fake, context, TIMER)
                    if state != {"RUNNING_MODAL"}:
                        break
                self.assertEqual(state, {"FINISHED"})
                context.window_manager.invoke_props_dialog.assert_not_called()
                later.assert_called_once()
                self.assertEqual(later.call_args.args[0], "geoblender.des_refit_to_limit")
                values = later.call_args.kwargs
                self.assertEqual(values["note"], "")
                rows = {row["name"]: row for row in values["surfaces"]}
                self.assertEqual(sorted(rows), sorted(expected))
                for row in rows.values():
                    self.assertEqual((row["outside"], row["selected"]), (True, True))
                    self.assertIn(OUTSIDE, row["label"])
        fake, context = invoked()  # con acierto: la ventana, sin leer ninguna rejilla
        with self.no_grid_read():
            self.assertEqual(self.panels.cached_refit_rows(self.project, self.v01.uid),
                             ([(name, rows[name]["label"], True) for name in sorted(rows)], ""))
            cls.invoke(fake, context, None)
        context.window_manager.invoke_props_dialog.assert_called_once()
        context.window_manager.modal_handler_add.assert_not_called()
        self.assertEqual([(row.name, row.outside, row.selected) for row in fake.surfaces],
                         [(name, True, True) for name in sorted(rows)])

if __name__ == "__main__":
    unittest.main()

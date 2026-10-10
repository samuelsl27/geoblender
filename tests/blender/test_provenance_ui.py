# SPDX-License-Identifier: GPL-3.0-or-later
"""La procedencia en la interfaz: barra de estado, control 7 y lo obsoleto (spec 008, fase 8;
plan 008 §5.5; ADR-0012).

T49:

- RF-008-16, RF-008-28, RF-008-58: los campos «⚠ n entradas», «! n obsoletos» y «Comprobando
  el proyecto… n %» (con su botón de cancelar) se ven en la barra de estado en los dos modos
  (Geoblender y Blender), solo si hay algo y con su número: sin proyecto, o con todo al día,
  ninguno.
- RF-008-28: el control 7 del acceso rápido dice el número de lo obsoleto tras Refrescar, y
  ese número abre ``GEOBLENDER_PT_core_stale``, que dice «Refrescar · obsoletos (n)» y lista
  cada resultado obsoleto con su causa, su módulo y Recalcular.
- RNF-008-06: los campos se ponen al día ≤ 1 s después de un cambio en el proyecto (el
  temporizador de los indicadores, cada ≤ 0,5 s, y lo que tarda en leerlos) y dibujarlos
  cuesta ≤ 1 ms.
- RF-008-32: el aviso de Ctrl+Z se ve en la barra de estado durante 10 s.
- Principio 8: desregistrar quita los campos, el número del control 7, el panel, la escucha
  del proyecto y los temporizadores.

T50 (Parámetros del proyecto):

- RF-008-06: ``geoblender.core_show_parameters`` abre ``GEOBLENDER_PT_core_parameters``, cuya
  lista (``GEOBLENDER_UL_core_parameters``) dice de cada parámetro su valor con su unidad, su
  insignia de tipo (la de [HIP] en ámbar), sus marcas, su origen, su decisor y su fecha; se
  filtra por módulo, tipo y marca, y enseña el historial completo del seleccionado
  (``GEOBLENDER_UL_core_parameter_history``) con Cambiar y Confirmar; en solo lectura, los
  dos desactivados con el motivo, y la lista se sigue consultando.
- RF-008-02, RF-008-03: Cambiar rechaza los casos de la spec §8 con su texto y sin guardar
  nada (sin motivo, fuera de rango, NaN, vacío, CALCULADO a mano) y guarda «35 %» como 0,35 en
  un parámetro en fracción; cambiar o Confirmar quitan «sin confirmar» y añaden una fila al
  historial, sin tocar las anteriores.
- RF-008-59: el aviso de divergencia del seleccionado lleva «Usar el valor calculado…», que
  abre Cambiar relleno con la cifra calculada y su operación; nada cambia hasta que la persona
  lo acepta, y entonces el parámetro es CALCULADO con esa operación.
- ARQ-13: ninguna propiedad de las órdenes de parámetros es flotante.

Se ejecuta con ``tools/run_blender_tests.py``. En ``blender -b`` los temporizadores no corren:
las pruebas llaman a su función. El proyecto es sintético (la demostración de la 008 y los
GeoPackage de ``tests/data/core/provenance/``).
"""

import importlib
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.core_fixtures import settings_values
from tests.support.fake_layout import FakeLayout, draw
from tests.support.provenance_demo import PRODUCTION, SWELL_FACTOR, Demo
from tests.support.repo import ROOT

DATA = ROOT / "tests" / "data" / "core" / "provenance"
MAX_TICKS = 300  # la comprobación de un proyecto pequeño acaba en unas decenas de pasos
REFRESH = "geoblender.core_refresh"
STALE_PANEL = "GEOBLENDER_PT_core_stale"
SHOW_INPUTS = "geoblender.core_show_inputs"
CANCEL_CHECKS = "geoblender.core_cancel_checks"
RECOMPUTE = "geoblender.core_recompute_stale"
FIELD_KEYS = ("provenance_inputs", "provenance_stale", "provenance_checking",
              "provenance_undo")
UNDO_TEXT = "Ctrl+Z no deshace la operación «gis.resample»: sigue en el proyecto"
DRAWS = 300  # dibujos para medir lo que cuesta uno
DRAW_BUDGET_S = 0.001  # RNF-008-06
UPDATE_BUDGET_S = 1.0  # RNF-008-06
PARAMETERS_PANEL = "GEOBLENDER_PT_core_parameters"
PARAMETERS_LIST = "GEOBLENDER_UL_core_parameters"
HISTORY_LIST = "GEOBLENDER_UL_core_parameter_history"
SHOW_PARAMETERS = "geoblender.core_show_parameters"
SET_PARAMETER = "geoblender.core_set_parameter"
CONFIRM_PARAMETER = "geoblender.core_confirm_parameter"
COPY_LIMIT = "core.original_copy_limit"
RECOVERY = "demo.recovery"  # de prueba: una fracción (spec §8, «35 %»)
KEYS = [COPY_LIMIT, PRODUCTION, RECOVERY, SWELL_FACTOR]  # por clave
USE_CALCULATED = "Usar el valor calculado…"
READ_ONLY = "Proyecto en solo lectura:"  # y el motivo del proyecto
PROPERTY = {"kind": "ADOPTADO", "source": "Acta de la propiedad", "source_kind": "DOCUMENT",
            "decided_by": "la propiedad", "decided_at": "24/09/2026"}


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def _ctx(*, geoblender: bool) -> SimpleNamespace:
    """La barra de estado de una ventana de 1920 px en modo Geoblender o Blender."""
    window = bpy.context.window_manager.windows[0]
    return SimpleNamespace(workspace=SimpleNamespace(geoblender_mode=geoblender),
                           region=SimpleNamespace(width=1920.0), scene=bpy.context.scene,
                           window=window, screen=window.screen, area=None,
                           preferences=bpy.context.preferences)


class ProvenanceUiTest(unittest.TestCase):
    """Con la extensión habilitada una vez para todas y una carpeta temporal."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.unload()
        blender_ext.enable()
        cls.ui = _module("bl.ui.provenance")
        cls.session = _module("bl.ops.core_provenance")
        cls.ps = _module("bl.scene.project_session")
        cls.statusbar = _module("bl.ui.statusbar")
        cls.quick = _module("bl.ui.quick_access")
        cls.core = _module("core.project")
        cls.stale = _module("core.provenance.stale")

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.unload()

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="gb-t49-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(self.ps.take_notices)
        self.addCleanup(self.ps.close)

    # Ayudas -------------------------------------------------------------------------------

    def create(self) -> object:
        """Un proyecto nuevo (del esquema 2), abierto en escritura y aún fuera de la sesión."""
        settings = self.core.ProjectSettings(**settings_values())
        return self.core.create_project(self.tmp, settings, self.ps.session(),
                                        self.ps.userdata()).project

    def run_checks(self) -> None:
        for _ in range(MAX_TICKS):
            if self.session.check_tick() is None:
                return
        self.fail("la comprobación no termina")

    def bar(self, *, geoblender: bool = True) -> FakeLayout:
        layout = FakeLayout()
        self.statusbar.draw_statusbar(SimpleNamespace(layout=layout),
                                      _ctx(geoblender=geoblender))
        return layout

    def ours(self, *, geoblender: bool = True) -> list[str]:
        """Los textos de los campos de la procedencia en la barra de estado."""
        marks = ("⚠", "!", "Comprobando", "Ctrl+Z")
        return [text for text in self.bar(geoblender=geoblender).texts()
                if text.startswith(marks)]

    def both_modes(self) -> list[str]:
        shown = self.ours(geoblender=True)
        self.assertEqual(self.ours(geoblender=False), shown)  # también en modo Blender
        return shown

    def control_7(self) -> list[object]:
        """Lo que dibuja el control 7 en la barra superior (nivel C)."""
        level = _module("core.catalog.width").Level
        layout = FakeLayout()
        bar = SimpleNamespace(workspace=SimpleNamespace(geoblender_mode=True),
                              screen=SimpleNamespace(show_fullscreen=False),
                              region=SimpleNamespace(width=1920), scene=bpy.context.scene)
        self.quick.draw_project(layout, bar, level.C)
        targets = [item.target for item in layout.items]
        start = targets.index(REFRESH)
        return layout.items[start:start + 2]

    # Pruebas ------------------------------------------------------------------------------

    def test_fields_and_control_7_follow_the_project(self) -> None:
        """RF-008-58, RF-008-16, RF-008-28, RNF-008-06: sin proyecto no hay ningún campo de la
        procedencia ni número en el control 7. Al abrir un proyecto, «Comprobando el
        proyecto… 0 %» con su botón de cancelar, en los dos modos; al terminar la comprobación
        (que registra la entrada «Limites», redibujada por la propiedad), el temporizador de los
        indicadores pone «⚠ 1 entradas» y nada de obsoletos. Cambiar la producción deja
        obsoletos los años por banco: hasta el siguiente tic se ve lo de antes y, con él (≤ 1 s
        con lo que tarda), «! 1 obsoletos» en la barra y «1» tras Refrescar en el control 7, que
        abre el panel de lo obsoleto con «Refrescar · obsoletos (1)», el dato, su módulo, la
        causa y Recalcular; otro tic sin cambios no vuelve a leer el proyecto. Dibujar los
        campos cuesta ≤ 1 ms. Cerrar el proyecto los quita y retira el temporizador."""
        ui = self.ui
        self.assertEqual(self.both_modes(), [])
        refresh, after = self.control_7()
        self.assertEqual(refresh.target, REFRESH)
        self.assertNotEqual(after.target, STALE_PANEL)  # sin número
        self.assertIsNone(self.quick.count_of(REFRESH, bpy.context))

        project = self.create()
        sources = self.tmp / "fuentes"
        sources.mkdir()
        source = sources / "Limites.gpkg"
        shutil.copyfile(DATA / "Limites_v1.gpkg", source)
        demo = self.enterContext(Demo(module_name()).registered())
        demo.import_boundary(project, source)
        demo.digitize(project)
        demo.bench_years(project)
        shutil.copyfile(DATA / "Limites_v2.gpkg", source)
        later = time.time() + 10
        os.utime(source, (later, later))

        self.ps.attach(project)
        self.assertTrue(bpy.app.timers.is_registered(ui.indicator_tick))
        self.assertEqual(self.both_modes(), ["Comprobando el proyecto… 0 %"])
        cancel = [item for item in self.bar().items if item.target == CANCEL_CHECKS]
        self.assertEqual(len(cancel), 1)
        self.assertFalse(cancel[0].enabled)  # su orden real llega con T54
        self.run_checks()
        self.assertEqual(self.both_modes(), [])  # aún sin leer los recuentos

        self.assertEqual(ui.indicator_tick(), ui.INDICATOR_TICK_S)
        self.assertEqual(self.stale.counts(project), self.stale.Counts(0, 0, 1))
        self.assertEqual(self.both_modes(), ["⚠ 1 entradas"])
        inputs = [item for item in self.bar().items if item.text == "⚠ 1 entradas"]
        self.assertEqual(inputs[0].target, SHOW_INPUTS)
        self.assertIsNone(self.quick.count_of(REFRESH, bpy.context))

        store = _module("core.params").ParameterStore(project)
        with project.write_transaction() as conn:
            store.change(conn, PRODUCTION, value=400_000.0, kind="ADOPTADO",
                         source="Plan de labores 2027", source_kind="document",
                         decided_by="la propiedad", reason="Plan revisado")
        self.assertEqual(self.both_modes(), ["⚠ 1 entradas"])  # hasta el siguiente tic
        self.assertLessEqual(ui.INDICATOR_TICK_S, UPDATE_BUDGET_S / 2)
        start = time.perf_counter()
        interval = ui.indicator_tick()
        elapsed = time.perf_counter() - start
        self.assertEqual(interval, ui.INDICATOR_TICK_S)
        self.assertLessEqual(interval + elapsed, UPDATE_BUDGET_S)
        self.assertEqual(self.both_modes(), ["⚠ 1 entradas", "! 1 obsoletos"])
        stale_field = [item for item in self.bar().items if item.text == "! 1 obsoletos"]
        self.assertEqual(stale_field[0].target, STALE_PANEL)
        with mock.patch.object(self.stale, "stale_items") as read:
            self.assertEqual(ui.indicator_tick(), ui.INDICATOR_TICK_S)
        read.assert_not_called()  # sin cambios en el proyecto, no vuelve a leer

        refresh, number = self.control_7()
        self.assertEqual((refresh.target, refresh.text), (REFRESH, ""))
        self.assertEqual((number.kind, number.target, number.text), ("popover", STALE_PANEL,
                                                                      "1"))
        self.assertTrue(number.enabled)
        self.assertEqual(self.quick.count_of(REFRESH, bpy.context), 1)
        panel = draw(bpy.types.GEOBLENDER_PT_core_stale, bpy.context)
        texts = panel.texts()
        self.assertEqual(texts[0], "Refrescar · obsoletos (1)")
        self.assertIn("demo_bench_years", texts)
        self.assertIn("demo", texts)
        causes = [text for text in texts if text.startswith("Obsoleto: cambió")]
        self.assertEqual(len(causes), 1, texts)
        self.assertIn("Producción (demostración)", causes[0])
        recompute = [item for item in panel.items if item.target == RECOMPUTE]
        self.assertEqual([item.text for item in recompute],
                         ["Recalcular", "Recalcular lo obsoleto"])
        self.assertTrue(all(item.enabled for item in recompute))  # su orden real (T53)
        with project.read() as conn:
            (years,) = conn.execute("SELECT uid FROM gb_dataset WHERE name = 'demo_bench_years'"
                                    ).fetchone()
        self.assertEqual([vars(item.properties) for item in recompute],
                         [{"scope": "ITEM", "subject_uid": years}, {}])

        fields = [field for field in self.statusbar.fields() if field.key in FIELD_KEYS]
        ctx = _ctx(geoblender=True)
        layout = FakeLayout()
        start = time.perf_counter()
        for _ in range(DRAWS):
            for field in fields:
                if field.width_px(ctx) > 0:
                    field.draw(layout, ctx)
        self.assertLessEqual((time.perf_counter() - start) / DRAWS, DRAW_BUDGET_S)

        self.ps.close()
        self.assertEqual(self.both_modes(), [])
        self.assertFalse(bpy.app.timers.is_registered(ui.indicator_tick))
        self.assertEqual(len(bpy.context.window_manager.geoblender_provenance.stale), 0)
        self.assertIsNone(self.quick.count_of(REFRESH, bpy.context))

    def test_undo_notice_for_ten_seconds(self) -> None:
        """RF-008-32 (plan §5.5): el aviso de Ctrl+Z se ve en la barra de estado, en los dos
        modos, durante 10 s; después, el campo desaparece."""
        ui = self.ui
        now = time.monotonic()
        with mock.patch.object(ui, "_clock", return_value=now):
            ui.show_undo_notice(UNDO_TEXT)
            self.assertEqual(self.both_modes(), [UNDO_TEXT])
            self.assertTrue(bpy.app.timers.is_registered(ui.expire_undo_notice))
        with mock.patch.object(ui, "_clock", return_value=now + ui.UNDO_NOTICE_S - 0.1):
            self.assertEqual(self.both_modes(), [UNDO_TEXT])
        with mock.patch.object(ui, "_clock", return_value=now + ui.UNDO_NOTICE_S):
            self.assertEqual(self.both_modes(), [])
            self.assertIsNone(ui.expire_undo_notice())
        self.assertEqual(ui.undo_notice(), "")

    def test_disabling_removes_everything(self) -> None:
        """RF-008-16, RF-008-28 (principio 8): habilitar registra el panel de lo obsoleto (real,
        disponible), los campos y el número del control 7; desactivar Geoblender los quita,
        con la escucha del proyecto y los temporizadores de los indicadores y del aviso."""
        ui = self.ui
        commands = _module("bl.ui.commands")
        self.assertTrue(commands.is_available(STALE_PANEL))
        self.assertFalse(commands.is_provisional(commands.registered_class(STALE_PANEL)))
        keys = {field.key for field in self.statusbar.fields()}
        self.assertLessEqual(set(FIELD_KEYS), keys)
        self.assertIsNotNone(self.quick.count_provider(REFRESH))
        self.assertIn(ui.on_project_changed, self.ps.listeners())
        self.ps.attach(self.create())
        ui.show_undo_notice(UNDO_TEXT)
        self.assertTrue(bpy.app.timers.is_registered(ui.indicator_tick))
        self.addCleanup(blender_ext.enable)
        panel = bpy.types.GEOBLENDER_PT_core_stale
        blender_ext.disable()
        self.assertFalse(panel.is_registered)
        self.assertFalse({field.key for field in self.statusbar.fields()} & set(FIELD_KEYS))
        self.assertIsNone(self.quick.count_provider(REFRESH))
        self.assertNotIn(ui.on_project_changed, self.ps.listeners())
        self.assertFalse(bpy.app.timers.is_registered(ui.indicator_tick))
        self.assertFalse(bpy.app.timers.is_registered(ui.expire_undo_notice))
        self.assertEqual(ui.undo_notice(), "")

    # Parámetros del proyecto (T50) ------------------------------------------------------------

    def parameters_project(self) -> tuple[object, object, object]:
        """Un proyecto de la sesión con cuatro parámetros por defecto, «sin confirmar»: la
        producción y K de la demostración (con el balance, que calcula K = 1,11 frente al 1,15
        por defecto), el límite de los originales de ``core`` y ``demo.recovery`` (de prueba,
        en fracción). Devuelve el proyecto, su almacén de parámetros y el balance."""
        project = self.create()
        demo = self.enterContext(Demo(module_name()).registered())
        params = _module("core.params")
        # Se quita con la demostración (todas las definiciones «demo»).
        params.register_definitions([params.ParamDef(
            RECOVERY, "float", "-", 0.9, 0.0, 1.0, ("RF-008-03",),
            "Prueba: recuperación del plan", kind="HIPÓTESIS", source_kind="document")])
        demo.digitize(project)
        demo.bench_years(project)
        balance = demo.balance(project)
        store = params.ParameterStore(project)
        with project.write_transaction() as conn:
            for key in (COPY_LIMIT, RECOVERY):
                store.ensure_default(conn, key, geoblender_version="0.1.0")
        self.ps.attach(project)
        return project, store, balance

    def show_parameters(self) -> object:
        """Proyecto ▸ Control ▸ Parámetros del proyecto (``wm.call_panel`` sustituido): la vista
        de ``WindowManager`` con sus filas."""
        window = bpy.context.window_manager.windows[0]
        with mock.patch.object(self.session, "_call_panel", return_value={"FINISHED"}) as call:
            with bpy.context.temp_override(window=window):
                self.assertEqual(bpy.ops.geoblender.core_show_parameters(), {"FINISHED"})
        call.assert_called_once_with(PARAMETERS_PANEL)
        return bpy.context.window_manager.geoblender_provenance

    @staticmethod
    def keys(view: object) -> list[str]:
        return [row.key for row in view.parameters]

    @staticmethod
    def select(view: object, key: str) -> object:
        view.parameter_index = [row.key for row in view.parameters].index(key)
        return view.parameters[view.parameter_index]

    @staticmethod
    def list_items(view: object) -> FakeLayout:
        """Lo que dibuja la lista de parámetros, fila a fila."""
        layout = FakeLayout()
        for index, row in enumerate(view.parameters):
            bpy.types.GEOBLENDER_UL_core_parameters.draw_item(
                SimpleNamespace(), bpy.context, layout, view, row, 0, view, "parameter_index",
                index)
        return layout

    def rejected(self, **values: object) -> str:
        """El texto con que Cambiar rechaza ``values`` (un error: ``bpy.ops`` lo lanza)."""
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.core_set_parameter(**values)
        return str(caught.exception)

    def test_parameters_panel_lists_filters_and_confirms(self) -> None:
        """RF-008-06, RF-008-02, RF-008-59: Parámetros del proyecto lista cada parámetro con su
        valor y su unidad, su insignia ([HIP] en ámbar), «sin confirmar», su origen, su
        decisor y su fecha; Confirmar quita la marca con una fila más en el historial (y sin
        nada que confirmar, lo dice); los filtros por marca, tipo y módulo se combinan; el
        seleccionado enseña su historial, su aviso de divergencia con «Usar el valor
        calculado…», Cambiar y Confirmar. En solo lectura la lista se consulta, pero Cambiar,
        Confirmar y «Usar el valor calculado…» están desactivados con el motivo."""
        project, store, balance = self.parameters_project()
        view = self.show_parameters()
        self.assertEqual(self.keys(view), KEYS)
        swell = self.select(view, SWELL_FACTOR)
        self.assertEqual((swell.value, swell.kind, swell.unconfirmed, swell.review),
                         ("1,15", "HIPÓTESIS", True, False))
        self.assertTrue(swell.source.startswith("valor por defecto de Geoblender "),
                        swell.source)
        self.assertEqual(swell.decided_by, "Geoblender (valor por defecto)")
        self.assertRegex(swell.decided_at, r"^\d\d/\d\d/\d{4}$")
        self.assertEqual(view.parameters[0].value, "200 MB")
        items = self.list_items(view)
        badges = [item for item in items.items if item.text in ("[HIP]", "[ADO]")]
        self.assertEqual([(item.text, item.alert) for item in badges],
                         [("[ADO]", False), ("[HIP]", True), ("[HIP]", True), ("[HIP]", True)])
        texts = items.texts()
        for shown in ("1,15", "500000 t/año", "sin confirmar", swell.source, swell.decided_by,
                      swell.decided_at):
            self.assertIn(shown, texts)

        self.assertEqual(bpy.ops.geoblender.core_confirm_parameter(key=PRODUCTION),
                         {"FINISHED"})
        record = store.get(PRODUCTION)
        self.assertEqual((record.unconfirmed, record.kind, record.value), (False, "HIPÓTESIS",
                                                                            500_000.0))
        self.assertEqual([entry.action for entry in store.history(PRODUCTION)],
                         ["default", "confirm"])
        production = self.select(view, PRODUCTION)
        self.assertFalse(production.unconfirmed)
        self.assertEqual([(row.rev, row.action, row.kind, row.unconfirmed)
                          for row in view.parameter_history],
                         [(1, "default", "HIPÓTESIS", True), (2, "confirm", "HIPÓTESIS", False)])
        self.assertIn("no está «sin confirmar» ni «revisar»",
                      self.rejected_confirm(PRODUCTION))

        view.filter_mark = "UNCONFIRMED"
        self.assertEqual(self.keys(view), [COPY_LIMIT, RECOVERY, SWELL_FACTOR])
        view.filter_kind = "HIPOTESIS"
        self.assertEqual(self.keys(view), [RECOVERY, SWELL_FACTOR])
        view.filter_mark = "ALL"
        self.assertEqual(self.keys(view), [PRODUCTION, RECOVERY, SWELL_FACTOR])
        view.filter_kind = "ALL"
        view.filter_module = "core"
        self.assertEqual(self.keys(view), [COPY_LIMIT])
        view.filter_module = "ALL"
        self.assertEqual(self.keys(view), KEYS)

        swell = self.select(view, SWELL_FACTOR)
        self.assertEqual([(row.rev, row.action, row.value, row.kind)
                          for row in view.parameter_history],
                         [(1, "default", "1,15", "HIPÓTESIS")])
        self.assertTrue(view.parameter_divergence.startswith(
            "La operación «demo.balance» calcula"), view.parameter_divergence)
        self.assertIn("= 1,11; el valor hipotético sin confirmar es 1,15",
                      view.parameter_divergence)
        figure_uid = view.parameter_figure_uid
        with project.read() as conn:
            self.assertEqual(conn.execute("SELECT operation_uid FROM gb_figure WHERE uid = ?",
                                          (figure_uid,)).fetchone()[0], balance.uid)
        panel = draw(bpy.types.GEOBLENDER_PT_core_parameters, bpy.context)
        self.assertEqual([item.target for item in panel.of_kind("template_list")],
                         [PARAMETERS_LIST, HISTORY_LIST])
        self.assertEqual({item.target for item in panel.of_kind("prop")},
                         {"filter_module", "filter_kind", "filter_mark"})
        self.assertIn(view.parameter_divergence, panel.texts())
        commands = {(item.target, item.text): item for item in panel.of_kind("operator")}
        use = commands[(SET_PARAMETER, USE_CALCULATED)]
        self.assertEqual((use.properties.key, use.properties.from_figure_uid),
                         (SWELL_FACTOR, figure_uid))
        change = commands[(SET_PARAMETER, "Cambiar parámetro…")]
        confirm = commands[(CONFIRM_PARAMETER, "Confirmar parámetro")]
        self.assertEqual((change.properties.key, confirm.properties.key),
                         (SWELL_FACTOR, SWELL_FACTOR))
        self.assertTrue(use.enabled and change.enabled and confirm.enabled)

        project.set_read_only(self.core.ReadOnlyCode.REQUESTED, "prueba")
        for operator in (bpy.ops.geoblender.core_set_parameter,
                         bpy.ops.geoblender.core_confirm_parameter):
            with self.subTest(orden=operator.idname()):
                self.assertFalse(operator.poll())
        self.assertTrue(bpy.ops.geoblender.core_show_parameters.poll())
        self.assertEqual(self.keys(self.show_parameters()), KEYS)
        self.select(view, SWELL_FACTOR)
        panel = draw(bpy.types.GEOBLENDER_PT_core_parameters, bpy.context)
        buttons = [item for item in panel.of_kind("operator")
                   if item.target in (SET_PARAMETER, CONFIRM_PARAMETER)]
        self.assertEqual(len(buttons), 3)
        self.assertFalse(any(item.enabled for item in buttons))
        reasons = [text for text in panel.texts() if text.startswith(READ_ONLY)]
        self.assertEqual(len(reasons), 1, panel.texts())
        self.assertIn("prueba", reasons[0])
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.core_confirm_parameter(key=SWELL_FACTOR)
        self.assertIn(READ_ONLY, str(caught.exception))
        self.assertTrue(store.get(SWELL_FACTOR).unconfirmed)

    def rejected_confirm(self, key: str) -> str:
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.core_confirm_parameter(key=key)
        return str(caught.exception)

    def test_change_rejects_converts_and_adopts_the_figure(self) -> None:
        """RF-008-02, RF-008-03, RF-008-59: Cambiar rechaza sin guardar nada un cambio sin
        motivo, un valor fuera de rango, NaN o vacío y un CALCULADO a mano, con los textos de
        la spec §8; «35 %» en un parámetro en fracción se guarda y se ve 0,35 y quita «sin
        confirmar». Desde el aviso de divergencia, Cambiar sale relleno con la cifra calculada
        (1,11 [CAL]) y su operación, y nada cambia hasta que la persona lo acepta; entonces K
        es CALCULADO con la operación del balance, el aviso desaparece y la HIPÓTESIS anterior
        sigue en el historial. Ninguna propiedad de Cambiar ni de Confirmar es flotante."""
        project, store, balance = self.parameters_project()
        view = self.show_parameters()
        for values, expected in (
            ({"value": "1,23", **PROPERTY},
             "Indique el motivo del cambio de «demo.swell_factor» (1,15 → 1,23, HIPÓTESIS → "
             "ADOPTADO"),
            ({"value": "3,5", **PROPERTY, "reason": "Acta"},
             "Parámetro «demo.swell_factor»: 3,5 está fuera de su rango [1; 2]."),
            ({"value": "NaN", **PROPERTY, "reason": "Acta"},
             "Parámetro «demo.swell_factor»: «NaN» no es un número."),
            ({"value": "", **PROPERTY, "reason": "Acta"},
             "demo.swell_factor: falta el valor; este parámetro no admite «sin valor»."),
            ({"value": "1,23", **PROPERTY, "kind": "CALCULADO", "reason": "Acta"},
             "demo.swell_factor: un parámetro CALCULADO lo escribe una operación; para fijarlo "
             "a mano, elija ADOPTADO o HIPÓTESIS."),
        ):
            with self.subTest(valor=values["value"], tipo=values["kind"]):
                self.assertIn(expected, self.rejected(key=SWELL_FACTOR, **values))
        self.assertEqual(store.get(SWELL_FACTOR).rev, 1)

        self.assertEqual(bpy.ops.geoblender.core_set_parameter(
            key=RECOVERY, value="35 %", reason="Ensayo de recuperación 2026", **PROPERTY),
            {"FINISHED"})
        recovery = store.get(RECOVERY)
        self.assertEqual((recovery.value, recovery.unit, recovery.kind, recovery.unconfirmed,
                          recovery.decided_by), (0.35, "-", "ADOPTADO", False, "la propiedad"))
        self.assertTrue(recovery.decided_at.startswith("2026-09-24T"), recovery.decided_at)
        row = self.select(view, RECOVERY)
        self.assertEqual((row.value, row.kind, row.unconfirmed), ("0,35", "ADOPTADO", False))
        self.assertEqual([(entry.value, entry.kind) for entry in view.parameter_history],
                         [("0,9", "HIPÓTESIS"), ("0,35", "ADOPTADO")])

        self.select(view, SWELL_FACTOR)
        figure_uid = view.parameter_figure_uid
        cls = _module("bl.ui.commands").registered_class(SET_PARAMETER)
        dialog = mock.Mock(return_value={"RUNNING_MODAL"})
        launched = SimpleNamespace(key=SWELL_FACTOR, from_figure_uid=figure_uid, value="",
                                   unit="", kind="ADOPTADO", source="", source_kind="PERSON",
                                   decided_by="", decided_at="", reason="",
                                   report=mock.Mock())
        context = SimpleNamespace(window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        self.assertEqual(cls.invoke(launched, context, None), {"RUNNING_MODAL"})
        dialog.assert_called_once()
        self.assertEqual((launched.value, launched.kind, launched.decided_by),
                         ("1,11", "CALCULADO", self.ps.session().user_host))
        self.assertIn("demo.balance", launched._divergence)
        filled = draw(cls, bpy.context, **vars(launched))
        self.assertIn(launched._divergence, filled.texts())
        self.assertNotIn("value", [item.target for item in filled.of_kind("prop")])
        self.assertEqual((store.get(SWELL_FACTOR).rev, store.get(SWELL_FACTOR).value),
                         (1, 1.15))  # hasta que la persona acepta

        self.assertEqual(bpy.ops.geoblender.core_set_parameter(
            key=SWELL_FACTOR, from_figure_uid=figure_uid, value=launched.value,
            kind=launched.kind, decided_by=launched.decided_by,
            reason="Se adopta el K del balance"), {"FINISHED"})
        swell = store.get(SWELL_FACTOR)
        self.assertEqual((swell.value, swell.kind, swell.operation_uid, swell.unconfirmed),
                         (1.11, "CALCULADO", balance.uid, False))
        self.assertEqual(view.parameter_divergence, "")
        self.assertEqual([(row.rev, row.value, row.kind) for row in view.parameter_history],
                         [(1, "1,15", "HIPÓTESIS"), (2, "1,11", "CALCULADO")])

        for idname in (SET_PARAMETER, CONFIRM_PARAMETER):
            group, name = idname.split(".")
            rna = getattr(getattr(bpy.ops, group), name).get_rna_type()
            with self.subTest(orden=idname):
                self.assertEqual([prop.identifier for prop in rna.properties
                                  if prop.type == "FLOAT"], [])


if __name__ == "__main__":
    unittest.main()

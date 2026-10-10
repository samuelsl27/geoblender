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

T55 (Grafo de operaciones y procedencia):

- RF-008-29: ``geoblender.core_show_lineage`` abre ``GEOBLENDER_PT_core_lineage`` con la
  cadena de una cifra o un dato hasta sus entradas (``GEOBLENDER_UL_core_lineage``: filas
  sangradas y plegables por nudo), con los parámetros (valor, unidad, insignia de tipo y «sin
  confirmar»), las versiones del código, quién y cuándo, y los eslabones obsoletos con su
  causa; su búsqueda encuentra las cifras vigentes y los datos por su nombre; también en solo
  lectura.
- RF-008-31: la cifra va con su unidad, su insignia y sus marcas según el estado de hoy de lo
  de aguas arriba; ningún nombre de objeto, de colección ni de fichero del proyecto contiene
  una cifra registrada (``assert_no_figures_in_names``).

T56 (estados de comando, BS §7.3):

- RF-008-61: con una orden sintética de un módulo (``ProvenanceAwareOperator``) que declaran
  las operaciones de la demostración: con una entrada cambiada sin decidir aguas arriba, la
  orden se dibuja activa con la insignia ⚠ y su descripción lleva el aviso de RF-008-10; con
  resultados obsoletos, su descripción lleva «Obsoleto: cambió …» y «Recalcular lo obsoleto»
  se dibuja resaltado en Proyecto ▸ Control y en el contextual; sin nada, todo se dibuja como
  antes. Desregistrar quita el proveedor de estado.

T66 (spec 0.3; F-1 de la verificación):

- RF-008-28, RF-008-61: una operación obsoleta que solo deja cifras (el área del límite tras
  actualizar su entrada) cuenta en «! n obsoletos» y en el control 7, sale en el panel con su
  causa y Recalcular, y su orden lleva la causa en su descripción con «Recalcular lo obsoleto»
  resaltado; tras recalcular, nada.

T70 (T58, M1: [HIP] salía en rojo, el color de alerta de Blender, que la interfaz deja para los
errores y los cambios):

- RF-008-02, RF-008-06, RF-008-29: la lista de parámetros, su historial y la procedencia
  dibujan [HIP] con el icono ámbar propio ``gb_type_assumption`` (conjunto de la 003) junto a
  la insignia y sin alerta; sin interfaz, su reserva nativa ámbar; los demás tipos, sin alerta
  y con un hueco del ancho del icono (el texto queda alineado). La columna cabe con el icono en
  los dos idiomas, y el icono pasa las reglas de iconos de la 003 (licencia y tamaños).

T71 (textos de T58):

- RF-008-16, RF-008-28: «⚠ 1 entrada» y «! 1 obsoleto» en singular (0, 1 y n, en español y en
  inglés); RF-008-06, RF-008-16, RF-008-29: las propiedades de la vista con nombre y descripción
  del catálogo; RF-008-06: el motivo de solo lectura, sin repetir «Solo lectura:»; los valores
  de los parámetros con el separador de miles de las cifras («500 000 t/año»).

Se ejecuta con ``tools/run_blender_tests.py``. En ``blender -b`` los temporizadores no corren:
las pruebas llaman a su función. El proyecto es sintético (la demostración de la 008 y los
GeoPackage de ``tests/data/core/provenance/``).
"""

import dataclasses
import importlib
import json
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
from tests.support.provenance_checks import assert_no_figures_in_names
from tests.support.provenance_demo import AREA, BENCH_YEARS, PRODUCTION, SWELL_FACTOR, Demo
from tests.support.repo import EXTENSION_DIR, ROOT, tools_on_path

tools_on_path()

from gbtools import icons as icon_rules  # noqa: E402

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
LINEAGE_PANEL = "GEOBLENDER_PT_core_lineage"
LINEAGE_LIST = "GEOBLENDER_UL_core_lineage"
SHOW_LINEAGE = "geoblender.core_show_lineage"
YEARS_B1 = "Años del banco (demostración) · B-1 = 2,5 año"
YEARS_OP = "Años por banco (demostración) · demo.bench_years 1.0 · Geoblender "
THIN = "\u202f"  # separador de miles de las cifras en español (spec 003, II §2.4; T71)
PRODUCTION_ROW = f"Producción (demostración) · demo.production = 500{THIN}000 t/año"
HYPOTHESIS = "depende de una hipótesis"
UNCONFIRMED = "depende de un valor sin confirmar"
STALE_CAUSE = "Obsoleto: cambió Producción (demostración)"
AREA_UPDATE = "La propiedad entrega el límite redibujado"
AREA_LABEL = "Calcular el área del límite (demostración)"  # la operación, en el panel
AREA_CAUSE = "Obsoleto: se actualizó la entrada «Limites»"
SYNTHETIC = "geoblender.core_selftest_state"  # la orden sintética de un módulo (T56)
SYNTHETIC_LABEL = "Synthetic module order"  # sin traducción: se ve el msgid
SYNTHETIC_ABOUT = "Synthetic order of a module"
CHANGED_WARNING = "La entrada «Limites» ha cambiado desde su registro ("
PROJECT_MENU = "GEOBLENDER_MT_ui_project"  # Proyecto ▸ Control ▸ Recalcular lo obsoleto
CONTEXT_MENU = "GEOBLENDER_MT_des_context_design"  # un contextual que la lleva
HYPOTHESIS_ICON = "gb_type_assumption"  # [HIP]: «HIP» sobre ámbar (spec 003, II §1.4)
HYPOTHESIS_FALLBACK = "COLLECTION_COLOR_03"  # su reserva nativa ámbar (la de BORRADOR)
HYPOTHESIS_AMBER = "#E0A526"  # el ámbar de HIP (II §1.2)
FAKE_ICON_ID = 4242  # el icon_id de un icono propio cargado, con interfaz
SVG_DIR = ROOT / "assets" / "icons"
PNG_DIR = EXTENSION_DIR / "resources" / "icons"
MAX_PNG_BYTES = 8 * 1024  # RNF-003-09


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

    def synthetic_command(self) -> type:
        """La orden sintética de un módulo (``ProvenanceAwareOperator`` de ``geoblender.*``),
        registrada y en el catálogo hasta el final de la prueba (T56)."""
        commands = _module("bl.ui.commands")

        class GEOBLENDER_OT_core_selftest_state(self.session.ProvenanceAwareOperator,
                                                bpy.types.Operator):
            bl_idname = SYNTHETIC
            bl_label = SYNTHETIC_LABEL
            bl_description = SYNTHETIC_ABOUT
            provenance_op_type = AREA

            def execute(self, context: object) -> set[str]:
                return {"FINISHED"}

        cat = commands.catalog()
        command = dataclasses.replace(
            cat.commands[RECOMPUTE], key=SYNTHETIC, idname=SYNTHETIC, label=SYNTHETIC_LABEL,
            label_es=SYNTHETIC_LABEL, description=SYNTHETIC_ABOUT,
            description_es=SYNTHETIC_ABOUT, home="", aliases=())
        self.addCleanup(commands.clear)  # el último: la disponibilidad, de nuevo al pedirla
        self.enterContext(mock.patch.dict(cat.commands, {SYNTHETIC: command}))
        bpy.utils.register_class(GEOBLENDER_OT_core_selftest_state)
        self.addCleanup(bpy.utils.unregister_class, GEOBLENDER_OT_core_selftest_state)
        return GEOBLENDER_OT_core_selftest_state

    def declare(self, op_type: str) -> None:
        """La operación ``op_type`` de la demostración declara la orden sintética entre sus
        ``commands`` hasta el final de la prueba (antes de quitar la demostración)."""
        contract = _module("core.provenance.contract")
        original = contract.OPERATIONS[op_type]
        contract.unregister_operation(op_type)
        contract.register_operation(dataclasses.replace(original, commands=(SYNTHETIC,)))

        def restore() -> None:
            contract.unregister_operation(op_type)
            contract.register_operation(original)

        self.addCleanup(restore)

    def synthetic_drawn(self, cls: type) -> tuple[str, bool, bool, str]:
        """Cómo se dibuja la orden sintética (texto, activa y en alerta) y su descripción
        emergente."""
        layout = FakeLayout()
        _module("bl.ui.drawing").draw_command(layout, SYNTHETIC, context=bpy.context)
        (item,) = layout.items
        return item.text, item.enabled, item.alert, cls.description(bpy.context, None)

    @staticmethod
    def recompute_highlighted() -> list[list[bool]]:
        """Si «Recalcular lo obsoleto» está resaltado en Proyecto ▸ Control y en el
        contextual."""
        return [[item.alert for item in draw(getattr(bpy.types, menu), bpy.context).items
                 if item.target == RECOMPUTE] for menu in (PROJECT_MENU, CONTEXT_MENU)]

    # Pruebas ------------------------------------------------------------------------------

    def test_fields_and_control_7_follow_the_project(self) -> None:
        """RF-008-58, RF-008-16, RF-008-28, RNF-008-06: sin proyecto no hay ningún campo de la
        procedencia ni número en el control 7. Al abrir un proyecto, «Comprobando el
        proyecto… 0 %» con su botón de cancelar, en los dos modos; al terminar la comprobación
        (que registra la entrada «Limites», redibujada por la propiedad), el temporizador de los
        indicadores pone «⚠ 1 entrada» y nada de obsoletos. Cambiar la producción deja
        obsoletos los años por banco: hasta el siguiente tic se ve lo de antes y, con él (≤ 1 s
        con lo que tarda), «! 1 obsoleto» en la barra y «1» tras Refrescar en el control 7, que
        abre el panel de lo obsoleto con «Refrescar · obsoletos (1)», el dato, su módulo, la
        causa y Recalcular; otro tic sin cambios no vuelve a leer el proyecto. Dibujar los
        campos cuesta ≤ 1 ms. Cerrar el proyecto los quita y retira el temporizador.

        RF-008-61 (T56), con una orden sintética de un módulo que declaran el área y los años
        por banco: sin nada, se dibuja como antes (su etiqueta, activa, sin alerta y con su
        descripción) y «Recalcular lo obsoleto», sin resaltar; con «Limites» cambiada (de ella
        depende el área), activa con la insignia ⚠ y el aviso de RF-008-10 en su descripción;
        con los años obsoletos, además «Obsoleto: cambió Producción (demostración)» y Recalcular
        lo obsoleto resaltado en Proyecto ▸ Control y en el contextual; al cerrar, como antes."""
        ui = self.ui
        synthetic = self.synthetic_command()
        plain = (SYNTHETIC_LABEL, True, False, SYNTHETIC_ABOUT)
        self.assertEqual(self.synthetic_drawn(synthetic), plain)
        self.assertEqual(self.recompute_highlighted(), [[False], [False]])
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
        self.declare(AREA)
        self.declare(BENCH_YEARS)
        boundary = demo.import_boundary(project, source)
        demo.area(project, boundary.dataset.uid)
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
        self.assertTrue(cancel[0].enabled)  # su orden real (T54)
        self.run_checks()
        self.assertEqual(self.both_modes(), [])  # aún sin leer los recuentos

        self.assertEqual(ui.indicator_tick(), ui.INDICATOR_TICK_S)
        self.assertEqual(self.stale.counts(project),
                         self.stale.Counts(stale=0, figures=0, review=0, inputs_changed=1))
        self.assertEqual(self.both_modes(), ["⚠ 1 entrada"])
        inputs = [item for item in self.bar().items if item.text == "⚠ 1 entrada"]
        self.assertEqual(inputs[0].target, SHOW_INPUTS)
        self.assertIsNone(self.quick.count_of(REFRESH, bpy.context))
        shown, enabled, alert, about = self.synthetic_drawn(synthetic)
        self.assertEqual((shown, enabled, alert), (f"⚠ {SYNTHETIC_LABEL}", True, False))
        first, warning = about.split("\n")
        self.assertEqual(first, SYNTHETIC_ABOUT)
        self.assertTrue(warning.startswith(CHANGED_WARNING), warning)
        self.assertTrue(warning.endswith("Dependen de ella: 1 dato, 1 operación y 1 cifra."),
                        warning)
        self.assertEqual(self.recompute_highlighted(), [[False], [False]])

        store = _module("core.params").ParameterStore(project)
        with project.write_transaction() as conn:
            store.change(conn, PRODUCTION, value=400_000.0, kind="ADOPTADO",
                         source="Plan de labores 2027", source_kind="document",
                         decided_by="la propiedad", reason="Plan revisado")
        self.assertEqual(self.both_modes(), ["⚠ 1 entrada"])  # hasta el siguiente tic
        self.assertLessEqual(ui.INDICATOR_TICK_S, UPDATE_BUDGET_S / 2)
        start = time.perf_counter()
        interval = ui.indicator_tick()
        elapsed = time.perf_counter() - start
        self.assertEqual(interval, ui.INDICATOR_TICK_S)
        self.assertLessEqual(interval + elapsed, UPDATE_BUDGET_S)
        self.assertEqual(self.both_modes(), ["⚠ 1 entrada", "! 1 obsoleto"])
        stale_field = [item for item in self.bar().items if item.text == "! 1 obsoleto"]
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
        shown, enabled, alert, about = self.synthetic_drawn(synthetic)
        self.assertEqual((shown, enabled, alert), (f"⚠ {SYNTHETIC_LABEL}", True, False))
        self.assertEqual(about.split("\n")[2:], [STALE_CAUSE])
        self.assertEqual(self.recompute_highlighted(), [[True], [True]])

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
        self.assertEqual(self.synthetic_drawn(synthetic), plain)
        self.assertEqual(self.recompute_highlighted(), [[False], [False]])

    def test_stale_area_that_only_leaves_a_figure(self) -> None:
        """RF-008-28, RF-008-61 (spec 0.3, T66; F-1 de la verificación): importado el límite
        y calculada su área (que solo deja la cifra), con ``Limites_v2`` en su lugar y la
        entrada actualizada, «! 1 obsoleto» en la barra (los dos modos) y «1» en el control 7,
        que abre el panel con la operación del área, su módulo, su causa («Obsoleto: se
        actualizó la entrada «Limites»») y Recalcular de esa operación; la orden sintética que
        declara el área lleva la causa en su descripción («Resultado obsoleto», sin la
        insignia ⚠) y «Recalcular lo obsoleto» sale resaltado. Tras recalcular, el siguiente
        tic lo quita todo: ningún campo, ningún número, «No hay nada obsoleto» y la orden como
        antes."""
        ui = self.ui
        synthetic = self.synthetic_command()
        plain = (SYNTHETIC_LABEL, True, False, SYNTHETIC_ABOUT)
        project = self.create()
        sources = self.tmp / "fuentes"
        sources.mkdir()
        source = sources / "Limites.gpkg"
        shutil.copyfile(DATA / "Limites_v1.gpkg", source)
        demo = self.enterContext(Demo(module_name()).registered())
        self.declare(AREA)
        boundary = demo.import_boundary(project, source)
        area = demo.area(project, boundary.dataset.uid)
        shutil.copyfile(DATA / "Limites_v2.gpkg", source)
        _module("core.provenance.importer").reimport_input(project, "Limites", AREA_UPDATE)

        self.ps.attach(project)
        self.run_checks()
        self.assertEqual(ui.indicator_tick(), ui.INDICATOR_TICK_S)
        self.assertEqual(self.both_modes(), ["! 1 obsoleto"])
        _refresh, number = self.control_7()
        self.assertEqual((number.kind, number.target, number.text), ("popover", STALE_PANEL,
                                                                      "1"))
        panel = draw(bpy.types.GEOBLENDER_PT_core_stale, bpy.context)
        texts = panel.texts()
        self.assertEqual(texts[0], "Refrescar · obsoletos (1)")
        self.assertIn(AREA_LABEL, texts)
        self.assertIn("demo", texts)
        self.assertIn(AREA_CAUSE, texts)
        self.assertNotIn("No hay nada obsoleto", texts)
        recompute = [item for item in panel.items if item.target == RECOMPUTE]
        self.assertEqual([item.text for item in recompute],
                         ["Recalcular", "Recalcular lo obsoleto"])
        self.assertEqual([vars(item.properties) for item in recompute],
                         [{"scope": "ITEM", "subject_uid": area.uid}, {}])
        self.assertEqual(self.synthetic_drawn(synthetic),
                         (SYNTHETIC_LABEL, True, False, f"{SYNTHETIC_ABOUT}\n{AREA_CAUSE}"))
        self.assertEqual(self.recompute_highlighted(), [[True], [True]])

        for _progress in _module("core.provenance.recompute").recompute_steps(project):
            pass
        self.assertEqual(ui.indicator_tick(), ui.INDICATOR_TICK_S)
        self.assertEqual(self.both_modes(), [])
        self.assertIsNone(self.quick.count_of(REFRESH, bpy.context))
        texts = draw(bpy.types.GEOBLENDER_PT_core_stale, bpy.context).texts()
        self.assertEqual(texts[:2], ["Refrescar · obsoletos (0)", "No hay nada obsoleto"])
        self.assertEqual(self.synthetic_drawn(synthetic), plain)
        self.assertEqual(self.recompute_highlighted(), [[False], [False]])

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
        """RF-008-16, RF-008-28, RF-008-61 (principio 8): habilitar registra el panel de lo
        obsoleto (real, disponible), los campos, el número del control 7 y el proveedor de
        estado de las órdenes; desactivar Geoblender los quita, con la escucha del proyecto y
        los temporizadores de los indicadores y del aviso."""
        ui = self.ui
        commands = _module("bl.ui.commands")
        self.assertIs(commands.state_provider(), ui.command_state)
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
        self.assertIsNone(commands.state_provider())
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
        Confirmar y «Usar el valor calculado…» están desactivados con el motivo, que no repite
        «Solo lectura:». T71: cada valor, con el separador de miles de las cifras en los dos
        idiomas («500 000 t/año»; «500,000 t/año»)."""
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
        amber = ("[HIP]", False, HYPOTHESIS_FALLBACK)  # sin interfaz, su reserva (T70)
        self.assertEqual([(item.text, item.alert, item.icon) for item in badges],
                         [("[ADO]", False, "BLANK1"), amber, amber, amber])
        texts = items.texts()
        for shown in ("1,15", f"500{THIN}000 t/año", "sin confirmar", swell.source,
                      swell.decided_by, swell.decided_at):
            self.assertIn(shown, texts)
        i18n = _module("core.i18n")
        self.addCleanup(i18n.set_language, i18n.language())
        i18n.set_language("en")  # T71: como las cifras, también en inglés
        self.assertEqual([row.value for row in self.show_parameters().parameters],
                         ["200 MB", "500,000 t/año", "0.9", "1.15"])
        i18n.set_language("es")
        self.assertEqual([row.value for row in self.show_parameters().parameters],
                         ["200 MB", f"500{THIN}000 t/año", "0,9", "1,15"])

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
        self.assertEqual(reasons, [f"{READ_ONLY} prueba"])  # sin repetir «Solo lectura:» (T71)
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.core_confirm_parameter(key=SWELL_FACTOR)
        self.assertIn(f"{READ_ONLY} prueba", str(caught.exception))
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

    # Grafo de operaciones y procedencia (T55) -------------------------------------------------

    def show_lineage(self, **props: object) -> object:
        """Proyecto ▸ Control ▸ Procedencia y registro ▸ Grafo de operaciones y procedencia
        (``wm.call_panel`` sustituido): la vista de ``WindowManager`` con sus filas."""
        window = bpy.context.window_manager.windows[0]
        with mock.patch.object(self.session, "_call_panel", return_value={"FINISHED"}) as call:
            with bpy.context.temp_override(window=window):
                self.assertEqual(bpy.ops.geoblender.core_show_lineage(**props), {"FINISHED"})
        call.assert_called_once_with(LINEAGE_PANEL)
        return bpy.context.window_manager.geoblender_provenance

    @staticmethod
    def lineage_rows(view: object) -> list[tuple[int, str, list[str]]]:
        """Lo que dibuja la lista de la procedencia: profundidad, clase y textos de cada fila."""
        found = []
        for index, row in enumerate(view.lineage):
            layout = FakeLayout()
            bpy.types.GEOBLENDER_UL_core_lineage.draw_item(
                SimpleNamespace(), bpy.context, layout, view, row, 0, view, "lineage_index",
                index)
            found.append((row.depth, row.kind, [text for text in layout.texts() if text]))
        return found

    def test_lineage_of_a_figure_with_badges_and_marks(self) -> None:
        """RF-008-29, RF-008-31 (M3): con la cadena de la demostración, la procedencia de los
        años de B-1 enseña la cifra con su valor, su unidad, su insignia [CAL] y las marcas
        «depende de una hipótesis» y «depende de un valor sin confirmar»; debajo, los años por
        banco con la versión de su algoritmo y de Geoblender, quién y cuándo; la producción
        que leyó (500 000 t/año [HIP] «sin confirmar»), los bancos y su digitalización. La del
        área llega hasta su entrada («Limites: vigente»). Cambiada la producción (ADOPTADO),
        la cifra solo está «obsoleta», su eslabón dice la causa en alerta y la producción
        leída, lo de hoy. Cada nudo se pliega; la búsqueda encuentra las cifras vigentes por su
        nombre; lo que no está en el proyecto, desde un guion, es un error. En solo lectura se
        consulta igual. Ningún nombre de objeto, de colección ni de fichero del proyecto
        contiene una cifra registrada."""
        project = self.create()
        sources = self.tmp / "fuentes"
        sources.mkdir()
        source = sources / "Limites.gpkg"
        shutil.copyfile(DATA / "Limites_v1.gpkg", source)
        demo = self.enterContext(Demo(module_name()).registered())
        boundary = demo.import_boundary(project, source)
        area = demo.area(project, boundary.dataset.uid)
        demo.digitize(project)
        years = demo.bench_years(project)
        self.ps.attach(project)
        (b1, *_others), _warnings = demo.figures(project, years.uid)
        self.assertEqual(dict(b1.scope), {"bench": "B-1"})

        view = self.show_lineage(item_uid=b1.uid)
        rows = self.lineage_rows(view)
        self.assertEqual([(depth, kind) for depth, kind, _texts in rows], [
            (0, "figure"), (1, "operation"), (2, "parameter"), (2, "dataset"),
            (3, "operation")])
        figure, operation, parameter, benches, digitize = (texts for *_r, texts in rows)
        self.assertEqual(figure, ["[CAL]", YEARS_B1, HYPOTHESIS, UNCONFIRMED])
        self.assertTrue(operation[0].startswith(YEARS_OP), operation)
        self.assertIn(self.ps.session().user_host, operation[0])
        self.assertEqual(parameter, ["[HIP]", PRODUCTION_ROW, "sin confirmar"])
        self.assertEqual(benches, ["demo_benches (benches)"])
        self.assertIn("demo.digitize 1.0", digitize[0])
        self.assertEqual(view.lineage_uid, b1.uid)
        panel = draw(bpy.types.GEOBLENDER_PT_core_lineage, bpy.context)
        self.assertEqual([item.target for item in panel.of_kind("template_list")],
                         [LINEAGE_LIST])
        self.assertEqual([item.target for item in panel.of_kind("prop")], ["lineage_uid"])
        badge = [item for item in self.list_lineage(view).items if item.text == "[HIP]"]
        self.assertEqual((badge[0].alert, badge[0].icon), (False, HYPOTHESIS_FALLBACK))  # T70

        view.lineage[1].expanded = False  # plegar los años por banco
        self.assertEqual(self.ui.lineage_visible(view.lineage), [True, True, False, False,
                                                                 False])
        shown = bpy.types.UIList.bl_rna.properties["bitflag_filter_item"].default
        flags, order = bpy.types.GEOBLENDER_UL_core_lineage.filter_items(
            SimpleNamespace(bitflag_filter_item=shown), bpy.context, view, "lineage")
        self.assertEqual(flags, [shown, shown, 0, 0, 0])
        self.assertEqual(order, [])

        texts = [texts for *_r, texts in self.lineage_rows(self.show_lineage(item_uid=area.uid))]
        self.assertIn(["Limites: vigente"], texts)

        view.lineage_uid = "años del banco"  # la búsqueda
        self.assertEqual(len(view.lineage), 0)
        self.assertEqual([match.text for match in view.lineage_matches][:1], [YEARS_B1])
        panel = draw(bpy.types.GEOBLENDER_PT_core_lineage, bpy.context)
        found = [item for item in panel.of_kind("operator") if item.target == SHOW_LINEAGE]
        self.assertEqual(len(found), 3)
        self.assertEqual((found[0].text, found[0].properties.item_uid), (YEARS_B1, b1.uid))
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.core_show_lineage(item_uid="nada")  # desde un guion
        self.assertIn("«nada» no es un dato, una cifra ni una operación", str(caught.exception))

        with project.write_transaction() as conn:
            _module("core.params").ParameterStore(project).change(
                conn, PRODUCTION, value=400_000.0, kind="ADOPTADO", source="Plan de labores",
                source_kind="document", decided_by="la propiedad", reason="Plan revisado")
        project.set_read_only(self.core.ReadOnlyCode.REQUESTED, "prueba")
        self.assertTrue(bpy.ops.geoblender.core_show_lineage.poll())
        rows = self.lineage_rows(self.show_lineage(item_uid=b1.uid))
        figure, operation, parameter = (texts for *_r, texts in rows[:3])
        self.assertEqual(figure, ["[CAL]", YEARS_B1, "obsoleta"])
        self.assertEqual(operation[1:], [STALE_CAUSE])
        self.assertEqual(parameter, ["[HIP]", PRODUCTION_ROW, "sin confirmar",
                                     f"hoy: 400{THIN}000 t/año [ADO]"])
        cause = [item for item in self.list_lineage(view).items if item.text == STALE_CAUSE]
        self.assertTrue(cause[0].alert)

        with project.read() as conn:
            values = [value for (value,) in conn.execute("SELECT value FROM gb_figure")]
        self.assertEqual(len(values), 4)  # el área y los años de los tres bancos
        names = [*(item.name for item in bpy.data.objects),
                 *(item.name for item in bpy.data.collections),
                 *(path.relative_to(project.root).as_posix()
                   for path in project.root.rglob("*"))]
        self.assertIn("project.gpkg", names)
        assert_no_figures_in_names(names, values)

    def list_lineage(self, view: object) -> FakeLayout:
        """Lo que dibuja la lista de la procedencia, todo en un mismo *layout*."""
        layout = FakeLayout()
        for index, row in enumerate(view.lineage):
            bpy.types.GEOBLENDER_UL_core_lineage.draw_item(
                SimpleNamespace(), bpy.context, layout, view, row, 0, view, "lineage_index",
                index)
        return layout

    @staticmethod
    def badge_rows(kind: str) -> tuple[tuple[str, object, object], ...]:
        """Una fila de tipo ``kind`` de cada una de las tres listas con insignia (T70): el
        ``bl_idname`` de su ``UIList``, sus datos y la fila."""
        parameter = SimpleNamespace(key="demo.k", value="1,15", kind=kind, unconfirmed=True,
                                    review=False, source="Plan de labores",
                                    decided_by="la propiedad", decided_at="10/10/2026")
        history = SimpleNamespace(rev=1, action="default", value="1,15", kind=kind,
                                  unconfirmed=True, decided_by="la propiedad",
                                  decided_at="10/10/2026", reason="", changed_by="técnico",
                                  changed_at="10/10/2026 10:00")
        lineage = SimpleNamespace(depth=1, expanded=True, param_kind=kind, text="K = 1,15",
                                  repeated=False, marks="", kind="parameter", note="")
        return ((PARAMETERS_LIST, SimpleNamespace(), parameter),
                (HISTORY_LIST, SimpleNamespace(), history),
                (LINEAGE_LIST, SimpleNamespace(lineage=[lineage]), lineage))

    def drawn_badges(self, kind: str) -> list[object]:
        """La insignia de tipo ``kind`` como la dibuja cada una de las tres listas."""
        found = []
        for name, data, row in self.badge_rows(kind):
            layout = FakeLayout()
            getattr(bpy.types, name).draw_item(SimpleNamespace(), bpy.context, layout, data,
                                               row, 0, data, "index", 0)
            shown = [item for item in layout.items if item.text == self.ui.badge(kind)]
            self.assertEqual(len(shown), 1, (name, layout.texts()))
            found.append(shown[0])
        return found

    def test_hypothesis_badge_with_its_amber_icon_and_no_alert(self) -> None:
        """RF-008-02, RF-008-06, RF-008-29 (T70; T58, M1): la lista de parámetros, su
        historial y la procedencia dibujan [HIP] con el icono ámbar propio
        ``gb_type_assumption`` (con interfaz, su ``icon_value``) junto a la insignia y sin
        alerta, que la interfaz deja para los errores y los cambios; sin interfaz, su reserva
        nativa ámbar. [MED], [CAL] y [ADO], sin alerta y con un hueco del ancho del icono
        (``BLANK1``), para que el texto de la columna quede alineado. La columna de la
        insignia cabe con el icono en español y en inglés (el ancho ``blf`` más lo que añade
        el icono, como lo mide la barra de estado). El icono es el de HIP de la 003: está en
        el catálogo, su SVG pasa las reglas (sin texto ni referencias externas, metadatos de
        licencia CC0 de IMGA) con el ámbar de HIP, y sus PNG son de 32 y 64 px, ≤ 8 KB y con
        el sha256 del manifiesto."""
        kinds = list(_module("core.params").ParamKind)
        hypothesis = _module("core.params").ParamKind.HIPOTESIS
        icons = _module("bl.ui.icons")
        i18n = _module("core.i18n")

        loaded = {HYPOTHESIS_ICON: FAKE_ICON_ID}  # con interfaz, el icono propio cargado
        with mock.patch.object(icons, "icon_id", side_effect=lambda name: loaded.get(name, 0)):
            for badge in self.drawn_badges(hypothesis):
                self.assertEqual((badge.text, badge.alert, badge.options.get("icon_value")),
                                 ("[HIP]", False, FAKE_ICON_ID))
        for badge in self.drawn_badges(hypothesis):  # sin interfaz, su reserva nativa
            self.assertEqual((badge.alert, badge.icon), (False, HYPOTHESIS_FALLBACK))
        for kind in kinds:
            if kind == hypothesis:
                continue
            for badge in self.drawn_badges(kind):
                self.assertEqual((badge.alert, badge.icon, badge.options.get("icon_value")),
                                 (False, "BLANK1", None), badge.text)

        for shown in ("es", "en"):
            i18n.set_language(shown)
            try:
                for kind in kinds:
                    for badge in self.drawn_badges(kind):
                        self.assertLessEqual(self.statusbar.label_px(badge.text, icon=True),
                                             self.statusbar.units_px(badge.units_x),
                                             (shown, badge.text))
            finally:
                i18n.set_language("es")

        self.assertIn(HYPOTHESIS_ICON, _module("bl.ui.commands").catalog().icons)
        native = bpy.types.UILayout.bl_rna.functions["label"].parameters["icon"].enum_items
        self.assertIn(HYPOTHESIS_FALLBACK, native.keys())
        svg = SVG_DIR / f"{HYPOTHESIS_ICON}.svg"
        self.assertEqual(icon_rules.svg_problems(svg), [])
        self.assertIn(f'fill="{HYPOTHESIS_AMBER}"', svg.read_text(encoding="utf-8"))
        manifest = json.loads((PNG_DIR / "manifest.json").read_text(encoding="utf-8"))
        entry = manifest["icons"][HYPOTHESIS_ICON]
        self.assertEqual(icon_rules.sha256_file(svg), entry["svg"])
        for size in icon_rules.SIZES:
            png = PNG_DIR / f"{HYPOTHESIS_ICON}_{size}.png"
            self.assertEqual(icon_rules.png_size(png), (size, size))
            self.assertLessEqual(png.stat().st_size, MAX_PNG_BYTES)
            self.assertEqual(icon_rules.sha256_file(png), entry[f"png{size}"])

    # Textos (T71) -----------------------------------------------------------------------------

    def test_texts_in_singular_with_names_and_one_read_only_reason(self) -> None:
        """RF-008-16, RF-008-28 (T71; T58): con 0 no hay campo; con 1, «⚠ 1 entrada» y «! 1
        obsoleto» en la barra de estado de los dos modos; con 3, «⚠ 3 entradas» y «! 3
        obsoletos»; en inglés, «⚠ 1 input», «⚠ 3 inputs», «! 1 stale» y «! 3 stale»;
        plegados, «⚠ n» y «! n» en los dos idiomas. RF-008-06, RF-008-16, RF-008-29: ninguna
        propiedad de ``WindowManager.geoblender_provenance`` queda sin nombre ni descripción
        (la ayuda de una lista o de la búsqueda no enseña ``input_index`` ni
        ``lineage_uid``), ni «Desplegado» de las filas de la procedencia. RF-008-06: el motivo
        de un proyecto del que solo se lee la cabecera no repite «Solo lectura:». RF-008-03:
        Cambiar se rellena con el valor sin separar sus miles, como se teclea en cada idioma."""
        ui = self.ui
        i18n = _module("core.i18n")
        self.addCleanup(i18n.set_language, i18n.language())
        expected = {
            "es": {0: ("", ""), 1: ("⚠ 1 entrada", "! 1 obsoleto"),
                   3: ("⚠ 3 entradas", "! 3 obsoletos")},
            "en": {0: ("", ""), 1: ("⚠ 1 input", "! 1 stale"), 3: ("⚠ 3 inputs", "! 3 stale")},
        }
        for language, by_count in expected.items():
            i18n.set_language(language)
            for n, texts in by_count.items():
                counts = self.stale.Counts(stale=n, figures=0, review=0, inputs_changed=n)
                with self.subTest(idioma=language, n=n), \
                        mock.patch.object(ui._STATE, "counts", counts):
                    self.assertEqual((ui.inputs_text(), ui.stale_text()), texts)
                    self.assertEqual(self.both_modes(), [text for text in texts if text])
                    folded = (f"⚠ {n}", f"! {n}") if n else ("", "")
                    self.assertEqual((ui.inputs_text(folded=True), ui.stale_text(folded=True)),
                                     folded)
        i18n.set_language("es")

        base = set(bpy.types.PropertyGroup.bl_rna.properties.keys())
        view = bpy.context.window_manager.geoblender_provenance.bl_rna.properties
        found = {prop.identifier: (prop.name, prop.description) for prop in view
                 if prop.identifier not in base}
        expanded = view["lineage"].fixed_type.properties["expanded"]
        found["expanded"] = (expanded.name, expanded.description)
        self.assertLessEqual({"parameter_index", "input_index", "lineage_index", "lineage_uid",
                              "stale_index", "history_index"}, set(found))
        for identifier, (name, about) in found.items():
            with self.subTest(propiedad=identifier):
                self.assertTrue(name and about, (name, about))
                self.assertNotIn("_", name)
        self.assertEqual((found["input_index"][0], found["lineage_uid"][0]),
                         ("Entrada seleccionada", "Cifra o dato"))

        status = _module("core.project.session").read_only_status(
            self.core.ReadOnlyCode.REQUESTED, "copia de otro equipo")
        header_only = SimpleNamespace(closed=False, header_only=True, status=status)
        with mock.patch.object(self.session.SESSION, "_project", header_only):
            self.assertEqual(self.session.SESSION.unavailable(),
                             f"{READ_ONLY} copia de otro equipo")

        typed = self.session.typed_value
        self.assertEqual([typed(500_000.0, "es"), typed(500_000.0, "en"),
                          typed((1_000.0, 2_500.5), "es"), typed((1_000.0, 2_500.5), "en")],
                         ["500000", "500000", "[1000; 2500,5]", "[1000, 2500.5]"])


if __name__ == "__main__":
    unittest.main()

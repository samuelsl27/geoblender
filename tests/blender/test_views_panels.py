# SPDX-License-Identifier: GPL-3.0-or-later
"""N ▸ Proyecto ▸ Elemento activo (spec 010, T14; HU-010-3; RF-010-06; plan 010 §5.3.3, §5.5, A6
y D-16).

Con el proyecto sintético de ``tests/support/views_fixtures.py`` (una rejilla, un MDT importado de
un GeoTIFF y una rejilla calculada de él, que lee el parámetro que la deja obsoleta) o con la
cadena de la demostración de la 008 (los años por banco, con sus cifras), abierto en la sesión.
En ``blender -b`` no hay interfaz (``docs/trampas.md`` §3): el panel se dibuja con un *layout*
simulado, y lo que haría ``bpy.msgbus`` al cambiar el objeto activo (en ``-b`` nunca avisa) se
hace llamando a la función que tiene suscrita:

- **la ficha** del objeto activo, leída del proyecto al cambiarlo (``item_card``, sin escribir
  nada): su dato, su tipo, su estado, «al día» (de ``Object.geoblender.view_state``: también «no
  al día: Refrescar (F5)» y «sin respaldo en el proyecto»), versión «—», la operación que
  escribió su contenido con su fecha y su versión de Geoblender, ↑ sus entradas con el hash
  abreviado a 12 caracteres, ↓ sus derivados con «obsoleto» (en alerta) y sus cifras con su unidad
  y su tipo, o «Sin cifras registradas»; y Procedencia (``geoblender.core_show_lineage`` con su
  dato);
- **al cambiar el proyecto**, la siguiente lectura de los indicadores de la procedencia la vuelve
  a leer (el derivado, «obsoleto»); dibujar **no lee el proyecto**; en **solo lectura**, igual;
- **cambiar el objeto activo** cambia la ficha; un objeto del usuario, sin ficha; uno cuyo dato ya
  no está en el proyecto, dicho; **tras cargar otro ``.blend``** la suscripción a
  ``LayerObjects.active`` sigue, porque se renueva en ``load_post``: Blender borra las de
  ``msgbus`` al cargar un fichero (sin renovarla, la suscripción ya no está);
- los textos **caben** en la barra lateral de por defecto con la escala efectiva 1,0 y 1,25 (a
  1920 px); el panel, en la pestaña «Proyecto» tras el panel Proyecto, también tras cambiar el
  idioma;
- **registro y desregistro sin rastro**: el manejador ``load_post``, la suscripción, la escucha
  del proyecto y de los indicadores; desactivada, la huella de Blender como al principio.

N ▸ Proyecto ▸ Inventario (spec 010, T15; HU-010-3; RF-010-07; plan 010 §5.3.3, §5.5, A7 y
D-15), con el mismo proyecto:

- **lo registrado en el proyecto**, cargado o no: entradas y datos, con su tipo, su estado, su
  versión («—»), si está en la escena y sus marcas, por nombre; el filtro de texto (y los de
  tipo, estado y presencia) **no lee el proyecto**: filtra lo ya leído;
- **las órdenes de la fila elegida**: «Cargar en la vista» (``geoblender.core_load_into_view``
  con su dato) lo carga, «Descargar» (``geoblender.core_unload_from_view``) lo quita y
  «Procedencia» abre la de la 008 con ese dato; una entrada no se carga ni tiene procedencia
  (botones desactivados, con el motivo); «en la escena», al día tras cargar y descargar;
- **cuándo se lee**: un cambio en el proyecto deja vieja la lectura, pero no se lee nada hasta
  que el panel se dibuja, que pide un temporizador de un disparo (en ``-b`` no corre: la prueba
  llama a su función); en **solo lectura**, igual; nada escrito en el proyecto;
- **como mucho 500 filas**: 20 100 elementos dan 500 y «… y 19 600 más: afine el filtro»;
- el panel, en el modo Geoblender, y sus textos caben a 1920 px con escala 1,0 y 1,25.

«Cifras de la selección» (control 29; spec 010, T16; RF-010-08; plan 010 §5.3.3, §5.5, A8, D-17
y D-18), con el mismo proyecto y la cadena de la demostración de la 008:

- **la orden real** de la entrada «010», entregada (ni provisional ni «Disponible en R-07»):
  lee del proyecto, con sus marcas, las cifras registradas de los datos de los objetos
  seleccionados (sin repetir) y abre su ventana (``wm.call_panel``: en ``-b`` no hay región
  donde abrirla y se sustituye); **no mide**: con la rejilla, que no tiene cifras, «Sin cifras
  registradas: …» y nada más; con los años por banco, cada cifra con su valor y su unidad, su
  insignia ([CAL]) y sus marcas («depende de una hipótesis»…) y, tras cambiar la producción,
  «obsoleta»; no escribe en el proyecto;
- **las cifras de cada objeto** (``Object.geoblender.figures``, solo para mostrarlas): las de su
  dato al cargarlo y tras cada Refrescar (F5), también en lo que F5 no vuelve a cargar.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import shutil
import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy

from tests.blender.test_dh_import_tabular import assert_fits, at_scales
from tests.support import blender_ext
from tests.support import views_fixtures as vf
from tests.support.blender_ext import fingerprint_diff, module_name
from tests.support.fake_layout import FakeLayout, Item, draw, operator_self
from tests.support.provenance_demo import PRODUCTION, YEARS_TABLE, Demo
from tests.support.repo import ROOT
from tests.support.trees import temp_folder

PANEL = "GEOBLENDER_PT_core_active_item"
PROJECT_PANEL = "GEOBLENDER_PT_core_project"
INVENTORY_PANEL = "GEOBLENDER_PT_core_project_inventory"
INVENTORY_LIST = "GEOBLENDER_UL_core_project_inventory"
SHOW_LINEAGE = "geoblender.core_show_lineage"
LOAD = "geoblender.core_load_into_view"
UNLOAD = "geoblender.core_unload_from_view"
READING = "Leyendo el inventario del proyecto…"
INPUT_NOT_LOADED = "Una entrada no se carga en la vista: se cargan los datos importados de ella"
INPUT_NO_LINEAGE = "Una entrada no tiene procedencia: la tienen los datos importados de ella"
NOT_LOADED = "No está cargado en la escena: no hay nada que descargar"
MANY = 20_100  # los elementos de D-13 (20 000 datos y 100 entradas)
ROWS = 500
DEMO_DATA = ROOT / "tests" / "data" / "core" / "provenance"
MDT = "MDT norte"
DERIVED = "Derivada"
HASH_CHARS = 12
WIDE_PX = 5000.0  # una barra lateral en la que nada se parte (para leer cada línea entera)
NOT_OURS = "El objeto activo no muestra un dato de este proyecto"
GONE = "El proyecto ya no tiene el dato de este objeto"
NO_FIGURES = "Sin cifras registradas"
# Cifras de la selección (T16).
SELECTION_FIGURES = "geoblender.core_show_selection_figures"
SELECTION_PANEL = "GEOBLENDER_PT_core_selection_figures"
SELECTION_TITLE = "Cifras de la selección"
NONE_RECORDED = ("Sin cifras registradas: ninguna operación de estos datos registró cifras (las "
                 "registra, por ejemplo, la cubicación)")
NOTHING_SELECTED = "Ningún objeto seleccionado muestra un dato de este proyecto"
SELECTION_DESCRIPTION = ("Cifras registradas de los datos seleccionados, con su unidad, su tipo y "
                         "sus marcas; no mide")
HYPOTHESIS = "depende de una hipótesis"
STALE_FIGURE = "obsoleta"
DEMO_PREFIX = "demo_"  # el cargador de la prueba para los datos de la demostración
DEMO_LABEL = "Demo bench years"  # su msgid (la demostración pone su español)
FIGURE_PROPS = ("uid", "key", "label", "value_text", "unit", "kind")


class ActiveItemTest(unittest.TestCase):
    """La extensión habilitada una vez; en cada prueba, un proyecto de la vista con una rejilla."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.load_file()
        blender_ext.enable()

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.load_file()
        blender_ext.release()

    def setUp(self) -> None:
        self.panels = vf.extension("bl.ui.view_panels")
        self.labels = vf.extension("bl.ui.labels")
        self.ui = vf.extension("bl.ui.provenance")
        self.ps = vf.extension("bl.scene.project_session")
        i18n = vf.extension("core.i18n")
        self.addCleanup(i18n.set_language, i18n.language())
        i18n.set_language("es")
        self.folder = temp_folder(self, "gb-v010p-")
        self.addCleanup(blender_ext.load_file)
        self.data = vf.ViewsProject(self.folder, grids=1, param_readers=())
        self.addCleanup(self.data.close)
        self.addCleanup(self.ps.close)

    # --- Ayudas -------------------------------------------------------------------------------

    @staticmethod
    def only(uid: str) -> bpy.types.Object:
        (found,) = vf.objects_of(bpy.data, uid)
        return found

    def activate(self, obj: bpy.types.Object | None) -> None:
        """``obj`` activo y lo que hace ``msgbus`` al cambiarlo (en ``-b`` no avisa): la función
        suscrita a ``LayerObjects.active``."""
        bpy.context.view_layer.objects.active = obj
        self.panels.on_active_changed()

    def drawn(self, *, width_px: float = WIDE_PX) -> FakeLayout:
        """El panel dibujado (con ``width_px`` de barra lateral para sus etiquetas)."""
        panel = getattr(bpy.types, PANEL)
        with mock.patch.object(self.labels, "sidebar_width", return_value=width_px):
            return draw(panel, bpy.context)

    def lines(self) -> list[str]:
        """Las etiquetas del panel, una por línea (en una barra en la que nada se parte)."""
        return [item.text for item in self.drawn().of_kind("label")]

    def line(self, start: str) -> Any:
        """La etiqueta del panel que empieza por ``start``."""
        found = [item for item in self.drawn().of_kind("label") if item.text.startswith(start)]
        self.assertEqual(len(found), 1, (start, self.lines()))
        return found[0]

    def lineage_button(self) -> Any:
        (button,) = [item for item in self.drawn().of_kind("operator")
                     if item.target == SHOW_LINEAGE]
        return button

    def operation_of(self, record: Any) -> tuple[str, str, str, str]:
        """El tipo, la versión del algoritmo, cuándo terminó (en hora local, como la ficha) y la
        versión de Geoblender de la operación que escribió ``record``."""
        with self.data.project.read() as conn:
            op_type, op_version, finished, version = conn.execute(
                "SELECT op_type, op_version, finished_at, geoblender_version FROM gb_operation "
                "WHERE uid = ?", (record.operation_uid,)).fetchone()
        moment = vf.extension("core.timeutil").parse_utc(finished).astimezone()
        return op_type, op_version, moment.strftime("%d/%m/%Y %H:%M"), version

    # --- Ayudas del inventario (T15) ----------------------------------------------------------

    @staticmethod
    def view() -> Any:
        """``WindowManager.geoblender_view_panels`` (leída otra vez: docs/trampas.md §4)."""
        name = vf.extension("bl.props.views").WINDOW_MANAGER_PROPERTY
        return getattr(bpy.context.window_manager, name)

    def inventory_drawn(self, *, width_px: float = WIDE_PX) -> FakeLayout:
        """El panel del inventario dibujado (con ``width_px`` de barra lateral)."""
        panel = getattr(bpy.types, INVENTORY_PANEL)
        with mock.patch.object(self.labels, "sidebar_width", return_value=width_px):
            return draw(panel, bpy.context)

    def read_inventory(self) -> None:
        """Lo que hace el temporizador de un disparo que ha pedido el dibujo del panel (en
        ``-b`` no corre): se retira y se llama a su función, que acaba."""
        tick = self.panels.inventory_tick
        self.assertTrue(bpy.app.timers.is_registered(tick), "el dibujo no pidió la lectura")
        bpy.app.timers.unregister(tick)
        self.assertIsNone(tick())

    def shown(self) -> dict[str, tuple[str, bool, bool]]:
        """Las filas del inventario: por nombre, su categoría, si está en la escena y si está
        obsoleto."""
        return {row.name: (row.category, row.in_scene, row.stale)
                for row in self.view().inventory}

    def choose(self, name: str) -> Any:
        """Elige la fila de ``name`` (como un clic en la lista)."""
        view = self.view()
        view.inventory_index = [row.name for row in view.inventory].index(name)
        return view.inventory[view.inventory_index]

    @staticmethod
    def button(layout: FakeLayout, target: str) -> Item:
        (found,) = [item for item in layout.of_kind("operator") if item.target == target]
        return found

    @staticmethod
    def label_texts(layout: FakeLayout) -> list[str]:
        return [item.text for item in layout.of_kind("label") if item.text]

    def row_drawn(self, row: Any) -> FakeLayout:
        """Una fila de la lista (``draw_item`` de su ``UIList``) dibujada."""
        layout = FakeLayout()
        self.panels.draw_inventory_row(layout, row)
        return layout

    # --- Ayudas de las cifras de la selección (T16) -------------------------------------------

    def demo_years(self) -> Any:
        """La cadena de la demostración de la 008 en el proyecto de la prueba: los bancos y sus
        años (``demo_bench_years``, con 3 cifras [CAL] de la producción, HIPÓTESIS sin
        confirmar); devuelve la demostración."""
        demo = self.enterContext(Demo(module_name()).registered())
        demo.digitize(self.data.project)
        demo.bench_years(self.data.project)
        return demo

    def change_production(self, value: float) -> None:
        """Otra producción de la demostración (sigue HIPÓTESIS), con su motivo: lo que la leyó
        queda obsoleto."""
        store = vf.extension("core.params").ParameterStore(self.data.project)
        with self.data.project.write_transaction() as conn:
            store.change(conn, PRODUCTION, value=value, source="Prueba de la vista",
                         source_kind="document", decided_by="la prueba", reason=vf.REASON)

    def showing(self, record: Any, name: str) -> bpy.types.Object:
        """Un objeto vacío que muestra el dato ``record`` del proyecto de la prueba (como su
        vista: la demostración no tiene cargador)."""
        obj = bpy.data.objects.new(name, None)
        bpy.context.scene.collection.objects.link(obj)
        obj.geoblender.dataset_uid = record.uid
        obj.geoblender.project_uid = self.data.project.uid
        return obj

    def figures_drawn(self, *, width_px: float = WIDE_PX) -> FakeLayout:
        """La ventana de «Cifras de la selección» dibujada (con ``width_px`` para sus
        etiquetas)."""
        panel = getattr(bpy.types, SELECTION_PANEL)
        with mock.patch.object(self.labels, "dialog_width", return_value=width_px):
            return draw(panel, bpy.context)

    def selection_figures(self, *objects: bpy.types.Object) -> list[str]:
        """Selecciona solo ``objects``, pide «Cifras de la selección» con una ventana (la suya
        se abre con ``wm.call_panel``, sustituido: en ``-b`` no hay región donde abrirla) y
        devuelve las etiquetas de su ventana, una por línea."""
        for obj in bpy.context.view_layer.objects:
            obj.select_set(obj in objects)
        ops_views = vf.extension("bl.ops.views")
        window = bpy.context.window_manager.windows[0]
        with mock.patch.object(ops_views, "_call_panel", return_value={"FINISHED"}) as call:
            with bpy.context.temp_override(window=window):
                self.assertEqual(bpy.ops.geoblender.core_show_selection_figures(),
                                 {"FINISHED"})
        call.assert_called_once_with(SELECTION_PANEL)
        return self.label_texts(self.figures_drawn())

    def figure_lines(self, record: Any) -> list[str]:
        """Lo que dice la ventana de las cifras de ``record``: cada una con su insignia de tipo,
        su nombre y su valor con su unidad, y sus marcas de hoy («depende de una hipótesis»,
        «obsoleta»…), leídas del proyecto."""
        card = vf.extension("core.views.card")
        ui = vf.extension("bl.ui.provenance")
        (found,) = card.dataset_figures(self.data.project, [record.uid])
        lines: list[str] = []
        for figure in found.figures:
            lines.append(f"{ui.badge(figure.kind)} {figure.text(language='es')}")
            marks = found.marks[figure.uid].texts(language="es")
            if marks:
                lines.append(" · ".join(marks))
        return lines

    @staticmethod
    def object_figures(obj: bpy.types.Object) -> list[tuple[str, ...]]:
        """Las cifras que anota ``obj`` (``Object.geoblender.figures``)."""
        return [tuple(getattr(item, key) for key in FIGURE_PROPS)
                for item in obj.geoblender.figures]

    def registered_figures(self, record: Any) -> list[tuple[str, ...]]:
        """Las cifras registradas de ``record`` como las anota un objeto: las de la operación
        que escribió su contenido, leídas del proyecto, en el idioma de la interfaz."""
        card = vf.extension("core.views.card")
        views = vf.extension("bl.scene.views")
        (found,) = card.dataset_figures(self.data.project, [record.uid], marks=False)
        return [tuple(getattr(views.FigureText.of(figure, "es"), key) for key in FIGURE_PROPS)
                for figure in found.figures]

    @staticmethod
    def load_demo(request: Any) -> Any:
        """El cargador de la prueba para los datos de la demostración: un objeto vacío."""
        obj = bpy.data.objects.new(request.name, None)
        return vf.extension("bl.scene.views").ViewParts((obj,), None)

    # --- Pruebas ------------------------------------------------------------------------------

    def test_card_of_the_dtm_read_from_the_project(self) -> None:
        """RF-010-06 (HU-010-3; plan A6, D-16): con el MDT importado activo, la ficha leída del
        proyecto: su nombre, «Tipo: MDT de origen · ráster · gis», «Estado: VIGENTE», «En la
        vista: al día», «Versión: —», la importación con su fecha y su versión de Geoblender,
        ↑ su entrada con el hash abreviado a 12 caracteres, ↓ la rejilla calculada de él, «Sin
        cifras registradas» y Procedencia con su dato; sin escribir nada. Al cambiar el
        proyecto (la rejilla, obsoleta), lo dice la ficha tras la siguiente lectura de los
        indicadores, en alerta; «no al día» y «sin respaldo», de ``view_state``. Dibujar no lee
        el proyecto; los textos caben a escala 1,0 y 1,25. En solo lectura, la misma ficha."""
        data = self.data
        mdt = data.import_grid(MDT)
        derived = data.derive(mdt.uid, DERIVED)
        data.attach()
        data.load(bpy.context, data.names[0], mdt.uid)
        counter = data.change_counter()
        with data.project.read() as conn:
            (entry_hash,) = conn.execute("SELECT content_sha256 FROM gb_input WHERE uid = ?",
                                         (mdt.input_uid,)).fetchone()
        op_type, op_version, finished, version = self.operation_of(mdt)
        self.activate(self.only(mdt.uid))
        expected = [
            mdt.name,
            "Tipo: MDT de origen · ráster · gis",
            "Estado: VIGENTE",
            "En la vista: al día",
            "Versión: —",
            f"Operación: Importación de un MDT ráster · {op_type} {op_version} · {finished} · "
            f"Geoblender {version}",
            "↑ Entradas",
            f"{MDT} · vigente · {entry_hash[:HASH_CHARS]}",
            "↓ Derivados",
            f"{derived.name} (project_grid) · vigente",
            "Cifras",
            NO_FIGURES,
        ]
        self.assertEqual(self.lines(), expected)
        self.assertEqual(op_type, "gis.import_dtm")
        self.assertEqual(self.line(MDT).icon, "IMPORT")
        self.assertFalse(self.line(derived.name).alert)
        button = self.lineage_button()
        self.assertEqual((button.text, button.properties.item_uid), ("Procedencia", mdt.uid))

        # Cambia el proyecto: hasta la siguiente lectura de los indicadores, como estaba.
        self.assertEqual(data.make_stale(), ())  # la rejilla de la prueba no lo lee
        self.assertEqual(self.lines(), expected)
        self.assertEqual(self.ui.indicator_tick(), self.ui.INDICATOR_TICK_S)
        stale = self.line(derived.name)
        self.assertEqual((stale.text, stale.alert),
                         (f"{derived.name} (project_grid) · vigente · obsoleto", True))

        # «Al día», de view_state del objeto activo (lo pone la marca en vivo).
        props = self.only(mdt.uid).geoblender
        for state, text in (("OUTDATED", "En la vista: no al día: Refrescar (F5)"),
                            ("UNBACKED", "En la vista: sin respaldo en el proyecto"),
                            ("CURRENT", "En la vista: al día")):
            props.view_state = state
            self.assertEqual(self.line("En la vista").text, text)
        self.assertEqual(self.line("En la vista").alert, False)

        # Dibujar no lee el proyecto; cabe en la barra lateral a escala 1,0 y 1,25.
        card = vf.extension("core.views.card")
        sidebar = self.labels.sidebar_width(bpy.context)
        with mock.patch.object(card, "item_card", wraps=card.item_card) as reads, \
                mock.patch.object(data.project, "read", wraps=data.project.read) as opens:
            for scale in at_scales():
                layout = self.drawn(width_px=sidebar)
                self.assertGreater(len(layout.of_kind("label")), len(expected))  # partidas
                assert_fits(self, layout, sidebar, scale=scale)
                for item in layout.of_kind("operator"):
                    self.assertLessEqual(self.labels.label_px(item.text, icon=True, scale=scale),
                                         sidebar)
        self.assertEqual((reads.call_count, opens.call_count), (0, 0))
        icons = bpy.types.UILayout.bl_rna.functions["label"].parameters["icon"].enum_items
        self.assertLessEqual({item.icon for item in layout.items}, set(icons.keys()))

        # En solo lectura, la misma ficha; nada escrito en el proyecto.
        changed = data.change_counter()
        data.project.set_read_only(vf.extension("core.project").ReadOnlyCode.REQUESTED,
                                   "prueba")
        self.activate(None)
        self.assertEqual(self.lines(), [NOT_OURS])
        self.activate(self.only(mdt.uid))
        self.assertEqual(self.lines()[:3], expected[:3])
        self.assertEqual(self.line(derived.name).text,
                         f"{derived.name} (project_grid) · vigente · obsoleto")
        self.assertEqual(data.change_counter(), changed)
        self.assertEqual(changed, counter + 1)  # solo el parámetro de make_stale

    def test_figures_of_a_demonstration_dataset(self) -> None:
        """RF-010-06 (Silvestre UI-03): con un objeto que muestra los años por banco de la
        demostración, la ficha da sus cifras con su valor, su unidad y su insignia de tipo
        ([CAL]), sin marcas, ↑ los bancos que consumió con su hash y ningún derivado."""
        data = self.data
        source = data.sources / "Limites.gpkg"
        shutil.copyfile(DEMO_DATA / "Limites_v1.gpkg", source)
        demo = self.enterContext(Demo(module_name()).registered())
        demo.import_boundary(data.project, source)
        demo.digitize(data.project)
        years_op = demo.bench_years(data.project)
        data.attach()
        years = data.record("demo_bench_years")
        benches = data.record("demo_benches")
        shown = bpy.data.objects.new("Años por banco", None)
        bpy.context.scene.collection.objects.link(shown)
        shown.geoblender.dataset_uid = years.uid
        shown.geoblender.project_uid = data.project.uid
        counter = data.change_counter()
        self.activate(shown)
        figures, _warnings = demo.figures(data.project, years_op.uid)
        self.assertEqual(len(figures), 3)
        lines = self.lines()
        start = lines.index("Cifras") + 1
        self.assertEqual(lines[start:],
                         [f"[CAL] {figure.text(language='es')}" for figure in figures])
        self.assertIn("· B-1 = 2,5 año", lines[start])
        up = lines.index("↑ Entradas") + 1
        self.assertEqual(lines[up:lines.index("↓ Derivados")],
                         [f"{benches.name} (benches) · vigente · "
                          f"{benches.content_sha256[:HASH_CHARS]}"])
        self.assertEqual(lines[lines.index("↓ Derivados") + 1], "Ningún derivado")
        self.assertEqual(lines[0], years.name)
        self.assertEqual(data.change_counter(), counter)

    def test_active_object_changes_the_card_also_after_loading_a_blend(self) -> None:
        """RF-010-06 (plan A6, §2.1, R2): cambiar el objeto activo cambia la ficha; un objeto
        del usuario no tiene ficha y uno cuyo dato ya no está en el proyecto lo dice. La
        suscripción a ``LayerObjects.active`` sigue tras cargar otro ``.blend``: Blender borra
        las de ``msgbus`` al cargar un fichero (sin renovarla en ``load_post``, ya no está), y
        ``load_post`` la renueva y vuelve a leer la ficha del objeto activo del fichero."""
        data = self.data
        mdt = data.import_grid(MDT)
        data.attach()
        data.load(bpy.context, data.names[0], mdt.uid)
        grid = data.record(data.names[0])
        _work, (sketch, *_rest) = vf.user_objects(bpy.data, bpy.context.scene, count=1)
        self.assertTrue(self.panels.is_subscribed())
        self.activate(self.only(grid.uid))
        self.assertEqual(self.lines()[0], grid.name)
        self.activate(self.only(mdt.uid))
        self.assertEqual(self.lines()[0], mdt.name)
        self.activate(sketch)
        self.assertEqual(self.lines(), [NOT_OURS])
        self.assertEqual([item.target for item in self.drawn().of_kind("operator")], [])
        gone = bpy.data.objects.new("Sin dato", None)
        bpy.context.scene.collection.objects.link(gone)
        gone.geoblender.dataset_uid = vf.extension("core.ids").new_uid()
        gone.geoblender.project_uid = data.project.uid
        self.activate(gone)
        self.assertEqual(self.lines(), [GONE])
        bpy.data.objects.remove(gone)

        # Guardada la vista con la rejilla activa, cargarla otra vez sin renovar la suscripción:
        # Blender la ha borrado.
        bpy.context.view_layer.objects.active = self.only(grid.uid)
        view = data.root / "scenes" / "panel.blend"
        view.parent.mkdir(parents=True, exist_ok=True)
        self.assertEqual(bpy.ops.wm.save_as_mainfile(filepath=str(view)), {"FINISHED"})
        handlers = bpy.app.handlers.load_post
        handlers.remove(self.panels.on_load_post)
        try:
            blender_ext.load_file(view)
        finally:
            handlers.append(self.panels.on_load_post)
        self.assertFalse(self.panels.is_subscribed())

        # Con load_post, la suscripción se renueva y la ficha es la del objeto activo.
        with mock.patch.object(bpy.msgbus, "subscribe_rna",
                               wraps=bpy.msgbus.subscribe_rna) as subscribe:
            blender_ext.load_file(view)
        self.assertIs(self.ps.current(), data.project)  # la vista es de este proyecto
        self.assertTrue(self.panels.is_subscribed())
        # Los complementos de Blender también se suscriben al cargar: solo la de la ficha.
        (call,) = [call for call in subscribe.call_args_list
                   if call.kwargs.get("notify") is self.panels.on_active_changed]
        self.assertEqual(call.kwargs["key"], (bpy.types.LayerObjects, "active"))
        self.assertEqual(self.lines()[0], grid.name)
        self.activate(self.only(mdt.uid))
        self.assertEqual(self.lines()[0], mdt.name)

    def test_inventory_finds_loads_and_unloads_a_dataset(self) -> None:
        """RF-010-07 (HU-010-3; plan A7, D-15): el inventario da lo registrado, cargado o no
        (la entrada del MDT, lo importado de ella y la rejilla, que está en la escena), sin
        leer nada hasta que el panel se dibuja; el texto encuentra el dato no cargado sin leer
        el proyecto; «Cargar en la vista» lo carga, «Descargar» lo quita (y «en la escena»
        está al día tras cada uno) y «Procedencia» abre la de la 008 con él; una entrada no se
        carga ni tiene procedencia (botones desactivados, con el motivo). El panel, en el modo
        Geoblender; los textos caben a escala 1,0 y 1,25; nada escrito en el proyecto."""
        data = self.data
        mdt = data.import_grid(MDT)
        data.attach()
        data.load(bpy.context, data.names[0])
        grid = data.record(data.names[0])
        counter = data.change_counter()
        view = self.view()
        inventory = vf.extension("core.views.inventory")
        tick = self.panels.inventory_tick

        # Abrir el proyecto no lee el inventario: lo pide el dibujo del panel.
        self.assertFalse(bpy.app.timers.is_registered(tick))
        self.assertEqual(len(view.inventory), 0)
        self.assertEqual(self.label_texts(self.inventory_drawn()), [READING])
        self.read_inventory()
        self.assertEqual([row.name for row in view.inventory],
                         sorted((MDT, mdt.name, grid.name), key=inventory.fold))
        self.assertEqual(self.shown(), {MDT: ("INPUT", False, False),
                                        mdt.name: ("DATASET", False, False),
                                        grid.name: ("DATASET", True, False)})
        self.assertEqual({row.version for row in view.inventory}, {""})  # «—» hasta la 009
        self.assertEqual(view.inventory_more, 0)

        # El texto encuentra el dato no cargado, filtrando lo leído: no lee el proyecto.
        with mock.patch.object(inventory, "read_inventory",
                               wraps=inventory.read_inventory) as reads:
            with mock.patch.object(data.project, "read", wraps=data.project.read) as opens:
                view.inventory_text = "NORTE"
                self.assertEqual(set(self.shown()), {MDT, mdt.name})
                row = self.choose(mdt.name)
                layout = self.inventory_drawn()
            self.assertEqual(opens.call_count, 0)
            self.assertFalse(bpy.app.timers.is_registered(tick))  # nada viejo: no lo pide
            load, unload = self.button(layout, LOAD), self.button(layout, UNLOAD)
            lineage = self.button(layout, SHOW_LINEAGE)
            self.assertEqual((load.text, load.enabled, load.properties.datasets),
                             ("Cargar en la vista", True, mdt.uid))
            self.assertEqual((unload.text, unload.enabled, unload.properties.datasets),
                             ("Descargar", False, mdt.uid))
            self.assertEqual((lineage.text, lineage.enabled, lineage.properties.item_uid),
                             ("Procedencia", True, mdt.uid))
            texts = self.label_texts(layout)
            self.assertIn(NOT_LOADED, texts)
            for expected in (mdt.name, "Tipo: MDT de origen · ráster · gis",
                             "Estado: VIGENTE", "Versión: —", "No cargado en la escena"):
                self.assertIn(expected, texts)

            # «Cargar en la vista» lo carga; «en la escena», al día al dibujarlo otra vez.
            self.assertEqual(bpy.ops.geoblender.core_load_into_view(
                "EXEC_DEFAULT", datasets=load.properties.datasets), {"FINISHED"})
            self.assertEqual(len(vf.objects_of(bpy.data, mdt.uid)), 1)
            self.assertFalse(row.in_scene)  # hasta que el panel se dibuje
            self.inventory_drawn()
            self.read_inventory()
            row = view.inventory[view.inventory_index]
            self.assertEqual((row.name, row.in_scene), (mdt.name, True))  # sigue elegida
            layout = self.inventory_drawn()
            self.assertTrue(self.button(layout, UNLOAD).enabled)
            self.assertIn("Cargado en la escena", self.label_texts(layout))
            self.assertIn("HIDE_OFF", [item.icon for item in self.row_drawn(row).items])

            # «Descargar» lo quita.
            self.assertEqual(bpy.ops.geoblender.core_unload_from_view(
                "EXEC_DEFAULT", datasets=unload.properties.datasets), {"FINISHED"})
            self.assertEqual(vf.objects_of(bpy.data, mdt.uid), [])
            self.inventory_drawn()
            self.read_inventory()
            self.assertEqual(self.shown()[mdt.name], ("DATASET", False, False))
            self.assertNotIn("HIDE_OFF", [item.icon for item in self.row_drawn(
                view.inventory[view.inventory_index]).items])
        self.assertEqual(reads.call_count, 0)  # cargar y descargar no cambian el proyecto

        # «Procedencia» abre la de la 008 con ese dato (su ventana, con wm.call_panel sustituido:
        # en -b no hay región donde abrirla).
        lineage_ops = vf.extension("bl.ops.core_provenance")
        window = bpy.context.window_manager.windows[0]
        with mock.patch.object(lineage_ops, "_call_panel", return_value={"FINISHED"}) as call:
            with bpy.context.temp_override(window=window):
                self.assertEqual(bpy.ops.geoblender.core_show_lineage(
                    item_uid=lineage.properties.item_uid), {"FINISHED"})
        call.assert_called_once_with(vf.extension("bl.ui.provenance").LINEAGE_PANEL)
        lineage_view = getattr(bpy.context.window_manager,
                               vf.extension("bl.props.provenance").WINDOW_MANAGER_PROPERTY)
        self.assertEqual((lineage_view.lineage_uid, lineage_view.lineage[0].uid),
                         (mdt.uid, mdt.uid))

        # Una entrada no se carga ni tiene procedencia: desactivados, con el motivo.
        view.inventory_kind = "INPUT"
        self.assertEqual(list(self.shown()), [MDT])
        self.choose(MDT)
        layout = self.inventory_drawn()
        for target, reason in ((LOAD, INPUT_NOT_LOADED), (UNLOAD, NOT_LOADED),
                               (SHOW_LINEAGE, INPUT_NO_LINEAGE)):
            self.assertFalse(self.button(layout, target).enabled, target)
            self.assertIn(reason, self.label_texts(layout))
        self.assertIn("Estado: vigente", self.label_texts(layout))

        # En la escena, sin texto: solo la rejilla cargada.
        view.inventory_kind = "ALL"
        view.inventory_text = ""
        view.inventory_presence = "IN"
        self.assertEqual(self.shown(), {grid.name: ("DATASET", True, False)})
        view.inventory_presence = "ALL"
        view.inventory_kind = "RASTER"
        self.assertEqual(set(self.shown()), {mdt.name, grid.name})

        # Los textos caben en la barra lateral a escala 1,0 y 1,25; los iconos son de 5.2.
        icons = set(bpy.types.UILayout.bl_rna.functions["label"].parameters["icon"]
                    .enum_items.keys())
        sidebar = self.labels.sidebar_width(bpy.context)
        for name in (MDT, grid.name):
            view.inventory_kind = "ALL"
            self.choose(name)
            for scale in at_scales():
                layout = self.inventory_drawn(width_px=sidebar)
                assert_fits(self, layout, sidebar, scale=scale)
                for item in layout.of_kind("operator"):
                    self.assertLessEqual(self.labels.label_px(item.text, icon=True, scale=scale),
                                         sidebar)
            drawn = [*layout.items, *self.row_drawn(view.inventory[view.inventory_index]).items]
            self.assertLessEqual({item.icon for item in drawn}, icons)
        self.assertEqual([item.target for item in layout.of_kind("template_list")],
                         [INVENTORY_LIST])

        # En el modo Geoblender: en una Vista 3D en modo Blender, no.
        panel = getattr(bpy.types, INVENTORY_PANEL)
        mode = vf.extension("bl.props.ui").WORKSPACE_PROPERTY
        for marked in (False, True):
            context = SimpleNamespace(area=SimpleNamespace(type="VIEW_3D"),
                                      workspace=SimpleNamespace(**{mode: marked}))
            self.assertIs(panel.poll(context), marked)
        self.assertEqual(data.change_counter(), counter)

    def test_inventory_reads_the_project_only_when_drawn(self) -> None:
        """RF-010-07 (plan A7, D-15): un cambio en el proyecto (la rejilla calculada del MDT,
        obsoleta) deja vieja la lectura del inventario, pero no se lee nada (ni tras la lectura
        de los indicadores de la procedencia) hasta que el panel se dibuja: entonces, una vez,
        y la fila dice «obsoleto»; el filtro de estado lo encuentra. En solo lectura, igual:
        se vuelve a leer y se puede cargar; nada escrito."""
        data = self.data
        mdt = data.import_grid(MDT)
        derived = data.derive(mdt.uid, DERIVED)
        data.attach()
        view = self.view()
        tick = self.panels.inventory_tick
        self.inventory_drawn()
        self.read_inventory()
        self.assertEqual(self.shown()[derived.name], ("DATASET", False, False))
        inventory = vf.extension("core.views.inventory")
        with mock.patch.object(inventory, "read_inventory",
                               wraps=inventory.read_inventory) as reads:
            self.assertEqual(data.make_stale(), ())
            self.assertEqual(self.ui.indicator_tick(), self.ui.INDICATOR_TICK_S)
            self.assertEqual(reads.call_count, 0)
            self.assertFalse(bpy.app.timers.is_registered(tick))
            self.assertEqual(self.shown()[derived.name], ("DATASET", False, False))
            with mock.patch.object(data.project, "read", wraps=data.project.read) as opens:
                self.inventory_drawn()  # dibujar no lee: lo pide
            self.assertEqual((reads.call_count, opens.call_count), (0, 0))
            self.read_inventory()
            self.assertEqual(reads.call_count, 1)
        self.assertEqual(self.shown()[derived.name], ("DATASET", False, True))
        row = self.choose(derived.name)
        flags = [item for item in self.row_drawn(row).items if item.icon == "ERROR"]
        self.assertEqual([item.alert for item in flags], [True])
        self.assertIn("Estado: VIGENTE · OBSOLETO", self.label_texts(self.inventory_drawn()))
        view.inventory_status = "STALE"
        self.assertEqual(list(self.shown()), [derived.name])

        # En solo lectura, igual: al cambiar el proyecto de la sesión se olvida y se vuelve a
        # leer al dibujarlo; se puede cargar.
        changed = data.change_counter()
        data.project.set_read_only(vf.extension("core.project").ReadOnlyCode.REQUESTED,
                                   "prueba")
        self.panels.on_project_changed(data.project)
        self.assertEqual(len(view.inventory), 0)
        self.assertEqual(self.label_texts(self.inventory_drawn()), [READING])
        self.read_inventory()
        self.assertEqual(self.shown(), {derived.name: ("DATASET", False, True)})
        self.choose(derived.name)
        self.assertTrue(self.button(self.inventory_drawn(), LOAD).enabled)
        self.assertEqual(data.change_counter(), changed)

    def test_inventory_shows_at_most_500_rows(self) -> None:
        """RF-010-07 (D-7, RNF-010-02): con 20 100 elementos, 500 filas por nombre y «… y
        19 600 más: afine el filtro»; un filtro que deja menos, todas y sin la línea."""
        data = self.data
        data.attach()
        inventory = vf.extension("core.views.inventory")
        i18n = vf.extension("core.i18n")
        rows = tuple(("DATASET", f"{index:032x}", f"dato_{index:05d}", "gis", "raster",
                      "current", None, False, False, True) for index in range(MANY))
        snapshot = inventory.InventorySnapshot(rows, data.change_counter())
        view = self.view()
        with mock.patch.object(inventory, "read_inventory", return_value=snapshot) as reads:
            self.inventory_drawn()
            self.read_inventory()
        self.assertEqual(reads.call_count, 1)
        self.assertEqual(len(view.inventory), ROWS)
        self.assertEqual((view.inventory[0].name, view.inventory[ROWS - 1].name),
                         ("dato_00000", f"dato_{ROWS - 1:05d}"))
        more = f"… y {i18n.format_number(MANY - ROWS, 0)} más: afine el filtro"
        self.assertEqual(more, "… y 19\N{NARROW NO-BREAK SPACE}600 más: afine el filtro")
        self.assertIn(more, self.label_texts(self.inventory_drawn()))
        view.inventory_text = "dato_000"
        self.assertEqual(len(view.inventory), 100)
        self.assertFalse([text for text in self.label_texts(self.inventory_drawn())
                          if text.startswith("… y")])

    def test_selection_figures_without_measuring(self) -> None:
        """RF-010-08 (plan A8, D-17, D-18; §5.5): «Cifras de la selección» (control 29) es la
        orden real de la entrada «010», entregada, con la descripción que no dice que mide; con
        los datos de los objetos seleccionados (sin repetir) lee del proyecto sus cifras
        registradas con sus marcas y abre su ventana: con la rejilla, que no tiene cifras,
        «Sin cifras registradas: …» y nada más (no mide); con los años por banco de la
        demostración, cada cifra con su valor y su unidad, su insignia ([CAL]) y sus marcas
        («depende de una hipótesis»), y tras cambiar la producción, también «obsoleta»; las
        dos a la vez, cada una con lo suyo; sin un dato del proyecto seleccionado, lo dice.
        No escribe en el proyecto; los textos caben a escala 1,0 y 1,25; sin proyecto, no se
        puede."""
        commands = vf.extension("bl.ui.commands")
        command = commands.catalog().commands[SELECTION_FIGURES]
        self.assertEqual((command.entry, command.action, command.description_es),
                         ("010", "P", SELECTION_DESCRIPTION))
        cls = commands.registered_class(SELECTION_FIGURES)
        self.assertFalse(commands.is_provisional(cls))
        self.assertTrue(commands.is_available(SELECTION_FIGURES))
        self.assertNotIn("R-07", cls.bl_description)

        data = self.data
        self.demo_years()
        data.attach()
        data.load(bpy.context, data.names[0])
        grid = data.record(data.names[0])
        years = data.record(YEARS_TABLE)
        shown = [self.showing(years, name) for name in ("Años por banco", "Años por banco 2")]
        (grid_obj,) = vf.objects_of(bpy.data, grid.uid)
        _work, (sketch, *_rest) = vf.user_objects(bpy.data, bpy.context.scene, count=1)
        counter = data.change_counter()

        # La rejilla no tiene cifras: «Sin cifras registradas: …» y nada más (no mide).
        self.assertEqual(self.selection_figures(grid_obj),
                         [SELECTION_TITLE, grid.name, NONE_RECORDED])

        # Los años por banco (dos objetos del mismo dato: una vez), con sus marcas; se leen
        # con ellas (marks=True), una vez por dato.
        card = vf.extension("core.views.card")
        with mock.patch.object(card, "dataset_figures", wraps=card.dataset_figures) as reads:
            lines = self.selection_figures(*shown)
        ((asked, options),) = [(list(call.args[1]), call.kwargs)
                               for call in reads.call_args_list]
        self.assertEqual((asked, options.get("marks")), ([years.uid], True))
        expected = self.figure_lines(years)
        self.assertEqual(lines, [SELECTION_TITLE, years.name, *expected])
        self.assertEqual(len([line for line in lines if line.startswith("[CAL] ")]), 3)
        self.assertIn("[CAL] Años del banco (demostración) · B-1 = 2,5 año", lines)
        self.assertIn(HYPOTHESIS, expected[1].split(" · "))
        layout = self.figures_drawn()
        marked = [item for item in layout.of_kind("label") if item.text == expected[1]]
        self.assertEqual([item.alert for item in marked], [True] * 3)  # bajo cada cifra
        self.assertEqual(data.change_counter(), counter)

        # Otra producción: las cifras, «obsoleta».
        self.change_production(400_000.0)
        counter = data.change_counter()
        lines = self.selection_figures(grid_obj, *shown)
        stale = self.figure_lines(years)
        self.assertIn(STALE_FIGURE, stale[1].split(" · "))
        self.assertIn(HYPOTHESIS, stale[1].split(" · "))
        # Las dos a la vez, por nombre: la rejilla dice que no tiene.
        self.assertEqual(lines, [SELECTION_TITLE, years.name, *stale, grid.name, NO_FIGURES])

        # Sin un dato del proyecto seleccionado (un objeto del usuario), lo dice.
        self.assertEqual(self.selection_figures(sketch), [SELECTION_TITLE, NOTHING_SELECTED])
        self.assertEqual(data.change_counter(), counter)

        # Desde un guion sin ventana: las filas, sin abrirla (tras cargar un .blend, en -b
        # bpy.context sí tiene ventana: un contexto sin ella). Los textos caben a escala 1,0 y
        # 1,25 en el ancho de la ventana.
        ops_views = vf.extension("bl.ops.views")
        operator = ops_views.GEOBLENDER_OT_core_show_selection_figures
        script = SimpleNamespace(window=None, window_manager=bpy.context.window_manager,
                                 selected_objects=[grid_obj, *shown])
        with mock.patch.object(ops_views, "_call_panel") as call:
            self.assertEqual(operator.execute(operator_self(operator), script), {"FINISHED"})
        self.assertEqual(call.call_count, 0)
        self.assertEqual(self.label_texts(self.figures_drawn()), lines)
        width = self.labels.dialog_width(self.panels.SELECTION_FIGURES_WIDTH_PX)
        for scale in at_scales():
            layout = draw(getattr(bpy.types, SELECTION_PANEL), bpy.context)
            self.assertGreaterEqual(len(layout.of_kind("label")), len(lines))
            assert_fits(self, layout, width, scale=scale)

        # Sin proyecto, no se puede.
        data.close()
        self.assertFalse(bpy.ops.geoblender.core_show_selection_figures.poll())

    def test_object_figures_after_loading_and_refresh(self) -> None:
        """RF-010-08 (plan A2, A8, D-17): las cifras de cada objeto (``Object.geoblender
        .figures``, solo para mostrarlas) son las registradas de su dato al cargarlo y tras cada
        Refrescar (F5): también en lo que F5 no vuelve a cargar (sin cifras, como un objeto
        cargado antes de la 010, las vuelve a tener), y con las de su operación nueva en lo que
        vuelve a cargar. La rejilla, sin cifras. Refrescar no escribe en el proyecto."""
        data = self.data
        views = vf.extension("bl.scene.views")
        demo = self.demo_years()
        views.register_loader(DEMO_PREFIX, "POINTS", DEMO_LABEL, self.load_demo)
        self.addCleanup(views.unregister_loader, DEMO_PREFIX)
        data.attach()
        years = data.record(YEARS_TABLE)
        data.load(bpy.context, data.names[0], years.uid)
        grid = data.record(data.names[0])
        obj = self.only(years.uid)
        loaded = self.registered_figures(years)
        self.assertEqual(len(loaded), 3)
        self.assertEqual(self.object_figures(obj), loaded)
        self.assertEqual({figure[4:] for figure in loaded}, {("yr", "CALCULADO")})
        self.assertIn(("Años del banco (demostración) · B-1", "2,5 año"),
                      [figure[2:4] for figure in loaded])
        self.assertEqual(self.object_figures(self.only(grid.uid)), [])

        # Sin cifras en el objeto: F5 no lo vuelve a cargar (está al día) y se las pone.
        obj.geoblender.figures.clear()
        counter = data.change_counter()
        self.assertEqual(bpy.ops.geoblender.core_refresh("EXEC_DEFAULT"), {"CANCELLED"})
        self.assertEqual(self.only(years.uid).name, obj.name)  # el mismo objeto
        self.assertEqual(self.object_figures(self.only(years.uid)), loaded)
        self.assertEqual(data.change_counter(), counter)

        # Otra producción y los años otra vez: F5 los vuelve a cargar con sus cifras nuevas.
        self.change_production(400_000.0)
        demo.bench_years(data.project)
        after = data.record(YEARS_TABLE)
        counter = data.change_counter()
        self.assertEqual(bpy.ops.geoblender.core_refresh("EXEC_DEFAULT"), {"FINISHED"})
        renewed = self.registered_figures(after)
        self.assertNotEqual(renewed, loaded)
        self.assertEqual(self.object_figures(self.only(after.uid)), renewed)
        self.assertEqual(self.object_figures(self.only(grid.uid)), [])
        self.assertEqual(data.change_counter(), counter)


class ActiveItemRegistrationTest(unittest.TestCase):
    """La extensión deshabilitada al empezar y al terminar (``blender_ext.release``)."""

    def setUp(self) -> None:
        blender_ext.release()
        self.addCleanup(blender_ext.release)

    def test_register_and_unregister_leave_no_trace(self) -> None:
        """RF-010-06, RF-010-07, RF-010-08 (plan §5.3.3, §2.1), principio 8: habilitar registra
        el panel en la pestaña «Proyecto» tras el panel Proyecto y, tras él, el del inventario
        con su lista (también tras cambiar el idioma), la ventana emergente de «Cifras de la
        selección» con su orden real (T16), suscribe la ficha al objeto activo y apunta su
        manejador ``@persistent`` de ``load_post``, su escucha del proyecto de la sesión y la
        de cada lectura de los indicadores; deshabilitar lo quita todo (la suscripción, también
        en Blender; el temporizador del inventario) y deja la huella de Blender como al
        principio de la sesión de pruebas."""
        blender_ext.enable()
        panels = vf.extension("bl.ui.view_panels")
        ui = vf.extension("bl.ui.provenance")
        ps = vf.extension("bl.scene.project_session")
        ui_i18n = vf.extension("bl.ui.i18n")
        panel = getattr(bpy.types, PANEL)
        project = getattr(bpy.types, PROJECT_PANEL)
        self.assertEqual((panel.bl_space_type, panel.bl_region_type, panel.bl_category,
                          panel.bl_label), ("VIEW_3D", "UI", project.bl_category,
                                            "Elemento activo"))
        self.assertEqual(project.bl_category, "Proyecto")
        self.assertNotIn("bl_order", vars(project))  # el de por defecto, 0
        self.assertGreater(panel.bl_order, 0)  # tras el panel Proyecto
        # T15: el inventario, tras Elemento activo, con su lista.
        inventory = getattr(bpy.types, INVENTORY_PANEL)
        self.assertEqual((inventory.bl_space_type, inventory.bl_region_type,
                          inventory.bl_category, inventory.bl_label),
                         ("VIEW_3D", "UI", "Proyecto", "Inventario"))
        self.assertGreater(inventory.bl_order, panel.bl_order)
        self.assertTrue(getattr(bpy.types, INVENTORY_LIST).is_registered)
        # T16: la ventana de «Cifras de la selección» (emergente, sin pestaña) y su orden.
        window = getattr(bpy.types, SELECTION_PANEL)
        self.assertEqual((window.bl_space_type, window.bl_region_type),
                         ("TOPBAR", "HEADER"))
        self.assertFalse(vf.extension("bl.ui.commands").is_provisional(
            vf.extension("bl.ui.commands").registered_class(SELECTION_FIGURES)))
        self.addCleanup(ui_i18n.apply, "es")
        ui_i18n.apply("en")
        panel = getattr(bpy.types, PANEL)
        self.assertEqual((panel.bl_category, panel.bl_label), ("Project", "Active item"))
        self.assertTrue(panel.is_registered)
        inventory = getattr(bpy.types, INVENTORY_PANEL)
        self.assertEqual((inventory.bl_category, inventory.bl_label), ("Project", "Inventory"))
        self.assertTrue(inventory.is_registered)
        ui_i18n.apply("es")
        self.assertEqual(getattr(bpy.types, PANEL).bl_category, "Proyecto")
        self.assertEqual(getattr(bpy.types, INVENTORY_PANEL).bl_category, "Proyecto")
        self.assertTrue(panels.is_subscribed())
        self.assertIn(panels.on_load_post, bpy.app.handlers.load_post)
        self.assertTrue(hasattr(panels.on_load_post, "_bpy_persistent"))
        self.assertIn(panels.on_project_changed, ps.listeners())
        self.assertIn(panels.on_project_read, ui.change_listeners())

        blender_ext.disable()
        self.assertFalse(panels.is_subscribed())
        self.assertNotIn(panels.on_load_post, bpy.app.handlers.load_post)
        self.assertNotIn(panels.on_project_changed, ps.listeners())
        self.assertNotIn(panels.on_project_read, ui.change_listeners())
        self.assertFalse(hasattr(bpy.types, PANEL))
        self.assertFalse(hasattr(bpy.types, INVENTORY_PANEL))
        self.assertFalse(hasattr(bpy.types, INVENTORY_LIST))
        self.assertFalse(hasattr(bpy.types, SELECTION_PANEL))
        self.assertFalse(bpy.app.timers.is_registered(panels.inventory_tick))
        after = blender_ext.state_fingerprint()
        baseline = blender_ext.session_baseline()
        if after != baseline:
            self.fail("la huella del estado de Blender cambió:\n"
                      + "\n".join(fingerprint_diff(baseline, after)))


if __name__ == "__main__":
    unittest.main()

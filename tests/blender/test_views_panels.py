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

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import shutil
import unittest
from typing import Any
from unittest import mock

import bpy

from tests.blender.test_dh_import_tabular import assert_fits, at_scales
from tests.support import blender_ext
from tests.support import views_fixtures as vf
from tests.support.blender_ext import fingerprint_diff, module_name
from tests.support.fake_layout import FakeLayout, draw
from tests.support.provenance_demo import Demo
from tests.support.repo import ROOT
from tests.support.trees import temp_folder

PANEL = "GEOBLENDER_PT_core_active_item"
PROJECT_PANEL = "GEOBLENDER_PT_core_project"
SHOW_LINEAGE = "geoblender.core_show_lineage"
DEMO_DATA = ROOT / "tests" / "data" / "core" / "provenance"
MDT = "MDT norte"
DERIVED = "Derivada"
HASH_CHARS = 12
WIDE_PX = 5000.0  # una barra lateral en la que nada se parte (para leer cada línea entera)
NOT_OURS = "El objeto activo no muestra un dato de este proyecto"
GONE = "El proyecto ya no tiene el dato de este objeto"
NO_FIGURES = "Sin cifras registradas"


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


class ActiveItemRegistrationTest(unittest.TestCase):
    """La extensión deshabilitada al empezar y al terminar (``blender_ext.release``)."""

    def setUp(self) -> None:
        blender_ext.release()
        self.addCleanup(blender_ext.release)

    def test_register_and_unregister_leave_no_trace(self) -> None:
        """RF-010-06 (plan §5.3.3, §2.1), principio 8: habilitar registra el panel en la pestaña
        «Proyecto» tras el panel Proyecto (también tras cambiar el idioma), suscribe la ficha
        al objeto activo y apunta su manejador ``@persistent`` de ``load_post``, su escucha del
        proyecto de la sesión y la de cada lectura de los indicadores; deshabilitar lo quita
        todo (la suscripción, también en Blender) y deja la huella de Blender como al
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
        self.addCleanup(ui_i18n.apply, "es")
        ui_i18n.apply("en")
        panel = getattr(bpy.types, PANEL)
        self.assertEqual((panel.bl_category, panel.bl_label), ("Project", "Active item"))
        self.assertTrue(panel.is_registered)
        ui_i18n.apply("es")
        self.assertEqual(getattr(bpy.types, PANEL).bl_category, "Proyecto")
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
        after = blender_ext.state_fingerprint()
        baseline = blender_ext.session_baseline()
        if after != baseline:
            self.fail("la huella del estado de Blender cambió:\n"
                      + "\n".join(fingerprint_diff(baseline, after)))


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: GPL-3.0-or-later
"""Ofrecer abrir el proyecto de una vista (spec 010, T12 y T13; HU-010-2; RF-010-04, RF-010-05,
RF-002-29; plan 010 §5.3.2, §5.3.3, §5.5, A5 y D-14).

Con el proyecto sintético de ``tests/support/views_fixtures.py`` (una rejilla, cargada en la
escena) y su vista guardada en ``scenes/`` con el proyecto abierto (``save_post`` la reescribe
sin los datos de la interfaz: ``georef.write_view_without_interface``); después, el proyecto
cerrado. En ``blender -b`` no corren los temporizadores e ``INVOKE_DEFAULT`` ejecuta ``execute``
(``docs/trampas.md`` §3): la oferta se hace como con interfaz (``view_link.background``
simulado); su temporizador se llama a mano, con ``view_link.launch`` simulado (en ``-b``, lanzar
el diálogo lo aceptaría); el diálogo, con ``invoke`` y ``draw`` a mano (``invoke_props_dialog``
y el *layout* simulados, como 004/T32); aceptar, como su botón (``EXEC_DEFAULT`` con lo que
lleva); y «Abrir proyecto…» de la 002, que lanza aceptar, con eventos ``TIMER`` a mano:

- **la oferta**: tras cargar la vista sin su proyecto (y además del aviso de RF-002-29), un
  temporizador de un disparo (≥ 0,1 s) lanza en la ventana ``geoblender.core_open_view_project``
  con la vista, la identidad, el nombre y la ruta relativa de su proyecto; el diálogo enseña el
  aviso de RF-002-29 y «¿Abrir el proyecto «…» de esta vista? Está en «..\\» (relativa a la
  vista).», en líneas que caben con la escala 1,0 y 1,25, con los botones de Geoblender «Abrir el
  proyecto de esta vista» y «Ahora no» (``template_popup_confirm``);
- **«Ahora no»** no abre nada, no toma el cerrojo ni cambia nada en la carpeta del proyecto; la
  oferta sigue en el panel Proyecto (R3);
- **aceptar** busca el proyecto por la ruta relativa de la vista y lo abre con «Abrir proyecto…»
  de la 002 desde la interfaz (``INVOKE_DEFAULT``) y, tras el primer tic de los indicadores, lo
  de la T10: la rejilla recalculada desde otra sesión «NO AL DÍA» sin volver a cargarla, y «1
  dato de la vista no está al día: Refrescar (F5)»;
- **una vista fuera del proyecto, en otro volumen** (simulado: sin ruta relativa), por la
  identidad del proyecto entre los recientes del equipo; y **tras cerrar el de otro** proyecto
  al cargarla, también; en un fichero con escenas de dos proyectos, el de la escena de la
  ventana;
- **las reglas de la 002**: con el cerrojo de otra sesión, en solo lectura y con el cerrojo
  igual; con un esquema anterior, «Abrir proyecto…» enseña su diálogo de migrar (con interfaz)
  sin escribir nada;
- **no se ofrece** en ``blender -b`` de verdad, al recuperar un autoguardado
  (``wm.save_auto_save`` y ``wm.recover_auto_save``) o la última sesión (``quit.blend``,
  ``wm.recover_last_session``) con la carpeta temporal de Blender en la de la prueba, ni en una
  vista dentro de ``.anterior``, ``.respaldo-esquema-N`` o ``.publicando``;
- **el proyecto movido** (T13; RF-010-05): el diálogo da el aviso con la ubicación y la
  identidad esperadas (también si allí hay otro proyecto) y ofrece «Localizar el proyecto…»
  (``geoblender.core_locate_project``, con el explorador de carpetas), que no abre otro proyecto
  ni una carpeta sin proyecto (los dos sin cambios) y abre el movido; mientras, sin proyecto
  abierto ni georreferencia (la vista no es fuente de nada, RF-002-29);
- **las órdenes** son internas, de la entrada «010», reales y con su ``bl_idname``;
- **abrir el proyecto la deja al día** (009/T42; RF-010-03, RF-010-04): con la orden de la
  oferta o con «Abrir proyecto…», si la georreferencia de la vista es la del proyecto, se quitan
  la marca de vista desfasada y el aviso de «no está abierto»; con otra, o con otro proyecto,
  siguen (RF-002-29).

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import dataclasses
import os
import shutil
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy

from tests.blender.test_dh_import_tabular import assert_fits, at_scales
from tests.support import blender_ext
from tests.support import views_fixtures as vf
from tests.support.core_fixtures import mark_schema, settings_values
from tests.support.fake_layout import FakeLayout, draw, operator_self
from tests.support.provenance_checks import assert_source_untouched
from tests.support.trees import temp_folder

OPEN_VIEW_PROJECT = "geoblender.core_open_view_project"
LOCATE_PROJECT = "geoblender.core_locate_project"
OPEN_THIS = "Abrir el proyecto de esta vista"
LOCATE = "Localizar el proyecto…"
NOT_NOW = "Ahora no"
NAME = "Cantera Prueba"  # el de los proyectos sintéticos (core_fixtures)
ONE_OUTDATED = "1 dato de la vista no está al día: Refrescar (F5)"
VIEW_STALE = "La vista está desfasada: vuelva a cargar sus datos"  # el panel Proyecto
TIMER = SimpleNamespace(type="TIMER", value="NOTHING")
MAX_EVENTS = 10_000
MAX_TICKS = 400
OPEN_FIELDS: dict[str, Any] = {
    "read_only": False, "confirmed": False, "force_lock": False, "seen_lock": "",
    "accept_migration": False, "notice": "", "offer_force": False, "offer_migration": False,
}
"""Las demás propiedades de «Abrir proyecto…» (002) cuando aceptar la lanza con la carpeta."""


class _WithInterface:
    """``bpy`` visto desde Blender con interfaz (``bpy.app.background`` falso), para lanzar a
    mano «Abrir proyecto…» de la 002 como lo lanza aceptar en la interfaz; lo demás, el de
    verdad."""

    app = SimpleNamespace(background=False)

    def __getattr__(self, name: str) -> Any:
        return getattr(bpy, name)


def _same(first: Any, second: Any) -> bool:
    """Si dos rutas son la misma (sin distinguir mayúsculas en Windows)."""
    def form(path: Any) -> str:
        return os.path.normcase(os.path.normpath(os.fspath(path)))
    return form(first) == form(second)


def _text(layout: FakeLayout, kind: str = "label") -> str:
    """Los textos de las etiquetas de ``layout`` seguidos, con los espacios normalizados."""
    return " ".join(" ".join(item.text for item in layout.of_kind(kind)).split())


def _flat(text: str) -> str:
    return " ".join(text.split())


def _squeezed(text: str) -> str:
    """``text`` sin ningún espacio: una ruta larga se parte en trozos de línea en línea, y
    :func:`_text` los une con uno."""
    return "".join(text.split())


class ViewLinkTest(unittest.TestCase):
    """La extensión habilitada una vez; en cada prueba, un proyecto de la vista con una rejilla
    cargada y su vista guardada en ``scenes/`` con el proyecto abierto."""

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
        self.link = vf.extension("bl.scene.view_link")
        self.views_ops = vf.extension("bl.ops.views")
        self.core_ops = vf.extension("bl.ops.core")
        self.georef = vf.extension("bl.scene.georef")
        self.ps = vf.extension("bl.scene.project_session")
        self.locate = vf.extension("core.views.locate")
        self.core = vf.extension("core.project")
        i18n = vf.extension("core.i18n")
        self.addCleanup(i18n.set_language, i18n.language())
        i18n.set_language("es")
        self.folder = temp_folder(self, "gb-v010k-")
        self.addCleanup(blender_ext.load_file)
        self.data = vf.ViewsProject(self.folder, grids=1)
        self.data.attach()
        self.addCleanup(self.data.close)
        self.addCleanup(self.ps.close)
        self.uid = self.data.project.uid
        self.data.load(bpy.context)
        self.grid = self.data.record(self.data.names[0])
        self.view = self.data.root / "scenes" / "principal.blend"
        self.save(self.view)

    # --- Ayudas -------------------------------------------------------------------------------

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.assertEqual(bpy.ops.wm.save_as_mainfile(filepath=str(path)), {"FINISHED"})

    @contextmanager
    def interface(self) -> Iterator[None]:
        """Blender con interfaz para la oferta (``view_link.background`` falso)."""
        with mock.patch.object(self.link, "background", return_value=False):
            yield

    def offered(self, path: Path) -> Any:
        """Carga ``path`` como con interfaz; la oferta que queda (``None`` si ninguna)."""
        with self.interface():
            blender_ext.load_file(path)
        return self.link.current_offer()

    def assertNotOffered(self) -> None:
        self.assertIsNone(self.link.current_offer())
        self.assertFalse(bpy.app.timers.is_registered(self.link.offer_tick))

    def other_session(self) -> Any:
        """El proyecto de la vista abierto en escritura por otra sesión (otro ``Project`` sobre
        la misma carpeta, fuera de la de Blender), con su cerrojo; lo que escriba
        ``self.data`` va con él."""
        session = dataclasses.replace(self.ps.session(),
                                      session_uid=vf.extension("core.ids").new_uid())
        other = self.core.open_project(self.data.root, session, self.ps.userdata()).project
        self.assertTrue(other.writable)
        self.data.project = other
        return other

    def dialog(self, offer: Any) -> tuple[Any, mock.Mock, Any]:
        """El diálogo de la oferta abierto a mano (``invoke`` con ``invoke_props_dialog``
        simulado): lo que devuelve, el simulado y la orden (su ``self`` simulado)."""
        cls = self.views_ops.GEOBLENDER_OT_core_open_view_project
        shown = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window_manager=SimpleNamespace(invoke_props_dialog=shown))
        operator = operator_self(cls, not_found="", **offer.properties())
        return cls.invoke(operator, context, None), shown, operator

    def drawn(self, offer: Any, not_found: str = "") -> FakeLayout:
        cls = self.views_ops.GEOBLENDER_OT_core_open_view_project
        return draw(cls, bpy.context, not_found=not_found, **offer.properties())

    def located(self, folder: Path) -> tuple[set[str], list[tuple[set[str], str]]]:
        """«Localizar el proyecto…» tras elegir ``folder`` en el explorador de carpetas (su
        ``execute``, con la identidad y el nombre del proyecto de la vista): lo que devuelve y
        lo que dice."""
        cls = self.views_ops.GEOBLENDER_OT_core_locate_project
        reports: list[tuple[set[str], str]] = []
        operator = operator_self(cls, directory=str(folder), project_uid=self.uid,
                                 project_name=NAME,
                                 report=lambda kind, text: reports.append((kind, text)))
        return cls.execute(operator, bpy.context), reports

    def accept(self, offer: Any) -> mock.Mock:
        """El botón «Abrir el proyecto de esta vista» del diálogo (la orden con lo que lleva,
        ``EXEC_DEFAULT``); lo que se le pidió a «Abrir proyecto…» (``open_project_folder``)."""
        opener = mock.patch.object(self.views_ops, "open_project_folder",
                                   wraps=self.views_ops.open_project_folder)
        with opener as called:
            self.assertEqual(
                bpy.ops.geoblender.core_open_view_project("EXEC_DEFAULT", **offer.properties()),
                {"FINISHED"})
        called.assert_called_once()
        return called

    def finish_opening(self) -> Any:
        """«Abrir proyecto…» (002), en marcha como modal, hasta el final con eventos ``TIMER``
        (sin bucle de eventos, Blender no se entera de los que terminaron: el que aún tiene
        pasos); el proyecto de la sesión."""
        cls = self.core_ops.GEOBLENDER_OT_core_open_project
        (operator,) = [op for op in bpy.context.window.modal_operators
                       if isinstance(op, cls) and getattr(op, "_steps", None) is not None]
        for _ in range(MAX_EVENTS):
            if operator.modal(bpy.context, TIMER) != {"RUNNING_MODAL"}:
                break
        self.assertEqual(operator.outcome, "FINISHED")
        return self.ps.current()

    def tick(self) -> None:
        """El primer tic de los indicadores de la procedencia y los de la marca en vivo."""
        ui, live = vf.extension("bl.ui.provenance"), vf.extension("bl.scene.live")
        self.assertEqual(ui.indicator_tick(), ui.INDICATOR_TICK_S)
        for _ in range(MAX_TICKS):
            if live.mark_tick() is None:
                return
        self.fail("la marca en vivo no acaba")

    # --- Las pruebas --------------------------------------------------------------------------

    def test_offer_dialog_and_opening_of_a_view_of_scenes(self) -> None:
        """RF-010-04, RF-002-29, HU-010-2 (T12; plan A5, D-14, R3): con la rejilla recalculada
        desde otra sesión y el proyecto cerrado, cargar su vista de ``scenes/`` en ``blender -b``
        avisa (RF-002-29) y no ofrece nada; con interfaz, además, un temporizador de un disparo
        (≥ 0,1 s) lanza en la primera ventana la orden interna con la vista, la identidad, el
        nombre y la ruta relativa («//../»). Su diálogo: el aviso y la pregunta con dónde está
        («..\\», relativa a la vista), en líneas que caben con la escala 1,0 y 1,25, y los
        botones «Abrir el proyecto de esta vista» (la orden con lo mismo, ``EXEC_DEFAULT``) y
        «Ahora no». Abrirlo y no aceptar no abre nada, no toma el cerrojo ni cambia nada en la
        carpeta del proyecto, y el panel Proyecto lo sigue ofreciendo (de qué proyecto es la
        vista y el botón, que caben en la barra lateral de por defecto con la escala 1,0 y
        1,25; el botón abre el diálogo, ``INVOKE_DEFAULT``). Aceptar lo busca por la
        ruta relativa y lo abre con «Abrir proyecto…» de la 002 (en escritura); después, con lo
        de la T10, la rejilla «[VIGENTE · NO AL DÍA]» sin volver a cargarla y «1 dato de la
        vista no está al día: Refrescar (F5)». La orden es interna, de la entrada «010», real
        (no provisional) y no deshace la vista."""
        data, ps, link = self.data, self.ps, self.link
        commands = vf.extension("bl.ui.commands")
        command = commands.catalog().commands[OPEN_VIEW_PROJECT]
        self.assertEqual((command.kind, command.entry, command.label_es),
                         ("internal", "010", OPEN_THIS))
        cls = commands.registered_class(OPEN_VIEW_PROJECT)
        self.assertFalse(commands.is_provisional(cls))
        self.assertTrue(commands.is_available(OPEN_VIEW_PROJECT))
        self.assertIn("INTERNAL", cls.bl_options)
        self.assertNotIn("UNDO", cls.bl_options)

        # Cerrado el proyecto, otra sesión recalcula la rejilla.
        data.close()
        other = self.other_session()
        try:
            changed = data.recompute(self.grid.uid)
        finally:
            other.close()
        self.assertNotEqual(changed.content_sha256, self.grid.content_sha256)
        ps.take_notices()

        # blender -b de verdad: el aviso de RF-002-29, sin oferta.
        blender_ext.load_file(self.view)
        self.assertIsNone(ps.current())
        self.assertEqual(len(ps.take_notices()), 1)
        self.assertNotOffered()

        # Con interfaz: el temporizador de un disparo, que lanza la orden en la ventana.
        registered = mock.patch.object(bpy.app.timers, "register",
                                       wraps=bpy.app.timers.register)
        with self.interface(), registered as timers:
            blender_ext.load_file(self.view)
        delays = [call.kwargs.get("first_interval") for call in timers.call_args_list
                  if call.args and call.args[0] is link.offer_tick]
        self.assertEqual(delays, [link.OFFER_DELAY_S])
        self.assertGreaterEqual(link.OFFER_DELAY_S, 0.1)
        self.assertTrue(bpy.app.timers.is_registered(link.offer_tick))
        (notice,) = ps.take_notices()
        offer = link.current_offer()
        self.assertEqual((offer.link, offer.notice),
                         (self.locate.ViewLink(self.uid, NAME, "//../"), notice))
        self.assertTrue(_same(offer.blend_file, self.view))
        with mock.patch.object(link, "launch") as launch:
            self.assertIsNone(link.offer_tick())
        bpy.app.timers.unregister(link.offer_tick)  # de un disparo: lo quitaría Blender
        launch.assert_called_once_with(bpy.context.window_manager.windows[0], offer)

        # El diálogo; «Ahora no» no abre nada y la oferta sigue en el panel Proyecto.
        labels = vf.extension("bl.ui.labels")
        question = (f"¿Abrir el proyecto «{NAME}» de esta vista? Está en «..{os.sep}» "
                    "(relativa a la vista).")
        with assert_source_untouched(data.root):
            result, shown, operator = self.dialog(offer)
            self.assertEqual(operator.not_found, "")
            self.assertEqual(result, {"RUNNING_MODAL"})
            shown.assert_called_once()
            self.assertEqual(shown.call_args.kwargs["title"], OPEN_THIS)
            width = labels.dialog_width(shown.call_args.kwargs["width"])
            for scale in at_scales():
                layout = self.drawn(offer)
                self.assertEqual(_text(layout), _flat(f"{notice} {question}"))
                assert_fits(self, layout, width, scale=scale)
                (buttons,) = layout.of_kind("template_popup_confirm")
                self.assertEqual((buttons.target, buttons.text, buttons.options.get("cancel_text"),
                                  buttons.operator_context),
                                 (OPEN_VIEW_PROJECT, OPEN_THIS, NOT_NOW, "EXEC_DEFAULT"))
                self.assertEqual(vars(buttons.properties), offer.properties())
            self.assertIsNone(ps.current())
            self.assertFalse((data.root / ".lock").exists())
        panel = vf.extension("bl.ui.core_panel").GEOBLENDER_PT_core_project
        (button,) = [item for item in draw(panel, bpy.context).of_kind("operator")
                     if item.target == OPEN_VIEW_PROJECT]
        self.assertEqual((button.text, button.operator_context, vars(button.properties)),
                         (OPEN_THIS, "INVOKE_DEFAULT", offer.properties()))
        sidebar = labels.sidebar_width(bpy.context)
        for scale in at_scales():
            layout = FakeLayout()  # lo que añade la oferta al panel
            panel.draw_view_offer(operator_self(panel), bpy.context, layout)
            self.assertEqual(_text(layout),
                             f"Esta vista es del proyecto «{NAME}», que no está abierto")
            assert_fits(self, layout, sidebar, scale=scale)
            (button,) = layout.of_kind("operator")
            self.assertLessEqual(labels.label_px(button.text, icon=button.icon != "NONE",
                                                 scale=scale), sidebar)

        # Aceptar: por la ruta relativa, con «Abrir proyecto…»; después, lo de la T10.
        objects = {uid: obj.as_pointer() for uid, (obj,) in vf.loaded(bpy.data).items()}
        jobs_ops = vf.extension("bl.ops.jobs")
        reports = len(jobs_ops.sent_reports())
        opener = self.accept(offer)
        self.assertTrue(_same(opener.call_args.args[0], data.root))
        project = self.finish_opening()
        self.assertTrue(_same(project.root, data.root))
        self.assertTrue(project.writable)
        self.assertIsNone(link.current_offer())
        self.assertEqual([item for item in draw(panel, bpy.context).of_kind("operator")
                          if item.target == OPEN_VIEW_PROJECT], [])
        self.tick()
        (obj,) = vf.objects_of(bpy.data, self.grid.uid)
        self.assertEqual((obj.name, obj.geoblender.view_state, obj.geoblender.content_sha256),
                         ("MDT rejilla_01 [VIGENTE · NO AL DÍA]", "OUTDATED",
                          self.grid.content_sha256))
        self.assertEqual(obj.as_pointer(), objects[self.grid.uid])
        self.assertEqual([text for kind, text in jobs_ops.sent_reports()[reports:]
                          if kind == "WARNING" and text.endswith("Refrescar (F5)")],
                         [ONE_OUTDATED])

    def test_outside_view_by_recents_after_closing_another_project(self) -> None:
        """RF-010-04, RF-002-06, RF-002-08, RF-002-29 (T12; plan A5, D-14): una vista guardada
        fuera del proyecto en otro volumen (simulado: ``core.paths.same_volume`` falso al
        guardarla) no lleva ruta relativa. Cargarla con otro proyecto abierto lo cierra (sin
        cerrojo), avisa con los dos y ofrece el de la vista; el diálogo dice que se busca entre
        los recientes; aceptar lo encuentra por su identidad entre los recientes del equipo y
        lo abre, y la vista, con su georreferencia, deja de estar desfasada (009/T42;
        RF-010-03)."""
        data, ps, link = self.data, self.ps, self.link
        paths = vf.extension("core.paths")
        outside = self.folder / "fuera" / "vista.blend"
        with mock.patch.object(paths, "same_volume", return_value=False):
            self.save(outside)
        self.assertEqual(bpy.context.scene.geoblender.project_path, "")
        data.close()
        parent = self.folder / "otros"
        parent.mkdir()
        settings = self.core.ProjectSettings(**settings_values(name="Cantera Otra",
                                                               window=vf.WINDOW))
        another = self.core.create_project(parent, settings, ps.session(),
                                           ps.userdata()).project
        ps.attach(another)
        ps.take_notices()

        offer = self.offered(outside)
        self.assertIsNone(ps.current())
        self.assertTrue(another.closed)
        self.assertFalse((another.root / ".lock").exists())
        (notice,) = ps.take_notices()
        self.assertIn("«Cantera Otra»", notice)
        self.assertIn(f"«{NAME}»", notice)
        self.assertEqual((offer.link, offer.notice),
                         (self.locate.ViewLink(self.uid, NAME, ""), notice))
        self.assertTrue(_same(offer.blend_file, outside))
        self.assertIn(f"¿Abrir el proyecto «{NAME}» de esta vista? La vista no dice dónde está: "
                      "se busca entre los proyectos recientes de este equipo.",
                      _text(self.drawn(offer)))

        found = self.locate.find_project(offer.link, offer.blend_file,
                                         ps.userdata().recent_projects())
        self.assertEqual(found.how, self.locate.RECENT)
        opener = self.accept(offer)
        self.assertTrue(_same(opener.call_args.args[0], data.root))
        self.assertTrue(_same(self.finish_opening().root, data.root))
        # Con la georreferencia de la vista: deja de estar desfasada (009/T42).
        self.assertEqual([scene.geoblender.view_stale for scene in bpy.data.scenes],
                         [False] * len(bpy.data.scenes))

    def test_moved_project_not_found_and_located(self) -> None:
        """RF-010-05, RF-010-04, RF-002-29, HU-010-2 (T13; plan A5, §5.3.3, §5.5): una vista
        guardada fuera del proyecto, en el mismo volumen (guarda su ruta relativa), y el
        proyecto movido después a otra carpeta sin abrirlo. Al cargarla, el diálogo de la oferta
        no lo encuentra (ni allí ni entre los recientes, que lo tienen donde estaba) y lo dice
        con la ubicación y la identidad esperadas, en líneas que caben con la escala 1,0 y 1,25,
        con los botones «Localizar el proyecto…» (la orden interna con la identidad y el nombre
        del proyecto, desde la interfaz: el explorador de carpetas, en la de la vista) y «Ahora
        no»; si allí hay ahora otro proyecto (el mismo nombre, otra identidad), lo dice también.
        Aceptar desde un guion da el mismo aviso y, con interfaz, vuelve a abrir el diálogo con
        él. «Localizar el proyecto…» con ese otro proyecto: «… es el proyecto «…» (identidad …),
        no el de la vista (…): no se abre»; con una carpeta que no es un proyecto, tampoco; nada
        abierto ni escrito en ninguno de los dos, sin proyecto abierto ni georreferencia (la
        vista no es fuente de nada) y la vista desfasada. Con el movido, lo abre con «Abrir
        proyecto…» de la 002, en escritura. La orden es interna, de la entrada «010», real y no
        deshace la vista."""
        data, ps, link, locate = self.data, self.ps, self.link, self.locate
        commands = vf.extension("bl.ui.commands")
        command = commands.catalog().commands[LOCATE_PROJECT]
        self.assertEqual((command.kind, command.entry, command.label_es),
                         ("internal", "010", LOCATE))
        cls = commands.registered_class(LOCATE_PROJECT)
        self.assertFalse(commands.is_provisional(cls))
        self.assertTrue(commands.is_available(LOCATE_PROJECT))
        self.assertIn("INTERNAL", cls.bl_options)
        self.assertNotIn("UNDO", cls.bl_options)

        # La vista, fuera del proyecto en el mismo volumen; después, el proyecto movido.
        outside = self.folder / "planos" / "vista.blend"
        self.save(outside)
        relative = bpy.context.scene.geoblender.project_path
        self.assertTrue(relative.startswith("//../"), relative)
        data.close()
        old = data.root
        moved = self.folder / "movido" / old.name
        moved.parent.mkdir()
        old.rename(moved)
        offer = self.offered(outside)
        self.assertEqual(offer.link, locate.ViewLink(self.uid, NAME, relative))
        expected = locate.relative_root(relative, outside)
        self.assertTrue(_same(expected, old))
        self.assertFalse(expected.exists())

        # El diálogo: el aviso de RF-010-05 y «Localizar el proyecto…».
        labels = vf.extension("bl.ui.labels")
        missing = (f"No se encuentra el proyecto «{NAME}» de la vista «vista.blend»: se "
                   f"esperaba en «{expected}» con la identidad {self.uid}; no está allí ni entre "
                   "los proyectos recientes de este equipo. Localícelo o ábralo a mano.")
        with assert_source_untouched(moved):
            result, shown, operator = self.dialog(offer)
        self.assertEqual(result, {"RUNNING_MODAL"})
        shown.assert_called_once()
        self.assertEqual(operator.not_found, missing)
        width = labels.dialog_width(shown.call_args.kwargs["width"])
        start = os.path.join(os.fspath(outside.parent), "")
        for scale in at_scales():
            layout = self.drawn(offer, operator.not_found)
            self.assertEqual(_squeezed(_text(layout)), _squeezed(f"{offer.notice} {missing}"))
            assert_fits(self, layout, width, scale=scale)
            (buttons,) = layout.of_kind("template_popup_confirm")
            self.assertEqual((buttons.target, buttons.text, buttons.options.get("cancel_text"),
                              buttons.operator_context),
                             (LOCATE_PROJECT, LOCATE, NOT_NOW, "INVOKE_DEFAULT"))
            self.assertEqual(vars(buttons.properties),
                             {"project_uid": self.uid, "project_name": NAME,
                              "directory": start})
        self.assertEqual(
            _squeezed(link.not_found_text(locate.NotFound(None, offer.link, None), str(outside))),
            _squeezed(f"No se encuentra el proyecto «{NAME}» de la vista «vista.blend»: la "
                      "vista no dice dónde está y ningún proyecto reciente de este equipo tiene "
                      f"su identidad, {self.uid}. Localícelo o ábralo a mano."))

        # Allí, ahora, otro proyecto con el mismo nombre y otra identidad.
        settings = self.core.ProjectSettings(**settings_values(name=NAME, window=vf.WINDOW))
        impostor = self.core.create_project(old.parent, settings, ps.session(),
                                            ps.userdata()).project
        impostor.close()
        self.assertTrue(_same(impostor.root, old))
        self.assertNotEqual(impostor.uid, self.uid)
        elsewhere = (f"No se encuentra el proyecto «{NAME}» de la vista «vista.blend»: se "
                     f"esperaba en «{expected}» con la identidad {self.uid}, pero allí hay otro "
                     f"proyecto (identidad {impostor.uid}) y no está entre los proyectos "
                     "recientes de este equipo. Localícelo o ábralo a mano.")
        with assert_source_untouched(old), assert_source_untouched(moved):
            _result, _shown, operator = self.dialog(offer)
            self.assertEqual(operator.not_found, elsewhere)

            # Aceptar desde un guion: el aviso; con interfaz, el diálogo otra vez con él.
            opener_cls = self.views_ops.GEOBLENDER_OT_core_open_view_project
            reports: list[tuple[set[str], str]] = []
            accepted = operator_self(opener_cls, not_found="", **offer.properties(),
                                     report=lambda kind, text: reports.append((kind, text)))
            self.assertEqual(opener_cls.execute(accepted, bpy.context), {"CANCELLED"})
            self.assertEqual(reports, [({"WARNING"}, elsewhere)])
            shown = mock.Mock(return_value={"RUNNING_MODAL"})
            context = SimpleNamespace(window_manager=SimpleNamespace(invoke_props_dialog=shown))
            accepted = operator_self(opener_cls, not_found="", **offer.properties(),
                                     report=lambda kind, text: None)
            with self.interface():
                self.assertEqual(opener_cls.execute(accepted, context), {"RUNNING_MODAL"})
            shown.assert_called_once()
            self.assertEqual(accepted.not_found, elsewhere)

            # «Localizar el proyecto…»: el explorador de carpetas; otro proyecto u otra
            # carpeta, no.
            browse = mock.Mock()
            chooser = operator_self(cls, directory=start, project_uid=self.uid,
                                    project_name=NAME)
            context = SimpleNamespace(window_manager=SimpleNamespace(fileselect_add=browse))
            self.assertEqual(cls.invoke(chooser, context, None), {"RUNNING_MODAL"})
            browse.assert_called_once_with(chooser)
            self.assertEqual(self.located(old), ({"CANCELLED"}, [({"WARNING"}, (
                f"La carpeta «{old}» es el proyecto «{NAME}» (identidad {impostor.uid}), no el "
                f"de la vista ({self.uid}): no se abre"))]))
            self.assertEqual(self.located(outside.parent), ({"CANCELLED"}, [({"WARNING"}, (
                f"La carpeta «{outside.parent}» no es un proyecto de Geoblender ni el de la "
                f"vista ({self.uid}): no se abre"))]))
        self.assertIsNone(ps.current())
        self.assertIsNone(self.georef.project_georeference())
        self.assertFalse((old / ".lock").exists())
        self.assertFalse((moved / ".lock").exists())
        self.assertTrue(all(scene.geoblender.view_stale for scene in bpy.data.scenes))
        self.assertEqual(link.current_offer(), offer)

        # Con el movido: lo abre con «Abrir proyecto…» de la 002 (la vista, la misma).
        (shown_grid,) = vf.objects_of(bpy.data, self.grid.uid)
        pointer = shown_grid.as_pointer()
        opener = mock.patch.object(self.views_ops, "open_project_folder",
                                   wraps=self.views_ops.open_project_folder)
        with opener as called:
            self.assertEqual(bpy.ops.geoblender.core_locate_project(
                "EXEC_DEFAULT", directory=str(moved), project_uid=self.uid, project_name=NAME),
                {"FINISHED"})
        called.assert_called_once()
        self.assertTrue(_same(called.call_args.args[0], moved))
        project = self.finish_opening()
        self.assertEqual(project.uid, self.uid)
        self.assertTrue(_same(project.root, moved))
        self.assertTrue(project.writable)
        self.assertIsNone(link.current_offer())
        (obj,) = vf.objects_of(bpy.data, self.grid.uid)
        self.assertEqual(obj.as_pointer(), pointer)

    def test_opening_follows_the_rules_of_002(self) -> None:
        """RF-010-04, RF-002-09, RF-002-20 (T12; plan A5): aceptar abre con las reglas de la
        002. Con el cerrojo de otra sesión, en solo lectura (``LOCKED``) y con el cerrojo
        igual. Con un esquema anterior, «Abrir proyecto…» lanzado como desde la interfaz enseña
        su diálogo de migrar (con la copia previa) sin tomar el cerrojo, migrar ni escribir
        nada en la carpeta del proyecto."""
        data, ps = self.data, self.ps
        data.close()
        other = self.other_session()
        self.addCleanup(other.close)
        lock = (data.root / ".lock").read_bytes()
        self.accept(self.offered(self.view))
        project = self.finish_opening()
        self.assertFalse(project.writable)
        self.assertEqual(project.read_only_reason, self.core.ReadOnlyCode.LOCKED)
        self.assertEqual((data.root / ".lock").read_bytes(), lock)
        ps.close()
        other.close()

        mark_schema(data.root, 1)
        offer = self.offered(self.view)
        cls = self.core_ops.GEOBLENDER_OT_core_open_project
        shown = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window_manager=SimpleNamespace(invoke_props_dialog=shown))
        opened: list[Any] = []

        def from_interface(root: Path) -> set[str]:
            fake = operator_self(cls, directory=str(root), **OPEN_FIELDS)
            opened.append(fake)
            with mock.patch.object(self.core_ops, "bpy", _WithInterface()):
                return cls.invoke(fake, context, None)

        with (assert_source_untouched(data.root),
              mock.patch.object(self.views_ops, "open_project_folder",
                                side_effect=from_interface)):
            self.assertEqual(
                bpy.ops.geoblender.core_open_view_project("EXEC_DEFAULT", **offer.properties()),
                {"FINISHED"})
        (fake,) = opened
        self.assertTrue(_same(fake.directory, data.root))
        shown.assert_called_once()
        self.assertTrue(fake.offer_migration)
        self.assertIn("migr", fake.notice)
        self.assertIsNone(ps.current())
        self.assertFalse((data.root / ".lock").exists())
        migrations = vf.extension("core.project.migrations")
        self.assertFalse(migrations.backup_path(data.root, 1).exists())

    def test_not_offered(self) -> None:
        """RF-010-04, RF-002-29 (T12; plan A5, D-14; 010/T06): la vista de ``scenes/`` se
        ofrece con interfaz y, con escenas de dos proyectos, se ofrece el de la escena de la
        ventana. No se ofrece (aunque siga el aviso de RF-002-29): en ``blender -b`` de verdad;
        al recuperar un autoguardado de la vista (``wm.save_auto_save``,
        ``wm.recover_auto_save``) ni la última sesión (``quit.blend``,
        ``wm.recover_last_session``), con la carpeta temporal de Blender en la de la prueba;
        ni en una copia de la vista dentro de ``.anterior``, ``.respaldo-esquema-1`` o
        ``.publicando``."""
        data, link, georef = self.data, self.link, self.georef
        data.close()
        self.assertIsNotNone(self.offered(self.view))

        # Dos proyectos en el fichero: el de la escena de la ventana.
        first = bpy.context.scene
        second = bpy.data.scenes.new("Otra vista")
        for name in ("crs_epsg", "vcrs_epsg", "origin_x", "origin_y", "origin_z"):
            setattr(second.geoblender, name, getattr(first.geoblender, name))
        other_link = self.locate.ViewLink(vf.extension("core.ids").new_uid(), "Otro proyecto",
                                          "//../../Otro proyecto.gbproj/")
        second.geoblender.project_uid = other_link.project_uid
        second.geoblender.project_name = other_link.project_name
        second.geoblender.project_path = other_link.relative_path
        georefs = georef.file_georeferences()
        self.assertEqual(len(georefs), 2)
        with self.interface():
            self.assertTrue(link.offer_after_load(str(self.view), georefs))
            self.assertEqual(link.current_offer().link.project_uid, self.uid)
            bpy.context.window.scene = second
            self.assertTrue(link.offer_after_load(str(self.view), georefs))
            self.assertEqual(link.current_offer().link, other_link)

        # blender -b de verdad.
        blender_ext.load_file(self.view)
        self.assertNotOffered()
        self.assertTrue(all(scene.geoblender.view_stale for scene in bpy.data.scenes))

        # Autoguardado y última sesión, en la carpeta temporal de Blender de la prueba.
        temp = self.folder / "temporal"
        temp.mkdir()
        prefs = bpy.context.preferences.filepaths
        self.addCleanup(setattr, prefs, "temporary_directory", prefs.temporary_directory)
        prefs.temporary_directory = str(temp)
        self.assertTrue(_same(Path(bpy.app.tempdir).parent, temp))
        self.assertEqual(bpy.ops.wm.save_auto_save(), {"FINISHED"})
        (autosave,) = temp.glob(f"*{self.locate.AUTOSAVE_SUFFIX}")
        with self.interface(), blender_ext.loading():
            self.assertEqual(bpy.ops.wm.recover_auto_save(filepath=str(autosave)), {"FINISHED"})
        self.assertEqual(georef.file_project_uids(), {self.uid})
        self.assertNotOffered()
        shutil.copyfile(self.view, temp / self.locate.RECOVERY_FILE)
        with self.interface(), blender_ext.loading():
            self.assertEqual(bpy.ops.wm.recover_last_session(), {"FINISHED"})
        self.assertEqual(georef.file_project_uids(), {self.uid})
        self.assertNotOffered()

        # Copias de respaldo del proyecto (la primera, cargada; las demás, la misma llamada).
        checkout = vf.extension("core.project.checkout")
        migrations = vf.extension("core.project.migrations")
        copies = []
        for folder in (checkout.previous_path(data.root), migrations.backup_path(data.root, 1),
                       checkout.publishing_path(data.root)):
            copy = folder / "scenes" / "principal.blend"
            copy.parent.mkdir(parents=True)
            shutil.copyfile(self.view, copy)
            copies.append(copy)
        self.assertIsNone(self.offered(copies[0]))
        self.assertNotOffered()
        georefs = georef.file_georeferences()
        with self.interface():
            for copy in copies[1:]:
                with self.subTest(copia=copy.parent.parent.name):
                    self.assertFalse(link.offer_after_load(str(copy), georefs))
                    self.assertNotOffered()

    def test_opening_its_project_brings_the_view_up_to_date(self) -> None:
        """RF-010-03, RF-010-04, RF-002-29, HU-010-2 (009/T42; regresión de la vuelta en
        pantalla del 23/10): una vista cargada sin su proyecto abierto queda desfasada con el
        aviso de «no está abierto» (RF-002-29). Abrir después su proyecto con la georreferencia
        que guardan sus escenas (la misma identidad, el mismo CRS y el mismo GeoOrigin), con la
        orden de la oferta y con «Abrir proyecto…» de la 002, quita la marca de vista desfasada
        y ese aviso: el panel Proyecto ya no dice «La vista está desfasada…» ni lo enseña; los
        demás avisos siguen. Con otro GeoOrigin en la vista, o abriendo otro proyecto con la
        misma ventana, la marca y su aviso siguen (RF-002-29). Una vista que ya estaba
        desfasada al guardarse lo sigue al abrir su proyecto (por otro motivo: lo cargado antes
        de la 010 no anota su GeoOrigin, RF-010-01); su aviso de «no está abierto», no."""
        data, ps = self.data, self.ps
        panel = vf.extension("bl.ui.core_panel").GEOBLENDER_PT_core_project
        not_open = "que no está abierto"
        other = "Otro aviso de la sesión"
        data.close()
        ps.take_notices()
        ps.notify(other)

        def stale() -> list[bool]:
            return [scene.geoblender.view_stale for scene in bpy.data.scenes]

        def loaded(path: Path) -> str:
            """Carga ``path`` sin proyecto abierto (``blender -b``): la vista desfasada y su
            aviso de «no está abierto»."""
            ps.close()
            blender_ext.load_file(path)
            notice = ps.notices()[-1]
            self.assertIn(not_open, notice)
            self.assertTrue(all(stale()))
            return notice

        def reopened() -> Any:
            """El proyecto de la vista abierto como lo deja «Abrir proyecto…» (``attach``)."""
            opened = self.core.open_project(data.root, ps.session(), ps.userdata()).project
            ps.attach(opened)
            return opened

        # La orden de la oferta.
        offer = self.offered(self.view)
        self.assertIn(not_open, offer.notice)
        self.assertEqual(ps.notices(), (other, offer.notice))
        self.assertTrue(all(stale()))
        self.accept(offer)
        self.assertEqual(self.finish_opening().uid, self.uid)
        self.assertEqual(stale(), [False] * len(bpy.data.scenes))
        self.assertEqual(ps.notices(), (other,))
        shown = _text(draw(panel, bpy.context))
        self.assertNotIn(VIEW_STALE, shown)
        self.assertNotIn(not_open, shown)

        # «Abrir proyecto…» (002) con el mismo proyecto.
        loaded(self.view)
        self.assertEqual(bpy.ops.geoblender.core_open_project(
            "EXEC_DEFAULT", directory=str(data.root)), {"RUNNING_MODAL"})
        self.assertEqual(self.finish_opening().uid, self.uid)
        self.assertEqual(stale(), [False] * len(bpy.data.scenes))
        self.assertEqual(ps.notices(), (other,))

        # Otro GeoOrigin en la vista: siguen.
        ps.close()
        for scene in bpy.data.scenes:
            scene.geoblender.origin_x += 100
            scene.geoblender.view_stale = False
        moved = self.view.with_name("otro_origen.blend")
        self.save(moved)
        notice = loaded(moved)
        reopened()
        self.assertTrue(all(stale()))
        self.assertEqual(ps.notices(), (other, notice))
        shown = _text(draw(panel, bpy.context))
        self.assertIn(VIEW_STALE, shown)
        self.assertIn(_flat(notice), shown)
        ps.take_notices()
        ps.notify(other)

        # Otro proyecto (la misma ventana, otra identidad): siguen.
        notice = loaded(self.view)
        parent = self.folder / "otros"
        parent.mkdir()
        settings = self.core.ProjectSettings(**settings_values(name="Cantera Otra",
                                                               window=vf.WINDOW))
        another = self.core.create_project(parent, settings, ps.session(),
                                           ps.userdata()).project
        ps.attach(another)
        self.assertTrue(all(stale()))
        self.assertEqual(ps.notices(), (other, notice))
        ps.take_notices()
        ps.notify(other)

        # Ya desfasada al guardarla (sin proyecto, se guarda con la marca): la marca sigue.
        loaded(self.view)
        saved_stale = self.view.with_name("desfasada.blend")
        self.save(saved_stale)
        ps.take_notices()
        ps.notify(other)
        loaded(saved_stale)
        reopened()
        self.assertTrue(all(stale()))
        self.assertEqual(ps.notices(), (other,))


if __name__ == "__main__":
    unittest.main()

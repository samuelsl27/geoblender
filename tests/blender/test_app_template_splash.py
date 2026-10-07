# SPDX-License-Identifier: GPL-3.0-or-later
"""La imagen de bienvenida con la plantilla de aplicación (spec 003, T44; RF-003-25; CW §7;
hallazgo D5 de la comprobación en pantalla).

Al arrancar con ``--app-template Geoblender``, Blender abre la imagen de bienvenida (con la
de la plantilla) antes del primer ciclo de eventos, en la ventana con el «Layout» del
``startup.blend``; en ese primer ciclo, la plantilla pide el espacio principal y Blender, al
aplicar el cambio de espacio (``ND_WORKSPACE_SET``), cierra las ventanas emergentes de la
ventana: la imagen de bienvenida no llegaba a verse. Ahora la plantilla:

- mientras arranca, anota en qué ventanas se dibuja la imagen de bienvenida (un añadido a
  ``WM_MT_splash`` y a ``WM_MT_splash_quick_setup`` que no dibuja nada), y lo quita en su
  primer ciclo (o al quitarse);
- si pasa al espacio principal una ventana donde estaba abierta, la vuelve a abrir en
  cuanto el cambio se ha aplicado (un temporizador que espera a que la ventana esté en un
  espacio de Geoblender, con un límite de ciclos);
- si Blender no la abrió (la preferencia apagada, un fichero abierto, sin interfaz) o la
  ventana no cambia, no abre nada; si no la puede abrir, lo dice y no insiste.

Con un fichero de la persona (``Geoblender.cmd fichero.blend``: T47, hallazgo de la
verificación de la segunda ronda), Blender lo abre después de registrar la plantilla y antes
del primer ciclo de eventos, y no abre la imagen de bienvenida. Antes, el temporizador del
arranque se perdía al abrirlo (no era ``persistent``) y la anotación se quedaba añadida a
``WM_MT_splash`` toda la sesión. Ahora su ``load_post`` anula lo que quedaba del arranque
(el temporizador, lo pedido y la anotación): manda el fichero, y nada queda colgado. Si
antes del primer ciclo se vuelve a leer el fichero de inicio (sin fichero de la persona), el
temporizador sigue (``persistent``) y hace lo suyo.

Sin interfaz el cambio de espacio no se aplica y la imagen no se puede abrir: la apertura se
sustituye por una función anotada (``open_splash``) y el cambio aplicado, por ``is_marked``.
Que se vea es la comprobación con interfaz de las T44 y T47.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support.repo import ROOT

layout = importlib.import_module("gbtools.layout")

TEMPLATE = ROOT / layout.APP_TEMPLATE_RELPATH
SPLASH_MENUS = ("WM_MT_splash", "WM_MT_splash_quick_setup")


def load_template() -> ModuleType:
    """El ``__init__.py`` de la plantilla como un módulo nuevo (sin registrarlo)."""
    path = Path(TEMPLATE) / "__init__.py"
    spec = importlib.util.spec_from_file_location("gb_test_app_template", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def draw_functions(name: str) -> list[object]:
    draw = getattr(bpy.types, name).draw
    return list(getattr(draw, "_draw_funcs", None) or [draw])


class SplashTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.unload()
        blender_ext.load_file()
        blender_ext.enable()

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.load_file()
        blender_ext.unload()

    def setUp(self) -> None:
        blender_ext.load_file(TEMPLATE / "startup.blend")
        self.window = bpy.context.window_manager.windows[0]
        self.assertFalse(bool(self.window.workspace.geoblender_mode))  # «Layout»
        self.before = {name: draw_functions(name) for name in SPLASH_MENUS}
        self.template = load_template()
        self.template.register()
        self.addCleanup(self.template.unregister)
        self.opened: list[int] = []
        patcher = mock.patch.object(self.template, "open_splash",
                                    lambda window: self.opened.append(window.as_pointer()))
        patcher.start()
        self.addCleanup(patcher.stop)

    def note_splash(self, window: object) -> None:
        """Lo que hace Blender al dibujar la imagen de bienvenida: llamar a los añadidos
        de su menú con el contexto de la ventana."""
        for name in SPLASH_MENUS:
            self.assertIn(self.template._note_splash, draw_functions(name))
        self.template._note_splash(None, SimpleNamespace(window=window))

    def test_register_watches_splash_and_unregister_restores(self) -> None:
        """RF-003-25: registrar la plantilla añade la anotación a los dos menús de la
        imagen de bienvenida; quitarla los deja como estaban, sin temporizadores."""
        for name in SPLASH_MENUS:
            self.assertIn(self.template._note_splash, draw_functions(name))
        self.template.unregister()
        for name in SPLASH_MENUS:
            self.assertEqual(draw_functions(name), self.before[name])
        self.assertFalse(bpy.app.timers.is_registered(self.template._startup))
        self.assertFalse(bpy.app.timers.is_registered(self.template._reopen_splash))

    def test_startup_reopens_splash_closed_by_switch(self) -> None:
        """RF-003-25 (hallazgo D5): con la imagen abierta en la ventana que pasa al espacio
        principal, la plantilla la vuelve a abrir cuando el cambio se ha aplicado, una
        vez; deja de anotar en su primer ciclo."""
        pointer = self.window.as_pointer()
        self.note_splash(self.window)
        self.template._startup()
        self.assertEqual(self.template._STATE.requested, [self.template.MAIN_WORKSPACE])
        for name in SPLASH_MENUS:
            self.assertEqual(draw_functions(name), self.before[name])
        self.assertTrue(bpy.app.timers.is_registered(self.template._reopen_splash))
        self.assertEqual(self.template._STATE.reopen, [pointer])

        # Sin interfaz el cambio no se aplica: espera, sin abrir nada.
        self.assertEqual(self.template._reopen_splash(), 0.0)
        self.assertEqual(self.opened, [])
        # Aplicado el cambio (la ventana ya está en un espacio de Geoblender): la abre.
        with mock.patch.object(self.template, "is_marked", return_value=True):
            self.assertIsNone(self.template._reopen_splash())
        self.assertEqual(self.opened, [pointer])
        self.assertEqual(self.template._STATE.reopen, [])

    def test_reopen_gives_up(self) -> None:
        """Si el cambio de espacio no llega a aplicarse, deja de esperar al cabo de
        ``SPLASH_WAIT_CYCLES`` ciclos sin abrir nada."""
        self.note_splash(self.window)
        self.template._startup()
        results = [self.template._reopen_splash()
                   for _ in range(self.template.SPLASH_WAIT_CYCLES)]
        self.assertEqual(results[:-1], [0.0] * (self.template.SPLASH_WAIT_CYCLES - 1))
        self.assertIsNone(results[-1])
        self.assertEqual(self.opened, [])
        self.assertEqual(self.template._STATE.reopen, [])

    def test_reopen_failure_does_not_raise(self) -> None:
        """Si Blender no deja abrirla (el operador falla), lo dice y no insiste."""
        self.note_splash(self.window)
        self.template._startup()

        def fail(_window: object) -> None:
            raise RuntimeError("sin ventana activa")

        with mock.patch.object(self.template, "open_splash", fail), \
                mock.patch.object(self.template, "is_marked", return_value=True):
            self.assertIsNone(self.template._reopen_splash())
        self.assertEqual(self.template._STATE.reopen, [])

    def test_no_splash_no_reopen(self) -> None:
        """Si Blender no abrió la imagen de bienvenida (la preferencia apagada, un fichero
        abierto, sin interfaz), la plantilla pasa la ventana al principal y no abre nada."""
        self.template._startup()
        self.assertEqual(self.template._STATE.requested, [self.template.MAIN_WORKSPACE])
        self.assertFalse(bpy.app.timers.is_registered(self.template._reopen_splash))
        for name in SPLASH_MENUS:
            self.assertEqual(draw_functions(name), self.before[name])

    def test_splash_in_another_window(self) -> None:
        """La imagen abierta en otra ventana, que no cambia de espacio, no se toca."""
        other = SimpleNamespace(as_pointer=lambda: self.window.as_pointer() + 1)
        self.note_splash(other)
        self.template._startup()
        self.assertFalse(bpy.app.timers.is_registered(self.template._reopen_splash))
        self.assertEqual(self.template._STATE.reopen, [])

    def test_note_splash_without_window(self) -> None:
        """Sin ventana en el contexto no anota nada ni falla."""
        self.template._note_splash(None, SimpleNamespace(window=None))
        self.template._note_splash(None, SimpleNamespace())
        self.template._startup()
        self.assertFalse(bpy.app.timers.is_registered(self.template._reopen_splash))

    def open_person_file(self) -> Path:
        """Guarda una copia del fichero abierto (el ``startup.blend`` de la plantilla, en
        «Layout» y con el espacio principal de Geoblender) y la abre como un fichero de la
        persona, igual que ``Geoblender.cmd fichero.blend``."""
        folder = Path(tempfile.mkdtemp(prefix="gb-plantilla-t47-"))
        self.addCleanup(shutil.rmtree, folder, True)
        path = folder / "persona.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(path), copy=True)
        blender_ext.load_file(path)
        self.assertEqual(Path(bpy.data.filepath), path)
        return path

    def assert_nothing_left(self) -> None:
        """Ni temporizadores ni anotación de la plantilla, y nada pendiente en su estado."""
        self.assertFalse(bpy.app.timers.is_registered(self.template._startup))
        self.assertFalse(bpy.app.timers.is_registered(self.template._reopen_splash))
        for name in SPLASH_MENUS:
            self.assertEqual(draw_functions(name), self.before[name])
        state = self.template._STATE
        self.assertEqual((state.requested, state.switched, state.splash_windows, state.reopen),
                         ([], [], set(), []))

    def test_person_file_cancels_startup(self) -> None:
        """RF-003-25 (T47): con un fichero de la persona, abierto tras registrar la plantilla
        y antes del primer ciclo (lo que hace ``Geoblender.cmd fichero.blend``), manda el
        fichero: se anula lo que quedaba del arranque (el temporizador, el espacio que pidió
        ``load_factory_startup_post`` al leer el fichero de inicio y la anotación de la
        imagen de bienvenida), la ventana sigue en el espacio del fichero y la extensión,
        habilitada."""
        self.template._on_factory_startup()  # Blender, al leer el fichero de inicio
        self.assertEqual(self.template._STATE.requested, [self.template.MAIN_WORKSPACE])
        self.open_person_file()
        self.assertEqual(bpy.context.window_manager.windows[0].workspace.name, "Layout")
        self.assert_nothing_left()
        self.assertTrue(self.template.find_extension() in bpy.context.preferences.addons)

    def test_person_file_cancels_reopen(self) -> None:
        """RF-003-25 (T47): si la persona abre un fichero mientras la plantilla espera para
        volver a abrir la imagen de bienvenida, ya no la abre ni queda nada esperando."""
        self.note_splash(self.window)
        self.template._startup()
        self.assertTrue(bpy.app.timers.is_registered(self.template._reopen_splash))
        self.open_person_file()
        self.assertEqual(self.opened, [])
        self.assert_nothing_left()

    def test_startup_survives_reading_the_startup_file(self) -> None:
        """RF-003-25 (T47): si antes del primer ciclo se vuelve a leer el fichero de inicio
        (sin fichero de la persona), el temporizador del arranque sigue (``persistent``) con
        la anotación puesta, y en su primer ciclo la quita: nada queda colgado."""
        blender_ext.load_file()  # el fichero de inicio: sin ruta
        self.assertEqual(bpy.data.filepath, "")
        self.assertTrue(bpy.app.timers.is_registered(self.template._startup))
        for name in SPLASH_MENUS:
            self.assertIn(self.template._note_splash, draw_functions(name))
        self.template._startup()
        for name in SPLASH_MENUS:
            self.assertEqual(draw_functions(name), self.before[name])


if __name__ == "__main__":
    unittest.main()

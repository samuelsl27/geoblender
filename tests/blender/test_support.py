# SPDX-License-Identifier: GPL-3.0-or-later
"""Las ayudas de las pruebas de la interfaz dentro de Blender (spec 003, T01).

- La instantánea de la interfaz (``tests.support.blender_ext.ui_snapshot``): en un
  Blender de fábrica, sin la extensión, dos tomas seguidas son iguales; un ``append`` o
  un ``prepend`` de prueba a una cabecera o a un menú aparece en la diferencia con su
  nombre y, al quitarlo, la instantánea vuelve a ser la de antes (RF-003-23).
- El *layout* simulado (``tests.support.fake_layout``) dibuja sin error la parte izquierda
  de la barra superior original de Blender, la que sustituye la 003, en sus dos ramas
  (menús desplegados o plegados; área maximizada) (RF-003-01, RF-003-04).
- Deshabilitar sin descargar (``tests.support.blender_ext.release``, spec 006, T48;
  RNF-001-01): las clases que no prueban el registro dejan la extensión deshabilitada con
  sus módulos importados, y la siguiente habilitación la registra otra vez sobre ellos sin
  importarla de nuevo.
- La extensión de cero mientras dura ``tests.support.blender_ext.fresh`` (spec 006, T59;
  RNF-001-01): las clases que prueban el registro la importan otra vez y, al terminar,
  devuelven los módulos de antes, sin que la siguiente tenga que importarla.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import sys
import unittest
from types import SimpleNamespace

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import UI_DRAW_TARGETS, fingerprint_diff, ui_snapshot
from tests.support.fake_layout import draw


# Lo que registra la extensión, en la huella (sin las funciones, que son otros objetos).
REGISTERED = ("types", "registered_classes", "properties", "addon_keymaps", "addons")


def _probe(self: object, context: object) -> None:
    """Función de dibujo de prueba: no dibuja nada."""


class UiSnapshotTest(unittest.TestCase):
    def assertSameSnapshot(self, before: dict[str, object]) -> None:
        after = ui_snapshot()
        if after != before:
            self.fail("\n".join(fingerprint_diff(before, after)))

    def test_two_snapshots_are_equal(self) -> None:
        """RF-003-23 (T01): dos instantáneas seguidas de un Blender de fábrica son iguales
        y recogen lo que toca la 003: ``draw_left`` de la barra superior, las cabeceras y
        menús de AR y PC, el mapa de complementos y los espacios de trabajo."""
        first = ui_snapshot()
        self.assertSameSnapshot(first)
        for key in ("topbar_draw_left", "draw_funcs", "addon_keymaps", "registered_classes",
                    "handlers", "timers", "workspaces", "window_workspaces"):
            self.assertIn(key, first)
        draw_funcs = first["draw_funcs"]
        assert isinstance(draw_funcs, dict)
        for name in UI_DRAW_TARGETS:
            self.assertIn(name, draw_funcs)
        self.assertIn("Layout", first["workspaces"])

    def test_detects_a_prepend_and_an_append(self) -> None:
        """RF-003-23 (T01): un ``prepend`` a la fila 2 de la Vista 3D y un ``append`` a la
        barra de estado salen en la diferencia, cada uno con su cabecera; al quitarlos,
        la instantánea es la de antes."""
        before = ui_snapshot()
        bpy.types.VIEW3D_HT_tool_header.prepend(_probe)
        bpy.types.STATUSBAR_HT_header.append(_probe)
        try:
            changed = fingerprint_diff(before, ui_snapshot())
        finally:
            bpy.types.VIEW3D_HT_tool_header.remove(_probe)
            bpy.types.STATUSBAR_HT_header.remove(_probe)
        self.assertEqual(len(changed), 2, changed)
        self.assertIn("draw_funcs[STATUSBAR_HT_header]", changed[0])
        self.assertIn("draw_funcs[VIEW3D_HT_tool_header]", changed[1])
        self.assertTrue(all("_probe" in line for line in changed), changed)
        self.assertSameSnapshot(before)


class ReleaseTest(unittest.TestCase):
    """Deshabilitar la extensión sin descargarla (spec 006, T48)."""

    def setUp(self) -> None:
        self.enterContext(blender_ext.fresh())  # de cero: sin la extensión cargada

    def assertBaseline(self) -> None:
        changes = fingerprint_diff(blender_ext.session_baseline(),
                                   blender_ext.state_fingerprint())
        if changes:
            self.fail("\n".join(changes))

    def test_release_keeps_the_modules_and_enable_registers_them_again(self) -> None:
        """RNF-001-01, RF-001-05 (spec 006, T48): tras ``release`` la extensión está
        deshabilitada y Blender queda como al principio de la sesión (la huella), con los
        mismos módulos en ``sys.modules``; ``enable`` la registra otra vez sobre ellos (el
        mismo objeto de cada módulo: no se vuelve a importar) con las mismas clases,
        propiedades, atajos y complementos que la primera vez. Repetir ``release``, o
        llamarlo sin la extensión cargada, no hace nada."""
        blender_ext.release()  # sin la extensión cargada
        self.assertEqual(blender_ext.loaded_modules(), [])
        root = blender_ext.enable()
        enabled = blender_ext.state_fingerprint()
        modules = {name: sys.modules[name] for name in blender_ext.loaded_modules()}
        self.assertIn(f"{blender_ext.module_name()}.bl.ops", modules)

        blender_ext.release()
        self.assertFalse(blender_ext.is_enabled())
        self.assertEqual(blender_ext.loaded_modules(), sorted(modules))
        self.assertBaseline()
        blender_ext.release()  # otra vez: nada
        self.assertFalse(blender_ext.is_enabled())

        self.assertIs(blender_ext.enable(), root)
        self.assertTrue(blender_ext.is_enabled())
        self.assertEqual({name: sys.modules[name] for name in blender_ext.loaded_modules()},
                         modules)
        again = blender_ext.state_fingerprint()
        for key in REGISTERED:  # las funciones de dibujo se crean de nuevo al registrar
            self.assertEqual(again[key], enabled[key], key)


class FreshTest(unittest.TestCase):
    """La extensión de cero mientras dura ``fresh`` (spec 006, T59): para las clases que
    prueban el registro, sin que la clase siguiente tenga que importarla otra vez."""

    def setUp(self) -> None:
        blender_ext.release()
        self.root = blender_ext.enable()  # los módulos que comparten las clases (release)
        blender_ext.release()
        self.addCleanup(blender_ext.release)
        self.shared = {name: sys.modules[name] for name in blender_ext.loaded_modules()}

    def assertShared(self) -> None:
        self.assertFalse(blender_ext.is_enabled())
        self.assertEqual({name: sys.modules[name] for name in blender_ext.loaded_modules()},
                         self.shared)
        parent, _, child = blender_ext.module_name().rpartition(".")
        self.assertIs(getattr(sys.modules[parent], child), self.root)
        changes = fingerprint_diff(blender_ext.session_baseline(),
                                   blender_ext.state_fingerprint())
        if changes:
            self.fail("\n".join(changes))

    def test_fresh_imports_anew_and_gives_back_the_shared_modules(self) -> None:
        """RNF-001-01, RF-001-05 (spec 006, T59): dentro de ``fresh`` la extensión está
        deshabilitada y fuera de ``sys.modules``, y habilitarla la importa de cero (otro
        módulo raíz); al salir, deshabilitada, sin lo importado dentro y con los módulos de
        antes (los mismos objetos, también en el paquete del repositorio), y Blender como al
        principio de la sesión; ``enable`` los registra otra vez sin importarlos."""
        with blender_ext.fresh():
            self.assertEqual(blender_ext.loaded_modules(), [])
            inner = blender_ext.enable()
            self.assertIsNot(inner, self.root)
            self.assertTrue(blender_ext.is_enabled())
        self.assertShared()
        self.assertIs(blender_ext.enable(), self.root)

    def test_fresh_also_when_the_body_fails(self) -> None:
        """RNF-001-01 (spec 006, T59): si lo de dentro falla, al salir queda igual; sin la
        extensión cargada al entrar, al salir no queda ningún módulo suyo, tampoco lo
        importado dentro."""
        with self.assertRaises(RuntimeError), blender_ext.fresh():
            raise RuntimeError("falla dentro")
        self.assertShared()
        with blender_ext.fresh():  # aparta los compartidos y los devuelve al final
            with blender_ext.fresh():  # sin la extensión cargada al entrar
                blender_ext.import_root()
                self.assertTrue(blender_ext.loaded_modules())
            self.assertEqual(blender_ext.loaded_modules(), [])
        self.assertShared()


class FakeLayoutBlenderTest(unittest.TestCase):
    def context(self, *, show_menus: bool, fullscreen: bool) -> SimpleNamespace:
        """Lo que el ``draw_left`` original lee del contexto: el área (``show_menus``), la
        pantalla (``show_fullscreen``) y la ventana."""
        return SimpleNamespace(
            area=SimpleNamespace(show_menus=show_menus),
            screen=SimpleNamespace(show_fullscreen=fullscreen, show_statusbar=True),
            window=bpy.context.window_manager.windows[0]
            if bpy.context.window_manager.windows
            else SimpleNamespace(),
        )

    def test_draws_the_original_topbar_left(self) -> None:
        """RF-003-01, RF-003-04 (T01): el *layout* simulado dibuja el ``draw_left`` de
        Blender: con los menús desplegados, su contenido y las pestañas de espacios de
        trabajo; con los menús plegados, el icono ≡; con el área maximizada, «Volver»."""
        topbar = bpy.types.TOPBAR_HT_upper_bar
        expanded = draw(topbar, self.context(show_menus=True, fullscreen=False),
                        method="draw_left")
        self.assertEqual(
            [(item.kind, item.target) for item in expanded.items],
            [("menu_contents", "TOPBAR_MT_editor_menus"), ("separator", ""),
             ("template_ID_tabs", "")],
        )
        collapsed = draw(topbar, self.context(show_menus=False, fullscreen=True),
                         method="draw_left")
        self.assertEqual(
            [(item.kind, item.target, item.icon) for item in collapsed.items],
            [("menu", "TOPBAR_MT_editor_menus", "COLLAPSEMENU"), ("separator", "", "NONE"),
             ("operator", "screen.back_to_previous", "SCREEN_BACK")],
        )


if __name__ == "__main__":
    unittest.main()

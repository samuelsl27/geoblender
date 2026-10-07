# SPDX-License-Identifier: GPL-3.0-or-later
"""Las ayudas de las pruebas de la interfaz dentro de Blender (spec 003, T01).

- La instantánea de la interfaz (``tests.support.blender_ext.ui_snapshot``): en un
  Blender de fábrica, sin la extensión, dos tomas seguidas son iguales; un ``append`` o
  un ``prepend`` de prueba a una cabecera o a un menú aparece en la diferencia con su
  nombre y, al quitarlo, la instantánea vuelve a ser la de antes (RF-003-23).
- El *layout* simulado (``tests.support.fake_layout``) dibuja sin error la parte izquierda
  de la barra superior original de Blender, la que sustituye la 003, en sus dos ramas
  (menús desplegados o plegados; área maximizada) (RF-003-01, RF-003-04).

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import unittest
from types import SimpleNamespace

import bpy

from tests.support.blender_ext import UI_DRAW_TARGETS, fingerprint_diff, ui_snapshot
from tests.support.fake_layout import draw


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

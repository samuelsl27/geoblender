# SPDX-License-Identifier: GPL-3.0-or-later
"""Barra superior con el *layout* simulado (spec 003, T12 y T13; BS §1, §3, §4, §8; CW §2,
§4 y §5).

- RF-003-01, RF-003-03: en modo Geoblender, el conmutador lo primero, con GB hundido, y
  después, en el orden de BS §1, Disposición ▾, ≡, los 11 menús del flujo, Herramientas,
  Ayuda y el acceso rápido del proyecto; con el área maximizada, también «Volver»;
  ``draw_right`` sin tocar.
- RF-003-04: en modo Blender, el conmutador con B hundido, «Geoblender ▾» y todas las
  llamadas del ``draw_left`` original.
- RF-003-06: los 11 menús del flujo empiezan con «Paso n de 11 · <etapa>»; los dibujos de
  los menús solo referencian operadores, menús y paneles registrados.
- RF-003-07, RF-003-08: lo no disponible, desactivado; con «Ocultar lo no disponible», fuera
  de los menús, pero los 13 menús de la barra siguen.
- RF-003-24: instalar dos veces no envuelve dos veces y restaurar devuelve el mismo objeto.
- RF-003-05 (T13): sin ``draw_left``, o con otra firma, el conmutador y «Geoblender ▾» se
  añaden tras la Ayuda de Blender, el aviso sale una vez y deshabilitar deja la instantánea
  idéntica.
- RF-003-02, RF-003-06, RF-003-07 (T41, hallazgo D1 de la convergencia): F3 recorre
  ``TOPBAR_MT_editor_menus`` aunque la barra no lo dibuje, con el área donde se pulsó;
  lo añadido allí dibuja «Geoblender ▾» con un área que no es la barra superior (o sin
  área) y nada en la barra ni en ≡, así que F3 llega a los 13 menús, a «Conmutar» y a lo
  no disponible en los dos modos; desde una Vista 3D en modo Blender, «Conmutar» pasa el
  ``poll`` y lo que tiene atajo de la Vista 3D sale desactivado con su explicación.
- RF-003-23, RF-003-24 (T41): ese añadido queda una sola vez tras habilitar, reparar (dos
  veces y tras una recarga del módulo) y conmutar, y deshabilitar lo quita; en el
  respaldo de compatibilidad no se pone (su función ya lleva «Geoblender ▾» a F3).

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from types import ModuleType, SimpleNamespace

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import fingerprint_diff, module_name, ui_snapshot
from tests.support.fake_layout import FakeLayout, Item, draw

TOGGLE = "geoblender.ui_toggle_mode"
VOLUME = "geoblender.res_compute_volume_between_surfaces"


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def context(*, geoblender: bool, fullscreen: bool = False,
            area: str | None = "TOPBAR") -> SimpleNamespace:
    """Lo que leen la barra y los menús: el espacio de trabajo (su marca), la pantalla,
    el área (por defecto, la barra superior; ``None``, sin área), la ventana y la
    escena."""
    return SimpleNamespace(
        workspace=SimpleNamespace(geoblender_mode=geoblender, use_filter_by_owner=False),
        screen=SimpleNamespace(show_fullscreen=fullscreen, show_statusbar=True),
        area=None if area is None else SimpleNamespace(show_menus=True, type=area),
        region=SimpleNamespace(alignment="LEFT", width=1920),
        window=bpy.context.window_manager.windows[0],
        scene=bpy.context.scene,
        space_data=None,
    )


def draw_topbar(ctx: SimpleNamespace) -> FakeLayout:
    return draw(bpy.types.TOPBAR_HT_upper_bar, ctx, method="draw_left")


def controls(layout: FakeLayout) -> list[tuple[str, str]]:
    """(tipo, destino) de los operadores, menús y ventanas emergentes, en orden."""
    kinds = ("operator", "menu", "popover", "menu_contents", "template_ID_tabs")
    return [(item.kind, item.target) for item in layout.items if item.kind in kinds]


class TopbarDrawTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        # En un diccionario: una función como atributo de la clase sería un método.
        cls.saved = {"draw_left": bpy.types.TOPBAR_HT_upper_bar.draw_left,
                     "draw_right": bpy.types.TOPBAR_HT_upper_bar.draw_right}
        blender_ext.enable()
        cls.cat = _module("core.catalog").load()
        cls.topbar = _module("bl.ui.topbar")
        cls.registry = _module("bl.ui.registry")

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.release()

    def preferences(self) -> object:
        return bpy.context.preferences.addons[module_name()].preferences.ui

    def label(self, key: str) -> str:
        return self.cat.commands[key].label_es

    def test_geoblender_mode_order(self) -> None:
        """RF-003-01, RF-003-03: en modo Geoblender, el orden de BS §1 con GB hundido y
        el bloque derecho sin tocar."""
        layout = draw_topbar(context(geoblender=True))
        first, second = [item for item in layout.items if item.target == TOGGLE]
        self.assertIs(layout.items[0], first)
        self.assertEqual((first.properties.target, first.options["depress"]),
                         ("GEOBLENDER", True))
        self.assertEqual((second.properties.target, second.options["depress"]),
                         ("BLENDER", False))
        top = list(self.cat.top_menus)
        quick = [("operator", "geoblender.core_save_project"), ("operator", "ed.undo"),
                 ("operator", "ed.redo"), ("menu", "GEOBLENDER_MT_core_data"),
                 ("operator", "geoblender.core_refresh"),
                 ("popover", "GEOBLENDER_PT_core_version")]
        expected = [("operator", TOGGLE), ("operator", TOGGLE),
                    ("popover", "GEOBLENDER_PT_ui_layouts"),
                    ("menu", "TOPBAR_MT_editor_menus"),
                    *[("menu", menu_id) for menu_id in top], *quick]
        self.assertEqual(controls(layout), expected)
        titles = [item.text for item in layout.items if item.target in top]
        self.assertEqual(titles, [self.label(menu_id) for menu_id in top])
        self.assertEqual(titles[0], "Proyecto")
        self.assertIs(bpy.types.TOPBAR_HT_upper_bar.draw_right, self.saved["draw_right"])
        self.assertNotIn("screen.back_to_previous", [t for _k, t in controls(layout)])

    def test_fullscreen_back(self) -> None:
        """CW §3.3: con el área maximizada, la barra dibuja también «Volver»."""
        layout = draw_topbar(context(geoblender=True, fullscreen=True))
        self.assertEqual(controls(layout)[-1], ("operator", "screen.back_to_previous"))

    def test_blender_mode(self) -> None:
        """RF-003-01, RF-003-04: en modo Blender, el conmutador con B hundido, «Geoblender
        ▾» y después exactamente lo que dibuja el original."""
        ctx = context(geoblender=False)
        layout = draw_topbar(ctx)
        first, second = layout.items[0], layout.items[1]
        self.assertEqual((first.target, first.options["depress"]), (TOGGLE, False))
        self.assertEqual((second.target, second.options["depress"]), (TOGGLE, True))
        self.assertEqual((layout.items[2].kind, layout.items[2].target),
                         ("menu", "GEOBLENDER_MT_ui_geoblender"))
        blender = SimpleNamespace(draw_left=self.saved["draw_left"])
        original = draw(blender, ctx, method="draw_left")
        tail = [(i.kind, i.target, i.text, i.icon) for i in layout.items[3:]]
        self.assertEqual(tail, [(i.kind, i.target, i.text, i.icon) for i in original.items])
        self.assertIn(("template_ID_tabs", ""), controls(layout))

    def test_flow_menus_step_line(self) -> None:
        """RF-003-06: los 11 menús del flujo empiezan con la línea no pulsable «Paso n de
        11 · <etapa>»; Herramientas y Ayuda, no."""
        flow = 0
        for menu_id in self.cat.top_menus:
            spec = self.cat.menus[menu_id]
            layout = draw(getattr(bpy.types, menu_id), context(geoblender=True))
            first = layout.items[0]
            if spec.step is None:
                self.assertFalse(first.text.startswith("Paso "), menu_id)
                continue
            flow += 1
            self.assertEqual(first.kind, "label")
            self.assertEqual(first.text, f"Paso {spec.step} de 11 · {spec.stage_es}")
            self.assertFalse(first.active, menu_id)
        self.assertEqual(flow, 11)

    def test_menus_reference_registered_classes(self) -> None:
        """RF-003-06 (BS §7.2, prueba 5): todo lo que dibujan los menús generados existe:
        operadores, menús y paneles registrados."""
        menus = [cls for cls in self.registry.own_classes() if issubclass(cls, bpy.types.Menu)]
        self.assertGreater(len(menus), 60)
        checked = 0
        for cls in menus:
            for item in draw(cls, context(geoblender=True)).items:
                if item.kind not in ("operator", "menu", "popover"):
                    continue
                checked += 1
                self.assertTrue(_exists(item), f"{cls.bl_idname}: {item.kind} {item.target}")
        self.assertGreater(checked, 400)

    def test_unavailable_disabled_and_hidden(self) -> None:
        """RF-003-07, RF-003-08: lo no disponible se dibuja desactivado; con «Ocultar lo no
        disponible» no se dibuja dentro de los menús, y los 13 menús de la barra siguen."""
        volumetrics = bpy.types.GEOBLENDER_MT_ui_volumetrics
        items = [i for i in draw(volumetrics, context(geoblender=True)).items
                 if i.target == VOLUME]
        self.assertEqual([i.enabled for i in items], [False])
        save = [i for i in draw(bpy.types.GEOBLENDER_MT_ui_project, context(geoblender=True)).items
                if i.target == "geoblender.core_save_project"]
        self.assertEqual([i.enabled for i in save], [True])
        preferences = self.preferences()
        preferences.hide_unavailable = True
        try:
            hidden = draw(volumetrics, context(geoblender=True))
            self.assertNotIn(VOLUME, [i.target for i in hidden.items])
            bar = draw_topbar(context(geoblender=True))
            shown = [t for _k, t in controls(bar) if t in self.cat.top_menus]
            self.assertEqual(shown, list(self.cat.top_menus))
        finally:
            preferences.hide_unavailable = False

    def test_icons_level(self) -> None:
        """BS §3 (nivel D con la preferencia «Iconos»): los 11 menús del flujo, Herramientas
        y Ayuda sin título, con su icono de reserva."""
        preferences = self.preferences()
        preferences.topbar_titles = "ICONS"
        try:
            layout = draw_topbar(context(geoblender=True))
        finally:
            preferences.topbar_titles = "AUTO"
        menus = [i for i in layout.items if i.target in self.cat.top_menus]
        self.assertEqual(len(menus), 13)
        self.assertTrue(all(i.text == "" and i.icon != "NONE" for i in menus))

    def test_patchable_in_this_version(self) -> None:
        """RF-003-05 (prueba por versión, ADR-0012): la barra de la versión instalada tiene
        la forma que se sustituye, y la interfaz no está en modo de compatibilidad."""
        compat = _module("bl.compat")
        self.assertTrue(compat.topbar_patchable())
        self.assertEqual(self.topbar.mode(), "patched")

    def test_install_twice_and_restore(self) -> None:
        """RF-003-24: instalar otra vez no envuelve dos veces; restaurar devuelve el mismo
        objeto original; volver a instalar lo deja como estaba."""
        header = bpy.types.TOPBAR_HT_upper_bar
        wrapper = header.draw_left
        self.assertIsNot(wrapper, self.saved["draw_left"])
        self.assertIs(self.topbar.original_of(wrapper), self.saved["draw_left"])
        self.topbar.install()
        self.assertIs(header.draw_left, wrapper)
        self.topbar.restore()
        self.assertIs(header.draw_left, self.saved["draw_left"])
        self.topbar.install()
        self.assertIs(self.topbar.original_of(header.draw_left), self.saved["draw_left"])
        self.assertTrue(self.topbar.is_installed())

    def test_search_menu_outside_topbar(self) -> None:
        """RF-003-02, RF-003-06 (T41): lo añadido a ``TOPBAR_MT_editor_menus`` no dibuja
        nada con el área de la barra superior (la barra en modo Blender y ≡, que se abre
        desde ella) y dibuja «Geoblender ▾», con su título del catálogo, con cualquier
        otra área o sin área (F3), en los dos modos."""
        menus = bpy.types.TOPBAR_MT_editor_menus
        for geoblender in (False, True):
            layout = draw(menus, context(geoblender=geoblender))
            self.assertEqual(after_blender_help(layout), [], geoblender)
            for area in ("VIEW_3D", "OUTLINER", None):
                layout = draw(menus, context(geoblender=geoblender, area=area))
                added = after_blender_help(layout)
                self.assertEqual(added, [("menu", "GEOBLENDER_MT_ui_geoblender")],
                                 (geoblender, area))
                item = layout.items[-1]
                self.assertEqual(item.text, self.label("GEOBLENDER_MT_ui_geoblender"))
                self.assertIs(item.options.get("translate"), False)

    def test_search_reaches_every_menu(self) -> None:
        """RF-003-02, RF-003-06, RF-003-07 (T41, D1): recorriendo los menús desde
        ``TOPBAR_MT_editor_menus`` como F3 (con el área de una Vista 3D) se llega en los
        dos modos a los 13 menús de la barra, a «Conmutar Geoblender ⇄ Blender» y a
        «Cubicar» (no disponible, desactivado); con el área de la barra superior, a
        ninguno de Geoblender."""
        for geoblender in (False, True):
            reached, operators = walk_search(context(geoblender=geoblender, area="VIEW_3D"))
            self.assertLessEqual(set(self.cat.top_menus), reached, geoblender)
            self.assertIn(True, operators[TOGGLE], geoblender)
            self.assertEqual(operators[VOLUME], {False}, geoblender)
            self.assertGreater(len(operators), 300)
            reached, operators = walk_search(context(geoblender=geoblender))
            self.assertEqual((reached, operators), (set(), {}), geoblender)

    def test_search_from_view3d_in_blender_mode(self) -> None:
        """RF-003-02, RF-003-19 (T41; spec §8, «Modo Blender, F3 lanzado sobre la Vista
        3D»): con el contexto de una Vista 3D de una ventana en modo Blender, que es el
        de F3 pulsado sobre ella, «Conmutar» pasa el ``poll`` y un comando con atajo de
        la Vista 3D (Encuadrar la ventana de trabajo) no, con «Solo en modo Geoblender
        (Ctrl+F10) o desde Geoblender ▾»."""
        window = bpy.context.window_manager.windows[0]
        area = next(a for a in window.screen.areas if a.type == "VIEW_3D")
        region = next(r for r in area.regions if r.type == "WINDOW")
        self.assertFalse(window.workspace.geoblender_mode)
        with bpy.context.temp_override(window=window, area=area, region=region):
            self.assertTrue(bpy.ops.geoblender.ui_toggle_mode.poll())
            self.assertFalse(bpy.ops.geoblender.ui_frame_work_window.poll())
            with self.assertRaisesRegex(RuntimeError, r"Solo en modo Geoblender \(Ctrl\+F10\)"):
                bpy.ops.geoblender.ui_frame_work_window()


class TopbarSearchCycleTest(unittest.TestCase):
    """Lo añadido para F3 a lo largo del ciclo de la extensión (RF-003-23, RF-003-24; T41)."""

    def setUp(self) -> None:
        self.enterContext(blender_ext.fresh())
        blender_ext.load_file()
        self.addCleanup(blender_ext.load_file)

    def count(self, topbar: ModuleType) -> int:
        functions = getattr(bpy.types.TOPBAR_MT_editor_menus.draw, "_draw_funcs", ())
        return sum(1 for function in functions if topbar.is_search_function(function))

    def test_once_and_removed(self) -> None:
        """RF-003-23, RF-003-24: una sola vez tras habilitar, instalar otra vez, reparar
        dos veces, conmutar ida y vuelta y recargar el módulo y reparar (la del módulo
        anterior se quita); deshabilitar la quita y deja la instantánea como antes."""
        before = ui_snapshot()
        blender_ext.enable()
        topbar = _module("bl.ui.topbar")
        self.assertEqual(self.count(topbar), 1)
        topbar.install()
        self.assertEqual(self.count(topbar), 1)
        for _ in range(2):
            self.assertEqual(bpy.ops.geoblender.ui_repair_interface(), {"FINISHED"})
        self.assertEqual(self.count(topbar), 1)
        for target in ("GEOBLENDER", "BLENDER", "TOGGLE"):
            bpy.ops.geoblender.ui_toggle_mode(target=target)  # sin interfaz, cambio diferido
        self.assertEqual(self.count(topbar), 1)
        old = [f for f in bpy.types.TOPBAR_MT_editor_menus.draw._draw_funcs
               if topbar.is_search_function(f)]
        topbar = importlib.reload(topbar)
        self.assertEqual(bpy.ops.geoblender.ui_repair_interface(), {"FINISHED"})
        self.assertEqual(self.count(topbar), 1)
        self.assertNotIn(old[0], bpy.types.TOPBAR_MT_editor_menus.draw._draw_funcs)
        blender_ext.disable()
        self.assertEqual(self.count(topbar), 0)
        changes = [line for line in fingerprint_diff(before, ui_snapshot())
                   if not line.startswith("workspaces:")]
        self.assertEqual(changes, [])


class TopbarCompatTest(unittest.TestCase):
    """Respaldo de compatibilidad (RF-003-05; ADR-0012, técnica A; CW §5)."""

    def setUp(self) -> None:
        self.enterContext(blender_ext.fresh())
        self.header = bpy.types.TOPBAR_HT_upper_bar
        self.saved = {"draw_left": self.header.__dict__["draw_left"]}

    def restore_header(self) -> None:
        self.header.draw_left = self.saved["draw_left"]

    def test_missing_draw_left(self) -> None:
        """RF-003-05: una barra sin ``draw_left`` usa el respaldo."""
        del self.header.draw_left
        self.addCleanup(self.restore_header)
        self.assertCompat()

    def test_other_signature(self) -> None:
        """RF-003-05: un ``draw_left`` con otra firma usa el respaldo."""

        def draw_left(self: object, context: object, extra: object) -> None:
            """Una versión de Blender con otra firma."""

        self.header.draw_left = draw_left
        self.addCleanup(self.restore_header)
        self.assertCompat()

    def assertCompat(self) -> None:
        before = ui_snapshot()
        blender_ext.enable()
        topbar = _module("bl.ui.topbar")
        session = _module("bl.scene.project_session")
        self.assertEqual(topbar.mode(), "compat")
        menus = bpy.types.TOPBAR_MT_editor_menus
        for geoblender in (False, True):
            layout = draw(menus, context(geoblender=geoblender))
            targets = controls(layout)
            after_help = targets[targets.index(("menu", "TOPBAR_MT_help")) + 1:]
            self.assertEqual(after_help, [("operator", TOGGLE), ("operator", TOGGLE),
                                          ("menu", "GEOBLENDER_MT_ui_geoblender")])
            switch = [i for i in layout.items if i.target == TOGGLE]
            self.assertEqual([i.options["depress"] for i in switch], [geoblender, not geoblender])
        notice = "Interfaz de Geoblender en modo de compatibilidad"
        self.assertEqual(session.notices().count(notice), 1)
        topbar.install()
        functions = getattr(menus.draw, "_draw_funcs", [])
        self.assertEqual(sum(1 for f in functions if topbar.is_compat_function(f)), 1)
        # T41: la función del respaldo ya lleva «Geoblender ▾» a F3; la de F3 no se pone.
        self.assertFalse(any(topbar.is_search_function(f) for f in functions))
        targets = controls(draw(menus, context(geoblender=False, area="VIEW_3D")))
        self.assertEqual(targets.count(("menu", "GEOBLENDER_MT_ui_geoblender")), 1)
        self.assertEqual(session.notices().count(notice), 1)
        blender_ext.disable()
        after = ui_snapshot()
        if after != before:
            self.fail("\n".join(fingerprint_diff(before, after)))


def after_blender_help(layout: FakeLayout) -> list[tuple[str, str]]:
    """Lo dibujado en ``TOPBAR_MT_editor_menus`` tras la Ayuda de Blender."""
    targets = controls(layout)
    return targets[targets.index(("menu", "TOPBAR_MT_help")) + 1:]


def walk_search(ctx: SimpleNamespace) -> tuple[set[str], dict[str, set[bool]]]:
    """Recorre los menús de Geoblender que se alcanzan desde ``TOPBAR_MT_editor_menus``
    con ``ctx``, como F3 (cada menú una vez; los de Blender no se abren): los menús
    alcanzados y, por operador, si se dibujó habilitado."""
    reached: set[str] = set()
    operators: dict[str, set[bool]] = {}
    pending = ["TOPBAR_MT_editor_menus"]
    while pending:
        layout = draw(getattr(bpy.types, pending.pop()), ctx)
        for item in layout.items:
            if item.kind == "operator":
                operators.setdefault(item.target, set()).add(item.enabled)
            elif (item.kind == "menu" and item.target.startswith("GEOBLENDER_MT_")
                  and item.target not in reached):
                reached.add(item.target)
                pending.append(item.target)
    operators = {key: value for key, value in operators.items()
                 if key.startswith("geoblender.")}
    return reached, operators


def _exists(item: Item) -> bool:
    if item.kind == "operator":
        module, _, name = item.target.partition(".")
        try:
            getattr(getattr(bpy.ops, module), name).get_rna_type()
        except (AttributeError, KeyError):
            return False
        return True
    cls = getattr(bpy.types, item.target, None)
    return isinstance(cls, type) and (not hasattr(cls, "is_registered") or cls.is_registered)


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: GPL-3.0-or-later
"""Registro de la extensión dentro de Blender (plan 001 §5.4.9).

- RF-001-04: importar la extensión sin habilitarla no carga ``bl``; habilitarla lo carga
  sin errores.
- RF-001-05: deshabilitarla deja la huella del estado de Blender idéntica a la de antes
  de habilitarla, también si el desregistro se repite o llega sin registro previo; ``bl``
  registra sus subpaquetes en orden fijo y los desregistra en el inverso, una sola vez.
  La referencia es la huella del principio de la sesión de pruebas
  (``blender_ext.session_baseline()``, que toma el lanzador antes de cualquier prueba):
  una tomada a mitad de sesión, después de que otra prueba habilitara la extensión,
  incluiría una fuga que se repite igual en cada habilitación (convergencia, T36). Las
  funciones de la huella se comparan por el objeto: una envoltura con
  ``functools.wraps`` tiene el nombre de la original (convergencia, T40).
- Contrato 1 del plan (§5.3): ``bl.ADDON_PACKAGE`` es el paquete raíz, de 3 componentes.

Se ejecuta con ``tools/run_blender_tests.py``, que instala la copia de pruebas.
"""

import functools
import importlib
import sys
import unittest
from collections.abc import Callable
from types import ModuleType
from unittest import mock

import bpy
import bpy.utils.previews

from tests.support import blender_ext
from tests.support.blender_ext import fingerprint_diff, module_name, state_fingerprint

# Orden de registro fijado por el plan 001 (§5.3, contrato 2).
EXPECTED_SUBPACKAGES = ("props", "scene", "draw", "gn", "ops", "ui")


class RegistrationTestCase(unittest.TestCase):
    """Cada prueba parte de la extensión deshabilitada y fuera de ``sys.modules``."""

    def setUp(self) -> None:
        blender_ext.unload()
        self.addCleanup(blender_ext.unload)

    def bl_name(self) -> str:
        return module_name() + ".bl"

    def assertSameFingerprint(self, before: dict[str, object]) -> None:
        # Sin assertEqual: su diferencia de dos diccionarios con miles de tipos tarda
        # segundos y no dice más que fingerprint_diff.
        after = state_fingerprint()
        if after != before:
            self.fail(
                "la huella del estado de Blender cambió:\n"
                + "\n".join(fingerprint_diff(before, after))
            )

    def import_bl(self) -> ModuleType:
        """Importa ``bl`` sin habilitar la extensión (para probar su registro)."""
        blender_ext.import_root()
        return importlib.import_module(self.bl_name())

    def record_subpackages(self, bl: ModuleType) -> list[tuple[str, str]]:
        """Sustituye ``register``/``unregister`` de cada subpaquete por registradores."""
        calls: list[tuple[str, str]] = []
        for name in EXPECTED_SUBPACKAGES:
            module = importlib.import_module(f"{bl.__name__}.{name}")
            for action in ("register", "unregister"):
                recorder = mock.Mock(
                    side_effect=lambda n=name, a=action: calls.append((n, a))
                )
                patcher = mock.patch.object(module, action, recorder, create=True)
                patcher.start()
                self.addCleanup(patcher.stop)
        return calls


class RegistrationTest(RegistrationTestCase):
    def test_bl_not_imported_before_enable(self) -> None:
        """RF-001-04: importar la extensión sin habilitarla no carga ``bl``."""
        root = blender_ext.import_root()
        self.assertEqual(root.__name__, module_name())
        self.assertTrue(callable(root.register))
        self.assertNotIn(self.bl_name(), sys.modules)
        self.assertFalse(blender_ext.is_enabled())

    def test_enable_without_errors(self) -> None:
        """RF-001-04: habilitarla no da errores, carga ``bl`` y queda habilitada."""
        root = blender_ext.enable()
        self.assertEqual(root.__name__, module_name())
        self.assertIn(self.bl_name(), sys.modules)
        self.assertTrue(blender_ext.is_enabled())
        self.assertIn(module_name(), bpy.context.preferences.addons)

    def test_disable_restores_fingerprint(self) -> None:
        """RF-001-05: habilitar y deshabilitar deja la huella de Blender idéntica a la
        del principio de la sesión de pruebas, antes de que ninguna prueba habilitara la
        extensión (CE-001-04)."""
        blender_ext.enable()
        blender_ext.disable()
        self.assertFalse(blender_ext.is_enabled())
        self.assertNotIn(module_name(), bpy.context.preferences.addons)
        self.assertSameFingerprint(blender_ext.session_baseline())

    def test_subpackages_registered_in_order(self) -> None:
        """RF-001-05: ``bl.register()`` registra los subpaquetes en el orden fijo y
        ``bl.unregister()`` los desregistra en el inverso; repetir cualquiera de los dos
        no vuelve a llamarlos."""
        bl = self.import_bl()
        self.assertEqual(tuple(getattr(bl, "SUBPACKAGES", ())), EXPECTED_SUBPACKAGES)
        calls = self.record_subpackages(bl)
        bl.register()
        bl.register()
        self.assertEqual(calls, [(name, "register") for name in EXPECTED_SUBPACKAGES])
        calls.clear()
        bl.unregister()
        bl.unregister()
        self.assertEqual(
            calls, [(name, "unregister") for name in reversed(EXPECTED_SUBPACKAGES)]
        )

    def test_unregister_twice(self) -> None:
        """RF-001-05: un segundo desregistro no llama a los subpaquetes, no lanza
        excepciones y deja la huella igual a la del principio de la sesión."""
        blender_ext.enable()
        blender_ext.disable()
        root = sys.modules[module_name()]
        root.unregister()  # segundo desregistro, ya sin registro
        self.assertSameFingerprint(blender_ext.session_baseline())

        bl = self.import_bl()
        calls = self.record_subpackages(bl)
        bl.register()
        calls.clear()
        bl.unregister()
        bl.unregister()
        self.assertEqual(
            calls, [(name, "unregister") for name in reversed(EXPECTED_SUBPACKAGES)]
        )

    def test_unregister_without_register(self) -> None:
        """RF-001-05: importar de nuevo y desregistrar sin registro previo no lanza
        excepciones ni cambia la huella del principio de la sesión."""
        root = blender_ext.import_root()
        root.unregister()
        root.unregister()
        self.assertSameFingerprint(blender_ext.session_baseline())

    def test_bl_subpackages_import(self) -> None:
        """RF-001-03: dentro de Blender se importan los seis subpaquetes de ``bl``,
        ``bl.compat`` y ``bl.registry``, cada subpaquete con su tupla ``classes`` y sus
        ``register``/``unregister``, sin habilitar la extensión."""
        bl = self.import_bl()
        for name in EXPECTED_SUBPACKAGES:
            with self.subTest(subpaquete=name):
                module = importlib.import_module(f"{bl.__name__}.{name}")
                self.assertIsInstance(module.classes, tuple)
                self.assertTrue(callable(module.register))
                self.assertTrue(callable(module.unregister))
                self.assertTrue(module.__doc__)
        compat = importlib.import_module(f"{bl.__name__}.compat")
        self.assertTrue(callable(compat.blender_version))
        registry = importlib.import_module(f"{bl.__name__}.registry")
        self.assertTrue(callable(registry.register_classes))
        self.assertFalse(blender_ext.is_enabled())

    def test_addon_package(self) -> None:
        """Contrato 1 (plan 001 §5.3): con la extensión habilitada,
        ``bl.ADDON_PACKAGE`` es el paquete raíz, de 3 componentes y acabado en
        ``.geoblender``."""
        blender_ext.enable()
        bl = sys.modules[self.bl_name()]
        package = getattr(bl, "ADDON_PACKAGE", None)
        self.assertEqual(package, module_name())
        self.assertEqual(len(package.split(".")), 3)
        self.assertTrue(package.endswith(".geoblender"))


class RegistryTest(RegistrationTestCase):
    def test_registry_tolerant(self) -> None:
        """RF-001-05: ``register_classes`` registra en orden y no repite;
        ``unregister_classes`` desregistra en orden inverso y omite las no registradas;
        si una clase falla al registrarse, deshace las anteriores."""
        blender_ext.import_root()
        registry = importlib.import_module(self.bl_name() + ".registry")

        class GBTEST_PG_first(bpy.types.PropertyGroup):
            pass

        class GBTEST_PG_second(bpy.types.PropertyGroup):
            pass

        class GBTEST_OT_broken(bpy.types.Operator):
            """Sin ``bl_idname`` ni ``bl_label``: Blender rechaza registrarla."""

        classes = (GBTEST_PG_first, GBTEST_PG_second)
        before = state_fingerprint()
        try:
            registry.register_classes(classes)
            registry.register_classes(classes)
            self.assertTrue(all(cls.is_registered for cls in classes))
            registry.unregister_classes(classes)
            registry.unregister_classes(classes)
            self.assertFalse(any(cls.is_registered for cls in classes))
            self.assertSameFingerprint(before)

            with self.assertRaises((AttributeError, RuntimeError, ValueError)):
                registry.register_classes((GBTEST_PG_first, GBTEST_OT_broken))
            self.assertFalse(GBTEST_PG_first.is_registered, "se deshace lo registrado")
            self.assertSameFingerprint(before)
        finally:
            for cls in (*classes, GBTEST_OT_broken):
                if cls.is_registered:
                    bpy.utils.unregister_class(cls)


class FingerprintTest(unittest.TestCase):
    def test_fingerprint_detects_changes(self) -> None:
        """RF-001-05: control positivo de la huella: cada cosa que una extensión puede
        dejar registrada la cambia (también un ``PropertyGroup``, que ``dir(bpy.types)``
        no lista, y ``draw_left``, un manejador o una función del menú sustituidos por
        una envoltura con ``functools.wraps``, que copia el módulo y el nombre de la
        original), y deshacerla la devuelve a su valor (CE-001-04; convergencia, T40):
        también un manejador de dibujo de un editor (``SpaceView3D``, ``SpaceImageEditor``)
        o del cursor, una colección de previews, una suscripción de msgbus, una
        preferencia de cada grupo, un complemento y una entrada de ``driver_namespace``
        (convergencia, T62)."""
        before = state_fingerprint()
        seen: dict[str, bool] = {}

        def change(
            key: str,
            do: Callable[[], object],
            undo: Callable[[], object],
            reference: dict[str, object] | None = None,
        ) -> None:
            """``do`` cambia la huella de ``reference`` (por defecto, la del principio
            de la prueba) y ``undo`` la devuelve a ella."""
            expected = before if reference is None else reference
            do()
            try:
                seen[key] = state_fingerprint() != expected
            finally:
                undo()
            after = state_fingerprint()
            if after != expected:
                self.fail(f"{key}: no se deshizo: {fingerprint_diff(expected, after)}")

        class GBTEST_PG_probe(bpy.types.PropertyGroup):
            pass

        class GBTEST_OT_probe(bpy.types.Operator):
            bl_idname = "gbtest.probe"
            bl_label = "Probe"

        for cls in (GBTEST_PG_probe, GBTEST_OT_probe):
            change(
                cls.__name__,
                lambda c=cls: bpy.utils.register_class(c),
                lambda c=cls: bpy.utils.unregister_class(c),
            )

        def add_property() -> None:
            bpy.types.Scene.gbtest_probe = bpy.props.IntProperty()

        def remove_property() -> None:
            del bpy.types.Scene.gbtest_probe

        change("Scene.gbtest_probe", add_property, remove_property)

        # Propiedades de cualquier tipo de Blender, no solo de los principales
        # (hallazgo F2: una que queda en Curve daba verde; convergencia, T49).
        for type_name in ("Curve", "Material", "ViewLayer"):
            owner = getattr(bpy.types, type_name)
            change(
                f"{type_name}.gbtest_probe",
                lambda o=owner: setattr(o, "gbtest_probe", bpy.props.IntProperty()),
                lambda o=owner: delattr(o, "gbtest_probe"),
            )

        def handler(*_args: object) -> None:
            pass

        handlers = bpy.app.handlers.load_post
        change(
            "load_post",
            lambda: handlers.append(handler),
            lambda: handlers.remove(handler),
        )

        # Con functools.wraps, la envoltura tiene el módulo y el nombre de la original:
        # la huella las distingue por el objeto (convergencia, T40).
        @functools.wraps(handler)
        def wrapped_handler(*args: object) -> None:
            handler(*args)

        handlers.append(handler)
        try:
            change(
                "load_post con functools.wraps",
                lambda: handlers.__setitem__(handlers.index(handler), wrapped_handler),
                lambda: handlers.__setitem__(handlers.index(wrapped_handler), handler),
                reference=state_fingerprint(),
            )
        finally:
            handlers.remove(handler)

        topbar = bpy.types.TOPBAR_HT_upper_bar
        original_draw_left = topbar.draw_left

        def draw_left(self: object, context: object) -> None:
            original_draw_left(self, context)

        change(
            "TOPBAR_HT_upper_bar.draw_left",
            lambda: setattr(topbar, "draw_left", draw_left),
            lambda: setattr(topbar, "draw_left", original_draw_left),
        )

        @functools.wraps(original_draw_left)
        def wrapped_draw_left(self: object, context: object) -> None:
            original_draw_left(self, context)

        change(
            "TOPBAR_HT_upper_bar.draw_left con functools.wraps",
            lambda: setattr(topbar, "draw_left", wrapped_draw_left),
            lambda: setattr(topbar, "draw_left", original_draw_left),
        )

        menus = bpy.types.TOPBAR_MT_editor_menus

        def menu(self: object, context: object) -> None:
            pass

        change(
            "TOPBAR_MT_editor_menus.append",
            lambda: menus.append(menu),
            lambda: menus.remove(menu),
        )

        @functools.wraps(menu)
        def wrapped_menu(self: object, context: object) -> None:
            menu(self, context)

        menus.append(menu)
        try:
            funcs = menus.draw._draw_funcs
            change(
                "TOPBAR_MT_editor_menus.append con functools.wraps",
                lambda: funcs.__setitem__(funcs.index(menu), wrapped_menu),
                lambda: funcs.__setitem__(funcs.index(wrapped_menu), menu),
                reference=state_fingerprint(),
            )
        finally:
            menus.remove(menu)

        # Funciones añadidas a cualquier menú, cabecera o panel (el importador de las
        # specs 005 y 006 se añade a TOPBAR_MT_file_import), también al principio, y la
        # «draw» de un panel sustituida (hallazgo F2; convergencia, T49).
        file_import = bpy.types.TOPBAR_MT_file_import
        change(
            "TOPBAR_MT_file_import.append",
            lambda: file_import.append(menu),
            lambda: file_import.remove(menu),
        )
        object_menu = bpy.types.VIEW3D_MT_object
        change(
            "VIEW3D_MT_object.prepend",
            lambda: object_menu.prepend(menu),
            lambda: object_menu.remove(menu),
        )
        panel = bpy.types.RENDER_PT_context
        original_panel_draw = panel.draw
        change(
            "RENDER_PT_context.draw",
            lambda: setattr(panel, "draw", menu),
            lambda: setattr(panel, "draw", original_panel_draw),
        )

        keyconfig = bpy.context.window_manager.keyconfigs.addon
        self.assertIsNotNone(keyconfig, "en segundo plano hay mapa de complementos")
        existed = "Window" in keyconfig.keymaps
        items: list[bpy.types.KeyMapItem] = []

        def add_item() -> None:
            keymap = keyconfig.keymaps.new(name="Window", space_type="EMPTY")
            items.append(keymap.keymap_items.new("wm.call_menu", "F10", "PRESS", ctrl=True))

        def remove_item() -> None:
            keymap = keyconfig.keymaps["Window"]
            keymap.keymap_items.remove(items.pop())
            if not existed:
                keyconfig.keymaps.remove(keymap)

        change("Ctrl+F10", add_item, remove_item)

        # Un temporizador registrado y unas traducciones con el nombre de la extensión,
        # sin quitar (hallazgo F3; convergencia, T50).
        def timer() -> float:
            return 60.0

        change(
            "bpy.app.timers.register",
            lambda: bpy.app.timers.register(timer, first_interval=60.0, persistent=True),
            lambda: bpy.app.timers.unregister(timer),
        )
        translations = {"es_ES": {("*", "gbtest probe"): "sonda de prueba"}}
        change(
            "bpy.app.translations.register",
            lambda: bpy.app.translations.register(module_name(), translations),
            lambda: bpy.app.translations.unregister(module_name()),
        )

        # Manejadores de dibujo de cualquier editor y del cursor, colecciones de previews,
        # suscripciones de msgbus, preferencias, complementos y entradas de
        # driver_namespace sin quitar (hallazgo F3 de la ronda 4; convergencia, T62).
        def draw() -> None:
            pass

        handles: list[object] = []
        for space, kind in (
            (bpy.types.SpaceView3D, "POST_VIEW"),
            (bpy.types.SpaceImageEditor, "POST_PIXEL"),
        ):
            change(
                f"{space.__name__}.draw_handler_add",
                lambda s=space, k=kind: handles.append(s.draw_handler_add(draw, (), "WINDOW", k)),
                lambda s=space: s.draw_handler_remove(handles.pop(), "WINDOW"),
            )
        manager = bpy.types.WindowManager
        change(
            "WindowManager.draw_cursor_add",
            lambda: handles.append(manager.draw_cursor_add(draw, (), "VIEW_3D", "WINDOW")),
            lambda: manager.draw_cursor_remove(handles.pop()),
        )
        collections: list[object] = []
        change(
            "bpy.utils.previews.new",
            lambda: collections.append(bpy.utils.previews.new()),
            lambda: bpy.utils.previews.remove(collections.pop()),
        )
        owner = object()
        change(
            "bpy.msgbus.subscribe_rna",
            lambda: bpy.msgbus.subscribe_rna(
                key=(bpy.types.Object, "location"), owner=owner, args=(), notify=draw
            ),
            lambda: bpy.msgbus.clear_by_owner(owner),
        )
        preferences = bpy.context.preferences
        for group, name in (
            ("view", "show_tooltips"),
            ("system", "use_region_overlap"),
            ("inputs", "use_mouse_emulate_3_button"),
            ("edit", "use_global_undo"),
            ("filepaths", "use_relative_paths"),
        ):
            struct = getattr(preferences, group)
            value = getattr(struct, name)
            change(
                f"preferences.{group}.{name}",
                lambda s=struct, n=name, v=value: setattr(s, n, not v),
                lambda s=struct, n=name, v=value: setattr(s, n, v),
            )
        addons: list[bpy.types.Addon] = []

        def add_addon() -> None:
            addons.append(preferences.addons.new())
            addons[-1].module = "gbtest_probe"

        change(
            "preferences.addons",
            add_addon,
            lambda: preferences.addons.remove(addons.pop()),
        )
        namespace = bpy.app.driver_namespace
        change(
            "bpy.app.driver_namespace",
            lambda: namespace.__setitem__("gbtest_probe", draw),
            lambda: namespace.pop("gbtest_probe"),
        )
        self.assertEqual(
            [key for key, changed in seen.items() if not changed],
            [],
            "la huella no ve estos cambios",
        )
        self.assertEqual(len(seen), 30)
        self.assertEqual(fingerprint_diff(before, state_fingerprint()), [])

    def test_diff_names_added_property(self) -> None:
        """RF-001-05: la diferencia de la huella nombra solo lo que sobra y lo que falta
        en una lista anidada (p. ej. una propiedad de ``Scene``), no la lista entera."""
        before = state_fingerprint()
        bpy.types.Scene.gbtest_diff = bpy.props.IntProperty()
        try:
            after = state_fingerprint()
        finally:
            del bpy.types.Scene.gbtest_diff
        self.assertEqual(
            fingerprint_diff(before, after),
            ["properties[Scene]: añadidos ['gbtest_diff'], quitados []"],
        )

    def test_diff_names_menu_function(self) -> None:
        """RF-001-05: la diferencia nombra el menú y la función que se le añadió (no
        solo los de la barra superior; convergencia, T49)."""

        def gbtest_import_menu(self: object, context: object) -> None:
            pass

        file_import = bpy.types.TOPBAR_MT_file_import
        before = state_fingerprint()
        file_import.append(gbtest_import_menu)
        try:
            after = state_fingerprint()
        finally:
            file_import.remove(gbtest_import_menu)
        (line,) = fingerprint_diff(before, after)
        self.assertTrue(line.startswith("draw_funcs[TOPBAR_MT_file_import]: añadidos ["), line)
        self.assertIn("gbtest_import_menu", line)
        self.assertTrue(line.endswith(", quitados []"), line)

    def test_wrapper_hint_only_when_replaced(self) -> None:
        """RF-001-05: la pista «mismo nombre y otro objeto» sale solo si se quitó una
        función y se añadió otra con su nombre (una envoltura sin deshacer); no si solo se
        añadió una, aunque en la lista quede otra con ese nombre (una fuga que se repite
        en cada habilitación) (hallazgo F8 de la ronda 3; convergencia, T55)."""

        def gbtest_handler(*_args: object) -> None:
            pass

        @functools.wraps(gbtest_handler)
        def gbtest_copy(*_args: object) -> None:
            pass

        hint = "mismo nombre y otro objeto"
        handlers = bpy.app.handlers.load_post
        start = state_fingerprint()
        handlers.append(gbtest_handler)
        try:
            one = state_fingerprint()
            handlers.append(gbtest_copy)  # la misma fuga, otra vez
            repeated = state_fingerprint()
            handlers.remove(gbtest_handler)  # y ahora la sustituye
            replaced = state_fingerprint()
        finally:
            for function in (gbtest_handler, gbtest_copy):
                while function in handlers:
                    handlers.remove(function)
        for label, old, new, expected in (
            ("añadida", start, one, False),
            ("repetida", one, repeated, False),
            ("sustituida", one, replaced, True),
        ):
            with self.subTest(caso=label):
                (line,) = fingerprint_diff(old, new)
                self.assertTrue(line.startswith("handlers[load_post]: "), line)
                self.assertEqual(hint in line, expected, line)

    def test_diff_names_timer_and_translations(self) -> None:
        """RF-001-05: la diferencia nombra el temporizador que sigue registrado (de los
        que se registraron durante la sesión, que el lanzador anota) y el módulo de la
        extensión con traducciones registradas (convergencia, T50)."""

        def gbtest_timer() -> float:
            return 60.0

        before = state_fingerprint()
        bpy.app.timers.register(gbtest_timer, first_interval=60.0, persistent=True)
        try:
            bpy.app.translations.register(module_name(), {"es_ES": {("*", "x"): "y"}})
            try:
                after = state_fingerprint()
            finally:
                bpy.app.translations.unregister(module_name())
        finally:
            bpy.app.timers.unregister(gbtest_timer)
        lines = fingerprint_diff(before, after)
        self.assertEqual(len(lines), 2, lines)
        self.assertTrue(lines[0].startswith("timers: añadidos ["), lines)
        self.assertIn("gbtest_timer", lines[0])
        self.assertEqual(lines[1], f"translations: añadidos [{module_name()!r}], quitados []")
        self.assertEqual(fingerprint_diff(before, state_fingerprint()), [])

    def test_diff_names_session_registrations(self) -> None:
        """RF-001-05: la diferencia nombra el manejador de dibujo (con su editor y su
        función), la colección de previews (con el módulo que la creó), la suscripción de
        msgbus (con su función), la preferencia cambiada (con su valor antes y después),
        el complemento y la entrada de ``driver_namespace`` (convergencia, T62)."""

        def gbtest_draw() -> None:
            pass

        preferences = bpy.context.preferences
        tooltips = preferences.view.show_tooltips
        owner = object()
        before = state_fingerprint()
        handle = bpy.types.SpaceView3D.draw_handler_add(gbtest_draw, (), "WINDOW", "POST_VIEW")
        try:
            collection = bpy.utils.previews.new()
            try:
                bpy.msgbus.subscribe_rna(
                    key=(bpy.types.Object, "location"), owner=owner, args=(), notify=gbtest_draw
                )
                preferences.view.show_tooltips = not tooltips
                addon = preferences.addons.new()
                addon.module = "gbtest_addon"
                bpy.app.driver_namespace["gbtest_driver"] = gbtest_draw
                try:
                    after = state_fingerprint()
                finally:
                    bpy.app.driver_namespace.pop("gbtest_driver", None)
                    preferences.addons.remove(addon)
                    preferences.view.show_tooltips = tooltips
                    bpy.msgbus.clear_by_owner(owner)
            finally:
                bpy.utils.previews.remove(collection)
        finally:
            bpy.types.SpaceView3D.draw_handler_remove(handle, "WINDOW")
        lines = fingerprint_diff(before, after)
        self.assertEqual(len(lines), 6, lines)
        by_key = {line.split(":", 1)[0]: line for line in lines}
        self.assertEqual(
            by_key["addons"], "addons: añadidos ['gbtest_addon'], quitados []"
        )
        self.assertIn("SpaceView3D.draw_handler_add → ", by_key["draw_handlers"])
        self.assertIn("gbtest_draw", by_key["draw_handlers"])
        self.assertEqual(
            by_key["driver_namespace"],
            "driver_namespace: añadidos ['gbtest_driver'], quitados []",
        )
        self.assertIn("bpy.msgbus.subscribe_rna → ", by_key["msgbus"])
        self.assertIn("gbtest_draw", by_key["msgbus"])
        self.assertEqual(
            by_key["preferences[view.show_tooltips]"],
            f"preferences[view.show_tooltips]: {tooltips!r} → {not tooltips!r}",
        )
        self.assertIn(f"bpy.utils.previews.new desde {__name__}", by_key["previews"])
        self.assertEqual(fingerprint_diff(before, state_fingerprint()), [])

    def test_session_baseline_available(self) -> None:
        """RF-001-05: el lanzador deja la huella del principio de la sesión, que tiene
        las mismas claves que una huella nueva."""
        baseline = blender_ext.session_baseline()
        self.assertEqual(sorted(baseline), sorted(state_fingerprint()))


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: GPL-3.0-or-later
"""Registro de la interfaz desde el catálogo (spec 003, T11; plan 003 §5.4, 1 y 2).

- RF-003-07: cada ``geoblender.*`` del catálogo está registrado una sola vez, real o
  provisional, y ninguno fuera del catálogo; un operador real de ``bl/ops`` no tiene
  provisional; un provisional invocado por script devuelve ``{'CANCELLED'}``, no cambia
  ``bpy.data`` e informa «Disponible en …» (también su descripción, y la de la variante
  pedida).
- RF-003-23: deshabilitar deja la instantánea de la interfaz idéntica a la de antes de
  habilitar.
- Contrato 1 del plan: ``bl_label`` de cada clase real = ``msgid`` del catálogo; con la
  extensión habilitada, Blender la muestra en el idioma de Geoblender (español por
  defecto).
- RF-003-04, RF-003-19 (puerta de modo): lo lanzado desde una Vista 3D exige el modo
  Geoblender; desde fuera de la Vista 3D, no.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import unittest
from types import ModuleType, SimpleNamespace

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import fingerprint_diff, module_name, ui_snapshot

VOLUME = "geoblender.res_compute_volume_between_surfaces"  # R-38, aún provisional
SAVE = "geoblender.core_save_project"  # real (spec 002)


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def _registered_subclasses(base: type) -> list[type]:
    found: list[type] = []
    pending = [base]
    while pending:
        for cls in pending.pop().__subclasses__():
            pending.append(cls)
            if "bl_rna" in cls.__dict__ and getattr(cls, "is_registered", False):
                found.append(cls)
    return found


def _data_state() -> dict[str, object]:
    """Lo que un comando provisional no debe cambiar: el número de elementos de cada
    colección de ``bpy.data`` y la marca de fichero modificado."""
    state: dict[str, object] = {"is_dirty": bpy.data.is_dirty}
    for name in dir(bpy.data):
        value = getattr(bpy.data, name, None)
        if isinstance(value, bpy.types.bpy_prop_collection):
            state[name] = len(value)
    return state


class EnabledUiTest(unittest.TestCase):
    """Con la extensión habilitada una vez para toda la clase."""

    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.unload()
        blender_ext.enable()
        cls.cat = _module("core.catalog").load()
        cls.commands = _module("bl.ui.commands")
        cls.registry = _module("bl.ui.registry")
        cls.provisional = _module("bl.ui.provisional")
        cls.ops = _module("bl.ops")

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.unload()

    def test_each_operator_registered_once(self) -> None:
        """RF-003-07: cada ``bl_idname`` del catálogo tiene una clase registrada, real o
        provisional (nunca las dos), y no hay ningún ``geoblender.*`` fuera del
        catálogo."""
        idnames = self.cat.operator_idnames()
        self.assertGreater(len(idnames), 300)
        for idname in sorted(idnames):
            cls = self.commands.registered_class(idname)
            self.assertIsNotNone(cls, idname)
            self.assertEqual(cls.bl_idname, idname)
        real = {cls.bl_idname for cls in self.ops.classes}
        provisional = {cls.bl_idname for cls in self.registry.provisional_classes()
                       if issubclass(cls, bpy.types.Operator)}
        self.assertEqual(real & provisional, set())
        self.assertEqual(real | provisional, set(idnames))
        registered = {cls.bl_idname for cls in _registered_subclasses(bpy.types.Operator)
                      if cls.bl_idname.startswith("geoblender.")}
        self.assertEqual(sorted(registered - idnames), [])

    def test_menus_and_panels_registered(self) -> None:
        """RF-003-06, RF-003-07: cada menú y cada panel del catálogo tiene su clase
        registrada (real, generada o provisional)."""
        for name in sorted(self.cat.class_names()):
            self.assertIsNotNone(self.commands.registered_class(name), name)

    def test_real_operator_without_provisional(self) -> None:
        """RF-003-07: un operador real registrado antes por ``bl/ops`` no tiene
        provisional y está disponible; uno de una entrada posterior, sí lo tiene y no
        está disponible."""
        cls = self.commands.registered_class(SAVE)
        self.assertIn(cls, self.ops.classes)
        self.assertFalse(self.commands.is_provisional(cls))
        self.assertTrue(self.commands.is_available(SAVE))
        volume = self.commands.registered_class(VOLUME)
        self.assertTrue(self.commands.is_provisional(volume))
        self.assertFalse(self.commands.is_available(VOLUME))
        self.assertTrue(self.commands.is_available("view3d.view_all"))

    def test_provisional_by_script(self) -> None:
        """RF-003-07: invocado por script, un provisional devuelve ``{'CANCELLED'}`` y no
        cambia ``bpy.data``; informa «Disponible en R-38 · …» y su descripción lo dice."""
        before = _data_state()
        self.assertEqual(bpy.ops.geoblender.res_compute_volume_between_surfaces(),
                         {"CANCELLED"})
        self.assertEqual(bpy.ops.geoblender.ui_set_view(view="PLAN"), {"CANCELLED"})
        self.assertEqual(_data_state(), before)
        cls = self.commands.registered_class(VOLUME)
        reports: list[tuple[set[str], str]] = []
        fake = SimpleNamespace(properties=SimpleNamespace(),
                               report=lambda kind, text: reports.append((kind, text)))
        self.assertEqual(cls.execute(fake, bpy.context), {"CANCELLED"})
        self.assertEqual(len(reports), 1)
        kind, text = reports[0]
        self.assertEqual(kind, {"INFO"})
        self.assertTrue(text.startswith("Disponible en R-38 · "), text)
        description = cls.description(bpy.context, SimpleNamespace())
        self.assertIn(text, description)
        self.assertIn(self.cat.commands[VOLUME].description_es, description)

    def test_variant_message(self) -> None:
        """RF-003-07: el texto es el de la variante pedida (D-1: «Sin recorte» es de la
        003 y «Delante», de R-16)."""
        message = self.provisional.message
        front = message(self.cat, "geoblender.geo_set_clip_mode", SimpleNamespace(mode="FRONT"))
        self.assertTrue(front.startswith("Disponible en R-16"), front)
        none = message(self.cat, "geoblender.geo_set_clip_mode", SimpleNamespace(mode="NONE"))
        self.assertTrue(none.startswith("Disponible en 003"), none)

    def test_labels_in_geoblender_language(self) -> None:
        """Contrato 1, RF-003-20: con la extensión habilitada, Blender muestra la etiqueta
        del catálogo en español (contexto de traducción propio), tanto de un real como de
        un provisional."""
        for idname in (SAVE, VOLUME):
            cmd = self.cat.commands[idname]
            module, _, name = idname.partition(".")
            rna = getattr(getattr(bpy.ops, module), name).get_rna_type()
            self.assertEqual(rna.name, cmd.label_es, idname)
            self.assertEqual(rna.translation_context, self.commands.TRANSLATION_CONTEXT, idname)

    def test_gate(self) -> None:
        """RF-003-04, RF-003-19: la puerta de modo solo actúa en una Vista 3D: allí exige
        un espacio de trabajo marcado; fuera (o sin área), pasa."""
        gate = _module("bl.ui.gate")
        marked = SimpleNamespace(geoblender_mode=True)
        plain = SimpleNamespace(geoblender_mode=False)
        view = SimpleNamespace(type="VIEW_3D")
        self.assertTrue(gate.in_geoblender_scope(SimpleNamespace(area=None, workspace=plain)))
        self.assertTrue(gate.in_geoblender_scope(
            SimpleNamespace(area=SimpleNamespace(type="OUTLINER"), workspace=plain)))
        self.assertFalse(gate.in_geoblender_scope(SimpleNamespace(area=view, workspace=plain)))
        self.assertTrue(gate.in_geoblender_scope(SimpleNamespace(area=view, workspace=marked)))
        window = bpy.context.window_manager.windows[0]
        area = next(a for a in window.screen.areas if a.type == "VIEW_3D")
        region = next(r for r in area.regions if r.type == "WINDOW")
        workspace = window.workspace
        self.assertFalse(workspace.geoblender_mode)
        with bpy.context.temp_override(window=window, area=area, region=region):
            self.assertFalse(bpy.ops.geoblender.res_compute_volume_between_surfaces.poll())
            workspace.geoblender_mode = True
            try:
                self.assertTrue(bpy.ops.geoblender.res_compute_volume_between_surfaces.poll())
            finally:
                workspace.geoblender_mode = False
        self.assertTrue(bpy.ops.geoblender.res_compute_volume_between_surfaces.poll())


class UiRegisterCycleTest(unittest.TestCase):
    def setUp(self) -> None:
        blender_ext.unload()
        self.addCleanup(blender_ext.unload)

    def test_disable_restores_snapshot(self) -> None:
        """RF-003-23: habilitar y deshabilitar deja la instantánea de la interfaz
        (``draw_left``, cabeceras, atajos, clases, propiedades, manejadores, espacios de
        trabajo) idéntica."""
        before = ui_snapshot()
        blender_ext.enable()
        blender_ext.disable()
        after = ui_snapshot()
        if after != before:
            self.fail("\n".join(fingerprint_diff(before, after)))

    def test_real_labels_are_catalog_msgids(self) -> None:
        """Contrato 1 del plan: tras habilitar y deshabilitar, cada clase real del
        catálogo tiene en su código el ``bl_label`` = ``msgid`` del catálogo (el registro
        se lo cambia al idioma de Geoblender y lo devuelve al desregistrar)."""
        blender_ext.enable()
        blender_ext.disable()
        cat = _module("core.catalog").load()
        ops = _module("bl.ops")
        ui = _module("bl.ui")
        checked = 0
        for cls in (*ops.classes, *ui.classes):
            cmd = cat.commands.get(cls.bl_idname)
            if cmd is None:
                continue
            checked += 1
            self.assertEqual(cls.bl_label, cmd.label, cls.bl_idname)
        self.assertGreater(checked, 10)


if __name__ == "__main__":
    unittest.main()

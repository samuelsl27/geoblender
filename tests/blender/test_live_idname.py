# SPDX-License-Identifier: GPL-3.0-or-later
"""La orden de un operador vivo, no el nombre de su clase (spec 011, T40; hallazgo O-5 de la
verificación de la 011).

En ``execute``, ``invoke`` y ``draw`` de un operador vivo, ``self.bl_idname`` es el nombre de su
clase en Blender («GEOBLENDER_OT_…»); solo ``cls.bl_idname`` (``poll``, ``description``) es la
orden («geoblender.…») que conocen el catálogo y ``bpy.ops``. Las pruebas de antes llamaban a
estos métodos con un ``self`` simulado que llevaba la orden; aquí lleva el de Blender.

- RF-006-24, RF-006-25 y spec 006 §8 («nunca se sobrescribe sin confirmación»): exportar desde
  la interfaz una rejilla o capas sobre un fichero que ya existe lo dice y pide confirmar que se
  sustituye (la misma orden con ``confirm``), en vez de lanzar un ``ValueError`` con su traza.
- RF-003-07: Añadir disposición y Recorte ▸ con una variante que aún no ha llegado dicen
  «Disponible en …» al lanzarlas, no un informe vacío.
- RF-005 (``bl.ops.dh``): una orden de los sondeos busca su motivo con la orden.
- Las hojas de ayuda y el diagnóstico dibujan su botón con la orden.
- ``bl.ui.commands.command_idname``: la orden de cualquiera de las dos formas.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import contextlib
import importlib
import shutil
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.fake_layout import draw, operator_self

EXPORT_RASTER = "geoblender.gis_export_raster"
EXPORT_GPKG = "geoblender.gis_export_gpkg"


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


class LiveIdnameTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.commands = _module("bl.ui.commands")

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.release()

    def live(self, idname: str) -> str:
        """El ``bl_idname`` de un operador vivo de la orden ``idname``."""
        return self.commands.operator_class_name(idname)

    def test_command_idname(self) -> None:
        """La orden de un ``bl_idname`` en cualquiera de sus dos formas, la inversa de
        ``operator_class_name``."""
        for idname in (EXPORT_RASTER, "geoblender.res_between_surfaces",
                       "geoblender.ui_show_shortcuts"):
            with self.subTest(orden=idname):
                self.assertEqual(self.commands.command_idname(self.live(idname)), idname)
                self.assertEqual(self.commands.command_idname(idname), idname)

    def test_export_over_an_existing_file_asks(self) -> None:
        """RF-006-24, RF-006-25, spec 006 §8: con el ``bl_idname`` de Blender, exportar sobre un
        fichero que ya existe avisa sin sustituirlo y pide confirmarlo con la misma orden
        (``confirm`` y el destino); nada de ``ValueError``."""
        gis_ops = _module("bl.ops.gis")
        folder = Path(tempfile.mkdtemp(prefix="gb-011-t40-"))
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        target = folder / "mdt.tif"
        target.write_bytes(b"anterior")
        for idname in (EXPORT_RASTER, EXPORT_GPKG):
            with self.subTest(orden=idname):
                report = mock.Mock()
                operator = SimpleNamespace(overwrite=False, provenance_dialog=True,
                                           bl_idname=self.live(idname), report=report)
                timers = mock.Mock()
                launched = mock.Mock()
                group, name = idname.split(".")
                fake_bpy = SimpleNamespace(
                    context=SimpleNamespace(
                        window_manager=SimpleNamespace(windows=["ventana"]),
                        temp_override=lambda **_kw: contextlib.nullcontext()),
                    app=SimpleNamespace(timers=SimpleNamespace(register=timers)),
                    ops=SimpleNamespace(**{group: SimpleNamespace(**{name: launched})}))
                with mock.patch.object(gis_ops, "bpy", fake_bpy):
                    result = gis_ops._existing(operator, target, {"source": "gis_src_mdt"})
                    self.assertEqual(result, {"CANCELLED"})
                    (kind, text), _kw = report.call_args
                    self.assertEqual(kind, {"WARNING"})
                    self.assertIn("Ya existe «mdt.tif»: confirme que se sustituye", text)
                    (call,), _kw = timers.call_args
                    call()
                launched.assert_called_once_with("INVOKE_DEFAULT", confirm=True,
                                                 filepath=str(target), source="gis_src_mdt")
                self.assertEqual(target.read_bytes(), b"anterior")

    def test_undelivered_variants_say_where(self) -> None:
        """RF-003-07: lanzadas con el ``bl_idname`` de Blender, Añadir disposición (Revisión
        de versiones, R-62) y Recorte ▸ Delante (R-16) dicen «Disponible en …»."""
        cases = ((bpy.types.GEOBLENDER_OT_ui_add_layout, "geoblender.ui_add_layout",
                  {"layout": "VERSION_REVIEW"}, "Disponible en R-62"),
                 (bpy.types.GEOBLENDER_OT_geo_set_clip_mode, "geoblender.geo_set_clip_mode",
                  {"mode": "FRONT"}, "Disponible en R-16"))
        for cls, idname, values, expected in cases:
            with self.subTest(orden=idname):
                report = mock.Mock()
                fake = operator_self(cls, report=report, bl_idname=self.live(idname),
                                     properties=SimpleNamespace(**values), **values)
                self.assertEqual(cls.execute(fake, bpy.context), {"CANCELLED"})
                (kind, text), _kw = report.call_args
                self.assertEqual(kind, {"INFO"})
                self.assertIn(expected, text)

    def test_drillholes_reason_with_the_command(self) -> None:
        """La orden de los sondeos busca su motivo con la orden, no con su clase."""
        dh_ops = _module("bl.ops.dh")
        idname = "geoblender.dh_validate"
        fake = SimpleNamespace(bl_idname=self.live(idname), report=mock.Mock())
        with mock.patch.object(dh_ops, "unavailable_reason", return_value="motivo") as reason:
            self.assertEqual(dh_ops._DrillholesCommand.execute(fake, bpy.context),
                             {"CANCELLED"})
        reason.assert_called_once_with(idname)
        fake.report.assert_called_once_with({"INFO"}, "motivo")

    def test_help_buttons_name_the_command(self) -> None:
        """Las hojas de ayuda y el diagnóstico dibujan su botón (versión imprimible, copiar)
        con la orden."""
        help_mod = _module("bl.ui.help")
        cases = ((bpy.types.GEOBLENDER_OT_ui_show_shortcuts, "geoblender.ui_show_shortcuts"),
                 (bpy.types.GEOBLENDER_OT_ui_show_glossary, "geoblender.ui_show_glossary"),
                 (bpy.types.GEOBLENDER_OT_ui_run_diagnostics, "geoblender.ui_run_diagnostics"))
        with mock.patch.object(help_mod, "draw_sheet"), \
                mock.patch.object(help_mod, "diagnostics", return_value=[]):
            for cls, idname in cases:
                with self.subTest(orden=idname):
                    layout = draw(cls, bpy.context, bl_idname=self.live(idname))
                    targets = [item.target for item in layout.items if item.kind == "operator"]
                    self.assertEqual(targets, [idname])


if __name__ == "__main__":
    unittest.main()

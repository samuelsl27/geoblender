# SPDX-License-Identifier: GPL-3.0-or-later
"""Ayuda: hojas de atajos, alias y glosario, diagnóstico, «Acerca de», preferencias e
idioma (spec 003, T33; RF-003-21, RF-003-27; BS §8.13).

- RF-003-27: la hoja de atajos sale del estado actual: los 49 atajos registrados, con la
  combinación que tienen ahora (uno cambiado se ve cambiado; uno desactivado no sale); su
  versión imprimible es un HTML que se escribe solo en la carpeta de datos de la extensión
  (``extension_path_user(…, "help")``) y tiene las 49 filas. Las de alias y glosario, con
  todos los alias y términos del catálogo.
- RF-003-27: el diagnóstico dice la versión de Blender y la de Geoblender, el modo de la
  barra (normal, compatibilidad o sustituida por otro complemento), los atajos registrados
  y los que chocan con otra asignación en el ámbito de la Vista 3D, y los iconos cargados.
- RF-004-22, RF-004-26 (spec 004, T41): el diagnóstico dice el estado del motor de cálculo
  del lanzador de la sesión (no instalado, desactualizado, dañado o «Listo · numpy … · BLAS
  … · 2000 × 2000 en … s», lo que midió su verificación) y, si lo hay, el intérprete
  externo; ya no «Disponible en 004».
- «Acerca de»: versión, licencia y la atribución de los datos de terceros (ADR-0019).
- RF-003-21: Ayuda ▸ Idioma de Geoblender ▸ English deja el cambio pendiente (lo aplica
  el siguiente ciclo de eventos), lo guarda en las preferencias y no cambia el idioma de
  Blender.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import importlib
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name

TOTAL = 49
ENGINE = "Motor de cálculo"
EXTERNAL = "Intérprete externo"
OTHER_LOCK_ID = "0123456789ab"  # el motor de otra versión de Geoblender
ENGINE_TEXTS = {
    "missing": "No instalado",
    "outdated": "Desactualizado: es de otra versión de Geoblender",
    "broken": "Dañado o sin verificar: hay que repararlo",
    "ready": "Listo · numpy 2.5.3 · BLAS scipy-openblas · 2000 × 2000 en 0,043 s",
}


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


def body_rows(html: str) -> int:
    """Las filas del cuerpo de la tabla de una hoja HTML."""
    body = html.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    return body.count("<tr>")


class HelpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.unload()
        blender_ext.load_file()
        blender_ext.enable()
        cls.help = _module("bl.ui.help")
        cls.keymap = _module("bl.ui.keymap")
        cls.commands = _module("bl.ui.commands")
        cls.topbar = _module("bl.ui.topbar")
        cls.ui_i18n = _module("bl.ui.i18n")
        cls.i18n = _module("core.i18n")
        cls.cat = cls.commands.catalog()

    @classmethod
    def tearDownClass(cls) -> None:
        blender_ext.load_file()
        blender_ext.unload()

    def help_folder(self) -> Path:
        return Path(bpy.utils.extension_path_user(module_name(), path="help"))

    # Hojas -----------------------------------------------------------------------------

    def test_shortcut_sheet_is_the_registered_state(self) -> None:
        """RF-003-27: 49 filas de los atajos registrados; uno cambiado sale con su
        combinación de ahora y uno desactivado no sale."""
        rows = self.help.shortcut_rows()
        self.assertEqual(len(rows), TOTAL)
        first = rows[0].columns
        self.assertEqual(first[0], "Ctrl+F10")
        self.assertEqual(first[1], "Conmutar Geoblender ⇄ Blender")
        # La persona cambia el atajo en Preferencias ▸ Mapa de teclado: el elemento del
        # keyconfig de usuario (si Blender no lo ha creado, el registrado).
        _keymap, item = next((km, kmi) for km, kmi in self.keymap.registered_items()
                             if kmi.idname == "geoblender.ui_open_command_line")
        user = bpy.context.window_manager.keyconfigs.user.keymaps.get("3D View")
        mine = [kmi for kmi in (user.keymap_items if user is not None else ())
                if kmi.idname == "geoblender.ui_open_command_line"]
        item = mine[0] if mine else item
        item.type = "F12"
        self.addCleanup(setattr, item, "type", "F10")
        row = next(r for r in self.help.shortcut_rows()
                   if r.key == "geoblender.ui_open_command_line")
        self.assertEqual(row.columns[0], "F12")
        item.active = False
        self.addCleanup(setattr, item, "active", True)
        self.assertEqual(len(self.help.shortcut_rows()), TOTAL - 1)

    def test_printable_sheets_in_the_user_data_folder(self) -> None:
        """RF-003-27: las versiones imprimibles se escriben en la carpeta de datos de la
        extensión, con una fila por atajo, alias o término (que nada más cambia en el
        repositorio lo comprueba la foto de ``tools/check.py``)."""
        aliases = sum(len(cmd.aliases) for cmd in self.cat.commands.values())
        terms = sum(len(cmd.jargon) for cmd in self.cat.commands.values())
        for operator, count, title in (
            (bpy.ops.geoblender.ui_show_shortcuts, TOTAL, "Atajos de Geoblender"),
            (bpy.ops.geoblender.ui_show_aliases, aliases, "Alias de la línea de comandos"),
            (bpy.ops.geoblender.ui_show_glossary, terms, "Glosario"),
        ):
            with self.subTest(title=title):
                self.assertEqual(operator(printable=True), {"FINISHED"})
                path = self.help.last_written()
                self.assertIsNotNone(path)
                self.assertEqual(path.parent, self.help_folder())
                html = path.read_text(encoding="utf-8")
                self.assertIn(f"<title>{title}</title>", html)
                self.assertEqual(body_rows(html), count)
        self.assertIn("Ctrl+F10", (self.help_folder() / "shortcuts_es.html")
                      .read_text(encoding="utf-8"))
        self.assertGreater(aliases, 0)
        self.assertGreater(terms, 0)

    def test_popup_sheets_without_interface(self) -> None:
        """Sin interfaz, la hoja en pantalla no abre nada y no falla."""
        for operator in (bpy.ops.geoblender.ui_show_shortcuts,
                         bpy.ops.geoblender.ui_show_aliases,
                         bpy.ops.geoblender.ui_show_glossary,
                         bpy.ops.geoblender.ui_run_diagnostics,
                         bpy.ops.geoblender.ui_show_about,
                         bpy.ops.geoblender.ui_show_preferences):
            with self.subTest(operator=operator.idname()):
                self.assertEqual(operator(), {"FINISHED"})

    # Diagnóstico ----------------------------------------------------------------------

    def diagnostics(self) -> dict[str, str]:
        return dict(self.help.diagnostics())

    def test_diagnostics(self) -> None:
        """RF-003-27: versiones, barra normal, 49 atajos sin choques e iconos cargados."""
        rows = self.diagnostics()
        self.assertIn(bpy.app.version_string, rows["Blender"])
        version = _module("core.version").geoblender_version()
        self.assertIn(version, rows["Extensión"])
        self.assertEqual(rows["Barra superior"], "normal")
        self.assertEqual(rows["Atajos"], f"{TOTAL} de {TOTAL} registrados")
        self.assertEqual(rows["Atajos en conflicto"], "ninguno")
        icons = len(self.cat.icons)
        self.assertEqual(rows["Iconos"], f"{icons} de {icons} cargados (32 px)")
        self.assertEqual(rows["Idioma de Geoblender"], "Español")

    def test_diagnostics_names_a_conflict(self) -> None:
        """RF-003-27: una asignación de otro operador con la misma combinación en el
        ámbito de la Vista 3D sale en «Atajos en conflicto»."""
        keyconfig = bpy.context.window_manager.keyconfigs.user
        keymap = keyconfig.keymaps.find("Object Mode", space_type="EMPTY", region_type="WINDOW")
        self.assertIsNotNone(keymap)
        item = keymap.keymap_items.new("object.select_all", "F10", "PRESS")
        self.addCleanup(keymap.keymap_items.remove, item)
        conflicts = self.diagnostics()["Atajos en conflicto"]
        self.assertIn("F10", conflicts)
        self.assertIn("Object Mode", conflicts)
        self.assertIn("object.select_all", conflicts)

    def test_diagnostics_sees_a_replaced_bar(self) -> None:
        """Spec §8: otro complemento sustituye la barra después de Geoblender y el
        diagnóstico lo indica."""
        header = bpy.types.TOPBAR_HT_upper_bar
        ours = header.draw_left

        def other(self: object, context: object) -> None:
            ours(self, context)

        header.draw_left = other
        self.addCleanup(setattr, header, "draw_left", ours)
        self.assertEqual(self.diagnostics()["Barra superior"],
                         "sustituida por otro complemento (Ayuda ▸ Reparar la interfaz)")

    def test_diagnostics_says_the_state_of_the_compute_engine(self) -> None:
        """RF-004-22, RF-004-26, RF-003-27: «Motor de cálculo» dice el estado del motor del
        lanzador de la sesión, ya no «Disponible en 004»: «No instalado», desactualizado
        (queda el de otro lock), dañado (su verificación no pasó) o, listo, lo que midió su
        verificación («Listo · numpy … · BLAS … · 2000 × 2000 en … s»; motor sintético en
        unos datos de usuario temporales). «Intérprete externo» sale, tras el motor, solo
        si el lanzador tiene uno, con su ruta; también en el texto que se copia."""
        ops = _module("bl.ops.jobs")
        runtime = _module("jobs.runtime")
        session = ops.session_runner()
        self.assertIsNotNone(session)
        rows = self.diagnostics()
        self.assertEqual(rows[ENGINE],
                         _module("bl.ui.jobs").engine_state_text(session.runtime))
        self.assertNotIn("Disponible en", rows[ENGINE])
        self.assertNotIn("Disponible en 004", self.help.diagnostics_text())

        tmp = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="gb4-")))
        env = runtime.ComputeEnvironment(tmp / "usuario", runtime.read_lock())
        runner = _module("jobs.runner").JobRunner(
            jobs_root=tmp / "jobs", package_dir=ops.PACKAGE_DIR,
            blender_python=Path(sys.executable), runtime=env)
        self.addCleanup(runner.shutdown, timeout_s=2.0)
        self.enterContext(mock.patch.object(ops._SESSION, "runner", runner))

        def check(status: str) -> None:
            self.assertEqual(env.status(), status)
            with self.subTest(estado=status):
                rows = self.diagnostics()
                self.assertEqual(rows[ENGINE], ENGINE_TEXTS[status])
                self.assertNotIn(EXTERNAL, rows)
                self.assertIn(f"{ENGINE}: {ENGINE_TEXTS[status]}",
                              self.help.diagnostics_text().splitlines())

        check("missing")
        (env.runtime_dir / OTHER_LOCK_ID).mkdir(parents=True)
        check("outdated")
        env.site_dir().mkdir(parents=True)
        verification = {"ok": False, "numpy": "2.5.3", "blas": "scipy-openblas",
                        "matmul_n": 2000, "matmul_s": 0.0431}
        info = env.path / runtime.RUNTIME_FILE
        info.write_text(json.dumps({"schema": runtime.RUNTIME_SCHEMA, "lock_id": env.lock_id,
                                    runtime.VERIFICATION_KEY: verification}),
                        encoding="utf-8")
        check("broken")
        verification["ok"] = True
        info.write_text(json.dumps({"schema": runtime.RUNTIME_SCHEMA, "lock_id": env.lock_id,
                                    runtime.VERIFICATION_KEY: verification}),
                        encoding="utf-8")
        check("ready")

        external = tmp / "entorno" / "Scripts" / "python.exe"
        runner.reconfigure(external_python=external)
        labels = [label for label, _value in self.help.diagnostics()]
        self.assertEqual(labels[labels.index(ENGINE) + 1], EXTERNAL)
        rows = self.diagnostics()
        self.assertEqual(rows[ENGINE], ENGINE_TEXTS["ready"])
        self.assertEqual(rows[EXTERNAL], str(external))
        self.assertIn(f"{EXTERNAL}: {external}", self.help.diagnostics_text().splitlines())

    def test_about(self) -> None:
        """«Acerca de»: versión, licencia y la atribución de los datos de terceros."""
        text = "\n".join(value for _label, value in self.help.about())
        self.assertIn(_module("core.version").geoblender_version(), text)
        self.assertIn("GPL-3.0-or-later", text)
        self.assertIn("IOGP", text)

    # Idioma -------------------------------------------------------------------------

    def test_set_language(self) -> None:
        """RF-003-21: Ayuda ▸ Idioma ▸ English: pendiente, guardado en las preferencias,
        aplicado en el siguiente ciclo (aquí, a mano) y Blender sin cambiar; y vuelta."""
        cls = self.commands.registered_class("geoblender.ui_set_language")
        self.assertFalse(self.commands.is_provisional(cls))
        prefs = self.commands.preferences()
        blender_language = bpy.context.preferences.view.language
        self.addCleanup(self.ui_i18n.apply, "es")
        self.addCleanup(setattr, prefs, "language", "ES")
        self.assertEqual(bpy.ops.geoblender.ui_set_language(language="EN"), {"FINISHED"})
        self.assertEqual(prefs.language, "EN")
        self.assertEqual(self.ui_i18n.pending(), "en")
        self.ui_i18n.apply_pending()
        self.assertEqual(self.i18n.language(), "en")
        self.assertEqual(bpy.types.GEOBLENDER_MT_ui_help.bl_label, "Help")
        self.assertEqual(bpy.ops.geoblender.ui_set_language(language="ES"), {"FINISHED"})
        self.ui_i18n.apply_pending()
        self.assertEqual(self.i18n.language(), "es")
        self.assertEqual(bpy.types.GEOBLENDER_MT_ui_help.bl_label, "Ayuda")
        self.assertEqual(bpy.context.preferences.view.language, blender_language)

    def test_real_operators(self) -> None:
        """Contrato 1: los siete son reales y están disponibles."""
        for idname in ("ui_show_shortcuts", "ui_show_aliases", "ui_show_glossary",
                       "ui_run_diagnostics", "ui_show_about", "ui_show_preferences",
                       "ui_set_language"):
            with self.subTest(idname=idname):
                cls = self.commands.registered_class(f"geoblender.{idname}")
                self.assertIsNotNone(cls)
                self.assertFalse(self.commands.is_provisional(cls))
        for key in ("geoblender.ui_show_shortcuts", "geoblender.ui_set_language?language=EN",
                    "geoblender.ui_run_diagnostics", "geoblender.ui_show_preferences"):
            self.assertTrue(self.commands.is_available(key), key)
        self.assertIsNotNone(re.search(r"\d", self.diagnostics()["Extensión"]))


if __name__ == "__main__":
    unittest.main()

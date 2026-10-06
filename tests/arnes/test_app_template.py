# SPDX-License-Identifier: GPL-3.0-or-later
"""La plantilla de aplicación «Geoblender» con el Blender real (spec 003, T34; RF-003-25;
ADR-0003; CW §7; D-2).

Relanza Blender entero, así que es del paso «arnés» (``tools/check.py --completo``). En
un perfil temporal (``BLENDER_USER_RESOURCES``), nunca el del usuario:

1. ``tools/dev_install.py --perfil`` instala y habilita la extensión (el Blender «normal»
   de ese perfil, con su ``config/userpref.blend``);
2. ``tools/install_app_template.py --perfil … --lanzador …`` instala la plantilla y el
   lanzador;
3. ``blender -b --app-template Geoblender`` arranca con la plantilla: la extensión queda
   habilitada; el fichero de inicio trae el espacio principal de Geoblender (con
   ``geoblender_mode``) y «Layout» sin marcar, ninguno más; la escena está vacía y en
   metros; y la plantilla pide el espacio principal para la ventana (sin interfaz el cambio
   diferido no se aplica: que se vea al arrancar es la comprobación M13);
4. las preferencias del Blender normal (``config/userpref.blend``) no cambian (mismo
   sha256) y ``--desinstalar`` deja el perfil como estaba antes del paso 2.
"""

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.support.harness import listing, listing_changes, locate
from tests.support.repo import ROOT, tools_on_path

tools_on_path()

import dev_install  # noqa: E402
import install_app_template  # noqa: E402
from gbtools import blender, layout  # noqa: E402

TIMEOUT_S = 300.0
RESULT_MARK = "GB-PLANTILLA:"
CACHE_FOLDER = "__pycache__"
CHECK_SCRIPT = f'''# SPDX-License-Identifier: GPL-3.0-or-later
import json

import addon_utils
import bl_app_template_utils
import bpy

template = bl_app_template_utils._modules.get("{layout.APP_TEMPLATE_ID}")
enabled = sorted(name for name in bpy.context.preferences.addons.keys()
                 if name.endswith(".geoblender"))
workspaces = {{ws.name: bool(getattr(ws, "geoblender_mode", False))
               for ws in bpy.data.workspaces}}
scene = bpy.context.scene
result = {{
    "template": bpy.context.preferences.app_template,
    "loaded": template is not None and getattr(template, "__template_enabled__", False),
    "enabled": enabled,
    "workspaces": workspaces,
    "objects": len(bpy.data.objects),
    "units": [scene.unit_settings.system, scene.unit_settings.length_unit],
    "requested": template.activate_main_workspace() if template else None,
}}
print("{RESULT_MARK}" + json.dumps(result))
'''


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AppTemplateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.install = locate()
        self.work = Path(tempfile.mkdtemp(prefix="gb-plantilla-arnes-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.profile = self.work / "perfil"
        self.launcher_dir = self.work / "escritorio"
        self.profile.mkdir()
        self.launcher_dir.mkdir()

    def run_template(self) -> dict[str, object]:
        script = self.work / "comprobar.py"
        script.write_text(CHECK_SCRIPT, encoding="utf-8")
        cmd = [str(self.install.exe), "-b", "--app-template", layout.APP_TEMPLATE_ID,
               "--python-exit-code", "1", "--python", str(script)]
        temp = self.work / "tmp"
        temp.mkdir(exist_ok=True)
        env = blender.isolated_env(self.profile)
        env.update({"TMP": str(temp), "TEMP": str(temp), "TMPDIR": str(temp)})
        result = subprocess.run(cmd, env=env, cwd=self.work, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=TIMEOUT_S)
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        line = next((line for line in output.splitlines() if line.startswith(RESULT_MARK)),
                    None)
        self.assertIsNotNone(line, output)
        return json.loads(line[len(RESULT_MARK):])

    def test_template_starts_in_geoblender_mode(self) -> None:
        """RF-003-25: con la plantilla, la extensión habilitada, el espacio principal de
        Geoblender (marcado) y «Layout», escena vacía en metros; el Blender normal sin
        cambios; desinstalar deja el perfil como estaba."""
        self.assertEqual(dev_install.main(["--perfil", str(self.profile)], root=ROOT), 0)
        prefs = self.profile / "config" / "userpref.blend"
        self.assertTrue(prefs.is_file())
        before_hash = sha256(prefs)
        before = listing(self.profile)
        code = install_app_template.main(
            ["--perfil", str(self.profile), "--lanzador", str(self.launcher_dir)], root=ROOT)
        self.assertEqual(code, 0)
        installed = install_app_template.template_dir(self.profile / "scripts")
        self.assertTrue(install_app_template.same_files(ROOT / layout.APP_TEMPLATE_RELPATH,
                                                        installed))
        self.assertTrue((self.launcher_dir / layout.LAUNCHER_NAME).is_file())

        result = self.run_template()
        self.assertEqual(result["template"], layout.APP_TEMPLATE_ID)
        self.assertTrue(result["loaded"])
        self.assertEqual(len(result["enabled"]), 1, result)
        workspaces = result["workspaces"]
        main = install_app_template_main_workspace()
        self.assertEqual(workspaces, {main: True, "Layout": False})
        self.assertEqual(result["objects"], 0)
        self.assertEqual(result["units"], ["METRIC", "METERS"])
        self.assertEqual(result["requested"], [main])
        self.assertEqual(sha256(prefs), before_hash)

        code = install_app_template.main(
            ["--perfil", str(self.profile), "--lanzador", str(self.launcher_dir),
             "--desinstalar"], root=ROOT)
        self.assertEqual(code, 0)
        self.assertFalse(installed.exists())
        self.assertFalse((self.launcher_dir / layout.LAUNCHER_NAME).exists())
        # Blender escribe la caché de código compilado de la extensión que carga, aunque se
        # le pida que no (PYTHONDONTWRITEBYTECODE): eso no es la plantilla.
        changes = [change for change in listing_changes(before, listing(self.profile))
                   if CACHE_FOLDER not in change]
        self.assertEqual(changes, [], "; ".join(changes))


def install_app_template_main_workspace() -> str:
    """El espacio principal de ``layouts.toml`` (el que lee ``make_app_template``)."""
    import make_app_template

    return make_app_template.main_workspace(ROOT)


if __name__ == "__main__":
    unittest.main()

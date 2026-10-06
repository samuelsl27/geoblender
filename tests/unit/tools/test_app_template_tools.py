# SPDX-License-Identifier: GPL-3.0-or-later
"""Plantilla de aplicación y lanzador: las herramientas sin Blender (spec 003, T34;
RF-003-25; ADR-0003; CW §7; D-2).

- ``tools/install_app_template.py``: la carpeta de guiones del usuario sale de
  ``--perfil``, ``BLENDER_USER_SCRIPTS``, ``BLENDER_USER_RESOURCES`` o
  ``%APPDATA%\\Blender Foundation\\Blender\\<serie>``; instalar copia la plantilla entera y
  el lanzador (dos veces, igual); nunca sustituye una carpeta o un lanzador que no son de
  Geoblender; desinstalar quita solo lo suyo y deja el perfil como estaba.
- ``tools/make_app_template.py``: instala la extensión en un perfil temporal, lanza el
  guion de dentro de Blender sin configuración de fábrica con ese perfil y el espacio
  principal de ``layouts.toml``, y borra el perfil; si Blender falla, no es verde.
- ``packaging/Geoblender.cmd``: CRLF y ASCII, abre ``--app-template`` de la plantilla con
  ``GEOBLENDER_BLENDER`` o la ruta por defecto y, sin Blender, lo dice y sale con 1.
- Los ficheros de la plantilla están en el repositorio con su ``LICENSE`` CC0.
"""

import contextlib
import io
import os
import shutil
import subprocess
import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path

from tests.support.harness import listing
from tests.support.repo import ROOT, tools_on_path

tools_on_path()

import install_app_template  # noqa: E402
import make_app_template  # noqa: E402
from gbtools import layout  # noqa: E402
from gbtools.blender import BlenderInstall  # noqa: E402

INSTALL = BlenderInstall(exe=Path("blender.exe"), python=Path("python.exe"), version=(5, 2, 1))
TEMPLATE = ROOT / layout.APP_TEMPLATE_RELPATH
LAUNCHER = ROOT / layout.LAUNCHER_RELPATH


def quiet(function: object, *args: object, **kwargs: object) -> tuple[object, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        result = function(*args, **kwargs)  # type: ignore[operator]
    return result, out.getvalue()


class InstallTest(unittest.TestCase):
    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="gb-plantilla-prueba-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.profile = self.work / "perfil"
        self.desk = self.work / "escritorio"
        (self.profile / "config").mkdir(parents=True)
        (self.profile / "config" / "userpref.blend").write_bytes(b"BLENDER-v502")
        other = self.profile / "scripts" / "startup" / "bl_app_templates_user" / "Otra"
        other.mkdir(parents=True)
        (other / "__init__.py").write_text("# otra plantilla\n", encoding="utf-8")

    def run_main(self, *args: str) -> tuple[int, str]:
        code, output = quiet(install_app_template.main,
                             ["--perfil", str(self.profile), "--lanzador", str(self.desk),
                              *args], root=ROOT, environ={},
                             desktop=lambda _env: self.work / "nunca")
        return int(code), output  # type: ignore[arg-type]

    def test_scripts_dir(self) -> None:
        """D-2: la carpeta de guiones del usuario, por orden de preferencia."""
        series = install_app_template.blender_series(ROOT)
        self.assertEqual(series, "5.2")
        scripts = install_app_template.user_scripts_dir
        self.assertEqual(scripts({}, series, Path("P")), Path("P") / "scripts")
        self.assertEqual(scripts({"BLENDER_USER_SCRIPTS": "S", "BLENDER_USER_RESOURCES": "R"},
                                 series), Path("S"))
        self.assertEqual(scripts({"BLENDER_USER_RESOURCES": "R"}, series), Path("R") / "scripts")
        self.assertEqual(scripts({"APPDATA": "A"}, series),
                         Path("A") / "Blender Foundation" / "Blender" / "5.2" / "scripts")
        self.assertEqual(install_app_template.template_dir(Path("S")),
                         Path("S") / "startup" / "bl_app_templates_user" / layout.APP_TEMPLATE_ID)

    def test_install_twice_and_uninstall(self) -> None:
        """RF-003-25: instalar copia la plantilla y el lanzador (dos veces, igual);
        desinstalar quita solo eso y el perfil queda como estaba."""
        before = listing(self.profile)
        for _ in range(2):
            code, output = self.run_main()
            self.assertEqual(code, 0, output)
        target = install_app_template.template_dir(self.profile / "scripts")
        self.assertTrue(install_app_template.same_files(TEMPLATE, target))
        self.assertEqual((self.desk / layout.LAUNCHER_NAME).read_bytes(), LAUNCHER.read_bytes())
        self.assertFalse((self.work / "nunca").exists())
        code, output = self.run_main("--desinstalar")
        self.assertEqual(code, 0, output)
        self.assertFalse(target.exists())
        self.assertFalse((self.desk / layout.LAUNCHER_NAME).exists())
        self.assertEqual({k: v for k, v in listing(self.profile).items() if v[0] >= 0},
                         {k: v for k, v in before.items() if v[0] >= 0})

    def test_never_replaces_foreign(self) -> None:
        """Una carpeta o un lanzador con ese nombre que no son de Geoblender no se tocan."""
        target = install_app_template.template_dir(self.profile / "scripts")
        target.mkdir(parents=True)
        (target / "__init__.py").write_text("# de otra persona\n", encoding="utf-8")
        code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("no es la plantilla de Geoblender", output)
        self.assertEqual(sorted(p.name for p in target.iterdir()), ["__init__.py"])
        self.assertFalse(self.desk.exists())
        shutil.rmtree(target)
        self.desk.mkdir()
        (self.desk / layout.LAUNCHER_NAME).write_text("@echo otro\r\n", encoding="utf-8")
        code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("no es el lanzador de Geoblender", output)
        self.assertFalse(target.exists())
        code, output = self.run_main("--desinstalar")
        self.assertEqual(code, 0)
        self.assertTrue((self.desk / layout.LAUNCHER_NAME).exists())


class FakeBlender:
    """Hace de Blender: escribe los cuatro ficheros de la plantilla y termina bien."""

    def __init__(self, code: int = 0) -> None:
        self.calls: list[tuple[list[str], dict[str, str]]] = []
        self.code = code

    def __call__(self, cmd: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        args = [str(part) for part in cmd]
        self.calls.append((args, dict(kwargs.get("env") or {})))  # type: ignore[arg-type]
        output = Path(args[args.index("--salida") + 1])
        for name in make_app_template.OUTPUT_FILES:
            (output / name).write_bytes(b"x")
        return subprocess.CompletedProcess(args, self.code,
                                           f"{make_app_template.END_LINE} 4 ficheros\n", "")


class MakeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="gb-plantilla-prueba-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.profiles: list[Path] = []

    def install_extension(self, repo: Path, profile: Path) -> int:
        self.assertEqual(repo, ROOT)
        self.assertTrue(profile.is_dir())
        self.profiles.append(profile)
        return 0

    def run_main(self, fake: FakeBlender) -> tuple[int, str]:
        code, output = quiet(make_app_template.main, ["--salida", str(self.work)], root=ROOT,
                             runner=fake, locate=lambda _minimum: INSTALL,
                             install_extension=self.install_extension)
        return int(code), output  # type: ignore[arg-type]

    def test_generates_with_a_temporary_profile(self) -> None:
        """Plan 003 §5.4, 13: perfil temporal con la extensión, Blender sin fábrica con el
        guion y el espacio principal, y el perfil borrado al terminar."""
        fake = FakeBlender()
        code, output = self.run_main(fake)
        self.assertEqual(code, 0, output)
        ((args, env),) = fake.calls
        self.assertNotIn("--factory-startup", args)
        self.assertEqual(Path(args[args.index("--python") + 1]),
                         ROOT / make_app_template.SCRIPT)
        self.assertEqual(args[args.index("--principal") + 1],
                         make_app_template.main_workspace(ROOT))
        self.assertEqual(env["BLENDER_USER_RESOURCES"], str(self.profiles[0]))
        self.assertFalse(self.profiles[0].exists())
        for name in make_app_template.OUTPUT_FILES:
            self.assertIn(name, output)

    def test_blender_failure_is_not_green(self) -> None:
        """Si el guion falla, «NO VERDE» y código 1; el perfil se borra igual."""
        code, output = self.run_main(FakeBlender(code=1))
        self.assertEqual(code, 1)
        self.assertIn("NO VERDE", output)
        self.assertFalse(self.profiles[0].exists())


class LauncherTest(unittest.TestCase):
    def test_launcher_text(self) -> None:
        """CW §7, D-2: CRLF, ASCII, la plantilla y ``GEOBLENDER_BLENDER`` o la ruta por
        defecto; el perfil aislado, como opción comentada."""
        data = LAUNCHER.read_bytes()
        data.decode("ascii")
        self.assertNotIn(b"\n", data.replace(b"\r\n", b""))
        text = data.decode("ascii")
        self.assertIn(f"--app-template {layout.APP_TEMPLATE_ID} %*", text)
        self.assertIn("GEOBLENDER_BLENDER", text)
        self.assertIn(r"Blender 5.2\blender.exe", text)
        self.assertIn('rem set "BLENDER_USER_RESOURCES=', text)

    def test_launcher_without_blender(self) -> None:
        """Spec §8: sin Blender en la ruta, el lanzador lo dice con la ruta y cómo indicar
        otra, sin arrancar nada, y sale con 1."""
        env = dict(os.environ, GEOBLENDER_BLENDER=r"C:\no\existe\blender.exe")
        result = subprocess.run(["cmd", "/c", str(LAUNCHER)], env=env,
                                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                timeout=60)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(r"C:\no\existe\blender.exe", result.stdout)
        self.assertIn("GEOBLENDER_BLENDER", result.stdout)


class TemplateFilesTest(unittest.TestCase):
    def test_template_files(self) -> None:
        """Plan 003 §5.1: la plantilla con su código (GPL), sus ficheros generados y su
        ``LICENSE`` CC0 (LIC-04)."""
        names = sorted(path.name for path in TEMPLATE.iterdir())
        self.assertEqual(names, ["LICENSE", "__init__.py", "splash.png", "splash_2x.png",
                                 "startup.blend", "userpref.blend"])
        self.assertEqual((TEMPLATE / "LICENSE").read_bytes(),
                         (ROOT / "LICENSES" / "CC0-1.0.txt").read_bytes())
        self.assertTrue(install_app_template.is_our_template(TEMPLATE))
        self.assertTrue((TEMPLATE / "userpref.blend").read_bytes().startswith(b"BLENDER"))


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: GPL-3.0-or-later
"""Localización de Blender y órdenes aisladas (``gbtools.blender``; plan 001 §5.3).

- RF-001-08: se usa el Blender de ``GEOBLENDER_BLENDER`` (ruta a ``blender.exe`` o a su
  carpeta) y, sin la variable, la ruta por defecto; el Python es el de esa instalación.
- RF-001-07: Blender inexistente o anterior al mínimo del manifiesto es un error de
  entorno que dice qué falta y cómo corregirlo; el intérprete se compara con el Python
  de ese Blender.
- RF-001-09: las pruebas de Blender se lanzan en segundo plano, con la configuración de
  fábrica, ``--python-exit-code 1`` y un perfil temporal.

El ejecutor de órdenes es simulado: ninguna prueba lanza Blender, salvo
``test_real_install``, que se omite si no está la instalación por defecto.
"""

import os
import subprocess
import sys
import unittest
from collections.abc import Sequence
from pathlib import Path
from unittest import mock

from tests.support.repo import EXT, ROOT, tools_on_path
from tests.support.resources import skip_reason
from tests.support.trees import temp_tree

tools_on_path()

from gbtools import blender  # noqa: E402
from gbtools.blender import BlenderInstall, EnvironmentProblem  # noqa: E402

MIN = (5, 2, 0)
# Estas pruebas miran la ruta por defecto, no GEOBLENDER_BLENDER (RF-001-08).
NO_DEFAULT_BLENDER = skip_reason(
    "blender",
    f"instale Blender 5.2 en la ruta por defecto «{blender.DEFAULT_BLENDER_EXE}»",
)
VERSION_521 = (
    "Blender 5.2.1 LTS\n"
    "\tbuild date: 2026-08-25\n"
    "\tbuild time: 02:38:20\n"
    "\tbuild hash: 9e2066aef7ef\n"
)


class FakeRunner:
    """Ejecutor simulado: anota cada orden y devuelve una salida fija."""

    def __init__(self, stdout: str = VERSION_521, returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def __call__(
        self, cmd: Sequence[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(cmd), kwargs))
        return subprocess.CompletedProcess(list(cmd), self.returncode, self.stdout, "")


def _install_tree(version_folder: str = "5.2") -> dict[str, str]:
    """Una instalación falsa: ``blender.exe`` y el Python de ``<versión>/``."""
    return {
        "Blender/blender.exe": "",
        f"Blender/{version_folder}/python/bin/python.exe": "",
    }


class ParseVersionTest(unittest.TestCase):
    def test_parse_version(self) -> None:
        """RF-001-07: la versión sale de la primera línea de ``blender --version``."""
        self.assertEqual(blender.parse_version("Blender 5.2.1 LTS"), (5, 2, 1))
        self.assertEqual(blender.parse_version(VERSION_521), (5, 2, 1))
        self.assertEqual(blender.parse_version("Blender 5.10.0 Alpha\r\n"), (5, 10, 0))
        self.assertEqual(
            blender.parse_version("Color management: x\nBlender 6.0.12\n"), (6, 0, 12)
        )
        for text in ("", "Blender", "Blender 5.2", "Python 3.13.13", "Blender x.y.z"):
            with self.subTest(texto=text), self.assertRaises(ValueError):
                blender.parse_version(text)


class LocateBlenderTest(unittest.TestCase):
    def test_env_var_exe(self) -> None:
        """RF-001-08: ``GEOBLENDER_BLENDER`` con la ruta a ``blender.exe``."""
        with temp_tree(_install_tree()) as tmp:
            exe = tmp / "Blender" / "blender.exe"
            runner = FakeRunner()
            install = blender.locate_blender(
                MIN, environ={blender.ENV_BLENDER: str(exe)}, runner=runner
            )
            self.assertEqual(install.exe, exe)
            self.assertEqual(install.version, (5, 2, 1))
            self.assertEqual(
                install.python, tmp / "Blender" / "5.2" / "python" / "bin" / "python.exe"
            )
            self.assertEqual(len(runner.calls), 1)
            cmd, kwargs = runner.calls[0]
            self.assertEqual(cmd, [str(exe), "--version"])
            self.assertIsNotNone(kwargs.get("timeout"), "nunca se espera sin límite")

    def test_env_var_dir(self) -> None:
        """RF-001-08: ``GEOBLENDER_BLENDER`` con la carpeta de la instalación."""
        with temp_tree(_install_tree()) as tmp:
            folder = tmp / "Blender"
            for value in (str(folder), str(folder) + os.sep, f'"{folder}"', f" {folder} "):
                with self.subTest(valor=value):
                    install = blender.locate_blender(
                        MIN, environ={blender.ENV_BLENDER: value}, runner=FakeRunner()
                    )
                    self.assertEqual(install.exe, folder / "blender.exe")

    def test_default_path(self) -> None:
        """RF-001-08: sin la variable (o vacía), la ruta por defecto de Blender 5.2."""
        self.assertEqual(
            blender.DEFAULT_BLENDER_EXE,
            Path(r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"),
        )
        self.assertEqual(blender.ENV_BLENDER, "GEOBLENDER_BLENDER")
        with temp_tree(_install_tree()) as tmp:
            fake = tmp / "Blender" / "blender.exe"
            with mock.patch.object(blender, "DEFAULT_BLENDER_EXE", fake):
                for environ in ({}, {blender.ENV_BLENDER: ""}, {"PATH": "x"}):
                    with self.subTest(entorno=environ):
                        runner = FakeRunner()
                        install = blender.locate_blender(MIN, environ, runner)
                        self.assertEqual(install.exe, fake)
                        self.assertEqual(runner.calls[0][0], [str(fake), "--version"])

    def test_default_environ_is_os_environ(self) -> None:
        """RF-001-08: sin ``environ`` explícito se lee el entorno del proceso."""
        with temp_tree(_install_tree()) as tmp:
            exe = tmp / "Blender" / "blender.exe"
            with mock.patch.dict(os.environ, {blender.ENV_BLENDER: str(exe)}):
                install = blender.locate_blender(MIN, runner=FakeRunner())
            self.assertEqual(install.exe, exe)

    def test_missing_exe(self) -> None:
        """RF-001-07, RF-001-08: ruta inexistente → el mensaje nombra la variable, su
        valor y la ruta por defecto, y no se ejecuta nada."""
        with temp_tree({"vacia/": ""}) as tmp:
            for value in (str(tmp / "no-existe" / "blender.exe"), str(tmp / "vacia")):
                with self.subTest(valor=value):
                    runner = FakeRunner()
                    with self.assertRaises(EnvironmentProblem) as ctx:
                        blender.locate_blender(
                            MIN, environ={blender.ENV_BLENDER: value}, runner=runner
                        )
                    message = str(ctx.exception)
                    self.assertIn("GEOBLENDER_BLENDER", message)
                    self.assertIn(value, message)
                    self.assertIn(str(blender.DEFAULT_BLENDER_EXE), message)
                    self.assertEqual(runner.calls, [])
            missing = tmp / "no-existe" / "blender.exe"
            with mock.patch.object(blender, "DEFAULT_BLENDER_EXE", missing):
                runner = FakeRunner()
                with self.assertRaises(EnvironmentProblem) as ctx:
                    blender.locate_blender(MIN, environ={}, runner=runner)
                message = str(ctx.exception)
                self.assertIn(str(missing), message)
                self.assertIn("GEOBLENDER_BLENDER", message)
                self.assertIn("no está definida", message)
                self.assertEqual(runner.calls, [])

    def test_old_version_rejected(self) -> None:
        """RF-001-07: Blender 5.1.0 es anterior al mínimo 5.2.0: error con ambas."""
        with temp_tree(_install_tree("5.1")) as tmp:
            exe = tmp / "Blender" / "blender.exe"
            with self.assertRaises(EnvironmentProblem) as ctx:
                blender.locate_blender(
                    MIN,
                    environ={blender.ENV_BLENDER: str(exe)},
                    runner=FakeRunner("Blender 5.1.0\n"),
                )
            message = str(ctx.exception)
            self.assertIn("5.1.0", message)
            self.assertIn("5.2.0", message)
            self.assertIn(str(exe), message)
            self.assertIn("GEOBLENDER_BLENDER", message)

    def test_newer_versions_accepted(self) -> None:
        """RF-001-07: el mínimo es inclusivo y una versión posterior también vale."""
        for text, folder in (("Blender 5.2.0\n", "5.2"), ("Blender 5.3.4\n", "5.3")):
            with self.subTest(version=text), temp_tree(_install_tree(folder)) as tmp:
                exe = tmp / "Blender" / "blender.exe"
                install = blender.locate_blender(
                    MIN, environ={blender.ENV_BLENDER: str(exe)}, runner=FakeRunner(text)
                )
                self.assertEqual(install.version, blender.parse_version(text))

    def test_python_derived_from_version(self) -> None:
        """RF-001-08: el Python es ``<carpeta>/<mayor>.<menor>/python/bin/python.exe``
        de esa misma instalación; si falta, es un error de entorno."""
        with temp_tree(_install_tree("5.3")) as tmp:
            exe = tmp / "Blender" / "blender.exe"
            install = blender.locate_blender(
                MIN,
                environ={blender.ENV_BLENDER: str(exe)},
                runner=FakeRunner("Blender 5.3.0\n"),
            )
            self.assertEqual(
                install.python, tmp / "Blender" / "5.3" / "python" / "bin" / "python.exe"
            )
        with temp_tree({"Blender/blender.exe": ""}) as tmp:
            exe = tmp / "Blender" / "blender.exe"
            with self.assertRaises(EnvironmentProblem) as ctx:
                blender.locate_blender(
                    MIN, environ={blender.ENV_BLENDER: str(exe)}, runner=FakeRunner()
                )
            self.assertIn(str(tmp / "Blender" / "5.2" / "python"), str(ctx.exception))

    def test_version_command_fails(self) -> None:
        """RF-001-07: si ``blender --version`` falla o no dice su versión, es un error
        de entorno con la orden, no una excepción sin explicar."""
        with temp_tree(_install_tree()) as tmp:
            exe = tmp / "Blender" / "blender.exe"
            environ = {blender.ENV_BLENDER: str(exe)}

            def raises(error: BaseException) -> blender.Runner:
                def runner(cmd: Sequence[str], **_: object) -> subprocess.CompletedProcess[str]:
                    raise error

                return runner

            runners = {
                "código 3": FakeRunner(returncode=3),
                "sin versión": FakeRunner("hola\n"),
                "OSError": raises(OSError("acceso denegado")),
                "tiempo": raises(subprocess.TimeoutExpired([str(exe)], 60)),
            }
            for name, runner in runners.items():
                with self.subTest(caso=name):
                    with self.assertRaises(EnvironmentProblem) as ctx:
                        blender.locate_blender(MIN, environ, runner)
                    self.assertIn(str(exe), str(ctx.exception))

    @unittest.skipUnless(blender.DEFAULT_BLENDER_EXE.is_file(), NO_DEFAULT_BLENDER)
    def test_real_install(self) -> None:
        """RF-001-08: con el ejecutor real, la instalación por defecto es 5.2 o posterior
        y su Python existe (``blender --version`` no abre ningún perfil)."""
        install = blender.locate_blender(MIN, environ={})
        self.assertEqual(install.exe, blender.DEFAULT_BLENDER_EXE)
        self.assertGreaterEqual(install.version, MIN)
        self.assertTrue(install.python.is_file())


class InterpreterTest(unittest.TestCase):
    def test_is_blender_python(self) -> None:
        """RF-001-07: solo el Python de la instalación localizada es el correcto (sin
        distinguir mayúsculas ni separadores en Windows)."""
        with temp_tree(_install_tree()) as tmp:
            python = tmp / "Blender" / "5.2" / "python" / "bin" / "python.exe"
            install = BlenderInstall(tmp / "Blender" / "blender.exe", python, (5, 2, 1))
            self.assertTrue(blender.is_blender_python(install, str(python)))
            if os.name == "nt":
                self.assertTrue(blender.is_blender_python(install, str(python).upper()))
                self.assertTrue(
                    blender.is_blender_python(install, str(python).replace("\\", "/"))
                )
            other = tmp / "Otro" / "python.exe"
            self.assertFalse(blender.is_blender_python(install, str(other)))
            self.assertFalse(blender.is_blender_python(install, ""))

    def test_this_interpreter(self) -> None:
        """RF-001-07: las pruebas unitarias se ejecutan con el Python de Blender."""
        if not blender.DEFAULT_BLENDER_EXE.is_file():
            self.skipTest(NO_DEFAULT_BLENDER)
        install = blender.locate_blender(MIN, environ={})
        self.assertTrue(blender.is_blender_python(install, sys.executable))


class CommandsTest(unittest.TestCase):
    install = BlenderInstall(
        Path(r"C:\B\blender.exe"), Path(r"C:\B\5.2\python\bin\python.exe"), (5, 2, 1)
    )

    def test_python_cmd(self) -> None:
        """RF-001-08: el Python de Blender, sin bytecode, sin el site-packages del
        usuario y en UTF-8."""
        self.assertEqual(
            blender.python_cmd(self.install, "-m", "unittest"),
            [str(self.install.python), "-B", "-s", "-X", "utf8", "-m", "unittest"],
        )

    def test_background_cmd(self) -> None:
        """RF-001-09: segundo plano, configuración de fábrica y ``--python-exit-code 1``
        siempre; los argumentos del guion, tras ``--``."""
        script = Path("tools") / "run_blender_tests.py"
        cmd = blender.background_cmd(self.install, script, "--carpeta", "tests/blender")
        self.assertEqual(
            cmd,
            [
                str(self.install.exe),
                "-b",
                "--factory-startup",
                "--python-exit-code",
                "1",
                "--python",
                str(script),
                "--",
                "--carpeta",
                "tests/blender",
            ],
        )
        self.assertEqual(
            blender.background_cmd(self.install, script)[:8], cmd[:8], "sin argumentos"
        )

    def test_profile_cmd(self) -> None:
        """RF-001-09: igual que la de fondo pero sin ``--factory-startup`` (solo con un
        perfil temporal: oculta la extensión instalada, plan §2.1, 13)."""
        script = Path("x.py")
        cmd = blender.profile_cmd(self.install, script, "a")
        self.assertEqual(
            cmd,
            [
                str(self.install.exe),
                "-b",
                "--python-exit-code",
                "1",
                "--python",
                str(script),
                "--",
                "a",
            ],
        )
        self.assertNotIn("--factory-startup", cmd)

    def test_extension_cmd(self) -> None:
        """RF-001-02: ``blender --factory-startup --command extension …``."""
        self.assertEqual(
            blender.extension_cmd(self.install, "validate", EXT),
            [
                str(self.install.exe),
                "--factory-startup",
                "--command",
                "extension",
                "validate",
                EXT,
            ],
        )

    def test_python_env(self) -> None:
        """RF-001-08: ``PYTHONPATH`` a ``.deps/site`` (sustituye al ajeno), sin bytecode,
        sin site-packages del usuario y en UTF-8; no cambia el entorno de partida."""
        base = {"PATH": "p", "PYTHONPATH": "ajeno", "PYTHONUTF8": "0"}
        env = blender.python_env(ROOT, base)
        self.assertEqual(env["PYTHONPATH"], str(ROOT / ".deps" / "site"))
        self.assertEqual(env["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertEqual(env["PYTHONNOUSERSITE"], "1")
        self.assertEqual(env["PYTHONUTF8"], "1")
        self.assertEqual(env["PATH"], "p")
        self.assertEqual(base["PYTHONPATH"], "ajeno", "el entorno de partida no cambia")
        with mock.patch.dict(os.environ, {"GB_PRUEBA_ENTORNO": "1"}):
            self.assertEqual(blender.python_env(ROOT)["GB_PRUEBA_ENTORNO"], "1")

    def test_isolated_env(self) -> None:
        """RF-001-09: perfil temporal con ``BLENDER_USER_RESOURCES`` y sin las variables
        ``BLENDER_USER_*`` que lo sustituirían por carpetas del perfil real."""
        base = {
            "PATH": "p",
            "BLENDER_USER_RESOURCES": "real",
            "BLENDER_USER_CONFIG": "real-config",
            "BLENDER_USER_SCRIPTS": "real-scripts",
            "BLENDER_USER_EXTENSIONS": "real-ext",
            "BLENDER_USER_DATAFILES": "real-data",
        }
        profile = Path("perfil-temporal")
        env = blender.isolated_env(profile, base)
        self.assertEqual(env["BLENDER_USER_RESOURCES"], str(profile))
        self.assertEqual(env["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertEqual(env["PATH"], "p")
        for name in (
            "BLENDER_USER_CONFIG",
            "BLENDER_USER_SCRIPTS",
            "BLENDER_USER_EXTENSIONS",
            "BLENDER_USER_DATAFILES",
        ):
            with self.subTest(variable=name):
                self.assertNotIn(name, env)
        self.assertEqual(base["BLENDER_USER_RESOURCES"], "real")

    def test_run(self) -> None:
        """RF-001-06: ``run`` captura la salida en UTF-8 y devuelve el código."""
        result = blender.run(
            [sys.executable, "-B", "-s", "-c", "import sys; print('ñandú'); sys.exit(3)"],
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            timeout=60,
        )
        self.assertEqual(result.returncode, 3)
        self.assertEqual(result.stdout.strip(), "ñandú")


if __name__ == "__main__":
    unittest.main()

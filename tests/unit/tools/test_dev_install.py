# SPDX-License-Identifier: GPL-3.0-or-later
"""La instalación de desarrollo, ``tools/dev_install.py`` (plan 001 §5.4.14).

- RF-001-28: el perfil (``--perfil``, ``GEOBLENDER_DEV_PROFILE`` o
  ``%LOCALAPPDATA%\\Geoblender\\dev\\blender-5.2``) se rechaza sin copiar nada si es una
  ruta UNC, está en una unidad de red, dentro del repositorio o dentro de la
  configuración normal de Blender; si no, la extensión se copia (solo lo que cambia, con
  las exclusiones del manifiesto) a ``<perfil>/extensions/user_default/geoblender`` y un
  Blender en segundo plano, con ``BLENDER_USER_RESOURCES`` = perfil y sin las
  variables ``BLENDER_USER_*`` que lo sustituirían, la habilita y guarda las
  preferencias de ese perfil; ``--abrir`` lo abre con interfaz con ese perfil y
  ``--desinstalar`` la deshabilita y borra su carpeta.

Ninguna prueba lanza Blender (ejecutor y lanzador simulados) ni toca una unidad de red:
el tipo de unidad lo da una función simulada. La prueba con el Blender real está en
``tests/arnes/test_harness_blender.py`` (``tools/check.py --completo``).
"""

import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from tests.support.repo import (
    EXT,
    ROOT,
    manifest_without_wheels,
    real_manifest,
    tools_on_path,
)
from tests.support.trees import temp_tree

tools_on_path()

import dev_install  # noqa: E402
from gbtools import blender, manifest  # noqa: E402
from gbtools.blender import BlenderInstall  # noqa: E402

FAKE_BLENDER = Path(tempfile.gettempdir()) / "geoblender-falso" / "Blender"
INSTALL = BlenderInstall(
    exe=FAKE_BLENDER / "blender.exe",
    python=FAKE_BLENDER / "5.2" / "python" / "bin" / "python.exe",
    version=(5, 2, 1),
)
MANIFEST = manifest.MANIFEST_RELPATH


# El id de la extensión, del manifiesto real, al usarlo y no al importar el módulo
# (convergencia, T56).
def _module() -> str:
    return f"bl_ext.user_default.{real_manifest()['id']}"


def _extension_rel() -> Path:
    return Path("extensions") / "user_default" / str(real_manifest()["id"])


DRIVE_FIXED = 3
DRIVE_REMOTE = 4
ENABLED = "GEOBLENDER-DEV listada=1 habilitada=1 errores=0\n"
DISABLED = "GEOBLENDER-DEV listada=0 habilitada=0 errores=0\n"
SPDX = "# SPDX-License-Identifier: GPL-3.0-or-later\n"


def _fixed(root: str) -> int:
    """Tipo de unidad simulado: todas fijas (locales)."""
    return DRIVE_FIXED


def _remote(letter: str) -> Callable[[str], int]:
    def drive_type(root: str) -> int:
        return DRIVE_REMOTE if root.upper().startswith(letter.upper()) else DRIVE_FIXED

    return drive_type


@dataclass
class Call:
    cmd: list[str]
    env: dict[str, str]
    cwd: Path | None
    script: str


@dataclass
class FakeRunner:
    """Ejecutor simulado: anota las órdenes y el guion, y responde por acción."""

    results: dict[str, tuple[int, str, str]] = field(
        default_factory=lambda: {"habilitar": (0, ENABLED, ""), "deshabilitar": (0, DISABLED, "")}
    )
    calls: list[Call] = field(default_factory=list)

    def __call__(
        self,
        cmd: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: Path | None = None,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        parts = [str(part) for part in cmd]
        script = Path(parts[parts.index("--python") + 1])
        self.calls.append(Call(parts, dict(env or {}), cwd, script.read_text(encoding="utf-8")))
        action = parts[parts.index("--") + 1]
        code, stdout, stderr = self.results[action]
        return subprocess.CompletedProcess(parts, code, stdout, stderr)

    def actions(self) -> list[str]:
        return [call.cmd[call.cmd.index("--") + 1] for call in self.calls]


@dataclass
class FakeLauncher:
    calls: list[tuple[list[str], dict[str, str]]] = field(default_factory=list)

    def __call__(self, cmd: Sequence[str], *, env: Mapping[str, str], cwd: str) -> object:
        self.calls.append(([str(part) for part in cmd], dict(env)))
        return object()


@dataclass
class Outcome:
    code: int
    out: str
    err: str
    runner: FakeRunner

    @property
    def text(self) -> str:
        return self.out + self.err


@contextlib.contextmanager
def _repo() -> Iterator[Path]:
    """Copia mínima del repositorio: la extensión con el manifiesto real, ficheros de
    agentes y un ``__pycache__`` (que no se copian)."""
    files: dict[str, str | bytes] = {
        MANIFEST: manifest_without_wheels(),
        f"{EXT}/__init__.py": SPDX,
        f"{EXT}/core/__init__.py": SPDX,
        f"{EXT}/AGENTS.md": "# reglas\n",
        f"{EXT}/CLAUDE.md": "@AGENTS.md\n",
        f"{EXT}/core/__pycache__/x.cpython-313.pyc": b"x",
    }
    with temp_tree(files) as root:
        yield root


def _run(
    root: Path,
    *args: str,
    environ: Mapping[str, str] | None = None,
    runner: FakeRunner | None = None,
    launcher: FakeLauncher | None = None,
    drive_type: Callable[[str], int] = _fixed,
) -> Outcome:
    runner = FakeRunner() if runner is None else runner
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = dev_install.main(
            list(args),
            root=root,
            environ=dict(environ if environ is not None else {}),
            runner=runner,
            locate=lambda minimum: INSTALL,
            launcher=launcher if launcher is not None else FakeLauncher(),
            drive_type=drive_type,
        )
    return Outcome(code, out.getvalue(), err.getvalue(), runner)


def _files(folder: Path) -> list[str]:
    if not folder.exists():
        return []
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())


def _temp_work_folders() -> set[str]:
    return {
        name
        for name in os.listdir(tempfile.gettempdir())
        if name.startswith(dev_install.TEMP_PREFIX)
    }


class RejectedProfileTest(unittest.TestCase):
    def assertRejected(self, result: Outcome, *texts: str) -> None:
        self.assertEqual(result.code, 2, result.text)
        self.assertEqual(result.runner.calls, [])
        for text in texts:
            self.assertIn(text, result.text)

    def test_network_drive_rejected(self) -> None:
        """RF-001-28: un perfil en una unidad de red (``GetDriveTypeW`` =
        ``DRIVE_REMOTE``), por ``--perfil`` o por ``GEOBLENDER_DEV_PROFILE``, se rechaza
        con 2, sin copiar nada ni lanzar Blender."""
        profile = "Q:\\perfiles\\geoblender"
        with _repo() as root:
            for args, environ in (
                (("--perfil", profile), {}),
                ((), {"GEOBLENDER_DEV_PROFILE": profile}),
            ):
                with self.subTest(args=args, entorno=environ):
                    result = _run(root, *args, environ=environ, drive_type=_remote("Q:"))
                    self.assertRejected(result, profile, "unidad de red")
        self.assertEqual(dev_install.DRIVE_REMOTE, DRIVE_REMOTE)

    def test_unc_rejected(self) -> None:
        """RF-001-28: un perfil con ruta UNC (``\\\\servidor\\recurso`` o
        ``//servidor/recurso``) se rechaza con 2 sin acceder a la red."""

        def no_drive_type(root: str) -> int:
            raise AssertionError("no debe consultar la unidad de una ruta UNC")

        with _repo() as root:
            for profile in ("\\\\servidor\\recurso\\perfil", "//servidor/recurso/perfil"):
                with self.subTest(perfil=profile):
                    result = _run(root, "--perfil", profile, drive_type=no_drive_type)
                    self.assertRejected(result, "UNC")

    def test_profile_inside_repo_rejected(self) -> None:
        """RF-001-28: un perfil dentro del repositorio (o el propio repositorio) se
        rechaza con 2 sin crear nada; también uno dentro de la configuración normal de
        Blender (``%APPDATA%\\Blender Foundation``)."""
        with _repo() as root:
            for profile in (root / "perfil-dev", root / EXT / "perfil", root):
                with self.subTest(perfil=profile):
                    result = _run(root, "--perfil", str(profile))
                    self.assertRejected(result, "repositorio")
            self.assertFalse((root / "perfil-dev").exists())
            with temp_tree({"Roaming/": ""}) as appdata:
                real = appdata / "Roaming" / "Blender Foundation" / "Blender" / "5.2"
                result = _run(
                    root,
                    "--perfil",
                    str(real),
                    environ={"APPDATA": str(appdata / "Roaming")},
                )
                self.assertRejected(result, "configuración normal de Blender")
                self.assertFalse(real.exists())


class InstallTest(unittest.TestCase):
    def test_enable_uses_isolated_env(self) -> None:
        """RF-001-28: copia la extensión al perfil (sin ``AGENTS.md``, ``CLAUDE.md`` ni
        ``__pycache__``) y la habilita con un Blender en segundo plano **sin**
        ``--factory-startup``, con ``BLENDER_USER_RESOURCES`` = perfil y sin las
        variables ``BLENDER_USER_*`` del usuario; el guion habilita con
        ``default_set=True`` y guarda las preferencias del perfil. Una segunda pasada sin
        cambios no copia nada. La carpeta de trabajo temporal se borra."""
        planted = {name: str(ROOT / "perfil-real") for name in blender.OVERRIDING_USER_VARIABLES}
        before = _temp_work_folders()
        with _repo() as root, temp_tree({"local/": ""}) as other:
            profile = other / "local" / "perfil-dev"
            environ = {**os.environ, **planted}
            result = _run(root, "--perfil", str(profile), environ=environ)
            self.assertEqual(result.code, 0, result.text)
            installed = profile / _extension_rel()
            self.assertEqual(_files(installed), ["__init__.py", "blender_manifest.toml", "core/__init__.py"])
            call = result.runner.calls[0]
            script = Path(call.cmd[call.cmd.index("--python") + 1])
            self.assertEqual(call.cmd, blender.profile_cmd(INSTALL, script, "habilitar", _module()))
            self.assertNotIn("--factory-startup", call.cmd)
            self.assertEqual(call.env["BLENDER_USER_RESOURCES"], str(profile))
            for name in blender.OVERRIDING_USER_VARIABLES:
                self.assertNotIn(name, call.env)
            self.assertIn("default_set=True", call.script)
            self.assertIn("save_userpref", call.script)
            self.assertFalse(script.resolve().is_relative_to(root.resolve()))
            self.assertFalse(script.resolve().is_relative_to(profile.resolve()))
            self.assertRegex(result.out, r"copia: \d+ copiados")
            self.assertIn(f'BLENDER_USER_RESOURCES = "{profile}"', result.out)
            self.assertIn(str(INSTALL.exe), result.out)

            again = _run(root, "--perfil", str(profile))
            self.assertEqual(again.code, 0, again.text)
            self.assertIn("copia: 0 copiados, 0 borrados, 3 sin cambios", again.out)
            self.assertEqual(again.runner.actions(), ["habilitar"])
        self.assertEqual(result.runner.actions(), ["habilitar"])
        self.assertEqual(_temp_work_folders(), before)

    def test_default_profile(self) -> None:
        """RF-001-28: sin ``--perfil`` ni ``GEOBLENDER_DEV_PROFILE``, el perfil es
        ``%LOCALAPPDATA%\\Geoblender\\dev\\blender-5.2``; la variable manda sobre el valor
        por defecto y ``--perfil`` sobre los dos; sin ninguno y sin ``LOCALAPPDATA``, 2."""
        local = Path(tempfile.gettempdir()) / "local-falso"
        default = local / "Geoblender" / "dev" / "blender-5.2"
        self.assertEqual(dev_install.resolve_profile(None, {"LOCALAPPDATA": str(local)}), default)
        chosen = Path(tempfile.gettempdir()) / "perfil-elegido"
        self.assertEqual(
            dev_install.resolve_profile(
                None, {"LOCALAPPDATA": str(local), "GEOBLENDER_DEV_PROFILE": str(chosen)}
            ),
            chosen,
        )
        option = Path(tempfile.gettempdir()) / "perfil-opcion"
        self.assertEqual(
            dev_install.resolve_profile(
                str(option), {"LOCALAPPDATA": str(local), "GEOBLENDER_DEV_PROFILE": str(chosen)}
            ),
            option,
        )
        with self.assertRaises(dev_install.UsageError):
            dev_install.resolve_profile(None, {})

        with _repo() as root, temp_tree({"Local/": ""}) as appdata:
            result = _run(root, environ={"LOCALAPPDATA": str(appdata / "Local")})
            self.assertEqual(result.code, 0, result.text)
            profile = appdata / "Local" / "Geoblender" / "dev" / "blender-5.2"
            self.assertTrue((profile / _extension_rel() / "__init__.py").is_file())
            self.assertEqual(
                result.runner.calls[0].env["BLENDER_USER_RESOURCES"], str(profile)
            )
            result = _run(root)
            self.assertEqual(result.code, 2, result.text)
            self.assertIn("LOCALAPPDATA", result.text)

    def test_enable_failure_exit_1(self) -> None:
        """RF-001-28: si Blender no consigue habilitarla (errores, no queda listada, no
        informa o sale con otro código), la orden termina con 1 y lo dice."""
        for case, outcome in {
            "errores": (0, "GEOBLENDER-DEV listada=1 habilitada=0 errores=1\n"
                           "GEOBLENDER-DEV-ERROR ImportError('x')\n", ""),
            "no listada": (0, "GEOBLENDER-DEV listada=0 habilitada=0 errores=0\n", ""),
            "sin informe": (0, "Blender quit\n", ""),
            "excepción": (1, "", "RuntimeError: x\n"),
        }.items():
            runner = FakeRunner({"habilitar": outcome})
            with self.subTest(caso=case), _repo() as root, temp_tree({"p/": ""}) as other:
                result = _run(root, "--perfil", str(other / "p"), runner=runner)
                self.assertEqual(result.code, 1, result.text)
                self.assertIn(_module(), result.text)

    def test_open_launches_blender_with_profile(self) -> None:
        """RF-001-28: ``--abrir`` abre Blender con interfaz (sin ``-b``) con
        ``BLENDER_USER_RESOURCES`` = perfil, sin esperar, después de habilitarla."""
        launcher = FakeLauncher()
        with _repo() as root, temp_tree({"p/": ""}) as other:
            profile = other / "p"
            result = _run(root, "--perfil", str(profile), "--abrir", launcher=launcher)
            self.assertEqual(result.code, 0, result.text)
        self.assertEqual(result.runner.actions(), ["habilitar"])
        self.assertEqual(len(launcher.calls), 1)
        cmd, env = launcher.calls[0]
        self.assertEqual(cmd, [str(INSTALL.exe)])
        self.assertEqual(env["BLENDER_USER_RESOURCES"], str(profile))
        for name in blender.OVERRIDING_USER_VARIABLES:
            self.assertNotIn(name, env)

    def test_uninstall(self) -> None:
        """RF-001-28: ``--desinstalar`` la deshabilita y guarda las preferencias del
        perfil, y borra su carpeta; si no hay nada instalado, no lanza Blender; si no se
        puede deshabilitar, 1 y la carpeta se queda."""
        with _repo() as root, temp_tree({"p/": ""}) as other:
            profile = other / "p"
            self.assertEqual(_run(root, "--perfil", str(profile)).code, 0)
            (profile / "config").mkdir()
            (profile / "config" / "userpref.blend").write_bytes(b"BLENDER")
            result = _run(root, "--perfil", str(profile), "--desinstalar")
            self.assertEqual(result.code, 0, result.text)
            self.assertEqual(result.runner.actions(), ["deshabilitar"])
            call = result.runner.calls[0]
            self.assertEqual(call.env["BLENDER_USER_RESOURCES"], str(profile))
            self.assertIn("save_userpref", call.script)
            self.assertFalse((profile / _extension_rel()).exists())

            result = _run(root, "--perfil", str(profile / "vacio"), "--desinstalar")
            self.assertEqual(result.code, 0, result.text)
            self.assertEqual(result.runner.calls, [])
            self.assertIn("nada que desinstalar", result.out)

            self.assertEqual(_run(root, "--perfil", str(profile)).code, 0)
            failing = FakeRunner({"deshabilitar": (0, ENABLED, "")})
            result = _run(root, "--perfil", str(profile), "--desinstalar", runner=failing)
            self.assertEqual(result.code, 1, result.text)
            self.assertTrue((profile / _extension_rel() / "__init__.py").is_file())

    def test_usage(self) -> None:
        """RF-001-28: una opción desconocida, ``--perfil`` sin valor o ``--abrir`` con
        ``--desinstalar`` dan 2 sin hacer nada; ``--ayuda`` muestra el uso."""
        with _repo() as root:
            for args in (("--otra",), ("--perfil",), ("--abrir", "--desinstalar")):
                with self.subTest(opciones=args):
                    result = _run(root, *args)
                    self.assertEqual(result.code, 2, result.text)
                    self.assertEqual(result.runner.calls, [])
            result = _run(root, "--ayuda")
            self.assertEqual(result.code, 0)
            for option in ("--perfil", "--abrir", "--desinstalar"):
                self.assertIn(option, result.out)


if __name__ == "__main__":
    unittest.main()

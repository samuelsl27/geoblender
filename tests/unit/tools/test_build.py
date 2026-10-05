# SPDX-License-Identifier: GPL-3.0-or-later
"""El empaquetado, ``tools/build.py`` (plan 001 §5.4.13), con un ejecutor simulado.

- RF-001-26: antes de llamar a Blender, el manifiesto (MAN-01, NOM-04) y las ruedas
  (LIC-01, LIC-02: ``geoblender/wheels/`` igual a la lista del manifiesto) no tienen
  incumplimientos; se valida con ``extension validate`` y, si falla, no se genera el zip;
  ``extension build`` lo deja en ``dist/`` y la inspección lo rechaza (y lo borra) si
  tiene ``AGENTS.md``, ``CLAUDE.md``, ``__pycache__``, ``.pyc``/``.pyo``, copias
  ``.blendN`` o ruedas que no están en el manifiesto, si le falta el manifiesto o el
  ``__init__.py`` en la raíz o si no se llama ``<id>-<versión>.zip``.
- RF-001-27: con ``--probar-instalacion``, el zip se instala en otro perfil temporal
  limpio, una sesión nueva sin configuración de fábrica tiene que verlo habilitado
  (control positivo), se desinstala y otra sesión nueva ya no lo ve ni queda su carpeta.
- RF-001-09: Blender se lanza con un perfil temporal en ``%TEMP%`` que se borra al
  terminar.

Ninguna prueba lanza Blender: el ejecutor simulado anota las órdenes y, para
``extension build``, escribe el zip que se le indique. Las pruebas con el Blender real
están en ``test_harness_blender.py``.
"""

import contextlib
import functools
import io
import os
import shutil
import subprocess
import tempfile
import tomllib
import unittest
import zipfile
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from tests.support.repo import (
    EMPTY_WHEELS_TOML,
    EXT,
    manifest_without_wheels,
    tools_on_path,
)
from tests.support.trees import temp_tree

tools_on_path()

import build  # noqa: E402
from gbtools import blender, manifest  # noqa: E402
from gbtools.blender import BlenderInstall, EnvironmentProblem  # noqa: E402

FAKE_BLENDER = Path(tempfile.gettempdir()) / "geoblender-falso" / "Blender"
INSTALL = BlenderInstall(
    exe=FAKE_BLENDER / "blender.exe",
    python=FAKE_BLENDER / "5.2" / "python" / "bin" / "python.exe",
    version=(5, 2, 1),
)
MANIFEST = manifest.MANIFEST_RELPATH


# El manifiesto real sin ruedas: las pruebas no dependen de las que fije cada spec (T45).
# Se lee al usarlo, no al importar el módulo: con un manifiesto ilegible (p. ej. con BOM)
# fallan sus pruebas y no la importación de todas (convergencia, T56).
@functools.cache
def _manifest_text() -> str:
    return manifest_without_wheels()


def _manifest_data() -> dict[str, object]:
    return tomllib.loads(_manifest_text())


def _zip_name() -> str:
    data = _manifest_data()
    return f"{data['id']}-{data['version']}.zip"


def _good_members() -> dict[str, str]:
    return {
        "blender_manifest.toml": _manifest_text(),
        "__init__.py": "# SPDX-License-Identifier: GPL-3.0-or-later\n",
        "bl/__init__.py": "# SPDX-License-Identifier: GPL-3.0-or-later\n",
        "core/__init__.py": "# SPDX-License-Identifier: GPL-3.0-or-later\n",
    }


WHEEL = "suelta-1.0-py3-none-any.whl"


def _zip_bytes(members: Mapping[str, str | bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _with(**changes: object) -> dict[str, object]:
    data = dict(_manifest_data())
    data.update(changes)
    return data


@contextlib.contextmanager
def _zip(members: Mapping[str, str | bytes], name: str | None = None) -> Iterator[Path]:
    name = _zip_name() if name is None else name
    with temp_tree({f"dist/{name}": _zip_bytes(members)}) as tmp:
        yield tmp / "dist" / name


def _inspect(members: Mapping[str, str | bytes], data: Mapping[str, object] | None = None,
             name: str | None = None) -> list[str]:
    with _zip(members, name) as path:
        return build.inspect_zip(path, _manifest_data() if data is None else data)


class InspectZipTest(unittest.TestCase):
    def test_clean_zip_ok(self) -> None:
        """RF-001-26: un zip con el manifiesto y el ``__init__.py`` en la raíz, sin
        ficheros prohibidos y con el nombre ``<id>-<versión>.zip`` pasa."""
        self.assertEqual(_inspect(_good_members()), [])
        self.assertEqual(build.zip_name(_manifest_data()), _zip_name())

    def test_inspect_zip_forbidden_members(self) -> None:
        """RF-001-26: ``AGENTS.md`` y ``CLAUDE.md`` (también anidados),
        ``__pycache__``, ``.pyc``, ``.pyo`` y copias ``.blendN`` hacen fallar la
        inspección, nombrando el miembro."""
        forbidden = (
            "AGENTS.md",
            "CLAUDE.md",
            "bl/ui/AGENTS.md",
            "bl/ui/CLAUDE.md",
            "core/__pycache__/__init__.cpython-313.pyc",
            "core/__pycache__/",
            "core/viejo.pyc",
            "core/viejo.pyo",
            "resources/escena.blend1",
            "resources/escena.blend12",
        )
        for member in forbidden:
            with self.subTest(miembro=member):
                problems = _inspect({**_good_members(), member: "x"})
                self.assertEqual(len(problems), 1, problems)
                self.assertIn(member, problems[0])
        for allowed in ("docs/LEEME.md", "resources/escena.blend", "core/agents.py"):
            with self.subTest(permitido=allowed):
                self.assertEqual(_inspect({**_good_members(), allowed: "x"}), [])

    def test_inspect_zip_unlisted_wheel(self) -> None:
        """RF-001-26: una rueda en ``wheels/`` del zip que no está en la lista del
        manifiesto falla (Blender empaqueta toda la carpeta); listada, pasa; listada y
        ausente del zip, también falla."""
        members = {**_good_members(), f"wheels/{WHEEL}": b"PK"}
        problems = _inspect(members)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn(f"wheels/{WHEEL}", problems[0])
        listed = _with(wheels=[f"./wheels/{WHEEL}"])
        self.assertEqual(_inspect(members, listed), [])
        problems = _inspect(_good_members(), listed)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn(WHEEL, problems[0])

    def test_inspect_zip_required_members_and_name(self) -> None:
        """RF-001-26: faltan el manifiesto o el ``__init__.py`` en la raíz (p. ej. todo
        dentro de una carpeta), el nombre no es ``<id>-<versión>.zip`` o el fichero no
        es un zip: falla."""
        nested = {f"{EXT}/{name}": data for name, data in _good_members().items()}
        problems = _inspect(nested)
        self.assertTrue(any("blender_manifest.toml" in p for p in problems), problems)
        self.assertTrue(any("__init__.py" in p for p in problems), problems)
        problems = _inspect(_good_members(), name="geoblender-9.9.9.zip")
        self.assertEqual(len(problems), 1, problems)
        self.assertIn(_zip_name(), problems[0])
        with temp_tree({f"dist/{_zip_name()}": b"no es un zip"}) as tmp:
            problems = build.inspect_zip(tmp / "dist" / _zip_name(), _manifest_data())
        self.assertEqual(len(problems), 1, problems)


@dataclass
class Call:
    kind: str
    cmd: list[str]
    env: dict[str, str]
    cwd: Path | None
    profile_existed: bool | None
    dist_existed: bool


Result = tuple[int, str, str]


INSTALLED = "GEOBLENDER-SONDA listada=1 importada=1 habilitada=1\n"
REMOVED = "GEOBLENDER-SONDA listada=0 importada=0 habilitada=0\n"
def _module() -> str:
    return f"bl_ext.user_default.{_manifest_data()['id']}"


@dataclass
class FakeRunner:
    """Ejecutor simulado de ``tools/build.py``: anota cada orden; ``extension build``
    escribe en ``<cwd>/dist/<zip_name>`` un zip con ``members``; ``install-file`` crea
    la carpeta de la extensión en el perfil y ``remove`` la borra (si
    ``remove_deletes``); las sesiones de comprobación («sonda») devuelven, por orden,
    las salidas de ``probes``."""

    results: dict[str, Result] = field(default_factory=dict)
    members: Mapping[str, str | bytes] = field(default_factory=lambda: dict(_good_members()))
    zip_name: str = field(default_factory=lambda: _zip_name())
    probes: list[Result] = field(
        default_factory=lambda: [(0, INSTALLED, ""), (0, REMOVED, "")]
    )
    remove_deletes: bool = True
    calls: list[Call] = field(default_factory=list)
    scripts: list[str] = field(default_factory=list)

    def _extension_folder(self, env: Mapping[str, str]) -> Path:
        profile = Path(env["BLENDER_USER_RESOURCES"])
        return profile / "extensions" / "user_default" / str(_manifest_data()["id"])

    @staticmethod
    def kind_of(cmd: Sequence[str]) -> str:
        parts = [str(part) for part in cmd]
        if "extension" in parts:
            return parts[parts.index("extension") + 1]
        if "--python" in parts:
            return "sonda"
        raise AssertionError(f"orden inesperada: {parts}")

    def __call__(
        self,
        cmd: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: Path | None = None,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        kind = self.kind_of(cmd)
        environment = dict(env or {})
        profile = environment.get("BLENDER_USER_RESOURCES")
        base = Path(cwd) if cwd is not None else Path.cwd()
        self.calls.append(
            Call(
                kind,
                [str(part) for part in cmd],
                environment,
                cwd,
                Path(profile).is_dir() if profile else None,
                (base / "dist").is_dir(),
            )
        )
        if kind == "sonda":
            parts = [str(part) for part in cmd]
            script = Path(parts[parts.index("--python") + 1])
            self.scripts.append(script.read_text(encoding="utf-8"))
            code, stdout, stderr = self.probes.pop(0)
            return subprocess.CompletedProcess(list(cmd), code, stdout, stderr)
        code, stdout, stderr = self.results.get(kind, (0, "", ""))
        if kind == "build" and code == 0:
            (base / "dist" / self.zip_name).write_bytes(_zip_bytes(self.members))
        if kind == "install-file" and code == 0:
            folder = self._extension_folder(environment)
            folder.mkdir(parents=True)
            (folder / "__init__.py").write_text("# instalada\n", encoding="utf-8")
        if kind == "remove" and code == 0 and self.remove_deletes:
            shutil.rmtree(self._extension_folder(environment))
        return subprocess.CompletedProcess(list(cmd), code, stdout, stderr)

    def kinds(self) -> list[str]:
        return [call.kind for call in self.calls]

    def call(self, kind: str) -> Call:
        found = [call for call in self.calls if call.kind == kind]
        if len(found) != 1:
            raise AssertionError(f"«{kind}» se ejecutó {len(found)} veces")
        return found[0]


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
def _repo(extra: Mapping[str, str | bytes] | None = None) -> Iterator[Path]:
    """Copia mínima del repositorio: la extensión (con el manifiesto real sin ruedas) y
    un ``tools/wheels.toml`` sin ruedas (no el real: T45)."""
    files: dict[str, str | bytes] = {
        MANIFEST: _manifest_text(),
        f"{EXT}/__init__.py": "# SPDX-License-Identifier: GPL-3.0-or-later\n",
        f"{EXT}/AGENTS.md": "# reglas\n",
        f"{EXT}/CLAUDE.md": "@AGENTS.md\n",
        "tools/wheels.toml": EMPTY_WHEELS_TOML,
    }
    files.update(extra or {})
    with temp_tree(files) as root:
        yield root


def _run(root: Path, *args: str, runner: FakeRunner | None = None,
         locate: object = None) -> Outcome:
    runner = FakeRunner() if runner is None else runner
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = build.main(
            list(args),
            root=root,
            runner=runner,
            locate=locate if locate is not None else (lambda minimum: INSTALL),
        )
    return Outcome(code, out.getvalue(), err.getvalue(), runner)


def _temp_folders() -> set[str]:
    return {
        name for name in os.listdir(tempfile.gettempdir())
        if name.startswith(build.TEMP_PREFIX)
    }


class BuildCommandTest(unittest.TestCase):
    def test_build_commands_and_temp_profile(self) -> None:
        """RF-001-26, RF-001-09: ``extension validate Geoblender`` y después
        ``extension build --source-dir Geoblender --output-dir dist`` desde la raíz, con
        un perfil temporal en ``%TEMP%`` (sin las variables ``BLENDER_USER_*`` que lo
        sustituirían) que se borra al terminar; ``dist/`` existe antes de construir
        (Blender no la crea) y el zip queda en ``dist/<id>-<versión>.zip``."""
        before = _temp_folders()
        with _repo() as root:
            result = _run(root)
            self.assertEqual(result.code, 0, result.text)
            self.assertTrue((root / "dist" / _zip_name()).is_file())
        runner = result.runner
        self.assertEqual(runner.kinds(), ["validate", "build"])
        self.assertEqual(
            runner.call("validate").cmd,
            blender.extension_cmd(INSTALL, "validate", EXT),
        )
        self.assertEqual(
            runner.call("build").cmd,
            blender.extension_cmd(
                INSTALL, "build", "--source-dir", EXT, "--output-dir", "dist"
            ),
        )
        self.assertTrue(runner.call("build").dist_existed)
        profiles = {call.env["BLENDER_USER_RESOURCES"] for call in runner.calls}
        self.assertEqual(len(profiles), 1)
        profile = Path(profiles.pop())
        temp = Path(tempfile.gettempdir()).resolve()
        self.assertTrue(profile.resolve().is_relative_to(temp))
        self.assertTrue(profile.parent.name.startswith(build.TEMP_PREFIX))
        self.assertFalse(profile.parent.exists())
        for call in runner.calls:
            with self.subTest(orden=call.kind):
                self.assertEqual(call.cwd, root)
                self.assertTrue(call.profile_existed)
                for name in blender.OVERRIDING_USER_VARIABLES:
                    self.assertNotIn(name, call.env)
        self.assertEqual(_temp_folders(), before)
        self.assertIn(f"dist/{_zip_name()}", result.out)

    def test_wheels_dir_must_match_manifest(self) -> None:
        """RF-001-26 / LIC-02: una rueda en ``geoblender/wheels/`` que no está en el
        manifiesto (Blender la metería en el zip) para el empaquetado antes de llamar a
        Blender: código 1, sin zip y con el incumplimiento."""
        with _repo({f"{EXT}/wheels/{WHEEL}": b"PK"}) as root:
            result = _run(root)
            self.assertEqual(result.code, 1, result.text)
            self.assertFalse((root / "dist" / _zip_name()).exists())
        self.assertEqual(result.runner.calls, [])
        self.assertIn("[LIC-02]", result.text)
        self.assertIn(WHEEL, result.text)

    def test_manifest_findings_stop_before_blender(self) -> None:
        """RF-001-26: un manifiesto que no cumple MAN-01 o NOM-04 (versión ``0.1``, o
        con BOM) para el empaquetado sin llamar a Blender."""
        text = _manifest_text()
        cases = {
            "versión": text.replace('version = "0.1.0"', 'version = "0.1"').encode(),
            "BOM": b"\xef\xbb\xbf" + text.encode("utf-8"),
        }
        for case, data in cases.items():
            with self.subTest(caso=case), _repo({MANIFEST: data}) as root:
                result = _run(root)
                self.assertEqual(result.code, 1, result.text)
                self.assertEqual(result.runner.calls, [])
                self.assertRegex(result.text, r"\[(MAN-01|NOM-04)\]")
                self.assertFalse((root / "dist").exists())

    def test_validate_failure_builds_nothing(self) -> None:
        """RF-001-26: si ``extension validate`` falla, no se construye ni queda zip (un
        zip anterior con el mismo nombre se borra antes) y se muestra la salida de
        Blender."""
        runner = FakeRunner({"validate": (1, "", 'missing "maintainer"\n')})
        with _repo({f"dist/{_zip_name()}": b"zip anterior"}) as root:
            result = _run(root, runner=runner)
            self.assertEqual(result.code, 1, result.text)
            self.assertFalse((root / "dist" / _zip_name()).exists())
        self.assertEqual(runner.kinds(), ["validate"])
        self.assertIn('missing "maintainer"', result.text)

    def test_build_failure_or_missing_zip(self) -> None:
        """RF-001-26: si ``extension build`` falla, o termina con 0 sin dejar el zip
        esperado, el empaquetado falla."""
        for runner in (
            FakeRunner({"build": (1, "", "FATAL_ERROR: Error creating archive\n")}),
            FakeRunner(zip_name="otro-nombre.zip"),
        ):
            with self.subTest(runner=runner.results or runner.zip_name), _repo() as root:
                result = _run(root, runner=runner)
                self.assertEqual(result.code, 1, result.text)
                self.assertFalse((root / "dist" / _zip_name()).exists())

    def test_bad_zip_is_deleted(self) -> None:
        """RF-001-26: si la inspección encuentra un miembro prohibido, el zip se borra y
        el código es 1, con el miembro nombrado."""
        runner = FakeRunner(members={**_good_members(), "bl/ui/AGENTS.md": "x"})
        with _repo() as root:
            result = _run(root, runner=runner)
            self.assertEqual(result.code, 1, result.text)
            self.assertFalse((root / "dist" / _zip_name()).exists())
        self.assertIn("bl/ui/AGENTS.md", result.text)

    def test_environment_and_usage(self) -> None:
        """RF-001-07: sin Blender, 2 sin ejecutar nada; una opción desconocida, 2;
        ``--ayuda``, 0."""

        def missing(minimum: tuple[int, int, int]) -> BlenderInstall:
            raise EnvironmentProblem("No se encuentra Blender: defina GEOBLENDER_BLENDER")

        with _repo() as root:
            result = _run(root, locate=missing)
            self.assertEqual(result.code, 2, result.text)
            self.assertEqual(result.runner.calls, [])
            self.assertIn("GEOBLENDER_BLENDER", result.err)
            result = _run(root, "--otra")
            self.assertEqual(result.code, 2, result.text)
            self.assertEqual(result.runner.calls, [])
            result = _run(root, "--ayuda")
            self.assertEqual(result.code, 0)
            self.assertIn("tools/build.py", result.out)
            self.assertIn("--probar-instalacion", result.out)
            self.assertEqual(result.runner.calls, [])


class InstallProbeTest(unittest.TestCase):
    def test_probe_sequence_and_commands(self) -> None:
        """RF-001-27: con ``--probar-instalacion``, tras construir: ``install-file -r
        user_default -e <zip>`` en un perfil temporal limpio (distinto del de la
        construcción), una sesión nueva **sin** ``--factory-startup`` que ve la
        extensión habilitada, ``remove user_default.<id>`` y otra sesión nueva que ya
        no la ve; sin carpeta de la extensión en el perfil, código 0 y todo lo temporal
        borrado."""
        before = _temp_folders()
        with _repo() as root:
            result = _run(root, "--probar-instalacion")
            self.assertEqual(result.code, 0, result.text)
            target = root / "dist" / _zip_name()
            self.assertTrue(target.is_file())
        runner = result.runner
        self.assertEqual(
            runner.kinds(), ["validate", "build", "install-file", "sonda", "remove", "sonda"]
        )
        self.assertEqual(
            runner.call("install-file").cmd,
            blender.extension_cmd(
                INSTALL, "install-file", "-r", "user_default", "-e", str(target)
            ),
        )
        self.assertEqual(
            runner.call("remove").cmd,
            blender.extension_cmd(INSTALL, "remove", f"user_default.{_manifest_data()['id']}"),
        )
        probes = [call for call in runner.calls if call.kind == "sonda"]
        for call in probes:
            with self.subTest(sonda=call.cmd):
                script = Path(call.cmd[call.cmd.index("--python") + 1])
                self.assertEqual(call.cmd, blender.profile_cmd(INSTALL, script, _module()))
                self.assertNotIn("--factory-startup", call.cmd)
                self.assertIn("--python-exit-code", call.cmd)
        for script in runner.scripts:
            self.assertIn("preferences.addons", script)
            self.assertIn("GEOBLENDER-SONDA", script)
        profiles = [call.env["BLENDER_USER_RESOURCES"] for call in runner.calls]
        build_profile, probe_profile = profiles[0], profiles[2]
        self.assertEqual(profiles[:2], [build_profile] * 2)
        self.assertEqual(profiles[2:], [probe_profile] * 4)
        self.assertNotEqual(build_profile, probe_profile)
        for call in runner.calls:
            self.assertTrue(call.profile_existed)
            for name in blender.OVERRIDING_USER_VARIABLES:
                self.assertNotIn(name, call.env)
        self.assertFalse(Path(probe_profile).exists())
        self.assertEqual(_temp_folders(), before)
        self.assertIn("instalación", result.out)
        self.assertIn("desinstalación", result.out)

    def test_probe_fails_if_extension_missing(self) -> None:
        """RF-001-27: control positivo: si tras instalar la sesión nueva no ve la
        extensión habilitada (o no informa), la prueba falla con 1 y lo dice; nunca da
        por buena una desinstalación de algo que no se instaló."""
        cases = {
            "no listada": (0, "GEOBLENDER-SONDA listada=0 importada=1 habilitada=0\n", ""),
            "no habilitada": (0, "GEOBLENDER-SONDA listada=1 importada=1 habilitada=0\n", ""),
            "sin informe": (0, "Blender quit\n", ""),
            "excepción": (1, "", "Traceback ...\nRuntimeError: x\n"),
        }
        for case, probe in cases.items():
            runner = FakeRunner(probes=[probe, (0, REMOVED, "")])
            with self.subTest(caso=case), _repo() as root:
                result = _run(root, "--probar-instalacion", runner=runner)
                self.assertEqual(result.code, 1, result.text)
                self.assertNotIn("remove", runner.kinds())
                self.assertIn(_module(), result.text)
                self.assertIn("RESULTADO: NO VERDE", result.text)

    def test_probe_fails_if_trace_left(self) -> None:
        """RF-001-27: si tras desinstalar la extensión sigue en la lista de complementos
        o queda su carpeta en el perfil, la prueba falla con 1 y lo nombra."""
        still = (0, "GEOBLENDER-SONDA listada=1 importada=0 habilitada=0\n", "")
        runner = FakeRunner(probes=[(0, INSTALLED, ""), still])
        with _repo() as root:
            result = _run(root, "--probar-instalacion", runner=runner)
        self.assertEqual(result.code, 1, result.text)
        self.assertIn("lista de complementos", result.text)

        runner = FakeRunner(remove_deletes=False)
        with _repo() as root:
            result = _run(root, "--probar-instalacion", runner=runner)
        self.assertEqual(result.code, 1, result.text)
        self.assertIn(f"extensions/user_default/{_manifest_data()['id']}", result.text)

    def test_install_or_remove_failure(self) -> None:
        """RF-001-27: si ``install-file`` o ``remove`` terminan con un código distinto
        de 0, la prueba falla con 1 y muestra la salida de Blender."""
        for kind in ("install-file", "remove"):
            runner = FakeRunner({kind: (1, "", f"ERROR de {kind}\n")})
            with self.subTest(orden=kind), _repo() as root:
                result = _run(root, "--probar-instalacion", runner=runner)
                self.assertEqual(result.code, 1, result.text)
                self.assertIn(f"ERROR de {kind}", result.text)

    def test_no_probe_without_option_or_zip(self) -> None:
        """RF-001-27: sin la opción no se instala nada; si no hay zip (la validación
        falla), tampoco."""
        with _repo() as root:
            result = _run(root)
        self.assertEqual(result.runner.kinds(), ["validate", "build"])
        runner = FakeRunner({"validate": (1, "", "Error\n")})
        with _repo() as root:
            result = _run(root, "--probar-instalacion", runner=runner)
        self.assertEqual(result.code, 1)
        self.assertEqual(runner.kinds(), ["validate"])


if __name__ == "__main__":
    unittest.main()

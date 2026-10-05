# SPDX-License-Identifier: GPL-3.0-or-later
"""Empaquetado de la extensión (plan 001 §5.4.13; RF-001-02, RF-001-26, RF-001-27).

Se ejecuta con el Python de Blender, desde la raíz del repositorio::

    & "C:\\Program Files\\Blender Foundation\\Blender 5.2\\5.2\\python\\bin\\python.exe" tools/build.py [--probar-instalacion]

1. Localiza Blender (``GEOBLENDER_BLENDER`` o la ruta por defecto, con la versión mínima
   del manifiesto) y comprueba el manifiesto (MAN-01, NOM-04) y las ruedas (LIC-01,
   LIC-02): ``geoblender/wheels/`` tiene que coincidir con la lista del manifiesto,
   porque Blender mete en el zip todo lo que hay en esa carpeta (plan 001 §2.1, 2).
2. ``blender --factory-startup --command extension validate Geoblender``; si falla,
   sale con 1 sin generar el zip.
3. ``extension build --source-dir Geoblender --output-dir dist``.
4. Inspecciona ``dist/<id>-<versión>.zip``: no puede tener ``AGENTS.md`` ni
   ``CLAUDE.md`` (en ningún nivel), ``__pycache__``, ``.pyc``, ``.pyo``, copias
   ``.blendN`` ni ruedas que no estén en la lista del manifiesto; tiene que tener
   ``blender_manifest.toml`` y ``__init__.py`` en la raíz y las ruedas listadas. Si algo
   falla, borra el zip y sale con 1.
5. Con ``--probar-instalacion``, en otro perfil temporal y limpio:
   ``extension install-file -r user_default -e <zip>`` (instala y habilita); una sesión
   nueva **sin** ``--factory-startup`` (que oculta la extensión instalada, plan 001
   §2.1, 13) tiene que ver ``bl_ext.user_default.<id>`` en la lista de complementos,
   importable y habilitada (control positivo: si no, la prueba falla);
   ``extension remove user_default.<id>``; otra sesión nueva no puede verla, y no puede
   quedar ``<perfil>/extensions/user_default/<id>``. Las sesiones ejecutan un guion que
   se escribe en la carpeta temporal (``PROBE_SCRIPT``): ``tools/`` no importa módulos
   de Blender.

Un zip anterior con el mismo nombre se borra antes de validar: en ``dist/`` solo queda
el de una ejecución correcta. Blender se lanza con perfiles temporales en ``%TEMP%``
(``BLENDER_USER_RESOURCES``), que se borran al terminar; nunca con el del usuario.

Códigos de salida: 0 correcto; 1 manifiesto o ruedas con incumplimientos, validación,
construcción o inspección fallidas (sin zip) o prueba de instalación fallida (el zip
queda); 2 entorno (Blender ausente o anterior al mínimo) u opción no válida.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # sin __pycache__ en Z: (plan 001 §5.3)

import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import stat  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import tomllib  # noqa: E402
import zipfile  # noqa: E402
from collections.abc import Callable, Collection, Mapping, Sequence  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

from gbtools import blender, layout, manifest, wheels  # noqa: E402
from gbtools.blender import BlenderInstall, EnvironmentProblem  # noqa: E402
from gbtools.findings import format_findings  # noqa: E402
from gbtools.repo import repo_root  # noqa: E402

EXTENSION_FOLDER = layout.EXTENSION_DIR
DIST_FOLDER = "dist"
TEMP_PREFIX = "geoblender-build-"
PROFILE_FOLDER = "perfil"
PROBE_PROFILE_FOLDER = "perfil-instalacion"
COMMAND_TIMEOUT_S = 600.0
OPTION_PROBE = "--probar-instalacion"
INSTALL_REPO = "user_default"  # repositorio de extensiones de usuario de Blender
PROBE_SCRIPT_NAME = "sonda_instalacion.py"
PROBE_MARKER = "GEOBLENDER-SONDA"

# Guion de las sesiones de comprobación: se escribe en la carpeta temporal y se ejecuta
# dentro de Blender (profile_cmd, con el módulo tras «--»). Solo informa del estado;
# quien decide es probe_install.
PROBE_SCRIPT = f'''# SPDX-License-Identifier: GPL-3.0-or-later
"""Sonda de tools/build.py: estado de una extensión en este perfil de Blender."""
import sys

sys.dont_write_bytecode = True

import importlib

import bpy

module = sys.argv[sys.argv.index("--") + 1]
listed = module in bpy.context.preferences.addons
try:
    loaded = importlib.import_module(module)
except Exception:
    loaded = None
enabled = bool(getattr(loaded, "__addon_enabled__", False))
print(
    f"{PROBE_MARKER} listada={{int(listed)}} importada={{int(loaded is not None)}} "
    f"habilitada={{int(enabled)}}",
    flush=True,
)
'''
_PROBE_LINE = re.compile(
    rf"^{PROBE_MARKER} listada=([01]) importada=([01]) habilitada=([01])\s*$", re.MULTILINE
)

AGENT_FILES: frozenset[str] = frozenset({"AGENTS.md", "CLAUDE.md"})
BYTECODE_SUFFIXES: tuple[str, ...] = (".pyc", ".pyo")
REQUIRED_MEMBERS: tuple[str, ...] = ("blender_manifest.toml", "__init__.py")
WHEELS_PREFIX = "wheels/"
_BLEND_BACKUP = re.compile(r"\.blend\d+$")

STATUS_OK = "correcto"
STATUS_FAIL = "fallo"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2

USAGE = """Uso (con el Python de Blender, desde la raíz del repositorio):
  & "<Blender>\\5.2\\python\\bin\\python.exe" tools/build.py [--probar-instalacion]

  --probar-instalacion  instala el zip en un perfil temporal limpio, comprueba que se
                        habilita, lo desinstala y comprueba que no queda rastro
  --ayuda, -h           muestra esta ayuda

Deja el zip en dist/<id>-<versión>.zip. Blender: GEOBLENDER_BLENDER o la ruta por
defecto. Códigos: 0 correcto, 1 fallo, 2 entorno u opción no válida."""


class UsageError(Exception):
    """Opciones no válidas: el mensaje dice cuál."""


@dataclass(frozen=True)
class Options:
    probe: bool = False
    show_help: bool = False


@dataclass(frozen=True)
class AddonState:
    """Lo que ve una sesión nueva de Blender de una extensión instalada."""

    listed: bool  # está en la lista de complementos (preferences.addons)
    imported: bool  # su módulo se importa
    enabled: bool  # está habilitada (__addon_enabled__)


@dataclass
class ProbeReport:
    """Resultado de la prueba de instalación (paso 5)."""

    installed: AddonState | None = None  # sesión tras instalar
    removed: AddonState | None = None  # sesión tras desinstalar
    folder_left: bool = False  # queda <perfil>/extensions/user_default/<id>
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def parse_args(args: Sequence[str]) -> Options:
    """Lee las opciones; lanza :class:`UsageError` si alguna no existe."""
    probe = False
    show_help = False
    for arg in args:
        if arg in ("--ayuda", "-h", "--help"):
            show_help = True
        elif arg == OPTION_PROBE:
            probe = True
        else:
            raise UsageError(f"opción desconocida «{arg}»")
    return Options(probe=probe, show_help=show_help)


def zip_name(manifest_data: Mapping[str, Any]) -> str:
    """Nombre del zip que genera ``extension build``: ``<id>-<versión>.zip``."""
    return f"{manifest_data['id']}-{manifest_data['version']}.zip"


def member_problem(name: str, listed_wheels: Collection[str]) -> str | None:
    """Motivo por el que ``name`` (miembro del zip, con «/») no puede estar en él, o
    ``None``. ``listed_wheels`` son las entradas ``./wheels/<fichero>`` del manifiesto."""
    parts = name.split("/")
    leaf = parts[-1] or (parts[-2] if len(parts) > 1 else "")
    if "__pycache__" in parts:
        return f"«{name}»: caché de Python (__pycache__), no se empaqueta"
    if leaf in AGENT_FILES:
        return f"«{name}»: los ficheros de agentes (AGENTS.md, CLAUDE.md) no se empaquetan"
    if leaf.lower().endswith(BYTECODE_SUFFIXES):
        return f"«{name}»: bytecode de Python, no se empaqueta"
    if _BLEND_BACKUP.search(leaf.lower()):
        return f"«{name}»: copia de seguridad de Blender, no se empaqueta"
    if name.startswith(WHEELS_PREFIX) and not name.endswith("/"):
        if f"./{name}" not in listed_wheels:
            return (
                f"«{name}»: rueda que no está en la lista «wheels» del manifiesto "
                f"(Blender empaqueta toda la carpeta): bórrela o "
                f"{wheels.FETCH_HINT}"
            )
    return None


def inspect_zip(path: Path, manifest_data: Mapping[str, Any]) -> list[str]:
    """Problemas del zip ``path`` (en español; lista vacía si está bien)."""
    path = Path(path)
    problems: list[str] = []
    expected = zip_name(manifest_data)
    if path.name != expected:
        problems.append(
            f"el zip se llama «{path.name}» y debe llamarse «{expected}» "
            "(<id>-<versión>.zip del manifiesto)"
        )
    try:
        with zipfile.ZipFile(path) as archive:
            names = [name.replace("\\", "/") for name in archive.namelist()]
    except (zipfile.BadZipFile, OSError) as exc:
        problems.append(f"«{path.name}» no es un zip válido: {exc}")
        return problems
    listed = set(manifest.wheel_files(manifest_data))
    for name in names:
        problem = member_problem(name, listed)
        if problem is not None:
            problems.append(problem)
    present = set(names)
    for required in REQUIRED_MEMBERS:
        if required not in present:
            problems.append(f"falta «{required}» en la raíz del zip")
    for entry in sorted(listed):
        if entry.removeprefix("./") not in present:
            problems.append(f"falta en el zip la rueda listada en el manifiesto «{entry}»")
    return problems


def _clear_readonly(
    function: Callable[..., object], path: str, _error: BaseException
) -> None:
    """Para ``shutil.rmtree``: quita el atributo de solo lectura y reintenta."""
    os.chmod(path, stat.S_IWRITE)
    function(path)


def _remove(path: Path, attempts: int = 5) -> None:
    """Borra un fichero o una carpeta entera, con reintentos (Windows puede retener un
    fichero un momento)."""
    for attempt in range(attempts):
        try:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path, onexc=_clear_readonly)
            elif path.exists() or path.is_symlink():
                path.unlink()
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.2 * (attempt + 1))


def _seconds(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def _line(status: str, name: str, seconds: float | None = None, detail: str = "") -> str:
    """Línea del resumen: ``  correcto  validación    0,5 s  (detalle)``."""
    line = f"  {status:<8}  {name:<12}"
    if seconds is not None:
        line += f" {_seconds(seconds):>5} s"
    if detail:
        line += f"  ({detail})"
    return line


def _show(title: str, text: str) -> None:
    if text.strip():
        print(f"--- {title} ---")
        print(text.rstrip())
        print(f"--- Fin: {title} ---")


def run_command(
    runner: blender.Runner, cmd: Sequence[str], env: Mapping[str, str], cwd: Path
) -> tuple[int | None, str]:
    """Ejecuta ``cmd``; devuelve su código (``None`` si no se pudo lanzar o no terminó
    a tiempo) y su salida."""
    try:
        result = runner(list(cmd), env=dict(env), cwd=cwd, timeout=COMMAND_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return None, f"no terminó en {COMMAND_TIMEOUT_S:.0f} s: {' '.join(map(str, cmd))}"
    except OSError as exc:
        return None, f"no se pudo ejecutar «{' '.join(map(str, cmd))}»: {exc}"
    parts = [part.rstrip() for part in (result.stdout or "", result.stderr or "")]
    return result.returncode, "\n".join(part for part in parts if part)


def package(
    root: Path,
    install: BlenderInstall,
    profile: Path,
    runner: blender.Runner,
    manifest_data: Mapping[str, Any],
) -> Path | None:
    """Pasos 2 a 4: valida, construye e inspecciona; devuelve el zip o ``None`` (sin
    zip) si algo falla."""
    env = blender.isolated_env(profile)
    target = root / DIST_FOLDER / zip_name(manifest_data)

    started = time.perf_counter()
    code, output = run_command(
        runner, blender.extension_cmd(install, "validate", EXTENSION_FOLDER), env, root
    )
    if code != 0:
        seconds = time.perf_counter() - started
        print(_line(STATUS_FAIL, "validación", seconds, f"código {code}"))
        _show("salida de «extension validate»", output)
        return None
    print(_line(STATUS_OK, "validación", time.perf_counter() - started))

    started = time.perf_counter()
    (root / DIST_FOLDER).mkdir(exist_ok=True)  # extension build no la crea
    code, output = run_command(
        runner,
        blender.extension_cmd(
            install, "build", "--source-dir", EXTENSION_FOLDER, "--output-dir", DIST_FOLDER
        ),
        env,
        root,
    )
    seconds = time.perf_counter() - started
    if code != 0 or not target.is_file():
        missing = f"no dejó «{DIST_FOLDER}/{target.name}»"
        detail = f"código {code}" if code != 0 else missing
        print(_line(STATUS_FAIL, "construcción", seconds, detail))
        _show("salida de «extension build»", output)
        _remove(target)
        return None
    print(_line(STATUS_OK, "construcción", seconds))

    problems = inspect_zip(target, manifest_data)
    if problems:
        print(_line(STATUS_FAIL, "inspección", detail=f"{len(problems)} problemas"))
        for problem in problems:
            print(f"    {problem}")
        _remove(target)
        return None
    with zipfile.ZipFile(target) as archive:
        count = len([name for name in archive.namelist() if not name.endswith("/")])
    size = _seconds(target.stat().st_size / 1024)
    print(_line(STATUS_OK, "inspección", detail=f"{count} ficheros, {size} KiB"))
    return target


def installed_module(manifest_data: Mapping[str, Any]) -> str:
    """Módulo de la extensión instalada en el repositorio de usuario:
    ``bl_ext.user_default.<id>``."""
    return f"bl_ext.{INSTALL_REPO}.{manifest_data['id']}"


def write_probe_script(folder: Path) -> Path:
    """Escribe :data:`PROBE_SCRIPT` en ``folder`` (UTF-8, LF) y devuelve su ruta."""
    path = Path(folder) / PROBE_SCRIPT_NAME
    path.write_bytes(PROBE_SCRIPT.encode("utf-8"))
    return path


def probe_session(
    install: BlenderInstall,
    profile: Path,
    script: Path,
    module: str,
    runner: blender.Runner,
) -> tuple[AddonState | None, str]:
    """Sesión nueva de Blender con el perfil ``profile``, **sin** configuración de
    fábrica (``profile_cmd``), que informa del estado de ``module``. Devuelve el estado
    (``None`` si la sesión falló o no informó) y su salida."""
    code, output = run_command(
        runner,
        blender.profile_cmd(install, script, module),
        blender.isolated_env(profile),
        Path(profile),
    )
    match = _PROBE_LINE.search(output)
    if code != 0 or match is None:
        return None, output
    listed, imported, enabled = (group == "1" for group in match.groups())
    return AddonState(listed, imported, enabled), output


def _describe(state: AddonState) -> str:
    return (
        f"listada={int(state.listed)}, importada={int(state.imported)}, "
        f"habilitada={int(state.enabled)}"
    )


def probe_install(
    install: BlenderInstall,
    zip_path: Path,
    manifest_data: Mapping[str, Any],
    work: Path,
    runner: blender.Runner,
) -> ProbeReport:
    """Paso 5: instala ``zip_path`` en un perfil limpio dentro de ``work``, comprueba
    que una sesión nueva lo ve habilitado, lo desinstala y comprueba que no queda ni su
    entrada en la lista de complementos ni su carpeta."""
    report = ProbeReport()
    profile = Path(work) / PROBE_PROFILE_FOLDER
    profile.mkdir()
    script = write_probe_script(Path(work))
    env = blender.isolated_env(profile)
    module = installed_module(manifest_data)
    extension_id = str(manifest_data["id"])
    folder_rel = f"extensions/{INSTALL_REPO}/{extension_id}"

    code, output = run_command(
        runner,
        blender.extension_cmd(
            install, "install-file", "-r", INSTALL_REPO, "-e", str(zip_path)
        ),
        env,
        Path(work),
    )
    if code != 0:
        report.problems.append(
            f"«extension install-file» terminó con código {code}:\n{output}"
        )
        return report
    state, output = probe_session(install, profile, script, module, runner)
    report.installed = state
    if state is None:
        report.problems.append(
            f"la sesión que comprueba «{module}» tras instalar no terminó bien o no "
            f"informó:\n{output}"
        )
        return report
    if not (state.listed and state.imported and state.enabled):
        report.problems.append(
            f"tras instalar, una sesión nueva no ve «{module}» habilitada "
            f"({_describe(state)}): sin eso, comprobar la desinstalación no demostraría "
            "nada"
        )
        return report

    code, output = run_command(
        runner,
        blender.extension_cmd(install, "remove", f"{INSTALL_REPO}.{extension_id}"),
        env,
        Path(work),
    )
    if code != 0:
        report.problems.append(f"«extension remove» terminó con código {code}:\n{output}")
        return report
    state, output = probe_session(install, profile, script, module, runner)
    report.removed = state
    if state is None:
        report.problems.append(
            f"la sesión que comprueba «{module}» tras desinstalar no terminó bien o no "
            f"informó:\n{output}"
        )
    elif state.listed or state.imported or state.enabled:
        report.problems.append(
            f"tras desinstalar, «{module}» sigue en la lista de complementos o se "
            f"importa ({_describe(state)})"
        )
    report.folder_left = (profile / folder_rel).exists()
    if report.folder_left:
        report.problems.append(f"tras desinstalar queda «{folder_rel}» en el perfil")
    return report


def main(
    argv: Sequence[str] | None = None,
    *,
    root: Path | None = None,
    runner: blender.Runner = blender.run,
    locate: Callable[[tuple[int, int, int]], BlenderInstall] = blender.locate_blender,
) -> int:
    """Empaqueta la extensión y devuelve el código de salida.

    Los parámetros con nombre solo los cambian las pruebas: raíz del repositorio,
    ejecutor de órdenes y localizador de Blender.
    """
    started = time.perf_counter()
    try:
        options = parse_args(list(sys.argv[1:] if argv is None else argv))
    except UsageError as exc:
        print(f"Error: {exc}\n\n{USAGE}", file=sys.stderr)
        return EXIT_USAGE
    if options.show_help:
        print(__doc__)
        print(USAGE)
        return EXIT_OK
    if root is None:
        try:
            root = repo_root(Path(__file__))
        except FileNotFoundError as exc:
            print(f"ERROR DE ENTORNO: {exc}", file=sys.stderr)
            return EXIT_USAGE
    root = Path(root)

    def verdict(target: Path | None) -> str:
        total = f"({_seconds(time.perf_counter() - started)} s)"
        if target is None:
            return f"RESULTADO: NO VERDE {total}: no se ha generado el zip"
        return f"RESULTADO: correcto {total}: {target.relative_to(root).as_posix()}"

    rel = manifest.MANIFEST_RELPATH
    try:
        data = manifest.load(root / rel)
        minimum = manifest.blender_min(data)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, ValueError) as exc:
        findings = manifest.check(root)
        if findings:
            print(format_findings(findings))
        print(f"ERROR: no se puede leer el manifiesto «{rel}»: {exc}", file=sys.stderr)
        print(verdict(None))
        return EXIT_FAILED
    try:
        install = locate(minimum)
    except EnvironmentProblem as exc:
        print(f"ERROR DE ENTORNO: {exc}", file=sys.stderr)
        return EXIT_USAGE

    version = ".".join(str(part) for part in install.version)
    print(f"Geoblender · empaquetado · Blender {version} ({install.exe})")
    findings = sorted([*manifest.check(root), *wheels.check(root)])
    if findings:
        print(_line(STATUS_FAIL, "comprobación", detail=f"{len(findings)} incumplimientos"))
        print(format_findings(findings))
        print(verdict(None))
        return EXIT_FAILED
    print(_line(STATUS_OK, "comprobación", detail="MAN-01, NOM-04, LIC-01, LIC-02"))

    _remove(root / DIST_FOLDER / zip_name(data))  # nunca queda un zip anterior
    work = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
    report: ProbeReport | None = None
    try:
        profile = work / PROFILE_FOLDER
        profile.mkdir()
        target = package(root, install, profile, runner, data)
        if target is not None and options.probe:
            report = _probe(install, target, data, work, runner)
    finally:
        try:
            _remove(work)
        except OSError as exc:
            print(f"AVISO: no se pudo borrar la carpeta temporal «{work}»: {exc}")
    if target is not None and report is not None and not report.ok:
        total = _seconds(time.perf_counter() - started)
        print(
            f"RESULTADO: NO VERDE ({total} s): falla la prueba de instalación (el zip "
            f"queda en {target.relative_to(root).as_posix()})"
        )
        return EXIT_FAILED
    print(verdict(target))
    return EXIT_OK if target is not None else EXIT_FAILED


def _probe(
    install: BlenderInstall,
    target: Path,
    data: Mapping[str, Any],
    work: Path,
    runner: blender.Runner,
) -> ProbeReport:
    """Paso 5 con sus líneas del resumen."""
    started = time.perf_counter()
    report = probe_install(install, target, data, work, runner)
    seconds = time.perf_counter() - started
    module = installed_module(data)
    if report.ok:
        enabled = f"{module} habilitada en una sesión nueva"
        print(_line(STATUS_OK, "instalación", seconds, enabled))
        print(
            _line(
                STATUS_OK,
                "desinstalación",
                detail="sin su carpeta ni su entrada en la lista de complementos",
            )
        )
        return report
    print(_line(STATUS_FAIL, "prueba de instalación", seconds, module))
    for problem in report.problems:
        print("    " + problem.replace("\n", "\n    "))
    return report


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(_stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")
    sys.exit(main())

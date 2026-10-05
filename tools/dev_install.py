# SPDX-License-Identifier: GPL-3.0-or-later
"""Instalación de desarrollo en un perfil de Blender aislado (plan 001 §5.4.14;
RF-001-28).

Se ejecuta con el Python de Blender, desde la raíz del repositorio::

    & "C:\\Program Files\\Blender Foundation\\Blender 5.2\\5.2\\python\\bin\\python.exe" tools/dev_install.py [--perfil CARPETA] [--abrir | --desinstalar]

1. Perfil: ``--perfil``, o ``GEOBLENDER_DEV_PROFILE``, o
   ``%LOCALAPPDATA%\\Geoblender\\dev\\blender-5.2``.
2. Se rechaza, con 2 y sin copiar nada, un perfil con ruta UNC, en una unidad de red
   (``GetDriveTypeW`` = ``DRIVE_REMOTE``, o una unidad asignada que se resuelve a una
   ruta UNC), dentro del repositorio o dentro de la configuración normal de Blender
   (``%APPDATA%\\Blender Foundation``).
3. Copia espejo (``gbtools.sync``) de ``geoblender/`` a
   ``<perfil>/extensions/user_default/geoblender`` con las exclusiones del manifiesto:
   copia solo lo que ha cambiado y borra lo que sobra (también los ``__pycache__`` que
   Blender escribe en la copia al cargarla, y que regenera), e informa de ello.
4. Con ``BLENDER_USER_RESOURCES`` = perfil y Blender en segundo plano **sin**
   configuración de fábrica (que ocultaría la extensión instalada, plan 001 §2.1, 13),
   un guion habilita ``bl_ext.user_default.geoblender`` con ``default_set=True`` y
   guarda las preferencias del perfil: queda habilitada en las sesiones siguientes.
5. ``--abrir``: abre Blender con interfaz y ese perfil, sin esperar; si no, imprime la
   orden de PowerShell que lo abre.
6. ``--desinstalar``: deshabilita la extensión, guarda las preferencias del perfil y
   borra su carpeta.

Nunca toca la configuración normal de Blender del usuario (todo va por
``BLENDER_USER_RESOURCES``), no crea enlaces simbólicos y no escribe en una unidad de
red. El guion que se ejecuta dentro de Blender se escribe en una carpeta temporal
(``DEV_SCRIPT``): ``tools/`` no importa módulos de Blender.

Códigos de salida: 0 correcto; 1 la copia, la habilitación o la deshabilitación
fallaron; 2 perfil rechazado, entorno (Blender ausente o anterior al mínimo) u opción no
válida.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # sin __pycache__ en Z: (plan 001 §5.3)

import ctypes  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import stat  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import tomllib  # noqa: E402
from collections.abc import Callable, Mapping, Sequence  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402

from build import INSTALL_REPO, installed_module, run_command  # noqa: E402
from gbtools import blender, layout, manifest, sync  # noqa: E402
from gbtools.blender import BlenderInstall, EnvironmentProblem  # noqa: E402
from gbtools.ignore import UnsupportedPattern  # noqa: E402
from gbtools.repo import repo_root  # noqa: E402

ENV_DEV_PROFILE = "GEOBLENDER_DEV_PROFILE"
DEFAULT_PROFILE_PARTS: tuple[str, ...] = ("Geoblender", "dev", "blender-5.2")
DEFAULT_PROFILE_HINT = "%LOCALAPPDATA%\\" + "\\".join(DEFAULT_PROFILE_PARTS)
EXTENSION_FOLDER = layout.EXTENSION_DIR
BLENDER_CONFIG_FOLDER = "Blender Foundation"  # bajo %APPDATA%: la configuración normal
PREFS_RELPATH = Path("config") / "userpref.blend"
TEMP_PREFIX = "geoblender-dev-"
DEV_SCRIPT_NAME = "dev_install_blender.py"
DEV_MARKER = "GEOBLENDER-DEV"
ACTION_ENABLE = "habilitar"
ACTION_DISABLE = "deshabilitar"
DRIVE_REMOTE = 4  # GetDriveTypeW: unidad de red

OPTION_PROFILE = "--perfil"
OPTION_OPEN = "--abrir"
OPTION_UNINSTALL = "--desinstalar"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2

USAGE = f"""Uso (con el Python de Blender, desde la raíz del repositorio):
  & "<Blender>\\5.2\\python\\bin\\python.exe" tools/dev_install.py [--perfil CARPETA] [--abrir | --desinstalar]

  --perfil CARPETA  perfil aislado de Blender (por defecto, GEOBLENDER_DEV_PROFILE o
                    {DEFAULT_PROFILE_HINT}); nunca en red ni en el
                    repositorio
  --abrir           después de instalar, abre Blender con interfaz y ese perfil
  --desinstalar     deshabilita la extensión en el perfil y borra su carpeta
  --ayuda, -h       muestra esta ayuda

Códigos: 0 correcto, 1 fallo, 2 perfil rechazado, entorno u opción no válida."""

# Guion que se ejecuta dentro de Blender (profile_cmd, con la acción y el módulo tras
# «--»): habilita o deshabilita la extensión, guarda las preferencias del perfil e
# informa del estado; quien decide es run_in_blender.
DEV_SCRIPT = f'''# SPDX-License-Identifier: GPL-3.0-or-later
"""Guion de tools/dev_install.py: habilita o deshabilita la extensión en este perfil."""
import sys

sys.dont_write_bytecode = True

import addon_utils
import bpy

action, module = sys.argv[sys.argv.index("--") + 1 :][:2]
errors = []


def enabled():
    return bool(getattr(sys.modules.get(module), "__addon_enabled__", False))


def listed():
    return module in bpy.context.preferences.addons


if action == "{ACTION_ENABLE}":
    if not (enabled() and listed()):
        addon_utils.enable(module, default_set=True, handle_error=errors.append)
elif listed() or enabled():
    addon_utils.disable(module, default_set=True, handle_error=errors.append)
bpy.ops.wm.save_userpref()
print(
    f"{DEV_MARKER} listada={{int(listed())}} habilitada={{int(enabled())}} "
    f"errores={{len(errors)}}",
    flush=True,
)
for error in errors:
    print(f"{DEV_MARKER}-ERROR {{error!r}}", flush=True)
'''
_DEV_LINE = re.compile(
    rf"^{DEV_MARKER} listada=([01]) habilitada=([01]) errores=(\d+)\s*$", re.MULTILINE
)

Launcher = Callable[..., object]


class UsageError(Exception):
    """Opciones o perfil no válidos: el mensaje dice cuál y cómo corregirlo."""


@dataclass(frozen=True)
class Options:
    profile: str | None = None
    open: bool = False
    uninstall: bool = False
    show_help: bool = False


def parse_args(args: Sequence[str]) -> Options:
    """Lee las opciones; lanza :class:`UsageError` si algo sobra, falta o choca."""
    profile: str | None = None
    flags: set[str] = set()
    show_help = False
    pending = list(args)
    while pending:
        arg = pending.pop(0)
        if arg in ("--ayuda", "-h", "--help"):
            show_help = True
            continue
        if arg in (OPTION_OPEN, OPTION_UNINSTALL):
            flags.add(arg)
            continue
        name, equals, value = arg.partition("=")
        if name != OPTION_PROFILE:
            raise UsageError(f"opción desconocida «{arg}»")
        if not equals:
            if not pending or pending[0].startswith("--"):
                raise UsageError(f"falta la carpeta de «{OPTION_PROFILE}»")
            value = pending.pop(0)
        if not value.strip():
            raise UsageError(f"«{OPTION_PROFILE}» no puede estar vacío")
        profile = value.strip()
    if {OPTION_OPEN, OPTION_UNINSTALL} <= flags:
        raise UsageError(f"«{OPTION_OPEN}» y «{OPTION_UNINSTALL}» no van juntas")
    return Options(
        profile=profile,
        open=OPTION_OPEN in flags,
        uninstall=OPTION_UNINSTALL in flags,
        show_help=show_help,
    )


def _clean(value: str) -> str:
    """Quita espacios y comillas que envuelven un valor."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value


def _is_unc(text: str) -> bool:
    return text.startswith(("\\\\", "//"))


def resolve_profile(option: str | None, environ: Mapping[str, str]) -> Path:
    """El perfil: ``option`` (``--perfil``), o ``GEOBLENDER_DEV_PROFILE``, o
    ``%LOCALAPPDATA%\\Geoblender\\dev\\blender-5.2``; :class:`UsageError` si no se
    puede saber."""
    if option is not None and _clean(option):
        raw = _clean(option)
    elif _clean(environ.get(ENV_DEV_PROFILE, "")):
        raw = _clean(environ[ENV_DEV_PROFILE])
    else:
        local = _clean(environ.get("LOCALAPPDATA", ""))
        if not local:
            raise UsageError(
                "no se puede saber el perfil por defecto porque LOCALAPPDATA no está "
                f"definida: indíquelo con {OPTION_PROFILE} o con {ENV_DEV_PROFILE}"
            )
        return Path(local).joinpath(*DEFAULT_PROFILE_PARTS)
    path = Path(raw)
    return path if path.is_absolute() or _is_unc(raw) else Path.cwd() / path


def drive_type(root: str) -> int:
    """``GetDriveTypeW`` de Windows para la raíz ``X:\\`` (0 si no se puede saber)."""
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    except AttributeError:
        return 0
    return int(kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)))


def _inside(child: Path | str, parent: Path | str) -> bool:
    """Verdadero si ``child`` es ``parent`` o está dentro (sin distinguir mayúsculas)."""
    child_text = os.path.normcase(os.path.normpath(str(child)))
    parent_text = os.path.normcase(os.path.normpath(str(parent))).rstrip("\\/")
    return child_text == parent_text or child_text.startswith(parent_text + os.sep)


def profile_problem(
    profile: Path,
    root: Path,
    environ: Mapping[str, str],
    drive_type: Callable[[str], int] = drive_type,
) -> str | None:
    """Motivo para rechazar el perfil (en español), o ``None`` si vale.

    Una ruta UNC se rechaza antes de tocar el sistema de ficheros (no se accede a la
    red para comprobarla).
    """
    local = (
        "elija un perfil en un disco local (p. ej. el de por defecto, "
        f"{DEFAULT_PROFILE_HINT})"
    )
    if _is_unc(str(profile)):
        return f"el perfil «{profile}» es una ruta UNC (de red): {local}"
    drive = profile.drive
    if drive and drive_type(drive + "\\") == DRIVE_REMOTE:
        return f"el perfil «{profile}» está en una unidad de red ({drive}): {local}"
    resolved = profile.resolve()
    if _is_unc(str(resolved)):
        return f"el perfil «{profile}» está en una unidad de red («{resolved}»): {local}"
    if _inside(resolved, Path(root).resolve()):
        return (
            f"el perfil «{profile}» está dentro del repositorio: Blender escribiría en él "
            f"(cachés, preferencias); {local}"
        )
    appdata = _clean(environ.get("APPDATA", ""))
    if appdata and _inside(resolved, Path(appdata).resolve() / BLENDER_CONFIG_FOLDER):
        return (
            f"el perfil «{profile}» está dentro de la configuración normal de Blender "
            f"(«{Path(appdata) / BLENDER_CONFIG_FOLDER}»), que la instalación de "
            f"desarrollo nunca toca: {local}"
        )
    return None


def run_in_blender(
    install: BlenderInstall,
    profile: Path,
    action: str,
    module: str,
    runner: blender.Runner,
    environ: Mapping[str, str],
) -> tuple[bool, str]:
    """Ejecuta :data:`DEV_SCRIPT` con ``action`` en Blender, en segundo plano, con el
    perfil ``profile`` y sin configuración de fábrica. Devuelve si quedó como se pedía
    (habilitada y listada, o ni una cosa ni otra, sin errores) y la salida."""
    work = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
    try:
        script = work / DEV_SCRIPT_NAME
        script.write_bytes(DEV_SCRIPT.encode("utf-8"))
        code, output = run_command(
            runner,
            blender.profile_cmd(install, script, action, module),
            blender.isolated_env(profile, base=environ),
            profile,
        )
    finally:
        _remove_tree(work)
    match = _DEV_LINE.search(output)
    if code != 0 or match is None:
        return False, output
    listed, enabled, errors = match.group(1) == "1", match.group(2) == "1", int(match.group(3))
    if action == ACTION_ENABLE:
        return errors == 0 and listed and enabled, output
    return errors == 0 and not listed and not enabled, output


def _clear_readonly(
    function: Callable[..., object], path: str, _error: BaseException
) -> None:
    """Para ``shutil.rmtree``: quita el atributo de solo lectura y reintenta."""
    os.chmod(path, stat.S_IWRITE)
    function(path)


def _remove_tree(folder: Path) -> None:
    if folder.exists():
        shutil.rmtree(folder, onexc=_clear_readonly)


def open_command(install: BlenderInstall, profile: Path) -> str:
    """Orden de PowerShell que abre Blender con interfaz y el perfil ``profile``."""
    return (
        f'$env:BLENDER_USER_RESOURCES = "{profile}"; & "{install.exe}"; '
        "Remove-Item Env:BLENDER_USER_RESOURCES"
    )


def _launch(cmd: Sequence[str], *, env: Mapping[str, str], cwd: str) -> object:
    """Abre Blender con interfaz en su propia consola, sin esperar a que se cierre."""
    return subprocess.Popen(
        list(cmd),
        env=dict(env),
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
    )


def _copy_summary(report: sync.SyncReport) -> list[str]:
    caches = [rel for rel in report.deleted if "__pycache__" in rel.split("/")]
    line = (
        f"  copia: {len(report.copied)} copiados, {len(report.deleted)} borrados, "
        f"{report.unchanged} sin cambios"
    )
    if caches:
        line += f" (de los borrados, {len(caches)} __pycache__ que Blender regenera)"
    lines = [line]
    shown = [f"    + {rel}" for rel in report.copied]
    shown += [f"    - {rel}" for rel in report.deleted if rel not in caches]
    lines.extend(shown[:20])
    if len(shown) > 20:
        lines.append(f"    … y {len(shown) - 20} más")
    return lines


def _locate(
    locate: Callable[[tuple[int, int, int]], BlenderInstall], minimum: tuple[int, int, int]
) -> BlenderInstall | None:
    try:
        return locate(minimum)
    except EnvironmentProblem as exc:
        print(f"ERROR DE ENTORNO: {exc}", file=sys.stderr)
        return None


def _header(install: BlenderInstall, profile: Path, title: str) -> None:
    version = ".".join(str(part) for part in install.version)
    print(f"Geoblender · {title} · Blender {version} ({install.exe})")
    print(f"Perfil: {profile}")


def _uninstall(
    profile: Path,
    folder: Path,
    module: str,
    minimum: tuple[int, int, int],
    runner: blender.Runner,
    locate: Callable[[tuple[int, int, int]], BlenderInstall],
    environ: Mapping[str, str],
) -> int:
    prefs = profile / PREFS_RELPATH
    if not folder.exists() and not prefs.exists():
        print(f"No hay nada que desinstalar en el perfil «{profile}»")
        return EXIT_OK
    if prefs.exists():
        install = _locate(locate, minimum)
        if install is None:
            return EXIT_USAGE
        _header(install, profile, "desinstalación de desarrollo")
        ok, output = run_in_blender(install, profile, ACTION_DISABLE, module, runner, environ)
        if not ok:
            print(f"  fallo: no se pudo deshabilitar «{module}»; su carpeta no se ha borrado")
            print(output.rstrip())
            print("RESULTADO: NO VERDE")
            return EXIT_FAILED
        print(f"  deshabilitada: {module} (preferencias del perfil guardadas)")
    if folder.exists():
        _remove_tree(folder)
        print(f"  borrada: {folder}")
    print("RESULTADO: correcto")
    return EXIT_OK


def main(
    argv: Sequence[str] | None = None,
    *,
    root: Path | None = None,
    environ: Mapping[str, str] | None = None,
    runner: blender.Runner = blender.run,
    locate: Callable[[tuple[int, int, int]], BlenderInstall] = blender.locate_blender,
    launcher: Launcher | None = None,
    drive_type: Callable[[str], int] = drive_type,
) -> int:
    """Instala (o desinstala) la extensión en el perfil de desarrollo y devuelve el
    código de salida.

    Los parámetros con nombre solo los cambian las pruebas: raíz del repositorio,
    entorno, ejecutor de órdenes, localizador de Blender, lanzador de Blender con
    interfaz y tipo de unidad.
    """
    environ = os.environ if environ is None else environ
    launcher = _launch if launcher is None else launcher
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
    try:
        profile = resolve_profile(options.profile, environ)
    except UsageError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    problem = profile_problem(profile, root, environ, drive_type)
    if problem is not None:
        print(f"Error: {problem}. No se ha copiado nada.", file=sys.stderr)
        return EXIT_USAGE

    rel = manifest.MANIFEST_RELPATH
    try:
        data = manifest.load(root / rel)
        minimum = manifest.blender_min(data)
        excludes = manifest.exclude_patterns(data)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, ValueError) as exc:
        print(f"ERROR: no se puede leer el manifiesto «{rel}»: {exc}", file=sys.stderr)
        return EXIT_FAILED
    module = installed_module(data)
    folder = profile / "extensions" / INSTALL_REPO / str(data["id"])
    if options.uninstall:
        return _uninstall(profile, folder, module, minimum, runner, locate, environ)

    install = _locate(locate, minimum)
    if install is None:
        return EXIT_USAGE
    _header(install, profile, "instalación de desarrollo")
    try:
        report = sync.mirror(root / EXTENSION_FOLDER, folder, excludes)
    except (sync.SyncError, UnsupportedPattern, OSError) as exc:
        print(f"  fallo: no se pudo copiar la extensión a «{folder}»: {exc}")
        print("RESULTADO: NO VERDE")
        return EXIT_FAILED
    print(f"  destino: {folder}")
    print("\n".join(_copy_summary(report)))
    ok, output = run_in_blender(install, profile, ACTION_ENABLE, module, runner, environ)
    if not ok:
        print(f"  fallo: Blender no dejó «{module}» habilitada en el perfil")
        print(output.rstrip())
        print("RESULTADO: NO VERDE")
        return EXIT_FAILED
    print(f"  habilitada: {module} (preferencias del perfil guardadas)")
    if options.open:
        try:
            launcher(
                [str(install.exe)],
                env=blender.isolated_env(profile, base=environ),
                cwd=str(profile),
            )
        except OSError as exc:
            print(f"  fallo: no se pudo abrir Blender: {exc}")
            print("RESULTADO: NO VERDE")
            return EXIT_FAILED
        print("  Blender abierto con el perfil de desarrollo (no se espera a que se cierre)")
    else:
        print("Para abrir Blender con este perfil (PowerShell):")
        print(f"  {open_command(install, profile)}")
        print(f'  o bien: & "{install.python}" tools/dev_install.py {OPTION_OPEN}')
    print("RESULTADO: correcto")
    return EXIT_OK


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(_stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")
    sys.exit(main())

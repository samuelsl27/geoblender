# SPDX-License-Identifier: GPL-3.0-or-later
"""Instala o desinstala la plantilla de aplicación «Geoblender» y su lanzador (spec 003,
T34; RF-003-25; ADR-0003; CW §7; D-2).

Se ejecuta con el Python de Blender, desde la raíz del repositorio::

    & "C:\\Program Files\\Blender Foundation\\Blender 5.2\\5.2\\python\\bin\\python.exe" -B tools/install_app_template.py [--perfil DIR] [--lanzador DIR] [--desinstalar]

- **Plantilla:** copia ``packaging/app_template/Geoblender/`` (su ``__init__.py``,
  ``startup.blend``, ``userpref.blend``, ``splash.png``, ``splash_2x.png`` y ``LICENSE``) a
  ``<scripts>/startup/bl_app_templates_user/Geoblender/``, donde ``<scripts>`` es la carpeta
  de guiones del usuario de Blender: la de ``--perfil`` (un perfil como el de
  ``BLENDER_USER_RESOURCES``: ``<perfil>/scripts``), la de ``BLENDER_USER_SCRIPTS``, la de
  ``BLENDER_USER_RESOURCES`` o la normal (``%APPDATA%\\Blender Foundation\\Blender\\<versión
  mínima del manifiesto>\\scripts``). Perfil de Blender compartido (D-2): la configuración
  que guarde la persona con la plantilla va a ``config/Geoblender/`` y no pisa la suya.
- **Lanzador:** copia ``packaging/Geoblender.cmd`` a ``--lanzador`` o, por defecto, al
  escritorio de la persona (la carpeta «Desktop» de sus carpetas de shell).
- ``--desinstalar``: quita las dos cosas, si son de Geoblender, y nada más (ni la
  extensión, ni ``config/Geoblender/``, que son de la persona).

Nunca sustituye una carpeta o un fichero que no sean de Geoblender: si el destino existe y
no lo es, lo dice y no copia nada. La extensión se instala aparte (desde Blender o con
``tools/dev_install.py``); la plantilla la habilita al arrancar si está instalada.

Códigos de salida: 0 correcto; 1 un destino no es de Geoblender o la copia falló; 2 opción
no válida o faltan los ficheros de la plantilla (``tools/make_app_template.py``).
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # sin __pycache__ en Z: (plan 001 §5.3)

import filecmp  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import tomllib  # noqa: E402
from collections.abc import Callable, Mapping, Sequence  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402

from gbtools import blender, layout, manifest  # noqa: E402
from gbtools.repo import repo_root  # noqa: E402

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
TEMPLATES_SUBDIR = Path("startup") / "bl_app_templates_user"
ENV_USER_SCRIPTS = "BLENDER_USER_SCRIPTS"
REQUIRED_FILES: tuple[str, ...] = ("__init__.py", "startup.blend", "userpref.blend",
                                   "splash.png", "LICENSE")
TEMPLATE_MARKER = "Plantilla de aplicación «Geoblender»"  # en su __init__.py
LAUNCHER_MARKER = "--app-template"  # en el lanzador
SKIPPED = ("__pycache__",)
USAGE = ("Uso: tools/install_app_template.py [--perfil DIR] [--lanzador DIR] "
         "[--desinstalar]")


class UsageError(Exception):
    """Opciones no válidas: el mensaje dice cuál."""


@dataclass(frozen=True)
class Options:
    profile: Path | None = None
    launcher_dir: Path | None = None
    uninstall: bool = False
    show_help: bool = False


def parse_args(args: Sequence[str]) -> Options:
    profile: Path | None = None
    launcher: Path | None = None
    uninstall = False
    rest = list(args)
    while rest:
        arg = rest.pop(0)
        if arg in ("--ayuda", "-h", "--help"):
            return Options(show_help=True)
        if arg == "--perfil" and rest:
            profile = Path(rest.pop(0))
        elif arg == "--lanzador" and rest:
            launcher = Path(rest.pop(0))
        elif arg == "--desinstalar":
            uninstall = True
        else:
            raise UsageError(f"opción no válida: «{arg}»")
    return Options(profile, launcher, uninstall)


def blender_series(root: Path) -> str:
    """La serie de Blender de la configuración del usuario (``"5.2"``), la de la versión
    mínima del manifiesto."""
    major, minor, _patch = manifest.blender_min(manifest.load(root / manifest.MANIFEST_RELPATH))
    return f"{major}.{minor}"


def user_scripts_dir(environ: Mapping[str, str], series: str,
                     profile: Path | None = None) -> Path:
    """La carpeta de guiones del usuario de Blender (``…\\scripts``)."""
    if profile is not None:
        return Path(profile) / "scripts"
    if environ.get(ENV_USER_SCRIPTS):
        return Path(environ[ENV_USER_SCRIPTS])
    if environ.get(blender.ENV_USER_RESOURCES):
        return Path(environ[blender.ENV_USER_RESOURCES]) / "scripts"
    appdata = environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Blender Foundation" / "Blender" / series / "scripts"


def template_dir(scripts: Path) -> Path:
    """Dónde va la plantilla dentro de la carpeta de guiones."""
    return scripts / TEMPLATES_SUBDIR / layout.APP_TEMPLATE_ID


def desktop_dir(environ: Mapping[str, str]) -> Path:
    """El escritorio de la persona (la carpeta de shell «Desktop»; si no se puede leer,
    ``%USERPROFILE%\\Desktop``)."""
    try:
        import winreg

        key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
            value, _kind = winreg.QueryValueEx(handle, "Desktop")
        return Path(os.path.expandvars(str(value)))
    except (ImportError, OSError):
        home = environ.get("USERPROFILE") or str(Path.home())
        return Path(home) / "Desktop"


def is_our_template(folder: Path) -> bool:
    """Si ``folder`` es una plantilla de Geoblender (su ``__init__.py`` lo dice)."""
    init = folder / "__init__.py"
    try:
        return init.is_file() and TEMPLATE_MARKER in init.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False


def is_our_launcher(path: Path) -> bool:
    """Si ``path`` es el lanzador de Geoblender."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return LAUNCHER_MARKER in text and layout.APP_TEMPLATE_ID in text


def _copy_template(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(*SKIPPED))


def install(source: Path, launcher: Path, scripts: Path, launcher_dir: Path) -> list[str]:
    """Copia la plantilla y el lanzador; devuelve lo que hizo. ``RuntimeError`` (sin
    copiar nada) si un destino existe y no es de Geoblender."""
    target = template_dir(scripts)
    launcher_target = launcher_dir / launcher.name
    if target.exists() and not is_our_template(target):
        raise RuntimeError(f"«{target}» existe y no es la plantilla de Geoblender; no se "
                           "ha copiado nada")
    if launcher_target.exists() and not is_our_launcher(launcher_target):
        raise RuntimeError(f"«{launcher_target}» existe y no es el lanzador de Geoblender; "
                           "no se ha copiado nada")
    _copy_template(source, target)
    launcher_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(launcher, launcher_target)
    return [f"plantilla: {target}", f"lanzador: {launcher_target}"]


def uninstall(scripts: Path, launcher_dir: Path) -> list[str]:
    """Quita la plantilla y el lanzador si son de Geoblender; devuelve lo que hizo."""
    done: list[str] = []
    target = template_dir(scripts)
    if is_our_template(target):
        shutil.rmtree(target)
        done.append(f"quitada la plantilla: {target}")
        for folder in (target.parent, target.parent.parent, scripts):
            try:
                folder.rmdir()  # solo si ha quedado vacía (la creó la instalación)
            except OSError:
                break
    elif target.exists():
        done.append(f"no se quita «{target}»: no es la plantilla de Geoblender")
    launcher_target = launcher_dir / layout.LAUNCHER_NAME
    if is_our_launcher(launcher_target):
        launcher_target.unlink()
        done.append(f"quitado el lanzador: {launcher_target}")
    elif launcher_target.exists():
        done.append(f"no se quita «{launcher_target}»: no es el lanzador de Geoblender")
    return done or ["no había nada de Geoblender que quitar"]


def same_files(source: Path, target: Path) -> bool:
    """Si la plantilla instalada es igual que la del repositorio."""
    names = sorted(p.name for p in source.iterdir() if p.name not in SKIPPED)
    installed = sorted(p.name for p in target.iterdir()) if target.is_dir() else []
    return names == installed and all(
        filecmp.cmp(source / name, target / name, shallow=False) for name in names
    )


def main(argv: Sequence[str] | None = None, *, root: Path | None = None,
         environ: Mapping[str, str] | None = None,
         desktop: Callable[[Mapping[str, str]], Path] = desktop_dir) -> int:
    """Instala (o desinstala) la plantilla y el lanzador; devuelve el código de salida.
    Los parámetros con nombre solo los cambian las pruebas."""
    environ = os.environ if environ is None else environ
    try:
        options = parse_args(list(sys.argv[1:] if argv is None else argv))
    except UsageError as exc:
        print(f"Error: {exc}\n\n{USAGE}", file=sys.stderr)
        return EXIT_USAGE
    if options.show_help:
        print(__doc__)
        print(USAGE)
        return EXIT_OK
    root = repo_root(Path(__file__)) if root is None else Path(root)
    try:
        series = blender_series(root)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, ValueError) as exc:
        print(f"ERROR: no se puede leer el manifiesto: {exc}", file=sys.stderr)
        return EXIT_USAGE
    scripts = user_scripts_dir(environ, series, options.profile)
    launcher_dir = options.launcher_dir or desktop(environ)
    if options.uninstall:
        print("\n".join(f"  {line}" for line in uninstall(scripts, launcher_dir)))
        print("RESULTADO: correcto")
        return EXIT_OK
    source = root / layout.APP_TEMPLATE_RELPATH
    launcher = root / layout.LAUNCHER_RELPATH
    missing = [name for name in REQUIRED_FILES if not (source / name).is_file()]
    if missing or not launcher.is_file():
        what = ", ".join(missing + ([] if launcher.is_file() else [str(launcher)]))
        print(f"ERROR: faltan {what}; genérelos con tools/make_app_template.py",
              file=sys.stderr)
        return EXIT_USAGE
    try:
        done = install(source, launcher, scripts, launcher_dir)
    except (RuntimeError, OSError) as exc:
        print(f"RESULTADO: NO VERDE: {exc}")
        return EXIT_FAILED
    print("\n".join(f"  {line}" for line in done))
    print(f"Abra Geoblender con «{launcher_dir / launcher.name}» (o "
          f"«blender --app-template {layout.APP_TEMPLATE_ID}»).")
    print("RESULTADO: correcto")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

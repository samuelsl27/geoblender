# SPDX-License-Identifier: GPL-3.0-or-later
"""Genera los ficheros de la plantilla de aplicación «Geoblender» (spec 003, T34;
RF-003-25; ADR-0003; CW §7; plan 003 §5.4, 13; D-2).

Se ejecuta con el Python de Blender, desde la raíz del repositorio::

    & "C:\\Program Files\\Blender Foundation\\Blender 5.2\\5.2\\python\\bin\\python.exe" -B tools/make_app_template.py [--salida DIR]

1. Crea un perfil de Blender temporal e instala y habilita en él la extensión del
   repositorio (``tools/dev_install.py --perfil``).
2. Con ese perfil, en segundo plano y **sin** configuración de fábrica (para que se vea la
   extensión), ejecuta ``tools/inblender/make_app_template_blend.py``, que escribe en
   ``--salida`` (por defecto ``packaging/app_template/Geoblender/``): ``userpref.blend``
   (la extensión habilitada, sin estadísticas de la escena en la barra de estado),
   ``startup.blend`` (el espacio principal de ``layouts.toml`` y «Layout», escena vacía en
   metros), ``splash.png`` y ``splash_2x.png`` (de ``assets/splash/splash.svg``).
3. Borra el perfil temporal. Nunca toca la configuración de Blender del usuario.

Los ficheros generados se versionan (CC0-1.0, con el ``LICENSE`` de la carpeta). Se vuelven
a generar cuando cambia la imagen de bienvenida, ``geoblender_ui.blend`` o la versión de
Blender. Los instala ``tools/install_app_template.py``.

Códigos de salida: 0 correcto; 1 la instalación de la extensión o la generación fallaron;
2 entorno (Blender ausente o anterior al mínimo) u opción no válida.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # sin __pycache__ en Z: (plan 001 §5.3)

import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import tomllib  # noqa: E402
from collections.abc import Callable, Sequence  # noqa: E402
from pathlib import Path  # noqa: E402

import dev_install  # noqa: E402
from gbtools import blender, layout, manifest  # noqa: E402
from gbtools.blender import BlenderInstall, EnvironmentProblem  # noqa: E402
from gbtools.repo import repo_root  # noqa: E402

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
SCRIPT = Path("tools") / "inblender" / "make_app_template_blend.py"
END_LINE = "FIN make_app_template_blend:"
TEMP_PREFIX = "gb-plantilla-"
TIMEOUT_S = 600.0
OUTPUT_FILES: tuple[str, ...] = ("userpref.blend", "startup.blend", "splash.png",
                                 "splash_2x.png")
USAGE = "Uso: tools/make_app_template.py [--salida DIR]"


class UsageError(Exception):
    """Opciones no válidas: el mensaje dice cuál."""


def parse_args(args: Sequence[str]) -> tuple[Path | None, bool]:
    """(``--salida`` o ``None``, ayuda pedida)."""
    output: Path | None = None
    rest = list(args)
    while rest:
        arg = rest.pop(0)
        if arg in ("--ayuda", "-h", "--help"):
            return output, True
        if arg == "--salida" and rest:
            output = Path(rest.pop(0))
        else:
            raise UsageError(f"opción no válida: «{arg}»")
    return output, False


def main_workspace(root: Path) -> str:
    """El espacio de trabajo de la disposición principal (``main = true`` de
    ``layouts.toml``)."""
    data = tomllib.loads((root / layout.LAYOUTS_TOML_RELPATH).read_text(encoding="utf-8"))
    for item in data.get("layout", ()):
        if item.get("main"):
            return str(item["workspace"])
    raise ValueError("layouts.toml no tiene disposición principal")


def generate(install: BlenderInstall, root: Path, profile: Path, output: Path,
             runner: blender.Runner) -> tuple[bool, str]:
    """Ejecuta el guion de dentro de Blender con ``profile``; devuelve si terminó bien
    y su salida."""
    cmd = blender.profile_cmd(
        install, root / SCRIPT,
        "--salida", str(output),
        "--ui", str(root / layout.UI_BLEND_RELPATH),
        "--principal", main_workspace(root),
        "--splash", str(root / layout.SPLASH_SVG_RELPATH),
    )
    try:
        result = runner(cmd, env=blender.isolated_env(profile), cwd=root, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return False, f"Blender no terminó en {TIMEOUT_S:.0f} s"
    text = (result.stdout or "") + (result.stderr or "")
    return result.returncode == 0 and END_LINE in text, text


def main(argv: Sequence[str] | None = None, *, root: Path | None = None,
         runner: blender.Runner = blender.run,
         locate: Callable[[tuple[int, int, int]], BlenderInstall] = blender.locate_blender,
         install_extension: Callable[[Path, Path], int] | None = None) -> int:
    """Genera la plantilla y devuelve el código de salida. Los parámetros con nombre solo
    los cambian las pruebas."""
    try:
        output, show_help = parse_args(list(sys.argv[1:] if argv is None else argv))
    except UsageError as exc:
        print(f"Error: {exc}\n\n{USAGE}", file=sys.stderr)
        return EXIT_USAGE
    if show_help:
        print(__doc__)
        print(USAGE)
        return EXIT_OK
    root = repo_root(Path(__file__)) if root is None else Path(root)
    output = output or root / layout.APP_TEMPLATE_RELPATH
    try:
        install = locate(manifest.blender_min(manifest.load(root / manifest.MANIFEST_RELPATH)))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, ValueError) as exc:
        print(f"ERROR DE ENTORNO: no se puede leer el manifiesto: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except EnvironmentProblem as exc:
        print(f"ERROR DE ENTORNO: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if install_extension is None:
        def install_extension(repo: Path, profile: Path) -> int:
            return dev_install.main(["--perfil", str(profile)], root=repo)

    profile = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
    try:
        if install_extension(root, profile) != 0:
            print("RESULTADO: NO VERDE: no se pudo instalar la extensión en el perfil temporal")
            return EXIT_FAILED
        output.mkdir(parents=True, exist_ok=True)
        ok, text = generate(install, root, profile, output, runner)
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    if not ok:
        print(text)
        print("RESULTADO: NO VERDE: Blender no generó la plantilla")
        return EXIT_FAILED
    missing = [name for name in OUTPUT_FILES if not (output / name).is_file()]
    if missing:
        print(f"RESULTADO: NO VERDE: faltan {', '.join(missing)} en «{output}»")
        return EXIT_FAILED
    for name in OUTPUT_FILES:
        print(f"  {name}: {(output / name).stat().st_size} bytes")
    print(f"RESULTADO: correcto: plantilla en «{output}»")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

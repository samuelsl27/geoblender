# SPDX-License-Identifier: GPL-3.0-or-later
"""Iconos propios de Geoblender: de las fuentes SVG a los PNG (spec 003, T30; RF-003-22;
RNF-003-09; plan 003 §5.4, 12; II §1.6).

Se ejecuta con el Python de Blender, desde la raíz del repositorio::

    & "C:\\Program Files\\Blender Foundation\\Blender 5.2\\5.2\\python\\bin\\python.exe" -B tools/build_icons.py [--check]

Sin opciones (genera):

1. Valida cada fuente ``assets/icons/<nombre>.svg`` (``gbtools.icons.svg_problems``:
   ``viewBox="0 0 16 16"``, solo ``path``, ``rect``, ``circle``, ``line``, ``polyline``,
   ``polygon`` y ``g``, sin texto ni imágenes ni referencias externas ni scripts, con los
   metadatos CC0 de II §1.7). Si alguna falla, dice cuál y por qué y **no genera nada**.
2. Localiza Blender (``GEOBLENDER_BLENDER`` o la ruta por defecto, con la versión mínima
   del manifiesto) y ejecuta en segundo plano, de fábrica, con un perfil temporal y
   ``--python-exit-code 1``, ``tools/inblender/rasterize_icons.py``: rasteriza cada SVG a
   256 × 256 con ``bpy.utils.previews`` y lo reduce a 64 y 32 px con un filtro de caja en
   alfa premultiplicada (``geoblender/resources/icons/<nombre>_32.png`` y ``_64.png``,
   RGBA de 8 bits).
3. Borra los PNG que no son de ninguna fuente y escribe ``manifest.json`` (sha256 de cada
   SVG y de sus PNG y la versión de Blender del rasterizado).
4. Comprueba el resultado como ``--check``.

Con ``--check`` (paso «iconos» de ``tools/check.py``) no rasteriza ni importa ``bpy``:
falla si una fuente cambió sin regenerar sus PNG, si falta o sobra un PNG o una entrada del
manifiesto, si un PNG no mide 32 o 64 px o pasa de 8 KB, o si una fuente no es válida.

``--fuentes DIR`` y ``--salida DIR`` cambian las carpetas (las pruebas). Códigos de salida:
0 correcto; 1 fuentes no válidas, rasterizado fallido o comprobación con incumplimientos;
2 entorno (Blender ausente o anterior al mínimo) u opción no válida.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # sin __pycache__ en Z: (plan 001 §5.3)

import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import tomllib  # noqa: E402
from collections.abc import Callable, Sequence  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402

from gbtools import blender, icons, manifest  # noqa: E402
from gbtools.blender import BlenderInstall, EnvironmentProblem  # noqa: E402
from gbtools.repo import repo_root  # noqa: E402

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
RASTERIZE_SCRIPT = Path("tools") / "inblender" / "rasterize_icons.py"
RASTERIZE_TIMEOUT_S = 600.0
END_LINE = "FIN rasterize_icons:"
TEMP_PREFIX = "gb-iconos-"
USAGE = "Uso: tools/build_icons.py [--check] [--fuentes DIR] [--salida DIR]"


class UsageError(Exception):
    """Una opción no válida."""


@dataclass(frozen=True)
class Options:
    check: bool = False
    sources: Path | None = None
    output: Path | None = None
    show_help: bool = False


def parse_args(args: Sequence[str]) -> Options:
    """Lee las opciones; lanza :class:`UsageError` si alguna no existe o le falta su
    valor."""
    check = show_help = False
    folders: dict[str, Path] = {}
    pending: str | None = None
    for arg in args:
        if pending is not None:
            folders[pending] = Path(arg)
            pending = None
        elif arg == "--check":
            check = True
        elif arg in ("--ayuda", "-h", "--help"):
            show_help = True
        elif arg in ("--fuentes", "--salida"):
            pending = arg
        else:
            raise UsageError(f"opción desconocida «{arg}»")
    if pending is not None:
        raise UsageError(f"falta la carpeta de {pending}")
    return Options(check=check, sources=folders.get("--fuentes"),
                   output=folders.get("--salida"), show_help=show_help)


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def invalid_sources(svg_dir: Path, root: Path) -> list[str]:
    """«<fuente>: <motivo>» de cada fuente no válida."""
    return [f"{_rel(svg, root)}: {problem}"
            for svg in icons.svg_files(svg_dir) for problem in icons.svg_problems(svg)]


def check(svg_dir: Path, png_dir: Path, root: Path) -> list[str]:
    """``--check``: fuentes no válidas y lo que no cuadra entre fuentes, PNG y
    manifiesto."""
    return [*invalid_sources(svg_dir, root), *icons.check_problems(svg_dir, png_dir)]


def rasterize(install: BlenderInstall, root: Path, svg_dir: Path, png_dir: Path,
              runner: blender.Runner) -> tuple[bool, str]:
    """Ejecuta el rasterizado dentro de Blender con un perfil temporal; devuelve si
    terminó bien y su salida."""
    profile = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
    try:
        cmd = blender.background_cmd(install, root / RASTERIZE_SCRIPT, "--fuentes",
                                     str(svg_dir), "--salida", str(png_dir))
        try:
            result = runner(cmd, env=blender.isolated_env(profile), cwd=root,
                            timeout=RASTERIZE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return False, f"el rasterizado no terminó en {RASTERIZE_TIMEOUT_S:.0f} s"
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode == 0 and END_LINE in output, output


def generate(root: Path, svg_dir: Path, png_dir: Path, *, runner: blender.Runner,
             locate: Callable[[tuple[int, int, int]], BlenderInstall]) -> int:
    """Valida, rasteriza, limpia y escribe el manifiesto; devuelve el código de salida."""
    invalid = invalid_sources(svg_dir, root)
    if invalid:
        print("\n".join(invalid))
        print(f"RESULTADO: NO VERDE: {len(invalid)} problemas en las fuentes; no se ha "
              "generado nada")
        return EXIT_FAILED
    svgs = icons.svg_files(svg_dir)
    try:
        minimum = manifest.blender_min(manifest.load(root / manifest.MANIFEST_RELPATH))
        install = locate(minimum)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, ValueError) as exc:
        print(f"ERROR DE ENTORNO: no se puede leer el manifiesto: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except EnvironmentProblem as exc:
        print(f"ERROR DE ENTORNO: {exc}", file=sys.stderr)
        return EXIT_USAGE
    version = ".".join(str(part) for part in install.version)
    print(f"Geoblender · iconos · Blender {version} ({install.exe}) · {len(svgs)} fuentes")
    png_dir.mkdir(parents=True, exist_ok=True)
    if svgs:
        ok, output = rasterize(install, root, svg_dir, png_dir, runner)
        if not ok:
            print(output)
            print("RESULTADO: NO VERDE: el rasterizado falló")
            return EXIT_FAILED
    for orphan in icons.orphan_pngs(svg_dir, png_dir):
        orphan.unlink()
        print(f"  quitado {_rel(orphan, root)} (sin fuente)")
    icons.write_manifest(png_dir, icons.build_manifest(svg_dir, png_dir, version))
    problems = icons.check_problems(svg_dir, png_dir)
    if problems:
        print("\n".join(problems))
        print(f"RESULTADO: NO VERDE: {len(problems)} problemas")
        return EXIT_FAILED
    print(f"RESULTADO: correcto: {len(svgs)} iconos, {2 * len(svgs)} PNG")
    return EXIT_OK


def main(argv: Sequence[str] | None = None, *, root: Path | None = None,
         runner: blender.Runner = blender.run,
         locate: Callable[[tuple[int, int, int]], BlenderInstall] = blender.locate_blender,
         ) -> int:
    """Genera los iconos (o los comprueba con ``--check``) y devuelve el código de salida.
    Los parámetros con nombre solo los cambian las pruebas."""
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
    root = repo_root(Path(__file__)) if root is None else Path(root)
    svg_dir = options.sources or root / icons.SVG_DIR_RELPATH
    png_dir = options.output or root / icons.PNG_DIR_RELPATH
    if not options.check:
        return generate(root, svg_dir, png_dir, runner=runner, locate=locate)
    problems = check(svg_dir, png_dir, root)
    seconds = f"{time.perf_counter() - started:.1f}".replace(".", ",")
    if problems:
        print("\n".join(problems))
        print(f"RESULTADO: NO VERDE ({seconds} s): {len(problems)} problemas en los iconos")
        return EXIT_FAILED
    count = len(icons.svg_files(svg_dir))
    print(f"RESULTADO: correcto ({seconds} s): {count} iconos con sus PNG y su manifiesto")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

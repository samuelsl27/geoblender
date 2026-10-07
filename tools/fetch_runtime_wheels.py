# SPDX-License-Identifier: GPL-3.0-or-later
"""El almacén de ruedas del motor de cálculo (spec 004, T30; RF-004-24; plan 004 §5.1; D-4,
DP-69).

La ejecuta la persona que mantiene el almacén (local o del NAS), con el Python de Blender,
desde la raíz del repositorio::

    & "C:\\Program Files\\Blender Foundation\\Blender 5.2\\5.2\\python\\bin\\python.exe" tools/fetch_runtime_wheels.py [--wheelhouse CARPETA]

Deja en el almacén (``--wheelhouse``; por defecto, la carpeta de ``GEOBLENDER_WHEELHOUSE``,
que tiene que existir) cada rueda del lock de la extensión (``jobs/runtime_lock.toml``) con
su nombre de fichero. La descarga de la URL del lock ``jobs.runtime.fetch_wheel``, el código
del producto (cargado con ``gbtools.package.load_geoblender``, HER-01), que calcula su sha256
mientras la lee y solo la deja si es la del lock: de una descarga con otra huella no queda
nada. Una rueda que ya está con su huella no se vuelve a descargar; una que está con otra
huella no se toca (otra persona la puso: que lo mire quien mantiene el almacén) y la orden
termina con 1.

Las instalaciones del motor desde ese almacén (el diálogo de Geoblender y
``tools/make_runtime.py --wheelhouse``) no usan la red y vuelven a comprobar cada huella.

Códigos de salida: 0 el almacén tiene todas las ruedas del lock; 1 una rueda del almacén con
otra huella, una descarga que falla o que no es la del lock; 2 error de uso o de entorno
(opciones, almacén que no existe, lock ilegible).
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # sin __pycache__ (plan 001 §5.3)

import os  # noqa: E402
from collections.abc import Mapping, Sequence  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402

from gbtools import layout, wheels  # noqa: E402
from gbtools.repo import repo_root  # noqa: E402
from make_runtime import load_runtime  # noqa: E402

OPTION_WHEELHOUSE = "--wheelhouse"
SCRIPT_RELPATH = "tools/fetch_runtime_wheels.py"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2

USAGE = f"""Uso (con el Python de Blender, desde la raíz del repositorio):
  & "<Blender>\\5.2\\python\\bin\\python.exe" {SCRIPT_RELPATH} [{OPTION_WHEELHOUSE} CARPETA]

  {OPTION_WHEELHOUSE} CARPETA  el almacén que se llena (por defecto, el de {wheels.ENV_WHEELHOUSE})
  --ayuda, -h          muestra esta ayuda

Códigos: 0 correcto, 1 una rueda que no es la del lock o que no se descarga, 2 error de uso."""


class UsageError(Exception):
    """Opciones, almacén o lock no válidos: el mensaje dice cuál."""


@dataclass(frozen=True)
class Options:
    wheelhouse: str | None = None
    show_help: bool = False


def parse_args(args: Sequence[str]) -> Options:
    """Lee ``--wheelhouse CARPETA`` (o ``--wheelhouse=CARPETA``); lanza
    :class:`UsageError` si una opción no existe o falta su valor."""
    wheelhouse: str | None = None
    show_help = False
    pending = list(args)
    while pending:
        arg = pending.pop(0)
        if arg in ("--ayuda", "-h", "--help"):
            show_help = True
            continue
        name, equals, value = arg.partition("=")
        if name != OPTION_WHEELHOUSE:
            raise UsageError(f"opción desconocida «{arg}»")
        if not equals:
            if not pending or pending[0].startswith("--"):
                raise UsageError(f"falta la carpeta de «{OPTION_WHEELHOUSE}»")
            value = pending.pop(0)
        if not value.strip():
            raise UsageError(f"«{OPTION_WHEELHOUSE}» no puede estar vacío")
        wheelhouse = value.strip()
    return Options(wheelhouse=wheelhouse, show_help=show_help)


def store_folder(options: Options, environ: Mapping[str, str]) -> Path:
    """El almacén: ``--wheelhouse`` o ``GEOBLENDER_WHEELHOUSE``; :class:`UsageError` si no
    hay ninguno o no existe."""
    if options.wheelhouse is not None:
        folder, origin = options.wheelhouse, f"«{OPTION_WHEELHOUSE}»"
    else:
        store = wheels.wheelhouse(environ)
        if store is None:
            raise UsageError(
                f"indique el almacén: {OPTION_WHEELHOUSE} CARPETA o la variable "
                f"{wheels.ENV_WHEELHOUSE}"
            )
        folder, origin = store, f"la variable {wheels.ENV_WHEELHOUSE}"
    path = Path(folder)
    if not path.is_dir():
        raise UsageError(f"no existe el almacén de ruedas «{folder}» (de {origin})")
    return path.absolute()


def fetch(runtime: object, lock: object, store: Path) -> int:
    """Trae al almacén ``store`` las ruedas de ``lock`` que faltan (``runtime.fetch_wheel``)
    y devuelve el código de salida."""
    source = runtime.WheelSource.pypi()
    failed = 0
    for package in lock.packages:
        target = store / package.filename
        if target.exists():
            found = wheels.sha256_file(target)
            if found == package.sha256:
                print(f"  {package.filename}: ya está, con su huella")
                continue
            print(
                f"ERROR: {package.filename} ya está en el almacén con otra huella ({found}; "
                f"el lock dice {package.sha256}): no se toca; bórrela o compruebe de dónde "
                "salió",
                file=sys.stderr,
            )
            failed += 1
            continue
        try:
            runtime.fetch_wheel(package, source, store)
        except runtime.JobError as exc:
            print(f"ERROR: {exc.text}", file=sys.stderr)
            failed += 1
            continue
        print(f"  {package.filename}: descargada, con su huella ({package.size} bytes)")
    if failed:
        print(f"Almacén de ruedas: NO VERDE, {failed} de {len(lock.packages)} ruedas con "
              "problemas", file=sys.stderr)
        return EXIT_FAILED
    print(f"Almacén de ruedas «{store}»: correcto, {len(lock.packages)} ruedas del lock "
          f"{lock.lock_id}")
    return EXIT_OK


def main(
    argv: Sequence[str] | None = None,
    *,
    root: Path | None = None,
    environ: Mapping[str, str] | None = None,
    lock_path: Path | None = None,
) -> int:
    """Llena el almacén y devuelve el código de salida.

    ``root`` (raíz del repositorio con la extensión), ``environ`` (donde se busca
    ``GEOBLENDER_WHEELHOUSE``) y ``lock_path`` (el lock; por defecto, el de la extensión)
    solo los cambian las pruebas.
    """
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
    if root is None:
        try:
            root = repo_root(Path(__file__))
        except FileNotFoundError as exc:
            print(f"ERROR DE ENTORNO: {exc}", file=sys.stderr)
            return EXIT_USAGE
    root = Path(root)
    lock_file = (root / layout.RUNTIME_LOCK_RELPATH) if lock_path is None else Path(lock_path)
    try:
        store = store_folder(options, environ)
        runtime = load_runtime(root)
        lock = runtime.read_lock(lock_file)
    except (UsageError, ImportError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    print(f"Ruedas del motor de cálculo · lock {lock.lock_id} · almacén «{store}»")
    return fetch(runtime, lock, store)


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(_stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")
    sys.exit(main())

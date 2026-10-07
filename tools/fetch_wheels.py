# SPDX-License-Identifier: GPL-3.0-or-later
"""Descarga de las ruedas fijadas en ``tools/wheels.toml`` (plan 001 §5.4.12; RF-001-25).

La ejecuta una persona, con el Python de Blender, desde la raíz del repositorio::

    & "C:\\Program Files\\Blender Foundation\\Blender 5.2\\5.2\\python\\bin\\python.exe" tools/fetch_wheels.py [--desde CARPETA]

1. Lee ``tools/wheels.toml``; si no cumple LIC-01, lo dice y sale con 1 sin tocar nada.
2. Reúne cada rueda en una carpeta de trabajo de ``%TEMP%``: con ``--desde`` (por
   defecto, la carpeta de ``GEOBLENDER_WHEELHOUSE``: el almacén local o del NAS) copia
   ``<carpeta>/<fichero>``; si no, busca el fichero en el JSON de PyPI
   (``https://pypi.org/pypi/<nombre>/<versión>/json``, con ``urllib`` y 60 s),
   comprueba que el sha256 que publica PyPI es el fijado y lo descarga.
3. Comprueba el sha256 de cada fichero, que es un zip y que, si trae DLL en
   ``<paquete>.libs/``, su ``bundled_licenses`` no está vacío (ADR-0017 §4), y extrae
   todas en la carpeta de trabajo. Si una falta, no tiene el sha256 fijado (se dan los
   dos hashes), no está auditada o no se puede extraer, sale con 1 **sin cambiar nada**
   (todo o nada).
4. Con todo comprobado: deja en ``geoblender/wheels/`` exactamente las ruedas de destino
   «extension» (borra lo demás; si no hay ninguna, la carpeta no existe), sustituye
   ``.deps/site/`` por las ruedas de los dos destinos extraídas y escribe la lista de
   las «extension» en ``wheels = [...]`` del manifiesto (solo ese bloque, en UTF-8 sin
   BOM y LF; si no cambia, el manifiesto no se reescribe).

Solo usa la red si hay ruedas fijadas y ninguna carpeta de ruedas. No toca
``.deps/runtime/`` (spec 004).

Códigos de salida: 0 correcto; 1 LIC-01, una rueda que falta, que no es la fijada, sin
auditar o que no se puede extraer, o un manifiesto sin bloque ``wheels`` (nada cambia); 2
error de uso (opción desconocida, carpeta de ruedas que no existe).
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # sin __pycache__ en Z: (plan 001 §5.3)

import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import stat  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import urllib.request  # noqa: E402
import zipfile  # noqa: E402
from collections.abc import Callable, Mapping, Sequence  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

from gbtools import manifest, wheels  # noqa: E402
from gbtools.blender import DEPS_SITE_RELPATH  # noqa: E402
from gbtools.findings import format_findings  # noqa: E402
from gbtools.repo import repo_root  # noqa: E402
from gbtools.wheels import WheelSpec  # noqa: E402

PYPI_JSON = "https://pypi.org/pypi/{name}/{version}/json"
TIMEOUT_S = 60.0
TEMP_PREFIX = "geoblender-ruedas-"
OPTION_SOURCE = "--desde"
CHUNK = 1 << 20

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2

USAGE = f"""Uso (con el Python de Blender, desde la raíz del repositorio):
  & "<Blender>\\5.2\\python\\bin\\python.exe" tools/fetch_wheels.py [--desde CARPETA]

  --desde CARPETA  carpeta con las ruedas fijadas (por defecto, la de {wheels.ENV_WHEELHOUSE});
                   sin ninguna de las dos, se descargan de PyPI
  --ayuda, -h      muestra esta ayuda

Códigos: 0 correcto, 1 fallo (no cambia nada), 2 error de uso."""

Opener = Callable[..., Any]


class UsageError(Exception):
    """Opciones o carpeta de ruedas no válidas: el mensaje dice cuál."""


class FetchError(Exception):
    """Una rueda no se pudo obtener o no es la fijada: el mensaje la nombra."""


@dataclass(frozen=True)
class Options:
    source: str | None = None
    show_help: bool = False


def parse_args(args: Sequence[str]) -> Options:
    """Lee ``--desde CARPETA`` (o ``--desde=CARPETA``); lanza :class:`UsageError`."""
    source: str | None = None
    show_help = False
    pending = list(args)
    while pending:
        arg = pending.pop(0)
        if arg in ("--ayuda", "-h", "--help"):
            show_help = True
            continue
        name, equals, value = arg.partition("=")
        if name != OPTION_SOURCE:
            raise UsageError(f"opción desconocida «{arg}»")
        if not equals:
            if not pending or pending[0].startswith("--"):
                raise UsageError(f"falta la carpeta de «{OPTION_SOURCE}»")
            value = pending.pop(0)
        if not value.strip():
            raise UsageError(f"«{OPTION_SOURCE}» no puede estar vacío")
        source = value.strip()
    return Options(source=source, show_help=show_help)


def source_folder(options: Options, environ: Mapping[str, str]) -> Path | None:
    """Carpeta de ruedas: ``--desde`` o ``GEOBLENDER_WHEELHOUSE``; ``None`` para PyPI.

    Lanza :class:`UsageError` si la carpeta indicada no existe.
    """
    if options.source is not None:
        folder, origin = options.source, f"«{OPTION_SOURCE}»"
    else:
        store = wheels.wheelhouse(environ)
        if store is None:
            return None
        folder, origin = store, f"la variable {wheels.ENV_WHEELHOUSE}"
    path = Path(folder)
    if not path.is_dir():
        raise UsageError(
            f"no existe la carpeta de ruedas «{folder}» (de {origin}): corríjala o, para "
            "descargarlas de PyPI, no indique ninguna"
        )
    return path


def copy_from_folder(spec: WheelSpec, folder: Path, dest: Path) -> Path:
    """Copia ``<folder>/<fichero>`` a ``dest``; :class:`FetchError` si no está."""
    source = folder / spec.filename
    if not source.is_file():
        raise FetchError(
            f"la rueda «{spec.filename}» ({spec.name} {spec.version}) no está en la "
            f"carpeta de ruedas «{folder}»: cópiela allí, o ejecute la orden sin carpeta "
            "para descargarla de PyPI"
        )
    target = dest / spec.filename
    try:
        shutil.copyfile(source, target)
    except OSError as exc:
        raise FetchError(f"no se pudo copiar la rueda «{spec.filename}»: {exc}") from None
    return target


def download_from_pypi(spec: WheelSpec, dest: Path, opener: Opener) -> Path:
    """Busca el fichero en el JSON de PyPI, comprueba el sha256 que publica PyPI y lo
    descarga a ``dest``; :class:`FetchError` con el motivo si algo no cuadra."""
    url = PYPI_JSON.format(name=spec.name, version=spec.version)
    try:
        with opener(url, timeout=TIMEOUT_S) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise FetchError(
            f"no se pudo leer «{url}» para la rueda «{spec.filename}»: {exc}"
        ) from None
    files = data.get("urls") if isinstance(data, dict) else None
    entry = next(
        (
            item
            for item in (files if isinstance(files, list) else [])
            if isinstance(item, dict) and item.get("filename") == spec.filename
        ),
        None,
    )
    if entry is None:
        raise FetchError(
            f"PyPI no publica «{spec.filename}» para {spec.name} {spec.version} ({url})"
        )
    digests = entry.get("digests")
    published = str(digests.get("sha256", "") if isinstance(digests, dict) else "")
    if published.lower() != spec.sha256:
        raise FetchError(
            f"la rueda «{spec.filename}»: PyPI publica el sha256 {published or '(ninguno)'}"
            f" y {wheels.WHEELS_TOML_RELPATH} fija {spec.sha256}; no se descarga"
        )
    file_url = entry.get("url")
    if not isinstance(file_url, str) or not file_url.startswith("https://"):
        raise FetchError(
            f"PyPI no da una dirección https para «{spec.filename}» ({file_url!r})"
        )
    target = dest / spec.filename
    try:
        with opener(file_url, timeout=TIMEOUT_S) as response, target.open("wb") as out:
            while chunk := response.read(CHUNK):
                out.write(chunk)
    except OSError as exc:
        raise FetchError(f"no se pudo descargar «{file_url}»: {exc}") from None
    return target


def verify(spec: WheelSpec, path: Path) -> None:
    """:class:`FetchError` si ``path`` no tiene el sha256 fijado o no es un zip."""
    actual = wheels.sha256_file(path)
    if actual != spec.sha256:
        raise FetchError(
            f"la rueda «{spec.filename}» tiene el sha256 {actual} y "
            f"{wheels.WHEELS_TOML_RELPATH} fija {spec.sha256}: no es la rueda fijada y no "
            "se acepta"
        )
    if not zipfile.is_zipfile(path):
        raise FetchError(f"la rueda «{spec.filename}» no es un zip válido")


def _clear_readonly(
    function: Callable[..., object], path: str, _error: BaseException
) -> None:
    """Para ``shutil.rmtree``: quita el atributo de solo lectura y reintenta."""
    os.chmod(path, stat.S_IWRITE)
    function(path)


def _remove(path: Path, attempts: int = 5) -> None:
    """Borra un fichero, un enlace (sin seguirlo) o una carpeta entera, con reintentos
    (Windows puede retener un fichero un momento)."""
    for attempt in range(attempts):
        try:
            if path.is_symlink() or path.is_junction():
                os.unlink(path)
            elif path.is_dir():
                shutil.rmtree(path, onexc=_clear_readonly)
            elif path.exists():
                os.chmod(path, stat.S_IWRITE)
                path.unlink()
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.2 * (attempt + 1))


def _place_extension_wheels(root: Path, specs: Sequence[WheelSpec], downloads: Path) -> None:
    """Deja en ``geoblender/wheels/`` exactamente las ruedas ``specs``."""
    folder = root / wheels.WHEELS_DIR_RELPATH
    if not specs:
        if folder.exists() or folder.is_symlink():
            _remove(folder)
        return
    if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
        _remove(folder)
    folder.mkdir(parents=True, exist_ok=True)
    wanted = {spec.filename for spec in specs}
    for entry in list(folder.iterdir()):
        is_file = entry.is_file() and not entry.is_symlink()
        if entry.name not in wanted or not is_file:
            _remove(entry)
    for spec in specs:
        target = folder / spec.filename
        if target.is_file() and wheels.sha256_file(target) == spec.sha256:
            continue
        shutil.copyfile(downloads / spec.filename, target)


def _replace_site(root: Path, staged: Path) -> None:
    """Sustituye ``.deps/site/`` por la carpeta ``staged`` ya extraída."""
    site = root / DEPS_SITE_RELPATH
    if site.exists() or site.is_symlink():
        _remove(site)
    site.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(staged, site)


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def fetch(
    root: Path, specs: Sequence[WheelSpec], folder: Path | None, opener: Opener
) -> int:
    """Pasos 2 a 4 del módulo; devuelve el código de salida."""
    extension = [spec for spec in specs if spec.target == "extension"]
    filenames = [spec.filename for spec in extension]
    manifest_path = root / manifest.MANIFEST_RELPATH
    try:
        original = manifest_path.read_bytes().decode("utf-8")
        manifest.with_wheels(original, filenames, manifest.MANIFEST_RELPATH)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}. No se ha cambiado nada.", file=sys.stderr)
        return EXIT_FAILED

    work = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
    try:
        downloads = work / "ruedas"
        staged = work / "site"
        downloads.mkdir()
        staged.mkdir()
        problems: list[str] = []
        for spec in specs:
            try:
                if folder is not None:
                    path = copy_from_folder(spec, folder, downloads)
                else:
                    path = download_from_pypi(spec, downloads, opener)
                verify(spec, path)
                with zipfile.ZipFile(path) as archive:
                    problem = wheels.audit_problem(
                        spec.filename, archive.namelist(), spec.bundled_licenses
                    )
                    if problem is not None:
                        raise FetchError(problem)
                    archive.extractall(staged)
            except FetchError as exc:
                problems.append(str(exc))
            except (zipfile.BadZipFile, OSError, ValueError) as exc:
                problems.append(f"no se pudo extraer la rueda «{spec.filename}»: {exc}")
        if problems:
            for problem in problems:
                print(f"ERROR: {problem}", file=sys.stderr)
            print(
                f"Ruedas: NO VERDE, {_plural(len(problems), 'problema', 'problemas')}; "
                f"no se ha cambiado nada (ni {wheels.WHEELS_DIR_RELPATH}/, ni "
                ".deps/site/, ni el manifiesto)"
            )
            return EXIT_FAILED

        _place_extension_wheels(root, extension, downloads)
        _replace_site(root, staged)
        changed = manifest.rewrite_wheels(manifest_path, filenames)
    finally:
        try:
            _remove(work)
        except OSError as exc:
            print(f"AVISO: no se pudo borrar la carpeta temporal «{work}»: {exc}")

    origin = "PyPI" if folder is None else f"la carpeta «{folder}»"
    if specs:
        print(f"Ruedas fijadas: {len(specs)}, desde {origin}")
    else:
        print("Ruedas fijadas: ninguna")
    extracted = _plural(len(specs), "rueda extraída", "ruedas extraídas")
    print(f"  {wheels.WHEELS_DIR_RELPATH}/: {', '.join(filenames) or 'ninguna'}")
    print(f"  {DEPS_SITE_RELPATH.as_posix()}/: {extracted}")
    print(f"  {'manifiesto actualizado' if changed else 'manifiesto sin cambios'}")
    print("Ruedas: correcto")
    return EXIT_OK


def main(
    argv: Sequence[str] | None = None,
    *,
    root: Path | None = None,
    environ: Mapping[str, str] | None = None,
    opener: Opener | None = None,
) -> int:
    """Descarga las ruedas fijadas y devuelve el código de salida.

    ``root`` (raíz del repositorio), ``environ`` (entorno donde se busca
    ``GEOBLENDER_WHEELHOUSE``) y ``opener`` (``urllib.request.urlopen``) solo los
    cambian las pruebas.
    """
    environ = os.environ if environ is None else environ
    opener = urllib.request.urlopen if opener is None else opener
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
            print(f"ERROR: {exc}", file=sys.stderr)
            return EXIT_USAGE
    root = Path(root)
    try:
        folder = source_folder(options, environ)
    except UsageError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    lic01 = [f for f in wheels.check(root) if f.rule == wheels.RULE_WHEEL]
    if lic01:
        print(format_findings(lic01))
        print(
            f"Ruedas: NO VERDE, {wheels.WHEELS_TOML_RELPATH} no cumple LIC-01; no se ha "
            "cambiado nada"
        )
        return EXIT_FAILED
    try:
        specs = wheels.load(root / wheels.WHEELS_TOML_RELPATH)
    except ValueError as exc:
        print(f"ERROR: {exc}. No se ha cambiado nada.", file=sys.stderr)
        return EXIT_FAILED
    return fetch(root, specs, folder, opener)


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(_stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")
    sys.exit(main())

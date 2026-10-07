# SPDX-License-Identifier: GPL-3.0-or-later
"""Genera y actualiza el lock del motor de cálculo (spec 004, T24; RF-004-21; plan 004
§5.2.5; ADR-0009 y ADR-0017 §4).

La ejecuta una persona, con el Python de Blender, desde la raíz del repositorio::

    & "C:\\Program Files\\Blender Foundation\\Blender 5.2\\5.2\\python\\bin\\python.exe" tools/lock_runtime.py [--desde CARPETA]

El lock (``jobs/runtime_lock.toml`` de la extensión) lo empieza la persona: la cabecera
(``schema``, ``python``, ``platform``) y, por paquete, ``name``, ``version``,
``bundled_licenses`` (la auditoría de ADR-0017 §4, con sus comentarios) y
``required_by``. La orden rellena el resto de cada ``[[package]]``:

1. ``filename``, ``url`` y ``sha256``: de la API JSON de PyPI
   (``https://pypi.org/pypi/<nombre>/<versión>/json``, con ``urllib`` y 60 s), la rueda
   con las etiquetas del lock (``cp313-cp313-win_amd64``, después ``cp313-abi3-win_amd64``
   y ``py3-none-any``), servida desde ``https://files.pythonhosted.org/``.
2. La rueda: con ``--desde`` (por defecto, la carpeta de ``GEOBLENDER_WHEELHOUSE``) se
   copia de ``<carpeta>/<fichero>``; si no, se descarga de esa url. Su sha256 y su tamaño
   (``size``) tienen que ser los que publica PyPI.
3. Auditoría: una rueda con DLL en ``<paquete>.libs/`` y ``bundled_licenses`` vacío no
   está auditada (ADR-0017 §4).
4. ``license``: la ``License-Expression`` de los metadatos de la rueda, literal; si no la
   trae, se conserva la que escribió la persona (con un comentario que diga de dónde la
   dedujo) y, si tampoco hay, es un error.
5. ``installed_size``: los bytes que deja ``pip install --target`` de esa rueda, en una
   carpeta temporal y con el ``pip`` de este intérprete en modo aislado (nunca en su
   ``site-packages``), con las mismas opciones que la instalación del motor (plan 004
   §5.4.7).

Reescribe solo esas seis líneas de cada paquete (el resto del fichero, con sus
comentarios, queda igual), en UTF-8 sin BOM y LF, de forma atómica, y solo si el resultado
lo leen ``jobs.runtime.read_lock`` (el producto, cargado con
``gbtools.package.load_geoblender``) y la regla LIC-01 del lock (``gbtools.runtime_lock``).
Si algo falla, no escribe nada. Imprime el ``lock_id`` (la carpeta del motor).

Códigos de salida: 0 correcto; 1 un paquete que no está en PyPI, una rueda que no es la
publicada, sin auditar o que no se instala, o un lock que no cumple (nada cambia); 2 error
de uso o de entorno (opción desconocida, carpeta de ruedas que no existe, un intérprete que
no es el Python del lock).
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # sin __pycache__ en Z: (plan 001 §5.3)

import email.parser  # noqa: E402
import importlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import stat  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import tomllib  # noqa: E402
import urllib.request  # noqa: E402
import zipfile  # noqa: E402
from collections.abc import Callable, Mapping, Sequence  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402
from types import ModuleType  # noqa: E402
from typing import Any  # noqa: E402

from gbtools import runtime_lock, wheels  # noqa: E402
from gbtools.findings import format_findings  # noqa: E402
from gbtools.package import load_geoblender  # noqa: E402
from gbtools.repo import repo_root  # noqa: E402

PYPI_JSON = "https://pypi.org/pypi/{name}/{version}/json"
TIMEOUT_S = 60.0
PIP_TIMEOUT_S = 600.0
TEMP_PREFIX = "gb-lock-"
OPTION_SOURCE = "--desde"
CHUNK = 1 << 20
MANAGED_KEYS: tuple[str, ...] = (
    "filename",
    "url",
    "sha256",
    "size",
    "installed_size",
    "license",
)
RUNTIME_MODULE = "jobs.runtime"
DROPPED_ENV_PREFIXES: tuple[str, ...] = ("PIP_", "PYTHON")

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2

USAGE = f"""Uso (con el Python de Blender, desde la raíz del repositorio):
  & "<Blender>\\5.2\\python\\bin\\python.exe" tools/lock_runtime.py [--desde CARPETA]

  --desde CARPETA  carpeta con las ruedas del lock (por defecto, la de {wheels.ENV_WHEELHOUSE});
                   sin ninguna de las dos, se descargan de PyPI
  --ayuda, -h      muestra esta ayuda

Códigos: 0 correcto, 1 fallo (no cambia nada), 2 error de uso."""

Opener = Callable[..., Any]
Installer = Callable[[Path, Path], int]
_LINE_KEY = re.compile(r"^\s*([A-Za-z0-9_-]+)\s*=")


class UsageError(Exception):
    """Opciones, carpeta de ruedas o intérprete no válidos: el mensaje dice cuál."""


class LockToolError(Exception):
    """Un paquete no se pudo fijar o el lock no cumple: el mensaje lo nombra."""


@dataclass(frozen=True)
class Options:
    source: str | None = None
    show_help: bool = False


@dataclass(frozen=True)
class PublishedWheel:
    """La rueda elegida en el JSON de PyPI."""

    filename: str
    url: str
    sha256: str
    size: int


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
    Lanza :class:`UsageError` si la carpeta indicada no existe."""
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


def wanted_tags(python: str, platform: str) -> list[tuple[str, str, str]]:
    """Etiquetas ``(python, abi, plataforma)`` aceptadas para el lock, por preferencia."""
    tag = "cp" + python.replace(".", "")
    return [
        (tag, tag, platform),
        (tag, "abi3", platform),
        ("py3", "none", "any"),
        ("py2.py3", "none", "any"),
    ]


def choose_wheel(
    files: object, *, name: str, version: str, python: str, platform: str
) -> PublishedWheel:
    """La rueda de ``name`` ``version`` con las etiquetas del lock entre los ficheros que
    publica PyPI (``urls`` del JSON); :class:`LockToolError` si no hay ninguna."""
    candidates: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in files if isinstance(files, list) else []:
        if not isinstance(item, dict):
            continue
        filename = item.get("filename")
        if not isinstance(filename, str) or not filename.endswith(".whl"):
            continue
        try:
            tags = wheels.parse_filename(filename)
        except ValueError:
            continue
        if wheels.normalize_name(tags.name) != wheels.normalize_name(name):
            continue
        if tags.version != version:
            continue
        candidates.setdefault((tags.python, tags.abi, tags.platform), item)
    for tags in wanted_tags(python, platform):
        item = candidates.get(tags)
        if item is None:
            continue
        digests = item.get("digests")
        sha = str(digests.get("sha256", "") if isinstance(digests, dict) else "").lower()
        url, size = item.get("url"), item.get("size")
        filename = str(item["filename"])
        if len(sha) != 64 or not isinstance(url, str) or not isinstance(size, int):
            raise LockToolError(
                f"PyPI no da la huella, la url o el tamaño de «{filename}»"
            )
        if not url.startswith(runtime_lock.PYPI_FILES_URL) or not url.endswith(
            "/" + filename
        ):
            raise LockToolError(
                f"PyPI sirve «{filename}» desde «{url}», que no es "
                f"{runtime_lock.PYPI_FILES_URL}…/{filename}"
            )
        return PublishedWheel(filename, url, sha, size)
    wanted = ", ".join("-".join(tags) for tags in wanted_tags(python, platform))
    raise LockToolError(
        f"PyPI no publica una rueda de {name} {version} con las etiquetas del lock "
        f"({wanted})"
    )


def pypi_wheel(
    name: str, version: str, *, python: str, platform: str, opener: Opener
) -> PublishedWheel:
    """Lee el JSON de PyPI de ``name`` ``version`` y elige la rueda del lock."""
    url = PYPI_JSON.format(name=name, version=version)
    try:
        with opener(url, timeout=TIMEOUT_S) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise LockToolError(f"no se pudo leer «{url}»: {exc}") from None
    files = data.get("urls") if isinstance(data, dict) else None
    return choose_wheel(
        files, name=name, version=version, python=python, platform=platform
    )


def obtain_wheel(
    published: PublishedWheel, folder: Path | None, dest: Path, opener: Opener
) -> Path:
    """Copia la rueda del almacén o la descarga de PyPI en ``dest`` y comprueba que su
    sha256 y su tamaño son los publicados; :class:`LockToolError` si no."""
    target = dest / published.filename
    try:
        if folder is not None:
            source = folder / published.filename
            if not source.is_file():
                raise LockToolError(
                    f"la rueda «{published.filename}» no está en la carpeta de ruedas "
                    f"«{folder}»: cópiela allí, o ejecute la orden sin carpeta para "
                    "descargarla de PyPI"
                )
            shutil.copyfile(source, target)
        else:
            with opener(published.url, timeout=TIMEOUT_S) as response, target.open(
                "wb"
            ) as out:
                while chunk := response.read(CHUNK):
                    out.write(chunk)
    except OSError as exc:
        raise LockToolError(
            f"no se pudo obtener la rueda «{published.filename}»: {exc}"
        ) from None
    actual = wheels.sha256_file(target)
    if actual != published.sha256:
        raise LockToolError(
            f"la rueda «{published.filename}» tiene el sha256 {actual} y PyPI publica "
            f"{published.sha256}: no es la rueda publicada y no se fija"
        )
    size = target.stat().st_size
    if size != published.size:
        raise LockToolError(
            f"la rueda «{published.filename}» tiene {size} bytes y PyPI publica "
            f"{published.size}"
        )
    return target


def wheel_license(archive: zipfile.ZipFile) -> str | None:
    """La ``License-Expression`` del ``METADATA`` de la rueda, literal, o ``None``."""
    names = [
        name
        for name in archive.namelist()
        if name.count("/") == 1 and name.endswith(".dist-info/METADATA")
    ]
    if len(names) != 1:
        raise LockToolError("la rueda no tiene un único «*.dist-info/METADATA»")
    text = archive.read(names[0]).decode("utf-8", errors="replace")
    message = email.parser.HeaderParser().parsestr(text)
    value = message.get("License-Expression")
    return " ".join(str(value).split()) if value else None


def pip_command(python: Path, wheel: Path, target: Path) -> list[str]:
    """La orden que instala solo ``wheel`` en ``target`` con el ``pip`` de ``python``,
    aislado y sin red, con las opciones de la instalación del motor (plan 004 §5.4.7)."""
    return [
        str(python), "-B", "-I", "-m", "pip", "--isolated", "install",
        "--no-index", "--no-deps", "--only-binary=:all:",
        "--target", str(target), "--no-cache-dir", "--disable-pip-version-check",
        "--no-input", "--progress-bar", "off", str(wheel),
    ]


def _pip_env(environ: Mapping[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in environ.items()
        if not key.upper().startswith(DROPPED_ENV_PREFIXES)
    }


def folder_bytes(folder: Path) -> int:
    """Bytes de todos los ficheros bajo ``folder``."""
    return sum(path.stat().st_size for path in folder.rglob("*") if path.is_file())


def measure_installed_size(wheel: Path, work: Path, *, python: Path) -> int:
    """Instala ``wheel`` en ``work/site`` con :func:`pip_command` y devuelve los bytes
    instalados; :class:`LockToolError` con la salida de ``pip`` si falla."""
    target = work / "site"
    try:
        result = subprocess.run(
            pip_command(python, wheel, target),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_pip_env(os.environ),
            cwd=work,
            timeout=PIP_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise LockToolError(f"no se pudo ejecutar pip para «{wheel.name}»: {exc}") from None
    if result.returncode != 0:
        tail = " | ".join((result.stderr or result.stdout).strip().splitlines()[-3:])
        raise LockToolError(
            f"pip no pudo instalar «{wheel.name}» (código {result.returncode}): {tail}"
        )
    return folder_bytes(target)


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        raise TypeError("un booleano no es un campo que reescriba la herramienta")
    if isinstance(value, int):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def rewrite_lock(text: str, updates: Mapping[int, Mapping[str, object]]) -> str:
    """El texto del lock con las líneas de :data:`MANAGED_KEYS` de cada paquete
    ``updates[índice]`` sustituidas: se quitan las que había y se escriben, en ese orden,
    tras la línea ``version``. El resto del texto no cambia."""
    lines = text.split("\n")
    spans = wheels.table_spans(lines, runtime_lock.TABLE)
    out: list[str] = []
    cursor = 0
    for index, (start, end) in enumerate(spans):
        out.extend(lines[cursor:start])
        cursor = end
        block = lines[start:end]
        values = updates.get(index)
        if values is None:
            out.extend(block)
            continue
        kept = [
            line
            for line in block
            if not ((match := _LINE_KEY.match(line)) and match.group(1) in MANAGED_KEYS)
        ]
        at = next(
            (
                position + 1
                for position, line in enumerate(kept)
                if (match := _LINE_KEY.match(line)) and match.group(1) == "version"
            ),
            None,
        )
        if at is None:
            raise LockToolError(f"el paquete n.º {index + 1} del lock no tiene «version»")
        managed = [f"{key} = {_toml_value(values[key])}" for key in MANAGED_KEYS]
        out.extend(kept[:at] + managed + kept[at:])
    out.extend(lines[cursor:])
    return "\n".join(out)


def _runtime_module() -> ModuleType:
    """``jobs.runtime`` del producto, cargado por ruta (HER-01)."""
    package = load_geoblender(repo_root(Path(__file__)))
    return importlib.import_module(f"{package.__name__}.{RUNTIME_MODULE}")


def _clear_readonly(function: Callable[..., object], path: str, _error: BaseException) -> None:
    os.chmod(path, stat.S_IWRITE)
    function(path)


def resolve_package(
    entry: Mapping[str, Any],
    index: int,
    *,
    python: str,
    platform: str,
    folder: Path | None,
    work: Path,
    opener: Opener,
    installer: Installer,
) -> dict[str, object]:
    """Los campos de :data:`MANAGED_KEYS` del paquete ``entry`` (pasos 1 a 5)."""
    name, version = entry.get("name"), entry.get("version")
    if not isinstance(name, str) or not isinstance(version, str):
        raise LockToolError(f"el paquete n.º {index + 1} del lock necesita «name» y «version»")
    if not wheels.exact_version(version):
        raise LockToolError(f"el paquete «{name}»: «{version}» no es una versión exacta")
    published = pypi_wheel(name, version, python=python, platform=platform, opener=opener)
    downloads = work / f"ruedas-{index}"
    downloads.mkdir()
    wheel = obtain_wheel(published, folder, downloads, opener)
    bundled = entry.get("bundled_licenses")
    if not isinstance(bundled, list):
        raise LockToolError(
            f"el paquete «{name}» necesita «bundled_licenses» (la auditoría de ADR-0017 §4; "
            "[] si la rueda no trae bibliotecas nativas)"
        )
    try:
        with zipfile.ZipFile(wheel) as archive:
            problem = wheels.audit_problem(published.filename, archive.namelist(), bundled)
            if problem is not None:
                raise LockToolError(problem)
            expression = wheel_license(archive)
    except zipfile.BadZipFile as exc:
        raise LockToolError(f"la rueda «{published.filename}» no es un zip: {exc}") from None
    if expression is None:
        current = entry.get("license")
        if not isinstance(current, str) or not current.strip():
            raise LockToolError(
                f"la rueda «{published.filename}» no declara «License-Expression»: escriba "
                "«license» en el lock, deducida de sus License-File, con un comentario "
                "(ADR-0017 §4)"
            )
        expression = current
    site_work = work / f"instalacion-{index}"
    site_work.mkdir()
    installed = installer(wheel, site_work)
    return {
        "filename": published.filename,
        "url": published.url,
        "sha256": published.sha256,
        "size": published.size,
        "installed_size": installed,
        "license": expression,
    }


def _check_result(
    text: str, new_text: str, updates: Mapping[int, Mapping[str, object]]
) -> None:
    """Comprueba el lock reescrito; :class:`LockToolError` si no cumple."""
    try:
        before = tomllib.loads(text)
        after = tomllib.loads(new_text)
    except tomllib.TOMLDecodeError as exc:
        raise LockToolError(f"el lock reescrito no es TOML válido: {exc}") from None
    old_packages, new_packages = before.get("package", []), after.get("package", [])
    if len(old_packages) != len(new_packages):
        raise LockToolError("el lock reescrito no tiene los mismos paquetes")
    for index, (old, new) in enumerate(zip(old_packages, new_packages)):
        expected = {key: value for key, value in old.items() if key not in MANAGED_KEYS}
        expected.update(updates.get(index, {}))
        if new != expected:
            raise LockToolError(
                f"el paquete n.º {index + 1} no se pudo reescribir sin tocar el resto: "
                "deje cada clave en su línea, «clave = valor»"
            )
    findings = runtime_lock.check_text(new_text)
    if findings:
        raise LockToolError(
            "el lock resultante no cumple LIC-01 y no se escribe:\n"
            + format_findings(findings)
        )


def write_atomically(path: Path, text: str) -> None:
    """Escribe ``text`` en ``path`` (UTF-8 sin BOM, LF) a través de ``<path>.partial``."""
    partial = path.with_name(path.name + ".partial")
    try:
        partial.write_bytes(text.encode("utf-8"))
        os.replace(partial, path)
    finally:
        if partial.exists():
            partial.unlink()


def run(
    root: Path, folder: Path | None, opener: Opener, installer: Installer
) -> int:
    """Pasos 1 a 5 y la escritura; devuelve el código de salida."""
    lock_path = root / runtime_lock.LOCK_RELPATH
    try:
        text = lock_path.read_bytes().decode("utf-8")
        data = tomllib.loads(text)
    except FileNotFoundError:
        print(
            f"ERROR: no existe «{runtime_lock.LOCK_RELPATH}»: escriba la cabecera y, por "
            "paquete, name, version, bundled_licenses y required_by (plan 004 §5.2.5)",
            file=sys.stderr,
        )
        return EXIT_FAILED
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        print(f"ERROR: no se puede leer «{runtime_lock.LOCK_RELPATH}»: {exc}", file=sys.stderr)
        return EXIT_FAILED
    header = [message for _key, message in runtime_lock.header_problems(data)]
    if header:
        for message in header:
            print(f"ERROR: {runtime_lock.LOCK_RELPATH}: {message}", file=sys.stderr)
        return EXIT_FAILED
    python, platform = str(data["python"]), str(data["platform"])
    running = f"{sys.version_info.major}.{sys.version_info.minor}"
    if running != python:
        print(
            f"Error: este intérprete es Python {running} y el lock es para Python "
            f"{python}: ejecute la orden con el Python de Blender",
            file=sys.stderr,
        )
        return EXIT_USAGE

    entries = data[runtime_lock.TABLE]
    work = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
    try:
        updates: dict[int, dict[str, object]] = {}
        problems: list[str] = []
        for index, entry in enumerate(entries):
            try:
                updates[index] = resolve_package(
                    entry, index, python=python, platform=platform, folder=folder,
                    work=work, opener=opener, installer=installer,
                )
            except LockToolError as exc:
                problems.append(str(exc))
        lock_id = ""
        new_text = text
        if not problems:
            try:
                new_text = rewrite_lock(text, updates)
                _check_result(text, new_text, updates)
                runtime = _runtime_module()
                lock_id = runtime.parse_lock(tomllib.loads(new_text)).lock_id
            except LockToolError as exc:
                problems.append(str(exc))
            except ValueError as exc:  # LockError del producto
                problems.append(f"el producto no lee el lock resultante: {exc}")
        if problems:
            for problem in problems:
                print(f"ERROR: {problem}", file=sys.stderr)
            print(
                f"Lock: NO VERDE, {len(problems)} "
                f"{'problema' if len(problems) == 1 else 'problemas'}; no se ha cambiado "
                f"{runtime_lock.LOCK_RELPATH}"
            )
            return EXIT_FAILED
        changed = new_text != text
        if changed:
            write_atomically(lock_path, new_text)
    finally:
        shutil.rmtree(work, onexc=_clear_readonly)

    origin = "PyPI" if folder is None else f"la carpeta «{folder}»"
    print(f"Paquetes del lock: {len(entries)}, ruedas desde {origin}")
    for index, entry in enumerate(entries):
        values = updates[index]
        print(
            f"  {entry['name']} {entry['version']}: {values['filename']}, "
            f"{_mb(values['size'])} MB de descarga, {_mb(values['installed_size'])} MB "
            f"instalado, sha256 {values['sha256']}"
        )
    print(f"  lock_id: {lock_id}")
    print(f"  {'lock actualizado' if changed else 'lock sin cambios'}")
    print("Lock: correcto")
    return EXIT_OK


def _mb(value: object) -> str:
    return f"{int(str(value)) / 1_000_000:.1f}".replace(".", ",")


def main(
    argv: Sequence[str] | None = None,
    *,
    root: Path | None = None,
    environ: Mapping[str, str] | None = None,
    opener: Opener | None = None,
    installer: Installer | None = None,
) -> int:
    """Actualiza el lock y devuelve el código de salida.

    ``root`` (raíz del repositorio con el lock), ``environ`` (donde se busca
    ``GEOBLENDER_WHEELHOUSE``), ``opener`` (``urllib.request.urlopen``) e ``installer``
    (mide el tamaño instalado: :func:`measure_installed_size` con este intérprete) solo
    los cambian las pruebas.
    """
    environ = os.environ if environ is None else environ
    if opener is None:
        opener = urllib.request.urlopen
    if installer is None:

        def installer(wheel: Path, work: Path) -> int:
            return measure_installed_size(wheel, work, python=Path(sys.executable))

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
    try:
        folder = source_folder(options, environ)
    except UsageError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    return run(Path(root), folder, opener, installer)


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(_stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")
    sys.exit(main())

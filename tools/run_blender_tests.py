# SPDX-License-Identifier: GPL-3.0-or-later
"""Lanzador de las pruebas que necesitan ``bpy`` (plan 001 §5.4.8; RF-001-04 a 06, 09).

Se ejecuta **dentro de Blender**, en segundo plano, con la configuración de fábrica, un
perfil temporal y ``--python-exit-code 1`` (sin esa opción una excepción sale con 0)::

    $env:BLENDER_USER_RESOURCES = (New-Item -ItemType Directory -Force "$env:TEMP\\gb-perfil").FullName
    & $B -b --factory-startup --python-exit-code 1 --python tools/run_blender_tests.py -- [opciones]

Opciones (tras ``--``):

- ``--carpeta DIR``: carpeta de pruebas (por defecto ``tests/blender``); una ruta
  relativa se toma desde la raíz del repositorio.
- ``--patron PATRÓN``: patrón de los ficheros (por defecto ``test_*.py``; las
  mediciones de ``tests/rendimiento/blender`` usan ``perf_*.py``).

Pasos: copia ``geoblender/`` con las exclusiones del manifiesto a
``%TEMP%\\geoblender-pruebas-*\\geoblender``, la registra como repositorio de extensiones
``gb_tests`` (sin habilitarla: lo hacen las pruebas, con ``tests.support.blender_ext``),
descubre y ejecuta las pruebas con ``unittest`` y, pase lo que pase, deshabilita la
extensión, retira el repositorio y borra la carpeta temporal. No escribe en el
repositorio ni en el perfil de Blender del usuario. Justo después de registrar el
repositorio de pruebas, y antes de cualquier prueba, toma la huella del estado de Blender
(``tests.support.blender_ext.SESSION_BASELINE``, la referencia de las pruebas de
registro); al terminar, con la extensión deshabilitada y descargada, la toma otra vez y,
si difiere, falla con «HUELLA:» y las diferencias (RF-001-05; convergencia de la spec
001, T36). Antes de esa huella, envuelve ``bpy.app.timers.register`` para anotar los
temporizadores que se registran durante la sesión y deja la lista de módulos de la copia,
cuyas traducciones registradas busca la huella: un temporizador o unas traducciones que
la extensión no quita al deshabilitarse también son «HUELLA:» (T50). Envuelve igual las
funciones de registro de los manejadores de dibujo (``draw_handler_add`` de los editores
y ``draw_cursor_add``), de las colecciones de previews y de las suscripciones de msgbus,
y la huella vuelca además las preferencias, los complementos y ``driver_namespace``
(``tests.support.blender_ext.track_registrations``; T62). Un fichero de pruebas de la
carpeta
que ``unittest discover`` no cargó (p. ej. en una subcarpeta sin ``__init__.py``) es un
fallo: «PRUEBAS SIN CARGAR» con su ruta (convergencia de la spec 001, T35). La última
línea, al terminar, es ``FIN DEL LANZADOR: <n> pruebas, código <c>``
(``gbtools.discovery.launcher_end_line``): ``check.py`` la exige cuando Blender sale
con 0, porque un ``os._exit(0)`` a mitad de una prueba saldría con 0 sin ella (T37).
Una prueba roja marcada con ``expectedFailure``, que ``unittest`` da por buena («OK
(expected failures=n)»), es un fallo: «FALLOS ESPERADOS» con la prueba (T59).

Códigos de salida: 0 todas pasan; 1 alguna falla, es un fallo esperado o no se cargó, no
hay pruebas o no se pudo limpiar;
2 no se ejecuta dentro de Blender, la versión es anterior a la mínima del manifiesto o
las opciones no son válidas.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # sin __pycache__ en Z: (plan 001 §2.1, 8)

import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import unittest  # noqa: E402
import warnings  # noqa: E402
from collections.abc import Sequence  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402

TOOLS_DIR = Path(__file__).resolve().parent
ROOT = TOOLS_DIR.parent

DEFAULT_FOLDER = "tests/blender"
DEFAULT_PATTERN = "test_*.py"
EXTENSION_ID = "geoblender"
REPO_NAME = "Geoblender (pruebas)"
REPO_MODULE = "gb_tests"
TEMP_PREFIX = "geoblender-pruebas-"
ENV_USER_RESOURCES = "BLENDER_USER_RESOURCES"

COMMAND = (
    "& $B -b --factory-startup --python-exit-code 1 --python tools/run_blender_tests.py "
    "-- [--carpeta DIR] [--patron PATRÓN]"
)
USAGE = f"""Uso (dentro de Blender, desde la raíz del repositorio):
  {COMMAND}

  --carpeta DIR      carpeta de pruebas (por defecto {DEFAULT_FOLDER}; relativa a la raíz)
  --patron PATRÓN    patrón de los ficheros de prueba (por defecto {DEFAULT_PATTERN})
  --ayuda, -h        muestra esta ayuda"""


class UsageError(Exception):
    """Opciones no válidas: el mensaje dice cuál y por qué."""


@dataclass(frozen=True)
class Options:
    folder: Path
    pattern: str
    show_help: bool = False


def _script_args(argv: Sequence[str]) -> list[str]:
    """Argumentos del guion: lo que sigue al primer ``--`` de la línea de Blender."""
    args = list(argv)
    return args[args.index("--") + 1 :] if "--" in args else []


def parse_args(args: Sequence[str]) -> Options:
    """Lee ``--carpeta`` y ``--patron``; lanza :class:`UsageError` si algo sobra o falta."""
    values = {"--carpeta": DEFAULT_FOLDER, "--patron": DEFAULT_PATTERN}
    show_help = False
    pending = list(args)
    while pending:
        arg = pending.pop(0)
        if arg in ("--ayuda", "-h", "--help"):
            show_help = True
            continue
        name, equals, value = arg.partition("=")
        if name not in values:
            raise UsageError(f"opción desconocida «{arg}»")
        if not equals:
            if not pending or pending[0].startswith("--"):
                raise UsageError(f"falta el valor de «{name}»")
            value = pending.pop(0)
        if not value:
            raise UsageError(f"«{name}» no puede estar vacío")
        values[name] = value
    folder = Path(values["--carpeta"])
    if not folder.is_absolute():
        folder = ROOT / folder
    return Options(folder=folder, pattern=values["--patron"], show_help=show_help)


def _inside(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
    except ValueError:
        return False
    return True


def _version(version: Sequence[int]) -> str:
    return ".".join(str(part) for part in version)


def _remove_tree(folder: Path, attempts: int = 5) -> None:
    """Borra ``folder`` con algunos reintentos (Windows puede retener un fichero)."""
    for attempt in range(attempts):
        try:
            shutil.rmtree(folder)
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.2 * (attempt + 1))


def _install_copy(manifest_data: dict[str, object], temp: Path) -> object:
    """Copia la extensión a ``temp`` y la registra como repositorio ``gb_tests``."""
    import bpy
    from gbtools import layout, manifest, sync

    sync.mirror(
        ROOT / layout.EXTENSION_DIR,
        temp / EXTENSION_ID,
        manifest.exclude_patterns(manifest_data),
    )
    repos = bpy.context.preferences.extensions.repos
    for stale in [repo for repo in repos if repo.module == REPO_MODULE]:
        repos.remove(stale)
    return repos.new(
        name=REPO_NAME,
        module=REPO_MODULE,
        custom_directory=str(temp),
        source="USER",
    )


def _suite_modules(suite: unittest.TestSuite) -> set[str]:
    """Módulos de las pruebas de ``suite``; de un módulo que no se pudo importar
    (``unittest.loader._FailedTest``), su nombre: sus pruebas fallarán al ejecutarse."""
    names: set[str] = set()
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            names |= _suite_modules(item)
        elif type(item).__module__ == unittest.loader.__name__:
            names.add(str(getattr(item, "_testMethodName", "")))
        else:
            names.add(type(item).__module__)
    return names


def _report_unloaded(options: Options, missing: Sequence[str]) -> None:
    from gbtools import discovery

    listed = "\n".join(f"  {rel}" for rel in missing)
    print(
        f"PRUEBAS SIN CARGAR ({len(missing)}) en «{options.folder}» con el patrón "
        f"«{options.pattern}»: unittest discover no importó estos ficheros y sus pruebas "
        f"no se ejecutaron; {discovery.HINT} (RF-001-06)\n{listed}",
        file=sys.stderr,
        flush=True,
    )


def _report_expected_failures(failures: Sequence[tuple[unittest.TestCase, str]]) -> None:
    from gbtools import discovery

    listed = "\n".join(f"  {test.id()}" for test, _trace in failures)
    print(
        f"FALLOS ESPERADOS ({len(failures)}): «OK (expected failures={len(failures)})» no "
        f"es verde: {discovery.EXPECTED_FAILURES_HINT}\n{listed}",
        file=sys.stderr,
        flush=True,
    )


def _run_tests(options: Options) -> tuple[int, int]:
    """Descubre y ejecuta las pruebas; devuelve el código y cuántas se ejecutaron."""
    from gbtools import discovery

    top_level = ROOT if _inside(options.folder, ROOT) else options.folder
    expected = discovery.expected_modules(options.folder, options.pattern, top_level)
    suite = unittest.defaultTestLoader.discover(
        str(options.folder), pattern=options.pattern, top_level_dir=str(top_level)
    )
    missing = discovery.missing_modules(expected, _suite_modules(suite))
    count = suite.countTestCases()
    if count == 0:
        if missing:
            _report_unloaded(options, missing)
            return 1, 0
        print(
            f"NO HAY PRUEBAS en «{options.folder}» con el patrón «{options.pattern}»: "
            "un arnés sin pruebas no demuestra nada (RF-001-07)",
            file=sys.stderr,
        )
        return 1, 0
    # Una prueba que devuelve algo (async def en un TestCase, o con yield) no ejecuta su
    # cuerpo: error, no solo un aviso (convergencia de la spec 001, T54).
    warnings.filterwarnings(
        "error",
        message=re.escape(discovery.RETURN_VALUE_WARNING),
        category=DeprecationWarning,
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    code = 0 if result.wasSuccessful() else 1
    # unittest da por buena una prueba roja marcada con expectedFailure (T59).
    if result.expectedFailures:
        _report_expected_failures(result.expectedFailures)
        code = 1
    if missing:
        _report_unloaded(options, missing)
        return 1, result.testsRun
    return code, result.testsRun


def _disable_and_unload(module: str) -> list[str]:
    """Deshabilita la extensión si quedó habilitada y la quita de ``sys.modules``;
    devuelve los problemas (en español)."""
    import addon_utils

    problems: list[str] = []
    try:
        if getattr(sys.modules.get(module), "__addon_enabled__", False) is True:
            errors: list[BaseException] = []
            addon_utils.disable(module, default_set=True, handle_error=errors.append)
            problems.extend(f"error al deshabilitar «{module}»: {exc!r}" for exc in errors)
    except Exception as exc:  # noqa: BLE001 - se informa y se sigue limpiando
        problems.append(f"no se pudo deshabilitar «{module}»: {exc!r}")
    for key in [k for k in sys.modules if k == module or k.startswith(module + ".")]:
        del sys.modules[key]
    return problems


def _fingerprint_changes(baseline: dict[str, object] | None) -> list[str]:
    """Diferencias entre la huella del principio de la sesión y la de ahora, con la
    extensión ya deshabilitada y descargada (RF-001-05): una fuga que se repite igual en
    cada habilitación no la ve una prueba que compara con una huella tomada a mitad de
    sesión, pero sí esta comparación."""
    if baseline is None:
        return []
    from tests.support import blender_ext

    try:
        changes = blender_ext.fingerprint_diff(baseline, blender_ext.state_fingerprint())
    except Exception as exc:  # noqa: BLE001 - sin huella no hay verde
        return [f"no se pudo tomar la huella del estado de Blender al terminar: {exc!r}"]
    if not changes:
        return []
    return [
        "al terminar, con la extensión deshabilitada y descargada, la huella del estado "
        "de Blender no es la del principio de la sesión: la extensión (o una prueba) "
        "dejó rastro (RF-001-05)",
        *changes,
    ]


def _remove_repo(repo: object | None, temp: Path) -> list[str]:
    """Retira el repositorio de pruebas y borra ``temp``; devuelve los problemas."""
    import bpy

    problems: list[str] = []
    repos = bpy.context.preferences.extensions.repos
    try:
        if repo is not None:
            repos.remove(repo)
    except Exception as exc:  # noqa: BLE001
        problems.append(f"no se pudo retirar el repositorio «{REPO_MODULE}»: {exc!r}")
    if any(item.module == REPO_MODULE for item in repos):
        problems.append(f"el repositorio de pruebas «{REPO_MODULE}» sigue registrado")
    try:
        _remove_tree(temp)
    except OSError as exc:
        problems.append(f"no se pudo borrar la carpeta temporal «{temp}»: {exc}")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    """Ejecuta las pruebas de Blender; devuelve el código de salida."""
    try:
        import bpy
    except ImportError:
        print(f"run_blender_tests.py se ejecuta dentro de Blender: {COMMAND}", file=sys.stderr)
        return 2
    try:
        options = parse_args(_script_args(sys.argv if argv is None else argv))
    except UsageError as exc:
        print(f"Error: {exc}\n\n{USAGE}", file=sys.stderr)
        return 2
    if options.show_help:
        print(USAGE)
        return 0
    for entry in (str(TOOLS_DIR), str(ROOT)):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    if not os.environ.get(ENV_USER_RESOURCES):
        print(
            f"AVISO: {ENV_USER_RESOURCES} no está definida: Blender puede escribir en el "
            "perfil real del usuario; use un perfil temporal (órdenes en AGENTS.md)",
            file=sys.stderr,
        )

    import tomllib

    from gbtools import manifest

    # Con BOM se lee igual, como en tools/check.py: el BOM lo señalan TXT-01, MAN-01 y el
    # paso «manifiesto», y las pruebas de Blender se ejecutan (convergencia, T56).
    text = (ROOT / manifest.MANIFEST_RELPATH).read_bytes().decode("utf-8-sig")
    manifest_data = tomllib.loads(text)
    minimum = manifest.blender_min(manifest_data)
    version = tuple(bpy.app.version)
    if version < minimum:
        print(
            f"Blender {_version(version)} es anterior a la versión mínima "
            f"{_version(minimum)} del manifiesto: use Blender {_version(minimum)} o "
            "posterior (GEOBLENDER_BLENDER)",
            file=sys.stderr,
        )
        return 2
    if not options.folder.is_dir():
        print(f"Error: no existe la carpeta de pruebas «{options.folder}»", file=sys.stderr)
        return 2

    from gbtools import discovery
    from tests.support import blender_ext

    module = f"bl_ext.{REPO_MODULE}.{EXTENSION_ID}"
    temp = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
    repo: object | None = None
    baseline: dict[str, object] | None = None
    code, count = 1, 0
    try:
        repo = _install_copy(manifest_data, temp)
        os.environ[blender_ext.ENV_MODULE] = module
        # Lo que no se puede enumerar (temporizadores, manejadores de dibujo, previews,
        # suscripciones de msgbus) se anota desde ahora, y se buscan las traducciones de
        # los módulos de la copia (RF-001-05; convergencia de la spec 001, T50 y T62).
        blender_ext.EXTENSION_MODULES = blender_ext.extension_modules(
            temp / EXTENSION_ID, module
        )
        blender_ext.track_registrations()
        # Huella de referencia de toda la sesión: antes de cualquier prueba (RF-001-05).
        baseline = blender_ext.state_fingerprint()
        blender_ext.SESSION_BASELINE = baseline
        print(f"Extensión de pruebas: {module} (copia en «{temp}»)", flush=True)
        code, count = _run_tests(options)
    finally:
        problems = _disable_and_unload(module)
        changes = _fingerprint_changes(baseline)
        blender_ext.untrack_registrations()
        blender_ext.EXTENSION_MODULES = ()
        problems += _remove_repo(repo, temp)
        blender_ext.SESSION_BASELINE = None
        os.environ.pop(blender_ext.ENV_MODULE, None)
        for change in changes:
            print(f"HUELLA: {change}", file=sys.stderr)
        for problem in problems:
            print(f"LIMPIEZA: {problem}", file=sys.stderr)
    final = 1 if problems or changes else code
    # Última línea: check.py la exige si Blender sale con 0 (un os._exit(0) a mitad de
    # una prueba no la escribe).
    print(discovery.launcher_end_line(count, final), file=sys.stderr, flush=True)
    return final


if __name__ == "__main__":
    sys.exit(main())

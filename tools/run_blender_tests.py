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
- ``--parte i/n``: de las pruebas que descubre, ejecuta solo la parte i de n
  (``gbtools.parts``: módulos enteros, repartidos por tiempo o por número de pruebas) y
  antes escribe ``PARTE i de n: r de T pruebas``; ``tools/check.py`` reparte así las de
  ``tests/blender`` en varios Blender a la vez, cada uno con su perfil temporal (spec
  003, T40). Las comprobaciones de lo descubierto («NO HAY PRUEBAS», «PRUEBAS SIN
  CARGAR») son sobre todas las pruebas.
- ``--tiempos F``: con ``--parte``, reparte por la duración de cada módulo del fichero F
  (sin él, o sin medidas, por número de pruebas); ``--medidas F``: al terminar, escribe en
  F la duración de cada módulo que ejecutó (spec 004, T39; ``gbtools.parts``). Una ruta
  relativa se toma desde la raíz del repositorio.
- ``--copia DIR``: usa la copia de la extensión ya preparada en DIR (``DIR/geoblender``,
  con su código compilado en ``DIR/pyc``; ``gbtools.ext_copy.prepare``) en vez de hacer la
  suya, y no la borra al terminar: ``tools/check.py`` la prepara una vez, mientras corren
  las unitarias, para todas las partes de «blender» (spec 006, T48; RNF-001-01). Una ruta
  relativa se toma desde la raíz del repositorio.
- ``--cola DIR``: con ``--parte`` y ``--tiempos``, las partes se reparten los módulos según
  acaban (spec 006, T59; ``gbtools.parts.Queue``): cada una empieza por uno de los que más
  tardan y, al acabar uno, toma el siguiente que ninguna ha tomado de la cola que comparten
  en DIR (de más a menos tiempo, y los de ``RUN_LAST`` al final); escribe su línea «PARTE i
  de n: r de T pruebas» al terminar. Una ruta relativa se toma desde la raíz.

Pasos: copia ``geoblender/`` con las exclusiones del manifiesto a
``%TEMP%\\geoblender-pruebas-*\\geoblender``, sin ``wheels/`` y con ``wheels = []`` en
el manifiesto de la copia (``gbtools.ext_copy.make_copy``; con ruedas, Blender instala y
quita pyproj, spec 006, en cada habilitar y deshabilitar: unos 0,17 s por vez y 9 s en el
paso «blender» de ``check.py``, RNF-001-01; ninguna prueba de Blender las usa), o toma la
de ``--copia``; la registra como repositorio de extensiones ``gb_tests`` (sin habilitarla:
lo hacen las pruebas, con ``tests.support.blender_ext``), descubre y ejecuta las pruebas
con ``unittest`` y, pase lo que pase, deshabilita la extensión, retira el repositorio y
borra la carpeta temporal (la de ``--copia``, no). Los módulos de prueba con
``RUN_LAST = True`` se ejecutan los últimos (``gbtools.parts.last_at_the_end``; spec 006,
T59): el que inicia la GPU deja el proceso más lento para los que vienen detrás. No
escribe en el repositorio ni en el perfil de Blender del usuario. El código compilado de
lo que se importa durante las pruebas se guarda en ``pyc/`` de la carpeta temporal (o de
la copia de ``--copia``), y solo
desde que se han descubierto las pruebas: lo que importan los módulos de prueba al
descubrirlos (numpy, la biblioteca estándar) se lee del código compilado de la instalación
de Blender en vez de compilarse otra vez (spec 006, T48). Justo después de registrar el
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
from collections.abc import Callable, Sequence  # noqa: E402
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
BYTECODE_DIR = "pyc"  # código compilado de la sesión: gbtools.ext_copy.BYTECODE_FOLDER
ENV_USER_RESOURCES = "BLENDER_USER_RESOURCES"

PART_OPTION = "--parte"  # gbtools.parts.OPTION (lo comprueba una prueba)
TIMES_OPTION = "--tiempos"  # gbtools.parts.TIMES_OPTION (spec 004, T39)
MEASURES_OPTION = "--medidas"  # gbtools.parts.MEASURES_OPTION (spec 004, T39)
COPY_OPTION = "--copia"  # la copia compartida que prepara tools/check.py (spec 006, T48)
QUEUE_OPTION = "--cola"  # gbtools.parts.QUEUE_OPTION: la cola de las partes (spec 006, T59)

COMMAND = (
    "& $B -b --factory-startup --python-exit-code 1 --python tools/run_blender_tests.py "
    "-- [--carpeta DIR] [--patron PATRÓN] [--parte i/n] [--tiempos F] [--medidas F] "
    "[--copia DIR] [--cola DIR]"
)
USAGE = f"""Uso (dentro de Blender, desde la raíz del repositorio):
  {COMMAND}

  --carpeta DIR      carpeta de pruebas (por defecto {DEFAULT_FOLDER}; relativa a la raíz)
  --patron PATRÓN    patrón de los ficheros de prueba (por defecto {DEFAULT_PATTERN})
  --parte i/n        solo la parte i de n de las pruebas (módulos enteros)
  --tiempos F        con --parte, reparte por la duración de cada módulo del fichero F
  --medidas F        al terminar, escribe en F la duración de cada módulo ejecutado
  --copia DIR        usa la copia de la extensión preparada en DIR y no la borra
  --cola DIR         con --parte y --tiempos, toma los módulos de la cola que comparten
                     las partes en DIR según acaba (al terminar escribe su línea)
  --ayuda, -h        muestra esta ayuda"""


class UsageError(Exception):
    """Opciones no válidas: el mensaje dice cuál y por qué."""


@dataclass(frozen=True)
class Options:
    folder: Path
    pattern: str
    show_help: bool = False
    part: tuple[int, int] | None = None  # (i, n) de --parte; None: todas
    times: Path | None = None  # --tiempos: la duración de cada módulo (spec 004, T39)
    measures: Path | None = None  # --medidas: donde se escribe la de los ejecutados
    copy: Path | None = None  # --copia: la copia compartida (spec 006, T48)
    queue: Path | None = None  # --cola: la cola que comparten las partes (spec 006, T59)


def _script_args(argv: Sequence[str]) -> list[str]:
    """Argumentos del guion: lo que sigue al primer ``--`` de la línea de Blender."""
    args = list(argv)
    return args[args.index("--") + 1 :] if "--" in args else []


def parse_args(args: Sequence[str]) -> Options:
    """Lee ``--carpeta``, ``--patron``, ``--parte``, ``--tiempos``, ``--medidas``,
    ``--copia`` y ``--cola``; lanza :class:`UsageError` si algo sobra, falta o no vale."""
    values = {
        "--carpeta": DEFAULT_FOLDER,
        "--patron": DEFAULT_PATTERN,
        PART_OPTION: "",
        TIMES_OPTION: "",
        MEASURES_OPTION: "",
        COPY_OPTION: "",
        QUEUE_OPTION: "",
    }
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
    part: tuple[int, int] | None = None
    if values[PART_OPTION]:
        _tools_on_path()
        from gbtools import parts

        try:
            part = parts.parse(values[PART_OPTION])
        except ValueError as exc:
            raise UsageError(str(exc)) from None
    return Options(
        folder=folder,
        pattern=values["--patron"],
        show_help=show_help,
        part=part,
        times=_file_option(values[TIMES_OPTION]),
        measures=_file_option(values[MEASURES_OPTION]),
        copy=_file_option(values[COPY_OPTION]),
        queue=_file_option(values[QUEUE_OPTION]),
    )


def _file_option(value: str) -> Path | None:
    """El fichero de una opción (``None`` si no se dio); una ruta relativa, desde la
    raíz del repositorio."""
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _tools_on_path() -> None:
    """``tools/`` y la raíz en ``sys.path``, para importar ``gbtools`` y ``tests``."""
    for entry in (str(TOOLS_DIR), str(ROOT)):
        if entry not in sys.path:
            sys.path.insert(0, entry)


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


def _install_copy(
    manifest_data: dict[str, object], temp: Path, *, copy: bool = True
) -> object:
    """Copia la extensión a ``temp`` (``gbtools.ext_copy.make_copy``; con ``copy`` falso,
    la de ``--copia``, ya hecha) y la registra como repositorio ``gb_tests``."""
    import bpy
    from gbtools import ext_copy

    if copy:
        ext_copy.make_copy(ROOT, temp, manifest_data)
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


def _run_tests(
    options: Options, on_discovered: Callable[[], None] | None = None
) -> tuple[int, int]:
    """Descubre y ejecuta las pruebas; devuelve el código y cuántas se ejecutaron. Llama a
    ``on_discovered`` (si se da) tras descubrirlas y antes de ejecutarlas."""
    from gbtools import discovery

    top_level = ROOT if _inside(options.folder, ROOT) else options.folder
    expected = discovery.expected_modules(options.folder, options.pattern, top_level)
    suite = unittest.defaultTestLoader.discover(
        str(options.folder), pattern=options.pattern, top_level_dir=str(top_level)
    )
    if on_discovered is not None:
        on_discovered()
    missing = discovery.missing_modules(expected, _suite_modules(suite))
    count = suite.countTestCases()
    queued = _queued(suite, options, count) if count != 0 else None
    if queued is not None:
        suite = queued
    elif count != 0:
        from gbtools import parts

        if options.part is not None:
            times = parts.read_times(options.times) if options.times is not None else None
            suite, _total = parts.select(suite, *options.part, times)
            print(
                parts.line(*options.part, suite.countTestCases(), count),
                file=sys.stderr,
                flush=True,
            )
        # Lo que deja el proceso más lento para los que vienen detrás, al final (T59).
        suite = parts.last_at_the_end(suite)
        if options.measures is not None:
            part, total_parts = options.part if options.part is not None else (1, 1)
            suite = parts.measured(suite, part, total_parts, options.measures)
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


def _queued(
    suite: unittest.TestSuite, options: Options, count: int
) -> unittest.TestSuite | None:
    """La suite de la parte con la cola de ``--cola`` (spec 006, T59; ``gbtools.parts``):
    los módulos descubiertos, en el orden de la cola por sus tiempos (los que piden ir los
    últimos, ``RUN_LAST``, al final), que las partes se reparten según acaban; los grupos
    sin pruebas, en la parte 1. Al terminar escribe su línea «PARTE i de n: r de T
    pruebas» y, con ``--medidas``, la duración de cada módulo. ``None`` sin ``--parte``,
    sin ``--cola`` o sin tiempos medidos: el reparto de siempre."""
    if options.part is None or options.queue is None or options.times is None:
        return None
    from gbtools import parts

    groups = list(suite)
    sizes = [group.countTestCases() for group in groups]
    names = [parts.module_of(group) for group in groups]
    weights = parts.weights(sizes, names, parts.read_times(options.times))
    if weights is None:
        return None
    units = parts.queue_order(
        weights,
        [parts.affinity_of(name) for name in names],
        [parts.runs_last(name) for name in names],
    )
    part, total_parts = options.part
    queue = parts.Queue(options.queue, len(units), part, total_parts)
    record: dict[str, float] = {}

    def done() -> None:
        ran = sum(sizes[index] for unit in queue.taken for index in units[unit])
        print(parts.line(part, total_parts, ran, count), file=sys.stderr, flush=True)
        if options.measures is not None:
            parts.write_measures(options.measures, record, part, total_parts)

    first = [group for group, size in zip(groups, sizes) if size == 0] if part == 1 else []
    return parts.QueuedSuite(
        queue,
        lambda unit: [groups[index] for index in units[unit]],
        done,
        first=first,
        record=record if options.measures is not None else None,
    )


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


def _remove_repo(repo: object | None, temp: Path | None) -> list[str]:
    """Retira el repositorio de pruebas y borra ``temp`` (``None``: nada que borrar, la
    copia de ``--copia``); devuelve los problemas."""
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
    if temp is None:
        return problems
    try:
        _remove_tree(temp)
    except OSError as exc:
        problems.append(f"no se pudo borrar la carpeta temporal «{temp}»: {exc}")
    return problems


def _cache_bytecode(temp: Path) -> None:
    """Guarda el código compilado de lo que se importa durante las pruebas en la carpeta
    temporal (``sys.pycache_prefix``), nunca junto a las fuentes: las pruebas que
    descargan y vuelven a habilitar la extensión no la recompilan cada vez (spec 003,
    T11), y no aparece ningún ``__pycache__`` en el repositorio. Se llama tras descubrir
    las pruebas (spec 006, T48): con el prefijo, Python busca ahí también el código
    compilado de la biblioteca estándar y de numpy, y lo compilaría otra vez (≈ 0,4 s por
    parte) en vez de leer el de la instalación de Blender."""
    sys.pycache_prefix = str(temp / BYTECODE_DIR)
    sys.dont_write_bytecode = False


def _stop_caching_bytecode() -> None:
    """Deshace :func:`_cache_bytecode`: sin código compilado, como al empezar."""
    sys.dont_write_bytecode = True
    sys.pycache_prefix = None


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
    _tools_on_path()
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
    if options.copy is not None and not (options.copy / manifest.MANIFEST_RELPATH).is_file():
        print(
            f"Error: «{options.copy}» no tiene la copia de la extensión de {COPY_OPTION} "
            f"(falta «{manifest.MANIFEST_RELPATH}»)",
            file=sys.stderr,
        )
        return 2

    from gbtools import discovery
    from tests.support import blender_ext

    module = f"bl_ext.{REPO_MODULE}.{EXTENSION_ID}"
    shared = options.copy is not None
    temp = options.copy if shared else Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
    repo: object | None = None
    baseline: dict[str, object] | None = None
    code, count = 1, 0
    try:
        repo = _install_copy(manifest_data, temp, copy=not shared)
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
        code, count = _run_tests(options, lambda: _cache_bytecode(temp))
    finally:
        problems = _disable_and_unload(module)
        _stop_caching_bytecode()
        changes = _fingerprint_changes(baseline)
        blender_ext.untrack_registrations()
        blender_ext.EXTENSION_MODULES = ()
        problems += _remove_repo(repo, None if shared else temp)
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

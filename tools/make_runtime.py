# SPDX-License-Identifier: GPL-3.0-or-later
"""El motor de cálculo de pruebas (spec 004, T30; RF-004-28, RNF-004-06; plan 004 §5.1 y
§7.1).

La ejecuta una persona, con el Python de Blender, desde la raíz del repositorio::

    & "C:\\Program Files\\Blender Foundation\\Blender 5.2\\5.2\\python\\bin\\python.exe" tools/make_runtime.py (--wheelhouse CARPETA | --pypi)

Crea en ``.deps/runtime/<lock_id>/`` (ignorada por git) el motor de cálculo del lock de la
extensión (``jobs/runtime_lock.toml``) con **el mismo código que el producto**: carga la
extensión por ruta (``gbtools.package.load_geoblender``, HER-01) y lanza su cadena
``jobs.runtime.RuntimeSetup.install`` con un ``jobs.runner.JobRunner`` cuya raíz de
trabajos es una carpeta temporal (se borra al terminar):

1. ``runtime_install``: copia o descarga cada rueda comprobando su huella y la instala con
   el ``pip`` de este intérprete (``--isolated``, ``--target``) en ``<lock_id>.partial/site``.
   Nunca en el ``site-packages`` de Blender.
2. ``runtime_check``, en el entorno ``compute`` sobre esa carpeta: versiones del lock, numpy
   cargado desde ella, BLAS optimizada, producto 2000 × 2000 y longitud de las rutas.
3. Adopción: ``runtime.json`` y ``<lock_id>.partial`` → ``<lock_id>``. Los motores de otros
   locks se borran entonces (RF-004-27); si algo falla, no queda nada a medias.

Las ruedas salen de ``--wheelhouse CARPETA`` (un almacén; sin ninguna opción, el de
``GEOBLENDER_WHEELHOUSE``), sin red, o de ``--pypi`` (las URL del lock). Quien la ejecuta da
su consentimiento al plan que imprime (usuario y equipo de esta sesión de Windows). Si el
motor del lock ya está listo no hace nada; uno roto se sustituye. Al acabar imprime la línea
``RNF-004-06`` con los s de la instalación, los MB en disco y los de las ruedas, y sus
límites (instalación desde un almacén local ≤ 60 s, ≤ 80 MB en disco, descarga ≤ 20 MB).

``tools/check.py`` ejecuta en su paso «motor» las pruebas de dominio con este motor
(:func:`find_test_runtime`, RF-004-28): el de ``.deps`` o, si está definida, la carpeta
``site`` de ``GEOBLENDER_TEST_RUNTIME_SITE``.

Códigos de salida: 0 motor listo (ya lo estaba o se ha instalado); 1 la instalación, la
verificación o la adopción fallaron, o se canceló (no queda ni motor ni carpeta parcial);
2 error de uso o de entorno (opciones, almacén que no existe, lock ilegible, un intérprete
que no es el Python del lock).
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # sin __pycache__ (plan 001 §5.3)

import importlib  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
from collections.abc import Mapping, Sequence  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402
from types import ModuleType  # noqa: E402

from gbtools import layout, wheels  # noqa: E402
from gbtools.blender import DEPS_SITE_RELPATH  # noqa: E402
from gbtools.package import load_geoblender  # noqa: E402
from gbtools.repo import repo_root  # noqa: E402

OPTION_WHEELHOUSE = "--wheelhouse"
OPTION_PYPI = "--pypi"
ENV_TEST_SITE = "GEOBLENDER_TEST_RUNTIME_SITE"
DEPS_RELPATH = DEPS_SITE_RELPATH.parent  # .deps: lo ignora git y no lo copia el espejo
SCRIPT_RELPATH = "tools/make_runtime.py"
HINT = f"ejecute {SCRIPT_RELPATH} {OPTION_WHEELHOUSE} <almacén> (o {OPTION_PYPI})"
TEMP_PREFIX = "gb-motor-"
POLL_S = 0.05
SHUTDOWN_S = 3.0
LOG_TAIL_LINES = 20

# RNF-004-06 (spec 004 §5): el motor de esta spec, solo numpy.
INSTALL_LIMIT_S = 60.0  # desde un almacén local
DISK_LIMIT_MB = 80.0
DOWNLOAD_LIMIT_MB = 20.0

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2

USAGE = f"""Uso (con el Python de Blender, desde la raíz del repositorio):
  & "<Blender>\\5.2\\python\\bin\\python.exe" {SCRIPT_RELPATH} ({OPTION_WHEELHOUSE} CARPETA | {OPTION_PYPI})

  {OPTION_WHEELHOUSE} CARPETA  instala desde un almacén de ruedas (sin red); sin ninguna opción,
                       el de {wheels.ENV_WHEELHOUSE}
  {OPTION_PYPI}               descarga las ruedas de las URL del lock (PyPI)
  --ayuda, -h          muestra esta ayuda

Crea el motor de cálculo de pruebas en {DEPS_RELPATH.as_posix()}/runtime/<lock_id>/.
Códigos: 0 motor listo, 1 fallo (no queda nada a medias), 2 error de uso o de entorno."""


class UsageError(Exception):
    """Opciones, almacén, lock o intérprete no válidos: el mensaje dice cuál."""


@dataclass(frozen=True)
class Options:
    wheelhouse: str | None = None
    pypi: bool = False
    show_help: bool = False


@dataclass(frozen=True)
class TestRuntime:
    """El motor de cálculo de pruebas: su carpeta ``site`` o, si no hay, el motivo
    (:func:`find_test_runtime`)."""

    site: Path | None
    reason: str = ""


def parse_args(args: Sequence[str]) -> Options:
    """Lee ``--wheelhouse CARPETA`` (o ``--wheelhouse=CARPETA``) y ``--pypi``; lanza
    :class:`UsageError` si una opción no existe, falta su valor o se dan las dos."""
    wheelhouse: str | None = None
    pypi = False
    show_help = False
    pending = list(args)
    while pending:
        arg = pending.pop(0)
        if arg in ("--ayuda", "-h", "--help"):
            show_help = True
            continue
        if arg == OPTION_PYPI:
            pypi = True
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
    if pypi and wheelhouse is not None:
        raise UsageError(f"elija {OPTION_WHEELHOUSE} o {OPTION_PYPI}, no los dos")
    return Options(wheelhouse=wheelhouse, pypi=pypi, show_help=show_help)


def load_runtime(root: Path) -> ModuleType:
    """``jobs.runtime`` de la extensión de ``root``, cargada por ruta (HER-01)."""
    package = load_geoblender(root)
    return importlib.import_module(f"{package.__name__}.jobs.runtime")


def _product(root: Path, name: str) -> ModuleType:
    package = load_geoblender(root)
    return importlib.import_module(f"{package.__name__}.jobs.{name}")


def find_test_runtime(
    root: Path,
    environ: Mapping[str, str] | None = None,
    *,
    deps_dir: Path | None = None,
    lock_path: Path | None = None,
) -> TestRuntime:
    """El motor de cálculo de pruebas para el paso «motor» de ``tools/check.py``
    (RF-004-28): la carpeta de ``GEOBLENDER_TEST_RUNTIME_SITE`` si está definida (tiene que
    existir) y, si no, la ``site`` del motor del lock en ``<root>/.deps/runtime`` si está
    listo (``ComputeEnvironment.status``, el código del producto). Si no hay, el motivo con
    la orden que lo crea. Solo lee. ``deps_dir`` y ``lock_path`` (la carpeta ``.deps`` y el
    lock) solo los cambian las pruebas."""
    env = os.environ if environ is None else environ
    value = env.get(ENV_TEST_SITE, "").strip()
    if value:
        site = Path(value)
        if site.is_dir():
            return TestRuntime(site)
        return TestRuntime(
            None, f"no existe la carpeta «{value}» de {ENV_TEST_SITE}: corríjala, o bórrela y "
                  f"{HINT}"
        )
    root = Path(root)
    deps = (root / DEPS_RELPATH) if deps_dir is None else Path(deps_dir)
    lock_file = (root / layout.RUNTIME_LOCK_RELPATH) if lock_path is None else Path(lock_path)
    try:
        runtime = load_runtime(root)
        engine = runtime.ComputeEnvironment(deps.resolve(), runtime.read_lock(lock_file))
        status = engine.status()
    except (ImportError, ValueError, OSError) as exc:
        return TestRuntime(None, f"no se puede leer el lock del motor de cálculo: {exc}")
    if status == runtime.STATUS_READY:
        return TestRuntime(engine.site_dir())
    try:
        where = engine.path.relative_to(root.resolve()).as_posix()
    except ValueError:
        where = str(engine.path)
    if status == runtime.STATUS_MISSING:
        return TestRuntime(None, f"no está el motor de cálculo de pruebas ({where}): {HINT}")
    return TestRuntime(
        None, f"el motor de cálculo de pruebas ({where}) está «{status}»: {HINT}"
    )


def _number(value: object, decimals: int = 1) -> str:
    """Un número con coma decimal (``?`` si no lo es)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "?"
    return f"{value:.{decimals}f}".replace(".", ",")


def _within(value: float, limit: float, unit: str) -> str:
    verdict = "cumple" if value <= limit else "NO CUMPLE"
    return f"≤ {limit:g} {unit}: {verdict}"


def _source(options: Options, environ: Mapping[str, str], runtime: ModuleType) -> object:
    """El ``WheelSource`` de las opciones; :class:`UsageError` si no hay ninguno o la
    carpeta del almacén no existe."""
    if options.pypi:
        return runtime.WheelSource.pypi()
    if options.wheelhouse is not None:
        folder, origin = options.wheelhouse, f"«{OPTION_WHEELHOUSE}»"
    else:
        store = wheels.wheelhouse(environ)
        if store is None:
            raise UsageError(
                f"indique de dónde salen las ruedas: {OPTION_WHEELHOUSE} CARPETA (o la "
                f"variable {wheels.ENV_WHEELHOUSE}) o {OPTION_PYPI}"
            )
        folder, origin = store, f"la variable {wheels.ENV_WHEELHOUSE}"
    path = Path(folder)
    if not path.is_dir():
        raise UsageError(f"no existe la carpeta de ruedas «{folder}» (de {origin})")
    return runtime.WheelSource.wheelhouse(path.absolute())


def _print_plan(plan: object) -> None:
    source = plan.source
    where = (
        "PyPI (las URL del lock)" if source.folder is None else f"el almacén «{source.folder}»"
    )
    print(f"  Origen: {where}")
    for package in plan.packages:
        bundled = ", ".join(package.bundled_licenses)
        bundled = f"; incluye {bundled}" if bundled else ""
        print(f"  {package.name} {package.version} ({package.license}{bundled})")
    print(
        f"  Ruedas: {_number(plan.download_mb)} MB · en disco: {_number(plan.disk_mb)} MB · "
        f"destino: {plan.destination}"
    )


def _log_tail(handles: Sequence[object]) -> list[str]:
    """Las últimas líneas del ``job.log`` del último trabajo de la cadena."""
    if not handles:
        return []
    try:
        text = Path(handles[-1].job_dir.log_file).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return text.rstrip().splitlines()[-LOG_TAIL_LINES:]


def _follow(launcher: object, setup: object) -> float:
    """Sondea el lanzador hasta que acaba la cadena ``setup``, imprimiendo cada mensaje
    nuevo de sus trabajos, y devuelve los s que tardó. Con Ctrl+C la cancela, cierra el
    lanzador y borra la carpeta parcial antes de dejar pasar la interrupción."""
    started = time.perf_counter()
    shown = ""
    try:
        while not setup.done:
            for update in launcher.poll():
                if update.message and update.message != shown:
                    shown = update.message
                    print(f"  {shown}", flush=True)
            if not setup.done:
                time.sleep(POLL_S)
    except KeyboardInterrupt:
        setup.cancel()
        launcher.shutdown(timeout_s=SHUTDOWN_S)
        launcher.poll()  # la cadena acaba «cancelada» y borra la carpeta parcial
        raise
    return time.perf_counter() - started


def install(
    root: Path, runtime: ModuleType, engine: object, plan: object, consent: object
) -> int:
    """Lanza la cadena del producto (``RuntimeSetup.install``) con un lanzador en una raíz
    de trabajos temporal, la sigue hasta el final y la cronometra (RNF-004-06). Deja el
    registro de tipos de trabajo como estaba y borra la raíz temporal."""
    catalog = _product(root, "catalog")
    runner = _product(root, "runner")
    cleanup = _product(root, "cleanup")
    added = [info for info in catalog.BUILTIN_WORKERS if info.name not in catalog.WORKERS]
    for info in added:
        catalog.register_worker(info)
    work = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
    tail: list[str] = []
    try:
        launcher = runner.JobRunner(
            jobs_root=work / "jobs",
            package_dir=Path(root) / layout.EXTENSION_DIR,
            blender_python=Path(sys.executable),
            runtime=engine,
        )
        try:
            setup = runtime.RuntimeSetup.install(launcher, engine, plan, consent)
            seconds = _follow(launcher, setup)
        except KeyboardInterrupt:
            runtime.remove_tree(engine.partial_path)
            print("Cancelado: no se ha instalado el motor de cálculo.", file=sys.stderr)
            return EXIT_FAILED
        finally:
            launcher.shutdown(timeout_s=SHUTDOWN_S)  # idempotente
        if setup.state != runtime.SETUP_SUCCEEDED:
            tail = _log_tail(setup.handles)
    finally:
        for info in added:
            catalog.unregister_worker(info.name)
        if not runtime.remove_tree(work):
            print(f"AVISO: no se pudo borrar la carpeta temporal «{work}»", file=sys.stderr)
    if setup.state != runtime.SETUP_SUCCEEDED:
        print(f"ERROR: {setup.error_text or setup.state}", file=sys.stderr)
        if tail:
            print("Final del registro del trabajo:", file=sys.stderr)
            print("\n".join(f"  {line}" for line in tail), file=sys.stderr)
        print("No se ha instalado el motor de cálculo; no queda nada a medias.", file=sys.stderr)
        return EXIT_FAILED
    check = setup.check or {}
    disk = cleanup.folder_size_mb(engine.path)
    print(
        f"Motor de cálculo listo en «{engine.path}»: numpy {check.get('numpy')} "
        f"(BLAS {check.get('blas')}), producto {check.get('matmul_n')} × "
        f"{check.get('matmul_n')} en {_number(check.get('matmul_s'), 3)} s; ruta más "
        f"larga, {check.get('max_path_length')} caracteres"
    )
    for folder in setup.removed:
        print(f"  Borrado el motor anterior «{folder}»")
    local = plan.source.folder is not None
    timing = f"≤ {INSTALL_LIMIT_S:g} s: " + (
        ("cumple" if seconds <= INSTALL_LIMIT_S else "NO CUMPLE") if local
        else "el límite es desde un almacén local"
    )
    print(
        f"RNF-004-06: instalación desde {'el almacén de ruedas' if local else 'PyPI'} en "
        f"{_number(seconds)} s ({timing}); {_number(disk)} MB en disco "
        f"({_within(disk, DISK_LIMIT_MB, 'MB')}); ruedas de {_number(plan.download_mb)} MB "
        f"({_within(plan.download_mb, DOWNLOAD_LIMIT_MB, 'MB')})"
    )
    return EXIT_OK


def main(
    argv: Sequence[str] | None = None,
    *,
    root: Path | None = None,
    environ: Mapping[str, str] | None = None,
    lock_path: Path | None = None,
    deps_dir: Path | None = None,
) -> int:
    """Crea el motor de cálculo de pruebas y devuelve el código de salida.

    ``root`` (raíz del repositorio con la extensión), ``environ`` (donde se busca
    ``GEOBLENDER_WHEELHOUSE``), ``lock_path`` (el lock; por defecto, el de la extensión) y
    ``deps_dir`` (la carpeta ``.deps`` donde va ``runtime/``) solo los cambian las pruebas.
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
    deps = (root / DEPS_RELPATH) if deps_dir is None else Path(deps_dir)
    lock_file = (root / layout.RUNTIME_LOCK_RELPATH) if lock_path is None else Path(lock_path)
    try:
        runtime = load_runtime(root)
        lock = runtime.read_lock(lock_file)
        source = _source(options, environ, runtime)
    except (UsageError, ImportError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    running = f"{sys.version_info.major}.{sys.version_info.minor}"
    if running != lock.python:
        print(
            f"Error: el motor es para Python {lock.python} y este intérprete es {running} "
            f"(«{sys.executable}»): use el Python de Blender",
            file=sys.stderr,
        )
        return EXIT_USAGE
    engine = runtime.ComputeEnvironment(deps.resolve(), lock)
    print(f"Motor de cálculo de pruebas · lock {lock.lock_id} · {engine.path}")
    status = engine.status()
    if status == runtime.STATUS_READY:
        print(f"El motor de cálculo ya está listo en «{engine.path}»; no se instala otra vez.")
        return EXIT_OK
    try:
        plan = engine.plan_install(source, online_access=True)
    except runtime.JobError as exc:
        print(f"ERROR: {exc.text}", file=sys.stderr)
        return EXIT_FAILED
    print(f"  Estado: {status}; se instala con la cadena del producto")
    _print_plan(plan)
    consent = runtime.Consent.given(plan)
    print(f"  Consentimiento: {consent.user} en {consent.host}, {consent.given_at}")
    return install(root, runtime, engine, plan, consent)


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(_stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")
    sys.exit(main())

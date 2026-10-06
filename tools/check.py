# SPDX-License-Identifier: GPL-3.0-or-later
"""La comprobación completa de Geoblender: la definición de «verde» (plan 001 §5.4.7;
ADR-0015; RF-001-06, RF-001-07, RF-001-09).

Se ejecuta con el Python de Blender, desde la raíz del repositorio::

    & "C:\\Program Files\\Blender Foundation\\Blender 5.2\\5.2\\python\\bin\\python.exe" tools/check.py [--rendimiento] [--banco] [--documentacion]

1. Entorno: localiza Blender (``GEOBLENDER_BLENDER`` o la ruta por defecto) con la
   versión mínima del manifiesto, y exige que el intérprete sea el Python de ese Blender
   y que no se ejecute dentro de Blender. Si algo falla, lo dice con la orden o la
   variable que lo corrige y sale con 2 sin ejecutar nada.
2. Pasos, en este orden y todos aunque falle alguno: «unitarias» (``tests/unit``, que
   incluye las reglas de arquitectura y del repositorio), «referencia»
   (``tests/referencia``; sin casos es correcto), «licencias»
   (``tools/check_licenses.py``), «manifiesto» (``blender --command extension
   validate``) y «blender» (``tools/run_blender_tests.py`` dentro de Blender, en segundo
   plano, de fábrica, con ``--python-exit-code 1``). Solo si se piden, y después de los
   obligatorios: «rendimiento» (``--rendimiento``: ``tests/rendimiento`` con el Python de
   Blender y ``tests/rendimiento/blender/perf_*.py`` dentro de Blender), «banco»
   (``--banco``: ``tools/bench_silvestre.py``; sin banco disponible, «omitido», que no es
   un fallo) y «documentación» (``--documentacion``, spec 007, RF-007-14:
   ``tools/check_docs.py`` sobre la documentación que encuentra ``repo.find_docs``, la
   de ``GEOBLENDER_DOCS_DIR`` o la carpeta madre; si no hay o no se alcanza, «omitido»
   con el motivo, que no es un fallo). Los pasos de Blender usan un perfil temporal en
   ``%TEMP%``, que se borra al terminar.
3. Resumen: una línea por paso (resultado, duración y pruebas), las pruebas omitidas por
   un recurso opcional (``[ENTORNO] <recurso>: <orden>``) agrupadas con la orden que lo
   instala, la salida entera de cada paso que falla y ``RESULTADO: VERDE``,
   ``RESULTADO: VERDE CON OMISIONES (n)`` o ``RESULTADO: NO VERDE``. Si «licencias»
   falla porque faltan ruedas (un clon o *worktree* nuevo), su línea lleva la orden que
   las descarga (``tools/fetch_wheels.py``, con ``--desde`` si ``GEOBLENDER_WHEELHOUSE``
   está definida).

No hay modo «solo una parte»: un verde parcial se confunde con el verde. Para iterar se
ejecuta ``unittest`` directamente (órdenes en ``AGENTS.md``).

En los pasos con pruebas, un fichero de pruebas en disco que ``unittest`` no cargó (en
una carpeta sin ``__init__.py``, con un nombre que no es un módulo válido o sin pruebas)
pone el paso en fallo aunque la orden termine con 0 o «sin pruebas» (``gbtools.
discovery``; convergencia de la spec 001, T35). Y un código 0 (o el 5 «sin pruebas» de
``unittest``) solo vale si la salida llega al resumen de ``unittest`` («Ran N tests» y
«OK», o «NO TESTS RAN») y, en el lanzador, a su línea final («FIN DEL LANZADOR: n
pruebas, código 0», con el mismo número): un proceso que sale a mitad con
``os._exit(0)`` no deja ni lo uno ni lo otro (T37). Y «OK (expected failures=n)» no es
verde: una prueba roja marcada con ``expectedFailure`` («con fallos esperados»; T59).

Una omisión es «VERDE CON OMISIONES» solo si es por un recurso opcional, con el motivo
``[ENTORNO] <recurso>: <orden>`` de ``tests.support.resources``: cualquier otra
(``@unittest.skip``, ``skipTest("…")``, el recurso vacío) esconde una prueba que no se
ejecuta y pone su paso en fallo con «OMISIONES SIN RECURSO» (convergencia de la spec
001, T42). El recurso, además, tiene que estar en la lista cerrada ``RESOURCES`` de
``tests/support/resources.py``, que se lee como texto (sin importar ``tests``): un
recurso inventado, o uno que su spec aún no ha declarado, también es una omisión sin
recurso; y si la lista no se puede leer, todas lo son (T47).

Las pruebas y las herramientas solo escriben en carpetas temporales (spec 001 §11;
RF-001-09): la comprobación hace una foto del repositorio (rutas, tamaños y
``mtime_ns``, ignorados incluidos y sin ``.git/``) antes del primer paso y otra tras el
último; si difieren, una línea «repositorio» en fallo y «REPOSITORIO MODIFICADO» con la
lista de cambios (también un ``__pycache__``), aunque todos los pasos sean correctos
(convergencia de la spec 001, T41). La foto guarda también la fecha de cada carpeta:
un fichero que una prueba crea y borra al terminar no queda, pero cambia la fecha de su
carpeta (T51).

Códigos de salida: 0 verde (también con omisiones); 1 algún paso falló (también una
suite obligatoria sin pruebas o un manifiesto ilegible); 2 entorno (Blender ausente o
anterior al mínimo, otro intérprete, dentro de Blender) u opción no válida.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # sin __pycache__ en Z: (plan 001 §5.3)

import ast  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import tomllib  # noqa: E402
from collections.abc import Callable, Collection, Mapping, Sequence  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from pathlib import Path  # noqa: E402

from gbtools import blender, discovery, layout, manifest, repo, wheels  # noqa: E402
from gbtools.blender import BlenderInstall, EnvironmentProblem  # noqa: E402
from gbtools.repo import repo_root  # noqa: E402
from gbtools.rules import imports  # noqa: E402

STATUS_OK = "correcto"
STATUS_FAIL = "fallo"
STATUS_SKIPPED = "omitido"

# Cómo se interpreta el código de salida de cada orden.
KIND_PLAIN = "orden"  # 0 correcto; otro, fallo
KIND_UNITTEST = "unittest"  # 0 correcto; 5 sin pruebas; otro, fallo
KIND_LAUNCHER = "lanzador"  # run_blender_tests.py: 0; 1 sin pruebas (T57); otro
KIND_BANK = "banco"  # bench_silvestre.py: 0 correcto; 3 omitido; otro, fallo

UNITTEST_NO_TESTS = 5  # «NO TESTS RAN» (plan 001 §2.1, 9)
BANK_OMITTED = 3  # bench_silvestre.py: ningún banco disponible (plan 001 §5.2)
LAUNCHER_NO_TESTS = "NO HAY PRUEBAS"
NO_TESTS = "sin pruebas"
NO_CASES = "sin casos"
SUMMARY_MISSING = "sin el resumen de unittest"
LAUNCHER_END_MISSING = "sin la línea final del lanzador"
EXPECTED_FAILURES = "con fallos esperados"  # «OK (expected failures=n)» (T59)

SKIP_PREFIX = "[ENTORNO]"  # el de tests/support/resources.py
OTHER_SKIPS = "otras omisiones"  # sin «[ENTORNO] <recurso>»: fallo del paso (T42)
RESOURCES_RELPATH = "tests/support/resources.py"  # su lista cerrada de recursos (T47)
RESOURCES_NAME = "RESOURCES"
TEMP_PREFIX = "geoblender-check-"
PROFILE_FOLDER = "perfil"
STEP_TIMEOUT_S = 1800.0  # la comprobación entera tarda menos de 60 s (RNF-001-01)
LAUNCHER_RELPATH = "tools/run_blender_tests.py"
UNITTEST_PATTERN = discovery.UNITTEST_PATTERN  # el de unittest discover sin «-p»
LAUNCHER_PATTERN = "test_*.py"  # el del lanzador sin «--patron» (DEFAULT_PATTERN)
OPTION_PERFORMANCE = "--rendimiento"
OPTION_BANK = "--banco"
OPTION_DOCS = "--documentacion"
OPTIONS: tuple[str, ...] = (OPTION_PERFORMANCE, OPTION_BANK, OPTION_DOCS)
DOCS_STEP = "documentación"
DOCS_RELPATH = "tools/check_docs.py"
NO_DOCS = f"no hay documentación en la carpeta madre ni en {layout.ENV_DOCS_DIR}"
REPOSITORY = "repositorio"  # la línea del resumen si la comprobación cambió el árbol
REPOSITORY_SKIP = (".git",)  # lo cambia git, no la comprobación

USAGE = """Uso (con el Python de Blender, desde la raíz del repositorio):
  & "<Blender>\\5.2\\python\\bin\\python.exe" tools/check.py [--rendimiento] [--banco] [--documentacion]

  --rendimiento     añade las pruebas de rendimiento (también las de dentro de Blender)
  --banco           añade el banco privado de Silvestre (GEOBLENDER_SILVESTRE_DIR)
  --documentacion   añade la comprobación de la documentación (tools/check_docs.py en
                    GEOBLENDER_DOCS_DIR o en la carpeta madre; sin ella, «omitido»)
  --ayuda, -h       muestra esta ayuda

Blender: GEOBLENDER_BLENDER (ruta a blender.exe o a su carpeta) o la ruta por defecto
«C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe».
Códigos: 0 verde (también con omisiones), 1 no verde, 2 entorno u opción no válida."""

_RAN = re.compile(r"^Ran (\d+) tests? in ", re.MULTILINE)
_OK_LINE = re.compile(r"^OK( \(.*\))?$")  # «OK» u «OK (skipped=3)» tras «Ran N tests»
_NO_TESTS_LINE = re.compile(r"^NO TESTS RAN$")
_LAUNCHER_NO_TESTS_LINE = re.compile(rf"^{LAUNCHER_NO_TESTS} en ", re.MULTILINE)
_TEST_HEAD = discovery.TEST_HEAD
_SKIPPED = re.compile(
    r"\.\.\. skipped (?P<reason>'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")\s*$"
)
_MEASURE_START = re.compile(r"(?=RNF-\d{3}-\d{2}: )")
_OMITTED_BANK = re.compile(r"^OMITIDO: (?P<bank>[^:]+): (?P<why>.+)$", re.MULTILINE)
_CLASS_FIXTURES = frozenset(
    {"setUpClass", "tearDownClass", "setUpModule", "tearDownModule"}
)


class UsageError(Exception):
    """Opciones no válidas: el mensaje dice cuál."""


class ManifestProblem(Exception):
    """El manifiesto no permite saber la versión mínima de Blender."""


@dataclass(frozen=True)
class Options:
    flags: frozenset[str] = frozenset()  # opciones pedidas: --rendimiento, --banco
    show_help: bool = False


@dataclass(frozen=True)
class Run:
    """Una orden de un paso: qué se ejecuta, con qué entorno y cómo se interpreta.

    En las de pruebas, ``folder`` (relativa a la raíz) y ``pattern`` dicen qué ficheros
    de prueba hay en disco, para comprobar que ``unittest`` los cargó todos.
    """

    command: list[str]
    env: dict[str, str]
    kind: str = KIND_PLAIN
    empty: str | None = None  # sin pruebas: None es fallo; si no, el texto (correcto)
    folder: str | None = None
    pattern: str | None = None


@dataclass(frozen=True)
class Context:
    """Lo que necesitan los pasos para construir sus órdenes."""

    root: Path
    install: BlenderInstall
    profile: Path
    blender_modules: frozenset[str] = frozenset()
    # Donde se busca la documentación (GEOBLENDER_DOCS_DIR); None: el del proceso.
    environ: Mapping[str, str] | None = None

    def docs_environ(self) -> Mapping[str, str]:
        """El entorno en que se busca la documentación (``repo.find_docs``)."""
        return os.environ if self.environ is None else self.environ

    def python_env(self) -> dict[str, str]:
        """Entorno del Python de Blender fuera de Blender (``gbtools.blender``)."""
        env = blender.python_env(self.root)
        env.pop(imports.ENV_BLENDER_MODULES, None)
        if self.blender_modules:
            env[imports.ENV_BLENDER_MODULES] = ",".join(sorted(self.blender_modules))
        return env

    def blender_env(self) -> dict[str, str]:
        """Entorno de Blender con el perfil temporal (``gbtools.blender``)."""
        return blender.isolated_env(self.profile)

    def python(self, *args: str, kind: str = KIND_PLAIN, empty: str | None = None) -> Run:
        """Una orden con el Python de Blender (``-B -s -X utf8``)."""
        return Run(blender.python_cmd(self.install, *args), self.python_env(), kind, empty)

    def unittest(
        self, folder: str, pattern: str | None = None, empty: str | None = None
    ) -> Run:
        """``unittest discover -v`` de ``folder`` con la raíz como nivel superior; una
        prueba que devuelve algo (``async def`` en un ``TestCase``, o con ``yield``) es
        un error y no solo un aviso (``-W``; convergencia de la spec 001, T54)."""
        args = ["-W", discovery.UNITTEST_WARNINGS, "-m", "unittest", "discover", "-v"]
        args += ["-s", folder, "-t", "."]
        if pattern is not None:
            args += ["-p", pattern]
        return Run(
            blender.python_cmd(self.install, *args),
            self.python_env(),
            KIND_UNITTEST,
            empty,
            folder,
            UNITTEST_PATTERN if pattern is None else pattern,
        )

    def blender_tests(
        self, folder: str, pattern: str | None = None, empty: str | None = None
    ) -> Run:
        """``tools/run_blender_tests.py`` sobre ``folder``, dentro de Blender."""
        args = ["--carpeta", folder]
        if pattern is not None:
            args += ["--patron", pattern]
        command = blender.background_cmd(self.install, self.root / LAUNCHER_RELPATH, *args)
        return Run(
            command,
            self.blender_env(),
            KIND_LAUNCHER,
            empty,
            folder,
            LAUNCHER_PATTERN if pattern is None else pattern,
        )

    def extension(self, *args: str) -> Run:
        """``blender --factory-startup --command extension …`` con el perfil temporal."""
        return Run(blender.extension_cmd(self.install, *args), self.blender_env())


@dataclass(frozen=True)
class Step:
    """Un paso de la comprobación: su nombre, sus órdenes, si es opcional la opción que
    lo pide (``None``: obligatorio), si falla, qué orden propone el resumen a partir de
    su salida (``advice``) y, antes de ejecutar nada, si hay que omitirlo (``omit``
    devuelve el motivo, o ``None``): un paso omitido no es un fallo, y el resumen lo
    cuenta como omisión con su motivo."""

    name: str
    runs: Callable[[Context], Sequence[Run]]
    option: str | None = None
    advice: Callable[[Context, str], list[str]] | None = None
    omit: Callable[[Context], str | None] | None = None


@dataclass(frozen=True)
class Skip:
    """Una prueba omitida: cuál, qué recurso falta y la orden que lo instala."""

    test: str
    resource: str
    hint: str


@dataclass
class StepResult:
    """Resultado de un paso (plan 001 §5.2)."""

    name: str
    status: str
    seconds: float
    tests: int | None = None
    detail: list[str] = field(default_factory=list)
    skipped: list[Skip] = field(default_factory=list)
    output: str = ""
    measurements: list[str] = field(default_factory=list)
    advice: list[str] = field(default_factory=list)


@dataclass
class _RunOutcome:
    status: str
    tests: int | None
    detail: str
    skipped: list[Skip]
    output: str
    text: str


def _unit(ctx: Context) -> list[Run]:
    return [ctx.unittest("tests/unit")]


def _reference(ctx: Context) -> list[Run]:
    return [ctx.unittest("tests/referencia", empty=NO_CASES)]


def _licenses(ctx: Context) -> list[Run]:
    return [ctx.python("tools/check_licenses.py")]


def _licenses_advice(ctx: Context, text: str) -> list[str]:
    """Si LIC-02 falla porque faltan ruedas o no coinciden (un clon o *worktree* nuevo),
    la orden exacta que las descarga (plan 001 §5.4.12)."""
    if f"[{wheels.RULE_COHERENCE}]" not in text or wheels.FETCH_HINT not in text:
        return []
    return [f"faltan ruedas o no coinciden: {wheels.fetch_command(ctx.install.python)}"]


def _manifest(ctx: Context) -> list[Run]:
    return [ctx.extension("validate", layout.EXTENSION_DIR)]


def _blender(ctx: Context) -> list[Run]:
    return [ctx.blender_tests("tests/blender")]


def _performance(ctx: Context) -> list[Run]:
    return [
        ctx.unittest("tests/rendimiento", pattern="test_*.py", empty=NO_TESTS),
        ctx.blender_tests("tests/rendimiento/blender", pattern="perf_*.py", empty=NO_TESTS),
    ]


def _bank(ctx: Context) -> list[Run]:
    return [ctx.python("tools/bench_silvestre.py", kind=KIND_BANK)]


def _docs_folder(ctx: Context) -> tuple[Path | None, str | None]:
    """La documentación que encuentra ``repo.find_docs`` desde la raíz del código, o el
    motivo por el que no la hay (no hay carpeta, o no existe o no lo es)."""
    found = repo.find_docs(ctx.root, ctx.docs_environ())
    if found is None:
        return None, NO_DOCS
    try:
        return repo.docs_root(found), None
    except repo.DocsProblem as exc:
        return None, str(exc)


def _docs(ctx: Context) -> list[Run]:
    folder, _reason = _docs_folder(ctx)
    return [] if folder is None else [ctx.python(DOCS_RELPATH, str(folder))]


def _docs_omit(ctx: Context) -> str | None:
    return _docs_folder(ctx)[1]


# Tabla de pasos (plan 001 §5.4.7). Las specs siguientes añaden el suyo en su lugar:
# «iconos» (003) tras «licencias» y «motor» (004) tras «blender». Los opcionales se
# ejecutan siempre después de los obligatorios (RF-001-10); «documentación» (spec 007,
# RF-007-14), el último.
STEPS: tuple[Step, ...] = (
    Step("unitarias", _unit),
    Step("referencia", _reference),
    Step("licencias", _licenses, advice=_licenses_advice),
    Step("manifiesto", _manifest),
    Step("blender", _blender),
    Step("rendimiento", _performance, option=OPTION_PERFORMANCE),
    Step("banco", _bank, option=OPTION_BANK),
    Step(DOCS_STEP, _docs, option=OPTION_DOCS, omit=_docs_omit),
)


def parse_args(args: Sequence[str]) -> Options:
    """Lee las opciones; lanza :class:`UsageError` si alguna no existe."""
    show_help = False
    flags: set[str] = set()
    for arg in args:
        if arg in ("--ayuda", "-h", "--help"):
            show_help = True
        elif arg in OPTIONS:
            flags.add(arg)
        else:
            raise UsageError(f"opción desconocida «{arg}»")
    return Options(flags=frozenset(flags), show_help=show_help)


def select_steps(steps: Sequence[Step], flags: Collection[str]) -> list[Step]:
    """Los obligatorios en su orden y, después, los opcionales pedidos (RF-001-10)."""
    mandatory = [step for step in steps if step.option is None]
    optional = [step for step in steps if step.option is not None and step.option in flags]
    return mandatory + optional


def read_minimum(root: Path) -> tuple[int, int, int]:
    """``blender_version_min`` del manifiesto (con BOM se lee igual: lo señalan TXT-01,
    MAN-01 y el paso «manifiesto»)."""
    path = Path(root) / manifest.MANIFEST_RELPATH
    try:
        data = tomllib.loads(path.read_bytes().decode("utf-8-sig"))
        return manifest.blender_min(data)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, ValueError) as exc:
        raise ManifestProblem(
            f"no se puede leer «blender_version_min» de «{manifest.MANIFEST_RELPATH}» "
            f"(MAN-01): {exc}. Corrija el manifiesto: hace falta para localizar Blender"
        ) from None


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def _seconds(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def tests_ran(text: str) -> int | None:
    """Número de pruebas de la última línea «Ran N tests» (``None`` si no hay)."""
    found = _RAN.findall(text)
    return int(found[-1]) if found else None


def known_resources(root: Path) -> frozenset[str] | None:
    """La lista cerrada de recursos por los que se puede omitir una prueba:
    ``RESOURCES`` de ``tests/support/resources.py``, leída como texto (``ast``, sin
    importar ``tests``: HER-01). ``None`` si no se puede leer o no es una tupla de
    textos literales no vacíos (entonces ninguna omisión cuenta como omisión por un
    recurso). Si se asigna varias veces, vale la última."""
    path = Path(root) / RESOURCES_RELPATH
    try:
        tree = ast.parse(path.read_bytes(), filename=str(path))
    except (OSError, SyntaxError, ValueError):
        return None
    found: frozenset[str] | None = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == RESOURCES_NAME for t in targets):
            continue
        try:
            names = ast.literal_eval(value)
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
            names = None
        valid = isinstance(names, tuple) and all(
            isinstance(name, str) and name.strip() for name in names
        )
        found = frozenset(names) if valid else None
    return found


def _unlisted(reason: str, resource: str, resources: Collection[str] | None) -> str:
    """El motivo de una omisión cuyo recurso no vale, con lo que falta."""
    where = f"{RESOURCES_NAME} de {RESOURCES_RELPATH}"
    if resources is None:
        return (
            f"{reason} (no se puede leer la lista cerrada de recursos, {where}: debe ser "
            "una tupla de textos literales)"
        )
    return (
        f"{reason} (el recurso «{resource}» no está en la lista cerrada de recursos, "
        f"{where}: {', '.join(sorted(resources)) or 'vacía'})"
    )


def parse_skips(text: str, resources: Collection[str] | None) -> list[Skip]:
    """Pruebas omitidas en la salida detallada de ``unittest`` (``-v``).

    Una omisión cuenta por su recurso solo si el motivo es ``[ENTORNO] <recurso>:
    <orden>`` y el recurso está en ``resources`` (la lista cerrada,
    :func:`known_resources`; ``None`` si no se pudo leer); si no, va a
    ``OTHER_SKIPS`` con el motivo y por qué no vale.

    Límite declarado (hallazgo F5 de la ronda 4; T63): una omisión por un recurso de la
    lista con una condición que no comprueba ese recurso (``@skipUnless(os.environ.get(
    "X"), skip_reason("symlink", …))``) cuenta como omisión por el recurso: la salida de
    ``unittest`` no dice por qué se omitió, y la regla TST-04 solo ve las condiciones
    constantes. Lo revisa la persona en la revisión del código: la condición debe ser la
    comprobación del recurso (``tests.support.resources.requires``)."""
    skips: list[Skip] = []
    head: re.Match[str] | None = None
    for line in text.splitlines():
        current = _TEST_HEAD.match(line)
        if current is not None:
            head = current
        match = _SKIPPED.search(line)
        if match is None:
            continue
        try:
            reason = str(ast.literal_eval(match.group("reason")))
        except (ValueError, SyntaxError):
            reason = match.group("reason")[1:-1]
        test = "?"
        if head is not None:
            name, where = head.group("name"), head.group("where")
            test = f"{where} ({name})" if name in _CLASS_FIXTURES else where
        resource, _sep, hint = reason[len(SKIP_PREFIX) :].strip().partition(":")
        resource = resource.strip()
        if not reason.startswith(SKIP_PREFIX) or not resource:
            skips.append(Skip(test, OTHER_SKIPS, reason))
        elif resources is None or resource not in resources:
            skips.append(Skip(test, OTHER_SKIPS, _unlisted(reason, resource, resources)))
        else:
            skips.append(Skip(test, resource, hint.strip()))
        head = None
    return skips


def parse_bank_omissions(text: str) -> list[Skip]:
    """Bancos omitidos por ``tools/bench_silvestre.py`` («OMITIDO: <banco>: <motivo>»)."""
    return [
        Skip(f"comparaciones de «{m.group('bank')}»", m.group("bank"), m.group("why"))
        for m in _OMITTED_BANK.finditer(text)
    ]


def parse_measurements(text: str) -> list[str]:
    """Líneas de medida «RNF-NNN-nn: …» que imprimen las pruebas de rendimiento.

    La primera línea del docstring de la prueba, que ``unittest -v`` escribe delante y
    termina en « ... », no cuenta.
    """
    found: list[str] = []
    for line in text.splitlines():
        for chunk in _MEASURE_START.split(line):
            chunk = chunk.strip()
            if not chunk.startswith("RNF-") or chunk.endswith("...") or " ... " in chunk:
                continue
            found.append(chunk)
    return found


def _output_of(result: subprocess.CompletedProcess[str]) -> str:
    parts = [part.rstrip() for part in (result.stdout or "", result.stderr or "")]
    return "\n".join(part for part in parts if part)


def _execute(
    run: Run,
    root: Path,
    runner: blender.Runner,
    resources: Collection[str] | None,
) -> _RunOutcome:
    try:
        result = runner(run.command, env=run.env, cwd=root, timeout=STEP_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        message = f"no terminó en {STEP_TIMEOUT_S:.0f} s: {' '.join(run.command)}"
        return _RunOutcome(STATUS_FAIL, None, "tiempo agotado", [], message, "")
    except OSError as exc:
        message = f"no se pudo ejecutar «{' '.join(run.command)}»: {exc}"
        return _RunOutcome(STATUS_FAIL, None, "no se pudo ejecutar", [], message, "")
    output = _output_of(result)
    text = f"{result.stdout or ''}\n{result.stderr or ''}"
    tests = tests_ran(text)
    if run.kind == KIND_BANK:
        skipped = parse_bank_omissions(text)
    elif run.kind in (KIND_UNITTEST, KIND_LAUNCHER):
        skipped = parse_skips(text, resources)
    else:
        skipped = []
    code = result.returncode
    empty = (run.kind == KIND_UNITTEST and code == UNITTEST_NO_TESTS) or (
        run.kind == KIND_LAUNCHER and code == 1 and launcher_found_no_tests(text)
    )
    if code == 0:
        status, detail = STATUS_OK, ""
    elif run.kind == KIND_BANK and code == BANK_OMITTED:
        status, detail = STATUS_SKIPPED, ""
    elif empty and run.empty is not None:
        status, detail = STATUS_OK, run.empty
    elif empty:
        status, detail = STATUS_FAIL, NO_TESTS
    else:
        status, detail = STATUS_FAIL, f"código {code}"
    problem = summary_problem(run, code, text) if status != STATUS_FAIL else None
    if problem is not None:
        status, detail = STATUS_FAIL, problem[0]
        output = f"{problem[1]}\n{output}"
    unloaded = unloaded_files(run, root, text)
    if unloaded:
        count = _plural(len(unloaded), "fichero sin cargar", "ficheros sin cargar")
        detail = count if status != STATUS_FAIL else f"{detail}, {count}"
        status = STATUS_FAIL
        listed = "\n".join(f"  {rel}" for rel in unloaded)
        output = (
            f"FICHEROS DE PRUEBA SIN CARGAR ({len(unloaded)}) en «{run.folder}» con el "
            f"patrón «{run.pattern}»: unittest no los importó y sus pruebas no se "
            f"ejecutaron; {discovery.HINT}\n{listed}\n{output}"
        )
    unresourced = [skip for skip in skipped if skip.resource == OTHER_SKIPS]
    if unresourced:
        skipped = [skip for skip in skipped if skip.resource != OTHER_SKIPS]
        count = _plural(len(unresourced), "omisión sin recurso", "omisiones sin recurso")
        detail = count if status != STATUS_FAIL else f"{detail}, {count}"
        status = STATUS_FAIL
        listed = "\n".join(f"  {skip.test}: {skip.hint}" for skip in unresourced)
        output = (
            f"OMISIONES SIN RECURSO ({len(unresourced)}): una prueba omitida sin "
            f"«{SKIP_PREFIX} <recurso>: <orden>», o por un recurso que no está en la "
            f"lista cerrada ({RESOURCES_NAME} de {RESOURCES_RELPATH}), no se ejecuta y "
            "no es una omisión por un recurso opcional, sino una prueba escondida "
            "(RF-001-06). Si falta un recurso de la lista, omítala con "
            "tests.support.resources.requires (o skip_reason); si el recurso es nuevo, "
            "lo declara su spec en esa lista; si no, quite la omisión y arregle la "
            f"prueba.\n{listed}\n{output}"
        )
    if status == STATUS_FAIL:
        output = f"(código {code}) {' '.join(run.command)}\n{output}"
    return _RunOutcome(status, tests, detail, skipped, output, text)


def launcher_found_no_tests(text: str) -> bool:
    """Si el lanzador terminó porque no había pruebas: su línea «NO HAY PRUEBAS en …» al
    principio de una línea y, como última línea final, «FIN DEL LANZADOR: 0 pruebas,
    código 1». El texto suelto en otra parte (p. ej. en el error de una medición) no
    cuenta (convergencia de la spec 001, T57)."""
    if _LAUNCHER_NO_TESTS_LINE.search(text) is None:
        return False
    ends = discovery.LAUNCHER_END.findall(text)
    return bool(ends) and tuple(int(value) for value in ends[-1]) == (0, 1)


def summary_problem(run: Run, code: int, text: str) -> tuple[str, str] | None:
    """``(detalle, explicación)`` si una orden de pruebas que dice haber terminado bien
    (código 0, o 5 «sin pruebas» de ``unittest``) no llega al resumen de ``unittest`` y,
    en el lanzador, a su línea final con el mismo número de pruebas y código 0. Un
    proceso que sale a mitad (``os._exit(0)``) no deja ni lo uno ni lo otro. Un «OK
    (expected failures=n)» tampoco vale: una prueba roja marcada con ``expectedFailure``
    no es verde (convergencia de la spec 001, T59).

    Límite declarado (hallazgo F4 de la ronda 4; T63): una prueba que imprime ella misma
    un resumen falso («Ran N tests» y «OK» y, en el lanzador, la línea final con el mismo
    número) y sale con ``os._exit(0)`` no se distingue de una ejecución que terminó bien:
    aquí solo se ven la salida y el código. No es un descuido sino una imitación
    deliberada; la ve la persona en la revisión del código."""
    if run.kind not in (KIND_UNITTEST, KIND_LAUNCHER):
        return None
    if code == 0:
        verdict, expected = _OK_LINE, "OK"
    elif run.kind == KIND_UNITTEST and code == UNITTEST_NO_TESTS:
        verdict, expected = _NO_TESTS_LINE, "NO TESTS RAN"
    else:
        return None
    ran = list(_RAN.finditer(text))
    if not ran:
        return (
            SUMMARY_MISSING,
            "la salida no llega al resumen de unittest («Ran N tests»): el proceso "
            "terminó antes que unittest (p. ej. con os._exit) y no se sabe qué pruebas "
            "pasaron",
        )
    after = text[ran[-1].end() :].splitlines()[1:]
    following = next((line.strip() for line in after if line.strip()), "")
    if not verdict.match(following):
        return (
            SUMMARY_MISSING,
            f"tras «Ran N tests», unittest no dice «{expected}» sino «{following}»",
        )
    if discovery.EXPECTED_FAILURES_MARK in following:
        return (
            EXPECTED_FAILURES,
            f"unittest dice «{following}»: {discovery.EXPECTED_FAILURES_HINT}",
        )
    if run.kind != KIND_LAUNCHER:
        return None
    count = int(ran[-1].group(1))
    ends = discovery.LAUNCHER_END.findall(text)
    if not ends:
        return (
            LAUNCHER_END_MISSING,
            "falta la línea final del lanzador "
            f"(«{discovery.launcher_end_line(count, 0)}»): Blender terminó antes que el "
            "lanzador",
        )
    end_count, end_code = (int(value) for value in ends[-1])
    if (end_count, end_code) != (count, 0):
        return (
            LAUNCHER_END_MISSING,
            f"la línea final del lanzador dice {end_count} pruebas y "
            f"código {end_code}, y unittest, {count} pruebas; Blender salió con {code}",
        )
    return None


def unloaded_files(run: Run, root: Path, text: str) -> list[str]:
    """Ficheros de prueba de ``run.folder`` en disco cuyo módulo no nombra la salida de
    ``unittest -v`` (vacío si la orden no es de pruebas). Los módulos son relativos a la
    raíz o, si la carpeta está fuera de ella, a la propia carpeta (como en el
    lanzador)."""
    if run.folder is None or run.pattern is None:
        return []
    folder = Path(root) / run.folder
    inside = folder.resolve().is_relative_to(Path(root).resolve())
    top = Path(root) if inside else folder
    expected = discovery.expected_modules(folder, run.pattern, top)
    return discovery.missing_modules(expected, discovery.loaded_in_output(text))


def execute_step(step: Step, ctx: Context, runner: blender.Runner) -> StepResult:
    """Ejecuta las órdenes de ``step`` y reúne su resultado; si ``step.omit`` da un
    motivo, no ejecuta nada y el paso queda «omitido» con él."""
    start = time.perf_counter()
    reason = step.omit(ctx) if step.omit is not None else None
    if reason is not None:
        return StepResult(
            step.name,
            STATUS_SKIPPED,
            time.perf_counter() - start,
            detail=[reason],
            skipped=[Skip(f"el paso «{step.name}»", step.name, reason)],
        )
    resources = known_resources(ctx.root)
    outcomes = [_execute(run, ctx.root, runner, resources) for run in step.runs(ctx)]
    seconds = time.perf_counter() - start
    if any(outcome.status == STATUS_FAIL for outcome in outcomes):
        status = STATUS_FAIL
    elif outcomes and all(outcome.status == STATUS_SKIPPED for outcome in outcomes):
        status = STATUS_SKIPPED
    else:
        status = STATUS_OK
    counts = [outcome.tests for outcome in outcomes if outcome.tests]
    tests = sum(counts) if counts else None
    detail: list[str] = []
    if tests:
        detail.append(_plural(tests, "prueba", "pruebas"))
    for outcome in outcomes:
        if outcome.detail and outcome.detail not in detail:
            if outcome.status == STATUS_OK and tests:
                continue  # «sin casos» de una parte cuando otra sí tiene pruebas
            detail.append(outcome.detail)
    skipped = [skip for outcome in outcomes for skip in outcome.skipped]
    if skipped:
        detail.append(_plural(len(skipped), "omitida", "omitidas"))
    output = "\n".join(o.output for o in outcomes if o.status == STATUS_FAIL)
    measurements = [m for outcome in outcomes for m in parse_measurements(outcome.text)]
    advice: list[str] = []
    if status == STATUS_FAIL and step.advice is not None:
        advice = step.advice(ctx, "\n".join(outcome.text for outcome in outcomes))
    return StepResult(
        step.name, status, seconds, tests, detail, skipped, output, measurements, advice
    )


def format_step(result: StepResult) -> str:
    """Línea del resumen: ``  correcto  unitarias     8,9 s  (190 pruebas)``."""
    line = f"  {result.status:<8}  {result.name:<12} {_seconds(result.seconds):>5} s"
    if result.detail:
        line += f"  ({', '.join(result.detail)})"
    return line


def _omissions(results: Sequence[StepResult]) -> list[str]:
    groups: dict[tuple[str, str], list[str]] = {}
    for result in results:
        for skip in result.skipped:
            groups.setdefault((skip.resource, skip.hint), []).append(
                f"{skip.test} [{result.name}]"
            )
    total = sum(len(tests) for tests in groups.values())
    lines = [f"\nOmisiones ({total}), por recurso y con la orden que lo instala:"]
    for (resource, hint), tests in groups.items():
        lines.append(f"  {resource} ({len(tests)}){': ' + hint if hint else ''}")
        lines.extend(f"      {test}" for test in tests)
    return lines


def _verdict(results: Sequence[StepResult], seconds: float) -> str:
    failed = [result.name for result in results if result.status == STATUS_FAIL]
    omitted = sum(len(result.skipped) for result in results)
    total = f"({_seconds(seconds)} s)"
    if failed:
        names = ", ".join(f"«{name}»" for name in failed)
        verb = "falla" if len(failed) == 1 else "fallan"
        return f"RESULTADO: NO VERDE {total}: {verb} {names}"
    if omitted:
        return f"RESULTADO: VERDE CON OMISIONES ({omitted}) {total}"
    return f"RESULTADO: VERDE {total}"


def repository_result(
    root: Path, before: repo.Snapshot, seconds: float
) -> StepResult | None:
    """Fallo «repositorio» si, tras el último paso, el repositorio (rutas, tamaños y
    ``mtime_ns``, ignorados incluidos y sin ``.git/``) no es el de antes del primero:
    las pruebas y las herramientas solo escriben en carpetas temporales (spec 001 §11;
    RF-001-09). ``None`` si no cambió nada. Límite declarado (hallazgo F8 de la ronda 4;
    T63): un fichero que se modifica y se restaura con los mismos bytes y la misma fecha
    no se ve (``gbtools.repo.snapshot``)."""
    start = time.perf_counter()
    changes = repo.snapshot_changes(before, repo.snapshot(root, REPOSITORY_SKIP))
    seconds += time.perf_counter() - start
    if not changes:
        return None
    count = _plural(len(changes), "cambio", "cambios")
    listed = "\n".join(f"  {change}" for change in changes)
    output = (
        f"REPOSITORIO MODIFICADO durante la comprobación ({count}): las pruebas y las "
        "herramientas solo escriben en carpetas temporales (spec 001 §11; RF-001-09). "
        "Lo que dejó el paso o la prueba que lo hizo sigue en el árbol: búsquelo, "
        "corríjalo y bórrelo; si solo cambió la fecha de una carpeta, algo se creó y "
        f"se borró en ella (convergencia, T51).\n{listed}"
    )
    return StepResult(REPOSITORY, STATUS_FAIL, seconds, detail=[count], output=output)


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


def correct_command(python: Path | str) -> str:
    """La orden correcta, en PowerShell, desde la raíz del repositorio."""
    return f'& "{python}" tools/check.py'


def _scripts_dir(install: BlenderInstall) -> Path:
    major, minor, _patch = install.version
    return install.exe.parent / f"{major}.{minor}" / "scripts"


def main(
    argv: Sequence[str] | None = None,
    *,
    root: Path | None = None,
    runner: blender.Runner = blender.run,
    locate: Callable[[tuple[int, int, int]], BlenderInstall] = blender.locate_blender,
    executable: str | None = None,
    loaded_modules: Collection[str] | None = None,
    steps: Sequence[Step] = STEPS,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Ejecuta la comprobación completa y devuelve el código de salida.

    Los parámetros con nombre solo los cambian las pruebas: raíz, ejecutor de órdenes,
    localizador de Blender, intérprete en uso, módulos cargados, tabla de pasos y el
    entorno en que se busca la documentación (``GEOBLENDER_DOCS_DIR``; por defecto, el
    del proceso).
    """
    started = time.perf_counter()
    executable = sys.executable if executable is None else executable
    modules = sys.modules if loaded_modules is None else loaded_modules
    if "bpy" in modules:
        print(
            "ERROR DE ENTORNO: tools/check.py no se ejecuta dentro de Blender: lance la "
            "comprobación con el Python de Blender desde la raíz del repositorio: "
            f"{correct_command(executable)}",
            file=sys.stderr,
        )
        return 2
    try:
        options = parse_args(list(sys.argv[1:] if argv is None else argv))
    except UsageError as exc:
        print(f"Error: {exc}\n\n{USAGE}", file=sys.stderr)
        return 2
    if options.show_help:
        print(__doc__)
        print(USAGE)
        return 0
    if root is None:
        try:
            root = repo_root(Path(__file__))
        except FileNotFoundError as exc:
            print(f"ERROR DE ENTORNO: {exc}", file=sys.stderr)
            return 2
    try:
        minimum = read_minimum(root)
    except ManifestProblem as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print(f"RESULTADO: NO VERDE ({_seconds(time.perf_counter() - started)} s)")
        return 1
    try:
        install = locate(minimum)
    except EnvironmentProblem as exc:
        print(f"ERROR DE ENTORNO: {exc}", file=sys.stderr)
        return 2
    if not blender.is_blender_python(install, executable):
        print(
            f"ERROR DE ENTORNO: tools/check.py se ejecuta con el Python de Blender "
            f"{'.'.join(map(str, install.version))} («{install.python}»), no con "
            f"«{executable}». Desde la raíz del repositorio: "
            f"{correct_command(install.python)}",
            file=sys.stderr,
        )
        return 2

    version = ".".join(str(part) for part in install.version)
    selected = select_steps(steps, options.flags)
    extras = " ".join(option for option in OPTIONS if option in options.flags)
    print(
        f"Geoblender · comprobación completa · Blender {version} ({install.exe})"
        + (f" · {extras}" if extras else "")
    )
    work = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
    results: list[StepResult] = []
    try:
        profile = work / PROFILE_FOLDER
        profile.mkdir()
        ctx = Context(
            root=root,
            install=install,
            profile=profile,
            blender_modules=imports.installation_modules(_scripts_dir(install)),
            environ=environ,
        )
        # Foto del repositorio antes del primer paso, para compararla tras el último.
        snapshot_start = time.perf_counter()
        before = repo.snapshot(root, REPOSITORY_SKIP)
        snapshot_seconds = time.perf_counter() - snapshot_start
        for step in selected:
            result = execute_step(step, ctx, runner)
            results.append(result)
            print(format_step(result), flush=True)
            for line in (*result.measurements, *result.advice):
                print(f"            {line}", flush=True)
        modified = repository_result(root, before, snapshot_seconds)
        if modified is not None:
            results.append(modified)
            print(format_step(modified), flush=True)
    finally:
        try:
            _remove_tree(work)
        except OSError as exc:
            print(f"AVISO: no se pudo borrar la carpeta temporal «{work}»: {exc}")

    if any(result.skipped for result in results):
        print("\n".join(_omissions(results)))
    for result in results:
        if result.status == STATUS_FAIL:
            print(f"\n--- Salida del paso «{result.name}» ---")
            print(result.output)
            print(f"--- Fin de la salida del paso «{result.name}» ---")
    print(_verdict(results, time.perf_counter() - started))
    return 1 if any(result.status == STATUS_FAIL for result in results) else 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(_stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")
    sys.exit(main())

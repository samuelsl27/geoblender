# SPDX-License-Identifier: GPL-3.0-or-later
"""Ayudas de las pruebas de ``tools/check.py`` con un ejecutor simulado (plan 001 §5.4.7):
``tests/unit/tools/test_check_cli_*.py`` (spec 006, T46: el antiguo ``test_check_cli.py``,
partido en módulos más pequeños para que el reparto por tiempo de las partes de
«unitarias» no tenga un suelo de 15 s; RNF-001-01, RNF-007-01). Están aquí porque TST-02
no admite en una carpeta de pruebas un ``.py`` que no case con ``test*.py``.

Ninguna prueba lanza Blender ni Python: el ejecutor simulado (:class:`FakeRunner`) anota
cada orden y devuelve una salida fija por paso; en los pasos con pruebas que terminan con
0, la salida nombra además los módulos de prueba que hay en disco, como haría
``unittest -v``. Con partes, la primera da esa salida (con su línea «PARTE 1 de n: T de T
pruebas») y las demás, una parte sin pruebas que termina bien, salvo que la prueba fije la
de una parte (``"<paso>#<i>"``). :func:`run_check` ejecuta ``check.main`` con él y recoge
la salida; si la prueba no dice otra cosa, con un motor de cálculo de pruebas simulado
(:data:`FAKE_SITE`), sin almacén de tiempos y sin el cerrojo del equipo (spec 006, T46:
lo prueba ``tests/unit/tools/test_check_lock.py``).
"""

import contextlib
import fnmatch
import io
import re
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

from tests.support.repo import EXT, ROOT, tools_on_path
from tests.support.trees import temp_tree

tools_on_path()

import check  # noqa: E402
from gbtools import blender, discovery, parts  # noqa: E402
from gbtools.blender import BlenderInstall  # noqa: E402
from gbtools.layout import CODE_DIR_IN_DOCS, DOCS_MARKER, ENV_DOCS_DIR  # noqa: E402
from gbtools.rules import imports  # noqa: E402

FAKE_BLENDER = Path(tempfile.gettempdir()) / "geoblender-falso" / "Blender"
INSTALL = BlenderInstall(
    exe=FAKE_BLENDER / "blender.exe",
    python=FAKE_BLENDER / "5.2" / "python" / "bin" / "python.exe",
    version=(5, 2, 1),
)
# Los pasos obligatorios en el orden de la tabla, que es el del resumen (RF-001-06).
MANDATORY = ["unitarias", "referencia", "licencias", "iconos", "manifiesto", "blender"]
# Los que van a la vez que «blender», tras «manifiesto» (RF-001-06, spec 001 0.8, tarea
# 009/T34; «unitarias» desde la 0.10, tarea 011/T30), en el orden de la tabla; «motor»
# (--completo) va solo, después de ellos (tarea 011/T36).
WITH_BLENDER = ("unitarias", "referencia", "licencias", "iconos")
# El orden en que se ejecutan los obligatorios (FakeRunner.steps): «manifiesto», el primero,
# y después los que van a la vez que «blender», en el orden de la tabla, con «blender» al final.
EXECUTED = ["manifiesto", *WITH_BLENDER, "blender"]
_WITH_BLENDER_BLOCK = (*WITH_BLENDER, "blender")
# El paso de la spec 004 (T30): las pruebas de dominio con el numpy del motor de cálculo de
# pruebas, tras «blender» (desde la tarea 011/T36; antes, a la vez que él), con --completo (spec 004 0.4; spec 005, T50). Salvo en
# RuntimeStepTest, el motor es este, simulado.
RUNTIME = "motor"
FAKE_SITE = Path(tempfile.gettempdir()) / "geoblender-falso" / "motor" / "site"
DOMAIN_FOLDERS = [
    f"tests/unit/{name}" for name in imports.LEVELS if (ROOT / "tests" / "unit" / name).is_dir()
]
# Una prueba que devuelve algo (``async def`` en un TestCase, o con ``yield``) es un
# error y no solo un aviso (hallazgo F7 de la ronda 3; convergencia, T54).
RETURN_VALUE_IS_ERROR = ("-W", "error:It is deprecated to return a value:DeprecationWarning")
LINE = "-" * 70
SPDX = "# SPDX-License-Identifier: GPL-3.0-or-later\n"
USER_VARIABLES = (
    "BLENDER_USER_CONFIG",
    "BLENDER_USER_SCRIPTS",
    "BLENDER_USER_EXTENSIONS",
    "BLENDER_USER_DATAFILES",
)


def _unittest_output(ran: int, verdict: str = "OK", body: str = "") -> str:
    return f"{body}\n{LINE}\nRan {ran} tests in 1.234s\n\n{verdict}\n"


def _launcher_output(
    ran: int, verdict: str = "OK", body: str = "", code: int = 0
) -> str:
    """Salida del lanzador: la de ``unittest`` y su línea final (T37)."""
    noun = "prueba" if ran == 1 else "pruebas"
    end = f"FIN DEL LANZADOR: {ran} {noun}, código {code}\n"
    return _unittest_output(ran, verdict, body) + end


NO_TESTS = f"\n{LINE}\nRan 0 tests in 0.000s\n\nNO TESTS RAN\n"
NO_TESTS_END = "FIN DEL LANZADOR: 0 pruebas, código 1\n"  # el lanzador sin pruebas (T57)
DEFAULT_RESULTS: Mapping[str, tuple[int, str, str]] = {
    "unitarias": (
        0,
        "",
        _unittest_output(
            217, body="test_a (tests.unit.test_a.A.test_a)\nRF-001-01: doc. ... ok"
        ),
    ),
    # Desde la spec 002 (T03) el repositorio tiene casos de referencia: por defecto el
    # paso los carga (el ejecutor simulado nombra los módulos que hay en disco). «Sin
    # casos» se prueba en una raíz temporal sin ellos (test_empty_reference_suite_ok).
    "referencia": (0, "", _unittest_output(2)),
    "licencias": (0, "Licencias (LIC-01 a LIC-04): correcto\n", ""),
    "iconos": (0, "RESULTADO: correcto (0,0 s): 58 iconos con sus PNG y su manifiesto\n", ""),
    "manifiesto": (0, 'Success parsing TOML in "Geoblender"\n', ""),
    "blender": (
        0,
        "Extensión de pruebas: bl_ext.gb_tests.geoblender\n",
        _launcher_output(12),
    ),
    "rendimiento": (0, "", _unittest_output(2)),
    "rendimiento-blender": (
        0,
        "",
        _launcher_output(
            1,
            body=(
                "test_enable_under_half_second (tests.rendimiento.blender.perf_registration"
                ".RegistrationSpeedTest.test_enable_under_half_second)\n"
                "RNF-001-03: habilitar Geoblender en segundo plano tarda poco (mediana de"
                " ... RNF-001-03: habilitar Geoblender, mediana de 3 ciclos: 0,006 s\nok"
            ),
        ),
    ),
    "banco": (
        3,
        "OMITIDO: silvestre: la variable GEOBLENDER_SILVESTRE_DIR no está definida; "
        "defínala con la carpeta del banco\nBancos: omitidos\n",
        "",
    ),
    "documentación": (
        0,
        "Geoblender · comprobación de la documentación · x\n"
        "RESULTADO: DOCUMENTACIÓN CORRECTA (6 ficheros, 0,0 s)\n",
        "",
    ),
    "arnés": (0, "", _unittest_output(23)),
    RUNTIME: (0, "", _unittest_output(40)),
}
OPTIONAL = ["rendimiento", "rendimiento-blender", "banco"]
HARNESS = "arnés"  # el paso de --completo (spec 001 0.6; spec 002, T48)
NOT_COMPLETE_NOTE = "--completo"  # la línea del resumen sin --completo la nombra
DOCS_STEP = "documentación"
NO_DOCS = f"no hay documentación en la carpeta madre ni en {ENV_DOCS_DIR}"


def step_of(cmd: Sequence[str]) -> str:
    """Paso al que pertenece una orden simulada."""
    parts = [str(part) for part in cmd]
    if "validate" in parts:
        return "manifiesto"
    if any(part.replace("\\", "/").endswith("tools/check_licenses.py") for part in parts):
        return "licencias"
    if any(part.endswith("build_icons.py") for part in parts):
        return "iconos"
    if any(part.replace("\\", "/").endswith("tools/bench_silvestre.py") for part in parts):
        return "banco"
    if any(part.replace("\\", "/").endswith("tools/check_docs.py") for part in parts):
        return DOCS_STEP
    if any(part.endswith("run_blender_tests.py") for part in parts):
        if "tests/rendimiento/blender" in parts:
            return "rendimiento-blender"
        return "blender"
    if "-S" in parts:  # el Python de Blender sin su site-packages: el numpy del motor
        return RUNTIME
    if "discover" in parts:  # «-m unittest discover» o tools/unittest_part.py (T40)
        folder = parts[parts.index("-s", parts.index("discover")) + 1]
        return {
            "tests/unit": "unitarias",
            "tests/referencia": "referencia",
            "tests/rendimiento": "rendimiento",
            "tests/arnes": HARNESS,
        }[folder]
    raise AssertionError(f"orden inesperada: {parts}")


TEST_STEPS = (
    "unitarias",
    "referencia",
    "rendimiento",
    "blender",
    "rendimiento-blender",
    HARNESS,
    RUNTIME,
)


def suite_of(step: str, cmd: Sequence[str]) -> tuple[str, str]:
    """Carpeta y patrón de una orden de pruebas simulada (los de ``unittest`` y del
    lanzador por defecto si la orden no los da)."""
    parts = [str(part) for part in cmd]
    if step in ("blender", "rendimiento-blender"):
        folder = parts[parts.index("--carpeta") + 1]
        pattern = parts[parts.index("--patron") + 1] if "--patron" in parts else "test_*.py"
    else:
        folder = parts[parts.index("-s", parts.index("discover")) + 1]
        pattern = parts[parts.index("-p") + 1] if "-p" in parts else "test*.py"
    return folder, pattern


def disk_modules(root: Path, folder: str, pattern: str) -> list[str]:
    """Módulos de prueba de ``folder`` en disco (cálculo propio de la prueba, sin
    ``gbtools.discovery``)."""
    found: list[str] = []
    for path in sorted((root / folder).rglob("*.py")):
        if "__pycache__" not in path.parts and fnmatch.fnmatch(path.name, pattern):
            found.append(path.relative_to(root).with_suffix("").as_posix().replace("/", "."))
    return found


@dataclass
class Call:
    step: str
    cmd: list[str]
    env: dict[str, str]
    cwd: Path | None
    timeout: float | None
    profile_existed: bool | None
    part: tuple[int, int] | None = None  # «--parte i/n» (T40)
    started: float = 0.0  # time.perf_counter() al empezar y al terminar
    ended: float = 0.0


Result = tuple[int, str, str] | BaseException
LAUNCHER_STEPS = ("blender", "rendimiento-blender")


def part_of(cmd: Sequence[str]) -> tuple[int, int] | None:
    """La parte «i/n» de una orden con ``--parte`` (``None`` sin ella; T40)."""
    items = [str(item) for item in cmd]
    if parts.OPTION not in items:
        return None
    return parts.parse(items[items.index(parts.OPTION) + 1])


def _total(result: Result) -> int:
    """Las pruebas («Ran N tests») de una salida fijada que termina con 0; si no, 0."""
    if isinstance(result, BaseException) or result[0] != 0:
        return 0
    return check.tests_ran(f"{result[1]}\n{result[2]}") or 0


def _empty_part(step: str, part: tuple[int, int], total: int) -> Result:
    """Una parte sin pruebas que termina bien: su línea «PARTE i de n: 0 de T pruebas»,
    el resumen de ``unittest`` y, en el lanzador, su línea final."""
    end = discovery.launcher_end_line(0, 0) + "\n" if step in LAUNCHER_STEPS else ""
    return (0, "", parts.line(*part, 0, total) + "\n" + _unittest_output(0) + end)


class FakeRunner:
    """Ejecutor simulado: anota cada orden y devuelve la salida fijada para su paso.

    Con ``loaded=True`` (por defecto), un paso de pruebas que termina con 0 nombra al
    principio de su salida cada módulo de prueba que hay en disco (``unittest -v``).
    ``effects`` hace algo en la carpeta de trabajo (la raíz) cuando se ejecuta un paso,
    como una prueba que escribe donde no debe. ``on_call`` se llama con cada orden, en
    el hilo que la ejecuta, antes de devolver su salida.

    Una orden con ``--parte i/n`` (T40) devuelve la salida fijada para ``"<paso>#<i>"``
    si la hay; si no, la parte 1 da la del paso (con «PARTE 1 de n: T de T pruebas» si
    termina con 0 y dice «Ran T tests», y los módulos de disco) y las demás, una parte
    sin pruebas que termina bien (``_empty_part``).
    """

    def __init__(
        self,
        overrides: Mapping[str, Result] | None = None,
        loaded: bool = True,
        effects: Mapping[str, Callable[[Path], object]] | None = None,
        on_call: Callable[[Call], object] | None = None,
    ) -> None:
        self.results: dict[str, Result] = {**DEFAULT_RESULTS, **(overrides or {})}
        self.calls: list[Call] = []
        self.loaded = loaded
        self.effects = dict(effects or {})
        self.on_call = on_call

    def result_of(self, step: str, part: tuple[int, int] | None) -> Result:
        if part is None:
            return self.results[step]
        key = f"{step}#{part[0]}"
        if key in self.results:
            return self.results[key]
        base = self.results[step]
        if part[0] > 1:
            return _empty_part(step, part, _total(base))
        if isinstance(base, BaseException) or not _total(base):
            return base
        code, stdout, stderr = base
        total = _total(base)
        return (code, stdout, parts.line(1, part[1], total, total) + "\n" + stderr)

    def __call__(
        self,
        cmd: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: Path | None = None,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        step = step_of(cmd)
        part = part_of(cmd)
        environment = dict(env or {})
        profile = environment.get("BLENDER_USER_RESOURCES")
        call = Call(
            step,
            [str(item) for item in cmd],
            environment,
            cwd,
            timeout,
            Path(profile).is_dir() if profile else None,
            part,
            time.perf_counter(),
        )
        self.calls.append(call)
        try:
            if self.on_call is not None:
                self.on_call(call)
            first = part is None or part[0] == 1
            if step in self.effects and cwd is not None and first:
                self.effects[step](Path(cwd))
            result = self.result_of(step, part)
            if isinstance(result, BaseException):
                raise result
            code, stdout, stderr = result
            if self.loaded and code == 0 and step in TEST_STEPS and cwd is not None and first:
                heads = [
                    f"test_cargado ({module}.Cargado.test_cargado) ... ok\n"
                    for module in disk_modules(Path(cwd), *suite_of(step, cmd))
                ]
                stderr = "".join(heads) + stderr
            return subprocess.CompletedProcess(list(cmd), code, stdout, stderr)
        finally:
            call.ended = time.perf_counter()

    def steps(self) -> list[str]:
        """Los pasos en el orden de sus órdenes; las partes seguidas de un paso, una vez.
        Las órdenes de «blender» y de los que van a la vez que él (:data:`WITH_BLENDER`;
        spec 001 0.8) se mezclan: las seguidas cuentan como un bloque, que da sus pasos en el
        orden de :data:`EXECUTED` (los que van con él y «blender» al final); el bloque acaba en
        una orden de otro paso o en una que ya tiene (la misma parte de un paso, o un paso sin
        partes). El paso «motor» no cuenta (se mira aparte, con ``calls_of``)."""
        found: list[str] = []
        block: dict[str, set[tuple[int, int] | None]] = {}

        def close() -> None:
            found.extend(step for step in _WITH_BLENDER_BLOCK if step in block)
            block.clear()

        previous: Call | None = None
        for call in self.calls:
            if call.step == RUNTIME:
                continue
            if call.step in _WITH_BLENDER_BLOCK:
                seen = block.get(call.step)
                if seen is not None and (call.part is None or call.part in seen):
                    close()
                block.setdefault(call.step, set()).add(call.part)
                previous = call
                continue
            if block:
                close()
            same = previous is not None and previous.step == call.step
            if not (same and call.part is not None and previous.part is not None):
                found.append(call.step)
            previous = call
        if block:
            close()
        return found

    def call(self, step: str, part: int | None = None) -> Call:
        """La orden de ``step`` (o su parte ``part``): tiene que haber una sola."""
        found = [
            call
            for call in self.calls
            if call.step == step
            and (part is None or (call.part is not None and call.part[0] == part))
        ]
        if len(found) != 1:
            raise AssertionError(f"«{step}» se ejecutó {len(found)} veces")
        return found[0]

    def calls_of(self, step: str) -> list[Call]:
        """Las órdenes de ``step``, por número de parte."""
        found = [call for call in self.calls if call.step == step]
        return sorted(found, key=lambda call: call.part or (0, 0))


@dataclass
class Outcome:
    code: int
    out: str
    err: str
    runner: FakeRunner


def run_check(
    *args: str,
    runner: FakeRunner | None = None,
    executable: str | None = None,
    modules: Sequence[str] = (),
    locate: Callable[[tuple[int, int, int]], BlenderInstall] | None = None,
    root: Path = ROOT,
    **kwargs: object,
) -> Outcome:
    """Ejecuta ``check.main`` con el ejecutor simulado y recoge la salida; si la prueba no
    dice otra cosa (``find_runtime``, ``times_store``, ``lock_file``, ``test_copy``,
    ``bytecode``), con un motor de cálculo de pruebas simulado (:data:`FAKE_SITE`), sin
    almacén de tiempos, sin el cerrojo del equipo, sin la copia compartida de la extensión y
    sin la carpeta del código compilado."""
    runner = FakeRunner() if runner is None else runner
    kwargs.setdefault("find_runtime", lambda root, environ: check.TestRuntime(FAKE_SITE))
    # Sin almacén de tiempos (spec 004, T39): las órdenes de siempre, y nada se escribe
    # en el almacén de la carpeta temporal del sistema; lo prueba PartTimesTest.
    kwargs.setdefault("times_store", lambda root: None)
    # Sin el cerrojo del equipo (spec 006, T46): ni se espera al check.py de otra sesión
    # ni se escribe en %LOCALAPPDATA%; lo prueba tests/unit/tools/test_check_lock.py.
    kwargs.setdefault("lock_file", lambda environ: None)
    # Sin la copia compartida de la extensión (spec 006, T48): cada parte de «blender», la
    # orden de siempre, y no se copia la extensión; lo prueba
    # PartsTest.test_shared_copy_for_the_blender_parts.
    kwargs.setdefault("test_copy", None)
    # Sin la carpeta del código compilado (spec 005, T44): las órdenes de Python sin
    # PYTHONPYCACHEPREFIX, y no se compila nada en la carpeta temporal del sistema; lo prueba
    # PartsTest.test_bytecode_folder_for_the_python_steps.
    kwargs.setdefault("bytecode", lambda root: None)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = check.main(
            list(args),
            root=root,
            runner=runner,
            locate=locate if locate is not None else (lambda minimum: INSTALL),
            executable=str(INSTALL.python) if executable is None else executable,
            loaded_modules=modules,
            **kwargs,
        )
    return Outcome(code, out.getvalue(), err.getvalue(), runner)


def many_cpus() -> contextlib.AbstractContextManager[object]:
    """24 procesadores: el número de partes no depende del puesto (T40)."""
    return mock.patch("os.cpu_count", return_value=24)


def unit_part_cmd(part: int, count: int) -> list[str]:
    """La orden de la parte ``part`` de ``count`` de las pruebas unitarias (T40)."""
    return blender.python_cmd(
        INSTALL,
        *RETURN_VALUE_IS_ERROR,
        "tools/unittest_part.py",
        parts.OPTION,
        parts.label(part, count),
        "discover",
        "-v",
        "-s",
        "tests/unit",
        "-t",
        ".",
    )


def reference_part_cmd(part: int, count: int) -> list[str]:
    """La orden de la parte ``part`` de ``count`` de los casos de referencia (spec 006,
    T59)."""
    return blender.python_cmd(
        INSTALL,
        *RETURN_VALUE_IS_ERROR,
        "tools/unittest_part.py",
        parts.OPTION,
        parts.label(part, count),
        "discover",
        "-v",
        "-s",
        "tests/referencia",
        "-t",
        ".",
    )


def blender_part_cmd(part: int, count: int) -> list[str]:
    """La orden de la parte ``part`` de ``count`` de las pruebas de Blender (T40)."""
    return blender.background_cmd(
        INSTALL,
        ROOT / "tools" / "run_blender_tests.py",
        "--carpeta",
        "tests/blender",
        parts.OPTION,
        parts.label(part, count),
    )


def _seconds_of(line: str) -> float:
    """La duración de una línea del resumen («  correcto  blender  0,3 s  (…)»)."""
    match = re.search(r"\s(\d+),(\d) s", line)
    if match is None:
        raise AssertionError(f"sin duración: {line}")
    return float(f"{match.group(1)}.{match.group(2)}")


def _step_line(out: str, name: str) -> str:
    lines = [line for line in out.splitlines() if re.match(rf"^  \S+\s+{name}\s", line)]
    if len(lines) != 1:
        raise AssertionError(f"no hay una línea de «{name}» en:\n{out}")
    return lines[0]


def _python_env() -> dict[str, str]:
    return blender.python_env(ROOT)


def _manifest_root(
    files: Mapping[str, str] | None = None,
) -> contextlib.AbstractContextManager[Path]:
    """Raíz temporal con el manifiesto real y ``files``: ``check.main`` la acepta."""
    manifest = (ROOT / EXT / "blender_manifest.toml").read_bytes()
    return temp_tree({f"{EXT}/blender_manifest.toml": manifest, **(files or {})})


def _project_root(docs: bool = True) -> contextlib.AbstractContextManager[Path]:
    """Carpeta del proyecto temporal: el código (con el manifiesto real) en
    ``Geoblender/`` y, con ``docs``, la documentación en la carpeta madre."""
    manifest = (ROOT / EXT / "blender_manifest.toml").read_bytes()
    files: dict[str, str | bytes] = {
        f"{CODE_DIR_IN_DOCS}/{EXT}/blender_manifest.toml": manifest
    }
    if docs:
        files[DOCS_MARKER] = "# Constitución\n"
    return temp_tree(files)


def _resources_file(*names: str) -> dict[str, str]:
    """``tests/support/resources.py`` de una raíz temporal con la lista cerrada de
    recursos ``names`` (la que amplía cada spec con los suyos; T47)."""
    return {"tests/support/resources.py": f"{SPDX}RESOURCES: tuple[str, ...] = {names!r}\n"}

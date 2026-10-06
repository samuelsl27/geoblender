# SPDX-License-Identifier: GPL-3.0-or-later
"""La publicación de Geoblender: sube el código a GitHub y deja el espejo del NAS igual
que la carpeta del proyecto (spec 007, HU-007-4 y HU-007-7; plan 007 §5.4.5 a §5.4.9;
ADR-0023).

Se ejecuta con el Python de Blender, desde la raíz del repositorio de código (la carpeta
``Geoblender\\`` de la carpeta del proyecto)::

    & "<Blender>\\5.2\\python\\bin\\python.exe" -B tools/publish.py [--destino CARPETA] [--solo-espejo] [--rehacer-estado]

1. Raíz: la del código (``repo_root``) es la de su repositorio git.
2. Estructura (RF-007-33): el código está en la carpeta ``Geoblender`` (con esa
   mayúscula) directamente dentro de la carpeta del proyecto, que es la documentación
   (``docs/constitution.md`` y su ``.git``); ``GEOBLENDER_DOCS_DIR``, si está definida,
   es esa misma carpeta.
3. Destino (RF-007-17, RF-007-18, RF-007-31): ``--destino`` o, si no,
   ``GEOBLENDER_NAS_ESPEJO``. Se rechaza (sin escribir nada en él) la raíz de una unidad
   o de un recurso, la carpeta de expedientes de clientes o una de dentro (por el texto,
   sin buscar la unidad ni el servidor, y por la ruta real), la carpeta del proyecto,
   una de dentro o una que la contiene, uno que no existe o no es una carpeta, y uno sin
   ``docs/constitution.md`` salvo el primer espejo contra su foto. La base de la
   comparación es el estado del último espejo de ese destino o, en el primero, su foto
   inicial (``gbtools.safe_mirror``); sin ninguno, o con un estado ilegible, código 2 y
   ``--rehacer-estado``.
4. Remoto (RF-007-19): el código tiene ``origin``, y ni su dirección ni el texto de los
   dos ``.git/config`` llevan credenciales (usuario con contraseña o token en una
   dirección, también en una regla ``insteadOf``, o una cabecera ``extraHeader``): el
   espejo copiaría los ``.git`` al NAS. Si no, código 2 sin mostrar el secreto.
5. Árboles (RF-007-15), en los dos repositorios: ``.git`` propio (ni *worktree*
   enlazado ni ``alternates``), sin cambios sin commit ni ficheros nuevos sin ignorar,
   sin operaciones de git a medias ni cerrojos, HEAD en una rama; y la documentación no
   versiona nada bajo ``Geoblender/`` (ni un *gitlink*).
8. Comprobaciones (RF-007-16), con el Python del Blender del manifiesto y desde la raíz
   del código, con su salida en directo: ``tools/check.py`` (salvo con
   ``--solo-espejo``) y siempre ``tools/check_docs.py <carpeta del proyecto>``; las dos
   tienen que terminar con 0. Después se miran otra vez los árboles: las comprobaciones
   no deben cambiar nada.
9. Subida (RF-007-20, RF-007-21), salvo con ``--solo-espejo``: ``git push
   --follow-tags`` de la rama actual del código a la misma rama de ``origin``, nunca
   forzada; si falla (rechazada, sin red o sin permiso), código 1 con el mensaje de git
   y sin espejo.

Las lecturas de git no toman cerrojos opcionales (``gbtools.git``): no reescriben
``.git/index``. Nadie publica salvo la persona que publica (D-15); un agente, solo si
ella se lo pide en esa tarea.

Códigos de salida: 0 publicado; 1 árbol no limpio, *worktree* o ``alternates``, la
documentación versiona algo bajo ``Geoblender/``, comprobación roja; 2 uso, raíz,
estructura, sin destino, destino rechazado, sin estado ni foto o estado ilegible, o sin
el Blender del manifiesto; 3 cambios en el destino.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # sin __pycache__ en los repositorios

import datetime  # noqa: E402
import ntpath  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
from collections.abc import Callable, Mapping, Sequence  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402

from gbtools import blender, git, layout, manifest, safe_mirror  # noqa: E402
from gbtools.repo import repo_root  # noqa: E402

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
EXIT_CHANGES = 3

OPTION_DEST = "--destino"
OPTION_MIRROR_ONLY = "--solo-espejo"
OPTION_REBUILD = "--rehacer-estado"
HELP_OPTIONS: tuple[str, ...] = ("--ayuda", "-h", "--help")

STATUS_OK = "correcto"
STATUS_FAIL = "fallo"
STATUS_STOP = "PARADA"
STATUS_SKIPPED = "omitido"

STEP_STRUCTURE = "estructura"
STEP_DEST = "destino"
STEP_REMOTE = "remoto"
STEP_TREES = "árboles"
STEP_CHECK = "comprobación"
STEP_DOCS = "documentación"
STEP_PUSH = "subida"

# El primer componente bajo la raíz de una unidad, o el nombre del recurso, de la
# carpeta de expedientes de clientes (solo lectura, siempre): nunca es un destino.
DOSSIER_FOLDER = "an"
_SEPARATORS = re.compile(r"[\\/]+")

CHECK_SCRIPT = layout.CHECK_RELPATH
DOCS_CHECK_SCRIPT = "tools/check_docs.py"
CHECK_TIMEOUT_S = 1800.0  # la comprobación completa tarda menos de 60 s
RESULT_PREFIX = "RESULTADO:"

CODE_LABEL = "código"
DOCS_LABEL = "documentación"
NOTHING_DONE = "No se ha subido ni copiado nada."

USAGE = f"""Uso (con el Python de Blender, desde la raíz del repositorio de código):
  & "<Blender>\\5.2\\python\\bin\\python.exe" -B tools/publish.py [opciones]

  {OPTION_DEST} CARPETA  el espejo (por defecto, la variable {layout.ENV_NAS_MIRROR})
  {OPTION_MIRROR_ONLY}       solo el espejo: sin comprobar el código ni subirlo
  {OPTION_REBUILD}    rehace el estado del espejo si nada del destino se pierde
  --ayuda, -h          muestra esta ayuda

Códigos: 0 publicado, 1 árboles, comprobación, subida o espejo, 2 uso, estructura o
destino, 3 cambios en el destino desde el último espejo."""


class UsageError(Exception):
    """Opciones no válidas: el mensaje dice cuál."""


class Stop(Exception):
    """La publicación se para en un paso: código de salida, paso, motivo y, si hay, la
    lista de lo que hay que corregir."""

    def __init__(
        self, code: int, step: str, detail: str, lines: Sequence[str] = ()
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.step = step
        self.detail = detail
        self.lines = list(lines)


@dataclass(frozen=True)
class Options:
    destination: str | None = None
    mirror_only: bool = False
    rebuild_state: bool = False
    show_help: bool = False


def parse_args(args: Sequence[str]) -> Options:
    """Lee las opciones; :class:`UsageError` si alguna no vale."""
    destination: str | None = None
    mirror_only = rebuild = show_help = False
    items = list(args)
    index = 0
    while index < len(items):
        arg = items[index]
        index += 1
        if arg in HELP_OPTIONS:
            show_help = True
        elif arg == OPTION_MIRROR_ONLY:
            mirror_only = True
        elif arg == OPTION_REBUILD:
            rebuild = True
        elif arg == OPTION_DEST or arg.startswith(f"{OPTION_DEST}="):
            if "=" in arg:
                value = arg.partition("=")[2]
            elif index < len(items):
                value, index = items[index], index + 1
            else:
                value = ""
            if not value.strip():
                raise UsageError(f"{OPTION_DEST} necesita una carpeta")
            if destination is not None:
                raise UsageError(f"{OPTION_DEST} se da una sola vez")
            destination = value
        else:
            raise UsageError(f"opción desconocida «{arg}»")
    if mirror_only and rebuild:
        raise UsageError(f"{OPTION_MIRROR_ONLY} y {OPTION_REBUILD} no se combinan")
    return Options(destination, mirror_only, rebuild, show_help)


def same_path(a: str | os.PathLike[str], b: str | os.PathLike[str]) -> bool:
    """Si ``a`` y ``b`` son la misma carpeta (ruta real, sin distinguir mayúsculas)."""

    def norm(path: str | os.PathLike[str]) -> str:
        return os.path.normcase(os.path.realpath(os.path.abspath(path)))

    return norm(a) == norm(b)


def structure_problem(code_root: Path, environ: Mapping[str, str]) -> str | None:
    """Qué falla en la estructura de la carpeta del proyecto (RF-007-33), o ``None``: el
    código en ``layout.CODE_DIR_IN_DOCS`` (nombre exacto en el disco) directamente dentro
    de una carpeta con ``docs/constitution.md`` y una carpeta ``.git``; y
    ``GEOBLENDER_DOCS_DIR``, si está definida, es esa carpeta."""
    expected = (
        "la publicación espera el repositorio de código en la carpeta "
        f"«{layout.CODE_DIR_IN_DOCS}» (con esa mayúscula) directamente dentro de la "
        "carpeta del proyecto, que es la documentación: un repositorio git con "
        f"«{layout.DOCS_MARKER}»"
    )
    code_root = Path(code_root)
    parent = code_root.parent
    try:
        names = os.listdir(parent)
    except OSError as exc:
        return f"no se puede leer la carpeta madre del código «{parent}»: {exc}; {expected}"
    on_disk = [name for name in names if name.casefold() == code_root.name.casefold()]
    if on_disk != [layout.CODE_DIR_IN_DOCS]:
        shown = on_disk[0] if on_disk else code_root.name
        return f"el repositorio de código está en la carpeta «{shown}»: {expected}"
    if not (parent / layout.DOCS_MARKER).is_file():
        return f"la carpeta madre del código no tiene «{layout.DOCS_MARKER}»: {expected}"
    if not (parent / ".git").is_dir():
        return (
            "la carpeta madre del código no es un repositorio git (no tiene la carpeta "
            f".git): {expected}"
        )
    value = environ.get(layout.ENV_DOCS_DIR, "").strip().strip('"')
    if value and not same_path(value, parent):
        return (
            f"{layout.ENV_DOCS_DIR} apunta a «{value}», que no es la carpeta madre del "
            f"código («{parent}»): la publicación solo refleja la documentación que "
            "contiene al código; corrija la variable o bórrela"
        )
    return None


def resolve_destination(option: str | None, environ: Mapping[str, str]) -> Path | None:
    """El destino (RF-007-17): ``--destino`` o, si no se da, ``GEOBLENDER_NAS_ESPEJO``
    (sin espacios ni comillas alrededor; vacía no cuenta); ``None`` si no hay."""
    value = option if option else environ.get(layout.ENV_NAS_MIRROR, "")
    value = value.strip().strip('"').strip()
    return Path(value) if value else None


def root_problem(path: str) -> str | None:
    """Mirando solo el texto de ``path`` (sin buscar la unidad ni el servidor): si es la
    raíz de una unidad o de un recurso compartido, o la carpeta de expedientes de
    clientes o una de dentro (plan 007 §5.4.6)."""
    drive, _root, tail = ntpath.splitroot(path)
    parts = [part for part in _SEPARATORS.split(tail) if part]
    if not parts:
        return (
            f"«{path}» es la raíz de una unidad o de un recurso compartido: el espejo va "
            "en su propia carpeta"
        )
    names = [parts[0]]
    if drive.startswith(("\\\\", "//")):
        names.append(_SEPARATORS.split(drive.strip("\\/"))[-1])
    if any(name.casefold() == DOSSIER_FOLDER for name in names):
        return (
            f"«{path}» es la carpeta de expedientes de clientes o está dentro de ella: "
            "allí nunca se escribe"
        )
    return None


def _inside(path: str, folder: str) -> bool:
    return path.startswith(folder.rstrip("\\/") + os.sep)


def destination_problem(
    destination: Path, project: Path, base: safe_mirror.MirrorState | None
) -> str | None:
    """Por qué se rechaza el destino (RF-007-18; plan 007 §5.4.6), o ``None``: la raíz
    de una unidad o de un recurso, la carpeta de expedientes (por el texto y por la ruta
    real), la carpeta del proyecto, una de dentro o una que la contiene, uno que no
    existe o no es una carpeta, y uno sin ``docs/constitution.md`` que no es el primer
    espejo contra su foto. No escribe nada ni lanza git sobre el destino."""
    text = os.path.abspath(destination)
    problem = root_problem(text)
    if problem is not None:
        return problem
    real = os.path.realpath(text)
    problem = root_problem(real)
    if problem is not None:
        return problem
    folded = os.path.normcase(real)
    home = os.path.normcase(os.path.realpath(project))
    if folded == home:
        return f"«{destination}» es la carpeta del proyecto: el espejo es otra carpeta"
    if _inside(folded, home):
        return f"«{destination}» está dentro de la carpeta del proyecto"
    if _inside(home, folded):
        return f"«{destination}» contiene la carpeta del proyecto"
    if not os.path.lexists(real):
        return f"«{destination}» no existe (la publicación no crea el destino)"
    if not os.path.isdir(real):
        return f"«{destination}» no es una carpeta"
    if not (Path(real) / layout.DOCS_MARKER).is_file() and not (base is not None and base.photo):
        return (
            f"«{destination}» no tiene «{layout.DOCS_MARKER}»: no parece el espejo de la "
            "carpeta del proyecto, y no es el primer espejo contra su foto"
        )
    return None


def _when(taken: str) -> str:
    """``2026-10-05T23:09:01`` → ``05/10/2026 23:09`` (o el texto, si no es una fecha)."""
    try:
        return datetime.datetime.fromisoformat(taken).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return taken or "fecha desconocida"


def base_text(base: safe_mirror.MirrorState) -> str:
    """De dónde sale la comparación: «primer espejo, foto del …» o «estado del …»."""
    if base.photo:
        return f"primer espejo, foto del {_when(base.taken)}"
    return f"estado del {_when(base.taken)}"


def _status_line(entry: str) -> str:
    """``"XY ruta"`` de ``git.dirty_entries`` en palabras."""
    status, _sep, path = entry.partition(" ")
    if status == "??":
        return f"nuevo, sin commit ni ignorar: {path}"
    return f"cambiado sin commit ({status.strip()}): {path}"


def tree_problems(repo: Path, git_runner: blender.Runner) -> tuple[list[str], str | None]:
    """Lo que impide publicar desde el repositorio ``repo`` (RF-007-15): su ``.git``
    (fichero, ``alternates``), cambios sin commit y ficheros nuevos, operaciones a
    medias y cerrojos, y HEAD fuera de una rama (vacía si está limpio); y su rama."""
    problem = git.git_dir_problem(repo)
    if problem is not None:
        return [problem], None
    found = [_status_line(entry) for entry in git.dirty_entries(repo, runner=git_runner)]
    found += git.operations_in_progress(repo / ".git")
    branch = git.current_branch(repo, runner=git_runner)
    if branch is None:
        found.append(
            "HEAD no está en ninguna rama (está separado): cambie a la rama que quiere "
            "publicar"
        )
    return found, branch


def _seconds(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def stream_run(
    cmd: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Como ``gbtools.blender.run``, pero la salida de la orden (con sus errores) se ve
    en directo, línea a línea, sangrada, y se devuelve también. ``timeout`` no se
    aplica: cada comprobación tiene los suyos."""
    process = subprocess.Popen(
        [str(part) for part in cmd],
        env=dict(env) if env is not None else None,
        cwd=str(cwd) if cwd is not None else None,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    lines: list[str] = []
    assert process.stdout is not None
    with process.stdout:
        for line in process.stdout:
            lines.append(line)
            print(f"    │ {line.rstrip()}", flush=True)
    code = process.wait()
    return subprocess.CompletedProcess(list(cmd), code, "".join(lines), "")


def last_result(text: str) -> str:
    """La última línea «RESULTADO: …» de una salida (vacía si no hay)."""
    found = [line.strip() for line in text.splitlines() if line.strip().startswith(RESULT_PREFIX)]
    return found[-1] if found else ""


class Publication:
    """Una publicación: lo que se sabe en cada paso y sus líneas en la consola."""

    def __init__(
        self,
        options: Options,
        code_root: Path,
        environ: Mapping[str, str],
        git_runner: blender.Runner,
        runner: blender.Runner,
        locate: Callable[..., blender.BlenderInstall],
    ) -> None:
        self.options = options
        self.code = code_root
        self.project = code_root.parent
        self.environ = environ
        self.git_runner = git_runner
        self.runner = runner
        self.locate = locate
        self.dest: Path | None = None
        self.base: safe_mirror.MirrorState | None = None
        self.url: str | None = None
        self.pushed: str | None = None  # la rama subida, si se subió
        self.branches: dict[str, str | None] = {}  # la rama de cada repositorio
        self.started = time.perf_counter()
        self.step_started = self.started

    def line(self, status: str, step: str, detail: str = "") -> None:
        seconds = _seconds(time.perf_counter() - self.step_started)
        text = f"  {status:<8}  {step:<13} {seconds:>5} s"
        print(text + (f"  ({detail})" if detail else ""), flush=True)
        self.step_started = time.perf_counter()

    def elapsed(self) -> str:
        return _seconds(time.perf_counter() - self.started)

    # Paso 1 y 2: raíz y estructura.
    def check_structure(self) -> None:
        try:
            top = git.toplevel(self.code, runner=self.git_runner)
        except git.GitProblem as exc:
            raise Stop(EXIT_USAGE, STEP_STRUCTURE, str(exc)) from exc
        if not same_path(top, self.code):
            raise Stop(
                EXIT_USAGE,
                STEP_STRUCTURE,
                f"la raíz del código «{self.code}» no es la de su repositorio git "
                f"(«{top}»): ¿le falta su carpeta .git?",
            )
        problem = structure_problem(self.code, self.environ)
        if problem is not None:
            raise Stop(EXIT_USAGE, STEP_STRUCTURE, problem)
        self.line(
            STATUS_OK,
            STEP_STRUCTURE,
            f"código en {layout.CODE_DIR_IN_DOCS}\\ de la documentación",
        )

    # Paso 3: destino y base de la comparación.
    def check_destination(self) -> None:
        dest = resolve_destination(self.options.destination, self.environ)
        if dest is None:
            raise Stop(
                EXIT_USAGE,
                STEP_DEST,
                f"no hay destino: dé {OPTION_DEST} CARPETA o defina la variable de "
                f"usuario {layout.ENV_NAS_MIRROR} con la carpeta del espejo",
            )
        problem = root_problem(os.path.abspath(dest))
        if problem is not None:
            raise Stop(EXIT_USAGE, STEP_DEST, problem)
        try:
            base = safe_mirror.load_base(dest, self.environ)
        except safe_mirror.StateUnreadable as exc:
            raise Stop(
                EXIT_USAGE,
                STEP_DEST,
                f"{exc}; no se usa la foto en su lugar: {OPTION_REBUILD} lo rehace si "
                "nada del destino se pierde",
            ) from exc
        except safe_mirror.MirrorError as exc:
            raise Stop(EXIT_USAGE, STEP_DEST, str(exc)) from exc
        problem = destination_problem(dest, self.project, base)
        if problem is not None:
            raise Stop(EXIT_USAGE, STEP_DEST, problem)
        if base is None and not self.options.rebuild_state:
            folder = safe_mirror.state_dir(self.environ)
            raise Stop(
                EXIT_USAGE,
                STEP_DEST,
                f"no hay estado del último espejo de este destino ni su foto inicial (en "
                f"«{folder}»): {OPTION_REBUILD} lo rehace si nada del destino se pierde",
            )
        self.dest, self.base = dest, base
        self.line(
            STATUS_OK,
            STEP_DEST,
            base_text(base) if base is not None else "sin estado ni foto",
        )

    # Paso 4: el remoto del código y las credenciales de los dos .git/config.
    def check_remote(self) -> None:
        try:
            url = git.remote_url(self.code, runner=self.git_runner)
        except git.GitProblem as exc:
            raise Stop(EXIT_USAGE, STEP_REMOTE, str(exc)) from exc
        if url is None:
            raise Stop(
                EXIT_USAGE,
                STEP_REMOTE,
                f"el código no tiene el remoto «{git.REMOTE}»: no hay a dónde subir",
            )
        for label, repo, address in (
            (CODE_LABEL, self.code, url),
            (DOCS_LABEL, self.project, None),
        ):
            try:
                text = (repo / ".git" / "config").read_bytes().decode("utf-8", "replace")
            except OSError:
                text = ""
            problem = git.credential_problem(address, text)
            if problem is not None:
                raise Stop(
                    EXIT_USAGE,
                    STEP_REMOTE,
                    f"credenciales en la configuración de git de la {label}"
                    if label == DOCS_LABEL
                    else f"credenciales en la configuración de git del {label}",
                    [f"{label}: {problem}"],
                )
        self.url = url
        self.line(STATUS_OK, STEP_REMOTE, f"{git.REMOTE} = {url}; sin credenciales")

    # Paso 5: árboles (y otra vez tras las comprobaciones, que no deben cambiar nada).
    def check_trees(self, after_checks: bool = False) -> None:
        problems: list[str] = []
        try:
            for label, repo in ((CODE_LABEL, self.code), (DOCS_LABEL, self.project)):
                found, branch = tree_problems(repo, self.git_runner)
                problems += [f"{label}: {item}" for item in found]
                self.branches[label] = branch
            tracked = git.tracked_under(
                self.project, layout.CODE_DIR_IN_DOCS, runner=self.git_runner
            )
        except git.GitProblem as exc:
            raise Stop(EXIT_FAIL, STEP_TREES, str(exc)) from exc
        problems += [
            f"{DOCS_LABEL}: versiona «{path}», dentro de la carpeta del código: la "
            "documentación nunca versiona el repositorio anidado (git rm --cached)"
            for path in tracked
        ]
        if problems:
            count = "1 problema" if len(problems) == 1 else f"{len(problems)} problemas"
            if after_checks:
                detail = f"las comprobaciones cambiaron los árboles: {count}"
                advice = "Las comprobaciones no deben escribir en los repositorios: " \
                    "busque qué lo hizo, deshágalo y repita."
            else:
                detail = f"{count} en los árboles"
                advice = "Haga commit (o ignórelo) en su repositorio, termine o anule " \
                    "la operación a medias y repita."
            raise Stop(EXIT_FAIL, STEP_TREES, detail, [*problems, advice])
        if not after_checks:
            self.line(STATUS_OK, STEP_TREES, "los dos limpios")

    # Paso 8: comprobaciones.
    def _install(self) -> blender.BlenderInstall:
        path = self.code / layout.MANIFEST_RELPATH
        try:
            minimum = manifest.blender_min(manifest.load(path))
            return self.locate(minimum)
        except blender.EnvironmentProblem as exc:
            raise Stop(EXIT_USAGE, STEP_CHECK, str(exc)) from exc
        except (OSError, ValueError) as exc:  # también tomllib.TOMLDecodeError
            raise Stop(
                EXIT_USAGE,
                STEP_CHECK,
                f"no se puede leer «blender_version_min» de «{layout.MANIFEST_RELPATH}»: {exc}",
            ) from exc

    def _run_check(self, step: str, install: blender.BlenderInstall, *args: str) -> None:
        command = blender.python_cmd(install, *args)
        env = blender.python_env(self.code, self.environ)
        try:
            result = self.runner(command, env=env, cwd=self.code, timeout=CHECK_TIMEOUT_S)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise Stop(EXIT_FAIL, step, f"no se pudo ejecutar «{' '.join(command)}»: {exc}") from exc
        text = f"{result.stdout or ''}\n{result.stderr or ''}"
        verdict = last_result(text) or "sin línea «RESULTADO»"
        if result.returncode != 0:
            raise Stop(
                EXIT_FAIL,
                step,
                f"{args[0]} terminó con el código {result.returncode}: {verdict}",
                ["Corrija lo que dice su salida y repita."],
            )
        self.line(STATUS_OK, step, verdict)

    def run_checks(self) -> None:
        install = self._install()
        if self.options.mirror_only:
            self.line(
                STATUS_SKIPPED,
                STEP_CHECK,
                f"{OPTION_MIRROR_ONLY}: el código no se comprueba ni se sube",
            )
        else:
            self._run_check(STEP_CHECK, install, CHECK_SCRIPT)
        self._run_check(STEP_DOCS, install, DOCS_CHECK_SCRIPT, str(self.project))
        self.check_trees(after_checks=True)

    # Paso 9: la subida.
    def push(self) -> None:
        if self.options.mirror_only:
            return
        branch = self.branches.get(CODE_LABEL)
        if branch is None:  # los árboles lo comprueban antes
            raise Stop(EXIT_FAIL, STEP_PUSH, "HEAD del código no está en ninguna rama")
        try:
            result = git.push(self.code, branch, runner=self.git_runner)
        except git.GitProblem as exc:
            raise Stop(EXIT_FAIL, STEP_PUSH, f"{exc}; sin espejo") from exc
        if result.returncode != 0:
            output = [
                line.rstrip()
                for line in f"{result.stdout or ''}\n{result.stderr or ''}".splitlines()
                if line.strip()
            ]
            raise Stop(
                EXIT_FAIL,
                STEP_PUSH,
                f"git push terminó con el código {result.returncode}; sin espejo",
                [
                    *output,
                    "Si la rama de origin avanzó, traiga sus commits (git pull) y repita; "
                    "nunca se fuerza la subida.",
                ],
            )
        self.pushed = branch
        self.line(STATUS_OK, STEP_PUSH, f"{git.REMOTE} = {self.url}, {branch}")

    def run(self) -> int:
        self.check_structure()
        self.check_destination()
        self.check_remote()
        self.check_trees()
        self.run_checks()
        self.push()
        raise Stop(
            EXIT_FAIL,
            "publicación",
            "la publicación aún no hace el espejo (spec 007, T25 a T28)",
        )

    def done_note(self) -> str:
        """Qué se hizo antes de parar: nada, o la subida sin el espejo."""
        if self.pushed is not None:
            return (
                f"Se subió {self.pushed} a {git.REMOTE}; no se ha copiado nada: el destino "
                "sigue en el espejo anterior."
            )
        return NOTHING_DONE


def _print_stop(stop: Stop, publication: Publication | None) -> None:
    status = STATUS_STOP if stop.code == EXIT_CHANGES else STATUS_FAIL
    if publication is not None:
        publication.line(status, stop.step, stop.detail)
    else:
        print(f"  {status:<8}  {stop.step:<13}  ({stop.detail})")
    for item in stop.lines:
        print(f"    {item}")
    print(f"  {publication.done_note() if publication is not None else NOTHING_DONE}")
    elapsed = publication.elapsed() if publication is not None else "0,0"
    print(f"RESULTADO: NO PUBLICADO ({elapsed} s): {stop.detail}")


def main(
    argv: Sequence[str] | None = None,
    *,
    root: Path | None = None,
    environ: Mapping[str, str] | None = None,
    git_runner: blender.Runner = blender.run,
    runner: blender.Runner | None = None,
    locate: Callable[..., blender.BlenderInstall] = blender.locate_blender,
) -> int:
    """Publica y devuelve el código de salida. Los parámetros con nombre solo los
    cambian las pruebas: la raíz del código, el entorno (``GEOBLENDER_NAS_ESPEJO``,
    ``GEOBLENDER_DOCS_DIR``, ``LOCALAPPDATA``), el ejecutor de git, el de las
    comprobaciones y el localizador de Blender."""
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
            print(f"ERROR: {exc}", file=sys.stderr)
            return EXIT_USAGE
    code_root = Path(root).resolve()
    print(f"Geoblender · publicación · {code_root.parent}", flush=True)
    publication = Publication(
        options,
        code_root,
        environ,
        git_runner,
        stream_run if runner is None else runner,
        locate,
    )
    try:
        return publication.run()
    except Stop as stop:
        _print_stop(stop, publication)
        return stop.code


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(errors="replace")
    sys.exit(main())

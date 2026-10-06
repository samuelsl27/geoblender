# SPDX-License-Identifier: GPL-3.0-or-later
"""Lecturas de git para la publicación (spec 007; plan 007 §5.3 y §5.4.5).

Git es un programa del puesto (Git para Windows), lanzado como proceso: solo biblioteca
estándar (HER-01). Cada orden se lanza con ``cwd`` = la raíz del repositorio, un tiempo
máximo y ``GIT_TERMINAL_PROMPT=0`` (nunca pregunta nada), y sin las variables que harían
que git mirase otro repositorio (``GIT_DIR``, ``GIT_WORK_TREE``, ``GIT_INDEX_FILE``…).
Las lecturas, además, con ``GIT_OPTIONAL_LOCKS=0``: un ``git status`` normal reescribe
``.git/index`` si puede tomar su cerrojo, y en el NAS ese cambio pararía el siguiente
espejo (plan 007 §2.1, 16; ``docs/trampas.md`` §7 de la documentación).

:func:`git_dir_problem` y :func:`operations_in_progress` miran ficheros de ``.git`` sin
lanzar git. Un fallo es :class:`GitProblem`, con un mensaje en español. Las pruebas
inyectan el ejecutor (``runner``, con la firma de ``gbtools.blender.run``).
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .blender import Runner, run

GIT = "git"
GIT_TIMEOUT_S = 120.0
INSTALL_HINT = "instale Git para Windows (https://git-scm.com/download/win)"
ENV_OPTIONAL_LOCKS = "GIT_OPTIONAL_LOCKS"
ENV_TERMINAL_PROMPT = "GIT_TERMINAL_PROMPT"
# Las que cambian el repositorio sobre el que trabaja git: nunca se heredan.
REPOSITORY_VARIABLES: tuple[str, ...] = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_NAMESPACE",
    "GIT_PREFIX",
)
GITLINK_MODE = "160000"
REMOTE = "origin"

# Operaciones a medias en un .git (nombre → qué es).
_IN_PROGRESS: tuple[tuple[str, str], ...] = (
    ("MERGE_HEAD", "una fusión a medias"),
    ("REBASE_HEAD", "un rebase a medias"),
    ("rebase-merge", "un rebase a medias"),
    ("rebase-apply", "un rebase o un «git am» a medias"),
    ("CHERRY_PICK_HEAD", "una selección de commits a medias"),
    ("REVERT_HEAD", "una reversión a medias"),
    ("BISECT_LOG", "una bisección a medias"),
    ("gc.pid", "un mantenimiento de git (gc) en curso"),
)
_LOOSE_OBJECTS = re.compile(r"^[0-9a-f]{2}$")


class GitProblem(Exception):
    """Git no está, o una orden de git falló: el mensaje dice cuál y por qué."""


def git_env(
    base: Mapping[str, str] | None = None, *, write: bool = False
) -> dict[str, str]:
    """El entorno de una orden de git: copia de ``base`` (por defecto, el del proceso)
    sin ``REPOSITORY_VARIABLES``, con ``GIT_TERMINAL_PROMPT=0`` y, salvo que la orden
    escriba (``write``), ``GIT_OPTIONAL_LOCKS=0``."""
    env = dict(os.environ if base is None else base)
    for name in list(env):
        if name.upper() in REPOSITORY_VARIABLES:
            del env[name]
    env[ENV_TERMINAL_PROMPT] = "0"
    if write:
        env.pop(ENV_OPTIONAL_LOCKS, None)
    else:
        env[ENV_OPTIONAL_LOCKS] = "0"
    return env


def _git(
    root: Path,
    args: Sequence[str],
    runner: Runner,
    *,
    accept: tuple[int, ...] = (0,),
    write: bool = False,
) -> subprocess.CompletedProcess[str]:
    """``git <args>`` en ``root``; :class:`GitProblem` si no se puede lanzar, se agota el
    tiempo o termina con un código que no está en ``accept``."""
    command = [GIT, *args]
    shown = " ".join(command)
    env = git_env(write=write)
    try:
        result = runner(command, env=env, cwd=Path(root), timeout=GIT_TIMEOUT_S)
    except OSError as exc:
        raise GitProblem(f"no se pudo ejecutar «{shown}»: {exc}; {INSTALL_HINT}") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitProblem(
            f"«{shown}» en «{root}» no terminó en {GIT_TIMEOUT_S:.0f} s"
        ) from exc
    if result.returncode not in accept:
        output = (result.stderr or result.stdout or "").strip()
        raise GitProblem(
            f"«{shown}» en «{root}» terminó con el código {result.returncode}"
            + (f": {output}" if output else "")
        )
    return result


def toplevel(root: Path, runner: Runner = run) -> Path:
    """La raíz del árbol de trabajo del repositorio que contiene ``root``."""
    out = _git(root, ["rev-parse", "--show-toplevel"], runner).stdout.strip()
    return Path(out).resolve()


def git_dir_problem(root: Path) -> str | None:
    """Qué impide publicar desde el ``.git`` de ``root``, sin lanzar git: que no
    exista, que sea un fichero (un *worktree* enlazado o un submódulo: los objetos y la
    configuración están en otra parte) o que tome objetos de otro repositorio
    (``objects/info/alternates``); ``None`` si nada."""
    git_dir = Path(root) / ".git"
    if not os.path.lexists(git_dir):
        return f"«{root}» no es un repositorio git: no tiene la carpeta .git"
    if not git_dir.is_dir():
        return (
            "«.git» es un fichero: es un worktree enlazado o un submódulo, y su historial "
            "está en otro repositorio; publique desde el repositorio principal"
        )
    if (git_dir / "objects" / "info" / "alternates").exists():
        return (
            "toma objetos de otro repositorio (.git/objects/info/alternates): una copia "
            "de ese .git no tendría todo su historial"
        )
    return None


def head(root: Path, runner: Runner = run) -> str:
    """El commit de ``HEAD`` (40 caracteres hexadecimales)."""
    args = ["rev-parse", "--verify", "--quiet", "HEAD^{commit}"]
    return _git(root, args, runner).stdout.strip()


def current_branch(root: Path, runner: Runner = run) -> str | None:
    """La rama de ``HEAD``, o ``None`` si está separado de toda rama."""
    args = ["symbolic-ref", "--quiet", "--short", "HEAD"]
    result = _git(root, args, runner, accept=(0, 1))
    name = result.stdout.strip()
    return name if result.returncode == 0 and name else None


def dirty_entries(root: Path, runner: Runner = run) -> list[str]:
    """Lo que no está en el último commit (``git status --porcelain -z``, con cada
    fichero nuevo aunque esté en una carpeta nueva): ``"XY ruta"``, y un renombrado,
    ``"XY nueva (antes vieja)"``. Vacía si el árbol está limpio."""
    args = ["status", "--porcelain=v1", "-z", "--untracked-files=all"]
    tokens = _git(root, args, runner).stdout.split("\0")
    entries: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if not token:
            continue
        status, path = token[:2], token[3:]
        if status[0] in "RC" and index < len(tokens):
            entries.append(f"{status} {path} (antes {tokens[index]})")
            index += 1
        else:
            entries.append(f"{status} {path}")
    return entries


@dataclass(frozen=True)
class TreeStatus:
    """Lo que dice ``git status`` de un repositorio: su rama (``None`` si HEAD está
    separado), su commit (``None`` sin commits) y los cambios como en
    :func:`dirty_entries`."""

    branch: str | None
    commit: str | None
    entries: list[str]


_DETACHED = "(detached)"
_INITIAL = "(initial)"


def _v2_status(xy: str) -> str:
    """El estado ``XY`` de v2 (``.`` = sin cambio) como en v1 (espacio)."""
    return xy.replace(".", " ")


def tree_status(root: Path, runner: Runner = run) -> TreeStatus:
    """Rama, commit y cambios de ``root`` en una sola orden (``git status
    --porcelain=v2 --branch -z --untracked-files=all``, sin cerrojos opcionales): lo
    mismo que :func:`current_branch`, :func:`head` y :func:`dirty_entries` con un
    proceso de git en lugar de tres."""
    args = ["status", "--porcelain=v2", "--branch", "-z", "--untracked-files=all"]
    tokens = _git(root, args, runner).stdout.split("\0")
    branch: str | None = None
    commit: str | None = None
    entries: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if not token:
            continue
        if token.startswith("# branch.oid "):
            value = token[len("# branch.oid ") :].strip()
            commit = None if value == _INITIAL else value
        elif token.startswith("# branch.head "):
            value = token[len("# branch.head ") :].strip()
            branch = None if value == _DETACHED else value
        elif token.startswith("#"):
            continue
        elif token.startswith("1 "):
            fields = token.split(" ", 8)
            entries.append(f"{_v2_status(fields[1])} {fields[8]}")
        elif token.startswith("2 "):
            fields = token.split(" ", 9)
            original = tokens[index] if index < len(tokens) else ""
            index += 1
            entries.append(f"{_v2_status(fields[1])} {fields[9]} (antes {original})")
        elif token.startswith("u "):
            fields = token.split(" ", 10)
            entries.append(f"{_v2_status(fields[1])} {fields[10]}")
        elif token.startswith("? "):
            entries.append(f"?? {token[2:]}")
    return TreeStatus(branch, commit, entries)


def operations_in_progress(git_dir: Path) -> list[str]:
    """Operaciones de git a medias en ``git_dir`` (fusión, rebase, selección de
    commits, reversión, bisección, ``gc`` en curso) y cualquier cerrojo ``*.lock``
    (también en ``refs/`` o ``objects/info/``); sin lanzar git."""
    folder = Path(git_dir)
    found = [
        f"{what} ({name})" for name, what in _IN_PROGRESS if (folder / name).exists()
    ]
    for current, dirs, files in os.walk(folder):
        here = Path(current)
        if here == folder / "objects":
            dirs[:] = [name for name in dirs if not _LOOSE_OBJECTS.match(name)]
        for name in sorted(files):
            if name.endswith(".lock"):
                rel = (here / name).relative_to(folder).as_posix()
                found.append(f"un cerrojo de git ({rel}): otro git está trabajando")
    return found


def remote_url(root: Path, name: str = REMOTE, runner: Runner = run) -> str | None:
    """La dirección del remoto ``name`` tal como está en la configuración, o ``None``
    si no existe."""
    args = ["config", "--get", f"remote.{name}.url"]
    result = _git(root, args, runner, accept=(0, 1))
    url = result.stdout.strip()
    return url if result.returncode == 0 and url else None


_URL_IN_TEXT = re.compile(r"(?i)\b[a-z][a-z0-9+.\-]*://[^\s\"'<>]+")
_URL_PARTS = re.compile(r"(?i)^([a-z][a-z0-9+.\-]*)://([^/?#]*)")
_EXTRA_HEADER = re.compile(r"(?i)^\s*extraheader\s*=")
SSH_USER = "git"


def _url_has_credentials(url: str) -> bool:
    """Si ``url`` lleva un secreto: usuario con contraseña (o token) en cualquier
    esquema, o, en http(s), un usuario que no es «git» (un token como usuario). La
    forma ``git@servidor:ruta`` de SSH no tiene dónde llevar contraseña."""
    match = _URL_PARTS.match(url.strip())
    if match is None:
        return False
    scheme, authority = match.group(1).lower(), match.group(2)
    if "@" not in authority:
        return False
    userinfo = authority.rsplit("@", 1)[0]
    if ":" in userinfo:
        return True
    return scheme in ("http", "https") and userinfo.casefold() != SSH_USER


def credential_problem(url: str | None, config_text: str) -> str | None:
    """Dónde hay credenciales (RF-007-19), sin mostrarlas: en la dirección ``url`` (la
    de ``origin``), o en cualquier dirección del texto de un ``.git/config``
    (``remote.*.url``, ``url.<…>.insteadOf``…) o una cabecera ``http.*.extraHeader``,
    con su línea. ``None`` si no hay. No lanza git: lee el texto."""
    if url is not None and _url_has_credentials(url):
        return (
            "la dirección de «origin» lleva credenciales (usuario con contraseña o token): "
            "quítelas (git remote set-url origin <dirección sin usuario>) y guárdelas en "
            "el gestor de credenciales (gh auth setup-git)"
        )
    for number, line in enumerate(config_text.splitlines(), start=1):
        if _EXTRA_HEADER.match(line):
            return (
                f".git/config, línea {number}: una cabecera de autorización "
                "(http.extraHeader); quítela: el espejo copiaría el .git al NAS"
            )
        if any(_url_has_credentials(found) for found in _URL_IN_TEXT.findall(line)):
            return (
                f".git/config, línea {number}: una dirección con credenciales (usuario con "
                "contraseña o token); quítelas: el espejo copiaría el .git al NAS"
            )
    return None


def push(root: Path, branch: str, runner: Runner = run) -> subprocess.CompletedProcess[str]:
    """Sube la rama ``branch`` a la misma rama de ``origin`` con sus etiquetas anotadas
    (``--follow-tags``), sin forzar: nunca ``--force``, ``--mirror``, ``--all`` ni una
    referencia con «+» (RF-007-20). Devuelve el resultado de git, también si falla (la
    publicación lo muestra); :class:`GitProblem` solo si no se puede lanzar."""
    refspec = f"refs/heads/{branch}:refs/heads/{branch}"
    args = ["push", "--follow-tags", "--porcelain", REMOTE, refspec]
    return _git(root, args, runner, accept=tuple(range(256)), write=True)


def ahead_of_remote(root: Path, branch: str, runner: Runner = run) -> int | None:
    """Commits de ``branch`` que ``refs/remotes/origin/<branch>`` no tiene, según el
    repositorio (sin red); ``None`` si no hay esa referencia."""
    remote_ref = f"refs/remotes/{REMOTE}/{branch}"
    args = ["rev-parse", "--verify", "--quiet", remote_ref]
    if _git(root, args, runner, accept=(0, 1)).returncode != 0:
        return None
    span = f"{remote_ref}..refs/heads/{branch}"
    count = _git(root, ["rev-list", "--count", span], runner).stdout.strip()
    try:
        return int(count)
    except ValueError as exc:
        message = f"«git rev-list --count {span}» no dio un número: «{count}»"
        raise GitProblem(message) from exc


def tracked_under(root: Path, folder: str, runner: Runner = run) -> list[str]:
    """Lo que el índice de ``root`` versiona en ``folder`` o debajo, sin distinguir
    mayúsculas (como Windows): las rutas, y un repositorio anidado añadido con
    ``git add -f`` (un *gitlink*, modo 160000), con «(gitlink)»."""
    wanted = folder.strip("/").casefold()
    found: list[str] = []
    for token in _git(root, ["ls-files", "-s", "-z"], runner).stdout.split("\0"):
        if "\t" not in token:
            continue
        info, path = token.split("\t", 1)
        if path.casefold() != wanted and not path.casefold().startswith(wanted + "/"):
            continue
        mode = info.split(" ", 1)[0]
        found.append(f"{path} (gitlink)" if mode == GITLINK_MODE else path)
    return found

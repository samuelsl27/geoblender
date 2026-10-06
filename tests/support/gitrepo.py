# SPDX-License-Identifier: GPL-3.0-or-later
"""Repositorios git temporales para las pruebas de la spec 007 (plan 007 §6 y §7.1).

Una carpeta del proyecto como la del PC (la documentación, con su git y
``docs/constitution.md``, que ignora la carpeta del código; dentro, en ``Geoblender/``,
el código, con su git) y un remoto desnudo, todo en ``%TEMP%``. Se construye una vez
por proceso (:func:`shared_template`, la primera clase que la pide; se borra al
terminar) y cada prueba trabaja en una copia (:meth:`GitTemplate.project`), con el remoto
del código apuntando a su propio remoto.

La configuración de git está aislada (:func:`isolated_env`): ``GIT_CONFIG_GLOBAL`` es un
fichero vacío de la copia, ``GIT_CONFIG_NOSYSTEM=1``, ``HOME`` y ``XDG_CONFIG_HOME`` en la
copia, y fuera las demás variables ``GIT_*`` del puesto; lo que hace falta va por
entorno (``GIT_CONFIG_COUNT``): rama inicial ``main``, identidad y fechas fijas, sin
firmas, sin ayudante de credenciales, ``gc.auto=0`` y ``maintenance.auto=false`` (ningún
git se queda trabajando en segundo plano). ``GIT_TERMINAL_PROMPT=0``: nunca pregunta.
Así ninguna prueba lee la configuración de git del usuario ni la del sistema (Git para
Windows trae, por ejemplo, ``core.autocrlf=true`` y su gestor de credenciales).

Sin git, las pruebas se omiten con el recurso ``git`` (:data:`GIT`,
``tests.support.resources``).
"""

from __future__ import annotations

import atexit
import functools
import os
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from tests.support import resources
from tests.support.repo import tools_on_path

tools_on_path()

from gbtools import blender, layout  # noqa: E402

GIT = "git"  # el recurso de tests.support.resources
GIT_HINT = "instale Git para Windows"
GIT_TIMEOUT_S = 60.0
BRANCH = "main"
IDENTITY: tuple[str, str] = ("Pruebas de Geoblender", "pruebas@geoblender.invalid")
DATE = "2026-10-05T12:00:00+02:00"
# Configuración de las pruebas, por entorno (GIT_CONFIG_COUNT): manda sobre la del
# repositorio y no la escribe ningún fichero.
CONFIG: tuple[tuple[str, str], ...] = (
    ("init.defaultBranch", BRANCH),
    ("user.name", IDENTITY[0]),
    ("user.email", IDENTITY[1]),
    ("commit.gpgSign", "false"),
    ("tag.gpgSign", "false"),
    ("credential.helper", ""),
    ("core.autocrlf", "false"),
    ("core.fsmonitor", "false"),
    ("gc.auto", "0"),
    ("maintenance.auto", "false"),
)
# Las que pone gbtools.git en cada orden: se conservan.
KEPT_VARIABLES: frozenset[str] = frozenset({"GIT_OPTIONAL_LOCKS", "GIT_TERMINAL_PROMPT"})
GLOBAL_CONFIG = "gitconfig-vacio"
DOCS_FOLDER = "proyecto"
REMOTE_FOLDER = "remoto.git"

# Ficheros de cada repositorio de la plantilla (texto UTF-8 y LF).
SPDX = "# SPDX-License-Identifier: GPL-3.0-or-later\n"
DOCS_FILES: Mapping[str, str] = {
    layout.DOCS_MARKER: "# Constitución\n",
    "README.md": "# Documentación de prueba\n",
    ".gitignore": f"/{layout.CODE_DIR_IN_DOCS}/\n",
}
CODE_FILES: Mapping[str, str] = {
    layout.MANIFEST_RELPATH: (
        f'schema_version = "1.0.0"\nid = "{layout.EXTENSION_DIR}"\n'
        'blender_version_min = "5.2.0"\n'
    ),
    f"{layout.EXTENSION_DIR}/__init__.py": SPDX,
    layout.CHECK_RELPATH: SPDX,
    "README.md": "# Código de prueba\n",
    ".gitignore": "__pycache__/\n/dist/\n/.deps/\n",
}


@functools.lru_cache(maxsize=1)
def git_available() -> bool:
    """Si ``git`` está en el ``PATH`` y responde a ``git --version``."""
    if shutil.which(GIT) is None:
        return False
    try:
        result = blender.run([GIT, "--version"], timeout=GIT_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


resources.register_resource(GIT, git_available)


def isolated_env(base: Mapping[str, str] | None, home: Path) -> dict[str, str]:
    """Copia de ``base`` (por defecto, el entorno del proceso) para git: sin las
    variables ``GIT_*`` del puesto (salvo las de ``gbtools.git``), con la configuración
    global vacía de ``home``, sin la de sistema y con la de las pruebas por entorno."""
    source = os.environ if base is None else base
    env = {
        name: value
        for name, value in source.items()
        if not name.upper().startswith("GIT_") or name.upper() in KEPT_VARIABLES
    }
    env.pop("SSH_ASKPASS", None)
    env.update(
        {
            "GIT_CONFIG_GLOBAL": str(home / GLOBAL_CONFIG),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CEILING_DIRECTORIES": str(home.parent),
            "GCM_INTERACTIVE": "never",
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home),
            "GIT_AUTHOR_DATE": DATE,
            "GIT_COMMITTER_DATE": DATE,
            "GIT_CONFIG_COUNT": str(len(CONFIG)),
        }
    )
    for number, (key, value) in enumerate(CONFIG):
        env[f"GIT_CONFIG_KEY_{number}"] = key
        env[f"GIT_CONFIG_VALUE_{number}"] = value
    return env


def _remove_readonly(func: Callable[..., object], path: str, _exc: BaseException) -> None:
    os.chmod(path, stat.S_IWRITE)  # git deja de solo lectura sus objetos
    func(path)


def remove_tree(folder: Path) -> None:
    """Borra ``folder`` entera, también los ficheros de solo lectura de ``.git``."""
    shutil.rmtree(folder, onexc=_remove_readonly)


def _write(root: Path, files: Mapping[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        if not path.parent.is_dir():
            path.parent.mkdir(parents=True)
        path.write_bytes(text.encode("utf-8"))


def _remote_config(remote: Path) -> str:
    """La parte de ``.git/config`` del código que dejan ``git remote add origin`` y
    ``git push -u origin main``: el remoto y la rama que sigue."""
    return (
        f'[remote "origin"]\n\turl = {remote.as_posix()}\n'
        "\tfetch = +refs/heads/*:refs/remotes/origin/*\n"
        f'[branch "{BRANCH}"]\n\tremote = origin\n\tmerge = refs/heads/{BRANCH}\n'
    )


@dataclass(frozen=True)
class GitProject:
    """Una copia de la plantilla: ``base`` (la carpeta temporal, que hace de ``HOME``),
    ``docs`` (la carpeta del proyecto, la documentación), ``code`` (el código, dentro)
    y ``remote`` (el remoto desnudo del código)."""

    base: Path

    @property
    def docs(self) -> Path:
        return self.base / DOCS_FOLDER

    @property
    def code(self) -> Path:
        return self.docs / layout.CODE_DIR_IN_DOCS

    @property
    def remote(self) -> Path:
        return self.base / REMOTE_FOLDER

    @property
    def global_config(self) -> Path:
        return self.base / GLOBAL_CONFIG

    def env(self, base: Mapping[str, str] | None = None) -> dict[str, str]:
        """El entorno aislado de git de esta copia (:func:`isolated_env`)."""
        return isolated_env(base, self.base)

    def git(
        self, repo: Path, *args: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        """``git <args>`` en ``repo`` con el entorno aislado; con ``check``, un código
        distinto de 0 es un ``AssertionError`` con la salida."""
        result = blender.run(
            [GIT, *args], env=self.env(), cwd=repo, timeout=GIT_TIMEOUT_S
        )
        if check and result.returncode != 0:
            raise AssertionError(
                f"git {' '.join(args)} en «{repo}» terminó con {result.returncode}:\n"
                f"{result.stdout}{result.stderr}"
            )
        return result

    def runner(self) -> blender.Runner:
        """Un ejecutor de órdenes para ``gbtools.git`` (y la publicación): el de
        ``gbtools.blender`` con el entorno de cada orden aislado."""

        def run_isolated(
            cmd: Sequence[str],
            *,
            env: Mapping[str, str] | None = None,
            cwd: Path | None = None,
            timeout: float | None = None,
        ) -> subprocess.CompletedProcess[str]:
            return blender.run(cmd, env=self.env(env), cwd=cwd, timeout=timeout)

        return run_isolated

    def close(self) -> None:
        """Borra la copia."""
        remove_tree(self.base)


class GitTemplate:
    """La carpeta del proyecto de prueba, construida una vez; cada prueba trabaja en su
    copia (:meth:`project`). :meth:`close` la borra. Las clases de pruebas usan
    :func:`shared_template` (una sola por proceso)."""

    def __init__(self) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="geoblender-git-plantilla-")).resolve()
        try:
            self._build(GitProject(self.base))
        except BaseException:
            remove_tree(self.base)
            raise

    @staticmethod
    def _build(project: GitProject) -> None:
        project.global_config.write_bytes(b"")
        _write(project.docs, DOCS_FILES)
        _write(project.code, CODE_FILES)
        repos = ((project.docs, "docs: inicial"), (project.code, "chore: inicial"))
        for repo, message in repos:
            project.git(repo, "init", "-q", "-b", BRANCH)
            project.git(repo, "add", "-A")
            project.git(repo, "commit", "-q", "-m", message)
        # El remoto desnudo con lo que dejaría «git push -u origin main»: los objetos y
        # las referencias del código, y en el código su remoto y la rama que sigue. Se
        # escribe en lugar de subir: la subida cuesta unos 0,2 s en Windows (RNF-007-01).
        code_git, remote = project.code / ".git", project.remote
        for name in ("objects", "refs"):
            shutil.copytree(code_git / name, remote / name)
        (remote / "HEAD").write_bytes(f"ref: refs/heads/{BRANCH}\n".encode())
        (remote / "config").write_bytes(
            b"[core]\n\trepositoryformatversion = 0\n\tfilemode = false\n\tbare = true\n"
        )
        branch_ref = (code_git / "refs" / "heads" / BRANCH).read_bytes()
        _write(code_git, {f"refs/remotes/origin/{BRANCH}": branch_ref.decode("ascii")})
        config = code_git / "config"
        config.write_bytes(config.read_bytes() + _remote_config(remote).encode("utf-8"))

    def project(self) -> GitProject:
        """Una copia nueva de la plantilla, con el remoto del código en su propio remoto
        desnudo (nunca en el de la plantilla): la dirección se cambia en el texto de su
        ``.git/config`` (lo que haría ``git remote set-url``, sin lanzar git)."""
        base = Path(tempfile.mkdtemp(prefix="geoblender-git-")).resolve()
        copy = GitProject(base)
        try:
            shutil.copytree(self.base, base, dirs_exist_ok=True)
            config = copy.code / ".git" / "config"
            text = config.read_bytes().decode("utf-8")
            old, new = _remote_config(self.base / REMOTE_FOLDER), _remote_config(copy.remote)
            if old not in text:
                raise AssertionError(f"«{config}» no tiene el remoto de la plantilla")
            config.write_bytes(text.replace(old, new).encode("utf-8"))
        except BaseException:
            remove_tree(base)
            raise
        return copy

    def close(self) -> None:
        remove_tree(self.base)


@functools.lru_cache(maxsize=1)
def shared_template() -> GitTemplate:
    """La plantilla de este proceso: se construye la primera vez que la pide una clase
    de pruebas (en su ``setUpClass``, ya con git disponible) y se borra al terminar el
    proceso. Construirla cuesta unas 8 órdenes de git (unos 0,4 s en Windows): una sola
    para todas las clases ahorra ese tiempo en cada una (RNF-007-01; plan 007 §7.1).
    Nadie la cambia: cada prueba trabaja en su copia (:meth:`GitTemplate.project`)."""
    template = GitTemplate()
    atexit.register(_close_quietly, template)
    return template


def _close_quietly(template: GitTemplate) -> None:
    try:
        template.close()
    except OSError:
        pass

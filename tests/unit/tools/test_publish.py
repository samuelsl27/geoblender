# SPDX-License-Identifier: GPL-3.0-or-later
"""La publicación, ``tools/publish.py`` (spec 007, HU-007-4 y HU-007-7; plan 007 §5.4.5).

Casi todas las pruebas trabajan sobre una carpeta del proyecto temporal escrita a mano
(la documentación con ``docs/constitution.md`` y su ``.git``, y dentro el código con el
suyo) y un ejecutor de git simulado (:class:`FakeGit`) que responde como git sin
lanzarlo: así cuestan milisegundos (RNF-007-01). Las de extremo a extremo
(:class:`EndToEndTest`) usan git de verdad sobre una copia de la plantilla de
``tests.support.gitrepo`` (la documentación, el código anidado y un remoto desnudo en
``%TEMP%``), construida una vez por proceso, con la configuración de git aislada.

Ninguna prueba lee ``GEOBLENDER_NAS_ESPEJO``, ``GEOBLENDER_DOCS_DIR`` ni ``LOCALAPPDATA``
del puesto: cada una pasa su entorno a ``publish.main`` (``test_main_always_with_environ``
lo comprueba), con el perfil local en su carpeta temporal. Ninguna escribe fuera de
ella: ni GitHub, ni el NAS, ni el estado real del espejo.
"""

import ast
import contextlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from tests.support import gitrepo, mirror
from tests.support.repo import tools_on_path
from tests.support.resources import requires

tools_on_path()

import publish  # noqa: E402
from gbtools import layout, safe_mirror  # noqa: E402
from gbtools import repo as gbrepo  # noqa: E402
from gbtools.blender import BlenderInstall, EnvironmentProblem  # noqa: E402

CODE = layout.CODE_DIR_IN_DOCS
SHA_CODE = "c" * 40
SHA_DOCS = "d" * 40
DOCS_BRANCH = "docs/rama"
CODE_BRANCH = "main"
CODE_URL = "https://github.invalid/pruebas/codigo.git"
SPDX = "# SPDX-License-Identifier: GPL-3.0-or-later\n"
NOT_PUBLISHED = "RESULTADO: NO PUBLICADO"
CHANGES = "RESULTADO: CAMBIOS EN EL DESTINO"

# La carpeta del proyecto de prueba (texto UTF-8 y LF): la documentación y, dentro, el
# código, cada uno con un .git mínimo escrito a mano (FakeGit responde por git). Solo lo
# que la publicación necesita: cada fichero cuesta al escribirlo, compararlo y copiarlo
# (RNF-007-01).
DOCS_FILES: Mapping[str, str] = {
    layout.DOCS_MARKER: "# Constitución\n",
    ".git/config": "[core]\n\tbare = false\n",
}
CODE_FILES: Mapping[str, str] = {
    layout.MANIFEST_RELPATH: 'schema_version = "1.0.0"\nblender_version_min = "5.2.0"\n',
    layout.CHECK_RELPATH: SPDX,
    ".git/config": f'[core]\n\tbare = false\n[remote "origin"]\n\turl = {CODE_URL}\n',
}
# Unas comprobaciones en rojo: las pruebas de los pasos de antes paran ahí, sin subir ni
# hacer el espejo.
STOP_AT_CHECK = (1, "RESULTADO: NO VERDE (prueba)\n")

Answer = tuple[int, str] | tuple[int, str, str]
CHECK_GREEN = "RESULTADO: VERDE (1,0 s)\n"
DOCS_GREEN = "RESULTADO: DOCUMENTACIÓN CORRECTA (3 ficheros, 0,0 s)\n"
FAKE_BLENDER = Path(tempfile.gettempdir()) / "geoblender-falso" / "Blender"
INSTALL = BlenderInstall(
    exe=FAKE_BLENDER / "blender.exe",
    python=FAKE_BLENDER / "5.2" / "python" / "bin" / "python.exe",
    version=(5, 2, 1),
)


def fake_locate(minimum: tuple[int, int, int]) -> BlenderInstall:
    """El localizador de Blender de las pruebas: nunca busca el Blender del puesto."""
    return INSTALL


class FakeChecks:
    """Ejecutor simulado de las comprobaciones (``tools/check.py`` y
    ``tools/check_docs.py``): responde con ``check`` o ``docs`` y anota cada orden con
    su carpeta de trabajo."""

    def __init__(
        self,
        check: tuple[int, str] = (0, CHECK_GREEN),
        docs: tuple[int, str] = (0, DOCS_GREEN),
        during_check: Callable[[], None] | None = None,
    ) -> None:
        self.check, self.docs = check, docs
        self.during_check = during_check  # lo que pasa mientras corre tools/check.py
        self.calls: list[tuple[list[str], Path | None]] = []

    def __call__(
        self,
        cmd: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: Path | None = None,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        parts = [str(part) for part in cmd]
        self.calls.append((parts, cwd))
        is_docs = "tools/check_docs.py" in parts
        if not is_docs and self.during_check is not None:
            self.during_check()
        code, out = self.docs if is_docs else self.check
        return subprocess.CompletedProcess(parts, code, out, "")

    def scripts(self) -> list[str]:
        return [next(p for p in cmd if p.startswith("tools/")) for cmd, _cwd in self.calls]


DETACHED = "(detached)"


def status_v2(branch: str, commit: str, entries: str = "") -> str:
    """La salida de ``git status --porcelain=v2 --branch -z --untracked-files=all`` con
    ``branch`` (o ``DETACHED``), ``commit`` y unos cambios escritos en la forma corta
    de v1 (``" M ruta"``, ``"R  nueva\\0vieja"``, ``"?? ruta"``, separados por NUL)."""
    sha, modes = "e" * 40, "N... 100644 100644 100644"
    lines = [f"# branch.oid {commit}", f"# branch.head {branch}"]
    tokens = [token for token in entries.split("\0")]
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if not token:
            continue
        xy, path = token[:2], token[3:]
        if xy == "??":
            lines.append(f"? {path}")
        elif xy[0] in "RC":
            lines.append(f"2 {xy.replace(' ', '.')} {modes} {sha} {sha} R100 {path}")
            lines.append(tokens[index])
            index += 1
        else:
            lines.append(f"1 {xy.replace(' ', '.')} {modes} {sha} {sha} {path}")
    return "\0".join(lines) + "\0"


class FakeGit:
    """Ejecutor de git simulado: responde como git en la documentación («docs») o en el
    código («code», la carpeta ``CODE``), con respuestas por defecto de dos árboles
    limpios en una rama y las de ``overrides`` (``(repositorio o «*», prefijo de la
    orden)`` → ``(código, salida[, error])``, o una lista de respuestas que se dan por
    orden, la última para siempre), y anota cada orden. La salida de ``status`` se da
    con los cambios en la forma corta de v1 (``" M ruta"``): se responde en v2, con la
    rama y el commit del repositorio (:func:`status_v2`); una que empieza por «#» va tal
    cual."""

    def __init__(
        self, overrides: Mapping[tuple[str, str], Answer | list[Answer]] | None = None
    ) -> None:
        self.overrides = {key: value for key, value in (overrides or {}).items()}
        self.calls: list[tuple[str, list[str]]] = []

    @staticmethod
    def repo_of(cwd: Path | None) -> str:
        return "code" if cwd is not None and Path(cwd).name == CODE else "docs"

    def defaults(self, repo: str, cwd: Path | None) -> Mapping[str, Answer]:
        code = repo == "code"
        return {
            "rev-parse --show-toplevel": (0, f"{cwd}\n"),
            "symbolic-ref": (0, f"{CODE_BRANCH if code else DOCS_BRANCH}\n"),
            "rev-parse --verify --quiet HEAD": (0, f"{SHA_CODE if code else SHA_DOCS}\n"),
            "status": (0, ""),
            "config --get remote.origin.url": (0, f"{CODE_URL}\n") if code else (1, ""),
            "ls-files": (0, ""),
            "rev-parse --verify --quiet refs/remotes/origin/": (0, f"{SHA_CODE}\n"),
            "rev-list --count": (0, "0\n"),
        }

    def __call__(
        self,
        cmd: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: Path | None = None,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        parts = [str(part) for part in cmd]
        repo = self.repo_of(cwd)
        self.calls.append((repo, parts))
        key = " ".join(parts[1:])
        answer: Answer = (0, "")
        found = False
        for (who, prefix), value in self.overrides.items():
            if who in (repo, "*") and key.startswith(prefix):
                if isinstance(value, list):
                    answer = value.pop(0) if len(value) > 1 else value[0]
                else:
                    answer = value
                found = True
                break
        if not found:
            for prefix, value in self.defaults(repo, cwd).items():
                if key.startswith(prefix):
                    answer = value
                    break
        code, out, err = (*answer, "")[:3]
        if key.startswith("status") and not out.startswith("#"):
            code_repo = repo == "code"
            branch = CODE_BRANCH if code_repo else DOCS_BRANCH
            out = status_v2(branch, SHA_CODE if code_repo else SHA_DOCS, out)
        return subprocess.CompletedProcess(parts, code, out, err)

    def commands(self, repo: str | None = None) -> list[str]:
        """Las órdenes lanzadas (sin «git»), de un repositorio o de los dos."""
        return [" ".join(cmd[1:]) for who, cmd in self.calls if repo in (None, who)]


def write_files(root: Path, files: Mapping[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        if not path.parent.is_dir():
            path.parent.mkdir(parents=True)
        path.write_bytes(text.encode("utf-8"))


@dataclass
class Workspace:
    """Una carpeta temporal con la carpeta del proyecto (``project``, con el código en
    ``code``), un destino (``dest``) y el perfil local (``profile``, que hace de
    ``LOCALAPPDATA``)."""

    base: Path
    environ: dict[str, str] = field(default_factory=dict)

    @property
    def project(self) -> Path:
        return self.base / "proyecto"

    @property
    def code(self) -> Path:
        return self.project / CODE

    @property
    def dest(self) -> Path:
        return self.base / "destino"

    @property
    def profile(self) -> Path:
        return self.base / "perfil"

    def env(self, **extra: str) -> dict[str, str]:
        return {"LOCALAPPDATA": str(self.profile), **self.environ, **extra}


@contextlib.contextmanager
def workspace(
    docs: Mapping[str, str] | None = None,
    code: Mapping[str, str] | None = None,
    photo: bool = True,
) -> Iterator[Workspace]:
    """Un :class:`Workspace` con la carpeta del proyecto de prueba (más ``docs`` y
    ``code``) y un destino vacío con su foto inicial (``photo``: el primer espejo, que
    no necesita marcador); se borra al salir."""
    with tempfile.TemporaryDirectory(prefix="geoblender-publicacion-") as tmp:
        space = Workspace(Path(tmp).resolve())
        write_files(space.project, {**DOCS_FILES, **(docs or {})})
        write_files(space.code, {**CODE_FILES, **(code or {})})
        space.dest.mkdir()
        space.profile.mkdir()
        if photo:
            mirror.write_photo(space.profile, space.dest, files={})
        yield space


@dataclass
class Outcome:
    code: int
    out: str
    err: str
    git: FakeGit | None
    checks: FakeChecks

    @property
    def text(self) -> str:
        return self.out + self.err


def run_publish(
    space: Workspace,
    *args: str,
    git_runner: FakeGit | None = None,
    environ: Mapping[str, str] | None = None,
    root: Path | None = None,
    real_git: object = None,
    checks: FakeChecks | None = None,
    locate: object = fake_locate,
    dest_option: bool = True,
    mirror_hook: Callable[[str, str], None] | None = None,
) -> Outcome:
    """``publish.main`` con ``--destino`` = el destino de ``space`` (salvo que ``args``
    traiga otro, o sin él si no ``dest_option``), su entorno, el ejecutor de git
    (simulado si no se da otro) y las comprobaciones simuladas (en verde si no se dan
    otras)."""
    fake = git_runner if git_runner is not None else FakeGit()
    checks = checks if checks is not None else FakeChecks()
    argv = list(args)
    if dest_option and publish.OPTION_DEST not in argv:
        argv = [publish.OPTION_DEST, str(space.dest), *argv]
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = publish.main(
            argv,
            root=space.code if root is None else root,
            environ=space.env() if environ is None else dict(environ),
            git_runner=fake if real_git is None else real_git,
            runner=checks,
            locate=locate,
            mirror_hook=mirror_hook,
        )
    git_used = fake if real_git is None else None
    return Outcome(code, out.getvalue(), err.getvalue(), git_used, checks)


class PublicationAssertions(unittest.TestCase):
    """Lo que toda parada antes de subir cumple: su código, nada subido, el destino sin
    cambios."""

    def assertStopped(
        self, space: Workspace, code: int, *args: str, **kwargs: object
    ) -> Outcome:
        before = gbrepo.snapshot(space.dest)
        outcome = run_publish(space, *args, **kwargs)  # type: ignore[arg-type]
        self.assertEqual(outcome.code, code, outcome.text)
        self.assertIn(CHANGES if code == 3 else NOT_PUBLISHED, outcome.out)
        self.assertNotIn("RESULTADO: PUBLICADO", outcome.out)
        if outcome.git is not None:
            self.assertFalse(
                [c for c in outcome.git.commands() if c.startswith("push")], outcome.text
            )
        self.assertEqual(gbrepo.snapshot_changes(before, gbrepo.snapshot(space.dest)), [])
        return outcome


class OptionsTest(PublicationAssertions):
    """Opciones y raíz (plan 007 §5.4.5, paso 1)."""

    def test_usage_exit_2(self) -> None:
        """RF-007-17: una opción desconocida, ``--destino`` sin carpeta o
        ``--solo-espejo`` con ``--rehacer-estado``: código 2 con el uso."""
        with workspace() as space:
            for argv in (
                ["--forzar"],
                [publish.OPTION_DEST],
                [publish.OPTION_MIRROR_ONLY, publish.OPTION_REBUILD],
            ):
                with self.subTest(argumentos=argv):
                    outcome = run_publish(space, *argv)
                    self.assertEqual(outcome.code, 2, outcome.text)
                    self.assertIn("Uso", outcome.err)

    def test_help(self) -> None:
        """La ayuda nombra las opciones en español y termina con 0 sin lanzar git."""
        with workspace() as space:
            fake = FakeGit()
            outcome = run_publish(space, "--ayuda", git_runner=fake)
        self.assertEqual(outcome.code, 0, outcome.text)
        for option in (
            publish.OPTION_DEST,
            publish.OPTION_MIRROR_ONLY,
            publish.OPTION_REBUILD,
            layout.ENV_NAS_MIRROR,
        ):
            self.assertIn(option, outcome.out)
        self.assertEqual(fake.calls, [])

    def test_root_not_toplevel_exit_2(self) -> None:
        """RF-007-33 (paso 1): si la raíz del código no es la de su repositorio git (le
        falta su ``.git`` y git ve el de la documentación), código 2."""
        with workspace() as space:
            fake = FakeGit({("code", "rev-parse --show-toplevel"): (0, f"{space.project}\n")})
            outcome = self.assertStopped(space, 2, git_runner=fake)
        self.assertIn("raíz", outcome.out)


class StructureTest(PublicationAssertions):
    """RF-007-33: la estructura de la carpeta del proyecto (plan 007 §5.4.5, paso 2)."""

    def test_code_not_nested_exit_2(self) -> None:
        """RF-007-33: el código no está dentro de una carpeta con
        ``docs/constitution.md`` y un ``.git``: código 2, diciendo qué espera."""
        with workspace() as space:
            (space.project / layout.DOCS_MARKER).unlink()
            outcome = self.assertStopped(space, 2)
            self.assertIn(layout.DOCS_MARKER, outcome.out)
            self.assertIn(f"«{CODE}»", outcome.out)
        with workspace() as space:
            docs_git = space.project / ".git"
            for path in sorted(docs_git.rglob("*"), reverse=True):
                path.rmdir() if path.is_dir() else path.unlink()
            docs_git.rmdir()
            outcome = self.assertStopped(space, 2)
            self.assertIn(".git", outcome.out)

    def test_code_folder_wrong_case_exit_2(self) -> None:
        """RF-007-33: la carpeta del código con otra mayúscula (o con otro nombre):
        código 2 nombrando la carpeta esperada, mayúsculas incluidas."""
        for name in (CODE.lower(), "Codigo"):
            with self.subTest(carpeta=name), workspace() as space:
                renamed = space.project / name
                space.code.rename(space.project / "renombrando")
                (space.project / "renombrando").rename(renamed)
                outcome = self.assertStopped(space, 2, root=renamed)
                self.assertIn(f"«{name}»", outcome.out)
                self.assertIn(f"«{CODE}» (con esa mayúscula)", outcome.out)

    def test_docs_variable_elsewhere_exit_2(self) -> None:
        """RF-007-33: ``GEOBLENDER_DOCS_DIR`` apunta a otra carpeta que la madre del
        código: código 2 nombrando la variable; a la madre (escrita de otra forma), no
        para."""
        with workspace() as space:
            other = space.base / "otra-documentacion"
            write_files(other, {layout.DOCS_MARKER: "x\n"})
            environ = space.env(**{layout.ENV_DOCS_DIR: str(other)})
            outcome = self.assertStopped(space, 2, environ=environ)
            self.assertIn(layout.ENV_DOCS_DIR, outcome.out)
            same = space.env(**{layout.ENV_DOCS_DIR: str(space.code / "..")})
            outcome = run_publish(space, environ=same, checks=FakeChecks(check=STOP_AT_CHECK))
            self.assertNotIn(layout.ENV_DOCS_DIR, outcome.out, outcome.text)


class DestinationTest(PublicationAssertions):
    """RF-007-17, RF-007-18, RF-007-31: de dónde sale el destino y cuándo se rechaza
    (plan 007 §5.4.5, paso 3; §5.4.6), antes de subir nada y sin escribir en él ni en su
    carpeta madre."""

    def assertRejected(self, space: Workspace, dest: str | Path, *expected: str) -> Outcome:
        before = gbrepo.snapshot(space.base)
        outcome = self.assertStopped(space, 2, publish.OPTION_DEST, str(dest))
        self.assertIn(f"fallo     {publish.STEP_DEST}", outcome.out)
        for text in expected:
            self.assertIn(text, outcome.out)
        self.assertEqual(gbrepo.snapshot_changes(before, gbrepo.snapshot(space.base)), [])
        self.assertEqual(outcome.checks.calls, [])
        return outcome

    def test_option_over_variable(self) -> None:
        """RF-007-17: ``--destino`` manda sobre ``GEOBLENDER_NAS_ESPEJO``; sin la opción,
        vale la variable."""
        with workspace() as space:
            missing = space.base / "no-existe"
            environ = space.env(**{layout.ENV_NAS_MIRROR: str(missing)})
            outcome = run_publish(space, environ=environ, checks=FakeChecks(check=STOP_AT_CHECK))
            self.assertIn(f"correcto  {publish.STEP_DEST}", outcome.out, outcome.text)
            environ = space.env(**{layout.ENV_NAS_MIRROR: str(space.dest)})
            outcome = run_publish(space, environ=environ, dest_option=False, checks=FakeChecks(check=STOP_AT_CHECK))
            self.assertIn(f"correcto  {publish.STEP_DEST}", outcome.out, outcome.text)
            outcome = self.assertStopped(
                space, 2, environ=space.env(**{layout.ENV_NAS_MIRROR: str(missing)}),
                dest_option=False,
            )
            self.assertIn("no existe", outcome.out)

    def test_no_destination_exit_2(self) -> None:
        """RF-007-17: sin ``--destino`` ni ``GEOBLENDER_NAS_ESPEJO`` (o vacía), código 2
        nombrando la opción y la variable."""
        with workspace() as space:
            for environ in (space.env(), space.env(**{layout.ENV_NAS_MIRROR: "  "})):
                outcome = self.assertStopped(space, 2, environ=environ, dest_option=False)
                self.assertIn(publish.OPTION_DEST, outcome.out)
                self.assertIn(layout.ENV_NAS_MIRROR, outcome.out)

    def test_dest_is_project(self) -> None:
        """RF-007-18: el destino es la carpeta del proyecto (también escrita con otras
        mayúsculas)."""
        with workspace() as space:
            self.assertRejected(space, space.project, "carpeta del proyecto")
            self.assertRejected(space, str(space.project).upper(), "carpeta del proyecto")

    def test_dest_inside_project(self) -> None:
        """RF-007-18: el destino está dentro de la carpeta del proyecto (la del código,
        o la de ``docs/``)."""
        with workspace() as space:
            self.assertRejected(space, space.code, "dentro de la carpeta del proyecto")
            self.assertRejected(space, space.project / "docs", "dentro")

    def test_dest_contains_project(self) -> None:
        """RF-007-18: el destino contiene la carpeta del proyecto."""
        with workspace() as space:
            self.assertRejected(space, space.base, "contiene la carpeta del proyecto")

    def test_drive_root(self) -> None:
        """RF-007-18: la raíz de una unidad (la del disco temporal, o una que no existe)."""
        with workspace() as space:
            anchor = Path(space.base.anchor)
            self.assertRejected(space, anchor, "raíz")
            self.assertRejected(space, "Y" + ":\\", "raíz")

    def test_share_root(self) -> None:
        """RF-007-18: la raíz de un recurso compartido (sin buscar el servidor)."""
        with workspace() as space:
            self.assertRejected(space, "\\\\servidor.invalid\\recurso", "raíz")
            self.assertRejected(space, "\\\\servidor.invalid\\recurso\\", "raíz")

    def test_dossier_folder(self) -> None:
        """RF-007-18: la carpeta de expedientes de clientes o una de dentro (el primer
        componente bajo la raíz de una unidad, o el nombre del recurso, es ``an``),
        escrita con cualquier mayúscula y sin buscar la unidad ni el servidor."""
        dossier = "an"
        with workspace() as space:
            for dest in (
                "Y" + ":\\" + dossier,
                "Y" + ":\\" + dossier.upper() + "\\proyecto\\espejo",
                "\\\\servidor.invalid\\" + dossier + "\\espejo",
            ):
                with self.subTest(destino=dest):
                    self.assertRejected(space, dest, "expedientes de clientes")

    def test_missing_dest(self) -> None:
        """RF-007-18: un destino que no existe: se rechaza y no se crea."""
        with workspace() as space:
            missing = space.base / "no-existe"
            self.assertRejected(space, missing, "no existe")
            self.assertFalse(missing.exists())

    def test_dest_is_file(self) -> None:
        """RF-007-18: un destino que es un fichero."""
        with workspace() as space:
            target = space.base / "destino.txt"
            target.write_bytes(b"x\n")
            self.assertRejected(space, target, "no es una carpeta")

    def test_dest_without_marker(self) -> None:
        """RF-007-18: un destino sin ``docs/constitution.md`` que no es el primer espejo
        contra su foto (tiene estado, o no tiene ni estado ni foto)."""
        with workspace(photo=False) as space:
            mirror.write_state(space.profile, space.dest, files={}, folders=[])
            self.assertRejected(space, space.dest, layout.DOCS_MARKER)
        with workspace(photo=False) as space:
            self.assertRejected(space, space.dest, layout.DOCS_MARKER)

    def test_first_mirror_without_marker_ok(self) -> None:
        """RF-007-18, RF-007-31: sin marcador, el primer espejo contra su foto sí vale;
        con marcador y estado, también."""
        with workspace() as space:
            outcome = run_publish(space, checks=FakeChecks(check=STOP_AT_CHECK))
            self.assertIn(f"correcto  {publish.STEP_DEST}", outcome.out, outcome.text)
            self.assertIn("primer espejo", outcome.out)
        with workspace(photo=False) as space:
            write_files(space.dest, {layout.DOCS_MARKER: "x\n"})
            mirror.write_state(space.profile, space.dest)
            outcome = run_publish(space, checks=FakeChecks(check=STOP_AT_CHECK))
            self.assertIn(f"correcto  {publish.STEP_DEST}", outcome.out, outcome.text)
            self.assertIn("estado del 05/10/2026 23:40", outcome.out)

    def test_no_state_exit_2(self) -> None:
        """RF-007-31: con marcador pero sin estado ni foto, código 2 remitiendo a
        ``--rehacer-estado``, sin escribir nada."""
        with workspace(photo=False) as space:
            write_files(space.dest, {layout.DOCS_MARKER: "x\n"})
            outcome = self.assertRejected(space, space.dest, publish.OPTION_REBUILD)
        self.assertIn("ni su foto", outcome.out)

    def test_unreadable_state_exit_2(self) -> None:
        """RF-007-31: un estado ilegible, aunque haya foto: código 2 remitiendo a
        ``--rehacer-estado``; ni el estado ni la foto cambian."""
        with workspace() as space:
            write_files(space.dest, {layout.DOCS_MARKER: "x\n"})
            state = mirror.write_state(space.profile, space.dest)
            state.write_bytes(b"{roto")
            outcome = self.assertRejected(space, space.dest, publish.OPTION_REBUILD)
            self.assertEqual(state.read_bytes(), b"{roto")
        self.assertIn("no se puede leer", outcome.out)


class RemoteTest(PublicationAssertions):
    """RF-007-19: el remoto del código y las credenciales de los dos ``.git/config``
    (plan 007 §5.4.5, paso 4): código 2 antes de subir nada, sin copiar ningún ``.git``
    al destino y sin mostrar el secreto."""

    SECRET = "secreto-de-prueba"

    def assertCredentials(self, space: Workspace, **kwargs: object) -> Outcome:
        outcome = self.assertStopped(space, 2, **kwargs)
        self.assertIn(f"fallo     {publish.STEP_REMOTE}", outcome.out)
        self.assertIn("credenciales", outcome.out)
        self.assertNotIn(self.SECRET, outcome.text)
        self.assertEqual(outcome.checks.calls, [])
        self.assertEqual(list(space.dest.iterdir()), [])
        return outcome

    def test_credentials_in_code_url(self) -> None:
        """RF-007-19: la dirección de ``origin`` del código lleva usuario y token."""
        url = f"https://usuario:{self.SECRET}@github.invalid/pruebas/codigo.git"
        config = f'[core]\n\tbare = false\n[remote "origin"]\n\turl = {url}\n'
        fake = FakeGit({("code", "config --get remote.origin.url"): (0, f"{url}\n")})
        with workspace(code={".git/config": config}) as space:
            outcome = self.assertCredentials(space, git_runner=fake)
        self.assertIn("origin", outcome.out)

    def test_credentials_in_docs_config(self) -> None:
        """RF-007-19: la configuración de la documentación (que el espejo copiaría al
        NAS) tiene una regla ``insteadOf`` con credenciales."""
        config = (
            "[core]\n\tbare = false\n"
            f'[url "https://usuario:{self.SECRET}@github.invalid/"]\n'
            "\tinsteadOf = https://github.invalid/\n"
        )
        with workspace(docs={".git/config": config}) as space:
            outcome = self.assertCredentials(space)
        self.assertIn(publish.DOCS_LABEL, outcome.out)
        self.assertIn("línea 3", outcome.out)

    def test_credentials_no_copy(self) -> None:
        """RF-007-19: una cabecera de autorización en el ``.git/config`` del código:
        nada subido, nada copiado (el destino sigue vacío), ninguna comprobación."""
        config = (
            f'[core]\n\tbare = false\n[remote "origin"]\n\turl = {CODE_URL}\n'
            f"[http]\n\textraheader = AUTHORIZATION: bearer {self.SECRET}\n"
        )
        with workspace(code={".git/config": config}) as space:
            outcome = self.assertCredentials(space)
        self.assertIn(publish.CODE_LABEL, outcome.out)

    def test_origin_missing_exit_2(self) -> None:
        """RF-007-20 (plan §5.4.5, paso 4): sin ``origin`` en el código no hay a dónde
        subir: código 2."""
        fake = FakeGit({("code", "config --get remote.origin.url"): (1, "")})
        with workspace() as space:
            outcome = self.assertStopped(space, 2, git_runner=fake)
        self.assertIn("origin", outcome.out)

    def test_remote_reported(self) -> None:
        """RF-007-23: el remoto, sin credenciales, va en el informe."""
        with workspace() as space:
            outcome = run_publish(space, checks=FakeChecks(check=STOP_AT_CHECK))
        self.assertIn(f"correcto  {publish.STEP_REMOTE}", outcome.out)
        self.assertIn(CODE_URL, outcome.out)


class TreesTest(PublicationAssertions):
    """RF-007-15: los dos árboles limpios, en una rama, sin operaciones a medias (plan
    007 §5.4.5, paso 5)."""

    def assertTreeStop(
        self, space: Workspace, label: str, *expected: str, git_runner: FakeGit | None = None
    ) -> Outcome:
        outcome = self.assertStopped(space, 1, git_runner=git_runner)
        self.assertIn(f"fallo     {publish.STEP_TREES}", outcome.out)
        for text in (label, *expected):
            self.assertIn(text, outcome.out)
        return outcome

    def test_dirty_code_tree(self) -> None:
        """RF-007-15: un cambio sin commit en el código: código 1 con el repositorio y
        el fichero."""
        fake = FakeGit({("code", "status"): (0, " M README.md\0")})
        with workspace() as space:
            self.assertTreeStop(space, "código", "README.md", git_runner=fake)

    def test_dirty_docs_tree(self) -> None:
        """RF-007-15: un cambio sin commit en la documentación (también un renombrado):
        código 1 con el repositorio y los ficheros."""
        status = " M docs/constitution.md\0R  nuevo.md\0viejo.md\0"
        fake = FakeGit({("docs", "status"): (0, status)})
        with workspace() as space:
            self.assertTreeStop(
                space, "documentación", "docs/constitution.md", "nuevo.md", "viejo.md",
                git_runner=fake,
            )

    def test_untracked_file(self) -> None:
        """RF-007-15: un fichero nuevo que no se ignora, en cualquiera de los dos."""
        fake = FakeGit({("*", "status"): (0, "?? notas/borrador.txt\0")})
        with workspace() as space:
            outcome = self.assertTreeStop(
                space, "código", "documentación", "notas/borrador.txt", git_runner=fake
            )
        self.assertIn("nuevo", outcome.out)

    def test_rebase_in_progress(self) -> None:
        """RF-007-15: un rebase a medias en el código (``.git/rebase-merge``)."""
        with workspace(code={".git/rebase-merge/head-name": "refs/heads/main\n"}) as space:
            self.assertTreeStop(space, "código", "rebase")

    def test_index_lock(self) -> None:
        """RF-007-15: un cerrojo de git (``.git/index.lock``) en la documentación."""
        with workspace(docs={".git/index.lock": ""}) as space:
            self.assertTreeStop(space, "documentación", "index.lock")

    def test_gc_running(self) -> None:
        """RF-007-15: un mantenimiento de git en curso (``.git/gc.pid``)."""
        with workspace(code={".git/gc.pid": "1234 equipo\n"}) as space:
            self.assertTreeStop(space, "código", "gc.pid")

    def test_detached_head(self) -> None:
        """RF-007-15: HEAD separado de toda rama, en cualquiera de los dos."""
        fake = FakeGit({("docs", "status"): (0, status_v2(DETACHED, SHA_DOCS))})
        with workspace() as space:
            self.assertTreeStop(space, "documentación", "rama", git_runner=fake)

    def test_linked_worktree(self) -> None:
        """RF-007-15: el código es un *worktree* enlazado (``.git`` es un fichero)."""
        with workspace() as space:
            git_dir = space.code / ".git"
            for path in sorted(git_dir.rglob("*"), reverse=True):
                path.rmdir() if path.is_dir() else path.unlink()
            git_dir.rmdir()
            git_dir.write_bytes(b"gitdir: C:/otro/.git/worktrees/codigo\n")
            self.assertTreeStop(space, "código", "worktree")

    def test_alternates(self) -> None:
        """RF-007-15: la documentación toma objetos de otro repositorio
        (``objects/info/alternates``)."""
        with workspace(docs={".git/objects/info/alternates": "C:/otro/objects\n"}) as space:
            self.assertTreeStop(space, "documentación", "alternates")

    def test_docs_tracks_code_folder(self) -> None:
        """RF-007-15: la documentación versiona algo bajo la carpeta del código (también
        un *gitlink* de ``git add -f``)."""
        listing = f"160000 {'b' * 40} 0\t{CODE}\x00100644 {'a' * 40} 0\t{CODE}/x.md\x00"
        fake = FakeGit({("docs", "ls-files"): (0, listing)})
        with workspace() as space:
            self.assertTreeStop(
                space, "documentación", f"{CODE} (gitlink)", f"{CODE}/x.md", git_runner=fake
            )

    def test_all_problems_listed(self) -> None:
        """RF-007-15: con varios problemas en los dos repositorios, la lista los da
        todos, cada uno con su repositorio, y no lanza más git que las lecturas."""
        fake = FakeGit({("*", "status"): (0, " M README.md\0")})
        with workspace(docs={".git/MERGE_HEAD": f"{SHA_DOCS}\n"}) as space:
            outcome = self.assertTreeStop(
                space, "código", "documentación", "README.md", "fusión", git_runner=fake
            )
        reads = ("rev-parse", "status", "config", "ls-files")
        for command in fake.commands():
            self.assertTrue(command.startswith(reads), command)
        self.assertIn("No se ha subido ni copiado nada", outcome.out)


class ChecksTest(PublicationAssertions):
    """RF-007-16: la publicación ejecuta siempre las dos comprobaciones (plan 007
    §5.4.5, paso 8), con el Python de Blender, y no sigue si alguna no termina con 0."""

    def test_check_red_stops(self) -> None:
        """RF-007-16: ``tools/check.py`` no termina con 0: código 1, sin subir ni
        copiar, mostrando su resultado."""
        red = (1, "  fallo     unitarias\nRESULTADO: NO VERDE (2,0 s): falla «unitarias»\n")
        with workspace() as space:
            outcome = self.assertStopped(space, 1, checks=FakeChecks(check=red))
        self.assertIn("fallo     comprobación", outcome.out)
        self.assertIn("RESULTADO: NO VERDE (2,0 s): falla «unitarias»", outcome.out)

    def test_docs_check_red_stops(self) -> None:
        """RF-007-16: ``tools/check_docs.py`` no termina con 0 (con el código en verde):
        código 1, sin subir ni copiar, mostrando su resultado."""
        red = (1, "docs/x.md:1: [TXT-02] …\nRESULTADO: DOCUMENTACIÓN CON INCUMPLIMIENTOS (1)\n")
        with workspace() as space:
            outcome = self.assertStopped(space, 1, checks=FakeChecks(docs=red))
        self.assertIn("correcto  comprobación", outcome.out)
        self.assertIn("fallo     documentación", outcome.out)
        self.assertIn("DOCUMENTACIÓN CON INCUMPLIMIENTOS (1)", outcome.out)

    def test_checks_commands(self) -> None:
        """RF-007-16, RF-001-06 (spec 001 0.6): las dos con el Python del Blender
        localizado (``-B -s -X utf8``), desde la raíz del código: ``tools/check.py
        --completo`` (nada se publica sin las pruebas del arnés que lanzan Blender entero;
        D-9 de la spec 002, T48) y ``tools/check_docs.py`` con la carpeta del proyecto;
        después de los árboles, que se miran otra vez."""
        fake = FakeGit({("code", "push"): (1, "", "subida rechazada (prueba)\n")})
        with workspace() as space:
            outcome = run_publish(space, git_runner=fake)
            project = space.project
        self.assertEqual(outcome.checks.scripts(), ["tools/check.py", "tools/check_docs.py"])
        for cmd, cwd in outcome.checks.calls:
            self.assertEqual(cmd[:5], [str(INSTALL.python), "-B", "-s", "-X", "utf8"])
            self.assertEqual(cwd, project / CODE)
        self.assertEqual(outcome.checks.calls[0][0][5:], ["tools/check.py", "--completo"])
        self.assertEqual(outcome.checks.calls[1][0][-1], str(project))
        self.assertEqual(len([c for c in fake.commands() if c.startswith("status")]), 4)
        self.assertIn("RESULTADO: VERDE (1,0 s)", outcome.out)
        self.assertIn("DOCUMENTACIÓN CORRECTA", outcome.out)

    def test_solo_espejo_skips_code_check(self) -> None:
        """RF-007-16, RF-007-24: con ``--solo-espejo`` no se comprueba el código, pero sí
        la documentación."""
        with workspace() as space:
            checks = FakeChecks(docs=STOP_AT_CHECK)
            outcome = run_publish(space, publish.OPTION_MIRROR_ONLY, checks=checks)
        self.assertEqual(outcome.checks.scripts(), ["tools/check_docs.py"])
        self.assertIn("omitido   comprobación", outcome.out)

    def test_checks_change_tree_stops(self) -> None:
        """RF-007-15, RF-007-16: si tras las comprobaciones un árbol ya no está limpio
        (las comprobaciones no deben cambiar nada), código 1 sin subir."""
        status = [(0, ""), (0, ""), (0, " M tools/check.py\0")]
        with workspace() as space:
            outcome = self.assertStopped(space, 1, git_runner=FakeGit({("*", "status"): status}))
        self.assertIn("tools/check.py", outcome.out)
        self.assertIn("comprobaciones", outcome.out)

    def test_stream_run_shows_and_returns_output(self) -> None:
        """RF-007-16 (plan §5.4.5, paso 8): la salida de una comprobación se ve en
        directo, sangrada, y se devuelve entera con su código."""
        code = "import sys; print('una'); print('RESULTADO: VERDE'); sys.exit(3)"
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = publish.stream_run([sys.executable, "-B", "-c", code], timeout=60)
        self.assertEqual(result.returncode, 3)
        self.assertEqual(publish.last_result(result.stdout), "RESULTADO: VERDE")
        self.assertIn("    │ una\n", out.getvalue())

    def test_blender_missing_exit_2(self) -> None:
        """RF-007-16: sin el Blender del manifiesto no se puede comprobar: código 2 con
        el mensaje del localizador, sin ejecutar nada."""

        def missing(_minimum: tuple[int, int, int]) -> BlenderInstall:
            raise EnvironmentProblem("No se encuentra Blender (prueba)")

        with workspace() as space:
            outcome = self.assertStopped(space, 2, locate=missing)
        self.assertIn("No se encuentra Blender (prueba)", outcome.out)
        self.assertEqual(outcome.checks.calls, [])


class PushTest(PublicationAssertions):
    """RF-007-20, RF-007-21: la subida de la rama actual del código y sus etiquetas
    anotadas, sin forzar (plan 007 §5.4.5, paso 9); si falla, sin espejo."""

    def test_never_force(self) -> None:
        """RF-007-20: una sola subida, de la rama actual a la misma rama de ``origin``,
        con ``--follow-tags`` y sin ``--force``, ``--mirror``, ``--all``, ``--delete`` ni
        un «+» en la referencia; después de las comprobaciones."""
        fake = FakeGit()
        with workspace() as space:
            # Un fichero que aparece en el destino durante las comprobaciones para la
            # publicación tras la subida (sin hacer el espejo, que aquí no hace falta).
            late = space.dest / "tarde.txt"
            checks = FakeChecks(during_check=lambda: late.write_bytes(b"x\n"))
            outcome = run_publish(space, git_runner=fake, checks=checks)
        pushes = [cmd for cmd in fake.commands("code") if cmd.startswith("push")]
        self.assertEqual(
            pushes,
            [f"push --follow-tags --porcelain origin refs/heads/{CODE_BRANCH}:refs/heads/{CODE_BRANCH}"],
        )
        self.assertEqual([c for c in fake.commands("docs") if c.startswith("push")], [])
        for forbidden in ("--force", " -f", "--mirror", "--all", "--delete", " +"):
            self.assertNotIn(forbidden, pushes[0])
        self.assertIn(f"correcto  {publish.STEP_PUSH}", outcome.out, outcome.text)
        self.assertEqual(outcome.checks.scripts(), ["tools/check.py", "tools/check_docs.py"])

    def test_rejected_push_no_mirror(self) -> None:
        """RF-007-21: la subida rechazada (la rama de ``origin`` avanzó): código 1 con el
        mensaje de git, sin espejo (el destino, igual)."""
        rejected = (
            1, "To origen\n!\trefs/heads/main:refs/heads/main\t[rejected] (fetch first)\n",
            "error: failed to push some refs to 'origen'\n",
        )
        fake = FakeGit({("code", "push"): rejected})
        with workspace() as space:
            before = gbrepo.snapshot(space.dest)
            outcome = run_publish(space, git_runner=fake)
            self.assertEqual(gbrepo.snapshot_changes(before, gbrepo.snapshot(space.dest)), [])
        self.assertEqual(outcome.code, 1, outcome.text)
        self.assertIn(f"fallo     {publish.STEP_PUSH}", outcome.out)
        self.assertIn("[rejected] (fetch first)", outcome.out)
        self.assertIn("failed to push some refs", outcome.out)
        self.assertIn("sin espejo", outcome.out)

    def test_unreachable_remote_no_mirror(self) -> None:
        """RF-007-21: sin red o sin permiso: código 1 con el mensaje de git, sin espejo."""
        failed = (128, "", "fatal: unable to access 'https://github.invalid/': Could not resolve host\n")
        fake = FakeGit({("code", "push"): failed})
        with workspace() as space:
            outcome = run_publish(space, git_runner=fake)
            self.assertEqual(list(space.dest.iterdir()), [])
        self.assertEqual(outcome.code, 1, outcome.text)
        self.assertIn("Could not resolve host", outcome.out)
        self.assertIn("código 128", outcome.out)


class DestinationChangesTest(PublicationAssertions):
    """RF-007-29: si el destino cambió desde el último espejo, código 3 con la lista y
    cómo traer cada cambio al PC, sin subir, copiar ni borrar nada (plan 007 §5.4.5,
    paso 7, y otra vez justo antes de copiar)."""

    def test_dest_changes_exit_3_nothing_pushed(self) -> None:
        """RF-007-29: un fichero nuevo en el destino (no estaba en la foto): código 3
        antes de las comprobaciones y de la subida, con su tipo, su ruta, su
        repositorio y cómo traerlo; el destino, igual."""
        with workspace() as space:
            write_files(space.dest, {"nota.txt": "del NAS\n"})
            outcome = self.assertStopped(space, 3)
            dest, project = space.dest, space.project
        self.assertIn(f"PARADA    {publish.STEP_DEST}", outcome.out)
        self.assertIn("1 cambio en el destino desde el último espejo", outcome.out)
        self.assertRegex(outcome.out, r"nuevo +nota\.txt +documentación")
        self.assertIn(f'Copy-Item -LiteralPath "{dest}\\nota.txt" "{project}\\nota.txt"', outcome.out)
        self.assertIn("git diff --no-index", outcome.out)
        self.assertIn(f"{CHANGES} (1)", outcome.out)
        self.assertIn("No se ha subido ni copiado nada", outcome.out)
        self.assertEqual(outcome.checks.calls, [])

    def test_dest_git_change_advice(self) -> None:
        """RF-007-29, RF-007-32: un cambio dentro de un ``.git`` del destino (alguien usó
        git allí): marcado como tal, y cómo traer sus commits y rehacer el estado."""
        with workspace() as space:
            write_files(space.dest, {f"{CODE}/.git/index": "índice del NAS\n"})
            outcome = self.assertStopped(space, 3)
        self.assertRegex(outcome.out, r"nuevo +" + CODE + r"/\.git/index +código, dentro de \.git")
        self.assertIn("fetch", outcome.out)
        self.assertIn(publish.OPTION_REBUILD, outcome.out)

    def test_dest_changed_before_copy(self) -> None:
        """RF-007-29: el destino cambia durante las comprobaciones (después de la
        primera comparación): la segunda, justo antes de copiar, lo ve: código 3; la
        subida ya se hizo y el informe lo dice; no se copia nada."""
        with workspace() as space:
            late = space.dest / "tarde.txt"
            checks = FakeChecks(during_check=lambda: late.write_bytes(b"durante\n"))
            outcome = run_publish(space, checks=checks)
            listing = sorted(path.name for path in space.dest.iterdir())
        self.assertEqual(outcome.code, 3, outcome.text)
        self.assertEqual(listing, ["tarde.txt"])
        self.assertIn(f"correcto  {publish.STEP_PUSH}", outcome.out)
        self.assertRegex(outcome.out, r"nuevo +tarde\.txt")
        self.assertIn(f"Se subió {CODE_BRANCH} a origin", outcome.out)
        self.assertIn("sigue en el espejo anterior", outcome.out)
        self.assertIn(f"{CHANGES} (1)", outcome.out)


class MirrorStepTest(PublicationAssertions):
    """RF-007-22, RF-007-34: el espejo dentro de la publicación (plan 007 §5.4.5, paso
    10; §5.4.8)."""

    def test_lock_present_exit_1(self) -> None:
        """RF-007-22: con el cerrojo de otro espejo desde este PC a ese destino, código 1
        antes de comparar, comprobar, subir o copiar; el cerrojo no se toca."""
        with workspace() as space:
            lock = safe_mirror.lock_file(space.dest, space.env())
            lock.parent.mkdir(parents=True, exist_ok=True)
            lock.write_bytes(b'{"quien": "otro"}')
            outcome = self.assertStopped(space, 1)
            self.assertEqual(lock.read_bytes(), b'{"quien": "otro"}')
        self.assertIn("otro espejo en curso", outcome.out)
        self.assertEqual(outcome.checks.calls, [])

    def test_change_during_mirror_exit_3_after_push_reported(self) -> None:
        """RF-007-34: un fichero que aparece en el destino mientras se copia no se toca:
        código 3, sin guardar el estado; el informe dice que se subió y que el espejo
        quedó a medias."""
        with workspace() as space:
            target = space.dest / layout.DOCS_MARKER

            def hook(action: str, rel: str) -> None:
                if (action, rel) == ("sustituir", layout.DOCS_MARKER):
                    target.write_bytes(b"del NAS durante el espejo\n")

            outcome = run_publish(space, mirror_hook=hook)
            self.assertEqual(target.read_bytes(), b"del NAS durante el espejo\n")
            state = safe_mirror.state_file(space.dest, space.env())
            self.assertFalse(state.exists())
        self.assertEqual(outcome.code, 3, outcome.text)
        self.assertIn(f"PARADA    {publish.STEP_MIRROR}", outcome.out)
        self.assertIn(f"Se subió {CODE_BRANCH} a origin", outcome.out)
        self.assertIn("a medias", outcome.out)
        self.assertIn(f"{CHANGES} (1)", outcome.out)


class ReportTest(unittest.TestCase):
    """RF-007-22, RF-007-23, RF-007-30: una publicación correcta a un destino vacío (con
    algo excluido) y su repetición sin cambios, hechas una vez por clase
    (``setUpClass``); cada prueba mira una parte: el espejo, la comprobación, el estado y
    el informe (plan 007 §5.4.8, pasos 4 y 5; §5.5)."""

    stack: contextlib.ExitStack
    space: Workspace
    first: Outcome
    second: Outcome
    state: dict[str, object]
    files: dict[str, dict[str, object]]
    folders: list[str]
    leftovers: list[bool]

    @classmethod
    def setUpClass(cls) -> None:
        cls.stack = contextlib.ExitStack()
        try:
            space = cls.stack.enter_context(workspace())
            cls.space = space
            write_files(space.dest, {"dist/viejo.zip": "zip"})
            cls.first = run_publish(space)
            environ = space.env()
            cls.state = json.loads(safe_mirror.state_file(space.dest, environ).read_bytes())
            cls.files = {
                rel: info
                for rel, info in mirror.describe(space.dest).items()
                if not safe_mirror.is_excluded(rel)
            }
            cls.folders = [
                rel for rel in mirror.folders_of(space.dest)
                if not safe_mirror.is_excluded(rel, True)
            ]
            cls.leftovers = [
                path.exists()
                for path in (
                    safe_mirror.pending_file(space.dest, environ),
                    safe_mirror.lock_file(space.dest, environ),
                )
            ]
            cls.second = run_publish(space)
        except BaseException:
            cls.stack.close()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        cls.stack.close()

    def test_mirror_copies_project(self) -> None:
        """RF-007-22: tras subir, el destino (vacío, primer espejo) queda con los
        ficheros de la carpeta del proyecto, los dos ``.git`` incluidos (y con lo
        excluido que tenía, sin tocar), y el informe da los copiados."""
        source = mirror.describe(self.space.project)
        self.assertIn(f"correcto  {publish.STEP_MIRROR}", self.first.out, self.first.text)
        self.assertEqual(
            {rel: info["sha256"] for rel, info in self.files.items()},
            {rel: info["sha256"] for rel, info in source.items()},
        )
        self.assertEqual((self.space.dest / "dist" / "viejo.zip").read_bytes(), b"zip")
        self.assertIn(f"{len(source)} copiados", self.first.out)

    def test_report_fields(self) -> None:
        """RF-007-23: el informe da la rama y el commit de cada repositorio, el remoto,
        los copiados, borrados y sin cambios, las exclusiones halladas en el destino, la
        verificación, el resultado, la duración y el destino."""
        outcome, dest = self.first, self.space.dest
        self.assertEqual(outcome.code, 0, outcome.text)
        out = outcome.out
        for text in (
            f"{publish.CODE_LABEL} {CODE_BRANCH} {SHA_CODE[:7]}",
            f"{publish.DOCS_LABEL} {DOCS_BRANCH} {SHA_DOCS[:7]}",
            f"origin = {CODE_URL}",
            f"{len(CODE_FILES) + len(DOCS_FILES)} copiados, 0 borrados, 0 sin cambios",
            "excluidos en el destino: dist/",
            f"correcto  {publish.STEP_VERIFY}",
            "estado guardado",
        ):
            self.assertIn(text, out)
        self.assertRegex(out, r"RESULTADO: PUBLICADO \(\d+,\d s\) en " + re.escape(str(dest)))

    def test_state_written(self) -> None:
        """RF-007-30: tras una publicación correcta, el estado del destino (en el perfil
        local) tiene cada fichero con el tamaño, la fecha y el sha256 del destino, sus
        carpetas (sin lo excluido), la rama y el commit de cada repositorio y el remoto;
        el registro en curso y el cerrojo ya no están."""
        state = self.state
        self.assertEqual((state["formato"], state["tipo"]), (1, "estado"))
        self.assertEqual(state["ficheros"], self.files)
        self.assertEqual(sorted(state["carpetas"]), self.folders)  # type: ignore[arg-type]
        repos = state["repositorios"]
        assert isinstance(repos, dict)
        self.assertEqual(repos[CODE], {"rama": CODE_BRANCH, "commit": SHA_CODE, "origin": CODE_URL})
        self.assertEqual(repos["."], {"rama": DOCS_BRANCH, "commit": SHA_DOCS})
        self.assertEqual(self.leftovers, [False, False])

    def test_second_run_copies_nothing(self) -> None:
        """RF-007-23: repetir la publicación sin cambios copia 0 ficheros y termina con
        0, comparando con el estado de la primera."""
        self.assertEqual((self.first.code, self.second.code), (0, 0), self.second.text)
        self.assertIn("estado del", self.second.out)
        self.assertIn("0 copiados, 0 borrados", self.second.out)


class VerifyStepTest(PublicationAssertions):
    """RF-007-23: sin estado si la comprobación del espejo no cuadra."""

    def test_state_only_after_verify(self) -> None:
        """RF-007-23, RF-007-34: si la comprobación del espejo ve una diferencia (un
        fichero ya copiado cambió en el destino), código 3 y no se guarda el estado: el
        siguiente espejo se compara con el anterior."""
        with workspace() as space:
            copied = space.dest / layout.DOCS_MARKER

            def hook(action: str, rel: str) -> None:
                if (action, rel) == ("sustituir", f"{CODE}/{layout.CHECK_RELPATH}"):
                    copied.write_bytes(b"cambiada en el NAS tras copiarla\n")

            outcome = run_publish(space, mirror_hook=hook)
            state = safe_mirror.state_file(space.dest, space.env())
            self.assertFalse(state.exists())
            self.assertTrue(safe_mirror.pending_file(space.dest, space.env()).exists())
        self.assertEqual(outcome.code, 3, outcome.text)
        self.assertIn(f"PARADA    {publish.STEP_VERIFY}", outcome.out)
        self.assertIn(f"{CHANGES} (1)", outcome.out)


class MirrorOnlyTest(PublicationAssertions):
    """RF-007-24: ``--solo-espejo``: todo salvo la comprobación del código y la subida, y
    un aviso si la rama del código tiene commits que ``origin`` no tiene."""

    def test_solo_espejo_no_push(self) -> None:
        """RF-007-24: con ``--solo-espejo`` no se lanza ``git push`` ni se comprueba el
        código; el espejo se hace, se comprueba, se guarda el estado y el resultado lo
        dice."""
        fake = FakeGit()
        with workspace() as space:
            outcome = run_publish(space, publish.OPTION_MIRROR_ONLY, git_runner=fake)
            mirrored = safe_mirror.state_file(space.dest, space.env()).exists()
        self.assertEqual(outcome.code, 0, outcome.text)
        self.assertEqual([c for c in fake.commands() if c.startswith("push")], [])
        self.assertEqual(outcome.checks.scripts(), ["tools/check_docs.py"])
        self.assertIn(f"omitido   {publish.STEP_PUSH}", outcome.out)
        self.assertIn(f"{CODE_BRANCH} está en origin", outcome.out)
        self.assertRegex(outcome.out, r"RESULTADO: PUBLICADO \(solo espejo, \d+,\d s\)")
        self.assertTrue(mirrored)

    def test_solo_espejo_warns_unpushed(self) -> None:
        """RF-007-24: si la rama del código tiene commits que ``refs/remotes/origin``
        no tiene, o no hay esa referencia, un aviso (no un error): el espejo sigue."""
        cases = (
            ({("code", "rev-list --count"): (0, "2\n")}, "2 commits que origin no tiene"),
            (
                {("code", "rev-parse --verify --quiet refs/remotes/origin/"): (1, "")},
                "no se sabe si origin tiene",
            ),
        )
        for overrides, expected in cases:
            with self.subTest(aviso=expected), workspace() as space:
                outcome = run_publish(
                    space, publish.OPTION_MIRROR_ONLY, git_runner=FakeGit(overrides)
                )
                self.assertEqual(outcome.code, 0, outcome.text)
                self.assertIn(f"aviso     {publish.STEP_PUSH}", outcome.out)
                self.assertIn(expected, outcome.out)
                self.assertIn("sin subir", outcome.out)


REBUILT = "RESULTADO: ESTADO REHECHO"


class RebuildStateTest(PublicationAssertions):
    """RF-007-32 (D-16): ``--rehacer-estado`` toma el destino como estado nuevo solo si
    nada se pierde (plan 007 §5.4.9); nunca sube, copia ni borra nada."""

    def mirrored_space(self, stack: contextlib.ExitStack) -> Workspace:
        """Un espacio cuyo destino es una copia exacta de la carpeta del proyecto (como
        la deja un espejo) con su estado, y una rama en el ``.git`` del código del
        destino."""
        space = stack.enter_context(workspace())
        shutil.copytree(space.project, space.dest, dirs_exist_ok=True)
        write_files(space.dest, {f"{CODE}/.git/refs/heads/{CODE_BRANCH}": f"{SHA_CODE}\n"})
        mirror.write_state(space.profile, space.dest)
        return space

    def rebuild(self, space: Workspace, fake: FakeGit | None = None, code: int = 0) -> Outcome:
        """``--rehacer-estado``: sin subir, comprobar ni tocar el destino."""
        fake = fake or FakeGit()
        before = gbrepo.snapshot(space.dest)
        outcome = run_publish(space, publish.OPTION_REBUILD, git_runner=fake)
        self.assertEqual(outcome.code, code, outcome.text)
        self.assertEqual(gbrepo.snapshot_changes(before, gbrepo.snapshot(space.dest)), [])
        self.assertEqual([c for c in fake.commands() if c.startswith("push")], [])
        self.assertEqual(outcome.checks.calls, [])
        return outcome

    def test_rehacer_estado_git_only(self) -> None:
        """RF-007-32: un cambio dentro de un ``.git`` del destino (un ``git status`` en
        el NAS reescribió el índice) para la publicación (3); con ``--rehacer-estado``,
        si sus referencias apuntan a commits que el PC tiene, el destino pasa a ser el
        estado (0) y la publicación siguiente ya no para por eso."""
        with contextlib.ExitStack() as stack:
            space = self.mirrored_space(stack)
            write_files(space.dest, {f"{CODE}/.git/index": "índice reescrito en el NAS\n"})
            outcome = self.rebuild(space)
            self.assertIn(REBUILT, outcome.out)
            self.assertIn(f"{CODE}/.git/index", outcome.out)
            state = safe_mirror.load_base(space.dest, space.env())
            assert state is not None
            self.assertEqual(state.files, {
                rel: safe_mirror.FileState(info["size"], info["mtime_ns"], info["sha256"])
                for rel, info in mirror.describe(space.dest).items()
            })
            listing = safe_mirror.scan_destination(space.dest)
            source = safe_mirror.scan_source(space.project)
            changes, _observed = safe_mirror.destination_changes(space.dest, state, source, listing)
            self.assertEqual(changes, [])

    def test_rehacer_estado_refuses_work_files(self) -> None:
        """RF-007-32: un fichero de trabajo cambiado en el destino cuyo contenido no está
        en el historial del PC, o uno borrado, o una carpeta nueva, no se acepta: código 3
        nombrándolos, sin tocar el estado."""
        listing = f"{'1' * 40}\n"
        fake = FakeGit({("*", "hash-object"): (0, f"{'2' * 40}\n"), ("*", "rev-list --objects"): (0, listing)})
        with contextlib.ExitStack() as stack:
            space = self.mirrored_space(stack)
            state = safe_mirror.state_file(space.dest, space.env())
            saved = state.read_bytes()
            write_files(space.dest, {layout.DOCS_MARKER: "# Cambiada en el NAS\n"})
            (space.dest / CODE / layout.CHECK_RELPATH).unlink()
            (space.dest / "Documentacion").mkdir()
            outcome = self.rebuild(space, fake, code=3)
            self.assertEqual(state.read_bytes(), saved)
        for text in (layout.DOCS_MARKER, f"{CODE}/{layout.CHECK_RELPATH}", "Documentacion"):
            self.assertIn(text, outcome.out)
        self.assertIn("no está en el historial", outcome.out)
        self.assertIn(f"{CHANGES} (3)", outcome.out)

    def test_rehacer_estado_ref_only_in_dest(self) -> None:
        """RF-007-32: una rama que solo está en el ``.git`` del destino (su commit no está
        en el PC): código 3 nombrándola, con cómo traerla."""
        unknown = "9" * 40
        fake = FakeGit({("code", f"cat-file -e {unknown}"): (1, "")})
        with contextlib.ExitStack() as stack:
            space = self.mirrored_space(stack)
            write_files(space.dest, {f"{CODE}/.git/refs/heads/hecha-en-el-nas": f"{unknown}\n"})
            outcome = self.rebuild(space, fake, code=3)
        self.assertIn(f"refs/heads/hecha-en-el-nas → {unknown[:12]}", outcome.out)
        self.assertIn("fetch", outcome.out)

    def test_rehacer_estado_stash_only_in_dest(self) -> None:
        """RF-007-32: un ``stash`` que solo está en el ``.git`` del destino (de la
        documentación): código 3 nombrándolo."""
        unknown = "8" * 40
        fake = FakeGit({("docs", f"cat-file -e {unknown}"): (1, "")})
        with contextlib.ExitStack() as stack:
            space = self.mirrored_space(stack)
            write_files(space.dest, {".git/refs/stash": f"{unknown}\n"})
            outcome = self.rebuild(space, fake, code=3)
        self.assertIn(f"refs/stash → {unknown[:12]}", outcome.out)

    def test_rehacer_estado_content_in_history(self) -> None:
        """RF-007-32: un fichero de trabajo del destino con el contenido de un commit del
        PC (una versión anterior) se acepta: estado rehecho, con el motivo."""
        blob = "3" * 40
        fake = FakeGit({
            ("*", "hash-object"): (0, f"{blob}\n"),
            ("*", "rev-list --objects"): (0, f"{'4' * 40}\n{blob} docs/constitution.md\n"),
        })
        with contextlib.ExitStack() as stack:
            space = self.mirrored_space(stack)
            write_files(space.dest, {layout.DOCS_MARKER: "# Versión anterior\n"})
            outcome = self.rebuild(space, fake)
        self.assertIn(REBUILT, outcome.out)
        self.assertIn("en el historial", outcome.out)
        command = next(c for c in fake.commands("docs") if c.startswith("hash-object"))
        self.assertIn(f"--path={layout.DOCS_MARKER}", command)

    def test_rehacer_estado_without_base(self) -> None:
        """RF-007-32, RF-007-31: sin estado ni foto (o con el estado ilegible, que se
        guarda aparte), se compara con un estado vacío: un destino igual que el PC se
        acepta entero y pasa a ser el estado."""
        with contextlib.ExitStack() as stack:
            space = self.mirrored_space(stack)
            state = safe_mirror.state_file(space.dest, space.env())
            state.unlink()
            for photo in mirror.state_folder(space.profile).glob("foto-*.json"):
                photo.unlink()
            self.assertStopped(space, 2)
            outcome = self.rebuild(space)
            self.assertIn(REBUILT, outcome.out)
            self.assertTrue(state.exists())
            state.write_bytes(b"{roto")
            outcome = self.rebuild(space)
            aside = list(state.parent.glob(f"{state.stem}.ilegible-*.json"))
            self.assertEqual([path.read_bytes() for path in aside], [b"{roto"])
            self.assertIn(REBUILT, outcome.out)
            self.assertIsNotNone(safe_mirror.load_base(space.dest, space.env()))

    def test_rehacer_estado_touches_nothing(self) -> None:
        """RF-007-32: ``--rehacer-estado`` con un destino sin cambios: estado rehecho, y
        ni subida, ni comprobaciones, ni espejo (el destino, igual)."""
        with contextlib.ExitStack() as stack:
            space = self.mirrored_space(stack)
            outcome = self.rebuild(space)
        self.assertIn(REBUILT, outcome.out)
        self.assertNotIn(f"correcto  {publish.STEP_MIRROR}", outcome.out)


class EnvironTest(unittest.TestCase):
    def test_main_always_with_environ(self) -> None:
        """Plan 007 §7.1: ninguna prueba llama a ``publish.main`` sin su entorno
        (nunca lee ``GEOBLENDER_NAS_ESPEJO``, ``GEOBLENDER_DOCS_DIR`` ni ``LOCALAPPDATA``
        del puesto)."""
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "main"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "publish"
        ]
        self.assertTrue(calls)
        for call in calls:
            with self.subTest(linea=call.lineno):
                self.assertIn("environ", {keyword.arg for keyword in call.keywords})


def real_workspace(project: gitrepo.GitProject) -> Workspace:
    """El :class:`Workspace` de una copia de la plantilla: su destino vacío con su foto
    (el primer espejo) y su perfil local, junto a la carpeta del proyecto."""
    space = Workspace(project.base)
    space.dest.mkdir()
    space.profile.mkdir()
    mirror.write_photo(space.profile, space.dest, files={})
    return space


@requires(gitrepo.GIT, gitrepo.GIT_HINT)
class PublishedTest(unittest.TestCase):
    """Una publicación de verdad, hecha una vez por clase (``setUpClass``) sobre una
    copia de la plantilla con un commit nuevo y una etiqueta anotada en el código; cada
    prueba mira una parte de su resultado (RNF-007-01: una sola publicación con git)."""

    TAG = "v0.1.0-prueba"
    project: gitrepo.GitProject
    space: Workspace
    outcome: Outcome
    head: str
    docs_head: str
    indexes: dict[Path, tuple[int, int]]

    @classmethod
    def setUpClass(cls) -> None:
        project = gitrepo.shared_template().project()
        cls.project = project
        try:
            cls.space = real_workspace(project)
            (project.code / "README.md").write_text("# Código de prueba, 2\n", encoding="utf-8")
            project.git(project.code, "commit", "-q", "-a", "-m", "segundo")
            project.git(project.code, "tag", "-a", cls.TAG, "-m", "versión de prueba")
            cls.head = project.git(project.code, "rev-parse", "HEAD").stdout.strip()
            cls.docs_head = project.git(project.docs, "rev-parse", "HEAD").stdout.strip()
            cls.indexes = cls.index_stats()
            cls.outcome = run_publish(cls.space, real_git=project.runner())
        except BaseException:
            project.close()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        cls.project.close()

    @classmethod
    def index_stats(cls) -> dict[Path, tuple[int, int]]:
        """Tamaño y fecha del ``.git/index`` de los dos repositorios."""
        stats = {}
        for repo in (cls.project.docs, cls.project.code):
            info = (repo / ".git" / "index").stat()
            stats[repo] = (info.st_size, info.st_mtime_ns)
        return stats

    def test_mirror_has_both_histories(self) -> None:
        """RF-007-22: un clon hecho desde cada ``.git`` del destino tiene su historial:
        la rama de cada repositorio en el commit del PC (el del código, con la etiqueta)."""
        project = self.project
        for rel, wanted in ((".", self.docs_head), (CODE, f"{self.TAG}^{{commit}}")):
            with self.subTest(repositorio=rel), tempfile.TemporaryDirectory() as tmp:
                clone = Path(tmp) / "clon"
                source = str(self.space.dest / rel)
                project.git(Path(tmp), "clone", "-q", "--no-checkout", source, str(clone))
                found = project.git(clone, "rev-parse", "HEAD", wanted).stdout.split()
                expected = self.docs_head if rel == "." else self.head
                self.assertEqual(found, [expected, expected])

    def test_reads_keep_index(self) -> None:
        """RF-007-15 (plan §2.1, 16): las lecturas de git de la publicación no
        reescriben el ``.git/index`` de ninguno de los dos repositorios."""
        self.assertEqual(self.index_stats(), self.indexes)

    def test_read_only_git_keeps_index(self) -> None:
        """RF-007-23, RF-007-30, RNF-007-04: con git de verdad, la publicación termina con
        0 y deja el destino igual que la carpeta del proyecto, fichero a fichero; y
        después nada de los dos ``.git`` ni del destino ha cambiado respecto al estado
        guardado: otra publicación no copiaría nada (sin cambios del NAS ni sha256
        distintos)."""
        self.assertEqual(self.outcome.code, 0, self.outcome.text)
        dest, project = mirror.describe(self.space.dest), mirror.describe(self.project.docs)
        self.assertEqual(
            {rel: info["sha256"] for rel, info in dest.items()},
            {rel: info["sha256"] for rel, info in project.items()},
        )
        environ = self.space.env()
        base = safe_mirror.load_base(self.space.dest, environ)
        assert base is not None
        self.assertFalse(base.photo)
        source = safe_mirror.scan_source(self.project.docs)
        listing = safe_mirror.scan_destination(self.space.dest)
        changes, observed = safe_mirror.destination_changes(
            self.space.dest, base, source, listing
        )
        self.assertEqual(changes, [])
        to_copy = [rel for rel, sha in source.files.items() if observed[rel].sha256 != sha]
        self.assertEqual(to_copy, [])
        self.assertEqual(observed, base.files)

    def test_push_branch_and_tags(self) -> None:
        """RF-007-20: con git de verdad, un commit nuevo y una etiqueta anotada en el
        código: el remoto desnudo acaba con la rama en ese commit y con la etiqueta; la
        documentación no tiene remoto y no se sube."""
        project, outcome = self.project, self.outcome
        self.assertIn(f"correcto  {publish.STEP_PUSH}", outcome.out, outcome.text)
        listing = project.git(project.remote, "show-ref").stdout.splitlines()
        refs = {name: sha for sha, name in (line.split(" ", 1) for line in listing)}
        self.assertEqual(refs.get("refs/heads/main"), self.head)
        tag = project.git(project.remote, "rev-parse", f"{self.TAG}^{{commit}}").stdout
        self.assertEqual(tag.strip(), self.head)
        self.assertNotIn(f"refs/heads/{DOCS_BRANCH}", refs)


if __name__ == "__main__":
    unittest.main()

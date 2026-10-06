# SPDX-License-Identifier: GPL-3.0-or-later
"""La publicación, ``tools/publish.py`` (spec 007, HU-007-4 y HU-007-7; plan 007 §5.4.5).

Casi todas las pruebas trabajan sobre una carpeta del proyecto temporal escrita a mano
(la documentación con ``docs/constitution.md`` y su ``.git``, y dentro el código con el
suyo) y un ejecutor de git simulado (:class:`FakeGit`) que responde como git sin
lanzarlo: así cuestan milisegundos (RNF-007-01). Las de extremo a extremo
(:class:`EndToEndTest`) usan git de verdad sobre una copia de la plantilla de
``tests.support.gitrepo`` (la documentación, el código anidado y un remoto desnudo en
``%TEMP%``), construida una vez por clase, con la configuración de git aislada.

Ninguna prueba lee ``GEOBLENDER_NAS_ESPEJO``, ``GEOBLENDER_DOCS_DIR`` ni ``LOCALAPPDATA``
del puesto: cada una pasa su entorno a ``publish.main`` (``test_main_always_with_environ``
lo comprueba), con el perfil local en su carpeta temporal. Ninguna escribe fuera de
ella: ni GitHub, ni el NAS, ni el estado real del espejo.
"""

import ast
import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from tests.support import gitrepo
from tests.support.repo import tools_on_path
from tests.support.resources import requires

tools_on_path()

import publish  # noqa: E402
from gbtools import layout  # noqa: E402
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

# La carpeta del proyecto de prueba (texto UTF-8 y LF): la documentación y, dentro, el
# código; cada uno con un .git mínimo escrito a mano (FakeGit responde por git).
DOCS_FILES: Mapping[str, str] = {
    layout.DOCS_MARKER: "# Constitución\n",
    "README.md": "# Documentación de prueba\n",
    ".gitignore": f"/{CODE}/\n",
    ".git/HEAD": f"ref: refs/heads/{DOCS_BRANCH}\n",
    ".git/config": "[core]\n\tbare = false\n",
    f".git/refs/heads/{DOCS_BRANCH}": f"{SHA_DOCS}\n",
}
CODE_FILES: Mapping[str, str] = {
    layout.MANIFEST_RELPATH: 'schema_version = "1.0.0"\nblender_version_min = "5.2.0"\n',
    layout.CHECK_RELPATH: SPDX,
    "README.md": "# Código de prueba\n",
    ".git/HEAD": f"ref: refs/heads/{CODE_BRANCH}\n",
    ".git/config": f'[core]\n\tbare = false\n[remote "origin"]\n\turl = {CODE_URL}\n',
    f".git/refs/heads/{CODE_BRANCH}": f"{SHA_CODE}\n",
}

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
        self, check: tuple[int, str] = (0, CHECK_GREEN), docs: tuple[int, str] = (0, DOCS_GREEN)
    ) -> None:
        self.check, self.docs = check, docs
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
        code, out = self.docs if "tools/check_docs.py" in parts else self.check
        return subprocess.CompletedProcess(parts, code, out, "")

    def scripts(self) -> list[str]:
        return [next(p for p in cmd if p.startswith("tools/")) for cmd, _cwd in self.calls]


class FakeGit:
    """Ejecutor de git simulado: responde como git en la documentación («docs») o en el
    código («code», la carpeta ``CODE``), con respuestas por defecto de dos árboles
    limpios en una rama y las de ``overrides`` (``(repositorio o «*», prefijo de la
    orden)`` → ``(código, salida[, error])``, o una lista de respuestas que se dan por
    orden, la última para siempre), y anota cada orden."""

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
        return subprocess.CompletedProcess(parts, code, out, err)

    def commands(self, repo: str | None = None) -> list[str]:
        """Las órdenes lanzadas (sin «git»), de un repositorio o de los dos."""
        return [" ".join(cmd[1:]) for who, cmd in self.calls if repo in (None, who)]


def write_files(root: Path, files: Mapping[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
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
    docs: Mapping[str, str] | None = None, code: Mapping[str, str] | None = None
) -> Iterator[Workspace]:
    """Un :class:`Workspace` con la carpeta del proyecto de prueba (más ``docs`` y
    ``code``) y un destino vacío; se borra al salir."""
    with tempfile.TemporaryDirectory(prefix="geoblender-publicacion-") as tmp:
        space = Workspace(Path(tmp).resolve())
        write_files(space.project, {**DOCS_FILES, **(docs or {})})
        write_files(space.code, {**CODE_FILES, **(code or {})})
        space.dest.mkdir()
        space.profile.mkdir()
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
) -> Outcome:
    """``publish.main`` con ``--destino`` = el destino de ``space`` (salvo que ``args``
    traiga otro), su entorno, el ejecutor de git (simulado si no se da otro) y las
    comprobaciones simuladas (en verde si no se dan otras)."""
    fake = git_runner if git_runner is not None else FakeGit()
    checks = checks if checks is not None else FakeChecks()
    argv = list(args)
    if publish.OPTION_DEST not in argv:
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
        self.assertIn(NOT_PUBLISHED, outcome.out)
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
            outcome = run_publish(space, environ=same)
            self.assertNotIn(layout.ENV_DOCS_DIR, outcome.out, outcome.text)


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
        fake = FakeGit({("docs", "symbolic-ref"): (1, "")})
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
        reads = ("rev-parse", "symbolic-ref", "status", "config", "ls-files")
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
        """RF-007-16: las dos con el Python del Blender localizado (``-B -s -X utf8``),
        desde la raíz del código: ``tools/check.py`` y ``tools/check_docs.py`` con la
        carpeta del proyecto; después de los árboles, que se miran otra vez."""
        fake = FakeGit()
        with workspace() as space:
            outcome = run_publish(space, git_runner=fake)
            project = space.project
        self.assertEqual(outcome.checks.scripts(), ["tools/check.py", "tools/check_docs.py"])
        for cmd, cwd in outcome.checks.calls:
            self.assertEqual(cmd[:5], [str(INSTALL.python), "-B", "-s", "-X", "utf8"])
            self.assertEqual(cwd, project / CODE)
        self.assertEqual(outcome.checks.calls[1][0][-1], str(project))
        self.assertEqual(len([c for c in fake.commands() if c.startswith("status")]), 4)
        self.assertIn("RESULTADO: VERDE (1,0 s)", outcome.out)
        self.assertIn("DOCUMENTACIÓN CORRECTA", outcome.out)

    def test_solo_espejo_skips_code_check(self) -> None:
        """RF-007-16, RF-007-24: con ``--solo-espejo`` no se comprueba el código, pero sí
        la documentación."""
        with workspace() as space:
            outcome = run_publish(space, publish.OPTION_MIRROR_ONLY)
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


@requires(gitrepo.GIT, gitrepo.GIT_HINT)
class EndToEndTest(PublicationAssertions):
    """Con git de verdad, sobre una copia de la plantilla de la clase."""

    template: gitrepo.GitTemplate

    @classmethod
    def setUpClass(cls) -> None:
        cls.template = gitrepo.GitTemplate()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.template.close()

    def setUp(self) -> None:
        self.project = self.template.project()
        self.addCleanup(self.project.close)
        self.space = Workspace(self.project.base)
        self.space.dest.mkdir()
        self.space.profile.mkdir()

    def publish(self, *args: str) -> Outcome:
        return run_publish(self.space, *args, real_git=self.project.runner())

    def remote_refs(self) -> str:
        return self.project.git(self.project.remote, "show-ref").stdout

    def test_dirty_trees_with_git(self) -> None:
        """RF-007-15: con git de verdad, un cambio sin commit en el código y un fichero
        nuevo en la documentación: código 1 con los dos, sin subir (el remoto, igual) ni
        tocar el destino; las lecturas no reescriben ``.git/index``."""
        (self.project.code / "README.md").write_text("cambiado\n", encoding="utf-8")
        (self.project.docs / "nota.txt").write_text("x\n", encoding="utf-8")
        index = self.project.code / ".git" / "index"
        index_before = (index.stat().st_size, index.stat().st_mtime_ns)
        refs = self.remote_refs()
        before = gbrepo.snapshot(self.space.dest)
        outcome = self.publish()
        self.assertEqual(outcome.code, 1, outcome.text)
        for text in ("código", "README.md", "documentación", "nota.txt"):
            self.assertIn(text, outcome.out)
        self.assertEqual(self.remote_refs(), refs)
        self.assertEqual(gbrepo.snapshot_changes(before, gbrepo.snapshot(self.space.dest)), [])
        self.assertEqual((index.stat().st_size, index.stat().st_mtime_ns), index_before)


if __name__ == "__main__":
    unittest.main()

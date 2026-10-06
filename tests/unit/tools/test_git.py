# SPDX-License-Identifier: GPL-3.0-or-later
"""Las lecturas de git de la publicación, ``gbtools.git`` (spec 007, T19; plan 007 §5.3).

Las de interpretación usan un ejecutor simulado con respuestas fijas; las de extremo a
extremo, una carpeta del proyecto temporal con la documentación, el código anidado y un
remoto desnudo (``tests.support.gitrepo``), copiada de una plantilla que se construye
una vez por clase, con la configuración de git aislada: ninguna lee la del usuario ni la
del sistema, y ninguna deja procesos de git en segundo plano (``gc.auto=0``,
``maintenance.auto=false``). Sin git, se omiten con ``[ENTORNO] git``.
"""

import os
import subprocess
import unittest
from collections.abc import Mapping, Sequence
from pathlib import Path
from unittest import mock

from tests.support import gitrepo
from tests.support.repo import tools_on_path
from tests.support.resources import requires
from tests.support.trees import temp_tree

tools_on_path()

from gbtools import git  # noqa: E402
from gbtools.layout import CODE_DIR_IN_DOCS  # noqa: E402


class FakeGit:
    """Ejecutor simulado: anota cada orden y responde según sus argumentos."""

    def __init__(self, answers: Mapping[str, tuple[int, str]] | None = None) -> None:
        self.answers = dict(answers or {})
        self.calls: list[tuple[list[str], dict[str, str], Path | None, float | None]] = []

    def __call__(
        self,
        cmd: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: Path | None = None,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        parts = [str(part) for part in cmd]
        self.calls.append((parts, dict(env or {}), cwd, timeout))
        key = " ".join(parts[1:])
        for prefix, (code, out) in self.answers.items():
            if key.startswith(prefix):
                return subprocess.CompletedProcess(parts, code, out, "")
        return subprocess.CompletedProcess(parts, 0, "", "")


class ReadsTest(unittest.TestCase):
    """Cómo se lanzan las lecturas y cómo se interpreta su salida (sin git)."""

    def test_reads_without_optional_locks(self) -> None:
        """RF-007-15: cada lectura se lanza en la raíz, con tiempo máximo,
        ``GIT_OPTIONAL_LOCKS=0`` y ``GIT_TERMINAL_PROMPT=0``, y sin las variables que
        cambian de repositorio (``GIT_DIR``, ``GIT_WORK_TREE``…)."""
        runner = FakeGit(
            {
                "rev-parse --show-toplevel": (0, "C:/x/proyecto\n"),
                "rev-list --count": (0, "0\n"),
            }
        )
        root = Path("C:/x/proyecto")
        inherited = {"GIT_DIR": "C:/otro/.git", "GIT_WORK_TREE": "C:/otro", "PATH": "p"}
        with mock.patch.dict(os.environ, inherited):
            git.toplevel(root, runner=runner)
            git.head(root, runner=runner)
            git.current_branch(root, runner=runner)
            git.dirty_entries(root, runner=runner)
            git.remote_url(root, runner=runner)
            git.ahead_of_remote(root, "main", runner=runner)
            git.tracked_under(root, CODE_DIR_IN_DOCS, runner=runner)
        self.assertGreaterEqual(len(runner.calls), 7)
        for cmd, env, cwd, timeout in runner.calls:
            with self.subTest(orden=" ".join(cmd)):
                self.assertEqual(cmd[0], "git")
                self.assertEqual(env.get("GIT_OPTIONAL_LOCKS"), "0")
                self.assertEqual(env.get("GIT_TERMINAL_PROMPT"), "0")
                self.assertNotIn("GIT_DIR", env)
                self.assertNotIn("GIT_WORK_TREE", env)
                self.assertEqual(env.get("PATH"), "p")
                self.assertEqual(cwd, root)
                self.assertIsNotNone(timeout)

    def test_git_missing_or_failing(self) -> None:
        """RF-007-15: sin git, o si una lectura falla, :class:`GitProblem` con lo que
        pasó (y, sin git, cómo instalarlo)."""

        def missing(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess:
            raise FileNotFoundError("git")

        with self.assertRaises(git.GitProblem) as ctx:
            git.head(Path("."), runner=missing)
        self.assertIn("Git para Windows", str(ctx.exception))
        failing = FakeGit({"rev-parse": (128, "")})
        with self.assertRaises(git.GitProblem) as ctx:
            git.head(Path("."), runner=failing)
        self.assertIn("128", str(ctx.exception))

    def test_parsing(self) -> None:
        """RF-007-15, RF-007-24: rama (``None`` con HEAD separado), cambios con
        ``--porcelain -z`` (también un renombrado y un fichero nuevo en una carpeta),
        remoto (``None`` si no hay), commits sin subir (``None`` sin la referencia del
        remoto) y entradas bajo una carpeta (sin distinguir mayúsculas, y un *gitlink*)."""
        root = Path(".")
        branch = FakeGit({"symbolic-ref": (0, "main\n")})
        self.assertEqual(git.current_branch(root, runner=branch), "main")
        detached = FakeGit({"symbolic-ref": (1, "")})
        self.assertIsNone(git.current_branch(root, runner=detached))
        status = " M docs/a.md\0R  nuevo.md\0viejo.md\0?? sub/carpeta/x.txt\0"
        self.assertEqual(
            git.dirty_entries(root, runner=FakeGit({"status": (0, status)})),
            [" M docs/a.md", "R  nuevo.md (antes viejo.md)", "?? sub/carpeta/x.txt"],
        )
        self.assertEqual(git.dirty_entries(root, runner=FakeGit({"status": (0, "")})), [])
        url = FakeGit({"config --get remote.origin.url": (0, "https://x.invalid/r.git\n")})
        self.assertEqual(git.remote_url(root, runner=url), "https://x.invalid/r.git")
        self.assertIsNone(git.remote_url(root, runner=FakeGit({"config": (1, "")})))
        ahead = FakeGit({"rev-parse": (0, "abc\n"), "rev-list --count": (0, "3\n")})
        self.assertEqual(git.ahead_of_remote(root, "main", runner=ahead), 3)
        self.assertIn(
            "refs/remotes/origin/main..refs/heads/main", " ".join(ahead.calls[-1][0])
        )
        self.assertIsNone(
            git.ahead_of_remote(root, "main", runner=FakeGit({"rev-parse": (1, "")}))
        )
        code = CODE_DIR_IN_DOCS
        listing = (
            f"100644 {'a' * 40} 0\tdocs/{code}/x.md\0"
            f"160000 {'b' * 40} 0\t{code}\0"
            f"100644 {'c' * 40} 0\t{code.lower()}/nota.md\0"
            f"100644 {'d' * 40} 0\t{code}x.md\0"
        )
        self.assertEqual(
            git.tracked_under(root, code, runner=FakeGit({"ls-files": (0, listing)})),
            [f"{code} (gitlink)", f"{code.lower()}/nota.md"],
        )


class GitDirTest(unittest.TestCase):
    """``.git`` y operaciones a medias, mirando ficheros (sin lanzar git)."""

    def test_git_dir_problem(self) -> None:
        """RF-007-15: un ``.git`` que es un fichero (*worktree* enlazado o submódulo),
        uno que toma objetos de otro (``objects/info/alternates``) o que falta, lo dice;
        uno normal, ``None``."""
        with temp_tree({".git/HEAD": "ref: refs/heads/main\n"}) as root:
            self.assertIsNone(git.git_dir_problem(root))
        with temp_tree({".git": "gitdir: C:/otro/.git/worktrees/x\n"}) as root:
            self.assertIn("worktree", git.git_dir_problem(root) or "")
        alternates = {".git/HEAD": "x\n", ".git/objects/info/alternates": "C:/otro\n"}
        with temp_tree(alternates) as root:
            self.assertIn("alternates", git.git_dir_problem(root) or "")
        with temp_tree({"a.txt": "x\n"}) as root:
            self.assertIn(".git", git.git_dir_problem(root) or "")

    def test_operations_in_progress(self) -> None:
        """RF-007-15: fusión, rebase, selección de commits, reversión o bisección a
        medias, un ``gc`` en curso y cualquier cerrojo ``*.lock`` (también en
        ``refs/``); un ``.git`` limpio, ninguna."""
        with temp_tree({"HEAD": "x\n", "objects/pack/a.pack": "x"}) as git_dir:
            self.assertEqual(git.operations_in_progress(git_dir), [])
        files = {
            "MERGE_HEAD": "x\n",
            "rebase-merge/head-name": "x\n",
            "CHERRY_PICK_HEAD": "x\n",
            "REVERT_HEAD": "x\n",
            "BISECT_LOG": "x\n",
            "gc.pid": "1 equipo\n",
            "index.lock": "",
            "refs/heads/main.lock": "",
        }
        with temp_tree(files) as git_dir:
            found = git.operations_in_progress(git_dir)
        text = "\n".join(found)
        for name in (*files, "rebase-merge"):
            if name == "rebase-merge/head-name":
                continue
            with self.subTest(fichero=name):
                self.assertIn(name, text)
        self.assertEqual(len(found), len(files))


@requires(gitrepo.GIT, gitrepo.GIT_HINT)
class EndToEndTest(unittest.TestCase):
    """Con git de verdad, sobre una copia de la plantilla de cada clase."""

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
        self.run_git = self.project.runner()

    def test_template_layout(self) -> None:
        """RF-007-15, RF-007-24, RF-007-33: la carpeta del proyecto es la documentación
        (con ``docs/constitution.md``, que ignora la carpeta del código) y dentro está el
        código, cada uno con su git limpio en ``main``; el remoto del código es el
        desnudo de esta copia (no el de la plantilla), y sin commits por subir."""
        project = self.project
        self.assertTrue((project.docs / "docs" / "constitution.md").is_file())
        self.assertEqual(project.code, project.docs / CODE_DIR_IN_DOCS)
        for repo in (project.docs, project.code):
            with self.subTest(repositorio=repo.name):
                self.assertEqual(git.toplevel(repo, runner=self.run_git), repo.resolve())
                self.assertIsNone(git.git_dir_problem(repo))
                self.assertEqual(git.dirty_entries(repo, runner=self.run_git), [])
                self.assertEqual(git.current_branch(repo, runner=self.run_git), "main")
                self.assertEqual(git.operations_in_progress(repo / ".git"), [])
        run_git = self.run_git
        self.assertIsNone(git.remote_url(project.docs, runner=run_git))
        self.assertEqual(
            Path(git.remote_url(project.code, runner=run_git) or ""), project.remote
        )
        self.assertEqual(git.ahead_of_remote(project.code, "main", runner=run_git), 0)
        self.assertEqual(
            git.tracked_under(project.docs, CODE_DIR_IN_DOCS, runner=run_git), []
        )
        head = git.head(project.code, runner=run_git)
        remote_head = project.git(project.remote, "rev-parse", "refs/heads/main").stdout
        self.assertEqual(head, remote_head.strip())

    def test_reads_do_not_rewrite_index(self) -> None:
        """RF-007-15 (plan §2.1, 16): con un fichero tocado (otra fecha, el mismo
        contenido), las lecturas no reescriben ``.git/index``; un ``git status`` normal,
        sí (control). Y un cambio, un fichero nuevo y un commit sin subir se ven."""
        project = self.project
        readme = project.code / "README.md"
        index = project.code / ".git" / "index"
        before = index.stat()
        stamp = readme.stat().st_mtime_ns + 10**9
        os.utime(readme, ns=(stamp, stamp))
        self.assertEqual(git.dirty_entries(project.code, runner=self.run_git), [])
        git.head(project.code, runner=self.run_git)
        after = index.stat()
        self.assertEqual(
            (after.st_size, after.st_mtime_ns), (before.st_size, before.st_mtime_ns)
        )
        project.git(project.code, "status", "--porcelain")
        self.assertNotEqual(index.stat().st_mtime_ns, before.st_mtime_ns)

        readme.write_text("cambiado\n", encoding="utf-8")
        (project.code / "tools" / "nuevo").mkdir()
        (project.code / "tools" / "nuevo" / "a.py").write_text("x\n", encoding="utf-8")
        self.assertEqual(
            git.dirty_entries(project.code, runner=self.run_git),
            [" M README.md", "?? tools/nuevo/a.py"],
        )
        project.git(project.code, "commit", "-q", "-a", "-m", "cambio")
        self.assertEqual(git.ahead_of_remote(project.code, "main", runner=self.run_git), 1)

    def test_gitlink_in_docs(self) -> None:
        """RF-007-15: si la documentación versiona la carpeta del código (``git add -f``
        de un repositorio anidado: un *gitlink*), ``tracked_under`` lo nombra."""
        project = self.project
        project.git(project.docs, "add", "-f", CODE_DIR_IN_DOCS)
        found = git.tracked_under(project.docs, CODE_DIR_IN_DOCS, runner=self.run_git)
        self.assertEqual(found, [f"{CODE_DIR_IN_DOCS} (gitlink)"])

    def test_isolated_config(self) -> None:
        """T19: git solo lee la configuración del repositorio y la de las pruebas (por
        entorno): ninguna global ni de sistema; sin ``gc`` ni mantenimiento en segundo
        plano, sin preguntas y con la identidad y la rama fijadas."""
        listing = self.project.git(
            self.project.code, "config", "--list", "--show-scope"
        ).stdout.splitlines()
        scopes = {line.split("\t", 1)[0] for line in listing}
        self.assertLessEqual(scopes, {"local", "command"}, listing)
        values = dict(line.split("\t", 1)[1].split("=", 1) for line in listing)
        self.assertEqual(values.get("gc.auto"), "0")
        self.assertEqual(values.get("maintenance.auto"), "false")
        self.assertEqual(values.get("init.defaultbranch"), "main")
        self.assertEqual(values.get("user.email"), gitrepo.IDENTITY[1])
        self.assertEqual(self.project.global_config.read_bytes(), b"")
        env = self.project.env()
        self.assertEqual(env["GIT_CONFIG_NOSYSTEM"], "1")
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: GPL-3.0-or-later
"""Las lecturas de git de la publicación, ``gbtools.git`` (spec 007, T19; plan 007 §5.3).

Las de interpretación usan un ejecutor simulado con respuestas fijas; las de extremo a
extremo, una carpeta del proyecto temporal con la documentación, el código anidado y un
remoto desnudo (``tests.support.gitrepo``), copiada de una plantilla que se construye
una vez por proceso, con la configuración de git aislada: ninguna lee la del usuario ni la
del sistema, y ninguna deja procesos de git en segundo plano (``gc.auto=0``,
``maintenance.auto=false``). Sin git, se omiten con ``[ENTORNO] git``.
"""

import os
import shutil
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


class TreeStatusTest(unittest.TestCase):
    """Rama, commit y cambios de un repositorio en una sola orden
    (``git status --porcelain=v2 --branch -z``)."""

    def test_tree_status_parsing(self) -> None:
        """RF-007-15, RF-007-23: la rama (``None`` si HEAD está separado), el commit
        (``None`` sin commits) y cada cambio como ``"XY ruta"`` (también un renombrado,
        un conflicto y un fichero nuevo), con una sola orden sin cerrojos opcionales."""
        sha = "a" * 40
        modes = "N... 100644 100644 100644"
        out = (
            f"# branch.oid {sha}\0# branch.head main\0# branch.upstream origin/main\0"
            "# branch.ab +1 -0\0"
            f"1 .M {modes} {sha} {sha} docs/a.md\0"
            f"2 R. {modes} {sha} {sha} R100 nuevo.md\0viejo.md\0"
            f"u UU N... 100644 100644 100644 100644 {sha} {sha} {sha} conflicto.md\0"
            "? sub/carpeta/x.txt\0"
        )
        runner = FakeGit({"status": (0, out)})
        status = git.tree_status(Path("C:/x"), runner=runner)
        self.assertEqual((status.branch, status.commit), ("main", sha))
        self.assertEqual(
            status.entries,
            [" M docs/a.md", "R  nuevo.md (antes viejo.md)", "UU conflicto.md", "?? sub/carpeta/x.txt"],
        )
        command, env, _cwd, _timeout = runner.calls[0]
        self.assertEqual(command[1:4], ["status", "--porcelain=v2", "--branch"])
        self.assertEqual(env.get("GIT_OPTIONAL_LOCKS"), "0")
        detached = "# branch.oid " + sha + "\0# branch.head (detached)\0"
        status = git.tree_status(Path("."), runner=FakeGit({"status": (0, detached)}))
        self.assertEqual((status.branch, status.commit, status.entries), (None, sha, []))
        initial = "# branch.oid (initial)\0# branch.head main\0"
        status = git.tree_status(Path("."), runner=FakeGit({"status": (0, initial)}))
        self.assertEqual((status.branch, status.commit), ("main", None))


class CredentialsTest(unittest.TestCase):
    """RF-007-19: credenciales en la dirección de ``origin`` o en el texto de un
    ``.git/config`` (sin lanzar git); el mensaje nunca muestra el secreto."""

    SECRET = "secreto-de-prueba"

    def assertProblem(self, url: str | None, text: str, *expected: str) -> str:
        problem = git.credential_problem(url, text)
        self.assertIsNotNone(problem, (url, text))
        assert problem is not None
        self.assertNotIn(self.SECRET, problem)
        for piece in expected:
            self.assertIn(piece, problem)
        return problem

    def test_credentials_in_url(self) -> None:
        """RF-007-19: usuario con contraseña (o token) en la dirección, o en http(s) un
        usuario que no es «git» (un token puesto como usuario)."""
        for url in (
            f"https://usuario:{self.SECRET}@github.invalid/pruebas/codigo.git",
            f"https://{self.SECRET}@github.invalid/pruebas/codigo.git",
            f"http://usuario:{self.SECRET}@github.invalid/codigo",
            f"ssh://git:{self.SECRET}@github.invalid/codigo.git",
        ):
            with self.subTest(direccion=url.replace(self.SECRET, "…")):
                self.assertProblem(url, "", "origin")
        for url in (
            "https://github.invalid/pruebas/codigo.git",
            "https://git@github.invalid/pruebas/codigo.git",
            None,
        ):
            with self.subTest(direccion=url):
                self.assertIsNone(git.credential_problem(url, ""))

    def test_credentials_in_insteadof(self) -> None:
        """RF-007-19: una regla ``url.<…>.insteadOf`` (o cualquier dirección del
        ``.git/config``) con credenciales, con su línea."""
        text = (
            "[core]\n\tbare = false\n"
            f'[url "https://usuario:{self.SECRET}@github.invalid/"]\n'
            "\tinsteadOf = https://github.invalid/\n"
        )
        self.assertProblem(None, text, ".git/config", "línea 3")
        value = f"[url \"https://github.invalid/\"]\n\tinsteadOf = https://x:{self.SECRET}@otro.invalid/\n"
        self.assertProblem(None, value, "línea 2")
        remote = f'[remote "origin"]\n\turl = https://{self.SECRET}@github.invalid/x.git\n'
        self.assertProblem(None, remote, "línea 2")

    def test_extraheader(self) -> None:
        """RF-007-19: una cabecera de autorización (``http.extraHeader``, con o sin
        dirección, con cualquier mayúscula)."""
        for text in (
            f'[http "https://github.invalid/"]\n\textraheader = AUTHORIZATION: basic {self.SECRET}\n',
            f"[http]\n\textraHeader = Authorization: bearer {self.SECRET}\n",
        ):
            with self.subTest(texto=text.splitlines()[0]):
                self.assertProblem(None, text, "línea 2", "cabecera")

    def test_ssh_url_ok(self) -> None:
        """RF-007-19: una dirección SSH con el usuario «git» (también la forma
        ``git@servidor:ruta``) y una configuración normal no son credenciales."""
        text = (
            "[core]\n\trepositoryformatversion = 0\n"
            '[remote "origin"]\n\turl = git@github.invalid:pruebas/codigo.git\n'
            "\tfetch = +refs/heads/*:refs/remotes/origin/*\n"
            '[branch "main"]\n\tremote = origin\n\tmerge = refs/heads/main\n'
        )
        for url in ("git@github.invalid:pruebas/codigo.git", "ssh://git@github.invalid/x.git"):
            with self.subTest(direccion=url):
                self.assertIsNone(git.credential_problem(url, text))


class RebuildReadsTest(unittest.TestCase):
    """RF-007-32 (D-16): lo que mira ``--rehacer-estado`` antes de aceptar el destino,
    sin lanzar git en el destino."""

    def test_unknown_refs(self) -> None:
        """RF-007-32: las referencias del ``.git`` del destino se leen como texto
        (``HEAD`` separado, ``refs/**`` —ramas, etiquetas, ``stash``— y
        ``packed-refs``; las simbólicas se saltan) y se nombran las que apuntan a un
        commit que el repositorio del PC no tiene (``cat-file -e <id>^{commit}``, una
        vez por commit)."""
        known, unknown, other = "a" * 40, "b" * 40, "c" * 40
        files = {
            "HEAD": f"{unknown}\n",
            "refs/heads/main": f"{known}\n",
            "refs/heads/nas": f"{unknown}\n",
            "refs/remotes/origin/HEAD": "ref: refs/remotes/origin/main\n",
            "refs/stash": f"{other}\n",
            "packed-refs": (
                "# pack-refs with: peeled fully-peeled sorted\n"
                f"{known} refs/tags/v0.1.0\n^{other}\n{other} refs/heads/vieja\n"
            ),
        }
        runner = FakeGit({f"cat-file -e {unknown}": (1, ""), f"cat-file -e {other}": (1, "")})
        with temp_tree(files) as git_dir:
            found = git.unknown_refs(git_dir, Path("C:/x/codigo"), runner=runner)
        self.assertEqual(
            found,
            [
                f"HEAD → {unknown[:12]}",
                f"refs/heads/nas → {unknown[:12]}",
                f"refs/heads/vieja → {other[:12]}",
                f"refs/stash → {other[:12]}",
            ],
        )
        checked = [cmd[2:] for cmd, _env, _cwd, _timeout in runner.calls]
        self.assertEqual(len(checked), 3, checked)
        for cmd, _env, cwd, _timeout in runner.calls:
            self.assertEqual(cwd, Path("C:/x/codigo"))
        with temp_tree({"HEAD": "ref: refs/heads/main\n"}) as git_dir:
            self.assertEqual(git.unknown_refs(git_dir, Path("."), runner=FakeGit()), [])

    def test_in_history(self) -> None:
        """RF-007-32: un fichero del destino está en el historial del PC si su blob (con
        los filtros de su ruta: ``hash-object --path``, sin escribir) está en algún
        commit alcanzable desde una rama o una etiqueta."""
        blob = "d" * 40
        listing = f"{'e' * 40}\n{blob} docs/a.md\n{'f' * 40} docs\n"
        runner = FakeGit({"hash-object": (0, f"{blob}\n"), "rev-list --objects": (0, listing)})
        with temp_tree({"a.md": "x\n"}) as folder:
            self.assertTrue(git.in_history(Path("."), "docs/a.md", folder / "a.md", runner=runner))
            command = runner.calls[0][0]
            self.assertEqual(command[1:3], ["hash-object", "--path=docs/a.md"])
            self.assertNotIn("-w", command)
            other = FakeGit({"hash-object": (0, f"{'9' * 40}\n"), "rev-list --objects": (0, listing)})
            self.assertFalse(git.in_history(Path("."), "docs/a.md", folder / "a.md", runner=other))
        self.assertIn("--branches", " ".join(runner.calls[1][0]))
        self.assertIn("--tags", " ".join(runner.calls[1][0]))


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
class ReadOnlyEndToEndTest(unittest.TestCase):
    """Con git de verdad, sobre una copia de la plantilla para toda la clase: estas
    pruebas no cambian los repositorios (RNF-007-01: una copia en lugar de una por
    prueba). Las lecturas de la publicación con git de verdad (``toplevel``,
    ``remote_url``, ``tree_status`` y ``tracked_under`` en los dos repositorios) las
    hace ``test_publish.py::PublishedTest``."""

    project: gitrepo.GitProject

    @classmethod
    def setUpClass(cls) -> None:
        cls.project = gitrepo.shared_template().project()
        cls.run_git = staticmethod(cls.project.runner())

    @classmethod
    def tearDownClass(cls) -> None:
        cls.project.close()

    def test_template_layout(self) -> None:
        """RF-007-15, RF-007-24, RF-007-33: la carpeta del proyecto es la documentación
        (con ``docs/constitution.md``, que ignora la carpeta del código) y dentro está el
        código, cada uno con su ``.git`` sin operaciones a medias; el remoto del código
        es el desnudo de esta copia (no el de la plantilla), con la rama del código: el
        código está limpio en ``main`` y sin commits por subir."""
        project = self.project
        self.assertTrue((project.docs / "docs" / "constitution.md").is_file())
        self.assertEqual(project.code, project.docs / CODE_DIR_IN_DOCS)
        self.assertIn(f"/{CODE_DIR_IN_DOCS}/", (project.docs / ".gitignore").read_text("utf-8"))
        for repo in (project.docs, project.code):
            with self.subTest(repositorio=repo.name):
                self.assertIsNone(git.git_dir_problem(repo))
                self.assertEqual(git.operations_in_progress(repo / ".git"), [])
        config = (project.code / ".git" / "config").read_text(encoding="utf-8")
        self.assertIn(f"url = {project.remote.as_posix()}", config)
        remote_head = (project.remote / "refs" / "heads" / "main").read_text("utf-8").strip()
        status = git.tree_status(project.code, runner=self.run_git)
        self.assertEqual((status.branch, status.entries, status.commit), ("main", [], remote_head))
        self.assertEqual(git.ahead_of_remote(project.code, "main", runner=self.run_git), 0)

    def test_rebuild_reads_with_git(self) -> None:
        """RF-007-32: con git de verdad, una copia del ``.git`` del código con un commit
        que solo está en ella (una rama hecha «en el NAS»): ``unknown_refs`` la nombra y
        no las demás; y ``in_history`` reconoce un fichero con el contenido de un commit
        y no uno nuevo."""
        project = self.project
        copy = project.base / "destino-git"
        shutil.copytree(project.code / ".git", copy)
        commit = project.git(
            project.code, f"--git-dir={copy}", "commit-tree", "HEAD^{tree}", "-p", "HEAD",
            "-m", "hecho en el NAS",
        ).stdout.strip()
        (copy / "refs" / "heads" / "nas").write_text(f"{commit}\n", encoding="utf-8")
        found = git.unknown_refs(copy, project.code, runner=self.run_git)
        self.assertEqual(found, [f"refs/heads/nas → {commit[:12]}"])
        readme = project.base / "README.md"
        readme.write_bytes((project.code / "README.md").read_bytes())
        objects = git.history_objects(project.code, runner=self.run_git)
        for content, expected in ((None, True), (b"# Sin commit que lo tenga\n", False)):
            if content is not None:
                readme.write_bytes(content)
            with self.subTest(en_el_historial=expected):
                found = git.in_history(project.code, "README.md", readme, self.run_git, objects)
                self.assertEqual(found, expected)

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


@requires(gitrepo.GIT, gitrepo.GIT_HINT)
class EndToEndTest(unittest.TestCase):
    """Con git de verdad, sobre una copia de la plantilla para cada prueba (estas
    cambian los repositorios)."""

    template: gitrepo.GitTemplate

    @classmethod
    def setUpClass(cls) -> None:
        cls.template = gitrepo.shared_template()

    def setUp(self) -> None:
        self.project = self.template.project()
        self.addCleanup(self.project.close)
        self.run_git = self.project.runner()

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
        clean = git.tree_status(project.code, runner=self.run_git)
        self.assertEqual(clean.entries, [])
        after = index.stat()
        self.assertEqual(
            (after.st_size, after.st_mtime_ns), (before.st_size, before.st_mtime_ns)
        )
        project.git(project.code, "status", "--porcelain")
        self.assertNotEqual(index.stat().st_mtime_ns, before.st_mtime_ns)

        readme.write_text("cambiado\n", encoding="utf-8")
        (project.code / "tools" / "nuevo").mkdir()
        (project.code / "tools" / "nuevo" / "a.py").write_text("x\n", encoding="utf-8")
        status = git.tree_status(project.code, runner=self.run_git)
        self.assertEqual(status.entries, [" M README.md", "?? tools/nuevo/a.py"])
        self.assertEqual((status.branch, status.commit), ("main", clean.commit))
        project.git(project.code, "commit", "-q", "-a", "-m", "cambio")
        self.assertEqual(git.ahead_of_remote(project.code, "main", runner=self.run_git), 1)

    def test_gitlink_in_docs(self) -> None:
        """RF-007-15: si la documentación versiona la carpeta del código (``git add -f``
        de un repositorio anidado: un *gitlink*), ``tracked_under`` lo nombra."""
        project = self.project
        project.git(project.docs, "add", "-f", CODE_DIR_IN_DOCS)
        found = git.tracked_under(project.docs, CODE_DIR_IN_DOCS, runner=self.run_git)
        self.assertEqual(found, [f"{CODE_DIR_IN_DOCS} (gitlink)"])


if __name__ == "__main__":
    unittest.main()

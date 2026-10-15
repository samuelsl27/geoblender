# SPDX-License-Identifier: GPL-3.0-or-later
"""Ayudas de las pruebas de ``jobs`` y ``workers`` (spec 004, T01; plan 004 §7 y §7.1).

La tarea no cubre ningún RF: prepara lo que usan las pruebas de los RF-004-01 a
RF-004-28. Comprueba que las ayudas se importan con el Python de Blender, que
``pid_alive`` distingue un proceso vivo de uno terminado (sin terminarlo al preguntar), que
el proyecto falso, la rueda sintética ``gbtestpkg`` y el intérprete falso hacen lo que
dicen, y que el texto de las ayudas no lleva rutas absolutas ni datos de clientes
(constitución, principio 7: ``tests/`` solo usa datos sintéticos).
"""

import base64
import csv
import hashlib
import inspect
import io
import os
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from tests.support import jobs_fixtures
from tests.support.jobs_fixtures import (
    PROJECT_FILES,
    WHEEL_PACKAGE,
    FakeProject,
    jobs_tmp,
    make_fake_interpreter,
    make_fake_project,
    make_wheel,
    pid_alive,
    sha256_file,
    temp_jobs_root,
    wait_until_dead,
)

# Lo que no puede aparecer en las ayudas: una unidad con barra, una UNC, carpetas
# absolutas de Linux o macOS, y datos de un expediente real (el origen de Silvestre).
_ABSOLUTE = re.compile(r"[A-Za-z]:[\\/]|\\\\|(?<![\w.])/(?:mnt|home|Users|tmp|var)/")
_CLIENT_DATA = ("silvestre", "736200", "736 200", "4435300", "4 435 300")
_REPO = Path(__file__).resolve().parents[3]
_SLEEPER = [sys.executable, "-B", "-I", "-c", "import time; time.sleep(60)"]


class ImportTest(unittest.TestCase):
    def test_imports(self) -> None:
        """Spec 004, T01: las ayudas se importan con el Python de Blender y ofrecen raíz
        de trabajos temporal, proyecto falso, ``pid_alive``, ruedas sintéticas e
        intérpretes falsos."""
        names = (
            "jobs_tmp",
            "temp_jobs_root",
            "make_fake_project",
            "sha256_file",
            "pid_alive",
            "wait_until_dead",
            "make_wheel",
            "make_fake_interpreter",
        )
        for name in names:
            with self.subTest(name=name):
                self.assertTrue(callable(getattr(jobs_fixtures, name)))
        self.assertEqual(WHEEL_PACKAGE, "gbtestpkg")
        self.assertEqual(PROJECT_FILES, ("project.gpkg", "blocks.duckdb"))

    def test_no_absolute_paths_or_client_data(self) -> None:
        """Spec 004, T01: el texto de las ayudas no contiene rutas absolutas ni datos de
        clientes."""
        text = inspect.getsource(jobs_fixtures)
        self.assertIsNone(_ABSOLUTE.search(text))
        lowered = text.lower()
        for needle in _CLIENT_DATA:
            self.assertNotIn(needle, lowered)


class TempFoldersTest(unittest.TestCase):
    def test_jobs_tmp(self) -> None:
        """Spec 004, T01: la carpeta temporal es nueva, está en ``%TEMP%`` y no en el
        repositorio, tiene una ruta corta (las de ``pip --target`` y los trabajos se
        alargan: Blender no admite más de 259 caracteres) y desaparece al salir."""
        with jobs_tmp() as base:
            self.assertTrue(base.is_dir())
            self.assertEqual(list(base.iterdir()), [])
            temp = Path(tempfile.gettempdir()).resolve()
            self.assertTrue(base.resolve().is_relative_to(temp))
            self.assertFalse(base.resolve().is_relative_to(_REPO))
            self.assertLessEqual(len(base.name), 16)
            (base / "x.txt").write_text("x", encoding="utf-8")
        self.assertFalse(base.exists())

    def test_temp_jobs_root(self) -> None:
        """Spec 004, T01 (instrumento de RF-004-18): la raíz de trabajos temporal es
        ``<temporal>/jobs``, existe y está vacía; su madre admite el proyecto falso y los
        datos de usuario, y todo se borra al salir."""
        with temp_jobs_root() as root:
            self.assertEqual(root.name, "jobs")
            self.assertTrue(root.is_dir())
            self.assertEqual(list(root.iterdir()), [])
            self.assertFalse(root.resolve().is_relative_to(_REPO))
            (root / "20261007_101500_abcdef").mkdir()
        self.assertFalse(root.parent.exists())


class FakeProjectTest(unittest.TestCase):
    def test_fake_project(self) -> None:
        """Spec 004, T01 (instrumento de RF-004-14): el proyecto falso tiene
        ``project.gpkg`` y ``blocks.duckdb`` de bytes aleatorios del tamaño pedido; sus
        huellas sha256 se repiten mientras no cambian y cambian con un byte."""
        with jobs_tmp() as base:
            project = make_fake_project(base, size=4096)
            self.assertIsInstance(project, FakeProject)
            self.assertEqual(project.root, base / "proyecto")
            self.assertEqual(project.gpkg, project.root / "project.gpkg")
            self.assertEqual(project.duckdb, project.root / "blocks.duckdb")
            for path in project.files():
                with self.subTest(path=path.name):
                    self.assertEqual(path.stat().st_size, 4096)
            first = project.fingerprints()
            self.assertEqual(sorted(first), sorted(PROJECT_FILES))
            self.assertEqual(first["project.gpkg"], sha256_file(project.gpkg))
            self.assertNotEqual(first["project.gpkg"], first["blocks.duckdb"])
            self.assertEqual(project.fingerprints(), first)
            other = make_fake_project(base, name="otro", size=4096)
            self.assertNotEqual(other.fingerprints(), first)
            data = bytearray(project.duckdb.read_bytes())
            data[0] ^= 0xFF
            project.duckdb.write_bytes(bytes(data))
            changed = project.fingerprints()
            self.assertEqual(changed["project.gpkg"], first["project.gpkg"])
            self.assertNotEqual(changed["blocks.duckdb"], first["blocks.duckdb"])
            with self.assertRaises(FileExistsError):
                make_fake_project(base)


class PidAliveTest(unittest.TestCase):
    def test_running_child_is_alive_and_survives(self) -> None:
        """Spec 004, T01 (instrumento de RF-004-13): un proceso en marcha está vivo y
        preguntarlo no lo termina (``os.kill(pid, 0)`` en Windows lo mataría); muerto, deja
        de estarlo, y ``wait_until_dead`` lo ve enseguida."""
        child = subprocess.Popen(_SLEEPER, stdin=subprocess.DEVNULL)
        try:
            self.assertTrue(pid_alive(child.pid))
            self.assertTrue(pid_alive(child.pid))
            self.assertIsNone(child.poll())
            self.assertFalse(wait_until_dead(child.pid, timeout_s=0.2))
            self.assertIsNone(child.poll())
        finally:
            child.kill()
            child.wait(timeout=60)
        self.assertFalse(pid_alive(child.pid))
        self.assertTrue(wait_until_dead(child.pid, timeout_s=5.0))

    def test_finished_and_impossible_pids(self) -> None:
        """Spec 004, T01 (instrumento de RF-004-13): un proceso que ya terminó por sí solo
        no está vivo, ni uno que no puede existir; el propio, sí."""
        finished = subprocess.Popen(
            [sys.executable, "-B", "-I", "-c", "pass"], stdin=subprocess.DEVNULL
        )
        finished.wait(timeout=60)
        self.assertFalse(pid_alive(finished.pid))
        for pid in (0, -1, 2**31 - 1):
            with self.subTest(pid=pid):
                self.assertFalse(pid_alive(pid))
        self.assertTrue(pid_alive(os.getpid()))


class ProcessesTest(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "CreateToolhelp32Snapshot es de Windows")
    def test_processes_include_this_one_with_its_parent(self) -> None:
        """Spec 004, T01; spec 005, T33 (instrumento de RNF-004-07 y RNF-005-05): la foto de
        los procesos del equipo tiene este, con su padre y el nombre de su ejecutable."""
        parent, exe = jobs_fixtures.processes()[os.getpid()]
        self.assertEqual(parent, os.getppid())
        self.assertEqual(exe.casefold(), Path(sys.executable).name.casefold())

    def test_descendants_are_the_new_processes_under_the_roots(self) -> None:
        """Spec 004, T01; spec 005, T33 (instrumento de RNF-004-07 y RNF-005-05): los
        descendientes de unas raíces son los procesos nuevos que cuelgan de ellas, también los
        nietos y el huérfano de una raíz que ya terminó; no los que ya estaban ni los de otro
        padre, y un pid que se reutiliza con otro padre es nuevo."""
        before = {10: (1, "lanzador.exe"), 11: (10, "viejo.exe"), 30: (1, "otro.exe")}
        after = {10: (1, "lanzador.exe"), 11: (10, "viejo.exe"), 12: (10, "hijo.exe"),
                 13: (12, "nieto.exe"), 21: (20, "huérfano.exe"), 31: (30, "ajeno.exe")}
        self.assertEqual(jobs_fixtures.descendants(before, after, [10, 20]),
                         {12: "hijo.exe", 13: "nieto.exe", 21: "huérfano.exe"})
        self.assertEqual(jobs_fixtures.descendants({12: (5, "a.exe")}, {12: (10, "b.exe")},
                                                   [10]), {12: "b.exe"})


def _record_hash(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    return "sha256=" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class SyntheticWheelTest(unittest.TestCase):
    def test_wheel_layout_and_record(self) -> None:
        """Spec 004, T01 (instrumento de RF-004-21): la rueda ``gbtestpkg`` es
        ``py3-none-any``, lleva el paquete y su ``dist-info`` (``METADATA``, ``WHEEL`` y un
        ``RECORD`` cuyas huellas casan), y su sha256 y su tamaño son los del fichero."""
        with jobs_tmp() as base:
            wheel = make_wheel(base / "almacen", version="1.2.3")
            self.assertEqual(wheel.path.name, "gbtestpkg-1.2.3-py3-none-any.whl")
            self.assertEqual(wheel.filename, wheel.path.name)
            self.assertEqual((wheel.name, wheel.version), ("gbtestpkg", "1.2.3"))
            self.assertEqual(wheel.sha256, sha256_file(wheel.path))
            self.assertEqual(wheel.size, wheel.path.stat().st_size)
            info = "gbtestpkg-1.2.3.dist-info"
            with zipfile.ZipFile(wheel.path) as archive:
                names = set(archive.namelist())
                self.assertEqual(
                    names,
                    {
                        "gbtestpkg/__init__.py",
                        f"{info}/METADATA",
                        f"{info}/WHEEL",
                        f"{info}/RECORD",
                    },
                )
                metadata = archive.read(f"{info}/METADATA").decode("utf-8")
                self.assertIn("Name: gbtestpkg\n", metadata)
                self.assertIn("Version: 1.2.3\n", metadata)
                self.assertIn("Tag: py3-none-any\n", archive.read(f"{info}/WHEEL").decode())
                record_text = archive.read(f"{info}/RECORD").decode("utf-8")
                record = list(csv.reader(io.StringIO(record_text)))
                self.assertEqual({row[0] for row in record}, names)
                for path, digest, size in record:
                    with self.subTest(path=path):
                        if path == f"{info}/RECORD":
                            self.assertEqual((digest, size), ("", ""))
                            continue
                        data = archive.read(path)
                        self.assertEqual(digest, _record_hash(data))
                        self.assertEqual(int(size), len(data))

    def test_wheel_is_reproducible(self) -> None:
        """Spec 004, T01 (instrumento de RF-004-21): la misma rueda da la misma huella (el
        lock de pruebas puede fijarla) y otra versión u otro contenido, otra."""
        with jobs_tmp() as base:
            first = make_wheel(base / "a")
            again = make_wheel(base / "b")
            other = make_wheel(base / "c", version="2.0.0")
            altered = make_wheel(base / "d", extra_files={"gbtestpkg/data.txt": "ñ\n"})
            self.assertEqual(first.sha256, again.sha256)
            self.assertNotEqual(first.sha256, other.sha256)
            self.assertNotEqual(first.sha256, altered.sha256)
            with self.assertRaises(ValueError):
                make_wheel(base / "e", name="no-valido")

    def test_wheel_imports(self) -> None:
        """Spec 004, T01 (instrumento de RF-004-21): el paquete de la rueda se importa (con
        el Python de Blender, aislado) y dice su versión."""
        with jobs_tmp() as base:
            wheel = make_wheel(base, version="1.0.7")
            code = (
                "import sys; sys.path.insert(0, sys.argv[1]); import gbtestpkg; "
                "print(gbtestpkg.__version__)"
            )
            done = subprocess.run(
                [sys.executable, "-B", "-I", "-c", code, str(wheel.path)],
                capture_output=True,
                text=True,
                timeout=60,
                stdin=subprocess.DEVNULL,
            )
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(done.stdout.strip(), "1.0.7")


class FakeInterpreterTest(unittest.TestCase):
    def test_prints_and_exits_as_told(self) -> None:
        """Spec 004, T01 (instrumento de RF-004-26): el intérprete falso es un ``.cmd`` que
        no ejecuta Python: ignora los argumentos, escribe en la salida tal cual lo que se
        le dio (también «ñ» y los caracteres especiales de cmd) y termina con el código
        pedido."""
        text = '{"python": "3.12.9", "numpy": null, "nota": "ñ <&|>^% !x!"}\n'
        with jobs_tmp() as base:
            exe = make_fake_interpreter(base, stdout=text, exit_code=3)
            self.assertEqual(exe.suffix, ".cmd")
            self.assertEqual(exe.parent, base)
            done = subprocess.run(
                [str(exe), "-I", "-B", "-c", "print('no se ejecuta')"],
                capture_output=True,
                timeout=60,
                stdin=subprocess.DEVNULL,
            )
            self.assertEqual(done.returncode, 3)
            self.assertEqual(done.stdout.replace(b"\r\n", b"\n"), text.encode("utf-8"))
            self.assertEqual(done.stderr, b"")

    def test_stderr_and_several_interpreters(self) -> None:
        """Spec 004, T01 (instrumento de RF-004-26): puede escribir también en la salida de
        errores, y dos intérpretes falsos de la misma carpeta no se pisan."""
        with jobs_tmp() as base:
            ok = make_fake_interpreter(base, stdout="3.13\n", name="py313")
            bad = make_fake_interpreter(
                base,
                stdout="",
                stderr="No module named 'numpy'\n",
                exit_code=1,
                name="sin_numpy",
            )
            first = subprocess.run(
                [str(ok)], capture_output=True, timeout=60, stdin=subprocess.DEVNULL
            )
            second = subprocess.run(
                [str(bad)], capture_output=True, timeout=60, stdin=subprocess.DEVNULL
            )
            self.assertEqual((first.returncode, first.stdout.strip()), (0, b"3.13"))
            self.assertEqual((second.returncode, second.stdout), (1, b""))
            self.assertEqual(second.stderr.strip(), b"No module named 'numpy'")
            with self.assertRaises(FileExistsError):
                make_fake_interpreter(base, stdout="otra", name="py313")


if __name__ == "__main__":
    unittest.main()

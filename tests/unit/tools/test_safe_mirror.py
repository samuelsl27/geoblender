# SPDX-License-Identifier: GPL-3.0-or-later
"""El espejo seguro del NAS, ``gbtools.safe_mirror`` (spec 007, HU-007-7; plan 007 §5.2 y
§5.4.6 a §5.4.8).

Todas las pruebas trabajan en carpetas temporales locales: la carpeta del proyecto, el
destino y el perfil local (que hace de ``LOCALAPPDATA``, con los estados y las fotos).
Ninguna lee el perfil real del puesto ni toca el NAS.
"""

import json
import os
import shutil
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

from tests.support import mirror
from tests.support.repo import tools_on_path
from tests.support.resources import WINDOWS, WINDOWS_HINT, skip_reason

tools_on_path()

from gbtools import layout, safe_mirror  # noqa: E402

SHA = "a" * 64


@contextmanager
def places() -> Iterator[tuple[Path, Path, dict[str, str]]]:
    """Un destino y un perfil local temporales: ``(destino, perfil, entorno)``."""
    with tempfile.TemporaryDirectory(prefix="geoblender-espejo-") as tmp:
        base = Path(tmp).resolve()
        dest, profile = base / "destino", base / "perfil"
        dest.mkdir()
        profile.mkdir()
        yield dest, profile, {"LOCALAPPDATA": str(profile)}


class StateTest(unittest.TestCase):
    """RF-007-30, RF-007-31: dónde está el estado de cada destino y cuál es la base de la
    comparación (el estado, o la foto en el primer espejo)."""

    def test_state_dir(self) -> None:
        """RF-007-30: el estado vive en ``%LOCALAPPDATA%\\Geoblender\\espejo`` (fuera de
        los repositorios y del destino); sin ``LOCALAPPDATA``, un error claro."""
        with places() as (_dest, profile, environ):
            self.assertEqual(
                safe_mirror.state_dir(environ), profile.joinpath(*layout.MIRROR_STATE_PARTS)
            )
        with self.assertRaises(safe_mirror.MirrorError) as ctx:
            safe_mirror.state_dir({})
        self.assertIn("LOCALAPPDATA", str(ctx.exception))

    def test_state_per_destination(self) -> None:
        """RF-007-30: un estado por destino, en un fichero cuyo nombre sale de su ruta
        real; cada destino lee el suyo."""
        with places() as (dest, profile, environ):
            other = dest.parent / "otro"
            other.mkdir()
            files = {"a.txt": {"size": 1, "mtime_ns": 5, "sha256": SHA}}
            mirror.write_state(profile, dest, files=files, folders=["docs"])
            mirror.write_state(profile, other, files={}, folders=[])
            first = safe_mirror.state_file(dest, environ)
            self.assertNotEqual(first, safe_mirror.state_file(other, environ))
            self.assertRegex(first.name, r"^estado-[0-9a-f]{16}\.json$")
            base = safe_mirror.load_base(dest, environ)
            assert base is not None
            self.assertFalse(base.photo)
            self.assertEqual(base.files, {"a.txt": safe_mirror.FileState(1, 5, SHA)})
            self.assertEqual(base.folders, {"docs"})
            base_other = safe_mirror.load_base(other, environ)
            assert base_other is not None
            self.assertEqual(base_other.files, {})
            same = safe_mirror.state_file(Path(str(dest).upper() + "\\"), environ)
            self.assertEqual(same, first)

    def test_state_same_for_unc_and_drive(self) -> None:
        """RF-007-30: una unidad de red y su ruta UNC son el mismo destino: la clave sale
        de la ruta real (``os.path.realpath``, que da la UNC de una unidad de red)."""
        drive = "Y" + ":\\espejo\\proyecto"
        unc = "\\\\servidor.invalid\\recurso\\espejo\\proyecto"

        def realpath(path: object, *_args: object, **_kwargs: object) -> str:
            text = os.fspath(path)
            return unc + text[len(drive):] if text.upper().startswith(drive.upper()) else text

        with mock.patch("os.path.realpath", side_effect=realpath):
            environ = {"LOCALAPPDATA": "C:\\perfil-de-prueba"}
            self.assertEqual(
                safe_mirror.state_file(Path(drive), environ),
                safe_mirror.state_file(Path(unc), environ),
            )
            self.assertEqual(safe_mirror.destination_key(drive), safe_mirror.destination_key(unc))

    def test_first_mirror_uses_photo(self) -> None:
        """RF-007-31: sin estado, la foto cuyo ``destino`` tiene la misma ruta real
        (escrita de otra forma) es la base: sus ficheros y, como carpetas, las madres de
        sus ficheros."""
        with places() as (dest, profile, environ):
            files = {
                "docs/adr/0001.md": {"size": 3, "mtime_ns": 7, "sha256": SHA},
                "README.md": {"size": 2, "mtime_ns": 8, "sha256": SHA},
            }
            written = str(dest).upper() + "\\"
            mirror.write_photo(profile, written, files=files)
            base = safe_mirror.load_base(dest, environ)
        assert base is not None
        self.assertTrue(base.photo)
        self.assertEqual(base.taken, mirror.TAKEN)
        self.assertEqual(base.files["README.md"], safe_mirror.FileState(2, 8, SHA))
        self.assertEqual(base.folders, {"docs", "docs/adr"})

    def test_photo_of_other_destination_ignored(self) -> None:
        """RF-007-31: la foto de otro destino no vale, y sin estado ni foto no hay base;
        una foto ilegible se salta."""
        with places() as (dest, profile, environ):
            mirror.write_photo(profile, dest.parent / "otro", files={})
            folder = mirror.state_folder(profile)
            (folder / "foto-rota.json").write_bytes(b"{no es json")
            self.assertIsNone(safe_mirror.load_base(dest, environ))
        with places() as (dest, _profile, environ):
            self.assertIsNone(safe_mirror.load_base(dest, environ))

    def test_unreadable_state_not_replaced_by_photo(self) -> None:
        """RF-007-31: un estado que existe y no se puede leer es ``StateUnreadable``,
        aunque haya foto: nunca se vuelve a la foto."""
        with places() as (dest, profile, environ):
            mirror.write_photo(profile, dest, files={})
            state = safe_mirror.state_file(dest, environ)
            for content in (b"{no es json", b"[]", json.dumps({"formato": 2}).encode()):
                with self.subTest(contenido=content):
                    state.write_bytes(content)
                    with self.assertRaises(safe_mirror.StateUnreadable) as ctx:
                        safe_mirror.load_base(dest, environ)
                    self.assertIn(state.name, str(ctx.exception))

    def test_state_paths_validated(self) -> None:
        """RF-007-30: un estado con una ruta que sale del destino («..», absoluta o con
        «\\»), un sha256 o un tamaño que no lo son, no se lee (``StateUnreadable``): el
        espejo nunca usa una ruta del estado fuera del destino."""
        bad_files = (
            {"../fuera.txt": {"size": 1, "mtime_ns": 1, "sha256": SHA}},
            {"C:/x.txt": {"size": 1, "mtime_ns": 1, "sha256": SHA}},
            {"docs\\x.txt": {"size": 1, "mtime_ns": 1, "sha256": SHA}},
            {"x.txt": {"size": 1, "mtime_ns": 1, "sha256": "corto"}},
            {"x.txt": {"size": True, "mtime_ns": 1, "sha256": SHA}},
        )
        with places() as (dest, profile, environ):
            for files in bad_files:
                with self.subTest(ficheros=files):
                    mirror.write_state(profile, dest, files=files, folders=[])
                    with self.assertRaises(safe_mirror.StateUnreadable):
                        safe_mirror.load_base(dest, environ)
            mirror.write_state(profile, dest, files={}, folders=["../fuera"])
            with self.assertRaises(safe_mirror.StateUnreadable):
                safe_mirror.load_base(dest, environ)


CODE = layout.CODE_DIR_IN_DOCS
# Una carpeta del proyecto pequeña: la documentación y el código, cada uno con su .git.
PROJECT: dict[str, str] = {
    layout.DOCS_MARKER: "# Constitución\n",
    "README.md": "# Documentación\n",
    ".git/HEAD": "ref: refs/heads/main\n",
    ".git/objects/ab/cdef0123": "objeto\n",
    f"{CODE}/README.md": "# Código\n",
    f"{CODE}/.git/HEAD": "ref: refs/heads/main\n",
    f"{CODE}/.git/index": "índice\n",
    f"{CODE}/{layout.EXTENSION_DIR}/__init__.py": "x = 1\n",
}


@dataclass
class Mirrored:
    """Una carpeta del proyecto (``project``), su espejo idéntico (``dest``) y el estado
    del último espejo de ese destino en el perfil local (``environ``)."""

    project: Path
    dest: Path
    profile: Path
    environ: dict[str, str]

    def write(self, root: Path, rel: str, text: str, shift_s: int = 0) -> Path:
        """Escribe ``text`` en ``root/rel`` y, con ``shift_s``, mueve su fecha."""
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        before = path.stat().st_mtime_ns if path.exists() else None
        path.write_bytes(text.encode("utf-8"))
        if shift_s and before is not None:
            stamp = before + shift_s * 10**9
            os.utime(path, ns=(stamp, stamp))
        return path

    def compare(self) -> tuple[list[safe_mirror.DestChange], dict[str, safe_mirror.FileState]]:
        base = safe_mirror.load_base(self.dest, self.environ)
        assert base is not None
        source = safe_mirror.scan_source(self.project)
        listing = safe_mirror.scan_destination(self.dest)
        pending = safe_mirror.load_pending(self.dest, self.environ)
        return safe_mirror.destination_changes(self.dest, base, source, listing, pending)

    def kinds(self) -> list[tuple[str, str]]:
        return [(change.kind, change.path) for change in self.compare()[0]]


@contextmanager
def mirrored(files: dict[str, str] | None = None) -> Iterator[Mirrored]:
    """La carpeta del proyecto ``files`` (por defecto, ``PROJECT``), su copia exacta
    (tamaños y fechas incluidos) como destino y su estado."""
    with places() as (dest, profile, environ):
        project = dest.parent / "proyecto"
        for rel, text in (files or PROJECT).items():
            path = project / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
        shutil.copytree(project, dest, dirs_exist_ok=True)
        mirror.write_state(profile, dest)
        yield Mirrored(project, dest, profile, environ)


class CompareTest(unittest.TestCase):
    """RF-007-29: el destino frente al estado del último espejo (plan 007 §5.4.7):
    nuevo, cambiado, borrado y carpeta nueva; sin distinguir mayúsculas; lo ya traído al
    PC, lo borrado en los dos, el cambio de solo la fecha y lo que dejó un espejo en curso
    no son cambios del NAS."""

    def test_unchanged(self) -> None:
        """RF-007-29: sin cambios, ninguno; lo observado de cada fichero es lo del
        estado (no se lee su contenido)."""
        with mirrored() as m:
            with mock.patch.object(safe_mirror, "observe", side_effect=AssertionError):
                changes, observed = m.compare()
            base = safe_mirror.load_base(m.dest, m.environ)
        assert base is not None
        self.assertEqual(changes, [])
        self.assertEqual(observed, base.files)

    def test_new_in_dest_stops(self) -> None:
        """RF-007-29: un fichero nuevo en el destino, de la documentación."""
        with mirrored() as m:
            m.write(m.dest, "docs/nota.docx", "nota")
            changes, _observed = m.compare()
        self.assertEqual(
            changes, [safe_mirror.DestChange("docs/nota.docx", safe_mirror.NEW, False)]
        )
        self.assertEqual(changes[0].repo, safe_mirror.REPO_DOCS)

    def test_changed_in_dest_stops(self) -> None:
        """RF-007-29: un fichero cambiado (otro tamaño) en el código."""
        with mirrored() as m:
            m.write(m.dest, f"{CODE}/README.md", "# Código cambiado en el NAS\n", shift_s=5)
            self.assertEqual(m.kinds(), [(safe_mirror.CHANGED, f"{CODE}/README.md")])
            self.assertEqual(m.compare()[0][0].repo, safe_mirror.REPO_CODE)

    def test_changed_same_size_stops(self) -> None:
        """RF-007-29: un fichero con el mismo tamaño y otra fecha: se lee su sha256, y
        si es otro, «cambiado»."""
        with mirrored() as m:
            m.write(m.dest, "README.md", "# DOCUMENTACIÓN\n", shift_s=3)
            self.assertEqual(
                (m.dest / "README.md").stat().st_size, (m.project / "README.md").stat().st_size
            )
            self.assertEqual(m.kinds(), [(safe_mirror.CHANGED, "README.md")])

    def test_deleted_in_dest_stops(self) -> None:
        """RF-007-29: un fichero que el estado tiene, el PC también y el destino no."""
        with mirrored() as m:
            (m.dest / "README.md").unlink()
            self.assertEqual(m.kinds(), [(safe_mirror.DELETED, "README.md")])

    def test_new_folder_in_dest_stops(self) -> None:
        """RF-007-29: una carpeta nueva y vacía en el destino (de una anidada, la de
        fuera)."""
        with mirrored() as m:
            (m.dest / "Documentacion" / "vacia" / "dentro").mkdir(parents=True)
            self.assertEqual(m.kinds(), [(safe_mirror.NEW_FOLDER, "Documentacion")])

    def test_new_folder_with_only_excluded_stops(self) -> None:
        """RF-007-29: una carpeta nueva con solo excluidos (``Thumbs.db``): «carpeta
        nueva», y el excluido no se compara."""
        with mirrored() as m:
            m.write(m.dest, "fotos/Thumbs.db", "miniaturas")
            changes, _observed = m.compare()
            listing = safe_mirror.scan_destination(m.dest)
        self.assertEqual([(c.kind, c.path) for c in changes], [(safe_mirror.NEW_FOLDER, "fotos")])
        self.assertIn("fotos/Thumbs.db", listing.excluded)

    def test_case_insensitive_match(self) -> None:
        """RF-007-29: una ruta del destino que solo difiere en mayúsculas de la del
        estado y del PC (fichero o carpeta) es la misma: sin cambios."""
        with mirrored() as m:
            for old, new in (("README.md", "readme.md"), ("docs", "Docs")):
                (m.dest / old).rename(m.dest / f"{new}.renombrando")
                (m.dest / f"{new}.renombrando").rename(m.dest / new)
            self.assertIn("readme.md", os.listdir(m.dest))
            self.assertEqual(m.kinds(), [])

    def test_already_in_source_not_reported(self) -> None:
        """RF-007-29: el destino ya tiene lo del PC (alguien lo trajo y lo cambió en los
        dos): no es un cambio del NAS, y lo observado lleva su sha256."""
        text = "# Documentación nueva\n"
        with mirrored() as m:
            m.write(m.project, "README.md", text)
            info = m.write(m.dest, "README.md", text, shift_s=7).stat()
            changes, observed = m.compare()
        self.assertEqual(changes, [])
        self.assertEqual(
            observed["README.md"],
            safe_mirror.FileState(info.st_size, info.st_mtime_ns, mirror.sha256_of_text(text)),
        )

    def test_both_deleted_not_reported(self) -> None:
        """RF-007-29: borrado en el PC y en el destino: no es un cambio."""
        with mirrored() as m:
            (m.dest / "README.md").unlink()
            (m.project / "README.md").unlink()
            self.assertEqual(m.kinds(), [])

    def test_date_only_change_not_reported(self) -> None:
        """RF-007-29, RF-007-30: solo cambió la fecha (mismo sha256): no es un cambio, y
        lo observado lleva la fecha nueva (la que guardará el estado)."""
        with mirrored() as m:
            path = m.dest / "README.md"
            stamp = path.stat().st_mtime_ns + 9 * 10**9
            os.utime(path, ns=(stamp, stamp))
            changes, observed = m.compare()
        self.assertEqual(changes, [])
        self.assertEqual(observed["README.md"].mtime_ns, stamp)

    def test_git_change_marked(self) -> None:
        """RF-007-29: un cambio dentro de un ``.git`` (un ``git status`` en el NAS
        reescribe el índice) va marcado como tal, con su repositorio."""
        with mirrored() as m:
            m.write(m.dest, f"{CODE}/.git/index", "índice reescrito en el NAS\n", shift_s=1)
            changes, _observed = m.compare()
        self.assertEqual(len(changes), 1)
        self.assertTrue(changes[0].in_git)
        self.assertEqual(changes[0].repo, safe_mirror.REPO_CODE)

    def test_interrupted_mirror_resumes(self) -> None:
        """RF-007-29, RF-007-34: lo que dejó un espejo en curso de este PC (el sha256 que
        iba a dejar, un borrado que iba a hacer, un temporal suyo, una carpeta que creó)
        no es un cambio del NAS; lo demás, sí."""
        with mirrored() as m:
            m.write(m.dest, "README.md", "# Escrito por el espejo cortado\n", shift_s=2)
            m.write(m.project, "README.md", "# Cambiado después en el PC\n")
            (m.project / f"{CODE}/README.md").unlink()
            (m.dest / f"{CODE}/README.md").unlink()
            m.write(m.project, f"{CODE}/README.md", "# Vuelve\n")
            temp = f"docs/constitution.md{layout.MIRROR_TEMP_SUFFIX}"
            m.write(m.dest, temp, "a medias")
            (m.dest / "nueva").mkdir()
            pending = {
                "formato": 1,
                "tipo": "en-curso",
                "destino": str(m.dest),
                "ficheros": {"README.md": mirror.sha256_of_text("# Escrito por el espejo cortado\n")},
                "borrados": [f"{CODE}/README.md"],
                "temporales": [temp],
                "carpetas": ["nueva"],
            }
            safe_mirror.pending_file(m.dest, m.environ).write_bytes(json.dumps(pending).encode())
            self.assertEqual(m.kinds(), [])
            m.write(m.dest, "otro.txt", "esto sí es del NAS")
            self.assertEqual(m.kinds(), [(safe_mirror.NEW, "otro.txt")])

    def test_excluded_never_compared(self) -> None:
        """RF-007-22, D-17: ``dist/`` y ``.deps/`` de la raíz de cada repositorio y, a
        cualquier nivel, ``__pycache__/``, ``*.pyc``, ``*.blend1``, bloqueos de Office,
        ``Thumbs.db`` y ``desktop.ini``: ni se comparan ni cuentan como carpeta nueva, y
        se informa de ellos; un ``dist/`` dentro de otra carpeta, sí se compara."""
        cache = f"{CODE}/{layout.EXTENSION_DIR}/__pycache__/"
        with mirrored() as m:
            for rel in (
                "dist/geoblender-0.1.0.zip", f"{CODE}/.deps/site/x.txt", f"{cache}a.pyc",
                "docs/b.pyc", "docs/plano.blend1", "docs/~$informe.docx",
                "docs/.~lock.hoja.ods#", "docs/desktop.ini", "docs/THUMBS.DB",
            ):
                m.write(m.dest, rel, "x")
            listing = safe_mirror.scan_destination(m.dest)
            self.assertEqual(m.kinds(), [])
            m.write(m.dest, "Documentacion/dist/x.txt", "x")
            self.assertEqual(
                m.kinds(),
                [
                    (safe_mirror.NEW_FOLDER, "Documentacion"),
                    (safe_mirror.NEW, "Documentacion/dist/x.txt"),
                ],
            )
        for excluded in ("dist/", f"{CODE}/.deps/", cache, "docs/b.pyc", "docs/THUMBS.DB"):
            self.assertIn(excluded, listing.excluded)
        self.assertNotIn("docs/plano.blend1", listing.files)


class SourceTest(unittest.TestCase):
    """RF-007-22: lo que se refleja de la carpeta del proyecto (``scan_source``)."""

    def test_source_files_and_folders(self) -> None:
        """RF-007-22: cada fichero con su sha256, los dos ``.git`` incluidos, y cada
        carpeta (también una vacía); sin lo excluido."""
        with mirrored() as m:
            (m.project / ".git" / "refs" / "tags").mkdir(parents=True)
            m.write(m.project, f"{CODE}/dist/geoblender-0.1.0.zip", "zip")
            source = safe_mirror.scan_source(m.project)
        self.assertEqual(set(source.files), set(PROJECT))
        self.assertEqual(source.files["README.md"], mirror.sha256_of_text(PROJECT["README.md"]))
        self.assertIn(".git/refs/tags", source.folders)
        self.assertIn(f"{CODE}/.git", source.folders)
        self.assertNotIn(f"{CODE}/dist", source.folders)

    def test_source_rescan_reuses_unchanged(self) -> None:
        """RF-007-22: el segundo recorrido de una misma publicación solo vuelve a leer
        el sha256 de los ficheros cuyo tamaño o fecha cambió."""
        with mirrored() as m:
            first = safe_mirror.scan_source(m.project)
            m.write(m.project, "README.md", "# Cambiado en el PC tras la subida\n")
            real = safe_mirror.sha256_of
            with mock.patch.object(safe_mirror, "sha256_of", side_effect=real) as spy:
                second = safe_mirror.scan_source(m.project, first)
        self.assertEqual([call.args[0].name for call in spy.call_args_list], ["README.md"])
        self.assertEqual(
            second.files["README.md"], mirror.sha256_of_text("# Cambiado en el PC tras la subida\n")
        )
        self.assertEqual(second.files[f"{CODE}/README.md"], first.files[f"{CODE}/README.md"])

    def test_source_case_clash_stops(self) -> None:
        """RF-007-22: dos rutas del origen que solo difieren en mayúsculas (en una
        carpeta que distingue mayúsculas) no se pueden reflejar en NTFS ni en SMB."""
        with self.assertRaises(safe_mirror.MirrorError) as ctx:
            safe_mirror.check_case_clashes(["docs/Nota.md", "docs/nota.md", "README.md"])
        self.assertIn("docs/Nota.md", str(ctx.exception))
        safe_mirror.check_case_clashes(["docs/Nota.md", "docs/otra.md"])

    @unittest.skipUnless(os.name == "nt", skip_reason(WINDOWS, WINDOWS_HINT))
    def test_symlink_in_source_stops(self) -> None:
        """RF-007-22: un enlace (aquí, una unión de Windows) en el origen: el espejo no
        lo copia y no sigue (``MirrorError``), sin entrar en él."""
        import _winapi

        with mirrored() as m:
            outside = m.dest.parent / "fuera"
            outside.mkdir()
            _winapi.CreateJunction(str(outside), str(m.project / "docs" / "union"))
            with self.assertRaises(safe_mirror.MirrorError) as ctx:
                safe_mirror.scan_source(m.project)
        self.assertIn("docs/union", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

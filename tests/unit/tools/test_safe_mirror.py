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
import stat
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
from gbtools import repo as gbrepo  # noqa: E402

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
    ".git/objects/ab/cdef0123": "objeto\n",
    f"{CODE}/README.md": "# Código\n",
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
        if not path.parent.is_dir():
            path.parent.mkdir(parents=True)
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

    def mirror(self, hook: object = None) -> safe_mirror.MirrorReport:
        """Compara (sin cambios del NAS) y hace el espejo, como la publicación."""
        base = safe_mirror.load_base(self.dest, self.environ)
        assert base is not None
        source = safe_mirror.scan_source(self.project)
        listing = safe_mirror.scan_destination(self.dest)
        pending = safe_mirror.load_pending(self.dest, self.environ)
        changes, observed = safe_mirror.destination_changes(
            self.dest, base, source, listing, pending
        )
        assert not changes, changes
        return safe_mirror.mirror(
            self.project, self.dest, source, listing, observed, base, self.environ,
            hook=hook,  # type: ignore[arg-type]
        )


@contextmanager
def mirrored(files: dict[str, str] | None = None, empty: bool = False) -> Iterator[Mirrored]:
    """La carpeta del proyecto ``files`` (por defecto, ``PROJECT``) y como destino su
    copia exacta (tamaños y fechas incluidos) con su estado o, con ``empty``, una
    carpeta vacía con su foto (el primer espejo)."""
    with places() as (dest, profile, environ):
        project = dest.parent / "proyecto"
        roots = (project,) if empty else (project, dest)
        state: dict[str, dict[str, object]] = {}
        for rel, text in (files or PROJECT).items():
            data = text.encode("utf-8")
            for root in roots:
                path = root / rel
                if not path.parent.is_dir():
                    path.parent.mkdir(parents=True)
                path.write_bytes(data)
            if not empty:
                # El estado sale del contenido escrito y de la fecha del destino: sin
                # volver a leer los ficheros (RNF-007-01). Las fechas de los dos lados
                # se igualan, como las deja una copia.
                info = (dest / rel).stat()
                os.utime(project / rel, ns=(info.st_mtime_ns, info.st_mtime_ns))
                state[rel] = {
                    "size": len(data),
                    "mtime_ns": info.st_mtime_ns,
                    "sha256": mirror.sha256_of_text(text),
                }
        if empty:
            mirror.write_photo(profile, dest, files={})
        else:
            mirror.write_state(profile, dest, files=state)
        yield Mirrored(project, dest, profile, environ)


def tree_of(root: Path) -> dict[str, bytes]:
    """Cada fichero bajo ``root`` con sus bytes (rutas con «/» y su mayúscula)."""
    return {
        (Path(current) / name).relative_to(root).as_posix(): (Path(current) / name).read_bytes()
        for current, _dirs, files in os.walk(root)
        for name in files
    }


class Interrupt(Exception):
    """Un corte simulado del espejo (el NAS cae, se cierra la consola)."""


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


PACKED = {
    **PROJECT,
    ".git/objects/pack/pack-1.pack": "paquete",
    ".git/objects/pack/pack-1.idx": "índice del paquete",
    ".git/objects/pack/pack-1.rev": "inverso",
    ".git/refs/heads/main": "a" * 40 + "\n",
    ".git/logs/HEAD": "registro\n",
    f"{CODE}/.git/packed-refs": "# pack-refs\n",
}


class MirrorTest(unittest.TestCase):
    """RF-007-22, RF-007-34: el espejo (plan 007 §5.4.8): solo lo que cambió, en un
    orden que nunca deja un ``.git`` del destino incoherente, cada fichero a un temporal
    comprobado y solo si el del destino sigue como se comparó; sin tocar lo excluido ni
    borrar una carpeta con contenido."""

    def test_mirror_whole_folder(self) -> None:
        """RF-007-22: el primer espejo a un destino vacío deja exactamente los ficheros
        y las carpetas de la carpeta del proyecto (también una vacía), con sus bytes y
        sus fechas; el registro en curso dice lo que iba a dejar."""
        with mirrored(empty=True) as m:
            (m.project / ".git" / "refs" / "tags").mkdir(parents=True)
            report = m.mirror()
            self.assertEqual(tree_of(m.dest), tree_of(m.project))
            self.assertTrue((m.dest / ".git" / "refs" / "tags").is_dir())
            info, copy = (m.project / "README.md").stat(), (m.dest / "README.md").stat()
            self.assertEqual(info.st_mtime_ns, copy.st_mtime_ns)
            pending = safe_mirror.load_pending(m.dest, m.environ)
            self.assertEqual(list(m.dest.rglob(f"*{layout.MIRROR_TEMP_SUFFIX}")), [])
        self.assertEqual(sorted(report.copied), sorted(PROJECT))
        assert pending is not None
        self.assertEqual(set(pending.files), {rel.casefold() for rel in PROJECT})
        self.assertEqual(report.verified["README.md"].mtime_ns, copy.st_mtime_ns)

    def test_only_changes_copied(self) -> None:
        """RF-007-22: con un fichero cambiado en el PC, solo ese se copia."""
        with mirrored() as m:
            m.write(m.project, "README.md", "# Documentación, 2\n")
            report = m.mirror()
            self.assertEqual(tree_of(m.dest), tree_of(m.project))
        self.assertEqual(report.copied, ["README.md"])
        self.assertEqual(report.unchanged, len(PROJECT) - 1)

    def test_exclusions_never_touched(self) -> None:
        """RF-007-22, D-17: lo excluido del destino sigue igual (bytes y fecha) y lo
        excluido del PC no se copia."""
        seeded = ("dist/geoblender-0.1.0.zip", "docs/Thumbs.db", f"{CODE}/.deps/site/x.txt")
        with mirrored() as m:
            for rel in seeded:
                m.write(m.dest, rel, "del destino")
            m.write(m.project, f"{CODE}/dist/geoblender-0.1.0.zip", "del PC")
            m.write(m.project, "docs/~$borrador.docx", "del PC")
            m.write(m.project, "README.md", "# Documentación, 2\n")
            before = {rel: (m.dest / rel).stat().st_mtime_ns for rel in seeded}
            m.mirror()
            for rel in seeded:
                self.assertEqual((m.dest / rel).read_bytes(), "del destino".encode())
                self.assertEqual((m.dest / rel).stat().st_mtime_ns, before[rel])
            self.assertFalse((m.dest / CODE / "dist").exists())
            self.assertFalse((m.dest / "docs" / "~$borrador.docx").exists())

    def test_exclusions_anchored_to_repo_roots(self) -> None:
        """RF-007-22, D-17: ``dist/`` y ``.deps/`` solo se excluyen en la raíz de cada
        repositorio; una carpeta de documentos que se llame así sí se refleja."""
        with mirrored() as m:
            m.write(m.project, "Documentacion/dist/informe.pdf", "informe")
            m.write(m.project, f"{CODE}/{layout.EXTENSION_DIR}/.deps/nota.txt", "nota")
            m.write(m.project, "dist/zip.zip", "zip")
            report = m.mirror()
            self.assertTrue((m.dest / "Documentacion" / "dist" / "informe.pdf").is_file())
            self.assertFalse((m.dest / "dist").exists())
        self.assertIn(f"{CODE}/{layout.EXTENSION_DIR}/.deps/nota.txt", report.copied)

    def test_client_data_never_mirrored(self) -> None:
        """RF-007-22, D-17, EXP-01 (DIFF-007a): ``Documentacion/datos_reales/`` (datos de
        clientes, ignorada por git) ni se lista, ni se copia, ni cuenta como sobrante del
        PC; una copia ya existente en el destino ni se toca ni es un cambio del NAS; una
        carpeta con ese nombre en otro sitio sí se refleja."""
        data = "Documentacion/datos_reales/cliente/sondeos.csv"
        with mirrored() as m:
            m.write(m.project, data, "dato de cliente")
            m.write(m.project, "docs/datos_reales/nota.txt", "nota")
            source = safe_mirror.scan_source(m.project)
            self.assertNotIn(data, source.files)
            self.assertNotIn("Documentacion/datos_reales", source.folders)
            self.assertIn("docs/datos_reales/nota.txt", source.files)
            self.assertTrue(safe_mirror.is_excluded("documentacion/DATOS_REALES", True))
            report = m.mirror()
            self.assertFalse((m.dest / "Documentacion" / "datos_reales").exists())
            self.assertTrue((m.dest / "docs" / "datos_reales" / "nota.txt").is_file())
            self.assertNotIn(data, report.copied)
            m.write(m.dest, "Documentacion/datos_reales/viejo.txt", "copia antigua")
            self.assertEqual(m.kinds(), [])
            self.assertIn(
                "Documentacion/datos_reales/", safe_mirror.scan_destination(m.dest).excluded
            )
            m.mirror()
            self.assertEqual(
                (m.dest / "Documentacion" / "datos_reales" / "viejo.txt").read_bytes(),
                "copia antigua".encode(),
            )

    def test_order_objects_files_refs_deletions(self) -> None:
        """RF-007-22: primero los objetos de git, después los ficheros de trabajo, el
        resto de cada ``.git``, sus referencias (``refs/``, ``packed-refs``, ``HEAD``,
        ``index``) y al final los borrados."""
        with mirrored(empty=True) as m:
            m.write(m.project, "viejo.txt", "x")
            first = m.mirror()
            (m.project / "viejo.txt").unlink()
            for rel, text in PACKED.items():
                m.write(m.project, rel, text + "2")
            mirror.write_state(m.profile, m.dest)
            report = m.mirror()
        self.assertIn(("copiar", "viejo.txt"), first.order)
        stages = [safe_mirror.copy_stage(rel) if action == "copiar" else 4 for action, rel in report.order]
        self.assertEqual(stages, sorted(stages), report.order)
        self.assertEqual(report.order[-1], ("borrar", "viejo.txt"))
        names = [rel for _action, rel in report.order]
        self.assertLess(names.index(".git/objects/ab/cdef0123"), names.index("README.md"))
        self.assertLess(names.index("README.md"), names.index(".git/logs/HEAD"))
        self.assertLess(names.index(".git/logs/HEAD"), names.index(".git/refs/heads/main"))
        self.assertLess(names.index(f"{CODE}/README.md"), names.index(f"{CODE}/.git/packed-refs"))

    def test_pack_before_idx(self) -> None:
        """RF-007-22: de cada paquete, el ``.pack`` antes que su ``.idx`` y su ``.rev``."""
        with mirrored(PACKED, empty=True) as m:
            names = [rel for _action, rel in m.mirror().order]
        pack = names.index(".git/objects/pack/pack-1.pack")
        self.assertLess(pack, names.index(".git/objects/pack/pack-1.idx"))
        self.assertLess(pack, names.index(".git/objects/pack/pack-1.rev"))

    def test_deletes_extra_and_empty_dirs(self) -> None:
        """RF-007-22: lo que el PC ya no tiene se borra del destino, y su carpeta, si
        queda vacía."""
        with mirrored({**PROJECT, "viejo/a.txt": "x", "viejo/b/c.txt": "y"}) as m:
            shutil.rmtree(m.project / "viejo")
            report = m.mirror()
            self.assertFalse((m.dest / "viejo").exists())
        self.assertEqual(sorted(report.deleted), ["viejo/a.txt", "viejo/b/c.txt"])
        self.assertEqual(report.removed_folders, ["viejo/b", "viejo"])

    def test_only_empty_folders_removed(self) -> None:
        """RF-007-22, RF-007-34: una carpeta que el PC ya no tiene pero que en el
        destino conserva algo excluido no se borra (ni lo excluido)."""
        with mirrored({**PROJECT, "viejo/a.txt": "x"}) as m:
            m.write(m.dest, "viejo/Thumbs.db", "miniaturas")
            shutil.rmtree(m.project / "viejo")
            report = m.mirror()
            self.assertEqual(os.listdir(m.dest / "viejo"), ["Thumbs.db"])
        self.assertEqual(report.kept_folders, ["viejo"])

    def test_case_only_rename_in_dest(self) -> None:
        """RF-007-22: un fichero o una carpeta que en el PC solo cambió de mayúsculas se
        renombra en el destino (en dos pasos), nunca se borra."""
        with mirrored({**PROJECT, "docs/Nota.md": "nota\n", "informes/a.txt": "a\n"}) as m:
            for old, new in (("docs/Nota.md", "docs/nota.md"), ("informes", "Informes")):
                (m.project / old).rename(m.project / f"{new}.tmp")
                (m.project / f"{new}.tmp").rename(m.project / new)
            report = m.mirror()
            self.assertIn("nota.md", os.listdir(m.dest / "docs"))
            self.assertIn("Informes", os.listdir(m.dest))
            self.assertEqual(tree_of(m.dest), tree_of(m.project))
        self.assertEqual(report.deleted, [])
        self.assertIn(("docs/Nota.md", "docs/nota.md"), report.renamed)

    def test_read_only_objects_replaced(self) -> None:
        """RF-007-22: git deja sus objetos de solo lectura: el espejo sustituye uno así
        del destino y deja los suyos como en el PC."""
        rel = ".git/objects/ab/cdef0123"
        with mirrored() as m:
            os.chmod(m.dest / rel, stat.S_IREAD)
            m.write(m.project, rel, "objeto, 2\n")
            os.chmod(m.project / rel, stat.S_IREAD)
            m.mirror()
            self.assertEqual((m.dest / rel).read_bytes(), "objeto, 2\n".encode())
            self.assertFalse(os.stat(m.dest / rel).st_mode & stat.S_IWRITE)
            for root in (m.dest, m.project):
                os.chmod(root / rel, stat.S_IWRITE)

    def test_lock_present_stops(self) -> None:
        """RF-007-22: si ya hay un espejo en curso desde este PC a ese destino (su
        cerrojo), otro no empieza; el cerrojo ajeno no se toca."""
        with mirrored() as m:
            with safe_mirror.mirror_lock(m.dest, m.environ) as lock:
                with self.assertRaises(safe_mirror.MirrorBusy) as ctx:
                    with safe_mirror.mirror_lock(m.dest, m.environ):
                        pass
                self.assertTrue(lock.exists())
            self.assertFalse(lock.exists())
        self.assertIn("otro espejo en curso", str(ctx.exception))

    def test_dest_changed_during_copy_untouched(self) -> None:
        """RF-007-34: un fichero del destino que cambia entre la comparación y su
        sustitución no se toca (sigue con sus bytes y su fecha): para con
        ``DestinationChanged`` y sin temporal."""
        with mirrored() as m:
            m.write(m.project, "README.md", "# Del PC\n")

            def hook(action: str, rel: str) -> None:
                if (action, rel) == ("sustituir", "README.md"):
                    m.write(m.dest, rel, "# Del NAS, durante el espejo\n", shift_s=4)

            with self.assertRaises(safe_mirror.DestinationChanged) as ctx:
                m.mirror(hook)
            self.assertEqual((m.dest / "README.md").read_bytes(), "# Del NAS, durante el espejo\n".encode())
            self.assertEqual(list(m.dest.rglob(f"*{layout.MIRROR_TEMP_SUFFIX}")), [])
        self.assertEqual([c.path for c in ctx.exception.changes], ["README.md"])

    def test_dest_created_during_copy_untouched(self) -> None:
        """RF-007-34: un fichero que aparece en el destino donde el espejo iba a crear
        uno no se toca."""
        with mirrored() as m:
            m.write(m.project, "nuevo.txt", "del PC")

            def hook(action: str, rel: str) -> None:
                if (action, rel) == ("sustituir", "nuevo.txt"):
                    m.write(m.dest, rel, "del NAS")

            with self.assertRaises(safe_mirror.DestinationChanged):
                m.mirror(hook)
            self.assertEqual((m.dest / "nuevo.txt").read_bytes(), b"del NAS")

    def test_dest_changed_before_delete_kept(self) -> None:
        """RF-007-34: un fichero que el espejo iba a borrar y que cambia justo antes se
        conserva."""
        with mirrored({**PROJECT, "viejo.txt": "x"}) as m:
            (m.project / "viejo.txt").unlink()

            def hook(action: str, rel: str) -> None:
                if (action, rel) == ("borrar", "viejo.txt"):
                    m.write(m.dest, rel, "cambiado en el NAS", shift_s=2)

            with self.assertRaises(safe_mirror.DestinationChanged):
                m.mirror(hook)
            self.assertEqual((m.dest / "viejo.txt").read_bytes(), b"cambiado en el NAS")

    def test_temp_verified_before_replace(self) -> None:
        """RF-007-34: la copia va a un temporal que se lee de vuelta: si su sha256 no es
        el del PC, se copia otra vez; si sigue mal, el espejo para (``MirrorError``) sin
        tocar el fichero del destino ni dejar el temporal."""
        real_copy = shutil.copy2
        calls: list[int] = []

        def corrupt(times: int):
            def copy(src: object, dst: object, *args: object, **kwargs: object) -> object:
                result = real_copy(src, dst, *args, **kwargs)  # type: ignore[arg-type]
                calls.append(1)
                if len(calls) <= times:
                    Path(dst).write_bytes(b"corrupto")  # type: ignore[arg-type]
                return result
            return copy

        with mirrored() as m:
            m.write(m.project, "README.md", "# Del PC\n")
            with mock.patch("shutil.copy2", side_effect=corrupt(1)):
                m.mirror()
            self.assertEqual((m.dest / "README.md").read_bytes(), "# Del PC\n".encode())
            calls.clear()
            mirror.write_state(m.profile, m.dest)
            safe_mirror.pending_file(m.dest, m.environ).unlink()
            m.write(m.project, "README.md", "# Del PC, 2\n")
            with mock.patch("shutil.copy2", side_effect=corrupt(2)):
                with self.assertRaises(safe_mirror.MirrorError):
                    m.mirror()
            self.assertEqual((m.dest / "README.md").read_bytes(), "# Del PC\n".encode())
            self.assertEqual(list(m.dest.rglob(f"*{layout.MIRROR_TEMP_SUFFIX}")), [])

    def test_interrupted_temp_recognized(self) -> None:
        """RF-007-34, RF-007-29: un espejo cortado deja lo ya copiado y un temporal; el
        siguiente los reconoce (no son cambios del NAS), termina y no deja temporales."""
        with mirrored(empty=True) as m:

            def hook(action: str, rel: str) -> None:
                if (action, rel) == ("sustituir", "README.md"):
                    raise Interrupt()

            with self.assertRaises(Interrupt):
                m.mirror(hook)
            temps = list(m.dest.rglob(f"*{layout.MIRROR_TEMP_SUFFIX}"))
            self.assertEqual([path.name for path in temps], [f"README.md{layout.MIRROR_TEMP_SUFFIX}"])
            self.assertEqual(m.kinds(), [])
            m.mirror()
            self.assertEqual(tree_of(m.dest), tree_of(m.project))

    def test_never_rmtree(self) -> None:
        """RF-007-34: el espejo nunca borra una carpeta con su contenido
        (``shutil.rmtree``): solo ``os.rmdir`` de las vacías."""
        with mirrored({**PROJECT, "viejo/a/b.txt": "x"}) as m:
            shutil.rmtree(m.project / "viejo")
            with mock.patch("shutil.rmtree", side_effect=AssertionError("rmtree")):
                m.mirror()
            self.assertFalse((m.dest / "viejo").exists())


def mirror_and_verify(m: Mirrored) -> tuple[safe_mirror.MirrorReport, safe_mirror.Verification]:
    """Compara, hace el espejo y lo verifica (sin guardar el estado)."""
    base = safe_mirror.load_base(m.dest, m.environ)
    assert base is not None
    source = safe_mirror.scan_source(m.project)
    listing = safe_mirror.scan_destination(m.dest)
    pending = safe_mirror.load_pending(m.dest, m.environ)
    changes, observed = safe_mirror.destination_changes(m.dest, base, source, listing, pending)
    assert not changes, changes
    report = safe_mirror.mirror(m.project, m.dest, source, listing, observed, base, m.environ)
    return report, safe_mirror.verify(m.dest, source, report, observed)


def save(m: Mirrored, verification: safe_mirror.Verification) -> None:
    state = safe_mirror.new_state(m.dest, m.project, verification, {}, m.environ)
    safe_mirror.save_state(m.dest, m.environ, state)


class VerifyTest(unittest.TestCase):
    """RF-007-23, RF-007-30: la comprobación del espejo (sin copiar ni borrar) y el
    estado que se guarda: con lo comprobado, nunca con una lectura posterior."""

    def test_verify_ok(self) -> None:
        """RF-007-23: tras un espejo sin incidencias, cada fichero del PC está en el
        destino con su sha256 (sin volver a leer los que no cambiaron de tamaño ni de
        fecha) y no sobra nada."""
        with mirrored(empty=True) as m:
            report, verification = mirror_and_verify(m)
        self.assertEqual((verification.problems, verification.changes), ([], []))
        self.assertEqual(verification.identical, len(PROJECT))
        self.assertEqual(verification.files["README.md"], report.verified["README.md"])

    def test_verify_detects_difference(self) -> None:
        """RF-007-23: un fichero que falta es un problema (código 1); uno con otro
        contenido o uno que sobra (también una carpeta) es un cambio del NAS (código 3),
        nunca algo que borrar."""
        with mirrored(empty=True) as m:
            base = safe_mirror.load_base(m.dest, m.environ)
            assert base is not None
            source = safe_mirror.scan_source(m.project)
            listing = safe_mirror.scan_destination(m.dest)
            _changes, observed = safe_mirror.destination_changes(m.dest, base, source, listing)
            report = safe_mirror.mirror(m.project, m.dest, source, listing, observed, base, m.environ)
            (m.dest / f"{CODE}/README.md").unlink()
            m.write(m.dest, "README.md", "# Cambiado en el NAS tras copiarlo\n", shift_s=3)
            m.write(m.dest, "docs/sobra.txt", "x")
            (m.dest / "nueva").mkdir()
            verification = safe_mirror.verify(m.dest, source, report, observed)
        self.assertEqual(len(verification.problems), 1)
        self.assertIn(f"{CODE}/README.md", verification.problems[0])
        self.assertEqual(
            [(c.kind, c.path) for c in verification.changes],
            [
                (safe_mirror.NEW, "docs/sobra.txt"),
                (safe_mirror.NEW_FOLDER, "nueva"),
                (safe_mirror.CHANGED, "README.md"),
            ],
        )

    def test_verify_never_copies_or_deletes(self) -> None:
        """RF-007-23: la comprobación solo lee: con diferencias, el destino sigue igual."""
        with mirrored() as m:
            report, _verification = mirror_and_verify(m)
            m.write(m.dest, "docs/sobra.txt", "x")
            before = gbrepo.snapshot(m.dest)
            source = safe_mirror.scan_source(m.project)
            with mock.patch("shutil.copy2", side_effect=AssertionError), mock.patch(
                "os.unlink", side_effect=AssertionError
            ), mock.patch("os.replace", side_effect=AssertionError):
                safe_mirror.verify(m.dest, source, report, {})
            self.assertEqual(gbrepo.snapshot_changes(before, gbrepo.snapshot(m.dest)), [])

    def test_state_keeps_compared_stat(self) -> None:
        """RF-007-30: el estado guarda el tamaño y la fecha con que se comprobó cada
        sha256 (el del temporal de lo copiado; lo comparado de lo demás), no una
        lectura posterior: un cambio hecho en el NAS justo después de comprobarlo se ve
        en el espejo siguiente."""
        with mirrored() as m:
            m.write(m.project, "README.md", "# Del PC, 2\n")
            report, verification = mirror_and_verify(m)
            m.write(m.dest, "docs/constitution.md", "# Cambiada en el NAS tras comprobarla\n", shift_s=5)
            save(m, verification)
            state = safe_mirror.load_base(m.dest, m.environ)
            self.assertEqual(m.kinds(), [(safe_mirror.CHANGED, "docs/constitution.md")])
        assert state is not None
        self.assertEqual(state.files["README.md"], report.verified["README.md"])
        self.assertFalse(safe_mirror.pending_file(m.dest, m.environ).exists())

    def test_state_records_folders(self) -> None:
        """RF-007-30: el estado guarda las carpetas del destino (también las vacías):
        una carpeta suya no es «nueva» en el espejo siguiente, y una creada después sí."""
        with mirrored(empty=True) as m:
            (m.project / ".git" / "refs" / "tags").mkdir(parents=True)
            _report, verification = mirror_and_verify(m)
            save(m, verification)
            state = safe_mirror.load_base(m.dest, m.environ)
            self.assertEqual(m.kinds(), [])
            (m.dest / "Documentacion").mkdir()
            self.assertEqual(m.kinds(), [(safe_mirror.NEW_FOLDER, "Documentacion")])
        assert state is not None
        self.assertIn(".git/refs/tags", state.folders)
        self.assertFalse(state.photo)

    def test_date_only_change_updates_state(self) -> None:
        """RF-007-30: si en el destino solo cambió la fecha de un fichero, no se copia y
        el estado guarda la fecha nueva: el espejo siguiente no lo vuelve a leer."""
        with mirrored() as m:
            path = m.dest / "README.md"
            stamp = path.stat().st_mtime_ns + 6 * 10**9
            os.utime(path, ns=(stamp, stamp))
            report, verification = mirror_and_verify(m)
            save(m, verification)
            state = safe_mirror.load_base(m.dest, m.environ)
            with mock.patch.object(safe_mirror, "observe", side_effect=AssertionError):
                self.assertEqual(m.kinds(), [])
        self.assertEqual(report.copied, [])
        assert state is not None
        self.assertEqual(state.files["README.md"].mtime_ns, stamp)


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

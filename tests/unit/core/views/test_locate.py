# SPDX-License-Identifier: GPL-3.0-or-later
"""Dónde está el proyecto de una vista (spec 010, T06; RF-010-04, RF-010-05; plan 010 §5.3.1,
A5 y D-14).

``core.views.locate`` decide, sin interfaz y sin escribir nada:

- cuándo no se ofrece «Abrir el proyecto de esta vista» (:func:`offer_refusal`): con Blender sin
  interfaz, en un fichero de recuperación (``quit.blend``) o de autoguardado
  (``*_autosave.blend``) de la carpeta temporal de Blender, y en una vista que está dentro de una
  copia de respaldo del proyecto (``<Nombre>.gbproj.anterior``, ``.publicando`` o
  ``.respaldo-esquema-N[-n]``, con las marcas de ``core.project``);
- la identidad de una carpeta (:func:`project_identity`, el ``project_uid`` de su
  ``manifest.json``, sin cerrojo);
- dónde está el proyecto (:func:`find_project`): por la ruta relativa que guarda la vista
  (``//../`` desde ``scenes/``, o desde fuera del proyecto en el mismo volumen) y, si no está allí
  o la vista no la tiene (otro volumen), por su identidad entre los recientes del equipo; si no,
  con la ubicación y la identidad esperadas y lo que hay allí;
- si la carpeta que elige la persona es ese proyecto (:func:`check_chosen`).

Carpetas temporales con ``manifest.json`` sintéticos; cada consulta deja la carpeta candidata con
el mismo listado, las mismas fechas y las mismas huellas (sha256) que antes.
"""

from __future__ import annotations

import json
import os
import unittest
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

from tests.support.package import import_geoblender
from tests.support.provenance_checks import assert_source_untouched
from tests.support.trees import age_folders, temp_folder

locate = import_geoblender("core.views.locate")
checkout = import_geoblender("core.project.checkout")
migrations = import_geoblender("core.project.migrations")
paths = import_geoblender("core.paths")
userdata = import_geoblender("core.userdata")

Refusal = locate.Refusal
ViewLink = locate.ViewLink
Located = locate.Located
NotFound = locate.NotFound
RecentProject = userdata.RecentProject

UID = "4f1c2b9a-6d3e-4a71-9c55-0e2f8b7d1a20"
OTHER_UID = "9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d"
NAME = "Cantera"
OPENED = "2026-10-17T08:00:00.000Z"


def write_manifest(root: Path, uid: object = UID, *, fmt: str = "geoblender-project") -> Path:
    """Una carpeta de proyecto con un ``manifest.json`` sintético (solo lo que lee la
    identidad, más un campo cualquiera) y su ``scenes/``."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "scenes").mkdir(exist_ok=True)
    (root / "manifest.json").write_text(
        json.dumps({"format": fmt, "project_uid": uid, "name": NAME}), encoding="utf-8"
    )
    return root


def same(first: Path, second: Path) -> bool:
    """Verdadero si las dos rutas son la misma carpeta (sin distinguir mayúsculas)."""
    return os.path.normcase(os.path.normpath(first)) == os.path.normcase(os.path.normpath(second))


class Counting:
    """La identidad de verdad, anotando cada carpeta que lee."""

    def __init__(self) -> None:
        self.read: list[Path] = []

    def __call__(self, folder: Path) -> str | None:
        self.read.append(Path(folder))
        return locate.project_identity(folder)


class LocateTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = temp_folder(self, "gb-loc-")

    def link(self, relative_path: str = "//../") -> object:
        return ViewLink(UID, NAME, relative_path)

    @contextmanager
    def untouched(self, *folders: Path) -> Iterator[None]:
        """Falla al salir si algo cambió en alguna de las carpetas (listado, fechas y sha256);
        antes retrasa su fecha, para ver también lo que se crea y se borra dentro."""
        for folder in folders:
            age_folders(folder)
        with ExitStack() as stack:
            for folder in folders:
                stack.enter_context(assert_source_untouched(folder))
            yield


class OfferRefusalTest(LocateTestCase):
    """RF-010-04: cuándo no se ofrece abrir el proyecto de una vista."""

    def setUp(self) -> None:
        super().setUp()
        self.temp = self.tmp / "Temp"
        self.temp.mkdir()
        self.view = self.tmp / "vistas" / "plano.blend"

    def refusal(self, blend_file: object, *, background: bool = False,
                temp_dirs: tuple[Path, ...] | None = None) -> object:
        dirs = (self.temp,) if temp_dirs is None else temp_dirs
        return locate.offer_refusal(blend_file, background=background, temp_dirs=dirs)

    def test_a_view_of_a_project_is_offered(self) -> None:
        """RF-010-04: una vista corriente, guardada o sin guardar, sí lo ofrece."""
        self.assertIsNone(self.refusal(str(self.view)))
        self.assertIsNone(self.refusal(str(self.tmp / NAME / "scenes" / "principal.blend")))
        self.assertIsNone(self.refusal(None))
        self.assertIsNone(self.refusal(""))

    def test_never_without_interface(self) -> None:
        """RF-010-04: con Blender sin interfaz no se ofrece nunca."""
        for blend_file in (str(self.view), None, str(self.temp / "quit.blend")):
            with self.subTest(blend_file=blend_file):
                self.assertIs(self.refusal(blend_file, background=True), Refusal.BACKGROUND)

    def test_recovery_and_autosave_in_the_temporary_folder(self) -> None:
        """RF-010-04, D-14: ``quit.blend`` y ``*_autosave.blend`` en la carpeta temporal de
        Blender (la que se le pase, sin distinguir mayúsculas) no lo ofrecen; con el mismo
        nombre en otra carpeta, sí."""
        upper = Path(str(self.temp).upper())
        cases = {
            self.temp / "quit.blend": Refusal.RECOVERY,
            upper / "QUIT.BLEND": Refusal.RECOVERY,
            self.temp / "plano_8124_autosave.blend": Refusal.AUTOSAVE,
            self.temp / "8124_autosave.blend": Refusal.AUTOSAVE,
            self.tmp / "vistas" / "quit.blend": None,
            self.tmp / "vistas" / "plano_8124_autosave.blend": None,
            self.temp / "plano.blend": None,
            self.temp / "quit.blend1": None,
        }
        for blend_file, expected in cases.items():
            with self.subTest(blend_file=blend_file.name, folder=blend_file.parent.name):
                self.assertIs(self.refusal(str(blend_file)), expected)
        other = self.tmp / "OtraTemp"
        self.assertIs(
            self.refusal(str(other / "quit.blend"), temp_dirs=(Path(""), self.temp, other)),
            Refusal.RECOVERY,
        )
        self.assertIsNone(self.refusal(str(self.temp / "quit.blend"), temp_dirs=()))

    def test_inside_a_backup_copy_of_the_project(self) -> None:
        """RF-010-04: dentro de ``<Nombre>.gbproj.anterior``, ``.publicando`` o
        ``.respaldo-esquema-N[-n]`` (las marcas de ``core.project``), a cualquier nivel, no
        se ofrece; una carpeta que solo se parece, sí."""
        original = self.tmp / f"{NAME}.gbproj"
        first = migrations.backup_path(original, 1)
        first.mkdir()
        second = migrations.backup_path(original, 1)
        self.assertEqual(second.name, f"{NAME}.gbproj{migrations.BACKUP_MARK}1-2")
        refused = (
            checkout.previous_path(original),
            checkout.publishing_path(original),
            first,
            second,
            original.parent / f"{NAME.upper()}.GBPROJ{checkout.PREVIOUS_MARK.upper()}",
        )
        for copy in refused:
            for blend_file in (copy / "scenes" / "principal.blend",
                               copy / "scenes" / "planos" / "fase-1.blend"):
                with self.subTest(copy=copy.name, depth=len(blend_file.parts)):
                    self.assertIs(self.refusal(str(blend_file)), Refusal.BACKUP_COPY)
        offered = (
            original,
            self.tmp / f"{NAME}.anterior",
            self.tmp / f"{NAME}.gbproj.anterior-notas",
            self.tmp / f"{NAME}.gbproj{migrations.BACKUP_MARK}x",
            self.tmp / f"{NAME}.gbproj{migrations.BACKUP_MARK}1-2-3",
            self.tmp / f"{NAME}.gbproj{checkout.DISCARD_MARK}",
        )
        for folder in offered:
            with self.subTest(folder=folder.name):
                self.assertIsNone(self.refusal(str(folder / "scenes" / "principal.blend")))
        # La copia de respaldo es el fichero, no una carpeta cualquiera con ese nombre.
        self.assertIsNone(self.refusal(str(self.tmp / f"{NAME}.gbproj.anterior")))


class ProjectIdentityTest(LocateTestCase):
    """RF-010-04, RF-010-05: la identidad de una carpeta, sin cerrojo y sin escribir."""

    def test_identity_of_a_project_folder(self) -> None:
        """RF-010-04: el ``project_uid`` de ``manifest.json``; nada cambia en la carpeta (ni
        un ``.lock``)."""
        root = write_manifest(self.tmp / f"{NAME}.gbproj")
        with self.untouched(root):
            self.assertEqual(locate.project_identity(root), UID)
        self.assertFalse((root / ".lock").exists())

    def test_folders_without_identity(self) -> None:
        """RF-010-05: sin carpeta, sin cabecera, con una cabecera que no es JSON, de otro
        formato o sin una identidad de texto: ninguna identidad (``None``), sin errores."""
        self.assertIsNone(locate.project_identity(self.tmp / "no-existe"))
        empty = self.tmp / "vacia"
        empty.mkdir()
        self.assertIsNone(locate.project_identity(empty))
        a_file = self.tmp / "fichero.txt"
        a_file.write_text("x", encoding="utf-8")
        self.assertIsNone(locate.project_identity(a_file))
        broken = self.tmp / "rota"
        broken.mkdir()
        (broken / "manifest.json").write_text("{no es json", encoding="utf-8")
        self.assertIsNone(locate.project_identity(broken))
        binary = self.tmp / "binaria"
        binary.mkdir()
        (binary / "manifest.json").write_bytes(b"\xff\xfe\x00\x81")
        self.assertIsNone(locate.project_identity(binary))
        cases = {
            "otro-formato": ("otra-cosa", UID),
            "sin-texto": ("geoblender-project", 12),
            "vacia-uid": ("geoblender-project", "  "),
            "nula": ("geoblender-project", None),
        }
        for name, (fmt, uid) in cases.items():
            with self.subTest(name=name):
                folder = write_manifest(self.tmp / name, uid, fmt=fmt)
                self.assertIsNone(locate.project_identity(folder))
        listed = self.tmp / "lista"
        listed.mkdir()
        (listed / "manifest.json").write_text("[1, 2]", encoding="utf-8")
        self.assertIsNone(locate.project_identity(listed))


class FindProjectTest(LocateTestCase):
    """RF-010-04, RF-010-05: dónde está el proyecto de una vista."""

    def setUp(self) -> None:
        super().setUp()
        self.root = write_manifest(self.tmp / "proyectos" / f"{NAME}.gbproj")
        self.view = self.root / "scenes" / "principal.blend"
        self.outside = self.tmp / "planos" / "fase-1" / "plano.blend"
        self.outside.parent.mkdir(parents=True)

    def recent(self, path: Path, uid: str = UID, name: str = NAME) -> object:
        return RecentProject(uid, name, path, OPENED)

    def test_relative_path_from_scenes(self) -> None:
        """RF-010-04: la ruta que guarda una vista de ``scenes/`` (``//../``, la que escribe la
        002 con ``blend_relative_path``) lleva al proyecto, sin mirar los recientes."""
        relative = paths.blend_relative_path(self.root, self.view)
        self.assertEqual(relative, "//../")
        counting = Counting()
        with self.untouched(self.root):
            found = locate.find_project(self.link(relative), self.view, (), identity=counting)
        self.assertIsInstance(found, Located)
        self.assertTrue(same(found.root, self.root))
        self.assertEqual(found.how, locate.RELATIVE)
        self.assertEqual(len(counting.read), 1)
        # La vista guardada en la raíz del proyecto («//»), también.
        beside = self.root / "vista.blend"
        found = locate.find_project(
            self.link(paths.blend_relative_path(self.root, beside)), beside, ()
        )
        self.assertTrue(same(found.root, self.root))

    def test_relative_path_from_outside_on_the_same_volume(self) -> None:
        """RF-010-04: una vista guardada fuera del proyecto en el mismo volumen
        (``//../../proyectos/Cantera.gbproj/``) lo encuentra por su ruta relativa, aunque
        haya un reciente con su identidad en otro sitio."""
        relative = paths.blend_relative_path(self.root, self.outside)
        self.assertEqual(relative, f"//../../proyectos/{NAME}.gbproj/")
        elsewhere = write_manifest(self.tmp / "copia" / f"{NAME}.gbproj")
        with self.untouched(self.root, elsewhere):
            found = locate.find_project(
                self.link(relative), self.outside, (self.recent(elsewhere),)
            )
        self.assertEqual(found.how, locate.RELATIVE)
        self.assertTrue(same(found.root, self.root))

    def test_recent_projects_by_identity(self) -> None:
        """RF-010-04: sin ruta relativa (vista en otro volumen) o si allí no está (la vista se
        copió a otro sitio), el reciente de esa identidad que existe y la tiene; los recientes
        de otros proyectos no se leen."""
        other = write_manifest(self.tmp / "Otro.gbproj", OTHER_UID)
        moved = self.tmp / "Movido.gbproj"
        recents = (
            self.recent(other, OTHER_UID, "Otro"),
            self.recent(moved),  # ya no existe
            self.recent(self.root),
        )
        far = Path("Q:/vistas/plano.blend")
        self.assertEqual(paths.blend_relative_path(self.root, far), "")
        copied = self.tmp / "copiada" / "plano.blend"
        copied.parent.mkdir()
        cases = {
            "otro volumen": (self.link(""), far),
            "copiada": (self.link(f"//../../proyectos/{NAME}.gbproj/"), copied),
            "sin guardar": (self.link(""), None),
        }
        for label, (link, blend_file) in cases.items():
            with self.subTest(label=label):
                counting = Counting()
                with self.untouched(self.root, other):
                    found = locate.find_project(link, blend_file, recents, identity=counting)
                self.assertIsInstance(found, Located)
                self.assertEqual(found.how, locate.RECENT)
                self.assertTrue(same(found.root, self.root))
                self.assertFalse(any(same(path, other) for path in counting.read))

    def test_another_identity_is_not_the_project(self) -> None:
        """RF-010-05: si en la ruta relativa hay otro proyecto (u otro proyecto ocupa la carpeta
        de un reciente), no se abre: ``NotFound`` con la ubicación esperada, la identidad
        esperada y la que hay allí."""
        impostor = write_manifest(self.tmp / "planos" / f"{NAME}.gbproj", OTHER_UID)
        relative = paths.blend_relative_path(impostor, self.outside)
        with self.untouched(impostor):
            found = locate.find_project(
                self.link(relative), self.outside, (self.recent(impostor),)
            )
        self.assertIsInstance(found, NotFound)
        self.assertTrue(same(found.expected, impostor))
        self.assertEqual(found.found_uid, OTHER_UID)
        self.assertEqual(found.link, self.link(relative))
        self.assertEqual(found.link.project_uid, UID)
        # Sin ruta relativa, la ubicación esperada es la del reciente que no la tiene.
        found = locate.find_project(self.link(""), self.outside, (self.recent(impostor),))
        self.assertIsInstance(found, NotFound)
        self.assertTrue(same(found.expected, impostor))
        self.assertEqual(found.found_uid, OTHER_UID)

    def test_nothing_found(self) -> None:
        """RF-010-05: ni en la ruta relativa ni entre los recientes: ``NotFound`` con la
        ubicación esperada (la relativa, si la hay) y sin identidad encontrada; sin ruta ni
        recientes, sin ubicación."""
        gone = f"//../../proyectos/{NAME}-movido.gbproj/"
        found = locate.find_project(self.link(gone), self.outside, ())
        self.assertIsInstance(found, NotFound)
        self.assertTrue(same(found.expected, self.tmp / "proyectos" / f"{NAME}-movido.gbproj"))
        self.assertIsNone(found.found_uid)
        found = locate.find_project(self.link(""), self.outside, ())
        self.assertEqual(found, NotFound(None, self.link(""), None))

    def test_only_blender_relative_paths(self) -> None:
        """RF-010-04, RF-002-18: la vista nunca guarda una ruta absoluta; si trae una (o una
        relativa sin el «//» de Blender), no se usa: se busca entre los recientes."""
        for odd in (str(self.root), self.root.as_posix(), f"../proyectos/{NAME}.gbproj"):
            with self.subTest(relative_path=odd):
                counting = Counting()
                found = locate.find_project(self.link(odd), self.outside, (), identity=counting)
                self.assertEqual(found, NotFound(None, self.link(odd), None))
                self.assertEqual(counting.read, [])


class CheckChosenTest(LocateTestCase):
    """RF-010-05: «Localizar el proyecto…» solo acepta un proyecto con esa identidad."""

    def test_chosen_folder(self) -> None:
        """RF-010-05: la carpeta con la identidad de la vista, sí; con otra o sin cabecera,
        ``NotFound`` con esa carpeta y lo que tiene; nada cambia en ella."""
        root = write_manifest(self.tmp / f"{NAME}.gbproj")
        other = write_manifest(self.tmp / "Otro.gbproj", OTHER_UID)
        empty = self.tmp / "vacia"
        empty.mkdir()
        with self.untouched(root, other, empty):
            chosen = locate.check_chosen(root, self.link())
            refused = locate.check_chosen(other, self.link())
            nothing = locate.check_chosen(empty, self.link())
        self.assertEqual(chosen, Located(root, locate.CHOSEN))
        self.assertEqual(refused, NotFound(other, self.link(), OTHER_UID))
        self.assertEqual(nothing, NotFound(empty, self.link(), None))
        counting = Counting()
        self.assertEqual(locate.check_chosen(root, self.link(), identity=counting).how,
                         locate.CHOSEN)
        self.assertEqual(counting.read, [root])


if __name__ == "__main__":
    unittest.main()

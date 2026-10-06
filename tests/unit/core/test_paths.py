# SPDX-License-Identifier: GPL-3.0-or-later
"""Rutas del proyecto (spec 002, T10; RF-002-02, RF-002-18, RF-002-19, RF-002-30;
ADR-0006 §5; formato-proyecto §1).

- Una carpeta de red (UNC o unidad de red) se detecta; la detección de la unidad es
  inyectable, y las pruebas no tocan ninguna unidad de red real.
- La ubicación de un fichero externo se guarda relativa a la raíz del proyecto
  **original** (también desde una copia local, cuya ruta del original está en los datos
  de usuario) si está en el mismo volumen; si no, solo su nombre, con la ruta completa
  anotada en los datos de usuario del equipo. Sin anotación, «no localizable» (``None``).
- El detector de rutas absolutas encuentra las de Windows, las UNC y las de Linux o
  macOS, y no confunde «m/s» ni una URL.
- Un nombre de proyecto tiene que ser válido en Windows.
"""

import ntpath
import os
import unittest
from dataclasses import dataclass
from pathlib import Path

from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender

paths = import_geoblender("core.paths")
userdata_mod = import_geoblender("core.userdata")
errors = import_geoblender("core.errors")

UID = "00000000-0000-4000-8000-0000000000aa"


@dataclass(frozen=True)
class FakeProject:
    """Lo que ``core.paths`` necesita de un proyecto: su identidad y su raíz."""

    uid: str
    root: Path


def _normalised(path: Path) -> Path:
    """Canonización sin tocar el disco ni la red (para rutas de otras unidades)."""
    return Path(ntpath.normpath(ntpath.abspath(str(path))))


class NetworkPathTest(unittest.TestCase):
    def test_unc_is_network(self) -> None:
        """RF-002-30: una ruta UNC, con barras invertidas o normales, es de red."""
        never = lambda root: 3  # noqa: E731 — una unidad fija
        self.assertTrue(paths.is_network_path(Path("\\\\srv\\recurso\\P.gbproj"), never))
        self.assertTrue(paths.is_network_path(Path("//srv/recurso/P.gbproj"), never))

    def test_simulated_drive_types(self) -> None:
        """RF-002-30: una unidad de red simulada (``DRIVE_REMOTE`` = 4) es de red; una fija
        (3), no; se pregunta por la raíz de la unidad."""
        asked: list[str] = []

        def remote(root: str) -> int:
            asked.append(root)
            return 4

        self.assertTrue(paths.is_network_path(Path("X:/proyectos/P.gbproj"), remote))
        self.assertEqual(asked, ["X:\\"])
        self.assertFalse(paths.is_network_path(Path("X:/proyectos/P.gbproj"), lambda r: 3))

    def test_local_temp_is_not_network(self) -> None:
        """RF-002-30: la carpeta temporal local no es de red (detección real)."""
        with project_tmp() as tmp:
            self.assertFalse(paths.is_network_path(tmp))


class ExternalRefTest(unittest.TestCase):
    def test_same_volume_relative_to_project(self) -> None:
        """RF-002-19: en el mismo volumen, ruta relativa con «/» desde la raíz del
        proyecto, que vuelve a la misma ruta."""
        with project_tmp() as tmp:
            root = tmp / "proyectos" / "P.gbproj"
            root.mkdir(parents=True)
            target = tmp / "cliente" / "datos" / "limites.gpkg"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"x")
            data = userdata_mod.UserData(tmp / "datos-usuario")
            project = FakeProject(UID, root)
            ref = paths.make_external_ref(target, project, data)
            self.assertEqual(ref.anchor, "project")
            self.assertEqual(ref.path, "../../cliente/datos/limites.gpkg")
            self.assertTrue(ref.ref_uid)
            resolved = paths.resolve_external_ref(ref, project, data)
            self.assertEqual(os.path.normcase(resolved), os.path.normcase(target.resolve()))
            self.assertFalse((tmp / "datos-usuario").exists())  # nada que anotar

    def test_relative_to_original_from_local_copy(self) -> None:
        """RF-002-19: desde una copia local, la ruta relativa es la del **original** (sale
        de los datos de usuario), y se resuelve igual desde la copia."""
        with project_tmp() as tmp:
            original = tmp / "red" / "proyectos" / "P.gbproj"
            original.mkdir(parents=True)
            copy = tmp / "copias" / "P.gbproj"
            copy.mkdir(parents=True)
            target = tmp / "red" / "cliente" / "limites.gpkg"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"x")
            data = userdata_mod.UserData(tmp / "datos-usuario")
            data.set_checkout_record(UID, {"original": str(original), "copy": str(copy)})
            project = FakeProject(UID, copy)
            ref = paths.make_external_ref(target, project, data)
            self.assertEqual((ref.anchor, ref.path), ("project", "../../cliente/limites.gpkg"))
            resolved = paths.resolve_external_ref(ref, project, data)
            self.assertEqual(os.path.normcase(resolved), os.path.normcase(target.resolve()))

    def test_other_volume_name_and_annotation(self) -> None:
        """RF-002-19: en otro volumen (otra unidad u otro servidor), solo el nombre en el
        proyecto y la ruta completa anotada en los datos de usuario del equipo; en otro
        equipo sin esa anotación, «no localizable» (``None``)."""
        with project_tmp() as tmp:
            project = FakeProject(UID, Path("C:/proyectos/P.gbproj"))
            data = userdata_mod.UserData(tmp / "equipo-a")
            for target in (Path("D:/datos/mdt.tif"), Path("//srv/recurso/mdt.tif")):
                with self.subTest(target=str(target)):
                    ref = paths.make_external_ref(target, project, data, canonical=_normalised)
                    self.assertEqual((ref.anchor, ref.path), ("external", "mdt.tif"))
                    found = paths.resolve_external_ref(ref, project, data, canonical=_normalised)
                    self.assertEqual(found, _normalised(target))
                    other = userdata_mod.UserData(tmp / "equipo-b")
                    self.assertIsNone(
                        paths.resolve_external_ref(ref, project, other, canonical=_normalised)
                    )
            stored = (tmp / "equipo-a" / "projects" / UID / "external_refs.json").read_text(
                encoding="utf-8"
            )
            self.assertIn("mdt.tif", stored)

    def test_external_ref_is_relative_text(self) -> None:
        """RF-002-18: lo que se guarda en el proyecto (``anchor`` y ``path``) no contiene
        ninguna ruta absoluta."""
        with project_tmp() as tmp:
            project = FakeProject(UID, Path("C:/proyectos/P.gbproj"))
            data = userdata_mod.UserData(tmp / "u")
            ref = paths.make_external_ref(
                Path("D:/datos/mdt.tif"), project, data, canonical=_normalised
            )
            self.assertEqual(paths.find_absolute_paths([ref.anchor, ref.path]), [])


class AbsolutePathDetectorTest(unittest.TestCase):
    def test_detects_absolute_paths(self) -> None:
        """RF-002-18: encuentra ``C:\\x``, ``\\\\srv\\x`` y ``/mnt/x`` (también dentro de
        textos, listas y diccionarios, y en las claves) y no ``m/s``, una ruta relativa,
        una URL ni ``a:b``."""
        value = {
            "a": "C:\\x",
            "b": ["\\\\srv\\x", {"c": "/mnt/x"}],
            "d": "m/s",
            "e": "rasters/dtm.tif",
            "f": "https://epsg.org/terms-of-use.html",
            "g": "a:b",
            "h": ("fichero C:/datos/x.tif no encontrado", 3, None, 2.5),
            "D:\\clave": 1,
            "i": "//srv/recurso/x",
        }
        found = paths.find_absolute_paths(value)
        self.assertEqual(
            sorted(found),
            sorted(
                ["C:\\x", "\\\\srv\\x", "/mnt/x", "C:/datos/x.tif", "D:\\clave", "//srv/recurso/x"]
            ),
        )
        self.assertEqual(paths.find_absolute_paths(["m/s", "km/h", "t/m3", "1/2"]), [])


class ProjectNameTest(unittest.TestCase):
    def test_valid_names(self) -> None:
        """RF-002-02: un nombre válido se devuelve sin espacios a los lados; con 100
        caracteres, también."""
        self.assertEqual(paths.validate_project_name("  Cantera Ejemplo  "), "Cantera Ejemplo")
        name = "Cantera_V10-b (2026), ñandú"
        self.assertEqual(paths.validate_project_name(name), name)
        self.assertEqual(len(paths.validate_project_name("a" * 100)), 100)

    def test_invalid_names(self) -> None:
        """RF-002-02: ``CON``, ``nul``, ``COM1`` (también con extensión), ``a:b``, otros
        caracteres prohibidos, de control, vacío, acabado en punto o espacio y más de 100
        caracteres se rechazan con el carácter o el nombre."""
        cases = {
            "CON": "CON",
            "nul": "nul",
            "COM1.datos": "COM1",
            "LPT9": "LPT9",
            "a:b": ":",
            "a/b": "/",
            "a\\b": "\\",
            'a"b': '"',
            "a*b": "*",
            "a?b": "?",
            "a<b>": "<",
            "a|b": "|",
            "a\tb": "control",
            "": "vacío",
            "   ": "vacío",
            "nombre.": "punto",
            "a" * 101: "101",
        }
        for name, shown in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(errors.ValidationError) as caught:
                    paths.validate_project_name(name)
                self.assertEqual(caught.exception.code, "core.project_name_invalid")
                self.assertIn(shown, str(caught.exception))


if __name__ == "__main__":
    unittest.main()

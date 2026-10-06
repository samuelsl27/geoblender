# SPDX-License-Identifier: GPL-3.0-or-later
"""Datos de usuario de la extensión fuera de los proyectos (spec 002, T10; RF-002-08,
RF-002-13, RF-002-18, RF-002-19, RF-002-30, RF-002-31; plan 002 §5.2).

Lo que es de un equipo y no de un proyecto: los 10 proyectos recientes, las rutas
completas de las fuentes de otro volumen, el registro de una copia local, la caché de un
proyecto abierto desde la red o en solo lectura, las copias privadas de lectura y la
carpeta de copias locales. ``bl`` calcula la raíz con ``extension_path_user`` y se la
pasa a ``core`` como ``Path``. Nada de esto entra en un proyecto.
"""

import json
import unittest
from pathlib import Path

from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender

userdata_mod = import_geoblender("core.userdata")
errors = import_geoblender("core.errors")

UID = "00000000-0000-4000-8000-0000000000aa"
SESSION = "00000000-0000-4000-8000-000000000001"


class FoldersTest(unittest.TestCase):
    def test_folders(self) -> None:
        """RF-002-13, RF-002-30, RF-002-31: caché de un proyecto (``cache/<uid>/``), caché
        sin proyecto, copias privadas por sesión (``readonly/<sesión>/``) y copias locales
        (``checkouts/``), todas bajo la raíz de los datos de usuario."""
        with project_tmp() as tmp:
            data = userdata_mod.UserData(tmp)
            self.assertEqual(data.cache_dir(UID), tmp / "cache" / UID)
            self.assertEqual(data.no_project_cache_dir(), tmp / "cache" / "_sin_proyecto")
            self.assertEqual(data.private_read_dir(SESSION), tmp / "readonly" / SESSION)
            self.assertEqual(data.checkouts_dir(), tmp / "checkouts")
            self.assertEqual(data.project_dir(UID), tmp / "projects" / UID)
            self.assertEqual(list(tmp.iterdir()), [])  # calcular una ruta no crea nada

    def test_unsafe_identifiers(self) -> None:
        """RF-002-18: un uid o una sesión que no son un identificador (con barras, ``..``
        o vacíos) se rechazan: no pueden salirse de la carpeta."""
        with project_tmp() as tmp:
            data = userdata_mod.UserData(tmp)
            for bad in ("..", "../x", "a/b", "a\\b", "", "C:x"):
                with self.subTest(bad=bad):
                    with self.assertRaises(errors.ValidationError):
                        data.cache_dir(bad)
                    with self.assertRaises(errors.ValidationError):
                        data.private_read_dir(bad)


class ExternalRefsTest(unittest.TestCase):
    def test_annotations_per_project(self) -> None:
        """RF-002-19: la ruta completa de una fuente se anota por proyecto y por
        ``ref_uid`` en ``projects/<uid>/external_refs.json``; sin anotación, ``None``."""
        with project_tmp() as tmp:
            data = userdata_mod.UserData(tmp)
            self.assertIsNone(data.external_ref(UID, "r1"))
            data.set_external_ref(UID, "r1", Path("D:/datos/mdt.tif"))
            data.set_external_ref(UID, "r2", Path("D:/datos/otra.tif"))
            self.assertEqual(data.external_ref(UID, "r1"), Path("D:/datos/mdt.tif"))
            stored = json.loads(
                (tmp / "projects" / UID / "external_refs.json").read_text(encoding="utf-8")
            )
            self.assertEqual(set(stored), {"r1", "r2"})
            self.assertIsNone(data.external_ref("00000000-0000-4000-8000-0000000000bb", "r1"))


class CheckoutRecordTest(unittest.TestCase):
    def test_record_round_trip(self) -> None:
        """RF-002-31: el registro de una copia local (original, copia, sesión, huellas) se
        guarda en ``projects/<uid>/checkout.json``, se lee y se borra."""
        with project_tmp() as tmp:
            data = userdata_mod.UserData(tmp)
            self.assertIsNone(data.checkout_record(UID))
            self.assertIsNone(data.checkout_original(UID))
            record = {"original": "X:/proyectos/P.gbproj", "copy": "C:/copias/P.gbproj"}
            data.set_checkout_record(UID, record)
            self.assertEqual(data.checkout_record(UID), record)
            self.assertEqual(data.checkout_original(UID), Path("X:/proyectos/P.gbproj"))
            data.clear_checkout_record(UID)
            self.assertIsNone(data.checkout_record(UID))
            data.clear_checkout_record(UID)  # sin registro, no hace nada


class RecentProjectsTest(unittest.TestCase):
    def test_last_ten_most_recent_first(self) -> None:
        """RF-002-08: la lista de recientes guarda los 10 últimos, el más reciente
        primero, sin repetir un proyecto (por uid), en ``projects/recent.json``."""
        with project_tmp() as tmp:
            data = userdata_mod.UserData(tmp)
            self.assertEqual(data.recent_projects(), [])
            for index in range(12):
                uid = f"00000000-0000-4000-8000-{index:012d}"
                data.add_recent(uid, f"P{index}", Path(f"C:/p/P{index}.gbproj"), f"2026-10-05T08:00:{index:02d}.000Z")
            data.add_recent(
                "00000000-0000-4000-8000-000000000005",
                "P5",
                Path("C:/otra/P5.gbproj"),
                "2026-10-05T09:00:00.000Z",
            )
            recent = data.recent_projects()
            self.assertEqual(len(recent), 10)
            self.assertEqual(recent[0].name, "P5")
            self.assertEqual(recent[0].path, Path("C:/otra/P5.gbproj"))
            self.assertEqual([item.name for item in recent[1:4]], ["P11", "P10", "P9"])
            self.assertEqual(len({item.uid for item in recent}), 10)
            self.assertTrue((tmp / "projects" / "recent.json").is_file())

    def test_unreadable_file_is_empty(self) -> None:
        """RF-002-08: un ``recent.json`` ilegible no impide trabajar: la lista sale vacía y
        se rehace al añadir."""
        with project_tmp() as tmp:
            target = tmp / "projects" / "recent.json"
            target.parent.mkdir(parents=True)
            target.write_text("{no es json", encoding="utf-8")
            data = userdata_mod.UserData(tmp)
            self.assertEqual(data.recent_projects(), [])
            data.add_recent(UID, "P", Path("C:/p/P.gbproj"), "2026-10-05T08:00:00.000Z")
            self.assertEqual([item.uid for item in data.recent_projects()], [UID])


if __name__ == "__main__":
    unittest.main()

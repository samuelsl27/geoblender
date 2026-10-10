# SPDX-License-Identifier: GPL-3.0-or-later
"""Carpetas de solo lectura en el ciclo de vida del proyecto (spec 008, T24; RF-008-15; S-3 del
plan 008; ADR-0025 §9; plan 008 §5.4.13).

Las carpetas de solo lectura (los expedientes de clientes) las declaran la variable de IMGA
``GEOBLENDER_READ_ONLY_DIRS`` y la preferencia de cada usuario (``core.paths.ReadOnlyDirs``,
T23); crear, abrir, migrar, sacar una copia local y publicar la reciben como argumento:

- crear un proyecto dentro de una se rechaza nombrando la carpeta, sin crear nada;
- uno que ya está dentro se abre en solo lectura (``ReadOnlyCode.READ_ONLY_FOLDER``) con el
  motivo, sin tomar el cerrojo, sin migrar y sin escribir ni un byte (listado, tamaños, fechas
  y huellas iguales);
- no se saca de él una copia local (habría que reservarlo), ni se saca una copia local dentro de
  una, ni se publica en él una copia local.

Todo igual si la carpeta se declara con su unidad, con su ruta UNC o con otras mayúsculas, en la
variable o en la preferencia. Las unidades y el recurso de red son simulados: una carpeta temporal
hace de recurso de red (:data:`SHARE`, que tiene asignada la unidad :data:`DRIVE`) con un
resolvedor inyectado; la prueba nunca toca la red.
"""

from __future__ import annotations

import ntpath
import os
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from tests.support.core_fixtures import (
    FakeClock,
    FakePids,
    make_schema_1,
    make_session,
    make_settings,
    project_tmp,
)
from tests.support.package import import_geoblender
from tests.support.provenance_checks import source_changes, source_state
from tests.support.trees import age_folders

create = import_geoblender("core.project.create")
open_mod = import_geoblender("core.project.open")
model = import_geoblender("core.project.model")
schema = import_geoblender("core.project.schema")
checkout = import_geoblender("core.project.checkout")
migrations = import_geoblender("core.project.migrations")
manifest = import_geoblender("core.project.manifest")
paths = import_geoblender("core.paths")
errors = import_geoblender("core.errors")
userdata_mod = import_geoblender("core.userdata")

ReadOnlyDirs = paths.ReadOnlyDirs
ReadOnlyCode = model.ReadOnlyCode
OpenMode = model.OpenMode

SESSION = make_session()
DRIVE = "Q:"  # unidad de red simulada: la prueba nunca la abre
SHARE = "\\\\servidor-prueba\\recurso"  # su recurso de red, también simulado
DOSSIERS = "expedientes"
READ_ONLY_TEXT = "una carpeta de solo lectura en las preferencias de Geoblender"


class ShareResolver:
    """Resolvedor de unidades simulado: la carpeta temporal ``backing`` es el recurso de red
    :data:`SHARE` (como una unidad asignada, cuya ruta canónica es la UNC), la unidad
    :data:`DRIVE` también, una ruta UNC queda como está y cualquier otra local se resuelve con
    ``canonical_path``. Nunca abre una ruta de red."""

    def __init__(self, backing: Path) -> None:
        self.backing = ntpath.normcase(os.fspath(paths.canonical_path(backing)))
        self.calls: list[str] = []

    def __call__(self, path: Path) -> Path:
        text = os.fspath(path)
        self.calls.append(text)
        if text[:2].upper() == DRIVE:
            return Path(SHARE + text[2:])
        if text.startswith(("\\\\", "//")):
            return Path(text)
        real = os.fspath(paths.canonical_path(path))
        folded = ntpath.normcase(real)
        if folded == self.backing or folded.startswith(self.backing + "\\"):
            return Path(SHARE + real[len(self.backing):])
        return Path(real)


class ReadOnlyLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = self.enterContext(project_tmp("geoblender-008-ro-"))
        self.backing = self.tmp / "recurso"
        self.dossiers = self.backing / DOSSIERS
        self.dossiers.mkdir(parents=True)
        self.outside = self.tmp / "proyectos"
        self.outside.mkdir()
        self.copies = self.tmp / "copias"
        self.copies.mkdir()
        self.userdata = userdata_mod.UserData(self.tmp / "datos_usuario")
        self.clock = FakeClock()
        self.pids = FakePids({SESSION.pid})
        self.resolver = ShareResolver(self.backing)

    # Ayudas -------------------------------------------------------------------------------

    def forms(self) -> list[tuple[str, ReadOnlyDirs]]:
        """La carpeta de los expedientes declarada de cuatro maneras (cada una sola)."""
        local = os.fspath(self.dossiers)
        declared = (
            ("unidad, en la variable", DRIVE + "\\" + DOSSIERS, ()),
            ("UNC, en la preferencia", None, (SHARE + "\\" + DOSSIERS,)),
            ("unidad en minúsculas y con barra final, en la preferencia", None,
             (DRIVE.lower() + "\\" + DOSSIERS.upper() + "\\",)),
            ("ruta local con otras mayúsculas, en la variable", local.swapcase(), ()),
        )
        return [
            (label, ReadOnlyDirs.from_sources(env, prefs, resolve=self.resolver))
            for label, env, prefs in declared
        ]

    def elsewhere(self) -> ReadOnlyDirs:
        """Una lista no vacía que no contiene ni el proyecto ni las copias locales."""
        return ReadOnlyDirs.from_sources(DRIVE + "\\otros", [SHARE + "\\clientes"],
                                         resolve=self.resolver)

    def make_project(self, parent: Path) -> Path:
        """Un proyecto cerrado en ``parent`` (antes de declarar la carpeta de solo lectura)."""
        created = create.create_project(parent, make_settings(), SESSION, self.userdata,
                                        clock=self.clock)
        created.project.close()
        return created.root

    def open(self, root: Path, read_only: ReadOnlyDirs, **kwargs):
        return open_mod.open_project(root, SESSION, self.userdata, clock=self.clock,
                                     pid_alive=self.pids, read_only=read_only, **kwargs)

    @contextmanager
    def frozen(self, *folders: Path) -> Iterator[None]:
        """Falla si en ``folders`` se crea, cambia o borra algo (también la fecha de una
        carpeta) mientras dura el bloque."""
        before = []
        for folder in folders:
            age_folders(folder)
            before.append(source_state(folder))
        yield
        for state in before:
            changes = source_changes(state, source_state(state.folder))
            self.assertEqual(changes, [], f"ha cambiado «{state.folder.name}»")

    def refused(self, code: str, dirs: ReadOnlyDirs, run) -> object:
        """Ejecuta ``run`` y comprueba el rechazo ``code`` nombrando la carpeta declarada."""
        with self.assertRaises(errors.ProjectError) as caught:
            run()
        error = caught.exception
        self.assertEqual(error.code, code, error.message)
        folder = os.fspath(dirs.folders[0])
        self.assertIn(f"«{folder}», {READ_ONLY_TEXT}", error.message)
        return error

    # Pruebas ------------------------------------------------------------------------------

    def test_create_inside_is_refused(self) -> None:
        """RF-008-15 (S-3): crear un proyecto dentro de una carpeta de solo lectura, en ella
        misma o en una subcarpeta (exista o no), declarada con su unidad, con su UNC o con otras
        mayúsculas, se rechaza nombrando la carpeta y sin crear nada; fuera de ella, con la misma
        lista, se crea en escritura."""
        (self.dossiers / "2026").mkdir()
        for label, dirs in self.forms():
            for parent in (self.dossiers, self.dossiers / "2026", self.dossiers / "nueva"):
                with self.subTest(form=label, parent=parent.name), self.frozen(self.backing):
                    error = self.refused(
                        "core.project_read_only_folder", dirs,
                        lambda: create.create_project(parent, make_settings(), SESSION,
                                                      self.userdata, clock=self.clock,
                                                      read_only=dirs))
                    self.assertIn("no se ha creado nada", error.message)
                    self.assertEqual(error.value, os.fspath(parent / "Cantera Prueba.gbproj"))
                    self.assertEqual(self.userdata.recent_projects(), [])
        every = ReadOnlyDirs(tuple(f for _, d in self.forms() for f in d.env_folders),
                             tuple(f for _, d in self.forms() for f in d.preference_folders),
                             resolve=self.resolver)
        created = create.create_project(self.outside, make_settings(), SESSION, self.userdata,
                                        clock=self.clock, read_only=every)
        self.assertEqual(created.project.mode, OpenMode.WRITE_LOCAL)
        created.project.close()

    def test_open_inside_is_read_only_without_writing(self) -> None:
        """RF-008-15 (S-3; ADR-0025 §9): un proyecto que está dentro de una carpeta de solo
        lectura se abre en solo lectura con el motivo «carpeta de solo lectura» (también si se
        pidió así), sin ``.lock`` y sin escribir ni un byte en la carpeta (listado, tamaños,
        fechas y huellas iguales) al abrirlo, leerlo, intentar escribir y cerrarlo; la inspección
        dice la carpeta. Por unidad, por UNC y sin distinguir mayúsculas."""
        root = self.make_project(self.dossiers)
        for label, dirs in self.forms():
            for want_write in (True, False):
                with self.subTest(form=label, want_write=want_write), self.frozen(self.backing):
                    folder = dirs.folders[0]
                    inspection = open_mod.inspect_project(
                        root, SESSION, self.userdata, clock=self.clock, pid_alive=self.pids,
                        read_only=dirs)
                    self.assertEqual(inspection.read_only_folder, folder)
                    result = self.open(root, dirs, want_write=want_write)
                    project = result.project
                    self.assertEqual(project.mode, OpenMode.READ_ONLY)
                    self.assertIs(project.read_only_reason, ReadOnlyCode.READ_ONLY_FOLDER)
                    self.assertTrue(project.status.message.startswith("Solo lectura: "))
                    self.assertIn(f"«{os.fspath(folder)}», {READ_ONLY_TEXT}",
                                  project.status.message)
                    self.assertFalse((root / ".lock").exists())
                    with project.read() as conn:
                        self.assertEqual(schema.read_project(conn).name, "Cantera Prueba")
                    with self.assertRaises(errors.ProjectError) as caught:
                        with project.write_transaction():
                            pass
                    self.assertEqual(caught.exception.code, "core.project_read_only")
                    self.assertEqual(project.cache_dir(), self.userdata.cache_dir(project.uid))
                    self.assertEqual(project.close(), ())
        # Sin carpetas de solo lectura (o con otras), el mismo proyecto se abre en escritura.
        for dirs in (None, self.elsewhere()):
            result = self.open(root, dirs)
            self.assertEqual(result.project.mode, OpenMode.WRITE_LOCAL)
            self.assertIsNone(open_mod.inspect_project(
                root, SESSION, self.userdata, clock=self.clock, pid_alive=self.pids,
                read_only=dirs).read_only_folder)
            result.project.close()

    def test_older_schema_is_neither_migrated_nor_written(self) -> None:
        """RF-008-15 (S-3; ADR-0025 §9): un proyecto del esquema 1 dentro de una carpeta de solo
        lectura se abre en solo lectura por la carpeta (no «sin migrar») y no se migra: migrar
        se rechaza nombrando la carpeta antes de tomar el cerrojo, sin copia previa junto a él
        y sin cambiar nada."""
        root = self.make_project(self.dossiers)
        make_schema_1(root)
        for label, dirs in self.forms():
            with self.subTest(form=label), self.frozen(self.backing):
                result = self.open(root, dirs)
                self.assertIs(result.project.read_only_reason, ReadOnlyCode.READ_ONLY_FOLDER)
                self.assertEqual(result.project.schema_version, 1)
                result.project.close()
                error = self.refused(
                    "core.migration_read_only_folder", dirs,
                    lambda: list(migrations.migrate_steps(
                        root, SESSION, self.userdata, clock=self.clock, pid_alive=self.pids,
                        read_only=dirs)))
                self.assertIn("no se migra", error.message)
                self.assertEqual(sorted(p.name for p in self.dossiers.iterdir()),
                                 ["Cantera Prueba.gbproj"])

    def test_checkout_from_inside_is_refused(self) -> None:
        """RF-008-15 (S-3; ADR-0025 §9): no se saca una copia local de un proyecto que está
        dentro de una carpeta de solo lectura (habría que reservarlo con su cerrojo): se
        rechaza nombrando la carpeta, sin reserva, sin copia y sin registro en el equipo."""
        root = self.make_project(self.dossiers)
        uid = manifest.read_manifest(root).project_uid
        for label, dirs in self.forms():
            with self.subTest(form=label), self.frozen(self.backing, self.copies):
                self.refused(
                    "core.checkout_read_only_folder", dirs,
                    lambda: list(checkout.checkout_steps(
                        root, self.copies, SESSION, self.userdata, clock=self.clock,
                        pid_alive=self.pids, read_only=dirs)))
                self.assertIsNone(self.userdata.checkout_record(uid))

    def test_checkout_into_one_is_refused(self) -> None:
        """RF-008-15 (S-3): sacar una copia local dentro de una carpeta de solo lectura se
        rechaza nombrando la carpeta, sin reservar el original y sin copiar nada."""
        root = self.make_project(self.outside)
        dest = self.dossiers / "copias"
        dest.mkdir()
        for label, dirs in self.forms():
            with self.subTest(form=label), self.frozen(self.backing, self.outside):
                self.refused(
                    "core.checkout_dest_read_only", dirs,
                    lambda: list(checkout.checkout_steps(
                        root, dest, SESSION, self.userdata, clock=self.clock,
                        pid_alive=self.pids, read_only=dirs)))
                self.assertFalse((root / ".lock").exists())

    def test_publish_into_one_is_refused(self) -> None:
        """RF-008-15 (S-3; ADR-0025 §9): si el original de una copia local está dentro de una
        carpeta de solo lectura (declarada después de sacarla), publicar se rechaza nombrando la
        carpeta: ni ``.publicando`` ni ``.anterior``, el original sigue reservado e intacto y la
        copia local sigue abierta en escritura, intacta y con su registro en el equipo."""
        root = self.make_project(self.dossiers)
        result = None
        for step in checkout.checkout_steps(root, self.copies, SESSION, self.userdata,
                                            clock=self.clock, pid_alive=self.pids,
                                            read_only=self.elsewhere()):
            result = step.result if step.result is not None else result
        local = result.opened.project
        self.addCleanup(local.close)
        self.assertEqual(local.mode, OpenMode.CHECKOUT)
        record = self.userdata.checkout_record(local.uid)
        for label, dirs in self.forms():
            with self.subTest(form=label), self.frozen(self.backing, self.copies):
                error = self.refused(
                    "core.publish_read_only_folder", dirs,
                    lambda: list(checkout.publish_steps(
                        local, SESSION, self.userdata, clock=self.clock, pid_alive=self.pids,
                        read_only=dirs)))
                self.assertIn("La copia local se conserva intacta", error.message)
                self.assertTrue(local.writable)
                self.assertEqual(self.userdata.checkout_record(local.uid), record)
                self.assertEqual(sorted(p.name for p in self.dossiers.iterdir()),
                                 ["Cantera Prueba.gbproj"])


if __name__ == "__main__":
    unittest.main()

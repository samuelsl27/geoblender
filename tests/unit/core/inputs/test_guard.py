# SPDX-License-Identifier: GPL-3.0-or-later
"""Carpetas de solo lectura y guarda de las escrituras (spec 008, T23; RF-008-14, RF-008-15; S-3
del plan 008; ADR-0025 §9; plan 008 §5.3.1 y §5.4.13).

- ``core.paths.ReadOnlyDirs`` une las carpetas de solo lectura de la variable de IMGA
  ``GEOBLENDER_READ_ONLY_DIRS`` (lista con «;») y las de la preferencia de cada usuario; una ruta
  está dentro de una de ellas si lo está con su unidad o con su ruta UNC (el resolvedor de
  unidades se inyecta: la prueba no toca la red), sin distinguir mayúsculas. Si la lista
  combinada está vacía, hay aviso.
- ``core.inputs.check_write_target`` rechaza, nombrando la entrada o la carpeta y sin crear
  nada, una escritura de Geoblender en la fuente de una entrada registrada, en la carpeta que la
  contiene (fuera del proyecto) o en una carpeta de solo lectura.

Cada prueba de la guarda crea su proyecto sintético (esquema 2) con un reloj simulado y registra
el límite «Limites_v1» desde una carpeta «Entregas» junto a él. Ninguna ruta de un equipo real:
las unidades y los recursos de red de la prueba no existen y nunca se abren.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import unittest
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any

from tests.support import provenance_data as data
from tests.support.package import import_geoblender
from tests.support.provenance_checks import assert_source_untouched
from tests.support.trees import age_folders
from tests.unit.core.inputs.test_registry import NOT_APPLICABLE, SOURCE, InputsCase

inputs = import_geoblender("core.inputs")
guard = import_geoblender("core.inputs.guard")
model = import_geoblender("core.inputs.model")
registry = import_geoblender("core.inputs.registry")
content = import_geoblender("core.content")
hashing = import_geoblender("core.hashing")
messages = import_geoblender("core.provenance.messages")
paths = import_geoblender("core.paths")

ProvenanceError = messages.ProvenanceError
ReadOnlyDirs = paths.ReadOnlyDirs

DRIVE = "Q:"  # una unidad de red simulada (la prueba nunca la abre)
SHARE = "\\\\servidor-prueba\\recurso"  # su recurso de red, también simulado
DOSSIERS_DRIVE = "Q:\\expedientes"
DOSSIERS_UNC = SHARE + "\\expedientes"
FOLDER_CODE = "core.write_target_source_folder"
SOURCE_CODE = "core.write_target_source"
READ_ONLY_CODE = "core.write_target_read_only"
DELIVERIES_TEXT = ("No se puede escribir en la carpeta «Entregas»: contiene la fuente de la "
                   "entrada «Limites_v1».")
EMPTY_TEXT = ("No hay ninguna carpeta de solo lectura: ni la variable GEOBLENDER_READ_ONLY_DIRS "
              "ni las preferencias de Geoblender declaran ninguna, así que los expedientes de "
              "clientes no están protegidos de las escrituras de Geoblender.")


def _read_only_text(folder: str) -> str:
    return f"La carpeta «{folder}» es de solo lectura en las preferencias de Geoblender."


class DriveResolver:
    """Resolvedor de unidades simulado: la unidad :data:`DRIVE` es el recurso :data:`SHARE`, una
    ruta UNC queda como está y una local (las carpetas temporales de la prueba), si se admite,
    se resuelve con ``canonical_path``. Anota lo que resuelve y nunca abre una ruta de red."""

    def __init__(self, *, local: bool = False, fail: bool = False) -> None:
        self.local = local
        self.fail = fail
        self.calls: list[str] = []

    def __call__(self, path: Path) -> Path:
        text = os.fspath(path)
        self.calls.append(text)
        if self.fail:
            raise OSError(53, "no se encuentra la ruta de red (simulado)")
        if text[:2].upper() == DRIVE:
            return Path(SHARE + text[2:])
        if text.startswith(("\\\\", "//")):
            return Path(text)
        if not self.local:
            raise AssertionError(f"el resolvedor simulado no resuelve rutas locales: {text}")
        return paths.canonical_path(path)


def _digest(label: str, kind: str) -> Any:
    """Los hashes simulados de una fuente sin coordenadas cuyos datos simula ``label``."""
    declarations = model.input_declarations(NOT_APPLICABLE, NOT_APPLICABLE, {})
    data_sha = hashing.sha256_bytes(label.encode("utf-8"))
    return content.ContentDigest(data_sha, content.content_sha256(kind, declarations, data_sha),
                                 content.NORMALIZER, SOURCE.id)


class ReadOnlyDirsTest(unittest.TestCase):
    def test_variable_and_preference_add_up(self) -> None:
        """RF-008-15 (S-3): las carpetas de la variable ``GEOBLENDER_READ_ONLY_DIRS`` (separadas
        por «;», con espacios, comillas, barras finales y huecos) y las de la preferencia se
        suman, sin repetir la misma carpeta escrita con otras mayúsculas; cada una protege lo
        que tiene dentro y nada más."""
        self.assertEqual(paths.READ_ONLY_DIRS_ENV, "GEOBLENDER_READ_ONLY_DIRS")
        resolver = DriveResolver()
        dirs = ReadOnlyDirs.from_sources(
            ' Q:\\expedientes ; "Q:\\otros\\" ;; ', ["Q:\\cliente", "  ", "q:\\EXPEDIENTES\\"],
            resolve=resolver,
        )
        self.assertEqual(dirs.env_folders, (Path("Q:\\expedientes"), Path("Q:\\otros")))
        self.assertEqual(dirs.preference_folders,
                         (Path("Q:\\cliente"), Path("q:\\EXPEDIENTES")))
        self.assertEqual(dirs.folders,
                         (Path("Q:\\expedientes"), Path("Q:\\otros"), Path("Q:\\cliente")))
        self.assertEqual(dirs.ignored, ())
        self.assertFalse(dirs.empty)
        for target, folder in (
            ("Q:\\expedientes\\plano.dxf", "Q:\\expedientes"),
            ("Q:\\otros\\2026\\informe.pdf", "Q:\\otros"),
            ("Q:\\cliente\\a\\b\\c.csv", "Q:\\cliente"),
            ("Q:\\cliente", "Q:\\cliente"),
        ):
            with self.subTest(target=target):
                self.assertEqual(dirs.contains(target), Path(folder))
                self.assertEqual(dirs.contains(Path(target)), Path(folder))
        for target in ("Q:\\plano.dxf", "Q:\\clientes\\x.dxf", "Q:\\otro\\expedientes\\x.dxf"):
            with self.subTest(target=target):
                self.assertIsNone(dirs.contains(target))
        # Solo la variable o solo la preferencia: cada una protege por sí sola.
        only_env = ReadOnlyDirs.from_sources("Q:\\expedientes", [], resolve=resolver)
        only_preference = ReadOnlyDirs.from_sources(None, ("Q:\\expedientes",), resolve=resolver)
        for dirs in (only_env, only_preference):
            self.assertEqual(dirs.contains("Q:\\expedientes\\x.dxf"), Path("Q:\\expedientes"))
            self.assertEqual(guard.read_only_warnings(dirs), ())
        self.assertEqual((only_env.env_folders, only_env.preference_folders),
                         ((Path("Q:\\expedientes"),), ()))
        self.assertEqual((only_preference.env_folders, only_preference.preference_folders),
                         ((), (Path("Q:\\expedientes"),)))

    def test_drive_and_unc_without_case(self) -> None:
        """RF-008-15 (S-3; ADR-0025 §9): una carpeta declarada con su unidad protege también su
        ruta UNC, y al revés, sin distinguir mayúsculas, con «/» o con «..»; una carpeta vecina
        con el mismo comienzo, la carpeta madre u otro recurso no. El resolvedor de unidades
        inyectado solo recibe la unidad y las rutas UNC: la prueba no toca la red."""
        resolver = DriveResolver()
        by_drive = ReadOnlyDirs.from_sources(DOSSIERS_DRIVE, [], resolve=resolver)
        by_unc = ReadOnlyDirs.from_sources(None, [DOSSIERS_UNC], resolve=resolver)
        inside = (
            SHARE.upper() + "\\EXPEDIENTES\\Cliente\\plano.dxf",
            "q:\\Expedientes\\cliente\\plano.dxf",
            "Q:/expedientes/cliente/plano.dxf",
            "Q:\\otra\\..\\expedientes\\plano.dxf",
            "//servidor-prueba/recurso/expedientes/plano.dxf",
            DOSSIERS_DRIVE,
            DOSSIERS_UNC + "\\",
        )
        outside = (
            "Q:\\expedientes2\\plano.dxf",
            "Q:\\plano.dxf",
            "Q:\\",
            SHARE + "\\otros\\expedientes\\plano.dxf",
            "\\\\otro-servidor\\recurso\\expedientes\\plano.dxf",
            SHARE + "2\\expedientes\\plano.dxf",
        )
        for dirs, declared in ((by_drive, DOSSIERS_DRIVE), (by_unc, DOSSIERS_UNC)):
            for target in inside:
                with self.subTest(declared=declared, target=target):
                    self.assertEqual(dirs.contains(target), Path(declared))
            for target in outside:
                with self.subTest(declared=declared, target=target):
                    self.assertIsNone(dirs.contains(target))
        # Toda la unidad o todo el recurso de red, declarados con su barra final.
        whole_drive = ReadOnlyDirs.from_sources("Q:\\", [], resolve=resolver)
        whole_share = ReadOnlyDirs.from_sources(None, [SHARE + "\\"], resolve=resolver)
        for dirs, declared in ((whole_drive, "Q:\\"), (whole_share, SHARE + "\\")):
            for target in ("Q:\\expedientes\\plano.dxf", SHARE + "\\plano.dxf", "q:\\"):
                with self.subTest(declared=declared, target=target):
                    self.assertEqual(dirs.contains(target), Path(declared))
            self.assertIsNone(dirs.contains("\\\\otro-servidor\\recurso\\plano.dxf"))

        def junction(path: Path) -> Path:
            """«Q:\\enlace» es un enlace a los expedientes: su ruta resuelta lleva «..»."""
            text = os.fspath(path)
            if text.lower().startswith("q:\\enlace"):
                return Path(SHARE + "\\otra\\..\\expedientes" + text[len("Q:\\enlace"):])
            return resolver(path)

        linked = ReadOnlyDirs.from_sources(None, [DOSSIERS_UNC], resolve=junction)
        self.assertEqual(linked.contains("Q:\\enlace\\plano.dxf"), Path(DOSSIERS_UNC))
        self.assertTrue(resolver.calls)
        for call in resolver.calls:
            self.assertTrue(call[:2].upper() == DRIVE or call.startswith(("\\\\", "//")), call)

    def test_resolver_failure_keeps_the_declared_form(self) -> None:
        """RF-008-15: si el resolvedor no puede resolver (la red no responde), la carpeta sigue
        protegida en la forma en que se declaró."""
        dirs = ReadOnlyDirs.from_sources(DOSSIERS_DRIVE, [], resolve=DriveResolver(fail=True))
        self.assertEqual(dirs.contains("q:\\EXPEDIENTES\\plano.dxf"), Path(DOSSIERS_DRIVE))
        self.assertIsNone(dirs.contains(DOSSIERS_UNC + "\\plano.dxf"))

    def test_empty_list_and_ignored_entries_warn(self) -> None:
        """RF-008-15 (S-3): con la variable y la preferencia vacías hay aviso; una carpeta que
        no es una ruta completa (relativa, sin barra tras la unidad o un servidor sin recurso)
        no se tiene en cuenta y también se avisa de ella."""
        for env, preferences in ((None, []), ("", ["", "  "]), (" ; ;", ())):
            with self.subTest(env=env, preferences=preferences):
                dirs = ReadOnlyDirs.from_sources(env, preferences, resolve=DriveResolver())
                self.assertTrue(dirs.empty)
                self.assertEqual((dirs.folders, dirs.ignored), ((), ()))
                self.assertIsNone(dirs.contains("Q:\\expedientes\\plano.dxf"))
                self.assertEqual(guard.read_only_warnings(dirs), (EMPTY_TEXT,))
        dirs = ReadOnlyDirs.from_sources("expedientes;Q:datos;\\solo", ["\\\\servidor"],
                                         resolve=DriveResolver())
        self.assertTrue(dirs.empty)
        self.assertEqual(dirs.ignored, ("expedientes", "Q:datos", "\\solo", "\\\\servidor"))
        ignored = [
            f"No se tiene en cuenta la carpeta de solo lectura «{entry}»: no es una ruta "
            "completa, con su unidad o de red."
            for entry in dirs.ignored
        ]
        self.assertEqual(guard.read_only_warnings(dirs), (*ignored, EMPTY_TEXT))
        self.assertEqual(
            guard.read_only_warnings(dirs, "en")[-1],
            "There is no read-only folder: neither the variable GEOBLENDER_READ_ONLY_DIRS nor "
            "the Geoblender preferences declare any, so client dossiers are not protected from "
            "Geoblender writes.",
        )
        mixed = ReadOnlyDirs.from_sources("relativa", [DOSSIERS_DRIVE], resolve=DriveResolver())
        self.assertFalse(mixed.empty)
        self.assertEqual(guard.read_only_warnings(mixed), (ignored[0].replace(
            "«expedientes»", "«relativa»"),))

    def test_wrong_arguments(self) -> None:
        """RF-008-15: una lista mal formada o una ruta vacía son errores del programa (una ruta
        vacía sería la carpeta de trabajo)."""
        for env, preferences in ((5, []), (None, "Q:\\expedientes"), (None, [5]),
                                 (None, None)):
            with self.subTest(env=env, preferences=preferences), self.assertRaises(TypeError):
                ReadOnlyDirs.from_sources(env, preferences)
        dirs = ReadOnlyDirs.from_sources(DOSSIERS_DRIVE, [], resolve=DriveResolver())
        with self.assertRaises(ValueError):
            dirs.contains("")
        with self.assertRaises(TypeError):
            dirs.contains(None)


class GuardTest(InputsCase):
    """Un proyecto con la entrada «Limites_v1» registrada desde la carpeta «Entregas», junto a
    él (``tmp/Entregas``; el proyecto está en ``tmp/proyectos``)."""

    def setUp(self) -> None:
        super().setUp()
        self.sources = self.tmp / "Entregas"
        self.sources.mkdir()
        shutil.copyfile(data.DATA_DIR / data.BOUNDARY_V1, self.sources / data.BOUNDARY_V1)
        self.limits = self.register(self.boundary())
        self.no_dirs = ReadOnlyDirs.from_sources(None, [])

    # --- Ayudas -----------------------------------------------------------------------------

    def check(self, target: Any, read_only: Any = None, **kw: Any) -> None:
        guard.check_write_target(target, project=kw.pop("project", self.project),
                                 read_only=self.no_dirs if read_only is None else read_only,
                                 **kw)

    def blocked(self, code: str, target: Any, read_only: Any = None, *,
                watch: Path | None = None, **kw: Any) -> Any:
        """Escribir en ``target`` se rechaza con ``code`` sin crear ni cambiar nada en la carpeta
        vigilada (``watch``, por defecto «Entregas») ni en el proyecto."""
        folder = self.sources if watch is None else watch
        before = self.snapshot()
        age_folders(folder)
        with assert_source_untouched(folder), self.assertRaises(ProvenanceError) as caught:
            self.check(target, read_only, **kw)
        self.assertEqual(caught.exception.code, code, str(caught.exception))
        self.assertEqual(self.snapshot(), before)
        return caught.exception

    def accepted(self, *targets: Any, read_only: Any = None, **kw: Any) -> None:
        for target in targets:
            with self.subTest(target=str(target)):
                self.assertIsNone(self.check(target, read_only, **kw))

    def layer(self, path: Path, name: str) -> Any:
        """La capa ``limites`` del GeoPackage ``path`` como la entrada ``name``."""
        saved, self.sources = self.sources, path.parent
        try:
            return self.boundary(path.name, name=name)
        finally:
            self.sources = saved

    def document(self, files: list[model.SourceFile], name: str, path: Path) -> Any:
        """Una entrada documental de los ficheros ``files`` con la huella de ``path``."""
        found = path.stat()
        return model.InputSpec(
            name, "document", "res", SOURCE.id, files=files,
            file_prints=[model.SourcePrint(hashing.sha256_file(path), size=found.st_size,
                                           mtime_ns=found.st_mtime_ns)],
            digest=_digest(name, "document"), crs_h=NOT_APPLICABLE, crs_v=NOT_APPLICABLE,
        )

    # --- Pruebas ----------------------------------------------------------------------------

    def test_source_and_its_folder_are_refused(self) -> None:
        """RF-008-15, RF-008-14: escribir sobre la fuente de «Limites_v1», junto a ella (un
        ``-wal``, un plano), en una subcarpeta nueva o en la propia carpeta «Entregas» (también
        con otras mayúsculas o con «/») se rechaza con el texto de la spec §8, que nombra la
        carpeta y la entrada, sin crear ni cambiar nada en «Entregas» ni en el proyecto; una
        carpeta vecina con el mismo comienzo, la carpeta madre o el propio proyecto, no."""
        source = self.sources / data.BOUNDARY_V1
        for target in (
            source,
            str(source),
            self.sources / (data.BOUNDARY_V1 + "-wal"),
            self.sources / "plano.dxf",
            self.sources / "planos" / "2026" / "plano.dxf",
            self.sources,
            str(self.sources).upper() + "/PLANO.DXF",
        ):
            with self.subTest(target=str(target)):
                error = self.blocked(FOLDER_CODE, target)
                self.assertEqual(str(error), DELIVERIES_TEXT)
                self.assertEqual(error.values, {"folder": "Entregas", "name": "Limites_v1"})
        self.assertFalse((self.sources / "planos").exists())
        self.assertEqual(
            messages.render(FOLDER_CODE, language="en", **error.values),
            "Cannot write in folder «Entregas»: it contains the source of input «Limites_v1».",
        )
        self.accepted(self.tmp / "Entregas2" / "plano.dxf", self.tmp / "salidas" / "plano.dxf",
                      self.tmp / "plano.dxf", self.project.root / "planos" / "plano.dxf",
                      self.project.root)
        self.assertFalse((self.tmp / "salidas").exists())
        # Con la red caída (el resolvedor falla), cuenta la forma absoluta de cada ruta.
        down = ReadOnlyDirs.from_sources(None, [], resolve=DriveResolver(fail=True))
        self.blocked(FOLDER_CODE, self.sources / "plano.dxf", down)
        self.accepted(self.tmp / "salidas" / "plano.dxf", read_only=down)
        # Sigue protegida aunque se descarte: su fuente es un fichero del usuario.
        self.mark(self.limits.uid, "discarded", "Importación equivocada")
        self.blocked(FOLDER_CODE, self.sources / "plano.dxf")

    def test_sources_inside_or_around_the_project(self) -> None:
        """RF-008-15: si la carpeta de una fuente contiene el proyecto, se rechaza escribir en
        ella fuera del proyecto, pero no dentro de él; de una fuente que está dentro del
        proyecto solo se rechaza el propio fichero, nombrando la entrada."""
        parent = self.project.root.parent  # «proyectos», donde está el proyecto
        around = parent / data.BOUNDARY_V2
        shutil.copyfile(data.DATA_DIR / data.BOUNDARY_V2, around)
        self.register(self.layer(around, "Limites_v2"))
        inner = self.project.root / "documentos" / "informe.pdf"
        inner.parent.mkdir()
        shutil.copyfile(data.DATA_DIR / data.REPORT, inner)
        located = registry.locate_source(inner, self.project, self.userdata)
        self.assertEqual(located.anchor, model.FileAnchor.PROJECT)
        self.register(self.document([located], "Informe", inner))
        error = self.blocked(FOLDER_CODE, parent / "plano.dxf", watch=parent)
        self.assertEqual(str(error), "No se puede escribir en la carpeta «proyectos»: contiene "
                                     "la fuente de la entrada «Limites_v2».")
        error = self.blocked(SOURCE_CODE, inner, watch=inner.parent)
        self.assertEqual(str(error),
                         "No se puede escribir en «informe.pdf»: es la fuente de la entrada "
                         "«Informe».")
        self.assertEqual(error.values, {"file": "informe.pdf", "name": "Informe"})
        self.accepted(self.project.root / "planos" / "plano.dxf",
                      inner.parent / "otro.pdf", self.project.root / "documentos")

    def test_external_sources(self) -> None:
        """RF-008-15: la fuente de otro volumen se protege donde está anotada en este equipo;
        una sin anotación («no localizable», RF-008-13) no impide nada ni es un error."""
        other = self.tmp / "Otro volumen"
        other.mkdir()
        collars = other / "collares.csv"
        collars.write_bytes(data.collars_csv(1))
        self.userdata.set_external_ref(self.project.uid, "ref-anotada", collars)
        noted = model.SourceFile("collares.csv", "main", "external", ref_uid="ref-anotada")
        lost = model.SourceFile("perdido.csv", "main", "external", ref_uid="ref-sin-anotar")
        self.register(self.document([noted], "Collares", collars))
        self.register(self.document([lost], "Perdido", collars))
        error = self.blocked(FOLDER_CODE, other / "plano.dxf", watch=other)
        self.assertEqual(str(error), "No se puede escribir en la carpeta «Otro volumen»: "
                                     "contiene la fuente de la entrada «Collares».")
        self.accepted(self.tmp / "salidas" / "perdido.csv")

    def test_read_only_folders(self) -> None:
        """RF-008-15 (S-3): escribir dentro de una carpeta de solo lectura (de la variable o de
        la preferencia) o en ella misma se rechaza nombrándola tal como se declaró y sin crear
        nada; también por su ruta UNC si se declaró con su unidad, y al revés, sin tocar la red.
        Va antes que la fuente: en un expediente con entregas se nombra la carpeta declarada."""
        dossiers = self.tmp / "expedientes"
        (dossiers / "cliente").mkdir(parents=True)
        (dossiers / "cliente" / "acta.pdf").write_bytes(b"%PDF-1.4 acta\n")
        for dirs in (ReadOnlyDirs.from_sources(str(dossiers), []),
                     ReadOnlyDirs.from_sources(None, [str(dossiers) + "\\"])):
            for target in (dossiers / "cliente" / "plano.dxf", dossiers / "nuevo" / "plano.dxf",
                           dossiers):
                with self.subTest(target=str(target)):
                    error = self.blocked(READ_ONLY_CODE, target, dirs, watch=dossiers)
                    self.assertEqual(str(error), _read_only_text(str(dossiers)))
            self.accepted(self.tmp / "salidas" / "plano.dxf", read_only=dirs)
        self.assertEqual(
            messages.render(READ_ONLY_CODE, language="en", folder="Q:\\x"),
            "Folder «Q:\\x» is read-only in the Geoblender preferences.",
        )
        # Unidad y UNC con el resolvedor simulado (las rutas locales, con el de verdad).
        resolver = DriveResolver(local=True)
        by_drive = ReadOnlyDirs.from_sources(DOSSIERS_DRIVE, [], resolve=resolver)
        by_unc = ReadOnlyDirs.from_sources(DOSSIERS_UNC, [], resolve=resolver)
        for dirs, target, declared in (
            (by_drive, SHARE.upper() + "\\EXPEDIENTES\\cliente\\plano.dxf", DOSSIERS_DRIVE),
            (by_unc, "q:\\expedientes\\cliente\\plano.dxf", DOSSIERS_UNC),
        ):
            with self.subTest(declared=declared):
                error = self.blocked(READ_ONLY_CODE, target, dirs)
                self.assertEqual(str(error), _read_only_text(declared))
        self.accepted(SHARE + "\\otros\\plano.dxf", "Q:\\otros\\plano.dxf", read_only=by_drive)
        for call in resolver.calls:  # la red, nunca: solo las simuladas o las locales
            self.assertTrue(call[:2].upper() == DRIVE or call.startswith("\\\\")
                            or Path(call).is_relative_to(self.tmp), call)
        # Un expediente que contiene la fuente de una entrada: se nombra la carpeta declarada.
        dirs = ReadOnlyDirs.from_sources(None, [str(self.sources)])
        error = self.blocked(READ_ONLY_CODE, self.sources / "plano.dxf", dirs)
        self.assertEqual(str(error), _read_only_text(str(self.sources)))

    def test_without_project_or_inputs(self) -> None:
        """RF-008-15: sin proyecto solo cuentan las carpetas de solo lectura; un proyecto sin
        las tablas de las entradas (esquema 1, en solo lectura) no tiene fuentes que proteger;
        con la conexión de quien llama se ven sus entradas."""
        dossiers = ReadOnlyDirs.from_sources(str(self.tmp / "expedientes"), [])
        self.blocked(READ_ONLY_CODE, self.tmp / "expedientes" / "plano.dxf", dossiers,
                     project=None)
        self.accepted(self.sources / "plano.dxf", read_only=dossiers, project=None)
        # closing: el «with» de una conexión no la cierra (docs/trampas.md), y el aviso de la
        # conexión abierta saltaría en otra prueba de la misma parte (test_readers).
        with closing(sqlite3.connect(":memory:")) as empty:
            self.accepted(self.sources / "plano.dxf", conn=empty)
        with self.project.read() as conn:
            self.blocked(FOLDER_CODE, self.sources / "plano.dxf", conn=conn)

    def test_wrong_arguments(self) -> None:
        """RF-008-15: sin las carpetas de solo lectura, o con una ruta vacía o que no es una
        ruta, es un error del programa, no un permiso."""
        cases: tuple[tuple[type[BaseException], Callable[[], Any]], ...] = (
            (TypeError, lambda: guard.check_write_target(self.sources / "x", project=self.project,
                                                         read_only=None)),
            (ValueError, lambda: self.check("")),
            (TypeError, lambda: self.check(None)),
            (TypeError, lambda: self.check(5)),
        )
        for error, work in cases:
            with self.subTest(error=error), self.assertRaises(error):
                work()

    def test_public_api(self) -> None:
        """RF-008-15: ``core.inputs`` reexporta la guarda y los avisos; ``core.paths``, las
        carpetas de solo lectura y el nombre de su variable."""
        self.assertIs(inputs.check_write_target, guard.check_write_target)
        self.assertIs(inputs.read_only_warnings, guard.read_only_warnings)
        self.assertIs(paths.ReadOnlyDirs, ReadOnlyDirs)
        for code in (FOLDER_CODE, SOURCE_CODE, READ_ONLY_CODE, "core.read_only_dirs_empty",
                     "core.read_only_dir_ignored"):
            self.assertIn(code, messages.MESSAGES)
